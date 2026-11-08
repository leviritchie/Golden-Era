#!/usr/bin/env python3
"""contact_v1 building depth: the thickness prior (contact_sigma), the upright / ground split (ground_split) and the
streak measure the buildingDepth contract judges (docs/homm3_town_building_contact_depth.md). Synthetic arrays,
plus real bins cut from the audits for the terrain-aware rule (testdata/building_depth_terrain_cases.npz).

    python tools/homm3_town_scene_meshes/test_town_building_contact_depth.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import stronghold_full3d_buildings as BL  # noqa: E402
import town_full3d_building_depth as BD  # noqa: E402
import town_full3d_building_redepth as RD  # noqa: E402
import validate_town_scene3d_contract as V  # noqa: E402

H0 = -40.0          # synthetic horizon row (above the sprite)
K = 1e-4            # 1/z = K (row - H0)


def plane_z(rows):
    return 1.0 / (K * (np.asarray(rows, np.float64) - H0))


def sprite(h=60, w=24, wall_rows=30, wall_from_plane=True):
    """A wall standing on the floor (rows < wall_rows: constant depth = the floor at its base) over its reflection
    lying on the floor (rows >= wall_rows: the floor plane's depth and gradient)."""
    rows = np.arange(h, dtype=np.float64)[:, None].repeat(w, 1)
    z = plane_z(rows + 0.5)
    raw = z.copy()
    raw[:wall_rows] = plane_z(wall_rows + 0.5) if wall_from_plane else 0.8 * plane_z(wall_rows + 0.5)
    mask = np.ones((h, w), bool)
    plane = z
    in_floor = np.ones((h, w), bool)
    dlog = -1.0 / (rows + 0.5 - H0)
    low = np.full(w, h - 1)
    return mask, raw, plane, in_floor, dlog, low


class ContactSigma(unittest.TestCase):
    def test_thin_sprite_keeps_full_relief(self):
        inv = 1.0 / 100.0 + np.linspace(-1e-4, 1e-4, 200)        # ~ +-1 m around a 100 m contact
        s, e1, e = BL.contact_sigma(inv, 1.0 / 100.0, 100.0, width_m=10.0)
        self.assertEqual(s, 1.0)
        self.assertAlmostEqual(e, e1)
        self.assertLessEqual(e, BL.CONTACT_THICK_K * 10.0)

    def test_deep_sprite_is_compressed_to_the_thickness_prior(self):
        inv = 1.0 / 100.0 + np.linspace(-5e-3, 5e-3, 500)        # the waterfall's case: ~70-200 m raw
        s, e1, e = BL.contact_sigma(inv, 1.0 / 100.0, 100.0, width_m=20.0)
        self.assertGreater(e1, BL.CONTACT_THICK_K * 20.0)
        self.assertTrue(0.0 < s < 1.0)
        self.assertLessEqual(e, BL.CONTACT_THICK_K * 20.0 + 1e-6)
        self.assertGreater(e, 0.95 * BL.CONTACT_THICK_K * 20.0)    # the largest sigma, not just any

    def test_contact_depth_is_fixed_point(self):
        # whatever sigma, the contact px keeps z_c: 1/z = 1/z_c + sigma (inv_c - inv_c)
        inv = np.array([0.004, 0.005, 0.006])
        s, _, _ = BL.contact_sigma(inv, 0.005, 200.0, width_m=5.0)
        self.assertAlmostEqual(1.0 / (1.0 / 200.0 + s * (0.005 - 0.005)), 200.0)

    def test_beyond_far_is_refused_by_sigma(self):
        inv = np.array([1e-5, 1e-2])                                # one px at 100 km
        s, e1, e = BL.contact_sigma(inv, 1e-2, 100.0, width_m=1e4, far_m=4000.0)
        self.assertEqual(e1, float("inf"))
        self.assertLess(s, 1.0)
        self.assertTrue(np.isfinite(e))

    def test_empty(self):
        self.assertEqual(BL.contact_sigma(np.array([np.nan]), 0.01, 100.0, 5.0), (0.0, 0.0, 0.0))


class ContactDepth(unittest.TestCase):
    def test_tail_is_clipped_to_the_prior_window(self):
        inv = np.full(200, 1 / 90.0)
        inv[:180] = np.linspace(1 / 85.0, 1 / 95.0, 180)
        inv[180:] = 1 / 400.0                         # a 10% tail running far back (above the p2 cut: 10% > 2%)
        inv[195:] = 1 / 4000.0                        # the last 2.5%: beyond p2
        up = np.ones(200, bool)
        z = BL.contact_depth(inv, up, 1 / 90.0, 90.0, 1.0)
        lo = np.percentile(inv, 2)
        self.assertAlmostEqual(z.max(), 1 / (1 / 90.0 + (lo - 1 / 90.0)), places=6)
        self.assertLess(z.max(), 4000.0)

    def test_contact_is_fixed_point_and_rays_inside_window_unchanged(self):
        inv = np.linspace(1 / 80.0, 1 / 100.0, 101)
        up = np.ones(101, bool)
        z = BL.contact_depth(inv, up, inv[50], 90.0, 0.5)
        self.assertAlmostEqual(z[50], 90.0, places=9)
        mid = slice(5, 96)
        np.testing.assert_allclose(z[mid], 1 / (1 / 90.0 + 0.5 * (inv[mid] - inv[50])))


class GroundSplit(unittest.TestCase):
    def test_reflection_is_ground_wall_is_upright(self):
        m, raw, plane, inf, dlog, low = sprite()
        g = BL.ground_split(m, raw, plane, inf, dlog, low)
        self.assertFalse(g[:26].any(), "the wall (floor depth at its base, no floor gradient) must stay upright")
        self.assertTrue(g[34:].all(), "the reflection lying on the floor must be ground")

    def test_wall_alone_has_no_ground(self):
        m, raw, plane, inf, dlog, low = sprite(wall_rows=60)
        self.assertFalse(BL.ground_split(m, raw, plane, inf, dlog, low).any())

    def test_outside_floor_polygon_is_never_ground(self):
        m, raw, plane, inf, dlog, low = sprite()
        inf[:] = False
        self.assertFalse(BL.ground_split(m, raw, plane, inf, dlog, low).any())

    def test_speckle_inside_reflection_is_absorbed(self):
        m, raw, plane, inf, dlog, low = sprite()
        raw[45:46, 10:12] *= 1.3                                    # depth-model speckle under the waterline
        g = BL.ground_split(m, raw, plane, inf, dlog, low)
        self.assertTrue(g[31:, 10:12].all(), "a <= GROUND_GAP_PX upright island under the waterline is ground")

    def test_large_speckle_cuts_the_run_upward_only(self):
        # recorded limit: a step the 2 px smoothing spreads past GROUND_GAP_PX ends the column's ground run there;
        # everything below stays ground, everything above is upright (the contact moves down, never up into the wall)
        m, raw, plane, inf, dlog, low = sprite()
        raw[45:47, 10:12] *= 1.6
        g = BL.ground_split(m, raw, plane, inf, dlog, low)
        self.assertTrue(g[50:, 10].all())
        self.assertFalse(g[30:44, 10].any())
        self.assertTrue(g[31:, 0].all(), "other columns are unaffected")

    def test_floating_floor_patch_is_not_ground(self):
        # a floor-like patch that does not reach the sprite's bottom (a balcony with floor depth) stays upright
        m, raw, plane, inf, dlog, low = sprite(wall_rows=60)
        raw[5:12] = plane[5:12]
        self.assertFalse(BL.ground_split(m, raw, plane, inf, dlog, low).any())


class StreakMeasure(unittest.TestCase):
    """The validator's measure and the module's are one rule, and it fails the waterfall shape."""

    def setUp(self):
        self.n, self.d, self.scale = np.array([0.0, 1.0, 0.0]), -10.0, 2.0   # floor 10 m below the camera

    def verts(self, depth_span):
        rng = np.random.default_rng(0)
        x = rng.uniform(-5, 5, 4000)
        y = rng.uniform(-8, 5, 4000)                              # 2 m .. 15 m above the floor
        z = 200.0 + rng.uniform(-depth_span / 2, depth_span / 2, 4000)
        return np.stack([x, y, z], 1) * self.scale

    def test_identical_rules(self):
        v = self.verts(80.0)
        a = BD.upright_stats(v, self.scale, self.n, self.d)
        b = V.building_upright_stats(v, self.scale, self.n, self.d, BD.UPRIGHT_H_M)
        self.assertEqual(a, b)

    def test_streak_fails_card_passes(self):
        bad = BD.upright_stats(self.verts(85.0), self.scale, self.n, self.d)     # 10 m wide, 85 m deep
        good = BD.upright_stats(self.verts(8.0), self.scale, self.n, self.d)
        self.assertGreater(bad["spanOverWidth"], BD.SPAN_OVER_WIDTH_MAX)
        self.assertGreater(bad["uprightSpanM"], BD.SPAN_MIN_M)
        self.assertLess(good["spanOverWidth"], BD.SPAN_OVER_WIDTH_MAX)

    def test_floor_lying_vertices_do_not_count(self):
        v = self.verts(8.0)
        rng = np.random.default_rng(1)
        flat = np.stack([rng.uniform(-5, 5, 4000), np.full(4000, -9.8), 200 + rng.uniform(0, 150, 4000)], 1)
        a = BD.upright_stats(np.r_[v, flat * self.scale], self.scale, self.n, self.d)
        self.assertLess(a["spanOverWidth"], BD.SPAN_OVER_WIDTH_MAX)


class TerrainRule(unittest.TestCase):
    """The terrain-aware upright measure (buildingDepth.terrainSample): ground lying on a hill above the floor plane is
    not upright; a streak standing above the hill and walls buried in a terrain bump still are."""

    def setUp(self):
        self.n, self.d, self.scale = np.array([0.0, 1.0, 0.0]), -10.0, 2.0   # floor 10 m below the camera
        e1, e2 = np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, -1.0])        # e2 = n x e1
        self.hill = 6.0
        g = np.full((800, 80), self.hill, np.float32)                            # x -20..20, z 0..400 at 0.5 m
        self.t = {"terrain_grid": g, "terrain_origin": np.array([-20.0, -400.0]), "terrain_cell": np.float64(0.5),
                  "terrain_e1": e1, "terrain_e2": e2}
        assert (e2 == np.cross(self.n, e1)).all()

    def pts(self, y_lo, y_hi, depth_span, n=4000, seed=0):
        rng = np.random.default_rng(seed)
        y = -10.0 + rng.uniform(y_lo, y_hi, n)                                   # height above the floor plane
        z = 200.0 + rng.uniform(-depth_span / 2, depth_span / 2, n)
        return np.stack([rng.uniform(-5, 5, n), y, z], 1) * self.scale

    def stats(self, v, terrain):
        return BD.upright_stats(v, self.scale, self.n, self.d, terrain)

    def fails(self, st):
        return st["spanOverWidth"] > BD.SPAN_OVER_WIDTH_MAX and st["uprightSpanM"] > BD.SPAN_MIN_M

    def test_identical_rules_with_terrain(self):
        v = self.pts(0, 15, 80.0)
        self.assertEqual(BD.upright_stats(v, self.scale, self.n, self.d, self.t),
                         V.building_upright_stats(v, self.scale, self.n, self.d, BD.UPRIGHT_H_M, self.t))

    def test_ground_on_the_hill_is_not_upright(self):
        card = self.pts(0, 15, 8.0)                       # a 10 m wide, 8 m deep building
        on_hill = self.pts(self.hill - 0.5, self.hill + 1.5, 150.0, seed=1)   # ground lying on the hill, 150 m deep
        v = np.r_[card, on_hill]
        self.assertTrue(self.fails(self.stats(v, None)))  # the plane alone calls the hill's ground a streak
        self.assertFalse(self.fails(self.stats(v, self.t)))

    def test_streak_standing_above_relief_still_fails(self):
        v = self.pts(self.hill + 2.5, self.hill + 20, 85.0)   # 10 m wide, 85 m deep, all above the hill
        self.assertTrue(self.fails(self.stats(v, self.t)))

    def test_walls_buried_in_a_terrain_bump_still_count(self):
        t = dict(self.t, terrain_grid=np.full((800, 80), 30.0, np.float32))  # the painting's building left a bump
        v = self.pts(2.5, 20, 85.0)                           # more than 2 m under the bump top
        self.assertTrue(self.fails(self.stats(v, t)))

    def test_no_terrain_cell_is_the_floor_plane(self):
        t = dict(self.t, terrain_grid=np.full((800, 80), np.nan, np.float32))
        v = self.pts(0, 15, 80.0)
        self.assertEqual(self.stats(v, t), self.stats(v, None))

    def test_real_bins(self):
        """Cove pre-fix waterfall / stilt houses (pb_v1, bgd_v1) still fail; tower rx_cond_dalarge_dfix tbtwdw_0_2's
        ground on the da_large terrain passes (testdata/building_depth_terrain_cases.npz, cut from the audits)."""
        with np.load(HERE / "testdata" / "building_depth_terrain_cases.npz") as z:
            d = dict(z.items())
        self.assertIn("pass", list(d["expect"]))
        self.assertIn("fail", list(d["expect"]))
        for k, (label, want, want_plane) in enumerate(zip(d["labels"], d["expect"], d["expect_plane"])):
            t = {kk: d[f"c{k}_{kk}"] for kk in ("terrain_grid", "terrain_origin", "terrain_cell", "terrain_e1",
                                                  "terrain_e2")}
            args = (d[f"c{k}_P"], float(d[f"c{k}_depth_scale"]), d[f"c{k}_floor_n"], float(d[f"c{k}_floor_d"]))
            with self.subTest(str(label)):
                self.assertEqual("fail" if self.fails(BD.upright_stats(*args, t)) else "pass", str(want))
                self.assertEqual("fail" if self.fails(BD.upright_stats(*args)) else "pass", str(want_plane))

    def test_stale_terrain_sample_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = root / "env"
            env.mkdir()
            (env / "Mesh_Terrain.bytes").write_bytes(b"terrain-a")
            (env / "Mesh_Prop_rock.bytes").write_bytes(b"not terrain")
            pieces, sha = V.building_terrain_pieces_sha(env)
            self.assertEqual(pieces, ["Mesh_Terrain"])
            npz = {k: self.t[k] for k in self.t}
            npz["terrain_sha"] = np.array(sha)
            bd = {"terrainSample": {"pieces": pieces, "sha256": sha, "stageDir": "env"}}
            old = V.ROOT
            V.ROOT = root
            try:
                self.assertEqual(V.building_terrain_failures(bd, npz)[0], [])
                (env / "Mesh_Terrain.bytes").write_bytes(b"terrain-b")           # restaged after the sample
                self.assertTrue(any("stale" in f for f in V.building_terrain_failures(bd, npz)[0]))
                (env / "Mesh_Terrain.bytes").unlink()
                self.assertTrue(V.building_terrain_failures(bd, npz)[0])
                self.assertTrue(V.building_terrain_failures({}, npz)[0])        # npz sample without the block
                self.assertEqual(V.building_terrain_failures({}, {})[0], [])     # neither: the floor plane alone
                (env / "Mesh_Terrain.bytes").write_bytes(b"terrain-a")
                self.assertTrue(V.building_terrain_failures(bd, dict(npz, terrain_sha=np.array("0" * 64)))[0])
            finally:
                V.ROOT = old


