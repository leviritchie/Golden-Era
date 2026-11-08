#!/usr/bin/env python3
"""Prebaked-lighting lab for one HoMM3 unit: characterise the DEF sprite's lighting, compose
baked-texture variants from UV-space lighting terms, relight them with the game's Hex/Lit model
and compare against the DEF at the sprite camera and at four battle facings.

Inputs (produced by the Blender halves in this folder):
    <out>/terms/*.npy          bake_terms.py   (UV-space AO, sky, suns, position, normal)
    <out>/views/*.npz          render_passes.py (per-view UV, normal, shadowed sun Lambert)
    <out>/source_basecolor.png the unit's Meshy base colour, extracted from the source GLB

Runtime model (source/static, from the installed Hex/Lit Lit-pass bytecode, see
docs/homm3_prebaked_lighting.md):  rgb = albedo * (sunColour * saturate(N.L) * shadow + SH_ambient)
with the arena's serialized MainLight colour/intensity and flat ambient colour, in linear space.
No normal map, no specular. Screen-space AO, fog, tonemapping and post are not modelled.

Proof tier of everything written here: generated artifact (numpy relight of Blender passes).

    python tools/homm3_prebake/prebake_lab.py --unit h3_behemoth --out artifacts/homm3_prebaked_lighting/behemoth
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage, optimize

ROOT = Path(__file__).resolve().parents[2]
TEX = 2048

# Arena lighting, from artifacts/homm3_prebaked_lighting/game_lighting_probe.json (sRGB colours).
SUN_SRGB = (1.0, 0.9569, 0.8392)
SUN_INTENSITY = {"sand": 1.0, "grass": 1.0, "snow": 1.0}
AMBIENT_SRGB = (0.6235, 0.6784, 0.7922)


# ----------------------------------------------------------------------------- colour
def srgb_to_lin(x):
    x = np.asarray(x, dtype=np.float32)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(x):
    x = np.clip(np.asarray(x, dtype=np.float32), 0, None)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def lin_to_lab(rgb):
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]], np.float32)
    xyz = rgb @ m.T / np.array([0.95047, 1.0, 1.08883], np.float32)
    f = np.where(xyz > 0.008856, np.cbrt(np.clip(xyz, 0, None)), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def lab_to_lin(lab):
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    f = np.stack([fx, fy, fz], -1)
    xyz = np.where(f > 6 / 29, f ** 3, (f - 16 / 116) / 7.787) * np.array([0.95047, 1.0, 1.08883], np.float32)
    m = np.array([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]], np.float32)
    return np.clip(xyz @ m.T, 0, None).astype(np.float32)


def luminance(rgb_lin):
    return rgb_lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)


# ----------------------------------------------------------------------------- io
def load_rgba(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32) / 255.0


def load_terms(out: Path) -> dict:
    terms = {}
    for p in sorted((out / "terms").glob("*.npy")):
        terms[p.stem] = np.load(p).astype(np.float32)
    for p in sorted((out / "terms").glob("*.npz")):  # lossless compressed form (unit look runner); wins over .npy
        with np.load(p) as z:
            terms[p.stem] = z["term"].astype(np.float32)
    return terms


def sample_tex(tex: np.ndarray, uv: np.ndarray) -> np.ndarray:
    """Bilinear lookup of a top-down (H,W,C) texture at Blender UVs (v up)."""
    h, w = tex.shape[:2]
    rows = (1.0 - uv[..., 1]) * h - 0.5
    cols = uv[..., 0] * w - 0.5
    return np.stack([ndimage.map_coordinates(tex[..., c], [rows, cols], order=1, mode="nearest")
                     for c in range(tex.shape[2])], -1)


def downsample(rgb: np.ndarray, alpha: np.ndarray, k: int):
    h, w = alpha.shape
    a = alpha.reshape(h // k, k, w // k, k).mean((1, 3))
    c = (rgb * alpha[..., None]).reshape(h // k, k, w // k, k, rgb.shape[-1]).mean((1, 3))
    c = c / np.maximum(a[..., None], 1e-6)
    return c, a


# ----------------------------------------------------------------------------- variants
def base_maps(out: Path, terms: dict) -> dict:
    alb = Image.open(out / "source_basecolor.png").convert("RGB").resize((TEX, TEX), Image.LANCZOS)
    albedo = srgb_to_lin(np.asarray(alb, dtype=np.float32) / 255.0)
    valid = terms["nrm"].sum(-1) > 0.01
    pos = terms["pos"]
    z = pos[..., 2]
    zlo, zhi = np.percentile(z[valid], [1, 99])
    height = np.clip((z - zlo) / (zhi - zlo), 0, 1)
    suns = {k[4:]: np.clip(v[..., 0] * math.pi, 0, 1.2) for k, v in terms.items() if k.startswith("sun_")}
    maps = {"albedo": albedo, "valid": valid, "height": height, "ao": terms["ao"][..., 0],
            "sky": np.clip(terms["sky"][..., 0], 0, 1.05), "suns": suns}
    # Optional terms from ``bake_terms.py --extras`` (v7 ladder only).
    for k in ("ao_short", "thickness", "pointiness"):
        if k in terms:
            maps[k] = terms[k][..., 0]
    if "nrm_geo" in terms:
        maps["nrm_map"] = terms["nrm"] * 2 - 1
        maps["nrm_geo"] = terms["nrm_geo"] * 2 - 1
    return maps


VARIANTS = {
    # name: (label, recipe). Recipes multiply the (graded) albedo in linear space.
    "raw_meshy": "Meshy base colour as the retarget build ships it (no grade, no bake)",
    "v0_graded": "palette grade only, no lighting terms (control: separates grade from bake)",
    "v1_shipped": "approved-oe-v1 bake already in the Stronghold rollout (65 deg front-biased key + flood)",
    "v2_occlusion": "yaw-invariant: AO x hemisphere sky (occlusion + bent-normal term)",
    "v3_occl_height": "yaw-invariant: v2 x height gradient (darker toward the feet)",
    "v4_sagittal_key": "v3 + symmetric key: top + front pair + weaker back pair (left == right by construction)",
    "v6_sprite_match": "v3 + crevice-weighted AO (aoGamma x2) + texture detail boost (luminance unsharp mask), all yaw-invariant",
    "v5_sprite_key": "anti-pattern: one front-left key like the sprite (breaks when the unit turns)",
    # v7 ladder (needs bake_terms.py --extras ao_short,thickness,pointiness,nrm_geo). Each rung adds one
    # yaw-invariant term to the previous one so its gain can be read in isolation.
    "v7a_crevice": "v6 + fine cavity (short-distance AO) + black-point toe in the grade",
    "v7b_colour": "v7a + chroma detail boost + luminance-banded a*b* transfer fitted to the DEF",
    "v7c_gloss": "v7b + baked view-independent wet speckle (yaw-averaged sky sheen on fine bump tips)",
    "v7d_rim": "v7c + thin-extremity darkening (inside-AO thickness) as a baked outline stand-in",
    "v7e_material": "v7c with a per-class grade: albedo k-means classes (fur / skin / bone ordered by L*) each "
                    "graded to the matching DEF k-means cluster, soft-blended (after the Titan's v6m idea)",
}
V7 = ("v7a_crevice", "v7b_colour", "v7c_gloss", "v7d_rim", "v7e_material")


UNGRADED = ("raw_meshy", "v1_shipped")


def shading(name: str, m: dict, p: dict) -> np.ndarray:
    ao = np.power(np.clip(m["ao"], 0, 1), p.get("aoGamma", 1.0))
    sky = m["sky"]
    h = m["height"]
    hterm = 1.0 - p.get("heightDepth", 0.0) * (1.0 - np.power(h, p.get("heightPower", 1.0)))
    s = m["suns"]
    if name in ("raw_meshy", "v0_graded"):
        return np.ones_like(sky)
    if name == "v2_occlusion":
        return ao * (p.get("skyFloor", 0.35) + (1 - p.get("skyFloor", 0.35)) * sky)
    if name == "v3_occl_height":
        return ao * (p.get("skyFloor", 0.35) + (1 - p.get("skyFloor", 0.35)) * sky) * hterm
    if name == "v4_sagittal_key":
        key = (p.get("wTop", 0.4) * s["top"] + p.get("wFront", 0.4) * 0.5 * (s["fl"] + s["fr"])
               + p.get("wBack", 0.2) * 0.5 * (s["bl"] + s["br"]))
        return ao * hterm * (p.get("fill", 0.45) * (0.35 + 0.65 * sky) + p.get("keyGain", 0.8) * key)
    if name == "v6_sprite_match":
        ao6 = np.power(np.clip(m["ao"], 0, 1), p.get("aoGamma", 1.0) * p.get("creviceGammaScale", 2.0))
        return ao6 * (p.get("skyFloor", 0.35) + (1 - p.get("skyFloor", 0.35)) * sky) * hterm
    if name == "v5_sprite_key":
        return ao * (0.45 * (0.35 + 0.65 * sky) + 0.8 * s["fr"])
    raise KeyError(name)


def detail_boost(rgb_lin: np.ndarray, valid: np.ndarray, amount: float, sigma: float) -> np.ndarray:
    """Luminance unsharp mask in texture space (log domain), normalised so empty UV space does not bleed in."""
    lum = np.maximum(luminance(rgb_lin), 1e-4)
    w = valid.astype(np.float32)
    ll = np.log(lum) * w
    blur = ndimage.gaussian_filter(ll, sigma) / np.maximum(ndimage.gaussian_filter(w, sigma), 1e-3)
    gain = np.exp(amount * (np.log(lum) - blur) * w)
    return np.clip(rgb_lin * gain[..., None], 0, 1)


def masked_blur(x: np.ndarray, valid: np.ndarray, sigma: float) -> np.ndarray:
    w = valid.astype(np.float32)
    if x.ndim == 3:
        return np.stack([masked_blur(x[..., c], valid, sigma) for c in range(x.shape[-1])], -1)
    return ndimage.gaussian_filter(x * w, sigma) / np.maximum(ndimage.gaussian_filter(w, sigma), 1e-3)


def chroma_detail(rgb_lin: np.ndarray, valid: np.ndarray, amount: float, sigma: float) -> np.ndarray:
    """Amplify local a*b* deviations (mottling) around a blurred chroma; L* untouched."""
    if amount == 0:
        return rgb_lin
    lab = lin_to_lab(rgb_lin)
    ab = lab[..., 1:]
    base = masked_blur(ab, valid, sigma)
    lab = np.concatenate([lab[..., :1], base + (1 + amount) * (ab - base)], -1)
    return np.where(valid[..., None], np.clip(lab_to_lin(lab), 0, 1), rgb_lin)


def v7_shading(m: dict, p: dict, name: str) -> np.ndarray:
    sh = shading("v6_sprite_match", m, p)
    sh = sh * np.power(np.clip(m["ao_short"], 0, 1), p.get("cavityGamma", 2.0))
    if name == "v7d_rim":
        lo = p.get("rimThickLo", 0.3)
        thin = 1.0 - np.clip((m["thickness"] - lo) / max(1e-3, 1 - lo), 0, 1)
        sh = sh * (1.0 - p.get("rimAmount", 0.5) * np.power(thin, p.get("rimPower", 1.5)))
    return sh


def v7_gloss(m: dict, p: dict) -> np.ndarray:
    """View-independent wet speckle: fine bump tips (normal map agrees with the geometric normal and
    luminance sits above its local mean), weighted toward upward-tilted normals (the yaw-averaged sky
    reflection at a fixed camera elevation), and toward convex mesh regions. Additive, linear."""
    nm, ng = m["nrm_map"], m["nrm_geo"]
    nm = nm / np.maximum(np.linalg.norm(nm, axis=-1, keepdims=True), 1e-4)
    ng = ng / np.maximum(np.linalg.norm(ng, axis=-1, keepdims=True), 1e-4)
    tip = np.clip(np.sum(nm * ng, -1), 0, 1)
    lum = np.maximum(luminance(m["albedo"]), 1e-4)
    hp = np.log(lum) - masked_blur(np.log(lum), m["valid"], p.get("glossSigma", 3.0))
    speck = np.clip(hp / p.get("glossScale", 0.25), 0, 1)
    up = np.clip(0.5 + 0.5 * nm[..., 2], 0, 1) ** p.get("glossUpPower", 1.5)
    conv = np.clip((m["pointiness"] - 0.5) / 0.06 + 0.5, 0, 1)
    g = np.power(tip, 8.0) * speck ** p.get("glossPower", 1.5) * up * (0.5 + 0.5 * conv)
    # Floor: only the true speckle gets sheen; a broad faint layer lifts the crevices (L* is steep near 0).
    fl = p.get("glossFloor", 0.15)
    g = np.clip((g - fl) / max(1e-3, 1 - fl), 0, 1)
    return p.get("glossAmount", 0.15) * g * m["valid"]


def apply_gloss(tex_lin: np.ndarray, m: dict, p: dict) -> np.ndarray:
    """Add the wet speckle. With ``glossNeutral`` > 0 the neighbourhood is darkened by that fraction of the
    local mean sheen, so the sheen adds sparkle (contrast) instead of lifting the whole unit."""
    tint = srgb_to_lin(np.array(p.get("glossTintSrgb", [1.0, 0.93, 0.72]), np.float32))
    g = v7_gloss(m, p)
    out = tex_lin + g[..., None] * tint
    k = p.get("glossNeutral", 0.0)
    if k > 0:
        lum = np.maximum(luminance(tex_lin), 1e-4)
        local = masked_blur(g, m["valid"], p.get("glossNeutralSigma", 4.0))
        out = out * np.clip(1 - k * local / np.maximum(lum, 0.02), 0.5, 1)[..., None]
    return np.where(m["valid"][..., None], np.clip(out, 0, 1), tex_lin).astype(np.float32)


def grade(rgb_lin: np.ndarray, g: np.ndarray) -> np.ndarray:
    """Global colour grade on linear rgb: exposure, luminance gamma, saturation, white balance,
    and (optional sixth value) a black-point toe that crushes only the darkest values."""
    exposure, gamma, sat, wr, wb = g[:5]
    lum = np.maximum(luminance(rgb_lin), 1e-5)[..., None]
    chroma = rgb_lin / lum
    chroma = 1.0 + sat * (chroma - 1.0)
    lum2 = exposure * np.power(lum, gamma)
    if len(g) > 5 and g[5] > 0:
        lum2 = lum2 * lum / (lum + g[5]) * (1 + g[5])
    out = np.clip(chroma, 0, None) * lum2 * np.array([wr, 1.0, wb], np.float32)
    return np.clip(out, 0, 1)


def lab_classes(lab_px: np.ndarray, k: int, seed: int = 7):
    """k-means on L*a*b* (L weighted 1, a*b* weighted 1.5), centroids ordered by L*."""
    from scipy.cluster.vq import kmeans2
    w = np.array([1.0, 1.5, 1.5], np.float32)
    rng = np.random.default_rng(seed)
    sub = lab_px[rng.choice(len(lab_px), size=min(60000, len(lab_px)), replace=False)] * w
    cent, _ = kmeans2(sub.astype(np.float64), k, seed=seed, minit="++", iter=30)
    cent = cent[np.argsort(cent[:, 0])]
    return cent / w


def class_weights(lab: np.ndarray, cent: np.ndarray, soft: float) -> np.ndarray:
    w = np.array([1.0, 1.5, 1.5], np.float32)
    d2 = (((lab[..., None, :] - cent) * w) ** 2).sum(-1)
    e = np.exp(-(d2 - d2.min(-1, keepdims=True)) / (2 * soft ** 2))
    return e / e.sum(-1, keepdims=True)


def fit_band_transfer(tex_lin, valid, samples, views, def_lab, bands=8):
    """Luminance-banded a*b* transfer: per rendered-L band, match the DEF band's a*b* mean and spread.
    Expressed against the texel's own luminance rank so it applies in texture space."""
    lum = luminance(tex_lin)
    vv = lum[valid]
    order = np.sort(vv)
    rank = np.zeros_like(lum)
    rank[valid] = np.searchsorted(order, vv) / max(1, len(vv) - 1)
    ranks, labs = [], []
    for n, (rows, cols, light) in samples.items():
        uv = views[n]["uv"][rows, cols]
        c = sample_tex(tex_lin, uv[None])[0] * light
        labs.append(lin_to_lab(c))
        ranks.append(sample_tex(rank[..., None], uv[None])[0][:, 0])
    lab_r, rk = np.concatenate(labs), np.concatenate(ranks)
    edges_r = np.percentile(lab_r[:, 0], np.linspace(0, 100, bands + 1))
    edges_d = np.percentile(def_lab[:, 0], np.linspace(0, 100, bands + 1))
    centers, d_mu, s_ab = [], [], []
    for i in range(bands):
        sr = (lab_r[:, 0] >= edges_r[i]) & (lab_r[:, 0] <= edges_r[i + 1])
        sd = (def_lab[:, 0] >= edges_d[i]) & (def_lab[:, 0] <= edges_d[i + 1])
        centers.append(float(np.median(rk[sr])))
        d_mu.append(def_lab[sd, 1:].mean(0) - lab_r[sr, 1:].mean(0))
        s_ab.append(np.clip(def_lab[sd, 1:].std(0) / np.maximum(lab_r[sr, 1:].std(0), 1e-3), 0.5, 2.5))
    o = np.argsort(centers)
    centers, d_mu, s_ab = np.array(centers)[o], np.array(d_mu)[o], np.array(s_ab)[o]
    return {"rankCenters": centers.round(3).tolist(), "deltaAB": d_mu.round(2).tolist(),
            "scaleAB": s_ab.round(3).tolist(), "_rank": rank}


