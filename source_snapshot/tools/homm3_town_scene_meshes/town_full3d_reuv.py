#!/usr/bin/env python3
"""Town full-3D: re-UV the terrain's depth-step curtains instead of fixing their geometry
(docs/homm3_town_curtain_reuv.md).

The full-3D terrain is a screen-space grid projection-textured from the rest frame. Where a near ridge covers far
ground, the grid bridges the step with triangles along the rest camera's rays: edge-on at rest, and at the sweep poses
rubber-sheet bands whose UV is near-degenerate, so one texel column of the ridge's edge is smeared across them. This
pass keeps the geometry and gives those triangles a sane texel density instead:

  (a) select: a triangle is a curtain when its rest forward-depth ratio exceeds RATIO_CAP, or when it spans a depth step
      (ratio > MIN_RATIO) that a reachable proof pose smears past ANISO_CUT (town_full3d_ldi's two cut rules);
  (b) unweld: the curtain triangles get their own copies of their vertices (same position / normal), so no triangle
      that is shown at rest changes its UV;
  (c) unfold: on the curtain's own edge graph, every copied vertex gets s = its geodesic 3D distance (Dijkstra) from
      the curtain's far foot (a curtain vertex shared with the uncut surface and at least as far as its curtain
      neighbours), converted to rest-frame px at the far side's texel density (f_px / z). Its new UV is the rest-frame
      texel at  pixel + s * n_far , n_far the unit gradient of the smoothed rest log-depth (towards the far side). The
      curtain thus samples a band of the far side's own texture, laid out along the stretch direction at the density
      the far ground is painted at, like a world-space planar projection anchored at the foot. A band that would run
      into texels that are not the far side (nearer paint, off the piece) is folded back (triangle wave) at the last
      far-side texel, so it never samples foreign paint.

Textures are never touched. The rest frame changes only where a curtain sliver covers a pixel (edge-on 1-px lines).

    TOWN_FULL3D_CANDIDATE=<fresh seed> python town_full3d_reuv.py --faction <key> apply [--pieces ...]

Faction-agnostic like town_full3d_ldi (it needs each piece's UV to be an affine map of the rest frame; fails closed
otherwise). Refuses a stage whose report already carries a "reuv" section. Proof tier: generated artifact / offline
render. No Meshy, no paid API, no model.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import town_full3d_ldi as L  # noqa: E402

W, H = L.W, L.H
SIGMA_PX = 4.0          # log-depth smoothing for the far-side direction
S_MAX_PX = 256.0        # longest band (rest-frame px) a curtain may sample before it is folded
FAR_TOL = 1.03          # a texel is far side when its rest depth is at least the foot depth / FAR_TOL
FAR_MAX = 1.5           # ... and at most FAR_MAX x the foot depth (never the distant backdrop or painted sky)
SMOOTH_ITERS = 30       # Laplacian smoothing of the band direction over the curtain's edge graph
MARCH_STEP = 2.0


def curtain_mask(v, tris, fov, poses, rule="ratio") -> np.ndarray:
    """rule 'ratio': rest depth ratio > RATIO_CAP only; 'ratio+smear': also the pose-smear step triangles."""
    _fx, _fy, z = L.project(v, fov)
    r = L.depth_ratio(z, tris)
    m = r > L.RATIO_CAP
    step = (r > L.MIN_RATIO) & ~m
    if rule == "ratio+smear" and poses and step.any():
        a = L.pose_aniso(v, tris[step], fov, poses)
        idx = np.flatnonzero(step)
        m[idx[a > L.ANISO_CUT]] = True
    return m


def far_dir(zrest: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Unit direction (per rest px) of increasing smoothed log-depth. Uncovered px are filled from the nearest covered."""
    from scipy.ndimage import distance_transform_edt
    ok = np.isfinite(zrest)
    lz = np.log(np.where(ok, zrest, 1.0))
    if (~ok).any():
        _, (iy, ix) = distance_transform_edt(~ok, return_indices=True)
        lz = lz[iy, ix]
    lz = cv2.GaussianBlur(lz.astype(np.float32), (0, 0), SIGMA_PX).astype(np.float64)
    gy, gx = np.gradient(lz)
    nrm = np.hypot(gx, gy)
    return np.stack([gx, gy], -1) / np.maximum(nrm, 1e-12)[..., None], nrm


