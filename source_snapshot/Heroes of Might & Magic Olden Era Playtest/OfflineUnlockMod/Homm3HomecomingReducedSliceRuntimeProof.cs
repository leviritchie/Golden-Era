using System;
using System.Collections.Generic;
using System.IO;
using BepInEx;
using BepInEx.Logging;
using Newtonsoft.Json.Linq;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic-only runtime proof that the validated Homecoming reduced-slice IR can be
/// loaded from deployed plugin assets and represented as layer-qualified runtime data.
/// This does not emit or mutate a native Olden map.
/// </summary>
internal static class Homm3HomecomingReducedSliceRuntimeProof
{
	internal const string DiagnosticFlag = "homm3_homecoming_reduced_slice_runtime_proof.flag";
	internal const string RuntimeAssetRelativePath = "homm3_runtime_assets/campaign_port/homecoming_reduced_slice_ir.json";
	private const string LogPrefix = "HOMM3_HOMECOMING_REDUCED_SLICE_PROOF";
	private const string ExpectedEventMessage = "Having defeated the Troglodytes, your men free the Guardhouse.  Within, the occupying Pikemen are eager to fight at your side.";
	private static readonly HashSet<string> RequiredEmittedKeys = new HashSet<string>(StringComparer.Ordinal)
	{
		"0:49:3",
		"0:14:41",
		"0:58:67",
		"0:21:62",
		"0:18:35",
		"1:14:41",
		"1:35:35",
		"1:49:3",
	};
	private static readonly HashSet<string> RequiredCaveEdges = new HashSet<string>(StringComparer.Ordinal)
	{
		"0:14:41<->1:14:41",
		"0:49:3<->1:49:3",
	};
	private static readonly HashSet<string> RequiredUnresolvedWhirlpools = new HashSet<string>(StringComparer.Ordinal)
	{
		"0:58:67",
		"0:21:62",
	};
	private static readonly Dictionary<string, ExpectedRecord> RequiredRecords = new Dictionary<string, ExpectedRecord>(StringComparer.Ordinal)
	{
		["0:49:3"] = new ExpectedRecord(591, 0, 49, 3, "0x1a247", 103, "AvTCave.def", "travel_link_candidate", "emit_stub", "layer_travel", "layer_aware_travel_graph", "blocked_for_faithful_map"),
		["0:14:41"] = new ExpectedRecord(596, 0, 14, 41, "0x1a283", 103, "AvTCave.def", "travel_link_candidate", "emit_stub", "layer_travel", "layer_aware_travel_graph", "blocked_for_faithful_map"),
		["0:58:67"] = new ExpectedRecord(1434, 0, 58, 67, "0x1cfc9", 111, "AVXwhrl0.def", "travel_link_candidate", "emit_stub", "layer_travel", "layer_aware_travel_graph", "blocked_for_faithful_map"),
		["0:21:62"] = new ExpectedRecord(1435, 0, 21, 62, "0x1cfd5", 111, "AVXwhrl0.def", "travel_link_candidate", "emit_stub", "layer_travel", "layer_aware_travel_graph", "blocked_for_faithful_map"),
		["0:18:35"] = new ExpectedRecord(1451, 0, 18, 35, "0x1d0ae", 26, "AVZevnt0.def", "map_event", "emit_stub", "event_trigger", "layer_aware_event_tile_trigger", "text_players_mask_computer_activation_and_remove_after_visit_portable_if_event_tile_object_or_custom_trigger_exists"),
		["1:14:41"] = new ExpectedRecord(1453, 1, 14, 41, "0x1d197", 103, "AvTCave.def", "travel_link_candidate", "emit_stub", "layer_travel", "layer_aware_travel_graph", "blocked_for_faithful_map"),
		["1:35:35"] = new ExpectedRecord(1454, 1, 35, 35, "0x1d1a3", 98, "AVCdung0.def", "town", "emit_stub", "primary_objective", "layer_aware_entity_emitter_and_capture_trigger", "portable_to_ObjectCaptureEntity_if_entity_is_emitted"),
		["1:49:3"] = new ExpectedRecord(1466, 1, 49, 3, "0x1d356", 103, "AvTCave.def", "travel_link_candidate", "emit_stub", "layer_travel", "layer_aware_travel_graph", "blocked_for_faithful_map"),
	};
	private static bool _ran;

