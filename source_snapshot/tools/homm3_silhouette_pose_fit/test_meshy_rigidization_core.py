from __future__ import annotations

import unittest

from meshy_rigidization_core import (
    RigidizationConfig,
    armature_signature_diffs,
    armature_signatures_match,
    classify_component,
    component_stats,
    connected_components,
    with_mesh_fraction,
)


class RigidizationCoreTests(unittest.TestCase):
    def test_same_owner_regions_are_topology_connected_and_mixed_edges_are_not_merged(self):
        labels = ["hand", "hand", "hand", "forearm", "hand"]
        top = [1.0, 0.95, 0.9, 0.9, 0.4]
        edges = [(0, 1), (1, 2), (2, 3), (1, 4)]
        regions = connected_components(
            len(labels),
            edges,
            labels=labels,
            seed_top_weights=top,
            min_seed_top_weight=0.55,
        )
        self.assertEqual(regions, [[0, 1, 2], [3]])


    def test_decisive_existing_owner_is_frozen(self):
        weights = [
            {"hand": 1.0},
            {"hand": 0.96, "forearm": 0.04},
            {"hand": 0.92, "forearm": 0.08},
            {"hand": 1.0},
        ]
        positions = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)]
        stats = component_stats(0, [0, 1, 2, 3], weights, positions)
        decision = classify_component(
            with_mesh_fraction(stats, 10),
            RigidizationConfig(min_part_vertices=1, max_part_fraction=1.0),
        )
        self.assertEqual(decision.classification, "freeze_rigid_candidate")
        self.assertEqual(decision.owner_bone, "hand")


    def test_mixed_region_is_preserved_instead_of_silently_rigidized(self):
        weights = [
            {"spine": 0.55, "shoulder": 0.45},
            {"spine": 0.52, "shoulder": 0.48},
            {"spine": 0.50, "shoulder": 0.50},
            {"spine": 0.54, "shoulder": 0.46},
        ]
        positions = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)]
        stats = component_stats(0, [0, 1, 2, 3], weights, positions)
        decision = classify_component(
            with_mesh_fraction(stats, 10),
            RigidizationConfig(min_part_vertices=1, max_part_fraction=1.0),
        )
        self.assertIn(decision.classification, {"preserve_flexible", "ambiguous_rigid_candidate"})
        self.assertIn(decision.owner_bone, {None, "spine"})


    def test_large_body_region_is_not_frozen_even_when_single_owned(self):
        weights = [{"spine": 1.0}] * 10
        positions = [(float(i), 0, 0) for i in range(10)]
        stats = component_stats(0, list(range(10)), weights, positions)
        decision = classify_component(
            with_mesh_fraction(stats, 10),
            RigidizationConfig(min_part_vertices=1),
        )
        self.assertEqual(decision.classification, "preserve_large_region")


    def test_config_rejects_unknown_fields(self):
        with self.assertRaisesRegex(ValueError, "unknown"):
            RigidizationConfig.from_mapping({"not_a_real_setting": True})


    def test_armature_signatures_match_by_name_not_order(self):
        expected = [
            {"name": "root", "parent": None, "head": [0.0, 0.0, 0.0], "tail": [0.0, 1.0, 0.0]},
            {"name": "child", "parent": "root", "head": [0.0, 1.0, 0.0], "tail": [0.0, 2.0, 0.0]},
        ]
        reordered = [expected[1], expected[0]]
        self.assertTrue(armature_signatures_match(expected, reordered))
        self.assertEqual(armature_signature_diffs(expected, reordered), [])


    def test_armature_signature_rejects_rest_or_hierarchy_changes(self):
        expected = [
            {"name": "Bone_000", "parent": None, "head": [0.0, 0.0, 0.0], "tail": [0.0, 1.0, 0.0]},
            {"name": "Bone_001", "parent": "Bone_000", "head": [0.0, 1.0, 0.0], "tail": [0.02, 1.05, 0.84]},
        ]
        tail_drift = [
            expected[0],
            {**expected[1], "tail": [-0.01, 1.09, 0.84]},
        ]
        diffs = armature_signature_diffs(expected, tail_drift)
        self.assertTrue(any("Bone_001 tail" in item for item in diffs))
        self.assertFalse(armature_signatures_match(expected, tail_drift))
        parent_change = [
            expected[0],
            {**expected[1], "parent": None},
        ]
        self.assertTrue(any("parent" in item for item in armature_signature_diffs(expected, parent_change)))


if __name__ == "__main__":
    unittest.main()
