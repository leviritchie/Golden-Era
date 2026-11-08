"""Tests for the diagnostic local-rotation capture transfer."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

from donor_eagle import compute_rest_joints
from local_rotation_capture_motion import reconstruct_local_rotation
from mesh_preview import fk_world_matrices
from test_native_rotation import axis_rotation


def _rig() -> tuple[np.ndarray, np.ndarray, list[str]]:
    parents = np.asarray((-1, 0, 1, 1), dtype=np.int64)
    offsets = np.zeros((4, 3), dtype=np.float64)
    offsets[1] = (0.0, 1.0, 0.0)
    offsets[2] = (1.0, 0.0, 0.0)
    offsets[3] = (-1.0, 0.0, 0.0)
    return parents, offsets, ["root", "hub", "left", "right"]


def _fk(offsets: np.ndarray, parents: np.ndarray, local: np.ndarray, root: np.ndarray) -> np.ndarray:
    return fk_world_matrices(
        local_rotation=local,
        local_translation=offsets,
        parents=parents,
        root_world=root,
    )[:, :3, 3]


class LocalRotationCaptureMotionTests(unittest.TestCase):
    def test_rigid_turn_different_rest_angles_with_structural_hub(self):
        parents = np.array([-1, 0, 1, 1, 1])
        offsets = np.array([[0., 0., 0.], [0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]])
        names = ['root', 'hub', 'a', 'b', 'c']
        reference = compute_rest_joints(offsets, parents) + [2., -1., 3.]
        fitted = np.array([[.2, .3, .1], [0., 0., 0.], [1., .1, .1], [-.1, 1.8, .2], [.2, -.1, .8]])
        r = axis_rotation(0, .7) @ axis_rotation(2, -.4)
        capture = np.stack([reference, (reference-reference[0]) @ r.T + reference[0] + [.1, .3, -.2]])
        result = reconstruct_local_rotation(capture_positions=capture, capture_reference_positions=reference,
            capture_offsets=offsets, fitted_offsets=fitted, parents=parents, names=names, hub_names=tuple(names[1:]))
        q = result['staticBindRotation']
        rest = result['fittedRest']
        expected = (rest-rest[0]) @ (q @ r @ q.T).T + rest[0] + q @ np.array([.1, .3, -.2])
        np.testing.assert_allclose(result['positions'][1], expected, atol=1e-10)
        self.assertLess(result['fixedLengthErrorMax'], 1e-10)

    def _call(self, capture: np.ndarray, reference: np.ndarray, fitted: np.ndarray) -> dict:
        parents, offsets, names = _rig()
        return reconstruct_local_rotation(
            capture_positions=capture,
            capture_reference_positions=reference,
            capture_offsets=offsets,
            fitted_offsets=fitted,
            parents=parents,
            names=names,
            hub_names=("root", "hub", "left", "right"),
        )

    def test_reference_bind_identity_with_different_rest(self) -> None:
        parents, offsets, _ = _rig()
        reference = compute_rest_joints(offsets, parents)
        fitted = offsets.copy()
        fitted[1] = (0.0, 2.0, 0.0)
        fitted[2] = (1.5, 0.0, 0.0)
        fitted[3] = (-1.5, 0.0, 0.0)
        result = self._call(np.repeat(reference[None], 2, axis=0), reference, fitted)
        self.assertTrue(result["clipFrame0IsBind"])
        self.assertLess(result["fixedLengthErrorMax"], 1e-8)

    def test_pure_global_turn_and_root_translation_use_same_q(self) -> None:
        parents, offsets, _ = _rig()
        reference = compute_rest_joints(offsets, parents)
        q = axis_rotation(1, 0.4)
        root_delta = np.asarray((0.3, -0.2, 0.5))
        fitted = (q @ offsets.T).T
        capture = np.stack([reference, reference])
        capture[1] = (q @ reference.T).T + root_delta
        result = self._call(capture, reference, fitted)
        expected = (q @ capture[1].T).T
        np.testing.assert_allclose(result["positions"][1], expected, atol=1e-6)
        np.testing.assert_allclose(result["staticBindRotation"], q, atol=1e-6)

    def test_nonidentity_q_and_fixed_lengths(self) -> None:
        parents, offsets, _ = _rig()
        reference = compute_rest_joints(offsets, parents)
        q = axis_rotation(1, 0.4)
        fitted = (q @ offsets.T).T
        result = self._call(np.repeat(reference[None], 2, axis=0), reference, fitted)
        self.assertGreater(np.linalg.norm(result["staticBindRotation"] - np.eye(3)), 1e-3)
        self.assertLess(result["fixedLengthErrorMax"], 1e-8)

    def test_inputs_are_not_mutated(self) -> None:
        parents, offsets, names = _rig()
        reference = compute_rest_joints(offsets, parents)
        capture = np.repeat(reference[None], 2, axis=0)
        snapshots = [capture.copy(), reference.copy(), offsets.copy()]
        self._call(capture, reference, offsets)
        for actual, expected in zip((capture, reference, offsets), snapshots):
            np.testing.assert_array_equal(actual, expected)


if __name__ == "__main__":
    unittest.main()
