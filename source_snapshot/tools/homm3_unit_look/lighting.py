"""Lighting stage: fit the spec's grade mode against the DEF and write the prebaked base colour.

Modes (docs/homm3_unit_look_pipeline.md):
  v7c  whole-unit grade: v6 bake + fine cavity + chroma detail + toe grade + luminance-banded a*b*
       transfer + brightness-neutral wet speckle (the Behemoth recipe, prebake_lab v7c_gloss).
  v6m  per-material grade: soft material classes, each with its own shading power and grade fitted
       to the same class of DEF pixels (the Titan recipe, titan_prebake.py), generalised: classes come
       from ``knobs.classes`` (hue/chroma windows) or, without it, from k-means on the texture.

DEF targets are the DEF body pixels of the fit frames minus every defFlipbook layer's effect pixels,
on frames where no dynamic light exceeds its floor; every dynamic light is held at its floor while the
grade is fitted (effectLight.floor). ``lighting.regions`` (regions.py) grade their own texels against
their own DEF region first; the unit-level mode is then fitted on the rest only, and the textures are
composed by region weight. Steady ``bakedGlow`` is applied after the grade.
Uses tools/homm3_prebake/prebake_lab.py functions (imported, not modified).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage, optimize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/homm3_prebake"))
import prebake_lab as pl  # noqa: E402

import masks as mk  # noqa: E402

V7C_DEFAULTS = {"aoGamma": 1.4, "skyFloor": 0.35, "heightDepth": 0.35, "heightPower": 0.6,
                "detailAmount": 1.0, "detailSigma": 12.0, "chromaDetail": 0.6, "chromaSigma": 16.0,
                "cavityGamma": 2.0, "creviceGammaScale": 2.0, "toeMax": 0.08, "bandCount": 8,
                "bandStrength": 1.0, "bandLocalSigma": 24.0, "glossAmount": 0.6, "glossFloor": 0.15,
                "glossNeutral": 1.0}
V6M_DEFAULTS = {"aoGamma": 1.4, "creviceGammaScale": 2.0, "skyFloor": 0.35, "heightDepth": 0.15,
                "heightPower": 0.6, "detailAmount": 1.0, "detailSigma": 12.0, "classCount": 3,
                "classSoftness": 8.0, "restClass": "rest", "restShadingPower": 1.2, "classBlur": 1.5}
# grade bounds: [exposure, gamma, sat, wr, wb, toe]
V7C_BOUNDS = [(0.0, 12.0), (0.5, 1.8), (0.5, 2.0), (0.7, 1.5), (0.6, 1.3), (0.0, None)]
V6M_BOUNDS = [(0.0, 30.0), (0.4, 2.0), (0.3, 3.0), (0.6, 1.6), (0.5, 1.4)]
GRADE_NAMES = ["exposure", "gamma", "saturation", "whiteR", "whiteB", "toe"]


def load_work(work: Path):
    vmeta = json.loads((work / "views/views_meta.json").read_text())
    terms = pl.load_terms(work)
    m = pl.base_maps(work, terms)
    views = {n: dict(np.load(work / "views" / f"{n}.npz")) for n in vmeta["views"]}
    return vmeta, m, views


def in_bounds(g, bounds, toe_max=None):
    for i, (lo, hi) in enumerate(bounds[:len(g)]):
        if i == 5:
            lo, hi = 0.0, toe_max
        if not (lo <= g[i] <= hi) or (i == 0 and g[i] <= 0):
            return False
    return True


def bound_hits(g, bounds, where, toe_max=None, tol=0.01):
    hits = []
    for i, (lo, hi) in enumerate(bounds[:len(g)]):
        if i == 5:
            lo, hi = 0.0, toe_max
            if abs(g[i] - hi) <= tol * max(hi, 1e-6):
                hits.append(f"{where}:{GRADE_NAMES[i]}={g[i]:.3f}@max{hi}")
            continue
        span = hi - lo
        if abs(g[i] - lo) <= tol * span:
            hits.append(f"{where}:{GRADE_NAMES[i]}={g[i]:.3f}@min{lo}")
        elif abs(g[i] - hi) <= tol * span:
            hits.append(f"{where}:{GRADE_NAMES[i]}={g[i]:.3f}@max{hi}")
    return hits


def def_targets(ctx, fit_views):
    """DEF L*a*b* body pixels (effects removed) and per-view DEF records."""
    labs, recs = [], {}
    for n in fit_views:
        rec = ctx["def"][n]
        labs.append(pl.lin_to_lab(pl.srgb_to_lin(rec["rgba"][..., :3]))[rec["bodyNoFx"]])
        recs[n] = rec
    return np.concatenate(labs), recs


def samples_for(views, fit_views, cond, n_max=40000, alpha_min=0.99, keep=None, keep_min=0.8, extras=None):
    """Sampled visible texels per fit view: (rows, cols, light). ``keep`` (texture weight) keeps only texels
    whose weight is >= keep_min; ``extras`` adds each view's held dynamic-light irradiance (the floors)."""
    out = {}
    for n in fit_views:
        v = views[n]
        sel = np.nonzero(v["alpha"] > alpha_min)
        if keep is not None:
            kw = pl.sample_tex(keep[..., None], v["uv"][sel][None])[0][:, 0]
            sel = (sel[0][kw >= keep_min], sel[1][kw >= keep_min])
        if len(sel[0]) == 0:
            continue
        idx = np.random.default_rng(3).choice(len(sel[0]), size=min(n_max, len(sel[0])), replace=False)
        rows, cols = sel[0][idx], sel[1][idx]
        light = pl.runtime_light(v, cond)
        if extras and extras.get(n) is not None:
            light = light + extras[n]
        out[n] = (rows, cols, light[rows, cols])
    return out