def apply_band_transfer(tex_lin, valid, tr, strength=1.0, sigma=24.0):
    rank = tr["_rank"]
    c = np.array(tr["rankCenters"])
    lab = lin_to_lab(tex_lin)
    out = lab.copy()
    local = masked_blur(lab[..., 1:], valid, sigma)
    for i in range(2):
        dm = np.interp(rank, c, np.array(tr["deltaAB"])[:, i])
        sc = np.interp(rank, c, np.array(tr["scaleAB"])[:, i])
        a = lab[..., 1 + i]
        out[..., 1 + i] = a + strength * (dm + (sc - 1) * (a - local[..., i]))
    res = np.clip(lab_to_lin(out), 0, 1)
    return np.where(valid[..., None], res, tex_lin).astype(np.float32)


# ----------------------------------------------------------------------------- relight
def runtime_light(view: dict, cond: str, ss_alpha_mask=None) -> np.ndarray:
    sun = srgb_to_lin(SUN_SRGB) * SUN_INTENSITY[cond]
    amb = srgb_to_lin(AMBIENT_SRGB)
    lam = np.clip(view[f"sun_{cond}"] * math.pi, 0, 1)
    return lam[..., None] * sun + amb


SIM_CONTOUR = None  # (width px at output res, opacity) while simulating the runtime silhouette line


