"""Conflux full-3D phase 6b: ridge-curtain cut and far-side back layer.

The phase-5 terrain is a screen-space grid (conflux_full3d_env.terrain_mesh). Where a near ridge occludes far terrain
the grid bridges the depth step with triangles that run almost along the rest camera's rays: invisible from the
default frame, stretched into streak bands from every pan pose (phase-6 diagnosis: 1,713 triangles with forward-depth
ratio > 1.25, median longest edge 41 m, all in the upper half of the frame).

One fix:
  * cut every terrain triangle whose rest-camera forward-depth ratio (max/min over its vertices) exceeds RATIO_CAP;
  * add a back layer: a copy of the grid cells on the near side of each cut, pushed back along their own rest rays
    onto a continuation of the far surface (normalised-convolution push-pull of the far side's depth), so the rest
    frame's cut cells stay covered at exactly the same screen positions and a moved camera sees far terrain continue
    under the ridge instead of a curtain.

Rest-frame registration: back-layer vertices keep their screen position (they move along their own rest ray). The
cut cells themselves keep their own frame UV and normal (they are the only back-layer pixels visible from the rest
pose); vertices deeper under the ridge (hidden behind it at rest) take the texture and normal of the far side,
mirrored across the silhouette, so the continuation is far-side ground and not a smear of the ridge's paint.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import distance_transform_edt, gaussian_filter

RATIO_CAP = 1.25        # max/min rest forward depth over a terrain triangle's vertices
EXT_CELLS = 40          # back layer reaches this many grid cells (3 px each) under the near side of a cut
SIGMA_CELLS = 3.0       # far-depth push-pull smoothing
BEHIND = 1.02           # back-layer depth at least this factor behind the main surface on the same ray


def grid_topology(nx: int, ny: int) -> np.ndarray:
    j, i = np.meshgrid(np.arange(ny - 1), np.arange(nx - 1), indexing="ij")
    a = (j * nx + i).ravel()
    return np.concatenate([np.stack([a, a + 1, a + nx], 1), np.stack([a + 1, a + nx + 1, a + nx], 1)])


def depth_ratio(zc: np.ndarray, tris: np.ndarray) -> np.ndarray:
    zt = zc[tris]
    return zt.max(1) / np.maximum(zt.min(1), 1e-9)


def apply(ctx, grid: dict) -> dict:
    """Cut the bridging triangles out of grid["tris"] (in place) and return the back layer:
    {"P", "n", "fx", "fy" (texture source frame position), "tris", "report"}. Vertex order of P is the back layer's own."""
    from conflux_full3d_env import rays

    ny, nx = grid["P"].shape[:2]
    P = grid["P"].reshape(-1, 3)
    n = grid["n"].reshape(-1, 3)
    fx, fy = grid["fx"].ravel(), grid["fy"].ravel()
    keep = grid["keep"].ravel()
    fwd = np.asarray(ctx.cam["fwd"], np.float64)
    zc = (P - ctx.cpos) @ fwd
    tris = grid["tris"]
    ratio = depth_ratio(zc, tris)
    cut = ratio > RATIO_CAP
    ct = tris[cut]
    # Far vertices of each cut triangle (within the cap of its farthest vertex) are the silhouette's far side B; the
    # rest of the triangle (including a middle vertex of a three-level step) is its near side.
    zmax = zc[ct].max(1, keepdims=True)
    far_v = zc[ct] >= zmax / RATIO_CAP
    B = np.zeros(len(P), bool)
    B[ct[far_v]] = True
    near_cut = np.zeros(len(P), bool)
    near_cut[ct[~far_v]] = True
    B &= ~near_cut          # a vertex on the near side of any cut is pushed back (its main copy stays put)
    Bg = B.reshape(ny, nx)
    dist, (bi, bj) = distance_transform_edt(~Bg, return_indices=True)
    nb = (bi * nx + bj).ravel()                      # nearest far-side vertex
    zB = zc[nb]
    Ecand = keep & ~B & (dist.ravel() <= EXT_CELLS) & (zc < zB / RATIO_CAP)
    E = Ecand | near_cut
    # Far surface support: kept vertices near a silhouette that are not on its near side.
    S = keep & ~E & (dist.ravel() <= EXT_CELLS + 3 * SIGMA_CELLS) & (zc >= zB / RATIO_CAP)
    num = gaussian_filter(np.where(S, zc, 0.0).reshape(ny, nx), SIGMA_CELLS).ravel()
    den = gaussian_filter(S.astype(np.float64).reshape(ny, nx), SIGMA_CELLS).ravel()
    # Where the far side's own neighbourhood is thin, the nearest silhouette vertex anchors the depth.
    w0 = 0.05
    zb = (num + w0 * zB) / (den + w0)
    # Texture/normal source for vertices under the ridge: the mirror of the vertex across its nearest silhouette
    # vertex, if that lands on far-side ground; else the silhouette vertex itself.
    gi, gj = np.divmod(np.arange(len(P)), nx)
    mi = np.clip(2 * bi.ravel() - gi, 0, ny - 1)
    mj = np.clip(2 * bj.ravel() - gj, 0, nx - 1)
    mirror = mi * nx + mj
    m_ok = keep[mirror] & ~E[mirror] & (np.abs(np.log(np.maximum(zc[mirror], 1e-9) / zB)) < np.log(RATIO_CAP))
    src = np.where(m_ok, mirror, nb)
    src = np.where(near_cut, np.arange(len(P)), src)   # visible at rest: own paint and normal
    # (1) Extension: full grid topology over the silhouette's neighbourhood (at least one E vertex, all kept), the
    # cut cells included, on the continued far surface: what a moved camera sees under the ridge.
    layer = keep & (dist.ravel() <= EXT_CELLS + 1)
    topo = grid_topology(nx, ny)
    bt = topo[layer[topo].all(1) & E[topo].any(1) & keep[topo].all(1)]
    # Hidden at rest: a copy nearer than the continued far surface moves onto it; the rest stay on the main surface.
    pushed = ~B & (zb > zc * BEHIND)
    zl = np.where(pushed, zb, zc)
    src = np.where(pushed, src, np.arange(len(P)))
    rb = depth_ratio(zl, bt)
    # Where the continued far surface itself steps (two far layers behind one ridge, or a far slope beside its
    # silhouette), an extension cell would be a new curtain: it gets its own vertex copies, each pushed to within the
    # cap of the cell's farthest one (a flat far-layer tile; hidden at rest).
    over = rb > RATIO_CAP
    ot = bt[over]
    zo = zl[ot]
    zo = np.maximum(zo, zo.max(1, keepdims=True) / RATIO_CAP)
    bt = bt[~over]
    used = np.unique(bt)
    remap = np.full(len(P), -1, np.int64)
    remap[used] = np.arange(len(used))
    # (2) Cut-cell patches: each cut triangle again with its own vertex copies: far vertices at their own point,
    # near vertices pushed back only as far as the cap needs (the least change to the rest frame's perspective
    # interpolation). Same rays, own paint and normal: the rest frame shows the same cell, now inside the cap, in
    # front of the extension's copy of that cell, which shares its far edge.
    zt = zc[ct]
    zp = np.where(far_v, zt, np.maximum(zt, zmax / RATIO_CAP))
    pv = np.concatenate([ct.ravel(), ot.ravel()])
    all_v = np.concatenate([used, pv])
    zall = np.concatenate([zl[used], zp.ravel(), zo.ravel()])
    srcall = np.concatenate([src[used], ct.ravel(), src[ot.ravel()]])
    d = rays(ctx.cam, fx[all_v], fy[all_v])
    Pb = ctx.cpos + d * (zall / (d @ fwd))[:, None]
    exact = np.concatenate([~pushed[used], far_v.ravel(), (zo == zc[ot]).ravel() & ~pushed[ot.ravel()]])
    Pb[exact] = P[all_v[exact]]
    nb_ = n[srcall]
    tb = np.concatenate([remap[bt], len(used) + np.arange(len(pv)).reshape(-1, 3)])
    ratio_after = depth_ratio((Pb - ctx.cpos) @ fwd, tb)
    if len(tb) and ratio_after.max() > RATIO_CAP + 1e-6:
        raise SystemExit(f"curtain: back layer triangle over the cap ({ratio_after.max():.4f})")
    grid["tris"] = tris[~cut]
    grid["curtainCut"] = ct
    rep = {"ratioCap": RATIO_CAP, "cutTris": int(cut.sum()), "maxRatioBefore": round(float(ratio.max()), 3),
           "farSideVerts": int(B.sum()), "backVerts": int(len(Pb)), "backTris": int(len(tb)), "extensionTris": int(len(bt)),
           "extensionTilesFlattened": int(over.sum()), "cutCellPatches": int(len(ct)),
           "backMaxRatio": round(float(ratio_after.max()), 4),
           "extCells": EXT_CELLS, "sigmaCells": SIGMA_CELLS, "mirroredSources": int((m_ok & E & ~near_cut).sum())}
    return {"P": Pb, "n": nb_, "fx": fx[srcall], "fy": fy[srcall], "tris": tb, "report": rep}


