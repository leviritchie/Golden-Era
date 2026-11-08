import copy
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from audit_skin_region_clipping import audit


def fixture():
    original = {
        "vertices": np.asarray([[0., 0., 0.], [1., 0., 0.]]),
        "triangles": np.asarray([[0, 1, 1]], dtype=np.int64),
        "uvs": np.asarray([[0., 0.], [1., 0.]]),
        "albedo": np.zeros((1, 1, 4), dtype=np.uint8),
        "names": np.asarray(["A", "B"]),
        "regions": np.asarray(["arm", "arm"]),
        "weights": np.asarray([[1., 0.], [0., 1.]]),
        "parents": np.asarray([-1, 0]),
        "offsets": np.asarray([[0., 0., 0.], [0., 1., 0.]]),
        "captureOffsets": np.asarray([[0., 0., 0.], [0., 1., 0.]]),
        "inverseBind": np.repeat(np.eye(4)[None], 2, axis=0),
    }
    target = {key: value.copy() for key, value in original.items() if key in ("vertices", "triangles", "uvs", "albedo")}
    target.update({"sourceNames": np.asarray(["src_b", "src_a"]),
                  "sourceDenseWeights": np.asarray([[0., 1.], [.25, .75]])})
    profile = {"sourceJointMap": {"src_a": "A", "src_b": "B"},
               "regionJoints": {"arm": ("A",)}}
    return original, target, profile


class RegionClippingAuditTests(unittest.TestCase):
    def test_retains_cross_region_blend_without_hard_clipping(self):
        original, target, profile = fixture()
        snapshot = copy.deepcopy(original)
        result = audit(original, target, profile)
        np.testing.assert_allclose(result["skin"]["weights"], [[1., 0.], [.75, .25]])
        self.assertAlmostEqual(result["report"]["perRegion"]["arm"]["discardedMass"], .25)
        self.assertEqual(result["report"]["verticesWithCrossRegionMass"], 1)
        self.assertFalse(result["report"]["clippedReconstruction"]["matchesPreparedWeights"])
        self.assertGreater(result["report"]["clippedReconstruction"]["maxAbsDifferenceFromPrepared"], 0.)
        np.testing.assert_array_equal(original["weights"], snapshot["weights"])

    def test_mapping_order_is_explicit(self):
        original, target, profile = fixture()
        profile["regionJoints"] = {"arm": ("A", "B")}
        target["sourceDenseWeights"] = np.asarray([[1., 0.], [0., 1.]])
        result = audit(original, target, profile)
        np.testing.assert_allclose(result["skin"]["weights"], [[0., 1.], [1., 0.]])

    def test_rejects_geometry_and_incomplete_mapping(self):
        original, target, profile = fixture()
        target["vertices"] = target["vertices"].copy()
        target["vertices"][0, 0] = 2.
        with self.assertRaisesRegex(ValueError, "geometry"):
            audit(original, target, profile)
        original, target, profile = fixture()
        profile["sourceJointMap"] = {"src_a": "A"}
        with self.assertRaisesRegex(ValueError, "map every"):
            audit(original, target, profile)

    def test_rejects_rigid_attachments(self):
        original, target, profile = fixture()
        profile["rigidAttachments"] = ({"region": "weapon", "donorJoints": ("B",)},)
        with self.assertRaisesRegex(ValueError, "rigidAttachments"):
            audit(original, target, profile)

    def test_rejects_negative_source_or_prepared_weight(self):
        original, target, profile = fixture()
        target["sourceDenseWeights"] = target["sourceDenseWeights"].copy()
        target["sourceDenseWeights"][0, 0] = -1e-12
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            audit(original, target, profile)
        original, target, profile = fixture()
        original["weights"] = original["weights"].copy()
        original["weights"][0, 0] = -1e-12
        with self.assertRaisesRegex(ValueError, "prepared weights"):
            audit(original, target, profile)

    def test_candidate_preserves_all_nonweight_fields(self):
        original, target, profile = fixture()
        result = audit(original, target, profile)["skin"]
        for key in original:
            if key != "weights":
                np.testing.assert_array_equal(result[key], original[key])

    def test_zero_allowed_support_is_reported_without_invalid_clipped_row(self):
        original, target, profile = fixture()
        profile["regionJoints"] = {"arm": ("A",)}
        target["sourceDenseWeights"] = np.asarray([[1., 0.], [1., 0.]])
        result = audit(original, target, profile)
        self.assertEqual(result["report"]["noAllowedSupportVertices"], 2)
        self.assertIsNone(result["report"]["clippedReconstruction"])
        np.testing.assert_allclose(result["skin"]["weights"], [[0., 1.], [0., 1.]])

    def test_preserves_dense_more_than_eight_influences_for_diagnostic_only(self):
        count = 9
        original = {"vertices": np.zeros((1, 3)), "triangles": np.asarray([[0, 0, 0]]),
                    "uvs": np.zeros((1, 2)), "albedo": np.zeros((1, 1, 4), dtype=np.uint8),
                    "names": np.asarray([f"J{i}" for i in range(count)]), "regions": np.asarray(["body"]),
                    "weights": np.full((1, count), 1.0 / count)}
        target = {key: original[key].copy() for key in ("vertices", "triangles", "uvs", "albedo")}
        target["sourceNames"] = np.asarray([f"S{i}" for i in range(count)])
        target["sourceDenseWeights"] = np.full((1, count), 1.0 / count)
        profile = {"sourceJointMap": {f"S{i}": f"J{i}" for i in range(count)},
                   "regionJoints": {"body": tuple(original["names"])}}
        result = audit(original, target, profile)
        self.assertFalse(result["report"]["inputContract"]["export8Compatible"])
        self.assertEqual(np.count_nonzero(result["skin"]["weights"] > 1e-8), count)


if __name__ == "__main__":
    unittest.main()