def render_view(tex_lin: np.ndarray, view: dict, mode: str, cond: str, k: int):
    alpha = view["alpha"]
    col = sample_tex(tex_lin, view["uv"])
    if mode == "game":
        col = col * runtime_light(view, cond)
    elif mode == "unlit":
        pass
    col, a = downsample(col, alpha, k)
    if SIM_CONTOUR and mode == "game":
        # Silhouette-only stand-in for Hidden/Hex/ContourLines' depth-edge term: darken pixels within
        # `width` of the coverage edge. The game's line colour/opacity/width are runtime constants.
        w, op = SIM_CONTOUR
        d = ndimage.distance_transform_edt(a > 0.5)
        line = np.clip(w + 0.5 - d, 0, 1) * op
        col = col * (1 - line[..., None]) + line[..., None] * srgb_to_lin(np.array([0.05, 0.04, 0.03], np.float32))
    return col, a


# ----------------------------------------------------------------------------- sprite metrics
def def_mask(rgba: np.ndarray) -> np.ndarray:
    a = rgba[..., 3] > 0.9
    # HoMM3 battle DEFs carry a translucent/black cast shadow; keep only the body.
    lum = rgba[..., :3].max(-1)
    return a & (lum > 0.02)


def edge_distance(mask: np.ndarray) -> np.ndarray:
    return ndimage.distance_transform_edt(mask)


