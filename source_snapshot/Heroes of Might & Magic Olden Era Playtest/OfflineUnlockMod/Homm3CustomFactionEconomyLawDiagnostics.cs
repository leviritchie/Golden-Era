using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic-only scaffold for no-compromise custom economy law work.
/// This traces exact side day-start and resource-add surfaces so reward/capture
/// and day-start economy laws can later fail closed on proven native events.
/// </summary>
internal static class Homm3CustomFactionEconomyLawDiagnostics
{
	internal const string DiagnosticFlag = "homm3_custom_faction_economy_diag.flag";

	private const int LogCap = 160;
	private const int MaxMemberSnapshots = 10;
	private static bool _registered;
	private static int _logged;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";
	[ThreadStatic]
	private static int _traceSuppressionDepth;

	internal static string RegistrationAuditStatus => _registrationAuditStatus;

	internal static IDisposable SuppressTraceForExactBridgeResourceMutation()
	{
		_traceSuppressionDepth++;
		return new TraceSuppressionScope();
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
		{
			_registrationAuditStatus = "DIAGNOSTIC_FLAG_NOT_ENABLED";
			return;
		}
		_registered = true;

		var patched = 0;
		try
		{
			patched += PatchSideStartDay(harmony, log);
			patched += PatchResourceAdd(harmony, log);
			patched += PatchResourceSpendIfAvailable(harmony, log);
			patched += PatchResourceDataMethods(harmony, log);
			patched += PatchResHeapDataMethods(harmony, log);
		}
		catch (Exception ex)
		{
			_registrationAuditStatus = "FAILED_CLOSED: " + ex.Message;
			log?.LogWarning("HoMM3 custom economy law diagnostics failed closed during registration: " + ex.Message);
			return;
		}

		if (patched == 0)
		{
			_registrationAuditStatus = "FAILED_CLOSED: no exact startup hook surfaces patched";
			log?.LogWarning("HoMM3 custom economy law diagnostics found no exact economy surfaces.");
			return;
		}

		_registrationAuditStatus = "DIAGNOSTIC_HOOK_REGISTERED: exact trace patches=" + patched.ToString(System.Globalization.CultureInfo.InvariantCulture);
		log?.LogInfo("HoMM3 custom economy law diagnostics registered " + patched + " exact trace patch(es). Diagnostic observation only.");
		log?.LogInfo("HoMM3 custom economy law diagnostics: active-law state is attempted only through the shared exact resolver; none-or-unresolved is not negative gameplay evidence.");
	}

	private static int PatchSideStartDay(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.FindType(
			GameSymbols.EconomyLaws.SideLogicTypeId,
			GameSymbols.EconomyLaws.SideLogicTypeHint);
		if (type == null)
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: exact dtj side logic type not found.");
			return 0;
		}

