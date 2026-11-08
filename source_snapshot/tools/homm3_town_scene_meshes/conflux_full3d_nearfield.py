"""Conflux full-3D, phase 5: the extension and the near field carry the most detail in the scene.

The 2026-09-27 in-game review of phase 4 (the user plays at 4096x2160): "there is still that cutoff point near the camera
and right edge of the screen where we used to have gaussian blur and the environment looks really blurry there", and
"close up geometry is generally expected to have the MOST detail, not the least". Measured cause: the extension albedo
was seamless crops of the 800x374 HoMM3 painting upscaled 2x and tiled in world space (soft by construction), a mirrored
copy of the painting was feathered along the frame rectangle (a straight smear at x = TOWN_W / y = TOWN_H), the whole
terrain was one 3840x2160 bake (1 texel per 4K screen pixel, magnified at the frame bottom), and nothing but the terrain
grid stood on the ground nearer than 8 m.

This module replaces all of that:
  * albedo    extension: the game's own terrain textures (conflux_full3d_detail.DETAIL_SOURCES, read-only UnityPy
              extracts with provenance) as FULL-COLOUR albedo, each normalised to mean 1 per channel, sampled top-down in
              world metres at three rotated scales mixed by world noise (tile, 2.37x tile, and 0.53x tile nearer than
              16 m), side-projected on slopes. The painting enters only as low-frequency colour L0: its albedo under a
              Gaussian of L0_SIGMA_PX inside the rect, and outside it per-class medians of the painting's own colour,
              pulled toward the painting's edge colour with an e-folding world distance SEAM_TONE_M. No painted crop is
              upscaled or tiled; no mirrored painting.
  * seam      the synthesis reaches into the HoMM3 rect on every ground class over SEAM_BLEND_M world metres (at least SEAM_BLEND_PX) from the seam,
              the edge of that band broken by world-space noise (SEAM_NOISE_M), so there is no line along the frame
              rectangle: the painted texels give way to the vanilla texture along a ragged world-space contour.
  * pieces    the terrain grid is split: Mesh_TerrainNear_0..3 (frame rows below NEAR_Y0, noise-jittered) baked at
              NEAR_SCALE texels per 1080p pixel and Mesh_TerrainRight (the right cliff/meadow) at RIGHT_SCALE, each with
              its own texture; Mesh_Terrain keeps MAIN_SCALE. The pieces share the grid's vertices, so no crack.
  * relief    in the extension near field the grid vertices move along their camera rays (screen registration and the
              frame edges are untouched) so the ground gains undulation and grassy mounds (RELIEF_*), none near water,
              buildings or on steep ground.
  * dressing  geometry nearer the camera than NEAR_DRESS_Z: grass tufts of camera-facing blades, flower clumps in the
              Conflux elemental palette (air white/blue, water blue, fire orange, earth yellow, a violet), pebbles along
              the banks and in the river edge, exposed roots at the near conifers; density per square metre and piece
              size both rise toward the camera. Merged into a few lit Mesh_ bins (one draw each). Kept off the building
              plots (and, for tall pieces, their screen corridor toward the camera), off water, and out of the bottom
              HUD_BOTTOM_PX (an assumption: the in-game town HUD layout was not read).
Proof tier: generated artifact / Unity-editor render at the reference camera (1080p and 3840x2160). Not in-game.
"""
from __future__ import annotations

import hashlib
import math

import cv2
import numpy as np
from PIL import Image

import conflux_full3d_detail as D
import conflux_full3d_env as E

W, H, TW, TH = E.W, E.H, E.TW, E.TH
SEED = 505

# --- texture pieces --------------------------------------------------------------------------------------------------
MAIN_SCALE = 2.0            # bake texels per 1080p px (the phase 1-4 terrain)
NEAR_Y0, NEAR_JITTER, NEAR_COLS, NEAR_SCALE = 560, 36, 4, 4.0
RIGHT_X0, RIGHT_Y0, RIGHT_JITTER, RIGHT_SCALE = 1320, 190, 40, 3.0

# --- albedo ----------------------------------------------------------------------------------------------------------
# Power on the mean-1 texture. grass1 is a low-contrast swatch: at 1.0 the near field rendered crisp but flat
# (|L - G1.5 L| 4.1 against the painted phase-4 grass 7.5), so the near layers are steepened.
SYN_CONTRAST = {"grass": 1.9, "dirt": 1.4, "rock": 1.2, "snow": 0.8}
SYN_SAMPLES = ((1.0, 0.0, 0.0), (2.37, 0.61, 0.29), (0.53, 1.13, 0.53))  # (tile multiple, rotation rad, offset)
ANISO_N = 8                    # anisotropic bake: at most this many lookups down a grazing texel's column
NEAR_OCTAVE_Z = (10.0, 16.0)   # m: the 0.53x octave fades in nearer than this
L0_SIGMA_PX = 10.0             # frame px: the painting's low-pass (its only role in the synthesised albedo)
SEAM_BLEND_M, SEAM_NOISE_M, SEAM_TONE_M = 3.5, 1.6, 5.0
# ... at least this many 1080p pixels wide where the ground is far (a 3.5 m band is only ~70 px at 50 m, and read as
# a vertical line down the right edge of the rect): band and tone distance scale with max(1, px * m_px / metres).
SEAM_BLEND_PX, SEAM_TONE_PX = 200, 260
EDGE_FILL_SIGMA = 24.0         # px: the rect edge colour's gap fill (rivers, sky) before it tones the extension
BANK_M, WET_M = 1.2, 0.35
VAR_GAIN, VAR_HUE = 0.30, 0.07  # world-noise luminance / hue variation of the synthesised ground

# --- relief ----------------------------------------------------------------------------------------------------------
RELIEF_AMP, RELIEF_BUMP, RELIEF_MOUND = 0.09, 0.03, 0.10   # raw metres
RELIEF_Z = (22.0, 32.0)        # fades out between these depths

# --- dressing --------------------------------------------------------------------------------------------------------
NEAR_DRESS_Z = 26.0
TUFT_FLOOR = 3.0               # tufts per m2 at least, beyond NEAR_DRESS_Z (the far meadow)
TUFT_Z = 60.0                  # grass tufts reach this far on synthesised ground (the right-edge meadow)
FLOWER_GAIN = 0.6              # flower albedo scale: at full value the lit heads read as glowing stars
HUD_BOTTOM_PX = 64
FLOWERS_LIN = {"earth_yellow": (0.86, 0.62, 0.08), "air_white": (0.82, 0.83, 0.78), "air_blue": (0.30, 0.48, 0.92),
               "water_blue": (0.10, 0.25, 0.80), "fire_orange": (0.90, 0.28, 0.04), "violet": (0.40, 0.18, 0.75)}
ATLAS_W, ATLAS_H, COL_PX = 512, 64, 12
N_GRASS_COLS = 32
FLOWER_COL0 = N_GRASS_COLS                 # flower palette columns follow the grass
STEM_COL = FLOWER_COL0 + len(FLOWERS_LIN)
BARK_COL = STEM_COL + 1                    # two bark columns


