import sys
import itertools
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attachment_mask_refinement import complete_enclosed_mask_faces, refine_mask


class AttachmentMaskRefinementTests(unittest.TestCase):
    def setUp(self):
        self.vertices = np.array(
            [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
             [1, 0, 0], [2, 0, 0], [2, 1, 0], [1, 1, 0]], dtype=float)
        self.triangles = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]], dtype=np.int64)

    def test_strong_seeds_are_hard(self):
        passed = np.array([[True, True], [False, False], [True, True], [False, False]])
        result = refine_mask(self.vertices, self.triangles, passed, smoothness=10.0)
        self.assertEqual(result["selectedFaceIds"].tolist(), [0, 2])

    def test_uv_duplicate_positions_share_adjacency(self):
        passed = np.array([[True, True], [False, False], [True, True], [False, False]])
        result = refine_mask(self.vertices, self.triangles, passed)
        self.assertLess(result["weldedVertexCount"], len(self.vertices))
        self.assertGreaterEqual(result["adjacencyEdgeCount"], 2)

    def test_input_arrays_are_not_mutated(self):
        vertices, triangles = self.vertices.copy(), self.triangles.copy()
        passed = np.array([[True, False], [False, False], [True, False], [False, False]])
        refine_mask(vertices, triangles, passed)
        np.testing.assert_array_equal(vertices, self.vertices)
        np.testing.assert_array_equal(triangles, self.triangles)

    def test_malformed_inputs_fail_closed(self):
        with self.assertRaises(ValueError): refine_mask(self.vertices, self.triangles, np.ones((4, 2), dtype=np.int8))
        with self.assertRaises(ValueError): refine_mask(self.vertices, np.array([[0, 1, 99]]), np.ones((1, 2), dtype=bool))
        with self.assertRaises(ValueError): refine_mask(self.vertices, self.triangles, np.ones((3, 2), dtype=bool))

    def test_tiny_graph_matches_exhaustive_energy(self):
        vertices = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)
        triangles = np.array([[0, 1, 2], [0, 2, 3]], np.int64)
        passed = np.array([[True, True, True, False], [False, True, False, False]])
        result = refine_mask(vertices, triangles, passed, smoothness=0.5)
        p = passed.mean(1)
        area = np.array([0.5, 0.5])
        energy = []
        for labels in itertools.product((0, 1), repeat=2):
            unary = sum((-np.log(p[i]) if labels[i] else -np.log1p(-p[i])) * area[i] / np.median(area) for i in range(2))
            energy.append((unary + 0.5 * (labels[0] != labels[1]), labels))
        expected = min(energy)[1]
        self.assertEqual(tuple(int(x in set(result["selectedFaceIds"])) for x in range(2)), expected)

    def test_capacity_contract_rejects_overflow(self):
        vertices = np.array([[0, 0, 0], [1e20, 0, 0], [0, 1e20, 0], [1e20, 1e20, 0]], float)
        triangles = np.array([[0, 1, 2], [1, 3, 2]], np.int64)
        with self.assertRaises(ValueError):
            refine_mask(vertices, triangles, np.array([[True, False], [False, True]], dtype=bool), smoothness=1e20)

    def test_hard_seeds_survive_large_pairwise_weight(self):
        passed = np.array([[True, True], [False, False], [True, True], [False, False]])
        result = refine_mask(self.vertices, self.triangles, passed, smoothness=1e-8)
        self.assertEqual(result["selectedFaceIds"].tolist(), [0, 2])


