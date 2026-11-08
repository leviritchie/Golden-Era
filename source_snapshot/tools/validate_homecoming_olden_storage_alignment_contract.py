#!/usr/bin/env python3
"""Validate the Homecoming Olden storage-alignment query-shape contract."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA = "homm3.homecoming_olden_storage_alignment.v0"
STATUS = "query_shape_only_not_playable"
EXPECTED_SOURCE_COUNT = 1853
EXPECTED_LAYER_COUNTS = {"0": 1453, "1": 400}
EXPECTED_TILE_COUNT = 72 * 72
EXPECTED_CHUNK_COUNT = 4
EXPECTED_TERRANEUS = "1:35:35"
EXPECTED_TERRANEUS_TEMPLATE = 98
EXPECTED_GUARDHOUSE = "0:18:35"
EXPECTED_GUARDHOUSE_MESSAGE = (
    "Having defeated the Troglodytes, your men free the Guardhouse.  Within, the occupying "
    "Pikemen are eager to fight at your side."
)
EXPECTED_ALIGNMENT_MODE = "layered_olden_chunk1_views_not_native_olden_container"
FORBIDDEN_CHUNK_WRAPPER_KEYS = {"chunk", "kind", "payload", "mapData"}
REQUIRED_MAP_SETTINGS_KEYS = {
    "isScenario",
    "gameMode",
    "endController",
    "economicDifficulties",
    "aiDifficulties",
    "neutralDifficulties",
    "quickStartDifficulties",
}
EXPECTED_LAYER_PROPERTY_SCOPE = "layerLocalObjectProperties"
EXPECTED_GLOBAL_PROPERTY_SCOPE = "globalObjectProperties"
OUTPUT_PATH = Path("artifacts") / "campaign_port_poc" / "homecoming_poc" / "olden_storage_alignment" / "homecoming.olden_storage_alignment.json"
GENERATION_CHAIN = [
    "build_homecoming_layered_ir.py",
    "walk_homecoming_objects.py",
    "build_homecoming_object_port_manifest.py",
    "build_homecoming_olden_storage_alignment.py",
]
VALIDATOR_FORBIDDEN_TOKENS = [
    'write_olden_map_container(',
    'generate_olden_map',
    'PLAYABLE_TEMPLATE_MAP',
    'queryNative',
    'nativeLayeredMapWriterUsed": True',
    'silentFallbacksUsed": True',
]


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def read_json(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"missing JSON artifact: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as ex:  # pragma: no cover
        errors.append(f"cannot read {path}: {ex}")
        return {}


def validate_builder_source(repo_root: Path, errors: list[str]) -> None:
    builder = repo_root / "experiments" / "campaign_port_poc" / "build_homecoming_olden_storage_alignment.py"
    require(builder.exists(), f"missing storage-alignment builder: {builder}", errors)
    if not builder.exists():
        return
    source = builder.read_text(encoding="utf-8")
    for token in VALIDATOR_FORBIDDEN_TOKENS:
        require(token not in source, f"storage alignment builder contains forbidden token: {token}", errors)


def run_generation(repo_root: Path, errors: list[str]) -> Path:
    script_dir = repo_root / "experiments" / "campaign_port_poc"
    out_root = repo_root / "artifacts" / "campaign_port_poc" / "validator_tmp" / "homecoming_olden_storage_alignment"
    if out_root.exists():
        shutil.rmtree(out_root)
    env = dict(os.environ)
    env["HOMECOMING_POC_OUT_ROOT"] = str(out_root)

    for script_name in GENERATION_CHAIN:
        script = script_dir / script_name
        if not script.exists():
            errors.append(f"missing homecoming generation script: {script}")
            return out_root
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(repo_root),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            errors.append(f"{script_name} failed with exit {result.returncode}:\n{result.stdout}")
            return out_root
    return out_root


def parse_source_key(source_key: str) -> tuple[int, int, int]:
    layer_s, x_s, y_s = source_key.split(":")
    return int(layer_s), int(x_s), int(y_s)


def source_key_layer(entry: dict[str, Any], errors: list[str], label: str) -> int | None:
    source_key = entry.get("sourceKey")
    if not isinstance(source_key, str):
        errors.append(f"{label} missing sourceKey")
        return None
    parts = source_key.split(":")
    if len(parts) != 3:
        errors.append(f"{label} invalid sourceKey format: {source_key!r}")
        return None
    try:
        return int(parts[0])
    except ValueError:
        errors.append(f"{label} invalid sourceKey layer: {source_key!r}")
        return None


def source_pairs(entries: list[dict[str, Any]], errors: list[str], label: str) -> set[tuple[Any, Any]]:
    pairs = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"{label}[{index}] must be object")
            continue
        pairs.add((entry.get("sourceIndex"), entry.get("sourceKey")))
    return pairs


def ensure_entity_alignment(entries: list[dict[str, Any]], errors: list[str], *, source_count: int | None = None) -> None:
    seen_indices = set()
    for entry in entries:
        source_key = entry.get("sourceKey")
        require(isinstance(source_key, str), f"entity missing sourceKey: {entry}", errors)
        require("sourceIndex" in entry, f"entity missing sourceIndex: {source_key}", errors)
        require("alignmentStatus" in entry, f"entity missing alignmentStatus: {source_key}", errors)
        source_index = entry.get("sourceIndex")
        require(source_index not in seen_indices, f"duplicate entity sourceIndex: {source_key}/{source_index}", errors)
        seen_indices.add(source_index)
    if source_count is not None:
        require(len(seen_indices) == source_count, f"entity sourceIndex count mismatch: {len(seen_indices)} != {source_count}", errors)
    layer_hist = Counter()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        layer = source_key_layer(entry, errors, f"entity[{index}]")
        if layer is not None:
            layer_hist[str(layer)] += 1
    require(dict(layer_hist) == EXPECTED_LAYER_COUNTS, f"entity source layer coverage mismatch: {dict(layer_hist)}", errors)


def ensure_counter_set(entries: list[dict[str, Any]], expected: set[str], errors: list[str], *, label: str) -> None:
    missing = expected.difference({item.get("sid") for item in entries if isinstance(item, dict)})
    require(not missing, f"{label} missing sids: {sorted(missing)}", errors)


def ensure_olden_group_rows(group_rows: list[dict[str, Any]], errors: list[str], *, expected_indices: set[Any] | None = None) -> list[int]:
    ids_seen = []
    for row in group_rows:
        require(isinstance(row, dict), "chunk1.objects row must be object", errors)
        sid = row.get("sid")
        require(isinstance(sid, str), f"chunk1.objects row missing sid: {row}", errors)
        ids = row.get("ids")
        nodes = row.get("nodes")
        rotations = row.get("rotations")
        levels = row.get("levels")
        require(isinstance(ids, list), f"chunk1.objects[{sid}] ids must be list", errors)
        require(isinstance(nodes, list), f"chunk1.objects[{sid}] nodes must be list", errors)
        require(isinstance(rotations, list), f"chunk1.objects[{sid}] rotations must be list", errors)
        require(isinstance(levels, list), f"chunk1.objects[{sid}] levels must be list", errors)
        require(len(ids) == len(nodes) == len(rotations) == len(levels), f"chunk1.objects[{sid}] ids/nodes/rotations/levels length mismatch", errors)
        for source_index in ids:
            require(isinstance(source_index, int), f"chunk1.objects[{sid}] id must be int: {source_index}", errors)
            ids_seen.append(source_index)
    if expected_indices is not None:
        require(set(ids_seen) == set(expected_indices), f"chunk1.objects index set mismatch: expected {len(expected_indices)} found {len(set(ids_seen))}", errors)
    return ids_seen



def ensure_no_chunk_wrappers(chunk: dict[str, Any], label: str, errors: list[str]) -> None:
    for key in FORBIDDEN_CHUNK_WRAPPER_KEYS:
        require(key not in chunk, f"{label} must not contain wrapper key {key!r}; expose the Olden chunk payload directly", errors)


def ensure_dialogs_quests_chunk(chunk: dict[str, Any], errors: list[str]) -> None:
    require(set(chunk.keys()).issuperset({"dialogs", "quests"}), "chunk2 must expose dialogs and quests directly", errors)
    dialogs = chunk.get("dialogs")
    quests = chunk.get("quests")
    require(isinstance(dialogs, dict), "chunk2.dialogs must be an object", errors)
    require(isinstance(quests, dict), "chunk2.quests must be an object", errors)
    if isinstance(dialogs, dict):
        require(isinstance(dialogs.get("lines", []), list), "chunk2.dialogs.lines must be a list", errors)
    if isinstance(quests, dict):
        require(isinstance(quests.get("quests", []), list), "chunk2.quests.quests must be a list", errors)


def ensure_settings(settings: Any, label: str, errors: list[str]) -> None:
    require(isinstance(settings, dict), f"{label}.settings must be an explicit object", errors)
    if not isinstance(settings, dict):
        return
    missing = REQUIRED_MAP_SETTINGS_KEYS.difference(settings.keys())
    require(not missing, f"{label}.settings missing required keys: {sorted(missing)}", errors)
    for key in ["economicDifficulties", "aiDifficulties", "neutralDifficulties", "quickStartDifficulties"]:
        require(isinstance(settings.get(key), list), f"{label}.settings.{key} must be a list", errors)


def ensure_full_map_area(map_data: dict[str, Any], label: str, errors: list[str]) -> None:
    areas = map_data.get("areas")
    require(isinstance(areas, list) and len(areas) >= 1, f"{label}.areas must contain at least one explicit area row", errors)
    if not isinstance(areas, list) or not areas:
        return
    full_area = areas[0]
    require(isinstance(full_area, dict), f"{label}.areas[0] must be an object", errors)
    if isinstance(full_area, dict):
        nodes = full_area.get("nodes")
        require(isinstance(nodes, list), f"{label}.areas[0].nodes must be a list", errors)
        require(len(nodes or []) == EXPECTED_TILE_COUNT, f"{label}.areas[0] must cover all {EXPECTED_TILE_COUNT} nodes", errors)


def ensure_property_scope(properties: Any, label: str, expected_scope: str, errors: list[str]) -> dict[str, Any]:
    require(isinstance(properties, dict), f"{label} must be an object", errors)
    if not isinstance(properties, dict):
        return {}
    alignment = properties.get("alignment") or {}
    require(isinstance(alignment, dict), f"{label}.alignment must be an object", errors)
    if isinstance(alignment, dict):
        require(alignment.get("scope") == expected_scope, f"{label}.alignment.scope must be {expected_scope}", errors)
        require(alignment.get("alignmentMode") == EXPECTED_ALIGNMENT_MODE, f"{label}.objectsProperties alignmentMode mismatch", errors)
    return properties


def validate_artifact(repo_root: Path, errors: list[str], artifact_path: Path | None = None) -> None:
    root = artifact_path if artifact_path is not None else repo_root / OUTPUT_PATH
    artifact = read_json(root, errors)
    if not artifact:
        return

    require(artifact.get("schema") == SCHEMA, f"artifact schema mismatch: {artifact.get('schema')}", errors)
    require(artifact.get("status") == STATUS, f"artifact status must be {STATUS}, found {artifact.get('status')}", errors)
    require(artifact.get("nonPlayable") is True, "artifact must mark nonPlayable=True", errors)
    require(artifact.get("runtimeNotApplicable") is True, "artifact must mark runtimeNotApplicable=True", errors)
    require(artifact.get("queryShapeOnly") is True, "artifact must be queryShapeOnly=True", errors)
    require(artifact.get("nativeLayeredMapWriterUsed") is False, "artifact must not use native layered map writer", errors)
    require(artifact.get("silentFallbacksUsed") is False, "artifact must report silentFallbacksUsed=false", errors)

    storage_format = artifact.get("storageFormat") or {}
    require(storage_format.get("reference") == "Olden story map c_M1.map", "storageFormat.reference mismatch", errors)
    require(storage_format.get("chunkModel") == ["meta", "mapData", "dialogsQuests", "storyScript"], "storageFormat.chunkModel mismatch", errors)

    source = artifact.get("source") or {}
    require(source.get("sourceObjectCount") == EXPECTED_SOURCE_COUNT, f"sourceObjectCount mismatch: {source.get('sourceObjectCount')}", errors)
    require(source.get("sourceLayerCounts") == EXPECTED_LAYER_COUNTS, f"sourceLayerCounts mismatch: {source.get('sourceLayerCounts')}", errors)

    source_manifest = Path(source.get("objectManifest", ""))
    if source_manifest.is_absolute():
        manifest_path = source_manifest
    else:
        manifest_path = repo_root / source_manifest
    object_manifest = read_json(manifest_path, errors)
    if object_manifest:
        manifest_records = object_manifest.get("records") or []
        require(len(manifest_records) == EXPECTED_SOURCE_COUNT, f"object manifest record count mismatch: {len(manifest_records)}", errors)
    else:
        manifest_records = []
    manifest_layer_indices = {
        "0": {entry.get("sourceIndex") for entry in manifest_records if isinstance(entry, dict) and str(entry.get("sourceKey", "")).startswith("0:")},
        "1": {entry.get("sourceIndex") for entry in manifest_records if isinstance(entry, dict) and str(entry.get("sourceKey", "")).startswith("1:")},
    }

    layered_ir_path = Path(source.get("layeredIr", ""))
    if layered_ir_path.is_absolute():
        layered_path = layered_ir_path
    else:
        layered_path = repo_root / layered_ir_path
    layered_ir = read_json(layered_path, errors)
    if layered_ir:
        layers = layered_ir.get("layers") or []
        require(len(layers) == 2, f"layered IR must have 2 layers, found {len(layers)}", errors)
        for layer in layers:
            require(layer.get("width") == 72 and layer.get("height") == 72, "layered IR layer must be 72x72", errors)
            require(len(layer.get("tiles", [])) == EXPECTED_TILE_COUNT, "layered IR tile count mismatch", errors)

    container = artifact.get("container") or {}
    chunks = container.get("chunks") or []
    require(isinstance(chunks, list), "container.chunks must be a list", errors)
    if not isinstance(chunks, list):
        return
    require(len(chunks) == EXPECTED_CHUNK_COUNT, f"container chunk count mismatch: {len(chunks)}", errors)

    chunk0, chunk1, chunk2, chunk3 = (chunks + [{}] * 4)[:4]
    for index, chunk in enumerate([chunk0, chunk1, chunk2, chunk3]):
        require(isinstance(chunk, dict), f"chunk{index} must be an object", errors)
        if isinstance(chunk, dict):
            ensure_no_chunk_wrappers(chunk, f"chunk{index}", errors)
    require("title" in chunk0, "chunk0 must expose Olden-like title directly", errors)
    require("mapName" not in chunk0, "chunk0 must not carry mapName; mapName belongs on chunk1 mapData", errors)
    require(chunk0.get("sizeX") == 72 and chunk0.get("sizeZ") == 72, "chunk0 must expose native-like sizeX/sizeZ metadata", errors)
    ensure_dialogs_quests_chunk(chunk2, errors)

    map_data = chunk1
    require(map_data.get("sizeX_") == 72 and map_data.get("sizeZ_") == 72, "chunk1 size must be 72x72", errors)
    for array_key in ["tilesMap", "roadsMap", "waterMap", "levelsMap", "climbsMap", "customAreasPainting"]:
        require(len(map_data.get(array_key, [])) == EXPECTED_TILE_COUNT, f"chunk1 {array_key} length mismatch", errors)

    require(map_data.get("queryMode") == "raw_h3_layer_flat_arrays", "chunk1 queryMode must be raw_h3_layer_flat_arrays", errors)
    require(map_data.get("queryShapeOnly") is True, "chunk1 must remain query-shape-only", errors)
    ensure_settings(map_data.get("settings"), "chunk1", errors)
    ensure_full_map_area(map_data, "chunk1", errors)

    alignment = artifact.get("alignment") or {}
    global_object_properties = ensure_property_scope(alignment.get("globalObjectProperties"), "alignment.globalObjectProperties", EXPECTED_GLOBAL_PROPERTY_SCOPE, errors)
    global_prop_entities = global_object_properties.get("propEntities") or []
    require(isinstance(global_prop_entities, list), "alignment.globalObjectProperties.propEntities must be list", errors)
    require(len(global_prop_entities) == EXPECTED_SOURCE_COUNT, f"global propEntities count mismatch: {len(global_prop_entities)}", errors)
    ensure_entity_alignment(global_prop_entities, errors, source_count=EXPECTED_SOURCE_COUNT)
    if global_prop_entities:
        layer0_entities = {entry.get("sourceIndex") for index, entry in enumerate(global_prop_entities) if isinstance(entry, dict) and source_key_layer(entry, errors, f"globalObjectProperties.propEntities[{index}]") == 0}
        layer1_entities = {entry.get("sourceIndex") for index, entry in enumerate(global_prop_entities) if isinstance(entry, dict) and source_key_layer(entry, errors, f"globalObjectProperties.propEntities[{index}]") == 1}
    else:
        layer0_entities = manifest_layer_indices["0"]
        layer1_entities = manifest_layer_indices["1"]

    expected_layer_pairs = {
        0: {(entry.get("sourceIndex"), entry.get("sourceKey")) for entry in manifest_records if isinstance(entry, dict) and str(entry.get("sourceKey", "")).startswith("0:")},
        1: {(entry.get("sourceIndex"), entry.get("sourceKey")) for entry in manifest_records if isinstance(entry, dict) and str(entry.get("sourceKey", "")).startswith("1:")},
    }

    object_properties = ensure_property_scope(chunk1.get("objectsProperties"), "chunk1", EXPECTED_LAYER_PROPERTY_SCOPE, errors)
    require("propEntities" in object_properties, "chunk1 objectsProperties must include propEntities", errors)
    prop_entities = object_properties.get("propEntities") or []
    require(isinstance(prop_entities, list), "chunk1 propEntities must be list", errors)
    require(len(prop_entities) == len(layer0_entities), f"chunk1 surface propEntities count mismatch: {len(prop_entities)} != {len(layer0_entities)}", errors)
    require(all(source_key_layer(entry, errors, "chunk1.propEntities") == 0 for entry in prop_entities if isinstance(entry, dict)), "chunk1 propEntities must be layer-0 surface records only", errors)
    if expected_layer_pairs[0]:
        require(source_pairs(prop_entities, errors, "chunk1.propEntities") == expected_layer_pairs[0], "chunk1 propEntities must exactly match layer-0 source records", errors)

    prop_before = object_properties.get("propActionsBefore") or []
    prop_after = object_properties.get("propActionsAfter") or []
    require(isinstance(prop_before, list), "chunk1 propActionsBefore must be list", errors)
    require(isinstance(prop_after, list), "chunk1 propActionsAfter must be list", errors)

    before_actions = [a for a in prop_before if isinstance(a, dict)]
    after_actions = [a for a in prop_after if isinstance(a, dict)]
    require(any(a.get("sourceKey") == EXPECTED_GUARDHOUSE for a in before_actions), "missing guardhouse action in chunk1 propActionsBefore", errors)
    require(not any(a.get("sourceKey") == EXPECTED_TERRANEUS for a in after_actions), "chunk1 surface propActionsAfter must not include underground Terraneus action", errors)

    story = chunk3
    require("payload" not in story, "chunk3 should expose counters/quests directly, not inside payload", errors)
    counters = story.get("counters") or []
    quests = story.get("quests") or []
    ensure_counter_set(
        counters,
        {"homecoming_started", "homecoming_terraneus_captured", "homecoming_map_event_0_visited"},
        errors,
        label="story counters",
    )
    ensure_counter_set(
        quests,
        {"homecoming_intro", "homecoming_main_goal", "homecoming_map_event_0"},
        errors,
        label="story quests",
    )

    sidecar = artifact.get("sidecar") or {}
    require(set(sidecar.keys()).issuperset({"rawLayer0", "rawLayer1", "counters", "quests"}), "sidecar must include rawLayer0, rawLayer1, counters, quests", errors)
    for key in ("rawLayer0", "rawLayer1"):
        for array_key in ["terrain", "road", "water", "mirror"]:
            require(len((sidecar.get(key) or {}).get(array_key, [])) == EXPECTED_TILE_COUNT, f"{key} {array_key} length mismatch", errors)
    ensure_counter_set(
        sidecar.get("counters") or [],
        {"homecoming_started", "homecoming_terraneus_captured", "homecoming_map_event_0_visited"},
        errors,
        label="sidecar counters",
    )
    ensure_counter_set(
        sidecar.get("quests") or [],
        {"homecoming_intro", "homecoming_main_goal", "homecoming_map_event_0"},
        errors,
        label="sidecar quests",
    )

    require((artifact.get("alignment") or {}).get("alignmentMode") == EXPECTED_ALIGNMENT_MODE, "alignment mode mismatch", errors)
    require((artifact.get("alignment") or {}).get("nonNative") is True, "alignment nonNative must be true", errors)

    if object_manifest:
        manifest_source_indices = {(entry.get("sourceIndex"), entry.get("sourceKey")) for entry in manifest_records}
        artifact_source_indices = {(entry.get("sourceIndex"), entry.get("sourceKey")) for entry in global_prop_entities}
        require(manifest_source_indices.issuperset(artifact_source_indices), "artifact propEntities must be covered by object manifest", errors)

    container_chunks = artifact.get("chunks")
    if container_chunks is not None:
        require(container_chunks == chunks, "legacy top-level chunks must mirror container.chunks when present", errors)
    require("objectsProperties" not in artifact, "artifact should not expose top-level objectsProperties in this adapter format", errors)

    expect_sidecar_actions = artifact.get("actions") or []
    require(any(action.get("sourceKey") == EXPECTED_TERRANEUS for action in expect_sidecar_actions), "actions must include Terraneus hypothesis", errors)
    require(any(action.get("sourceKey") == EXPECTED_GUARDHOUSE for action in expect_sidecar_actions), "actions must include Guardhouse event action", errors)

    chunk1_grouped = map_data.get("objects") or []
    require(len(chunk1_grouped) > 0, "chunk1.objects must include grouped map-object rows", errors)
    grouped_ids = ensure_olden_group_rows(chunk1_grouped, errors, expected_indices=layer0_entities)
    require("mapData" not in map_data, "chunk1 must not expose mapData wrapper; fields should be direct mapData fields", errors)

    # mapData chunk is surface/default; verify 1:1 source coverage for layer 0 objects.
    require(len(grouped_ids) == len(layer0_entities), f"chunk1 objects index coverage mismatch: {len(grouped_ids)} != {len(layer0_entities)}", errors)

    layered_map_data = artifact.get("layeredMapData") or []
    require(len(layered_map_data) >= 2, "layeredMapData must include both layers", errors)
    for sidecar_entry in layered_map_data:
        if not isinstance(sidecar_entry, dict):
            continue
        sidecar_map_data = sidecar_entry.get("mapData") or {}
        require(isinstance(sidecar_map_data, dict), "layeredMapData.mapData must be object", errors)
        require(sidecar_map_data.get("sizeX_") == 72 and sidecar_map_data.get("sizeZ_") == 72, "layeredMapData mapData must be 72x72", errors)
        ensure_settings(sidecar_map_data.get("settings"), f"layeredMapData[{sidecar_entry.get('layer')}].mapData", errors)
        ensure_full_map_area(sidecar_map_data, f"layeredMapData[{sidecar_entry.get('layer')}].mapData", errors)
        layer_properties = ensure_property_scope(sidecar_map_data.get("objectsProperties"), f"layeredMapData[{sidecar_entry.get('layer')}].mapData", EXPECTED_LAYER_PROPERTY_SCOPE, errors)
        sidecar_layer = sidecar_entry.get("layer")
        if sidecar_layer == 0:
            expected = layer0_entities
            expected_action_key = EXPECTED_GUARDHOUSE
            forbidden_action_key = EXPECTED_TERRANEUS
        elif sidecar_layer == 1:
            expected = layer1_entities
            expected_action_key = EXPECTED_TERRANEUS
            forbidden_action_key = EXPECTED_GUARDHOUSE
        else:
            expected = set()
            expected_action_key = None
            forbidden_action_key = None
        layered_prop_entities = layer_properties.get("propEntities") or []
        require(len(layered_prop_entities) == len(expected), f"layeredMapData layer {sidecar_layer} propEntities coverage mismatch: {len(layered_prop_entities)} != {len(expected)}", errors)
        if sidecar_layer in (0, 1):
            require(all(source_key_layer(entry, errors, f"layeredMapData layer {sidecar_layer}.propEntities") == sidecar_layer for entry in layered_prop_entities if isinstance(entry, dict)), f"layeredMapData layer {sidecar_layer} propEntities must be layer-local", errors)
            if expected_layer_pairs[sidecar_layer]:
                require(source_pairs(layered_prop_entities, errors, f"layeredMapData layer {sidecar_layer}.propEntities") == expected_layer_pairs[sidecar_layer], f"layeredMapData layer {sidecar_layer} propEntities must exactly match layer-local source records", errors)
        layer_actions = list(layer_properties.get("propActionsBefore") or []) + list(layer_properties.get("propActionsAfter") or [])
        if expected_action_key is not None:
            require(any(isinstance(action, dict) and action.get("sourceKey") == expected_action_key for action in layer_actions), f"layeredMapData layer {sidecar_layer} missing expected action {expected_action_key}", errors)
        if forbidden_action_key is not None:
            require(not any(isinstance(action, dict) and action.get("sourceKey") == forbidden_action_key for action in layer_actions), f"layeredMapData layer {sidecar_layer} contains cross-layer action {forbidden_action_key}", errors)
        layered_grouped_ids = ensure_olden_group_rows(sidecar_map_data.get("objects") or [], errors)
        if sidecar_layer in (0, 1):
            require(len(layered_grouped_ids) == len(expected), f"layeredMapData mapData layer {sidecar_layer} object index coverage mismatch: {len(layered_grouped_ids)} != {len(expected)}", errors)

    terraneus_entities = [e for e in global_prop_entities if e.get("sourceKey") == EXPECTED_TERRANEUS]
    require(len(terraneus_entities) == 1, f"expected exactly one Terraneus entity, found {len(terraneus_entities)}", errors)
    if terraneus_entities:
        terraneus_entity = terraneus_entities[0]
        require(terraneus_entity.get("templateObjectId") == EXPECTED_TERRANEUS_TEMPLATE, "terraneus templateObjectId must be 98", errors)

    guardhouse_entities = [e for e in global_prop_entities if e.get("sourceKey") == EXPECTED_GUARDHOUSE]
    require(len(guardhouse_entities) == 1, f"expected exactly one Guardhouse event entity, found {len(guardhouse_entities)}", errors)
    if guardhouse_entities:
        require(guardhouse_entities[0].get("message") == EXPECTED_GUARDHOUSE_MESSAGE, "guardhouse entity message mismatch", errors)

    guard_action = next((a for a in before_actions if a.get("sourceKey") == EXPECTED_GUARDHOUSE), None)
    if guard_action is not None:
        require(guard_action.get("message") == EXPECTED_GUARDHOUSE_MESSAGE, "guardhouse action message mismatch", errors)
        trigger_fields = guard_action.get("triggerFields") or {}
        if not trigger_fields:
            trigger_fields = guard_action
        require(trigger_fields.get("playersMask") == 255, "guardhouse playersMask must be 255", errors)
        require(trigger_fields.get("computerActivate") is True, "guardhouse computerActivate must be true", errors)
        require(trigger_fields.get("removeAfterVisit") is True, "guardhouse removeAfterVisit must be true", errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    errors: list[str] = []

    validate_builder_source(repo_root, errors)
    generated_root = None
    if not args.skip_generate:
        generated_root = run_generation(repo_root, errors)
    generated_artifact = (generated_root / "olden_storage_alignment" / "homecoming.olden_storage_alignment.json") if generated_root is not None else None
    validate_artifact(repo_root, errors, generated_artifact)

    if errors:
        print("Homecoming olden storage alignment contract validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Homecoming olden storage alignment contract validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




