#!/usr/bin/env python3
"""Copied layered object emit leaves for approach_cell (no footprint/FP spine)."""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
from typing import Any, Iterator

import campaign_runtime_script as campaign_script
import exact_homm3_footprint as exact_fp
import h3_town_name_pool
import h3m_object_registry as h3obj
import h3m_scenario_translation as scenario
import h3m_town_construction as town_construction
import homecoming_localization as homecoming_lang
import surface_emit as single
from layer_atlas import (
    ALIGNMENT_PATH,
    LAYER_SPECS,
    MAP_SID,
    MONOLITH_PORTAL_SIDS,
    OLDEN_HEIGHT,
    OLDEN_WIDTH,
    OUT_ROOT,
    SOURCE_HEIGHT,
    SOURCE_WIDTH,
    SUBTERRANEAN_GATE_PORTAL_SID,
    UNDERGROUND_PAYLOADLESS_SCENERY_SUPPRESSION_POLICY,
    UNDERGROUND_PAYLOADLESS_SCENERY_SUPPRESSION_STATUS,
    read_json,
)

_ACTIVE_PROFILE = None
TERRANEUS_SOURCE_KEY = "1:35:35"
TERRANEUS_OBJECT_ID = 1454


def mission_id_from_profile(profile: Any) -> str:
    from scenario_profile import mission_id_from_profile as _mission_id_from_profile

    return _mission_id_from_profile(profile)


def set_active_profile(profile: Any) -> None:
    global _ACTIVE_PROFILE
    _ACTIVE_PROFILE = profile

@contextmanager
def single_output_context() -> Iterator[None]:
    mission_id = mission_id_from_profile(_ACTIVE_PROFILE) if _ACTIVE_PROFILE is not None else single.MISSION_ID
    patches = {"MAP_SID": MAP_SID, "OUT_ROOT": OUT_ROOT}
    previous = {name: getattr(single, name) for name in patches}
    previous_mission = single.MISSION_ID
    previous_squad_root = single.SQUAD_OVERLAY_MEMBER_ROOT
    try:
        for name, value in patches.items():
            setattr(single, name, value)
        single.set_mission_id(mission_id)
        yield
    finally:
        for name, value in previous.items():
            setattr(single, name, value)
        single.MISSION_ID = previous_mission
        single.SQUAD_OVERLAY_MEMBER_ROOT = previous_squad_root


@contextmanager
def single_projection_context(layer: int) -> Iterator[None]:
    spec = LAYER_SPECS[layer]
    mission_id = mission_id_from_profile(_ACTIVE_PROFILE) if _ACTIVE_PROFILE is not None else single.MISSION_ID
    patches = {
        "OLDEN_WIDTH": OLDEN_WIDTH,
        "OLDEN_HEIGHT": OLDEN_HEIGHT,
        "SOURCE_WIDTH": SOURCE_WIDTH,
        "SOURCE_HEIGHT": SOURCE_HEIGHT,
        "SOURCE_OFFSET_X": spec["offsetX"],
        "SOURCE_OFFSET_Y": spec["offsetY"],
        "MAP_SID": MAP_SID,
        "OUT_ROOT": OUT_ROOT,
    }
    previous = {name: getattr(single, name) for name in patches}
    previous_mission = single.MISSION_ID
    previous_squad_root = single.SQUAD_OVERLAY_MEMBER_ROOT
    try:
        for name, value in patches.items():
            setattr(single, name, value)
        single.set_mission_id(mission_id)
        yield
    finally:
        for name, value in previous.items():
            setattr(single, name, value)
        single.MISSION_ID = previous_mission
        single.SQUAD_OVERLAY_MEMBER_ROOT = previous_squad_root


def is_start_hero_source(entity: dict[str, Any]) -> bool:
    profile = _ACTIVE_PROFILE
    if profile is not None:
        return profile.start_hero_contract.matches_entity(entity)
    return {
        "sourceLayer": entity.get("sourceLayer"),
        "heroType": entity.get("heroType"),
        "owner": entity.get("owner"),
        "payloadKind": entity.get("payloadKind"),
        "templateAnimation": entity.get("templateAnimation"),
        "templateObjectId": entity.get("templateObjectId"),
    } == {
        "sourceLayer": 0,
        "heroType": single.START_HERO_SOURCE_HERO_TYPE,
        "owner": 0,
        "payloadKind": "hero_or_prison",
        "templateAnimation": "ah00_e.def",
        "templateObjectId": 34,
    }


