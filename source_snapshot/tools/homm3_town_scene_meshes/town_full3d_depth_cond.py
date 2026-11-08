#!/usr/bin/env python3
"""Full-3D towns: opt-in conditioning of the background depth that drives the one-sheet terrain (experiment rx_cond).

The terrain is one continuous screen-space depth sheet (stronghold_full3d_terrain / stronghold_full3d_ground). The
2026-09-30 image-to-image maps (depth/img2img_bg.npy) are sharper than Depth Anything: real steps at house, ridge,
cliff and tree edges become curtains the sheet stretches at the sweep poses, and the map has its own defects (texture
ridges, non-monotone patches, a 1-5 px ECC residual that puts its edges beside the painted ones). This module keeps
the one sheet and conditions the depth instead. It is used ONLY when a candidate's pin
(<candidate>/work/background_depth.json) carries a "conditioning" object; no key = the terrain is byte-identical.

    {"source": "img2img_bg", "npySha256": ..., "conditioning": {
        "disparity": [op, ...],      # on the raw map (larger = nearer), before the floor calibration
        "inverseDepth": [op, ...],   # on the calibrated rect 1/zc (painting m^-1), sky excluded
        "frame": [op, ...]}}         # on the whole frame's 1/zs (rect + raymarched extension), before the seam smooth

Ops (each a dict with "op"):
  guided   {"r", "eps"}            He et al. guided filter, guide = the painting (Lab, per channel mean of the box
                                   statistics), on the disparity: edge-aware smoothing that keeps painted silhouettes
  jbf      {"r", "sigmaS", "sigmaR"}  joint bilateral (painting Lab range kernel)
  snap     {"r", "minStep"}        guided edge alignment: in a (2r+1)^2 window around a depth step (max - min disparity
                                   >= minStep, relative to the map's p1..p99 range) each pixel takes the near or the far
                                   side's value, whichever side's mean painting colour it is closer to, so the step
                                   lands on the painted silhouette
  hybrid   {"sigma", "edgeStep"}   old (da_large) low frequencies + new high frequencies, the new map's own steps kept
                                   only where they are occlusion edges (local new-map step >= edgeStep x range); else the
                                   new map's detail over the old map's base. Old/new matched by a robust affine fit.
  oldlow   {"sigma"}               (inverse depth) the old map's calibrated low frequencies x the new map's detail
  monotone {"ratioMax"}            (inverse depth) grounded-surface prior per column, see monotone()
  envelope {"slope", "axis"}       step-limiting compression (inverse depth or frame): the Lipschitz max envelope
                                   inv'(p) = max_q inv(q) - g |p - q|_1, g = slope x the floor plane's own vertical
                                   inverse-depth gradient per px. The near side (the occluder) is never moved; the far
                                   side next to it is pulled forward into a ramp, so no step is steeper than g and the
                                   curtain a pan can open across it is bounded. Ordinary floor (gradient < g) is untouched.
Proof tier: generated artifact (offline). Docs: docs/homm3_town_depth_conditioning.md.
"""
from __future__ import annotations

import json

import cv2
import numpy as np


def _box(a: np.ndarray, r: int) -> np.ndarray:
    return cv2.blur(a.astype(np.float32), (2 * r + 1, 2 * r + 1), borderType=cv2.BORDER_REFLECT)


