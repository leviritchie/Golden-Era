using System;
using System.IO;
using System.Text;
using HarmonyLib;
using Hex.UI.City;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// Volatile live probe: Harmony close/open tracers for BUILDING VIEW PANEL.
/// Events are appended to live_probe_bridge/artifacts/hall_close_trace.log because
/// each volatile_load_probe_assembly call loads a fresh assembly (static memory does not persist).
/// </summary>
public static class HallCloseTrace20260723d
{
	private const string HarmonyId = "offlineunlock.hall.close.trace.20260723d";
	private const string MarkerPathRelative = "artifacts/hall_close_trace.installed";
	private const string LogPathRelative = "artifacts/hall_close_trace.log";

	private static bool _patchedThisLoad;
	private static string _bridgeRoot;

	public static string Run()
	{
		return Install();
	}

	public static string Install()
	{
		try
		{
			EnsureBridgeRoot();
			Directory.CreateDirectory(Path.Combine(_bridgeRoot, "artifacts"));
			if (!File.Exists(MarkerPath()))
			{
				var harmony = new Harmony(HarmonyId);
				PatchPrefix(harmony, typeof(BhUIBuildingSession), "OnExitBtn", nameof(PrefixBuildingOnExitBtn));
				PatchPrefix(harmony, typeof(BhUIBuildingSession), "OnHide", nameof(PrefixBuildingOnHide));
				PatchPrefix(harmony, typeof(BhUIBuildingSession), "OnEscapeClick", nameof(PrefixBuildingOnEscapeClick));
				PatchPrefix(harmony, typeof(BhNavigationView), "Method_Public_Void_ECityNavigation_0", nameof(PrefixNavigationSelect));
				PatchPrefix(harmony, typeof(BhNavigationView), "OnDeselect", nameof(PrefixNavigationOnDeselect));
				PatchPrefix(harmony, typeof(BhNavigationView), "OnSoftDeselect", nameof(PrefixNavigationOnSoftDeselect));
				PatchPrefix(harmony, typeof(BhNavigationView), "Hide", nameof(PrefixNavigationHide));
				PatchPrefix(harmony, typeof(BhNavigationView), "Show", nameof(PrefixNavigationShow));
				WriteUtf8(MarkerPath(), DateTime.UtcNow.ToString("o"));
				AddEvent("installed-new");
			}
			else if (!_patchedThisLoad)
			{
				// Marker exists from a prior load; Harmony already points at that prior load's
				// methods. Re-patching the same id from a new assembly duplicates handlers, so
				// leave patches alone and only use this load for explicit Trigger/Dump actions.
				AddEvent("install-skipped-already-marked");
			}
			_patchedThisLoad = true;
			return Status("installed");
		}
		catch (Exception ex)
		{
			return "{\"ok\":false,\"error\":\"install-failed\",\"exception\":\""
				+ Escape(ex.GetType().Name + ":" + ex.Message) + "\"}";
		}
	}

	public static string Clear()
	{
		EnsureBridgeRoot();
		Directory.CreateDirectory(Path.Combine(_bridgeRoot, "artifacts"));
		WriteUtf8(LogPath(), "");
		AddEvent("cleared");
		return Status("cleared");
	}

	public static string Dump()
	{
		return Status("dump");
	}

	public static string Snapshot()
	{
		return Status("snapshot");
	}

	public static string TriggerHudOpen(string unused)
	{
		Install();
		try
		{
			var nav = FindCityNavigation();
			if (nav == null)
				return "{\"ok\":false,\"error\":\"navigation-missing\"}";
			AddEvent("trigger-hud-open begin " + SnapshotPanelShort());
			nav.Method_Public_Void_ECityNavigation_0(ECityNavigation.BuildingsConstruction);
			AddEvent("trigger-hud-open after-select " + SnapshotPanelShort());
			return Status("triggered");
		}
		catch (Exception ex)
		{
			AddEvent("trigger-hud-open failed " + ex.GetType().Name + ":" + ex.Message);
			return "{\"ok\":false,\"error\":\"trigger-failed\",\"exception\":\""
				+ Escape(ex.GetType().Name + ":" + ex.Message) + "\"}";
		}
	}

