#!/usr/bin/env python3
"""Unit tests: body_v1 residual depth and the seams_v1 building seam gate (town_full3d_building_seams,
validate_town_scene3d_contract building_seam_*; docs/homm3_town_building_seams.md).

    python tools/homm3_town_scene_meshes/test_town_building_seams.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import town_full3d_building_seams as SEAMS  # noqa: E402
import validate_town_scene3d_contract as V  # noqa: E402


class HarmonicFill(unittest.TestCase):
    def test_known_values_are_kept_and_a_constant_boundary_fills_constant(self):
        val = np.zeros((20, 30)); known = np.zeros_like(val, bool)
        known[:, 0] = True; val[:, 0] = 0.3
        u = SEAMS.harmonic_fill(val, known)
        np.testing.assert_allclose(u, 0.3, atol=1e-9)

    def test_screened_fill_decays_away_from_the_boundary(self):
        val = np.zeros((5, 200)); known = np.zeros_like(val, bool)
        known[:, 0] = True; val[:, 0] = 1.0
        u = SEAMS.harmonic_fill(val, known, decay_px=10.0)
        row = u[2]
        self.assertTrue(np.all(np.diff(row[1:]) < 0))
        self.assertAlmostEqual(row[10] / row[1], np.exp(-9 / 10.0), delta=0.05)
        self.assertLess(row[100], 1e-3)


def synthetic_layer(h=60, w=80, zc=100.0, body_z=90.0):
    """A sprite grid: upright everywhere, a ground band in the bottom 10 rows; the body covers a block whose rest
    front sits 10% in front of contact_v1's own depth there."""
    z = np.full((h, w), zc)
    ground = np.zeros((h, w), bool); ground[h - 10:] = True
    ld = {"z": z, "mask": np.ones((h, w), bool), "ground": ground}
    zb = np.full((h, w), np.inf)
    zb[10:40, 20:50] = body_z
    return ld, zb


class BodyAnchor(unittest.TestCase):
    def test_residual_meets_the_body_at_the_seam(self):
        ld, zb = synthetic_layer()
        out, rep = SEAMS.body_anchor(ld, zb)
        z = out["z"]
        np.testing.assert_allclose(z[10:40, 20:50], 90.0 * SEAMS.SEAM_BEHIND, rtol=1e-9)
        # the px just outside the body continue its depth (contact_v1 alone would leave a 10% step)
        for y, x in ((25, 19), (25, 50), (9, 35), (40, 35)):
            self.assertLess(abs(z[y, x] / (90.0 * SEAMS.SEAM_BEHIND) - 1), 0.01, (y, x, z[y, x]))
        self.assertTrue(out["mask"].all())
        self.assertEqual(rep["rule"], SEAMS.RESIDUAL_RULE)

    def test_the_field_is_continuous_and_returns_to_contact_v1_far_away(self):
        ld, zb = synthetic_layer(w=300)
        z = SEAMS.body_anchor(ld, zb)[0]["z"]
        step = np.abs(np.diff(np.log(z), axis=1)).max()
        self.assertLess(step, 0.02)                      # no step anywhere: the residual is one surface with the body
        self.assertAlmostEqual(z[25, 299] / 100.0, 1.0, delta=0.002)

    def test_far_ground_keeps_the_floor_and_near_ground_moves_with_the_body(self):
        ld, zb = synthetic_layer(h=80)
        zb[:] = np.inf; zb[50:70, 20:50] = 90.0          # the body's foot stands in the ground band's top rows
        ld["ground"][:] = False; ld["ground"][60:] = True
        z = SEAMS.body_anchor(ld, zb, floor_px=8.0)[0]["z"]
        self.assertEqual(z[79, 79], 100.0)               # > floor_px from the body: contact_v1's floor
        self.assertLess(z[71, 35], 100.0 * 0.95)          # beside the foot: with the body, not stepped off it

    def test_no_body_cover_fails_closed(self):
        ld, zb = synthetic_layer()
        zb[:] = np.inf
        with self.assertRaises(SystemExit):
            SEAMS.body_anchor(ld, zb)


