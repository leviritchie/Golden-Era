"""Dungeon effect masks (committed `file` effect masks for the unit-look defFlipbook layers).

    python tools/homm3_unit_look/units/masks/dungeon_fx_masks.py [unit ...] [--preview DIR]

Writes tools/homm3_unit_look/units/masks/<unit>/<layer>/GG_FF.png (1-bit, DEF canvas).
Proof tier: generated artifact (DEF pixel measurement), reviewed by eye on the preview.

breath (black / shadow dragon, g12 attack_front)
    The breath's first frames (f3-f4) are drawn in the belly's own orange ramp and touch the snout,
    so the roster ripper's `defEffects` (novel colour minus "relit body" minus on-body tint) keeps
    nothing on f3 and 12 px on f4; only the detached puff on f5-f6 survives. Here the breath is cut
    as one flame cloud: seeds are warm pixels whose colour never appears in the calm groups (the
    ripper's own novelty baseline); the seed cloud is the largest dense seed cluster (the wings'
    breath-lit red speckle is sparse and is dropped), and the mask is every warm pixel inside the
    cloud's closed hull, plus the largest detached speck cluster (the dissipating puff, which dims below the colour test). The shadow
    dragon (lvl7Alt) is the same drawing in gold: its breath uses a gold predicate instead of red.
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


def _warm(c):
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    return (r >= 150) & (r >= g + 30) & (r >= b + 40)


def _gold(c):
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    return (r >= 150) & (r >= b + 60) & (g >= 0.45 * r)


def breath_mask(a: np.ndarray, base, pred=_warm) -> np.ndarray:
    op = a[..., 3] == 255
    c = a[..., :3].astype(np.int32)
    warm = pred(c) & op
    seed = warm & base.novel(a[..., :3])
    lab2, n2 = ndi.label(op, structure=np.ones((3, 3), bool))
    det = np.zeros_like(op)
    if n2:
        sz = np.bincount(lab2.ravel()); sz[0] = 0
        det = op & (lab2 != sz.argmax())
        # the dissipating puff: the largest cluster of detached specks (any colour, it dims as it fades)
        dl, dn = ndi.label(ndi.binary_dilation(det, iterations=3))
        if dn:
            ds = np.bincount(dl[det], minlength=dn + 1); ds[0] = 0
            det = det & (dl == ds.argmax()) if ds.max() >= 40 else np.zeros_like(op)
    if seed.sum() < 20:
        return det
    dens = ndi.uniform_filter(seed.astype(np.float32), 7, mode="constant") * 49
    dense = seed & (dens >= 8)
    lab, n = ndi.label(ndi.binary_dilation(dense, iterations=3))
    if n == 0:
        return np.zeros_like(op)
    sizes = np.bincount(lab[dense], minlength=n + 1)
    sizes[0] = 0
    cloud = lab == sizes.argmax()
    cloud = ndi.binary_fill_holes(ndi.binary_closing(cloud, iterations=3))
    lum = c @ np.array([0.299, 0.587, 0.114])
    m = warm & cloud | (seed & cloud) | (cloud & op & (lum >= 150) & (c[..., 0] >= c[..., 2]))
    return m | (det & ndi.binary_dilation(cloud, iterations=8)) if cloud.sum() > 150 else m | det


def gold_breath_mask(a, base):
    return breath_mask(a, base, _gold)


def lightning_mask(a: np.ndarray, base, min_cluster=14) -> np.ndarray:
    """White forked discharge drawn over and around the body (beholder / evil eye / fargazer attack_front: the roster inventory
    saw none of it, because the discharge is white on a body with white eye-stalk tips): bright near-white
    pixels in thin strokes. The eye-stalk tips are the same white but are small blobs present in
    idle, so they fall to the novelty test or the cluster-size floor; the body's own white flash
    (dense interior) falls to the stroke-density test and is left to the effect light."""
    op = a[..., 3] == 255
    c = a[..., :3].astype(np.float32)
    lum = c @ np.array([0.299, 0.587, 0.114], np.float32)
    sat = (c.max(-1) - c.min(-1)) / np.maximum(c.max(-1), 1)
    white = op & (lum >= 185) & (sat <= 0.3)
    dens = ndi.uniform_filter(op.astype(np.float32), 5, mode="constant") * 25
    m = white & (dens <= 17)
    grp, n = ndi.label(ndi.binary_dilation(m, iterations=1), structure=np.ones((3, 3), bool))
    if n:
        sz = np.bincount(grp[m], minlength=n + 1); sz[0] = 0
        m &= (sz >= min_cluster)[grp]
    # grow into the stroke's dimmer anti-aliased edge (grey-white, still thin)
    edge = op & (lum >= 150) & (sat <= 0.3) & (dens <= 17) & ndi.binary_dilation(m, iterations=1)
    return m | edge


def _idle_top(base_unit) -> int:
    us = D.load_unit(base_unit)
    return int(min(np.nonzero((a[..., 3] == 255).any(1))[0].min() for a in us.group_rgba(2)))


def whip_crack_mask(a: np.ndarray, base, unit="h3_minotaur_taskmaster", band=24) -> np.ndarray:
    """Taskmaster shoot_front: the whip cracked overhead is drawn as white streaks over the horns plus
    a spray of white star sparks. The only other near-white pixels are the axe glints (present in
    idle, low on the body), so the mask is near-white / pale-blue pixels in a band from the idle
    horn tip down `band` rows, plus every detached speck (the sparks) anywhere above that band's end."""
    op = a[..., 3] == 255
    c = a[..., :3].astype(np.float32)
    lum = c @ np.array([0.299, 0.587, 0.114], np.float32)
    sat = (c.max(-1) - c.min(-1)) / np.maximum(c.max(-1), 1)
    pale = op & (((lum >= 170) & (sat <= 0.35)) | ((lum >= 140) & (c[..., 2] >= c[..., 0] + 15)))
    y_end = _idle_top(unit) + band
    m = pale.copy()
    m[y_end:] = False
    lab, n = ndi.label(op, structure=np.ones((3, 3), bool))
    if n:
        sz = np.bincount(lab.ravel()); sz[0] = 0
        det = op & (lab != sz.argmax()) & (lum >= 120)
        det[y_end:] = False
        m |= det
    return m


