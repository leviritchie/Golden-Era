using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic-only scaffold for no-compromise spell cooldown laws.
/// Static evidence on June 16 shows eew.cfxk is a battle spell cooldown-like
/// field; eew.bdmd reads/effectively clamps cooldown with HeroStat.magicCdBonus,
/// eew.bdmg decrements it, eew.bdmi adds only when it is zero,
/// and eex.bdnj shifts cooldowns across the battle spell pool. This hook logs
/// those exact surfaces only. It does not alter cooldowns or cast gates.
/// </summary>
internal static class Homm3SpellCooldownLawDiagnostics
{
	internal const string DiagnosticFlag = "homm3_spell_cooldown_law_diag.flag";

	private const int LogCap = 160;
	private const int MaxMemberSnapshots = 14;
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
		try
		{
			patched += PatchBattleSpellLogic(harmony, log);
			patched += PatchBattleSpellPool(harmony, log);
		}
		catch (Exception ex)
		{
			_registrationAuditStatus = "FAILED_CLOSED: " + ex.Message;
			log?.LogWarning("HoMM3 spell cooldown law diagnostics failed closed during registration: " + ex.Message);
			return;
		}

		if (patched == 0)
		{
			_registrationAuditStatus = "FAILED_CLOSED: no exact startup hook surfaces patched";
			log?.LogWarning("HoMM3 spell cooldown law diagnostics found no exact cooldown surfaces; cooldown law gameplay remains disabled.");
			return;
		}

