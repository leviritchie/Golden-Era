using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic-only ingress mining: counters, exact patch readback, bounded
/// outcome ring, and evidence envelope. Flag-gated; never mutates combat.
/// Proof lane: ingress-shape capture only (not gameplay proof).
/// </summary>
internal static class Homm3DirectStateIngressMining
{
	internal const string FlagFileName = "homm3_direct_state_ingress_mining.flag";
	internal const int OutcomeRingCapacity = 32;

	private static readonly object Gate = new();
	private static readonly string[] OutcomeRing = new string[OutcomeRingCapacity];
	private static int _outcomeWrite;
	private static int _outcomeCount;
	private static int _accepted;
	private static int _rejected;
	private static int _failed;
	private static string _lastEnvelopePath = "none";

	internal static bool IsEnabled => Homm3DiagnosticFlags.IsEnabled(FlagFileName);

	internal static void ObserveOutcome(in Homm3DirectStateIngressOutcome outcome)
	{
		if (!IsEnabled)
			return;
		lock (Gate)
		{
			switch (outcome.Status)
			{
				case Homm3DirectStateIngressStatus.Accepted:
					_accepted++;
					break;
				case Homm3DirectStateIngressStatus.Rejected:
					_rejected++;
					break;
				default:
					_failed++;
					break;
			}
			var line = outcome.Status
			           + "|" + outcome.Surface
			           + "|" + Escape(outcome.AbilityName)
			           + "|" + Escape(outcome.Reason);
			OutcomeRing[_outcomeWrite % OutcomeRingCapacity] = line;
			_outcomeWrite++;
			if (_outcomeCount < OutcomeRingCapacity)
				_outcomeCount++;
		}
	}

	internal static string BuildEvidenceEnvelopeJson()
	{
		string[] ring;
		int accepted;
		int rejected;
		int failed;
		lock (Gate)
		{
			accepted = _accepted;
			rejected = _rejected;
			failed = _failed;
			ring = SnapshotRingLocked();
		}

		var patches = BuildDamagePatchReadbackJson();
		var sb = new StringBuilder(2048);
		sb.Append('{');
		sb.Append("\"schemaVersion\":1,");
		sb.Append("\"kind\":\"directStateIngressEvidence\",");
		sb.Append("\"proofLane\":\"ingress-shape-capture-only\",");
		sb.Append("\"gameplayProof\":\"none\",");
		sb.Append("\"miningEnabled\":").Append(IsEnabled ? "true" : "false").Append(',');
		sb.Append("\"activationStatus\":\"").Append(Escape(Homm3RuntimeMechanicHooks.ActivationStatus)).Append("\",");
		sb.Append("\"counters\":{");
		sb.Append("\"accepted\":").Append(accepted).Append(',');
		sb.Append("\"rejected\":").Append(rejected).Append(',');
		sb.Append("\"failed\":").Append(failed);
		sb.Append("},");
		sb.Append("\"outcomeRing\":[");
		for (var i = 0; i < ring.Length; i++)
		{
			if (i > 0)
				sb.Append(',');
			sb.Append('"').Append(Escape(ring[i])).Append('"');
		}
		sb.Append("],");
		sb.Append("\"damageSurfacePatches\":").Append(patches);
		sb.Append('}');
		return sb.ToString();
	}

	internal static bool TryWriteEvidenceEnvelope(out string path, out string failReason)
	{
		path = null;
		try
		{
			var json = BuildEvidenceEnvelopeJson();
			var dir = Path.Combine(
				Path.GetDirectoryName(typeof(Homm3DirectStateIngressMining).Assembly.Location) ?? ".",
				"live_probe_bridge",
				"direct_state_ingress");
			Directory.CreateDirectory(dir);
			path = Path.Combine(
				dir,
				"evidence_" + DateTime.UtcNow.ToString("yyyyMMdd_HHmmss") + ".json");
			File.WriteAllText(path, json, Encoding.UTF8);
			_lastEnvelopePath = path;
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = ex.Message;
			return false;
		}
	}

	internal static string LastEnvelopePath => _lastEnvelopePath;

	private static string[] SnapshotRingLocked()
	{
		var count = _outcomeCount;
		var result = new string[count];
		var start = _outcomeWrite - count;
		for (var i = 0; i < count; i++)
			result[i] = OutcomeRing[(start + i) % OutcomeRingCapacity] ?? "";
		return result;
	}

	private static string BuildDamagePatchReadbackJson()
	{
		try
		{
			var hooksType = typeof(Homm3RuntimeMechanicHooks);
			var damageField = hooksType.GetField("_damageTarget", BindingFlags.NonPublic | BindingFlags.Static);
			var prefixField = hooksType.GetField("_damagePrefix", BindingFlags.NonPublic | BindingFlags.Static);
			var postfixField = hooksType.GetField("_damagePostfix", BindingFlags.NonPublic | BindingFlags.Static);
			var target = damageField?.GetValue(null) as MethodBase;
			var prefix = prefixField?.GetValue(null) as MethodInfo;
			var postfix = postfixField?.GetValue(null) as MethodInfo;
			if (target == null)
			{
				return "{\"registered\":false,\"reason\":\"damage target not registered\"}";
			}
			var info = Harmony.GetPatchInfo(target);
			var ownedPrefix = false;
			var ownedPostfix = false;
			if (info != null)
			{
				foreach (var patch in info.Prefixes)
				{
					if (patch.PatchMethod == prefix)
						ownedPrefix = true;
				}
				foreach (var patch in info.Postfixes)
				{
					if (patch.PatchMethod == postfix)
						ownedPostfix = true;
				}
			}
			return "{\"registered\":true"
			       + ",\"target\":\"" + Escape(FormatMethod(target)) + "\""
			       + ",\"ownedPrefix\":" + (ownedPrefix ? "true" : "false")
			       + ",\"ownedPostfix\":" + (ownedPostfix ? "true" : "false")
			       + ",\"prefix\":\"" + Escape(FormatMethod(prefix)) + "\""
			       + ",\"postfix\":\"" + Escape(FormatMethod(postfix)) + "\""
			       + "}";
		}
		catch (Exception ex)
		{
			return "{\"registered\":false,\"reason\":\"" + Escape(ex.Message) + "\"}";
		}
	}

	private static string FormatMethod(MethodBase method)
	{
		return method == null
			? "null"
			: (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}

	private static string Escape(string value)
	{
		return (value ?? string.Empty)
			.Replace("\\", "\\\\")
			.Replace("\"", "\\\"")
			.Replace("\r", "\\r")
			.Replace("\n", "\\n");
	}
}
