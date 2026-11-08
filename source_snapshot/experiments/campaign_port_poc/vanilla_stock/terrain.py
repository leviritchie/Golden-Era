"""Stock-legal terrain projection for the vanilla_stock emit lane.

Mirrors raw_translation / layer_atlas geometry stages within the stock tile
allowlist loaded from Core.zip (currently tiles 1..7 only):

- Ocean: Sand (tile 2) + levelsMap=-1 + perimeter climbs (no GE water tiles 18-22)
- Subterranean walkable: Dirt (tile 7) at levels=0
- Underground rock: Dirt (tile 7) at levels=1, climbs=0
- Rivers: stock waterMap ids 1..7 by biome (no longer omitted)
- Underground tunnel clearance: Chebyshev-2 rock→walkable dirt shoulder
  (stock stand-in for raw's rock→Burrow clearance)

Fail-closed if any projected tile or water id is absent from stock Core.
"""

from __future__ import annotations

import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import h3m_scenario_translation as scenario

from . import (
    GE_ONLY_TILE_IDS,
    STOCK_OCEAN_TILE_ID,
    STOCK_PADDING_TILE_ID,
    STOCK_ROCK_TILE_ID,
    STOCK_SUBTERRANEAN_TILE_ID,
)


# H3 terrain → stock Olden tilesMap ids (must be subset of Core tiles.json).
H3_TO_STOCK_TILE: dict[int, int] = {
    0: 7,  # dirt
    1: 2,  # sand
    2: 1,  # grass
    3: 4,  # snow
    4: 5,  # swamp → Autumn
    5: 1,  # rough → grass
    6: STOCK_SUBTERRANEAN_TILE_ID,  # subterranean → Dirt (Burrow is GE-only)
    7: 6,  # lava
    8: STOCK_OCEAN_TILE_ID,  # water → sand basin
    9: STOCK_ROCK_TILE_ID,  # rock (elevated)
    10: 1,  # HotA highlands → grass
    11: 3,  # HotA wasteland → Deathland
}

# H3 terrain → stock waterMap overlay for rivers (Core DB/map/waters/waters.json).
# Keys: h3_terrain → {h3_river_code → stock_water_id}.
# H3 river codes commonly seen: 1=clear, 2=icy, 3=muddy, 4=lava.
H3_RIVER_TO_STOCK_WATER: dict[int, dict[int, int]] = {
    0: {1: 1, 2: 1, 3: 1},  # dirt → water dirt
    1: {1: 2, 2: 2, 3: 2, 4: 6},  # sand; explicit lava river → water lava
    2: {1: 7, 2: 7, 3: 7},  # grass → water grass
    3: {1: 4, 2: 4, 3: 4},  # snow → water snow
    4: {1: 3, 2: 3, 3: 3},  # swamp → water death (lossy)
    5: {1: 7, 2: 7, 3: 7},  # rough → water grass
    6: {1: 1, 2: 1, 3: 1},  # subterranean river → water dirt
    7: {1: 1, 2: 1, 3: 1, 4: 6},  # lava terrain / lava river
    10: {1: 7, 2: 7, 3: 7},  # HotA highlands → water grass
    11: {1: 3, 2: 3, 3: 3},  # HotA wasteland → water death
}

WATER_PROJECTION_POLICY = (
    "h3_water_to_stock_sand_tile_2_levels_minus_one_water_map_zero_"
    "perimeter_climbs_one_interior_climbs_zero"
)
RIVER_PROJECTION_POLICY = "h3_river_to_stock_water_map_biome_channel"
UNDERGROUND_ROCK_POLICY = "h3_rock_to_stock_dirt_tile_7_levels_one_climbs_zero"
STOCK_OCEAN_BASIN_GEOMETRY_POLICY = scenario.NATIVE_OCEAN_BASIN_GEOMETRY_POLICY
UNDERGROUND_TUNNEL_CLEARANCE_POLICY = (
    "chebyshev_two_tile_elevation_shoulder_rock_to_stock_dirt_clearance"
)
UNDERGROUND_TUNNEL_CLEARANCE_RADIUS = 2
UNDERGROUND_TUNNEL_CLEARANCE_DIRECTIONS = (
    (-1, -1), (0, -1), (1, -1),
    (-1, 0),           (1, 0),
    (-1, 1),  (0, 1),  (1, 1),
)


