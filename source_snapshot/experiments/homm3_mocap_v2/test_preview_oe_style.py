"""CPU-only contracts for the offline OE-style preview replay."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from eagle_glb import gltf_world_matrices  # noqa: E402
from glb_skeleton import load_bind_skeleton  # noqa: E402
from mesh_preview import skin_vertices  # noqa: E402
from preview_oe_style import compare_geometry, edge_strain, replay, union_camera  # noqa: E402
from verify_calibrated_export import _serialized_local_rotations  # noqa: E402

RAW_IDLE = ROOT / "artifacts/homm3_mocap_v2/stronghold_oe_approved_v1/units/h3_ogre/Unit_Idle.glb"


class PreviewOEStyleTests(unittest.TestCase):
    def test_replay_keeps_all_eight_influence_slots_and_rest_identity(self) -> None:
        """The preview must exercise the same 8-slot LBS data shipped to Unity."""
        skin = load_bind_skeleton(RAW_IDLE)
        self.assertIsNotNone(skin.vertex_weights)
        self.assertIsNotNone(skin.vertex_joints)
        self.assertEqual(skin.vertex_weights.shape[1], 8)
        times, rotations, translations, _ = _serialized_local_rotations(RAW_IDLE, allow_root_motion=True)
        _, meshes = replay(RAW_IDLE, np.asarray([times[0], times[-1]], dtype=float))
        self.assertEqual(meshes.shape, (2, skin.vertices.shape[0], 3))
        self.assertTrue(np.isfinite(meshes).all())
        expected = skin_vertices(skin, gltf_world_matrices(
            local_rotation=rotations[0], local_translation=translations[0],
            parents=np.asarray(skin.parents)))
        np.testing.assert_allclose(meshes[0], expected, rtol=1e-9, atol=1e-9)

    def test_union_camera_contains_both_variants_with_one_frame(self) -> None:
        basis = {"right": [1.0, 0.0, 0.0], "down": [0.0, 1.0, 0.0], "forward": [0.0, 0.0, 1.0]}
        meshes = np.asarray([[[-2.0, -1.0, 2.0], [1.0, 2.0, 3.0]],
                             [[-1.5, -0.5, 2.5], [3.0, 1.5, 4.0]]], dtype=float)
        camera = union_camera(basis, [meshes[:1], meshes[1:]], 64)
        points = meshes.reshape(-1, 3)
        x = points @ np.asarray(camera["right"]); y = points @ np.asarray(camera["down"])
        projected_x = x * camera["scale"] + camera["offset"][0]
        projected_y = y * camera["scale"] + camera["offset"][1]
        self.assertTrue(0.0 <= projected_x.min() < projected_x.max() <= 63.0)
        self.assertTrue(0.0 <= projected_y.min() < projected_y.max() <= 63.0)
        self.assertGreater(camera["depth_span"], 0.0)

    def test_animation_duration_and_gif_delay_contract(self) -> None:
        times, *_ = _serialized_local_rotations(RAW_IDLE, allow_root_motion=True)
        self.assertEqual(times[0], 0.0)
        duration = float(times[-1]); frame_count = max(2, round(duration * 24))
        self.assertEqual(frame_count, 14)
        boundaries = np.rint(np.arange(frame_count + 1) * duration * 100 / frame_count).astype(int) * 10
        delays = np.maximum(10, np.diff(boundaries))
        self.assertTrue(np.all(delays >= 10))
        self.assertLessEqual(abs(float(delays.sum()) / 1000.0 - duration), 0.01)

    def test_compare_geometry_uses_bind_inverse_field_and_rejects_changes(self) -> None:
        common = {"names": ("root",), "vertices": np.zeros((1, 3)),
                  "triangles": np.zeros((0, 3), dtype=np.int32), "uvs": np.zeros((1, 2)),
                  "vertex_joints": np.zeros((1, 8), dtype=np.int32), "vertex_weights": np.zeros((1, 8)),
                  "inverse_bind": np.eye(4, dtype=float)[None], "parents": np.array([-1]),
                  "rest_local_rotation": np.eye(3, dtype=float)[None],
                  "rest_local_translation": np.zeros((1, 3), dtype=float)}
        compare_geometry(SimpleNamespace(**common), SimpleNamespace(**common))
        changed = dict(common); changed["inverse_bind"] = np.zeros((1, 4, 4))
        with self.assertRaisesRegex(ValueError, "inverse_bind"):
            compare_geometry(SimpleNamespace(**common), SimpleNamespace(**changed))

    def test_edge_strain_is_zero_for_identity_and_detects_known_scale(self) -> None:
        triangles = np.asarray([[0, 1, 2]], dtype=np.int32)
        baseline = np.asarray([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]])
        identity = edge_strain(triangles, baseline, baseline.copy())
        self.assertEqual(identity["max"], 0.0)
        candidate = baseline.copy()
        candidate[:, 1] *= 1.5
        measured = edge_strain(triangles, baseline, candidate)
        self.assertGreater(measured["max"], 0.4)
        self.assertEqual(measured["disposition"], "diagnostic only; no automatic acceptance or damping")
