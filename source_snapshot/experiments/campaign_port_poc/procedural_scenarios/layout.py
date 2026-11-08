"""Deterministic spatial embedding and route/decision-anchor planning."""

from __future__ import annotations

import math

from .model import (
    ConstraintViolation,
    DecisionAnchor,
    GenerationFailure,
    Point,
    ProgressionGraph,
    Route,
    SpatialLayout,
    ZonePlacement,
)
from .profile import ScenarioProfileV1
from .rng import DeterministicRng


_DEFAULT_LATTICE_STEP = 8
_MAP_MARGIN = 4


def embed_progression_graph(
    graph: ProgressionGraph,
    profile: ScenarioProfileV1,
    rng: DeterministicRng,
) -> SpatialLayout:
    profile = profile.normalized()
    exact_spacing = (
        profile.density.decision_spacing_min
        == profile.density.decision_spacing_max
    )
    lattice_step = (
        profile.density.decision_spacing_min
        if exact_spacing
        else _DEFAULT_LATTICE_STEP
    )
    points = [
        Point(x, y)
        for y in range(_MAP_MARGIN, profile.map_size - _MAP_MARGIN, lattice_step)
        for x in range(_MAP_MARGIN, profile.map_size - _MAP_MARGIN, lattice_step)
    ]
    if len(points) < len(graph.zones):
        raise GenerationFailure(
            "layout",
            (
                ConstraintViolation(
                    "insufficient_lattice_capacity",
                    "layout",
                    "map size cannot fit the requested zone count",
                    (("capacity", len(points)), ("zoneCount", len(graph.zones))),
                ),
            ),
            seed=profile.seed,
        )
    parent_by_zone = {
        edge.target_zone_id: edge.source_zone_id
        for edge in graph.edges
        if edge.target_zone_id not in graph.primary_path
    }
    max_depth = max(zone.depth for zone in graph.zones)
    max_axis = max(point.x for point in points)
    min_axis = min(point.x for point in points)
    # Map coordinates use increasing Z/Y toward the south edge. Keep the
    # player start on the southwest approach so a town's native bottom-center
    # gate faces the playable map rather than placing the hero on its north
    # side. Victory remains diagonally opposite for clear progression.
    centers: dict[str, Point] = {
        graph.start_zone_id: Point(min_axis, max_axis),
        graph.victory_zone_id: Point(max_axis, min_axis),
    }
    used = set(centers.values())
    zone_order = sorted(
        (
            zone
            for zone in graph.zones
            if zone.zone_id not in (graph.start_zone_id, graph.victory_zone_id)
        ),
        key=lambda zone: (zone.depth, zone.zone_id),
    )
    for ordinal, zone in enumerate(zone_order):
        target_y = min_axis + round(
            (max_axis - min_axis) * zone.depth / max(1, max_depth)
        )
        preferred_x = (
            min_axis
            + ((zone.depth * 2 + ordinal) * lattice_step)
            % (max_axis - min_axis + lattice_step)
        )
        parent_id = parent_by_zone.get(zone.zone_id)
        if parent_id is None:
            primary_index = graph.primary_path.index(zone.zone_id)
            parent_id = graph.primary_path[primary_index - 1]
        parent = centers[parent_id]
        candidates = [point for point in points if point not in used]
        scored: list[tuple[float, int, int, Point]] = []
        for point in candidates:
            parent_distance = point.manhattan(parent)
            min_existing = min(point.manhattan(other) for other in used)
            score = (
                abs(point.y - target_y) * 3.0
                + abs(point.x - preferred_x)
                + abs(parent_distance - lattice_step) * 2.0
                + max(0, lattice_step - min_existing) * 4.0
            )
            scored.append((score, point.y, point.x, point))
        best_score = min(item[0] for item in scored)
        tied = [item[3] for item in scored if item[0] == best_score]
        chosen = rng.choice(sorted(tied))
        centers[zone.zone_id] = chosen
        used.add(chosen)

    routes: list[Route] = []
    anchors: list[DecisionAnchor] = []
    used_route_cells: set[Point] = set()
    for edge in graph.edges:
        start = centers[edge.source_zone_id]
        end = centers[edge.target_zone_id]
        unrelated_centers = tuple(
            point
            for zone_id, point in centers.items()
            if zone_id not in (edge.source_zone_id, edge.target_zone_id)
        )
        cells = _choose_route(
            start,
            end,
            occupied=used_route_cells,
            unrelated_centers=unrelated_centers,
            width=profile.map_size,
            height=profile.map_size,
            spacing_min=profile.density.decision_spacing_min,
            spacing_max=profile.density.decision_spacing_max,
            rng=rng,
        )
        route = Route(edge_id=edge.edge_id, cells=cells)
        routes.append(route)
        used_route_cells.update(cells)
        total_distance = len(cells) - 1
        segments = _partition_distance(
            total_distance,
            profile.density.decision_spacing_min,
            profile.density.decision_spacing_max,
            rng,
        )
        offset = 0
        for index, distance in enumerate(segments[:-1]):
            offset += distance
            point = cells[offset]
            anchors.append(
                DecisionAnchor(
                    anchor_id=f"anchor_{edge.edge_id}_{index:02d}",
                    edge_id=edge.edge_id,
                    point=point,
                    distance_from_previous=distance,
                )
            )

    layout = SpatialLayout(
        width=profile.map_size,
        height=profile.map_size,
        zones=tuple(
            ZonePlacement(zone.zone_id, centers[zone.zone_id], radius=3)
            for zone in graph.zones
        ),
        routes=tuple(routes),
        decision_anchors=tuple(anchors),
    )
    violations = validate_layout(layout, graph, profile)
    if violations:
        raise GenerationFailure("layout", violations, seed=profile.seed)
    return layout