def _bil(tex, u, v):
    h, w = tex.shape[:2]
    x = np.mod(u, 1.0) * w - 0.5
    y = np.mod(v, 1.0) * h - 0.5
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx = (x - x0)[:, None].astype(np.float32)
    fy = (y - y0)[:, None].astype(np.float32)
    x0 %= w
    y0 %= h
    x1 = (x0 + 1) % w
    y1 = (y0 + 1) % h
    return ((tex[y0, x0] * (1 - fx) + tex[y0, x1] * fx) * (1 - fy) + (tex[y1, x0] * (1 - fx) + tex[y1, x1] * fx) * fy)


def _tri(mips, u, v, mip):
    out = np.zeros((len(u), 3), np.float32)
    mip = np.clip(np.broadcast_to(mip, u.shape), 0, len(mips) - 1.001)
    m0 = np.floor(mip).astype(np.int64)
    fr = (mip - m0).astype(np.float32)[:, None]
    for lv in np.unique(m0):
        s = m0 == lv
        out[s] = _bil(mips[lv], u[s], v[s]) * (1 - fr[s]) + _bil(mips[lv + 1], u[s], v[s]) * fr[s]
    return out


def _sample(img, x, y, interp=cv2.INTER_LINEAR):
    """Bilinear lookup of a frame-resolution map at float frame coordinates (any shape)."""
    shp = np.shape(x)
    out = D._remap(np.ascontiguousarray(img, np.float32), np.ravel(x).astype(np.float32), np.ravel(y).astype(np.float32))
    return out.reshape(shp + np.shape(img)[2:])


class Synth:
    """The vanilla terrain textures as full-colour, mean-1 albedo layers (DETAIL_SOURCES order)."""

    def __init__(self, det: D.Detail, cache):
        self.maps = {}
        self.prov = {}
        for k, (name, _w, tile, _s, _c) in D.DETAIL_SOURCES.items():
            t = E.srgb_to_lin(np.asarray(Image.open(cache / f"{name}.png").convert("RGB")).astype(np.float32) / 255)
            n = np.power(np.clip(t / t.reshape(-1, 3).mean(0), 0.05, 6.0), SYN_CONTRAST[k])
            n = (n / n.reshape(-1, 3).mean(0)).astype(np.float32)
            self.maps[k] = {"mips": D._mips(n, 7), "size": t.shape[0], "tile": tile}
            self.prov[k] = {"texture": name, **{kk: det.prov[name][kk] for kk in ("file", "pathId", "sha256")},
                            "tileM": tile, "contrast": SYN_CONTRAST[k]}

    def layer(self, li, k, P, Ns, foot, near):
        m = self.maps[k]
        T, s = m["tile"], m["size"]
        x, z = P[:, 0], P[:, 2]

        def top(mul, ang, off, sel=slice(None)):
            c, sn = math.cos(ang), math.sin(ang)
            tile = T * mul
            u = (c * x[sel] - sn * z[sel]) / tile + off
            v = -(sn * x[sel] + c * z[sel]) / tile + 0.7 * off
            return _tri(m["mips"], u, v, np.log2(np.maximum(foot[sel] * s / tile, 1e-9)))
        a = top(*SYN_SAMPLES[0])
        b = top(*SYN_SAMPLES[1])
        mx = E.smoothstep(0.38, 0.62, E.fbm(x, z, SEED + 11 + li, 3.3, 3)).astype(np.float32)[:, None]
        col = a * (1 - mx) + b * mx
        sel = np.nonzero(near > 0.01)[0]
        if len(sel):
            c_ = top(*SYN_SAMPLES[2], sel=sel)
            mn = (near[sel] * E.smoothstep(0.35, 0.65, E.fbm(x[sel], z[sel], SEED + 17 + li, 1.6, 2))).astype(np.float32)[:, None]
            col[sel] = col[sel] * (1 - mn) + c_ * mn
        ws = (1 - E.smoothstep(0.55, 0.8, Ns[:, 1])).astype(np.float32)
        sel = np.nonzero(ws > 0.01)[0]
        if len(sel):
            ax = np.abs(Ns[sel, 0]) ** 4
            az = np.abs(Ns[sel, 2]) ** 4
            tot = ax + az + 1e-6
            mip = np.log2(np.maximum(foot[sel] * s / T, 1e-9))
            y = P[sel, 1]
            side = (_tri(m["mips"], z[sel] / T, -y / T, mip) * (ax / tot)[:, None]
                    + _tri(m["mips"], x[sel] / T + 0.31, -y / T, mip) * (az / tot)[:, None])
            col[sel] = col[sel] * (1 - ws[sel, None]) + side * ws[sel, None]
        return col

    def colour(self, P, Ns, foot, zdep, wl, L0, wet):
        near = (1 - E.smoothstep(NEAR_OCTAVE_Z[0], NEAR_OCTAVE_Z[1], zdep)).astype(np.float32)
        M = np.zeros((len(P), 3), np.float32)
        wsum = np.zeros(len(P), np.float32)
        for li, k in enumerate(D.LAYERS):
            sel = np.nonzero(wl[:, li] > 0.01)[0]
            if len(sel) == 0:
                continue
            M[sel] += self.layer(li, k, P[sel], Ns[sel], foot[sel], near[sel]) * wl[sel, li, None]
            wsum[sel] += wl[sel, li]
        M = M / np.maximum(wsum, 1e-6)[:, None]
        x, z = P[:, 0], P[:, 2]
        g = 2 * E.fbm(x, z, SEED + 21, 4.5, 3) - 1
        d = 2 * E.fbm(x, z, SEED + 23, 7.0, 2) - 1
        gain = (1 + VAR_GAIN * g).astype(np.float32)[:, None]
        hue = np.stack([1 + VAR_HUE * d, 1 + 0.4 * VAR_HUE * d, 1 - 1.4 * VAR_HUE * d], -1).astype(np.float32)
        return L0 * M * gain * hue * (1 - 0.38 * wet)[:, None]


# ------------------------------------------------------------------------------------------------ frame state
def ext_classes(ctx, fd: dict, nf: np.ndarray, zfill: np.ndarray) -> dict:
    """Extension class weights (world: slope, height above the meadow, noise; the phase 1-4 extension classes) at
    frame resolution, and cls_f (argmax index into E.EXT_CLASSES in the extension, 255 in the rect / sky)."""
    cam, cpos = ctx.cam, ctx.cpos
    sky = np.isnan(fd["zs"])
    ys, xs = np.mgrid[0:H, 0:W]
    Pf = (cpos + E.rays(cam, xs.astype(np.float64), ys.astype(np.float64)) * zfill[..., None]).astype(np.float32)
    slope = np.degrees(np.arccos(np.clip(nf[..., 1], -1, 1)))
    ha = Pf[..., 1] - fd["heightmap"]["meadowHeight"]
    _, rad, _ = E.polar(cam, Pf[..., 0], Pf[..., 2])
    nz1 = E.fbm(Pf[..., 0], Pf[..., 2], 11, 6.0, 3)
    w_rock = E.smoothstep(30, 44, slope + (nz1 - 0.5) * 16) * E.smoothstep(1.5, 4.0, ha)
    w_snow = E.smoothstep(21, 28, ha + (nz1 - 0.5) * 6) * (1 - E.smoothstep(48, 62, slope))
    w_slope = E.smoothstep(0.8, 3.5, ha + (nz1 - 0.5) * 2.0) * (1 - w_rock) * (1 - w_snow)
    w_mead = np.clip(1 - w_rock - w_slope - w_snow, 0, 1)
    W4 = np.stack([w_mead, w_slope, w_rock, w_snow], -1).astype(np.float32)
    ext = np.ones((H, W), bool)
    ext[:TH, :TW] = False
    cls_f = np.full((H, W), 255, np.uint8)
    cls_f[ext & ~sky] = W4[ext & ~sky].argmax(-1)
    return {"Pf": Pf, "W4": W4, "w_near": (1 - E.smoothstep(22, 32, rad)).astype(np.float32), "cls_f": cls_f}


