"""Build sparse (x, y, rgb) observations from a TwCrPort-style LR portrait."""

from __future__ import annotations

import numpy as np
from PIL import Image

import sys
from pathlib import Path

_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from nearest_collapse import sample_coords_for_frame  # noqa: E402


def build_sparse_observations(
    lr: Image.Image,
    *,
    scale: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (obs N×5 float32, coords lr_h×lr_w×2).

    Each row is ``[y_norm, x_norm, r, g, b]`` with norms in [0, 1] over the HR
    frame, and RGB in [0, 1]. Only Pillow-NEAREST sample sites — no soft fill.
    """
    if scale < 2:
        raise ValueError(f"scale must be >= 2, got {scale}")
    rgb = np.asarray(lr.convert("RGB"), dtype=np.float32) / 255.0
    lr_h, lr_w = rgb.shape[:2]
    hr_w, hr_h = lr_w * scale, lr_h * scale
    coords = sample_coords_for_frame(hr_w, hr_h, lr_w, lr_h)

    n = lr_h * lr_w
    obs = np.empty((n, 5), dtype=np.float32)
    i = 0
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
            obs[i, 0] = yy / max(hr_h - 1, 1)
            obs[i, 1] = xx / max(hr_w - 1, 1)
            obs[i, 2:5] = rgb[y, x]
            i += 1
    if i != n:
        raise RuntimeError(f"observation count {i} != {n}")
    return obs, coords


def observations_to_tensor(obs: np.ndarray):
    """Convert N×5 numpy observations to a torch float32 tensor (no device)."""
    import torch

    if obs.ndim != 2 or obs.shape[1] != 5:
        raise ValueError(f"expected (N,5) observations, got {obs.shape}")
    return torch.from_numpy(np.ascontiguousarray(obs, dtype=np.float32))


def self_check() -> None:
    """Fail-closed coord contract for a toy 4×4 → 32×32 (S=8) frame."""
    lr = Image.fromarray(
        np.arange(4 * 4 * 3, dtype=np.uint8).reshape(4, 4, 3), mode="RGB"
    )
    obs, coords = build_sparse_observations(lr, scale=8)
    if obs.shape != (16, 5):
        raise AssertionError(f"obs shape {obs.shape}")
    if coords.shape != (4, 4, 2):
        raise AssertionError(f"coords shape {coords.shape}")
    # Center of block (0,0) at S=8 is (4,4)
    if int(coords[0, 0, 0]) != 4 or int(coords[0, 0, 1]) != 4:
        raise AssertionError(f"bad first coord {coords[0, 0]}")
    if not (0.0 <= obs.min() and obs.max() <= 1.0):
        raise AssertionError("obs out of [0,1]")
    print("observations.self_check OK", flush=True)


if __name__ == "__main__":
    self_check()