		var method = AccessTools.Method(type, GameSymbols.EconomyLaws.SideStartDayName, Type.EmptyTypes);
		if (method == null)
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: exact dtj.OnStartDay() not found.");
			return 0;
		}

		harmony.Patch(method, postfix: new HarmonyMethod(typeof(Homm3CustomFactionEconomyLawDiagnostics), nameof(PostfixSideStartDay)) { priority = Priority.Last });
		return 1;
	}

	private static int PatchResourceAdd(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.FindType(
			GameSymbols.EconomyLaws.ResourceWrapperTypeId,
			GameSymbols.EconomyLaws.ResourceWrapperTypeHint);
		if (type == null)
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: exact dti resource wrapper type not found.");
			return 0;
		}

		var method = GameMember.FindFirstMethod(
			type,
			typeof(void),
			new[] { typeof(string), typeof(int) },
			GameSymbols.EconomyLaws.AddResource);
		if (method == null)
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: exact resource add method not found.");
			return 0;
		}

		harmony.Patch(method, prefix: new HarmonyMethod(typeof(Homm3CustomFactionEconomyLawDiagnostics), nameof(PrefixResourceAdd)) { priority = Priority.Last });
		return 1;
	}

	private static int PatchResourceSpendIfAvailable(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.FindType(
			GameSymbols.EconomyLaws.ResourceWrapperTypeId,
			GameSymbols.EconomyLaws.ResourceWrapperTypeHint);
		if (type == null)
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: exact dti resource wrapper type not found for spend trace.");
			return 0;
		}

		var method = GameMember.FindFirstMethod(
			type,
			typeof(bool),
			new[] { typeof(string), typeof(int) },
			GameSymbols.EconomyLaws.SpendResourceIfAvailable);
		if (method == null)
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: exact resource spend-if-available wrapper method not found.");
			return 0;
		}

		var prefix = AccessTools.Method(typeof(Homm3CustomFactionEconomyLawDiagnostics), nameof(PrefixResourceSpendIfAvailable));
		if (prefix == null)
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: spend prefix not found.");
			return 0;
		}
		if (!GameMember.IsHarmonyPatchCompatible(method, prefix, out var reason))
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: refusing incompatible spend prefix for " + DescribeMethod(method) + ": " + reason);
			return 0;
		}

				var postfix = AccessTools.Method(typeof(Homm3CustomFactionEconomyLawDiagnostics), nameof(PostfixResourceSpendIfAvailable));
		if (postfix == null)
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: spend postfix not found.");
			return 0;
		}
		if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var postfixReason))
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: refusing incompatible spend postfix for " + DescribeMethod(method) + ": " + postfixReason);
			return 0;
		}

		harmony.Patch(method, prefix: new HarmonyMethod(prefix) { priority = Priority.First }, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		log?.LogInfo("HoMM3 custom economy law diagnostics: exact named method " + DescribeMethod(method) + " accepted for resource-spend-if-available.");
		return 1;
	}
	private static int PatchResourceDataMethods(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.EconomyLawsResourceData);
		if (type == null)
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: Resource data type not found.");
			return 0;
		}

		var patched = 0;
		patched += PatchExact(harmony, log, type, GameSymbols.EconomyLaws.ResourceSetValue.NameHints, typeof(void), new[] { "Int32" }, nameof(PostfixResourceDataSet), "resource-data-set");
		patched += PatchExact(harmony, log, type, GameSymbols.EconomyLaws.ResourceAddValue.NameHints, typeof(void), new[] { "Int32" }, nameof(PostfixResourceDataAdd), "resource-data-add");
		log?.LogInfo("HoMM3 custom economy law diagnostics: resource-data-subtract-if-available primitive intentionally not patched; use dti.ymk wrapper for spend tracing.");
		return patched;
	}

	private static int PatchResHeapDataMethods(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.EconomyLawsResHeapData);
		if (type == null)
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: ResHeap data type not found.");
			return 0;
		}

		return PatchExact(harmony, log, type, GameSymbols.EconomyLaws.ResHeapApply.NameHints, typeof(bool), new[] { "ResHeap", "Boolean" }, nameof(PostfixResHeapDataApply), "res-heap-data-apply");
	}

	private static int PatchExactWithPrefix(Harmony harmony, ManualLogSource log, Type type, string[] methodNames, Type requiredReturnType, string[] parameterTypeNames, string prefixName, string postfixName, string stage)
	{
		var method = ResolveExactMethod(type, methodNames, requiredReturnType, parameterTypeNames, stage, log);
		if (method == null)
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: exact " + type.FullName + " method not found for " + stage + ".");
			return 0;
		}

		var prefix = AccessTools.Method(typeof(Homm3CustomFactionEconomyLawDiagnostics), prefixName);
		var postfix = AccessTools.Method(typeof(Homm3CustomFactionEconomyLawDiagnostics), postfixName);
		if (prefix == null || postfix == null)
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: prefix/postfix not found for " + stage + ".");
			return 0;
		}
		if (!GameMember.IsHarmonyPatchCompatible(method, prefix, out var prefixReason))
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: refusing incompatible prefix for " + DescribeMethod(method) + ": " + prefixReason);
			return 0;
		}
		if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var postfixReason))
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: refusing incompatible postfix for " + DescribeMethod(method) + ": " + postfixReason);
			return 0;
		}

		harmony.Patch(method, prefix: new HarmonyMethod(prefix) { priority = Priority.First }, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		log?.LogInfo("HoMM3 custom economy law diagnostics: exact named method " + DescribeMethod(method) + " accepted for " + stage + ".");
		return 1;
	}
	private static int PatchExact(Harmony harmony, ManualLogSource log, Type type, string[] methodNames, Type requiredReturnType, string[] parameterTypeNames, string postfixName, string stage)
	{
		var method = ResolveExactMethod(type, methodNames, requiredReturnType, parameterTypeNames, stage, log);
		if (method == null)
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: exact " + type.FullName + " method not found for " + stage + ".");
			return 0;
		}

		var postfix = AccessTools.Method(typeof(Homm3CustomFactionEconomyLawDiagnostics), postfixName);
		if (postfix == null)
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: postfix " + postfixName + " not found.");
			return 0;
		}

		if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
		{
			log?.LogWarning("HoMM3 custom economy law diagnostics: refusing incompatible postfix for " + DescribeMethod(method) + ": " + reason);
			return 0;
		}

		harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		log?.LogInfo("HoMM3 custom economy law diagnostics: exact named method " + DescribeMethod(method) + " accepted for " + stage + ".");
		return 1;
	}

	private static MethodInfo ResolveExactMethod(Type type, string[] names, Type requiredReturnType, string[] parameterTypeNames, string stage, ManualLogSource log)
	{
		foreach (var methodName in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(methodName))
				continue;
			foreach (var method in AccessTools.GetDeclaredMethods(type))
			{
				if (!string.Equals(method.Name, methodName, StringComparison.Ordinal))
					continue;
				if (!SignatureMatches(method, requiredReturnType, parameterTypeNames))
					continue;
				return method;
			}
		}

		log?.LogWarning("HoMM3 custom economy law diagnostics: no exact named method found for " + stage + "; refusing signature-only binding.");
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

	private static void PostfixSideStartDay(object __instance, MethodBase __originalMethod)
	{
		LogTrace("side-start-day", __instance, __originalMethod, null);
	}

	private static void PrefixResourceAdd(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("resource-add", __instance, __originalMethod, __args);
	}

	private static void PrefixResourceSpendIfAvailable(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("resource-spend-if-available-prefix", __instance, __originalMethod, __args);
	}

	private static void PostfixResourceSpendIfAvailable(object __instance, MethodBase __originalMethod, object[] __args, bool __result)
	{
		LogTrace("resource-spend-if-available", __instance, __originalMethod, __args, __result);
	}

	private static void PrefixResourceDataSubtractIfAvailable(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("resource-data-subtract-if-available-prefix", __instance, __originalMethod, __args);
	}

	private static void PostfixResourceDataSet(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("resource-data-set", __instance, __originalMethod, __args);
	}

	private static void PostfixResourceDataAdd(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("resource-data-add", __instance, __originalMethod, __args);
	}

	private static void PostfixResourceDataSubtractIfAvailable(object __instance, MethodBase __originalMethod, object[] __args, bool __result)
	{
		LogTrace("resource-data-subtract-if-available", __instance, __originalMethod, __args, __result);
	}

	private static void PostfixResHeapDataApply(object __instance, MethodBase __originalMethod, object[] __args, bool __result)
	{
		LogTrace("res-heap-data-apply", __instance, __originalMethod, __args, __result);
	}

	private static void LogTrace(string stage, object instance, MethodBase method, object[] args, object result = null)
	{
		try
		{
			if (_traceSuppressionDepth > 0)
				return;
			if (_logged >= LogCap)
				return;
			_logged++;

			Plugin.LogSource?.LogInfo(
				"HoMM3 custom economy law diagnostic: "
				+ stage
				+ " method="
				+ DescribeMethod(method)
				+ " instance="
				+ DescribeObjectContext(instance)
				+ " args="
				+ DescribeArgs(args)
				+ " result="
				+ DescribeObjectContext(result)
				+ " economyPlans="
				+ DescribeEconomyPlans(instance, args, result)
				+ " spendSnapshot="
				+ DescribeSpendSnapshot(stage, instance, args)
				+ " handlerGate="
				+ Homm3CustomLawHandlerTrace.Describe(
					instance,
					Homm3CustomLawHandlerTrace.RewardGoldEconomy,
					Homm3CustomLawHandlerTrace.RewardCalendar)
				+ ". Diagnostic observation only.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 custom economy law diagnostic log failed: " + ex.Message);
		}
	}


	private static string DescribeSpendSnapshot(string stage, object instance, object[] args)
	{
		if (instance == null || args == null || args.Length < 2)
			return "n/a";
		if (stage == null || !stage.StartsWith("resource-spend-if-available", StringComparison.Ordinal))
			return "n/a";
		var resourceName = args[0] as string;
		if (string.IsNullOrWhiteSpace(resourceName))
			return "invalid-resource-name";
		var amount = args[1] is int intAmount ? intAmount.ToString(System.Globalization.CultureInfo.InvariantCulture) : DescribeObjectContext(args[1]);
		if (!TryFindResourceObject(instance, resourceName, out var resource, out var resourceFail))
			return "resource=" + resourceName + " amount=" + amount + " lookup=failed:" + resourceFail;
		return "resource=" + resourceName + " amount=" + amount + " object=" + DescribeObjectContext(resource);
	}

	private static bool TryFindResourceObject(object wrapper, string resourceName, out object resource, out string fail)
	{
		resource = null;
		fail = null;
		try
		{
			var type = wrapper.GetType();
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			for (var current = type; current != null; current = current.BaseType)
			{
				foreach (var field in current.GetFields(flags))
				{
					if (field.IsStatic)
						continue;
					var value = field.GetValue(wrapper);
					if (value == null)
						continue;
					if (TryGetDictionaryResource(value, resourceName, out resource))
						return true;
				}
			}
			fail = "no dictionary-like resource field matched";
			return false;
		}
		catch (Exception ex)
		{
			fail = ex.GetType().Name + ":" + ex.Message;
			return false;
		}
	}

	private static bool TryGetDictionaryResource(object dictionary, string resourceName, out object resource)
	{
		resource = null;
		if (dictionary is IDictionary nonGeneric)
		{
			if (!nonGeneric.Contains(resourceName))
				return false;
			resource = nonGeneric[resourceName];
			return resource != null;
		}

		var type = dictionary.GetType();
		var tryGetValue = AccessTools.Method(type, "TryGetValue");
		if (tryGetValue != null)
		{
			var parameters = tryGetValue.GetParameters();
			if (parameters.Length == 2 && parameters[0].ParameterType == typeof(string))
			{
				var callArgs = new object[] { resourceName, null };
				var ok = tryGetValue.Invoke(dictionary, callArgs) is bool b && b;
				if (ok && callArgs[1] != null)
				{
					resource = callArgs[1];
					return true;
				}
			}
		}

		var getItem = AccessTools.Method(type, "get_Item", new[] { typeof(string) });
		if (getItem != null)
		{
			try
			{
				resource = getItem.Invoke(dictionary, new object[] { resourceName });
				return resource != null;
			}
			catch
			{
				return false;
			}
		}

		return false;
	}

	private sealed class TraceSuppressionScope : IDisposable
	{
		private bool _disposed;

		public void Dispose()
		{
			if (_disposed)
				return;
			_disposed = true;
			if (_traceSuppressionDepth > 0)
				_traceSuppressionDepth--;
		}
	}

	private static string DescribeMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}

	private static string DescribeEconomyPlans(object instance, object[] args, object result)
	{
		var failures = new List<string>(8);
		if (TryDescribeEconomyPlansFromOwner("instance", instance, out var direct, failures))
			return direct;
		if (args != null)
		{
			for (var i = 0; i < args.Length; i++)
			{
				if (TryDescribeEconomyPlansFromOwner("arg" + i, args[i], out var fromArg, failures))
					return fromArg;
			}
		}
		if (TryDescribeEconomyPlansFromOwner("result", result, out var fromResult, failures))
			return fromResult;
		return failures.Count == 0
			? "unresolved:no economy owner candidates"
			: "unresolved:[" + string.Join(";", failures) + "]";
	}

	private static bool TryDescribeEconomyPlansFromOwner(string label, object owner, out string description, List<string> failures)
	{
		description = null;
		if (owner == null)
		{
			failures?.Add(label + "=null");
			return false;
		}

		var plans = new List<string>(2);
		if (Homm3CustomRewardEconomyLawRuntime.TryPlanCandidateGoldEconomyEffect(
			    owner,
			    out var goldProfile,
			    out var goldContext,
			    out var goldPlan,
			    out var goldFail))
		{
			plans.Add("gold={context={" + goldContext + "} profile={" + goldProfile + "} plan={" + goldPlan + "}}");
		}
		else
		{
			failures?.Add(label + ".gold=" + goldFail);
		}

		if (Homm3CustomRewardEconomyLawRuntime.TryPlanCandidateCalendarEffect(
			    owner,
			    out var calendarProfile,
			    out var calendarContext,
			    out var calendarPlan,
			    out var calendarFail))
		{
			plans.Add("calendar={context={" + calendarContext + "} profile={" + calendarProfile + "} plan={" + calendarPlan + "}}");
		}
		else
		{
			failures?.Add(label + ".calendar=" + calendarFail);
		}

		if (plans.Count == 0)
			return false;
		description = label + "=[" + string.Join("|", plans) + "]";
		return true;
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
