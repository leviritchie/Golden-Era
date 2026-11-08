"""Stronghold full-3D: the HoMM3 town background as registered, metric terrain (depth measurement + hand tuning).

Measured cues (no Meshy, no outpaint, no old 2D backdrop):
  * horizon    the row where the painted far desert meets the sky through the canyon mouth: HoMM3 y 91 (frame
               163.8). The painting's floor plane vanishes there.
  * pivot      the vanilla cityHuman2 CityCamera pivot projects to frame (941, 507), on painted ground (the town
               floor by the market); the floor plane passes through it (the camera orbits a ground point, as in the
               vanilla city). With the horizon this fixes the floor plane in the camera frame up to scale. The
               vanilla camera's own world horizon is frame row ~357, so the painted floor rises ~8.5 deg away from
               the camera in the OE world: registration forces it (the HoMM3 camera looked down ~17 deg, OE's 8.5).
  * scale      a background log hut (HoMM3 base y 315) has a 16 HoMM3 px wall = 0.62 camera units at its depth;
               a one-storey hut eave of HUT_EAVE_M (hand-set 2.2 m) gives DEPTH_SCALE 0.282 units per painting m.
  * relief     Depth Anything V2 Large disparity of the painting, mapped to inverse camera depth by a robust
               (Tukey IRLS) degree-2 polynomial fitted to the floor plane on a hand-traced floor polygon; DA V2 Base
               and Depth Pro are cross-checks (agreement reported, never blended).
Hand tuning (named constants below): the floor polygon, the far cap, the wall continuation beyond the painted edges,
the ridge noise, the foreground hummocks.
"""
from __future__ import annotations

import json
import math

import cv2
import numpy as np

import stronghold_full3d_common as SC

W, H, TW, TH = SC.W, SC.H, SC.TW, SC.TH
HORIZON_HOMM3_Y = SC.FP.HORIZON_HOMM3_Y   # measured (faction profile)
HORIZON_PY = HORIZON_HOMM3_Y * SC.SCALE
HUT_WALL_UNITS, HUT_EAVE_M = SC.FP.HUT_WALL_UNITS, SC.FP.HUT_EAVE_M
DEPTH_SCALE = round(HUT_WALL_UNITS / HUT_EAVE_M, 3)   # 0.282 camera units per painting metre
FAR_CAP_M = SC.FP.FAR_CAP_M     # painting metres along the ray: the far field is clamped here
MIN_DEPTH_M = 12.0
DOME_R = 415.0                  # painting m (117 camera units: inside the runtime's raised far clip of 120)
FLOOR_POLY_HOMM3 = SC.FP.FLOOR_POLY_HOMM3   # hand-traced floor polygon (HoMM3 px), faction profile
# Outer world
FIELD_RES = 1.0                 # m per cell
FIELD_THETA = 72.0              # deg either side of the rest heading
FIELD_RHO = 400.0               # m
FIELD_BACK = 40.0               # m behind the rest camera
SPUR_SCALE, SPUR_AMP = SC.FP.SPUR_SCALE, SC.FP.SPUR_AMP   # spurs: across-slope scale (arc m at 100 m), rel. height
WALL_SHIFT_M = SC.FP.WALL_SHIFT_M   # a continued wall's foot comes this much nearer per unit of edge weight
SEAM_BLEND_M = 12.0


def camera() -> dict:
    """The cityHuman2 MainCamera rest pose (the Conflux lane's reader, read-only)."""
    import build_conflux_town3d_preview as B
    c = B.camera()
    return {k: (np.asarray(v, np.float64) if k in ("pos", "right", "up", "fwd") else v) for k, v in c.items()
            if k != "scene"}


def rays(cam, px, py):
    t = math.tan(math.radians(cam["fov"]) / 2)
    nx = (np.asarray(px, np.float64) / W) * 2 - 1
    ny = 1 - (np.asarray(py, np.float64) / H) * 2
    return cam["fwd"] + cam["right"] * (nx * t * W / H)[..., None] + cam["up"] * (ny * t)[..., None]


def project(cam, p):
    d = np.asarray(p, np.float64) - cam["pos"]
    zc = d @ cam["fwd"]
    t = math.tan(math.radians(cam["fov"]) / 2)
    px = ((d @ cam["right"]) / (zc * t * W / H) + 1) * 0.5 * W
    py = (1 - (d @ cam["up"]) / (zc * t)) * 0.5 * H
    return px, py, zc


