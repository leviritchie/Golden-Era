using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic-only scaffold for no-compromise custom construction laws.
/// Static generated interop evidence identifies these as town/building UI and
/// candidate construction-state surfaces. Runtime logs must prove commit/cost
/// ordering before any law mutates build limits, costs, resources, or town state.
/// </summary>
internal static class Homm3CustomConstructionLawDiagnostics
{
	internal const string DiagnosticFlag = "homm3_custom_construction_law_diag.flag";

	private const int LogCap = 320;
	private const int MaxMemberSnapshots = 12;
	private static bool _registered;
	private static int _logged;
	private static readonly Dictionary<string, int> LoggedByStage = new(StringComparer.Ordinal);

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
			patched += PatchBuildingsManagerCandidates(harmony, log);
			patched += PatchBuildingSessionCandidates(harmony, log);
			patched += PatchBuildingViewCandidates(harmony, log);
			// June 18 runtime note: do not patch BuildingData constructed-state mutation here.
			// The town/economy pilot crashed exactly when construction was committed, and this
			// candidate is the only construction diagnostic on the commit mutation path. Keep the
			// safer UI/session/manager traces for ordering evidence until a native-friendly commit
			// proof surface is identified.
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 custom construction law diagnostics failed closed during registration: " + ex.Message);
			return;
		}

		if (patched == 0)
		{
			log?.LogWarning("HoMM3 custom construction law diagnostics found no exact construction/town surfaces.");
			return;
		}

		log?.LogInfo("HoMM3 custom construction law diagnostics registered " + patched + " exact trace patch(es). Diagnostic observation only.");
		log?.LogInfo("HoMM3 custom construction law diagnostics: these are candidate surfaces only; runtime ordering must prove cost display, charged cost, build validation, and committed construction before gameplay hooks consume them.");
		log?.LogInfo("HoMM3 custom construction law diagnostics: active-law state is attempted only through the shared exact resolver; none-or-unresolved is not negative gameplay evidence.");
	}

	private static int PatchBuildingsManagerCandidates(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.ConstructionLawsBuildingsManager);
		if (type == null)
		{
			log?.LogWarning("HoMM3 custom construction law diagnostics: BhBuildingsManager type not found.");
			return 0;
		}

		var patched = 0;
		patched += PatchExact(harmony, log, type, GameSymbols.ConstructionLaws.BuildingsManagerStateCandidate.NameHints, typeof(void), new[] { "dwc", "Boolean" }, nameof(PostfixBuildingsManagerStateCandidate), "buildings-manager-state-candidate");
		patched += PatchExact(harmony, log, type, GameSymbols.ConstructionLaws.BuildingsManagerLookupCandidate.NameHints, null, new[] { "String" }, nameof(PostfixBuildingsManagerLookupCandidate), "buildings-manager-lookup-candidate");
		patched += PatchExact(harmony, log, type, GameSymbols.ConstructionLaws.BuildingsManagerRefreshCandidate.NameHints, typeof(void), Array.Empty<string>(), nameof(PostfixBuildingsManagerRefreshCandidate), "buildings-manager-refresh-candidate");
		return patched;
	}

	private static int PatchBuildingSessionCandidates(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.ConstructionLawsBuildingSession);
		if (type == null)
		{
			log?.LogWarning("HoMM3 custom construction law diagnostics: BhUIBuildingSession type not found.");
			return 0;
		}

		var patched = 0;
		patched += PatchExact(harmony, log, type, GameSymbols.ConstructionLaws.BuildingSessionCostCandidate.NameHints, typeof(int), new[] { "Int32", "Int32" }, nameof(PostfixBuildingSessionCostCandidate), "building-session-cost-candidate");
		patched += PatchExact(harmony, log, type, GameSymbols.ConstructionLaws.BuildingSessionSelectCandidate.NameHints, typeof(void), new[] { "bfh" }, nameof(PostfixBuildingSessionSelectCandidate), "building-session-select-candidate");
		return patched;
	}

	private static int PatchBuildingViewCandidates(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.ConstructionLawsBuildingView);
		if (type == null)
		{
			log?.LogWarning("HoMM3 custom construction law diagnostics: BhBuildingView type not found.");
			return 0;
		}

		var patched = 0;
		// June 19 runtime note: skip building-view-bind-candidate. After removing the
		// direct constructed-state mutation hook, construction still crashed and the last
		// repeated construction trace was BhBuildingView bind/rebind. Keep the less invasive
		// manager/session/update traces active for construction ordering evidence.
		// patched += PatchExact(harmony, log, type, GameSymbols.ConstructionLaws.BuildingViewBindCandidate.NameHints, typeof(void), new[] { "fbs", "dwc", "Int32" }, nameof(PostfixBuildingViewBindCandidate), "building-view-bind-candidate");
		// June 19 runtime note: skip building-view-update-candidate. After building-view
		// bind was removed, construction advanced to menu close and then crashed while
		// repeated BhBuildingView.UpdateView diagnostics were the last construction traces.
		// Keep manager/session traces active; avoid patching hot view lifecycle methods.
		// patched += PatchExact(harmony, log, type, GameSymbols.ConstructionLaws.BuildingViewUpdateCandidate.NameHints, typeof(void), Array.Empty<string>(), nameof(PostfixBuildingViewUpdateCandidate), "building-view-update-candidate");
		patched += PatchExact(harmony, log, type, GameSymbols.ConstructionLaws.BuildingViewCostCheckCandidate.NameHints, typeof(bool), new[] { "ResNameAndCost[]" }, nameof(PostfixBuildingViewCostCheckCandidate), "building-view-cost-check-candidate");
		return patched;
	}

	private static int PatchBuildingDataCandidates(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.ConstructionCommitLawsBuildingData);
		if (type == null)
		{
			log?.LogWarning("HoMM3 custom construction law diagnostics: BuildingData type not found.");
			return 0;
		}

		return PatchExact(harmony, log, type, GameSymbols.ConstructionCommitLaws.BuildingConstructStateMutation.NameHints, typeof(void), new[] { "Int32", "Boolean" }, nameof(PostfixBuildingConstructStateMutation), "building-data-construct-state-mutation");
	}

	private static int PatchExact(Harmony harmony, ManualLogSource log, Type type, string[] methodNames, Type requiredReturnType, string[] parameterTypeNames, string postfixName, string stage)
	{
		var method = ResolveExactMethod(type, methodNames, requiredReturnType, parameterTypeNames, stage, log);
		if (method == null)
		{
			log?.LogWarning("HoMM3 custom construction law diagnostics: exact " + type.FullName + " method not found for " + stage + ".");
			return 0;
		}

		var postfix = AccessTools.Method(typeof(Homm3CustomConstructionLawDiagnostics), postfixName);
		if (postfix == null)
		{
			log?.LogWarning("HoMM3 custom construction law diagnostics: postfix " + postfixName + " not found.");
			return 0;
		}

		harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		return 1;
	}

	private static MethodInfo ResolveExactMethod(Type type, string[] names, Type requiredReturnType, string[] parameterTypeNames, string stage, ManualLogSource log)
	{
		var methods = AccessTools.GetDeclaredMethods(type);
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			foreach (var method in methods)
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal))
					continue;
				if (!SignatureMatches(method, requiredReturnType, parameterTypeNames))
					continue;
				log?.LogInfo("HoMM3 custom construction law diagnostics: exact named method " + DescribeMethod(method) + " accepted for " + stage + ".");
				return method;
			}
		}

		log?.LogWarning("HoMM3 custom construction law diagnostics: no exact named method found for " + stage + "; refusing signature-only binding.");
		return null;
	}

	private static bool SignatureMatches(MethodInfo method, Type requiredReturnType, string[] parameterTypeNames)
	{
		if (method == null || method.IsSpecialName)
			return false;
		if (requiredReturnType != null && method.ReturnType != requiredReturnType)
			return false;
		var parameters = method.GetParameters();
		parameterTypeNames ??= Array.Empty<string>();
		if (parameters.Length != parameterTypeNames.Length)
			return false;
		for (var i = 0; i < parameters.Length; i++)
		{
			var expected = parameterTypeNames[i];
			if (string.IsNullOrWhiteSpace(expected))
				continue;
			var actual = parameters[i].ParameterType;
			var actualName = actual.Name;
			var actualFullName = actual.FullName ?? actualName;
			var actualObfuscatedName = GameMember.ReadObfuscatedName(actual);
			if (!string.Equals(actualName, expected, StringComparison.Ordinal)
			    && !string.Equals(actualFullName, expected, StringComparison.Ordinal)
			    && !actualFullName.EndsWith("." + expected, StringComparison.Ordinal)
			    && !string.Equals(actualObfuscatedName, expected, StringComparison.Ordinal))
				return false;
		}
		return true;
	}

	private static void PostfixBuildingsManagerStateCandidate(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("buildings-manager-state-candidate", __instance, __originalMethod, __args);
	}

	private static void PostfixBuildingsManagerLookupCandidate(object __instance, MethodBase __originalMethod, object[] __args, object __result)
	{
		LogTrace("buildings-manager-lookup-candidate", __instance, __originalMethod, __args, __result);
	}

	private static void PostfixBuildingsManagerRefreshCandidate(object __instance, MethodBase __originalMethod)
	{
		LogTrace("buildings-manager-refresh-candidate", __instance, __originalMethod, null);
	}

	private static void PostfixBuildingSessionCostCandidate(object __instance, MethodBase __originalMethod, object[] __args, object __result)
	{
		LogTrace("building-session-cost-candidate", __instance, __originalMethod, __args, __result);
	}

	private static void PostfixBuildingSessionSelectCandidate(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("building-session-select-candidate", __instance, __originalMethod, __args);
	}

	private static void PostfixBuildingViewBindCandidate(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("building-view-bind-candidate", __instance, __originalMethod, __args);
	}

	private static void PostfixBuildingViewUpdateCandidate(object __instance, MethodBase __originalMethod)
	{
		LogTrace("building-view-update-candidate", __instance, __originalMethod, null);
	}

	private static void PostfixBuildingViewCostCheckCandidate(object __instance, MethodBase __originalMethod, object[] __args, bool __result)
	{
		LogTrace("building-view-cost-check-candidate", __instance, __originalMethod, __args, __result);
	}

	private static void PostfixBuildingConstructStateMutation(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("building-data-construct-state-mutation", __instance, __originalMethod, __args);
	}

	private static void LogTrace(string stage, object instance, MethodBase method, object[] args, object result = null)
	{
		try
		{
			if (_logged >= LogCap)
				return;
			if (!TryConsumeStageBudget(stage))
				return;
			_logged++;

			Plugin.LogSource?.LogInfo(
				"HoMM3 custom construction law diagnostic: "
				+ stage
				+ " method="
				+ DescribeMethod(method)
				+ " instance="
				+ DescribeObjectContext(instance)
				+ " args="
				+ DescribeArgs(args)
				+ " result="
				+ DescribeObjectContext(result)
				+ " constructionPlan="
				+ DescribeConstructionPlan(instance, args, result)
				+ " handlerGate="
				+ Homm3CustomLawHandlerTrace.Describe(
					instance,
					Homm3CustomLawHandlerTrace.ConstructionCommit)
				+ ". Diagnostic observation only.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 custom construction law diagnostic log failed: " + ex.Message);
		}
	}

	private static bool TryConsumeStageBudget(string stage)
	{
		if (!LoggedByStage.TryGetValue(stage, out var count))
			count = 0;

		var limit = stage switch
		{
			"building-session-cost-candidate" => 96,
			"building-session-select-candidate" => 96,
			"economy-resource-add-candidate" => 96,
			"building-manager-lookup-candidate" => 48,
			"building-manager-refresh-candidate" => 48,
			"building-manager-state-candidate" => 48,
			"building-view-bind-candidate" => 24,
			"building-view-update-candidate" => 12,
			"building-view-cost-check-candidate" => 96,
			"building-data-construct-state-mutation" => 96,
			_ => 32,
		};

		if (count >= limit)
			return false;

		LoggedByStage[stage] = count + 1;
		return true;
	}

	private static string DescribeMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}

	private static string DescribeConstructionPlan(object instance, object[] args, object result)
	{
		var failures = new List<string>(8);
		if (TryDescribeConstructionPlanFromOwner("instance", instance, out var direct, failures))
			return direct;
		if (args != null)
		{
			for (var i = 0; i < args.Length; i++)
			{
				if (TryDescribeConstructionPlanFromOwner("arg" + i, args[i], out var fromArg, failures))
					return fromArg;
			}
		}
		if (TryDescribeConstructionPlanFromOwner("result", result, out var fromResult, failures))
			return fromResult;
		return failures.Count == 0
			? "unresolved:no construction owner candidates"
			: "unresolved:[" + string.Join(";", failures) + "]";
	}

	private static bool TryDescribeConstructionPlanFromOwner(string label, object owner, out string description, List<string> failures)
	{
		description = null;
		if (owner == null)
		{
			failures?.Add(label + "=null");
			return false;
		}
		if (Homm3CustomConstructionLawRuntime.TryPlanCandidateConstructionEffect(
			    owner,
			    out var profile,
			    out var context,
			    out var plan,
			    out var failReason))
		{
			description = label + "={context={" + context + "} profile={" + profile + "} plan={" + plan + "}}";
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
