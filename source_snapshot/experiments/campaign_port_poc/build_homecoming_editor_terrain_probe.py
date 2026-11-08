#!/usr/bin/env python3
"""Build an editor-format Homecoming terrain probe map.

This intentionally targets the native Map Editor save shape rather than a shipped
scenario template. It is not a playable scenario: it proves whether the editor's
clean three-chunk map structure can carry the Homecoming underground terrain
projection without donor objects, players, or scenario script residue.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import h3m_scenario_translation as scenario
import port_homecoming_poc as poc

MAP_SID = "h3_roe_castle_homecoming_editor_terrain_probe"
TITLE = "Homecoming Editor Terrain Probe"
SOURCE_IR = poc.OUT_ROOT / "layered_ir" / "homecoming.authentic_terraneus_layer_slice_ir.json"
EDITOR_TEMPLATE_MAP = Path(__file__).resolve().parent / "fixtures" / "codex_editor_probe_64x64.map"
OUT_ROOT = poc.OUT_ROOT / "editor_terrain_probe"
OLDEN_WIDTH = 96
OLDEN_HEIGHT = 96
SOURCE_WIDTH = 72
SOURCE_HEIGHT = 72
SOURCE_OFFSET_X = 12
SOURCE_OFFSET_Y = 12
PADDING_TILE_ID = 1
PADDING_WATER_ID = 0

H3_TO_OLDEN_TILE = {
    scenario.H3_UNDERGROUND_SUBTERRANEAN_TERRAIN_ID: {"oldenId": scenario.OLDEN_BURROW_TILE_ID, "oldenBiome": "Burrow"},
    scenario.H3_UNDERGROUND_ROCK_TERRAIN_ID: {"oldenId": scenario.OLDEN_VOID_TILE_ID, "oldenBiome": "Void"},
}
RIVER_TO_OLDEN_WATER = {1: {"oldenId": scenario.OLDEN_BURROW_TILE_ID, "oldenName": "water burrow"}}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_source_ir() -> dict[str, Any]:
    data = json.loads(SOURCE_IR.read_text(encoding="utf-8"))
    validation = data.get("validation") or {}
    if validation.get("result") != "PASS":
        raise ValueError(f"authentic slice IR must validate before editor probe emission: {validation}")
    terrain = data.get("terrain") or {}
    if terrain.get("width") != SOURCE_WIDTH or terrain.get("height") != SOURCE_HEIGHT:
        raise ValueError(f"expected {SOURCE_WIDTH}x{SOURCE_HEIGHT} source terrain, found {terrain.get('width')}x{terrain.get('height')}")
    return data


def project_editor_arrays(source_tiles: list[dict[str, Any]]) -> dict[str, list[int]]:
    total = OLDEN_WIDTH * OLDEN_HEIGHT
    arrays = {
        "tilesMap": [PADDING_TILE_ID] * total,
        "waterMap": [PADDING_WATER_ID] * total,
        "roadsMap": [0] * total,
        "levelsMap": [0] * total,
        "climbsMap": [0] * total,
    }
    seen = 0
    for tile in source_tiles:
        key = tile.get("key")
        try:
            layer, raw_x, raw_y = str(key).split(":")
            x = int(raw_x)
            y = int(raw_y)
        except Exception as ex:
            raise ValueError(f"invalid source tile key {key!r}") from ex
        if int(layer) != 1:
            raise ValueError(f"expected underground tile key, found {key!r}")
        terrain = tile.get("terrain")
        river = tile.get("river")
        road = tile.get("road")
        if terrain not in H3_TO_OLDEN_TILE:
            raise ValueError(f"unsupported terrain {terrain!r} at {key}")
        if road != 0:
            raise ValueError(f"unsupported nonzero road {road!r} at {key}")
        target = (SOURCE_OFFSET_Y + y) * OLDEN_WIDTH + SOURCE_OFFSET_X + x
        arrays["tilesMap"][target] = H3_TO_OLDEN_TILE[terrain]["oldenId"]
        if river == 0:
            arrays["waterMap"][target] = 0
        elif river in RIVER_TO_OLDEN_WATER:
            arrays["waterMap"][target] = RIVER_TO_OLDEN_WATER[river]["oldenId"]
        else:
            raise ValueError(f"unsupported river {river!r} at {key}")
        if terrain == scenario.H3_UNDERGROUND_ROCK_TERRAIN_ID:
            arrays["levelsMap"][target] = scenario.UNDERGROUND_ROCK_LEVEL
            arrays["climbsMap"][target] = scenario.UNDERGROUND_ROCK_CLIMB
        seen += 1
    expected = SOURCE_WIDTH * SOURCE_HEIGHT
    if seen != expected:
        raise ValueError(f"expected {expected} source tiles, projected {seen}")
    return arrays


def require_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"editor template field {key!r} must be an object, found {type(value).__name__}")
    return value


def require_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"editor template field {key!r} must be a list, found {type(value).__name__}")
    return value


def require_clean_dialog_chunk(chunk: Any) -> None:
    if not isinstance(chunk, dict):
        raise ValueError("editor template chunk 2 must be an object")
    dialogs = require_dict(chunk, "dialogs")
    quests = require_dict(chunk, "quests")
    if require_list(dialogs, "lines") != []:
        raise ValueError("editor template dialogs.lines must be empty")
    if require_list(quests, "quests") != []:
        raise ValueError("editor template quests.quests must be empty")


def rewrite_editor_map() -> dict[str, Any]:
    if not EDITOR_TEMPLATE_MAP.exists():
        raise FileNotFoundError(f"missing editor template map; create it once from Extras -> Map Editor -> Save As: {EDITOR_TEMPLATE_MAP}")
    source = load_source_ir()
    arrays = project_editor_arrays(source["terrain"]["tiles"])
    container = poc.read_olden_map_container(EDITOR_TEMPLATE_MAP)
    if container.version != "0.80.20" or len(container.chunks) != 3:
        raise ValueError(f"editor template contract changed: version={container.version!r} chunks={len(container.chunks)}")
    chunks = json.loads(json.dumps(container.chunks, ensure_ascii=False))
    meta = chunks[0]
    map_data = chunks[1]
    require_clean_dialog_chunk(chunks[2])
    if not isinstance(meta, dict) or not isinstance(map_data, dict):
        raise ValueError("editor template meta and map data chunks must be objects")

    spawns = require_dict(meta, "spawns")
    start_settings = require_dict(meta, "startSettings")
    settings = require_dict(map_data, "settings")
    props = require_dict(map_data, "objectsProperties")
    rivers = require_list(map_data, "rivers")
    if len(rivers) != 1 or not isinstance(rivers[0], dict) or not isinstance(rivers[0].get("randomSeed"), int):
        raise ValueError("editor template must expose exactly one river row with an integer randomSeed")
    for key, value in props.items():
        if not isinstance(value, list):
            raise ValueError(f"editor template objectsProperties.{key} must be a list, found {type(value).__name__}")

    map_hash = hashlib.md5(MAP_SID.encode("utf-8")).hexdigest()
    meta.update({
        "title": TITLE,
        "template": "",
        "desc": "Editor-format terrain-only Homecoming underground projection.",
        "displayWinCondition": "",
        "hashSum": map_hash,
        "nameFromLocalization": False,
        "descFromLocalization": False,
        "sizeX": OLDEN_WIDTH,
        "sizeZ": OLDEN_HEIGHT,
        "isScenario": False,
        "gameMode": 0,
        "endController": 0,
        "banInfoData": {"bannedMagics": [], "bannedItems": [], "bannedSkills": [], "bannedHeroes": [], "bannedUnits": []},
        "campaignInfo": None,
    })
    spawns.update({"playersCount": 0, "spawns": [], "takenHeroes": []})
    start_settings["DefeatAllEnemiesEnabled"] = False

    total = OLDEN_WIDTH * OLDEN_HEIGHT
    map_data.update({
        "fileMapName": MAP_SID,
        "mapName": TITLE,
        "mapNameFromLoc": False,
        "mapDesc": "Editor-format terrain-only Homecoming underground projection.",
        "mapDescFromLoc": False,
        "sizeX_": OLDEN_WIDTH,
        "sizeZ_": OLDEN_HEIGHT,
        "tilesMap": arrays["tilesMap"],
        "levelsMap": arrays["levelsMap"],
        "climbsMap": arrays["climbsMap"],
        "roadsMap": arrays["roadsMap"],
        "waterMap": arrays["waterMap"],
        "customAreasPainting": [],
        "haveCustomAreas": False,
        "areasVersion": 1,
        "objects": [],
        "objectsFreeId": 0,
        "squads": [],
        "squadsFreeId": 0,
        "markers": [],
        "markersFreeId": 0,
        "takenHeroes": [],
        "keyObjects": [],
        "objectValuesOverrides": [],
        "areas": [{"id": 0, "keyObjectId": -1, "rootNode": 0, "nodes": list(range(total))}],
        "rivers": [{"sid": "test", "randomSeed": rivers[0]["randomSeed"], "nodes": []}],
        "views": [{"name": "", "minSecX": 0, "minSecZ": 0, "secSizeX": 6, "secSizeZ": 6, "isUnderground": False, "stack": -1}],
        "banInfoData": {"bannedMagics": [], "bannedItems": [], "bannedSkills": [], "bannedHeroes": [], "bannedUnits": []},
    })
    for key in list(props.keys()):
        props[key] = []
    settings["isScenario"] = False
    settings["gameMode"] = 0
    settings["endController"] = 0
    settings["disableWeekEffect"] = False
    settings["economicDifficulties"] = []
    settings["aiDifficulties"] = []
    settings["neutralDifficulties"] = []
    settings["quickStartDifficulties"] = []
    settings["bonuses"] = []
    settings["idSidesWithoutTimer"] = []
    settings["idSidesWithoutNotification"] = []
    settings["idSidesWithoutCameraFollowing"] = []

    chunks[2] = {"dialogs": {"lines": []}, "quests": {"quests": []}}
    out_map = OUT_ROOT / "maps" / f"{MAP_SID}.map"
    poc.write_olden_map_container(out_map, poc.OldenMapContainer(container.version, container.prefix_suffix, chunks), map_hash)
    manifest = {
        "schema": "homm3.homecoming_editor_terrain_probe.v0",
        "status": "generated_editor_runtime_unvalidated",
        "mapSid": MAP_SID,
        "editorTemplateMap": str(EDITOR_TEMPLATE_MAP),
        "sourceIr": str(SOURCE_IR),
        "outputMap": str(out_map),
        "dimensions": {"width": OLDEN_WIDTH, "height": OLDEN_HEIGHT, "sourceWidth": SOURCE_WIDTH, "sourceHeight": SOURCE_HEIGHT, "sourceOffsetX": SOURCE_OFFSET_X, "sourceOffsetY": SOURCE_OFFSET_Y},
        "projection": {
            "terrain": H3_TO_OLDEN_TILE,
            "river": RIVER_TO_OLDEN_WATER,
            "terrainHistogram": dict(sorted(Counter(arrays["tilesMap"]).items())),
            "waterHistogram": dict(sorted(Counter(arrays["waterMap"]).items())),
        },
        "contract": "No donor scenario/template objects are allowed; this is an editor-load terrain serialization probe only.",
        "silentFallbacksUsed": False,
    }
    write_json(OUT_ROOT / "install_manifest.json", manifest)
    return manifest

def main() -> int:
    manifest = rewrite_editor_map()
    print(f"generated editor terrain probe map={manifest['outputMap']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())