"""Unit tests for cs_weight_keys.py (the morph-weight keys bake_cs.py writes per clip).

    python tools/homm3_def_retarget/test_cs_weight_keys.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs_weight_keys as WK  # noqa: E402


class WeightKeys(unittest.TestCase):
    def test_zero_correction_clip_gets_all_zero_channel(self):
        # 2026-10-12 h3_sacred_phoenix Unit_Move: no CS_ shape of its own -> the first shape keyed 0 at both ends
        keys = WK.weight_keys(1, 7, [], first="CS_Unit_Idle_002")
        self.assertEqual(keys, [("CS_Unit_Idle_002", 1, 0.0), ("CS_Unit_Idle_002", 7, 0.0)])
        self.assertTrue(all(v == 0.0 for _, _, v in keys))

    def test_single_frame_clip_keys_once(self):
        self.assertEqual(WK.weight_keys(3, 3, [], first="s"), [("s", 3, 0.0)])

    def test_clip_with_correction_unchanged(self):
        # the rule before 2026-10-12: each own shape 1 on its frame, 0 either side, clipped to the clip's range;
        # `first` plays no part when the clip has shapes of its own
        own = [(1, "a"), (4, "b"), (7, "c")]
        expected = [("a", 1, 1.0), ("a", 2, 0.0),
                    ("b", 3, 0.0), ("b", 4, 1.0), ("b", 5, 0.0),
                    ("c", 6, 0.0), ("c", 7, 1.0)]
        self.assertEqual(WK.weight_keys(1, 7, own), expected)
        self.assertEqual(WK.weight_keys(1, 7, own, first="other"), expected)

    def test_bake_without_shapes_keys_nothing(self):
        self.assertEqual(WK.weight_keys(1, 7, [], first=None), [])


if __name__ == "__main__":
    unittest.main()
