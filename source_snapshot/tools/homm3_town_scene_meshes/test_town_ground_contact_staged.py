"""Unit test: town_full3d_ground_contact measures the vertices as the staged float32 bins hold them (staged_world), so
a low point on a ground triangle's edge gets the same verdict in memory (the recipe's float64 Stage) as from the files
(Cove zs_v1 2026-10-02: Mesh_Near_pebbles piece 36, anchored at -0.24 m in memory, read 1.03 m from the bins)."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import town_full3d_ground_contact as GC  # noqa: E402


class StagedVerdict(unittest.TestCase):
    def test_float64_inside_float32_outside_same_verdict(self):
        sc = type("Sc", (), {"cpos": np.zeros(3), "scale": 1.0, "C": np.eye(3)})()
        # a ledge triangle at y 0 over x+z <= 1, a lower sheet at y -1 under everything (the pebble's step lip)
        P = np.array([[0, 0, 0], [1, 0, 0], [0, 0, 1], [-5, -1, -5], [5, -1, -5], [-5, -1, 5], [5, -1, 5]], float)
        F = np.array([[0, 1, 2], [3, 4, 5], [4, 6, 5]])
        g = GC.Ground(GC.staged_world(sc, P), F, "cpu")
        v64 = np.array([[0.7063608022679042, 0.1, 0.2936391984976192]])   # x+z-1 = +7.7e-10 (in the edge tolerance)
        raw = g.gap(sc.cpos + (v64 / sc.scale) @ sc.C.T)                 # float64: on the ledge
        mem = g.gap(GC.staged_world(sc, v64))
        staged = g.gap(GC.staged_world(sc, v64.astype(np.float32)))     # read back from a float32 bin
        self.assertAlmostEqual(float(raw[0]), 0.1, places=6)             # the case is real: float64 alone disagrees
        self.assertEqual(float(mem[0]), float(staged[0]))
        self.assertAlmostEqual(float(staged[0]), 1.1, places=6)


if __name__ == "__main__":
    unittest.main()
