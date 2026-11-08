using System;
using System.Collections;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Creates the custom Avenger marker from the Rampart hero action-bar Avenger cast.
/// Runtime proof is still pending because the current deployed DLL was not built
/// with the live probe workbench enabled.
/// </summary>
internal static class Homm3RampartAvengerCastMarkerRuntime
{
	private const int LogCap = 64;
	private static bool _registered;
	private static ManualLogSource _log;
	private static readonly object LockObject = new();
	private static readonly System.Collections.Generic.HashSet<long> HandledEventIds = new();
	private static int _patched;
	private static int _observedAvengerCasts;
	private static int _applied;
	private static int _failed;
	private static int _logged;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";
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
				_registrationAuditStatus = "FAILED_CLOSED: no exact Avenger cast dispatcher patched";
				log?.LogWarning("HoMM3 Rampart Avenger cast marker runtime failed closed: no exact dispatcher hook was patched.");
				return;
			}
			_registrationAuditStatus = "RUNTIME_HOOK_REGISTERED: exact dispatcher patches=" + patched.ToString(System.Globalization.CultureInfo.InvariantCulture);
			log?.LogInfo("HoMM3 Rampart Avenger cast marker runtime registered " + patched + " exact dispatcher patch(es). Runtime proof still required.");
		}
		catch (Exception ex)
		{
			_registrationAuditStatus = "FAILED_CLOSED: " + ex.Message;
			log?.LogWarning("HoMM3 Rampart Avenger cast marker runtime failed closed during registration: " + ex.Message);
		}
	}

	private static int PatchExactVoidMethod(Harmony harmony, Type type, string methodName, int parameterCount)
	{
		var method = ResolveExactVoidMethod(type, methodName, parameterCount);
		if (method == null)
			return 0;
		var postfix = AccessTools.Method(typeof(Homm3RampartAvengerCastMarkerRuntime), nameof(PostfixEventDispatch));
		if (postfix == null)
			return 0;
		if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
		{
			_log?.LogWarning("HoMM3 Rampart Avenger cast marker runtime refused incompatible postfix for " + FormatMethod(method) + ": " + reason);
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
		if (!Homm3BattleEventNativeAdapter.TryReadCastAbilityEvent(eventArgs, out var eventInfo, out _))
			return false;
		if (!eventInfo.HasAbilityName(GameSymbols.RampartAvengerLaws.AbilitySid))
			return false;

		_observedAvengerCasts++;
		var eventId = Homm3DirectStateIdentity.ResolveKeyOrZero(eventArgs);
		lock (LockObject)
		{
			if (HandledEventIds.Contains(eventId))
				return false;
			HandledEventIds.Add(eventId);
		}

		if (eventInfo.Caster == null)
		{
			RecordFailure("Avenger cast event has no caster: " + eventInfo);
			return false;
		}
		if (!TryReadSingleAttackedObject(eventInfo.AttackedObjects, out var target, out var targetFailReason))
		{
			RecordFailure("Avenger cast target failed closed: " + targetFailReason + " event={" + eventInfo + "} method=" + FormatMethod(originalMethod));
			return false;
		}
		if (!Homm3BattleLocalLawState.TryMarkRampartAvengerTarget(
			    target,
			    out var oldMarkCount,
			    out var newMarkCount,
			    out var markFailReason,
			    markerDuration: 99,
			    markerSource: "Rampart Avenger hero cast"))
		{
			RecordFailure("Avenger cast marker failed closed: " + markFailReason + " event={" + eventInfo + "} method=" + FormatMethod(originalMethod));
			return false;
		}

		RecordApplied("ability=" + GameSymbols.RampartAvengerLaws.AbilitySid
		              + " oldMarkCount=" + oldMarkCount.ToString(System.Globalization.CultureInfo.InvariantCulture)
		              + " newMarkCount=" + newMarkCount.ToString(System.Globalization.CultureInfo.InvariantCulture)
		              + " target=" + DescribeObject(target)
		              + " method=" + FormatMethod(originalMethod));
		return true;
	}

	private static bool TryReadSingleAttackedObject(object attackedObjects, out object target, out string failReason)
	{
		target = null;
		if (attackedObjects == null)
		{
			failReason = "CastAbilityEventArgs.attackedObjects is null";
			return false;
		}
		if (attackedObjects is not IEnumerable enumerable || attackedObjects is string)
		{
			failReason = "CastAbilityEventArgs.attackedObjects is not an enumerable target list: " + DescribeObject(attackedObjects);
			return false;
		}

		var count = 0;
		foreach (var item in enumerable)
		{
			if (item == null)
			{
				failReason = "CastAbilityEventArgs.attackedObjects contains a null target";
				return false;
			}
			count++;
			if (count == 1)
			{
				target = item;
				continue;
			}
			failReason = "Rampart Avenger marker expects exactly one attacked object; observed at least two";
			target = null;
			return false;
		}
		if (count == 1)
		{
			failReason = null;
			return true;
		}
		failReason = "Rampart Avenger marker expects exactly one attacked object; observed zero";
		return false;
	}

	private static void RecordApplied(string detail)
	{
		_applied++;
		_lastApplied = detail ?? "applied";
		LogLimited("HoMM3 Rampart Avenger cast marker runtime applied marker: " + _lastApplied + ".");
	}

	private static void RecordFailure(string detail)
	{
		_failed++;
		_lastFailure = detail ?? "unknown";
		LogLimited("HoMM3 Rampart Avenger cast marker runtime failed closed: " + _lastFailure + ".");
	}

	private static void LogLimited(string message)
	{
		Homm3CandidateSurfaceRuntimeCounters.Record(message);
		if (_logged >= LogCap)
			return;
		_logged++;
		_log?.LogInfo(message);
	}

	internal static string SnapshotJson()
	{
		return "{\"registration\":\"" + EscapeJson(_registrationAuditStatus) + "\",\"patched\":" + _patched.ToString(System.Globalization.CultureInfo.InvariantCulture)
		       + ",\"observedAvengerCasts\":" + _observedAvengerCasts.ToString(System.Globalization.CultureInfo.InvariantCulture)
		       + ",\"applied\":" + _applied.ToString(System.Globalization.CultureInfo.InvariantCulture)
		       + ",\"failed\":" + _failed.ToString(System.Globalization.CultureInfo.InvariantCulture)
		       + ",\"lastApplied\":\"" + EscapeJson(_lastApplied) + "\",\"lastFailure\":\"" + EscapeJson(_lastFailure) + "\"}";
	}

	private static string FormatMethod(MethodBase method)
	{
		return method == null ? "<null>" : method.DeclaringType?.FullName + "." + method.Name;
	}

	private static string DescribeObject(object value)
	{
		if (value == null)
			return "null";
		var type = value.GetType();
		return type.FullName ?? type.Name;
	}

	private static string EscapeJson(string value)
	{
		return (value ?? string.Empty).Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n");
	}
}
