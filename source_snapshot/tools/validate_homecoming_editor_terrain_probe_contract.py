#!/usr/bin/env python3
"""Validate the editor-format Homecoming terrain probe contract."""

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

MAP_SID = "h3_roe_castle_homecoming_editor_terrain_probe"
TITLE = "Homecoming Editor Terrain Probe"
OLDEN_WIDTH = 96
OLDEN_HEIGHT = 96
SOURCE_WIDTH = 72
SOURCE_HEIGHT = 72
SOURCE_OFFSET_X = 12
SOURCE_OFFSET_Y = 12
PADDING_TILE_ID = 1
PADDING_WATER_ID = 0
H3_TO_OLDEN_TILE = {6: 15, 9: 23}
RIVER_TO_OLDEN_WATER = {1: 15}
EXPECTED_TERRAIN_HISTOGRAM = {1: 4032, 15: 1216, 23: 3968}
EXPECTED_WATER_HISTOGRAM = {0: 9090, 15: 126}
EXPECTED_LEVEL_HISTOGRAM = {0: 5248, 1: 3968}
EXPECTED_CLIMB_HISTOGRAM = {0: 9216}
H3_UNDERGROUND_ROCK_TERRAIN_ID = 9
UNDERGROUND_ROCK_LEVEL = 1
UNDERGROUND_ROCK_CLIMB = 0

GENERATION_CHAIN = [
    "build_homecoming_layered_ir.py",
    "walk_homecoming_objects.py",
    "build_homecoming_object_port_manifest.py",
    "build_homecoming_authentic_slice_ir.py",
    "build_homecoming_editor_terrain_probe.py",
]

REQUIRED_BUILDER_TOKENS = [
    'MAP_SID = "h3_roe_castle_homecoming_editor_terrain_probe"',
    'EDITOR_TEMPLATE_MAP = Path(__file__).resolve().parent / "fixtures" / "codex_editor_probe_64x64.map"',
    'OLDEN_WIDTH = 96',
    'OLDEN_HEIGHT = 96',
    'SOURCE_OFFSET_X = 12',
    'SOURCE_OFFSET_Y = 12',
    'PADDING_TILE_ID = 1',
    'PADDING_WATER_ID = 0',
    '"objects": []',
    '"customAreasPainting": []',
    '"silentFallbacksUsed": False',
    'require_dict(meta, "spawns")',
    'require_clean_dialog_chunk(chunks[2])',
    '"rivers": [{"sid": "test", "randomSeed": rivers[0]["randomSeed"], "nodes": []}]',
]

FORBIDDEN_BUILDER_TOKENS = [
    'PLAYABLE_TEMPLATE_MAP',
    'Thirst_for_Power',
    'OLDEN_MAPS_DIR / "codex_editor_probe_64x64.map"',
    'generate_quickstart',
    '"silentFallbacksUsed": True',
    'or [{"randomSeed": 0}]',
    'isinstance(meta.get("spawns"), dict)',
    'if isinstance(settings, dict)',
]

OBJECT_LIST_KEYS = [
    "objects",
    "squads",
    "markers",
    "takenHeroes",
    "keyObjects",
    "objectValuesOverrides",
]


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"missing JSON artifact: {path}")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as ex:
        errors.append(f"could not read {path}: {ex}")
        return {}
    if not isinstance(payload, dict):
        errors.append(f"JSON artifact is not an object: {path}")
        return {}
    return payload


