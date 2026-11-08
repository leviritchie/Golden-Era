#!/usr/bin/env python3
"""Campaign-safe accessibility pass: unseal interactable step-here tiles and H3-open floor.

Clears suppressible scenery (plus gap-fill / pathing blockers / homm3_xfp_s_*) that
sits on:

- Olden GATE cells (ObjectConfig nodes value 2) of non-scenery hosts
- HoMM3 ground-truth walkable cells (passable terrain, not a non-visitable block)

Does not mutate waterMap, levelsMap, climbsMap, ocean basins, shoreline rivers,
or inland-river-as-waterMap. Does not relocate pickups or functional objects.

Functional objects occupying a GATE cell are reported as unresolved and left in
place. Leftover suppressible occupancy of GATE cells or H3-open floor fails closed.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

_PKG = Path(__file__).resolve().parent
_POC = _PKG.parent
_APPROACH = _POC / "approach_cell"
for _path in (_PKG, _POC, _APPROACH):
    text = str(_path)
    if text not in sys.path:
        sys.path.insert(0, text)

import functional_emit_reservation as fer
import h3m_scenario_translation as scenario
import object_property_namespaces as propns
import surface_emit as single

SCHEMA = "homm3.raw_translation.entrance_occupancy.v1"
STATUS_APPLIED = "applied"
PROOF_BOUNDARY = "generated_artifact_runtime_unvalidated"
POLICY = (
    "clear_suppressible_on_interactable_gate_cells_and_h3_open_floor;"
    "do_not_mutate_waterMap_levelsMap_climbsMap_or_ocean_geometry"
)
H3_WATER_TERRAIN_ID = 8
H3_ROCK_TERRAIN_ID = scenario.H3_UNDERGROUND_ROCK_TERRAIN_ID
H3_IMPASSABLE_TERRAIN_IDS = frozenset({H3_WATER_TERRAIN_ID, H3_ROCK_TERRAIN_ID})

_CLEARABLE_SIDS = frozenset(
    set(fer.SUPPRESSIBLE_SOURCE_SCENERY_SIDS)
    | {
        single.HOMM3_PATHING_GAP_FILL_VISIBLE_SID,
        single.HOMM3_PATHING_BLOCKER_SID,
    }
)

LayerTargetNode = Callable[[int, int, int], int]


def is_clearable_sid(sid: str) -> bool:
    return sid in _CLEARABLE_SIDS or str(sid).startswith("homm3_xfp_s_")


def _iter_instances(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
):
    for group in objects:
        if not isinstance(group, dict):
            continue
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
            yield sid, config, object_id, node, int(rotation or 0)


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
        if levels:
            group["levels"] = [levels[i] for i in keep if i < len(levels)]
    objects[:] = [
        group
        for group in objects
        if isinstance(group, dict) and (group.get("ids") or [])
    ]
    propns.remove_object_property_rows(properties, remove_ids)


def _instance_occupancy(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
) -> list[tuple[int, str, set[int]]]:
    """(object id, sid, occupied cells) in object order; recompute after objects change."""
    return [
        (object_id, sid, single.occupied_nodes_for_object_instance(sid, config, node, rotation))
        for sid, config, object_id, node, rotation in _iter_instances(objects, native_object_configs)
    ]


def _owners_covering_nodes(
    occupancy: list[tuple[int, str, set[int]]],
    nodes: set[int],
    *,
    exclude_object_ids: set[int],
) -> list[tuple[int, str]]:
    return [
        (object_id, sid)
        for object_id, sid, occupied in occupancy
        if object_id not in exclude_object_ids and occupied & nodes
    ]


def _layer_source_size(map_data: dict[str, Any]) -> tuple[int, int]:
    tiles = map_data.get("tilesMap") or []
    size_x = map_data.get("sizeX_")
    size_z = map_data.get("sizeZ_")
    if not isinstance(size_x, int):
        size_x = map_data.get("sizeX")
    if not isinstance(size_z, int):
        size_z = map_data.get("sizeZ")
    if (
        isinstance(size_x, int)
        and isinstance(size_z, int)
        and size_x > 0
        and size_z > 0
        and isinstance(tiles, list)
        and len(tiles) == size_x * size_z
    ):
        return size_x, size_z
    raise ValueError(
        "entrance_occupancy cannot read H3 layer size from tilesMap/"
        f"sizeX_/sizeZ_ (sizeX_={size_x!r} sizeZ_={size_z!r} tiles={len(tiles) if isinstance(tiles, list) else type(tiles)})"
    )


def _in_source_bounds(x: int, y: int, width: int, height: int) -> bool:
    return 0 <= x < width and 0 <= y < height


def build_h3_ground_truth_walkable_nodes(
    *,
    layered_map_data: list[dict[str, Any]],
    global_entities: list[dict[str, Any]],
    layer_target_node: LayerTargetNode,
    source_width: int,
    source_height: int,
) -> set[int]:
    """Olden nodes that correspond to HoMM3-walkable source floor.

    Walkable = H3 terrain is not water (8) or rock (9), and the cell is not in
    any in-bounds non-visitable H3 block mask. Visitable cells stay walkable.
    Coastline / ocean tiles are terrain 8, so they are never in this set.
    """
    blocked: set[tuple[int, int, int]] = set()
    layer_sizes: dict[int, tuple[int, int]] = {}
    for entry in layered_map_data:
        if not isinstance(entry, dict):
            continue
        layer = entry.get("layer")
        map_data = entry.get("mapData")
        if not isinstance(layer, int) or not isinstance(map_data, dict):
            continue
        width, height = _layer_source_size(map_data)
        layer_sizes[layer] = (width, height)

    for entity in global_entities:
        if not isinstance(entity, dict):
            continue
        layer = entity.get("sourceLayer")
        source_x = entity.get("sourceX")
        source_y = entity.get("sourceY")
        if not isinstance(layer, int) or not isinstance(source_x, int) or not isinstance(source_y, int):
            continue
        width, height = layer_sizes.get(layer, (source_width, source_height))
        for dx, dy in single.entity_nonvisitable_block_offsets(entity):
            cell_x = source_x + dx
            cell_y = source_y + dy
            if _in_source_bounds(cell_x, cell_y, width, height):
                blocked.add((layer, cell_x, cell_y))

    walkable: set[int] = set()
    for entry in layered_map_data:
        if not isinstance(entry, dict):
            continue
        layer = entry.get("layer")
        map_data = entry.get("mapData")
        if not isinstance(layer, int) or not isinstance(map_data, dict):
            continue
        tiles = map_data.get("tilesMap") or []
        width, height = layer_sizes[layer]
        for source_y in range(height):
            for source_x in range(width):
                index = source_y * width + source_x
                if index >= len(tiles):
                    continue
                try:
                    terrain = int(tiles[index])
                except (TypeError, ValueError):
                    continue
                if terrain in H3_IMPASSABLE_TERRAIN_IDS:
                    continue
                if (layer, source_x, source_y) in blocked:
                    continue
                try:
                    walkable.add(int(layer_target_node(layer, source_x, source_y)))
                except (TypeError, ValueError):
                    continue
    return walkable


def collect_entrance_hosts(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    hosts: list[dict[str, Any]] = []
    for sid, config, object_id, node, rotation in _iter_instances(
        objects, native_object_configs
    ):
        if is_clearable_sid(sid) or single.is_homm3_pathing_visual_sid(sid):
            continue
        gates = single.gate_nodes_for_object_instance(sid, config, node, rotation)
        if not gates:
            continue
        hosts.append(
            {
                "objectId": object_id,
                "sid": sid,
                "gates": gates,
            }
        )
    return hosts


def apply_raw_translation_accessibility_pass(
    *,
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    object_properties: dict[str, Any] | None,
    global_entities: list[dict[str, Any]],
    layered_map_data: list[dict[str, Any]],
    layer_target_node: LayerTargetNode,
    width: int,
    height: int,
    source_width: int,
    source_height: int,
    map_sid: str,
) -> dict[str, Any]:
    """Delete suppressible scenery sealing GATE cells or H3-open floor. In-place."""
    previous_w, previous_h = single.OLDEN_WIDTH, single.OLDEN_HEIGHT
    single.OLDEN_WIDTH = width
    single.OLDEN_HEIGHT = height
    try:
        hosts = collect_entrance_hosts(objects, native_object_configs)
        entrance_cells: set[int] = set()
        host_ids: set[int] = set()
        for host in hosts:
            entrance_cells.update(host["gates"])
            host_ids.add(int(host["objectId"]))

        h3_walkable = build_h3_ground_truth_walkable_nodes(
            layered_map_data=layered_map_data,
            global_entities=global_entities,
            layer_target_node=layer_target_node,
            source_width=source_width,
            source_height=source_height,
        )

        remove_ids: set[int] = set()
        cleared: list[dict[str, Any]] = []
        occupancy = _instance_occupancy(objects, native_object_configs)

        for host in hosts:
            for object_id, owner_sid in _owners_covering_nodes(
                occupancy,
                host["gates"],
                exclude_object_ids={int(host["objectId"])},
            ):
                if not is_clearable_sid(owner_sid):
                    continue
                if object_id in remove_ids:
                    continue
                remove_ids.add(object_id)
                cleared.append(
                    {
                        "objectId": object_id,
                        "sid": owner_sid,
                        "reason": "suppressible_on_interactable_gate_cell",
                        "hostObjectId": host["objectId"],
                        "hostSid": host["sid"],
                    }
                )

        for object_id, owner_sid in _owners_covering_nodes(
            occupancy,
            h3_walkable,
            exclude_object_ids=set(),
        ):
            if not is_clearable_sid(owner_sid):
                continue
            if object_id in remove_ids:
                continue
            remove_ids.add(object_id)
            cleared.append(
                {
                    "objectId": object_id,
                    "sid": owner_sid,
                    "reason": "suppressible_sealing_h3_open_floor",
                }
            )

        _remove_object_ids(objects, remove_ids, object_properties)
        occupancy = _instance_occupancy(objects, native_object_configs)

        leftover: list[dict[str, Any]] = []
        leftover_ids: set[int] = set()
        for host in hosts:
            if int(host["objectId"]) in remove_ids:
                continue
            for object_id, owner_sid in _owners_covering_nodes(
                occupancy,
                host["gates"],
                exclude_object_ids={int(host["objectId"])},
            ):
                if is_clearable_sid(owner_sid) and object_id not in leftover_ids:
                    leftover_ids.add(object_id)
                    leftover.append(
                        {
                            "objectId": object_id,
                            "sid": owner_sid,
                            "reason": "leftover_suppressible_on_gate",
                        }
                    )
        for object_id, owner_sid in _owners_covering_nodes(
            occupancy,
            h3_walkable,
            exclude_object_ids=set(),
        ):
            if is_clearable_sid(owner_sid) and object_id not in leftover_ids:
                leftover_ids.add(object_id)
                leftover.append(
                    {
                        "objectId": object_id,
                        "sid": owner_sid,
                        "reason": "leftover_suppressible_on_h3_open_floor",
                    }
                )
        if leftover:
            sample = ", ".join(
                f"{row['sid']}:{row['objectId']}" for row in leftover[:8]
            )
            raise ValueError(
                "entrance_occupancy leftover suppressible scenery still occupies "
                f"GATE cells or H3-open floor: {sample}"
            )

        unresolved: list[dict[str, Any]] = []
        seen_unresolved: set[int] = set()
        for host in hosts:
            if int(host["objectId"]) in remove_ids:
                continue
            for object_id, owner_sid in _owners_covering_nodes(
                occupancy,
                host["gates"],
                exclude_object_ids={int(host["objectId"])},
            ):
                if is_clearable_sid(owner_sid):
                    continue
                if object_id in seen_unresolved:
                    continue
                seen_unresolved.add(object_id)
                unresolved.append(
                    {
                        "objectId": object_id,
                        "sid": owner_sid,
                        "reason": "non_suppressible_occupying_gate_cell",
                        "hostObjectId": host["objectId"],
                        "hostSid": host["sid"],
                    }
                )

        return {
            "schema": SCHEMA,
            "status": STATUS_APPLIED,
            "policy": POLICY,
            "proofBoundary": PROOF_BOUNDARY,
            "mapSid": map_sid,
            "entranceHostCount": len(hosts),
            "entranceCellCount": len(entrance_cells),
            "h3WalkableCellCount": len(h3_walkable),
            "clearedCount": len(cleared),
            "cleared": cleared,
            "unresolvedCount": len(unresolved),
            "unresolved": unresolved,
            "leftoverSuppressibleCount": 0,
        }
    finally:
        single.OLDEN_WIDTH = previous_w
        single.OLDEN_HEIGHT = previous_h
