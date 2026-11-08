using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text;
using System.Threading;
using HarmonyLib;
using Hex.Configs;
using Hex.Videoplayer;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class VideoInputsProbe25672315
{
	// Volatile diagnostic only: observe the first input; never repair or suppress playback.
	private const string OutputPath = @"V:\olden_port_work\port_runtime_25672315\run8_video_inputs.json";
	private const string LookupOutputPath = @"V:\olden_port_work\port_runtime_25672315\run8_video_lookups.json";
	private const int MaxClipRows = 8;
	private const int MaxNameLength = 512;
	private const int MaxLookupRows = 16;
	private const int MaxLookupTextLength = 512;
	private static readonly object LookupLock = new object();
	private static readonly List<JObject> LookupRows = new List<JObject>(MaxLookupRows);
	private static int _armed;
	private static int _recorded;
	private static int _writeStarted;
	private static int _lookupWriteStarted;
	private static long _lookupCallCount;
	private static bool _lookupRowsTruncated;
	private static string _lookupDiagnosticError;

	public static string Run()
	{
		if (Interlocked.Exchange(ref _armed, 1) != 0)
			return "diagnostic already armed";

		Harmony harmony = null;
		try
		{
			var target = ResolveLoadTarget();
			var lookupTarget = ResolveClipInfoLookupTarget();
			var prefix = typeof(VideoInputsProbe25672315).GetMethod(nameof(Prefix), BindingFlags.NonPublic | BindingFlags.Static);
			if (prefix == null)
				throw new MissingMethodException(typeof(VideoInputsProbe25672315).FullName, nameof(Prefix));
			var lookupPostfix = typeof(VideoInputsProbe25672315).GetMethod(nameof(LookupPostfix), BindingFlags.NonPublic | BindingFlags.Static);
			if (lookupPostfix == null)
				throw new MissingMethodException(typeof(VideoInputsProbe25672315).FullName, nameof(LookupPostfix));

			harmony = new Harmony("codex.port.video-inputs.25672315");
			harmony.Patch(lookupTarget, postfix: new HarmonyMethod(lookupPostfix));
			harmony.Patch(target, prefix: new HarmonyMethod(prefix));
			return "armed exact Load input and unique declared ClipInfoConfig lookup observers";
		}
		catch (Exception error)
		{
			var record = CreateRecord();
			record["diagnosticError"] = FormatException(error);
			if (harmony != null)
			{
				try
				{
					harmony.UnpatchSelf();
					record["partialArmRemoved"] = true;
				}
				catch (Exception cleanupError)
				{
					record["partialArmCleanupError"] = FormatException(cleanupError);
				}
			}
			WriteOnce(record);
			return "diagnosticError=" + error.GetType().FullName + ": " + error.Message;
		}
	}

	private static MethodInfo ResolveLoadTarget()
	{
		var clipArrayType = typeof(Il2CppReferenceArray<ClipInfo>);
		var target = AccessTools.Method(typeof(BhSubtitlesPlayer), "Load", new[] { clipArrayType });
		if (target == null)
			throw new MissingMethodException(typeof(BhSubtitlesPlayer).FullName, "Load(Il2CppReferenceArray<ClipInfo>)");

		var parameters = target.GetParameters();
		if (target.DeclaringType != typeof(BhSubtitlesPlayer) || target.ReturnType != typeof(void) || parameters.Length != 1 || parameters[0].ParameterType != clipArrayType)
			throw new InvalidOperationException("Resolved Load method does not have the pinned declared one-argument ClipInfo array signature.");
		return target;
	}

	private static MethodInfo ResolveClipInfoLookupTarget()
	{
		MethodInfo match = null;
		var matches = 0;
		var methods = typeof(ClipInfoConfig).GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly);
		foreach (var method in methods)
		{
			if (method.IsStatic || method.ContainsGenericParameters || method.ReturnType != typeof(ClipInfo))
				continue;

			var parameters = method.GetParameters();
			if (parameters.Length != 1 || parameters[0].ParameterType != typeof(string) || parameters[0].IsOut || parameters[0].ParameterType.IsByRef)
				continue;

			match = method;
			matches++;
		}

		if (matches != 1)
			throw new InvalidOperationException("Expected one declared public instance ClipInfoConfig method (ClipInfo return, one System.String argument); found " + matches + ".");
		return match;
	}

	private static void Prefix(BhSubtitlesPlayer __instance, Il2CppReferenceArray<ClipInfo> __0)
	{
		if (Interlocked.Exchange(ref _recorded, 1) != 0)
			return;

		JObject record = null;
		try
		{
			record = CreateRecord();
			try
			{
				CaptureClipsFirst(record, __0);
				record["frame"] = Time.frameCount;
				record["scene"] = SceneManager.GetActiveScene().name ?? string.Empty;
				record["instanceNull"] = __instance == null;
				if (__instance != null)
					record["gameObjectNull"] = __instance.gameObject == null;
			}
			catch (Exception error)
			{
				record["diagnosticError"] = FormatException(error);
			}

			// Persist the original input record before any separate lookup snapshot work.
			WriteOnce(record);
		}
		catch (Exception error)
		{
			try
			{
				if (record == null)
					record = CreateRecord();
				record["diagnosticError"] = FormatException(error);
				WriteOnce(record);
			}
			catch (Exception reportError)
			{
				LogDiagnosticError("Load input diagnosticError", reportError);
			}
		}

		try
		{
			FlushLookupRecord("first_Load_invocation");
		}
		catch (Exception error)
		{
			try
			{
				SetLookupDiagnosticError(FormatException(error));
			}
			catch (Exception reportError)
			{
				LogDiagnosticError("lookup snapshot diagnosticError", reportError);
			}
			LogDiagnosticError("lookup snapshot diagnosticError", error);
		}

		// A void Harmony prefix always lets the original Load method continue.
	}

	private static void LookupPostfix(string __0, ClipInfo __result)
	{
		try
		{
			if (LookupRecordAlreadyFlushed())
				return;

			var isNull = __result == null;
			var key = BoundText(__0, MaxLookupTextLength, out var keyTruncated);
			var row = new JObject
			{
				["key"] = key,
				["keyTruncated"] = keyTruncated,
				["resultNull"] = isNull,
				["name"] = JValue.CreateNull()
			};
			if (!isNull)
			{
				try
				{
					var name = BoundText(__result.name, MaxLookupTextLength, out var nameTruncated);
					row["name"] = name;
					row["nameTruncated"] = nameTruncated;
				}
				catch (Exception error)
				{
					var detail = FormatException(error);
					row["diagnosticError"] = detail;
					SetLookupDiagnosticError(detail);
				}
			}

			AddLookupRow(row, isNull);
		}
		catch (Exception error)
		{
			SetLookupDiagnosticError(FormatException(error));
		}
	}

	private static string BoundText(string value, int maxLength, out bool truncated)
	{
		truncated = value != null && value.Length > maxLength;
		return value == null || !truncated ? value : value.Substring(0, maxLength);
	}

	private static void AddLookupRow(JObject row, bool resultNull)
	{
		JObject flushRecord = null;
		lock (LookupLock)
		{
			if (_lookupWriteStarted != 0)
				return;

			_lookupCallCount++;
			if (resultNull)
			{
				if (LookupRows.Count == MaxLookupRows)
				{
					LookupRows.RemoveAt(MaxLookupRows - 1);
					_lookupRowsTruncated = true;
				}
				LookupRows.Add(row);
				_lookupWriteStarted = 1;
				flushRecord = CreateLookupRecordLocked("first_null_lookup");
			}
			else if (LookupRows.Count < MaxLookupRows - 1)
			{
				LookupRows.Add(row);
			}
			else
			{
				_lookupRowsTruncated = true;
			}
		}

		if (flushRecord != null)
			WriteLookupRecord(flushRecord);
	}

	private static void SetLookupDiagnosticError(string error)
	{
		lock (LookupLock)
		{
			if (string.IsNullOrEmpty(_lookupDiagnosticError))
				_lookupDiagnosticError = error;
		}
	}

	private static bool LookupRecordAlreadyFlushed()
	{
		lock (LookupLock)
			return _lookupWriteStarted != 0;
	}

	private static void FlushLookupRecord(string trigger)
	{
		JObject record;
		lock (LookupLock)
		{
			if (_lookupWriteStarted != 0)
				return;

			_lookupWriteStarted = 1;
			record = CreateLookupRecordLocked(trigger);
		}
		WriteLookupRecord(record);
	}

	private static JObject CreateLookupRecordLocked(string trigger)
	{
		var rows = new JArray();
		foreach (var row in LookupRows)
			rows.Add(row.DeepClone());

		var record = new JObject
		{
			["schemaVersion"] = "port.video-lookups.v1",
			["capturedAtUtc"] = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture),
			["diagnosticOnly"] = true,
			["playbackMutated"] = false,
			["flushTrigger"] = trigger,
			["lookupCallCount"] = _lookupCallCount,
			["lookupRowsTruncated"] = _lookupRowsTruncated,
			["lookupRows"] = rows
		};
		if (!string.IsNullOrEmpty(_lookupDiagnosticError))
			record["diagnosticError"] = _lookupDiagnosticError;
		return record;
	}

	private static void WriteLookupRecord(JObject record)
	{
		try
		{
			var directory = System.IO.Path.GetDirectoryName(LookupOutputPath);
			if (string.IsNullOrEmpty(directory) || !System.IO.Directory.Exists(directory))
				throw new System.IO.DirectoryNotFoundException("Run8 lookup diagnostic output directory does not exist: " + directory);
			System.IO.File.WriteAllText(LookupOutputPath, record.ToString(Formatting.None), new UTF8Encoding(false));
		}
		catch (Exception error)
		{
			try
			{
				Debug.LogError("VideoInputsProbe25672315 lookup diagnosticError while writing its single output: " + FormatException(error));
			}
			catch
			{
				// A failed diagnostic must not escape Harmony or alter the original return value.
			}
		}
	}

	private static void LogDiagnosticError(string context, Exception error)
	{
		try
		{
			Debug.LogError("VideoInputsProbe25672315 " + context + ": " + FormatException(error));
		}
		catch
		{
			// Diagnostic reporting must not escape a Harmony observer.
		}
	}

	private static void CaptureClipsFirst(JObject record, Il2CppReferenceArray<ClipInfo> clips)
	{
		record["clipsArrayNull"] = clips == null;
		if (clips == null)
			return;

		var length = clips.Length;
		var rowCount = Math.Min(length, MaxClipRows);
		record["clipsLength"] = length;
		record["clipRowsTruncated"] = length > rowCount;
		var rows = new JArray();
		record["clips"] = rows;

		for (var index = 0; index < rowCount; index++)
		{
			var row = new JObject { ["index"] = index, ["isNull"] = JValue.CreateNull() };
			rows.Add(row);
			var clip = clips[index];
			row["isNull"] = clip == null;
			if (clip == null)
			{
				row["name"] = JValue.CreateNull();
				row["canSkip"] = JValue.CreateNull();
				row["haveSubtitles"] = JValue.CreateNull();
				row["skipByHoldingEsc"] = JValue.CreateNull();
				row["playVideoShowAnimation"] = JValue.CreateNull();
				continue;
			}

			var name = clip.name;
			row["name"] = name == null ? JValue.CreateNull() : new JValue(name.Length <= MaxNameLength ? name : name.Substring(0, MaxNameLength));
			row["nameTruncated"] = name != null && name.Length > MaxNameLength;
			row["canSkip"] = clip.canSkip;
			row["haveSubtitles"] = clip.haveSubtitles;
			row["skipByHoldingEsc"] = clip.skipByHoldingEsc;
			row["playVideoShowAnimation"] = clip.playVideoShowAnimation;
		}
	}

	private static JObject CreateRecord()
	{
		return new JObject
		{
			["schemaVersion"] = "port.video-inputs.v1",
			["capturedAtUtc"] = DateTime.UtcNow.ToString("o"),
			["diagnosticOnly"] = true,
			["playbackMutated"] = false
		};
	}

	private static string FormatException(Exception error)
	{
		var text = error.ToString();
		return text.Length <= 4096 ? text : text.Substring(0, 4096);
	}

	private static void WriteOnce(JObject record)
	{
		if (Interlocked.Exchange(ref _writeStarted, 1) != 0)
			return;

		try
		{
			var directory = System.IO.Path.GetDirectoryName(OutputPath);
			if (string.IsNullOrEmpty(directory) || !System.IO.Directory.Exists(directory))
				throw new System.IO.DirectoryNotFoundException("Run8 diagnostic output directory does not exist: " + directory);
			System.IO.File.WriteAllText(OutputPath, record.ToString(Formatting.None), new UTF8Encoding(false));
		}
		catch (Exception error)
		{
			try
			{
				Debug.LogError("VideoInputsProbe25672315 diagnosticError while writing its single output: " + FormatException(error));
			}
			catch
			{
				// A failed diagnostic must not escape this prefix or suppress original playback.
			}
		}
	}
}
