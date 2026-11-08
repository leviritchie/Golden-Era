using System;
using System.Collections.Generic;
using System.Reflection;
using Hex.Configs;
using Hex.Session.Battle;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Maps integer damage to killed stacks through the current battle target contract
/// (<c>eaf.bbfj(int)</c>) and validates caps against concrete UnitData. The UnitData
/// path mirrors the old <c>DamageCalculatorUtility.GetKilledStacks</c> decompilation.
/// </summary>
internal static class DamageKillMapping
{
	private static readonly BindingFlags MemberFlags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
	private static readonly Dictionary<Type, UnitAccessors> UnitAccessorCache = new();
	private static readonly Dictionary<Type, DataAccessors> DataAccessorCache = new();

	private sealed class UnitAccessors
	{
		internal FieldInfo DataField;
		internal PropertyInfo DataProperty;
		internal MethodInfo DataGetter;
		internal MethodInfo StatsMethod;
		internal MethodInfo StackCountMethod;
		internal MethodInfo KilledStackMethod;
	}

	private sealed class DataAccessors
	{
		internal FieldInfo HpLastUnitField;
		internal PropertyInfo HpLastUnitProperty;
		internal FieldInfo AllStacksField;
		internal PropertyInfo AllStacksProperty;
		internal MethodInfo AllStacksMethod;
		internal FieldInfo FullStacksField;
		internal PropertyInfo FullStacksProperty;
		internal FieldInfo TempFullStacksField;
		internal PropertyInfo TempFullStacksProperty;
		internal FieldInfo HpPerFallbackField;
		internal PropertyInfo HpPerFallbackProperty;
	}

	internal sealed class KillCapInfo
	{
		internal int DtoKillMin;
		internal int DtoKillMax;
		internal bool HasNativeKills;
		internal int NativeKillMin;
		internal int NativeKillMax;
		internal bool HasUnitDataKills;
		internal int UnitDataKillMin;
		internal int UnitDataKillMax;
		internal bool HasUnitDataAlive;
		internal int UnitDataAlive;
		internal bool HasInterfaceStackCount;
		internal int InterfaceStackCount;
		internal bool HasReceiverStackHint;
		internal int ReceiverStackHint;
		internal bool IsDefensible;
		internal int SelectedCap;
		internal string SelectedCapSource;

		internal int ExpectedMax => Mathf.Max(
			Mathf.Max(DtoKillMax, HasUsableNativeKills ? NativeKillMax : 0),
			HasUsableUnitDataKills ? UnitDataKillMax : 0);

		internal bool NativeConflictsWithDto => HasNativeKills && !RangeCanRepresentDto(NativeKillMin, NativeKillMax);
		internal bool UnitDataConflictsWithDto => HasUnitDataKills && !RangeCanRepresentDto(UnitDataKillMin, UnitDataKillMax);
		internal bool HasUsableNativeKills => HasNativeKills && !NativeConflictsWithDto;
		internal bool HasUsableUnitDataKills => HasUnitDataKills && !UnitDataConflictsWithDto;
		internal bool UnitDataMatchesDto => HasUsableUnitDataKills;

		private bool RangeCanRepresentDto(int min, int max)
		{
			if (DtoKillMax == 0)
			{
				return max == 0;
			}
			if (max < DtoKillMax)
			{
				return false;
			}
			if (min > DtoKillMax)
			{
				return false;
			}
			return min <= DtoKillMin || min <= DtoKillMax;
		}

		internal string ToDiagnosticString()
		{
			return "dtoKills=" + DtoKillMin + "-" + DtoKillMax
				+ ", nativeKills=" + (HasNativeKills ? NativeKillMin + "-" + NativeKillMax : "?")
				+ ", unitDataKills=" + (HasUnitDataKills ? UnitDataKillMin + "-" + UnitDataKillMax : "?")
				+ ", selectedCap=" + (IsDefensible ? SelectedCap.ToString() : "?")
				+ ", capSource=" + (SelectedCapSource ?? "?")
				+ ", unitDataAlive=" + (HasUnitDataAlive ? UnitDataAlive.ToString() : "?")
				+ ", interfaceStack=" + (HasInterfaceStackCount ? InterfaceStackCount.ToString() : "?")
				+ ", receiverHint=" + (HasReceiverStackHint ? ReceiverStackHint.ToString() : "?");
		}
	}

