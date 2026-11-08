using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace OfflineUnlockMod;

internal static class OfflinePerformanceProfiler
{
	private const string FlagFileName = "homm3_runtime_performance_profiler.flag";
	private const int SlowCallThresholdMs = 10;
	private const int ReportIntervalFrames = 180;
	private const int MaxRowsPerReport = 40;
	private const int SlowLineLimit = 240;

	private sealed class Counter
	{
		public long Count;
		public long TotalTicks;
		public long MaxTicks;
		public long Exceptions;
		public string MaxScene;
		public int MaxFrame;
	}

	private static readonly object Gate = new();
	private static readonly Dictionary<string, Counter> Counters = new(StringComparer.Ordinal);
	private static readonly List<string> SlowLines = new();
	private static readonly List<string> LastCompletedSlow = new();
	private static bool _enabled;
	private static bool _logToFile;
	private static bool _fileLoggingFailureWarned;
	private static int _lastReportFrame;
	private static ManualLogSource _log;
	private static string _logPath;

	[ThreadStatic]
	private static Stack<string> ActiveScopes;

	internal static bool Enabled => _enabled;

	internal static void Configure(ManualLogSource log)
	{
		_log = log;
		_enabled = Homm3DiagnosticFlags.IsEnabled(FlagFileName);
		_logToFile = _enabled;
		_lastReportFrame = SafeFrameCount();
		if (!_enabled)
			return;

		try
		{
			var dir = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod");
			Directory.CreateDirectory(dir);
			_logPath = Path.Combine(dir, "runtime_performance_profile.log");
			File.WriteAllText(
				_logPath,
				"OfflineUnlockMod runtime performance profile start " + DateTime.UtcNow.ToString("O") + Environment.NewLine);
		}
		catch (Exception ex)
		{
			_logToFile = false;
			log?.LogWarning("Performance profiler: file logging disabled: " + ex.Message);
		}

		log?.LogWarning(
			"Performance profiler enabled by "
			+ FlagFileName
			+ ": slowCallMs="
			+ SlowCallThresholdMs
			+ ", reportFrames="
			+ ReportIntervalFrames
			+ ", maxRows="
			+ MaxRowsPerReport
			+ ", file="
			+ (_logToFile ? _logPath : "disabled"));
	}

	internal static IDisposable Scope(string key)
	{
		if (!_enabled || string.IsNullOrEmpty(key))
			return NullScope.Instance;
		return new ScopeToken(key);
	}

	internal static long BeginCall(MethodBase method)
	{
		try
		{
			if (!_enabled)
				return 0;
			var key = MethodKey(method);
			PushActive(key);
			return Stopwatch.GetTimestamp();
		}
		catch (Exception ex)
		{
			WarnProfilerFailure("begin", ex);
			return 0;
		}
	}

	internal static void EndCall(MethodBase method, long startTicks, Exception exception)
	{
		try
		{
			if (!_enabled)
				return;
			var key = MethodKey(method);
			if (startTicks > 0)
				Record(key, Stopwatch.GetTimestamp() - startTicks, exception != null);
			PopActive(key);
		}
		catch (Exception ex)
		{
			WarnProfilerFailure("end", ex);
		}
	}

	internal static string ActiveScopeSummary()
	{
		var stack = ActiveScopes;
		if (stack == null || stack.Count == 0)
			return "";
		try
		{
			return string.Join(" <- ", stack.ToArray());
		}
		catch
		{
			return "";
		}
	}

	internal static string LastCompletedSlowSummary()
	{
		lock (Gate)
		{
			if (LastCompletedSlow.Count == 0)
				return "";
			return string.Join(" | ", LastCompletedSlow.ToArray());
		}
	}

