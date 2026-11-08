"""Separate the baked lightning layer from CSTORM body pixels.

The storm elemental's arcs are 1-px filaments drawn in near-white palette slots
(10 #FFFFFF, 13, 16) plus pale-yellow sparks, over transparent background. A pixel
is 'effect' when it is bright (luma >= 175) AND sparse: at most 12 of its 5x5
neighbours are opaque. Body shading (the yellow glow painted on the smoke) is dense,
so it stays in the body. Arcs crossing the body are lost; that is recorded, not hidden.
"""
from __future__ import annotations
import numpy as np
from scipy.ndimage import uniform_filter


def effect_mask(idx: np.ndarray, pal: np.ndarray, lum_min=175.0, max_nbrs=12) -> np.ndarray:
    opaque = idx > 7
    lum = pal.astype(float)[idx] @ np.array([0.299, 0.587, 0.114])
    dens = uniform_filter(opaque.astype(float), size=5, mode="constant") * 25
    return opaque & (lum >= lum_min) & (dens <= max_nbrs + 1)
