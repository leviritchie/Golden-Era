#!/usr/bin/env python3
"""Tests for genai_pink_square_weapon_tip detection."""
from __future__ import annotations

import unittest

import numpy as np
from PIL import Image

from genai_pink_square_weapon_tip import (
    deceptive_prompt,
    detect_neon_pink_centroid,
    map_point_to_source,
    resolve_prompt,
)


class GenaiPinkSquareTests(unittest.TestCase):
    def test_deceptive_prompt_mentions_no_keypoints(self) -> None:
        prompt = deceptive_prompt()
        self.assertIn("neon pink", prompt.lower())
        self.assertNotIn("keypoint", prompt.lower())
        self.assertNotIn("landmark", prompt.lower())
        self.assertNotIn("ik", prompt.lower())

    def test_landmarking_prompt_is_explicit(self) -> None:
        prompt = resolve_prompt("landmarking")
        self.assertIn("landmark", prompt.lower())
        self.assertIn("weapontip", prompt.lower())
        self.assertIn("neon pink", prompt.lower())

    def test_detect_centroid_of_square(self) -> None:
        im = Image.new("RGB", (100, 80), (0, 0, 0))
        arr = np.array(im)
        arr[20:24, 60:64] = (255, 0, 255)
        cx, cy, count = detect_neon_pink_centroid(Image.fromarray(arr))
        self.assertEqual((cx, cy), (62, 22))
        self.assertGreaterEqual(count, 16)

    def test_map_point_across_sizes(self) -> None:
        mapped = map_point_to_source((768, 512), edited_size=(1536, 1024), source_size=(1098, 876))
        self.assertEqual(mapped, (549, 438))


if __name__ == "__main__":
    unittest.main()
