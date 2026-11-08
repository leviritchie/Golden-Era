"""grounding.offsets' joint entry: where lifting the entry onto the floor would step the Hips out of the gate's band,
the entry lands inside both gate bands (feet and Hips) instead; a clip already inside is unchanged; bands that do not
meet leave the rule as it was, for the gate to refuse.

    python -m unittest tools/homm3_def_retarget_delivery/test_joint_entry.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "homm3_def_retarget"))
import grounding as GR  # noqa: E402

TOL = GR.GROUND_TOL


def gate(lows, s, d, hips0, allow):
    """ground_check's three first-frame / sink judgements on the offset clip, measured at its 4-decimal rounding."""
    L = np.round(np.asarray(lows) + s, 4)
    d = np.asarray(d, float)
    ok_sink = L.min() >= min(0.0, d.min()) - TOL
    ok_entry = min(0.0, d[0]) - TOL <= L[0] <= max(0.0, d[0]) + TOL
    ok_hips = abs(round(hips0 + s[0], 4)) <= allow
    return ok_sink, ok_entry, ok_hips


class JointEntry(unittest.TestCase):
    def test_ghost_dragon_mouseover_passes_both_bands(self):
        # 2026-09-27 h3_ghost_dragon Mouseover: feet enter 0.0489 under the floor with the Hips exactly at Idle
        lows = [-0.0489, -0.0438, -0.0235, -0.037, -0.03, -0.02, -0.01, 0.0, 0.0]
        d = np.zeros(9)
        old, _ = GR.offsets(lows, d, False, None)
        self.assertEqual(gate(lows, old, d, 0.0, 0.0488), (True, True, False))
        s, info = GR.offsets(lows, d, False, None, hips0=0.0, allow_hips=0.0488)
        self.assertEqual(gate(lows, s, d, 0.0, 0.0488), (True, True, True))
        self.assertIn("from", info["entryJoint"])

    def test_ghost_dragon_movestart_passes_both_bands(self):
        # Hips already +0.0441 before ground, feet at -0.0587; the full lift stepped the Hips to +0.103 (allow 0.0665)
        lows, d = [-0.0587, -0.0718, 0.0441], np.array([0.0088, 0.0, 0.0])
        s, info = GR.offsets(lows, d, False, None, hips0=0.0441, allow_hips=0.0665)
        self.assertEqual(gate(lows, s, d, 0.0441, 0.0665), (True, True, True))
        self.assertTrue(0.0187 < s[0] < 0.0224)

    def test_a_clip_inside_the_hips_band_is_unchanged(self):
        lows, d = [-0.03, -0.01, 0.0, -0.02], np.zeros(4)
        old, oi = GR.offsets(lows, d, False, None)
        new, ni = GR.offsets(lows, d, False, None, hips0=0.005, allow_hips=0.04)
        np.testing.assert_array_equal(old, new)
        self.assertEqual(oi, ni)

    def test_bands_that_do_not_meet_leave_the_rule_for_the_gate_to_refuse(self):
        # stormbird-like Hitted: the feet need +0.064 at least, the Hips allow +0.04 at most
        lows, d = [-0.104, -0.05, 0.0], np.zeros(3)
        old, _ = GR.offsets(lows, d, False, None)
        new, info = GR.offsets(lows, d, False, None, hips0=0.0, allow_hips=0.04)
        np.testing.assert_array_equal(old, new)
        self.assertTrue(info["entryJoint"].startswith("infeasible"))
        self.assertFalse(gate(lows, new, d, 0.0, 0.04)[2])

    def test_the_clamp_does_not_lift_the_entry_back_out(self):
        lows, d = [-0.06, -0.06, -0.06, -0.06, -0.06, -0.06], np.zeros(6)
        s, info = GR.offsets(lows, d, False, None, hips0=0.0, allow_hips=0.04)
        self.assertLessEqual(abs(s[0]), 0.04)
        self.assertGreater(info["clampRelaxed"], 0)
        self.assertEqual(gate(lows, s, d, 0.0, 0.04), (True, True, True))
        np.testing.assert_allclose(np.asarray(lows)[2:] + s[2:], 0.0, atol=1e-9)   # relaxation eased out: floored

    def test_closed_loop_holds_the_joint_entry(self):
        lows, d = [-0.05, -0.02, 0.0, -0.05], np.zeros(4)
        s, info = GR.offsets(lows, d, False, None, loop=True, hips0=0.0, allow_hips=0.04)
        self.assertAlmostEqual(s[0], s[-1])
        self.assertEqual(gate(lows, s, d, 0.0, 0.04), (True, True, True))


