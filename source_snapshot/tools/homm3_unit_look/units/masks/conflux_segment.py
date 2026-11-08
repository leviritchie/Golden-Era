"""Conflux faction: `lighting.defSegmenter` functions and the UV texture masks their regions pair with.

The energy and plasma elementals are painted in one saturated hue (deep blue / hot orange) with white
highlight stripes.  A whole-unit grade cannot reach that chroma: it trades it for lightness and the
body comes out pale (energy v7c: body L-hist 15.1 raw -> 21.2 look).  A `defPalette` region hands the
hued texels the DEF's own hued colours by rank instead, and the white stripes stay on the unit grade.

  segment_<unit>(rgba_uint8) -> {"hue": bool mask, "white": bool mask}   (DEF frame, opaque pixels)

Texture masks (UV space, L 0/255) are written by

    python tools/homm3_unit_look/units/masks/conflux_segment.py [unit ...]

to tools/homm3_unit_look/units/masks/<unit>/tex_hue.png from the unit's un-prebaked def_retarget base
colour (the superseded original once the unit is applied), with the same hue window.

Proof tier: generated artifact.
"""
from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))

# unit -> (hue lo, hue hi, sat min, value min); hue in degrees, wrapping when lo > hi
WINDOWS = {
    "h3_energy_elemental": (195.0, 270.0, 0.45, 0.15),
    "h3_plasma_elemental": (10.0, 45.0, 0.45, 0.15),
}


def _hsv(rgb: np.ndarray):
    c = rgb.astype(np.float32) / 255.0
    mx, mn = c.max(-1), c.min(-1)
    d = np.maximum(mx - mn, 1e-6)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    return h, s, mx


def _in_window(rgb: np.ndarray, win) -> np.ndarray:
    lo, hi, smin, vmin = win
    h, s, v = _hsv(rgb)
    hue = (h >= lo) & (h < hi) if lo <= hi else (h >= lo) | (h < hi)
    return hue & (s >= smin) & (v >= vmin)


def _segment(unit: str, rgba: np.ndarray) -> dict:
    op = rgba[..., 3] == 255
    hue = op & _in_window(rgba[..., :3], WINDOWS[unit])
    return {"hue": hue, "white": op & ~hue}


def segment_energy(rgba: np.ndarray) -> dict:
    return _segment("h3_energy_elemental", rgba)


def segment_plasma(rgba: np.ndarray) -> dict:
    return _segment("h3_plasma_elemental", rgba)


def _source_basecolor(unit: str) -> np.ndarray:
    sys.path.insert(0, os.path.join(ROOT, "tools", "homm3_unit_look"))
    import io
    import look  # noqa: E402  (read-only: resolve_source picks the un-prebaked original)
    from glbpatch import Glb  # noqa: E402
    b, _where = look.resolve_source(unit)
    g = Glb(b)
    return np.asarray(Image.open(io.BytesIO(g.image_bytes(g.body_base_color_image()))).convert("RGB"))


def build(unit: str, size: int = 1024) -> None:
    tex = _source_basecolor(unit)
    m = _in_window(tex, WINDOWS[unit])
    m = ndi.binary_opening(ndi.binary_closing(m, iterations=2), iterations=1)
    im = Image.fromarray((m * 255).astype(np.uint8), "L").resize((size, size), Image.BILINEAR)
    out = os.path.join(HERE, unit)
    os.makedirs(out, exist_ok=True)
    im.save(os.path.join(out, "tex_hue.png"))
    print(f"{unit}: tex_hue {m.mean() * 100:.1f}% of texels")


if __name__ == "__main__":
    for u in (sys.argv[1:] or list(WINDOWS)):
        build(u)