def prepare(ctx, fd: dict, X: dict, nf: np.ndarray, nf_s: np.ndarray, wts: np.ndarray, zfill: np.ndarray,
            excl: np.ndarray, det: D.Detail, cache) -> dict:
    """Frame-resolution maps the bakes and the relief share: L0, layer weights, seam distance, synthesis weight."""
    from scipy.ndimage import binary_dilation, distance_transform_edt
    from scipy.spatial import cKDTree

    zs, zh, water = fd["zs"], fd["zh"], fd["water"]
    cam = ctx.cam
    sky = np.isnan(zs)
    Pf, W4, w_near = X["Pf"], X["W4"], X["w_near"]
    w_mead, w_slope, w_rock, w_snow = (W4[..., i] for i in range(4))
    t = math.tan(math.radians(cam["fov"]) / 2)
    m_px = (2 * zfill * t / H).astype(np.float32)
    rect = np.zeros((H, W), bool)
    rect[:TH, :TW] = True
    ext = ~rect
    # Painting albedo at frame resolution (the painting / Hex/Lit irradiance, as the rect bake).
    Lf = E.light(nf, ctx.rig, ctx.sun)
    Lm = float(np.median(E.lum(Lf)))
    pl = E.srgb_to_lin(np.asarray(E.original().resize((TW, TH), Image.LANCZOS)).astype(np.float32) / 255)
    alb = np.zeros((H, W, 3), np.float32)
    alb[:TH, :TW] = pl / np.maximum(Lf[:TH, :TW], 0.18 * Lm)
    ground = rect & ~sky & ~water
    g = ground.astype(np.float32)
    L0r = cv2.GaussianBlur(alb * g[..., None], (0, 0), L0_SIGMA_PX) / (cv2.GaussianBlur(g, (0, 0), L0_SIGMA_PX)[..., None] + 1e-6)
    # Seam: world points along the bottom and right edges of the HoMM3 rect; world distance of every pixel to them.
    bx = np.arange(0, TW, 2)
    by = np.arange(0, TH, 2)
    sp = np.concatenate([Pf[TH - 1, bx][~sky[TH - 1, bx]], Pf[by, TW - 1][~sky[by, TW - 1]]])
    tree = cKDTree(sp[:, [0, 2]])
    dseam = tree.query(Pf.reshape(-1, 3)[:, [0, 2]], workers=-1)[0].reshape(H, W).astype(np.float32)
    # Class colours: medians of the painting's own low-passed albedo over the regions that show each class.
    def med(box):
        x0, y0, x1, y1 = box
        m = ground[y0:y1, x0:x1]
        return np.median(L0r[y0:y1, x0:x1][m], 0) if m.sum() > 50 else np.median(L0r[ground], 0)
    cc = {k: med(E.CROPS[k]) for k in E.CROPS}
    C = ((w_mead * w_near)[..., None] * cc["meadow_near"] + (w_mead * (1 - w_near))[..., None] * cc["meadow_mid"]
         + w_slope[..., None] * cc["slope_green"] + w_rock[..., None] * cc["rock"] + w_snow[..., None] * cc["snow"])
    C = C / np.maximum(W4.sum(-1), 1e-6)[..., None]
    # Edge colour: the rect's ground colour (water / sky gaps filled by a normalised Gaussian) at the pixel's
    # projection onto the rect, which is continuous. The nearest *ground* pixel (a first version) jumps where the
    # nearest pixel switches across a river mouth: a straight light/dark line ran down the near field at x ~ 388.
    Es = (cv2.GaussianBlur(L0r * g[..., None], (0, 0), EDGE_FILL_SIGMA)
          / (cv2.GaussianBlur(g, (0, 0), EDGE_FILL_SIGMA)[..., None] + 1e-6))
    Es = np.where((cv2.GaussianBlur(g, (0, 0), EDGE_FILL_SIGMA) > 1e-3)[..., None], Es, np.median(L0r[ground], 0))
    yy_, xx_ = np.mgrid[0:H, 0:W]
    edge = Es[np.minimum(yy_, TH - 1), np.minimum(xx_, TW - 1)]
    dn = dseam * (0.7 + 0.6 * E.fbm(Pf[..., 0], Pf[..., 2], SEED + 3, 4.0, 2))
    ws = np.exp(-dn / np.maximum(SEAM_TONE_M, SEAM_TONE_PX * m_px))[..., None]
    L0 = np.where(rect[..., None], L0r, C * (1 - ws) + edge * ws).astype(np.float32)
    L0 = cv2.GaussianBlur(L0, (0, 0), 3.0)
    # Layer weights: rect = the phase-3 splat (grass, dirt, rock, snow); extension = the world classes, bare-earth
    # patches, dirt banks. Water = river bed (dirt, wet).
    wd = (distance_transform_edt(~water) * m_px).astype(np.float32)
    bank = (1 - E.smoothstep(0.5 * BANK_M, BANK_M, wd)).astype(np.float32)
    patch = 0.35 * E.smoothstep(0.66, 0.74, E.fbm(Pf[..., 0], Pf[..., 2], SEED + 5, 2.5, 3))
    wx = np.stack([w_mead * (1 - patch) + 0.75 * w_slope, 0.25 * w_slope + patch * w_mead, w_rock, w_snow], -1)
    wx = np.stack([wx[..., 0] * (1 - bank), wx[..., 1] + bank * (wx[..., 0] + 0.5 * wx[..., 2]), wx[..., 2] * (1 - 0.5 * bank),
                   wx[..., 3]], -1)
    wr = wts / np.maximum(wts.sum(-1, keepdims=True), 1e-6)
    wr[wts.sum(-1) < 0.01] = (1, 0, 0, 0)
    wl = np.where(rect[..., None], wr, wx).astype(np.float32)
    wl[water] = (0, 1, 0, 0)
    wl = cv2.GaussianBlur(wl, (0, 0), 2.0)
    wl /= np.maximum(wl.sum(-1, keepdims=True), 1e-6)
    wet = np.where(water, 1.0, 1 - E.smoothstep(0.0, WET_M, wd)).astype(np.float32)
    # Synthesis weight: 1 in the extension; inside the rect it reaches SEAM_BLEND_M (noise-broken).
    nzs = 2 * E.fbm(Pf[..., 0], Pf[..., 2], SEED + 7, 2.2, 3) - 1
    # All ground classes ramp (rock and forest too: a grass/dirt-only ramp left a hard rock edge at x = TW).
    bs = np.maximum(1.0, SEAM_BLEND_PX * m_px / SEAM_BLEND_M)
    # The noise scales with the distance (0 at the seam itself): an additive noise term let w_syn fall to ~0.5 right
    # at the seam, i.e. a painting-vs-synthesis step exactly along x = TW.
    wsyn_r = (1 - E.smoothstep(0.0, SEAM_BLEND_M * bs, dseam * (1 + SEAM_NOISE_M / SEAM_BLEND_M * nzs))) * ~water
    w_syn = np.where(rect, wsyn_r, 1.0).astype(np.float32)
    w_syn = np.where(sky, 0, cv2.GaussianBlur(w_syn, (0, 0), 1.5)).astype(np.float32)
    # Relief weight (extension near field only, off water, buildings and steep ground).
    excl_d = binary_dilation(excl, np.ones((9, 9), bool))
    rel = (ext * E.smoothstep(0.5, 3.0, dseam) * E.smoothstep(0.8, 2.0, wd) * (1 - E.smoothstep(*RELIEF_Z, zfill))
           * E.smoothstep(0.75, 0.9, nf_s[..., 1]) * ~excl_d * ~sky).astype(np.float32)
    rel = cv2.GaussianBlur(rel, (0, 0), 4.0)
    # World step per frame pixel down the screen (the anisotropic bake's footprint along the view).
    dPy = np.linalg.norm(np.diff(Pf, axis=0), axis=-1)
    m_py = np.maximum(np.concatenate([dPy, dPy[-1:]], 0), m_px)
    m_py = np.where(sky | ~np.isfinite(m_py), m_px, np.minimum(m_py, 12 * m_px)).astype(np.float32)
    m_py = cv2.GaussianBlur(m_py, (0, 0), 1.0)
    return {"Pf": Pf, "m_px": m_px, "m_py": m_py, "zfill": zfill, "nf": nf, "nf_s": nf_s, "wts": wts, "L0": L0, "wl": wl, "wet": wet,
            "w_syn": w_syn, "dseam": dseam, "wd": wd, "rel": rel, "rect": rect, "sky": sky, "water": water, "zh": zh,
            "Lm": Lm, "cls_f": X["cls_f"], "alb_frame": np.where(rect[..., None], alb, L0).astype(np.float32), "classColours": {k: [round(float(c), 4) for c in v] for k, v in cc.items()},
            "synth": Synth(det, cache), "det": det, "W4share": {k: float(W4[..., i][ext & ~sky].sum())
                                                                 for i, k in enumerate(E.EXT_CLASSES)}}


