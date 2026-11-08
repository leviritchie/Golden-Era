#!/usr/bin/env python3
"""One continuous sky for a full-3D town candidate: a single camera-locked panorama surface (prototype: Inferno).

    TOWN_FULL3D_FACTION=inferno TOWN_FULL3D_CANDIDATE=sky_cont_v1 python tools/homm3_town_scene_meshes/town_full3d_sky_continuous.py pano
    ...                                                                                       town_full3d_sky_continuous.py stage
    (catalog is rewritten by stage; bundle / render: stronghold_full3d_scene.py --faction inferno bundle | render)
    ...                                                                                       town_full3d_sky_continuous.py measure --before props_v1
    ...                                                                                       town_full3d_sky_continuous.py sheet --before props_v1

Design (docs/homm3_town_sky_continuous.md): the sky is ONE surface, Sky_Pano, a sphere around the rest camera drawn by
Homm3Town/SkyPanorama. The shader looks the panorama up by view direction only (object-space direction from the
camera, so the root's aspect scale and every pan pose see the same sky: zero parallax) and writes depth just inside
the far plane, so every mesh draws in front of it. The panorama is an equirectangular image (PANO_W x PANO_H, azimuth
from the rest heading, column 0 behind the camera so a static sky's wrap is never in view - a drifting one (Castle) turns it through every
view, so the wrap limit is a real limit; elevation EL_MIN..EL_MAX):
  painted   directions the rest camera sees on the painted sky P (the profile's SKY_MASK plus the dark painted sky the
            colour rule leaves out: DA disparity < daMax connected to SKY_MASK, rows < rowMax) take the HoMM3 painting
            itself (2x LANCZOS, bilinear, as the old dome sampled it): the rest frame is the painting.
  extension everywhere else is the painted sky itself, re-laid: the painted tile's holes (ridge peaks, the sun's
            surround) are filled by horizontally shifted painted rows; around the back run 1-D quilted strips of the
            sun-free painted plate and its mirror (whole-height pieces chosen by SSD on a 6 deg overlap, joined by a
            minimum-error cut + two-band blend), phase-matched to each painted edge and meeting once behind the
            camera; above the band, periodic quilted strips of the plate's top rows are stacked (alternately flipped
            so dark meets dark); beyond SYN_EL a per-row mean fade. A tone carry (SKY_EDGE_MATCH's rule, the sun never
            a reference) and a C0 membrane close the painted edge. No SD panorama, no AI, no stretch; P's own px are
            never changed.
The relief stops carrying sky: Mesh_Terrain triangles whose centroid is on P are cut, and the albedo texels on P of the
triangles kept at the silhouette take the nearest non-sky texel, so the skyline is crisp in front of the panorama
(no sky-coloured halo moving with the ridge). Sky_Dome / Sky_Drift are removed: one Sky_ piece.
Opt-in per candidate (stage_report["skyPano"] -> catalog skyLook + bundleShaders). Proof tier: generated artifact +
offline preview; editor render and runtime unproven until the bundle is built and rendered.
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
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stronghold_full3d_common as SC  # noqa: E402
import stronghold_full3d_scene as S  # noqa: E402
import stronghold_full3d_terrain as T  # noqa: E402

SCHEMA = "town_full3d_sky_continuous.v1"
SHADER = "Homm3Town/SkyPanorama"
SHADER_FILE = "Homm3TownSkyPanorama.shader"
PIECE = "Sky_Pano"
TEX_NAME = f"{PIECE}_equirect.png"
PANO_W, PANO_H = 6144, 1280            # 17.1 px / deg (HoMM3 native ~12.6 px / deg at the rest frame)
EL_MIN, EL_MAX = -20.0, 55.0           # deg; the reachable poses see about -10 .. +25
AZ0 = -180.0                           # column 0: directly behind the rest camera (the wrap is never in view)
SPHERE_R = 100.0                       # prefab units; depth is pinned to the far plane by the shader, so only > near
SPHERE_SEG = (96, 48)
MEASURE_EL = (2.0, 25.0)              # seam band measured: the sky the reachable poses show above the ridge
MIRROR_EXTRA_DEG = 1.5                 # assemble edgeJoin mirror: reflected span beyond the next piece's overlap
BELOW_BLUR_DEG = 3.0                   # below_painted_smooth: horizontal blur of the sky continued below the lowest painted row
BELOW_RAMP_DEG = 1.5                   # ... ramped in over this far above that row
SYN_EL = (-8.0, 32.0)                  # quilted band; outside it a smooth fade (never visible: max pose el ~ 25)
SKY_QUEUE = 1000
NPZ = "sky_continuity.npz"
# Seam metric (line detector, on the half-resolution panorama inside MEASURE_EL): a straight vertical / horizontal line
# is a column (row) boundary whose median adjacent-pixel L* step over a SEAM_WIN px window stands above the local
# background (the median of the boundaries 3..SEAM_BG px either side). The painting's own sky, measured the same way at
# the same angular scale, is the reference: no line of the panorama may stand out more than SEAM_REL_MAX times the
# painting's own strongest one (the painting's smoke bands are strong horizontal structure; a seam the eye reads as a
# seam is stronger than that). The wrap column and the painted edge get their own limits.
SEAM_WIN, SEAM_BG = 80, 12
SEAM_REL_MAX = 1.1
WRAP_RATIO_MAX = 1.6
EDGE_RATIO_MAX = 2.6                   # painted-edge step / the painting's own median adjacent step
REST_DE_MEAN_MAX, REST_DE_P95_MAX = 2.5, 7.0
REST_CONSIST_MAX = 3.0                 # rest_sky vs the half-resolution panorama's own rest lookup (mean dE)
RELIEF_SKY_PX_MAX = 400                # rect px on the eroded painted sky still covered by relief at rest

# Hand-set per painting.
#   ext      the dark painted sky SKY_MASK's colour rule leaves out: DA disparity < daMax, rect rows < rowMax,
#            connected to SKY_MASK (Inferno: the black smoke band rows ~170-215 the relief carried as slabs)
#   exclude  quilting sources excluded (the sun disc and its glow: one sun, at its painted place)
TOWNS = {
    "inferno": {
        "ext": {"daMax": 0.5, "rowMax": 340,
                "reason": "the black smoke band (rect rows ~170-215) is painted sky darker than SKY_MASK's lab rule"},
        "exclude": {"lMin": 62.0, "bMin": 35.0, "dilatePx": 70,
                    "reason": "the painted sun disc and its glow: quilting must not copy a second sun"},
        "plateAzDeg": [-24.0, 20.5],
        "seed": 11,
        "extSky": {"rule": "ridgeDark", "max": 8, "run": 8,
                   "reason": "the extension's outpaint ridge is a near-black silhouette under red cloud and a pale "
                             "haze band"},
        "reason": "worst seams of the installed full-3D towns (2026-10-01 audit): the relief carried the smoke band as "
                  "horizontal slabs that smear at every sweep, the SD panorama's swirl style steps at x1440, and the "
                  "dome / relief / panorama meet in three places",
    },
    "castle": {
        "ext": {"daMax": 0.5, "rowMax": 210,
                "reason": "white cumulus left of the spires (rect rows ~95-180) and at the upper right that the blue "
                          "SKY_MASK rule leaves out; rowMax keeps the far snow mountains (rows 219+, also low "
                          "disparity) as relief"},
        "exclude": {"lMin": 101.0, "bMin": 0.0, "dilatePx": 0,
                    "reason": "no sun or moon disc in the painting (L* never exceeds 100: nothing is excluded)"},
        "plateAzDeg": [-23.5, 20.5],
        "edgeJoin": "mirror",
        "seed": 12,  # seeds 1-12 scanned (mirror edge join): 12 has the lowest horizontal seam (stack joins) and wrap
        "extSky": {"rule": "none",
                   "reason": "the frame extension is the TOWN_FULL3D_EXTSRC outpaint (extsrc_p2_blend) and the far "
                             "wall is already fitted to its own skyline (profile EXT_SKYLINE): no relief stands on its "
                             "sky, so there is nothing to cut beyond the rect's P"},
        "ring": "rebake",
        "edgeSkylineCut": False,
        "ringReason": "the staged ring carried the outpaint's sky and a cloud on Mesh_OuterL2 (sweep_left: a sky slab "
                      "with a hard top edge on the far left hills), so it is rebaked from the painting like Inferno's; "
                      "the frame extension has no painted sky at the frame's right edge, so no edge skyline is held",
        "reason": "second town: its separate Sky_Drift band (SKY_ANIM drift, period 2400 s) folds into the one "
                  "panorama's shader drift",
    },
}


def town() -> dict:
    if SC.FACTION not in TOWNS:
        raise SystemExit(f"sky continuous: no hand-set parameters for {SC.FACTION} (prototype towns: {sorted(TOWNS)})")
    return TOWNS[SC.FACTION]


def drift_deg_per_s() -> float:
    """The profile's SKY_ANIM drift folded into the one panorama: 360 / periodS deg/s (0 for a static sky). The whole
    panorama turns as one layer; the runtime zeroes the shader clock at scene apply so the rest view starts on the
    painting."""
    anim = getattr(SC.FP, "SKY_ANIM", None) or {}
    if anim.get("mode") != "drift":
        return 0.0
    period = float(anim["periodS"])
    if not period > 0:
        raise SystemExit(f"sky continuous: SKY_ANIM periodS {period} is not positive")
    return round(360.0 / period, 6)


def need_candidate() -> None:
    if not S.CANDIDATE:
        raise SystemExit("sky continuous: opt-in per candidate only - set TOWN_FULL3D_CANDIDATE (the base outputs are "
                         "the installed 'before')")


# ------------------------------------------------------------------------------------------------ geometry
def basis(cam) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The panorama's world frame: rest heading f, its right r, world up u (= painting up)."""
    f, r = T.heading(cam)
    return f, r, np.array([0.0, 1.0, 0.0])


def grid_az_el(w=PANO_W, h=PANO_H):
    az = AZ0 + (np.arange(w) + 0.5) * 360.0 / w
    el = EL_MAX - (np.arange(h) + 0.5) * (EL_MAX - EL_MIN) / h
    return az, el


def dirs(cam, az_deg, el_deg):
    f, r, u = basis(cam)
    A, E = np.radians(az_deg), np.radians(el_deg)
    return np.cos(E)[..., None] * (np.cos(A)[..., None] * f + np.sin(A)[..., None] * r) + np.sin(E)[..., None] * u


def to_az_el(cam, d):
    f, r, u = basis(cam)
    d = d / np.linalg.norm(d, axis=-1, keepdims=True)
    return np.degrees(np.arctan2(d @ r, d @ f)), np.degrees(np.arcsin(np.clip(d @ u, -1, 1)))


def pano_lookup(pano: np.ndarray, az, el) -> np.ndarray:
    """Bilinear panorama sample (wrap in azimuth, clamp in elevation), as the shader does at mip 0."""
    h, w = pano.shape[:2]
    u = (np.mod(np.asarray(az) - AZ0, 360.0) / 360.0 * w - 0.5).astype(np.float32)
    v = np.clip((EL_MAX - np.asarray(el)) / (EL_MAX - EL_MIN) * h - 0.5, 0, h - 1).astype(np.float32)
    return cv2.remap(pano.astype(np.float32), u, v, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)


