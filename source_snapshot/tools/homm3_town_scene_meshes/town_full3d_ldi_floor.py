#!/usr/bin/env python3
"""Floor clamp of the terrain back layers (an opt-in step after town_full3d_ldi.py apply; docs/
homm3_town_layered_depth_backfill.md "Floor clamp").

The LDI back layer continues the far surface under a ridge by inverse-depth push-pull. Where the far side it continues
descends (a terrace dropping towards the camera), the continuation runs on below the painted floor plane (T.Floor). A
reachable pose that looks over the ridge then passes above that sunken sheet and meets nothing: an undrawn pixel whose
ray meets the painted floor inside the far cap, which town_full3d_zero_streak counts as a ground hole (Castle
rx_ldi_zone_old_nfix: up to 476 px at the forward sweeps under the blacksmith's foot, 550 px there with no building).

The clamp is driven by the holes themselves. At every reachable pose of the certificate (town_full3d_zero_streak.
reachable_cams: default, pans, sweeps, the 36-pose loop) the environment alone is rendered, and each ground-hole px's
floor hit is mapped back to its rest px (hole_map). Only *pushed* back vertices (ones the LDI moved behind their main
copy, so hidden at rest) that lie below the floor plane and within HOLE_FEATHER_PX of such a rest px move: up their own
rest ray towards the floor plane, fully within HOLE_CORE_PX and linearly less out to the feather, never nearer than
BEHIND x the main surface's rest depth at their pixel (they stay hidden at rest); the moved vertices are then relaxed
under the ratio cap (town_full3d_ldi.relax_to_cap). Clamping every below-floor vertex instead (26236 on Castle) closed
the same holes but raised the revealed back-terrain streaks from 13941 to 28172 px summed over the poses (the raised
sheet shows over the cottages at the right sweeps), so the clamp stays local to the holes.
Unpushed vertices - the boundary welded to the main surface, the cut cells drawn at rest - never move, and the
backstop (Mesh_Back_*_Far) stays behind, so the rest frame is unchanged. terrain_streak.npz back_P and the stage report
(ldi.sha256, ldi.floorClamp) are rewritten to match. Proof tier: generated artifact / offline render.

    TOWN_FULL3D_FACTION=castle TOWN_FULL3D_CANDIDATE=<c> python town_full3d_ldi_floor.py apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import town_full3d_ldi as L  # noqa: E402

PUSHED_MIN = 1.01      # a back vertex this factor behind the main rest depth at its pixel was pushed by the LDI
HOLE_CORE_PX = 8.0     # rest px from a ground-hole floor hit inside which a below-floor back vertex is fully clamped
HOLE_FEATHER_PX = 40.0  # ... and out to which the clamp fades linearly to nothing
HOLE_LOOP = 36         # the certificate's loop poses (town_full3d_zero_streak --loop default)


def floor_clamp(zb: np.ndarray, zmain: np.ndarray, zfloor: np.ndarray, tris: np.ndarray, weight: np.ndarray | None = None,
                cap: float = L.RATIO_CAP) -> tuple[np.ndarray, dict]:
    """New rest-ray depths of one back layer. zb: its vertex depths; zmain: the main surface's rest depth at each
    vertex's pixel (inf / nan where it draws nothing); zfloor: the floor plane's depth on each vertex's ray (inf above
    the horizon); weight: the clamp's strength per vertex in [0, 1] (None: 1 everywhere). Only pushed vertices below
    the floor with weight > 0 move, towards max(zfloor, BEHIND * zmain) by their weight; the moved set is then relaxed
    (deeper only) until every triangle is within cap."""
    zb = np.asarray(zb, np.float64)
    zm = np.asarray(zmain, np.float64)
    zf = np.asarray(zfloor, np.float64)
    wt = np.ones(len(zb)) if weight is None else np.clip(np.asarray(weight, np.float64), 0.0, 1.0)
    pushed = np.isfinite(zm) & (zb > zm * PUSHED_MIN)
    below = pushed & np.isfinite(zf) & (zb > zf) & (wt > 0)
    tgt = np.maximum(np.where(np.isfinite(zf), zf, 0.0), np.where(np.isfinite(zm), zm, 0.0) * L.BEHIND)
    z = np.where(below, zb + wt * (tgt - zb), zb)
    z = L.relax_to_cap(z, np.asarray(tris, np.int64), below, cap)
    rep = {"pushedVerts": int(pushed.sum()), "belowFloorVerts": int(below.sum()),
           "raisedVerts": int((z < zb - 1e-9).sum()), "deeperAfterRelax": int((z > zb + 1e-9).sum()),
           "maxRatioAfter": round(float(L.depth_ratio(z, tris).max()) if len(tris) else 0.0, 4)}
    if rep["maxRatioAfter"] > cap + 1e-6:
        raise SystemExit(f"ldi floor: a back triangle is over the cap after the clamp ({rep['maxRatioAfter']})")
    return z, rep


def hole_map(sc, rows: dict, S, T) -> tuple[np.ndarray, dict]:
    """Rest px (H x W bool) that a ground-hole px of a reachable pose sees on the painted floor: the environment
    alone at every certificate pose (town_full3d_zero_streak.reachable_cams), each undrawn px whose ray meets the floor
    plane inside T.FAR_CAP_M mapped through its floor hit to the rest frame."""
    import town_full3d_t2_paint as TP
    import town_full3d_zero_streak as Z
    import town_t2_streak_map as SM
    P, _uv, F, *_ = SM.load_bins(sc, rows, [S.ENV_KEY])
    floor = T.Floor(sc.cam)
    M = np.zeros((L.H, L.W), bool)
    worst, wpose = 0, None
    for k, cam in Z.reachable_cams(sc, HOLE_LOOP).items():
        _z, fid = TP.zbuffer(cam, P, F, sup=1)
        vis = fid >= 0
        dw = Z.world_points(cam, np.where(vis, np.nan, 1.0)) - cam["pos"][None, None]
        dw /= np.maximum(np.linalg.norm(dw, axis=-1, keepdims=True), 1e-12)
        nd = dw @ floor.n
        th = (floor.d - float(floor.n @ (cam["pos"] - sc.cam["pos"]))) / np.where(np.abs(nd) > 1e-12, nd, 1e-12)
        g = (~vis) & (th > 0) & (th < T.FAR_CAP_M)
        if int(g.sum()) > worst:
            worst, wpose = int(g.sum()), k
        px, py, _zc = T.project(sc.cam, cam["pos"][None] + dw[g] * th[g][:, None])
        ok = (px >= 0) & (px < L.W) & (py >= 0) & (py < L.H)
        M[py[ok].astype(int), px[ok].astype(int)] = True
    return M, {"envMaxGroundHolePx": worst, "envWorstPose": wpose, "holeRestPx": int(M.sum())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["apply"])
    ap.parse_args()
    import stronghold_full3d_scene as S
    import stronghold_full3d_terrain as T
    if not S.CANDIDATE:
        raise SystemExit("ldi floor: set TOWN_FULL3D_CANDIDATE (the shipped outputs are never rewritten)")
    sc = S.Scene()
    fov = float(sc.cam["fov"])
    rp = S.WORK / "stage_report.json"
    sr = json.loads(rp.read_text(encoding="utf-8"))
    ldi = sr.get("ldi")
    if not ldi:
        raise SystemExit("ldi floor: the stage report has no ldi section (run town_full3d_ldi.py apply first)")
    if "floorClamp" in ldi:
        raise SystemExit("ldi floor: already applied to this candidate (re-seed to apply again)")
    npz = S.OUT / ldi["file"]
    if hashlib.sha256(npz.read_bytes()).hexdigest() != ldi["sha256"]:
        raise SystemExit(f"ldi floor: {npz} differs from the stage report's ldi.sha256")
    with np.load(npz) as d:
        data = dict(d.items())
    from scipy.ndimage import distance_transform_edt
    floor = T.Floor(sc.cam)
    pdir = S.STAGE / S.ENV_KEY
    holes, hrep = hole_map(sc, json.loads(S.ROWS.read_text(encoding="utf-8")), S, T)
    print("holes", json.dumps(hrep), flush=True)
    hdist = distance_transform_edt(~holes)
    back_P, off, rep = [], 0, {}
    for name, pr in ldi["pieces"].items():
        if "backPiece" not in pr:
            continue
        v, _n, _uv, subs = L.read_bin(pdir / f"{name}.bytes")
        zr = L.rest_depth(v, np.concatenate(subs).astype(np.int64), fov)
        bpath = pdir / f"{pr['backPiece']}.bytes"
        vb, nb, uvb, sb = L.read_bin(bpath)
        tb = np.concatenate(sb).astype(np.int64)
        bx, by, bz = L.project(vb.astype(np.float64), fov)
        xi, yi = L._pix(bx, by)
        inv = floor.inv_depth(by)          # 1 / camera depth (painting m); local depth = camera depth x scale
        zf = np.where(inv > 0, sc.scale / np.maximum(inv, 1e-12), np.inf)
        wt = np.clip((HOLE_FEATHER_PX - hdist[yi, xi]) / (HOLE_FEATHER_PX - HOLE_CORE_PX), 0.0, 1.0)
        z, r = floor_clamp(bz, zr[yi, xi], zf, tb, wt)
        vn = vb.astype(np.float64) * (z / bz)[:, None]
        stored = data["back_P"][off: off + len(vb)]
        if stored.shape != vb.shape or np.abs(stored - vb).max() > 1e-3:
            raise SystemExit(f"ldi floor: terrain_streak.npz back_P does not hold {pr['backPiece']} at offset {off}")
        L.write_bin(bpath, vn, nb, uvb, tb)
        back_P.append(vn)
        off += len(vb)
        if "stopPiece" in pr:
            vs = L.read_bin(pdir / f"{pr['stopPiece']}.bytes")[0]
            back_P.append(data["back_P"][off: off + len(vs)])
            off += len(vs)
        rep[pr["backPiece"]] = r
        print(pr["backPiece"], json.dumps(r), flush=True)
    if off != len(data["back_P"]):
        raise SystemExit(f"ldi floor: back pieces hold {off} vertices, terrain_streak.npz back_P {len(data['back_P'])}")
    data["back_P"] = np.concatenate(back_P)
    np.savez_compressed(npz, **data)
    ldi["sha256"] = hashlib.sha256(npz.read_bytes()).hexdigest()
    ldi["floorClamp"] = {"schema": "town_full3d_ldi_floor.v1", "pushedMin": PUSHED_MIN, "behind": L.BEHIND,
                         "holeCorePx": HOLE_CORE_PX, "holeFeatherPx": HOLE_FEATHER_PX, "holeLoop": HOLE_LOOP,
                         "holesBefore": hrep,
                         "pieces": rep, "proofTier": "generated artifact / offline render"}
    rp.write_text(json.dumps(sr, indent=1), encoding="utf-8")
    print(json.dumps({"sha256": ldi["sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
