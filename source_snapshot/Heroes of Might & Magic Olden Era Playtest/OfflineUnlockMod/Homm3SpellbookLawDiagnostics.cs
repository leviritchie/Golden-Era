using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic-only scaffold for no-compromise spell-school and spell-cooldown law work.
/// This traces exact spellbook data/UI and battle spell-cast event factories. It does
/// not mutate spell access, spellbook rows, cooldown state, cast gates, mana, or law state.
/// </summary>
internal static class Homm3SpellbookLawDiagnostics
{
	internal const string DiagnosticFlag = "homm3_spellbook_law_diag.flag";

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
			patched += PatchHeroMagicCandidates(harmony, log);
			patched += PatchDataMagicCandidates(harmony, log);
			patched += PatchMagicBookViewCandidates(harmony, log);
			patched += PatchCastMagicFactories(harmony, log);
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 spellbook law diagnostics failed closed during registration: " + ex.Message);
			return;
		}

		if (patched == 0)
		{
			log?.LogWarning("HoMM3 spellbook law diagnostics found no exact spellbook/cast surfaces.");
			return;
		}

		log?.LogInfo("HoMM3 spellbook law diagnostics registered " + patched + " exact trace patch(es). Diagnostic observation only.");
		log?.LogInfo("HoMM3 spellbook law diagnostics: cooldown storage and cast-gate surfaces are still unproven; do not implement cooldown laws from spellbook UI traces alone.");
		log?.LogInfo("HoMM3 spellbook law diagnostics: active-law state is attempted only through the shared exact resolver; none-or-unresolved is not negative gameplay evidence.");
	}

	private static int PatchHeroMagicCandidates(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.SpellbookLawsHeroMagics);
		if (type == null)
		{
			log?.LogWarning("HoMM3 spellbook law diagnostics: HeroMagics type not found.");
			return 0;
		}

		var patched = 0;
		patched += PatchExact(harmony, log, type, GameSymbols.SpellbookLaws.HeroMagicLookup.NameHints[0], 1, false, nameof(PostfixHeroMagicLookup), "hero-magic-lookup");
		patched += PatchExact(harmony, log, type, GameSymbols.SpellbookLaws.HeroMagicCopy.NameHints[0], 1, true, nameof(PostfixHeroMagicCopy), "hero-magic-copy");
		patched += PatchExact(harmony, log, type, GameSymbols.SpellbookLaws.HeroMagicCount.NameHints[0], 0, false, nameof(PostfixHeroMagicCount), "hero-magic-count");
		return patched;
	}

	private static int PatchDataMagicCandidates(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.SpellbookLawsDataMagics);
		if (type == null)
		{
			log?.LogWarning("HoMM3 spellbook law diagnostics: DataMagics type not found.");
			return 0;
		}

		var patched = 0;
		patched += PatchExact(harmony, log, type, GameSymbols.SpellbookLaws.DataMagicLookup.NameHints[0], 1, false, nameof(PostfixDataMagicLookup), "data-magic-lookup");
		patched += PatchExact(harmony, log, type, GameSymbols.SpellbookLaws.DataMagicIndex.NameHints[0], 1, false, nameof(PostfixDataMagicIndex), "data-magic-index");
		return patched;
	}

	private static int PatchMagicBookViewCandidates(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.SpellbookLawsMagicBookView);
		if (type == null)
		{
			log?.LogWarning("HoMM3 spellbook law diagnostics: BhMagicBookView type not found.");
			return 0;
		}

		var patched = 0;
		patched += PatchExact(harmony, log, type, GameSymbols.SpellbookLaws.MagicBookInit.NameHints[0], 1, true, nameof(PostfixMagicBookInit), "magic-book-init");
		patched += PatchExact(harmony, log, type, GameSymbols.SpellbookLaws.MagicBookShow.NameHints[0], 0, true, nameof(PostfixMagicBookShow), "magic-book-show");
		patched += PatchExact(harmony, log, type, GameSymbols.SpellbookLaws.MagicBookUpdateView.NameHints[0], 3, true, nameof(PostfixMagicBookUpdateView), "magic-book-update-view");
		patched += PatchExact(harmony, log, type, GameSymbols.SpellbookLaws.MagicBookTypeFilter.NameHints[0], 1, true, nameof(PostfixMagicBookTypeFilter), "magic-book-type-filter");
		foreach (var name in GameSymbols.SpellbookLaws.MagicBookSchoolFilters.NameHints)
			patched += PatchExact(harmony, log, type, name, 1, true, nameof(PostfixMagicBookSchoolFilter), "magic-book-school-filter");
		patched += PatchExact(harmony, log, type, GameSymbols.SpellbookLaws.MagicBookSelection.NameHints[0], 2, true, nameof(PostfixMagicBookSelection), "magic-book-selection");
		return patched;
	}

	private static int PatchCastMagicFactories(Harmony harmony, ManualLogSource log)
	{
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.SpellbookLawsCastMagicEventArgs);
		if (type == null)
		{
			log?.LogWarning("HoMM3 spellbook law diagnostics: CastMagicEventArgs type not found.");
			return 0;
		}

		var patched = 0;
		patched += PatchExact(harmony, log, type, GameSymbols.SpellbookLaws.CastMagicFromArrayFactory.NameHints[0], 3, false, nameof(PostfixCastMagicFromArrayFactory), "cast-magic-array-factory");
		patched += PatchExact(harmony, log, type, GameSymbols.SpellbookLaws.CastMagicFromListsFactory.NameHints[0], 4, false, nameof(PostfixCastMagicFromListsFactory), "cast-magic-lists-factory");
		return patched;
	}

	private static int PatchExact(Harmony harmony, ManualLogSource log, Type type, string methodName, int parameterCount, bool requireVoid, string postfixName, string stage)
	{
		var method = ResolveExactMethod(type, methodName, parameterCount, requireVoid);
		if (method == null)
		{
			log?.LogWarning("HoMM3 spellbook law diagnostics: exact " + type.FullName + "." + methodName + "(" + parameterCount + " args) not found for " + stage + ".");
			return 0;
		}

		var postfix = AccessTools.Method(typeof(Homm3SpellbookLawDiagnostics), postfixName);
		if (postfix == null)
		{
			log?.LogWarning("HoMM3 spellbook law diagnostics: postfix " + postfixName + " not found.");
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

	private static void PostfixHeroMagicLookup(object __instance, MethodBase __originalMethod, object[] __args, object __result) => LogTrace("hero-magic-lookup", __instance, __originalMethod, __args, __result);
	private static void PostfixHeroMagicCopy(object __instance, MethodBase __originalMethod, object[] __args) => LogTrace("hero-magic-copy", __instance, __originalMethod, __args);
	private static void PostfixHeroMagicCount(object __instance, MethodBase __originalMethod, object __result) => LogTrace("hero-magic-count", __instance, __originalMethod, null, __result);
	private static void PostfixDataMagicLookup(object __instance, MethodBase __originalMethod, object[] __args, object __result) => LogTrace("data-magic-lookup", __instance, __originalMethod, __args, __result);
	private static void PostfixDataMagicIndex(object __instance, MethodBase __originalMethod, object[] __args, object __result) => LogTrace("data-magic-index", __instance, __originalMethod, __args, __result);
	private static void PostfixMagicBookInit(object __instance, MethodBase __originalMethod, object[] __args) => LogTrace("magic-book-init", __instance, __originalMethod, __args);
	private static void PostfixMagicBookShow(object __instance, MethodBase __originalMethod) => LogTrace("magic-book-show", __instance, __originalMethod, null);
	private static void PostfixMagicBookUpdateView(object __instance, MethodBase __originalMethod, object[] __args) => LogTrace("magic-book-update-view", __instance, __originalMethod, __args);
	private static void PostfixMagicBookTypeFilter(object __instance, MethodBase __originalMethod, object[] __args) => LogTrace("magic-book-type-filter", __instance, __originalMethod, __args);
	private static void PostfixMagicBookSchoolFilter(object __instance, MethodBase __originalMethod, object[] __args) => LogTrace("magic-book-school-filter", __instance, __originalMethod, __args);
	private static void PostfixMagicBookSelection(object __instance, MethodBase __originalMethod, object[] __args) => LogTrace("magic-book-selection", __instance, __originalMethod, __args);
	private static void PostfixCastMagicFromArrayFactory(MethodBase __originalMethod, object[] __args, object __result) => LogTrace("cast-magic-array-factory", null, __originalMethod, __args, __result);
	private static void PostfixCastMagicFromListsFactory(MethodBase __originalMethod, object[] __args, object __result) => LogTrace("cast-magic-lists-factory", null, __originalMethod, __args, __result);

	private static void LogTrace(string stage, object instance, MethodBase method, object[] args, object result = null)
	{
		try
		{
			if (_logged >= LogCap)
				return;
			_logged++;
			Homm3DiagnosticBreadcrumbs.Enter("spellbook-law", method, stage);

			Plugin.LogSource?.LogInfo(
				"HoMM3 spellbook law diagnostic: "
				+ stage
				+ " method="
				+ DescribeMethod(method)
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
			Plugin.LogSource?.LogWarning("HoMM3 spellbook law diagnostic log failed: " + ex.Message);
		}
	}

	private static string DescribeMethod(MethodBase method)
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
