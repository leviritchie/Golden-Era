"""lighting.metal: yaw-invariant baked reflection on metal texels (docs/homm3_unit_look_pipeline.md, 'Metal').

Hex/Lit has no specular and no emission (rgb = albedo * (sun * N.L * shadow + ambient)), so a metal can only
read as shiny if the reflection is baked into the base colour. The bake must survive the unit turning, so the
reflection depends on the rest-pose normal's elevation (and mesh convexity), never on its yaw:

  env(n)  = sigmoid((n_z - horizon) / width)            sky above a sharp horizon, dark ground below
  e       = env + edge * convexity(pointiness)          convex edges catch the sky, crevices fall off
  L-gain  = exp(strength * (e - median_metal(e)) + bias)
  chroma  = x (1 - hiDesat * env^2) * (1 + loSat * (1 - env))   highlights go pale, the ground side goes deep

applied only on the metal texels, blended in by the metal mask. The mask comes from the source GLB's own PBR
metallic texture (Meshy bakes one in the base colour's UV space: glTF metallicRoughness, B = metallic,
G = roughness), or from a v6m material class when a unit has no usable metallic map.

The five reflection parameters are fitted so the relit metal texels' L* / C* percentiles match the DEF's metal
region (the DEF pixels in ``defRegion``'s Lab window, closed spatially so the pale highlights and deep
shadows that fall outside the hue window but sit inside the metal count too). The metal-region metric is the
L-hist distance between those two, per fit view.

The block is opt-in (``lighting.metal``); a spec without it never imports this module.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage, optimize

_PREBAKE = str(Path(__file__).resolve().parents[1] / "homm3_prebake")
if _PREBAKE not in sys.path:
    sys.path.insert(0, _PREBAKE)
import prebake_lab as pl  # noqa: E402

KEYS = {"mask", "defRegion", "normalDetail", "fit", "params", "notes"}
MASK_KEYS = {"source", "metallic", "roughnessMax", "materialClass", "blur"}
DEFREGION_KEYS = {"class", "window", "projected", "erode", "close"}
PARAM_NAMES = ["strength", "horizon", "width", "edge", "bias", "hiDesat", "loSat"]
PARAM_BOUNDS = {"strength": (0.0, 4.0), "horizon": (-0.6, 0.8), "width": (0.03, 0.6), "edge": (0.0, 1.0),
                "bias": (-1.0, 1.0), "hiDesat": (0.0, 0.95), "loSat": (0.0, 1.5)}
PARAM_START = {"strength": 1.2, "horizon": 0.1, "width": 0.15, "edge": 0.2, "bias": 0.0, "hiDesat": 0.4,
               "loSat": 0.3}
DEFAULT_MASK = {"source": "meshyMetallic", "metallic": [0.45, 0.8], "blur": 1.5}


# ----------------------------------------------------------------------------- validation
def validate(block, class_names) -> list[str]:
    """Spec errors for ``lighting.metal`` (class_names: the v6m class names, or [] for v7c)."""
    e = []
    if not isinstance(block, dict):
        return ["lighting.metal must be an object"]
    for k in set(block) - KEYS:
        e.append(f"lighting.metal: unknown key {k!r}")
    mk = block.get("mask", DEFAULT_MASK)
    if not isinstance(mk, dict):
        return e + ["lighting.metal.mask must be an object"]
    for k in set(mk) - MASK_KEYS:
        e.append(f"lighting.metal.mask: unknown key {k!r}")
    src = mk.get("source", "meshyMetallic")
    if src == "meshyMetallic":
        lohi = mk.get("metallic", DEFAULT_MASK["metallic"])
        if not (isinstance(lohi, list) and len(lohi) == 2 and 0 <= lohi[0] < lohi[1] <= 1):
            e.append("lighting.metal.mask.metallic must be [lo, hi] with 0 <= lo < hi <= 1")
        rm = mk.get("roughnessMax")
        if rm is not None and not (isinstance(rm, list) and len(rm) == 2 and 0 <= rm[0] < rm[1] <= 1):
            e.append("lighting.metal.mask.roughnessMax must be [lo, hi] with 0 <= lo < hi <= 1")
    elif src == "materialClass":
        if mk.get("materialClass") not in class_names:
            e.append(f"lighting.metal.mask.materialClass must name a v6m class ({class_names})")
    else:
        e.append("lighting.metal.mask.source must be 'meshyMetallic' or 'materialClass'")
    dr = block.get("defRegion")
    if not isinstance(dr, dict):
        e.append("lighting.metal.defRegion {class | window | projected} is required (the DEF pixels the metal is fitted to)")
    else:
        for k in set(dr) - DEFREGION_KEYS:
            e.append(f"lighting.metal.defRegion: unknown key {k!r}")
        if sum(k in dr for k in ("class", "window", "projected")) != 1:
            e.append("lighting.metal.defRegion needs exactly one of class / window / projected")
        elif "projected" in dr and dr["projected"] is not True:
            e.append("lighting.metal.defRegion.projected must be true")
        elif "class" in dr and dr["class"] not in class_names:
            e.append(f"lighting.metal.defRegion.class must name a v6m class ({class_names})")
        elif "window" in dr and (not isinstance(dr["window"], dict) or not dr["window"]
                                 or set(dr["window"]) - {"chroma", "chromaMax", "hue", "lightness"}):
            e.append("lighting.metal.defRegion.window must be a non-empty {chroma, chromaMax, hue, lightness} object")
    nd = block.get("normalDetail", 0.5)
    if not (isinstance(nd, (int, float)) and 0 <= nd <= 1):
        e.append("lighting.metal.normalDetail must be in [0, 1]")
    if block.get("fit", True) not in (True, False):
        e.append("lighting.metal.fit must be a boolean")
    ps = block.get("params")
    if ps is not None:
        if not isinstance(ps, dict) or set(ps) - set(PARAM_NAMES):
            e.append(f"lighting.metal.params keys must be among {PARAM_NAMES}")
        else:
            for k, v in ps.items():
                lo, hi = PARAM_BOUNDS[k]
                if not (isinstance(v, (int, float)) and lo <= v <= hi):
                    e.append(f"lighting.metal.params.{k} must be in [{lo}, {hi}]")
    if block.get("fit", True) is False and not ps:
        e.append("lighting.metal.fit=false needs params")
    return e


# ----------------------------------------------------------------------------- mask
def metallic_roughness_image(glb) -> bytes | None:
    """PNG/JPEG bytes of the body material's metallicRoughness texture, or None."""
    mesh = glb.json["meshes"][glb.body_mesh_index()]
    mats = sorted({p.get("material") for p in mesh["primitives"]} - {None})
    imgs = set()
    for mi in mats:
        t = glb.json["materials"][mi].get("pbrMetallicRoughness", {}).get("metallicRoughnessTexture")
        if t is not None:
            imgs.add(glb.json["textures"][t["index"]]["source"])
    if len(imgs) != 1:
        return None
    return glb.image_bytes(imgs.pop())


