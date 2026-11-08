using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic-only scaffold for no-compromise spell cast-gate laws.
/// This traces exact eew/eex boolean gates that static ISIL ties to cooldown,
/// spell rank, mana/counter limits, same-spell/same-school limits, and selected
/// spell lookup. It does not change gate results or cooldown state.
/// </summary>
internal static class Homm3SpellCastGateLawDiagnostics
{
	internal const string DiagnosticFlag = "homm3_spell_cast_gate_law_diag.flag";

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
			log?.LogWarning("HoMM3 spell cast-gate law diagnostics failed closed during registration: " + ex.Message);
			return;
		}

		if (patched == 0)
		{
			_registrationAuditStatus = "FAILED_CLOSED: no exact startup hook surfaces patched";
			log?.LogWarning("HoMM3 spell cast-gate law diagnostics found no exact cast-gate surfaces; cooldown/reuse law gameplay remains disabled.");
			return;
		}

		_registrationAuditStatus = "DIAGNOSTIC_HOOK_REGISTERED: exact trace patches=" + patched.ToString(System.Globalization.CultureInfo.InvariantCulture);
		log?.LogInfo("HoMM3 spell cast-gate law diagnostics registered " + patched + " exact trace patch(es). Diagnostic observation only.");
		log?.LogInfo("HoMM3 spell cast-gate law diagnostics: gate traces are observational only; do not override results until runtime proof confirms visible spellbook/cast behavior and native synchronization.");
		log?.LogInfo("HoMM3 spell cast-gate law diagnostics: active-law state is attempted only through the shared exact resolver; none-or-unresolved is not negative gameplay evidence.");
	}

	private static int PatchBattleSpellLogic(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.SpellCastGateLawsBattleSpellLogic);
		if (type == null)
		{
			log?.LogWarning("HoMM3 spell cast-gate law diagnostics: eew battle spell logic type not found.");
			return 0;
		}

		var patched = 0;
		patched += PatchExact(harmony, log, type, GameSymbols.SpellCastGateLaws.CooldownReadinessGate.NameHints[0], 0, nameof(PostfixGateTrace), "cooldown-readiness-gate");
		patched += PatchExact(harmony, log, type, GameSymbols.SpellCastGateLaws.FullCastGate.NameHints[0], 1, nameof(PostfixGateTrace), "full-cast-gate");
		return patched;
	}

	private static int PatchBattleSpellPool(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.SpellCastGateLawsBattleSpellPool);
		if (type == null)
		{
			log?.LogWarning("HoMM3 spell cast-gate law diagnostics: eex battle spell pool type not found.");
			return 0;
		}

		var patched = 0;
		patched += PatchExact(harmony, log, type, GameSymbols.SpellCastGateLaws.SpellCounterGate.NameHints[0], 2, nameof(PostfixGateTrace), "spell-counter-gate");
		patched += PatchExact(harmony, log, type, GameSymbols.SpellCastGateLaws.SpellIndexSelectionGate.NameHints[0], 1, nameof(PostfixGateTrace), "spell-index-selection-gate");
		return patched;
	}

	private static int PatchExact(Harmony harmony, ManualLogSource log, Type type, string methodName, int parameterCount, string postfixName, string stage)
	{
		var method = ResolveExactBoolMethod(type, methodName, parameterCount);
		if (method == null)
		{
			log?.LogWarning("HoMM3 spell cast-gate law diagnostics: exact bool " + type.FullName + "." + methodName + "(" + parameterCount + " args) not found for " + stage + ".");
			return 0;
		}

		var postfix = AccessTools.Method(typeof(Homm3SpellCastGateLawDiagnostics), postfixName);
		if (postfix == null)
		{
			log?.LogWarning("HoMM3 spell cast-gate law diagnostics: postfix " + postfixName + " not found.");
			return 0;
		}

		if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
		{
			log?.LogWarning("HoMM3 spell cast-gate law diagnostics: refusing incompatible postfix for " + FormatMethod(method) + ": " + reason);
			return 0;
		}

		harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		return 1;
	}

	private static MethodInfo ResolveExactBoolMethod(Type type, string name, int parameterCount)
	{
		var methods = AccessTools.GetDeclaredMethods(type);
		foreach (var method in methods)
		{
			if (!string.Equals(method.Name, name, StringComparison.Ordinal))
				continue;
			if (method.IsSpecialName)
				continue;
			if (method.ReturnType != typeof(bool))
				continue;
			if (method.GetParameters().Length != parameterCount)
				continue;
			return method;
		}

		return null;
	}

	private static void PostfixGateTrace(object __instance, MethodBase __originalMethod, object[] __args, bool __result)
	{
		LogTrace("gate", __instance, __originalMethod, __args, __result);
	}

	private static void LogTrace(string stage, object instance, MethodBase method, object[] args, bool result)
	{
		try
		{
			if (_logged >= LogCap)
				return;
			_logged++;
			Homm3DiagnosticBreadcrumbs.Enter("spell-cast-gate-law", method, stage);

			Plugin.LogSource?.LogInfo(
				"HoMM3 spell cast-gate law diagnostic: "
				+ stage
				+ " method="
				+ FormatMethod(method)
				+ " instance="
				+ DescribeObjectContext(instance)
				+ " args="
				+ DescribeArgs(args)
				+ " result="
				+ result
				+ ". Diagnostic observation only.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 spell cast-gate law diagnostic log failed: " + ex.Message);
		}
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
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
