"""Backing plate for the Warcry counter's small line ("x4 warcrying   +16 Attack").

The line sits over the battlefield, whose colour ranges from snow to lava, so a soft dark smear goes behind it
(user, 2026-11-18: the small text was not always readable). The plate is procedural: a near-black band with
feathered, slightly ragged edges, densest under the right-aligned text and fading out to the left.

Output: homm3_ui/stronghold_warcry/subline_plate.png (loaded by Homm3StrongholdWarcryCounter.cs).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_ui" / "stronghold_warcry"

WIDTH, HEIGHT = 320, 44
COLOR = (14, 4, 2)
MAX_ALPHA = 0.72


def smoothstep(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def build() -> Image.Image:
    rng = np.random.default_rng(1118)
    xs = np.linspace(0.0, 1.0, WIDTH)
    ys = np.linspace(0.0, 1.0, HEIGHT)
    # ragged left edge and top/bottom edges, like a brush stroke
    jitter = np.convolve(rng.normal(0, 1, HEIGHT + 8), np.ones(9) / 9, mode="valid")[:HEIGHT]
    left = 0.30 + 0.05 * jitter[:, None]
    hx = smoothstep(0.0, 1.0, xs[None, :] / np.maximum(left, 0.05)) * (1 - smoothstep(0.94, 1.0, xs[None, :]))
    edge = np.convolve(rng.normal(0, 1, WIDTH + 16), np.ones(17) / 17, mode="valid")[:WIDTH]
    top = 0.20 + 0.04 * edge[None, :]
    bottom = 0.80 - 0.04 * edge[None, :]
    hy = smoothstep(0.0, 1.0, ys[:, None] / top) * (1 - smoothstep(0.0, 1.0, (ys[:, None] - bottom) / (1 - bottom)))
    alpha = np.clip(hx * hy, 0, 1) * MAX_ALPHA
    rgba = np.zeros((HEIGHT, WIDTH, 4), np.uint8)
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = COLOR
    rgba[..., 3] = np.round(alpha * 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    build().save(args.out / "subline_plate.png", optimize=True)
    print(args.out / "subline_plate.png")


if __name__ == "__main__":
    main()
