"""Surface terrain painting constrained to catalog-backed native tile IDs."""

from __future__ import annotations

from .catalog import CatalogBuildError, ContentCatalogSnapshot
from .model import (
    ConstraintViolation,
    GenerationFailure,
    Point,
    SpatialLayout,
    TerrainGrid,
)
from .profile import ScenarioProfileV1
from .rng import DeterministicRng


# Stock/Golden Era maps evidence roadsMap code 1 as a native road overlay.
_NATIVE_ROAD_CODE = 1


def paint_surface_terrain(
    layout: SpatialLayout,
    profile: ScenarioProfileV1,
    catalog: ContentCatalogSnapshot,
    rng: DeterministicRng,
) -> TerrainGrid:
    profile = profile.normalized()
    try:
        biome_tiles = {
            biome: _native_tile_id(catalog.terrain_for_biome(biome), biome)
            for biome in profile.biomes
        }
        road_tile = _native_tile_id(
            catalog.terrain_for_biome(profile.terrain.road_biome),
            profile.terrain.road_biome,
        )
    except CatalogBuildError as ex:
        raise GenerationFailure(
            "terrain",
            (
                ConstraintViolation(
                    "missing_native_biome",
                    "terrain",
                    str(ex),
                ),
            ),
            seed=profile.seed,
        ) from ex

    zone_biomes: dict[str, str] = {}
    biome_values = tuple(profile.biomes)
    for zone in layout.zones:
        zone_biomes[zone.zone_id] = rng.choice(biome_values)
    total = layout.width * layout.height
    tiles = [0] * total
    biome_map = [""] * total
    custom_areas = [0] * total
    for y in range(layout.height):
        for x in range(layout.width):
            point = Point(x, y)
            nearest_index, nearest_zone = min(
                enumerate(layout.zones),
                key=lambda item: (
                    point.manhattan(item[1].center),
                    item[1].zone_id,
                ),
            )
            biome = zone_biomes[nearest_zone.zone_id]
            node = point.node(layout.width)
            tiles[node] = biome_tiles[biome]
            biome_map[node] = biome
            custom_areas[node] = nearest_index

    roads = [0] * total
    if profile.terrain.roads_enabled:
        for point in layout.route_cells:
            node = point.node(layout.width)
            tiles[node] = road_tile
            biome_map[node] = profile.terrain.road_biome
            roads[node] = _NATIVE_ROAD_CODE

    levels, climbs = _paint_elevation(layout, profile)

    terrain = TerrainGrid(
        width=layout.width,
        height=layout.height,
        tiles_map=tuple(tiles),
        water_map=(0,) * total,
        roads_map=tuple(roads),
        levels_map=tuple(levels),
        climbs_map=tuple(climbs),
        custom_areas_painting=tuple(custom_areas),
        biome_map=tuple(biome_map),
        blocked=(False,) * total,
    )
    violations = validate_terrain(terrain, layout, set(biome_tiles.values()) | {road_tile})
    if violations:
        raise GenerationFailure("terrain", violations, seed=profile.seed)
    return terrain


