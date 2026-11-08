using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Runtime bridge from native Rampart Avenger buff-adds into the custom visible
/// marker used by the law runtime. Damage-time recognition accepts battle-local
/// state or the custom marker SID; the native Avenger SID is only the creation
/// trigger for that marker.
/// </summary>
internal static class Homm3RampartAvengerMarkerRuntime
{
	private const int LogCap = 48;
	private static bool _registered;
	private static int _logged;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";

	internal static string RegistrationAuditStatus => _registrationAuditStatus;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_registered = true;


		var type = GameMember.FindType(
			GameSymbols.BuffDebuffLaws.BuffManagerTypeId,
			GameSymbols.BuffDebuffLaws.BuffManagerTypeHint);
		if (type == null)
		{
			_registrationAuditStatus = "FAILED_CLOSED: exact buff manager type not found";
			log?.LogWarning("HoMM3 Rampart Avenger marker runtime failed closed: exact buff manager type not found.");
			return;
		}

		var patched = 0;
		var seen = new System.Collections.Generic.HashSet<MethodInfo>();
		foreach (var name in GameSymbols.BuffDebuffLaws.BuffAdd.NameHints)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var method = ResolveExactBuffAddMethod(type, name);
			if (method == null)
			{
				log?.LogWarning("HoMM3 Rampart Avenger marker runtime: exact " + type.FullName + "." + name + "(6 args) not found.");
				continue;
			}
			if (!seen.Add(method))
				continue;

			var postfix = AccessTools.Method(typeof(Homm3RampartAvengerMarkerRuntime), nameof(PostfixBuffAdd));
			if (postfix == null)
			{
				log?.LogWarning("HoMM3 Rampart Avenger marker runtime failed closed: postfix method not found.");
				continue;
			}
			if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
			{
				log?.LogWarning("HoMM3 Rampart Avenger marker runtime: refusing incompatible postfix for " + FormatMethod(method) + ": " + reason);
				continue;
			}

			harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
			patched++;
		}

		if (patched == 0)
		{
			_registrationAuditStatus = "FAILED_CLOSED: exact buff add method was not patched";
			log?.LogWarning("HoMM3 Rampart Avenger marker runtime failed closed: exact buff add method was not patched.");
			return;
		}

		_registrationAuditStatus = "REGISTERED_EXACT_POSTFIX_PATCHES=" + patched.ToString(System.Globalization.CultureInfo.InvariantCulture);
		log?.LogInfo("HoMM3 Rampart Avenger marker runtime registered " + patched + " exact buff-add postfix patch(es).");
	}

	internal static bool TrySynchronizeMarkFromReceiver(object receiver, out int oldMarkCount, out int newMarkCount, out string detail, out string failReason)
	{
		oldMarkCount = 0;
		newMarkCount = 0;
		detail = null;
		if (receiver == null)
		{
			failReason = "Avenger marker sync requires exact receiver battle unit";
			return false;
		}
		if (Homm3BattleLocalLawState.TryRequireRampartAvengerMark(receiver, out var localMarkCount, out var localFailReason))
		{
			oldMarkCount = localMarkCount;
			newMarkCount = localMarkCount;
			detail = "battleLocalAvengerMark; localMarkCount=" + localMarkCount.ToString(System.Globalization.CultureInfo.InvariantCulture);
			failReason = null;
			return true;
		}

		if (!Homm3BuffDebuffNativeAdapter.TryQueryAnyBuffSidFromReceiver(receiver, GameSymbols.RampartAvengerLaws.CustomMarkerBuffSids, out var customInfo, out failReason))
		{
			failReason = "no battle-local Avenger mark; custom Avenger marker query failed: local miss={" + localFailReason + "}; " + failReason;
			return false;
		}
		if (!customInfo.HasSid)
		{
			failReason = "no battle-local or custom Avenger marker is present: local miss={" + localFailReason + "}; customInfo={" + customInfo + "}";
			return false;
		}
		return TrySynchronizeKnownMarker(receiver, customInfo, "customAvengerMarker", out oldMarkCount, out newMarkCount, out detail, out failReason);
	}
	private static bool TrySynchronizeKnownMarker(
		object receiver,
		Homm3BuffDebuffNativeAdapter.BuffQueryInfo info,
		string markerKind,
		out int oldMarkCount,
		out int newMarkCount,
		out string detail,
		out string failReason)
	{
		oldMarkCount = 0;
		newMarkCount = 0;
		detail = null;
		if (Homm3BattleLocalLawState.TryRequireRampartAvengerMark(receiver, out var existingMarkCount, out _))
		{
			oldMarkCount = existingMarkCount;
			newMarkCount = existingMarkCount;
			detail = markerKind + "={" + info + "}; localMarkCount=" + existingMarkCount.ToString(System.Globalization.CultureInfo.InvariantCulture);
			failReason = null;
			return true;
		}
		if (!Homm3BattleLocalLawState.TryMarkRampartAvengerTarget(receiver, out oldMarkCount, out newMarkCount, out failReason, applyMarker: false))
			return false;
		detail = markerKind + "={" + info + "}; localMarkInitialized=true";
		failReason = null;
		return true;
	}

	private static void PostfixBuffAdd(object __instance, MethodBase __originalMethod, object[] __args, object __result)
	{
		try
		{
			if (__args == null || __args.Length < 3 || __args[0] is not string sid)
				return;
			if (!GameSymbols.RampartAvengerLaws.TryDescribeMarkBuffSid(sid, out var avengerDescription))
				return;

			var receiver = ReadFirstExactMember(__instance, __instance?.GetType(), GameSymbols.BuffDebuffLaws.BuffManagerReceiverMembers);
			if (receiver == null)
			{
				LogLimited("HoMM3 Rampart Avenger marker runtime failed closed: buff-add receiver was not resolved for " + sid + " (" + avengerDescription + ") method=" + FormatMethod(__originalMethod) + ".");
				return;
			}
			if (!TryReadPositiveIntArg(__args, 1, "level", out var level, out var readFailReason)
			    || !TryReadPositiveIntArg(__args, 2, "duration", out var duration, out readFailReason))
			{
				LogLimited("HoMM3 Rampart Avenger marker runtime failed closed: " + readFailReason + " sid=" + sid + " method=" + FormatMethod(__originalMethod) + ".");
				return;
			}
			if (!Homm3BattleLocalLawState.TryMarkRampartAvengerTarget(
				receiver,
				out var oldMarkCount,
				out var newMarkCount,
				out var failReason,
				applyMarker: true,
				markerDuration: duration,
				markerSource: "Rampart Avenger native mark mirror"))
			{
				LogLimited("HoMM3 Rampart Avenger marker runtime failed closed: custom visual marker was not applied for native Avenger buff; " + failReason + " sid=" + sid + " markerSid=" + Homm3CustomLawVisualMarkerRuntime.AvengerIntensity + " duration=" + duration.ToString(System.Globalization.CultureInfo.InvariantCulture) + " method=" + FormatMethod(__originalMethod) + ".");
				return;
			}

			LogLimited("HoMM3 Rampart Avenger marker runtime recorded native mark with required custom visual marker: sid=" + sid + " description=" + avengerDescription + " markerSid=" + Homm3CustomLawVisualMarkerRuntime.AvengerIntensity + " nativeLevel=" + level.ToString(System.Globalization.CultureInfo.InvariantCulture) + " duration=" + duration.ToString(System.Globalization.CultureInfo.InvariantCulture) + " oldMarkCount=" + oldMarkCount + " newMarkCount=" + newMarkCount + " receiver=" + DescribeObject(receiver) + " method=" + FormatMethod(__originalMethod) + ".");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 Rampart Avenger marker runtime failed closed during buff-add postfix: " + ex.Message);
		}
	}

	private static bool TryReadPositiveIntArg(object[] args, int index, string name, out int value, out string failReason)
	{
		value = 0;
		if (args == null || index < 0 || index >= args.Length || args[index] is not int intValue)
		{
			failReason = "native Avenger buff-add " + name + " argument is not an Int32";
			return false;
		}
		if (intValue <= 0)
		{
			failReason = "native Avenger buff-add " + name + " argument is not positive: " + intValue.ToString(System.Globalization.CultureInfo.InvariantCulture);
			return false;
		}
		value = intValue;
		failReason = null;
		return true;
	}

	private static MethodInfo ResolveExactBuffAddMethod(Type type, string name)
	{
		if (type == null || string.IsNullOrWhiteSpace(name))
			return null;
		foreach (var method in AccessTools.GetDeclaredMethods(type))
		{
			if (!string.Equals(method.Name, name, StringComparison.Ordinal))
				continue;
			if (method.IsSpecialName || method.ReturnType == typeof(void))
				continue;
			if (method.GetParameters().Length != 6)
				continue;
			return method;
		}
		return null;
	}

	private static object ReadFirstExactMember(object value, Type type, string[] names)
	{
		if (value == null || type == null || names == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var property = type.GetProperty(name, flags);
			if (property != null && property.GetIndexParameters().Length == 0)
			{
				try { return property.GetValue(value); }
				catch { }
			}
			var field = type.GetField(name, flags);
			if (field != null)
			{
				try { return field.GetValue(value); }
				catch { }
			}
			var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
			if (method != null && method.ReturnType != typeof(void))
			{
				try { return method.Invoke(value, Array.Empty<object>()); }
				catch { }
			}
		}
		return null;
	}

	private static void LogLimited(string message)
	{
		Homm3CandidateSurfaceRuntimeCounters.Record(message);
		if (_logged >= LogCap)
			return;
		_logged++;
		Plugin.LogSource?.LogInfo(message);
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "null";
		return method.DeclaringType?.FullName + "." + method.Name;
	}

	private static string DescribeObject(object value)
	{
		if (value == null)
			return "null";
		var type = value.GetType();
		return type.FullName ?? type.Name;
	}
}

