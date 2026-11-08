using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

internal static class Homm3BattleActionLawRuntime
{
	private static bool _registered;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";
	private static ManualLogSource _log;
	private static readonly object LockObject = new();
	private static readonly HashSet<long> AppliedEventIds = new();
	private static int _patched;
	private static int _observed;
	private static int _applied;
	private static int _failed;
	private static string _lastApplied = "none";
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
			var patched = 0;
			foreach (var typeHint in GameSymbols.BattleEventLaws.BattleEventDispatcherTypeHints)
			{
				var type = GameMember.FindType(GameSymbols.BattleEventLaws.BattleEventDispatcherTypeId + "." + typeHint, typeHint) ?? AccessTools.TypeByName(typeHint);
				if (type == null)
					continue;
				foreach (var methodName in GameSymbols.BattleEventLaws.BattleEventDispatch.NameHints)
					patched += PatchExactVoidMethod(harmony, type, methodName, 2);
			}
			_patched = patched;
			if (patched == 0)
			{
				_registrationAuditStatus = "FAILED_CLOSED: no exact battle-action dispatcher patched";
				log?.LogWarning("HoMM3 battle-action law runtime failed closed: no exact dispatcher hook was patched.");
				return;
			}
			_registrationAuditStatus = "RUNTIME_HOOK_REGISTERED: exact dispatcher patches=" + patched.ToString(System.Globalization.CultureInfo.InvariantCulture);
			log?.LogInfo("HoMM3 battle-action law runtime registered " + patched + " exact dispatcher patch(es).");
		}
		catch (Exception ex)
		{
			_registrationAuditStatus = "FAILED_CLOSED: " + ex.Message;
			log?.LogWarning("HoMM3 battle-action law runtime failed closed during registration: " + ex.Message);
		}
	}

	private static int PatchExactVoidMethod(Harmony harmony, Type type, string methodName, int parameterCount)
	{
		var method = ResolveExactVoidMethod(type, methodName, parameterCount);
		if (method == null)
			return 0;
		var postfix = AccessTools.Method(typeof(Homm3BattleActionLawRuntime), nameof(PostfixEventDispatch));
		if (postfix == null)
			return 0;
		if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
		{
			_log?.LogWarning("HoMM3 battle-action law runtime refused incompatible postfix for " + FormatMethod(method) + ": " + reason);
			return 0;
		}
		harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		return 1;
	}

	private static MethodInfo ResolveExactVoidMethod(Type type, string methodName, int parameterCount)
	{
		if (type == null || string.IsNullOrWhiteSpace(methodName))
			return null;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static))
		{
			if (!string.Equals(method.Name, methodName, StringComparison.Ordinal))
				continue;
			if (method.ReturnType != typeof(void))
				continue;
			if (method.GetParameters().Length != parameterCount)
				continue;
			return method;
		}
		return null;
	}

	private static void PostfixEventDispatch(object __instance, MethodBase __originalMethod, object[] __args)
	{
		try
		{
			if (__args == null)
				return;
			for (var i = 0; i < __args.Length; i++)
				TryApplyForEventObject(__args[i], __originalMethod);
		}
		catch (Exception ex)
		{
			RecordFailure("exception: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static bool TryApplyForEventObject(object eventArgs, MethodBase originalMethod)
	{
		if (eventArgs == null)
			return false;
		if (!Homm3BattleEventNativeAdapter.TryReadCastAbilityEvent(eventArgs, out var eventInfo, out var readFailReason))
			return false;
		_observed++;
		if (eventInfo.Caster == null)
		{
			RecordFailure("cast event has no caster");
			return false;
		}
		var eventId = Homm3DirectStateIdentity.ResolveKeyOrZero(eventArgs);
		lock (LockObject)
		{
			if (AppliedEventIds.Contains(eventId))
				return false;
		}

		if (TryPlanAndArm(eventInfo.Caster, eventArgs, true, originalMethod, out var appliedDetail))
		{
			lock (LockObject)
				AppliedEventIds.Add(eventId);
			RecordApplied(appliedDetail);
			return true;
		}
		if (TryPlanAndArm(eventInfo.Caster, eventArgs, false, originalMethod, out appliedDetail))
		{
			lock (LockObject)
				AppliedEventIds.Add(eventId);
			RecordApplied(appliedDetail);
			return true;
		}
		return false;
	}

	private static bool TryPlanAndArm(object caster, object eventArgs, bool melee, MethodBase originalMethod, out string appliedDetail)
	{
		appliedDetail = null;
		var lawIndex = melee ? Homm3CustomFactionLawRuntime.MeleeFormationIndex : Homm3CustomFactionLawRuntime.RangedFormationIndex;
		if (!Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(caster, lawIndex, out var lawOwner, out var ownerFailReason))
		{
			RecordFailure((melee ? "melee" : "ranged") + " law-owner resolution failed: " + ownerFailReason);
			return false;
		}

        if (!Homm3CustomLawRuntimeGuard.TryResolveAllowedActiveLaw(lawOwner, lawIndex, out _, out var guardFailReason))
        {
            RecordFailure((melee ? "melee" : "ranged") + " combined guard failed: " + guardFailReason);
            return false;
        }
		bool planned;
		Homm3BattleEventNativeAdapter.CastAbilityEventInfo info;
		Homm3CustomLawEffectProfiles.FormationProfile profile;
		Homm3CustomLawRuntimeGuard.AllowedLawContext context;
		Homm3CustomLawEffectPlans.FormationEffectPlan plan;
		string failReason;
		if (melee)
			planned = Homm3CustomBattleEventLawRuntime.TryPlanAllowedMeleeFormationEffect(lawOwner, eventArgs, out info, out profile, out context, out plan, out failReason);
		else
			planned = Homm3CustomBattleEventLawRuntime.TryPlanAllowedRangedFormationEffect(lawOwner, eventArgs, out info, out profile, out context, out plan, out failReason);
		if (!planned)
		{
			RecordFailure((melee ? "melee" : "ranged") + " plan failed: " + failReason);
			return false;
		}
		var percent = Math.Min(40, Math.Max(5, plan.Rank * 10));
		if (!Homm3BattleLocalLawState.TryArmBattleActionOneShotDamage(info.Caster, percent, plan.LawName, out var oldPercent, out var newPercent, out var stateFailReason))
		{
			RecordFailure((melee ? "melee" : "ranged") + " state arm failed: " + stateFailReason);
			return false;
		}
		appliedDetail = (melee ? "melee" : "ranged")
		                + " law=" + context.Law
		                + " effect=" + plan.EffectKey
		                + " oldPercent=" + oldPercent
		                + " newPercent=" + newPercent
		                + " method=" + FormatMethod(originalMethod);
		return true;
	}

	private static void RecordApplied(string detail)
	{
		_applied++;
		_lastApplied = detail ?? "applied";
		_log?.LogInfo("HoMM3 battle-action law runtime armed candidate one-shot damage: " + _lastApplied);
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
		       + ",\"failed\":" + _failed.ToString(System.Globalization.CultureInfo.InvariantCulture)
		       + ",\"lastApplied\":\"" + EscapeJson(_lastApplied) + "\",\"lastFailure\":\"" + EscapeJson(_lastFailure) + "\"}";
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