	internal static void TryRun(ManualLogSource log)
	{
		if (_ran)
			return;
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;
		_ran = true;

		try
		{
			var assetPath = ResolveRuntimeAssetPath();
			var report = ReducedSliceProof.Run(assetPath);
			log?.LogInfo(LogPrefix + " result=" + (report.Passed ? "PASS" : "FAIL")
				+ " asset='" + assetPath + "'"
				+ " emittedRecords=" + report.EmittedRecords
				+ " entities=" + report.Entities
				+ " events=" + report.Events
				+ " travelEdges=" + report.TravelEdges
				+ " unresolvedWhirlpools=" + report.UnresolvedWhirlpools
				+ " terraneusKey=" + report.TerraneusKey
				+ " guardhouseEventKey=" + report.GuardhouseEventKey
				+ " nativeMapMutation=false"
				+ " playable=false"
				+ " blocker=missing_layer_aware_olden_map_emission");
			log?.LogInfo(LogPrefix + " emittedKeys=" + report.EmittedKeys);
			log?.LogInfo(LogPrefix + " caveEdges=" + report.CaveEdges);
			if (!report.Passed)
				log?.LogWarning(LogPrefix + " failures=" + report.Failures);
		}
		catch (Exception ex)
		{
			log?.LogWarning(LogPrefix + " failed closed during reduced-slice proof: " + ex);
		}
	}

	private static string ResolveRuntimeAssetPath()
	{
		var path = Path.GetFullPath(Path.Combine(Paths.PluginPath, "OfflineUnlockMod", RuntimeAssetRelativePath));
		if (!File.Exists(path))
			throw new FileNotFoundException("Homecoming reduced-slice runtime asset is missing", path);
		return path;
	}

	private static class ReducedSliceProof
	{
		internal static ProofReport Run(string assetPath)
		{
			var root = JObject.Parse(File.ReadAllText(assetPath));
			var failures = new List<string>();
			Require((string)root["schema"] == "homm3.homecoming_reduced_slice.v0", "schema", failures);
			Require((string)root["notPlayableReason"] == "missing_layer_aware_olden_map_runtime", "not-playable-reason", failures);

			var emitted = RequireArray(root, "emittedRecords", failures);
			var entities = RequireArray(root, "entities", failures);
			var events = RequireArray(root, "events", failures);
			var travelGraph = ParseObjectToken(root["travelGraph"]);
			Require(travelGraph != null, "travel-graph-object", failures);
			var edges = travelGraph != null ? RequireArray(travelGraph, "edges", failures) : new JArray();
			var unresolved = travelGraph != null ? RequireArray(travelGraph, "unresolvedCandidates", failures) : new JArray();

			var emittedKeys = CollectSourceKeys(emitted);
			Require(SetEquals(emittedKeys, RequiredEmittedKeys), "emitted-key-set", failures);
			Require(emitted.Count == 8, "emitted-count", failures);
			ValidateEmittedRecords(emitted, failures);
			Require(entities.Count == 1, "entity-count", failures);
			Require(events.Count == 1, "event-count", failures);
			Require(edges.Count == 2, "cave-edge-count", failures);
			Require(unresolved.Count == 2, "unresolved-whirlpool-count", failures);

			var terraneus = entities.Count > 0 ? ParseObjectToken(entities[0]) : null;
			Require(terraneus != null, "terraneus-object", failures);
			Require((string)terraneus?["sourceKey"] == "1:35:35", "terraneus-key", failures);
			ValidateExpectedRecord(terraneus, "entity", failures);
			Require((string)terraneus?["name"] == "Terraneus", "terraneus-name", failures);
			Require((string)terraneus?["triggerRole"] == "primary_victory_capture_target", "terraneus-trigger-role", failures);

			var guardhouse = events.Count > 0 ? ParseObjectToken(events[0]) : null;
			Require(guardhouse != null, "guardhouse-object", failures);
			Require((string)guardhouse?["sourceKey"] == "0:18:35", "guardhouse-key", failures);
			ValidateExpectedRecord(guardhouse, "event", failures);
			Require((string)guardhouse?["message"] == ExpectedEventMessage, "guardhouse-message", failures);
			ValidateGuardhouseFields(guardhouse, failures);

			var caveEdges = CollectCaveEdges(edges, failures);
			Require(SetEquals(caveEdges, RequiredCaveEdges), "cave-edge-set", failures);
			var unresolvedWhirlpools = CollectUnresolvedWhirlpools(unresolved, failures);
			Require(SetEquals(unresolvedWhirlpools, RequiredUnresolvedWhirlpools), "unresolved-whirlpool-set", failures);
			Require(NoPayloadlessEmitted(emitted), "no-payloadless-emitted", failures);

			return new ProofReport(
				failures.Count == 0,
				emitted.Count,
				entities.Count,
				events.Count,
				edges.Count,
				unresolvedWhirlpools.Count,
				(string)terraneus?["sourceKey"] ?? "<missing>",
				(string)guardhouse?["sourceKey"] ?? "<missing>",
				FormatSet(emittedKeys),
				FormatSet(caveEdges),
				FormatFailures(failures));
		}

