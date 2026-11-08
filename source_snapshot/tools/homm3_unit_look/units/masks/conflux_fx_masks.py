"""Conflux faction: committed `file` effect masks for units whose effect colours are also body paint.

The roster ripper (`def_effects.frame_effects`, `defEffects`) keeps only *novel* colours.  On the
conflux elementals the effect is drawn in the body's own colours (white-cyan lightning on a white-cyan
air elemental, blue arcs on the blue energy elemental, ...), so `defEffects` sees only specks.  These
masks use a different, per-unit rule instead of a second selection path in the runner:

  thin  : an effect is the DEF's *thin* structure.  The body is the opaque silhouette opened by a
          disk of radius `r` (limbs and torso survive, 1-3 px arcs/bolts/sparks do not); an effect
          pixel is opaque, outside the body grown by `grow`, and at least `lumaMin` bright.  Pixels
          are grouped by `link` px; a group is kept when it has `minPx` pixels and, with `seed`
          ((h0, h1, sMin) HSV), at least `seedMin` pixels of that hue (e.g. cyan lightning, which
          separates the bolt from the grey tornado streaks that are thin too).

Writes tools/homm3_unit_look/units/masks/<unit>/<layer>/GG_FF.png (L, 0/255, DEF canvas), the
format `effectMask.method: "file"` reads.  Deterministic; rerun after a DEF re-extraction:

    python tools/homm3_unit_look/units/masks/conflux_fx_masks.py [unit ...]

Proof tier: generated artifact (DEF measurement).  Reviewed on each unit's review_sheet.png.
"""
from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "homm3_vfx"))
import def_effects as D  # noqa: E402  (read-only use of the ripper's loader)

# unit -> layer -> recipe.  frames: {group: [frame, ...]}
RECIPES: dict[str, dict[str, dict]] = {
    "h3_air_elemental": {
        # g12 attack: the branching white-cyan bolt thrown from the fists (f2-5); cyan seeds drop the tornado streaks
        "attack_bolt": {"frames": {12: [2, 3, 4, 5]}, "rule": "thin",
                        "r": 2, "grow": 2, "lumaMin": 150, "minPx": 6, "link": 2,
                        "seed": [160, 250, 0.2], "seedMin": 2},
    },
    # T1 line: a magic ball at the outstretched hand with a radial spray (g12 f3-6, two alternating cells);
    # the ball's hue is the dress/wing paint, so defEffects keeps only specks of it
    "h3_sprite": {
        "attack_burst": {"frames": {12: [3, 4, 5, 6]}, "rule": "burst", "R": 9, "haloLuma": 200,
                         "hue": [190, 250], "sMin": 0.4, "core": 240,
                         "thin": {"r": 1, "grow": 1, "lumaMin": 40, "minPx": 3, "link": 1, "seed": [200, 250, 0.4]}},
    },
    "h3_faerie": {
        "attack_burst": {"frames": {12: [3, 4, 5, 6]}, "rule": "burst", "R": 9, "haloLuma": 200,
                         "hue": [290, 360], "sMin": 0.5, "core": 245,
                         "thin": {"r": 1, "grow": 1, "lumaMin": 60, "minPx": 3, "link": 1, "seed": [290, 360, 0.5]}},
    },
    "h3_pixie": {
        "attack_burst": {"frames": {12: [3, 4, 5, 6]}, "rule": "burst", "R": 9, "haloLuma": 200,
                         "hue": [30, 60], "sMin": 0.5, "core": 240,
                         "thin": {"r": 1, "grow": 1, "lumaMin": 60, "minPx": 3, "link": 1, "seed": [30, 60, 0.5]}},
    },
    # the flame jet thrown from the outstretched fist (g12 f3-11); fire on a fire body, so defEffects sees specks
    "h3_fire_elemental": {
        "punch_fire": {"frames": {12: [3, 4, 5, 6, 7, 8, 9, 10, 11]}, "rule": "reach", "r": 3, "grow": 2, "minPx": 40, "sideMin": 15},
    },
    # storm line: white (storm) / peach (hurricane) branching bolts from the fists (g12) and above the raised hands (g15)
    "h3_storm_elemental": {
        "attack_bolt": {"frames": {12: [2, 3, 4]}, "rule": "thin", "r": 2, "grow": 1, "lumaMin": 200, "minPx": 6, "link": 2},
        "shoot_bolt": {"frames": {15: [1, 2, 3, 4]}, "rule": "thin", "r": 2, "grow": 1, "lumaMin": 200, "minPx": 6, "link": 2},
    },
    "h3_hurricane_elemental": {
        "attack_bolt": {"frames": {12: [2, 3, 4]}, "rule": "thin", "r": 2, "grow": 1, "lumaMin": 120, "minPx": 6, "link": 2,
                        "seed": [0, 45, 0.2], "seedMin": 3},
        "shoot_bolt": {"frames": {15: [1, 2, 3, 4]}, "rule": "thin", "r": 2, "grow": 1, "lumaMin": 120, "minPx": 6, "link": 2,
                       "seed": [0, 45, 0.2], "seedMin": 3},
    },
    # energy line: the crackling arcs around the body (every frame: idle self-electric) and the attack's arc burst
    "h3_energy_elemental": {
        "attack_arcs": {"frames": {12: "all"}, "rule": "thin", "r": 2, "grow": 1, "lumaMin": 90, "minPx": 4, "link": 1},
        "idle_arcs": {"frames": {2: "all"}, "rule": "thin", "r": 2, "grow": 1, "lumaMin": 90, "minPx": 4, "link": 1},
    },
    "h3_plasma_elemental": {
        "attack_arcs": {"frames": {12: "all"}, "rule": "thin", "r": 2, "grow": 1, "lumaMin": 90, "minPx": 4, "link": 1},
        "idle_arcs": {"frames": {2: "all"}, "rule": "thin", "r": 2, "grow": 1, "lumaMin": 90, "minPx": 4, "link": 1},
    },
}


