import json
import math
import shutil
import uuid
import unittest
from pathlib import Path
from unittest import mock

from experiments.homm3_mocap_v2.onboarding_ledger import finish, main, note, stage, start


class OnboardingLedgerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parent / (".ledger_test_" + uuid.uuid4().hex)
        self.root.mkdir()
        self.path = self.root / "ledger.json"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_explicit_start_and_end_to_end_are_wall_clock(self):
        start(str(self.path), "roc", "2026-09-06T20:24:00Z")
        stage(str(self.path), "capture pass", "capture", 2.5, now=1788726242.0)
        result = finish(str(self.path), now=1788726246.0)
        self.assertEqual(result["startUTC"], "2026-09-06T20:24:00Z")
        self.assertEqual(result["endToEndSeconds"], 6.0)
        self.assertEqual(result["stageSeconds"], 2.5)
        self.assertEqual(result["modelCost"], "unavailable")

    def test_all_categories_and_note_hash(self):
        start(str(self.path), "beholder", now=10)
        for category in ("auth", "preparation", "capture", "fit", "validation"):
            stage(str(self.path), category, category, 1, now=10)
        artifact = self.root / "artifact.bin"
        artifact.write_bytes(b"verified")
        record = note(str(self.path), "candidate retained", str(artifact))
        self.assertEqual(len(record["artifactSHA256"]), 64)
        self.assertEqual(len(json.loads(self.path.read_text())["stages"]), 5)

    def test_stage_keeps_reported_duration_without_inventing_interval(self):
        start(str(self.path), "roc", now=10)
        stage(str(self.path), "fit", "fit", 3.25, now=20)
        entry = json.loads(self.path.read_text())["stages"][0]
        self.assertEqual(entry["durationSeconds"], 3.25)
        self.assertEqual(entry["recordedTimestampSeconds"], 20)
        self.assertNotIn("startUTC", entry)
        self.assertNotIn("stopUTC", entry)

    def test_invalid_stage_duration_and_category(self):
        start(str(self.path), "roc", now=10)
        for value in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                stage(str(self.path), "bad", "fit", value, now=10)
        with self.assertRaises(ValueError):
            stage(str(self.path), "bad", "other", 1, now=10)

    def test_unsafe_unit_and_existing_output_fail_closed(self):
        with self.assertRaises(ValueError):
            start(str(self.path), "../roc", now=10)
        start(str(self.path), "roc", now=10)
        with self.assertRaises(FileExistsError):
            start(str(self.path), "roc", now=10)

    def test_artifact_must_be_verified_existing_file(self):
        start(str(self.path), "roc", now=10)
        with self.assertRaises(ValueError):
            note(str(self.path), "missing", str(self.root / "missing.bin"))
        with self.assertRaises(ValueError):
            note(str(self.path), "directory", str(self.root))

    def test_finished_ledger_cannot_be_reopened_or_extended(self):
        start(str(self.path), "roc", now=10)
        finish(str(self.path), now=11)
        with self.assertRaises(ValueError):
            stage(str(self.path), "late", "fit", 1, now=12)
        with self.assertRaises(ValueError):
            note(str(self.path), "late")
        with self.assertRaises(ValueError):
            finish(str(self.path), now=12)

    def test_cli_uses_explicit_started_at(self):
        self.assertEqual(main(["start", "--output", str(self.path), "--unit", "roc", "--started-at", "2026-09-06T20:24:00Z"]), 0)
        data = json.loads(self.path.read_text())
        self.assertEqual(data["startUTC"], "2026-09-06T20:24:00Z")

    def test_default_clock_is_injectable_with_mock_timestamp(self):
        with mock.patch("experiments.homm3_mocap_v2.onboarding_ledger.time.time", return_value=50.0):
            start(str(self.path), "roc")
        data = json.loads(self.path.read_text())
        self.assertEqual(data["startTimestampSeconds"], 50.0)


if __name__ == "__main__":
    unittest.main()
