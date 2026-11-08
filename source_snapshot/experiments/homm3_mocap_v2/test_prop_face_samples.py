import unittest
import numpy as np

from prop_face_samples import classify_prop_faces


def cam():
    return {"perPanelAutofit": False,
            "front": {"cameraPolicy": "shared_capture_space", "basisScreenRows": [[1, 0, 0], [0, -1, 0]], "pxPerWorld": 1, "screenOffsetPx": [100, 100]},
            "side": {"cameraPolicy": "shared_capture_space", "basisScreenRows": [[0, 0, 1], [0, -1, 0]], "pxPerWorld": 1, "screenOffsetPx": [100, 100]}}


def ann():
    return {"schema": 1, "prop": "rock", "viewPolygons": {"front": [[70, 70], [90, 70], [90, 90], [70, 90]], "side": [[70, 70], [90, 70], [90, 90], [70, 90]]}, "rgbMaxSpread": .12, "rgbMeanRange": [.18, .75]}


class PropFaceSampleTests(unittest.TestCase):
    def test_gray_interior_survives_red_vertex_texels(self):
        vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
        uv = np.array([[.1, .1], [.9, .1], [.1, .9]], float)
        image = np.full((10, 10, 4), 110, np.uint8)
        image[1, 1, :3] = [255, 0, 0]; image[1, 8, :3] = [255, 0, 0]; image[8, 1, :3] = [255, 0, 0]
        got = classify_prop_faces(vertices=vertices, triangles=np.array([[0, 1, 2]]), uvs=uv, albedo=image, cameras=cam(), annotation=ann())
        self.assertEqual(got["samplePassCounts"].tolist(), [7])

    def test_full_colored_face_rejected(self):
        image = np.zeros((10, 10, 4), np.uint8); image[..., :3] = [255, 0, 0]
        got = classify_prop_faces(vertices=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float), triangles=np.array([[0, 1, 2]]), uvs=np.array([[.1, .1], [.9, .1], [.1, .9]]), albedo=image, cameras=cam(), annotation=ann())
        self.assertEqual(got["faceIds"].size, 0)

    def test_outside_roi_rejected_and_inputs_unchanged(self):
        vertices = np.array([[20, 20, 0], [21, 20, 0], [20, 21, 0]], float); original = vertices.copy()
        uv = np.full((3, 2), .5); image = np.full((4, 4, 4), 100, np.uint8)
        got = classify_prop_faces(vertices=vertices, triangles=np.array([[0, 1, 2]]), uvs=uv, albedo=image, cameras=cam(), annotation=ann())
        self.assertEqual(got["faceIds"].size, 0); np.testing.assert_array_equal(vertices, original); np.testing.assert_array_equal(uv, np.full((3, 2), .5)); np.testing.assert_array_equal(image, np.full((4, 4, 4), 100, np.uint8))


if __name__ == "__main__": unittest.main()
