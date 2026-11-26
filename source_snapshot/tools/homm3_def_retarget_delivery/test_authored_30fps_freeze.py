"""Fail-closed freeze-gate tests for authored 30fps (unit_rebuild) clips.

    python -m unittest tools/homm3_def_retarget_delivery/test_authored_30fps_freeze.py
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import flyer_articulation as F  # noqa: E402


def _make_clip(angles_rad: list[float], fps: float = 30.0):
    times = np.arange(len(angles_rad), dtype=float) / fps
    quats = np.array([[0.0, math.sin(a * 0.5), 0.0, math.cos(a * 0.5)] for a in angles_rad], dtype=float)
    vals = {0: times[:, None], 1: quats}
    acc = lambda i: vals[i]  # noqa: E731
    anim = {
        "name": "Unit_Idle",
        "samplers": [{"input": 0, "output": 1}],
        "channels": [{"sampler": 0, "target": {"node": 1, "path": "rotation"}}],
    }
    return anim, acc


class Authored30fpsFreezeTest(unittest.TestCase):
    def test_unstamped_30fps_fails_closed(self):
        anim, acc = _make_clip([0.05 * i for i in range(31)])
        js = {"asset": {"version": "2.0"}, "nodes": [{}, {"rotation": [0, 0, 0, 1]}]}
        m = F.freeze_metrics(js, acc, anim, {1: 0}, 1.0)
        self.assertIn("freezeResampled", m)
        self.assertTrue(any("not measured" in b for b in F.freeze_gate({"Unit_Idle": m})))

    def test_stamped_moving_30fps_passes(self):
        anim, acc = _make_clip([0.05 * math.sin(i * 0.25) + 0.02 * i for i in range(31)])
        js = {
            "asset": {
                "version": "2.0",
                "extras": {F.AUTHORED_30FPS_STAMP: {"schema": F.AUTHORED_30FPS_SCHEMA, "fps": 30.0}},
            },
            "nodes": [{}, {"rotation": [0, 0, 0, 1]}],
        }
        m = F.freeze_metrics(js, acc, anim, {1: 0}, 1.0)
        self.assertNotIn("freezeResampled", m)
        self.assertNotIn("freezeEvidence", m)
        self.assertLess(m["freezeRun"], F.FREEZE_RUN_MAX)
        self.assertEqual(F.freeze_gate({"Unit_Idle": m}), [])

    def test_stamped_030s_hold_fails_closed(self):
        # 10 frames moving, 10 frames frozen (0.30s at 30fps -> >= 3 steps at 12Hz), 11 frames moving
        angles = [0.05 * i for i in range(10)] + [0.45] * 10 + [0.45 + 0.05 * i for i in range(11)]
        anim, acc = _make_clip(angles)
        js = {
            "asset": {
                "version": "2.0",
                "extras": {F.AUTHORED_30FPS_STAMP: {"schema": F.AUTHORED_30FPS_SCHEMA, "fps": 30.0}},
            },
            "nodes": [{}, {"rotation": [0, 0, 0, 1]}],
        }
        m = F.freeze_metrics(js, acc, anim, {1: 0}, 1.0)
        self.assertGreaterEqual(m["freezeRun"], F.FREEZE_RUN_MAX)
        bad = F.freeze_gate({"Unit_Idle": m})
        self.assertEqual(len(bad), 1)
        self.assertIn("holds one pose", bad[0])

    def test_invalid_stamp_fails_closed(self):
        anim, acc = _make_clip([0.05 * i for i in range(31)])
        for bad_extra in (
            {"schema": "wrong.v1", "fps": 30.0},
            {"schema": F.AUTHORED_30FPS_SCHEMA, "fps": 24.0},
            "not-a-dict",
        ):
            js = {
                "asset": {"version": "2.0", "extras": {F.AUTHORED_30FPS_STAMP: bad_extra}},
                "nodes": [{}, {"rotation": [0, 0, 0, 1]}],
            }
            m = F.freeze_metrics(js, acc, anim, {1: 0}, 1.0)
            self.assertIn("freezeEvidence", m)


if __name__ == "__main__":
    unittest.main()
