"""CPU tests for topology-owned harmonic skin candidate generation."""
import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from topology_owned_skin import solve


class TopologyOwnedSkinTests(unittest.TestCase):
    def setUp(self):
        # A connected strip with one exact duplicate weld (vertex 4 == 0).
        self.vertices = np.array([[0., 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 0]])
        self.triangles = np.array([[0, 1, 2], [4, 2, 3]], dtype=np.int64)
        self.original = np.array([[1., 0, 0], [.8, .2, 0], [.2, .8, 0], [0, 1., 0], [1., 0, 0]])

    def test_welded_strip_normalizes_and_preserves_weapon_pin(self):
        result, report = solve(self.vertices, self.triangles, self.original, [3], .015)
        self.assertEqual(report["uniqueSurfacePositions"], 4)
        self.assertTrue(np.allclose(result.sum(axis=1), 1.0, atol=1e-8))
        self.assertTrue(np.all(result >= -1e-10))
        self.assertTrue(np.array_equal(result[3], self.original[3]))
        self.assertTrue(np.array_equal(result[0], result[4]))
        self.assertLessEqual(int(np.count_nonzero(result > 1e-8, axis=1).max()), 8)

    def test_invalid_prior_strength_fails_closed(self):
        with self.assertRaises(ValueError):
            solve(self.vertices, self.triangles, self.original, [3], 0.0)
        with self.assertRaises(ValueError):
            solve(self.vertices, self.triangles, self.original, [3], float("nan"))

    def test_isolated_vertex_fails_closed(self):
        vertices = np.vstack([self.vertices, [[4., 4., 0.]]])
        with self.assertRaises(ValueError):
            solve(vertices, self.triangles, np.vstack([self.original, [[1., 0, 0]]]), [3], .015)


if __name__ == "__main__":
    unittest.main()
