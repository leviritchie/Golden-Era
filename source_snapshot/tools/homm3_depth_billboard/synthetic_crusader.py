"""Colored-rectangle geometry fixture for depth-billboard unit tests.

This is not HoMM3 art and not ``CCRUSD.def``. Do not present these frames as
the crusader move animation. They exist so projection / z-buffer tests have a
tiny near-sword / far-shield occupancy without a HoMM3 install.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image


FRAME_COUNT = 8
WIDTH = 96
HEIGHT = 128


@dataclass(frozen=True)
class SyntheticClip:
    sprites: list[np.ndarray]
    depths: list[np.ndarray]


def _fill_rect(
    rgba: np.ndarray,
    depth: np.ndarray,
    box: tuple[int, int, int, int],
    color: tuple[int, int, int, int],
    depth_value: float,
) -> None:
    x0, y0, x1, y1 = box
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(rgba.shape[1], x1)
    y1 = min(rgba.shape[0], y1)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"empty rect {box}")
    rgba[y0:y1, x0:x1] = color
    depth[y0:y1, x0:x1] = depth_value


def synthetic_crusader_move_frame(index: int) -> tuple[np.ndarray, np.ndarray]:
    if index < 0 or index >= FRAME_COUNT:
        raise ValueError(f"crusader move frame must be 0..{FRAME_COUNT - 1}, got {index}")
    phase = index / float(FRAME_COUNT)
    stride = int(round(math_sin(phase) * 6.0))
    rgba = np.zeros((HEIGHT, WIDTH, 4), dtype=np.uint8)
    depth = np.zeros((HEIGHT, WIDTH), dtype=np.float32)

    cx = WIDTH // 2
    # Shield (far): left of body.
    _fill_rect(rgba, depth, (cx - 28, 46, cx - 8, 92), (70, 90, 150, 255), 0.22)
    # Torso / surcoat.
    _fill_rect(rgba, depth, (cx - 10, 40, cx + 12, 88), (176, 42, 42, 255), 0.52)
    # Helmet.
    _fill_rect(rgba, depth, (cx - 8, 18, cx + 10, 42), (168, 176, 188, 255), 0.58)
    # Visor slit (slightly nearer than helmet).
    _fill_rect(rgba, depth, (cx - 5, 28, cx + 7, 32), (24, 24, 28, 255), 0.64)
    # Back leg / front leg by stride.
    _fill_rect(
        rgba,
        depth,
        (cx - 8 - stride, 86, cx - 1 - stride, 118),
        (96, 88, 80, 255),
        0.40,
    )
    _fill_rect(
        rgba,
        depth,
        (cx + 2 + stride, 86, cx + 9 + stride, 118),
        (120, 108, 96, 255),
        0.56,
    )
    # Sword (near): blade + hilt, swings with the stride.
    blade_x = cx + 14 + stride // 2
    _fill_rect(rgba, depth, (blade_x, 24, blade_x + 5, 96), (214, 220, 230, 255), 0.92)
    _fill_rect(rgba, depth, (blade_x - 6, 52, blade_x + 11, 58), (196, 156, 64, 255), 0.88)
    return rgba, depth


def math_sin(phase: float) -> float:
    return float(np.sin(phase * 2.0 * np.pi))


def synthetic_crusader_move_frames(count: int = FRAME_COUNT) -> SyntheticClip:
    if count != FRAME_COUNT:
        raise ValueError(f"synthetic crusader move is exactly {FRAME_COUNT} frames")
    sprites: list[np.ndarray] = []
    depths: list[np.ndarray] = []
    for index in range(count):
        rgba, depth = synthetic_crusader_move_frame(index)
        sprites.append(rgba)
        depths.append(depth)
    return SyntheticClip(sprites=sprites, depths=depths)


def preview_panel(rgba: np.ndarray, depth01: np.ndarray) -> Image.Image:
    sprite = Image.fromarray(rgba, "RGBA")
    depth_u8 = np.clip(np.rint(depth01 * 255.0), 0, 255).astype(np.uint8)
    depth_rgb = Image.fromarray(depth_u8, "L").convert("RGBA")
    gap = 8
    canvas = Image.new("RGBA", (sprite.width * 2 + gap, sprite.height), (18, 22, 28, 255))
    canvas.paste(sprite, (0, 0), sprite)
    canvas.paste(depth_rgb, (sprite.width + gap, 0))
    return canvas