def _disk(r: int) -> np.ndarray:
    y, x = np.mgrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r


def thin_mask(a: np.ndarray, r=2, grow=2, lumaMin=150, minPx=6, link=2, seed=None, seedMin=2, **_) -> np.ndarray:
    op = a[..., 3] == 255
    body = ndi.binary_opening(op, _disk(r))
    lab, n = ndi.label(body)
    if n:
        s = np.bincount(lab.ravel())
        s[0] = 0
        body = s[lab] >= 0.05 * s.max()
    m = op & ~ndi.binary_dilation(body, _disk(grow)) & (D.luma(a[..., :3]) >= lumaMin)
    if not m.any():
        return m
    grp, _ = ndi.label(ndi.binary_dilation(m, np.ones((3, 3), bool), iterations=link), np.ones((3, 3), bool))
    keep = np.bincount(grp[m], minlength=grp.max() + 1) >= minPx
    keep[0] = False
    if seed is not None:
        h, s, _v = D._hsv(a[..., :3])
        sd = m & (h >= seed[0]) & (h < seed[1]) & (s >= seed[2])
        keep &= np.bincount(grp[sd], minlength=grp.max() + 1) >= seedMin
    return m & keep[grp]


def burst_mask(a: np.ndarray, thin: dict, R=9, haloLuma=200, hue=None, sMin=0.5, core=None, coreR=10,
               minSpray=10, thinR=40, **_) -> np.ndarray:
    """A radial burst at the hand (the sprite/faerie/pixie magic ball): its thin spray (thin_mask with a
    hue seed) is found first, and its median is the burst centre (refined to the white core within coreR
    when `core` is a luma floor).  The ball is every opaque pixel within R of the centre that is
    `haloLuma` bright or of the burst `hue` (sMin); the spray is kept within thinR."""
    op = a[..., 3] == 255
    m = np.zeros_like(op)
    tm = thin_mask(a, **thin)
    if tm.sum() < minSpray:
        return m
    ty, tx = np.nonzero(tm)
    cy, cx = np.median(ty), np.median(tx)
    lum = D.luma(a[..., :3])
    yy, xx = np.mgrid[:op.shape[0], :op.shape[1]]
    if core is not None:
        w = op & (lum >= core) & (np.hypot(yy - cy, xx - cx) <= coreR)
        if w.sum() >= 2:
            wy, wx = np.nonzero(w)
            cy, cx = wy.mean(), wx.mean()
    d = np.hypot(yy - cy, xx - cx)
    sel = lum >= haloLuma
    if hue is not None:
        h, s, v = D._hsv(a[..., :3])
        sel |= (h >= hue[0]) & (h < hue[1]) & (s >= sMin) & (v >= 0.5)
    return (op & (d <= R) & sel) | (tm & (d <= thinR))


def reach_mask(a: np.ndarray, r=3, grow=2, minPx=20, keepLargest=1, sideMin=None, **_) -> np.ndarray:
    """An effect thrown out of the body (the fire elemental's flame jet): the silhouette is opened by a
    disk of radius r, which cuts thin limbs; the largest opened component(s) are the torso.  Every opaque
    pixel outside the torso grown by `grow` is the effect (the extended arm included: the mesh does not
    make that reach); groups smaller than minPx are dropped, and with sideMin only groups whose centroid
    lies at least sideMin px to the right of the torso centroid are kept (drops head flames and toes)."""
    op = a[..., 3] == 255
    lab, n = ndi.label(ndi.binary_opening(op, _disk(r)))
    if not n:
        return np.zeros_like(op)
    sz = np.bincount(lab.ravel())
    sz[0] = 0
    torso = np.isin(lab, np.argsort(sz)[::-1][:keepLargest])
    m = op & ~ndi.binary_dilation(torso, _disk(grow))
    grp, _ = ndi.label(m, np.ones((3, 3), bool))
    keep = np.bincount(grp.ravel()) >= minPx
    keep[0] = False
    if sideMin is not None and grp.max():
        tx = np.nonzero(torso)[1].mean()
        cx = np.asarray(ndi.center_of_mass(m, grp, np.arange(grp.max() + 1)[1:]))[:, 1]
        keep[1:] &= (cx - tx) >= sideMin
    return m & keep[grp]


RULES = {"thin": thin_mask, "burst": burst_mask, "reach": reach_mask}


def build(unit: str) -> None:
    us = D.load_unit(unit)
    for layer, rc in RECIPES[unit].items():
        out = os.path.join(HERE, unit, layer)
        os.makedirs(out, exist_ok=True)
        for f in os.listdir(out):
            if f.endswith(".png"):
                os.remove(os.path.join(out, f))
        for g, frames in rc["frames"].items():
            fr = us.group_rgba(int(g))
            for i in (range(len(fr)) if frames == "all" else frames):
                m = RULES[rc["rule"]](fr[i], **{k: v for k, v in rc.items() if k not in ("frames", "rule")})
                Image.fromarray((m * 255).astype(np.uint8), "L").save(os.path.join(out, f"{int(g):02d}_{i:02d}.png"))
                print(f"{unit} {layer} g{int(g):02d} f{i:02d}: {int(m.sum())} px")


if __name__ == "__main__":
    for u in (sys.argv[1:] or list(RECIPES)):
        build(u)