class PosedBinScaleTest(unittest.TestCase):
    """scale_bin_about_camera: a posed card (holder pos / rot, holder-local vertices) scaled about the camera keeps
    its projection and moves its pivot with the body (the 2026-10-01 tower pendulum left behind its pulled body)."""

    def test_posed_card_keeps_projection_and_rides(self):
        import struct
        import tempfile
        import town_full3d_building_redepth as RD

        class FakeS:
            @staticmethod
            def write_bin(path, v, n, uv, subs):
                with open(path, "wb") as f:
                    f.write(struct.pack("<ii", len(v), len(subs)))
                    f.write(np.asarray(v, np.float32).tobytes())
                    f.write(np.asarray(n, np.float32).tobytes())
                    f.write(np.asarray(uv, np.float32).tobytes())
                    for t in subs:
                        t = np.asarray(t, np.int32).ravel()
                        f.write(struct.pack("<i", len(t)))
                        f.write(t.tobytes())

            @staticmethod
            def read_bin(path):
                b = Path(path).read_bytes()
                nv, ns = struct.unpack_from("<ii", b, 0)
                o = 8
                v = np.frombuffer(b, np.float32, nv * 3, o).reshape(-1, 3); o += nv * 12
                n = np.frombuffer(b, np.float32, nv * 3, o).reshape(-1, 3); o += nv * 12
                uv = np.frombuffer(b, np.float32, nv * 2, o).reshape(-1, 2); o += nv * 8
                subs = []
                for _ in range(ns):
                    (k,) = struct.unpack_from("<i", b, o); o += 4
                    subs.append(np.frombuffer(b, np.int32, k, o).reshape(-1, 3)); o += k * 4
                return v, n, uv, subs

        h = 1.78
        v = np.array([[-h, 0, h], [h, 0, h], [h, 0, -h], [-h, 0, -h]])
        b = {"name": "Fx_Swing_0_x", "pos": [-2.798, 2.583, 33.624],
             "rot": [0.6789024267741063, -0.028116516616807103, 0.03035949916247055, 0.7330615644160934]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "card.bytes"
            FakeS.write_bin(path, v, np.zeros_like(v), np.zeros((4, 2)), [np.array([[0, 1, 2], [0, 2, 3]])])
            before = RD.bin_prefab_vertices(b, FakeS.read_bin(path)[0])
            k = 0.4525
            RD.scale_bin_about_camera(FakeS, path, b, k)
            after = RD.bin_prefab_vertices(b, FakeS.read_bin(path)[0])
        np.testing.assert_allclose(after, before * k, rtol=1e-5, atol=1e-5)          # every point scaled about the camera
        np.testing.assert_allclose(after[:, :2] / after[:, 2:], before[:, :2] / before[:, 2:], atol=1e-6)  # same pixels
        np.testing.assert_allclose(b["pos"], np.array([-2.798, 2.583, 33.624]) * k, rtol=1e-9)


class OrderOptions(unittest.TestCase):
    """The pin's optional "order" block (docs "Near layers"): defaults off, closed key set, q bounded by the residual gate."""

    def opts(self, pin):
        from unittest import mock
        with mock.patch.object(RD.BL, "building_depth_pin", return_value=pin):
            return RD.order_options()

    def test_default_is_the_installed_rule(self):
        self.assertEqual(self.opts(None), {"q": RD.ORDER_Q, "artSameDE": None})
        self.assertEqual(self.opts({"mode": "contact_v1"}), {"q": RD.ORDER_Q, "artSameDE": None})

    def test_values_pass_through(self):
        self.assertEqual(self.opts({"order": {"q": 0.015, "artSameDE": 6}}), {"q": 0.015, "artSameDE": 6.0})

    def test_unknown_key_is_refused(self):
        with self.assertRaises(SystemExit):
            self.opts({"order": {"quantile": 0.015}})

    def test_q_outside_the_residual_gate_is_refused(self):
        for q in (0.0, -0.01, RD.ORDER_RESIDUAL_MAX * 1.5):
            with self.assertRaises(SystemExit):
                self.opts({"order": {"q": q}})

    def test_art_same_off_is_an_empty_mask(self):
        m = RD.art_same("anything", None)
        self.assertFalse(m.any())


if __name__ == "__main__":
    unittest.main()
