#!/usr/bin/env python3
"""Apply the current custom-biome pack to a Core.zip artifact."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORE = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
    r"\HeroesOldenEra_Data\StreamingAssets\Core.zip"
)
DEFAULT_OUT_DIR = ROOT / "artifacts" / "custom_biome_pack"

TILES_PATH = "DB/map/tiles/tiles.json"
WATERS_PATH = "DB/map/waters/waters.json"
BIOMES_INFO_PATH = "DB/biomes_info.json"
ARENAS_INFO_PATH = "DB/arenas/arenas_info.json"
ARENA_VIEWS_PATH = "DB/arenas/arenas_views_configs/arenas_views_configs.json"
GENERATOR_CONFIG_PATH = "generator/generator_config.json"
GENERATOR_ENVIRONMENT_ASSETS_PATH = "generator/generator_environment_assets.json"
MAP_MUSIC_SOUNDS_PATH = "DB/map_music_sounds.json"
MAP_AMBIENT_SOUNDS_PATH = "DB/map_ambient_sounds.json"
ARENA_OBSTRUCTIONS_CONFIG_PATH = "DB/arenas/arenas_obstructions_configs/test_obstructions.json"
FRACTIONS_PREFIX = "DB/fractions/"

BIOMES = [
    {
        "target": "Swamp",
        "source": "Autumn",
        "environmentSource": "Grass",
        "arenaSource": "Grass",
        "soundSource": "Grass",
        "faction": "homm3_fortress",
    },
    {"target": "Tundra", "source": "Snow", "faction": "homm3_tower"},
    {"target": "Hills", "source": "Grass", "faction": "homm3_rampart"},
    {"target": "Wasteland", "source": "Sand", "faction": "homm3_stronghold"},
    {"target": "Tropical", "source": "Sand", "faction": "homm3_cove"},
    {"target": "Greenlands", "source": "Grass", "faction": "homm3_conflux"},
    {"target": "Curselands", "source": "Deathland", "faction": "homm3_necropolis"},
    {"target": "Burrow", "source": "Dirt", "faction": "homm3_dungeon"},
    {"target": "Valleys", "source": "Grass", "faction": "homm3_castle"},
    {"target": "Molten", "source": "Lava", "faction": "homm3_inferno"},
    {"target": "Void", "source": "Dirt", "faction": None, "terrainOnly": True, "tileId": 23},
    # 24-28 are retired display-water Sand aliases; Factory/Bulwark own Sand/Snow clones above that range.
    {"target": "Foundry", "source": "Sand", "faction": "homm3_factory", "tileId": 29},
    {"target": "Permafrost", "source": "Snow", "faction": "homm3_bulwark", "tileId": 30},
]


class CorePackError(RuntimeError):
    pass


def load_json(raw: bytes, path: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except Exception as exc:
        raise CorePackError(f"failed to parse {path}: {exc}") from exc


def dump_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def rows_array(doc: dict[str, Any], path: str) -> list[dict[str, Any]]:
    rows = doc.get("array") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise CorePackError(f"{path} must contain array list")
    return rows


def keyed_rows(doc: dict[str, Any], path: str) -> list[dict[str, Any]]:
    rows = doc.get("array", {}).get("data") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise CorePackError(f"{path} must contain array.data list")
    return rows


def add_tile(docs: dict[str, Any], source: str, target: str, preferred_id: int | None = None) -> tuple[dict[str, Any], dict[str, Any], bool]:
    rows = rows_array(docs[TILES_PATH], TILES_PATH)
    existing = [row for row in rows if row.get("biome") == target]
    source_rows = [row for row in rows if row.get("biome") == source]
    if len(source_rows) != 1:
        raise CorePackError(f"{TILES_PATH}: expected one source biome {source}, found {len(source_rows)}")
    if existing:
        if preferred_id is not None and existing[0].get("id") != preferred_id:
            raise CorePackError(f"{TILES_PATH}: existing target biome {target} id must be {preferred_id}, got {existing[0].get('id')}")
        return source_rows[0], existing[0], False
    if preferred_id is not None:
        collisions = [row for row in rows if row.get("id") == preferred_id]
        if collisions:
            raise CorePackError(f"{TILES_PATH}: preferred id {preferred_id} for {target} already belongs to {collisions[0].get('biome')}")
        new_id = preferred_id
    else:
        new_id = max(int(row["id"]) for row in rows if isinstance(row.get("id"), int)) + 1
    clone = copy.deepcopy(source_rows[0])
    clone["id"] = new_id
    clone["name"] = f"tiles_{new_id}"
    clone["biome"] = target
    rows.append(clone)
    return source_rows[0], clone, True


def add_water(docs: dict[str, Any], source_tile: dict[str, Any], target_tile: dict[str, Any], target: str) -> tuple[dict[str, Any], bool]:
    rows = rows_array(docs[WATERS_PATH], WATERS_PATH)
    existing = [row for row in rows if row.get("id") == target_tile.get("id")]
    if existing:
        return existing[0], False
    source_rows = [row for row in rows if row.get("id") == source_tile.get("id")]
    if len(source_rows) != 1:
        raise CorePackError(f"{WATERS_PATH}: expected one source id {source_tile.get('id')}, found {len(source_rows)}")
    clone = copy.deepcopy(source_rows[0])
    clone["id"] = target_tile["id"]
    clone["name"] = f"water {target.lower()}"
    rows.append(clone)
    return clone, True


def add_water_mapping(docs: dict[str, Any], target: str, water_name: str) -> bool:
    rows = docs[GENERATOR_CONFIG_PATH].get("waterForBiome")
    if not isinstance(rows, list):
        raise CorePackError(f"{GENERATOR_CONFIG_PATH}: waterForBiome missing")
    existing = [row for row in rows if isinstance(row, dict) and row.get("key") == target]
    if existing:
        existing[0]["val"] = water_name
        return False
    rows.append({"key": target, "val": water_name})
    return True


def add_environment(docs: dict[str, Any], source: str, target: str) -> bool:
    rows = docs[GENERATOR_ENVIRONMENT_ASSETS_PATH].get("biomes")
    if not isinstance(rows, list):
        raise CorePackError(f"{GENERATOR_ENVIRONMENT_ASSETS_PATH}: biomes missing")
    existing = [row for row in rows if isinstance(row, dict) and row.get("sid") == target]
    source_rows = [row for row in rows if isinstance(row, dict) and row.get("sid") == source]
    if len(source_rows) != 1:
        raise CorePackError(f"{GENERATOR_ENVIRONMENT_ASSETS_PATH}: expected one source {source}, found {len(source_rows)}")
    if existing:
        for key in ("tilesets", "walkable", "water"):
            if key in source_rows[0]:
                existing[0][key] = copy.deepcopy(source_rows[0][key])
        return False
    clone = copy.deepcopy(source_rows[0])
    clone["sid"] = target
    rows.append(clone)
    return True


def add_biomes_info(docs: dict[str, Any], target: str, faction: str) -> bool:
    rows = docs[BIOMES_INFO_PATH].get("fractionsByBiome", {}).get("data")
    if not isinstance(rows, list):
        raise CorePackError(f"{BIOMES_INFO_PATH}: fractionsByBiome.data missing")
    existing = [row for row in rows if isinstance(row, dict) and row.get("key") == target]
    if existing:
        existing[0]["val"] = faction
        return False
    rows.append({"key": target, "val": faction})
    return True


def add_sound_row(docs: dict[str, Any], path: str, source: str, target: str) -> bool:
    rows = keyed_rows(docs[path], path)
    existing = [row for row in rows if row.get("key") == target]
    source_rows = [row for row in rows if row.get("key") == source]
    if len(source_rows) != 1:
        raise CorePackError(f"{path}: expected one source {source}, found {len(source_rows)}")
    if existing:
        existing[0]["val"] = copy.deepcopy(source_rows[0].get("val"))
        return False
    clone = copy.deepcopy(source_rows[0])
    clone["key"] = target
    rows.append(clone)
    return True


def view_id_for_target(view_id: str, source: str, target: str) -> str:
    source_lower = source.lower()
    target_lower = target.lower()
    return target_lower + view_id[len(source_lower) :] if view_id.startswith(source_lower) else f"{target_lower}_{view_id}"


def add_arena_views(docs: dict[str, Any], source: str, target: str) -> dict[str, str]:
    rows = rows_array(docs[ARENA_VIEWS_PATH], ARENA_VIEWS_PATH)
    source_rows = [row for row in rows if row.get("biome") == source]
    if not source_rows:
        raise CorePackError(f"{ARENA_VIEWS_PATH}: no source views for {source}")
    mapping: dict[str, str] = {}
    by_id = {str(row.get("id")): row for row in rows if row.get("id") is not None}
    existing_target = [row for row in rows if row.get("biome") == target]
    for row in source_rows:
        source_id = str(row["id"])
        target_id = view_id_for_target(source_id, source, target)
        mapping[source_id] = target_id
        if target_id in by_id:
            clone = by_id[target_id]
        else:
            clone = copy.deepcopy(row)
            clone["id"] = target_id
            rows.append(clone)
            by_id[target_id] = clone
        preserved_id = clone["id"]
        preserved_biome = target
        for key, value in row.items():
            if key in {"id", "biome"}:
                continue
            clone[key] = copy.deepcopy(value)
        clone["id"] = preserved_id
        clone["biome"] = preserved_biome
    return mapping


def add_arena_info(docs: dict[str, Any], source: str, target: str, mapping: dict[str, str]) -> int:
    rows = docs[ARENAS_INFO_PATH].get("arenas")
    if not isinstance(rows, list):
        raise CorePackError(f"{ARENAS_INFO_PATH}: arenas missing")
    source_rows = [row for row in rows if isinstance(row, dict) and row.get("biome") == source]
    if not source_rows:
        raise CorePackError(f"{ARENAS_INFO_PATH}: no source arenas for {source}")
    rows[:] = [row for row in rows if not (isinstance(row, dict) and row.get("biome") == target)]
    for row in source_rows:
        clone = copy.deepcopy(row)
        clone["biome"] = target
        if isinstance(clone.get("arenaViewSids"), list):
            clone["arenaViewSids"] = [mapping.get(str(sid), str(sid)) for sid in clone["arenaViewSids"]]
        rows.append(clone)
    return len(source_rows)


def add_arena_obstruction_models(docs: dict[str, Any], source: str, target: str) -> int:
    rows = rows_array(docs[ARENA_OBSTRUCTIONS_CONFIG_PATH], ARENA_OBSTRUCTIONS_CONFIG_PATH)
    changed = 0
    for row in rows:
        models = row.get("models")
        pairs = models.get("keyValuePairs") if isinstance(models, dict) else None
        if not isinstance(pairs, list):
            continue
        source_pair = next(
            (pair for pair in pairs if isinstance(pair, dict) and pair.get("key") == source),
            None,
        )
        if source_pair is None:
            raise CorePackError(f"{ARENA_OBSTRUCTIONS_CONFIG_PATH}: obstruction {row.get('id')!r} missing source biome {source}")
        target_pair = next(
            (pair for pair in pairs if isinstance(pair, dict) and pair.get("key") == target),
            None,
        )
        source_value = copy.deepcopy(source_pair.get("value"))
        if target_pair is not None:
            if target_pair.get("value") != source_pair.get("value"):
                target_pair["value"] = source_value
                changed += 1
            continue
        pairs.append({"key": target, "value": source_value})
        changed += 1
    return changed


def set_faction_biome(members: dict[str, bytes], faction: str, target: str) -> list[dict[str, str]]:
    updates: list[dict[str, str]] = []
    for name, raw in list(members.items()):
        if not name.startswith(FRACTIONS_PREFIX) or not name.endswith(".json"):
            continue
        doc = load_json(raw, name)
        rows = doc.get("array") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            continue
        changed = False
        for row in rows:
            if isinstance(row, dict) and row.get("id") == faction:
                old = str(row.get("biome", ""))
                row["biome"] = target
                updates.append({"path": name, "faction": faction, "old": old, "new": target})
                changed = True
        if changed:
            members[name] = dump_json(doc)
    if not updates:
        raise CorePackError(f"Could not find faction row {faction}")
    return updates


def build_pack(core: Path, out_dir: Path) -> dict[str, Any]:
    docs_paths = [
        TILES_PATH,
        WATERS_PATH,
        BIOMES_INFO_PATH,
        ARENAS_INFO_PATH,
        ARENA_VIEWS_PATH,
        GENERATOR_CONFIG_PATH,
        GENERATOR_ENVIRONMENT_ASSETS_PATH,
        MAP_MUSIC_SOUNDS_PATH,
        MAP_AMBIENT_SOUNDS_PATH,
        ARENA_OBSTRUCTIONS_CONFIG_PATH,
    ]
    with zipfile.ZipFile(core, "r") as src:
        members = {name: src.read(name) for name in src.namelist()}
        docs = {path: load_json(src.read(path), path) for path in docs_paths}

    report = apply_custom_biome_pack_to_members(members, docs)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_core = out_dir / "Core.custom_biome_pack.zip"
    with zipfile.ZipFile(out_core, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        for name in sorted(members):
            dst.writestr(name, members[name])
    report["inputCore"] = str(core)
    report["outputCore"] = str(out_core)
    (out_dir / "custom_biome_pack_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def apply_custom_biome_pack_to_members(members: dict[str, bytes], docs: dict[str, Any]) -> dict[str, Any]:
    report: dict[str, Any] = {"biomes": []}
    for spec in BIOMES:
        target = spec["target"]
        source = spec["source"]
        environment_source = spec.get("environmentSource", source)
        arena_source = spec.get("arenaSource", source)
        sound_source = spec.get("soundSource", source)
        faction = spec.get("faction")
        terrain_only = bool(spec.get("terrainOnly", False))
        source_tile, target_tile, tile_added = add_tile(docs, source, target, spec.get("tileId"))
        water, water_added = add_water(docs, source_tile, target_tile, target)
        add_water_mapping(docs, target, str(water["name"]))
        add_environment(docs, environment_source, target)
        if terrain_only:
            faction_updates = []
        else:
            if not isinstance(faction, str):
                raise CorePackError(f"{target}: faction biome must define a faction id")
            add_biomes_info(docs, target, faction)
        add_sound_row(docs, MAP_MUSIC_SOUNDS_PATH, sound_source, target)
        add_sound_row(docs, MAP_AMBIENT_SOUNDS_PATH, sound_source, target)
        mapping = add_arena_views(docs, arena_source, target)
        arena_rows = add_arena_info(docs, arena_source, target, mapping)
        obstruction_models = add_arena_obstruction_models(docs, arena_source, target)
        if not terrain_only:
            faction_updates = set_faction_biome(members, faction, target)
        report["biomes"].append(
            {
                "target": target,
                "source": source,
                "environmentSource": environment_source,
                "arenaSource": arena_source,
                "soundSource": sound_source,
                "faction": faction,
                "terrainOnly": terrain_only,
                "tileId": target_tile.get("id"),
                "tileAdded": tile_added,
                "waterAdded": water_added,
                "arenaViews": len(mapping),
                "arenaRows": arena_rows,
                "arenaObstructionModels": obstruction_models,
                "factionUpdates": faction_updates,
            }
        )

    for path, doc in docs.items():
        members[path] = dump_json(doc)
    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.clean and args.out_dir.exists():
            shutil.rmtree(args.out_dir)
        report = build_pack(args.core, args.out_dir)
    except CorePackError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
