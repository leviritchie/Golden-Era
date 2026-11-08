import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from anatomical_direction_transfer import transfer_direction
from direction_retarget import transfer_chain_directions


def rot(axis, degrees):
    axis = np.asarray(axis, dtype=float)
    axis /= np.linalg.norm(axis)
    x, y, z = axis
    a = np.deg2rad(degrees)
    c, s = np.cos(a), np.sin(a)
    k = np.array([[0., -z, y], [z, 0., -x], [-y, x, 0.]])
    return np.eye(3) * c + s * k + (1 - c) * np.outer(axis, axis)


class AnatomicalDirectionTransferTests(unittest.TestCase):
    def test_explicit_hint_removes_observed_one_edge_axis_dependence(self):
        c = np.array([1., 0., 0.])
        t = np.array([1., 1., 0.])
        p = rot([0, 0, 1], 35) @ c
        h = np.array([0., 1., 0.])
        q = rot([0, 0, 1], 17) @ rot([0, 1, 0], 61) @ rot([1, 0, 0], 32)

        def old(source, target, pose):
            return transfer_chain_directions(
                capture_polyline=np.stack([np.zeros(3), pose]),
                capture_rest_polyline=np.stack([np.zeros(3), source]),
                target_rest_polyline=np.stack([np.zeros(3), target]),
                sample_count=1,
            )[0]

        # This fixture demonstrates the historical path's axis dependence;
        # it is not an acceptance gate for the complete retargeter.
        legacy_error = np.degrees(np.arccos(np.clip(
            np.dot(q @ old(c, t, p), old(q @ c, q @ t, q @ p)), -1., 1.)))
        self.assertAlmostEqual(legacy_error, 5.712279411, places=7)
        expected = q @ transfer_direction(c, t, p, h, h)
        actual = transfer_direction(q @ c, q @ t, q @ p, q @ h, q @ h)
        np.testing.assert_allclose(actual, expected, atol=1e-12)

    def test_neutral_maps_target_rest_direction(self):
        result = transfer_direction([1, 0, 0], [0, 1, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1])
        np.testing.assert_allclose(result, [0, 1, 0], atol=1e-12)

    def test_common_world_rotation_is_equivariant(self):
        q = rot([1, 2, 3], 32)
        source = transfer_direction([1, 0, 0], [0, 1, 0], rot([0, 0, 1], 35) @ np.array([1., 0, 0]), [0, 1, 0], [1, 0, 0])
        rotated = transfer_direction(q @ np.array([1., 0, 0]), q @ np.array([0., 1, 0]),
                                     q @ rot([0, 0, 1], 35) @ np.array([1., 0, 0]), q @ np.array([0., 1, 0]), q @ np.array([1., 0, 0]))
        np.testing.assert_allclose(rotated, q @ source, atol=1e-10)

    def test_distinct_source_target_gauges_transfer_expected_local_direction(self):
        result = transfer_direction([1, 0, 0], [0, 0, 1], [0, 1, 0], [0, 1, 0], [0, 1, 0])
        np.testing.assert_allclose(result, [0, 1, 0], atol=1e-12)
        self.assertAlmostEqual(np.linalg.norm(result), 1.0)

    def test_rejects_zero_and_collinear_hints(self):
        with self.assertRaisesRegex(ValueError, "nonzero"):
            transfer_direction([1, 0, 0], [0, 1, 0], [1, 0, 0], [0, 0, 0], [0, 0, 1])
        with self.assertRaisesRegex(ValueError, "collinear"):
            transfer_direction([1, 0, 0], [0, 1, 0], [1, 0, 0], [1, 0, 0], [0, 0, 1])

        with self.assertRaisesRegex(ValueError, "collinear"):
            transfer_direction([1, 0, 0], [0, 1, 0], [1, 0, 0], [1., 5e-7, 0.], [0, 0, 1])

    def test_rejects_nonfinite_inputs(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            transfer_direction([np.nan, 0, 0], [0, 1, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1])

    def test_independent_source_and_target_world_changes_are_covariant(self):
        source_q = rot([1, 2, 3], 61)
        target_q = rot([3, -1, 2], 17)
        source_rest, source_pose, source_hint = np.array([1., 0, 0]), np.array([0., 0, 1]), np.array([0., 1, 0])
        target_rest, target_hint = np.array([0., 1, 0]), np.array([1., 0, 0])
        baseline = transfer_direction(source_rest, target_rest, source_pose, source_hint, target_hint)
        changed = transfer_direction(source_q @ source_rest, target_q @ target_rest,
                                     source_q @ source_pose, source_q @ source_hint, target_q @ target_hint)
        np.testing.assert_allclose(changed, target_q @ baseline, atol=1e-10)


if __name__ == "__main__":
    unittest.main()
