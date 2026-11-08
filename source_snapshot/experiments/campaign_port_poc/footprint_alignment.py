#!/usr/bin/env python3
"""Align Olden object footprints to HoMM3 template masks via shift, absorb, and scenery pad."""

from __future__ import annotations

from collections import Counter
from typing import Any, TYPE_CHECKING

import build_homecoming_entity_substitution_map as sub
import functional_emit_reservation

if TYPE_CHECKING:
    import build_homecoming_single_layer_map as single


def _single():
    import build_homecoming_single_layer_map as single_mod

    return single_mod

FOOTPRINT_ALIGNMENT_POLICY = (
    "h3_mask_pad_absorb_true_scenery_no_functional_shift_no_stack_visit_gate_only"
)
FOOTPRINT_PAD_ID_BASE = 890_000
MAX_ANCHOR_SHIFT_RADIUS = 4


def access_protected_nodes_for_placement(
    placement: dict[str, Any],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    grid_width: int,
) -> set[int]:
    """Visit and GATE cells that must stay pad-free for access.

    No approach halo: scenery mask walls refill around interactables. Land-on
    ObjectConfig clones put GATE on the HoMM3 visit cell so pathing reaches it.
    """
    del grid_width  # reserved for callers; halo abandoned
    single = _single()
    if is_scenery_placement(placement):
        return set()
    entity = placement.get("entity")
    if not isinstance(entity, dict):
        return set()
    sid = str(placement.get("replacementSid") or "")
    if sid == single.HOMM3_PATHING_BLOCKER_SID or single.is_homm3_pathing_visual_sid(sid):
        return set()
    config = native_object_configs.get(sid)
    if not isinstance(config, dict):
        return set()
    rotation = int(placement.get("rotation") or 0)
    anchor_node = placement.get("node")
    if not isinstance(anchor_node, int):
        return set()
    visit = single.entity_visit_nodes(entity)
    gate = single.nodes_for_object_instance_with_value(
        sid,
        config,
        anchor_node,
        rotation,
        node_value=2,
    )
    return visit | gate


def access_protected_nodes_for_placements(
    placements: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    grid_width: int,
) -> set[int]:
    protected: set[int] = set()
    for placement in placements:
        protected |= access_protected_nodes_for_placement(
            placement,
            native_object_configs,
            grid_width=grid_width,
        )
    return protected


def blocked_nodes_for_placements(
    placements: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    exclude_ids: set[int] | None = None,
) -> set[int]:
    """Union of ObjectConfig nodes==1 cells across current placements."""
    single = _single()
    blocked: set[int] = set()
    skip_ids = exclude_ids or set()
    for placement in placements:
        placement_id = placement.get("id")
        if isinstance(placement_id, int) and placement_id in skip_ids:
            continue
        sid = str(placement.get("replacementSid") or "")
        if sid == single.HOMM3_PATHING_BLOCKER_SID or single.is_homm3_pathing_visual_sid(sid):
            continue
        blocked |= occupied_for_placement(placement, native_object_configs)
    return blocked


FOOTPRINT_PAD_CATEGORIES = functional_emit_reservation.FOOTPRINT_PAD_CATEGORIES


def is_scenery_placement(placement: dict[str, Any]) -> bool:
    """True only for pads/clusters or suppressible biome scenery.

    Delegates to functional_emit_reservation (canonical MiniLM-free definition).
    """
    return functional_emit_reservation.is_scenery_placement(placement)


def may_best_anchor_shift(placement: dict[str, Any]) -> bool:
    """Only true biome/pad scenery may relocate; payloadless interactables must not."""
    return functional_emit_reservation.may_best_anchor_shift(placement)


def functional_reserved_nodes_for_current_placements(
    placements: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    grid_width: int,
) -> set[int]:
    """H3 visit∪block for functional placements (pad refusal)."""
    single = _single()
    return functional_emit_reservation.functional_reserved_nodes_for_placements(
        placements,
        native_object_configs,
        grid_width=grid_width,
        grid_height=single.OLDEN_HEIGHT,
        mirrored_rotation=single.OLDEN_MIRRORED_ROTATION,
        entity_visit_nodes_fn=single.entity_visit_nodes,
        entity_block_nodes_fn=single.entity_nonvisitable_block_nodes,
        skip_sid_fn=lambda sid: sid == single.HOMM3_PATHING_BLOCKER_SID or single.is_homm3_pathing_visual_sid(sid),
    )


def is_single_cell_blocker_sid(sid: str, config: dict[str, Any]) -> bool:
    """True when ObjectConfig occupies exactly one nodes==1 cell at rotation 0."""
    single = _single()
    occupied = single.occupied_nodes_for_object_instance(sid, config, 0, 0)
    return len(occupied) == 1


