using System;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace OfflineUnlockMod;

internal static class FrameStallMonitor
{
	private static bool _registered;
	private static bool _attached;

	internal static void Ensure(ManualLogSource log)
	{
		if (_attached)
			return;

		try
		{
			if (!_registered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<FrameStallMonitorBehaviour>();
				_registered = true;
			}

			var go = new GameObject("OfflineUnlockFrameStallMonitor");
			go.hideFlags = HideFlags.HideAndDontSave;
			go.AddComponent<FrameStallMonitorBehaviour>();
			UnityEngine.Object.DontDestroyOnLoad(go);
			_attached = true;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Frame stall monitor attach failed: " + ex.Message);
		}
	}
}

public sealed class FrameStallMonitorBehaviour : MonoBehaviour
{
	private const float SlowFrameSeconds = 2f;
	private static int _logged;
	private float _lastRealtime;

	private void Awake()
	{
		_lastRealtime = Time.realtimeSinceStartup;
	}

	private void Update()
	{
		OfflinePerformanceProfiler.FlushIfDue();
		// Do not reconcile town UI here — Homm3TownUiCanvasLiftPump owns that hot path.
		// Calling Reconcile from the stall monitor duplicated full-scene canvas walks every frame.
		var now = Time.realtimeSinceStartup;
		var delta = now - _lastRealtime;
		_lastRealtime = now;
		if (delta < SlowFrameSeconds || _logged >= 12)
			return;

		_logged++;
		Homm3MapLoadFlightRecorder.MarkStall(delta);
		var scene = SceneManager.GetActiveScene();
		Plugin.LogSource?.LogInfo(
			"Frame stall monitor: main thread gap "
			+ (delta * 1000f).ToString("0")
			+ " ms at frame "
			+ Time.frameCount
			+ ", realtime="
			+ now.ToString("0.000")
			+ ", scene='"
			+ (scene.IsValid() ? scene.name : "?")
			+ "'"
			+ FormatProfilerContext()
			+ ".");
	}

	private static string FormatProfilerContext()
	{
		if (!OfflinePerformanceProfiler.Enabled)
			return "";
		var active = OfflinePerformanceProfiler.ActiveScopeSummary();
		if (!string.IsNullOrEmpty(active))
			return ", activeProfilerScope=" + active;
		var recent = OfflinePerformanceProfiler.LastCompletedSlowSummary();
		return string.IsNullOrEmpty(recent) ? "" : ", recentSlowProfilerCalls=" + recent;
	}
}