def smoothstep(a, b, x):
    t = np.clip((np.asarray(x, np.float64) - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def heading(cam):
    up = np.array([0.0, 1.0, 0.0])
    f = cam["fwd"] - up * (cam["fwd"] @ up)
    f /= np.linalg.norm(f)
    return f, np.cross(up, f)


def polar(cam, X, Z):
    f, r = heading(cam)
    dx, dz = np.asarray(X) - cam["pos"][0], np.asarray(Z) - cam["pos"][2]
    along, side = dx * f[0] + dz * f[2], dx * r[0] + dz * r[2]
    return np.degrees(np.arctan2(side, along)), np.hypot(dx, dz), along


def polar_to_xz(cam, th_deg, rho):
    f, r = heading(cam)
    t = np.radians(th_deg)
    X = cam["pos"][0] + rho * (np.cos(t) * f[0] + np.sin(t) * r[0])
    Z = cam["pos"][2] + rho * (np.cos(t) * f[2] + np.sin(t) * r[2])
    return X, Z


def edge_azimuth(cam, px: float) -> float:
    f, r = heading(cam)
    d = rays(cam, np.array(float(px)), np.array(H * 0.5))
    return math.degrees(math.atan2(float(d @ r), float(d @ f)))


# ------------------------------------------------------------------------------------------------ painting + sky
def painting() -> np.ndarray:
    """The HoMM3 background at the frame rect size (1440x673, LANCZOS), uint8 RGB."""
    from PIL import Image
    return np.asarray(SC.background_rgb().resize((TW, TH), Image.LANCZOS))


def sky_mask(paint: np.ndarray) -> np.ndarray:
    """Painted sky by the faction profile's explicit rule (SKY_MASK; town_full3d_masks: blue / lab / none)."""
    import town_full3d_masks as M
    return M.sky_mask(paint, HORIZON_PY, SC.FP.SKY_MASK)


def floor_mask() -> np.ndarray:
    poly = (np.array(FLOOR_POLY_HOMM3, np.float64) * SC.SCALE).round().astype(np.int32)
    m = np.zeros((TH, TW), np.uint8)
    cv2.fillPoly(m, [poly], 1)
    return m.astype(bool)


# ------------------------------------------------------------------------------------------------ floor plane
class Floor:
    """The painted floor plane: 1/zc = k (py - HORIZON_PY) in painting metres; in camera coords y = a z + b."""

    def __init__(self, cam: dict):
        import conflux_town_camera_pan as PAN   # read-only: the extracted vanilla camera row
        self.cam = cam
        piv = np.asarray(PAN.load()["lookAt"]["worldPos"], np.float64)
        _, self.pivot_py, zc_units = project(cam, piv)
        self.pivot_px = float(project(cam, piv)[0])
        self.k = DEPTH_SCALE / (float(zc_units) * (float(self.pivot_py) - HORIZON_PY))
        t = math.tan(math.radians(cam["fov"]) / 2)
        self.a = t * (1 - 2 * HORIZON_PY / H)
        self.b = -2 * t / (H * self.k)
        n = cam["up"] - self.a * cam["fwd"]
        self.n = n / np.linalg.norm(n)
        self.d = self.b / np.linalg.norm(n)       # n . (P - pos) = d on the plane
        self.tilt_deg = math.degrees(math.acos(float(np.clip(self.n[1], -1, 1))))

    def inv_depth(self, py):
        return self.k * (np.asarray(py, np.float64) - HORIZON_PY)

    def y(self, X, Z):
        """World height of the plane over (X, Z)."""
        p = self.cam["pos"]
        dx, dz = np.asarray(X) - p[0], np.asarray(Z) - p[2]
        return p[1] + (self.d - self.n[0] * dx - self.n[2] * dz) / self.n[1]

    def rel(self, P):
        """Height of world points above the plane, measured vertically."""
        P = np.asarray(P, np.float64)
        return P[..., 1] - self.y(P[..., 0], P[..., 2])


# ------------------------------------------------------------------------------------------------ calibration
def calibrate(floor: Floor, disp: np.ndarray, sky: np.ndarray) -> dict:
    """Map DA disparity to inverse camera depth (1/painting m): a robust degree-2 polynomial fitted to the floor plane
    over the floor polygon (DA compresses the far floor, an affine map does not fit it)."""
    ys, xs = np.mgrid[0:TH, 0:TW]
    sel = floor_mask() & ~sky
    inv_plane = floor.inv_depth(ys[sel] + 0.5)
    d = disp[sel].astype(np.float64)
    A = np.stack([np.ones_like(d), d, d * d], 1)
    w = np.ones(len(d))
    for _ in range(15):
        sol, *_ = np.linalg.lstsq(A * w[:, None], inv_plane * w, rcond=None)
        res = A @ sol - inv_plane
        s = 1.4826 * np.median(np.abs(res[w > 0])) + 1e-12
        u = res / (4.685 * s)
        w = np.where(np.abs(u) < 1, (1 - u * u) ** 2, 0.0)
    dd = np.linspace(disp.min(), disp.max(), 256)
    mono = bool(np.all(np.diff(sol[0] + sol[1] * dd + sol[2] * dd * dd) > 0))
    inv = sol[0] + sol[1] * disp + sol[2] * disp * disp
    zc = 1.0 / np.maximum(inv, 1e-6)
    return {"zc": zc, "sol": sol.tolist(), "inliers": float((w > 0).mean()), "monotone": mono,
            "residRel": float(np.median(np.abs(res[w > 0]) / inv_plane[w > 0])), "floorPx": int(sel.sum())}


def cap_depth(cam, zc: np.ndarray, px, py) -> np.ndarray:
    """Clamp so no point is farther than FAR_CAP_M along its ray (the dome sits behind)."""
    rl = np.linalg.norm(rays(cam, px, py), axis=-1)
    return np.clip(zc, MIN_DEPTH_M, FAR_CAP_M / rl)


def background_depth_pin() -> dict | None:
    """The candidate's background depth pin (<candidate>/work/background_depth.json), None when it has none.
    Pin {"source": "img2img_bg", "npySha256": ...} selects depth/img2img_bg.npy (town_full3d_bg_depth.py import: the
    2026-09-30 image-to-image background depth, registered to the painting); {"source": "da_large", "conditioning":
    ...} conditions da_large (no disparity ops, no oldlow); no pin = da_large.npy as before."""
    import os
    cand = (os.environ.get("TOWN_FULL3D_CANDIDATE", "") or os.environ.get("STRONGHOLD_FULL3D_CANDIDATE", "")).strip()
    if not cand:
        return None
    pin = SC.DATA / "candidates" / cand / "work" / "background_depth.json"
    return json.loads(pin.read_text(encoding="utf-8")) if pin.is_file() else None


def background_disparity() -> tuple[np.ndarray, dict]:
    """The background disparity (TH x TW, larger = nearer) the calibration maps, and its provenance."""
    import hashlib
    pin = background_depth_pin()
    if pin is None:
        return np.load(SC.DATA / "depth" / "da_large.npy"), {"source": "da_large"}
    if pin.get("source") == "da_large":
        # da_large with the rx_cond conditioning (tower rx_cond_dalarge_dfix): the pin must carry it (a bare da_large
        # pin is the no-pin default and is refused, one way to say it); oldlow is the identity on its own old map
        cond = pin.get("conditioning")
        if not cond or set(cond) - {"inverseDepth", "frame"}:
            raise SystemExit("terrain: a da_large background_depth.json pin needs inverseDepth / frame conditioning")
        if any(o.get("op") == "oldlow" for o in cond.get("inverseDepth", [])):
            raise SystemExit("terrain: oldlow on da_large is the identity (its old map is itself); drop it")
        return np.load(SC.DATA / "depth" / "da_large.npy"), {"source": "da_large", "conditioning": cond}
    if pin.get("source") != "img2img_bg":
        raise SystemExit(f"terrain: background_depth.json source {pin.get('source')!r} is not img2img_bg / da_large")
    npy, meta = SC.DATA / "depth" / "img2img_bg.npy", SC.DATA / "depth" / "img2img_bg.json"
    if not npy.is_file() or not meta.is_file():
        raise SystemExit(f"terrain: pinned background depth {npy} / {meta.name} missing (town_full3d_bg_depth.py import)")
    got = hashlib.sha256(npy.read_bytes()).hexdigest()
    rec = json.loads(meta.read_text(encoding="utf-8"))
    if got != pin.get("npySha256") or got != rec.get("npySha256"):
        raise SystemExit(f"terrain: img2img_bg.npy sha256 {got} != pin {pin.get('npySha256')} / record "
                         f"{rec.get('npySha256')}")
    d = np.load(npy)
    if d.shape != (TH, TW):
        raise SystemExit(f"terrain: img2img_bg.npy {d.shape} is not the frame rect {(TH, TW)}")
    prov = {"source": "img2img_bg", "npySha256": got, "rawSha256": rec["source"]["rawSha256"],
            "raw": rec["source"]["raw"], "registration": rec["registration"]}
    cond = pin.get("conditioning")
    if cond is not None:
        # opt-in (rx_cond experiment): town_full3d_depth_cond; a pin without the key is unchanged
        import town_full3d_depth_cond as DC
        if cond.get("disparity"):
            d = DC.apply_disparity(d, cond["disparity"], painting(), np.load(SC.DATA / "depth" / "da_large.npy"))
        prov["conditioning"] = cond
    return d, prov


def cross_check(floor: Floor, sky: np.ndarray, tags=("da_base", "depthpro")) -> dict:
    """Agreement of the other estimators with the background calibration, each calibrated the same way."""
    disp, prov = background_disparity()
    base = calibrate(floor, disp, sky)["zc"]
    if prov["source"] != "da_large":
        tags = ("da_large",) + tuple(tags)
    out = {}
    for tag in tags:
        d = np.load(SC.DATA / "depth" / f"{tag}.npy")
        if tag == "depthpro":
            d = 1.0 / np.maximum(d, 1e-3)
        z = calibrate(floor, d, sky)["zc"]
        m = ~sky & np.isfinite(z) & np.isfinite(base)
        lr = np.abs(np.log(z[m] / base[m]))
        out[tag] = {"medianAbsLogRatio": round(float(np.median(lr)), 4), "p90": round(float(np.percentile(lr, 90)), 4)}
    return out


# ------------------------------------------------------------------------------------------------ rect depth
def rect_depth(cam) -> dict:
    """Calibrated background depth (background_disparity: DA Large, or the candidate's pinned source) of the HoMM3 rect (painting m), sky NaN; plus the painting and the calibration."""
    paint = painting()
    sky = sky_mask(paint)
    floor = Floor(cam)
    disp, prov = background_disparity()
    cal = calibrate(floor, disp, sky)
    cal["backgroundDepth"] = prov
    ys, xs = np.mgrid[0:TH, 0:TW] + 0.5
    zc = cap_depth(cam, cal["zc"], xs, ys)
    zc[sky] = np.nan
    cond = prov.get("conditioning") or {}
    if cond.get("inverseDepth"):
        import town_full3d_depth_cond as DC
        old = None
        if DC.needs_old(cond["inverseDepth"]):
            old = 1.0 / cap_depth(cam, calibrate(floor, np.load(SC.DATA / "depth" / "da_large.npy"), sky)["zc"], xs, ys)
        zc = cap_depth(cam, 1.0 / DC.apply_inverse(1.0 / zc, cond["inverseDepth"], floor.k, old), xs, ys)
        zc[sky] = np.nan
    return {"zc": zc, "sky": sky, "paint": paint, "floor": floor, "calib": {k: v for k, v in cal.items() if k != "zc"}}


# ------------------------------------------------------------------------------------------------ world field
def value_noise(x, z, seed, scale):
    rng = np.random.default_rng(seed)
    lat = rng.random((257, 257)).astype(np.float32)
    u, v = np.asarray(x) / scale, np.asarray(z) / scale
    iu, iv = np.floor(u).astype(int), np.floor(v).astype(int)
    fu, fv = u - iu, v - iv
    fu, fv = fu * fu * (3 - 2 * fu), fv * fv * (3 - 2 * fv)
    iu %= 256
    iv %= 256
    a, b = lat[iv, iu], lat[iv, iu + 1]
    c, d = lat[iv + 1, iu], lat[iv + 1, iu + 1]
    return (a * (1 - fu) + b * fu) * (1 - fv) + (c * (1 - fu) + d * fu) * fv


def fbm(x, z, seed, scale, octaves=5, ridged=False):
    s, amp, tot, norm = scale, 1.0, 0.0, 0.0
    for o in range(octaves):
        n = value_noise(x, z, seed + o, s)
        if ridged:
            n = 1 - np.abs(n * 2 - 1)
            n = n * n
        tot = tot + amp * n
        norm += amp
        amp *= 0.5
        s *= 0.5
    return tot / norm


def push_pull(val: np.ndarray, known: np.ndarray) -> np.ndarray:
    levels = []
    v, k = np.where(known, val, 0).astype(np.float64), known.astype(np.float64)
    while min(v.shape) > 2:
        levels.append((v, k))
        h2, w2 = (v.shape[0] + 1) // 2, (v.shape[1] + 1) // 2
        vp = np.zeros((h2 * 2, w2 * 2))
        kp = np.zeros_like(vp)
        vp[:v.shape[0], :v.shape[1]] = v * k
        kp[:v.shape[0], :v.shape[1]] = k
        s = kp.reshape(h2, 2, w2, 2).sum((1, 3))
        v = np.where(s > 0, vp.reshape(h2, 2, w2, 2).sum((1, 3)) / np.maximum(s, 1e-9), 0)
        k = np.minimum(s, 1)
    fill = v
    for v0, k0 in reversed(levels):
        up = cv2.resize(fill.astype(np.float32), (fill.shape[1] * 2, fill.shape[0] * 2), interpolation=cv2.INTER_LINEAR)
        up = up[:v0.shape[0], :v0.shape[1]]
        fill = v0 * k0 + up * (1 - k0)
    return fill


class Field:
    """World height grid (Y up) with bilinear lookup (clamped); rel = height above the floor plane."""

    def __init__(self, x0, z0, res, h):
        self.x0, self.z0, self.res, self.h = x0, z0, res, h.astype(np.float32)

    def sample(self, arr, X, Z):
        cx = np.clip((np.asarray(X) - self.x0) / self.res, 0, arr.shape[1] - 1.001)
        cz = np.clip((np.asarray(Z) - self.z0) / self.res, 0, arr.shape[0] - 1.001)
        ix, iz = cx.astype(int), cz.astype(int)
        fx, fz = cx - ix, cz - iz
        return ((arr[iz, ix] * (1 - fx) + arr[iz, ix + 1] * fx) * (1 - fz)
                + (arr[iz + 1, ix] * (1 - fx) + arr[iz + 1, ix + 1] * fx) * fz)

    def height(self, X, Z):
        return self.sample(self.h, X, Z)

    def normal(self, X, Z, eps=1.0):
        hx = (self.height(X + eps, Z) - self.height(X - eps, Z)) / (2 * eps)
        hz = (self.height(X, Z + eps) - self.height(X, Z - eps)) / (2 * eps)
        n = np.stack([-hx, np.ones_like(hx), -hz], -1)
        return n / np.linalg.norm(n, axis=-1, keepdims=True)


def edge_profile(cam, floor: Floor, zc: np.ndarray, cols: slice) -> np.ndarray:
    """Height above the floor over horizontal distance of a painted edge column band (running max, smoothed)."""
    cy, cx = np.mgrid[0:TH, cols]
    z = zc[:, cols]
    ok = np.isfinite(z)
    P = cam["pos"] + rays(cam, cx[ok] + 0.5, cy[ok] + 0.5) * z[ok][:, None]
    _, rho, _ = polar(cam, P[:, 0], P[:, 2])
    rb = np.arange(0.0, FIELD_RHO + 40, 1.0)
    prof = np.full(len(rb), np.nan)
    np.fmax.at(prof, np.clip(rho.astype(int), 0, len(rb) - 1), floor.rel(P))
    g = ~np.isnan(prof)
    first = int(np.argmax(g))
    prof = np.interp(rb, rb[g], prof[g])
    prof[:first] = 0.0          # nearer than the painted edge's nearest ground: the floor
    prof = np.maximum.accumulate(np.maximum(prof, 0))
    return cv2.GaussianBlur(prof.astype(np.float32)[None], (0, 0), 4.0)[0]


_CAM_POS = None


def rho_theta_u(X, Z):
    """Arc length across the view at 100 m (m): a coordinate that is constant down a slope toward the camera."""
    c = _CAM_POS
    return np.arctan2(np.asarray(X) - c[0], np.asarray(Z) - c[2]) * 100.0


def wall_rel(X, Z, rho, prof, s, seed, rough=None):
    """A painted wall continued past a frame edge: the edge profile, foot pulled nearer with the edge weight s, with
    ridged strata noise faded in by s (at s = 0 it is the edge's own skyline)."""
    rb = np.arange(0.0, FIELD_RHO + 40, 1.0)
    hb = np.interp(rho + WALL_SHIFT_M * s, rb, prof)
    s = s if rough is None else rough
    # badlands spurs run down the slope (toward the camera): anisotropic noise, fine across, long along rho
    ridge = fbm(X, Z, seed, 60.0, 4, ridged=True)
    u = rho_theta_u(X, Z)
    spur = fbm(u, rho * 0.18, seed + 30, SPUR_SCALE, 4, ridged=True)
    gully = fbm(X, Z, seed + 50, 35.0, 3)
    mod = 1.0 + s * (0.45 * ridge - 0.30 + SPUR_AMP * (spur - 0.45) + 0.25 * (gully - 0.5))
    return hb * mod


def world_field(cam, rd: dict) -> tuple[Field, dict]:
    """Outer heightfield: the painted surface splatted (max), push-pull filled; beyond the painted left / right edges
    the walls continued from their edge profiles; nearer than the painted floor the plane with low hummocks."""
    from scipy.ndimage import distance_transform_edt

    global _CAM_POS
    _CAM_POS = cam["pos"]
    floor: Floor = rd["floor"]
    zc = rd["zc"]
    thL, thE = edge_azimuth(cam, 0.0), edge_azimuth(cam, float(TW))
    tt = np.linspace(-FIELD_THETA - 3, FIELD_THETA + 3, 256)
    T_, R_ = np.meshgrid(tt, [0.0, FIELD_RHO + 8])
    Xb, Zb = polar_to_xz(cam, T_, R_)
    f, r = heading(cam)
    back = cam["pos"][[0, 2]] - f[[0, 2]] * FIELD_BACK
    x0 = math.floor(min(Xb.min(), back[0] - 60) / FIELD_RES) * FIELD_RES - 4
    x1 = math.ceil(max(Xb.max(), back[0] + 60) / FIELD_RES) * FIELD_RES + 4
    z0 = math.floor(min(Zb.min(), back[1]) / FIELD_RES) * FIELD_RES - 4
    z1 = math.ceil(Zb.max() / FIELD_RES) * FIELD_RES + 4
    nx, nz = int(round((x1 - x0) / FIELD_RES)) + 1, int(round((z1 - z0) / FIELD_RES)) + 1
    gz, gx = np.mgrid[0:nz, 0:nx]
    X, Z = x0 + gx * FIELD_RES, z0 + gz * FIELD_RES
    theta, rho, along = polar(cam, X, Z)
    # observed: the painted surface (height above the floor), max per cell
    ys, xs = np.nonzero(np.isfinite(zc))
    P = cam["pos"] + rays(cam, xs + 0.5, ys + 0.5) * zc[ys, xs][:, None]
    ix = np.round((P[:, 0] - x0) / FIELD_RES).astype(int)
    iz = np.round((P[:, 2] - z0) / FIELD_RES).astype(int)
    ok = (ix >= 0) & (ix < nx) & (iz >= 0) & (iz < nz)
    obs = np.full((nz, nx), -1e9)
    np.maximum.at(obs, (iz[ok], ix[ok]), floor.rel(P[ok]))
    known = obs > -1e8
    rel_pp = push_pull(np.where(known, obs, 0), known)
    # the walls past the painted edges
    prof_l = edge_profile(cam, floor, zc, slice(0, 4))
    prof_r = edge_profile(cam, floor, zc, slice(TW - 4, TW))
    thR = edge_azimuth(cam, float(W))
    # the walls close in (WALL_SHIFT_M) only outside the default frame; inside it (the frame's right quarter, right
    # of the HoMM3 rect) the right wall keeps its painted distance and only gains its spurs
    s_l = smoothstep(-thL, -thL + 25.0, -theta)
    s_r = smoothstep(thR - 2.0, thR + 25.0, theta)
    r_r = smoothstep(thE, thE + 8.0, theta)
    w_l = wall_rel(X, Z, rho, prof_l, s_l, 17)
    w_r = wall_rel(X, Z, rho, prof_r, s_r, 7, rough=r_r)
    side = np.where(theta < 0, w_l, w_r)
    in_view = (theta > thL) & (theta < thE)
    # nearer than the painted floor's nearest row (the frame bottom band / behind the camera): the floor plane
    near_rel = (fbm(X, Z, 91, 18.0, 4) - 0.5) * 1.2
    d_obs = distance_transform_edt(~known) * FIELD_RES
    b = np.exp(-(d_obs / SEAM_BLEND_M) ** 2)
    fill = np.where(in_view, np.where(rho < np.nanmin(np.where(known, rho, np.inf)) + 5, near_rel, rel_pp), side)
    # beside the view: blend the push-pull fill (which continues the edge) into the procedural wall
    edge_w = np.maximum(s_l * (theta < 0), r_r * (theta >= 0))
    fill = np.where(in_view, fill, rel_pp * (1 - edge_w) + side * edge_w)
    near_w = smoothstep(60.0, 20.0, rho) * (~in_view)
    fill = fill * (1 - near_w) + np.maximum(near_rel, fill * 0.0) * near_w
    rel = fill * (1 - b) + np.where(known, obs, rel_pp) * b
    rel = cv2.GaussianBlur(rel.astype(np.float32), (0, 0), 1.2)
    sk_info = None
    if getattr(SC.FP, "EXT_SKYLINE", None):
        rel, sk_info = fit_ext_skyline(cam, floor, X, Z, theta, rho, rel, thE, SC.FP.EXT_SKYLINE, rd["sky"])
    h = floor.y(X, Z) + rel
    field = Field(x0, z0, FIELD_RES, h)
    field.rel = rel
    field.known = known
    info = {"extent": [x0, z0, x1, z1], "res": FIELD_RES, "cells": [nz, nx], "thetaLeft": round(thL, 2),
            "thetaHoMM3Right": round(thE, 2), "thetaFrameRight": round(edge_azimuth(cam, float(W)), 2),
            "wallLeftMaxM": round(float(prof_l.max()), 1), "wallRightMaxM": round(float(prof_r.max()), 1),
            "observedShare": round(float(known.mean()), 4)}
    if sk_info is not None:
        info["extSkyline"] = sk_info
    return field, info


def fit_ext_skyline(cam, floor: Floor, X, Z, theta, rho, rel, thE: float, spec: dict, painted_sky: np.ndarray):
    """Profile EXT_SKYLINE (right side only): the continued wall's far part is scaled per azimuth so the rest camera's
    terrain silhouette lies on the TOWN_FULL3D_EXTSRC canvas's own skyline (the extension sky, town_full3d_masks.
    extension_sky with the profile's SKY_MASK). Without it the wall is the painted edge's profile plus noise, so where
    the fill paints peaks higher than that wall the rays escape and the dome shows over painted rock, and where it
    paints sky lower the canvas's sky is projected onto rock that stands up in the pans (Bulwark). Per 0.1 deg azimuth
    bin a factor k in [kMin, kMax] multiplies rel beyond rhoMinM..rhoFullM (smoothstep; the near snowfield keeps its
    own height) and fades in over the first fadeDeg past the lowest skyline azimuth; bisection on the bin's highest
    cell elevation (every far cell is scaled; only cells inside the far cap count, as the raymarch stops there;
    the cells past it are capped at the skyline, as the periphery ring draws them).
    Optional edgeRampPx: where the painting's last column stands higher than the fill's skyline beside it, the target
    ramps from the painted skyline row to the fill's over that many px (the fill's continuation of a painted peak can
    be as smooth and dark as its sky, so the sky rule takes it; the terrain must still carry it). No EXTSRC canvas: stop (the profile asks for the canvas)."""
    import town_full3d_masks as M
    ec = SC.extension_canvas()
    if ec is None:
        raise SystemExit("EXT_SKYLINE: the profile fits the extension skyline to TOWN_FULL3D_EXTSRC, which is unset")
    img, cx0, k_ = ec
    if k_ != 1:
        img = cv2.resize(img, (img.shape[1] // k_, img.shape[0] // k_), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(np.ascontiguousarray(img.astype(np.float32)), cv2.COLOR_RGB2LAB)
    rect = np.zeros(lab.shape[:2], bool)
    rect[:TH, -cx0:-cx0 + TW] = True
    rule = spec.get("skyRule")
    if rule is None:
        sky = M.extension_sky(lab, rect, SC.FP.SKY_MASK)
        cols = np.arange(-cx0 + TW, sky.shape[1])
        sub = sky[:, cols]
        ys = np.argmin(sub, axis=0).astype(np.float64)        # first non-sky row per column
    else:
        # optional skyRule {"stdMax", "stdWin", "rockRunPx", "medianPx"}: the fill paints its forests and peaks in the
        # sky's own blue (Castle: pines b* -26 against sky -20..-38), so the SKY_MASK extension box takes them as sky,
        # and textured cloud edges cut the smooth sky pockets below them off the top (the connected rule then calls
        # those pockets rock). Here a pixel is sky when it is in the extension box and smooth (local L* std over a
        # stdWin square < stdMax, as the extension stdMax rule); the skyline is the first row that starts rockRunPx
        # consecutive non-sky rows (a cloud edge is a short run), then a running median over medianPx columns (a
        # single cloud column is not a peak). No connectivity to the top is required.
        for key in ("stdMax", "stdWin", "rockRunPx", "medianPx"):
            if key not in rule:
                raise SystemExit(f"EXT_SKYLINE skyRule needs {key}, got {rule!r}")
        e = SC.FP.SKY_MASK.get("extension") or {}
        skyish = np.ones(lab.shape[:2], bool)
        for c, kk in enumerate("lab"):
            if f"{kk}Min" in e:
                skyish &= lab[..., c] > e[f"{kk}Min"]
            if f"{kk}Max" in e:
                skyish &= lab[..., c] < e[f"{kk}Max"]
        w = int(rule["stdWin"])
        Lc = lab[..., 0].astype(np.float32)
        m1, m2 = cv2.blur(Lc, (w, w)), cv2.blur(Lc * Lc, (w, w))
        skyish &= np.sqrt(np.maximum(m2 - m1 * m1, 0)) < float(rule["stdMax"])
        rl = rule.get("rockLab")
        if rl is not None:
            # optional rockLab {"lMax", "bMin"}: a pixel darker than lMax and less blue than bMin is rock, however
            # smooth (Castle seam_v3: the re-bridged mountain body under its snow line is L* 41-47 / b* -7..-11 with
            # local std 1.4-2, as smooth as the sky L* 33-47 / b* -26..-38, so the std rule took it as sky and dropped
            # the wall 50-65 rows below the mountain top onto the drifting sky dome)
            if not (isinstance(rl, dict) and set(rl) == {"lMax", "bMin"}):
                raise SystemExit(f"EXT_SKYLINE skyRule rockLab needs exactly lMax, bMin, got {rl!r}")
            skyish &= ~((lab[..., 0] < float(rl["lMax"])) & (lab[..., 2] > float(rl["bMin"])))
        skyish[int(e["maxRow"]):] = False
        skyish &= ~rect
        cols = np.arange(-cx0 + TW, skyish.shape[1])
        sub = skyish[:, cols]
        run = int(rule["rockRunPx"])
        rk = np.apply_along_axis(lambda col: np.convolve(~col, np.ones(run), mode="valid"), 0, sub) >= run
        ys = np.where(rk.any(0), np.argmax(rk, 0), sub.shape[0]).astype(np.float64)
        from scipy.ndimage import median_filter
        ys = median_filter(ys, size=int(rule["medianPx"]), mode="nearest")
    ramp = None
    if spec.get("edgeRampPx"):
        # the painted skyline at the edge: per column of the last 6 the first row that starts 20 rows of rock (the sky
        # mask has small holes: clouds, a glow), median over the columns
        def rock_top(col):
            run = np.convolve(~col, np.ones(20), mode="valid")
            return int(np.argmax(run >= 20)) if (run >= 20).any() else len(col)
        y_edge = float(np.median([rock_top(painted_sky[:, c]) for c in range(TW - 6, TW)]))
        t = np.clip((cols + cx0 - TW) / float(spec["edgeRampPx"]), 0, 1)
        ramped = y_edge + (ys - y_edge) * t * t * (3 - 2 * t)
        ramp = {"paintedEdgeRow": y_edge, "px": spec["edgeRampPx"], "raisedColumns": int((ramped < ys).sum())}
        ys = np.minimum(ys, ramped)
    keep = (sub[0] if rule is None else ys < sub.shape[0]) & (ys > 0)   # columns that have sky at the top / a skyline
    if keep.sum() < 20:
        raise SystemExit(f"EXT_SKYLINE: only {int(keep.sum())} extension columns have a sky to fit")
    fx = (cols + cx0)[keep] + 0.5
    d = rays(cam, fx, ys[keep])
    f, r = heading(cam)
    th_t = np.degrees(np.arctan2(d @ r, d @ f))
    el_t = np.arctan2(d[:, 1], np.hypot(d[:, 0], d[:, 2]))
    o = np.argsort(th_t)
    th_t, el_t = th_t[o], el_t[o]
    BIN = 0.1
    # the edge column's azimuth falls toward the top of a pitched-down frame (thE is taken at mid height): the fit
    # starts at the lowest azimuth any extension skyline ray has
    th0 = min(thE, float(th_t[0]))
    b0 = math.floor(th0 / BIN)
    sel = (theta > th0) & (rho > spec["rhoMinM"])
    bi = (np.floor(theta[sel] / BIN).astype(int) - b0)
    nb = int(bi.max()) + 1
    bc = (np.arange(nb) + b0 + 0.5) * BIN
    tgt = np.interp(bc, th_t, el_t)
    covered = (bc >= th_t[0]) & (bc <= th_t[-1])
    # the raymarch stops at the far cap along the ray: a cell counts if the bin's skyline ray reaches its distance
    reach = rho[sel] < FAR_CAP_M * np.cos(tgt[np.clip(bi, 0, nb - 1)])
    fy = floor.y(X[sel], Z[sel]) - cam["pos"][1]
    rr, wr = rel[sel], smoothstep(spec["rhoMinM"], spec["rhoFullM"], rho[sel])
    rs = rho[sel]
    fade = smoothstep(th0, th0 + spec["fadeDeg"], theta[sel])
    ths = theta[sel]

    def top_el(kb):
        # each cell's factor is interpolated between the bin centres (continuous across bins: the raymarch's bilinear
        # lookup mixes neighbouring cells, so a per-bin step would lift a bin's silhouette by its neighbour's k)
        kk = 1 + (np.interp(ths, bc, kb) - 1) * wr * fade
        e = np.arctan2(fy + rr * kk, rs)
        m = np.full(nb, -np.inf)
        np.maximum.at(m, bi[reach], e[reach])
        return m
    lo, hi = np.full(nb, float(spec["kMin"])), np.full(nb, float(spec["kMax"]))
    for _ in range(28):
        mid = 0.5 * (lo + hi)
        above = top_el(mid) > tgt
        hi, lo = np.where(above, mid, hi), np.where(above, lo, mid)
    kb = np.where(covered, 0.5 * (lo + hi), np.nan)
    # past the canvas's last fitted column: the last bin's factor
    okb = np.nonzero(covered)[0]
    kb = np.interp(np.arange(nb), okb, kb[okb])
    out = rel.copy()
    out[sel] = rr * (1 + (np.interp(ths, bc, kb) - 1) * wr * fade)
    # the cells past the ray's reach are not fitted, but the periphery ring draws them (its polar mesh samples this
    # field out to the far cap): scaled by the bin's k they stood up to 4 deg above the skyline at the painted edge,
    # a needle over the sky in the Bulwark renders. They are capped at the bin's skyline elevation (lowered only).
    far = ~reach
    capped = np.minimum(out[sel][far], np.tan(tgt[np.clip(bi[far], 0, nb - 1)]) * rs[far] - fy[far])
    nCapped = int((capped < out[sel][far] - 1e-6).sum())
    o_sel = out[sel]; o_sel[far] = capped; out[sel] = o_sel
    resid = np.degrees(top_el(kb) - tgt)[covered]
    atLo, atHi = int((kb[covered] <= spec["kMin"] + 1e-3).sum()), int((kb[covered] >= spec["kMax"] - 1e-3).sum())
    info = {"bins": int(covered.sum()), "binDeg": BIN, "k": [round(float(np.nanmin(kb)), 3), round(float(np.median(kb)), 3),
            round(float(np.nanmax(kb)), 3)], "binsAtKMin": atLo, "binsAtKMax": atHi,
            "residDegP50P95Max": [round(float(np.percentile(np.abs(resid), q)), 3) for q in (50, 95, 100)],
            "fittedColumns": int(keep.sum()), "farCellsCapped": nCapped, "targetDeg": [round(float(th_t[0]), 2), round(float(th_t[-1]), 2)],
            "binsDeg": [round(float(bc[0]), 2), round(float(bc[-1]), 2)], "edgeRamp": ramp, "spec": spec}
    if atHi > spec.get("maxBinsAtKMax", 0):
        raise SystemExit(f"EXT_SKYLINE: {atHi} azimuth bins need k > kMax {spec['kMax']} to reach the painted skyline "
                         f"(allowed {spec.get('maxBinsAtKMax', 0)}): {info}")
    print("extSkyline", json.dumps(info), flush=True)
    return out.astype(np.float32), info


def raymarch(cam, field: Field, px, py, t0=5.0, t1=None, device: str | None = None) -> np.ndarray:
    """Camera depth where each pixel ray first meets the field (NaN if it escapes).

    device (else TOWN_FULL3D_DEVICE, else cuda): cuda runs town_gpu_terrain.raymarch, byte-identical (no fallback);
    this body is the cpu reference. Parity: test_town_gpu_terrain.py."""
    import town_gpu_kernels as GK
    if GK.resolve_device(device) == "cuda":
        import town_gpu_terrain as GT
        return GT.raymarch(cam, field, px, py, t0, t1)
    t1 = t1 or FAR_CAP_M
    d = rays(cam, px, py)
    dn = d / np.linalg.norm(d, axis=-1, keepdims=True)
    fz = (dn @ cam["fwd"])
    O = cam["pos"]
    n = len(dn)
    t = np.full(n, t0)
    prev_t = t.copy()
    hit = np.full(n, np.nan)
    live = np.ones(n, bool)
    prev_above = np.ones(n, bool)
    while live.any() and True:
        idx = np.nonzero(live)[0]
        P = O + dn[idx] * t[idx, None]
        above = P[:, 1] - field.height(P[:, 0], P[:, 2])
        crossed = above <= 0
        if crossed.any():
            # bisect between prev_t and t
            ci = idx[crossed]
            lo, hi = prev_t[ci], t[ci]
            for _ in range(12):
                mid = 0.5 * (lo + hi)
                Pm = O + dn[ci] * mid[:, None]
                a = Pm[:, 1] - field.height(Pm[:, 0], Pm[:, 2]) > 0
                lo, hi = np.where(a, mid, lo), np.where(a, hi, mid)
            hit[ci] = hi * fz[ci]
            live[ci] = False
        adv = idx[~crossed]
        prev_t[adv] = t[adv]
        t[adv] += np.maximum(0.3, 0.004 * t[adv])
        live[adv[t[adv] > t1]] = False
    if SC.FP.SKY_MASK.get("rule") == "none":
        # a town with no open sky (an underground cavern): a ray that meets no terrain meets the enclosing rock at the
        # far cap instead of escaping to a sky dome (profile-gated: every other rule keeps NaN = sky, byte-identical)
        hit = np.where(np.isnan(hit), t1 * fz, hit)
    return hit
