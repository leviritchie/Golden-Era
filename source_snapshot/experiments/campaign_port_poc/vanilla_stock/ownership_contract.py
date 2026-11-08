"""Stock-safe ownership contract: faction split, orphan bind, compact renumber.

Wraps campaign helpers from ``approach_cell.surface_emit`` without importing
StoryHub/campaign-grant behavior. Fail-closed on illegal stock outcomes.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_APPROACH = Path(__file__).resolve().parents[1] / "approach_cell"
if str(_APPROACH) not in sys.path:
    sys.path.insert(0, str(_APPROACH))

import surface_emit as single  # noqa: E402

SCHEMA = "homm3.vanilla_stock.ownership_contract.v1"
PROOF_BOUNDARY = "generated_artifact_runtime_unvalidated"


class VanillaStockOwnershipError(ValueError):
    """Fail-closed ownership / spawn binding error."""


def h3_owner_to_provisional_olden(owner: Any) -> int | None:
    """Map H3 owner byte to provisional Olden 1-based index; neutral 255 → None."""
    if owner is None or owner == single.H3_NEUTRAL_OWNER:
        return None
    if not isinstance(owner, int) or owner < 0 or owner > 7:
        raise VanillaStockOwnershipError(f"unsupported H3 owner index {owner!r}")
    return owner + 1


def select_spawn_city_for_owner(
    *,
    owner: int,
    owned_cities: list[dict[str, Any]],
    scenario_player: dict[str, Any] | None,
) -> dict[str, Any]:
    """Choose the lobby spawn city for one provisional Olden owner."""
    if not owned_cities:
        raise VanillaStockOwnershipError(
            f"playable H3 scenario player has no owned town for spawn: {owner}"
        )
    main_town = scenario_player.get("mainTown") if isinstance(scenario_player, dict) else None
    if isinstance(main_town, dict):
        expected_position = {
            # H3 stores the main-town entrance two cells left of the placed
            # town object's binary anchor.
            "x": int(main_town["x"]) + 2,
            "y": int(main_town["y"]),
            "z": int(main_town["z"]),
        }
        candidates = [
            city for city in owned_cities if city.get("_sourcePosition") == expected_position
        ]
        if len(candidates) != 1:
            raise VanillaStockOwnershipError(
                f"H3 owner {owner} main town {expected_position} matched "
                f"{len(candidates)} owned town objects"
            )
        return {
            "owner": owner,
            "city": candidates[0],
            "cityObjectId": int(candidates[0]["id"]),
            "sourcePosition": candidates[0].get("_sourcePosition"),
            "ownedTownCount": len(owned_cities),
            "reason": "h3_designated_main_town",
        }
    if len(owned_cities) == 1:
        return {
            "owner": owner,
            "city": owned_cities[0],
            "cityObjectId": int(owned_cities[0]["id"]),
            "sourcePosition": owned_cities[0].get("_sourcePosition"),
            "ownedTownCount": 1,
            "reason": "only_owned_town",
        }
    chosen = min(owned_cities, key=lambda city: int(city["id"]))
    return {
        "owner": owner,
        "city": chosen,
        "cityObjectId": int(chosen["id"]),
        "sourcePosition": chosen.get("_sourcePosition"),
        "ownedTownCount": len(owned_cities),
        "reason": "lowest_source_object_id_when_h3_has_no_main_town",
    }


def bind_orphan_playable_owners_to_neutral_towns(
    city_rows: list[dict[str, Any]],
    *,
    playable_owners: set[int],
    human_olden_owner: int,
    entities_by_id: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Claim nearest unbound neutral towns for playable owners that own none.

    Vanilla omits HoMM3 hero objects, so the campaign hero-orphan helper is a
    no-op here. Playable AI sides without an owned town still need a City bind.
    """
    owned_by_owner: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for city in city_rows:
        owner = city.get("_owner")
        if isinstance(owner, int):
            owned_by_owner[owner].append(city)

    orphan_owners = sorted(
        owner
        for owner in playable_owners
        if owner != human_olden_owner and owner not in owned_by_owner
    )
    if not orphan_owners:
        return {
            "boundCount": 0,
            "bindings": [],
            "policy": "no_orphan_playable_ai_owners",
        }

    available: list[tuple[int, int, int, dict[str, Any]]] = []
    for city in city_rows:
        if city.get("_owner") is not None:
            continue
        object_id = int(city["id"])
        entity = entities_by_id.get(object_id) or {}
        x = int(entity.get("sourceX") if entity.get("sourceX") is not None else entity.get("x") or 0)
        y = int(entity.get("sourceY") if entity.get("sourceY") is not None else entity.get("y") or 0)
        available.append((object_id, x, y, city))
    if len(available) < len(orphan_owners):
        raise VanillaStockOwnershipError(
            f"orphan playable AI owners {orphan_owners} need towns but only "
            f"{len(available)} unbound neutral towns remain"
        )

    bindings: list[dict[str, Any]] = []
    used: set[int] = set()
    for olden_owner in orphan_owners:
        # Deterministic anchor: lowest available city id when no hero exists.
        candidates = [
            (object_id, x, y, city)
            for object_id, x, y, city in available
            if object_id not in used
        ]
        candidates.sort(key=lambda row: (row[0], row[1], row[2]))
        object_id, x, y, city = candidates[0]
        used.add(object_id)
        city["_owner"] = olden_owner
        bindings.append(
            {
                "oldenOwner": olden_owner,
                "cityObjectId": object_id,
                "citySourceXY": [x, y],
                "policy": "lowest_unbound_neutral_town_for_playable_ai",
            }
        )
    return {
        "boundCount": len(bindings),
        "bindings": bindings,
        "policy": "vanilla_stock_orphan_playable_ai_to_neutral_town",
        "proofBoundary": PROOF_BOUNDARY,
    }


