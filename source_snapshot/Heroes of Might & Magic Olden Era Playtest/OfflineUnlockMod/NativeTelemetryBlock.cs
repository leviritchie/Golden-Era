using System;
using System.Linq;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Stops the channels that would send mod-caused data to the game developer's analytics service
/// (docs/mod_bug_reporting.md, "Telemetry block"). A modded game's changed units and maps would otherwise pollute the
/// developer's balancing data, and its crash reports would describe our bugs, not theirs.
///
/// Channels, each bound independently behind <c>blockNativeTelemetry</c> (default on):
/// <list type="bullet">
/// <item>the desync auto bug report launchers on the bug report screen (no form, no user confirmation): skipped, so no
/// screenshot, log or save is gathered. Golden Era has one, build 25061458 two; all must bind or the channel
/// fails;</item>
/// <item><c>HexAnalytics.SendGameMetrics</c> (void): skipped;</item>
/// <item><c>HexAnalytics.SendTable</c> (Task&lt;bool&gt;): skipped and answered with a completed <c>true</c> task,
/// because its only caller re-queues the rows on <c>false</c> and would grow its queue forever;</item>
/// <item><c>HexAnalytics.SendReport</c>: skipped with no bundle, only when the bug report redirect is not already
/// holding it.</item>
/// </list>
///
/// Fail closed without breaking the game: a channel whose hook cannot be bound is logged at error level and left
/// unchanged; nothing here throws out of <see cref="TryRegister"/> or out of a prefix. Nothing here opens a network
/// connection.
///
/// Proof: source/static validated (tools/validate_mod_bug_reporting_contract.py) and build target. The hooks have not
/// been exercised in a running game.
/// </summary>
internal static class NativeTelemetryBlock
{
	private static ManualLogSource _log;
	private static int _metricsBlocked;
	private static int _tablesBlocked;
	private static int _autoReportsBlocked;
	private static int _reportsBlocked;

	internal static bool Active { get; private set; }

	/// <summary>True when this block bound its own SendReport hook (only when the redirect is not holding it).</summary>
	internal static bool ReportSinkBlocked { get; private set; }

	internal static void TryRegister(Harmony harmony, ManualLogSource log, LauncherConfig cfg)
	{
		_log = log;
		if (cfg == null || !cfg.BlockNativeTelemetry)
		{
			log?.LogWarning(
				"NativeTelemetry: block off (blockNativeTelemetry=false). Gameplay telemetry and the desync auto bug report "
				+ "still reach the game developer's analytics service.");
			return;
		}

		try
		{
			var blocked = new System.Collections.Generic.List<string>();
			var failed = new System.Collections.Generic.List<string>();
			var owner = GameMember.FindTypeFromHints(
				"telemetry.analytics.owner",
				GameSymbols.ModBugReporting.SendReportOwnerTypeHints);

			Bind(blocked, failed, GameSymbols.ModBugReporting.SendGameMetricsMethodName, () => PatchStatic(
				harmony,
				owner,
				GameSymbols.ModBugReporting.SendGameMetricsMethodName,
				GameSymbols.ModBugReporting.SendGameMetricsParameterCount,
				nameof(SendGameMetricsPrefix)));
			Bind(blocked, failed, GameSymbols.ModBugReporting.SendTableMethodName, () => PatchStatic(
				harmony,
				owner,
				GameSymbols.ModBugReporting.SendTableMethodName,
				GameSymbols.ModBugReporting.SendTableParameterCount,
				nameof(SendTablePrefix)));
			var autoReportLaunchers = 0;
			Bind(blocked, failed, "desync auto report", () => PatchAutoReport(harmony, out autoReportLaunchers),
				() => autoReportLaunchers > 1 ? " (" + autoReportLaunchers + " launchers)" : "");
			if (ModBugReportRedirect.State == ModBugReportRedirect.GuardState.Redirecting)
			{
				blocked.Add(GameSymbols.ModBugReporting.SendReportMethodName + " (held by the bug report redirect)");
			}
			else
			{
				Bind(blocked, failed, GameSymbols.ModBugReporting.SendReportMethodName, () => PatchStatic(
					harmony,
					owner,
					GameSymbols.ModBugReporting.SendReportMethodName,
					GameSymbols.ModBugReporting.SendReportParameterCount,
					nameof(SendReportPrefix)));
				ReportSinkBlocked = blocked.Contains(GameSymbols.ModBugReporting.SendReportMethodName);
			}

			Active = blocked.Count > 0;
			if (blocked.Count > 0)
			{
				log?.LogInfo(
					"NativeTelemetry: blocking sends to the game developer's analytics service: " + string.Join(", ", blocked) + ".");
			}
			if (failed.Count > 0)
			{
				log?.LogError(
					"NativeTelemetry: NOT BLOCKED, hook could not be bound, channel left unchanged and may still reach the game "
					+ "developer: " + string.Join("; ", failed) + ".");
			}
		}
		catch (Exception ex)
		{
			log?.LogError("NativeTelemetry: NOT BLOCKED, registration failed (" + ex.GetType().Name + ": " + ex.Message + ").");
		}
	}

