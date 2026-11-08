"""Centaur captain grey hair: `lighting.defSegmenter` for h3_centaur_captain (CECENT.def).

The DEF draws a white-to-grey horse body with mid-grey fetlock feathering and tail, ridden by a tan-skinned
torso with a gold halberd. The Meshy source albedo paints the feathering and tail hair green-grey (raw texels
with a* < -4: 3.7% of the atlas, mean Lab 46.6/-15/10.7; about 0.94% stay green after look B, 9526ef1142
probe), which no unit-level grade can neutralise. A `defPalette` region hands those texels the DEF's own
neutral grey hair palette by rank.

  segment_centaur_captain(rgba_uint8) -> {"grey", "hair", "rest"}   (DEF frame, opaque pixels)

Window measured on CECENT 02_00 / 00_03 / 12_04 / 03_03 (opaque px, HSV): sat p50 0.07-0.09, p70 0.14-0.20;
value p10/p50/p90 0.16/0.52/0.87. grey = sat < 0.20 and value > 0.25 in 8-connected pieces of >= 40 px (0.58-0.65
of the opaque pixels: horse coat, feathering, tail). hair = the darker half of grey (value below the grey p55):
the DEF's feathering and tail are its shaded mid greys, not the white coat highlights.
`build_hair_mask` writes the UV mask of the raw albedo's green-cast texels (a* < -4 incl. the strong green flecks up to C* 90, components
>= 24 px at 2048, dilated 1 px) to h3_centaur_captain/hair_green.png.

    python tools/homm3_unit_look/units/masks/centaur_segment.py   (rebuilds the mask from the look work source_basecolor.png)
Proof tier: generated artifact (offline DEF colour measurement).
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi

GREY = {"satMax": 0.20, "valueMin": 0.25, "minComponentPx": 40, "hairPct": 55}
HAIR_TEX = {"aMax": -4.0, "chromaMax": 90.0, "minComponentPx": 24, "dilate": 1, "size": 2048}


def _hsv(rgb):
    c = rgb.astype(np.float32) / 255.0
    mx, mn = c.max(-1), c.min(-1)
    return np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0), mx


def _keep(m, min_px):
    lab, n = ndi.label(m, np.ones((3, 3), bool))
    if not n:
        return m
    size = ndi.sum(m, lab, np.arange(1, n + 1))
    return np.isin(lab, 1 + np.nonzero(size >= min_px)[0])


def segment_centaur_captain(rgba: np.ndarray) -> dict:
    op = rgba[..., 3] == 255
    s, v = _hsv(rgba[..., :3])
    grey = _keep(op & (s < GREY["satMax"]) & (v > GREY["valueMin"]), GREY["minComponentPx"])
    hair = np.zeros_like(grey)
    if grey.any():
        hair = grey & (v < np.percentile(v[grey], GREY["hairPct"]))
    return {"grey": grey, "hair": hair, "rest": op & ~grey}


def _lab(rgb):
    c = rgb.astype(np.float32) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = c @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def build_hair_mask(src_png, out_png) -> float:
    """Raw-albedo green-cast hair texels -> 8-bit UV mask (glTF UV, v down, base colour layout). Returns coverage."""
    from PIL import Image
    rgb = np.asarray(Image.open(src_png).convert("RGB").resize((HAIR_TEX["size"],) * 2, Image.BILINEAR))
    lab = _lab(rgb)
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    m = _keep((lab[..., 1] < HAIR_TEX["aMax"]) & (chroma < HAIR_TEX["chromaMax"]), HAIR_TEX["minComponentPx"])
    if HAIR_TEX["dilate"]:
        m = ndi.binary_dilation(m, np.ones((3, 3), bool), iterations=HAIR_TEX["dilate"])
    Image.fromarray((m * 255).astype(np.uint8)).save(out_png, optimize=True)
    return float(m.mean())


if __name__ == "__main__":
    from pathlib import Path
    root = Path(__file__).resolve().parents[4]
    src = root / "artifacts/homm3_unit_look/h3_centaur_captain/work/source_basecolor.png"
    out = Path(__file__).resolve().parent / "h3_centaur_captain" / "hair_green.png"
    print(f"hair_green coverage {build_hair_mask(src, out):.4f} -> {out}")