def smooth(x, lo, hi):
    t = np.clip((x - lo) / max(hi - lo, 1e-6), 0, 1)
    return t * t * (3 - 2 * t)


def meshy_metal_mask(glb, size: int, mk: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(mask, metallic, roughness) at ``size`` from the GLB's metallicRoughness texture (fails closed)."""
    b = metallic_roughness_image(glb)
    if b is None:
        raise ValueError("lighting.metal.mask meshyMetallic: the body material has no single metallicRoughness texture")
    im = Image.open(io.BytesIO(b)).convert("RGB").resize((size, size), Image.BILINEAR)
    a = np.asarray(im, np.float32) / 255
    met, rough = a[..., 2], a[..., 1]
    w = smooth(met, *mk.get("metallic", DEFAULT_MASK["metallic"]))
    if mk.get("roughnessMax"):
        lo, hi = mk["roughnessMax"]
        w = w * (1 - smooth(rough, lo, hi))
    return w, met, rough


def texture_mask(block, glb, size, class_info) -> np.ndarray:
    mk = block.get("mask", DEFAULT_MASK)
    if mk.get("source", "meshyMetallic") == "meshyMetallic":
        w = meshy_metal_mask(glb, size, mk)[0]
    else:
        names = class_info["_names"]
        w = class_info["_wtex"][..., names.index(mk["materialClass"])]
    return np.clip(ndimage.gaussian_filter(w.astype(np.float32), mk.get("blur", 1.5)), 0, 1)


# ----------------------------------------------------------------------------- DEF metal region
def projected_mask(ctx, vn, W) -> np.ndarray:
    """Mesh pixels of view ``vn`` whose texture metal mask is above 0.5 (sampled through the view's uv and
    downsampled like the colour, so it is pixel-aligned with the DEF frame)."""
    v, vmv = ctx["views"][vn], ctx["vmeta"]["views"][vn]
    wv, a = pl.downsample(pl.sample_tex(W[..., None], v["uv"]), v["alpha"], vmv["supersample"])
    return (a > 0.9) & (wv[..., 0] > 0.5)


def def_region(lab, body, dr: dict, classes: list | None, proj: np.ndarray | None = None) -> np.ndarray:
    """DEF pixels of the metal: the Lab window, the v6m class (assigned as v6m assigns), or (``projected``) the
    DEF body under the mesh's own projected metal mask, eroded by ``erode`` so silhouette slop stays out;
    then closed spatially."""
    import lighting as LT
    if dr.get("projected"):
        if proj is None:
            raise ValueError("lighting.metal.defRegion.projected needs the projected mesh metal mask")
        core = ndimage.binary_erosion(proj, iterations=int(dr.get("erode", 1))) if dr.get("erode", 1) else proj.copy()
    elif "class" in dr:
        wn = LT.window_weights(lab, classes)
        wr = np.clip(1 - wn.sum(-1, keepdims=True), 0, 1)
        w = np.concatenate([wn, wr], -1)
        w = w / np.maximum(w.sum(-1, keepdims=True), 1e-6)
        i = [c["name"] for c in classes].index(dr["class"])
        core = (w.argmax(-1) == i) & (w.max(-1) > 0.6)
    else:
        win = dict(dr["window"])
        cmax = win.pop("chromaMax", None)          # low-chroma metals (steel): weight falls off over [lo, hi]
        w = LT.window_weights(lab, [win])[..., 0] if win else np.ones(lab.shape[:2], np.float32)
        if cmax:
            w = w * (1 - smooth(np.hypot(lab[..., 1], lab[..., 2]), *cmax))
        core = w > 0.5
    core &= body
    r = int(dr.get("close", 2))
    if r > 0:
        core = ndimage.binary_closing(core, iterations=r) & body
    return core


# ----------------------------------------------------------------------------- reflection
def env_terms(m: dict, detail: float) -> tuple[np.ndarray, np.ndarray]:
    """(n_z, convexity) per texel: blended geometric/normal-map normal elevation, pointiness in [-1, 1]."""
    ng, nm = m["nrm_geo"], m["nrm_map"]
    ng = ng / np.maximum(np.linalg.norm(ng, axis=-1, keepdims=True), 1e-4)
    nm = nm / np.maximum(np.linalg.norm(nm, axis=-1, keepdims=True), 1e-4)
    n = ng + detail * (nm - ng)
    n = n / np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-4)
    conv = np.clip((m["pointiness"] - 0.5) / 0.06, -1, 1)
    return n[..., 2].astype(np.float32), conv.astype(np.float32)