	internal static bool TryGetKilledStacksFromGameRules(int unitDmg, object target, out int killedStacks)
	{
		killedStacks = 0;
		if (target == null || unitDmg < 0)
		{
			return false;
		}

		var accessors = GetUnitAccessors(target.GetType());
		if (TryInvokeInt(target, accessors.KilledStackMethod, unitDmg, out var nativeKills))
		{
			killedStacks = Mathf.Max(0, nativeKills);
			return true;
		}

		try
		{
			return TryGetKilledStacksFromUnitData(unitDmg, target, out killedStacks);
		}
		catch
		{
			killedStacks = 0;
			return false;
		}
	}

	internal static int GetKilledStacksFromGameRules(int unitDmg, Unit target)
	{
		return TryGetKilledStacksFromGameRules(unitDmg, target, out var killedStacks)
			? killedStacks
			: 0;
	}

	internal static bool TryGetCombatStats(object target, out UnitStat stats)
	{
		stats = TryGetStats(target);
		return stats != null;
	}

	internal static bool TryGetStackCount(object target, out int allStacks)
	{
		allStacks = 0;
		if (target == null)
		{
			return false;
		}

		try
		{
			var accessors = GetUnitAccessors(target.GetType());
			if (TryInvokeInt(target, accessors.StackCountMethod, out allStacks) && allStacks > 0)
			{
				return true;
			}

			return TryGetUnitData(target, out var data)
			       && TryReadStackCount(data, out allStacks)
			       && allStacks > 0;
		}
		catch
		{
			allStacks = 0;
			return false;
		}
	}

	/// <summary>
	/// Like <see cref="TryGetStackCount"/> but returns true for a readable zero count.
	/// MovementPush dead-stack CapLog requires this; <see cref="TryGetStackCount"/> never observes 0.
	/// </summary>
	internal static bool TryGetStackCountIncludingZero(object target, out int allStacks)
	{
		allStacks = 0;
		if (target == null)
			return false;

		try
		{
			var accessors = GetUnitAccessors(target.GetType());
			if (TryInvokeInt(target, accessors.StackCountMethod, out allStacks) && allStacks >= 0)
				return true;

			return TryGetUnitData(target, out var data)
			       && TryReadStackCount(data, out allStacks)
			       && allStacks >= 0;
		}
		catch
		{
			allStacks = 0;
			return false;
		}
	}

	internal static bool TryGetInterfaceStackCount(object target, out int stackCount)
	{
		stackCount = 0;
		if (target == null)
		{
			return false;
		}

		try
		{
			var accessors = GetUnitAccessors(target.GetType());
			return TryInvokeInt(target, accessors.StackCountMethod, out stackCount) && stackCount > 0;
		}
		catch
		{
			stackCount = 0;
			return false;
		}
	}

	internal static bool TryGetAliveCreatureCount(object target, out int aliveCount)
	{
		aliveCount = 0;
		if (target == null)
		{
			return false;
		}

		try
		{
			if (TryReadAliveCreatureCount(target, out aliveCount) && aliveCount >= 0)
			{
				return true;
			}

			return TryGetUnitData(target, out var data)
			       && TryReadAliveCreatureCount(data, out aliveCount)
			       && aliveCount >= 0;
		}
		catch
		{
			aliveCount = 0;
			return false;
		}
	}

	internal static bool TryGetKilledStacksFromUnitDataRules(int unitDmg, object target, out int killedStacks)
	{
		return TryGetKilledStacksFromUnitData(unitDmg, target, out killedStacks);
	}

