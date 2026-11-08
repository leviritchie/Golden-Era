"""Tests for anatomy-detected keypoint derivation (no CUDA detector)."""
from __future__ import annotations

import unittest

from anatomy_detect_keypoints import (
    anatomy_keypoints_by_frame_index,
    box_center,
    build_anatomy_keypoints_payload,
)
from roc_anatomical_boxes import PartBox


class AnatomyDetectKeypointsTests(unittest.TestCase):
    def test_box_center(self) -> None:
        self.assertEqual(box_center((10.0, 20.0, 30.0, 40.0)), (20.0, 30.0))

    def test_payload_from_synthetic_boxes(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from PIL import Image

        class FakeDetector:
            def detect(self, image, *, allowed_parts, laterality_enabled=False, laterality_depth=None):
                return [PartBox("head", (40.0, 30.0, 60.0, 50.0), 0.9)]

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "07.png"
            Image.new("RGBA", (120, 80), (40, 40, 40, 255)).save(path)
            payload = build_anatomy_keypoints_payload(
                frame_indices=(7,),
                target_paths=(path,),
                parts=("head",),
                detector=FakeDetector(),
            )
        self.assertEqual(payload["method"], "anatomy_box_detection")
        keyed = anatomy_keypoints_by_frame_index(payload)
        self.assertEqual(keyed[7]["head"], (50.0, 40.0))

    def test_keypoints_by_frame_index(self) -> None:
        payload = {
            "frames": [
                {
                    "frameIndex": 7,
                    "joints": {"head": {"x": 12.0, "y": 34.0, "visible": True}},
                }
            ]
        }
        keyed = anatomy_keypoints_by_frame_index(payload)
        self.assertEqual(keyed[7]["head"], (12.0, 34.0))


if __name__ == "__main__":
    unittest.main()
