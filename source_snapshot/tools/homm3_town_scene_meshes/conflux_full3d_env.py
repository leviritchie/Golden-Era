"""Conflux full-3D environment from the ORIGINAL HoMM3 town background only (phase 2).

References allowed (2026-09-27 user review): the original HoMM3 Conflux town screen (Conflux-in-background.png, 800x374)
and the HoMM3 building art (layers/*.png). The old runtime 2D backdrop, its outpaint and every derivative of them
(conflux_plate_z.npy, the 4k plate, homm3_conflux_reference_1920.png) are NOT read here.

  * HoMM3 region (frame x < TOWN_W, y < TOWN_H): Depth Anything V2 disparity of the upscaled original, calibrated as
    1/z = a*d + b to the registered building contacts, then a smooth multiplicative correction so the ground passes
    through every contact. Sky = disparity < SKY_DISP. Albedo = the painting at full sharpness / the Hex/Lit rig.
  * Extension (x >= TOWN_W or y >= TOWN_H, previously a blurred outpaint): a world heightmap splatted from the HoMM3
    surface, push-pull filled, plus a procedural right valley wall (ridged noise) and the two rivers carried on toward
    the camera as carved channels; every extension pixel is ray-marched against it, so edges are geometric and sharp.
    Albedo (phase 5, conflux_full3d_nearfield): the game's own terrain textures in world space, the painting only as
    low-frequency colour; phases 1-4 tiled upscaled painted crops and mirrored the painting across the seams.
  * Sky: the HoMM3 sky, directions outside it filled by mirror reflection into the painted sky (no blur).
  * Water: HoMM3 water pixels + the extension channels; flow coordinate v = geodesic distance downstream from each
    river's source (the mountains), u = across; the water mesh carries it for the flow shader.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import build_conflux_town3d_preview as B

W, H = B.W, B.H
TW, TH = B.TOWN_W, B.TOWN_H
SKY_DISP = 0.1
Z_MIN, Z_MAX = 8.0, 160.0
DA_MODEL = "depth-anything/Depth-Anything-V2-Base-hf"

# Heightmap (world metres).
HX0, HX1, HZ0, HZ1, HRES = 20.0, 200.0, -5.0, 230.0, 0.25

# Contact layers used for calibration: the full-level mesh of every building (one contact each).
CONTACT_MESHES = ("tbelhall_4", "tbelcstl_3_keep", "tbelmage_4", "tbeltvrn", "tbelblak", "tbelmark_a", "tbelmark_b",
                  "tbelsilo", "tbelspec", "tbeldock", "tbeldw_0", "tbeldw_2", "tbeldw_5_frame")

# Seamless texture crops of the original painting, in 1440x673 (frame px) coordinates.
CROPS = {
    "meadow_near": (620, 565, 860, 672),
    "meadow_mid": (820, 445, 1055, 535),
    "slope_green": (1000, 285, 1200, 398),
    "rock": (1292, 175, 1438, 328),
    "snow": (1102, 66, 1238, 138),
}


def srgb_to_lin(c):
    c = np.asarray(c, np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(c):
    c = np.clip(np.asarray(c, np.float32), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def lum(c):
    return c[..., 0] * 0.2126 + c[..., 1] * 0.7152 + c[..., 2] * 0.0722


def rays(cam, px, py):
    t = math.tan(math.radians(cam["fov"]) / 2)
    nx = (np.asarray(px, np.float64) / W) * 2 - 1
    ny = 1 - (np.asarray(py, np.float64) / H) * 2
    return (cam["fwd"] + cam["right"] * (nx * t * W / H)[..., None] + cam["up"] * (ny * t)[..., None])


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


# ------------------------------------------------------------------------------------------ HoMM3 painting + depth
def original() -> Image.Image:
    return Image.open(B.REFS / "Conflux-in-background.png").convert("RGB")


def painting(width: int = TW, height: int = TH) -> np.ndarray:
    return np.asarray(original().resize((width, height), Image.LANCZOS))


def da_disparity(work: Path) -> np.ndarray:
    """DA-V2 disparity of the original upscaled to the town rect (cached)."""
    p = work / "da_homm3.npy"
    src = B.REFS / "Conflux-in-background.png"
    key = work / "da_homm3.key"
    sig = f"{DA_MODEL}|{src.stat().st_size}|{TW}x{TH}"
    if p.is_file() and key.is_file() and key.read_text() == sig:
        return np.load(p)
    import torch
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation

    up = Image.fromarray(painting())
    proc = AutoImageProcessor.from_pretrained(DA_MODEL)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = AutoModelForDepthEstimation.from_pretrained(DA_MODEL).to(dev).eval()
    with torch.no_grad():
        out = model(**{k: v.to(dev) for k, v in proc(images=up, return_tensors="pt").items()})
        d = torch.nn.functional.interpolate(out.predicted_depth.unsqueeze(1), size=(TH, TW), mode="bicubic",
                                            align_corners=False)[0, 0].cpu().numpy()
    work.mkdir(parents=True, exist_ok=True)
    np.save(p, d.astype(np.float32))
    key.write_text(sig)
    return d.astype(np.float32)


def contacts(ctx, mesh_rows) -> list[tuple[str, float, float, float]]:
    """(name, px, py, zc) of each calibration building's base centre (registered transform)."""
    from fit_mesh_to_sprite import load_glb_unity, yaw_matrix

    out = []
    for m in mesh_rows:
        if m["name"] not in CONTACT_MESHES:
            continue
        v, _ = load_glb_unity(B.MESHY / m.get("mesh", m["name"]) / B.MESH_ATTEMPT / "model.glb")
        lo, hi = v.min(0), v.max(0)
        c = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
        w = np.asarray(m["rootPosition"]) + yaw_matrix(m["yaw"]) @ (c * m["scale"])
        px, py, zc = project(ctx.cam, w)
        out.append((m["name"], float(px), float(py), float(zc)))
    return out


