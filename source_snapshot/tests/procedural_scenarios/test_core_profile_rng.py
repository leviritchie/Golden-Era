from __future__ import annotations

import unittest

from procedural_scenarios.model import Archetype
from procedural_scenarios.profile import (
    ProfileError,
    ScenarioProfileV1,
    TerrainSettings,
)
from procedural_scenarios.rng import StageRngFactory


class ProfileAndRngTests(unittest.TestCase):
    def test_profile_defaults_and_supported_sizes(self) -> None:
        profile = ScenarioProfileV1(seed=7).normalized()
        self.assertEqual(64, profile.map_size)
        self.assertEqual("homm3_castle", profile.player_faction)
        self.assertEqual(("city-spawner", "random-squad"), profile.content_allowlist)
        for size in (32, 48, 64):
            self.assertEqual(size, ScenarioProfileV1(seed=7, map_size=size).normalized().map_size)
        with self.assertRaises(ProfileError):
            ScenarioProfileV1(seed=7, map_size=40).normalized()

    def test_profile_round_trip_is_canonical(self) -> None:
        profile = ScenarioProfileV1(
            seed=17,
            archetype=Archetype.OBJECTIVE_CHAIN,
            map_size=48,
            biomes=("Dirt", "Grass"),
            content_allowlist=("random-squad", "random-squad"),
        ).normalized()
        restored = ScenarioProfileV1.from_dict(profile.to_dict())
        self.assertEqual(profile, restored)
        self.assertEqual(profile.fingerprint, restored.fingerprint)
        self.assertEqual(("dirt", "grass"), restored.biomes)

    def test_unproven_water_fails_closed(self) -> None:
        with self.assertRaisesRegex(ProfileError, "water traversal is not proven"):
            ScenarioProfileV1(
                seed=1,
                terrain=TerrainSettings(water_enabled=True, water_fraction=0.1),
            ).normalized()

    def test_scenario_id_prefix_stays_in_procedural_namespace(self) -> None:
        with self.assertRaisesRegex(ProfileError, "reserved 'proc' namespace"):
            ScenarioProfileV1(seed=1, scenario_id_prefix="legacy").normalized()
        normalized = ScenarioProfileV1(seed=1, scenario_id_prefix="proc_custom").normalized()
        self.assertEqual("proc_custom", normalized.scenario_id_prefix)

    def test_stage_streams_are_isolated(self) -> None:
        args = dict(
            generator_version="1.0.0",
            profile_hash="1" * 64,
            donor_hash="2" * 64,
            catalog_hash="3" * 64,
        )
        first = StageRngFactory(91, **args)
        topology_before = [first.stream("topology").next_u64() for _ in range(4)]
        first.stream("new-placement-pass").next_u64()
        topology_after = [first.stream("topology").next_u64() for _ in range(4)]
        second = StageRngFactory(91, **args)
        expected = [second.stream("topology").next_u64() for _ in range(4)]
        self.assertEqual(expected, topology_before)
        self.assertEqual(expected, topology_after)
        self.assertNotEqual(first.seed_for("topology"), first.seed_for("terrain"))


if __name__ == "__main__":
    unittest.main()