CONFIG = {
    "h3_minotaur_taskmaster": {"whip_crack": (15, [3, 4, 5, 6, 7], whip_crack_mask)},
    "h3_beholder": {"attack_bolt": (12, [0, 1, 2, 3, 4, 5, 6], lightning_mask)},
    "h3_evil_eye": {"attack_bolt": (12, [0, 1, 2, 3, 4, 5, 6], lightning_mask)},
    "h3_fargazer": {"attack_bolt": (12, [0, 1, 2, 3, 4, 5, 6], lightning_mask)},
    "h3_black_dragon": {"breath": (12, [3, 4, 5, 6], breath_mask)},
    "h3_shadow_dragon": {"breath": (12, [3, 4, 5, 6], gold_breath_mask)},
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("units", nargs="*")
    ap.add_argument("--preview")
    a = ap.parse_args()
    for unit in a.units or list(CONFIG):
        us = D.load_unit(unit)
        base = D.baseline(us)
        for layer, (g, frames, fn) in CONFIG[unit].items():
            imgs = us.group_rgba(g)
            out = os.path.join(HERE, unit, layer)
            os.makedirs(out, exist_ok=True)
            tiles = []
            for f in frames:
                m = fn(imgs[f], base)
                Image.fromarray((m * 255).astype(np.uint8)).save(os.path.join(out, f"{g:02d}_{f:02d}.png"))
                print(unit, layer, g, f, int(m.sum()))
                if a.preview:
                    op = imgs[f][..., 3] == 255
                    src = np.where(op[..., None], imgs[f][..., :3], np.array([72, 88, 64], np.uint8))
                    vis = (src * 0.4).astype(np.uint8)
                    vis[m] = src[m]
                    tiles.append((op, np.concatenate([src, vis], 1)))
            if a.preview:
                ys, xs = np.nonzero(np.any([t[0] for t in tiles], 0))
                y0, y1, x0, x1 = max(0, ys.min() - 3), ys.max() + 4, max(0, xs.min() - 3), xs.max() + 4
                w = imgs[0].shape[1]
                im = np.concatenate([np.concatenate([t[1][y0:y1, x0:x1], t[1][y0:y1, w + x0:w + x1]], 0)
                                     for t in tiles], 1)
                Image.fromarray(im).resize((im.shape[1] * 2, im.shape[0] * 2), Image.NEAREST).save(
                    os.path.join(a.preview, f"{unit}_{layer}_mask.png"))


if __name__ == "__main__":
    main()