class VanillaStockTerrainError(ValueError):
    """Raised when terrain cannot be projected into the stock tile allowlist."""


def load_stock_tile_ids(core: Path) -> set[int]:
    """Authoritative stock tilesMap allowlist from Core.zip DB/map/tiles/tiles.json."""
    try:
        with zipfile.ZipFile(core) as archive:
            payload = json.loads(archive.read("DB/map/tiles/tiles.json").decode("utf-8-sig"))
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as ex:
        raise VanillaStockTerrainError(f"cannot read stock tiles catalog from {core}: {ex}") from ex
    rows = payload.get("array") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise VanillaStockTerrainError(f"stock tiles catalog empty: {core}")
    ids: set[int] = set()
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), int):
            ids.add(int(row["id"]))
    if not ids:
        raise VanillaStockTerrainError(f"stock tiles catalog has no integer ids: {core}")
    ge_leaks = sorted(ids & GE_ONLY_TILE_IDS)
    if ge_leaks:
        raise VanillaStockTerrainError(
            f"stock Core tiles catalog unexpectedly contains GE-only tile ids {ge_leaks}; "
            "refusing to treat them as stock-legal"
        )
    return ids


def load_stock_water_ids(core: Path) -> set[int]:
    """Authoritative stock waterMap allowlist from Core.zip DB/map/waters/waters.json."""
    try:
        with zipfile.ZipFile(core) as archive:
            payload = json.loads(archive.read("DB/map/waters/waters.json").decode("utf-8-sig"))
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as ex:
        raise VanillaStockTerrainError(f"cannot read stock waters catalog from {core}: {ex}") from ex
    rows = payload.get("array") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise VanillaStockTerrainError(f"stock waters catalog empty: {core}")
    ids: set[int] = set()
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), int):
            ids.add(int(row["id"]))
    if not ids:
        raise VanillaStockTerrainError(f"stock waters catalog has no integer ids: {core}")
    return ids


def assert_stock_tile_ids(tiles: list[int], allowed: set[int] | None = None) -> None:
    allow = allowed if allowed is not None else set(range(1, 8))
    bad = sorted({int(t) for t in tiles if int(t) not in allow})
    if bad:
        raise VanillaStockTerrainError(f"non-stock tile ids present (allowed {sorted(allow)}): {bad}")
    ge = sorted({int(t) for t in tiles if int(t) in GE_ONLY_TILE_IDS})
    if ge:
        raise VanillaStockTerrainError(f"GE-only tile ids present: {ge}")


def assert_stock_water_ids(waters: list[int], allowed: set[int] | None = None) -> None:
    allow = allowed if allowed is not None else set(range(1, 8))
    # waterMap 0 = no water overlay
    bad = sorted({int(w) for w in waters if int(w) != 0 and int(w) not in allow})
    if bad:
        raise VanillaStockTerrainError(f"non-stock waterMap ids present (allowed 0 + {sorted(allow)}): {bad}")


def project_h3_tile_to_stock(h3_terrain: int, allowed_tiles: set[int]) -> int:
    if h3_terrain not in H3_TO_STOCK_TILE:
        raise VanillaStockTerrainError(f"unsupported H3 terrain id {h3_terrain}")
    tile = H3_TO_STOCK_TILE[h3_terrain]
    if tile not in allowed_tiles:
        raise VanillaStockTerrainError(
            f"projected tile {tile} for H3 terrain {h3_terrain} absent from stock Core allowlist {sorted(allowed_tiles)}"
        )
    if tile in GE_ONLY_TILE_IDS:
        raise VanillaStockTerrainError(f"refusing GE-only tile id {tile}")
    return tile


