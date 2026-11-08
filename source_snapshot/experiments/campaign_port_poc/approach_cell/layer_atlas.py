#!/usr/bin/env python3
"""Copied terrain/atlas projection leaves for approach_cell."""
from __future__ import annotations

from collections import Counter
import copy
import json
import os
import zipfile
from pathlib import Path
from typing import Any

import h3m_object_registry as h3obj
import h3m_scenario_translation as scenario
import port_homecoming_poc as poc
import surface_emit as single

SCHEMA = "homm3.olden_approach_cell_map.v1"
STATUS = "generated_runtime_unvalidated"
MAP_SID = "h3_roe_castle_homecoming_approach_cell"
TITLE = "Homecoming - Approach Cell"
DESCRIPTION = (
    "Parallel Homecoming generator: domain/choke topology and local single-approach-cell "
    "clears. Runtime gameplay remains user-unvalidated."
)

DEFAULT_INPUT_ROOT = Path(os.environ.get("HOMECOMING_POC_OUT_ROOT", single.DEFAULT_INPUT_ROOT))
OUT_ROOT = DEFAULT_INPUT_ROOT / "approach_cell_map"
ALIGNMENT_PATH = single.ALIGNMENT_PATH
SUBSTITUTION_PATH = single.SUBSTITUTION_PATH
CORE_CATALOG_PATH = single.CORE_CATALOG_PATH

SOURCE_WIDTH = 72
SOURCE_HEIGHT = 72
LAYER_LAYOUT = scenario.build_side_by_side_layer_atlas(
    source_width=SOURCE_WIDTH,
    source_height=SOURCE_HEIGHT,
    layer_ids=[0, 1],
    view_names={0: "surface", 1: "underground"},
    underground_layers={1},
)
OLDEN_WIDTH = LAYER_LAYOUT.atlas_width
OLDEN_HEIGHT = LAYER_LAYOUT.atlas_height
SOURCE_OFFSET_Y = LAYER_LAYOUT.source_offset_y
SURFACE_OFFSET_X = LAYER_LAYOUT.layers[0]["offsetX"]
UNDERGROUND_OFFSET_X = LAYER_LAYOUT.layers[1]["offsetX"]
VIEW_SECTOR_SIZE = LAYER_LAYOUT.sector_size
PADDING_TILE_ID = single.PADDING_TILE_ID
PADDING_WATER_ID = single.PADDING_WATER_ID
Y_AXIS_TRANSFORM = scenario.Y_AXIS_FLIP
LAYER_SPECS: dict[int, dict[str, Any]] = LAYER_LAYOUT.layers

H3_LAYER_TO_OLDEN_TILE: dict[int, dict[int, dict[str, Any]]] = {
    0: single.H3_SURFACE_TO_OLDEN_TILE,
    1: {
        # Underground can reuse surface terrain codes on AB/SoD maps (caves with
        # dirt/grass/lava pockets). Keep rock→Void and subterranean→Burrow; map
        # other land codes through the surface table so emit stays fail-closed only
        # on truly unknown ids.
        **single.H3_SURFACE_TO_OLDEN_TILE,
        scenario.H3_UNDERGROUND_SUBTERRANEAN_TERRAIN_ID: {
            "oldenId": scenario.OLDEN_BURROW_TILE_ID,
            "oldenBiome": "Burrow",
        },
        scenario.H3_UNDERGROUND_ROCK_TERRAIN_ID: {
            "oldenId": scenario.OLDEN_VOID_TILE_ID,
            "oldenBiome": "Void",
        },
        # Prefer Void for underground lava pockets (matches prior Tunnels contract).
        7: {"oldenId": scenario.OLDEN_VOID_TILE_ID, "oldenBiome": "Void"},
    },
}

H3_LAYER_RIVER_TO_OLDEN_WATER: dict[int, dict[int, dict[int, dict[str, Any]]]] = {
    0: single.H3_SURFACE_RIVER_TO_OLDEN_WATER_BY_TERRAIN,
    1: {
        **single.H3_SURFACE_RIVER_TO_OLDEN_WATER_BY_TERRAIN,
        scenario.H3_UNDERGROUND_SUBTERRANEAN_TERRAIN_ID: {
            1: {"oldenId": scenario.OLDEN_BURROW_TILE_ID, "oldenName": "water burrow"},
            # Lava river (4) in underground tunnels — same lossy burrow water channel.
            4: {"oldenId": scenario.OLDEN_BURROW_TILE_ID, "oldenName": "water burrow (lava river lossy)"},
        },
        # Tunnels: lava river overlays sit on H3 lava terrain (7), not only Burrow (6).
        7: {
            1: {"oldenId": scenario.OLDEN_BURROW_TILE_ID, "oldenName": "water burrow (lava clear-river lossy)"},
            4: {
                "oldenId": scenario.OLDEN_BURROW_TILE_ID,
                "oldenName": "water burrow (lava-terrain lava river lossy)",
            },
        },
    },
}

