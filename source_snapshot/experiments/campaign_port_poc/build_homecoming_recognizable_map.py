#!/usr/bin/env python3
"""Build a recognizable playable Homecoming underground-slice map.

This emits an Olden .map from the source-authentic Terraneus-layer IR. It is a
visual/layout step toward authenticity, not a faithful full mission port: object
mapping remains limited to the proven Terraneus proxy, and layer travel/events
remain explicitly blocked.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import port_homecoming_poc as poc
import scenario_menu_shell

OUT_ROOT = poc.OUT_ROOT / "recognizable_underground_slice"
MAP_SID = "h3_roe_castle_homecoming_underground_slice"
TITLE = "Homecoming - Underground Slice"
DESCRIPTION = "A source-derived single-layer preview of Homecoming's underground Terraneus layer."
GOAL_ENTITY = "homecoming_underground_slice_terraneus_city"
SOURCE_IR = poc.OUT_ROOT / "layered_ir" / "homecoming.authentic_terraneus_layer_slice_ir.json"
TERRANEUS_SOURCE_KEY = "1:35:35"
TERRANEUS_PROXY_ID = poc.TERRANEUS_PROXY_TEMPLATE_ID
OLDEN_WIDTH = 96
OLDEN_HEIGHT = 96
SOURCE_OFFSET_X = 12
SOURCE_OFFSET_Y = 12
PADDING_TILE_ID = 10
PADDING_WATER_ID = 0

H3_TO_OLDEN_TILE = {
    6: {"oldenId": 15, "oldenBiome": "Burrow"},
    9: {"oldenId": 10, "oldenBiome": "Hills"},
}
RIVER_TO_OLDEN_WATER = {1: {"oldenId": 15, "oldenName": "water burrow"}}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_source_ir() -> dict[str, Any]:
    if not SOURCE_IR.exists():
        raise FileNotFoundError(f"missing authentic slice IR: {SOURCE_IR}")
    data = json.loads(SOURCE_IR.read_text(encoding="utf-8"))
    validation = data.get("validation") or {}
    if validation.get("result") != "PASS":
        raise ValueError(f"authentic slice IR must validate before map emission: {validation}")
    if data.get("emitsOldenMap") is not False:
        raise ValueError("authentic slice IR unexpectedly claims to emit an Olden map")
    return data


def project_terrain(tiles: list[dict[str, Any]]) -> dict[str, Any]:
    tiles_map: list[int] = []
    water_map: list[int] = []
    roads_map: list[int] = []
    unsupported_terrain: Counter[int] = Counter()
    unsupported_rivers: Counter[int] = Counter()
    for tile in tiles:
        terrain = tile.get("terrain")
        river = tile.get("river")
        road = tile.get("road")
        if terrain not in H3_TO_OLDEN_TILE:
            unsupported_terrain[int(terrain)] += 1
            continue
        if road != 0:
            raise ValueError(f"underground slice has unsupported nonzero road value at {tile.get('key')}: {road}")
        tiles_map.append(H3_TO_OLDEN_TILE[terrain]["oldenId"])
        roads_map.append(0)
        if river == 0:
            water_map.append(0)
        elif river in RIVER_TO_OLDEN_WATER:
            water_map.append(RIVER_TO_OLDEN_WATER[river]["oldenId"])
        else:
            unsupported_rivers[int(river)] += 1
    if unsupported_terrain:
        raise ValueError(f"unsupported H3 terrain values in underground slice: {dict(unsupported_terrain)}")
    if unsupported_rivers:
        raise ValueError(f"unsupported H3 river values in underground slice: {dict(unsupported_rivers)}")
    return {"tilesMap": tiles_map, "waterMap": water_map, "roadsMap": roads_map}


def pad_projected_terrain(projected: dict[str, list[int]], source_width: int, source_height: int) -> dict[str, list[int]]:
    expected = source_width * source_height
    if any(len(projected[key]) != expected for key in ("tilesMap", "waterMap", "roadsMap")):
        raise ValueError("projected map arrays do not match source terrain size")
    if SOURCE_OFFSET_X < 0 or SOURCE_OFFSET_Y < 0:
        raise ValueError("source offsets must be non-negative")
    if SOURCE_OFFSET_X + source_width > OLDEN_WIDTH or SOURCE_OFFSET_Y + source_height > OLDEN_HEIGHT:
        raise ValueError("source terrain does not fit in the Olden padded map envelope")

    out = {
        "tilesMap": [PADDING_TILE_ID] * (OLDEN_WIDTH * OLDEN_HEIGHT),
        "waterMap": [PADDING_WATER_ID] * (OLDEN_WIDTH * OLDEN_HEIGHT),
        "roadsMap": [0] * (OLDEN_WIDTH * OLDEN_HEIGHT),
    }
    for y in range(source_height):
        for x in range(source_width):
            source_index = y * source_width + x
            target_index = (SOURCE_OFFSET_Y + y) * OLDEN_WIDTH + (SOURCE_OFFSET_X + x)
            out["tilesMap"][target_index] = projected["tilesMap"][source_index]
            out["waterMap"][target_index] = projected["waterMap"][source_index]
            out["roadsMap"][target_index] = projected["roadsMap"][source_index]
    return out


def source_key_to_node(source_key: str, width: int, offset_x: int = 0, offset_y: int = 0) -> int:
    layer, x, y = source_key.split(":")
    if int(layer) != 1:
        raise ValueError(f"expected underground source key, found {source_key}")
    return (int(y) + offset_y) * width + int(x) + offset_x


def move_object_node(map_data: dict[str, Any], object_id: int, node: int) -> None:
    matches = []
    for group in map_data.get("objects", []):
        ids = group.get("ids")
        nodes = group.get("nodes")
        if not isinstance(ids, list) or not isinstance(nodes, list):
            continue
        for index, value in enumerate(ids):
            if value == object_id:
                matches.append((group, index))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one object id {object_id} placement, found {len(matches)}")
    group, index = matches[0]
    group["nodes"][index] = node
    if "levels" in group:
        group["levels"][index] = 0.0



def generate_local_quickstart_overlay(map_sid: str) -> dict[str, Any]:
    quickstart = poc.read_core_quickstart(poc.OLDEN_CORE_ZIP)
    scenarios = quickstart.get("scenarios")
    if not isinstance(scenarios, list) or "Thirst_for_Power" not in scenarios:
        raise ValueError("Core quickStart.json scenarios are missing the native Thirst_for_Power anchor")
    if scenarios.count(map_sid) > 1:
        raise ValueError(f"Core quickStart.json already contains duplicate {map_sid!r} entries")
    if map_sid not in scenarios:
        scenarios.append(map_sid)
    out_dir = OUT_ROOT / "core_overlay"
    out_path = out_dir / "quickStart.json"
    write_json(out_path, quickstart)
    manifest = {
        "status": "generated_catalog_overlay_uninstalled",
        "coreSource": str(poc.OLDEN_CORE_ZIP),
        "coreEntry": "DB/quickStart.json",
        "mapSid": map_sid,
        "scenarioAnchor": "Thirst_for_Power",
        "output": str(out_path),
        "contract": "Recognizable Homecoming underground slice must be present in QuickStartConfig.scenarios before runtime scenario selection can expose it.",
    }
    write_json(out_dir / "quickstart_catalog_overlay_manifest.json", manifest)
    return manifest

def generate_map() -> dict[str, Any]:
    source = load_source_ir()
    terrain = source["terrain"]
    width = terrain["width"]
    height = terrain["height"]
    if width != 72 or height != 72:
        raise ValueError(f"expected 72x72 source terrain, found {width}x{height}")
    projected = project_terrain(terrain["tiles"])
    padded = pad_projected_terrain(projected, width, height)
    expected = OLDEN_WIDTH * OLDEN_HEIGHT

    container = poc.read_olden_map_container(poc.PLAYABLE_TEMPLATE_MAP)
    chunks = json.loads(json.dumps(container.chunks, ensure_ascii=False))
    meta = chunks[0]
    map_data = chunks[1]
    map_hash = hashlib.md5(MAP_SID.encode("utf-8")).hexdigest()

    meta.update({
        "title": TITLE,
        "template": "",
        "desc": DESCRIPTION,
        "displayWinCondition": DESCRIPTION,
        "hashSum": map_hash,
        "nameFromLocalization": False,
        "descFromLocalization": False,
        "sizeX": OLDEN_WIDTH,
        "sizeZ": OLDEN_HEIGHT,
        "isScenario": True,
    })
    map_data.update({
        "fileMapName": MAP_SID,
        "mapName": TITLE,
        "mapNameFromLoc": False,
        "mapDesc": DESCRIPTION,
        "mapDescFromLoc": False,
        "sizeX_": OLDEN_WIDTH,
        "sizeZ_": OLDEN_HEIGHT,
        "tilesMap": padded["tilesMap"],
        "levelsMap": [0] * expected,
        "climbsMap": [0] * expected,
        "roadsMap": padded["roadsMap"],
        "waterMap": padded["waterMap"],
        "customAreasPainting": [2] * expected,
    })
    scenario_menu_shell.apply_menu_shell(meta, map_data, MAP_SID)
    poc.retag_terraneus_proxy(map_data, GOAL_ENTITY)
    terraneus_node = source_key_to_node(TERRANEUS_SOURCE_KEY, OLDEN_WIDTH, SOURCE_OFFSET_X, SOURCE_OFFSET_Y)
    move_object_node(map_data, TERRANEUS_PROXY_ID, terraneus_node)

    intro_text = "\n\n".join(source["mission"].get("briefingTexts") or [])
    chunks[2] = {"dialogs": {"lines": []}, "quests": {"quests": []}}
    chunks[3] = poc.make_embedded_homecoming_script(GOAL_ENTITY, intro_text)
    sidecar_script = poc.make_homecoming_script(GOAL_ENTITY, intro_text)

    maps_dir = OUT_ROOT / "maps"
    out_map = maps_dir / f"{MAP_SID}.map"
    out_json = maps_dir / f"{MAP_SID}.json"
    poc.write_olden_map_container(out_map, poc.OldenMapContainer(container.version, container.prefix_suffix, chunks), map_hash)
    write_json(out_json, sidecar_script)

    quickstart = generate_local_quickstart_overlay(MAP_SID)
    manifest = {
        "schema": "homm3.homecoming_recognizable_underground_slice_map.v0",
        "status": "generated_runtime_unvalidated",
        "mapSid": MAP_SID,
        "sourceIr": str(SOURCE_IR),
        "templateMap": str(poc.PLAYABLE_TEMPLATE_MAP),
        "outputs": {"map": str(out_map), "script": str(out_json), "quickStartOverlay": quickstart["output"]},
        "projection": {
            "terrain": H3_TO_OLDEN_TILE,
            "river": RIVER_TO_OLDEN_WATER,
            "runtimeEnvelope": {
                "width": OLDEN_WIDTH,
                "height": OLDEN_HEIGHT,
                "sourceWidth": width,
                "sourceHeight": height,
                "sourceOffsetX": SOURCE_OFFSET_X,
                "sourceOffsetY": SOURCE_OFFSET_Y,
                "paddingTileId": PADDING_TILE_ID,
                "paddingWaterId": PADDING_WATER_ID,
                "reason": "Golden Era runtime test left the session in adventure_map mode behind a stale loadingScene overlay when emitted at the exact HoMM3 72x72 size; this padded 96x96 envelope is a runtime-aligned substitution that preserves the complete 72x72 source layer.",
            },
            "terrainHistogram": dict(sorted(Counter(padded["tilesMap"]).items())),
            "waterHistogram": dict(sorted(Counter(padded["waterMap"]).items())),
            "sourceTerrainHistogram": terrain["terrainHistogram"],
            "sourceRiverHistogram": terrain["riverHistogram"],
        },
        "objectiveProxy": {
            "sourceKey": TERRANEUS_SOURCE_KEY,
            "sourceNode": terraneus_node,
            "templateObjectId": TERRANEUS_PROXY_ID,
            "entitySid": GOAL_ENTITY,
            "customCityName": "homecoming_city_name_terraneus",
        },
        "knownGaps": [
            "Only the underground layer is emitted; surface event/travel context remains blocked by missing layer support.",
            "Only the proven Terraneus proxy object is moved to a source coordinate; other source objects remain accounted in IR but not emitted as Olden objects.",
            "Terrain projection uses named Core tile IDs and is runtime-unvalidated until the generated map is loaded in Golden Era.",
        ],
        "silentFallbacksUsed": False,
    }
    write_json(OUT_ROOT / "install_manifest.json", manifest)
    write_report(manifest)
    return manifest


def write_report(manifest: dict[str, Any]) -> None:
    lines = [
        "# Homecoming Recognizable Underground Slice Map",
        "",
        f"Status: {manifest['status']}",
        f"Map SID: `{manifest['mapSid']}`",
        "",
        "## Source Projection",
        "",
    ]
    for source_value, target in sorted(manifest["projection"]["terrain"].items()):
        lines.append(f"- H3 terrain `{source_value}` -> Olden tile `{target['oldenId']}` ({target['oldenBiome']})")
    for source_value, target in sorted(manifest["projection"]["river"].items()):
        lines.append(f"- H3 river `{source_value}` -> Olden water `{target['oldenId']}` ({target['oldenName']})")
    lines.extend([
        "",
        "## Objective Proxy",
        "",
        f"- Terraneus source key `{manifest['objectiveProxy']['sourceKey']}` -> Olden node `{manifest['objectiveProxy']['sourceNode']}`",
        "",
        "## Known Gaps",
        "",
    ])
    lines.extend(f"- {gap}" for gap in manifest["knownGaps"])
    (OUT_ROOT / "RECOGNIZABLE_UNDERGROUND_SLICE_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    manifest = generate_map()
    print(f"generated {manifest['mapSid']} map={manifest['outputs']['map']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