def reflect(base_lin, nz, conv, p: dict, e_med: float):
    """Metal colour for base (N,3) linear rgb at elevation nz / convexity conv (all flat arrays)."""
    env = 1 / (1 + np.exp(-(nz - p["horizon"]) / max(p["width"], 1e-3)))
    e = env + p["edge"] * conv
    gain = np.exp(p["strength"] * (e - e_med) + p["bias"])
    lum = np.maximum(pl.luminance(base_lin), 1e-5)[..., None]
    out_lum = np.clip(lum * gain[..., None], 0, 1)
    chroma = base_lin / lum
    cs = (1 - p["hiDesat"] * env ** 2) * (1 + p["loSat"] * (1 - env))
    chroma = 1 + cs[..., None] * (chroma - 1)
    return np.clip(out_lum * chroma, 0, 1), env


def median_e(nz, conv, mask, p):
    env = 1 / (1 + np.exp(-(nz - p["horizon"]) / max(p["width"], 1e-3)))
    e = env + p["edge"] * conv
    return float(np.median(e[mask]))


def apply_params(tex, m, W, nz, conv, p) -> np.ndarray:
    sel = (W > 0.02) & m["valid"]
    em = median_e(nz, conv, (W > 0.5) & m["valid"], p)
    out = tex.copy()
    met, _ = reflect(tex[sel], nz[sel], conv[sel], p, em)
    out[sel] = (1 - W[sel, None]) * tex[sel] + W[sel, None] * met
    return out.astype(np.float32)


