"""Unit tests: town_full3d_recipe.fill_ground_faces (backstop.groundFloor: the floor-fill faces the sky-side prune
keeps because they are ground for some certified pose; Inferno zs_v3 2026-10-02). cuda against the numpy reference
(bit-equal booleans), and the rule itself on a hand-built case. Needs CUDA for the parity case (no fallback)."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import town_full3d_recipe as R  # noqa: E402


class FillGroundFaces(unittest.TestCase):
    def test_rule(self):
        V = np.array([[0, 0, 399.0], [1, 0, 399.0], [0, 1, 399.0],          # face 0: a vertex within 400 of cam 0
                      [0, 0, 401.0], [1, 0, 401.0], [0, 1, 401.5]])          # face 1: every vertex past 400
        tris = np.array([[0, 1, 2], [3, 4, 5]])
        cams = np.array([[0, 0, 0.0], [0, 0, -10.0]])
        self.assertEqual(R.fill_ground_faces(V, tris, cams, 400.0, "cpu").tolist(), [True, False])
        # a closer camera makes face 1 ground too
        cams2 = np.r_[cams, [[0, 0, 5.0]]]
        self.assertEqual(R.fill_ground_faces(V, tris, cams2, 400.0, "cpu").tolist(), [True, True])

    def test_unknown_device_fails(self):
        with self.assertRaises(SystemExit):
            R.fill_ground_faces(np.zeros((3, 3)), np.array([[0, 1, 2]]), np.zeros((1, 3)), 1.0, "mps")

    def test_cuda_parity(self):
        import torch
        if not torch.cuda.is_available():
            self.fail("CUDA required for the parity case (GPU first, no fallback)")
        rng = np.random.default_rng(7)
        V = rng.uniform(-420, 420, (200_000, 3))
        tris = rng.integers(0, len(V), (300_000, 3))
        cams = rng.uniform(-20, 20, (160, 3))
        a = R.fill_ground_faces(V, tris, cams, 400.0, "cpu")
        b = R.fill_ground_faces(V, tris, cams, 400.0, "cuda")
        self.assertGreater(a.sum(), 0)
        self.assertLess(a.sum(), len(a))
        self.assertTrue(np.array_equal(a, b), f"{int((a != b).sum())} faces differ")


if __name__ == "__main__":
    unittest.main()
