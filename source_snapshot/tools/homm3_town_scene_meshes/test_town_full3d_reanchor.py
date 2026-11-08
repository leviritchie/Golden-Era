"""Unit tests: town_full3d_recipe.support_drops_under (the evidence reanchor_after_repair names when a repair round took
an anchored piece's ground; finish lane 2026-10-02, Stronghold zs_v2 Mesh_Houses piece 20)."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import town_full3d_recipe as R  # noqa: E402


class _GS:
    """The two members support_drops_under reads: stage.bins[bin]["v"] and _low()."""

    def __init__(self, low):
        self.stage = type("St", (), {"bins": [{"v": np.zeros((4, 3))}]})()
        self._low_pts = np.asarray(low, np.float64)

    def _low(self, v, idx, s):
        return self._low_pts


def _drop(face, tri, rnd=1, name="Mesh_Back_Terrain"):
    return {"round": rnd, "bin": name, "face": face, "tri": np.asarray(tri, np.float64).tolist()}


class SupportDropsUnder(unittest.TestCase):
    def setUp(self):
        self.rec = {"bin": 0, "idx": np.arange(4)}
        # piece low points around x 1, z 1, at height -1 (world Y up; the footprint test is on x / z)
        self.gs = _GS([[1.0, -1.0, 1.0], [1.2, -1.0, 1.1]])

    def test_face_under_a_low_point_is_named(self):
        under = _drop(7, [[0, -0.8, 0], [3, -0.8, 0], [0, -0.8, 3]])
        aside = _drop(8, [[10, -0.8, 10], [12, -0.8, 10], [10, -0.8, 12]])
        got = R.support_drops_under(self.gs, self.rec, [under, aside])
        self.assertEqual([(g["bin"], g["face"], g["round"]) for g in got], [("Mesh_Back_Terrain", 7, 1)])
        self.assertAlmostEqual(got[0]["heightM"], -0.8, places=6)

    def test_height_does_not_matter_only_the_footprint(self):
        # a face far above or below the base is still under it horizontally (the gate's own lookup is vertical)
        hi = _drop(3, [[0, 5.0, 0], [3, 5.0, 0], [0, 5.0, 3]])
        self.assertEqual(len(R.support_drops_under(self.gs, self.rec, [hi])), 1)

    def test_degenerate_face_is_skipped_and_cap_holds(self):
        flat = _drop(1, [[0, 0, 0], [1, 0, 0], [2, 0, 0]])       # zero horizontal area
        many = [_drop(i, [[0, -1, 0], [3, -1, 0], [0, -1, 3]]) for i in range(30)]
        self.assertEqual(R.support_drops_under(self.gs, self.rec, [flat]), [])
        self.assertEqual(len(R.support_drops_under(self.gs, self.rec, many, cap=20)), 20)

    def test_cycle_caps_are_bounded(self):
        self.assertEqual(R.REANCHOR_CYCLES, 3)
        self.assertGreaterEqual(R.PRUNE_CYCLES, 1)


if __name__ == "__main__":
    unittest.main()
