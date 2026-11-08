from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_surface_loss_attribution import _face_debug_geometry


class FaceDebugGeometryTests(unittest.TestCase):
    def test_selected_faces_use_red_constant_uv_and_unselected_use_gray(self) -> None:
        triangles = np.asarray([[0, 1, 2], [2, 3, 0], [1, 3, 2]], dtype=np.int64)
        expanded, uvs, texture = _face_debug_geometry(triangles, [1])
        self.assertEqual(expanded.shape, (3, 3))
        np.testing.assert_allclose(uvs[0:3], np.tile((0.25, 0.5), (3, 1)))
        np.testing.assert_allclose(uvs[3:6], np.tile((0.75, 0.5), (3, 1)))
        np.testing.assert_allclose(uvs[6:9], np.tile((0.25, 0.5), (3, 1)))
        np.testing.assert_array_equal(texture[0, 0], (150, 150, 150))
        np.testing.assert_array_equal(texture[0, 1], (220, 25, 25))

    def test_selection_changes_only_face_uv_assignment(self) -> None:
        triangles = np.asarray([[0, 1, 2], [2, 3, 0]], dtype=np.int64)
        first = _face_debug_geometry(triangles, [0])
        second = _face_debug_geometry(triangles, [1])
        np.testing.assert_array_equal(first[0], second[0])
        self.assertFalse(np.array_equal(first[1], second[1]))
        np.testing.assert_array_equal(first[2], second[2])


if __name__ == "__main__":
    unittest.main()