	private static void PatchPrefix(Harmony harmony, Type type, string methodName, string prefixName)
	{
		var method = AccessTools.Method(type, methodName);
		var prefix = AccessTools.Method(typeof(HallCloseTrace20260723d), prefixName);
		if (method == null || prefix == null)
			throw new InvalidOperationException("missing patch surface " + type.FullName + "." + methodName);
		harmony.Patch(method, prefix: new HarmonyMethod(prefix));
	}

	private static void PrefixBuildingOnExitBtn()
	{
		AddEvent("BhUIBuildingSession.OnExitBtn " + SnapshotPanelShort() + " | " + TrimStack(Environment.StackTrace));
	}

	private static void PrefixBuildingOnHide()
	{
		AddEvent("BhUIBuildingSession.OnHide " + SnapshotPanelShort() + " | " + TrimStack(Environment.StackTrace));
	}

	private static void PrefixBuildingOnEscapeClick()
	{
		AddEvent("BhUIBuildingSession.OnEscapeClick " + SnapshotPanelShort() + " | " + TrimStack(Environment.StackTrace));
	}

	private static void PrefixNavigationSelect(ECityNavigation __0)
	{
		AddEvent("BhNavigationView.Select " + __0 + " " + SnapshotPanelShort() + " | " + TrimStack(Environment.StackTrace));
	}

	private static void PrefixNavigationOnDeselect(ECityNavigation __0)
	{
		AddEvent("BhNavigationView.OnDeselect " + __0 + " " + SnapshotPanelShort());
	}

	private static void PrefixNavigationOnSoftDeselect()
	{
		AddEvent("BhNavigationView.OnSoftDeselect " + SnapshotPanelShort());
	}

	private static void PrefixNavigationHide(ECityNavigation __0)
	{
		AddEvent("BhNavigationView.Hide " + __0 + " " + SnapshotPanelShort());
	}

	private static void PrefixNavigationShow(ECityNavigation __0)
	{
		AddEvent("BhNavigationView.Show " + __0 + " " + SnapshotPanelShort());
	}

	private static BhNavigationView FindCityNavigation()
	{
		var all = UnityEngine.Object.FindObjectsOfType<BhNavigationView>(true);
		for (var i = 0; i < all.Length; i++)
		{
			var candidate = all[i];
			if (candidate == null || candidate.gameObject == null)
				continue;
			if (!candidate.gameObject.activeInHierarchy)
				continue;
			return candidate;
		}
		return null;
	}

	private static GameObject FindBuildingPanel()
	{
		var all = UnityEngine.Object.FindObjectsOfType<BhUIBuildingSession>(true);
		for (var i = 0; i < all.Length; i++)
		{
			var session = all[i];
			if (session == null || session.gameObject == null)
				continue;
			if (string.Equals(session.gameObject.name, "BUILDING VIEW PANEL", StringComparison.Ordinal))
				return session.gameObject;
		}
		return GameObject.Find("BUILDING VIEW PANEL");
	}

	private static string SnapshotPanelShort()
	{
		var go = FindBuildingPanel();
		if (go == null)
			return "panel=null scene=" + SceneManager.GetActiveScene().name;
		var canvas = go.GetComponent<Canvas>();
		var group = go.GetComponent<CanvasGroup>();
		return "panelActive=" + go.activeInHierarchy
			+ " canvasEnabled=" + (canvas != null && canvas.enabled)
			+ " sort=" + (canvas == null ? -1 : canvas.sortingOrder)
			+ " override=" + (canvas != null && canvas.overrideSorting)
			+ " alpha=" + (group == null ? -1f : group.alpha)
			+ " interactable=" + (group != null && group.interactable)
			+ " blocks=" + (group != null && group.blocksRaycasts)
			+ " scene=" + SceneManager.GetActiveScene().name;
	}

