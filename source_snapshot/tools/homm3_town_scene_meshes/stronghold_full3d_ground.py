"""Stronghold full-3D: the registered frame terrain (depth -> mesh) and its albedo.

  * depth    inside the HoMM3 rect the calibrated DA Large depth (stronghold_full3d_terrain); outside it (x >= 1440 or
             y >= 673 of the 1080p frame) every pixel is ray-marched against the world field (the painted surface,
             the floor plane nearer than it, the canyon walls continued past the painted edges). Across the two seams
             the inverse depth is smoothed over SEAM_PX (along each pixel's own ray: registration unchanged).
  * mesh     the Conflux screen-space terrain grid (conflux_full3d_env.terrain_mesh, read-only reuse), split into
             Mesh_Terrain (2 bake texels per 1080p px) and Mesh_TerrainNear_0/1 (the bottom band nearer than the
             rect's floor, 4 texels per px).
  * albedo   inside the rect: the HoMM3 painting at full sharpness divided by the Hex/Lit irradiance of the surface
             normal (the lit result reproduces the painting at the rest pose). Outside it: synthesised from the
             vanilla Olden Era desert textures (sand / dirt on the floor, the desert rock set on walls) sampled in
             world space; the painting gives low-frequency colour only - the floor colour and a canyon strata palette
             (the de-lit painted walls' median colour per world height). A world-space band blends into the rect.
Proof tier: generated artifact (offline previews). Editor renders are the review evidence; nothing is in-game proof.
"""
from __future__ import annotations

import math

import cv2
import numpy as np
from PIL import Image

import stronghold_full3d_common as SC
import stronghold_full3d_terrain as T
import stronghold_full3d_vanilla as V

W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
SEAM_PX = 70.0
MAIN_SCALE, NEAR_SCALE = 2, 4
NEAR_Y = 700                   # frame row: below it the near pieces (all synthesised ground)
SEAM_BAND_M = 6.0              # world-space blend of the synthesis into the rect
EDGE_TONE_M = 10.0             # the synthesis takes the rect edge colour, e-folding over this distance
EDGE_BLUR_PX = 60.0            # outside the rect the edge colour is blurred this wide (no streaks out of the seam)
FLOOR_TEX, ROCK_TEX, ROCK_ROT = SC.FP.FLOOR_TEX, SC.FP.ROCK_TEX, SC.FP.ROCK_ROT   # (vanilla texture, m per tile)
DETAIL_CONTRAST, ROCK_CONTRAST = SC.FP.DETAIL_CONTRAST, SC.FP.ROCK_CONTRAST   # calibrated per painting
FLOOR_STONES = SC.FP.FLOOR_STONES   # pebbly floor layers
SHADE_GAIN = (3.0, 0.8)        # baked fine-relief shading (wall, floor): the painting carries its relief shading
SHADE_EPS_M = (0.75, 6.0)      # fine / broad normal scales for the baked shading ratio
STRATA_COLS = SC.FP.STRATA_COLS   # rect columns the strata palettes are read from
FLOOR_K = 5
PATCH_M = 14.0                 # world size of the floor colour patches
WALL_REL_M = (4.0, 10.0)       # height above the floor where the ground turns to wall rock
CAV_R_M = (2.0, 6.0)           # cavity radii (m): gullies between the spurs read dark, ridges light, as painted
CAV_K = 0.20                   # albedo change per metre of cavity depth (wall texels only)
CAV_CLIP = (0.45, 1.12)


class Ctx:
    def __init__(self):
        self.cam = T.camera()
        self.cpos = self.cam["pos"]


def seam_smooth(zs: np.ndarray) -> np.ndarray:
    """Smooth the inverse depth across x = TW (rows < TH) and y = TH over SEAM_PX, weight falling off the seam."""
    inv = np.where(np.isfinite(zs), 1.0 / zs, np.nan)
    ok = np.isfinite(inv)
    fill = np.where(ok, inv, 0.0).astype(np.float32)
    k = ok.astype(np.float32)
    s = SEAM_PX / 2.5
    bx = cv2.GaussianBlur(fill, (0, 0), s, sigmaY=1.0) / np.maximum(cv2.GaussianBlur(k, (0, 0), s, sigmaY=1.0), 1e-6)
    by = cv2.GaussianBlur(fill, (0, 0), 1.0, sigmaY=s) / np.maximum(cv2.GaussianBlur(k, (0, 0), 1.0, sigmaY=s), 1e-6)
    ys, xs = np.mgrid[0:H, 0:W]
    wx = np.exp(-((xs - TW) / (SEAM_PX * 0.6)) ** 2) * (ys < TH + SEAM_PX)
    wy = np.exp(-((ys - TH) / (SEAM_PX * 0.6)) ** 2) * (xs < TW + SEAM_PX)
    out = inv * (1 - wx) + bx * wx
    out = out * (1 - wy) + by * wy
    return np.where(ok, 1.0 / np.maximum(out, 1e-6), np.nan)