def terrain_context_for_entity(entity: dict[str, Any], surface_map_data: dict[str, Any] | None) -> dict[str, Any]:
    single = _single()
    source_x = entity.get("sourceX")
    source_y = entity.get("sourceY")
    if not isinstance(source_x, int) or not isinstance(source_y, int) or surface_map_data is None:
        return {"biome": "grass", "dominantBiome": "grass", "h3TerrainId": None}
    if surface_map_data.get("sizeX_") != single.SOURCE_WIDTH or surface_map_data.get("sizeZ_") != single.SOURCE_HEIGHT:
        return {"biome": "grass", "dominantBiome": "grass", "h3TerrainId": None}
    raw_node = source_y * single.SOURCE_WIDTH + source_x
    terrain_id = surface_map_data["tilesMap"][raw_node]
    biome = sub.H3_TERRAIN_BIOME.get(int(terrain_id), "grass")
    return {
        "biome": biome,
        "dominantBiome": biome,
        "h3TerrainId": int(terrain_id),
        "sourceX": source_x,
        "sourceY": source_y,
    }


def choose_pad_scenery_sid(
    entity: dict[str, Any],
    valid_ids: set[str],
    surface_map_data: dict[str, Any] | None,
    *,
    node: int | None = None,
    footprint_cells: int = 1,
    native_object_configs: dict[str, dict[str, Any]] | None = None,
) -> str:
    terrain_context = terrain_context_for_entity(entity, surface_map_data)
    role = sub.terrain_role_for_row(entity)
    seed_key = str(entity.get("sourceKey") or "pad")
    pad_node = int(node if node is not None else 0)
    configs = native_object_configs or {}

    def accept(candidate: str | None) -> str | None:
        if not candidate or candidate not in valid_ids:
            return None
        config = configs.get(candidate)
        if not isinstance(config, dict):
            # Without config evidence, only allow known 1-cell mountain/stone/tree SIDs.
            if footprint_cells == 1 and any(
                candidate.startswith(prefix)
                for prefix in ("mountain_", "pinetree_", "tree_", "grass_", "snow_stones_", "flowers_", "mushrooms_")
            ) and "big" not in candidate and "pool" not in candidate:
                return candidate
            return None
        if footprint_cells == 1 and not is_single_cell_blocker_sid(candidate, config):
            return None
        return candidate

    # Per-node pads are 1x1; pools are 2x2/3x3 and must not be chosen for single-cell gaps.
    pad_role = role
    if role in {"pool", "pool_big"} and footprint_cells < 4:
        pad_role = "rock"
    if pad_role is not None:
        replacement, _rule, _evidence = sub.choose_terrain_biome_replacement(
            pad_role,
            valid_ids,
            terrain_context,
            footprint_cells=footprint_cells,
            seed_key=seed_key,
            node=pad_node,
        )
        accepted = accept(replacement)
        if accepted:
            return accepted
    animation = str(entity.get("templateAnimation") or "")
    template_id = entity.get("templateObjectId")
    replacement, _rule = sub.choose_biome_decoration(template_id, animation, valid_ids)
    accepted = accept(replacement)
    if accepted:
        return accepted
    replacement, _rule = sub.choose_decoration(animation, valid_ids)
    accepted = accept(replacement)
    if accepted:
        return accepted
    biome = str(terrain_context.get("biome") or "grass")
    # Prefer proven 1-cell blockers for single-cell pads; never emit 2x2 dunes/rocks as pads.
    one_cell_fallbacks = [
        (sub.BIOME_ROLE_REPLACEMENTS.get("mountain") or {}).get(biome),
        "mountain_green_small_1" if biome == "grass" else None,
        "mountain_snow_small_1" if biome == "snow" else None,
        "mountain_dirt_small_1" if biome in {"dirt", "desert"} else None,
        "grass_stones_1",
        "snow_stones_1",
        "mountain_green_small_2",
    ]
    for candidate in one_cell_fallbacks:
        accepted = accept(candidate)
        if accepted:
            return accepted
    raise ValueError(
        f"no single-cell footprint pad SID available for biome={biome} role={pad_role} node={pad_node}"
    )


def occupied_for_placement(placement: dict[str, Any], native_object_configs: dict[str, dict[str, Any]]) -> set[int]:
    single = _single()
    sid = str(placement["replacementSid"])
    config = native_object_configs.get(sid)
    if not isinstance(config, dict):
        raise ValueError(f"missing native object config for footprint alignment SID {sid}")
    return single.occupied_nodes_for_object_instance(
        sid,
        config,
        int(placement["node"]),
        int(placement["rotation"]),
    )


