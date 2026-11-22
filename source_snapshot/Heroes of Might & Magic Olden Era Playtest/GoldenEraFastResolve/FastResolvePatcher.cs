using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Threading;
using BepInEx;
using BepInEx.Preloader.Core.Patching;

namespace GoldenEraFastResolve;

/// <summary>
/// BepInEx preloader patcher (goes in BepInEx/patchers). BepInEx answers every assembly-resolve request by
/// listing every folder under BepInEx/core, BepInEx/patchers and BepInEx/plugins and probing each one for
/// "name.dll". Golden Era keeps ~4,000 asset folders under plugins, and BepInEx asks once per game interop
/// assembly (142 of them) before the plugin loads, so that search cost about 70 seconds of every launch
/// (measured 2026-11-18: 14 million file-system calls, no file reads).
/// This patcher swaps that handler for one with the same answers from a one-time index of the DLL and EXE
/// files in those three trees. Handler order is preserved: this search first, then BepInEx's interop search.
/// </summary>
[PatcherPluginInfo("goldenera.fastresolve", "Golden Era Fast Resolve", "1.0.0")]
public sealed class FastResolvePatcher : BasePatcher
{
	private static readonly object Gate = new object();
	private static Dictionary<string, List<string>> _index;
	private static BepInEx.Logging.ManualLogSource _log;
	private static long _requests;
	private static long _ticks;
	private static int _summaryLogged;
	private static long _lastLoadTicks;
	private static string _lastLoadName = "(start)";
	private static int _pluginLoadLogged;
	private const long GapLogMs = 1000;
	private const long SlowResolveMs = 200;

