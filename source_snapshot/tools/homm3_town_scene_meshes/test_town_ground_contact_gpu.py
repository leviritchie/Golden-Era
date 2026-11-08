"""Ground contact: the cuda path reproduces the cpu reference exactly on a staged candidate (town_full3d_ground_contact).

    TOWN_FULL3D_FACTION=castle TOWN_FULL3D_CANDIDATE=zs_v5 python tools/homm3_town_scene_meshes/test_town_ground_contact_gpu.py [--quick]

Compares, cpu against cuda: the lookup's split ground (Ground.split_oversized), every piece's gap (records), the ground lookup on random points over the town, the rest
z-buffer and face ids of every build state and of the fill's subsets, and (unless --quick) the whole anchor() run in
both: the same records, the same final vertices of every bin bit for bit, the same contact gate after it.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import town_full3d_ground_contact as GC  # noqa: E402


def same(a, b, what):
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape or not np.array_equal(a, b, equal_nan=a.dtype.kind == "f"):
        bad = int((a != b).sum()) if a.shape == b.shape else "shape"
        raise SystemExit(f"PARITY FAIL {what}: {bad} differ")


def scene(device, states):
    S, sc, stage, state_keys = GC._stage()
    cat = json.loads((S.OUT / "catalog.json").read_text(encoding="utf-8"))
    return S, sc, stage, state_keys, cat, GC.Scene(sc, stage, S.ENV_KEY, cat, device, state_keys if states else None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="skip the full anchor() comparison")
    a = ap.parse_args()
    import stronghold_full3d_terrain as T
    t0 = time.time()
    *_, cs = scene("cpu", True)
    S, sc, stage_g, state_keys, cat, gg = scene("cuda", True)
    for k in ("H2", "HT", "F"):                       # the lookup's split ground (Ground.split_oversized)
        same(getattr(cs.ground, k), getattr(gg.ground, k), f"split ground {k}")
    print("split ground OK:", cs.ground.split, flush=True)
    rc, rg = cs.records(), gg.records()
    same([r["gapM"] for r in rc], [r["gapM"] for r in rg], "records gap")
    rng = np.random.default_rng(7)
    P = cs.ground.P
    lo, hi = P.min(0), P.max(0)
    Q = lo + rng.random((20000, 3)) * (hi - lo)
    same(cs.ground.gap(Q), gg.ground.gap(Q), "ground gap (random points)")
    for s in state_keys:
        zc, fc, _ = cs.rasters.state(s)
        zg, fg, _ = gg.rasters.state(s)
        same(zc, zg, f"state {s} z"); same(fc, fg, f"state {s} fid")
    sel = [(gi, cs.stage.bins[gi]["f"]) for gi in cs.ground_bins]
    same(cs.rasters.subset(sel)[0], gg.rasters.subset(sel)[0], "ground subset z")
    fl = [r for r in rc if np.isfinite(r["gapM"]) and r["gapM"] > GC.ANCHOR_TOL_M]
    print("records / lookup / rasters OK:", len(rc), "pieces,", len(fl), "floating,", len(state_keys), "states",
          f"{time.time() - t0:.0f} s", flush=True)
    for r in fl[:3]:                                   # one fill step on each of the first floating pieces
        ec = GC.ground_slide(cs, cs.stage.bins[r["bin"]], r["idx"], T)
        eg = GC.ground_slide(gg, gg.stage.bins[r["bin"]], r["idx"], T)
        if (ec is None) != (eg is None):
            raise SystemExit(f"PARITY FAIL ground_slide {r['name']} {r['piece']}: one moved nothing")
        if ec is None:
            continue
        same(sorted(ec["old"]), sorted(eg["old"]), "slide bins")
        for gi in ec["old"]:
            same(cs.stage.bins[gi]["v"], gg.stage.bins[gi]["v"], f"slide {r['name']} {r['piece']} bin {gi}")
        if GC.max_slope_deg(cs, ec) != GC.max_slope_deg(gg, eg):
            raise SystemExit("PARITY FAIL max_slope_deg")
        GC.undo_ground(cs, ec); GC.undo_ground(gg, eg)
    print("ground_slide OK", f"{time.time() - t0:.0f} s", flush=True)
    # the recipe's rule planar (unseen faces): its per-face math on both devices
    import os, types
    import town_full3d_recipe as R
    bi = cs.piece_bins[0]
    src = cs.stage.bins[bi]
    lf = np.arange(0, len(src["f"]), max(1, len(src["f"]) // 500))
    A = np.array([[1 / 1920, 0.0], [0.0, 1 / 1080], [0.01, 0.02]])
    got = {}
    for dev in ("cpu", "cuda"):
        os.environ["TOWN_FULL3D_DEVICE"] = dev
        b = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in src.items()}
        R.Stage.planar(types.SimpleNamespace(bins=[b], sc=cs.sc), 0, lf, A)
        got[dev] = b["uv"]
    os.environ.pop("TOWN_FULL3D_DEVICE")
    same(got["cpu"], got["cuda"], "rule planar uv")
    # per-face maps (a packed atlas's uv charts, town_full3d_step_flap.uv_affine_charts)
    Af = A[None] * (1 + 0.01 * (np.arange(len(lf)) % 7))[:, None, None]
    for dev in ("cpu", "cuda"):
        os.environ["TOWN_FULL3D_DEVICE"] = dev
        b = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in src.items()}
        R.Stage.planar(types.SimpleNamespace(bins=[b], sc=cs.sc), 0, lf, Af)
        got[dev] = b["uv"]
    os.environ.pop("TOWN_FULL3D_DEVICE")
    same(got["cpu"], got["cuda"], "rule planar uv (per-face maps)")
    print("rule planar OK:", len(lf), "faces", flush=True)
    if not a.quick:
        out = {}
        for dev, gs in (("cpu", cs), ("cuda", gg)):
            t1 = time.time()
            before = GC.rest_identity(gs, None)
            moved = GC.anchor(gs, lambda faces=None, gs=gs, before=before: GC.rest_identity(gs, before, faces), T,
                              strict=False)
            out[dev] = (moved, time.time() - t1)
        if json.dumps(out["cpu"][0], default=float) != json.dumps(out["cuda"][0], default=float):
            raise SystemExit("PARITY FAIL anchor records")
        for bi, (bc, bg) in enumerate(zip(cs.stage.bins, gg.stage.bins)):
            same(bc["v"], bg["v"], f"anchored bin {bi} {bc['name']}")
        print("anchor OK:", len(out["cpu"][0]), "pieces;", f"cpu {out['cpu'][1]:.0f} s, cuda {out['cuda'][1]:.0f} s")
    cs.rasters.release(); gg.rasters.release()
    print("ground contact gpu parity OK", f"{time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
