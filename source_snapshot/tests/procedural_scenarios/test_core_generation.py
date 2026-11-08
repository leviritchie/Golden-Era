from __future__ import annotations

import unittest

from procedural_scenarios.catalog import (
    CatalogEntry,
    ContentCatalogSnapshot,
    ContentKind,
)
from procedural_scenarios.events import (
    CounterTrigger,
    VictoryAction,
    compile_mechanical_events,
)
from procedural_scenarios.generator import generate_scenario
from procedural_scenarios.placement import _placement_decision_anchor_ids
from procedural_scenarios.validator import validate_generated_ir
from procedural_scenarios.model import (
    Archetype,
    Footprint,
    GenerationFailure,
    PlacementKind,
    Point,
)
from procedural_scenarios.native_catalog import (
    NativeContentList,
    NativeContentPool,
    NativeEncounterBuilding,
    NativeEncounterPickup,
    NativeEncounterTemplate,
    NativeGeneratorSnapshot,
    NativePoolGroup,
    WeightedContentRef,
)
from procedural_scenarios.profile import (
    DensitySettings,
    EconomySettings,
    ScenarioProfileV1,
    TopologySettings,
)


EMPTY = Footprint(1, 1, (), ())
ONE = Footprint(1, 1, (Point(0, 0),), ())
INTERACTIVE = Footprint(
    3,
    3,
    (Point(0, 0),),
    (
        Point(-1, -1),
        Point(0, -1),
        Point(1, -1),
        Point(-1, 0),
        Point(1, 0),
        Point(-1, 1),
        Point(0, 1),
        Point(1, 1),
    ),
)
CITY = Footprint(
    3,
    3,
    (
        Point(-1, -1),
        Point(0, -1),
        Point(1, -1),
        Point(-1, 0),
        Point(0, 0),
        Point(1, 0),
        Point(-1, 1),
        Point(1, 1),
    ),
    (Point(0, 1),),
)


def _entry(
    sid: str,
    kind: ContentKind,
    footprint: Footprint = EMPTY,
    *,
    native_id: int | str | None = None,
    biomes: tuple[str, ...] = (),
    metadata: tuple[tuple[str, object], ...] = (),
) -> CatalogEntry:
    return CatalogEntry(
        sid=sid,
        kind=kind,
        source="test",
        source_member=f"test/{kind.value}/{sid}",
        content_hash=(sid.encode("utf-8").hex() + "0" * 64)[:64],
        footprint=footprint,
        biomes=biomes,
        native_id=sid if native_id is None else native_id,
        metadata=metadata,
    )


def _catalog() -> ContentCatalogSnapshot:
    entries = [
        _entry("homm3_castle", ContentKind.FACTION),
        _entry("homm3_inferno", ContentKind.FACTION),
        _entry(
            "castle_hero",
            ContentKind.HERO,
            metadata=(("factionSid", "homm3_castle"),),
        ),
        _entry(
            "inferno_hero",
            ContentKind.HERO,
            metadata=(("factionSid", "homm3_inferno"),),
        ),
        _entry(
            "inferno_unit",
            ContentKind.UNIT,
            metadata=(
                ("factionSid", "homm3_inferno"),
                ("squadValue", 200.0),
                ("tier", 2),
            ),
        ),
        _entry(
            "neutral_unit",
            ContentKind.UNIT,
            metadata=(
                ("factionSid", "neutral"),
                ("squadValue", 150.0),
                ("tier", 2),
            ),
        ),
        _entry("grass", ContentKind.TERRAIN, native_id=1, biomes=("grass",)),
        _entry("dirt", ContentKind.TERRAIN, native_id=7, biomes=("dirt",)),
        _entry("city-spawner", ContentKind.SETTLEMENT, CITY),
        _entry("random-squad", ContentKind.ENCOUNTER, INTERACTIVE),
        _entry("objective_marker", ContentKind.OBJECTIVE),
        _entry("resource_gold", ContentKind.REWARD, INTERACTIVE),
        _entry("mine_gold", ContentKind.INTERACTABLE, INTERACTIVE),
        _entry("tree", ContentKind.SCENERY, ONE),
    ]
    native = NativeGeneratorSnapshot(
        content_lists=(
            NativeContentList(
                "rewards",
                (WeightedContentRef("resource_gold", 10),),
                "lists.json",
                "1" * 64,
            ),
            NativeContentList(
                "interactables",
                (WeightedContentRef("mine_gold", 10),),
                "lists.json",
                "2" * 64,
            ),
        ),
        content_pools=(
            NativeContentPool(
                "content_pool_default_resources",
                (NativePoolGroup(5, ("rewards",), ()),),
                (),
                "pools.json",
                "3" * 64,
            ),
            NativeContentPool(
                "content_pool_default_unguarded",
                (NativePoolGroup(5, ("interactables",), ()),),
                (),
                "pools.json",
                "4" * 64,
            ),
        ),
        encounter_templates=(
            NativeEncounterTemplate(
                "guarded_3x3",
                3,
                3,
                0,
                True,
                1,
                1,
                "encounter.json",
                "5" * 64,
                relative_frequency=1.0,
                road_target_type=1,
                road_target=Point(1, 1),
                guards=(Point(1, 1),),
                buildings=(
                    NativeEncounterBuilding(1, 1, 2, Point(2, 1)),
                ),
                pickups=(
                    NativeEncounterPickup(Point(1, 2), False, False),
                ),
                entrances=(Point(1, -1),),
                tile_contents=(1, 2, 0, 0, 4, 3, 0, 5, 0),
            ),
        ),
    )
    return ContentCatalogSnapshot.from_entries(
        entries,
        core_hash="6" * 64,
        source_hashes=(("core", "6" * 64),),
        allowlist=("city-spawner", "random-squad"),
        native_generator=native,
    )