def build_city_prop_spawns(
    *,
    city_rows: list[dict[str, Any]],
    scenario_players_by_olden_owner: dict[int, dict[str, Any]],
    spawn_city_id_by_owner: dict[int, int],
) -> list[dict[str, Any]]:
    """Emit City propSpawns for every owned town (required for faction split)."""
    rows: list[dict[str, Any]] = []
    for city in city_rows:
        owner = city.get("_owner")
        if not isinstance(owner, int):
            continue
        scenario_player = scenario_players_by_olden_owner.get(int(owner))
        if scenario_player is None:
            # Non-playable owned towns stay owned via propOwners only.
            continue
        spawn_type = 0 if scenario_player.get("canHuman") else 1
        if not scenario_player.get("canHuman") and not scenario_player.get("canComputer"):
            raise VanillaStockOwnershipError(
                f"playable H3 scenario player cannot be human or computer: {owner}"
            )
        rows.append(
            {
                "type": 0,
                "id": int(city["id"]),
                "owner": int(owner),
                "spawnType": spawn_type,
                "spawnPointType": single.OLDEN_SPAWN_POINT_TYPE_CITY,
                "isLocked": False,
                "_isLobbyPrimary": int(city["id"]) == spawn_city_id_by_owner.get(int(owner)),
                "_freeChoice": bool(city.get("_freeChoice")),
            }
        )
    return rows


