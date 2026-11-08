"""absolute_floor_probe: the floor is the world's y = 0, not Idle key 0; owners name the sinking bones; report only."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import absolute_floor_probe as AFP  # noqa: E402


class AbsoluteFloorProbeTest(unittest.TestCase):
    def test_clip_floor_is_absolute_fraction_of_height(self):
        # a clip whose lowest key sits 0.2 below y = 0 on a 2.0-tall unit reports -0.1, at that key
        self.assertEqual(AFP.clip_floor([0.05, -0.2, 0.0], 2.0), {"minAbs": -0.1, "worstKey": 1})
        # a sunk reference is not zeroed: every key below the floor stays negative
        self.assertLess(AFP.clip_floor([-0.17, -0.18], 1.65)["minAbs"], 0)

    def test_owners_count_each_vertex_once_by_its_heaviest_joint(self):
        J = np.array([[0, 1], [1, 2], [2, 0], [1, 0]])
        W = np.array([[0.9, 0.1], [0.2, 0.8], [0.6, 0.4], [0.7, 0.3]])
        names = ["Hips", "QTail_01", "LeftFoot"]
        mask = np.array([True, True, True, False])
        self.assertEqual(AFP.dominant_owners(J, W, names, mask), {"Hips": 1, "LeftFoot": 2})
        self.assertEqual(AFP.dominant_owners(J, W, names, np.zeros(4, bool)), {})

    def test_resolve_unit_and_path(self):
        unit, glb = AFP.resolve("h3_green_dragon")
        self.assertEqual(unit, "h3_green_dragon")
        self.assertTrue(str(glb).replace("\\", "/").endswith("h3_green_dragon/h3_green_dragon_def_retarget.glb"))
        self.assertEqual(AFP.resolve("F:/x/h3_gold_dragon_idle_retimed.glb")[0], "h3_gold_dragon")

    def test_missing_glb_is_the_only_failure(self):
        self.assertEqual(AFP.main(["Z:/no/such_unit_def_retarget.glb"]), 1)


if __name__ == "__main__":
    unittest.main()
