#!/usr/bin/env python3
"""Shared raw_translation map orchestrator — emit-only 1:1 placements.

Profile-driven: every campaign mission (Homecoming included) is emitted through
this one module, selected by the scenario profile passed to generate_map().

Imports approach_cell leaves only (surface_emit / layer_atlas / layered_objects).
Never imports the approach_cell orchestrator or the retired post-pass modules
listed in the forbidden-module guard below.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_PKG = Path(__file__).resolve().parent
_POC = _PKG.parent
_APPROACH = _POC / "approach_cell"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))
if str(_APPROACH) not in sys.path:
    sys.path.insert(0, str(_APPROACH))

import campaign_ocean
import campaign_runtime_script as campaign_script
import campaign_placed_hero_payloads as hero_payloads
import campaign_victory
import emit_policy
import h3m_format as h3m
import h3m_hero_sid
import h3m_town_construction as town_construction
import homecoming_localization as homecoming_lang
import gate_face_rotation
import landon_access
import layer_atlas as atlas
import layered_objects as lob
import object_property_namespaces as propns
import port_homecoming_poc as poc
import placement_ground_truth
import scenario_menu_shell
import surface_emit as single
import visual_scenery_canon_postpass
import entrance_occupancy
import homm3_footprint_compatibility
import homm3_bank_remapping
import border_guard_gates
import object_billboards
import campaign_hero_level_cap
from campaign_mission import load_batch_manifest
from h3c_mission_source import load_h3c_block
from scenario_profile import ScenarioProfile, load_scenario_profile

_BATCH_MANIFEST_CANDIDATES = (
    Path("scenarios/roe_castle_campaign/batch_manifest.json"),
    Path("scenarios/roe_remaining_campaigns/batch_manifest.json"),
    Path("scenarios/ab_sod_campaigns/batch_manifest.json"),
)


def _mission_for_profile(profile: ScenarioProfile):
    """Resolve campaignEntry/blockIndex for this profile's scenarioId."""

    scenario_id = profile.scenario_id
    mission_id = lob.mission_id_from_profile(profile)
    configured = getattr(profile, "batch_manifest_path", None)
    if configured is not None:
        paths = (Path(configured).resolve(),)
    else:
        paths = tuple(poc.ROOT / rel for rel in _BATCH_MANIFEST_CANDIDATES)

    matches: list[tuple[Path, Any]] = []
    for path in paths:
        if not path.is_file():
            continue
        batch = load_batch_manifest(path)
        for mission in batch.missions:
            if mission.scenario_id == scenario_id or mission.mission_id == mission_id:
                matches.append((path, mission))
    if len(matches) == 1:
        return matches[0][1]
    if not matches:
        raise ValueError(
            f"no batch manifest mission for scenarioId={scenario_id!r}; "
            f"checked {[str(p) for p in paths]}"
        )
    raise ValueError(
        f"ambiguous batch manifest mission for scenarioId={scenario_id!r}, "
        f"missionId={mission_id!r}: "
        f"{[(str(path), mission.mission_id) for path, mission in matches]}"
    )


def _replace_group_member_sid(
    objects: list[dict[str, Any]],
    *,
    object_id: int,
    replacement_sid: str | None,
) -> int:
    """Remove one grouped object member, optionally re-emitting it under another SID."""
    for group in list(objects):
        ids = group.get("ids") or []
        if object_id not in ids:
            continue
        index = ids.index(object_id)
        node = int((group.get("nodes") or [])[index])
        member = {
            key: [value[index]]
            for key, value in group.items()
            if key != "sid" and isinstance(value, list) and index < len(value)
        }
        for key, value in list(group.items()):
            if key != "sid" and isinstance(value, list) and index < len(value):
                del value[index]
        if not group.get("ids"):
            objects.remove(group)
        if replacement_sid is not None:
            target = next((row for row in objects if row.get("sid") == replacement_sid), None)
            if target is None:
                target = {"sid": replacement_sid}
                objects.append(target)
            for key, values in member.items():
                target.setdefault(key, []).extend(values)
        return node
    raise ValueError(f"map event object {object_id} was not emitted")


def _object_sid_by_id(objects: list[dict[str, Any]], object_id: int) -> str | None:
    for group in objects:
        if not isinstance(group, dict):
            continue
        ids = group.get("ids") or []
        if object_id in ids:
            sid = group.get("sid")
            return str(sid) if isinstance(sid, str) else None
    return None