	internal static KillCapInfo ResolveKillCap(
		int dMin,
		int dMax,
		int dtoKillMin,
		int dtoKillMax,
		object nativeTarget,
		object unitDataOwner,
		int receiverStackHint)
	{
		var info = new KillCapInfo
		{
			DtoKillMin = Mathf.Max(0, dtoKillMin),
			DtoKillMax = Mathf.Max(0, dtoKillMax),
			HasReceiverStackHint = receiverStackHint > 0,
			ReceiverStackHint = Mathf.Max(0, receiverStackHint)
		};
		if (info.DtoKillMax < info.DtoKillMin)
		{
			info.DtoKillMax = info.DtoKillMin;
		}

		if (nativeTarget != null
		    && TryGetKilledStacksFromGameRules(dMin, nativeTarget, out var nativeMin)
		    && TryGetKilledStacksFromGameRules(dMax, nativeTarget, out var nativeMax))
		{
			info.HasNativeKills = true;
			info.NativeKillMin = Mathf.Max(0, nativeMin);
			info.NativeKillMax = Mathf.Max(info.NativeKillMin, nativeMax);
		}

		if (unitDataOwner != null
		    && TryGetKilledStacksFromUnitDataRules(dMin, unitDataOwner, out var dataMin)
		    && TryGetKilledStacksFromUnitDataRules(dMax, unitDataOwner, out var dataMax))
		{
			info.HasUnitDataKills = true;
			info.UnitDataKillMin = Mathf.Max(0, dataMin);
			info.UnitDataKillMax = Mathf.Max(info.UnitDataKillMin, dataMax);
		}

		if (unitDataOwner != null && TryGetAliveCreatureCount(unitDataOwner, out var alive)
		    || nativeTarget != null && TryGetAliveCreatureCount(nativeTarget, out alive))
		{
			info.HasUnitDataAlive = true;
			info.UnitDataAlive = Mathf.Max(0, alive);
		}

		if (nativeTarget != null && TryGetInterfaceStackCount(nativeTarget, out var interfaceStack))
		{
			info.HasInterfaceStackCount = true;
			info.InterfaceStackCount = Mathf.Max(0, interfaceStack);
		}

		var expectedMax = info.ExpectedMax;
		if (info.HasUnitDataAlive && info.UnitDataAlive >= expectedMax)
		{
			info.IsDefensible = true;
			info.SelectedCap = info.UnitDataAlive;
			info.SelectedCapSource = "unitDataAlive";
		}
		else if (expectedMax > 0 || info.DtoKillMax == 0 || info.HasUsableNativeKills || info.HasUsableUnitDataKills)
		{
			info.IsDefensible = true;
			info.SelectedCap = expectedMax;
			info.SelectedCapSource = info.HasUnitDataAlive
				? "forecastMax(unitDataAlive-mismatch)"
				: "forecastMax";
		}
		else
		{
			info.IsDefensible = false;
			info.SelectedCap = 0;
			info.SelectedCapSource = "unresolved";
		}

		info.SelectedCap = Mathf.Clamp(info.SelectedCap, 0, 511);
		return info;
	}

	private static bool TryGetKilledStacksFromUnitData(int unitDmg, object target, out int killedStacks)
	{
		killedStacks = 0;
		if (!TryGetUnitData(target, out var data))
		{
			return false;
		}

		if (!TryReadHpLastUnit(data, out var hpLastUnit) || hpLastUnit <= 0f)
		{
			return false;
		}
		if (!TryReadAliveCreatureCount(data, out var allStacks) || allStacks <= 0)
		{
			return false;
		}

		var stats = TryGetStats(target);
		// Audit B5: UnitStat.hp is field_Public_Int32_0 on live Golden Era; read by name. A miss
		// falls through to the existing data-driven hp-per-unit resolution below.
		var hpPer = stats != null
		            && DeobfInteropCompat.TryGetInt32Member(stats, out var statHp, GameSymbols.LiveRenamedMembers.UnitStatHp)
		            && statHp > 0
			? statHp
			: 0;
		if (hpPer <= 0)
		{
			TryReadHpPerFallback(data, out hpPer);
			if (hpPer <= 0)
			{
				hpPer = Mathf.CeilToInt(hpLastUnit);
			}
		}
		if (hpPer <= 0)
		{
			return false;
		}

		var killed = 0;
		var remaining = (float)unitDmg;
		if (remaining >= hpLastUnit)
		{
			killed++;
			remaining -= hpLastUnit;
			killed += Mathf.FloorToInt(remaining / hpPer);
		}

		killedStacks = Mathf.Clamp(killed, 0, allStacks);
		return true;
	}

