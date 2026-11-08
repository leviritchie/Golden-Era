"""Focused contract tests for the immutable idle calibration."""
from __future__ import annotations

import sys
import tempfile
import unittest
import json
from pathlib import Path

import numpy as np
from PIL import Image

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

from idle_calibration import load_or_create


class IdleCalibrationTests(unittest.TestCase):
    def _fixture(self, root: Path):
        capture = root / "capture.npz"
        skin = root / "research_skin.npz"
        reference_png = root / "attack_00.png"
        idle_png = root / "idle_00.png"
        positions = np.asarray([[[0., 0., 0.], [0., 1., 0.]], [[0., 0., 0.], [0., 1.2, 0.]]])
        names = np.asarray(["Root", "Tip"])
        parents = np.asarray([-1, 0], dtype=np.int64)
        np.savez(capture, pred_position=positions, joint_names=names, parents=parents)
        skin.write_bytes(b"frozen skin fixture")
        image = Image.new("RGBA", (2, 2), (20, 243, 14, 255))
        image.save(reference_png)
        image.save(idle_png)
        return capture, skin, reference_png, idle_png, positions, names.tolist(), parents

    def test_create_and_strict_reuse(self) -> None:
        with tempfile.TemporaryDirectory(dir="V:/Games/Olden Era Playtest Tweak/artifacts/homm3_mocap_v2") as directory:
            root = Path(directory)
            capture, skin, ref, idle, positions, names, parents = self._fixture(root)
            path = root / "calibration.json"
            first = load_or_create(calibration_path=path, capture_path=capture, reference_png=ref,
                                    known_idle_png=idle, research_skin=skin, capture_positions=positions,
                                    names=names, parents=parents)
            second = load_or_create(calibration_path=path, capture_path=capture, reference_png=ref,
                                    known_idle_png=idle, research_skin=skin, capture_positions=positions,
                                    names=names, parents=parents)
            self.assertTrue(np.array_equal(first["referencePositions"], positions[0]))
            self.assertEqual(first["hash"], second["hash"])

    def test_rejects_reference_edit_and_topology_drift(self) -> None:
        with tempfile.TemporaryDirectory(dir="V:/Games/Olden Era Playtest Tweak/artifacts/homm3_mocap_v2") as directory:
            root = Path(directory)
            capture, skin, ref, idle, positions, names, parents = self._fixture(root)
            path = root / "calibration.json"
            load_or_create(calibration_path=path, capture_path=capture, reference_png=ref,
                           known_idle_png=idle, research_skin=skin, capture_positions=positions,
                           names=names, parents=parents)
            changed = positions.copy()
            changed[0, 1, 0] += 0.01
            with self.assertRaisesRegex(ValueError, "caller positions"):
                load_or_create(calibration_path=path, capture_path=capture, reference_png=ref,
                               known_idle_png=idle, research_skin=skin, capture_positions=changed,
                               names=names, parents=parents)
            with self.assertRaisesRegex(ValueError, "topology"):
                load_or_create(calibration_path=root / "other.json", capture_path=capture, reference_png=ref,
                               known_idle_png=idle, research_skin=skin, capture_positions=positions,
                               names=["Root", "Other"], parents=parents)

    def test_rejects_caller_drift_and_all_provenance_changes(self) -> None:
        with tempfile.TemporaryDirectory(dir="V:/Games/Olden Era Playtest Tweak/artifacts/homm3_mocap_v2") as directory:
            root = Path(directory)
            capture, skin, ref, idle, positions, names, parents = self._fixture(root)
            with self.assertRaisesRegex(ValueError, "caller positions"):
                load_or_create(calibration_path=root / "initial.json", capture_path=capture, reference_png=ref,
                               known_idle_png=idle, research_skin=skin, capture_positions=positions + 0.01,
                               names=names, parents=parents)
            path = root / "calibration.json"
            load_or_create(calibration_path=path, capture_path=capture, reference_png=ref,
                           known_idle_png=idle, research_skin=skin, capture_positions=positions,
                           names=names, parents=parents)
            changed = positions.copy()
            changed[1, 1, 1] += 0.02
            np.savez(capture, pred_position=changed, joint_names=np.asarray(names), parents=parents)
            with self.assertRaisesRegex(ValueError, "provenance drifted"):
                load_or_create(calibration_path=path, capture_path=capture, reference_png=ref,
                               known_idle_png=idle, research_skin=skin, capture_positions=changed,
                               names=names, parents=parents)

    def test_rejects_mismatched_idle_and_saved_reference(self) -> None:
        with tempfile.TemporaryDirectory(dir="V:/Games/Olden Era Playtest Tweak/artifacts/homm3_mocap_v2") as directory:
            root = Path(directory)
            capture, skin, ref, idle, positions, names, parents = self._fixture(root)
            mismatch = root / "mismatch.png"
            Image.new("RGBA", (2, 2), (0, 0, 0, 255)).save(mismatch)
            with self.assertRaisesRegex(ValueError, "PNGs differ"):
                load_or_create(calibration_path=root / "bad.json", capture_path=capture, reference_png=ref,
                               known_idle_png=mismatch, research_skin=skin, capture_positions=positions,
                               names=names, parents=parents)
            path = root / "calibration.json"
            load_or_create(calibration_path=path, capture_path=capture, reference_png=ref,
                           known_idle_png=idle, research_skin=skin, capture_positions=positions,
                           names=names, parents=parents)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["referencePositions"][1][0] += 0.1
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reference positions drifted"):
                load_or_create(calibration_path=path, capture_path=capture, reference_png=ref,
                               known_idle_png=idle, research_skin=skin, capture_positions=positions,
                               names=names, parents=parents)


if __name__ == "__main__":
    unittest.main()
