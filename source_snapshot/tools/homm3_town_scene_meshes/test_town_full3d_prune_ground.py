"""Unit tests: town_full3d_recipe.ground_ray_px (the sky-side prune's ground-ray mask for `final`'s poses, read by
final_ground_tris; Dungeon zs_v7 2026-10-02). cuda against the numpy reference, and the rule on the rest camera.
Needs CUDA for the parity case (GPU first, no fallback)."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import town_full3d_recipe as R  # noqa: E402


def _scene():
    import stronghold_full3d_scene as S
    import stronghold_full3d_terrain as T
    import town_full3d_zero_streak as ZS
    sc = S.Scene()
    return sc, T, ZS


class GroundRayPx(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sc, cls.T, cls.ZS = _scene()
        full = cls.ZS.reachable_cams_full(cls.sc, R.FINAL_LOOP)
        cls.cams = {k: full[k] for k in list(full)[::17]}

    def test_rule_rest_camera(self):
        g = R.ground_ray_px(self.sc, self.T, self.sc.cam, "cpu")
        # the painted floor plane is below the horizon: the bottom row is ground, the top row is sky
        self.assertTrue(g[-1].all())
        self.assertFalse(g[0].any())

    def test_unknown_device_fails(self):
        with self.assertRaises(SystemExit):
            R.ground_ray_px(self.sc, self.T, self.sc.cam, "mps")

    def test_cuda_parity(self):
        import torch
        if not torch.cuda.is_available():
            self.fail("CUDA required for the parity case (GPU first, no fallback)")
        for k, cam in self.cams.items():
            a = R.ground_ray_px(self.sc, self.T, cam, "cpu")
            b = R.ground_ray_px(self.sc, self.T, cam, "cuda")
            self.assertTrue(np.array_equal(a, b), f"{k}: {int((a != b).sum())} px differ")


if __name__ == "__main__":
    unittest.main()
