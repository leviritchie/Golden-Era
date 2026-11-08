import hashlib
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

from PIL import Image
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_attachment_direction_trial as trial


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class AttachmentTrialPreflightTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("artifacts/test_tmp") / ("attachment_trial_" + uuid.uuid4().hex)
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def fixture(self):
        frame = self.root / "000000.png"
        Image.new("RGB", (4, 4), (20, 30, 40)).save(frame)
        capture = self.root / "capture.npz"
        capture.write_bytes(b"capture")
        skin = self.root / "skin.npz"
        skin.write_bytes(b"skin")
        mesh = self.root / "mesh.glb"
        mesh.write_bytes(b"mesh")
        calibration = self.root / "idle_reference.json"
        calibration.write_text(json.dumps({"referencePositions": [[0, 0, 0]]}), encoding="utf-8")
        registration = self.root / "registration"
        registration.mkdir()
        camera = {"right": [1, 0, 0], "down": [0, 1, 0], "forward": [0, 0, 1],
                  "scale": 1, "offset": [0, 0], "depth_center": 0, "depth_span": 1,
                  "sourceSize": [4, 4], "sourceCrop": {"left": 0, "top": 0, "size": 4}, "resolution": 224}
        (registration / "camera.json").write_text(json.dumps(camera), encoding="utf-8")
        previous = {"asset": "test_asset", "kind": "idle_registration_only",
                    "inputs": {"researchSkin": digest(skin), "calibrationPath": str(calibration),
                               "calibration": digest(calibration)}}
        (registration / "pilot_report.json").write_text(json.dumps(previous), encoding="utf-8")
        row = {"key": "clip", "frames": [str(frame)], "sourceIndices": [0], "capture": str(capture),
               "captureSha256": digest(capture), "referenceIndex": 0, "contextBeforeCount": 0,
               "contextAfterCount": 0}
        corpus = {"unit": "test_asset", "captures": [row], "sourceFrames": {}}
        corpus_path = self.root / "corpus.json"
        corpus_path.write_text(json.dumps(corpus), encoding="utf-8")
        recipe = {"schema": 1, "method": "agent_eye_authored_attachment_axis", "asset": "test_asset",
                  "clip": "clip", "corpusSha256": digest(corpus_path), "skinSha256": digest(skin),
                  "calibrationSha256": digest(calibration), "cameraSha256": digest(registration / "camera.json"),
                  "sourceMeshSha256": digest(mesh), "joint": "j0", "region": "weapon",
                  "sourceAxisBones": ["Bone_0", "Bone_1"], "coordinateCanvas": [4, 4],
                  "anchorFrame": 0, "maxCorrectionDegrees": 30,
                  "frames": [{"sha256": digest(frame), "grip": [1, 1], "tip": [2, 1]}]}
        recipe_path = self.root / "recipe.json"
        recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
        return recipe_path, corpus_path, registration, frame

    def invoke(self, recipe, corpus, registration, output, **kwargs):
        with mock.patch.object(trial, "get_profile", return_value={"mesh": self.root / "mesh.glb"}), \
             mock.patch.object(trial, "_load_frozen_prep", return_value=({"researchSkin": self.root / "skin.npz"}, {"weights": np.ones((1,1))})):
            trial.run(recipe, corpus, registration, output, **kwargs)

    def test_candidate_requires_paired_hash(self):
        recipe, corpus, registration, _ = self.fixture()
        with self.assertRaisesRegex(ValueError,'supplied together'):
            self.invoke(recipe,corpus,registration,self.root/'out',candidate_skin=self.root/'skin.npz')

    def test_candidate_hash_drift_refused(self):
        recipe, corpus, registration, _ = self.fixture()
        with self.assertRaisesRegex(ValueError,'candidate skin hash'):
            self.invoke(recipe,corpus,registration,self.root/'out',candidate_skin=self.root/'skin.npz',candidate_sha256='wrong')

    def test_existing_output_refused(self):
        recipe, corpus, registration, _ = self.fixture()
        output = self.root / "out"
        output.mkdir()
        with self.assertRaises(FileExistsError):
            trial.run(recipe, corpus, registration, output)

    def test_mismatched_registration_camera_refused(self):
        recipe, corpus, registration, _ = self.fixture()
        (registration / "camera.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "registration camera"):
            self.invoke(recipe, corpus, registration, self.root / "out")

    def test_source_frame_hash_mismatch_refused(self):
        recipe, corpus, registration, frame = self.fixture()
        frame.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "source frame"):
            self.invoke(recipe, corpus, registration, self.root / "out")

    def test_wrong_registration_asset_refused(self):
        recipe, corpus, registration, _ = self.fixture()
        report = json.loads((registration / "pilot_report.json").read_text(encoding="utf-8"))
        report["asset"] = "other_asset"
        (registration / "pilot_report.json").write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "registration identity"):
            self.invoke(recipe, corpus, registration, self.root / "out")


if __name__ == "__main__":
    unittest.main()
