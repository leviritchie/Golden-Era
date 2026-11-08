"""Canonical V2 artifact and Blender parity boundary."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image

from .contracts import ExperimentResult, PoseState


def pose_state_json(pose: PoseState) -> dict[str, Any]:
    def values(value: Any) -> Any:
        return value.detach().cpu().tolist() if hasattr(value, "detach") else value

    return {
        "registration": values(pose.registration),
        "motionTranslation": values(pose.motion_translation),
        "motionRotation": values(pose.motion_rotation),
        "boneRotation": values(pose.bone_rotation),
        "frameIndices": list(pose.frame_indices),
        "rotationRepresentation": "axis_angle_radians_glTF_world_axes",
        "rootRepresentation": "camera_basis_registration_then_motion",
    }


def write_canonical_result(result: ExperimentResult, path: str | Path) -> Path:
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = result.to_jsonable()
    payload["canonicalPose"] = pose_state_json(result.selected.pose)
    destination.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return destination


def compare_alpha_masks(gpu_masks: Any, blender_paths: Sequence[str | Path], *, threshold: int = 8) -> dict[str, Any]:
    """Compare exact GPU alpha with final Blender renders after export."""
    gpu = np.asarray(gpu_masks, dtype=np.float32)
    if gpu.ndim != 3:
        raise ValueError("gpu_masks must have shape [frames,height,width]")
    if len(blender_paths) != gpu.shape[0]:
        raise ValueError("GPU and Blender frame counts differ")
    rows = []
    for index, path_value in enumerate(blender_paths):
        path = Path(path_value)
        if not path.is_file():
            raise FileNotFoundError(f"Blender parity render is missing: {path}")
        with Image.open(path) as image:
            rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        alpha = (rgba[..., 3] >= int(threshold)).astype(np.float32)
        if alpha.shape != gpu[index].shape:
            alpha = np.asarray(Image.fromarray((alpha * 255).astype(np.uint8)).resize((gpu.shape[2], gpu.shape[1]), Image.Resampling.NEAREST), dtype=np.float32) / 255.0
        target = gpu[index] > 0.5
        candidate = alpha > 0.5
        intersection = np.logical_and(target, candidate).sum()
        union = np.logical_or(target, candidate).sum()
        ys, xs = np.where(target)
        yc, xc = np.where(candidate)
        center_error = 0.0
        if len(xs) and len(xc):
            center_error = float(np.linalg.norm(np.asarray([xs.mean(), ys.mean()]) - np.asarray([xc.mean(), yc.mean()])))
        rows.append({"frame": index, "iou": float(intersection / max(union, 1)), "centerErrorPx": center_error})
    mean_iou = float(np.mean([row["iou"] for row in rows])) if rows else 0.0
    min_iou = float(min((row["iou"] for row in rows), default=0.0))
    result = {
        "ok": mean_iou >= 0.98 and min_iou >= 0.95 and all(row["centerErrorPx"] < 1.0 for row in rows),
        "meanIoU": mean_iou,
        "minIoU": min_iou,
        "frames": rows,
        "thresholds": {"meanIoU": 0.98, "minIoU": 0.95, "centerErrorPx": 1.0},
    }
    return result


def compare_preview_frames(
    baseline_paths: Sequence[str | Path],
    v2_paths: Sequence[str | Path],
    output_dir: str | Path,
    *,
    duration_ms: int = 180,
) -> dict[str, Any]:
    """Create an inspection-only side-by-side comparison of two previews.

    This deliberately does not claim numerical parity: the frozen baseline
    may be a legacy composite, while V2's preview is a four-panel exact-GPU
    diagnostic.  The artifact is for direct user review and keeps the source
    paths and frame counts visible.
    """
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    left = [Path(value).resolve() for value in baseline_paths]
    right = [Path(value).resolve() for value in v2_paths]
    if not left or not right:
        raise ValueError("both preview sequences must contain at least one image")
    if any(not value.is_file() for value in (*left, *right)):
        missing = [str(value) for value in (*left, *right) if not value.is_file()]
        raise FileNotFoundError(f"preview comparison images are missing: {missing}")
    frame_count = max(len(left), len(right))
    composite_paths: list[Path] = []
    for index in range(frame_count):
        with Image.open(left[min(index, len(left) - 1)]).convert("RGB") as first, Image.open(right[min(index, len(right) - 1)]).convert("RGB") as second:
            height = max(first.height, second.height)
            first_width = max(1, round(first.width * height / first.height))
            second_width = max(1, round(second.width * height / second.height))
            first = first.resize((first_width, height), Image.Resampling.LANCZOS)
            second = second.resize((second_width, height), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (first.width + second.width, height), "black")
            canvas.paste(first, (0, 0))
            canvas.paste(second, (first.width, 0))
            path = destination / f"compare_{index:04d}.png"
            canvas.save(path)
            composite_paths.append(path)
    gif = destination / "baseline_vs_v2.gif"
    images = [Image.open(path).convert("RGB") for path in composite_paths]
    try:
        images[0].save(gif, save_all=True, append_images=images[1:], duration=int(duration_ms), loop=0)
    finally:
        for image in images:
            image.close()
    report = {
        "schemaVersion": 2,
        "comparison": "inspection_only",
        "baselinePaths": [str(value) for value in left],
        "v2Paths": [str(value) for value in right],
        "frameCount": frame_count,
        "gif": str(gif),
    }
    report_path = destination / "baseline_vs_v2.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["report"] = str(report_path)
    return report
