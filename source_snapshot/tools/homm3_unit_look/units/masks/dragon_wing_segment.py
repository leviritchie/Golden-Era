"""Dragon wing membranes: `lighting.defSegmenter` for units whose DEF wing is a different material from the body.

The green dragon's DEF draws its body in saturated dark green scales with gold, and its wing membranes in a pale,
low-saturation green fading to lavender. One whole-unit grade fits the body and takes the Meshy blue-violet
membrane to pink-mauve (identity review: look FAIL on the wings). A `defPalette` region on the wing bones hands the
membrane texels the DEF membrane's own colours by rank instead.

  segment_green_dragon(rgba_uint8) -> {"wing": bool mask, "body": bool mask}   (DEF frame, opaque pixels)
  segment_gold_dragon(rgba_uint8)  -> same keys, same rule

Gold dragon (2026-09-28): the DEF's membrane is pale blue-lavender between gold ribs; the same window picks it
(DEF fit frames 0/9/30/45: wing hue p10/p50/p90 46-228/236-240/272-278, sat p50 0.25-0.26, against a body of hue
p50 42-45, sat p50 0.80-0.82). The Meshy-7 identity regen (2026-09-27) paints the membrane saturated blue with
white patches, which the unit-level grade takes to blue-grey/white; the wing region ranks them onto the DEF's
own membrane and rib colours instead.

Membrane window, measured on CGDRAG group 02 frame 0 (wing vs body patch, HSV percentiles p10/p50/p90):
  wing  hue 93/120/226, sat 0.16/0.31/0.76, value 0.09/0.39/0.65
  body  hue 34/120/129, sat 0.39/0.67/1.00, value 0.03/0.15/0.40
so a membrane pixel is green-to-violet (hue 80..290), unsaturated (sat < 0.5) and not in shadow (value > 0.22),
in an 8-connected piece of at least 40 px (claw and tooth highlights and breath specks pass the colour test alone),
then closed (2 iterations, opaque pixels only) so the dark saturated wing ribs inside the membrane join it: the
mesh region is every texel on the wing bones, ribs included, and a membrane-only DEF palette left it too light
(body L-hist 9.1 against the unit grade's 4.1).
Proof tier: generated artifact (offline DEF colour measurement).
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi

WING = {"hueLo": 80.0, "hueHi": 290.0, "satMax": 0.5, "valueMin": 0.22, "minComponentPx": 40, "closeIters": 2}


def _hsv(rgb: np.ndarray):
    c = rgb.astype(np.float32) / 255.0
    mx, mn = c.max(-1), c.min(-1)
    d = np.maximum(mx - mn, 1e-6)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    return h, s, mx


def segment_green_dragon(rgba: np.ndarray) -> dict:
    op = rgba[..., 3] == 255
    h, s, v = _hsv(rgba[..., :3])
    wing = op & (h >= WING["hueLo"]) & (h < WING["hueHi"]) & (s < WING["satMax"]) & (v > WING["valueMin"])
    lab, n = ndi.label(wing, np.ones((3, 3), bool))
    if n:
        size = ndi.sum(wing, lab, np.arange(1, n + 1))
        wing = np.isin(lab, 1 + np.nonzero(size >= WING["minComponentPx"])[0])
    wing = ndi.binary_closing(wing, np.ones((3, 3), bool), iterations=WING["closeIters"]) & op
    return {"wing": wing, "body": op & ~wing}


def segment_gold_dragon(rgba: np.ndarray) -> dict:
    """Gold dragon: the green dragon's membrane rule, measured on its own DEF fit frames (module docstring)."""
    return segment_green_dragon(rgba)
