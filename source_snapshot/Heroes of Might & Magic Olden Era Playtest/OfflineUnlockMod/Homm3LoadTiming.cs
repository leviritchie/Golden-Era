using System;
using System.Diagnostics;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace OfflineUnlockMod;

/// <summary>
/// Always-on, bounded load-time instrumentation. Every line carries the "LoadTiming:" prefix so a
/// timed session can be read straight out of LogOutput.log (BepInEx lines carry no timestamps).
/// Marks report process uptime, time since Plugin.Load began and time since the previous mark; the
/// frame probe reports scene changes and main-thread hitches (>= <see cref="HitchMs"/>) with Unity
/// frame numbers so they align with Player.log "[GameLoading] ... frame: N" lines.
/// Diagnostic only: every path is try/catch and bounded; it never changes gameplay.
/// Proof: source/static only until a timed session log shows the lines.
/// </summary>
internal static class Homm3LoadTiming
{
	internal const string Prefix = "LoadTiming: ";
	internal const int HitchMs = 250;
	private const int MaxHitchLines = 300;
	private const int MaxScopeLines = 200;

	private static readonly Stopwatch Clock = Stopwatch.StartNew();
	private static long _lastMarkMs;
	private static long _loadBeginMs = -1;
	private static int _hitchLines;
	private static int _scopeLines;
	private static bool _probeAttached;
	private static bool _probeRegistered;
	private static int _mainThreadId = -1;

	internal static int HitchLinesRemaining => MaxHitchLines - _hitchLines;

	internal static void Mark(string label)
	{
		try
		{
			var now = Clock.ElapsedMilliseconds;
			if (_loadBeginMs < 0)
			{
				_loadBeginMs = now;
				_mainThreadId = Environment.CurrentManagedThreadId;
			}
			var sincePrev = now - _lastMarkMs;
			_lastMarkMs = now;
			Plugin.LogSource?.LogInfo(
				Prefix + label
				+ " processUptimeMs=" + ProcessUptimeMs()
				+ " sinceLoadBeginMs=" + (now - _loadBeginMs)
				+ " sincePrevMarkMs=" + sincePrev);
		}
		catch
		{
			// Diagnostic only.
		}
	}

	/// <summary>Logs the scope duration when it is at least <paramref name="minMs"/> (bounded line count).</summary>
	internal static ScopeToken Scope(string label, long minMs = 0) => new(label, minMs);

	internal readonly struct ScopeToken : IDisposable
	{
		private readonly string _label;
		private readonly long _minMs;
		private readonly long _start;

		internal ScopeToken(string label, long minMs)
		{
			_label = label;
			_minMs = minMs;
			_start = Stopwatch.GetTimestamp();
		}

		public void Dispose()
		{
			try
			{
				var ms = (Stopwatch.GetTimestamp() - _start) * 1000.0 / Stopwatch.Frequency;
				if (ms < _minMs || _scopeLines >= MaxScopeLines)
					return;
				_scopeLines++;
				Plugin.LogSource?.LogInfo(
					Prefix + _label + " tookMs=" + ms.ToString("0.0")
					+ " processUptimeMs=" + ProcessUptimeMs()
					+ " frame=" + SafeFrame());
			}
			catch
			{
				// Diagnostic only.
			}
		}
	}

	internal static void EnsureFrameProbe(ManualLogSource log)
	{
		if (_probeAttached)
			return;
		try
		{
			if (!_probeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3LoadTimingProbe>();
				_probeRegistered = true;
			}
			var go = new GameObject("HOMM3_LOAD_TIMING_PROBE");
			go.hideFlags = HideFlags.HideAndDontSave;
			go.AddComponent<Homm3LoadTimingProbe>();
			UnityEngine.Object.DontDestroyOnLoad(go);
			_probeAttached = true;
		}
		catch (Exception ex)
		{
			log?.LogWarning(Prefix + "frame probe attach failed: " + ex.Message);
		}
	}

	internal static void LogHitch(string line)
	{
		if (_hitchLines >= MaxHitchLines)
			return;
		_hitchLines++;
		Plugin.LogSource?.LogInfo(Prefix + line);
	}

	internal static long ProcessUptimeMs()
	{
		try
		{
			using var p = Process.GetCurrentProcess();
			return (long)(DateTime.Now - p.StartTime).TotalMilliseconds;
		}
		catch
		{
			return -1;
		}
	}

	private static int SafeFrame()
	{
		// Unity API only on the thread Plugin.Load ran on; other threads report -1.
		if (_mainThreadId < 0 || Environment.CurrentManagedThreadId != _mainThreadId)
			return -1;
		try { return Time.frameCount; }
		catch { return -1; }
	}
}

/// <summary>
/// Per-frame probe for <see cref="Homm3LoadTiming"/>: logs active-scene changes (with the time spent
/// in the previous scene and its hitch totals) and every main-thread gap >= HitchMs, bounded.
/// </summary>
public sealed class Homm3LoadTimingProbe : MonoBehaviour
{
	private float _lastRealtime = -1f;
	private string _scene;
	private float _sceneStart;
	private int _sceneStartFrame;
	private int _sceneHitches;
	private double _sceneHitchMs;
	private double _sceneLongestMs;
	private bool _firstFrameLogged;

	private void Update()
	{
		try
		{
			var now = Time.realtimeSinceStartup;
			var frame = Time.frameCount;
			if (!_firstFrameLogged)
			{
				_firstFrameLogged = true;
				Homm3LoadTiming.LogHitch(
					"first probe frame frame=" + frame
					+ " realtime=" + now.ToString("0.000")
					+ " processUptimeMs=" + Homm3LoadTiming.ProcessUptimeMs());
			}

			if (_lastRealtime >= 0f)
			{
				var gapMs = (now - _lastRealtime) * 1000.0;
				if (gapMs >= Homm3LoadTiming.HitchMs)
				{
					_sceneHitches++;
					_sceneHitchMs += gapMs;
					if (gapMs > _sceneLongestMs)
						_sceneLongestMs = gapMs;
					Homm3LoadTiming.LogHitch(
						"hitch gapMs=" + gapMs.ToString("0")
						+ " frame=" + frame
						+ " realtime=" + now.ToString("0.000")
						+ " scene='" + (_scene ?? "?") + "'");
				}
			}
			_lastRealtime = now;

			var active = SceneManager.GetActiveScene();
			var name = active.IsValid() ? active.name : "?";
			if (!string.Equals(name, _scene, StringComparison.Ordinal))
			{
				if (_scene != null)
				{
					Homm3LoadTiming.LogHitch(
						"scene '" + _scene + "' -> '" + name + "'"
						+ " prevSceneSeconds=" + (now - _sceneStart).ToString("0.000")
						+ " prevSceneFrames=" + (frame - _sceneStartFrame)
						+ " prevSceneHitches=" + _sceneHitches
						+ " prevSceneHitchMs=" + _sceneHitchMs.ToString("0")
						+ " prevSceneLongestMs=" + _sceneLongestMs.ToString("0")
						+ " frame=" + frame
						+ " realtime=" + now.ToString("0.000"));
				}
				else
				{
					Homm3LoadTiming.LogHitch("scene first='" + name + "' frame=" + frame + " realtime=" + now.ToString("0.000"));
				}
				_scene = name;
				_sceneStart = now;
				_sceneStartFrame = frame;
				_sceneHitches = 0;
				_sceneHitchMs = 0;
				_sceneLongestMs = 0;
			}
		}
		catch
		{
			// Diagnostic only.
		}
	}
}
