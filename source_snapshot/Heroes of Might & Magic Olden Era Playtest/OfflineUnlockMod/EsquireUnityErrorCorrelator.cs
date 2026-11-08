using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading;
using BepInEx;
using BepInEx.Logging;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// When enabled, subscribes to <see cref="Application.logMessageReceived"/> and appends <see cref="EsquirePikemanVisuals"/>
/// runtime state next to each Unity <see cref="LogType.Error"/> / <see cref="LogType.Exception"/> / <see cref="LogType.Assert"/> line.
/// This does <em>not</em> tell you the exact C# line inside Hex.dll — only Player.log/Unity with full stack does — but it proves
/// order-of-events relative to the last Esquire <c>ResManager</c> get and patch installation.
/// </summary>
internal static class EsquireUnityErrorCorrelator
{
	private static bool _subscribed;
	private static System.Delegate _logCallbackDelegate;
	private static MethodInfo _add;
	private static MethodInfo _rem;
	private static readonly object FileLock = new();
	private static int _lineCount;
	private const int MaxLines = 2000;

	internal static void SetEnabled(bool enabled, ManualLogSource log)
	{
		if (enabled)
		{
			if (_subscribed)
				return;
			if (!TryResolveLogHook(out _add, out _rem, log))
			{
				return;
			}
			_logCallbackDelegate = CreateCallbackDelegateFor(_add);
			if (_logCallbackDelegate == null)
			{
				log?.LogWarning("EsquirePikeman: could not build Unity log callback (Il2cpp); correlator off.");
				return;
			}
			_add.Invoke(null, new object[] { _logCallbackDelegate });
			_subscribed = true;
			_lineCount = 0;
			log?.LogInfo(
				"EsquirePikeman: Unity error correlator on — writing "
				+ Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", "esquire_unity_correlator.log")
				+ " (order-of-events; use Player.log / Unity Exception stack for the throw site).");
		}
		else
		{
			Disable();
		}
	}

	private static bool TryResolveLogHook(out MethodInfo add, out MethodInfo rem, ManualLogSource log)
	{
		add = null;
		rem = null;
		var t = typeof(Application);
		var f = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static;
		add = t.GetMethods(f).FirstOrDefault(m => m.Name == "add_logMessageReceived");
		rem = t.GetMethods(f).FirstOrDefault(m => m.Name == "remove_logMessageReceived");
		if (add == null || rem == null)
		{
			log?.LogWarning("EsquirePikeman: Application add/remove_logMessageReceived not in interop; correlator not available on this build.");
			return false;
		}
		return true;
	}

	private static System.Delegate CreateCallbackDelegateFor(MethodInfo addLog)
	{
		var ps = addLog.GetParameters();
		if (ps.Length != 1)
		{
			return null;
		}
		var delegateType = ps[0].ParameterType;
		if (!typeof(System.Delegate).IsAssignableFrom(delegateType))
		{
			return null;
		}
		var invoke = delegateType.GetMethod("Invoke", BindingFlags.Public | BindingFlags.Instance);
		if (invoke == null)
		{
			return null;
		}
		var ip = invoke.GetParameters();
		// Net / Mono: void(string, string, LogType)
		if (ip.Length == 3
		    && ip[0].ParameterType == typeof(string)
		    && ip[1].ParameterType == typeof(string)
		    && ip[2].ParameterType == typeof(LogType))
		{
			return System.Delegate.CreateDelegate(delegateType, typeof(EsquireUnityErrorCorrelator), nameof(OnUnityLog));
		}
		// Il2Cpp interop: void(Il2CppSystem.String, Il2CppSystem.String, LogType) — same managed names for CreateDelegate
		if (ip.Length == 3
		    && ip[2].ParameterType == typeof(LogType)
		    && ResManagerInteropProbe.IsResourcePathParamType(ip[0].ParameterType)
		    && ResManagerInteropProbe.IsResourcePathParamType(ip[1].ParameterType))
		{
			return System.Delegate.CreateDelegate(delegateType, typeof(EsquireUnityErrorCorrelator), nameof(OnUnityLogIl2cppStrings));
		}
		return null;
	}

	internal static void Disable()
	{
		if (!_subscribed || _rem == null || _logCallbackDelegate == null)
		{
			_subscribed = false;
			_logCallbackDelegate = null;
			return;
		}
		try
		{
			_rem.Invoke(null, new object[] { _logCallbackDelegate });
		}
		catch
		{
		}
		_logCallbackDelegate = null;
		_subscribed = false;
	}

	/// <summary>Il2Cpp <c>LogCallback</c> uses <c>Il2CppSystem.String</c> for message lines instead of managed <c>string</c>.</summary>
	internal static void OnUnityLogIl2cppStrings(Il2CppSystem.String condition, Il2CppSystem.String stackTrace, LogType type)
	{
		OnUnityLog(
			condition == null ? null : condition.ToString(),
			stackTrace == null ? null : stackTrace.ToString(),
			type);
	}

	/// <summary>Must be invokable as <c>Application.LogCallback</c> (or Il2cpp equivalent delegate).</summary>
	internal static void OnUnityLog(string condition, string stackTrace, LogType type)
	{
		if (type != LogType.Error && type != LogType.Exception && type != LogType.Assert)
			return;
		if (_lineCount >= MaxLines)
			return;
		Interlocked.Increment(ref _lineCount);

		var logPath = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", "esquire_unity_correlator.log");
		var b = new StringBuilder(512);
		b.Append("---\n");
		b.Append("utc\t").Append(DateTime.UtcNow.ToString("O")).Append('\n');
		b.Append("unityType\t").Append(type).Append('\n');
		b.Append("condition\t").Append(SanitizeForFile(condition)).Append('\n');
		b.Append("esquireState\t")
			.Append(SanitizeForFile(EsquirePikemanVisuals.GetCorrelationSnapshot()))
			.Append('\n');
		if (!string.IsNullOrEmpty(stackTrace))
		{
			b.Append("unityStack\n");
			b.Append(SanitizeForFile(stackTrace));
			if (!stackTrace.EndsWith("\n", StringComparison.Ordinal))
				b.Append('\n');
		}
		b.Append('\n');

		try
		{
			lock (FileLock)
			{
				File.AppendAllText(logPath, b.ToString(), Encoding.UTF8);
			}
		}
		catch
		{
		}
	}

	private static string SanitizeForFile(string s)
	{
		if (string.IsNullOrEmpty(s))
			return string.Empty;
		return s.Replace("\r", " ").Replace("\t", "    ");
	}
}
