#!/usr/bin/env python3
"""Validate The Emberwatch Signal generated-artifact contract."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

MAP_SID = "h3_emberwatch_signal"
MISSION_ID = "emberwatch_signal"
SCHEMA = "homm3.olden_emberwatch_signal.v1"
POLICY_ID = "ridge_trail_48_capture_keep"
ARTIFACT_ROOT = Path("artifacts") / "campaign_port_poc" / "emberwatch_signal"
BUILDER = Path("experiments") / "campaign_port_poc" / "build_emberwatch_signal_scenario.py"
INSTALLER = Path("tools") / "install_emberwatch_signal_scenario.py"
MAP_SIZE = 48
ENEMY_KEEP_ENTITY = f"{MISSION_ID}_emberwatch_keep"
PLAYER_HERO_SID = "homm3_castle_hero_1"
ENEMY_HERO_SID = "homm3_stronghold_hero_2"
WOLF_SQUAD_SID = f"{MISSION_ID}_h3_wolf_rider_x3"
GUARD_UNIT_SID = "h3_wolf_rider"

REQUIRED_BUILDER_TOKENS = [
    f'MAP_SID = "{MAP_SID}"',
    f'SCHEMA = "{SCHEMA}"',
    f'POLICY_ID = "{POLICY_ID}"',
    "MAP_SIZE = 48",
    "ObjectCaptureEntity",
    "GameVictory",
    "BeforeIamVsHero",
    "SquadInteraction",
    "SquadKill",
    "counter_equality_in_days_condition",
    "Zone 1x1",
    'ENEMY_KEEP_ENTITY = f"{MISSION_ID}_emberwatch_keep"',
    f'WOLF_UNIT_SID = "{GUARD_UNIT_SID}"',
    'PLAYER_FACTION = "homm3_castle"',
    'ENEMY_FACTION = "homm3_stronghold"',
    "maps_root_custom_only",
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
    require(builder.is_file(), f"missing builder {BUILDER}", errors)
    require(installer.is_file(), f"missing installer {INSTALLER}", errors)
    if builder.is_file():
        text = builder.read_text(encoding="utf-8")
        for token in REQUIRED_BUILDER_TOKENS:
            require(token in text, f"builder missing token {token!r}", errors)
    if installer.is_file():
        text = installer.read_text(encoding="utf-8")
        for token in REQUIRED_INSTALLER_TOKENS:
            require(token in text, f"installer missing token {token!r}", errors)


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
    quest_script = container.chunks[3]
    props = map_data.get("objectsProperties") or {}

    require(map_data.get("sizeX_") == MAP_SIZE, f"sizeX_ must be {MAP_SIZE}", errors)
    require(map_data.get("sizeZ_") == MAP_SIZE, f"sizeZ_ must be {MAP_SIZE}", errors)
    require(len(map_data.get("tilesMap") or []) == MAP_SIZE * MAP_SIZE, "tilesMap length", errors)

    spawns = (meta.get("spawns") or {})
    require(spawns.get("playersCount") == 2, "requires 2-player spawns", errors)

    entity_sids = {row.get("sid") for row in props.get("propEntities") or [] if isinstance(row, dict)}
    require(ENEMY_KEEP_ENTITY in entity_sids, f"missing enemy keep entity {ENEMY_KEEP_ENTITY}", errors)

    quest_blob = json.dumps(quest_script)
    for token in ("ObjectCaptureEntity", "GameVictory", "BeforeIamVsHero", "SquadKill"):
        require(token in quest_blob, f"quest script missing {token}", errors)

    main_quests = [q for q in quest_script.get("quests") or [] if q.get("main")]
    require(len(main_quests) == 1, "exactly one main quest", errors)
    if main_quests:
        sub_count = len(main_quests[0].get("subQuests") or [])
        require(sub_count >= 5, f"main quest needs >=5 sub-objectives; got {sub_count}", errors)

    squad_overlay = overlay / "DB" / "squads" / "squads_custom_maps" / "EmberwatchSignal" / f"{WOLF_SQUAD_SID}.json"
    require(squad_overlay.is_file(), f"missing wolf squad overlay {squad_overlay}", errors)

    dialog_dir = overlay / "DB" / "dialogs" / "dialogs" / "custom_maps" / "EmberwatchSignal"
    require(dialog_dir.is_dir(), f"missing dialog dir {dialog_dir}", errors)
    if dialog_dir.is_dir():
        require(len(list(dialog_dir.glob("*.json"))) >= 7, "expected >=7 dialog files", errors)

    hero_rows = [
        row.get("heroSid")
        for row in (props.get("propHeroes") or [])
        if isinstance(row, dict) and row.get("heroSid")
    ]
    require(
        hero_rows.count(ENEMY_HERO_SID) == 1,
        f"enemy hero must appear on exactly one map object; got {hero_rows.count(ENEMY_HERO_SID)}",
        errors,
    )
    require(PLAYER_HERO_SID in hero_rows, "player hero missing from propHeroes", errors)

    guarded_rows = [
        row
        for row in (props.get("propSquads") or [])
        if isinstance(row, dict) and row.get("unitProps")
    ]
    require(len(guarded_rows) == 1, "wolf pass needs exactly one propSquads row", errors)
    if guarded_rows:
        unit = (guarded_rows[0].get("unitProps") or [None])[0] or {}
        require(unit.get("sid") == GUARD_UNIT_SID, f"guard unit must be {GUARD_UNIT_SID}", errors)

    core_zip = poc.OLDEN_CORE_ZIP
    if core_zip.is_file():
        import zipfile

        with zipfile.ZipFile(core_zip) as core:
            names = set(core.namelist())
        logic_path = f"DB/units/units_logics/homm3_stronghold/{GUARD_UNIT_SID}_l.json"
        require(
            logic_path in names,
            f"guard unit logic missing from Core.zip: {logic_path}",
            errors,
        )
        require(
            "DB/units/units_logics/homm3_stronghold/h3_wolf_l.json" not in names,
            "do not reference fictional h3_wolf; use h3_wolf_rider",
            errors,
        )

    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    errors: list[str] = []
    validate_sources(repo_root, errors)

    if not args.skip_generate:
        result = subprocess.run(
            [sys.executable, str(repo_root / BUILDER), "--out-root", str(repo_root / ARTIFACT_ROOT)],
            check=False,
        )
        require(result.returncode == 0, "builder failed", errors)

    validate_artifact(repo_root, errors)
    if errors:
        print("emberwatch signal contract validation FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "mapSid": MAP_SID, "schema": SCHEMA}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