	internal static void FlushIfDue(bool force = false)
	{
		if (!_enabled)
			return;
		var frame = SafeFrameCount();
		if (!force && frame - _lastReportFrame < ReportIntervalFrames)
			return;
		_lastReportFrame = frame;

		List<KeyValuePair<string, Counter>> rows;
		List<string> slow;
		lock (Gate)
		{
			rows = new List<KeyValuePair<string, Counter>>(Counters);
			slow = new List<string>(SlowLines);
			SlowLines.Clear();
		}

		rows.Sort((a, b) => b.Value.TotalTicks.CompareTo(a.Value.TotalTicks));
		var sb = new StringBuilder();
		sb.Append("PERF_PROFILE_REPORT frame=").Append(frame);
		sb.Append(" scene='").Append(SafeSceneName()).Append("'");
		sb.Append(" counters=").Append(rows.Count);
		var limit = Math.Min(MaxRowsPerReport, rows.Count);
		for (var i = 0; i < limit; i++)
		{
			var row = rows[i];
			var c = row.Value;
			var totalMs = TicksToMs(c.TotalTicks);
			var maxMs = TicksToMs(c.MaxTicks);
			var avgMs = c.Count <= 0 ? 0.0 : totalMs / c.Count;
			sb.AppendLine();
			sb.Append("  #").Append(i + 1)
				.Append(" totalMs=").Append(totalMs.ToString("0.###"))
				.Append(" avgMs=").Append(avgMs.ToString("0.###"))
				.Append(" maxMs=").Append(maxMs.ToString("0.###"))
				.Append(" count=").Append(c.Count)
				.Append(" exceptions=").Append(c.Exceptions)
				.Append(" maxAt=").Append(c.MaxScene ?? "?").Append("@").Append(c.MaxFrame)
				.Append(" key=").Append(row.Key);
		}

		if (slow.Count > 0)
		{
			sb.AppendLine();
			sb.Append("  slowCallsSinceLastReport=").Append(slow.Count);
			foreach (var line in slow)
			{
				sb.AppendLine();
				sb.Append("    ").Append(line);
			}
		}

		Log(sb.ToString());
	}

	internal static int RegisterHarmonyPatchedMethodProfiler(Harmony profilerHarmony, string ownerHarmonyId, ManualLogSource log)
	{
		if (!_enabled || profilerHarmony == null || string.IsNullOrEmpty(ownerHarmonyId))
			return 0;

		var prefix = new HarmonyMethod(typeof(OfflinePerformanceProfilerHarmonyPatch).GetMethod(
			nameof(OfflinePerformanceProfilerHarmonyPatch.Prefix),
			BindingFlags.Static | BindingFlags.NonPublic));
		var finalizer = new HarmonyMethod(typeof(OfflinePerformanceProfilerHarmonyPatch).GetMethod(
			nameof(OfflinePerformanceProfilerHarmonyPatch.Finalizer),
			BindingFlags.Static | BindingFlags.NonPublic));

		var patched = 0;
		var skipped = 0;
		foreach (var method in Harmony.GetAllPatchedMethods())
		{
			try
			{
				if (method == null || method.DeclaringType == null)
				{
					skipped++;
					continue;
				}

				var info = Harmony.GetPatchInfo(method);
				if (!HasOwner(info, ownerHarmonyId))
					continue;

				profilerHarmony.Patch(method, prefix: prefix, finalizer: finalizer);
				patched++;
			}
			catch (Exception ex)
			{
				skipped++;
				log?.LogWarning("Performance profiler: failed to wrap " + MethodKey(method) + ": " + ex.Message);
			}
		}

		log?.LogWarning("Performance profiler: wrapped " + patched + " Harmony-patched method(s); skipped " + skipped + ".");
		return patched;
	}

	private static bool HasOwner(Patches patches, string ownerHarmonyId)
	{
		if (patches == null)
			return false;
		return HasOwner(patches.Prefixes, ownerHarmonyId)
			|| HasOwner(patches.Postfixes, ownerHarmonyId)
			|| HasOwner(patches.Transpilers, ownerHarmonyId)
			|| HasOwner(patches.Finalizers, ownerHarmonyId);
	}

