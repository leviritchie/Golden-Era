import unittest
import numpy as np
from audit_rigid_capture_transfer import distance_drift


class RigidDistanceTests(unittest.TestCase):
    def test_translation_and_rotation_preserve_all_distances(self):
        points = np.array([[0., 0, 0], [1, 2, 0], [-1, 0, 3]])
        rotation = np.array([[0., -1, 0], [1, 0, 0], [0, 0, 1]])
        self.assertLess(distance_drift(np.stack([points, points@rotation.T+4])), 1e-12)
        changed = points.copy()
        changed[1, 0] += 1
        self.assertGreater(distance_drift(np.stack([points, changed])), .1)

    def test_nonfinite_and_invalid_shape_reject(self):
        for points in (np.zeros((0, 3, 3)), np.zeros((3, 3)), np.full((1, 3, 3), np.nan)):
            with self.assertRaises(ValueError):
                distance_drift(points)


if __name__ == '__main__':
    unittest.main()