def fit_light(lum: np.ndarray, normals_cam: np.ndarray):
    """Least-squares L = k0 + k.n; direction of k is the dominant light direction (camera frame)."""
    A = np.concatenate([np.ones((len(lum), 1), np.float32), normals_cam], 1)
    coef, *_ = np.linalg.lstsq(A, lum, rcond=None)
    pred = A @ coef
    r2 = 1 - np.sum((lum - pred) ** 2) / max(np.sum((lum - lum.mean()) ** 2), 1e-9)
    k = coef[1:]
    d = k / max(np.linalg.norm(k), 1e-9)
    # camera frame: x = screen right, y = screen up, z = toward the viewer
    az = math.degrees(math.atan2(d[0], d[2]))      # + = light from screen right
    el = math.degrees(math.asin(np.clip(d[1], -1, 1)))
    return {"dir": d.round(3).tolist(), "azimuthFromViewerDeg": round(az, 1),
            "elevationDeg": round(el, 1), "r2": round(float(r2), 3), "strength": round(float(np.linalg.norm(k)), 4)}


def image_stats(rgb_srgb: np.ndarray, mask: np.ndarray, extra: dict | None = None) -> dict:
    if not np.any(mask):
        raise ValueError("image_stats: empty mask (no pixels to measure); the caller must record the empty state")
    lab = lin_to_lab(srgb_to_lin(rgb_srgb))
    L = lab[..., 0]
    Lm = L[mask]
    C = np.hypot(lab[..., 1], lab[..., 2])[mask]
    order = np.argsort(Lm)
    n = max(1, len(Lm) // 7)
    dark, bright = lab[mask][order[:n]], lab[mask][order[-n:]]
    blur = ndimage.gaussian_filter(np.where(mask, L, np.nan_to_num(L)), 1.0)
    local = np.abs(L - blur)[mask]
    dist = edge_distance(mask)
    rim = {}
    for lo, hi in ((0, 1.5), (1.5, 3), (3, 6), (6, 1e9)):
        sel = mask & (dist > lo) & (dist <= hi)
        rim[f"{lo:g}-{hi:g}px"] = round(float(L[sel].mean()), 1) if sel.any() else None
    ys = np.nonzero(mask)[0]
    y0, y1 = ys.min(), ys.max()
    rows = (np.arange(mask.shape[0])[:, None] - y0) / max(1, y1 - y0)
    rows = np.broadcast_to(rows, mask.shape)
    top = L[mask & (rows < 0.33)].mean()
    bot = L[mask & (rows > 0.67)].mean()
    xs = np.nonzero(mask)[1]
    cols = (np.arange(mask.shape[1])[None, :] - xs.min()) / max(1, xs.max() - xs.min())
    cols = np.broadcast_to(cols, mask.shape)
    left = L[mask & (cols < 0.4)].mean()
    right = L[mask & (cols > 0.6)].mean()
    out = {
        "pixels": int(mask.sum()),
        "Lpercentiles_5_25_50_75_95": np.percentile(Lm, [5, 25, 50, 75, 95]).round(1).tolist(),
        "chromaMean": round(float(C.mean()), 1),
        "chromaP90": round(float(np.percentile(C, 90)), 1),
        "chromaP10_50_90": np.percentile(C, [10, 50, 90]).round(1).tolist(),
        "hueSpreadDeg": circular_spread(lab[..., 1][mask][C > 5], lab[..., 2][mask][C > 5]),
        "aP5_50_95": np.percentile(lab[..., 1][mask], [5, 50, 95]).round(1).tolist(),
        "bP5_50_95": np.percentile(lab[..., 2][mask], [5, 50, 95]).round(1).tolist(),
        "hueDeg": round(float(np.degrees(np.arctan2(lab[..., 2][mask].mean(), lab[..., 1][mask].mean()))), 1),
        "shadowLab": dark.mean(0).round(1).tolist(),
        "highlightLab": bright.mean(0).round(1).tolist(),
        "shadowHueDeg": round(float(np.degrees(np.arctan2(dark[:, 2].mean(), dark[:, 1].mean()))), 1),
        "highlightHueDeg": round(float(np.degrees(np.arctan2(bright[:, 2].mean(), bright[:, 1].mean()))), 1),
        "localContrast": round(float(local.mean()), 2),
        "rimProfileL": rim,
        "topMinusBottomL": round(float(top - bot), 1),
        "leftMinusRightL": round(float(left - right), 1),
    }
    if extra:
        out.update(extra)
    return out


def circular_spread(a: np.ndarray, b: np.ndarray) -> float:
    """Circular standard deviation of hue (degrees) over chromatic pixels."""
    if len(a) == 0:
        return 0.0
    r = abs(np.mean(np.exp(1j * np.arctan2(b, a))))
    return round(float(np.degrees(np.sqrt(-2 * np.log(max(r, 1e-6))))), 1)


def hist_distance(a: np.ndarray, b: np.ndarray) -> float:
    """1-D Wasserstein distance between two L* samples (percentile matching)."""
    if np.size(a) == 0 or np.size(b) == 0:
        raise ValueError(f"hist_distance: empty L* sample (sizes {np.size(a)}, {np.size(b)}); "
                         "the caller must record the empty state")
    q = np.linspace(1, 99, 99)
    return float(np.mean(np.abs(np.percentile(a, q) - np.percentile(b, q))))


# ----------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", default="h3_behemoth")
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts/homm3_prebaked_lighting/behemoth")
    ap.add_argument("--shipped", type=Path,
                    default=ROOT / "artifacts/homm3_mocap_v2/stronghold_oe_approved_v1/units/h3_behemoth/baked_lit.png")
    ap.add_argument("--params", type=Path, default=None, help="per-unit knob JSON (defaults inline)")
    ap.add_argument("--variants", default="", help="comma list to evaluate (default: all whose terms exist)")
    ap.add_argument("--tag", default="", help="suffix for metrics/sheets so a run does not overwrite another")
    ap.add_argument("--sim-contour", default="",
                    help="WIDTHpx:OPACITY - also write sheets with a simulated screen-space silhouette line "
                         "(stand-in for Hidden/Hex/ContourLines; its colour/width/opacity are guesses)")
    args = ap.parse_args()
    out = args.out.resolve()
    unit_dir = ROOT / "artifacts/homm3_def_retarget" / args.unit
    frames_meta = json.loads((unit_dir / f"{args.unit}_def_retarget.blend.frames.json").read_text())
    vmeta = json.loads((out / "views/views_meta.json").read_text())
    params = {"aoGamma": 1.4, "skyFloor": 0.35, "heightDepth": 0.35, "heightPower": 0.6,
              "wTop": 0.45, "wFront": 0.35, "wBack": 0.2, "fill": 0.55, "keyGain": 0.75}
    if args.params and args.params.is_file():
        params.update(json.loads(args.params.read_text()))

    terms = load_terms(out)
    m = base_maps(out, terms)
    global VARIANTS
    names = [v for v in args.variants.split(",") if v] or list(VARIANTS)
    names = [v for v in names if v not in V7 or ("ao_short" in m and "nrm_geo" in m)]
    VARIANTS = {k: VARIANTS[k] for k in names}
    sfx = f"_{args.tag}" if args.tag else ""
    views = {n: dict(np.load(out / "views" / f"{n}.npz")) for n in vmeta["views"]}
    sprite_views = [n for n in views if n.startswith("sprite_")]
    battle_views = ["battle_faces_right", "battle_faces_left", "battle_faces_camera", "battle_faces_away"]

    # ---------------- raw texture per variant (linear, before grade)
    raw = {}
    for name in VARIANTS:
        if name == "v1_shipped":
            shp = Image.open(args.shipped).convert("RGB").resize((TEX, TEX), Image.LANCZOS)
            raw[name] = srgb_to_lin(np.asarray(shp, dtype=np.float32) / 255.0)
        else:
            alb = m["albedo"]
            if name in V7 and name != "v7a_crevice":
                alb = chroma_detail(alb, m["valid"], params.get("chromaDetail", 0.6), params.get("chromaSigma", 16.0))
            if name == "v6_sprite_match" or name in V7:
                alb = detail_boost(alb, m["valid"], params.get("detailAmount", 0.8), params.get("detailSigma", 2.0))
            if name in V7:
                raw[name] = alb * v7_shading(m, params, name)[..., None]
            else:
                raw[name] = alb * shading(name, m, params)[..., None]

    # ---------------- DEF targets at the sprite camera
    defs = {}
    for n in sprite_views:
        f = views[n]
        frame = vmeta["views"][n]["frame"]
        src = Path(frames_meta["sources"][frame - 1])
        rgba = load_rgba(src)
        defs[n] = {"src": str(src), "rgba": rgba, "mask": def_mask(rgba)}

    # camera-space normals (downsampled) for light-direction fits
    def cam_normals(n):
        v = views[n]
        vm = vmeta["views"][n]
        r = np.array(vm["camRight"], np.float32)
        fwd = np.array(vm["camForward"], np.float32)
        up = np.cross(r, fwd)
        nrm = v["normal"]
        nc = np.stack([nrm @ r, nrm @ up, nrm @ -fwd], -1)
        k = vm["supersample"]
        nd, a = downsample(nc, v["alpha"], k)
        nd = nd / np.maximum(np.linalg.norm(nd, axis=-1, keepdims=True), 1e-6)
        return nd, a

    # ---------------- grade fit per variant: game-lit (sand) render at sprite cam vs DEF L*/a*/b*
    samples = {}
    for n in sprite_views:
        v = views[n]
        k = vmeta["views"][n]["supersample"]
        # subsample full-res pixels for the optimiser
        sel = np.nonzero(v["alpha"] > 0.99)
        idx = np.random.default_rng(3).choice(len(sel[0]), size=min(40000, len(sel[0])), replace=False)
        rows, cols = sel[0][idx], sel[1][idx]
        samples[n] = (rows, cols, runtime_light(v, "sand")[rows, cols])
    def_lab = np.concatenate([lin_to_lab(srgb_to_lin(defs[n]["rgba"][..., :3]))[defs[n]["mask"]] for n in sprite_views])
    q = np.linspace(2, 98, 25)
    tgt = [np.percentile(def_lab[:, i], q) for i in range(3)]

    grades = {}
    for name in VARIANTS:
        cols_lin = []
        for n in sprite_views:
            rows, cc, light = samples[n]
            uv = views[n]["uv"][rows, cc]
            cols_lin.append((sample_tex(raw[name], uv[None])[0], light))
        if name in UNGRADED:
            grades[name] = np.array([1, 1, 1, 1, 1], np.float32)  # evaluated as-is
            continue
        if name == "v7e_material":
            continue  # graded per class below
        if name in ("v7c_gloss", "v7d_rim") and "v7b_colour" in grades:
            # Later rungs reuse the colour rung's grade so each rung's own change is what differs.
            grades[name] = grades["v7b_colour"]
            continue

        def cost(g):
            # Bounded so the optimiser cannot trade saturation for a white-balance cast.
            if not (0 < g[0] < 12 and 0.5 <= g[1] <= 1.8 and 0.5 <= g[2] <= 2.0
                    and 0.7 <= g[3] <= 1.5 and 0.6 <= g[4] <= 1.3):
                return 1e6
            if len(g) > 5 and not (0 <= g[5] <= params.get("toeMax", 0.08)):
                return 1e6
            labs = [lin_to_lab(grade(c, g) * l) for c, l in cols_lin]
            lab = np.concatenate(labs)
            return sum(np.mean(np.abs(np.percentile(lab[:, i], q) - tgt[i])) * w for i, w in ((0, 1.0), (1, 0.7), (2, 0.7)))

        starts = ([2.0, 1.0, 1.3, 1.0, 1.0], [4.0, 0.9, 1.6, 1.1, 0.8])
        if name in V7:
            starts = tuple(x + [0.02] for x in starts)
        best = min((optimize.minimize(cost, x0, method="Nelder-Mead",
                                      options={"maxiter": 900 if name in V7 else 600, "xatol": 1e-3, "fatol": 1e-3})
                    for x0 in starts), key=lambda r: r.fun)
        grades[name] = best.x.astype(np.float32)
        print(f"grade {name}: {np.round(best.x, 3).tolist()} cost {best.fun:.2f}", flush=True)

    class_info = {}
    if "v7e_material" in VARIANTS:
        k = int(params.get("classCount", 3))
        soft = params.get("classSoftness", 8.0)
        alb_lab = lin_to_lab(m["albedo"])
        tex_cent = lab_classes(alb_lab[m["valid"]], k)
        def_cent = lab_classes(def_lab, k)
        wtex = class_weights(alb_lab, tex_cent, soft)
        wdef = class_weights(def_lab, def_cent, soft).argmax(-1)
        cls_grades = []
        base_g = grades.get("v7b_colour", np.array([1.0, 1.0, 1.0, 1.0, 1.0, 0.02], np.float32))
        for c in range(k):
            dsel = def_lab[wdef == c]
            tgt_c = [np.percentile(dsel[:, i], q) for i in range(3)]
            cols_c = []
            for n in sprite_views:
                rows, cc, light = samples[n]
                uv = views[n]["uv"][rows, cc]
                wc = sample_tex(wtex[..., c:c + 1], uv[None])[0][:, 0]
                sel = wc > 0.6
                cols_c.append((sample_tex(raw["v7e_material"], uv[sel][None])[0], light[sel]))

            def cost_c(g):
                if not (0 < g[0] < 12 and 0.5 <= g[1] <= 1.8 and 0.5 <= g[2] <= 2.0
                        and 0.7 <= g[3] <= 1.5 and 0.6 <= g[4] <= 1.3 and 0 <= g[5] <= params.get("toeMax", 0.08)):
                    return 1e6
                lab_c = np.concatenate([lin_to_lab(grade(cl, g) * li) for cl, li in cols_c])
                return sum(np.mean(np.abs(np.percentile(lab_c[:, i], q) - tgt_c[i])) * w
                           for i, w in ((0, 1.0), (1, 0.7), (2, 0.7)))

            r = optimize.minimize(cost_c, np.array(base_g, np.float64), method="Nelder-Mead",
                                  options={"maxiter": 900, "xatol": 1e-3, "fatol": 1e-3})
            cls_grades.append(r.x.astype(np.float32))
            print(f"class {c} centroid tex {np.round(tex_cent[c], 1).tolist()} def {np.round(def_cent[c], 1).tolist()} "
                  f"texels {float((wtex[..., c][m['valid']] > 0.5).mean()):.2f} grade {np.round(r.x, 3).tolist()} cost {r.fun:.2f}",
                  flush=True)
        grades["v7e_material"] = np.array(base_g, np.float32)
        class_info = {"texCentroids": np.round(tex_cent, 2).tolist(), "defCentroids": np.round(def_cent, 2).tolist(),
                      "grades": [np.round(g, 4).tolist() for g in cls_grades], "softness": soft}
        raw["_v7e_graded"] = np.where(m["valid"][..., None], sum(wtex[..., c:c + 1] * grade(raw["v7e_material"], g)
                                                               for c, g in enumerate(cls_grades)), m["albedo"])
    tex = {name: (raw[name] if name in UNGRADED else raw["_v7e_graded"] if name == "v7e_material"
                  else grade(raw[name], grades[name])) for name in VARIANTS}
    transfers = {}
    for name in VARIANTS:
        if name in V7 and name != "v7a_crevice":
            tr = fit_band_transfer(tex[name], m["valid"], samples, views, def_lab, params.get("bandCount", 8))
            if name in ("v7c_gloss", "v7d_rim") and "v7b_colour" in transfers:  # v7e fits its own
                tr = transfers["v7b_colour"]
                tr = dict(tr, _rank=fit_band_transfer(tex[name], m["valid"], samples, views, def_lab,
                                                     params.get("bandCount", 8))["_rank"])
            tex[name] = apply_band_transfer(tex[name], m["valid"], tr, params.get("bandStrength", 1.0),
                                            params.get("bandLocalSigma", 24.0))
            transfers[name] = {k: v for k, v in tr.items() if not k.startswith("_")}
            if name in ("v7c_gloss", "v7d_rim", "v7e_material"):
                # Wet speckle is a highlight layer on the finished colour, so the grade cannot fit it away.
                tex[name] = apply_gloss(tex[name], m, params)
            print(f"band transfer {name}: dAB {transfers[name]['deltaAB']}", flush=True)
    # ungraded raw for reference column
    (out / "textures").mkdir(exist_ok=True)
    for name, t in tex.items():
        if name in UNGRADED:
            continue
        Image.fromarray((lin_to_srgb(t) * 255 + 0.5).astype(np.uint8)).save(out / "textures" / f"{name}_basecolor.png")

    # ---------------- metrics
    metrics = {"proof": "generated artifact: numpy relight of Blender Cycles passes with the Hex/Lit model",
               "params": params, "grades": {k: np.round(v, 4).tolist() for k, v in grades.items()},
               "bandTransfers": transfers, "classGrade": class_info,
               "variants": VARIANTS, "def": {}, "sprite": {}, "battle": {}}
    for n in sprite_views:
        d = defs[n]
        nd, a = cam_normals(n)
        both = d["mask"] & (a > 0.9)
        def_lum = luminance(srgb_to_lin(d["rgba"][..., :3]))
        metrics["def"][n] = image_stats(d["rgba"][..., :3], d["mask"], {
            "source": d["src"],
            "lightFit": fit_light(def_lum[both], nd[both])})
        metrics["sprite"][n] = {}
        for name in VARIANTS:
            for mode in ("game", "unlit"):
                col, al = render_view(tex[name], views[n], mode, "sand", vmeta["views"][n]["supersample"])
                srgb = lin_to_srgb(col)
                mask = al > 0.9
                lum = luminance(col)
                st = image_stats(srgb, mask, {"lightFit": fit_light(lum[both & mask], nd[both & mask])})
                st["LhistDistanceToDEF"] = round(hist_distance(lin_to_lab(col)[..., 0][mask],
                                                               lin_to_lab(srgb_to_lin(d["rgba"][..., :3]))[..., 0][d["mask"]]), 2)
                metrics["sprite"][n][f"{name}/{mode}"] = st

    for cond in ("sand", "grass"):
        metrics["battle"][cond] = {}
        for name in VARIANTS:
            per = {}
            for bv in battle_views:
                col, al = render_view(tex[name], views[bv], "game", cond, vmeta["views"][bv]["supersample"])
                mask = al > 0.9
                L = lin_to_lab(col)[..., 0][mask]
                per[bv] = {"meanL": round(float(L.mean()), 1), "p10": round(float(np.percentile(L, 10)), 1),
                           "p90": round(float(np.percentile(L, 90)), 1)}
            means = [per[b]["meanL"] for b in battle_views]
            per["leftRightDeltaL"] = round(per["battle_faces_right"]["meanL"] - per["battle_faces_left"]["meanL"], 1)
            per["frontBackDeltaL"] = round(per["battle_faces_camera"]["meanL"] - per["battle_faces_away"]["meanL"], 1)
            per["facingSpreadL"] = round(max(means) - min(means), 1)
            metrics["battle"][cond][name] = per

    # ---------------- sheets
    sheets = out / "sheets"
    sheets.mkdir(exist_ok=True)
    make_sprite_sheet(sheets / f"sprite_cam_game_sand{sfx}.png", sprite_views, defs, tex, views, vmeta, "game", "sand")
    make_sprite_sheet(sheets / f"sprite_cam_unlit{sfx}.png", sprite_views, defs, tex, views, vmeta, "unlit", "sand")
    for cond in ("sand", "grass"):
        make_yaw_sheet(sheets / f"battle_yaw_{cond}{sfx}.png", battle_views, defs[sprite_views[0]], tex, views, vmeta, cond)
    make_terms_sheet(sheets / f"uv_terms{sfx}.png", m, raw, tex)
    if args.sim_contour:
        global SIM_CONTOUR
        w, op = (float(x) for x in args.sim_contour.split(":"))
        SIM_CONTOUR = (w, op)
        make_sprite_sheet(sheets / f"sprite_cam_game_sand{sfx}_simcontour.png", sprite_views, defs, tex, views, vmeta, "game", "sand")
        make_yaw_sheet(sheets / f"battle_yaw_sand{sfx}_simcontour.png", battle_views, defs[sprite_views[0]], tex, views, vmeta, "sand")
        metrics["simContour"] = {"widthPx": w, "opacity": op, "note": "guess; not the game's ContourLines constants"}
        for n in sprite_views:
            for name in VARIANTS:
                col, al = render_view(tex[name], views[n], "game", "sand", vmeta["views"][n]["supersample"])
                st = image_stats(lin_to_srgb(col), al > 0.9)
                metrics["sprite"][n][f"{name}/game+simContour"] = {
                    k: st[k] for k in ("Lpercentiles_5_25_50_75_95", "rimProfileL", "localContrast")}
        SIM_CONTOUR = None
    (out / f"metrics{sfx}.json").write_text(json.dumps(metrics, indent=1), encoding="utf-8")
    print("wrote", out / f"metrics{sfx}.json")
    return 0


# ----------------------------------------------------------------------------- sheets
def crop_box(masks, pad=6):
    ys, xs = np.nonzero(np.any(np.stack(masks), 0))
    return max(0, xs.min() - pad), max(0, ys.min() - pad), xs.max() + pad + 1, ys.max() + pad + 1


def to_img(srgb, alpha, bg=(46, 46, 46)):
    rgb = srgb * alpha[..., None] + np.array(bg, np.float32)[None, None] / 255 * (1 - alpha[..., None])
    return Image.fromarray((np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8))


def label(img, text):
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, img.width, 13], fill=(0, 0, 0))
    d.text((3, 1), text, fill=(255, 255, 255))
    return img


