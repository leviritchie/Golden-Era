"""Builds the Cove Dig spell icon by recolouring the vanilla Graverobber shovel emblem (graverobber_passive_1_name:
a gold shovel striking the ground on a dark navy disc). The emblem's shading is kept; only the colours change. The
shovel (handle and blade) and the ground impact burst below it are separate shapes, so each gets its own colour.

Usage: python tools/cove_treasure/build_dig_icon.py <game HeroesOldenEra_Data dir> <out png> [variant]
       python tools/cove_treasure/build_dig_icon.py <game HeroesOldenEra_Data dir> <out png> --sheet
"""
import sys

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

from build_marker_art import load_textures

SOURCE = "graverobber_passive_1_name"
SIZE = 256
SRC_BG = np.array([14, 19, 32], np.float32)
SRC_FG = np.array([196, 160, 96], np.float32)

# name: (disc colour, shovel colour, impact colour)
VARIANTS = {
    "sea_silver": ((16, 62, 74), (206, 216, 226), (240, 208, 130)),  # user pick 2026-11-17: silver shovel, gold impact
    "sea": ((16, 62, 74), (240, 208, 130), (240, 208, 130)),         # deep Cove teal, pale gold throughout
    "sand": ((196, 160, 104), (92, 48, 26), (92, 48, 26)),           # sand disc, dark wood-brown
    "red": ((28, 20, 18), (196, 52, 36), (196, 52, 36)),             # near-black disc, treasure-map red
}
DEFAULT = "sea_silver"


def shovel_mask(t):
    """Soft mask of the shovel: the connected emblem shape that holds the top of the handle."""
    labels, _ = ndimage.label(t > 0.2)
    cols = np.where((t > 0.5).any(axis=1))[0]
    top = cols[0]
    label = labels[top, np.where(t[top] > 0.5)[0][0]]
    mask = Image.fromarray(((labels == label) * 255).astype(np.uint8))
    mask = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(1.0))
    return np.asarray(mask).astype(np.float32)[..., None] / 255.0


def recolour(emblem, disc, shovel, impact):
    arr = np.asarray(emblem.convert("RGBA")).astype(np.float32)
    rgb, alpha = arr[..., :3], arr[..., 3:]
    axis = SRC_FG - SRC_BG
    # position of each pixel between the emblem's two colours (above 1 = its highlights, kept as highlights)
    t = ((rgb - SRC_BG) @ axis) / float(axis @ axis)
    m = shovel_mask(t)
    t = np.clip(t, -0.15, 1.35)[..., None]
    disc = np.array(disc, np.float32)
    ink = np.array(shovel, np.float32) * m + np.array(impact, np.float32) * (1.0 - m)
    out = disc + (ink - disc) * t
    result = np.concatenate([np.clip(out, 0, 255), alpha], axis=2).astype(np.uint8)
    return Image.fromarray(result, "RGBA").resize((SIZE, SIZE), Image.LANCZOS)


def main(data_dir, out_path, variant):
    emblem = load_textures(data_dir, [SOURCE])[SOURCE]
    if variant == "--sheet":
        names = ["original"] + list(VARIANTS)
        sheet = Image.new("RGBA", (SIZE * len(names) + 20 * (len(names) + 1), SIZE + 40), (38, 40, 56, 255))
        for i, name in enumerate(names):
            icon = emblem.resize((SIZE, SIZE), Image.LANCZOS) if name == "original" else recolour(emblem, *VARIANTS[name])
            sheet.alpha_composite(icon, (20 + i * (SIZE + 20), 20))
        sheet.save(out_path)
    else:
        recolour(emblem, *VARIANTS[variant]).save(out_path)
    print("wrote", out_path)


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else DEFAULT)