	private static bool TryGetUnitData(object target, out object data)
	{
		data = null;
		if (target == null)
			return false;

		var accessors = GetUnitAccessors(target.GetType());
		if (TryGetMemberValue(target, accessors.DataField, accessors.DataProperty, out data) && data != null)
		{
			return true;
		}

		if (accessors.DataGetter == null)
		{
			return false;
		}
		try
		{
			data = accessors.DataGetter.Invoke(target, Array.Empty<object>());
			return data != null;
		}
		catch
		{
			data = null;
			return false;
		}
	}

	private static UnitStat TryGetStats(object target)
	{
		if (target == null)
			return null;

		var accessors = GetUnitAccessors(target.GetType());
		var method = accessors.StatsMethod;
		if (method == null)
			return null;
		try
		{
			return method.Invoke(target, Array.Empty<object>()) as UnitStat;
		}
		catch
		{
			return null;
		}
	}

	private static bool TryReadHpLastUnit(object data, out float value)
	{
		value = 0f;
		var accessors = GetDataAccessors(data?.GetType());
		return accessors != null && TryReadFloat(data, accessors.HpLastUnitField, accessors.HpLastUnitProperty, out value);
	}

	private static bool TryReadStackCount(object data, out int value)
	{
		value = 0;
		var accessors = GetDataAccessors(data?.GetType());
		return accessors != null && TryReadInt(data, accessors.AllStacksField, accessors.AllStacksProperty, out value);
	}

	private static bool TryReadAliveCreatureCount(object data, out int value)
	{
		value = 0;
		var accessors = GetDataAccessors(data?.GetType());
		if (accessors == null)
		{
			return false;
		}

		if (TryReadInt(data, accessors.AllStacksField, accessors.AllStacksProperty, out value) && value >= 0)
		{
			return true;
		}
		if (TryInvokeInt(data, accessors.AllStacksMethod, out value) && value >= 0)
		{
			return true;
		}

		if (!TryReadInt(data, accessors.FullStacksField, accessors.FullStacksProperty, out var fullStacks))
		{
			return false;
		}
		var tempFullStacks = 0;
		_ = TryReadInt(data, accessors.TempFullStacksField, accessors.TempFullStacksProperty, out tempFullStacks);
		_ = TryReadHpLastUnit(data, out var hpLastUnit);
		value = Mathf.Max(0, fullStacks) + Mathf.Max(0, tempFullStacks) + (hpLastUnit > 0f ? 1 : 0);
		return true;
	}

	private static bool TryReadHpPerFallback(object data, out int value)
	{
		value = 0;
		var accessors = GetDataAccessors(data?.GetType());
		return accessors != null && TryReadInt(data, accessors.HpPerFallbackField, accessors.HpPerFallbackProperty, out value);
	}

	private static UnitAccessors GetUnitAccessors(Type type)
	{
		if (type == null)
			return new UnitAccessors();
		if (UnitAccessorCache.TryGetValue(type, out var accessors))
			return accessors;

		accessors = new UnitAccessors
		{
			DataField = FindField(type, GameSymbols.DamageKill.UnitDataFields),
			DataProperty = FindProperty(type, GameSymbols.DamageKill.UnitDataFields),
			DataGetter = FindMethod(type, GameSymbols.DamageKill.UnitDataGetter.NameHints, Type.EmptyTypes),
			StatsMethod = FindMethod(type, GameSymbols.DamageKill.UnitStatsGetter.NameHints, Type.EmptyTypes),
			StackCountMethod = FindMethod(type, GameSymbols.DamageKill.StackCountGetter.NameHints, Type.EmptyTypes),
			KilledStackMethod = FindMethod(type, GameSymbols.DamageKill.KilledStackGetter.NameHints, new[] { typeof(int) })
		};
		UnitAccessorCache[type] = accessors;
		return accessors;
	}

