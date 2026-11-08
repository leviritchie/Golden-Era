#!/usr/bin/env python3
"""Fail-closed validator for HoMM3 custom city building functions.

Prerequisites, construction-tree layout and buildOrders are owned by
tools/release_port/homm3_city_building_tree.py and checked by
validate_homm3_city_building_tree_contract.py, which this validator also runs.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release_port"))
sys.path.insert(0, str(ROOT / "tools"))

from apply_release_core_overlay import (  # noqa: E402
    CITY_BUILDING_MECHANICS_BY_FACTION,
    HOMM3_MAGE_GUILD_LEVEL_CAPS_BY_FACTION,
    city_building_mechanic_bonuses,
    collect_city_building_config_rows,
    first_array_item,
    homm3_native_growth_bonuses,
)
from validate_city_construction_tree_layout import construction_tree_layout_errors  # noqa: E402
from validate_homm3_city_building_tree_contract import city_errors as building_tree_city_errors  # noqa: E402
from validate_custom_faction_manifests import (  # noqa: E402
    DEFAULT_MANIFEST_DIR,
    Validation,
    core_overlay_enabled,
    load_json,
)

DEFAULT_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)


def validate_faction(
    zf: zipfile.ZipFile,
    manifest: dict[str, Any],
    v: Validation,
) -> None:
    faction = manifest["identity"]["factionSid"]
    member = (manifest.get("coreOverlay") or {}).get("cityLogic")
    if not isinstance(member, str):
        v.error(f"{faction}: missing coreOverlay.cityLogic")
        return
    if member not in zf.namelist():
        v.error(f"{faction}: cityLogic member missing from Core: {member}")
        return
    doc = json.loads(zf.read(member).decode("utf-8-sig"))
    rows = {row["sid"]: row for row in collect_city_building_config_rows(doc) if isinstance(row.get("sid"), str)}

    specs = CITY_BUILDING_MECHANICS_BY_FACTION.get(faction, {})
    for building_sid, spec in specs.items():
        row = rows.get(building_sid)
        if row is None:
            v.error(f"{faction}: mechanics building missing from city: {building_sid}")
            continue
        # Native form (2026-10-01): non-growth spec bonuses + per-dwelling growth percent.
        expected = city_building_mechanic_bonuses(manifest, {**spec, "growth": ()})
        expected.extend(homm3_native_growth_bonuses(first_array_item(doc), manifest, spec))
        live = row.get("bonuses") if isinstance(row.get("bonuses"), list) else []
        if json.dumps(live, sort_keys=True) != json.dumps(expected, sort_keys=True):
            v.error(f"{faction}: {building_sid} bonuses mismatch live={live} expected={expected}")

    if faction == "homm3_stronghold":
        item = first_array_item(doc)
        if isinstance(item, dict):
            artifact = item.get("artifactChangers") if isinstance(item.get("artifactChangers"), list) else []
            if any(isinstance(row, dict) and row.get("sid") == "Build_Lyceum" for row in artifact):
                v.error(f"{faction}: Mess Hall Build_Lyceum still lives under artifactChangers")
            banks = item.get("banks") if isinstance(item.get("banks"), list) else []
            if not any(isinstance(row, dict) and row.get("sid") == "Build_Lyceum" for row in banks):
                v.error(f"{faction}: Mess Hall Build_Lyceum missing from banks (its growth is a native bank bonus)")

    mg_cap = HOMM3_MAGE_GUILD_LEVEL_CAPS_BY_FACTION.get(faction)
    mg = rows.get("Build_Magic_Guild")
    if mg_cap is not None and mg is not None:
        levels = mg.get("parametersPerLevel") if isinstance(mg.get("parametersPerLevel"), list) else []
        names = mg.get("names") if isinstance(mg.get("names"), list) else []
        live_count = len(levels) if levels else len(names)
        if live_count > mg_cap:
            v.error(f"{faction}: Mage Guild has {live_count} levels, cap is {mg_cap}")

    for line in manifest.get("additionalRecruitmentLines") or []:
        if not isinstance(line, dict):
            continue
        city_sid = line.get("cityBuildingSid")
        if not isinstance(city_sid, str):
            v.error(f"{faction}: additionalRecruitmentLines entry missing cityBuildingSid")
            continue
        if city_sid not in rows:
            v.error(f"{faction}: additional recruitment building missing from city: {city_sid}")
        for preset in (
            "DB/buildings_constructions/default_buildings_construction.json",
            "DB/buildings_constructions/extra_rich_buildings_construction.json",
            "DB/buildings_constructions/full_buildings_construction.json",
        ):
            if preset not in zf.namelist():
                continue
            blob = zf.read(preset).decode("utf-8-sig")
            if city_sid not in blob:
                v.error(f"{faction}: {city_sid} missing from construction preset {preset}")

    occupied: dict[tuple[int, int], str] = {}
    for building_sid, row in rows.items():
        levels = row.get("parametersPerLevel")
        if not isinstance(levels, list):
            continue
        for level_index, level in enumerate(levels, start=1):
            if not isinstance(level, dict):
                continue
            node = level.get("nodePos")
            if not isinstance(node, dict):
                continue
            try:
                coord = (int(node["xPos"]), int(node["yPos"]))
            except (KeyError, TypeError, ValueError):
                v.error(f"{faction}: {building_sid}:L{level_index} has invalid nodePos {node!r}")
                continue
            owner = f"{building_sid}:L{level_index}"
            prior = occupied.get(coord)
            if prior is not None:
                v.error(f"{faction}: construction-tree nodePos collision at {coord}: {prior} and {owner}")
            else:
                occupied[coord] = owner

    city_item = first_array_item(doc)
    if not isinstance(city_item, dict):
        v.error(f"{faction}: city document has no array item for construction-tree layout")
    else:
        for message in construction_tree_layout_errors(city_item):
            v.error(f"{faction}: construction-tree layout: {message}")
        for message in building_tree_city_errors(f"{faction}_city", faction, city_item):
            v.error(f"{faction}: building tree: {message}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    args = parser.parse_args()
    v = Validation()
    manifests = [
        load_json(path)
        for path in sorted(args.manifest_dir.glob("homm3_*.json"))
        if path.is_file()
    ]
    with zipfile.ZipFile(args.core) as zf:
        for manifest in manifests:
            if not isinstance(manifest, dict) or not core_overlay_enabled(manifest):
                continue
            validate_faction(zf, manifest, v)
    print(f"homm3 city building contracts: errors={len(v.errors)}")
    if v.warnings:
        print(f"warnings: {len(v.warnings)}")
    for message in v.errors:
        print(f"ERROR: {message}")
    for message in v.warnings:
        print(f"WARN: {message}")
    return 1 if v.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
