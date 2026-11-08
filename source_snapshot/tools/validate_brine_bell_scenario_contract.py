#!/usr/bin/env python3
"""Validate The Brine Bell generated-artifact contract."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

MAP_SID = "h3_brine_bell"
MISSION_ID = "brine_bell"
SCHEMA = "homm3.olden_brine_bell.v1"
POLICY_ID = "salt_flats_32_capture_brinehold"
ARTIFACT_ROOT = Path("artifacts") / "campaign_port_poc" / "brine_bell"
BUILDER = Path("experiments") / "campaign_port_poc" / "build_brine_bell_scenario.py"
INSTALLER = Path("tools") / "install_brine_bell_scenario.py"
PROFILE = Path("scenarios") / "brine_bell" / "scenario.profile.json"
MAP_SIZE = 32
VIEW_SEC_SIZE = 2
ENEMY_KEEP_ENTITY = f"{MISSION_ID}_capture_brinehold"
ENEMY_CITY_HERO = "homm3_cove_hero_1"
ENEMY_FIELD_HERO = "homm3_cove_hero_3"
PIRATE_SQUAD_SID = f"{MISSION_ID}_h3_pirate_x3"
PIRATE_VALUE_BUDGET = 3 * 299

REQUIRED_BUILDER_TOKENS = [
    f'MAP_SID = "{MAP_SID}"',
    f'SCHEMA = "{SCHEMA}"',
    f'POLICY_ID = "{POLICY_ID}"',
    "MAP_SIZE = 32",
    "VIEW_SECTOR_SIZE = 16",
    "ObjectCaptureEntity",
    "GameVictory",
    "BeforeIamVsHero",
    "SquadInteraction",
    "SquadKill",
    "counter_equality_in_days_condition",
    "Zone 1x1",
    'PLAYER_FACTION = "homm3_tower"',
    'ENEMY_FACTION = "homm3_cove"',
    'ENEMY_CITY_HERO = "homm3_cove_hero_1"',
    'ENEMY_HERO = "homm3_cove_hero_3"',
    'PIRATE_UNIT_SID = "h3_pirate"',
    "maps_root_custom_only",
    "spawnHero",
    "propGrowthUnits",
    'sides": ""',
    '"mapWinConditions": []',
]

FORBIDDEN_BUILDER_TOKENS = [
    "Story_maps",
]

REQUIRED_INSTALLER_TOKENS = [
    f'MAP_SID = "{MAP_SID}"',
    'INSTALL_DESTINATION_POLICY = "maps_root_custom_only"',
    "Story_maps",
    "Core.zip",
]


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_sources(repo_root: Path, errors: list[str]) -> None:
    builder = repo_root / BUILDER
    installer = repo_root / INSTALLER
    profile = repo_root / PROFILE
    require(builder.is_file(), f"missing builder {BUILDER}", errors)
    require(installer.is_file(), f"missing installer {INSTALLER}", errors)
    require(profile.is_file(), f"missing profile {PROFILE}", errors)
    if builder.is_file():
        text = builder.read_text(encoding="utf-8")
        for token in REQUIRED_BUILDER_TOKENS:
            require(token in text, f"builder missing token {token!r}", errors)
        for token in FORBIDDEN_BUILDER_TOKENS:
            require(token not in text, f"builder must not mention {token!r}", errors)
    if installer.is_file():
        text = installer.read_text(encoding="utf-8")
        for token in REQUIRED_INSTALLER_TOKENS:
            require(token in text, f"installer missing token {token!r}", errors)
    if profile.is_file():
        doc = json.loads(profile.read_text(encoding="utf-8"))
        require(doc.get("mapSid") == MAP_SID, "profile mapSid pin", errors)
        require(doc.get("id") == MISSION_ID, "profile id pin", errors)
        require(doc.get("victoryMode") == "capture_keep", "profile victoryMode pin", errors)


def validate_artifact(repo_root: Path, errors: list[str]) -> dict[str, Any] | None:
    root = repo_root / ARTIFACT_ROOT
    map_path = root / "maps" / f"{MAP_SID}.map"
    sidecar = root / "maps" / f"{MAP_SID}.json"
    manifest_path = root / "install_manifest.json"
    overlay = root / "core_overlay"
    require(map_path.is_file(), f"missing map {map_path}", errors)
    require(sidecar.is_file(), f"missing sidecar {sidecar}", errors)
    require(manifest_path.is_file(), f"missing manifest {manifest_path}", errors)
    require(overlay.is_dir(), f"missing core overlay {overlay}", errors)
    if not manifest_path.is_file():
        return None

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("schema") == SCHEMA, "manifest schema pin", errors)
    require(manifest.get("mapSid") == MAP_SID, "manifest mapSid pin", errors)
    require(manifest.get("policyId") == POLICY_ID, "manifest policyId pin", errors)
    require(
        manifest.get("installDestinationPolicy") == "maps_root_custom_only",
        "manifest install policy pin",
        errors,
    )
    require(manifest.get("coreOverlayRequired") is True, "core overlay must be required", errors)

    sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))
    import port_homecoming_poc as poc

    container = poc.read_olden_map_container(map_path)
    require(len(container.chunks) == 4, "map must have 4 chunks", errors)
    if len(container.chunks) != 4:
        return None

    meta = container.chunks[0]
    map_data = container.chunks[1]
    props = map_data.get("objectsProperties") or {}
    quests = container.chunks[3]

    require(map_data.get("sizeX_") == MAP_SIZE, f"sizeX_ must be {MAP_SIZE}", errors)
    require(map_data.get("sizeZ_") == MAP_SIZE, f"sizeZ_ must be {MAP_SIZE}", errors)
    require(MAP_SIZE % 16 == 0, "map size must be a multiple of view sector 16", errors)
    views = map_data.get("views") or []
    require(
        len(views) == 1
        and isinstance(views[0], dict)
        and views[0].get("secSizeX") == VIEW_SEC_SIZE
        and views[0].get("secSizeZ") == VIEW_SEC_SIZE,
        f"views must be exact {VIEW_SEC_SIZE}x{VIEW_SEC_SIZE} for {MAP_SIZE} map",
        errors,
    )
    settings = map_data.get("settings")
    require(isinstance(settings, dict), "map settings object required", errors)
    if isinstance(settings, dict):
        require(settings.get("mapWinConditions") == [], "settings.mapWinConditions must be []", errors)
        require(settings.get("isScenario") is True, "settings.isScenario must be true", errors)
    require(isinstance(meta.get("campaignInfo"), dict), "meta.campaignInfo must be an object", errors)

    levels = map_data.get("levelsMap") or []
    require(len(levels) == MAP_SIZE * MAP_SIZE, "levelsMap length mismatch", errors)
    require(all(v == 0 for v in levels), "levelsMap must be all 0 (pathable)", errors)
    require(all(v == 0 for v in (map_data.get("climbsMap") or [])), "climbsMap must be all 0", errors)
    require(all(v == 0 for v in (map_data.get("waterMap") or [])), "waterMap must be all 0", errors)
    tiles = map_data.get("tilesMap") or []
    require(set(tiles).issubset({2, 7}), f"tiles must be Sand(2)/Dirt(7) only, found {sorted(set(tiles))}", errors)

    object_sids: set[str] = set()
    for group in map_data.get("objects") or []:
        if not isinstance(group, dict):
            continue
        ids = group.get("ids")
        if not isinstance(ids, list):
            continue
        sid = str(group.get("sid"))
        object_sids.add(sid)
        for key, values in group.items():
            if key == "sid" or not isinstance(values, list):
                continue
            require(
                len(values) == len(ids),
                f"object group {sid!r} list {key!r} length {len(values)} != ids {len(ids)}",
                errors,
            )

    require("city-spawner" in object_sids, "missing city-spawner", errors)
    require("fx_quest_mark_gold_01" in object_sids, "missing gold FX decor", errors)
    require("random-squad" in object_sids, "missing pirate random-squad", errors)
    require("hero-spawner" in object_sids, "missing Captain Rime hero-spawner", errors)

    cities = [r for r in (props.get("propCities") or []) if isinstance(r, dict)]
    require(
        any(r.get("factionSid") == "homm3_tower" and r.get("spawnHero") is True for r in cities),
        "player city must be homm3_tower with spawnHero",
        errors,
    )
    require(
        any(r.get("factionSid") == "homm3_cove" for r in cities),
        "enemy city must be homm3_cove",
        errors,
    )
    hero_sids = [
        str(r.get("heroSid"))
        for r in (props.get("propHeroes") or [])
        if isinstance(r, dict) and r.get("heroSid")
    ]
    require(len(hero_sids) == len(set(hero_sids)), f"duplicate propHeroes heroSid values: {hero_sids}", errors)
    require(ENEMY_CITY_HERO in hero_sids, "enemy city garrison hero missing", errors)
    require(ENEMY_FIELD_HERO in hero_sids, "Captain Rime field hero missing", errors)
    entities = {
        (r.get("type"), r.get("id")): r.get("sid")
        for r in (props.get("propEntities") or [])
        if isinstance(r, dict)
    }
    require(
        ENEMY_KEEP_ENTITY in entities.values(),
        f"enemy keep missing propEntities sid {ENEMY_KEEP_ENTITY}",
        errors,
    )

    markers = [r for r in (map_data.get("markers") or []) if isinstance(r, dict)]
    zone_markers = [r for r in markers if r.get("sid") == "Zone 1x1"]
    require(len(zone_markers) == 3, f"expected 3 Zone 1x1 bell caches, found {len(zone_markers)}", errors)
    before = {
        (r.get("type"), r.get("id")): r
        for r in (props.get("propActionsBefore") or [])
        if isinstance(r, dict)
    }
    for zm in zone_markers:
        mid = zm.get("id")
        row = before.get((1, mid)) or {}
        require(row.get("sides") == "", f"zone {mid} Dialog sides must be empty string", errors)
        require("computerActivate" not in row, f"zone {mid} must not set computerActivate", errors)
        require(row.get("repeat") is False, f"zone {mid} action must be one-shot", errors)

    prop_markers = {
        r.get("id"): r for r in (props.get("propMarkers") or []) if isinstance(r, dict)
    }
    for zm in zone_markers:
        mid = zm.get("id")
        require(prop_markers.get(mid, {}).get("isDelete") is True, f"zone {mid} isDelete", errors)

    squad_blob = json.dumps(props.get("propRandomSquads") or [])
    require(PIRATE_SQUAD_SID in squad_blob, "pirate squad overlay sid missing from propRandomSquads", errors)
    require(
        any(
            isinstance(r, dict) and r.get("aiIgnore") is True
            for r in (props.get("propAiIntetations") or [])
        ),
        "pirate landing must set aiIgnore",
        errors,
    )

    quest_blob = json.dumps(quests)
    for token in (
        "ObjectCaptureEntity",
        "GameVictory",
        ENEMY_KEEP_ENTITY,
        "BeforeIamVsHero",
        "SquadInteraction",
        "SquadKill",
        "CounterEqualityInDays",
    ):
        require(token in quest_blob, f"quest script missing {token}", errors)

    interruptions = quests.get("interruptions") or []
    require(
        any(
            isinstance(r, dict)
            and r.get("interruption") == "BeforeIamVsHero"
            and ENEMY_HERO_IN_INTERRUPTION(r)
            for r in interruptions
        ),
        "missing Captain Rime BeforeIamVsHero interruption",
        errors,
    )

    spawns = ((meta.get("spawns") or {}).get("spawns")) or []
    require(len(spawns) == 2, "meta.spawns must list human + AI", errors)
    require(
        any(isinstance(r, dict) and r.get("owner") == 1 and r.get("factionSid") == "homm3_tower" for r in spawns),
        "human spawn must be Tower",
        errors,
    )
    require(
        any(isinstance(r, dict) and r.get("owner") == 2 and r.get("factionSid") == "homm3_cove" for r in spawns),
        "AI spawn must be Cove",
        errors,
    )

    squad_overlay = (
        overlay
        / "DB"
        / "squads"
        / "squads_custom_maps"
        / "BrineBell"
        / f"{PIRATE_SQUAD_SID}.json"
    )
    require(squad_overlay.is_file(), f"missing squad overlay {squad_overlay}", errors)
    if squad_overlay.is_file():
        squad_doc = json.loads(squad_overlay.read_text(encoding="utf-8"))
        row = (squad_doc.get("array") or [None])[0] or {}
        base_units = ((row.get("baseSquad") or {}).get("units")) or []
        require(
            any(isinstance(u, dict) and u.get("s") == "h3_pirate" and u.get("v") == PIRATE_VALUE_BUDGET for u in base_units),
            "squad overlay pirate value budget mismatch",
            errors,
        )

    dialog_dir = overlay / "DB" / "dialogs" / "dialogs" / "custom_maps" / "BrineBell"
    required_dialogs = [
        f"{MISSION_ID}_briefing",
        f"{MISSION_ID}_clapper",
        f"{MISSION_ID}_rope",
        f"{MISSION_ID}_crown",
        f"{MISSION_ID}_pirate_landing",
        f"{MISSION_ID}_captain_taunt",
        f"{MISSION_ID}_victory",
        f"{MISSION_ID}_harbor_subsidy",
    ]
    for dialog_sid in required_dialogs:
        require(
            (dialog_dir / f"{dialog_sid}.json").is_file(),
            f"missing dialog {dialog_sid}",
            errors,
        )

    quickstart = overlay / "DB" / "quickStart.json"
    require(quickstart.is_file(), "missing quickStart overlay", errors)
    if quickstart.is_file():
        qs = json.loads(quickstart.read_text(encoding="utf-8"))
        require(MAP_SID in (qs.get("scenarios") or []), "quickStart must list mapSid", errors)

    world = manifest.get("world") or {}
    require(isinstance(world.get("caches"), dict) and len(world["caches"]) == 3, "manifest caches", errors)
    require((world.get("enemyKeep") or {}).get("entitySid") == ENEMY_KEEP_ENTITY, "manifest keep entity", errors)

    return manifest


def ENEMY_HERO_IN_INTERRUPTION(row: dict[str, Any]) -> bool:
    return "homm3_cove_hero_3" in (row.get("p") or [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    errors: list[str] = []

    validate_sources(repo_root, errors)
    if not args.skip_generate:
        builder = repo_root / BUILDER
        result = subprocess.run([sys.executable, str(builder)], cwd=str(repo_root), check=False)
        if result.returncode != 0:
            errors.append("builder failed before artifact validation")

    manifest = validate_artifact(repo_root, errors)
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "mapSid": MAP_SID,
                "schema": SCHEMA,
                "policyId": POLICY_ID,
                "proofBoundary": (manifest or {}).get("proofBoundary"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