def seam_arrays(a, b, fill, roles=None, layer=None):
    """seam_* arrays in the prefab frame: rest camera at the origin looking +z, proof poses translated sideways / up."""
    n = len(a)
    poses = np.array([[-1.0, 0, 0], [1.0, 0, 0], [-4.0, 0, 0], [4.0, 0, 0], [0, 3.0, 0]])
    return {"seam_a": np.asarray(a, np.float32), "seam_b": np.asarray(b, np.float32),
            "seam_layer": np.zeros(n, np.int32) if layer is None else np.asarray(layer, np.int32),
            "seam_roles": np.tile([0, 2], (n, 1)).astype(np.int8) if roles is None else np.asarray(roles, np.int8),
            "seam_fill": np.asarray(fill, np.float32), "seam_layers": np.array(["tbxxhall"]),
            "seam_pose_names": np.array(list(V.BUILDING_SEAM_POSES)), "seam_pose_pos": poses,
            "seam_pose_fwd": np.tile([0, 0, 1.0], (5, 1)), "seam_pose_up": np.tile([0, 1.0, 0], (5, 1)),
            "seam_pose_right": np.tile([1.0, 0, 0], (5, 1)), "seam_fov": np.float64(30.0),
            "seam_frame": np.array([1920, 1080], np.int32)}


def pairs(n, depth_b):
    """n rest-adjacent pairs at 50 m: side a, and side b one px to the right at depth_b (on b's own ray)."""
    t = np.tan(np.radians(15.0)); px = 2 * t / 1080      # one 1080p px at unit depth
    x = np.linspace(-5, 5, n)
    a = np.stack([x, np.zeros(n), np.full(n, 50.0)], 1)
    b = np.stack([(x / 50.0 + px) * depth_b, np.zeros(n), np.full(n, depth_b)], 1)
    return a, b


class SeamGate(unittest.TestCase):
    def test_a_glued_seam_does_not_split(self):
        a, b = pairs(50, 50.0)
        d = seam_arrays(a, b, np.full((50, 5), np.inf))
        split, worst = V.building_seam_split(d)
        self.assertFalse(split.any())
        self.assertLess(worst.max(), 0.1)

    def test_a_depth_split_seam_with_nothing_behind_splits(self):
        a, b = pairs(50, 60.0)                           # the residual 20% behind its body: opens on a pan
        d = seam_arrays(a, b, np.full((50, 5), np.inf))
        split, worst = V.building_seam_split(d)
        self.assertTrue(split.all())
        self.assertGreater(worst.min(), V.BUILDING_SEAM_OPEN_PX)
        st = V.building_seam_stats(d)["tbxxhall"]
        self.assertEqual((st["residualPairs"], st["residualSplit"]), (50, 50))

    def test_an_opening_the_building_fills_is_not_a_split(self):
        a, b = pairs(50, 60.0)
        d = seam_arrays(a, b, np.full((50, 5), 55.0))     # the layer itself draws in between (a glue surface)
        self.assertFalse(V.building_seam_split(d)[0].any())
        d = seam_arrays(a, b, np.full((50, 5), 60.0 * V.BUILDING_SEAM_HOLE_RATIO * 1.05))   # only the far backdrop
        self.assertTrue(V.building_seam_split(d)[0].all())

    def test_meshy_meshy_and_solid_pairs_are_not_gated(self):
        a, b = pairs(50, 60.0)
        d = seam_arrays(a, b, np.full((50, 5), np.inf), roles=np.tile([1, 1], (50, 1)))
        st = V.building_seam_stats(d)["tbxxhall"]
        self.assertEqual((st["residualPairs"], st["solidSplit"]), (0, 50))

    def block(self, d):
        return {"seams": {"schema": V.BUILDING_SEAM_SCHEMA, "openPx": V.BUILDING_SEAM_OPEN_PX,
                          "splitShareMax": V.BUILDING_SEAM_SPLIT_MAX, "splitMinPairs": V.BUILDING_SEAM_SPLIT_MIN_PAIRS,
                          "holeRatio": V.BUILDING_SEAM_HOLE_RATIO, "layers": V.building_seam_stats(d)}}

    def test_failures(self):
        a, b = pairs(50, 50.0)
        ok = seam_arrays(a, b, np.full((50, 5), np.inf))
        self.assertEqual(V.building_seam_failures(self.block(ok), ok), [])
        a, b = pairs(50, 60.0)
        bad = seam_arrays(a, b, np.full((50, 5), np.inf))
        f = V.building_seam_failures(self.block(bad), bad)
        self.assertTrue(any("building seam split" in x for x in f), f)
        # a declared count that is not the re-measure
        bl = self.block(bad); bl["seams"]["layers"]["tbxxhall"]["residualSplit"] = 0
        self.assertTrue(any("declared 0 split pairs" in x for x in V.building_seam_failures(bl, bad)))
        # a loosened threshold
        bl = self.block(ok); bl["seams"]["openPx"] = 50.0
        self.assertTrue(any("openPx" in x for x in V.building_seam_failures(bl, ok)))
        # arrays without the block, or the block without the hole samples
        self.assertTrue(V.building_seam_failures({}, ok))
        nofill = {k: v for k, v in ok.items() if k != "seam_fill"}
        self.assertTrue(V.building_seam_failures(self.block(ok), nofill))
        # a pre-seams build: neither
        self.assertEqual(V.building_seam_failures({}, {}), [])

    def test_the_stage_tool_and_the_validator_share_the_contract(self):
        self.assertEqual(SEAMS.SEAM_POSES, V.BUILDING_SEAM_POSES)
        self.assertEqual(SEAMS.SEAM_OPEN_PX, V.BUILDING_SEAM_OPEN_PX)
        self.assertEqual(SEAMS.SEAM_SCHEMA, V.BUILDING_SEAM_SCHEMA)
        self.assertIsNone(SEAMS.RESIDUAL_CUT_RATIO)


