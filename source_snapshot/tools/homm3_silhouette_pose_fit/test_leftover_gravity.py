"""Leftover gravity: hard unique-region assignment, not torso-winning soft 1/r^2."""
from __future__ import annotations

import unittest

import numpy as np

from gpu_depth_silhouette_solver import DepthSilhouetteConfig
from leftover_gravity import (
    bone_distance_map,
    extra_predicted_mask,
    leftover_gravity_pull,
    leftover_mask,
    pick_next_gravity_bone,
    unique_median_depths,
)


def _reports(
    leftover: np.ndarray,
    unique: dict[str, np.ndarray],
    joints: dict[str, tuple[float, float]],
    *,
    remaining: tuple[str, ...] = ("arm", "torso"),
    previous: dict[str, np.ndarray] | None = None,
    extra: np.ndarray | None = None,
    extra_weight: float = 0.0,
    max_assign_px: float = 24.0,
    sigma_px: float = 8.0,
    depth: np.ndarray | None = None,
    unique_median_depth: dict[str, float] | None = None,
    depth_gate: float = 0.0,
    depths: dict[str, int] | None = None,
) -> dict[str, dict[str, float]]:
    shape = leftover.shape
    distance = {
        name: bone_distance_map(unique[name], joints[name], shape=shape) for name in remaining
    }
    return leftover_gravity_pull(
        leftover,
        remaining=remaining,
        unique_distance=distance,
        unique_masks=unique,
        previous_unique=previous,
        node_depth=(depths or {"arm": 4, "torso": 1}).__getitem__,
        extra=extra,
        extra_weight=extra_weight,
        max_assign_px=max_assign_px,
        sigma_px=sigma_px,
        depth=depth,
        unique_median_depth=unique_median_depth or {},
        depth_gate=depth_gate,
    )


class LeftoverMaskTests(unittest.TestCase):
    def test_ignore_pixels_are_not_attractors(self) -> None:
        target = np.zeros((3, 3), dtype=np.float32)
        predicted = np.zeros((3, 3), dtype=np.float32)
        ignore = np.zeros((3, 3), dtype=np.float32)
        target[1, 1] = 1.0
        target[1, 2] = 1.0
        ignore[1, 1] = 1.0
        leftover = leftover_mask(target, predicted, ignore, predicted_threshold=0.5)
        self.assertFalse(bool(leftover[1, 1]))
        self.assertTrue(bool(leftover[1, 2]))
        predicted[1, 2] = 1.0
        predicted[0, 0] = 1.0
        extra = extra_predicted_mask(target, predicted, ignore, predicted_threshold=0.5)
        self.assertFalse(bool(extra[1, 1]))
        self.assertFalse(bool(extra[1, 2]))
        self.assertTrue(bool(extra[0, 0]))