def apply_ownership_contract(
    *,
    properties: dict[str, Any],
    city_rows: list[dict[str, Any]],
    scenario_header: dict[str, Any],
    entities_by_id: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Faction-split, orphan-bind, and compact-renumber into native owners 1..N.

    Mutates ``properties`` and ``city_rows`` in place. Returns a manifest report
    including the provisional→final owner mapping used by victory/events.
    """
    playable_rows = [
        row
        for row in (scenario_header.get("players") or [])
        if isinstance(row, dict) and isinstance(row.get("index"), int) and row.get("playable")
    ]
    scenario_players_by_olden_owner = {
        int(row["index"]) + 1: row for row in playable_rows
    }
    playable_owners = set(scenario_players_by_olden_owner)
    human_owners = sorted(
        owner
        for owner, row in scenario_players_by_olden_owner.items()
        if row.get("canHuman")
    )
    if not human_owners:
        raise VanillaStockOwnershipError("scenario has no human-capable playable player")
    # Prefer the lowest provisional human owner as the designated human seat.
    human_olden_owner = human_owners[0]

    orphan_report = bind_orphan_playable_owners_to_neutral_towns(
        city_rows,
        playable_owners=playable_owners,
        human_olden_owner=human_olden_owner,
        entities_by_id=entities_by_id,
    )

    spawn_selection_rows: list[dict[str, Any]] = []
    spawn_city_id_by_owner: dict[int, int] = {}
    for owner, scenario_player in sorted(scenario_players_by_olden_owner.items()):
        owned_cities = [city for city in city_rows if city.get("_owner") == owner]
        selection = select_spawn_city_for_owner(
            owner=owner,
            owned_cities=owned_cities,
            scenario_player=scenario_player,
        )
        spawn_city_id_by_owner[owner] = int(selection["cityObjectId"])
        spawn_selection_rows.append(
            {
                "owner": owner,
                "cityObjectId": int(selection["cityObjectId"]),
                "sourcePosition": selection.get("sourcePosition"),
                "ownedTownCount": selection["ownedTownCount"],
                "reason": selection["reason"],
            }
        )

    # Materialize cities into properties before ownership mutations.
    properties["propCities"] = []
    properties["propOwners"] = []
    properties["propSpawns"] = []
    free_choice_city_ids: set[int] = set()
    for city in city_rows:
        owner = city.get("_owner")
        free_choice = bool(city.get("_freeChoice"))
        if free_choice:
            free_choice_city_ids.add(int(city["id"]))
        city_row = {
            "type": 0,
            "id": int(city["id"]),
            "isDefined": True,
            "factionSid": str(city.get("factionSid") or ""),
            "spawnHero": True,
            "buildingsConstructionSid": city["buildingsConstructionSid"],
            "buildingsBanSid": city["buildingsBanSid"],
            "buildingsSettingsSid": city["buildingsSettingsSid"],
            "customCityName": city.get("customCityName") or "",
        }
        if isinstance(owner, int):
            # Keep owner on the city row so compact renumber rewrites it.
            city_row["owner"] = int(owner)
        properties["propCities"].append(city_row)

    spawn_rows = build_city_prop_spawns(
        city_rows=city_rows,
        scenario_players_by_olden_owner=scenario_players_by_olden_owner,
        spawn_city_id_by_owner=spawn_city_id_by_owner,
    )
    # Secondary owned towns that are not playable-side seats still need ownership.
    spawned_ids = {int(row["id"]) for row in spawn_rows}
    for city in city_rows:
        owner = city.get("_owner")
        if not isinstance(owner, int):
            continue
        if int(city["id"]) in spawned_ids:
            continue
        properties["propOwners"].append(
            {"type": 0, "id": int(city["id"]), "owner": int(owner)}
        )

    # Faction-split planner refuses empty factionSid. Plan using locked cities only.
    locked_spawn_rows = [
        {k: v for k, v in row.items() if not str(k).startswith("_")}
        for row in spawn_rows
        if int(row["id"]) not in free_choice_city_ids
    ]
    free_choice_spawn_rows = [
        {k: v for k, v in row.items() if not str(k).startswith("_")}
        for row in spawn_rows
        if int(row["id"]) in free_choice_city_ids
    ]
    properties["propSpawns"] = list(locked_spawn_rows)
    reserved_owners = {
        int(row["owner"])
        for row in spawn_rows
        if isinstance(row, dict) and isinstance(row.get("owner"), int)
    }
    demoted_mixed_faction_cities: list[dict[str, Any]] = []
    try:
        remaps = single.plan_ai_multi_faction_city_owner_split(
            properties,
            human_olden_owner=human_olden_owner,
            protect_city_ids=None,
        )
        # Planner only sees locked City propSpawns, so it may hand synthetic
        # minority owners numbers already reserved by free-choice / other
        # playable seats restored after the plan. Reassign collisions; when no
        # seat remains (8 playable colors), demote the minority city to neutral.
        taken = set(reserved_owners)
        free_owners = [
            owner
            for owner in range(1, 9)
            if owner not in taken and owner != human_olden_owner
        ]
        free_index = 0
        collision_safe_remaps: dict[int, int] = {}
        for object_id, new_owner in sorted(remaps.items()):
            if new_owner in reserved_owners:
                if free_index >= len(free_owners):
                    demoted_mixed_faction_cities.append(
                        {
                            "cityObjectId": int(object_id),
                            "refusedSyntheticOwner": int(new_owner),
                            "reason": "no_free_olden_owner_after_reserving_playable_seats",
                        }
                    )
                    continue
                new_owner = free_owners[free_index]
                free_index += 1
                taken.add(new_owner)
            collision_safe_remaps[int(object_id)] = int(new_owner)
        remaps = collision_safe_remaps
        split_report = single.apply_explicit_ai_owner_faction_split(
            properties,
            remaps=remaps,
        )
    except ValueError as ex:
        raise VanillaStockOwnershipError(str(ex)) from ex

    if demoted_mixed_faction_cities:
        demoted_ids = {int(row["cityObjectId"]) for row in demoted_mixed_faction_cities}
        properties["propSpawns"] = [
            row
            for row in (properties.get("propSpawns") or [])
            if not (isinstance(row, dict) and int(row.get("id") or -1) in demoted_ids)
        ]
        for city in properties.get("propCities") or []:
            if isinstance(city, dict) and int(city.get("id") or -1) in demoted_ids:
                city.pop("owner", None)
        for city in city_rows:
            if int(city.get("id") or -1) in demoted_ids:
                city["_owner"] = None

    split_report["splitPolicy"] = (
        "auto_majority_keep_minority_city_owner_split_reserve_playable_owners"
    )
    split_report["protectedFreeChoiceCityIds"] = sorted(free_choice_city_ids)
    split_report["reservedPlayableOwners"] = sorted(reserved_owners)
    split_report["demotedMixedFactionCities"] = demoted_mixed_faction_cities
    split_report["proofBoundary"] = (
        "generated_artifact; minority towns demoted to neutral when all Olden "
        "owners 1..8 are already playable seats — runtime capture unvalidated"
    )

    # Restore free-choice City propSpawns on their provisional owners.
    properties["propSpawns"] = list(properties.get("propSpawns") or []) + free_choice_spawn_rows

    # Shared hero-orphan helper remains available; vanilla currently omits heroes.
    try:
        shared_orphan = single.bind_orphan_ai_owners_to_neutral_towns(
            properties,
            entities_by_id,
            human_olden_owner=human_olden_owner,
        )
    except ValueError as ex:
        raise VanillaStockOwnershipError(str(ex)) from ex

    # Track provisional owners before compact renumber (includes synthetic splits).
    provisional_owners = sorted(
        {
            int(row["owner"])
            for row in (properties.get("propSpawns") or [])
            if isinstance(row, dict) and isinstance(row.get("owner"), int)
        }
    )
    provisional_to_h3: dict[int, int | None] = {}
    for owner in provisional_owners:
        if owner in scenario_players_by_olden_owner:
            provisional_to_h3[owner] = owner - 1
        else:
            # Synthetic split owners inherit the H3 color of the city they came from.
            provisional_to_h3[owner] = None

    # Fill synthetic → H3 using remap before/after from split report.
    # Never overwrite an existing playable provisional→H3 mapping (reserved seats).
    owners_map = split_report.get("owners") or {}
    for object_id_str, change in owners_map.items():
        if not isinstance(change, dict):
            continue
        before = change.get("before")
        after = change.get("after")
        if not isinstance(before, int) or not isinstance(after, int):
            continue
        if after in scenario_players_by_olden_owner:
            continue
        if before in scenario_players_by_olden_owner:
            provisional_to_h3[after] = before - 1

    try:
        renumber = single.renumber_map_owners_to_native_compact(
            properties,
            human_olden_owner=human_olden_owner,
        )
    except ValueError as ex:
        raise VanillaStockOwnershipError(str(ex)) from ex

    owner_mapping_raw = {
        int(k): int(v) for k, v in (renumber.get("ownerMapping") or {}).items()
    }
    final_human = int(renumber["humanOldenOwner"])
    if final_human != 1:
        raise VanillaStockOwnershipError(
            f"compact renumber must place human at owner 1; got {final_human}"
        )

    # h3Color → list of final native owners (expanded for faction splits).
    h3_to_final: dict[int, list[int]] = defaultdict(list)
    for provisional, final in sorted(owner_mapping_raw.items()):
        h3 = provisional_to_h3.get(provisional)
        if h3 is None and provisional in scenario_players_by_olden_owner:
            h3 = provisional - 1
        if h3 is None:
            continue
        if final not in h3_to_final[h3]:
            h3_to_final[h3].append(final)
    for h3 in list(h3_to_final):
        h3_to_final[h3] = sorted(h3_to_final[h3])

    # Sync city_rows owners to final numbering for later lobby hero assignment.
    for city in city_rows:
        owner = city.get("_owner")
        if isinstance(owner, int) and owner in owner_mapping_raw:
            city["_owner"] = owner_mapping_raw[owner]

    # Rewrite spawn selection rows to final owners / surviving primary cities.
    final_spawn_selection: list[dict[str, Any]] = []
    final_primary_by_owner: dict[int, int] = {}
    city_by_id = {
        int(row["id"]): row
        for row in (properties.get("propCities") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }
    for row in properties.get("propSpawns") or []:
        if not isinstance(row, dict):
            continue
        if row.get("spawnPointType") != single.OLDEN_SPAWN_POINT_TYPE_CITY:
            continue
        owner = int(row["owner"])
        object_id = int(row["id"])
        # Prefer previously selected primary when it still belongs to this owner.
        prior_primary = None
        for sel in spawn_selection_rows:
            prior_provisional = int(sel["owner"])
            if owner_mapping_raw.get(prior_provisional) == owner:
                if int(sel["cityObjectId"]) == object_id:
                    prior_primary = object_id
                    break
        if owner not in final_primary_by_owner:
            final_primary_by_owner[owner] = prior_primary or object_id
        elif prior_primary is not None:
            final_primary_by_owner[owner] = prior_primary

    for owner, city_id in sorted(final_primary_by_owner.items()):
        city = city_by_id.get(city_id) or {}
        final_spawn_selection.append(
            {
                "owner": owner,
                "cityObjectId": city_id,
                "factionSid": city.get("factionSid"),
                "reason": "post_ownership_contract_primary",
            }
        )

    human_start_audit = {
        "policy": "vanilla_stock_city_mainTown_only",
        "promotionRequired": False,
        "reason": (
            "vanilla_stock omits HoMM3 hero objects and always binds lobby starts "
            "through owned City propSpawns + mainTown/lowest-id selection"
        ),
        "humanOwner": 1,
        "humanPrimaryCityObjectId": final_primary_by_owner.get(1),
    }
    if 1 not in final_primary_by_owner:
        raise VanillaStockOwnershipError(
            "human owner 1 has no City propSpawn after ownership contract"
        )

    return {
        "schema": SCHEMA,
        "proofBoundary": PROOF_BOUNDARY,
        "humanOldenOwner": 1,
        "provisionalHumanOldenOwner": human_olden_owner,
        "playersCount": int(renumber["playersCount"]),
        "ownerMapping": {str(k): v for k, v in sorted(owner_mapping_raw.items())},
        "h3ColorToFinalOwners": {
            str(k): v for k, v in sorted(h3_to_final.items())
        },
        "aiOwnerFactionSplit": split_report,
        "orphanPlayableNeutralTownBind": orphan_report,
        "orphanAiNeutralTownBind": shared_orphan,
        "ownerRenumber": renumber,
        "spawnSelectionProvisional": spawn_selection_rows,
        "spawnSelection": final_spawn_selection,
        "lobbyPrimaryCityByOwner": {
            str(k): v for k, v in sorted(final_primary_by_owner.items())
        },
        "humanStartAudit": human_start_audit,
        "freeChoiceCityIds": sorted(free_choice_city_ids),
    }


def translate_h3_players_mask_to_final_sides(
    players_mask: Any,
    *,
    h3_color_to_final_owners: dict[int, list[int]],
) -> str:
    """Encode event audience as zero-based CSV of final native owners.

    Empty string remains the stock all-players sentinel (mask 0 / 255 / unset).
    Partial masks expand through faction-split owner lists. H3 colors that never
    received a native spawn seat are dropped (common on AB/SoD event masks that
    include unused player colors); if every bit is dropped, fail closed.
    """
    if not isinstance(players_mask, int) or players_mask <= 0:
        return ""
    if players_mask == 255:
        return ""
    final_owners: list[int] = []
    dropped_colors: list[int] = []
    for h3_color in range(8):
        if not (players_mask & (1 << h3_color)):
            continue
        mapped = h3_color_to_final_owners.get(h3_color)
        if not mapped:
            dropped_colors.append(h3_color)
            continue
        for owner in mapped:
            if owner not in final_owners:
                final_owners.append(owner)
    if not final_owners:
        raise VanillaStockOwnershipError(
            f"playersMask {players_mask} selected no final native owners "
            f"(dropped unbound H3 colors {dropped_colors})"
        )
    # propActions*.sides is zero-based (owner 1 → \"0\").
    return ",".join(str(owner - 1) for owner in sorted(final_owners))


def final_owners_for_h3_colors(
    h3_colors: list[int],
    *,
    h3_color_to_final_owners: dict[int, list[int]],
) -> list[int]:
    out: list[int] = []
    for color in h3_colors:
        mapped = h3_color_to_final_owners.get(int(color))
        if not mapped:
            raise VanillaStockOwnershipError(
                f"H3 color {color} has no final native owners after ownership contract"
            )
        for owner in mapped:
            if owner not in out:
                out.append(owner)
    return sorted(out)
