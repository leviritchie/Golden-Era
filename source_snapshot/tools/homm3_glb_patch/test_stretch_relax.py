"""Tests of the patch lane's stretchRelax op (stretch_relax.py; docs/homm3_glb_patch_lane.md, "Deep hip and knee
flexion").

    python -m unittest tools/homm3_glb_patch/test_stretch_relax.py          # synthetic sheet: cheap, CUDA parity
    python tools/homm3_glb_patch/test_stretch_relax.py --titan              # + the h3_giant_upg heap D3 proof (~15 s)

Synthetic: a flat sheet skinned to two bones with a hard weight seam; bone 1 slides away so the seam row tears past
2x. The relax must cut the torn count, slide only in the sheet's plane, leave non-movable vertices and pinned
(ill-conditioned) groups alone, keep UV-seam copies welded, and give the same bytes on cpu and cuda (a missing CUDA
device is a failure, as in test_cs_device_parity.py). --titan: the retained h3_giant_upg base with the shipped ops plus
the heap D3 body tables must be refused without stretchRelax and pass the lane's tear gate with it.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import cs_numpy as CS  # noqa: E402
import patch_glb as P  # noqa: E402
import stretch_relax as SR  # noqa: E402

OP = {"op": "stretchRelax", "clips": ["Unit_Death"], "ratio": 1.7, "iterations": 1000, "smooth": 0.4}


def sheet(nx=14, ny=5, seam=6.5, dup=True):
    """Unit grid in the xy plane; x < seam on bone 0, x > seam on bone 1. dup: vertex 0 gets a UV-seam copy."""
    V = np.array([[x, y, 0.0] for y in range(ny) for x in range(nx)], np.float64)
    F = []
    for y in range(ny - 1):
        for x in range(nx - 1):
            a = y * nx + x
            F += [[a, a + 1, a + nx], [a + 1, a + nx + 1, a + nx]]
    F = np.array(F, np.int64)
    if dup:                                   # the copy carries the first triangle; the original keeps the rest
        V = np.vstack([V, V[:1]])
        F[0, 0] = len(V) - 1
    J = np.zeros((len(V), 4), np.int64)
    W = np.zeros((len(V), 4))
    J[:, 0] = (V[:, 0] > seam).astype(np.int64)
    W[:, 0] = 1.0
    return V, J, W, F


def mats(shift=2.0, rot180=False):
    Sk = np.stack([np.eye(4), np.eye(4)])
    Sk[1, 0, 3] = shift
    if rot180:
        Sk[1, :3, :3] = np.diag([-1.0, -1.0, 1.0])
    return Sk


def torn(V, J, W, F, Sk, D):
    S, _, _ = CS._skin(V + D, J, W, Sk)
    E = np.unique(np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), 1), axis=0)
    r = np.linalg.norm(S[E[:, 0]] - S[E[:, 1]], axis=1) / np.linalg.norm(V[E[:, 0]] - V[E[:, 1]], axis=1)
    return int((r > 2).sum()), S


class Spec(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(P.spec_errors({"reason": "r", "ops": [OP]}), [])
        self.assertEqual(P.spec_errors({"reason": "r", "ops": [dict(OP, bones=["*UpLeg"], maxMove=0.03)]}), [])

    def test_refusals(self):
        rt = {"op": "rotateTrack", "bone": "T", "clips": ["c"], "axis": [1, 0, 0], "deg": 5}
        bad = [dict(OP, ratio=2.0), dict(OP, ratio=1.0), dict(OP, iterations=0), dict(OP, iterations=1.5),
               dict(OP, smooth=1.5), dict(OP, clips=[]), dict(OP, bones=[]), dict(OP, maxMove=0.5), dict(OP, extra=1)]
        for op in bad:
            self.assertTrue(P.spec_errors({"reason": "r", "ops": [op]}), op)
        # it corrects the re-baked targets, so it must be the last op(s)
        self.assertTrue(P.spec_errors({"reason": "r", "ops": [OP, rt]}))
        self.assertEqual(P.spec_errors({"reason": "r", "ops": [rt, OP, dict(OP, clips=["Unit_Hitted"])]}), [])


class Relax(unittest.TestCase):
    def run_relax(self, V, J, W, F, Sk, movable=None, device="cpu", **kw):
        weld = CS.Weld(V, J, W, F)
        D = np.zeros_like(V)
        mv = np.ones(len(V), bool) if movable is None else movable
        args = dict(ratio=1.7, iterations=400, smooth=0.4)
        args.update(kw)
        out, moved, pinned = SR.relax_batch(weld, V, J, W, [Sk], [D], mv, device=device, **args)
        return out[0], moved[0], pinned[0], weld

    def test_cuts_tears_in_plane_and_welded(self):
        V, J, W, F = sheet()
        Sk = mats()
        n0, _ = torn(V, J, W, F, Sk, np.zeros_like(V))
        D, moved, pinned, weld = self.run_relax(V, J, W, F, Sk)
        n1, _ = torn(V, J, W, F, Sk, D)
        self.assertGreater(n0, 0)
        self.assertLess(n1, n0)
        self.assertEqual(pinned, 0)
        self.assertLess(np.abs(D[:, 2]).max(), 1e-12)               # tangential: the flat sheet stays flat
        np.testing.assert_array_equal(D[-1], D[0])                   # the UV-seam copy moves with its original
        self.assertGreater(moved, 0)

    def test_non_movable_stay(self):
        V, J, W, F = sheet()
        mv = V[:, 0] < 9                                             # bone-1 side past x 9 may not move
        D, _, _, _ = self.run_relax(V, J, W, F, mats(), movable=mv)
        self.assertEqual(np.abs(D[~mv]).max(), 0.0)
        self.assertGreater(np.abs(D[mv]).max(), 0.0)

    def test_ill_conditioned_pinned(self):
        V, J, W, F = sheet(dup=False)
        col = np.isclose(V[:, 0], 7.0)                               # one column half on each bone
        J[col, 0], J[col, 1] = 0, 1
        W[col, :2] = 0.5
        Sk = mats(shift=16.0, rot180=True)                           # 0.5 (I + R180): a singular blend there
        D, _, pinned, _ = self.run_relax(V, J, W, F, Sk)
        self.assertEqual(pinned, int(col.sum()))
        self.assertEqual(np.abs(D[col]).max(), 0.0)

    def test_cpu_cuda_bytes(self):
        import cs_torch
        if cs_torch.torch is None or not cs_torch.torch.cuda.is_available():
            self.fail("stretchRelax CUDA parity needs torch with a CUDA device (no fallback; HOMM3_CS_DEVICE=cpu "
                      "selects the reference in the lane, not here)")
        V, J, W, F = sheet()
        a = self.run_relax(V, J, W, F, mats(), device="cpu")
        b = self.run_relax(V, J, W, F, mats(), device="cuda")
        self.assertEqual(a[0].tobytes(), b[0].tobytes())
        self.assertEqual(float(a[1]), float(b[1]))


def titan() -> int:
    """The h3_giant_upg heap D3 proof on the retained base (docs/homm3_glb_patch_lane.md)."""
    base = ROOT / "artifacts/homm3_glb_patch/h3_giant_upg/base.glb"
    if not base.is_file():
        print("SKIP titan: no retained base", base)
        return 0
    kr = "tools/homm3_glb_patch/key_rotations/"
    shipped = json.loads((ROOT / "tools/homm3_def_retarget/units/h3_giant_upg.json").read_text(encoding="utf-8"))
    rot = {"op": "keyRotations", "table": kr + "h3_giant_upg_heapD3_body_rot.json",
           "sha256": "621171249c17f5779f19a8af4a212dad41326f846703d5e901c4a287169b2bdc", "regrid": True}
    tr = {"op": "keyTranslations", "table": kr + "h3_giant_upg_heapD3_body_tr.json",
          "sha256": "33ebde3ce1e7319412562b499ff44feed072aa393ecc56fb9f54257443db05b9", "regrid": True}
    ops = [*shipped["glbPatch"]["ops"], rot, dict(rot), tr]
    data = base.read_bytes()
    try:
        P.patch_bytes("h3_giant_upg", data, {"reason": "titan heap proof", "ops": ops})
        print("FAIL titan: the heap without stretchRelax was not refused (the proof pose no longer tears)")
        return 1
    except SystemExit as e:
        print("titan heap without stretchRelax: refused as expected:", str(e).split("(")[0][-140:])
    _, rec = P.patch_bytes("h3_giant_upg", data, {"reason": "titan heap proof", "ops": [*ops, dict(OP)]})
    st = rec["csRebake"]["stretch"]
    print("titan heap with stretchRelax: PASS", json.dumps(st), json.dumps(rec["csRebake"]["stretchRelax"][0]["edgesOver2x"]))
    return 0


if __name__ == "__main__":
    want = "--titan" in sys.argv
    argv = [a for a in sys.argv if a != "--titan"]
    res = unittest.main(argv=argv, exit=False).result
    rc = 0 if res.wasSuccessful() else 1
    sys.exit(rc or (titan() if want else 0))
