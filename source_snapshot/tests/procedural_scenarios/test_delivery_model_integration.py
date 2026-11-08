from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from experiments.campaign_port_poc.procedural_scenarios.emitter import (
    NativeMapContainer,
    emit_scenario,
    parse_container_bytes,
)
from experiments.campaign_port_poc.procedural_scenarios.events import (
    CounterAction,
    CounterTrigger,
    MechanicalEventSpec,
    ObjectiveProgressAction,
    VictoryAction,
    VisitTrigger,
)
from experiments.campaign_port_poc.procedural_scenarios.model import (
    Archetype,
    Footprint,
    GeneratedScenarioIR,
    GenerationProvenance,
    Placement,
    PlacementKind,
    Point,
    ProgressionEdge,
    ProgressionGraph,
    ScenarioMetrics,
    SpatialLayout,
    TerrainGrid,
    ZonePlacement,
    ZoneRole,
    ZoneSpec,
)
from experiments.campaign_port_poc.procedural_scenarios.profile import (
    ScenarioProfileV1,
)


def _donor() -> NativeMapContainer:
    return NativeMapContainer(
        "1.0",
        b"\0\0",
        (
            {"startSettings": {"DefeatAllEnemiesEnabled": False}},
            {"cliffRandomSeed": 1, "generatorChecksum": "", "settings": {}},
            {},
            {},
        ),
    )


def _typed_scenario() -> GeneratedScenarioIR:
    size = 32
    start = ZoneSpec(
        "start",
        ZoneRole.START,
        depth=0,
        risk_tier=0,
        required_placement=PlacementKind.PLAYER_START,
    )
    victory = ZoneSpec(
        "victory",
        ZoneRole.VICTORY,
        depth=1,
        risk_tier=2,
        required_placement=PlacementKind.OBJECTIVE,
    )
    graph = ProgressionGraph(
        archetype=Archetype.OBJECTIVE_CHAIN,
        zones=(start, victory),
        edges=(ProgressionEdge("edge_0", "start", "victory", True, 1),),
        start_zone_id="start",
        victory_zone_id="victory",
        primary_path=("start", "victory"),
    )
    layout = SpatialLayout(
        width=size,
        height=size,
        zones=(
            ZonePlacement("start", Point(4, 4), 3),
            ZonePlacement("victory", Point(27, 27), 3),
        ),
        routes=(),
        decision_anchors=(),
    )
    zeroes = (0,) * (size * size)
    terrain = TerrainGrid(
        width=size,
        height=size,
        tiles_map=(1,) * (size * size),
        water_map=zeroes,
        roads_map=zeroes,
        levels_map=zeroes,
        climbs_map=zeroes,
        custom_areas_painting=zeroes,
        biome_map=("grass",) * (size * size),
        blocked=(False,) * (size * size),
    )
    footprint = Footprint(
        width=1,
        height=1,
        occupied=(Point(0, 0),),
        interaction=(Point(0, 0),),
    )
    placements = (
        Placement(
            "proc_start",
            PlacementKind.PLAYER_START,
            "city-spawner",
            Point(4, 4),
            Point(4, 4).node(size),
            "start",
            footprint,
            True,
            0,
            (("owner", 1), ("factionSid", "homm3_castle")),
        ),
        Placement(
            "proc_objective",
            PlacementKind.OBJECTIVE,
            "fx_quest_mark_gold_01",
            Point(27, 27),
            Point(27, 27).node(size),
            "victory",
            footprint,
            True,
            2,
            (),
        ),
    )
    events = (
        MechanicalEventSpec(
            "proc_objective_progress",
            triggers=(VisitTrigger("proc_objective"),),
            actions=(
                CounterAction("proc_objective_counter", 1),
                ObjectiveProgressAction("proc_objective_00"),
            ),
            title="Primary Objective",
            objective_label="Secure the objective",
        ),
        MechanicalEventSpec(
            "proc_victory",
            triggers=(CounterTrigger("proc_objective_counter", 1),),
            actions=(VictoryAction("proc_victory"),),
            title="Victory",
        ),
    )
    profile = ScenarioProfileV1(
        seed=7,
        archetype=Archetype.OBJECTIVE_CHAIN,
        map_size=size,
    ).normalized()
    metrics = ScenarioMetrics(
        zone_count=2,
        route_cell_count=2,
        gameplay_placement_count=2,
        scenery_placement_count=0,
        gameplay_density_per_100_tiles=0.2,
        scenery_density_per_100_tiles=0.0,
        decision_spacing_min=8,
        decision_spacing_max=8,
        decision_spacing_mean=8.0,
        high_risk_zone_count=0,
    )
    provenance = GenerationProvenance(
        generator_version="test",
        profile_hash="a" * 64,
        catalog_hash="b" * 64,
        donor_hash="c" * 64,
        source_hashes=(("core", "d" * 64),),
        stage_seeds=(("test", 1),),
        mechanical_hash="e" * 64,
    )
    return GeneratedScenarioIR(
        scenario_id="typed",
        map_sid="proc_typed_scenario",
        seed=7,
        profile=profile,
        topology=graph,
        layout=layout,
        terrain=terrain,
        placements=placements,
        events=events,
        metrics=metrics,
        provenance=provenance,
    )


class DeliveryModelIntegrationTests(unittest.TestCase):
    def test_typed_ir_compiles_counters_and_objective_subquests(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = emit_scenario(
                _typed_scenario(),
                Path(raw),
                donor_container=_donor(),
            )
            container = parse_container_bytes(result.map_path.read_bytes())
            script = container.chunks[3]
            self.assertEqual(
                [row["sid"] for row in script["counters"]],
                ["proc_objective_counter"],
            )
            subquests = script["quests"][0]["subQuests"]
            self.assertIn("proc_objective_00", {row["sid"] for row in subquests})
            victory_actions = [
                action
                for subquest in subquests
                for trigger in subquest["triggers"]
                for action in trigger["actions"]
                if action.get("a") == "GameVictory"
            ]
            self.assertEqual(len(victory_actions), 1)


if __name__ == "__main__":
    unittest.main()