		private static JArray RequireArray(JToken parent, string name, List<string> failures)
		{
			var array = ParseArrayToken(parent?[name]);
			if (array == null)
			{
				failures.Add(name + "-array");
				return new JArray();
			}
			return array;
		}

		private static JObject ParseObjectToken(JToken token)
		{
			if (token == null || token.Type == JTokenType.Null)
				return null;
			return token as JObject ?? JObject.Parse(token.ToString());
		}

		private static JArray ParseArrayToken(JToken token)
		{
			if (token == null || token.Type == JTokenType.Null)
				return null;
			return token as JArray ?? JArray.Parse(token.ToString());
		}

		private static void ValidateEmittedRecords(JArray records, List<string> failures)
		{
			for (var i = 0; i < records.Count; i++)
				ValidateExpectedRecord(ParseObjectToken(records[i]), "emitted", failures);
		}

		private static void ValidateExpectedRecord(JObject record, string label, List<string> failures)
		{
			var key = (string)record?["sourceKey"];
			ExpectedRecord expected = null;
			Require(!string.IsNullOrEmpty(key) && RequiredRecords.TryGetValue(key, out expected), label + "-known-key", failures);
			if (expected == null)
				return;

			Require(ReadInt(record, "sourceIndex") == expected.SourceIndex, label + "-" + key + "-source-index", failures);
			Require(ReadPositionLayer(record) == expected.Layer, label + "-" + key + "-layer", failures);
			Require(ReadPositionInt(record, "x") == expected.X, label + "-" + key + "-x", failures);
			Require(ReadPositionInt(record, "y") == expected.Y, label + "-" + key + "-y", failures);
			Require((string)record?["recordOffset"] == expected.RecordOffset, label + "-" + key + "-record-offset", failures);
			Require(ReadInt(record, "templateObjectId") == expected.TemplateObjectId, label + "-" + key + "-template-object-id", failures);
			Require((string)record?["templateAnimation"] == expected.TemplateAnimation, label + "-" + key + "-template-animation", failures);
			Require((string)record?["sourceCategory"] == expected.SourceCategory, label + "-" + key + "-source-category", failures);
			Require((string)record?["policyAction"] == expected.PolicyAction, label + "-" + key + "-policy-action", failures);
			Require((string)record?["policyScope"] == expected.PolicyScope, label + "-" + key + "-policy-scope", failures);
			Require((string)record?["runtimeRequirement"] == expected.RuntimeRequirement, label + "-" + key + "-runtime-requirement", failures);
			Require((string)record?["triggerPort"] == expected.TriggerPort, label + "-" + key + "-trigger-port", failures);
		}

		private static void ValidateGuardhouseFields(JObject guardhouse, List<string> failures)
		{
			var fields = ParseObjectToken(guardhouse?["triggerFields"]);
			Require(fields != null, "guardhouse-trigger-fields", failures);
			Require(ReadInt(fields, "playersMask") == 255, "guardhouse-players-mask", failures);
			Require(ReadBool(fields, "computerActivate") == true, "guardhouse-computer-activate", failures);
			Require(ReadBool(fields, "removeAfterVisit") == true, "guardhouse-remove-after-visit", failures);
			Require(ReadBool(fields, "hasMessage") == true, "guardhouse-has-message", failures);
			Require(ReadBool(fields, "hasGuards") == false, "guardhouse-no-guards", failures);
			var rewards = ParseObjectToken(fields?["rewardCounts"]);
			Require(rewards != null, "guardhouse-reward-counts", failures);
			Require(ReadInt(rewards, "skills") == 0, "guardhouse-reward-skills", failures);
			Require(ReadInt(rewards, "artifacts") == 0, "guardhouse-reward-artifacts", failures);
			Require(ReadInt(rewards, "spells") == 0, "guardhouse-reward-spells", failures);
			Require(ReadInt(rewards, "creatures") == 0, "guardhouse-reward-creatures", failures);
		}

		private static HashSet<string> CollectSourceKeys(JArray records)
		{
			var keys = new HashSet<string>(StringComparer.Ordinal);
			for (var i = 0; i < records.Count; i++)
			{
				var key = (string)records[i]?["sourceKey"];
				if (!string.IsNullOrEmpty(key))
					keys.Add(key);
			}
			return keys;
		}

		private static HashSet<string> CollectCaveEdges(JArray edges, List<string> failures)
		{
			var values = new HashSet<string>(StringComparer.Ordinal);
			for (var i = 0; i < edges.Count; i++)
			{
				var edge = ParseObjectToken(edges[i]);
				Require((string)edge?["kind"] == "subterranean_gate_pair_by_exact_xy", "cave-edge-kind", failures);
				Require(ReadBool(edge, "bidirectional") == true, "cave-edge-bidirectional", failures);
				var from = (string)edge?["from"];
				var to = (string)edge?["to"];
				if (!string.IsNullOrEmpty(from) && !string.IsNullOrEmpty(to))
					values.Add(from + "<->" + to);
			}
			return values;
		}