def fit_grade(cols_lin, tgt, q, bounds, starts, toe_max=None, weights=((0, 1.0), (1, 0.7), (2, 0.7)), maxiter=900):
    def cost(g):
        if not in_bounds(g, bounds, toe_max):
            return 1e6
        lab = np.concatenate([pl.lin_to_lab(pl.grade(c, g) * l) for c, l in cols_lin])
        return sum(np.mean(np.abs(np.percentile(lab[:, i], q) - tgt[i])) * w for i, w in weights)
    best = min((optimize.minimize(cost, np.array(x0, np.float64), method="Nelder-Mead",
                                  options={"maxiter": maxiter, "xatol": 1e-3, "fatol": 1e-3}) for x0 in starts),
               key=lambda r: r.fun)
    return best.x.astype(np.float32), float(best.fun)


# ----------------------------------------------------------------------------- v7c
def v7c_raw(m, p):
    alb = pl.chroma_detail(m["albedo"], m["valid"], p["chromaDetail"], p["chromaSigma"])
    alb = pl.detail_boost(alb, m["valid"], p["detailAmount"], p["detailSigma"])
    return alb * pl.v7_shading(m, p, "v7c_gloss")[..., None]


def fit_v7c(m, views, fit_views, def_lab, p, cond, keep=None, extras=None):
    raw = v7c_raw(m, p)
    samples = samples_for(views, fit_views, cond, keep=keep, extras=extras)
    cols = [(pl.sample_tex(raw, views[n]["uv"][r, c][None])[0], l) for n, (r, c, l) in samples.items()]
    q = np.linspace(2, 98, 25)
    tgt = [np.percentile(def_lab[:, i], q) for i in range(3)]
    # Opt-in (absent = the original fit, bit for bit): ``gradeWeights`` [L, a, b] re-weights the percentile
    # objective (the a*b* terms can pull L off the DEF, and the band transfer corrects a*b* afterwards anyway);
    # ``gradeStarts: "wide"`` adds low-exposure / low-gamma starts plus a refine pass, because Nelder-Mead from
    # the two default starts can stall far from the L optimum when the v7c shading is much darker than the DEF.
    wl = p.get("gradeWeights")
    weights = ((0, 1.0), (1, 0.7), (2, 0.7)) if wl is None else tuple((i, float(w)) for i, w in enumerate(wl) if w)
    starts = ([2.0, 1.0, 1.3, 1.0, 1.0, 0.02], [4.0, 0.9, 1.6, 1.1, 0.8, 0.02])
    wide = p.get("gradeStarts", "default") == "wide"
    if wide:
        starts = starts + ([1.0, 0.6, 1.0, 1.0, 1.0, 0.02], [0.5, 0.55, 1.2, 1.0, 1.0, 0.02],
                           [0.8, 0.7, 1.2, 1.2, 1.1, 0.02], [1.5, 0.8, 1.0, 1.0, 1.0, 0.02])
    g, cost = fit_grade(cols, tgt, q, V7C_BOUNDS, starts, toe_max=p["toeMax"], weights=weights)
    if wide:
        g, cost = fit_grade(cols, tgt, q, V7C_BOUNDS, (g.tolist(),), toe_max=p["toeMax"], weights=weights)
    tex = pl.grade(raw, g)
    tr = pl.fit_band_transfer(tex, m["valid"], samples, views, def_lab, int(p["bandCount"]))
    tex = pl.apply_band_transfer(tex, m["valid"], tr, p["bandStrength"], p["bandLocalSigma"])
    tex = pl.apply_gloss(tex, m, p)
    info = {"grade": np.round(g, 4).tolist(), "cost": round(cost, 3),
            "bandTransfer": {k: v for k, v in tr.items() if not k.startswith("_")},
            "boundHits": bound_hits(g, V7C_BOUNDS, "grade", p["toeMax"])}
    return tex, info


