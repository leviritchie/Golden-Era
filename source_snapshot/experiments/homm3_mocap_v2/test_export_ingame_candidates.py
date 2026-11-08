import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
try:
    from .export_ingame_candidates import _deform, _validate_selection, export_selection
except ImportError:
    from export_ingame_candidates import _deform, _validate_selection, export_selection

FIXTURE = Path("artifacts/homm3_mocap_v2/unittest_export_candidates")


def _selection(kind="baseline_glb"):
    return {
        "schema": "stronghold-current-mocap-ingame-test-selection-v1",
        "accepted": False,
        "disposition": "user_requested_ingame_test",
        "units": [{
            "gameSid": "h3_test", "labSid": "h3_test", "bundleName": "custom_units_h3_test",
            "assetId": "h3_test", "fitReport": "fit/report.json", "sourceReport": "fit/report.json",
            "sourceReportSha256": "0" * 64, "kind": kind, "qualityWarnings": [],
            "disposition": "user_requested_ingame_test",
        }],
    }


class ExportCandidateTests(unittest.TestCase):
    def test_selection_is_fail_closed_for_accepted_or_unknown_schema(self):
        value = _selection()
        _validate_selection(value)
        value["accepted"] = True
        with self.assertRaisesRegex(ValueError, "unaccepted"):
            _validate_selection(value)
        value = _selection()
        value["schema"] = "other"
        with self.assertRaisesRegex(ValueError, "schema"):
            _validate_selection(value)


    def test_deform_preserves_onehot_rigid_motion(self):
        vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float64)
        weights = np.eye(2, dtype=np.float64)
        worlds = np.repeat(np.eye(4, dtype=np.float64)[None, None], 4, axis=0).reshape(2, 2, 4, 4)
        worlds[1, 0, 0, 3] = 3.0
        inverse_bind = np.repeat(np.eye(4, dtype=np.float64)[None], 2, axis=0)
        result = _deform(vertices, weights, worlds, inverse_bind)
        self.assertTrue(np.array_equal(result[0], vertices))
        self.assertTrue(np.array_equal(result[1, 0], vertices[0] + [3.0, 0.0, 0.0]))
        self.assertTrue(np.array_equal(result[1, 1], vertices[1]))


    def test_export_refuses_existing_output_and_requires_saved_refit_contract(self):
        tmp_path = FIXTURE / "existing"
        tmp_path.mkdir(parents=True, exist_ok=True)
        path = tmp_path / "selection.json"
        path.write_text(json.dumps(_selection("saved_skin_refit")), encoding="utf-8")
        output = tmp_path / "out"
        output.mkdir(exist_ok=True)
        with self.assertRaises(FileExistsError):
            export_selection(path, output, repo_root=tmp_path)


    def test_export_selection_requires_source_hash_before_copy(self):
        tmp_path = FIXTURE / "hash"
        tmp_path.mkdir(parents=True, exist_ok=True)
        path = tmp_path / "selection.json"
        path.write_text(json.dumps(_selection()), encoding="utf-8")
        (tmp_path / "fit").mkdir(exist_ok=True)
        (tmp_path / "fit" / "report.json").write_text(json.dumps({"cases": {}}), encoding="utf-8")
        shutil.rmtree(tmp_path / "out", ignore_errors=True)
        with self.assertRaisesRegex(ValueError, "source report hash"):
            export_selection(path, tmp_path / "out", repo_root=tmp_path)


if __name__ == "__main__":
    unittest.main()
