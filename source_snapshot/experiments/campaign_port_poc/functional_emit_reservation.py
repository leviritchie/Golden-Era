#!/usr/bin/env python3
"""Functional-first emit reservation: H3 visit ∪ non-visitable block; omit scenery.

MiniLM-free and import-acyclic: do not import footprint_alignment,
build_homecoming_single_layer_map, approach_cell.surface_emit, or
build_homecoming_entity_substitution_map. Callers and wrappers delegate down only.

Occupancy authority for scenery-omit is HoMM3 visit ∪ non-visitable block only.
Native ObjectConfig GATE rings (e.g. chest/gold) must not reserve cells — those
rings invent walkable markers on cells HoMM3 often hard-blocks with mountains,
and reserving them falsely omits blocking scenery (holes). Interact cells stay
protected because they are already in the H3 visit set when keep-donor aligned.
Native OCC (nodes==1) outside that object's H3 visit∪block is likewise not
reserved.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable

FUNCTIONAL_EMIT_RESERVATION_POLICY = (
    "functional_first_h3_visit_block_scenery_omit_only"
)

# Size-grid reservation retired: GATE rings over-reserve H3-blocked cells.
# Keep helper for diagnostics; empty set means size_grid_nodes_for_instance
# returns nothing for reservation callers.
RESERVED_SIZE_GRID_NODE_VALUES = frozenset()

# Scorched-earth subterranean portal: reserve Olden GATE markers so scenery OCC
# cannot bury approach angles. General GATE rings stay unreserved.
SCORCHED_EARTH_GATE_RESERVE_SIDS = frozenset({
    "homm3_subterranean_gate_portal",
})

# Map infrastructure: never scenery-omit targets and never functional-reserved donors.
INFRASTRUCTURE_SIDS = frozenset({
    "homm3_pathing_blocker",
    "homm3_envelope_padding_blocker",
})


def is_infrastructure_sid(sid: str) -> bool:
    """True for pathing/envelope blockers and pathability visual clone SIDs."""
    if sid in INFRASTRUCTURE_SIDS:
        return True
    return sid.startswith("homm3_pathing_")


FOOTPRINT_PAD_CATEGORIES = frozenset({
    "footprint_alignment_pad",
    "footprint_alignment_global_pad",
    "footprint_alignment_cluster",
})

# Approach-cell / block-parity visible seals (and merged big mountains that reuse
# those ids). Not omit-able scenery: they close HoMM3 hard-block gaps on cells that
# functional reservation still marks for visit-cursor coverage (nodes==0).
BLOCK_PARITY_SEAL_ID_BASE = 891_000
BLOCK_PARITY_SEAL_SIDS = frozenset({
    "mountain_green_small_1",
    "mountain_green_big_1",
    "mountain_green_big_2",
    "mountain_green_big_3",
    "mountain_green_big_4",
})
BLOCK_PARITY_SEAL_CATEGORY = "block_parity_seal"

# Canonical suppressible biome scenery SIDs. Wrappers re-export; do not fork.
SUPPRESSIBLE_SOURCE_SCENERY_SIDS = frozenset({
    "desert_dune_1",
    "desert_dune_2",
    "dirt_rock_1",
    "dirt_rock_2",
    "dirt_rock_3",
    "dirt_rock_4",
    "dirt_stones_1",
    "dirt_strange_flower",
    "dirt_volcanic_rock",
    "crystal_trail",
    "dead_sculls_bones_hill",
    "grass_1",
    "grass_2",
    "grass_snow_1",
    "grass_stones_1",
    "grass_stones_2",
    "log_1",
    "mountain_dead_big_1",
    "mountain_dead_big_2",
    "mountain_dead_big_3",
    "mountain_dead_big_4",
    "mountain_dead_small_1",
    "mountain_dead_small_2",
    "mountain_desert_1",
    "mountain_desert_2",
    "mountain_desert_3",
    "mountain_desert_4",
    "mountain_desert_5",
    "mountain_desert_6",
    "mountain_dirt_big_1",
    "mountain_dirt_big_2",
    "mountain_dirt_big_3",
    "mountain_dirt_big_4",
    "mountain_dirt_small_1",
    "mountain_dirt_small_2",
    "mountain_green_big_1",
    "mountain_green_big_2",
    "mountain_green_big_3",
    "mountain_green_big_4",
    "mountain_green_small_1",
    "mountain_green_small_2",
    "mountain_lava_big_1",
    "mountain_lava_big_2",
    "mountain_lava_big_3",
    "mountain_lava_big_4",
    "mountain_lava_small_1",
    "mountain_lava_small_2",
    "mountain_lava_small_3",
    "mountain_lava_small_4",
    "mountain_snow_big_1",
    "mountain_snow_big_2",
    "mountain_snow_big_3",
    "mountain_snow_big_4",
    "mountain_snow_small_1",
    "mountain_snow_small_2",
    "mountain_water_big_1",
    "mountain_water_big_2",
    "mountain_water_big_3",
    "mountain_water_small_1",
    "mountain_water_small_2",
    "mountain_water_small_3",
    "mushrooms_1",
    "mushrooms_2",
    "mushrooms_3",
    "mushrooms_4",
    "pinetree_1",
    "pinetree_2",
    "pinetree_3",
    "pinetree_4",
    "pinetree_snow_1",
    "pinetree_snow_2",
    "pinetree_snow_3",
    "pinetree_snow_4",
    "pool_big",
    "pool_dead_big_1",
    "pool_dead_small_1",
    "pool_desert_big_1",
    "pool_desert_small_1",
    "pool_dirt_big_1",
    "pool_dirt_small_1",
    "pool_lava_big_1",
    "pool_lava_big_2",
    "pool_lava_small_1",
    "pool_small",
    "pool_snow_big_1",
    "pool_snow_small_1",
    "pool_snow_small_2",
    "rocks_1",
    "rocks_2",
    "snow_grassy_hill_1",
    "snow_rock_hill_1",
    "snow_stones_1",
    "snow_stones_2",
    "tree_dead_1",
    "tree_dead_2",
    "tree_dead_3",
    "tree_dead_4",
    "tree_dirt_1",
    "tree_dirt_2",
    "tree_dirt_3",
    "tree_dirt_4",
    "tree_lava_1",
    "tree_lava_2",
    "tree_lava_3",
    "water_reed_1",
    # AB/SoD biome plates that bury subterranean portal GATE cells.
    "dead_meadow",
    "lava_ground_1",
    "lava_ground_2",
    "lava_ground_3",
    "lava_ground_4",
    "lava_stones_1",
})


def is_suppressible_source_scenery(placement: dict[str, Any]) -> bool:
    entity = placement.get("entity")
    sid = placement.get("replacementSid")
    # Scenery same-size clones (homm3_xfp_s_*) keep payloadless category; treat as
    # suppressible so portal scorched-clear / omit paths can remove them.
    if (
        isinstance(entity, dict)
        and entity.get("category") == "payloadless_object_unclassified_for_current_scope"
        and isinstance(sid, str)
        and sid.startswith("homm3_xfp_s_")
    ):
        return True
    return (
        isinstance(entity, dict)
        and entity.get("category") == "payloadless_object_unclassified_for_current_scope"
        and placement.get("replacementSid") in SUPPRESSIBLE_SOURCE_SCENERY_SIDS
    )


def is_scenery_placement(placement: dict[str, Any]) -> bool:
    """True only for pads/clusters or suppressible biome scenery.

    `payloadless_object_unclassified_for_current_scope` alone is not scenery: that
    category means "no H3M payload," not "safe to absorb." Mapped interactables such
    as stables keep that category and must remain functional keepers.
    """
    entity = placement.get("entity")
    if not isinstance(entity, dict):
        return False
    if str(entity.get("category") or "") in FOOTPRINT_PAD_CATEGORIES:
        return True
    return is_suppressible_source_scenery(placement)


def may_best_anchor_shift(placement: dict[str, Any]) -> bool:
    """Only true biome/pad scenery may relocate; payloadless interactables must not."""
    entity = placement.get("entity") if isinstance(placement.get("entity"), dict) else {}
    category = str(entity.get("category") or "")
    if category in FOOTPRINT_PAD_CATEGORIES:
        return True
    return is_suppressible_source_scenery(placement)


def size_grid_nodes_for_instance(
    config: dict[str, Any],
    anchor_node: int,
    rotation: int,
    *,
    grid_width: int,
    grid_height: int,
    mirrored_rotation: int,
) -> set[int]:
    """ObjectConfig cells whose node value is in RESERVED_SIZE_GRID_NODE_VALUES (GATE only)."""
    return _instance_nodes_with_values(
        config,
        anchor_node,
        rotation,
        values=RESERVED_SIZE_GRID_NODE_VALUES,
        grid_width=grid_width,
        grid_height=grid_height,
        mirrored_rotation=mirrored_rotation,
    )


def _instance_nodes_with_values(
    config: dict[str, Any],
    anchor_node: int,
    rotation: int,
    *,
    values: frozenset[int] | set[int],
    grid_width: int,
    grid_height: int,
    mirrored_rotation: int,
) -> set[int]:
    """ObjectConfig cells whose node value is in ``values``."""
    if not values:
        return set()
    size_x = config.get("sizeX")
    size_z = config.get("sizeZ")
    if not isinstance(size_x, int) or not isinstance(size_z, int) or size_x <= 0 or size_z <= 0:
        generator_config = config.get("generatorConfig")
        if isinstance(generator_config, dict) and isinstance(generator_config.get("buildingSizeX"), int) and isinstance(generator_config.get("buildingSizeZ"), int):
            size_x = int(generator_config["buildingSizeX"])
            size_z = int(generator_config["buildingSizeZ"])
        else:
            return set()
    nodes = config.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != size_x * size_z:
        return set()
    mirrored = rotation == mirrored_rotation and config.get("canBeMirrored") is True
    anchor_x = anchor_node % grid_width
    anchor_y = anchor_node // grid_width
    matched: set[int] = set()
    for config_z in range(size_z):
        for config_x in range(size_x):
            value = nodes[config_z * size_x + config_x]
            if value not in values:
                continue
            placed_dx = size_x - 1 - config_x if mirrored else config_x
            grid_x = anchor_x + placed_dx
            grid_y = anchor_y + (size_z - 1 - config_z)
            if 0 <= grid_x < grid_width and 0 <= grid_y < grid_height:
                matched.add(grid_y * grid_width + grid_x)
    return matched


def functional_reserved_nodes_for_placements(
    placements: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    grid_width: int,
    grid_height: int,
    mirrored_rotation: int,
    entity_visit_nodes_fn: Callable[[dict[str, Any]], set[int]],
    entity_block_nodes_fn: Callable[[dict[str, Any]], set[int]],
    skip_sid_fn: Callable[[str], bool] | None = None,
) -> set[int]:
    """Reserve HoMM3 visit ∪ non-visitable block for functionals.

    Olden GATE markers are not reserved in general — GATE rings invent markers on
    H3-blocked cells and would omit true scenery. Scorched-earth subterranean
    portal is the explicit exception: all of its GATE markers must stay clear.
    """
    reserved: set[int] = set()
    for placement in placements:
        sid = str(placement.get("replacementSid") or "")
        if skip_sid_fn is not None and skip_sid_fn(sid):
            continue
        if is_infrastructure_sid(sid):
            continue
        if is_scenery_placement(placement):
            continue
        entity = placement.get("entity")
        if isinstance(entity, dict):
            reserved |= entity_visit_nodes_fn(entity)
            reserved |= entity_block_nodes_fn(entity)
        if sid in SCORCHED_EARTH_GATE_RESERVE_SIDS:
            config = native_object_configs.get(sid)
            anchor = placement.get("node")
            rotation = placement.get("rotation")
            if isinstance(config, dict) and isinstance(anchor, int) and isinstance(rotation, int):
                reserved |= _instance_nodes_with_values(
                    config,
                    anchor,
                    rotation,
                    values=frozenset({2}),
                    grid_width=grid_width,
                    grid_height=grid_height,
                    mirrored_rotation=mirrored_rotation,
                )
    return reserved


def apply_functional_first_scenery_omit(
    placements: list[dict[str, Any]],
    *,
    reserved_nodes: set[int],
    occupied_nodes_for_placement: Callable[[dict[str, Any]], set[int]],
) -> dict[str, Any]:
    """Omit scenery whose occupied footprint intersects reserved functional cells.

    Mutates `placements` in place. Functional placements are never removed.
    """
    kept: list[dict[str, Any]] = []
    omitted_counts = Counter()
    omitted_examples: list[dict[str, Any]] = []
    omitted_source_ids: list[int] = []
    functional_count = 0
    scenery_kept_count = 0
    for placement in placements:
        sid = str(placement.get("replacementSid") or "")
        if is_infrastructure_sid(sid):
            kept.append(placement)
            continue
        if not is_scenery_placement(placement):
            kept.append(placement)
            functional_count += 1
            continue
        occupied = occupied_nodes_for_placement(placement)
        overlap = occupied & reserved_nodes
        if overlap:
            omitted_counts[sid] += 1
            oid = placement.get("id")
            if isinstance(oid, int):
                omitted_source_ids.append(oid)
            if len(omitted_examples) < 20:
                entity = placement.get("entity") if isinstance(placement.get("entity"), dict) else {}
                omitted_examples.append({
                    "sourceKey": entity.get("sourceKey"),
                    "sourceIndex": oid if isinstance(oid, int) else None,
                    "replacementSid": sid,
                    "node": placement.get("node"),
                    "overlapNodeCount": len(overlap),
                    "overlapNodesSample": sorted(overlap)[:8],
                    "reason": "occupied_intersects_functional_reserved",
                })
            continue
        kept.append(placement)
        scenery_kept_count += 1
    placements[:] = kept
    return {
        "policy": FUNCTIONAL_EMIT_RESERVATION_POLICY,
        "functionalPlacementCount": functional_count,
        "sceneryKeptCount": scenery_kept_count,
        "sceneryOmittedCount": int(sum(omitted_counts.values())),
        "sceneryOmittedSidHistogram": dict(omitted_counts.most_common()),
        "sceneryOmittedSourceIds": omitted_source_ids,
        "reservedNodeCount": len(reserved_nodes),
        "omittedExamples": omitted_examples,
    }


def apply_functional_first_emit_reservation(
    placements: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    grid_width: int,
    grid_height: int,
    mirrored_rotation: int,
    entity_visit_nodes_fn: Callable[[dict[str, Any]], set[int]],
    entity_block_nodes_fn: Callable[[dict[str, Any]], set[int]],
    occupied_nodes_for_placement: Callable[[dict[str, Any]], set[int]],
    skip_sid_fn: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Functional-first reservation: compute reserved set, omit intersecting scenery."""
    reserved = functional_reserved_nodes_for_placements(
        placements,
        native_object_configs,
        grid_width=grid_width,
        grid_height=grid_height,
        mirrored_rotation=mirrored_rotation,
        entity_visit_nodes_fn=entity_visit_nodes_fn,
        entity_block_nodes_fn=entity_block_nodes_fn,
        skip_sid_fn=skip_sid_fn,
    )
    stats = apply_functional_first_scenery_omit(
        placements,
        reserved_nodes=reserved,
        occupied_nodes_for_placement=occupied_nodes_for_placement,
    )
    stats["reservedNodes"] = reserved
    return stats


