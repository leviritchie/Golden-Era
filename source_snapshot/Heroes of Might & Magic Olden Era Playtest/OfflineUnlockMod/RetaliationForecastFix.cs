using System;
using System.Collections.Generic;
using System.Diagnostics;
using HarmonyLib;
using Hex.Session.Battle;

namespace OfflineUnlockMod;

internal static class RetaliationForecastFixSettings
{
	private static bool? _enabled;
	private static bool _logged;

	internal static bool ShouldApplyPatches()
	{
		if (!_enabled.HasValue)
		{
			var config = LauncherConfigReader.TryLoad();
			_enabled = config?.RetaliationForecastFix ?? false;
		}

		if (!_logged)
		{
			_logged = true;
			Plugin.LogSource?.LogInfo(
				$"RetaliationForecastFix: {(_enabled.Value ? "ENABLED" : "DISABLED")} " +
				$"(debounce={RetaliationDebug.GetDebounceMs()}ms).");
		}

		return _enabled.Value;
	}
}

internal static class RetaliationForecastState
{
	private static readonly Dictionary<long, long> LastShowTicksByPanel = new();
	private static readonly object SyncRoot = new();

	internal static void RecordShow(BhHealDamageForecastPanel panel)
	{
		var panelKey = GetPanelKey(panel);
		if (panelKey == 0)
		{
			return;
		}

		lock (SyncRoot)
		{
			LastShowTicksByPanel[panelKey] = Stopwatch.GetTimestamp();
		}

		RetaliationDebug.Log($"BhHealDamageForecastPanel.Show panel={panelKey}");
	}

	internal static bool ShouldSuppressHide(BhHealDamageForecastPanel panel, out long elapsedMs)
	{
		elapsedMs = long.MaxValue;

		var panelKey = GetPanelKey(panel);
		if (panelKey == 0)
		{
			return false;
		}

		var now = Stopwatch.GetTimestamp();
		lock (SyncRoot)
		{
			if (!LastShowTicksByPanel.TryGetValue(panelKey, out var lastShowTicks))
			{
				return false;
			}

			elapsedMs = ToMilliseconds(now - lastShowTicks);
			if (elapsedMs <= RetaliationDebug.GetDebounceMs())
			{
				return true;
			}

			LastShowTicksByPanel.Remove(panelKey);
		}

		return false;
	}

	private static long GetPanelKey(BhHealDamageForecastPanel panel)
	{
		return panel?.Pointer.ToInt64() ?? 0L;
	}

	private static long ToMilliseconds(long ticks)
	{
		return (long)(ticks * 1000d / Stopwatch.Frequency);
	}
}

// FIXME(steam: member absent from steam assemblies; keep disabled): ekx type removed
        //[HarmonyPatch(typeof(BhHealDamageForecastPanel), nameof(BhHealDamageForecastPanel.Show), new[] { typeof(ekx) })]
internal static class BhHealDamageForecastPanelShowPatch
{
	private static bool Prepare()
	{
		return RetaliationForecastFixSettings.ShouldApplyPatches();
	}

	private static void Postfix(BhHealDamageForecastPanel __instance)
	{
		RetaliationForecastState.RecordShow(__instance);
	}
}

[HarmonyPatch(typeof(BhHealDamageForecastPanel), nameof(BhHealDamageForecastPanel.Hide))]
internal static class BhHealDamageForecastPanelHidePatch
{
	private static bool Prepare()
	{
		return RetaliationForecastFixSettings.ShouldApplyPatches();
	}

	private static bool Prefix(BhHealDamageForecastPanel __instance)
	{
		if (!RetaliationForecastState.ShouldSuppressHide(__instance, out var elapsedMs))
		{
			return true;
		}

		RetaliationDebug.Log(
			$"BhHealDamageForecastPanel.Hide suppressed after {elapsedMs}ms " +
			$"(debounce={RetaliationDebug.GetDebounceMs()}ms)");
		return false;
	}
}