class SeamOffFrame(unittest.TestCase):
    """seams_v2: a pose counts only where the pair's midpoint is on screen (docs/homm3_town_building_seams.md)."""

    def offset(self, a, b, x0):
        """The pairs moved to x0 m (+-0.2) at 50 m: the frame's half width there is 23.8 m, the poses sit at x -1, +1,
        -4, +4 and y +3, so x0 -23.5 is on screen at rest and at the -x / high poses and off screen at the +x ones."""
        a = a.copy(); b = b.copy()
        dx = x0 + np.linspace(-0.2, 0.2, len(a)) - a[:, 0]
        a[:, 0] += dx; b[:, 0] += dx * b[:, 2] / a[:, 2]
        return a, b

    def test_a_pair_off_screen_at_a_pose_does_not_count_there(self):
        # at the rest frame's left edge the +x poses push it off screen; it is on screen at the -x poses and at
        # sweep_high, where it opens but the layer fills the gap
        a, b = self.offset(*pairs(50, 60.0), -23.5)
        fill = np.full((50, 5), 55.0); fill[:, [1, 3]] = np.inf            # nothing sampled off screen
        on = V.building_seam_onscreen(seam_arrays(a, b, fill))
        self.assertFalse(on[:, [1, 3]].any()); self.assertTrue(on[:, [0, 2, 4]].all())
        d = seam_arrays(a, b, fill)
        self.assertFalse(V.building_seam_split(d)[0].any())
        self.assertTrue(V.building_seam_split(d, onscreen=False)[0].all())  # seams_v1 counted the off-screen poses
        st = V.building_seam_stats(d)["tbxxhall"]
        self.assertEqual((st["residualSplit"], st["residualUnmeasured"]), (0, 0))

    def test_an_on_screen_see_through_still_splits_at_every_on_screen_pose(self):
        a, b = self.offset(*pairs(50, 60.0), -23.5)
        fill = np.full((50, 5), np.inf)                                      # see-through wherever it is seen
        d = seam_arrays(a, b, fill)
        split, worst = V.building_seam_split(d)
        self.assertTrue(split.all())
        self.assertEqual(V.building_seam_stats(d)["tbxxhall"]["residualSplit"], 50)

    def test_a_pair_on_screen_at_no_pose_is_unmeasured_not_passed_silently(self):
        a, b = self.offset(*pairs(50, 60.0), 200.0)                          # far right of every pose frame
        d = seam_arrays(a, b, np.full((50, 5), np.inf))
        self.assertFalse(V.building_seam_onscreen(d).any())
        st = V.building_seam_stats(d)["tbxxhall"]
        self.assertEqual((st["residualPairs"], st["residualSplit"], st["residualUnmeasured"]), (50, 0, 50))
        sm = {"schema": V.BUILDING_SEAM_SCHEMA, "layers": {"tbxxhall": st}}
        self.assertEqual(V.building_seam_unmeasured_flags(sm), [" UNMEASURED-SEAMS:tbxxhall=50/50"])
        bl = SeamGate.block(None, d)
        bl["seams"]["layers"]["tbxxhall"]["residualUnmeasured"] = 0
        self.assertTrue(any("unmeasured" in x for x in V.building_seam_failures(bl, d)))

    def test_a_seams_v1_block_is_measured_by_its_own_rule(self):
        a, b = self.offset(*pairs(50, 60.0), -23.5)
        fill = np.full((50, 5), 55.0); fill[:, [1, 3]] = np.inf
        d = seam_arrays(a, b, fill)
        st1 = V.building_seam_stats(d, onscreen=False)
        self.assertNotIn("residualUnmeasured", st1["tbxxhall"])
        bl = {"seams": {"schema": "seams_v1", "openPx": V.BUILDING_SEAM_OPEN_PX,
                        "splitShareMax": V.BUILDING_SEAM_SPLIT_MAX, "splitMinPairs": V.BUILDING_SEAM_SPLIT_MIN_PAIRS,
                        "holeRatio": V.BUILDING_SEAM_HOLE_RATIO, "layers": st1}}
        f = V.building_seam_failures(bl, d)
        self.assertFalse(any("declared" in x for x in f), f)
        self.assertTrue(any("building seam split" in x for x in f), f)
        bl["seams"]["schema"] = "seams_v0"
        self.assertTrue(any("schema" in x for x in V.building_seam_failures(bl, d)))


