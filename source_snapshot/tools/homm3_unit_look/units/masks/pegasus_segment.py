"""Pegasus white coat + feathers: `lighting.defSegmenter` for h3_pegasus (CPEGAS.def).

The DEF draws a white winged horse with pale grey feather shading, ridden by a tan-skinned, blonde elf in brown
leather. The Meshy wing feathers are thin layered sheets: the unit-level v7c grade (gamma pinned at its 0.5 bound)
takes their AO-occluded texels to black, so the wings render dark grey with black blotches although the raw bake
is white (artifacts/homm3_unit_look/h3_pegasus/review_sheet.png, look column, 2026-10-09). A `defPalette` region
on the wing bones hands the wing texels the DEF's own white-to-grey coat/feather colours by rank instead.

  segment_pegasus(rgba_uint8) -> {"pale": bool mask, "rest": bool mask}   (DEF frame, opaque pixels)

The DEF wing and coat are one material (same white, same grey shading), so "pale" is both: the wing palette is
the white coat + feather palette. Window measured on CPEGAS 02_00 / 00_03 / 12_04 / 03_03 (opaque px, HSV):
sat p10/p50/p90 0.06-0.07 / 0.14 / 0.40-0.41, value p50 0.58-0.71. Pale = sat < 0.25 and value > 0.30 (the
rider's skin, hair and leather are saturated, the hooves and outline dark), in 8-connected pieces of at least
40 px (sword and hair glints pass the colour test alone), then closed (2 iterations, opaque only) so the feather
shading lines inside the wing join it. Covers 0.67-0.76 of the opaque pixels.
Coat mask (2026-10-09, coordinator: fix the whole unit, not just the wings): the rider's body is weighted to the
horse's Spine1, so a bone mask cannot split coat from rider. `build_coat_mask` writes a UV mask of the raw Meshy
albedo's pale texels (sat < 0.20, value > 0.45: all wing area, 89% of the horse area, 21% of the rider-bone area -
sword blade and the raw white hair) to h3_pegasus/coat_pale.png; the coat region grades those texels to the DEF
"pale" palette by rank and the rider + hooves stay on the unit-level grade, fitted on the DEF "rest" pixels.
The wing-bone texels (skin weight > 0.5, rasterised like regions.texture_weight) are cut out of the coat mask and
graded by their own wing region, also to the DEF "pale" palette: ranked together with the coat, the slightly darker
raw feathers (L p50 0.65 vs coat 0.71) took the palette's shaded half and read brown-grey (offline rank estimate:
wing p50 0.48 joint vs 0.67 on their own, coat 0.67); overlapping masks would instead split each texel's weight.

    python tools/homm3_unit_look/units/masks/pegasus_segment.py [unit]   (rebuilds the unit's masks from its look work source_basecolor.png;
    h3_silver_pegasus / h3_gold_pegasus: build_armoured_masks, see the armoured-pegasi section)
Proof tier: generated artifact (offline DEF colour measurement).
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi

PALE = {"satMax": 0.25, "valueMin": 0.30, "minComponentPx": 40, "closeIters": 2}
WING = {"valuePct": 40}
RIDER = {"rbMin": 0.08, "satMin": 0.20, "valueMin": 0.08, "minComponentPx": 20}


def _hsv(rgb: np.ndarray):
    c = rgb.astype(np.float32) / 255.0
    mx, mn = c.max(-1), c.min(-1)
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    return s, mx


def segment_pegasus(rgba: np.ndarray) -> dict:
    op = rgba[..., 3] == 255
    s, v = _hsv(rgba[..., :3])
    pale = op & (s < PALE["satMax"]) & (v > PALE["valueMin"])
    lab, n = ndi.label(pale, np.ones((3, 3), bool))
    if n:
        size = ndi.sum(pale, lab, np.arange(1, n + 1))
        pale = np.isin(lab, 1 + np.nonzero(size >= PALE["minComponentPx"])[0])
    pale = ndi.binary_closing(pale, np.ones((3, 3), bool), iterations=PALE["closeIters"]) & op
    c = rgba[..., :3].astype(np.float32) / 255.0
    rb = (c[..., 0] - c[..., 2]) / np.maximum(v, 1e-3)
    wing = np.zeros_like(pale)
    if pale.any():
        bright = pale & (v >= np.percentile(v[pale], WING["valuePct"]))
        if bright.any():
            wing = bright & (rb <= np.median(rb[bright]))
    warm = ((c[..., 0] - c[..., 2]) >= RIDER["rbMin"]) & (c[..., 0] >= c[..., 1])
    rider = op & ~pale & warm & (s > RIDER["satMin"]) & (v > RIDER["valueMin"])
    lab, n = ndi.label(rider, np.ones((3, 3), bool))
    if n:
        size = ndi.sum(rider, lab, np.arange(1, n + 1))
        rider = np.isin(lab, 1 + np.nonzero(size >= RIDER["minComponentPx"])[0])
    return {"pale": pale, "rest": op & ~pale, "wing": wing, "rider": rider}


COAT = {"satMax": 0.20, "valueMin": 0.45, "size": 2048}
RIDER_TEX = {"rbMin": 0.08, "chromaMin": 0.10}


WING_BONES = ["WingL_*", "WingR_*", "LeftWing", "RightWing"]


def _wing_texels(glb, size):
    import sys
    from pathlib import Path
    here = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(here), str(here.parent / "homm3_prebake")]
    import regions as RG
    from glbpatch import Glb
    val, cov = RG.rasterise_values(RG.vertex_values(Glb(Path(glb).read_bytes()), {"bones": WING_BONES}), size)
    return (val > 0.5) & cov


def _albedo(src_png):
    from PIL import Image
    im = Image.open(src_png).convert("RGB").resize((COAT["size"], COAT["size"]), Image.BILINEAR)
    return np.asarray(im)


def rider_texels(rgb: np.ndarray) -> np.ndarray:
    """Warm raw-albedo texels (the riderPaint test): skin, leather, hair-brown."""
    c = rgb.astype(np.float32) / 255.0
    return ((c[..., 0] - c[..., 2]) >= RIDER_TEX["rbMin"]) & ((c.max(-1) - c.min(-1)) >= RIDER_TEX["chromaMin"])


def build_coat_mask(src_png, out_png, glb=None) -> float:
    """Raw-albedo pale texels, minus the rider (warm) texels and the wing-bone texels of `glb` -> 8-bit UV mask
    (glTF UV, v down, same layout as the base colour). Returns coverage."""
    from PIL import Image
    rgb = _albedo(src_png)
    s, v = _hsv(rgb)
    m = (s < COAT["satMax"]) & (v > COAT["valueMin"]) & ~rider_texels(rgb)
    if glb is not None:
        m &= ~_wing_texels(glb, COAT["size"])
    Image.fromarray((m * 255).astype(np.uint8)).save(out_png, optimize=True)
    return float(m.mean())


def build_rider_mask(src_png, out_png, glb=None) -> float:
    """Raw-albedo warm texels, minus the wing-bone texels -> 8-bit UV mask. Disjoint from the coat mask."""
    from PIL import Image
    rgb = _albedo(src_png)
    m = rider_texels(rgb)
    if glb is not None:
        m &= ~_wing_texels(glb, COAT["size"])
    Image.fromarray((m * 255).astype(np.uint8)).save(out_png, optimize=True)
    return float(m.mean())

# ----------------------------------------------------------------------------- armoured pegasi (2026-10-09)
# h3_silver_pegasus (CAPEGS.def) and h3_gold_pegasus (LVL4ALT.def) shipped on the plain unit-level v7c grade, which
# crushed the AO-occluded feather and coat texels to black (frozen pegasus_slice_v1 look basecolor, UV-area share under
# L 0.25: silver wing 22% / horse 36% vs raw 0% / 8%, gold wing 52% / horse 43% vs raw 0% / 5%) - the user's "black
# splotches over the pegasi" in game. Same fix as h3_pegasus: defPalette regions, plus an armour region so the barding
# keeps the DEF's own gold (never the white coat palette).
# DEF (fit frames 02_00 / 00_03 / 12_04 / 03_03, opaque px): pale coat + wings 44-46%, rider orange 9-12%, gold-hued
# barding 11% (silver: gold trim over a dark checker, which stays on the unit-level grade) / 22% (gold: full barding).
# Raw Meshy albedo k-means: cool-white coat + feathers (hue ~228, s < 0.1), gold barding (hue 45-47, s 0.5-0.64, the
# only gold-hued material on both units), rider skin / leather / silver's brown blanket (hue 25-32, s 0.23-0.36),
# warm-grey leg coat + silver scale mail (hue 39-51, s 0.05-0.07).
ARMOUR = {"hueMin": 35.0, "hueMax": 70.0, "satMin": 0.20, "valueMin": 0.12, "minComponentPx": 20, "closeIters": 2}


def _hue(rgb: np.ndarray) -> np.ndarray:
    c = rgb.astype(np.float32) / 255.0
    mx, mn = c.max(-1), c.min(-1)
    d = np.maximum(mx - mn, 1e-6)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    return np.where(mx - mn > 0, h, -1.0)


def _keep(m: np.ndarray, min_px: int) -> np.ndarray:
    lab, n = ndi.label(m, np.ones((3, 3), bool))
    if not n:
        return m
    size = ndi.sum(m, lab, np.arange(1, n + 1))
    return np.isin(lab, 1 + np.nonzero(size >= min_px)[0])


def gold_hued(rgb: np.ndarray) -> np.ndarray:
    h = _hue(rgb)
    s, v = _hsv(rgb)
    return (h >= ARMOUR["hueMin"]) & (h < ARMOUR["hueMax"]) & (s >= ARMOUR["satMin"]) & (v >= ARMOUR["valueMin"])


def _segment_armoured(rgba: np.ndarray, fill: bool) -> dict:
    """pale / wing / rider as segment_pegasus, with the gold barding ("armour") carved out first. fill=True (gold
    pegasus) adds what the gold panels enclose (their dark shading); silver keeps only the gold trim (the enclosed
    checker is dark and stays on the unit-level grade)."""
    op = rgba[..., 3] == 255
    s, v = _hsv(rgba[..., :3])
    arm = _keep(op & gold_hued(rgba[..., :3]), ARMOUR["minComponentPx"])
    arm = ndi.binary_closing(arm, np.ones((3, 3), bool), iterations=ARMOUR["closeIters"])
    if fill:
        arm = ndi.binary_fill_holes(arm)
    arm &= op
    pale = _keep(op & ~arm & (s < PALE["satMax"]) & (v > PALE["valueMin"]), PALE["minComponentPx"])
    pale = ndi.binary_closing(pale, np.ones((3, 3), bool), iterations=PALE["closeIters"]) & op & ~arm
    c = rgba[..., :3].astype(np.float32) / 255.0
    rb = (c[..., 0] - c[..., 2]) / np.maximum(v, 1e-3)
    wing = np.zeros_like(pale)
    if pale.any():
        bright = pale & (v >= np.percentile(v[pale], WING["valuePct"]))
        if bright.any():
            wing = bright & (rb <= np.median(rb[bright]))
    warm = ((c[..., 0] - c[..., 2]) >= RIDER["rbMin"]) & (c[..., 0] >= c[..., 1])
    rider = _keep(op & ~pale & ~arm & warm & (s > RIDER["satMin"]) & (v > RIDER["valueMin"]), RIDER["minComponentPx"])
    return {"pale": pale, "wing": wing, "armour": arm, "rider": rider, "rest": op & ~pale & ~arm & ~rider}


def segment_silver_pegasus(rgba: np.ndarray) -> dict:
    return _segment_armoured(rgba, fill=False)


def segment_gold_pegasus(rgba: np.ndarray) -> dict:
    return _segment_armoured(rgba, fill=True)


def build_armoured_masks(src_png, out_dir, glb=None) -> dict:
    """UV masks for an armoured pegasus, disjoint, all minus the wing-bone texels of `glb`:
    armour_gold.png = gold-hued raw texels; rider_warm.png = warm raw texels (rider_texels) that are not gold-hued
    (skin, leather, silver's brown blanket); coat_pale.png = sat < 0.20 and value > 0.45, minus both."""
    from pathlib import Path
    from PIL import Image
    rgb = _albedo(src_png)
    s, v = _hsv(rgb)
    wing = _wing_texels(glb, COAT["size"]) if glb is not None else np.zeros(rgb.shape[:2], bool)
    arm = gold_hued(rgb) & ~wing
    rider = rider_texels(rgb) & ~arm & ~wing
    coat = (s < COAT["satMax"]) & (v > COAT["valueMin"]) & ~arm & ~rider & ~wing
    out = {}
    for name, m in (("armour_gold", arm), ("rider_warm", rider), ("coat_pale", coat)):
        Image.fromarray((m * 255).astype(np.uint8)).save(Path(out_dir) / f"{name}.png", optimize=True)
        out[name] = round(float(m.mean()), 3)
    return out


if __name__ == "__main__":
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[4]
    unit = sys.argv[1] if len(sys.argv) > 1 else "h3_pegasus"
    d = Path(__file__).resolve().parent / unit
    d.mkdir(exist_ok=True)
    src = root / f"artifacts/homm3_unit_look/{unit}/work/source_basecolor.png"
    glb = root / f"artifacts/homm3_def_retarget/{unit}/{unit}_def_retarget.glb"
    if unit == "h3_pegasus":
        print(d / "coat_pale.png", round(build_coat_mask(src, d / "coat_pale.png", glb), 3))
        print(d / "rider_warm.png", round(build_rider_mask(src, d / "rider_warm.png", glb), 3))
    else:
        print(d, build_armoured_masks(src, d, glb))