class HeldLoopEntry(unittest.TestCase):
    """A closed loop's held pull-down sinks no frame, so the clamp has nothing to lift back (h3_amalek Move)."""

    def test_an_airborne_first_frame_over_planted_stance_frames_is_left_alone(self):
        lows = [0.024, 0.03, 0.01, 0.0, 0.0, 0.02, 0.035, 0.024]      # stride-planted: stance soles on the floor
        s, info = GR.offsets(lows, np.zeros(8), False, None, loop=True)
        self.assertTrue(np.allclose(s, 0.0))
        self.assertEqual(info["entryLimited"]["from"], -0.024)
        self.assertNotIn("clampLiftMax", info)

    def test_the_pull_down_stops_at_the_frame_nearest_its_floor(self):
        lows = [0.05, 0.06, 0.02, 0.03, 0.05]
        s, info = GR.offsets(lows, np.zeros(5), False, None, loop=True)
        self.assertTrue(np.allclose(s, -0.02))                        # constant: the loop stays closed
        self.assertAlmostEqual(min(np.add(lows, s)), 0.0)

    def test_a_loop_that_sinks_nowhere_takes_the_full_pull_down_and_an_eased_entry_is_unchanged(self):
        lows = [0.03, 0.05, 0.04, 0.03]
        s, info = GR.offsets(lows, np.zeros(4), False, None, loop=True)
        self.assertTrue(np.allclose(s, -0.03))
        self.assertNotIn("entryLimited", info)
        lows = [0.024, 0.0, 0.0, 0.02, 0.0, 0.0]
        s, info = GR.offsets(lows, np.zeros(6), False, None, loop=False)
        self.assertAlmostEqual(s[0], -0.024)
        self.assertNotIn("entryLimited", info)

    def test_a_bobbing_flier_loop_is_pulled_down_to_the_entry_band_and_only_its_sinking_frames_lift(self):
        # h3_spectral_dragon Move (2026-09-28): the loop touches its floor mid-cycle only; DEF enters at +0.257
        lows = [0.3852, 0.3096, 0.0725, 0.0331, 0.0085, 0.0183, 0.3852]
        d = [0.257, 0.23, 0.31, 0.035, 0.0, 0.283, 0.257]
        s, info = GR.offsets(lows, np.asarray(d), False, None, loop=True, hips0=0.4897, allow_hips=0.6064)
        first = round(lows[0] + s[0], 4)
        self.assertLessEqual(first, 0.257 + GR.GROUND_TOL)                 # inside the gate's entry band
        self.assertGreaterEqual(first, 0.257 + GR.GROUND_TOL - 2 * GR.GATE_RES)   # and no deeper than it needs
        self.assertEqual(info["entryLimited"]["by"], "held pull-down to the entry band's top")
        self.assertAlmostEqual(s[0], s[-1])                               # the loop stays closed
        self.assertGreaterEqual(min(np.round(np.add(lows, s) - np.minimum(0.0, d), 6)), 0.0)   # no frame sinks

    def test_a_walker_whose_first_frame_is_in_the_band_keeps_the_floor_limit(self):
        # h3_amalek-like: the band bound is looser than the floor bound, so 14c27b1d78's offsets are unchanged
        lows = [0.024, 0.03, 0.01, 0.0, 0.0, 0.02, 0.035, 0.024]
        s, info = GR.offsets(lows, np.zeros(8), False, None, loop=True)
        self.assertTrue(np.array_equal(s, np.zeros(8)))
        self.assertEqual(info["entryLimited"]["by"], "held pull-down keeps every frame on its floor")

    def test_where_the_gate_judges_the_hips_the_pull_down_enters_the_hips_band_too(self):
        # h3_horned_demon-like: the feet band's top alone leaves the Hips above their allowance at entry
        lows = [0.30, 0.25, 0.05, 0.0, 0.1, 0.30]
        s, info = GR.offsets(lows, np.zeros(6), False, None, loop=True, hips0=0.40, allow_hips=0.10)
        self.assertLessEqual(abs(round(0.40 + s[0], 4)), 0.10)
        self.assertLessEqual(round(lows[0] + s[0], 4), GR.GROUND_TOL)
        self.assertAlmostEqual(s[0], s[-1])


if __name__ == "__main__":
    unittest.main()