def relief_height(x, z):
    return (RELIEF_AMP * (2 * E.fbm(x, z, SEED + 31, 2.4, 3) - 1) + RELIEF_BUMP * (2 * E.fbm(x, z, SEED + 37, 0.5, 2) - 1)
            + RELIEF_MOUND * E.smoothstep(0.6, 0.78, E.fbm(x, z, SEED + 41, 3.6, 2)) - 0.02)


def relief_dz(ctx, S: dict):
    """Callable for E.terrain_mesh(disp=...): depth offset along each vertex's camera ray that raises the ground by the
    relief height (screen position unchanged)."""
    def f(fx, fy, P):
        w = _sample(S["rel"], fx, fy)
        ry = E.rays(ctx.cam, fx, fy)[..., 1]
        h = relief_height(P[..., 0], P[..., 2])
        return np.where((w > 1e-3) & (ry < -0.05), w * h / np.minimum(ry, -0.05), 0.0)
    return f


SEAM_DEPTH_SIGMA, SEAM_DEPTH_PX, SEAM_DEPTH_TOL = 30.0, 70.0, 0.04


def seam_depth(zs: np.ndarray) -> np.ndarray:
    """The HoMM3 rect's depth (calibrated from the painting) and the extension's (the heightmap) meet with a kink:
    at x = TW the depth slope along a row jumps from about -0.06 to -0.02 m/px on the right cliff. The kink turned
    the terrain normals, and with them the Hex/Lit shading, into a vertical light/dark step exactly along the seam
    even where the albedo was continuous. Near the seam lines (Gaussian band SEAM_DEPTH_PX) the inverse depth is
    replaced by its normalised Gaussian average (SEAM_DEPTH_SIGMA px), only where that stays within SEAM_DEPTH_TOL
    of the original (never across an occlusion edge). Depth moves along each pixel's own ray: screen positions and
    texture registration are unchanged."""
    valid = ~np.isnan(zs)
    inv = np.where(valid, 1.0 / np.where(valid, zs, 1.0), 0.0).astype(np.float32)
    g = cv2.GaussianBlur(valid.astype(np.float32), (0, 0), SEAM_DEPTH_SIGMA)
    sm = cv2.GaussianBlur(inv, (0, 0), SEAM_DEPTH_SIGMA) / np.maximum(g, 1e-6)
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    dv = np.hypot(xs - TW, np.maximum(ys - TH, 0))          # to the right edge x = TW, 0 <= y <= TH
    dh = np.hypot(ys - TH, np.maximum(xs - TW, 0))          # to the bottom edge y = TH, 0 <= x <= TW
    d = np.minimum(dv, dh)
    ok = valid & (g > 0.9) & (np.abs(sm / np.maximum(inv, 1e-9) - 1) < SEAM_DEPTH_TOL)
    b = np.exp(-(d / SEAM_DEPTH_PX) ** 2) * ok
    inv2 = inv * (1 - b) + sm * b
    return np.where(valid, 1.0 / np.maximum(inv2, 1e-9), np.nan).astype(zs.dtype)


def frame_relief_depth(ctx, S: dict) -> np.ndarray:
    """Forward depth of the relieved ground at every frame pixel (placement of the dressing)."""
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float64)
    return (S["zfill"] + relief_dz(ctx, S)(xs, ys, S["Pf"].astype(np.float64))).astype(np.float32)


# ------------------------------------------------------------------------------------------------ bakes
def _paint_window(ctx, S, px, py):
    """Painting albedo (painting / Hex/Lit irradiance) at float frame coords (2-D arrays), sky rim filled inward."""
    src = np.asarray(E.original().convert("RGB")).astype(np.float32) / 255
    sh, sw = src.shape[:2]
    u = ((px + 0.5) * sw / TW - 0.5).astype(np.float32)
    v = ((py + 0.5) * sh / TH - 0.5).astype(np.float32)
    pl = E.srgb_to_lin(np.clip(cv2.remap(src, u, v, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT), 0, 1))
    sky = np.isnan(S["zh"])[np.clip(np.round(py).astype(int), 0, TH - 1), np.clip(np.round(px).astype(int), 0, TW - 1)]
    from scipy.ndimage import binary_dilation
    bad = binary_dilation(sky, np.ones((3, 3), bool), iterations=2)
    if bad.any() and (~bad).any():
        pl = E.fill_from_interior(pl, bad)
    n = _sample(S["nf"], px, py)
    n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-9
    return pl / np.maximum(E.light(n, ctx.rig, ctx.sun), 0.18 * S["Lm"])