def homm3_depth(ctx, work: Path) -> tuple[np.ndarray, dict]:
    """Camera depth (along fwd) over the town rect; NaN = sky."""
    d = da_disparity(work)
    raw_sky = d < SKY_DISP
    sky = raw_sky
    # Sky only where it is the sky: small disparity drop-outs inside the mountains (snow glare) are terrain; left as
    # sky they became pin-holes in the terrain mesh along the ridges.
    ncomp, lab, st, _ = cv2.connectedComponentsWithStats(sky.astype(np.uint8), connectivity=4)
    keep = np.zeros(ncomp, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= 3000
    keep[np.unique(lab[0][sky[0]])] = True
    keep[0] = False
    sky = keep[lab]
    rows = contacts(ctx, ctx.spec["meshes"])
    X, Y, P = [], [], []
    for _, px, py, zc in rows:
        xi, yi = int(px), int(min(py + 3, TH - 1))
        if 0 <= xi < TW:
            X.append(float(d[yi, xi])); Y.append(1 / zc); P.append((px, py, zc))
    a, b = np.polyfit(np.array(X), np.array(Y), 1)
    z = 1 / np.maximum(a * d + b, 1 / Z_MAX)
    # Smooth multiplicative correction through every contact, fading out ~250 px from the nearest contact.
    from scipy.interpolate import RBFInterpolator

    pts = np.array([(p[0], p[1]) for p in P])
    res = np.array([math.log(p[2] / (1 / (a * X[i] + b))) for i, p in enumerate(P)])
    rbf = RBFInterpolator(pts, res, kernel="thin_plate_spline", smoothing=2.0)
    gy, gx = np.mgrid[0:TH:8, 0:TW:8]
    q = np.stack([gx.ravel(), gy.ravel()], 1).astype(np.float64)
    r = rbf(q).reshape(gx.shape)
    dist = np.min(np.linalg.norm(q[:, None, :] - pts[None], axis=-1), 1).reshape(gx.shape)
    r = np.clip(r, -0.2, 0.2) * np.exp(-(dist / 250.0) ** 2)
    r = cv2.resize(r.astype(np.float32), (TW, TH), interpolation=cv2.INTER_CUBIC)
    z = np.clip(z * np.exp(r), Z_MIN, Z_MAX)
    z[raw_sky] = np.nan
    holes = raw_sky & ~sky
    z = np.where(holes, filled_depth(z), z)  # the drop-outs take their surroundings' depth
    z[sky] = np.nan
    fit = [{"name": n, "zc": round(zc, 2), "zAfter": round(float(z[int(min(py + 3, TH - 1)), int(px)]), 2)}
           for n, px, py, zc in rows if int(px) < TW]
    return z.astype(np.float32), {"a": float(a), "b": float(b), "contacts": fit, "skyShare": float(sky.mean())}


# ------------------------------------------------------------------------------------------------- heightmap
def push_pull(val: np.ndarray, known: np.ndarray) -> np.ndarray:
    """Fill unknown cells smoothly from known ones (pyramid push-pull)."""
    levels = []
    v, k = np.where(known, val, 0).astype(np.float64), known.astype(np.float64)
    while min(v.shape) > 2:
        levels.append((v, k))
        h2, w2 = (v.shape[0] + 1) // 2, (v.shape[1] + 1) // 2
        vp = np.zeros((h2 * 2, w2 * 2)); kp = np.zeros_like(vp)
        vp[:v.shape[0], :v.shape[1]] = v * k; kp[:v.shape[0], :v.shape[1]] = k
        s = kp.reshape(h2, 2, w2, 2).sum((1, 3))
        v = np.where(s > 0, vp.reshape(h2, 2, w2, 2).sum((1, 3)) / np.maximum(s, 1e-9), 0)
        k = np.minimum(s, 1)
    fill = v
    for v0, k0 in reversed(levels):
        up = cv2.resize(fill.astype(np.float32), (fill.shape[1] * 2, fill.shape[0] * 2), interpolation=cv2.INTER_LINEAR)
        up = up[:v0.shape[0], :v0.shape[1]]
        fill = v0 * k0 + up * (1 - k0)
    return fill


def value_noise(x, z, seed, scale):
    """Smooth value noise (bicubic-interpolated lattice)."""
    rng = np.random.default_rng(seed)
    lat = rng.random((257, 257)).astype(np.float32)
    u, v = np.asarray(x) / scale, np.asarray(z) / scale
    iu, iv = np.floor(u).astype(int), np.floor(v).astype(int)
    fu, fv = u - iu, v - iv
    fu, fv = fu * fu * (3 - 2 * fu), fv * fv * (3 - 2 * fv)
    iu %= 256; iv %= 256
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


class Heightmap:
    def __init__(self, hgt: np.ndarray, water_level: np.ndarray, channel: np.ndarray):
        self.h = hgt.astype(np.float32)
        self.wl = water_level.astype(np.float32)
        self.ch = channel.astype(np.float32)  # 1 on extension river channels (water surface), 0 elsewhere

    def cell(self, x, z):
        return (np.asarray(x) - HX0) / HRES, (np.asarray(z) - HZ0) / HRES

    def sample(self, arr, x, z):
        cx, cz = self.cell(x, z)
        cx = np.clip(cx, 0, arr.shape[1] - 1.001); cz = np.clip(cz, 0, arr.shape[0] - 1.001)
        ix, iz = cx.astype(int), cz.astype(int)
        fx, fz = cx - ix, cz - iz
        return ((arr[iz, ix] * (1 - fx) + arr[iz, ix + 1] * fx) * (1 - fz)
                + (arr[iz + 1, ix] * (1 - fx) + arr[iz + 1, ix + 1] * fx) * fz)

    def height(self, x, z):
        return self.sample(self.h, x, z)


def boundary_angle(cam) -> float:
    """Horizontal angle (deg, right of the camera heading) of the HoMM3 right edge at the horizon."""
    d = rays(cam, np.array(float(TW)), np.array(H * 0.5))
    f, r = heading(cam)
    return math.degrees(math.atan2(float(d @ r), float(d @ f)))


def heading(cam):
    up = np.array([0.0, 1.0, 0.0])
    f = cam["fwd"] - up * (cam["fwd"] @ up)
    f /= np.linalg.norm(f)
    return f, np.cross(up, f)


def river_exits(cam, z_homm3: np.ndarray, water: np.ndarray) -> list[dict]:
    """Where the HoMM3 rivers leave the town rect through its bottom row: world entry point, direction, half-width."""
    row = TH - 2
    segs = []
    xs = np.nonzero(water[TH - 14:TH - 1].any(0))[0]
    if len(xs) == 0:
        return []
    start = xs[0]
    for i in range(1, len(xs) + 1):
        if i == len(xs) or xs[i] != xs[i - 1] + 1:
            end = xs[i - 1]
            if end - start >= 12:
                segs.append((start, end))
            if i < len(xs):
                start = xs[i]
    out = []
    for x0, x1 in segs:
        wr = np.nonzero(water[TH - 14:TH - 1, x0:x1 + 1].any(1))[0]
        row = TH - 14 + int(wr.max())
        xr = np.nonzero(water[row, x0:x1 + 1])[0] + x0
        if len(xr):
            x0, x1 = int(xr.min()), int(xr.max())
        cx = 0.5 * (x0 + x1)
        pw = cam["pos"] + rays(cam, np.array(cx), np.array(float(row))) * z_homm3[row, int(cx)]
        pl = cam["pos"] + rays(cam, np.array(float(x0)), np.array(float(row))) * z_homm3[row, x0]
        pr = cam["pos"] + rays(cam, np.array(float(x1)), np.array(float(row))) * z_homm3[row, x1]
        # Direction: centroid of the water pixels 60 rows up -> exit (downstream, toward the camera).
        up_row = row - 60
        wx = np.nonzero(water[up_row, max(0, x0 - 120):x1 + 120])[0] + max(0, x0 - 120)
        cu = float(np.median(wx)) if len(wx) else cx
        pu = cam["pos"] + rays(cam, np.array(cu), np.array(float(up_row))) * z_homm3[up_row, int(cu)]
        dxz = (pw - pu)[[0, 2]]
        dxz /= np.linalg.norm(dxz) + 1e-9
        m_per_px = float(np.linalg.norm((pr - pl)[[0, 2]])) / max(1, x1 - x0)
        widths = [int(water[rr, max(0, x0 - 60):x1 + 60].sum()) for rr in range(TH - 40, TH - 1)]
        half = float(0.5 * np.percentile(widths, 75) * m_per_px)
        # halfWidth is a row slice, i.e. measured along the seam; a river crossing the seam at angle a has the
        # perpendicular half-width halfWidth * sin(a) there. The carved channel starts at that width (entry_taper).
        _, r_h = heading(cam)
        sin_a = abs(dxz[0] * r_h[2] - dxz[1] * r_h[0]) / (np.linalg.norm(r_h[[0, 2]]) + 1e-9)
        out.append({"px": [int(x0), int(x1)], "entry": pw.tolist(), "dir": dxz.tolist(), "halfWidth": half,
                    "entryHalfWidth": half * float(sin_a)})
    return out


def entry_taper(wide: np.ndarray, e: dict, s_m: np.ndarray) -> np.ndarray:
    """Channel half-width near its HoMM3 exit: the painted exit's perpendicular half-width at the seam, growing to the
    channel's own width over ENTRY_TAPER_M. Without it a channel leaving at a shallow angle to the bottom row (its
    0.5 m floor on top) showed water under the row over 2.6x the painted exit, a straight bank along y = TH."""
    w0 = np.minimum(wide, e["entryHalfWidth"])
    return w0 + (wide - w0) * smoothstep(0.0, ENTRY_TAPER_M, s_m)


def polar(cam, X, Z):
    f, r = heading(cam)
    dx, dz = X - cam["pos"][0], Z - cam["pos"][2]
    along, side = dx * f[0] + dz * f[2], dx * r[0] + dz * r[2]
    return np.degrees(np.arctan2(side, along)), np.hypot(dx, dz), along


def build_heightmap(ctx, z: np.ndarray, water: np.ndarray, rng_seed: int = 7,
                    taper: bool = True) -> tuple[Heightmap, dict]:
    """World heightmap: splatted HoMM3 surface where observed; explicit extensions where the frame shows new ground:
      A  foreground (inside the HoMM3 horizontal view, nearer than its bottom row): the bottom-row heights carried
         toward the camera along each viewing azimuth, plus meadow hummocks and the carved river channels;
      B  right of the HoMM3 view: the right-edge column's height profile over distance, pulled toward the camera
         and raised with the azimuth (a valley wall), with ridged noise scaled by the height above the meadow;
      C  everything else (occluded or off-frame): push-pull fill."""
    cam = ctx.cam
    ys, xs = np.nonzero(~np.isnan(z))
    P = cam["pos"] + rays(cam, xs.astype(np.float64), ys.astype(np.float64)) * z[ys, xs][:, None]
    nx, nz = int((HX1 - HX0) / HRES) + 1, int((HZ1 - HZ0) / HRES) + 1
    ix = np.clip(((P[:, 0] - HX0) / HRES).round().astype(int), 0, nx - 1)
    iz = np.clip(((P[:, 2] - HZ0) / HRES).round().astype(int), 0, nz - 1)
    obs = np.full((nz, nx), -1e9)
    np.maximum.at(obs, (iz, ix), P[:, 1])
    known = obs > -1e8
    hgt = push_pull(np.where(known, obs, 0), known)
    gz, gx = np.mgrid[0:nz, 0:nx]
    X, Z = HX0 + gx * HRES, HZ0 + gz * HRES
    theta, rad, along = polar(cam, X, Z)
    th_e = boundary_angle(cam)
    d0 = rays(cam, np.array(0.0), np.array(H * 0.5))
    f0, r0 = heading(cam)
    th_l = math.degrees(math.atan2(float(d0 @ r0), float(d0 @ f0)))  # the HoMM3 left edge is the frame's left edge
    # --- A: foreground from the bottom row (last 4 rows, binned by azimuth -> height / along distance).
    rows = slice(TH - 5, TH - 1)
    ry, rx = np.mgrid[rows, 0:TW]
    ok = ~np.isnan(z[rows])
    Pb = cam["pos"] + rays(cam, rx[ok].astype(np.float64), ry[ok].astype(np.float64)) * z[rows][ok][:, None]
    tb, _, ab = polar(cam, Pb[:, 0], Pb[:, 2])
    hb = Pb[:, 1]
    bins = np.linspace(th_l - 0.5, th_e + 0.5, 200)
    idx = np.clip(np.searchsorted(bins, tb) - 1, 0, len(bins) - 2)
    hs = np.array([np.median(hb[idx == i]) if (idx == i).any() else np.nan for i in range(len(bins) - 1)])
    as_ = np.array([np.median(ab[idx == i]) if (idx == i).any() else np.nan for i in range(len(bins) - 1)])
    bc = 0.5 * (bins[1:] + bins[:-1])
    good = ~np.isnan(hs)
    hs = cv2.GaussianBlur(np.interp(bc, bc[good], hs[good]).astype(np.float32)[None], (0, 0), 2.0)[0]
    as_ = np.interp(bc, bc[good], as_[good])
    hs_far = cv2.GaussianBlur(hs[None], (0, 0), 14.0)[0]
    h_seam = np.interp(theta, bc, hs)
    h_far = np.interp(theta, bc, hs_far)
    a_seam = np.interp(theta, bc, as_)
    hummock = (fbm(X, Z, rng_seed + 20, 7.0, 4) - 0.5) * 0.55
    # The painted bottom row's hedges and banks are not carried toward the camera as radial ridges: the seam height
    # relaxes to its broad trend within ~5 m, and meadow hummocks take over.
    relax = smoothstep(0.0, 5.0, a_seam - along)
    fade_in = smoothstep(0.0, 3.0, a_seam - along)  # 0 at the seam: meets the painted ground exactly
    hA = h_seam * (1 - relax) + h_far * relax + hummock * fade_in
    fg = (theta <= th_e) & (theta >= th_l - 3) & (along < a_seam) & (along > -5)
    fgx = (theta >= th_l - 3) & (theta <= th_e + 20) & (along < a_seam) & (along > -5)  # A carried under B's blend
    hgt = np.where(fgx, hA, hgt)
    # --- B: right of the HoMM3 view.
    cy, cx_ = np.mgrid[0:TH, TW - 3:TW]
    ok = ~np.isnan(z[:, TW - 3:TW])
    Pe = cam["pos"] + rays(cam, cx_[ok].astype(np.float64), cy[ok].astype(np.float64)) * z[:, TW - 3:TW][ok][:, None]
    _, re_, _ = polar(cam, Pe[:, 0], Pe[:, 2])
    rb = np.arange(0.0, 240.0, 0.5)
    prof = np.full(len(rb), np.nan)
    ib = np.clip((re_ / 0.5).astype(int), 0, len(rb) - 1)
    np.fmax.at(prof, ib, Pe[:, 1])
    g = ~np.isnan(prof)
    prof = np.interp(rb, rb[g], prof[g])
    prof = np.maximum.accumulate(prof)  # a front-seen surface does not descend behind its visible ridge here
    prof = cv2.GaussianBlur(prof.astype(np.float32)[None], (0, 0), 3.0)[0]
    meadow_h = float(np.median(prof[(rb > 18) & (rb < 35)]))
    s = smoothstep(th_e, th_e + 17.0, theta)
    shift = 10.0 * s                       # the mountain foot comes ~10 m nearer at the frame edge
    rise = 1.0 - 0.35 * s                  # the ridge falls away to the right: a peak frames the town, sky above
    hb_ = np.interp(rad + shift, rb, prof)
    above = np.maximum(hb_ - meadow_h, 0) * rise
    ridge = fbm(X, Z, rng_seed, 16.0, 4, ridged=True)
    crag = fbm(X, Z, rng_seed + 60, 6.0, 3, ridged=True)
    gully = fbm(X, Z, rng_seed + 40, 9.0, 3)
    hB = (meadow_h + above * (0.64 + 0.55 * ridge + 0.08 * (crag - 0.5)) + (gully - 0.5) * 0.25 * above
          + hummock * (1 - smoothstep(0, 4, above)))
    wB = smoothstep(th_e, th_e + 6.0, theta)
    right = theta > th_e - 0.3
    hgt = np.where(right & (~known | fgx), hgt * (1 - wB) + hB * wB, hgt)
    hgt = np.where(right & known & (theta > th_e + 0.5), hB, hgt)
    # --- rivers: carve channels from each exit toward (and past) the camera, through region A.
    f, _ = heading(cam)
    exits = river_exits(cam, z, water)
    channel = np.zeros_like(hgt)
    wl = np.full_like(hgt, -1e3)
    rng = np.random.default_rng(rng_seed)
    paths = []
    from scipy.spatial import cKDTree

    for k, e in enumerate(exits):
        p = np.array([e["entry"][0], e["entry"][2]])
        d = np.array(e["dir"])
        hw = max(0.5, e["halfWidth"])
        level = float(e["entry"][1]) - 0.05
        pts = []
        phase = rng.uniform(0, 6.28)
        for i in range(600):
            pts.append(p.copy())
            tgt = -f[[0, 2]]
            ang = math.atan2(d[1], d[0])
            tang = math.atan2(tgt[1], tgt[0])
            # Phase 3b: a meander about the heading toward the camera (the phase-2 path was nearly straight), eased
            # in over the first metres so the channel leaves the HoMM3 exit on the painted direction.
            s_m = i * 0.2
            want = tang + MEANDER_AMP * math.sin(2 * math.pi * s_m / MEANDER_LEN + phase) * smoothstep(0.0, 6.0, s_m)
            ang += 0.1 * math.atan2(math.sin(want - ang), math.cos(want - ang))
            d = np.array([math.cos(ang), math.sin(ang)])
            p = p + d * 0.2
            if (p[0] - cam["pos"][0]) * f[0] + (p[1] - cam["pos"][2]) * f[2] < 2.0:
                break
        pts = np.array(pts)
        paths.append({"exit": e, "points": pts[::10].round(3).tolist()})
        tree = cKDTree(pts)
        sel = fgx & (rad < 40)
        dd, ii = tree.query(np.stack([X[sel], Z[sel]], 1))
        wide = hw * (1.0 + 0.3 * np.clip(ii * 0.2 / 10.0, 0, 1))  # widens a little toward the camera
        if taper:
            wide = entry_taper(wide, e, ii * 0.2)
        wide = wide * (1.0 + 0.18 * np.sin(ii * 0.2 * 2 * math.pi / (MEANDER_LEN * 0.55) + phase * 1.7))  # pools/narrows
        bed = level - 0.3
        bank = level + 0.12 + 0.35 * np.clip(dd / wide - 1, 0, None)
        hs_ = hgt[sel]
        carve = np.clip(1 - (dd / wide) ** 2, 0, 1)
        hs_ = np.where(dd < wide * 2.5, np.minimum(hs_, bank), hs_)
        hs_ = np.where(dd < wide, np.minimum(hs_, bed + (level - bed) * (1 - carve)), hs_)
        hs_ = np.where(dd < wide * 1.05, np.maximum(hs_, level), hs_)  # the water surface itself
        hgt[sel] = hs_
        channel[sel] = np.maximum(channel[sel], (dd < wide * 1.05).astype(np.float32))
        wl[sel] = np.where(dd < wide * 1.05, np.maximum(wl[sel], level), wl[sel])
    # Banks and the region seams are sub-cell steps; bilinear sampling of a step renders as a staircase silhouette
    # near the camera (a 0.25 m cell spans ~30 px at 10 m). One cell of Gaussian keeps the shapes, drops the stairs.
    hgt = cv2.GaussianBlur(hgt.astype(np.float32), (0, 0), 1.2)
    channel = cv2.GaussianBlur(channel.astype(np.float32), (0, 0), 1.2)
    hm = Heightmap(hgt, wl, channel)
    return hm, {"thetaEdge": th_e, "meadowHeight": meadow_h, "exits": exits, "riverPaths": paths,
                "knownShare": float(known.mean())}


def raymarch(cam, hm: Heightmap, px: np.ndarray, py: np.ndarray, t0=2.0, t1=190.0) -> tuple[np.ndarray, np.ndarray]:
    """Depth along fwd of the first heightmap hit for each pixel ray (NaN = sky); also whether it hit water."""
    d = rays(cam, px, py).reshape(-1, 3)
    n = len(d)
    zc = np.full(n, np.nan)
    wat = np.zeros(n, bool)
    act = np.arange(n)
    t_prev = np.full(n, t0)
    t = np.full(n, t0)
    o = cam["pos"]
    while len(act):
        p = o + d[act] * t[act, None]
        hgt = hm.height(p[:, 0], p[:, 2])
        hit = p[:, 1] <= hgt
        if hit.any():
            hi = act[hit]
            lo_t, hi_t = t_prev[hi].copy(), t[hi].copy()
            for _ in range(10):
                mid = 0.5 * (lo_t + hi_t)
                q = o + d[hi] * mid[:, None]
                below = q[:, 1] <= hm.height(q[:, 0], q[:, 2])
                hi_t = np.where(below, mid, hi_t)
                lo_t = np.where(below, lo_t, mid)
            zc[hi] = hi_t
            q = o + d[hi] * hi_t[:, None]
            wat[hi] = hm.sample(hm.ch, q[:, 0], q[:, 2]) > 0.5
        keep = ~hit
        act = act[keep]
        t_prev[act] = t[act]
        t[act] = t[act] + np.maximum(0.04, 0.012 * t[act])
        far = t[act] > t1
        act = act[~far]
    return zc.reshape(np.shape(px)), wat.reshape(np.shape(px))


# ------------------------------------------------------------------------------------------------ classes
SKY, GRASS, FOREST, ROCK, SNOW, DIRT, WATER = range(7)


def homm3_water(img: np.ndarray, z: np.ndarray) -> np.ndarray:
    """River / waterfall pixels of the painting (town rect)."""
    im = cv2.GaussianBlur(img, (0, 0), 1.2)
    hsv = cv2.cvtColor(im, cv2.COLOR_RGB2HSV).astype(np.float32)
    s, v = hsv[..., 1] / 255, hsv[..., 2]
    r, g, b = (im[..., i].astype(np.float32) for i in range(3))
    yy, xx = np.mgrid[0:TH, 0:TW]
    water = (b > r + 6) & (b >= g - 6) & (v > 95) & (s < 0.5) & (yy > 0.52 * TH)
    fall = (v > 185) & (s < 0.2) & (xx > 1195) & (xx < 1300) & (yy > 320) & (yy < 470)
    water |= fall
    water &= ~np.isnan(z)
    water = cv2.morphologyEx(water.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    water = cv2.morphologyEx(water, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(water)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= 150
    return keep[lab]


# ------------------------------------------------------------------------------------------------ full frame
def frame_depth(ctx, work: Path, taper: bool = True) -> dict:
    """Full-frame depth zs (NaN = sky), water mask, extension flag, heightmap. taper=False carves the river channels
    without entry_taper: the placement frame the scatter reads (stage), so the taper reshapes the rendered channel only
    and leaves every prop, tuft and pebble where it was."""
    zh, cal = homm3_depth(ctx, work)
    img = painting()
    wat_h = homm3_water(img, zh)
    hm, hstats = build_heightmap(ctx, zh, wat_h, taper=taper)
    zs = np.full((H, W), np.nan, np.float32)
    water = np.zeros((H, W), bool)
    zs[:TH, :TW] = zh
    water[:TH, :TW] = wat_h
    ext = np.ones((H, W), bool)
    ext[:TH, :TW] = False
    ys, xs = np.nonzero(ext)
    zc = np.full(len(xs), np.nan)
    wa = np.zeros(len(xs), bool)
    step = 200000
    for i in range(0, len(xs), step):
        zc[i:i + step], wa[i:i + step] = raymarch(ctx.cam, hm, xs[i:i + step].astype(np.float64) + 0.5,
                                                  ys[i:i + step].astype(np.float64) + 0.5)
    zs[ys, xs] = zc
    water[ys, xs] = wa
    # Seam blend: within SEAM px outside the town rect, pull the ray-marched depth toward the edge row/column depth
    # so the mesh has no step at the seam (the heightmap already agrees there up to splat resolution).
    SEAM = 10
    zr = zs.copy()
    for k in range(SEAM):
        w = 1 - (k + 1) / (SEAM + 1)
        if TW + k < W:
            col, edge = zs[:TH, TW + k], zh[:, TW - 1]
            ok = ~np.isnan(col) & ~np.isnan(edge)
            zr[:TH, TW + k] = np.where(ok, (1 / ((1 - w) / col + w / edge)), col)
        if TH + k < H:
            row, edge = zs[TH + k, :TW], zh[TH - 1, :]
            ok = ~np.isnan(row) & ~np.isnan(edge)
            zr[TH + k, :TW] = np.where(ok, (1 / ((1 - w) / row + w / edge)), row)
    zs = zr
    return {"zs": zs, "water": water, "ext": ext, "hm": hm, "calib": cal, "heightmap": hstats, "zh": zh,
            "paint": img}


def mirror_index(px: np.ndarray, py: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Reflect frame coordinates into the town rect (mirror at its right and bottom edges, and at 0). Sky dome only."""
    x = np.where(px >= TW, 2 * (TW - 1) - px, px)
    x = np.where(x < 0, -x, x)
    y = np.where(py >= TH, 2 * (TH - 1) - py, py)
    y = np.where(y < 0, -y, y)
    return np.clip(x, 0, TW - 1), np.clip(y, 0, TH - 1)


# ------------------------------------------------------------------------------------------------ lighting
def light(n, rig, sun_dir):
    """Hex/Lit diffuse irradiance: trilight + key + fill (bake_town_materials.light)."""
    ny = n[..., 1:2]
    up = np.sqrt(np.clip(ny, 0, 1))
    dn = np.sqrt(np.clip(-ny, 0, 1))
    sky, eq, gr = (np.array(rig[k], np.float32) for k in ("ambSky", "ambEq", "ambGround"))
    amb = np.where(ny >= 0, eq + (sky - eq) * up, eq + (gr - eq) * dn)
    out = amb + np.array(rig["sunColor"], np.float32) * np.clip(n @ -np.asarray(sun_dir, np.float32), 0, None)[..., None]
    if rig.get("fillColor"):
        out = out + np.array(rig["fillColor"], np.float32) * np.clip(n @ -np.asarray(rig["fillDir"], np.float32), 0, None)[..., None]
    return out


# ------------------------------------------------------------------------------------------------ terrain mesh
def terrain_mesh(ctx, zs: np.ndarray, grid: int = 3, disp=None) -> dict:
    """Screen-space terrain grid over the whole frame. Grid vertices one cell outside the silhouette are snapped onto
    it (half a pixel beyond the nearest terrain pixel), so the ridge line follows the depth map's own edge to about a
    pixel instead of a 3 px staircase; uv = the vertex's (snapped) frame position, so the texture edge coincides.
    disp(fx, fy, P) -> forward-depth offset per vertex (phase 5 relief): the vertex moves along its own camera ray,
    so its screen position and the texture registration are unchanged; normals follow the moved surface."""
    from scipy.ndimage import binary_dilation, distance_transform_edt

    # The grid runs to the frame's far edges (x = W, y = H): rays() puts pixel i's left edge at i, so a grid ending
    # at W - 1 / H - 1 left the last column and the bottom row uncovered (the clear colour showed along the bottom
    # of every render). Lookups use the clamped pixel index.
    xs_f = np.unique(np.r_[np.arange(0, W, grid), W - 1, W])
    ys_f = np.unique(np.r_[np.arange(0, H, grid), H - 1, H])
    xs, ys = np.minimum(xs_f, W - 1), np.minimum(ys_f, H - 1)
    gx, gy = np.meshgrid(xs, ys)
    terr = ~np.isnan(zs)
    valid = terr[gy, gx]
    fringe = binary_dilation(valid, np.ones((3, 3), bool)) & ~valid
    _, (iy, ix) = distance_transform_edt(~terr, return_indices=True)
    fx, fy = (a_.astype(np.float64) for a_ in np.meshgrid(xs_f, ys_f))
    ty, tx = iy[gy, gx], ix[gy, gx]
    vx, vy = fx - tx, fy - ty
    nrm = np.hypot(vx, vy) + 1e-9
    fx = np.where(fringe, tx + 0.5 * vx / nrm, fx)
    fy = np.where(fringe, ty + 0.5 * vy / nrm, fy)
    zz = np.where(valid, zs[gy, gx], zs[ty, tx])
    keep = valid | fringe
    if disp is not None:
        zz = zz + disp(fx, fy, ctx.cpos + rays(ctx.cam, fx, fy) * zz[..., None])
    P = ctx.cpos + rays(ctx.cam, fx, fy) * zz[..., None]
    dx = np.zeros_like(P); dy = np.zeros_like(P)
    dx[:, 1:-1] = P[:, 2:] - P[:, :-2]; dx[:, 0] = P[:, 1] - P[:, 0]; dx[:, -1] = P[:, -1] - P[:, -2]
    dy[1:-1] = P[2:] - P[:-2]; dy[0] = P[1] - P[0]; dy[-1] = P[-1] - P[-2]
    n = np.cross(dx, dy)
    n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-12
    n[(n * (ctx.cpos - P)).sum(-1) < 0] *= -1
    # Where the grid bridges a depth step (a near ridge in front of a far slope) the bridging normals turn edge-on to
    # the camera: lit, they went black, and the albedo bake (paint / irradiance) turned bright there, so the ridges
    # were dotted. Such normals are pulled toward the viewer; ordinary slopes (cos >= 0.3) are untouched.
    to_cam = ctx.cpos - P
    to_cam /= np.linalg.norm(to_cam, axis=-1, keepdims=True) + 1e-12
    cosv = (n * to_cam).sum(-1)
    w = np.clip((0.3 - cosv) / 0.3, 0, 1)[..., None]
    n = n * (1 - w) + to_cam * w
    n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-12
    # Bridging normals can also face the camera yet point downward: lit only by the dark ground ambient they read
    # black (and the bake boosted their albedo to white). Terrain faces up, so these lean toward up + viewer.
    up_cam = to_cam + np.array([0.0, 1.0, 0.0])
    up_cam /= np.linalg.norm(up_cam, axis=-1, keepdims=True) + 1e-12
    wy = np.clip((0.25 - n[..., 1]) / 0.5, 0, 1)[..., None]
    n = n * (1 - wy) + up_cam * wy
    n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-12
    nx_ = len(xs)
    j, i = np.meshgrid(np.arange(len(ys) - 1), np.arange(nx_ - 1), indexing="ij")
    a = (j * nx_ + i).ravel()
    tris = np.concatenate([np.stack([a, a + 1, a + nx_], 1), np.stack([a + 1, a + nx_ + 1, a + nx_], 1)])
    tris = tris[keep.ravel()[tris].all(1)]
    uv = np.clip(np.stack([fx / (W - 1), 1 - fy / (H - 1)], -1).reshape(-1, 2), 0, 1)
    return {"xs": xs, "ys": ys, "P": P, "n": n, "tris": tris, "uv": uv, "keep": keep, "fx": fx, "fy": fy,
            "snapped": int(fringe.sum())}


def frame_normals(grid: dict) -> np.ndarray:
    nf = cv2.resize(grid["n"].astype(np.float32), (W, H), interpolation=cv2.INTER_LINEAR)
    return nf / (np.linalg.norm(nf, axis=-1, keepdims=True) + 1e-9)


def filled_depth(zs: np.ndarray) -> np.ndarray:
    from scipy.ndimage import distance_transform_edt

    _, (iy, ix) = distance_transform_edt(np.isnan(zs), return_indices=True)
    return zs[iy, ix]


# ------------------------------------------------------------------------------------------------ albedo
# Phase 5: the terrain albedo is baked by conflux_full3d_nearfield (vanilla terrain textures as the extension's albedo,
# the painting as low-frequency colour only). The phase 1-4 painted-crop tiling and mirrored seam feather are gone.
def fill_from_interior(img: np.ndarray, bad: np.ndarray) -> np.ndarray:
    from scipy.ndimage import distance_transform_edt

    _, (iy, ix) = distance_transform_edt(bad, return_indices=True)
    return img[iy, ix]


EXT_CLASSES = ("meadow", "slope", "rock", "snow")


# ------------------------------------------------------------------------------------------------ water
MEANDER_AMP = 0.75  # rad: river swing about its heading toward the camera (extension channels)
MEANDER_LEN = 14.0  # m: one meander wavelength
ENTRY_TAPER_M = 4.0  # m: the channel widens from the painted exit's cross-section to its own width over this
FLOW_STEP = 2  # px lattice of the downstream-distance solve
SHORE_OUT = 6     # px the water mesh and its shore coordinate reach past the bank (FlowWater _ShoreOut)
SHORE_RANGE = 32  # px span of the shore coordinate in the tint alpha (FlowWater _ShoreRange)


def water_mesh(ctx, fd: dict, grid: dict) -> dict:
    """Water mesh over the (dilated) water mask, pulled 0.4 % toward the camera. UV0 = frame position (painted
    tint texture), UV1 = flow coordinate: u across the stream (metres along the camera right axis), v = geodesic
    metres downstream from the component's source. The source of each connected water body is its highest pixel
    (mountain end), so v grows toward the camera along every river's own path, round every bend."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra

    water = fd["water"]
    zfill = filled_depth(fd["zs"])
    # Phase 3b: the mesh reaches SHORE_OUT px past the bank so the shader can feather its alpha across it.
    wd = cv2.dilate(water.astype(np.uint8), np.ones((2 * SHORE_OUT + 1,) * 2, np.uint8)).astype(bool) & ~np.isnan(fd["zs"])
    xs, ys = grid["xs"], grid["ys"]
    gw = wd[np.ix_(ys, xs)]
    tris = grid["tris"][gw.ravel()[grid["tris"]].all(1)]
    P = ctx.cpos + (grid["P"] - ctx.cpos) * 0.996
    n = grid["n"].copy()
    n[n[..., 1] > math.cos(math.radians(40))] = np.array([0, 1, 0])
    step = FLOW_STEP
    sub = wd[::step, ::step]
    sy, sx = np.nonzero(sub)
    idx = -np.ones(sub.shape, np.int64)
    idx[sy, sx] = np.arange(len(sy))
    Pw = ctx.cpos + rays(ctx.cam, sx * step * 1.0, sy * step * 1.0) * zfill[sy * step, sx * step][:, None]
    rows, cols, wts = [], [], []
    for dy_, dx_ in ((0, 1), (1, 0), (1, 1), (1, -1)):
        yy, xx = sy + dy_, sx + dx_
        ok = (yy < sub.shape[0]) & (xx >= 0) & (xx < sub.shape[1])
        ok[ok] = sub[yy[ok], xx[ok]]
        a, b = idx[sy[ok], sx[ok]], idx[yy[ok], xx[ok]]
        d = np.linalg.norm(Pw[a] - Pw[b], axis=1) + 1e-4
        rows += [a, b]; cols += [b, a]; wts += [d, d]
    G = coo_matrix((np.concatenate(wts), (np.concatenate(rows), np.concatenate(cols))), shape=(len(sy),) * 2).tocsr()
    ncomp, lab = cv2.connectedComponents(sub.astype(np.uint8), connectivity=8)
    comp = lab[sy, sx]
    sources = []
    for c in range(1, ncomp):
        m = np.nonzero(comp == c)[0]
        if len(m) >= 20:
            sources.append(int(m[np.argmax(Pw[m, 1])]))
    dist = dijkstra(G, indices=sources, min_only=True) if sources else np.zeros(len(sy))
    dist = np.where(np.isfinite(dist), dist, 0.0)
    vmap = np.zeros(sub.shape, np.float64)
    vmap[sy, sx] = dist
    known = np.zeros(sub.shape, bool)
    known[sy, sx] = True
    vfull = cv2.resize(push_pull(vmap, known).astype(np.float32), (sub.shape[1] * step, sub.shape[0] * step),
                       interpolation=cv2.INTER_LINEAR)[:H, :W]
    _, r = heading(ctx.cam)
    gxs, gys = grid["fx"], grid["fy"]
    v = vfull[np.clip(gys.round().astype(int), 0, H - 1), np.clip(gxs.round().astype(int), 0, W - 1)]
    u = (grid["P"] - ctx.cpos) @ r
    flow_uv = np.stack([u.ravel(), v.ravel()], 1).astype(np.float32)
    # Tint: the painted water colours where HoMM3 shows water (spread a few px over the dilated rim), the median
    # painted river colour on the extension channels.
    paint = fd["paint"]
    hw = water[:TH, :TW]
    base = np.median(paint[hw], 0) if hw.any() else np.array([150.0, 170.0, 190.0])
    tint = np.empty((H, W, 3), np.uint8)
    tint[:] = np.clip(base, 0, 255).astype(np.uint8)
    if hw.any():
        from scipy.ndimage import distance_transform_edt

        known_w = np.zeros((H, W), bool)
        known_w[:TH, :TW] = hw
        src = np.zeros((H, W, 3), np.uint8)
        src[:TH, :TW] = paint
        dd, (iy, ix) = distance_transform_edt(~known_w, return_indices=True)
        near = (dd < 6) & (np.arange(H)[:, None] < TH) & (np.arange(W)[None, :] < TW)
        tint[near] = src[iy, ix][near]
    # Shore coordinate in the tint's alpha: signed px from the bank of the smoothed mask (the painted mask steps in
    # 1.8x pixels; a Gaussian of 2 px and a 0.5 threshold give a smooth bank), a = (sd + SHORE_OUT) / SHORE_RANGE.
    from scipy.ndimage import distance_transform_edt as _edt

    sm = cv2.GaussianBlur(water.astype(np.float32), (0, 0), 2.0) > 0.5
    sd = _edt(sm) - _edt(~sm)
    sd = cv2.GaussianBlur(sd.astype(np.float32), (0, 0), 1.0)
    shore = np.clip((sd + SHORE_OUT) / SHORE_RANGE * 255 + 0.5, 0, 255).astype(np.uint8)
    tint = np.dstack([tint, shore])
    return {"P": P, "n": n, "tris": tris, "flow_uv": flow_uv, "tint": tint, "sources": len(sources),
            "vMaxM": float(dist.max()) if len(dist) else 0.0, "vfull": vfull}


# ------------------------------------------------------------------------------------------------ sky
SKY_AZ, SKY_EL = (-62.0, 62.0), (-14.0, 48.0)


def sky_dome(ctx, fd: dict, dome_r: float) -> dict:
    """Camera-centred sphere cap. Texture (azimuth x elevation, 2 texels per frame px at the frame centre) sampled
    from the painted sky without blur; a direction outside the painted sky is mirrored into the town rect, and
    where the mirror lands on terrain it takes the nearest painted sky pixel above it in that column."""
    from scipy.ndimage import binary_erosion

    up = np.array([0.0, 1.0, 0.0])
    f, r = heading(ctx.cam)
    STW, STH = 4096, 2048
    az = np.radians(np.linspace(SKY_AZ[0], SKY_AZ[1], STW))
    el = np.radians(np.linspace(SKY_EL[1], SKY_EL[0], STH))
    sky_e = binary_erosion(np.isnan(fd["zh"]), np.ones((3, 3), bool), iterations=2)
    rows = np.where(sky_e, np.arange(TH)[:, None], -1)
    above = np.maximum.accumulate(rows, axis=0)
    first = np.where(sky_e.any(0), np.argmax(sky_e, axis=0), 0)
    pl = np.asarray(original().resize((TW * 2, TH * 2), Image.LANCZOS)).astype(np.float32)
    img = np.zeros((STH, STW, 3), np.float32)
    for r0 in range(0, STH, 256):
        E, A = np.meshgrid(el[r0:r0 + 256], az, indexing="ij")
        d = (np.cos(E)[..., None] * (np.cos(A)[..., None] * f + np.sin(A)[..., None] * r) + np.sin(E)[..., None] * up)
        px, py, _ = project(ctx.cam, ctx.cam["pos"] + d)
        mx, my = mirror_index(px, py)
        xi, yi = np.clip(mx.round().astype(int), 0, TW - 1), np.clip(my.round().astype(int), 0, TH - 1)
        ya = above[yi, xi]
        ya = np.where(ya < 0, first[xi], ya)
        sy_ = np.where(sky_e[yi, xi], my, ya.astype(np.float64))
        u = np.clip(mx * 2 + 0.5, 0, TW * 2 - 1.001).astype(np.float32)
        v = np.clip(sy_ * 2 + 0.5, 0, TH * 2 - 1.001).astype(np.float32)
        img[r0:r0 + 256] = cv2.remap(pl, u, v, cv2.INTER_LINEAR)
    img = np.clip(img, 0, 255).astype(np.uint8)
    GA, GE = 128, 64
    ga = np.radians(np.linspace(SKY_AZ[0], SKY_AZ[1], GA + 1))
    ge = np.radians(np.linspace(SKY_EL[1], SKY_EL[0], GE + 1))
    AA, EE = np.meshgrid(ga, ge)
    dd = (np.cos(EE)[..., None] * (np.cos(AA)[..., None] * f + np.sin(AA)[..., None] * r) + np.sin(EE)[..., None] * up)
    Pw = ctx.cam["pos"] + dd * dome_r
    # Texture row 0 = highest elevation = v 1 (the terrain's convention: frame row 0 = v 1).
    uv = np.stack([(AA - ga[0]) / (ga[-1] - ga[0]), (EE - ge[-1]) / (ge[0] - ge[-1])], -1).reshape(-1, 2)
    nx_ = GA + 1
    j, i = np.meshgrid(np.arange(GE), np.arange(GA), indexing="ij")
    a = (j * nx_ + i).ravel()
    tris = np.concatenate([np.stack([a, a + 1, a + nx_], 1), np.stack([a + 1, a + nx_ + 1, a + nx_], 1)])
    return {"P": Pw.reshape(-1, 3), "n": -dd.reshape(-1, 3), "uv": uv, "tris": tris, "img": img}
