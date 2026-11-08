import unittest

import numpy as np

from propose_rigid_prop_mask import _annotation, color_gate, propose_mask, sample_albedo_uv


def camera():
    return {
        "perPanelAutofit": False,
        "front": {"cameraPolicy": "shared_capture_space", "basisScreenRows": [[1, 0, 0], [0, -1, 0]], "pxPerWorld": 1, "screenOffsetPx": [100, 100]},
        "side": {"cameraPolicy": "shared_capture_space", "basisScreenRows": [[0, 0, 1], [0, -1, 0]], "pxPerWorld": 1, "screenOffsetPx": [100, 100]},
    }


class RigidPropMaskTests(unittest.TestCase):
    def test_intersection_and_all_vertex_face_policy(self):
        vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [3, -4, 0]], dtype=float)
        triangles = np.array([[0, 1, 2], [0, 1, 3], [1, 3, 4]], dtype=np.int64)
        uvs = np.full((5, 2), .5)
        albedo = np.full((4, 4, 4), 100, dtype=np.uint8)
        ann = {"schema": 1, "asset": "x", "prop": "rock", "viewPolygons": {"front": [[70, 70], [79, 70], [79, 85], [70, 85]], "side": [[70, 70], [79, 70], [79, 85], [70, 85]]}, "rgbMaxSpread": .12, "rgbMeanRange": [.18, .75]}
        got = propose_mask(vertices=vertices, triangles=triangles, uvs=uvs, albedo=albedo, cameras=camera(), annotation=ann)
        np.testing.assert_array_equal(got["selectedVertices"], [0, 1, 2, 3])
        np.testing.assert_array_equal(got["propTriangles"], [0, 1])
        np.testing.assert_array_equal(got["boundaryTriangles"], [2])

    def test_color_rejects_spread_or_mean(self):
        vertices = np.zeros((4, 3))
        triangles = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
        uvs = np.array([[.125, .5], [.375, .5], [.625, .5], [.875, .5]])
        image = np.array([[[100,100,100], [200,60,60], [10,10,10], [250,250,250]]], dtype=np.uint8)
        ann = {"schema": 1, "prop": "rock", "viewPolygons": {v: [[0,0],[200,0],[200,200],[0,200]] for v in ("front","side")}, "rgbMaxSpread": .12, "rgbMeanRange": [.18,.75]}
        inputs = [vertices, triangles, uvs, image]
        copies = [x.copy() for x in inputs]
        result = propose_mask(vertices=vertices, triangles=triangles, uvs=uvs, albedo=image, cameras=camera(), annotation=ann)
        np.testing.assert_array_equal(result["selectedVertices"], [0])
        self.assertEqual(len(result["propTriangles"]), 0)
        np.testing.assert_array_equal(result["boundaryTriangles"], [0,1])
        for actual, expected in zip(inputs, copies):
            np.testing.assert_array_equal(actual, expected)

    def test_invalid_annotations_are_rejected(self):
        base = {"schema": 1, "prop": "rock", "viewPolygons": {"front": [[0, 0], [1, 0], [1, 1]], "side": [[0, 0], [1, 0], [1, 1]]}, "rgbMaxSpread": .12, "rgbMeanRange": [.18, .75]}
        for bad in ({**base, "schema": 2}, {**base, "prop": ""}, {**base, "viewPolygons": {"front": []}}, {**base, "rgbMeanRange": [.8, .2]}):
            with self.assertRaises(ValueError):
                _annotation(bad)

    def test_annotation_identity_is_pinned(self):
        base = {"schema": 1, "asset": "cyclops", "researchSkinSha256": "abc", "prop": "rock", "viewPolygons": {"front": [[0, 0], [1, 0], [1, 1]], "side": [[0, 0], [1, 0], [1, 1]]}, "rgbMaxSpread": .12, "rgbMeanRange": [.18, .75]}
        with self.assertRaises(ValueError):
            _annotation(base, asset="king")
        with self.assertRaises(ValueError):
            _annotation(base, asset="cyclops", research_hash="different")
        _annotation(base, asset="cyclops", research_hash="abc")

    def test_optional_ordered_channel_gate(self):
        ann = {"schema": 1, "prop": "club", "viewPolygons": {"front": [[0, 0], [1, 0], [1, 1]], "side": [[0, 0], [1, 0], [1, 1]]}, "rgbMaxSpread": 1, "rgbMeanRange": [0, 1], "channelOrder": [0, 1, 2], "channelMinGap": .015}
        _annotation(ann)
        got = color_gate(np.array([[.5, .4, .3], [.5, .49, .3], [.3, .4, .5]]), ann)
        np.testing.assert_array_equal(got, [True, False, False])
        for bad in ({**ann, "channelOrder": [0, 0, 2]}, {**ann, "channelMinGap": -1}, {**ann, "channelOrder": [0, 1, 2], "channelMinGap": None}):
            with self.assertRaises(ValueError):
                _annotation(bad)

    def test_noninteger_triangles_rejected(self):
        with self.assertRaises(ValueError):
            propose_mask(vertices=np.zeros((3, 3)), triangles=np.zeros((1, 3), dtype=float), uvs=np.zeros((3, 2)), albedo=np.zeros((2, 2, 4), dtype=np.uint8), cameras=camera(), annotation={"schema": 1, "prop": "rock", "viewPolygons": {"front": [[0, 0], [1, 0], [1, 1]], "side": [[0, 0], [1, 0], [1, 1]]}, "rgbMaxSpread": .12, "rgbMeanRange": [.18, .75]})


if __name__ == "__main__":
    unittest.main()