def reuv_piece(v, n, uv, tris, fov, poses, rule="ratio", side="far", density=1.0):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra
    v64 = v.astype(np.float64)
    fx, fy, z = L.project(v64, fov)
    A, res = L.uv_affine(uv.astype(np.float64), fx, fy)
    if res > L.AFFINE_TOL_PX:
        raise SystemExit(f"reuv: uv is not an affine map of the rest frame (residual {res:.3f} px)")
    cm = curtain_mask(v64, tris, fov, poses, rule)
    if not cm.any():
        return None
    ct = tris[cm]
    cv_ = np.unique(ct)                                   # original ids of curtain vertices
    loc = np.full(len(v), -1, np.int64)
    loc[cv_] = np.arange(len(cv_))
    lt = loc[ct]                                          # curtain tris in local ids
    # curtain edge graph, weights in rest px at the far side's density
    fpx = density * 0.5 * H / math.tan(math.radians(fov) / 2)   # density < 1 magnifies the band (softer, fewer folds)
    e = np.concatenate([lt[:, [0, 1]], lt[:, [1, 2]], lt[:, [2, 0]]])
    e = np.unique(np.sort(e, 1), axis=0)
    P, zc = v64[cv_], z[cv_]
    zden = np.maximum(zc[e[:, 0]], zc[e[:, 1]]) if side == "far" else np.minimum(zc[e[:, 0]], zc[e[:, 1]])
    wgt = np.linalg.norm(P[e[:, 0]] - P[e[:, 1]], axis=1) * fpx / zden
    wgt = np.maximum(wgt, 1e-6)
    nc = len(cv_)
    G = coo_matrix((np.r_[wgt, wgt], (np.r_[e[:, 0], e[:, 1]], np.r_[e[:, 1], e[:, 0]])), shape=(nc, nc)).tocsr()
    # feet: curtain vertices also used by an uncut triangle and at least as far as every curtain neighbour (1% slack)
    in_main = np.zeros(len(v), bool)
    in_main[np.unique(tris[~cm])] = True
    zmax_nb = zc.copy()
    np.maximum.at(zmax_nb, e[:, 0], zc[e[:, 1]])
    np.maximum.at(zmax_nb, e[:, 1], zc[e[:, 0]])
    zmin_nb = zc.copy()
    np.minimum.at(zmin_nb, e[:, 0], zc[e[:, 1]])
    np.minimum.at(zmin_nb, e[:, 1], zc[e[:, 0]])
    # side 'far': anchored at the far foot, sampling the far side; 'near': anchored at the near lip, sampling the
    # ridge's own paint (the curtain is that ridge's face)
    if side == "far":
        feet = in_main[cv_] & (zc >= zmax_nb / 1.01)
    else:
        feet = in_main[cv_] & (zc <= zmin_nb * 1.01)
    # a component with no foot takes its farthest vertex
    from scipy.sparse.csgraph import connected_components
    ncomp, lab = connected_components(G, directed=False)
    has = np.zeros(ncomp, bool)
    has[lab[feet]] = True
    for c in np.flatnonzero(~has):
        ids = np.flatnonzero(lab == c)
        feet[ids[np.argmax(zc[ids]) if side == "far" else np.argmin(zc[ids])]] = True
    dist, _pred, src = dijkstra(G, directed=False, indices=np.flatnonzero(feet), min_only=True,
                                return_predecessors=True)
    s = np.minimum(dist, S_MAX_PX)
    zfoot = zc[np.where(src >= 0, src, np.arange(nc))]
    # far-side direction and the fold-back march on the piece's own rest depth
    zrest = L.rest_depth(v64, tris, fov)
    ndir, _gn = far_dir(zrest)
    xi, yi = L._pix(fx[cv_], fy[cv_])
    d = ndir[yi, xi]
    d[~np.isfinite(d).all(1)] = (0.0, -1.0)
    if side == "near":
        d = -d
    # smooth the direction along the curtain (a per-vertex gradient swirls the band); feet included
    deg = np.bincount(e.ravel(), minlength=nc).astype(np.float64)
    for _ in range(SMOOTH_ITERS):
        acc = d.copy()
        np.add.at(acc, e[:, 0], d[e[:, 1]])
        np.add.at(acc, e[:, 1], d[e[:, 0]])
        acc /= (deg + 1)[:, None]
        d = acc / np.maximum(np.linalg.norm(acc, axis=1), 1e-9)[:, None]
    # march along n_far: start = first far-side texel (a lip vertex sits on the near paint), reach = last far-side
    # texel of the contiguous run after it
    start = np.full(nc, -1.0)
    reach = np.full(nc, -1.0)
    alive = s > 0
    t = 0.0
    while alive.any() and t < 2 * S_MAX_PX:
        qx = fx[cv_] + d[:, 0] * t
        qy = fy[cv_] + d[:, 1] * t
        inb = (qx >= 0) & (qx < W) & (qy >= 0) & (qy < H)
        qxi, qyi = L._pix(qx, qy)
        zq = zrest[qyi, qxi]
        okq = inb & np.isfinite(zq) & ((zq >= zfoot / FAR_TOL) & (zq <= zfoot * FAR_MAX) if side == "far" else
                                        (zq <= zfoot * FAR_TOL) & (zq >= zfoot / FAR_MAX))
        started = start >= 0
        begin = alive & ~started & okq
        start[begin] = t
        alive &= ~(started & ~okq)
        upd = alive & okq
        reach[upd] = t
        alive &= ~(started & (t - start >= s))
        alive &= inb
        t += MARCH_STEP
    # fold s into the far-side run [start, reach] (triangle wave); a band that never reaches the far side keeps s = 0
    got = start >= 0
    # one fold period per curtain component (its 25th-percentile far-side run): per-vertex periods marble the band
    run = np.where(got, reach - start, np.nan)
    per_c = np.full(ncomp, MARCH_STEP)
    for c in np.unique(lab[got]):
        per_c[c] = max(float(np.nanpercentile(run[lab == c], 25)), MARCH_STEP)
    per = per_c[lab]
    ph = np.mod(s, 2 * per)
    sf = np.where(got, np.where(start < 0, 0, start) + np.where(ph > per, 2 * per - ph, ph), 0.0)
    folded = int((got & (s > per)).sum())
    px_new = np.stack([fx[cv_] + d[:, 0] * sf, fy[cv_] + d[:, 1] * sf], 1)
    # rest px -> uv (invert the affine uv -> px)
    M = np.vstack([A, [0, 0, 1]])
    Minv = np.linalg.inv(M)
    uv_new = (np.c_[px_new, np.ones(nc)] @ Minv.T)[:, :2]
    # feet keep their own uv exactly (seamless with the uncut surface)
    uv_new[feet] = uv[cv_][feet]
    nv = np.concatenate([v, v[cv_]]).astype(np.float32)
    nn = np.concatenate([n, n[cv_]]).astype(np.float32)
    nuv = np.concatenate([uv, uv_new.astype(np.float32)]).astype(np.float32)
    nt = tris.copy()
    nt[cm] = lt + len(v)
    rep = {"curtainTris": int(cm.sum()), "curtainVerts": int(nc), "feet": int(feet.sum()),
           "components": int(ncomp), "bandPx": {"p50": round(float(np.median(s)), 1),
                                                 "p99": round(float(np.percentile(s, 99)), 1),
                                                 "clampedAtMax": int((dist >= S_MAX_PX).sum())},
           "folded": folded, "neverReachedFarSide": int((~got & (s > 0)).sum()),
           "uvAffineResidualPx": round(res, 4)}
    return nv, nn, nuv, nt, rep