def run_generation_chain(repo_root: Path, out_root: Path, errors: list[str]) -> None:
    script_dir = repo_root / "experiments" / "campaign_port_poc"
    env = dict(os.environ)
    env["HOMECOMING_POC_OUT_ROOT"] = str(out_root)
    for script_name in GENERATION_CHAIN:
        script = script_dir / script_name
        if not script.exists():
            errors.append(f"missing Homecoming generation script: {script}")
            return
        result = subprocess.run([sys.executable, str(script)], cwd=str(repo_root), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            errors.append(f"{script_name} failed with exit {result.returncode}:\n{result.stdout}")
            return

def validate_builder(repo_root: Path, errors: list[str]) -> None:
    builder = repo_root / "experiments" / "campaign_port_poc" / "build_homecoming_editor_terrain_probe.py"
    require(builder.exists(), f"missing editor terrain probe builder: {builder}", errors)
    if not builder.exists():
        return
    source = builder.read_text(encoding="utf-8-sig")
    for token in REQUIRED_BUILDER_TOKENS:
        require(token in source, f"editor terrain builder missing contract token: {token}", errors)
    for token in FORBIDDEN_BUILDER_TOKENS:
        require(token not in source, f"editor terrain builder contains forbidden token: {token}", errors)


def validate_editor_fixture(repo_root: Path, poc: Any, errors: list[str]) -> None:
    fixture = repo_root / "experiments" / "campaign_port_poc" / "fixtures" / "codex_editor_probe_64x64.map"
    require(fixture.exists(), f"missing checked-in editor fixture: {fixture}", errors)
    if not fixture.exists():
        return
    container = poc.read_olden_map_container(fixture)
    require(container.version == "0.80.20", f"editor fixture version changed: {container.version}", errors)
    require(len(container.chunks) == 3, f"editor fixture must have 3 chunks, found {len(container.chunks)}", errors)
    map_data = container.chunks[1]
    require(map_data.get("sizeX_") == 64 and map_data.get("sizeZ_") == 64, "editor fixture must remain the clean 64x64 native save", errors)
    require(len(map_data.get("tilesMap") or []) == 4096, "editor fixture tilesMap must have 4096 entries", errors)
    require(len(map_data.get("objects") or []) == 0, "editor fixture must not contain objects", errors)


def expected_target_values(source_tile: dict[str, Any]) -> tuple[int, int]:
    terrain = int(source_tile.get("terrain"))
    river = int(source_tile.get("river"))
    if terrain not in H3_TO_OLDEN_TILE:
        raise ValueError(f"unsupported source terrain {terrain} at {source_tile.get('key')}")
    if river != 0 and river not in RIVER_TO_OLDEN_WATER:
        raise ValueError(f"unsupported source river {river} at {source_tile.get('key')}")
    return H3_TO_OLDEN_TILE[terrain], RIVER_TO_OLDEN_WATER.get(river, 0)


def validate_generated(repo_root: Path, out_root: Path, poc: Any, errors: list[str]) -> None:
    root = out_root / "editor_terrain_probe"
    manifest = load_json(root / "install_manifest.json", errors)
    require(manifest.get("schema") == "homm3.homecoming_editor_terrain_probe.v0", "editor terrain manifest schema changed", errors)
    require(manifest.get("status") == "generated_editor_runtime_unvalidated", "editor terrain probe must remain runtime-unvalidated until native editor/load proof", errors)
    require(manifest.get("mapSid") == MAP_SID, "editor terrain probe map SID changed", errors)
    require(manifest.get("silentFallbacksUsed") is False, "editor terrain probe must report silentFallbacksUsed=false", errors)
    require("fixtures\\codex_editor_probe_64x64.map" in manifest.get("editorTemplateMap", "") or "fixtures/codex_editor_probe_64x64.map" in manifest.get("editorTemplateMap", ""), "manifest must point at checked-in editor fixture", errors)

    source_ir = load_json(out_root / "layered_ir" / "homecoming.authentic_terraneus_layer_slice_ir.json", errors)
    terrain = source_ir.get("terrain") or {}
    source_tiles = terrain.get("tiles") if isinstance(terrain, dict) else None
    require(terrain.get("width") == SOURCE_WIDTH and terrain.get("height") == SOURCE_HEIGHT, "source terrain must remain 72x72", errors)
    require(isinstance(source_tiles, list) and len(source_tiles) == SOURCE_WIDTH * SOURCE_HEIGHT, "source terrain tile count changed", errors)

    map_path = root / "maps" / f"{MAP_SID}.map"
    require(map_path.exists(), f"missing generated editor terrain map: {map_path}", errors)
    if not map_path.exists():
        return
    container = poc.read_olden_map_container(map_path)
    require(container.version == "0.80.20", f"generated editor map version changed: {container.version}", errors)
    require(len(container.chunks) == 3, f"generated editor map must have 3 chunks, found {len(container.chunks)}", errors)
    meta = container.chunks[0]
    map_data = container.chunks[1]
    require(meta.get("title") == TITLE, "generated map title changed", errors)
    require(meta.get("sizeX") == OLDEN_WIDTH and meta.get("sizeZ") == OLDEN_HEIGHT, "generated map metadata size changed", errors)
    require(meta.get("isScenario") is False, "generated map meta isScenario must be false", errors)
    require((meta.get("spawns") or {}).get("playersCount") == 0, "generated map must not declare player spawns", errors)
    require((meta.get("startSettings") or {}).get("DefeatAllEnemiesEnabled") is False, "generated map must not preserve defeat-all-enemies scenario setting", errors)
    require(map_data.get("fileMapName") == MAP_SID, "generated map fileMapName changed", errors)
    require(map_data.get("sizeX_") == OLDEN_WIDTH and map_data.get("sizeZ_") == OLDEN_HEIGHT, "generated map data size changed", errors)
    expected_len = OLDEN_WIDTH * OLDEN_HEIGHT
    for key in ["tilesMap", "levelsMap", "climbsMap", "roadsMap", "waterMap"]:
        require(isinstance(map_data.get(key), list) and len(map_data[key]) == expected_len, f"{key} must have {expected_len} entries", errors)
    for key in OBJECT_LIST_KEYS:
        require(map_data.get(key) == [], f"{key} must be empty in editor terrain probe", errors)
    require(map_data.get("customAreasPainting") == [], "customAreasPainting must be empty for editor terrain probe", errors)
    require(map_data.get("views") == [{"name": "", "minSecX": 0, "minSecZ": 0, "secSizeX": 6, "secSizeZ": 6, "isUnderground": False, "stack": -1}], "views must be pinned to one full 96x96 surface view", errors)
    require(map_data.get("rivers") and len(map_data["rivers"]) == 1 and map_data["rivers"][0].get("sid") == "test" and map_data["rivers"][0].get("nodes") == [] and isinstance(map_data["rivers"][0].get("randomSeed"), int), "rivers must preserve one Core river seed (sid 'test') with empty nodes", errors)
    require(map_data.get("banInfoData") == {"bannedMagics": [], "bannedItems": [], "bannedSkills": [], "bannedHeroes": [], "bannedUnits": []}, "map banInfoData must be empty", errors)
    require(meta.get("banInfoData") == {"bannedMagics": [], "bannedItems": [], "bannedSkills": [], "bannedHeroes": [], "bannedUnits": []}, "meta banInfoData must be empty", errors)
    require(map_data.get("haveCustomAreas") is False, "haveCustomAreas must remain false", errors)
    require(len(map_data.get("areas") or []) == 1, "editor terrain probe must have exactly one full map area", errors)
    if map_data.get("areas"):
        require(len(map_data["areas"][0].get("nodes") or []) == expected_len, "single area must cover every 96x96 node", errors)
    props = map_data.get("objectsProperties") or {}
    if isinstance(props, dict):
        for key, value in props.items():
            if isinstance(value, list):
                require(value == [], f"objectsProperties.{key} must be empty", errors)
    settings = map_data.get("settings") or {}
    require(settings.get("isScenario") is False and settings.get("gameMode") == 0 and settings.get("endController") == 0, "settings scenario/game mode fields changed", errors)
    for settings_key in ["economicDifficulties", "aiDifficulties", "neutralDifficulties", "quickStartDifficulties", "bonuses", "idSidesWithoutTimer", "idSidesWithoutNotification", "idSidesWithoutCameraFollowing"]:
        require(settings.get(settings_key) == [], f"settings.{settings_key} must be empty", errors)
    require(dict(sorted(Counter(map_data.get("tilesMap", [])).items())) == EXPECTED_TERRAIN_HISTOGRAM, "terrain histogram changed", errors)
    require(dict(sorted(Counter(map_data.get("waterMap", [])).items())) == EXPECTED_WATER_HISTOGRAM, "water histogram changed", errors)
    require(dict(sorted(Counter(map_data.get("levelsMap", [])).items())) == EXPECTED_LEVEL_HISTOGRAM, "level histogram changed", errors)
    require(dict(sorted(Counter(map_data.get("climbsMap", [])).items())) == EXPECTED_CLIMB_HISTOGRAM, "climb histogram changed", errors)

    if isinstance(source_tiles, list):
        by_key = {tile.get("key"): tile for tile in source_tiles if isinstance(tile, dict)}
        for y in range(OLDEN_HEIGHT):
            for x in range(OLDEN_WIDTH):
                target = y * OLDEN_WIDTH + x
                inside = SOURCE_OFFSET_X <= x < SOURCE_OFFSET_X + SOURCE_WIDTH and SOURCE_OFFSET_Y <= y < SOURCE_OFFSET_Y + SOURCE_HEIGHT
                if not inside:
                    require(map_data["tilesMap"][target] == PADDING_TILE_ID, f"padding tile changed at {x},{y}", errors)
                    require(map_data["waterMap"][target] == PADDING_WATER_ID, f"padding water changed at {x},{y}", errors)
                    continue
                sx = x - SOURCE_OFFSET_X
                sy = y - SOURCE_OFFSET_Y
                key = f"1:{sx}:{sy}"
                source_tile = by_key.get(key)
                require(source_tile is not None, f"missing source tile {key}", errors)
                if source_tile is None:
                    continue
                expected_tile, expected_water = expected_target_values(source_tile)
                require(map_data["tilesMap"][target] == expected_tile, f"projected tile mismatch at source {key}: {map_data['tilesMap'][target]} != {expected_tile}", errors)
                require(map_data["waterMap"][target] == expected_water, f"projected water mismatch at source {key}: {map_data['waterMap'][target]} != {expected_water}", errors)
                expected_level = UNDERGROUND_ROCK_LEVEL if int(source_tile.get("terrain")) == H3_UNDERGROUND_ROCK_TERRAIN_ID else 0
                require(map_data["levelsMap"][target] == expected_level, f"projected level mismatch at source {key}: {map_data['levelsMap'][target]} != {expected_level}", errors)
                require(map_data["climbsMap"][target] == UNDERGROUND_ROCK_CLIMB, f"projected climb mismatch at source {key}: {map_data['climbsMap'][target]} != {UNDERGROUND_ROCK_CLIMB}", errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    parser.add_argument("--skip-generate", action="store_true", help="Validate existing artifacts only.")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    errors: list[str] = []
    validate_builder(repo_root, errors)
    sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))
    import port_homecoming_poc as poc  # type: ignore
    validate_editor_fixture(repo_root, poc, errors)

    temp_root: Path | None = None
    if args.skip_generate:
        validation_out_root = repo_root / "artifacts" / "campaign_port_poc" / "homecoming_poc"
    else:
        temp_root = repo_root / "artifacts" / "campaign_port_poc" / "validator_tmp" / "homecoming_editor_probe"
        shutil.rmtree(temp_root, ignore_errors=True)
        validation_out_root = temp_root / "homecoming_poc"

    try:
        if not args.skip_generate and not errors:
            run_generation_chain(repo_root, validation_out_root, errors)
        if not errors:
            validate_generated(repo_root, validation_out_root, poc, errors)
    finally:
        if temp_root is not None:
            shutil.rmtree(temp_root, ignore_errors=True)

    if errors:
        print("Homecoming editor terrain probe validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Homecoming editor terrain probe validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())