def _paint_elevation(
    layout: SpatialLayout,
    profile: ScenarioProfileV1,
) -> tuple[list[int], list[int]]:
    total = layout.width * layout.height
    levels = [0] * total
    climbs = [0] * total
    if not profile.terrain.elevation_enabled or profile.terrain.elevation_fraction == 0.0:
        return levels, climbs
    flat: set[Point] = set(layout.route_cells)
    for point in tuple(layout.route_cells):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                candidate = Point(point.x + dx, point.y + dy)
                if 0 <= candidate.x < layout.width and 0 <= candidate.y < layout.height:
                    flat.add(candidate)
    for zone in layout.zones:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                candidate = Point(zone.center.x + dx, zone.center.y + dy)
                if 0 <= candidate.x < layout.width and 0 <= candidate.y < layout.height:
                    flat.add(candidate)
    patch_size = max(4, layout.width // 8)
    threshold = round(profile.terrain.elevation_fraction * 1000)
    for y in range(layout.height):
        for x in range(layout.width):
            point = Point(x, y)
            if point in flat:
                continue
            patch_x, patch_y = x // patch_size, y // patch_size
            value = (
                patch_x * 73856093
                ^ patch_y * 19349663
                ^ (profile.seed & 0xFFFFFFFF) * 83492791
            ) & 0xFFFFFFFF
            if value % 1000 >= threshold:
                continue
            levels[point.node(layout.width)] = 1 if ((value >> 9) & 1) else -1
    route_nodes = set(layout.route_cells)
    for y in range(layout.height):
        for x in range(layout.width):
            point = Point(x, y)
            node = point.node(layout.width)
            if point in route_nodes or not levels[node]:
                continue
            neighbors = tuple(
                candidate
                for candidate in (
                    Point(x - 1, y), Point(x + 1, y),
                    Point(x, y - 1), Point(x, y + 1),
                )
                if 0 <= candidate.x < layout.width and 0 <= candidate.y < layout.height
            )
            if any(levels[neighbor.node(layout.width)] != levels[node] for neighbor in neighbors):
                edge_hash = (x * 92837111 ^ y * 689287499 ^ profile.seed) & 0xFFFFFFFF
                if edge_hash % 23 == 0:
                    climbs[node] = 1
    return levels, climbs


def validate_terrain(
    terrain: TerrainGrid,
    layout: SpatialLayout,
    allowed_tile_ids: set[int],
) -> tuple[ConstraintViolation, ...]:
    violations: list[ConstraintViolation] = []
    if terrain.width != layout.width or terrain.height != layout.height:
        violations.append(
            ConstraintViolation(
                "terrain_size_mismatch",
                "terrain",
                "terrain dimensions must match spatial layout",
            )
        )
    unknown = sorted(set(terrain.tiles_map) - allowed_tile_ids)
    if unknown:
        violations.append(
            ConstraintViolation(
                "unknown_native_tile",
                "terrain",
                "terrain contains tile IDs outside the selected catalog-backed set",
                (("tileIds", unknown),),
            )
        )
    blocked_route = sorted(
        point.node(terrain.width)
        for point in layout.route_cells
        if terrain.blocked[point.node(terrain.width)]
    )
    if blocked_route:
        violations.append(
            ConstraintViolation(
                "blocked_route_terrain",
                "terrain",
                "painted terrain blocks a routed progression cell",
                (("nodes", blocked_route[:20]),),
            )
        )
    invalid_road_codes = sorted(set(terrain.roads_map) - {0, _NATIVE_ROAD_CODE})
    if invalid_road_codes:
        violations.append(
            ConstraintViolation(
                "unknown_native_road",
                "terrain",
                "roadsMap contains unevidenced native road codes",
                (("roadCodes", invalid_road_codes),),
            )
        )
    route_nodes = {point.node(terrain.width) for point in layout.route_cells}
    roads_off_route = [
        node for node, value in enumerate(terrain.roads_map)
        if value and node not in route_nodes
    ]
    if roads_off_route:
        violations.append(
            ConstraintViolation(
                "road_outside_route",
                "terrain",
                "roadsMap overlays must stay on planned route cells",
                (("nodes", roads_off_route[:20]),),
            )
        )
    if any(terrain.water_map):
        violations.append(
            ConstraintViolation(
                "water_traversal_unproven",
                "terrain",
                "procedural surface terrain must not emit water traversal",
            )
        )
    invalid_levels = sorted(set(terrain.levels_map) - {-1, 0, 1})
    if invalid_levels:
        violations.append(
            ConstraintViolation(
                "unknown_native_level",
                "terrain",
                "levelsMap contains unsupported native level values",
                (("levels", invalid_levels),),
            )
        )
    invalid_climbs = sorted(set(terrain.climbs_map) - {0, 1})
    if invalid_climbs:
        violations.append(
            ConstraintViolation(
                "unknown_native_climb",
                "terrain",
                "climbsMap contains unsupported native climb values",
                (("climbs", invalid_climbs),),
            )
        )
    return tuple(violations)


def _native_tile_id(entry: object, biome: str) -> int:
    value = getattr(entry, "native_id", None)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CatalogBuildError(
            f"terrain biome {biome!r} has no positive integer native tile ID"
        )
    return value
