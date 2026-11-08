"""Phoenix fire look lab (CPU): lighting + VFX candidates composited against CPHX.DEF.

Inputs (all copies / regenerable; the build output is never modified):
- artifacts/homm3_def_retarget/h3_phoenix/h3_phoenix_def_retarget.glb   (read only: albedo, rest mesh, UVs)
- work/views/sprite_fNNN.npz  tools/homm3_prebake/render_passes.py on work/phoenix_copy.blend (--front=-y, ss 2)
- work/mesh1x/bones.json      tools/homm3_vfx/render_mesh_frames.py (bone heads projected to DEF px)
- evidence/fire_motion.json   phoenix_fire_motion.py

Model (static read of Hex/Lit, see docs/homm3_vfx_experiments.md): rgb = albedo * (sun*shadowedLambert + ambient)
(sand arena) + URP point light(s) = colour*I*saturate(1-(d^2/r^2)^2)^2/d^2*saturate(N.L). The point-light term uses a
flat-depth approximation (every pixel on the camera plane through the unit), so it is a CPU estimate, not a render.

Layers built (names follow the unit-look spec, tools/homm3_unit_look/units/h3_phoenix.json):
- lighting grade  : exposure/gamma/sat/wb grade fitted to the DEF body minus its hot core (idle views)
- fire_core glow  : steady baked glow on a UV mask around the torso axis (lighting.bakedGlow, light 'fire_core')
- fire_boil       : uvAtlas, 8 stepped cells: the look texture with its fire streaks re-rolled per DEF frame
- fire_fringe     : defFlipbook, DEF thin-flame + ember pixels outside the mesh silhouette (literal)
- fire_crest      : defFlipbook, DEF crest (top 30 % of the silhouette) drawn BEHIND the body
- fire_tongues    : particles (procedural): DEF-cut tongue strips re-rolled per frame on the mesh's top edges
- breath / hit_sparks / death_burn : DEF-ripped event flipbooks
- fire_flicker    : effectLight, stepped intensity per DEF frame fitted to the DEF body mean-L rise

Candidates: C0 raw | C1 look | C2 look+boil | C3 C2+fringe+crest+events | C4 C2+tongues+events |
            C5 C3+flicker light | C6 C4+flicker light

    python tools/homm3_vfx/phoenix_fire_lab.py            (all stages)

Outputs: artifacts/homm3_vfx_experiments/phoenix/lab/ (textures, flipbook sheets, cells.json, light curves,
frames/<cand>/<clip>_NN.png, lab_report.json). Proof tier: generated artifact (numpy relight + 2D composite).
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage, optimize

HERE = Path(__file__).parent
ROOT = HERE.resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools/homm3_prebake"))
import h3def  # noqa: E402
import prebake_lab as pl  # noqa: E402
import phoenix_fire_motion as fm  # noqa: E402
from glb_io import Glb  # noqa: E402
from oceanid_water_lab import rasterise, value_noise3, dilate_into  # noqa: E402

UNIT = "h3_phoenix"
GLB = ROOT / f"artifacts/homm3_def_retarget/{UNIT}/{UNIT}_def_retarget.glb"
FRAMES_JSON = ROOT / f"artifacts/homm3_def_retarget/{UNIT}/{UNIT}_def_retarget.blend.frames.json"
BASE = ROOT / "artifacts/homm3_vfx_experiments/phoenix"
WORK = BASE / "work"
LAB = BASE / "lab"
PPU = 111.3700795884412          # SpriteCam px per unit (1x)
TEX = 1024                       # lab texture size (cells, masks)
SS = 2
CLIPS = {  # GLB clip -> (DEF group, master frames 1-based)
    "Unit_Idle": (2, list(range(1, 9))),
    "Unit_Move": (0, list(range(12, 18))),
    "Unit_Hitted": (3, list(range(32, 38))),
    "Unit_AttackFront": (12, list(range(49, 61))),
    "Unit_Death": (5, list(range(62, 69))),
}
CANDS = ["C0_raw", "C1_look", "C2_boil", "C3_defflip", "C4_tongues", "C5_defflip_light", "C6_tongues_light"]
GLOW_RGB = np.array([1.0, 0.72, 0.25], np.float32)  # sRGB hot yellow; saturated so the bluish ambient keeps it warm
LIGHT_RGB = np.array([1.0, 0.72, 0.36], np.float32)  # sRGB fire light
LIGHT_RANGE = 3.0
GLOW_STRENGTH = 1.0   # authored: a hue-preserving albedo lift (Hex/Lit cannot emit; see the report)
FIRE_FLOOR = 0.45     # fire light intensity the grade is fitted under (the idle mean of the per-frame fit)
SPINE_GLTF = (np.array([0, 0.42, 0.0]), np.array([0, 0.90, 0.12]))  # Hips -> Neck, glTF (y up, +z = beak side)


# ------------------------------------------------------------------ inputs
def def_frames():
    d = h3def.read_def("cphx.def")
    out = {}
    for clip, (g, _) in CLIPS.items():
        fr = d.groups[g]
        out[clip] = {"rgba": [fm.frame_rgba(f, d.palette) for f in fr], "names": [f.name for f in fr]}
    return d, out


def load_views():
    meta = json.loads((WORK / "views/views_meta.json").read_text())
    views = {}
    for clip, (_, mfr) in CLIPS.items():
        views[clip] = []
        for f in mfr:
            v = dict(np.load(WORK / f"views/sprite_f{f:03d}.npz"))
            v["meta"] = meta["views"][f"sprite_f{f:03d}"]
            views[clip].append(v)
    return views


def bones():
    b = json.loads((WORK / "mesh1x/bones.json").read_text())
    return b["frames"]


def load_albedo():
    g = Glb(GLB)
    im = g.image(g.base_color_image_index()).convert("RGB").resize((TEX, TEX), Image.LANCZOS)
    return pl.srgb_to_lin(np.asarray(im, np.float32) / 255.0)


def rest_raster():
    p = WORK / f"rest_raster_{TEX}.npz"
    if p.exists():
        z = np.load(p)
        return z["pos"], z["cov"]
    g = Glb(GLB)
    pr = g.json["meshes"][0]["primitives"][0]
    P = g.accessor(pr["attributes"]["POSITION"]).astype(np.float64)
    UV = g.accessor(pr["attributes"]["TEXCOORD_0"]).astype(np.float64)
    I = g.accessor(pr["indices"]).astype(np.int64).reshape(-1, 3)
    pos, cov = rasterise(P, UV, I, np.ones(len(I), bool), TEX)
    pos = dilate_into(pos, cov, pos)
    np.savez_compressed(p, pos=pos, cov=cov)
    return pos, cov


# ------------------------------------------------------------------ relight
def light_factor(v):
    return pl.runtime_light(v, "sand")


def cam_up(meta):
    r, f = np.array(meta["camRight"]), np.array(meta["camForward"])
    return np.cross(r, f)


def point_light_term(v, anchor_px, toward_cam_u, intensity):
    """Flat-depth URP point light (linear rgb, before albedo), at supersampled resolution."""
    if intensity <= 0:
        return None
    H, W = v["alpha"].shape
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    r, f = np.array(v["meta"]["camRight"], np.float32), np.array(v["meta"]["camForward"], np.float32)
    u = cam_up(v["meta"]).astype(np.float32)
    dx = (anchor_px[0] - (xs + 0.5) / SS) / PPU
    dy = -(anchor_px[1] - (ys + 0.5) / SS) / PPU
    vec = dx[..., None] * r + dy[..., None] * u - f * toward_cam_u
    d2 = np.maximum((vec ** 2).sum(-1), 1e-4)
    ldir = vec / np.sqrt(d2)[..., None]
    ndl = np.clip((v["normal"] * ldir).sum(-1), 0, 1)
    att = np.clip(1 - (d2 / LIGHT_RANGE ** 2) ** 2, 0, 1) ** 2 / d2
    return (att * ndl)[..., None] * pl.srgb_to_lin(LIGHT_RGB) * intensity


def render(tex_lin, v, light=None):
    col = pl.sample_tex(tex_lin, v["uv"])
    lf = light_factor(v)
    if light is not None:
        lf = lf + light
    col = col * lf
    col, a = pl.downsample(col, v["alpha"], SS)
    srgb = np.clip(pl.lin_to_srgb(np.clip(col, 0, 1)), 0, 1)
    rgba = np.zeros(a.shape + (4,), np.uint8)
    rgba[..., :3] = (srgb * 255 + 0.5).astype(np.uint8)
    rgba[..., 3] = np.where(a > 0.5, 255, 0)
    return rgba


# ------------------------------------------------------------------ lighting: grade + glow
def def_body_lab(defs, core=False):
    px = []
    for rgba in defs["Unit_Idle"]["rgba"]:
        s = fm.segment(rgba)
        m = s["body"] & (s["core"] if core else ~s["core"])
        px.append(rgba[..., :3][m])
    px = np.concatenate(px).astype(np.float32) / 255
    return pl.lin_to_lab(pl.srgb_to_lin(px))


def fit_grade(albedo, views, defs, gmask, bones_by_frame):
    """Grade fitted with the effects on: the baked glow is applied and the fire light at FIRE_FLOOR is lit."""
    rng = np.random.default_rng(3)
    samp_alb, samp_lf, samp_gm = [], [], []
    for v, f in zip(views["Unit_Idle"], CLIPS["Unit_Idle"][1]):
        m = v["alpha"] > 0.99
        ys, xs = np.nonzero(m)
        k = rng.choice(len(ys), min(6000, len(ys)), replace=False)
        uv = v["uv"][ys[k], xs[k]][None]
        samp_alb.append(pl.sample_tex(albedo, uv)[0])
        samp_gm.append(pl.sample_tex(gmask[..., None], uv)[0, :, 0])
        lt = point_light_term(v, np.array(bones_by_frame[str(f)]["Spine2"]["head"][:2]), 0.45, FIRE_FLOOR)
        samp_lf.append((light_factor(v) + lt)[ys[k], xs[k]])
    alb, lf, gm = np.concatenate(samp_alb), np.concatenate(samp_lf), np.concatenate(samp_gm)
    tgt = def_body_lab(defs)
    q = [10, 25, 50, 75, 90]
    tL = np.percentile(tgt[:, 0], q)
    ta = np.percentile(tgt[:, 1], [25, 50, 75])
    tb = np.percentile(tgt[:, 2], [25, 50, 75])

    def loss(g):
        lab = pl.lin_to_lab(np.clip(apply_glow(pl.grade(alb, g), gm, GLOW_STRENGTH) * lf, 0, 1))
        e = np.abs(np.percentile(lab[:, 0], q) - tL).mean()
        e += np.abs(np.percentile(lab[:, 1], [25, 50, 75]) - ta).mean()
        e += np.abs(np.percentile(lab[:, 2], [25, 50, 75]) - tb).mean()
        return e

    x0 = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
    bounds = [(0.3, 4.0), (0.4, 1.6), (0.3, 2.0), (0.6, 1.5), (0.3, 1.5)]
    res = optimize.minimize(lambda g: loss(np.clip(g, [b[0] for b in bounds], [b[1] for b in bounds])), x0,
                            method="Nelder-Mead", options={"maxiter": 400, "xatol": 1e-3, "fatol": 1e-3})
    g = np.clip(res.x, [b[0] for b in bounds], [b[1] for b in bounds])
    hits = [i for i, (x, b) in enumerate(zip(g, bounds)) if abs(x - b[0]) < 1e-3 or abs(x - b[1]) < 1e-3]
    return g, float(loss(np.ones(5))), float(res.fun), hits


def glow_mask(pos, cov):
    a, b = SPINE_GLTF
    ab = b - a
    t = np.clip(((pos - a) @ ab) / (ab @ ab), 0, 1)
    d = np.linalg.norm(pos - (a + t[..., None] * ab), axis=-1)
    radial = 1 - np.clip((d - 0.10) / 0.22, 0, 1)
    # chest side (+z, beak side) glows more, the back less (the DEF core sits on the breast and belly)
    side = 0.55 + 0.45 * np.clip(pos[..., 2] / 0.25, -1, 1)
    patch = value_noise3(pos, 0.07, 11) * 0.6 + value_noise3(pos, 0.025, 12) * 0.4
    patch = np.clip((patch - 0.38) / 0.25, 0, 1)
    m = radial * side * patch
    return np.where(cov, m, ndimage.maximum_filter(m, 3)).astype(np.float32)


def apply_glow(tex_lin, mask, strength):
    g = pl.srgb_to_lin(GLOW_RGB)
    w = np.clip(mask * strength, 0, 1)[..., None]
    return tex_lin * (1 - w) + g * w


def core_share(rgba):
    s = fm.segment(rgba)
    return float(s["core"].sum() / max(1, s["body"].sum()))


def fit_glow(tex, mask, views, defs):
    tgt = np.mean([core_share(r) for r in defs["Unit_Idle"]["rgba"]])
    vs = views["Unit_Idle"][::2]

    def share(s):
        t = apply_glow(tex, mask, s)
        return np.mean([core_share(render(t, v)) for v in vs])

    lo, hi = 0.0, 3.0
    for _ in range(9):
        mid = 0.5 * (lo + hi)
        if share(mid) < tgt:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi), float(tgt), float(share(0.5 * (lo + hi)))


# ------------------------------------------------------------------ fire_boil atlas
def fire_texels(tex_lin):
    lab = pl.lin_to_lab(tex_lin)
    C = np.hypot(lab[..., 1], lab[..., 2])
    return (np.clip((C - 25) / 20, 0, 1) * np.clip((lab[..., 0] - 30) / 15, 0, 1)).astype(np.float32)


def boil_cell(look, pos, fire, seed, amp, hot):
    p = pos / np.array([1.0, 2.6, 1.0])  # streaks elongated vertically (glTF y up), as the DEF body texture is
    n = 0.65 * value_noise3(p, 0.035, seed) + 0.35 * value_noise3(p, 0.012, seed + 101)
    m = (n - 0.5) * 2.0
    lum = np.exp(amp * m)[..., None]
    out = np.clip(look * lum, 0, 1)
    hot_w = (np.clip((n - (1 - hot)) / 0.06, 0, 1) * fire)[..., None]
    out = out * (1 - hot_w) + pl.srgb_to_lin(GLOW_RGB) * hot_w
    red_w = (np.clip(((hot * 0.9) - n) / 0.08, 0, 1) * fire * 0.5)[..., None]
    out = out * (1 - red_w) + pl.srgb_to_lin(np.array([0.85, 0.25, 0.05], np.float32)) * red_w
    f = fire[..., None]
    return (look * (1 - f) + out * f).astype(np.float32)


def cell_sequence(names, ncell=8, used=None):
    """New cell whenever the DEF draws a new frame; the same cell when it repeats a frame (holds, ping-pong)."""
    seen, seq = {}, []
    for nm in names:
        if nm not in seen:
            seen[nm] = len(seen) % ncell
        seq.append(seen[nm])
    return seq


def body_change(frames, masks=None):
    vals = []
    for i in range(len(frames) - 1):
        a, b = frames[i], frames[i + 1]
        m = (a[..., 3] == 255) & (b[..., 3] == 255)
        m = ndimage.binary_erosion(m, fm.disk(2))
        chg = np.abs(a[..., :3].astype(np.int32) - b[..., :3].astype(np.int32)).sum(-1) > 60
        vals.append(float(chg[m].mean()) if m.any() else 0.0)
    return float(np.mean(vals))


# ------------------------------------------------------------------ DEF flipbook masks
def fringe_mask(seg, mesh_a):
    return (seg["flame"] | seg["ember"]) & ~ndimage.binary_dilation(mesh_a, fm.disk(1))


def feather_mask(seg):
    """DEF wing/tail feathers: the orange areas striped with dark quill lines (dense dark pixels)."""
    dark = seg["opaque"] & (seg["luma"] < 80)
    dens = ndimage.uniform_filter(dark.astype(np.float32), 7)
    return ndimage.binary_dilation(dens > 0.06, fm.disk(2)) & seg["opaque"]


def tip_mask(seg, seed=0, dmin=20, dmax=34, upper=0.45):
    """Flame tips: per column, the top DMIN..DMAX px of the silhouette's topmost run (depth varies smoothly
    along x, so the cut is ragged, not a line), only where that top lies in the upper part of the silhouette,
    and never on feathers."""
    op = seg["opaque"] & ~seg["ember"]
    H, W = op.shape
    ys = np.nonzero(op.any(1))[0]
    top, h = ys.min(), ys.max() - ys.min()
    rng = np.random.default_rng(seed)
    depth = ndimage.gaussian_filter1d(rng.uniform(dmin, dmax, W), 2.0)
    out = np.zeros_like(op)
    feath = feather_mask(seg)
    bx = np.nonzero(seg["body"].any(0))[0]
    xa, xb = bx.min() + 0.12 * (bx.max() - bx.min()), bx.min() + 0.88 * (bx.max() - bx.min())
    for x in np.nonzero(op.any(0))[0]:
        if x < xa or x > xb:
            continue
        col = op[:, x]
        y0 = int(np.argmax(col))
        if y0 > top + upper * h:
            continue
        run = col[y0:]
        stop = int(np.argmin(run)) if not run.all() else len(run)
        y1 = y0 + min(stop, int(depth[x]))
        out[y0:y1, x] = True
    return out & ~feath


def crest_mask(seg, mesh_a):
    return tip_mask(seg) | fringe_mask(seg, mesh_a)


def front_mask(seg):
    ys, xs = np.nonzero(seg["body"])
    cx = xs.min() + 0.62 * (xs.max() - xs.min())
    m = np.zeros_like(seg["opaque"])
    m[:, int(cx):] = True
    return m


BEAK_X, JET_TOP_Y, JET_CLEAR_X = 276, 190, 320   # DEF px, g12 (identical in CPHX and CFBIRD)


def breath_mask(seg, i):
    """The beak jet. From frame 4 the jet's root is thicker than the r=3 opening, so the region rule calls it BODY;
    the jet is therefore everything opaque in front of the beak (x >= 276), below the crest (y >= 190) until it clears
    the head (x >= 320). Frame 3 (before the jet) keeps the region rule: sparks in front of the body."""
    if i <= 3:
        return (seg["flame"] | seg["ember"]) & front_mask(seg)
    H, W = seg["opaque"].shape
    ys, xs = np.mgrid[0:H, 0:W]
    return seg["opaque"] & (xs >= BEAK_X) & ((ys >= JET_TOP_Y) | (xs >= JET_CLEAR_X))


def over(dst, src):
    """Alpha-over of hard-alpha RGBA uint8 (the DEF has no partial alpha outside the shadow slots)."""
    out = dst.copy()
    m = src[..., 3] == 255
    out[m] = src[m]
    return out


def cut(rgba, mask):
    out = np.zeros_like(rgba)
    out[mask] = rgba[mask]
    out[..., 3] = np.where(mask & (rgba[..., 3] == 255), 255, 0)
    return out


# ------------------------------------------------------------------ procedural tongues
def teardrop(spr, rng):
    """Clip a tip window to a pointed flame envelope (apex at the window top, ragged edge)."""
    h, w = spr.shape[:2]
    t = (np.arange(h)[:, None] + 0.5) / h                 # 0 top .. 1 bottom
    half = 0.5 * w * np.clip(np.sin(np.pi * np.clip(0.08 + 0.92 * t, 0, 1) * 0.62) ** 0.9, 0, 1)
    half = half + rng.normal(0, 0.8, (h, 1))
    cx = 0.5 * w + ndimage.gaussian_filter1d(rng.normal(0, 1.2, h), 2)[:, None]
    x = np.arange(w)[None, :] + 0.5
    env = np.abs(x - cx) <= half
    out = spr.copy()
    out[~env] = 0
    return out


def tongue_bank(defs):
    """Tongue sprites: the DEF idle flame tips split at the valleys between tips (natural tongue outlines)."""
    strips, embers = [], []
    for k, rgba in enumerate(defs["Unit_Idle"]["rgba"]):
        s = fm.segment(rgba)
        tips = tip_mask(s, seed=k)
        cols = np.nonzero(tips.any(0))[0]
        if not len(cols):
            continue
        topy = np.array([np.argmax(tips[:, x]) if tips[:, x].any() else 10**4 for x in range(tips.shape[1])], float)
        sm = ndimage.gaussian_filter1d(np.where(topy > 9000, np.nan_to_num(topy.max()), topy), 1.0)
        valleys = [x for x in range(cols.min() + 1, cols.max()) if sm[x] >= sm[x - 1] and sm[x] > sm[x + 1]]
        edges = [cols.min()] + valleys + [cols.max() + 1]
        for a, b in zip(edges[:-1], edges[1:]):
            if b - a < 8:
                continue
            m = np.zeros_like(tips)
            m[:, a:b] = tips[:, a:b]
            if m.sum() < 20:
                continue
            yy, xx = np.nonzero(m)
            spr = cut(rgba, m)[yy.min():yy.max() + 1, xx.min():xx.max() + 1]
            spr = teardrop(spr, np.random.default_rng(len(strips)))
            if (spr[..., 3] == 255).sum() >= 20 and spr.shape[1] >= 5:
                strips.append(spr)
        lab, n = ndimage.label(s["ember"], np.ones((3, 3)))
        for sl in ndimage.find_objects(lab):
            spr = cut(rgba, s["ember"])[sl]
            if (spr[..., 3] > 0).sum() >= 2:
                embers.append(spr)
    return strips, embers


def nearest_bone_weight(px, py, bf):
    wts = {"Spine": 1.0, "Spine1": 1.0, "Spine2": 1.0, "Neck": 1.0, "Head": 0.8, "Hips": 0.6,
           "WingL_00": 0.7, "WingL_01": 0.6, "WingL_02": 0.4, "WingL_03": 0.3,
           "WingR_00": 0.7, "WingR_01": 0.6, "WingR_02": 0.4, "WingR_03": 0.3}
    best, bw = 1e9, 0.0
    for nm, w in wts.items():
        if nm not in bf:
            continue
        a, b = np.array(bf[nm]["head"][:2]), np.array(bf[nm]["tail"][:2])
        ab = b - a
        t = np.clip(((np.array([px, py]) - a) @ ab) / max(ab @ ab, 1e-6), 0, 1)
        d = np.linalg.norm(np.array([px, py]) - (a + t * ab))
        if d < best:
            best, bw = d, w
    for nm in ("LeftUpLeg", "RightUpLeg", "LeftLeg", "RightLeg", "LeftFoot", "RightFoot"):
        a = np.array(bf[nm]["head"][:2])
        if np.linalg.norm(np.array([px, py]) - a) < best:
            return 0.0
    return bw


def tongues_layer(mesh_a, bf, strips, embers, seed, n_tongue, n_ember):
    """Tongue strips (behind the body) and ember specks placed on the mesh's upper silhouette edge."""
    H, W = mesh_a.shape
    rng = np.random.default_rng(seed)
    up = np.zeros_like(mesh_a)
    up[3:] = mesh_a[3:] & ~mesh_a[:-3] & ~mesh_a[1:-2] & ~mesh_a[2:-1]
    ys, xs = np.nonzero(up)
    if not len(ys):
        return np.zeros((H, W, 4), np.uint8), np.zeros((H, W, 4), np.uint8)
    ytop, ybot = ys.min(), np.nonzero(mesh_a.any(1))[0].max()
    keep = ys < ytop + 0.65 * (ybot - ytop)
    ys, xs = ys[keep], xs[keep]
    w = np.array([nearest_bone_weight(x, y, bf) for y, x in zip(ys, xs)])
    if w.sum() <= 0:
        w = np.ones(len(ys))
    behind = np.zeros((H, W, 4), np.uint8)
    front = np.zeros((H, W, 4), np.uint8)
    idx = rng.choice(len(ys), size=min(n_tongue, len(ys)), replace=False, p=w / w.sum())
    for k in idx:
        spr = strips[int(rng.integers(len(strips)))]
        h, ww = spr.shape[:2]
        y0, x0 = ys[k] + 4 - h, xs[k] - ww // 2
        paste(behind, spr, y0, x0)
    for _ in range(n_ember):
        k = int(rng.choice(len(ys), p=w / w.sum()))
        spr = embers[int(rng.integers(len(embers)))]
        y0 = ys[k] - int(rng.integers(8, 40))
        x0 = xs[k] + int(rng.integers(-12, 12))
        paste(front, spr, y0, x0)
    return behind, front