class EnclosedMaskCompletionTests(unittest.TestCase):
    def setUp(self):
        # A center grid cell is background and is surrounded by selected
        # cells.  The outer grid cells remain the exterior background.
        self.vertices = np.array([[float(x), float(y), 0.] for y in range(4) for x in range(4)])
        faces = []
        for y in range(3):
            for x in range(3):
                a, b, c, d = y * 4 + x, y * 4 + x + 1, (y + 1) * 4 + x + 1, (y + 1) * 4 + x
                faces.extend([[a, b, c], [a, c, d]])
        self.triangles = np.asarray(faces, dtype=np.int64)
        self.center = np.array([8, 9], dtype=np.int64)
        self.selected_ring = np.array([2, 3, 6, 7, 10, 11, 14, 15], dtype=np.int64)

    def test_enclosed_component_is_added_without_geometry_change(self):
        result = complete_enclosed_mask_faces(self.vertices, self.triangles, self.selected_ring)
        self.assertEqual(result["expandedFaceIds"].tolist(), sorted(self.selected_ring.tolist() + self.center.tolist()))
        self.assertEqual(result["addedComponents"][0]["faceIds"], [8, 9])
        self.assertFalse(result["accepted"])
        self.assertEqual(result["proof"], "diagnostic-enclosed-mask-completion")

    def test_open_background_patch_is_refused(self):
        result = complete_enclosed_mask_faces(self.vertices, self.triangles, np.setdiff1d(self.selected_ring, [7]))
        self.assertTrue(any(row["reason"] == "open_boundary_edge" for row in result["rejectedReasons"]))
        self.assertTrue(any(row["reason"] == "open_boundary_edge" for row in result["rejectedReasons"]))

    def test_uv_seam_duplicate_positions_are_welded(self):
        vertices = np.vstack([self.vertices, self.vertices[5]])
        triangles = self.triangles.copy()
        triangles[8, 0] = 16
        result = complete_enclosed_mask_faces(vertices, triangles, self.selected_ring)
        self.assertTrue(set(self.center).issubset(set(result["expandedFaceIds"])))
        self.assertLess(result["weldedVertexCount"], len(vertices))

    def test_isolated_background_component_is_untouched_and_seed_protects_hole(self):
        vertices = np.vstack([self.vertices, [[4., 4, 4], [5., 4, 4], [4., 5, 4]]])
        triangles = np.vstack([self.triangles, [[16, 17, 18]]])
        result = complete_enclosed_mask_faces(vertices, triangles, self.selected_ring)
        self.assertNotIn(18, result["expandedFaceIds"])
        protected = complete_enclosed_mask_faces(self.vertices, self.triangles, self.selected_ring,
                                                 background_seed_face_ids=self.center)
        self.assertEqual(protected["expandedFaceIds"].tolist(), self.selected_ring.tolist())

    def test_malformed_and_nonmanifold_inputs_fail_closed(self):
        with self.assertRaises(ValueError): complete_enclosed_mask_faces(self.vertices, self.triangles, [1, 1])
        with self.assertRaises(ValueError): complete_enclosed_mask_faces(self.vertices, self.triangles, [1], background_seed_face_ids=[1])
        nonmanifold = np.vstack([self.triangles, [self.triangles[8]]])
        result = complete_enclosed_mask_faces(self.vertices, nonmanifold, self.selected_ring)
        self.assertTrue(any(row["reason"] == "nonmanifold_edges" for row in result["rejectedReasons"]))

    def test_tiny_protected_background_does_not_replace_largest_exterior(self):
        vertices = np.array([
            [0., 0., 1.], [0., 0., -1.], [2., 0., 0.], [0., 1., 0.],
            [-10., 0., 0.], [0., -4., 0.],
        ])
        triangles = np.array([
            [0, 2, 3], [0, 3, 4], [0, 4, 5], [0, 5, 2],
            [1, 4, 3], [1, 3, 2], [1, 2, 5], [1, 5, 4],
        ], dtype=np.int64)
        selected = np.array([1, 2, 3, 5, 6, 7], dtype=np.int64)
        result = complete_enclosed_mask_faces(vertices, triangles, selected,
                                              background_seed_face_ids=[0])
        self.assertEqual(result["expandedFaceIds"].tolist(), selected.tolist())
        self.assertNotIn(0, result["expandedFaceIds"])
        self.assertNotIn(4, result["expandedFaceIds"])


if __name__ == "__main__":
    unittest.main()
