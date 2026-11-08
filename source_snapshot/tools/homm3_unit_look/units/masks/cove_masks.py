"""Cove faction: committed `file` effect masks for effects drawn in the unit's own body-paint colours.

The roster ripper (`def_effects.frame_effects`, `defEffects`) keeps only *novel* colours, and the
calm-group vote makes every colour of a prop that is present in the calm groups body paint.  The sea
witch's held orb is in every group (so its colours, and the pale-blue water swirl that shares them,
are body paint), and `defEffects` sees none of it.  These per-unit rules replace no runner path; they
only write the masks `effectMask.method: "file"` reads:

  orb      : a small held/floating orb.  Per frame, the connected clusters of saturated dark blue
             (hue `hue`, s >= `sMin`) with `minPx..maxPx` pixels and a bounding box no larger than
             `box`; the one nearest the previous frame's orb (first frame: nearest `seedXY`) is the
             orb.  Mask = opaque pixels within `R` of its centroid that are blue (s >= 0.2) or bright
             (luma >= `coreLuma`).  A frame with no qualifying cluster (the defence body tint turns
             the whole body blue) gets an empty mask.
  paleblue : a water swirl painted in pale blue over and around the body.  Opaque pixels of hue
             `hue`, saturation `s`, luma >= `lumaMin`, outside the orb disk (grown by `orbGrow`);
             pixels are linked by 1 px and groups smaller than `minPx` are dropped.  The shirt and
             sleeves are neutral white (s ~ 0), so the saturation floor separates them.

  gather   : a water ball gathered in the hands, in the body's own water colours (the nymph line).
             Opaque pixels outside the silhouette of a reference pre-gather frame `ref` (grown by
             `grow`), above DEF row `yMax`, of the ball's pale-blue hue/saturation/luma; groups smaller
             than `minPx` are dropped and the rest closed by 1 px (inside the opaque silhouette).

Writes tools/homm3_unit_look/units/masks/<unit>/<layer>/GG_FF.png (L, 0/255, DEF canvas).
Deterministic; rerun after a DEF re-extraction:

    python tools/homm3_unit_look/units/masks/cove_masks.py [unit ...]

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

ALL_RETARGET = [0, 1, 2, 3, 4, 5, 12, 15, 20, 21]

ORB = {"rule": "orb", "hue": [205, 255], "sMin": 0.55, "minPx": 20, "maxPx": 80, "box": 14,
       "R": 6, "coreLuma": 150, "seedXY": [209, 198]}

ORB_RED = dict(ORB, hue=[345, 10])

RECIPES: dict[str, dict[str, dict]] = {
    "hota_cove_sea_witch": {
        # the blue orb she keeps floating over her left palm in every group (and lets rise on death)
        "orb": dict(ORB, groups=ALL_RETARGET),
        # g15 shoot_front f2-5: the pale-blue water swirl gathered over the head and raised hand before
        # the bolt leaves (the `bolt` defEffects layer only starts at f5 and sees a speck there)
        "charge": {"rule": "paleblue", "frames": {15: [2, 3, 4, 5]}, "hue": [195, 240], "s": [0.12, 0.85],
                   "lumaMin": 110, "minPx": 8, "orb": ORB, "orbGrow": 2},
    },
    # the sea witch's two upgrades share her template: a floating orb over the left palm in every
    # group and the shoot_front swirl over the head and raised hand (f2-6; their g15 draws no bolt)
    "hota_cove_sorceress": {
        "orb": dict(ORB, groups=ALL_RETARGET),
        "charge": {"rule": "paleblue", "frames": {15: [2, 3, 4, 5, 6]}, "hue": [195, 240], "s": [0.12, 0.85],
                   "lumaMin": 110, "minPx": 8, "orb": ORB, "orbGrow": 2},
    },
    "hota_cove_tidecaller": {
        "orb": dict(ORB_RED, groups=ALL_RETARGET),
        "charge": {"rule": "paleblue", "frames": {15: [2, 3, 4, 5, 6]}, "hue": [335, 10], "s": [0.12, 0.85],
                   "lumaMin": 110, "minPx": 8, "orb": ORB_RED, "orbGrow": 2},
    },
    # g12 attack_front f3-4: the water ball gathered over the head and pushed forward from the hands,
    # before it flies (f5-6, the defEffects `g12_detached_0` layer).  f2's start of the gather is inside
    # the silhouette and is left to the mesh.
    "hota_cove_nymph": {
        "gather": {"rule": "gather", "frames": {12: [3, 4]}, "ref": [12, 0], "grow": 1, "yMax": 228,
                   "hue": [198, 214], "s": [0.17, 0.34], "lumaMin": 115, "minPx": 20},
    },
    # the nereid is the nymph sprite recoloured teal (same frames and extents)
    "hota_cove_nereid": {
        "gather": {"rule": "gather", "frames": {12: [3, 4]}, "ref": [12, 0], "grow": 1, "yMax": 228,
                   "hue": [148, 162], "s": [0.22, 0.46], "lumaMin": 125, "minPx": 20},
    },
}


def in_hue(h, rng):
    """Hue in [h0, h1); h0 > h1 wraps through 360 (reds)."""
    h0, h1 = rng
    return ((h >= h0) & (h < h1)) if h0 <= h1 else ((h >= h0) | (h < h1))


def _hsv_luma(a):
    h, s, v = D._hsv(a[..., :3])
    return h, s, v, D.luma(a[..., :3])


def find_orb(a, hue, sMin, minPx, maxPx, box, prev, nearPx=8, nearMinPx=10, maxJump=25, coreLuma=150, **_):
    op = a[..., 3] == 255
    h, s, v, lum = _hsv_luma(a)
    b = op & in_hue(h, hue) & (s >= sMin) & (v >= 0.25)
    lab, n = ndi.label(ndi.binary_dilation(b, iterations=1))
    best, bd = None, 1e9
    for k in range(1, n + 1):
        m = (lab == k) & b
        c = int(m.sum())
        ys, xs = np.nonzero(m)
        cy, cx = ys.mean(), xs.mean()
        d = np.hypot(cy - prev[1], cx - prev[0])
        lo = nearMinPx if d <= nearPx else minPx
        if not (lo <= c <= maxPx) or d > maxJump:
            continue
        if np.ptp(ys) + 1 > box or np.ptp(xs) + 1 > box:
            continue
        # the orb has a bright core inside its dark-blue ring
        y0, y1, x0, x1 = int(cy) - 3, int(cy) + 4, int(cx) - 3, int(cx) + 4
        if not (op[y0:y1, x0:x1] & (lum[y0:y1, x0:x1] >= coreLuma)).any():
            continue
        if d < bd:
            best, bd = (cx, cy), d
    return best


def orb_disk(a, centre, R, coreLuma, hue, **_):
    op = a[..., 3] == 255
    h, s, v, lum = _hsv_luma(a)
    yy, xx = np.mgrid[:a.shape[0], :a.shape[1]]
    d = np.hypot(yy - centre[1], xx - centre[0])
    blue = in_hue(h, [(hue[0] - 25) % 360, (hue[1] + 5) % 360]) & (s >= 0.2)
    return op & (d <= R) & (blue | (lum >= coreLuma))


def paleblue_mask(a, hue, s, lumaMin, minPx, orb=None, orbGrow=2, prev=None, **_):
    op = a[..., 3] == 255
    h, sat, v, lum = _hsv_luma(a)
    m = op & in_hue(h, hue) & (sat >= s[0]) & (sat <= s[1]) & (lum >= lumaMin)
    if orb is not None:
        c = find_orb(a, prev=prev or orb["seedXY"], **{k: v for k, v in orb.items() if k != "rule"})
        if c is not None:
            m &= ~ndi.binary_dilation(orb_disk(a, c, **{k: v for k, v in orb.items() if k != "rule"}),
                                      iterations=orbGrow)
    if not m.any():
        return m
    grp, _ = ndi.label(ndi.binary_dilation(m, np.ones((3, 3), bool)), np.ones((3, 3), bool))
    keep = np.bincount(grp[m], minlength=grp.max() + 1) >= minPx
    keep[0] = False
    return m & keep[grp]


def gather_mask(a, refOpaque, hue, s, lumaMin, yMax, minPx, **_):
    op = a[..., 3] == 255
    h, sat, v, lum = _hsv_luma(a)
    m = op & ~refOpaque & (lum >= lumaMin) & (sat >= s[0]) & (sat <= s[1]) & (h >= hue[0]) & (h <= hue[1])
    m[yMax:] = False
    if not m.any():
        return m
    grp, _ = ndi.label(ndi.binary_dilation(m, np.ones((3, 3), bool)), np.ones((3, 3), bool))
    keep = np.bincount(grp[m], minlength=grp.max() + 1) >= minPx
    keep[0] = False
    return ndi.binary_closing(m & keep[grp], iterations=1) & op


def build(unit: str) -> None:
    us = D.load_unit(unit)
    for layer, rc in RECIPES[unit].items():
        out = os.path.join(HERE, unit, layer)
        os.makedirs(out, exist_ok=True)
        for f in os.listdir(out):
            if f.endswith(".png"):
                os.remove(os.path.join(out, f))
        frames = rc.get("frames") or {g: list(range(len(us.groups.get(g, [])))) for g in rc["groups"]}
        for g, idx in frames.items():
            fr = us.group_rgba(int(g))
            prev = rc.get("seedXY")
            for i in idx:
                a = fr[i]
                if rc["rule"] == "orb":
                    c = find_orb(a, prev=prev, **rc)
                    m = orb_disk(a, c, **rc) if c is not None else np.zeros(a.shape[:2], bool)
                    if c is not None:
                        prev = c
                elif rc["rule"] == "gather":
                    ref = us.group_rgba(rc["ref"][0])[rc["ref"][1]][..., 3] == 255
                    m = gather_mask(a, ndi.binary_dilation(ref, iterations=rc["grow"]), **rc)
                else:
                    m = paleblue_mask(a, **{k: v for k, v in rc.items() if k not in ("frames", "rule")})
                Image.fromarray((m * 255).astype(np.uint8), "L").save(os.path.join(out, f"{int(g):02d}_{i:02d}.png"))
                print(f"{unit} {layer} g{int(g):02d} f{i:02d}: {int(m.sum())} px")


if __name__ == "__main__":
    for u in (sys.argv[1:] or list(RECIPES)):
        build(u)