def frame_depth(ctx: Ctx, rd: dict, field) -> dict:
    cache = SC.DATA / "work" / "frame_depth.npz"
    ys, xs = np.mgrid[0:H, 0:W]
    ext = (xs >= TW) | (ys >= TH)
    key = np.array([T.DEPTH_SCALE, T.FAR_CAP_M, field.h.shape[0], field.h.shape[1], float(field.h.sum())])
    if cache.is_file():
        with np.load(cache) as d:
            if d["key"].shape == key.shape and np.allclose(d["key"], key):
                zext = d["zext"]
            else:
                zext = None
    else:
        zext = None
    if zext is None:
        zext = np.full(int(ext.sum()), np.nan)
        px, py = xs[ext] + 0.5, ys[ext] + 0.5
        for i in range(0, len(px), 200000):
            zext[i:i + 200000] = T.raymarch(ctx.cam, field, px[i:i + 200000], py[i:i + 200000])
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, zext=zext, key=key)
    zs = np.full((H, W), np.nan)
    zs[:TH, :TW] = rd["zc"]
    zs[ext] = zext
    sky = np.zeros((H, W), bool)
    sky[:TH, :TW] = rd["sky"]
    sky |= ~np.isfinite(zs)
    if SC.HOUSES:
        import town_full3d_houses as HS
        zs = HS.carve_depth(np.where(sky, np.nan, zs))
    cond = (rd["calib"].get("backgroundDepth") or {}).get("conditioning") or {}
    if cond.get("frame"):
        # opt-in (rx_cond experiment, town_full3d_depth_cond): step limiting over the whole frame before the seam smooth
        import town_full3d_depth_cond as DC
        zs = np.where(sky, np.nan, zs)
        zs = 1.0 / DC.apply_inverse(1.0 / zs, cond["frame"], rd["floor"].k)
    zs = seam_smooth(np.where(sky, np.nan, zs))
    return {"zs": zs, "sky": sky, "ext": ext, "escaped": int(np.isnan(zext).sum())}


# ------------------------------------------------------------------------------------------------ albedo
def detail_layer(name: str) -> np.ndarray:
    """Vanilla texture as linear colour with mean 1 per channel over a large blur (a detail ratio)."""
    t = T_CACHE.get(name)
    if t is None:
        img = V.tex(name).astype(np.float32) / 255
        lin = SC_srgb_to_lin(img)
        h, w = lin.shape[:2]
        low = cv2.GaussianBlur(np.tile(lin, (3, 3, 1)), (0, 0), h / 6)[h:2 * h, w:2 * w]
        t = (lin / np.maximum(low, 1e-3)).astype(np.float32)
        t = np.pad(t, ((2, 2), (2, 2), (0, 0)), mode="wrap")
        T_CACHE[name] = t
    return t


T_CACHE: dict = {}


