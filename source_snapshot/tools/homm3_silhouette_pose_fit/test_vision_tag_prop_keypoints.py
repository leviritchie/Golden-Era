#!/usr/bin/env python3
"""Tests for vision_tag_prop_keypoints coordinate scaling."""
from __future__ import annotations

import unittest

from vision_tag_prop_keypoints import _coords_from_payload


class VisionCoordScalingTests(unittest.TestCase):
    def test_normalized_coords_map_to_full_image(self) -> None:
        payload = {
            "frameIndex": 10,
            "xy": {"WeaponTip": [0.5, 0.25], "RWrist": [0.4, 0.5]},
        }
        out = _coords_from_payload(
            payload,
            frame_index=10,
            expected=["WeaponTip", "RWrist"],
            sent_w=512,
            sent_h=408,
            sx=1098 / 512,
            sy=876 / 408,
            full_w=1098,
            full_h=876,
        )
        self.assertEqual(out["WeaponTip"], (548, 219))

    def test_sent_pixel_coords_scale_to_full_image(self) -> None:
        payload = {
            "frameIndex": 10,
            "xy": {"WeaponTip": [415, 241], "RWrist": [221, 230]},
        }
        out = _coords_from_payload(
            payload,
            frame_index=10,
            expected=["WeaponTip", "RWrist"],
            sent_w=512,
            sent_h=408,
            sx=1098 / 512,
            sy=876 / 408,
            full_w=1098,
            full_h=876,
        )
        self.assertEqual(out["WeaponTip"], (890, 517))
        self.assertEqual(out["RWrist"], (474, 494))

    def test_full_res_pixels_without_scaling_fail_closed(self) -> None:
        payload = {
            "frameIndex": 10,
            "xy": {"WeaponTip": [415, 518]},
        }
        with self.assertRaisesRegex(ValueError, "neither normalized"):
            _coords_from_payload(
                payload,
                frame_index=10,
                expected=["WeaponTip"],
                sent_w=512,
                sent_h=408,
                sx=1098 / 512,
                sy=876 / 408,
                full_w=1098,
                full_h=876,
            )


if __name__ == "__main__":
    unittest.main()
