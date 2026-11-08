using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic-only scaffold for no-compromise adventure vision/reveal laws.
/// This traces exact fog read/init, native map-magic registry, and magic-vision
/// object descriptor factories. It does not mutate fog, reveal tiles, create
/// map vision objects, change map magic counters, or consume law state.
/// </summary>
internal static class Homm3AdventureVisionLawDiagnostics
{
	internal const string DiagnosticFlag = "homm3_adventure_vision_law_diag.flag";

	private const int LogCap = 120;
	private const int MaxMemberSnapshots = 12;
	private static bool _registered;
	private static int _logged;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;
		_registered = true;

		var patched = 0;
		try
		{
			patched += PatchFogCandidates(harmony, log);
			patched += PatchDataObjectScoutingCandidates(harmony, log);
			patched += PatchMapMagicCandidates(harmony, log);
			patched += PatchMapVisionObjectFactories(harmony, log);
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 adventure vision law diagnostics failed closed during registration: " + ex.Message);
			return;
		}

		if (patched == 0)
		{
			log?.LogWarning("HoMM3 adventure vision law diagnostics found no exact vision/fog surfaces.");
			return;
		}

		log?.LogInfo("HoMM3 adventure vision law diagnostics registered " + patched + " exact trace patch(es). Diagnostic observation only.");
		log?.LogInfo("HoMM3 adventure vision law diagnostics: fog visibility writes/reveal APIs are still unproven; do not implement reveal laws from read-only fog or magic-vision object traces alone.");
	}

	private static int PatchFogCandidates(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.AdventureVisionLawsDataFogOfWar);
		if (type == null)
		{
			log?.LogWarning("HoMM3 adventure vision law diagnostics: DataFogOfWar type not found.");
			return 0;
		}

		var patched = 0;
		patched += PatchExactHints(harmony, log, type, GameSymbols.AdventureVisionLaws.FogInitialize.NameHints, 2, true, nameof(PostfixFogInitialize), "fog-initialize");
		patched += PatchExactHints(harmony, log, type, GameSymbols.AdventureVisionLaws.FogVisibilityRead.NameHints, 1, false, nameof(PostfixFogVisibilityRead), "fog-visibility-read");
		patched += PatchExactHints(harmony, log, type, GameSymbols.AdventureVisionLaws.FogCountCandidate.NameHints, 0, false, nameof(PostfixFogCountCandidate), "fog-count-candidate");
		return patched;
	}

	private static int PatchDataObjectScoutingCandidates(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.AdventureObjectScoutingLawsDataObject);
		if (type == null)
		{
			log?.LogWarning("HoMM3 adventure vision law diagnostics: DataObject type not found.");
			return 0;
		}

		return PatchExactHints(harmony, log, type, GameSymbols.AdventureObjectScoutingLaws.ObjectScoutedBySide.NameHints, 1, true, nameof(PostfixObjectScoutedBySide), "object-scouted-by-side");
	}

	private static int PatchMapMagicCandidates(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.AdventureVisionLawsMapMagics);
		if (type == null)
		{
			log?.LogWarning("HoMM3 adventure vision law diagnostics: MapMagics type not found.");
			return 0;
		}

		var patched = 0;
		patched += PatchExactHints(harmony, log, type, GameSymbols.AdventureVisionLaws.MapMagicAdd.NameHints, 1, true, nameof(PostfixMapMagicAdd), "map-magic-add");
		patched += PatchExactHints(harmony, log, type, GameSymbols.AdventureVisionLaws.MapMagicLookup.NameHints, 1, false, nameof(PostfixMapMagicLookup), "map-magic-lookup");
		return patched;
	}

	private static int PatchMapVisionObjectFactories(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.AdventureVisionLawsMapVisionObjectDesc);
		if (type == null)
		{
			log?.LogWarning("HoMM3 adventure vision law diagnostics: MapVisionObjectDesc type not found.");
			return 0;
		}

		var patched = 0;
		patched += PatchExactHints(harmony, log, type, GameSymbols.AdventureVisionLaws.MapVisionCity.NameHints, 1, false, nameof(PostfixMapVisionCity), "map-vision-city");
		patched += PatchExactHints(harmony, log, type, GameSymbols.AdventureVisionLaws.MapVisionHero.NameHints, 1, false, nameof(PostfixMapVisionHero), "map-vision-hero");
		patched += PatchExactHints(harmony, log, type, GameSymbols.AdventureVisionLaws.MapVisionItem.NameHints, 1, false, nameof(PostfixMapVisionItem), "map-vision-item");
		patched += PatchExactHints(harmony, log, type, GameSymbols.AdventureVisionLaws.MapVisionSquadCandidate.NameHints, 1, false, nameof(PostfixMapVisionSquadCandidate), "map-vision-squad-candidate");
		patched += PatchExactHints(harmony, log, type, GameSymbols.AdventureVisionLaws.MapVisionBySid.NameHints, 1, false, nameof(PostfixMapVisionBySid), "map-vision-by-sid");
		return patched;
	}

	private static int PatchExactHints(Harmony harmony, ManualLogSource log, Type type, string[] methodNames, int parameterCount, bool requireVoid, string postfixName, string stage)
	{
		var patched = 0;
		for (var i = 0; i < methodNames.Length; i++)
			patched += PatchExact(harmony, log, type, methodNames[i], parameterCount, requireVoid, postfixName, stage);
		return patched;
	}

	private static int PatchExact(Harmony harmony, ManualLogSource log, Type type, string methodName, int parameterCount, bool requireVoid, string postfixName, string stage)
	{
		var method = ResolveExactMethod(type, methodName, parameterCount, requireVoid);
		if (method == null)
		{
			log?.LogWarning("HoMM3 adventure vision law diagnostics: exact " + type.FullName + "." + methodName + "(" + parameterCount + " args) not found for " + stage + ".");
			return 0;
		}

		var postfix = AccessTools.Method(typeof(Homm3AdventureVisionLawDiagnostics), postfixName);
		if (postfix == null)
		{
			log?.LogWarning("HoMM3 adventure vision law diagnostics: postfix " + postfixName + " not found.");
			return 0;
		}

		harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		return 1;
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

	private static void PostfixFogInitialize(object __instance, MethodBase __originalMethod, object[] __args) => LogTrace("fog-initialize", __instance, __originalMethod, __args);
	private static void PostfixFogVisibilityRead(object __instance, MethodBase __originalMethod, object[] __args, object __result) => LogTrace("fog-visibility-read", __instance, __originalMethod, __args, __result);
	private static void PostfixFogCountCandidate(object __instance, MethodBase __originalMethod, object __result) => LogTrace("fog-count-candidate", __instance, __originalMethod, null, __result);
	private static void PostfixObjectScoutedBySide(object __instance, MethodBase __originalMethod, object[] __args) => LogTrace("object-scouted-by-side", __instance, __originalMethod, __args);
	private static void PostfixMapMagicAdd(object __instance, MethodBase __originalMethod, object[] __args) => LogTrace("map-magic-add", __instance, __originalMethod, __args);
	private static void PostfixMapMagicLookup(object __instance, MethodBase __originalMethod, object[] __args, object __result) => LogTrace("map-magic-lookup", __instance, __originalMethod, __args, __result);
	private static void PostfixMapVisionCity(MethodBase __originalMethod, object[] __args, object __result) => LogTrace("map-vision-city", null, __originalMethod, __args, __result);
	private static void PostfixMapVisionHero(MethodBase __originalMethod, object[] __args, object __result) => LogTrace("map-vision-hero", null, __originalMethod, __args, __result);
	private static void PostfixMapVisionItem(MethodBase __originalMethod, object[] __args, object __result) => LogTrace("map-vision-item", null, __originalMethod, __args, __result);
	private static void PostfixMapVisionSquadCandidate(MethodBase __originalMethod, object[] __args, object __result) => LogTrace("map-vision-squad-candidate", null, __originalMethod, __args, __result);
	private static void PostfixMapVisionBySid(MethodBase __originalMethod, object[] __args, object __result) => LogTrace("map-vision-by-sid", null, __originalMethod, __args, __result);

	private static void LogTrace(string stage, object instance, MethodBase method, object[] args, object result = null)
	{
		try
		{
			if (_logged >= LogCap)
				return;
			_logged++;

			Plugin.LogSource?.LogInfo(
				"HoMM3 adventure vision law diagnostic: "
				+ stage
				+ " method="
				+ DescribeMethod(method)
				+ " instance="
				+ DescribeObjectContext(instance)
				+ " args="
				+ DescribeArgs(args)
				+ " result="
				+ DescribeObjectContext(result)
				+ " visionPlan="
				+ DescribeVisionPlan(instance, args, result)
				+ " handlerGate="
				+ Homm3CustomLawHandlerTrace.Describe(
					instance,
					Homm3CustomLawHandlerTrace.VisionReveal)
				+ ". Diagnostic observation only.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 adventure vision law diagnostic log failed: " + ex.Message);
		}
	}

	private static string DescribeMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}

	private static string DescribeVisionPlan(object instance, object[] args, object result)
	{
		var failures = new List<string>(8);
		if (TryDescribeVisionPlanFromOwner("instance", instance, out var direct, failures))
			return direct;
		if (args != null)
		{
			for (var i = 0; i < args.Length; i++)
			{
				if (TryDescribeVisionPlanFromOwner("arg" + i, args[i], out var fromArg, failures))
					return fromArg;
			}
		}
		if (TryDescribeVisionPlanFromOwner("result", result, out var fromResult, failures))
			return fromResult;
		return failures.Count == 0
			? "unresolved:no vision owner candidates"
			: "unresolved:[" + string.Join(";", failures) + "]";
	}

	private static bool TryDescribeVisionPlanFromOwner(string label, object owner, out string description, List<string> failures)
	{
		description = null;
		if (owner == null)
		{
			failures?.Add(label + "=null");
			return false;
		}
		if (Homm3CustomVisionLawRuntime.TryPlanCandidateVisionEffect(
			    owner,
			    out var profile,
			    out var context,
			    out var side,
			    out var plan,
			    out var failReason))
		{
			description = label + "={side=" + side + " context={" + context + "} profile={" + profile + "} plan={" + plan + "}}";
			return true;
		}
		failures?.Add(label + "=" + failReason);
		return false;
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
}
