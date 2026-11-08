using System;
using System.IO;
using BepInEx;
using HarmonyLib;
using Hex.UI;

namespace OfflineUnlockMod;

[AttributeUsage(AttributeTargets.Class)]
internal sealed class ProbePatchAttribute : Attribute
{
}

internal static class RetaliationDebug
{
	private const string FlagFileName = "retaliation_debug.flag";
	private static bool? _enabled;
	private static int? _debounceMs;

	internal static void InvalidateCache()
	{
		_enabled = null;
		_debounceMs = null;
	}

	internal static bool IsEnabled()
	{
		if (_enabled.HasValue)
		{
			return _enabled.Value;
		}

		_enabled = File.Exists(GetFlagPath());
		return _enabled.Value;
	}

	internal static int GetDebounceMs()
	{
		if (_debounceMs.HasValue)
		{
			return _debounceMs.Value;
		}

		var config = LauncherConfigReader.TryLoad();
		var configuredValue = config?.RetaliationForecastDebounceMs ?? 100;
		_debounceMs = Math.Clamp(configuredValue, 0, 1000);
		return _debounceMs.Value;
	}

	internal static void Log(string message)
	{
		if (!IsEnabled())
		{
			return;
		}

		Plugin.LogSource?.LogInfo("[RetaliationProbe] " + message);
	}

	private static string GetFlagPath()
	{
		return Path.Combine(Paths.GameRootPath, "BepInEx", "plugins", "OfflineUnlockMod", FlagFileName);
	}
}

[ProbePatch]
// FIXME(steam: member absent from steam assemblies; keep disabled): [HarmonyPatch(typeof(BhTooltipUnit), nameof(BhTooltipUnit.tbw))]
internal static class BhTooltipUnitSrsProbePatch
{
	private static void Postfix(BhTooltipUnit __instance, [HarmonyArgument(0)] string a)
	{
		TryLog(() =>
			$"BhTooltipUnit.tbw text='{a}' unitActive={SafeActive(__instance)} lossesActive={SafeActive(__instance?.countLosses)}");
	}

	private static void TryLog(Func<string> messageFactory)
	{
		if (!RetaliationDebug.IsEnabled())
		{
			return;
		}

		try
		{
			RetaliationDebug.Log(messageFactory());
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning($"Retaliation probe logging failed: {ex.Message}");
		}
	}

	private static string SafeActive(UnityEngine.Component component)
	{
		return component?.gameObject != null ? component.gameObject.activeSelf.ToString() : "null";
	}
}

[ProbePatch]
// FIXME(steam: member absent from steam assemblies; keep disabled): [HarmonyPatch(typeof(BhTooltipUnit), nameof(BhTooltipUnit.tbx))]
internal static class BhTooltipUnitSrtProbePatch
{
	private static void Postfix(BhTooltipUnit __instance)
	{
		RetaliationDebug.Log($"BhTooltipUnit.tbx unitActive={SafeActive(__instance)} lossesActive={SafeActive(__instance?.countLosses)}");
	}

	private static string SafeActive(UnityEngine.Component component)
	{
		return component?.gameObject != null ? component.gameObject.activeSelf.ToString() : "null";
	}
}

[ProbePatch]
// FIXME(steam: member absent from steam assemblies; keep disabled): [HarmonyPatch(typeof(BhTooltipUnit), nameof(BhTooltipUnit.tby))]
internal static class BhTooltipUnitSruProbePatch
{
	private static void Postfix(BhTooltipUnit __instance, [HarmonyArgument(0)] string a)
	{
		RetaliationDebug.Log($"BhTooltipUnit.tby text='{a}' unitActive={SafeActive(__instance)} lossesActive={SafeActive(__instance?.countLosses)}");
	}

	private static string SafeActive(UnityEngine.Component component)
	{
		return component?.gameObject != null ? component.gameObject.activeSelf.ToString() : "null";
	}
}

[ProbePatch]
// FIXME(steam: member absent from steam assemblies; keep disabled): [HarmonyPatch(typeof(BhTooltipUnit), nameof(BhTooltipUnit.tca))]
internal static class BhTooltipUnitSrwProbePatch
{
	private static void Postfix(BhTooltipUnit __instance, [HarmonyArgument(0)] float a, [HarmonyArgument(1)] float b, [HarmonyArgument(2)] float c)
	{
		RetaliationDebug.Log($"BhTooltipUnit.tca values={a},{b},{c} unitActive={SafeActive(__instance)} lossesActive={SafeActive(__instance?.countLosses)}");
	}

	private static string SafeActive(UnityEngine.Component component)
	{
		return component?.gameObject != null ? component.gameObject.activeSelf.ToString() : "null";
	}
}

[ProbePatch]
// FIXME(steam: member absent from steam assemblies; keep disabled): [HarmonyPatch(typeof(BhTooltipUnit), nameof(BhTooltipUnit.tcb))]
internal static class BhTooltipUnitSrxProbePatch
{
	private static void Postfix(BhTooltipUnit __instance, [HarmonyArgument(0)] int a, [HarmonyArgument(1)] int b, [HarmonyArgument(2)] float c)
	{
		RetaliationDebug.Log($"BhTooltipUnit.tcb values={a},{b},{c} unitActive={SafeActive(__instance)} lossesActive={SafeActive(__instance?.countLosses)}");
	}

	private static string SafeActive(UnityEngine.Component component)
	{
		return component?.gameObject != null ? component.gameObject.activeSelf.ToString() : "null";
	}
}

[ProbePatch]
// FIXME(steam: member absent from steam assemblies; keep disabled): [HarmonyPatch(typeof(BhTooltipUnitCountLosses), nameof(BhTooltipUnitCountLosses.tch))]
internal static class BhTooltipUnitCountLossesSsdProbePatch
{
	private static void Postfix(BhTooltipUnitCountLosses __instance)
	{
		RetaliationDebug.Log($"BhTooltipUnitCountLosses.taq active={SafeActive(__instance)}");
	}

	private static string SafeActive(UnityEngine.Component component)
	{
		return component?.gameObject != null ? component.gameObject.activeSelf.ToString() : "null";
	}
}

[ProbePatch]
// FIXME(steam: member absent from steam assemblies; keep disabled): [HarmonyPatch(typeof(BhTooltipUnitCountLosses), nameof(BhTooltipUnitCountLosses.tar))]
internal static class BhTooltipUnitCountLossesSseProbePatch
{
	private static void Postfix(BhTooltipUnitCountLosses __instance)
	{
		RetaliationDebug.Log($"BhTooltipUnitCountLosses.tar active={SafeActive(__instance)}");
	}

	private static string SafeActive(UnityEngine.Component component)
	{
		return component?.gameObject != null ? component.gameObject.activeSelf.ToString() : "null";
	}
}