def make_sprite_sheet(path, sprite_views, defs, tex, views, vmeta, mode, cond, scale=3):
    rows, all_cells = [], []
    for n in sprite_views:
        d = defs[n]
        cells = [(d["rgba"][..., :3], d["rgba"][..., 3] * d["mask"], "DEF " + Path(d["src"]).stem)]
        for name in tex:
            col, al = render_view(tex[name], views[n], mode, cond, vmeta["views"][n]["supersample"])
            cells.append((lin_to_srgb(col), al, name))
        all_cells.append(cells)
    x0, y0, x1, y1 = crop_box([c[1] > 0.5 for cells in all_cells for c in cells])
    for cells in all_cells:
        imgs = []
        for rgb, a, text in cells:
            im = to_img(rgb[y0:y1, x0:x1], a[y0:y1, x0:x1]).resize(((x1 - x0) * scale, (y1 - y0) * scale), Image.NEAREST)
            imgs.append(label(im, text))
        rows.append(imgs)
    w = sum(i.width for i in rows[0])
    h = sum(r[0].height for r in rows) + 16
    sheet = Image.new("RGB", (w, h), (20, 20, 20))
    ImageDraw.Draw(sheet).text((4, 2), f"sprite camera | {'game-like Hex/Lit relight, ' + cond + ' arena sun' if mode == 'game' else 'unlit texture only'} | x{scale} nearest", fill=(255, 255, 0))
    y = 16
    for r in rows:
        x = 0
        for im in r:
            sheet.paste(im, (x, y))
            x += im.width
        y += r[0].height
    sheet.save(path)