def placement_priority(placement: dict[str, Any]) -> int:
    single = _single()
    if is_scenery_placement(placement):
        return 100
    entity = placement.get("entity") if isinstance(placement.get("entity"), dict) else {}
    category = str(entity.get("category") or "")
    return single.SOURCE_ANCHOR_PRIORITY_BY_CATEGORY.get(category, 500)


def remove_placement_ids(placements: list[dict[str, Any]], remove_ids: set[int]) -> int:
    if not remove_ids:
        return 0
    before = len(placements)
    placements[:] = [placement for placement in placements if int(placement.get("id") or -1) not in remove_ids]
    return before - len(placements)


def best_anchor_node_for_mask(
    *,
    sid: str,
    config: dict[str, Any],
    rotation: int,
    anchor_node: int,
    required_nodes: set[int],
    grid_width: int,
    max_radius: int = MAX_ANCHOR_SHIFT_RADIUS,
) -> tuple[int, set[int], tuple[int, int]]:
    single = _single()
    def score(occupied: set[int]) -> tuple[int, int, int]:
        extraneous = len(occupied - required_nodes)
        missing = len(required_nodes - occupied)
        return (extraneous, missing, len(occupied))

    current = single.occupied_nodes_for_object_instance(sid, config, anchor_node, rotation)
    best_node = anchor_node
    best_occupied = current
    best_score = score(current)
    best_delta = (0, 0)
    for dy in range(-max_radius, max_radius + 1):
        for dx in range(-max_radius, max_radius + 1):
            candidate_node = anchor_node + dx + dy * grid_width
            if candidate_node < 0:
                continue
            occupied = single.occupied_nodes_for_object_instance(sid, config, candidate_node, rotation)
            candidate_score = score(occupied)
            if candidate_score < best_score:
                best_score = candidate_score
                best_node = candidate_node
                best_occupied = occupied
                best_delta = (dx, dy)
    return best_node, best_occupied, best_delta


def scenery_ids_absorbed_by_shift(
    placements: list[dict[str, Any]],
    *,
    mover_id: int,
    new_occupied: set[int],
    native_object_configs: dict[str, dict[str, Any]],
) -> set[int]:
    absorbed: set[int] = set()
    for placement in placements:
        placement_id = placement.get("id")
        if not isinstance(placement_id, int) or placement_id == mover_id:
            continue
        if not is_scenery_placement(placement):
            continue
        scenery_nodes = occupied_for_placement(placement, native_object_configs)
        if scenery_nodes & new_occupied:
            absorbed.add(placement_id)
    return absorbed