def apply_native_map_event_hosts(
    *,
    global_entities: list[dict[str, Any]],
    objects: list[dict[str, Any]],
    properties: dict[str, Any],
    event_specs: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    """Translate H3 map events into native invisible zones, guarded squads, or hero hosts.

    Returns (zone_markers, host_ledger). ``zone_markers`` are only Zone 1x1 rows for the
    map body; ``host_ledger`` maps sourceIndex → hostMode for placement GT (includes
    guarded random-squad and colocated-hero hosts that are not zone markers).
    """
    event_entities = [
        row
        for row in global_entities
        if row.get("category") == "map_event"
        or row.get("payloadKind") in {"map_event", "event"}
    ]
    if len(event_entities) != len(event_specs):
        raise ValueError(
            "decoded map-event count does not match semantic event specs: "
            f"{len(event_entities)} entities versus {len(event_specs)} specs"
        )

    markers: list[dict[str, Any]] = []
    host_ledger: dict[int, dict[str, Any]] = {}
    for entity in event_entities:
        source_key = str(entity.get("sourceKey") or "")
        object_id = entity.get("sourceIndex")
        spec = event_specs.get(source_key)
        if not isinstance(object_id, int) or not isinstance(spec, dict):
            raise ValueError(f"map event {source_key!r} lacks an emitted semantic binding")
        expected_entity_sid = str(
            spec.get("squadEntitySid") if spec.get("hasGuards") else spec.get("entitySid")
        )
        entity_rows = [
            row
            for row in (properties.get("propEntities") or [])
            if isinstance(row, dict) and row.get("sid") == expected_entity_sid
        ]
        if len(entity_rows) != 1:
            raise ValueError(
                f"map event {source_key!r} requires one entity row for {expected_entity_sid!r}; "
                f"found {len(entity_rows)}"
            )
        if entity_rows[0].get("id") != object_id:
            # A generation pass already rebound this event to a real interactable
            # (for example Homecoming's Guardhouse dwelling). Keep that proven host.
            host_ledger[object_id] = {
                "sourceKey": source_key,
                "hostMode": "prebound_interactable_host",
                "hostObjectId": int(entity_rows[0]["id"]),
            }
            continue

        host_lifetime = str(spec.get("hostLifetime") or campaign_script.DISPOSABLE_MARKER_HOST_LIFETIME)
        colocated_hero_id = spec.get("colocatedHeroHostSourceIndex")
        if host_lifetime == campaign_script.COLOCATED_HERO_HOST_LIFETIME:
            if not isinstance(colocated_hero_id, int):
                raise ValueError(
                    f"map event {source_key!r} colocated_hero_host missing colocatedHeroHostSourceIndex"
                )
            hero_sid = _object_sid_by_id(objects, colocated_hero_id)
            # Engagement contract: keep hero-spawner (tile engage). Never convert to
            # random-squad (adjacent ZoC). HoMM3 heroes do not adjacent-ZoC.
            if hero_sid != "hero-spawner":
                raise ValueError(
                    f"map event {source_key!r} colocated hero host {colocated_hero_id} "
                    f"must remain hero-spawner; found {hero_sid!r}"
                )
            landon_access.bind_map_event_dialog_to_host(
                properties,
                event_id=object_id,
                host_id=colocated_hero_id,
                policy="raw_colocated_hero_event_dialog_on_hero_spawner",
                host_lifetime=campaign_script.COLOCATED_HERO_HOST_LIFETIME,
                dialog_delivery="hero_interruption",
            )
            _replace_group_member_sid(objects, object_id=object_id, replacement_sid=None)
            host_ledger[object_id] = {
                "sourceKey": source_key,
                "hostMode": "colocated_hero_host",
                "hostObjectId": colocated_hero_id,
                "sid": "hero-spawner",
            }
            continue

        if spec.get("hasGuards"):
            _replace_group_member_sid(
                objects,
                object_id=object_id,
                replacement_sid="random-squad",
            )
            host_ledger[object_id] = {
                "sourceKey": source_key,
                "hostMode": "guarded_random_squad",
                "sid": "random-squad",
            }
            continue

        node = _replace_group_member_sid(objects, object_id=object_id, replacement_sid=None)
        marker_id = len(markers)
        remove_after_visit = bool(spec.get("removeAfterVisit"))
        action_repeat = bool(spec.get("actionRepeat", False))
        # propAiIntetations must rebound with Dialog hosts. Leaving it on the deleted
        # object id (or stripping it in the catch-all below) drops computerActivate=false
        # aiIgnore and lets AI sides consume narrative Dialog.
        rebound_families = {
            "propEntities",
            "propActionsBefore",
            "propActionsAfter",
            "propAiIntetations",
        }
        for family in rebound_families:
            for row in properties.get(family) or []:
                if row.get("type") == 0 and row.get("id") == object_id:
                    row["type"] = 1
                    row["id"] = marker_id
                    if family in {"propActionsBefore", "propActionsAfter"}:
                        # Lifetime recurrence is independent of isDelete (vanilla c_M2).
                        row["repeat"] = bool(action_repeat and family == "propActionsBefore")
        for family, rows in properties.items():
            if family in rebound_families or not isinstance(rows, list):
                continue
            rows[:] = [
                row
                for row in rows
                if not (isinstance(row, dict) and row.get("type") == 0 and row.get("id") == object_id)
            ]
        properties.setdefault("propMarkers", []).append(
            {
                "type": 1,
                "id": marker_id,
                "isDelete": remove_after_visit,
                "isActivate": True,
            }
        )
        marker = {
            "node": node,
            "v": "",
            "sid": "Zone 1x1",
            "id": marker_id,
            "sourceIndex": object_id,
            "sourceKey": source_key,
            "hostMode": "invisible_zone_marker",
        }
        markers.append(marker)
        host_ledger[object_id] = {
            "sourceKey": source_key,
            "hostMode": "invisible_zone_marker",
            "sid": "Zone 1x1",
            "markerId": marker_id,
            "node": node,
        }
    return markers, host_ledger


def rebase_native_event_marker_ids(
    *,
    markers: list[dict[str, Any]],
    properties: dict[str, Any],
    areas: list[dict[str, Any]],
) -> int:
    """Allocate marker ids after area ids, matching native Story-map namespaces."""
    first_marker_id = max(
        (int(row["id"]) for row in areas if isinstance(row.get("id"), int)),
        default=-1,
    ) + 1
    id_remap = {
        int(marker["id"]): first_marker_id + index
        for index, marker in enumerate(markers)
    }
    for marker in markers:
        marker["id"] = id_remap[int(marker["id"])]
    for family, rows in list(properties.items()):
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not propns.is_marker_property_row(row):
                continue
            old_id = row.get("id")
            if old_id in id_remap:
                row["id"] = id_remap[int(old_id)]
    return first_marker_id + len(markers)

# Native custom-area maps (Thirst / zone atlas) use areasVersion 858 with full area rows.
# Stripped {id,nodes}+version 1 is only seen on unfinished shells and is a pickup/interact suspect.
NATIVE_CUSTOM_AREAS_VERSION = 858
_TILE_BIOME_BY_ID: dict[int, str] = {
    1: "Grass",
    2: "Sand",
    4: "Snow",
    6: "Lava",
    7: "Dirt",
    8: "Swamp",
    15: "Burrow",
    23: "Void",
}
_TOWN_SIDS = frozenset({
    "homm3_landon_castle_city",
    "homm3_landon_dungeon_city",
    "homm3_castle_city",
    "homm3_dungeon_city",
})

FORBIDDEN_IMPORT_NAMES = (
    "functional_points",
    "footprint_alignment",
    "block_parity",
    "accessibility_repair",
    "mountain_merge",
    "local_1c",
    "domains",
    "must_fight_catalogue",
    "soft_grid",
    "build_homecoming_approach_cell_map",
    "build_layered_atlas_map",
    "build_homecoming_layered_atlas_map",
    "build_campaign_layered_atlas_batch",
)

DEFAULT_PROFILE = (
    Path(poc.ROOT) / "scenarios" / "homecoming_roe_castle" / "raw_translation.profile.json"
)
SCHEMA = "homm3.olden_raw_translation_map.v1"
PIPELINE = "raw_translation"
EMIT_POLICY = emit_policy.RAW_TRANSLATION_EMIT_POLICY

def ensure_campaign_granted_start_hero(
    entities: list[dict[str, Any]],
    profile: ScenarioProfile,
    substitution_lookup: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Bind campaign-granted starts to the H3M mainTown (no synthetic hero-spawner).

    Some RoE campaign maps (Deal With the Devil, Neutral Affairs, A Gryphon's
    Heart, Griffin Cliff, …) grant the opening hero from the campaign shell /
    H3M ``mainTown.generateHero`` instead of embedding a map hero. Stacking a
    3x3 ``hero-spawner`` on the town GATE puts the hero body into the town
    billboard (``bodyOverlap``). Native OE / brine_bell equivalents use the
    town as the human City propSpawn with ``spawnHero`` and ``propHeroes`` on
    that city id.

    When startHeroContract matches nothing, grant the anchor town to the human
    (if neutral) and return a report consumed by
    ``apply_campaign_granted_city_start_contract``. Do not invent a synthetic
    hero entity — that path is retired.
    """
    del substitution_lookup  # retained in signature for call-site compatibility
    contract = profile.start_hero_contract
    if any(contract.matches_entity(entity) for entity in entities):
        return entities, None
    if not contract.source_key:
        raise ValueError(
            f"{profile.scenario_id}: no map entity matches startHeroContract and "
            "sourceKey town anchor is missing for campaign-granted synthesis"
        )
    parts = str(contract.source_key).split(":")
    if len(parts) != 3:
        raise ValueError(f"invalid campaign start sourceKey {contract.source_key!r}")
    town = None
    for entity in entities:
        if entity.get("sourceKey") == contract.source_key and entity.get("payloadKind") == "town":
            town = entity
            break
    if town is None:
        raise ValueError(
            f"campaign-granted start sourceKey {contract.source_key!r} does not match a town entity"
        )
    town_owner = int(town.get("owner", -1))
    contract_owner = int(contract.owner)
    # Neutral towns (255) and the human's own towns are valid grant anchors.
    # Owner-0 is only valid when the human H3 color is also 0 (otherwise we
    # would steal a red AI castle). Enemy AI towns are refused.
    if town_owner == contract_owner:
        ownership_grant = None
    elif town_owner in (255, 0xFF):
        town["owner"] = contract_owner
        town["campaignGrantedOwnership"] = True
        ownership_grant = {
            "fromOwner": town_owner,
            "toOwner": contract_owner,
            "sourceKey": contract.source_key,
            "sourceIndex": town.get("sourceIndex"),
            "policy": "neutral_town_granted_to_campaign_human",
        }
    elif town_owner == 0 and contract_owner == 0:
        ownership_grant = None
    else:
        raise ValueError(
            f"campaign-granted start town {contract.source_key} owner {town.get('owner')} "
            f"!= contract owner {contract.owner} and is not neutral; refusing to steal an AI town"
        )
    town_id = town.get("sourceIndex")
    if not isinstance(town_id, int):
        raise ValueError(
            f"campaign-granted start town {contract.source_key!r} missing integer sourceIndex"
        )
    report = {
        "anchorTownSourceKey": contract.source_key,
        "anchorTownSourceIndex": town_id,
        "ownershipGrant": ownership_grant,
        "policy": "campaign_granted_city_spawn_start",
        "proofBoundary": (
            "source/static: HoMM3 mainTown.generateHero maps to Olden City propSpawn + "
            "spawnHero + propHeroes on the town id (brine_bell / vanilla_stock shape); "
            "runtime standing on town GATE and ownership still user-unvalidated"
        ),
    }
    return entities, report


def _object_instance_fields(
    objects: list[dict[str, Any]],
    object_id: int,
) -> tuple[dict[str, Any], int]:
    for group in objects:
        ids = group.get("ids") or []
        if not isinstance(ids, list):
            continue
        for index, oid in enumerate(ids):
            if oid == object_id:
                return group, index
    raise ValueError(f"object id {object_id} not found in objects[]")


def apply_campaign_granted_city_start_contract(
    objects: list[dict[str, Any]],
    properties: dict[str, Any],
    *,
    town_object_id: int,
    human_h3_owner: int,
    human_hero_sid: str,
) -> dict[str, Any]:
    """Bind the human start to the grant town as City + spawnHero + propHeroes.

    Fail-closed if the town object or ``propCities`` row is missing. Does not
    emit or require a ``hero-spawner``.
    """
    del objects  # town presence is verified via propCities / callers
    hero_sid = str(human_hero_sid or "").strip()
    if not hero_sid:
        raise ValueError("campaign-granted city start requires non-empty human_hero_sid")
    city_rows = [
        row
        for row in (properties.get("propCities") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    ]
    city = next((row for row in city_rows if int(row["id"]) == town_object_id), None)
    if city is None:
        raise ValueError(
            f"campaign-granted town {town_object_id} missing from propCities; "
            "cannot bind City start"
        )
    city["spawnHero"] = True
    olden_owner = h3m_hero_sid.h3_owner_to_olden_player_index(human_h3_owner)
    city_spawn = {
        "type": 0,
        "id": town_object_id,
        "owner": olden_owner,
        "spawnType": single.OLDEN_SPAWN_TYPE_HUMAN,
        "spawnPointType": single.OLDEN_SPAWN_POINT_TYPE_CITY,
        "isLocked": False,
    }
    spawn_rows = [
        row
        for row in (properties.get("propSpawns") or [])
        if isinstance(row, dict) and row.get("id") != town_object_id
    ]
    properties["propSpawns"] = [city_spawn, *spawn_rows]
    existing_heroes = [
        row
        for row in (properties.get("propHeroes") or [])
        if isinstance(row, dict) and row.get("id") != town_object_id
    ]
    properties["propHeroes"] = [
        {"type": 0, "id": town_object_id, "isDefined": True, "heroSid": hero_sid},
        *existing_heroes,
    ]
    return {
        "status": "applied",
        "policy": "campaign_granted_city_spawn_plus_spawn_hero",
        "townObjectId": town_object_id,
        "oldenOwner": olden_owner,
        "heroSid": hero_sid,
        "spawnHero": True,
    }


def clear_campaign_granted_town_gate_blockers(
    objects: list[dict[str, Any]],
    *,
    campaign_granted_start: dict[str, Any],
    native_object_configs: dict[str, dict[str, Any]],
    width: int,
    height: int,
    emit: Any,
) -> dict[str, Any]:
    """Clear gap-fill / suppressible scenery occupying the grant town GATE.

    City+spawnHero starts the avatar on the town entrance; gap-fill mountains on
    that GATE would recreate the mountain-pocket trap without a stacked hero.
    """
    town_id = campaign_granted_start.get("anchorTownSourceIndex")
    if not isinstance(town_id, int):
        raise ValueError(
            "campaign-granted start missing anchorTownSourceIndex; cannot clear town GATE"
        )
    town_group, town_index = _object_instance_fields(objects, town_id)
    town_sid = str(town_group.get("sid") or "")
    town_config = native_object_configs.get(town_sid)
    if not isinstance(town_config, dict):
        raise ValueError(f"campaign-granted town {town_id} sid {town_sid!r} has no ObjectConfig")
    town_anchor = int((town_group.get("nodes") or [])[town_index])
    town_rotation = int((town_group.get("rotations") or [0])[town_index] or 0)
    previous_w, previous_h = emit.OLDEN_WIDTH, emit.OLDEN_HEIGHT
    emit.OLDEN_WIDTH = width
    emit.OLDEN_HEIGHT = height
    try:
        town_gates = emit.gate_nodes_for_object_instance(
            town_sid, town_config, town_anchor, town_rotation
        )
        if len(town_gates) != 1:
            # Envelope clipping can drop the GATE when a city sits on the source
            # rim; access clearing still needs the true ObjectConfig GATE cell.
            import native_footprint_model as native_fp

            model = native_fp.model_native_footprint(
                town_sid,
                town_config,
                town_anchor,
                town_rotation,
                width=width,
                height=height,
            )
            town_gates = {int(node) for node in model.gate_cells}
        if len(town_gates) != 1:
            raise ValueError(
                f"campaign-granted town {town_id} ({town_sid}) needs exactly one GATE; "
                f"got {sorted(town_gates)}"
            )
        town_gate = next(iter(town_gates))
        clearable = set(getattr(emit, "SUPPRESSIBLE_SOURCE_SCENERY_SIDS", ()) or ())
        clearable.add(getattr(emit, "HOMM3_PATHING_GAP_FILL_VISIBLE_SID", "mountain_dirt_small_1"))
        clearable.add(getattr(emit, "HOMM3_PATHING_BLOCKER_SID", "homm3_pathing_blocker"))
        remove_ids: set[int] = set()
        for group in objects:
            sid = str(group.get("sid") or "")
            if sid in ("hero-spawner", "random-hero"):
                continue
            if not (
                sid in clearable
                or sid.startswith("homm3_xfp_s_")
                or sid.startswith("mountain_")
                or sid.startswith("tree_")
                or sid.startswith("pinetree")
            ):
                continue
            config = native_object_configs.get(sid)
            if not isinstance(config, dict):
                continue
            ids = group.get("ids") or []
            nodes = group.get("nodes") or []
            rotations = group.get("rotations") or [0] * len(ids)
            for oid, node, rotation in zip(ids, nodes, rotations):
                if int(oid) == town_id:
                    continue
                occ = emit.occupied_nodes_for_object_instance(
                    sid, config, int(node), int(rotation or 0)
                )
                if town_gate in occ:
                    remove_ids.add(int(oid))
        removed = 0
        if remove_ids:
            for group in objects:
                ids = group.get("ids") or []
                if not isinstance(ids, list) or not ids:
                    continue
                keep = [i for i, oid in enumerate(ids) if oid not in remove_ids]
                if len(keep) == len(ids):
                    continue
                removed += len(ids) - len(keep)
                for key in ("ids", "nodes", "rotations", "levels"):
                    values = group.get(key)
                    if isinstance(values, list):
                        group[key] = [values[i] for i in keep if i < len(values)]
            objects[:] = [group for group in objects if group.get("ids")]
        return {
            "status": "applied",
            "policy": "campaign_granted_clear_town_gate_blockers",
            "townObjectId": town_id,
            "townSid": town_sid,
            "townGateNode": town_gate,
            "clearedBlockerCount": removed,
            "clearedBlockerIds": sorted(remove_ids),
            "ownershipGrant": campaign_granted_start.get("ownershipGrant"),
            "cityStart": campaign_granted_start.get("cityStart"),
        }
    finally:
        emit.OLDEN_WIDTH = previous_w
        emit.OLDEN_HEIGHT = previous_h


def assert_no_forbidden_imports() -> None:
    imported = set(sys.modules)
    bad = [name for name in FORBIDDEN_IMPORT_NAMES if name in imported]
    if bad:
        raise RuntimeError(
            "raw_translation forbid importing OUT modules: " + ", ".join(sorted(bad))
        )


def build_native_shaped_areas_shell(
    objects: list[dict[str, Any]],
    tiles_map: list[int],
    *,
    width: int,
    height: int,
    player_spawn_node: int | None,
) -> tuple[list[dict[str, Any]], list[int], int]:
    """Emit Glittering-Strait / Thirst-shaped areas + keyObjects (not the stripped shell).

    Working native maps use ``haveCustomAreas=true``, non-1 ``areasVersion``, and area rows
    with ``biome`` / ``keyObjectId`` / ``rootNode`` / ``neighbors``. Gold object rows already
    match those maps; the stripped ``{id,nodes}`` + ``areasVersion=1`` shell does not.
    """
    cell_count = width * height
    if len(tiles_map) != cell_count:
        raise ValueError(
            f"tilesMap length {len(tiles_map)} != atlas cells {cell_count} ({width}x{height})"
        )
    biome_counts: Counter[str] = Counter()
    # Atlas is side-by-side; score biome from the surface half only so Void/Burrow
    # underground padding cannot dominate the single-area shell label.
    surface_width = width // 2 if width >= 2 else width
    for index, tile_id in enumerate(tiles_map):
        if index % width >= surface_width:
            continue
        biome_counts[_TILE_BIOME_BY_ID.get(int(tile_id), "Grass")] += 1
    if not biome_counts:
        raise ValueError("cannot derive area biome: no surface tiles counted")
    biome = max(biome_counts.items(), key=lambda item: (item[1], item[0]))[0]

    town_entries: list[tuple[int, int]] = []
    for group in objects:
        sid = str(group.get("sid") or "")
        if sid not in _TOWN_SIDS:
            continue
        for object_id, node in zip(group.get("ids") or [], group.get("nodes") or []):
            if isinstance(object_id, int) and isinstance(node, int):
                town_entries.append((object_id, node))
    town_entries.sort(key=lambda item: (item[1], item[0]))
    key_objects = [object_id for object_id, _ in town_entries]
    if key_objects:
        key_object_id = key_objects[0]
        root_node = town_entries[0][1]
    elif isinstance(player_spawn_node, int):
        key_object_id = -1
        root_node = player_spawn_node
    else:
        key_object_id = -1
        root_node = 0

    areas = [{
        "id": 0,
        "keyObjectId": key_object_id,
        "rootNode": root_node,
        "nodes": list(range(cell_count)),
        "neighbors": [],
        "biome": biome,
    }]
    return areas, key_objects, NATIVE_CUSTOM_AREAS_VERSION


def prepare_core_overlay(profile: ScenarioProfile) -> Path:
    """Create an empty core_overlay root for raw emit.

    ``emit_fresh`` is the only supported mode: squads, dialogs, land-on objects,
    portals, Lang rows and the pathability alignment overlay are all regenerated
    below. The retired ``inherit_single_layer_artifact`` mode copied the single_layer
    lane's overlay, which made one mission's payload depend on a retired lane's
    artifact; it is rejected fail-closed rather than silently downgraded.
    """
    destination = atlas.OUT_ROOT / "core_overlay"
    if destination.exists():
        shutil.rmtree(destination)
    mode = profile.core_overlay.mode
    if mode != "emit_fresh":
        raise ValueError(
            f"unsupported raw_translation coreOverlay.mode {mode!r}; expected emit_fresh "
            "(inherit_single_layer_artifact is retired with the single_layer lane)"
        )
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def merge_homm3_artifact_overlay_into_mission_core(destination: Path) -> dict[str, Any]:
    """Copy generated HoMM3 artifact Core members into the mission overlay.

    Continuity install merges mission overlays into Core.zip. Catalog seeds that are
    ahead of the installed Core (AB 127–128) must ride with the mission overlay or
    map_sid_missing_objectconfig fails preflight.
    """
    source = (
        poc.ROOT
        / "custom_factions"
        / "artifacts"
        / "generated_core_overlay"
    )
    if not source.is_dir():
        raise ValueError(
            f"missing generated artifact overlay {source}; "
            "run tools/homm3_import/homm3_artifact_core_overlay.py"
        )
    copied = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(source)
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    return {
        "status": "merged",
        "source": str(source.relative_to(poc.ROOT)).replace("\\", "/"),
        "copiedFileCount": copied,
        "policy": "mission_core_overlay_carries_generated_homm3_artifact_catalog",
    }


def apply_profile_globals(profile: ScenarioProfile) -> None:
    atlas.SCHEMA = SCHEMA
    atlas.STATUS = "generated_runtime_unvalidated"
    atlas.MAP_SID = profile.map_sid
    atlas.TITLE = profile.title
    atlas.DESCRIPTION = profile.description
    atlas.OUT_ROOT = profile.output_root
    atlas.ALIGNMENT_PATH = profile.alignment_path
    atlas.SUBSTITUTION_PATH = profile.substitution_path
    atlas.CORE_CATALOG_PATH = profile.core_catalog_path
    atlas.SOURCE_WIDTH = profile.source_width
    atlas.SOURCE_HEIGHT = profile.source_height
    atlas.LAYER_LAYOUT = __import__(
        "h3m_scenario_translation", fromlist=["build_side_by_side_layer_atlas"]
    ).build_side_by_side_layer_atlas(
        source_width=atlas.SOURCE_WIDTH,
        source_height=atlas.SOURCE_HEIGHT,
        layer_ids=list(profile.layer_ids),
        view_names={
            layer: ("surface" if layer == 0 else "underground" if layer == 1 else f"layer_{layer}")
            for layer in profile.layer_ids
        },
        underground_layers=set(profile.underground_layers),
    )
    atlas.OLDEN_WIDTH = atlas.LAYER_LAYOUT.atlas_width
    atlas.OLDEN_HEIGHT = atlas.LAYER_LAYOUT.atlas_height
    atlas.LAYER_SPECS = atlas.LAYER_LAYOUT.layers
    lob.OLDEN_WIDTH = atlas.OLDEN_WIDTH
    lob.OLDEN_HEIGHT = atlas.OLDEN_HEIGHT
    lob.SOURCE_WIDTH = atlas.SOURCE_WIDTH
    lob.SOURCE_HEIGHT = atlas.SOURCE_HEIGHT
    lob.LAYER_SPECS = atlas.LAYER_SPECS
    lob.MAP_SID = atlas.MAP_SID
    lob.OUT_ROOT = atlas.OUT_ROOT
    lob.ALIGNMENT_PATH = atlas.ALIGNMENT_PATH
    lob.set_active_profile(profile)
    single.SUBSTITUTION_PATH = profile.substitution_path
    # surface_emit keeps its own SOURCE_* / OLDEN_* module globals used by ocean
    # shoreline projection and spawn helpers — keep them in lockstep with the profile.
    single.SOURCE_WIDTH = atlas.SOURCE_WIDTH
    single.SOURCE_HEIGHT = atlas.SOURCE_HEIGHT
    single.OLDEN_WIDTH = atlas.OLDEN_WIDTH
    single.OLDEN_HEIGHT = atlas.OLDEN_HEIGHT
    single.SOURCE_OFFSET_X = (atlas.OLDEN_WIDTH - atlas.SOURCE_WIDTH) // 2
    single.SOURCE_OFFSET_Y = (atlas.OLDEN_HEIGHT - atlas.SOURCE_HEIGHT) // 2
    # Native-cell clipping outside a layer projection context needs every layer's envelope.
    layer_width = atlas.LAYER_LAYOUT.layer_width
    single.SOURCE_LAYER_ENVELOPES = tuple(
        (
            int(spec["layerOriginX"]),
            int(spec["layerOriginX"]) + layer_width,
            int(spec["offsetX"]),
            int(spec["offsetY"]),
            int(spec["offsetX"]) + atlas.SOURCE_WIDTH,
            int(spec["offsetY"]) + atlas.SOURCE_HEIGHT,
        )
        for spec in atlas.LAYER_SPECS.values()
    )


def _homm3_scenery_footprint_pin(
    objects: list[dict[str, Any]],
    *,
    exact_registry: Any | None = None,
) -> dict[str, Any]:
    import build_homecoming_entity_substitution_map as sub_mod

    if exact_registry is not None:
        return {
            "policy": (
                "exact_homm3_traversal_shape_class_gate_on_visit_plus_visible_gap_fill_"
                "scenery_1x1_mountain_tree_rock_or_catalog_or_full_grid_clone_or_solid_square"
            ),
            "status": "applied",
            "sceneryCatalogMatchCount": int((exact_registry.stats or {}).get("sceneryCatalogMatch") or 0),
            "sceneryNoCatalogSolidSquareCount": int(
                (exact_registry.stats or {}).get("sceneryNoCatalogSolidSquare") or 0
            ),
            "sceneryCloneCount": int((exact_registry.stats or {}).get("sceneryClone") or 0),
            "functionalKeepDonorCount": int((exact_registry.stats or {}).get("functionalKeepDonor") or 0),
            "functionalSameSizeCloneCount": int(
                (exact_registry.stats or {}).get("functionalSameSizeClone") or 0
            ),
            "stats": exact_registry.stats,
        }

    side_counts: Counter[int] = Counter()
    sid_counts: Counter[str] = Counter()
    for group in objects:
        sid = str(group.get("sid") or "")
        side = sub_mod.scenery_sid_solid_side(sid)
        if side is None:
            continue
        for object_id in group.get("ids") or []:
            if not isinstance(object_id, int):
                continue
            side_counts[side] += 1
            sid_counts[sid] += 1
    return {
        "policy": sub_mod.HOMM3_SCENERY_FOOTPRINT_POLICY,
        "status": "applied",
        "nativeSolid1x1Count": int(side_counts.get(1, 0)),
        "nativeSolid2x2Count": int(side_counts.get(2, 0)),
        "nativeSolid3x3Count": int(side_counts.get(3, 0)),
        "nativeSidHistogram": dict(sid_counts.most_common()),
    }


def _intentional_occupied_overlap_diagnostic(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Count Olden occupied (nodes==1) cells with more than one object — diagnostic only."""
    cell_owners: dict[int, list[dict[str, Any]]] = defaultdict(list)
    previous_w, previous_h = single.OLDEN_WIDTH, single.OLDEN_HEIGHT
    single.OLDEN_WIDTH = atlas.OLDEN_WIDTH
    single.OLDEN_HEIGHT = atlas.OLDEN_HEIGHT
    try:
        for group in objects:
            sid = str(group.get("sid") or "")
            config = native_object_configs.get(sid)
            if not isinstance(config, dict):
                continue
            for object_id, node, rotation in zip(
                group.get("ids") or [],
                group.get("nodes") or [],
                group.get("rotations") or [],
            ):
                if not isinstance(object_id, int) or not isinstance(node, int):
                    continue
                occupied = single.occupied_nodes_for_object_instance(
                    sid, config, node, int(rotation or 0)
                )
                for cell in occupied:
                    cell_owners[cell].append({"id": object_id, "sid": sid, "node": node})
    finally:
        single.OLDEN_WIDTH = previous_w
        single.OLDEN_HEIGHT = previous_h

    overlapped = {cell: owners for cell, owners in cell_owners.items() if len(owners) > 1}
    examples = []
    for cell, owners in sorted(overlapped.items())[:20]:
        examples.append({"cell": cell, "owners": owners})
    return {
        "status": "intentional_diagnostic",
        "policy": "raw_translation_fer_on_overlap_diagnostic",
        "overlappedCellCount": len(overlapped),
        "overlappedOwnerPairApprox": sum(len(owners) for owners in overlapped.values()),
        "examples": examples,
    }


def _assert_owned_output_dir(out_maps: Path, map_sid: str) -> None:
    # The visual postpass owns its full-map rollback copy. Keep that exact
    # generated suffix allowlisted without weakening the foreign-artifact gate.
    expected = {
        f"{map_sid}.map",
        f"{map_sid}.json",
        f"{map_sid}{visual_scenery_canon_postpass.BACKUP_SUFFIX}",
    }
    foreign = sorted(
        stale.name
        for stale in out_maps.iterdir()
        if stale.is_file()
        and stale.name not in expected
        and stale.suffix.lower() in {".map", ".json"}
    )
    if foreign:
        raise ValueError(
            f"raw_translation output directory {out_maps} contains unowned map artifacts: "
            f"{foreign}; refusing to delete them"
        )


def _atlas_layer_for_node(node: int) -> int | None:
    if not isinstance(node, int) or node < 0 or node >= atlas.OLDEN_WIDTH * atlas.OLDEN_HEIGHT:
        return None
    x = node % atlas.OLDEN_WIDTH
    y = node // atlas.OLDEN_WIDTH
    for layer, spec in atlas.LAYER_SPECS.items():
        offset_x = spec.get("offsetX")
        offset_y = spec.get("offsetY")
        if (
            isinstance(offset_x, int)
            and isinstance(offset_y, int)
            and offset_x <= x < offset_x + atlas.SOURCE_WIDTH
            and offset_y <= y < offset_y + atlas.SOURCE_HEIGHT
        ):
            return int(layer)
    return None


def generate_map(
    profile: ScenarioProfile,
    *,
    skip_visual_scenery_postpass: bool = False,
    enable_homm3_footprint_compatibility: bool = False,
    enable_homm3_bank_remapping: bool = False,
) -> dict[str, Any]:
    import time

    # Each map starts from the base city-name tables (see reset_registered_city_names).
    homecoming_lang.reset_registered_city_names()
    phase_timings: dict[str, float] = {}

    def _phase(name: str, started: float) -> None:
        phase_timings[name] = round(time.perf_counter() - started, 3)

    t_all = time.perf_counter()
    assert_no_forbidden_imports()
    apply_profile_globals(profile)
    single.require_current_substitution_map()
    mission_id = lob.mission_id_from_profile(profile)

    t0 = time.perf_counter()
    alignment = atlas.read_json(atlas.ALIGNMENT_PATH)
    substitution = atlas.read_json(atlas.SUBSTITUTION_PATH)
    core_catalog = atlas.read_json(atlas.CORE_CATALOG_PATH)
    global_entities = alignment["alignment"]["globalObjectProperties"]["propEntities"]
    valid_ids = {
        row["id"]
        for row in core_catalog.get("mapObjects", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    valid_ids.add(single.HOMM3_BOAT_SID)
    valid_ids.add("homm3_seer_hut")
    valid_ids.add(single.HOMM3_SUBTERRANEAN_GATE_PORTAL_SID)
    valid_ids.add(single.HOMM3_FLOTSAM_PICKUP_SID)
    valid_ids.add(single.HOMM3_PATHING_BLOCKER_SID)
    valid_ids.update(single.HOMM3_LANDON_OBJECT_SIDS)
    single.extend_valid_ids_with_core_homm3_artifacts(valid_ids)

    substitution_lookup = single.build_substitution_lookup(substitution)
    substitution_lookup, travel_link_visual_contract = atlas.build_layered_travel_link_substitution_lookup(
        substitution_lookup, valid_ids
    )
    _phase("load_inputs_and_substitution", t0)

    t0 = time.perf_counter()
    native_object_configs = single.load_native_object_configs(valid_ids)
    _phase("load_native_object_configs", t0)

    t0 = time.perf_counter()
    single.clear_exact_homm3_footprints()
    exact_registry = None
    if EMIT_POLICY.exact_homm3_footprints:
        exact_registry = single.prepare_exact_homm3_footprints(
            global_entities,
            substitution_lookup=substitution_lookup,
            valid_ids=valid_ids,
            native_object_configs=native_object_configs,
        )
    _phase("exact_homm3_footprints", t0)

    layer_histogram = Counter(entity.get("sourceLayer") for entity in global_entities)
    expected = profile.validation.expected_source_layer_entity_counts
    if expected is not None and dict(layer_histogram) != dict(expected):
        raise ValueError(f"unexpected source layer histogram: {dict(layer_histogram)}")

    campaign_granted_start: dict[str, Any] | None = None
    global_entities, campaign_granted_start = ensure_campaign_granted_start_hero(
        global_entities, profile, substitution_lookup
    )

    projected, projection_stats = atlas.project_layers(
        alignment["layeredMapData"],
        emit_policy=EMIT_POLICY,
        preserve_underground_ocean=profile.terrain.preserve_underground_ocean,
    )
    surface_map_data = next(entry["mapData"] for entry in alignment["layeredMapData"] if entry.get("layer") == 0)

    start_source: dict[str, Any] | None = None
    with lob.single_projection_context(0):
        display_water_summary = single.summarize_display_water_projection(surface_map_data, projected)
        shoreline_rivers, shoreline_river_summary = single.build_ocean_shoreline_rivers(surface_map_data)
        property_required_sids = single.discover_native_property_required_sids()
        if campaign_granted_start is None:
            start_candidates: list[dict[str, Any]] = []
            start_layer = int(profile.start_hero_contract.source_layer)
            for entity in global_entities:
                if entity.get("sourceLayer") != start_layer or not lob.in_source_bounds(entity):
                    continue
                replacement_sid, _, _ = single.resolve_replacement_sid(entity, substitution_lookup, valid_ids)
                if replacement_sid == "hero-spawner" and lob.is_start_hero_source(entity):
                    start_candidates.append(entity)
            start_source = single.find_single_replacement_source(
                start_candidates,
                substitution_lookup,
                valid_ids,
                "hero-spawner",
                expected_source={
                    "heroType": profile.start_hero_contract.hero_type,
                    "owner": profile.start_hero_contract.owner,
                    "payloadKind": profile.start_hero_contract.payload_kind,
                    "templateAnimation": profile.start_hero_contract.template_animation,
                    "templateObjectId": profile.start_hero_contract.template_object_id,
                },
            )

    t0 = time.perf_counter()
    objects, object_properties, object_stats, pathability_visual_rows = lob.build_layered_objects(
        global_entities,
        substitution_lookup,
        valid_ids,
        property_required_sids,
        native_object_configs,
        emit_policy=EMIT_POLICY,
    )
    _phase("build_layered_objects", t0)
    underground_pond_placements: list[dict[str, Any]] = []
    for layer_stat in projection_stats:
        conversion = layer_stat.get("undergroundWaterToPondScenery")
        if isinstance(conversion, dict):
            underground_pond_placements.extend(
                placement
                for placement in (conversion.get("placements") or [])
                if isinstance(placement, dict)
            )
    if underground_pond_placements:
        object_stats["undergroundPondScenery"] = single.add_underground_pond_scenery_objects(
            objects,
            underground_pond_placements,
            valid_ids,
        )
    event_specs = campaign_script.map_event_specs_by_source_key(
        alignment["container"]["chunks"][3]
    )
    native_event_markers: list[dict[str, Any]] = []
    map_event_host_ledger: dict[int, dict[str, Any]] = {}
    placed_hero_payload_plan = hero_payloads.PlacedHeroPayloadPlan(mission_id=mission_id)

    with lob.single_projection_context(0):
        # Raw: do NOT adjust boats or add environment decorations.
        human_olden_owner = h3m_hero_sid.h3_owner_to_olden_player_index(
            int(profile.start_hero_contract.owner)
        )
        if campaign_granted_start is not None:
            town_id = int(campaign_granted_start["anchorTownSourceIndex"])
            city_start = apply_campaign_granted_city_start_contract(
                objects,
                object_properties,
                town_object_id=town_id,
                human_h3_owner=int(profile.start_hero_contract.owner),
                human_hero_sid=profile.spawn_hero_sid,
            )
            campaign_granted_start["cityStart"] = city_start
            start_object_id = town_id
            hero_spawner_id = None
        else:
            if start_source is None:
                raise ValueError("map-embedded start requires a resolved hero-spawner start_source")
            hero_spawner_id = single.apply_native_start_contract(
                objects,
                object_properties,
                start_object_id=int(start_source["sourceIndex"]),
                human_h3_owner=int(profile.start_hero_contract.owner),
                human_hero_sid=profile.spawn_hero_sid,
            )
            start_object_id = hero_spawner_id
        entities_by_id = {
            int(entity["sourceIndex"]): entity
            for entity in global_entities
            if isinstance(entity.get("sourceIndex"), int)
        }
        hero_names_by_type: dict[int, str] = {}
        try:
            from campaign_profile_derive import collect_campaign_chain_hero_names_by_type

            hero_names_by_type = collect_campaign_chain_hero_names_by_type(
                _mission_for_profile(profile)
            )
        except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError):
            # Non-campaign / missing batch: fall back to type-id resolution only.
            hero_names_by_type = {}
        placed_heroes = single.append_placed_hero_properties(
            objects,
            object_properties,
            entities_by_id,
            start_hero_object_id=start_object_id,
            hero_names_by_type=hero_names_by_type,
        )
        object_stats["placedNonStartHeroes"] = placed_heroes
        # StoryHub paints every bound city as Bot fractionSid. Mixed-faction H3 AI
        # players (Homecoming Terraneus; Steadwick Castle+Dungeon+Inferno; Neutral
        # Fortress/Stronghold+Castle captures) must become distinct Olden Bot owners.
        if profile.scenario_id == "homecoming_roe_castle":
            # Terraneus + Xyron → Olden owner 4. Bot fractionSid follows Terraneus
            # (Dungeon city); Xyron remains Inferno in propHeroes and is filled at
            # campaign start by Homm3CampaignSpawnParityHook.
            ai_split_remaps = dict(single.HOMECOMING_AI_OWNER_FACTION_SPLIT_REMAPS)
            split_policy = "homecoming_explicit_terraneus_xyron_remap"
        else:
            protect_cities = (
                {int(start_object_id)} if campaign_granted_start is not None else None
            )
            ai_split_remaps = single.plan_ai_multi_faction_city_owner_split(
                object_properties,
                human_olden_owner=human_olden_owner,
                protect_city_ids=protect_cities,
            )
            split_policy = (
                "auto_majority_keep_minority_city_owner_split_protect_campaign_granted"
                if protect_cities
                else "auto_majority_keep_minority_city_owner_split"
            )
        split_report = single.apply_explicit_ai_owner_faction_split(
            object_properties,
            remaps=ai_split_remaps,
        )
        split_report["splitPolicy"] = split_policy
        object_stats["aiOwnerFactionSplit"] = split_report
        object_stats["orphanAiNeutralTownBind"] = single.bind_orphan_ai_owners_to_neutral_towns(
            object_properties,
            entities_by_id,
            human_olden_owner=human_olden_owner,
        )
        # Final owner-mutating step: collapse H3-color-derived owners to the native
        # compact scheme (human=1, AI=2..N). Runs after faction split / orphan binds
        # so meta.spawns and install_manifest are built from the final numbering.
        owner_renumber = single.renumber_map_owners_to_native_compact(
            object_properties,
            human_olden_owner=human_olden_owner,
        )
        object_stats["ownerRenumber"] = owner_renumber
        human_olden_owner = int(owner_renumber["humanOldenOwner"])
        # Map-embedded hero starts that also own towns must promote to City+spawnHero.
        # Leaving the town on propOwners alone makes campaign ObjCity.ownerSide use the
        # spawn-id (human=1) as a sides.array index — solo Length=1 → invalid; multi
        # assigns the wrong Bot side. Campaign-granted starts already use City primary.
        if campaign_granted_start is None:
            city_promotion = single.promote_human_hero_start_to_owned_city_spawn(
                objects,
                object_properties,
                hero_object_id=int(start_object_id),
                human_olden_owner=human_olden_owner,
                human_hero_sid=profile.spawn_hero_sid,
                human_faction_sid=profile.spawn_faction_sid,
            )
            object_stats["humanCityStartPromotion"] = city_promotion
            if city_promotion is not None:
                start_object_id = int(city_promotion["townObjectId"])
                campaign_granted_start = {
                    "anchorTownSourceIndex": start_object_id,
                    "policy": "promoted_map_hero_start_to_owned_city_spawn",
                    "cityStart": city_promotion,
                    "promotedFromHeroObjectId": city_promotion["retiredHeroObjectId"],
                }
        if campaign_granted_start is not None:
            player_spawns = single.build_scenario_player_spawns_from_prop_bindings(
                object_properties,
                human_olden_owner=human_olden_owner,
                human_faction_sid=profile.spawn_faction_sid,
                human_hero_sid=profile.spawn_hero_sid,
                human_start_city_object_id=start_object_id,
            )
        else:
            player_spawns = single.build_scenario_player_spawns_from_prop_bindings(
                object_properties,
                human_olden_owner=human_olden_owner,
                human_faction_sid=profile.spawn_faction_sid,
                human_hero_sid=profile.spawn_hero_sid,
                human_start_hero_object_id=start_object_id,
            )
        editor_spawn_contract = single.apply_editor_compatible_spawn_contract(
            objects,
            object_properties,
            player_spawns,
        )
        object_stats["editorCompatibleSpawnContract"] = editor_spawn_contract
        # Fail closed: every defined propHeroes SID must be reserved in takenHeroes
        # (native c_M* orphan random-hero parity; Tyranell-class extras).
        defined_sids = {
            str(row.get("heroSid"))
            for row in (object_properties.get("propHeroes") or [])
            if isinstance(row, dict)
            and row.get("isDefined") is True
            and isinstance(row.get("heroSid"), str)
            and row.get("heroSid")
            and row.get("heroSid") != "random"
        }
        taken_sids = {
            str(sid)
            for sid in (player_spawns.get("takenHeroes") or [])
            if isinstance(sid, str) and sid
        }
        missing_taken = sorted(defined_sids - taken_sids)
        if missing_taken:
            raise ValueError(
                f"{mission_id}: defined propHeroes missing from takenHeroes: {missing_taken}"
            )
        placed_hero_payload_plan = hero_payloads.plan_placed_hero_payload_grants(
            mission_id=mission_id,
            placed_heroes=placed_heroes,
            entities_by_id=entities_by_id,
            creature_to_unit=lambda creature_id: single.H3_CREATURE_TYPE_TO_UNIT_SID.get(
                int(creature_id)
            ),
        )
        object_stats["placedHeroPayloadGrants"] = {
            "heroCount": len(placed_hero_payload_plan.heroes),
            "grantCount": len(placed_hero_payload_plan.actions),
            "defeatLootCount": len(placed_hero_payload_plan.defeat_loot),
            "rescueGrantHostCount": len(placed_hero_payload_plan.rescue_grants),
            "heroes": list(placed_hero_payload_plan.heroes),
            "evidence": list(placed_hero_payload_plan.evidence),
            "proofBoundary": (
                "generated_artifact; AI placed heroes: equipped artifacts → Clone "
                "HeroKill GiveItemHero onto human start hero (AI GiveItemHero "
                "live-negative); army/skills still day1 AI GiveUnitHero/AddSkillHero; "
                "prisons bind propHeroes; ObjectInteractionAfter arms a next-side-start "
                "rescue grant so artifacts/skills/army target the rescued heroSid; "
                "runtime-unvalidated)"
            ),
        }
        object_stats["herolessAiTownSpawnHero"] = (
            single.enable_town_spawn_hero_for_heroless_ai(
                object_properties,
                player_spawns,
            )
        )
        object_stats["scenarioPlayerSpawns"] = {
            "playersCount": player_spawns["playersCount"],
            "oldenOwners": player_spawns["oldenOwners"],
            "humanOldenOwner": player_spawns["humanOldenOwner"],
            "ownerReports": player_spawns["ownerReports"],
            "policy": player_spawns["policy"],
        }
        landon_access_report = landon_access.apply_raw_landon_access_pass(
            objects,
            object_properties,
            entities_by_id=entities_by_id,
            native_object_configs=native_object_configs,
            path_root_id=start_object_id,
        )
        object_stats["landonAccess"] = landon_access_report
        if event_specs:
            native_event_markers, map_event_host_ledger = apply_native_map_event_hosts(
                global_entities=global_entities,
                objects=objects,
                properties=object_properties,
                event_specs=event_specs,
            )
        # HoMM3 Border Guards/Gates + Keymaster's Tents -> native campaign_FX_block deleted by
        # a key-counter quest; tents become Zone 1x1 markers (ids rebased with map events).
        border_key_gate_plan = border_guard_gates.apply_border_key_gate_hosts(
            mission_id=mission_id,
            global_entities=global_entities,
            objects=objects,
            properties=object_properties,
            markers=native_event_markers,
            native_object_configs=native_object_configs,
            single=single,
            lob=lob,
            land_cell=lambda node: gate_face_rotation._terrain_pathable(
                node,
                tiles_map=projected["tilesMap"],
                water_map=projected["waterMap"],
                levels_map=projected["levelsMap"],
                climbs_map=projected["climbsMap"],
            ),
        )
        object_stats["borderKeyGates"] = border_key_gate_plan
        # landon_access may delete gap-fill scenery from barracks approaches; re-fill only
        # true H3 non-visitable block cells that became open again (never invent open-cell seals).
        surface_entities = [
            entity
            for entity in global_entities
            if isinstance(entity, dict) and int(entity.get("sourceLayer") or 0) == 0
        ]
        object_stats["pathabilityGapFillAfterLandonAccess"] = (
            single.append_homm3_pathability_gap_fill_blockers(
                objects,
                surface_entities,
                native_object_configs,
                id_base=single.HOMM3_PATHING_BLOCKER_ID_BASE + 50_000,
            )
        )
        # Gate-face rotation runs later — after envelope pads — so approach freeness
        # matches final occupancy (early pass could mark OK then late gap-fill/pads re-seal).

    if campaign_granted_start is None:
        if start_source is None or hero_spawner_id is None:
            raise ValueError("map-embedded start missing start_source / hero_spawner_id")
        if start_source["sourceIndex"] != hero_spawner_id:
            raise ValueError(
                f"hero-spawner id {hero_spawner_id} does not match start source index {start_source['sourceIndex']}"
            )

    # No OUT post-passes beyond raw landon access. Envelope padding uses cliffs (no blockers).
    cleared_ids: set[int] = set()
    landon_report = object_stats.get("landonAccess") or {}
    for example in (landon_report.get("barracksSouthApproachClear") or {}).get("examples") or []:
        cleared_ids.update(int(x) for x in (example.get("clearedObjectIds") or []) if isinstance(x, int))
    for example in (landon_report.get("subterraneanPortalGateClear") or {}).get("examples") or []:
        cleared_id = example.get("clearedObjectId")
        if isinstance(cleared_id, int):
            cleared_ids.add(cleared_id)
    marker = landon_report.get("guardhouseMarker") or {}
    cleared_ids.update(int(x) for x in (marker.get("clearedObjectIds") or []) if isinstance(x, int))
    fer_report = object_stats.get("functionalEmitReservation") or {}
    fer_omitted_ids = {
        int(x) for x in (fer_report.get("sceneryOmittedSourceIds") or []) if isinstance(x, int)
    }
    # Layered emit may nest fer stats under layerStats; also collect any nested lists.
    for layer_stat in (object_stats.get("layerStats") or {}).values():
        if not isinstance(layer_stat, dict):
            continue
        nested = layer_stat.get("functionalEmitReservation") or {}
        fer_omitted_ids.update(
            int(x) for x in (nested.get("sceneryOmittedSourceIds") or []) if isinstance(x, int)
        )
    padding_blockers = atlas.emit_envelope_padding_blockers(objects, native_object_configs)
    # Late pass: after layered emit gap-fill, landon_access, post-landon gap-fill, and
    # envelope pads. Shared by all raw maps via this orchestrator. Fail-closed.
    object_stats["gateFaceRotation"] = gate_face_rotation.apply_single_gate_face_rotations(
        objects,
        native_object_configs,
        tiles_map=projected["tilesMap"],
        water_map=projected["waterMap"],
        levels_map=projected["levelsMap"],
        climbs_map=projected["climbsMap"],
        width=atlas.OLDEN_WIDTH,
        height=atlas.OLDEN_HEIGHT,
        objects_properties=object_properties,
    )
    # HoMM3 mainTown.generateHero has no map hero. Bind City+spawnHero (above) and
    # clear gap-fill on the town GATE so the native entrance cell stays walkable.
    if campaign_granted_start is not None:
        object_stats["campaignGrantedTownGatePlacement"] = (
            clear_campaign_granted_town_gate_blockers(
                objects,
                campaign_granted_start=campaign_granted_start,
                native_object_configs=native_object_configs,
                width=atlas.OLDEN_WIDTH,
                height=atlas.OLDEN_HEIGHT,
                emit=single,
            )
        )
    else:
        object_stats["campaignGrantedTownGatePlacement"] = {
            "status": "skipped",
            "reason": "map_embedded_start_hero",
        }

    # Raw translation previously omitted approach_cell's spawn unbury. Griffin Cliff's
    # AI hero-spawners can sit under mountain/town footprints. Campaign-granted human
    # starts use City+spawnHero (no hero-spawner to unbury).
    import spawn_footprint_unbury

    spawn_ids_to_unbury: list[int] = []
    if hero_spawner_id is not None:
        spawn_ids_to_unbury.append(int(hero_spawner_id))
    for report in (player_spawns.get("ownerReports") or {}).values():
        if not isinstance(report, dict):
            continue
        primary = report.get("primaryHeroObjectId")
        if isinstance(primary, int) and primary not in spawn_ids_to_unbury:
            spawn_ids_to_unbury.append(primary)
    unbury_reports: list[dict[str, Any]] = []
    previous_w, previous_h = single.OLDEN_WIDTH, single.OLDEN_HEIGHT
    single.OLDEN_WIDTH = atlas.OLDEN_WIDTH
    single.OLDEN_HEIGHT = atlas.OLDEN_HEIGHT
    envelope_forbidden = set(atlas.envelope_padding_nodes())
    try:
        for spawn_object_id in spawn_ids_to_unbury:
            spawn_node = None
            for group in objects:
                if group.get("sid") != "hero-spawner":
                    continue
                for oid, node in zip(group.get("ids") or [], group.get("nodes") or []):
                    if oid == spawn_object_id and isinstance(node, int):
                        spawn_node = node
                        break
                if spawn_node is not None:
                    break
            if spawn_node is None:
                # Primary may be a city (heroless AI); nothing to unbury.
                continue
            runtime = spawn_footprint_unbury.SpawnUnburyContext(
                width=atlas.OLDEN_WIDTH,
                height=atlas.OLDEN_HEIGHT,
                native_object_configs=native_object_configs,
                spawn_node=int(spawn_node),
                spawn_object_id=int(spawn_object_id),
            )
            report = spawn_footprint_unbury.unbury_spawn_from_foreign_footprints(
                objects,
                runtime,
                emit=single,
                forbidden_nodes=envelope_forbidden,
                levels_map=list(projected["levelsMap"]),
                climbs_map=list(projected["climbsMap"]),
            )
            if report is not None:
                unbury_reports.append(report)
        # Fail-closed: no hero-spawner GATE/body may remain on elevated envelope cliffs.
        spawn_footprint_unbury.assert_hero_spawners_outside_forbidden(
            objects,
            native_object_configs,
            emit=single,
            forbidden_nodes=envelope_forbidden,
            width=atlas.OLDEN_WIDTH,
            levels_map=list(projected["levelsMap"]),
            climbs_map=list(projected["climbsMap"]),
        )
    finally:
        single.OLDEN_WIDTH = previous_w
        single.OLDEN_HEIGHT = previous_h
    object_stats["spawnFootprintUnbury"] = {
        "status": "applied" if unbury_reports else "noop",
        "policy": (
            "spawn_footprint_unbury_gate_visit_only_reject_envelope_padding_elevated"
        ),
        "spawnObjectIds": spawn_ids_to_unbury,
        "forbiddenEnvelopePaddingCellCount": len(envelope_forbidden),
        "buryPolicy": "gate_visit_cell_only",
        "reports": unbury_reports,
    }
    gate_face = object_stats.get("gateFaceRotation") or {}
    for row in gate_face.get("rotated") or []:
        if not isinstance(row, dict):
            continue
        for cleared in (row.get("clearedApproachBlockers") or []):
            if isinstance(cleared, dict) and isinstance(cleared.get("objectId"), int):
                cleared_ids.add(int(cleared["objectId"]))
        for cleared in (row.get("nonkeeperCleared") or []):
            if isinstance(cleared, dict) and isinstance(cleared.get("objectId"), int):
                cleared_ids.add(int(cleared["objectId"]))

    # Bank remapping must run before footprint repair: a wrong bank SID changes
    # the native footprint the repair pass would try to fix.
    if enable_homm3_bank_remapping:
        object_stats["homm3BankRemapping"] = homm3_bank_remapping.apply_homm3_bank_remapping(
            global_entities=global_entities,
            objects=objects,
            native_object_configs=native_object_configs,
            layer_target_node=atlas.layer_target_node,
            width=atlas.OLDEN_WIDTH,
            height=atlas.OLDEN_HEIGHT,
            map_sid=atlas.MAP_SID,
            core_zip_path=str(poc.OLDEN_CORE_ZIP),
        )
    else:
        object_stats["homm3BankRemapping"] = {
            "schema": homm3_bank_remapping.SCHEMA,
            "status": homm3_bank_remapping.STATUS_DISABLED,
            "policy": "candidate_only_explicit_opt_in",
        }

    if enable_homm3_footprint_compatibility:
        object_stats["homm3FootprintCompatibility"] = homm3_footprint_compatibility.apply_homm3_footprint_compatibility(
            global_entities=global_entities,
            objects=objects,
            object_properties=object_properties,
            native_object_configs=native_object_configs,
            layer_target_node=atlas.layer_target_node,
            layer_resolver=_atlas_layer_for_node,
            width=atlas.OLDEN_WIDTH,
            height=atlas.OLDEN_HEIGHT,
            map_sid=atlas.MAP_SID,
        )
    else:
        object_stats["homm3FootprintCompatibility"] = {
            "schema": homm3_footprint_compatibility.SCHEMA,
            "status": homm3_footprint_compatibility.STATUS_DISABLED,
            "policy": "candidate_only_explicit_opt_in",
        }

    # Separate visual postpass (canon terrain + scenery variety). Dangerous; skip via
    # env RAW_TRANSLATION_SKIP_VISUAL_SCENERY_POSTPASS=1 or --skip-visual-scenery-postpass.
    # Runs before placement GT + areas so both see the remapped tiles / final scenery.
    visual_pre_snapshot = visual_scenery_canon_postpass.snapshot_pre_postpass_state(
        tiles_map=projected["tilesMap"],
        water_map=projected["waterMap"],
        objects=objects,
    )
    object_stats["visualSceneryCanon"] = (
        visual_scenery_canon_postpass.apply_visual_scenery_canon_postpass(
            tiles_map=projected["tilesMap"],
            water_map=projected["waterMap"],
            objects=objects,
            native_object_configs=native_object_configs,
            layered_map_data=list(alignment["layeredMapData"]),
            layer_target_node=atlas.layer_target_node,
            map_sid=atlas.MAP_SID,
            width=atlas.OLDEN_WIDTH,
            height=atlas.OLDEN_HEIGHT,
            preserve_source_ids=True,
            skip_flag=skip_visual_scenery_postpass,
        )
    )

    # After visual scenery (SID diversify / mountain merge), clear suppressible
    # solids sitting on interactable GATE cells or on HoMM3-open floor. Does not
    # rewrite waterMap, shoreline rivers, ocean basins, or climbs.
    object_stats["entranceOccupancy"] = (
        entrance_occupancy.apply_raw_translation_accessibility_pass(
            objects=objects,
            native_object_configs=native_object_configs,
            object_properties=object_properties,
            global_entities=global_entities,
            layered_map_data=list(alignment["layeredMapData"]),
            layer_target_node=atlas.layer_target_node,
            width=atlas.OLDEN_WIDTH,
            height=atlas.OLDEN_HEIGHT,
            source_width=atlas.SOURCE_WIDTH,
            source_height=atlas.SOURCE_HEIGHT,
            map_sid=atlas.MAP_SID,
        )
    )
    for row in (object_stats["entranceOccupancy"].get("cleared") or []):
        if isinstance(row, dict) and isinstance(row.get("objectId"), int):
            cleared_ids.add(int(row["objectId"]))

    # Visual-only HoMM3 DEF billboards: each covered object gets an inert billboard host on one
    # of its own HoMM3 blocked cells, replacing a gap fill there when one exists
    # (raw_translation/object_billboards.py). Runs after every occupancy pass so no later pass
    # moves or clears a host.
    object_billboard_report = object_billboards.apply_object_billboard_hosts(
        global_entities=global_entities,
        objects=objects,
        native_object_configs=native_object_configs,
        single=single,
        lob=lob,
        marker_nodes={int(m["node"]) for m in native_event_markers if isinstance(m.get("node"), int)},
        width=atlas.OLDEN_WIDTH,
        height=atlas.OLDEN_HEIGHT,
    )
    object_stats["objectBillboards"] = object_billboard_report

    # Visual mountain merging can remove source-associated 1x1 objects. Raw
    # translation keeps source IDs authoritative, so scrub only type-0 rows
    # after the final object mutation while preserving marker namespace rows.
    object_stats["finalObjectPropertyScrub"] = {
        "removedRows": propns.scrub_orphan_object_namespace_properties(
            object_properties,
            live_object_ids=propns.live_object_ids(objects),
        ),
        "policy": "raw_translation_type0_properties_must_reference_final_objects",
    }

    visual_stats = object_stats.get("visualSceneryCanon") or {}
    visual_diversify = visual_stats.get("sceneryDiversify") or {}
    visual_sid_change_ids = {
        int(object_id)
        for object_id in (visual_diversify.get("changedObjectIds") or [])
        if isinstance(object_id, int)
    }
    promoted_start_bindings: dict[int, int] = {}
    if isinstance(campaign_granted_start, dict):
        city_start = campaign_granted_start.get("cityStart")
        if isinstance(city_start, dict):
            retired_id = city_start.get("retiredHeroObjectId")
            town_id = city_start.get("townObjectId")
            if isinstance(retired_id, int) and isinstance(town_id, int):
                promoted_start_bindings[retired_id] = town_id
    ground_truth = placement_ground_truth.build_placement_ground_truth(
        global_entities=global_entities,
        objects=objects,
        substitution_lookup=substitution_lookup,
        valid_ids=valid_ids,
        native_object_configs=native_object_configs,
        profile=profile,
        approach_cleared_ids=cleared_ids,
        fer_omitted_ids=fer_omitted_ids,
        map_event_host_ledger=map_event_host_ledger,
        visual_scenery_sid_change_ids=visual_sid_change_ids,
        promoted_start_bindings=promoted_start_bindings,
        object_billboard_hosts=object_billboards.hosts_by_source_index(object_billboard_report),
    )
    ground_truth_path = placement_ground_truth.write_placement_ground_truth(ground_truth)
    overlap_diagnostic = _intentional_occupied_overlap_diagnostic(objects, native_object_configs)
    scenery_footprint = _homm3_scenery_footprint_pin(objects, exact_registry=exact_registry)

    ug_tunnel_statuses = []
    ug_tunnel_contracts = []
    for layer_stat in projection_stats:
        clearance = layer_stat.get("undergroundTunnelClearance")
        if isinstance(clearance, dict):
            ug_tunnel_statuses.append(clearance.get("status") or "applied")
            ug_tunnel_contracts.append(clearance)
    ug_clearance_applied = bool(ug_tunnel_statuses) and all(
        status not in (None, "disabled") for status in ug_tunnel_statuses
    )
    ug_layer_clearance = next(
        (
            clearance
            for clearance in ug_tunnel_contracts
            if isinstance(clearance, dict) and clearance.get("status") not in (None, "disabled")
        ),
        None,
    )
    ug_scenery_statuses = []
    for layer_stat in (object_stats.get("layerStats") or {}).values():
        if not isinstance(layer_stat, dict):
            continue
        suppress = layer_stat.get("undergroundPayloadlessScenerySuppression")
        if isinstance(suppress, dict):
            ug_scenery_statuses.append(suppress.get("status"))
    assert_no_forbidden_imports()

    mission = _mission_for_profile(profile)
    hero_level_limit = campaign_hero_level_cap.mission_hero_level_limit(mission)
    hero_max_level_settings = campaign_hero_level_cap.olden_custom_hero_max_level_settings(
        hero_level_limit
    )

    with lob.single_output_context():
        meta_shape, start_settings, native_settings = single.load_native_start_shape()
        # HoMM3 campaign maps are multi-hero: scenario text says "Heroes" / "N strongest
        # Heroes" carry over, and guides hire a second from the tavern. Profile does not
        # lock single-hero. heroCountMax=1 was an incorrect Olden port constraint.
        native_settings["heroCountMin"] = 1
        native_settings["heroCountMax"] = 8
        native_settings["heroCountIncrement"] = 1
        # Per-mission H3M levelLimit (0 = unlimited). Do not hardcode Homecoming's 6.
        native_settings["enableCustomHeroMaxLevel"] = hero_max_level_settings[
            "enableCustomHeroMaxLevel"
        ]
        native_settings["customHeroMaxLevel"] = hero_max_level_settings["customHeroMaxLevel"]
        native_settings["mapWinConditions"] = []
        native_settings["idSidesWithoutTimer"] = []
        # Glittering Strait / Thirst use isScenario=true; stripped false shell is non-native.
        native_settings["isScenario"] = True
        # Allow auto-battle vs neutrals/guards; block auto vs enemy heroes.
        native_settings["disableAutoBattleAgainstEnemyHeroes"] = True

    container = poc.read_olden_map_container(profile.template_map_path)
    chunks = copy.deepcopy(container.chunks)
    meta = chunks[0]
    map_data = chunks[1]
    map_hash = hashlib.md5(atlas.MAP_SID.encode("utf-8")).hexdigest()
    meta.update({
        "title": atlas.TITLE,
        "template": "",
        "gameMode": 0,
        "endController": 0,
        "economicDifficulties": meta_shape["economicDifficulties"],
        "aiDifficulties": meta_shape["aiDifficulties"],
        "neutralDifficulties": meta_shape["neutralDifficulties"],
        "quickStartDifficulties": meta_shape["quickStartDifficulties"],
        "campaignInfo": meta_shape["campaignInfo"],
        "desc": atlas.DESCRIPTION,
        "displayWinCondition": "",
        "hashSum": map_hash,
        "nameFromLocalization": True,
        "descFromLocalization": True,
        "spawns": {
            "playersCount": player_spawns["playersCount"],
            "spawns": player_spawns["spawns"],
            "takenHeroes": player_spawns["takenHeroes"],
        },
        "startSettings": start_settings,
        "sizeX": atlas.OLDEN_WIDTH,
        "sizeZ": atlas.OLDEN_HEIGHT,
        "banInfoData": meta_shape["banInfoData"],
        "daysInGame": 0,
        "isAutoSave": False,
        "currentTurnMode": 0,
        "isScenario": True,
    })
    meta["isScenario"] = True
    player_spawn_node = None
    spawn_owners = {
        int(row["id"]): int(row["owner"])
        for row in (object_properties.get("propSpawns") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int) and isinstance(row.get("owner"), int)
    }
    for group in objects:
        if str(group.get("sid") or "") != "hero-spawner":
            continue
        for object_id, node in zip(group.get("ids") or [], group.get("nodes") or []):
            if spawn_owners.get(object_id) == 1 and isinstance(node, int):
                player_spawn_node = node
                break
        if player_spawn_node is not None:
            break
    areas, key_objects, areas_version = build_native_shaped_areas_shell(
        objects,
        projected["tilesMap"],
        width=atlas.OLDEN_WIDTH,
        height=atlas.OLDEN_HEIGHT,
        player_spawn_node=player_spawn_node,
    )
    markers_free_id = rebase_native_event_marker_ids(
        markers=native_event_markers,
        properties=object_properties,
        areas=areas,
    )
    propns.assert_marker_property_integrity(
        markers=native_event_markers,
        properties=object_properties,
        context=atlas.MAP_SID,
    )
    border_key_gate_plan["finalCheck"] = border_guard_gates.verify_border_key_gates_final(
        plan=border_key_gate_plan,
        objects=objects,
        native_object_configs=native_object_configs,
        markers=native_event_markers,
        properties=object_properties,
        single=single,
    )
    map_data.update({
        "fileMapName": atlas.MAP_SID,
        "mapName": atlas.TITLE,
        "mapNameFromLoc": True,
        "mapDesc": atlas.DESCRIPTION,
        "mapDescFromLoc": True,
        "sizeX_": atlas.OLDEN_WIDTH,
        "sizeZ_": atlas.OLDEN_HEIGHT,
        "tilesMap": projected["tilesMap"],
        "levelsMap": projected["levelsMap"],
        "climbsMap": projected["climbsMap"],
        "roadsMap": projected["roadsMap"],
        "waterMap": projected["waterMap"],
        "customAreasPainting": projected["customAreasPainting"],
        "views": [atlas.LAYER_SPECS[layer]["view"] for layer in sorted(atlas.LAYER_SPECS)],
        "settings": native_settings,
        "objects": objects,
        "objectsProperties": object_properties,
        "areas": areas,
        "objectsFreeId": max(
            (value for group in objects for value in group.get("ids", []) if isinstance(value, int)),
            default=-1,
        ) + 1,
        "squads": [],
        "squadsFreeId": 1,
        "markers": native_event_markers,
        "markersFreeId": markers_free_id,
        "rivers": shoreline_rivers,
        "keyObjects": key_objects,
        "objectValuesOverrides": {"list": []},
        "takenHeroes": player_spawns["takenHeroes"],
        "areasVersion": areas_version,
        "haveCustomAreas": True,
        "generatorChecksum": "",
    })
    scenario_menu_shell.apply_menu_shell(meta, map_data, atlas.MAP_SID)
    alignment_entities = list(
        ((alignment.get("alignment") or {}).get("globalObjectProperties") or {}).get("propEntities")
        or []
    )
    campaign_mission = _mission_for_profile(profile)
    header = h3m.decode_h3m_scenario_header(
        load_h3c_block(campaign_mission.campaign_entry, campaign_mission.block_index).h3m_data
    )
    profile_victory = None
    if profile.victory_contract is not None:
        profile_victory = {
            "type": profile.victory_contract.victory_type,
            "allowNormalVictory": profile.victory_contract.allow_normal_victory,
            "sourceKeys": list(profile.victory_contract.source_keys),
            "expectedEmittedSid": profile.victory_contract.expected_emitted_sid,
        }
    victory_plan = campaign_victory.plan_campaign_victory(
        mission_id=mission_id,
        header=header,
        entities=alignment_entities,
        creature_to_unit=lambda creature_id: single.H3_CREATURE_TYPE_TO_UNIT_SID.get(int(creature_id)),
        profile_victory=profile_victory,
    )
    object_stats["victoryPlan"] = campaign_victory.apply_victory_prop_entities(
        object_properties,
        victory_plan,
    )
    meta["startSettings"]["DefeatAllEnemiesEnabled"] = bool(
        victory_plan.defeat_all_enemies_enabled
    )
    # Legacy TAKEDWELLINGS-only adapter kept for validators that still read it.
    ownership_victory = campaign_victory.ownership_victory_from_plan(victory_plan)
    if profile.victory_contract is not None:
        header_name = str((header.get("victory") or {}).get("name") or "")
        if header_name != profile.victory_contract.victory_type:
            raise ValueError(
                f"{mission_id}: profile victoryContract.type "
                f"{profile.victory_contract.victory_type!r} disagrees with H3 header "
                f"{header_name!r}"
            )
    chunks[2] = {"dialogs": {"lines": []}, "quests": {"quests": []}}
    alignment_story = alignment["container"]["chunks"][3]
    import campaign_starting_bonus as starting_bonus

    bonus_spec = starting_bonus.resolve_starting_bonus(
        mission_id,
        hero_sid=profile.spawn_hero_sid,
        mission_title=alignment_story.get("missionTitle") or atlas.TITLE,
    )
    if bonus_spec is not None and bonus_spec.get("requiresStartCityEntity"):
        city_sid = str(bonus_spec.get("startCityEntitySid") or "").strip()
        if not city_sid:
            raise ValueError(
                f"{mission_id}: BUILDING starting bonus missing startCityEntitySid"
            )
        try:
            object_stats["startingBonusStartCityEntity"] = (
                single.bind_human_start_city_entity_sid(
                    object_properties,
                    player_spawns,
                    entity_sid=city_sid,
                )
            )
        except ValueError as exc:
            # Hero-only starts cannot host UnlockBuildingCity; drop building choices.
            kept = [
                option
                for option in bonus_spec["options"]
                if not any(
                    isinstance(grant, dict) and grant.get("kind") == "building"
                    for grant in (option.get("grants") or [])
                )
            ]
            omitted = list(bonus_spec.get("omittedOptions") or [])
            for option in bonus_spec["options"]:
                if option in kept:
                    continue
                omitted.append(
                    {
                        "index": None,
                        "homm3": option.get("homm3"),
                        "omitReason": (
                            f"BUILDING option omitted: no human primary city "
                            f"({exc})"
                        ),
                        "missionId": mission_id,
                    }
                )
            if not kept:
                object_stats["startingBonusOmitted"] = {
                    "reason": (
                        f"all surviving options were BUILDING grants but human has "
                        f"no primary city ({exc})"
                    ),
                    "omittedOptions": omitted,
                }
                bonus_spec = None
            else:
                bonus_spec = dict(bonus_spec)
                bonus_spec["options"] = kept
                bonus_spec["omittedOptions"] = omitted
                bonus_spec["requiresStartCityEntity"] = False
                bonus_spec["startCityEntitySid"] = None
                bonus_spec["evidence"] = (
                    f"{bonus_spec.get('evidence')}; dropped building options "
                    f"(no human primary city)"
                )
    if bonus_spec is not None:
        alignment_story = starting_bonus.attach_to_alignment_story(alignment_story, bonus_spec)
    featured_city_capture_sids = {
        contract.source_key: campaign_script.featured_capture_entity_sid(mission_id, city_name=contract.name)
        for contract in profile.featured_cities
    }
    runtime_dialog_lines = campaign_script.build_runtime_dialog_lines(mission_id, alignment_story)
    chunks[3] = campaign_script.build_runtime_script_chunk(
        mission_id,
        alignment_story,
        dialog_lines=runtime_dialog_lines,
        featured_city_capture_sids=featured_city_capture_sids,
        ownership_victory=ownership_victory,
        victory_plan=victory_plan,
        placed_hero_payload_plan=placed_hero_payload_plan,
        human_hero_sid=profile.spawn_hero_sid,
        # Use the same placement entity list emit already loaded (propEntities),
        # not a second deserialized top-level copy that can drift.
        global_entities=list(global_entities),
    )
    border_key_gate_dialogs = border_guard_gates.apply_border_key_gate_script(
        mission_id=mission_id,
        plan=border_key_gate_plan,
        chunk3=chunks[3],
        properties=object_properties,
    )
    campaign_script.assert_quest_counter_sids_declared(
        counters=chunks[3].get("counters"),
        quests=chunks[3].get("quests"),
        mission_id=mission_id,
        interruptions=chunks[3].get("interruptions"),
    )
    hero_payloads.assert_script_covers_placed_hero_payloads(
        chunks[3],
        placed_hero_payload_plan,
        human_hero_sid=profile.spawn_hero_sid,
    )

    out_maps = atlas.OUT_ROOT / "maps"
    out_maps.mkdir(parents=True, exist_ok=True)
    # Fail-closed hygiene: never delete unowned map artifacts from a shared output folder.
    # The event-policy contract still requires exactly one current *.map/sidecar pair.
    _assert_owned_output_dir(out_maps, atlas.MAP_SID)
    out_map = out_maps / f"{atlas.MAP_SID}.map"
    out_json = out_maps / f"{atlas.MAP_SID}.json"

    prepare_core_overlay(profile)
    object_stats["homm3ArtifactOverlayMerge"] = merge_homm3_artifact_overlay_into_mission_core(
        atlas.OUT_ROOT / "core_overlay"
    )
    homecoming_lang.write_lang_overlay(atlas.OUT_ROOT / "core_overlay", Path(poc.OLDEN_CORE_ZIP))
    town_construction_contract = object_stats.get("townConstruction")
    if not isinstance(town_construction_contract, dict):
        raise ValueError("raw_translation requires townConstruction contract from layered object emit")
    default_presets = single.read_core_json("DB/buildings_constructions/general_buildings_presets.json")
    template_row = next(
        (
            row
            for row in default_presets.get("array", [])
            if isinstance(row, dict) and row.get("id") == "poor_buildings_construction"
        ),
        None,
    )
    if not isinstance(template_row, dict):
        raise ValueError("Core.zip missing poor_buildings_construction template for H3 town presets")
    existing_preset_path = (
        atlas.OUT_ROOT / "core_overlay" / "DB" / "buildings_constructions" / "custom_maps_buildings_presets.json"
    )
    existing_preset_doc = atlas.read_json(existing_preset_path) if existing_preset_path.is_file() else {"array": []}
    town_construction_overlay = town_construction.write_town_construction_overlay(
        overlay_root=atlas.OUT_ROOT / "core_overlay",
        town_contract=town_construction_contract,
        template_row=template_row,
        existing_preset_doc=existing_preset_doc,
    )
    object_stats["townConstructionOverlay"] = town_construction_overlay
    padding_blocker_overlay = atlas.write_envelope_padding_blocker_overlay()
    padding_blockers = {
        **padding_blockers,
        "overlay": padding_blocker_overlay,
    }
    projected["envelopePaddingVoid"] = {
        **(projected.get("envelopePaddingVoid") or {}),
        "blockers": padding_blockers,
    }
    with lob.single_output_context():
        map_event_specs = campaign_script.map_event_specs_by_source_key(alignment_story)
        single.generate_squad_overlays(
            global_entities,
            map_event_specs=map_event_specs,
            human_h3_owner=int(profile.start_hero_contract.owner),
        )
        single.generate_subterranean_gate_portal_overlay()
        single.generate_homm3_landon_object_overlay()
        object_billboard_report["overlay"] = object_billboards.write_host_overlay(
            atlas.OUT_ROOT / "core_overlay",
            set(object_billboard_report["bySid"]),
        )
        if exact_registry is not None:
            single.generate_exact_homm3_footprint_overlay(exact_registry)
            # Blocker ObjectConfig only (no scenery visual clones on raw).
            single.generate_homm3_pathability_alignment_overlay({})
        single.generate_quickstart_overlay(atlas.MAP_SID)
        dialog_entries = campaign_script.core_dialog_entries_from_alignment(mission_id, alignment_story)
        dialog_entries.extend(
            campaign_script.core_dialog_entries_from_monster_messages(
                mission_id,
                global_entities,
                mission_title=alignment_story.get("missionTitle") or atlas.TITLE,
            )
        )
        intro_text = "\n\n".join(
            str(segment.get("body") or "").strip()
            for segment in (alignment_story.get("briefingSegments") or [])
            if isinstance(segment, dict) and str(segment.get("body") or "").strip()
        )
        if intro_text:
            intro_sid = (
                single.INTRO_DIALOG_SID
                if mission_id == "homecoming"
                else f"{mission_id}_intro_dialog"
            )
            intro_title = campaign_script.mission_display_title(mission_id, atlas.TITLE)
            intro_entry = {"id": intro_sid, "title": intro_title, "text": intro_text}
            intro_entry = campaign_script._apply_dialog_portrait_plans(mission_id, [intro_entry])[0]
            dialog_entries = [
                intro_entry,
                *[entry for entry in dialog_entries if entry.get("id") != intro_sid],
            ]
        dialog_entries.extend(border_key_gate_dialogs)
        if dialog_entries:
            single.generate_campaign_dialog_overlay(dialog_entries)

    visual_report = object_stats.get("visualSceneryCanon") or {}
    if visual_report.get("status") == visual_scenery_canon_postpass.STATUS_APPLIED:
        # Full pre-pass container for one-step reverse (restore copies backup → live).
        backup_chunks = copy.deepcopy(chunks)
        backup_map_data = backup_chunks[1]
        backup_map_data["tilesMap"] = list(visual_pre_snapshot["tilesMap"])
        backup_map_data["waterMap"] = list(visual_pre_snapshot["waterMap"])
        backup_map_data["objects"] = visual_pre_snapshot["objects"]
        backup_path = visual_scenery_canon_postpass.write_pre_postpass_backup(
            live_map_path=out_map,
            container=poc.OldenMapContainer(
                container.version, container.prefix_suffix, backup_chunks
            ),
            hash_sum=map_hash,
        )
        visual_report = dict(visual_report)
        visual_report["backupMap"] = str(backup_path.relative_to(poc.ROOT)).replace("\\", "/")
        object_stats["visualSceneryCanon"] = visual_report

    ocean_errors = campaign_ocean.map_ocean_errors(chunks[1], label=atlas.MAP_SID)
    if ocean_errors:
        raise ValueError("raw_translation ocean contract: " + "; ".join(ocean_errors))
    poc.write_olden_map_container(
        out_map,
        poc.OldenMapContainer(container.version, container.prefix_suffix, chunks),
        map_hash,
    )
    atlas.write_json(out_json, campaign_script.map_quest_sidecar_payload(chunks[3]))

    disabled_post_passes = {
        "blockParity": {"status": "disabled"},
        "accessibilityRepair": {"status": "disabled"},
        "mountainMerge": {"status": "disabled"},
        "localApproachCell": {"status": "disabled"},
        "omitSigns": {"status": "disabled", "policy": "raw_translation_keep_source_sign_placements"},
        # Legacy disabled/omitted pin (homecoming validator). Real relocate is spawnFootprintUnbury.
        "spawnUnbury": {
            "status": "omitted",
            "policy": "superseded_by_spawnFootprintUnbury_gate_visit_reject_envelope_padding",
        },
        "spawnFootprintUnbury": object_stats.get("spawnFootprintUnbury")
        or {
            "status": "noop",
            "policy": "spawn_footprint_unbury_gate_visit_only_reject_envelope_padding_elevated",
            "buryPolicy": "gate_visit_cell_only",
        },
        "landonGateWaterClear": {"status": "disabled"},
        "boatPlacementAdjust": {"status": "disabled"},
        "environmentDecorations": {"status": "disabled"},
        "functionalEmitReservation": {"status": "disabled"},
        "exactAnchorScenerySuppress": {"status": "disabled"},
        "landonAccess": object_stats.get("landonAccess") or {"status": "missing"},
        "gateFaceRotation": object_stats.get("gateFaceRotation") or {"status": "missing"},
        "visualSceneryCanon": object_stats.get("visualSceneryCanon")
        or {"status": "missing"},
        "entranceOccupancy": object_stats.get("entranceOccupancy")
        or {"status": "missing"},
        "homm3BankRemapping": object_stats.get("homm3BankRemapping"),
        "borderKeyGates": object_stats.get("borderKeyGates") or {"status": "missing"},
        "homm3FootprintCompatibility": object_stats.get("homm3FootprintCompatibility")
        or {"status": "missing"},
        "undergroundTunnelClearance": {
            "status": "applied" if ug_clearance_applied else "disabled",
            "policy": (
                None
                if ug_layer_clearance is None
                else ug_layer_clearance.get("policy")
            ),
            "layerStatuses": ug_tunnel_statuses,
            "contract": ug_layer_clearance,
        },
        "undergroundPayloadlessScenerySuppress": {
            "status": "disabled",
            "layerStatuses": ug_scenery_statuses,
        },
    }

    # Pull layer-level fer/suppress evidence from object_stats when present.
    fer_statuses = []
    for layer_stat in (object_stats.get("layerStats") or {}).values():
        if not isinstance(layer_stat, dict):
            continue
        fer = layer_stat.get("functionalEmitReservation")
        if isinstance(fer, dict):
            fer_statuses.append(fer.get("status") or fer.get("policy"))
        anchor = layer_stat.get("sourceAnchorComposition")
        if isinstance(anchor, dict) and anchor.get("status") == "disabled":
            disabled_post_passes["exactAnchorScenerySuppress"]["status"] = "disabled"

    manifest = {
        "schema": SCHEMA,
        "status": atlas.STATUS,
        "proofBoundary": "generated_artifact_validator_runtime_unvalidated",
        "mapSid": atlas.MAP_SID,
        "title": atlas.TITLE,
        "scenarioId": profile.scenario_id,
        "pipeline": PIPELINE,
        "emitPolicyPack": EMIT_POLICY.to_manifest(),
        "brNodeShiftPolicy": emit_policy.RAW_TRANSLATION_BR_NODE_SHIFT_POLICY,
        "output": {
            "map": str(out_map.relative_to(poc.ROOT)).replace("\\", "/"),
            "script": str(out_json.relative_to(poc.ROOT)).replace("\\", "/"),
            "coreOverlay": str((atlas.OUT_ROOT / "core_overlay").relative_to(poc.ROOT)).replace("\\", "/"),
        },
        "postPasses": disabled_post_passes,
        "landonClones": {
            "status": "enabled",
            "policy": "raw_translation_landon_bottom_gate_size_mismatch_only",
        },
        "exactHomm3Footprints": {
            "status": "enabled" if exact_registry is not None else "disabled",
            "policy": "keep_donor_native_nodes_plus_visible_gap_fill_scenery_catalog_or_solid_square",
            "stats": None if exact_registry is None else exact_registry.stats,
        },
        "pathabilityGapFill": object_stats.get("pathabilityGapFill"),
        "pathabilityGapFillAfterLandonAccess": object_stats.get("pathabilityGapFillAfterLandonAccess"),
        "objectBillboards": object_stats.get("objectBillboards"),
        "homm3SceneryFootprint": scenery_footprint,
        "occupiedOverlapDiagnostic": overlap_diagnostic,
        "placementGroundTruth": {
            "schema": ground_truth.get("schema"),
            "status": "applied",
            "artifact": str(ground_truth_path.relative_to(poc.ROOT)).replace("\\", "/"),
            "stats": ground_truth.get("stats"),
        },
        "scenarioPlayers": object_stats.get("scenarioPlayerSpawns") or {},
        "heroHireContract": {
            "status": "homm3_multi_hero",
            "heroCountMin": native_settings["heroCountMin"],
            "heroCountMax": native_settings["heroCountMax"],
            "enableCustomHeroMaxLevel": native_settings["enableCustomHeroMaxLevel"],
            "customHeroMaxLevel": native_settings["customHeroMaxLevel"],
            "h3mLevelLimit": hero_level_limit,
            "missionId": mission.mission_id,
            "evidence": (
                f"H3M levelLimit={hero_level_limit} for {mission.mission_id} "
                f"({mission.campaign_entry} block {mission.block_index}); "
                "multi-hero hire (heroCountMax=8); cities keep default_buildings_ban "
                "(tavern not banned)"
            ),
            "proofBoundary": (
                "generated_artifact from H3M header; runtime tavern hire and "
                "customHeroMaxLevel enforcement remain user-unvalidated"
            ),
        },
        "townOwnership": object_stats.get("townOwnership") or {},
        "townNameAssignment": object_stats.get("townNameAssignment") or {"status": "missing"},
        "heroPatrolSink": {
            "status": "blocked_no_native_sink",
            "policy": "h3_patrol_radius_not_emitted_isLocked_is_not_adventure_patrol",
            "proofBoundary": (
                "HoMM3 patrolRadius (Xyron 255) has no PropHero/PropSpawn field in DiffableCs; "
                "propSpawns.isLocked is lobby lock, not stand-still AI"
            ),
        },
        "forbiddenSpine": {
            "bannedModules": list(FORBIDDEN_IMPORT_NAMES),
            "importedAtGenerate": False,
        },
        "travelLinkVisualContract": travel_link_visual_contract,
        "projectionStats": projection_stats,
        "envelopePaddingVoid": projected.get("envelopePaddingVoid") or {},
        "objectStats": {
            "emittedObjectGroupCount": len(objects),
            "homm3BoatInstanceCount": sum(
                len(group.get("ids") or [])
                for group in objects
                if isinstance(group, dict) and group.get("sid") == single.HOMM3_BOAT_SID
            ),
            "pathabilityVisualSidCount": len(pathability_visual_rows),
            "functionalEmitReservationStatuses": fer_statuses,
        },
        "displayWater": {
            "oceanNodeCount": display_water_summary.get("oceanNodeCount"),
            "shorelineRiverSummary": shoreline_river_summary,
        },
        "runtimeWaterProfile": {
            "mapSid": atlas.MAP_SID,
            "profileResolver": "HomecomingMapProfile",
            "profileId": "raw_translation_surface",
            "requiresPluginSidAllowlist": True,
        },
        "parityPadCount": 0,
        "knownGaps": list(profile.known_gaps),
    }

    # Fail-closed: StoryHub weave reads install_manifest.scenarioPlayers; those owners
    # must match the map that was just written (propSpawns + propCities). A stale or
    # env-polluted manifest previously left Secret1/the_grail with weave [1..4] vs map [7].
    final_map_owners = sorted(
        {
            int(row["owner"])
            for key in ("propSpawns", "propCities")
            for row in (object_properties.get(key) or [])
            if isinstance(row, dict) and isinstance(row.get("owner"), int)
        }
    )
    scenario_players = manifest.get("scenarioPlayers") or {}
    manifest_owners = sorted(int(o) for o in (scenario_players.get("oldenOwners") or []))
    human_owner = scenario_players.get("humanOldenOwner")
    if manifest_owners != final_map_owners:
        raise ValueError(
            f"scenarioPlayers.oldenOwners {manifest_owners} != final map owners "
            f"{final_map_owners}; refusing desynced install_manifest (StoryHub preflight risk)"
        )
    if human_owner is None or int(human_owner) not in final_map_owners:
        raise ValueError(
            f"scenarioPlayers.humanOldenOwner {human_owner!r} not in final map owners "
            f"{final_map_owners}"
        )
    # Native compact owner contract: stock Olden maps number players 1..N with the
    # human as owner 1. Non-compact owners (H3 color pass-through) reference player
    # seats the runtime never creates and silently break town ownership grants.
    if final_map_owners != list(range(1, len(final_map_owners) + 1)):
        raise ValueError(
            f"final map owners {final_map_owners} are not compact 1..N; "
            "renumber_map_owners_to_native_compact must run before emit"
        )
    if int(human_owner) != 1:
        raise ValueError(
            f"scenarioPlayers.humanOldenOwner {human_owner!r} != 1; human must hold "
            "the native first player seat"
        )
    meta_spawns = (chunks[0].get("spawns") or {}) if isinstance(chunks[0], dict) else {}
    meta_count = meta_spawns.get("playersCount")
    if meta_count != scenario_players.get("playersCount") or meta_count != len(final_map_owners):
        raise ValueError(
            f"meta.spawns.playersCount {meta_count!r} != scenarioPlayers.playersCount "
            f"{scenario_players.get('playersCount')!r} / map owner count {len(final_map_owners)}"
        )

    atlas.write_json(atlas.OUT_ROOT / "install_manifest.json", manifest)
    _phase("total", t_all)
    atlas.write_json(atlas.OUT_ROOT / "raw_translation_report.json", {
        "emitPolicyPack": EMIT_POLICY.to_manifest(),
        "occupiedOverlapDiagnostic": overlap_diagnostic,
        "homm3SceneryFootprint": scenery_footprint,
        "postPasses": disabled_post_passes,
        "placementGroundTruth": {
            "artifact": str(ground_truth_path.relative_to(poc.ROOT)).replace("\\", "/"),
            "stats": ground_truth.get("stats"),
        },
        "phaseTimingsSec": phase_timings,
    })
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Homecoming raw_translation map")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument(
        "--enable-homm3-footprint-compatibility",
        action="store_true",
        help="Run the isolated H3-versus-Olden footprint repair pass on this candidate map.",
    )
    parser.add_argument(
        "--enable-homm3-bank-remapping",
        action="store_true",
        help=(
            "Run the isolated HoMM3 creature-bank/Den remapping pass before "
            "footprint repair and visual scenery randomization."
        ),
    )
    parser.add_argument(
        "--skip-visual-scenery-postpass",
        action="store_true",
        help=(
            "Skip the separate visual scenery / canon terrain postpass "
            f"(also honored via env {visual_scenery_canon_postpass.SKIP_ENV}=1)"
        ),
    )
    args = parser.parse_args()
    profile = load_scenario_profile(args.profile)
    manifest = generate_map(
        profile,
        skip_visual_scenery_postpass=bool(args.skip_visual_scenery_postpass),
        enable_homm3_footprint_compatibility=bool(args.enable_homm3_footprint_compatibility),
        enable_homm3_bank_remapping=bool(args.enable_homm3_bank_remapping),
    )
    print(json.dumps({"ok": True, "mapSid": manifest["mapSid"], "output": manifest["output"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
