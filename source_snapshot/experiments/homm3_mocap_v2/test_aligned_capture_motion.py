from __future__ import annotations

import unittest

import numpy as np
from scipy.spatial.transform import Rotation

from aligned_capture_motion import reconstruct_aligned


def _fixture():
    parents = np.array([-1, 0, 0, 1, 2], dtype=np.int64)
    names = ["root", "a", "b", "c", "d"]
    source_offsets = np.array([
        [0.0, 0.0, 0.0], [0.3, 0.9, 0.1], [-0.4, 0.5, 0.3],
        [0.6, 0.2, 0.1], [-0.3, 0.1, 0.7],
    ])
    fitted_offsets = source_offsets * np.array([[1.0], [1.2], [.8], [.9], [1.1]])

    def fk(local):
        pos = np.zeros((5, 3))
        world_rot = np.zeros((5, 3, 3))
        for j, p in enumerate(parents):
            if p < 0:
                world_rot[j] = local[j]
                continue
            world_rot[j] = world_rot[p] @ local[j]
            pos[j] = pos[p] + world_rot[p] @ source_offsets[j]
        return pos

    local = np.tile(np.eye(3), (3, 5, 1, 1))
    local[1, 1] = Rotation.from_euler("xyz", [23, -14, 36], degrees=True).as_matrix()
    local[1, 2] = Rotation.from_euler("xyz", [-16, 8, -11], degrees=True).as_matrix()
    local[2, 1] = Rotation.from_euler("xyz", [-21, 32, 7], degrees=True).as_matrix()
    capture = np.stack([fk(frame) for frame in local])
    capture += np.array([1.2, -0.4, 0.8])
    capture += np.array([[0.0, 0.0, 0.0], [0.12, -0.03, 0.05], [-0.07, 0.04, 0.02]])[:, None, :]
    return parents, names, source_offsets, fitted_offsets, capture


def _run(capture, offsets, fitted, parents, names):
    return reconstruct_aligned(
        capture_positions=capture,
        capture_reference_positions=capture[0],
        capture_offsets=offsets,
        fitted_offsets=fitted,
        parents=parents,
        names=names,
        hub_names=("root", "a", "b"),
    )


class AlignedCaptureMotionTests(unittest.TestCase):
  def test_alignment_is_source_gauge_invariant_with_articulated_motion(self):
    parents, names, offsets, fitted, capture = _fixture()
    rotation = Rotation.from_euler("xyz", [37, 21, 13], degrees=True).as_matrix()
    base = _run(capture, offsets, fitted, parents, names)
    rotated = _run(capture @ rotation.T, offsets @ rotation.T, fitted, parents, names)
    # Target outputs are compared directly: the target bind frame is fixed.
    self.assertLess(np.max(np.abs(base["positions"] - rotated["positions"])), 1e-9)
    self.assertLess(np.max(np.abs(base["localRotation"] - rotated["localRotation"])), 1e-9)
    self.assertTrue(base["motionPreservation"])
    self.assertEqual(base["sourceWholeBodyRotation"].shape, (3, 3))
    self.assertEqual(np.max(np.abs(base["fittedRest"] - rotated["fittedRest"])), 0.0)
    self.assertGreater(np.max(np.abs(base["localRotation"][1:] - np.eye(3))), 1e-3)


  def test_alignment_preserves_reference_bind_and_lengths(self):
    parents, names, offsets, fitted, capture = _fixture()
    result = _run(capture, offsets, fitted, parents, names)
    self.assertEqual(result["alignedCaptureReference"][0].tolist(), result["fittedRest"][0].tolist())
    self.assertLess(result["fixedLengthErrorMax"], 1e-8)
    self.assertEqual(np.max(np.abs(result["localTranslation"][0] - result["localTranslation"][1])), 0.0)
    self.assertLess(result["frame0LocalFromIdentityMaxRad"], 1e-8)

  def test_alignment_does_not_mutate_inputs_and_rejects_collinear_hubs(self):
    parents, names, offsets, fitted, capture = _fixture()
    originals = [x.copy() for x in (capture, offsets, fitted)]
    _run(capture, offsets, fitted, parents, names)
    for actual, expected in zip((capture, offsets, fitted), originals):
      self.assertTrue(np.array_equal(actual, expected))
    with self.assertRaisesRegex(ValueError, "rank-2"):
      _run(np.zeros_like(capture), offsets, fitted, parents, names)

  def test_alignment_reports_root_travel_and_so3(self):
    parents, names, offsets, fitted, capture = _fixture()
    result = _run(capture, offsets, fitted, parents, names)
    self.assertEqual(result["wholeBodyRotation"].shape, (3, 3))
    self.assertLess(np.max(np.abs(result["wholeBodyRotation"].T @ result["wholeBodyRotation"] - np.eye(3))), 1e-10)
    self.assertGreater(np.max(np.linalg.norm(result["positions"][:, 0] - result["positions"][0, 0], axis=1)), 0.0)
    self.assertTrue(np.array_equal(result["originalCaptureReferencePositions"], capture[0]))