# ----------------------------------------------------------------------------- v6m
def smooth(x, lo, hi):
    t = np.clip((x - lo) / max(hi - lo, 1e-6), 0, 1)
    return t * t * (3 - 2 * t)


def window_weights(lab, classes):
    """Named classes from hue/chroma windows. ``hue`` = [in0, in1, out0, out1] degrees: weight ramps up
    over in0..in1 and down over out0..out1, measured forward from in0 (so windows may wrap past 0)."""
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    C = np.hypot(a, b)
    h = np.degrees(np.arctan2(b, a)) % 360
    ws = []
    for c in classes:
        w = smooth(C, *c["chroma"]) if "chroma" in c else np.ones_like(C)
        if "hue" in c:
            i0, i1, o0, o1 = c["hue"]
            hr = (h - i0) % 360
            w = w * smooth(hr, 0, (i1 - i0) % 360) * (1 - smooth(hr, (o0 - i0) % 360, (o1 - i0) % 360))
        if "lightness" in c:
            w = w * smooth(L, *c["lightness"])
        ws.append(w)
    return np.stack(ws, -1)


def v6m_classes(m, def_lab_all, p):
    """Returns (names, texture weights (H,W,K), DEF assignment function, per-class shading power, sheen)."""
    alb_lab = pl.lin_to_lab(m["albedo"])
    if p.get("classes"):
        cls = p["classes"]
        named = window_weights(alb_lab, cls)
        rest = np.clip(1 - named.sum(-1, keepdims=True), 0, 1)
        wtex = np.concatenate([named, rest], -1)
        names = [c["name"] for c in cls] + [p["restClass"]]
        power = [c.get("shadingPower", 1.0) for c in cls] + [p["restShadingPower"]]
        sheen = [c.get("topSheen", 0.0) for c in cls] + [0.0]
        target = [c.get("defTarget", "body") for c in cls] + ["body"]

        def assign(lab):
            wn = window_weights(lab, cls)
            wr = np.clip(1 - wn.sum(-1, keepdims=True), 0, 1)
            w = np.concatenate([wn, wr], -1)
            w = w / np.maximum(w.sum(-1, keepdims=True), 1e-6)
            a = w.argmax(-1)
            return np.where(w.max(-1) > 0.6, a, -1)
        mode = "windows"
    else:
        from scipy.optimize import linear_sum_assignment
        k = int(p["classCount"])
        tex_c = pl.lab_classes(alb_lab[m["valid"]], k)
        def_c = pl.lab_classes(def_lab_all, k)
        cost = np.array([[abs(t[0] - d[0]) * 0.3 + math.hypot(t[1] - d[1], t[2] - d[2]) for d in def_c] for t in tex_c])
        ri, ci = linear_sum_assignment(cost)
        def_c = def_c[ci[np.argsort(ri)]]
        wtex = pl.class_weights(alb_lab, tex_c, p["classSoftness"])
        names = [f"c{i}" for i in range(k)]
        power = [p.get("classShadingPower", {}).get(n, 1.0) for n in names]
        sheen = [0.0] * k
        target = ["body"] * k

        def assign(lab):
            w = pl.class_weights(lab, def_c, p["classSoftness"])
            return np.where(w.max(-1) > 0.6, w.argmax(-1), -1)
        mode = "kmeans"
    wtex = np.stack([ndimage.gaussian_filter(wtex[..., i], p["classBlur"]) for i in range(wtex.shape[-1])], -1)
    wtex /= np.maximum(wtex.sum(-1, keepdims=True), 1e-6)
    return {"names": names, "wtex": wtex, "assign": assign, "power": power, "sheen": sheen,
            "target": target, "mode": mode}


