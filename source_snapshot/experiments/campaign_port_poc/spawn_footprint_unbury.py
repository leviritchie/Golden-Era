#!/usr/bin/env python3
"""Relocate hero-spawner off foreign occupied footprints (shared by layered FP + approach_cell).

Olden +Y = north. South-edge land-on GATE puts town body north of the entrance; source-projected
spawn can land under that body. Prefer free anchors west of the overlapping object's GATE.

Unbury triggers only when a foreign footprint covers the hero-spawner GATE / visit cell.
Body-cell (occupied value=1) bleed from adjacent scenery must not relocate an already-valid
visit-aligned spawn onto atlas padding cliffs.

Callers must pass ``emit`` (surface_emit or build_homecoming_single_layer_map). The module does
not import footprint_alignment / functional_points so approach_cell's forbidden spine stays intact.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Any, Protocol


class SpawnUnburyRuntime(Protocol):
    width: int
    height: int
    native_object_configs: dict[str, dict[str, Any]]
    spawn_node: int
    spawn_object_id: int


@dataclass
class SpawnUnburyContext:
    """Minimal mutable runtime for approach_cell (no functional_points import)."""

    width: int
    height: int
    native_object_configs: dict[str, dict[str, Any]]
    spawn_node: int
    spawn_object_id: int


def _resolve_emit(emit: ModuleType | None) -> ModuleType:
    if emit is not None:
        return emit
    import build_homecoming_single_layer_map as single

    return single


def _object_index(objects: list[dict[str, Any]]) -> dict[int, tuple[dict[str, Any], int]]:
    result: dict[int, tuple[dict[str, Any], int]] = {}
    for group in objects:
        ids = group.get("ids") or []
        for idx, object_id in enumerate(ids):
            if isinstance(object_id, int):
                if object_id in result:
                    raise ValueError(f"duplicate object id in spawn-unbury index: {object_id}")
                result[object_id] = (group, idx)
    return result


def _object_node(objects: list[dict[str, Any]], object_id: int) -> int:
    group, idx = _object_index(objects)[object_id]
    node = (group.get("nodes") or [])[idx]
    if not isinstance(node, int):
        raise ValueError(f"object {object_id} node is not an integer: {node!r}")
    return node


def _object_rotation(objects: list[dict[str, Any]], object_id: int) -> int:
    group, idx = _object_index(objects)[object_id]
    return int((group.get("rotations") or [])[idx] or 0)


def _object_sid(objects: list[dict[str, Any]], object_id: int) -> str:
    group, _ = _object_index(objects)[object_id]
    sid = group.get("sid")
    if not isinstance(sid, str):
        raise ValueError(f"object {object_id} missing string SID")
    return sid


def _set_object_node(objects: list[dict[str, Any]], object_id: int, node: int) -> None:
    group, idx = _object_index(objects)[object_id]
    group["nodes"][idx] = int(node)


def _neighbors8(node: int, width: int, height: int) -> list[int]:
    x = node % width
    y = node // width
    out: list[int] = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nx, ny = x + dx, y + dy
            if 0 <= nx < width and 0 <= ny < height:
                out.append(ny * width + nx)
    return out


def _occupied_nodes_for_objects(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    ignore_object_ids: set[int],
    emit: ModuleType,
) -> set[int]:
    blocked: set[int] = set()
    for group in objects:
        sid = str(group.get("sid") or "")
        config = native_object_configs.get(sid)
        for object_id, node, rotation in zip(
            group.get("ids") or [],
            group.get("nodes") or [],
            group.get("rotations") or [],
        ):
            if not isinstance(object_id, int) or not isinstance(node, int):
                continue
            if object_id in ignore_object_ids:
                continue
            if sid == emit.HOMM3_PATHING_BLOCKER_SID:
                blocked.add(node)
                continue
            if emit.is_homm3_pathing_visual_sid(sid):
                continue
            if not isinstance(config, dict):
                continue
            blocked |= emit.occupied_nodes_for_object_instance(sid, config, node, int(rotation or 0))
    return blocked


def _placement_nodes_for_objects(
    objects: list[dict[str, Any]],
    *,
    ignore_object_ids: set[int],
) -> set[int]:
    """Every other object's placement anchor — including payload SIDs with empty footprints.

    Approach-cell contracts forbid any non-spawn object sharing the hero-spawner node, even
    when ObjectConfig has no occupied cells (e.g. random-squad).
    """
    placed: set[int] = set()
    for group in objects:
        for object_id, node in zip(group.get("ids") or [], group.get("nodes") or []):
            if not isinstance(object_id, int) or object_id in ignore_object_ids:
                continue
            if isinstance(node, int):
                placed.add(node)
    return placed


def _objects_occupying_cells(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    cells: set[int],
    *,
    exclude_ids: set[int],
    emit: ModuleType,
) -> list[int]:
    found: list[int] = []
    for group in objects:
        sid = str(group.get("sid") or "")
        config = native_object_configs.get(sid)
        for object_id, node, rotation in zip(
            group.get("ids") or [],
            group.get("nodes") or [],
            group.get("rotations") or [],
        ):
            if not isinstance(object_id, int) or object_id in exclude_ids or not isinstance(node, int):
                continue
            if sid == emit.HOMM3_PATHING_BLOCKER_SID or emit.is_homm3_pathing_visual_sid(sid):
                occupied = {node}
            elif isinstance(config, dict):
                occupied = emit.occupied_nodes_for_object_instance(sid, config, node, int(rotation or 0))
                # Empty footprints still occupy their placement anchor for spawn co-location.
                if not occupied:
                    occupied = {node}
            else:
                occupied = {node}
            if occupied & cells:
                found.append(object_id)
    return found


def _spawn_gate_cells(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    spawn_id: int,
    spawn_node: int,
    *,
    emit: ModuleType,
) -> set[int]:
    """Visit / GATE cells for a hero-spawner (node_value=2). Falls back to placement node."""
    sid = _object_sid(objects, spawn_id)
    config = native_object_configs.get(sid)
    if not isinstance(config, dict):
        return {spawn_node}
    gate = emit.nodes_for_object_instance_with_value(
        sid,
        config,
        spawn_node,
        _object_rotation(objects, spawn_id),
        node_value=2,
    )
    return gate if gate else {spawn_node}


def _spawn_placement_footprint(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    spawn_id: int,
    spawn_node: int,
    spawn_rot: int,
    *,
    emit: ModuleType,
) -> set[int]:
    sid = _object_sid(objects, spawn_id)
    config = native_object_configs.get(sid)
    if not isinstance(config, dict):
        return {spawn_node}
    foot = emit.occupied_nodes_for_object_instance(sid, config, spawn_node, spawn_rot)
    foot |= emit.nodes_for_object_instance_with_value(
        sid, config, spawn_node, spawn_rot, node_value=2
    )
    return foot if foot else {spawn_node}


def _elevated_unramped_cells(
    cells: set[int],
    *,
    levels_map: list[int] | None,
    climbs_map: list[int] | None,
) -> set[int]:
    """levelsMap=1 with no ramp is not a legal hero spawn / relocate surface."""
    if not levels_map:
        return set()
    bad: set[int] = set()
    for node in cells:
        if node < 0 or node >= len(levels_map):
            continue
        if int(levels_map[node]) != 1:
            continue
        climb = int(climbs_map[node]) if climbs_map and node < len(climbs_map) else 0
        if climb == 0:
            bad.add(node)
    return bad


def assert_hero_spawners_outside_forbidden(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    emit: ModuleType,
    forbidden_nodes: set[int],
    width: int,
    levels_map: list[int] | None = None,
    climbs_map: list[int] | None = None,
) -> None:
    """Fail-closed: no hero-spawner GATE/visit may remain on padding or elevated cliffs."""
    cliff_heroes: list[dict[str, Any]] = []
    for group in objects:
        if group.get("sid") != "hero-spawner":
            continue
        for oid, node, rot in zip(
            group.get("ids") or [],
            group.get("nodes") or [],
            group.get("rotations") or [],
        ):
            if not isinstance(oid, int) or not isinstance(node, int):
                continue
            gate = _spawn_gate_cells(
                objects,
                native_object_configs,
                oid,
                node,
                emit=emit,
            )
            hit_pad = sorted(gate & forbidden_nodes)
            hit_elev = sorted(
                _elevated_unramped_cells(gate, levels_map=levels_map, climbs_map=climbs_map)
            )
            if hit_pad or hit_elev:
                cliff_heroes.append(
                    {
                        "objectId": oid,
                        "node": node,
                        "xy": [node % width, node // width],
                        "paddingCells": hit_pad[:12],
                        "elevatedUnrampedCells": hit_elev[:12],
                        "rotation": int(rot or 0),
                    }
                )
    if cliff_heroes:
        raise ValueError(
            "hero-spawner GATE/visit intersects envelope padding / elevated unramped cliffs "
            f"(count={len(cliff_heroes)} sample={cliff_heroes[:5]}); "
            "spawn unbury must not leave heroes on OOB cliffs"
        )


def unbury_spawn_from_foreign_footprints(
    objects: list[dict[str, Any]],
    runtime: SpawnUnburyRuntime,
    *,
    emit: ModuleType | None = None,
    forbidden_nodes: set[int] | None = None,
    levels_map: list[int] | None = None,
    climbs_map: list[int] | None = None,
) -> dict[str, Any] | None:
    """Move hero-spawner off foreign GATE/visit burial. Mutates objects and runtime.spawn_node.

    Relocate only when a foreign footprint covers the hero-spawner GATE (visit) cell — not when
    scenery merely overlaps the north/east body cells of the 3x3 ObjectConfig.

    ``forbidden_nodes`` (atlas envelope-padding elevated-cliff cells) and elevated-unramped
    ``levels_map``/``climbs_map`` cells are never valid relocates.
    """
    single = _resolve_emit(emit)
    forbidden = set(forbidden_nodes or ())
    spawn_id = runtime.spawn_object_id
    spawn_sid = _object_sid(objects, spawn_id)
    spawn_config = runtime.native_object_configs.get(spawn_sid)
    spawn_rot = _object_rotation(objects, spawn_id)
    spawn_anchor = _object_node(objects, spawn_id)
    # Truly buried = foreign occupancy on GATE/visit, not body-cell scenery bleed.
    spawn_gate = _spawn_gate_cells(
        objects,
        runtime.native_object_configs,
        spawn_id,
        spawn_anchor,
        emit=single,
    )
    stacks = _objects_occupying_cells(
        objects,
        runtime.native_object_configs,
        spawn_gate,
        exclude_ids={spawn_id},
        emit=single,
    )
    # Prefer clearing suppressible scenery / gap-fill / scenery exact-footprint clones
    # that sit on the spawn GATE over relocating the hero-spawner into padding cliffs.
    clearable_sids = set(getattr(single, "SUPPRESSIBLE_SOURCE_SCENERY_SIDS", ()) or ())
    gap_fill_sid = getattr(single, "HOMM3_PATHING_GAP_FILL_VISIBLE_SID", "mountain_dirt_small_1")
    clearable_sids.add(gap_fill_sid)
    clearable_sids.add(getattr(single, "HOMM3_PATHING_BLOCKER_SID", "homm3_pathing_blocker"))
    remove_ids: set[int] = set()
    for foreign_id in list(stacks):
        foreign_sid = _object_sid(objects, foreign_id)
        if (
            foreign_sid in clearable_sids
            or str(foreign_sid).startswith("homm3_xfp_s_")
            or str(foreign_sid).startswith("mountain_")
            or str(foreign_sid).startswith("tree_")
            or str(foreign_sid).startswith("pinetree")
        ):
            remove_ids.add(foreign_id)
    if remove_ids:
        for group in objects:
            ids = group.get("ids") or []
            if not isinstance(ids, list) or not ids:
                continue
            keep = [i for i, oid in enumerate(ids) if oid not in remove_ids]
            if len(keep) == len(ids):
                continue
            for key in ("ids", "nodes", "rotations", "levels"):
                values = group.get(key)
                if isinstance(values, list):
                    group[key] = [values[i] for i in keep if i < len(values)]
        objects[:] = [group for group in objects if group.get("ids")]
        stacks = _objects_occupying_cells(
            objects,
            runtime.native_object_configs,
            spawn_gate,
            exclude_ids={spawn_id},
            emit=single,
        )

    gate_on_illegal = bool(spawn_gate & forbidden) or bool(
        _elevated_unramped_cells(spawn_gate, levels_map=levels_map, climbs_map=climbs_map)
    )
    if not stacks and not gate_on_illegal:
        # Visit-aligned / GATE-clear on playable surface: leave alone
        # (even if body cells overlap adjacent scenery).
        return None

    width = runtime.width
    height = runtime.height
    preferred: list[int] = []
    for foreign_id in stacks:
        foreign_sid = _object_sid(objects, foreign_id)
        foreign_config = runtime.native_object_configs.get(foreign_sid)
        foreign_node = _object_node(objects, foreign_id)
        foreign_rot = _object_rotation(objects, foreign_id)
        gate_nodes: set[int] = set()
        if isinstance(foreign_config, dict):
            gate_nodes = single.nodes_for_object_instance_with_value(
                foreign_sid,
                foreign_config,
                foreign_node,
                foreign_rot,
                node_value=2,
            )
        if not gate_nodes:
            gate_nodes = {foreign_node}
        for gate in sorted(gate_nodes):
            gx, gy = gate % width, gate // width
            for dx, dy in ((-1, 0), (-2, 0), (0, -1), (0, 1), (1, 0), (-1, -1), (-1, 1), (1, -1), (1, 1)):
                nx, ny = gx + dx, gy + dy
                if 0 <= nx < width and 0 <= ny < height:
                    preferred.append(ny * width + nx)

    frontier = [spawn_anchor]
    seen = {spawn_anchor}
    for _ in range(width + height):
        if not frontier:
            break
        nxt_frontier: list[int] = []
        for node in frontier:
            for nxt in _neighbors8(node, width, height):
                if nxt in seen:
                    continue
                seen.add(nxt)
                preferred.append(nxt)
                nxt_frontier.append(nxt)
        frontier = nxt_frontier

    foreign_blocked = _occupied_nodes_for_objects(
        objects,
        runtime.native_object_configs,
        ignore_object_ids={spawn_id},
        emit=single,
    )
    # Also block placement anchors so spawn cannot land on payload-only SIDs
    # (random-squad, etc.) that have no ObjectConfig occupancy.
    foreign_blocked |= _placement_nodes_for_objects(objects, ignore_object_ids={spawn_id})
    for foreign_id in stacks:
        foreign_sid = _object_sid(objects, foreign_id)
        foreign_config = runtime.native_object_configs.get(foreign_sid)
        if not isinstance(foreign_config, dict):
            continue
        foreign_blocked |= single.nodes_for_object_instance_with_value(
            foreign_sid,
            foreign_config,
            _object_node(objects, foreign_id),
            _object_rotation(objects, foreign_id),
            node_value=2,
        )

    previous = spawn_anchor

    def _candidate_illegal(foot: set[int]) -> bool:
        if foot & forbidden:
            return True
        if _elevated_unramped_cells(foot, levels_map=levels_map, climbs_map=climbs_map):
            return True
        if any(
            not (0 <= (cell % width) < width and 0 <= (cell // width) < height)
            for cell in foot
        ):
            return True
        return False

    for candidate in preferred:
        if candidate in forbidden:
            continue
        if _elevated_unramped_cells({candidate}, levels_map=levels_map, climbs_map=climbs_map):
            continue
        if not isinstance(spawn_config, dict):
            if candidate in foreign_blocked:
                continue
            if _candidate_illegal({candidate}):
                continue
            _set_object_node(objects, spawn_id, candidate)
            object.__setattr__(runtime, "spawn_node", candidate)
            return {
                "functionalPointId": "spawn",
                "action": "relocate_spawn_off_foreign_footprint",
                "objectId": spawn_id,
                "fromNode": previous,
                "toNode": candidate,
                "stackedObjectIds": sorted(stacks),
                "buryPolicy": "gate_visit_cell_only",
                "forbiddenNodePolicy": "reject_envelope_padding_elevated_cliffs",
                "gateWasOnIllegalSurface": gate_on_illegal,
            }
        new_foot = _spawn_placement_footprint(
            objects,
            runtime.native_object_configs,
            spawn_id,
            candidate,
            spawn_rot,
            emit=single,
        )
        if new_foot & foreign_blocked:
            continue
        if _candidate_illegal(new_foot):
            continue
        _set_object_node(objects, spawn_id, candidate)
        object.__setattr__(runtime, "spawn_node", candidate)
        return {
            "functionalPointId": "spawn",
            "action": "relocate_spawn_off_foreign_footprint",
            "objectId": spawn_id,
            "fromNode": previous,
            "toNode": candidate,
            "stackedObjectIds": sorted(stacks),
            "buryPolicy": "gate_visit_cell_only",
            "forbiddenNodePolicy": "reject_envelope_padding_elevated_cliffs",
            "gateWasOnIllegalSurface": gate_on_illegal,
        }

    _set_object_node(objects, spawn_id, previous)
    object.__setattr__(runtime, "spawn_node", previous)
    raise ValueError(
        f"cannot relocate spawn {spawn_id} off foreign GATE burial {sorted(stacks)} "
        f"without entering forbidden/envelope-padding/elevated-unramped cells "
        f"(forbiddenCount={len(forbidden)} gateOnIllegal={gate_on_illegal}); "
        f"spawnGate={sorted(spawn_gate)}"
    )
