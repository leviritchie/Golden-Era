"""Pad Stage A into Infinity's 1024^2 frame and encode multi-scale bit labels."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image
from torchvision.transforms.functional import to_tensor


TARGET = 1024


def pad_stage_a_to_square(stage_a: Image.Image, target: int = TARGET) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Letterbox Stage A onto a black square. Returns (padded, crop_box xyxy for restore)."""
    rgb = stage_a.convert("RGB")
    w, h = rgb.size
    if w > target or h > target:
        raise ValueError(f"Stage A {w}x{h} exceeds Infinity target {target}x{target}")
    canvas = Image.new("RGB", (target, target), (0, 0, 0))
    x0 = (target - w) // 2
    y0 = (target - h) // 2
    canvas.paste(rgb, (x0, y0))
    crop_box = (x0, y0, x0 + w, y0 + h)
    return canvas, crop_box


def crop_from_square(img: Image.Image, crop_box: tuple[int, int, int, int]) -> Image.Image:
    return img.convert("RGB").crop(crop_box)


def tensor_from_pil_minus1_1(pil_img: Image.Image) -> torch.Tensor:
    """Match Infinity transform output range without LANCZOS resize (exact pad)."""
    arr = np.asarray(pil_img.convert("RGB"), dtype=np.uint8)
    t = to_tensor(arr)  # [0,1]
    return t.add(t).add_(-1)  # [-1,1]


def encode_stage_a_bit_labels(
    vae: Any,
    stage_a: Image.Image,
    scale_schedule: list[tuple[int, int, int]],
    device: torch.device,
) -> tuple[list[torch.Tensor], tuple[int, int, int, int], Image.Image]:
    """
    Encode padded Stage A through Infinity VAE.

    Returns (all_bit_indices / gt_ls_Bl, crop_box, padded_rgb).
    """
    padded, crop_box = pad_stage_a_to_square(stage_a, TARGET)
    inp = tensor_from_pil_minus1_1(padded).unsqueeze(0).to(device)
    schedule = [(int(t), int(h), int(w)) for (t, h, w) in scale_schedule]
    with torch.no_grad():
        _h, _z, _all_indices, all_bit_indices, _residual, _vin = vae.encode(
            inp, scale_schedule=schedule
        )
    return all_bit_indices, crop_box, padded


def resolve_gt_leak(n_scales: int, gt_leak: int | str) -> int:
    """
    gt_leak: absolute int, or aliases:
      0 / none / pure — free invent
      half — teacher-force first half of scales
      almost — leave last 2 scales free
    """
    if isinstance(gt_leak, str):
        key = gt_leak.strip().lower()
        if key in ("0", "none", "pure"):
            return 0
        if key == "half":
            return max(0, n_scales // 2)
        if key in ("almost", "n-2", "last2"):
            return max(0, n_scales - 2)
        raise ValueError(f"unknown gt_leak alias: {gt_leak!r}")
    leak = int(gt_leak)
    if leak < 0 or leak > n_scales:
        raise ValueError(f"gt_leak={leak} out of range for n_scales={n_scales}")
    return leak


def tensor_bgr_to_pil(img_bgr: torch.Tensor | np.ndarray) -> Image.Image:
    """Infinity gen_one_img returns BGR uint8 HxWx3 (cv2 convention)."""
    if isinstance(img_bgr, torch.Tensor):
        arr = img_bgr.detach().cpu().numpy()
    else:
        arr = np.asarray(img_bgr)
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"expected HxWx3 image, got {arr.shape}")
    rgb = arr[:, :, ::-1].copy()
    return Image.fromarray(rgb, mode="RGB")
