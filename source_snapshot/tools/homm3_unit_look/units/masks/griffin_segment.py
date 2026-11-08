"""Griffin forepart: `lighting.defSegmenter` for h3_griffin, whose DEF eagle forepart is a different material from
its lion body.

CGRIFF draws the head, neck, chest and forelegs in saturated golden yellow (mean RGB about 123/98/23) and the lion
body in dull brown (about 62/49/31); the wings are grey-lavender and near-black flight feathers. The 2026-09-27
Meshy-7 spread-wing regen (identity_regen/h3_griffin) paints the forepart a dull olive-gold, and one whole-unit grade
fits the dominant brown, so the forepart reads uniformly dark olive-brown (coordinator review 2026-09-29). A `grade`
region on the forepart bones grades those texels to this DEF region's own L*a*b* percentiles instead.

  segment_griffin(rgba_uint8) -> {"forepart": bool mask, "body": bool mask}   (DEF frame, opaque pixels)

Window, measured on CGRIFF frames 02_00 / 00_00 / 03_02 / 12_03 (opaque pixels, HSV percentiles p10/p50/p90):
  all   hue 0/32-37/49-60, sat 0.10-0.16/0.51-0.59/0.88-0.95, value 0.09-0.13/0.26-0.29/0.44-0.48
so a forepart pixel is yellow (hue 39..68), saturated (sat > 0.6) and not black (value > 0.18), in an 8-connected
piece of at least 40 px, then closed (2 iterations, opaque pixels only) so the darker feather shading inside the gold
joins it. That picks 32-42% of the opaque pixels: head, neck, chest, forelegs and the gold wing coverts; the brown
lion body, the grey/black flight feathers and most of the orange talons stay in "body".
Proof tier: generated artifact (offline DEF colour measurement; mask sheet F:/olden_fp_work/ident/def_gold_mask.png).
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi

FOREPART = {"hueLo": 39.0, "hueHi": 68.0, "satMin": 0.6, "valueMin": 0.18, "minComponentPx": 40, "closeIters": 2}


def _hsv(rgb: np.ndarray):
    c = rgb.astype(np.float32) / 255.0
    mx, mn = c.max(-1), c.min(-1)
    d = np.maximum(mx - mn, 1e-6)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    return h, s, mx


def segment_griffin(rgba: np.ndarray) -> dict:
    op = rgba[..., 3] == 255
    h, s, v = _hsv(rgba[..., :3])
    w = FOREPART
    fore = op & (h >= w["hueLo"]) & (h < w["hueHi"]) & (s > w["satMin"]) & (v > w["valueMin"])
    lab, n = ndi.label(fore, np.ones((3, 3), bool))
    if n:
        size = ndi.sum(fore, lab, np.arange(1, n + 1))
        fore = np.isin(lab, 1 + np.nonzero(size >= w["minComponentPx"])[0])
    fore = ndi.binary_closing(fore, np.ones((3, 3), bool), iterations=w["closeIters"]) & op
    return {"forepart": fore, "body": op & ~fore}
