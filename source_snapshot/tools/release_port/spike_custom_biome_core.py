#!/usr/bin/env python3
"""Build a scratch Core.zip with one cloned custom biome for proof-spike testing.

This tool is intentionally conservative: it writes a new artifact and never
edits the live Steam Core.zip. It proves the JSON/Core side of a true biome
addition while calling out Unity resource surfaces that still need runtime or
asset-bundle proof.
"""

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
DEFAULT_TEMPLATE_DIR = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
    r"\HeroesOldenEra_Data\StreamingAssets\map_templates"
)
DEFAULT_UNITY_EXPORT = (
    ROOT
    / "tools"
    / "reference"
    / "assetripper_olden_demo_unity"
    / "ExportedProject"
    / "Assets"
)

TILES_PATH = "DB/map/tiles/tiles.json"
WATERS_PATH = "DB/map/waters/waters.json"
BIOMES_INFO_PATH = "DB/biomes_info.json"
ARENAS_INFO_PATH = "DB/arenas/arenas_info.json"
ARENA_VIEWS_PATH = "DB/arenas/arenas_views_configs/arenas_views_configs.json"
GENERATOR_CONFIG_PATH = "generator/generator_config.json"
GENERATOR_ENVIRONMENT_ASSETS_PATH = "generator/generator_environment_assets.json"
MAP_MUSIC_SOUNDS_PATH = "DB/map_music_sounds.json"
MAP_AMBIENT_SOUNDS_PATH = "DB/map_ambient_sounds.json"
FRACTIONS_PREFIX = "DB/fractions/"
BIOME_RULE_KEYS = {"zoneBiome", "contentBiome", "metaObjectsBiome"}


class SpikeError(RuntimeError):
    pass