	public override void Initialize()
	{
		try
		{
			_log = Log;
			Crumb("patcher.initialize");
			_lastLoadTicks = Stopwatch.GetTimestamp();
			AppDomain.CurrentDomain.AssemblyLoad += OnAssemblyLoad;
			const BindingFlags flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
			Type runner = null;
			Type interop = null;
			foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
			{
				if (assembly.GetName().Name != "BepInEx.Unity.IL2CPP")
					continue;
				runner = assembly.GetType("BepInEx.Unity.IL2CPP.UnityPreloaderRunner");
				interop = assembly.GetType("BepInEx.Unity.IL2CPP.Il2CppInteropManager");
			}
			var local = runner?.GetMethod("LocalResolve", flags);
			if (local == null)
			{
				Log.LogWarning("BepInEx local resolve handler not found; leaving assembly resolution unchanged.");
				return;
			}
			var localHandler = (ResolveEventHandler)Delegate.CreateDelegate(typeof(ResolveEventHandler), local);
			AppDomain.CurrentDomain.AssemblyResolve -= localHandler;
			AppDomain.CurrentDomain.AssemblyResolve += Resolve;

			// Keep BepInEx's order: its interop search ran after the local one, so move it behind ours.
			var interopResolve = interop?.GetMethod("ResolveInteropAssemblies", flags);
			if (interopResolve != null)
			{
				var interopHandler = (ResolveEventHandler)Delegate.CreateDelegate(typeof(ResolveEventHandler), interopResolve);
				AppDomain.CurrentDomain.AssemblyResolve -= interopHandler;
				AppDomain.CurrentDomain.AssemblyResolve += interopHandler;
			}
			Log.LogInfo("Assembly resolution now uses a one-time file index instead of a folder walk per request.");
		}
		catch (Exception ex)
		{
			Log.LogWarning("Fast resolve not installed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	public override void Finalizer()
	{
		Crumb("patcher.finalizer");
	}

	/// <summary>
	/// Launch timing crumbs (2026-11-20): process uptime and CPU split at fixed points, so a slow launch shows
	/// which stretch between the preloader and the plugin's Load is slow without a sampled launch.
	/// Pure System.Diagnostics; safe on any thread (no IL2CPP objects).
	/// </summary>
	private static void Crumb(string label, string extra = null)
	{
		try
		{
			using var process = Process.GetCurrentProcess();
			var uptime = (long)(DateTime.Now - process.StartTime).TotalMilliseconds;
			_log?.LogInfo("Timing: " + label + " uptimeMs=" + uptime
				+ " cpuUserMs=" + (long)process.UserProcessorTime.TotalMilliseconds
				+ " cpuKernelMs=" + (long)process.PrivilegedProcessorTime.TotalMilliseconds
				+ " threads=" + process.Threads.Count
				+ " resolves=" + Interlocked.Read(ref _requests)
				+ (string.IsNullOrEmpty(extra) ? "" : " " + extra));
		}
		catch
		{
			// Timing is diagnostic only.
		}
	}

	private static void OnAssemblyLoad(object sender, AssemblyLoadEventArgs args)
	{
		try
		{
			var name = args.LoadedAssembly.GetName().Name;
			var now = Stopwatch.GetTimestamp();
			var previous = Interlocked.Exchange(ref _lastLoadTicks, now);
			var gapMs = (now - previous) * 1000 / Stopwatch.Frequency;
			var previousName = _lastLoadName;
			_lastLoadName = name;
			if (name == "OfflineUnlockMod")
			{
				if (Interlocked.Exchange(ref _pluginLoadLogged, 1) == 0)
					Crumb("pluginAssembly.loaded", "gapMs=" + gapMs + " after=" + previousName);
				return;
			}
			if (gapMs >= GapLogMs)
				Crumb("assemblyLoad.afterGap", "name=" + name + " gapMs=" + gapMs + " after=" + previousName);
		}
		catch
		{
			// Timing is diagnostic only.
		}
	}

	private static Assembly Resolve(object sender, ResolveEventArgs args)
	{
		var started = Stopwatch.GetTimestamp();
		string requested = args?.Name;
		try
		{
			var name = new AssemblyName(args.Name).Name;
			foreach (var loaded in AppDomain.CurrentDomain.GetAssemblies())
			{
				if (loaded.GetName().Name == name)
					return loaded;
			}
			var index = _index;
			if (index == null)
			{
				lock (Gate)
				{
					index = _index ??= BuildIndex();
				}
			}
			if (!index.TryGetValue(name, out var paths))
				return null;
			foreach (var path in paths)
			{
				try
				{
					return Assembly.LoadFrom(path);
				}
				catch
				{
					// Same as BepInEx: an unloadable candidate is skipped and the next one is tried.
				}
			}
			return null;
		}
		catch
		{
			return null;
		}
		finally
		{
			var elapsed = Stopwatch.GetTimestamp() - started;
			Interlocked.Add(ref _ticks, elapsed);
			var elapsedMs = elapsed * 1000 / Stopwatch.Frequency;
			if (elapsedMs >= SlowResolveMs)
				Crumb("resolve.slow", "ms=" + elapsedMs + " name=" + requested);
			var count = Interlocked.Increment(ref _requests);
			if (count == 150 && Interlocked.Exchange(ref _summaryLogged, 1) == 0)
				_log?.LogInfo("First 150 resolve requests took " + (Interlocked.Read(ref _ticks) * 1000 / Stopwatch.Frequency) + " ms in total.");
		}
	}

	private static Dictionary<string, List<string>> BuildIndex()
	{
		Crumb("index.begin");
		var watch = Stopwatch.StartNew();
		var index = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
		var files = 0;
		// Same roots and precedence as BepInEx: core, then patchers, then plugins; .dll before .exe per folder walk
		// is approximated by listing every .dll of a root before its .exe files.
		foreach (var root in new[] { Paths.BepInExAssemblyDirectory, Paths.PatcherPluginPath, Paths.PluginPath })
		{
			foreach (var pattern in new[] { "*.dll", "*.exe" })
			{
				try
				{
					if (string.IsNullOrEmpty(root) || !Directory.Exists(root))
						continue;
					foreach (var file in Directory.EnumerateFiles(root, pattern, SearchOption.AllDirectories))
					{
						var key = Path.GetFileNameWithoutExtension(file);
						if (!index.TryGetValue(key, out var list))
							index[key] = list = new List<string>(1);
						list.Add(file);
						files++;
					}
				}
				catch
				{
					// A folder that cannot be listed contributes nothing, as in BepInEx's own search.
				}
			}
		}
		_log?.LogInfo("Indexed " + files + " assembly files in " + watch.ElapsedMilliseconds + " ms.");
		Crumb("index.end");
		return index;
	}
}
