#!/usr/bin/env python3
"""Predict relative depth maps for sprite frames (alpha-masked).

Per-frame Depth Anything V2 Small via Hugging Face transformers. This is the
comparison / still-image lane. The animation pose pipeline uses
``run_vda_movement_depth.ensure_vda_pipeline_cache`` (Video Depth Anything)
and refuses to mix the two caches.

Output PNGs are 16-bit grayscale with near=bright. Outside alpha is zero.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image


_PIPE_CACHE = {}


def _predict_batch(rgb_u8: np.ndarray, pipe) -> np.ndarray:
    """Return float depth (larger = farther, model-native) HxW."""
    pil = Image.fromarray(rgb_u8, "RGB")
    out = pipe(pil)
    depth = out["depth"]
    if isinstance(depth, Image.Image):
        arr = np.asarray(depth, dtype=np.float32)
        if arr.ndim == 3:
            arr = arr[:, :, 0]
    else:
        arr = np.asarray(depth, dtype=np.float32)
    return arr


def predict_sprite_depth(
    rgba: np.ndarray,
    pipe,
    *,
    bg: tuple[int, int, int] = (128, 128, 128),
) -> np.ndarray:
    """Alpha-masked relative depth in [0,1], near=1, outside=0."""
    rgba = np.asarray(rgba)
    if rgba.dtype != np.uint8:
        if rgba.max() <= 1.5:
            rgba = np.clip(np.rint(rgba * 255.0), 0, 255).astype(np.uint8)
        else:
            rgba = np.clip(rgba, 0, 255).astype(np.uint8)
    alpha = rgba[:, :, 3].astype(np.float32) / 255.0
    mask = alpha > 0.08
    rgb = rgba[:, :, :3].copy()
    # Neutral composite so transparent BG does not dominate monocular depth.
    for c, v in enumerate(bg):
        channel = rgb[:, :, c].astype(np.float32)
        rgb[:, :, c] = np.clip(channel * alpha + v * (1.0 - alpha), 0, 255).astype(np.uint8)

    raw = _predict_batch(rgb, pipe)
    if raw.shape[0] != rgba.shape[0] or raw.shape[1] != rgba.shape[1]:
        raw_img = Image.fromarray(raw.astype(np.float32), mode="F")
        raw_img = raw_img.resize((rgba.shape[1], rgba.shape[0]), Image.Resampling.BILINEAR)
        raw = np.asarray(raw_img, dtype=np.float32)

    out = np.zeros(mask.shape, dtype=np.float32)
    if not mask.any():
        return out
    vals = raw[mask]
    # Robust stretch so flat monocular estimates still use full [0,1].
    lo = float(np.percentile(vals, 5.0))
    hi = float(np.percentile(vals, 95.0))
    if hi - lo < 1e-6:
        out[mask] = 1.0
    else:
        # Depth Anything V2 relative depth: larger = closer (disparity-like).
        out[mask] = np.clip((raw[mask] - lo) / (hi - lo), 0.0, 1.0).astype(np.float32)
    # Keep full range on opaque pixels; alpha only gates validity (zeros outside mask).
    return out


def save_depth_u16(path: Path, depth01: np.ndarray) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    u16 = np.clip(np.rint(depth01 * 65535.0), 0, 65535).astype(np.uint16)
    Image.fromarray(u16).save(path)


def load_depth_u16(path: Path) -> np.ndarray:
    arr = np.asarray(Image.open(path), dtype=np.float32)
    if arr.max() > 1.5:
        arr = arr / (65535.0 if arr.max() > 255.5 else 255.0)
    return np.clip(arr, 0.0, 1.0).astype(np.float32)


def build_pipe(device: str | None = None):
    import torch
    from transformers import pipeline

    if not torch.cuda.is_available():
        raise RuntimeError("Depth estimation requires CUDA; refusing CPU inference.")
    if device is None:
        device = "cuda:0"
    if str(device).lower() in {"cpu", "-1"}:
        raise RuntimeError(f"Depth estimation requires CUDA; received device={device!r}.")
    cache_key = str(device)
    cached = _PIPE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    pipe = pipeline(
        task="depth-estimation",
        model="depth-anything/Depth-Anything-V2-Small-hf",
        device=device,
    )
    _PIPE_CACHE[cache_key] = pipe
    return pipe


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--frames", type=Path, required=True, help="RGBA sprite frame directory")
    ap.add_argument("--out", type=Path, required=True, help="Output depth directory")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    sources = sorted(args.frames.glob("*.png"))
    if args.limit > 0:
        sources = sources[: args.limit]
    assert sources, f"no frames in {args.frames}"
    pipe = build_pipe()
    print(f"predicting depth for {len(sources)} frames -> {args.out}")
    for i, src in enumerate(sources, 1):
        rgba = np.asarray(Image.open(src).convert("RGBA"), dtype=np.uint8)
        depth = predict_sprite_depth(rgba, pipe)
        save_depth_u16(args.out / src.name, depth)
        if i % 5 == 0 or i == len(sources):
            print(f"  [{i}/{len(sources)}] {src.name}")
    print("done")


if __name__ == "__main__":
    main()
