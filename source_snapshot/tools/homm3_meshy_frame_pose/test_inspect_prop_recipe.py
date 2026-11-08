"""Visible surface picking must not seed the hidden side of a thin prop."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from inspect_prop_recipe import pick_surface, inspection_view, render
import inspect_prop_recipe as inspection


class PickingTests(unittest.TestCase):
    def test_panel_scale_keeps_diagnostic_dimensions_explicit(self):
        with patch.object(inspection.render, "textured", return_value=np.zeros((2800, 2400, 3), dtype=np.uint8)):
            surface = {
                "positions": np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]),
                "normals": np.array([[0., 0., 1.]] * 3),
                "baseColor": np.zeros((1, 1, 3), dtype=np.uint8),
            }
            path = Path("panel_scale_test.png")
            try:
                inspection.save_view(path, surface, np.array([0, 1, 2]), {}, "scaled", 4)
                with Image.open(path) as image:
                    self.assertEqual(image.size, (2400, 2800))
            finally:
                path.unlink(missing_ok=True)

    def test_failed_inspection_invalidates_previous_and_partial_outputs(self):
        with patch.object(sys, "argv", ["inspect", "--mesh", "missing.glb", "--out", "review"]), \
             patch.object(inspection, "inspect", side_effect=ValueError("bad recipe")), \
             patch.object(inspection, "invalidate_inspection") as invalidate:
            with self.assertRaisesRegex(ValueError, "bad recipe"):
                inspection.main()
            self.assertEqual([call.args[1]["status"] for call in invalidate.call_args_list], ["running", "error"])
            self.assertEqual(invalidate.call_args.args[1]["props"], [])

    def setUp(self):
        self.view = {"right": np.array([1., 0., 0.]), "down": np.array([0., 1., 0.]),
                     "forward": np.array([0., 0., 1.]), "k": 100., "off": np.array([20., 30.])}
        self.points = np.array([[0., 0., 2.], [1., 0., 2.], [0., 1., 2.],
                                [0., 0., -1.], [1., 0., -1.], [0., 1., -1.]])

    def test_frontmost_face_and_exact_barycentric_point(self):
        hit = pick_surface(self.points, np.array([0, 1, 2, 3, 4, 5]), self.view, [45, 55])
        self.assertEqual(hit["face"], 1)
        np.testing.assert_allclose(hit["point"], [.255, .255, -1.])
        np.testing.assert_allclose(hit["barycentric"], [.49, .255, .255])

    def test_winding_does_not_change_hit(self):
        hit = pick_surface(self.points, np.array([3, 5, 4]), self.view, [45, 55])
        np.testing.assert_allclose(hit["point"], [.255, .255, -1.])

    def test_empty_background_does_not_return_nearest_vertex(self):
        with self.assertRaisesRegex(ValueError, "hits no surface"):
            pick_surface(self.points, np.array([0, 1, 2]), self.view, [500, 500])

    def test_degenerate_face_is_ignored(self):
        hit = pick_surface(self.points, np.array([0, 0, 0, 3, 4, 5]), self.view, [45, 55])
        self.assertEqual(hit["face"], 1)

    def test_camera_fits_bounds_not_vertex_density(self):
        points = np.vstack((np.tile([0., 5., 0.], (100, 1)), [[-2., -3., 1.], [2., -3., -1.]]))
        view = inspection_view(0, points)
        xy = np.column_stack((points @ view["right"], points @ view["down"])) * view["k"] + view["off"]
        np.testing.assert_allclose((xy.min(axis=0) + xy.max(axis=0)) / 2, np.array(render.PANEL) / 2)
        self.assertTrue(np.all(xy.min(axis=0) >= 0))
        self.assertTrue(np.all(xy.max(axis=0) <= render.PANEL))


if __name__ == "__main__":
    unittest.main()
