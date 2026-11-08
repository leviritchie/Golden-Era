"""Inferno faction: committed per-frame DEF effect masks for unit-look `defFlipbook` layers (effectMask.method "file").

Why a file mask: the roster ripper (def_effects.frame_effects) calls a colour an effect only when it is novel
against the idle frames and the calm groups. On the inferno units the effect's colours are body paint:
- gog / magog / amalek hold a fireball in the hand on every idle frame, so the thrown fireball's yellow-orange is
  "idle paint" and the ripper keeps only one frame of it;
- the efreet family's lower body is fire, so the fireball in the hand shares the tail's colours;
- the arch demon's body is fire-red, so its teleport fire cloud is body paint.
The rules below select the effect by colour *and* by shape (a compact bright cluster = a fireball; the whole
sprite where the DEF has turned into the teleport cloud), per unit, and write 1-bit masks GG_FF.png
(DEF canvas, 1 px = 1 DEF px) to tools/homm3_unit_look/units/masks/<unit>/<layer>/.

Usage: python tools/homm3_vfx/inferno_fx_masks.py [<unit> ...] [--preview DIR]
Deterministic: reads only the DEF extraction PNGs through def_effects.load_unit.
Proof: generated artifact (DEF measurement); not in game.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

sys.path.insert(0, os.path.dirname(__file__))
import def_effects as D  # noqa: E402

ROOT = D.ROOT
OUT = os.path.join(ROOT, "tools", "homm3_unit_look", "units", "masks")
K8 = np.ones((3, 3), bool)


def _f(a):
    rgb = a[..., :3].astype(np.int32)
    op = a[..., 3] == 255
    luma = rgb @ np.array([299, 587, 114]) // 1000
    return rgb, op, luma


def _body(op):
    lab, n = ndi.label(op, structure=K8)
    if not n:
        return np.zeros_like(op)
    s = np.bincount(lab.ravel()); s[0] = 0
    return lab == s.argmax()


def hot_blob(a, seed_luma=200, min_seed=25, min_fill=0.35, grow=2, detached=True):
    """A fireball: clusters of white-hot/yellow pixels (luma >= seed_luma, R >= 200) holding >= min_seed pixels
    and compact (seed pixels fill >= min_fill of the cluster's bounding box: star streaks and lit rims are thin),
    grown by `grow` px into the surrounding hot fringe (R >= 180, R-B >= 60, luma >= 110). Detached components
    (sparks, the burst's scattered embers) are added when `detached`."""
    rgb, op, luma = _f(a)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    seed = op & (luma >= seed_luma) & (r >= 200)
    lab, n = ndi.label(ndi.binary_dilation(seed, iterations=1, structure=K8), structure=K8)
    keep = np.zeros_like(seed)
    for k, sl in enumerate(ndi.find_objects(lab), start=1):
        if sl is None:
            continue
        s = seed[sl] & (lab[sl] == k)
        cnt = int(s.sum())
        area = (sl[0].stop - sl[0].start) * (sl[1].stop - sl[1].start)
        if cnt >= min_seed and cnt / max(area, 1) >= min_fill:
            keep[sl] |= s
    fringe = op & (r >= 180) & (r - b >= 60) & (luma >= 110)
    m = keep | (fringe & ndi.binary_dilation(keep, iterations=grow, structure=K8))
    if detached:
        m |= op & ~ndi.binary_dilation(_body(op), iterations=2)
    return m


def white_sparkle(a, min_px=12):
    """Neutral white four-point stars (the efreet sufi's attack): near-white, unsaturated pixels (min channel
    >= 150, R-B <= 45), minus the white glints inside the fire tail (>= 35% of the 5x5 neighbourhood is hot
    orange), grouped by 2 px proximity; groups under min_px are dropped."""
    rgb, op, luma = _f(a)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    white = op & (np.minimum(np.minimum(r, g), b) >= 150) & (r - b <= 45)
    hot = op & (r >= 180) & (r - b >= 80)
    white &= ndi.uniform_filter(hot.astype(np.float32), size=5, mode="constant") < 0.35
    grp, n = ndi.label(ndi.binary_dilation(white, iterations=2, structure=K8), structure=K8)
    if not n:
        return white
    cnt = np.bincount(grp[white], minlength=n + 1)
    keep = cnt >= min_px; keep[0] = False
    return white & keep[grp]


def opaque_all(a):
    """The whole sprite: used where the DEF has become the effect (the teleport cloud, the burning death, the
    efreet's death flash); the spec's bodyMask.subtractMeshSilhouette, where set, removes what the mesh still
    draws."""
    return a[..., 3] == 255


# ------------------------------------------------------------------------------------------ registry
# unit -> rule key -> (group, frames, rule(rgba, group, frame) -> bool mask); a key "<layer>@<group>" writes a
# second DEF group into the same layer folder (masks are named GG_FF, so one layer can span clips)
RULES: dict[str, dict[str, tuple[int, list[int], callable]]] = {}


def rule(unit, layer, group, frames):
    def deco(fn):
        RULES.setdefault(unit, {})[layer] = (group, frames, fn)
        return fn
    return deco


# gog family: fireball conjured over the shoulder (f2-3), carried forward (f4), bursting at the target (f5-6)
for _u in ("h3_gog", "h3_magog", "h3_amalek"):
    rule(_u, "fireball", 12, [2, 3, 4, 5, 6])(lambda a, g, i: hot_blob(a, min_seed=30, min_fill=0.2, detached=i >= 5))
    rule(_u, "fireball@15", 15, [2, 3, 4])(lambda a, g, i: hot_blob(a, min_seed=30, min_fill=0.2, detached=False))

# gog family: the flame carried in the hand (drawn by the DEF on every frame; the mesh only has a dull brown
# prop there), knocked away on the hit, raised into a wall of fire on the defence, flaring on the death
for _u in ("h3_gog", "h3_magog", "h3_amalek"):
    for _g, _fr in ((2, None), (0, None), (1, None), (3, [0, 1, 2, 3, 4, 6]), (4, [0, 1, 2, 3, 4, 5, 6]), (5, [0, 1, 2, 3, 4])):
        rule(_u, f"hand_flame@{_g}", _g, _fr)(lambda a, g, i: hot_blob(a, seed_luma=170, min_seed=10, min_fill=0.15, grow=2, detached=True))

# hound family: the death, where the body goes up in flames (f2-3) and bursts into sparks and ash (f4-5); the
# sprite is the fire, so the whole sprite is the layer on those frames
for _u in ("h3_hell_hound", "h3_cerberus", "h3_fire_hound"):
    rule(_u, "death_burn", 5, [2, 3, 4, 5])(lambda a, g, i: opaque_all(a))

# efreet family: the fireball held in the hand on the attack
for _u in ("h3_efreeti", "h3_efreet_sultan"):
    rule(_u, "fireball", 12, [4, 5, 6, 7])(lambda a, g, i: hot_blob(a, min_seed=40, min_fill=0.3, detached=False))
    # the death: the body bursts into a white star flash (f2-6); the sprite *is* the flash
    rule(_u, "death_flash", 5, [2, 3, 4, 5, 6])(lambda a, g, i: opaque_all(a))

# efreet sufi: white sparkle stars thrown from the hands; the death's flame wisps and the lamp it retreats into
rule("h3_efreet_sufi", "sparkle", 12, [0, 1, 2, 3, 4, 5])(lambda a, g, i: white_sparkle(a))
rule("h3_efreet_sufi", "death_lamp", 5, [3, 4, 5])(lambda a, g, i: opaque_all(a))

# devil family: the fire-cloud teleport (the sprite *is* the cloud once it forms; on the arch demon its colours
# are also body paint). The spec subtracts the mesh silhouette, so the shrinking mesh keeps its own pixels.
for _u in ("h3_devil", "h3_arch_devil", "h3_arch_demon"):
    rule(_u, "teleport", 20, list(range(4, 14)))(lambda a, g, i: opaque_all(a))
    rule(_u, "teleport@21", 21, list(range(0, 8)))(lambda a, g, i: opaque_all(a))


def build(unit, preview=None):
    us = D.load_unit(unit)
    for layer, (g, frames, fn) in RULES.get(unit, {}).items():
        d = os.path.join(OUT, unit, layer.split("@")[0])   # "<layer>@<group>": another group of the same layer
        os.makedirs(d, exist_ok=True)
        fr = us.group_rgba(g)
        U = np.zeros(fr[0].shape[:2], bool)
        for a in fr:
            U |= a[..., 3] > 0
        ys, xs = np.nonzero(U)
        crop = (slice(max(0, ys.min() - 2), ys.max() + 3), slice(max(0, xs.min() - 2), xs.max() + 3))
        tiles = []
        for i in range(len(fr)):
            on = frames is None or i in frames
            m = fn(fr[i], g, i) if on else np.zeros(fr[i].shape[:2], bool)
            if on:
                Image.fromarray((m * 255).astype(np.uint8), "L").save(os.path.join(d, f"{g:02d}_{i:02d}.png"), optimize=True)
            print(f"{unit} {layer} g{g} f{i}: {int(m.sum())} px")
            if preview:
                a = fr[i][crop]
                im = np.where((a[..., 3] > 0)[..., None], a[..., :3], 40).astype(np.uint8)
                ov = (im * 0.3).astype(np.uint8); ov[m[crop]] = (255, 0, 255)
                tiles.append(np.concatenate([im, ov], 0))
        if preview and tiles:
            img = np.concatenate(tiles, 1)
            os.makedirs(preview, exist_ok=True)
            Image.fromarray(img).save(os.path.join(preview, f"{unit}_{layer}.png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("units", nargs="*")
    ap.add_argument("--preview")
    a = ap.parse_args()
    for u in a.units or sorted(RULES):
        build(u, a.preview)


if __name__ == "__main__":
    main()
