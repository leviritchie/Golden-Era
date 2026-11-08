"""HoMM3 DEF soft ground-shadow cull (near-black RGB + partial alpha).

Same rule as tools/homm3_import/artifact_map_shadow_crop.py.
Opaque near-black subject pixels (e.g. metal) are kept.
"""
from __future__ import annotations

import numpy as np

_NEAR_BLACK_MAX = 8
_SHADOW_ALPHA_MAX = 199


def cull_def_soft_shadow_rgba(arr: np.ndarray) -> tuple[np.ndarray, int]:
    """Zero alpha on DEF soft-shadow pixels. Returns (rgba_uint8, culled_count)."""
    if arr.ndim != 3 or arr.shape[2] != 4:
        raise ValueError(f"expected HxWx4 RGBA, got {arr.shape}")
    out = np.array(arr, dtype=np.uint8, copy=True)
    rgb_max = out[..., :3].max(axis=-1)
    a = out[..., 3]
    shadow = (a > 0) & (a <= _SHADOW_ALPHA_MAX) & (rgb_max <= _NEAR_BLACK_MAX)
    n = int(shadow.sum())
    out[shadow, 3] = 0
    return out, n


NEAR_BLACK_MAX = _NEAR_BLACK_MAX
SHADOW_ALPHA_MAX = _SHADOW_ALPHA_MAX