def validate_layout(
    layout: SpatialLayout,
    graph: ProgressionGraph,
    profile: ScenarioProfileV1,
) -> tuple[ConstraintViolation, ...]:
    violations: list[ConstraintViolation] = []
    if layout.width != profile.map_size or layout.height != profile.map_size:
        violations.append(
            ConstraintViolation(
                "layout_size_mismatch",
                "layout",
                "layout dimensions must match the normalized profile",
            )
        )
    centers = [zone.center for zone in layout.zones]
    if len(centers) != len(set(centers)):
        violations.append(
            ConstraintViolation(
                "overlapping_zone_centers",
                "layout",
                "zone centers must be unique",
            )
        )
    zone_map = {zone.zone_id: zone for zone in layout.zones}
    if set(zone_map) != {zone.zone_id for zone in graph.zones}:
        violations.append(
            ConstraintViolation(
                "layout_zone_set_mismatch",
                "layout",
                "layout zones must exactly match topology zones",
            )
        )
    edge_map = {edge.edge_id: edge for edge in graph.edges}
    route_ids = [route.edge_id for route in layout.routes]
    if len(route_ids) != len(set(route_ids)) or set(route_ids) != set(edge_map):
        violations.append(
            ConstraintViolation(
                "route_set_mismatch",
                "layout",
                "layout must contain exactly one route for every topology edge",
            )
        )
    for route in layout.routes:
        if not route.cells:
            violations.append(
                ConstraintViolation(
                    "empty_route", "layout", f"route {route.edge_id} is empty"
                )
            )
            continue
        if any(not _in_bounds(point, layout.width, layout.height) for point in route.cells):
            violations.append(
                ConstraintViolation(
                    "route_out_of_bounds",
                    "layout",
                    f"route {route.edge_id} leaves the map",
                )
            )
        if any(
            first.manhattan(second) != 1
            for first, second in zip(route.cells, route.cells[1:])
        ):
            violations.append(
                ConstraintViolation(
                    "route_not_contiguous",
                    "layout",
                    f"route {route.edge_id} is not cardinally contiguous",
                )
            )
        edge = edge_map.get(route.edge_id)
        if edge is not None and edge.source_zone_id in zone_map and edge.target_zone_id in zone_map:
            endpoints = {route.cells[0], route.cells[-1]}
            expected = {
                zone_map[edge.source_zone_id].center,
                zone_map[edge.target_zone_id].center,
            }
            if endpoints != expected:
                violations.append(
                    ConstraintViolation(
                        "route_endpoint_mismatch",
                        "layout",
                        f"route {route.edge_id} does not connect its zones",
                    )
                )
    spacing = decision_distances(layout)
    if spacing:
        bad = [
            value
            for value in spacing
            if value < profile.density.decision_spacing_min
            or value > profile.density.decision_spacing_max
        ]
        if bad:
            violations.append(
                ConstraintViolation(
                    "decision_spacing_out_of_range",
                    "layout",
                    "route decision spacing lies outside the configured range",
                    (("values", bad),),
                )
            )
    return tuple(violations)


def decision_distances(layout: SpatialLayout) -> tuple[int, ...]:
    anchors_by_edge: dict[str, list[DecisionAnchor]] = {}
    for anchor in layout.decision_anchors:
        anchors_by_edge.setdefault(anchor.edge_id, []).append(anchor)
    distances: list[int] = []
    for route in layout.routes:
        route_anchors = anchors_by_edge.get(route.edge_id, [])
        cursor = 0
        for anchor in route_anchors:
            try:
                offset = route.cells.index(anchor.point, cursor + 1)
            except ValueError:
                continue
            distances.append(offset - cursor)
            cursor = offset
        final = (len(route.cells) - 1) - cursor
        if final:
            distances.append(final)
    return tuple(distances)