def SC_srgb_to_lin(c):
    c = np.asarray(c, np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(c):
    c = np.clip(np.asarray(c, np.float32), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def sample_wrap(tex: np.ndarray, u, v) -> np.ndarray:
    h, w = tex.shape[0] - 4, tex.shape[1] - 4      # the layer carries a 2-texel wrap pad
    x = (np.mod(u, 1.0) * w + 2).astype(np.float32)
    y = (np.mod(v, 1.0) * h + 2).astype(np.float32)
    shp = x.shape
    out = cv2.remap(tex, x.reshape(-1, 1) if x.ndim == 1 else x, y.reshape(-1, 1) if y.ndim == 1 else y,
                    cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return out.reshape(shp + (tex.shape[2],))


def tiled(name, scale, a, b, rot=0.0, off=(0.0, 0.0)):
    c, s = math.cos(rot), math.sin(rot)
    u = (a * c - b * s) / scale + off[0]
    v = (a * s + b * c) / scale + off[1]
    return sample_wrap(detail_layer(name), u, v)


def synth_detail(P, nrm, rel, rng_seed=5) -> np.ndarray:
    """Mean-1 detail ratio (linear RGB) from the vanilla textures in world space: floor textures on XZ, rock on the
    camera-facing vertical projection; mixed by height above the floor and slope; each at two rotated scales."""
    fl, rk, wall = synth_detail_parts(P, nrm, rel, rng_seed)
    det = fl * (1 - wall[..., None]) + rk * wall[..., None]
    return det, wall


def synth_detail_parts(P, nrm, rel, rng_seed=5):
    """synth_detail's floor ratio, rock ratio and wall weight, unmixed (GROUNDSRC replaces the floor part only)."""
    X, Y, Z = P[..., 0], P[..., 1], P[..., 2]
    fl = np.zeros(X.shape + (3,), np.float32)
    wsum = np.zeros(X.shape, np.float32)
    for i, (nm, sc) in enumerate(FLOOR_TEX):
        m = T.fbm(X, Z, 300 + i, 25.0, 3)
        w = np.clip((m - 0.35) * 3.0, 0, 1) ** 2 + 0.05
        d = 0.65 * tiled(nm, sc, X, Z, 0.3 * i, (0.13 * i, 0.71 * i)) + 0.35 * tiled(nm, sc * 2.37, X, Z, 1.1 + i, (0.4, 0.2))
        fl += d * w[..., None]
        wsum += w
    fl /= wsum[..., None]
    rk = np.zeros_like(fl)
    rs = np.zeros_like(wsum)
    # triplanar: the wall rock projects along the dominant normal axis (no stretching on any facing)
    tw = np.abs(nrm) ** 4
    tw /= tw.sum(-1, keepdims=True) + 1e-9
    for i, (nm, sc) in enumerate(ROCK_TEX):
        m = T.fbm(X, Z, 400 + i, 40.0, 3)
        w = np.clip((m - 0.3) * 2.5, 0, 1) ** 2 + 0.05
        ro = ROCK_ROT.get(nm, 0.0)
        d = (tiled(nm, sc, Z, -Y, ro, (0.3 * i, 0.1)) * tw[..., 0:1]
             + tiled(nm, sc, X, Z, 0.4, (0.1 * i, 0.6)) * tw[..., 1:2]
             + tiled(nm, sc, X, -Y, ro, (0.7 * i, 0.3)) * tw[..., 2:3])
        rk += d * w[..., None]
        rs += w
    rk /= rs[..., None]
    # pebbles: the painting's floor is stony, the vanilla sand alone reads as smooth dune
    st = np.ones_like(fl)
    for i, (nm, sc) in enumerate(FLOOR_STONES):
        m = T.fbm(X, Z, 500 + i, 12.0, 3)
        w = np.clip((m - 0.4) * 3.0, 0, 1)[..., None]
        st *= 1 + w * (tiled(nm, sc, X, Z, 0.7 + i, (0.21 * i, 0.5)) - 1)
    fl = fl * st
    slope = np.degrees(np.arccos(np.clip(nrm[..., 1], -1, 1)))
    wall = np.maximum(T.smoothstep(WALL_REL_M[0], WALL_REL_M[1], rel), T.smoothstep(30.0, 50.0, slope))
    fl = np.power(np.maximum(fl, 1e-3), DETAIL_CONTRAST)
    rk = np.power(np.maximum(rk, 1e-3), ROCK_CONTRAST)
    return fl, rk, wall


def baked_shade(field, X, Z, rig, sun, wall) -> np.ndarray:
    """exp(gain * log(L(fine normal) / L(broad normal))): the relief shading the soft runtime normals cannot show,
    baked into the albedo the way the painting carries it (gain calibrated against the painting's own contrast)."""
    import conflux_full3d_env as E
    nf = field.normal(X, Z, eps=SHADE_EPS_M[0]).astype(np.float32)
    nb = field.normal(X, Z, eps=SHADE_EPS_M[1]).astype(np.float32)
    lf = E.light(nf, rig, sun).mean(-1)
    lb = E.light(nb, rig, sun).mean(-1)
    g = SHADE_GAIN[1] + (SHADE_GAIN[0] - SHADE_GAIN[1]) * wall
    return np.exp(np.clip(g * np.log(np.maximum(lf, 1e-3) / np.maximum(lb, 1e-3)), -1.2, 0.6)).astype(np.float32)


def cavity(field, X, Z, wall) -> np.ndarray:
    """Albedo factor from the field's own concavity (mean of ring samples minus the height, two radii): the painted
    badlands carry their gullies as dark shadowed lines, which a softened Hex/Lit normal alone does not reproduce."""
    h0 = field.height(X, Z)
    cav = np.zeros_like(h0)
    for r in CAV_R_M:
        ring = sum(field.height(X + r * math.cos(a), Z + r * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 6, endpoint=False)) / 6
        cav += (ring - h0) / len(CAV_R_M)
    f = np.clip(1 - CAV_K * cav, *CAV_CLIP)
    return (1 + (f - 1) * wall).astype(np.float32)


CONTRAST_REGIONS = SC.FP.CONTRAST_REGIONS   # (painting box, extension box)


def contrast_stats(img_lin: np.ndarray, box) -> list:
    """Std of log(lum / blurred lum) at sigma 2 / 6 / 20 px inside a frame box (1080p px)."""
    x0, y0, x1, y1 = box
    lum = img_lin.mean(-1)
    out = []
    for sg in (2, 6, 20):
        r = np.log(np.maximum(lum, 1e-4)) - np.log(np.maximum(cv2.GaussianBlur(lum, (0, 0), sg), 1e-4))
        out.append(round(float(r[y0:y1, x0:x1].std()), 3))
    return out


def strata_palette(ctx: Ctx, albedo_rect: np.ndarray, P_rect: np.ndarray, rel_rect: np.ndarray, sky: np.ndarray):
    """Low-frequency colour the painting lends the synthesis:
      * a strata palette per wall side: the de-lit painted wall's mean colour per 0.5 m of world height, taken only
        from the columns next to that edge (STRATA_COLS) so the bands stay local and keep their contrast;
      * floor patch colours: k-means of the de-lit painted floor (the red dirt, tan sand, dark scrub...)."""
    out = {}
    xs = np.arange(albedo_rect.shape[1])[None, :]
    for side, (c0, c1) in STRATA_COLS.items():
        wall = (rel_rect > 8.0) & ~sky & (xs >= c0) & (xs < c1)
        Y = P_rect[..., 1][wall]
        cols = albedo_rect[wall]
        y0, y1 = float(np.percentile(Y, 1)), float(np.percentile(Y, 99.5))
        bins = np.arange(math.floor(y0), math.ceil(y1) + 0.5, 0.5)
        idx = np.clip(np.digitize(Y, bins) - 1, 0, len(bins) - 1)
        pal = np.full((len(bins), 3), np.nan, np.float32)
        for i in range(len(bins)):
            sel = idx == i
            if sel.sum() > 20:
                pal[i] = cols[sel].mean(0)
        g = np.isfinite(pal[:, 0])
        for c in range(3):
            pal[:, c] = np.interp(bins, bins[g], pal[g, c])
        out[side] = {"bins": bins, "pal": pal}
    flo = (rel_rect < 1.5) & ~sky
    fc = albedo_rect[flo].reshape(-1, 3)
    rng = np.random.default_rng(3)
    samp = fc[rng.choice(len(fc), min(len(fc), 60000), replace=False)]
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 1e-4)
    _, lab, cen = cv2.kmeans(samp.astype(np.float32), FLOOR_K, None, crit, 4, cv2.KMEANS_PP_CENTERS)
    share = np.bincount(lab.ravel(), minlength=FLOOR_K) / len(lab)
    order = np.argsort(-share)
    out["floorK"], out["floorShare"] = cen[order], share[order]
    out["floor"] = np.median(fc, 0)
    return out


def palette_at(pal: dict, Y, theta_sign):
    def one(p):
        return np.stack([np.interp(Y, p["bins"], p["pal"][:, c]) for c in range(3)], -1)
    return np.where(theta_sign[..., None] < 0, one(pal["left"]), one(pal["right"]))


def floor_patches(pal: dict, X, Z) -> np.ndarray:
    """The painted floor's k-means colours laid out as world-noise patches in their painted shares."""
    cen, share = pal["floorK"], pal["floorShare"]
    out = np.zeros(X.shape + (3,), np.float32)
    wsum = np.zeros(X.shape, np.float32)
    for k in range(len(cen)):
        m = T.fbm(X, Z, 600 + k, PATCH_M * (1.0 if k == 0 else 0.6), 4)
        w = np.exp(8.0 * (m - 0.5)) * share[k]
        out += cen[k] * w[..., None]
        wsum += w
    return out / wsum[..., None]


# ------------------------------------------------------------------------------------------------ GROUNDSRC
def _svd2(a, b, c, d):
    """Singular values (max, min) of the 2x2 matrices [[a, b], [c, d]] and the angle of the major left singular
    vector (elementwise arrays)."""
    s = a * a + b * b + c * c + d * d
    det = a * d - b * c
    r = np.sqrt(np.maximum(s * s - 4 * det * det, 0))
    smax = np.sqrt(np.maximum((s + r) / 2, 0))
    smin = np.sqrt(np.maximum((s - r) / 2, 0))
    p, q, t = a * a + b * b, a * c + b * d, c * c + d * d        # M M^T = [[p, q], [q, t]]
    ang = 0.5 * np.arctan2(2 * q, p - t)
    return smax, smin, ang


def footprint(P, px, py) -> dict:
    """Ground footprint of a texel grid: 'tex' = largest world (XZ) extent of one texel; 'major' / 'minor' / 'ang' =
    the singular values and major-axis angle (in XZ) of d(X, Z)/d(rest-frame px), the ellipse one rest-frame pixel
    covers on the ground (finite differences over the grid's own neighbours; non-finite px -> a huge footprint)."""
    X, Z = P[..., 0].astype(np.float64), P[..., 2].astype(np.float64)
    px, py = np.asarray(px, np.float64), np.asarray(py, np.float64)
    g = lambda a, ax: np.gradient(a, axis=ax) if a.shape[ax] > 1 else np.zeros_like(a)
    Xu, Xv, Zu, Zv = g(X, 1), g(X, 0), g(Z, 1), g(Z, 0)
    pu, pv, qu, qv = g(px, 1), g(px, 0), g(py, 1), g(py, 0)
    ft, _, _ = _svd2(Xu, Xv, Zu, Zv)
    det = pu * qv - pv * qu
    ok = np.isfinite(det) & (np.abs(det) > 1e-9)
    det = np.where(ok, det, 1.0)
    # J S^-1 with S^-1 = [[qv, -pv], [-qu, pu]] / det
    a, b = (Xu * qv - Xv * qu) / det, (-Xu * pv + Xv * pu) / det
    c, d = (Zu * qv - Zv * qu) / det, (-Zu * pv + Zv * pu) / det
    mj, mn, ang = _svd2(a, b, c, d)
    bad = ~ok | ~np.isfinite(mj)
    f32 = lambda v: np.minimum(np.where(bad, 1e3, v), 1e3).astype(np.float32)
    return {"tex": np.minimum(np.nan_to_num(ft, nan=1e3), 1e3).astype(np.float32), "major": f32(mj),
            "minor": f32(mn), "ang": np.where(bad, 0.0, ang).astype(np.float32)}


class GroundSrc:
    """TOWN_FULL3D_GROUNDSRC: an authored floor material (schema town_full3d_groundsrc.v1).

      * floor    a world-XZ albedo map (sRGB of linear albedo, res m texels) sampled from its own pyramid with an
                 anisotropic filter shaped like the painting's native pixel there (nativePx rest-frame px): the
                 pyramid level follows the ellipse's minor axis and up to MAX_TAPS taps average along its major axis.
                 At the painting's edge the extension is as sharp across and as soft along the view as the painting.
      * details  mean-1 log-ratio tiles in world XZ (sx, sz m per texel) that add the grain the map cannot hold:
                 each fades in as the bake texel gets smaller than its fadeFootprintM [on, full] and with world
                 distance from the painted rect (rampM; a detail's own rampM overrides it, 0 = none), scaled by
                 gain. Nearer ground shows finer grain.
      * floorNear  optional finer map (same encoding) over the near ground, which the floor map magnifies; it is
                 used inside its bounds and feathers to the floor map over featherM.
    Walls are not part of it (they keep the synthesis)."""
    MAX_TAPS = 8

    def __init__(self, d, man):
        self.maps = [self._load_map(d, man["floor"])]
        if man.get("floorNear") is not None:        # finer map over the near ground; fades to floor over featherM
            fn = man["floorNear"]
            self.maps.append(self._load_map(d, fn))
            self.near_feather = float(fn["featherM"])
        self.native_px, self.ramp_m = float(man["nativePx"]), float(man["rampM"])
        self.shade_ramp_m = float(man["floorShadeRampM"])
        self.details = []
        for e in man["details"]:
            raw = cv2.imread(str(d / e["file"]), cv2.IMREAD_UNCHANGED)
            if raw is None or raw.dtype != np.uint16 or raw.ndim != 3:
                raise SystemExit(f"TOWN_FULL3D_GROUNDSRC {d}: {e['file']} is not a 16-bit RGB log-ratio tile")
            logr = (raw[..., ::-1].astype(np.float32) - 32768) / 8192
            self.details.append((np.pad(logr, ((2, 2), (2, 2), (0, 0)), mode="wrap"), float(e["sx"]), float(e["sz"]),
                                 float(e["gain"]), tuple(float(v) for v in e["fadeFootprintM"]),
                                 float(e.get("rampM", self.ramp_m))))

    @staticmethod
    def _remap(img, mx, mz):
        n, k = len(mx), 4096                       # remap maps must stay under SHRT_MAX rows: fold into k columns
        pad = (-n) % k
        mx = np.pad(mx.astype(np.float32), (0, pad)).reshape(-1, k)
        mz = np.pad(mz.astype(np.float32), (0, pad)).reshape(-1, k)
        return cv2.remap(img, mx, mz, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).reshape(-1, 3)[:n]

    @staticmethod
    def _load_map(d, f) -> dict:
        img = np.asarray(Image.open(d / f["file"]).convert("RGB")).astype(np.float32) / 255
        levels = [SC_srgb_to_lin(img).astype(np.float32)]
        while min(levels[-1].shape[:2]) > 16:
            levels.append(cv2.pyrDown(levels[-1]))
        h, w = img.shape[:2]
        x0, z0, res = float(f["x0"]), float(f["z0"]), float(f["res"])
        return {"levels": levels, "x0": x0, "z0": z0, "res": res, "x1": x0 + w * res, "z1": z0 + h * res}

    def _trilinear(self, m, X, Z, lvl):
        """Pyramid lookup in map m at world points (1-D arrays) and fractional levels."""
        cx = (X - m["x0"]) / m["res"] - 0.5
        cz = (Z - m["z0"]) / m["res"] - 0.5
        l0 = np.floor(lvl).astype(np.int32)
        t = (lvl - l0).astype(np.float32)
        out = np.zeros((len(X), 3), np.float32)
        for li in range(len(m["levels"])):
            w = np.where(l0 == li, 1 - t, 0) + np.where(l0 + 1 == li, t, 0)
            sel = w > 0
            if sel.any():
                s = 2.0 ** li
                out[sel] += self._remap(m["levels"][li], (cx[sel] + 0.5) / s - 0.5,
                                        (cz[sel] + 0.5) / s - 0.5) * w[sel][:, None]
        return out

    def _aniso(self, m, X, Z, major, minor, ang, ntap):
        lvl = np.clip(np.log2(np.maximum(minor, 1e-6) / m["res"]), 0, len(m["levels"]) - 1)
        ux, uz = np.cos(ang), np.sin(ang)
        out = np.zeros((len(X), 3), np.float32)
        for nt in np.unique(ntap):
            sel = np.where(ntap == nt)[0]
            acc = np.zeros((len(sel), 3), np.float32)
            for k in range(nt):
                o = major[sel] * ((k + 0.5) / nt - 0.5)
                acc += self._trilinear(m, X[sel] + ux[sel] * o, Z[sel] + uz[sel] * o, lvl[sel])
            out[sel] = acc / nt
        return out

    def floor(self, P, fp: dict, d_rect_m) -> np.ndarray:
        """Linear floor albedo at world points P (..., 3); fp = footprint(...) of the same grid."""
        shp = P.shape[:-1]
        X, Z = P[..., 0].reshape(-1).astype(np.float64), P[..., 2].reshape(-1).astype(np.float64)
        ftex = fp["tex"].reshape(-1)
        major = np.maximum(fp["major"].reshape(-1) * self.native_px, ftex)
        minor = np.maximum(fp["minor"].reshape(-1) * self.native_px, np.minimum(ftex, major))
        ang = fp["ang"].reshape(-1)
        ntap = np.clip(np.ceil(major / np.maximum(minor, 1e-6)), 1, self.MAX_TAPS).astype(np.int32)
        minor = np.maximum(minor, major / self.MAX_TAPS)     # taps capped: the minor axis widens to cover the ellipse
        out = self._aniso(self.maps[0], X, Z, major, minor, ang, ntap)
        if len(self.maps) > 1:                        # the near map inside its bounds, feathered at its edges
            m, fe = self.maps[1], self.near_feather
            inner = np.minimum.reduce([X - m["x0"], m["x1"] - X, Z - m["z0"], m["z1"] - Z])
            wn = T.smoothstep(0.0, fe, inner).astype(np.float32)
            sel = np.where(wn > 0)[0]
            if len(sel):
                nv = self._aniso(m, X[sel], Z[sel], major[sel], minor[sel], ang[sel], ntap[sel])
                out[sel] = out[sel] * (1 - wn[sel, None]) + nv * wn[sel, None]
        out = out.reshape(shp + (3,))
        logsum = np.zeros_like(out)
        for tex, sx, sz, gain, (on, full), ramp_m in self.details:
            ramp = T.smoothstep(0.0, ramp_m, d_rect_m).astype(np.float32) if ramp_m > 0 else 1.0
            w = T.smoothstep(on, full, fp["tex"]).astype(np.float32) * ramp * gain
            if not (w > 0).any():
                continue
            h, wd = tex.shape[0] - 4, tex.shape[1] - 4
            logsum += sample_wrap(tex, P[..., 0] / (sx * wd), P[..., 2] / (sz * h)) * w[..., None]
        return (out * np.exp(logsum)).astype(np.float32)


# ------------------------------------------------------------------------------------------------ bake
def upsample(img: np.ndarray, box, scale: int) -> np.ndarray:
    """Frame-space array sampled at bake texel centres of the window box = (x0, y0, x1, y1) (frame px)."""
    x0, y0, x1, y1 = box
    tw, th = (x1 - x0) * scale, (y1 - y0) * scale
    fx = (x0 + (np.arange(tw) + 0.5) / scale - 0.5).astype(np.float32)
    fy = (y0 + (np.arange(th) + 0.5) / scale - 0.5).astype(np.float32)
    mx, my = np.meshgrid(fx, fy)
    return cv2.remap(np.ascontiguousarray(img.astype(np.float32)), mx, my, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REPLICATE)


class Baker:
    """Everything the per-piece bake needs at frame resolution."""

    def __init__(self, ctx: Ctx, fd: dict, grid: dict, floor, rig: dict, sun, field):
        import conflux_full3d_env as E
        self.field = field
        self.ctx, self.fd, self.floor, self.rig, self.sun = ctx, fd, floor, rig, np.asarray(sun, np.float32)
        self.E = E
        zf = E.filled_depth(np.where(fd["sky"], np.nan, fd["zs"]))
        self.zf = zf.astype(np.float32)
        self.nf = E.frame_normals(grid).astype(np.float32)
        ys, xs = np.mgrid[0:H, 0:W]
        self.P = (ctx.cpos + T.rays(ctx.cam, xs + 0.5, ys + 0.5) * zf[..., None]).astype(np.float32)
        orig = SC.background_rgb()
        self.orig = orig
        paint = np.asarray(orig.resize((TW, TH), Image.LANCZOS)).astype(np.float32) / 255
        lin = SC_srgb_to_lin(paint)
        L = E.light(self.nf[:TH, :TW], rig, self.sun)
        self.alb_rect = np.clip(lin / np.maximum(L, 0.02), 0, 1)
        rel = floor.rel(self.P[:TH, :TW].astype(np.float64))
        self.pal = strata_palette(ctx, self.alb_rect, self.P[:TH, :TW], rel, fd["sky"][:TH, :TW])
        # the rect's low-frequency albedo, pushed out across the seams (the edge tone of the synthesis)
        low = cv2.GaussianBlur(np.where(fd["sky"][:TH, :TW, None], 0, self.alb_rect), (0, 0), 10)
        wt = cv2.GaussianBlur((~fd["sky"][:TH, :TW]).astype(np.float32), (0, 0), 10)
        low = low / np.maximum(wt[..., None], 1e-3)
        full = np.zeros((H, W, 3), np.float32)
        known = np.zeros((H, W), bool)
        full[:TH, :TW] = low
        known[:TH, :TW] = wt > 0.2
        from scipy.ndimage import distance_transform_edt
        dpx, (iy, ix) = distance_transform_edt(~known, return_indices=True)
        near = full[iy, ix]
        # the nearest-edge colour would streak straight out of the seam: outside the rect it is blurred wide
        wide = cv2.GaussianBlur(near, (0, 0), EDGE_BLUR_PX)
        self.edge_col = np.where(known[..., None], near, wide).astype(np.float32)
        # world distance from the rect: pixel distance x metres per pixel at the depth
        mpp = 2 * zf * math.tan(math.radians(ctx.cam["fov"]) / 2) / H
        self.d_rect_m = (dpx * mpp).astype(np.float32)
        ysr, xsr = np.mgrid[0:H, 0:W]
        din = np.minimum(TW - xsr, TH - ysr).astype(np.float32)      # px inside the rect (to its right/bottom edge)
        self.d_in_m = np.where((xsr < TW) & (ysr < TH), din * mpp, 0).astype(np.float32)
        # TOWN_FULL3D_EXTSRC: an outpainted canvas replaces the synthesis outside the rect, de-lit like the rect
        self.ext = None
        cv = SC.extension_canvas()
        if cv is not None:
            img, cx0, k = cv
            lin = SC_srgb_to_lin(img)
            self.ext = {"lin": lin, "x0": cx0, "k": k, "frameAlb": None}
            if k == 1:
                L = E.light(self.nf, rig, self.sun)
                self.ext["frameAlb"] = np.clip(lin[:, -cx0:-cx0 + W] / np.maximum(L, 0.02), 0, 1).astype(np.float32)
        # TOWN_FULL3D_GROUNDSRC: an authored floor material replaces the floor synthesis outside the rect
        gsrc = SC.ground_source()
        self.gs = GroundSrc(*gsrc) if gsrc is not None else None

    def bake(self, box, scale: int) -> np.ndarray:
        """Linear albedo of the window at scale texels per frame px (float32 HxWx3)."""
        x0, y0, x1, y1 = box
        E = self.E
        P = upsample(self.P, box, scale)
        n = upsample(self.nf, box, scale)
        n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-9
        if self.ext is not None:
            # the outpaint outside the rect; the painting inside it, unblended (the outpaint was feathered to it)
            if self.ext["k"] == 1:
                out = upsample(self.ext["frameAlb"], box, scale)
            else:
                # a k x canvas: sampled at the bake texels' own centres, de-lit by the texel's (upsampled) normal
                k, cx0 = self.ext["k"], self.ext["x0"]
                tw, th = (x1 - x0) * scale, (y1 - y0) * scale
                fx = x0 + (np.arange(tw) + 0.5) / scale - 0.5
                fy = y0 + (np.arange(th) + 0.5) / scale - 0.5
                mx, my = np.meshgrid(((fx - cx0 + 0.5) * k - 0.5).astype(np.float32),
                                     ((fy + 0.5) * k - 0.5).astype(np.float32))
                samp = cv2.remap(self.ext["lin"], mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                out = np.clip(samp / np.maximum(E.light(n, self.rig, self.sun), 0.02), 0, 1)
            if x0 < TW and y0 < TH:
                big = np.asarray(SC.albedo_background().resize((round(800 * SC.SCALE * scale),
                                                                round(374 * SC.SCALE * scale)), Image.LANCZOS)
                                 ).astype(np.float32) / 255
                rx1, ry1 = min(x1, TW), min(y1, TH)
                crop = SC_srgb_to_lin(big[y0 * scale:ry1 * scale, x0 * scale:rx1 * scale])
                L = E.light(n[:crop.shape[0], :crop.shape[1]], self.rig, self.sun)
                out[:crop.shape[0], :crop.shape[1]] = np.clip(crop / np.maximum(L, 0.02), 0, 1)
            return np.clip(out, 0, 1).astype(np.float32)
        rel = self.floor.rel(P.astype(np.float64)).astype(np.float32)
        if self.gs is not None:
            return self._bake_groundsrc(box, scale, P, n, rel)
        det, wall = synth_detail(P, n, rel)
        th, _, _ = T.polar(self.ctx.cam, P[..., 0], P[..., 2])
        base_wall = palette_at(self.pal, P[..., 1], th)
        base_floor = floor_patches(self.pal, P[..., 0], P[..., 2])
        base = base_floor * (1 - wall[..., None]) + base_wall * wall[..., None]
        d_out = upsample(self.d_rect_m, box, scale)
        edge = upsample(self.edge_col, box, scale)
        tone = np.exp(-d_out / EDGE_TONE_M)[..., None] * (1 - 0.6 * wall[..., None])
        synth = (edge * tone + base * (1 - tone)) * det * (cavity(self.field, P[..., 0], P[..., 2], wall)
                                                            * baked_shade(self.field, P[..., 0], P[..., 2], self.rig,
                                                                          self.sun, wall))[..., None]
        # rect: the painting at bake resolution, de-lit
        tw, th = (x1 - x0) * scale, (y1 - y0) * scale
        out = synth
        if x0 < TW and y0 < TH:
            big = np.asarray(SC.albedo_background().resize((round(800 * SC.SCALE * scale), round(374 * SC.SCALE * scale)),
                                              Image.LANCZOS)).astype(np.float32) / 255
            rx1, ry1 = min(x1, TW), min(y1, TH)
            crop = SC_srgb_to_lin(big[y0 * scale:ry1 * scale, x0 * scale:rx1 * scale])
            L = E.light(n[:crop.shape[0], :crop.shape[1]], self.rig, self.sun)
            rect = np.clip(crop / np.maximum(L, 0.02), 0, 1)
            # inside the rect near its right / bottom seam: the painting's grain crossfades to low-freq x detail
            d_in = upsample(self.d_in_m, box, scale)[:crop.shape[0], :crop.shape[1]]
            wb = T.smoothstep(SEAM_BAND_M, 0.0, d_in)[..., None] * 0.6
            lowdet = edge[:crop.shape[0], :crop.shape[1]] * det[:crop.shape[0], :crop.shape[1]]
            out = synth.copy()
            out[:crop.shape[0], :crop.shape[1]] = rect * (1 - wb) + lowdet * wb
        return np.clip(out, 0, 1).astype(np.float32)

    def _bake_groundsrc(self, box, scale, P, n, rel) -> np.ndarray:
        """bake() with TOWN_FULL3D_GROUNDSRC: floor from the authored material, walls from the synthesis, the painting
        inside the rect unblended (the material was built continuous with it)."""
        x0, y0, x1, y1 = box
        E = self.E
        fl_, rk, wall = synth_detail_parts(P, n, rel)
        th, _, _ = T.polar(self.ctx.cam, P[..., 0], P[..., 2])
        base_wall = palette_at(self.pal, P[..., 1], th)
        d_out = upsample(self.d_rect_m, box, scale)
        edge = upsample(self.edge_col, box, scale)
        tone = np.exp(-d_out / EDGE_TONE_M)[..., None] * (1 - 0.6 * wall[..., None])
        wall_alb = (edge * tone + base_wall * (1 - tone)) * rk
        tw, th_ = (x1 - x0) * scale, (y1 - y0) * scale
        fx = x0 + (np.arange(tw) + 0.5) / scale - 0.5
        fy = y0 + (np.arange(th_) + 0.5) / scale - 0.5
        mx, my = np.meshgrid(fx, fy)
        flo = self.gs.floor(P, footprint(P, mx, my), d_out)
        shade = cavity(self.field, P[..., 0], P[..., 2], wall) * baked_shade(self.field, P[..., 0], P[..., 2], self.rig,
                                                                            self.sun, wall)
        ramp = T.smoothstep(0.0, self.gs.shade_ramp_m, d_out).astype(np.float32)
        shade = np.power(np.maximum(shade, 1e-3), wall + (1 - wall) * ramp)
        out = (flo * (1 - wall[..., None]) + wall_alb * wall[..., None]) * shade[..., None]
        if x0 < TW and y0 < TH:
            big = np.asarray(SC.albedo_background().resize((round(800 * SC.SCALE * scale), round(374 * SC.SCALE * scale)),
                                                           Image.LANCZOS)).astype(np.float32) / 255
            rx1, ry1 = min(x1, TW), min(y1, TH)
            crop = SC_srgb_to_lin(big[y0 * scale:ry1 * scale, x0 * scale:rx1 * scale])
            L = E.light(n[:crop.shape[0], :crop.shape[1]], self.rig, self.sun)
            out[:crop.shape[0], :crop.shape[1]] = np.clip(crop / np.maximum(L, 0.02), 0, 1)
        return np.clip(out, 0, 1).astype(np.float32)