class GenerationTests(unittest.TestCase):
    def test_all_archetypes_generate_explicit_single_victory(self) -> None:
        catalog = _catalog()
        for archetype in Archetype:
            with self.subTest(archetype=archetype.value):
                result = generate_scenario(
                    ScenarioProfileV1(
                        seed=31,
                        map_size=32,
                        archetype=archetype,
                        density=DensitySettings(scenery_per_100_tiles=0.0),
                    ),
                    catalog,
                    donor_hash="a" * 64,
                )
                victories = [
                    action
                    for event in result.events
                    for action in event.actions
                    if isinstance(action, VictoryAction)
                ]
                self.assertEqual(1, len(victories))
                counters = {
                    action.counter_sid
                    for event in result.events
                    for action in event.actions
                    if hasattr(action, "counter_sid")
                }
                compile_mechanical_events(
                    result.events, declared_counter_sids=tuple(counters)
                )
                self.assertTrue(
                    any(
                        placement.kind is PlacementKind.PLAYER_START
                        and dict(placement.metadata)["heroSid"] == "castle_hero"
                        for placement in result.placements
                    )
                )
                anchor_points = {
                    anchor.anchor_id: anchor.point
                    for anchor in result.layout.decision_anchors
                }
                populated_anchor_ids = set()
                anchor_placements = 0
                for placement in result.placements:
                    metadata = dict(placement.metadata)
                    anchor_ids = metadata.get("decisionAnchorIds")
                    if anchor_ids is None:
                        single_anchor_id = metadata.get("decisionAnchorId")
                        anchor_ids = () if single_anchor_id is None else (single_anchor_id,)
                    if anchor_ids:
                        anchor_placements += 1
                        interactions = placement.footprint.translated_interaction(
                            placement.origin
                        ) or (placement.origin,)
                        for anchor_id in anchor_ids:
                            populated_anchor_ids.add(anchor_id)
                            self.assertIn(anchor_points[anchor_id], interactions)
                self.assertEqual(set(anchor_points), populated_anchor_ids)
                self.assertEqual(
                    len({anchor.point for anchor in result.layout.decision_anchors}),
                    anchor_placements,
                )
                self.assertTrue(
                    all(
                        result.terrain.roads_map[
                            point.node(result.terrain.width)
                        ]
                        == 1
                        for point in result.layout.route_cells
                    )
                )
                if archetype is Archetype.OBJECTIVE_CHAIN:
                    objective_events = tuple(
                        event
                        for event in result.events
                        if "_objective_event_" in event.event_id
                    )
                    self.assertGreaterEqual(len(objective_events), 2)
                    for index, event in enumerate(objective_events[1:], start=1):
                        counters = tuple(
                            trigger
                            for trigger in event.triggers
                            if isinstance(trigger, CounterTrigger)
                        )
                        self.assertEqual(1, len(counters))
                        self.assertEqual(
                            f"proc_objective_{index - 1:02d}",
                            counters[0].counter_sid,
                        )

    def test_route_orientation_preserves_dense_side_edge_anchors(self) -> None:
        profile = ScenarioProfileV1(
            seed=9065,
            map_size=64,
            archetype=Archetype.CONQUEST,
            biomes=("grass", "dirt"),
            density=DensitySettings(scenery_per_100_tiles=0.0),
            topology=TopologySettings(neutral_city_count=0),
        )
        result = generate_scenario(
            profile,
            _catalog(),
            donor_hash="a" * 64,
        )
        validate_generated_ir(result).raise_for_errors()
        self.assertEqual(6, result.metrics.decision_spacing_min)
        self.assertLessEqual(result.metrics.decision_spacing_max, 10)
        # Overlapping corridors may co-locate anchors onto one interaction
        # cell; one placement then owns every shared anchor id.
        populated = {
            anchor_id
            for placement in result.placements
            for anchor_id in _placement_decision_anchor_ids(placement)
        }
        self.assertEqual(
            {anchor.anchor_id for anchor in result.layout.decision_anchors},
            populated,
        )
    def test_encounters_instantiate_native_template_and_exact_squad(self) -> None:
        catalog = _catalog()
        result = generate_scenario(
            ScenarioProfileV1(
                seed=31,
                map_size=32,
                density=DensitySettings(scenery_per_100_tiles=0.0),
            ),
            catalog,
            donor_hash="d" * 64,
        )
        encounters = tuple(
            placement
            for placement in result.placements
            if placement.kind is PlacementKind.ENCOUNTER
        )
        self.assertTrue(encounters)
        for placement in encounters:
            metadata = dict(placement.metadata)
            self.assertEqual("exact", metadata["squadMode"])
            self.assertIn("exactSquad", metadata)
            self.assertNotIn("requestedValue", metadata)
            self.assertNotIn("randomSquad", metadata)
            exact_squad = metadata["exactSquad"]
            self.assertEqual(f"{placement.placement_id}_squad", exact_squad["sid"])
            self.assertEqual("inferno_unit", exact_squad["unitProps"][0]["sid"])
            instance = metadata["encounterTemplateInstance"]
            template = instance["template"]
            self.assertEqual([1, 2, 0, 0, 4, 3, 0, 5, 0], template["tileContents"])
            self.assertEqual(template["width"], placement.footprint.width)
            self.assertEqual(template["height"], placement.footprint.height)
            self.assertIn(Point(0, 0), placement.footprint.occupied)
            self.assertIn(Point(1, 0), placement.footprint.occupied)
            self.assertEqual(placement.placement_id, instance["guards"][0]["entitySid"])
            for index, child in enumerate(instance["buildings"]):
                self.assertEqual(
                    f"{placement.placement_id}_building_{index:02d}",
                    child["entitySid"],
                )
                catalog.require_sid(
                    child["contentSid"], kinds=(ContentKind.INTERACTABLE,)
                )
            for index, child in enumerate(instance["pickups"]):
                self.assertEqual(
                    f"{placement.placement_id}_pickup_{index:02d}",
                    child["entitySid"],
                )
                catalog.require_sid(child["contentSid"], kinds=(ContentKind.REWARD,))

    def test_mechanics_are_byte_stable_for_same_inputs(self) -> None:
        catalog = _catalog()
        profile = ScenarioProfileV1(
            seed=991,
            map_size=48,
            density=DensitySettings(scenery_per_100_tiles=0.0),
        )
        first = generate_scenario(profile, catalog, donor_hash="b" * 64)
        second = generate_scenario(profile, catalog, donor_hash="b" * 64)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.mechanical_fingerprint, second.mechanical_fingerprint)

    def test_different_seeds_change_topology_or_layout(self) -> None:
        catalog = _catalog()
        fingerprints = set()
        for seed in range(5):
            result = generate_scenario(
                ScenarioProfileV1(
                    seed=seed,
                    map_size=32,
                    density=DensitySettings(scenery_per_100_tiles=0.0),
                ),
                catalog,
                donor_hash="c" * 64,
            )
            fingerprints.add(
                (
                    tuple(
                        (edge.source_zone_id, edge.target_zone_id)
                        for edge in result.topology.edges
                    ),
                    tuple(
                        (zone.center.x, zone.center.y) for zone in result.layout.zones
                    ),
                )
            )
            self.assertGreaterEqual(result.metrics.decision_spacing_min, 6)
            self.assertLessEqual(result.metrics.decision_spacing_max, 10)
        self.assertGreater(len(fingerprints), 1)


    def test_exact_decision_spacing_endpoints_are_supported(self) -> None:
        catalog = _catalog()
        for spacing in (6, 10):
            for seed in range(5):
                with self.subTest(spacing=spacing, seed=seed):
                    result = generate_scenario(
                        ScenarioProfileV1(
                            seed=seed,
                            map_size=32,
                            density=DensitySettings(
                                decision_spacing_min=spacing,
                                decision_spacing_max=spacing,
                                scenery_per_100_tiles=0.0,
                            ),
                        ),
                        catalog,
                        donor_hash="f" * 64,
                    )
    def test_zero_starting_resources_emit_no_empty_turn_event(self) -> None:
        result = generate_scenario(
            ScenarioProfileV1(
                seed=45,
                map_size=32,
                economy=EconomySettings(
                    starting_gold=0,
                    starting_wood=0,
                    starting_ore=0,
                ),
                density=DensitySettings(scenery_per_100_tiles=0.0),
            ),
            _catalog(),
            donor_hash="0" * 64,
        )
        self.assertFalse(
            any(event.event_id.endswith("_starting_resources") for event in result.events)
        )
    def test_zero_ai_uses_native_neutral_encounters(self) -> None:
        result = generate_scenario(
            ScenarioProfileV1(
                seed=44,
                map_size=32,
                ai_count=0,
                ai_factions=(),
                density=DensitySettings(scenery_per_100_tiles=0.0),
            ),
            _catalog(),
            donor_hash="e" * 64,
        )
        encounters = tuple(
            placement
            for placement in result.placements
            if placement.kind is PlacementKind.ENCOUNTER
        )
        self.assertTrue(encounters)
        self.assertTrue(
            all(dict(placement.metadata)["factionSid"] == "neutral" for placement in encounters)
        )

if __name__ == "__main__":
    unittest.main()