def paste(dst, spr, y0, x0):
    H, W = dst.shape[:2]
    h, w = spr.shape[:2]
    ya, xa = max(0, y0), max(0, x0)
    yb, xb = min(H, y0 + h), min(W, x0 + w)
    if yb <= ya or xb <= xa:
        return
    s = spr[ya - y0:yb - y0, xa - x0:xb - x0]
    m = s[..., 3] == 255
    dst[ya:yb, xa:xb][m] = s[m]


# ------------------------------------------------------------------ light fit
def body_mean_L(rgba, mask):
    lab = pl.lin_to_lab(pl.srgb_to_lin(rgba[..., :3].astype(np.float32) / 255))
    return float(lab[..., 0][mask].mean())


LIGHT_ANCHOR = {"Unit_Idle": ("Spine2", 0.0), "Unit_Move": ("Spine2", 0.0), "Unit_Hitted": ("Spine2", 0.0),
                "Unit_AttackFront": ("Head", 0.5), "Unit_Death": ("Spine1", 0.0)}


def light_anchor(clip, bf, fx_rgba):
    bone, toward = LIGHT_ANCHOR[clip]
    p = np.array(bf[bone]["head"][:2])
    if toward > 0 and fx_rgba is not None and (fx_rgba[..., 3] == 255).sum() > 30:
        yy, xx = np.nonzero(fx_rgba[..., 3] == 255)
        p = p + toward * (np.array([xx.mean(), yy.mean()]) - p)
    return p


