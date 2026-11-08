"""Footprint-aware gameplay and path-safe scenery placement."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, replace
from typing import Iterable

from .catalog import (
    CatalogBuildError,
    CatalogEntry,
    ContentCatalogSnapshot,
    ContentKind,
)
from .model import (
    ConstraintViolation,
    Difficulty,
    Footprint,
    GenerationFailure,
    Placement,
    PlacementKind,
    Point,
    ProgressionGraph,
    SpatialLayout,
    TerrainGrid,
)
from .native_catalog import NativeEncounterTemplate
from .rng import DeterministicRng


_ENTRY_KIND: dict[PlacementKind, ContentKind] = {
    PlacementKind.PLAYER_START: ContentKind.SETTLEMENT,
    PlacementKind.AI_SETTLEMENT: ContentKind.SETTLEMENT,
    PlacementKind.NEUTRAL_CITY: ContentKind.SETTLEMENT,
    PlacementKind.OBJECTIVE: ContentKind.OBJECTIVE,
    PlacementKind.ENCOUNTER: ContentKind.ENCOUNTER,
    PlacementKind.REWARD: ContentKind.REWARD,
    PlacementKind.INTERACTABLE: ContentKind.INTERACTABLE,
    PlacementKind.QUEST_GIVER: ContentKind.INTERACTABLE,
    PlacementKind.SCENERY: ContentKind.SCENERY,
}


@dataclass(frozen=True)
class PlacementRngStreams:
    required: DeterministicRng
    anchors: DeterministicRng
    optional: DeterministicRng
    scenery: DeterministicRng


@dataclass(frozen=True)
class _EncounterPlan:
    metadata: tuple[tuple[str, object], ...]
    alignment: Point
    footprint: Footprint


def place_scenario_content(
    graph: ProgressionGraph,
    layout: SpatialLayout,
    terrain: TerrainGrid,
    profile: ScenarioProfileV1,
    catalog: ContentCatalogSnapshot,
    rngs: PlacementRngStreams,
) -> tuple[Placement, ...]:
    profile = profile.normalized()
    required_rng = rngs.required
    anchor_rng = rngs.anchors
    optional_rng = rngs.optional
    scenery_rng = rngs.scenery
    pools = {
        kind: catalog.eligible(content_kind, biomes=profile.biomes)
        for kind, content_kind in _ENTRY_KIND.items()
    }
    needed = {
        zone.required_placement
        for zone in graph.zones
        if zone.required_placement is not None
    }
    if layout.decision_anchors:
        needed.update(
            (
                PlacementKind.ENCOUNTER,
                PlacementKind.REWARD,
                PlacementKind.INTERACTABLE,
            )
        )
    if profile.density.scenery_per_100_tiles > 0:
        needed.add(PlacementKind.SCENERY)
    if profile.topology.neutral_city_count > 0:
        needed.add(PlacementKind.NEUTRAL_CITY)
    missing = sorted(kind.value for kind in needed if not pools[kind])
    if missing:
        raise GenerationFailure(
            "placement",
            (
                ConstraintViolation(
                    "empty_content_pool",
                    "placement",
                    "catalog has no eligible native content for required placement kinds",
                    (("kinds", missing),),
                ),
            ),
            seed=profile.seed,
        )

    state = _PlacementState(
        layout.width,
        layout.height,
        terrain,
        reserved=layout.route_cells,
        reachability_root=layout.zone(graph.start_zone_id).center,
    )
    placements: list[Placement] = []
    ai_ordinal = 0
    objective_ordinal = 0
    anchor_clearance = _decision_anchor_clearance_cells(layout)
    # Manhattan "full map" from any cell reaches the opposite corner only when
    # the radius covers width+height-2, not max(width, height).
    full_map_radius = max(layout.width + layout.height - 2, 0)

    for zone in graph.zones:
        kind = zone.required_placement
        if kind is None:
            continue
        target = layout.zone(zone.zone_id).center
        placement_id = f"zone_{zone.zone_id}_{kind.value}"
        alignment: tuple[Point, ...] | None = None
        metadata: list[tuple[str, object]] = []
        if kind is PlacementKind.PLAYER_START:
            faction, owner = profile.player_faction, 1
            entry, hero = _settlement_selection(catalog, faction, required_rng)
            metadata.extend(
                (("owner", owner), ("factionSid", faction), ("heroSid", hero.sid))
            )
        elif kind is PlacementKind.AI_SETTLEMENT:
            faction = profile.ai_factions[ai_ordinal]
            ai_ordinal += 1
            entry, hero = _settlement_selection(catalog, faction, required_rng)
            metadata.extend(
                (
                    ("owner", ai_ordinal + 1),
                    ("factionSid", faction),
                    ("heroSid", hero.sid),
                )
            )
        else:
            entry = _gameplay_entry(catalog, pools, kind, terrain, target, required_rng)
        if kind is PlacementKind.OBJECTIVE:
            metadata.extend(
                (
                    ("objectiveIndex", objective_ordinal),
                    ("counterSid", f"proc_objective_{objective_ordinal:02d}"),
                )
            )
            objective_ordinal += 1
        elif kind is PlacementKind.ENCOUNTER:
            encounter = _encounter_plan(
                catalog,
                terrain,
                profile,
                placement_id,
                target,
                zone.risk_tier,
                required_rng,
            )
            metadata.extend(encounter.metadata)
            alignment = (encounter.alignment,)
            entry = replace(entry, footprint=encounter.footprint)
        # Keep zone processing order intact so earlier roaming content can still
        # diversify later settlement footprints. Protect corridor anchors only
        # while an encounter may search the whole map.
        clearance_held = False
        if kind is PlacementKind.ENCOUNTER:
            state.reserved.update(anchor_clearance)
            clearance_held = True
        try:
            placements.append(
                _place_near(
                    state,
                    entry,
                    placement_id=placement_id,
                    kind=kind,
                    zone_id=zone.zone_id,
                    target=target,
                    risk_tier=zone.risk_tier,
                    metadata=tuple(metadata),
                    alignment=alignment,
                    rng=required_rng,
                    search_radius=(
                        full_map_radius if kind is PlacementKind.ENCOUNTER else 5
                    ),
                )
            )
        finally:
            if clearance_held:
                state.reserved.difference_update(anchor_clearance)

    anchor_kinds = (
        PlacementKind.ENCOUNTER,
        PlacementKind.REWARD,
        PlacementKind.INTERACTABLE,
    )
    anchors_by_point: dict[Point, list[str]] = {}
    for anchor in layout.decision_anchors:
        anchors_by_point.setdefault(anchor.point, []).append(anchor.anchor_id)
    for index, (point, anchor_ids) in enumerate(anchors_by_point.items()):
        offset = (index + anchor_rng.randbelow(len(anchor_kinds))) % len(anchor_kinds)
        kind_order = anchor_kinds[offset:] + anchor_kinds[:offset]
        zone = _nearest_zone(graph, layout, point)
        placements.append(
            _place_decision_anchor(
                state,
                catalog,
                pools,
                terrain,
                profile,
                tuple(anchor_ids),
                point,
                zone.zone_id,
                zone.risk_tier,
                kind_order,
                anchor_rng,
            )
        )

    # Neutral cities roam after anchors so radius-9 town footprints cannot
    # strand exact corridor interactions; anchor occupied cells already block
    # that ring.
    neutral_zones = tuple(
        zone for zone in graph.zones
        if zone.zone_id != graph.start_zone_id and zone.zone_id != graph.victory_zone_id
    )
    for index in range(profile.topology.neutral_city_count):
        if not neutral_zones:
            raise GenerationFailure(
                "placement",
                (ConstraintViolation("neutral_city_zone_missing", "placement", "neutral cities require a non-start zone"),),
                seed=profile.seed,
            )
        zone = neutral_zones[index % len(neutral_zones)]
        target = layout.zone(zone.zone_id).center
        entry = _neutral_city_selection(catalog)
        faction = profile.factions[index % len(profile.factions)]
        placements.append(
            _place_near(
                state,
                entry,
                placement_id=f"neutral_city_{index:02d}",
                kind=PlacementKind.NEUTRAL_CITY,
                zone_id=zone.zone_id,
                target=target,
                risk_tier=zone.risk_tier,
                metadata=(("factionSid", faction), ("owner", -1)),
                rng=required_rng,
                search_radius=9,
            )
        )

    optional_target = round(
        len(graph.zones) * profile.density.optional_gameplay_per_zone
    )
    optional_kinds = (
        PlacementKind.REWARD,
        PlacementKind.INTERACTABLE,
        PlacementKind.ENCOUNTER,
    )
    # Optional content should distribute across the whole traversable surface,
    # not stack all eighty-plus decisions on the sixteen zone centers. Native
    # maps use broad object fields; sampling global targets keeps encounters,
    # rewards, and interactables dense without creating a single crowded hub.
    for index in range(optional_target):
        kind = optional_kinds[index % len(optional_kinds)]
        target = _open_surface_target(state, layout.width, layout.height, optional_rng)
        zone = _nearest_zone(graph, layout, target)
        placement_id = f"optional_{index:03d}_{kind.value}"
        entry = _gameplay_entry(catalog, pools, kind, terrain, target, optional_rng)
        metadata: list[tuple[str, object]] = [("optional", True)]
        alignment: tuple[Point, ...] | None = None
        if kind is PlacementKind.ENCOUNTER:
            encounter = _encounter_plan(
                catalog, terrain, profile, placement_id, target, zone.risk_tier, optional_rng
            )
            metadata.extend(encounter.metadata)
            alignment = (encounter.alignment,)
            entry = replace(entry, footprint=encounter.footprint)
        placements.append(
            _place_near(
                state,
                entry,
                placement_id=placement_id,
                kind=kind,
                zone_id=zone.zone_id,
                target=target,
                risk_tier=zone.risk_tier,
                metadata=tuple(metadata),
                alignment=alignment,
                rng=optional_rng,
                # Optional decisions are sampled over the whole surface. A
                # short local search can report a false footprint failure in a
                # crowded pocket even when the rest of the map has room. Keep
                # the target as the first choice, then search the full map
                # deterministically before failing closed.
                search_radius=full_map_radius,
            )
        )

    state.reserve_interaction_paths(placements)

    scenery_target = round(
        layout.width
        * layout.height
        * profile.density.scenery_per_100_tiles
        / 100.0
    )
    scenery_entries = pools[PlacementKind.SCENERY]
    scenery_placements: list[Placement] = []
    route_clearance = {
        Point(route.x + dx, route.y + dy)
        for route in layout.route_cells
        for dx, dy in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1))
        if 0 <= route.x + dx < layout.width and 0 <= route.y + dy < layout.height
    }
    attempts = 0
    while len(scenery_placements) < scenery_target:
        attempts += 1
        if attempts > max(100, scenery_target * 200):
            actual = sum(
                item.kind is PlacementKind.SCENERY for item in placements
            )
            raise GenerationFailure(
                "placement",
                (
                    ConstraintViolation(
                        "scenery_density_unsatisfied",
                        "placement",
                        "path-safe placement could not meet configured scenery density",
                        (("target", scenery_target), ("actual", actual)),
                    ),
                ),
                seed=profile.seed,
            )
        if scenery_placements and scenery_rng.randbelow(100) < 65:
            anchor = scenery_rng.choice(scenery_placements)
            matching = tuple(
                candidate
                for candidate in scenery_entries
                if candidate.sid == anchor.content_sid
            )
            entry = matching[0] if matching else scenery_rng.choice(scenery_entries)
            target = Point(
                anchor.origin.x + scenery_rng.randint(-6, 6),
                anchor.origin.y + scenery_rng.randint(-6, 6),
            )
        else:
            entry = scenery_rng.choice(scenery_entries)
            target = Point(
                scenery_rng.randint(1, layout.width - 2),
                scenery_rng.randint(1, layout.height - 2),
            )
        if target in route_clearance:
            continue
        try:
            placement = _place_exact(
                state,
                entry,
                placement_id=f"scenery_{len(placements):04d}",
                kind=PlacementKind.SCENERY,
                zone_id=_nearest_zone(graph, layout, target).zone_id,
                target=target,
                risk_tier=0,
                metadata=(),
                rng=scenery_rng,
            )
        except _CannotPlace:
            continue
        # Route cells are reserved for the progression graph, so scenery cannot
        # occupy the only connection between zones. Final validation performs
        # the complete reachability check after the whole scenery pass; doing
        # a full BFS for every decorative object made large maps needlessly slow.
        placements.append(placement)
        scenery_placements.append(placement)

    violations = validate_placements(
        tuple(placements),
        graph,
        layout,
        terrain,
        profile,
    )
    if violations:
        raise GenerationFailure("placement", violations, seed=profile.seed)
    return tuple(placements)


def validate_placements(
    placements: tuple[Placement, ...],
    graph: ProgressionGraph,
    layout: SpatialLayout,
    terrain: TerrainGrid,
    profile: ScenarioProfileV1,
) -> tuple[ConstraintViolation, ...]:
    violations: list[ConstraintViolation] = []
    ids = [placement.placement_id for placement in placements]
    if len(ids) != len(set(ids)):
        violations.append(
            ConstraintViolation(
                "duplicate_placement_id",
                "placement",
                "placement IDs must be unique",
            )
        )
    occupied: dict[Point, str] = {}
    state = _PlacementState(
        layout.width,
        layout.height,
        terrain,
        reserved=layout.route_cells,
    )
    for placement in placements:
        cells = placement.footprint.translated_occupied(placement.origin)
        all_cells = cells + placement.footprint.translated_interaction(placement.origin)
        if any(not state.in_bounds(point) for point in all_cells + (placement.origin,)):
            violations.append(
                ConstraintViolation(
                    "footprint_out_of_bounds",
                    "placement",
                    f"placement {placement.placement_id} leaves the map",
                )
            )
        for point in cells:
            previous = occupied.get(point)
            if previous is not None:
                violations.append(
                    ConstraintViolation(
                        "overlapping_footprints",
                        "placement",
                        f"{placement.placement_id} overlaps {previous}",
                        (("x", point.x), ("y", point.y)),
                    )
                )
            occupied[point] = placement.placement_id
        state.add(placement)
    populated_anchor_ids = {
        anchor_id
        for placement in placements
        for anchor_id in _placement_decision_anchor_ids(placement)
    }
    expected_anchor_ids = {anchor.anchor_id for anchor in layout.decision_anchors}
    missing_anchors = sorted(expected_anchor_ids - populated_anchor_ids)
    if missing_anchors:
        violations.append(
            ConstraintViolation(
                "decision_anchor_unpopulated",
                "placement",
                "every planned decision anchor must receive gameplay content",
                (("anchorIds", missing_anchors),),
            )
        )
    anchor_points = {
        anchor.anchor_id: anchor.point for anchor in layout.decision_anchors
    }
    for placement in placements:
        placement_anchor_ids = _placement_decision_anchor_ids(placement)
        if not placement_anchor_ids:
            continue
        interaction = placement.footprint.translated_interaction(placement.origin)
        candidates = interaction or (placement.origin,)
        for anchor_id in placement_anchor_ids:
            if anchor_id not in anchor_points or anchor_points[anchor_id] not in candidates:
                violations.append(
                    ConstraintViolation(
                        "decision_anchor_displaced",
                        "placement",
                        f"placement {placement.placement_id} does not interact at planned anchor {anchor_id}",
                    )
                )
    if not _all_zone_centers_reachable(state, layout, graph.start_zone_id):
        violations.append(
            ConstraintViolation(
                "unreachable_progression",
                "placement",
                "placed footprints disconnect progression zones",
            )
        )
    reachable = state.reachable_from(layout.zone(graph.start_zone_id).center)
    for placement in placements:
        if not placement.interactive:
            continue
        interaction = placement.footprint.translated_interaction(placement.origin)
        candidates = interaction or (placement.origin,)
        if not any(point in reachable for point in candidates):
            violations.append(
                ConstraintViolation(
                    "blocked_interaction",
                    "placement",
                    f"interaction {placement.placement_id} is unreachable",
                )
            )
    expected_scenery = round(
        layout.width
        * layout.height
        * profile.density.scenery_per_100_tiles
        / 100.0
    )
    actual_scenery = sum(
        placement.kind is PlacementKind.SCENERY for placement in placements
    )
    if actual_scenery != expected_scenery:
        violations.append(
            ConstraintViolation(
                "scenery_density_mismatch",
                "placement",
                "scenery placement count does not match configured density",
                (("expected", expected_scenery), ("actual", actual_scenery)),
            )
        )
    return tuple(violations)


def _placement_decision_anchor_ids(placement: Placement) -> tuple[str, ...]:
    metadata = dict(placement.metadata)
    values = metadata.get("decisionAnchorIds")
    if isinstance(values, (list, tuple)):
        return tuple(str(value) for value in values)
    value = metadata.get("decisionAnchorId")
    return () if value is None else (str(value),)


# Off-route Chebyshev ring kept free until exact decision-anchor placement.
# Observed full-map encounter footprints reach about three cells from corridor
# anchors; smaller rings still let roaming content strand exact anchors.
_DECISION_ANCHOR_CLEARANCE = 3


def _decision_anchor_clearance_cells(layout: SpatialLayout) -> set[Point]:
    route_cells = set(layout.route_cells)
    protected: set[Point] = set()
    for anchor in layout.decision_anchors:
        for dy in range(-_DECISION_ANCHOR_CLEARANCE, _DECISION_ANCHOR_CLEARANCE + 1):
            for dx in range(-_DECISION_ANCHOR_CLEARANCE, _DECISION_ANCHOR_CLEARANCE + 1):
                point = Point(anchor.point.x + dx, anchor.point.y + dy)
                if (
                    0 <= point.x < layout.width
                    and 0 <= point.y < layout.height
                    and point not in route_cells
                ):
                    protected.add(point)
    return protected


class _CannotPlace(RuntimeError):
    pass


class _PlacementState:
    def __init__(
        self,
        width: int,
        height: int,
        terrain: TerrainGrid,
        *,
        reserved: Iterable[Point] = (),
        reachability_root: Point | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.terrain = terrain
        self.blocked = {
            Point(node % width, node // width)
            for node, value in enumerate(terrain.blocked)
            if value
        }
        self.origins: set[Point] = set()
        self.reserved = set(reserved)
        self.reachability_root = reachability_root
        self.interaction_groups: dict[str, set[Point]] = {}

    def in_bounds(self, point: Point) -> bool:
        return 0 <= point.x < self.width and 0 <= point.y < self.height

    def can_add(self, origin: Point, footprint: Footprint) -> bool:
        occupied = footprint.translated_occupied(origin)
        interactions = footprint.translated_interaction(origin)
        if not self.in_bounds(origin) or origin in self.origins:
            return False
        if any(not self.in_bounds(point) for point in occupied + interactions):
            return False
        if any(point in self.blocked or point in self.reserved for point in occupied):
            return False
        if interactions and all(point in self.blocked for point in interactions):
            return False
        return True

    def add(self, placement: Placement) -> None:
        self.blocked.update(
            placement.footprint.translated_occupied(placement.origin)
        )
        if placement.interactive:
            self.interaction_groups[placement.placement_id] = set(
                placement.footprint.translated_interaction(placement.origin)
                or (placement.origin,)
            )
        self.origins.add(placement.origin)

    def remove(self, placement: Placement) -> None:
        for point in placement.footprint.translated_occupied(placement.origin):
            self.blocked.discard(point)
        self.interaction_groups.pop(placement.placement_id, None)
        self.origins.discard(placement.origin)

    def interactions_open(self) -> bool:
        return all(
            any(point not in self.blocked for point in interactions)
            for interactions in self.interaction_groups.values()
        )
    def interactions_reachable(self) -> bool:
        if self.reachability_root is None:
            return True
        reachable = self.reachable_from(self.reachability_root)
        return all(
            any(point in reachable for point in interactions)
            for interactions in self.interaction_groups.values()
        )


    def reachable_from(self, start: Point) -> set[Point]:
        if not self.in_bounds(start) or start in self.blocked:
            return set()
        visited = {start}
        queue = deque([start])
        while queue:
            point = queue.popleft()
            for neighbor in (
                Point(point.x + 1, point.y),
                Point(point.x - 1, point.y),
                Point(point.x, point.y + 1),
                Point(point.x, point.y - 1),
            ):
                if (
                    self.in_bounds(neighbor)
                    and neighbor not in self.blocked
                    and neighbor not in visited
                ):
                    visited.add(neighbor)
                    queue.append(neighbor)
        return visited

    def reserve_interaction_paths(self, placements: Iterable[Placement]) -> None:
        """Protect one reachable path to every gameplay interaction.

        Decorative objects are placed after gameplay content. Reserving these
        shortest paths lets the scenery pass skip a full-map BFS per object
        without allowing a late visual blocker to strand an interaction.
        """
        if self.reachability_root is None:
            return
        parents: dict[Point, Point | None] = {self.reachability_root: None}
        queue = deque([self.reachability_root])
        while queue:
            point = queue.popleft()
            for neighbor in (
                Point(point.x + 1, point.y),
                Point(point.x - 1, point.y),
                Point(point.x, point.y + 1),
                Point(point.x, point.y - 1),
            ):
                if (
                    self.in_bounds(neighbor)
                    and neighbor not in self.blocked
                    and neighbor not in parents
                ):
                    parents[neighbor] = point
                    queue.append(neighbor)
        for placement in placements:
            if not placement.interactive:
                continue
            interactions = placement.footprint.translated_interaction(
                placement.origin
            ) or (placement.origin,)
            target = next((point for point in interactions if point in parents), None)
            if target is None:
                raise ValueError(
                    f"cannot protect unreachable interaction {placement.placement_id}"
                )
            while target is not None:
                self.reserved.add(target)
                target = parents[target]


def _place_decision_anchor(
    state: _PlacementState,
    catalog: ContentCatalogSnapshot,
    pools: dict[PlacementKind, tuple[CatalogEntry, ...]],
    terrain: TerrainGrid,
    profile: ScenarioProfileV1,
    anchor_ids: tuple[str, ...],
    point: Point,
    zone_id: str,
    risk_tier: int,
    kind_order: tuple[PlacementKind, ...],
    rng: DeterministicRng,
) -> Placement:
    if not anchor_ids:
        raise ValueError("decision anchor group cannot be empty")
    placement_id = f"decision_{anchor_ids[0]}"
    tried: list[str] = []
    for kind in kind_order:
        candidates = _gameplay_candidates(
            catalog, pools, kind, terrain, point, rng
        )
        tried.extend(
            f"{kind.value}:{entry.sid}" for entry in candidates
        )
        metadata: list[tuple[str, object]] = [
            ("decisionAnchorId", anchor_ids[0]),
            ("decisionAnchorIds", list(anchor_ids)),
        ]
        encounter: _EncounterPlan | None = None
        if kind is PlacementKind.ENCOUNTER:
            encounter = _encounter_plan(
                catalog,
                terrain,
                profile,
                placement_id,
                point,
                risk_tier,
                rng,
            )
            metadata.extend(encounter.metadata)
        for entry in candidates:
            if encounter is not None:
                entry = replace(entry, footprint=encounter.footprint)
            try:
                return _place_exact(
                    state,
                    entry,
                    placement_id=placement_id,
                    kind=kind,
                    zone_id=zone_id,
                    target=point,
                    risk_tier=risk_tier,
                    metadata=tuple(metadata),
                    rng=rng,
                    alignment=None if encounter is None else (encounter.alignment,),
                )
            except _CannotPlace:
                continue
    raise GenerationFailure(
        "placement",
        (
            ConstraintViolation(
                "decision_anchor_no_fitting_content",
                "placement",
                "no eligible native footprint can interact at the exact decision anchor",
                (("anchorIds", list(anchor_ids)), ("contentSids", tried)),
            ),
        ),
        seed=profile.seed,
    )


def _gameplay_entry(
    catalog: ContentCatalogSnapshot,
    pools: dict[PlacementKind, tuple[CatalogEntry, ...]],
    kind: PlacementKind,
    terrain: TerrainGrid,
    target: Point,
    rng: DeterministicRng,
) -> CatalogEntry:
    return _gameplay_candidates(
        catalog, pools, kind, terrain, target, rng
    )[0]


def _gameplay_candidates(
    catalog: ContentCatalogSnapshot,
    pools: dict[PlacementKind, tuple[CatalogEntry, ...]],
    kind: PlacementKind,
    terrain: TerrainGrid,
    target: Point,
    rng: DeterministicRng,
) -> tuple[CatalogEntry, ...]:
    pool_name = {
        PlacementKind.REWARD: "content_pool_default_resources",
        PlacementKind.INTERACTABLE: "content_pool_default_unguarded",
    }.get(kind)
    if pool_name is None:
        candidates = list(pools[kind])
        rng.shuffle(candidates)
        return tuple(candidates)
    biome = terrain.biome_map[target.node(terrain.width)]
    try:
        weighted = catalog.pool_entries(
            pool_name,
            kinds=(_ENTRY_KIND[kind],),
            biome=biome,
        )
    except CatalogBuildError as ex:
        raise GenerationFailure(
            "placement",
            (
                ConstraintViolation(
                    "native_content_pool_unresolved",
                    "placement",
                    str(ex),
                    (("placementKind", kind.value), ("biome", biome)),
                ),
            ),
        ) from ex
    return _weighted_order(weighted, rng)


def _weighted_choice(
    weighted: tuple[tuple[CatalogEntry, int], ...],
    rng: DeterministicRng,
) -> CatalogEntry:
    total = sum(weight for _entry, weight in weighted)
    if total <= 0:
        raise ValueError("weighted content pool must have positive total weight")
    roll = rng.randbelow(total)
    for entry, weight in weighted:
        if roll < weight:
            return entry
        roll -= weight
    raise AssertionError("weighted content selection exhausted positive pool")


def _weighted_order(
    weighted: tuple[tuple[CatalogEntry, int], ...],
    rng: DeterministicRng,
) -> tuple[CatalogEntry, ...]:
    remaining = list(weighted)
    ordered: list[CatalogEntry] = []
    while remaining:
        selected = _weighted_choice(tuple(remaining), rng)
        ordered.append(selected)
        index = next(
            i for i, (entry, _weight) in enumerate(remaining) if entry == selected
        )
        remaining.pop(index)
    return tuple(ordered)


def _neutral_city_selection(catalog: ContentCatalogSnapshot) -> CatalogEntry:
    matches = tuple(
        entry
        for entry in catalog.eligible(ContentKind.SETTLEMENT)
        if entry.sid == "random-city"
    )
    if len(matches) != 1:
        raise GenerationFailure(
            "placement",
            (ConstraintViolation(
                "neutral_city_content_missing",
                "placement",
                "profile requests neutral cities but catalog has no unique random-city ObjectConfig",
                (("count", len(matches)),),
            ),),
        )
    return matches[0]

def _settlement_selection(
    catalog: ContentCatalogSnapshot,
    faction_sid: str,
    rng: DeterministicRng,
) -> tuple[CatalogEntry, CatalogEntry]:
    settlements = tuple(
        entry
        for entry in catalog.eligible(ContentKind.SETTLEMENT)
        if entry.sid == "city-spawner"
    )
    heroes = catalog.entries_for_faction(ContentKind.HERO, faction_sid)
    if len(settlements) != 1 or not heroes:
        raise GenerationFailure(
            "placement",
            (
                ConstraintViolation(
                    "faction_start_content_missing",
                    "placement",
                    "faction requires an eligible matching city and hero",
                    (
                        ("factionSid", faction_sid),
                        ("citySpawnerCount", len(settlements)),
                        ("heroCount", len(heroes)),
                    ),
                ),
            ),
        )
    return rng.choice(settlements), rng.choice(heroes)


def _encounter_plan(
    catalog: ContentCatalogSnapshot,
    terrain: TerrainGrid,
    profile: ScenarioProfileV1,
    placement_id: str,
    target: Point,
    risk_tier: int,
    rng: DeterministicRng,
) -> _EncounterPlan:

    templates = tuple(
        template
        for template in catalog.native_generator.encounter_templates
        if template.guarded
        and len(template.guards) == 1
        and template.road_target is not None
        and template.entrances
        and template.relative_frequency > 0
        and 3 <= template.width <= 6
        and 3 <= template.height <= 6
    )
    if not templates:
        raise GenerationFailure(
            "placement",
            (
                ConstraintViolation(
                    "encounter_template_missing",
                    "placement",
                    "catalog has no eligible guarded native encounter template",
                ),
            ),
        )
    enemy_faction = rng.choice(profile.ai_factions) if profile.ai_factions else "neutral"
    units = catalog.entries_for_faction(ContentKind.UNIT, enemy_faction)
    valued_units = tuple(
        unit
        for unit in units
        if isinstance(unit.metadata_value("squadValue"), (int, float))
        and float(unit.metadata_value("squadValue")) > 0
    )
    if not valued_units:
        raise GenerationFailure(
            "placement",
            (
                ConstraintViolation(
                    "encounter_unit_missing",
                    "placement",
                    "AI faction has no eligible unit with a positive squadValue",
                    (("factionSid", enemy_faction),),
                ),
            ),
        )
    desired_tier = max(1, risk_tier + 1)
    closest_delta = min(
        abs(int(unit.metadata_value("tier", desired_tier)) - desired_tier)
        for unit in valued_units
    )
    candidates = tuple(
        unit
        for unit in valued_units
        if abs(int(unit.metadata_value("tier", desired_tier)) - desired_tier)
        == closest_delta
    )
    unit = rng.choice(candidates)
    multiplier = {
        Difficulty.EASY: 0.8,
        Difficulty.NORMAL: 1.0,
        Difficulty.HARD: 1.25,
        Difficulty.EXPERT: 1.5,
    }[profile.difficulty]
    requested = max(1, round(600 * (risk_tier + 1) * multiplier))
    squad_value = float(unit.metadata_value("squadValue"))
    count = max(1, round(requested / squad_value))
    actual_value = round(count * squad_value, 3)
    template = _weighted_template_choice(templates, rng)
    squad_sid = f"{placement_id}_squad"
    biome = terrain.biome_map[target.node(terrain.width)]
    buildings: list[dict[str, object]] = []
    for index, slot in enumerate(template.buildings):
        entry = _encounter_slot_content(
            catalog,
            pool_name="content_pool_default_unguarded",
            kind=ContentKind.INTERACTABLE,
            biome=biome,
            width=slot.width,
            height=slot.height,
            rng=rng,
        )
        buildings.append(
            {
                **slot.to_dict(),
                "contentSid": entry.sid,
                "entitySid": f"{placement_id}_building_{index:02d}",
            }
        )
    pickups: list[dict[str, object]] = []
    for index, slot in enumerate(template.pickups):
        entry = _encounter_slot_content(
            catalog,
            pool_name="content_pool_default_resources",
            kind=ContentKind.REWARD,
            biome=biome,
            width=1,
            height=1,
            rng=rng,
        )
        pickups.append(
            {
                **slot.to_dict(),
                "contentSid": entry.sid,
                "entitySid": f"{placement_id}_pickup_{index:02d}",
            }
        )
    instance = {
        "template": template.to_dict(),
        "mirroredX": False,
        "mirroredY": False,
        "guards": [
            {
                "position": template.guards[0].to_dict(),
                "entitySid": placement_id,
                "squadSid": squad_sid,
            }
        ],
        "buildings": buildings,
        "pickups": pickups,
    }
    road_target = template.road_target
    if road_target is None:
        raise AssertionError("filtered encounter template has no road target")
    occupied_cells = {
        Point(index % template.width, index // template.width)
        for index, tile_content in enumerate(template.tile_contents)
        if tile_content != 0
    }
    occupied_cells.update(template.guards)
    occupied_cells.update(slot.position for slot in template.pickups)
    for slot in template.buildings:
        occupied_cells.update(
            Point(slot.position.x + x, slot.position.y + y)
            for y in range(slot.height)
            for x in range(slot.width)
        )
    entrance = min(
        template.entrances,
        key=lambda point: (point.manhattan(road_target), point.y, point.x),
    )
    interactions = tuple(sorted(set((road_target, entrance))))
    occupied_cells.difference_update(interactions)
    occupied = tuple(sorted(occupied_cells))
    return _EncounterPlan(
        metadata=(
            ("squadMode", "exact"),
            ("factionSid", enemy_faction),
            (
                "exactSquad",
                {
                    "sid": squad_sid,
                    "unitProps": [{"sid": unit.sid, "count": count}],
                    "actualValue": actual_value,
                },
            ),
            ("encounterTemplateInstance", instance),
        ),
        footprint=Footprint(
            template.width,
            template.height,
            occupied,
            interactions,
        ),
        alignment=road_target,
    )


def _open_surface_target(
    state: _PlacementState,
    width: int,
    height: int,
    rng: DeterministicRng,
) -> Point:
    """Choose a global target away from the reserved route cells."""
    for _ in range(64):
        point = Point(rng.randint(1, width - 2), rng.randint(1, height - 2))
        if point not in state.reserved:
            return point
    # The fallback is deterministic and still lets _place_near perform the
    # footprint/reachability check; it is not a content substitution.
    return Point(width // 2, height // 2)


def _weighted_template_choice(
    templates: tuple[NativeEncounterTemplate, ...],
    rng: DeterministicRng,
) -> NativeEncounterTemplate:
    total = sum(template.relative_frequency for template in templates)
    roll = rng.random() * total
    for template in templates:
        if roll < template.relative_frequency:
            return template
        roll -= template.relative_frequency
    return templates[-1]


def _encounter_slot_content(
    catalog: ContentCatalogSnapshot,
    *,
    pool_name: str,
    kind: ContentKind,
    biome: str,
    width: int,
    height: int,
    rng: DeterministicRng,
) -> CatalogEntry:
    try:
        weighted = catalog.pool_entries(
            pool_name,
            kinds=(kind,),
            biome=biome,
        )
    except CatalogBuildError as ex:
        raise GenerationFailure(
            "placement",
            (
                ConstraintViolation(
                    "encounter_slot_pool_unresolved",
                    "placement",
                    str(ex),
                    (("poolName", pool_name), ("biome", biome)),
                ),
            ),
        ) from ex
    fitting: list[tuple[CatalogEntry, int]] = []
    for entry, weight in weighted:
        occupied_width, occupied_height = _occupied_extent(entry.footprint)
        if (
            occupied_width > 0
            and occupied_height > 0
            and occupied_width <= width
            and occupied_height <= height
        ):
            fitting.append((entry, weight))
    if not fitting:
        raise GenerationFailure(
            "placement",
            (
                ConstraintViolation(
                    "encounter_slot_content_missing",
                    "placement",
                    "native encounter slot has no eligible fitting content",
                    (
                        ("poolName", pool_name),
                        ("biome", biome),
                        ("width", width),
                        ("height", height),
                    ),
                ),
            ),
        )
    return _weighted_choice(tuple(fitting), rng)


def _occupied_extent(footprint: Footprint) -> tuple[int, int]:
    if not footprint.occupied:
        return (0, 0)
    xs = tuple(point.x for point in footprint.occupied)
    ys = tuple(point.y for point in footprint.occupied)
    return (max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)

def _place_near(
    state: _PlacementState,
    entry: CatalogEntry,
    *,
    placement_id: str,
    kind: PlacementKind,
    zone_id: str,
    target: Point,
    risk_tier: int,
    metadata: tuple[tuple[str, object], ...],
    rng: DeterministicRng,
    alignment: tuple[Point, ...] | None = None,
    search_radius: int,
) -> Placement:
    candidates = _points_by_radius(target, search_radius)
    grouped: dict[int, list[Point]] = {}
    for point in candidates:
        grouped.setdefault(point.manhattan(target), []).append(point)
    for distance in sorted(grouped):
        points = sorted(grouped[distance])
        rng.shuffle(points)
        for point in points:
            try:
                placement = _place_exact(
                    state,
                    entry,
                    placement_id=placement_id,
                    kind=kind,
                    zone_id=zone_id,
                    target=point,
                    risk_tier=risk_tier,
                    metadata=metadata,
                    rng=rng,
                    alignment=alignment,
                )
            except _CannotPlace:
                continue
            if _placement_interaction_reachable(state, placement):
                return placement
            state.remove(placement)
    raise GenerationFailure(
        "placement",
        (
            ConstraintViolation(
                "footprint_cannot_fit",
                "placement",
                f"no valid footprint position for {placement_id}",
                (("contentSid", entry.sid), ("target", target.to_dict())),
            ),
        ),
    )


def _place_exact(
    state: _PlacementState,
    entry: CatalogEntry,
    *,
    placement_id: str,
    kind: PlacementKind,
    zone_id: str,
    target: Point,
    risk_tier: int,
    metadata: tuple[tuple[str, object], ...],
    rng: DeterministicRng,
    alignment: tuple[Point, ...] | None = None,
) -> Placement:
    local_interactions = list(
        entry.footprint.interaction if alignment is None else alignment
    ) or [Point(0, 0)]
    rng.shuffle(local_interactions)
    interactive = kind is not PlacementKind.SCENERY
    for local in local_interactions:
        origin = Point(target.x - local.x, target.y - local.y)
        if not state.can_add(origin, entry.footprint):
            continue
        node = origin.node(state.width)
        placement_metadata = metadata
        placement = Placement(
            placement_id=placement_id,
            kind=kind,
            content_sid=entry.sid,
            origin=origin,
            node=node,
            zone_id=zone_id,
            footprint=entry.footprint,
            interactive=interactive,
            risk_tier=risk_tier,
            metadata=placement_metadata,
        )
        state.add(placement)
        if (not state.interactions_open()) or (
            placement.interactive and not state.interactions_reachable()
        ):
            state.remove(placement)
            continue
        return placement
    raise _CannotPlace


def _all_zone_centers_reachable(
    state: _PlacementState,
    layout: SpatialLayout,
    start_zone_id: str,
) -> bool:
    reachable = state.reachable_from(layout.zone(start_zone_id).center)
    return all(zone.center in reachable for zone in layout.zones)


def _placement_interaction_reachable(
    state: _PlacementState,
    placement: Placement,
) -> bool:
    if not state.reserved:
        return False
    reachable = state.reachable_from(min(state.reserved))
    interactions = placement.footprint.translated_interaction(placement.origin)
    return any(point in reachable for point in interactions or (placement.origin,))

def _points_by_radius(center: Point, radius: int) -> list[Point]:
    return [
        Point(center.x + dx, center.y + dy)
        for dy in range(-radius, radius + 1)
        for dx in range(-radius, radius + 1)
        if abs(dx) + abs(dy) <= radius
    ]


def _nearest_zone(
    graph: ProgressionGraph,
    layout: SpatialLayout,
    point: Point,
):
    layout_zone = min(
        layout.zones,
        key=lambda zone: (point.manhattan(zone.center), zone.zone_id),
    )
    return graph.zone(layout_zone.zone_id)
