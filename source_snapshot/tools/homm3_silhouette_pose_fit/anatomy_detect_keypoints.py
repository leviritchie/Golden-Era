"""Derive per-frame 2D stick targets from local anatomical box detection.

Grounding DINO runs on each target sprite frame. Detected head box centers become
sparse IK goals for neck/head chains during cascade anatomy head pin.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image

from roc_anatomical_boxes import PartBox, RocAnatomicalBoxDetector, best_by_part


def box_center(box: tuple[float, float, float, float]) -> tuple[float, float]:
    x0, y0, x1, y1 = (float(v) for v in box)
    return (0.5 * (x0 + x1), 0.5 * (y0 + y1))


def detect_part_centers_on_image(
    image: Image.Image,
    *,
    parts: Sequence[str],
    depth: Image.Image | np.ndarray | None = None,
    detector: RocAnatomicalBoxDetector | None = None,
) -> dict[str, tuple[float, float]]:
    """Return part name → (x, y) center for each requested part found on ``image``."""
    if not parts:
        raise ValueError("parts must be non-empty")
    active = detector or RocAnatomicalBoxDetector()
    rgba = image.convert("RGBA")
    depth_ref = depth
    if depth_ref is None:
        depth_ref = rgba
    boxes = active.detect(
        rgba,
        allowed_parts=tuple(parts),
        laterality_enabled=False,
        laterality_depth=depth_ref,
    )
    by_part = best_by_part(boxes)
    out: dict[str, tuple[float, float]] = {}
    for part in parts:
        key = str(part)
        item = by_part.get(key)
        if item is None:
            continue
        out[key] = box_center(item.box)
    return out


def build_anatomy_keypoints_payload(
    *,
    frame_indices: Sequence[int],
    target_paths: Sequence[str | Path],
    target_depth_paths: Sequence[str | Path] | None = None,
    parts: Sequence[str] = ("head",),
    detector: RocAnatomicalBoxDetector | None = None,
) -> dict[str, Any]:
    """Build keypoints.json-shaped payload from sprite paths aligned to clip frames."""
    frames: list[dict[str, Any]] = []
    missing: list[int] = []
    active_detector = detector or RocAnatomicalBoxDetector()
    for position, frame_index in enumerate(frame_indices):
        path = Path(target_paths[int(position)])
        if not path.is_file():
            raise FileNotFoundError(f"anatomy detect target frame is missing: {path}")
        depth_path = None
        if target_depth_paths is not None and int(position) < len(target_depth_paths):
            depth_path = Path(target_depth_paths[int(position)])
        depth_img = None
        if depth_path is not None and depth_path.is_file():
            depth_img = Image.open(depth_path)
        with Image.open(path) as sprite:
            centers = detect_part_centers_on_image(
                sprite,
                parts=parts,
                depth=depth_img,
                detector=active_detector,
            )
        joints: dict[str, Any] = {}
        for part, (x, y) in centers.items():
            joints[str(part)] = {
                "x": float(x),
                "y": float(y),
                "visible": True,
            }
        if not joints:
            missing.append(int(frame_index))
            continue
        frames.append({"frameIndex": int(frame_index), "joints": joints})
    return {
        "method": "anatomy_box_detection",
        "parts": [str(part) for part in parts],
        "frames": frames,
        "missingFrameIndices": missing,
    }


def anatomy_keypoints_by_frame_index(payload: Mapping[str, Any]) -> dict[int, dict[str, tuple[float, float]]]:
    """Convert payload to frameIndex → joint → (x, y) like ``load_ik_keypoints``."""
    out: dict[int, dict[str, tuple[float, float]]] = {}
    for frame in payload.get("frames", []):
        frame_index = int(frame["frameIndex"])
        joints: dict[str, tuple[float, float]] = {}
        for name, entry in (frame.get("joints") or {}).items():
            if not entry.get("visible", False):
                continue
            joints[str(name)] = (float(entry["x"]), float(entry["y"]))
        out[frame_index] = joints
    return out


def write_anatomy_keypoints(path: Path, payload: Mapping[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