	private static DataAccessors GetDataAccessors(Type type)
	{
		if (type == null)
			return null;
		if (DataAccessorCache.TryGetValue(type, out var accessors))
			return accessors;

		accessors = new DataAccessors
		{
			HpLastUnitField = FindField(type, GameSymbols.DamageKill.HpLastUnitFields),
			HpLastUnitProperty = FindProperty(type, GameSymbols.DamageKill.HpLastUnitFields),
			AllStacksField = FindField(type, GameSymbols.DamageKill.AllStacksFields),
			AllStacksProperty = FindProperty(type, GameSymbols.DamageKill.AllStacksFields),
			AllStacksMethod = FindMethod(type, GameSymbols.DamageKill.AliveStackCountGetter.NameHints, Type.EmptyTypes),
			FullStacksField = FindField(type, GameSymbols.DamageKill.FullStacksFields),
			FullStacksProperty = FindProperty(type, GameSymbols.DamageKill.FullStacksFields),
			TempFullStacksField = FindField(type, GameSymbols.DamageKill.TempFullStacksFields),
			TempFullStacksProperty = FindProperty(type, GameSymbols.DamageKill.TempFullStacksFields),
			HpPerFallbackField = FindField(type, GameSymbols.DamageKill.HpPerFallbackFields),
			HpPerFallbackProperty = FindProperty(type, GameSymbols.DamageKill.HpPerFallbackFields)
		};
		DataAccessorCache[type] = accessors;
		return accessors;
	}

	private static FieldInfo FindField(Type type, string[] names)
	{
		if (type == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrEmpty(name))
				continue;
			var field = type.GetField(name, MemberFlags);
			if (field != null)
				return field;
		}
		return null;
	}

	private static PropertyInfo FindProperty(Type type, string[] names)
	{
		if (type == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrEmpty(name))
				continue;
			var property = type.GetProperty(name, MemberFlags);
			if (property != null)
				return property;
		}
		return null;
	}

	private static MethodInfo FindMethod(Type type, string[] names, Type[] parameterTypes)
	{
		if (type == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrEmpty(name))
				continue;
			var method = type.GetMethod(name, MemberFlags, null, parameterTypes, null);
			if (method != null)
				return method;
		}
		return null;
	}

	private static bool TryInvokeInt(object instance, MethodInfo method, out int value)
	{
		value = 0;
		if (instance == null || method == null)
		{
			return false;
		}
		try
		{
			var raw = method.Invoke(instance, Array.Empty<object>());
			if (raw == null)
			{
				return false;
			}
			value = Convert.ToInt32(raw);
			return true;
		}
		catch
		{
			value = 0;
			return false;
		}
	}

	private static bool TryInvokeInt(object instance, MethodInfo method, int argument, out int value)
	{
		value = 0;
		if (instance == null || method == null)
		{
			return false;
		}
		try
		{
			var raw = method.Invoke(instance, new object[] { argument });
			if (raw == null)
			{
				return false;
			}
			value = Convert.ToInt32(raw);
			return true;
		}
		catch
		{
			value = 0;
			return false;
		}
	}

	private static bool TryGetMemberValue(object instance, FieldInfo field, PropertyInfo property, out object value)
	{
		value = null;
		if (instance == null)
			return false;
		if (field != null)
		{
			try
			{
				value = field.GetValue(instance);
				return true;
			}
			catch
			{
			}
		}

		if (property == null)
			return false;
		try
		{
			value = property.GetValue(instance, null);
			return true;
		}
		catch
		{
			value = null;
			return false;
		}
	}

	private static bool TryReadInt(object instance, FieldInfo field, PropertyInfo property, out int value)
	{
		value = 0;
		if (!TryGetMemberValue(instance, field, property, out var raw) || raw == null)
			return false;
		try
		{
			value = Convert.ToInt32(raw);
			return true;
		}
		catch
		{
			value = 0;
			return false;
		}
	}

	private static bool TryReadFloat(object instance, FieldInfo field, PropertyInfo property, out float value)
	{
		value = 0f;
		if (!TryGetMemberValue(instance, field, property, out var raw) || raw == null)
			return false;
		try
		{
			value = Convert.ToSingle(raw);
			return true;
		}
		catch
		{
			value = 0f;
			return false;
		}
	}
}
