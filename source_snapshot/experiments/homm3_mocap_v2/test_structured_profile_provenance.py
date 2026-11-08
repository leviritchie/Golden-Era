"""Registered profile producer/consumer boundary tests; no inference or rendering."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import structured_profiles as profiles
import capture_skin_corpus as capture
import run_shape_preserved as preparation
import register_skin_corpus_asset as registration
import prepare_mapped_skin_asset as mapped


class StructuredProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.pin = {"structuredProfileSha256": "a" * 64}
        p = patch.object(profiles, "current_profile_pin", return_value=self.pin)
        p.start()
        self.addCleanup(p.stop)

    def test_each_registered_input_requires_exact_pin(self):
        self.assertEqual(profiles.require_profile_pin("h3_test", self.pin, dict(self.pin)), self.pin)
        for bad in ({}, {"structuredProfileSha256": "b" * 64}):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "regenerate"):
                profiles.require_profile_pin("h3_test", self.pin, bad)

    def test_builtin_without_pin_unchanged_but_unregistered_pin_rejected(self):
        with patch.object(profiles, "current_profile_pin", return_value={}):
            self.assertEqual(profiles.require_profile_pin("h3_builtin", {}, {}), {})
            with self.assertRaisesRegex(ValueError, "unregistered"):
                profiles.require_profile_pin("h3_builtin", self.pin)

    def test_capture_rejects_unpinned_manifest_before_model_or_output(self):
        with patch.object(Path, "read_text", return_value=json.dumps({"unit": "h3_test"})), \
                patch.object(capture, "validate_source_identity") as validate_source:
            with self.assertRaisesRegex(ValueError, "regenerate"):
                capture.capture_corpus(Path("manifest.json"), Path("no-output"))
        validate_source.assert_not_called()

    def test_frozen_preparation_rejects_missing_pin_before_loading_mesh(self):
        with patch.object(Path, "is_file", return_value=True), \
                patch.object(Path, "read_text", return_value="{}"), \
                patch.object(preparation, "verify_original_untouched") as verify:
            with self.assertRaisesRegex(ValueError, "regenerate"):
                preparation._load_frozen_prep("h3_test")
        verify.assert_not_called()

    def test_registration_rejects_different_manifest_profile_before_gpu(self):
        corpus = {"unit": "h3_test", "manifest": "manifest.json", "manifestSha256": "hash", **self.pin}
        with patch.object(Path, "exists", return_value=False), \
                patch.object(Path, "read_text", side_effect=[json.dumps(corpus), "{}"]), \
                patch.object(registration, "sha256_file", return_value="hash"), \
                patch.object(registration, "_load_frozen_prep") as load:
            with self.assertRaisesRegex(ValueError, "regenerate"):
                registration.register("h3_test", Path("corpus.json"), Path("output"))
        load.assert_not_called()

    def test_preparation_rejects_profile_changed_after_load_before_any_work(self):
        old = {"structuredProfileSha256": "b" * 64}
        with patch.object(mapped.shared, "get_profile", return_value=old), \
                patch.object(mapped.shared, "load_target_asset") as load, \
                patch.object(mapped.shared, "_write_json") as write:
            with self.assertRaisesRegex(ValueError, "regenerate"):
                mapped.prepare("h3_test", "not-generated")
        load.assert_not_called()
        write.assert_not_called()

    def test_existing_report_pin_failure_never_rewrites_freeze(self):
        freeze = {**self.pin, "preparationDir": "old-preparation", "skinInitialization": "source_joint_map"}
        with patch.object(mapped.shared, "get_profile", return_value=dict(self.pin)), \
                patch.object(Path, "is_file", return_value=True), \
                patch.object(Path, "read_text", side_effect=[json.dumps(freeze), "{}"]), \
                patch.object(mapped.shared, "_write_json") as write:
            with self.assertRaisesRegex(ValueError, "regenerate"):
                mapped.validate_and_pin_existing("h3_test")
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
