"""Lab a,b chroma quality: occupancy miss is a miss; lightness is ignored."""
from __future__ import annotations

import numpy as np
import torch

from absolute_chroma_match import _rgb_to_lab
from gpu_depth_silhouette_solver import chroma_quality, gpu_score_raster_resolution, srgb_rgb_to_lab_ab


def _terms(target_fg, pred_fg, target_ab, pred_ab) -> dict[str, float]:
    scored = chroma_quality(
        target_foreground=target_fg,
        predicted_foreground=pred_fg,
        target_ab=target_ab,
        predicted_ab=pred_ab,
        chroma_tolerance=0.10,
        chroma_robust_delta=0.12,
        chroma_error_scale=80.0,
    )
    return {
        "chromaQuality": float(scored["chromaQuality"].item()),
        "chromaError": float(scored["chromaError"].item()),
    }


def run() -> dict[str, object]:
    rgb = np.zeros((2, 2, 3), dtype=np.float32)
    rgb[0, 0] = (40.0, 180.0, 50.0)
    rgb[0, 1] = (40.0, 40.0, 180.0)
    rgb[1, 0] = (10.0, 45.0, 12.0)
    rgb[1, 1] = (160.0, 90.0, 20.0)
    numpy_ab = _rgb_to_lab(rgb)[..., 1:3]
    torch_ab = srgb_rgb_to_lab_ab(torch.from_numpy(rgb / 255.0)).numpy()
    delta = float(np.max(np.abs(numpy_ab - torch_ab)))
    assert delta < 0.05, delta

    target_fg = torch.zeros((1, 8, 8), dtype=torch.bool)
    target_fg[0, 2:6, 2:6] = True
    green = torch.zeros((1, 8, 8, 3), dtype=torch.float32)
    green[0, :, :, 1] = 0.7
    green[0, :, :, 0] = 0.15
    green[0, :, :, 2] = 0.15
    brown = torch.zeros((1, 8, 8, 3), dtype=torch.float32)
    brown[0, :, :, 0] = 0.55
    brown[0, :, :, 1] = 0.28
    brown[0, :, :, 2] = 0.10
    green_ab = srgb_rgb_to_lab_ab(green)
    brown_ab = srgb_rgb_to_lab_ab(brown)
    match = _terms(target_fg, target_fg, green_ab, green_ab)
    # Same Lab a,b is the lightness-ignored case: brightness is not a channel.
    same_hue = _terms(target_fg, target_fg, green_ab, green_ab.clone())
    wrong = _terms(target_fg, target_fg, green_ab, brown_ab)
    missed_fg = target_fg.clone()
    missed_fg[0, 2:6, 2:6] = False
    missed = _terms(target_fg, missed_fg, green_ab, green_ab)

    assert match["chromaQuality"] > 0.97, match
    assert same_hue["chromaQuality"] == match["chromaQuality"]
    assert wrong["chromaQuality"] < match["chromaQuality"], (wrong, match)
    assert missed["chromaQuality"] < match["chromaQuality"]
    assert missed["chromaError"] > 0.9, missed

    proxy = (96, 86)
    off = gpu_score_raster_resolution(
        proxy, chroma_weight=0.0, chroma_resolution=None, chroma_scale=4,
    )
    scaled = gpu_score_raster_resolution(
        proxy, chroma_weight=0.5, chroma_resolution=None, chroma_scale=4,
    )
    explicit = gpu_score_raster_resolution(
        proxy, chroma_weight=0.5, chroma_resolution=(192, 172), chroma_scale=4,
    )
    assert off == proxy, off
    upsampled = gpu_score_raster_resolution(
        proxy, chroma_weight=0.0, chroma_resolution=None, chroma_scale=4, rgb_upsample=True,
    )
    assert upsampled == (384, 344), upsampled
    assert scaled == (384, 344), scaled
    assert explicit == (192, 172), explicit
    try:
        gpu_score_raster_resolution(
            proxy, chroma_weight=0.5, chroma_resolution=None, chroma_scale=1,
        )
        raise AssertionError("chroma_scale=1 should fail")
    except ValueError as exc:
        assert "chroma_scale" in str(exc)
    try:
        gpu_score_raster_resolution(
            proxy, chroma_weight=0.5, chroma_resolution=(384, 172), chroma_scale=4,
        )
        raise AssertionError("mismatched chroma aspect should fail")
    except ValueError as exc:
        assert "same integer scale" in str(exc)

    return {
        "ok": True,
        "labDelta": delta,
        "match": match,
        "wrong": wrong,
        "missed": missed,
        "chromaRaster": scaled,
    }


if __name__ == "__main__":
    print(run())