def apply_footprint_alignment_to_placements(
    placements: list[dict[str, Any]],
    *,
    native_object_configs: dict[str, dict[str, Any]],
    valid_ids: set[str],
    surface_map_data: dict[str, Any] | None,
    grid_width: int,
    synthetic_id_base: int | None = None,
) -> dict[str, Any]:
    single = _single()
    shift_counts = Counter()
    absorbed_counts = Counter()
    shift_examples: list[dict[str, Any]] = []
    pad_counts = Counter()
    pad_examples: list[dict[str, Any]] = []
    skipped_pad_counts = Counter()
    skipped_pad_examples: list[dict[str, Any]] = []
    skipped_functional_shift_counts = Counter()
    skipped_functional_shift_examples: list[dict[str, Any]] = []
    next_pad_id = FOOTPRINT_PAD_ID_BASE if synthetic_id_base is None else synthetic_id_base
    removed_scenery_ids: set[int] = set()

    functional = [placement for placement in placements if not is_scenery_placement(placement)]
    scenery = [placement for placement in placements if is_scenery_placement(placement)]
    processing_order = sorted(functional, key=placement_priority, reverse=True) + scenery
    # Precompute once: functional size-grid (incl. nodes==0) ∪ visit. Stable across
    # scenery absorb/shift; pads must refuse these cells.
    functional_reserved = functional_reserved_nodes_for_current_placements(
        placements,
        native_object_configs,
        grid_width=grid_width,
    )

    active_ids = {
        int(placement["id"])
        for placement in placements
        if isinstance(placement.get("id"), int)
    }
    for placement in processing_order:
        placement_id = placement.get("id")
        entity = placement.get("entity")
        if not isinstance(placement_id, int) or not isinstance(entity, dict):
            continue
        if placement_id not in active_ids:
            # Absorbed earlier in this pass; do not emit pads for removed scenery.
            continue
        required_nodes = single.entity_nonvisitable_block_nodes(entity)
        if not required_nodes:
            continue
        sid = str(placement["replacementSid"])
        if sid == single.HOMM3_PATHING_BLOCKER_SID or single.is_homm3_pathing_visual_sid(sid):
            continue
        config = native_object_configs.get(sid)
        if not isinstance(config, dict):
            raise ValueError(f"missing native object config for footprint alignment: {sid}")
        rotation = int(placement["rotation"])
        anchor_node = int(placement["node"])
        occupied = single.occupied_nodes_for_object_instance(sid, config, anchor_node, rotation)
        extraneous = occupied - required_nodes
        # Best-anchor search may relocate objects and break visit/guard adjacency.
        # Only suppressible biome/pad scenery may shift. Functional and payloadless
        # interactables stay on their source-derived emit node.
        if extraneous and may_best_anchor_shift(placement):
            best_node, best_occupied, delta = best_anchor_node_for_mask(
                sid=sid,
                config=config,
                rotation=rotation,
                anchor_node=anchor_node,
                required_nodes=required_nodes,
                grid_width=grid_width,
            )
            if best_node != anchor_node and (best_occupied & functional_reserved):
                # Do not shift scenery onto functional size-grid / visit cells.
                best_node = anchor_node
                best_occupied = occupied
                delta = (0, 0)
            if best_node != anchor_node:
                absorbed = scenery_ids_absorbed_by_shift(
                    placements,
                    mover_id=placement_id,
                    new_occupied=best_occupied,
                    native_object_configs=native_object_configs,
                )
                if absorbed:
                    removed = remove_placement_ids(placements, absorbed)
                    removed_scenery_ids |= absorbed
                    active_ids -= absorbed
                    absorbed_counts["scenery_absorbed_by_shift"] += removed
                placement["node"] = best_node
                placement["footprintShift"] = {
                    "dx": delta[0],
                    "dy": delta[1],
                    "previousNode": anchor_node,
                    "extraneousBefore": len(extraneous),
                    "extraneousAfter": len(best_occupied - required_nodes),
                }
                shift_counts[sid] += 1
                if len(shift_examples) < 20:
                    shift_examples.append({
                        "sourceIndex": placement_id,
                        "sourceKey": entity.get("sourceKey"),
                        "replacementSid": sid,
                        **placement["footprintShift"],
                    })
                occupied = best_occupied
        elif extraneous:
            skipped_functional_shift_counts[sid] += 1
            if len(skipped_functional_shift_examples) < 20:
                skipped_functional_shift_examples.append({
                    "node": anchor_node,
                    "sourceIndex": placement_id,
                    "sourceKey": entity.get("sourceKey"),
                    "reason": "non_scenery_best_anchor_shift_disabled",
                    "extraneousCount": len(extraneous),
                    "replacementSid": sid,
                })

        # Absorb suppressible scenery already intersecting this footprint so pads
        # are not stacked on top of source scenery that already blocks the cell.
        if not is_scenery_placement(placement):
            absorbed = scenery_ids_absorbed_by_shift(
                placements,
                mover_id=placement_id,
                new_occupied=occupied,
                native_object_configs=native_object_configs,
            )
            if absorbed:
                removed = remove_placement_ids(placements, absorbed)
                removed_scenery_ids |= absorbed
                active_ids -= absorbed
                absorbed_counts["scenery_absorbed_by_footprint_intersect"] += removed

        global_blocked = blocked_nodes_for_placements(
            placements,
            native_object_configs,
            exclude_ids={placement_id},
        )
        # Keep visit/GATE/approach open for this placement and every other
        # functional object already on the map. Pads must not wall town fronts.
        access_protected = access_protected_nodes_for_placements(
            placements,
            native_object_configs,
            grid_width=grid_width,
        )
        # Full functional size-grid (including nodes==0) plus visit — pads must not
        # bury interactable visual corners that still route to GATE at runtime.
        missing = sorted(required_nodes - occupied)
        for node in missing:
            if node in global_blocked:
                skipped_pad_counts["already_blocked"] += 1
                if len(skipped_pad_examples) < 20:
                    skipped_pad_examples.append({
                        "node": node,
                        "forSourceIndex": placement_id,
                        "forSourceKey": entity.get("sourceKey"),
                        "reason": "olden_cell_already_blocked",
                    })
                continue
            if node in access_protected:
                skipped_pad_counts["access_lane_protected"] += 1
                if len(skipped_pad_examples) < 20:
                    skipped_pad_examples.append({
                        "node": node,
                        "forSourceIndex": placement_id,
                        "forSourceKey": entity.get("sourceKey"),
                        "reason": "visit_gate_or_approach_access_lane",
                    })
                continue
            if node in functional_reserved:
                skipped_pad_counts["functional_reserved"] += 1
                if len(skipped_pad_examples) < 20:
                    skipped_pad_examples.append({
                        "node": node,
                        "forSourceIndex": placement_id,
                        "forSourceKey": entity.get("sourceKey"),
                        "reason": "functional_reserved_size_grid_or_visit",
                    })
                continue
            pad_sid = choose_pad_scenery_sid(
                entity,
                valid_ids,
                surface_map_data,
                node=node,
                footprint_cells=1,
                native_object_configs=native_object_configs,
            )
            if pad_sid not in native_object_configs:
                raise ValueError(f"missing native object config for pad scenery {pad_sid}")
            if not is_single_cell_blocker_sid(pad_sid, native_object_configs[pad_sid]):
                raise ValueError(f"footprint pad SID must occupy exactly one cell: {pad_sid}")
            placements.append({
                "replacementSid": pad_sid,
                "id": next_pad_id,
                "entity": {
                    "sourceKey": f"footprint_pad:{entity.get('sourceKey')}:{node}",
                    "category": "footprint_alignment_pad",
                    "payloadKind": "explicit_no_payload",
                    "templateObjectId": entity.get("templateObjectId"),
                    "templateAnimation": entity.get("templateAnimation"),
                },
                "ruleName": "footprint_pad_biome_scenery",
                "lossiness": "footprint_alignment",
                "node": node,
                "rotation": 0,
                "level": float(entity.get("level") or 0),
                "footprintPad": {
                    "forSourceIndex": placement_id,
                    "forSourceKey": entity.get("sourceKey"),
                    "node": node,
                },
            })
            active_ids.add(next_pad_id)
            global_blocked.add(node)
            pad_counts[pad_sid] += 1
            next_pad_id += 1
            if len(pad_examples) < 20:
                pad_examples.append({
                    "padId": next_pad_id - 1,
                    "padSid": pad_sid,
                    "node": node,
                    "forSourceIndex": placement_id,
                    "forSourceKey": entity.get("sourceKey"),
                })

    return {
        "status": single.HOMM3_PATHABILITY_ALIGNMENT_STATUS,
        "policy": FOOTPRINT_ALIGNMENT_POLICY,
        "phase": "footprint_shift_absorb_and_per_entity_pad",
        "shiftedPlacementCount": sum(shift_counts.values()),
        "shiftedReplacementSidHistogram": dict(shift_counts.most_common()),
        "absorbedSceneryPlacementCount": len(removed_scenery_ids),
        "absorbedSceneryHistogram": dict(absorbed_counts.most_common()),
        "perEntityPadPlacementCount": sum(pad_counts.values()),
        "perEntityPadSidHistogram": dict(pad_counts.most_common()),
        "skippedPadPlacementCount": sum(skipped_pad_counts.values()),
        "skippedPadReasonHistogram": dict(skipped_pad_counts.most_common()),
        "skippedPadExamples": skipped_pad_examples,
        "skippedFunctionalShiftCount": sum(skipped_functional_shift_counts.values()),
        "skippedFunctionalShiftSidHistogram": dict(skipped_functional_shift_counts.most_common()),
        "skippedFunctionalShiftExamples": skipped_functional_shift_examples,
        "shiftExamples": shift_examples,
        "padExamples": pad_examples,
        "proofBoundary": "source/static generated footprint alignment; runtime exactness remains user-unvalidated",
    }



