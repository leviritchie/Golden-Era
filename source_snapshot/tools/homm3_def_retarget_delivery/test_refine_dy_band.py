"""build_unit.py's silhouetteRefine dy band: the ground gate's Hips entry rule, at the frames the gate judges.

    python -m unittest tools/homm3_def_retarget_delivery/test_refine_dy_band.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ground_check as G  # noqa: E402


class RefineDyBand(unittest.TestCase):
    """build_unit.py's silhouetteRefine searches dy only where the Hips stays inside the gate's entry allowance."""

    def test_judged_frames_are_the_gates_clip_entries_with_its_exemption(self):
        curve = {"segments": [{"suffix": "Idle", "globalStart": 0, "frameCount": 2, "bottom": [0.0, 0.0], "top": [0.0, 0.0]},
                              {"suffix": "Hitted", "globalStart": 2, "frameCount": 2, "bottom": [None, -0.066],
                               "top": [0.02, 0.05]},
                              {"suffix": "Idle", "globalStart": 4, "frameCount": 1, "bottom": [0.0], "top": [0.0]},
                              {"suffix": "Hitted", "globalStart": 5, "frameCount": 1, "bottom": [0.3], "top": [0.3]}]}
        a = G.GR.judged_hips_frames(curve, {"unit": "u"})
        # only the canonical (longest) Hitted's first frame; Idle is the reference; the empty bottom row takes its
        # neighbour, as ground_check's _fill does
        self.assertEqual(list(a), [2])
        self.assertAlmostEqual(a[2], G.GROUND_TOL + 0.066)
        self.assertEqual(G.GR.judged_hips_frames(curve, {"unit": "u", "groundContact": {"exempt": "why"}}), {})

    def test_band_keeps_the_hips_within_the_allowance(self):
        H, allow, uz, s = 2.0, 0.05, 0.985, 50.0
        lo, hi = G.GR.refine_dy_band(1.15, 1.0, H, allow, uz, s)
        for dy, bound in ((lo, -allow * H), (hi, allow * H)):
            self.assertAlmostEqual(1.15 + uz * dy / s - 1.0, bound)
        self.assertLess(hi, 0)   # a pose already 0.15 above Idle's Hips may only be pulled down by the refine
        with self.assertRaises(SystemExit):
            G.GR.refine_dy_band(1.0, 1.0, H, allow, 0.0, s)


if __name__ == "__main__":
    unittest.main()