def make_yaw_sheet(path, battle_views, def0, tex, views, vmeta, cond, scale=2):
    rows = []
    for name in tex:
        cells = []
        for bv in battle_views:
            col, al = render_view(tex[name], views[bv], "game", cond, vmeta["views"][bv]["supersample"])
            cells.append((lin_to_srgb(col), al, f"{name} | {bv[7:]}"))
        rows.append(cells)
    x0, y0, x1, y1 = crop_box([c[1] > 0.5 for r in rows for c in r])
    cw, ch = (x1 - x0) * scale, (y1 - y0) * scale
    d = def0
    dx0, dy0, dx1, dy1 = crop_box([d["mask"]])
    dimg = to_img(d["rgba"][dy0:dy1, dx0:dx1, :3], (d["rgba"][..., 3] * d["mask"])[dy0:dy1, dx0:dx1])
    dimg = dimg.resize((int(dimg.width * ch / dimg.height), ch), Image.NEAREST)
    sheet = Image.new("RGB", (dimg.width + cw * 4, ch * len(rows) + 16), (20, 20, 20))
    ImageDraw.Draw(sheet).text((4, 2), f"battle facings, ortho 40 deg down | game-like Hex/Lit relight, {cond} arena sun (camera-relative) | DEF at left for reference", fill=(255, 255, 0))
    for ri, r in enumerate(rows):
        y = 16 + ri * ch
        sheet.paste(label(dimg.copy(), "DEF"), (0, y))
        for ci, (rgb, a, text) in enumerate(r):
            im = to_img(rgb[y0:y1, x0:x1], a[y0:y1, x0:x1]).resize((cw, ch), Image.LANCZOS)
            sheet.paste(label(im, text), (dimg.width + ci * cw, y))
    sheet.save(path)


def make_terms_sheet(path, m, raw, tex, size=384):
    def gray(x):
        return Image.fromarray((np.clip(x, 0, 1) * 255).astype(np.uint8)).convert("RGB").resize((size, size), Image.LANCZOS)

    def col(x):
        return Image.fromarray((lin_to_srgb(np.clip(x, 0, 1)) * 255).astype(np.uint8)).resize((size, size), Image.LANCZOS)

    cells = [(gray(m["ao"]), "AO"), (gray(m["sky"]), "sky hemisphere"), (gray(m["height"]), "height"),
             (gray(m["suns"]["fl"]), "sun front-left"), (gray(m["suns"]["fr"]), "sun front-right"),
             (col(m["albedo"]), "Meshy albedo")]
    cells += [(col(tex[n]), n) for n in tex if n != "raw_meshy"]
    cols = 6
    rows = math.ceil(len(cells) / cols)
    sheet = Image.new("RGB", (cols * size, rows * size), (20, 20, 20))
    for i, (im, t) in enumerate(cells):
        sheet.paste(label(im, t), ((i % cols) * size, (i // cols) * size))
    sheet.save(path)


if __name__ == "__main__":
    raise SystemExit(main())
