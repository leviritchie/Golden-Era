"""Focused geometry regression tests; Archer data tests skip when the asset is absent.

Run: py -3 -m unittest discover -s tools/homm3_meshy_frame_pose -p test_mesh_rest_fit.py -v
Rotation means yaw: this fitter explicitly requires Y-up, not arbitrary 3D rotation.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from owned_rerig.mesh_rest_fit import _section_width, fit_mesh_rest


def yaw(degrees: float) -> np.ndarray:
    a = np.radians(degrees)
    return np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])


class SectionTests(unittest.TestCase):
    def test_width_is_envelope_difference_not_coordinate_difference(self):
        section = np.array([[2, 10], [4, 14], [6, 18], [8, 22]], dtype=float)
        expected = np.sum(np.quantile(section, .85, axis=0) - np.quantile(section, .15, axis=0))
        self.assertAlmostEqual(_section_width(section), expected)
        self.assertAlmostEqual(_section_width(section + [123, -70]), expected)
        self.assertGreater(_section_width(section), 0)

    def test_invalid_points(self):
        for points in (np.zeros((5, 3)), np.zeros((100, 2)), np.full((100, 3), np.nan)):
            with self.subTest(shape=points.shape), self.assertRaises(ValueError):
                fit_mesh_rest(points, np.zeros((0, 3)), [], [])


class ArcherFitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from owned_rerig.glb_io import load_mesh
        from preview_exact_reference_bind import load_delivered_skeleton

        root = Path(__file__).resolve().parents[2]
        base = root / "artifacts/meshy_downloads/meshy71_repair_candidates/h3_archer/t-pose"
        mesh_path = base / "mesh.glb"
        bind_path = base / "bind/owned_bind_h3_archer_t-pose.glb"
        if not mesh_path.is_file() or not bind_path.is_file():
            raise unittest.SkipTest("Local Archer mesh/reference fixtures are absent")
        cls.points = np.array(load_mesh(mesh_path).positions, dtype=float)
        cls.ref = load_delivered_skeleton(bind_path)
        cls.prior = np.asarray(cls.ref["heads"])
        cls.names, cls.parents = cls.ref["names"], cls.ref["parents"]
        cls.idx = {n: i for i, n in enumerate(cls.names)}
        cls.result = cls.fit(cls.points, cls.prior)

    @classmethod
    def fit(cls, points, prior):
        return fit_mesh_rest(positions=points, reference_heads=prior, parents=cls.parents, names=cls.names)

    def test_api_serializable_metadata_and_no_mutation(self):
        points, prior = self.points.copy(), self.prior.copy()
        result = self.fit(points, prior)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["heads"].shape, self.prior.shape)
        self.assertTrue(np.isfinite(result["heads"]).all())
        json.dumps({k: v for k, v in result.items() if k != "heads"}, allow_nan=False)
        np.testing.assert_array_equal(points, self.points)
        np.testing.assert_array_equal(prior, self.prior)

    def test_archer_front_and_side_landmarks(self):
        h, idx = self.result["heads"], self.idx
        # Broad observed-mesh regression bounds, not production fitting constants.
        # These specifically catch the old 46-degree yaw and chest-height hips.
        self.assertGreater(self.result["yawCorrectionDegrees"], 40)
        self.assertLess(self.result["yawCorrectionDegrees"], 52)
        for side, sign in (("Left", 1), ("Right", -1)):
            for part in ("Arm", "ForeArm", "Hand"):
                joint = h[idx[side + part]]
                self.assertTrue(0.40 < joint[1] < 0.53, (side, part, joint))
                self.assertLess(abs(joint[2]), .09, (side, part, joint))
                self.assertGreater(joint[0] * sign, .15)
            self.assertTrue(-.60 < h[idx[side + "Leg"], 1] < -.40)
            self.assertTrue(-.90 < h[idx[side + "Foot"], 1] < -.75)
            self.assertGreater(h[idx[side + "UpLeg"], 0] * sign, .08)
        self.assertTrue(-.18 < h[idx["Hips"], 1] < -.04)
        self.assertLess(abs(h[idx["Hips"], 2]), .08)
        self.assertLess(self.result["landmarksNormalized"]["crotchHeight"], .40)

    def test_scale_translation_exact_equivariance(self):
        scale, translation = 3.7, np.array([12, -4, 8])
        result = self.fit(self.points * scale + translation, self.prior * scale + translation)
        restored = (result["heads"] - translation) / scale
        np.testing.assert_allclose(restored, self.result["heads"], atol=1e-10)

    def test_combined_yaw_scale_translation_equivariance(self):
        # Voxelization happens in the fitted body frame, so rigid yaw changes
        # cannot perturb wrist-section selection or any other mesh landmark.
        limit = 1e-10 * self.result["meshHeight"]
        for angle, scale, offset in ((37, .2, [-5, 6, 13]), (-73, 2.3, [7, -9, 2]),
                                     (150, .8, [2, 3, -4])):
            with self.subTest(angle=angle, scale=scale):
                rotation, offset = yaw(angle), np.array(offset)
                result = self.fit(self.points @ rotation.T * scale + offset,
                                  self.prior @ rotation.T * scale + offset)
                restored = (result["heads"] - offset) @ rotation / scale
                errors = np.linalg.norm(restored - self.result["heads"], axis=1)
                self.assertLess(float(errors.max()), limit, self.names[int(errors.argmax())])

    def test_prior_absolute_pose_and_scale_do_not_move_fit(self):
        # Same topology and chain ratios, wildly different location and size.
        for rotation in (yaw(25), yaw(-20)):
            prior = self.prior @ rotation.T * 7.5 + [9, -14, 23]
            result = self.fit(self.points, prior)
            np.testing.assert_allclose(result["heads"], self.result["heads"], atol=1e-10)

    def test_export_duplicates_and_vertex_order_do_not_bias_fit(self):
        duplicated = np.concatenate([self.points, np.repeat(self.points[:1500], 5, axis=0)])
        np.random.default_rng(63).shuffle(duplicated)
        result = self.fit(duplicated, self.prior)
        np.testing.assert_allclose(result["heads"], self.result["heads"], atol=1e-10)

    def test_joint_permutation_and_namespace(self):
        permutation = np.random.default_rng(8).permutation(len(self.names))
        inverse = np.argsort(permutation)
        parents = [None if self.parents[i] is None else int(inverse[self.parents[i]]) for i in permutation]
        result = fit_mesh_rest(self.points, self.prior[permutation], parents,
                               ["mixamorig:" + self.names[i] for i in permutation])
        np.testing.assert_allclose(result["heads"][inverse], self.result["heads"], atol=1e-10)

    def test_incompatible_body_plan_not_silently_adapted(self):
        names = list(self.names)
        names[self.idx["LeftArm"]] = "LeftWing"
        with self.assertRaisesRegex(ValueError, "25-joint"):
            fit_mesh_rest(self.points, self.prior, self.parents, names)


if __name__ == "__main__":
    unittest.main()
