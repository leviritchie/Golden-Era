using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

internal static class Homm3MoraleTriggerLawRuntime
{
	private static bool _registered;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";
	private static ManualLogSource _log;
	private static int _patched;
	private static int _observed;
	private static int _applied;
	private static int _unimplemented;
	private static int _failed;
	private static string _lastApplied = "none";
	private static string _lastUnimplemented = "none";
	private static string _lastFailure = "none";

	internal static string RegistrationAuditStatus => _registrationAuditStatus;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_registered = true;
		_log = log;
		try
		{
			var battleLogicType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.MoraleTriggerLawsBattleLogic);
			var unitType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.BattleEventLawsBattleUnit);
			if (battleLogicType == null || unitType == null)
			{
				_registrationAuditStatus = "FAILED_CLOSED: morale battle logic or unit type missing";
				return;
			}
			var patched = 0;
			patched += PatchExactMoraleMethod(harmony, battleLogicType, unitType, GameSymbols.MoraleTriggerLaws.PositiveMoraleRoll, 2, false);
			patched += PatchExactMoraleMethod(harmony, battleLogicType, unitType, GameSymbols.MoraleTriggerLaws.NegativeMoraleRoll, 3, true);
			_patched = patched;
			if (patched == 0)
			{
				_registrationAuditStatus = "FAILED_CLOSED: no exact morale roll surfaces patched";
				log?.LogWarning("HoMM3 morale-trigger law runtime failed closed: no exact morale roll surfaces patched.");
				return;
			}
			_registrationAuditStatus = "RUNTIME_HOOK_REGISTERED: exact morale patches=" + patched.ToString(System.Globalization.CultureInfo.InvariantCulture);
			log?.LogInfo("HoMM3 morale-trigger law runtime registered " + patched + " exact morale patch(es).");
		}
		catch (Exception ex)
		{
			_registrationAuditStatus = "FAILED_CLOSED: " + ex.Message;
			log?.LogWarning("HoMM3 morale-trigger law runtime failed closed during registration: " + ex.Message);
		}
	}

	private static int PatchExactMoraleMethod(Harmony harmony, Type battleLogicType, Type unitType, GameSymbols.MethodSymbol symbol, int parameterCount, bool requiresThirdBool)
	{
		var method = ResolveExactMoraleMethod(battleLogicType, unitType, symbol, parameterCount, requiresThirdBool);
		if (method == null)
			return 0;
		var postfix = AccessTools.Method(typeof(Homm3MoraleTriggerLawRuntime), nameof(PostfixMoraleRoll));
		if (postfix == null)
			return 0;
		if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
		{
			_log?.LogWarning("HoMM3 morale-trigger law runtime refused incompatible postfix for " + FormatMethod(method) + ": " + reason);
			return 0;
		}
		harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		return 1;
	}

	private static MethodInfo ResolveExactMoraleMethod(Type battleLogicType, Type unitType, GameSymbols.MethodSymbol symbol, int parameterCount, bool requiresThirdBool)
	{
		if (battleLogicType == null || unitType == null || symbol.NameHints == null)
			return null;
		foreach (var method in battleLogicType.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static))
		{
			if (method.ReturnType != typeof(bool) || method.GetParameters().Length != parameterCount)
				continue;
			if (!NameMatches(method.Name, symbol.NameHints))
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length == 0 || !unitType.IsAssignableFrom(parameters[0].ParameterType))
				continue;
			if (requiresThirdBool && (parameters.Length < 3 || parameters[2].ParameterType != typeof(bool)))
				continue;
			return method;
		}
		return null;
	}

	private static bool NameMatches(string name, string[] hints)
	{
		if (string.IsNullOrWhiteSpace(name) || hints == null)
			return false;
		for (var i = 0; i < hints.Length; i++)
			if (string.Equals(name, hints[i], StringComparison.Ordinal))
				return true;
		return false;
	}

	private static void PostfixMoraleRoll(object __instance, MethodBase __originalMethod, object[] __args, bool __result)
	{
		try
		{
			if (__args == null || __args.Length == 0)
				return;
			for (var i = 0; i < __args.Length; i++)
				TryApplyForUnit(__args[i], __originalMethod, __result);
		}
		catch (Exception ex)
		{
			RecordFailure("exception: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static bool TryApplyForUnit(object unit, MethodBase moraleMethod, bool rollResult)
	{
		if (unit == null)
			return false;
		if (!Homm3CustomMoraleLawRuntime.TryPlanAllowedMoraleTriggerEffectForUnit(unit, moraleMethod, rollResult, out var observation, out var profile, out var lawOwner, out var context, out var plan, out var failReason))
			return false;
		_observed++;
		if (string.Equals(profile.EffectKey, "castle.native-morale-package", StringComparison.Ordinal))
		{
			RecordUnimplemented("Castle native morale package remains native row only; runtime skipped intentionally.");
			return false;
		}
		if (string.Equals(profile.EffectKey, "cove.crew-momentum", StringComparison.Ordinal))
		{
			var delta = Math.Max(1, profile.FocusDelta > 0 ? profile.FocusDelta : profile.Rank);
			if (!Homm3FocusNativeAdapter.TryGrantFocusToSide(lawOwner, delta, out var focusFailReason))
			{
				RecordFailure("Cove morale Focus grant failed: " + focusFailReason);
				return false;
			}
			RecordApplied("law=" + context.Law + " effect=" + profile.EffectKey + " focusDelta=" + delta + " observation=" + observation);
			return true;
		}
		if (string.Equals(profile.EffectKey, "rampart.protect-preserve-avenger-momentum", StringComparison.Ordinal))
		{
			if (!Homm3BattleLocalLawState.TryRequireRampartAvengerMark(unit, out var markCount, out var markFailReason))
			{
				RecordFailure("Rampart morale Avenger mark predicate failed: " + markFailReason);
				return false;
			}
			return TryArmMoraleDamage(unit, profile, context, observation, Math.Min(30, Math.Max(10, profile.Rank * 10 + markCount * 5)));
		}
		if (string.Equals(profile.EffectKey, "conflux.elemental-family-resonance", StringComparison.Ordinal)
		    || string.Equals(profile.EffectKey, "stronghold.damage-kill-tempo", StringComparison.Ordinal))
		{
			return TryArmMoraleDamage(unit, profile, context, observation, Math.Min(30, Math.Max(10, profile.Rank * 10)));
		}
		RecordUnimplemented("no morale-trigger mutator implemented for effect=" + profile.EffectKey + " law=" + context.Law + " observation=" + observation);
		return false;
	}

	private static bool TryArmMoraleDamage(object unit, Homm3CustomLawEffectProfiles.MoraleTriggerProfile profile, Homm3CustomLawRuntimeGuard.AllowedLawContext context, Homm3MoraleTriggerNativeAdapter.MoraleRollObservation observation, int percent)
	{
		if (!Homm3BattleLocalLawState.TryArmMoraleOneShotDamage(unit, percent, profile.LawName, out var oldPercent, out var newPercent, out var failReason))
		{
			RecordFailure("morale one-shot state arm failed: " + failReason);
			return false;
		}
		RecordApplied("law=" + context.Law + " effect=" + profile.EffectKey + " oldPercent=" + oldPercent + " newPercent=" + newPercent + " observation=" + observation);
		return true;
	}

	private static void RecordApplied(string detail)
	{
		_applied++;
		_lastApplied = detail ?? "applied";
		_log?.LogInfo("HoMM3 morale-trigger law runtime applied candidate mutation: " + _lastApplied);
	}

	private static void RecordUnimplemented(string detail)
	{
		_unimplemented++;
		_lastUnimplemented = detail ?? "unknown";
	}

	private static void RecordFailure(string detail)
	{
		_failed++;
		_lastFailure = detail ?? "unknown";
	}

	internal static string SnapshotJson()
	{
		return "{\"registration\":\"" + EscapeJson(_registrationAuditStatus) + "\",\"patched\":" + _patched.ToString(System.Globalization.CultureInfo.InvariantCulture)
		       + ",\"observed\":" + _observed.ToString(System.Globalization.CultureInfo.InvariantCulture)
		       + ",\"applied\":" + _applied.ToString(System.Globalization.CultureInfo.InvariantCulture)
		       + ",\"unimplemented\":" + _unimplemented.ToString(System.Globalization.CultureInfo.InvariantCulture)
		       + ",\"failed\":" + _failed.ToString(System.Globalization.CultureInfo.InvariantCulture)
		       + ",\"lastApplied\":\"" + EscapeJson(_lastApplied) + "\",\"lastUnimplemented\":\"" + EscapeJson(_lastUnimplemented) + "\",\"lastFailure\":\"" + EscapeJson(_lastFailure) + "\"}";
	}

	private static string FormatMethod(MethodBase method)
	{
		return method == null ? "<null>" : method.DeclaringType?.FullName + "." + method.Name;
	}

	private static string EscapeJson(string value)
	{
		return (value ?? string.Empty).Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n");
	}
}
