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
	/// <summary>Battle-only frame-gap threshold: combat stalls well under HitchMs are still felt at contact.</summary>
	internal const int BattleHitchMs = 40;
	/// <summary>Minimum duration for the "battle ..." hook scopes that attribute those stalls.</summary>
	internal const int BattleScopeMinMs = 15;
	private const int MaxHitchLines = 300;
	private const int MaxBattleHitchLines = 400;
	private const int MaxScopeLines = 600;

	private static readonly Stopwatch Clock = Stopwatch.StartNew();
	private static long _lastMarkMs;
	private static long _loadBeginMs = -1;
	private static int _hitchLines;
	private static int _battleHitchLines;
	private static int _scopeLines;
	private static bool _probeAttached;
	private static bool _probeRegistered;
	private static int _mainThreadId = -1;

	internal static int HitchLinesRemaining => MaxHitchLines - _hitchLines;

	// ---- Harmony patch profiler: times every PatchProcessor.Patch during Plugin.Load, by owning class ----
	private sealed class PatchOwnerStat { internal int Calls; internal double Ms; internal double MaxMs; internal string MaxTarget; }
	private static readonly System.Collections.Generic.Dictionary<string, PatchOwnerStat> PatchByOwner = new(StringComparer.Ordinal);
	private static readonly System.Collections.Generic.Dictionary<string, int> PatchTargetCounts = new(StringComparer.Ordinal);
	private static System.Reflection.FieldInfo _patchProcessorOriginal;
	private static HarmonyLib.Harmony _patchProfilerHarmony;
	private static bool _patchProfileFlushed;
	[ThreadStatic] private static long _patchStartTicks;
	[ThreadStatic] private static int _patchDepth;

	private static void InstallPatchProfiler()
	{
		try
		{
			var flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic;
			var processor = typeof(HarmonyLib.PatchProcessor);
			_patchProcessorOriginal = processor.GetField("original", flags);
			var patch = processor.GetMethod("Patch", flags, null, Type.EmptyTypes, null);
			if (patch == null)
				return;
			var self = typeof(Homm3LoadTiming);
			var mine = System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic;
			_patchProfilerHarmony = new HarmonyLib.Harmony("offlineunlock.loadtiming.patchprofiler");
			_patchProfilerHarmony.Patch(patch,
				prefix: new HarmonyLib.HarmonyMethod(self.GetMethod(nameof(PatchProfilerPrefix), mine)),
				finalizer: new HarmonyLib.HarmonyMethod(self.GetMethod(nameof(PatchProfilerFinalizer), mine)));
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogInfo(Prefix + "patchProfile unavailable: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static void PatchProfilerPrefix()
	{
		if (_patchDepth++ == 0)
			_patchStartTicks = Stopwatch.GetTimestamp();
	}

	private static void PatchProfilerFinalizer(object __instance)
	{
		try
		{
			if (--_patchDepth != 0 || _patchProfileFlushed)
				return;
			var ms = (Stopwatch.GetTimestamp() - _patchStartTicks) * 1000.0 / Stopwatch.Frequency;
			string target = "?";
			try
			{
				if (_patchProcessorOriginal?.GetValue(__instance) is System.Reflection.MethodBase original)
					target = (original.DeclaringType?.Name ?? "?") + "." + original.Name;
			}
			catch { }
			var owner = "?";
			var trace = new StackTrace(2, false);
			for (var i = 0; i < trace.FrameCount && i < 12; i++)
			{
				var type = trace.GetFrame(i)?.GetMethod()?.DeclaringType;
				if (type == null || type == typeof(Homm3LoadTiming) || type.Assembly != typeof(Homm3LoadTiming).Assembly)
					continue;
				while (type.DeclaringType != null)
					type = type.DeclaringType;
				owner = type.Name;
				break;
			}
			lock (PatchByOwner)
			{
				if (!PatchByOwner.TryGetValue(owner, out var stat))
					PatchByOwner[owner] = stat = new PatchOwnerStat();
				stat.Calls++;
				stat.Ms += ms;
				if (ms > stat.MaxMs) { stat.MaxMs = ms; stat.MaxTarget = target; }
				PatchTargetCounts.TryGetValue(target, out var count);
				PatchTargetCounts[target] = count + 1;
			}
		}
		catch
		{
			// Diagnostic only.
		}
	}

	private static void FlushPatchProfile()
	{
		try
		{
			if (_patchProfileFlushed)
				return;
			_patchProfileFlushed = true;
			try { _patchProfilerHarmony?.UnpatchSelf(); } catch { }
			lock (PatchByOwner)
			{
				var owners = new System.Collections.Generic.List<System.Collections.Generic.KeyValuePair<string, PatchOwnerStat>>(PatchByOwner);
				owners.Sort((a, b) => b.Value.Ms.CompareTo(a.Value.Ms));
				var calls = 0;
				var total = 0.0;
				foreach (var pair in owners) { calls += pair.Value.Calls; total += pair.Value.Ms; }
				var repeated = 0;
				var repeatCalls = 0;
				foreach (var pair in PatchTargetCounts)
					if (pair.Value > 1) { repeated++; repeatCalls += pair.Value; }
				Plugin.LogSource?.LogInfo(Prefix + "patchProfile patches=" + calls + " totalMs=" + (long)total
					+ " owners=" + owners.Count + " distinctTargets=" + PatchTargetCounts.Count
					+ " targetsPatchedMoreThanOnce=" + repeated + " (" + repeatCalls + " patches)");
				for (var i = 0; i < owners.Count && i < 60; i++)
				{
					var stat = owners[i].Value;
					Plugin.LogSource?.LogInfo(Prefix + "patchProfile owner=" + owners[i].Key + " patches=" + stat.Calls
						+ " ms=" + (long)stat.Ms + " maxMs=" + (long)stat.MaxMs + " maxTarget=" + stat.MaxTarget);
				}
				PatchByOwner.Clear();
				PatchTargetCounts.Clear();
			}
		}
		catch
		{
			// Diagnostic only.
		}
	}

	// Main-thread JIT cost so far: how much of a slow stretch was first-use compilation of managed code.
	private static System.Reflection.MethodInfo _jitTime;
	private static System.Reflection.MethodInfo _jitCount;
	private static bool _jitResolved;

	private static string JitText()
	{
		try
		{
			if (!_jitResolved)
			{
				_jitResolved = true;
				// System.Runtime.JitInfo exists in the .NET 6 runtime but not in the reference set this plugin builds against.
				var jitInfo = typeof(object).Assembly.GetType("System.Runtime.JitInfo");
				_jitTime = jitInfo?.GetMethod("GetCompilationTime", new[] { typeof(bool) });
				_jitCount = jitInfo?.GetMethod("GetCompiledMethodCount", new[] { typeof(bool) });
			}
			if (_jitTime == null || _jitCount == null)
				return string.Empty;
			var mine = (TimeSpan)_jitTime.Invoke(null, new object[] { true });
			var all = (TimeSpan)_jitTime.Invoke(null, new object[] { false });
			return " jitMainThreadMs=" + (long)mine.TotalMilliseconds
				+ " jitMainThreadMethods=" + _jitCount.Invoke(null, new object[] { true })
				+ " jitAllThreadsMs=" + (long)all.TotalMilliseconds;
		}
		catch
		{
			return string.Empty;
		}
	}

	internal static void Mark(string label)
	{
		try
		{
			var now = Clock.ElapsedMilliseconds;
			if (_loadBeginMs < 0)
			{
				_loadBeginMs = now;
				_mainThreadId = Environment.CurrentManagedThreadId;
				LogPrePluginPhase();
				InstallPatchProfiler();
			}
			if (label == "Plugin.Load.end")
				FlushPatchProfile();
			var sincePrev = now - _lastMarkMs;
			_lastMarkMs = now;
			Plugin.LogSource?.LogInfo(
				Prefix + label
				+ " processUptimeMs=" + ProcessUptimeMs()
				+ " sinceLoadBeginMs=" + (now - _loadBeginMs)
				+ " sincePrevMarkMs=" + sincePrev
				+ JitText());
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

	/// <summary>Battle frame gaps between BattleHitchMs and HitchMs, on their own budget.</summary>
	internal static void LogBattleHitch(string line)
	{
		if (_battleHitchLines >= MaxBattleHitchLines)
			return;
		_battleHitchLines++;
		Plugin.LogSource?.LogInfo(Prefix + line);
	}

	/// <summary>Logs the time since <paramref name="startTicks"/> (a Stopwatch timestamp) when it is at least <paramref name="minMs"/>.</summary>
	internal static void ReportSince(string label, long startTicks, long minMs)
	{
		try
		{
			if (startTicks <= 0)
				return;
			var ms = (Stopwatch.GetTimestamp() - startTicks) * 1000.0 / Stopwatch.Frequency;
			if (ms < minMs || _scopeLines >= MaxScopeLines)
				return;
			_scopeLines++;
			Plugin.LogSource?.LogInfo(Prefix + label + " tookMs=" + ms.ToString("0.0") + " frame=" + SafeFrame());
		}
		catch
		{
			// Diagnostic only.
		}
	}

	private sealed class Total
	{
		internal int Count;
		internal long Ticks;
		internal long MaxTicks;
	}

	private static readonly System.Collections.Generic.Dictionary<string, Total> Totals = new(StringComparer.Ordinal);
	private static readonly object TotalsGate = new();

	/// <summary>
	/// Adds the scope's duration to a per-label total instead of logging each call; totals are logged and reset
	/// at every scene change (<see cref="FlushTotals"/>). For work that runs many times during one load.
	/// Nested labels overlap: an outer total includes the inner ones.
	/// </summary>
	internal static TotalToken Sum(string label) => new(label);

	internal readonly struct TotalToken : IDisposable
	{
		private readonly string _label;
		private readonly long _start;

		internal TotalToken(string label)
		{
			_label = label;
			_start = Stopwatch.GetTimestamp();
		}

		public void Dispose()
		{
			try
			{
				var ticks = Stopwatch.GetTimestamp() - _start;
				lock (TotalsGate)
				{
					if (!Totals.TryGetValue(_label, out var total))
						Totals[_label] = total = new Total();
					total.Count++;
					total.Ticks += ticks;
					if (ticks > total.MaxTicks)
						total.MaxTicks = ticks;
				}
			}
			catch
			{
				// Diagnostic only.
			}
		}
	}

	/// <summary>Logs every total of at least 5 ms gathered since the last flush, then clears them.</summary>
	internal static void FlushTotals(string when)
	{
		try
		{
			Plugin.LogSource?.LogInfo(Prefix + "jit before=" + when + JitText());
			lock (TotalsGate)
			{
				foreach (var pair in Totals)
				{
					var ms = pair.Value.Ticks * 1000.0 / Stopwatch.Frequency;
					if (ms < 5)
						continue;
					Plugin.LogSource?.LogInfo(
						Prefix + "total " + pair.Key
						+ " calls=" + pair.Value.Count
						+ " totalMs=" + ms.ToString("0")
						+ " maxMs=" + (pair.Value.MaxTicks * 1000.0 / Stopwatch.Frequency).ToString("0.0")
						+ " before=" + when);
				}
				Totals.Clear();
			}
		}
		catch
		{
			// Diagnostic only.
		}
	}

	/// <summary>
	/// What the process did before the plugin's first line: wall time since process start against CPU time
	/// used, so a long launch can be told apart as computing (CPU close to wall) or waiting on disk/other.
	/// </summary>
	private static void LogPrePluginPhase()
	{
		try
		{
			using var p = Process.GetCurrentProcess();
			var now = DateTime.Now;
			Plugin.LogSource?.LogInfo(
				Prefix + "prePlugin processStart=" + p.StartTime.ToString("HH:mm:ss.fff")
				+ " now=" + now.ToString("HH:mm:ss.fff")
				+ " wallMs=" + (long)(now - p.StartTime).TotalMilliseconds
				+ " cpuUserMs=" + (long)p.UserProcessorTime.TotalMilliseconds
				+ " cpuKernelMs=" + (long)p.PrivilegedProcessorTime.TotalMilliseconds
				+ " threads=" + p.Threads.Count
				+ " modules=" + p.Modules.Count
				+ " assemblies=" + AppDomain.CurrentDomain.GetAssemblies().Length
				+ " workingSetMb=" + (p.WorkingSet64 >> 20));

			// Threads are created as each stage of the launch begins (runtime, engine jobs, graphics, audio), so
			// their start times, in seconds after process start, give a coarse timeline of the phase.
			var starts = new System.Collections.Generic.List<double>();
			foreach (ProcessThread thread in p.Threads)
			{
				try { starts.Add((thread.StartTime - p.StartTime).TotalSeconds); }
				catch { }
			}
			starts.Sort();
			var text = new System.Text.StringBuilder();
			var last = double.NaN;
			var run = 0;
			for (var i = 0; i <= starts.Count; i++)
			{
				var value = i < starts.Count ? Math.Round(starts[i], 1) : double.NaN;
				if (i < starts.Count && value == last)
				{
					run++;
					continue;
				}
				if (run > 0)
					text.Append(last.ToString("0.0")).Append(run > 1 ? "x" + run : "").Append(' ');
				last = value;
				run = 1;
			}
			Plugin.LogSource?.LogInfo(Prefix + "prePlugin threadStartsSec " + text.ToString().TrimEnd());
		}
		catch
		{
			// Diagnostic only.
		}
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
				else if (gapMs >= Homm3LoadTiming.BattleHitchMs && string.Equals(_scene, "battle", StringComparison.Ordinal))
				{
					Homm3LoadTiming.LogBattleHitch(
						"battle hitch gapMs=" + gapMs.ToString("0")
						+ " frame=" + frame
						+ " realtime=" + now.ToString("0.000"));
				}
			}
			_lastRealtime = now;

			var active = SceneManager.GetActiveScene();
			var name = active.IsValid() ? active.name : "?";
			if (!string.Equals(name, _scene, StringComparison.Ordinal))
			{
				Homm3LoadTiming.FlushTotals("scene '" + name + "' frame=" + frame);
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
