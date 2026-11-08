import json
import shutil
import uuid
import unittest
from pathlib import Path

from audit_faction_fit_status import audit


def _cleanup(root: Path) -> None:
    resolved = root.resolve()
    allowed = (Path("artifacts").resolve())
    if resolved.parent != allowed or not resolved.name.startswith("_audit_test_"):
        raise AssertionError(f"refusing to remove unexpected test path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


class AuditFactionFitStatusTests(unittest.TestCase):
    def test_missing_fit_fails(self):
        root = Path("artifacts") / ("_audit_test_" + uuid.uuid4().hex)
        try:
            (root / "experiments/homm3_mocap_v2").mkdir(parents=True)
            manifest = root / "experiments/homm3_mocap_v2/status.json"
            manifest.write_text(json.dumps({"units": [{"name": "A", "sid": "a", "fit": "missing.json"}]}))
            with self.assertRaises(FileNotFoundError): audit(manifest, root / "out.json", path_root=root)
        finally:
            _cleanup(root)

    def test_evidence_asset_mismatch_fails(self):
        root = Path("artifacts") / ("_audit_test_" + uuid.uuid4().hex)
        try:
            (root / "experiments/homm3_mocap_v2").mkdir(parents=True)
            fit = root / "fit.json"; fit.write_text(json.dumps({"asset": "wrong", "qualityGate": {}}))
            manifest = root / "experiments/homm3_mocap_v2/status.json"
            manifest.write_text(json.dumps({"units": [{"name": "A", "sid": "a", "fit": "fit.json", "evidenceAsset": "expected"}]}))
            with self.assertRaisesRegex(ValueError, "does not match evidenceAsset"):
                audit(manifest, root / "out.json", path_root=root)
        finally:
            _cleanup(root)

    def test_without_evidence_asset_records_mapping_only(self):
        root = Path("artifacts") / ("_audit_test_" + uuid.uuid4().hex)
        try:
            (root / "experiments/homm3_mocap_v2").mkdir(parents=True)
            fit = root / "fit.json"; fit.write_text(json.dumps({"asset": "report_asset", "qualityGate": {}, "cases": {"idle": {}}}))
            manifest = root / "experiments/homm3_mocap_v2/status.json"
            manifest.write_text(json.dumps({"units": [{"name": "A", "sid": "a", "fit": "fit.json"}]}))
            result = audit(manifest, root / "out.json", path_root=root)
            self.assertEqual(result["units"][0]["sourceSidMapping"]["matchedBy"], "recorded-only")
            self.assertEqual(result["units"][0]["acceptance"], "unknown")
        finally:
            _cleanup(root)

    def test_explicit_root_allows_manifest_outside_default_root(self):
        root = Path("artifacts") / ("_audit_test_" + uuid.uuid4().hex)
        try:
            manifest_dir = root / "arbitrary_manifest_location"
            manifest_dir.mkdir(parents=True)
            (root / "fit.json").write_text(json.dumps({"asset": "expected", "qualityGate": {"restShape": True}}))
            manifest = manifest_dir / "status.json"
            manifest.write_text(json.dumps({"units": [{"name": "A", "sid": "a", "fit": "fit.json", "evidenceAsset": "expected"}]}))
            result = audit(manifest, root / "out.json", path_root=root)
            self.assertEqual(result["fitReportCount"], 1)
        finally:
            _cleanup(root)

    def test_duplicate_sid_fails(self):
        root = Path("artifacts") / ("_audit_test_" + uuid.uuid4().hex)
        try:
            root.mkdir(parents=True)
            manifest = root / "status.json"
            manifest.write_text(json.dumps({"units": [
                {"name": "A", "sid": "same"},
                {"name": "B", "sid": "same"},
            ]}))
            with self.assertRaisesRegex(ValueError, "duplicate sids"):
                audit(manifest, root / "out.json", path_root=root)
        finally:
            _cleanup(root)

    def test_non_boolean_quality_gate_fails(self):
        root = Path("artifacts") / ("_audit_test_" + uuid.uuid4().hex)
        try:
            root.mkdir(parents=True)
            fit = root / "fit.json"
            fit.write_text(json.dumps({"asset": "expected", "qualityGate": {"restShape": "true"}}))
            manifest = root / "status.json"
            manifest.write_text(json.dumps({"units": [{"name": "A", "sid": "a", "fit": "fit.json", "evidenceAsset": "expected"}]}))
            with self.assertRaisesRegex(ValueError, "qualityGate values must be boolean"):
                audit(manifest, root / "out.json", path_root=root)
        finally:
            _cleanup(root)

    def test_malformed_report_root_fails(self):
        root = Path("artifacts") / ("_audit_test_" + uuid.uuid4().hex)
        try:
            root.mkdir(parents=True)
            fit = root / "fit.json"
            fit.write_text(json.dumps([{"asset": "expected"}]))
            manifest = root / "status.json"
            manifest.write_text(json.dumps({"units": [{"name": "A", "sid": "a", "fit": "fit.json"}]}))
            with self.assertRaisesRegex(ValueError, "fit report root must be an object"):
                audit(manifest, root / "out.json", path_root=root)
        finally:
            _cleanup(root)

    def test_existing_output_refuses_overwrite(self):
        root = Path("artifacts") / ("_audit_test_" + uuid.uuid4().hex)
        try:
            root.mkdir(parents=True)
            manifest = root / "status.json"
            manifest.write_text(json.dumps({"units": [{"name": "A", "sid": "a"}]}))
            output = root / "out.json"
            output.write_text("original\n")
            with self.assertRaises(FileExistsError):
                audit(manifest, output, path_root=root)
            self.assertEqual(output.read_text(), "original\n")
        finally:
            _cleanup(root)


if __name__ == "__main__": unittest.main()