class ResidualRule(unittest.TestCase):
    def test_pin_selects_the_rule_and_defaults_to_body_v1(self):
        import os
        os.environ.pop("SEAM_RULE", None)
        self.assertEqual(SEAMS.residual_rule(None), "body_v1")
        self.assertEqual(SEAMS.residual_rule({"mode": "contact_v1"}), "body_v1")
        self.assertEqual(SEAMS.residual_rule({"mode": "contact_v1", "residual": "contact_v1"}), "contact_v1")
        self.assertEqual(SEAMS.residual_rule({"mode": "contact_v1", "residual": "body_v2"}), "body_v2")
        with self.assertRaises(SystemExit):
            SEAMS.residual_rule({"residual": "legacy"})

    def test_body_v1_stays_the_unrefined_rule(self):
        self.assertEqual(SEAMS.RESIDUAL_RULE, "body_v1")
        self.assertEqual(SEAMS.BODY_RULE_PARAMS["body_v1"], {"sub": 1, "snapPx": 0.0, "snapSup": 1, "subdiv": 0})
        self.assertEqual(set(SEAMS.BODY_RULE_PARAMS), {r for r in SEAMS.RESIDUAL_RULES if r.startswith("body_")})

    def test_the_retired_env_switch_fails_closed(self):
        import os
        os.environ["SEAM_RULE"] = "off"
        try:
            with self.assertRaises(SystemExit):
                SEAMS.residual_rule(None)
        finally:
            os.environ.pop("SEAM_RULE", None)

    def test_the_label_is_the_rule_the_stage_applied(self):
        b = lambda r: {"contactDepth": {"meshy": True, "residualDepth": {"rule": r}}}
        solid = {"contactDepth": {"meshy": False}}
        self.assertEqual(SEAMS.applied_rule({"buildings": {"a": b("contact_v1"), "s": solid}}), "contact_v1")
        self.assertEqual(SEAMS.applied_rule({"buildings": {"a": b("body_v1")}}), "body_v1")
        self.assertIsNone(SEAMS.applied_rule({"buildings": {"s": solid}}))
        with self.assertRaises(SystemExit):
            SEAMS.applied_rule({"buildings": {"a": b("body_v1"), "c": b("contact_v1")}})


class Subdivide(unittest.TestCase):
    def grid(self):
        v = np.array([[x, y, 0.0] for y in range(3) for x in range(3)])
        t = []
        for y in range(2):
            for x in range(2):
                a = y * 3 + x
                t += [[a, a + 1, a + 4], [a, a + 4, a + 3]]
        return v, np.tile([0.0, 0.0, 1.0], (9, 1)), v[:, :2] / 2, [np.array(t[:4]), np.array(t[4:])]

    def test_crack_free_area_and_winding_kept(self):
        v, n, uv, subs = self.grid()
        for lev in (1, 2):
            V, N, U, S = SEAMS.subdivide(v, n, uv, subs, lev)
            F = np.concatenate(S)
            self.assertEqual([len(s_) for s_ in S], [4 * 4 ** lev, 4 * 4 ** lev])
            e = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), 1)
            _, c = np.unique(e, axis=0, return_counts=True)
            self.assertLessEqual(c.max(), 2)
            area = 0.5 * np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])[:, 2]
            self.assertTrue((area > 0).all())
            self.assertAlmostEqual(float(area.sum()), 4.0)
            np.testing.assert_allclose(U, V[:, :2] / 2)            # UV stays the linear map of position
            np.testing.assert_allclose(np.linalg.norm(N, axis=1), 1.0)


if __name__ == "__main__":
    unittest.main()
