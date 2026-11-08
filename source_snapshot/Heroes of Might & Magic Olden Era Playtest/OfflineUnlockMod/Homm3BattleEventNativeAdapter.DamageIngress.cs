using System;
using System.Reflection;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.Runtime;

namespace OfflineUnlockMod;

/// <summary>
/// Damage-surface normalization: single unwrap of caster/ability identity and
/// committed-damage shape into Homm3DirectStateIngressOutcome.
/// </summary>
internal static partial class Homm3BattleEventNativeAdapter
{
	internal static Homm3DirectStateIngressOutcome NormalizeDamageApplyInvocation(
		Homm3DirectStateHookSurface surface,
		object receiverUnit,
		object casterArg,
		object castSourceArg,
		object damageDealerArg,
		int damage,
		object fromMech,
		bool immuneToDamage,
		bool cumulative)
	{
		if (surface != Homm3DirectStateHookSurface.DamageApplying
		    && surface != Homm3DirectStateHookSurface.DamageApplied)
		{
			return Homm3DirectStateIngressOutcome.Fail(
				surface,
				"damage normalize requires DamageApplying or DamageApplied surface");
		}
		if (receiverUnit == null)
			return Homm3DirectStateIngressOutcome.Reject(surface, "damage receiver Unit instance is null");
		// Best-effort Unit unwrap: prefer arg0, then dealer; adapters that require identity
		// also use TryResolveUnitSid for TransferUnit/configSid paths.
		if (!TryResolveBattleUnit(casterArg, out var caster)
		    && !TryResolveBattleUnit(damageDealerArg, out caster))
			caster = casterArg;
		var info = new DamageEventInfo(
			caster,
			receiverUnit,
			castSourceArg,
			damageDealerArg,
			damage,
			0,
			immuneToDamage,
			cumulative,
			fromMech);
		TryResolveAbilityName(castSourceArg, damageDealerArg, out var abilityName);
		return Homm3DirectStateIngressOutcome.AcceptDamage(surface, info, abilityName);
	}

	internal static bool TryResolveBattleUnit(object value, out object unit)
	{
		unit = null;
		if (value == null)
			return false;
		if (value is Unit concrete)
		{
			unit = concrete;
			return true;
		}
		var wrapped = TryWrapAsUnit(value);
		if (wrapped != null)
		{
			unit = wrapped;
			return true;
		}
		// Exact eab.self route (bbce) before FieldObject scans.
		if (TryInvokeNamedNoArg(value, GameSymbols.BuffDebuffLaws.BuffSourceSelfMembers, out var self)
		    && self != null
		    && !ReferenceEquals(self, value))
		{
			if (self is Unit selfUnit)
			{
				unit = selfUnit;
				return true;
			}
			var wrappedSelf = TryWrapAsUnit(self);
			if (wrappedSelf != null)
			{
				unit = wrappedSelf;
				return true;
			}
		}
		if (TryReadExactMember(
			    value,
			    value.GetType(),
			    GameSymbols.BuffDebuffLaws.BuffReceiverObjectMembers,
			    out var fieldObject)
		    && fieldObject != null)
		{
			if (fieldObject is Unit fieldUnit)
			{
				unit = fieldUnit;
				return true;
			}
			var wrappedField = TryWrapAsUnit(fieldObject);
			if (wrappedField != null)
			{
				unit = wrappedField;
				return true;
			}
		}
		return TryMatchRegisteredUnitByPointer(value, out unit);
	}

	/// <summary>
	/// Resolve a battle unit SID for mechanic lookup without reading live IL2CPP string
	/// pointers (Il2CppStringToManaged is fatal on corrupted pointers during DamageApplied).
	/// Prefer the managed SID captured at Unit.Init; fall back only to typed TransferUnit.configSid.
	/// </summary>
	internal static bool TryResolveUnitSid(object unit, out string sid)
	{
		sid = null;
		if (unit == null)
			return false;

		if (Homm3BattleUnitLawOwnerRegistry.TryGetRegisteredConfigSid(unit, out var registered)
		    && !string.IsNullOrWhiteSpace(registered))
		{
			sid = registered;
			return true;
		}

		TransferUnit transfer = null;
		if (TryReadExactMember(unit, unit.GetType(), GameSymbols.BattleVisual.BattleUnitTransferFields, out var transferRaw)
		    && transferRaw != null)
		{
			transfer = transferRaw as TransferUnit
			           ?? (transferRaw is Il2CppObjectBase transferObj && transferObj.Pointer != IntPtr.Zero
				           ? transferObj.TryCast<TransferUnit>()
				           : null);
		}
		if (transfer == null)
			return false;
		try
		{
			var transferTyped = transfer.configSid;
			if (string.IsNullOrWhiteSpace(transferTyped))
				return false;
			sid = transferTyped.Trim();
			return true;
		}
		catch
		{
			return false;
		}
	}

	internal static bool TryResolveAbilityName(
		object castSourceArg,
		object damageDealerArg,
		out string abilityName)
	{
		if (TryReadAbilityName(castSourceArg, out abilityName)
		    || TryReadAbilityName(damageDealerArg, out abilityName))
			return true;
		if (TryReadAbilityNameFromDealerConfigs(castSourceArg, out abilityName)
		    || TryReadAbilityNameFromDealerConfigs(damageDealerArg, out abilityName))
			return true;
		abilityName = null;
		return false;
	}

