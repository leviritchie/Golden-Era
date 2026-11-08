"""Focused phase-6b regressions: ridge-curtain cut + back layer, and the validator's terrain-streak gate."""
from __future__ import annotations

import contextlib
import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import conflux_full3d_curtain as curtain  # noqa: E402
import validate_town_scene3d_contract as gate  # noqa: E402


class FakeCtx:
    """A camera at the origin looking down +z with a 90 degree vertical field of view over a 30x18 px frame."""

    def __init__(self, W=30, H=18):
        self.cpos = np.zeros(3)
        self.cam = {"fwd": np.array([0.0, 0.0, 1.0]), "right": np.array([1.0, 0.0, 0.0]),
                    "up": np.array([0.0, 1.0, 0.0]), "fov": 90.0, "pos": np.zeros(3)}
        self.W, self.H = W, H


def ridge_grid(ctx, step=3):
    """A far slope (z 40..48) with a near ridge (z 20) over the lower half of the frame."""
    W, H = 30, 18
    xs = np.arange(0, W + 1, step)
    ys = np.arange(0, H + 1, step)
    fx, fy = (a.astype(np.float64) for a in np.meshgrid(xs, ys))
    z = 40 + 8 * (1 - fy / H)
    z = np.where(fy >= 9, 20.0, z)
    t = np.tan(np.radians(45))
    d = np.stack([(fx / W * 2 - 1) * t * W / H, (1 - fy / H * 2) * t, np.ones_like(fx)], -1)
    P = d * z[..., None]
    n = np.broadcast_to(np.array([0.0, 1.0, 0.0]), P.shape).copy()
    nx = len(xs)
    tris = curtain.grid_topology(nx, len(ys))
    return {"xs": xs, "ys": ys, "P": P, "n": n, "tris": tris, "keep": np.ones(fx.shape, bool), "fx": fx, "fy": fy}, (W, H)


class CurtainApplyTests(unittest.TestCase):
    def setUp(self):
        import conflux_full3d_env as E

        self.E = E
        self.saved = (E.W, E.H)
        E.W, E.H = 30, 18

    def tearDown(self):
        self.E.W, self.E.H = self.saved

    def test_cut_removes_every_curtain_and_back_layer_stays_inside_cap(self):
        ctx = FakeCtx()
        grid, _ = ridge_grid(ctx)
        P = grid["P"].reshape(-1, 3)
        before = gate.streak_ratios(P, grid["tris"], ctx.cpos, ctx.cam["fwd"])
        self.assertTrue((before > curtain.RATIO_CAP).any())
        back = curtain.apply(ctx, grid)
        after = gate.streak_ratios(P, grid["tris"], ctx.cpos, ctx.cam["fwd"])
        self.assertTrue((after <= curtain.RATIO_CAP).all())
        rb = gate.streak_ratios(back["P"], back["tris"], ctx.cpos, ctx.cam["fwd"])
        self.assertTrue(len(rb) and (rb <= curtain.RATIO_CAP + 1e-9).all())
        self.assertEqual(back["report"]["cutTris"], int((before > curtain.RATIO_CAP).sum()))

    def test_back_layer_keeps_rest_screen_positions(self):
        """Every back-layer vertex lies on the rest ray of a grid vertex (rest-frame registration)."""
        ctx = FakeCtx()
        grid, _ = ridge_grid(ctx)
        rays = grid["P"].reshape(-1, 3) / np.linalg.norm(grid["P"].reshape(-1, 3), axis=1, keepdims=True)
        back = curtain.apply(ctx, grid)
        rb = back["P"] / np.linalg.norm(back["P"], axis=1, keepdims=True)
        best = (rb @ rays.T).max(1)
        self.assertTrue((best > 1 - 1e-9).all())