def _choose_route(
    start: Point,
    end: Point,
    *,
    occupied: set[Point],
    unrelated_centers: tuple[Point, ...],
    width: int,
    height: int,
    spacing_min: int,
    spacing_max: int,
    rng: DeterministicRng,
) -> tuple[Point, ...]:
    """Choose a route that leaves decision clearance around other zones.

    Two-axis L routes are intentionally simple and native-friendly, but an
    arbitrary orientation can run a side edge through another zone's required
    encounter. Include short orthogonal detours when both direct orientations
    cross a nearby zone, then score all candidates before partitioning decision
    spacing. This keeps anchors on traversable corridors without moving their
    planned points during placement.
    """
    candidates = [
        _l_route(start, end, horizontal_first=True),
        _l_route(start, end, horizontal_first=False),
    ]
    for offset in (-4, -3, -2, 2, 3, 4):
        shifted_y = start.y + offset
        if 0 <= shifted_y < height:
            candidates.append(
                _polyline_route(
                    (
                        start,
                        Point(start.x, shifted_y),
                        Point(end.x, shifted_y),
                        end,
                    )
                )
            )
        shifted_x = start.x + offset
        if 0 <= shifted_x < width:
            candidates.append(
                _polyline_route(
                    (
                        start,
                        Point(shifted_x, start.y),
                        Point(shifted_x, end.y),
                        end,
                    )
                )
            )
    unique_candidates: list[tuple[Point, ...]] = []
    seen: set[tuple[Point, ...]] = set()
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique_candidates.append(candidate)
    endpoints = {start, end}
    scores: list[tuple[int, int, int, int]] = []
    for cells in unique_candidates:
        route_distance = len(cells) - 1
        minimum_segments = math.ceil(route_distance / spacing_max)
        maximum_segments = route_distance // spacing_min
        partition_penalty = int(minimum_segments > maximum_segments)
        near_zone_penalty = sum(
            max(0, 4 - cell.manhattan(center))
            for cell in cells
            for center in unrelated_centers
        )
        overlap_penalty = sum(
            cell in occupied and cell not in endpoints
            for cell in cells
        )
        scores.append((partition_penalty, near_zone_penalty, overlap_penalty, len(cells)))
    best = min(scores)
    choices = [index for index, score in enumerate(scores) if score == best]
    return unique_candidates[choices[rng.randbelow(len(choices))]]


def _polyline_route(points: tuple[Point, ...]) -> tuple[Point, ...]:
    cells: list[Point] = [points[0]]
    for start, end in zip(points, points[1:]):
        if start.x != end.x and start.y != end.y:
            raise ValueError("route polyline segments must be axis-aligned")
        segment = _l_route(
            start,
            end,
            horizontal_first=start.y == end.y,
        )
        cells.extend(segment[1:])
    return tuple(cells)

def _l_route(start: Point, end: Point, *, horizontal_first: bool) -> tuple[Point, ...]:
    cells = [start]
    current = start
    axes = ("x", "y") if horizontal_first else ("y", "x")
    for axis in axes:
        target = end.x if axis == "x" else end.y
        value = current.x if axis == "x" else current.y
        step = 1 if target > value else -1
        while value != target:
            value += step
            current = Point(value, current.y) if axis == "x" else Point(current.x, value)
            cells.append(current)
    return tuple(cells)


def _partition_distance(
    total: int,
    minimum: int,
    maximum: int,
    rng: DeterministicRng,
) -> tuple[int, ...]:
    if total <= 0:
        raise GenerationFailure(
            "layout",
            (
                ConstraintViolation(
                    "zero_length_route",
                    "layout",
                    "topology edge endpoints embedded at the same point",
                ),
            ),
        )
    minimum_segments = math.ceil(total / maximum)
    maximum_segments = total // minimum
    if minimum_segments > maximum_segments:
        raise GenerationFailure(
            "layout",
            (
                ConstraintViolation(
                    "unpartitionable_route",
                    "layout",
                    "route length cannot be partitioned into configured decision spacing",
                    (
                        ("routeLength", total),
                        ("minimum", minimum),
                        ("maximum", maximum),
                    ),
                ),
            ),
        )
    count = rng.randint(minimum_segments, maximum_segments)
    segments = [minimum] * count
    remainder = total - minimum * count
    order = list(range(count))
    rng.shuffle(order)
    while remainder:
        changed = False
        for index in order:
            if remainder == 0:
                break
            if segments[index] < maximum:
                segments[index] += 1
                remainder -= 1
                changed = True
        if not changed:
            raise AssertionError("validated decision partition could not consume remainder")
    return tuple(segments)


def _in_bounds(point: Point, width: int, height: int) -> bool:
    return 0 <= point.x < width and 0 <= point.y < height
