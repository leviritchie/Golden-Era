import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skin_joint_anchors import build_anchors, evaluate_anchors


class SkinJointAnchorTests(unittest.TestCase):
    def setUp(self):
        self.skin = {
            "vertices": np.array([[0., 0., 0.], [1., 0., 0.], [2., 0., 0.],
                                  [0., .1, 0.], [1., .1, 0.], [2., .1, 0.]]),
            "triangles": np.array([[0, 1, 3], [1, 4, 3], [1, 2, 4], [2, 5, 4]], np.int64),
            "weights": np.tile([1., 0., 0.], (6, 1)),
            "names": np.array(["root", "mid", "tip"]),
            "parents": np.array([-1, 0, 1], np.int64),
            "inverseBind": np.array([
                np.eye(4),
                [[1., 0., 0., -1.], [0., 1., 0., 0.], [0., 0., 1., 0.], [0., 0., 0., 1.]],
                [[1., 0., 0., -2.], [0., 1., 0., 0.], [0., 0., 1., 0.], [0., 0., 0., 1.]],
            ]),
            "regions": np.array(["limb"] * 6),
        }
        self.profile = {"chains": ({"name": "limb", "kind": "polyline",
                                     "donor": ("root", "mid", "tip")},)}

    def test_build_uses_body_unique_points_and_json_values(self):
        prop = np.array([False, False, False, False, False, True])
        model = build_anchors(self.skin, prop, self.profile, ["limb"], max_points=2)
        self.assertEqual(model["schema"], "skin-joint-anchor-model-v1")
        for anchor in model["chains"]["limb"]["joints"].values():
            self.assertLessEqual(len(anchor["vertexIds"]), 2)
            if anchor["supported"]:
                self.assertTrue(np.all(np.asarray(anchor["coefficients"]) >= 0))
                self.assertAlmostEqual(sum(anchor["coefficients"]), 1.0)
        self.assertNotIn(5, model["chains"]["limb"]["joints"]["2"]["vertexIds"])

    def test_routed_label_is_effective_body_support_but_prop_is_not(self):
        skin = dict(self.skin, regions=np.array(["limb", "limb", "weapon", "weapon", "limb", "limb"]))
        routing = {"weapon": {"chain": "limb", "owner": "tip", "vertexCount": 2}}
        model = build_anchors(skin, np.array([False] * 5 + [True]), self.profile, ["limb"], routing)
        support = model["chains"]["limb"]["supportVertexCount"]
        self.assertEqual(support, 5)

    def test_unsupported_chain_is_reported_without_fallback(self):
        skin = dict(self.skin, regions=np.array(["other"] * 6))
        model = build_anchors(skin, np.zeros(6, bool), self.profile, ["limb"])
        self.assertFalse(model["chains"]["limb"]["supported"])
        self.assertTrue(all(not x["supported"] for x in model["chains"]["limb"]["joints"].values()))

    def test_evaluate_matches_fixed_joint_world_targets(self):
        model = build_anchors(self.skin, np.zeros(6, bool), self.profile, ["limb"])
        frames = 2
        world = np.tile(np.eye(4)[None, None], (frames, 3, 1, 1))
        world[:, 0, 0, 3] = [0., .25]
        world[:, 1, 0, 3] = [1., 1.25]
        world[:, 2, 0, 3] = [2., 2.25]
        posed = np.zeros((frames, 6, 3))
        posed[0] = self.skin["vertices"]
        posed[1] = self.skin["vertices"] + [.25, 0., 0.]
        report = evaluate_anchors(model, posed, world, {"clip": (0, frames)})
        self.assertEqual(report["clips"]["clip"]["mesh"]["anchorCount"], 6)
        self.assertLess(report["clips"]["clip"]["mesh"]["maxError"], 1e-5)
        self.assertIn("joints", report["clips"]["clip"]["mesh"])

    def test_bad_motion_shape_refuses(self):
        model = build_anchors(self.skin, np.zeros(6, bool), self.profile, ["limb"])
        with self.assertRaises(ValueError):
            evaluate_anchors(model, np.zeros((2, 6, 3)), np.eye(4)[None])

    def test_malformed_chain_and_limits_refuse(self):
        for kwargs in ({"max_points": True}, {"residual_fraction": np.nan}):
            with self.assertRaises(ValueError):
                build_anchors(self.skin, np.zeros(6, bool), self.profile, ["limb"], **kwargs)
        bad_profile = {"chains": ({"name": "limb", "kind": "polyline",
                                    "donor": ("root", "tip")},)}
        with self.assertRaises(ValueError):
            build_anchors(self.skin, np.zeros(6, bool), bad_profile, ["limb"])

    def test_empty_or_incomplete_clip_coverage_refuses(self):
        model = build_anchors(self.skin, np.zeros(6, bool), self.profile, ["limb"])
        world = np.tile(np.eye(4)[None, None], (2, 3, 1, 1))
        posed = np.tile(self.skin["vertices"][None], (2, 1, 1))
        for slices in ({"empty": (0, 0)}, {"partial": (0, 1)}, {"overlap": (0, 2), "also": (1, 2)}):
            with self.assertRaises(ValueError):
                evaluate_anchors(model, posed, world, slices)


if __name__ == "__main__":
    unittest.main()
