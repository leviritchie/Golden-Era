"""Phoenix / firebird: per-frame effect masks for the unit-look specs (effectMask method "file").

The roster's colour rule (def_effects: colours absent from the idle frames) cannot see the fire of a unit whose
body *is* fire, so these masks come from the region segmentation of phoenix_fire_motion.py instead:
  BODY  = largest component of the main silhouette after an r=3 opening (dilated 1, inside the silhouette)
  FLAME = main silhouette minus BODY (thin tongues, tips, the breath jet)
  EMBER = components detached from the main silhouette
  TIPS  = phoenix_fire_lab.tip_mask: the ragged top 20-34 px of the upper silhouette (the crest), feathers excluded
Masks are the DEF's own pixels only; the spec's bodyMask.subtractMeshSilhouette removes what the mesh draws
(so the crest drawn in front of the quad's bone is identical, from the SpriteCam, to a crest drawn behind the body).

Writes tools/homm3_unit_look/units/masks/<unit>/<layer>/<GG>_<FF>.png (L, 450x400, 255 = on; committed: the
validator warns on untracked file masks) plus a preview sheet and px counts under
artifacts/homm3_vfx_experiments/phoenix/masks_preview/.
Proof: generated artifact (2D masks on the DEF canvas).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import h3def  # noqa: E402
import phoenix_fire_lab as lab  # noqa: E402
import phoenix_fire_motion as fm  # noqa: E402

MASKS = ROOT / "tools/homm3_unit_look/units/masks"
PREVIEW = lab.BASE / "masks_preview"

# layer -> {clip group: frames}; clip groups use the GLB clip names' DEF groups
PHOENIX = {
    # (no crest flipbook: the DEF crest lands off the mesh where the retarget's pose differs; loops use the
    #  procedural fire_tongues particles instead -- see docs/homm3_vfx_experiments.md "Phoenix fire")
    "breath": {12: range(3, 12)},        # the beak jet: flame/ember in front of the body
    "hit_sparks": {3: range(2, 6)},      # embers flung outward
    "death_burn": {5: range(0, 5)},      # white-hot flare, wings burning, pillar of fire (frame 4: everything off-body)
    "death_ash": {5: range(5, 7)},       # the ash pile: the whole DEF frame
}
FIREBIRD = {
    "breath": {12: range(4, 12)},
    "death_burn": {5: range(1, 5)},      # flare frames 1-3: the feather fringe; frame 4: the burning pillar (off-mesh)
    "death_ash": {5: range(5, 7)},       # the ash pile (same art as the phoenix's)
}


FIRE_LUMA = 100   # DEF body luma split: fire (>=) vs dark rest (beak, talons, feather strokes)


def def_regions(rgba):
    """lighting.defSegmenter for h3_phoenix: {"fire", "dark"} bool masks of a DEF frame (uint8 RGBA).
    The runner intersects each with the DEF body minus effect pixels; "fire" pairs with the texture's
    fire_region_uv.png (Lab chroma rule), and the dark rest is graded by the unit-level mode."""
    seg = fm.segment(np.asarray(rgba, np.uint8))
    return {"fire": seg["body"] & (seg["luma"] >= FIRE_LUMA), "dark": seg["body"] & (seg["luma"] < FIRE_LUMA)}


def phoenix_mask(layer, g, i, seg):
    fx = seg["flame"] | seg["ember"]
    if layer == "breath":
        return lab.breath_mask(seg, i)
    if layer == "hit_sparks":
        return seg["ember"]
    if layer == "death_burn":
        m = lab.tip_mask(seg, seed=500 + i) | fx
        if i == 4:
            m = seg["opaque"]             # the pillar: everything the mesh does not draw (subtractMeshSilhouette)
        return m
    if layer == "death_ash":
        return seg["opaque"]
    raise KeyError(layer)


def firebird_mask(layer, g, i, seg):
    if layer == "breath":
        return lab.breath_mask(seg, i)
    if layer == "death_burn":
        return seg["opaque"] if i == 4 else (seg["flame"] | seg["ember"])
    if layer == "death_ash":
        return seg["opaque"]
    raise KeyError(layer)


def export(unit, defname, table, fn):
    d = h3def.read_def(defname)
    counts = {}
    rows = []
    for layer, groups in table.items():
        out = MASKS / unit / layer
        out.mkdir(parents=True, exist_ok=True)
        for old in out.glob("*.png"):
            old.unlink()
        for g, frames in groups.items():
            for i in frames:
                rgba = fm.frame_rgba(d.groups[g][i], d.palette)
                seg = fm.segment(rgba)
                m = fn(layer, g, i, seg) & seg["opaque"]
                Image.fromarray((m * 255).astype(np.uint8), "L").save(out / f"{g:02d}_{i:02d}.png", optimize=True)
                counts.setdefault(layer, {}).setdefault(str(g), []).append(int(m.sum()))
                rows.append((layer, g, i, rgba, m))
    PREVIEW.mkdir(parents=True, exist_ok=True)
    # preview: DEF frame dimmed, mask pixels at full colour
    tiles = []
    for layer, g, i, rgba, m in rows:
        ys, xs = np.nonzero(rgba[..., 3] == 255)
        box = (max(0, xs.min() - 20), max(0, ys.min() - 30), min(450, xs.max() + 20), min(400, ys.max() + 10))
        bg = np.zeros_like(rgba)
        bg[...] = (40, 48, 36, 255)
        dim = rgba.copy()
        dim[..., :3] = (dim[..., :3] * 0.25).astype(np.uint8)
        im = np.where((rgba[..., 3:] == 255), dim, bg)
        im[m] = rgba[m]
        t = Image.fromarray(im[..., :3]).crop(box)
        ImageDraw.Draw(t).text((2, 2), f"{layer} g{g} f{i}", fill=(255, 255, 255))
        tiles.append(t)
    w = max(t.width for t in tiles)
    h = max(t.height for t in tiles)
    cols = 8
    sheet = Image.new("RGB", (w * cols, h * ((len(tiles) + cols - 1) // cols)), (20, 20, 20))
    for k, t in enumerate(tiles):
        sheet.paste(t, ((k % cols) * w, (k // cols) * h))
    sheet.save(PREVIEW / f"{unit}_masks.png")
    (PREVIEW / f"{unit}_mask_px.json").write_text(json.dumps(counts, indent=1))
    print(unit, json.dumps(counts))


def main():
    export("h3_phoenix", "cphx.def", PHOENIX, phoenix_mask)
    export("h3_firebird", "cfbird.def", FIREBIRD, firebird_mask)


if __name__ == "__main__":
    main()