	private static void Bind(
		System.Collections.Generic.List<string> blocked,
		System.Collections.Generic.List<string> failed,
		string label,
		Func<string> patch,
		Func<string> boundDetail = null)
	{
		string error;
		try
		{
			error = patch();
		}
		catch (Exception ex)
		{
			error = ex.GetType().Name + ": " + ex.Message;
		}

		if (error == null)
			blocked.Add(label + (boundDetail?.Invoke() ?? ""));
		else
			failed.Add(label + " (" + error + ")");
	}

	/// <summary>Returns null on success, otherwise the reason the hook was not bound.</summary>
	private static string PatchStatic(Harmony harmony, Type owner, string methodName, int parameterCount, string prefixName)
	{
		if (owner == null)
			return "analytics owner type not found";
		var candidates = AccessTools.GetDeclaredMethods(owner)
			.Where(m => m.IsStatic && m.Name == methodName && m.GetParameters().Length == parameterCount)
			.ToArray();
		if (candidates.Length != 1)
			return "expected exactly one static " + methodName + " with " + parameterCount + " parameters, found " + candidates.Length;
		harmony.Patch(
			candidates[0],
			prefix: new HarmonyMethod(typeof(NativeTelemetryBlock), prefixName) { priority = Priority.First });
		return null;
	}

	/// <summary>
	/// Every desync auto-send launcher must be bound before any is patched: Golden Era has one (<c>void(bool)</c>),
	/// build 25061458 split it into two parameterless launchers (GameSymbolScope.MethodSplit). A missing one fails
	/// the whole channel with its reason instead of leaving a partial block that would look like success.
	/// </summary>
	private static string PatchAutoReport(Harmony harmony, out int launcherCount)
	{
		launcherCount = 0;
		var screen = GameMember.FindTypeFromHints("telemetry.bugReport.screen", GameSymbols.ModBugReporting.ScreenTypeHints);
		if (screen == null)
			return "bug report screen type not found";
		MethodInfo[] launchers = ModBugReportRedirect.FindAutoSendLaunchers(
			screen,
			GameSymbols.ModBugReporting.ScreenStaticAutoSend,
			out var error);
		if (launchers == null)
			return "desync auto-send launcher not found on " + screen.FullName + " (" + error + ")";
		var prefix = new HarmonyMethod(typeof(NativeTelemetryBlock), nameof(AutoReportPrefix)) { priority = Priority.First };
		foreach (var launcher in launchers)
			harmony.Patch(launcher, prefix: prefix);
		launcherCount = launchers.Length;
		return null;
	}

	private static bool SendGameMetricsPrefix()
	{
		LogFirstAndEvery(ref _metricsBlocked, GameSymbols.ModBugReporting.SendGameMetricsMethodName);
		return false;
	}

	private static bool SendTablePrefix(ref Il2CppSystem.Threading.Tasks.Task<bool> __result)
	{
		try
		{
			// Same completed-task construction as ScEarlyAccessOpenPatch. True makes the row sender drop the rows
			// instead of re-queueing them.
			var tcs = new Il2CppSystem.Threading.Tasks.TaskCompletionSource<bool>();
			tcs.SetResult(true);
			__result = tcs.Task;
			LogFirstAndEvery(ref _tablesBlocked, GameSymbols.ModBugReporting.SendTableMethodName);
		}
		catch (Exception ex)
		{
			_log?.LogError("NativeTelemetry: analytics table send blocked but its completed task could not be built: " + ex.GetType().Name + ": " + ex.Message);
		}

		return false;
	}

	private static bool AutoReportPrefix()
	{
		LogFirstAndEvery(ref _autoReportsBlocked, "desync auto bug report");
		return false;
	}

	private static bool SendReportPrefix()
	{
		LogFirstAndEvery(ref _reportsBlocked, GameSymbols.ModBugReporting.SendReportMethodName + " (redirect not active, no bundle written)");
		return false;
	}

	/// <summary>Telemetry fires often; log the first block of each channel and then every 100th.</summary>
	private static void LogFirstAndEvery(ref int counter, string channel)
	{
		var n = ++counter;
		if (n == 1 || n % 100 == 0)
			_log?.LogInfo("NativeTelemetry: send blocked: " + channel + " (" + n + " so far this session).");
	}
}
