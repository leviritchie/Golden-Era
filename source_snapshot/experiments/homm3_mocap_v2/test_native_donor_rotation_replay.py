import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import native_donor_rotation_replay as replay
from donor_eagle import bind_world_matrices, inverse_bind_matrices, skin_dense
from mesh_preview import fk_world_matrices


class NativeDonorRotationReplayTests(unittest.TestCase):
    def _rot_z(self, angle):
        c, s = np.cos(angle), np.sin(angle)
        return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])

    def test_decoded_rotation_rows_and_fk_are_replayed(self):
        parents = np.array([-1, 0], dtype=np.int64)
        offsets = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        direct = np.stack([self._rot_z(0.4), self._rot_z(-0.3)])[None]
        encoded = np.concatenate((direct[..., 0, :], direct[..., 1, :]), axis=-1)
        result = replay.replay_native_rotations(encoded, offsets, parents, [2.0, -1.0, 0.5])
        np.testing.assert_allclose(result["localRotation"], direct, atol=1e-7)
        expected = fk_world_matrices(local_rotation=direct[0], local_translation=offsets,
                                     parents=parents, root_world=[2.0, -1.0, 0.5])
        np.testing.assert_allclose(result["jointWorld"][0], expected, atol=1e-7)
        np.testing.assert_allclose(result["positions"][0], expected[:, :3, 3], atol=1e-7)

    def test_identity_bind_mesh_parity(self):
        parents = np.array([-1, 0], dtype=np.int64)
        offsets = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        bind = bind_world_matrices(offsets, parents)
        inverse = inverse_bind_matrices(bind)
        vertices = np.array([[0.2, 0.3, 0.0], [1.1, -0.2, 0.4]])
        weights = np.array([[1.0, 0.0], [0.0, 1.0]])
        encoded = np.zeros((1, 2, 6), dtype=np.float64)
        encoded[..., 0] = 1.0
        encoded[..., 4] = 1.0
        result = replay.replay_native_rotations(encoded, offsets, parents, np.zeros(3),
                                                vertices=vertices, weights=weights,
                                                inverse_bind=inverse)
        np.testing.assert_allclose(result["meshes"][0], vertices, atol=1e-10)
        np.testing.assert_allclose(result["meshes"][0], skin_dense(vertices, weights,
                                                                      result["jointWorld"][0], inverse), atol=1e-10)

    def test_degenerate_decoded_rotation_is_rejected(self):
        parents = np.array([-1], dtype=np.int64)
        encoded = np.ones((1, 1, 6), dtype=np.float64)
        bad = np.zeros((1, 1, 3, 3), dtype=np.float32)
        with patch.object(replay, "rotations_from_6d", return_value=(bad, None)):
            with self.assertRaisesRegex(ValueError, "orthonormal"):
                replay.replay_native_rotations(encoded, np.zeros((1, 3)), parents, np.zeros(3))

    def test_actual_decoder_rejects_zero_and_collinear_rows(self):
        for values in ([0,0,0,0,0,0], [1,0,0,2,0,0]):
            with self.assertRaises(ValueError):
                replay.replay_native_rotations(np.array(values)[None,None],
                    np.zeros((1,3)),np.array([-1]),np.zeros(3))

    def test_inputs_are_not_mutated_and_anchor_can_be_per_frame(self):
        parents = np.array([-1, 0], dtype=np.int64)
        offsets = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        encoded = np.zeros((2, 2, 6), dtype=np.float64)
        encoded[..., 0] = 1.0
        encoded[..., 4] = 1.0
        anchor = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        before = (encoded.copy(), offsets.copy(), parents.copy(), anchor.copy())
        identity = np.repeat(np.eye(3)[None, None], 4, axis=0).reshape(2, 2, 3, 3)
        with patch.object(replay, "rotations_from_6d", return_value=(identity.astype(np.float32), None)):
            result = replay.replay_native_rotations(encoded, offsets, parents, anchor)
        np.testing.assert_array_equal(encoded, before[0]); np.testing.assert_array_equal(offsets, before[1])
        np.testing.assert_array_equal(parents, before[2]); np.testing.assert_array_equal(anchor, before[3])
        np.testing.assert_allclose(result["positions"][:, 0], anchor)

    def test_partial_mesh_and_bad_anchor_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "together"):
            replay.replay_native_rotations(np.ones((1, 1, 6)), np.zeros((1, 3)), np.array([-1]),
                                           np.zeros(3), vertices=np.zeros((1, 3)))
        with self.assertRaisesRegex(ValueError, "root_anchor"):
            replay.replay_native_rotations(np.ones((1, 1, 6)), np.zeros((1, 3)), np.array([-1]),
                                           np.zeros((2, 3)))


if __name__ == "__main__":
    unittest.main()
