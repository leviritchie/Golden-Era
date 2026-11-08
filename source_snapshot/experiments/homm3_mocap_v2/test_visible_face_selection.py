"""Occluded geometry must not be selected through a screen-space polygon."""
import unittest

import numpy as np

from mesh_preview import raster_mesh, visible_faces_in_polygon


class VisibleFaceSelectionTests(unittest.TestCase):
    def fixture(self, reverse=False):
        front = np.array([[1., 1., 0.], [1., 6., 0.], [6., 1., 0.]])
        vertices = np.concatenate([front, front + [0., 0., 1.]])
        triangles = np.array([[0, 1, 2], [3, 4, 5]])
        if reverse:
            triangles = triangles[::-1]
        return dict(vertices=vertices, triangles=triangles, width=8, height=8,
                    camera={'basisScreenRows': [[1., 0., 0.], [0., 1., 0.]],
                            'pxPerWorld': 1., 'screenOffsetPx': [0., 0.]})

    def test_only_frontmost_surface_selected_in_either_draw_order(self):
        polygon = np.array([[0, 0], [8, 0], [8, 8], [0, 8]])
        for reverse in (False, True):
            image, ids = raster_mesh(**self.fixture(reverse), return_face_ids=True)
            result = visible_faces_in_polygon(ids, polygon)
            self.assertEqual(result['faceIds'], [int(reverse)])
            self.assertEqual(sum(result['visiblePixelCounts']), int((ids >= 0).sum()))
            self.assertTrue(np.all(ids[np.asarray(image)[..., 3] == 0] == -1))

    def test_default_render_unchanged(self):
        ordinary = raster_mesh(**self.fixture())
        with_ids, _ = raster_mesh(**self.fixture(), return_face_ids=True)
        np.testing.assert_array_equal(ordinary, with_ids)

    def test_explicit_double_sided_surface_keeps_occlusion(self):
        fixture = self.fixture()
        fixture['triangles'][0] = [0, 2, 1]
        _, culled = raster_mesh(**fixture, return_face_ids=True)
        _, double_sided = raster_mesh(**fixture, return_face_ids=True,
                                      cull_backfaces=False)
        self.assertEqual(set(culled[culled >= 0]), {1})
        self.assertEqual(set(double_sided[double_sided >= 0]), {0})

    def test_background_polygon_selects_nothing(self):
        _, ids = raster_mesh(**self.fixture(), return_face_ids=True)
        result = visible_faces_in_polygon(ids, [[6, 6], [7, 6], [7, 7], [6, 7]])
        self.assertEqual(result['faceIds'], [])

    def test_invalid_selection_is_refused(self):
        _, ids = raster_mesh(**self.fixture(), return_face_ids=True)
        for polygon in ([[1, 1], [2, 2]], [[0, 0], [9, 0], [0, 1]],
                        [[0, 0], [1, 1], [2, 2]],
                        [[0, 0], [float('nan'), 0], [0, 1]]):
            with self.subTest(polygon=polygon), self.assertRaises(ValueError):
                visible_faces_in_polygon(ids, polygon)
        with self.assertRaises(ValueError):
            visible_faces_in_polygon(ids.astype(float), [[0, 0], [1, 0], [0, 1]])


if __name__ == '__main__':
    unittest.main()
