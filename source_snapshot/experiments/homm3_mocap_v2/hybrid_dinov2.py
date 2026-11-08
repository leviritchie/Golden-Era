"""Hybrid DINOv2 keep score: dense image cosine plus occupancy IoU.

This is the weave-search keep authority. It is not the V2 proposal keep.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np

from dino_embed import extract_subject_from_rgba
from paths import WEAVE_KEEP_AUTHORITY

DINO_WEIGHT = 2.0
OCCUPANCY_WEIGHT = 1.0
KEEP_EPS = 1e-4


def occupancy_iou(sprite_alpha: np.ndarray, mesh_alpha: np.ndarray) -> float:
    sprite = np.asarray(sprite_alpha) > 0
    mesh = np.asarray(mesh_alpha) > 0
    if sprite.shape != mesh.shape:
        raise ValueError(f"alpha shapes {sprite.shape} != {mesh.shape}")
    union = int(np.logical_or(sprite, mesh).sum())
    if union <= 0:
        raise ValueError("occupancy union is empty")
    return float(np.logical_and(sprite, mesh).sum() / union)


def window_alpha(rgba: np.ndarray, window: dict[str, Any]) -> np.ndarray:
    x0, y0, x1, y1 = [int(value) for value in window["bboxXyxy"]]
    return np.asarray(rgba[y0:y1, x0:x1, 3], dtype=np.uint8)


def cosine_quality(a: np.ndarray, b: np.ndarray) -> float:
    left = np.asarray(a, dtype=np.float64).reshape(-1)
    right = np.asarray(b, dtype=np.float64).reshape(-1)
    if left.shape != right.shape:
        raise ValueError(f"embedding shapes {left.shape} != {right.shape}")
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom <= 1e-12:
        raise ValueError("hybrid DINOv2 cosine is undefined for a zero embedding")
    cosine = float(np.dot(left, right) / denom)
    return float(np.clip(0.5 * (cosine + 1.0), 0.0, 1.0))


def hybrid_dinov2_score(
    *,
    sprite_embedding: np.ndarray,
    mesh_embedding: np.ndarray,
    sprite_alpha: np.ndarray,
    mesh_alpha: np.ndarray,
) -> dict[str, Any]:
    dino = cosine_quality(sprite_embedding, mesh_embedding)
    occupancy = occupancy_iou(sprite_alpha, mesh_alpha)
    weight_sum = DINO_WEIGHT + OCCUPANCY_WEIGHT
    score = (DINO_WEIGHT * dino + OCCUPANCY_WEIGHT * occupancy) / weight_sum
    return {
        "keepAuthority": WEAVE_KEEP_AUTHORITY,
        "score": float(score),
        "dinoQuality": float(dino),
        "occupancyIou": float(occupancy),
        "dinoWeight": DINO_WEIGHT,
        "occupancyWeight": OCCUPANCY_WEIGHT,
    }


def should_keep(incumbent: dict[str, Any], candidate: dict[str, Any]) -> bool:
    return float(candidate["score"]) > float(incumbent["score"]) + KEEP_EPS


class DinoEncoder:
    def __init__(self, device: str):
        from transformers import AutoImageProcessor, Dinov2Model
        import torch

        if device != "cuda":
            raise ValueError("hybrid DINOv2 scoring requires CUDA")
        self.device = device
        self._torch = torch
        self.processor = AutoImageProcessor.from_pretrained(
            "facebook/dinov2-large",
            do_center_crop=False,
        )
        self.model = Dinov2Model.from_pretrained("facebook/dinov2-large").to(device).eval()

    def encode_rgb(self, images: list[np.ndarray]) -> np.ndarray:
        if not images:
            raise ValueError("no images to encode")
        packed = []
        for image in images:
            frame = np.asarray(image, dtype=np.float32)
            if frame.ndim != 3 or frame.shape[2] != 3:
                raise ValueError(f"RGB image must be HWC, got {frame.shape}")
            packed.append((np.clip(frame, 0.0, 1.0) * 255.0).astype(np.uint8))
        inputs = self.processor(images=packed, return_tensors="pt", do_center_crop=False)
        pixel = inputs["pixel_values"].to(self.device)
        with self._torch.no_grad():
            hidden = self.model(pixel_values=pixel).last_hidden_state
        pooled = hidden.mean(dim=1)
        pooled = self._torch.nn.functional.normalize(pooled, dim=-1)
        return pooled.detach().float().cpu().numpy().astype(np.float32)


def score_mesh_rgba(
    *,
    encoder: DinoEncoder | Callable[[list[np.ndarray]], np.ndarray],
    sprite_embedding: np.ndarray,
    sprite_rgba: np.ndarray,
    mesh_rgba: np.ndarray,
    window: dict[str, Any],
) -> dict[str, Any]:
    subject = extract_subject_from_rgba(mesh_rgba, window)
    if hasattr(encoder, "encode_rgb"):
        mesh_embedding = encoder.encode_rgb([subject])[0]
    else:
        mesh_embedding = encoder([subject])[0]
    return hybrid_dinov2_score(
        sprite_embedding=sprite_embedding,
        mesh_embedding=mesh_embedding,
        sprite_alpha=window_alpha(sprite_rgba, window),
        mesh_alpha=window_alpha(mesh_rgba, window),
    )
