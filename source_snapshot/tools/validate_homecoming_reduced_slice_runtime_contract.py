#!/usr/bin/env python3
"""Validate the Homecoming reduced-slice runtime proof contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

EXPECTED_EVENT_MESSAGE = "Having defeated the Troglodytes, your men free the Guardhouse.  Within, the occupying Pikemen are eager to fight at your side."
EXPECTED_RECORDS = {
    "0:49:3": {
        "sourceIndex": 591,
        "position": {"layer": 0, "x": 49, "y": 3},
        "recordOffset": "0x1a247",
        "templateObjectId": 103,
        "templateAnimation": "AvTCave.def",
        "sourceCategory": "travel_link_candidate",
        "policyAction": "emit_stub",
        "policyScope": "layer_travel",
        "runtimeRequirement": "layer_aware_travel_graph",
        "triggerPort": "blocked_for_faithful_map",
    },
    "0:14:41": {
        "sourceIndex": 596,
        "position": {"layer": 0, "x": 14, "y": 41},
        "recordOffset": "0x1a283",
        "templateObjectId": 103,
        "templateAnimation": "AvTCave.def",
        "sourceCategory": "travel_link_candidate",
        "policyAction": "emit_stub",
        "policyScope": "layer_travel",
        "runtimeRequirement": "layer_aware_travel_graph",
        "triggerPort": "blocked_for_faithful_map",
    },
    "0:58:67": {
        "sourceIndex": 1434,
        "position": {"layer": 0, "x": 58, "y": 67},
        "recordOffset": "0x1cfc9",
        "templateObjectId": 111,
        "templateAnimation": "AVXwhrl0.def",
        "sourceCategory": "travel_link_candidate",
        "policyAction": "emit_stub",
        "policyScope": "layer_travel",
        "runtimeRequirement": "layer_aware_travel_graph",
        "triggerPort": "blocked_for_faithful_map",
    },
    "0:21:62": {
        "sourceIndex": 1435,
        "position": {"layer": 0, "x": 21, "y": 62},
        "recordOffset": "0x1cfd5",
        "templateObjectId": 111,
        "templateAnimation": "AVXwhrl0.def",
        "sourceCategory": "travel_link_candidate",
        "policyAction": "emit_stub",
        "policyScope": "layer_travel",
        "runtimeRequirement": "layer_aware_travel_graph",
        "triggerPort": "blocked_for_faithful_map",
    },
    "0:18:35": {
        "sourceIndex": 1451,
        "position": {"layer": 0, "x": 18, "y": 35},
        "recordOffset": "0x1d0ae",
        "templateObjectId": 26,
        "templateAnimation": "AVZevnt0.def",
        "sourceCategory": "map_event",
        "policyAction": "emit_stub",
        "policyScope": "event_trigger",
        "runtimeRequirement": "layer_aware_event_tile_trigger",
        "triggerPort": "text_players_mask_computer_activation_and_remove_after_visit_portable_if_event_tile_object_or_custom_trigger_exists",
    },
    "1:14:41": {
        "sourceIndex": 1453,
        "position": {"layer": 1, "x": 14, "y": 41},
        "recordOffset": "0x1d197",
        "templateObjectId": 103,
        "templateAnimation": "AvTCave.def",
        "sourceCategory": "travel_link_candidate",
        "policyAction": "emit_stub",
        "policyScope": "layer_travel",
        "runtimeRequirement": "layer_aware_travel_graph",
        "triggerPort": "blocked_for_faithful_map",
    },
    "1:35:35": {
        "sourceIndex": 1454,
        "position": {"layer": 1, "x": 35, "y": 35},
        "recordOffset": "0x1d1a3",
        "templateObjectId": 98,
        "templateAnimation": "AVCdung0.def",
        "sourceCategory": "town",
        "policyAction": "emit_stub",
        "policyScope": "primary_objective",
        "runtimeRequirement": "layer_aware_entity_emitter_and_capture_trigger",
        "triggerPort": "portable_to_ObjectCaptureEntity_if_entity_is_emitted",
    },
    "1:49:3": {
        "sourceIndex": 1466,
        "position": {"layer": 1, "x": 49, "y": 3},
        "recordOffset": "0x1d356",
        "templateObjectId": 103,
        "templateAnimation": "AvTCave.def",
        "sourceCategory": "travel_link_candidate",
        "policyAction": "emit_stub",
        "policyScope": "layer_travel",
        "runtimeRequirement": "layer_aware_travel_graph",
        "triggerPort": "blocked_for_faithful_map",
    },
}
EXPECTED_EMITTED_KEYS = set(EXPECTED_RECORDS)
EXPECTED_CAVE_EDGES = {("0:14:41", "1:14:41"), ("0:49:3", "1:49:3")}
EXPECTED_WHIRLPOOLS = {"0:58:67", "0:21:62"}


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_expected_record(record: dict, label: str, errors: list[str]) -> None:
    key = record.get("sourceKey")
    expected = EXPECTED_RECORDS.get(key)
    require(expected is not None, f"{label} unknown source key: {key}", errors)
    if expected is None:
        return
    for field in ("sourceIndex", "recordOffset", "templateObjectId", "templateAnimation", "sourceCategory", "policyAction", "policyScope", "runtimeRequirement", "triggerPort"):
        require(record.get(field) == expected[field], f"{label} {key} {field} mismatch", errors)
    position = record.get("position") or {}
    require(position == expected["position"], f"{label} {key} position mismatch", errors)


def validate_payload(path: Path, errors: list[str]) -> None:
    if not path.exists():
        errors.append(f"missing runtime payload: {path}")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    require(data.get("schema") == "homm3.homecoming_reduced_slice.v0", "payload schema mismatch", errors)
    require(data.get("notPlayableReason") == "missing_layer_aware_olden_map_runtime", "payload must remain not-playable/runtime-blocked", errors)
    policy = data.get("policy") or {}
    require(not any(":" in str(policy.get(key, "")) for key in ("artifact", "validationArtifact")), "payload policy provenance must be repo-relative, not absolute", errors)
    emitted = data.get("emittedRecords") or []
    entities = data.get("entities") or []
    events = data.get("events") or []
    graph = data.get("travelGraph") or {}
    edges = graph.get("edges") or []
    unresolved = graph.get("unresolvedCandidates") or []
    require({item.get("sourceKey") for item in emitted} == EXPECTED_EMITTED_KEYS, "payload emitted source keys mismatch", errors)
    require(len(emitted) == 8, "payload emitted count mismatch", errors)
    for item in emitted:
        validate_expected_record(item, "emitted", errors)
    require(len(entities) == 1 and entities[0].get("sourceKey") == "1:35:35" and entities[0].get("name") == "Terraneus", "Terraneus entity mismatch", errors)
    if entities:
        validate_expected_record(entities[0], "entity", errors)
        require(entities[0].get("triggerRole") == "primary_victory_capture_target", "Terraneus triggerRole mismatch", errors)
    require(len(events) == 1 and events[0].get("sourceKey") == "0:18:35", "Guardhouse event key mismatch", errors)
    if events:
        event = events[0]
        validate_expected_record(event, "event", errors)
        fields = event.get("triggerFields") or {}
        rewards = fields.get("rewardCounts") or {}
        require(event.get("message") == EXPECTED_EVENT_MESSAGE, "Guardhouse event message mismatch", errors)
        require(fields.get("playersMask") == 255, "Guardhouse playersMask mismatch", errors)
        require(fields.get("computerActivate") is True, "Guardhouse computerActivate mismatch", errors)
        require(fields.get("removeAfterVisit") is True, "Guardhouse removeAfterVisit mismatch", errors)
        require(fields.get("hasMessage") is True, "Guardhouse hasMessage mismatch", errors)
        require(fields.get("hasGuards") is False, "Guardhouse hasGuards mismatch", errors)
        require(all(rewards.get(key) == 0 for key in ("skills", "artifacts", "spells", "creatures")), "Guardhouse reward counts must be zero", errors)
    require({(edge.get("from"), edge.get("to")) for edge in edges} == EXPECTED_CAVE_EDGES, "cave edge set mismatch", errors)
    require(all(edge.get("kind") == "subterranean_gate_pair_by_exact_xy" for edge in edges), "unexpected cave edge kind", errors)
    require(all(edge.get("bidirectional") is True for edge in edges), "cave edges must be bidirectional", errors)
    require({item.get("sourceKey") for item in unresolved} == EXPECTED_WHIRLPOOLS, "unresolved whirlpool set mismatch", errors)
    require(all(item.get("kind") == "unpaired_whirlpool_candidate" for item in unresolved), "unexpected unresolved travel candidate kind", errors)
    require(not any(item.get("sourceCategory") == "payloadless_object_unclassified_for_current_scope" for item in emitted), "payloadless object emitted", errors)


def validate_source(plugin_dir: Path, errors: list[str]) -> None:
    source = (plugin_dir / "Homm3HomecomingReducedSliceRuntimeProof.cs").read_text(encoding="utf-8")
    plugin = (plugin_dir / "Plugin.cs").read_text(encoding="utf-8")
    csproj = (plugin_dir / "OfflineUnlockMod.csproj").read_text(encoding="utf-8")
    require('DiagnosticFlag = "homm3_homecoming_reduced_slice_runtime_proof.flag"' in source, "missing exact diagnostic flag", errors)
    require('RuntimeAssetRelativePath = "homm3_runtime_assets/campaign_port/homecoming_reduced_slice_ir.json"' in source, "missing exact runtime asset path", errors)
    require('Path.Combine(Paths.PluginPath, "OfflineUnlockMod", RuntimeAssetRelativePath)' in source, "runtime proof must use one exact deployed plugin asset path", errors)
    require('nativeMapMutation=false' in source and 'playable=false' in source, "runtime proof must log no native mutation and non-playable state", errors)
    require('missing_layer_aware_olden_map_emission' in source, "runtime proof must keep native-emission blocker explicit", errors)
    require('new ExpectedRecord(591, 0, 49, 3, "0x1a247"' in source, "runtime proof must pin exact emitted record identities", errors)
    require('ValidateExpectedRecord(ParseObjectToken(records[i]), "emitted", failures);' in source, "runtime proof must validate each emitted record", errors)
    require('ParseArrayToken(parent?[name])' in source and 'JArray.Parse(token.ToString())' in source, "runtime proof must normalize array tokens for IL2CPP/Newtonsoft runtime", errors)
    require('ParseObjectToken(root["travelGraph"])' in source and 'JObject.Parse(token.ToString())' in source, "runtime proof must normalize object tokens for IL2CPP/Newtonsoft runtime", errors)
    require('Homm3HomecomingReducedSliceRuntimeProof.TryRun(Log);' in plugin, "Plugin.cs must call Homecoming reduced-slice proof", errors)
    require(r'DeployHomm3RuntimeAsset Include="$(MSBuildThisFileDirectory)homm3_runtime_assets\**\*"' in csproj, "csproj must deploy homm3_runtime_assets", errors)
    require('--source-plugin-dir &quot;$(MSBuildThisFileDirectory).&quot; --plugin-dir &quot;$(PluginDeployDir).&quot;' in csproj, "csproj must validate deployed Homecoming runtime asset after deploy", errors)
    forbidden = ['Directory.GetFiles', 'SearchOption.AllDirectories', 'Paths.GameRootPath', 'File.Exists(Path.Combine(Paths.PluginPath, RuntimeAssetRelativePath)']
    for token in forbidden:
        require(token not in source, f"forbidden fallback/search token present: {token}", errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-dir", default="Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod")
    parser.add_argument("--source-plugin-dir")
    args = parser.parse_args()
    plugin_dir = Path(args.plugin_dir)
    source_plugin_dir = Path(args.source_plugin_dir) if args.source_plugin_dir else plugin_dir
    errors: list[str] = []
    validate_source(source_plugin_dir, errors)
    validate_payload(plugin_dir / "homm3_runtime_assets" / "campaign_port" / "homecoming_reduced_slice_ir.json", errors)
    if errors:
        print("Homecoming reduced-slice runtime contract validation failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    print("Homecoming reduced-slice runtime contract validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
