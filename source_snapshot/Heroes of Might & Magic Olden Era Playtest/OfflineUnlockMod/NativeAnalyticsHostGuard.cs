using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Second, independent layer behind the bug report redirect and the telemetry block (docs/mod_bug_reporting.md,
/// "Analytics host guard"). Those two layers hook named game methods; when a game update renames them both can fail
/// and the native report sink is left unprotected. This layer hooks the gRPC client library instead: every
/// <c>GrpcChannel(Uri, GrpcChannelOptions)</c> construction whose host is the game developer's analytics host is
/// pointed at a closed local port (127.0.0.1:9), so nothing the game queues on that channel can leave the machine.
/// Other hosts are untouched.
///
/// Bound behind <c>blockNativeTelemetry</c> (default on). Failure to bind is logged at error level; nothing here
/// throws out of <see cref="TryRegister"/> or out of the prefix. Nothing here opens a network connection.
///
/// <see cref="ShowStateWarningIfNeeded"/> puts a dismissible on-screen notice up whenever the redirect is not in its
/// Redirecting state, so a player is never left believing their reports go to the mod author when they do not.
///
/// Proof: source/static validated (tools/validate_mod_bug_reporting_contract.py), build target and live-interop gate.
/// The hook and the notice have not been exercised in a running game.
/// </summary>
internal static class NativeAnalyticsHostGuard
{
	// The only host refused. Kept out of the redirect/transport/telemetry sources, which must contain no developer host.
	private const string BlockedHost = "an.prod.hex.unfrozen.app";
	private const string SinkAddress = "https://127.0.0.1:9/";

	private static ManualLogSource _log;
	private static int _redirected;

	internal static bool Active { get; private set; }

	internal static void TryRegister(Harmony harmony, ManualLogSource log, LauncherConfig cfg)
	{
		_log = log;
		if (cfg == null || !cfg.BlockNativeTelemetry)
		{
			log?.LogWarning("AnalyticsHostGuard: off (blockNativeTelemetry=false). The game developer's analytics host is reachable.");
			return;
		}

		try
		{
			// A real-named gRPC library type, not an obfuscated game symbol, so no GameSymbols entry is needed.
			var ctor = typeof(Grpc.Net.Client.GrpcChannel).GetConstructor(
				BindingFlags.Public | BindingFlags.Instance,
				null,
				new[] { typeof(Il2CppSystem.Uri), typeof(Grpc.Net.Client.GrpcChannelOptions) },
				null);
			if (ctor == null)
			{
				log?.LogError("AnalyticsHostGuard: NOT ACTIVE, GrpcChannel(Uri, GrpcChannelOptions) constructor not found.");
				return;
			}

			harmony.Patch(ctor, prefix: new HarmonyMethod(typeof(NativeAnalyticsHostGuard), nameof(ChannelPrefix)) { priority = Priority.First });
			Active = true;
			log?.LogInfo("AnalyticsHostGuard: gRPC channels to the game developer's analytics host are redirected to a closed local port.");
		}
		catch (Exception ex)
		{
			log?.LogError("AnalyticsHostGuard: NOT ACTIVE, registration failed (" + ex.GetType().Name + ": " + ex.Message + ").");
		}
	}

	internal static bool IsBlockedHost(string host)
	{
		return host != null && string.Equals(host.Trim().TrimEnd('.'), BlockedHost, StringComparison.OrdinalIgnoreCase);
	}

	private static void ChannelPrefix(ref Il2CppSystem.Uri address)
	{
		try
		{
			if (address == null || !IsBlockedHost(address.Host))
				return;
			address = new Il2CppSystem.Uri(SinkAddress);
			var n = ++_redirected;
			if (n == 1 || n % 100 == 0)
				_log?.LogInfo("AnalyticsHostGuard: analytics channel redirected to a closed local port (" + n + " so far this session).");
		}
		catch (Exception ex)
		{
			_log?.LogError("AnalyticsHostGuard: channel check failed (" + ex.GetType().Name + "); channel left unchanged.");
		}
	}

	/// <summary>Shows the on-screen notice for every bug report state other than Redirecting that needs one.</summary>
	internal static void ShowStateWarningIfNeeded(LauncherConfig cfg)
	{
		try
		{
			var message = StateWarning(
				ModBugReportRedirect.State,
				cfg != null && cfg.ModBugReporting,
				NativeTelemetryBlock.ReportSinkBlocked,
				Active);
			if (message == null)
				return;
			_log?.LogWarning("ModBugReporting: on-screen notice: " + message);
			ModBugReportWarningHost.Show(message);
		}
		catch (Exception ex)
		{
			_log?.LogError("ModBugReporting: on-screen state notice could not be shown (" + ex.GetType().Name + ": " + ex.Message + ").");
		}
	}

	internal static string StateWarning(ModBugReportRedirect.GuardState state, bool reportingEnabled, bool reportSinkBlocked, bool hostGuardActive)
	{
		// Player-facing wording; the technical cause is already logged to BepInEx/LogOutput.log.
		var fallback = reportSinkBlocked
			? " Reports from the game's own form are not sent anywhere."
			: hostGuardActive
				? " The mod tries to stop the game's own form from sending reports, but this is not guaranteed."
				: " Reports from the game's own form may be sent to the game's developer.";
		switch (state)
		{
			case ModBugReportRedirect.GuardState.Redirecting:
				return null;
			case ModBugReportRedirect.GuardState.EntryPointsBlocked:
				return "Bug reports are turned off for this session. The game's bug report buttons are disabled and nothing is sent.";
			case ModBugReportRedirect.GuardState.SubmissionUnavailable:
				return "Bug reports can't be sent this session. Anything you submit with the game's bug report form is discarded.";
			case ModBugReportRedirect.GuardState.Unprotected:
				return "The mod could not take over the game's bug report form this session."
				       + fallback + " Please don't use the in-game bug report form until you restart the game.";
			default:
				if (!reportingEnabled && reportSinkBlocked)
					return null;
				return "Mod bug reporting is turned off in the mod settings, so the game's bug report form does not send reports to the mod team."
				       + fallback;
		}
	}
}

/// <summary>Dismissible IMGUI notice for <see cref="NativeAnalyticsHostGuard.ShowStateWarningIfNeeded"/>.</summary>
public sealed class ModBugReportWarningHost : MonoBehaviour
{
	private const string HostObjectName = "OfflineUnlockMod.ModBugReportWarning";
	private static ModBugReportWarningHost _instance;
	private static string _message;
	private static bool _registered;

	public ModBugReportWarningHost(IntPtr ptr) : base(ptr) { }

	internal static void Show(string message)
	{
		_message = message;
		if (_instance != null)
			return;
		if (!_registered)
		{
			ClassInjector.RegisterTypeInIl2Cpp<ModBugReportWarningHost>();
			_registered = true;
		}
		var go = new GameObject(HostObjectName) { hideFlags = HideFlags.HideAndDontSave };
		UnityEngine.Object.DontDestroyOnLoad(go);
		_instance = go.AddComponent<ModBugReportWarningHost>();
	}

	private void OnGUI()
	{
		var previousMatrix = GUI.matrix;
		try
		{
			if (_message == null)
				return;
			// Same 720-line virtual screen as the bug report window, so the notice stays readable at 1440p/4K.
			var scale = Mathf.Max(1f, Screen.height / 720f);
			GUI.matrix = Matrix4x4.TRS(Vector3.zero, Quaternion.identity, new Vector3(scale, scale, 1f));
			var width = Mathf.Min(560f, Screen.width / scale - 32f);
			var area = new Rect(16f, 16f, width, 150f);
			GUI.Box(area, GUIContent.none);
			GUILayout.BeginArea(new Rect(area.x + 10f, area.y + 8f, area.width - 20f, area.height - 16f));
			try
			{
				var style = new GUIStyle(GUI.skin.label) { wordWrap = true };
				GUILayout.Label("Bug reports", GUI.skin.label);
				GUILayout.Label(_message, style);
				if (GUILayout.Button("Dismiss", GUILayout.Width(100f), GUILayout.Height(28f)))
					_message = null;
			}
			finally
			{
				GUILayout.EndArea();
			}
		}
		catch (Exception)
		{
			_message = null;
		}
		finally
		{
			GUI.matrix = previousMatrix;
		}
	}
}