def fit_v6m(m, views, fit_views, recs, p, cond, keep=None, extras=None):
    alb = pl.detail_boost(m["albedo"], m["valid"], p["detailAmount"], p["detailSigma"])
    sh6 = pl.shading("v6_sprite_match", m, p)
    top = m["suns"].get("top", np.zeros_like(sh6))
    body_lab = np.concatenate([pl.lin_to_lab(pl.srgb_to_lin(recs[n]["rgba"][..., :3]))[recs[n]["bodyNoFx"]] for n in fit_views])
    C = v6m_classes(m, body_lab, p)
    K = len(C["names"])
    # DEF targets per class
    tgts = {i: [] for i in range(K)}
    for n in fit_views:
        rec = recs[n]
        lab = pl.lin_to_lab(pl.srgb_to_lin(rec["rgba"][..., :3]))
        a = C["assign"](lab)
        for i in range(K):
            if C["target"][i] == "effect":
                tgts[i].append(lab[rec["body"] & rec["fx"]])
            else:
                tgts[i].append(lab[rec["bodyNoFx"] & (a == i)])
    tgts = {i: np.concatenate(v) if v else np.zeros((0, 3)) for i, v in tgts.items()}
    craw = []
    for i in range(K):
        sh = np.power(np.clip(sh6, 1e-4, None), C["power"][i])
        if C["sheen"][i]:
            sh = sh * (1 + C["sheen"][i] * np.clip(top, 0, 1) ** 2)
        craw.append(alb * sh[..., None])
    samples = samples_for(views, fit_views, cond, n_max=60000, keep=keep, extras=extras)
    q = np.linspace(4, 96, 17)
    grades, report, hits = [], {}, []
    for i, name in enumerate(C["names"]):
        cols, lights = [], []
        for n, (r, c, l) in samples.items():
            uv = views[n]["uv"][r, c]
            wc = pl.sample_tex(C["wtex"][..., i:i + 1], uv[None])[0][:, 0]
            s = wc > 0.7
            cols.append(pl.sample_tex(craw[i], uv[s][None])[0])
            lights.append(l[s])
        cols, lights = np.concatenate(cols), np.concatenate(lights)
        t = tgts[i]
        if len(cols) < 200 or len(t) < 200:
            # too few texels or DEF pixels to fit: fall back to the whole-body target, and say so
            t = body_lab
            report.setdefault("thinClasses", []).append(name)
        if len(cols) < 50:
            g = np.array([2.0, 1.0, 1.0, 1.0, 1.0], np.float32)
            grades.append(g)
            report[name] = {"grade": g.tolist(), "note": "no texels above weight 0.7; neutral grade"}
            continue
        tg = [np.percentile(t[:, j], q) for j in range(3)]
        g, cost = fit_grade([(cols, lights)], tg, q, V6M_BOUNDS,
                            ([3.0, 1.0, 1.2, 1.0, 1.0], [8.0, 0.9, 1.6, 1.1, 0.8], [1.5, 1.1, 0.8, 1.0, 1.0]),
                            weights=((0, 1.0), (1, 0.8), (2, 0.8)))
        grades.append(g)
        lab = pl.lin_to_lab(pl.grade(cols, g) * lights)
        report[name] = {"grade": np.round(g, 3).tolist(), "cost": round(cost, 2), "texSamples": int(len(cols)),
                        "defSamples": int(len(tgts[i])), "defMedianLab": np.round(np.median(t, 0), 1).tolist(),
                        "fitMedianLab": np.round(np.median(lab, 0), 1).tolist()}
        hits += bound_hits(g, V6M_BOUNDS, f"class:{name}")
    tex = sum(C["wtex"][..., i:i + 1] * pl.grade(craw[i], grades[i]) for i in range(K))
    tex = np.where(m["valid"][..., None], tex, m["albedo"]).astype(np.float32)
    report["classMode"] = C["mode"]
    report["classTexelShare"] = {n: round(float((C["wtex"][..., i][m["valid"]] > 0.5).mean()), 3)
                                 for i, n in enumerate(C["names"])}
    return tex, {"classFit": report, "boundHits": hits, "_wtex": C["wtex"], "_names": C["names"]}


