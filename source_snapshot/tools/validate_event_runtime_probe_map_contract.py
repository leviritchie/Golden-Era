#!/usr/bin/env python3
"""Validate the Event Runtime Probe generated-artifact contract."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

MAP_SID = "h3_event_runtime_probe"
MISSION_ID = "event_runtime_probe"
SCHEMA = "homm3.olden_event_runtime_probe.v1"
POLICY_ID = "compact_grass_lab_32_north_stations"
ARTIFACT_ROOT = Path("artifacts") / "campaign_port_poc" / "event_runtime_probe"
BUILDER = Path("experiments") / "campaign_port_poc" / "build_event_runtime_probe_map.py"
INSTALLER = Path("tools") / "install_event_runtime_probe_map.py"
MAP_SIZE = 32
GUARD_UNIT_SID = "h3_pikeman"
GUARD_COUNT = 1
GUARD_VALUE_BUDGET = 80
GUARD_SQUAD_SID = f"{MISSION_ID}_h3_pikeman_x{GUARD_COUNT}"

REQUIRED_BUILDER_TOKENS = [
    f'MAP_SID = "{MAP_SID}"',
    f'SCHEMA = "{SCHEMA}"',
    f'POLICY_ID = "{POLICY_ID}"',
    "MAP_SIZE = 32",
    "CounterEqualityInDays",
    "AnyStartTurn",
    "CounterPlus",
    "SquadInteraction",
    "SquadKill",
    "propSquads",
    "aiIgnore",
    "persistent_object",
    "one_shot_no_host_delete",
    "maps_root_custom_only",
    'GUARD_UNIT_SID = "h3_pikeman"',
    "GUARD_SQUAD_SID",
    'PLAYER_FACTION = "dungeon"',
    "Olden +Y = north",
    "spawnHero",
    "propGrowthUnits",
    "Zone 1x1",
    'sides": ""',
    "type1_zone_marker",
    "Can not find property random squad",
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


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def validate_sources(repo_root: Path, errors: list[str]) -> None:
    builder = repo_root / BUILDER
    installer = repo_root / INSTALLER
    require(builder.is_file(), f"missing builder {BUILDER}", errors)
    require(installer.is_file(), f"missing installer {INSTALLER}", errors)
    if builder.is_file():
        text = _read(builder)
        for token in REQUIRED_BUILDER_TOKENS:
            require(token in text, f"builder missing token {token!r}", errors)
        for token in FORBIDDEN_BUILDER_TOKENS:
            require(token not in text, f"builder must not mention {token!r}", errors)
    if installer.is_file():
        text = _read(installer)
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
    require(len(container.chunks) == 4, "probe map must have 4 chunks", errors)
    if len(container.chunks) != 4:
        return None
    map_data = container.chunks[1]
    props = map_data.get("objectsProperties") or {}
    quests = container.chunks[3].get("quests") or []

    require(map_data.get("sizeX_") == MAP_SIZE, f"sizeX_ must be {MAP_SIZE}", errors)
    require(map_data.get("sizeZ_") == MAP_SIZE, f"sizeZ_ must be {MAP_SIZE}", errors)
    tiles = map_data.get("tilesMap") or []
    levels = map_data.get("levelsMap") or []
    require(len(tiles) == MAP_SIZE * MAP_SIZE, "tilesMap length must match 32x32", errors)
    require(len(levels) == MAP_SIZE * MAP_SIZE, "levelsMap length must match 32x32", errors)
    require(all(v == 0 for v in (map_data.get("waterMap") or [])), "lab waterMap must be all 0", errors)
    require(all(v == 0 for v in levels), "lab levelsMap must be all 0 (pathable; no stranded city plateau)", errors)
    require(all(v == 0 for v in (map_data.get("climbsMap") or [])), "lab climbsMap must be all 0", errors)

    # Object-group parallel arrays must stay lockstep (load crash: MapObjects.oqf).
    object_sids: set[str] = set()
    for group in map_data.get("objects") or []:
        if not isinstance(group, dict):
            continue
        ids = group.get("ids")
        if not isinstance(ids, list):
            continue
        sid = group.get("sid")
        object_sids.add(str(sid))
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
    require("prison" in object_sids, "missing persistent prison host (Guardhouse stand-in)", errors)
    require("random-squad" in object_sids, "missing guarded random-squad", errors)
    require("hero-spawner" in object_sids, "missing colocated enemy hero-spawner station", errors)
    # Player start still comes from city spawnHero (Thirst). hero-spawner is only the
    # colocated EVENT+hero engagement station (tile engage, not adjacent ZoC).
    require(
        object_sids
        == {"city-spawner", "fx_quest_mark_gold_01", "hero-spawner", "prison", "random-squad"},
        f"expected only lab object SIDs, found {sorted(object_sids)}",
        errors,
    )

    marker_ids = ((manifest.get("stations") or {}).get("markerIds")) or {}
    object_ids = ((manifest.get("stations") or {}).get("objectIds")) or {}
    markers = {row.get("id"): row for row in (map_data.get("markers") or []) if isinstance(row, dict)}
    prop_markers = {
        row.get("id"): row
        for row in (props.get("propMarkers") or [])
        if isinstance(row, dict)
    }
    before = {
        (row.get("type"), row.get("id")): row
        for row in (props.get("propActionsBefore") or [])
        if isinstance(row, dict)
    }
    for key in ("info", "oneshot", "avalanche"):
        mid = marker_ids.get(key)
        require(isinstance(mid, int), f"manifest missing markerIds.{key}", errors)
        if not isinstance(mid, int):
            continue
        require(mid in markers and markers[mid].get("sid") == "Zone 1x1", f"{key} must be Zone 1x1", errors)
        require(prop_markers.get(mid, {}).get("isActivate") is True, f"{key} propMarkers.isActivate", errors)
        row = before.get((1, mid)) or {}
        require(row.get("sides") == "", f"{key} Dialog sides must be empty string (story-map proven)", errors)
        require("computerActivate" not in row, f"{key} must not set computerActivate", errors)
    oneshot_id = marker_ids.get("oneshot")
    avalanche_id = marker_ids.get("avalanche")
    if isinstance(oneshot_id, int):
        require(prop_markers.get(oneshot_id, {}).get("isDelete") is True, "oneshot isDelete must be true", errors)
        require(before.get((1, oneshot_id), {}).get("repeat") is False, "oneshot action repeat must be false", errors)
    if isinstance(avalanche_id, int):
        require(prop_markers.get(avalanche_id, {}).get("isDelete") is False, "avalanche isDelete must be false", errors)
        require(before.get((1, avalanche_id), {}).get("repeat") is True, "avalanche action repeat must be true", errors)
    host_id = object_ids.get("guardhouse")
    if isinstance(host_id, int):
        host_before = before.get((0, host_id)) or {}
        require(host_before.get("repeat") is False, "persistent prison dialog is one-shot", errors)
        require(host_before.get("sides") == "", "persistent prison Dialog sides must be empty string", errors)
        require("computerActivate" not in host_before, "persistent prison must not set computerActivate", errors)
        after = [
            action
            for row in (props.get("propActionsAfter") or [])
            if isinstance(row, dict) and row.get("type") == 0 and row.get("id") == host_id
            for action in (row.get("actions") or [])
            if isinstance(action, dict) and action.get("a") == "DeleteEntity"
        ]
        require(after == [], "persistent prison must not DeleteEntity", errors)
        require(
            any(
                isinstance(row, dict) and row.get("id") == host_id and row.get("sid") == f"{MISSION_ID}_guardhouse"
                for row in (props.get("propEntities") or [])
            ),
            "persistent prison missing propEntities sid",
            errors,
        )

    cities = props.get("propCities") or []
    require(
        any(isinstance(r, dict) and r.get("factionSid") == "dungeon" and r.get("spawnHero") is True for r in cities),
        "city must use dungeon faction + spawnHero (Thirst-proven)",
        errors,
    )
    city_id = cities[0].get("id") if cities and isinstance(cities[0], dict) else None
    require(
        isinstance(city_id, int)
        and any(isinstance(r, dict) and r.get("id") == city_id for r in (props.get("propGrowthUnits") or [])),
        "city missing propGrowthUnits",
        errors,
    )
    require(
        isinstance(city_id, int)
        and any(isinstance(r, dict) and r.get("id") == city_id for r in (props.get("propRandomSquads") or [])),
        "city missing propRandomSquads garrison row",
        errors,
    )
    spawns_meta = (container.chunks[0].get("spawns") or {}).get("spawns") or []
    require(
        any(isinstance(r, dict) and r.get("factionSid") == "dungeon" for r in spawns_meta),
        "meta spawn factionSid must be dungeon",
        errors,
    )
    prop_spawns = props.get("propSpawns") or []
    require(
        isinstance(city_id, int)
        and any(isinstance(r, dict) and r.get("id") == city_id for r in prop_spawns),
        "city propSpawns row missing",
        errors,
    )

    stations = ((manifest.get("stations") or {}).get("stations")) or {}
    for key in ("info", "oneshot", "avalanche", "guarded", "guardhouse", "colocated_hero"):
        require(key in stations, f"manifest missing station {key}", errors)

    colocated_id = object_ids.get("colocated_hero")
    if isinstance(colocated_id, int):
        # hero-spawner skips propActionsBefore Dialog — delivery is BeforeIamVsHero.
        require(
            (0, colocated_id) not in before,
            "colocated hero must not use propActionsBefore Dialog",
            errors,
        )
        chunk3 = container.chunks[3] if len(container.chunks) > 3 else {}
        interruptions = chunk3.get("interruptions") or [] if isinstance(chunk3, dict) else []
        colocated_interruptions = [
            row
            for row in interruptions
            if isinstance(row, dict)
            and row.get("interruption") == "BeforeIamVsHero"
            and "homm3_stronghold_hero_2" in (row.get("p") or [])
            and any(
                isinstance(action, dict)
                and action.get("a") == "Dialog"
                and action.get("p") == [f"{MISSION_ID}_colocated_hero_dialog"]
                for action in (row.get("actions") or [])
            )
        ]
        require(
            len(colocated_interruptions) == 1,
            "colocated hero requires one BeforeIamVsHero Dialog interruption "
            "targeting heroSid homm3_stronghold_hero_2",
            errors,
        )
        after = [
            action
            for row in (props.get("propActionsAfter") or [])
            if isinstance(row, dict) and row.get("type") == 0 and row.get("id") == colocated_id
            for action in (row.get("actions") or [])
            if isinstance(action, dict) and action.get("a") == "DeleteEntity"
        ]
        require(after == [], "colocated hero must not DeleteEntity the hero-spawner", errors)
        require(
            any(
                isinstance(row, dict)
                and row.get("id") == colocated_id
                and row.get("sid") == f"{MISSION_ID}_colocated_hero"
                for row in (props.get("propEntities") or [])
            ),
            "colocated hero missing propEntities sid",
            errors,
        )
        require(
            any(
                isinstance(row, dict) and row.get("id") == colocated_id and row.get("heroSid")
                for row in (props.get("propHeroes") or [])
            ),
            "colocated hero missing propHeroes binding",
            errors,
        )
        require(
            any(
                isinstance(row, dict) and row.get("id") == colocated_id and row.get("spawnType") == 1
                for row in prop_spawns
            ),
            "colocated hero missing AI propSpawns row",
            errors,
        )
        station = stations.get("colocated_hero") or {}
        require(
            station.get("hostLifetime") == "colocated_hero_host"
            and station.get("objectSid") == "hero-spawner",
            "colocated hero station must remain hero-spawner hostLifetime",
            errors,
        )
        require(
            station.get("dialogAvatarIcon")
            == "icons/dialogue/dialogue_hero_homm3_stronghold_2"
            and station.get("dialogHeroSid") == "homm3_stronghold_hero_2",
            "colocated hero station must use Gurnisson dialogue portrait icon key",
            errors,
        )
        require(
            any(
                isinstance(row, dict)
                and row.get("id") == colocated_id
                and row.get("heroSid") == "homm3_stronghold_hero_2"
                for row in (props.get("propHeroes") or [])
            ),
            "colocated hero must spawn Gurnisson (homm3_stronghold_hero_2)",
            errors,
        )
        colocated_dialog = (
            overlay
            / "DB"
            / "dialogs"
            / "dialogs"
            / "custom_maps"
            / "EventRuntimeProbe"
            / f"{MISSION_ID}_colocated_hero_dialog.json"
        )
        if colocated_dialog.is_file():
            dialog_doc = json.loads(colocated_dialog.read_text(encoding="utf-8"))
            start = (((dialog_doc.get("array") or [None])[0] or {}).get("slides") or [None])[0] or {}
            avatars = start.get("avatars") or []
            require(
                len(avatars) == 1
                and avatars[0].get("icon")
                == "icons/dialogue/dialogue_hero_homm3_stronghold_2"
                and str(avatars[0].get("isForeground")).lower() == "true",
                "colocated hero dialog must show Gurnisson avatar "
                "(icons/dialogue/dialogue_hero_homm3_stronghold_2)",
                errors,
            )
        # Engagement contract: hero must not be emitted as random-squad (adjacent ZoC).
        require(
            not any(
                isinstance(group, dict)
                and group.get("sid") == "random-squad"
                and colocated_id in (group.get("ids") or [])
                for group in (map_data.get("objects") or [])
            ),
            "colocated hero must not be random-squad (would adjacent-ZoC)",
            errors,
        )

    guarded_id = object_ids.get("guarded")
    if isinstance(guarded_id, int):
        squad_rows = [
            row
            for row in (props.get("propSquads") or [])
            if isinstance(row, dict) and row.get("id") == guarded_id and row.get("unitProps")
        ]
        require(len(squad_rows) == 1, "guarded station needs exact propSquads.unitProps", errors)
        if squad_rows:
            unit = (squad_rows[0].get("unitProps") or [None])[0] or {}
            require(unit.get("sid") == GUARD_UNIT_SID, f"guard unit must be {GUARD_UNIT_SID}", errors)
            require(unit.get("count") == 1, "guard count must be 1", errors)
        random_rows = [
            row
            for row in (props.get("propRandomSquads") or [])
            if isinstance(row, dict) and row.get("id") == guarded_id
        ]
        require(len(random_rows) == 1, "guarded station needs propRandomSquads (SpawnsCreator)", errors)
        if random_rows:
            require(
                GUARD_SQUAD_SID in (random_rows[0].get("sids") or []),
                f"propRandomSquads.sids must include {GUARD_SQUAD_SID}",
                errors,
            )
            require(
                float(random_rows[0].get("requestedValue") or 0) == float(GUARD_VALUE_BUDGET),
                f"propRandomSquads.requestedValue must be {GUARD_VALUE_BUDGET} (squadValue budget)",
                errors,
            )
            require(
                random_rows[0].get("customTopUnit") == GUARD_UNIT_SID,
                f"propRandomSquads.customTopUnit must be {GUARD_UNIT_SID}",
                errors,
            )
        ai_rows = [
            row
            for row in (props.get("propAiIntetations") or [])
            if isinstance(row, dict) and row.get("id") == guarded_id and row.get("aiIgnore") is True
        ]
        require(len(ai_rows) == 1, "guarded station needs aiIgnore", errors)

    squad_overlay = (
        overlay
        / "DB"
        / "squads"
        / "squads_custom_maps"
        / "EventRuntimeProbe"
        / f"{GUARD_SQUAD_SID}.json"
    )
    require(squad_overlay.is_file(), f"missing squad overlay {squad_overlay}", errors)
    if squad_overlay.is_file():
        squad_doc = json.loads(squad_overlay.read_text(encoding="utf-8"))
        squad_row = ((squad_doc.get("array") or [None])[0]) or {}
        units = ((squad_row.get("baseSquad") or {}).get("units") or [None])
        unit0 = units[0] if units else {}
        require(squad_row.get("id") == GUARD_SQUAD_SID, "squad overlay id mismatch", errors)
        require(unit0.get("s") == GUARD_UNIT_SID, "squad overlay unit sid mismatch", errors)
        require(
            int(unit0.get("v") or 0) == GUARD_VALUE_BUDGET,
            f"squad overlay v must be value budget {GUARD_VALUE_BUDGET}, not headcount",
            errors,
        )

    flat_triggers: list[dict[str, Any]] = []
    for quest in quests:
        for sub in quest.get("subQuests") or []:
            flat_triggers.extend(sub.get("triggers") or [])
    conds = [
        condition.get("c")
        for trigger in flat_triggers
        for condition in (trigger.get("conditions") or [])
        if isinstance(condition, dict)
    ]
    require("CounterEqualityInDays" in conds, "missing CounterEqualityInDays recurrence", errors)
    require("AnyStartTurn" in conds, "missing AnyStartTurn daily timer ticks", errors)
    require("SquadInteraction" in conds, "missing SquadInteraction pre-battle dialog", errors)
    require("SquadKill" in conds, "missing SquadKill reward path", errors)
    require("StartTurn" in conds, "missing StartTurn timed grants", errors)
    require("ObjectInteractionAfter" in conds, "missing ObjectInteractionAfter visit tracking", errors)

    for dialog_sid in (
        f"{MISSION_ID}_briefing",
        f"{MISSION_ID}_oneshot_dialog",
        f"{MISSION_ID}_avalanche_dialog",
        f"{MISSION_ID}_guarded_dialog",
        f"{MISSION_ID}_guardhouse_dialog",
        f"{MISSION_ID}_colocated_hero_dialog",
    ):
        path = overlay / "DB" / "dialogs" / "dialogs" / "custom_maps" / "EventRuntimeProbe" / f"{dialog_sid}.json"
        require(path.is_file(), f"missing dialog overlay {path}", errors)
    require((overlay / "DB" / "quickStart.json").is_file(), "missing quickStart overlay", errors)
    require((overlay / "Lang" / "english" / "texts" / "dialogues.json").is_file(), "missing dialogues lang overlay", errors)

    return {
        "mapSid": MAP_SID,
        "mapSize": MAP_SIZE,
        "stationCount": len(stations),
        "questCount": len(quests),
        "triggerCount": len(flat_triggers),
        "guardUnit": GUARD_UNIT_SID,
        "proofBoundary": "generated-artifact shape only; runtime unproven",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    errors: list[str] = []

    validate_sources(repo_root, errors)
    if not args.skip_generate:
        builder = repo_root / BUILDER
        result = subprocess.run(
            [sys.executable, str(builder), "--out-root", str(repo_root / ARTIFACT_ROOT)],
            cwd=str(repo_root / "experiments" / "campaign_port_poc"),
            check=False,
        )
        if result.returncode != 0:
            errors.append("builder failed")
            print("Event runtime probe contract FAIL")
            for error in errors:
                print(f"- {error}")
            return 1

    summary = validate_artifact(repo_root, errors)
    if errors:
        print("Event runtime probe contract FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Event runtime probe contract PASS")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
