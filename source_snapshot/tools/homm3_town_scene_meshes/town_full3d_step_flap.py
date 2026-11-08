#!/usr/bin/env python3
"""Full-3D towns: the residual depth-step rule (recipe repair rule `flap`; docs/homm3_town_scene_methodology_v2.md,
"Residual depth steps: tear and flap").

The conflict it resolves (Castle zs_v3, 2026-10-01): a Meshy layer's residual (Mesh_BodyRest_<l> and the other
ray-role pieces) is one continuous sheet. Where its depth target has a step - two body parts at different depths
side by side (a pole at 89 m in front of a wall at 103 m), with the residual fringe between them - the sheet bridges
the step with sub-pixel faces whose vertices span the step (R1 inside a building). Those faces are hidden or almost
hidden at rest, so at a sweep they stretch across the opening: the zero-streak certificate counts them as streak
behind objects. Dropping them opens the seam instead (seams_v1 counts the see-through gap), because they were the
only surface there: each gate fails whichever way the face goes.

The rule: a failing residual face that bridges a step (its vertex depths differ by more than STEP_EPS) is torn out
(the recipe's own drop / card choice: drop when no state shows it at rest, else card), and the far side of the step
gets a flap - a sheet at the far side's own depth, on the rest rays of the near side's px, over the px the poses
can reveal there (the opening between the near side's rest front and the far side's depth at each reachable pose,
plus FLAP_PAD_PX). The flap is hidden at rest by the layer's own front (FLAP_HIDE x nearer on every flap px), so the
rest frame does not change, and at a sweep the opening shows the far side continuing instead of a stretched face or
a hole: the seam's fill test sees a surface at the far side's depth, and the certificate sees no stretched texels
(the flap's texels are the residual's own sprite texels mirrored across the lip, one rest px per rest px). Its uv
comes from the residual's own affine rest-px -> uv map, which is checked (FLAP_UV_TOL texels) and fails closed.

Proof tier: generated artifact (offline raster). Unit test: test_town_full3d_step_flap.py.
"""
from __future__ import annotations

import math

import numpy as np

STEP_EPS = 0.02        # a face whose vertex depths differ by more than this ratio bridges a depth step
FLAP_HIDE = 1.01       # every flap px lies at least this factor behind the layer's own rest front there
FLAP_PAD_PX = 2.0      # px added to each flap px's largest pose opening
FLAP_RMAX_PX = 64      # cap on how far a flap reaches from its lip (rest px)
FLAP_UV_TOL = 0.5      # texels: largest allowed deviation of the residual's uv from an affine map of rest px


def step_faces(z_face: np.ndarray, eps: float = STEP_EPS) -> np.ndarray:
    """Mask of faces whose three vertex depths (n, 3) differ by more than eps (ratio): faces that bridge a step."""
    z = np.asarray(z_face, np.float64)
    return z.max(1) > (1.0 + eps) * np.maximum(z.min(1), 1e-12)


