"""Unit test: town_full3d_sprite_decal.layer_card_depth (decal "layerDepth"): a decal px whose environment lies past the
layer's back goes to the layer's depth; ground just behind the building's foot stays on the environment (Cove zs_v1
2026-10-02: the hall's gable decal on the cliff 185-264 m out behind a 51-72 m hall)."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import town_full3d_ldi as L  # noqa: E402
import town_full3d_sprite_decal as DC  # noqa: E402


class _TP:
    """zbuffer(cam, P, F): the layer covers columns 0-31 of a 64x64 frame at forward depth 50..60 (face id 0)."""

    @staticmethod
    def zbuffer(cam, P, F, sup=1):
        z = np.full((64, 64), np.inf)
        fid = -np.ones((64, 64), np.int64)
        z[:, :32] = np.linspace(50.0, 60.0, 32)[None]
        fid[:, :32] = 0
        return z, fid


class LayerCardDepth(unittest.TestCase):
    def test_far_px_to_layer_depth_near_ground_kept(self):
        sc = type("Sc", (), {"cam": None})()
        names = ["environment/Mesh_Terrain", "homm3_cove3d_tbcvhall/Mesh_Body_tbcvhall",
                 "homm3_cove3d_tbcvhall/Mesh_Decal_tbcvhall"]
        F = np.array([[0, 1, 2], [0, 1, 2], [0, 1, 2]])
        owner = np.array([0, 1, 2])
        z_env = np.full((64, 64), 62.0)
        z_env[:, 40:] = 200.0                    # the cliff behind the gable
        mask = np.zeros((64, 64), bool)
        mask[:, 32:48] = True
        z, card, drawn = DC.layer_card_depth(_TP, sc, None, F, owner, names, z_env, mask, L)
        self.assertEqual(drawn, 64 * 32)
        self.assertTrue(card[:, 40:48].all())                      # 200 > back ~60 x 1.05
        self.assertFalse(card[:, 32:40].any() or card[:, 48:].any())   # 62 at the foot stays; off-mask untouched
        self.assertTrue(np.all(z[:, 40:48] < 65) and np.all(z[:, 40:48] > 45))   # the layer's depth, filled
        self.assertTrue(np.array_equal(z[~card], z_env[~card]))


if __name__ == "__main__":
    unittest.main()