	internal static bool IsAbilityNameMatch(string expectedAbilityName, string observedAbilityName)
	{
		if (string.IsNullOrWhiteSpace(expectedAbilityName) || string.IsNullOrWhiteSpace(observedAbilityName))
			return false;
		if (string.Equals(expectedAbilityName, observedAbilityName, StringComparison.Ordinal))
			return true;
		if (observedAbilityName.IndexOf(expectedAbilityName, StringComparison.OrdinalIgnoreCase) >= 0)
			return true;
		if (expectedAbilityName.IndexOf(observedAbilityName, StringComparison.OrdinalIgnoreCase) >= 0)
			return true;
		// Allow lang-key forms only when the expected display name itself contains the token
		// (e.g. expected "Shoulder Check" vs observed "...abilities_0..." / "...shoulder...").
		if (expectedAbilityName.IndexOf("shoulder", StringComparison.OrdinalIgnoreCase) >= 0
		    && (observedAbilityName.IndexOf("shoulder", StringComparison.OrdinalIgnoreCase) >= 0
		        || observedAbilityName.IndexOf("abilities_0", StringComparison.OrdinalIgnoreCase) >= 0))
		{
			Plugin.LogSource?.LogInfo(
				"HoMM3 direct-state ability soft-match: expected="
				+ expectedAbilityName
				+ " observed="
				+ observedAbilityName);
			return true;
		}
		return false;
	}

	private static object TryWrapAsUnit(object value)
	{
		if (value is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return null;
		try
		{
			var method = typeof(Il2CppObjectPool).GetMethod(
				"Get",
				BindingFlags.Public | BindingFlags.Static,
				null,
				new[] { typeof(IntPtr) },
				null);
			if (method == null || !method.IsGenericMethodDefinition)
				return null;
			return method.MakeGenericMethod(typeof(Unit)).Invoke(null, new object[] { il2Cpp.Pointer }) as Unit;
		}
		catch
		{
			return null;
		}
	}

	private static bool TryMatchRegisteredUnitByPointer(object value, out object unit)
	{
		unit = null;
		if (value is not Il2CppObjectBase needle || needle.Pointer == IntPtr.Zero)
			return false;
		var snapshots = Homm3BattleUnitLawOwnerRegistry.SnapshotUnits(64);
		for (var i = 0; i < snapshots.Count; i++)
		{
			var candidate = snapshots[i].Unit;
			if (candidate is not Il2CppObjectBase candidateIl2Cpp || candidateIl2Cpp.Pointer == IntPtr.Zero)
				continue;
			if (candidateIl2Cpp.Pointer != needle.Pointer)
				continue;
			unit = candidate;
			return true;
		}
		return false;
	}

	private static bool TryReadAbilityName(object value, out string abilityName)
	{
		abilityName = null;
		if (value == null)
			return false;
		if (TryReadExactMember(
			    value,
			    value.GetType(),
			    GameSymbols.BattleEventLaws.CastAbilityNameMembers,
			    out var rawName)
		    && rawName is string exactName
		    && !string.IsNullOrWhiteSpace(exactName))
		{
			abilityName = exactName.Trim();
			return true;
		}
		var text = value.ToString();
		if (!string.IsNullOrWhiteSpace(text)
		    && text.IndexOf("Shoulder Check", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			abilityName = "Shoulder Check";
			return true;
		}
		return false;
	}

	private static bool TryReadAbilityNameFromDealerConfigs(object castSource, out string abilityName)
	{
		abilityName = null;
		if (castSource == null)
			return false;
		var getters = GameSymbols.DamageCastSource.PrimaryDamageDealerGetters;
		for (var i = 0; i < getters.Length; i++)
		{
			if (!TryInvokeNoArg(castSource, getters[i], out var dealer) || dealer == null)
				continue;
			if (TryReadAbilityName(dealer, out abilityName))
				return true;
			if (TryReadExactMember(
				    dealer,
				    dealer.GetType(),
				    GameSymbols.BattleEventLaws.CastAbilityNameMembers,
				    out var nested)
			    && nested is string nestedName
			    && !string.IsNullOrWhiteSpace(nestedName))
			{
				abilityName = nestedName.Trim();
				return true;
			}
		}
		return false;
	}

	private static bool TryInvokeNamedNoArg(object value, string[] methodNames, out object result)
	{
		result = null;
		if (value == null || methodNames == null)
			return false;
		for (var i = 0; i < methodNames.Length; i++)
		{
			if (TryInvokeNoArg(value, methodNames[i], out result) && result != null)
				return true;
		}
		return false;
	}

	private static bool TryInvokeNoArg(object value, string methodName, out object result)
	{
		result = null;
		if (value == null || string.IsNullOrWhiteSpace(methodName))
			return false;
		for (var current = value.GetType(); current != null && current != typeof(object); current = current.BaseType)
		{
			try
			{
				var method = current.GetMethod(
					methodName,
					BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
					null,
					Type.EmptyTypes,
					null);
				if (method == null)
					continue;
				result = method.Invoke(value, null);
				return true;
			}
			catch
			{
				return false;
			}
		}
		return false;
	}

	private static string DescribeTypeName(object value)
	{
		return value == null ? "null" : (value.GetType().FullName ?? value.GetType().Name);
	}
}
