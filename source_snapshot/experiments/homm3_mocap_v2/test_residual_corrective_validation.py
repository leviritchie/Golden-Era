import sys
import unittest
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import validate_pose_corrective_artifact as validator


class _Arrays:
    def __init__(self, candidate):
        self.candidate = candidate

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __contains__(self, key):
        return key == "candidate"

    def __getitem__(self, key):
        if key != "candidate":
            raise KeyError(key)
        return self.candidate


class ResidualCorrectiveValidationTests(unittest.TestCase):
    def _warm(self, *, feasible=True):
        candidate = np.arange(12, dtype=np.float32).reshape(2, 2, 3)
        warm = {
            "reportPath": "warm/report.json", "reportSha256": "report",
            "statePath": "warm/state.pt", "stateSha256": "state",
            "meshesPath": "warm/meshes.npz", "meshesSha256": "meshes",
            "candidateSha256": validator._array_sha(candidate),
            "warmStartMetrics": {"image": 2., "surface": 1., "idle": .5},
            "selectedMetrics": {"image": 1. if feasible else 2., "surface": .9, "idle": .4},
            "feasibleImprovement": feasible,
        }
        return warm, candidate

    def _report(self, warm):
        return {"asset": "bird", "baseFit": None, "fixedMotionHashes": {"g00": "motion"},
                "warmStart": warm, "checkpointPolicy": "image_best_without_surface_or_idle_regression",
                "warmStartMetrics": warm["warmStartMetrics"], "selectedMetrics": warm["selectedMetrics"],
                "feasibleImprovement": warm["feasibleImprovement"]}

    def test_legacy_report_without_warm_checkpoint_remains_valid(self):
        self.assertIsNone(validator._validate_warm_checkpoint({}))

    def test_checkpoint_hashes_and_metrics_are_verified(self):
        warm, candidate = self._warm()
        report = self._report(warm)

        def digest(path):
            return {"report.json": "report", "state.pt": "state", "meshes.npz": "meshes"}[Path(path).name]

        with patch.object(Path, "is_file", return_value=True), \
             patch.object(Path, "read_text", return_value=json.dumps({"asset": "bird", "baseFit": None, "fixedMotionHashes": {"g00": "motion"}})), \
             patch.object(validator, "_sha", side_effect=digest), \
             patch("validate_pose_corrective_artifact.np.load", return_value=_Arrays(candidate)):
            result = validator._validate_warm_checkpoint(report)
        self.assertTrue(result["feasibleImprovement"])
        self.assertEqual(result["checkpointPolicy"], "image_best_without_surface_or_idle_regression")

    def test_checkpoint_rejects_policy_regression_and_inconsistent_flag(self):
        warm, _ = self._warm()
        warm["selectedMetrics"]["surface"] = 2.
        def digest(path):
            return {"report.json": "report", "state.pt": "state", "meshes.npz": "meshes"}[Path(path).name]
        with patch.object(Path, "is_file", return_value=True), \
             patch.object(Path, "read_text", return_value=json.dumps({"asset": "bird", "baseFit": None, "fixedMotionHashes": {"g00": "motion"}})), \
             patch.object(validator, "_sha", side_effect=digest), \
             patch("validate_pose_corrective_artifact.np.load", return_value=_Arrays(np.arange(12, dtype=np.float32).reshape(2, 2, 3))):
            with self.assertRaisesRegex(ValueError, "regressed"):
                validator._validate_warm_checkpoint(self._report(warm))
        warm, _ = self._warm()
        warm["feasibleImprovement"] = False
        with patch.object(Path, "is_file", return_value=True), \
             patch.object(Path, "read_text", return_value=json.dumps({"asset": "bird", "baseFit": None, "fixedMotionHashes": {"g00": "motion"}})), \
             patch.object(validator, "_sha", side_effect=digest), \
             patch("validate_pose_corrective_artifact.np.load", return_value=_Arrays(np.arange(12, dtype=np.float32).reshape(2, 2, 3))):
            with self.assertRaisesRegex(ValueError, "flag"):
                validator._validate_warm_checkpoint(self._report(warm))


if __name__ == "__main__":
    unittest.main()