def placements_from_map_objects(
    objects: list[dict[str, Any]],
    entities_by_source_index: dict[int, dict[str, Any]],
    *,
    footprint_pad_id_base: int = 890_000,
) -> list[dict[str, Any]]:
    """Rebuild placement-shaped rows from MapData objects + alignment entities."""
    placements: list[dict[str, Any]] = []
    for group in objects:
        if not isinstance(group, dict):
            continue
        sid = group.get("sid")
        ids = group.get("ids")
        nodes = group.get("nodes")
        rotations = group.get("rotations")
        if not isinstance(sid, str) or not isinstance(ids, list) or not isinstance(nodes, list) or not isinstance(rotations, list):
            continue
        if not (len(ids) == len(nodes) == len(rotations)):
            continue
        for index, object_id in enumerate(ids):
            if not isinstance(object_id, int):
                continue
            entity = entities_by_source_index.get(object_id)
            if is_infrastructure_sid(sid):
                entity = {
                    "sourceKey": f"infrastructure:{object_id}",
                    "category": "emit_reservation_infrastructure",
                    "payloadKind": "explicit_no_payload",
                }
            elif object_id >= BLOCK_PARITY_SEAL_ID_BASE and sid in BLOCK_PARITY_SEAL_SIDS:
                entity = {
                    "sourceKey": f"block_parity_seal:{object_id}",
                    "category": BLOCK_PARITY_SEAL_CATEGORY,
                    "payloadKind": "explicit_no_payload",
                }
            elif entity is None and object_id >= footprint_pad_id_base:
                entity = {
                    "sourceKey": f"synthetic_pad:{object_id}",
                    "category": "footprint_alignment_pad",
                    "payloadKind": "explicit_no_payload",
                }
            if entity is None:
                # Pathing visuals / unknown synthetics: treat as non-scenery for omit
                # classification only when SID is suppressible without entity — skip.
                if sid in SUPPRESSIBLE_SOURCE_SCENERY_SIDS:
                    entity = {
                        "sourceKey": f"orphan_scenery:{object_id}",
                        "category": "payloadless_object_unclassified_for_current_scope",
                        "payloadKind": "explicit_no_payload",
                    }
                else:
                    entity = {
                        "sourceKey": f"orphan_functional:{object_id}",
                        "category": "payloadless_object_unclassified_for_current_scope",
                        "payloadKind": "explicit_no_payload",
                    }
            placements.append({
                "replacementSid": sid,
                "id": object_id,
                "entity": entity,
                "node": int(nodes[index]),
                "rotation": int(rotations[index] or 0),
            })
    return placements