def _lab(paint: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(np.ascontiguousarray(paint.astype(np.float32) / 255.0), cv2.COLOR_RGB2LAB)


def guided(p: np.ndarray, guide: np.ndarray, r: int, eps: float) -> np.ndarray:
    """Grey guided filter per guide channel, averaged (guide: H x W x C float, p: H x W)."""
    outs = []
    for c in range(guide.shape[2]):
        I = guide[..., c]
        mI, mp = _box(I, r), _box(p, r)
        cov = _box(I * p, r) - mI * mp
        var = _box(I * I, r) - mI * mI
        a = cov / (var + eps)
        b = mp - a * mI
        outs.append(_box(a, r) * I + _box(b, r))
    return np.mean(outs, 0)


def jbf(p: np.ndarray, lab: np.ndarray, r: int, sigma_s: float, sigma_r: float) -> np.ndarray:
    num = np.zeros_like(p, np.float64)
    den = np.zeros_like(p, np.float64)
    pp = np.pad(p, r, mode="reflect")
    lp = np.pad(lab, ((r, r), (r, r), (0, 0)), mode="reflect")
    H, W = p.shape
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            ws = np.exp(-(dx * dx + dy * dy) / (2 * sigma_s ** 2))
            sl = lp[r + dy:r + dy + H, r + dx:r + dx + W]
            dc = ((sl - lab) ** 2).sum(-1)
            w = ws * np.exp(-dc / (2 * sigma_r ** 2))
            num += w * pp[r + dy:r + dy + H, r + dx:r + dx + W]
            den += w
    return (num / den).astype(np.float32)


def snap(p: np.ndarray, lab: np.ndarray, r: int, min_step: float) -> np.ndarray:
    k = np.ones((2 * r + 1, 2 * r + 1), np.uint8)
    hi = cv2.dilate(p.astype(np.float32), k)
    lo = cv2.erode(p.astype(np.float32), k)
    rng = float(np.percentile(p, 99) - np.percentile(p, 1)) + 1e-9
    band = (hi - lo) >= min_step * rng
    mid = 0.5 * (hi + lo)
    near = (p >= mid).astype(np.float32)
    far = 1.0 - near
    cn, cf = _box(near, r) + 1e-6, _box(far, r) + 1e-6
    d_near = np.zeros(p.shape, np.float32)
    d_far = np.zeros(p.shape, np.float32)
    for c in range(3):
        mn = _box(lab[..., c] * near, r) / cn
        mf = _box(lab[..., c] * far, r) / cf
        d_near += (lab[..., c] - mn) ** 2
        d_far += (lab[..., c] - mf) ** 2
    # the side's own representative depth: its mean inside the window
    zn = _box(p * near, r) / cn
    zf = _box(p * far, r) / cf
    take_near = d_near < d_far
    out = np.where(band, np.where(take_near, np.maximum(p, zn), np.minimum(p, zf)), p)
    return out.astype(np.float32)


def hybrid(new: np.ndarray, old: np.ndarray, sigma: float, edge_step: float, r: int = 4) -> np.ndarray:
    # match old to new's scale (robust affine on the whole rect)
    a, b = np.polyfit(old.ravel()[::7], new.ravel()[::7], 1)
    oldm = a * old + b
    lo_old = cv2.GaussianBlur(oldm.astype(np.float32), (0, 0), sigma)
    lo_new = cv2.GaussianBlur(new.astype(np.float32), (0, 0), sigma)
    k = np.ones((2 * r + 1, 2 * r + 1), np.uint8)
    step = cv2.dilate(new.astype(np.float32), k) - cv2.erode(new.astype(np.float32), k)
    rng = float(np.percentile(new, 99) - np.percentile(new, 1)) + 1e-9
    occl = cv2.GaussianBlur((step >= edge_step * rng).astype(np.float32), (0, 0), 2.0)
    occl = np.clip(occl * 2, 0, 1)
    tex = lo_old + (new - lo_new)
    return (occl * new + (1 - occl) * tex).astype(np.float32)


def envelope(inv: np.ndarray, g: float, axis: str = "xy") -> np.ndarray:
    """Max envelope with L1 slope g per px; NaN stays NaN and contributes nothing."""
    ok = np.isfinite(inv)
    a = np.where(ok, inv, -np.inf).astype(np.float64)

    def sweep(a, ax):
        n = a.shape[ax]
        x = np.arange(n, dtype=np.float64)
        sh = [1, 1]
        sh[ax] = n
        x = x.reshape(sh)
        f = np.maximum.accumulate(a + g * x, axis=ax) - g * x
        rb = np.flip(a, ax)
        bk = np.flip(np.maximum.accumulate(rb + g * x, axis=ax) - g * x, ax)
        return np.maximum(f, bk)
    for _ in range(2):
        if "x" in axis:
            a = sweep(a, 1)
        if "y" in axis:
            a = sweep(a, 0)
    return np.where(ok, np.maximum(a, inv), np.nan)


def monotone(inv: np.ndarray, ratio_max: float) -> np.ndarray:
    """Grounded-surface prior: seen from above the ground, nothing is nearer than every surface below it in its own
    column unless it overhangs. inv'(y) = the running min of inv over the rows below, where inv exceeds that min by at
    most ratio_max (a floating relief pop, e.g. a painted rock slab the map lifts 20-30% toward the camera); a larger
    violation is a real overhang (a canopy over far ground) and is kept."""
    a = np.where(np.isfinite(inv), inv, np.inf)
    m = np.flip(np.minimum.accumulate(np.flip(a, 0), axis=0), 0)
    fix = np.isfinite(inv) & (a > m) & (a <= m * ratio_max)
    return np.where(fix, m, inv)


def apply_disparity(d: np.ndarray, ops: list, paint: np.ndarray, old: np.ndarray | None) -> np.ndarray:
    lab = _lab(paint)
    for o in ops:
        k = o["op"]
        if k == "guided":
            g = lab / np.array([100.0, 128.0, 128.0], np.float32)
            d = guided(d, g, int(o["r"]), float(o["eps"]))
        elif k == "jbf":
            d = jbf(d, lab, int(o["r"]), float(o["sigmaS"]), float(o["sigmaR"]))
        elif k == "snap":
            d = snap(d, lab, int(o["r"]), float(o["minStep"]))
        elif k == "hybrid":
            if old is None:
                raise SystemExit("depth_cond hybrid: needs the old map (da_large.npy)")
            d = hybrid(d, old, float(o["sigma"]), float(o["edgeStep"]))
        else:
            raise SystemExit(f"depth_cond: disparity op {k!r} unknown")
    return d.astype(np.float32)


def oldlow(inv: np.ndarray, old: np.ndarray, sigma: float) -> np.ndarray:
    """Hybrid in calibrated inverse depth: the old map's low frequencies, the new map's detail.
    inv' = inv * G(old) / G(inv), G a NaN-aware Gaussian of sigma px. Restores the old map's coarse layering (which
    surface is in front of which at the scale of sigma: Tower's mountains behind its houses) and keeps the new map's
    sharp steps and relief inside that scale."""
    ok = np.isfinite(inv) & np.isfinite(old)
    def g(a):
        num = cv2.GaussianBlur(np.where(ok, a, 0).astype(np.float32), (0, 0), sigma)
        den = cv2.GaussianBlur(ok.astype(np.float32), (0, 0), sigma)
        return num / np.maximum(den, 1e-6)
    r = g(old) / np.maximum(g(inv), 1e-12)
    return np.where(ok, inv * r, inv)


def needs_old(ops: list) -> bool:
    return any(o["op"] == "oldlow" for o in ops or [])


def apply_inverse(inv: np.ndarray, ops: list, floor_grad: float, old_inv: np.ndarray | None = None) -> np.ndarray:
    for o in ops:
        if o["op"] == "oldlow":
            if old_inv is None:
                raise SystemExit("depth_cond oldlow: needs the old map's calibrated inverse depth")
            inv = oldlow(inv, old_inv, float(o["sigma"]))
            continue
        if o["op"] == "envelope":
            inv = envelope(inv, float(o["slope"]) * floor_grad, o.get("axis", "xy"))
        elif o["op"] == "monotone":
            inv = monotone(inv, float(o["ratioMax"]))
        else:
            raise SystemExit(f"depth_cond: inverse-depth op {o['op']!r} unknown")
    return inv


def spec_digest(spec: dict) -> str:
    return json.dumps(spec, sort_keys=True)
