"""Factory faction: committed `file` effect masks for units whose effect colours are also body paint.

The roster ripper (`def_effects.frame_effects`, `defEffects`) keeps only *novel* colours.  The
factory flamethrowers break that in two ways:

  * the Engineer / Tinker carry a steady pilot flame at the nozzle on idle, so the jet's own
    orange-yellow ramp is idle body paint and `defEffects` keeps only its outer specks;
  * every flamethrower DEF relights the coat and hose orange while the jet burns; those relit
    pixels are fire-class and novel, so a colour rule rips them as flipbook specks on the body
    (they are the jet's *light*, which the unit's effectLight carries instead).

Rule used here instead of a second selection path in the runner:

  jet : fire-class pixels (`def_effects.colour_class`, no novelty test) grouped by `link` px.
        The largest group is the jet.  A group is kept when it is the jet or lies entirely in
        front of the jet's rear edge (x >= jet.xmin - `slack`) - the sprite faces +x, so this keeps
        the flying embers ahead of the nozzle and drops the relit coat/hose behind it.  Groups
        smaller than `minPx` go.  A frame whose jet is smaller than `jetMinPx` gets an empty mask.

Writes tools/homm3_unit_look/units/masks/<unit>/<layer>/GG_FF.png (L, 0/255, DEF canvas), the
format `effectMask.method: "file"` reads.  Deterministic; rerun after a DEF re-extraction:

    python tools/homm3_unit_look/units/masks/factory_fx_masks.py [unit ...]

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

_JET = {"rule": "jet", "link": 2, "slack": 2, "minPx": 3, "jetMinPx": 60}
# unit -> layer -> recipe.  frames: {group: [frame, ...]}
RECIPES: dict[str, dict[str, dict]] = {
    "hota_factory_mechanic": {"flame_jet": {"frames": {12: [1, 2, 3, 4, 5, 6]}, **_JET}},
    "hota_factory_engineer": {"flame_jet": {"frames": {12: [1, 2, 3, 4, 5, 6]}, **_JET}},
    "h3_mechanic_upg_alt": {"flame_jet": {"frames": {12: [1, 2, 3, 4, 5, 6]}, **_JET}},
}
_BOOM = {"rule": "explode", "ref": 1, "fullFrom": 4, "diff": 48, "lumaMin": 150}
_STEAM = {"rule": "steam", "ref": 0, "diff": 40, "satMax": 0.25, "lumaMin": 100, "belowTop": 14, "minPx": 4}
for _u in ("hota_factory_automaton", "hota_factory_sentinel_automaton", "h3_automaton_upg_alt"):
    RECIPES[_u] = {"death_explosion": {"frames": {5: [2, 3, 4, 5, 6, 7, 8, 9, 10]}, **_BOOM},
                   "vent_steam": {"frames": {1: [4, 5, 6, 7, 8]}, **_STEAM}}


def explode_mask(a: np.ndarray, ref_rgba=None, frame=0, fullFrom=4, diff=48, lumaMin=150, **_) -> np.ndarray:
    """Self-destruct: before `fullFrom` the burst is what changed against the intact reference
    frame (newly opaque, or recoloured by more than `diff`) and is at least `lumaMin` bright (the
    hull shifts as it bursts, so a change test alone takes the whole dark hull); from `fullFrom` on
    the fireball covers the hull, so the whole DEF frame is the effect (the mesh is hidden by a
    hideMesh event there)."""
    op = a[..., 3] == 255
    if frame >= fullFrom:
        return op
    rop = ref_rgba[..., 3] == 255
    d = np.abs(a[..., :3].astype(np.int32) - ref_rgba[..., :3].astype(np.int32)).max(-1)
    return op & (~rop | (d > diff)) & (D.luma(a[..., :3]) >= lumaMin)


def steam_mask(a: np.ndarray, ref_rgba=None, diff=40, satMax=0.25, lumaMin=100, belowTop=14, minPx=4, **_) -> np.ndarray:
    """Vent steam puffs: grey, bright, new against the rest frame, and no lower than `belowTop` px
    under the rest frame's top row (the grey gun barrel moves too, lower down)."""
    op = a[..., 3] == 255
    rop = ref_rgba[..., 3] == 255
    d = np.abs(a[..., :3].astype(np.int32) - ref_rgba[..., :3].astype(np.int32)).max(-1)
    _h, s, _v = D._hsv(a[..., :3])
    top = np.nonzero(rop.any(1))[0].min()
    m = op & (~rop | (d > diff)) & (s <= satMax) & (D.luma(a[..., :3]) >= lumaMin)
    m[top + belowTop:] = False
    lab, n = ndi.label(ndi.binary_dilation(m, np.ones((3, 3), bool)), np.ones((3, 3), bool))
    keep = np.bincount(lab[m], minlength=n + 1) >= minPx
    keep[0] = False
    return m & keep[lab]


def jet_mask(a: np.ndarray, link=2, slack=2, minPx=3, jetMinPx=60, **_) -> np.ndarray:
    op = a[..., 3] == 255
    m = op & (D.colour_class(a[..., :3]) == D.EFFECT_CLASSES.index("fire") + 1)
    if not m.any():
        return m
    grp, n = ndi.label(ndi.binary_dilation(m, np.ones((3, 3), bool), iterations=link), np.ones((3, 3), bool))
    sizes = np.bincount(grp[m], minlength=n + 1)
    sizes[0] = 0
    jet = int(sizes.argmax())
    if sizes[jet] < jetMinPx:
        return np.zeros_like(m)
    xs = np.nonzero(m & (grp == jet))[1]
    x0 = xs.min() - slack
    keep = np.zeros(n + 1, bool)
    for g in range(1, n + 1):
        if sizes[g] < minPx:
            continue
        gx = np.nonzero(m & (grp == g))[1]
        keep[g] = g == jet or gx.min() >= x0
    return m & keep[grp]


RULES = {"jet": jet_mask, "explode": explode_mask, "steam": steam_mask}


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
            extra = {"ref_rgba": fr[rc["ref"]]} if "ref" in rc else {}
            for i in frames:
                m = RULES[rc["rule"]](fr[i], frame=i, **extra,
                                      **{k: v for k, v in rc.items() if k not in ("frames", "rule", "ref")})
                Image.fromarray((m * 255).astype(np.uint8), "L").save(os.path.join(out, f"{int(g):02d}_{i:02d}.png"))
                print(f"{unit} {layer} g{int(g):02d} f{i:02d}: {int(m.sum())} px")


if __name__ == "__main__":
    for u in (sys.argv[1:] or list(RECIPES)):
        build(u)
