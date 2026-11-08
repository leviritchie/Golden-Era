import hashlib
import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest import mock
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compare_aligned_capture_motion as trial


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class CompareAlignedPreflightTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("artifacts/compare_aligned_tests") / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.original = self.root / "original.npz"
        self.skin = self.root / "skin.npz"
        self.corpus_path = self.root / "corpus.json"
        self.registration = self.root / "registration"
        self.registration.mkdir()
        self.original.write_bytes(b"original")
        self.skin.write_bytes(b"skin")
        self.manifest = self.root / "source_manifest.json"
        self.manifest.write_text("{}", encoding="utf-8")
        self.calibration = self.root / "idle_reference.json"
        self.calibration.write_text(json.dumps({"referencePositions": [[0, 0, 0]]}), encoding="utf-8")
        self.capture = self.root / "clip.npz"
        self.capture.write_bytes(b"capture")
        self.frame = self.root / "000.png"
        self.frame.write_bytes(b"frame")
        self.camera = self.registration / "camera.json"
        self.camera.write_text(json.dumps({
            "right": [1, 0, 0], "down": [0, 1, 0], "forward": [0, 0, 1],
            "scale": 1, "offset": [0, 0], "depth_center": 0, "depth_span": 1,
            "sourceSize": [4, 4], "sourceCrop": {"left": 0, "top": 0, "size": 4},
            "resolution": 224,
        }), encoding="utf-8")
        self.skin_data = {
            "names": np.asarray(["j0"]), "parents": np.asarray([-1]),
            "captureOffsets": np.zeros((1, 3)), "offsets": np.zeros((1, 3)),
            "vertices": np.zeros((1, 3)), "triangles": np.zeros((0, 3), dtype=np.int64),
            "uvs": np.zeros((1, 2)), "albedo": np.ones((1, 4)),
            "weights": np.ones((1, 1)), "regions": np.asarray(["body"]),
            "inverseBind": np.eye(4)[None],
        }
        self._write_corpus("capture_positions_v1")

    def tearDown(self):
        shutil.rmtree(self.root)

    def _write_corpus(self, representation):
        row = {
            "key": "clip", "frames": [str(self.frame.resolve())],
            "sourceIndices": [0], "capture": str(self.capture.resolve()),
            "captureSha256": digest(self.capture), "referenceIndex": 0,
            "contextBeforeCount": 1, "contextAfterCount": 0,
        }
        corpus = {
            "unit": "test_asset", "manifest": str(self.manifest.resolve()),
            "manifestSha256": digest(self.manifest), "motionRepresentation": representation,
            "captures": [row], "sourceFrames": {str(self.frame.resolve()): {"sha256": digest(self.frame)}},
        }
        self.corpus_path.write_text(json.dumps(corpus), encoding="utf-8")
        previous = {
            "asset": "test_asset", "kind": "idle_registration_only",
            "inputs": {
                "researchSkin": digest(self.original),
                "corpusSha256": digest(self.corpus_path),
                "calibrationPath": str(self.calibration.resolve()),
                "calibration": digest(self.calibration),
            },
        }
        (self.registration / "pilot_report.json").write_text(json.dumps(previous), encoding="utf-8")

    def _invoke(self, *, validation_gate=None):
        gate = validation_gate if validation_gate is not None else mock.Mock()
        with mock.patch.object(trial, "read_skin", side_effect=[self.skin_data, self.skin_data]), \
             mock.patch.object(trial, "validate_invariants", new=gate), \
             mock.patch.object(trial, "get_profile", return_value={"wholeBodyHubs": ()}):
            return trial.run(self.original, self.skin, self.corpus_path, self.registration, self.root / "out")

    def test_composed_motion_is_rejected_before_render(self):
        self._write_corpus("fixed_composed_fk_v1")
        with self.assertRaisesRegex(ValueError, "ordinary position captures"):
            self._invoke()
        self.assertFalse((self.root / "out").exists())

    def test_registration_asset_mismatch_is_rejected(self):
        self._write_corpus("capture_positions_v1")
        previous = json.loads((self.registration / "pilot_report.json").read_text())
        previous["asset"] = "other_asset"
        (self.registration / "pilot_report.json").write_text(json.dumps(previous), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "registration identity"):
            self._invoke()

    def test_manifest_hash_mismatch_is_rejected(self):
        self._write_corpus("capture_positions_v1")
        corpus = json.loads(self.corpus_path.read_text())
        corpus["manifestSha256"] = "0" * 64
        self.corpus_path.write_text(json.dumps(corpus), encoding="utf-8")
        previous = json.loads((self.registration / "pilot_report.json").read_text())
        previous["inputs"]["corpusSha256"] = digest(self.corpus_path)
        (self.registration / "pilot_report.json").write_text(json.dumps(previous), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source manifest changed"):
            self._invoke()

    def test_common_skin_inputs_reach_invariant_gate(self):
        self._write_corpus("fixed_composed_fk_v1")
        gate = mock.Mock()
        with self.assertRaises(ValueError):
            self._invoke(validation_gate=gate)
        gate.assert_called_once()
        self.assertIs(gate.call_args.args[0], self.skin_data)
        self.assertIs(gate.call_args.args[1], self.skin_data)


if __name__ == "__main__":
    unittest.main()
