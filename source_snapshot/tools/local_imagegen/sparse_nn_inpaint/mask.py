"""NN known-mask helpers for sparse inpaint."""

from __future__ import annotations

import numpy as np
from PIL import Image

from nearest_collapse import sample_coords_for_frame


def build_nn_known_mask(
    lr_w: int,
    lr_h: int,
    *,
    scale: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (known_mask HW bool, coords lr_h,lr_w,2)."""
    hr_w, hr_h = lr_w * scale, lr_h * scale
    coords = sample_coords_for_frame(hr_w, hr_h, lr_w, lr_h)
    mask = np.zeros((hr_h, hr_w), dtype=bool)
    for y in range(lr_h):
        for x in range(lr_w):
            yy = int(coords[y, x, 0])
            xx = int(coords[y, x, 1])
            expected_y = y * scale + scale // 2
            expected_x = x * scale + scale // 2
            if yy != expected_y or xx != expected_x:
                raise RuntimeError(
                    f"NN sample coord drift at ({y},{x}): got ({yy},{xx}) "
                    f"expected ({expected_y},{expected_x})"
                )
            mask[yy, xx] = True
    return mask, coords


def plant_nn_samples_rgb(
    lr: Image.Image,
    *,
    scale: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Plant LR RGB at NN sample sites; free pixels left 0. Returns (hr_rgb, known_mask)."""
    lr_rgb = np.asarray(lr.convert("RGB"), dtype=np.float32)
    lr_h, lr_w = lr_rgb.shape[:2]
    mask, coords = build_nn_known_mask(lr_w, lr_h, scale=scale)
    hr = np.zeros((lr_h * scale, lr_w * scale, 3), dtype=np.float32)
    for y in range(lr_h):
        for x in range(lr_w):
            yy = int(coords[y, x, 0])
            xx = int(coords[y, x, 1])
            hr[yy, xx] = lr_rgb[y, x]
    return hr, mask
