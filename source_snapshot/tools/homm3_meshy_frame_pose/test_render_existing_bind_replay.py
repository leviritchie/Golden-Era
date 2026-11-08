import unittest

import numpy as np

from .render_existing_bind_replay import (
    _content_crop,
    build_camera,
    canonical_square_crop,
    inverse_surface_alignment,
    validate_report,
)


class ExistingBindReplayTests(unittest.TestCase):
    def test_canonical_crop_pads_short_height_without_recentering_foreground(self):
        self.assertEqual(canonical_square_crop((450, 400)), {"left": 0, "top": -25, "size": 450})

    def test_camera_scales_registration_and_shifts_into_padded_canvas(self):
        registration = {
            "views": {
                "candidates": [
                    {
                        "camera": {
                            "scale": 57.5,
                            "offset": [196.0, 266.0],
                            "yawDeg": 0.0,
                            "pitchDeg": 0.0,
                        }
                    }
                ]
            }
        }
        camera, crop = build_camera(registration, (450, 400), 2)
        self.assertEqual(crop, {"left": 0, "top": -25, "size": 450})
        self.assertEqual(camera["resolution"], 900)
        self.assertEqual(camera["offset"], [392.0, 582.0])
        np.testing.assert_allclose(camera["right"], [1.0, 0.0, 0.0])

    def test_camera_yaw_offset_is_recorded_without_changing_registration_offset(self):
        registration = {
            "views": {
                "candidates": [
                    {
                        "camera": {
                            "scale": 57.5,
                            "offset": [196.0, 266.0],
                            "yawDeg": 0.0,
                            "pitchDeg": 0.0,
                        }
                    }
                ]
            }
        }
        camera, _ = build_camera(registration, (450, 450), 1, camera_yaw_offset_deg=90.0)
        self.assertEqual(camera["baseRegistrationYawDeg"], 0.0)
        self.assertEqual(camera["cameraYawOffsetDeg"], 90.0)
        self.assertEqual(camera["yawDeg"], 90.0)
        self.assertNotEqual(camera["right"], [1.0, 0.0, 0.0])

    def test_content_crop_contains_both_source_and_mesh(self):
        source = np.zeros((2, 8, 8), dtype=float)
        mesh = np.zeros_like(source)
        source[0, 1, 2] = 1.0
        mesh[1, 5, 6] = 1.0
        self.assertEqual(_content_crop(source, mesh, 0), (2, 1, 7, 6))

    def test_inverse_surface_alignment_returns_source_mesh_coordinates(self):
        alignment = {
            "rotation": [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]],
            "scale": 2.0,
            "translation": [1.0, 2.0, 3.0],
        }
        source = np.asarray([[1.0, 0.0, 0.0], [0.0, 2.0, -1.0]])
        capture = 2.0 * (source @ np.asarray(alignment["rotation"]).T) + alignment["translation"]
        np.testing.assert_allclose(inverse_surface_alignment(capture, alignment), source)

    def test_report_validator_rejects_missing_frame_labels(self):
        report = {
            "schema": "homm3.existing-bind-replay.v1",
            "proof": "generated-artifact fixed-camera replay",
            "unit": "h3_test",
            "bind": "bind.glb",
            "capture": "capture.npz",
            "master": "master.json",
            "registration": "registration.json",
            "previewScale": 2,
            "resolution": 900,
            "frameCount": 2,
            "restFrameMaxVertexError": 0.0,
            "fullReel": "full.gif",
            "detailReel": "detail.gif",
            "labels": ["one"],
        }
        with self.assertRaisesRegex(ValueError, "labels"):
            validate_report(report)


if __name__ == "__main__":
    unittest.main()
