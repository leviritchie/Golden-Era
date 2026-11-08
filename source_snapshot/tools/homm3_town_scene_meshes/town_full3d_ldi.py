#!/usr/bin/env python3
"""Town full-3D: layered-depth back-fill of the staged terrain (docs/homm3_town_layered_depth_backfill.md).

A 3D-photo style layered depth image for the projection-textured terrain of any full-3D town candidate. The terrain is
a screen-space grid registered to the rest frame: where a near ridge occludes far ground, the grid bridges the depth
step with triangles that run along the rest camera's rays. They are edge-on (invisible) at rest and become stretched
rubber-sheet bands as soon as the camera translates. The pass reserves the space behind each ridge for the far ground:

  (a) cut: a triangle is removed from the main surface when its rest forward-depth ratio (max / min over its vertices)
      exceeds RATIO_CAP, or when it spans a depth step (ratio > MIN_RATIO) that a reachable proof pose smears past
      ANISO_CUT (worst s1/s2 of its rest-to-pose screen map). Main vertices, UVs and textures are untouched;
  (b) back layer (Mesh_Back_<piece>): the triangles within the band (at least EXT_PX, else EXT_GAIN x the widest gap
      a reachable pose opens across a cut, capped at EXT_MAX_PX) of each cut's far-side silhouette, copied and pushed
      back along their own rest rays onto a continuation of the far surface: inverse forward depth (planes stay
      planes) filled by pyramid push-pull from the far-side pixels of the rest depth only. Every near-side vertex goes
      at least BEHIND x its own depth back; a stepping continuation is relaxed (relax_to_cap) so no back triangle
      exceeds the cap and the layer stays one sheet. Every back vertex keeps its rest-frame screen position and UV, so
      at rest the layer is hidden except in the cut cells, which it draws in place (same rays, UV, normal, texel);
  (c) colour: the back layer samples its own texture, a crop of the piece's albedo in which only texels that are the
      ridge's paint (hidden at rest by the remaining main surface), less a PROTECT_TEXELS ring around every texel the
      layer shows at rest, are replaced by quilt_fill: exemplar tiles copied verbatim from far-side texels (image
      quilting with SSD overlap matching and a clamped tone shift). Every other texel is a verbatim copy; the main
      textures are not touched at all;
  (d) closure (keep_holes): every reachable pose is id-rendered, original piece against main + back + backstop. A
      pose-smear cut seen through a reveal hole goes back into the main surface (stretched beats empty) and the pass
      re-runs; ratio cuts never go back (validator cap). The backstop (Mesh_Back_<piece>_Far) is the band once more
      at the farthest silhouette depth within it, behind main and back, pruned (prune_stop) to the triangles some
      reachable pose sees where the original piece was, with its own fully synthesised far-side texture.

Faction-agnostic: it reads a staged candidate's terrain bins (prefab-local, i.e. rest-camera axes scaled by the depth
scale: z is forward depth) and the rest camera's field of view, and needs only that each piece's UV is an affine map of
the rest frame (checked; fails closed otherwise). No Meshy, no paid API, no model: classical CPU image operations (deterministic, seeded).

    TOWN_FULL3D_CANDIDATE=<name> python town_full3d_ldi.py --faction <key> apply   [--pieces Mesh_Terrain,...]
    TOWN_FULL3D_CANDIDATE=<name> python town_full3d_ldi.py --faction <key> measure  (bridging counts, read-only)

`apply` refuses a stage that already carries Mesh_Back_* bins (re-seed the candidate instead: the main bins are
rewritten in place). `unlayer` undoes a previous `apply` exactly, from the stage's own record: every layered piece's
main bin gets its cut triangles back from bundle/terrain_streak.npz (the vertices, normals, uv and texture were never
touched), the back / stop bins and their rows go, and the stage report's "ldi" section moves to "ldiUnlayered". It
fails closed unless the npz is the one the report pins (sha256), each main bin's vertices are that npz's main_P slice
and the restored triangles are free of duplicates; so a candidate seeded from an LDI candidate (whose other fixes are
wanted) can be layered again with different flags. It writes the stage report's "ldi" section and bundle/terrain_streak.npz; the lane's
write_catalog then declares phaseRevision 6b + terrainStreak, which tools/validate_town_scene3d_contract.py
re-measures. Proof tier: generated artifact / offline render.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import distance_transform_edt

W, H = 1920, 1080          # the rest frame (1920x1080 reference frame of the cityHuman2 MainCamera rest pose)
FH = H                     # focal reference: px of the rest frame's height. --frame auto grows the rasters (W, H)
                           # symmetrically about the principal point to cover pieces that reach past the rest frame
                           # (the no-split lane's canvas grid, 2026-10-20); FH, so the focal length, never changes
RATIO_CAP = 1.25           # max/min rest forward depth over a triangle's vertices (validator STREAK_RATIO_CAP)
CAPS = (1.25, 1.5, 2.0)    # reported bridging thresholds
EXT_PX = 120.0             # the back layer reaches at least this far (rest-frame px) under the near side of a cut
EXT_GAIN = 1.5             # ... and this many times the widest gap a reachable pose opens across a cut
EXT_MAX_PX = 320.0         # ... but never further
SIGMA_PX = 9.0             # far-depth push-pull smoothing (px)
BEHIND = 1.02              # a back vertex is pushed only when the continued far surface is this factor behind it
ANISO_CUT = 3.0            # a step triangle whose rest texture a reachable pose smears past this (s1/s2) is cut
MIN_RATIO = 1.01           # below this rest depth ratio a triangle is no depth step (grazing ground is never cut)
NEAR_RATIO = 1.04          # a vertex this factor nearer than its silhouette's far side is on the near side
PROTECT_TEXELS = 6         # texels this close to a back texel shown at rest stay verbatim (bilinear + mip reach)
QUILT_TILE = 24            # texture fill: tile size (texels), overlap, candidate radius, candidates per tile
QUILT_OVERLAP = 6
QUILT_RADIUS = 360
QUILT_CANDIDATES = 96
QUILT_TONE_MAX = 24.0      # max per-channel tone shift (0..255) applied to a copied tile
HALO_TEXELS = 2            # far-side texels this close to the ridge's paint are not used as synthesis sources
KEEP_ROUNDS = 4            # keep_holes: re-runs after keeping hole-opening smear cuts in the main surface
AFFINE_TOL_PX = 0.05       # max residual of the uv -> rest-frame affine fit (frame px)
# --cut zone (opt-in; docs/homm3_town_layered_depth_backfill.md "Occlusion-zone cut"): defaults of the zone rule
ZONE_DEFAULTS = {"r": 24, "tau_v": 1.2, "tau_h": 1.15, "near_tol": 1.06, "far_tol": 1.06}
# --back-rule vlb (opt-in; docs/homm3_town_scene_methodology_v2.md "Pilot 1"): the back layer's depth rule from the
# reachable camera set instead of the ratio cap alone. A surface on its own rest rays with inverse depth w moves by
# f * b * w px under a lateral camera offset b, so an edge of rest length l px stretches by at most K at every
# reachable pose iff |dw| <= (K - 1) * l / G, G = f * max |b| (the view-set bound). Default K:
VLB_K = 2.0


def vlb_bound(fx, fy, poses, fov_deg, K: float = VLB_K, h: int | None = None) -> dict:
    """The view-set bound's constants for one frame-registered piece: rest px of its vertices and G (px per unit
    inverse depth) from the widest lateral baseline of poses [(pos, R)] in the prefab-local frame."""
    h = H if h is None else h
    if not poses:
        raise SystemExit("ldi: --back-rule vlb needs the reachable poses (the bound comes from the camera set)")
    f_px = (FH / 2) / math.tan(math.radians(fov_deg) / 2)
    bmax = max(float(np.hypot(p[0][0], p[0][1])) for p in poses)
    if bmax <= 0:
        raise SystemExit("ldi: --back-rule vlb: the reachable poses have no lateral baseline")
    return {"fx": fx, "fy": fy, "K": float(K), "G": f_px * bmax, "bmaxLocal": bmax}


def _vlb_edges(tris, free, b):
    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    e = np.unique(np.sort(e, 1), axis=0)
    e = np.concatenate([e, e[:, ::-1]])
    e = e[free[e[:, 0]]]
    ell = np.hypot(b["fx"][e[:, 0]] - b["fx"][e[:, 1]], b["fy"][e[:, 0]] - b["fy"][e[:, 1]])
    return e, (b["K"] - 1.0) * np.maximum(ell, 0.5) / b["G"]


def vlb_relax(z, tris, free, cap, b: dict, iters: int = 20000) -> np.ndarray:
    """Smallest deepening of the free vertices meeting both the view-set bound (|w_i - w_j| <= (K-1) l_ij / G on every
    edge of tris, a min-plus distance transform on w = 1/z) and relax_to_cap (the validator's ratio cap). Both only
    deepen free vertices, so alternating them converges to the smallest depths meeting both."""
    z = np.asarray(z, np.float64).copy()
    if not len(tris):
        return z
    e, c = _vlb_edges(tris, free, b)
    for _ in range(50):
        w = 1.0 / z
        for _it in range(iters):
            want = np.full_like(w, np.inf)
            np.minimum.at(want, e[:, 0], w[e[:, 1]] + c)
            nw = np.minimum(w, want)
            if np.allclose(nw, w, rtol=0, atol=1e-12):
                break
            w = nw
        else:
            raise SystemExit("ldi: view-set bound relaxation did not converge")
        nz = relax_to_cap(1.0 / w, tris, free, cap)
        if np.allclose(nz, z, rtol=1e-12, atol=0):
            return nz
        z = nz
    raise SystemExit("ldi: view-set bound / cap alternation did not converge")


def vlb_violation(z, tris, b: dict) -> np.ndarray:
    """Tiles still over the view-set bound on some edge (two fixed vertices across a step): LDI's over-cap test then
    makes them flat cards at their farthest depth (a fronto-parallel card cannot streak)."""
    w = 1.0 / np.asarray(z, np.float64)
    bad = np.zeros(len(tris), bool)
    for i0, j0 in ((0, 1), (1, 2), (2, 0)):
        i, j = tris[:, i0], tris[:, j0]
        ell = np.maximum(np.hypot(b["fx"][i] - b["fx"][j], b["fy"][i] - b["fy"][j]), 0.5)
        bad |= np.abs(w[i] - w[j]) > (b["K"] - 1.0) * ell / b["G"] * (1 + 1e-6)
    return bad


def occlusion_zone_cut(v, tris, fx, fy, z, by_ratio, smear, fov_deg, zone, w=None, h=None):
    """The opt-in occlusion-zone cut (--cut zone). The default per-triangle smear rule cuts single step triangles: on
    a sharp depth map whose occlusion edges are ramps a few cells wide (and whose grass carries micro-relief) it cuts
    scattered cells and welds the back layer to the middle of the ramp, so the curtain survives in the back layer.
    Here a cut is a coherent region instead, decided on the rest depth raster zr of the piece:
      zone   px within r of a horizontal step (max/min of zr over a 1 x (2r+1) window > tau_h: ground does not recede
             sideways) or of a vertical step past the ground's own recession (max/min over (2r+1) x 1 > tau_v x the same
             ratio of the frame's row-median depth), dilated by r; only connected zones holding a seed (a ratio cut or
             a default smear cut) count, so a step no reachable pose smears is left alone;
      near / far  in a zone, a vertex within near_tol of the windowed min depth / far_tol of the windowed max depth.
    Every zone triangle that is not wholly near and not wholly far (the ramp and both of its seams) is cut, plus the
    ratio cuts; smear cuts outside every zone stay in the main surface. The far ends that weld the back layer are
    the far vertices (exclusive of near) inside zones, the geometric-mean split elsewhere.
    Returns (cut, far flag per vertex, zone flag per vertex, report)."""
    w, h = (W if w is None else w), (H if h is None else h)
    p = {**ZONE_DEFAULTS, **(zone or {})}
    r = int(p["r"])
    zr = rest_depth(v, tris, fov_deg, w, h)
    fin = np.isfinite(zr)
    z0 = np.where(fin, zr, 0).astype(np.float32)
    z1 = np.where(fin, zr, 1e9).astype(np.float32)
    disc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    zmax = cv2.dilate(z0, disc).astype(np.float64)
    zmin = cv2.erode(z1, disc).astype(np.float64)
    rowmed = np.array([np.median(zr[y][fin[y]]) if fin[y].sum() > 20 else np.nan for y in range(h)])
    ok = np.isfinite(rowmed)
    if not ok.any():
        raise SystemExit("ldi --cut zone: the piece covers no frame row")
    rowmed = np.interp(np.arange(h), np.flatnonzero(ok), rowmed[ok])
    rmx = np.array([rowmed[max(0, y - r):y + r + 1].max() for y in range(h)])
    rmn = np.array([rowmed[max(0, y - r):y + r + 1].min() for y in range(h)])
    expected = (rmx / np.maximum(rmn, 1e-9))[:, None]
    kh, kv = np.ones((1, 2 * r + 1), np.uint8), np.ones((2 * r + 1, 1), np.uint8)
    hr = cv2.dilate(z0, kh).astype(np.float64) / np.maximum(cv2.erode(z1, kh).astype(np.float64), 1e-9)
    vr = cv2.dilate(z0, kv).astype(np.float64) / np.maximum(cv2.erode(z1, kv).astype(np.float64), 1e-9)
    zone_px = fin & ((hr > p["tau_h"]) | (vr > p["tau_v"] * expected))
    zone_px = (cv2.dilate(zone_px.astype(np.uint8), disc) > 0) & fin
    seed = np.zeros((h, w), np.uint8)
    st = tris[by_ratio | smear]
    seed[np.clip(fy[st].mean(1).astype(np.int64), 0, h - 1), np.clip(fx[st].mean(1).astype(np.int64), 0, w - 1)] = 1
    nlab, lab = cv2.connectedComponents(zone_px.astype(np.uint8), connectivity=8)
    hit = np.zeros(nlab, bool)
    hit[np.unique(lab[seed > 0])] = True
    hit[0] = False
    zone_px = hit[lab]
    xi, yi = _pix(fx, fy, w, h)
    zv = zone_px[yi, xi]
    near = z <= zmin[yi, xi] * p["near_tol"]
    far = (z >= zmax[yi, xi] / p["far_tol"]) & ~near
    tz = zv[tris].any(1)
    cutz = tz & ~near[tris].all(1) & ~far[tris].all(1)
    rep = {"cut": "zone", "zone": p, "zonePx": int(zone_px.sum()), "zones": int(hit.sum()), "zoneCutTris": int(cutz.sum()),
           "smearLeftOutsideZones": int((smear & ~tz).sum())}
    return by_ratio | cutz, far & zv, zv, rep


# ------------------------------------------------------------------------------------------------ geometry
def project(v: np.ndarray, fov_deg: float, w: int | None = None, h: int | None = None):
    """Prefab-local points (x right, y up, z forward) -> rest-frame px (fx, fy) and forward depth z."""
    w, h = (W if w is None else w), (H if h is None else h)
    v = np.asarray(v, np.float64)
    t = math.tan(math.radians(fov_deg) / 2)
    z = v[:, 2]
    zs = np.where(np.abs(z) > 1e-9, z, 1e-9)
    fx = v[:, 0] / (zs * t) * (0.5 * FH) + 0.5 * w
    fy = 0.5 * h - v[:, 1] / (zs * t) * (0.5 * FH)
    return fx, fy, z


def depth_ratio(z: np.ndarray, tris: np.ndarray) -> np.ndarray:
    zt = np.asarray(z, np.float64)[np.asarray(tris, np.int64)]
    if not len(zt):
        return np.zeros(0)
    return zt.max(1) / np.maximum(zt.min(1), 1e-9)


def bridging_counts(z: np.ndarray, tris: np.ndarray, caps=CAPS) -> dict:
    r = depth_ratio(z, tris)
    return {f">{c:g}": int((r > c + 1e-6).sum()) for c in caps}


def _pix(fx, fy, w=None, h=None):
    w, h = (W if w is None else w), (H if h is None else h)
    return (np.clip(np.floor(fx), 0, w - 1).astype(np.int64), np.clip(np.floor(fy), 0, h - 1).astype(np.int64))


def _blur(img: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(img.astype(np.float32), (0, 0), sigma).astype(np.float64)


def uv_affine(uv: np.ndarray, fx: np.ndarray, fy: np.ndarray):
    """Least-squares affine uv -> frame px; returns (A 2x3, max residual px). A piece whose texture is not registered
    to the rest frame has no meaningful 'far-side texel' and is refused by the caller."""
    X = np.c_[uv[:, 0], uv[:, 1], np.ones(len(uv))]
    Y = np.c_[fx, fy]
    A, *_ = np.linalg.lstsq(X, Y, rcond=None)
    res = np.abs(X @ A - Y).max() if len(uv) else 0.0
    return A.T, float(res)


def uv_affine_registered(uv: np.ndarray, fx: np.ndarray, fy: np.ndarray, rounds: int = 6):
    """uv_affine on the texture-registered vertices only: trimmed refits drop the vertices whose uv does not follow the
    rest frame (a mirror skirt past the painted canvas: the no-split lane's envPad). Returns (A, max residual px over
    the registered vertices, registered mask)."""
    X = np.c_[uv[:, 0], uv[:, 1], np.ones(len(uv))]
    Y = np.c_[fx, fy]
    reg = np.ones(len(uv), bool)
    for _ in range(rounds):
        A, *_ = np.linalg.lstsq(X[reg], Y[reg], rcond=None)
        r = np.abs(X @ A - Y).max(1)
        reg = r <= max(0.5, 3 * float(np.median(r)))
    A, *_ = np.linalg.lstsq(X[reg], Y[reg], rcond=None)
    r = np.abs(X @ A - Y).max(1)
    reg = r <= 0.5
    return A.T, float(r[reg].max()) if reg.any() else float("inf"), reg


def pose_aniso(v: np.ndarray, tris: np.ndarray, fov_deg: float, poses, w=None, h=None) -> np.ndarray:
    """Per triangle, the worst anisotropy (s1 / s2) of the map from its rest-frame footprint (= its texture: the
    terrain is projection-textured from the rest frame) to its footprint at each pose. poses: [(pos, R)] in the
    prefab-local frame, R's columns the pose camera's right / up / forward. A vertex behind a pose camera is inf."""
    w, h = (W if w is None else w), (H if h is None else h)
    from town_full3d_stretch import tri_jacobian_sv
    v = np.asarray(v, np.float64)
    fx0, fy0, _ = project(v, fov_deg, w, h)
    S0 = np.stack([fx0, fy0], 1)[tris]
    worst = np.ones(len(tris))
    for pos, R in poses:
        q = (v - pos) @ R
        fx, fy, zq = project(q, fov_deg, w, h)
        s1, s2 = tri_jacobian_sv(np.stack([fx, fy], 1)[tris], S0)
        a = s1 / s2
        a[(zq[tris] <= 0).any(1)] = np.inf
        worst = np.maximum(worst, a)
    return worst


def layer_piece(v, n, uv, tris, fov_deg, poses=(), cap=RATIO_CAP, ext_px=EXT_PX, sigma_px=SIGMA_PX, w=None,
                h=None, keep=None, zone=None, back_rule: dict | None = None, frozen=None) -> dict | None:
    """The layered-depth pass on one frame-registered mesh (prefab-local). A triangle is cut when its rest forward-
    depth ratio exceeds cap, or when it spans a depth step (ratio > MIN_RATIO) that a reachable pose (poses, see
    pose_aniso) smears past ANISO_CUT. Returns None when nothing is cut, else {"main": (v, n, uv, tris) with the
    patches appended, "back": (v, n, uv, tris), "rasters": {...}, "report": {...}, "cut": the original cut triangles
    (indices into the returned main v)}."""
    w, h = (W if w is None else w), (H if h is None else h)
    v = np.asarray(v, np.float64)
    n = np.asarray(n, np.float64)
    uv = np.asarray(uv, np.float64)
    tris = np.asarray(tris, np.int64)
    poses = list(poses)
    fx, fy, z = project(v, fov_deg, w, h)
    if (z <= 0).any():
        raise SystemExit("ldi: a vertex is behind the rest camera (not a frame-registered surface)")
    ratio = depth_ratio(z, tris)
    vlbb = vlb_bound(fx, fy, poses, fov_deg, back_rule.get("K", VLB_K), h) if back_rule else None
    an = pose_aniso(v, tris, fov_deg, poses, w, h) if poses else np.ones(len(tris))
    by_ratio = ratio > cap + 1e-6
    zone_far = zone_v = None
    if zone is None:
        cut = by_ratio | ((ratio > MIN_RATIO) & (an > ANISO_CUT))
    else:
        cut, zone_far, zone_v, zone_rep = occlusion_zone_cut(v, tris, fx, fy, z, by_ratio,
                                                             (ratio > MIN_RATIO) & (an > ANISO_CUT), fov_deg, zone, w, h)
    if keep is not None:
        cut &= by_ratio | ~keep            # smear cuts that opened a reveal hole stay in the main surface (keep_holes)
    if frozen is not None:
        cut &= ~frozen                     # triangles on texture-unregistered vertices (a mirror skirt) are never cut
    if not cut.any():
        return None
    ct = tris[cut]
    zmax = z[ct].max(1, keepdims=True)
    zmin = z[ct].min(1, keepdims=True)
    far_v = z[ct] >= np.sqrt(zmax * zmin)          # the far end of the step (geometric-mean split)
    if zone_v is not None:
        far_v = np.where(zone_v[ct], zone_far[ct], far_v)   # inside a zone: the far plateau, never mid-ramp
    B = np.zeros(len(v), bool)
    B[ct[far_v]] = True
    near_cut = np.zeros(len(v), bool)
    near_cut[ct[~far_v]] = True
    B &= ~near_cut
    xi, yi = _pix(fx, fy, w, h)
    sp = np.hypot(*(np.stack([fx, fy], 1)[tris[:, 1]] - np.stack([fx, fy], 1)[tris[:, 0]]).T)
    spacing = float(np.median(sp)) if len(sp) else 3.0          # vertex spacing (px)
    # the band: at least ext_px, else EXT_GAIN x the widest gap a reachable pose opens across a cut (its far and near
    # vertices' relative displacement), capped at EXT_MAX_PX
    gap = 0.0
    if poses:
        ia = ct[np.arange(len(ct)), z[ct].argmax(1)]
        ib = ct[np.arange(len(ct)), z[ct].argmin(1)]
        for pos, R in poses:
            px_, py_, _ = project((v - pos) @ R, fov_deg, w, h)
            gap = max(gap, float(np.hypot((px_[ia] - px_[ib]) - (fx[ia] - fx[ib]),
                                          (py_[ia] - py_[ib]) - (fy[ia] - fy[ib])).max()))
    ext_px = float(min(max(ext_px, EXT_GAIN * gap), EXT_MAX_PX))
    # silhouette raster: the far-side vertices of the cuts, their depth (the farthest when two share a pixel)
    Bimg = np.zeros((h, w), bool)
    Bimg[yi[B], xi[B]] = True
    Bz = np.zeros((h, w))
    np.maximum.at(Bz, (yi[B], xi[B]), z[B])
    dist, (bi, bj) = distance_transform_edt(~Bimg, return_indices=True)
    zB_img = Bz[bi, bj]
    dv = dist[yi, xi]
    zB = zB_img[yi, xi]
    # the continued far surface: inverse depth (affine on screen for a plane, so planes continue as planes) filled by
    # pyramid push-pull from the far-side pixels of the rest depth only (never the ridge), plus the silhouette vertices
    zr = rest_depth(v, tris, fov_deg, w, h)
    far_px = np.isfinite(zr) & (zr >= zB_img / NEAR_RATIO) & (dist <= ext_px + 4 * sigma_px)
    near_px = np.isfinite(zr) & (zr < zB_img / NEAR_RATIO) & (dist <= ext_px + 2 * spacing)
    known = (far_px & ~near_px) | Bimg
    inv = np.where(Bimg, 1.0 / np.maximum(Bz, 1e-9), 1.0 / np.where(np.isfinite(zr), np.maximum(zr, 1e-9), 1.0))
    inv_f = push_pull(inv[..., None].astype(np.float32), known)[..., 0].astype(np.float64)
    zb_img = 1.0 / np.maximum(inv_f, 1e-9)
    zb = zb_img[yi, xi]
    # near side: nearer than its silhouette's far side OR than the continued far surface itself (the silhouette test
    # alone left stripes of near-side vertices unpushed where a small step's far side was the nearest one, and the
    # back sheet tore along them at the sweeps: fa_v5_ldi v1 review)
    E = (~B & (dv <= ext_px) & ((z < zB / NEAR_RATIO) | (z < zb / NEAR_RATIO))) | near_cut
    S = ~E & (dv <= ext_px + 4 * sigma_px) & (z >= zB / NEAR_RATIO)
    nr = np.zeros((h, w, 3), np.float32)
    nk = np.zeros((h, w), bool)
    nr[yi[S], xi[S]] = n[S]
    nk[yi[S], xi[S]] = True
    nb_img = push_pull(nr, nk).astype(np.float64)
    nf = nb_img[yi, xi]
    nfl = np.linalg.norm(nf, axis=1, keepdims=True)
    nf = np.where(nfl > 1e-6, nf / np.maximum(nfl, 1e-9), n)
    layer = dv <= ext_px + 1.5 * spacing
    # only near-side vertices move (at least BEHIND behind their main copy): every other back vertex keeps its main
    # copy's depth, so the layer's open boundary is welded to the main surface (moving far-side vertices too detached
    # the boundary from the main mesh and opened reveal holes along it: fa_v5_ldi v1 review)
    pushed = E
    bt = tris[layer[tris].all(1) & E[tris].any(1)]
    zl = np.where(pushed, np.maximum(zb, z * BEHIND), z)
    # a continued far surface that steps (two far layers behind one ridge) would be a new curtain. Its nearer vertices
    # (pushed ones only: the far side stays welded to the main mesh) move further back along their rays until every
    # back tile is within the cap - a monotone relaxation zl_i >= zl_j / cap over the layer's edges, so the layer
    # stays one connected sheet (flattening each over-cap tile into its own card cracked it: fa_v5_ldi try 6).
    zl = relax_to_cap(zl, bt, pushed, cap) if vlbb is None else vlb_relax(zl, bt, pushed, cap, vlbb)
    rb = depth_ratio(zl, bt)
    # a tile still over the cap has two unpushed vertices across the step; it gets its own copies at its farthest depth
    over = rb > cap + 1e-6
    cards_by_bound = 0
    if vlbb is not None:            # --back-rule vlb: a tile over the view-set bound is a card too
        vio = vlb_violation(zl, bt, vlbb) & ~over
        cards_by_bound = int(vio.sum())
        over |= vio
    ot = bt[over]
    zo = np.repeat(zl[ot].max(1, keepdims=True), 3, 1) if len(ot) else np.zeros((0, 3))
    bt = bt[~over]
    used = np.unique(bt)
    remap = np.full(len(v), -1, np.int64)
    remap[used] = np.arange(len(used))
    # back layer vertices: along their own rest rays (screen position and uv unchanged). The vertices of the cut cells
    # keep their own normal: at rest the back layer draws those cells in place of the cut (same rays, uv, normal and
    # texel); deeper under the ridge (hidden at rest) the normal is the continued far surface's.
    in_cut = np.zeros(len(v), bool)
    in_cut[ct] = True
    nsrc = np.where((pushed & ~in_cut)[:, None], nf, n)
    vb = np.concatenate([v[used] * (zl[used] / z[used])[:, None], (v[ot.ravel()] * (zo.ravel() / z[ot.ravel()])[:, None])])
    nb = np.concatenate([nsrc[used], nsrc[ot.ravel()]])
    uvb = np.concatenate([uv[used], uv[ot.ravel()]])
    tb = np.concatenate([remap[bt], len(used) + np.arange(ot.size).reshape(-1, 3)]).astype(np.int64)
    # backstop (Mesh_Back_<piece>_Far): the whole band once more, every vertex on its own rest ray at least as far
    # as the farthest silhouette depth within the band (band_max, smoothed in inverse depth) and behind both the main
    # surface and the back layer, relaxed under the cap with every vertex free. Hidden at rest; it shows only where a
    # reachable pose still sees past the back layer (a far side that steps again, a band edge, a sheet boundary),
    # which without it would be sky or the clear colour (fa_v5_ldi v1 review: magenta + sky shards).
    zf_img = band_max(Bz, ext_px)
    has = zf_img > 0
    s_inv = _blur(np.where(has, 1.0 / np.maximum(zf_img, 1e-9), 0.0), ext_px / 4)
    s_w = _blur(has.astype(np.float64), ext_px / 4)
    zf = 1.0 / np.maximum((s_inv / np.maximum(s_w, 1e-9))[yi, xi], 1e-9)
    zf = np.where(has[yi, xi], np.minimum(zf, zf_img[yi, xi]), z)
    st = tris[layer[tris].all(1)]
    zs = np.maximum(zf, z * BEHIND)
    zs[used] = np.maximum(zs[used], zl[used] * BEHIND)
    if len(ot):
        np.maximum.at(zs, ot.ravel(), zo.ravel() * BEHIND)
    zs = relax_to_cap(zs, st, np.ones(len(v), bool), cap) if vlbb is None else \
        vlb_relax(zs, st, np.ones(len(v), bool), cap, vlbb)
    s_used = np.unique(st)
    s_map = np.full(len(v), -1, np.int64)
    s_map[s_used] = np.arange(len(s_used))
    vs_ = v[s_used] * (zs[s_used] / z[s_used])[:, None]
    stop = (vs_, nf[s_used], uv[s_used], s_map[st].astype(np.int64))
    main_t = tris[~cut]
    covered = np.zeros(len(tris), bool)
    covered[cut] = (layer[ct].all(1))
    rb_after = np.concatenate([depth_ratio(vb[:, 2], tb) if len(tb) else np.zeros(0), depth_ratio(vs_[:, 2], stop[3])])
    # frozen triangles (a mirror skirt, --frame auto) are never cut, so they keep their steps: reported, not checked
    chk_t = tris[~cut & ~frozen] if frozen is not None else main_t
    worst = float(max(rb_after.max() if len(rb_after) else 0.0, depth_ratio(z, chk_t).max()))
    frozen_worst = float(depth_ratio(z, tris[frozen]).max()) if frozen is not None and frozen.any() else None
    if worst > cap + 1e-6:
        raise SystemExit(f"ldi: a shipped triangle is still over the cap ({worst:.4f})")
    rep = {"ratioCap": cap, "cutTris": int(cut.sum()), "maxRatioBefore": round(float(ratio.max()), 3),
           "bridgingBefore": bridging_counts(z, tris), "bridgingAfterMain": bridging_counts(z, main_t),
           "cutByRatio": int(by_ratio.sum()), "cutBySmear": int((cut & ~by_ratio).sum()), "poses": len(poses),
           "anisoCut": ANISO_CUT, "farSideVerts": int(B.sum()), "nearSideVerts": int(E.sum()),
           "pushedVerts": int(pushed[used].sum()), "backVerts": int(len(vb)), "backTris": int(len(tb)),
           "tilesFlattened": int(over.sum()), "relaxedVerts": int((zl[used] > np.where(pushed, np.maximum(zb, z * BEHIND), z)[used] * (1 + 1e-9)).sum()) if len(bt) else 0, "backAnisoP99": round(float(np.percentile(
               pose_aniso(vb, tb, fov_deg, poses, w, h), 99)) if poses and len(tb) else 1.0, 3),
           "maxRatioAfter": round(worst, 4), **({"frozenMaxRatio": round(frozen_worst, 4)} if frozen_worst else {}), "extPx": round(ext_px, 1), "maxPoseGapPx": round(gap, 1), "sigmaPx": sigma_px,
           "vertexSpacingPx": round(spacing, 2)}
    rep.update({"stopVerts": int(len(vs_)), "stopTris": int(len(st))})
    if zone is not None:
        rep["zoneCut"] = zone_rep
    if vlbb is not None:
        rep["backRule"] = {"rule": "vlb", "K": vlbb["K"], "G": round(vlbb["G"], 3),
                           "bmaxLocal": round(vlbb["bmaxLocal"], 4),
                           "cardsByBound": cards_by_bound}
    return {"main": (v, n, uv, main_t), "back": (vb, nb, uvb, tb), "stop": stop, "cut": ct, "cutByRatio": by_ratio[cut],
            "report": rep,
            "backSource": np.concatenate([bt, ot]),
            "rasters": {"zb": zb_img, "dist": dist, "bi": bi, "bj": bj},
            "vertex": {"B": B, "E": E, "zB": zB, "zb": zb, "zl": zl, "dv": dv}}


def band_max(img: np.ndarray, radius_px: float, step: int = 4) -> np.ndarray:
    """Max of img over a disc of radius_px, on a step-times coarser grid (conservative: each coarse cell takes its
    block's max before the dilation and hands the result to every pixel of the block)."""
    h, w = img.shape
    hh, ww = -(-h // step), -(-w // step)
    pad = np.zeros((hh * step, ww * step), np.float32)
    pad[:h, :w] = img
    coarse = pad.reshape(hh, step, ww, step).max((1, 3))
    r = int(math.ceil(radius_px / step)) + 1
    dil = cv2.dilate(coarse, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    return np.repeat(np.repeat(dil, step, 0), step, 1)[:h, :w].astype(np.float64)


def relax_to_cap(z: np.ndarray, tris: np.ndarray, free: np.ndarray, cap: float, iters: int = 4000) -> np.ndarray:
    """Smallest depths >= z with z_i >= z_j / cap' across every edge of tris for the free vertices (cap' = cap / (1 +
    1e-4), a margin under the validator's cap); fixed vertices keep their depth."""
    z = np.asarray(z, np.float64).copy()
    if not len(tris):
        return z
    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    e = np.concatenate([e, e[:, ::-1]])
    e = e[free[e[:, 0]]]
    c = cap / (1.0 + 1e-4)
    for _ in range(iters):
        want = np.zeros_like(z)
        np.maximum.at(want, e[:, 0], z[e[:, 1]] / c)
        nz = np.maximum(z, want)
        if np.array_equal(nz, z):
            return z
        z = nz
    raise SystemExit("ldi: back-layer cap relaxation did not converge")


def id_render(parts, fov_deg, pose=None, w=None, h=None) -> tuple[np.ndarray, np.ndarray]:
    """Per pixel (part index, triangle index) of the nearest surface, -1 where none: parts [(v, tris)] prefab-local,
    seen from the rest camera or from pose (pos, R), R's columns the camera's right / up / forward."""
    w, h = (W if w is None else w), (H if h is None else h)
    import moderngl
    t = math.tan(math.radians(fov_deg) / 2)
    ctx = moderngl.create_standalone_context()
    try:
        prog = ctx.program(vertex_shader="""
#version 330
uniform vec2 k; uniform vec2 zr; in vec3 p;
void main(){ float z = p.z; gl_Position = vec4(p.x / k.x, p.y / k.y, ((z - zr.x) / (zr.y - zr.x) * 2.0 - 1.0) * z, z); }""",
                           fragment_shader="""
#version 330
uniform int pid; out ivec4 o; void main(){ o = ivec4(pid, gl_PrimitiveID, 0, 1); }""")
        prog["k"].value = (t * w / FH, t * h / FH)
        qs = []
        for pv, _ in parts:
            q = np.asarray(pv, np.float64)
            if pose is not None:
                q = (q - pose[0]) @ pose[1]
            qs.append(q)
        zz = np.concatenate([q[:, 2] for q in qs])
        zz = zz[zz > 0]
        prog["zr"].value = (float(zz.min()) * 0.5, float(zz.max()) * 2.0)
        fbo = ctx.framebuffer(color_attachments=[ctx.renderbuffer((w, h), 4, dtype="i4")],
                              depth_attachment=ctx.depth_renderbuffer((w, h)))
        fbo.use()
        fbo.clear(-1, -1, -1, -1, depth=1.0)
        ctx.enable(moderngl.DEPTH_TEST)
        for i, (q, (_, pt)) in enumerate(zip(qs, parts)):
            if not len(pt):
                continue
            vao = ctx.vertex_array(prog, [(ctx.buffer(q.astype(np.float32).tobytes()), "3f", "p")],
                                   ctx.buffer(np.asarray(pt, np.int32).tobytes()))
            prog["pid"].value = i
            vao.render()
        a = np.frombuffer(fbo.read(components=4, dtype="i4"), np.int32).reshape(h, w, 4)[::-1]
        return a[..., 0].copy(), a[..., 1].copy()
    finally:
        ctx.release()


def reveal_holes(v, tris, out, fov_deg, poses) -> dict:
    """Per reachable pose, the pixels the original piece covers that its main + back + backstop do not (a hole the
    pass opened), and the original triangles seen there."""
    res = {}
    after = [(out["main"][0], out["main"][3]), (out["back"][0], out["back"][3]), (out["stop"][0], out["stop"][3])]
    for k, pose in enumerate(poses):
        pb, tb = id_render([(v, tris)], fov_deg, pose)
        pa, _ = id_render(after, fov_deg, pose)
        hole = (pb == 0) & (pa < 0)
        res[k] = {"px": int(hole.sum()), "tris": np.unique(tb[hole])}
    return res


def prune_stop(v, tris, out, fov_deg, poses) -> dict:
    """Keep only the backstop triangles some reachable pose sees where the original piece was (they fill a hole the
    pass opened); the rest is either never seen or would stand in front of what the original showed past the piece's
    own edge (sky), a new artefact. Rewrites out["stop"] in place."""
    sv, sn, suv, st = out["stop"]
    after = [(out["main"][0], out["main"][3]), (out["back"][0], out["back"][3]), (sv, st)]
    useful = np.zeros(len(st), bool)
    for pose in poses:
        pb, _ = id_render([(v, tris)], fov_deg, pose)
        pa, ta = id_render(after, fov_deg, pose)
        sel = (pa == 2) & (pb == 0)
        useful[np.unique(ta[sel])] = True
    st2 = st[useful]
    used = np.unique(st2)
    remap = np.full(len(sv), -1, np.int64)
    remap[used] = np.arange(len(used))
    out["stop"] = (sv[used], sn[used], suv[used], remap[st2])
    out["report"].update({"stopTris": int(len(st2)), "stopVerts": int(len(used))})
    return {"stopTrisBuilt": int(len(st)), "stopTrisKept": int(len(st2))}


def keep_holes(v, n, uv, tris, fov_deg, poses, rounds=KEEP_ROUNDS, zone=None,
               back_rule: dict | None = None, frozen=None) -> tuple[dict, dict]:
    """layer_piece, then: every pose-smear cut triangle seen through a reveal hole at a reachable pose is kept in the
    main surface (a stretched but closed surface beats a hole), and the pass re-runs, up to rounds times. Ratio cuts
    are never kept (the validator's cap); holes on them are reported."""
    keep = np.zeros(len(tris), bool)
    ratio = depth_ratio(project(v, fov_deg)[2], tris)
    hist = []
    for r in range(rounds + 1):
        out = layer_piece(v, n, uv, tris, fov_deg, poses, keep=keep, zone=zone, back_rule=back_rule, frozen=frozen)
        if out is None or not poses:
            return out, {"rounds": r, "history": hist}
        holes = reveal_holes(v, tris, out, fov_deg, poses)
        ht = np.unique(np.concatenate([hh["tris"] for hh in holes.values()]).astype(np.int64))
        smear = ht[(ratio[ht] <= RATIO_CAP + 1e-6) & ~keep[ht]]
        hist.append({"holePx": [hh["px"] for hh in holes.values()], "holeTris": int(len(ht)),
                     "smearKept": int(len(smear))})
        if not len(smear) or r == rounds:
            prune = prune_stop(v, tris, out, fov_deg, poses)
            holes = reveal_holes(v, tris, out, fov_deg, poses)
            return out, {"stopPrune": prune,"rounds": r, "history": hist,
                         "keptSmearTris": int(keep.sum()),
                         "holePxByPose": [hh["px"] for hh in holes.values()],
                         "holeTrisRatioCut": int((ratio[ht] > RATIO_CAP + 1e-6).sum())}
        keep[smear] = True
    raise AssertionError("unreachable")


def rest_depth(v, tris, fov_deg, w=None, h=None) -> np.ndarray:
    """Forward depth of the nearest surface per rest-frame pixel (inf where the mesh does not cover it)."""
    w, h = (W if w is None else w), (H if h is None else h)
    import moderngl
    t = math.tan(math.radians(fov_deg) / 2)
    ctx = moderngl.create_standalone_context()
    try:
        prog = ctx.program(vertex_shader="""
#version 330
uniform vec2 k; uniform vec2 zr; in vec3 p; out float vz;
void main(){ float z = p.z; gl_Position = vec4(p.x / k.x, p.y / k.y, ((z - zr.x) / (zr.y - zr.x) * 2.0 - 1.0) * z, z);
             vz = z; }""",
                           fragment_shader="""
#version 330
in float vz; out vec4 o; void main(){ o = vec4(vz, 0, 0, 1); }""")
        prog["k"].value = (t * w / FH, t * h / FH)
        zz = np.asarray(v, np.float64)[:, 2]
        prog["zr"].value = (float(zz.min()) * 0.5, float(zz.max()) * 2.0)
        vb = ctx.buffer(np.asarray(v, np.float32).tobytes())
        ib = ctx.buffer(np.asarray(tris, np.int32).tobytes())
        vao = ctx.vertex_array(prog, [(vb, "3f", "p")], ib)
        col = ctx.texture((w, h), 4, dtype="f4")
        fbo = ctx.framebuffer(color_attachments=[col], depth_attachment=ctx.depth_texture((w, h)))
        fbo.use()
        fbo.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        ctx.enable(moderngl.DEPTH_TEST)
        vao.render()
        a = np.frombuffer(col.read(), np.float32).reshape(h, w, 4)[::-1]
        return np.where(a[..., 3] > 0.5, a[..., 0], np.inf).astype(np.float64)
    finally:
        ctx.release()


# ------------------------------------------------------------------------------------------------ colour
def push_pull(img: np.ndarray, known: np.ndarray) -> np.ndarray:
    """Normalised-convolution push-pull: a smooth fill of every pixel from the known pixels only (exact where known).
    img: H x W x C float; returns H x W x C."""
    def c3(x):
        return x if x.ndim == 3 else x[..., None]
    c = c3(img.astype(np.float32)) * known[..., None]
    wgt = known.astype(np.float32)
    pyr = [(c, wgt)]
    while min(pyr[-1][1].shape) > 2:
        c_, w_ = pyr[-1]
        pyr.append((c3(cv2.pyrDown(c_)), cv2.pyrDown(w_)))
    fc, fw = pyr[-1]
    est = fc / np.maximum(fw, 1e-6)[..., None]
    for c_, w_ in reversed(pyr[:-1]):
        up = c3(cv2.resize(est, (w_.shape[1], w_.shape[0]), interpolation=cv2.INTER_LINEAR))
        a = np.clip(w_ * 4, 0, 1)[..., None]
        est = np.where(w_[..., None] > 1e-6, c_ / np.maximum(w_, 1e-6)[..., None], up) * a + up * (1 - a)
    # exact at the known pixels
    return np.where(known[..., None], c3(img.astype(np.float32)), est)


def quilt_fill(img: np.ndarray, fill: np.ndarray, src: np.ndarray, tile=QUILT_TILE, ov=QUILT_OVERLAP,
               radius=QUILT_RADIUS, ncand=QUILT_CANDIDATES, seed=0) -> tuple[np.ndarray, dict]:
    """Classical exemplar fill (image quilting, Efros & Freeman 2001, credit-free and deterministic): the fill texels,
    tile by tile in order of distance from the source, each take a window copied verbatim from a source-only window
    within radius texels (the one of ncand seeded random candidates whose overlap best matches the source and already
    filled texels around it, SSD), shifted by the mean overlap difference (clamped to QUILT_TONE_MAX) so the tone
    meets its neighbours; texels a previous tile filled blend 50/50 in the overlap. Only fill texels are written.
    img float32 (h, w, 3) 0..255. Fails closed when the source holds no window at all."""
    from scipy.spatial import cKDTree
    h, w = fill.shape
    P = tile + 2 * ov
    out = img.astype(np.float32).copy()
    if not fill.any():
        return out, {"tiles": 0}
    ii = cv2.integral(src.astype(np.uint8))
    ys, xs = np.mgrid[0:h - P + 1:2, 0:w - P + 1:2]
    ok = (ii[ys + P, xs + P] - ii[ys, xs + P] - ii[ys + P, xs] + ii[ys, xs]) == P * P
    cy, cx = ys[ok], xs[ok]
    if not len(cy):
        raise SystemExit("ldi: texture fill has no all-source window to copy from")
    tree = cKDTree(np.stack([cy, cx], 1))
    rng = np.random.default_rng(seed)
    d_src = distance_transform_edt(~src)
    known = src.copy()
    filled = np.zeros_like(fill)
    tiles = []
    for ty in range(0, h, tile):
        for tx in range(0, w, tile):
            f = fill[ty:ty + tile, tx:tx + tile]
            if f.any():
                tiles.append((float(d_src[ty:ty + tile, tx:tx + tile][f].min()), ty, tx))
    tiles.sort()
    widened = 0
    tone = []
    for _, ty, tx in tiles:
        y0, x0 = ty - ov, tx - ov
        wy0, wx0 = max(y0, 0), max(x0, 0)
        wy1, wx1 = min(y0 + P, h), min(x0 + P, w)
        r = radius
        idx = tree.query_ball_point([ty + tile / 2 - P / 2, tx + tile / 2 - P / 2], r)
        while len(idx) < 4 and r < 4 * max(h, w):
            r *= 2
            widened += 1
            idx = tree.query_ball_point([ty + tile / 2 - P / 2, tx + tile / 2 - P / 2], r)
        if not idx:
            idx = [int(tree.query([ty, tx])[1])]
        idx = np.asarray(idx)
        if len(idx) > ncand:
            idx = rng.choice(idx, ncand, replace=False)
        sy, sx = cy[idx] + (wy0 - y0), cx[idx] + (wx0 - x0)
        hh, ww = wy1 - wy0, wx1 - wx0
        tgt = out[wy0:wy1, wx0:wx1]
        m = (known | filled)[wy0:wy1, wx0:wx1] & ~(fill[wy0:wy1, wx0:wx1] & ~filled[wy0:wy1, wx0:wx1])
        gy = sy[:, None, None] + np.arange(hh)[None, :, None]
        gx = sx[:, None, None] + np.arange(ww)[None, None, :]
        cand = out[gy, gx]                                   # (n, hh, ww, 3): source windows are never written
        if m.any():
            diff = (cand - tgt[None])[:, m]                  # (n, k, 3)
            shift = diff.mean(1)                             # candidate minus target, per channel
            ssd = ((diff - shift[:, None, :]) ** 2).sum((1, 2)) + 0.25 * (shift ** 2).sum(1) * m.sum()
            best = int(np.argmin(ssd))
            sh = np.clip(-shift[best], -QUILT_TONE_MAX, QUILT_TONE_MAX)
        else:
            best, sh = 0, np.zeros(3, np.float32)
        tone.append(float(np.abs(sh).max()))
        patch = cand[best] + sh
        fz = fill[wy0:wy1, wx0:wx1]
        fd = filled[wy0:wy1, wx0:wx1]
        blend = fz & fd
        new = fz & ~fd
        tgt[new] = patch[new]
        tgt[blend] = 0.5 * tgt[blend] + 0.5 * patch[blend]
        filled[wy0:wy1, wx0:wx1] |= fz
    rep = {"tiles": len(tiles), "tile": tile, "overlap": ov, "radius": radius, "candidates": ncand,
           "sourceWindows": int(len(cy)), "radiusWidened": widened,
           "toneShiftP95": round(float(np.percentile(tone, 95)), 2) if tone else 0.0}
    return np.clip(out, 0, 255), rep


def synth_back_texture(tex: np.ndarray, A: np.ndarray, zrest: np.ndarray, zmain: np.ndarray, zback: np.ndarray,
                       rast: dict, uv_used: np.ndarray, pad=16, src_zmain=None, src_zback=None, align=1
                       ) -> tuple[np.ndarray, tuple, dict]:
    """The back layer's texture: a crop of the piece's albedo (sRGB uint8) around the texels the back layer samples.
    Replaced by far-side synthesis: only texels whose rest-frame pixel the remaining main surface hides (zmain in front
    of zback: the ridge's own paint), less a PROTECT_TEXELS ring around every texel the back layer shows at rest (the
    cut cells: filtering and mips must not pull synthesis into the rest frame). Sources: far-side texels (the original
    rest depth zrest on the far side of the continued surface), not hidden, HALO_TEXELS away from the ridge's paint.
    Every other texel is a verbatim copy. The fill is quilt_fill (exemplar tiles copied from the far side).
    Returns (crop, (x0, y0, x1, y1) texel box, report)."""
    th, tw = tex.shape[:2]
    tx = uv_used[:, 0] * tw
    ty = (1 - uv_used[:, 1]) * th
    x0, x1 = max(int(tx.min()) - pad, 0), min(int(math.ceil(tx.max())) + pad, tw)
    y0, y1 = max(int(ty.min()) - pad, 0), min(int(math.ceil(ty.max())) + pad, th)
    if align > 1:
        # crop on a multiple of align texels: the crop's mip blocks then cover the same texels as the main texture's,
        # so the cut cells the back layer draws at rest filter exactly like the main surface did (an odd crop origin
        # shifts every mip block and re-tints minified distant terrain at rest: Castle rx_ldi_zone, y0 213)
        x0, y0 = x0 // align * align, y0 // align * align
        x1, y1 = min(-(-x1 // align) * align, tw), min(-(-y1 // align) * align, th)
    crop = tex[y0:y1, x0:x1, :3].astype(np.float32)
    jj, ii = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
    u, vv = jj / tw, 1 - ii / th
    fx = A[0, 0] * u + A[0, 1] * vv + A[0, 2]
    fy = A[1, 0] * u + A[1, 1] * vv + A[1, 2]
    hh, ww = zrest.shape
    xi = np.clip(np.floor(fx), 0, ww - 1).astype(np.int64)
    yi = np.clip(np.floor(fy), 0, hh - 1).astype(np.int64)
    zr, zm, zk = zrest[yi, xi], zmain[yi, xi], zback[yi, xi]
    zb = rast["zb"][yi, xi]
    has_back = np.isfinite(zk)
    hidden = has_back & (zm < zk / 1.0005)
    shown = has_back & ~hidden
    kp = 2 * PROTECT_TEXELS + 1
    protect = cv2.dilate(shown.astype(np.uint8), np.ones((kp, kp), np.uint8)) > 0
    fill = hidden & ~protect
    k = 2 * HALO_TEXELS + 1
    halo = cv2.dilate(hidden.astype(np.uint8), np.ones((k, k), np.uint8)) > 0
    if src_zback is not None:
        # the backstop: its own texels are all hidden at rest, so the sources are those of the back layer's texture
        zs_m, zs_b = src_zmain[yi, xi], src_zback[yi, xi]
        h_src = np.isfinite(zs_b) & (zs_m < zs_b / 1.0005)
        halo = cv2.dilate(h_src.astype(np.uint8), np.ones((k, k), np.uint8)) > 0
        src = np.isfinite(zr) & (zr >= zb / NEAR_RATIO) & ~h_src & ~halo
    else:
        src = np.isfinite(zr) & (zr >= zb / NEAR_RATIO) & ~hidden & ~halo
    syn, qrep = quilt_fill(crop, fill, src)
    out = np.where(fill[..., None], syn, crop)
    rep = {"cropTexels": [int(x0), int(y0), int(x1), int(y1)], "synthTexels": int(fill.sum()),
           "hiddenTexels": int(hidden.sum()), "shownAtRestTexels": int(shown.sum()),
           "sourceTexels": int(src.sum()), "quilt": qrep,
           "verbatimTexels": int((~fill).sum())}
    if align > 1:
        rep["cropAlign"] = int(align)
    return np.clip(out + 0.5, 0, 255).astype(np.uint8), (x0, y0, x1, y1), rep


def crop_uv(uv: np.ndarray, box: tuple, tw: int, th: int) -> np.ndarray:
    x0, y0, x1, y1 = box
    u = (uv[:, 0] * tw - x0) / (x1 - x0)
    v = ((1 - uv[:, 1]) * th - y0) / (y1 - y0)
    return np.stack([u, 1 - v], 1)


# ------------------------------------------------------------------------------------------------ stage I/O
def read_bin(path: Path):
    import struct
    b = path.read_bytes()
    nv, ns = struct.unpack_from("<ii", b, 0)
    o = 8
    v = np.frombuffer(b, np.float32, nv * 3, o).reshape(-1, 3); o += nv * 12
    n = np.frombuffer(b, np.float32, nv * 3, o).reshape(-1, 3); o += nv * 12
    uv = np.frombuffer(b, np.float32, nv * 2, o).reshape(-1, 2); o += nv * 8
    subs = []
    for _ in range(ns):
        (c,) = struct.unpack_from("<i", b, o); o += 4
        subs.append(np.frombuffer(b, np.int32, c, o).reshape(-1, 3)); o += c * 4
    return v, n, uv, subs


def write_bin(path: Path, v, n, uv, tris) -> None:
    import struct
    with open(path, "wb") as f:
        f.write(struct.pack("<ii", len(v), 1))
        f.write(np.asarray(v, np.float32).tobytes())
        f.write(np.asarray(n, np.float32).tobytes())
        f.write(np.asarray(uv, np.float32).tobytes())
        t = np.asarray(tris, np.int32).ravel()
        f.write(struct.pack("<i", len(t)))
        f.write(t.tobytes())


def unlayer_stage(stage: Path, env_prefab: str, bundle_dir: Path, rows_path: Path, report_path: Path,
                  npz_path: Path | None = None) -> dict:
    """Undo apply_stage on a staged candidate (see the module doc). npz_path: the layered stage's terrain_streak.npz
    when it is not in bundle_dir (candidate-init does not copy it: a candidate seeded from an LDI candidate reads its
    seed's); it must be the npz the stage report pins. Returns the report it records."""
    pdir = stage / env_prefab
    sr = json.loads(report_path.read_text(encoding="utf-8"))
    rep = sr.get("ldi")
    if not rep or not rep.get("pieces"):
        raise SystemExit(f"ldi unlayer: {report_path} has no ldi section (nothing was layered)")
    own = bundle_dir / str(rep.get("file", "terrain_streak.npz"))
    npz_path = Path(npz_path) if npz_path else own
    if not npz_path.is_file() or hashlib.sha256(npz_path.read_bytes()).hexdigest() != rep.get("sha256"):
        raise SystemExit(f"ldi unlayer: {npz_path} is missing or not the npz the stage report pins")
    z = np.load(npz_path)
    main_P = z["main_P"]
    cut = np.concatenate([z["cut_tris"], z["smear_cut_tris"]]).astype(np.int64)
    rows = json.loads(rows_path.read_text(encoding="utf-8"))
    env_rows = {b["name"]: b for b in rows[env_prefab]["bins"]}
    off, out = 0, {}
    staged = {}
    for name in rep["pieces"]:              # apply's piece order: the npz offsets follow it
        v, n, uv, subs = read_bin(pdir / f"{name}.bytes")
        if off + len(v) > len(main_P) or not np.array_equal(np.asarray(v, np.float64), main_P[off:off + len(v)]):
            raise SystemExit(f"ldi unlayer: {name} vertices are not the npz main_P slice at {off} (edited since apply)")
        inside = (cut >= off) & (cut < off + len(v))
        sel = inside.all(1)
        if (inside.any(1) != sel).any():
            raise SystemExit(f"ldi unlayer: a cut triangle of {name} straddles a piece boundary")
        tris = np.concatenate([*[s.astype(np.int64) for s in subs], cut[sel] - off])
        if len(np.unique(np.sort(tris, 1), axis=0)) != len(tris):
            raise SystemExit(f"ldi unlayer: {name} restored triangles repeat (the main bin already holds cut ones)")
        staged[name] = (v, n, uv, tris)
        out[name] = {"mainTris": int(sum(len(s) for s in subs)), "restoredTris": int(sel.sum())}
        off += len(v)
    if off != len(main_P) or sum(o["restoredTris"] for o in out.values()) != len(cut):
        raise SystemExit("ldi unlayer: the npz holds vertices or cut triangles of no recorded piece")
    back = list(rep.get("backPieces", []))
    extra = sorted(p.stem for p in pdir.glob("Mesh_Back_*.bytes") if p.stem not in back)
    if extra:
        raise SystemExit(f"ldi unlayer: {pdir} stages back bins the ldi record does not own: {extra}")
    for name, (v, n, uv, tris) in staged.items():
        write_bin(pdir / f"{name}.bytes", v, n, uv, tris)
    for b in back:
        for f in (f"{b}.bytes", f"{b}.bytes.meta", f"{b}_albedo.png", f"{b}_albedo.png.meta"):
            (pdir / f).unlink(missing_ok=True)
        env_rows.pop(b, None)
    rows[env_prefab]["bins"] = [env_rows[k] for k in sorted(env_rows)]
    rows_path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    own.unlink(missing_ok=True)
    res = {"schema": "town_full3d_ldi_unlayer.v1", "fromSha256": rep["sha256"], "removed": back, "pieces": out,
           "previous": {k: rep[k] for k in ("backRule", "keepRounds", "cutTris", "smearCutTris") if k in rep}}
    sr.pop("ldi")
    sr["ldiUnlayered"] = res
    report_path.write_text(json.dumps(sr, indent=1), encoding="utf-8")
    return res


def measure_stage(stage: Path, fov: float, rows: dict | None = None) -> dict:
    """Bridging-triangle counts of every staged lit bin (read-only), by prefab and piece."""
    out = {}
    for pdir in sorted(p for p in stage.iterdir() if p.is_dir() and p.name != "generated"):
        named = None if rows is None else {b["name"] for b in rows.get(pdir.name, {}).get("bins", [])}
        for mb in sorted(pdir.glob("*.bytes")):
            if mb.stem.startswith(("Fx_", "Sky_")) or (named is not None and mb.stem not in named):
                continue
            v, _n, _uv, subs = read_bin(mb)
            t = np.concatenate(subs)
            _fx, _fy, z = project(v, fov)
            out.setdefault(pdir.name, {})[mb.stem] = {"tris": int(len(t)), **bridging_counts(z, t)}
    return out


def apply_stage(stage: Path, env_prefab: str, pieces: list[str], fov: float, bundle_dir: Path, rows_path: Path,
                report_path: Path, poses=(), zone=None, crop_align=1, back_rule: dict | None = None,
                keep_rounds: int = KEEP_ROUNDS, skirt: bool = False) -> dict:
    from PIL import Image
    pdir = stage / env_prefab
    if list(pdir.glob("Mesh_Back_*.bytes")):
        raise SystemExit(f"ldi: {pdir} already carries Mesh_Back_* bins (re-seed the candidate; the main bins are "
                         "rewritten in place)")
    rows = json.loads(rows_path.read_text(encoding="utf-8"))
    env_rows = {b["name"]: b for b in rows[env_prefab]["bins"]}
    rep = {"schema": "town_full3d_ldi.v1", "fov": fov, "poses": len(poses), "pieces": {}, "keepRounds": keep_rounds,
           "frame": {"w": W, "h": H, "focalRefH": FH},
           "backRule": dict(back_rule) if back_rule else {"rule": "cap"}}
    main_P, main_T, back_P, back_T, cut_T, smear_T = [], [], [], [], [], []
    off_m = off_b = 0
    for name in pieces:
        mb = pdir / f"{name}.bytes"
        if name not in env_rows or not mb.is_file():
            raise SystemExit(f"ldi: {env_prefab}/{name} is not a staged row")
        v, n, uv, subs = read_bin(mb)
        tris = np.concatenate(subs).astype(np.int64)
        fx, fy, _z = project(v, fov)
        A, res = uv_affine(uv.astype(np.float64), fx, fy)
        frozen, skirt_rep = None, None
        if res > AFFINE_TOL_PX and skirt:
            # --frame auto: a mirror skirt past the painted canvas is allowed; its triangles are frozen (never cut)
            A, res, reg = uv_affine_registered(uv.astype(np.float64), fx, fy)
            if reg.mean() < 0.6:
                raise SystemExit(f"ldi: {name}: only {reg.mean():.0%} of the vertices follow one affine uv map")
            frozen = ~reg[tris].all(1)
            skirt_rep = {"registeredVerts": round(float(reg.mean()), 4), "frozenTris": int(frozen.sum()),
                         "frozenRatioOverCap": int((depth_ratio(_z, tris)[frozen] > RATIO_CAP + 1e-6).sum())}
            print(name, "skirt", json.dumps(skirt_rep), flush=True)
        if res > AFFINE_TOL_PX:
            raise SystemExit(f"ldi: {name} uv is not an affine map of the rest frame (residual {res:.3f} px)")
        out, krep = keep_holes(v, n, uv, tris, fov, poses, rounds=keep_rounds, zone=zone, back_rule=back_rule,
                               frozen=frozen)
        if out is None:
            rep["pieces"][name] = {"cutTris": 0, "bridgingBefore": bridging_counts(_z, tris)}
            main_P.append(v.astype(np.float64)); main_T.append(tris + off_m); off_m += len(v)
            continue
        mv_, mn_, muv_, mt_ = out["main"]
        bv, bn, buv, bt = out["back"]
        tex_path = pdir / f"{name}_albedo.png"
        tex = np.asarray(Image.open(tex_path).convert("RGB"))
        zrest = rest_depth(v, tris, fov)
        zmain = rest_depth(mv_, mt_, fov)
        zback = rest_depth(bv, bt, fov)
        crop, box, trep = synth_back_texture(tex, A, zrest, zmain, zback, out["rasters"], buv, align=crop_align)
        sv, sn, suv, st = out["stop"]
        # the backstop is hidden everywhere at rest: its texture is far-side synthesis throughout
        has_stop = len(st) > 0          # none kept: no reachable pose sees past this piece's back layer
        if has_stop:
            crop_s, box_s, trep_s = synth_back_texture(tex, A, zrest, np.minimum(zmain, zback),
                                                       rest_depth(sv, st, fov), out["rasters"], suv,
                                                       src_zmain=zmain, src_zback=zback, align=crop_align)
        th, tw = tex.shape[:2]
        buv_c = crop_uv(buv, box, tw, th)
        back_name = f"Mesh_Back_{name[len('Mesh_'):]}"
        # main bin rewritten without the cut triangles (vertices and texture untouched); back bin + its texture added
        write_bin(mb, mv_, mn_, muv_, mt_)
        write_bin(pdir / f"{back_name}.bytes", bv, bn, buv_c, bt)
        Image.fromarray(crop).save(pdir / f"{back_name}_albedo.png")
        stop_name = f"{back_name}_Far"
        if has_stop:
            write_bin(pdir / f"{stop_name}.bytes", sv, sn, crop_uv(suv, box_s, tw, th), st)
            Image.fromarray(crop_s).save(pdir / f"{stop_name}_albedo.png")
        row = dict(env_rows[name])
        row.update({"name": back_name, "mesh": row["mesh"].replace(f"/{name}.bytes", f"/{back_name}.bytes"),
                    "texture": row["texture"].replace(f"/{name}_albedo.png", f"/{back_name}_albedo.png")})
        env_rows[back_name] = row
        if has_stop:
            row_s = dict(env_rows[name])
            row_s.update({"name": stop_name, "mesh": row_s["mesh"].replace(f"/{name}.bytes", f"/{stop_name}.bytes"),
                          "texture": row_s["texture"].replace(f"/{name}_albedo.png", f"/{stop_name}_albedo.png")})
            env_rows[stop_name] = row_s
        rep["pieces"][name] = {**out["report"], "backPiece": back_name, "texture": trep, "revealHoles": krep,
                               **({"stopPiece": stop_name, "stopTexture": trep_s} if has_stop else {}),
                               "uvAffineResidualPx": round(res, 4), **({"skirt": skirt_rep} if skirt_rep else {})}
        main_P.append(mv_); main_T.append(mt_ + off_m)
        cut_T.append(out["cut"][out["cutByRatio"]] + off_m)
        smear_T.append(out["cut"][~out["cutByRatio"]] + off_m)
        off_m += len(mv_)
        back_P.append(bv); back_T.append(bt + off_b); off_b += len(bv)
        if has_stop:
            back_P.append(sv); back_T.append(st + off_b); off_b += len(sv)
        print(name, json.dumps({k: rep["pieces"][name][k] for k in ("cutTris", "backTris", "backAnisoP99",
                                                                     "maxRatioAfter")}), flush=True)
    rows[env_prefab]["bins"] = [env_rows[k] for k in sorted(env_rows)]
    rows_path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    if not back_T:
        raise SystemExit("ldi: no piece bridges a depth step; nothing to do")
    npz = bundle_dir / "terrain_streak.npz"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(npz, main_P=np.concatenate(main_P), main_tris=np.concatenate(main_T).astype(np.int32),
                        back_P=np.concatenate(back_P), back_tris=np.concatenate(back_T).astype(np.int32),
                        cut_tris=np.concatenate(cut_T).astype(np.int32),
                        smear_cut_tris=np.concatenate(smear_T).astype(np.int32), cpos=np.zeros(3), cam_fwd=np.array([0, 0, 1.0]),
                        ratio_cap=np.array(RATIO_CAP))
    # cut_tris: the ratio cuts only - the validator's negative check (every stored cut exceeds the cap) holds for
    # them by construction; the pose-smear cuts (ratio under the cap) are stored apart as smear_cut_tris
    rep.update({"ratioCap": RATIO_CAP, "cutTris": int(sum(len(c) for c in cut_T)),
                "smearCutTris": int(sum(len(c) for c in smear_T)), "file": npz.name,
                "sha256": hashlib.sha256(npz.read_bytes()).hexdigest(),
                "backPieces": sorted([r["backPiece"] for r in rep["pieces"].values() if "backPiece" in r]
                                     + [r["stopPiece"] for r in rep["pieces"].values() if "stopPiece" in r]),
                "frame": "prefab-local (rest camera at the origin, forward +z)",
                "proofTier": "generated artifact / offline render"})
    sr = json.loads(report_path.read_text(encoding="utf-8"))
    sr["ldi"] = rep
    report_path.write_text(json.dumps(sr, indent=1), encoding="utf-8")
    return rep


def local_poses(sc, S) -> list:
    """The vanilla camera's proof poses (the cursor rotations and sweep extremes the runtime reaches; not the rest pose)
    in the prefab-local frame: [(pos, R)], R's columns the pose's right / up / forward."""
    out = []
    for k, cam in S.pan_cams(sc).items():
        if k == "default":
            continue
        pos = sc.local(np.asarray(cam["pos"], np.float64)[None])[0]
        R = np.stack([sc.local_dir(np.asarray(cam[a], np.float64)[None])[0] for a in ("right", "up", "fwd")], 1)
        out.append((pos, R))
    return out


def reach_poses(sc, loop: int) -> list:
    """The zero-streak certificate's reachable set (proof poses + forward dolly + loop samples, without the rest pose)
    in the prefab-local form local_poses returns."""
    import town_full3d_zero_streak as ZS
    out = []
    for k, cam in ZS.reachable_cams(sc, loop).items():
        if k == "default":
            continue
        pos = sc.local(np.asarray(cam["pos"], np.float64)[None])[0]
        R = np.stack([sc.local_dir(np.asarray(cam[a], np.float64)[None])[0] for a in ("right", "up", "fwd")], 1)
        out.append((pos, R))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["apply", "measure", "unlayer"])
    ap.add_argument("--faction", required=True)
    ap.add_argument("--pieces", default="Mesh_Terrain,Mesh_TerrainNear_0,Mesh_TerrainNear_1")
    ap.add_argument("--out", default="", help="measure: write the counts here (json)")
    ap.add_argument("--npz", default="", help="unlayer: the layered stage's terrain_streak.npz (default: the "
                    "candidate's own bundle; a seeded candidate passes its seed's, sha-checked against the report)")
    ap.add_argument("--cut", default="smear", choices=["smear", "zone"],
                    help="apply: smear = the per-triangle ratio + pose-smear cut (default); zone = the opt-in occlusion-zone "
                         "cut (occlusion_zone_cut), for sharp depth maps whose edges are ramps")
    ap.add_argument("--crop-align", type=int, default=1,
                    help="apply: align the back layers' texture crops to this many texels (1 = as before; 64 keeps the "
                         "mip blocks of the cut cells shown at rest identical to the main texture's)")
    ap.add_argument("--zone", default="", help="--cut zone: json overrides of ZONE_DEFAULTS, e.g. '{\"r\": 16}'")
    ap.add_argument("--back-rule", default="cap", choices=["cap", "vlb"],
                    help="apply: cap = relax the back layer under the ratio cap (default); vlb = the view-set bound "
                         "with K (--vlb-k) on top of the cap, tiles still over it become cards (methodology v2 pilot 1)")
    ap.add_argument("--vlb-k", type=float, default=VLB_K)
    ap.add_argument("--keep-rounds", type=int, default=KEEP_ROUNDS,
                    help="apply: keep_holes rounds (0 = no stretched smear cut is put back where a hole opens; with a "
                         "frame-wide backstop behind it the hole is closed by the backstop instead)")
    ap.add_argument("--reach-loop", type=int, default=0,
                    help="apply: cut and close against the zero-streak certificate's reachable set with this many loop "
                         "samples (town_full3d_zero_streak.reachable_cams) instead of the proof poses (0)")
    ap.add_argument("--frame", default="rest", choices=["rest", "auto"],
                    help="apply: rest = the 1920x1080 rest frame (default); auto = rasters grown symmetrically about the "
                         "principal point to cover every piece (same focal length), and a mirror skirt whose uv does not "
                         "follow the rest frame is allowed but never cut (the no-split lane's canvas grid)")
    a = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import stronghold_full3d_scene as S
    sc = S.Scene()
    fov = float(sc.cam["fov"])
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    if a.cmd == "measure":
        res = measure_stage(S.STAGE, fov, rows)
        txt = json.dumps(res, indent=1)
        if a.out:
            Path(a.out).write_text(txt, encoding="utf-8")
        print(txt)
        return 0
    if not S.CANDIDATE:
        raise SystemExit(f"ldi {a.cmd}: set TOWN_FULL3D_CANDIDATE (the shipped outputs are never rewritten)")
    if a.cmd == "unlayer":
        print(json.dumps(unlayer_stage(S.STAGE, S.ENV_KEY, S.OUT, S.ROWS, S.WORK / "stage_report.json",
                                       Path(a.npz) if a.npz else None)))
        return 0
    if a.frame == "auto":
        global W, H
        px = py = 0
        for name in [p for p in a.pieces.split(",") if p]:
            mb = S.STAGE / S.ENV_KEY / f"{name}.bytes"
            if mb.is_file():
                fx, fy, _ = project(read_bin(mb)[0], fov)
                px = max(px, math.ceil(max(-fx.min(), fx.max() - W, 0)) + 2)
                py = max(py, math.ceil(max(-fy.min(), fy.max() - H, 0)) + 2)
        W, H = W + 2 * px, H + 2 * py
        print("ldi frame", W, "x", H, "(focal ref", FH, "px)", flush=True)
    rep = apply_stage(S.STAGE, S.ENV_KEY, [p for p in a.pieces.split(",") if p], fov, S.OUT, S.ROWS,
                      S.WORK / "stage_report.json", reach_poses(sc, a.reach_loop) if a.reach_loop else local_poses(sc, S),
                      zone=None if a.cut == "smear" else {**ZONE_DEFAULTS, **json.loads(a.zone or "{}")},
                      crop_align=a.crop_align,
                      back_rule={"rule": "vlb", "K": a.vlb_k} if a.back_rule == "vlb" else None,
                      keep_rounds=a.keep_rounds, skirt=a.frame == "auto")
    print(json.dumps({k: rep[k] for k in ("cutTris", "backPieces", "sha256")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
