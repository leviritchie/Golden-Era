"""Region-cut `file` effect masks for stronghold units whose DEF effect shares the body's colours.

The roster ripper (def_effects.frame_effects) rejects effect pixels whose colours already appear on
the idle body. The thunderbird's yellow-white lightning is the golden body's highlight ramp, so
defEffects keeps only frame 5 (342 px). Here each frame gets a hand-read DEF region in front of the
beak (DEF canvas pixels, read off the 20 px grid of the frames), and inside it every opaque,
bright, non-red pixel is the effect. The beak (red/orange) and the head gold stay body.

    python tools/homm3_unit_look/units/masks/stronghold_masks.py [unit ...]

Writes tools/homm3_unit_look/units/masks/<unit>/<layer>/GG_FF.png (L, 0/255, DEF canvas).
Proof: generated artifact (DEF measurement).
"""
from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "../../../.."))
sys.path.insert(0, os.path.join(ROOT, "tools/homm3_vfx"))
import def_effects as D  # noqa: E402

# unit -> layer -> group -> {frame: [boxes (x0, y0, x1, y1), half-open, DEF px]}
RULES = {
    "h3_thunderbird": {
        "beak_bolt": {12: {
            2: [(264, 170, 290, 200)],
            3: [(299, 165, 345, 245)],
            4: [(299, 180, 350, 295), (270, 238, 299, 295)],
            5: [(270, 215, 350, 300)],
        }},
    },
}


def bolt_pixels(a: np.ndarray) -> np.ndarray:
    """Opaque, bright and not red/orange (the beak): the white core and the yellow branches."""
    rgb = a[..., :3].astype(np.int32)
    op = a[..., 3] == 255
    lum = rgb @ np.array([299, 587, 114]) / 1000
    redish = (rgb[..., 0] - rgb[..., 1]) > 70
    return op & (lum >= 150) & ~redish


def build(unit: str) -> None:
    us = D.load_unit(unit)
    for layer, groups in RULES[unit].items():
        out = os.path.join(HERE, unit, layer)
        os.makedirs(out, exist_ok=True)
        for g, frames in groups.items():
            fr = us.group_rgba(g)
            for i, boxes in frames.items():
                a = fr[i]
                region = np.zeros(a.shape[:2], bool)
                for x0, y0, x1, y1 in boxes:
                    region[y0:y1, x0:x1] = True
                m = bolt_pixels(a) & region
                Image.fromarray((m * 255).astype(np.uint8), "L").save(os.path.join(out, f"{g:02d}_{i:02d}.png"))
                print(f"{unit} {layer} g{g:02d} f{i:02d}: {int(m.sum())} px")


if __name__ == "__main__":
    for u in sys.argv[1:] or RULES:
        build(u)
