"""Archetype-specific progression graph construction and validation."""

from __future__ import annotations

from collections import deque

from .model import (
    Archetype,
    ConstraintViolation,
    GenerationFailure,
    PlacementKind,
    ProgressionEdge,
    ProgressionGraph,
    ZoneRole,
    ZoneSpec,
)
from .profile import ScenarioProfileV1
from .rng import DeterministicRng


_DEFAULT_ZONE_COUNT = {32: 8, 48: 12, 64: 16}


def build_progression_graph(
    profile: ScenarioProfileV1,
    rng: DeterministicRng,
) -> ProgressionGraph:
    profile = profile.normalized()
    if profile.archetype is Archetype.CONQUEST and profile.ai_count < 1:
        raise GenerationFailure(
            "topology",
            (
                ConstraintViolation(
                    "conquest_requires_ai",
                    "topology",
                    "conquest requires at least one AI faction",
                    (("aiCount", profile.ai_count),),
                ),
            ),
            seed=profile.seed,
        )
    target_count = profile.topology.zone_count or _DEFAULT_ZONE_COUNT[profile.map_size]
    risk_count = (
        profile.topology.high_risk_side_area_count
        if profile.topology.high_risk_side_areas_enabled
        else 0
    )
    minimum_primary = max(5, profile.ai_count + 2)
    primary_count = min(
        target_count - risk_count,
        max(minimum_primary, profile.map_size // 8 + 1),
    )
    if primary_count < minimum_primary or target_count < primary_count + risk_count:
        raise GenerationFailure(
            "topology",
            (
                ConstraintViolation(
                    "zone_budget_too_small",
                    "topology",
                    "zone count cannot satisfy the selected archetype and side-area policy",
                    (
                        ("zoneCount", target_count),
                        ("minimumPrimary", minimum_primary),
                        ("highRiskCount", risk_count),
                    ),
                ),
            ),
            seed=profile.seed,
        )

    zones: list[ZoneSpec] = []
    primary_ids = tuple(f"zone_{index:02d}" for index in range(primary_count))
    ai_settlement_indices = _ai_settlement_indices(
        profile.archetype, primary_count, profile.ai_count
    )
    for index, zone_id in enumerate(primary_ids):
        role, required = _primary_role(
            profile.archetype,
            index=index,
            count=primary_count,
            ai_settlement_indices=ai_settlement_indices,
        )
        zones.append(
            ZoneSpec(
                zone_id=zone_id,
                role=role,
                depth=index,
                risk_tier=_risk_tier(index, primary_count),
                required_placement=required,
            )
        )

    edges: list[ProgressionEdge] = []
    for index in range(primary_count - 1):
        edges.append(
            ProgressionEdge(
                edge_id=f"edge_primary_{index:02d}",
                source_zone_id=primary_ids[index],
                target_zone_id=primary_ids[index + 1],
                required=True,
                guard_tier=_risk_tier(index + 1, primary_count),
            )
        )

    remaining = target_count - primary_count
    side_index = 0
    side_ids: list[str] = []
    while side_index < remaining:
        zone_id = f"side_{side_index:02d}"
        is_high_risk = side_index < risk_count
        parent_index = rng.randint(1, max(1, primary_count - 2))
        parent_id = primary_ids[parent_index]
        if is_high_risk:
            role = ZoneRole.HIGH_RISK
            required = PlacementKind.ENCOUNTER
            risk_tier = 4
        elif profile.archetype is Archetype.EXPLORATION:
            role = ZoneRole.OBJECTIVE if side_index % 2 == 0 else ZoneRole.TRANSIT
            required = (
                PlacementKind.OBJECTIVE
                if role is ZoneRole.OBJECTIVE
                else PlacementKind.REWARD
            )
            risk_tier = min(3, _risk_tier(parent_index + 1, primary_count))
        elif profile.archetype is Archetype.CONQUEST:
            role = ZoneRole.TRANSIT
            required = PlacementKind.ENCOUNTER
            risk_tier = min(3, _risk_tier(parent_index + 1, primary_count))
        else:
            role = ZoneRole.TRANSIT
            required = PlacementKind.REWARD
            risk_tier = min(3, _risk_tier(parent_index + 1, primary_count))
        zones.append(
            ZoneSpec(
                zone_id=zone_id,
                role=role,
                depth=parent_index + 1,
                risk_tier=risk_tier,
                required_placement=required,
            )
        )
        edges.append(
            ProgressionEdge(
                edge_id=f"edge_side_{side_index:02d}",
                source_zone_id=parent_id,
                target_zone_id=zone_id,
                required=False,
                guard_tier=risk_tier,
            )
        )
        side_ids.append(zone_id)
        side_index += 1

    if profile.topology.optional_loops_enabled and side_ids:
        existing = {edge.endpoints() for edge in edges}
        candidates: list[tuple[str, str]] = []
        depths = {zone.zone_id: zone.depth for zone in zones}
        for side_id in side_ids:
            for primary_id in primary_ids[1:-1]:
                pair = frozenset((side_id, primary_id))
                if pair not in existing and abs(depths[side_id] - depths[primary_id]) <= 2:
                    candidates.append((side_id, primary_id))
        if candidates:
            source, target = rng.choice(sorted(candidates))
            edges.append(
                ProgressionEdge(
                    edge_id="edge_optional_loop_00",
                    source_zone_id=source,
                    target_zone_id=target,
                    required=False,
                    guard_tier=max(
                        next(zone.risk_tier for zone in zones if zone.zone_id == source),
                        next(zone.risk_tier for zone in zones if zone.zone_id == target),
                    ),
                )
            )

    graph = ProgressionGraph(
        archetype=profile.archetype,
        zones=tuple(zones),
        edges=tuple(edges),
        start_zone_id=primary_ids[0],
        victory_zone_id=primary_ids[-1],
        primary_path=primary_ids,
    )
    violations = validate_topology(graph, profile)
    if violations:
        raise GenerationFailure("topology", violations, seed=profile.seed)
    return graph


def validate_topology(
    graph: ProgressionGraph,
    profile: ScenarioProfileV1 | None = None,
) -> tuple[ConstraintViolation, ...]:
    violations: list[ConstraintViolation] = []
    ids = [zone.zone_id for zone in graph.zones]
    if len(ids) != len(set(ids)):
        violations.append(
            ConstraintViolation(
                "duplicate_zone_id", "topology", "zone IDs must be unique"
            )
        )
    edge_ids = [edge.edge_id for edge in graph.edges]
    if len(edge_ids) != len(set(edge_ids)):
        violations.append(
            ConstraintViolation(
                "duplicate_edge_id", "topology", "edge IDs must be unique"
            )
        )
    id_set = set(ids)
    starts = [zone for zone in graph.zones if zone.role is ZoneRole.START]
    victories = [zone for zone in graph.zones if zone.role is ZoneRole.VICTORY]
    if len(starts) != 1 or not starts or starts[0].zone_id != graph.start_zone_id:
        violations.append(
            ConstraintViolation(
                "invalid_start_zone",
                "topology",
                "graph must declare exactly one matching start zone",
            )
        )
    if (
        len(victories) != 1
        or not victories
        or victories[0].zone_id != graph.victory_zone_id
    ):
        violations.append(
            ConstraintViolation(
                "invalid_victory_zone",
                "topology",
                "graph must declare exactly one matching victory zone",
            )
        )
    pairs: set[frozenset[str]] = set()
    adjacency: dict[str, set[str]] = {zone_id: set() for zone_id in ids}
    for edge in graph.edges:
        if (
            edge.source_zone_id not in id_set
            or edge.target_zone_id not in id_set
            or edge.source_zone_id == edge.target_zone_id
        ):
            violations.append(
                ConstraintViolation(
                    "invalid_edge_endpoint",
                    "topology",
                    f"edge {edge.edge_id} has invalid endpoints",
                )
            )
            continue
        pair = edge.endpoints()
        if pair in pairs:
            violations.append(
                ConstraintViolation(
                    "duplicate_edge",
                    "topology",
                    f"edge {edge.edge_id} duplicates a zone connection",
                )
            )
        pairs.add(pair)
        adjacency[edge.source_zone_id].add(edge.target_zone_id)
        adjacency[edge.target_zone_id].add(edge.source_zone_id)
    if graph.start_zone_id in adjacency:
        visited = {graph.start_zone_id}
        queue = deque([graph.start_zone_id])
        while queue:
            current = queue.popleft()
            for neighbor in adjacency[current] - visited:
                visited.add(neighbor)
                queue.append(neighbor)
        missing = sorted(id_set - visited)
        if missing:
            violations.append(
                ConstraintViolation(
                    "unreachable_zones",
                    "topology",
                    "all zones must be reachable from the start",
                    (("zones", missing),),
                )
            )
    if (
        not graph.primary_path
        or graph.primary_path[0] != graph.start_zone_id
        or graph.primary_path[-1] != graph.victory_zone_id
        or len(set(graph.primary_path)) != len(graph.primary_path)
    ):
        violations.append(
            ConstraintViolation(
                "invalid_primary_path",
                "topology",
                "primary path must be a simple start-to-victory path",
            )
        )
    required_pairs = {
        edge.endpoints() for edge in graph.edges if edge.required
    }
    for source, target in zip(graph.primary_path, graph.primary_path[1:]):
        if frozenset((source, target)) not in required_pairs:
            violations.append(
                ConstraintViolation(
                    "primary_path_edge_missing",
                    "topology",
                    f"primary path lacks required edge {source}->{target}",
                )
            )
    if profile is not None:
        high_risk_count = sum(
            zone.role is ZoneRole.HIGH_RISK for zone in graph.zones
        )
        expected = (
            profile.topology.high_risk_side_area_count
            if profile.topology.high_risk_side_areas_enabled
            else 0
        )
        if high_risk_count != expected:
            violations.append(
                ConstraintViolation(
                    "high_risk_count_mismatch",
                    "topology",
                    "high-risk side-area count does not match the profile",
                    (("expected", expected), ("actual", high_risk_count)),
                )
            )
    return tuple(violations)


def _primary_role(
    archetype: Archetype,
    *,
    index: int,
    count: int,
    ai_settlement_indices: frozenset[int],
) -> tuple[ZoneRole, PlacementKind | None]:
    if index == 0:
        return ZoneRole.START, PlacementKind.PLAYER_START
    if index == count - 1:
        required = (
            PlacementKind.AI_SETTLEMENT
            if archetype is Archetype.CONQUEST
            else PlacementKind.OBJECTIVE
        )
        return ZoneRole.VICTORY, required
    if index in ai_settlement_indices:
        return ZoneRole.SETTLEMENT, PlacementKind.AI_SETTLEMENT
    if archetype in (Archetype.EXPLORATION, Archetype.OBJECTIVE_CHAIN):
        if archetype is Archetype.OBJECTIVE_CHAIN or index % 2 == 0:
            return ZoneRole.OBJECTIVE, PlacementKind.OBJECTIVE
    return ZoneRole.TRANSIT, PlacementKind.ENCOUNTER


def _ai_settlement_indices(
    archetype: Archetype, count: int, ai_count: int
) -> frozenset[int]:
    # Conquest reserves the victory zone for one AI. Other archetypes still
    # require every configured AI to own a real settlement/spawn.
    interior_count = ai_count - 1 if archetype is Archetype.CONQUEST else ai_count
    if interior_count <= 0:
        return frozenset()
    available = list(range(1, count - 1))
    picked: set[int] = set()
    for ordinal in range(1, interior_count + 1):
        target = round(ordinal * (count - 1) / (interior_count + 1))
        candidate = min(available, key=lambda value: (abs(value - target), value))
        picked.add(candidate)
        available.remove(candidate)
    return frozenset(picked)


def _risk_tier(depth: int, primary_count: int) -> int:
    if depth <= 0:
        return 0
    return min(3, 1 + (depth * 3 // max(1, primary_count)))
