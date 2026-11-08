"""Unit tests for the float64 Corrective Smooth bake (cs_numpy.py, docs/homm3_cs_bake_float64.md).

    python tools/homm3_glb_patch/test_cs_numpy.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs_numpy as CS  # noqa: E402


def grid(n=7, bend=0.0):
    xs = np.linspace(0, 1, n)
    V = np.array([[x, y, bend * (x - 0.5) ** 2] for y in xs for x in xs])
    F = []
    for j in range(n - 1):
        for i in range(n - 1):
            a, b, c, d = j * n + i, j * n + i + 1, (j + 1) * n + i, (j + 1) * n + i + 1
            F += [[a, b, d], [a, d, c]]
    return V, np.array(F)


def one_bone(V):
    J = np.zeros((len(V), 4), np.int64)
    W = np.zeros((len(V), 4))
    W[:, 0] = 1
    return J, W


def rot(axis, deg):
    a = np.asarray(axis, float) / np.linalg.norm(axis)
    t = np.radians(deg)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(t) * K + (1 - np.cos(t)) * K @ K


class CsNumpyTest(unittest.TestCase):
    def with_degenerate_parts(self):
        """a grid plus a lone tiny triangle (smooths to a point) and a zero-area sliver fan (collinear vertices)."""
        V, F = grid(bend=0.3)
        tri = np.array([[5.0, 5, 5], [5.001, 5, 5], [5, 5.001, 5]])
        line = np.array([[-3.0, 0, 0], [-2.0, 0, 0], [-1.0, 0, 0]])     # a flat face: every corner degenerate
        n = len(V)
        V2 = np.r_[V, tri, line]
        F2 = np.r_[F, [[n, n + 1, n + 2]], [[n + 3, n + 4, n + 5]]]
        return V2, F2

    def test_rest_round_trip_exact_with_degenerate_parts(self):
        V, F = self.with_degenerate_parts()
        J, W = one_bone(V)
        w = CS.Weld(V, J, W, F)
        cache = w.rest_deltas(V[w.rep])
        C = w.corrective(V[w.rep], cache)
        self.assertLess(np.abs(C - V[w.rep]).max(), 1e-12)
        # the collinear face has no valid corner, and the lone tiny triangle smooths to a point: both are
        # skinning-only (counted); the grid keeps its frames
        so = w.last_skin_only[w.gid]
        self.assertTrue(so[-6:].all())
        self.assertFalse(so[:-6].any())
        self.assertGreaterEqual(int((~w.rest_valid).sum()), 3)

    def test_degenerate_corner_has_no_weight(self):
        V, F = self.with_degenerate_parts()
        J, W = one_bone(V)
        w = CS.Weld(V, J, W, F)
        T, wt, valid = w.tangents(V[w.rep])
        self.assertTrue((wt[~valid] == 0).all())
        self.assertTrue(np.allclose(T[~valid], np.eye(3)))
        # a valid frame is orthonormal
        TT = np.einsum("cij,ckj->cik", T[valid], T[valid])
        self.assertLess(np.abs(TT - np.eye(3)).max(), 1e-12)

    def test_rigid_motion_needs_no_offset(self):
        """one bone, any rotation + translation: CS is rotation-equivariant, so the offset vanishes (float64)."""
        V, F = self.with_degenerate_parts()
        J, W = one_bone(V)
        w = CS.Weld(V, J, W, F)
        cache = w.rest_deltas(V[w.rep])
        Sk = np.eye(4)[None].copy()
        Sk[0, :3, :3] = rot([0.3, 1, -0.2], 73)
        Sk[0, :3, 3] = [0.4, -1.2, 2.0]
        d = CS.offsets(w, V, J, W, Sk, cache)
        self.assertLess(np.abs(d).max(), 1e-9)

    def test_skin_only_group_returns_skin(self):
        V, F = self.with_degenerate_parts()
        J, W = one_bone(V)
        w = CS.Weld(V, J, W, F)
        cache = w.rest_deltas(V[w.rep])
        S = V[w.rep] + np.c_[0.1 * V[w.rep][:, 1] ** 2, np.zeros(w.ng), np.zeros(w.ng)]
        C = w.corrective(S, cache)
        so = w.last_skin_only
        self.assertTrue(so.any())
        # the undefined groups here are islands (no defined neighbour): skinning only
        np.testing.assert_array_equal(C[so], S[so])
        self.assertEqual(w.last_unfilled, int(so.sum()))

    def test_from_groups_matches_glb_weld(self):
        V, F = grid()
        J, W = one_bone(V)
        a = CS.Weld(V, J, W, F)
        b = CS.Weld.from_groups(a.gid, F.tolist(), V)
        np.testing.assert_array_equal(a.edges, b.edges)
        R = V[a.rep]
        S = R + np.c_[0.2 * R[:, 1] ** 2, np.zeros(len(R)), 0.1 * R[:, 0]]
        ca, cb = a.rest_deltas(R), b.rest_deltas(R)
        np.testing.assert_allclose(a.corrective(S, ca), b.corrective(S, cb), atol=1e-14)

    def test_smoothing_matches_reference_loop(self):
        """the vectorised length-weighted smoothing equals Blender's per-edge loop (smooth_iter__length_weight)."""
        V, F = grid(5, bend=0.4)
        J, W = one_bone(V)
        w = CS.Weld(V, J, W, F)
        X = V[w.rep].copy()
        ref = X.copy()
        for _ in range(5):
            delta = np.zeros_like(ref)
            lens = np.zeros(w.ng)
            for a, b in w.edges:
                d = ref[b] - ref[a]
                ln = np.linalg.norm(d)
                delta[a] += d * ln
                delta[b] -= d * ln
                lens[a] += ln
                lens[b] += ln
            div = lens * w.edge_count
            ref = ref + delta * np.where(div > 0, 1.4 / np.where(div > 0, div, 1), 0)[:, None]
        np.testing.assert_allclose(w.smooth(X, 5, 0.7), ref, atol=1e-13)

    def test_skin_dense_unweighted_vertex_keeps_rest(self):
        V = np.array([[0.0, 1, 2], [1, 1, 1]])
        Wt = np.array([[1.0, 0.0], [0.0, 0.0]])
        M = np.stack([np.eye(4), np.eye(4)])
        M[0, :3, 3] = [1, 0, 0]
        S, Mb, sc = CS.skin_dense(V, Wt, M)
        np.testing.assert_allclose(S, [[1, 1, 2], [1, 1, 1]])
        self.assertEqual(sc[1], 0.0)

    def test_undefined_groups_take_harmonic_fill(self):
        """undefined groups bordered by defined ones take the exact harmonic interpolation (each is the mean of its weld
        neighbours, defined groups untouched); an undefined island with no defined neighbour stays at 0 (skinning only)."""
        V, F = self.with_degenerate_parts()
        J, W = one_bone(V)
        w = CS.Weld(V, J, W, F)
        rng = np.random.default_rng(3)
        D = rng.normal(size=(w.ng, 3))
        free = np.zeros(w.ng, bool)
        free[w.gid[[8, 9, 10, 15, 16, 17, 24]]] = True        # an interior patch of the grid
        island = w.gid[-3:]                                 # the collinear face: its own component
        free[island] = True
        D[free] = 0.0
        out, unfilled = w._fill(D, free)
        self.assertEqual(unfilled, 3)
        np.testing.assert_array_equal(out[~free], D[~free])
        np.testing.assert_array_equal(out[island], 0.0)
        for g in np.flatnonzero(free):
            if g in island:
                continue
            nb = np.unique(np.r_[w.edges[w.edges[:, 0] == g, 1], w.edges[w.edges[:, 1] == g, 0]])
            np.testing.assert_allclose(out[g], out[nb].mean(0), atol=1e-12)

    def test_exclusion_scales_corrective_displacement(self):
        """correctiveSmooth.excludeBones: C - S scaled by 1 - the excluded weight share; fully excluded = skin only."""
        V, F = grid(bend=0.3)
        J, W = one_bone(V)
        w = CS.Weld(V, J, W, F)
        cache = w.rest_deltas(V[w.rep])
        S = V[w.rep] * [1.0, 1.0, 1.6]                     # a non-rigid deformation: CS corrects it
        D = w.corrective(S, cache) - S
        self.assertGreater(np.abs(D).max(), 1e-3)
        m = CS.exclusion_share(J, W, ["b0", "b1"], ["b0"])[w.rep] * 0.25
        w.set_exclusion(m)
        np.testing.assert_allclose(w.corrective(S, cache) - S, D * 0.75, atol=1e-12)
        w.set_exclusion(np.ones(w.ng))
        self.assertEqual(np.abs(w.corrective(S, cache) - S).max(), 0.0)
        w.set_exclusion(None)
        np.testing.assert_array_equal(w.corrective(S, cache) - S, D)

    def test_rule_record(self):
        r = CS.rule()
        self.assertEqual(r["precision"], "float64")
        self.assertEqual(r["degenerateCornerHeight"], CS.DEGEN_CORNER_HEIGHT)

    def test_bake_smoothing_from_record(self):
        """A re-bake smooths with the bake record's iterations / factor (h3_pegasus 60 / 0.8, 2026-10-09)."""
        self.assertEqual(CS.bake_smoothing({"schema": CS.BAKE_SCHEMA, "iterations": 60, "factor": 0.8}), (60, 0.8))
        self.assertEqual(CS.bake_smoothing(None), (CS.ITERATIONS, CS.FACTOR))         # legacy float32 bake
        with self.assertRaises(SystemExit):
            CS.bake_smoothing({"schema": CS.BAKE_SCHEMA})
        # the parameters matter: a 60 / 0.8 bake does not reproduce under the defaults
        V, F = grid(bend=0.3)
        J, W = one_bone(V)
        J[: len(V) // 2, 1], W[: len(V) // 2] = 1, [0.5, 0.5, 0, 0]
        w = CS.Weld(V, J, W, F)
        Sk = np.stack([np.eye(4), np.eye(4)])
        Sk[1, :3, :3] = rot([0, 1, 0], 40)
        d = {p: CS.offsets(w, V, J, W, Sk, w.rest_deltas(V[w.rep], *p)) for p in ((60, 0.8), (30, 0.7))}
        np.testing.assert_array_equal(CS.offsets(w, V, J, W, Sk, w.rest_deltas(V[w.rep], 60, 0.8)), d[(60, 0.8)])
        self.assertGreater(np.abs(d[(60, 0.8)] - d[(30, 0.7)]).max(), 1e-4)


if __name__ == "__main__":
    unittest.main()