class StreakGateTests(unittest.TestCase):
    def write(self, folder: Path, **over):
        tri = np.array([[0, 1, 2]], np.int32)
        arrays = {"main_P": np.array([[0, 0, 10], [1, 0, 10.5], [0, 1, 11], [0, 0, 30.0]]),
                  "main_tris": tri, "back_P": np.array([[0, 0, 30], [1, 0, 31], [0, 1, 32.0]]), "back_tris": tri,
                  "cut_tris": np.array([[0, 1, 3]], np.int32), "cpos": np.zeros(3), "cam_fwd": np.array([0, 0, 1.0])}
        arrays.update(over)
        path = folder / "terrain_streak.npz"
        np.savez_compressed(path, **arrays)
        cat = {"environment": {"pieces": ["Mesh_Terrain", "Mesh_Back_Terrain"]},
               "terrainStreak": {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                 "ratioCap": 1.25, "cutTris": len(arrays["cut_tris"]),
                                 "backPieces": ["Mesh_Back_Terrain"]}}
        return cat

    def run_gate(self, cat, folder):
        with contextlib.redirect_stderr(io.StringIO()):
            return gate.check_terrain_streak(cat, "t", folder)

    def test_clean_mesh_passes(self):
        with tempfile.TemporaryDirectory() as td:
            cat = self.write(Path(td))
            self.assertIn("streakNeg=1", self.run_gate(cat, Path(td)))

    def test_curtain_in_main_refused(self):
        with tempfile.TemporaryDirectory() as td:
            cat = self.write(Path(td), main_tris=np.array([[0, 1, 2], [0, 1, 3]], np.int32))
            with self.assertRaises(SystemExit):
                self.run_gate(cat, Path(td))

    def test_curtain_in_back_layer_refused(self):
        with tempfile.TemporaryDirectory() as td:
            cat = self.write(Path(td), back_P=np.array([[0, 0, 30], [1, 0, 31], [0, 1, 45.0]]))
            with self.assertRaises(SystemExit):
                self.run_gate(cat, Path(td))

    def test_negative_that_cannot_fail_refused(self):
        with tempfile.TemporaryDirectory() as td:
            cat = self.write(Path(td), cut_tris=np.array([[0, 1, 2]], np.int32))
            with self.assertRaises(SystemExit):
                self.run_gate(cat, Path(td))

    def test_empty_cut_matching_catalog_passes(self):
        """The zone cut bounded everything (vlb back rule): no ratio cut, catalog cutTris 0; the positive check runs."""
        with tempfile.TemporaryDirectory() as td:
            cat = self.write(Path(td), cut_tris=np.zeros((0, 3), np.int32))
            self.assertEqual(cat["terrainStreak"]["cutTris"], 0)
            self.assertIn("maxRatioAfter=", self.run_gate(cat, Path(td)))

    def test_empty_cut_with_catalog_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as td:
            cat = self.write(Path(td), cut_tris=np.zeros((0, 3), np.int32))
            cat["terrainStreak"]["cutTris"] = 1
            with self.assertRaises(SystemExit):
                self.run_gate(cat, Path(td))

    def test_empty_cut_with_curtain_in_main_refused(self):
        with tempfile.TemporaryDirectory() as td:
            cat = self.write(Path(td), cut_tris=np.zeros((0, 3), np.int32),
                             main_tris=np.array([[0, 1, 2], [0, 1, 3]], np.int32))
            with self.assertRaises(SystemExit):
                self.run_gate(cat, Path(td))

    def test_loose_cap_and_missing_back_piece_refused(self):
        with tempfile.TemporaryDirectory() as td:
            cat = self.write(Path(td))
            cat["terrainStreak"]["ratioCap"] = 2.0
            with self.assertRaises(SystemExit):
                self.run_gate(cat, Path(td))
            cat = self.write(Path(td))
            cat["environment"]["pieces"] = ["Mesh_Terrain"]
            with self.assertRaises(SystemExit):
                self.run_gate(cat, Path(td))


if __name__ == "__main__":
    unittest.main()