		_registrationAuditStatus = "DIAGNOSTIC_HOOK_REGISTERED: exact trace patches=" + patched.ToString(System.Globalization.CultureInfo.InvariantCulture);
		log?.LogInfo("HoMM3 spell cooldown law diagnostics registered " + patched + " exact trace patch(es). Diagnostic observation only.");
		log?.LogInfo("HoMM3 spell cooldown law diagnostics: eew/eex traces are cooldown-storage evidence only; cast-gate and UI synchronization still require runtime proof before implementation.");
		log?.LogInfo("HoMM3 spell cooldown law diagnostics: active-law state is attempted only through the shared exact resolver; none-or-unresolved is not negative gameplay evidence.");
	}

	private static int PatchBattleSpellLogic(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.SpellCooldownLawsBattleSpellLogic);
		if (type == null)
		{
			log?.LogWarning("HoMM3 spell cooldown law diagnostics: eew battle spell logic type not found.");
			return 0;
		}

		var patched = 0;
		patched += PatchExactHints(harmony, log, type, GameSymbols.SpellCooldownLaws.EffectiveCooldown.NameHints, Array.Empty<string>(), typeof(int), nameof(PostfixEffectiveCooldown), "effective-cooldown");
		patched += PatchExactHints(harmony, log, type, GameSymbols.SpellCooldownLaws.DecrementCooldown.NameHints, Array.Empty<string>(), typeof(void), nameof(PostfixCooldownMutation), "cooldown-decrement");
		patched += PatchExactHints(harmony, log, type, GameSymbols.SpellCooldownLaws.AddCooldownIfReady.NameHints, new[] { "Int32" }, typeof(void), nameof(PostfixCooldownMutation), "cooldown-add-if-ready");
		return patched;
	}

	private static int PatchBattleSpellPool(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.SpellCooldownLawsBattleSpellPool);
		if (type == null)
		{
			log?.LogWarning("HoMM3 spell cooldown law diagnostics: eex battle spell pool type not found.");
			return 0;
		}

		var patched = 0;
		patched += PatchExactHints(harmony, log, type, GameSymbols.SpellCooldownLaws.SpellPoolInit.NameHints, new[] { "eir" }, typeof(void), nameof(PostfixPoolTrace), "spell-pool-init");
		patched += PatchExactHints(harmony, log, type, GameSymbols.SpellCooldownLaws.SpellPoolCooldownShift.NameHints, new[] { "Int32", "Boolean" }, typeof(void), nameof(PostfixPoolTrace), "spell-pool-cooldown-shift");
		return patched;
	}

	private static int PatchExactHints(Harmony harmony, ManualLogSource log, Type type, string[] methodNames, string[] expectedParameterTypeNames, Type expectedReturnType, string postfixName, string stage)
	{
		var patched = 0;
		for (var i = 0; i < methodNames.Length; i++)
			patched += PatchExact(harmony, log, type, methodNames[i], expectedParameterTypeNames, expectedReturnType, postfixName, stage);
		return patched;
	}

	private static int PatchExact(Harmony harmony, ManualLogSource log, Type type, string methodName, string[] expectedParameterTypeNames, Type expectedReturnType, string postfixName, string stage)
	{
		var method = ResolveExactMethod(type, methodName, expectedParameterTypeNames, expectedReturnType);
		if (method == null)
		{
			log?.LogWarning("HoMM3 spell cooldown law diagnostics: exact " + type.FullName + "." + methodName + "(" + string.Join(",", expectedParameterTypeNames ?? Array.Empty<string>()) + ") not found for " + stage + ".");
			return 0;
		}

		var postfix = AccessTools.Method(typeof(Homm3SpellCooldownLawDiagnostics), postfixName);
		if (postfix == null)
		{
			log?.LogWarning("HoMM3 spell cooldown law diagnostics: postfix " + postfixName + " not found.");
			return 0;
		}

		if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
		{
			log?.LogWarning("HoMM3 spell cooldown law diagnostics: refusing incompatible postfix for " + FormatMethod(method) + ": " + reason);
			return 0;
		}

		harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		return 1;
	}
	private static MethodInfo ResolveExactMethod(Type type, string name, string[] expectedParameterTypeNames, Type expectedReturnType)
	{
		var methods = AccessTools.GetDeclaredMethods(type);
		foreach (var method in methods)
		{
			if (!string.Equals(method.Name, name, StringComparison.Ordinal))
				continue;
			if (method.IsSpecialName)
				continue;
			if (expectedReturnType != null && method.ReturnType != expectedReturnType)
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length != expectedParameterTypeNames.Length)
				continue;
			var parameterTypesMatch = true;
			for (var i = 0; i < parameters.Length; i++)
			{
				var parameterTypeName = parameters[i].ParameterType.Name;
				var parameterFullName = parameters[i].ParameterType.FullName ?? parameterTypeName;
				if (!string.Equals(parameterTypeName, expectedParameterTypeNames[i], StringComparison.Ordinal)
				    && !parameterFullName.EndsWith("." + expectedParameterTypeNames[i], StringComparison.Ordinal))
				{
					parameterTypesMatch = false;
					break;
				}
			}
			if (!parameterTypesMatch)
				continue;
			return method;
		}

		return null;
	}
	private static void PostfixEffectiveCooldown(object __instance, MethodBase __originalMethod, object[] __args, object __result)
	{
		LogTrace("effective-cooldown", __instance, __originalMethod, __args, __result);
	}

	private static void PostfixCooldownMutation(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("cooldown-mutation", __instance, __originalMethod, __args);
	}

	private static void PostfixPoolTrace(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("spell-pool", __instance, __originalMethod, __args);
	}

	private static void LogTrace(string stage, object instance, MethodBase method, object[] args, object result = null)
	{
		try
		{
			if (_logged >= LogCap)
				return;
			_logged++;
			Homm3DiagnosticBreadcrumbs.Enter("spell-cooldown-law", method, stage);

			Plugin.LogSource?.LogInfo(
				"HoMM3 spell cooldown law diagnostic: "
				+ stage
				+ " method="
				+ FormatMethod(method)
				+ " instance="
				+ DescribeObjectContext(instance)
				+ " args="
				+ DescribeArgs(args)
				+ " result="
				+ DescribeObjectContext(result)
				+ " spellCooldownPlan="
				+ DescribeSpellCooldownPlan(instance, args, result)
				+ " handlerGate="
				+ Homm3CustomLawHandlerTrace.Describe(
					instance,
					Homm3CustomLawHandlerTrace.SpellLow,
					Homm3CustomLawHandlerTrace.SpellHigh,
					Homm3CustomLawHandlerTrace.SpellCooldown)
				+ ". Diagnostic observation only.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 spell cooldown law diagnostic log failed: " + ex.Message);
		}
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}

	private static string DescribeSpellCooldownPlan(object instance, object[] args, object result)
	{
		var failures = new List<string>(4);
		if (TryDescribeSpellCooldownPlanFromOwner("instance", instance, out var direct, failures))
			return direct;
		if (args != null)
		{
			for (var i = 0; i < args.Length; i++)
			{
				if (TryDescribeSpellCooldownPlanFromOwner("arg" + i, args[i], out var fromArg, failures))
					return fromArg;
			}
		}
		if (TryDescribeSpellCooldownPlanFromOwner("result", result, out var fromResult, failures))
			return fromResult;
		return failures.Count == 0
			? "unresolved:no instance, arg, or result resolved spell cooldown law owner"
			: "unresolved:[" + string.Join(";", failures) + "]";
	}

	private static bool TryDescribeSpellCooldownPlanFromOwner(string label, object owner, out string description, List<string> failures)
	{
		description = null;
		if (owner == null)
		{
			failures?.Add(label + "=null");
			return false;
		}
		if (Homm3CustomSpellCooldownLawRuntime.TryPlanCandidateSpellCooldownEffect(
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
}
