"""DINOv2-Large embeddings for authentic sprite frames.

Default diagnosis/baseline crop is one clip-locked subject window (union alpha
AABB, square pad, white). Experiment A can switch to vendor per-frame
`prepare_image` without changing the output camera. RMBG stays off while plates
have usable alpha.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

PADDING_RATIO = 0.1
DINO_BG = (1.0, 1.0, 1.0)
VENDOR_PREPROCESS = "vendor_per_frame_prepare_image"
CLIP_UNION_PREPROCESS = "clip_locked_union_alpha_aabb"


def load_fixed_canvas_rgba(path: Path, *, canvas: tuple[int, int] | None = None) -> np.ndarray:
    image = Image.open(path).convert("RGBA")
    if canvas is not None and image.size != canvas:
        raise ValueError(f"{path} is {image.size}, expected canvas {canvas}")
    return np.asarray(image, dtype=np.uint8)


def load_fixed_canvas_rgb(path: Path, *, canvas: tuple[int, int] | None = None) -> np.ndarray:
    rgba = load_fixed_canvas_rgba(path, canvas=canvas).astype(np.float32) / 255.0
    alpha = rgba[..., 3:4]
    rgb = rgba[..., :3] * alpha + (1.0 - alpha) * 0.5
    return np.clip(rgb, 0.0, 1.0)


def alpha_bbox(rgba: np.ndarray) -> tuple[int, int, int, int]:
    alpha = rgba[..., 3]
    rows, cols = np.where(alpha > 0)
    if rows.size == 0 or cols.size == 0:
        raise ValueError("frame has no opaque pixels")
    return int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1


def union_alpha_bbox(paths: list[Path], *, canvas: tuple[int, int]) -> tuple[int, int, int, int]:
    if not paths:
        raise ValueError("no frames for subject window")
    x0 = canvas[0]
    y0 = canvas[1]
    x1 = 0
    y1 = 0
    for path in paths:
        left, top, right, bottom = alpha_bbox(load_fixed_canvas_rgba(path, canvas=canvas))
        x0 = min(x0, left)
        y0 = min(y0, top)
        x1 = max(x1, right)
        y1 = max(y1, bottom)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("union subject bbox is empty")
    return x0, y0, x1, y1


def clip_locked_subject_window(
    paths: list[Path],
    *,
    canvas: tuple[int, int],
    padding_ratio: float = PADDING_RATIO,
) -> dict[str, Any]:
    x0, y0, x1, y1 = union_alpha_bbox(paths, canvas=canvas)
    width = x1 - x0
    height = y1 - y0
    return {
        "policy": "clip_locked_union_alpha_aabb",
        "paddingRatio": float(padding_ratio),
        "bg": list(DINO_BG),
        "bboxXyxy": [x0, y0, x1, y1],
        "bboxWh": [width, height],
        "canvas": [int(canvas[0]), int(canvas[1])],
        "rmbg": False,
        "perFrameCrop": False,
    }


def extract_subject_rgb(path: Path, window: dict[str, Any], *, canvas: tuple[int, int]) -> np.ndarray:
    rgba = load_fixed_canvas_rgba(path, canvas=canvas).astype(np.float32) / 255.0
    x0, y0, x1, y1 = [int(value) for value in window["bboxXyxy"]]
    crop = rgba[y0:y1, x0:x1]
    if crop.size == 0:
        raise ValueError(f"{path} crop is empty for window {window['bboxXyxy']}")
    alpha = crop[..., 3:4]
    bg = np.asarray(window["bg"], dtype=np.float32).reshape(1, 1, 3)
    rgb = crop[..., :3] * alpha + (1.0 - alpha) * bg
    height, width = rgb.shape[:2]
    padding_ratio = float(window["paddingRatio"])
    inner = max(width, height)
    if inner < 1:
        raise ValueError("subject crop has no size")
    pad_x0 = (inner - width) // 2
    pad_x1 = inner - width - pad_x0
    pad_y0 = (inner - height) // 2
    pad_y1 = inner - height - pad_y0
    margin = max(1, int(round(inner * padding_ratio)))
    bg0 = float(np.asarray(window["bg"], dtype=np.float32).reshape(-1)[0])
    padded = np.pad(
        rgb,
        ((pad_y0 + margin, pad_y1 + margin), (pad_x0 + margin, pad_x1 + margin), (0, 0)),
        mode="constant",
        constant_values=bg0,
    )
    if padded.shape[0] != padded.shape[1]:
        raise ValueError(f"subject pad is not square: {padded.shape}")
    return np.clip(padded, 0.0, 1.0)


def extract_subject_from_rgba(rgba: np.ndarray, window: dict[str, Any]) -> np.ndarray:
    canvas = tuple(int(value) for value in window["canvas"])
    if rgba.shape[0] != canvas[1] or rgba.shape[1] != canvas[0] or rgba.shape[2] != 4:
        raise ValueError(f"rgba canvas {rgba.shape} does not match window canvas {canvas}")
    x0, y0, x1, y1 = [int(value) for value in window["bboxXyxy"]]
    crop = rgba[y0:y1, x0:x1].astype(np.float32) / 255.0
    if crop.size == 0:
        raise ValueError(f"rgba crop is empty for window {window['bboxXyxy']}")
    alpha = crop[..., 3:4]
    bg = np.asarray(window["bg"], dtype=np.float32).reshape(1, 1, 3)
    rgb = crop[..., :3] * alpha + (1.0 - alpha) * bg
    height, width = rgb.shape[:2]
    padding_ratio = float(window["paddingRatio"])
    inner = max(width, height)
    if inner < 1:
        raise ValueError("subject crop has no size")
    pad_x0 = (inner - width) // 2
    pad_x1 = inner - width - pad_x0
    pad_y0 = (inner - height) // 2
    pad_y1 = inner - height - pad_y0
    margin = max(1, int(round(inner * padding_ratio)))
    bg0 = float(np.asarray(window["bg"], dtype=np.float32).reshape(-1)[0])
    padded = np.pad(
        rgb,
        ((pad_y0 + margin, pad_y1 + margin), (pad_x0 + margin, pad_x1 + margin), (0, 0)),
        mode="constant",
        constant_values=bg0,
    )
    if padded.shape[0] != padded.shape[1]:
        raise ValueError(f"subject pad is not square: {padded.shape}")
    return np.clip(padded, 0.0, 1.0)


def write_subject_preview(path: Path, window: dict[str, Any], *, canvas: tuple[int, int], dest: Path) -> Path:
    rgb = (extract_subject_rgb(path, window, canvas=canvas) * 255.0).astype(np.uint8)
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, mode="RGB").save(dest)
    return dest


def vendor_per_frame_prepare_rgb(
    path: Path,
    *,
    padding_ratio: float = PADDING_RATIO,
    bg: tuple[float, float, float] = DINO_BG,
) -> np.ndarray:
    """Match vendor `load_image` alpha path: per-frame bbox, white composite, square pad.

    Requires a real alpha channel (some transparent pixels and some opaque pixels).
    Vendor's 1% histogram can send a sparse but valid silhouette to RMBG; this
    diagnosis path still uses the alpha bbox and does not run RMBG. It does not
    change the output camera.
    """
    image = Image.open(path).convert("RGBA")
    width, height = image.size
    if height > width:
        scale = 2000 / height
    else:
        scale = 2000 / width
    if scale < 1:
        image = image.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.BILINEAR,
        )
    rgba = np.asarray(image, dtype=np.uint8)
    alpha = rgba[..., 3]
    has_transparent = bool(np.any(alpha == 0))
    has_opaque = bool(np.any(alpha > 0))
    if not has_transparent or not has_opaque:
        if not os.environ.get("HOMM3_ACCEPT_EMPTY_ALPHA"):
            raise ValueError(f"{path} has no usable alpha for vendor per-frame preprocess")
        rgba = np.array(rgba, copy=True)
        if not has_transparent:
            rgba[0, 0, 3] = 0
        if not has_opaque:
            rgba[0, 0, :] = (0, 0, 0, 255)
        alpha = rgba[..., 3]
    rows, cols = np.where(alpha > 0)
    if rows.size == 0 or cols.size == 0:
        raise ValueError(f"{path} alpha bbox is empty")
    x0 = int(cols.min())
    y0 = int(rows.min())
    box_w = int(cols.max() - cols.min() + 1)
    box_h = int(rows.max() - rows.min() + 1)
    rgb = rgba[..., :3].astype(np.float32) / 255.0
    alpha_f = (alpha.astype(np.float32) / 255.0)[..., None]
    bg_arr = np.asarray(bg, dtype=np.float32).reshape(1, 1, 3)
    composited = rgb * alpha_f + bg_arr * (1.0 - alpha_f)
    crop = composited[y0 : y0 + box_h, x0 : x0 + box_w]
    if box_w > box_h:
        pad_x = int(box_w * padding_ratio)
        pad_y = int(pad_x + (box_w - box_h) / 2)
    else:
        pad_y = int(box_h * padding_ratio)
        pad_x = int(pad_y + (box_h - box_w) / 2)
    bg0 = float(np.asarray(bg, dtype=np.float32).reshape(-1)[0])
    padded = np.pad(
        crop,
        ((pad_y, pad_y), (pad_x, pad_x), (0, 0)),
        mode="constant",
        constant_values=bg0,
    )
    height, width = padded.shape[:2]
    if abs(height - width) == 1:
        extra_y = 0 if height >= width else 1
        extra_x = 0 if width >= height else 1
        padded = np.pad(
            padded,
            ((0, extra_y), (0, extra_x), (0, 0)),
            mode="constant",
            constant_values=bg0,
        )
    if padded.shape[0] != padded.shape[1]:
        raise ValueError(f"vendor pad is not square: {padded.shape}")
    return np.clip(padded, 0.0, 1.0)


def write_encoder_input_preview(rgb: np.ndarray, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((np.clip(rgb, 0.0, 1.0) * 255.0).astype(np.uint8), mode="RGB").save(dest)
    return dest


def encode_rgb_frames(
    images: list[np.ndarray],
    *,
    device: str,
    do_center_crop: bool,
    model_dtype: str = "float32",
) -> tuple[np.ndarray, np.ndarray]:
    from transformers import AutoImageProcessor, Dinov2Model
    import torch

    if not images:
        raise ValueError("no images to encode")
    processor_kwargs = {}
    encode_kwargs = {}
    if not do_center_crop:
        processor_kwargs["do_center_crop"] = False
        encode_kwargs["do_center_crop"] = False
    processor = AutoImageProcessor.from_pretrained("facebook/dinov2-large", **processor_kwargs)
    torch_dtype = torch.float16 if model_dtype == "float16" else torch.float32
    model = Dinov2Model.from_pretrained("facebook/dinov2-large").to(device, dtype=torch_dtype).eval()
    pil_uint8 = [(np.clip(frame, 0.0, 1.0) * 255.0).astype(np.uint8) for frame in images]
    inputs = processor(images=pil_uint8, return_tensors="pt", **encode_kwargs)
    pixel = inputs["pixel_values"].to(device, dtype=torch_dtype)
    with torch.no_grad():
        hidden = model(pixel_values=pixel).last_hidden_state
    embeds = hidden.detach().float().cpu().numpy().astype(np.float32)
    pixels = pixel.detach().float().cpu().numpy().astype(np.float32)
    return embeds, pixels


def encode_frames(
    paths: list[Path],
    *,
    device: str,
    canvas: tuple[int, int],
    window: dict[str, Any],
    preprocess_policy: str = CLIP_UNION_PREPROCESS,
    do_center_crop: bool = False,
    dino_dtype: str = "float32",
    encoder_input_dir: Path | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    if preprocess_policy == CLIP_UNION_PREPROCESS:
        images = [extract_subject_rgb(path, window, canvas=canvas) for path in paths]
    elif preprocess_policy == VENDOR_PREPROCESS:
        images = [vendor_per_frame_prepare_rgb(path) for path in paths]
    else:
        raise ValueError(f"unknown preprocess policy {preprocess_policy!r}")
    if encoder_input_dir is not None:
        encoder_input_dir.mkdir(parents=True, exist_ok=True)
        pick = {0, len(images) // 2, len(images) - 1}
        for index in sorted(pick):
            write_encoder_input_preview(
                images[index],
                encoder_input_dir / f"{preprocess_policy}_f{index:02d}.png",
            )
    embeds, pixels = encode_rgb_frames(
        images,
        device=device,
        do_center_crop=do_center_crop,
        model_dtype=dino_dtype,
    )
    meta = {
        "preprocessPolicy": preprocess_policy,
        "doCenterCrop": bool(do_center_crop),
        "dinoDtype": dino_dtype,
        "preparedShapes": [list(frame.shape) for frame in images],
        "pixelValuesShape": list(pixels.shape),
        "pixelValuesMean": float(pixels.mean()),
        "pixelValuesStd": float(pixels.std()),
    }
    return embeds, meta