class AssignmentTests(unittest.TestCase):
    def test_leftover_next_to_arm_unique_picks_arm_not_torso(self) -> None:
        unique = {
            "arm": np.zeros((8, 8), dtype=bool),
            "torso": np.zeros((8, 8), dtype=bool),
        }
        unique["arm"][1, 6] = True
        unique["torso"][4, 1] = True
        leftover = np.zeros((8, 8), dtype=bool)
        leftover[1, 5] = True
        leftover[1, 7] = True
        leftover[4, 0] = True
        joints = {"arm": (6.0, 1.0), "torso": (1.0, 4.0)}
        reports = _reports(leftover, unique, joints)
        self.assertEqual(int(reports["arm"]["assigned"]), 2)
        self.assertEqual(int(reports["torso"]["assigned"]), 1)
        picked = pick_next_gravity_bone(
            reports,
            ("arm", "torso"),
            fallback=("torso", "arm"),
            min_pull=1.0,
        )
        self.assertEqual(picked, "arm")

    def test_previous_unique_keeps_distal_identity_over_nearer_torso(self) -> None:
        unique = {
            "arm": np.zeros((8, 8), dtype=bool),
            "torso": np.zeros((8, 8), dtype=bool),
        }
        unique["torso"][4, 4] = True
        leftover = np.zeros((8, 8), dtype=bool)
        leftover[2, 2] = True
        previous = {
            "arm": np.zeros((8, 8), dtype=bool),
            "torso": np.zeros((8, 8), dtype=bool),
        }
        previous["arm"][2, 2] = True
        previous["torso"][2, 2] = True
        joints = {"arm": (0.0, 0.0), "torso": (4.0, 4.0)}
        reports = _reports(
            leftover,
            unique,
            joints,
            previous=previous,
            max_assign_px=3.0,
        )
        self.assertEqual(int(reports["arm"]["assigned"]), 1)
        self.assertEqual(int(reports["torso"]["assigned"]), 0)

    def test_far_leftover_stays_unassigned(self) -> None:
        unique = {
            "arm": np.zeros((8, 8), dtype=bool),
            "torso": np.zeros((8, 8), dtype=bool),
        }
        unique["torso"][0, 0] = True
        leftover = np.zeros((8, 8), dtype=bool)
        leftover[7, 7] = True
        joints = {"arm": (0.0, 0.0), "torso": (0.0, 0.0)}
        reports = _reports(leftover, unique, joints, max_assign_px=3.0)
        self.assertEqual(int(reports["arm"]["assigned"]), 0)
        self.assertEqual(int(reports["torso"]["assigned"]), 0)

    def test_depth_gate_blocks_far_surface_from_near_unique(self) -> None:
        unique = {
            "arm": np.zeros((8, 8), dtype=bool),
            "torso": np.zeros((8, 8), dtype=bool),
        }
        unique["arm"][1, 1] = True
        leftover = np.zeros((8, 8), dtype=bool)
        leftover[1, 2] = True
        depth = np.zeros((8, 8), dtype=np.float64)
        depth[1, 1] = 0.2
        depth[1, 2] = 0.9
        sprite = np.zeros((8, 8), dtype=bool)
        sprite[1, 1] = True
        medians = unique_median_depths(unique, depth, sprite)
        joints = {"arm": (1.0, 1.0), "torso": (7.0, 7.0)}
        reports = _reports(
            leftover,
            unique,
            joints,
            remaining=("arm",),
            depth=depth,
            unique_median_depth=medians,
            depth_gate=0.2,
        )
        self.assertEqual(int(reports["arm"]["assigned"]), 0)

    def test_extra_unique_coverage_adds_pull(self) -> None:
        unique = {
            "arm": np.zeros((4, 4), dtype=bool),
            "torso": np.zeros((4, 4), dtype=bool),
        }
        unique["arm"][0, 0] = True
        leftover = np.zeros((4, 4), dtype=bool)
        extra = np.zeros((4, 4), dtype=bool)
        extra[0, 0] = True
        joints = {"arm": (0.0, 0.0), "torso": (3.0, 3.0)}
        reports = _reports(
            leftover,
            unique,
            joints,
            extra=extra,
            extra_weight=0.25,
        )
        self.assertGreater(float(reports["arm"]["pull"]), 0.0)
        self.assertEqual(float(reports["torso"]["pull"]), 0.0)

    def test_held_previous_unique_does_not_feed_the_torso(self) -> None:
        unique = {
            "arm": np.zeros((8, 8), dtype=bool),
            "torso": np.zeros((8, 8), dtype=bool),
        }
        unique["torso"][3, 3] = True
        leftover = np.zeros((8, 8), dtype=bool)
        leftover[3, 4] = True
        blocked = {"arm": np.zeros((8, 8), dtype=bool)}
        blocked["arm"][3, 4] = True
        joints = {"arm": (0.0, 0.0), "torso": (3.0, 3.0)}
        reports = leftover_gravity_pull(
            leftover,
            remaining=("torso",),
            unique_distance={
                "torso": bone_distance_map(unique["torso"], joints["torso"], shape=leftover.shape)
            },
            unique_masks={"torso": unique["torso"]},
            previous_unique=None,
            node_depth={"torso": 1}.__getitem__,
            extra=None,
            extra_weight=0.0,
            max_assign_px=24.0,
            sigma_px=8.0,
            depth=None,
            unique_median_depth={},
            depth_gate=0.0,
            blocked_unique=blocked,
        )
        self.assertEqual(int(reports["torso"]["assigned"]), 0)


class PickNextTests(unittest.TestCase):
    def test_empty_pull_uses_fallback_order(self) -> None:
        reports = {
            "torso": {"pull": 0.0, "assigned": 0.0, "extra": 0.0},
            "arm": {"pull": 0.0, "assigned": 0.0, "extra": 0.0},
        }
        picked = pick_next_gravity_bone(
            reports,
            ("arm", "torso"),
            fallback=("torso", "arm"),
            min_pull=1.0,
        )
        self.assertEqual(picked, "torso")


class ConfigTests(unittest.TestCase):
    def test_leftover_gravity_mode_validates_and_rejects_branch(self) -> None:
        DepthSilhouetteConfig(bone_order_mode="leftover_gravity").validate()
        with self.assertRaisesRegex(ValueError, "leftover_gravity requires multi_bone_mode='single'"):
            DepthSilhouetteConfig(
                bone_order_mode="leftover_gravity",
                multi_bone_mode="branch",
            ).validate()
        with self.assertRaisesRegex(ValueError, "leftover_gravity_max_assign_px"):
            DepthSilhouetteConfig(
                bone_order_mode="leftover_gravity",
                leftover_gravity_max_assign_px=0.0,
            ).validate()


if __name__ == "__main__":
    unittest.main()
