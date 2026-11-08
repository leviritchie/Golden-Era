using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic-only first slice for restoring no-compromise Counterstroke Doctrine laws.
/// Static evidence on June 16 shows dxy.bate/ldn/cec call edb.bcry only when
/// CastDealerConfig.triggerCounter is true. This hook proves that request/event
/// surface in the running build before any law mutates combat state.
/// </summary>
internal static class Homm3CounterstrokeDoctrineHook
{
	internal const string DiagnosticFlag = "homm3_counterstroke_doctrine_diag.flag";

	private const int LogCap = 80;
	private const int MaxMemberSnapshots = 12;
	private static bool _registered;
	private static int _logged;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_registered = true;

		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;

		var patched = 0;
		try
		{
			patched += PatchTriggerRequestMethods(harmony, log);
			patched += PatchTriggerDispatcher(harmony, log);
			patched += PatchDamageCandidateMethods(harmony, log);
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 Counterstroke Doctrine diagnostics failed closed during registration: " + ex.Message);
			return;
		}

		if (patched == 0)
		{
			log?.LogWarning("HoMM3 Counterstroke Doctrine diagnostics found no exact counterattack surfaces; custom Counterstroke laws remain disabled.");
			return;
		}

		log?.LogInfo("HoMM3 Counterstroke Doctrine diagnostics registered " + patched + " exact trace patch(es). Diagnostic observation only.");
		log?.LogInfo("HoMM3 Counterstroke Doctrine diagnostics: law gate is custom law index "
			+ Homm3CustomFactionLawRuntime.CounterstrokeDoctrineIndex
			+ " ("
			+ Homm3CustomFactionLawRuntime.CounterstrokeDoctrineFamily
			+ "); active rank is not consumed until runtime law resolution is proven.");
	}

	private static int PatchTriggerRequestMethods(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.CounterstrokeDoctrineAbilityExecution);
		if (type == null)
		{
			log?.LogWarning("HoMM3 Counterstroke Doctrine diagnostics: dxy ability execution type not found.");
			return 0;
		}

		var postfix = AccessTools.Method(typeof(Homm3CounterstrokeDoctrineHook), nameof(PostfixTriggerRequest));
		if (postfix == null)
			return 0;

		var patched = 0;
		foreach (var name in GameSymbols.CounterstrokeDoctrine.TriggeringAbilityExecuteMethods)
		{
			var method = ResolveExactVoidMethod(type, name, parameterCount: 2);
			if (method == null)
			{
				log?.LogWarning("HoMM3 Counterstroke Doctrine diagnostics: exact dxy." + name + "(2 args) not found.");
				continue;
			}

			var hm = new HarmonyMethod(postfix) { priority = Priority.Last };
			harmony.Patch(method, postfix: hm);
			patched++;
		}

		return patched;
	}

	private static int PatchTriggerDispatcher(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.CounterstrokeDoctrineEventDispatcher);
		if (type == null)
		{
			log?.LogWarning("HoMM3 Counterstroke Doctrine diagnostics: edb event dispatcher type not found.");
			return 0;
		}

		var method = ResolveExactVoidMethod(type, GameSymbols.CounterstrokeDoctrine.TriggerCounterDispatcher.NameHints[0], parameterCount: 2);
		if (method == null)
		{
			log?.LogWarning("HoMM3 Counterstroke Doctrine diagnostics: exact edb.bcry(object, BattleEventArgs) not found.");
			return 0;
		}

		var postfix = AccessTools.Method(typeof(Homm3CounterstrokeDoctrineHook), nameof(PostfixTriggerDispatcher));
		if (postfix == null)
			return 0;

		var hm = new HarmonyMethod(postfix) { priority = Priority.Last };
		harmony.Patch(method, postfix: hm);
		return 1;
	}

	private static int PatchDamageCandidateMethods(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.CounterstrokeDoctrineDamageCalculator);
		if (type == null)
		{
			log?.LogWarning("HoMM3 Counterstroke Doctrine diagnostics: ell damage calculator type not found.");
			return 0;
		}

		var postfix = AccessTools.Method(typeof(Homm3CounterstrokeDoctrineHook), nameof(PostfixDamageCandidate));
		if (postfix == null)
			return 0;

		var patched = 0;
		foreach (var name in GameSymbols.CounterstrokeDoctrine.DamageCandidateMethods)
		{
			var method = ResolveExactMethod(type, name, parameterCount: 2, requireVoid: false);
			if (method == null)
			{
				log?.LogWarning("HoMM3 Counterstroke Doctrine diagnostics: exact ell." + name + "(DamageUiParams,bool) candidate not found.");
				continue;
			}

			var hm = new HarmonyMethod(postfix) { priority = Priority.Last };
			harmony.Patch(method, postfix: hm);
			patched++;
		}

		return patched;
	}

	private static MethodInfo ResolveExactVoidMethod(Type type, string name, int parameterCount)
	{
		return ResolveExactMethod(type, name, parameterCount, requireVoid: true);
	}

	private static MethodInfo ResolveExactMethod(Type type, string name, int parameterCount, bool requireVoid)
	{
		var methods = AccessTools.GetDeclaredMethods(type);
		foreach (var method in methods)
		{
			if (!string.Equals(method.Name, name, StringComparison.Ordinal))
				continue;
			if (method.IsSpecialName)
				continue;
			if (requireVoid && method.ReturnType != typeof(void))
				continue;
			if (method.GetParameters().Length != parameterCount)
				continue;
			return method;
		}

		return null;
	}

	private static void PostfixTriggerRequest(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("request", __instance, __originalMethod, __args);
	}

	private static void PostfixTriggerDispatcher(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("dispatch", __instance, __originalMethod, __args);
	}

	private static void PostfixDamageCandidate(object __instance, MethodBase __originalMethod, object[] __args, object __result)
	{
		LogTrace("damage-candidate", __instance, __originalMethod, __args, __result);
	}

	private static void LogTrace(string stage, object instance, MethodBase originalMethod, object[] args, object result = null)
	{
		try
		{
			if (_logged >= LogCap)
				return;
			_logged++;

			Plugin.LogSource?.LogInfo(
				"HoMM3 Counterstroke Doctrine diagnostic: "
				+ stage
				+ " method="
				+ DescribeMethod(originalMethod)
				+ " instance="
				+ DescribeObjectContext(instance)
				+ " args="
				+ DescribeArgs(args)
				+ " result="
				+ DescribeObjectContext(result)
				+ ". Diagnostic observation only.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 Counterstroke Doctrine diagnostic log failed: " + ex.Message);
		}
	}

	private static string DescribeMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}

	private static string DescribeObject(object value)
	{
		if (value == null)
			return "null";
		return value.GetType().FullName ?? value.GetType().Name;
	}

	private static string DescribeObjectContext(object value)
	{
		if (value == null)
			return "null";

		var type = value.GetType();
		var parts = new List<string>(MaxMemberSnapshots + 2)
		{
			"type=" + (type.FullName ?? type.Name)
		};

		var obfuscated = GameMember.ReadObfuscatedName(type);
		if (!string.IsNullOrEmpty(obfuscated))
			parts.Add("obf=" + obfuscated);

		parts.Add("activeKnownCustomLawsFromThisObject=" + DescribeActiveKnownCustomLaws(value));
		AddSimpleMemberSnapshots(value, type, parts);
		return "{" + string.Join("|", parts) + "}";
	}

	private static string DescribeActiveKnownCustomLaws(object owner)
	{
		if (owner == null)
			return "null";

		var lawParts = new List<string>(8);
		foreach (var lawIndex in Homm3CustomFactionLawRuntime.KnownRuntimeLawIndices)
		{
			if (!Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw(owner, lawIndex, out var state))
				continue;
			lawParts.Add("index=" + state.Index
			             + ",rank=" + state.Rank
			             + ",faction=" + state.FactionSid
			             + ",family=" + state.Family);
			if (lawParts.Count >= 8)
				break;
		}

		return lawParts.Count == 0 ? "none-or-unresolved" : "[" + string.Join(";", lawParts) + "]";
	}

	private static void AddSimpleMemberSnapshots(object value, Type type, List<string> parts)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var current = type; current != null && parts.Count < MaxMemberSnapshots; current = current.BaseType)
		{
			foreach (var field in current.GetFields(flags))
			{
				if (field.IsStatic)
					continue;
				if (!TryFormatSimpleValue(field.FieldType, () => field.GetValue(value), out var formatted))
					continue;
				parts.Add(field.Name + "=" + formatted);
				if (parts.Count >= MaxMemberSnapshots)
					return;
			}

			foreach (var property in current.GetProperties(flags))
			{
				if (parts.Count >= MaxMemberSnapshots)
					return;
				if (property.GetIndexParameters().Length != 0)
					continue;
				var getter = property.GetGetMethod(nonPublic: true);
				if (getter == null || getter.IsStatic)
					continue;
				if (!TryFormatSimpleValue(property.PropertyType, () => property.GetValue(value, null), out var formatted))
					continue;
				parts.Add(property.Name + "=" + formatted);
			}
		}
	}

	private static bool TryFormatSimpleValue(Type valueType, Func<object> read, out string formatted)
	{
		formatted = null;
		try
		{
			var raw = read();
			if (raw == null)
			{
				formatted = "null";
				return true;
			}

			var runtimeType = raw.GetType();
			if (!IsSimpleType(valueType) && !IsSimpleType(runtimeType))
				return false;

			var text = raw.ToString();
			if (string.IsNullOrEmpty(text))
				text = "(empty)";
			if (text.Length > 80)
				text = text.Substring(0, 80) + "...";
			formatted = text;
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static bool IsSimpleType(Type type)
	{
		if (type == null)
			return false;
		if (type.IsPrimitive || type.IsEnum)
			return true;
		return type == typeof(string)
		       || type == typeof(decimal)
		       || type == typeof(IntPtr)
		       || type == typeof(UIntPtr);
	}

	private static string DescribeArgs(object[] args)
	{
		if (args == null || args.Length == 0)
			return "[]";

		var parts = new string[args.Length];
		for (var i = 0; i < args.Length; i++)
			parts[i] = DescribeObjectContext(args[i]);
		return "[" + string.Join(",", parts) + "]";
	}
}
