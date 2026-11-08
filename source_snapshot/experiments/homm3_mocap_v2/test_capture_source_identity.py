import hashlib
import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_skin_corpus import capture_corpus, validate_source_identity


class CaptureSourceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("artifacts/capture_source_identity_tests") / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.source = self.root / "02_00.png"
        self.source.write_bytes(b"authentic native idle")
        self.prepared = self.root / "g02_idle_000.png"
        self.prepared.write_bytes(b"prepared NN idle")
        self.identity = {"nativeIdleSha256": self.digest(self.source), "defName": "COGMAG.def"}

    def tearDown(self):
        shutil.rmtree(self.root)

    @staticmethod
    def digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def manifest(self, source=None, rows=None):
        source = source or self.source
        return {"unit": "h3_ogre_mage", "idle": str(self.prepared.resolve()),
                "sourceIdentity": self.identity,
                "frames": rows if rows is not None else [{"group": 2, "frame": 0,
                    "source": str(source.resolve()), "sourceSha256": self.digest(source),
                    "prepared": str(self.prepared.resolve()), "preparedSha256": self.digest(self.prepared)}]}

    def test_matching_native_idle_pin_is_accepted(self):
        with mock.patch("capture_skin_corpus.asset_entry", return_value={"sourceIdentity": self.identity}):
            validate_source_identity(self.manifest())

    def test_old_duplicate_source_is_rejected(self):
        duplicate = self.root / "old_cogre_02_00.png"
        duplicate.write_bytes(b"old duplicate source")
        rows = [{"group": 2, "frame": 0, "source": str(duplicate.resolve()),
                 "sourceSha256": self.digest(duplicate)}]
        rows[0]["prepared"] = str(self.prepared.resolve())
        rows[0]["preparedSha256"] = self.digest(self.prepared)
        with mock.patch("capture_skin_corpus.asset_entry", return_value={"sourceIdentity": self.identity}):
            with self.assertRaisesRegex(ValueError, "nativeIdleSha256"):
                validate_source_identity(self.manifest(rows=rows))

    def test_row_hash_mismatch_is_rejected_before_output_creation(self):
        manifest_path = self.root / "manifest.json"
        payload = self.manifest()
        payload["frames"][0]["sourceSha256"] = "0" * 64
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        output = self.root / "out"
        with mock.patch("capture_skin_corpus.asset_entry", return_value={"sourceIdentity": self.identity}):
            with self.assertRaisesRegex(ValueError, "does not match row.sourceSha256"):
                capture_corpus(manifest_path, output, device="cpu")
        self.assertFalse(output.exists())

    def test_current_corrected_ogre_mage_manifest_is_accepted(self):
        manifest = Path("artifacts/homm3_mocap_v2/skin_mesh_pilot/ogre_mage/corpus_corrected_v1/manifest.json")
        self.assertTrue(manifest.is_file())
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        identity = {"nativeIdleSha256": "20130e77d0435188ac99bf5dd458ce0ea22538b69a04973e91badc2085a0b42b", "defName": "COGMAG.def"}
        with mock.patch("capture_skin_corpus.asset_entry", return_value={"sourceIdentity": identity}):
            validate_source_identity(payload)

    def test_historical_wrong_ogre_mage_manifest_is_rejected(self):
        manifest = Path("artifacts/homm3_mocap_v2/skin_mesh_pilot/ogre_mage/corpus_v1/manifest.json")
        self.assertTrue(manifest.is_file())
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        identity = {"nativeIdleSha256": "20130e77d0435188ac99bf5dd458ce0ea22538b69a04973e91badc2085a0b42b", "defName": "COGMAG.def"}
        with mock.patch("capture_skin_corpus.asset_entry", return_value={"sourceIdentity": identity}):
            with self.assertRaisesRegex(ValueError, "nativeIdleSha256"):
                validate_source_identity(payload)

    def test_missing_provenance_is_rejected_when_pin_present(self):
        payload = self.manifest()
        del payload["frames"]
        with mock.patch("capture_skin_corpus.asset_entry", return_value={"sourceIdentity": self.identity}):
            with self.assertRaisesRegex(ValueError, "raw manifest.frames"):
                validate_source_identity(payload)

    def test_manifest_without_optional_identity_keeps_legacy_behavior(self):
        payload = self.manifest()
        del payload["sourceIdentity"]
        with mock.patch("capture_skin_corpus.asset_entry", return_value={}):
            validate_source_identity(payload)


if __name__ == "__main__":
    unittest.main()
