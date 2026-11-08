"""prop_floor_glb tilts a prop out of the floor within its lean plane, lift only, and refuses a vertical prop.

    python -m unittest tools/homm3_def_retarget_delivery/test_prop_floor_glb.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prop_floor_glb as PF  # noqa: E402
from stride_match_glb import write_channels  # noqa: E402
from test_ground_check import fixture  # noqa: E402


def cane(tip_local):
    """One vertex rigid on node 2 (the fixture's 'Head', at world height 1 + the Hips' key)."""
    return {"B": np.array([[[*tip_local, 1.0]]]), "J": np.array([[2]]), "W": np.ones((1, 1))}


class PropFloor(unittest.TestCase):
    def test_tip_below_the_floor_is_tilted_onto_it_and_nothing_else_moves(self):
        g = fixture(head_heights=(1.0, 1.0))
        body = cane((0.3, -1.1, 0.0))            # world height -0.1 at t=0 and 1, 0.0 at t=0.5 (Hips +0.1)
        mask = np.ones(1, bool)
        times, _, rots, tilts, depth = PF.plan_clip(g, body, "Unit_Move", 2, 0.0, mask)
        self.assertTrue(tilts[0] > 0 and tilts[-1] > 0)
        self.assertAlmostEqual(tilts[0], tilts[-1])
        self.assertAlmostEqual(depth[0], -0.1, places=5)
        write_channels(g, g.anim("Unit_Move"), times, {(2, "rotation"): rots})
        _, _, _, tilts2, depth2 = PF.plan_clip(g, body, "Unit_Move", 2, 0.0, mask)
        self.assertGreaterEqual(depth2.min(), -1e-4)
        self.assertEqual(float(tilts2.max()), 0.0)
        # the tip keeps its lean direction (+x) and rises toward the joint's height
        self.assertGreater(depth2[0], depth[0])

    def test_a_prop_above_the_floor_is_left_alone(self):
        g = fixture(head_heights=(1.0, 1.0))
        _, _, _, tilts, _ = PF.plan_clip(g, cane((0.3, -0.5, 0.0)), "Unit_Move", 2, 0.0, np.ones(1, bool))
        self.assertEqual(float(tilts.max()), 0.0)

    def test_an_exactly_vertical_prop_has_no_lean_plane(self):
        g = fixture(head_heights=(1.0, 1.0))
        with self.assertRaises(SystemExit):
            PF.plan_clip(g, cane((0.0, -1.5, 0.0)), "Unit_Move", 2, 0.0, np.ones(1, bool))

    def test_a_prop_too_long_to_tilt_out_is_refused(self):
        g = fixture(head_heights=(1.0, 1.0))
        with self.assertRaises(SystemExit):
            PF.plan_clip(g, cane((0.01, -9.0, 0.0)), "Unit_Move", 2, 0.0, np.ones(1, bool))


    def test_a_constant_step_track_takes_a_varying_tilt_as_linear(self):
        class Stub:
            def __init__(self, out): self.out = out
            def read(self, _): return self.out
        held = np.array([[0.0, 0.0, 0.0, 1.0]] * 2)
        tilt = np.array([[0.0, 0.0, 0.0, 1.0], [0.0, 0.0, 0.1, 0.995], [0.0, 0.0, 0.0, 1.0]])
        self.assertEqual(PF.held_interpolation(Stub(held), {"output": 0, "interpolation": "STEP"}, tilt), "LINEAR")
        # a STEP track that already varies is the author's; a tilt that is constant changes nothing
        self.assertEqual(PF.held_interpolation(Stub(tilt), {"output": 0, "interpolation": "STEP"}, tilt), "STEP")
        self.assertEqual(PF.held_interpolation(Stub(held), {"output": 0, "interpolation": "STEP"}, held), "STEP")
        self.assertEqual(PF.held_interpolation(Stub(held), {"output": 0}, tilt), "LINEAR")


if __name__ == "__main__":
    unittest.main()