def in_source_bounds(entity: dict[str, Any]) -> bool:
    source_x = entity.get("sourceX")
    source_y = entity.get("sourceY")
    return isinstance(source_x, int) and isinstance(source_y, int) and 0 <= source_x < SOURCE_WIDTH and 0 <= source_y < SOURCE_HEIGHT


def split_layer_entities(
    entities: list[dict[str, Any]],
    layer: int,
    substitution_lookup: dict[str, dict[str, Any]],
    valid_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    in_bounds: list[dict[str, Any]] = []
    border_overhang: list[dict[str, Any]] = []
    deferred_non_start_heroes: list[dict[str, Any]] = []
    for entity in entities:
        if entity.get("sourceLayer") != layer:
            continue
        if not in_source_bounds(entity):
            border_overhang.append(entity)
            continue
        # Non-start heroes emit as hero-spawner + propHeroes (append_placed_hero_properties).
        _replacement_sid, _rule_name, _lossiness = single.resolve_replacement_sid(entity, substitution_lookup, valid_ids)
        in_bounds.append(entity)
    return in_bounds, border_overhang, deferred_non_start_heroes


def merge_object_groups(layer_objects: dict[int, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, list[Any]]] = defaultdict(lambda: {"ids": [], "nodes": [], "rotations": [], "levels": []})
    seen_ids: set[int] = set()
    for layer in sorted(layer_objects):
        for group in layer_objects[layer]:
            sid = group.get("sid")
            if not isinstance(sid, str):
                raise ValueError(f"emitted object group missing string SID on layer {layer}: {group}")
            ids = group.get("ids") or []
            nodes = group.get("nodes") or []
            rotations = group.get("rotations") or []
            levels = group.get("levels") or []
            if not (len(ids) == len(nodes) == len(rotations) == len(levels)):
                raise ValueError(f"object group length mismatch for {sid} on layer {layer}")
            for object_id in ids:
                if not isinstance(object_id, int):
                    raise ValueError(f"object id is not integer for {sid}: {object_id!r}")
                if object_id in seen_ids:
                    raise ValueError(f"duplicate emitted object id across atlas layers: {object_id}")
                seen_ids.add(object_id)
            grouped[sid]["ids"].extend(ids)
            grouped[sid]["nodes"].extend(nodes)
            grouped[sid]["rotations"].extend(rotations)
            grouped[sid]["levels"].extend(levels)
    return [{"sid": sid, **grouped[sid]} for sid in sorted(grouped)]


def merge_properties(layer_properties: dict[int, dict[str, Any]]) -> dict[str, Any]:
    keys: set[str] = set()
    for props in layer_properties.values():
        keys.update(props)
    merged: dict[str, Any] = {}
    for key in sorted(keys):
        merged[key] = []
    for layer in sorted(layer_properties):
        for key, rows in layer_properties[layer].items():
            if not isinstance(rows, list):
                raise ValueError(f"property family {key} on layer {layer} is not a list")
            merged[key].extend(rows)
    return merged


def object_id_to_sid(objects: list[dict[str, Any]]) -> dict[int, str]:
    result: dict[int, str] = {}
    for group in objects:
        sid = group.get("sid")
        if not isinstance(sid, str):
            continue
        for object_id in group.get("ids") or []:
            if isinstance(object_id, int):
                result[object_id] = sid
    return result


def object_id_to_node(objects: list[dict[str, Any]]) -> dict[int, int]:
    result: dict[int, int] = {}
    for group in objects:
        ids = group.get("ids") or []
        nodes = group.get("nodes") or []
        for object_id, node in zip(ids, nodes):
            if isinstance(object_id, int) and isinstance(node, int):
                result[object_id] = node
    return result


_PROPCITY_NON_NATIVE_FIELDS = (
    "owner",
    "garrisonStacks",
    "builtBuildingsMask",
    "forbiddenBuildingsMask",
)


def normalize_map_only_city_properties(properties: dict[str, Any]) -> dict[str, Any]:
    """Strip non-native PropCity fields and apply native-shaped SID placeholders.

    ``buildingsConstructionSid`` is overwritten immediately afterward by
    ``h3m_town_construction.apply_town_construction_from_h3`` from the H3 mask.
    The rich placeholder must never remain as the final starting-buildings policy.
    """
    rows = properties.get("propCities") or []
    if not isinstance(rows, list):
        raise ValueError("propCities must be a list before map-only city normalization")
    normalized_ids: list[int] = []
    stripped_field_counts: dict[str, int] = {key: 0 for key in _PROPCITY_NON_NATIVE_FIELDS}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), int):
            raise ValueError(f"malformed propCities row before map-only city normalization: {row}")
        row["buildingsBanSid"] = "default_buildings_ban"
        row["buildingsConstructionSid"] = "rich_buildings_construction"
        row["buildingsSettingsSid"] = "default_buildings_settings"
        for key in _PROPCITY_NON_NATIVE_FIELDS:
            if key in row:
                del row[key]
                stripped_field_counts[key] += 1
        normalized_ids.append(row["id"])
    return {
        "status": "native_default_city_building_sids_placeholder_before_h3_mask_apply",
        "normalizedCityIds": normalized_ids,
        "buildingsBanSid": "default_buildings_ban",
        "buildingsConstructionSid": "rich_buildings_construction",
        "buildingsSettingsSid": "default_buildings_settings",
        "strippedNonNativePropCityFields": stripped_field_counts,
        "note": "rich_buildings_construction is a temporary placeholder; H3 mask apply replaces it",
    }

