"""Sprite-occupancy preemptive seed: signed image-plane swing, not leftover pose."""
from __future__ import annotations

import unittest

import numpy as np

from gpu_depth_silhouette_solver import DepthSilhouetteConfig
from ik_silhouette_miss_keypoints import SilhouetteMissPair
from sprite_delta_init import (
    clipped_axis_targets,
    screen_plane_signed_deg,
    sprite_delta_moves_from_pairs,
    sprite_occupancy_delta,
)


class SpriteOccupancyDeltaTests(unittest.TestCase):
    def test_appeared_and_disappeared_are_unique_pixels(self) -> None:
        previous = np.zeros((8, 8), dtype=np.float32)
        current = np.zeros((8, 8), dtype=np.float32)
        previous[2:5, 1:4] = 1.0
        current[2:5, 4:7] = 1.0
        disappeared, appeared = sprite_occupancy_delta(previous, current)
        self.assertEqual(int(disappeared.sum()), 9)
        self.assertEqual(int(appeared.sum()), 9)
        self.assertFalse(bool((disappeared & appeared).any()))

    def test_identical_frames_have_empty_delta(self) -> None:
        mask = np.ones((4, 4), dtype=np.float32)
        disappeared, appeared = sprite_occupancy_delta(mask, mask)
        self.assertFalse(bool(disappeared.any()))
        self.assertFalse(bool(appeared.any()))


class ScreenPlaneSwingTests(unittest.TestCase):
    def test_up_to_right_is_ninety_degrees_in_png_y_down(self) -> None:
        angle = screen_plane_signed_deg((50.0, 50.0), (50.0, 20.0), (80.0, 50.0), min_radius_px=4.0)
        self.assertAlmostEqual(angle, 90.0, places=5)

    def test_rejects_pivot_on_the_tip(self) -> None:
        with self.assertRaisesRegex(ValueError, "too close to the joint pivot"):
            screen_plane_signed_deg((10.0, 10.0), (10.0, 10.0), (40.0, 10.0), min_radius_px=4.0)


class SpriteDeltaMoveTests(unittest.TestCase):
    def test_attributes_one_bone_and_skips_tiny_swings(self) -> None:
        pair = SilhouetteMissPair(
            excess_tip=(50.0, 20.0),
            target_tip=(80.0, 50.0),
            predicted_depth=0.4,
            target_depth=0.4,
            excess_area=40,
            missing_area=42,
            excess_label_id=1,
            missing_label_id=1,
            tip_distance_sq=1800.0,
        )
        tiny = SilhouetteMissPair(
            excess_tip=(20.0, 20.0),
            target_tip=(21.0, 20.0),
            predicted_depth=0.4,
            target_depth=0.4,
            excess_area=12,
            missing_area=12,
            excess_label_id=2,
            missing_label_id=2,
            tip_distance_sq=1.0,
        )
        moves = sprite_delta_moves_from_pairs(
            (pair, tiny),
            joint_xy={"hand": (50.0, 50.0), "foot": (20.0, 20.0)},
            bone_name_for_pair=lambda item: "hand" if item.excess_label_id == 1 else "foot",
            min_radius_px=4.0,
            min_angle_deg=8.0,
        )
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0].bone_name, "hand")
        self.assertAlmostEqual(moves[0].angle_deg, 90.0, places=5)

    def test_unattributed_and_empty_joints_stay_unmoved(self) -> None:
        pair = SilhouetteMissPair(
            excess_tip=(50.0, 20.0),
            target_tip=(80.0, 50.0),
            predicted_depth=0.4,
            target_depth=0.4,
            excess_area=40,
            missing_area=42,
            excess_label_id=1,
            missing_label_id=1,
            tip_distance_sq=1800.0,
        )
        empty = sprite_delta_moves_from_pairs(
            (pair,),
            joint_xy={},
            bone_name_for_pair=lambda _item: None,
            min_radius_px=4.0,
            min_angle_deg=8.0,
        )
        self.assertEqual(empty, ())

    def test_plus_and_minus_axis_targets_are_clipped(self) -> None:
        targets = clipped_axis_targets({"x": 140.0, "y": 0.0}, 30.0, joint_limit_deg=150.0)
        self.assertIn(("x", 150.0), targets)
        self.assertIn(("x", 110.0), targets)
        self.assertIn(("y", 30.0), targets)
        self.assertIn(("y", -30.0), targets)


class SpriteDeltaConfigTests(unittest.TestCase):
    def test_enabled_requires_previous_frame_seed(self) -> None:
        DepthSilhouetteConfig().validate()
        self.assertTrue(bool(DepthSilhouetteConfig().sprite_delta_init_enabled))
        self.assertTrue(bool(DepthSilhouetteConfig().occupancy_ignore_ambiguous))
        self.assertTrue(bool(DepthSilhouetteConfig().blob_identity_persist))
        self.assertTrue(bool(DepthSilhouetteConfig().unique_vanish_hold))
        DepthSilhouetteConfig(occupancy_ignore_ambiguous=False, unique_vanish_hold=False).validate()
        with self.assertRaisesRegex(ValueError, "occupancy_ambiguous_ratio"):
            DepthSilhouetteConfig(occupancy_ambiguous_ratio=0.0).validate()
        DepthSilhouetteConfig(sprite_delta_init_enabled=False).validate()
        with self.assertRaisesRegex(ValueError, "seed_previous_frame"):
            DepthSilhouetteConfig(
                sprite_delta_init_enabled=True,
                seed_previous_frame=False,
            ).validate()
        with self.assertRaisesRegex(ValueError, "sprite_delta_init_min_angle_deg"):
            DepthSilhouetteConfig(sprite_delta_init_min_angle_deg=0.0).validate()


if __name__ == "__main__":
    unittest.main()