	private static void EnsureBridgeRoot()
	{
		if (!string.IsNullOrEmpty(_bridgeRoot))
			return;
		// Probe DLL lives in live_probe_bridge/probes/*.dll
		var asmPath = typeof(HallCloseTrace20260723d).Assembly.Location;
		if (string.IsNullOrEmpty(asmPath))
		{
			// Assembly.Load(byte[]) has empty Location; fall back to known plugin path via cwd-independent marker.
			var candidates = new[]
			{
				@"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod\live_probe_bridge",
			};
			for (var i = 0; i < candidates.Length; i++)
			{
				if (Directory.Exists(candidates[i]))
				{
					_bridgeRoot = candidates[i];
					return;
				}
			}
			throw new InvalidOperationException("bridge root not found");
		}
		_bridgeRoot = Path.GetFullPath(Path.Combine(Path.GetDirectoryName(asmPath), ".."));
	}

	private static string LogPath()
	{
		EnsureBridgeRoot();
		return Path.Combine(_bridgeRoot, LogPathRelative.Replace('/', Path.DirectorySeparatorChar));
	}

	private static string MarkerPath()
	{
		EnsureBridgeRoot();
		return Path.Combine(_bridgeRoot, MarkerPathRelative.Replace('/', Path.DirectorySeparatorChar));
	}

	private static void AddEvent(string value)
	{
		var line = "[" + DateTime.UtcNow.ToString("HH:mm:ss.fff") + " f=" + Time.frameCount + "] " + value;
		try
		{
			EnsureBridgeRoot();
			Directory.CreateDirectory(Path.Combine(_bridgeRoot, "artifacts"));
			AppendUtf8(LogPath(), line.Replace("\r", " ").Replace("\n", " || ") + "\n");
		}
		catch
		{
		}
		try
		{
			Debug.Log("[HallCloseTrace] " + value);
		}
		catch
		{
		}
	}

	private static string TrimStack(string stack)
	{
		if (string.IsNullOrEmpty(stack))
			return "";
		var lines = stack.Replace("\r\n", "\n").Split('\n');
		var sb = new StringBuilder();
		var kept = 0;
		for (var i = 0; i < lines.Length && kept < 14; i++)
		{
			var line = lines[i].Trim();
			if (string.IsNullOrEmpty(line))
				continue;
			if (line.IndexOf("HallCloseTrace", StringComparison.Ordinal) >= 0)
				continue;
			if (line.IndexOf("HarmonyLib", StringComparison.Ordinal) >= 0)
				continue;
			if (kept > 0) sb.Append(" || ");
			sb.Append(line);
			kept++;
		}
		return sb.ToString();
	}

	private static void WriteUtf8(string path, string text)
	{
		File.WriteAllText(path, text ?? "", new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
	}

	private static void AppendUtf8(string path, string text)
	{
		File.AppendAllText(path, text ?? "", new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
	}

	private static string Status(string note)
	{
		var sb = new StringBuilder(1024);
		sb.Append("{\"ok\":true,\"note\":\"").Append(Escape(note)).Append("\"");
		sb.Append(",\"marked\":").Append(File.Exists(MarkerPath()) ? "true" : "false");
		sb.Append(",\"panel\":\"").Append(Escape(SnapshotPanelShort())).Append("\"");
		sb.Append(",\"activeScene\":\"").Append(Escape(SceneManager.GetActiveScene().name)).Append("\"");
		sb.Append(",\"logPath\":\"").Append(Escape(LogPath())).Append("\"}");
		return sb.ToString();
	}

	private static string Escape(string value)
	{
		if (value == null)
			return "";
		return value
			.Replace("\\", "\\\\")
			.Replace("\"", "\\\"")
			.Replace("\r", "\\r")
			.Replace("\n", "\\n")
			.Replace("\t", "\\t");
	}
}