def far_vertices(F: np.ndarray, z: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """The far side of each step face: its vertices at or beyond the geometric mean of its depth range."""
    f = np.asarray(F, np.int64)[np.asarray(faces, np.int64)]
    if not len(f):
        return np.zeros(0, np.int64)
    zf = np.asarray(z, np.float64)[f]
    mid = np.sqrt(zf.max(1) * zf.min(1))
    return np.unique(f[zf >= mid[:, None]])


def uv_affine(px: np.ndarray, py: np.ndarray, uv: np.ndarray, tex_wh) -> np.ndarray:
    """The 3x2 affine map rest px -> uv of a residual piece; fails closed when the uv is not one."""
    A = np.c_[px, py, np.ones(len(px))]
    M, *_ = np.linalg.lstsq(A, np.asarray(uv, np.float64), rcond=None)
    dev = (np.abs(A @ M - uv) * np.asarray(tex_wh, np.float64)[None]).max() if len(px) else 0.0
    if dev > FLAP_UV_TOL:
        raise SystemExit(f"flap: the residual's uv is not an affine map of rest px ({dev:.3f} texels off)")
    return M


def uv_charts(f: np.ndarray, uv: np.ndarray) -> np.ndarray:
    """Chart id per face: faces are linked by a shared vertex, and vertices by an identical uv (the coincident corners
    of a triangle soup). Two packed crops of one atlas never share a uv, so each crop is its own chart (Castle zs_v6
    2026-10-01: a Mesh_Cloth_ bin packs crops of two source bins, 162 texels off one affine map)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    n = len(uv)
    key = np.ascontiguousarray(np.asarray(uv, np.float64)).view(np.dtype((np.void, 16))).ravel()
    _, first = np.unique(key, return_inverse=True)
    rep = np.zeros(first.max() + 1 if n else 0, np.int64)
    rep[first[::-1]] = np.arange(n)[::-1]               # the first vertex of each identical-uv group
    a = np.r_[f[:, 0], f[:, 1], np.arange(n)]
    b = np.r_[f[:, 1], f[:, 2], rep[first]]
    _, comp = connected_components(coo_matrix((np.ones(len(a)), (a, b)), shape=(n, n)), directed=False)
    return comp[f[:, 0]]


def uv_affine_charts(px: np.ndarray, py: np.ndarray, f: np.ndarray, uv: np.ndarray, shown: np.ndarray, tex_wh):
    """Per chart (uv_charts), the 3x2 affine map rest px -> uv fitted to the vertices of its rest-shown faces (shown:
    face ids). -> (chart per face, {chart: map}, {chart: texels off}). Only a chart whose uv is a rest projection has a
    map: one with fewer than 3 shown vertices, or whose uv is off an affine map by more than FLAP_UV_TOL texels (a
    Meshy body's mirrored back-fill chart, a few of whose faces the rest raster still reaches at the silhouette:
    Castle zs_v6 Mesh_Body_tbcsdw_6, 31.8 texels), has none and is listed with its deviation."""
    ch = uv_charts(f, uv)
    maps, off = {}, {}
    for c in np.unique(ch[shown]):
        vv = np.unique(f[shown[ch[shown] == c]].ravel())
        if len(vv) < 3:
            continue
        try:
            maps[int(c)] = uv_affine(px[vv], py[vv], uv[vv], tex_wh)
        except SystemExit:
            A = np.c_[px[vv], py[vv], np.ones(len(vv))]
            M, *_ = np.linalg.lstsq(A, uv[vv], rcond=None)
            off[int(c)] = round(float((np.abs(A @ M - uv[vv]) * np.asarray(tex_wh, np.float64)[None]).max()), 3)
    return ch, maps, off


def px_world(cam: dict, x, y, z) -> np.ndarray:
    """World points on the camera's rays through frame px (x, y) (continuous px coordinates) at forward depth z."""
    from stronghold_full3d_common import W, H
    t = math.tan(math.radians(cam["fov"]) / 2)
    xn = (np.asarray(x, np.float64) / W * 2 - 1) * t * W / H
    yn = (1 - np.asarray(y, np.float64) / H * 2) * t
    d = (np.asarray(cam["fwd"])[None] + xn[:, None] * np.asarray(cam["right"])[None]
         + yn[:, None] * np.asarray(cam["up"])[None])
    return np.asarray(cam["pos"])[None] + d * np.asarray(z, np.float64)[:, None]


def flap_grid(lip_x, lip_y, lip_z, lip_v, z_front: np.ndarray, opening, frame_wh,
              rmax: int = FLAP_RMAX_PX, hide: float = FLAP_HIDE, pad: float = FLAP_PAD_PX,
              eps: float = STEP_EPS) -> dict | None:
    """The flap behind the near side of a set of lip vertices (rest px lip_x, lip_y; depth lip_z; vertex id lip_v).

    z_front: the layer's own rest front depth per frame px (inf where it draws nothing). opening(gx, gy, zn, zf): the
    largest pose distance (px) between the points at depths zn and zf on each rest ray (the caller's reachable poses).
    Returns the flap's vertex px / depth / mirror px / nearest lip vertex and its triangles (pixel-centre grid,
    never across a step), or None."""
    from scipy import ndimage as ndi
    W, H = frame_wh
    lx = np.floor(lip_x).astype(np.int64)
    ly = np.floor(lip_y).astype(np.int64)
    ok = (lx >= 0) & (lx < W) & (ly >= 0) & (ly < H)
    lx, ly, lz, lv = lx[ok], ly[ok], np.asarray(lip_z, np.float64)[ok], np.asarray(lip_v, np.int64)[ok]
    if not len(lx):
        return None
    y0, y1 = max(int(ly.min()) - rmax, 0), min(int(ly.max()) + rmax + 1, H)
    x0, x1 = max(int(lx.min()) - rmax, 0), min(int(lx.max()) + rmax + 1, W)
    h, w = y1 - y0, x1 - x0
    order = np.argsort(lz)                          # the farthest lip vertex of a px wins it
    lipz = np.full((h, w), np.nan)
    lipz[ly[order] - y0, lx[order] - x0] = lz[order]
    lipv = -np.ones((h, w), np.int64)
    lipv[ly[order] - y0, lx[order] - x0] = lv[order]
    lip = np.isfinite(lipz)
    dist, (iy, ix) = ndi.distance_transform_edt(~lip, return_indices=True)
    zlip = lipz[iy, ix]
    zf = np.asarray(z_front, np.float64)[y0:y1, x0:x1]
    dom = (dist > 0) & (dist <= rmax) & np.isfinite(zf) & (zf * hide < zlip)
    yy, xx = np.nonzero(dom)
    if not len(yy):
        return None
    opn = np.asarray(opening(xx + x0 + 0.5, yy + y0 + 0.5, zf[yy, xx], zlip[yy, xx]), np.float64)
    sel = dist[yy, xx] <= opn + pad
    fm = np.zeros((h, w), bool)
    fm[yy[sel], xx[sel]] = True
    if not fm.any():
        return None
    vm = fm | (lip & ndi.binary_dilation(fm, np.ones((3, 3), bool)))
    vy, vx = np.nonzero(vm)
    vid = -np.ones((h, w), np.int64)
    vid[vy, vx] = np.arange(len(vy))
    zv = np.where(lip[vy, vx], lipz[vy, vx], zlip[vy, vx])
    qx, qy = vx + x0 + 0.5, vy + y0 + 0.5
    mx, my = 2 * (ix[vy, vx] + x0 + 0.5) - qx, 2 * (iy[vy, vx] + y0 + 0.5) - qy
    a, b, c, d = vid[:-1, :-1], vid[:-1, 1:], vid[1:, :-1], vid[1:, 1:]
    tris = []
    for t3 in ((a, b, d), (a, d, c)):
        m = (t3[0] >= 0) & (t3[1] >= 0) & (t3[2] >= 0)
        tris.append(np.stack([t3[0][m], t3[1][m], t3[2][m]], 1))
    tris = np.concatenate(tris)
    if len(tris):
        tris = tris[~step_faces(zv[tris], eps)]
        tris = tris[fm[vy, vx][tris].any(1)]
    if not len(tris):
        return None
    return {"x": qx, "y": qy, "z": zv, "mx": mx, "my": my, "lipVertex": lipv[iy[vy, vx], ix[vy, vx]], "tris": tris,
            "flapPx": int(fm.sum()), "openingMaxPx": float(opn[sel].max()) if sel.any() else 0.0}


def orient_like(tris: np.ndarray, qx, qy, ref_f: np.ndarray, ref_x, ref_y) -> np.ndarray:
    """Flip flap triangles to the reference piece's majority screen winding at rest (its front faces the camera)."""
    def sgn(f, x, y):
        return np.sign((x[f[:, 1]] - x[f[:, 0]]) * (y[f[:, 2]] - y[f[:, 0]])
                       - (x[f[:, 2]] - x[f[:, 0]]) * (y[f[:, 1]] - y[f[:, 0]]))
    sr = sgn(ref_f, ref_x, ref_y)
    want = 1.0 if (sr > 0).sum() >= (sr < 0).sum() else -1.0
    st = sgn(tris, qx, qy)
    return np.where((st != want)[:, None], tris[:, [0, 2, 1]], tris)
