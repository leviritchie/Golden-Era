"""Focused phase-6 town coverage and native camera contract regressions."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import sys
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import conflux_full3d_periphery as periphery
import conflux_town_camera_pan as pan
import build_conflux_full3d_scene as builder
import extract_city_camera_pan as extractor
import validate_town_scene3d_contract as gate


class Phase6PanContractTests(unittest.TestCase):
    @contextmanager
    def patched_native_camera_inputs(self, expected, extracted, loaded, level_digest=None,
                                     resource_file_digest=None):
        # The checked-in v1 camera record is the legacy Golden contract. Keep an
        # explicit fixture so port v2 provenance cannot silently redefine it.
        folder = gate.DEFAULT_GAME_DATA
        level = folder / "level67"
        resources = folder / "resources.assets"
        camera_record = Path("synthetic-camera-record.json")
        resource_digest = "b" * 64
        camera_json = json.dumps({"schema": "homm3.vanilla_city_camera_pan.v1",
                                  "gameFiles": {"resources.assets": resource_digest}})
        digests = {"level67": level_digest or expected["sourceLevelSha256"],
                   "resources.assets": resource_file_digest or resource_digest}

        def is_file(path):
            return path in (level, resources)

        real_read_text = Path.read_text

        def read_text(path, *args, **kwargs):
            if path == camera_record:
                return camera_json
            return real_read_text(path, *args, **kwargs)

        with ExitStack() as stack:
            stack.enter_context(patch.object(gate, "GAME_DATA", folder))
            stack.enter_context(patch.object(pan, "PAN_JSON", camera_record))
            stack.enter_context(patch.object(pan, "rest_pose_contract", return_value=expected))
            stack.enter_context(patch.object(pan, "load", return_value=loaded))
            stack.enter_context(patch.object(extractor, "GAME", folder))
            stack.enter_context(patch.object(extractor, "LEVELS", {"cityHuman2": "level67"}))
            stack.enter_context(patch.object(Path, "is_file", autospec=True, side_effect=is_file))
            stack.enter_context(patch.object(Path, "read_text", autospec=True, side_effect=read_text))
            sha = stack.enter_context(patch.object(
                extractor, "sha256", side_effect=lambda path: digests[path.name]))
            extract = stack.enter_context(patch.object(extractor, "extract", return_value=extracted))
            yield extract, sha

    @staticmethod
    def ray_triangle_t(origin, direction, triangle):
        a, b, c = triangle
        edge1, edge2 = b - a, c - a
        pvec = np.cross(direction, edge2)
        det = np.dot(edge1, pvec)
        if abs(det) < 1e-9:
            return None
        inv = 1 / det
        tvec = origin - a
        u = np.dot(tvec, pvec) * inv
        qvec = np.cross(tvec, edge1)
        v = np.dot(direction, qvec) * inv
        t = np.dot(edge2, qvec) * inv
        return float(t) if u >= 0 and v >= 0 and u + v <= 1 and t >= 0 else None

    @staticmethod
    def sample_raster():
        field = periphery.Field(0, 0, 1, np.full((5, 5), 5, np.float32))
        mesh = {"P": np.array([[1, -2, 1], [3, -2, 1], [1, -2, 3]], np.float32),
                "tris": np.array([[0, 1, 2]], np.int32)}
        cov = periphery.coverage_raster(field, mesh)
        npz = {**cov, "cam_pos": np.array([0, 1, 0]), "cam_fwd": np.array([0, 0, 1]),
               "cam_up": np.array([0, 1, 0]), "cam_right": np.array([1, 0, 0]),
               "frame_wh": np.array([4, 4]), "frame_sky": np.ones((4, 4), bool),
               "fov": np.array(47.6), "dome_r": np.array(10),
               "sky_az": np.array([-20, 20]), "sky_el": np.array([-90, 90])}
        return npz

    def test_final_retained_triangle_height_not_presettle_field(self):
        npz = self.sample_raster()
        self.assertEqual(float(npz["h"][1, 1]), 5)
        self.assertEqual(float(npz["outer_h"][1, 1]), -2)
        self.assertTrue(npz["covered"][1, 1])
        self.assertFalse(npz["covered"][2, 4])  # no dilation over a retained-geometry hole

    def test_stale_field_height_cannot_credit_outer_mesh(self):
        npz = self.sample_raster()
        origin = np.array([[1.5, 0, 1.5]])
        direction = np.array([[1.0, 0, 0]])
        final_triangle = np.array([[1, -2, 1], [3, -2, 1], [1, -2, 3]], np.float64)
        self.assertIsNone(self.ray_triangle_t(origin[0], direction[0], final_triangle))
        self.assertTrue(gate.pan_voids(npz, origin, direction)[0])
        stale = dict(npz, outer_h=npz["h"])
        self.assertFalse(gate.pan_voids(stale, origin, direction)[0])
        down = np.array([[0.0, -1.0, 0.0]])
        self.assertEqual(self.ray_triangle_t(origin[0], down[0], final_triangle), 2)
        self.assertFalse(gate.pan_voids(npz, origin, down)[0])

    def test_mathematical_image_border_maps_to_last_frame_pixel(self):
        npz = self.sample_raster()
        npz["covered"] = np.zeros_like(npz["covered"])
        npz["frame_sky"] = np.zeros_like(npz["frame_sky"])
        origin = np.array([[0.0, 1.0, 0.0]])
        t = np.tan(np.deg2rad(float(npz["fov"])) / 2)
        direction = np.array([[0.0, -t, 1.0]])
        direction /= np.linalg.norm(direction, axis=1, keepdims=True)
        self.assertFalse(gate.pan_voids(npz, origin, direction)[0])

    def test_native_camera_row_drift_refused(self):
        expected = copy.deepcopy(pan.rest_pose_contract())
        native = copy.deepcopy(pan.load())
        native["settings"]["deltaHorizontalAngle"] += 1
        native["camera"]["fieldOfView"] = 47.6
        with self.patched_native_camera_inputs(expected, native, pan.load()) as (extract, _):
            with self.assertRaises(SystemExit):
                gate.verify_native_camera_rest_pose("phase6-test")
            extract.assert_called_once_with("cityHuman2", "level67", {}, game_data_root=gate.DEFAULT_GAME_DATA)
            self.assertNotIn("fieldOfView", native["camera"])

    def test_native_camera_fov_drift_is_not_compatible(self):
        port = copy.deepcopy(pan.load())
        golden = copy.deepcopy(pan.load())
        port["camera"]["fieldOfView"] = 47.6
        golden["camera"]["fieldOfView"] = 48.0
        self.assertEqual(pan.native_layout_differences(port, golden), ["camera.fieldOfView"])

    def test_native_camera_level_hash_drift_refused_before_extraction(self):
        expected = copy.deepcopy(pan.rest_pose_contract())
        with self.patched_native_camera_inputs(expected, pan.load(), pan.load(),
                                               level_digest="0" * 64) as (extract, _):
            with self.assertRaises(SystemExit):
                gate.verify_native_camera_rest_pose("phase6-test")
            extract.assert_not_called()

    def test_native_camera_resources_hash_drift_refused_before_extraction(self):
        expected = copy.deepcopy(pan.rest_pose_contract())
        with self.patched_native_camera_inputs(expected, pan.load(), pan.load(),
                                               resource_file_digest="0" * 64) as (extract, _):
            with self.assertRaises(SystemExit):
                gate.verify_native_camera_rest_pose("phase6-test")
            extract.assert_not_called()

    def test_native_camera_snapshot_is_reused_but_each_catalog_is_compared(self):
        expected = pan.rest_pose_contract()
        catalog = {"referenceCamera": {"restPose": copy.deepcopy(expected)}}
        verifier = gate.NativeCameraRestPoseVerifier()
        with patch.object(gate, "verify_native_camera_rest_pose", return_value=expected) as verify:
            self.assertIn("restPose=installed-native-verified", verifier.check(catalog, "phase6-a"))
            self.assertIn("restPose=installed-native-verified", verifier.check(catalog, "phase6-b"))
            changed = copy.deepcopy(catalog)
            changed["referenceCamera"]["restPose"]["localPosition"][0] += 0.01
            with self.assertRaises(SystemExit):
                verifier.check(changed, "phase6-mutated")
            verify.assert_called_once_with("phase6-a", expected)

    def test_first_catalog_mismatch_refused_before_native_verification(self):
        catalog = {"referenceCamera": {"restPose": {"sourceLevelFile": "mutated"}}}
        verifier = gate.NativeCameraRestPoseVerifier()
        with patch.object(gate, "verify_native_camera_rest_pose") as verify:
            with self.assertRaises(SystemExit):
                verifier.check(catalog, "phase6-mutated")
            verify.assert_not_called()

    def test_file_hash_streams_bounded_chunks_and_counts_bytes(self):
        class ReadTrackingStream(io.BytesIO):
            def __init__(self, payload):
                super().__init__(payload)
                self.requested_sizes = []

            def read(self, size=-1):
                self.requested_sizes.append(size)
                return super().read(size)

        payload = b"bundle" * (gate.FILE_HASH_CHUNK_SIZE // 6 + 2)
        stream = ReadTrackingStream(payload)
        with patch.object(Path, "open", return_value=stream):
            size, digest = gate.file_sha256_and_size(Path("fixture.bundle"))
        self.assertEqual(size, len(payload))
        self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
        self.assertGreater(len(stream.requested_sizes), 2)
        self.assertTrue(all(n == gate.FILE_HASH_CHUNK_SIZE for n in stream.requested_sizes))

    def test_pan_render_aspects_use_runtime_root_scale(self):
        poses = builder.pan_render_specs()
        self.assertEqual(len(poses), 12)
        sizes = {(p["w"], p["h"]) for p in poses}
        self.assertEqual(sizes, {(1920, 1080), (4096, 2160), (2560, 1080)})
        for p in poses:
            self.assertAlmostEqual(p["scaleX"], (p["w"] / p["h"]) / (1920 / 1080))
            self.assertEqual(p["scaleY"], 1)

    def test_missing_outer_water_refused(self):
        cat = {"panCoverage": {"file": "pan_coverage.npz", "sha256": "0" * 64},
               "periphery": {"meshyCredits": 0, "mesh": {"frameIntrusions": 0},
                             "pieces": {"Mesh_OuterL0": {"tris": 1}}, "scatter": {}},
               "environment": {"pieces": ["Mesh_OuterL0"]}}
        with self.assertRaises(SystemExit):
            gate.check_pan_coverage(cat, "phase6-test", HERE)
        cat["environment"]["pieces"].append("Fx_WaterOuter")
        cat["periphery"]["water"] = {"tris": 2, "rivers": [{}, {}]}
        with self.assertRaises(SystemExit):
            gate.check_pan_coverage(cat, "phase6-test", HERE)
        cat["periphery"]["scatter"] = {"_tree": {"outsideFrame": 1},
                                         "Mesh_Outer_conifer_a_0": {"instances": 1, "tris": 1}}
        cat["environment"]["pieces"].append("Mesh_Outer_conifer_a_0")
        with self.assertRaises(SystemExit):
            gate.check_pan_coverage(cat, "phase6-test", HERE)


if __name__ == "__main__":
    unittest.main()
