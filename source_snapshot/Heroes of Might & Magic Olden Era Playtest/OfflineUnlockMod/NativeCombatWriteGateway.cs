using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.InteropServices;
using HarmonyLib;
using Il2CppInterop.Runtime.InteropTypes;

namespace OfflineUnlockMod;

internal sealed class Homm3MovementRollbackSnapshot
{
	internal object Unit;
	internal object BattleLogic;
	internal object SourceHex;
	internal object DestinationHex;
}

/// <summary>
/// Sole native write gateway for direct-state mechanics. Adapters prepare and
/// journal typed mutations; only this class may modify native members,
/// collections, committed damage, Focus, cooldowns, buffs, or occupancy.
/// </summary>
internal static class NativeCombatWriteGateway
{
	private sealed class BoundMember
	{
		internal FieldInfo Field;
		internal PropertyInfo Property;

		internal object Read(object target)
		{
			return Field != null ? Field.GetValue(target) : Property.GetValue(target, null);
		}

		internal void Write(object target, object value)
		{
			if (Field != null)
				Field.SetValue(target, value);
			else
				Property.SetValue(target, value, null);
		}
	}

	private static readonly object Gate = new();
	private static readonly Dictionary<string, BoundMember> Members = new(StringComparer.Ordinal);
	private static readonly HashSet<Homm3DirectStateAdapterId> PreparedAdapters = new();
	private static readonly HashSet<Homm3DirectStateAdapterId> PrepareHonestyLogged = new();
	private static bool _movementSurfacePrepared;
	private static ICombatWriteBackend _writeBackend = LiveCombatWriteBackend.Instance;

	internal static bool PreparedMovementSurface => _movementSurfacePrepared;

	internal static void UseWriteBackend(ICombatWriteBackend backend)
	{
		_writeBackend = backend ?? LiveCombatWriteBackend.Instance;
	}

	internal static void UseLiveWriteBackend()
	{
		_writeBackend = LiveCombatWriteBackend.Instance;
	}

	internal static ICombatWriteBackend ActiveWriteBackend => _writeBackend;

	internal static bool TryPrepareAdapter(Homm3DirectStateAdapterId adapterId, out string failReason)
	{
		lock (Gate)
		{
			if (PreparedAdapters.Contains(adapterId))
			{
				failReason = null;
				return true;
			}
		}

		bool prepared;
		switch (adapterId)
		{
			case Homm3DirectStateAdapterId.None:
				failReason = "AdapterId.None cannot be prepared";
				return false;
			case Homm3DirectStateAdapterId.Damage:
			case Homm3DirectStateAdapterId.Cast:
			case Homm3DirectStateAdapterId.NestedDamage:
			case Homm3DirectStateAdapterId.Kill:
			case Homm3DirectStateAdapterId.AllyDeath:
			case Homm3DirectStateAdapterId.ActionQueue:
			case Homm3DirectStateAdapterId.TurnOrder:
			case Homm3DirectStateAdapterId.Aura:
			case Homm3DirectStateAdapterId.Corpse:
			case Homm3DirectStateAdapterId.Trap:
				// Manager / deferred-native families: no live surface bind at prepare time.
				LogPrepareHonestyOnce(adapterId, "manager-or-deferred-native");
				prepared = true;
				failReason = null;
				break;
			case Homm3DirectStateAdapterId.Focus:
				prepared = Homm3FocusNativeAdapter.TryResolve(out failReason);
				break;
			case Homm3DirectStateAdapterId.Cooldown:
				prepared = TryPrepareCooldownStorage(out failReason);
				break;
			case Homm3DirectStateAdapterId.Status:
				// The declared policy is ManagerAuthoritativeNoNativeInventory.
				// Native buff surfaces are deliberately not an activation dependency.
				LogPrepareHonestyOnce(adapterId, "managerAuthoritativeNoNativeInventory");
				prepared = true;
				failReason = null;
				break;
			case Homm3DirectStateAdapterId.Movement:
				prepared = TryPrepareMovement(out failReason);
				break;
			case Homm3DirectStateAdapterId.Summon:
				prepared = TryPrepareSummon(out failReason);
				break;
			default:
				prepared = false;
				failReason = "unknown direct-state adapter " + adapterId;
				break;
		}

		if (!prepared)
			return false;
		lock (Gate)
			PreparedAdapters.Add(adapterId);
		return true;
	}

	internal static bool TryCommitPreparedDamage(ref int damage, PreparedDamageMutation mutation)
	{
		return _writeBackend.TryCommitPreparedDamage(ref damage, mutation);
	}

	internal static bool TryCommitPreparedDamageLive(ref int damage, PreparedDamageMutation mutation)
	{
		if (!mutation.IsValid || damage != mutation.ExpectedDamage)
			return false;
		damage = mutation.NewDamage;
		return true;
	}

	internal static bool TryGrantFocus(object side, int delta, out string failReason)
	{
		return Homm3FocusNativeAdapter.TryGrantFocusToSide(side, delta, out failReason);
	}

	internal static bool TryResolveFocusManager(object side, out object manager, out string failReason)
	{
		manager = null;
		if (side == null)
		{
			failReason = "Focus side is null";
			return false;
		}
		if (!TryReadExactMember(side, GameSymbols.FocusLaws.SideEnergyManagerMembers, out manager)
		    || manager == null)
		{
			failReason = "Focus side has no exact energy manager";
			return false;
		}
		failReason = null;
		return true;
	}

