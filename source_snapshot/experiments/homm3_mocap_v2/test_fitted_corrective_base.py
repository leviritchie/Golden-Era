import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fitted_corrective_base as fitted


class _LoadResult:
    def __init__(self, arrays):
        self.arrays = arrays

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    @property
    def files(self):
        return list(self.arrays)

    def __getitem__(self, key):
        return self.arrays[key]


class FittedCorrectiveBaseTests(unittest.TestCase):
    def setUp(self):
        self.prepared = {
            "vertices": np.zeros((3, 3), dtype=np.float64),
            "weights": np.array([[1., 0.], [0., 1.], [.5, .5]]),
            "names": np.array(["root", "tip"]),
            "parents": np.array([-1, 0], dtype=np.int64),
            "triangles": np.array([[0, 1, 2]], dtype=np.int64),
            "inverseBind": np.eye(4)[None].repeat(2, axis=0),
        }
        self.candidate = {
            "vertices": np.ones((3, 3), dtype=np.float32),
            "weights": np.array([[1., 0.], [0., 1.], [.25, .75]], dtype=np.float32),
            "names": np.array(["root", "tip"]),
            "parents": np.array([-1, 0], dtype=np.int64),
        }

    def test_array_validation_preserves_shapes_and_rejects_bad_weights(self):
        vertices, weights = fitted._validate_arrays(self.candidate, self.prepared)
        np.testing.assert_array_equal(vertices, self.candidate["vertices"])
        np.testing.assert_array_equal(weights, self.candidate["weights"])
        bad = dict(self.candidate, weights=np.array([[1., 0.], [0., 0.], [.5, .5]]))
        with self.assertRaisesRegex(ValueError, "normalized"):
            fitted._validate_arrays(bad, self.prepared)

    def test_loader_replaces_only_vertices_and_weights_with_pinned_provenance(self):
        report = {"asset": "bird", "inputs": {"researchSkin": "skin-hash", "corpus": "corpus.json", "corpusSha256": "corpus-hash"},
                  "cases": {"g00": {"fixedMotionSha256": "motion-hash"}},
                  "validationBeforeAllFrameRefit": {"g00": {"heldoutIndices": [1]}},
                  "stages": {"allFrames": [{"step": 1}]}}
        corpus = {"unit": "bird"}

        def read_text(path, *args, **kwargs):
            return json.dumps(report if str(path).endswith("report.json") else corpus)

        before = {key: np.array(value, copy=True) for key, value in self.prepared.items()}
        with patch.object(Path, "is_file", return_value=True), \
             patch.object(Path, "read_text", new=read_text), \
             patch.object(fitted, "_sha", side_effect=lambda path: "corpus-hash" if str(path).endswith("corpus.json") else "artifact-hash"), \
             patch("fitted_corrective_base.np.load", return_value=_LoadResult(self.candidate)):
            updated, provenance = fitted.load_fitted_base("fit", "bird", self.prepared,
                                                          {"g00": "motion-hash"}, "corpus-hash", "skin-hash")
        np.testing.assert_array_equal(updated["vertices"], self.candidate["vertices"])
        np.testing.assert_array_equal(updated["weights"], self.candidate["weights"])
        np.testing.assert_array_equal(updated["triangles"], self.prepared["triangles"])
        for key, value in self.prepared.items():
            np.testing.assert_array_equal(value, before[key])
        self.assertTrue(provenance["allFrameBaseFit"])
        self.assertEqual(provenance["replacedFields"], ["vertices", "weights"])

    def test_loader_rejects_motion_key_drift_and_skeleton_mismatch(self):
        report = {"asset": "bird", "inputs": {"researchSkin": "skin", "corpus": "corpus.json", "corpusSha256": "corpus"},
                  "cases": {"g00": {"fixedMotionSha256": "actual"}},
                  "validationBeforeAllFrameRefit": True, "stages": {"allFrames": []}}
        with self.assertRaisesRegex(ValueError, "motion"):
            with patch.object(Path, "is_file", return_value=True), \
                 patch.object(Path, "read_text", return_value=json.dumps({"unit": "bird"})), \
                 patch.object(fitted, "_sha", return_value="corpus"):
                fitted._require_report(report, "bird", "skin", {"g00": "different"}, "corpus")
        bad = dict(self.candidate, parents=np.array([-1, -1], dtype=np.int64))
        with self.assertRaisesRegex(ValueError, "parents"):
            fitted._validate_arrays(bad, self.prepared)

    def test_report_identity_and_unnormalized_weights_fail_closed(self):
        report = {"asset": "other", "inputs": {"researchSkin": "skin", "corpus": "corpus.json", "corpusSha256": "corpus"},
                  "cases": {"g00": {"fixedMotionSha256": "motion"}},
                  "validationBeforeAllFrameRefit": True, "stages": {"allFrames": []}}
        with self.assertRaisesRegex(ValueError, "asset"):
            fitted._require_report(report, "bird", "skin", {"g00": "motion"}, "corpus")
        bad = dict(self.candidate, weights=np.array([[1., 0.], [0., 1.], [.2, .2]], dtype=np.float32))
        with self.assertRaisesRegex(ValueError, "normalized"):
            fitted._validate_arrays(bad, self.prepared)


if __name__ == "__main__":
    unittest.main()
