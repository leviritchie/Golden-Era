import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from joint_refit import REFIT_SCHEMA, refit_joint_proxies, validate_refit_proxies


def _bar_fixture(offset=0.5):
    cluster_a = np.array([[1., 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0]])
    cluster_b = cluster_a + np.array([10., 0, 0])
    vertices = np.vstack([cluster_a, cluster_b])
    weights = np.zeros((8, 2))
    weights[:4, 0] = 1.0
    weights[4:, 1] = 1.0
    names = np.array(["boneA", "boneB"])
    heads = np.array([[-1. + offset, 0, 0], [9., 0, 0]])
    tails = np.array([[1. + offset, 0, 0], [11., 0, 0]])
    return vertices, weights, names, heads, tails


class JointRefitTests(unittest.TestCase):
    def test_offset_bone_reseats_rigidly(self):
        vertices, weights, names, heads, tails = _bar_fixture()
        new_heads, new_tails, report = refit_joint_proxies(
            vertices, weights, names, heads, tails, marker_tokens=("ZZZ",))
        self.assertTrue(np.allclose(new_heads[0], [-1., 0, 0]))
        self.assertTrue(np.allclose(new_tails[0], [1., 0, 0]))
        self.assertTrue(np.allclose(new_heads[0] - heads[0], new_tails[0] - tails[0]))
        self.assertTrue(np.allclose(new_heads[1], heads[1]))
        self.assertTrue(np.allclose(report["globalShift"], [-0.25, 0, 0]))
        entry = {bone["name"]: bone for bone in report["bones"]}
        self.assertTrue(entry["boneA"]["moved"])
        self.assertEqual(entry["boneA"]["reason"], "fitted")
        self.assertTrue(np.allclose(entry["boneA"]["localShift"], [-0.25, 0, 0]))
        self.assertFalse(entry["boneB"]["moved"])
        self.assertEqual(entry["boneB"]["reason"], "already_seated")
        self.assertEqual(report["schema"], REFIT_SCHEMA)
        self.assertEqual(report["movedBones"], 1)

    def test_whole_skeleton_shift_absorbed_globally(self):
        vertices, weights, names, heads, tails = _bar_fixture(offset=0.0)
        drift = np.array([0.4, 0, 0])
        new_heads, new_tails, report = refit_joint_proxies(
            vertices, weights, names, heads + drift, tails + drift, marker_tokens=("ZZZ",))
        self.assertTrue(np.allclose(report["globalShift"], [-0.4, 0, 0]))
        self.assertTrue(np.allclose(new_heads, heads))
        self.assertTrue(np.allclose(new_tails, tails))
        for bone in report["bones"]:
            self.assertEqual(bone["reason"], "fitted")
            self.assertTrue(np.allclose(bone["localShift"], [0, 0, 0], atol=1e-9))

    def test_cap_markers_and_unowned_stay_put(self):
        vertices, weights, names, heads, tails = _bar_fixture(offset=6.0)
        big_names = np.array(["boneA", "boneB", "Toe_End", "ghost"])
        big_weights = np.column_stack([weights, np.zeros(8), np.zeros(8)])
        big_weights[4:, 2] = 1.0
        big_heads = np.vstack([heads, [[0., 5, 0], [0, 0, 0]]])
        big_tails = np.vstack([tails, [[0., 5, 0], [0, 0, 0]]])
        new_heads, new_tails, report = refit_joint_proxies(
            vertices, big_weights, big_names, big_heads, big_tails)
        entry = {bone["name"]: bone for bone in report["bones"]}
        self.assertEqual(entry["boneA"]["reason"], "local_clamped")
        self.assertTrue(entry["boneA"]["moved"])
        budget = 0.15 * float(np.linalg.norm(vertices.max(0) - vertices.min(0)))
        self.assertAlmostEqual(float(new_heads[0, 0] - big_heads[0, 0]), -4.0 - budget, places=3)
        self.assertEqual(entry["Toe_End"]["reason"], "marker_skipped")
        self.assertTrue(np.array_equal(new_heads[2], big_heads[2]))
        self.assertEqual(entry["ghost"]["reason"], "unowned")
        self.assertTrue(np.array_equal(new_heads[3], big_heads[3]))
        self.assertEqual(report["markerBonesSkipped"], ["Toe_End"])

    def test_deterministic_and_scale_invariant(self):
        first = refit_joint_proxies(*_bar_fixture(), marker_tokens=("ZZZ",))
        second = refit_joint_proxies(*_bar_fixture(), marker_tokens=("ZZZ",))
        self.assertTrue(np.array_equal(first[0], second[0]))
        self.assertEqual(first[2], second[2])
        vertices, weights, names, heads, tails = _bar_fixture()
        scaled = refit_joint_proxies(
            vertices * 3, weights, names, heads * 3, tails * 3, marker_tokens=("ZZZ",))
        self.assertTrue(np.allclose(scaled[0], first[0] * 3))
        self.assertEqual(
            [bone["reason"] for bone in scaled[2]["bones"]],
            [bone["reason"] for bone in first[2]["bones"]])

    def test_validator_accepts_good_output(self):
        vertices, weights, names, heads, tails = _bar_fixture()
        new_heads, new_tails, report = refit_joint_proxies(
            vertices, weights, names, heads, tails, marker_tokens=("ZZZ",))
        verdict = validate_refit_proxies(
            new_heads, new_tails, report, vertices, names, heads, tails,
            marker_tokens=("ZZZ",))
        self.assertTrue(verdict["ok"], verdict["errors"])

    def test_validator_rejects_tampering(self):
        vertices, weights, names, heads, tails = _bar_fixture()
        new_heads, new_tails, report = refit_joint_proxies(
            vertices, weights, names, heads, tails, marker_tokens=("ZZZ",))
        moved_marker = new_heads.copy()
        moved_marker[1] += 1.0
        verdict = validate_refit_proxies(
            moved_marker, new_tails, report, vertices, names, heads, tails,
            marker_tokens=("ZZZ",))
        self.assertFalse(verdict["ok"])
        shifted_mesh = vertices.copy()
        shifted_mesh[0, 0] += 0.001
        verdict = validate_refit_proxies(
            new_heads, new_tails, report, shifted_mesh, names, heads, tails,
            marker_tokens=("ZZZ",))
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("checksum" in error for error in verdict["errors"]))
        verdict = validate_refit_proxies(
            new_heads, new_tails, report, vertices, names, heads, tails,
            max_shift_frac=0.5, marker_tokens=("ZZZ",))
        self.assertFalse(verdict["ok"])
        stretched = new_heads.copy()
        stretched[0, 0] += 0.001
        verdict = validate_refit_proxies(
            stretched, new_tails, report, vertices, names, heads, tails,
            marker_tokens=("ZZZ",))
        self.assertFalse(verdict["ok"])

    def test_malformed_inputs_fail_closed(self):
        vertices, weights, names, heads, tails = _bar_fixture()
        with self.assertRaises(ValueError):
            refit_joint_proxies(vertices, weights, names, heads[:1], tails, marker_tokens=("ZZZ",))
        bad_mass = weights.copy()
        bad_mass[0, 0] = -1.0
        with self.assertRaises(ValueError):
            refit_joint_proxies(vertices, bad_mass, names, heads, tails, marker_tokens=("ZZZ",))
        bad_names = np.array(["boneA", "boneA"])
        with self.assertRaises(ValueError):
            refit_joint_proxies(vertices, weights, bad_names, heads, tails, marker_tokens=("ZZZ",))
        with self.assertRaises(ValueError):
            refit_joint_proxies(vertices, weights, names, heads, tails,
                                max_shift_frac=0.0, marker_tokens=("ZZZ",))
        with self.assertRaises(ValueError):
            refit_joint_proxies(vertices, weights, names, heads, tails, marker_tokens=())
        with self.assertRaises(ValueError):
            refit_joint_proxies(np.empty((0, 3)), np.empty((0, 2)), names, heads, tails,
                                marker_tokens=("ZZZ",))


if __name__ == "__main__":
    unittest.main()
