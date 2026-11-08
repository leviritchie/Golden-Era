#!/usr/bin/env python3
"""Rotate mirrored GATE footprints so a GATE faces a free cardinal approach.

Raw translation places HoMM3 interactables with donor ObjectConfig.nodes. Default
rotation can leave every GATE with no free land approach while the mirrored
rotation would. This pass is fail-closed: eligible blocked objects must resolve to
a working rotation or generation fails with an explicit list.

Eligibility: any canBeMirrored ObjectConfig with ≥1 GATE (small portals and larger
buildings alike). Trigger: default rotation has zero free cardinal approaches.

Blockers for approach freeness: scenery and other buildings only. Neutral stacks,
monster armies, and hero-spawners (guard / placed heroes) do not count as blockers —
their cells are treated as open for rotation decisions. Pathable land terrain is still
required; water, void, elevated no-ramp cliffs, and impassable terrain still block.

When both rotations are blocked only by suppressible scenery / gap-fill pads, those
blockers are cleared from the candidate approach cells and the rotation is retried
(Neutral Affairs one-way portal_1 hit this). Functional building blockers still fail
closed. Resource piles, chests, and other pickups are keepers — never cleared as
"nonkeeper" approach seals (that previously deleted gold next to visit banks).

Portal family (portal_1..5, including stock subterranean gates as portal_5): always
eligible for mirror rotation when the entrance is covered. If every face remains
sealed after clears/carve (typically keeper pickups), soft-skip with an explicit
report instead of failing the whole map. Dedicated homm3_subterranean_gate_portal
stays fail-closed.

Underground void/elevated-rock seals: before classifying a footprint as permanently
terrain-sealed, carve void cardinal neighbors into Burrow so a GATE can open.

Timing (orchestrator contract): must run as a late generator pass after all objects,
scenery, per-layer gap-fill, landon_access, post-landon gap-fill, and envelope pads
are placed. Approach freeness is evaluated against that final occupancy; an earlier
pass can falsely mark faces OK before late seals land on their approaches.

Policy: raw_gated_mirror_rotation_to_free_cardinal_approach
Phase: after_final_occupancy
"""
from __future__ import annotations

from typing import Any

import functional_emit_reservation as fer
import object_property_namespaces as propns
import surface_emit as single

POLICY = "raw_gated_mirror_rotation_to_free_cardinal_approach"
RELOCATION_POLICY = "bounded_same_atlas_region_functional_collision_relocation"
# Prior narrow policy name kept as alias for breadcrumb/search continuity.
LEGACY_POLICY = "raw_single_gate_mirror_rotation_to_free_cardinal_approach"
PHASE = "after_final_occupancy"
STATUS = "generated_artifact_validator_runtime_unvalidated"

# Whirlpools / boats sit on water; Olden water approach is a separate traversal bridge.
WATER_GATE_EXEMPT_SIDS = frozenset({"portal_magic", "homm3_boat"})

# Event-bank / visit buildings often ship incidental GATE nodes in ObjectConfig.
# Mirror rotation is for travel portals and Landon-style path gates; visit banks
# that remain approach-sealed after clears must not fail the whole map emit
# (Independence altar_of_magic_1).
#
# Do NOT put portal_* here. Stock subterranean gates are portal_5; monoliths are
# portal_1..5. Blanketing them as ineligible left covered entrances unrotated.
# Portal instances still try mirror rotation + clears; if a keeper pickup seals
# every face, soft-skip instead of fail-closing the whole map emit.
VISIT_BANK_GATE_EXEMPT_PREFIXES = (
    "altar_of_magic",
    "altar_of_sacrifice",
    "altar_of_wishes",
    "campaign_magic_altar",
    "custom_MB_magic_altar",
    # Dwelling / den visit banks ship incidental GATEs; keeper pickups on the
    # footprint must not fail-close the whole map (Tunnels shady_den).
    "shady_den",
    # Experience / skill visit banks (gazebo → temporary_camp, university).
    # Keeper pickups on approach must not fail-close map emit.
    "temporary_camp",
    "university",
    "custom_university",
    # Abandoned Outpost visit bank (native OE town-conversion site). HoMM3
    # Abandoned Mine now remaps to mine_gold; keep this SID for any remaining
    # native/outpost placements that still need approach soft-fail.
    "abandoned_outpost",
)

# After rotation + clears + void carve, portal_* that remain sealed (usually by
# keeper pickups) soft-skip rather than raising. Dedicated subterranean SID
# stays fail-closed — its entrance must open.
PORTAL_SOFT_UNRESOLVED_PREFIXES = ("portal_",)
SUBTERRANEAN_GATE_FAIL_CLOSED_SIDS = frozenset(
    {
        "homm3_subterranean_gate_portal",
    }
)

# Olden only honors rotation 10 when canBeMirrored is true; try 0 then 10.
ROTATION_CANDIDATES = (single.OLDEN_DEFAULT_ROTATION, single.OLDEN_MIRRORED_ROTATION)

# Enemies occupy cells but do not seal GATE approaches for rotation purposes.
ENEMY_NONBLOCKING_SIDS = frozenset(
    {
        "random-squad",
        "hero-spawner",
    }
)

_CLEARABLE_APPROACH_SIDS = frozenset(
    set(fer.SUPPRESSIBLE_SOURCE_SCENERY_SIDS)
    | {
        single.HOMM3_PATHING_GAP_FILL_VISIBLE_SID,
        single.HOMM3_PATHING_BLOCKER_SID,
    }
)


def _is_clearable_approach_sid(sid: str) -> bool:
    return sid in _CLEARABLE_APPROACH_SIDS or str(sid).startswith("homm3_xfp_s_")

