"""Occupancy-lane crossover helpers: ignore overlap, persist identity, hold vanished limbs."""
from __future__ import annotations

import unittest

import numpy as np

from occupancy_lane import (
    occupancy_lane_maps,
    persist_blob_bone,
    sprite_visible_unique,
    vanished_unique_bones,
)


class OccupancyLaneMapTests(unittest.TestCase):
    def test_two_strong_bones_are_ambiguous_one_winner_is_unique(self) -> None:
        arm = np.zeros((4, 4), dtype=np.float64)
        torso = np.zeros((4, 4), dtype=np.float64)
        arm[1, 1] = 10.0
        torso[1, 1] = 8.0
        arm[1, 2] = 10.0
        torso[2, 2] = 10.0
        maps = occupancy_lane_maps(
            {"arm": arm, "torso": torso},
            min_weight=1.0,
            ambiguous_ratio=0.4,
        )
        self.assertTrue(bool(maps.ambiguous[1, 1]))
        self.assertFalse(bool(maps.ambiguous[1, 2]))
        self.assertTrue(bool(maps.unique["arm"][1, 2]))
        self.assertTrue(bool(maps.unique["torso"][2, 2]))
        self.assertFalse(bool(maps.unique["arm"][1, 1]))

    def test_rejects_empty_maps_and_bad_ratio(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            occupancy_lane_maps({}, min_weight=1.0, ambiguous_ratio=0.4)
        with self.assertRaisesRegex(ValueError, "ambiguous_ratio"):
            occupancy_lane_maps(
                {"arm": np.ones((2, 2))},
                min_weight=1.0,
                ambiguous_ratio=0.0,
            )


class PersistBlobBoneTests(unittest.TestCase):
    def test_merged_blob_keeps_the_deeper_bone(self) -> None:
        arm = np.zeros((6, 6), dtype=bool)
        torso = np.zeros((6, 6), dtype=bool)
        arm[1:3, 1:3] = True
        torso[1:3, 3:5] = True
        blob = np.zeros((6, 6), dtype=bool)
        blob[1:3, 1:5] = True
        depths = {"arm": 4, "torso": 1}
        name = persist_blob_bone(
            blob,
            {"arm": arm, "torso": torso},
            node_depth=depths.__getitem__,
            min_overlap=4,
        )
        self.assertEqual(name, "arm")

    def test_single_overlap_keeps_that_bone(self) -> None:
        arm = np.zeros((4, 4), dtype=bool)
        arm[0:2, 0:2] = True
        blob = arm.copy()
        name = persist_blob_bone(
            blob,
            {"arm": arm, "torso": np.zeros((4, 4), dtype=bool)},
            node_depth=lambda _name: 3,
            min_overlap=2,
        )
        self.assertEqual(name, "arm")

    def test_no_overlap_returns_none_for_influence_fallback(self) -> None:
        blob = np.zeros((4, 4), dtype=bool)
        blob[3, 3] = True
        unique = {"arm": np.zeros((4, 4), dtype=bool)}
        unique["arm"][0, 0] = True
        self.assertIsNone(
            persist_blob_bone(
                blob,
                unique,
                node_depth=lambda _name: 3,
                min_overlap=1,
            )
        )


class VanishHoldTests(unittest.TestCase):
    def test_collapsed_unique_region_is_held(self) -> None:
        previous = {"hand": np.zeros((8, 8), dtype=bool), "spine": np.zeros((8, 8), dtype=bool)}
        previous["hand"][1:4, 1:4] = True
        previous["spine"][4:7, 4:7] = True
        current = {"hand": np.zeros((8, 8), dtype=bool), "spine": previous["spine"].copy()}
        held = vanished_unique_bones(
            previous,
            current,
            min_area=4,
            vanish_frac=0.25,
            min_bone_depth=3,
            node_depth=lambda name: 4 if name == "hand" else 1,
        )
        self.assertEqual(held, ("hand",))

    def test_moved_unique_region_is_not_held(self) -> None:
        previous = {"hand": np.zeros((8, 8), dtype=bool)}
        previous["hand"][1:4, 1:4] = True
        current = {"hand": np.zeros((8, 8), dtype=bool)}
        current["hand"][5:8, 5:8] = True
        held = vanished_unique_bones(
            previous,
            current,
            min_area=4,
            vanish_frac=0.25,
            min_bone_depth=3,
            node_depth=lambda _name: 4,
        )
        self.assertEqual(held, ())

    def test_sprite_delta_exclude_skips_hold(self) -> None:
        previous = {"hand": np.ones((4, 4), dtype=bool)}
        current = {"hand": np.zeros((4, 4), dtype=bool)}
        held = vanished_unique_bones(
            previous,
            current,
            min_area=4,
            vanish_frac=0.25,
            min_bone_depth=3,
            node_depth=lambda _name: 4,
            exclude=("hand",),
        )
        self.assertEqual(held, ())

    def test_sprite_visible_unique_drops_clear_pixels(self) -> None:
        unique = {"hand": np.ones((2, 2), dtype=bool)}
        sprite = np.zeros((2, 2), dtype=bool)
        sprite[0, 0] = True
        visible = sprite_visible_unique(unique, sprite)
        self.assertTrue(bool(visible["hand"][0, 0]))
        self.assertFalse(bool(visible["hand"][1, 1]))


if __name__ == "__main__":
    unittest.main()
