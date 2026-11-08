import unittest
from pathlib import Path
import numpy as np

from experiments.homm3_mocap_v2.oe_motion_style_v2 import MAX_GAIN, style_rotations
from experiments.homm3_mocap_v2.glb_skeleton import load_bind_skeleton


class MotionStyleV2Tests(unittest.TestCase):
    def test_world_chain_identity_and_root(self):
        q = np.zeros((3, 3, 4), dtype=float); q[..., 3] = 1.0
        q[1, 1] = [0, 0, np.sin(.2), np.cos(.2)]
        result = style_rotations(q, (-1, 0, 1), np.array([0., .5, 1.]), mode="attack", gain=1.45)
        np.testing.assert_allclose(result[0], q[0], atol=1e-6)
        np.testing.assert_allclose(result[-1], q[-1], atol=1e-6)
        np.testing.assert_allclose(result[:, 0], q[:, 0], atol=1e-6)
        np.testing.assert_allclose(np.linalg.norm(result, axis=-1), 1.0, atol=1e-6)

    def test_gain_one_keeps_nontrivial_motion_and_gain_grows_angle(self):
        q = np.zeros((3, 3, 4), dtype=float); q[..., 3] = 1.0
        q[1, 1] = [0, 0, np.sin(.2), np.cos(.2)]
        identity = style_rotations(q, (-1, 0, 1), np.array([0., .5, 1.]), mode="attack", gain=1.0)
        np.testing.assert_allclose(identity, q, atol=1e-6)
        styled = style_rotations(q, (-1, 0, 1), np.array([0., .5, 1.]), mode="attack", gain=1.45)
        original_angle = 2.0 * np.arctan2(abs(q[1, 1, 2]), q[1, 1, 3])
        styled_angle = 2.0 * np.arctan2(abs(styled[1, 1, 2]), styled[1, 1, 3])
        self.assertAlmostEqual(styled_angle / original_angle, 1.45, places=2)

    def test_gain_cap_allows_plus_120_and_refuses_above_it(self):
        q = np.zeros((3, 3, 4), dtype=float); q[..., 3] = 1.0
        q[1, 1] = [0, 0, np.sin(.2), np.cos(.2)]
        times = np.array([0., .5, 1.])
        style_rotations(q, (-1, 0, 1), times, mode="move", gain=2.20)
        with self.assertRaisesRegex(ValueError, "gain must be"):
            style_rotations(q, (-1, 0, 1), times, mode="move", gain=MAX_GAIN + 0.01)

    def test_leaf_rotation_is_preserved(self):
        q = np.zeros((3, 3, 4), dtype=float); q[..., 3] = 1.0
        q[1, 2] = [0, np.sin(.3), 0, np.cos(.3)]
        result = style_rotations(q, (-1, 0, 1), np.array([0., .5, 1.]), mode="attack", gain=1.45)
        np.testing.assert_allclose(result[:, 2], q[:, 2], atol=1e-6)

    def test_actual_v2_candidate_rest_and_skin(self):
        root = Path(__file__).resolve().parents[2]
        source = root / "artifacts/homm3_mocap_v2/stronghold_ingame_test_v1/raw/h3_goblin/g00_move.glb"
        candidate = root / "artifacts/homm3_mocap_v2/oe_style_pilot_v2/motion/h3_goblin/g00_move.glb"
        if not source.is_file() or not candidate.is_file():
            self.skipTest("v2 pilot artifact unavailable")
        original = load_bind_skeleton(source); styled = load_bind_skeleton(candidate)
        np.testing.assert_array_equal(styled.vertices, original.vertices)
        np.testing.assert_array_equal(styled.triangles, original.triangles)
        np.testing.assert_array_equal(styled.uvs, original.uvs)
        np.testing.assert_array_equal(styled.inverse_bind, original.inverse_bind)


if __name__ == "__main__":
    unittest.main()