# ----------------------------------------------------------------------------- fit + metric
def _samples(ctx, W, views, fit_views, cond, extras, n_max=30000):
    out = {}
    for vn in fit_views:
        v = views[vn]
        sel = np.nonzero(v["alpha"] > 0.99)
        uv = v["uv"][sel]
        w = pl.sample_tex(W[..., None], uv[None])[0][:, 0]
        keep = w > 0.7
        rows, cols = sel[0][keep], sel[1][keep]
        if len(rows) == 0:
            continue
        idx = np.random.default_rng(5).choice(len(rows), size=min(n_max, len(rows)), replace=False)
        rows, cols = rows[idx], cols[idx]
        light = pl.runtime_light(v, cond)
        if extras and extras.get(vn) is not None:
            light = light + extras[vn]
        out[vn] = (v["uv"][rows, cols], light[rows, cols])
    return out


def def_targets(ctx, fit_views, dr, classes, W=None):
    labs, per = [], {}
    for vn in fit_views:
        rec = ctx["def"][vn]
        lab = pl.lin_to_lab(pl.srgb_to_lin(rec["rgba"][..., :3]))
        proj = projected_mask(ctx, vn, W) if dr.get("projected") else None
        reg = def_region(lab, rec["bodyNoFx"], dr, classes, proj)
        per[vn] = lab[reg]
        labs.append(lab[reg])
    return np.concatenate(labs), per


def fit(tex, m, W, nz, conv, ctx, fit_views, block, classes, cond, extras) -> tuple[dict, dict]:
    """Fit the reflection params to the DEF metal region; returns (params, report)."""
    dr = block["defRegion"]
    tgt_lab, per_def = def_targets(ctx, fit_views, dr, classes, W)
    if len(tgt_lab) < 200:
        raise ValueError(f"lighting.metal: only {len(tgt_lab)} DEF metal pixels in the fit views")
    smp = _samples(ctx, W, ctx["views"], fit_views, cond, extras)
    uv = np.concatenate([u for u, _ in smp.values()])
    light = np.concatenate([l for _, l in smp.values()])
    if len(uv) < 200:
        raise ValueError(f"lighting.metal: only {len(uv)} visible metal texels in the fit views")
    base = pl.sample_tex(tex, uv[None])[0]
    snz = pl.sample_tex(nz[..., None], uv[None])[0][:, 0]
    sconv = pl.sample_tex(conv[..., None], uv[None])[0][:, 0]
    mvalid = (W > 0.5) & m["valid"]
    q = np.linspace(3, 97, 19)
    tL = np.percentile(tgt_lab[:, 0], q)
    tC = np.percentile(np.hypot(tgt_lab[:, 1], tgt_lab[:, 2]), q)
    fixed = dict(block.get("params") or {})
    free = [k for k in PARAM_NAMES if k not in fixed]

    def unpack(x):
        p = dict(PARAM_START, **fixed)
        p.update(dict(zip(free, x)))
        return p

    def cost(x):
        p = unpack(x)
        for k in free:
            lo, hi = PARAM_BOUNDS[k]
            if not lo <= p[k] <= hi:
                return 1e6
        em = median_e(nz, conv, mvalid, p)
        col, _ = reflect(base, snz, sconv, p, em)
        lab = pl.lin_to_lab(col * light)
        return (np.mean(np.abs(np.percentile(lab[:, 0], q) - tL))
                + 0.5 * np.mean(np.abs(np.percentile(np.hypot(lab[:, 1], lab[:, 2]), q) - tC)))

    if block.get("fit", True) and free:
        starts = [[PARAM_START[k] for k in free]]
        alt = dict(PARAM_START, strength=2.0, horizon=0.3, width=0.08, edge=0.4)
        starts.append([alt[k] for k in free])
        res = min((optimize.minimize(cost, np.array(s, float), method="Nelder-Mead",
                                     options={"maxiter": 1200, "xatol": 1e-3, "fatol": 1e-3}) for s in starts),
                  key=lambda r: r.fun)
        p, c = unpack(res.x), float(res.fun)
    else:
        p, c = unpack([]), float(cost(np.array([])))
    p = {k: round(float(v), 4) for k, v in p.items()}
    hits = []
    for k in free:
        lo, hi = PARAM_BOUNDS[k]
        if abs(p[k] - lo) <= 0.01 * (hi - lo) or abs(p[k] - hi) <= 0.01 * (hi - lo):
            hits.append(f"metal:{k}={p[k]}")
    rep = {"params": p, "cost": round(c, 3), "defPixels": int(len(tgt_lab)), "texSamples": int(len(uv)),
           "defLp5_50_95": np.round(np.percentile(tgt_lab[:, 0], [5, 50, 95]), 1).tolist(), "boundHits": hits}
    return p, rep


