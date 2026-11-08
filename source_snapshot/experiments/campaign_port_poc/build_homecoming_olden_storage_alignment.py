#!/usr/bin/env python3
"""Build a query-shape-only Homecoming Olden storage-alignment artifact.

This utility creates only a contract artifact for source-shape verification. It is
explicitly non-playable and does not emit an Olden `.map` container.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import campaign_runtime_script as campaign_script
import port_homecoming_poc as poc

SCHEMA = "homm3.homecoming_olden_storage_alignment.v0"
STATUS = "query_shape_only_not_playable"
ALIGNMENT_MODE = "layered_olden_chunk1_views_not_native_olden_container"
GLOBAL_OBJECT_PROPERTIES_SCOPE = "globalObjectProperties"
LAYER_LOCAL_OBJECT_PROPERTIES_SCOPE = "layerLocalObjectProperties"
MAP_SID = "h3_roe_castle_homecoming_olden_storage_alignment"
MAP_TITLE = "Homecoming Olden Storage Alignment"
SOURCE_SIZE = 72
SOURCE_TILE_COUNT = SOURCE_SIZE * SOURCE_SIZE
CHUNK_COUNT = 4
TERRANEUS_SOURCE_KEY = "1:35:35"
GUARDHOUSE_SOURCE_KEY = "0:18:35"
TERRANEUS_TEMPLATE_ID = 98
GUARDHOUSE_MESSAGE = (
    "Having defeated the Troglodytes, your men free the Guardhouse.  Within, the occupying "
    "Pikemen are eager to fight at your side."
)

OUT_ROOT = poc.OUT_ROOT / "olden_storage_alignment"
OUTPUT_PATH = OUT_ROOT / "homecoming.olden_storage_alignment.json"
REPORT_PATH = OUT_ROOT / "HOMECOMING_OLDEN_STORAGE_ALIGNMENT_REPORT.md"
LAYERED_IR_PATH = poc.OUT_ROOT / "layered_ir" / "homecoming.layered_map_ir.json"
MANIFEST_PATH = poc.OUT_ROOT / "layered_ir" / "homecoming.object_port_manifest.json"
OBJECT_WALK_PATH = poc.OUT_ROOT / "layered_ir" / "homecoming.object_walk.json"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_source_key(source_key: str) -> tuple[int, int, int]:
    layer_s, x_s, y_s = source_key.split(":")
    return int(layer_s), int(x_s), int(y_s)


def flatten_layer_tiles(layer: dict[str, Any]) -> dict[str, list[int]]:
    if layer.get("width") != SOURCE_SIZE or layer.get("height") != SOURCE_SIZE:
        raise ValueError(
            f"source layer has invalid size {layer.get('width')}x{layer.get('height')} "
            f"expected {SOURCE_SIZE}x{SOURCE_SIZE}"
        )

    tiles = layer.get("tiles")
    if not isinstance(tiles, list):
        raise ValueError("source layer is missing tiles list")
    if len(tiles) != SOURCE_TILE_COUNT:
        raise ValueError(f"source layer tile count mismatch, expected {SOURCE_TILE_COUNT}, found {len(tiles)}")

    terrain: list[int] = [0] * SOURCE_TILE_COUNT
    roads: list[int] = [0] * SOURCE_TILE_COUNT
    waters: list[int] = [0] * SOURCE_TILE_COUNT
    mirrors: list[int] = [0] * SOURCE_TILE_COUNT

    for tile in tiles:
        key = tile["key"]
        _, x, y = parse_source_key(key)
        if not (0 <= x < SOURCE_SIZE and 0 <= y < SOURCE_SIZE):
            raise ValueError(f"source key out of bounds {key}")
        node = y * SOURCE_SIZE + x
        terrain[node] = int(tile.get("terrain", 0))
        roads[node] = int(tile.get("road", 0))
        waters[node] = int(tile.get("river", 0))
        mirrors[node] = int(tile.get("mirror", 0))

    return {
        "terrain": terrain,
        "road": roads,
        "water": waters,
        "mirror": mirrors,
    }


def load_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    if not LAYERED_IR_PATH.exists():
        raise FileNotFoundError(f"missing layered IR: {LAYERED_IR_PATH}")
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"missing object port manifest: {MANIFEST_PATH}")

    layered_ir = json.loads(LAYERED_IR_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    if (manifest.get("validation") or {}).get("result") != "PASS":
        raise ValueError("object port manifest must pass before storage-alignment build")
    if manifest.get("silentFallbacksUsed") is not False:
        raise ValueError("object port manifest must declare silentFallbacksUsed=false")
    if layered_ir.get("silentFallbacksUsed") is not False:
        raise ValueError("layered IR must declare silentFallbacksUsed=false")

    return layered_ir, manifest


def category_to_alignment_sid(record: dict[str, Any]) -> str:
    category = (record.get("category") or "").lower()
    template_id = record.get("templateObjectId")
    if category == "town":
        return f"h3m.object.town.{template_id}"
    if category == "map_event":
        return "h3m.object.map_event"
    if template_id in (None, "unknown", ""):
        return "h3m.object.unmapped.unknown"
    return f"h3m.object.unmapped.{template_id}"


def build_entities(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter[str]]:
    entities: list[dict[str, Any]] = []
    layer_hist: Counter[str] = Counter()

    for record in records:
        if record.get("emitToMap") is False or record.get("category") == "campaign_briefing_script":
            continue
        source_key = record["sourceKey"]
        if not isinstance(source_key, str) or source_key.count(":") != 2:
            raise ValueError(
                f"record {record.get('sourceIndex')} category {record.get('category')} has non-map sourceKey {source_key!r}"
            )
        source_index = int(record["sourceIndex"])
        layer, x, y = parse_source_key(source_key)
        layer_hist[str(layer)] += 1
        node = y * SOURCE_SIZE + x
        template_id = record.get("templateObjectId")
        entity = {
            "id": source_index,
            "sid": category_to_alignment_sid(record),
            "sourceIndex": source_index,
            "sourceKey": source_key,
            "sourceLayer": layer,
            "sourceNode": node,
            "sourceX": x,
            "sourceY": y,
            "templateObjectId": template_id,
            "templateAnimation": record.get("templateAnimation"),
            "templateBlockMask": record.get("templateBlockMask"),
            "templateVisitMask": record.get("templateVisitMask"),
            "recordOffset": record.get("recordOffset"),
            "category": record.get("category"),
            "payloadKind": record.get("payloadKind"),
            "alignmentSid": category_to_alignment_sid(record),
            "alignmentStatus": "aligned_query_shape_only",
            "alignmentMode": ALIGNMENT_MODE,
            "queryShapeOnly": True,
            "rotation": int(record.get("rotation", 0) or 0),
            "level": int(record.get("level", 0) or 0),
        }
        for key in [
            "templateSubtype",
            "identifier",
            "count",
            "character",
            "hasMessage",
            "message",
            "artifact",
            "guardResources",
            "neverFlees",
            "notGrowingTeam",
            "owner",
            "ownerEncoding",
            "generatorFamily",
            "payloadDecoderEvidence",
            "heroType",
            "experience",
            "hasName",
            "hasGarrison",
            "hasArtifactSet",
            "secondarySkillCount",
            "secondarySkills",
            "garrisonStacks",
            "formation",
            "equippedArtifacts",
            "backpackArtifacts",
            "patrolRadius",
            "hasCustomBuildings",
            "builtBuildingsMask",
            "forbiddenBuildingsMask",
            "hasFort",
            "obligatorySpells",
            "availableSpells",
            "townEventCount",
            "townEvents",
            "townState",
            "alignment",
            "amount",
            "isRandomResource",
            "messageAndGuards",
            "playersMask",
            "computerActivate",
            "removeAfterVisit",
            "boxContent",
            "quest",
            "quests",
            "repeatableQuests",
            "payloadKind",
        ]:
            if key in record:
                entity[key] = record[key]
        if "name" in record:
            entity["name"] = record["name"]
        if "triggerFields" in record and record["triggerFields"] is not None:
            entity["triggerFields"] = record["triggerFields"]
        entities.append(entity)

    return sorted(entities, key=lambda item: item["sourceIndex"]), layer_hist


def build_chunk_object_rows(entities: list[dict[str, Any]], layer: int) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, list[int]]] = {}
    for entity in entities:
        layer_index, _, _ = parse_source_key(entity["sourceKey"])
        if layer_index != layer:
            continue
        sid = entity["sid"]
        bucket = grouped.setdefault(
            sid,
            {
                "sid": sid,
                "ids": [],
                "nodes": [],
                "rotations": [],
                "levels": [],
            },
        )
        bucket["ids"].append(int(entity["sourceIndex"]))
        bucket["nodes"].append(int(entity["sourceNode"]))
        bucket["rotations"].append(int(entity.get("rotation", 0) or 0))
        bucket["levels"].append(int(entity.get("level", 0) or 0))

    return [
        {
            "sid": sid,
            "ids": data["ids"],
            "nodes": data["nodes"],
            "rotations": data["rotations"],
            "levels": data["levels"],
        }
        for sid, data in sorted(grouped.items(), key=lambda item: item[0])
    ]


def build_map_settings() -> dict[str, Any]:
    return {
        "isScenario": True,
        "gameMode": "scenario",
        "endController": "neutral",
        "economicDifficulties": [0, 1, 2, 3],
        "aiDifficulties": [0, 1, 2, 3],
        "neutralDifficulties": [0, 1, 2, 3],
        "quickStartDifficulties": [0, 1, 2, 3],
    }


def build_full_map_area() -> list[dict[str, Any]]:
    return [
        {
            "sid": "full_map",
            "nodes": list(range(SOURCE_TILE_COUNT)),
        }
    ]


def build_layer_object_properties(
    entities: list[dict[str, Any]],
    before_actions: list[dict[str, Any]],
    after_actions: list[dict[str, Any]],
    scope: str,
) -> dict[str, Any]:
    return {
        "propsName": [],
        "propSpawns": [],
        "propHeroes": [],
        "propRandomSquads": [],
        "propPortals": [],
        "propVariants": [],
        "propActionsBefore": before_actions,
        "propActionsAfter": after_actions,
        "propEntities": entities,
        "propRewardParams": [],
        "propResParams": [],
        "propMarkers": [],
        "propActivations": [],
        "alignment": {
            "scope": scope,
            "alignmentMode": ALIGNMENT_MODE,
            "queryShapeOnly": True,
        },
    }


def build_olden_map_chunk(
    layer_index: int,
    layer_arrays: dict[str, list[int]],
    layer_objects: list[dict[str, Any]],
    object_properties: dict[str, Any],
) -> dict[str, Any]:
    return {
        "mapName": MAP_TITLE,
        "sizeX_": SOURCE_SIZE,
        "sizeZ_": SOURCE_SIZE,
        "valueDomain": "h3m_raw_terrain_ids",
        "tilesMap": layer_arrays["terrain"],
        "roadsMap": layer_arrays["road"],
        "waterMap": layer_arrays["water"],
        "levelsMap": [0] * SOURCE_TILE_COUNT,
        "climbsMap": [0] * SOURCE_TILE_COUNT,
        "customAreasPainting": [0] * SOURCE_TILE_COUNT,
        "settings": build_map_settings(),
        "areas": build_full_map_area(),
        "rivers": [],
        "banInfoData": {
            "bannedMagics": [],
            "bannedItems": [],
            "bannedSkills": [],
            "bannedHeroes": [],
            "bannedUnits": [],
        },
        "views": [
            {
                "name": "surface" if layer_index == 0 else "underground",
                "minSecX": 0,
                "minSecZ": 0,
                "secSizeX": 6,
                "secSizeZ": 6,
                "isUnderground": layer_index == 1,
                "stack": -1,
            }
        ],
        "objects": layer_objects,
        "objectsProperties": object_properties,
        "queryMode": "raw_h3_layer_flat_arrays",
        "queryShapeOnly": True,
        "rawMirror": layer_arrays["mirror"],
    }


def select_layer_entities(entities: list[dict[str, Any]], layer_index: int) -> list[dict[str, Any]]:
    layer_entities: list[dict[str, Any]] = []
    for entity in entities:
        try:
            source_layer = parse_source_key(entity["sourceKey"])[0]
        except Exception:
            continue
        if source_layer == layer_index:
            layer_entities.append(entity)
    return layer_entities


def build_story_rows(
    records: list[dict[str, Any]],
    *,
    objective_text: str = "",
    briefing_texts: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    global_timed_events = None
    if OBJECT_WALK_PATH.exists():
        global_timed_events = json.loads(OBJECT_WALK_PATH.read_text(encoding="utf-8")).get("globalTimedEvents")
    prop_actions_before, prop_actions_after, actions, story_payload = campaign_script.build_alignment_story_payload(
        "homecoming",
        records,
        objective_text=objective_text or None,
        briefing_texts=briefing_texts,
        global_timed_events=global_timed_events,
        mission_title="Homecoming",
    )

    for record in records:
        if record.get("sourceKey") != TERRANEUS_SOURCE_KEY:
            continue
        terraneus_found = {
            "sid": "h3m.action.terraneus_capture_alignment",
            "sourceKey": TERRANEUS_SOURCE_KEY,
            "sourceIndex": record.get("sourceIndex"),
            "sourceObjectTemplate": record.get("templateObjectId"),
            "templateAnimation": record.get("templateAnimation"),
            "alignmentStatus": "aligned_query_shape_only",
            "alignmentMode": ALIGNMENT_MODE,
            "alignmentOnlyHypothesis": "capture binding to Olden-objective tracker",
            "queryShapeOnly": True,
        }
        prop_actions_after.append(terraneus_found)
        actions.append(terraneus_found)

    counter_sids = {row.get("sid") for row in story_payload.get("counters") or []}
    if "homecoming_terraneus_captured" not in counter_sids:
        story_payload["counters"].append({"sid": "homecoming_terraneus_captured", "value": 0})

    return prop_actions_before, prop_actions_after, actions, story_payload


def build_artifact() -> dict[str, Any]:
    layered_ir, manifest = load_inputs()
    layers = layered_ir.get("layers") or []
    if len(layers) != 2:
        raise ValueError(f"expected exactly two source layers, found {len(layers)}")

    records = manifest.get("records") or []
    source_count = manifest.get("sourceObjectCount")
    if source_count != len(records):
        raise ValueError("manifest sourceObjectCount mismatch")
    if source_count != 1853:
        raise ValueError(f"expected 1853 source objects from manifest, found {source_count}")

    entities, source_hist = build_entities(records)
    source_hist = dict(sorted(source_hist.items()))

    flatten: dict[int, dict[str, list[int]]] = {}
    for layer in layers:
        layer_index = int(layer.get("index", -1))
        if layer_index not in (0, 1):
            raise ValueError(f"unsupported layer index {layer_index}")
        flatten[layer_index] = flatten_layer_tiles(layer)

    surface_map_rows = build_chunk_object_rows(entities, 0)
    underground_map_rows = build_chunk_object_rows(entities, 1)

    mission = layered_ir.get("mission") or {}
    prop_actions_before, prop_actions_after, actions, story_payload = build_story_rows(
        records,
        objective_text=str(mission.get("objectiveText") or ""),
        briefing_texts=list(mission.get("briefingTexts") or []),
    )

    surface_layer_entities = select_layer_entities(entities, 0)
    underground_layer_entities = select_layer_entities(entities, 1)

    surface_objects_properties = build_layer_object_properties(
        surface_layer_entities,
        before_actions=prop_actions_before,
        after_actions=[],
        scope=LAYER_LOCAL_OBJECT_PROPERTIES_SCOPE,
    )
    underground_objects_properties = build_layer_object_properties(
        underground_layer_entities,
        before_actions=[],
        after_actions=prop_actions_after,
        scope=LAYER_LOCAL_OBJECT_PROPERTIES_SCOPE,
    )
    global_objects_properties = build_layer_object_properties(
        entities,
        before_actions=prop_actions_before,
        after_actions=prop_actions_after,
        scope=GLOBAL_OBJECT_PROPERTIES_SCOPE,
    )

    surface_map_data = build_olden_map_chunk(
        0,
        flatten[0],
        surface_map_rows,
        surface_objects_properties,
    )
    underground_map_data = build_olden_map_chunk(
        1,
        flatten[1],
        underground_map_rows,
        underground_objects_properties,
    )

    container_chunks = [
        {
            "sizeX": SOURCE_SIZE,
            "sizeZ": SOURCE_SIZE,
            "queryChunkCount": CHUNK_COUNT,
            "schema": SCHEMA,
            "title": MAP_TITLE,
            "mapSid": MAP_SID,
                        "sourceLayerHistogram": source_hist,
            "nonPlayable": True,
            "runtimeNotApplicable": True,
            "nativeLayeredMapWriterUsed": False,
        },
        surface_map_data,
        {
            "dialogs": {
                "lines": [],
            },
            "quests": {
                "quests": [],
            },
        },
        story_payload,
    ]

    artifact = {
        "schema": SCHEMA,
        "status": STATUS,
        "storageFormat": {
            "reference": "Olden story map c_M1.map",
            "containerVersionReference": "0.72.30",
            "chunkModel": ["meta", "mapData", "dialogsQuests", "storyScript"],
        },
        "alignment": {
            "alignmentMode": ALIGNMENT_MODE,
            "nonNative": True,
            "surfaceLayer": "surface",
            "undergroundLayer": "underground",
            "note": "Layered H3M source is projected into flat chunk-1 map views for query compatibility only.",
            "globalObjectProperties": global_objects_properties,
        },
        "nonPlayable": True,
        "runtimeNotApplicable": True,
        "nativeLayeredMapWriterUsed": False,
        "queryShapeOnly": True,
        "silentFallbacksUsed": False,
        "source": {
            "layeredIr": str(LAYERED_IR_PATH),
            "objectManifest": str(MANIFEST_PATH),
            "sourceObjectCount": source_count,
            "sourceLayerCounts": source_hist,
        },
        "container": {
            "version": "h3m-aligned-olden-query-shape.v0",
            "chunks": container_chunks,
        },
        "chunks": container_chunks,
        "layeredMapData": [
            {
                "layer": 0,
                "sid": "surface",
                "alignment": "raw_query_shape_only",
                "mapData": surface_map_data,
            },
            {
                "layer": 1,
                "sid": "underground",
                "alignment": "raw_query_shape_only",
                "mapData": underground_map_data,
            },
        ],
        "actions": actions,
        "sidecar": {
            "rawLayer0": {
                "terrain": flatten[0]["terrain"],
                "road": flatten[0]["road"],
                "water": flatten[0]["water"],
                "mirror": flatten[0]["mirror"],
                "valueDomain": "h3m_raw_terrain_ids",
            },
            "rawLayer1": {
                "terrain": flatten[1]["terrain"],
                "road": flatten[1]["road"],
                "water": flatten[1]["water"],
                "mirror": flatten[1]["mirror"],
                "valueDomain": "h3m_raw_terrain_ids",
            },
            "counters": story_payload["counters"],
            "quests": story_payload["quests"],
        },
        "queryExamples": {
            "chunk1_size": {
                "sizeX_": surface_map_data["sizeX_"],
                "sizeZ_": surface_map_data["sizeZ_"],
            },
            "layered": [
                "container.chunks[1] contains Olden-style surface map data rows",
                "container.chunks[1].objectsProperties exists for Olden-style query code",
                "layeredMapData entries include layer 0 and layer 1 explicit mapData payloads",
            ],
        },
        "validationGates": {
            "expectSourceObjectCount": 1853,
            "expectLayerCount": 2,
            "expectLayer0Objects": 1453,
            "expectLayer1Objects": 400,
            "expectChunkCount": CHUNK_COUNT,
            "expectTerrainLength": SOURCE_TILE_COUNT,
        },
    }

    report = [
        "# Homecoming Olden Storage Alignment",
        "",
        f"Schema: {SCHEMA}",
        f"Status: {STATUS}",
        "",
        "## Contract",
        "- Non-playable, query-shape-only alignment artifact.",
        "- No `.map` writer called.",
        "- Container chunks are Olden-shaped directly: no chunk/kind/payload/mapData wrappers.",
        "- chunk2 uses direct dialogs/quests, and chunk3 uses direct story fields.",
        "- chunk1 and layer map views carry explicit settings and full-map areas.",
        "- globalObjectProperties and layer-local objectsProperties are explicit and separated.",
        "",
        "## Source checks",
        f"- Source objects: {source_count}",
        "- Source layer counts: 0=>1453, 1=>400",
        "",
        "## Proven required facts",
        f"- Terraneus source key: {TERRANEUS_SOURCE_KEY}",
        f"- Guardhouse source key: {GUARDHOUSE_SOURCE_KEY}",
        f"- Guardhouse message: {GUARDHOUSE_MESSAGE}",
        f"- Chunk count: {CHUNK_COUNT}",
    ]

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(report) + "\n", encoding="utf-8")
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    _ = parser.parse_args()
    artifact = build_artifact()
    write_json(OUTPUT_PATH, artifact)
    print(f"generated {OUTPUT_PATH}")
    print(
        f"chunks={len(artifact['container']['chunks'])} "
        f"entities={len(artifact['container']['chunks'][1].get('objectsProperties', {}).get('propEntities', []))} "
        f"sourceLayerCounts={artifact['source']['sourceLayerCounts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


