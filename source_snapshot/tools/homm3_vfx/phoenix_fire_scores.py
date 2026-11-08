"""Phoenix: un-lit boil scores for the runner-graded `fire_boil` uvAtlas + the UV mask of the `fire` region.

The unit-look runner grades the atlas itself (docs/homm3_unit_look_pipeline.md, uvAtlas): cell k is the look texture
with the `fire` defPalette region re-ranked by cell k's scores, so the texel at score-quantile q takes the DEF fire
colour at luma-quantile q. This script supplies only the scores (cells, H, W) in [0,1]:

  score_k = rank of ( wLum * albedo luminance            -- keeps the Meshy feather structure
                    + wCore * spine/chest core mask       -- the DEF's hot core is mostly steady (survives 0.61 vs 0.26)
                    + beta * (boil noise_k - 0.5) )       -- vertically stretched 3D value noise, new per cell

beta is bisected so the simulated per-cell colour change of the fire texels (DEF fire palette, sum |dRGB| > 60 on
0-255, the phoenix_fire_motion body-change rule) matches the DEF idle body change, 0.347.

Writes
  artifacts/homm3_vfx_experiments/phoenix/scores/fire_boil_scores.npz   ('scores' float16 (8, 512, 512); regenerable)
  tools/homm3_unit_look/units/masks/h3_phoenix/fire_region_uv.png        (UV weight of the fire region; committed)
Proof: generated artifact.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "homm3_prebake"))
import h3def  # noqa: E402
import phoenix_fire_lab as lab  # noqa: E402
import phoenix_fire_masks as fmask  # noqa: E402
import phoenix_fire_motion as fm  # noqa: E402
import prebake_lab as pl  # noqa: E402
from oceanid_water_lab import value_noise3  # noqa: E402

OUT = lab.BASE / "scores"
REGION_PNG = ROOT / "tools/homm3_unit_look/units/masks/h3_phoenix/fire_region_uv.png"
CELLS = 8
SIZE = 512
W_LUM, W_CORE = 1.0, 0.6
TARGET_CHANGE = 0.347  # DEF idle body change (fire_motion.json)


def def_fire_palette():
    d = h3def.read_def("cphx.def")
    px = []
    for f in d.groups[2]:
        rgba = fm.frame_rgba(f, d.palette)
        m = fmask.def_regions(rgba)["fire"]
        px.append(rgba[..., :3][m])
    p = np.concatenate(px).astype(np.float32)
    return p[np.argsort(p @ np.array([0.299, 0.587, 0.114], np.float32), kind="stable")]


def ranks(x, sel):
    r = np.zeros(x.shape, np.float32)
    v = x[sel]
    r[sel] = np.argsort(np.argsort(v, kind="stable"), kind="stable") / max(1, len(v) - 1)
    return r


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    albedo = lab.load_albedo()                      # (1024,1024,3) linear, base-colour image layout
    pos, cov = lab.rest_raster()
    fire = lab.fire_texels(albedo) * (cov > 0)
    Image.fromarray((np.clip(fire, 0, 1) * 255).astype(np.uint8), "L").resize((SIZE, SIZE), Image.BILINEAR) \
        .save(REGION_PNG, optimize=True)
    core = lab.glow_mask(pos, cov)
    lum = pl.luminance(albedo)
    lumr = ranks(lum, cov > 0)
    p = pos / np.array([1.0, 2.6, 1.0])
    noise = [0.65 * value_noise3(p, 0.035, 40 + k) + 0.35 * value_noise3(p, 0.012, 141 + k) for k in range(CELLS)]
    sel = (fire > 0.8)
    pal = def_fire_palette()

    def cells(beta):
        return [ranks(W_LUM * lumr + W_CORE * core + beta * (n - 0.5), cov > 0) for n in noise]

    def change(beta):
        cs = cells(beta)
        cols = [pal[np.minimum((c[sel] * len(pal)).astype(int), len(pal) - 1)] for c in cs]
        return float(np.mean([(np.abs(cols[k] - cols[(k + 1) % CELLS]).sum(1) > 60).mean() for k in range(CELLS)]))

    lo, hi = 0.0, 8.0
    for _ in range(12):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if change(mid) < TARGET_CHANGE else (lo, mid)
    beta = 0.5 * (lo + hi)
    cs = cells(beta)
    sc = np.stack([np.asarray(Image.fromarray(c).resize((SIZE, SIZE), Image.BILINEAR)) for c in cs]).astype(np.float16)
    np.savez_compressed(OUT / "fire_boil_scores.npz", scores=sc)
    rep = {"schema": "phoenix_fire_scores.v1", "cells": CELLS, "size": SIZE, "wLum": W_LUM, "wCore": W_CORE,
           "beta": round(beta, 4), "simulatedChange": round(change(beta), 3), "target": TARGET_CHANGE,
           "fireTexelShare": round(float(sel.mean()), 3), "paletteSize": int(len(pal))}
    (OUT / "fire_boil_scores.json").write_text(json.dumps(rep, indent=1))
    print(rep)


if __name__ == "__main__":
    main()
