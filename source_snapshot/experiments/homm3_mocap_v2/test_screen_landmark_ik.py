import unittest
import numpy as np
from unittest import mock
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import screen_landmark_ik
from screen_landmark_ik import solve


class ScreenLandmarkIKTests(unittest.TestCase):
    def test_reduces_error_and_preserves_inactive_joint(self):
        rotations = np.repeat(np.eye(3)[None, None], 3, axis=0).repeat(2, axis=1)
        offsets = np.array([[0, 0, 0], [1, 0, 0]], dtype=float)
        parents = np.array([-1, 0])
        roots = np.zeros((3, 3))
        sites = {"tip": {"joint": 1, "localPoint": [1, 0, 0]}}
        targets = np.tile([[1, 1]], (3, 1, 1)).astype(float)
        fitted, worlds, report = solve(rotations, offsets, parents, roots,
            {"right": [1, 0, 0], "down": [0, 1, 0], "scale": 10, "offset": [0, 0]}, [1], sites, targets, np.ones((3, 1)))
        self.assertLess(report["finalPixelError"], report["initialPixelError"])
        self.assertEqual(report["unchangedInactiveMatrixError"], 0)
        self.assertEqual(worlds.shape, (3, 2, 4, 4))

    def test_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            solve(np.eye(3)[None, None], [[0, 0, 0]], [-1], [[0, 0, 0]], {}, [], {}, np.zeros((1, 1, 2)), np.ones((1, 1)))

    def test_fixed_offset_parity_uses_local_offset_lengths(self):
        rotations = np.repeat(np.eye(3)[None, None], 1, axis=0).repeat(2, axis=1)
        result = solve(rotations, [[3, 4, 0], [0, 3, 4]], [-1, 0], [[0, 0, 0]],
            {"right": [1, 0, 0], "down": [0, 1, 0], "scale": 1, "offset": [0, 0]}, [1],
            {"tip": {"joint": 1, "localPoint": [0, 0, 0]}}, [[[0, 0]]], [[1]])
        self.assertTrue(result[2]["fixedOffsetParity"])

    def test_multiframe_sparse_fit_without_temporal_term(self):
        rotations = np.repeat(np.eye(3)[None, None], 4, axis=0).repeat(3, axis=1)
        result = solve(rotations, [[0, 0, 0], [1, 0, 0], [1, 0, 0]], [-1, 0, 1], np.zeros((4, 3)),
            {"right": [1, 0, 0], "down": [0, 1, 0], "scale": 10, "offset": [0, 0]}, [1, 2],
            {"tip": {"joint": 2, "localPoint": [1, 0, 0]}}, np.tile([[[2, 0]]], (4, 1, 1)), np.ones((4, 1)),
            temporal_weight=0, max_nfev=10)
        self.assertTrue(result[2]["fixedOffsetParity"])

    def test_per_joint_rotation_bounds_are_enforced(self):
        rotations = np.repeat(np.eye(3)[None, None], 2, axis=0).repeat(2, axis=1)
        result = solve(rotations, [[0, 0, 0], [1, 0, 0]], [-1, 0], np.zeros((2, 3)),
            {"right": [1, 0, 0], "down": [0, 1, 0], "scale": 10, "offset": [0, 0]}, [1],
            {"tip": {"joint": 1, "localPoint": [1, 0, 0]}}, np.tile([[[0, 10]]], (2, 1, 1)), np.ones((2, 1)),
            max_degrees=[3], max_nfev=20)
        self.assertLessEqual(result[2]["maxDeltaDegrees"]["1"], 3.0001)

    def test_rejects_non_rotation_and_invalid_graph(self):
        bad_rotation = np.zeros((1, 1, 3, 3))
        with self.assertRaises(ValueError):
            solve(bad_rotation, [[0, 0, 0]], [-1], [[0, 0, 0]],
                {"right": [1, 0, 0], "down": [0, 1, 0], "scale": 1, "offset": [0, 0]}, [0],
                {"tip": {"joint": 0, "localPoint": [0, 0, 0]}}, [[[0, 0]]], [[1]])

    def test_distinct_joint_bounds_repeat_each_axis_in_frame_order(self):
        rotations = np.repeat(np.eye(3)[None, None], 3, axis=1)
        parents = [-1, 0, 1]
        offsets = [[0, 0, 0], [1, 0, 0], [1, 0, 0]]
        camera = {"right": [1, 0, 0], "down": [0, 1, 0], "scale": 1, "offset": [0, 0]}
        sites = {"tip": {"joint": 2, "localPoint": [1, 0, 0]}}
        captured = {}
        real_least_squares = screen_landmark_ik.least_squares

        def record_bounds(*args, **kwargs):
            captured["bounds"] = kwargs["bounds"]
            return real_least_squares(*args, **kwargs)

        with mock.patch.object(screen_landmark_ik, "least_squares", side_effect=record_bounds):
            solve(rotations, offsets, parents, [[0, 0, 0]], camera, [1, 2], sites,
                  [[[3, 0]]], [[1]], max_degrees=[3, 10], max_nfev=1)
        lower, upper = captured["bounds"]
        np.testing.assert_allclose(np.rad2deg(-lower), [3, 3, 3, 10, 10, 10])
        np.testing.assert_allclose(np.rad2deg(upper), [3, 3, 3, 10, 10, 10])


if __name__ == "__main__":
    unittest.main()