def load_json_bytes(raw: bytes, path: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except Exception as exc:  # pragma: no cover - kept explicit for CLI diagnostics
        raise SpikeError(f"failed to parse {path}: {exc}") from exc


def dump_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def read_core_json(zf: zipfile.ZipFile, path: str) -> Any:
    try:
        raw = zf.read(path)
    except KeyError as exc:
        raise SpikeError(f"Core archive missing required member {path}") from exc
    return load_json_bytes(raw, path)


def require_array(doc: Any, path: str) -> list[dict[str, Any]]:
    if not isinstance(doc, dict) or not isinstance(doc.get("array"), list):
        raise SpikeError(f"{path} must be an object with an array list")
    rows = doc["array"]
    if not all(isinstance(row, dict) for row in rows):
        raise SpikeError(f"{path}.array must contain objects only")
    return rows


def require_unique_ids(rows: list[dict[str, Any]], path: str) -> set[Any]:
    ids: set[Any] = set()
    duplicates: set[Any] = set()
    for row in rows:
        row_id = row.get("id")
        if row_id in ids:
            duplicates.add(row_id)
        ids.add(row_id)
    if duplicates:
        raise SpikeError(f"{path} contains duplicate ids: {sorted(duplicates)!r}")
    return ids


def clone_tile_row(doc: dict[str, Any], source: str, target: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = require_array(doc, TILES_PATH)
    require_unique_ids(rows, TILES_PATH)
    if any(row.get("biome") == target for row in rows):
        raise SpikeError(f"{TILES_PATH} already contains biome {target!r}")
    source_rows = [row for row in rows if row.get("biome") == source]
    if len(source_rows) != 1:
        raise SpikeError(f"{TILES_PATH} expected one source biome {source!r}, found {len(source_rows)}")
    max_id = max(int(row["id"]) for row in rows if isinstance(row.get("id"), int))
    source_row = source_rows[0]
    target_row = copy.deepcopy(source_row)
    target_row["id"] = max_id + 1
    target_row["name"] = f"tiles_{max_id + 1}"
    target_row["biome"] = target
    rows.append(target_row)
    return source_row, target_row


def clone_water_row(doc: dict[str, Any], source_tile: dict[str, Any], target_tile: dict[str, Any], target: str) -> dict[str, Any]:
    rows = require_array(doc, WATERS_PATH)
    require_unique_ids(rows, WATERS_PATH)
    source_id = source_tile.get("id")
    source_rows = [row for row in rows if row.get("id") == source_id]
    if len(source_rows) != 1:
        raise SpikeError(f"{WATERS_PATH} expected one source id {source_id!r}, found {len(source_rows)}")
    target_row = copy.deepcopy(source_rows[0])
    target_row["id"] = target_tile["id"]
    target_row["name"] = f"water {target.lower()}"
    # Keep the donor material to isolate data plumbing from asset procurement.
    rows.append(target_row)
    return target_row


def add_generator_water_mapping(
    doc: dict[str, Any],
    source: str,
    target: str,
    target_water_name: str,
) -> dict[str, str]:
    rows = doc.get("waterForBiome") if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise SpikeError(f"{GENERATOR_CONFIG_PATH} must contain waterForBiome object rows")
    if any(row.get("key") == target for row in rows):
        raise SpikeError(f"{GENERATOR_CONFIG_PATH} already contains waterForBiome key {target!r}")
    if not any(row.get("key") == source for row in rows):
        raise SpikeError(f"{GENERATOR_CONFIG_PATH} has no source waterForBiome key {source!r}")
    row = {"key": target, "val": target_water_name}
    rows.append(row)
    return row


def clone_environment_biome(doc: dict[str, Any], source: str, target: str) -> dict[str, Any]:
    rows = doc.get("biomes") if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise SpikeError(f"{GENERATOR_ENVIRONMENT_ASSETS_PATH} must contain biomes object rows")
    if any(row.get("sid") == target for row in rows):
        raise SpikeError(f"{GENERATOR_ENVIRONMENT_ASSETS_PATH} already contains biome sid {target!r}")
    source_rows = [row for row in rows if row.get("sid") == source]
    if len(source_rows) != 1:
        raise SpikeError(f"{GENERATOR_ENVIRONMENT_ASSETS_PATH} expected one source biome {source!r}, found {len(source_rows)}")
    clone = copy.deepcopy(source_rows[0])
    clone["sid"] = target
    rows.append(clone)
    return clone


def apply_environment_presentation_donor(
    doc: dict[str, Any],
    clone: dict[str, Any],
    donor: str,
) -> dict[str, Any]:
    rows = doc.get("biomes") if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise SpikeError(f"{GENERATOR_ENVIRONMENT_ASSETS_PATH} must contain biomes object rows")
    donor_rows = [row for row in rows if row.get("sid") == donor]
    if len(donor_rows) != 1:
        raise SpikeError(f"{GENERATOR_ENVIRONMENT_ASSETS_PATH} expected one presentation donor biome {donor!r}, found {len(donor_rows)}")
    donor_row = donor_rows[0]
    for key in ("tilesets", "walkable", "water"):
        if key in donor_row:
            clone[key] = copy.deepcopy(donor_row[key])
    return {
        "donor": donor,
        "target": clone.get("sid"),
        "tilesets": len(clone.get("tilesets") or []),
        "walkableCopied": "walkable" in donor_row,
        "waterCopied": "water" in donor_row,
    }


def add_biome_mapping(doc: dict[str, Any], target: str, faction: str) -> dict[str, str]:
    mapping = doc.get("fractionsByBiome") if isinstance(doc, dict) else None
    rows = mapping.get("data") if isinstance(mapping, dict) else None
    if not isinstance(rows, list):
        raise SpikeError(f"{BIOMES_INFO_PATH} must contain fractionsByBiome.data")
    keys = [row.get("key") for row in rows if isinstance(row, dict)]
    if target in keys:
        raise SpikeError(f"{BIOMES_INFO_PATH} already contains biome key {target!r}")
    if len(keys) != len(set(keys)):
        raise SpikeError(f"{BIOMES_INFO_PATH} already contains duplicate biome keys")
    row = {"key": target, "val": faction}
    rows.append(row)
    return row


def clone_biome_keyed_data_row(doc: dict[str, Any], path: str, source: str, target: str) -> dict[str, Any]:
    mapping = doc.get("array") if isinstance(doc, dict) else None
    rows = mapping.get("data") if isinstance(mapping, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise SpikeError(f"{path} must contain array.data object rows")
    keys = [row.get("key") for row in rows]
    if target in keys:
        raise SpikeError(f"{path} already contains biome key {target!r}")
    if len(keys) != len(set(keys)):
        raise SpikeError(f"{path} already contains duplicate biome keys")
    source_rows = [row for row in rows if row.get("key") == source]
    if len(source_rows) != 1:
        raise SpikeError(f"{path} expected one source biome {source!r}, found {len(source_rows)}")
    clone = copy.deepcopy(source_rows[0])
    clone["key"] = target
    rows.append(clone)
    return clone


def set_faction_biome(members: dict[str, bytes], faction: str, target: str) -> list[dict[str, str]]:
    updates: list[dict[str, str]] = []
    for name, raw in list(members.items()):
        if not name.startswith(FRACTIONS_PREFIX) or not name.endswith(".json"):
            continue
        doc = load_json_bytes(raw, name)
        rows = doc.get("array") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            continue
        changed = False
        for row in rows:
            if not isinstance(row, dict) or row.get("id") != faction:
                continue
            old = str(row.get("biome", ""))
            row["biome"] = target
            updates.append({"path": name, "faction": faction, "old": old, "new": target})
            changed = True
        if changed:
            members[name] = dump_json_bytes(doc)
    if not updates:
        raise SpikeError(f"Could not find faction row {faction!r} to set biome {target!r}")
    return updates


def view_id_for_target(view_id: str, source: str, target: str) -> str:
    source_lower = source.lower()
    target_lower = target.lower()
    if view_id.startswith(source_lower):
        return target_lower + view_id[len(source_lower) :]
    return f"{target_lower}_{view_id}"


def clone_arena_views(doc: dict[str, Any], source: str, target: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    rows = require_array(doc, ARENA_VIEWS_PATH)
    require_unique_ids(rows, ARENA_VIEWS_PATH)
    if any(row.get("biome") == target for row in rows):
        raise SpikeError(f"{ARENA_VIEWS_PATH} already contains biome {target!r}")
    source_rows = [row for row in rows if row.get("biome") == source]
    if not source_rows:
        raise SpikeError(f"{ARENA_VIEWS_PATH} has no rows for source biome {source!r}")
    existing_ids = {row.get("id") for row in rows}
    mapping: dict[str, str] = {}
    clones: list[dict[str, Any]] = []
    for row in source_rows:
        source_id = str(row["id"])
        target_id = view_id_for_target(source_id, source, target)
        if target_id in existing_ids:
            raise SpikeError(f"{ARENA_VIEWS_PATH} target id already exists: {target_id!r}")
        clone = copy.deepcopy(row)
        clone["id"] = target_id
        clone["biome"] = target
        mapping[source_id] = target_id
        clones.append(clone)
    rows.extend(clones)
    return mapping, clones


def apply_arena_presentation_donor(
    doc: dict[str, Any],
    source: str,
    donor: str,
    view_mapping: dict[str, str],
    clones: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = require_array(doc, ARENA_VIEWS_PATH)
    by_id = {str(row.get("id")): row for row in rows if row.get("id") is not None}
    clone_by_id = {str(row.get("id")): row for row in clones if row.get("id") is not None}
    updates: list[dict[str, Any]] = []
    for source_id, target_id in view_mapping.items():
        clone = clone_by_id.get(target_id)
        if clone is None:
            raise SpikeError(f"{ARENA_VIEWS_PATH} cloned view disappeared: {target_id!r}")
        donor_id = view_id_for_target(source_id, source, donor)
        donor_row = by_id.get(donor_id)
        if donor_row is None:
            raise SpikeError(f"{ARENA_VIEWS_PATH} has no presentation donor view {donor_id!r}")
        old = {
            "sceneName": clone.get("sceneName"),
            "tileSets": copy.deepcopy(clone.get("tileSets")),
        }
        preserved_id = clone.get("id")
        preserved_biome = clone.get("biome")
        for key, value in donor_row.items():
            if key in {"id", "biome"}:
                continue
            clone[key] = copy.deepcopy(value)
        clone["id"] = preserved_id
        clone["biome"] = preserved_biome
        updates.append(
            {
                "id": target_id,
                "donor": donor_id,
                "old": old,
                "new": {
                    "sceneName": clone.get("sceneName"),
                    "tileSets": copy.deepcopy(clone.get("tileSets")),
                },
            }
        )
    return updates


def clone_arena_info(
    doc: dict[str, Any],
    source: str,
    target: str,
    view_mapping: dict[str, str],
) -> list[dict[str, Any]]:
    rows = doc.get("arenas") if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise SpikeError(f"{ARENAS_INFO_PATH} must contain arenas object rows")
    if any(row.get("biome") == target for row in rows):
        raise SpikeError(f"{ARENAS_INFO_PATH} already contains biome {target!r}")
    source_rows = [row for row in rows if row.get("biome") == source]
    if not source_rows:
        raise SpikeError(f"{ARENAS_INFO_PATH} has no rows for source biome {source!r}")
    clones: list[dict[str, Any]] = []
    for row in source_rows:
        clone = copy.deepcopy(row)
        clone["biome"] = target
        view_sids = clone.get("arenaViewSids")
        if isinstance(view_sids, list):
            clone["arenaViewSids"] = [view_mapping.get(str(sid), str(sid)) for sid in view_sids]
        clones.append(clone)
    rows.extend(clones)
    return clones


def replace_biome_rules(value: Any, target: str, key_name: str | None = None) -> int:
    changed = 0
    if isinstance(value, dict):
        if key_name in BIOME_RULE_KEYS and set(value) >= {"type", "args"} and isinstance(value.get("args"), list):
            value["type"] = "FromList"
            value["args"] = [target]
            changed += 1
        for child_key, child in value.items():
            changed += replace_biome_rules(child, target, str(child_key))
    elif isinstance(value, list):
        for child in value:
            changed += replace_biome_rules(child, target, key_name)
    return changed


def set_border_water(value: Any, water_name: str) -> int:
    changed = 0
    if isinstance(value, dict):
        if "waterType" in value:
            value["waterType"] = water_name
            changed += 1
        for child in value.values():
            changed += set_border_water(child, water_name)
    elif isinstance(value, list):
        for child in value:
            changed += set_border_water(child, water_name)
    return changed


def build_template(
    template_dir: Path,
    template_name: str,
    out_dir: Path,
    target: str,
    water_name: str,
) -> dict[str, Any]:
    source_path = template_dir / template_name
    if not source_path.exists():
        raise SpikeError(f"map template not found: {source_path}")
    template = json.loads(source_path.read_text(encoding="utf-8-sig"))
    template["name"] = f"{target} Proof"
    template["description"] = f"Proof spike template forcing {target} biome rules"
    biome_rule_count = replace_biome_rules(template, target)
    water_type_count = set_border_water(template, water_name)
    out_template_dir = out_dir / "map_templates"
    out_template_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_template_dir / f"{target} Proof.rmg.json"
    out_path.write_text(json.dumps(template, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "source": str(source_path),
        "output": str(out_path),
        "biome_rule_count": biome_rule_count,
        "water_type_count": water_type_count,
    }


def unity_resource_checks(unity_assets: Path, target: str, arena_views: list[dict[str, Any]]) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "unity_assets": str(unity_assets),
        "terrain_material_asset_exists": False,
        "target_terrain_material_present": False,
        "scene_missing": [],
        "tile_set_missing": [],
    }
    terrain_material = unity_assets / "Resources" / "configs" / "TerrainMaterials.asset"
    checks["terrain_material_asset_exists"] = terrain_material.exists()
    if terrain_material.exists():
        text = terrain_material.read_text(encoding="utf-8", errors="ignore")
        checks["target_terrain_material_present"] = f"name: {target}" in text
    scenes_dir = unity_assets / "Scenes" / "Arenas"
    tile_sets_dir = unity_assets / "Resources" / "configs" / "arenas" / "tile_sets"
    missing_scenes: set[str] = set()
    missing_tile_sets: set[str] = set()
    for view in arena_views:
        scene = view.get("sceneName")
        if isinstance(scene, str) and not (scenes_dir / f"{scene}.unity").exists():
            missing_scenes.add(scene)
        for tile_set in view.get("tileSets") or []:
            if isinstance(tile_set, str) and not (tile_sets_dir / f"{tile_set}.asset").exists():
                missing_tile_sets.add(tile_set)
    checks["scene_missing"] = sorted(missing_scenes)
    checks["tile_set_missing"] = sorted(missing_tile_sets)
    return checks


def validate_spike(
    docs: dict[str, Any],
    target: str,
    expected_counts: dict[str, int],
) -> list[str]:
    failures: list[str] = []
    tiles = require_array(docs[TILES_PATH], TILES_PATH)
    waters = require_array(docs[WATERS_PATH], WATERS_PATH)
    arena_views = require_array(docs[ARENA_VIEWS_PATH], ARENA_VIEWS_PATH)
    arena_rows = docs[ARENAS_INFO_PATH].get("arenas", [])
    biome_rows = docs[BIOMES_INFO_PATH].get("fractionsByBiome", {}).get("data", [])
    generator_water_rows = docs[GENERATOR_CONFIG_PATH].get("waterForBiome", [])
    environment_rows = docs[GENERATOR_ENVIRONMENT_ASSETS_PATH].get("biomes", [])
    map_music_rows = docs[MAP_MUSIC_SOUNDS_PATH].get("array", {}).get("data", [])
    map_ambient_rows = docs[MAP_AMBIENT_SOUNDS_PATH].get("array", {}).get("data", [])
    if sum(1 for row in tiles if row.get("biome") == target) != 1:
        failures.append(f"{TILES_PATH} must contain exactly one {target} tile row")
    if sum(1 for row in waters if str(row.get("name", "")).lower() == f"water {target.lower()}") != 1:
        failures.append(f"{WATERS_PATH} must contain exactly one water {target.lower()} row")
    if sum(1 for row in generator_water_rows if isinstance(row, dict) and row.get("key") == target) != 1:
        failures.append(f"{GENERATOR_CONFIG_PATH} waterForBiome must contain exactly one {target} key")
    if sum(1 for row in environment_rows if isinstance(row, dict) and row.get("sid") == target) != 1:
        failures.append(f"{GENERATOR_ENVIRONMENT_ASSETS_PATH} must contain exactly one {target} biome row")
    if sum(1 for row in map_music_rows if isinstance(row, dict) and row.get("key") == target) != 1:
        failures.append(f"{MAP_MUSIC_SOUNDS_PATH} must contain exactly one {target} key")
    if sum(1 for row in map_ambient_rows if isinstance(row, dict) and row.get("key") == target) != 1:
        failures.append(f"{MAP_AMBIENT_SOUNDS_PATH} must contain exactly one {target} key")
    if sum(1 for row in biome_rows if row.get("key") == target) != 1:
        failures.append(f"{BIOMES_INFO_PATH} must contain exactly one {target} key")
    if sum(1 for row in arena_views if row.get("biome") == target) != expected_counts["arena_views"]:
        failures.append(f"{ARENA_VIEWS_PATH} target view count mismatch")
    target_arena_rows = [row for row in arena_rows if isinstance(row, dict) and row.get("biome") == target]
    if len(target_arena_rows) != expected_counts["arena_info"]:
        failures.append(f"{ARENAS_INFO_PATH} target arena count mismatch")
    view_ids = {row.get("id") for row in arena_views}
    missing_views = sorted(
        {
            sid
            for row in target_arena_rows
            for sid in row.get("arenaViewSids", [])
            if sid not in view_ids
        }
    )
    if missing_views:
        failures.append(f"{ARENAS_INFO_PATH} references missing arena views: {missing_views!r}")
    return failures


def build_spike(args: argparse.Namespace) -> dict[str, Any]:
    if not args.core.exists():
        raise SpikeError(f"Core archive not found: {args.core}")
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_core = out_dir / f"Core.{args.target.lower()}_spike.zip"

    with zipfile.ZipFile(args.core, "r") as src:
        members = {name: src.read(name) for name in src.namelist()}
        docs = {
            TILES_PATH: read_core_json(src, TILES_PATH),
            WATERS_PATH: read_core_json(src, WATERS_PATH),
            BIOMES_INFO_PATH: read_core_json(src, BIOMES_INFO_PATH),
            ARENAS_INFO_PATH: read_core_json(src, ARENAS_INFO_PATH),
            ARENA_VIEWS_PATH: read_core_json(src, ARENA_VIEWS_PATH),
            GENERATOR_CONFIG_PATH: read_core_json(src, GENERATOR_CONFIG_PATH),
            GENERATOR_ENVIRONMENT_ASSETS_PATH: read_core_json(src, GENERATOR_ENVIRONMENT_ASSETS_PATH),
            MAP_MUSIC_SOUNDS_PATH: read_core_json(src, MAP_MUSIC_SOUNDS_PATH),
            MAP_AMBIENT_SOUNDS_PATH: read_core_json(src, MAP_AMBIENT_SOUNDS_PATH),
        }

    source_tile, target_tile = clone_tile_row(docs[TILES_PATH], args.source, args.target)
    target_water = clone_water_row(docs[WATERS_PATH], source_tile, target_tile, args.target)
    generator_water_mapping = add_generator_water_mapping(
        docs[GENERATOR_CONFIG_PATH],
        args.source,
        args.target,
        str(target_water["name"]),
    )
    environment_biome = clone_environment_biome(docs[GENERATOR_ENVIRONMENT_ASSETS_PATH], args.source, args.target)
    environment_presentation = None
    if args.environment_presentation_donor:
        environment_presentation = apply_environment_presentation_donor(
            docs[GENERATOR_ENVIRONMENT_ASSETS_PATH],
            environment_biome,
            args.environment_presentation_donor,
        )
    target_mapping = add_biome_mapping(docs[BIOMES_INFO_PATH], args.target, args.faction)
    sound_presentation_donor = args.environment_presentation_donor or args.source
    map_music_row = clone_biome_keyed_data_row(
        docs[MAP_MUSIC_SOUNDS_PATH],
        MAP_MUSIC_SOUNDS_PATH,
        sound_presentation_donor,
        args.target,
    )
    map_ambient_row = clone_biome_keyed_data_row(
        docs[MAP_AMBIENT_SOUNDS_PATH],
        MAP_AMBIENT_SOUNDS_PATH,
        sound_presentation_donor,
        args.target,
    )
    view_mapping, cloned_views = clone_arena_views(docs[ARENA_VIEWS_PATH], args.source, args.target)
    arena_presentation_updates: list[dict[str, Any]] = []
    if args.arena_presentation_donor:
        arena_presentation_updates = apply_arena_presentation_donor(
            docs[ARENA_VIEWS_PATH],
            args.source,
            args.arena_presentation_donor,
            view_mapping,
            cloned_views,
        )
    cloned_arenas = clone_arena_info(docs[ARENAS_INFO_PATH], args.source, args.target, view_mapping)
    faction_biome_updates = set_faction_biome(members, args.faction, args.target)

    expected_counts = {
        "arena_views": len(cloned_views),
        "arena_info": len(cloned_arenas),
    }
    failures = validate_spike(docs, args.target, expected_counts)

    for path, doc in docs.items():
        members[path] = dump_json_bytes(doc)

    with zipfile.ZipFile(out_core, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        for name in sorted(members):
            dst.writestr(name, members[name])

    template_report = build_template(
        args.template_dir,
        args.template_name,
        out_dir,
        args.target,
        str(target_water["name"]),
    )
    unity_checks = unity_resource_checks(args.unity_assets, args.target, cloned_views)

    report = {
        "target": args.target,
        "source": args.source,
        "faction_mapping": target_mapping,
        "core_input": str(args.core),
        "core_output": str(out_core),
        "source_tile": source_tile,
        "target_tile": target_tile,
        "target_water": target_water,
        "generator_water_mapping": generator_water_mapping,
        "generator_environment_biome": {
            "sid": environment_biome.get("sid"),
            "tilesets": len(environment_biome.get("tilesets") or []),
            "has_walkable": isinstance(environment_biome.get("walkable"), dict),
            "has_water": isinstance(environment_biome.get("water"), dict),
        },
        "environment_presentation_donor": environment_presentation,
        "sound_presentation_donor": sound_presentation_donor,
        "map_music_sounds": map_music_row,
        "map_ambient_sounds": map_ambient_row,
        "faction_biome_updates": faction_biome_updates,
        "arena_view_mapping": view_mapping,
        "arena_presentation_donor": args.arena_presentation_donor,
        "arena_presentation_updates": arena_presentation_updates,
        "cloned_arena_views": len(cloned_views),
        "cloned_arena_info_rows": len(cloned_arenas),
        "template": template_report,
        "unity_resource_checks": unity_checks,
        "validation_failures": failures,
        "observed_runtime_failure": {
            "status": "requires_runtime_material_prime",
            "date": "2026-05-20",
            "player_log": [
                "[Config Error] [MapGen] Can't find water for biome 'Swamp'",
                "KeyNotFoundException: The given key '8' was not present in the dictionary.",
                "at beg.kvs(Hex.Map.Map)",
            ],
            "interpretation": (
                "The first scratch Core JSON omitted generator_config waterForBiome and generator_environment_assets "
                "rows. After those were added, the map-view renderer still lacked tile key 8 unless the runtime proof "
                "primed SoTerrainMaterial before beg.kvs(Map). The generator-side rows are data-owned in Core.zip, but "
                "the render dictionary is built from the serialized SoTerrainMaterial resource."
            ),
        },
        "runtime_blockers": [
            "SoTerrainMaterial.Biome is serialized in Unity Resources/configs/TerrainMaterials; the scratch Core.zip cannot add the target tileCode entry that beg..ctor uses to build its render dictionary, so a real Swamp lane still needs a Unity resource change or the current constructor-prefix runtime material registration hook.",
            "May 20 static tracing showed beg..ctor builds the renderer lookup from SoTerrainMaterial.biomes before beg.kvs(Map) consumes it. Homm3SwampAutumnTintProof must prime SoTerrainMaterial from a beg constructor prefix; a beg.kvs(Map) prefix is too late except as a validation guard.",
            "Current bkr.WeightsArray is range-checked to indexes 0..7 for tilesets within one EnvironmentAssets biome. Keep each cloned biome to at most eight tilesets unless a native patch replaces that selector.",
        ],
    }
    report_path = out_dir / "spike_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_markdown_report(out_dir / "spike_report.md", report)
    return report


def write_markdown_report(path: Path, report: dict[str, Any]) -> None:
    status = "PASS" if not report["validation_failures"] else "FAIL"
    lines = [
        f"# {report['target']} Biome Proof Spike",
        "",
        f"- Static Core data status: {status}",
        f"- Source biome cloned: {report['source']}",
        f"- Scratch Core: `{report['core_output']}`",
        f"- RMG template: `{report['template']['output']}`",
        f"- Tile id: {report['target_tile']['id']}",
        f"- Water id: {report['target_water']['id']} using donor material `{report['target_water'].get('material')}`",
        f"- Generator water mapping: `{report['generator_water_mapping']['key']}` -> `{report['generator_water_mapping']['val']}`",
        f"- EnvironmentAssets biome row cloned: {report['generator_environment_biome']}",
        f"- EnvironmentAssets presentation donor: {report.get('environment_presentation_donor') or 'None'}",
        f"- Faction biome updates: {report['faction_biome_updates']}",
        f"- Observed runtime status: {report['observed_runtime_failure']['status']}",
        f"- Arena views cloned: {report['cloned_arena_views']}",
        f"- Arena info rows cloned: {report['cloned_arena_info_rows']}",
        f"- Arena presentation donor: {report.get('arena_presentation_donor') or 'None'}",
        "",
        "## Validation Failures",
        "",
    ]
    failures = report["validation_failures"]
    lines.extend([f"- {failure}" for failure in failures] or ["- None"])
    lines.extend(
        [
            "",
            "## Unity Resource Checks",
            "",
            f"- TerrainMaterials.asset exists: {report['unity_resource_checks']['terrain_material_asset_exists']}",
            f"- Target terrain material present: {report['unity_resource_checks']['target_terrain_material_present']}",
            f"- Missing reused arena scenes: {report['unity_resource_checks']['scene_missing']}",
            f"- Missing reused arena tile sets: {report['unity_resource_checks']['tile_set_missing']}",
            "",
            "## Runtime Blockers",
            "",
        ]
    )
    lines.extend([f"- {item}" for item in report["runtime_blockers"]])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--source", default="Autumn")
    parser.add_argument("--target", default="Swamp")
    parser.add_argument("--faction", default="homm3_fortress")
    parser.add_argument(
        "--environment-presentation-donor",
        default=None,
        help=(
            "Optional existing biome whose generator_environment_assets presentation should be copied into "
            "the cloned target row while preserving the target sid."
        ),
    )
    parser.add_argument(
        "--arena-presentation-donor",
        default=None,
        help=(
            "Optional existing biome whose arena view scenes/tile sets should be copied into cloned target "
            "arena views while preserving target ids and biome."
        ),
    )
    parser.add_argument("--template-dir", type=Path, default=DEFAULT_TEMPLATE_DIR)
    parser.add_argument("--template-name", default="Blitz.rmg.json")
    parser.add_argument(
        "--unity-assets",
        type=Path,
        default=DEFAULT_UNITY_EXPORT,
        help="AssetRipper ExportedProject/Assets root used only for static resource existence checks.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "artifacts" / "custom_biome_spike_swamp",
    )
    parser.add_argument("--clean", action="store_true", help="Delete out-dir before writing the spike artifact.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        if args.clean and args.out_dir.exists():
            shutil.rmtree(args.out_dir)
        report = build_spike(args)
    except SpikeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {report['core_output']}")
    print(f"wrote {report['template']['output']}")
    print(f"wrote {args.out_dir / 'spike_report.json'}")
    if report["validation_failures"]:
        for failure in report["validation_failures"]:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print(
        "static Core data clone passed; map-view tile key 8 still requires the runtime material-prime proof hook "
        "or a serialized SoTerrainMaterial resource change"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