EXPECTED_LAYER_COUNTS = {0: 1453, 1: 400}
UNDERGROUND_TUNNEL_CLEARANCE_POLICY = "chebyshev_two_tile_elevation_shoulder_rock_to_burrow_clearance"
UNDERGROUND_TUNNEL_CLEARANCE_STATUS = "generated_static_2x2_elevation_buffer_validated_runtime_unvalidated"
UNDERGROUND_TUNNEL_CLEARANCE_RADIUS = 2
UNDERGROUND_TUNNEL_CLEARANCE_NEIGHBORHOOD = "chebyshev_8_neighbor"
UNDERGROUND_TUNNEL_CLEARANCE_DIRECTIONS = (
    (-1, -1), (0, -1), (1, -1),
    (-1, 0),           (1, 0),
    (-1, 1),  (0, 1),  (1, 1),
)
UNDERGROUND_PAYLOADLESS_SCENERY_SUPPRESSION_POLICY = "retired_emit_blocking_biome_scenery_instead"
UNDERGROUND_PAYLOADLESS_SCENERY_SUPPRESSION_STATUS = "generated_static_pathability_validated_runtime_unvalidated"
H3_OCEAN_WATER_TERRAIN_ID = 8
UNDERGROUND_WATER_TO_POND_SCENERY_POLICY = "underground_ocean_to_pond_scenery_unless_preserved"
UNDERGROUND_POND_SCENERY_SMALL_SID = "pool_dirt_small_1"
UNDERGROUND_POND_SCENERY_BIG_SID = "pool_dirt_big_1"
UNDERGROUND_POND_SCENERY_BIG_COMPONENT_MIN_TILES = 16
UNDERGROUND_POND_SCENERY_ID_BASE = 905_000
SUBTERRANEAN_GATE_PORTAL_SID = single.HOMM3_SUBTERRANEAN_GATE_PORTAL_SID
# Native one-/two-way monolith family (portal_1..5 and visual variants). Keep in
# sync with single.PORTAL_SIDS minus subterranean custom SID and portal_magic.
MONOLITH_PORTAL_SIDS = frozenset(
    sid
    for sid in single.PORTAL_SIDS
    if sid not in {SUBTERRANEAN_GATE_PORTAL_SID, "portal_magic"}
)
TRAVEL_LINK_PORTAL_SELECTION_BY_OBJECT_ID = {
    h3obj.OBJECT_SUBTERRANEAN_GATE: {
        "sid": SUBTERRANEAN_GATE_PORTAL_SID,
        "ruleName": "subterranean_gate_to_dungeon_entrance_portal",
        "visualFamily": "homm3_dungeon_entrance_portal",
        "reason": "Homecoming Core overlay defines a custom portal SID using Dungeon Entrance prefab",
    },
    h3obj.OBJECT_WHIRLPOOL: {
        "sid": "portal_magic",
        "ruleName": "whirlpool_to_magic_portal_same_layer",
        "visualFamily": "native_magic_portal",
        "reason": "HoMM3 whirlpools pair on the same layer via mutual nearest XY",
    },
}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))