def region_metric(tex_before, tex_after, W, ctx, views_, dr, classes, cond) -> dict:
    """Per-view L-hist distance of the relit metal texels (mask > 0.5) to the DEF metal region, before/after."""
    import vfx as VX
    per = {}
    for vn in views_:
        rec = ctx["def"][vn]
        lab = pl.lin_to_lab(pl.srgb_to_lin(rec["rgba"][..., :3]))
        # metal pixels of the render: the texture mask sampled through the view's uv, downsampled like the colour
        sel = projected_mask(ctx, vn, W)
        ref = lab[..., 0][def_region(lab, rec["bodyNoFx"], dr, classes, sel)]
        if ref.size < 50:
            continue
        v, vmv = ctx["views"][vn], ctx["vmeta"]["views"][vn]
        row = {n: VX.lit_render(t, v, vmv, cond)[0] for n, t in (("before", tex_before), ("after", tex_after))}
        if sel.sum() < 50:
            continue
        per[vn] = {n: round(pl.hist_distance(pl.lin_to_lab(c)[..., 0][sel], ref), 2) for n, c in row.items()}
        per[vn]["Lp5_50_95"] = {n: np.round(np.percentile(pl.lin_to_lab(c)[..., 0][sel], [5, 50, 95]), 1).tolist()
                                for n, c in row.items()}
        per[vn]["defLp5_50_95"] = np.round(np.percentile(ref, [5, 50, 95]), 1).tolist()
    if not per:
        return {"views": {}}
    return {"views": per,
            "meanBefore": round(float(np.mean([r["before"] for r in per.values()])), 2),
            "meanAfter": round(float(np.mean([r["after"] for r in per.values()])), 2)}


# ----------------------------------------------------------------------------- pipeline entry
def run(tex, m, block, ctx, fit_views, class_info, classes, cond, extras) -> tuple[np.ndarray, dict]:
    """lighting.run's hook: the graded texture with the metal reflection applied, and the metrics part."""
    for k in ("nrm_geo", "nrm_map", "pointiness"):
        if k not in m:
            raise RuntimeError(f"lighting.metal needs the bake extra {k!r}")
    from glbpatch import Glb
    W = texture_mask(block, Glb(ctx["srcGlb"]()), tex.shape[0], class_info) * m["valid"]
    if (W > 0.5).sum() < 200:
        raise ValueError(f"lighting.metal: the metal mask covers only {int((W > 0.5).sum())} texels")
    nz, conv = env_terms(m, block.get("normalDetail", 0.5))
    p, rep = fit(tex, m, W, nz, conv, ctx, fit_views, block, classes, cond, extras)
    out = apply_params(tex, m, W, nz, conv, p)
    rep["maskShare"] = round(float((W[m["valid"]] > 0.5).mean()), 3)
    mm = region_metric(tex, out, W, ctx, ctx["reviewViews"], block["defRegion"], classes, cond)
    rep["regionLhist"] = {"before": mm.get("meanBefore"), "after": mm.get("meanAfter"),
                          "views": {k: {"before": v["before"], "after": v["after"]} for k, v in mm["views"].items()}}
    return out, rep