	internal static bool TryResolveUnitAbility(
		object unit,
		object abilityType,
		object abilityIndex,
		out object ability,
		out string failReason)
	{
		ability = null;
		if (unit == null || abilityType == null || abilityIndex == null)
		{
			failReason = "unit ability resolution requires unit, ability type, and ability index";
			return false;
		}
		if (!TryReadExactMember(unit, GameSymbols.DirectStateLaws.UnitAbilityManagerMembers, out var manager)
		    || manager == null)
		{
			failReason = "unit has no exact ability manager";
			return false;
		}
		MethodInfo resolver = null;
		foreach (var name in GameSymbols.DirectStateLaws.AbilityManagerResolve.NameHints)
		{
			var candidate = manager.GetType().GetMethod(
				name,
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (candidate == null || candidate.ReturnType != typeof(bool))
				continue;
			var parameters = candidate.GetParameters();
			if (parameters.Length != 3
			    || !parameters[0].ParameterType.IsInstanceOfType(abilityType)
			    || parameters[1].ParameterType != typeof(int)
			    || !parameters[2].ParameterType.IsByRef)
				continue;
			if (resolver != null && resolver != candidate)
			{
				failReason = "unit ability resolver binding is ambiguous";
				return false;
			}
			resolver = candidate;
		}
		if (resolver == null)
		{
			failReason = "exact unit ability resolver was not found";
			return false;
		}
		try
		{
			var args = new[] { abilityType, (object)Convert.ToInt32(abilityIndex), null };
			if (!Convert.ToBoolean(resolver.Invoke(manager, args)) || args[2] == null)
			{
				failReason = "exact unit ability resolver did not return an ability";
				return false;
			}
			ability = args[2];
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "unit ability resolution failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryResolveActionQueue(object context, out IList queue, out string failReason)
	{
		queue = null;
		if (context == null)
		{
			failReason = "action queue context is null";
			return false;
		}
		if (context is IList direct)
		{
			queue = direct;
			failReason = null;
			return true;
		}
		if (!TryReadExactMember(context, GameSymbols.DirectStateLaws.BattleLogicActionQueueMembers, out var value)
		    || value is not IList list)
		{
			failReason = "context has no exact authoritative action queue";
			return false;
		}
		queue = list;
		failReason = null;
		return true;
	}

	internal static bool TrySpendFocus(object side, int amount, out string failReason)
	{
		return Homm3FocusNativeAdapter.TrySpendFocusFromSide(side, amount, out failReason);
	}

	internal static bool TrySetSpellCooldown(object battleSpell, int cooldown, out string failReason)
	{
		if (Homm3SpellCooldownNativeAdapter.TrySetCooldown(battleSpell, cooldown, out failReason))
			return true;
		if (!TryWriteIntMember(battleSpell, "spell.storedCooldown", Math.Max(0, cooldown), out failReason))
			return false;
		return true;
	}

	internal static string GetCooldownMemberId(object cooldownOwner)
	{
		if (cooldownOwner == null)
			return null;
		var type = cooldownOwner.GetType();
		for (var i = 0; i < GameSymbols.SpellCooldownLaws.BattleSpellLogicTypeHints.Length; i++)
		{
			var hint = GameSymbols.SpellCooldownLaws.BattleSpellLogicTypeHints[i];
			if (string.Equals(type.FullName, hint, StringComparison.Ordinal)
			    || string.Equals(type.Name, hint, StringComparison.Ordinal))
				return "spell.storedCooldown";
		}
		return "ability.cooldown";
	}

	internal static bool TryReduceSpellCooldown(object battleSpell, int amount, out string failReason)
	{
		return Homm3SpellCooldownNativeAdapter.TryReduceCooldownBy(battleSpell, amount, out failReason);
	}

	internal static bool TryIncreaseSpellCooldown(object battleSpell, int amount, out string failReason)
	{
		return Homm3SpellCooldownNativeAdapter.TryAddCooldownIfReady(battleSpell, amount, out failReason);
	}

	internal static bool TryApplyStatus(
		object receiver,
		string sid,
		object caster,
		int level,
		int duration,
		int value,
		bool refresh,
		out string failReason)
	{
		return Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(
			receiver,
			sid,
			caster,
			level,
			duration,
			value,
			refresh,
			out _,
			out failReason);
	}

	internal static bool TryReadIntMember(object target, string memberId, out int value, out string failReason)
	{
		value = 0;
		if (!TryResolveBoundMember(target, memberId, requireWritable: false, out var member, out failReason))
			return false;
		try
		{
			value = Convert.ToInt32(member.Read(target), System.Globalization.CultureInfo.InvariantCulture);
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "native Int32 read failed for " + memberId + ": " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryWriteIntMember(object target, string memberId, int value, out string failReason)
	{
		return _writeBackend.TryWriteIntMember(target, memberId, value, out failReason);
	}

	internal static bool TryWriteIntMemberLive(object target, string memberId, int value, out string failReason)
	{
		if (!TryResolveBoundMember(target, memberId, requireWritable: true, out var member, out failReason))
			return false;
		try
		{
			var memberType = member.Field?.FieldType ?? member.Property.PropertyType;
			member.Write(target, Convert.ChangeType(value, memberType, System.Globalization.CultureInfo.InvariantCulture));
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "native Int32 write failed for " + memberId + ": " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryReadObjectMember(object target, string memberId, out object value, out string failReason)
	{
		value = null;
		if (!TryResolveBoundMember(target, memberId, requireWritable: false, out var member, out failReason))
			return false;
		try
		{
			value = member.Read(target);
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "native object read failed for " + memberId + ": " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryWriteObjectMember(object target, string memberId, object value, out string failReason)
	{
		return _writeBackend.TryWriteObjectMember(target, memberId, value, out failReason);
	}

	internal static bool TryWriteObjectMemberLive(object target, string memberId, object value, out string failReason)
	{
		if (!TryResolveBoundMember(target, memberId, requireWritable: true, out var member, out failReason))
			return false;
		try
		{
			var memberType = member.Field?.FieldType ?? member.Property.PropertyType;
			if (value != null && !memberType.IsInstanceOfType(value))
			{
				failReason = "value is not assignable to native member " + memberId;
				return false;
			}
			member.Write(target, value);
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "native object write failed for " + memberId + ": " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryCommitUnitHexMove(
		object unit,
		object destinationHex,
		Homm3DirectStateTransaction transaction,
		out object sourceHex,
		out string failReason)
	{
		sourceHex = null;
		if (unit == null || destinationHex == null || transaction == null)
		{
			failReason = "movement commit requires unit, destination hex, and transaction";
			return false;
		}
		if (!TryReadExactMember(unit, GameSymbols.BattleEventLaws.BattleObjectHexMembers, out sourceHex)
		    || sourceHex == null)
		{
			failReason = "movement unit has no exact current hex";
			return false;
		}
		if (NativeHexIdentityEquals(sourceHex, destinationHex))
		{
			failReason = "movement destination is the current hex";
			return false;
		}
		if (!ValidateDestination(destinationHex, unit, out failReason))
			return false;
		if (!TryReadExactMember(unit, GameSymbols.BattleEventLaws.BattleObjectBattleLogicMembers, out var battleLogic)
		    || battleLogic == null)
		{
			failReason = "movement unit has no exact battle-logic owner";
			return false;
		}
		if (!_movementSurfacePrepared)
		{
			failReason = "movement direct hex surface is not prepared";
			return false;
		}

		var snapshot = new Homm3MovementRollbackSnapshot
		{
			Unit = unit,
			BattleLogic = battleLogic,
			SourceHex = sourceHex,
			DestinationHex = destinationHex,
		};
		if (!transaction.TryRecordOccupancySnapshot(snapshot, out failReason))
			return false;
		// M3: journaled one-invoke UnitData.bfdi (movement.commit.bfdi_v1). Prefer this over
		// helper+_cfqf dual-write. Shared by MovementPush (M3) and MovementTeleport relocate
		// (M6 / movement.relocate.bfdi_v1) — not a second occupancy model.
		var beforeSourceMembership = TryFieldObjectsContainsUnit(sourceHex, unit, out var beforeSrc, out _)
			&& beforeSrc;
		var beforeDestMembership = TryFieldObjectsContainsUnit(destinationHex, unit, out var beforeDst, out _)
			&& beforeDst;
		if (!Homm3DirectStateUnitHexNative.TryMoveUnitHex(unit, sourceHex, destinationHex, out failReason))
			return false;
		// Dual readback: helper hex AND fieldObjects membership. CapLog only when both agree.
		// Do not use Hex.bcxo/cfqf (lastCorpse) as occupancy proof.
		if (!TryReadExactMember(unit, GameSymbols.BattleEventLaws.BattleObjectHexMembers, out var committedHex)
		    || !NativeHexIdentityEquals(committedHex, destinationHex))
		{
			failReason = "movement commit did not publish destination as unit helper hex (bfdi readback)"
			             + " " + DescribeHexIdentity(committedHex, "committed")
			             + " " + DescribeHexIdentity(destinationHex, "destination");
			Plugin.LogSource?.LogWarning(
				Homm3DirectStateM3BfdiShoveDiagnostic.CapLogPrefix
				+ " disagree helper_hex "
				+ failReason);
			return false;
		}
		if (!TryFieldObjectsContainsUnit(destinationHex, unit, out var destMembership, out failReason))
			return false;
		if (!destMembership)
		{
			failReason = "movement commit did not place unit in destination Hex.fieldObjects (bfdi occupancy)";
			Plugin.LogSource?.LogWarning(
				Homm3DirectStateM3BfdiShoveDiagnostic.CapLogPrefix
				+ " disagree fieldObjects_dest "
				+ failReason);
			return false;
		}
		if (sourceHex != null
		    && TryFieldObjectsContainsUnit(sourceHex, unit, out var sourceMembership, out _)
		    && sourceMembership)
		{
			failReason = "movement commit left unit in source Hex.fieldObjects after bfdi";
			Plugin.LogSource?.LogWarning(
				Homm3DirectStateM3BfdiShoveDiagnostic.CapLogPrefix
				+ " disagree fieldObjects_source "
				+ failReason);
			return false;
		}
		// Do not invent UnitPosChanged / Method_N dispatch here. Mid-attack event
		// publish desynced views; Method_N↔event-field correlation is unproven
		// (Skip is Method_11 vs mono ordinal 15). Logic occupancy is committed above;
		// presentation remains a separate proven-native gap.
		Plugin.LogSource?.LogInfo(
			Homm3DirectStateM3BfdiShoveDiagnostic.CapLogPrefix
			+ " agree"
			+ " " + DescribeHexIdentity(sourceHex, "beforeHelper")
			+ " " + DescribeHexIdentity(destinationHex, "afterHelper")
			+ " beforeSourceFieldObjects=" + beforeSourceMembership
			+ " beforeDestFieldObjects=" + beforeDestMembership
			+ " afterSourceFieldObjects=False"
			+ " afterDestFieldObjects=True"
			+ " dualAgree=True");
		failReason = null;
		return true;
	}

	internal static bool TryReadExactMemberPublic(object target, string[] names, out object value)
	{
		return TryReadExactMember(target, names, out value);
	}

	internal static bool TryReadIntMemberPublic(object target, string[] names, out int value)
	{
		value = 0;
		if (!TryReadExactMember(target, names, out var raw) || raw == null)
			return false;
		try
		{
			value = Convert.ToInt32(raw, System.Globalization.CultureInfo.InvariantCulture);
			return true;
		}
		catch
		{
			return false;
		}
	}

	internal static bool TryFieldObjectsContainsUnitPublic(
		object hex,
		object unit,
		out bool contains,
		out string failReason)
	{
		return TryFieldObjectsContainsUnit(hex, unit, out contains, out failReason);
	}

	internal static bool NativeHexIdentityEqualsPublic(object left, object right)
	{
		return NativeHexIdentityEquals(left, right);
	}

	private static bool TryFieldObjectsContainsUnit(
		object hex,
		object unit,
		out bool contains,
		out string failReason)
	{
		contains = false;
		failReason = null;
		if (hex == null || unit == null)
		{
			failReason = "fieldObjects membership requires hex and unit";
			return false;
		}
		if (!TryReadExactMember(hex, GameSymbols.DirectStateLaws.HexFieldObjectsMembers, out var listObj)
		    || listObj == null)
		{
			failReason = "Hex.fieldObjects unavailable for occupancy readback";
			return false;
		}
		if (!TryEnumerateFieldObjects(listObj, out var items, out failReason))
			return false;
		for (var i = 0; i < items.Count; i++)
		{
			var item = items[i];
			if (item != null && NativeUnitIdentityEquals(item, unit))
			{
				contains = true;
				return true;
			}
		}
		contains = false;
		return true;
	}

	/// <summary>
	/// Enumerate Hex.fieldObjects. Live GE exposes Il2Cpp List&lt;FieldObject&gt; which does not
	/// implement managed <see cref="System.Collections.IEnumerable"/>; use Count/Item.
	/// </summary>
	private static bool TryEnumerateFieldObjects(
		object listObj,
		out List<object> items,
		out string failReason)
	{
		items = new List<object>();
		failReason = null;
		if (listObj == null)
		{
			failReason = "Hex.fieldObjects list is null";
			return false;
		}
		if (listObj is System.Collections.IEnumerable managedEnumerable
		    && listObj is not string)
		{
			try
			{
				foreach (var item in managedEnumerable)
					items.Add(item);
				return true;
			}
			catch
			{
				items.Clear();
			}
		}

		var listType = listObj.GetType();
		const BindingFlags flags =
			BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		try
		{
			var countProp = listType.GetProperty("Count", flags)
			                ?? listType.GetProperty("get_Count", flags);
			var countMethod = countProp == null
				? listType.GetMethod("get_Count", flags, null, Type.EmptyTypes, null)
				: null;
			int count;
			if (countProp != null)
				count = Convert.ToInt32(countProp.GetValue(listObj, null), System.Globalization.CultureInfo.InvariantCulture);
			else if (countMethod != null)
				count = Convert.ToInt32(countMethod.Invoke(listObj, null), System.Globalization.CultureInfo.InvariantCulture);
			else
			{
				failReason = "Hex.fieldObjects Count surface missing type=" + (listType.FullName ?? listType.Name);
				return false;
			}
			if (count < 0 || count > 4096)
			{
				failReason = "Hex.fieldObjects Count out of bounds count=" + count;
				return false;
			}

			PropertyInfo itemProp = null;
			MethodInfo itemMethod = null;
			foreach (var prop in listType.GetProperties(flags))
			{
				if (prop.GetIndexParameters().Length == 1
				    && (prop.Name == "Item" || prop.Name == "get_Item"))
				{
					itemProp = prop;
					break;
				}
			}
			if (itemProp == null)
			{
				foreach (var method in listType.GetMethods(flags))
				{
					if (method.Name != "get_Item")
						continue;
					var parameters = method.GetParameters();
					if (parameters.Length == 1 && parameters[0].ParameterType == typeof(int))
					{
						itemMethod = method;
						break;
					}
				}
			}
			if (itemProp == null && itemMethod == null)
			{
				failReason = "Hex.fieldObjects Item indexer missing type=" + (listType.FullName ?? listType.Name);
				return false;
			}

			for (var i = 0; i < count; i++)
			{
				object item;
				if (itemProp != null)
					item = itemProp.GetValue(listObj, new object[] { i });
				else
					item = itemMethod.Invoke(listObj, new object[] { i });
				items.Add(item);
			}
			return true;
		}
		catch (Exception ex)
		{
			failReason = "Hex.fieldObjects enumerate failed: " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	internal static bool TryInitializeAndInsertObject(
		Type runtimeType,
		object[] initArgs,
		IList ownerCollection,
		Homm3DirectStateTransaction transaction,
		out object runtimeObject,
		out string failReason)
	{
		runtimeObject = null;
		if (runtimeType == null || initArgs == null || ownerCollection == null || transaction == null)
		{
			failReason = "spawn transaction requires runtime type, Init args, owner collection, and transaction";
			return false;
		}
		var init = ResolveExactInit(runtimeType, initArgs);
		if (init == null)
		{
			failReason = "exact spawn Init shape was not found on " + runtimeType.FullName;
			return false;
		}
		if (!transaction.TryRecordListSnapshot(ownerCollection, out failReason))
			return false;
		try
		{
			runtimeObject = Activator.CreateInstance(runtimeType);
			if (runtimeObject == null)
			{
				failReason = "runtime object construction returned null";
				return false;
			}
			init.Invoke(runtimeObject, initArgs);
			ownerCollection.Add(runtimeObject);
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			runtimeObject = null;
			failReason = "runtime object create/Init/insert failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryInsertListItem(
		IList list,
		int index,
		object value,
		Homm3DirectStateTransaction transaction,
		out string failReason)
	{
		if (list == null || transaction == null || index < 0 || index > list.Count)
		{
			failReason = "list insertion requires list, transaction, and valid index";
			return false;
		}
		if (!transaction.TryRecordListSnapshot(list, out failReason))
			return false;
		try
		{
			list.Insert(index, value);
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "native list insertion failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryRemoveListItem(
		IList list,
		int index,
		Homm3DirectStateTransaction transaction,
		out object removed,
		out string failReason)
	{
		removed = null;
		if (list == null || transaction == null || index < 0 || index >= list.Count)
		{
			failReason = "list removal requires list, transaction, and valid index";
			return false;
		}
		if (!transaction.TryRecordListSnapshot(list, out failReason))
			return false;
		try
		{
			removed = list[index];
			list.RemoveAt(index);
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "native list removal failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryReorderListItem(
		IList list,
		int fromIndex,
		int toIndex,
		Homm3DirectStateTransaction transaction,
		out string failReason)
	{
		if (list == null
		    || transaction == null
		    || fromIndex < 0
		    || fromIndex >= list.Count
		    || toIndex < 0
		    || toIndex >= list.Count)
		{
			failReason = "list reorder requires list, transaction, and valid indexes";
			return false;
		}
		if (!transaction.TryRecordListSnapshot(list, out failReason))
			return false;
		try
		{
			var entry = list[fromIndex];
			list.RemoveAt(fromIndex);
			list.Insert(toIndex, entry);
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "native list reorder failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryInvokeDeferredDamage(
		Homm3DirectDamageRequest request,
		out string failReason)
	{
		if (request.Receiver == null || request.ApplyDamageMethod == null || request.Arguments == null)
		{
			failReason = "nested damage request is incomplete";
			return false;
		}
		try
		{
			request.ApplyDamageMethod.Invoke(request.Receiver, request.Arguments);
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "nested damage invocation failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryInvokeRedirectedDamage(
		MethodInfo method,
		object receiver,
		object caster,
		object castSource,
		object dealer,
		int damage,
		object fromMech,
		bool immuneToDamage,
		float scalar,
		bool cumulative,
		out string failReason)
	{
		if (method == null || receiver == null)
		{
			failReason = "redirected damage method or receiver is null";
			return false;
		}
		try
		{
			method.Invoke(
				receiver,
				new[]
				{
					caster,
					castSource,
					dealer,
					(object)damage,
					fromMech,
					immuneToDamage,
					scalar,
					cumulative,
				});
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "redirected damage invocation failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryInvokeDeferredCast(
		Homm3DirectCastRequest request,
		out string failReason)
	{
		if (!request.IsValid)
		{
			failReason = "cast-chain request is incomplete";
			return false;
		}
		try
		{
			request.CastMethod.Invoke(request.CastMethod.IsStatic ? null : request.Target, request.Arguments);
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "cast-chain invocation failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryRestore(Homm3DirectStateJournalEntry entry, out string failReason)
	{
		switch (entry.Opcode)
		{
			case Homm3DirectStateJournalOpcode.NativeIntMember:
				return TryWriteIntMember(entry.Target, entry.MemberId, entry.OldInt, out failReason);
			case Homm3DirectStateJournalOpcode.NativeObjectMember:
				return TryWriteObjectMember(entry.Target, entry.MemberId, entry.OldValue, out failReason);
			case Homm3DirectStateJournalOpcode.NativeListSnapshot:
				return TryRestoreList(entry.Target as IList, entry.OldItems, out failReason);
			case Homm3DirectStateJournalOpcode.Occupancy:
				return TryRestoreMovement(entry.Target as Homm3MovementRollbackSnapshot, out failReason);
			case Homm3DirectStateJournalOpcode.ManagerInt:
			case Homm3DirectStateJournalOpcode.ManagerObject:
			case Homm3DirectStateJournalOpcode.StatusLedger:
			case Homm3DirectStateJournalOpcode.Spawn:
			case Homm3DirectStateJournalOpcode.Trap:
			case Homm3DirectStateJournalOpcode.Corpse:
			case Homm3DirectStateJournalOpcode.ActionQueue:
			case Homm3DirectStateJournalOpcode.TurnOrder:
			case Homm3DirectStateJournalOpcode.Aura:
			case Homm3DirectStateJournalOpcode.EventToken:
			case Homm3DirectStateJournalOpcode.PresentationToken:
				if (entry.Target is IHomm3DirectStateLedger ledger)
					return ledger.TryRestore(entry, out failReason);
				failReason = "journal entry " + entry.Opcode + " has no typed ledger owner";
				return false;
			case Homm3DirectStateJournalOpcode.DamageScalar:
			case Homm3DirectStateJournalOpcode.None:
			default:
				failReason = null;
				return true;
		}
	}

	private static bool TryPrepareMovement(out string failReason)
	{
		if (!Homm3DirectStateUnitHexNative.TryValidateSurface(out failReason))
			return false;
		_movementSurfacePrepared = true;
		failReason = null;
		return true;
	}

	private static bool TryPrepareCooldownStorage(out string failReason)
	{
		var spellType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.SpellCooldownLawsBattleSpellLogic);
		if (spellType == null
		    || !HasWritableIntMember(spellType, GameSymbols.DirectStateLaws.SpellStoredCooldownMembers))
		{
			failReason = "spell cooldown direct-storage member was not found";
			return false;
		}

		var abilityType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.DirectStateLawsUnitAbility);
		if (abilityType == null
		    || !HasWritableIntMember(abilityType, GameSymbols.DirectStateLaws.AbilityCooldownMembers))
		{
			failReason = "unit-ability cooldown direct-storage member was not found";
			return false;
		}

		failReason = null;
		return true;
	}

	private static bool TryPrepareSummon(out string failReason)
	{
		var unitType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.BattleEventLawsBattleUnit);
		if (unitType == null)
		{
			failReason = "summon Unit type was not found";
			return false;
		}
		foreach (var method in unitType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (string.Equals(method.Name, "Init", StringComparison.Ordinal)
			    || Contains(GameSymbols.BattleUnitInit.Init.NameHints, method.Name))
			{
				failReason = null;
				return true;
			}
		}
		failReason = "summon Unit.Init method was not found";
		return false;
	}

	private static bool ValidateDestination(object destinationHex, object movingUnit, out string failReason)
	{
		// Occupancy = Hex.fieldObjects (bcyl/bcyn path). Never lastCorpse as occupancy.
		// Blocked flags mirror Hex.bcyf / IsLockedForSide store inputs (blockedFromAll /
		// blockedByMap / tempBlocked) without inventing a second occupancy model.
		if (!TryReadAnyBlockedFlag(destinationHex, out var blocked, out failReason))
			return false;
		if (blocked)
		{
			failReason = "destination hex is blocked";
			return false;
		}
		if (!TryFieldObjectsContainsUnit(destinationHex, movingUnit, out var selfPresent, out failReason))
			return false;
		if (!TryFieldObjectsHasForeignOccupant(destinationHex, movingUnit, out var foreign, out failReason))
			return false;
		if (foreign && !selfPresent)
		{
			failReason = "destination hex is occupied (Hex.fieldObjects)";
			return false;
		}
		failReason = null;
		return true;
	}

	private static bool TryReadAnyBlockedFlag(object hex, out bool blocked, out string failReason)
	{
		blocked = false;
		failReason = null;
		var names = GameSymbols.DirectStateLaws.HexBlockedMembers;
		if (names == null || names.Length == 0)
		{
			failReason = "destination blocked state unavailable";
			return false;
		}
		var anyKnown = false;
		for (var i = 0; i < names.Length; i++)
		{
			if (!TryReadExactMember(hex, new[] { names[i] }, out var raw) || raw == null)
				continue;
			if (raw is not bool flag)
				continue;
			anyKnown = true;
			if (flag)
			{
				blocked = true;
				return true;
			}
		}
		if (!anyKnown)
		{
			failReason = "destination blocked state unavailable";
			return false;
		}
		return true;
	}

	private static bool TryFieldObjectsHasForeignOccupant(
		object hex,
		object movingUnit,
		out bool hasForeign,
		out string failReason)
	{
		hasForeign = false;
		if (hex == null)
		{
			failReason = "fieldObjects foreign occupancy requires hex";
			return false;
		}
		if (!TryReadExactMember(hex, GameSymbols.DirectStateLaws.HexFieldObjectsMembers, out var listObj)
		    || listObj == null)
		{
			failReason = "Hex.fieldObjects unavailable for occupancy gate";
			return false;
		}
		if (!TryEnumerateFieldObjects(listObj, out var items, out failReason))
			return false;
		for (var i = 0; i < items.Count; i++)
		{
			var item = items[i];
			if (item == null)
				continue;
			if (movingUnit != null && NativeUnitIdentityEquals(item, movingUnit))
				continue;
			hasForeign = true;
			failReason = null;
			return true;
		}
		failReason = null;
		return true;
	}

	private static void LogPrepareHonestyOnce(Homm3DirectStateAdapterId adapterId, string mode)
	{
		lock (Gate)
		{
			if (!PrepareHonestyLogged.Add(adapterId))
				return;
		}
		Plugin.LogSource?.LogInfo(
			"HoMM3 direct-state prepare: adapter="
			+ adapterId
			+ " mode=" + mode
			+ " (no live surface bind at prepare).");
	}

	private static bool NativeHexIdentityEquals(object left, object right)
	{
		if (left == null || right == null)
			return false;
		if (ReferenceEquals(left, right))
			return true;
		if (left is Il2CppObjectBase leftNative
		    && right is Il2CppObjectBase rightNative
		    && leftNative.Pointer != IntPtr.Zero
		    && leftNative.Pointer == rightNative.Pointer)
			return true;
		if (TryReadIntMember(left, GameSymbols.BattleEventLaws.HexIndexMembers, out var leftIndex)
		    && TryReadIntMember(right, GameSymbols.BattleEventLaws.HexIndexMembers, out var rightIndex)
		    && leftIndex == rightIndex)
			return true;
		return TryReadIntMember(left, GameSymbols.BattleEventLaws.HexXMembers, out var lx)
		       && TryReadIntMember(left, GameSymbols.BattleEventLaws.HexZMembers, out var lz)
		       && TryReadIntMember(right, GameSymbols.BattleEventLaws.HexXMembers, out var rx)
		       && TryReadIntMember(right, GameSymbols.BattleEventLaws.HexZMembers, out var rz)
		       && lx == rx
		       && lz == rz;
	}

	private static bool NativeUnitIdentityEquals(object left, object right)
	{
		if (left == null || right == null)
			return false;
		if (ReferenceEquals(left, right))
			return true;
		return left is Il2CppObjectBase leftNative
		       && right is Il2CppObjectBase rightNative
		       && leftNative.Pointer != IntPtr.Zero
		       && leftNative.Pointer == rightNative.Pointer;
	}

	private static string DescribeHexIdentity(object hex, string label)
	{
		if (hex == null)
			return label + "=null";
		var ptr = hex is Il2CppObjectBase native ? native.Pointer.ToString("X") : "n/a";
		TryReadIntMember(hex, GameSymbols.BattleEventLaws.HexIndexMembers, out var index);
		TryReadIntMember(hex, GameSymbols.BattleEventLaws.HexXMembers, out var x);
		TryReadIntMember(hex, GameSymbols.BattleEventLaws.HexZMembers, out var z);
		return label + "={ptr=" + ptr + ";index=" + index + ";x=" + x + ";z=" + z + "}";
	}

	private static bool TryReadIntMember(object target, string[] names, out int value)
	{
		value = 0;
		if (!TryReadExactMember(target, names, out var raw) || raw == null)
			return false;
		try
		{
			value = Convert.ToInt32(raw, System.Globalization.CultureInfo.InvariantCulture);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static MethodInfo ResolveExactInit(Type runtimeType, object[] args)
	{
		foreach (var method in runtimeType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (!string.Equals(method.Name, "Init", StringComparison.Ordinal)
			    && !Contains(GameSymbols.BattleUnitInit.Init.NameHints, method.Name))
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length != args.Length)
				continue;
			var valid = true;
			for (var i = 0; i < parameters.Length; i++)
			{
				if (args[i] != null && !parameters[i].ParameterType.IsInstanceOfType(args[i]))
				{
					valid = false;
					break;
				}
			}
			if (valid)
				return method;
		}
		return null;
	}

	private static bool TryRestoreMovement(Homm3MovementRollbackSnapshot snapshot, out string failReason)
	{
		if (snapshot?.Unit == null
		    || snapshot.SourceHex == null
		    || snapshot.DestinationHex == null)
		{
			failReason = "movement rollback snapshot is incomplete";
			return false;
		}
		if (!Homm3DirectStateUnitHexNative.TryMoveUnitHex(
			    snapshot.Unit,
			    snapshot.DestinationHex,
			    snapshot.SourceHex,
			    out failReason))
			return false;
		failReason = null;
		return true;
	}

	private static bool TryRestoreList(IList list, object[] oldItems, out string failReason)
	{
		if (list == null || oldItems == null)
		{
			failReason = "list rollback snapshot is incomplete";
			return false;
		}
		try
		{
			list.Clear();
			for (var i = 0; i < oldItems.Length; i++)
				list.Add(oldItems[i]);
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "list rollback failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	private static bool TryResolveBoundMember(
		object target,
		string memberId,
		bool requireWritable,
		out BoundMember member,
		out string failReason)
	{
		member = null;
		if (target == null || string.IsNullOrWhiteSpace(memberId))
		{
			failReason = "native member target or semantic ID is missing";
			return false;
		}
		var key = target.GetType().AssemblyQualifiedName + "|" + memberId + "|" + requireWritable;
		lock (Gate)
		{
			if (Members.TryGetValue(key, out member))
			{
				failReason = null;
				return true;
			}
		}
		if (!TryGetMemberNames(memberId, out var names))
		{
			failReason = "unknown native member semantic ID " + memberId;
			return false;
		}
		for (var current = target.GetType(); current != null && current != typeof(object); current = current.BaseType)
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			for (var i = 0; i < names.Length; i++)
			{
				var name = names[i];
				if (string.IsNullOrWhiteSpace(name))
					continue;
				var field = current.GetField(name, flags);
				if (field != null && (!requireWritable || !field.IsInitOnly))
				{
					member = new BoundMember { Field = field };
					lock (Gate)
						Members[key] = member;
					failReason = null;
					return true;
				}
				var property = current.GetProperty(name, flags);
				if (property != null
				    && property.GetIndexParameters().Length == 0
				    && (!requireWritable || property.CanWrite))
				{
					member = new BoundMember { Property = property };
					lock (Gate)
						Members[key] = member;
					failReason = null;
					return true;
				}
			}
		}
		failReason = "native member " + memberId + " was not found on " + target.GetType().FullName;
		return false;
	}

	private static bool HasWritableIntMember(Type type, string[] names)
	{
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			for (var i = 0; i < names.Length; i++)
			{
				var name = names[i];
				if (string.IsNullOrWhiteSpace(name))
					continue;
				var field = current.GetField(name, flags);
				if (field != null && field.FieldType == typeof(int) && !field.IsInitOnly)
					return true;
				var property = current.GetProperty(name, flags);
				if (property != null
				    && property.PropertyType == typeof(int)
				    && property.GetIndexParameters().Length == 0
				    && property.CanRead
				    && property.CanWrite)
					return true;
			}
		}
		return false;
	}

	private static bool TryGetMemberNames(string memberId, out string[] names)
	{
		switch (memberId)
		{
			case "spell.storedCooldown":
				names = GameSymbols.DirectStateLaws.SpellStoredCooldownMembers;
				return true;
			case "ability.cooldown":
				names = GameSymbols.DirectStateLaws.AbilityCooldownMembers;
				return true;
			case "ability.charges":
				names = GameSymbols.DirectStateLaws.AbilityChargesMembers;
				return true;
			case "ability.castCounter":
				names = GameSymbols.DirectStateLaws.AbilityCastCounterMembers;
				return true;
			case "focus.value":
				names = GameSymbols.DirectStateLaws.FocusValueMembers;
				return true;
			case "hex.occupant":
				names = GameSymbols.DirectStateLaws.HexOccupantWriteMembers;
				return true;
			case "fieldObject.hex":
				names = GameSymbols.DirectStateLaws.FieldObjectHexWriteMembers;
				return true;
			case "fieldObject.positionHelper":
				names = GameSymbols.DirectStateLaws.FieldObjectPositionHelperMembers;
				return true;
			default:
				names = null;
				return false;
		}
	}

	private static bool TryReadExactMember(object target, string[] names, out object value)
	{
		value = null;
		if (target == null || names == null)
			return false;
		for (var current = target.GetType(); current != null && current != typeof(object); current = current.BaseType)
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			for (var i = 0; i < names.Length; i++)
			{
				var name = names[i];
				if (string.IsNullOrWhiteSpace(name))
					continue;
				try
				{
					var field = current.GetField(name, flags);
					if (field != null)
					{
						value = field.GetValue(target);
						return true;
					}
					var property = current.GetProperty(name, flags);
					if (property != null && property.GetIndexParameters().Length == 0)
					{
						value = property.GetValue(target, null);
						return true;
					}
					var method = current.GetMethod(name, flags, null, Type.EmptyTypes, null);
					if (method != null && method.ReturnType != typeof(void))
					{
						value = method.Invoke(target, null);
						return true;
					}
				}
				catch
				{
				}
			}
		}
		return false;
	}

	private static bool TryReadBool(object target, string[] names, out bool value)
	{
		value = false;
		if (!TryReadExactMember(target, names, out var raw) || raw == null)
			return false;
		if (raw is bool boolean)
		{
			value = boolean;
			return true;
		}
		return false;
	}

	private static bool Contains(string[] values, string value)
	{
		for (var i = 0; i < values.Length; i++)
		{
			if (string.Equals(values[i], value, StringComparison.Ordinal))
				return true;
		}
		return false;
	}
}

/// <summary>
/// Compatibility surface retained while callers move from the damage-only API.
/// It delegates to the sole native write gateway and owns no state or writes.
/// </summary>
internal static class CombatMutationApi
{
	internal static bool TryPrepareFlatDamageMutation(
		int mechanicIndex,
		int currentDamage,
		int damageDelta,
		out PreparedDamageMutation mutation)
	{
		mutation = default;
		if (mechanicIndex < 0 || currentDamage < 0 || damageDelta == 0)
			return false;
		try
		{
			var newDamage = checked(currentDamage + damageDelta);
			if (newDamage < 0)
				return false;
			mutation = new PreparedDamageMutation(mechanicIndex, currentDamage, newDamage);
			return mutation.IsValid;
		}
		catch (OverflowException)
		{
			return false;
		}
	}

	internal static bool TryCommitPreparedDamage(ref int damage, PreparedDamageMutation mutation)
	{
		return NativeCombatWriteGateway.TryCommitPreparedDamage(ref damage, mutation);
	}
}