def validate_scenery_occupied_disjoint_from_functional_reserved(
    placements: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    grid_width: int,
    grid_height: int,
    mirrored_rotation: int,
    entity_visit_nodes_fn: Callable[[dict[str, Any]], set[int]],
    entity_block_nodes_fn: Callable[[dict[str, Any]], set[int]],
    occupied_nodes_for_placement: Callable[[dict[str, Any]], set[int]],
    skip_sid_fn: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Fail-closed check: scenery nodes==1 must not intersect functional reserved cells."""
    reserved = functional_reserved_nodes_for_placements(
        placements,
        native_object_configs,
        grid_width=grid_width,
        grid_height=grid_height,
        mirrored_rotation=mirrored_rotation,
        entity_visit_nodes_fn=entity_visit_nodes_fn,
        entity_block_nodes_fn=entity_block_nodes_fn,
        skip_sid_fn=skip_sid_fn,
    )
    violations: list[dict[str, Any]] = []
    for placement in placements:
        sid = str(placement.get("replacementSid") or "")
        if skip_sid_fn is not None and skip_sid_fn(sid):
            continue
        if is_infrastructure_sid(sid):
            continue
        if not is_scenery_placement(placement):
            continue
        occupied = occupied_nodes_for_placement(placement)
        overlap = occupied & reserved
        if not overlap:
            continue
        entity = placement.get("entity") if isinstance(placement.get("entity"), dict) else {}
        violations.append({
            "sourceKey": entity.get("sourceKey"),
            "objectId": placement.get("id"),
            "replacementSid": placement.get("replacementSid"),
            "node": placement.get("node"),
            "overlapNodeCount": len(overlap),
            "overlapNodesSample": sorted(overlap)[:8],
        })
    return {
        "policy": FUNCTIONAL_EMIT_RESERVATION_POLICY,
        "ok": len(violations) == 0,
        "reservedNodeCount": len(reserved),
        "violationCount": len(violations),
        "violations": violations[:20],
    }