	private static bool HasOwner(IEnumerable<Patch> patches, string ownerHarmonyId)
	{
		if (patches == null)
			return false;
		foreach (var patch in patches)
		{
			if (patch != null && string.Equals(patch.owner, ownerHarmonyId, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static void Record(string key, long ticks, bool exception)
	{
		if (string.IsNullOrEmpty(key) || ticks < 0)
			return;

		var ms = TicksToMs(ticks);
		var sceneName = SafeSceneName();
		var frame = SafeFrameCount();
		lock (Gate)
		{
			if (!Counters.TryGetValue(key, out var counter))
			{
				counter = new Counter();
				Counters[key] = counter;
			}
			counter.Count++;
			counter.TotalTicks += ticks;
			if (exception)
				counter.Exceptions++;
			if (ticks > counter.MaxTicks)
			{
				counter.MaxTicks = ticks;
				counter.MaxScene = sceneName;
				counter.MaxFrame = frame;
			}

			if (ms >= SlowCallThresholdMs)
			{
				var line = "ms="
					+ ms.ToString("0.###")
					+ " frame="
					+ frame
					+ " scene='"
					+ sceneName
					+ "' exception="
					+ exception
					+ " key="
					+ key;
				if (SlowLines.Count < SlowLineLimit)
					SlowLines.Add(line);
				LastCompletedSlow.Add(line);
				while (LastCompletedSlow.Count > 8)
					LastCompletedSlow.RemoveAt(0);
			}
		}
	}

	private static void PushActive(string key)
	{
		if (string.IsNullOrEmpty(key))
			return;
		ActiveScopes ??= new Stack<string>();
		ActiveScopes.Push(key);
	}

	private static void PopActive(string key)
	{
		var stack = ActiveScopes;
		if (stack == null || stack.Count == 0)
			return;
		stack.Pop();
	}

	private static string MethodKey(MethodBase method)
	{
		if (method == null)
			return "unknown";
		var type = method.DeclaringType;
		return (type == null ? "unknown" : type.FullName) + "." + method.Name;
	}

	private static double TicksToMs(long ticks)
	{
		return ticks * 1000.0 / Stopwatch.Frequency;
	}

	private static void Log(string message)
	{
		_log?.LogInfo(message);
		if (!_logToFile || string.IsNullOrEmpty(_logPath))
			return;
		try
		{
			File.AppendAllText(_logPath, message + Environment.NewLine);
		}
		catch (Exception ex)
		{
			_logToFile = false;
			if (!_fileLoggingFailureWarned)
			{
				_fileLoggingFailureWarned = true;
				_log?.LogWarning("Performance profiler: file logging disabled after append failure: " + ex.Message);
			}
		}
	}

	private static string SafeSceneName()
	{
		try
		{
			var scene = SceneManager.GetActiveScene();
			return scene.IsValid() ? scene.name : "?";
		}
		catch
		{
			return "?";
		}
	}

	private static int SafeFrameCount()
	{
		try
		{
			return Time.frameCount;
		}
		catch
		{
			return -1;
		}
	}

	private static void WarnProfilerFailure(string phase, Exception ex)
	{
		try
		{
			_log?.LogWarning("Performance profiler: " + phase + " bookkeeping failed without altering original call: " + ex.Message);
		}
		catch
		{
		}
	}

	private sealed class ScopeToken : IDisposable
	{
		private readonly string _key;
		private readonly long _start;
		private bool _disposed;

		internal ScopeToken(string key)
		{
			_key = key;
			_start = Stopwatch.GetTimestamp();
			PushActive(key);
		}

		public void Dispose()
		{
			if (_disposed)
				return;
			_disposed = true;
			Record(_key, Stopwatch.GetTimestamp() - _start, exception: false);
			PopActive(_key);
		}
	}

	private sealed class NullScope : IDisposable
	{
		internal static readonly NullScope Instance = new();

		public void Dispose()
		{
		}
	}
}

internal static class OfflinePerformanceProfilerHarmonyPatch
{
	internal static void Prefix(MethodBase __originalMethod, ref long __state)
	{
		try
		{
			__state = OfflinePerformanceProfiler.BeginCall(__originalMethod);
		}
		catch
		{
			__state = 0;
		}
	}

	internal static Exception Finalizer(MethodBase __originalMethod, long __state, Exception __exception)
	{
		try
		{
			OfflinePerformanceProfiler.EndCall(__originalMethod, __state, __exception);
		}
		catch
		{
		}
		return __exception;
	}
}