def promote_cluster_scenery_placements(
    placements: list[dict[str, Any]],
    *,
    native_object_configs: dict[str, dict[str, Any]],
    valid_ids: set[str],
    surface_map_data: dict[str, Any] | None,
    grid_width: int,
    next_id: int,
) -> dict[str, Any]:
    """Replace contiguous 1-cell pad clusters with larger mountain/pool objects when they fit."""
    single = _single()
    pad_indices = [
        i
        for i, p in enumerate(placements)
        if isinstance(p.get("entity"), dict)
        and p["entity"].get("category") in {"footprint_alignment_pad", "footprint_alignment_global_pad"}
    ]
    if not pad_indices:
        return {"promotedClusterCount": 0, "removedPadCount": 0, "promotedSidHistogram": {}, "nextId": next_id}

    node_to_idx = {int(placements[i]["node"]): i for i in pad_indices}
    remaining = set(node_to_idx)
    components: list[list[int]] = []
    while remaining:
        start = min(remaining)
        stack = [start]
        remaining.remove(start)
        comp: list[int] = []
        while stack:
            node = stack.pop()
            comp.append(node)
            x = node % grid_width
            y = node // grid_width
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if nx < 0 or ny < 0:
                    continue
                nnode = ny * grid_width + nx
                if nnode in remaining:
                    remaining.remove(nnode)
                    stack.append(nnode)
        components.append(sorted(comp))

    promoted = Counter()
    skipped_promote = Counter()
    remove_ids: set[int] = set()
    new_placements: list[dict[str, Any]] = []
    for comp in components:
        if len(comp) < 4:
            continue
        seed_placement = placements[node_to_idx[comp[0]]]
        entity = seed_placement.get("entity") if isinstance(seed_placement.get("entity"), dict) else {}
        for_source = (seed_placement.get("footprintPad") or {}).get("forSourceKey") or entity.get("sourceKey")
        pad_sid = str(seed_placement.get("replacementSid") or "")
        if pad_sid.startswith("pinetree_") or pad_sid.startswith("tree_"):
            continue
        if pad_sid.startswith("pool_"):
            role = "pool"
        else:
            role = "mountain"
        # Infer biome from the already-chosen pad SID. Pad nodes are Olden-grid
        # coordinates and must not be treated as HoMM3 source terrain indices.
        biome = "grass"
        for token, mapped in (
            ("snow", "snow"),
            ("dirt", "dirt"),
            ("desert", "desert"),
            ("dead", "dead"),
            ("lava", "lava"),
            ("water", "water"),
            ("green", "grass"),
        ):
            if token in pad_sid:
                biome = mapped
                break
        pad_ids_in_comp = {
            int(placements[node_to_idx[n]]["id"])
            for n in comp
            if n in node_to_idx and isinstance(placements[node_to_idx[n]].get("id"), int)
        }
        foreign_blocked = blocked_nodes_for_placements(
            placements,
            native_object_configs,
            exclude_ids=pad_ids_in_comp,
        )
        promoted_here = False
        for cells in (9, 4):
            if len(comp) < cells:
                continue
            lookup_role = "pool_big" if role == "pool" and cells == 9 else role
            candidates = sub.scenery_variant_candidates(lookup_role, biome, cells, valid_ids)
            if not candidates:
                continue
            for cand in candidates:
                config = native_object_configs.get(cand)
                if not isinstance(config, dict):
                    continue
                for anchor in comp:
                    occupied = single.occupied_nodes_for_object_instance(cand, config, anchor, 0)
                    if not occupied or (occupied - set(comp)):
                        continue
                    if occupied & foreign_blocked:
                        skipped_promote["foreign_blocked"] += 1
                        continue
                    sid = (
                        sub.choose_scenery_variant(
                            lookup_role,
                            biome,
                            cells,
                            valid_ids,
                            seed_key=str(for_source),
                            node=anchor,
                        )
                        or cand
                    )
                    config2 = native_object_configs.get(sid) or config
                    occupied = single.occupied_nodes_for_object_instance(sid, config2, anchor, 0)
                    if occupied - set(comp):
                        continue
                    if occupied & foreign_blocked:
                        skipped_promote["foreign_blocked"] += 1
                        continue
                    new_placements.append(
                        {
                            "replacementSid": sid,
                            "id": next_id,
                            "entity": {
                                "sourceKey": f"footprint_cluster_promote:{for_source}:{anchor}",
                                "category": "footprint_alignment_cluster",
                                "payloadKind": "explicit_no_payload",
                                "templateObjectId": entity.get("templateObjectId"),
                                "templateAnimation": entity.get("templateAnimation"),
                            },
                            "ruleName": "footprint_cluster_promote_biome_scenery",
                            "lossiness": "footprint_alignment",
                            "node": anchor,
                            "rotation": 0,
                            "level": 0.0,
                            "footprintClusterPromote": {
                                "cells": cells,
                                "coveredNodes": sorted(occupied),
                                "forSourceKey": for_source,
                            },
                        }
                    )
                    next_id += 1
                    promoted[sid] += 1
                    for n in occupied:
                        idx = node_to_idx.get(n)
                        if idx is not None:
                            remove_ids.add(int(placements[idx]["id"]))
                    promoted_here = True
                    break
                if promoted_here:
                    break
            if promoted_here:
                break

    if remove_ids:
        remove_placement_ids(placements, remove_ids)
    placements.extend(new_placements)
    return {
        "promotedClusterCount": sum(promoted.values()),
        "removedPadCount": len(remove_ids),
        "promotedSidHistogram": dict(promoted.most_common()),
        "skippedPromoteReasonHistogram": dict(skipped_promote.most_common()),
        "nextId": next_id,
    }


