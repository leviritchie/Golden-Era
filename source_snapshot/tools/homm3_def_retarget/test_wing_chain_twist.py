"""wing_chain `twist` channel: opt-in, identity when absent, a rotation about the rest arm axis, mirrored by side.
Runs outside Blender: mathutils is stubbed with the two calls the pose model needs (Matrix.Rotation, Vector).
python -m unittest tools.homm3_def_retarget.test_wing_chain_twist"""

import importlib.util
import math
from pathlib import Path
import sys
import types
import unittest

import numpy as np


def _load():
    if "mathutils" not in sys.modules:
        mu = types.ModuleType("mathutils")

        class Matrix:
            @staticmethod
            def Rotation(ang, n, axis):
                k = np.asarray(axis, float); k = k / np.linalg.norm(k)
                K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
                return np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * K @ K

        mu.Matrix = Matrix
        mu.Vector = lambda v: np.asarray(v, float)
        mu.Quaternion = object
        sys.modules["mathutils"] = mu
    spec = importlib.util.spec_from_file_location("wing_chain_under_test", Path(__file__).resolve().parent / "ext" / "wing_chain.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


wc = _load()
wc._slerp_R = lambda R, t: np.eye(3)      # the test wings rest in their spread attitude (S = I): open is a no-op


def _wing(side):
    """a _Wing with its pose-model fields set directly (no Blender rig), arm along +-X, membrane in X-Y."""
    w = object.__new__(wc._Wing)
    w.s = side
    w.H, w.D = np.array([0.0, -1, 0]), np.array([0.0, 0, 1])
    w.S = np.eye(3)
    w.names = ["a", "b", "c"]
    w.N, w.C = np.array([0.0, 0, 1]), np.array([0.0, 1, 0])
    w.d = np.array([float(side), 0, 0]); w.A = w.d
    w.fsign, w.fsh, w.dsh = 1.0, [0.3, 0.7], [0.4, 0.6]
    return w


class TwistChannel(unittest.TestCase):
    def test_absent_or_zero_is_bit_identical(self):
        w = _wing(1)
        v = {"open": 0.4, "flap": 20.0, "sweep": 5.0, "fold": 10.0, "droop": 7.0}
        base = w.G(v)
        for extra in ({}, {"twist": 0.0}, {"twist": 0}):
            for a, b in zip(base, w.G({**v, **extra})):
                self.assertTrue(np.array_equal(a, b))

    def test_rotates_about_the_arm_axis(self):
        w = _wing(1)
        R0 = w.G({"open": 0.0})[0]; R1 = w.G({"open": 0.0, "twist": 90.0})[0]
        np.testing.assert_allclose(R1 @ w.d, R0 @ w.d, atol=1e-12)          # the arm line stays put
        np.testing.assert_allclose(R1 @ w.N, [0, -1, 0], atol=1e-12)        # membrane normal turned 90 deg about +X

    def test_mirrored_by_side(self):
        L, R = _wing(1), _wing(-1)
        M = np.diag([-1.0, 1, 1])
        for t in (30.0, -55.0):
            gl = L.G({"twist": t, "flap": 15.0})[0]; gr = R.G({"twist": t, "flap": 15.0})[0]
            np.testing.assert_allclose(M @ gl @ M, gr, atol=1e-12)

    def test_opt_in_gate(self):
        self.assertFalse(wc._uses_twist({"anim": {"Move": {"flap": 10}}, "fit": {"params": ["flap"]}}))
        self.assertTrue(wc._uses_twist({"anim": {"Move": {"twist": {"keys": [[0, 0], [1, 40]]}}}}))
        self.assertTrue(wc._uses_twist({"fit": {"params": ["open", "twist"]}}))
        self.assertNotIn("twist", wc.P_ALL)


if __name__ == "__main__":
    unittest.main()
