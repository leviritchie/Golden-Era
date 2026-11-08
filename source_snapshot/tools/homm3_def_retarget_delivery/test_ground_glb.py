"""The ground stage writes only the body's vertical translation and leaves every other sampler as it was.

    python -m unittest tools/homm3_def_retarget_delivery/test_ground_glb.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ground_glb as GG  # noqa: E402
from test_ground_check import fixture  # noqa: E402


def skinned(**kw):
    g = fixture(**kw)
    g.json["skins"] = [{"joints": [0, 1, 2]}]
    g.json["nodes"].append({"name": "body", "mesh": 0, "skin": 0})
    return g


class GroundStage(unittest.TestCase):
    def test_closed_loop_entry_is_held_so_the_loop_stays_closed(self):
        lows = [0.0187, 0.01, -0.01, 0.005, 0.0187]
        d = [0.0161, 0.0161, -0.0122, 0.0, 0.0161]
        s, info = GG.GR.offsets(lows, d, False, None, loop=True)
        self.assertAlmostEqual(s[0], s[-1])
        # the held pull-down (-0.0026 to the DEF's first-frame band) stops where frame 2 meets its own floor
        self.assertAlmostEqual(info["entry"], -0.0022)
        self.assertEqual(info["entryLimited"]["from"], -0.0026)
        eased, _ = GG.GR.offsets(lows, d, False, None)
        self.assertNotAlmostEqual(eased[0], eased[-1])

    def test_body_nodes_are_roots_joint_children(self):
        self.assertEqual(GG.body_nodes(skinned()), (0, [1]))
        g = skinned()
        g.json["nodes"][0]["name"] = g.names[0] = "Armature"
        with self.assertRaisesRegex(SystemExit, "one 'Root'"):
            GG.body_nodes(g)

    def test_offsets_move_only_the_body_translation(self):
        g = skinned()
        before = GG.channel_snapshot(g)
        times = np.array([0.0, 0.25, 0.5, 1.0])
        s = np.array([0.0, 0.1, 0.2, 0.0])
        changed = GG.apply_offsets(g, {"Move": (times, s, {})}, 2.0)
        self.assertEqual(changed, ["Unit_Move"])
        after = GG.channel_snapshot(g)
        self.assertEqual(GG.preserved_errors(before, after, {("Unit_Move", 1)}), [])
        _, t, v = after[("Unit_Move", 1, "translation")]
        np.testing.assert_allclose(t[:, 0], times)
        # the original Hips keys (0, 0.1, 0 at 0 / 0.5 / 1) sampled on the grid, plus s * H on +Y only
        np.testing.assert_allclose(v, [[0, 0, 0], [0, 0.05 + 0.2, 0], [0, 0.1 + 0.4, 0], [0, 0, 0]], atol=1e-6)
        # zero offsets leave a clip byte-for-byte alone
        self.assertEqual(GG.apply_offsets(g, {"Idle": (np.array([0.0, 1.0]), np.zeros(2), {})}, 2.0), [])

    def test_preserved_errors_catch_a_foreign_edit(self):
        g = skinned()
        before = GG.channel_snapshot(g)
        GG.apply_offsets(g, {"Move": (np.array([0.0, 1.0]), np.array([0.1, 0.1]), {})}, 1.0)
        after = GG.channel_snapshot(g)
        self.assertTrue(GG.preserved_errors(before, after, set()))   # Hips was not declared as rewritten

    def test_step_body_translation_stays_step(self):
        g = skinned()
        g.json["animations"][1]["samplers"][0]["interpolation"] = "STEP"
        GG.apply_offsets(g, {"Move": (np.array([0.0, 0.5, 1.0]), np.array([0.1, 0.1, 0.1]), {})}, 1.0)
        it, t, v = GG.channel_snapshot(g)[("Unit_Move", 1, "translation")]
        self.assertEqual(it, "STEP")
        np.testing.assert_allclose(v, [[0, 0.1, 0], [0, 0.2, 0], [0, 0.1, 0]], atol=1e-6)
        g = skinned()
        g.json["animations"][1]["samplers"][0]["interpolation"] = "CUBICSPLINE"
        with self.assertRaisesRegex(SystemExit, "CUBICSPLINE"):
            GG.apply_offsets(g, {"Move": (np.array([0.0, 1.0]), np.array([0.1, 0.1]), {})}, 1.0)

    def test_a_constant_step_track_under_a_varying_offset_is_written_linear(self):
        # 2026-09-28 hota_cove_oceanid: the held two-key STEP Hips translation of Unit_Idle became a 10-key STEP
        g = skinned()
        g.json["animations"][0]["samplers"][0]["interpolation"] = "STEP"      # Unit_Idle Hips: two equal keys
        GG.apply_offsets(g, {"Idle": (np.array([0.0, 0.5, 1.0]), np.array([0.0, 0.05, 0.0]), {})}, 1.0)
        it, t, v = GG.channel_snapshot(g)[("Unit_Idle", 1, "translation")]
        self.assertEqual(it, "LINEAR")
        np.testing.assert_allclose(v[:, 1], [0.0, 0.05, 0.0], atol=1e-6)
        g = skinned()                                                          # a constant offset keeps it STEP
        g.json["animations"][0]["samplers"][0]["interpolation"] = "STEP"
        GG.apply_offsets(g, {"Idle": (np.array([0.0, 1.0]), np.array([0.05, 0.05]), {})}, 1.0)
        self.assertEqual(GG.channel_snapshot(g)[("Unit_Idle", 1, "translation")][0], "STEP")

    def test_def_curve_on_grid(self):
        t = np.array([0.0, 0.5, 1.0])
        np.testing.assert_allclose(GG.def_on_grid([0.0, -0.2, 0.0], t, False), [0.0, -0.2, 0.0])
        # a closed loop's last key is DEF frame 0 again
        np.testing.assert_allclose(GG.def_on_grid([0.1, -0.1], t, True), [0.1, -0.1, 0.1])
        np.testing.assert_allclose(GG.def_on_grid([None, 0.3], t, False), [0.3, 0.3, 0.3])

    def test_stamp_errors(self):
        self.assertTrue(GG.stamp_errors({}))
        ok = {"asset": {"extras": {GG.STAMP: {"schema": GG.SCHEMA, "sourceGlbSha256": "a" * 64, "clips": {"Idle": {}}}}}}
        self.assertEqual(GG.stamp_errors(ok), [])
        ok["asset"]["extras"][GG.STAMP]["schema"] = "old"
        self.assertTrue(GG.stamp_errors(ok))


class PlantedSoleLift(unittest.TestCase):
    """P2 (user-approved 2026-09-28): the ground stage refuses a stride-stamped Move whose offsets lift a planted sole
    off the floor at a stance key -- the clamp stood other geometry (hota_bulwark_shaman's robe and shin) on the floor."""

    def run_rule(self, sole_above_low, s):
        from types import SimpleNamespace
        from unittest.mock import patch
        n = len(s)
        g = SimpleNamespace(json={"asset": {"extras": {GG.SM.STAMP: {"clip": "Unit_Move"}}}}, names=["Root", "LeftFoot", "RightLeg"],
                            world=lambda local: None, sample_local=lambda clip, t: None)
        heights = np.zeros((n, 3))                     # vertex 0: the plant's sole, vertex 1-2: RightLeg-owned robe
        heights[:, 0] = sole_above_low
        body = {"J": np.array([[1], [2], [2]]), "W": np.ones((3, 1))}
        with patch.object(GG.SM, "skin_body", lambda g: body), patch.object(GG.SM, "skin_heights", lambda b, m, f: heights),                 patch.object(GG.SM, "chains_of", lambda g: [{"name": "LeftUpLeg"}]),                 patch.object(GG.SM, "planted_chains", lambda st: ["LeftUpLeg"]),                 patch.object(GG.SM, "sole_of", lambda g, b, c: (1, np.array([True, False, False]))):
            return GG.planted_sole_lift_errors(g, np.arange(n) / 10, np.zeros(n), np.asarray(s), 1.0)

    def test_a_clamp_that_stands_the_robe_on_the_floor_and_floats_the_plant_refuses(self):
        # the robe reaches 0.13 below the sole: lows are the robe's, the clamp lifts 0.13, the sole ends at +0.13
        bad = self.run_rule([0.13, 0.13, 0.0], [0.13, 0.13, 0.0])
        self.assertEqual(len(bad), 0)                  # the sole was 0.13 above the floor before: not a stance key
        bad = self.run_rule([0.0, 0.13, 0.0], [0.13, 0.13, 0.0])
        self.assertEqual(len(bad), 1)
        self.assertIn("RightLeg-owned", bad[0])
        self.assertIn("key 0", bad[0])

    def test_a_lift_within_the_tolerance_and_an_unstamped_glb_pass(self):
        self.assertEqual(self.run_rule([0.0, 0.0, 0.0], [0.03, 0.02, 0.0]), [])
        from types import SimpleNamespace
        g = SimpleNamespace(json={"asset": {"extras": {}}})
        self.assertEqual(GG.planted_sole_lift_errors(g, np.zeros(3), np.zeros(3), np.full(3, 0.5), 1.0), [])


if __name__ == "__main__":
    unittest.main()