# ----------------------------------------------------------------------------- baked glow
def apply_baked_glow(tex, m, glows, class_info):
    """Steady self-glow as a lift of the base colour on a material class (or a UV mask)."""
    out = tex.copy()
    for g in glows:
        if g.get("maskPath"):
            mp = Path(g["maskPath"])
            mp = mp if mp.is_absolute() else ROOT / mp
            w = np.asarray(Image.open(mp).convert("L").resize(tex.shape[1::-1], Image.BILINEAR), np.float32) / 255
        else:
            names = class_info.get("_names") if class_info else None
            if not names or g["materialClass"] not in names:
                raise ValueError(f"bakedGlow materialClass {g['materialClass']!r} is not a v6m class ({names})")
            w = class_info["_wtex"][..., names.index(g["materialClass"])]
        rgb = pl.srgb_to_lin(np.array(g["rgb"], np.float32))
        out = out + g["strength"] * w[..., None] * rgb
    return np.where(m["valid"][..., None], np.clip(out, 0, 1), tex).astype(np.float32)


def run(unit, spec, work: Path, outd: Path, ctx) -> dict:
    """Fit and write ``outd/basecolor.png``; returns the lighting part of metrics.json."""
    import regions as RG
    import vfx as VX
    lt = spec["lighting"]
    vmeta, m, views = ctx["vmeta"], ctx["maps"], ctx["views"]
    cond = lt.get("arena", "sand")
    fit_views = ctx["fitViews"]
    extras, floors = VX.floor_extras(spec, ctx, fit_views)
    ctx["floorExtras"] = extras
    keep, W, rtex, rrep = None, {}, {}, {}
    fctx = ctx
    if lt.get("regions"):
        if "ao_short" not in m or "nrm_geo" not in m:
            raise RuntimeError("regions need the bake extras (ao_short, nrm_geo, ...)")
        W, rtex, rrep, dmask = RG.fit_regions(spec, ctx, work, samples_for, fit_grade,
                                              v7c_raw(m, dict(V7C_DEFAULTS, **lt.get("knobs", {}))) if lt["mode"] == "v7c"
                                              else v7c_raw(m, V7C_DEFAULTS), V7C_BOUNDS, bound_hits)
        keep = 1 - sum(W.values())
        fdef = {}
        for vn, rec in ctx["def"].items():
            union = np.zeros_like(rec["bodyNoFx"])
            for d in dmask.values():
                if vn in d:
                    union |= d[vn]
            fdef[vn] = dict(rec, bodyNoFx=rec["bodyNoFx"] & ~union)
        fctx = {**ctx, "def": fdef}
    def_lab, recs = def_targets(fctx, fit_views)
    if len(def_lab) < 200:
        raise ValueError(f"only {len(def_lab)} DEF body pixels are left for the unit-level grade "
                         "(outside every region and effect): the regions cover the whole DEF body")
    mode = lt["mode"]
    if mode == "v7c":
        if "ao_short" not in m or "nrm_geo" not in m:
            raise RuntimeError("v7c needs the bake extras (ao_short, nrm_geo, ...)")
        p = dict(V7C_DEFAULTS, **lt.get("knobs", {}))
        tex, info = fit_v7c(m, views, fit_views, def_lab, p, cond, keep=keep, extras=extras)
        cls = None
    else:
        p = dict(V6M_DEFAULTS, **lt.get("knobs", {}))
        tex, info = fit_v6m(m, views, fit_views, recs, p, cond, keep=keep, extras=extras)
        cls = info
    if W:
        tex = RG.compose(tex, W, rtex)
        tex = np.where(m["valid"][..., None], tex, m["albedo"]).astype(np.float32)
        info["boundHits"] = info["boundHits"] + [h for r in rrep.values() for h in r["boundHits"]]
        (work / "regions_fit.json").write_text(json.dumps(rrep, indent=1))
    if lt.get("metal"):          # opt-in baked metal reflection (metal.py); absent = unchanged behaviour
        import metal as MT
        tex, info["metal"] = MT.run(tex, m, lt["metal"], ctx, fit_views, cls, p.get("classes"), cond, extras)
        info["boundHits"] = info["boundHits"] + info["metal"]["boundHits"]
    if lt.get("bakedGlow"):
        tex = apply_baked_glow(tex, m, lt["bakedGlow"], cls)
    img = (pl.lin_to_srgb(tex) * 255 + 0.5).astype(np.uint8)
    Image.fromarray(img).save(outd / "basecolor.png", optimize=False)
    np.save(work / "look_tex_lin.npy", tex.astype(np.float16))
    return {"mode": mode, "knobsResolved": p, "fit": {k: v for k, v in info.items() if not k.startswith("_")},
            "boundHits": info["boundHits"], "fitViews": fit_views, "regions": rrep, "heldFloors": floors,
            "defTargetPixels": int(len(def_lab))}