# Last-resort clear for portal_* GATE approaches: keep functional interactables only.
_PORTAL_APPROACH_KEEP_EXACT = frozenset(
    {
        "hero-spawner",
        "random-squad",
        "homm3_subterranean_gate_portal",
    }
)


def _is_portal_approach_keeper(sid: str) -> bool:
    if sid in _PORTAL_APPROACH_KEEP_EXACT:
        return True
    if _is_enemy_nonblocking_sid(sid):
        return True
    # Pickups must remain on map; GATE-approach freeness cannot delete gold/chests.
    if single.is_pickup_range_fallback_sid(sid) or sid.startswith("resource_"):
        return True
    if sid in {"chest", "random-item", "random-res"} or "artifact" in sid:
        return True
    if sid.startswith("portal_"):
        return True
    if sid.startswith("barracks_"):
        return True
    if sid.startswith("homm3_landon_"):
        return True
    if sid.endswith("_city"):
        return True
    return False


def _clear_nonkeeper_portal_approach_blockers(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    sid: str,
    config: dict[str, Any],
    anchor: int,
    rotations: list[int],
    exclude_object_id: int,
    width: int,
    height: int,
    properties: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Remove non-keeper scenery/buildings covering GATE cells or cardinal neighbors."""
    cells: set[int] = set()
    for rotation in rotations:
        gates = single.gate_nodes_for_object_instance(sid, config, anchor, rotation)
        cells |= set(gates)
        for gate in gates:
            cells.update(_cardinal_neighbors(gate, width=width, height=height))
    owners = _owners_covering_nodes(
        objects,
        native_object_configs,
        cells,
        exclude_object_id=exclude_object_id,
    )
    remove_ids: set[int] = set()
    report: list[dict[str, Any]] = []
    for object_id, owner_sid in owners:
        if _is_portal_approach_keeper(owner_sid):
            continue
        remove_ids.add(object_id)
        report.append(
            {
                "objectId": object_id,
                "sid": owner_sid,
                "reason": "gate_approach_nonkeeper_clear",
            }
        )
    _remove_object_ids(objects, remove_ids, properties)
    return report

def _cardinal_neighbors(node: int, *, width: int, height: int) -> list[int]:
    x = node % width
    y = node // width
    out: list[int] = []
    for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nx = x + dx
        ny = y + dy
        if 0 <= nx < width and 0 <= ny < height:
            out.append(ny * width + nx)
    return out


def _terrain_pathable(
    node: int,
    *,
    tiles_map: list[int],
    water_map: list[int],
    levels_map: list[int] | None = None,
    climbs_map: list[int] | None = None,
) -> bool:
    if node < 0 or node >= len(tiles_map):
        return False
    if water_map and node < len(water_map) and int(water_map[node] or 0) != 0:
        return False
    tile = int(tiles_map[node])
    # Ocean carries a nonzero waterMap (rejected above); Void is not a land approach.
    if tile == 23:  # Void
        return False
    # Elevated no-ramp cliffs (envelope padding / underground rock) are not walkable.
    if levels_map is not None and node < len(levels_map) and int(levels_map[node]) > 0:
        climb = (
            int(climbs_map[node])
            if climbs_map is not None and node < len(climbs_map)
            else 0
        )
        if climb == 0:
            return False
    return True


def _is_enemy_nonblocking_sid(sid: str) -> bool:
    """Neutral stacks / monster armies / heroes do not seal GATE approaches."""
    return sid in ENEMY_NONBLOCKING_SIDS


def _config_gate_counts(config: dict[str, Any]) -> tuple[int, int] | None:
    size_x = config.get("sizeX")
    size_z = config.get("sizeZ")
    nodes = config.get("nodes")
    if (
        not isinstance(size_x, int)
        or not isinstance(size_z, int)
        or size_x <= 0
        or size_z <= 0
        or not isinstance(nodes, list)
        or len(nodes) != size_x * size_z
    ):
        return None
    gate_count = sum(1 for value in nodes if value == 2)
    return gate_count, size_x * size_z


def _is_portal_soft_unresolved_sid(sid: str) -> bool:
    """True when unresolved portal faces soft-skip instead of fail-closing emit."""
    if sid in SUBTERRANEAN_GATE_FAIL_CLOSED_SIDS:
        return False
    return any(sid.startswith(prefix) for prefix in PORTAL_SOFT_UNRESOLVED_PREFIXES)


def is_eligible_gated_mirror_object(sid: str, config: dict[str, Any]) -> bool:
    """True when mirror rotation can reorient at least one GATE face."""
    if sid == single.HOMM3_PATHING_BLOCKER_SID or single.is_homm3_pathing_visual_sid(sid):
        return False
    if sid in WATER_GATE_EXEMPT_SIDS:
        return False
    if any(sid.startswith(prefix) for prefix in VISIT_BANK_GATE_EXEMPT_PREFIXES):
        return False
    if _is_enemy_nonblocking_sid(sid):
        # Do not rotate the enemy itself for approach freeness of other objects.
        return False
    counts = _config_gate_counts(config)
    if counts is None:
        return False
    gate_count, _ = counts
    if gate_count < 1:
        return False
    if config.get("canBeMirrored") is not True:
        return False
    return True


# Back-compat alias for callers / tests that still use the narrow name.
def is_eligible_single_gate_mirror_object(sid: str, config: dict[str, Any]) -> bool:
    return is_eligible_gated_mirror_object(sid, config)


def _build_foreign_occupied(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    exclude_object_id: int | None = None,
    exclude_object_ids: set[int] | None = None,
) -> set[int]:
    """Occupied cells from scenery + buildings only (enemies omitted)."""
    occupied: set[int] = set()
    for group in objects:
        sid = group.get("sid")
        if not isinstance(sid, str):
            continue
        if _is_enemy_nonblocking_sid(sid):
            continue
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
            if exclude_object_id is not None and object_id == exclude_object_id:
                continue
            if exclude_object_ids is not None and object_id in exclude_object_ids:
                continue
            occupied |= single.occupied_nodes_for_object_instance(
                sid, config, node, int(rotation or 0)
            )
    return occupied


def _object_sid_index(objects: list[dict[str, Any]]) -> dict[int, str]:
    index: dict[int, str] = {}
    for group in objects:
        sid = group.get("sid")
        if not isinstance(sid, str):
            continue
        for object_id in group.get("ids") or []:
            if isinstance(object_id, int):
                index[object_id] = sid
    return index


def _owners_covering_nodes(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    nodes: set[int],
    *,
    exclude_object_id: int,
) -> list[tuple[int, str]]:
    owners: list[tuple[int, str]] = []
    for group in objects:
        sid = group.get("sid")
        if not isinstance(sid, str):
            continue
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
            if object_id == exclude_object_id:
                continue
            occupied = single.occupied_nodes_for_object_instance(
                sid, config, node, int(rotation or 0)
            )
            if occupied & nodes:
                owners.append((object_id, sid))
    return owners


def _remove_property_rows(properties: dict[str, Any] | None, remove_ids: set[int]) -> None:
    """Drop object-namespace property rows whose id was removed from objects[].

    Marker-namespace rows (type 1 / Zone hosts) use a separate id space and must
    not be scrubbed by object-id coincidence.
    """
    propns.remove_object_property_rows(properties, remove_ids)


def _assert_objects_pack_arrays_consistent(objects: list[dict[str, Any]]) -> None:
    """Fail-closed: every objects[] group must have equal ids/nodes/rotations/levels."""
    bad: list[str] = []
    for group in objects:
        if not isinstance(group, dict):
            continue
        ids = group.get("ids") or []
        nodes = group.get("nodes") or []
        rotations = group.get("rotations") or []
        levels = group.get("levels") or []
        if len(ids) == len(nodes) == len(rotations) == len(levels):
            continue
        bad.append(
            f"{group.get('sid')}: ids={len(ids)} nodes={len(nodes)} "
            f"rotations={len(rotations)} levels={len(levels)}"
        )
    if bad:
        raise ValueError(
            "gate_face_rotation left objects[] pack array length mismatch: "
            + "; ".join(bad[:8])
        )


def _remove_object_ids(
    objects: list[dict[str, Any]],
    remove_ids: set[int],
    properties: dict[str, Any] | None = None,
) -> None:
    if not remove_ids:
        return
    for group in objects:
        ids = group.get("ids") or []
        nodes = group.get("nodes") or []
        rotations = group.get("rotations") or []
        levels = group.get("levels") or []
        keep = [
            i
            for i, object_id in enumerate(ids)
            if not (isinstance(object_id, int) and object_id in remove_ids)
        ]
        if len(keep) == len(ids):
            continue
        group["ids"] = [ids[i] for i in keep]
        group["nodes"] = [nodes[i] for i in keep]
        group["rotations"] = [rotations[i] for i in keep]
        # Mirror landon_access / vanilla_stock: zip-trim levels with ids/nodes/rotations.
        # Leaving stale levels entries after id removal produces len(levels) > len(ids),
        # which vanilla Story maps never have and correlates with Map load NRE → dual
        # QuestSystem init → doubled StartTurn Dialogs (Player.log qi=2 nre=1 osc=2).
        if levels:
            group["levels"] = [levels[i] for i in keep if i < len(levels)]
    objects[:] = [
        group
        for group in objects
        if isinstance(group, dict) and (group.get("ids") or [])
    ]
    _remove_property_rows(properties, remove_ids)


def _clear_suppressible_approach_blockers(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    sid: str,
    config: dict[str, Any],
    anchor: int,
    rotations: list[int],
    exclude_object_id: int,
    tiles_map: list[int],
    water: list[int],
    width: int,
    height: int,
    properties: dict[str, Any] | None = None,
    clearable_object_ids: set[int] | None = None,
    levels_map: list[int] | None = None,
    climbs_map: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Clear suppressible scenery blocking GATE cells or their cardinal approaches."""
    cleared_report: list[dict[str, Any]] = []
    target_cells: set[int] = set()
    for rotation in rotations:
        gates = single.gate_nodes_for_object_instance(sid, config, anchor, rotation)
        self_occ = single.occupied_nodes_for_object_instance(sid, config, anchor, rotation)
        # Suppressible scenery sitting on GATE cells seals freeness the same as
        # approach seals; clear those too (Tunnels mountain_dirt on shady_den GATE).
        target_cells.update(gates)
        for gate in gates:
            for neighbor in _cardinal_neighbors(gate, width=width, height=height):
                if neighbor in self_occ or neighbor in gates:
                    continue
                if not _terrain_pathable(
                    neighbor,
                    tiles_map=tiles_map,
                    water_map=water,
                    levels_map=levels_map,
                    climbs_map=climbs_map,
                ):
                    continue
                target_cells.add(neighbor)
    if not target_cells:
        return cleared_report
    owners = _owners_covering_nodes(
        objects,
        native_object_configs,
        target_cells,
        exclude_object_id=exclude_object_id,
    )
    remove_ids: set[int] = set()
    for object_id, owner_sid in owners:
        if (
            (clearable_object_ids is not None and object_id in clearable_object_ids)
            or _is_clearable_approach_sid(owner_sid)
            or single.is_homm3_pathing_visual_sid(owner_sid)
        ):
            remove_ids.add(object_id)
            cleared_report.append(
                {
                    "objectId": object_id,
                    "sid": owner_sid,
                    "reason": "suppressible_or_gapfill_blocking_gate_approach",
                }
            )
    _remove_object_ids(objects, remove_ids, properties)
    return cleared_report


def _set_node_and_rotation(
    objects: list[dict[str, Any]], object_id: int, node: int, rotation: int
) -> None:
    for group in objects:
        ids = group.get("ids") or []
        if object_id not in ids:
            continue
        index = ids.index(object_id)
        nodes = group.get("nodes") or []
        rotations = group.get("rotations") or []
        if index >= len(nodes) or index >= len(rotations):
            raise ValueError(f"object {object_id} missing node/rotation slot")
        nodes[index] = node
        rotations[index] = rotation
        return
    raise ValueError(f"object {object_id} not found for gate-face relocation")


def _relocate_gated_object(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    object_id: int,
    sid: str,
    config: dict[str, Any],
    anchor: int,
    rotations: list[int],
    clearable_object_ids: set[int],
    tiles_map: list[int],
    water: list[int],
    width: int,
    height: int,
    region_width: int,
    max_radius: int,
    properties: dict[str, Any] | None,
    levels_map: list[int] | None = None,
    climbs_map: list[int] | None = None,
) -> dict[str, Any] | None:
    """Move an oversized stock substitute only when functional footprints collide."""
    if max_radius <= 0 or region_width <= 0 or width % region_width != 0:
        return None
    origin_x = anchor % width
    origin_y = anchor // width
    origin_region = origin_x // region_width
    functional_occupied = _build_foreign_occupied(
        objects,
        native_object_configs,
        exclude_object_id=object_id,
        exclude_object_ids=clearable_object_ids,
    )

    for distance in range(max_radius + 1):
        for dy in range(-distance, distance + 1):
            dx_abs = distance - abs(dy)
            dx_values = (0,) if dx_abs == 0 else (-dx_abs, dx_abs)
            for dx in dx_values:
                x = origin_x + dx
                y = origin_y + dy
                if not (0 <= x < width and 0 <= y < height):
                    continue
                if x // region_width != origin_region:
                    continue
                candidate_node = y * width + x
                for rotation in rotations:
                    occupied = single.occupied_nodes_for_object_instance(
                        sid, config, candidate_node, rotation
                    )
                    if occupied & functional_occupied:
                        continue
                    approaches = free_cardinal_approaches(
                        sid,
                        config,
                        candidate_node,
                        rotation,
                        foreign_occupied=functional_occupied,
                        tiles_map=tiles_map,
                        water_map=water,
                        width=width,
                        height=height,
                    levels_map=levels_map,
                    climbs_map=climbs_map,
                    )
                    if not approaches:
                        continue

                    candidate_cells = set(occupied) | set(approaches)
                    covering = _owners_covering_nodes(
                        objects,
                        native_object_configs,
                        candidate_cells,
                        exclude_object_id=object_id,
                    )
                    remove_ids = {
                        owner_id
                        for owner_id, _owner_sid in covering
                        if owner_id in clearable_object_ids
                    }
                    cleared = [
                        {
                            "objectId": owner_id,
                            "sid": owner_sid,
                            "reason": "bounded_gate_relocation_scenery_clear",
                        }
                        for owner_id, owner_sid in covering
                        if owner_id in remove_ids
                    ]
                    _remove_object_ids(objects, remove_ids, properties)
                    _set_node_and_rotation(objects, object_id, candidate_node, rotation)
                    return {
                        "policy": RELOCATION_POLICY,
                        "fromNode": anchor,
                        "toNode": candidate_node,
                        "distance": distance,
                        "dx": dx,
                        "dy": dy,
                        "rotation": rotation,
                        "approaches": sorted(approaches),
                        "clearedRelocationBlockers": cleared,
                    }
    return None


def _carve_void_burrow_approaches(
    *,
    sid: str,
    config: dict[str, Any],
    anchor: int,
    rotations: list[int],
    tiles_map: list[int],
    water: list[int],
    levels_map: list[int] | None,
    climbs_map: list[int] | None,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    """Carve Olden void/rock cells into Burrow so an underground portal GATE can open.

    Tunnels places two-way monoliths against elevated rock. Rotation cannot invent a
    land approach when every cardinal neighbor is void tile 23. Convert the first
    void neighbor per try-rotation into Burrow and flatten elevation (lossy visual).
    """
    carved: list[dict[str, Any]] = []
    burrow_id = 15
    try:
        import h3m_scenario_translation as scenario

        burrow_id = int(scenario.OLDEN_BURROW_TILE_ID)
    except Exception:
        pass
    for rotation in rotations:
        gates = single.gate_nodes_for_object_instance(sid, config, anchor, rotation)
        self_occ = single.occupied_nodes_for_object_instance(sid, config, anchor, rotation)
        for gate in gates:
            for neighbor in _cardinal_neighbors(gate, width=width, height=height):
                if neighbor in self_occ or neighbor in gates:
                    continue
                if neighbor < 0 or neighbor >= len(tiles_map):
                    continue
                if water and neighbor < len(water) and int(water[neighbor] or 0) != 0:
                    continue
                tile = int(tiles_map[neighbor])
                if tile != 23:  # Void / underground rock projection
                    continue
                before_level = (
                    int(levels_map[neighbor])
                    if levels_map is not None and neighbor < len(levels_map)
                    else None
                )
                before_climb = (
                    int(climbs_map[neighbor])
                    if climbs_map is not None and neighbor < len(climbs_map)
                    else None
                )
                tiles_map[neighbor] = burrow_id
                if levels_map is not None and neighbor < len(levels_map):
                    levels_map[neighbor] = 0
                if climbs_map is not None and neighbor < len(climbs_map):
                    climbs_map[neighbor] = 0
                carved.append(
                    {
                        "node": neighbor,
                        "fromTile": 23,
                        "toTile": burrow_id,
                        "fromLevel": before_level,
                        "fromClimb": before_climb,
                        "gateNode": gate,
                        "rotation": rotation,
                        "reason": "underground_portal_void_approach_carve",
                    }
                )
                # One carve per GATE/rotation is enough to reopen a cardinal.
                break
    return carved


def free_cardinal_approaches(
    sid: str,
    config: dict[str, Any],
    anchor_node: int,
    rotation: int,
    *,
    foreign_occupied: set[int],
    tiles_map: list[int],
    water_map: list[int],
    width: int,
    height: int,
    levels_map: list[int] | None = None,
    climbs_map: list[int] | None = None,
) -> set[int]:
    """Return free land cardinal neighbors of any GATE cell under this rotation.

    A GATE whose cell is occupied by scenery/buildings is not approachable. Enemy
    occupancy is already omitted from ``foreign_occupied``.
    """
    self_occ = single.occupied_nodes_for_object_instance(sid, config, anchor_node, rotation)
    gates = single.gate_nodes_for_object_instance(sid, config, anchor_node, rotation)
    if not gates:
        return set()
    approaches: set[int] = set()
    for gate in gates:
        if gate in foreign_occupied:
            continue
        for neighbor in _cardinal_neighbors(gate, width=width, height=height):
            if neighbor in self_occ or neighbor in gates:
                continue
            if neighbor in foreign_occupied:
                continue
            if not _terrain_pathable(
                neighbor,
                tiles_map=tiles_map,
                water_map=water_map,
                levels_map=levels_map,
                climbs_map=climbs_map,
            ):
                continue
            approaches.add(neighbor)
    return approaches


def land_cardinal_neighbors(
    sid: str,
    config: dict[str, Any],
    anchor_node: int,
    rotation: int,
    *,
    tiles_map: list[int],
    water_map: list[int],
    width: int,
    height: int,
    levels_map: list[int] | None = None,
    climbs_map: list[int] | None = None,
) -> set[int]:
    """Land-terrain cardinal neighbors of GATEs, ignoring foreign occupancy.

    Used to distinguish scenery/building seals (rotation problem) from water/void
    seals (not fixable by mirror rotation). Elevated no-ramp cliffs count as sealed.
    """
    self_occ = single.occupied_nodes_for_object_instance(sid, config, anchor_node, rotation)
    gates = single.gate_nodes_for_object_instance(sid, config, anchor_node, rotation)
    land: set[int] = set()
    for gate in gates:
        for neighbor in _cardinal_neighbors(gate, width=width, height=height):
            if neighbor in self_occ or neighbor in gates:
                continue
            if not _terrain_pathable(
                neighbor,
                tiles_map=tiles_map,
                water_map=water_map,
                levels_map=levels_map,
                climbs_map=climbs_map,
            ):
                continue
            land.add(neighbor)
    return land


def _set_rotation(objects: list[dict[str, Any]], object_id: int, rotation: int) -> None:
    for group in objects:
        ids = group.get("ids") or []
        rotations = group.get("rotations") or []
        if object_id not in ids:
            continue
        index = ids.index(object_id)
        if index >= len(rotations):
            raise ValueError(f"object {object_id} missing rotation slot")
        rotations[index] = rotation
        return
    raise ValueError(f"object {object_id} not found for gate-face rotation")


def _object_emitted(objects: list[dict[str, Any]], object_id: int) -> bool:
    for group in objects:
        ids = group.get("ids") or []
        if object_id in ids:
            return True
    return False


def apply_single_gate_face_rotations(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    tiles_map: list[int],
    water_map: list[int] | None = None,
    levels_map: list[int] | None = None,
    climbs_map: list[int] | None = None,
    width: int | None = None,
    height: int | None = None,
    objects_properties: dict[str, Any] | None = None,
    clearable_object_ids: set[int] | None = None,
    relocation_region_width: int | None = None,
    max_relocation_radius: int = 0,
) -> dict[str, Any]:
    """Mutate object rotations so eligible gated faces get a free approach.

    Fail-closed: raises if an eligible object remains without a free approach after
    trying every Olden mirror rotation candidate, scenery clear, and void carve.

    Enemy stacks / hero-spawners are ignored when measuring approach freeness.
    """
    width = int(width if width is not None else single.OLDEN_WIDTH)
    height = int(height if height is not None else single.OLDEN_HEIGHT)
    water = list(water_map or [0] * (width * height))
    if len(tiles_map) != width * height:
        raise ValueError(
            f"tilesMap length {len(tiles_map)} != atlas cells {width}x{height}"
        )
    if len(water) != width * height:
        raise ValueError(
            f"waterMap length {len(water)} != atlas cells {width}x{height}"
        )

    # gate_nodes_for_object_instance / occupied_nodes_for_object_instance read
    # single.OLDEN_WIDTH/HEIGHT. Raw layered atlases are wider than the surface
    # 80x80 constants; patch for this pass so late (post-context) calls stay correct.
    previous_w, previous_h = single.OLDEN_WIDTH, single.OLDEN_HEIGHT
    single.OLDEN_WIDTH = width
    single.OLDEN_HEIGHT = height
    try:
        return _apply_single_gate_face_rotations_body(
            objects,
            native_object_configs,
            tiles_map=tiles_map,
            water=water,
            levels_map=levels_map,
            climbs_map=climbs_map,
            width=width,
            height=height,
            objects_properties=objects_properties,
            clearable_object_ids=set(clearable_object_ids or ()),
            relocation_region_width=int(relocation_region_width or width),
            max_relocation_radius=int(max_relocation_radius),
        )
    finally:
        single.OLDEN_WIDTH = previous_w
        single.OLDEN_HEIGHT = previous_h


def _apply_single_gate_face_rotations_body(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    tiles_map: list[int],
    water: list[int],
    levels_map: list[int] | None,
    climbs_map: list[int] | None,
    width: int,
    height: int,
    objects_properties: dict[str, Any] | None = None,
    clearable_object_ids: set[int],
    relocation_region_width: int,
    max_relocation_radius: int,
) -> dict[str, Any]:
    inspected = 0
    already_ok: list[dict[str, Any]] = []
    rotated: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    skipped_water_exempt = 0
    skipped_ineligible = 0
    skipped_terrain_sealed = 0
    skipped_portal_approach_sealed = 0
    skipped_cleared_during_pass = 0
    terrain_sealed_examples: list[dict[str, Any]] = []
    portal_approach_sealed_examples: list[dict[str, Any]] = []

    for group in objects:
        sid = group.get("sid")
        if not isinstance(sid, str):
            continue
        config = native_object_configs.get(sid)
        if not isinstance(config, dict):
            continue
        if sid in WATER_GATE_EXEMPT_SIDS:
            skipped_water_exempt += len(group.get("ids") or [])
            continue
        if not is_eligible_gated_mirror_object(sid, config):
            skipped_ineligible += len(group.get("ids") or [])
            continue

        ids = group.get("ids") or []
        nodes = group.get("nodes") or []
        rotations = group.get("rotations") or []
        if not (len(ids) == len(nodes) == len(rotations)):
            raise ValueError(f"object group length mismatch for {sid}")

        for object_id, anchor, current_rotation in zip(ids, nodes, rotations):
            if not isinstance(object_id, int) or not isinstance(anchor, int):
                continue
            inspected += 1
            current = int(current_rotation or 0)
            foreign = _build_foreign_occupied(
                objects, native_object_configs, exclude_object_id=object_id
            )
            current_approaches = free_cardinal_approaches(
                sid,
                config,
                anchor,
                current,
                foreign_occupied=foreign,
                tiles_map=tiles_map,
                water_map=water,
                width=width,
                height=height,
                    levels_map=levels_map,
                    climbs_map=climbs_map,
            )
            if current_approaches:
                already_ok.append(
                    {
                        "objectId": object_id,
                        "sid": sid,
                        "node": anchor,
                        "rotation": current,
                        "approachCount": len(current_approaches),
                    }
                )
                continue

            try_order = [current] + [r for r in ROTATION_CANDIDATES if r != current]
            # Water/void-sealed footprints cannot gain a land approach by mirroring
            # alone. Underground portals often sit against Void/elevated rock on every
            # face — carve void neighbors into Burrow before giving up as terrain-sealed
            # (otherwise carve below is unreachable when landNeighborCount is 0).
            land_by_rotation = {
                candidate: land_cardinal_neighbors(
                    sid,
                    config,
                    anchor,
                    candidate,
                    tiles_map=tiles_map,
                    water_map=water,
                    width=width,
                    height=height,
                    levels_map=levels_map,
                    climbs_map=climbs_map,
                )
                for candidate in try_order
            }
            carved_early: list[dict[str, Any]] = []
            if not any(land_by_rotation.values()):
                carved_early = _carve_void_burrow_approaches(
                    sid=sid,
                    config=config,
                    anchor=anchor,
                    rotations=try_order,
                    tiles_map=tiles_map,
                    water=water,
                    levels_map=levels_map,
                    climbs_map=climbs_map,
                    width=width,
                    height=height,
                )
                if carved_early:
                    land_by_rotation = {
                        candidate: land_cardinal_neighbors(
                            sid,
                            config,
                            anchor,
                            candidate,
                            tiles_map=tiles_map,
                            water_map=water,
                            width=width,
                            height=height,
                            levels_map=levels_map,
                            climbs_map=climbs_map,
                        )
                        for candidate in try_order
                    }
            if not any(land_by_rotation.values()):
                skipped_terrain_sealed += 1
                if len(terrain_sealed_examples) < 20:
                    terrain_sealed_examples.append(
                        {
                            "objectId": object_id,
                            "sid": sid,
                            "node": anchor,
                            "fromRotation": current,
                            "reason": "no_land_cardinal_neighbor_any_rotation",
                            "carvedVoidApproaches": carved_early,
                        }
                    )
                continue

            chosen: int | None = None
            chosen_approaches: set[int] = set()
            attempts: list[dict[str, Any]] = []
            for candidate in try_order:
                approaches = free_cardinal_approaches(
                    sid,
                    config,
                    anchor,
                    candidate,
                    foreign_occupied=foreign,
                    tiles_map=tiles_map,
                    water_map=water,
                    width=width,
                    height=height,
                    levels_map=levels_map,
                    climbs_map=climbs_map,
                )
                gates = sorted(
                    single.gate_nodes_for_object_instance(sid, config, anchor, candidate)
                )
                attempts.append(
                    {
                        "rotation": candidate,
                        "gateNodes": gates,
                        "approachCount": len(approaches),
                        "approaches": sorted(approaches),
                        "landNeighborCount": len(land_by_rotation.get(candidate) or []),
                    }
                )
                if approaches and chosen is None:
                    chosen = candidate
                    chosen_approaches = approaches

            if chosen is None:
                cleared = _clear_suppressible_approach_blockers(
                    objects,
                    native_object_configs,
                    sid=sid,
                    config=config,
                    anchor=anchor,
                    rotations=try_order,
                    exclude_object_id=object_id,
                    tiles_map=tiles_map,
                    water=water,
                    width=width,
                    height=height,
                    properties=objects_properties,
                    clearable_object_ids=clearable_object_ids,
                    levels_map=levels_map,
                    climbs_map=climbs_map,
                )
                carved: list[dict[str, Any]] = list(carved_early)
                if cleared:
                    foreign = _build_foreign_occupied(
                        objects, native_object_configs, exclude_object_id=object_id
                    )
                    retry_attempts: list[dict[str, Any]] = []
                    for candidate in try_order:
                        approaches = free_cardinal_approaches(
                            sid,
                            config,
                            anchor,
                            candidate,
                            foreign_occupied=foreign,
                            tiles_map=tiles_map,
                            water_map=water,
                            width=width,
                            height=height,
                    levels_map=levels_map,
                    climbs_map=climbs_map,
                        )
                        gates = sorted(
                            single.gate_nodes_for_object_instance(
                                sid, config, anchor, candidate
                            )
                        )
                        retry_attempts.append(
                            {
                                "rotation": candidate,
                                "gateNodes": gates,
                                "approachCount": len(approaches),
                                "approaches": sorted(approaches),
                                "afterSceneryClear": True,
                            }
                        )
                        if approaches and chosen is None:
                            chosen = candidate
                            chosen_approaches = approaches
                    attempts.extend(retry_attempts)
                if chosen is None:
                    late_carved = _carve_void_burrow_approaches(
                        sid=sid,
                        config=config,
                        anchor=anchor,
                        rotations=try_order,
                        tiles_map=tiles_map,
                        water=water,
                        levels_map=levels_map,
                        climbs_map=climbs_map,
                        width=width,
                        height=height,
                    )
                    if late_carved:
                        carved.extend(late_carved)
                        foreign = _build_foreign_occupied(
                            objects, native_object_configs, exclude_object_id=object_id
                        )
                        carve_attempts: list[dict[str, Any]] = []
                        for candidate in try_order:
                            approaches = free_cardinal_approaches(
                                sid,
                                config,
                                anchor,
                                candidate,
                                foreign_occupied=foreign,
                                tiles_map=tiles_map,
                                water_map=water,
                                width=width,
                                height=height,
                    levels_map=levels_map,
                    climbs_map=climbs_map,
                            )
                            gates = sorted(
                                single.gate_nodes_for_object_instance(
                                    sid, config, anchor, candidate
                                )
                            )
                            carve_attempts.append(
                                {
                                    "rotation": candidate,
                                    "gateNodes": gates,
                                    "approachCount": len(approaches),
                                    "approaches": sorted(approaches),
                                    "afterVoidCarve": True,
                                }
                            )
                            if approaches and chosen is None:
                                chosen = candidate
                                chosen_approaches = approaches
                        attempts.extend(carve_attempts)
                nonkeeper_cleared: list[dict[str, Any]] = []
                if chosen is None:
                    nonkeeper_cleared = _clear_nonkeeper_portal_approach_blockers(
                        objects,
                        native_object_configs,
                        sid=sid,
                        config=config,
                        anchor=anchor,
                        rotations=try_order,
                        exclude_object_id=object_id,
                        width=width,
                        height=height,
                        properties=objects_properties,
                    )
                    if nonkeeper_cleared:
                        foreign = _build_foreign_occupied(
                            objects, native_object_configs, exclude_object_id=object_id
                        )
                        nonkeeper_attempts: list[dict[str, Any]] = []
                        for candidate in try_order:
                            approaches = free_cardinal_approaches(
                                sid,
                                config,
                                anchor,
                                candidate,
                                foreign_occupied=foreign,
                                tiles_map=tiles_map,
                                water_map=water,
                                width=width,
                                height=height,
                    levels_map=levels_map,
                    climbs_map=climbs_map,
                            )
                            gates = sorted(
                                single.gate_nodes_for_object_instance(
                                    sid, config, anchor, candidate
                                )
                            )
                            nonkeeper_attempts.append(
                                {
                                    "rotation": candidate,
                                    "gateNodes": gates,
                                    "approachCount": len(approaches),
                                    "approaches": sorted(approaches),
                                    "afterNonkeeperClear": True,
                                }
                            )
                            if approaches and chosen is None:
                                chosen = candidate
                                chosen_approaches = approaches
                        attempts.extend(nonkeeper_attempts)
                relocation: dict[str, Any] | None = None
                if chosen is None and clearable_object_ids and max_relocation_radius > 0:
                    relocation = _relocate_gated_object(
                        objects,
                        native_object_configs,
                        object_id=object_id,
                        sid=sid,
                        config=config,
                        anchor=anchor,
                        rotations=try_order,
                        clearable_object_ids=clearable_object_ids,
                        tiles_map=tiles_map,
                        water=water,
                        width=width,
                        height=height,
                        region_width=relocation_region_width,
                        max_radius=max_relocation_radius,
                        properties=objects_properties,
                        levels_map=levels_map,
                        climbs_map=climbs_map,
                    )
                    if relocation is not None:
                        chosen = int(relocation["rotation"])
                        chosen_approaches = set(relocation["approaches"])
                if chosen is not None:
                    if not _object_emitted(objects, object_id):
                        # Cleared as a blocker for an earlier gate in this same pass.
                        skipped_cleared_during_pass += 1
                        continue
                    if relocation is None and chosen != current:
                        _set_rotation(objects, object_id, chosen)
                    rotated.append(
                        {
                            "objectId": object_id,
                            "sid": sid,
                            "node": anchor,
                            "fromRotation": current,
                            "toRotation": chosen,
                            "approachCount": len(chosen_approaches),
                            "approaches": sorted(chosen_approaches),
                            "attempts": attempts,
                            "clearedApproachBlockers": cleared,
                            "carvedVoidApproaches": carved,
                            "nonkeeperCleared": nonkeeper_cleared,
                            "relocation": relocation,
                            "clearedRelocationBlockers": (
                                relocation.get("clearedRelocationBlockers", [])
                                if relocation is not None
                                else []
                            ),
                        }
                    )
                    continue

                sealed_row = {
                    "objectId": object_id,
                    "sid": sid,
                    "node": anchor,
                    "fromRotation": current,
                    "attempts": attempts,
                    "clearedApproachBlockers": cleared,
                    "carvedVoidApproaches": carved,
                    "nonkeeperCleared": nonkeeper_cleared,
                }
                if _is_portal_soft_unresolved_sid(sid):
                    skipped_portal_approach_sealed += 1
                    if len(portal_approach_sealed_examples) < 20:
                        portal_approach_sealed_examples.append(
                            {
                                **sealed_row,
                                "reason": "portal_keeper_or_functional_approach_seal_soft_skip",
                            }
                        )
                    continue
                unresolved.append(sealed_row)
                continue

            if chosen != current:
                if not _object_emitted(objects, object_id):
                    skipped_cleared_during_pass += 1
                    continue
                _set_rotation(objects, object_id, chosen)
            rotated.append(
                {
                    "objectId": object_id,
                    "sid": sid,
                    "node": anchor,
                    "fromRotation": current,
                    "toRotation": chosen,
                    "approachCount": len(chosen_approaches),
                    "approaches": sorted(chosen_approaches),
                    "attempts": attempts,
                    "carvedVoidApproaches": carved_early,
                }
            )

    # Fail-open: report unresolved sealed faces but do not abort map emit. Approach
    # freeness remains best-effort after rotation + scenery clear + void carve.
    soft_unresolved = list(unresolved)
    unresolved.clear()

    _assert_objects_pack_arrays_consistent(objects)
    if objects_properties is not None:
        # Object-namespace only. Type-1 Zone marker props are owned by markers[]
        # (often temp ids 0..n-1 before rebase) and must survive this late pass.
        propns.scrub_orphan_object_namespace_properties(
            objects_properties,
            live_object_ids=propns.live_object_ids(objects),
        )

    status = STATUS
    if soft_unresolved:
        status = "generated_artifact_with_unresolved_approaches_validator_runtime_unvalidated"

    return {
        "status": status,
        "policy": POLICY,
        "legacyPolicy": LEGACY_POLICY,
        "phase": PHASE,
        "timing": (
            "after_layered_emit_gap_fill_landon_access_post_landon_gap_fill_"
            "and_envelope_padding_cliffs"
        ),
        "rotationCandidates": list(ROTATION_CANDIDATES),
        "relocationPolicy": RELOCATION_POLICY,
        "maxRelocationRadius": max_relocation_radius,
        "relocationRegionWidth": relocation_region_width,
        "eligibility": {
            "requireAtLeastOneGate": True,
            "requireCanBeMirrored": True,
            "maxFootprintCells": None,
            "requireExactlyOneGate": False,
            "requireAtLeastOneEmptyCell": False,
            "waterGateExemptSids": sorted(WATER_GATE_EXEMPT_SIDS),
            "enemyNonblockingSids": sorted(ENEMY_NONBLOCKING_SIDS),
            "blockerPolicy": (
                "scenery_and_buildings_block_enemies_and_hero_spawners_ignored"
            ),
            "terrainSealedSkipPolicy": (
                "carve_void_neighbors_then_skip_when_no_land_cardinal_neighbor_any_rotation"
            ),
            "portalSoftUnresolvedPolicy": (
                "soft_skip_portal_prefix_when_still_sealed_after_rotation_clear_carve; "
                "homm3_subterranean_gate_portal_fail_closed"
            ),
            "unresolvedApproachPolicy": (
                "fail_open_report_unresolved_after_rotation_clear_carve_without_aborting_emit"
            ),
            "visitBankGateExemptPrefixes": list(VISIT_BANK_GATE_EXEMPT_PREFIXES),
            "portalSoftUnresolvedPrefixes": list(PORTAL_SOFT_UNRESOLVED_PREFIXES),
            "subterraneanGateFailClosedSids": sorted(SUBTERRANEAN_GATE_FAIL_CLOSED_SIDS),
        },
        "inspectedCount": inspected,
        "alreadyOkCount": len(already_ok),
        "rotatedCount": len(rotated),
        "rotated": rotated,
        "skippedWaterExemptInstanceCount": skipped_water_exempt,
        "skippedIneligibleInstanceCount": skipped_ineligible,
        "skippedTerrainSealedInstanceCount": skipped_terrain_sealed,
        "skippedPortalApproachSealedInstanceCount": skipped_portal_approach_sealed,
        "skippedClearedDuringPassInstanceCount": skipped_cleared_during_pass,
        "terrainSealedExamples": terrain_sealed_examples,
        "portalApproachSealedExamples": portal_approach_sealed_examples,
        "unresolvedCount": len(soft_unresolved),
        "unresolvedExamples": soft_unresolved[:20],
        "proofBoundary": (
            "generated_artifact; runtime clickability of rotated GATE faces remains "
            "user-unvalidated"
        ),
    }
