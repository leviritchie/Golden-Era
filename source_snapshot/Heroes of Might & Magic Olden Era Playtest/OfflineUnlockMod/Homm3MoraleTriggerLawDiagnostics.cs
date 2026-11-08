using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic-only scaffold for no-compromise morale-trigger law work.
/// This traces exact positive/negative morale roll candidates proven in current
/// decomp. It does not alter rolls, extra actions, turn scheduling, events, unit
/// state, or law state.
/// </summary>
internal static class Homm3MoraleTriggerLawDiagnostics
{
	internal const string DiagnosticFlag = "homm3_morale_trigger_law_diag.flag";

	private const int LogCap = 120;
	private const int MaxMemberSnapshots = 18;
	private const int MaxCandidateLogs = 32;
	private static bool _registered;
	private static int _logged;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";

	internal static string RegistrationAuditStatus => _registrationAuditStatus;

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
		Type battleLogicType = null;
		Type unitType = null;
		try
		{
			battleLogicType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.MoraleTriggerLawsBattleLogic);
			unitType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.BattleEventLawsBattleUnit);
			if (battleLogicType == null || unitType == null)
			{
				log?.LogWarning("HoMM3 morale-trigger law diagnostics: exact battle logic or Unit type not found.");
				return;
			}

			patched += PatchExactMoraleMethod(harmony, log, battleLogicType, unitType, GameSymbols.MoraleTriggerLaws.PositiveMoraleRoll, 2, false, "positive-morale-roll");
			patched += PatchExactMoraleMethod(harmony, log, battleLogicType, unitType, GameSymbols.MoraleTriggerLaws.NegativeMoraleRoll, 3, true, "negative-morale-roll");
		}
		catch (Exception ex)
		{
			_registrationAuditStatus = "FAILED_CLOSED: " + ex.Message;
			log?.LogWarning("HoMM3 morale-trigger law diagnostics failed closed during registration: " + ex.Message);
			return;
		}

		if (patched == 0)
		{
			_registrationAuditStatus = "FAILED_CLOSED: no exact startup hook surfaces patched";
			log?.LogWarning("HoMM3 morale-trigger law diagnostics found no exact morale roll surfaces; morale-trigger gameplay remains disabled.");
			LogMoraleCandidateInventory(log, battleLogicType, unitType);
			return;
		}

		_registrationAuditStatus = "DIAGNOSTIC_HOOK_REGISTERED: exact trace patches=" + patched.ToString(System.Globalization.CultureInfo.InvariantCulture);
		log?.LogInfo("HoMM3 morale-trigger law diagnostics registered " + patched + " exact trace patch(es). Diagnostic observation only.");
		log?.LogInfo("HoMM3 morale-trigger law diagnostics: active-law state is attempted only through the shared exact resolver; none-or-unresolved is not negative gameplay evidence.");
	}

	private static int PatchExactMoraleMethod(Harmony harmony, ManualLogSource log, Type battleLogicType, Type unitType, GameSymbols.MethodSymbol symbol, int parameterCount, bool requiresThirdBool, string stage)
	{
		var method = ResolveExactMoraleMethod(battleLogicType, unitType, symbol, parameterCount, requiresThirdBool);
		if (method == null)
		{
			log?.LogWarning("HoMM3 morale-trigger law diagnostics: exact " + battleLogicType.FullName + "." + symbol.NameHints[0] + "(" + parameterCount + " args) not found for " + stage + ".");
			return 0;
		}

		var postfix = AccessTools.Method(typeof(Homm3MoraleTriggerLawDiagnostics), nameof(PostfixMoraleRoll));
		if (postfix == null)
		{
			log?.LogWarning("HoMM3 morale-trigger law diagnostics: postfix not found for " + stage + ".");
			return 0;
		}
		if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
		{
			log?.LogWarning("HoMM3 morale-trigger law diagnostics: refusing incompatible postfix for " + DescribeMethod(method) + ": " + reason);
			return 0;
		}

		harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		log?.LogInfo("HoMM3 morale-trigger law diagnostics: patched exact " + stage + " " + DescribeMethod(method) + ".");
		return 1;
	}

	private static MethodInfo ResolveExactMoraleMethod(Type type, Type unitType, GameSymbols.MethodSymbol symbol, int parameterCount, bool requiresThirdBool)
	{
		var methods = AccessTools.GetDeclaredMethods(type);
		foreach (var method in methods)
		{
			if (!NameMatches(method.Name, symbol.NameHints))
				continue;
			if (method.IsSpecialName || method.ReturnType != typeof(bool))
				continue;
			var ps = method.GetParameters();
			if (ps.Length != parameterCount)
				continue;
			if (!IsExactBattleUnitParameter(ps[0].ParameterType, unitType))
				continue;
			if (!IsRandomParameter(ps[1].ParameterType))
				continue;
			if (requiresThirdBool && ps[2].ParameterType != typeof(bool))
				continue;
			return method;
		}

		return null;
	}

	private static bool IsExactBattleUnitParameter(Type parameterType, Type resolvedUnitType)
	{
		if (parameterType == null)
			return false;
		if (resolvedUnitType != null && parameterType == resolvedUnitType)
			return true;
		return string.Equals(parameterType.FullName, "Hex.Session.Battle.Unit", StringComparison.Ordinal)
			|| string.Equals(parameterType.Name, "Unit", StringComparison.Ordinal);
	}

	private static void LogMoraleCandidateInventory(ManualLogSource log, Type battleLogicType, Type unitType)
	{
		var emitted = 0;
		foreach (var method in AccessTools.GetDeclaredMethods(battleLogicType))
		{
			if (emitted >= MaxCandidateLogs)
				break;
			if (method.IsSpecialName || method.ReturnType != typeof(bool))
				continue;

			var parameters = method.GetParameters();
			if (parameters.Length == 0 || parameters.Length > 4)
				continue;

			var hasUnit = false;
			var hasRandom = false;
			var hasBool = false;
			var parameterSummary = new List<string>(parameters.Length);
			foreach (var parameter in parameters)
			{
				var parameterType = parameter.ParameterType;
				if (IsExactBattleUnitParameter(parameterType, unitType))
					hasUnit = true;
				if (IsRandomParameter(parameterType))
					hasRandom = true;
				if (parameterType == typeof(bool))
					hasBool = true;
				parameterSummary.Add(parameterType.FullName ?? parameterType.Name);
			}

			if (!hasUnit)
				continue;

			emitted++;
			log?.LogInfo(
				"HoMM3 morale-trigger law diagnostics candidate: method='" + method.Name
				+ "' obfuscated='" + GameMember.ReadObfuscatedName(method)
				+ "' params=[" + string.Join(", ", parameterSummary)
				+ "] hasRandom=" + hasRandom
				+ " hasBool=" + hasBool
				+ ". Exact morale roll names remain unresolved; this candidate was not patched.");
		}

		if (emitted == 0)
			log?.LogWarning("HoMM3 morale-trigger law diagnostics: no bool methods with a Unit parameter were found on battle logic; no candidate surface was patched.");
	}

	private static bool NameMatches(string name, string[] hints)
	{
		for (var i = 0; i < hints.Length; i++)
		{
			if (string.Equals(name, hints[i], StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static bool IsRandomParameter(Type type)
	{
		return type == typeof(Random)
		       || string.Equals(type?.FullName, "Il2CppSystem.Random", StringComparison.Ordinal)
		       || string.Equals(type?.Name, "Random", StringComparison.Ordinal);
	}

	private static void PostfixMoraleRoll(object __instance, MethodBase __originalMethod, object[] __args, bool __result)
	{
		var methodName = __originalMethod?.Name ?? string.Empty;
		var stage = ResolveStage(__originalMethod, methodName);
		LogTrace(stage, __instance, __originalMethod, __args, __result);
	}

	private static string ResolveStage(MethodBase method, string methodName)
	{
		if (NameMatches(methodName, GameSymbols.MoraleTriggerLaws.PositiveMoraleRoll.NameHints))
			return "positive-morale-roll";
		if (NameMatches(methodName, GameSymbols.MoraleTriggerLaws.NegativeMoraleRoll.NameHints))
			return "negative-morale-roll";
		var ps = method?.GetParameters();
		if (ps != null && ps.Length == 2)
			return "candidate-unit-random-roll";
		if (ps != null && ps.Length == 3)
			return "candidate-unit-random-bool-roll";
		return "candidate-morale-roll";
	}

	private static void LogTrace(string stage, object instance, MethodBase method, object[] args, bool result)
	{
		try
		{
			if (_logged >= LogCap)
				return;
			_logged++;
			Homm3DiagnosticBreadcrumbs.Enter("morale-trigger-law", method, stage);

			Plugin.LogSource?.LogInfo(
				"HoMM3 morale-trigger law diagnostic: "
				+ stage
				+ " method="
				+ DescribeMethod(method)
				+ " result="
				+ result
				+ " observation="
				+ DescribeMoraleObservation(method, result)
				+ " moraleTriggerProfile="
				+ DescribeMoraleTriggerProfile(method, args, result)
				+ " moraleTriggerPlan="
				+ DescribeMoraleTriggerPlan(method, args, result)
				+ " instance="
				+ DescribeObjectContext(instance)
				+ " args="
				+ DescribeArgs(args)
				+ " handlerGate="
				+ Homm3CustomLawHandlerTrace.Describe(
					ResolveMoraleHandlerOwner(instance, args),
					Homm3CustomLawHandlerTrace.MoralePackage,
					Homm3CustomLawHandlerTrace.MoraleTrigger)
				+ ". Diagnostic observation only.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 morale-trigger law diagnostic log failed: " + ex.Message);
		}
	}

	private static string DescribeMoraleObservation(MethodBase method, bool result)
	{
		return Homm3MoraleTriggerNativeAdapter.TryObserveRollResult(method, result, out var observation, out var failReason)
			? observation.ToString()
			: "unresolved:" + failReason;
	}

	private static string DescribeMoraleTriggerProfile(MethodBase method, object[] args, bool result)
	{
		if (args == null || args.Length == 0)
			return "none";
		return Homm3CustomMoraleLawRuntime.TryGetCandidateMoraleTriggerProfileForUnit(
			args[0],
			method,
			result,
			out var observation,
			out var profile,
			out _,
			out var context,
			out var failReason)
			? "context={" + context + "} observation={" + observation + "} profile={" + profile + "}"
			: "unresolved:" + failReason;
	}

	private static string DescribeMoraleTriggerPlan(MethodBase method, object[] args, bool result)
	{
		if (args == null || args.Length == 0)
			return "none";
		return Homm3CustomMoraleLawRuntime.TryPlanCandidateMoraleTriggerEffectForUnit(
			args[0],
			method,
			result,
			out var observation,
			out var profile,
			out _,
			out var context,
			out var plan,
			out var failReason)
			? "context={" + context + "} observation={" + observation + "} profile={" + profile + "} plan={" + plan + "}"
			: "unresolved:" + failReason;
	}

	private static object ResolveMoraleHandlerOwner(object instance, object[] args)
	{
		if (Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw(instance, Homm3CustomFactionLawRuntime.MoraleTriggerIndex, out _)
		    || Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw(instance, Homm3CustomFactionLawRuntime.MoraleFlatIndex, out _))
			return instance;
		if (args != null)
		{
			for (var i = 0; i < args.Length; i++)
			{
				var arg = args[i];
				if (Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw(arg, Homm3CustomFactionLawRuntime.MoraleTriggerIndex, out _)
				    || Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw(arg, Homm3CustomFactionLawRuntime.MoraleFlatIndex, out _))
					return arg;
			}
		}
		return instance ?? (args != null && args.Length > 0 ? args[0] : null);
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
		AddMoraleUnitSnapshots(value, type, parts);
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

	private static void AddMoraleUnitSnapshots(object value, Type type, List<string> parts)
	{
		for (var i = 0; i < GameSymbols.MoraleTriggerLaws.UnitMoraleGateMembers.Length && parts.Count < MaxMemberSnapshots; i++)
		{
			var member = GameSymbols.MoraleTriggerLaws.UnitMoraleGateMembers[i];
			if (TryGetMemberValue(value, type, member, out var memberValue))
				parts.Add(member + "=" + SafeFormatValue(memberValue));
		}

		for (var i = 0; i < GameSymbols.MoraleTriggerLaws.UnitStatMembers.Length && parts.Count < MaxMemberSnapshots; i++)
		{
			var statMember = GameSymbols.MoraleTriggerLaws.UnitStatMembers[i];
			if (!TryGetMemberValue(value, type, statMember, out var stat) || stat == null)
				continue;
			AddStatSnapshot(statMember, stat, parts);
		}

		AddUnitConfigSnapshot("logic", value, type, GameSymbols.BattleEventLaws.UnitLogicConfigMembers, parts);
		AddUnitConfigSnapshot("view", value, type, GameSymbols.BattleEventLaws.UnitViewConfigMembers, parts);
		AddUnitConfigSnapshot("data", value, type, GameSymbols.BattleEventLaws.UnitDataMembers, parts);
	}

	private static void AddStatSnapshot(string prefix, object stat, List<string> parts)
	{
		var statType = stat.GetType();
		for (var i = 0; i < GameSymbols.MoraleTriggerLaws.UnitStatSnapshotMembers.Length && parts.Count < MaxMemberSnapshots; i++)
		{
			var member = GameSymbols.MoraleTriggerLaws.UnitStatSnapshotMembers[i];
			if (TryGetMemberValue(stat, statType, member, out var value))
				parts.Add(prefix + "." + member + "=" + SafeFormatValue(value));
		}
	}

	private static void AddUnitConfigSnapshot(string label, object value, Type type, string[] memberNames, List<string> parts)
	{
		if (parts.Count >= MaxMemberSnapshots)
			return;
		if (!TryGetFirstMemberValue(value, type, memberNames, out var config) || config == null)
			return;
		var configType = config.GetType();
		for (var i = 0; i < GameSymbols.BattleEventLaws.UnitConfigSidMembers.Length && parts.Count < MaxMemberSnapshots; i++)
		{
			var member = GameSymbols.BattleEventLaws.UnitConfigSidMembers[i];
			if (TryGetMemberValue(config, configType, member, out var memberValue))
			{
				parts.Add(label + "." + member + "=" + SafeFormatValue(memberValue));
				break;
			}
		}
	}

	private static bool TryGetFirstMemberValue(object instance, Type type, string[] names, out object value)
	{
		value = null;
		for (var i = 0; i < names.Length; i++)
		{
			if (TryGetMemberValue(instance, type, names[i], out value))
				return true;
		}
		return false;
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

	private static bool TryGetMemberValue(object instance, Type type, string name, out object value)
	{
		value = null;
		if (instance == null || type == null || string.IsNullOrWhiteSpace(name))
			return false;

		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			try
			{
				var prop = current.GetProperty(name, flags);
				if (prop != null && prop.GetIndexParameters().Length == 0)
				{
					value = prop.GetValue(instance, null);
					return true;
				}
			}
			catch
			{
			}
			try
			{
				var field = current.GetField(name, flags);
				if (field != null)
				{
					value = field.GetValue(instance);
					return true;
				}
			}
			catch
			{
			}
			try
			{
				var method = current.GetMethod(name, flags);
				if (method != null && method.GetParameters().Length == 0)
				{
					value = method.Invoke(instance, Array.Empty<object>());
					return true;
				}
			}
			catch
			{
			}
		}

		return false;
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
			formatted = SafeFormatValue(raw);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static string SafeFormatValue(object value)
	{
		if (value == null)
			return "null";
		var text = value.ToString();
		if (string.IsNullOrEmpty(text))
			text = "(empty)";
		return text.Length <= 80 ? text : text.Substring(0, 80) + "...";
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

	private static string DescribeMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}
}
