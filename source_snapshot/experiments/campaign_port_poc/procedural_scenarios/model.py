"""Immutable semantic IR for deterministic procedural scenarios.

This layer deliberately stops before Olden container encoding.  Native emitters
consume :class:`GeneratedScenarioIR` and remain responsible for translating the
semantic objects into the parallel arrays and typed property rows used by a
specific donor map version.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from .events import MechanicalEventSpec
    from .profile import ScenarioProfileV1


GENERATED_SCENARIO_IR_SCHEMA = "homm3.procedural_scenario_ir.v1"
GENERATOR_VERSION = "1.0.0"


class Archetype(str, Enum):
    EXPLORATION = "exploration"
    CONQUEST = "conquest"
    OBJECTIVE_CHAIN = "objective_chain"


class Difficulty(str, Enum):
    EASY = "easy"
    NORMAL = "normal"
    HARD = "hard"
    EXPERT = "expert"


class ZoneRole(str, Enum):
    START = "start"
    TRANSIT = "transit"
    OBJECTIVE = "objective"
    SETTLEMENT = "settlement"
    HIGH_RISK = "high_risk"
    VICTORY = "victory"


class PlacementKind(str, Enum):
    PLAYER_START = "player_start"
    AI_SETTLEMENT = "ai_settlement"
    NEUTRAL_CITY = "neutral_city"
    OBJECTIVE = "objective"
    ENCOUNTER = "encounter"
    REWARD = "reward"
    INTERACTABLE = "interactable"
    QUEST_GIVER = "quest_giver"
    SCENERY = "scenery"


@dataclass(frozen=True, order=True)
class Point:
    x: int
    y: int

    def node(self, width: int) -> int:
        return self.y * width + self.x

    def manhattan(self, other: "Point") -> int:
        return abs(self.x - other.x) + abs(self.y - other.y)

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y}


@dataclass(frozen=True)
class ConstraintViolation:
    code: str
    stage: str
    message: str
    context: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "stage": self.stage,
            "message": self.message,
            "context": {key: value for key, value in self.context},
        }


class GenerationFailure(RuntimeError):
    """Fail-closed generation error with machine-readable violations."""

    def __init__(
        self,
        stage: str,
        violations: Iterable[ConstraintViolation],
        *,
        seed: int | None = None,
    ) -> None:
        self.stage = stage
        self.violations = tuple(violations)
        self.seed = seed
        if not self.violations:
            raise ValueError("GenerationFailure requires at least one violation")
        summary = "; ".join(f"{item.code}: {item.message}" for item in self.violations)
        super().__init__(f"generation failed during {stage}: {summary}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "seed": self.seed,
            "violations": [item.to_dict() for item in self.violations],
        }


@dataclass(frozen=True)
class ZoneSpec:
    zone_id: str
    role: ZoneRole
    depth: int
    risk_tier: int
    required_placement: PlacementKind | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "zoneId": self.zone_id,
            "role": self.role.value,
            "depth": self.depth,
            "riskTier": self.risk_tier,
            "requiredPlacement": (
                None if self.required_placement is None else self.required_placement.value
            ),
        }


@dataclass(frozen=True)
class ProgressionEdge:
    edge_id: str
    source_zone_id: str
    target_zone_id: str
    required: bool
    guard_tier: int

    def endpoints(self) -> frozenset[str]:
        return frozenset((self.source_zone_id, self.target_zone_id))

    def to_dict(self) -> dict[str, Any]:
        return {
            "edgeId": self.edge_id,
            "sourceZoneId": self.source_zone_id,
            "targetZoneId": self.target_zone_id,
            "required": self.required,
            "guardTier": self.guard_tier,
        }


@dataclass(frozen=True)
class ProgressionGraph:
    archetype: Archetype
    zones: tuple[ZoneSpec, ...]
    edges: tuple[ProgressionEdge, ...]
    start_zone_id: str
    victory_zone_id: str
    primary_path: tuple[str, ...]

    def zone(self, zone_id: str) -> ZoneSpec:
        for zone in self.zones:
            if zone.zone_id == zone_id:
                return zone
        raise KeyError(zone_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "archetype": self.archetype.value,
            "startZoneId": self.start_zone_id,
            "victoryZoneId": self.victory_zone_id,
            "primaryPath": list(self.primary_path),
            "zones": [zone.to_dict() for zone in self.zones],
            "edges": [edge.to_dict() for edge in self.edges],
        }


@dataclass(frozen=True)
class ZonePlacement:
    zone_id: str
    center: Point
    radius: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "zoneId": self.zone_id,
            "center": self.center.to_dict(),
            "radius": self.radius,
        }


@dataclass(frozen=True)
class Route:
    edge_id: str
    cells: tuple[Point, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "edgeId": self.edge_id,
            "cells": [cell.to_dict() for cell in self.cells],
        }


@dataclass(frozen=True)
class DecisionAnchor:
    anchor_id: str
    edge_id: str
    point: Point
    distance_from_previous: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchorId": self.anchor_id,
            "edgeId": self.edge_id,
            "point": self.point.to_dict(),
            "distanceFromPrevious": self.distance_from_previous,
        }


@dataclass(frozen=True)
class SpatialLayout:
    width: int
    height: int
    zones: tuple[ZonePlacement, ...]
    routes: tuple[Route, ...]
    decision_anchors: tuple[DecisionAnchor, ...]

    def zone(self, zone_id: str) -> ZonePlacement:
        for zone in self.zones:
            if zone.zone_id == zone_id:
                return zone
        raise KeyError(zone_id)

    @property
    def route_cells(self) -> frozenset[Point]:
        return frozenset(cell for route in self.routes for cell in route.cells)

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "zones": [zone.to_dict() for zone in self.zones],
            "routes": [route.to_dict() for route in self.routes],
            "decisionAnchors": [anchor.to_dict() for anchor in self.decision_anchors],
        }


@dataclass(frozen=True)
class TerrainGrid:
    width: int
    height: int
    tiles_map: tuple[int, ...]
    water_map: tuple[int, ...]
    roads_map: tuple[int, ...]
    levels_map: tuple[int, ...]
    climbs_map: tuple[int, ...]
    custom_areas_painting: tuple[int, ...]
    biome_map: tuple[str, ...]
    blocked: tuple[bool, ...]

    def __post_init__(self) -> None:
        expected = self.width * self.height
        arrays = (
            self.tiles_map,
            self.water_map,
            self.roads_map,
            self.levels_map,
            self.climbs_map,
            self.custom_areas_painting,
            self.biome_map,
            self.blocked,
        )
        if any(len(values) != expected for values in arrays):
            raise ValueError(f"terrain arrays must all contain {expected} entries")

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "tilesMap": list(self.tiles_map),
            "waterMap": list(self.water_map),
            "roadsMap": list(self.roads_map),
            "levelsMap": list(self.levels_map),
            "climbsMap": list(self.climbs_map),
            "customAreasPainting": list(self.custom_areas_painting),
            "biomeMap": list(self.biome_map),
            "blocked": list(self.blocked),
        }


@dataclass(frozen=True)
class Footprint:
    width: int
    height: int
    occupied: tuple[Point, ...]
    interaction: tuple[Point, ...]

    def translated_occupied(self, origin: Point) -> tuple[Point, ...]:
        return tuple(Point(origin.x + point.x, origin.y + point.y) for point in self.occupied)

    def translated_interaction(self, origin: Point) -> tuple[Point, ...]:
        return tuple(
            Point(origin.x + point.x, origin.y + point.y) for point in self.interaction
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "occupied": [point.to_dict() for point in self.occupied],
            "interaction": [point.to_dict() for point in self.interaction],
        }


@dataclass(frozen=True)
class Placement:
    placement_id: str
    kind: PlacementKind
    content_sid: str
    origin: Point
    node: int
    zone_id: str
    footprint: Footprint
    interactive: bool
    risk_tier: int
    metadata: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "placementId": self.placement_id,
            "kind": self.kind.value,
            "contentSid": self.content_sid,
            "origin": self.origin.to_dict(),
            "node": self.node,
            "zoneId": self.zone_id,
            "footprint": self.footprint.to_dict(),
            "interactive": self.interactive,
            "riskTier": self.risk_tier,
            "metadata": {key: value for key, value in self.metadata},
        }


@dataclass(frozen=True)
class ScenarioMetrics:
    zone_count: int
    route_cell_count: int
    gameplay_placement_count: int
    scenery_placement_count: int
    gameplay_density_per_100_tiles: float
    scenery_density_per_100_tiles: float
    decision_spacing_min: int
    decision_spacing_max: int
    decision_spacing_mean: float
    high_risk_zone_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "zoneCount": self.zone_count,
            "routeCellCount": self.route_cell_count,
            "gameplayPlacementCount": self.gameplay_placement_count,
            "sceneryPlacementCount": self.scenery_placement_count,
            "gameplayDensityPer100Tiles": self.gameplay_density_per_100_tiles,
            "sceneryDensityPer100Tiles": self.scenery_density_per_100_tiles,
            "decisionSpacingMin": self.decision_spacing_min,
            "decisionSpacingMax": self.decision_spacing_max,
            "decisionSpacingMean": self.decision_spacing_mean,
            "highRiskZoneCount": self.high_risk_zone_count,
        }


@dataclass(frozen=True)
class GenerationProvenance:
    generator_version: str
    profile_hash: str
    catalog_hash: str
    donor_hash: str
    source_hashes: tuple[tuple[str, str], ...]
    stage_seeds: tuple[tuple[str, int], ...]
    mechanical_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "generatorVersion": self.generator_version,
            "profileHash": self.profile_hash,
            "catalogHash": self.catalog_hash,
            "donorHash": self.donor_hash,
            "sourceHashes": {key: value for key, value in self.source_hashes},
            "stageSeeds": {key: value for key, value in self.stage_seeds},
            "mechanicalHash": self.mechanical_hash,
        }


@dataclass(frozen=True)
class GeneratedScenarioIR:
    scenario_id: str
    map_sid: str
    seed: int
    profile: "ScenarioProfileV1"
    topology: ProgressionGraph
    layout: SpatialLayout
    terrain: TerrainGrid
    placements: tuple[Placement, ...]
    events: tuple["MechanicalEventSpec", ...]
    metrics: ScenarioMetrics
    provenance: GenerationProvenance
    schema: str = GENERATED_SCENARIO_IR_SCHEMA
    seer_script_triggers: tuple[dict[str, Any], ...] = ()
    seer_script_subquests: tuple[dict[str, Any], ...] = ()
    seer_dialog_plans: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "scenarioId": self.scenario_id,
            "mapSid": self.map_sid,
            "seed": self.seed,
            "profile": self.profile.to_dict(),
            "topology": self.topology.to_dict(),
            "layout": self.layout.to_dict(),
            "terrain": self.terrain.to_dict(),
            "placements": [placement.to_dict() for placement in self.placements],
            "events": [_to_dict(event) for event in self.events],
            "seerScriptTriggers": list(self.seer_script_triggers),
            "seerScriptSubQuests": list(self.seer_script_subquests),
            "seerDialogPlans": list(self.seer_dialog_plans),
            "metrics": self.metrics.to_dict(),
            "provenance": self.provenance.to_dict(),
        }

    @property
    def mechanical_fingerprint(self) -> str:
        return sha256_json(self.to_dict())


def _to_dict(value: Any) -> Any:
    method = getattr(value, "to_dict", None)
    if callable(method):
        return method()
    raise TypeError(f"{type(value).__name__} does not expose to_dict()")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