# ------------------------------------------------------------------ main
def main():
    LAB.mkdir(parents=True, exist_ok=True)
    (LAB / "textures").mkdir(exist_ok=True)
    report = {"schema": "phoenix_fire_lab.v1", "proof": "generated artifact: numpy Hex/Lit relight of Blender passes + 2D composite"}
    d, defs = def_frames()
    views = load_views()
    B = bones()
    albedo = load_albedo()
    pos, cov = rest_raster()

    # --- lighting
    gmask = glow_mask(pos, cov)
    g, loss0, loss1, hits = fit_grade(albedo, views, defs, gmask, B)
    graded = pl.grade(albedo, g)
    strength = GLOW_STRENGTH
    look = apply_glow(graded, gmask, strength)
    core_tgt = float(np.mean([core_share(r) for r in defs["Unit_Idle"]["rgba"]]))
    core_got = float(np.mean([core_share(render(look, v)) for v in views["Unit_Idle"]]))
    report["lighting"] = {"grade[exposure,gamma,sat,wr,wb]": np.round(g, 4).tolist(), "gradeLossRaw": round(loss0, 2),
                          "gradeLossFit": round(loss1, 2), "boundHits": hits, "glowStrength": round(strength, 3),
                          "defIdleCoreShare": round(core_tgt, 4), "lookIdleCoreShare": round(core_got, 4),
                          "glowRgbSrgb": GLOW_RGB.tolist()}
    print("lighting", report["lighting"])
    Image.fromarray((pl.lin_to_srgb(graded) * 255).astype(np.uint8)).save(LAB / "textures/basecolor_grade.png")
    Image.fromarray((pl.lin_to_srgb(look) * 255).astype(np.uint8)).save(LAB / "textures/basecolor_look.png")
    Image.fromarray((gmask * 255).astype(np.uint8)).save(LAB / "textures/fire_core_glow_mask.png")

    # --- fire_boil atlas: fit amplitude to the DEF idle body change
    fire = fire_texels(look)
    def_chg = body_change(defs["Unit_Idle"]["rgba"])
    vs = views["Unit_Idle"]

    def boil_change(amp):
        cells = [boil_cell(look, pos, fire, 40 + i, amp, 0.10) for i in range(2)]
        fr = [render(cells[i % 2], v) for i, v in enumerate(vs[:4])]
        return body_change(fr)

    lo, hi = 0.0, 2.5
    for _ in range(7):
        mid = 0.5 * (lo + hi)
        if boil_change(mid) < def_chg:
            lo = mid
        else:
            hi = mid
    amp = 0.5 * (lo + hi)
    cells = [boil_cell(look, pos, fire, 40 + i, amp, 0.10) for i in range(8)]
    report["fire_boil"] = {"amp": round(amp, 3), "hotShare": 0.10, "defIdleBodyChange": round(def_chg, 3),
                           "lookIdleBodyChange(no boil)": round(body_change([render(look, v) for v in vs]), 3)}
    gut = 32
    atlas = np.zeros((4 * (TEX + 2 * gut), 2 * (TEX + 2 * gut), 3), np.float32)
    cellST = []
    AW, AH = atlas.shape[1], atlas.shape[0]
    for i, c in enumerate(cells):
        cx, cy = i % 2, i // 2
        padded = np.pad(c, ((gut, gut), (gut, gut), (0, 0)), mode="edge")
        y0, x0 = cy * (TEX + 2 * gut), cx * (TEX + 2 * gut)
        atlas[y0:y0 + TEX + 2 * gut, x0:x0 + TEX + 2 * gut] = padded
        # Unity UV origin bottom-left: v offset counts from the atlas bottom
        cellST.append([TEX / AW, TEX / AH, (x0 + gut) / AW, 1 - (y0 + gut + TEX) / AH])
    Image.fromarray((pl.lin_to_srgb(atlas) * 255).astype(np.uint8)).save(LAB / "textures/fire_boil_atlas.png")
    seqs = {clip: cell_sequence(defs[clip]["names"]) for clip in CLIPS}
    (LAB / "fire_boil_cells.json").write_text(json.dumps({"atlasSize": [AW, AH], "cellST": cellST, "clips": seqs,
                                                          "rule": "new cell per new DEF frame name; repeated DEF frames reuse the cell"}, indent=1))
    report["fire_boil"]["cells"] = seqs

    # --- tongue bank
    strips, embers = tongue_bank(defs)
    report["fire_tongues"] = {"strips": len(strips), "embers": len(embers)}
    motion = json.loads((BASE / "evidence/fire_motion.json").read_text())

    # --- per clip composites
    frames_dir = LAB / "frames"
    light_curves = {}
    flip_counts = {}
    for clip, (grp, mfr) in CLIPS.items():
        drg = defs[clip]["rgba"]
        names = defs[clip]["names"]
        n = len(drg)
        segs = [fm.segment(r) for r in drg]
        base_raw, base_look, base_boil, mesh_a = [], [], [], []
        for i, v in enumerate(views[clip]):
            base_raw.append(render(albedo, v))
            base_look.append(render(look, v))
            base_boil.append(render(cells[seqs[clip][i]], v))
            mesh_a.append(base_raw[-1][..., 3] == 255)
        bfs = [B[str(f)] for f in mfr]
        # DEF flipbooks (per frame RGBA layers at DEF px)
        fringe = [cut(drg[i], fringe_mask(segs[i], mesh_a[i])) for i in range(n)]
        crest = [cut(drg[i], crest_mask(segs[i], mesh_a[i])) for i in range(n)]
        events_front = [np.zeros_like(drg[0]) for _ in range(n)]
        if clip == "Unit_AttackFront":
            for i in range(3, n):
                events_front[i] = cut(drg[i], breath_mask(segs[i], i) & ~ndimage.binary_dilation(mesh_a[i], fm.disk(1)))
        if clip == "Unit_Hitted":
            for i in range(2, n):
                events_front[i] = cut(drg[i], segs[i]["ember"] & ~mesh_a[i])
        if clip == "Unit_Death":
            for i in range(n):
                if i <= 4:
                    events_front[i] = cut(drg[i], fringe_mask(segs[i], mesh_a[i]) | ((i == 4) & segs[i]["opaque"] & ~mesh_a[i]))
                else:
                    events_front[i] = drg[i]  # ash pile: the DEF frame itself (the mesh is hidden by the event)
        flip_counts[clip] = {"fringePx": [int((x[..., 3] == 255).sum()) for x in fringe],
                             "crestPx": [int((x[..., 3] == 255).sum()) for x in crest],
                             "eventPx": [int((x[..., 3] == 255).sum()) for x in events_front]}
        # procedural tongues: counts matched to the DEF crest/ember px per frame
        mean_strip = np.mean([(s[..., 3] == 255).sum() for s in strips])
        mean_ember = np.mean([(s[..., 3] == 255).sum() for s in embers])
        tongues = []
        for i in range(n):
            crest_px = (crest[i][..., 3] == 255).sum() - (fringe[i][..., 3] == 255).sum() * 0
            nt = int(round(0.8 * crest_px / mean_strip))
            ne = int(round(motion["clips"][str(grp)]["perFrame"][i]["ember"] / mean_ember)) if clip in ("Unit_Idle", "Unit_Move") else 0
            seed = int(hashlib.md5(f"{clip}:{names[i]}".encode()).hexdigest()[:8], 16)
            tongues.append(tongues_layer(mesh_a[i], bfs[i], strips, embers, seed, nt, ne))
        # fire light: fitted per DEF frame so the mesh body mean L matches the DEF body (DEF opening minus effects)
        def_L = [body_mean_L(drg[i], segs[i]["body"]) for i in range(n)]
        live = n if clip != "Unit_Death" else 5  # death 5-6 are the ash pile: no fire, not a baseline
        rise = np.array(def_L) - min(def_L[:live])
        rise[live:] = 0.0
        intens = []
        for i, v in enumerate(views[clip]):
            anc = light_anchor(clip, bfs[i], events_front[i] if clip == "Unit_AttackFront" else None)
            base = base_boil[i]
            L0 = body_mean_L(base, mesh_a[i])
            # the light supplies what the albedo cannot under Hex/Lit: the DEF body's mean L over the prebaked body
            target = (def_L[i] - L0) if i < live else 0.0
            if target < 0.5:
                intens.append(0.0)
                continue
            lo, hi = 0.0, 6.0
            for _ in range(10):
                mid = 0.5 * (lo + hi)
                lt = point_light_term(v, anc, 0.45, mid)
                got = body_mean_L(render(cells[seqs[clip][i]], v, lt), mesh_a[i]) - L0
                if got < target:
                    lo = mid
                else:
                    hi = mid
            intens.append(round(0.5 * (lo + hi), 3))
        light_curves[clip] = {"meshBodyMeanLNoLight": None, "defBodyMeanL": np.round(def_L, 2).tolist(), "riseOverClipMin": np.round(rise, 2).tolist(),
                              "intensity": intens, "anchor": LIGHT_ANCHOR[clip]}
        print(clip, "light", intens)
        # compose candidates
        for cand in CANDS:
            out = frames_dir / cand
            out.mkdir(parents=True, exist_ok=True)
            for i, v in enumerate(views[clip]):
                if cand == "C0_raw":
                    img = base_raw[i]
                elif cand == "C1_look":
                    img = base_look[i]
                elif cand == "C2_boil":
                    img = base_boil[i]
                else:
                    body = base_boil[i]
                    if cand.endswith("light") and intens[i] > 0:
                        anc = light_anchor(clip, bfs[i], events_front[i] if clip == "Unit_AttackFront" else None)
                        body = render(cells[seqs[clip][i]], v, point_light_term(v, anc, 0.45, intens[i]))
                    if cand.startswith(("C3", "C5")):
                        img = over(crest[i], body)          # crest behind the body
                        img = over(img, fringe[i])          # fringe tongues + embers in front
                    else:
                        behind, front = tongues[i]
                        img = over(behind, body)
                        img = over(img, front)
                    if clip == "Unit_Death" and i >= 5:
                        img = drg[i]
                    else:
                        img = over(img, events_front[i])
                Image.fromarray(img).save(out / f"{clip}_{i:02d}.png")
    report["lightCurves"] = light_curves
    report["flipbookPx"] = flip_counts
    (LAB / "lab_report.json").write_text(json.dumps(report, indent=1))
    print("DONE")


if __name__ == "__main__":
    main()
