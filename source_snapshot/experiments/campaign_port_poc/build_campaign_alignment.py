#!/usr/bin/env python3
"""Build Olden storage alignment artifacts for campaign batch missions."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import build_homecoming_olden_storage_alignment as align
from campaign_mission import CampaignMission, default_batch_manifest_path, load_batch_manifest, mission_by_id


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def configure_alignment_module(mission: CampaignMission, source_size: int) -> None:
    align.SOURCE_SIZE = source_size
    align.SOURCE_TILE_COUNT = source_size * source_size
    align.OUT_ROOT = mission.artifact_root / "olden_storage_alignment"
    align.OUTPUT_PATH = mission.alignment_path
    align.REPORT_PATH = align.OUT_ROOT / f"{mission.mission_id}.olden_storage_alignment_report.md"
    align.LAYERED_IR_PATH = mission.layered_ir_path
    align.MANIFEST_PATH = mission.object_port_manifest_path
    align.MAP_SID = mission.map_sid
    align.MAP_TITLE = mission.title


def build_story_rows_generic(mission: CampaignMission) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    manifest = json.loads(mission.object_port_manifest_path.read_text(encoding="utf-8"))
    records = manifest.get("records") or []
    objective_text = None
    briefing_texts: list[str] | None = None
    mission_title: str | None = None
    if mission.layered_ir_path.exists():
        layered_ir = json.loads(mission.layered_ir_path.read_text(encoding="utf-8"))
        mission_meta = layered_ir.get("mission") or {}
        victory = mission_meta.get("declaredVictoryCondition") or {}
        objective_text = str(victory.get("objectiveText") or mission_meta.get("objectiveText") or "")
        briefing_texts = list(mission_meta.get("briefingTexts") or [])
        mission_title = str(victory.get("sourceName") or "").strip() or None
    global_timed_events = None
    if mission.object_walk_path.exists():
        walk = json.loads(mission.object_walk_path.read_text(encoding="utf-8"))
        global_timed_events = walk.get("globalTimedEvents")
        if not mission_title:
            mission_title = str((walk.get("source") or {}).get("missionTitle") or "").strip() or None
    import campaign_runtime_script as runtime_script

    return runtime_script.build_alignment_story_payload(
        mission.mission_id,
        records,
        objective_text=objective_text or None,
        briefing_texts=briefing_texts,
        global_timed_events=global_timed_events,
        mission_title=mission_title,
    )


def _source_provenance(mission: CampaignMission) -> dict[str, str]:
    from h3c_mission_source import load_h3c_block

    source_block = load_h3c_block(mission.campaign_entry, mission.block_index)
    return {
        "sourceLodSha256": hashlib.sha256(source_block.lod_path.read_bytes()).hexdigest(),
        "sourceH3mSha256": source_block.h3m_sha256,
        "layeredIrSha256": hashlib.sha256(mission.layered_ir_path.read_bytes()).hexdigest(),
        "objectManifestSha256": hashlib.sha256(mission.object_port_manifest_path.read_bytes()).hexdigest(),
    }


def build_artifact_for_mission(mission: CampaignMission) -> dict[str, Any]:
    layered_ir = json.loads(mission.layered_ir_path.read_text(encoding="utf-8"))
    source_size = int((layered_ir.get("mapShape") or {}).get("width") or 72)
    configure_alignment_module(mission, source_size)
    layered_ir, manifest = align.load_inputs()

    layers = layered_ir.get("layers") or []
    if not layers:
        raise ValueError(f"layered IR has no layers for {mission.mission_id}")

    records = manifest.get("records") or []
    source_count = manifest.get("sourceObjectCount")
    if source_count != len(records):
        raise ValueError("manifest sourceObjectCount mismatch")

    entities, source_hist = align.build_entities(records)
    source_hist = dict(sorted(source_hist.items()))

    flatten: dict[int, dict[str, list[int]]] = {}
    for layer in layers:
        layer_index = int(layer.get("index", -1))
        if layer_index < 0:
            raise ValueError(f"invalid layer index in layered IR: {layer}")
        flatten[layer_index] = align.flatten_layer_tiles(layer)

    prop_actions_before, prop_actions_after, _actions, story_payload = build_story_rows_generic(mission)

    layered_map_data: list[dict[str, Any]] = []
    chunk_map_data_layers: list[dict[str, Any]] = []
    for layer_index in sorted(flatten):
        layer_entities = align.select_layer_entities(entities, layer_index)
        layer_objects = align.build_chunk_object_rows(entities, layer_index)
        layer_properties = align.build_layer_object_properties(
            layer_entities,
            before_actions=prop_actions_before if layer_index == 0 else [],
            after_actions=prop_actions_after if layer_index == max(flatten) else [],
            scope=align.LAYER_LOCAL_OBJECT_PROPERTIES_SCOPE if layer_index in flatten else align.GLOBAL_OBJECT_PROPERTIES_SCOPE,
        )
        map_chunk = align.build_olden_map_chunk(layer_index, flatten[layer_index], layer_objects, layer_properties)
        chunk_map_data_layers.append(map_chunk)
        layered_map_data.append(
            {
                "layer": layer_index,
                "sid": "surface" if layer_index == 0 else "underground",
                "alignment": "raw_query_shape_only",
                "mapData": map_chunk,
            }
        )

    global_objects_properties = align.build_layer_object_properties(
        entities,
        before_actions=prop_actions_before,
        after_actions=prop_actions_after,
        scope=align.GLOBAL_OBJECT_PROPERTIES_SCOPE,
    )

    container_chunks = [
        {
            "sizeX": source_size,
            "sizeZ": source_size,
            "queryChunkCount": align.CHUNK_COUNT,
            "schema": align.SCHEMA,
            "title": mission.title,
            "mapSid": mission.map_sid,
            "sourceLayerHistogram": source_hist,
            "nonPlayable": True,
            "runtimeNotApplicable": True,
            "nativeLayeredMapWriterUsed": False,
        },
        chunk_map_data_layers[0],
        {"dialogs": {"lines": []}, "quests": {"quests": []}},
        story_payload,
    ]
    if len(chunk_map_data_layers) > 1:
        container_chunks[1] = chunk_map_data_layers[0]
        # Keep chunk[1] as surface; underground stays in layeredMapData only for query compatibility.

    artifact = {
        "schema": align.SCHEMA,
        "status": align.STATUS,
        "storageFormat": {
            "reference": "Olden story map c_M1.map",
            "containerVersionReference": "0.72.30",
            "chunkModel": ["meta", "mapData", "dialogsQuests", "storyScript"],
        },
        "alignment": {
            "alignmentMode": align.ALIGNMENT_MODE,
            "nonNative": True,
            "surfaceLayer": "surface",
            "undergroundLayer": "underground" if len(flatten) > 1 else None,
            "note": "Layered H3M source is projected into flat chunk-1 map views for query compatibility only.",
            "globalObjectProperties": global_objects_properties,
        },
        "nonPlayable": True,
        "runtimeNotApplicable": True,
        "nativeLayeredMapWriterUsed": False,
        "queryShapeOnly": True,
        "silentFallbacksUsed": False,
        "source": {
            "layeredIr": str(mission.layered_ir_path),
            "objectManifest": str(mission.object_port_manifest_path),
            "sourceObjectCount": source_count,
            "sourceLayerCounts": source_hist,
            "missionId": mission.mission_id,
            "campaignEntry": mission.campaign_entry,
            "blockIndex": mission.block_index,
            # Provenance the raw_translation batch worker checks before emitting
            # (campaign_raw_translation_batch_worker._assert_alignment_provenance).
            **_source_provenance(mission),
        },
        "container": {
            "version": "h3m-aligned-olden-query-shape.v0",
            "chunks": container_chunks,
        },
        "chunks": container_chunks,
        "layeredMapData": layered_map_data,
        "globalEntities": entities,
        "validationGates": {
            "expectSourceObjectCount": source_count,
            "expectLayerCount": len(flatten),
            "expectChunkCount": align.CHUNK_COUNT,
            "expectTerrainLength": source_size * source_size,
        },
    }
    write_json(mission.alignment_path, artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=default_batch_manifest_path())
    parser.add_argument("--mission", required=True)
    args = parser.parse_args()
    batch = load_batch_manifest(args.manifest.resolve())
    mission = mission_by_id(batch, args.mission)
    if mission.reuse_existing_upstream and mission.alignment_path.exists():
        print(f"reusing existing alignment for {mission.mission_id}: {mission.alignment_path}")
        return 0
    artifact = build_artifact_for_mission(mission)
    print(f"wrote {mission.alignment_path} objects={artifact['source']['sourceObjectCount']} layers={artifact['validationGates']['expectLayerCount']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