def upsert_property_row_by_id(rows: list[Any], row: dict[str, Any]) -> None:
    object_id = row.get("id")
    if not isinstance(object_id, int):
        raise ValueError(f"property row missing integer id: {row}")
    for index, existing in enumerate(rows):
        if isinstance(existing, dict) and existing.get("id") == object_id:
            rows[index] = row
            return
    rows.append(row)


def configure_layered_city_properties(properties: dict[str, Any], objects: list[dict[str, Any]], entities_by_id: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    profile = _ACTIVE_PROFILE
    featured_cities = profile.featured_cities if profile is not None else ()
    if not featured_cities:
        return []
    id_to_sid = object_id_to_sid(objects)
    rows: list[dict[str, Any]] = []
    for contract in featured_cities:
        emitted_sid = id_to_sid.get(contract.object_id)
        if emitted_sid is None:
            raise ValueError(
                f"expected {contract.name} object id {contract.object_id} "
                f"({contract.replacement_sid}); not present on map"
            )
        landon_ids = sorted(object_id for object_id, sid in id_to_sid.items() if sid == contract.replacement_sid)
        exact_ok = exact_fp.is_exact_footprint_sid(str(emitted_sid))
        if emitted_sid == contract.replacement_sid:
            if landon_ids != [contract.object_id]:
                raise ValueError(
                    f"expected only {contract.name} as emitted {contract.replacement_sid} "
                    f"id {contract.object_id}; found {landon_ids}"
                )
        elif exact_ok:
            if landon_ids:
                raise ValueError(
                    f"{contract.name} exact-footprint city {contract.object_id} sid={emitted_sid} "
                    f"but leftover {contract.replacement_sid} ids remain: {landon_ids}"
                )
        else:
            raise ValueError(
                f"expected {contract.name} as {contract.replacement_sid} or exact-fp clone "
                f"id {contract.object_id}; found sid {emitted_sid!r}"
            )
        entity = entities_by_id.get(contract.object_id)
        if not entity or entity.get("sourceKey") != contract.source_key or entity.get("name") != contract.name:
            raise ValueError(f"{contract.name} source entity mismatch for city properties: {entity}")
        # PropCity has no owner/garrison fields; ownership/garrisons bind later via
        # append_town_ownership_and_garrison_properties (propSpawns City + propRandomSquads).
        row = {
            "type": 0,
            "id": contract.object_id,
            "isDefined": True,
            "factionSid": contract.faction_sid,
            "spawnHero": False,
            "customCityName": homecoming_lang.custom_city_name_sid(contract.custom_city_name),
            "buildingsBanSid": contract.buildings_ban_sid,
            "buildingsConstructionSid": contract.buildings_construction_sid,
            "buildingsSettingsSid": contract.buildings_settings_sid,
        }
        # Land-on city emission already writes a generic propCities row; featured
        # contracts must replace it (name/faction) rather than duplicate the id.
        upsert_property_row_by_id(properties.setdefault("propCities", []), row)
        capture_entity_sid = campaign_script.featured_capture_entity_sid(
            mission_id_from_profile(profile),
            city_name=contract.name,
        )
        upsert_property_row_by_id(
            properties.setdefault("propEntities", []),
            {
                "type": 0,
                "id": contract.object_id,
                "sid": capture_entity_sid,
            },
        )
        rows.append({**row, "captureEntitySid": capture_entity_sid})
    return rows


def configure_victory_target_entities(
    properties: dict[str, Any],
    objects: list[dict[str, Any]],
    entities_by_id: dict[int, dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Validate profile TAKEDWELLINGS overlays; propEntities stamping is owned by campaign_victory.

    Header-derived victory planning in ``campaign_victory.plan_campaign_victory`` stamps
    dwellings/mines/towns. This hook only fail-closes when a profile ``victoryContract``
    lists source keys that do not resolve to unique creature generators.
    """

    profile = _ACTIVE_PROFILE
    contract = getattr(profile, "victory_contract", None) if profile is not None else None
    if contract is None:
        return None
    if contract.victory_type != "TAKEDWELLINGS":
        raise ValueError(
            f"profile victoryContract.type {contract.victory_type!r} is not supported; "
            "only TAKEDWELLINGS overlays remain (header owns other victory types)"
        )
    source_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entity in entities_by_id.values():
        if (
            entity.get("category") != "external_dwelling"
            or entity.get("payloadKind") != "creature_generator"
        ):
            continue
        source_rows[str(entity.get("sourceKey") or "")].append(entity)
    id_to_sid = object_id_to_sid(objects)
    bindings: list[dict[str, Any]] = []
    for source_key in contract.source_keys:
        matches = source_rows.get(source_key, [])
        if len(matches) != 1:
            raise ValueError(
                f"{contract.victory_type} source key {source_key!r} must resolve exactly once; "
                f"found {len(matches)}"
            )
        object_id = matches[0].get("sourceIndex")
        if not isinstance(object_id, int):
            raise ValueError(f"{contract.victory_type} source {source_key!r} has no integer sourceIndex")
        emitted_sid = id_to_sid.get(object_id)
        config = native_object_configs.get(str(emitted_sid))
        exact_donor = (
            ((config or {}).get(exact_fp.META_KEY) or {}).get("donorSid")
            if exact_fp.is_exact_footprint_sid(str(emitted_sid))
            else None
        )
        if emitted_sid != contract.expected_emitted_sid and exact_donor != contract.expected_emitted_sid:
            raise ValueError(
                f"{contract.victory_type} source {source_key!r} emitted SID must be "
                f"{contract.expected_emitted_sid!r} or its exact-footprint clone; got {emitted_sid!r}"
            )
        bindings.append(
            {
                "sourceKey": source_key,
                "objectId": object_id,
                "emittedSid": emitted_sid,
                "stampedBy": "campaign_victory",
            }
        )
    return {
        "type": contract.victory_type,
        "allowNormalVictory": contract.allow_normal_victory,
        "expectedEmittedSid": contract.expected_emitted_sid,
        "bindings": bindings,
        "stampDeferredToCampaignVictory": True,
    }


def build_layered_portal_targets(objects: list[dict[str, Any]], entities_by_id: dict[int, dict[str, Any]]) -> tuple[dict[int, int], dict[str, Any]]:
    id_to_sid = object_id_to_sid(objects)
    subterranean_portal_ids = sorted(object_id for object_id, sid in id_to_sid.items() if sid == SUBTERRANEAN_GATE_PORTAL_SID)
    whirlpool_portal_ids = sorted(object_id for object_id, sid in id_to_sid.items() if sid == "portal_magic")
    monolith_portal_ids = sorted(object_id for object_id, sid in id_to_sid.items() if sid in MONOLITH_PORTAL_SIDS)
    unsupported = sorted({
        sid for sid in id_to_sid.values()
        if sid in single.PORTAL_SIDS and sid not in {SUBTERRANEAN_GATE_PORTAL_SID, "portal_magic", *MONOLITH_PORTAL_SIDS}
    })
    if unsupported:
        raise ValueError(f"layered atlas has no explicit route contract for portal SID(s): {unsupported}")
    candidate_entities: list[dict[str, Any]] = []
    for object_id in subterranean_portal_ids:
        entity = entities_by_id.get(object_id)
        if not entity:
            raise ValueError(f"{SUBTERRANEAN_GATE_PORTAL_SID} object {object_id} has no source entity")
        expected_cave = {
            "templateAnimation": "AvTCave.def",
            "templateObjectId": h3obj.OBJECT_SUBTERRANEAN_GATE,
            "category": "travel_link_candidate",
            "payloadKind": "explicit_no_payload",
        }
        mismatches = {key: entity.get(key) for key, expected in expected_cave.items() if entity.get(key) != expected}
        if mismatches:
            raise ValueError(f"{SUBTERRANEAN_GATE_PORTAL_SID} object {object_id} is not a validated subterranean-gate candidate: {mismatches}")
        candidate_entities.append(entity)

    subterranean_contract = scenario.pair_subterranean_gates_by_nearest_cross_layer_rule(candidate_entities)
    targets: dict[int, int] = {}
    for pair in subterranean_contract["pairs"]:
        surface_id = int(pair["surfaceObjectId"])
        underground_id = int(pair["undergroundObjectId"])
        targets[surface_id] = underground_id
        targets[underground_id] = surface_id
    if sorted(object_id for object_id in targets if object_id in subterranean_portal_ids) != subterranean_portal_ids:
        raise ValueError(f"portal target coverage mismatch: ids={subterranean_portal_ids} targets={sorted(targets)}")

    whirlpool_entities: list[dict[str, Any]] = []
    for object_id in whirlpool_portal_ids:
        entity = entities_by_id.get(object_id)
        if not entity:
            raise ValueError(f"portal_magic object {object_id} has no source entity")
        if entity.get("templateObjectId") != h3obj.OBJECT_WHIRLPOOL:
            raise ValueError(
                f"portal_magic object {object_id} is not a whirlpool source: "
                f"templateObjectId={entity.get('templateObjectId')}"
            )
        whirlpool_entities.append(entity)
    whirlpool_contract = scenario.pair_whirlpools_by_nearest_same_layer_rule(whirlpool_entities)
    for pair in whirlpool_contract["pairs"]:
        # Directed routes (mutual for even same-layer; circular for odd/cross-layer).
        targets[int(pair["objectIdA"])] = int(pair["objectIdB"])

    monolith_entities: list[dict[str, Any]] = []
    for object_id in monolith_portal_ids:
        entity = entities_by_id.get(object_id)
        if not entity:
            raise ValueError(f"monolith portal object {object_id} has no source entity")
        if entity.get("templateObjectId") != h3obj.OBJECT_TWO_WAY_MONOLITH:
            raise ValueError(
                f"monolith portal object {object_id} is not a two-way monolith source: "
                f"templateObjectId={entity.get('templateObjectId')}"
            )
        monolith_entities.append(entity)
    monolith_contract = scenario.pair_two_way_monoliths_by_subtype_cross_layer_rule(monolith_entities)
    for pair in monolith_contract["pairs"]:
        # Pairs are already directed (mutual for N=2, circular for N>2).
        targets[int(pair["objectIdA"])] = int(pair["objectIdB"])

    expected_portal_ids = sorted(subterranean_portal_ids + whirlpool_portal_ids + monolith_portal_ids)
    if sorted(targets) != expected_portal_ids:
        raise ValueError(
            f"portal target coverage mismatch: expected={expected_portal_ids} targets={sorted(targets)}"
        )
    return targets, {
        "status": subterranean_contract["status"],
        "sid": SUBTERRANEAN_GATE_PORTAL_SID,
        "sidFamily": "homm3_dungeon_entrance_portal",
        "source": subterranean_contract["source"],
        "evidence": "dungeon_entrance_prefab_with_native_prop_portals_pairing",
        "policy": subterranean_contract["policy"],
        "tieBreak": subterranean_contract["tieBreak"],
        "pairCount": subterranean_contract["pairCount"],
        "pairs": subterranean_contract["pairs"],
        "whirlpoolRouteContract": {
            "status": whirlpool_contract["status"],
            "sid": "portal_magic",
            "source": whirlpool_contract["source"],
            "policy": whirlpool_contract["policy"],
            "tieBreak": whirlpool_contract["tieBreak"],
            "pairCount": whirlpool_contract["pairCount"],
            "pairs": whirlpool_contract["pairs"],
        },
        "monolithRouteContract": {
            "status": monolith_contract["status"],
            "sidFamily": sorted(MONOLITH_PORTAL_SIDS),
            "source": monolith_contract["source"],
            "policy": monolith_contract["policy"],
            "tieBreak": monolith_contract["tieBreak"],
            "pairCount": monolith_contract["pairCount"],
            "pairs": monolith_contract["pairs"],
        },
    }


def replace_portal_properties(properties: dict[str, Any], portal_targets: dict[int, int]) -> None:
    properties["propPortals"] = [
        {"type": 0, "id": object_id, "targetIdx": portal_targets[object_id], "isActive": True}
        for object_id in sorted(portal_targets)
    ]


def remove_object_ids_from_groups(objects: list[dict[str, Any]], suppressed_ids: set[int]) -> list[dict[str, Any]]:
    removed: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    for group in objects:
        sid = group.get("sid")
        ids = group.get("ids") or []
        nodes = group.get("nodes") or []
        rotations = group.get("rotations") or []
        levels = group.get("levels") or []
        if not isinstance(sid, str) or not (len(ids) == len(nodes) == len(rotations) == len(levels)):
            raise ValueError(f"malformed object group before underground scenery suppression: {group}")
        keep = {index for index, object_id in enumerate(ids) if object_id not in suppressed_ids}
        for index, object_id in enumerate(ids):
            if object_id in suppressed_ids:
                removed.append({"id": object_id, "sid": sid, "node": nodes[index], "rotation": rotations[index], "level": levels[index]})
        if keep:
            filtered.append({
                "sid": sid,
                "ids": [object_id for index, object_id in enumerate(ids) if index in keep],
                "nodes": [node for index, node in enumerate(nodes) if index in keep],
                "rotations": [rotation for index, rotation in enumerate(rotations) if index in keep],
                "levels": [level for index, level in enumerate(levels) if index in keep],
            })
    objects[:] = filtered
    return removed


def remove_property_rows_for_object_ids(properties: dict[str, Any], suppressed_ids: set[int]) -> dict[str, int]:
    removed_by_family: dict[str, int] = {}
    for family, rows in properties.items():
        if not isinstance(rows, list):
            raise ValueError(f"property family {family} is not a list before underground scenery suppression")
        kept: list[Any] = []
        removed = 0
        for row in rows:
            if isinstance(row, dict) and row.get("id") in suppressed_ids:
                removed += 1
            else:
                kept.append(row)
        if removed:
            properties[family] = kept
            removed_by_family[family] = removed
    return removed_by_family


def object_group_sid_histogram(objects: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for group in objects:
        sid = group.get("sid")
        ids = group.get("ids") or []
        if isinstance(sid, str):
            counts[sid] += len(ids)
    return dict(counts.most_common())


def native_blocking_footprint_summary(replacement_sid: str, native_object_configs: dict[str, dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    native_config = native_object_configs.get(replacement_sid)
    if not isinstance(native_config, dict):
        raise ValueError(f"missing native object config for underground payloadless scenery SID {replacement_sid}")
    footprint = single.native_main_footprint(native_config, replacement_sid)
    footprint_source = footprint.get("source")
    if footprint_source in single.SOURCE_ANCHOR_POINT_FOOTPRINT_SOURCES:
        return False, footprint
    cell_count = footprint.get("cellCount")
    if isinstance(cell_count, int):
        return cell_count > 0, footprint
    return int(footprint.get("width") or 0) > 0 and int(footprint.get("height") or 0) > 0, footprint


def suppress_underground_payloadless_scenery(
    layer: int,
    layer_entities: list[dict[str, Any]],
    objects: list[dict[str, Any]],
    properties: dict[str, Any],
    substitution_lookup: dict[str, dict[str, Any]],
    valid_ids: set[str],
    native_object_configs: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if not bool(LAYER_SPECS[layer]["view"].get("isUnderground")):
        return None
    return {
        "status": UNDERGROUND_PAYLOADLESS_SCENERY_SUPPRESSION_STATUS,
        "policy": UNDERGROUND_PAYLOADLESS_SCENERY_SUPPRESSION_POLICY,
        "reason": "Underground payloadless scenery now stays emitted; footprint alignment pads or shifts to match HoMM3 masks.",
        "sourceLayer": layer,
        "suppressedObjectCount": 0,
        "suppressedReplacementSidHistogram": {},
        "suppressedRuleHistogram": {},
        "suppressedCategoryHistogram": {},
        "suppressedTemplateObjectIdHistogram": {},
        "suppressedFootprintSourceHistogram": {},
        "suppressedBlockingFootprintCellTotal": 0,
        "preservedNoFootprintSidHistogram": {},
        "examples": [],
    }


def build_layered_objects(
    global_entities: list[dict[str, Any]],
    substitution_lookup: dict[str, dict[str, Any]],
    valid_ids: set[str],
    property_required_sids: dict[str, dict[str, int]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    emit_policy: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    import emit_policy as emit_policy_mod

    policy = emit_policy if emit_policy is not None else emit_policy_mod.APPROACH_CELL_EMIT_POLICY
    # Unnamed H3M towns must carry authentic HoMM3 default-pool names before any
    # layer emits PropCity rows. Runs on the full cross-layer list so the
    # used-name set is map-global (HoMM3 avoids duplicate town names map-wide).
    town_name_assignment = h3_town_name_pool.assign_default_town_names(
        global_entities,
        mission_id=mission_id_from_profile(_ACTIVE_PROFILE) if _ACTIVE_PROFILE is not None else single.MISSION_ID,
    )
    layer_objects: dict[int, list[dict[str, Any]]] = {}
    layer_properties: dict[int, dict[str, Any]] = {}
    layer_stats: dict[int, dict[str, Any]] = {}
    emitted_entities_by_layer: dict[int, list[dict[str, Any]]] = {}
    border_overhang_by_layer: dict[int, list[dict[str, Any]]] = {}
    deferred_non_start_heroes: list[dict[str, Any]] = []
    alignment = read_json(ALIGNMENT_PATH)
    layer_map_data = {
        int(entry["layer"]): entry["mapData"]
        for entry in (alignment.get("layeredMapData") or [])
        if isinstance(entry, dict) and isinstance(entry.get("layer"), int) and isinstance(entry.get("mapData"), dict)
    }
    pathability_visual_rows: dict[str, dict[str, Any]] = {}
    alignment_story = alignment["container"]["chunks"][3]
    map_event_specs = campaign_script.map_event_specs_by_source_key(alignment_story)
    profile = _ACTIVE_PROFILE
    # Oversized scenery becomes non-blocking visual clones before pads so footprint
    # alignment can cover HoMM3 masks without stacking blockers on the same cell.
    enable_pathability_visual_clones = False

    for layer in sorted(LAYER_SPECS):
        layer_entities, border_overhang, deferred_heroes = split_layer_entities(global_entities, layer, substitution_lookup, valid_ids)
        emitted_entities_by_layer[layer] = layer_entities
        border_overhang_by_layer[layer] = border_overhang
        deferred_non_start_heroes.extend(deferred_heroes)
        with single_projection_context(layer):
            synthetic_id_base = None
            objects, properties, stats, layer_pathability_visual_rows = single.build_surface_objects(
                layer_entities,
                substitution_lookup,
                valid_ids,
                property_required_sids,
                native_object_configs,
                portal_property_policy="deferred_to_layered_cross_layer_pairing",
                surface_map_data=layer_map_data.get(layer),
                enable_footprint_alignment=False,
                synthetic_id_base=synthetic_id_base,
                map_event_specs=map_event_specs,
                enable_pathability_visual_clones=enable_pathability_visual_clones,
                emit_policy=policy,
            )
            pathability_visual_rows.update(layer_pathability_visual_rows)
            if policy.exact_homm3_footprints:
                if single.HOMM3_PATHING_BLOCKER_SID not in native_object_configs:
                    raise ValueError(
                        "exact_homm3_footprints gap-fill requires homm3_pathing_blocker in native_object_configs"
                    )
                stats["pathabilityGapFill"] = single.append_homm3_pathability_gap_fill_blockers(
                    objects,
                    layer_entities,
                    native_object_configs,
                    id_base=single.HOMM3_PATHING_BLOCKER_ID_BASE + int(layer) * 100_000,
                )
        if policy.suppress_underground_payloadless_scenery:
            scenery_suppression = suppress_underground_payloadless_scenery(
                layer,
                layer_entities,
                objects,
                properties,
                substitution_lookup,
                valid_ids,
                native_object_configs,
            )
        else:
            scenery_suppression = {
                "status": "disabled",
                "policy": "disabled_raw_translation_emit_policy_pack",
                "sourceLayer": layer,
                "suppressedObjectCount": 0,
                "emitPolicyPack": policy.name,
            }
        if scenery_suppression is not None:
            stats["undergroundPayloadlessScenerySuppression"] = scenery_suppression
            stats["emittedSurfaceEntityCount"] = sum(len(group.get("ids") or []) for group in objects)
            stats["emittedObjectGroupCount"] = len(objects)
            stats["replacementSidHistogram"] = object_group_sid_histogram(objects)
            stats["propertyRowHistogram"] = {key: len(value) for key, value in sorted(properties.items()) if isinstance(value, list) and value}
        layer_objects[layer] = objects
        layer_properties[layer] = properties
        layer_stats[layer] = stats

    objects = merge_object_groups(layer_objects)
    properties = merge_properties(layer_properties)
    entities_by_id = {
        int(entity["sourceIndex"]): entity
        for entity in global_entities
        if isinstance(entity.get("sourceIndex"), int)
    }
    # Post-layer merge runs outside single_projection_context, which restores
    # MISSION_ID to the module default ("homecoming"). Town garrison propRandomSquads
    # SIDs must use the active mission prefix so they match generate_squad_overlays.
    with single_output_context():
        terraneus_city_rows = configure_layered_city_properties(properties, objects, entities_by_id)
        city_property_contract = normalize_map_only_city_properties(properties)
        town_construction_contract = town_construction.apply_town_construction_from_h3(
            properties,
            entities_by_id,
        )
        human_h3_owner = 0
        if _ACTIVE_PROFILE is not None and getattr(_ACTIVE_PROFILE, "start_hero_contract", None) is not None:
            human_h3_owner = int(_ACTIVE_PROFILE.start_hero_contract.owner)
        town_ownership = single.append_town_ownership_and_garrison_properties(
            objects,
            properties,
            entities_by_id,
            human_h3_owner=human_h3_owner,
        )
        victory_target_contract = configure_victory_target_entities(
            properties, objects, entities_by_id, native_object_configs
        )
        portal_targets, portal_contract = build_layered_portal_targets(objects, entities_by_id)
        replace_portal_properties(properties, portal_targets)

    emitted_counts = {
        str(layer): sum(len(group.get("ids") or []) for group in layer_objects[layer])
        for layer in sorted(layer_objects)
    }
    gap_fill_layers = {
        str(layer): layer_stats[layer].get("pathabilityGapFill")
        for layer in sorted(layer_stats)
        if isinstance(layer_stats[layer].get("pathabilityGapFill"), dict)
    }
    gap_fill_total = sum(
        int((entry or {}).get("gapFillBlockerCount") or 0) for entry in gap_fill_layers.values()
    )
    return objects, properties, {
        "emittedLayerEntityCounts": emitted_counts,
        "emittedObjectGroupCount": len(objects),
        "sourceLayerEntityCounts": {str(layer): len(emitted_entities_by_layer[layer]) for layer in sorted(emitted_entities_by_layer)},
        "sourceBorderOverhangCounts": {str(layer): len(border_overhang_by_layer[layer]) for layer in sorted(border_overhang_by_layer)},
        "sourceBorderOverhangKeys": {
            str(layer): [entity.get("sourceKey") for entity in border_overhang_by_layer[layer]]
            for layer in sorted(border_overhang_by_layer)
        },
        "deferredNonStartHeroSpawnerCount": len(deferred_non_start_heroes),
        "deferredNonStartHeroSpawners": deferred_non_start_heroes,
        "layerStats": {str(layer): layer_stats[layer] for layer in sorted(layer_stats)},
        "townNameAssignment": town_name_assignment,
        "featuredCityProperties": terraneus_city_rows,
        "pathabilityVisualSidCount": len(pathability_visual_rows),
        "cityPropertyContract": city_property_contract,
        "townConstruction": town_construction_contract,
        "townOwnership": town_ownership,
        "victoryTargetContract": victory_target_contract,
        "portalRouteContract": portal_contract,
        "propertyRowHistogram": {key: len(value) for key, value in sorted(properties.items()) if isinstance(value, list) and value},
        "pathabilityVisualRows": pathability_visual_rows,
        "pathabilityGapFill": {
            "status": "applied" if gap_fill_layers else "disabled",
            "gapFillBlockerCount": gap_fill_total,
            "layers": gap_fill_layers,
        },
    }, pathability_visual_rows


