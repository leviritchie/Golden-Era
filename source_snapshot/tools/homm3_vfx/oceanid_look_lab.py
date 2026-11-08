"""Oceanid look lab v2: foam-toned lighting, flowing water and DEF-ripped accents (lab copies only).

User decisions this implements (see docs/homm3_vfx_experiments.md, "Oceanid flowing water"):
  1. visible flow (the DEF itself boils in place; flow is asked for anyway),
  2. the water lands at the DEF's own white-foam palette under Hex/Lit,
  3. spray / thrown blob / puddle accents, ripped from the DEF and masked by the mesh silhouette.

Stages (all CPU, reads the Blender passes made by tools/homm3_prebake/{bake_terms,render_passes}.py
into artifacts/homm3_vfx_experiments/oceanid/prebake/):

  lighting  body: the prebake v7c recipe (detail, chroma detail, v7 shading, wet speckle) with its
            grade fitted to the DEF *body* pixels only; water: rank-mapped onto the DEF's idle water
            palette (column and foam separately), scaled by an exposure s and a sky-occlusion
            compensation sky^-alpha fitted so the Hex/Lit relit water matches the DEF water L*a*b*
            percentiles at the sprite camera (sand arena). Region = COLOR_0.r water mask (Tail_* bones).
  cells     8-cell atlases on the body UVs (same layout/cellST as the v1 boil atlas):
              boil  - v1 B2 re-roll (DEF-motion control), prebaked
              flow  - "F": the column's helical bands + speckle travel down 2 DEF px per 12 fps frame
                      (period 16 DEF px = one 8-frame loop), 25% of the speckle and 40% of the highlights
                      re-roll per frame (the DEF's boil), foam boils only; prebaked
            static  - look_static.png, 2048: lighting only (cell 0 of boil), the delivered base colour
  tile      split-renderer water tile atlas for "A2" (8 u-cells of 256x64, wrap gutters) and "A"
            (tile0.png): cylindrical UV (u around the column, v down it, one tile = 16 DEF px of height)
  accents   DEF-ripped flipbooks anchored at the Root bone (static at the ground origin): per-frame
            masks = DEF opaque, not gold, outside the mesh silhouette (+1 px) of the same frame
            (renders/mask from oceanid_unity_lab.py), restricted per layer to detached spray
            components and/or the ground band (puddle). Cells centred on the anchor pixel.

Outputs: artifacts/homm3_vfx_experiments/oceanid/look/ (look_meta.json lists everything).
Proof tier: generated artifact (numpy relight of Blender passes for the fit).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage, optimize

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools/homm3_prebake"))
import oceanid_water_motion as wm  # noqa: E402
import prebake_lab as pl  # noqa: E402  (imported, not modified)
from glb_io import Glb  # noqa: E402
from oceanid_water_lab import (CLIP_GROUPS, DEF_PX_UNITS, GRID, GUTTER, SRC_GLB, cell_sequences,  # noqa: E402
                               dilate_into, load_mesh, palette_map, rasterise, value_noise3)

EXP = ROOT / "artifacts/homm3_vfx_experiments/oceanid"
PB = EXP / "prebake"
OUT = EXP / "look"
N = 1024                      # atlas cell size (as v1)
FLOW_PX = 2.0                 # DEF px per 12 fps frame, downward
LOOP = 8                      # frames per flow period
LY = FLOW_PX * LOOP * DEF_PX_UNITS  # 16 DEF px = 0.403 units
BAND_TURNS = 4                # helical bands: integer turns around the circumference -> ~16 deg tilt
ORIGIN = (193.79, 266.47)     # DEF px of the world origin (SpriteCam offset), = the Root bone head
CREAM = np.array([0.99, 0.98, 0.90], np.float32)

ACCENTS = {
    # id: (clip, rule)   rule: spray = detached water components, puddle = ground band
    "hit_spray": ("Unit_Hitted", ("spray",)),
    "attack_blob": ("Unit_AttackFront", ("spray",)),
    "death_spray_puddle": ("Unit_Death", ("spray", "puddle")),
    "sink_puddle": ("Unit_MoveStart", ("puddle",)),
    "rise_puddle": ("Unit_MoveEnd", ("puddle",)),
}


# ---------------------------------------------------------------- noise with a periodic y lattice

def pnoise(p: np.ndarray, cell: float, seed: int, period: float) -> np.ndarray:
    """Value noise in [0,1]; the y lattice wraps every `period` (a multiple of `cell`)."""
    ny = int(round(period / cell))
    q = p / cell
    i = np.floor(q).astype(np.int64)
    f = q - i
    f = f * f * (3 - 2 * f)

    def h(ix, iy, iz):
        v = (ix * 73856093) ^ ((iy % ny) * 19349663) ^ (iz * 83492791) ^ (seed * 2654435761)
        v = (v ^ (v >> 13)) * 1274126177
        return ((v ^ (v >> 16)) & 0xFFFF) / 65535.0

    out = 0
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                w = (f[..., 0] if dx else 1 - f[..., 0]) * (f[..., 1] if dy else 1 - f[..., 1]) * (f[..., 2] if dz else 1 - f[..., 2])
                out = out + w * h(i[..., 0] + dx, i[..., 1] + dy, i[..., 2] + dz)
    return out


# travelling-feature scales (fractions of the 16 DEF px loop). "F": fine (bands 5.3 px, speckle 1.2/3.2 px,
# highlights 1 px) - at 2 px/frame the speckle and highlights alias into boil and only the bands carry the flow.
# "F2": coarse (bands 8 px, speckle 3.2/5.3 px, highlights 4 px) - every travelling feature is >= 2x the
# per-frame step, so it moves visibly instead of re-rolling. Same helix tilt (turns x period constant).
FLOW_SCALES = {"F": {"band": 3, "turns": 4, "speck": (13, 5), "hl": 16},
               "F2": {"band": 2, "turns": 2, "speck": (5, 3), "hl": 4}}


def flow_field(p: np.ndarray, k: int, r0: float, seed: int, scale: str = "F"):
    """Column pattern at frame k: helical bands + speckle, all travelling down FLOW_PX per frame."""
    fs = FLOW_SCALES[scale]
    q = p.copy()
    q[..., 1] = p[..., 1] + k * FLOW_PX * DEF_PX_UNITS  # value at y, frame k = value at y + v k, frame 0
    theta = np.arctan2(p[..., 0], p[..., 2])
    period = LY / fs["band"]
    warp = pnoise(q * np.array([1, 1, 1]), LY / 2, seed + 5, LY) - 0.5
    phase = (q[..., 1] + fs["turns"] * period * theta / (2 * math.pi)) / period + 0.6 * warp
    band = 0.5 + 0.5 * np.sin(2 * math.pi * phase)
    speck = 0.62 * pnoise(q, LY / fs["speck"][0], seed + 11, LY) + 0.38 * pnoise(q, LY / fs["speck"][1], seed + 12, LY)
    hl = pnoise(q, LY / fs["hl"], seed + 13, LY)
    return band, speck, hl


# ---------------------------------------------------------------- lighting

def def_region_pixels():
    """DEF idle water palette (column, foam: linear rgb sorted by luma) + frame lists for targets."""
    col, foam = [], []
    for f in sorted(Path(wm.DEFAULT_DEF_DIR).glob("02_*.png")):
        fr = np.array(Image.open(f).convert("RGBA"))
        sg = wm.segment(fr)
        col.append(fr[sg["column"], :3])
        foam.append(fr[sg["foam"], :3])
    out = {}
    for k, v in (("column", col), ("foam", foam)):
        px = pl.srgb_to_lin(np.concatenate(v).astype(np.float32) / 255)
        out[k] = px[np.argsort(pl.luminance(px), kind="stable")]
    return out


def lab_pct(lab, q):
    return [np.percentile(lab[:, i], q) for i in range(3)]


def fit_lighting(m, params, water_w, foam_w, water_cell0_score, cov_c, cov_f, pal, sky_n):
    """Returns body texture (lin, TEX), water albedo function, fit record."""
    vmeta = json.loads((PB / "views/views_meta.json").read_text())
    frames_meta = json.loads((ROOT / "artifacts/homm3_def_retarget/hota_cove_oceanid/"
                              "hota_cove_oceanid_def_retarget.blend.frames.json").read_text())
    sprite_views = [n for n in vmeta["views"] if n.startswith("sprite_")]
    views = {n: dict(np.load(PB / "views" / f"{n}.npz")) for n in sprite_views}
    q = np.linspace(2, 98, 25)
    body_def, col_def, foam_def = [], [], []
    for n in sprite_views:
        src = Path(frames_meta["sources"][vmeta["views"][n]["frame"] - 1])
        rgba = np.array(Image.open(src).convert("RGBA"))
        sg = wm.segment(rgba)
        lab = pl.lin_to_lab(pl.srgb_to_lin(rgba[..., :3].astype(np.float32) / 255))
        body = pl.def_mask(rgba.astype(np.float32) / 255) & ~sg["water"] & ~sg["spray"]
        body_def.append(lab[body])
        col_def.append(lab[sg["column"]])
        foam_def.append(lab[sg["foam"]])
    tgt_body = lab_pct(np.concatenate(body_def), q)
    tgt_col = lab_pct(np.concatenate(col_def), q)
    tgt_foam = lab_pct(np.concatenate(foam_def), q)

    alb = pl.chroma_detail(m["albedo"], m["valid"], params.get("chromaDetail", 0.6), params.get("chromaSigma", 16.0))
    alb = pl.detail_boost(alb, m["valid"], params.get("detailAmount", 0.8), params.get("detailSigma", 2.0))
    raw = alb * pl.v7_shading(m, params, "v7c_gloss")[..., None]

    samples = {"body": [], "col": [], "foam": []}
    for n in sprite_views:
        v = views[n]
        sel = np.nonzero(v["alpha"] > 0.99)
        idx = np.random.default_rng(3).choice(len(sel[0]), size=min(40000, len(sel[0])), replace=False)
        rows, cols = sel[0][idx], sel[1][idx]
        light = pl.runtime_light(v, "sand")[rows, cols]
        uv = v["uv"][rows, cols]
        # water masks were rasterised on glTF UVs (v down, row 0 = v 0), which is the top-down layout
        # sample_tex expects for Blender UVs (v up): the two conventions agree
        ww = pl.sample_tex(water_w[..., None], uv[None])[0][:, 0]
        fw = pl.sample_tex(foam_w[..., None], uv[None])[0][:, 0]
        b = ww < 0.2
        samples["body"].append((pl.sample_tex(raw, uv[b][None])[0], light[b]))
        c = (ww > 0.8) & (fw < 0.2)
        f = (ww > 0.8) & (fw > 0.8)
        samples["col"].append((uv[c], light[c]))
        samples["foam"].append((uv[f], light[f]))

    def pct_cost(labs, tgt):
        lab = np.concatenate(labs)
        return sum(np.mean(np.abs(np.percentile(lab[:, i], q) - tgt[i])) * w for i, w in ((0, 1.0), (1, 0.7), (2, 0.7)))

    def cost_body(g):
        if not (0 < g[0] < 12 and 0.5 <= g[1] <= 1.8 and 0.5 <= g[2] <= 2.0 and 0.7 <= g[3] <= 1.5
                and 0.6 <= g[4] <= 1.3 and 0 <= g[5] <= params.get("toeMax", 0.08)):
            return 1e6
        return pct_cost([pl.lin_to_lab(pl.grade(c, g) * l) for c, l in samples["body"]], tgt_body)

    rb = min((optimize.minimize(cost_body, np.array(x0), method="Nelder-Mead",
                                options={"maxiter": 900, "xatol": 1e-3, "fatol": 1e-3})
              for x0 in ([2.0, 1.0, 1.3, 1.0, 1.0, 0.02], [1.4, 0.8, 1.0, 1.1, 0.9, 0.02])), key=lambda r: r.fun)
    g_body = rb.x
    body_tex = pl.apply_gloss(pl.grade(raw, g_body), m, params)

    # water: albedo = clip(pal_lin[rank] * s * sky^-alpha); fitted on cell 0 of the boil pattern
    col_rgb = palette_map(water_cell0_score[cov_c], pal["column"])
    foam_rgb = palette_map(water_cell0_score[cov_f], pal["foam"])

    def water_tex(s, a, gam):
        t = np.zeros((N, N, 3), np.float32)
        comp = np.power(np.clip(sky_n, 0.2, 1.0), -a)[..., None]
        t[cov_c] = np.power(col_rgb, gam) * s * comp[cov_c]
        t[cov_f] = np.power(foam_rgb, gam) * s * comp[cov_f]
        return np.clip(t, 0, 1)

    def cost_water(x):
        s, a, gam = x
        if not (0.2 < s < 4 and 0 <= a <= 1.5 and 0.6 <= gam <= 1.6):
            return 1e6
        t = water_tex(s, a, gam)
        cl = [pl.lin_to_lab(pl.sample_tex(t, uv[None])[0] * l) for uv, l in samples["col"]]
        fl = [pl.lin_to_lab(pl.sample_tex(t, uv[None])[0] * l) for uv, l in samples["foam"]]
        return pct_cost(cl, tgt_col) + 0.7 * pct_cost(fl, tgt_foam)

    rw = min((optimize.minimize(cost_water, np.array(x0), method="Nelder-Mead",
                                options={"maxiter": 300, "xatol": 1e-3, "fatol": 1e-3})
              for x0 in ([1.0, 0.3, 1.0], [1.6, 0.6, 0.9])), key=lambda r: r.fun)
    s, a, gam = rw.x
    bounds = {"s": (0.2, 4), "alpha": (0, 1.5), "gamma": (0.6, 1.6)}
    hits = [k for k, v in zip(bounds, rw.x) if min(abs(v - bounds[k][0]), abs(v - bounds[k][1])) < 1e-2]
    rec = {"bodyGrade": np.round(g_body, 4).tolist(), "bodyCost": float(rb.fun),
           "water": {"s": float(s), "skyAlpha": float(a), "paletteGamma": float(gam), "cost": float(rw.fun)},
           "boundHits": hits, "arena": "sand", "spriteViews": sprite_views}
    return body_tex, (s, a, gam), rec


# ---------------------------------------------------------------- cells

def to_srgb8(t):
    return (pl.lin_to_srgb(np.clip(t, 0, 1)) * 255 + 0.5).astype(np.uint8)


def atlas(cells, ch):
    cw = N + 2 * GUTTER
    img = np.zeros((cw * GRID[1], cw * GRID[0], ch), np.uint8)
    for k, c in enumerate(cells):
        cx, cy = k % GRID[0], k // GRID[0]
        img[cy * cw:(cy + 1) * cw, cx * cw:(cx + 1) * cw] = np.pad(c, ((GUTTER, GUTTER), (GUTTER, GUTTER), (0, 0)), mode="edge")
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--stages", default="lighting,cells,tile,accents")
    a = ap.parse_args()
    stages = set(a.stages.split(","))
    OUT.mkdir(parents=True, exist_ok=True)
    meta_path = OUT / "look_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {"schema": "homm3_oceanid_look_lab.v1"}

    glb = Glb(SRC_GLB)
    P, UV, I, water, foam = load_mesh(glb)
    r_all = np.hypot(P[:, 0], P[:, 2])
    r0 = float(np.median(r_all[water & (P[:, 1] > 0.25) & (P[:, 1] < 0.45)]))
    tri_w = water[I].all(1)
    tri_f = foam[I].sum(1) >= 2
    pal = def_region_pixels()
    stats = json.loads((EXP / "work/cells.json").read_text())["defStats"]

    if stages & {"lighting", "cells", "tile", "scores"}:
        pos, cov = rasterise(P, UV, I, tri_w, N)
        _, cov_f = rasterise(P, UV, I, tri_f & tri_w, N)
        _, cov_all = rasterise(P, UV, I, np.ones(len(I), bool), N)
        cov_f &= cov
        cov_c = cov & ~cov_f
        band_pad = ndimage.binary_dilation(cov, iterations=4) & ~cov_all

        def boil_score(k):
            seed = a.seed * 100 + k
            sp = 0.62 * value_noise3(pos, 1.2 * DEF_PX_UNITS, seed) + 0.38 * value_noise3(pos, 3.0 * DEF_PX_UNITS, seed + 50)
            hn = value_noise3(pos, 1.0 * DEF_PX_UNITS, seed + 99)
            return sp, hn

        def hl_mask(hn, region, frac):
            return region & (hn > np.quantile(hn[region], 1 - frac)) if region.any() else region

        def boil_cell_score(k):
            sp, hn = boil_score(k)
            hl = hl_mask(hn, cov_c, stats["columnHighlightFrac"]) | hl_mask(hn, cov_f, stats["foamHighlightFrac"])
            return sp + 10.0 * hl

        def flow_cell_score(k, scale="F"):
            sp_b, hn_b = boil_score(k)
            band, sp_f, hl_f = flow_field(pos, k, r0, a.seed, scale)
            sc = 0.40 * band + 0.35 * sp_f + 0.25 * sp_b
            frac = stats["columnHighlightFrac"]
            hl = hl_mask(hl_f, cov_c, 0.6 * frac) | hl_mask(hn_b, cov_c, 0.4 * frac)
            score = np.where(cov_f, sp_b, sc)
            hl |= hl_mask(hn_b, cov_f, stats["foamHighlightFrac"])
            return score + 10.0 * hl

        score0 = boil_cell_score(0)

    if "lighting" in stages:
        terms = pl.load_terms(PB)
        m = pl.base_maps(PB, terms)
        params = {"aoGamma": 1.4, "skyFloor": 0.35, "heightDepth": 0.35, "heightPower": 0.6,
                  "wTop": 0.45, "wFront": 0.35, "wBack": 0.2, "fill": 0.55, "keyGain": 0.75}
        params.update(json.loads((PB / "knobs_v7n.json").read_text()))
        T = pl.TEX
        _, covT = rasterise(P, UV, I, tri_w, T)
        _, covfT = rasterise(P, UV, I, tri_f & tri_w, T)
        water_w = ndimage.gaussian_filter(covT.astype(np.float32), 1.0)
        foam_w = ndimage.gaussian_filter((covfT & covT).astype(np.float32), 1.0)
        sky_n = np.asarray(Image.fromarray(m["sky"].astype(np.float32)).resize((N, N), Image.BILINEAR))
        body_tex, wfit, rec = fit_lighting(m, params, water_w, foam_w, score0, cov_c, cov_f, pal, sky_n)
        np.save(OUT / "_body_tex_lin.npy", body_tex.astype(np.float16))
        np.save(OUT / "_sky_n.npy", sky_n.astype(np.float16))
        meta["lighting"] = rec
        meta["lighting"]["knobs"] = params
        print("lighting", json.dumps(rec), flush=True)

    if "cells" in stages:
        body_T = np.load(OUT / "_body_tex_lin.npy").astype(np.float32)
        sky_n = np.load(OUT / "_sky_n.npy").astype(np.float32)
        s, al, gam = (meta["lighting"]["water"][k] for k in ("s", "skyAlpha", "paletteGamma"))
        body_n = pl.srgb_to_lin(np.asarray(Image.fromarray(to_srgb8(body_T)).resize((N, N), Image.LANCZOS)).astype(np.float32) / 255)
        comp = np.power(np.clip(sky_n, 0.2, 1.0), -al)[..., None]

        def cell_rgb(score):
            t = body_n.copy()
            for region, key in ((cov_c, "column"), (cov_f, "foam")):
                t[region] = np.clip(np.power(palette_map(score[region], pal[key]), gam) * s * comp[region], 0, 1)
            pad = dilate_into(t, cov, t)
            t[band_pad] = pad[band_pad]
            return to_srgb8(t)

        boil = [cell_rgb(boil_cell_score(k)) for k in range(LOOP)]
        flow = [cell_rgb(flow_cell_score(k)) for k in range(LOOP)]
        Image.fromarray(atlas(boil, 3)).save(OUT / "look_boil_atlas.png")
        Image.fromarray(atlas(flow, 3)).save(OUT / "look_flow_atlas.png")
        flow2 = [cell_rgb(flow_cell_score(k, "F2")) for k in range(LOOP)]
        Image.fromarray(atlas(flow2, 3)).save(OUT / "look_flow2_atlas.png")
        # delivered static base colour (lighting only): body at full res, water = boil cell 0 upsampled
        stat = to_srgb8(body_T)
        up = np.asarray(Image.fromarray(boil[0]).resize((pl.TEX, pl.TEX), Image.NEAREST))
        _, covT = rasterise(P, UV, I, tri_w, pl.TEX)
        covT = ndimage.binary_dilation(covT, iterations=2)
        stat[covT] = up[covT]
        Image.fromarray(stat).save(OUT / "look_static.png")
        meta["cells"] = {"atlasSize": list(atlas(boil[:1] + boil[1:], 3).shape[1::-1]), "loop": LOOP,
                         "flowDefPxPerFrame": FLOW_PX, "flowPeriodDefPx": FLOW_PX * LOOP,
                         "bandTurns": BAND_TURNS, "flowShare": {"band": 0.40, "travellingSpeckle": 0.35, "rerolledSpeckle": 0.25,
                                                                "travellingHighlights": 0.6, "rerolledHighlights": 0.4},
                         "cellST": stats and json.loads((EXP / "work/cells.json").read_text())["cellST"],
                         "clips": cell_sequences(wm.DEFAULT_DEF_DIR)}

    if "scores" in stages:
        # un-lit source for the unit-look bake stage (which will grade uvAtlas cells itself): per-cell pattern
        # scores in [0, 1] + 10 x highlight flag, the column/foam coverage masks (body UV, glTF v-down rows,
        # N x N) and the DEF palettes (linear rgb, sorted by luma) the scores rank-map onto
        # unit-look contract (docs/homm3_unit_look_pipeline.md, uvAtlas): 'scores' (cells, H, W) in [0, 1], top-down
        # glTF UV. Only the order inside each region matters (rank map), so score + 10 x highlight is squashed by /11;
        # texels outside the water triangles take the nearest water texel's score (seam padding for the region blur).
        near = ndimage.distance_transform_edt(~cov, return_distances=False, return_indices=True)
        for name, fn in (("boil", lambda k: boil_cell_score(k)), ("flow", lambda k: flow_cell_score(k, "F")),
                         ("flow2", lambda k: flow_cell_score(k, "F2"))):
            sc = np.stack([np.clip(fn(k) / 11.0, 0, 1)[near[0], near[1]] for k in range(LOOP)]).astype(np.float16)
            np.savez_compressed(OUT / f"{name}_scores.npz", scores=sc,
                                column=cov_c, foam=cov_f, pad=band_pad, paletteColumn=pal["column"], paletteFoam=pal["foam"])
        # region masks for lighting.regions (maskPath, UV-space, top-down): the delivered GLB has no COLOR_0 and the
        # foam flare is a geometric rule, not a bone, so the masks are rasterised here at the bake size and committed
        md = ROOT / "tools/homm3_unit_look/units/masks/hota_cove_oceanid/regions"
        md.mkdir(parents=True, exist_ok=True)
        T = 2048
        _, cw = rasterise(P, UV, I, tri_w, T)
        _, cf = rasterise(P, UV, I, tri_f & tri_w, T)
        _, ca = rasterise(P, UV, I, np.ones(len(I), bool), T)
        cf &= cw
        for rn, m_ in (("column", cw & ~cf), ("foam", cf)):
            pad = ndimage.binary_dilation(m_, iterations=4) & ~ca     # grow into uncovered texels only
            Image.fromarray(((m_ | pad) * 255).astype(np.uint8)).save(md / f"{rn}.png", optimize=True)
        meta["scores"] = {"files": ["boil_scores.npz", "flow_scores.npz", "flow2_scores.npz"], "cellPx": N,
                          "rankMap": "oceanid_water_lab.palette_map(score[region], palette) per region, cells in grid order"}

    if "tile" in stages:
        s, al, gam = (meta["lighting"]["water"][k] for k in ("s", "skyAlpha", "paletteGamma"))
        tw, th, g = 256, 64, 8
        u = (np.arange(tw) + 0.5) / tw
        v = 1 - (np.arange(th) + 0.5) / th          # image row 0 = top = Unity v 1
        th_ = (u - 0.5) * 2 * math.pi
        TT, VV = np.meshgrid(th_, v)
        p = np.stack([r0 * np.sin(TT), VV * LY, r0 * np.cos(TT)], -1)
        region = np.ones((th, tw), bool)
        cells = []
        for k in range(LOOP):
            band, sp_f, hl_f = flow_field(p, 0, r0, a.seed)
            seed = a.seed * 100 + k
            sp_b = 0.62 * pnoise(p, LY / 13, seed, LY) + 0.38 * pnoise(p, LY / 5, seed + 50, LY)
            hn_b = pnoise(p, LY / 16, seed + 99, LY)
            sc = 0.40 * band + 0.35 * sp_f + 0.25 * sp_b
            frac = stats["columnHighlightFrac"]
            hl = (hl_f > np.quantile(hl_f, 1 - 0.6 * frac)) | (hn_b > np.quantile(hn_b, 1 - 0.4 * frac))
            sc = sc + 10.0 * hl
            rgb = np.clip(np.power(palette_map(sc[region], pal["column"]), gam) * s, 0, 1).reshape(th, tw, 3)
            cells.append(to_srgb8(rgb))
        W = LOOP * (tw + 2 * g)
        at = np.zeros((th, W, 3), np.uint8)
        for k, c in enumerate(cells):
            at[:, k * (tw + 2 * g):(k + 1) * (tw + 2 * g)] = np.concatenate([c[:, -g:], c, c[:, :g]], 1)
        Image.fromarray(at).save(OUT / "look_tile_atlas.png")
        Image.fromarray(cells[0]).save(OUT / "look_tile0.png")
        meta["tile"] = {"size": [W, th], "cell": [tw, th], "gutter": g, "tileWorldHeight": LY, "r0": r0,
                        "cellScaleX": tw / W, "cellOffsetX": [(k * (tw + 2 * g) + g) / W for k in range(LOOP)],
                        "scrollTilesPerSecond": 12.0 / LOOP}

    if "accents" in stages:
        mask_dir = EXP / "renders/mask"
        meta["accents"] = {}
        (OUT / "accents").mkdir(exist_ok=True)
        ax, ay = ORIGIN
        for aid, (clip, rules) in ACCENTS.items():
            grp = CLIP_GROUPS[clip]
            files = sorted(Path(wm.DEFAULT_DEF_DIR).glob(f"{grp}_*.png"))
            masks, frames_rgba = [], []
            for i, f in enumerate(files):
                rgba = np.array(Image.open(f).convert("RGBA"))
                sg = wm.segment(rgba)
                h, sat, val = wm.hsv(rgba[..., :3])
                gold = (h >= 25) & (h <= 65) & (sat >= 0.35) & (val >= 0.3)
                mesh = np.array(Image.open(mask_dir / f"{clip}_{i:02d}.png").convert("RGBA").reduce(2))[..., 3] > 127
                mesh = ndimage.binary_dilation(mesh, iterations=1)
                ok = (rgba[..., 3] == 255) & ~gold & ~mesh
                keep = np.zeros_like(ok)
                if "spray" in rules:
                    lab, n = ndimage.label(sg["spray"], structure=np.ones((3, 3)))
                    if n:
                        sizes = ndimage.sum(np.ones_like(lab), lab, index=np.arange(1, n + 1))
                        keep |= np.isin(lab, 1 + np.nonzero(sizes >= 2)[0])
                if "puddle" in rules:
                    yy = np.arange(rgba.shape[0])[:, None]
                    keep |= (yy >= ay - 16) & (yy <= ay + 14) & (sg["opaque"])
                mk = ok & keep
                masks.append(mk)
                frames_rgba.append(rgba)
            active = [i for i, mk in enumerate(masks) if mk.sum() >= 3]
            if not active:
                print(f"accent {aid}: no pixels", flush=True)
                continue
            ys = np.concatenate([np.nonzero(masks[i])[0] for i in active])
            xs = np.concatenate([np.nonzero(masks[i])[1] for i in active])
            cx, cy = int(math.floor(ax)), int(math.floor(ay))
            hw = int(max(abs(xs.min() - cx), abs(xs.max() - cx))) + 2
            hh = int(max(abs(ys.min() - cy), abs(ys.max() - cy))) + 2
            w, hgt = 2 * hw + 1, 2 * hh + 1
            n = len(files)
            sheet = np.zeros((hgt, w * n, 4), np.uint8)
            for i in range(n):
                cell = np.zeros((hgt, w, 4), np.uint8)
                src = frames_rgba[i]
                y0, x0 = cy - hh, cx - hw
                sy0, sx0 = max(0, y0), max(0, x0)
                sy1, sx1 = min(src.shape[0], y0 + hgt), min(src.shape[1], x0 + w)
                sub = src[sy0:sy1, sx0:sx1].copy()
                sub[~masks[i][sy0:sy1, sx0:sx1]] = 0
                cell[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = sub
                sheet[:, i * w:(i + 1) * w] = cell
                Image.fromarray((masks[i] * 255).astype(np.uint8)).save(OUT / "accents" / f"{aid}_mask_{i:02d}.png")
            Image.fromarray(sheet, "RGBA").save(OUT / "accents" / f"{aid}.png")
            meta["accents"][aid] = {"clip": clip, "defGroup": int(grp), "rules": list(rules), "frames": active,
                                    "frameCount": n, "cellPx": [w, hgt], "anchor": {"bone": "Root", "point": "head"},
                                    "anchorPx": [ax, ay], "cellCentrePx": [cx + 0.5, cy + 0.5],
                                    "centreOffsetPx": [cx + 0.5 - ax, cy + 0.5 - ay],
                                    "pixelsPerFrame": [int(mk.sum()) for mk in masks],
                                    "sheet": f"accents/{aid}.png"}
            print(f"accent {aid}: frames {active} cell {w}x{hgt} px {[int(mk.sum()) for mk in masks]}", flush=True)

    if "specmasks" in stages:
        # per-frame `file` masks (GG_FF.png) for the unit-look spec's puddle layers: the spray layers use the
        # pipeline's own defEffects rule (water + detached), which reproduces the lab's spray masks; the puddle
        # (ground band) has no schema rule, so its masks are committed next to the spec
        sm = ROOT / "tools/homm3_unit_look/units/masks/hota_cove_oceanid"
        ax, ay = ORIGIN
        meta["specMasks"] = {}
        for layer, clips_ in (("death_puddle", ["Unit_Death"]), ("move_puddle", ["Unit_MoveStart", "Unit_MoveEnd"])):
            d = sm / layer
            d.mkdir(parents=True, exist_ok=True)
            meta["specMasks"][layer] = {}
            for clip in clips_:
                grp = CLIP_GROUPS[clip]
                fr_on = []
                for i, f in enumerate(sorted(Path(wm.DEFAULT_DEF_DIR).glob(f"{grp}_*.png"))):
                    rgba = np.array(Image.open(f).convert("RGBA"))
                    sg = wm.segment(rgba)
                    h, sat, val = wm.hsv(rgba[..., :3])
                    gold = (h >= 25) & (h <= 65) & (sat >= 0.35) & (val >= 0.3)
                    mesh = np.array(Image.open(EXP / "renders/mask" / f"{clip}_{i:02d}.png").convert("RGBA").reduce(2))[..., 3] > 127
                    mesh = ndimage.binary_dilation(mesh, iterations=1)
                    yy = np.arange(rgba.shape[0])[:, None]
                    mk = (rgba[..., 3] == 255) & ~gold & ~mesh & (yy >= ay - 16) & (yy <= ay + 14) & sg["opaque"]
                    if mk.sum() >= 3:
                        fr_on.append(i)
                    Image.fromarray((mk * 255).astype(np.uint8)).save(d / f"{int(grp):02d}_{i:02d}.png", optimize=True)
                meta["specMasks"][layer][clip] = fr_on
        print("specmasks", meta["specMasks"], flush=True)

    meta_path.write_text(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
