"""Fail-closed validator for vanilla_stock emitted maps."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import native_only_stock as native
import port_homecoming_poc as poc
from approach_cell.surface_emit import source_block_offsets as raw_translation_source_block_offsets
from h3m_object_walk import walk_h3m_file

from . import GE_ONLY_TILE_IDS, SCHEMA_GROUND_TRUTH, SCHEMA_VALIDATION
from .emit_map import (
    DEFAULT_STOCK_CORE,
    FORBIDDEN_SID_SUBSTRINGS,
    resolve_stock_faction_choice,
)
from .scenery_footprint import (
    POLICY as SCENERY_FOOTPRINT_POLICY,
    SCHEMA as SCENERY_FOOTPRINT_SCHEMA,
    VanillaStockSceneryFootprintError,
    load_stock_object_configs,
    occupied_nodes_for_instance,
)
from .terrain import (
    VanillaStockTerrainError,
    assert_stock_ocean_basin_climb_contract,
    assert_stock_tile_ids,
    assert_stock_water_ids,
    load_stock_tile_ids,
    load_stock_water_ids,
)
from .victory_events import (
    MAIN_QUEST_SID,
    MINES_OWNED_COUNTER_SID,
    STOCK_MAP_EVENT_DECO_SID,
    STOCK_MAP_EVENT_GUARD_SID,
    STOCK_MAP_EVENT_MARKER_SID,
)


class VanillaStockValidationError(ValueError):
    pass


def validate_vanilla_stock_map(
    *,
    map_path: Path,
    stock_core: Path = DEFAULT_STOCK_CORE,
    expect_map_sid: str | None = None,
    expect_victory_mode: str | None = None,
    expect_mine_entity_count: int | None = None,
    expect_map_event_count: int | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    if not map_path.is_file():
        raise VanillaStockValidationError(f"map not found: {map_path}")
    if not stock_core.is_file():
        raise VanillaStockValidationError(f"stock Core.zip not found: {stock_core}")

    stock_objects = native.load_core_object_ids(stock_core)
    try:
        stock_object_configs = load_stock_object_configs(stock_core)
        allowed_tiles = load_stock_tile_ids(stock_core)
        allowed_waters = load_stock_water_ids(stock_core)
    except (VanillaStockSceneryFootprintError, VanillaStockTerrainError) as ex:
        raise VanillaStockValidationError(str(ex)) from ex
    container = poc.read_olden_map_container(map_path)
    if len(container.chunks) < 2:
        errors.append("map has fewer than 2 JSON chunks")
    meta = container.chunks[0]
    map_data = container.chunks[1]
    if not isinstance(meta, dict) or not isinstance(map_data, dict):
        raise VanillaStockValidationError("meta/mapData chunks must be objects")

    map_sid = map_data.get("fileMapName")
    if expect_map_sid is not None and map_sid != expect_map_sid:
        errors.append(f"fileMapName {map_sid!r} != expected {expect_map_sid!r}")
    if isinstance(map_sid, str) and (map_sid.startswith("h3_") or "homm3" in map_sid.lower()):
        errors.append(f"GE-branded map SID: {map_sid}")

    views = map_data.get("views")
    if not isinstance(views, list) or len(views) != 1:
        errors.append(f"views.length must be 1, found {0 if not isinstance(views, list) else len(views)}")

    width = map_data.get("sizeX_")
    height = map_data.get("sizeZ_")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        errors.append(f"invalid sizeX_/sizeZ_: {width},{height}")
        expected = 0
    else:
        expected = width * height
        if width % 16 != 0 or height % 16 != 0:
            errors.append(f"map dimensions must be sector-aligned (16): {width}x{height}")

    for key in ("tilesMap", "levelsMap", "climbsMap", "roadsMap", "waterMap"):
        arr = map_data.get(key)
        if not isinstance(arr, list):
            errors.append(f"{key} missing or not a list")
            continue
        if expected and len(arr) != expected:
            errors.append(f"{key} length {len(arr)} != sizeX_*sizeZ_ {expected}")

    tiles = map_data.get("tilesMap") if isinstance(map_data.get("tilesMap"), list) else []
    try:
        assert_stock_tile_ids([int(t) for t in tiles if isinstance(t, int)], allowed_tiles)
    except VanillaStockTerrainError as ex:
        errors.append(str(ex))
    ge_tiles = sorted({int(t) for t in tiles if isinstance(t, int) and t in GE_ONLY_TILE_IDS})
    if ge_tiles:
        errors.append(f"GE-only tile ids present: {ge_tiles}")

    water = map_data.get("waterMap") if isinstance(map_data.get("waterMap"), list) else []
    try:
        assert_stock_water_ids([int(v) for v in water if isinstance(v, int)], allowed_waters)
    except VanillaStockTerrainError as ex:
        errors.append(str(ex))
    if any(isinstance(v, int) and v == 18 for v in water):
        errors.append("waterMap contains GE ocean id 18")

    levels = map_data.get("levelsMap") if isinstance(map_data.get("levelsMap"), list) else []
    climbs = map_data.get("climbsMap") if isinstance(map_data.get("climbsMap"), list) else []
    basin_climb_report: dict[str, int] | None = None
    if (
        isinstance(width, int)
        and isinstance(height, int)
        and width > 0
        and height > 0
        and len(levels) == width * height
        and len(climbs) == width * height
    ):
        try:
            basin_climb_report = assert_stock_ocean_basin_climb_contract(
                levels_map=[int(v) for v in levels],
                climbs_map=[int(v) for v in climbs],
                width=width,
                height=height,
            )
        except VanillaStockTerrainError as ex:
            errors.append(str(ex))

    objects = map_data.get("objects") if isinstance(map_data.get("objects"), list) else []
    emitted_sids: list[str] = []
    placements_by_id: dict[int, dict[str, Any]] = {}
    for group in objects:
        if not isinstance(group, dict):
            errors.append("objects group is not an object")
            continue
        sid = group.get("sid")
        if not isinstance(sid, str):
            errors.append(f"objects group missing sid: {group}")
            continue
        emitted_sids.append(sid)
        if any(token in sid.lower() for token in FORBIDDEN_SID_SUBSTRINGS):
            errors.append(f"GE/h3 SID leak: {sid}")
        if sid not in stock_objects:
            errors.append(f"SID absent from stock Core ObjectConfig: {sid}")
        ids = group.get("ids")
        nodes = group.get("nodes")
        rotations = group.get("rotations")
        if not isinstance(ids, list) or not isinstance(nodes, list) or not isinstance(rotations, list):
            errors.append(f"objects group {sid} has malformed placement arrays")
            continue
        if len(ids) != len(nodes) or len(ids) != len(rotations):
            errors.append(f"objects group {sid} placement arrays have unequal lengths")
            continue
        for object_id, node, rotation in zip(ids, nodes, rotations):
            if not isinstance(object_id, int) or not isinstance(node, int) or not isinstance(rotation, int):
                errors.append(f"objects group {sid} has non-integer placement values")
                continue
            if object_id in placements_by_id:
                errors.append(f"duplicate object id {object_id}")
                continue
            placements_by_id[object_id] = {"sid": sid, "node": node, "rotation": rotation}

    props = map_data.get("objectsProperties") if isinstance(map_data.get("objectsProperties"), dict) else {}
    random_item_prop_ids = {
        int(row["id"])
        for row in (props.get("propRandomItems") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }
    random_item_object_ids = {
        object_id for object_id, row in placements_by_id.items() if row.get("sid") == "random-item"
    }
    if random_item_object_ids != random_item_prop_ids:
        errors.append(
            "random-item objects must have matching propRandomItems rows: "
            f"objects={sorted(random_item_object_ids)} props={sorted(random_item_prop_ids)}"
        )
    for row in props.get("propRandomItems") or []:
        if not isinstance(row, dict):
            errors.append("propRandomItems row must be an object")
            continue
        rarity = row.get("rarity")
        if rarity not in (0, 1, 2, 3):
            errors.append(f"propRandomItems id {row.get('id')} rarity must be 0..3, got {rarity!r}")
        elif rarity == 4:
            errors.append(f"propRandomItems id {row.get('id')} rarity 4 is invalid for stock RandomItemsPool")

    # No Core overlay markers in sibling dirs for this validator target — emit lane forbids overlays.
    overlay_markers = []
    sibling = map_path.parent.parent / "core_overlay"
    if sibling.is_dir():
        overlay_markers.append(str(sibling))
        errors.append(f"vanilla_stock forbids Core overlays: {sibling}")

    settings = map_data.get("settings") if isinstance(map_data.get("settings"), dict) else {}
    if meta.get("isScenario") is not True:
        errors.append("meta.isScenario must be true for a playable vanilla scenario")
    if map_data.get("isScenario") is not True:
        errors.append("mapData.isScenario must be true for a playable vanilla scenario")
    if settings.get("isScenario") is not True:
        errors.append("settings.isScenario must be true for a playable vanilla scenario")

    scenario_spawns = meta.get("spawns")
    if not isinstance(scenario_spawns, dict):
        errors.append("meta.spawns must be the scenario object with playersCount/spawns/takenHeroes")
    else:
        prop_spawns_by_owner: dict[int, list[dict[str, Any]]] = {}
        for prop_spawn in props.get("propSpawns") or []:
            if isinstance(prop_spawn, dict) and isinstance(prop_spawn.get("owner"), int):
                prop_spawns_by_owner.setdefault(int(prop_spawn["owner"]), []).append(prop_spawn)
        prop_cities_by_id = {
            int(row["id"]): row
            for row in (props.get("propCities") or [])
            if isinstance(row, dict) and isinstance(row.get("id"), int)
        }
        prop_hero_ids = {
            int(row["id"])
            for row in (props.get("propHeroes") or [])
            if isinstance(row, dict) and isinstance(row.get("id"), int)
        }
        players_count = scenario_spawns.get("playersCount")
        spawn_rows = scenario_spawns.get("spawns")
        spawn_taken_heroes = scenario_spawns.get("takenHeroes")
        if not isinstance(players_count, int) or players_count <= 0:
            errors.append("meta.spawns.playersCount must be a positive integer")
        if not isinstance(spawn_rows, list):
            errors.append("meta.spawns.spawns must be a list")
        elif isinstance(players_count, int) and players_count != len(spawn_rows):
            errors.append(
                f"meta.spawns.playersCount {players_count} != spawn row count {len(spawn_rows)}"
            )
        if not isinstance(spawn_taken_heroes, list):
            errors.append("meta.spawns.takenHeroes must be a list")
        if meta.get("takenHeroes") != spawn_taken_heroes:
            errors.append("meta.takenHeroes must match meta.spawns.takenHeroes")
        if isinstance(spawn_rows, list):
            owners_seen: list[int] = []
            for index, row in enumerate(spawn_rows):
                if not isinstance(row, dict):
                    errors.append(f"meta.spawns.spawns[{index}] must be an object")
                    continue
                if not isinstance(row.get("owner"), int) or not 1 <= row["owner"] <= 8:
                    errors.append(f"meta.spawns.spawns[{index}].owner must be an Olden player index 1..8")
                else:
                    owners_seen.append(int(row["owner"]))
                if row.get("playerId") != "":
                    errors.append(f"meta.spawns.spawns[{index}].playerId must be empty")
                if row.get("colorId") != -1:
                    errors.append(f"meta.spawns.spawns[{index}].colorId must be -1")
                if row.get("spawnType") not in (0, 1):
                    errors.append(f"meta.spawns.spawns[{index}].spawnType must be 0 or 1")
                faction_sid = row.get("factionSid")
                is_hero_defined = row.get("isHeroDefined")
                hero_sid = row.get("heroSid")
                is_editable_choice = (
                    row.get("isCityDefined") is False
                    and faction_sid == ""
                    and is_hero_defined is False
                    and hero_sid == ""
                )
                if is_editable_choice:
                    # Native free-choice contract: qmq() constructs editable
                    # SlotModel random defaults only when both definition flags
                    # are false. Validate the lobby primary city for this owner.
                    owner = int(row["owner"])
                    owner_prop_spawns = prop_spawns_by_owner.get(owner) or []
                    if not owner_prop_spawns:
                        errors.append(
                            f"meta.spawns.spawns[{index}] free-choice row has no matching propSpawns owner"
                        )
                    # Prefer an already-undefined city (lobby free-choice primary).
                    undefined_ids = [
                        int(ps["id"])
                        for ps in owner_prop_spawns
                        if isinstance(ps.get("id"), int)
                        and isinstance(prop_cities_by_id.get(int(ps["id"])), dict)
                        and prop_cities_by_id[int(ps["id"])].get("isDefined") is False
                    ]
                    if undefined_ids:
                        primary_id = min(undefined_ids)
                    else:
                        primary_id = min(
                            (int(ps["id"]) for ps in owner_prop_spawns if isinstance(ps.get("id"), int)),
                            default=None,
                        )
                    for prop_spawn in owner_prop_spawns:
                        spawn_id = prop_spawn.get("id")
                        if spawn_id != primary_id:
                            continue
                        city = prop_cities_by_id.get(spawn_id) if isinstance(spawn_id, int) else None
                        if not isinstance(city, dict):
                            errors.append(
                                f"meta.spawns.spawns[{index}] free-choice spawn id {spawn_id!r} "
                                "has no matching propCities row"
                            )
                            continue
                        if (
                            city.get("isDefined") is not False
                            or city.get("factionSid") != ""
                            or city.get("spawnHero") is not False
                        ):
                            errors.append(
                                f"free-choice propCities id {spawn_id} must be undefined with empty "
                                "factionSid and spawnHero=false"
                            )
                        if spawn_id in prop_hero_ids:
                            errors.append(
                                f"free-choice spawn id {spawn_id} must not have a propHeroes lock"
                            )
                elif row.get("isCityDefined") is False:
                    errors.append(
                        f"meta.spawns.spawns[{index}] undefined city must also have empty factionSid, "
                        "isHeroDefined=false, and empty heroSid"
                    )
                elif not isinstance(faction_sid, str) or not faction_sid:
                    errors.append(
                        f"meta.spawns.spawns[{index}].factionSid must be a non-empty stock faction"
                    )
                elif is_hero_defined is not True:
                    errors.append(f"meta.spawns.spawns[{index}].isHeroDefined must be true when faction is locked")
                elif not isinstance(hero_sid, str) or not hero_sid:
                    errors.append(f"meta.spawns.spawns[{index}].heroSid must be set when faction is locked")
                if hero_sid not in ("", None) and hero_sid not in (spawn_taken_heroes or []):
                    if is_hero_defined is True:
                        errors.append(
                            f"meta.spawns.spawns[{index}].heroSid {hero_sid!r} missing from takenHeroes"
                        )
            # Compact native ownership: exactly owners 1..playersCount, human owner 1 present.
            if isinstance(players_count, int) and players_count > 0 and owners_seen:
                expected_owners = list(range(1, players_count + 1))
                if sorted(owners_seen) != expected_owners:
                    errors.append(
                        f"meta.spawns owners must be compact 1..{players_count}; "
                        f"got {sorted(owners_seen)}"
                    )
                if 1 not in owners_seen:
                    errors.append("meta.spawns must include human owner 1 after compact renumber")
                if len(owners_seen) != len(set(owners_seen)):
                    errors.append("meta.spawns must have exactly one row per final owner")
                human_rows = [row for row in spawn_rows if isinstance(row, dict) and row.get("owner") == 1]
                if human_rows and human_rows[0].get("spawnType") != 0:
                    errors.append("meta.spawns owner 1 must be human spawnType=0")
            # Every property owner must have a matching meta/prop spawn seat.
            property_owners: set[int] = set()
            for prop_key in ("propSpawns", "propOwners", "propCities"):
                for row in props.get(prop_key) or []:
                    if isinstance(row, dict) and isinstance(row.get("owner"), int):
                        property_owners.add(int(row["owner"]))
            meta_owners = set(owners_seen)
            orphan_property_owners = sorted(owner for owner in property_owners if owner not in meta_owners)
            if orphan_property_owners:
                errors.append(
                    f"property owners without meta.spawns seats: {orphan_property_owners}"
                )
            # No mixed-faction City propSpawns under one owner.
            city_faction_by_id = {
                int(row["id"]): str(row.get("factionSid") or "")
                for row in (props.get("propCities") or [])
                if isinstance(row, dict) and isinstance(row.get("id"), int)
            }
            factions_by_owner: dict[int, set[str]] = {}
            for prop_spawn in props.get("propSpawns") or []:
                if not isinstance(prop_spawn, dict):
                    continue
                # City spawnPointType is 0; tolerate omitted field as city for stock.
                if prop_spawn.get("spawnPointType") not in (0, None):
                    continue
                owner = prop_spawn.get("owner")
                object_id = prop_spawn.get("id")
                if not isinstance(owner, int) or not isinstance(object_id, int):
                    continue
                faction = city_faction_by_id.get(object_id, "")
                if not faction:
                    continue
                factions_by_owner.setdefault(owner, set()).add(faction)
            for owner, factions in sorted(factions_by_owner.items()):
                if len(factions) > 1:
                    errors.append(
                        f"owner {owner} still has mixed city factions {sorted(factions)} "
                        "after ownership contract"
                    )
            # Human-capable (spawnType 0) rows must come first so lobby binds the intended start town.
            if all(isinstance(row, dict) and row.get("spawnType") in (0, 1) for row in spawn_rows):
                seen_ai = False
                for index, row in enumerate(spawn_rows):
                    if int(row["spawnType"]) == 1:
                        seen_ai = True
                    elif seen_ai:
                        errors.append(
                            f"meta.spawns.spawns must list human spawnType=0 before AI; "
                            f"human row at index {index} follows an AI row"
                        )
                        break

    campaign_info = meta.get("campaignInfo")
    required_campaign_info = {"missionNameSid", "missionDescSid", "campaignSid", "campaignDescSid", "hubIconSid"}
    if not isinstance(campaign_info, dict) or not required_campaign_info.issubset(campaign_info):
        errors.append("meta.campaignInfo must preserve the stock scenario object shape")

    key_objects = map_data.get("keyObjects")
    if key_objects != []:
        errors.append("vanilla_stock maps must clear template keyObjects")
    if expected:
        areas = map_data.get("areas")
        if not isinstance(areas, list) or len(areas) != 1:
            errors.append("vanilla_stock maps must contain one full-map area")
        elif not isinstance(areas[0], dict) or areas[0].get("nodes") != list(range(expected)):
            errors.append("vanilla_stock area nodes must cover the emitted map exactly")
        rivers = map_data.get("rivers")
        if (
            not isinstance(rivers, list)
            or len(rivers) != 1
            or not isinstance(rivers[0], dict)
            or rivers[0].get("nodes") != []
        ):
            errors.append("vanilla_stock maps must clear template river nodes")

    map_win = settings.get("mapWinConditions")
    if map_win not in ([], None):
        if not isinstance(map_win, list) or len(map_win) != 0:
            errors.append("settings.mapWinConditions must be cleared ([]); template leftovers are forbidden")

    start_settings = meta.get("startSettings") if isinstance(meta.get("startSettings"), dict) else {}
    defeat_all = start_settings.get("DefeatAllEnemiesEnabled")

    quest_chunk = container.chunks[3] if len(container.chunks) >= 4 and isinstance(container.chunks[3], dict) else {}
    quests = quest_chunk.get("quests") if isinstance(quest_chunk.get("quests"), list) else []
    counters = quest_chunk.get("counters") if isinstance(quest_chunk.get("counters"), list) else []
    thirst_leftover = any(
        isinstance(q, dict)
        and (
            str(q.get("name") or "").startswith("tfp_")
            or str(q.get("desc") or "").startswith("tfp_")
            or "Thirst" in str(q.get("comment") or "")
        )
        for q in quests
    )
    if thirst_leftover:
        errors.append("Thirst template quest Loc leftovers detected in chunk3")

    main_quests = [q for q in quests if isinstance(q, dict) and q.get("sid") == MAIN_QUEST_SID]
    if len(main_quests) != 1:
        errors.append(f"expected exactly one {MAIN_QUEST_SID} quest, found {len(main_quests)}")

    victory_mode = None
    mine_entity_count = None
    map_event_count = None
    footprint_validation = {"sourceObjectCount": 0, "placementCount": 0, "mismatchCount": 0}
    if manifest_path is not None and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        substitution = manifest.get("substitutionTable") if isinstance(manifest, dict) else None
        if not isinstance(substitution, dict):
            errors.append("manifest missing copied substitutionTable contract")
        else:
            if substitution.get("schema") != "homm3.vanilla_stock.copied_substitution_table.v1":
                errors.append(f"manifest substitutionTable schema is invalid: {substitution.get('schema')!r}")
            if not isinstance(substitution.get("entryCount"), int) or substitution["entryCount"] <= 0:
                errors.append("manifest substitutionTable entryCount must be positive")
            table_path = substitution.get("path")
            if not isinstance(table_path, str) or not Path(table_path).is_file():
                errors.append(f"manifest substitutionTable path is not readable: {table_path!r}")
        stock_allow = manifest.get("stockAllowlists") if isinstance(manifest, dict) else None
        if not isinstance(stock_allow, dict):
            errors.append("manifest missing stockAllowlists contract")
        else:
            if sorted(stock_allow.get("tileIds") or []) != sorted(allowed_tiles):
                errors.append("manifest stockAllowlists.tileIds drift from Core.zip tiles catalog")
            if sorted(stock_allow.get("waterIds") or []) != sorted(allowed_waters):
                errors.append("manifest stockAllowlists.waterIds drift from Core.zip waters catalog")
        scenario_header = manifest.get("scenarioHeader") if isinstance(manifest, dict) else None
        playable_players = (
            scenario_header.get("playablePlayers")
            if isinstance(scenario_header, dict)
            else None
        )
        manifest_spawns = (
            scenario_spawns.get("spawns")
            if isinstance(scenario_spawns, dict)
            and isinstance(scenario_spawns.get("spawns"), list)
            else []
        )
        ownership = manifest.get("ownershipContract") if isinstance(manifest, dict) else None
        h3_to_final = (
            ownership.get("h3ColorToFinalOwners")
            if isinstance(ownership, dict)
            else None
        )
        if not isinstance(ownership, dict):
            errors.append("manifest missing ownershipContract after compact-owner transfer")
        elif ownership.get("humanOldenOwner") != 1:
            errors.append("manifest ownershipContract.humanOldenOwner must be 1")
        elif not isinstance(h3_to_final, dict):
            errors.append("manifest ownershipContract.h3ColorToFinalOwners must be an object")
        if not isinstance(playable_players, list):
            errors.append("manifest scenarioHeader.playablePlayers must be a list")
        else:
            for player in playable_players:
                if not isinstance(player, dict) or not isinstance(player.get("index"), int):
                    errors.append("manifest playable player row is malformed")
                    continue
                h3_color = int(player["index"])
                final_owners = []
                if isinstance(h3_to_final, dict):
                    mapped = h3_to_final.get(str(h3_color), h3_to_final.get(h3_color))
                    if isinstance(mapped, list):
                        final_owners = [int(x) for x in mapped if isinstance(x, int)]
                if not final_owners:
                    errors.append(
                        f"manifest playable H3 color {h3_color} has no final native owners"
                    )
                    continue
                owner_rows = [
                    row
                    for row in manifest_spawns
                    if isinstance(row, dict) and row.get("owner") in final_owners
                ]
                if not owner_rows:
                    errors.append(
                        f"manifest playable H3 color {h3_color} finals {final_owners} "
                        "have no emitted spawn rows"
                    )
                    continue
                # Primary final owner for faction-choice checks: lowest final owner.
                primary_owner = min(final_owners)
                primary_rows = [
                    row
                    for row in owner_rows
                    if isinstance(row, dict) and row.get("owner") == primary_owner
                ]
                if len(primary_rows) != 1:
                    errors.append(
                        f"manifest H3 color {h3_color} primary final owner {primary_owner} "
                        f"must have exactly one spawn row, found {len(primary_rows)}"
                    )
                    continue
                expected = resolve_stock_faction_choice(
                    factions_mask=player.get("factionsMask"),
                    is_faction_random=player.get("isFactionRandom"),
                )
                if expected["freeChoice"]:
                    for row in primary_rows:
                        if not (
                            row.get("isCityDefined") is False
                            and row.get("factionSid") == ""
                            and row.get("isHeroDefined") is False
                            and row.get("heroSid") == ""
                        ):
                            errors.append(
                                f"H3 color {h3_color} requires editable faction/hero choice, "
                                "but emitted primary spawn metadata is defined"
                            )
                elif any(not row.get("factionSid") for row in primary_rows):
                    errors.append(
                        f"H3 color {h3_color} has one mapped forced faction but emitted an "
                        "undefined faction choice"
                    )
        victory = manifest.get("victory") if isinstance(manifest, dict) else None
        if isinstance(victory, dict) and victory.get("mode") == "WINSTANDARD":
            playable_finals = victory.get("playableFinalOwners")
            compact_count = (
                scenario_spawns.get("playersCount")
                if isinstance(scenario_spawns, dict)
                else None
            )
            if isinstance(playable_finals, list) and isinstance(compact_count, int):
                expected_owners = set(range(1, compact_count + 1))
                got = {int(x) for x in playable_finals if isinstance(x, int)}
                if not got.issubset(expected_owners):
                    errors.append(
                        f"victory playableFinalOwners {sorted(got)} exceed compact owners "
                        f"{sorted(expected_owners)}"
                    )
                if 1 not in got:
                    errors.append("victory playableFinalOwners must include human owner 1")
        if isinstance(manifest, dict) and "accessContract" not in manifest:
            errors.append("manifest missing accessContract")
        if isinstance(manifest, dict) and "serializationShape" not in manifest:
            errors.append("manifest missing serializationShape")
        if isinstance(manifest, dict) and "sceneryCanonPostpass" not in manifest:
            errors.append("manifest missing sceneryCanonPostpass")
        gate_face = manifest.get("gateFaceRotation") if isinstance(manifest, dict) else None
        if not isinstance(gate_face, dict):
            errors.append("manifest missing gateFaceRotation contract")
        else:
            unresolved = gate_face.get("unresolved") or []
            if isinstance(unresolved, list) and unresolved:
                errors.append(f"gateFaceRotation left unresolved objects: {len(unresolved)}")
            if gate_face.get("policy") != "raw_gated_mirror_rotation_to_free_cardinal_approach":
                errors.append(f"gateFaceRotation policy drifted: {gate_face.get('policy')!r}")
            relocation_policy = gate_face.get("relocationPolicy")
            max_relocation_radius = gate_face.get("maxRelocationRadius")
            relocation_region_width = gate_face.get("relocationRegionWidth")
            rotated_rows = gate_face.get("rotated") or []
            relocation_rows = [
                row
                for row in rotated_rows
                if isinstance(row, dict) and row.get("relocation") is not None
            ]
            if relocation_rows:
                if relocation_policy != "bounded_same_atlas_region_functional_collision_relocation":
                    errors.append(f"gateFaceRotation relocation policy drifted: {relocation_policy!r}")
                if not isinstance(max_relocation_radius, int) or max_relocation_radius < 0:
                    errors.append("gateFaceRotation maxRelocationRadius must be a non-negative integer")
                if (
                    not isinstance(relocation_region_width, int)
                    or relocation_region_width <= 0
                    or (isinstance(width, int) and width % relocation_region_width != 0)
                ):
                    errors.append(
                        "gateFaceRotation relocationRegionWidth must divide the atlas width"
                    )
            for rotated_row in rotated_rows:
                if not isinstance(rotated_row, dict):
                    continue
                relocation = rotated_row.get("relocation")
                if relocation is None:
                    continue
                object_id = rotated_row.get("objectId")
                placement = placements_by_id.get(object_id) if isinstance(object_id, int) else None
                if not isinstance(relocation, dict):
                    errors.append(f"gate relocation for object {object_id!r} is malformed")
                    continue
                from_node = relocation.get("fromNode")
                to_node = relocation.get("toNode")
                distance = relocation.get("distance")
                dx = relocation.get("dx")
                dy = relocation.get("dy")
                rotation = relocation.get("rotation")
                approaches = relocation.get("approaches")
                if not all(isinstance(value, int) for value in (from_node, to_node, distance, dx, dy, rotation)):
                    errors.append(f"gate relocation for object {object_id!r} has non-integer geometry")
                    continue
                if (
                    not isinstance(max_relocation_radius, int)
                    or distance < 0
                    or distance > max_relocation_radius
                    or distance != abs(dx) + abs(dy)
                ):
                    errors.append(f"gate relocation for object {object_id!r} exceeds its bounded radius")
                if isinstance(width, int) and to_node != from_node + dy * width + dx:
                    errors.append(f"gate relocation for object {object_id!r} has inconsistent node delta")
                if (
                    isinstance(relocation_region_width, int)
                    and relocation_region_width > 0
                    and isinstance(width, int)
                    and (from_node % width) // relocation_region_width
                    != (to_node % width) // relocation_region_width
                ):
                    errors.append(f"gate relocation for object {object_id!r} crossed an atlas region")
                if not isinstance(approaches, list) or not approaches:
                    errors.append(f"gate relocation for object {object_id!r} has no proven approach")
                if not isinstance(placement, dict):
                    errors.append(f"gate relocation object {object_id!r} is absent from emitted placements")
                elif placement.get("node") != to_node or placement.get("rotation") != rotation:
                    errors.append(f"gate relocation object {object_id!r} disagrees with emitted placement")
            stock_adapt = gate_face.get("stockAdaptation")
            if not isinstance(stock_adapt, dict):
                errors.append("gateFaceRotation missing stockAdaptation")
            elif "geOnlyTilesForbidden" not in stock_adapt:
                errors.append("gateFaceRotation.stockAdaptation missing geOnlyTilesForbidden")
        ground = manifest.get("placementGroundTruth") if isinstance(manifest, dict) else None
        if not isinstance(ground, dict):
            errors.append("manifest missing placementGroundTruth contract")
        else:
            if ground.get("status") != "applied":
                errors.append(f"placementGroundTruth status must be applied, got {ground.get('status')!r}")
            gt_path = ground.get("artifact")
            if not isinstance(gt_path, str) or not Path(gt_path).is_file():
                errors.append(f"placementGroundTruth artifact missing: {gt_path!r}")
            else:
                gt_doc = json.loads(Path(gt_path).read_text(encoding="utf-8"))
                if gt_doc.get("schema") != SCHEMA_GROUND_TRUTH:
                    errors.append(f"placementGroundTruth schema invalid: {gt_doc.get('schema')!r}")
                gt_placements = gt_doc.get("placements") if isinstance(gt_doc.get("placements"), list) else []
                emitted_ids = set(placements_by_id)
                for row in gt_placements:
                    if not isinstance(row, dict):
                        continue
                    status = row.get("emitStatus")
                    olden = row.get("olden")
                    if status in {"emitted", "emitted_sid_mismatch"}:
                        if not isinstance(olden, dict) or not isinstance(olden.get("objectId"), int):
                            errors.append(f"ground-truth emitted row missing olden objectId: {row.get('sourceKey')}")
                            continue
                        object_id = int(olden["objectId"])
                        if object_id not in emitted_ids:
                            errors.append(
                                f"ground-truth emitted object {object_id} absent from map objects"
                            )
                        else:
                            actual = placements_by_id[object_id]
                            if actual.get("sid") != olden.get("sid"):
                                errors.append(
                                    f"ground-truth sid mismatch for {object_id}: "
                                    f"map={actual.get('sid')} gt={olden.get('sid')}"
                                )
                    elif status == "missing_from_emit":
                        errors.append(
                            f"ground-truth reports missing_from_emit for {row.get('sourceKey')}"
                        )
        alignment = manifest.get("alignmentIr") if isinstance(manifest, dict) else None
        if not isinstance(alignment, dict):
            errors.append("manifest missing alignmentIr contract")
        elif alignment.get("entityCount") is None:
            errors.append("manifest alignmentIr.entityCount missing")
        terrain = manifest.get("terrain") if isinstance(manifest, dict) else None
        if isinstance(terrain, dict):
            policy = terrain.get("policy") if isinstance(terrain.get("policy"), dict) else {}
            if policy.get("rivers") != "h3_river_to_stock_water_map_biome_channel":
                errors.append(f"terrain river policy drifted: {policy.get('rivers')!r}")
            if "undergroundTunnelClearance" not in policy:
                errors.append("terrain policy missing undergroundTunnelClearance")
            if policy.get("envelopePadding") != (
                "atlas_cells_outside_source_envelopes_elevated_dirt_levels_one_climbs_zero"
            ):
                errors.append(f"terrain envelopePadding policy drifted: {policy.get('envelopePadding')!r}")
            padding = terrain.get("envelopePadding") if isinstance(terrain.get("envelopePadding"), dict) else None
            if not isinstance(padding, dict) or padding.get("status") != "applied":
                errors.append("manifest terrain.envelopePadding must be applied")
            elif not isinstance(padding.get("cellCount"), int) or padding["cellCount"] < 0:
                errors.append("manifest terrain.envelopePadding.cellCount must be a non-negative int")
            else:
                atlas_manifest = manifest.get("atlas") if isinstance(manifest.get("atlas"), dict) else {}
                source_w = atlas_manifest.get("sourceWidth")
                source_h = atlas_manifest.get("sourceHeight")
                layers = atlas_manifest.get("layers") if isinstance(atlas_manifest.get("layers"), dict) else {}
                if (
                    isinstance(source_w, int)
                    and isinstance(source_h, int)
                    and isinstance(width, int)
                    and isinstance(height, int)
                    and layers
                ):
                    expected_padding = (width * height) - (len(layers) * source_w * source_h)
                    if padding["cellCount"] != expected_padding:
                        errors.append(
                            f"envelope padding cellCount {padding['cellCount']} != expected {expected_padding}"
                        )
                    # Spot-check: every atlas cell outside source envelopes is elevated dirt cliff.
                    source_nodes: set[int] = set()
                    for layer_info in layers.values():
                        if not isinstance(layer_info, dict):
                            continue
                        ox = layer_info.get("offsetX")
                        oy = layer_info.get("offsetY")
                        if not isinstance(ox, int) or not isinstance(oy, int):
                            continue
                        for sy in range(source_h):
                            for sx in range(source_w):
                                # H3 top-left → Olden bottom-left within layer envelope.
                                node = (oy + source_h - 1 - sy) * width + (ox + sx)
                                source_nodes.add(node)
                    tiles_map = map_data.get("tilesMap") or []
                    levels_map = map_data.get("levelsMap") or []
                    climbs_map = map_data.get("climbsMap") or []
                    bad_padding = 0
                    for node in range(width * height):
                        if node in source_nodes:
                            continue
                        if (
                            tiles_map[node] != 7
                            or levels_map[node] != 1
                            or climbs_map[node] != 0
                        ):
                            bad_padding += 1
                            if bad_padding <= 5:
                                errors.append(
                                    f"envelope padding node {node} must be dirt/levels=1/climbs=0; "
                                    f"got tile={tiles_map[node]} level={levels_map[node]} climb={climbs_map[node]}"
                                )
                    if bad_padding > 5:
                        errors.append(f"envelope padding has {bad_padding} non-cliff cells (showing first 5)")
        objects_manifest = manifest.get("objects") if isinstance(manifest, dict) else None
        if isinstance(objects_manifest, dict):
            town_align = objects_manifest.get("townGateAlign")
            if not isinstance(town_align, dict) or town_align.get("policy") != "town_gate_aligned_one_north_of_h3_visit":
                errors.append("manifest objects.townGateAlign policy must be town_gate_aligned_one_north_of_h3_visit")
            else:
                rows = town_align.get("rows") if isinstance(town_align.get("rows"), list) else []
                city_count = objects_manifest.get("cityCount")
                if isinstance(city_count, int) and len(rows) != city_count:
                    errors.append(
                        f"townGateAlign row count {len(rows)} != cityCount {city_count}"
                    )
                for row in rows:
                    if not isinstance(row, dict):
                        errors.append("townGateAlign row must be an object")
                        continue
                    visit = row.get("visitNode")
                    gate_target = row.get("gateTargetNode")
                    gates = row.get("gateNodes")
                    emit_node = row.get("emitNode") or row.get("node")
                    city_id = row.get("cityObjectId")
                    if (
                        not isinstance(visit, int)
                        or not isinstance(gate_target, int)
                        or not isinstance(gates, list)
                        or gate_target not in gates
                    ):
                        errors.append(
                            f"town {city_id} GATE align requires gateTargetNode (one north of visit) "
                            f"in gateNodes (visit={visit}, gateTarget={gate_target}, gates={gates})"
                        )
                    # Emit node must not be the raw H3 BR anchor when visit differs from BR.
                    if (
                        isinstance(city_id, int)
                        and city_id in placements_by_id
                        and isinstance(emit_node, int)
                        and placements_by_id[city_id].get("node") != emit_node
                    ):
                        errors.append(
                            f"town {city_id} map node {placements_by_id[city_id].get('node')} "
                            f"!= townGateAlign emitNode {emit_node}"
                        )
            pairing = objects_manifest.get("subterraneanGatePairing")
            if isinstance(pairing, dict) and isinstance(pairing.get("pairCount"), int) and pairing["pairCount"] > 0:
                props = map_data.get("objectsProperties") if isinstance(map_data.get("objectsProperties"), dict) else {}
                portals = props.get("propPortals") if isinstance(props.get("propPortals"), list) else []
                by_id = {
                    int(row["id"]): int(row.get("targetIdx"))
                    for row in portals
                    if isinstance(row, dict) and isinstance(row.get("id"), int)
                }
                for pair in pairing.get("pairs") or []:
                    if not isinstance(pair, dict):
                        continue
                    a = pair.get("surfaceObjectId")
                    b = pair.get("undergroundObjectId")
                    if not isinstance(a, int) or not isinstance(b, int):
                        errors.append("subterranean gate pair ids must be ints")
                        continue
                    if by_id.get(a) != b or by_id.get(b) != a:
                        errors.append(
                            f"subterranean gate pair {a}<->{b} missing mutual propPortals.targetIdx "
                            f"(got {by_id.get(a)} / {by_id.get(b)})"
                        )
                # All portal_5 instances must be paired when gates exist.
                portal5_ids = [
                    int(oid)
                    for group in (map_data.get("objects") or [])
                    if isinstance(group, dict) and group.get("sid") == "portal_5"
                    for oid in (group.get("ids") or [])
                    if isinstance(oid, int)
                ]
                for oid in portal5_ids:
                    target = by_id.get(oid, -1)
                    if not isinstance(target, int) or target < 0 or by_id.get(target) != oid:
                        errors.append(f"portal_5 id {oid} must have mutual targetIdx, got {target}")
        footprints = manifest.get("sceneryFootprints") if isinstance(manifest, dict) else None
        if not isinstance(footprints, dict):
            errors.append("manifest missing sceneryFootprints contract")
        else:
            if footprints.get("schema") != SCENERY_FOOTPRINT_SCHEMA:
                errors.append(f"manifest sceneryFootprints schema is invalid: {footprints.get('schema')!r}")
            if footprints.get("policy") != SCENERY_FOOTPRINT_POLICY:
                errors.append(f"manifest sceneryFootprints policy is invalid: {footprints.get('policy')!r}")
            if footprints.get("result") != "PASS" or footprints.get("mismatchCount") != 0:
                errors.append("manifest sceneryFootprints must report PASS with zero mismatches")
            if footprints.get("coreOverlayRequired") is not False:
                errors.append("stock scenery footprints must not require a Core overlay")
            rows = footprints.get("rows")
            if not isinstance(rows, list):
                errors.append("manifest sceneryFootprints.rows must be a list")
                rows = []
            footprint_validation["sourceObjectCount"] = len(rows)
            source_records_by_id: dict[int, dict[str, Any]] = {}
            source_h3m = manifest.get("sourceH3m")
            if isinstance(source_h3m, str):
                source_path = Path(source_h3m)
                if not source_path.is_absolute():
                    source_path = Path(__file__).resolve().parents[3] / source_path
                if source_path.is_file():
                    source_walk = walk_h3m_file(source_path, include_records=True)
                    source_records_by_id = {
                        int(record["index"]): record
                        for record in source_walk.get("records") or []
                        if isinstance(record, dict) and isinstance(record.get("index"), int)
                    }
                else:
                    errors.append(f"manifest sourceH3m is not readable: {source_path}")
            else:
                errors.append("manifest sourceH3m must be a path string")
            atlas_manifest = manifest.get("atlas") if isinstance(manifest.get("atlas"), dict) else {}
            source_width = atlas_manifest.get("sourceWidth")
            source_height = atlas_manifest.get("sourceHeight")
            atlas_width = atlas_manifest.get("atlasWidth")
            atlas_layers = atlas_manifest.get("layers") if isinstance(atlas_manifest.get("layers"), dict) else {}
            if not all(isinstance(value, int) and value > 0 for value in (source_width, source_height, atlas_width)):
                errors.append("manifest atlas lacks valid source/atlas dimensions for footprint validation")
            seen_footprint_placements: set[int] = set()
            for row in rows:
                if not isinstance(row, dict):
                    errors.append("scenery footprint row is not an object")
                    continue
                expected_nodes = row.get("expectedNodes")
                source_record = source_records_by_id.get(row.get("sourceObjectId"))
                if source_record is None:
                    errors.append(f"scenery footprint {row.get('sourceKey')} has no source H3M record")
                else:
                    if source_record.get("key") != row.get("sourceKey"):
                        errors.append(f"scenery footprint source key drift for object {row.get('sourceObjectId')}")
                    try:
                        decoded_offsets = raw_translation_source_block_offsets(source_record)
                    except VanillaStockSceneryFootprintError as ex:
                        errors.append(f"scenery footprint source mask is invalid: {ex}")
                        decoded_offsets = set()
                    reported_offsets = row.get("sourceBlockOffsets")
                    if not isinstance(reported_offsets, list) or {
                        tuple(value) for value in reported_offsets if isinstance(value, list) and len(value) == 2
                    } != decoded_offsets:
                        errors.append(f"scenery footprint {row.get('sourceKey')} source offsets differ from H3M")
                    if row.get("sourceBlockCount") != len(decoded_offsets):
                        errors.append(f"scenery footprint {row.get('sourceKey')} source block count differs from H3M")
                    layer_info = atlas_layers.get(str(source_record.get("layer")))
                    if (
                        isinstance(layer_info, dict)
                        and isinstance(layer_info.get("offsetX"), int)
                        and isinstance(layer_info.get("offsetY"), int)
                        and isinstance(source_width, int)
                        and isinstance(source_height, int)
                        and isinstance(atlas_width, int)
                    ):
                        source_x = int(source_record["x"])
                        source_y = int(source_record["y"])
                        independently_expected = sorted(
                            (
                                int(layer_info["offsetY"]) + source_height - 1 - (source_y + dy)
                            ) * atlas_width + int(layer_info["offsetX"]) + source_x + dx
                            for dx, dy in decoded_offsets
                            if 0 <= source_x + dx < source_width and 0 <= source_y + dy < source_height
                        )
                        if row.get("expectedNodesNote") == "pruned_after_gate_face_approach_clear":
                            # Gate-face approach clearing intentionally opens some source-blocked
                            # cells; pruned expectedNodes must be a subset of the H3 projection.
                            if not set(expected_nodes or []).issubset(set(independently_expected)):
                                errors.append(
                                    f"scenery footprint {row.get('sourceKey')} pruned nodes escape H3M projection"
                                )
                        elif expected_nodes != independently_expected:
                            errors.append(f"scenery footprint {row.get('sourceKey')} expected nodes differ from H3M projection")
                    else:
                        errors.append(f"scenery footprint {row.get('sourceKey')} has no valid atlas layer")
                placements = row.get("placements")
                if not isinstance(expected_nodes, list) or not all(isinstance(node, int) for node in expected_nodes):
                    errors.append(f"scenery footprint {row.get('sourceKey')} has invalid expectedNodes")
                    continue
                if not isinstance(placements, list) or not placements:
                    errors.append(f"scenery footprint {row.get('sourceKey')} has no placements")
                    continue
                actual_nodes: set[int] = set()
                for placement in placements:
                    if not isinstance(placement, dict) or not isinstance(placement.get("id"), int):
                        errors.append(f"scenery footprint {row.get('sourceKey')} has invalid placement")
                        continue
                    object_id = placement["id"]
                    if object_id in seen_footprint_placements:
                        errors.append(f"scenery footprint placement id reused: {object_id}")
                    seen_footprint_placements.add(object_id)
                    actual = placements_by_id.get(object_id)
                    if actual is None:
                        errors.append(f"scenery footprint placement id absent from map: {object_id}")
                        continue
                    for field in ("sid", "node", "rotation"):
                        if actual.get(field) != placement.get(field):
                            errors.append(
                                f"scenery footprint placement {object_id} {field} {actual.get(field)!r} != manifest {placement.get(field)!r}"
                            )
                    config = stock_object_configs.get(str(actual["sid"]))
                    if config is None:
                        errors.append(f"scenery footprint placement {object_id} has no stock ObjectConfig")
                        continue
                    try:
                        actual_nodes.update(
                            occupied_nodes_for_instance(
                                config,
                                anchor_node=int(actual["node"]),
                                rotation=int(actual["rotation"]),
                                width=int(width),
                                height=int(height),
                            )
                        )
                    except (VanillaStockSceneryFootprintError, TypeError, ValueError) as ex:
                        errors.append(f"scenery footprint placement {object_id} invalid: {ex}")
                if actual_nodes != set(expected_nodes):
                    footprint_validation["mismatchCount"] += 1
                    errors.append(
                        f"scenery footprint {row.get('sourceKey')} occupied nodes do not match source mask"
                    )
            footprint_validation["placementCount"] = len(seen_footprint_placements)
            if footprints.get("sourceObjectCount") != footprint_validation["sourceObjectCount"]:
                errors.append("manifest scenery footprint sourceObjectCount does not match rows")
            if footprints.get("placementCount") != footprint_validation["placementCount"]:
                errors.append("manifest scenery footprint placementCount does not match rows")
        victory_mode = ((manifest.get("victory") or {}) if isinstance(manifest, dict) else {}).get("mode")
        mine_entity_count = (manifest.get("victory") or {}).get("mineEntityCount")
        map_event_count = (manifest.get("events") or {}).get("eventCount")

    if expect_victory_mode is not None:
        victory_mode = expect_victory_mode
    if expect_mine_entity_count is not None:
        mine_entity_count = expect_mine_entity_count
    if expect_map_event_count is not None:
        map_event_count = expect_map_event_count

    props = map_data.get("objectsProperties") if isinstance(map_data.get("objectsProperties"), dict) else {}
    entities = props.get("propEntities") if isinstance(props.get("propEntities"), list) else []

    if victory_mode == "WINSTANDARD":
        if defeat_all is not True:
            errors.append("WINSTANDARD requires startSettings.DefeatAllEnemiesEnabled=true")
        blob = json.dumps(main_quests[0] if main_quests else {}, ensure_ascii=False)
        if "PlayerDefeated" not in blob or "GameVictory" not in blob:
            errors.append("WINSTANDARD MainQuest must include PlayerDefeated → GameVictory")
        name = (main_quests[0] or {}).get("name") if main_quests else None
        desc = (main_quests[0] or {}).get("desc") if main_quests else None
        for field_name, value in (("name", name), ("desc", desc)):
            if isinstance(value, str) and value.startswith(("tfp_", "gs_", "Loc:")):
                errors.append(f"WINSTANDARD quest {field_name} looks like a ghost Loc SID: {value!r}")
    elif victory_mode == "TAKEMINES":
        allow_normal = None
        if manifest_path is not None and manifest_path.is_file():
            allow_normal = (json.loads(manifest_path.read_text(encoding="utf-8")).get("victory") or {}).get(
                "allowNormalVictory"
            )
        if allow_normal is False and defeat_all is not False:
            errors.append("TAKEMINES with allow_normal_win=false requires DefeatAllEnemiesEnabled=false")
        if allow_normal is True and defeat_all is not True:
            errors.append("TAKEMINES with allow_normal_win=true requires DefeatAllEnemiesEnabled=true")
        if allow_normal is None and defeat_all not in (True, False):
            errors.append("TAKEMINES requires explicit DefeatAllEnemiesEnabled boolean")
        if not isinstance(mine_entity_count, int) or mine_entity_count <= 0:
            errors.append(
                "TAKEMINES validation requires mineEntityCount > 0 (pass manifest or expect_mine_entity_count)"
            )
        else:
            mine_entities = [
                e for e in entities if isinstance(e, dict) and str(e.get("sid") or "").startswith("mine")
            ]
            if len(mine_entities) != mine_entity_count:
                errors.append(
                    f"TAKEMINES propEntities mine count {len(mine_entities)} != expected {mine_entity_count}"
                )
            counter_sids = {c.get("sid") for c in counters if isinstance(c, dict)}
            if MINES_OWNED_COUNTER_SID not in counter_sids:
                errors.append(f"TAKEMINES missing counter {MINES_OWNED_COUNTER_SID}")
            blob = json.dumps(main_quests[0] if main_quests else {}, ensure_ascii=False)
            for token in ("ObjectCaptureEntity", "ObjectLose", "GameVictory", MINES_OWNED_COUNTER_SID):
                if token not in blob:
                    errors.append(f"TAKEMINES MainQuest missing {token}")
        name = (main_quests[0] or {}).get("name") if main_quests else None
        if isinstance(name, str) and name.startswith(("tfp_", "gs_", "Loc:")):
            errors.append(f"TAKEMINES quest name looks like a ghost Loc SID: {name!r}")

    if map_event_count is not None:
        events_manifest: dict[str, Any] = {}
        if manifest_path is not None and manifest_path.is_file():
            try:
                events_manifest = (
                    json.loads(manifest_path.read_text(encoding="utf-8")).get("events") or {}
                )
            except (OSError, json.JSONDecodeError, TypeError):
                events_manifest = {}
        if not isinstance(events_manifest, dict):
            events_manifest = {}
        unguarded_expected = events_manifest.get("unguardedCount")
        guarded_expected = events_manifest.get("guardedCount")
        if unguarded_expected is None or guarded_expected is None:
            # Fall back: all events were unguarded markers in older manifests.
            unguarded_expected = int(map_event_count)
            guarded_expected = 0
        if int(unguarded_expected) + int(guarded_expected) != int(map_event_count):
            errors.append(
                f"map event count {map_event_count} != unguarded({unguarded_expected})+"
                f"guarded({guarded_expected})"
            )

        marker_ids: list[int] = []
        markers = map_data.get("markers") if isinstance(map_data.get("markers"), list) else []
        for row in markers:
            if (
                isinstance(row, dict)
                and row.get("sid") == STOCK_MAP_EVENT_MARKER_SID
                and isinstance(row.get("id"), int)
            ):
                marker_ids.append(int(row["id"]))
        if len(marker_ids) != int(unguarded_expected):
            errors.append(
                f"unguarded Zone 1x1 marker count {len(marker_ids)} != expected {unguarded_expected}"
            )

        object_zone_ids: list[int] = []
        for group in objects:
            if isinstance(group, dict) and group.get("sid") == STOCK_MAP_EVENT_MARKER_SID:
                object_zone_ids.extend(
                    int(x) for x in (group.get("ids") or []) if isinstance(x, int)
                )
        if object_zone_ids:
            errors.append(
                "unguarded map events must use map markers[] Zone 1x1 hosts, "
                f"not objects[] instances: {object_zone_ids[:8]}"
            )

        guarded_ids = [
            int(x)
            for x in (events_manifest.get("guardedObjectIds") or [])
            if isinstance(x, int)
        ]
        if len(guarded_ids) != int(guarded_expected):
            errors.append(
                f"manifest guardedObjectIds count {len(guarded_ids)} != expected {guarded_expected}"
            )

        random_squad_ids: set[int] = set()
        for group in objects:
            if isinstance(group, dict) and group.get("sid") == STOCK_MAP_EVENT_GUARD_SID:
                random_squad_ids.update(
                    int(x) for x in (group.get("ids") or []) if isinstance(x, int)
                )
        missing_guard_hosts = [oid for oid in guarded_ids if oid not in random_squad_ids]
        if missing_guard_hosts:
            errors.append(
                f"guarded map events missing random-squad hosts: {missing_guard_hosts[:8]}"
            )

        prop_reward = props.get("propRewardParams") if isinstance(props.get("propRewardParams"), list) else []
        if prop_reward:
            errors.append(
                f"map events must not use propRewardParams (GiveRes is QuestScript-only); "
                f"got {len(prop_reward)}"
            )

        before = props.get("propActionsBefore") if isinstance(props.get("propActionsBefore"), list) else []
        dialog_before_ids = {
            int(row["id"])
            for row in before
            if isinstance(row, dict)
            and isinstance(row.get("id"), int)
            and int(row.get("type") or 0) == 1
            and any(
                isinstance(action, dict) and action.get("a") == "Dialog"
                for action in (row.get("actions") or [])
            )
        }
        unguarded_marker_ids = [
            int(x)
            for x in (events_manifest.get("unguardedMarkerIds") or marker_ids)
            if isinstance(x, int)
        ]
        if int(unguarded_expected) > 0:
            missing_dialog = [mid for mid in unguarded_marker_ids if mid not in dialog_before_ids]
            if missing_dialog:
                errors.append(
                    f"unguarded map events missing type-1 propActionsBefore Dialog: "
                    f"{missing_dialog[:8]}"
                )
            guarded_with_before_dialog = [oid for oid in guarded_ids if oid in dialog_before_ids]
            if guarded_with_before_dialog:
                errors.append(
                    "guarded map events must not use propActionsBefore Dialog "
                    f"(SquadInteraction owns dialog): {guarded_with_before_dialog[:8]}"
                )
            for row in before:
                if not isinstance(row, dict) or int(row.get("type") or 0) != 1:
                    continue
                if "computerActivate" in row:
                    errors.append(
                        f"propActionsBefore id={row.get('id')} must not set computerActivate "
                        "(not a native PropActionsBase field)"
                    )
                if row.get("sides") not in ("", None) and isinstance(row.get("sides"), str):
                    # Zero-based CSV only; reject one-based "1,2,..." full masks.
                    if row.get("sides") == "1,2,3,4,5,6,7,8":
                        errors.append(
                            f"propActionsBefore id={row.get('id')} uses one-based all-sides; "
                            "native Dialog hosts use sides=\"\""
                        )

        prop_markers = props.get("propMarkers") if isinstance(props.get("propMarkers"), list) else []
        prop_marker_ids = {
            int(row["id"])
            for row in prop_markers
            if isinstance(row, dict)
            and isinstance(row.get("id"), int)
            and int(row.get("type") or 0) == 1
        }
        if int(unguarded_expected) > 0:
            missing_prop_markers = [mid for mid in unguarded_marker_ids if mid not in prop_marker_ids]
            if missing_prop_markers:
                errors.append(
                    f"unguarded map events missing type-1 propMarkers: {missing_prop_markers[:8]}"
                )

        map_event_quests = [
            q
            for q in quests
            if isinstance(q, dict) and "_map_event_" in str(q.get("sid") or "")
        ]
        if len(map_event_quests) != int(map_event_count):
            errors.append(
                f"map-event QuestScript count {len(map_event_quests)} != expected {map_event_count}"
            )

        quest_blob = json.dumps(map_event_quests, ensure_ascii=False)
        if int(unguarded_expected) > 0 and "ObjectInteractionAfter" not in quest_blob:
            errors.append("unguarded map events require ObjectInteractionAfter QuestScript triggers")
        if int(guarded_expected) > 0:
            if "SquadInteraction" not in quest_blob:
                errors.append("guarded map events require SquadInteraction QuestScript triggers")
            if "SquadKill" not in quest_blob:
                errors.append("guarded map events require SquadKill QuestScript triggers")

        random_squad_props = (
            props.get("propRandomSquads") if isinstance(props.get("propRandomSquads"), list) else []
        )
        random_squad_prop_ids = {
            int(row["id"])
            for row in random_squad_props
            if isinstance(row, dict) and isinstance(row.get("id"), int)
        }
        missing_squad_props = [oid for oid in guarded_ids if oid not in random_squad_prop_ids]
        if missing_squad_props:
            errors.append(
                f"guarded map events missing propRandomSquads rows: {missing_squad_props[:8]}"
            )
        zero_value_squads = [
            int(row["id"])
            for row in random_squad_props
            if isinstance(row, dict)
            and isinstance(row.get("id"), int)
            and float(row.get("requestedValue") or 0) <= 0
        ]
        if zero_value_squads:
            errors.append(
                "propRandomSquads requestedValue must be > 0 "
                f"(SpawnsCreator otherwise emits empty stacks): {zero_value_squads[:8]}"
            )
        bad_fraction = [
            int(row["id"])
            for row in random_squad_props
            if isinstance(row, dict)
            and isinstance(row.get("id"), int)
            and not isinstance(row.get("fraction"), str)
        ]
        if bad_fraction:
            errors.append(
                "propRandomSquads.fraction must be a string (stock uses \"\" or faction sid); "
                f"non-string fraction on ids {bad_fraction[:8]}"
            )
        non_autobattle = [
            int(row["id"])
            for row in random_squad_props
            if isinstance(row, dict)
            and isinstance(row.get("id"), int)
            and row.get("isAutobatle") is not True
        ]
        if non_autobattle:
            errors.append(
                "propRandomSquads.isAutobatle must be true for neutrals/guards "
                "(enemy-hero auto is settings-gated); "
                f"false/missing on ids {non_autobattle[:8]}"
            )
        settings = (
            map_data.get("settings") if isinstance(map_data.get("settings"), dict) else {}
        )
        if settings.get("disableAutoBattleAgainstEnemyHeroes") is not True:
            errors.append(
                "settings.disableAutoBattleAgainstEnemyHeroes must be true; "
                f"got {settings.get('disableAutoBattleAgainstEnemyHeroes')!r}"
            )

        give_res_count = int(events_manifest.get("giveResActionCount") or 0)
        if give_res_count > 0 and "GiveRes" not in quest_blob:
            errors.append(
                f"map events recorded giveResActionCount={give_res_count} but QuestScript has no GiveRes"
            )
        remove_res_count = int(events_manifest.get("removeResActionCount") or 0)
        if remove_res_count > 0 and "RemoveRes" not in quest_blob:
            errors.append(
                f"map events recorded removeResActionCount={remove_res_count} but QuestScript has no RemoveRes"
            )
        spawn_count = int(events_manifest.get("spawnMapObjectActionCount") or 0)
        if spawn_count > 0 and "SpawnMapObject" not in quest_blob:
            errors.append(
                f"map events recorded spawnMapObjectActionCount={spawn_count} but QuestScript has no SpawnMapObject"
            )
        deco_expected = int(unguarded_expected)
        deco_ids = [
            int(x)
            for group in objects
            if isinstance(group, dict) and group.get("sid") == STOCK_MAP_EVENT_DECO_SID
            for x in (group.get("ids") or [])
            if isinstance(x, int)
        ]
        if len(deco_ids) != deco_expected:
            errors.append(
                f"unguarded event deco ({STOCK_MAP_EVENT_DECO_SID}) count {len(deco_ids)} "
                f"!= expected {deco_expected}"
            )

    timed = manifest.get("timedEvents") if isinstance(manifest, dict) else None
    if isinstance(timed, dict) and int(timed.get("briefingCount") or 0) > 0:
        if "StartTurn" not in json.dumps(quests, ensure_ascii=False):
            errors.append("timed briefings require StartTurn QuestScript conditions")
        if "Dialog" not in json.dumps(quests, ensure_ascii=False):
            errors.append("timed briefings require Dialog QuestScript actions")

    result = "PASS" if not errors else "FAIL"
    report = {
        "schema": SCHEMA_VALIDATION,
        "result": result,
        "mapPath": str(map_path),
        "mapSid": map_sid,
        "stockCore": str(stock_core),
        "stockTileAllowlist": sorted(allowed_tiles),
        "stockWaterAllowlist": sorted(allowed_waters),
        "viewsCount": len(views) if isinstance(views, list) else None,
        "dimensions": {"width": width, "height": height},
        "scenarioPlayerCount": (
            (meta.get("spawns") or {}).get("playersCount")
            if isinstance(meta.get("spawns"), dict)
            else None
        ),
        "emittedSidCount": len(set(emitted_sids)),
        "emittedSids": sorted(set(emitted_sids)),
        "coreOverlayPathsFound": overlay_markers,
        "victoryMode": victory_mode,
        "defeatAllEnemiesEnabled": defeat_all,
        "questCount": len(quests),
        "propEntityCount": len(entities),
        "mapWinConditionsCleared": map_win in ([], None) or map_win == [],
        "oceanBasinClimbContract": basin_climb_report,
        "sceneryFootprintContract": footprint_validation,
        "errors": errors,
    }
    if errors:
        raise VanillaStockValidationError(json.dumps(report, indent=2))
    return report
