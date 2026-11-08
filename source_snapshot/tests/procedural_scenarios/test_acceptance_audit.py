from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools import validate_procedural_scenario_contract as audit


class AcceptanceAuditTests(unittest.TestCase):
    def test_diversity_and_profile_extreme_contracts_are_explicit(self) -> None:
        self.assertEqual(
            audit.DIVERSITY_FINGERPRINTS,
            (
                "topology",
                "layout",
                "biome",
                "route",
                "encounter",
                "objective",
            ),
        )
        faction_sids = tuple(f"faction_{index}" for index in range(8))
        biome_sids = ("dirt", "grass", "snow")
        extreme_rows = audit._profile_extremes(
            audit._load_default_profile(),
            faction_sids=faction_sids,
            biome_sids=biome_sids,
        )
        self.assertEqual(
            tuple(name for name, _profile in extreme_rows),
            audit.PROFILE_EXTREME_NAMES,
        )
        extremes = dict(extreme_rows)
        for candidate in extremes.values():
            candidate.normalized()

        sparse = extremes["density_sparse_spacing_10"].density
        dense = extremes["density_dense_spacing_6"].density
        self.assertEqual((sparse.decision_spacing_min, sparse.decision_spacing_max), (10, 10))
        self.assertEqual((dense.decision_spacing_min, dense.decision_spacing_max), (6, 6))
        self.assertLessEqual(dense.optional_gameplay_per_zone, 5)

        no_ai = extremes["ai_none"]
        max_ai = extremes["ai_max_7"]
        self.assertEqual((no_ai.ai_count, no_ai.ai_factions), (0, ()))
        self.assertEqual(max_ai.ai_count, 7)
        self.assertEqual(max_ai.factions, faction_sids)
        self.assertEqual(max_ai.archetype, audit.Archetype.CONQUEST)

        no_loops = extremes["topology_no_loops_no_risk"].topology
        max_topology = extremes["topology_max_loops_and_risk"].topology
        self.assertFalse(no_loops.optional_loops_enabled)
        self.assertEqual(no_loops.high_risk_side_area_count, 0)
        self.assertTrue(max_topology.optional_loops_enabled)
        self.assertEqual(max_topology.high_risk_side_area_count, 5)
        self.assertEqual(max_topology.zone_count, 30)

        single_biome = extremes["biome_single_roads_off"]
        all_biomes = extremes["biome_all_surface"]
        self.assertEqual(single_biome.biomes, ("dirt",))
        self.assertFalse(single_biome.terrain.roads_enabled)
        self.assertEqual(all_biomes.biomes, biome_sids)

        minimum = extremes["economy_min_easy"]
        maximum = extremes["economy_high_expert"]
        self.assertEqual(minimum.difficulty, audit.Difficulty.EASY)
        self.assertEqual(minimum.economy.starting_gold, 0)
        self.assertEqual(minimum.economy.reward_multiplier, 0.1)
        self.assertEqual(maximum.difficulty, audit.Difficulty.EXPERT)
        self.assertEqual(maximum.economy.reward_multiplier, 10.0)

        events = extremes["events_minimal_objective_only"].event_policy
        self.assertFalse(events.turn_schedules_enabled)
        self.assertFalse(events.squad_defeat_events_enabled)
        self.assertFalse(events.capture_events_enabled)
        self.assertFalse(events.resource_rewards_enabled)
        self.assertTrue(events.visit_events_enabled)
        self.assertTrue(events.objective_progress_enabled)
    def test_representative_generation_uses_service_presentation_path(self) -> None:
        profile = audit._load_default_profile()
        expected = SimpleNamespace(
            presentation=SimpleNamespace(
                manifest_fragment={
                    "presentation": {"status": "textless", "dialogCount": 0}
                }
            )
        )
        core = Path("source-Core.zip")
        donor = Path("donor.map")
        bundle_root = Path("representative")
        with mock.patch.object(
            audit.scenario_service,
            "generate_bundle",
            return_value=expected,
        ) as generate:
            actual = audit._generate_representative(
                profile,
                core=core,
                donor=donor,
                bundle_root=bundle_root,
            )

        self.assertIs(actual, expected)
        generate.assert_called_once_with(
            profile,
            core_zip=core,
            donor_map=donor,
            output_root=bundle_root,
        )

    def test_stages_core_delta_before_map_load_preflight(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix=".tmp_procedural_acceptance_",
            dir=audit.REPO_ROOT,
        ) as raw:
            root = Path(raw)
            source_core = root / "source-Core.zip"
            with zipfile.ZipFile(source_core, "w") as archive:
                archive.writestr(
                    "DB/quickStart.json",
                    json.dumps({"scenarios": ["stock"]}),
                )
            bundle_root = root / "bundle"
            map_sid = "proc_acceptance_audit"
            maps_root = bundle_root / "maps"
            maps_root.mkdir(parents=True)
            candidate_map = maps_root / f"{map_sid}.map"
            candidate_map.write_bytes(b"map-payload")
            (bundle_root / "core_deltas.json").write_text(
                json.dumps(
                    {
                        "operations": [
                            {
                                "member": "DB/quickStart.json",
                                "operation": "append_unique",
                                "path": ["scenarios"],
                                "values": [map_sid],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            def preflight(core: Path, map_path: Path, sid: str) -> tuple[str, ...]:
                self.assertEqual(map_path, candidate_map)
                self.assertEqual(sid, map_sid)
                with zipfile.ZipFile(core) as archive:
                    quickstart = json.loads(archive.read("DB/quickStart.json"))
                self.assertEqual(quickstart["scenarios"], ["stock", map_sid])
                return ("effective_core_integrity", "map_object_sid_resolution")

            with mock.patch.object(audit, "run_preflight", side_effect=preflight) as run:
                result = audit._stage_effective_core_and_preflight(
                    source_core=source_core,
                    bundle_root=bundle_root,
                    map_sid=map_sid,
                    stage_root=root / "staged",
                    expected_core_hash=hashlib.sha256(
                        source_core.read_bytes()
                    ).hexdigest(),
                )

            run.assert_called_once()
            self.assertEqual(
                result["mergedCoreMembers"],
                ["DB/quickStart.json"],
            )
            self.assertEqual(
                result["preflightChecks"],
                ["effective_core_integrity", "map_object_sid_resolution"],
            )
            with zipfile.ZipFile(source_core) as archive:
                original = json.loads(archive.read("DB/quickStart.json"))
            self.assertEqual(original["scenarios"], ["stock"])
            with self.assertRaisesRegex(ValueError, "source Core changed"):
                audit._stage_effective_core_and_preflight(
                    source_core=source_core,
                    bundle_root=bundle_root,
                    map_sid=map_sid,
                    stage_root=root / "drifted",
                    expected_core_hash="0" * 64,
                )


if __name__ == "__main__":
    unittest.main()
