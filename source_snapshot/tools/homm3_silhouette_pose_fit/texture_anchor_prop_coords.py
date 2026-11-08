#!/usr/bin/env python3
"""Snap prop tip targets to DEF sprite chroma/texture near articulation centroids."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
from PIL import Image, ImageDraw

from articulation_prop_coords import (
    articulation_to_props_coords,
    bind_tip_screen_xy,
    map_parts_by_bind_tip_proximity,
)

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
ALPHA_THRESHOLD = 8

# Optional HSV gates (OpenCV H: 0-180). Cheap roc flyer hints.
JOINT_HSV_HINTS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "HeadTip": ((10, 90, 120), (40, 255, 255)),
    "WingTipA": ((5, 40, 40), (25, 255, 220)),
    "WingTipB": ((5, 40, 40), (25, 255, 220)),
}


def _load_rgba(path: Path) -> tuple[np.ndarray, np.ndarray]:
    rgba = np.asarray(Image.open(path).convert("RGBA"))
    return rgba[..., :3], rgba[..., 3]


def _lab_ab_patch_median(rgb: np.ndarray, x: float, y: float, half: int) -> np.ndarray:
    h, w = rgb.shape[:2]
    xi = int(round(x))
    yi = int(round(y))
    x0 = max(0, xi - half)
    x1 = min(w, xi + half + 1)
    y0 = max(0, yi - half)
    y1 = min(h, yi + half + 1)
    patch = rgb[y0:y1, x0:x1]
    lab = cv2.cvtColor(patch, cv2.COLOR_RGB2LAB).astype(np.float32)
    return lab[:, :, 1:3].mean(axis=(0, 1))


def _hsv_mask(rgb: np.ndarray, lo: tuple[int, int, int], hi: tuple[int, int, int]) -> np.ndarray:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    lower = np.asarray(lo, dtype=np.uint8)
    upper = np.asarray(hi, dtype=np.uint8)
    return cv2.inRange(hsv, lower, upper) > 0


def snap_tip_chroma(
    rgb: np.ndarray,
    alpha: np.ndarray,
    *,
    seed_xy: tuple[float, float],
    center_xy: tuple[float, float],
    patch_half: int = 6,
    search_radius: int = 40,
    hsv_hint: tuple[tuple[int, int, int], tuple[int, int, int]] | None = None,
) -> tuple[float, float, float]:
    """Return snapped (x, y) and chroma distance score (lower is better)."""
    target_ab = _lab_ab_patch_median(rgb, seed_xy[0], seed_xy[1], patch_half)
    h, w = rgb.shape[:2]
    cx = int(round(center_xy[0]))
    cy = int(round(center_xy[1]))
    r = int(search_radius)
    x0 = max(0, cx - r)
    x1 = min(w, cx + r + 1)
    y0 = max(0, cy - r)
    y1 = min(h, cy + r + 1)
    roi_rgb = rgb[y0:y1, x0:x1]
    roi_alpha = alpha[y0:y1, x0:x1] >= ALPHA_THRESHOLD
    lab = cv2.cvtColor(roi_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    dist = np.linalg.norm(lab[:, :, 1:3] - target_ab.reshape(1, 1, 2), axis=2)
    valid = roi_alpha
    if hsv_hint is not None:
        color_ok = _hsv_mask(roi_rgb, hsv_hint[0], hsv_hint[1])
        valid = valid & color_ok
    dist[~valid] = np.inf
    if not np.isfinite(dist).any():
        return float(center_xy[0]), float(center_xy[1]), float("inf")
    flat = int(np.argmin(dist))
    oy, ox = np.unravel_index(flat, dist.shape)
    score = float(dist[oy, ox])
    return float(x0 + ox), float(y0 + oy), score


def texture_anchor_props_coords(
    centroid_coords: dict[str, Any],
    *,
    unit: str,
    clip: str,
    frame_dir: Path,
    frame_indices: list[int],
    prop_joints: list[str],
    bone_roles_path: Path,
    patch_half: int = 6,
    search_radius: int = 40,
) -> dict[str, Any]:
    seed_xy = bind_tip_screen_xy(
        unit=unit,
        clip=clip,
        frame_dir=frame_dir,
        frame_index=int(frame_indices[0]),
        prop_joints=prop_joints,
        bone_roles_path=bone_roles_path,
    )
    centroid_by_frame = {
        int(entry["frameIndex"]): entry["xy"] for entry in centroid_coords.get("frames") or ()
    }
    frames_out: list[dict[str, Any]] = []
    snap_scores: list[dict[str, Any]] = []
    for frame_num in frame_indices:
        path = frame_dir / f"{int(frame_num):02d}.png"
        if not path.is_file():
            path = frame_dir / f"{int(frame_num)}.png"
        rgb, alpha = _load_rgba(path)
        base_xy = centroid_by_frame[int(frame_num)]
        xy: dict[str, list[int]] = {}
        frame_scores: dict[str, float] = {}
        for joint_name in prop_joints:
            hint = JOINT_HSV_HINTS.get(str(joint_name))
            cx, cy = base_xy[str(joint_name)]
            sx, sy, score = snap_tip_chroma(
                rgb,
                alpha,
                seed_xy=seed_xy[str(joint_name)],
                center_xy=(float(cx), float(cy)),
                patch_half=int(patch_half),
                search_radius=int(search_radius),
                hsv_hint=hint,
            )
            xy[str(joint_name)] = [int(round(sx)), int(round(sy))]
            frame_scores[str(joint_name)] = round(score, 3)
        frames_out.append({"frameIndex": int(frame_num), "xy": xy})
        snap_scores.append({"frameIndex": int(frame_num), "chromaDist": frame_scores})
    return {
        **dict(centroid_coords),
        "edgeSet": "def_texture_chroma_anchor",
        "notes": (
            "Chroma snap: Lab-ab patch from bind tip frame 0, search near articulation centroid; "
            f"patch_half={patch_half} search_radius={search_radius}"
        ),
        "textureAnchor": {
            "seedFrame0Tips": {k: [round(v[0], 1), round(v[1], 1)] for k, v in seed_xy.items()},
            "hsvHints": {k: list(v) for k, v in JOINT_HSV_HINTS.items()},
            "snapScores": snap_scores,
        },
        "frames": frames_out,
    }


def draw_marker_overlay(
    frame_dir: Path,
    frame_index: int,
    *,
    centroid_xy: dict[str, Sequence[int]],
    texture_xy: dict[str, Sequence[int]],
    out_path: Path,
) -> None:
    path = frame_dir / f"{int(frame_index):02d}.png"
    if not path.is_file():
        path = frame_dir / f"{int(frame_index)}.png"
    base = Image.open(path).convert("RGBA")
    w, h = base.size
    panel = Image.new("RGBA", (w * 3, h), (24, 24, 24, 255))
    sprite = base.copy()
    centroid = base.copy()
    texture = base.copy()
    colors = {
        "HeadTip": (255, 220, 40),
        "TailTip": (180, 120, 255),
        "WingTipA": (80, 220, 255),
        "WingTipB": (255, 120, 80),
    }

    def _mark(im: Image.Image, points: dict[str, Sequence[int]]) -> None:
        draw = ImageDraw.Draw(im)
        for name, (x, y) in points.items():
            c = colors.get(str(name), (255, 255, 255))
            r = 10
            draw.ellipse((x - r, y - r, x + r, y + r), outline=c + (255,), width=3)
            draw.text((x + 12, y - 8), str(name), fill=c + (255,))

    _mark(sprite, texture_xy)
    _mark(centroid, centroid_xy)
    _mark(texture, texture_xy)
    draw = ImageDraw.Draw(texture)
    for name in centroid_xy:
        x0, y0 = centroid_xy[name]
        x1, y1 = texture_xy[name]
        draw.line((x0, y0, x1, y1), fill=(255, 255, 255, 180), width=2)

    panel.paste(sprite, (0, 0))
    panel.paste(centroid, (w, 0))
    panel.paste(texture, (w * 2, 0))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    panel.convert("RGB").save(out_path)
