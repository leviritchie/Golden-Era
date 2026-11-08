#!/usr/bin/env python3
"""Validate the Homecoming recognizable underground-slice map contract."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

RECOGNIZABLE_MAP_SID = "h3_roe_castle_homecoming_underground_slice"
PROXY_MAP_SID = "h3_roe_castle_homecoming_poc"
TERRANEUS_PROXY_ID = 5881
OLDEN_WIDTH = 96
OLDEN_HEIGHT = 96
SOURCE_OFFSET_X = 12
SOURCE_OFFSET_Y = 12
TERRANEUS_NODE = (35 + SOURCE_OFFSET_Y) * OLDEN_WIDTH + 35 + SOURCE_OFFSET_X
EXPECTED_TERRAIN_HISTOGRAM = {10: 8000, 15: 1216}
EXPECTED_WATER_HISTOGRAM = {0: 9090, 15: 126}
EXPECTED_SOURCE_TERRAIN = {"6": 1216, "9": 3968}
EXPECTED_SOURCE_RIVER = {"0": 5058, "1": 126}

REQUIRED_BUILDER_TOKENS = [
    'MAP_SID = "h3_roe_castle_homecoming_underground_slice"',
    'TITLE = "Homecoming - Underground Slice"',
    'GOAL_ENTITY = "homecoming_underground_slice_terraneus_city"',
    'H3_TO_OLDEN_TILE = {',
    '6: {"oldenId": 15, "oldenBiome": "Burrow"}',
    '9: {"oldenId": 10, "oldenBiome": "Hills"}',
    'RIVER_TO_OLDEN_WATER = {1: {"oldenId": 15, "oldenName": "water burrow"}}',
    'OLDEN_WIDTH = 96',
    'OLDEN_HEIGHT = 96',
    'SOURCE_OFFSET_X = 12',
    'SOURCE_OFFSET_Y = 12',
    'generate_local_quickstart_overlay',
    'move_object_node(map_data, TERRANEUS_PROXY_ID, terraneus_node)',
    '"silentFallbacksUsed": False',
]

FORBIDDEN_BUILDER_TOKENS = [
    'generate_quickstart_catalog_overlay(MAP_SID)',
    'build_quickstart_catalog_overlay(MAP_SID)',
    'PLAYABLE_DIR / "core_overlay"',
    '"silentFallbacksUsed": True',
]


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def read_json(path: Path, errors: list[str]) -> dict:
    if not path.exists():
        errors.append(f"missing JSON artifact: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as ex:
        errors.append(f"could not read {path}: {ex}")
        return {}


def validate_builder(repo_root: Path, errors: list[str]) -> None:
    builder = repo_root / "experiments" / "campaign_port_poc" / "build_homecoming_recognizable_map.py"
    require(builder.exists(), f"missing recognizable map builder: {builder}", errors)
    if not builder.exists():
        return
    source = builder.read_text(encoding="utf-8-sig")
    for token in REQUIRED_BUILDER_TOKENS:
        require(token in source, f"recognizable map builder missing contract token: {token}", errors)
    for token in FORBIDDEN_BUILDER_TOKENS:
        require(token not in source, f"recognizable map builder contains forbidden token: {token}", errors)


def validate_generated(repo_root: Path, errors: list[str]) -> None:
    sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))
    import port_homecoming_poc as poc  # type: ignore

    root = repo_root / "artifacts" / "campaign_port_poc" / "homecoming_poc"
    out_root = root / "recognizable_underground_slice"
    manifest = read_json(out_root / "install_manifest.json", errors)
    if not manifest:
        return
    require(manifest.get("schema") == "homm3.homecoming_recognizable_underground_slice_map.v0", "recognizable map manifest schema changed", errors)
    require(manifest.get("status") == "generated_runtime_unvalidated", "recognizable map status must remain runtime-unvalidated until live proof", errors)
    require(manifest.get("mapSid") == RECOGNIZABLE_MAP_SID, "recognizable map SID changed", errors)
    require(manifest.get("silentFallbacksUsed") is False, "recognizable map must report silentFallbacksUsed=false", errors)
    projection = manifest.get("projection") or {}
    require(projection.get("sourceTerrainHistogram") == EXPECTED_SOURCE_TERRAIN, f"source terrain histogram changed: {projection.get('sourceTerrainHistogram')}", errors)
    require(projection.get("sourceRiverHistogram") == EXPECTED_SOURCE_RIVER, f"source river histogram changed: {projection.get('sourceRiverHistogram')}", errors)
    require(projection.get("terrainHistogram") == {str(k): v for k, v in EXPECTED_TERRAIN_HISTOGRAM.items()}, f"projected terrain histogram changed: {projection.get('terrainHistogram')}", errors)
    require(projection.get("waterHistogram") == {str(k): v for k, v in EXPECTED_WATER_HISTOGRAM.items()}, f"projected water histogram changed: {projection.get('waterHistogram')}", errors)
    objective = manifest.get("objectiveProxy") or {}
    require(objective.get("sourceKey") == "1:35:35", "Terraneus source key changed", errors)
    require(objective.get("sourceNode") == TERRANEUS_NODE, f"Terraneus node changed: {objective.get('sourceNode')}", errors)
    require(objective.get("templateObjectId") == TERRANEUS_PROXY_ID, "Terraneus proxy object id changed", errors)

    outputs = manifest.get("outputs") or {}
    map_path = Path(outputs.get("map", ""))
    script_path = Path(outputs.get("script", ""))
    overlay_path = Path(outputs.get("quickStartOverlay", ""))
    require(map_path.exists(), f"missing generated recognizable map: {map_path}", errors)
    require(script_path.exists(), f"missing generated recognizable script: {script_path}", errors)
    require(overlay_path.exists(), f"missing generated recognizable QuickStart overlay: {overlay_path}", errors)
    require("recognizable_underground_slice" in str(overlay_path), "recognizable QuickStart overlay must live under recognizable_underground_slice", errors)

    if map_path.exists():
        container = poc.read_olden_map_container(map_path)
        meta = container.chunks[0]
        map_data = container.chunks[1]
        sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))
        import scenario_menu_shell as menu_shell

        menu_shell.validate_menu_shell_fields(
            meta,
            map_data,
            RECOGNIZABLE_MAP_SID,
            errors,
            context="recognizable underground slice map",
        )
        require(meta.get("sizeX") == OLDEN_WIDTH and meta.get("sizeZ") == OLDEN_HEIGHT, f"recognizable map metadata size must be {OLDEN_WIDTH}x{OLDEN_HEIGHT}, found {meta.get('sizeX')}x{meta.get('sizeZ')}", errors)
        require(map_data.get("fileMapName") == RECOGNIZABLE_MAP_SID, "recognizable map fileMapName changed", errors)
        require(map_data.get("sizeX_") == OLDEN_WIDTH and map_data.get("sizeZ_") == OLDEN_HEIGHT, f"recognizable map must be {OLDEN_WIDTH}x{OLDEN_HEIGHT}", errors)
        expected_len = OLDEN_WIDTH * OLDEN_HEIGHT
        for key in ["tilesMap", "levelsMap", "climbsMap", "roadsMap", "waterMap", "customAreasPainting"]:
            require(isinstance(map_data.get(key), list) and len(map_data[key]) == expected_len, f"{key} must have {expected_len} entries", errors)
        require(dict(sorted(Counter(map_data.get("tilesMap", [])).items())) == EXPECTED_TERRAIN_HISTOGRAM, "generated map terrain histogram changed", errors)
        require(dict(sorted(Counter(map_data.get("waterMap", [])).items())) == EXPECTED_WATER_HISTOGRAM, "generated map water histogram changed", errors)
        placements = []
        for group in map_data.get("objects", []):
            ids = group.get("ids") if isinstance(group, dict) else None
            nodes = group.get("nodes") if isinstance(group, dict) else None
            if isinstance(ids, list) and isinstance(nodes, list) and TERRANEUS_PROXY_ID in ids:
                placements.append((group.get("sid"), nodes[ids.index(TERRANEUS_PROXY_ID)]))
        require(placements == [("random-city", TERRANEUS_NODE)], f"Terraneus proxy placement changed: {placements}", errors)
        entities = [row for row in (map_data.get("objectsProperties") or {}).get("propEntities", []) if row.get("id") == TERRANEUS_PROXY_ID]
        require(len(entities) == 1 and entities[0].get("sid") == "homecoming_underground_slice_terraneus_city", f"Terraneus entity sid changed: {entities}", errors)
        cities = [row for row in (map_data.get("objectsProperties") or {}).get("propCities", []) if row.get("id") == TERRANEUS_PROXY_ID]
        require(len(cities) == 1 and cities[0].get("customCityName") == "homecoming_city_name_terraneus", f"Terraneus city name changed: {cities}", errors)

    if overlay_path.exists():
        overlay = read_json(overlay_path, errors)
        scenarios = overlay.get("scenarios") if overlay else None
        require(isinstance(scenarios, list), "recognizable QuickStart overlay scenarios must be a list", errors)
        if isinstance(scenarios, list):
            require(scenarios.count(RECOGNIZABLE_MAP_SID) == 1, "recognizable QuickStart overlay must contain exactly one underground slice SID", errors)
            require("Thirst_for_Power" in scenarios, "recognizable QuickStart overlay lost Thirst_for_Power anchor", errors)
    proxy_overlay = root / "playable_shell" / "core_overlay" / "quickStart.json"
    if proxy_overlay.exists():
        proxy = read_json(proxy_overlay, errors)
        scenarios = proxy.get("scenarios") if proxy else None
        if isinstance(scenarios, list):
            require(scenarios.count(PROXY_MAP_SID) == 1, "proxy QuickStart overlay must keep exactly one proxy SID", errors)
            require(RECOGNIZABLE_MAP_SID not in scenarios, "recognizable map must not pollute proxy QuickStart overlay", errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    errors: list[str] = []
    validate_builder(repo_root, errors)
    validate_generated(repo_root, errors)
    if errors:
        print("Homecoming recognizable underground-slice map validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Homecoming recognizable underground-slice map validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
