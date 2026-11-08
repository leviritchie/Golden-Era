import hashlib
import json
import shutil
import unittest
import uuid
from pathlib import Path

import numpy as np

from motion_completion import apply_motion_completion, restore_motion_completion


class MotionCompletionTests(unittest.TestCase):
    def setUp(self):
        self.base = (Path(__file__).resolve().parents[2] / "artifacts" / "homm3_mocap_v2" / "motion_completion_tests").resolve()
        self.root = self.base / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.frames = self.root / "frames"
        self.frames.mkdir()
        (self.frames / "idle.png").write_bytes(b"idle")
        (self.frames / "active.png").write_bytes(b"active")
        (self.root / "capture.npz").write_bytes(b"capture")
        self.corpus = self.root / "corpus.json"
        capture_sha = self._sha(self.root / "capture.npz")
        corpus = {"captures": [{"key": "g02_idle", "frames": [str((self.frames / "idle.png").resolve())], "captureSha256": capture_sha}, {"key": "clip", "frames": [str((self.frames / "idle.png").resolve()), str((self.frames / "active.png").resolve())], "captureSha256": capture_sha}]}
        self.corpus.write_text(json.dumps(corpus), encoding="utf-8")
        self.annotation = self.root / "annotation.json"
        self.annotation.write_text(json.dumps({"asset": "unit", "researchSkinSha256": "skin", "sourceCorpus": str(self.corpus.resolve()), "corpusSha256": self._sha(self.corpus), "captures": {"clip": {"captureSha256": capture_sha, "frameCount": 2, "frames": [{"localIndex": 0, "sourcePath": str((self.frames / "idle.png").resolve()), "sourceSha256": self._sha(self.frames / "idle.png")}, {"localIndex": 1, "sourcePath": str((self.frames / "active.png").resolve()), "sourceSha256": self._sha(self.frames / "active.png")}]}}}), encoding="utf-8")
        self.skin = {"names": np.array(["root", "hand"]), "parents": np.array([-1, 0], dtype=np.int64)}
        self.motions = {"clip": {"jointWorld": np.repeat(np.eye(4)[None, None], 4, axis=0).reshape(2, 2, 4, 4), "localRotation": np.repeat(np.eye(3)[None, None], 4, axis=0).reshape(2, 2, 3, 3)}}
        base_w = self.motions["clip"]["jointWorld"].copy()
        base_l = self.motions["clip"]["localRotation"].copy()
        corrected_w, corrected_l, corr = base_w.copy(), base_l.copy(), np.repeat(np.eye(3)[None], 2, axis=0)
        angle = np.pi / 4
        corrected_w[1, 1, :3, :3] = [[np.cos(angle), -np.sin(angle), 0], [np.sin(angle), np.cos(angle), 0], [0, 0, 1]]
        corrected_l[1, 1] = corrected_w[1, 1, :3, :3]
        corr[1] = corrected_l[1, 1]
        self._write_artifact(base_w, base_l, corrected_w, corrected_l, corr)

    @staticmethod
    def _sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _write_artifact(self, base_w, base_l, corrected_w, corrected_l, corr):
        motion = self.root / "source_wrist_motion.npz"
        np.savez_compressed(motion, clipKeys=np.array(["clip"]), clipOffsets=np.array([0, 2]), jointWorld=corrected_w.reshape(2, 2, 4, 4), localRotation=corrected_l.reshape(2, 2, 3, 3), corrections=corr, baselineJointWorld=base_w, baselineLocalRotation=base_l, anchorVertexIds=np.array([0]), anchorRestWorld=np.zeros(3), ownerRestWorld=np.zeros(3))
        report = {"proof": "source-guided-wrist-orientation-diagnostic-no-delivery", "asset": "unit", "corpusSha256": self._sha(self.corpus), "fitProvenance": {"preparedSkinSha256": "skin"}, "annotationPath": str(self.annotation.resolve()), "annotationSha256": self._sha(self.annotation), "motionArtifactSha256": self._sha(motion), "owner": "hand", "clipKeys": ["clip"], "clipOffsets": [0, 2]}
        self.report = self.root / "report.json"
        self.report.write_text(json.dumps(report), encoding="utf-8")

    def tearDown(self):
        if self.root.resolve().parent != self.base:
            raise ValueError("test cleanup escaped fixture root")
        shutil.rmtree(self.root)

    def test_valid_leaf_completion_preserves_idle_and_positions(self):
        result, provenance = apply_motion_completion(self.motions, self.skin, self.report, "unit", self._sha(self.corpus), "skin")
        np.testing.assert_array_equal(result["clip"]["jointWorld"][0], self.motions["clip"]["jointWorld"][0])
        self.assertEqual(provenance["mappedClips"], ["clip"])
        self.assertFalse(np.array_equal(result["clip"]["jointWorld"][1], self.motions["clip"]["jointWorld"][1]))
        self.assertTrue(result["clip"]["clipFrame0IsBind"])

    def test_fit_consumer_restores_pinned_completion(self):
        completed, provenance = apply_motion_completion(self.motions, self.skin, self.report, "unit", self._sha(self.corpus), "skin")
        fit = {"asset": "unit", "inputs": {"corpusSha256": self._sha(self.corpus), "researchSkin": "skin"},
               "motionCompletion": provenance}
        restored = restore_motion_completion(self.motions, self.skin, fit)
        np.testing.assert_array_equal(restored["clip"]["jointWorld"], completed["clip"]["jointWorld"])
        fit["motionCompletion"]["reportSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "report changed"):
            restore_motion_completion(self.motions, self.skin, fit)

    def test_legacy_fit_has_no_implicit_completion(self):
        self.assertIs(restore_motion_completion(self.motions, self.skin, {}), self.motions)

    def test_changed_first_active_frame_recomputes_bind_metadata(self):
        corpus = json.loads(self.corpus.read_text())
        corpus["captures"][1]["frames"][0] = str((self.frames / "active.png").resolve())
        self.corpus.write_text(json.dumps(corpus))
        annotation = json.loads(self.annotation.read_text())
        annotation["corpusSha256"] = self._sha(self.corpus)
        frame = annotation["captures"]["clip"]["frames"][0]
        frame["sourcePath"] = corpus["captures"][1]["frames"][0]
        frame["sourceSha256"] = self._sha(self.frames / "active.png")
        self.annotation.write_text(json.dumps(annotation))
        with np.load(self.root / "source_wrist_motion.npz", allow_pickle=False) as data:
            values = {key: data[key].copy() for key in data.files}
        values["jointWorld"][0, 1] = values["jointWorld"][1, 1]
        values["localRotation"][0, 1] = values["localRotation"][1, 1]
        values["corrections"][0] = values["corrections"][1]
        self._write_artifact(values["baselineJointWorld"], values["baselineLocalRotation"],
                             values["jointWorld"], values["localRotation"], values["corrections"])
        self.motions["clip"]["clipFrame0IsBind"] = True
        result, _ = apply_motion_completion(self.motions, self.skin, self.report, "unit", self._sha(self.corpus), "skin")
        self.assertFalse(result["clip"]["clipFrame0IsBind"])
        self.assertTrue(self.motions["clip"]["clipFrame0IsBind"])

    def test_changed_position_rejected(self):
        with np.load(self.root / "source_wrist_motion.npz") as data:
            values = {key: data[key] for key in data.files}
        values["jointWorld"] = values["jointWorld"].copy()
        values["jointWorld"][1, 1, 0, 3] = 1
        np.savez_compressed(self.root / "source_wrist_motion.npz", **values)
        report = json.loads(self.report.read_text())
        report["motionArtifactSha256"] = self._sha(self.root / "source_wrist_motion.npz")
        self.report.write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaises(ValueError):
            apply_motion_completion(self.motions, self.skin, self.report, "unit", self._sha(self.corpus), "skin")

    def test_wrong_baseline_rejected(self):
        with np.load(self.root / "source_wrist_motion.npz") as data:
            values = {key: data[key] for key in data.files}
        values["baselineLocalRotation"] = values["baselineLocalRotation"].copy()
        values["baselineLocalRotation"][0, 1] = values["localRotation"][1, 1]
        np.savez_compressed(self.root / "source_wrist_motion.npz", **values)
        report = json.loads(self.report.read_text())
        report["motionArtifactSha256"] = self._sha(self.root / "source_wrist_motion.npz")
        self.report.write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "baseline differs"):
            apply_motion_completion(self.motions, self.skin, self.report, "unit", self._sha(self.corpus), "skin")

    def test_nonleaf_owner_rejected(self):
        self.skin["parents"] = np.array([-1, 0], dtype=np.int64)
        self.report.write_text(self.report.read_text().replace('"owner": "hand"', '"owner": "root"'), encoding="utf-8")
        with self.assertRaises(ValueError):
            apply_motion_completion(self.motions, self.skin, self.report, "unit", self._sha(self.corpus), "skin")


if __name__ == "__main__":
    unittest.main()