def compute_occupied_overlap_report(
    placements: list[dict[str, Any]],
    *,
    native_object_configs: dict[str, dict[str, Any]],
    max_examples: int = 20,
) -> dict[str, Any]:
    """Count Olden cells where two or more placements contribute nodes==1 blocking."""
    single = _single()
    node_to_entries: dict[int, list[tuple[int, str]]] = {}
    for placement in placements:
        placement_id = placement.get("id")
        if not isinstance(placement_id, int):
            continue
        sid = str(placement.get("replacementSid") or "")
        if sid == single.HOMM3_PATHING_BLOCKER_SID or single.is_homm3_pathing_visual_sid(sid):
            continue
        for node in occupied_for_placement(placement, native_object_configs):
            node_to_entries.setdefault(node, []).append((placement_id, sid))

    overlap_cells = 0
    pad_overlap_cells = 0
    scenery_overlap_cells = 0
    functional_overlap_cells = 0
    occupancy_histogram: Counter[int] = Counter()
    sid_pair_counts: Counter[tuple[str, str]] = Counter()
    examples: list[dict[str, Any]] = []
    by_id_placement = {
        int(placement["id"]): placement
        for placement in placements
        if isinstance(placement.get("id"), int)
    }
    for node, entries in sorted(node_to_entries.items()):
        # Distinct object ids on this blocked cell.
        by_id: dict[int, str] = {}
        for object_id, sid in entries:
            by_id[object_id] = sid
        count = len(by_id)
        occupancy_histogram[count] += 1
        if count < 2:
            continue
        overlap_cells += 1
        sids = sorted(by_id.values())
        for i in range(len(sids)):
            for j in range(i + 1, len(sids)):
                sid_pair_counts[(sids[i], sids[j])] += 1
        object_ids = sorted(by_id.keys())
        placements_here = [by_id_placement[i] for i in object_ids if i in by_id_placement]
        has_pad = any(
            str((p.get("entity") or {}).get("category") or "") in FOOTPRINT_PAD_CATEGORIES
            for p in placements_here
        )
        scenery_count = sum(1 for p in placements_here if is_scenery_placement(p))
        functional_count = len(placements_here) - scenery_count
        if has_pad:
            pad_overlap_cells += 1
        if scenery_count >= 2 and functional_count == 0:
            scenery_overlap_cells += 1
        if functional_count >= 2:
            functional_overlap_cells += 1
        if len(examples) < max_examples:
            examples.append({
                "node": node,
                "objectIds": object_ids,
                "sids": sids,
                "blockerCount": count,
                "hasPad": has_pad,
                "sceneryCount": scenery_count,
                "functionalCount": functional_count,
            })

    return {
        "status": "generated_artifact_validated_runtime_unvalidated",
        "policy": "olden_nodes_value_1_distinct_object_ids_per_cell",
        "overlapCellCount": overlap_cells,
        "padOverlapCellCount": pad_overlap_cells,
        "sceneryOnlyOverlapCellCount": scenery_overlap_cells,
        "functionalOverlapCellCount": functional_overlap_cells,
        "occupancyHistogram": {str(k): v for k, v in sorted(occupancy_histogram.items())},
        "topSidPairs": [
            {"a": a, "b": b, "count": count}
            for (a, b), count in sid_pair_counts.most_common(25)
        ],
        "examples": examples,
        "proofBoundary": "source/static Olden-vs-Olden occupied overlap; runtime visual stacking remains user-unvalidated",
    }


