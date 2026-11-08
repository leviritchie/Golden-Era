"""Mixed-influence edge strain: LBS blend stretch vs bind rest length."""
from __future__ import annotations

import unittest

import numpy as np

from gpu_depth_silhouette_solver import DepthSilhouetteConfig
from gpu_mesh_strain import (
    mixed_influence_edge_mask,
    regional_winner_index,
    rest_edge_lengths,
    strain_error_from_excess,
    strain_error_from_positions,
    strain_excess_from_lengths,
    unique_triangle_edges,
)


class UniqueEdgeTests(unittest.TestCase):
    def test_triangle_has_three_undirected_edges(self) -> None:
        edges = unique_triangle_edges(np.array([[0, 1, 2], [0, 2, 1]], dtype=np.int64))
        self.assertEqual(len(edges), 3)
        self.assertTrue(np.all(edges[:, 0] < edges[:, 1]))


class MixedInfluenceTests(unittest.TestCase):
    def test_same_exclusive_bone_is_rigid_different_bones_are_mixed(self) -> None:
        joints = np.array([[0, 1], [0, 1], [1, 0]], dtype=np.int64)
        weights = np.array([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]], dtype=np.float64)
        edges = np.array([[0, 1], [1, 2]], dtype=np.int64)
        mixed = mixed_influence_edge_mask(
            edges,
            joints=joints,
            weights=weights,
            exclusive_weight=0.99,
        )
        self.assertFalse(bool(mixed[0]))
        self.assertTrue(bool(mixed[1]))


class StrainErrorTests(unittest.TestCase):
    def test_doubled_blend_edge_is_caught_rigid_edge_is_not(self) -> None:
        bind = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=np.float64)
        edges = np.array([[0, 1], [1, 2]], dtype=np.int64)
        rest = rest_edge_lengths(bind, edges)
        posed = bind.copy()
        posed[2, 0] = 3.0
        excess = strain_excess_from_lengths(
            np.linalg.norm(posed[edges[:, 0]] - posed[edges[:, 1]], axis=1),
            rest,
            tolerance=0.08,
        )
        self.assertAlmostEqual(float(excess[0]), 0.0, places=6)
        self.assertGreater(float(excess[1]), 0.8)
        error = strain_error_from_excess(excess)
        self.assertGreater(error, 0.5)

    def test_batch_identity_has_zero_strain(self) -> None:
        bind = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64)
        edges = unique_triangle_edges(np.array([[0, 1, 2]], dtype=np.int64))
        rest = rest_edge_lengths(bind, edges)
        errors = strain_error_from_positions(
            bind[None, ...],
            edges,
            rest,
            tolerance=0.08,
        )
        self.assertEqual(len(errors), 1)
        self.assertAlmostEqual(float(errors[0]), 0.0, places=6)

    def test_config_requires_positive_weight_when_enabled(self) -> None:
        DepthSilhouetteConfig().validate()
        self.assertTrue(bool(DepthSilhouetteConfig().strain_enabled))
        self.assertAlmostEqual(float(DepthSilhouetteConfig().strain_weight), 0.80)
        self.assertAlmostEqual(float(DepthSilhouetteConfig().strain_tolerance), 0.08)
        DepthSilhouetteConfig(strain_enabled=False, strain_weight=0.0).validate()
        with self.assertRaisesRegex(ValueError, "strain_weight must be positive"):
            DepthSilhouetteConfig(strain_enabled=True, strain_weight=0.0).validate()
        with self.assertRaisesRegex(ValueError, "strain_weight must be 0"):
            DepthSilhouetteConfig(strain_enabled=False, strain_weight=0.80).validate()


class RegionalWinnerTests(unittest.TestCase):
    def test_better_iou_with_extra_stretch_stays_identity(self) -> None:
        winner = regional_winner_index(
            (0.40, 0.70),
            (0.02, 0.20),
            strain_slack=0.04,
        )
        self.assertEqual(winner, 0)

    def test_better_iou_within_strain_slack_is_kept(self) -> None:
        winner = regional_winner_index(
            (0.40, 0.55),
            (0.02, 0.05),
            strain_slack=0.04,
        )
        self.assertEqual(winner, 1)

    def test_without_strain_gate_higher_iou_wins(self) -> None:
        winner = regional_winner_index(
            (0.40, 0.70),
            None,
            strain_slack=0.04,
        )
        self.assertEqual(winner, 1)

    def test_equal_iou_keeps_identity(self) -> None:
        winner = regional_winner_index(
            (0.50, 0.50),
            (0.01, 0.01),
            strain_slack=0.04,
        )
        self.assertEqual(winner, 0)


if __name__ == "__main__":
    unittest.main()
