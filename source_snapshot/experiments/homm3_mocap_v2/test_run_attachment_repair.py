import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import uuid

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_attachment_repair as runner
from attachment_repair import consolidate_redundant_owner, split_attachment


class RepairReadbackTests(unittest.TestCase):
    def setUp(self):
        self.root = runner.ROOT / "artifacts" / "attachment_repair_test_fixtures" / str(uuid.uuid4())
        self.root.mkdir(parents=True)
        self.mask_dir = self.root / "mask"
        self.mask_dir.mkdir()
        self.asset = "synthetic_attachment"
        self.skin = {
            "vertices": np.array([[0., 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]),
            "triangles": np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64),
            "uvs": np.array([[0., 0], [1, 0], [1, 1], [0, 1]]),
            "albedo": np.ones((4, 2, 3), dtype=np.uint8),
            "weights": np.array([[1., 0], [.7, .3], [.2, .8], [0., 1.]]),
            "names": np.array(["body", "prop"]),
            "parents": np.array([-1, 0], dtype=np.int64),
            "inverseBind": np.eye(4)[None].repeat(2, axis=0),
        }
        self.worlds = np.tile(np.eye(4), (2, 2, 1, 1))
        self.worlds[1, :, 0, 3] = 2
        self.motions = {"clip": {"jointWorld": self.worlds}}
        self.provenance = {"fit": "synthetic", "version": 1}
        self.prepared = {"prepared": True}
        self.fit_dir = self.root / "fit"
        self.fit_dir.mkdir()
        baseline = self.fit_dir / "baseline"
        baseline.mkdir()
        (baseline / "camera.json").write_text("{}", encoding="utf-8")
        self.fit_report = {"inputs": {"researchSkin": "prepared-skin", "corpusSha256": "corpus"},
                           "baselineDirectory": str(baseline), "motionCompletion": None}
        self.recipe_path = self.root / "recipe.json"
        self.mask = self.mask_dir / "face_proposal.npz"
        self.producer = self.mask_dir / "report.json"
        np.savez(self.mask, propTriangles=np.array([1], dtype=np.int64))
        mask_hash = runner.sha256_file(self.mask)
        producer_body = {"asset": self.asset, "researchSkinSha256": "prepared-skin", "maskSha256": mask_hash}
        self.producer.write_text(json.dumps(producer_body), encoding="utf-8")
        recipe = {"schema": "attachment-repair-recipe-v1", "asset": self.asset,
                  "preparedSkinSha256": "prepared-skin", "maskDirectory": str(self.mask_dir.resolve()),
                  "maskReportSha256": runner.sha256_file(self.producer), "maskSha256": mask_hash,
                  "attachmentType": "rigid_held_part", "maskRefinement": "none",
                  "consolidateRedundantOwner": True, "owner": "prop"}
        self.recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
        body, self.consolidation = consolidate_redundant_owner(self.skin, self.worlds, "prop")
        self.expected, self.topology = split_attachment(body, np.array([1], dtype=np.int64), "prop")
        self.output = self.root / "output"
        self.output.mkdir()
        np.savez(self.output / "repaired_skin.npz", **self.expected)
        self.report_path = self.output / "report.json"
        report = {"schema": "attachment-repair-result-v1", "asset": self.asset,
                  "fitProvenance": self.provenance, "recipePath": str(self.recipe_path.resolve()),
                  "recipeSha256": runner.sha256_file(self.recipe_path), "motionCompletion": None,
                  "topology": self.topology, "bodyOwnershipConsolidation": self.consolidation,
                  "candidateSha256": runner.sha256_file(self.output / "repaired_skin.npz"),
                  "cameraSha256": runner.sha256_file(baseline / "camera.json"),
                  "cases": {"clip": {"fixedMotionSha256": runner.digest(self.worlds)}}}
        self.report_path.write_text(json.dumps(report), encoding="utf-8")
        self.patcher = patch.object(runner, "_load_inputs", return_value=(
            self.fit_report, None, None, self.prepared, self.skin, None, self.motions, {}, self.provenance))
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_valid_readback_returns_serialized_skin(self):
        report, original, repaired, motions, selected = runner.load_repair(self.report_path, self.asset, self.fit_dir)
        self.assertEqual(report["asset"], self.asset)
        self.assertTrue(np.array_equal(repaired["vertices"], self.expected["vertices"]))
        self.assertTrue(np.array_equal(repaired["weights"], self.expected["weights"]))
        self.assertEqual(selected.tolist(), [1])

    def test_provenance_and_serialization_drifts_fail_closed(self):
        report = json.loads(self.report_path.read_text())
        report["candidateSha256"] = "wrong"
        self.report_path.write_text(json.dumps(report))
        with self.assertRaises(ValueError): runner.load_repair(self.report_path, self.asset, self.fit_dir)
        report["candidateSha256"] = runner.sha256_file(self.output / "repaired_skin.npz")
        report["recipeSha256"] = "wrong"
        self.report_path.write_text(json.dumps(report))
        with self.assertRaises(ValueError): runner.load_repair(self.report_path, self.asset, self.fit_dir)

    def test_fixed_motion_and_reconstructed_operation_drifts_fail(self):
        report = json.loads(self.report_path.read_text())
        report["recipeSha256"] = runner.sha256_file(self.recipe_path)
        report["cases"]["clip"]["fixedMotionSha256"] = "wrong"
        self.report_path.write_text(json.dumps(report))
        with self.assertRaises(ValueError): runner.load_repair(self.report_path, self.asset, self.fit_dir)
        report["cases"]["clip"]["fixedMotionSha256"] = runner.digest(self.worlds)
        altered = dict(self.expected)
        altered["weights"] = altered["weights"].copy()
        altered["weights"][0] = [0., 1.]
        np.savez(self.output / "repaired_skin.npz", **altered)
        report["candidateSha256"] = runner.sha256_file(self.output / "repaired_skin.npz")
        self.report_path.write_text(json.dumps(report))
        with self.assertRaises(ValueError): runner.load_repair(self.report_path, self.asset, self.fit_dir)

    def test_wrong_asset_and_mask_contract_fail(self):
        with self.assertRaises(ValueError): runner.load_repair(self.report_path, "wrong", self.fit_dir)
        recipe = json.loads(self.recipe_path.read_text())
        recipe["attachmentType"] = "soft"
        self.recipe_path.write_text(json.dumps(recipe))
        with self.assertRaises(ValueError): runner.load_repair(self.report_path, self.asset, self.fit_dir)

    def test_mask_refinement_policy_is_required_and_allowlisted(self):
        recipe = json.loads(self.recipe_path.read_text())
        del recipe["maskRefinement"]
        self.recipe_path.write_text(json.dumps(recipe))
        with self.assertRaises(ValueError): runner.load_repair(self.report_path, self.asset, self.fit_dir)
        recipe["maskRefinement"] = "invented_fallback"
        self.recipe_path.write_text(json.dumps(recipe))
        with self.assertRaises(ValueError): runner.load_repair(self.report_path, self.asset, self.fit_dir)

    def test_baseline_worlds_uses_validated_raw_reference_without_mutating_playback(self):
        completion_dir = self.root / "completion"
        completion_dir.mkdir()
        completion_report = completion_dir / "completion.json"
        artifact = completion_dir / "source_wrist_motion.npz"
        baseline = self.worlds.copy()
        baseline[:, :, 1, 3] = 7
        np.savez(artifact, clipKeys=np.array(["clip"]), clipOffsets=np.array([0, 2]),
                 jointWorld=self.worlds, baselineJointWorld=baseline)
        completion = {"reportPath": str(completion_report.resolve()),
                      "motionArtifactSha256": runner.sha256_file(artifact), "mappedClips": ["clip"]}
        completion_report.write_text("validated", encoding="utf-8")
        completion["reportSha256"] = runner.sha256_file(completion_report)
        before = self.motions["clip"]["jointWorld"].copy()
        actual = runner.baseline_worlds(self.motions, completion)
        self.assertTrue(np.array_equal(actual, baseline))
        self.assertTrue(np.array_equal(self.motions["clip"]["jointWorld"], before))

    def test_baseline_worlds_rejects_hash_and_clip_inventory_drift(self):
        completion_dir = self.root / "completion_drift"
        completion_dir.mkdir()
        completion_report = completion_dir / "completion.json"
        artifact = completion_dir / "source_wrist_motion.npz"
        np.savez(artifact, clipKeys=np.array(["clip"]), clipOffsets=np.array([0, 2]),
                 jointWorld=self.worlds, baselineJointWorld=self.worlds)
        completion_report.write_text("validated", encoding="utf-8")
        base = {"reportPath": str(completion_report.resolve()),
                "reportSha256": runner.sha256_file(completion_report),
                "motionArtifactSha256": runner.sha256_file(artifact), "mappedClips": ["clip"]}
        bad_report = dict(base, reportSha256="wrong")
        with self.assertRaises(ValueError): runner.baseline_worlds(self.motions, bad_report)
        bad_artifact = dict(base, motionArtifactSha256="wrong")
        with self.assertRaises(ValueError): runner.baseline_worlds(self.motions, bad_artifact)
        bad_clips = dict(base, mappedClips=["other"])
        with self.assertRaises(ValueError): runner.baseline_worlds(self.motions, bad_clips)
if __name__ == "__main__":
    unittest.main()