def resolve_occupied_scenery_stacks(
    placements: list[dict[str, Any]],
    *,
    native_object_configs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Remove lower-priority suppressible scenery from cells that already have another blocker."""
    by_id = {
        int(placement["id"]): placement
        for placement in placements
        if isinstance(placement.get("id"), int)
    }
    node_to_ids: dict[int, list[int]] = {}
    for placement_id, placement in by_id.items():
        sid = str(placement.get("replacementSid") or "")
        single = _single()
        if sid == single.HOMM3_PATHING_BLOCKER_SID or single.is_homm3_pathing_visual_sid(sid):
            continue
        for node in occupied_for_placement(placement, native_object_configs):
            node_to_ids.setdefault(node, []).append(placement_id)

    remove_ids: set[int] = set()
    resolved_cells = 0
    unresolved_cells = 0
    unresolved_examples: list[dict[str, Any]] = []
    for node, object_ids in sorted(node_to_ids.items()):
        unique_ids = sorted(set(object_ids))
        if len(unique_ids) < 2:
            continue
        keepers = []
        scenery_ids = []
        for object_id in unique_ids:
            placement = by_id[object_id]
            if is_scenery_placement(placement):
                scenery_ids.append(object_id)
            else:
                keepers.append(object_id)
        if keepers:
            # Functional object owns the cell; drop all stacked scenery.
            for object_id in scenery_ids:
                remove_ids.add(object_id)
            if len(keepers) > 1:
                unresolved_cells += 1
                if len(unresolved_examples) < 20:
                    unresolved_examples.append({
                        "node": node,
                        "objectIds": keepers,
                        "sids": [str(by_id[i]["replacementSid"]) for i in keepers],
                        "reason": "non_suppressible_occupied_stack",
                    })
            else:
                resolved_cells += 1
            continue
        # Scenery-only stack: keep highest priority (then lowest id), remove the rest.
        scenery_ids.sort(key=lambda oid: (-placement_priority(by_id[oid]), oid))
        for object_id in scenery_ids[1:]:
            remove_ids.add(object_id)
        resolved_cells += 1

    removed = remove_placement_ids(placements, remove_ids)
    return {
        "resolvedOverlapCellCount": resolved_cells,
        "unresolvedOverlapCellCount": unresolved_cells,
        "removedSceneryPlacementCount": removed,
        "unresolvedExamples": unresolved_examples,
    }


def append_global_scenery_gap_fill_placements(
    placements: list[dict[str, Any]],
    surface_entities: list[dict[str, Any]],
    *,
    native_object_configs: dict[str, dict[str, Any]],
    valid_ids: set[str],
    surface_map_data: dict[str, Any] | None,
    next_id: int = FOOTPRINT_PAD_ID_BASE + 50_000,
    grid_width: int | None = None,
) -> dict[str, Any]:
    single = _single()
    occupied_nodes = blocked_nodes_for_placements(placements, native_object_configs)
    width = single.OLDEN_WIDTH if grid_width is None else grid_width
    access_protected = access_protected_nodes_for_placements(
        placements,
        native_object_configs,
        grid_width=width,
    )
    functional_reserved = functional_reserved_nodes_for_current_placements(
        placements,
        native_object_configs,
        grid_width=width,
    )

    required_block_nodes: set[int] = set()
    for entity in surface_entities:
        required_block_nodes |= single.entity_nonvisitable_block_nodes(entity)
    gap_nodes = sorted(required_block_nodes - occupied_nodes)

    entity_by_node: dict[int, dict[str, Any]] = {}
    for entity in surface_entities:
        for node in single.entity_nonvisitable_block_nodes(entity):
            entity_by_node.setdefault(node, entity)

    pad_counts = Counter()
    skipped_counts = Counter()
    pad_examples: list[dict[str, Any]] = []
    emitted = 0
    for node in gap_nodes:
        if node in occupied_nodes:
            skipped_counts["already_blocked"] += 1
            continue
        if node in access_protected:
            skipped_counts["access_lane_protected"] += 1
            continue
        if node in functional_reserved:
            skipped_counts["functional_reserved"] += 1
            continue
        entity = entity_by_node.get(node)
        if not isinstance(entity, dict):
            continue
        pad_sid = choose_pad_scenery_sid(
            entity,
            valid_ids,
            surface_map_data,
            node=node,
            footprint_cells=1,
            native_object_configs=native_object_configs,
        )
        if pad_sid not in native_object_configs:
            raise ValueError(f"missing native object config for global pad scenery {pad_sid}")
        if not is_single_cell_blocker_sid(pad_sid, native_object_configs[pad_sid]):
            raise ValueError(f"global footprint pad SID must occupy exactly one cell: {pad_sid}")
        placements.append({
            "replacementSid": pad_sid,
            "id": next_id,
            "entity": {
                "sourceKey": f"footprint_global_pad:{node}",
                "category": "footprint_alignment_global_pad",
                "payloadKind": "explicit_no_payload",
            },
            "ruleName": "footprint_global_pad_biome_scenery",
            "lossiness": "footprint_alignment",
            "node": node,
            "rotation": 0,
            "level": 0.0,
            "footprintGlobalPad": {"node": node},
        })
        occupied_nodes.add(node)
        pad_counts[pad_sid] += 1
        emitted += 1
        if len(pad_examples) < 20:
            pad_examples.append({"padId": next_id, "padSid": pad_sid, "node": node})
        next_id += 1

    return {
        "status": single.HOMM3_PATHABILITY_ALIGNMENT_STATUS,
        "policy": FOOTPRINT_ALIGNMENT_POLICY,
        "phase": "global_scenery_gap_fill",
        "requiredH3NonvisitableBlockNodeCount": len(required_block_nodes),
        "occupiedNodeCountBeforeGapFill": len(occupied_nodes) - emitted,
        "candidateGapNodeCount": len(gap_nodes),
        "gapFillSceneryCount": emitted,
        "skippedGapFillReasonHistogram": dict(skipped_counts.most_common()),
        "gapFillScenerySidHistogram": dict(pad_counts.most_common()),
        "gapFillExamples": pad_examples,
        "proofBoundary": "source/static generated scenery gap-fill; native runtime pathfinder remains user-unvalidated",
    }
