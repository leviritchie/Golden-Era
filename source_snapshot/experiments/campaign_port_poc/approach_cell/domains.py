#!/usr/bin/env python3
"""Domain tags and choke edges for approach_cell (not a movement-graph product)."""
from __future__ import annotations

from typing import Any

import layer_atlas as atlas

DOMAIN_LAND = "land"
DOMAIN_WATER_BOAT = "water_boat"
DOMAIN_LAYER0 = "layer0"
DOMAIN_LAYER1 = "layer1"

CHOKE_SHORE_BOAT = "shore_boat"
CHOKE_SUBTERRANEAN_GATE = "subterranean_gate"


def layer_for_node(node: int) -> int:
    """Return atlas layer id for a flat node (surface left, underground right)."""
    width = atlas.OLDEN_WIDTH
    x = node % width
    for layer, spec in atlas.LAYER_SPECS.items():
        offset_x = int(spec["offsetX"])
        # Each view is an 80-wide sector; surface at 0, underground at 80.
        view = spec.get("view") or {}
        sec_size = int(view.get("secSizeX") or 5) * 16
        if offset_x <= x < offset_x + sec_size:
            return int(layer)
    # Fallback: left half surface, right half underground.
    return 0 if x < width // 2 else 1


def domain_tag_for_cell(node: int, *, water_map: list[int], tiles_map: list[int]) -> str:
    if not (0 <= node < len(water_map)):
        raise ValueError(f"node out of range for domain tag: {node}")
    if int(water_map[node] or 0) != 0:
        return DOMAIN_WATER_BOAT
    return DOMAIN_LAND


def build_domain_grid(*, water_map: list[int], tiles_map: list[int]) -> list[str]:
    if len(water_map) != atlas.OLDEN_WIDTH * atlas.OLDEN_HEIGHT:
        raise ValueError("water_map size mismatch for domain grid")
    return [domain_tag_for_cell(node, water_map=water_map, tiles_map=tiles_map) for node in range(len(water_map))]


CARDINAL_OFFSETS = ((1, 0), (-1, 0), (0, 1), (0, -1))
DIAGONAL_OFFSETS = ((1, 1), (1, -1), (-1, 1), (-1, -1))
EIGHT_OFFSETS = CARDINAL_OFFSETS + DIAGONAL_OFFSETS


def neighbors_with(
    node: int,
    offsets: tuple[tuple[int, int], ...],
    *,
    grid_width: int | None = None,
    grid_height: int | None = None,
) -> list[int]:
    width = atlas.OLDEN_WIDTH if grid_width is None else grid_width
    height = atlas.OLDEN_HEIGHT if grid_height is None else grid_height
    x = node % width
    y = node // width
    out: list[int] = []
    for dx, dy in offsets:
        nx, ny = x + dx, y + dy
        if 0 <= nx < width and 0 <= ny < height:
            out.append(ny * width + nx)
    return out


def neighbors4(
    node: int,
    *,
    grid_width: int | None = None,
    grid_height: int | None = None,
) -> list[int]:
    return neighbors_with(node, CARDINAL_OFFSETS, grid_width=grid_width, grid_height=grid_height)


def neighbors8(
    node: int,
    *,
    grid_width: int | None = None,
    grid_height: int | None = None,
) -> list[int]:
    return neighbors_with(node, EIGHT_OFFSETS, grid_width=grid_width, grid_height=grid_height)


def step_offsets(
    from_node: int,
    to_node: int,
    *,
    grid_width: int | None = None,
) -> tuple[int, int] | None:
    """Return (dx, dy) for an adjacent step on grid_width (default: atlas OLDEN_WIDTH).

    Callers on the surface-only 80x80 catalogue grid must pass grid_width=80.
    Using atlas width (160) on 80-wide node ids rejects vertical steps and
    falsely treats row wraps as adjacent.
    """
    width = atlas.OLDEN_WIDTH if grid_width is None else grid_width
    fx, fy = from_node % width, from_node // width
    tx, ty = to_node % width, to_node // width
    dx, dy = tx - fx, ty - fy
    if dx == 0 and dy == 0:
        return None
    if abs(dx) > 1 or abs(dy) > 1:
        return None
    return dx, dy