def frame_rays(cam, w, h):
    """Unit view rays of a w x h frame (pixel centres) for a camera dict (vertical fov)."""
    t = math.tan(math.radians(cam["fov"]) / 2)
    xs = ((np.arange(w) + 0.5) / w) * 2 - 1
    ys = 1 - ((np.arange(h) + 0.5) / h) * 2
    X, Y = np.meshgrid(xs * t * w / h, ys * t)
    d = cam["fwd"] + cam["right"] * X[..., None] + cam["up"] * Y[..., None]
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


# ------------------------------------------------------------------------------------------------ masks
def lab_l(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(np.clip(img, 0, 255).astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)[..., 0]


def rect_masks(cfg: dict) -> dict:
    """Frame-rect (TH x TW) masks: painting, SKY_MASK, the extended painted sky P, the excluded source (sun)."""
    paint = T.painting()
    sky = T.sky_mask(paint)
    da = np.load(SC.DATA / "depth" / "da_large.npy")
    if da.shape != sky.shape:
        raise SystemExit(f"sky continuous: da_large {da.shape} is not the rect {sky.shape}")
    rows = np.arange(SC.TH)[:, None]
    e = cfg["ext"]
    cand = sky | ((da < e["daMax"]) & (rows < e["rowMax"]))
    n, lab = cv2.connectedComponents(cand.astype(np.uint8), connectivity=8)
    keep = np.unique(lab[sky])
    P = np.isin(lab, keep[keep > 0])
    P = cv2.morphologyEx(P.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)).astype(bool) | sky
    x = cfg["exclude"]
    f = cv2.cvtColor(cv2.GaussianBlur(paint, (0, 0), 1.5).astype(np.float32) / 255, cv2.COLOR_RGB2LAB)
    bright = (f[..., 0] > x["lMin"]) & (f[..., 2] > x["bMin"]) & P
    n2, l2, st, _ = cv2.connectedComponentsWithStats(bright.astype(np.uint8), 8)
    excl = np.zeros_like(P)
    if n2 > 1:
        big = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        k = 2 * int(x["dilatePx"]) + 1
        excl = cv2.dilate((l2 == big).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    return {"paint": paint, "sky": sky, "P": P, "ext": P & ~sky, "excl": excl}


def painted_in_pano(sc, m: dict) -> dict:
    """The pano grid's rest projection: painting sample (float RGB), K (exact painted sky: P eroded 1 px, rect edges
    kept), the excluded-source mask, the in-rect mask."""
    from scipy.ndimage import binary_erosion
    az, el = grid_az_el()
    P_e = binary_erosion(m["P"], np.ones((3, 3), bool), iterations=1, border_value=1)
    pl = np.asarray(SC.background_rgb().resize((SC.TW * 2, SC.TH * 2), Image.LANCZOS)).astype(np.float32)
    img = np.zeros((PANO_H, PANO_W, 3), np.float32)
    K = np.zeros((PANO_H, PANO_W), bool)
    X = np.zeros_like(K)
    R = np.zeros_like(K)
    for r0 in range(0, PANO_H, 128):
        d = dirs(sc.cam, az[None, :], el[r0:r0 + 128, None])
        px, py, zc = T.project(sc.cam, sc.cam["pos"] + d)
        px, py = np.nan_to_num(px, nan=-1, posinf=-1, neginf=-1), np.nan_to_num(py, nan=-1, posinf=-1, neginf=-1)
        inside = (zc > 0) & (px >= 0) & (px <= SC.TW - 1) & (py >= 0) & (py <= SC.TH - 1)
        xi = np.clip(px.round(), 0, SC.TW - 1).astype(int)
        yi = np.clip(py.round(), 0, SC.TH - 1).astype(int)
        K[r0:r0 + 128] = inside & P_e[yi, xi]
        X[r0:r0 + 128] = inside & m["excl"][yi, xi]
        R[r0:r0 + 128] = inside
        u = np.clip(px * 2 + 0.5, 0, SC.TW * 2 - 1.001).astype(np.float32)
        v = np.clip(py * 2 + 0.5, 0, SC.TH * 2 - 1.001).astype(np.float32)
        img[r0:r0 + 128] = np.where(inside[..., None], cv2.remap(pl, u, v, cv2.INTER_LINEAR), 0)
    return {"img": img, "K": K, "excl": X, "inrect": R}


# ------------------------------------------------------------------------------------------------ synthesis
def el_row(el: float) -> int:
    return int(round((EL_MAX - el) * PANO_H / (EL_MAX - EL_MIN)))


def el_of_row(r: int) -> float:
    return EL_MAX - (r + 0.5) * (EL_MAX - EL_MIN) / PANO_H


def mincut_vertical(cost: np.ndarray) -> np.ndarray:
    """Column of the minimum-cost top-to-bottom path through cost (h, w), 8-connected: one column index per row."""
    h, w = cost.shape
    acc = cost.astype(np.float64).copy()
    back = np.zeros((h, w), np.int8)
    for y in range(1, h):
        prev = acc[y - 1]
        stack = np.stack([np.concatenate([[np.inf], prev[:-1]]), prev, np.concatenate([prev[1:], [np.inf]])])
        k = np.argmin(stack, 0)
        acc[y] += stack[k, np.arange(w)]
        back[y] = k - 1
    path = np.zeros(h, np.int64)
    path[-1] = int(np.argmin(acc[-1]))
    for y in range(h - 1, 0, -1):
        path[y - 1] = np.clip(path[y] + back[y, path[y]], 0, w - 1)
    return path


def join_lr(A: np.ndarray, B: np.ndarray, ov: int) -> np.ndarray:
    """A | B with the last ov columns of A over the first ov of B: a minimum-error cut for the detail and a linear
    crossfade over the whole overlap for the low-pass tone (two-band blend)."""
    h = A.shape[0]
    sig = max(ov / 6.0, 2.0)
    lowA, lowB = cv2.GaussianBlur(A, (0, 0), sig), cv2.GaussianBlur(B, (0, 0), sig)
    oa, ob = A[:, -ov:], B[:, :ov]
    cost = cv2.GaussianBlur((lab_l(oa) - lab_l(ob)) ** 2, (0, 0), 1.5)
    path = mincut_vertical(cost)
    mh = (np.arange(ov)[None, :] >= path[:, None]).astype(np.float32)
    mh = cv2.GaussianBlur(mh, (0, 0), 1.5)[..., None]
    ml = np.tile(((np.arange(ov) + 0.5) / ov).astype(np.float32)[None, :, None], (h, 1, 1))
    la, lb = lowA[:, -ov:], lowB[:, :ov]
    mid = la * (1 - ml) + lb * ml + (oa - la) * (1 - mh) + (ob - lb) * mh
    return np.concatenate([A[:, :-ov], mid, B[:, ov:]], 1)


def join_tb(A: np.ndarray, B: np.ndarray, ov: int) -> np.ndarray:
    """A over B (rows), the last ov rows of A over the first ov of B (join_lr transposed)."""
    return np.ascontiguousarray(join_lr(np.ascontiguousarray(A.transpose(1, 0, 2)),
                                        np.ascontiguousarray(B.transpose(1, 0, 2)), ov).transpose(1, 0, 2))


def push_pull3(val: np.ndarray, known: np.ndarray) -> np.ndarray:
    return np.stack([T.push_pull(val[..., c], known) for c in range(val.shape[2])], -1).astype(np.float32)


def fill_tile(img: np.ndarray, known: np.ndarray, src_ok: np.ndarray, rb: int) -> tuple[np.ndarray, int]:
    """The painted tile with its holes filled: hole components above row rb (ridge peaks, the excluded sun) take the
    same rows of the painted sky shifted horizontally (the shift whose 8 px ring around the hole matches best, the
    shifted pixels all src_ok), with a membrane (push-pull) correction of the ring difference; the rest (below the
    ridge's lowest painted sky) is the push-pull continuation of the sky above it (assemble smooths it below rb)."""
    out = img.copy()
    have = known.copy()
    hole = ~known
    hole[rb:] = False
    n, lab, st, _ = cv2.connectedComponentsWithStats(hole.astype(np.uint8), 8)
    h, w = known.shape
    g = 8
    copied = 0
    for i in range(1, n):
        x, y, bw, bh = (int(v) for v in st[i, :4])
        y0, y1, x0, x1 = max(y - g, 0), min(y + bh + g, h), max(x - g, 0), min(x + bw + g, w)
        comp = lab[y0:y1, x0:x1] == i
        ring = known[y0:y1, x0:x1] & ~comp
        best, bdx = np.inf, None
        for dx in range(-x0, w - x1 + 1, 2):
            if abs(dx) < bw // 2 + g:
                continue
            ok = src_ok[y0:y1, x0 + dx:x1 + dx]
            if not ok[comp].all():
                continue
            d = (out[y0:y1, x0 + dx:x1 + dx] - out[y0:y1, x0:x1])[ring & ok]
            c = float((d ** 2).mean()) if len(d) else np.inf
            if c < best:
                best, bdx = c, dx
        if bdx is None:
            continue                                  # no clean source: left to the push-pull below
        src = out[y0:y1, x0 + bdx:x1 + bdx].copy()
        diff = np.where(ring[..., None], out[y0:y1, x0:x1] - src, 0).astype(np.float32)
        corr = push_pull3(diff, ring)
        blk = out[y0:y1, x0:x1]
        blk[comp] = (src + corr)[comp]
        have[y0:y1, x0:x1] |= comp
        copied += 1
    fill = push_pull3(out, have & src_ok)
    return np.where(have[..., None], out, fill), copied


def best_phase(edge: np.ndarray, edge_ok: np.ndarray, plate: np.ndarray, lo: int, hi: int, right: bool) -> int:
    """Plate column whose neighbourhood best continues the painted edge strip (masked SSD over the band rows).
    right: the strip is the painting's last columns and the copy starts at the returned column, so the plate's
    columns just before it are compared; left: the copy ends at the returned column, the columns after it compared."""
    s = edge.shape[1]
    m3 = np.repeat(edge_ok[..., None].astype(np.float32), 3, 2)
    err = cv2.matchTemplate(plate.astype(np.float32), edge.astype(np.float32), cv2.TM_SQDIFF, mask=m3)[0]
    cols = np.arange(len(err)) + (s if right else 0)
    sel = (cols >= lo) & (cols <= hi)
    if not sel.any():
        raise SystemExit("sky continuous: no admissible phase for the edge join")
    return int(cols[sel][np.argmin(err[sel])])


def quilt_strip(sources: list, length: int, ov: int, lmin: int, lmax: int, rng, first: np.ndarray | None = None,
                first_src: tuple | None = None) -> tuple[np.ndarray, int]:
    """1-D quilting of whole-height strips: each next piece is the source span (any source, any start) whose first ov
    columns best match the strip's last ov (SSD, near-best picked at random), never the trivial continuation of the
    piece before it, joined by join_lr. Every piece keeps its rows, so the sky's elevation structure is the painting's."""
    if first is None:
        si = int(rng.integers(len(sources)))
        o = int(rng.integers(0, sources[si].shape[1] - lmin))
        L = min(int(rng.integers(lmin, lmax + 1)), sources[si].shape[1] - o)
        strip, cur = sources[si][:, o:o + L], (si, o + L)
    else:
        strip, cur = first, first_src
    n = 1
    while strip.shape[1] < length:
        tail = strip[:, -ov:].astype(np.float32)
        cands = []
        for si, src in enumerate(sources):
            err = cv2.matchTemplate(src.astype(np.float32), tail, cv2.TM_SQDIFF)[0]
            o = np.arange(len(err))
            ok = o + ov + lmin <= src.shape[1]
            if cur is not None and si == cur[0]:
                ok &= np.abs(o - (cur[1] - ov)) >= lmin
            for oi in o[ok]:
                cands.append((float(err[oi]), si, int(oi)))
        if not cands:
            raise SystemExit("sky continuous: quilt_strip found no admissible piece")
        e = np.array([c[0] for c in cands])
        near = np.nonzero(e <= e.min() * 1.1 + 1e-3)[0]
        _, si, o = cands[int(near[rng.integers(len(near))])]
        L = min(int(rng.integers(lmin, lmax + 1)), sources[si].shape[1] - o - ov)
        strip = join_lr(strip, sources[si][:, o:o + ov + L], ov)
        cur = (si, o + ov + L)
        n += 1
    return strip[:, :length], n


def close_wrap(strip: np.ndarray, w: int, ov: int) -> np.ndarray:
    """A strip of length w + ov whose first and last ov columns are the same panorama columns -> periodic, length w."""
    merged = join_lr(strip, strip[:, :2 * ov], ov)
    return merged[:, ov:w + ov]


def assemble(img: np.ndarray, K: np.ndarray, excl: np.ndarray, plate_az, seed: int, edge_join: str = "phase"):
    """The full panorama outside K (K's own px are put back by the caller): the painted tile with its holes filled
    (sun-free sources), 1-D quilted strips of the sun-free painted plate (and its mirror) from each painted edge
    around the back (phase-matched butt joins at the painted edges, one minimum-cut join behind the camera),
    periodic quilted strips of the plate's top rows stacked above, smooth fades beyond.

    edge_join: "phase" starts each chain with the plate span whose first columns best match the painted edge (a butt
    join: Inferno's smoke edge); "mirror" starts it with the painted tile reflected about its own edge for the
    next piece's overlap plus MIRROR_EXTRA_DEG (short, so no whole cloud is seen twice), so the painted edge continues
    exactly (Castle: the rect's right edge cuts through a bright cumulus, which a butt
    join shows as a straight vertical cut at rest)."""
    if edge_join not in ("phase", "mirror"):
        raise SystemExit(f"sky continuous: edgeJoin {edge_join!r} is not phase / mirror")
    rng = np.random.default_rng(seed)
    h, w = K.shape
    ppd = w / 360.0
    pc0, pc1 = (int(round((a - AZ0) * ppd)) for a in plate_az)
    ktop = np.array([np.argmax(K[:, c]) if K[:, c].any() else h for c in range(pc0, pc1)])
    r_top, r_bot = int(ktop.max()), el_row(SYN_EL[0])          # the band: the plate's lowest painted top row down
    kr = np.nonzero(K.any(1))[0]
    rb = int(kr.max())                                         # lowest painted sky row (the ridge base)
    good = K[r_top:el_row(7.0)].mean(0) >= 0.95
    runs, cur = [], None
    for c in range(w + 1):
        g = bool(good[c]) if c < w else False
        if g and cur is None:
            cur = c
        if not g and cur is not None:
            runs.append((cur, c))
            cur = None
    c0, c1 = max(runs, key=lambda r: r[1] - r[0])
    if not (c0 <= pc0 < pc1 <= c1):
        raise SystemExit(f"sky continuous: plateAzDeg {plate_az} is not inside the painted tile {c0}..{c1}")
    band = slice(r_top, r_bot)
    Kb, Xb, Ib = K[band, c0:c1], excl[band, c0:c1], img[band, c0:c1]
    src_ok = Kb & ~Xb
    tile0, n0 = fill_tile(Ib, Kb, src_ok, rb - r_top)
    plate_full, n1 = fill_tile(Ib, src_ok, src_ok, rb - r_top)
    plate = plate_full[:, pc0 - c0:pc1 - c0]
    wp, wt = pc1 - pc0, c1 - c0
    s = int(round(3.0 * ppd))
    ov = int(round(6.0 * ppd))
    lmin, lmax = int(round(14.0 * ppd)), int(round(26.0 * ppd))
    ok_rows = np.zeros((r_bot - r_top, s), bool)
    ok_rows[:rb - r_top] = True
    sources = [plate, np.ascontiguousarray(plate[:, ::-1])]
    # right chain: from the painted right edge (phase-matched start) around the back
    gap = w - wt
    half = (gap + ov) // 2
    off = pc0 - c0                                   # tile col j is plate col j - off
    lm = ov + int(round(MIRROR_EXTRA_DEG * ppd))     # mirror span: the next piece's overlap plus a little
    if edge_join == "mirror":
        # tile col wt-1-k continues at the edge's k-th column; in the mirrored plate that is col wp-1-(wt-1-k-off)
        phi = -1
        right, nr = quilt_strip(sources, half, ov, lmin, lmax, rng,
                                first=np.ascontiguousarray(tile0[:, ::-1][:, :lm]),
                                first_src=(1, wp - wt + off + lm))
    else:
        phi = best_phase(tile0[:, -s:], ok_rows & Kb[:, -s:], plate, s, wp - lmin, right=True)
        right, nr = quilt_strip(sources, half, ov, lmin, lmax, rng, first=plate[:, phi:], first_src=(0, wp))
    # left chain: the same in mirrored coordinates (sources mirrored), from the painted left edge leftward
    msources = [s_[:, ::-1].copy() for s_ in sources]
    if edge_join == "mirror":
        # mirrored coordinates: reading the tile from its left edge rightwards is the reflection about that edge;
        # msources[1] is the plate in its own orientation, where tile col j is plate col j - off
        psi = -1
        left_m, nl = quilt_strip(msources, gap + ov - half, ov, lmin, lmax, rng,
                                 first=np.ascontiguousarray(tile0[:, :lm]), first_src=(1, lm - off))
    else:
        psi = best_phase(tile0[:, :s], ok_rows & Kb[:, :s], plate, lmin, wp - s, right=False)
        left_m, nl = quilt_strip(msources, gap + ov - half, ov, lmin, lmax, rng,
                                 first=np.ascontiguousarray(plate[:, :psi][:, ::-1]), first_src=(0, psi))
    left = np.ascontiguousarray(left_m[:, ::-1])
    back = join_lr(right, left, ov)
    if back.shape[1] != gap:
        raise SystemExit(f"sky continuous: the chains cover {back.shape[1]} of {gap} columns")
    bandimg = np.roll(np.concatenate([tile0, back], 1), c0, axis=1)
    # rows above the band: periodic quilted strips of the plate's top 6 deg, every other one flipped vertically so
    # each join meets rows of the same elevation (dark top rows on dark top rows)
    hu = el_row(el_of_row(r_top) - 6.0) - r_top
    ovv = int(round(2.5 * ppd))
    tops = [np.ascontiguousarray(plate[:hu]), np.ascontiguousarray(plate[:hu, ::-1])]
    stack, r_cur, k = bandimg, r_top, 0
    r_end = el_row(SYN_EL[1])
    while r_cur > r_end:
        k += 1
        strip, _ = quilt_strip(tops, w + ov, ov, lmin, lmax, rng)
        layer = close_wrap(strip, w, ov)
        if k % 2 == 1:
            layer = layer[::-1]
        stack = join_tb(np.ascontiguousarray(layer), stack, ovv)
        r_cur -= hu - ovv
    canvas = np.zeros((h, w, 3), np.float32)
    lo = max(r_cur, 0)
    canvas[lo:r_bot] = stack[lo - r_cur:r_bot - r_cur]
    filled = np.zeros((h, w), bool)
    filled[lo:r_bot] = True
    rep = {"tileCols": [int(c0), int(c1)], "tileAzDeg": [round(AZ0 + c0 / ppd, 2), round(AZ0 + c1 / ppd, 2)],
           "plateCols": [pc0, pc1], "plateAzDeg": list(plate_az), "bandRows": [int(r_top), int(r_bot)],
           "ridgeBaseRow": rb, "holeCopies": [n0, n1], "phaseCols": [phi, psi], "edgeJoin": edge_join, "piecesRightLeft": [nr, nl],
           "overlapPx": ov, "pieceLenPx": [lmin, lmax], "stackLayers": k, "stackTopRow": int(lo),
           "stackOverlapPx": ovv, "seed": seed}
    return canvas, filled, rep


def fade_outside_band(canvas: np.ndarray, filled: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """Rows above / below the synthesised band: the mean colour of a row 3 deg inside it (one colour per row, so no
    vertical bands), crossfaded over those 3 deg (outside every reachable pose's view; it keeps the panorama's top
    and bottom free of pinched streaks)."""
    h, w = canvas.shape[:2]
    full = np.nonzero(filled.all(1))[0]
    if not len(full):
        raise SystemExit("sky continuous: the synthesis filled no complete pano row")
    e0, e1 = int(full.min()), int(full.max())
    F = int(round(3.0 * h / (EL_MAX - EL_MIN)))
    out = canvas.copy()

    def flat(y):
        return np.broadcast_to(canvas[y].mean(0), canvas[y].shape)
    ft, fb = flat(e0 + F), flat(e1 - F)
    for y in range(0, e0 + F):
        t = min(max((e0 + F - y) / F, 0.0), 1.0)
        out[y] = (canvas[y] if y >= e0 else 0) * (1 - t) + ft * t
    for y in range(e1 - F + 1, h):
        t = min(max((y - (e1 - F)) / F, 0.0), 1.0)
        out[y] = (canvas[y] if y <= e1 else 0) * (1 - t) + fb * t
    return out, [e0, e1]


def below_painted_smooth(canvas: np.ndarray, rb: int, K: np.ndarray, tile_cols) -> np.ndarray:
    """Below the lowest painted sky row rb no direction has a painted source: the hole fill's push-pull, the tone
    carry and the membrane all take each column's nearest painted px, straight above it, so the continuation reads as
    vertical streaks wherever a raised or swept camera sees over the relief (Castle sweep_high, behind the towers).
    From rb down it ramps over BELOW_RAMP_DEG into a horizontal-only blur (BELOW_BLUR_DEG, wrapped round the circle).
    At the painted tile's two edges the tile's continuation and the quilted back's meet as a butt join, which steps
    already between the edge column's own painted bottom and rb (Castle: L* 45 | 57 at az 20.6): within 2 blur sigmas
    of each edge the blur starts at that column's painted bottom instead. Painted px are never touched (the caller
    puts K back), and above rb away from the tile edges nothing changes, so the membrane's C0 join holds."""
    h, w = K.shape
    ppd = w / 360.0
    sig = BELOW_BLUR_DEG * ppd
    pad = int(3 * sig) + 1
    ext = np.concatenate([canvas[:, -pad:], canvas, canvas[:, :pad]], 1).astype(np.float32)
    smooth = cv2.GaussianBlur(ext, (0, 0), sigmaX=sig, sigmaY=0.5)[:, pad:pad + w]
    ramp = BELOW_RAMP_DEG * ppd
    yy = np.arange(h, dtype=np.float32)[:, None]
    ss = lambda x: (lambda c: c * c * (3.0 - 2.0 * c))(np.clip(x, 0.0, 1.0))  # noqa: E731
    cols = np.arange(w, dtype=np.float32)[None, :]
    c0, c1 = int(tile_cols[0]), int(tile_cols[1])
    in_tile = ((cols - c0) % w) < ((c1 - c0) % w)
    # inside the painted tile the blur starts at rb (above it the membrane's C0 join to the painting holds); in the
    # quilted back nothing is painted, so it is complete by rb (the quilt joins' lower rows meet in it)
    t = np.where(in_tile, ss((yy - rb) / ramp), ss((yy - rb + ramp) / ramp))
    for e, inside in ((c0, c0), (c1, c1 - 1)):
        kr = np.nonzero(K[:, inside % w])[0]
        kb = int(kr.max()) + 1 if len(kr) else rb
        dx = np.abs((cols - e + w / 2) % w - w / 2)
        t = np.maximum(t, ss(1.0 - dx / (2 * sig)) * ss((yy - kb + 1.0) / 2.0))
    t = t[..., None]
    return canvas * (1.0 - t) + smooth * t


def tone_carry(canvas: np.ndarray, K: np.ndarray, img: np.ndarray, excl: np.ndarray, sigma_deg=1.5,
               radius_deg=8.0) -> np.ndarray:
    """SKY_EDGE_MATCH's rule: the synthetic sky's low-pass tone is moved onto the painted sky's at the nearest painted
    direction, fully at the painted edge and fading out over radius_deg (the painted edge's dark smoke carries out
    instead of stepping to the copy's tone); the excluded sun is never a reference (its tone would carry 8 deg down
    behind the ridge as a pillar); K's own px are untouched."""
    from scipy.ndimage import distance_transform_edt
    w = K.shape[1]
    sig = sigma_deg * w / 360.0
    Kr = K & ~excl
    g = Kr.astype(np.float32)
    ng = cv2.GaussianBlur(g, (0, 0), sig)
    lp_img = cv2.GaussianBlur(img * g[..., None], (0, 0), sig) / np.maximum(ng, 1e-4)[..., None]
    lp_can = cv2.GaussianBlur(canvas, (0, 0), sig)
    core = (ng >= 0.5) & Kr
    dist, (iy, ix) = distance_transform_edt(~Kr, return_indices=True)
    _, (cy, cx) = distance_transform_edt(~core, return_indices=True)
    ref = lp_img[cy[iy, ix], cx[iy, ix]]
    wo = np.exp(-(dist / (radius_deg * w / 360.0)) ** 2)[..., None]
    return np.where(K[..., None], img, canvas + (ref - lp_can) * wo)


def membrane(canvas: np.ndarray, K: np.ndarray, img: np.ndarray, radius_deg=2.5, along_px=4.0) -> np.ndarray:
    """C0 join to the painted sky: the difference between each painted edge px and the synthetic px beside it,
    smoothed along the edge, spread outward by push-pull and faded over radius_deg; K's own px are the painting."""
    from scipy.ndimage import distance_transform_edt
    w = K.shape[1]
    ring = cv2.dilate(K.astype(np.uint8), np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], np.uint8)).astype(bool) & ~K
    dist, (iy, ix) = distance_transform_edt(~K, return_indices=True)
    diff = np.where(ring[..., None], img[iy, ix] - canvas, 0).astype(np.float32)
    rg = ring.astype(np.float32)
    ds = cv2.GaussianBlur(diff, (0, 0), along_px) / np.maximum(cv2.GaussianBlur(rg, (0, 0), along_px), 1e-4)[..., None]
    field = push_pull3(np.where(ring[..., None], ds, 0), ring)
    wgt = np.exp(-(dist / (radius_deg * w / 360.0)) ** 2)[..., None]
    return np.where(K[..., None], img, canvas + field * wgt)