def bake_window(ctx, S: dict, box, scale: float, skip=None, rows: int = 96) -> np.ndarray:
    """Linear albedo for the frame window box = (x0, y0, x1, y1) at `scale` texels per frame px: the painting (+ the
    phase-3 vanilla detail) inside the rect, the synthesised vanilla ground where w_syn > 0, blended by w_syn.
    skip(px, py) -> bool marks texels another piece owns (baked as flat L0 only)."""
    x0, y0, x1, y1 = box
    tw, th = int(round((x1 - x0) * scale)), int(round((y1 - y0) * scale))
    ty, tx = np.mgrid[0:th, 0:tw].astype(np.float64)
    px = x0 + (tx + 0.5) / scale - 0.5
    py = y0 + (ty + 0.5) / scale - 0.5
    cpx, cpy = np.clip(px, 0, W - 1), np.clip(py, 0, H - 1)
    out = _sample(S["L0"], cpx, cpy).astype(np.float32)
    wsyn = _sample(S["w_syn"], cpx, cpy).astype(np.float32)
    in_rect = (px < TW - 0.5) & (py < TH - 0.5)
    own = np.ones((th, tw), bool) if skip is None else ~skip(px, py)
    if in_rect.any():
        r = np.nonzero(in_rect.any(1))[0]
        c = np.nonzero(in_rect.any(0))[0]
        sl = (slice(r[0], r[-1] + 1), slice(c[0], c[-1] + 1))
        pw = _paint_window(ctx, S, np.clip(px[sl], 0, TW - 1), np.clip(py[sl], 0, TH - 1))
        blk = out[sl]
        blk[in_rect[sl]] = pw[in_rect[sl]]
        out[sl] = blk
        keep = in_rect & (wsyn < 0.999) & own
        out = D.apply_to_frame_texture(ctx, S["det"], out, x0, y0, scale, S["zfill"], S["nf_s"], S["wts"], keep=keep)
    syn_m = (wsyn > 1e-3) & own & ~_sample(S["sky"].astype(np.float32), cpx, cpy).astype(bool)
    t = math.tan(math.radians(ctx.cam["fov"]) / 2)
    Sy = S["synth"]
    for r0 in range(0, th, rows):
        r1 = min(th, r0 + rows)
        m = syn_m[r0:r1]
        if not m.any():
            continue
        qx, qy = cpx[r0:r1][m], cpy[r0:r1][m]

        def texel(qy_):
            z = _sample(S["zfill"], qx, qy_)
            P = ctx.cpos + E.rays(ctx.cam, qx, qy_) * z[:, None]
            Ns = _sample(S["nf_s"], qx, qy_)
            Ns /= np.linalg.norm(Ns, axis=-1, keepdims=True) + 1e-9
            view = ctx.cpos - P
            view /= np.linalg.norm(view, axis=-1, keepdims=True) + 1e-9
            return z, P, Ns, np.clip(np.abs((Ns * view).sum(-1)), 0.05, 1)
        z, P, Ns, cosv = texel(qy)
        base = (2 * z * t / H) / scale                       # world metres per texel across the screen
        along = _sample(S["m_py"], qx, qy) / scale           # ... and down the screen (the depth map's own step)
        wl = _sample(S["wl"], qx, qy)
        L0q, wetq = _sample(S["L0"], qx, qy), _sample(S["wet"], qx, qy)
        # Anisotropic filtering: a grazing texel covers `base` across and `along` down the screen. One isotropic
        # lookup (the geometric mean from the smoothed normal) aliased into horizontal streaks on the mid-distance
        # slopes, where along / base reaches 10. Texels with along > 1.5 base average n = ceil(along / base) (<= 
        # ANISO_N) lookups spread down their screen column, each at the footprint of its own sub-texel.
        n_s = np.clip(np.ceil(along / np.maximum(base, 1e-6)), 1, ANISO_N).astype(np.int32)
        n_s[along < 1.5 * base] = 1
        col = np.zeros((len(qx), 3), np.float32)
        one = n_s == 1
        if one.any():
            col[one] = Sy.colour(P[one], Ns[one], np.maximum(base, along)[one], z[one], wl[one], L0q[one], wetq[one])
        for n in np.unique(n_s[~one]):
            an = np.nonzero(n_s == n)[0]
            acc = np.zeros((len(an), 3), np.float32)
            fa = np.maximum(base[an], along[an] / n)
            for o in (np.arange(n) + 0.5) / n - 0.5:
                qa = qy[an] + o / scale
                za = _sample(S["zfill"], qx[an], qa)
                Pa = ctx.cpos + E.rays(ctx.cam, qx[an], qa) * za[:, None]
                acc += Sy.colour(Pa, Ns[an], fa, za, wl[an], L0q[an], wetq[an])
            col[an] = acc / n
        blk = out[r0:r1]
        w = wsyn[r0:r1][m][:, None]
        blk[m] = blk[m] * (1 - w) + col * w
        out[r0:r1] = blk
    mx = out.max(-1, keepdims=True)
    return np.where(mx > 0.95, out * 0.95 / np.maximum(mx, 1e-6), out).astype(np.float32)


def _near_boundary(x):
    return NEAR_Y0 + NEAR_JITTER * (2 * E.value_noise(np.asarray(x, np.float64), 0.0, SEED + 51, 70.0) - 1)


def _right_boundary(y):
    return RIGHT_X0 + RIGHT_JITTER * (2 * E.value_noise(np.asarray(y, np.float64), 0.0, SEED + 53, 60.0) - 1)


