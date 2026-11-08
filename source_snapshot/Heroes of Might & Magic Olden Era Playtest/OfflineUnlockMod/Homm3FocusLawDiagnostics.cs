using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic-only scaffold for no-compromise Focus/Energy law work.
/// This observes exact energy event payloads. It does not grant, spend,
/// or normalize Focus.
///
/// June 18 unvalidated crash-containment note: combat spellbook-open testing
/// implicated broad BhHeroAbilitiesView battle-event bind tracing. Those UI
/// event methods are no longer patched here; Focus UI proof needs a separate,
/// narrower decomp-backed diagnostic.
/// </summary>
internal static class Homm3FocusLawDiagnostics
{
	internal const string DiagnosticFlag = "homm3_focus_law_diag.flag";

	private const int LogCap = 140;
	private const int MaxMemberSnapshots = 16;
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
			patched += PatchEnergyEventConstructors(harmony, log);
			log?.LogWarning("HoMM3 Focus law diagnostics: hero ability UI bind tracing is disabled after BhHeroAbilitiesView crash evidence; use a dedicated decomp-backed UI diagnostic instead.");
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 Focus law diagnostics failed closed during registration: " + ex.Message);
			return;
		}

		if (patched == 0)
		{
			log?.LogWarning("HoMM3 Focus law diagnostics found no exact Focus/Energy surfaces; Focus law gameplay remains disabled.");
			return;
		}

		log?.LogInfo("HoMM3 Focus law diagnostics registered " + patched + " exact trace patch(es). Diagnostic observation only.");
		log?.LogInfo("HoMM3 Focus law diagnostics: traces are observational only; do not implement Focus gain/spend laws until runtime proof identifies native storage mutation and cast/ability UI synchronization.");
	}

	private static int PatchEnergyEventConstructors(Harmony harmony, ManualLogSource log)
	{
		var patched = 0;
		patched += PatchConstructors(harmony, log, GameSymbols.TypeGroups.FocusLawsEnergyUpdateEventArgs, "energy-update", 2, 3);
		patched += PatchConstructors(harmony, log, GameSymbols.TypeGroups.FocusLawsEnergyUpdatedByMechEventArgs, "energy-updated-by-mech", 3);
		patched += PatchConstructors(harmony, log, GameSymbols.TypeGroups.FocusLawsSideUsedEnergyEventArgs, "side-used-energy", 2);
		return patched;
	}

	private static int PatchConstructors(Harmony harmony, ManualLogSource log, GameSymbols.TypeHintGroup typeGroup, string stage, params int[] parameterCounts)
	{
		var type = GameMember.ResolveTypeGroup(typeGroup);
		if (type == null)
		{
			log?.LogWarning("HoMM3 Focus law diagnostics: event type not found for " + stage + ".");
			return 0;
		}

		var postfix = AccessTools.Method(typeof(Homm3FocusLawDiagnostics), nameof(PostfixEventConstructor));
		var patched = 0;
		foreach (var constructor in type.GetConstructors(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			if (!Contains(parameterCounts, constructor.GetParameters().Length))
				continue;
			harmony.Patch(constructor, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
			patched++;
		}

		if (patched == 0)
			log?.LogWarning("HoMM3 Focus law diagnostics: no exact constructor with expected parameter count found for " + stage + " on " + type.FullName + ".");
		return patched;
	}

	private static void PostfixEventConstructor(object __instance, MethodBase __originalMethod, object[] __args)
	{
		Homm3DiagnosticBreadcrumbs.Enter("focus-law", __originalMethod, "energy-event-constructor-postfix");
		LogTrace("energy-event-constructed", __instance, __originalMethod, __args);
	}

	private static void LogTrace(string stage, object instance, MethodBase method, object[] args)
	{
		try
		{
			if (_logged >= LogCap)
				return;
			_logged++;

			Plugin.LogSource?.LogInfo(
				"HoMM3 Focus law diagnostic: "
				+ stage
				+ " method="
				+ FormatMethod(method)
				+ " instance="
				+ DescribeObjectContext(instance)
				+ " args="
				+ DescribeArgs(args)
				+ ". Diagnostic observation only.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 Focus law diagnostic log failed: " + ex.Message);
		}
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
		AddAbilityConfigSnapshots(value, type, parts);
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

	private static void AddAbilityConfigSnapshots(object value, Type type, List<string> parts)
	{
		if (parts.Count >= MaxMemberSnapshots)
			return;
		for (var i = 0; i < GameSymbols.FocusLaws.AbilityConfigMembers.Length; i++)
		{
			var configName = GameSymbols.FocusLaws.AbilityConfigMembers[i];
			if (!TryGetMemberValue(value, type, configName, out var config) || config == null)
				continue;
			var configType = config.GetType();
			for (var m = 0; m < GameSymbols.FocusLaws.AbilityConfigEnergyMembers.Length && parts.Count < MaxMemberSnapshots; m++)
			{
				var member = GameSymbols.FocusLaws.AbilityConfigEnergyMembers[m];
				if (TryGetMemberValue(config, configType, member, out var memberValue))
					parts.Add(configName + "." + member + "=" + SafeFormatValue(memberValue));
			}
		}
	}

	private static void AddSimpleMemberSnapshots(object value, Type type, List<string> parts)
	{
		for (var i = 0; i < GameSymbols.FocusLaws.AbilityEnergyMembers.Length && parts.Count < MaxMemberSnapshots; i++)
		{
			var member = GameSymbols.FocusLaws.AbilityEnergyMembers[i];
			if (TryGetMemberValue(value, type, member, out var memberValue))
				parts.Add(member + "=" + SafeFormatValue(memberValue));
		}

		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var current = type; current != null && parts.Count < MaxMemberSnapshots; current = current.BaseType)
		{
			foreach (var field in current.GetFields(flags))
			{
				if (field.IsStatic)
					continue;
				if (!FieldLooksEnergyRelated(field.Name))
					continue;
				if (!TryFormatSimpleValue(field.FieldType, () => field.GetValue(value), out var formatted))
					continue;
				parts.Add(field.Name + "=" + formatted);
				if (parts.Count >= MaxMemberSnapshots)
					return;
			}
		}
	}

	private static bool FieldLooksEnergyRelated(string name)
	{
		if (string.IsNullOrEmpty(name))
			return false;
		return name.IndexOf("energy", StringComparison.OrdinalIgnoreCase) >= 0
		       || name.IndexOf("focus", StringComparison.OrdinalIgnoreCase) >= 0
		       || name.IndexOf("charge", StringComparison.OrdinalIgnoreCase) >= 0
		       || name.IndexOf("cast", StringComparison.OrdinalIgnoreCase) >= 0
		       || name.IndexOf("cd", StringComparison.OrdinalIgnoreCase) >= 0;
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

	private static bool Contains(int[] values, int value)
	{
		if (values == null)
			return false;
		for (var i = 0; i < values.Length; i++)
		{
			if (values[i] == value)
				return true;
		}
		return false;
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}
}