# ------------------------------------------------------------------------------------------------ metrics
def _step_profile(L: np.ndarray, ok: np.ndarray | None, win: int, wrap: bool) -> np.ndarray:
    """Per (row window, column boundary): the median over the window's rows of |L[:, c+1] - L[:, c]| (NaN where
    fewer than half the window's px pairs are inside ok). Columns c = 0..w-1 (c = w-1 is the wrap pair if wrap)."""
    Lr = np.concatenate([L, L[:, :1]], 1) if wrap else L
    s = np.abs(np.diff(Lr, axis=1))
    if ok is not None:
        okr = np.concatenate([ok, ok[:, :1]], 1) if wrap else ok
        pair = okr[:, 1:] & okr[:, :-1]
        s = np.where(pair, s, np.nan)
    h = s.shape[0]
    out = []
    for y0 in range(0, max(h - win, 0) + 1, max(win // 2, 1)):
        blk = s[y0:y0 + win]
        n = np.sum(~np.isnan(blk), 0)
        with np.errstate(all="ignore"):
            med = np.nanmedian(blk, 0)
        med[n < win // 2] = np.nan
        out.append(med)
    return np.array(out)


def seam_ratio_map(L: np.ndarray, ok: np.ndarray | None = None, wrap: bool = False, win: int = SEAM_WIN,
                   bg: int = SEAM_BG, floor: float = 0.5) -> np.ndarray:
    """Straight-line seam detector along one axis (vertical lines = column boundaries of L): a column boundary's
    window-median L* step over the background (the median of the boundaries 3..bg px either side)."""
    m = _step_profile(L, ok, win, wrap)
    w = m.shape[1]
    offs = [d for d in range(-bg, bg + 1) if abs(d) >= 3]
    idx = (np.arange(w)[:, None] + np.array(offs)[None, :])
    if wrap:
        idx %= w
    else:
        idx = np.clip(idx, 0, w - 1)
    with np.errstate(all="ignore"):
        back = np.nanmedian(m[:, idx], 2)
    return m / np.maximum(back, floor)


def seam_stats(L: np.ndarray, ok: np.ndarray | None = None, wrap: bool = False) -> dict:  # noqa: C901
    """Max vertical- and horizontal-line seam ratios (and where) of an L* image."""
    rv = seam_ratio_map(L, ok, wrap=wrap)
    rh = seam_ratio_map(np.ascontiguousarray(L.T), None if ok is None else np.ascontiguousarray(ok.T))
    out = {}
    for k, r in (("vertical", rv), ("horizontal", rh)):
        if np.all(np.isnan(r)):
            out[k] = {"max": 0.0, "at": None}
            continue
        i = int(np.nanargmax(r))
        out[k] = {"max": round(float(np.nanmax(r)), 3), "at": [int(i // r.shape[1]), int(i % r.shape[1])]}
    out["max"] = max(out["vertical"]["max"], out["horizontal"]["max"])
    return out


def column_ratio(L: np.ndarray, cols, ok=None, wrap=False) -> float:
    """Max seam ratio at the given column boundaries (c means the pair c | c+1), +-1 px."""
    r = seam_ratio_map(L, ok, wrap=wrap)
    w = r.shape[1]
    sel = sorted({(c + d) % w for c in cols for d in (-1, 0, 1)})
    v = r[:, sel]
    return 0.0 if np.all(np.isnan(v)) else round(float(np.nanmax(v)), 3)


def edge_step_ratio(L: np.ndarray, K: np.ndarray, band: np.ndarray, chunk: int = SEAM_WIN) -> dict:
    """The painted-region boundary: |L* step| across K's edge (the edge px pair, 4-neighbour, inside band) over the
    median adjacent-pixel step inside K, per chunk of chunk edge px along the boundary; reports the max chunk."""
    inner = []
    for ax in (0, 1):
        a = np.abs(np.diff(L, axis=ax))
        kk = (K[1:] & K[:-1]) if ax == 0 else (K[:, 1:] & K[:, :-1])
        inner.append(a[kk])
    base = max(float(np.median(np.concatenate(inner))), 0.5)
    pairs = []
    for ax in (0, 1):
        a = np.abs(np.diff(L, axis=ax))
        if ax == 0:
            cross = (K[1:] != K[:-1]) & band[1:] & band[:-1]
            ys, xs = np.nonzero(cross)
        else:
            cross = (K[:, 1:] != K[:, :-1]) & band[:, 1:] & band[:, :-1]
            ys, xs = np.nonzero(cross)
        pairs.append(np.stack([xs, ys, a[ys, xs]], 1))
    p = np.concatenate(pairs)
    if not len(p):
        return {"max": 0.0, "base": base, "edgePx": 0}
    order = np.lexsort((p[:, 1], p[:, 0]))
    p = p[order]
    chunks = [p[i:i + chunk, 2] for i in range(0, len(p), chunk) if len(p[i:i + chunk]) >= chunk // 2]
    vals = [float(np.median(c)) / base for c in chunks]
    return {"max": round(max(vals), 3) if vals else 0.0, "base": round(base, 3), "edgePx": int(len(p)),
            "chunks": len(vals)}


def delta_e(a: np.ndarray, b: np.ndarray, m: np.ndarray) -> dict:
    """CIE76 dE between two sRGB uint8 / float 0..255 images over mask m."""
    la = cv2.cvtColor(np.clip(a, 0, 255).astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)
    lb = cv2.cvtColor(np.clip(b, 0, 255).astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)
    d = np.linalg.norm(la - lb, axis=-1)[m]
    if not len(d):
        return {"mean": 0.0, "p95": 0.0, "px": 0}
    return {"mean": round(float(d.mean()), 3), "p95": round(float(np.percentile(d, 95)), 3), "px": int(len(d))}


def pano_metrics(pano: np.ndarray, K: np.ndarray, el_band=(MEASURE_EL[0], MEASURE_EL[1])) -> dict:
    """The panorama's own seams inside the measured band (the elevations the reachable poses show as sky):
    straight-line seams anywhere (wrap included), the wrap column, the painted-region boundary."""
    r0, r1 = el_row(el_band[1]), el_row(el_band[0])
    L = lab_l(pano.astype(np.float32))[r0:r1]
    w = L.shape[1]
    band = np.zeros(K.shape, bool)
    band[r0:r1] = True
    return {"band": {"elDeg": list(el_band), "rows": [r0, r1]},
            "seams": seam_stats(L, wrap=True),
            "wrapRatio": column_ratio(L, [w - 1], wrap=True),
            "edge": edge_step_ratio(lab_l(pano.astype(np.float32)), K, band)}


def build_pano() -> dict:
    need_candidate()
    cfg = town()
    sc = S.Scene()
    m = rect_masks(cfg)
    pp = painted_in_pano(sc, m)
    canvas, filled, qrep = assemble(pp["img"], pp["K"], pp["excl"], cfg["plateAzDeg"], cfg["seed"],
                                    cfg.get("edgeJoin", "phase"))
    canvas, qrep["fullRows"] = fade_outside_band(canvas, filled)
    canvas = tone_carry(canvas, pp["K"], pp["img"], pp["excl"], sigma_deg=1.5, radius_deg=8.0)
    canvas = membrane(canvas, pp["K"], pp["img"])
    canvas = below_painted_smooth(canvas, int(qrep["ridgeBaseRow"]), pp["K"], qrep["tileCols"])
    pano = np.clip(np.where(pp["K"][..., None], pp["img"], canvas) + 0.5, 0, 255).astype(np.uint8)
    out = S.WORK / "sky_pano"
    out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pano).save(out / "pano.png")
    np.savez_compressed(out / "masks.npz", K=pp["K"], excl=pp["excl"], inrect=pp["inrect"], P=m["P"], sky=m["sky"],
                        ext=m["ext"], rect_excl=m["excl"])
    viz = m["paint"].astype(np.float32) * 0.6
    viz[m["sky"]] = viz[m["sky"]] * 0.5 + np.array([60, 60, 255]) * 0.5
    viz[m["ext"]] = viz[m["ext"]] * 0.3 + np.array([0, 230, 0]) * 0.7
    viz[m["excl"]] = viz[m["excl"]] * 0.5 + np.array([255, 255, 0]) * 0.5
    Image.fromarray(viz.clip(0, 255).astype(np.uint8)).save(out / "masks_rect.png")
    rep = {"schema": SCHEMA, "faction": SC.FACTION, "size": [PANO_W, PANO_H], "azDeg": [AZ0, AZ0 + 360.0],
           "elDeg": [EL_MIN, EL_MAX], "pxPerDeg": round(PANO_W / 360.0, 3), "paintedPx": int(pp["K"].sum()),
           "skyMaskPx": int(m["sky"].sum()), "extPx": int(m["ext"].sum()), "exclPx": int(m["excl"].sum()),
           "synthesis": qrep, "params": {k: v for k, v in cfg.items()},
           "sha256": hashlib.sha256((out / "pano.png").read_bytes()).hexdigest()}
    (out / "pano.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("size", "paintedPx", "extPx", "exclPx", "synthesis", "sha256")}, indent=1))
    return rep


# ------------------------------------------------------------------------------------------------ stage
def sphere(sc) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """The Sky_Pano sphere in the prefab frame (origin = the rest camera), radius SPHERE_R, inward normals. Its UVs are
    informational (the shader looks the panorama up by direction); its radius only has to exceed the near plane."""
    na, ne = SPHERE_SEG
    az = np.linspace(-180.0, 180.0, na + 1)
    el = np.linspace(-89.0, 89.0, ne + 1)
    A, E = np.meshgrid(az, el)
    d = dirs(sc.cam, A, E).reshape(-1, 3)
    dl = sc.local_dir(d)
    dl /= np.linalg.norm(dl, axis=1, keepdims=True)
    v = dl * SPHERE_R
    uv = np.stack([((A + 180.0) / 360.0).ravel(), ((E + 90.0) / 180.0).ravel()], 1)
    nx = na + 1
    j, i = np.meshgrid(np.arange(ne), np.arange(na), indexing="ij")
    a = (j * nx + i).ravel()
    tris = np.concatenate([np.stack([a, a + nx, a + 1], 1), np.stack([a + 1, a + nx, a + nx + 1], 1)]).astype(np.int32)
    return v, -dl, uv, tris


def frame_P(m: dict) -> np.ndarray:
    """P on the full 1920x1080 frame (the painted rect is its top-left TW x TH)."""
    out = np.zeros((SC.H, SC.W), bool)
    out[:SC.TH, :SC.TW] = m["P"]
    return out


# the relief: terrain, the layered-depth back layer (town_full3d_ldi: Mesh_Back_Terrain*, built behind whatever the old
# SKY_MASK called rock, so it carries the painted cloud the mask missed) and the periphery ring; not props, rocks, scatter
RELIEF_RE = r"^Mesh_(Terrain\w*|Back_Terrain\w*|Outer[LRC]\d+)$"


def env_mesh_pieces(rows: dict) -> list[str]:
    """The relief pieces the cut applies to. Props / rocks / boulders standing in front of the painted sky at rest are
    deliberate objects (props_v1's streak-cover crag) and are never cut; their sky cover is reported separately."""
    import re
    return [b["name"] for b in rows[S.ENV_KEY]["bins"] if re.match(RELIEF_RE, b["name"]) and b.get("kind") == "lit"]


def object_pieces(rows: dict) -> list[str]:
    import re
    return [b["name"] for b in rows[S.ENV_KEY]["bins"] if b["name"].startswith("Mesh_")
            and not re.match(RELIEF_RE, b["name"])]


def relief_cover(sc, pieces: dict) -> np.ndarray:
    """Frame px (1920x1080) covered at rest by the given env meshes {name: (v_local, tris)}: triangle rasterisation of
    the rest projection (no depth needed: any cover of the painted sky by relief is what is counted)."""
    cov = np.zeros((SC.H, SC.W), np.uint8)
    for v, tris in pieces.values():
        w = v / sc.scale @ sc.C.T + sc.cpos
        px, py, zc = T.project(sc.cam, w)
        ok = (zc[tris] > 0.05).all(1)
        t = tris[ok]
        pts = np.stack([px[t], py[t]], -1)
        inb = (pts[..., 0].max(1) > -50) & (pts[..., 0].min(1) < SC.W + 50) & (pts[..., 1].max(1) > -50) \
            & (pts[..., 1].min(1) < SC.H + 50)
        pts = np.round(pts[inb] * 16).astype(np.int32)
        for k in range(0, len(pts), 50000):
            cv2.fillPoly(cov, list(pts[k:k + 50000]), 1, lineType=cv2.LINE_8, shift=4)
    return cov.astype(bool)


def orig_dir() -> Path:
    return S.WORK / "sky_pano" / "orig"


def keep_orig(env: Path, names: list[str]) -> None:
    """The seed's relief bins / albedo, copied once before the first cut so a restage always cuts the seed."""
    import shutil
    od = orig_dir()
    od.mkdir(parents=True, exist_ok=True)
    for n in names:
        for suf in (".bytes", "_albedo.png"):
            src, dst = env / f"{n}{suf}", od / f"{n}{suf}"
            if not dst.is_file():
                if not src.is_file():
                    raise SystemExit(f"sky continuous: {src} is not staged (seed incomplete)")
                shutil.copy2(src, dst)


OUTER_RE = r"^Mesh_Outer[LRC]\d+$"
RING_SEAM_FEATHER_PX = 240.0   # rest-frame px beyond the frame edge over which the ring continues the frame terrain


def frame_terrain_canvas(Pf: np.ndarray) -> np.ndarray:
    """The frame terrain's albedo (sRGB float, H x W x 3) on rest-frame px, from the seed's frame-box pieces, painted-sky
    texels already replaced by the nearest non-sky texel (what cut_relief stages). NaN where no piece covers."""
    import cv2 as _cv
    from scipy.ndimage import distance_transform_edt
    od = orig_dir()
    rep_t = json.loads((S.WORK / "stage_report.json").read_text(encoding="utf-8"))
    can = np.full((SC.H, SC.W, 3), np.nan, np.float32)
    for pc in sorted(rep_t["terrain"]["pieces"], key=lambda q: q["name"] != "Mesh_Terrain"):
        x0, y0, x1, y1 = pc["box"]
        alb = np.asarray(Image.open(od / f"{pc['name']}_albedo.png").convert("RGB")).astype(np.float32)
        a = _cv.resize(alb, (x1 - x0, y1 - y0), interpolation=_cv.INTER_AREA)
        on = Pf[y0:y1, x0:x1]
        if on.any() and (~on).any():
            _, (iy, ix) = distance_transform_edt(on, return_indices=True)
            a = a[iy, ix]
        reg = can[y0:y1, x0:x1]
        empty = np.isnan(reg[..., 0])
        reg[empty] = a[empty]
    return can


def ring_texel_proj(cam, field, pc: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Rest-frame (px, py, zc) of every texel centre of a ring piece (bake_piece's own texel -> world mapping)."""
    import stronghold_full3d_terrain as _T
    w, h = pc["size"]
    th = pc["th"][0] + (np.arange(w) + 0.5) / w * (pc["th"][1] - pc["th"][0])
    g = (h - 1 - np.arange(h) + 0.5) / h * pc["g"][-1]
    rho = np.interp(g, pc["g"], pc["rr"])
    Th, R = np.meshgrid(th, rho)
    X, Z = _T.polar_to_xz(cam, Th, R)
    Pw = np.stack([X, field.height(X, Z), Z], -1).reshape(-1, 3)
    px, py, zc = _T.project(cam, Pw.astype(np.float64))
    return px.reshape(h, w), py.reshape(h, w), zc.reshape(h, w)


RING_UV_TOL_TEXEL = 0.05      # a staged vertex is on the polar grid when this layout reproduces its UV to this
RING_ON_GRID_MIN = 0.95       # least share of staged vertices on the grid (the rest are settle-moved in-frame ones)


def ring_polar(cam, w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(theta deg, rho m) of world points about the camera: the inverse of stronghold_full3d_terrain.polar_to_xz."""
    import stronghold_full3d_terrain as _T
    f, r = _T.heading(cam)
    d = w - cam["pos"]
    a = d[:, 0] * f[0] + d[:, 2] * f[2]
    b = d[:, 0] * r[0] + d[:, 2] * r[2]
    return np.degrees(np.arctan2(b, a)), np.hypot(a, b)


def rebake_outer(sc, Pf: np.ndarray) -> tuple[dict, dict]:
    """The periphery ring's albedo re-derived from the HoMM3 painting with the painted sky P treated as sky.

    The ring (stronghold_full3d_periphery.bake_piece) fades from the rect's low-frequency edge colour into the vanilla
    synthesis. That edge colour was taken from the rect with SKY_MASK as the only sky, so the painted smoke band the
    mask leaves out (P minus SKY_MASK) was carried outward as ground colour; the seeded Inferno ring also carried a
    canvas strip at the frame edge (Mesh_OuterR2's left 0.1: painted-sky colour with ridge spires) that the current
    code does not produce. Here the edge colour is rebuilt from the painting with P as sky and every ring piece is
    rebaked with the periphery's own formula and no TOWN_FULL3D_EXTSRC canvas, so no painted sky lands outside the
    rect. Geometry is the staged one: each piece's layout must reproduce the staged texel -> world mapping (texture
    size, and the staged UVs of the vertices on the polar grid; fail closed otherwise). Returns ({name: sRGB uint8 albedo}, report)."""
    import cv2 as _cv
    from scipy.ndimage import distance_transform_edt
    import stronghold_full3d_ground as G
    import stronghold_full3d_periphery as PP
    if SC.GROUNDSRC:
        raise SystemExit("sky continuous: rebake_outer re-derives the ring from the painting; unset "
                         "TOWN_FULL3D_GROUNDSRC")
    # TOWN_FULL3D_EXTSRC may stay set: the terrain field is fitted to its skyline (profile EXT_SKYLINE, Castle), and the
    # staged geometry must be reproduced, but the canvas never textures the ring here (b.ext = None below)
    st = S.terrain_state(sc)
    b = st["baker"]
    cam, field, floor, fd, grid = (st[k] for k in ("cam", "field", "floor", "fd", "grid"))
    sky = fd["sky"][:SC.TH, :SC.TW] | Pf[:SC.TH, :SC.TW]
    low = _cv.GaussianBlur(np.where(sky[..., None], 0, b.alb_rect), (0, 0), 10)
    wt = _cv.GaussianBlur((~sky).astype(np.float32), (0, 0), 10)
    low = low / np.maximum(wt[..., None], 1e-3)
    full = np.zeros((SC.H, SC.W, 3), np.float32)
    known = np.zeros((SC.H, SC.W), bool)
    full[:SC.TH, :SC.TW] = low
    known[:SC.TH, :SC.TW] = wt > 0.2
    _, (iy, ix) = distance_transform_edt(~known, return_indices=True)
    near = full[iy, ix]
    wide = _cv.GaussianBlur(near, (0, 0), G.EDGE_BLUR_PX)
    b.edge_col = np.where(known[..., None], near, wide).astype(np.float32)
    b.ext = None
    hc = PP.cam_height(floor, cam)
    mesh = PP.polar_mesh(cam, field, PP.frame_depth_grid(grid, cam), fd["sky"])
    od = orig_dir()
    out, rep = {}, {}
    tmp = S.WORK / "sky_pano" / "_rebake_tmp.png"
    canvas = frame_terrain_canvas(Pf)
    can0 = np.nan_to_num(canvas, nan=0.0)
    have = (~np.isnan(canvas[..., 0])).astype(np.float32)
    for pc in PP.piece_layout(mesh, hc):
        n = pc["name"]
        if not (od / f"{n}.bytes").is_file():
            raise SystemExit(f"sky continuous: ring piece {n} is not staged in the seed")
        v, _, uv_st, _ = S.read_bin(od / f"{n}.bytes")
        seed = np.asarray(Image.open(od / f"{n}_albedo.png").convert("RGB"))
        w, h = pc["size"]
        # only the texel -> world mapping must be the staged one (the staged mesh and UVs are kept): the texture size
        # matches and the staged UVs of the vertices still on the polar grid (settle moves only in-frame ones) are
        # reproduced by this layout. The vertex count may differ (Castle: the field refitted from EXTSRC culls one
        # vertex fewer of Mesh_OuterC0), it never reaches the albedo
        wv = v / sc.scale @ sc.C.T + sc.cpos
        th_v, rho_v = ring_polar(cam, wv)
        uv_err = (np.abs(PP.piece_uv(pc, th_v, rho_v) - uv_st) * np.array([w, h])).max(1)
        on_grid = uv_err < RING_UV_TOL_TEXEL
        if seed.shape[:2] != (h, w) or on_grid.mean() < RING_ON_GRID_MIN:
            raise SystemExit(f"sky continuous: ring piece {n} texel mapping (tex {w}x{h}, staged UVs reproduced at "
                             f"{on_grid.mean():.3f} of {len(v)} verts) differs from the staged one (tex "
                             f"{seed.shape[1]}x{seed.shape[0]}, need >= {RING_ON_GRID_MIN}): restage the periphery "
                             f"first")
        dy = np.abs(wv[on_grid, 1] - field.height(wv[on_grid, 0], wv[on_grid, 2]))
        S.save_srgb(tmp, PP.bake_piece(b, field, floor, cam, pc))
        alb = np.asarray(Image.open(tmp).convert("RGB")).copy()
        # the seam with the frame terrain: beyond the frame edge the ring first continues the frame terrain mirrored
        # about that edge (texture-continuous, never an edge column stretched outward), fading into the synthesis
        px, py, zc = ring_texel_proj(cam, field, pc)
        beyond = np.where(px >= SC.W, px - (SC.W - 1), np.where(px < 0, -px, 0.0))
        mx = np.where(px >= SC.W, 2 * (SC.W - 1) - px, np.where(px < 0, -px, px))
        okp = (zc > 0.5) & (beyond > 0) & (beyond < RING_SEAM_FEATHER_PX)
        mxs = np.clip(mx, 0, SC.W - 1).astype(np.float32)
        mys = np.clip(py, 0, SC.H - 1).astype(np.float32)
        samp = _cv.remap(can0, mxs, mys, _cv.INTER_LINEAR, borderMode=_cv.BORDER_REPLICATE)
        sh = _cv.remap(have, mxs, mys, _cv.INTER_LINEAR, borderMode=_cv.BORDER_REPLICATE)
        t = np.clip(beyond / RING_SEAM_FEATHER_PX, 0, 1)
        wgt = np.where(okp, (1 - t * t * (3 - 2 * t)) * (sh > 0.99), 0.0)[..., None]
        alb = np.clip(alb * (1 - wgt) + samp * wgt + 0.5, 0, 255).astype(np.uint8)
        d = np.abs(alb.astype(np.int16) - seed.astype(np.int16)).max(-1)
        out[n] = alb
        rep[n] = {"texelsChangedOver24": int((d > 24).sum()), "texels": int(d.size),
                  "seamTexels": int((wgt[..., 0] > 0).sum()), "stagedVerts": int(len(v)),
                  "layoutVerts": int(len(pc["used"])), "uvOnGridFrac": round(float(on_grid.mean()), 4),
                  "fieldDyMaxM": round(float(dy.max()), 4) if dy.size else None}
    tmp.unlink(missing_ok=True)
    return out, {"pieces": rep, "rule": "ring albedo rebaked from the painting with P as sky (edge colour sky-masked "
                                        "by P, no EXTSRC canvas); beyond the frame edge it continues the frame terrain mirrored about "
                                        "that edge, smoothstep-feathered into the synthesis over RING_SEAM_FEATHER_PX; "
                                        "staged geometry unchanged", "seamFeatherPx": RING_SEAM_FEATHER_PX}


SKYLINE_EDGE_PX = 40          # rect columns at each side whose painted skyline is held outward
SKYLINE_MARGIN_DEG = 0.25


EXT_RIDGE_ROW0 = 150           # search for the ridge top from this frame row down


def extension_sky(Pf: np.ndarray, cfg: dict | None = None) -> tuple[np.ndarray, dict]:
    """Dispatch on the town's extSky rule: none (the extension carries no sky on relief) or ridgeDark
    (extension_sky_ridge)."""
    rule = ((cfg or town()).get("extSky") or {}).get("rule")
    if rule == "none":
        return Pf.copy(), {"rule": "none", "extensionSkyPx": 0}
    if rule == "ridgeDark":
        es = (cfg or town())["extSky"]
        return extension_sky_ridge(Pf, int(es["max"]), int(es["run"]))
    raise SystemExit(f"sky continuous: TOWNS[{SC.FACTION!r}].extSky.rule {rule!r} is not none / ridgeDark")


def extension_sky_ridge(Pf: np.ndarray, ridge_max: int = 8, ridge_run: int = 8) -> tuple[np.ndarray, dict]:
    """The painted sky continued across the frame extension (x >= TW). The seed's extension albedo carries a painted
    sky above its ridge silhouette (the old outpaint: red cloud and a pale grey-blue haze band above the ridge); any
    relief still drawing it stands sky colour on geometry, which smears at the sweeps. Per extension column the ridge
    top is the first row from EXT_RIDGE_ROW0 down that stays at or below ridge_max (sRGB max channel) for ridge_run rows (median
    over 9 columns); the rows above it join P for the cut. Fails closed when a column has no ridge."""
    import cv2 as _cv
    can = frame_terrain_canvas(Pf)
    mx = np.nan_to_num(can, nan=255.0).max(-1)
    dark = (mx <= ridge_max).astype(np.uint8)
    run = _cv.erode(dark, np.ones((ridge_run, 1), np.uint8), anchor=(0, 0), borderType=_cv.BORDER_CONSTANT,
                    borderValue=0)
    top = np.full(SC.W, -1)
    for x in range(SC.TW, SC.W):
        hit = np.nonzero(run[EXT_RIDGE_ROW0:SC.H, x])[0]
        if len(hit):
            top[x] = EXT_RIDGE_ROW0 + int(hit[0])
    bad = [x for x in range(SC.TW, SC.W) if top[x] < 0]
    if bad:
        raise SystemExit(f"sky continuous: no ridge silhouette in frame-extension columns {bad[:5]}.. (sky undefined)")
    seg = top[SC.TW:].astype(np.float32)
    seg = np.array([np.median(seg[max(0, i - 4):i + 5]) for i in range(len(seg))])
    out = Pf.copy()
    for i, x in enumerate(range(SC.TW, SC.W)):
        out[:int(seg[i]), x] = True
    return out, {"rule": "ridgeDark", "ridgeTopRows": [int(seg.min()), int(np.median(seg)), int(seg.max())],
                 "extensionSkyPx": int((out & ~Pf).sum()), "ridgeMax": ridge_max, "ridgeRun": ridge_run}


def edge_skylines(sc, Pf: np.ndarray) -> dict:
    """The painted skyline where the frame ends: per side, the median over the outer SKYLINE_EDGE_PX frame columns of
    the lowest sky row (P, continued across the frame extension), as a rest direction (az, el). Beyond the frame the
    ridge is held at that elevation: relief rising above it there is ground the old sky mask invented (the smoke band
    read as terrain depth), never painted ridge."""
    out = {}
    for side, cols in (("left", range(0, SKYLINE_EDGE_PX)), ("right", range(SC.W - SKYLINE_EDGE_PX, SC.W))):
        ys = [int(np.nonzero(Pf[:, c])[0].max()) for c in cols if Pf[:, c].any()]
        if not ys:
            raise SystemExit(f"sky continuous: no painted sky at the frame's {side} edge (skyline undefined)")
        x = 0.5 if side == "left" else SC.W - 0.5
        y = float(np.median(ys)) + 0.5
        az, el = to_az_el(sc.cam, frame_rays(sc.cam, SC.W, SC.H)[int(y), int(x)][None])
        out[side] = {"az": float(az[0]), "el": float(el[0]), "rectRow": round(y, 1)}
    return out


def cut_relief(sc, rows: dict, Pf: np.ndarray) -> tuple[dict, dict]:
    """Every env Mesh_ piece loses the triangles whose rest-projected centroid lies on the painted sky P; the frame-box
    terrain pieces' albedo texels on P (only the kept silhouette triangles still sample them) take the nearest
    non-sky texel. Returns (report, {name: (v, tris)} after the cut)."""
    from scipy.ndimage import distance_transform_edt
    env = S.STAGE / S.ENV_KEY
    names = env_mesh_pieces(rows)
    keep_orig(env, names)
    od = orig_dir()
    import re
    cfg = town()
    if cfg.get("ring", "rebake") == "rebake":
        ring, ring_rep = rebake_outer(sc, Pf)
        missing = sorted(n for n in names if re.match(OUTER_RE, n) and n not in ring)
        if missing:
            raise SystemExit(f"sky continuous: staged ring pieces {missing} have no rebake")
    elif cfg["ring"] == "staged":
        ring, ring_rep = {}, {"mode": "staged", "reason": cfg["ringReason"]}
    else:
        raise SystemExit(f"sky continuous: TOWNS[{SC.FACTION!r}].ring {cfg['ring']!r} is not rebake / staged")
    edge_cut = bool(cfg.get("edgeSkylineCut", True))
    sky_edge = edge_skylines(sc, Pf) if edge_cut else None
    rep_t = json.loads((S.WORK / "stage_report.json").read_text(encoding="utf-8"))
    boxes = {pc["name"]: pc["box"] for pc in rep_t["terrain"]["pieces"]}
    out, after, before = {}, {}, {}
    for n in names:
        v, nrm, uv, subs = S.read_bin(od / f"{n}.bytes")
        tris = np.concatenate(subs)
        before[n] = (v, tris)
        w = v / sc.scale @ sc.C.T + sc.cpos
        px, py, zc = T.project(sc.cam, w)
        cx, cy = px[tris].mean(1), py[tris].mean(1)
        inside = (zc[tris] > 0).all(1) & (cx >= 0) & (cx < SC.W) & (cy >= 0) & (cy < SC.H)
        xi = np.clip(cx, 0, SC.W - 1).astype(np.int64)
        yi = np.clip(cy, 0, SC.H - 1).astype(np.int64)
        drop = inside & Pf[yi, xi]
        # beyond the painted azimuths: relief whose whole triangle stands above the painted skyline held outward
        az, el = to_az_el(sc.cam, w - sc.cam["pos"])
        in_frame = inside
        az_t, el_t = az[tris].mean(1), el[tris].min(1)
        if edge_cut:
            thr = np.where(az_t >= sky_edge["right"]["az"], sky_edge["right"]["el"],
                           np.where(az_t <= sky_edge["left"]["az"], sky_edge["left"]["el"], np.inf))
            above = ~in_frame & (el_t > thr + SKYLINE_MARGIN_DEG)
        else:
            above = np.zeros_like(drop)
        drop_p = drop.copy()
        drop |= above
        import shutil
        if not drop.any():
            shutil.copy2(od / f"{n}.bytes", env / f"{n}.bytes")
            if n in ring:
                Image.fromarray(ring[n]).save(env / f"{n}_albedo.png")
            else:
                shutil.copy2(od / f"{n}_albedo.png", env / f"{n}_albedo.png")
            after[n] = (v, tris)
            continue
        # one submesh per piece is what every lit bin stages; keep the split if there were several
        kept_subs, o = [], 0
        for s_ in subs:
            kept_subs.append(s_[~drop[o:o + len(s_)]])
            o += len(s_)
        S.write_bin(env / f"{n}.bytes", v, nrm, uv, kept_subs)
        alb = ring[n] if n in ring else np.asarray(Image.open(od / f"{n}_albedo.png").convert("RGB"))
        fixed = 0
        if n in boxes:
            x0, y0, x1, y1 = boxes[n]
            th, tw = alb.shape[:2]
            fx = x0 + (np.arange(tw) + 0.5) / tw * (x1 - x0)
            fy = y0 + (np.arange(th) + 0.5) / th * (y1 - y0)
            FX, FY = np.meshgrid(np.clip(fx, 0, SC.W - 1).astype(int), np.clip(fy, 0, SC.H - 1).astype(int))
            on = Pf[FY, FX]
            if on.any() and (~on).any():
                _, (iy, ix) = distance_transform_edt(on, return_indices=True)
                alb = alb[iy, ix]
                fixed = int(on.sum())
        Image.fromarray(alb).save(env / f"{n}_albedo.png")
        after[n] = (v, np.concatenate(kept_subs))
        out[n] = {"trisCut": int(drop.sum()), "trisCutOnP": int(drop_p.sum()),
                  "trisCutAboveEdgeSkyline": int((drop & ~drop_p).sum()), "trisKept": int((~drop).sum()),
                  "albedoTexelsReplaced": fixed}
    return {"pieces": out, "ring": ring_rep, "edgeSkylines": sky_edge,
            "rule": "triangles whose rest-projected centroid lies on P are cut; albedo texels on P "
                                    "(frame-box pieces) take the nearest non-sky texel (no sky-coloured halo); outside the rect, "
                                    "triangles wholly above the painted skyline held out from the rect edge are cut"}, \
        {"before": before, "after": after}


def rest_sky(sc, pano: np.ndarray) -> np.ndarray:
    """The rest frame's painted rect as the panorama shows it (bilinear, mip 0): TH x TW x 3 float."""
    d = frame_rays(sc.cam, SC.W, SC.H)[:SC.TH, :SC.TW]
    az, el = to_az_el(sc.cam, d)
    return pano_lookup(pano, az, el)


def stage() -> dict:
    import shutil
    need_candidate()
    cfg = town()
    sc = S.Scene()
    pdir = S.WORK / "sky_pano"
    pj = json.loads((pdir / "pano.json").read_text(encoding="utf-8"))
    pano_png = pdir / "pano.png"
    if hashlib.sha256(pano_png.read_bytes()).hexdigest() != pj["sha256"]:
        raise SystemExit("sky continuous: pano.png differs from pano.json (rerun pano)")
    pano = np.asarray(Image.open(pano_png).convert("RGB"))
    masks = np.load(pdir / "masks.npz")
    m = rect_masks(cfg)
    if not np.array_equal(m["P"], masks["P"]):
        raise SystemExit("sky continuous: the painted-sky mask changed since pano (rerun pano)")
    Pf = frame_P(m)
    env = S.STAGE / S.ENV_KEY
    rows = json.loads(S.ROWS.read_text(encoding="utf-8"))
    prev = json.loads((S.WORK / "stage_report.json").read_text(encoding="utf-8")).get("skyPano") or {}
    old_sky = sorted({b["name"] for b in rows[S.ENV_KEY]["bins"] if b["name"].startswith("Sky_")} - {PIECE}
                     | set(prev.get("removed", [])))
    # relief: cut the painted sky out of every env mesh
    Pcut, ext_rep = extension_sky(Pf)
    cut, geo = cut_relief(sc, rows, Pcut)
    cut["extensionSky"] = ext_rep
    from scipy.ndimage import binary_erosion
    P_e = binary_erosion(Pf, np.ones((3, 3), bool), iterations=2, border_value=1)
    cov_b = relief_cover(sc, geo["before"])
    cov_a = relief_cover(sc, geo["after"])
    rsb, rsa = int((cov_b & P_e).sum()), int((cov_a & P_e).sum())
    objs = {}
    for nm in object_pieces(rows):
        vv, _, _, ss = S.read_bin(env / f"{nm}.bytes")
        c = int((relief_cover(sc, {nm: (vv, np.concatenate(ss))}) & P_e).sum())
        if c:
            objs[nm] = c
    cut["objectsOnPaintedSkyPx"] = objs
    cut["objectsNote"] = ("deliberate objects in front of the painted sky at rest (not relief; never cut): the rest "
                          "frame differs from the painting there by the object itself")
    # the one sky: drop every old Sky_ row and its files, stage the sphere + texture
    rows[S.ENV_KEY]["bins"] = [b for b in rows[S.ENV_KEY]["bins"] if not b["name"].startswith("Sky_")]
    for stale in list(env.glob("Sky_*")):
        stale.unlink()
    v, n, uv, tris = sphere(sc)
    S.write_bin(env / f"{PIECE}.bytes", v, n, uv, [tris])
    shutil.copy2(pano_png, env / TEX_NAME)
    f, r, u = basis(sc.cam)
    loc = [sc.local_dir(x[None, :])[0] for x in (f, r, u)]
    loc = [x / np.linalg.norm(x) for x in loc]
    mat = {"shader": f"{S.SHADER_DIR}/{SHADER_FILE}",
           "textures": [{"prop": "_MainTex", "path": f"{S.ASSET_ROOT}/{S.ENV_KEY}/{TEX_NAME}", "st": [1.0, 1.0, 0.0, 0.0],
                         "clamp": False, "srgb": True, "maxSize": 8192}],
           "floats": [{"name": "_Az0Deg", "value": AZ0}, {"name": "_ElMinDeg", "value": EL_MIN},
                      {"name": "_ElMaxDeg", "value": EL_MAX}, {"name": "_DriftDegPerSec", "value": drift_deg_per_s()}],
           "colors": [{"name": nm, "rgba": [float(x[0]), float(x[1]), float(x[2]), 0.0]}
                      for nm, x in zip(("_SkyFwd", "_SkyRight", "_SkyUp"), loc)],
           "queue": SKY_QUEUE}
    row = {"name": PIECE, "mesh": f"{S.ASSET_ROOT}/{S.ENV_KEY}/{PIECE}.bytes", "kind": "skyshader",
           "pos": [0.0, 0.0, 0.0], "rot": [0.0, 0.0, 0.0, 1.0], "material": mat}
    cur = {b["name"]: b for b in rows[S.ENV_KEY]["bins"]}
    cur[PIECE] = row
    rows[S.ENV_KEY]["bins"] = [cur[k] for k in sorted(cur)]
    S.ROWS.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    # evidence: the validator re-measures from this
    rs = rest_sky(sc, pano.astype(np.float32))
    src = SC.REFS / SC.FP.BACKGROUND
    q = cv2.resize(pano, (PANO_W // 2, PANO_H // 2), interpolation=cv2.INTER_AREA)
    S.OUT.mkdir(parents=True, exist_ok=True)
    npz = S.OUT / NPZ
    np.savez_compressed(
        npz, schema=np.array(SCHEMA), pano_q=q, K_q=np.packbits(cv2.resize(masks["K"].astype(np.uint8),
                                                                          (PANO_W // 2, PANO_H // 2),
                                                                          interpolation=cv2.INTER_NEAREST) > 0),
        K=np.packbits(masks["K"]), pano_shape=np.array(pano.shape), rest_sky=np.clip(rs + 0.5, 0, 255).astype(np.uint8),
        P=np.packbits(m["P"]), P_shape=np.array(m["P"].shape),
        relief_before=np.packbits(cov_b[:SC.TH, :SC.TW]), relief_after=np.packbits(cov_a[:SC.TH, :SC.TW]),
        cam=np.array([*sc.cam["pos"], *sc.cam["fwd"], *sc.cam["up"], *sc.cam["right"], sc.cam["fov"]]),
        grid=np.array([AZ0, EL_MIN, EL_MAX]),
        painting=np.array(str(src.relative_to(SC.ROOT)).replace("\\", "/")),
        painting_sha256=np.array(hashlib.sha256(src.read_bytes()).hexdigest()))
    sha = hashlib.sha256(npz.read_bytes()).hexdigest()
    rp = S.WORK / "stage_report.json"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    block = {"schema": SCHEMA, "shader": SHADER, "shaderFile": SHADER_FILE, "piece": PIECE, "file": NPZ, "sha256": sha,
             "panorama": {"texture": f"{S.ASSET_ROOT}/{S.ENV_KEY}/{TEX_NAME}", "size": [PANO_W, PANO_H],
                          "azDeg": [AZ0, AZ0 + 360.0], "elDeg": [EL_MIN, EL_MAX], "sha256": pj["sha256"],
                          "pxPerDeg": round(PANO_W / 360.0, 3), "synthesis": pj["synthesis"],
                          "method": "HoMM3 painted sky (2x LANCZOS) on its rest directions; elsewhere 1-D quilted "
                                    "strips of the sun-free painted plate and its mirror, stacked layers above, tone "
                                    "carry + C0 membrane at the painted edge (no SD, no AI, no stretch)"},
             "painting": {"source": str(src.relative_to(SC.ROOT)).replace("\\", "/"),
                          "sha256": hashlib.sha256(src.read_bytes()).hexdigest(), "maskParams": cfg["ext"],
                          "excludedSource": cfg["exclude"]},
             "limits": {"seamRelPaintingMax": SEAM_REL_MAX, "wrapRatioMax": WRAP_RATIO_MAX,
                        "edgeRatioMax": EDGE_RATIO_MAX, "restDeltaEMean": REST_DE_MEAN_MAX,
                        "restDeltaEP95": REST_DE_P95_MAX, "reliefSkyPxMax": RELIEF_SKY_PX_MAX,
                        "measureElDeg": list(MEASURE_EL)},
             "reliefCut": {**cut, "reliefSkyPxBefore": rsb, "reliefSkyPxAfter": rsa},
             "removed": old_sky, "depth": "far plane (shader-pinned), ZWrite On / ZTest LEqual: every mesh in front",
             "parallax": "none (direction-only lookup from the camera's object-space position)",
             "driftDegPerSec": drift_deg_per_s(),
             "proofTier": "generated artifact + offline preview; editor render and Hex SRP runtime unproven"}
    rep["skyPano"] = block
    if not (rep.get("sky") or {}).get("replacedBy"):
        rep["sky"] = {"replacedBy": "skyPano", "removed": old_sky, "previous": rep.get("sky")}
    rp.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    S.write_catalog(sc, carry="previous")   # the props block and every other block it does not own
    print(json.dumps({"removed": old_sky, "reliefCut": block["reliefCut"], "npz": sha[:12]}, indent=1))
    return block


# ------------------------------------------------------------------------------------------------ measure
def measure_evidence(z) -> dict:
    """Every number the contract checks, from sky_continuity.npz alone + the painting (used by the validator too)."""
    pano = z["pano_q"].astype(np.float32)
    h, w = pano.shape[:2]
    Kq = np.unpackbits(z["K_q"])[:h * w].reshape(h, w).astype(bool)
    hp = int(z["pano_shape"][0]) // h
    # measured at half resolution: row helpers scaled
    r0 = int(round((EL_MAX - MEASURE_EL[1]) * h / (EL_MAX - EL_MIN)))
    r1 = int(round((EL_MAX - MEASURE_EL[0]) * h / (EL_MAX - EL_MIN)))
    L = lab_l(pano)
    Lb = L[r0:r1]
    seams = seam_stats(Lb, wrap=True)
    wrap = column_ratio(Lb, [w - 1], wrap=True)
    band = np.zeros_like(Kq)
    band[r0:r1] = True
    edge = edge_step_ratio(L, Kq, band)
    # the painting's own: the same detector over its sky, at the same scale (half the pano's 2x sampling = 1x)
    from scipy.ndimage import binary_erosion
    src = SC.ROOT / str(z["painting"])
    if hashlib.sha256(src.read_bytes()).hexdigest() != str(z["painting_sha256"]):
        raise SystemExit(f"sky continuous: painting {src} differs from the evidence's sha256")
    paint = np.asarray(Image.open(src).convert("RGB").resize((SC.TW, SC.TH), Image.LANCZOS)).astype(np.float32)
    ph, pw = (int(x) for x in z["P_shape"])
    P = np.unpackbits(z["P"])[:ph * pw].reshape(ph, pw).astype(bool)
    cam = z["cam"]
    focal = (SC.H / 2) / math.tan(math.radians(float(cam[12])) / 2)
    sc_ = (w / 360.0) / (focal * math.pi / 180.0)          # painting px -> half-pano px at the rect centre
    sz = (int(round(pw * sc_)), int(round(ph * sc_)))
    paint_s = cv2.resize(paint, sz, interpolation=cv2.INTER_AREA)
    okp = binary_erosion(cv2.resize(P.astype(np.uint8), sz, interpolation=cv2.INTER_NEAREST) > 0,
                         np.ones((3, 3), bool), iterations=1)
    pseams = seam_stats(lab_l(paint_s), okp)
    rel = {k: round(seams[k]["max"] / max(pseams[k]["max"], 1e-3), 3) for k in ("vertical", "horizontal")}
    # a straight cut inside the painting's own sky, measured as an edge: the floor for the painted-edge ratio
    rest = z["rest_sky"].astype(np.float32)
    P_e = binary_erosion(P, np.ones((3, 3), bool), iterations=2, border_value=1)
    de = delta_e(rest, paint, P_e)
    # rest_sky is the panorama's own rest view: re-derived from pano_q (half resolution, so a loose bound)
    camd = {"pos": cam[0:3], "fwd": cam[3:6], "up": cam[6:9], "right": cam[9:12], "fov": float(cam[12])}
    d = frame_rays(camd, SC.W, SC.H)[:ph, :pw]
    az, el = to_az_el(camd, d)
    uq = (np.mod(az - AZ0, 360.0) / 360.0 * w - 0.5).astype(np.float32)
    vq = np.clip((EL_MAX - el) / (EL_MAX - EL_MIN) * h - 0.5, 0, h - 1).astype(np.float32)
    again = cv2.remap(pano, uq, vq, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
    consist = delta_e(again, rest, P_e)
    rb = np.unpackbits(z["relief_before"])[:ph * pw].reshape(ph, pw).astype(bool)
    ra = np.unpackbits(z["relief_after"])[:ph * pw].reshape(ph, pw).astype(bool)
    out = {"seams": seams, "paintingSeams": pseams, "seamRelPainting": rel, "wrapRatio": wrap, "edge": edge,
           "restDeltaE": de, "reliefSkyPxBefore": int((rb & P_e).sum()), "reliefSkyPxAfter": int((ra & P_e).sum()),
           "halfScale": hp, "restFromPano": consist}
    out["ok"] = bool(max(rel.values()) <= SEAM_REL_MAX and wrap <= WRAP_RATIO_MAX and edge["max"] <= EDGE_RATIO_MAX
                     and de["mean"] <= REST_DE_MEAN_MAX and de["p95"] <= REST_DE_P95_MAX
                     and out["reliefSkyPxAfter"] <= RELIEF_SKY_PX_MAX and consist["mean"] <= REST_CONSIST_MAX)
    return out


def synthetic_negative(z) -> dict:
    """A panorama with one strip swapped in from elsewhere (two straight vertical seams) must fail the seam check."""
    pano = z["pano_q"].astype(np.float32).copy()
    h, w = pano.shape[:2]
    r0 = int(round((EL_MAX - MEASURE_EL[1]) * h / (EL_MAX - EL_MIN)))
    r1 = int(round((EL_MAX - MEASURE_EL[0]) * h / (EL_MAX - EL_MIN)))
    c = w // 2 + w // 8
    pano[r0:r1, c:c + w // 24] = np.roll(pano, -w // 5, axis=1)[r0:r1, c:c + w // 24]
    seams = seam_stats(lab_l(pano)[r0:r1], wrap=True)
    return {"verticalMax": seams["vertical"]["max"]}


def old_dome_metrics(cand: str, K: np.ndarray) -> dict | None:
    """The same panorama metrics on a seed's old Sky_Dome texture (linear az/el, SKY_AZ x SKY_EL), resampled onto
    this grid over the dome's own azimuths: the 'before' of the sky surface itself."""
    tex = (SC.DATA / "candidates" / cand / "unity_project" / S.ASSET_ROOT / S.ENV_KEY / "Sky_Dome_albedo.png")
    if not tex.is_file():
        return None
    dome = np.asarray(Image.open(tex).convert("RGB")).astype(np.float32)
    dh, dw = dome.shape[:2]
    az0, az1 = S.SKY_AZ
    el0, el1 = S.SKY_EL
    az, el = grid_az_el()
    c0, c1 = np.searchsorted(az, az0), np.searchsorted(az, az1)
    A, E = np.meshgrid(az[c0:c1], el)
    u = ((A - az0) / (az1 - az0) * (dw - 1)).astype(np.float32)
    v = ((el1 - E) / (el1 - el0) * (dh - 1)).astype(np.float32)
    img = cv2.remap(dome, u, v, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    r0, r1 = el_row(MEASURE_EL[1]), el_row(MEASURE_EL[0])
    L = lab_l(img)
    band = np.zeros((PANO_H, c1 - c0), bool)
    band[r0:r1] = True
    q = lambda a: cv2.resize(a, (a.shape[1] // 2, a.shape[0] // 2), interpolation=cv2.INTER_AREA)
    Lq = q(L)
    rq0, rq1 = r0 // 2, r1 // 2
    return {"azDeg": [az0, az1], "seams": seam_stats(Lq[rq0:rq1]),
            "edge": edge_step_ratio(L, K[:, c0:c1], band),
            "note": "the old dome is one piece of the old sky; the relief-carried sky and the drift are not in it"}


def frame_seams(path: Path, top_frac: float = 0.2) -> dict | None:
    """Straight-line seams in the top of a rendered frame (all sky in the prototype town at every pose)."""
    if not path.is_file():
        return None
    im = np.asarray(Image.open(path).convert("RGB")).astype(np.float32)
    im = cv2.resize(im, (960, int(round(960 * im.shape[0] / im.shape[1]))), interpolation=cv2.INTER_AREA)
    return seam_stats(lab_l(im[:int(im.shape[0] * top_frac)]))


RENDER_POSES = ("full3d_full", "pan_default", "pan_cursor_left", "pan_cursor_right", "pan_sweep_left",
                "pan_sweep_right", "pan_sweep_high")


def measure(before: str) -> dict:
    need_candidate()
    with np.errstate(all="ignore"):
        import warnings
        warnings.simplefilter("ignore", RuntimeWarning)
        z = np.load(S.OUT / NPZ)
        ev = measure_evidence(z)
        neg = synthetic_negative(z)
        K = np.load(S.WORK / "sky_pano" / "masks.npz")["K"]
        old = old_dome_metrics(before, K)
        frames = {}
        for pose in RENDER_POSES:
            b = frame_seams(SC.DATA / "candidates" / before / "renders" / f"{pose}.png")
            a = frame_seams(S.CAND / "renders" / f"{pose}.png")
            frames[pose] = {"before": b and b["vertical"]["max"], "after": a and a["vertical"]["max"],
                            "beforeH": b and b["horizontal"]["max"], "afterH": a and a["horizontal"]["max"]}
    out = {"schema": SCHEMA, "evidence": ev, "syntheticNegative": neg, "beforeDome": old, "frameTopSeams": frames,
           "before": before}
    (S.WORK / "sky_pano" / "measure.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({"ok": ev["ok"], "seamRelPainting": ev["seamRelPainting"], "wrap": ev["wrapRatio"],
                      "edge": ev["edge"]["max"], "restDE": ev["restDeltaE"], "relief": [ev["reliefSkyPxBefore"],
                      ev["reliefSkyPxAfter"]], "neg": neg, "beforeDome": old and {"seams": old["seams"],
                      "edge": old["edge"]["max"]}, "frames": frames}, indent=1))
    return out


def sheet(before: str) -> Path:
    """Before | after at rest and at every proof pose (Unity editor renders of both candidates), plus the panorama."""
    need_candidate()
    rows = []
    for pose in RENDER_POSES:
        b = SC.DATA / "candidates" / before / "renders" / f"{pose}.png"
        a = S.CAND / "renders" / f"{pose}.png"
        if not (b.is_file() and a.is_file()):
            continue
        ib = Image.open(b).convert("RGB").resize((960, 540), Image.LANCZOS)
        ia = Image.open(a).convert("RGB").resize((960, 540), Image.LANCZOS)
        row = Image.new("RGB", (1920, 540))
        row.paste(ib, (0, 0))
        row.paste(ia, (960, 0))
        rows.append(row)
    if not rows:
        raise SystemExit("sky continuous: no before/after renders to sheet (render the candidate first)")
    pano = Image.open(S.WORK / "sky_pano" / "pano.png").convert("RGB").resize((1920, 400), Image.LANCZOS)
    out = Image.new("RGB", (1920, 540 * len(rows) + 400))
    for i, r in enumerate(rows):
        out.paste(r, (0, 540 * i))
    out.paste(pano, (0, 540 * len(rows)))
    p = S.WORK / "sky_pano" / "sheet_before_after.jpg"
    out.save(p, quality=88)
    print(p)
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["pano", "stage", "measure", "sheet"])
    ap.add_argument("--before", default="props_v1")
    a = ap.parse_args()
    if a.cmd == "pano":
        build_pano()
    elif a.cmd == "stage":
        stage()
    elif a.cmd == "measure":
        return 0 if measure(a.before)["evidence"]["ok"] else 1
    elif a.cmd == "sheet":
        sheet(a.before)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