def piece_of(px, py):
    """-1 main terrain, 0..NEAR_COLS-1 near pieces, NEAR_COLS the right piece (frame coords, arrays)."""
    px, py = np.asarray(px, np.float64), np.asarray(py, np.float64)
    out = np.full(px.shape, -1, np.int64)
    near = py > _near_boundary(px)
    out[near] = np.clip((px[near] // (W / NEAR_COLS)).astype(np.int64), 0, NEAR_COLS - 1)
    right = ~near & (py > RIGHT_Y0) & (px > _right_boundary(py))
    out[right] = NEAR_COLS
    return out


def split_terrain(grid: dict) -> dict:
    """Triangles of the terrain grid per piece, and each piece's frame window (its vertices' extent + a margin)."""
    fx, fy = grid["fx"].ravel(), grid["fy"].ravel()
    tris = grid["tris"]
    cx, cy = fx[tris].mean(1), fy[tris].mean(1)
    pid = piece_of(cx, cy)
    pieces = {}
    for k in range(-1, NEAR_COLS + 1):
        t = tris[pid == k]
        if len(t) == 0:
            continue
        vx, vy = fx[np.unique(t)], fy[np.unique(t)]
        box = (max(0, math.floor(vx.min()) - 2), max(0, math.floor(vy.min()) - 2),
               min(W, math.ceil(vx.max()) + 3), min(H, math.ceil(vy.max()) + 3))
        name = "Mesh_Terrain" if k < 0 else ("Mesh_TerrainRight" if k == NEAR_COLS else f"Mesh_TerrainNear_{k}")
        scale = MAIN_SCALE if k < 0 else (RIGHT_SCALE if k == NEAR_COLS else NEAR_SCALE)
        pieces[name] = {"tris": t, "box": (0, 0, W, H) if k < 0 else box, "scale": scale, "id": k}
    return pieces


def piece_mesh(grid: dict, piece: dict):
    """Vertex subset, remapped triangles and the piece's own UVs (texel-exact for its window)."""
    t = piece["tris"]
    used = np.unique(t)
    remap = np.full(grid["fx"].size, -1, np.int64)
    remap[used] = np.arange(len(used))
    fx, fy = grid["fx"].ravel()[used], grid["fy"].ravel()[used]
    if piece["id"] < 0:
        uv = grid["uv"][used]
    else:
        x0, y0, x1, y1 = piece["box"]
        s = piece["scale"]
        tw, th = round((x1 - x0) * s), round((y1 - y0) * s)
        uv = np.clip(np.stack([(fx - x0 + 0.5) * s / tw, 1 - (fy - y0 + 0.5) * s / th], -1), 0, 1)
    return used, remap[t], uv.astype(np.float32)


# ------------------------------------------------------------------------------------------------ dressing
def winding_sign(grid: dict, ctx) -> float:
    """Sign of (winding normal . surface normal) of the terrain's own triangles (the renderer's front-face rule as
    the terrain uses it); every dressing triangle is wound the same way against its outward / camera-facing normal."""
    P = grid["P"].reshape(-1, 3)
    n = grid["n"].reshape(-1, 3)
    t = grid["tris"][:: max(1, len(grid["tris"]) // 5000)]
    gn = np.cross(P[t[:, 1]] - P[t[:, 0]], P[t[:, 2]] - P[t[:, 0]])
    return float(np.sign(np.median(np.sign((gn * n[t[:, 0]]).sum(-1)))))


def orient(v, f, want_n, sgn):
    gn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    flip = (gn * want_n).sum(-1) * sgn < 0
    f = f.copy()
    f[flip] = f[flip][:, [0, 2, 1]]
    return f


def sample_sites(ctx, S, zmap, mask, rho, rng):
    """Poisson-disc-free Bernoulli sampling per frame pixel: rho(z) sites per square metre of ground. Returns frame
    coords, world points on the relieved ground, and depth."""
    t = math.tan(math.radians(ctx.cam["fov"]) / 2)
    m_px = 2 * zmap * t / H
    Pf = S["Pf"]
    view = ctx.cpos - Pf
    view /= np.linalg.norm(view, axis=-1, keepdims=True) + 1e-9
    cosi = np.clip(np.abs((S["nf_s"] * view).sum(-1)), 0.12, 1)
    p = np.where(mask, rho(zmap) * m_px * m_px / cosi, 0)
    ys, xs = np.nonzero(rng.random(p.shape) < p)
    fx = xs + rng.random(len(xs)) - 0.5
    fy = ys + rng.random(len(ys)) - 0.5
    z = _sample(zmap, fx, fy).astype(np.float64)
    P = ctx.cpos + E.rays(ctx.cam, fx, fy) * z[:, None]
    return fx, fy, P, z


def near_gain(z):
    """Piece size multiplier: larger individual pieces nearer the camera."""
    return 1 + 0.6 * E.smoothstep(18.0, 9.0, z)


def _col_u(col):
    return (col * COL_PX + COL_PX / 2) / ATLAS_W


def tufts(ctx, P, z, cols, rng):
    """Camera-facing grass blades, clumped per site: (v, n, uv, f, want)."""
    up = np.array([0.0, 1.0, 0.0])
    n_sites = len(P)
    near = E.smoothstep(22.0, 9.0, z)
    nb = (8 + np.round(7 * near)).astype(int)
    site = np.repeat(np.arange(n_sites), nb)
    nbl = len(site)
    h0 = rng.uniform(0.10, 0.20, n_sites) * near_gain(z)
    tc = ctx.cpos - P
    tc[:, 1] = 0
    tc /= np.linalg.norm(tc, axis=-1, keepdims=True) + 1e-9
    ang = rng.uniform(0, 2 * np.pi, nbl)
    rr = 0.35 * h0[site] * np.sqrt(rng.random(nbl))
    off = np.stack([np.cos(ang) * rr, np.zeros(nbl), np.sin(ang) * rr], -1)
    base = P[site] + off - up * 0.01
    yaw = rng.uniform(-0.6, 0.6, nbl)
    tcs = tc[site]
    side0 = np.cross(up, tcs)
    side = side0 * np.cos(yaw)[:, None] + tcs * np.sin(yaw)[:, None]
    lean_dir = np.stack([np.cos(ang), np.zeros(nbl), np.sin(ang)], -1) + rng.normal(0, 0.35, (nbl, 3)) * [1, 0, 1]
    lean_dir /= np.linalg.norm(lean_dir, axis=-1, keepdims=True) + 1e-9
    lean = rng.uniform(0.2, 0.6, nbl)
    h = h0[site] * rng.uniform(0.6, 1.1, nbl)
    w = h * rng.uniform(0.10, 0.16, nbl)
    ts = np.array([0.0, 0.45, 0.8, 1.0])
    vs, uvs = [], []
    for j, tt in enumerate(ts):
        c = base + up * (h * tt * (1 - 0.25 * lean * tt))[:, None] + lean_dir * (h * lean * tt * tt)[:, None]
        if j < 3:
            half = (w * (1 - tt) ** 0.9 / 2)[:, None]
            vs += [c - side * half, c + side * half]
            uvs += [tt, tt]
        else:
            vs += [c]
            uvs += [tt]
    V = np.stack(vs, 1)  # (nbl, 7, 3)
    nrm = up * 0.6 + tcs * 0.4 + lean_dir * 0.15
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    u = _col_u(cols[site])
    UV = np.stack([np.repeat(u[:, None], 7, 1), np.broadcast_to(np.array(uvs) * 0.94 + 0.03, (nbl, 7))], -1)
    ft = np.array([[0, 1, 2], [1, 3, 2], [2, 3, 4], [3, 5, 4], [4, 5, 6]])
    F = (ft[None] + 7 * np.arange(nbl)[:, None, None]).reshape(-1, 3)
    want = np.repeat(tcs + up * 0.2, 5, axis=0)
    return V.reshape(-1, 3), np.repeat(nrm, 7, axis=0), UV.reshape(-1, 2), F, want


def flowers(ctx, P, z, col_of_clump, stem_col, rng):
    """Flower clumps: a thin stem blade and a five-lobed rounded head facing the camera and the sky (a first
    deep five-point star head read as sparkles, not flowers)."""
    up = np.array([0.0, 1.0, 0.0])
    n_cl = len(P)
    k = rng.integers(3, 7, n_cl)
    site = np.repeat(np.arange(n_cl), k)
    nf = len(site)
    g = near_gain(z)[site]
    tc = ctx.cpos - P[site]
    tc[:, 1] = 0
    tc /= np.linalg.norm(tc, axis=-1, keepdims=True) + 1e-9
    ang = rng.uniform(0, 2 * np.pi, nf)
    rr = 0.12 * g * np.sqrt(rng.random(nf))
    base = P[site] + np.stack([np.cos(ang) * rr, np.zeros(nf), np.sin(ang) * rr], -1) - up * 0.01
    h = rng.uniform(0.12, 0.26, nf) * g
    side = np.cross(up, tc)
    lean = rng.normal(0, 0.12, (nf, 1)) * side
    top = base + up * h[:, None] + lean * h[:, None]
    ws = (0.012 * g)[:, None]
    sv = np.stack([base - side * ws, base + side * ws, (base + top) / 2 - side * ws * 0.6, (base + top) / 2 + side * ws * 0.6,
                   top], 1)
    s_uv = np.stack([np.full((nf, 5), _col_u(stem_col)), np.broadcast_to([0.05, 0.05, 0.5, 0.5, 0.9], (nf, 5))], -1)
    s_f = np.array([[0, 1, 2], [1, 3, 2], [2, 3, 4]])
    # head
    nh = up * 0.55 + tc * 0.45
    nh /= np.linalg.norm(nh, axis=-1, keepdims=True)
    e1 = side
    e2 = np.cross(nh, e1)
    rh = rng.uniform(0.016, 0.028, nf) * g
    a = np.linspace(0, 2 * np.pi, 11)[:-1] + rng.uniform(0, 1, (nf, 1))
    rad = np.where(np.arange(10) % 2 == 0, 1.0, 0.72)[None] * rh[:, None]  # five shallow lobes: a round head
    rim = top[:, None] + (np.cos(a) * rad)[..., None] * e1[:, None] + (np.sin(a) * rad)[..., None] * e2[:, None]
    hv = np.concatenate([top[:, None] + nh[:, None] * 0.004, rim], 1)  # (nf, 11, 3)
    cu = _col_u(col_of_clump[site])
    h_uv = np.stack([np.repeat(cu[:, None], 11, 1), np.concatenate([np.full((nf, 1), 0.97), np.full((nf, 10), 0.62)], 1)], -1)
    h_f = np.stack([np.zeros(10, int), 1 + np.arange(10), 1 + (np.arange(10) + 1) % 10], -1)
    V = np.concatenate([sv, hv], 1)  # (nf, 16, 3)
    UV = np.concatenate([s_uv, h_uv], 1)
    N = np.concatenate([np.repeat((up * 0.6 + tc * 0.4)[:, None], 5, 1), np.repeat(nh[:, None], 11, 1)], 1)
    F = np.concatenate([s_f, h_f + 5], 0)
    FF = (F[None] + 16 * np.arange(nf)[:, None, None]).reshape(-1, 3)
    want = np.concatenate([np.repeat(tc[:, None], 3, 1), np.repeat(nh[:, None], 10, 1)], 1).reshape(-1, 3)
    return V.reshape(-1, 3), (N / np.linalg.norm(N, axis=-1, keepdims=True)).reshape(-1, 3), UV.reshape(-1, 2), FF, want


def _icosphere(level: int = 1):
    t = (1 + 5 ** 0.5) / 2
    v = np.array([[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
                  [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]], np.float64)
    f = np.array([[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6],
                  [7, 1, 8], [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5], [2, 4, 11], [6, 2, 10],
                  [8, 6, 7], [9, 8, 1]])
    v = list(v / np.linalg.norm(v, axis=1, keepdims=True))
    cache = {}

    def mid(a, b):
        key = (min(a, b), max(a, b))
        if key not in cache:
            m = (v[a] + v[b]) / 2
            v.append(m / np.linalg.norm(m))
            cache[key] = len(v) - 1
        return cache[key]
    for _ in range(level):
        nf = []
        for a, b, c in f:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            nf += [[a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]]
        f = np.array(nf)
        cache.clear()
    return np.array(v), f


def pebbles(ctx, P, z, r0, rng, sink=0.35, level=1, rough=0.18, flat=(0.45, 0.7)):
    """Noise-deformed flattened icospheres, UVs projected along the fixed view into four pebble swatches."""
    iv, ifc = _icosphere(level)
    n = len(P)
    r = r0 * near_gain(z)
    scl = np.stack([rng.uniform(0.8, 1.25, n), rng.uniform(*flat, n), rng.uniform(0.8, 1.25, n)], -1) * r[:, None]
    yaw = rng.uniform(0, 2 * np.pi, n)
    # Smooth lumps (a few random dents per stone, not per-vertex spikes) plus a little per-vertex grain.
    dirs = rng.normal(size=(n, 5, 3))
    dirs /= np.linalg.norm(dirs, axis=-1, keepdims=True)
    lump = (np.clip(np.einsum("vk,nsk->nvs", iv, dirs), 0, 1) ** 3 * rng.uniform(-1, 1, (n, 1, 5))).sum(-1)
    jit = 1 + rough * lump + 0.04 * (rng.random((n, len(iv))) - 0.5)
    lv = iv[None] * jit[..., None] * scl[:, None]
    c, s = np.cos(yaw)[:, None], np.sin(yaw)[:, None]
    lv = np.stack([lv[..., 0] * c - lv[..., 2] * s, lv[..., 1], lv[..., 0] * s + lv[..., 2] * c], -1)
    ctr = P + np.array([0, 1.0, 0]) * (scl[:, 1] * (1 - 2 * sink))[:, None]
    V = ctr[:, None] + lv
    F = (ifc[None] + len(iv) * np.arange(n)[:, None, None]).reshape(-1, 3)
    Vf = V.reshape(-1, 3)
    fn = np.cross(Vf[F[:, 1]] - Vf[F[:, 0]], Vf[F[:, 2]] - Vf[F[:, 0]])
    cen = np.repeat(ctr, len(ifc), axis=0)
    outward = Vf[F].mean(1) - cen
    fn *= np.sign((fn * outward).sum(-1))[:, None]
    N = np.zeros_like(Vf)
    for j in range(3):
        np.add.at(N, F[:, j], fn)
    N /= np.linalg.norm(N, axis=-1, keepdims=True) + 1e-12
    right, upc = np.asarray(ctx.cam["right"]), np.asarray(ctx.cam["up"])
    q = rng.integers(0, 4, n)
    qu, qv = (q % 2) * 0.5, (q // 2) * 0.5
    rel = V - ctr[:, None]
    u = qu[:, None] + 0.25 + 0.2 * (rel @ right) / r[:, None]
    v = qv[:, None] + 0.25 + 0.2 * (rel @ upc) / r[:, None]
    UV = np.stack([u, v], -1).reshape(-1, 2)
    return Vf, N, UV, F, outward


def roots(ctx, bases, rng):
    """Exposed roots at conifer bases: tapering tubes from inside the trunk arcing into the ground."""
    up = np.array([0.0, 1.0, 0.0])
    Vs, Ns, UVs, Fs, Ws = [], [], [], [], []
    off = 0
    ring = 6
    ts = np.linspace(0, 1, 6)
    for b, hgt in bases:
        for _ in range(int(rng.integers(3, 6))):
            a = rng.uniform(0, 2 * np.pi)
            d = np.array([math.cos(a), 0, math.sin(a)])
            L = hgt * rng.uniform(0.07, 0.12)
            r0 = hgt * rng.uniform(0.009, 0.014)
            side = np.cross(up, d)
            for ti, t in enumerate(ts):
                c = b + d * (0.01 * hgt + L * t) + up * (0.025 * hgt * (1 - t) ** 2 - 0.015 * hgt * t)
                tang = d * L + up * (-0.12 * hgt * (1 - t) - 0.02 * hgt)
                tang /= np.linalg.norm(tang)
                e2 = np.cross(tang, side)
                rr = r0 * (1 - 0.75 * t)
                for k in range(ring):
                    th = 2 * np.pi * k / ring
                    nn = side * math.cos(th) + e2 * math.sin(th)
                    Vs.append(c + nn * rr)
                    Ns.append(nn)
                    UVs.append((_col_u(BARK_COL + (k % 2)), 0.25 + 0.5 * (0.5 + 0.5 * math.sin(th))))
            for ti in range(len(ts) - 1):
                for k in range(ring):
                    a0 = off + ti * ring + k
                    a1 = off + ti * ring + (k + 1) % ring
                    b0, b1 = a0 + ring, a1 + ring
                    Fs += [[a0, a1, b0], [a1, b1, b0]]
                    Ws += [Ns[a0] + Ns[a1], Ns[a1] + Ns[b1]]
            off += len(ts) * ring
    if not Vs:
        return None
    return np.array(Vs), np.array(Ns), np.array(UVs, np.float64), np.array(Fs), np.array(Ws)


def atlas(grass_cols, stem, bark) -> np.ndarray:
    """sRGB uint8 ATLAS_H x ATLAS_W: 32 grass columns (base AO -> sunlit tip), the flower palette, stem, two barks."""
    img = np.zeros((ATLAS_H, ATLAS_W, 3), np.float32)
    v = 1 - (np.arange(ATLAS_H) + 0.5) / ATLAS_H  # UV v per image row (v = 1 at the top row)
    def col(i, lo_rgb, hi_rgb, curve):
        g = curve(v)[:, None]
        img[:, i * COL_PX:(i + 1) * COL_PX] = (np.asarray(lo_rgb) * (1 - g) + np.asarray(hi_rgb) * g)[:, None, :]
    for i, c in enumerate(grass_cols):
        c = np.asarray(c)
        col(i, c * 0.42, c * np.array([1.22, 1.20, 0.92]), lambda x: np.clip(x, 0, 1) ** 0.8)
    for j, (k, c) in enumerate(FLOWERS_LIN.items()):
        c = np.asarray(c)
        c = c * FLOWER_GAIN
        col(FLOWER_COL0 + j, c * 0.6, c, lambda x: E.smoothstep(0.55, 1.0, x))
    col(STEM_COL, stem * 0.45, stem * 0.9, lambda x: x)
    col(BARK_COL, bark * 0.3, bark * 0.6, lambda x: x)      # roots sit in the trunk's shade: darker than the bark
    col(BARK_COL + 1, bark * 0.22, bark * 0.5, lambda x: x)
    img[:, (BARK_COL + 2) * COL_PX:] = img[:, (BARK_COL + 1) * COL_PX:(BARK_COL + 2) * COL_PX].mean(1, keepdims=True)
    return (E.lin_to_srgb(np.clip(img, 0, 0.95)) * 255 + 0.5).astype(np.uint8)


def pebble_texture(cache, tint_a, tint_b) -> np.ndarray:
    """256x256 sRGB: four 128 px swatches cut from the vanilla rock texture (512_6_dirt_rock4_diffuse), each
    normalised to mean 1 and tinted with the painting's rock / bank colours."""
    src = E.srgb_to_lin(np.asarray(Image.open(cache / "512_6_dirt_rock4_diffuse.png").convert("RGB")).astype(np.float32) / 255)
    out = np.zeros((256, 256, 3), np.float32)
    for q, (x0, y0, tint) in enumerate(((40, 60, tint_a), (300, 90, tint_b), (120, 330, tint_b), (330, 320, tint_a))):
        sw = src[y0:y0 + 128, x0:x0 + 128]
        sw = sw / sw.reshape(-1, 3).mean(0)
        out[(q // 2) * 128:(q // 2 + 1) * 128, (q % 2) * 128:(q % 2 + 1) * 128] = sw * np.asarray(tint)
    out = out[::-1]  # swatch q sits at UV (q % 2, q // 2) * 0.5 with v = 0 at the bottom row
    return (E.lin_to_srgb(np.clip(out, 0, 0.95)) * 255 + 0.5).astype(np.uint8)


def kmeans_palette(cols: np.ndarray, k: int, rng) -> tuple[np.ndarray, np.ndarray]:
    data = np.asarray(cols, np.float32)
    if len(data) > 60000:
        data = data[rng.choice(len(data), 60000, replace=False)]
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-4)
    cv2.setRNGSeed(SEED)
    _c, _l, centers = cv2.kmeans(data, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    order = np.argsort(E.lum(centers))
    centers = centers[order]
    d = ((np.asarray(cols, np.float32)[:, None] - centers[None]) ** 2).sum(-1)
    return centers, d.argmin(1)


def sha(path) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def density_after(ctx, S: dict, dens_detail: np.ndarray, scale_map: np.ndarray) -> np.ndarray:
    """Texels per 1080p screen pixel the terrain now shows: where synthesised, the vanilla textures' own texels per
    pixel (their tile, the near octave included), elsewhere the phase-3 detail density; both capped by the bake's
    texels per pixel of the piece that covers the pixel (scale_map)."""
    zf = S["zfill"]
    view = ctx.cpos - S["Pf"]
    view /= np.linalg.norm(view, axis=-1, keepdims=True) + 1e-9
    cosv = np.clip(np.abs((S["nf_s"] * view).sum(-1)), 0.1, 1)
    foot = S["m_px"] / np.sqrt(cosv)
    near = 1 - E.smoothstep(NEAR_OCTAVE_Z[0], NEAR_OCTAVE_Z[1], zf)
    syn = np.zeros_like(zf)
    for li, k in enumerate(D.LAYERS):
        m = S["synth"].maps[k]
        per_m = m["size"] / m["tile"] * (1 + near * (1 / SYN_SAMPLES[2][0] - 1) * 0.5)
        syn += S["wl"][..., li] * foot * per_m
    d = np.where(S["w_syn"] > 0.5, syn, dens_detail)
    return np.where(S["sky"], 0, np.minimum(d, scale_map)).astype(np.float32)