def project_h3_river_to_stock_water(
    *,
    h3_terrain: int,
    h3_river: int,
    allowed_waters: set[int],
) -> int:
    if h3_river == 0:
        return 0
    mapping = H3_RIVER_TO_STOCK_WATER.get(h3_terrain)
    if mapping is None or h3_river not in mapping:
        raise VanillaStockTerrainError(
            f"unsupported H3 river code {h3_river} on terrain {h3_terrain}; "
            "add an explicit stock waterMap mapping"
        )
    water_id = int(mapping[h3_river])
    if water_id not in allowed_waters:
        raise VanillaStockTerrainError(
            f"projected waterMap id {water_id} absent from stock Core allowlist {sorted(allowed_waters)}"
        )
    return water_id


def _connected_component_sizes(cells: set[tuple[int, int]]) -> list[int]:
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


def _underground_tunnel_clearance_widened_rock(
    source_walkable: set[tuple[int, int]],
    source_rock: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    walkable = set(source_walkable)
    frontier = set(source_walkable)
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


def apply_stock_underground_tunnel_clearance(
    *,
    out: dict[str, list[int]],
    layer_tiles: list[dict[str, Any]],
    layer_index: int,
    atlas: scenario.LayerAtlasLayout,
    source_width: int,
    source_height: int,
) -> dict[str, Any] | None:
    """Chebyshev-2 rock→walkable-dirt shoulder (stock stand-in for Burrow clearance).

    Only applies on non-surface layers. Returns None for surface.
    """
    if layer_index == 0:
        return None

    source_walkable: set[tuple[int, int]] = set()
    source_rock: set[tuple[int, int]] = set()
    for tile in layer_tiles:
        x = int(tile["x"])
        y = int(tile["y"])
        h3_terrain = int(tile["terrain"])
        if h3_terrain == scenario.H3_UNDERGROUND_ROCK_TERRAIN_ID:
            source_rock.add((x, y))
        elif h3_terrain != 8:  # non-water underground cells are walkable candidates
            source_walkable.add((x, y))

    widened = _underground_tunnel_clearance_widened_rock(source_walkable, source_rock)
    for x, y in sorted(widened):
        target = atlas.target_node(layer_index, x, y)
        out["tilesMap"][target] = STOCK_SUBTERRANEAN_TILE_ID
        out["waterMap"][target] = 0
        out["levelsMap"][target] = 0
        out["climbsMap"][target] = 0

    final_walkable = source_walkable | widened
    remaining_elevated = source_rock - widened
    clearance_positions = {
        (x, y)
        for y in range(source_height - 1)
        for x in range(source_width - 1)
        if all((x + dx, y + dy) in final_walkable for dx in (0, 1) for dy in (0, 1))
    }
    clearance_components = _connected_component_sizes(clearance_positions)
    walkable_components = _connected_component_sizes(final_walkable)
    return {
        "status": "applied",
        "policy": UNDERGROUND_TUNNEL_CLEARANCE_POLICY,
        "stockLimitation": "widens elevated rock to Dirt tile 7 levels=0; Burrow(15) is GE-only",
        "sourceWalkableCellCount": len(source_walkable),
        "sourceRockCellCount": len(source_rock),
        "widenedRockCellCount": len(widened),
        "finalWalkableCellCount": len(final_walkable),
        "remainingRockElevatedCellCount": len(remaining_elevated),
        "clearanceRadius": UNDERGROUND_TUNNEL_CLEARANCE_RADIUS,
        "clearancePositionCount": len(clearance_positions),
        "clearanceComponentCount": len(clearance_components),
        "clearanceLargestComponentSize": clearance_components[0] if clearance_components else 0,
        "walkableComponentCount": len(walkable_components),
        "walkableLargestComponentSize": walkable_components[0] if walkable_components else 0,
    }


def project_layer_into_atlas(
    *,
    layer_tiles: list[dict[str, Any]],
    layer_index: int,
    atlas: scenario.LayerAtlasLayout,
    out: dict[str, list[int]],
    allowed_tiles: set[int],
    allowed_waters: set[int],
    apply_underground_tunnel_clearance_flag: bool = True,
) -> dict[str, Any]:
    """Project one H3 layer into pre-sized atlas arrays. Mutates out."""
    ocean = 0
    rock = 0
    roads = 0
    rivers = 0
    for tile in layer_tiles:
        x = int(tile["x"])
        y = int(tile["y"])
        h3_terrain = int(tile["terrain"])
        h3_river = int(tile["river"])
        h3_road = int(tile["road"])
        node = atlas.target_node(layer_index, x, y)
        stock_tile = project_h3_tile_to_stock(h3_terrain, allowed_tiles)
        out["tilesMap"][node] = stock_tile
        out["waterMap"][node] = 0
        out["roadsMap"][node] = 0
        out["levelsMap"][node] = 0
        out["climbsMap"][node] = 0

        if h3_terrain == 8:
            if h3_river != 0:
                raise VanillaStockTerrainError(
                    f"H3 water terrain with additional river overlay {h3_river} at layer={layer_index} {x},{y}"
                )
            out["levelsMap"][node] = scenario.NATIVE_OCEAN_BASIN_LEVEL
            out["climbsMap"][node] = 0
            ocean += 1
        elif h3_terrain == scenario.H3_UNDERGROUND_ROCK_TERRAIN_ID:
            out["levelsMap"][node] = scenario.UNDERGROUND_ROCK_LEVEL
            out["climbsMap"][node] = scenario.UNDERGROUND_ROCK_CLIMB
            rock += 1
        elif h3_river != 0:
            out["waterMap"][node] = project_h3_river_to_stock_water(
                h3_terrain=h3_terrain,
                h3_river=h3_river,
                allowed_waters=allowed_waters,
            )
            rivers += 1

        if h3_road != 0:
            # Side-by-side atlas: underground roads share the Olden plane / code map.
            out["roadsMap"][node] = scenario.project_h3_road_code(layer_index, h3_road)
            roads += 1

    tunnel_clearance = None
    if apply_underground_tunnel_clearance_flag and layer_index != 0:
        tunnel_clearance = apply_stock_underground_tunnel_clearance(
            out=out,
            layer_tiles=layer_tiles,
            layer_index=layer_index,
            atlas=atlas,
            source_width=atlas.source_width,
            source_height=atlas.source_height,
        )
    elif layer_index != 0:
        tunnel_clearance = {"status": "disabled", "policy": "disabled_by_caller"}

    return {
        "oceanCells": ocean,
        "rockCells": rock,
        "roadCells": roads,
        "riverCells": rivers,
        "undergroundTunnelClearance": tunnel_clearance,
    }


def apply_stock_ocean_basin_geometry(
    out: dict[str, list[int]],
    *,
    width: int,
    height: int,
) -> dict[str, int | str]:
    """Stamp perimeter ramp climbs on every depressed H3-water stand-in cell.

    Uses ``levelsMap == NATIVE_OCEAN_BASIN_LEVEL`` (not GE water tile codes), because
    stock projects H3 water onto Sand tile 2. Same perimeter rule as the GE native
    ocean basin: 8-neighbor contact with non-basin (or map edge) → climbs=1;
    fully enclosed basin interior → climbs=0.
    """
    if width <= 0 or height <= 0:
        raise VanillaStockTerrainError(f"invalid atlas dimensions for basin geometry: {width}x{height}")
    levels = out["levelsMap"]
    climbs = out["climbsMap"]
    expected = width * height
    if len(levels) != expected or len(climbs) != expected:
        raise VanillaStockTerrainError(
            f"levels/climbs length mismatch for basin geometry: "
            f"levels={len(levels)} climbs={len(climbs)} expected={expected}"
        )

    perimeter_count = 0
    interior_count = 0
    for y in range(height):
        for x in range(width):
            node = y * width + x
            if int(levels[node]) != scenario.NATIVE_OCEAN_BASIN_LEVEL:
                continue
            perimeter = False
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx = x + dx
                    ny = y + dy
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        perimeter = True
                        break
                    neighbor = ny * width + nx
                    if int(levels[neighbor]) != scenario.NATIVE_OCEAN_BASIN_LEVEL:
                        perimeter = True
                        break
                if perimeter:
                    break
            if perimeter:
                climbs[node] = scenario.NATIVE_OCEAN_BASIN_PERIMETER_CLIMB
                perimeter_count += 1
            else:
                climbs[node] = scenario.NATIVE_OCEAN_BASIN_INTERIOR_CLIMB
                interior_count += 1

    return {
        "basinLevel": scenario.NATIVE_OCEAN_BASIN_LEVEL,
        "interiorClimb": scenario.NATIVE_OCEAN_BASIN_INTERIOR_CLIMB,
        "perimeterClimb": scenario.NATIVE_OCEAN_BASIN_PERIMETER_CLIMB,
        "policy": STOCK_OCEAN_BASIN_GEOMETRY_POLICY,
        "oceanTerrainNodeCount": perimeter_count + interior_count,
        "perimeterOceanTerrainNodeCount": perimeter_count,
        "interiorOceanTerrainNodeCount": interior_count,
    }


def assert_stock_ocean_basin_climb_contract(
    *,
    levels_map: list[int],
    climbs_map: list[int],
    width: int,
    height: int,
) -> dict[str, int]:
    """Fail closed if any basin↔land cliff lacks a perimeter climb ramp."""
    if width <= 0 or height <= 0:
        raise VanillaStockTerrainError(f"invalid dimensions: {width}x{height}")
    expected = width * height
    if len(levels_map) != expected or len(climbs_map) != expected:
        raise VanillaStockTerrainError(
            f"levels/climbs length mismatch: levels={len(levels_map)} climbs={len(climbs_map)} expected={expected}"
        )

    perimeter = 0
    interior = 0
    missing: list[str] = []
    bad_interior: list[str] = []
    for y in range(height):
        for x in range(width):
            node = y * width + x
            if int(levels_map[node]) != scenario.NATIVE_OCEAN_BASIN_LEVEL:
                continue
            is_perimeter = False
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx = x + dx
                    ny = y + dy
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        is_perimeter = True
                        break
                    if int(levels_map[ny * width + nx]) != scenario.NATIVE_OCEAN_BASIN_LEVEL:
                        is_perimeter = True
                        break
                if is_perimeter:
                    break
            climb = int(climbs_map[node])
            if is_perimeter:
                perimeter += 1
                if climb != scenario.NATIVE_OCEAN_BASIN_PERIMETER_CLIMB:
                    missing.append(f"{x},{y}:climb={climb}")
            else:
                interior += 1
                if climb != scenario.NATIVE_OCEAN_BASIN_INTERIOR_CLIMB:
                    bad_interior.append(f"{x},{y}:climb={climb}")

    if missing:
        sample = ", ".join(missing[:12])
        more = "" if len(missing) <= 12 else f" (+{len(missing) - 12} more)"
        raise VanillaStockTerrainError(
            f"stock ocean basin perimeter cells missing climbs="
            f"{scenario.NATIVE_OCEAN_BASIN_PERIMETER_CLIMB}: {sample}{more}"
        )
    if bad_interior:
        sample = ", ".join(bad_interior[:12])
        more = "" if len(bad_interior) <= 12 else f" (+{len(bad_interior) - 12} more)"
        raise VanillaStockTerrainError(
            f"stock ocean basin interior cells must keep climbs="
            f"{scenario.NATIVE_OCEAN_BASIN_INTERIOR_CLIMB}: {sample}{more}"
        )
    return {
        "perimeterOceanTerrainNodeCount": perimeter,
        "interiorOceanTerrainNodeCount": interior,
        "oceanTerrainNodeCount": perimeter + interior,
    }


def build_empty_atlas_arrays(atlas: scenario.LayerAtlasLayout) -> dict[str, list[int]]:
    total = atlas.atlas_width * atlas.atlas_height
    return {
        "tilesMap": [STOCK_PADDING_TILE_ID] * total,
        "waterMap": [0] * total,
        "roadsMap": [0] * total,
        "levelsMap": [0] * total,
        "climbsMap": [0] * total,
        "customAreasPainting": [0] * total,
    }


def single_view_for_atlas(atlas: scenario.LayerAtlasLayout) -> dict[str, Any]:
    """One MapView covering the full side-by-side atlas (no dual underground toggle)."""
    return {
        "name": "surface",
        "minSecX": 0,
        "minSecZ": 0,
        "secSizeX": atlas.atlas_width // atlas.sector_size,
        "secSizeZ": atlas.atlas_height // atlas.sector_size,
        "isUnderground": False,
        "stack": -1,
    }


ENVELOPE_PADDING_POLICY = (
    "atlas_cells_outside_source_envelopes_elevated_dirt_levels_one_climbs_zero"
)


def paint_envelope_padding_elevated_dirt(
    out: dict[str, list[int]],
    *,
    atlas: scenario.LayerAtlasLayout,
) -> dict[str, Any]:
    """Make atlas cells outside every HoMM3 source envelope unpathable.

    Stock has no invisible blocker ObjectConfig and no Void tile. Elevate padding
    to Dirt (tile 7) at levelsMap=1 with climbsMap=0 so there are no ramps onto
    the padding — matching underground rock cliff behavior.
    """
    width = atlas.atlas_width
    height = atlas.atlas_height
    expected = width * height
    for key in ("tilesMap", "levelsMap", "climbsMap", "waterMap"):
        if len(out[key]) != expected:
            raise VanillaStockTerrainError(
                f"{key} length {len(out[key])} != atlas cells {expected} for padding paint"
            )

    source_nodes: set[int] = set()
    for layer in atlas.layers:
        for y in range(atlas.source_height):
            for x in range(atlas.source_width):
                source_nodes.add(atlas.target_node(layer, x, y))
    padding_nodes = [node for node in range(expected) if node not in source_nodes]
    expected_padding = expected - len(atlas.layers) * atlas.source_width * atlas.source_height
    if len(padding_nodes) != expected_padding:
        raise VanillaStockTerrainError(
            f"envelope padding cell count {len(padding_nodes)} != expected {expected_padding}"
        )

    for node in padding_nodes:
        out["tilesMap"][node] = STOCK_ROCK_TILE_ID  # Dirt
        out["levelsMap"][node] = scenario.UNDERGROUND_ROCK_LEVEL  # 1
        out["climbsMap"][node] = scenario.UNDERGROUND_ROCK_CLIMB  # 0 — no ramps
        out["waterMap"][node] = 0
        out["roadsMap"][node] = 0

    return {
        "status": "applied",
        "policy": ENVELOPE_PADDING_POLICY,
        "tileId": STOCK_ROCK_TILE_ID,
        "level": scenario.UNDERGROUND_ROCK_LEVEL,
        "climb": scenario.UNDERGROUND_ROCK_CLIMB,
        "cellCount": len(padding_nodes),
        "pathingMechanism": "elevated_dirt_no_ramp_cliff",
        "stockLimitation": "Void(23) and invisible blockers are GE-only; elevated Dirt is the stock cliff stand-in",
    }


def terrain_policy_manifest() -> dict[str, str]:
    return {
        "water": WATER_PROJECTION_POLICY,
        "undergroundRock": UNDERGROUND_ROCK_POLICY,
        "rivers": RIVER_PROJECTION_POLICY,
        "undergroundTunnelClearance": UNDERGROUND_TUNNEL_CLEARANCE_POLICY,
        "envelopePadding": ENVELOPE_PADDING_POLICY,
        "stockTileSource": "Core.zip DB/map/tiles/tiles.json",
        "stockWaterSource": "Core.zip DB/map/waters/waters.json",
        "geOnlyTilesForbidden": ",".join(str(t) for t in sorted(GE_ONLY_TILE_IDS)),
    }


def tile_histogram(tiles: list[int]) -> dict[str, int]:
    return {str(k): v for k, v in sorted(Counter(tiles).items())}
