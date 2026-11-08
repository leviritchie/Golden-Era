"""cove_tube pure helpers (run outside Blender): python tools/homm3_def_retarget/test_cove_tube.py"""
import sys, unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent / "ext"))
import cove_tube as T


class CoveTube(unittest.TestCase):
    def test_largest_square(self):
        g = np.zeros((20, 30), bool); g[3:12, 5:20] = True; g[15:19, 25:29] = True
        r, c, n = T.largest_square(g)
        self.assertEqual(n, 9); self.assertTrue(g[r:r + n, c:c + n].all())

    def test_pingpong_continuous(self):
        x = np.linspace(0, 6, 601); y = T.pingpong(x)
        self.assertTrue((y >= 0).all() and (y <= 1).all())
        self.assertLess(np.abs(np.diff(y)).max(), 0.011)
        self.assertAlmostEqual(float(T.pingpong(np.array(2.0))), 0.0)

    def test_transport_frames_orthonormal(self):
        t = np.linspace(0, 3 * np.pi, 80); cen = np.stack([np.cos(t), np.sin(t), 0.1 * t], 1)
        tan, N, B = T.transport_frames(cen)
        for a, b in ((tan, N), (tan, B), (N, B)):
            self.assertLess(np.abs((a * b).sum(1)).max(), 1e-9)
        self.assertLess(np.abs(np.linalg.norm(N, axis=1) - 1).max(), 1e-9)

    def test_hat_weights(self):
        w = T.hat_weights(3.5, 12); self.assertEqual(w, {3: 1.0})
        w = T.hat_weights(4.0, 12); self.assertAlmostEqual(w[3], 0.5); self.assertAlmostEqual(w[4], 0.5)
        self.assertAlmostEqual(sum(T.hat_weights(11.9, 12).values()), 1.0)

    def test_radius_profile_and_projection(self):
        C = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], float)
        rng = np.random.default_rng(0); x = rng.uniform(0, 2, 4000); a = rng.uniform(0, 2 * np.pi, 4000)
        Q = np.stack([x, 0.2 * np.cos(a), 0.2 * np.sin(a)], 1)
        sv, d = T.project_s(Q, C)
        self.assertLess(np.abs(sv - x).max(), 1e-9); self.assertLess(np.abs(d - 0.2).max(), 1e-9)
        bc, r = T.radius_profile(sv, d, 2.0)
        self.assertLess(np.abs(r - 0.2).max(), 1e-9)

    def test_short_loop_drops(self):
        a = np.linspace(0, 2 * np.pi, 12, endpoint=False); pts = np.stack([np.cos(a), np.sin(a), 0 * a], 1)
        self.assertEqual(T.short_loop_drops(pts), [])
        pts2 = np.insert(pts, 5, pts[4] + [1e-4, 0, 0], 0)          # near-duplicate after vertex 4
        self.assertEqual(T.short_loop_drops(pts2), [5])

    def test_winding(self):
        a = np.linspace(0, 2 * np.pi, 16, endpoint=False); ring = np.stack([0 * a, np.cos(a), np.sin(a)], 1)
        self.assertAlmostEqual(abs(T.winding(ring, np.zeros(3), np.array([1.0, 0, 0]))), 1.0)
        hole = 0.05 * ring + [0, 0.5, 0]                            # a small hole beside the axis
        self.assertAlmostEqual(T.winding(hole, np.zeros(3), np.array([1.0, 0, 0])), 0.0)

    def test_uniform_phi(self):
        rng = np.random.default_rng(1); phi = np.sort(rng.uniform(-np.pi, np.pi, 20))
        pu, un = T.uniform_phi(phi)
        self.assertTrue(np.all(np.diff(un) > 0)); self.assertAlmostEqual(float(np.ptp(np.diff(un))), 0.0)
        self.assertLess(np.abs(np.mod(pu - phi + np.pi, 2 * np.pi) - np.pi).max(), 1e-9)
        self.assertLess(abs(float(np.mean(pu - un))), 1e-9)


if __name__ == "__main__":
    unittest.main()
