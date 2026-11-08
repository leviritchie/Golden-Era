using System;
using System.Collections;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;

namespace OfflineUnlockMod;

/// <summary>
/// Log-only map-load diagnostic for <c>HeroSkill.bfyg</c> NREs.
/// Does not swallow exceptions; identifies which skill SID / SkillConfig hole fails.
/// </summary>
internal static class Homm3HeroSkillApplyDiag
{
	private static bool _registered;
	private static ManualLogSource _log;
	private static int _loggedCalls;
	private static int _loggedFailures;
	private static MethodInfo _skillConfigGetter;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_log = log;
		try
		{
			var heroSkillType = typeof(ObjCityConfig).Assembly.GetType("Hex.Session.Data.HeroSkill")
				?? throw new MissingMemberException("Hex.Session.Data.HeroSkill");
			var rebuild = FindRebuildSubSkillsMethod(heroSkillType)
				?? throw new MissingMethodException("HeroSkill rebuild-subskills void() not found");
			_skillConfigGetter = FindSkillConfigGetter(heroSkillType);

			var prefix = AccessTools.Method(typeof(Homm3HeroSkillApplyDiag), nameof(PrefixRebuild));
			var finalizer = AccessTools.Method(typeof(Homm3HeroSkillApplyDiag), nameof(FinalizerRebuild));
			if (!GameMember.IsHarmonyPatchCompatible(rebuild, prefix, out var prefixReason))
				throw new MissingMethodException("HeroSkill rebuild prefix incompatible: " + prefixReason);
			if (!GameMember.IsHarmonyPatchCompatible(rebuild, finalizer, out var finalizerReason))
				throw new MissingMethodException("HeroSkill rebuild finalizer incompatible: " + finalizerReason);

			harmony.Patch(rebuild, prefix: new HarmonyMethod(prefix), finalizer: new HarmonyMethod(finalizer));
			_registered = true;
			_log?.LogWarning(
				"HoMM3 HeroSkill apply diag registered on "
				+ rebuild.DeclaringType!.FullName
				+ "."
				+ rebuild.Name
				+ " (log-only; does not swallow NREs).");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 HeroSkill apply diag not registered: " + ex.Message);
		}
	}

	private static void PrefixRebuild(object __instance)
	{
		if (__instance == null || _loggedCalls >= 48)
			return;
		_loggedCalls++;
		var sid = TryReadString(__instance, GameSymbols.DraconicDominion.HeroSkillSidMembers) ?? "?";
		var level = TryReadInt(__instance, GameSymbols.DraconicDominion.HeroSkillLevelMembers);
		var config = TryGetSkillConfig(__instance);
		_log?.LogWarning(
			"HoMM3 HeroSkill.bfyg enter sid='"
			+ sid
			+ "' level="
			+ level
			+ " skillConfig="
			+ (config == null ? "null" : config.GetType().Name)
			+ " "
			+ AuditParametersPerLevel(config));
	}

	private static Exception FinalizerRebuild(object __instance, Exception __exception)
	{
		if (__exception == null)
			return null;
		var sid = TryReadString(__instance, GameSymbols.DraconicDominion.HeroSkillSidMembers) ?? "?";
		if (_loggedFailures < 24)
		{
			_loggedFailures++;
			_log?.LogError(
				"HoMM3 HeroSkill.bfyg FAILED sid='"
				+ sid
				+ "' level="
				+ TryReadInt(__instance, GameSymbols.DraconicDominion.HeroSkillLevelMembers)
				+ " skillConfig="
				+ (TryGetSkillConfig(__instance) == null ? "null" : "present")
				+ " ex="
				+ __exception.GetType().Name
				+ ": "
				+ __exception.Message);
		}
		return __exception;
	}

	private static MethodInfo FindRebuildSubSkillsMethod(Type heroSkillType)
	{
		// Golden Era IL2CPP types often hide obfuscated methods from GetMethods(); prefer AccessTools.
		foreach (var name in new[] { "bfyg", "bfui" })
		{
			var byName = AccessTools.Method(heroSkillType, name);
			if (byName != null && byName.ReturnType == typeof(void) && byName.GetParameters().Length == 0)
				return byName;
		}

		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		MethodInfo fallback = null;
		foreach (var method in heroSkillType.GetMethods(flags))
		{
			if (method.IsStatic || method.ReturnType != typeof(void) || method.GetParameters().Length != 0)
				continue;
			if (method.Name == "bfyg" || method.Name == "bfui")
				return method;
			if (fallback == null && method.Name.StartsWith("bf", StringComparison.Ordinal))
				fallback = method;
		}
		return fallback;
	}

	private static MethodInfo FindSkillConfigGetter(Type heroSkillType)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var method in heroSkillType.GetMethods(flags))
		{
			if (method.IsStatic || method.GetParameters().Length != 0)
				continue;
			if (method.ReturnType != null && method.ReturnType.Name == "SkillConfig")
				return method;
		}
		foreach (var prop in heroSkillType.GetProperties(flags))
		{
			if (prop.PropertyType != null && prop.PropertyType.Name == "SkillConfig" && prop.GetMethod != null)
				return prop.GetMethod;
		}
		return null;
	}

	private static object TryGetSkillConfig(object heroSkill)
	{
		try
		{
			if (_skillConfigGetter != null)
				return _skillConfigGetter.Invoke(heroSkill, null);
		}
		catch
		{
			// fall through
		}
		return TryGetMemberValue(heroSkill, "chqt", "skillConfig", "_skillConfig_k__BackingField");
	}

	private static string AuditParametersPerLevel(object config)
	{
		if (config == null)
			return "parametersPerLevel=no-config";
		var levels = TryGetMemberValue(config, "parametersPerLevel") as IList;
		if (levels == null)
			return "parametersPerLevel=null";
		var parts = new string[Math.Min(levels.Count, 3)];
		for (var i = 0; i < parts.Length; i++)
		{
			var level = levels[i];
			if (level == null)
			{
				parts[i] = "L" + i + "=null";
				continue;
			}
			var bonuses = TryGetMemberValue(level, "bonuses") as IList;
			var subs = TryGetMemberValue(level, "subSkills") as IList;
			parts[i] = "L" + i + "(b=" + (bonuses?.Count ?? -1) + ",s=" + (subs?.Count ?? -1) + ")";
		}
		return "parametersPerLevel[" + levels.Count + "]=" + string.Join(",", parts);
	}

	private static string TryReadString(object instance, string[] names)
	{
		return TryGetMemberValue(instance, names) as string;
	}

	private static int TryReadInt(object instance, string[] names)
	{
		var value = TryGetMemberValue(instance, names);
		return value is int i ? i : -1;
	}

	private static object TryGetMemberValue(object instance, params string[] names)
	{
		if (instance == null || names == null)
			return null;
		var type = instance.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			if (string.IsNullOrEmpty(name))
				continue;
			var prop = type.GetProperty(name, flags);
			if (prop != null)
			{
				try { return prop.GetValue(instance, null); }
				catch { /* next */ }
			}
			var field = type.GetField(name, flags);
			if (field != null)
			{
				try { return field.GetValue(instance); }
				catch { /* next */ }
			}
		}
		return null;
	}
}
