"""Focused tests for serialized GLB animation parity."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

from eagle_glb import gltf_world_matrices, matrices_to_xyzw, write_skinned_glb
from glb_skeleton import load_bind_skeleton
from mesh_preview import skin_vertices
from verify_calibrated_export import verify_calibrated_export


def _axis_rotation(axis: int, angle: float) -> np.ndarray:
    result = np.eye(3, dtype=np.float64)
    c, s = float(np.cos(angle)), float(np.sin(angle))
    if axis == 0:
        result[1:, 1:] = ((c, -s), (s, c))
    elif axis == 1:
        result[::2, ::2] = ((c, s), (-s, c))
    else:
        result[:2, :2] = ((c, -s), (s, c))
    return result


class CalibratedExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="calibrated_export_", dir=EXPERIMENT)
        self.test_root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _fixture(self, path: Path, *, angle_scale: float = 1.0, translations: np.ndarray | None = None) -> np.ndarray:
        # The exporter always writes eight influence slots. Keep the fixture at
        # eight joints so the GLB remains valid without changing exporter code.
        names = ["Root"] + [f"Joint{index}" for index in range(1, 8)]
        parents = np.asarray((-1, 0, 1, 2, 3, 4, 5, 6), dtype=np.int64)
        rest_rot = np.repeat(np.eye(3, dtype=np.float64)[None], 8, axis=0)
        rest_trans = np.asarray([(0.0, 0.0, 0.0)] + [(0.0, 0.25, 0.0)] * 7)
        bind = gltf_world_matrices(local_rotation=rest_rot, local_translation=rest_trans, parents=parents)
        inverse_bind = np.linalg.inv(bind)
        vertices = np.asarray(((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.4, 1.0, 0.0)), dtype=np.float64)
        weights = np.zeros((3, 8), dtype=np.float64)
        weights[:, 0] = (1.0, 0.0, 0.0)
        weights[1:, 1] = 1.0
        triangles = np.asarray(((0, 1, 2),), dtype=np.int64)
        uvs = np.asarray(((0.0, 0.0), (0.5, 1.0), (1.0, 1.0)), dtype=np.float64)
        albedo = np.full((2, 2, 4), 255, dtype=np.uint8)
        rotations = np.stack(
            [
                rest_rot,
                np.concatenate((rest_rot[:1], rest_rot[1:].copy()), axis=0),
                np.concatenate((rest_rot[:1], rest_rot[1:].copy()), axis=0),
            ]
        )
        rotations[1, 1] = _axis_rotation(2, 0.6 * angle_scale)
        rotations[2, 1] = _axis_rotation(2, -0.4 * angle_scale)
        expected_skeleton_path = path
        animation = {"times": np.asarray((0.0, 0.1, 0.2)), "rotations": matrices_to_xyzw(rotations)}
        if translations is not None:
            animation["translations"] = np.asarray(translations)
        write_skinned_glb(
            expected_skeleton_path,
            names=names,
            parents=parents,
            rest_local_rotation=rest_rot,
            rest_local_translation=rest_trans,
            inverse_bind=inverse_bind,
            vertices=vertices,
            triangles=triangles,
            uvs=uvs,
            albedo=albedo,
            weights=weights,
            animation=animation,
        )
        loaded = load_bind_skeleton(path)
        expected = []
        for frame, local in enumerate(rotations):
            worlds = gltf_world_matrices(
                local_rotation=local,
                local_translation=rest_trans if translations is None else translations[frame],
                parents=parents,
            )
            expected.append(skin_vertices(loaded, worlds))
        return np.stack(expected)

    def test_allows_root_translation_only_when_explicitly_enabled(self) -> None:
        path = self.test_root / "root_motion.glb"
        translations = np.zeros((3, 8, 3), dtype=np.float64)
        translations[:, 1:, 1] = 0.25
        translations[:, 0, 0] = (0.0, 0.2, 0.4)
        expected = self._fixture(path, translations=translations)
        with self.assertRaisesRegex(ValueError, "translation channels"):
            verify_calibrated_export(path, expected_meshes=expected)
        report = verify_calibrated_export(path, expected_meshes=expected, allow_root_motion=True)
        self.assertTrue(report["ok"])
        self.assertEqual(report["channelInfo"]["translationJoints"], list(range(8)))

    def test_rejects_moving_nonroot_translation_in_root_motion_mode(self) -> None:
        path = self.test_root / "nonroot_motion.glb"
        translations = np.zeros((3, 8, 3), dtype=np.float64)
        translations[:, 1:, 1] = 0.25
        translations[1, 1, 0] = 0.01
        expected = self._fixture(path, translations=translations)
        with self.assertRaisesRegex(ValueError, "non-root translation"):
            verify_calibrated_export(path, expected_meshes=expected, allow_root_motion=True)

    def test_replays_all_serialized_frames_and_reports_idle(self) -> None:
        path = self.test_root / "parity.glb"
        expected = self._fixture(path)
        report = verify_calibrated_export(
            path, expected_meshes=expected, idle_frame=0,
            expected_times=np.asarray((0.0, 0.1, 0.2)),
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["frameCount"], 3)
        self.assertLess(report["idleFrameMax"], 1e-6)
        self.assertGreater(float(np.linalg.norm(expected[1] - expected[0], axis=-1).max()), 1e-4)

    def test_detects_serialized_timing_mismatch(self) -> None:
        path = self.test_root / "timing.glb"
        expected = self._fixture(path)
        with self.assertRaisesRegex(ValueError, "preview timing"):
            verify_calibrated_export(
                path, expected_meshes=expected,
                expected_times=np.asarray((0.0, 0.2, 0.4)),
            )

    def test_detects_serialized_rotation_mismatch(self) -> None:
        path = self.test_root / "parity.glb"
        expected = self._fixture(path, angle_scale=1.0)
        self._fixture(path, angle_scale=0.25)
        with self.assertRaisesRegex(ValueError, "does not replay"):
            verify_calibrated_export(path, expected_meshes=expected, idle_frame=0)


if __name__ == "__main__":
    unittest.main()
