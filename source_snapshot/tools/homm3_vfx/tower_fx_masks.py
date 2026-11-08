"""Tower faction: committed per-frame DEF effect masks for unit-look `defFlipbook` layers (effectMask.method "file").

Why a file mask: the roster ripper (def_effects.frame_effects) calls a colour an effect only when it is novel
against the idle frames and the calm groups. On several tower units the effect's colours are also body paint:
the genie's cream-white sparkle stars share the white-blue smoke tail's highlights, the genie's death dissolve is
the tail's own blue, and so on. The rules below select the effect by colour *and* by shape/position, per unit,
and write 1-bit masks GG_FF.png (DEF canvas, 1 px = 1 DEF px) to tools/homm3_unit_look/units/masks/<unit>/<layer>/.

Usage: python tools/homm3_vfx/tower_fx_masks.py [<unit> ...] [--preview DIR]
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


def _clusters_with(cand, seed, min_seed=3, gap=1):
    """cand pixels grouped by `gap`-px proximity; keep groups holding >= min_seed seed pixels."""
    grp, n = ndi.label(ndi.binary_dilation(cand, iterations=gap, structure=K8), structure=K8)
    if not n:
        return cand & False
    cnt = np.bincount(grp[seed & cand], minlength=n + 1)
    keep = cnt >= min_seed; keep[0] = False
    return cand & keep[grp]


def _xrange(mask, x0=None, x1=None, y0=None, y1=None):
    m = mask.copy()
    if x0 is not None: m[:, :x0] = False
    if x1 is not None: m[:, x1:] = False
    if y0 is not None: m[:y0] = False
    if y1 is not None: m[y1:] = False
    return m


# ------------------------------------------------------------------------------------------ exact novelty
_IDLE = {}


def idle_counts(unit):
    """Exact 24-bit colour -> count over the idle group (no quantisation, no calm-group vote: the roster
    baseline's calm vote is what turns these units' effect colours into body paint)."""
    if unit not in _IDLE:
        us = D.load_unit(unit)
        keys = [((x[..., 0].astype(np.int64) << 16) | (x[..., 1].astype(np.int64) << 8) | x[..., 2])[x[..., 3] == 255]
                for x in (us.group_rgba(2) or us.group_rgba(0))]
        k, n = np.unique(np.concatenate(keys), return_counts=True)
        _IDLE[unit] = (k, n)
    return _IDLE[unit]


def novel_exact(unit, a, max_idle=1):
    k, n = idle_counts(unit)
    key = (a[..., 0].astype(np.int64) << 16) | (a[..., 1].astype(np.int64) << 8) | a[..., 2]
    pos = np.clip(np.searchsorted(k, key), 0, len(k) - 1)
    cnt = np.where(k[pos] == key, n[pos], 0)
    return (a[..., 3] == 255) & (cnt <= max_idle)


def novel_blob(unit, a, max_idle=1, min_px=12, min_luma=0, min_sat=0.0, grow=1, bright_grow=150):
    """Clusters of exactly-novel pixels (>= min_px, optionally bright/saturated), grown by `grow` px into
    neighbouring pixels at least `bright_grow` luma (the effect's own highlights shared with the body)."""
    rgb, op, luma = _f(a)
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = (mx - mn) / np.maximum(mx, 1)
    seed = novel_exact(unit, a, max_idle) & (luma >= min_luma) & (sat >= min_sat)
    grp, n = ndi.label(ndi.binary_dilation(seed, structure=K8), structure=K8)
    if n:
        cnt = np.bincount(grp[seed], minlength=n + 1); keep = cnt >= min_px; keep[0] = False
        seed = seed & keep[grp]
    m = seed
    for _ in range(grow):
        m = m | (ndi.binary_dilation(m, structure=K8) & op & (luma >= bright_grow))
    return m


# ------------------------------------------------------------------------------------------ genie
def genie_star_sparkle(a):
    """Cream-white four-point sparkle stars (attack cloud): warm pale pixels (R-B >= 25, luma >= 150) and
    the white/near-white star cores clustered with them; plus detached components (the flung stars)."""
    rgb, op, luma = _f(a)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    warm = op & (luma >= 150) & (r - b >= 25) & (g - b >= 20)
    white = op & (np.minimum(np.minimum(r, g), b) >= 225)
    m = _clusters_with(warm | white, warm, min_seed=4, gap=1)
    det = op & ~ndi.binary_dilation(_body(op), iterations=2)
    return m | det


def genie_blue_sparkle(a):
    """Blue-white sparkle burst (defence, death dissolve): bright blue/white pixels outside a column around the
    idle smoke tail are handled by the caller's region; here, the colour test + detached components."""
    rgb, op, luma = _f(a)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    bright = op & (luma >= 140) & (b - r >= 20) & (b >= 170)
    det = op & ~ndi.binary_dilation(_body(op), iterations=2)
    return bright | det


_BP = {}


def bone_px(unit, group, frame, bone):
    """The def_retarget mesh bone projected to DEF pixels on this key (the SpriteCam, def_effects.BoneProjector)."""
    if unit not in _BP:
        _BP[unit] = (D.load_unit(unit), D.BoneProjector(unit))
    us, bp = _BP[unit]
    return bp.pixels(us.master_index(group, frame))[bone]


def above_bone(unit, group, frame, bone, mask, margin=0):
    """mask rows above the projected bone (DEF y < bone y - margin): the genie's smoke tail below the hips
    is the same blue-white as its sparkle."""
    y = int(round(bone_px(unit, group, frame, bone)[1])) - margin
    m = mask.copy(); m[max(0, y):] = False
    return m


# ------------------------------------------------------------------------------------------ colossus
def colossus_lightning(a):
    """The colossus sword's lightning is warm pink-white (R > B), while its armour and skin highlights are
    neutral silver, so a blue-leaning luma rule (the Titan's) finds nothing and a plain luma rule takes the
    armour. Seed: bright warm-white (luma >= 175, R >= 225, R - B >= 12); grown 1 px into bright neighbours."""
    rgb, op, luma = _f(a)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    seed = op & (luma >= 175) & (r >= 225) & (r - b >= 12)
    grow = ndi.binary_dilation(seed, structure=K8) & op & (luma >= 200)
    m = _clusters_with(seed | grow, seed, min_seed=3, gap=1)
    return drop_on_body(m, op)


def drop_on_body(m, op, size=7, body_share=0.4):
    """Drop mask pixels that sit inside the body (the def_effects on-body tint rule, wider window): the
    attack frames relight the armour warm, and those highlights are lighting, not the arc."""
    fxd = ndi.uniform_filter(m.astype(np.float32), size=size, mode="constant")
    bodyd = ndi.uniform_filter((op & ~m).astype(np.float32), size=size, mode="constant")
    return m & ~((bodyd >= body_share) & (fxd < bodyd))


# ------------------------------------------------------------------------------------------ mages
def hue_glow(a, hue, min_luma=110, min_sat=0.45):
    """Bright saturated pixels of one hue family: 'green' (the mage's shot glow), 'red' / 'orange' (the arch
    and battle mage's hand fireball), 'magenta' (death sparkles)."""
    rgb, op, luma = _f(a)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = (mx - mn) / np.maximum(mx, 1)
    if hue == "green":
        h = (g >= r + 50) & (g >= b + 50)
    elif hue == "red":
        h = (r >= 180) & (g <= 90) & (b <= 90)
    elif hue == "orange":
        h = (r >= 200) & (g >= 90) & (g <= 200) & (b <= 60)
    elif hue == "magenta":
        h = (r >= 150) & (b >= 150) & (g <= 0.7 * np.minimum(r, b))
    else:
        raise ValueError(hue)
    return op & h & (luma >= min_luma if hue != "red" else True) & (sat >= min_sat)


def orb_blobs(a, hue, min_px=4, grow_luma=170, **kw):
    seed = hue_glow(a, hue, **kw)
    grp, n = ndi.label(ndi.binary_dilation(seed, structure=K8), structure=K8)
    if n:
        cnt = np.bincount(grp[seed], minlength=n + 1); keep = cnt >= min_px; keep[0] = False
        seed = seed & keep[grp]
    rgb, op, luma = _f(a)
    return seed | (ndi.binary_dilation(seed, structure=K8) & op & (luma >= grow_luma))


def detached(a):
    op = a[..., 3] == 255
    return op & ~ndi.binary_dilation(_body(op), iterations=2)


# ------------------------------------------------------------------------------------------ registry
# unit -> layer -> (group, frames, rule(rgba, group, frame) -> bool mask)
RULES: dict[str, dict[str, tuple[int, list[int], callable]]] = {}


def rule(unit, layer, group, frames):
    def deco(fn):
        RULES.setdefault(unit, {})[layer] = (group, frames, fn)
        return fn
    return deco


def whole_frame(a):
    """Every opaque DEF pixel (the mesh is hidden on these keys: the DEF's own death remains take over)."""
    return a[..., 3] == 255


for _u in ("h3_genie", "h3_genie_upg"):
    rule(_u, "attack_sparkle", 12, [2, 3, 4, 5])(lambda a, g, i: genie_star_sparkle(a))
    rule(_u, "defence_sparkle", 4, [1, 2, 3, 4, 5])(
        lambda a, g, i, _u=_u: above_bone(_u, g, i, "Spine1", genie_blue_sparkle(a)))
    rule(_u, "death_sparkle", 5, [2, 3, 4])(lambda a, g, i: genie_blue_sparkle(a))
    rule(_u, "death_remains", 5, [5, 6, 7])(lambda a, g, i: whole_frame(a))
rule("h3_colossus", "strike_arc", 12, [1, 2, 3, 4, 5, 6])(lambda a, g, i: colossus_lightning(a))
rule("h3_colossus", "defence_arc", 4, [2, 3, 4, 5, 6])(lambda a, g, i: colossus_lightning(a))
rule("h3_colossus", "shoot_arc", 15, [1, 2, 3, 4, 5, 6])(lambda a, g, i: colossus_lightning(a))
rule("h3_mage", "shoot_glow", 15, [2, 3, 4, 5, 6, 7, 8, 9, 10])(lambda a, g, i: orb_blobs(a, "green", min_px=2))
rule("h3_mage", "death_sparks", 5, [4, 5, 6])(lambda a, g, i: detached(a))
for _u, _h in (("h3_mage_upg", "red"), ("h3_battle_mage", "orange")):
    rule(_u, "attack_fire", 12, [3, 4, 5, 6, 7])(lambda a, g, i, _h=_h: orb_blobs(a, _h, min_px=6))
    rule(_u, "death_orb_sparks", 5, [1, 2, 4, 5, 6])(lambda a, g, i: detached(a))
rule("h3_elemental_gargoyle", "death_melt", 5, [14, 15, 16])(lambda a, g, i: whole_frame(a))
rule("h3_genie_vizier", "death_flash", 5, [2, 3, 4, 5, 6, 7])(lambda a, g, i: whole_frame(a))


def build(unit, preview=None):
    us = D.load_unit(unit)
    for layer, (g, frames, fn) in RULES.get(unit, {}).items():
        d = os.path.join(OUT, unit, layer)
        os.makedirs(d, exist_ok=True)
        fr = us.group_rgba(g)
        tiles = []
        for i in range(len(fr)):
            m = fn(fr[i], g, i) if i in frames else np.zeros(fr[i].shape[:2], bool)
            if i in frames:
                Image.fromarray((m * 255).astype(np.uint8), "L").save(os.path.join(d, f"{g:02d}_{i:02d}.png"), optimize=True)
            print(f"{unit} {layer} g{g} f{i}: {int(m.sum())} px")
            if preview:
                a = fr[i]
                im = np.where((a[..., 3] > 0)[..., None], a[..., :3], 40).astype(np.uint8)
                ov = (im * 0.3).astype(np.uint8); ov[m] = (255, 0, 255)
                tiles.append(np.concatenate([im, ov], 0))
        if preview and tiles:
            H, W = fr[0].shape[:2]
            allop = np.zeros((H, W), bool)
            for q in fr: allop |= q[..., 3] > 0
            ys, xs = np.nonzero(allop)
            y0, y1, x0, x1 = max(0, ys.min() - 4), ys.max() + 4, max(0, xs.min() - 4), xs.max() + 4
            tiles = [np.concatenate([t[:H][y0:y1, x0:x1], t[H:][y0:y1, x0:x1]], 0) for t in tiles]
            img = np.concatenate(tiles, 1)
            img = np.asarray(Image.fromarray(img).resize((img.shape[1] * 2, img.shape[0] * 2), Image.NEAREST))
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