def piece_uv(piece: dict, fx: np.ndarray, fy: np.ndarray, W: int, H: int) -> np.ndarray:
    """The UV a terrain piece's texture gives frame position (fx, fy) (conflux_full3d_nearfield.piece_mesh)."""
    if piece["id"] < 0:
        uv = np.stack([fx / (W - 1), 1 - fy / (H - 1)], -1)
    else:
        x0, y0, x1, y1 = piece["box"]
        s = piece["scale"]
        tw, th = round((x1 - x0) * s), round((y1 - y0) * s)
        uv = np.stack([(fx - x0 + 0.5) * s / tw, 1 - (fy - y0 + 0.5) * s / th], -1)
    return np.clip(uv, 0, 1).astype(np.float32)


def split_back(back: dict, pieces: dict, piece_of, W: int, H: int) -> dict:
    """Back-layer triangles per terrain piece (by the centroid of their texture sources, so a cut cell keeps the
    texture its piece shows at rest): {piece name: (P, n, uv, tris)}."""
    t = back["tris"]
    pid = piece_of(back["fx"][t].mean(1), back["fy"][t].mean(1))
    out = {}
    for nm, pc in pieces.items():
        tt = t[pid == pc["id"]]
        if not len(tt):
            continue
        used = np.unique(tt)
        remap = np.full(len(back["P"]), -1, np.int64)
        remap[used] = np.arange(len(used))
        out[nm] = (back["P"][used], back["n"][used], piece_uv(pc, back["fx"][used], back["fy"][used], W, H), remap[tt])
    return out


def streak_arrays(ctx, grid: dict, back: dict) -> dict:
    """What the validator re-measures: every shipped terrain triangle (main pieces after the cut, and the back layer)
    in painting-world space, with the rest camera; and the cut triangles, for the validator's negative check."""
    return {"main_P": grid["P"].reshape(-1, 3).astype(np.float64), "main_tris": grid["tris"].astype(np.int32),
            "back_P": back["P"].astype(np.float64), "back_tris": back["tris"].astype(np.int32),
            "cut_tris": grid["curtainCut"].astype(np.int32),
            "cpos": np.asarray(ctx.cpos, np.float64), "cam_fwd": np.asarray(ctx.cam["fwd"], np.float64),
            "ratio_cap": np.array(RATIO_CAP)}