def build_layered_travel_link_substitution_lookup(
    substitution_lookup: dict[str, dict[str, Any]],
    valid_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    result = copy.deepcopy(substitution_lookup)
    overrides: list[dict[str, Any]] = []
    for signature, row in sorted(result.items()):
        if row.get("category") != "travel_link_candidate":
            continue
        template_object_id = row.get("templateObjectId")
        selection = TRAVEL_LINK_PORTAL_SELECTION_BY_OBJECT_ID.get(template_object_id)
        if selection is None:
            continue
        selected_sid = selection["sid"]
        if selected_sid not in valid_ids:
            raise ValueError(f"layered travel-link portal SID {selected_sid!r} is not present in native Core mapObjects")
        old_sid = row.get("replacementSid")
        row["replacementSid"] = selected_sid
        row["ruleName"] = selection["ruleName"]
        row["lossiness"] = "direct_or_family_substitution"
        row["layeredTravelLinkResolver"] = {
            "source": "h3m_object_family_to_native_portal_family",
            "templateObjectId": template_object_id,
            "oldReplacementSid": old_sid,
            "selectedSid": selected_sid,
            "visualFamily": selection["visualFamily"],
            "reason": selection["reason"],
        }
        overrides.append({
            "signature": signature,
            "templateObjectId": template_object_id,
            "oldReplacementSid": old_sid,
            "selectedSid": selected_sid,
            "ruleName": selection["ruleName"],
            "visualFamily": selection["visualFamily"],
        })
    return result, {
        "status": "generated_static_contract_runtime_unvalidated",
        "source": "h3m_object_family_to_native_portal_family",
        "overrideCount": len(overrides),
        "overrides": overrides,
    }



def project_source_y(source_y: int) -> int:
    if not (0 <= source_y < SOURCE_HEIGHT):
        raise ValueError(f"source y outside emitted envelope: {source_y}")
    return LAYER_LAYOUT.source_height - 1 - source_y


def layer_target_node(layer: int, source_x: int, source_y: int) -> int:
    return LAYER_LAYOUT.target_node(layer, source_x, source_y)


def node_xy(node: int) -> dict[str, int]:
    return LAYER_LAYOUT.node_xy(node)


def atlas_arrays() -> dict[str, list[int]]:
    count = OLDEN_WIDTH * OLDEN_HEIGHT
    return {
        "tilesMap": [PADDING_TILE_ID] * count,
        "roadsMap": [0] * count,
        "waterMap": [PADDING_WATER_ID] * count,
        "levelsMap": [0] * count,
        "climbsMap": [0] * count,
        "customAreasPainting": [0] * count,
    }


ENVELOPE_PADDING_VOID_POLICY = (
    "envelope_padding_elevated_cliffs_surface_land_match_underground_void"
)
# Legacy alias kept so older docs/greps still find the symbol.
ENVELOPE_PADDING_FLAT_VOID_POLICY_RETIRED = "envelope_padding_flat_void_black_blocked"
# 160x80 atlas minus two centered 72x72 source envelopes (Homecoming default).
# After apply_profile_globals, use expected_envelope_padding_cell_count().
EXPECTED_ENVELOPE_PADDING_CELL_COUNT = OLDEN_WIDTH * OLDEN_HEIGHT - 2 * SOURCE_WIDTH * SOURCE_HEIGHT
# Padding pathing: elevated cliffs (levelsMap=1, climbsMap=0) — same mechanism as
# underground rock / vanilla_stock elevated Dirt. No occupancy blockers.
# Visual: surface-nearest *land* tile match; underground-nearest stays Void 23.
# Ocean cells are never used as a match seed (elevated water looks wrong).
# Underground tunnel clearance (Chebyshev-2 rock→burrow) stays ON inside envelopes;
# elevating cells *outside* envelopes does not collapse in-envelope 2x2 clearance.
ENVELOPE_PADDING_BLOCKER_SID = "homm3_envelope_padding_blocker"
ENVELOPE_PADDING_BLOCKER_DONOR_SID = single.HOMM3_PATHING_BLOCKER_DONOR_SID
ENVELOPE_PADDING_BLOCKER_PREF = single.HOMM3_CHEAP_BLOCK_PREF
ENVELOPE_PADDING_BLOCKER_ID_BASE = 920_000
ENVELOPE_PADDING_BLOCKER_OBJECT_MEMBER = "DB/map/objects/homm3_envelope_padding_blocker.json"
ENVELOPE_PADDING_LEVEL = scenario.UNDERGROUND_ROCK_LEVEL  # 1 — elevated cliff
ENVELOPE_PADDING_FALLBACK_LAND_TILE_ID = 7  # Dirt
ENVELOPE_PADDING_BLOCKERS_STATUS = "retired_cliff_pathing_no_occupancy"


def expected_envelope_padding_cell_count() -> int:
    """Recompute after apply_profile_globals mutates SOURCE_/OLDEN_ dimensions."""
    layer_count = len(LAYER_SPECS) if LAYER_SPECS else 2
    return OLDEN_WIDTH * OLDEN_HEIGHT - layer_count * SOURCE_WIDTH * SOURCE_HEIGHT


def envelope_padding_nodes() -> list[int]:
    """Atlas nodes outside both centered HoMM3 source envelopes."""
    source_nodes: set[int] = set()
    for layer in LAYER_SPECS:
        for _, _, target_index in layer_source_target_nodes(layer):
            source_nodes.add(int(target_index))
    return [node for node in range(OLDEN_WIDTH * OLDEN_HEIGHT) if node not in source_nodes]


def _envelope_source_node_set() -> set[int]:
    nodes: set[int] = set()
    for layer in LAYER_SPECS:
        for _, _, target_index in layer_source_target_nodes(layer):
            nodes.add(int(target_index))
    return nodes


def _is_underground_layer(layer: int) -> bool:
    return bool(LAYER_SPECS[layer]["view"].get("isUnderground"))


def _connected_source_water_components(cells: set[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    remaining = set(cells)
    components: list[list[tuple[int, int]]] = []
    while remaining:
        start = min(remaining)
        stack = [start]
        component: list[tuple[int, int]] = []
        remaining.remove(start)
        while stack:
            x, y = stack.pop()
            component.append((x, y))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                neighbor = (x + dx, y + dy)
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)
        components.append(sorted(component))
    components.sort(key=lambda item: (item[0][1], item[0][0], len(item)))
    return components


def _pond_placement_for_water_component(cells: list[tuple[int, int]]) -> dict[str, Any]:
    if not cells:
        raise ValueError("water component must not be empty")
    avg_x = sum(x for x, _ in cells) / len(cells)
    avg_y = sum(y for _, y in cells) / len(cells)
    anchor = min(
        cells,
        key=lambda cell: (
            (cell[0] - avg_x) ** 2 + (cell[1] - avg_y) ** 2,
            cell[1],
            cell[0],
        ),
    )
    sid = (
        UNDERGROUND_POND_SCENERY_BIG_SID
        if len(cells) >= UNDERGROUND_POND_SCENERY_BIG_COMPONENT_MIN_TILES
        else UNDERGROUND_POND_SCENERY_SMALL_SID
    )
    return {
        "sourceX": anchor[0],
        "sourceY": anchor[1],
        "node": layer_target_node(1, anchor[0], anchor[1]),
        "sid": sid,
        "componentTileCount": len(cells),
    }


def plan_underground_water_to_pond_scenery(
    layer_map_data: dict[str, Any],
    *,
    preserve_underground_ocean: bool,
) -> dict[str, Any]:
    if preserve_underground_ocean:
        return {
            "status": "preserved_underground_ocean",
            "policy": UNDERGROUND_WATER_TO_POND_SCENERY_POLICY,
            "sourceWaterTileCount": 0,
            "componentCount": 0,
            "placements": [],
        }
    water_cells: set[tuple[int, int]] = set()
    width = int(layer_map_data.get("sizeX_") or SOURCE_WIDTH)
    height = int(layer_map_data.get("sizeZ_") or SOURCE_HEIGHT)
    for y in range(height):
        for x in range(width):
            source_index = y * width + x
            if layer_map_data["tilesMap"][source_index] != H3_OCEAN_WATER_TERRAIN_ID:
                continue
            if layer_map_data["waterMap"][source_index] != 0:
                raise ValueError(
                    f"underground water-to-pond conversion does not support river overlays at 1:{x}:{y}"
                )
            water_cells.add((x, y))
    components = _connected_source_water_components(water_cells)
    placements = [_pond_placement_for_water_component(component) for component in components]
    return {
        "status": "converted_to_pond_scenery",
        "policy": UNDERGROUND_WATER_TO_POND_SCENERY_POLICY,
        "sourceWaterTileCount": len(water_cells),
        "componentCount": len(components),
        "placements": placements,
    }


    view = LAYER_SPECS[layer].get("view") or {}
    return bool(view.get("isUnderground"))


def paint_atlas_envelope_padding_as_void(projected: dict[str, list[int]]) -> dict[str, Any]:
    """Paint atlas cells outside every HoMM3 source envelope as elevated cliffs.

    Pathing: levelsMap=1 + climbsMap=0 (no ramps onto padding). No Block objects.
    Visual:
      - nearest seed on an underground envelope → Void (23) cliff
      - nearest seed on a surface envelope → that cell's land tile (water skipped)
      - unreachable / only-water edge case → Dirt (7) cliff
    """
    from collections import deque

    expected = expected_envelope_padding_cell_count()
    source_nodes = _envelope_source_node_set()
    padding_nodes = [node for node in range(OLDEN_WIDTH * OLDEN_HEIGHT) if node not in source_nodes]
    if len(padding_nodes) != expected:
        raise ValueError(
            f"envelope padding cell count {len(padding_nodes)} != expected {expected} "
            f"(atlas={OLDEN_WIDTH}x{OLDEN_HEIGHT} source={SOURCE_WIDTH}x{SOURCE_HEIGHT} "
            f"layers={sorted(LAYER_SPECS)})"
        )

    # Seed BFS from playable envelopes. Underground always forces Void; surface
    # contributes land tiles only (never ocean cells).
    # assignment[node] = (distance, is_underground, tile_id)
    assignment: dict[int, tuple[int, bool, int]] = {}
    queue: deque[int] = deque()

    for layer in sorted(LAYER_SPECS):
        underground = _is_underground_layer(layer)
        for _, _, target_index in layer_source_target_nodes(layer):
            node = int(target_index)
            tile = int(projected["tilesMap"][node])
            if underground:
                seed_tile = scenario.OLDEN_VOID_TILE_ID
            else:
                if single.is_ocean_node(projected, node):
                    continue
                seed_tile = tile if tile != scenario.OLDEN_VOID_TILE_ID else ENVELOPE_PADDING_FALLBACK_LAND_TILE_ID
            assignment[node] = (0, underground, seed_tile)
            queue.append(node)

    width = OLDEN_WIDTH
    height = OLDEN_HEIGHT
    total = width * height
    while queue:
        node = queue.popleft()
        dist, underground, tile = assignment[node]
        x = node % width
        y = node // width
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if nx < 0 or ny < 0 or nx >= width or ny >= height:
                continue
            neighbor = ny * width + nx
            if neighbor in source_nodes:
                continue
            prev = assignment.get(neighbor)
            next_dist = dist + 1
            if prev is None or next_dist < prev[0]:
                assignment[neighbor] = (next_dist, underground, tile)
                queue.append(neighbor)

    tile_histogram: Counter[int] = Counter()
    surface_matched = 0
    underground_void = 0
    fallback_dirt = 0
    for node in padding_nodes:
        seed = assignment.get(node)
        if seed is None:
            tile = ENVELOPE_PADDING_FALLBACK_LAND_TILE_ID
            underground = False
            fallback_dirt += 1
        else:
            _dist, underground, tile = seed
            if underground:
                tile = scenario.OLDEN_VOID_TILE_ID
                underground_void += 1
            else:
                if tile == scenario.OLDEN_VOID_TILE_ID:
                    tile = ENVELOPE_PADDING_FALLBACK_LAND_TILE_ID
                    fallback_dirt += 1
                else:
                    surface_matched += 1
        projected["tilesMap"][node] = tile
        projected["levelsMap"][node] = ENVELOPE_PADDING_LEVEL
        projected["climbsMap"][node] = scenario.UNDERGROUND_ROCK_CLIMB
        projected["waterMap"][node] = PADDING_WATER_ID
        tile_histogram[tile] += 1

    if underground_void + surface_matched + fallback_dirt != expected:
        raise ValueError(
            f"envelope padding classification drift: ug={underground_void} "
            f"surface={surface_matched} fallback={fallback_dirt} expected={expected}"
        )

    return {
        "policy": ENVELOPE_PADDING_VOID_POLICY,
        "status": "applied",
        "level": ENVELOPE_PADDING_LEVEL,
        "climb": scenario.UNDERGROUND_ROCK_CLIMB,
        "waterId": PADDING_WATER_ID,
        "cellCount": expected,
        "surfaceMatchedCellCount": surface_matched,
        "undergroundVoidCellCount": underground_void,
        "fallbackDirtCellCount": fallback_dirt,
        "fallbackLandTileId": ENVELOPE_PADDING_FALLBACK_LAND_TILE_ID,
        "tileHistogram": {str(k): v for k, v in sorted(tile_histogram.items())},
        "pathingMechanism": "elevated_no_ramp_cliff",
        "pathingRationale": (
            "Padding uses levelsMap=1 climbsMap=0 cliffs (underground-rock style) so no "
            "occupancy blockers are required. Surface-nearest land tiles are matched; "
            "underground-nearest padding stays Void 23; water tiles are never matched."
        ),
        "blockers": {
            "status": ENVELOPE_PADDING_BLOCKERS_STATUS,
            "cellCount": 0,
            "sid": ENVELOPE_PADDING_BLOCKER_SID,
        },
    }


def load_envelope_padding_blocker_donor_row() -> dict[str, Any]:
    """Load campaign_FX_block from Core.zip for padding Block ObjectConfig cloning."""
    donor_row: dict[str, Any] | None = None
    with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
        for name in core.namelist():
            if not (name.startswith("DB/map/objects/") and name.endswith(".json")):
                continue
            doc = json.loads(core.read(name).decode("utf-8-sig"))
            rows = doc.get("array") if isinstance(doc, dict) else None
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and row.get("id") == ENVELOPE_PADDING_BLOCKER_DONOR_SID:
                    donor_row = row
                    break
            if donor_row is not None:
                break
    if not isinstance(donor_row, dict):
        raise ValueError(
            f"missing Core donor row {ENVELOPE_PADDING_BLOCKER_DONOR_SID!r} for "
            f"{ENVELOPE_PADDING_BLOCKER_SID}"
        )
    return donor_row


def envelope_padding_blocker_object_row(donor_row: dict[str, Any] | None = None) -> dict[str, Any]:
    """Retired: cliff padding no longer needs Block occupancy ObjectConfig."""
    raise RuntimeError(
        "envelope padding blockers are retired; padding pathing uses elevated cliffs "
        f"(policy={ENVELOPE_PADDING_VOID_POLICY!r})"
    )


def write_envelope_padding_blocker_overlay() -> dict[str, Any]:
    """Retired: remove any stale padding-blocker ObjectConfig overlay member."""
    out_dir = OUT_ROOT / "core_overlay"
    member_path = out_dir / ENVELOPE_PADDING_BLOCKER_OBJECT_MEMBER
    removed = False
    if member_path.is_file():
        member_path.unlink()
        removed = True
    return {
        "status": ENVELOPE_PADDING_BLOCKERS_STATUS,
        "member": ENVELOPE_PADDING_BLOCKER_OBJECT_MEMBER,
        "sid": ENVELOPE_PADDING_BLOCKER_SID,
        "removedStaleOverlay": removed,
        "output": str(member_path),
    }


def emit_envelope_padding_blockers(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Retired no-op: elevated cliff padding does not emit occupancy blockers.

    Strips any stale ``homm3_envelope_padding_blocker`` groups and config rows so
    regenerations cannot leave rock piles on the false-edge.
    """
    native_object_configs.pop(ENVELOPE_PADDING_BLOCKER_SID, None)
    removed_groups = 0
    for group in list(objects):
        if group.get("sid") == ENVELOPE_PADDING_BLOCKER_SID:
            objects.remove(group)
            removed_groups += 1
    return {
        "policy": ENVELOPE_PADDING_VOID_POLICY,
        "status": ENVELOPE_PADDING_BLOCKERS_STATUS,
        "sid": ENVELOPE_PADDING_BLOCKER_SID,
        "cellCount": 0,
        "removedStaleGroups": removed_groups,
        "objectMember": ENVELOPE_PADDING_BLOCKER_OBJECT_MEMBER,
    }


def layer_source_target_nodes(layer: int) -> list[tuple[int, int, int]]:
    return [
        (x, y, layer_target_node(layer, x, y))
        for y in range(SOURCE_HEIGHT)
        for x in range(SOURCE_WIDTH)
    ]


def connected_component_sizes(cells: set[tuple[int, int]]) -> list[int]:
    remaining = set(cells)
    sizes: list[int] = []
    while remaining:
        start = next(iter(remaining))
        queue = [start]
        remaining.remove(start)
        size = 1
        for x, y in queue:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                neighbor = (x + dx, y + dy)
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
                    size += 1
        sizes.append(size)
    return sorted(sizes, reverse=True)


def underground_clearance_positions(walkable: set[tuple[int, int]]) -> set[tuple[int, int]]:
    return {
        (x, y)
        for y in range(SOURCE_HEIGHT - 1)
        for x in range(SOURCE_WIDTH - 1)
        if all((x + dx, y + dy) in walkable for dx in (0, 1) for dy in (0, 1))
    }


def underground_tunnel_clearance_widened_rock(source_burrow: set[tuple[int, int]], source_rock: set[tuple[int, int]]) -> set[tuple[int, int]]:
    walkable = set(source_burrow)
    frontier = set(source_burrow)
    widened: set[tuple[int, int]] = set()
    for _ in range(UNDERGROUND_TUNNEL_CLEARANCE_RADIUS):
        next_frontier = {
            (x + dx, y + dy)
            for x, y in frontier
            for dx, dy in UNDERGROUND_TUNNEL_CLEARANCE_DIRECTIONS
            if (x + dx, y + dy) in source_rock and (x + dx, y + dy) not in walkable
        }
        widened.update(next_frontier)
        walkable.update(next_frontier)
        frontier = next_frontier
    return widened


def underground_elevation_buffered_walkable(walkable: set[tuple[int, int]], elevated: set[tuple[int, int]]) -> set[tuple[int, int]]:
    return {
        (x, y)
        for x, y in walkable
        if not any((x + dx, y + dy) in elevated for dx, dy in UNDERGROUND_TUNNEL_CLEARANCE_DIRECTIONS)
    }


def apply_underground_tunnel_clearance(out: dict[str, list[int]], layer: int, layer_map_data: dict[str, Any]) -> dict[str, Any] | None:
    if not bool(LAYER_SPECS[layer]["view"].get("isUnderground")):
        return None
    source_burrow = {
        (x, y)
        for y in range(SOURCE_HEIGHT)
        for x in range(SOURCE_WIDTH)
        if layer_map_data["tilesMap"][y * SOURCE_WIDTH + x] == scenario.H3_UNDERGROUND_SUBTERRANEAN_TERRAIN_ID
    }
    source_rock = {
        (x, y)
        for y in range(SOURCE_HEIGHT)
        for x in range(SOURCE_WIDTH)
        if layer_map_data["tilesMap"][y * SOURCE_WIDTH + x] == scenario.H3_UNDERGROUND_ROCK_TERRAIN_ID
    }
    widened = underground_tunnel_clearance_widened_rock(source_burrow, source_rock)
    for x, y in sorted(widened):
        target = layer_target_node(layer, x, y)
        out["tilesMap"][target] = scenario.OLDEN_BURROW_TILE_ID
        out["waterMap"][target] = 0
        out["levelsMap"][target] = 0
        out["climbsMap"][target] = 0
    final_walkable = source_burrow | widened
    clearance = underground_clearance_positions(final_walkable)
    clearance_components = connected_component_sizes(clearance)
    walkable_components = connected_component_sizes(final_walkable)
    remaining_elevated = source_rock - widened
    elevation_buffered_walkable = underground_elevation_buffered_walkable(final_walkable, remaining_elevated)
    elevation_buffered_clearance = underground_clearance_positions(elevation_buffered_walkable)
    elevation_buffered_clearance_components = connected_component_sizes(elevation_buffered_clearance)
    return {
        "status": UNDERGROUND_TUNNEL_CLEARANCE_STATUS,
        "policy": UNDERGROUND_TUNNEL_CLEARANCE_POLICY,
        "sourceBurrowCellCount": len(source_burrow),
        "sourceRockCellCount": len(source_rock),
        "widenedRockCellCount": len(widened),
        "finalBurrowCellCount": len(final_walkable),
        "remainingRockVoidCellCount": len(remaining_elevated),
        "clearanceRadius": UNDERGROUND_TUNNEL_CLEARANCE_RADIUS,
        "clearanceNeighborhood": UNDERGROUND_TUNNEL_CLEARANCE_NEIGHBORHOOD,
        "clearanceModel": "2x2_orthogonal_native_pathing_proxy",
        "clearancePositionCount": len(clearance),
        "clearanceComponentCount": len(clearance_components),
        "clearanceLargestComponentSize": clearance_components[0] if clearance_components else 0,
        "clearanceComponentSizesTop10": clearance_components[:10],
        "walkableComponentCount": len(walkable_components),
        "walkableLargestComponentSize": walkable_components[0] if walkable_components else 0,
        "elevationBufferedClearanceModel": "2x2_clearance_after_8_neighbor_level1_buffer",
        "elevationBufferedWalkableCellCount": len(elevation_buffered_walkable),
        "elevationBufferedClearancePositionCount": len(elevation_buffered_clearance),
        "elevationBufferedClearanceComponentCount": len(elevation_buffered_clearance_components),
        "elevationBufferedClearanceLargestComponentSize": elevation_buffered_clearance_components[0] if elevation_buffered_clearance_components else 0,
        "elevationBufferedClearanceComponentSizesTop10": elevation_buffered_clearance_components[:10],
    }

def project_layer_arrays(
    out: dict[str, list[int]],
    layer: int,
    layer_map_data: dict[str, Any],
    *,
    apply_underground_tunnel_clearance_flag: bool = True,
    preserve_underground_ocean: bool = False,
) -> dict[str, Any]:
    if layer_map_data.get("sizeX_") != SOURCE_WIDTH or layer_map_data.get("sizeZ_") != SOURCE_HEIGHT:
        raise ValueError(
            f"layer {layer} map data must be {SOURCE_WIDTH}x{SOURCE_HEIGHT} before atlas projection; "
            f"got {layer_map_data.get('sizeX_')}x{layer_map_data.get('sizeZ_')}"
        )
    terrain_mapping = H3_LAYER_TO_OLDEN_TILE.get(layer)
    river_mapping = H3_LAYER_RIVER_TO_OLDEN_WATER.get(layer, {})
    if terrain_mapping is None:
        raise ValueError(f"missing terrain mapping for Homecoming source layer {layer}")

    source_terrain_histogram: Counter[int] = Counter()
    source_water_histogram: Counter[int] = Counter()
    projected_terrain_histogram: Counter[int] = Counter()
    projected_water_histogram: Counter[int] = Counter()
    projected_level_histogram: Counter[int] = Counter()
    projected_climb_histogram: Counter[int] = Counter()
    source_road_histogram: Counter[int] = Counter()
    projected_road_histogram: Counter[int] = Counter()
    underground_rock_void_count = 0
    underground_water_to_pond = None
    if _is_underground_layer(layer):
        underground_water_to_pond = plan_underground_water_to_pond_scenery(
            layer_map_data,
            preserve_underground_ocean=preserve_underground_ocean,
        )
    for y in range(SOURCE_HEIGHT):
        for x in range(SOURCE_WIDTH):
            source_index = y * SOURCE_WIDTH + x
            target_index = layer_target_node(layer, x, y)
            h3_tile = layer_map_data["tilesMap"][source_index]
            h3_water = layer_map_data["waterMap"][source_index]
            h3_road = layer_map_data["roadsMap"][source_index]
            if h3_tile not in terrain_mapping:
                raise ValueError(f"unsupported H3 terrain {h3_tile} at layer={layer} {x},{y}")
            out["roadsMap"][target_index] = scenario.project_h3_road_code(layer, h3_road)
            if h3_road != 0:
                source_road_histogram[h3_road] += 1
                projected_road_histogram[out["roadsMap"][target_index]] += 1

            if layer == 0 and h3_tile == 8:
                if h3_water != 0:
                    raise ValueError(f"H3 water terrain with additional river overlay {h3_water} at layer={layer} {x},{y}")
                out["tilesMap"][target_index] = single.OCEAN_TILE_CODE
                out["waterMap"][target_index] = single.OCEAN_WATER_MAP_ID
            elif (
                _is_underground_layer(layer)
                and h3_tile == H3_OCEAN_WATER_TERRAIN_ID
                and underground_water_to_pond is not None
                and underground_water_to_pond["status"] == "converted_to_pond_scenery"
            ):
                if h3_water != 0:
                    raise ValueError(
                        f"H3 underground water terrain with additional river overlay {h3_water} at layer={layer} {x},{y}"
                    )
                out["tilesMap"][target_index] = scenario.OLDEN_BURROW_TILE_ID
                out["waterMap"][target_index] = 0
            elif h3_tile == H3_OCEAN_WATER_TERRAIN_ID:
                # The ocean basin (campaign_ocean) is a surface-layer projection only.
                raise ValueError(
                    f"H3 ocean at layer={layer} {x},{y} has no native ocean projection; "
                    "terrain.preserveUndergroundOcean is unsupported (underground water converts to pond scenery)"
                )
            else:
                mapped_tile = terrain_mapping[h3_tile]
                out["tilesMap"][target_index] = int(mapped_tile["oldenId"])
                if "oldenWaterId" in mapped_tile:
                    if h3_water != 0:
                        raise ValueError(f"H3 water terrain with additional river overlay {h3_water} at layer={layer} {x},{y}")
                    out["waterMap"][target_index] = int(mapped_tile["oldenWaterId"])
                elif h3_water == 0:
                    out["waterMap"][target_index] = 0
                else:
                    mapped_water = river_mapping.get(h3_tile, {}).get(h3_water)
                    if mapped_water is None:
                        raise ValueError(
                            f"unsupported H3 river code {h3_water} at layer={layer} {x},{y}; "
                            "add an explicit native water mapping"
                        )
                    out["waterMap"][target_index] = int(mapped_water["oldenId"])

            if bool(LAYER_SPECS[layer]["view"].get("isUnderground")) and h3_tile == scenario.H3_UNDERGROUND_ROCK_TERRAIN_ID:
                out["levelsMap"][target_index] = scenario.UNDERGROUND_ROCK_LEVEL
                out["climbsMap"][target_index] = scenario.UNDERGROUND_ROCK_CLIMB
                underground_rock_void_count += 1

            source_terrain_histogram[h3_tile] += 1
            source_water_histogram[h3_water] += 1
            projected_terrain_histogram[out["tilesMap"][target_index]] += 1
            projected_water_histogram[out["waterMap"][target_index]] += 1
            projected_level_histogram[out["levelsMap"][target_index]] += 1
            projected_climb_histogram[out["climbsMap"][target_index]] += 1

    tunnel_clearance = None
    if apply_underground_tunnel_clearance_flag:
        tunnel_clearance = apply_underground_tunnel_clearance(out, layer, layer_map_data)
    else:
        tunnel_clearance = {
            "status": "disabled",
            "policy": "disabled_raw_translation_emit_policy_pack",
            "remainingRockVoidCellCount": underground_rock_void_count,
        }
    if layer == 0:
        basin_geometry = single.apply_native_ocean_basin_geometry(
            out,
            LAYER_LAYOUT.atlas_width,
            LAYER_LAYOUT.atlas_height,
        )
        out["nativeOceanBasinGeometry"] = basin_geometry
    else:
        basin_geometry = None
    projected_terrain_histogram = Counter()
    projected_water_histogram = Counter()
    projected_level_histogram = Counter()
    projected_climb_histogram = Counter()
    for _, _, target_index in layer_source_target_nodes(layer):
        projected_terrain_histogram[out["tilesMap"][target_index]] += 1
        projected_water_histogram[out["waterMap"][target_index]] += 1
        projected_level_histogram[out["levelsMap"][target_index]] += 1
        projected_climb_histogram[out["climbsMap"][target_index]] += 1
    if tunnel_clearance is not None and apply_underground_tunnel_clearance_flag:
        underground_rock_void_count = int(tunnel_clearance["remainingRockVoidCellCount"])

    return {
        "layer": layer,
        "sid": LAYER_SPECS[layer]["sid"],
        "offsetX": LAYER_SPECS[layer]["offsetX"],
        "offsetY": LAYER_SPECS[layer]["offsetY"],
        "nativeOceanBasinGeometry": basin_geometry,
        "sourceTerrainHistogram": dict(sorted(source_terrain_histogram.items())),
        "sourceWaterHistogram": dict(sorted(source_water_histogram.items())),
        "projectedTerrainHistogram": dict(sorted(projected_terrain_histogram.items())),
        "projectedWaterHistogram": dict(sorted(projected_water_histogram.items())),
        "projectedLevelHistogram": dict(sorted(projected_level_histogram.items())),
        "projectedClimbHistogram": dict(sorted(projected_climb_histogram.items())),
        "roadProjectionPolicy": scenario.ROAD_PROJECTION_POLICY,
        "sourceRoadHistogram": dict(sorted(source_road_histogram.items())),
        "projectedRoadHistogram": dict(sorted(projected_road_histogram.items())),
        "undergroundRockVoidCount": underground_rock_void_count,
        "undergroundTunnelClearance": tunnel_clearance,
        "undergroundWaterToPondScenery": underground_water_to_pond,
    }


def project_layers(
    layered_map_data: list[dict[str, Any]],
    *,
    emit_policy: Any | None = None,
    preserve_underground_ocean: bool = False,
) -> tuple[dict[str, list[int]], list[dict[str, Any]]]:
    import emit_policy as emit_policy_mod

    policy = emit_policy if emit_policy is not None else emit_policy_mod.APPROACH_CELL_EMIT_POLICY
    projected = atlas_arrays()
    stats: list[dict[str, Any]] = []
    by_layer = {entry.get("layer"): entry.get("mapData") for entry in layered_map_data if isinstance(entry, dict)}
    if set(by_layer) != set(LAYER_SPECS):
        raise ValueError(f"layeredMapData must contain exactly layers {sorted(LAYER_SPECS)}; found {sorted(by_layer)}")
    for layer in sorted(LAYER_SPECS):
        stats.append(
            project_layer_arrays(
                projected,
                layer,
                by_layer[layer],
                apply_underground_tunnel_clearance_flag=policy.apply_underground_tunnel_clearance,
                preserve_underground_ocean=preserve_underground_ocean,
            )
        )
    padding_void = paint_atlas_envelope_padding_as_void(projected)
    projected["envelopePaddingVoid"] = padding_void
    return projected, stats