		private static HashSet<string> CollectUnresolvedWhirlpools(JArray unresolved, List<string> failures)
		{
			var values = new HashSet<string>(StringComparer.Ordinal);
			for (var i = 0; i < unresolved.Count; i++)
			{
				var item = ParseObjectToken(unresolved[i]);
				Require((string)item?["kind"] == "unpaired_whirlpool_candidate", "unresolved-kind", failures);
				var key = (string)item?["sourceKey"];
				if (!string.IsNullOrEmpty(key))
					values.Add(key);
			}
			return values;
		}

		private static bool NoPayloadlessEmitted(JArray emitted)
		{
			for (var i = 0; i < emitted.Count; i++)
			{
				if ((string)emitted[i]?["sourceCategory"] == "payloadless_object_unclassified_for_current_scope")
					return false;
			}
			return true;
		}

		private static int ReadPositionLayer(JObject obj)
		{
			return ReadPositionInt(obj, "layer");
		}

		private static int ReadPositionInt(JObject obj, string name)
		{
			var position = ParseObjectToken(obj?["position"]);
			return ReadInt(position, name);
		}

		private static int ReadInt(JObject obj, string name)
		{
			var token = obj?[name];
			return token != null && token.Type == JTokenType.Integer ? (int)token : int.MinValue;
		}

		private static bool? ReadBool(JObject obj, string name)
		{
			var token = obj?[name];
			return token != null && token.Type == JTokenType.Boolean ? (bool)token : (bool?)null;
		}

		private static void Require(bool condition, string label, List<string> failures)
		{
			if (!condition)
				failures.Add(label);
		}

		private static bool SetEquals(HashSet<string> actual, HashSet<string> expected)
		{
			return actual.Count == expected.Count && actual.SetEquals(expected);
		}

		private static string FormatSet(HashSet<string> values)
		{
			var list = new List<string>(values);
			list.Sort(StringComparer.Ordinal);
			return string.Join(",", list.ToArray());
		}

		private static string FormatFailures(List<string> failures)
		{
			return failures.Count == 0 ? "<none>" : string.Join(",", failures.ToArray());
		}
	}

	private sealed class ExpectedRecord
	{
		internal ExpectedRecord(int sourceIndex, int layer, int x, int y, string recordOffset, int templateObjectId, string templateAnimation, string sourceCategory, string policyAction, string policyScope, string runtimeRequirement, string triggerPort)
		{
			SourceIndex = sourceIndex;
			Layer = layer;
			X = x;
			Y = y;
			RecordOffset = recordOffset;
			TemplateObjectId = templateObjectId;
			TemplateAnimation = templateAnimation;
			SourceCategory = sourceCategory;
			PolicyAction = policyAction;
			PolicyScope = policyScope;
			RuntimeRequirement = runtimeRequirement;
			TriggerPort = triggerPort;
		}

		internal int SourceIndex { get; }
		internal int Layer { get; }
		internal int X { get; }
		internal int Y { get; }
		internal string RecordOffset { get; }
		internal int TemplateObjectId { get; }
		internal string TemplateAnimation { get; }
		internal string SourceCategory { get; }
		internal string PolicyAction { get; }
		internal string PolicyScope { get; }
		internal string RuntimeRequirement { get; }
		internal string TriggerPort { get; }
	}

	private sealed class ProofReport
	{
		internal ProofReport(bool passed, int emittedRecords, int entities, int events, int travelEdges, int unresolvedWhirlpools, string terraneusKey, string guardhouseEventKey, string emittedKeys, string caveEdges, string failures)
		{
			Passed = passed;
			EmittedRecords = emittedRecords;
			Entities = entities;
			Events = events;
			TravelEdges = travelEdges;
			UnresolvedWhirlpools = unresolvedWhirlpools;
			TerraneusKey = terraneusKey;
			GuardhouseEventKey = guardhouseEventKey;
			EmittedKeys = emittedKeys;
			CaveEdges = caveEdges;
			Failures = failures;
		}

		internal bool Passed { get; }
		internal int EmittedRecords { get; }
		internal int Entities { get; }
		internal int Events { get; }
		internal int TravelEdges { get; }
		internal int UnresolvedWhirlpools { get; }
		internal string TerraneusKey { get; }
		internal string GuardhouseEventKey { get; }
		internal string EmittedKeys { get; }
		internal string CaveEdges { get; }
		internal string Failures { get; }
	}
}