# ------------------------------------------------------------------------------------------------ buildings
DEG_ANISO = 20.0        # a building triangle whose 3D -> texel map is this anisotropic has a degenerate (extruded) UV


def reuv_building_piece(v, n, uv, tris, tw, th):
    """Side walls of a relief building: every triangle with a degenerate UV (the extruded silhouette texel) samples
    instead a band of the building's own front paint, walked inward from the silhouette in texture space by its 3D
    geodesic distance from the front edge at the front's own texel density (a world-space layout anchored at the
    edge, folded inside the painted front)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra, connected_components
    from scipy.ndimage import distance_transform_edt
    v64 = v.astype(np.float64)
    X = np.stack([uv[:, 0] * tw, (1 - uv[:, 1]) * th], 1).astype(np.float64)
    P3 = v64[tris]
    E3 = np.stack([P3[:, 1] - P3[:, 0], P3[:, 2] - P3[:, 0]], -1)        # (m, 3, 2)
    X2 = X[tris]
    E2 = np.stack([X2[:, 1] - X2[:, 0], X2[:, 2] - X2[:, 0]], -1)        # (m, 2, 2)
    J = E2 @ np.linalg.pinv(E3)                                          # (m, 2, 3): texel = J dP, J n = 0
    sv = np.linalg.svd(J, compute_uv=False)
    an = sv[:, 0] / np.maximum(sv[:, 1], 1e-9)
    deg = ~(an <= DEG_ANISO)
    if not deg.any() or deg.all():
        return None
    front = ~deg
    dens_t = np.sqrt(sv[:, 0] * sv[:, 1])
    dens = np.zeros(len(v))
    cnt = np.zeros(len(v))
    for k in range(3):
        np.add.at(dens, tris[front, k], dens_t[front])
        np.add.at(cnt, tris[front, k], 1)
    in_front = cnt > 0
    dens = np.where(in_front, dens / np.maximum(cnt, 1), 0.0)
    # the painted front's coverage in texture space, and its inward direction
    mask = np.zeros((th, tw), np.uint8)
    pts = np.round(X[tris[front]] * 4).astype(np.int32)
    cv2.fillPoly(mask, list(pts), 1, lineType=cv2.LINE_8, shift=2)
    mask = mask.astype(bool)
    sd = distance_transform_edt(mask) - distance_transform_edt(~mask)
    sd = cv2.GaussianBlur(sd.astype(np.float32), (0, 0), 2.0).astype(np.float64)
    gy, gx = np.gradient(sd)
    gn = np.maximum(np.hypot(gx, gy), 1e-12)
    ct = tris[deg]
    cv_ = np.unique(ct)
    loc = np.full(len(v), -1, np.int64)
    loc[cv_] = np.arange(len(cv_))
    lt = loc[ct]
    nc = len(cv_)
    e = np.concatenate([lt[:, [0, 1]], lt[:, [1, 2]], lt[:, [2, 0]]])
    e = np.unique(np.sort(e, 1), axis=0)
    P = v64[cv_]
    wgt = np.maximum(np.linalg.norm(P[e[:, 0]] - P[e[:, 1]], axis=1), 1e-9)
    G = coo_matrix((np.r_[wgt, wgt], (np.r_[e[:, 0], e[:, 1]], np.r_[e[:, 1], e[:, 0]])), shape=(nc, nc)).tocsr()
    feet = in_front[cv_]
    if not feet.any():
        return None
    ncomp, lab = connected_components(G, directed=False)
    dist, _pred, src = dijkstra(G, directed=False, indices=np.flatnonzero(feet), min_only=True,
                                return_predecessors=True)
    reachable = np.isfinite(dist)
    srcv = np.where(src >= 0, src, 0)
    s = np.where(reachable, np.minimum(np.where(reachable, dist, 0) * dens[cv_][srcv], S_MAX_PX), 0.0)
    Xc = X[cv_]
    xi = np.clip(Xc[:, 0].astype(int), 0, tw - 1)
    yi = np.clip(Xc[:, 1].astype(int), 0, th - 1)
    d = np.stack([gx[yi, xi] / gn[yi, xi], gy[yi, xi] / gn[yi, xi]], 1)
    deg_n = np.bincount(e.ravel(), minlength=nc).astype(np.float64)
    for _ in range(SMOOTH_ITERS):
        acc = d.copy()
        np.add.at(acc, e[:, 0], d[e[:, 1]])
        np.add.at(acc, e[:, 1], d[e[:, 0]])
        acc /= (deg_n + 1)[:, None]
        d = acc / np.maximum(np.linalg.norm(acc, axis=1), 1e-9)[:, None]
    start = np.full(nc, -1.0)
    reach = np.full(nc, -1.0)
    alive = s > 0
    t = 0.0
    while alive.any() and t < 2 * S_MAX_PX:
        qx = Xc[:, 0] + d[:, 0] * t
        qy = Xc[:, 1] + d[:, 1] * t
        inb = (qx >= 0) & (qx < tw) & (qy >= 0) & (qy < th)
        okq = inb & mask[np.clip(qy.astype(int), 0, th - 1), np.clip(qx.astype(int), 0, tw - 1)]
        started = start >= 0
        start[alive & ~started & okq] = t
        alive &= ~(started & ~okq)
        reach[alive & okq] = t
        alive &= ~(started & (t - start >= s))
        alive &= inb
        t += MARCH_STEP
    got = start >= 0
    run = np.where(got, reach - start, np.nan)
    per_c = np.full(ncomp, MARCH_STEP)
    for c in np.unique(lab[got]):
        per_c[c] = max(float(np.nanpercentile(run[lab == c], 25)), MARCH_STEP)
    per = per_c[lab]
    ph = np.mod(s, 2 * per)
    sf = np.where(got, start + np.where(ph > per, 2 * per - ph, ph), 0.0)
    Xn = Xc + d * sf[:, None]
    uv_new = np.stack([Xn[:, 0] / tw, 1 - Xn[:, 1] / th], 1)
    keep = feet | ~got
    uv_new[keep] = uv[cv_][keep]
    nv = np.concatenate([v, v[cv_]]).astype(np.float32)
    nn = np.concatenate([n, n[cv_]]).astype(np.float32)
    nuv = np.concatenate([uv, uv_new.astype(np.float32)]).astype(np.float32)
    nt = tris.copy()
    nt[deg] = lt + len(v)
    rep = {"degenerateTris": int(deg.sum()), "frontTris": int(front.sum()), "wallVerts": int(nc),
           "feet": int(feet.sum()), "components": int(ncomp),
           "bandPx": {"p50": round(float(np.median(s)), 1), "p99": round(float(np.percentile(s, 99)), 1)},
           "folded": int((got & (s > per)).sum()), "neverReachedPaint": int((~got & (s > 0)).sum()),
           "unreachedFromFront": int((~reachable).sum())}
    return nv, nn, nuv, nt, rep


def apply_buildings(S, a, rp, sr) -> int:
    from PIL import Image
    if "reuvBuildings" in sr:
        raise SystemExit("reuv apply-buildings: the stage already carries a reuvBuildings pass (re-seed the candidate)")
    layers = sorted(p.name for p in S.STAGE.iterdir() if p.is_dir() and p.name.startswith(S.PREFIX)
                    and p.name != S.ENV_KEY)
    if a.layers != "all":
        want = {S.PREFIX + k for k in a.layers.split(",") if k}
        missing = want - set(layers)
        if missing:
            raise SystemExit(f"reuv apply-buildings: no staged layer {sorted(missing)}")
        layers = [x for x in layers if x in want]
    rep = {"schema": "town_full3d_reuv_buildings.v1", "degAniso": DEG_ANISO, "sMaxPx": S_MAX_PX, "layers": {}}
    for layer in layers:
        for mb in sorted((S.STAGE / layer).glob("Mesh_*.bytes")):
            tex = mb.with_name(mb.stem + "_albedo.png")
            if not tex.is_file():
                continue
            v, n, uv, subs = L.read_bin(mb)
            if len(subs) != 1:
                raise SystemExit(f"reuv: {mb} has {len(subs)} submeshes (expected 1)")
            tw, th = Image.open(tex).size
            out = reuv_building_piece(v, n, uv, subs[0].astype(np.int64), tw, th)
            if out is None:
                continue
            nv, nn, nuv, nt, prep = out
            L.write_bin(mb, nv, nn, nuv, nt)
            rep["layers"].setdefault(layer, {})[mb.stem] = prep
            print(layer, mb.stem, json.dumps(prep), flush=True)
    rep["proofTier"] = "generated artifact / offline render"
    sr["reuvBuildings"] = rep
    rp.write_text(json.dumps(sr, indent=1), encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["apply", "apply-buildings"])
    ap.add_argument("--layers", default="tbfaholy", help="apply-buildings: comma list of layer keys, or 'all'")
    ap.add_argument("--faction", required=True)
    ap.add_argument("--pieces", default="Mesh_Terrain,Mesh_TerrainNear_0,Mesh_TerrainNear_1")
    ap.add_argument("--rule", choices=["ratio", "ratio+smear"], default="ratio")
    ap.add_argument("--side", choices=["far", "near"], default="far")
    ap.add_argument("--density", type=float, default=1.0, help="texel density x the painted density at that depth")
    a = ap.parse_args()
    import stronghold_full3d_scene as S
    if not S.CANDIDATE:
        raise SystemExit("reuv apply: set TOWN_FULL3D_CANDIDATE (the shipped outputs are never rewritten)")
    rp = S.WORK / "stage_report.json"
    sr = json.loads(rp.read_text(encoding="utf-8"))
    if a.cmd == "apply-buildings":
        return apply_buildings(S, a, rp, sr)
    if "reuv" in sr or "ldi" in sr:
        raise SystemExit("reuv apply: the stage already carries a reuv/ldi pass (re-seed the candidate)")
    sc = S.Scene()
    fov = float(sc.cam["fov"])
    poses = L.local_poses(sc, S)
    pdir = S.STAGE / S.ENV_KEY
    rep = {"schema": "town_full3d_reuv.v1", "fov": fov, "poses": len(poses), "sMaxPx": S_MAX_PX, "rule": a.rule, "side": a.side, "density": a.density, "pieces": {}}
    for name in [p for p in a.pieces.split(",") if p]:
        mb = pdir / f"{name}.bytes"
        if not mb.is_file():
            raise SystemExit(f"reuv: {mb} missing")
        v, n, uv, subs = L.read_bin(mb)
        if len(subs) != 1:
            raise SystemExit(f"reuv: {name} has {len(subs)} submeshes (expected 1)")
        out = reuv_piece(v, n, uv, subs[0].astype(np.int64), fov, poses, a.rule, a.side, a.density)
        if out is None:
            rep["pieces"][name] = {"curtainTris": 0}
            continue
        nv, nn, nuv, nt, prep = out
        L.write_bin(mb, nv, nn, nuv, nt)
        rep["pieces"][name] = prep
        print(name, json.dumps(prep), flush=True)
    rep["proofTier"] = "generated artifact / offline render"
    sr["reuv"] = rep
    rp.write_text(json.dumps(sr, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
