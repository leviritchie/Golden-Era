"""Look finish stage: the "vanilla philosophy" base colour (look B), the default finish since 2026-10-09.

    python tools/homm3_unit_look/finish.py <unit> [--device cuda|cpu] [--out <png>] [--json <path>]   (dry run)
    python tools/homm3_unit_look/look.py <unit> --stages finish,apply                                (delivery)

2026-10-09 user: "The vanilla philosophy looks quite a bit better. Let's switch everything over to it next version."
Port of the offline A/B prototype V:/olden_port_work/vanilla_material_study/ab/ab_idle.py (study:
docs/olden_era_vanilla_unit_materials.md). B is computed from A, the graded base colour the lighting stage wrote
(``basecolor_a.png``), entirely in texture space:

  1 detail: the fine band (box r8 at 2048) x0.5 on L*, a*, b*
  2 crevice: regress L* on mesh concavity (1/4/16 ring), remove half of the predicted darkening
  3 top-lit: add k*(0.7*n_up + 0.3*height), k bisected so r(L*, n_up) ~= 0.20 (k <= 12 L*)
  4 grade: L' = 100*k*(L/100)^g, fitted so the rendered body p50/p95 match the DEF idle body (outline eroded 2 px),
    then a soft toe holding the black floor at L* >= 9 (grid k, g in [0.5, 2.5]); chroma lift (midtone
    weighted, hue kept) fitted so the rendered body C50 reaches max(A's, the DEF's), bound [1.0, 2.2],
    no texel lifted past max(its C, the DEF body's C95 at its hue) (2026-10-09: angel skin went orange without it);
    the fine band re-held at 0.5x A's afterwards
  5 gutters: push-pull fill with the island colour
  6 metal hue (2026-10-09, user: gremlin ball and chain green in game): texels the Meshy metallicRoughness map marks
    metal (HUE_MASK: metallic ramp [0.45, 0.65], every unit) and whose source colour is neutral (C* ramp-out 12-24)
    keep B's lightness but take the source base colour's a*b* (scaled by the lightness ratio, [0.5, 1.5]): the whole-unit v7c grade (white balance at its whiteB bound + the luminance-banded
    a*b* transfer, both fitted to a skin-dominated DEF body) tinted neutral metal. Region-protected texels excluded.
  7 neutral guard (2026-10-09, h3_centaur_captain grey fetlocks / gremlin grey trim green-grey): any source-neutral
    texel (C* ramp-out 12-24, metal or not) may not lose a* against the source (lightness-scaled): the grade cannot
    push it toward green; the rest of the white balance (warm/cool) still applies. Source-green paint stays green.
  8 accent floor (2026-10-09, necropolis board: wraith hands/skull, rot zombie skin/axe muddied as the grade pulls A's
    highlights to the DEF p95): texels bright in A (L* smoothstep 45-65) keep >= 0.85x A's L* through the grade. The
    (k, gamma) fit runs without it (body p50/p95 still matched to the DEF); the chroma fit and B see it.

The render that steps 4 fit through is the prototype's: Unit_Idle frame 0 of the un-prebaked source GLB under the
battle camera (orthographic, 40 deg elevation, yaw 120 in Unity axes), Hex/Lit diffuse with the sand-arena sun +
ambient and a shadow map (no SSAO / outline / SH): an approximation, not an in-game capture.

Protected texels (look spec features that must keep working):
  - lighting.regions (defPalette / grade regions, e.g. the pegasus coat/wing/armour and the gold dragon): A is kept
    by region weight; B never re-grades a texel a region fitted to its own DEF region.
  - lighting.metal (the baked metal reflection, metal.py): metal texels are masked out of the detail and top-lit
    steps and keep their full fine band after the grade; the crevice and grade steps apply, so the reflection reads.
Emission is not touched (bakedGlow is already inside A; no emissive image is written here).

Spec: ``lighting.finish`` "vanilla" (default when absent) or "none" (A, the pre-2026-10-09 look, for comparison).
Torch, CUDA by default; ``--device cpu`` is the reference (test_finish.py checks parity). No silent fallback.
CPU-only steps (stated): vertex welding for the concavity graph (torch.unique; tiny), PNG I/O.
Proof tier: generated artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as TF
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools/homm3_prebake"))   # prebake_lab (regions.py, look.py's look_tex_lin refresh)
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools/homm3_authenticity"))
import raster as R  # noqa: E402  (authenticity board kernels: skinning, rasteriser; parity-tested on both devices)

SCHEMA = "homm3_unit_look_finish.v1"
MODES = ("vanilla", "none")
DEFAULT_MODE = "vanilla"
FLOOR = 9.0
TILE = 384
ELEV = 40.0
OUR_YAW = 120.0
ATTR_SIZE = 1024
SHADOW_SIZE = 768
# tools/homm3_prebake/probe_vanilla_unit_materials.py (sand arena, Unity world)
SUN_DIR = np.array([0.624, -0.4035, 0.6692])
SUN_COL = np.array([1.0, 0.957, 0.839])
AMBIENT = np.array([0.6235, 0.6784, 0.7922])
# grade / chroma search grids (same 0.025 / 0.02 steps as the prototype; widened 2026-10-09 after the pilot, where
# behemoth, griffin, walking dead hit the prototype's k [0.75, 1.35] x gamma [0.70, 1.40] box and archangel the 1.6 lift;
# behemoth converges at k 1.925, g 1.675)
K_LO, K_HI, K_N = 0.50, 2.50, 81
G_LO, G_HI, G_N = 0.50, 2.50, 81
C_HI, C_N = 2.20, 61
# step 6 (metal hue): Meshy metallic weight ramp and the source-chroma gate (C* ramp-out). Meshy marks some cloth
# metallic 0.4-0.6 (h3_gremlin's red robe, C* ~25): the source-chroma gate keeps those coloured texels out.
HUE_MASK = {"source": "meshyMetallic", "metallic": [0.45, 0.65], "blur": 1.5}
HUE_CHROMA = (12.0, 24.0)
# step 8 (accent floor, 2026-10-09 necropolis board: wraith hands/skull, rot zombie skin/axe dimmed): A-bright texels
# (A's L* smoothstep 45 -> 65) keep >= 0.85 of A's L* through the grade. Applied after the (k, gamma) fit (which
# still matches the DEF body p50/p95 without it), before the chroma fit.
ACCENT = (45.0, 65.0)
ACCENT_KEEP = 0.85
VRAM_CAP_GB = float(os.environ.get("HOMM3_FINISH_VRAM_CAP_GB", "3"))
F64 = torch.float64
F32 = torch.float32


def mode_of(spec: dict) -> str:
    return (spec.get("lighting") or {}).get("finish", DEFAULT_MODE)


def code_sha() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def device(name: str) -> torch.device:
    if name == "cuda":
        os.environ.setdefault("HOMM3_AUTH_VRAM_CAP_GB", str(VRAM_CAP_GB))
        R.VRAM_CAP_GB = VRAM_CAP_GB
    return R.resolve_device(name)


# ------------------------------------------------------------------ colour (D65, the probe's matrices)
_M = torch.tensor([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]], dtype=F64)
_MI = torch.tensor([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560],
                    [0.0556434, -0.2040259, 1.0572252]], dtype=F64)
_WHITE = torch.tensor([0.95047, 1.0, 1.08883], dtype=F64)


def srgb_to_lin(c):
    return torch.where(c <= 0.04045, c / 12.92, ((c.clamp_min(0) + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(c):
    c = c.clamp(0, 1)
    return torch.where(c <= 0.0031308, c * 12.92, 1.055 * c.clamp_min(1e-12) ** (1 / 2.4) - 0.055)


def srgb_to_lab(rgb):
    lin = srgb_to_lin(rgb)
    xyz = lin @ _M.to(rgb).T / _WHITE.to(rgb)
    f = torch.where(xyz > 216 / 24389, xyz.clamp_min(0) ** (1 / 3), (24389 / 27 * xyz + 16) / 116)
    return torch.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def lab_to_srgb(lab):
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16) / 116
    fx = fy + a / 500
    fz = fy - b / 200
    d = 6 / 29

    def finv(f):
        return torch.where(f > d, f ** 3, 3 * d * d * (f - 4 / 29))
    xyz = torch.stack([finv(fx) * 0.95047, finv(fy), finv(fz) * 1.08883], -1)
    lin = xyz @ _MI.to(lab).T
    return lin_to_srgb(lin.clamp_min(0)).clamp(0, 1)


def corr(a, b) -> float:
    a = a.to(F64) - a.to(F64).mean()
    b = b.to(F64) - b.to(F64).mean()
    d = torch.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if float(d) > 0 else 0.0


# ------------------------------------------------------------------ image ops
def _box1d(x, r, dim):
    """scipy.ndimage.uniform_filter(size=2r+1, mode='reflect') along ``dim`` (half-sample symmetric padding)."""
    n = x.shape[dim]
    if r <= 0:
        return x
    idx = torch.cat([torch.arange(r - 1, -1, -1), torch.arange(n), torch.arange(n - 1, n - 1 - r, -1)]).clamp(0, n - 1)
    xp = x.index_select(dim, idx.to(x.device)).to(F64)
    c = torch.cumsum(xp, dim)
    zero = torch.zeros_like(c.narrow(dim, 0, 1))
    c = torch.cat([zero, c], dim)
    out = (c.narrow(dim, 2 * r + 1, n) - c.narrow(dim, 0, n)) / (2 * r + 1)
    return out.to(x.dtype)


def box(x, r):
    return _box1d(_box1d(x, r, 0), r, 1)


def masked_blur(x, m, r):
    mm = m.to(x.dtype)
    num = box(x * (mm[..., None] if x.dim() == 3 else mm), r)
    den = box(mm, r)
    return num / (den[..., None] if x.dim() == 3 else den).clamp_min(1e-6)


def erode(m, it):
    """scipy binary_erosion (cross structure, border 0), ``it`` iterations."""
    for _ in range(it):
        p = TF.pad(m[None, None].to(F32), (1, 1, 1, 1))[0, 0] > 0.5
        m = m & p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
    return m


def push_pull(img, m):
    """Fill unmasked texels with the masked neighbourhood colour (pyramid push-pull)."""
    levels = [(img * m[..., None], m.to(img.dtype))]
    while min(levels[-1][1].shape) > 1:
        c, w = levels[-1]
        h, ww = c.shape[0] // 2, c.shape[1] // 2
        c2 = c[:2 * h, :2 * ww].reshape(h, 2, ww, 2, -1).sum((1, 3))
        w2 = w[:2 * h, :2 * ww].reshape(h, 2, ww, 2).sum((1, 3))
        levels.append((c2, w2))
    c, w = levels[-1]
    fill = c / w[..., None].clamp_min(1e-9)
    for c, w in reversed(levels[:-1]):
        up = fill.repeat_interleave(2, 0).repeat_interleave(2, 1)
        if up.shape[0] < c.shape[0] or up.shape[1] < c.shape[1]:
            up = TF.pad(up.permute(2, 0, 1)[None], (0, c.shape[1] - up.shape[1], 0, c.shape[0] - up.shape[0]),
                        mode="replicate")[0].permute(1, 2, 0)
        up = up[:c.shape[0], :c.shape[1]]
        cur = c / w[..., None].clamp_min(1e-9)
        a = w.clamp(0, 1)[..., None]
        fill = cur * a + up * (1 - a)
    return torch.where(m[..., None], img, fill)


def vwrap(v):
    """glTF v wrapped into [0, 1] the prototype's way (1 - mod(1 - v, 1)): v = 1.0 stays 1.0, the bottom row, instead
    of wrapping to the top (a plain mod turns every triangle touching v = 1 into a full-height sliver)."""
    return 1 - torch.remainder(1 - v, 1.0)


def sample_nearest(img, uv):
    """probe._sample: nearest texel, u*(w-1), v (glTF, top-left origin)*(h-1)."""
    h, w = img.shape[:2]
    c = torch.round(torch.remainder(uv[:, 0], 1.0) * (w - 1)).long().clamp(0, w - 1)
    r = torch.round(vwrap(uv[:, 1]) * (h - 1)).long().clamp(0, h - 1)
    return img[r, c]


# ------------------------------------------------------------------ raster helpers
def interp(xy, F, tid, attrs, W):
    """Pixels covered (flat index) and their barycentric-interpolated vertex attributes (ortho)."""
    pix = torch.nonzero(tid >= 0)[:, 0]
    Fi = F[tid[pix]]
    v = xy[Fi]
    area = (v[:, 1, 0] - v[:, 0, 0]) * (v[:, 2, 1] - v[:, 0, 1]) - (v[:, 2, 0] - v[:, 0, 0]) * (v[:, 1, 1] - v[:, 0, 1])
    px = (pix % W).to(xy.dtype) + 0.5
    py = torch.div(pix, W, rounding_mode="floor").to(xy.dtype) + 0.5
    w = torch.stack(R._edges(v, px, py, area), -1).clamp_min(0)
    w = w / w.sum(-1, keepdim=True).clamp_min(1e-12)
    return pix, (w[..., None] * attrs[Fi]).sum(1)


def raster_ortho(xy, depth, F, W, H, attrs):
    """(H*W) triangle ids via the authenticity rasteriser (depth > 0, nearest wins), plus interpolated attrs."""
    xy32 = xy.to(F32)
    z = (depth - depth.min() + 1.0).to(F32)
    tid = R.rasterize(xy32, z, F, W, H, persp=False)
    pix, a = interp(xy32, F, tid, attrs.to(F32), W)
    return tid, pix, a


# ------------------------------------------------------------------ geometry
def load_geometry(glb_path: Path, dev, body_name=None) -> dict:
    """Unit_Idle frame 0 of the body (skinned on the device) and its bind pose, in Unity axes (x flipped)."""
    from gltf_scene import Scene
    sc = Scene(glb_path, body_name=body_name)
    if "Unit_Idle" not in sc.anims:
        raise ValueError(f"{glb_path.name}: no Unit_Idle clip")
    t0 = sc.clip_range("Unit_Idle")["start"]
    mesh = R.DeviceMesh(sc, dev, np.ones((1, 1, 4), np.float32))
    Jm, mw = sc.pose("Unit_Idle", np.array([t0]))
    P, N = mesh.skin(Jm, mw)
    flip = torch.tensor([-1.0, 1.0, 1.0], device=dev, dtype=F64)
    return {"V": P[0].to(F64) * flip, "N": N[0].to(F64) * flip, "UV": mesh.UV.to(F64), "F": mesh.F,
            "Vbind": mesh.P.to(F64) * flip, "Nbind": mesh.N.to(F64) * flip}


def cavity(V, F, N, steps=(1, 4, 16)):
    """Mesh concavity at 1/4/16 Laplacian rings (welded positions), per vertex (n, 3)."""
    dev = V.device
    key = torch.round(V / max(1e-6, float((V.max(0).values - V.min(0).values).max()) * 1e-4)).to(torch.int64)
    _, inv = torch.unique(key, dim=0, return_inverse=True)
    m = int(inv.max()) + 1
    cnt = torch.bincount(inv, minlength=m).to(F64)
    Pw = torch.zeros((m, 3), dtype=F64, device=dev).index_add_(0, inv, V) / cnt[:, None]
    Nw = torch.zeros((m, 3), dtype=F64, device=dev).index_add_(0, inv, N)
    Nw = Nw / Nw.norm(dim=1, keepdim=True).clamp_min(1e-9)
    Tw = inv[F]
    i = torch.cat([Tw[:, 0], Tw[:, 1], Tw[:, 2], Tw[:, 1], Tw[:, 2], Tw[:, 0]])
    j = torch.cat([Tw[:, 1], Tw[:, 2], Tw[:, 0], Tw[:, 0], Tw[:, 1], Tw[:, 2]])
    A = torch.sparse_coo_tensor(torch.stack([i, j]), torch.ones(len(i), dtype=F64, device=dev), (m, m)).coalesce()
    A = torch.sparse_coo_tensor(A.indices(), torch.ones_like(A.values()), (m, m)).coalesce()
    deg = torch.sparse.sum(A, 1).to_dense().clamp_min(1)
    el = (Pw[i] - Pw[j]).norm(dim=1).mean()
    out, Q, done = [], Pw.clone(), 0
    for s in steps:
        while done < s:
            Q = torch.sparse.mm(A, Q) / deg[:, None]
            done += 1
        out.append((((Q - Pw) * Nw).sum(1) / (el * np.sqrt(s)))[inv])
    return torch.stack(out, 1)


def uv_attrs(geo, cav, size):
    """Per-texel n_up, height (idle f0) and concavity (bind), rasterised in UV space at ``size``."""
    UV = geo["UV"]
    xy = torch.stack([torch.remainder(UV[:, 0], 1) * size, vwrap(UV[:, 1]) * size], 1)
    V = geo["V"]
    h = (V[:, 1] - V[:, 1].min()) / (V[:, 1].max() - V[:, 1].min()).clamp_min(1e-9)
    attrs = torch.cat([geo["N"][:, 1:2], h[:, None], cav], 1)
    tid, pix, a = raster_ortho(xy, torch.ones(len(xy), dtype=F64, device=xy.device), geo["F"], size, size, attrs)
    img = torch.zeros((size * size, attrs.shape[1]), dtype=F32, device=xy.device)
    img[pix] = a
    return img.view(size, size, -1), (tid >= 0).view(size, size)


def rot(yaw, elev):
    ya, el = np.radians(yaw), -np.radians(elev)
    Ry = np.array([[np.cos(ya), 0, np.sin(ya)], [0, 1, 0], [-np.sin(ya), 0, np.cos(ya)]])
    Rx = np.array([[1, 0, 0], [0, np.cos(el), -np.sin(el)], [0, np.sin(el), np.cos(el)]])
    return Ry, Rx


def gbuffer(geo, yaw=OUR_YAW, size=TILE, elev=ELEV, fill=0.85):
    """Orthographic G-buffer (default: the battle camera at the prototype's framing, 85% fill): per covered pixel uv and
    light (ambient + sun*ndl*shadow, world-fixed sand sun). yaw/elev also serve the boards' preview angle."""
    dev = geo["V"].device
    t = lambda a: torch.as_tensor(a, dtype=F64, device=dev)  # noqa: E731
    V, N = geo["V"], geo["N"]
    Ry, Rx = (t(x) for x in rot(yaw, elev))
    centre = torch.stack([(V[:, 0].max() + V[:, 0].min()) / 2, torch.zeros((), dtype=F64, device=dev),
                          (V[:, 2].max() + V[:, 2].min()) / 2])
    Vw = (V - centre) @ Ry.T
    Nw = N @ Ry.T
    Q = Vw @ Rx.T
    S = fill * size / float(max(Q[:, 0].max() - Q[:, 0].min(), Q[:, 1].max() - Q[:, 1].min()))
    mid = (Q.max(0).values + Q.min(0).values) / 2
    xy = torch.stack([(Q[:, 0] - mid[0]) * S + size / 2, -(Q[:, 1] - mid[1]) * S + size / 2], 1)
    tid, pix, a = raster_ortho(xy, Q[:, 2], geo["F"], size, size, torch.cat([geo["UV"], Nw, Vw], 1))
    msk = (tid >= 0).view(size, size)
    # shadow map along the sun travel direction
    f = t(SUN_DIR / np.linalg.norm(SUN_DIR))
    up0 = t([0.0, 1.0, 0.0])
    r = torch.linalg.cross(up0, f)
    r = r / r.norm()
    u = torch.linalg.cross(f, r)
    S2 = torch.stack([Vw @ r, Vw @ u], 1)
    dz = Vw @ f
    lo = S2.min(0).values
    sc = (SHADOW_SIZE - 4) / float((S2.max(0).values - S2.min(0).values).max())
    sxy = (S2 - lo) * sc + 2
    stid, spix, sd = raster_ortho(sxy, dz, geo["F"], SHADOW_SIZE, SHADOW_SIZE, dz[:, None])
    szb = torch.full((SHADOW_SIZE * SHADOW_SIZE,), float("inf"), dtype=F32, device=dev)
    szb[spix] = sd[:, 0]
    szb = szb.view(SHADOW_SIZE, SHADOW_SIZE)
    pw = a[:, 5:8].to(F64)
    q = (((torch.stack([pw @ r, pw @ u], 1) - lo) * sc + 2).long()).clamp(0, SHADOW_SIZE - 1)
    pd = pw @ f
    bias = 0.02 * float((Vw.max(0).values - Vw.min(0).values).max())
    lit = torch.zeros(len(q), dtype=F64, device=dev)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            lit += (szb[(q[:, 1] + dy).clamp(0, SHADOW_SIZE - 1), (q[:, 0] + dx).clamp(0, SHADOW_SIZE - 1)].to(F64)
                    >= pd - bias).to(F64)
    lit /= 9.0
    n = a[:, 2:5].to(F64)
    n = n / n.norm(dim=1, keepdim=True).clamp_min(1e-9)
    ndl = (n @ (-f)).clamp(0, 1)
    light = t(AMBIENT)[None] + t(SUN_COL)[None] * (ndl * lit)[:, None]
    # pixels in row-major order of the mask, the order ``msk[msk]`` uses
    order = torch.argsort(pix)
    return {"uv": a[order, 0:2].to(F64), "light": light[order], "mask": msk, "size": size, "pxPerUnit": S}


# ------------------------------------------------------------------ B
def grade(lab, k, gm, chroma=1.0, cmax=None, accent=None):
    """Tone grade with a soft toe at FLOOR and a midtone-weighted chroma lift (hue kept). k, gm, chroma broadcast.
    cmax: chroma ceiling of the lift, (HUE_BINS,) per hue bin (hue_ceiling: the DEF body's C95 among its pixels of that
    hue): a texel is lifted to at most max(its own C, its hue's ceiling), so a mostly-white unit whose C50 is far
    below the DEF's cannot push its few coloured texels (skin) past what the DEF shows for that hue.
    accent: A's L* per texel (step 8): where A is bright (ACCENT ramp) the graded L* stays >= ACCENT_KEEP x A's."""
    L = lab[..., 0].clamp(0, 100)
    L = 100 * k * (L / 100) ** gm
    L = torch.sqrt(L * L + FLOOR * FLOOR) - (np.sqrt(100 ** 2 + FLOOR ** 2) - 100) * (L / 100)
    L = L.clamp(0, 100)
    if accent is not None:
        t = ((accent - ACCENT[0]) / (ACCENT[1] - ACCENT[0])).clamp(0, 1)
        L = L + t * t * (3 - 2 * t) * torch.clamp(ACCENT_KEEP * accent - L, min=0)
    w = (1.2 * torch.exp(-((L - 50) / 40) ** 2)).clamp(0, 1)
    s = 1 + (chroma - 1) * w
    if cmax is not None:
        c0 = torch.hypot(lab[..., 1], lab[..., 2])
        cm = cmax[hue_bin(lab[..., 1], lab[..., 2])]
        s = torch.minimum(s, torch.clamp(cm / c0.clamp(min=1e-6), min=1.0))
    L, a, b = torch.broadcast_tensors(L, lab[..., 1] * s, lab[..., 2] * s)
    return torch.stack([L, a, b], -1)


HUE_BINS = 12


def hue_bin(a, b):
    return (torch.remainder(torch.atan2(b, a), 2 * np.pi) / (2 * np.pi) * HUE_BINS).long().clamp(0, HUE_BINS - 1)


def hue_ceiling(dlab, min_px=30, min_c=4.0):
    """Per hue bin (30 deg), the C95 of the DEF body pixels of that hue (chroma >= min_c); a bin with fewer than
    min_px such pixels takes the lowest populated bin's ceiling (a hue the DEF hardly shows gets no strong lift)."""
    c = torch.hypot(dlab[:, 1], dlab[:, 2])
    hb = hue_bin(dlab[:, 1], dlab[:, 2])
    out = torch.full((HUE_BINS,), float("nan"), dtype=F64, device=dlab.device)
    for i in range(HUE_BINS):
        sel = (hb == i) & (c >= min_c)
        if int(sel.sum()) >= min_px:
            out[i] = quant(c[sel], [95])[0]
    fill = torch.nan_to_num(out, nan=float("inf")).min()
    return torch.where(torch.isnan(out), fill if torch.isfinite(fill) else torch.tensor(min_c, dtype=F64, device=dlab.device), out)


def quant(x, q):
    return torch.quantile(x.to(F64), torch.as_tensor(q, dtype=F64, device=x.device) / 100.0, dim=-1)


def finish_vanilla(texA, geo, def_rgba, protect=None, metal=None, log=None, hue_src=None, hue_mask=None):
    """texA (H, W, 3) sRGB float in [0, 1] on the device; geo from load_geometry; def_rgba (h, w, 4) uint8 numpy
    DEF idle frame 0. protect: (H, W) weight in [0, 1] of texels that keep A (regions); metal: (H, W) metal weight.
    hue_src (H, W, 3) sRGB source base colour + hue_mask (H, W) Meshy metal weight: those texels take B's lightness
    but the source's a*b* (scaled by the lightness ratio), undoing the whole-unit A grade's tint of neutral metal.
    hue_src alone: source-neutral texels may not lose a* against the source (step 7, no drift toward green).
    Returns (texB (H, W, 3) sRGB float, log dict)."""
    log = {} if log is None else log
    dev = texA.device
    H, W = texA.shape[:2]
    cav = cavity(geo["Vbind"], geo["F"], geo["Nbind"])
    att, m1k = uv_attrs(geo, cav, ATTR_SIZE)
    m = TF.interpolate(m1k[None, None].to(F32), size=(H, W), mode="nearest")[0, 0] > 0.5
    att2 = TF.interpolate(att.permute(2, 0, 1)[None], size=(H, W), mode="bilinear", align_corners=False)[0].permute(1, 2, 0)
    wm = torch.zeros((H, W), dtype=F32, device=dev) if metal is None else metal.to(F32).clamp(0, 1) * m
    nonmetal = m & (wm < 0.5)
    log["metalTexelShare"] = round(float((wm[m] > 0.5).float().mean()), 4) if bool(m.any()) else 0.0
    lab = srgb_to_lab(texA.to(F32))
    r_box = max(1, int(round(8 * H / 2048)))
    # 1 detail: fine band x0.5 (metal texels keep theirs)
    base = masked_blur(lab, m, r_box)
    det = lab - base
    dscale = (0.5 + 0.5 * wm)[..., None]
    lab1 = base + dscale * det
    sdA = float(det[..., 0][nonmetal].to(F64).std()) if bool(nonmetal.any()) else 0.0
    log["fineL_sd_A"] = round(sdA, 4)
    log["fineL_sd_B"] = round(0.5 * sdA, 4)
    # 2 crevice: regress L on concavity, remove half of the predicted (centred) component
    L = lab1[..., 0][m].to(F64)
    X = att2[..., 2:][m].to(F64)
    Xc = X - X.mean(0)
    A_ = torch.cat([Xc, torch.ones((len(Xc), 1), dtype=F64, device=dev)], 1)
    beta = torch.linalg.solve(A_.T @ A_ + 1e-9 * torch.eye(A_.shape[1], dtype=F64, device=dev), A_.T @ L)
    pred = Xc @ beta[:-1]
    log["crevice_beta"] = [round(float(b), 3) for b in beta[:-1]]
    log["r_L_cavity_A"] = round(corr(L, pred), 4)
    full_pred = torch.zeros((H, W), dtype=F32, device=dev)
    full_pred[m] = pred.to(F32)
    lab2 = lab1.clone()
    lab2[..., 0] -= 0.5 * full_pred
    log["r_L_cavity_B"] = round(corr(lab2[..., 0][m], pred), 4)
    # 3 top-lit: k*(0.7*n_up + 0.3*(2h-1)), k bisected to r(L, n_up) = 0.20, k <= 12 L*; not on metal
    g = (0.7 * att2[..., 0] + 0.3 * (2 * att2[..., 1] - 1)) * (1 - wm)
    nup = att2[..., 0][m].to(F64)
    L2 = lab2[..., 0][m].to(F64)
    gm_ = g[m].to(F64)
    log["r_L_up_A"] = round(corr(lab[..., 0][m], nup), 4)
    lo_, hi_ = 0.0, 12.0
    if corr(L2 + hi_ * gm_, nup) < 0.20:
        k = hi_
        log["toplit_bound_hit"] = True
    else:
        for _ in range(30):
            k = (lo_ + hi_) / 2
            if corr(L2 + k * gm_, nup) < 0.20:
                lo_ = k
            else:
                hi_ = k
        log["toplit_bound_hit"] = False
    lab3 = lab2.clone()
    lab3[..., 0] += k * g * m
    log["toplit_k"] = round(float(k), 3)
    log["r_L_up_B"] = round(corr(lab3[..., 0][m], nup), 4)
    # 4 grade: fit (k, gamma) on the rendered body against the DEF idle body
    gb = gbuffer(geo)
    em = erode(gb["mask"], 2)[gb["mask"]]
    dfa = torch.as_tensor(def_rgba, device=dev)
    dm = erode(dfa[..., 3] == 255, 2)
    dlab = srgb_to_lab(dfa[..., :3][dm].to(F64) / 255.0)
    if len(dlab) < 50:
        raise ValueError(f"DEF idle frame has only {len(dlab)} opaque body pixels")
    tgt = quant(dlab[:, 0], [5, 50, 95])
    log["DEF_body_L_p5_p50_p95"] = [round(float(x), 1) for x in tgt]
    defC50 = float(quant(torch.hypot(dlab[:, 1], dlab[:, 2]), [50])[0])
    log["DEF_body_C50"] = round(defC50, 2)
    cmax = hue_ceiling(dlab)
    log["DEF_body_C95_byHue"] = [round(float(c), 1) for c in cmax]
    labS = sample_nearest(lab3, gb["uv"]).to(F64)[em]
    light = gb["light"][em]
    accS = sample_nearest(lab[..., 0:1], gb["uv"]).to(F64)[em][:, 0]

    def rendered(kk, gg, ch=1.0, acc=None):
        alb = lab_to_srgb(grade(labS[None], kk, gg, ch, cmax, None if acc is None else acc[None]))
        return srgb_to_lab(lin_to_srgb(srgb_to_lin(alb) * light[None]))
    ks = torch.linspace(K_LO, K_HI, K_N, dtype=F64, device=dev)
    gs = torch.linspace(G_LO, G_HI, G_N, dtype=F64, device=dev)
    errs = []
    for kk in ks:
        Lr = rendered(kk, gs[:, None])[..., 0]
        p = quant(Lr, [50, 95])                               # (2, G_N)
        errs.append((p[0] - tgt[1]) ** 2 + (p[1] - tgt[2]) ** 2)
    e = torch.stack(errs)                                      # (K_N, G_N), k-major like the prototype's loop
    bi = int(torch.argmin(e.reshape(-1)))
    kk, gg = float(ks[bi // len(gs)]), float(gs[bi % len(gs)])
    log["grade_k"], log["grade_gamma"] = round(kk, 3), round(gg, 3)
    log["grade_bound_hit"] = bool(bi // len(gs) in (0, len(ks) - 1) or bi % len(gs) in (0, len(gs) - 1))
    labA_r = srgb_to_lab(lin_to_srgb(srgb_to_lin(sample_nearest(texA, gb["uv"]).to(F64)[em]) * light))
    cA = float(quant(torch.hypot(labA_r[:, 1], labA_r[:, 2]), [50])[0])
    tgtC = max(cA, defC50)
    cs = torch.linspace(1.0, C_HI, C_N, dtype=F64, device=dev)
    lr = rendered(kk, gg, cs[:, None], accS)
    c50 = quant(torch.hypot(lr[..., 1], lr[..., 2]), [50])[0]
    ok = torch.nonzero(c50 >= tgtC)
    ch = float(cs[int(ok[0])]) if len(ok) else C_HI
    log["chroma_scale"] = round(ch, 2)
    log["chroma_target_C50"] = round(tgtC, 1)
    log["chroma_bound_hit"] = bool(ch >= C_HI)
    labB = grade(lab3, kk, gg, ch, cmax, lab[..., 0])
    t8 = ((lab[..., 0] - ACCENT[0]) / (ACCENT[1] - ACCENT[0])).clamp(0, 1) * m
    up = labB[..., 0] - grade(lab3, kk, gg, ch, cmax)[..., 0]
    sel8 = (t8 > 0.5) & (up > 0.5)
    log["accentTexelShare"] = round(float(sel8.float().mean() / m.float().mean().clamp(min=1e-9)), 4)
    log["accent_dL_mean"] = round(float(up[sel8].mean()), 2) if bool(sel8.any()) else 0.0
    log["accent_dL_brightMean"] = round(float(up[(t8 > 0.5)].mean()), 2) if bool((t8 > 0.5).any()) else 0.0
    # 1 (cont.): re-hold the fine band at 0.5x A's after grading (metal texels keep the graded band)
    bB = masked_blur(labB, m, r_box)
    dB = labB - bB
    sdB = float(dB[..., 0][nonmetal].to(F64).std()) if bool(nonmetal.any()) else 0.0
    f = 0.5 * sdA / max(sdB, 1e-6)
    log["fine_restore_factor"] = round(f, 3)
    fx = (f * (1 - wm) + wm)[..., None]
    labB = bB + fx * dB
    labB[..., 0] = torch.maximum(labB[..., 0], torch.clamp(labB[..., 0] + 100, max=FLOOR))
    labB[..., 0] = torch.where(m, torch.clamp(labB[..., 0], min=FLOOR * 0.85), labB[..., 0])
    if hue_src is not None and hue_mask is not None:
        # 6 metal hue: the whole-unit v7c white balance + luminance-banded a*b* transfer, fitted to a skin-dominated
        # DEF body, tint grey Meshy metal (h3_gremlin ball and chain: source hue 9 deg -> 97 deg, green). Keep the
        # source hue and chroma (chroma scaled with the lightness change, [0.5, 1.5]); B's lightness stays.
        wh = hue_mask.to(F32).clamp(0, 1) * m
        if protect is not None:
            wh = wh * (1 - protect.to(F32).clamp(0, 1))
        labS = srgb_to_lab(hue_src.to(F32))
        cs = torch.hypot(labS[..., 1], labS[..., 2])
        t = ((cs - HUE_CHROMA[0]) / (HUE_CHROMA[1] - HUE_CHROMA[0])).clamp(0, 1)
        wh = wh * (1 - t * t * (3 - 2 * t))       # neutral metal only: coloured texels follow the unit grade
        sc = (labB[..., 0] / labS[..., 0].clamp(min=1.0)).clamp(0.5, 1.5)
        ab_src = labS[..., 1:] * sc[..., None]
        before = labB[..., 1:].clone()
        labB[..., 1:] = before * (1 - wh[..., None]) + ab_src * wh[..., None]
        sel = (wh > 0.5) & m
        log["metalHueTexelShare"] = round(float(sel.float().mean() / m.float().mean().clamp(min=1e-9)), 4)
        if bool(sel.any()):
            def hue(ab):
                return float(torch.rad2deg(torch.atan2(ab[:, 1].mean(), ab[:, 0].mean())) % 360)
            log["metalHue_ab_before"] = [round(float(x), 2) for x in before[sel].mean(0)]
            log["metalHue_ab_after"] = [round(float(x), 2) for x in labB[..., 1:][sel].mean(0)]
            log["metalHue_deg_before_after"] = [round(hue(before[sel]), 1), round(hue(labB[..., 1:][sel]), 1)]
            log["metalHue_dab_mean"] = round(float((labB[..., 1:][sel] - before[sel]).norm(dim=-1).mean()), 2)
    if hue_src is not None:
        # 7 neutral guard: the same v7c tint pushes near-neutral non-metal texels (grey hair, cloth, gremlin's
        # grey trim) toward green. Source-neutral texels (C* ramp-out HUE_CHROMA) may not lose a* against their
        # source (a* scaled with the lightness change): no drift toward green; warm/cool white balance kept.
        labS = srgb_to_lab(hue_src.to(F32))
        cs = torch.hypot(labS[..., 1], labS[..., 2])
        t = ((cs - HUE_CHROMA[0]) / (HUE_CHROMA[1] - HUE_CHROMA[0])).clamp(0, 1)
        wn = (1 - t * t * (3 - 2 * t)) * m
        if protect is not None:
            wn = wn * (1 - protect.to(F32).clamp(0, 1))
        sc = (labB[..., 0] / labS[..., 0].clamp(min=1.0)).clamp(0.5, 1.5)
        a0 = labB[..., 1].clone()
        lo = labS[..., 1] * sc
        labB[..., 1] = a0 + wn * torch.clamp(lo - a0, min=0)
        sel = (wn > 0.5) & m & (lo - a0 > 0.5)
        log["neutralGuardTexelShare"] = round(float(sel.float().mean() / m.float().mean().clamp(min=1e-9)), 4)
        log["neutralGuard_da_mean"] = round(float((labB[..., 1] - a0)[sel].mean()), 2) if bool(sel.any()) else 0.0
    texB = lab_to_srgb(labB)
    if protect is not None:
        wp = protect.to(F32).clamp(0, 1)[..., None]
        texB = lin_to_srgb(srgb_to_lin(texB) * (1 - wp) + srgb_to_lin(texA.to(F32)) * wp)
        log["protectedTexelShare"] = round(float((protect[m] > 0.5).float().mean()), 4)
    # 5 gutters
    texB = push_pull(texB, m)
    labBm = srgb_to_lab(texB[m].to(F64))
    labAm = srgb_to_lab(texA[m].to(F64))
    log["albedo_A_L_p5_p50_p95"] = [round(float(x), 1) for x in quant(labAm[:, 0], [5, 50, 95])]
    log["albedo_B_L_p5_p50_p95"] = [round(float(x), 1) for x in quant(labBm[:, 0], [5, 50, 95])]
    for nm, tex in (("A", texA), ("B", texB)):
        rl = srgb_to_lab(lin_to_srgb(srgb_to_lin(sample_nearest(tex, gb["uv"]).to(F64)[em]) * light))
        log[f"render_{nm}_L_p5_p50_p95"] = [round(float(x), 1) for x in quant(rl[:, 0], [5, 50, 95])]
        log[f"render_{nm}_C50"] = round(float(quant(torch.hypot(rl[:, 1], rl[:, 2]), [50])[0]), 1)
    return texB, log


# ------------------------------------------------------------------ unit glue (look.py's finish stage)
def unit_inputs(unit, spec, dev, glb_bytes: bytes | None = None):
    """Everything finish_vanilla needs for a look unit, from disk (no Blender, no views). glb_bytes overrides the
    geometry source (e.g. a frozen look_delivered.glb: same geometry, only the body image differs)."""
    import look as LK
    import spec as S
    from glbpatch import Glb
    outd = S.out_dir(unit)
    work = outd / "work"
    src, where = (glb_bytes, "override") if glb_bytes is not None else LK.resolve_source(unit)
    fd, name = tempfile.mkstemp(suffix=".glb", dir=str(work))
    os.close(fd)
    tmp = Path(name)
    try:
        tmp.write_bytes(src)
        geo = load_geometry(tmp, dev)
    finally:
        tmp.unlink(missing_ok=True)
    clips = S.clip_segments(unit)
    t0 = clips["Unit_Idle"]["masterFrames"][0]
    def_png = S.frames_meta(unit)["sources"][t0]
    def_rgba = np.asarray(Image.open(def_png).convert("RGBA"))
    lt = spec["lighting"]
    wr = wm = None
    ctx = {"srcGlb": lambda: src}
    a_png = outd / "basecolor_a.png"
    size = Image.open(a_png).size[1] if a_png.is_file() else Image.open(outd / "basecolor.png").size[1]
    if lt.get("regions"):
        import regions as RG
        W = RG.region_weights(spec, ctx, work, size)
        wr = torch.as_tensor(np.clip(sum(W.values()), 0, 1), dtype=F32, device=dev) if W else None
    if lt.get("metal"):
        import metal as MT
        wm = torch.as_tensor(MT.texture_mask(lt["metal"], Glb(src), size, None), dtype=F32, device=dev)
    # metal hue: Meshy metallic mask (HUE_MASK, every unit, independent of lighting.metal) + source colour
    import metal as MT
    wh = hs = None
    try:
        wh = MT.texture_mask({"mask": HUE_MASK}, Glb(src), size, None)
    except ValueError:
        wh = None                                   # no single metallicRoughness texture: nothing to protect
    # source base colour: metal hue (step 6) and neutral guard (step 7)
    sp = work / "source_basecolor.png"
    im = None
    if sp.is_file():
        im = Image.open(sp)
    elif glb_bytes is None:
        g = Glb(src)
        im = Image.open(io.BytesIO(g.image_bytes(g.body_base_color_image())))
    if im is not None:
        im = im.convert("RGB").resize((size, size), Image.BILINEAR)
        hs = torch.as_tensor(np.asarray(im, np.float32) / 255.0, device=dev)
    if wh is not None and float(wh.max()) > 0.5:
        if hs is None:
            raise ValueError(f"{unit}: no work/source_basecolor.png for the metal hue step (geometry override given)")
        wh = torch.as_tensor(wh, dtype=F32, device=dev)
    else:
        wh = None
    return {"geo": geo, "def": def_rgba, "defFrame": def_png, "protect": wr, "metal": wm, "sourceFrom": where,
            "sourceGlbSha256": hashlib.sha256(src).hexdigest(), "hueSrc": hs, "hueMask": wh}


def load_png(p: Path, dev):
    return torch.as_tensor(np.asarray(Image.open(p).convert("RGB"), np.float32) / 255.0, device=dev)


def save_png(tex, p: Path):
    Image.fromarray((tex.clamp(0, 1).cpu().numpy() * 255).round().astype(np.uint8)).save(p, optimize=False)


def run_unit(unit, spec, a_png: Path, out_png: Path, dev, glb_bytes: bytes | None = None) -> dict:
    inp = unit_inputs(unit, spec, dev, glb_bytes)
    texA = load_png(a_png, dev)
    texB, lg = finish_vanilla(texA, inp["geo"], inp["def"], protect=inp["protect"], metal=inp["metal"],
                              hue_src=inp["hueSrc"], hue_mask=inp["hueMask"])
    save_png(texB, out_png)
    lg.update({"defFrame": Path(inp["defFrame"]).as_posix(), "sourceFrom": inp["sourceFrom"],
               "sourceGlbSha256": inp["sourceGlbSha256"], "regionsProtected": inp["protect"] is not None,
               "metalMasked": inp["metal"] is not None, "metalHueKept": inp["hueMask"] is not None, "neutralGuard": inp["hueSrc"] is not None,
               "device": str(dev.type)})
    return lg


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("unit")
    ap.add_argument("--device", default="cuda", choices=("cuda", "cpu"))
    ap.add_argument("--a", help="A base colour (default artifacts/homm3_unit_look/<unit>/basecolor_a.png, else basecolor.png)")
    ap.add_argument("--out", required=True, help="where to write B (a dry run never touches the unit's artifacts)")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    import spec as S
    dev = device(a.device)
    spec = S.load(S.spec_path(a.unit))
    outd = S.out_dir(a.unit)
    ap_ = Path(a.a) if a.a else (outd / "basecolor_a.png" if (outd / "basecolor_a.png").is_file() else outd / "basecolor.png")
    lg = run_unit(a.unit, spec, ap_, Path(a.out), dev)
    lg["aPng"] = ap_.as_posix()
    if a.json:
        Path(a.json).write_text(json.dumps(lg, indent=1))
    print(json.dumps(lg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