def can_step_with_diagonal_squeeze(
    from_node: int,
    to_node: int,
    *,
    blocked: set[int],
    grid_width: int | None = None,
) -> bool:
    """True when a hero can step from->to under 8-dir squeeze rules.

    Cardinal: destination must not be blocked.
    Diagonal: origin and destination clear; corner tiles may be blocked
    (squeeze between blocked tiles). Origin is assumed clear by caller.

    grid_width defaults to atlas OLDEN_WIDTH. Surface 80x80 BFS must pass 80.
    """
    if to_node in blocked:
        return False
    offsets = step_offsets(from_node, to_node, grid_width=grid_width)
    if offsets is None:
        return False
    dx, dy = offsets
    if dx == 0 or dy == 0:
        return True
    # Diagonal squeeze: only origin+destination need to be clear.
    return from_node not in blocked


def diagonal_squeeze_corridor_cells(
    blocked: set[int],
    *,
    grid_width: int,
    grid_height: int,
) -> set[int]:
    """Open cells that participate in a diagonal squeeze between two blocked corners.

    Olden's pathfinder allows those diagonal steps; lens paints them so "pathable"
    walls with sneak corridors are visible. O(N) over the grid.
    """
    marks: set[int] = set()
    for node in range(grid_width * grid_height):
        if node in blocked:
            continue
        x = node % grid_width
        y = node // grid_width
        for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < grid_width and 0 <= ny < grid_height):
                continue
            dest = ny * grid_width + nx
            if dest in blocked:
                continue
            corner_a = y * grid_width + nx
            corner_b = ny * grid_width + x
            if corner_a in blocked or corner_b in blocked:
                marks.add(node)
                marks.add(dest)
    return marks


def build_choke_edges(
    *,
    water_map: list[int],
    objects: list[dict[str, Any]],
    portal_targets: dict[int, int] | None = None,
) -> list[dict[str, Any]]:
    """Explicit shore/boat and subterranean-gate choke edges only."""
    edges: list[dict[str, Any]] = []
    domain_grid = build_domain_grid(water_map=water_map, tiles_map=[0] * len(water_map))
    seen_shore: set[tuple[int, int]] = set()
    for node, domain in enumerate(domain_grid):
        if domain != DOMAIN_WATER_BOAT:
            continue
        for nxt in neighbors4(node):
            if domain_grid[nxt] != DOMAIN_LAND:
                continue
            key = (min(node, nxt), max(node, nxt))
            if key in seen_shore:
                continue
            seen_shore.add(key)
            edges.append({
                "kind": CHOKE_SHORE_BOAT,
                "a": key[0],
                "b": key[1],
                "layerA": layer_for_node(key[0]),
                "layerB": layer_for_node(key[1]),
            })

    # Subterranean gates: object pairs from portal targets.
    id_to_node: dict[int, int] = {}
    id_to_sid: dict[int, str] = {}
    for group in objects:
        sid = str(group.get("sid") or "")
        for object_id, node in zip(group.get("ids") or [], group.get("nodes") or []):
            if isinstance(object_id, int) and isinstance(node, int):
                id_to_node[object_id] = node
                id_to_sid[object_id] = sid
    if portal_targets:
        seen_gates: set[tuple[int, int]] = set()
        gate_sid = atlas.SUBTERRANEAN_GATE_PORTAL_SID
        for src, dst in portal_targets.items():
            if id_to_sid.get(src) != gate_sid:
                continue
            if id_to_sid.get(dst) != gate_sid:
                continue
            key = (min(src, dst), max(src, dst))
            if key in seen_gates:
                continue
            seen_gates.add(key)
            edges.append({
                "kind": CHOKE_SUBTERRANEAN_GATE,
                "objectA": key[0],
                "objectB": key[1],
                "nodeA": id_to_node.get(key[0]),
                "nodeB": id_to_node.get(key[1]),
                "layerA": layer_for_node(id_to_node[key[0]]) if key[0] in id_to_node else None,
                "layerB": layer_for_node(id_to_node[key[1]]) if key[1] in id_to_node else None,
            })
    return edges


def is_mountain_or_hard_blocker_sid(sid: str) -> bool:
    if sid.startswith("mountain_"):
        return True
    if sid in {"homm3_pathing_blocker", "homm3_envelope_padding_blocker"} or sid.startswith("homm3_pathing_"):
        return True
    return False


def cell_is_water_domain(node: int, water_map: list[int]) -> bool:
    return 0 <= node < len(water_map) and int(water_map[node] or 0) != 0
