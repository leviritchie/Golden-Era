"""Rampart dragon breath / death-gas masks (committed `file` effect masks for the unit-look defFlipbook layers).

Why a file mask: the green / gold / diamond dragon breaths are drawn in the body's own colours
(green on a green body, gold on a gold body, cyan-white on a cyan body), so the roster ripper's
`defEffects` novelty rule keeps only the outer specks and drops the breath core. The breath is
instead cut by region: every DEF pixel ahead of the snout (x >= a per-frame column measured from
the DEF) that is breath-coloured and either bright or sparse, and not a dark/grey rim pixel within
2 px of the dense body (the forearm and claws reach into the breath zone).

    python tools/homm3_unit_look/units/masks/rampart_effect_masks.py [unit ...] [--preview DIR]

Writes tools/homm3_unit_look/units/masks/<unit>/<layer>/GG_FF.png (1-bit, DEF canvas).
The green dragon's death gas (g05 f2-6, green glow over the thrown-back head, drifting upward) is cut
the same way inside a per-frame inclusion box around the head.
Proof tier: generated artifact (DEF pixel measurement), reviewed by eye on the preview.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "homm3_vfx"))
import def_effects as D  # noqa: E402


def _green(c, lum):
    gdom = (c[..., 1] >= c[..., 0] + 8) & (c[..., 1] >= c[..., 2] + 8)
    yg = (c[..., 1] >= c[..., 0] - 12) & (c[..., 1] >= c[..., 2] + 40) & (lum >= 140)
    return gdom | yg


def _gold(c, lum):
    return (c[..., 0] >= 110) & (c[..., 1] >= 0.55 * c[..., 0]) & (c[..., 2] <= c[..., 1] - 25) | (lum >= 215)


def _ice(c, lum):
    return ((c[..., 2] >= c[..., 0] + 30) & (c[..., 1] >= c[..., 0] + 20)) | (lum >= 215)


# unit: group, dy, {frame: (snout column x, [exclusion boxes x0,y0,x1,y1 (end-exclusive)])}, colour predicate.
# Columns and boxes were read off grid-annotated zooms of the DEF frames (snout, jaw and forearm/claws
# that reach into the breath zone). The gold and diamond dragons share one drawing; the diamond
# frames sit 2 px lower on the canvas (measured: silhouettes match to <=12 px at dy=+2).
_GOLD = {3: (250, [(240, 190, 275, 240)]),
         4: (262, [(255, 160, 276, 189), (255, 206, 284, 240)]),
         5: (262, [(255, 185, 281, 204), (250, 218, 276, 240)]),
         6: (276, [(270, 185, 286, 208), (255, 208, 280, 240)])}
CONFIG = {
    ("h3_green_dragon", "breath"): (12, 0, {3: (244, [(240, 193, 275, 240)]),
                                4: (258, [(250, 175, 270, 189), (255, 206, 280, 240)]),
                                5: (262, [(255, 185, 284, 204), (255, 214, 276, 240)]),
                                6: (283, [(283, 185, 292, 207), (270, 214, 292, 240)])}, _green),
    ("h3_gold_dragon", "breath"): (12, 0, _GOLD, _gold),
    ("h3_diamond_dragon", "breath"): (12, 2, _GOLD, _ice),
    # death gas: (x_cut, exclusions, inclusion box)
    ("h3_green_dragon", "death_gas"): (5, 0, {2: (160, [], (160, 130, 250, 172)),
                                              3: (160, [], (160, 130, 250, 172)),
                                              4: (180, [(150, 165, 200, 240)], (180, 130, 250, 182)),
                                              5: (190, [(150, 185, 205, 240)], (190, 140, 250, 205)),
                                              6: (200, [(150, 205, 215, 240)], (200, 140, 260, 218))}, _green),
}


def breath_mask(a: np.ndarray, x_cut: int, boxes, dy: int, pred, include=None) -> np.ndarray:
    op = a[..., 3] == 255
    c = a[..., :3].astype(np.int32)
    lum = c @ np.array([0.299, 0.587, 0.114])
    col = pred(c, lum) & op
    dens = ndi.uniform_filter(op.astype(np.float32), 5, mode="constant") * 25
    core = op & (dens >= 18) & (lum < 95)
    near_core = ndi.binary_dilation(core, iterations=2)
    m = col & ((lum >= 95) | (dens <= 15)) & ~(near_core & ((lum < 95) | (np.ptp(c, -1) < 40)))
    m[:, :x_cut] = False
    for x0, y0, x1, y1 in boxes:
        m[y0 + dy:y1 + dy, x0:x1] = False
    if include is not None:
        x0, y0, x1, y1 = include
        keep = np.zeros_like(m)
        keep[y0 + dy:y1 + dy, x0:x1] = True
        m &= keep
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("units", nargs="*")
    ap.add_argument("--preview")
    a = ap.parse_args()
    for (unit, layer), (g, dy, cuts, pred) in CONFIG.items():
        if a.units and unit not in a.units:
            continue
        us = D.load_unit(unit)
        frames = us.group_rgba(g)
        out = os.path.join(HERE, unit, layer)
        os.makedirs(out, exist_ok=True)
        tiles = []
        for f, (xc, boxes, *inc) in cuts.items():
            m = breath_mask(frames[f], xc, boxes, dy, pred, inc[0] if inc else None)
            Image.fromarray((m * 255).astype(np.uint8)).save(os.path.join(out, f"{g:02d}_{f:02d}.png"))
            print(unit, layer, g, f, int(m.sum()))
            if a.preview:
                op = frames[f][..., 3] == 255
                src = np.where(op[..., None], frames[f][..., :3], np.array([72, 88, 64], np.uint8))
                vis = (src * 0.4).astype(np.uint8)
                vis[m] = (255, 0, 255)
                tiles.append(np.concatenate([src[110:290], vis[110:290]], 0)[:, 140:360])
        if a.preview:
            im = np.concatenate(tiles, 1)
            Image.fromarray(im).resize((im.shape[1] * 2, im.shape[0] * 2), Image.NEAREST).save(
                os.path.join(a.preview, f"{unit}_{layer}_mask.png"))


if __name__ == "__main__":
    main()
