"""Register one fixed Y-up camera for the fixed-motion skin pilot.

The historical Roc camera artifact was measured in a different Z-up job
camera space and fails against the current frozen Y-up skin.  It is therefore
not an orientation authority here.  This module performs a bounded, idle-only
orthographic registration in the current glTF Y-up space, then freezes the
    result for all frames and all weight candidates.  Because generated meshes do
not share a reliable front-facing convention, both azimuth parities are scored
against the idle alpha instead of assuming that +Z is the visible front.

Only camera scale and 2-D offset are fitted after each bounded yaw/pitch
hypothesis.  No joint motion, per-frame camera fit, or weight-dependent camera
fit is allowed.
"""
from __future__ import annotations

from typing import Any

import numpy as np


MIN_REGISTERED_IOU = 0.60
COARSE_YAWS_DEG = tuple(range(0, 360, 20))
COARSE_PITCHES_DEG = tuple(range(0, 41, 10))
REFINE_STEP_DEG = 5.0
REFINE_SCALE_FACTORS = (0.97, 1.0, 1.03)
REFINE_OFFSET_FACTORS = (-0.02, 0.0, 0.02)


class CameraRegistrationError(ValueError):
    """Raised when no bounded current-space camera registers idle sufficiently."""

    def __init__(self, message: str, report: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.report = report or {}


def _finite_array(value: Any, *, name: str, shape: tuple[int, ...] | None = None) -> np.ndarray:
    detach = getattr(value, "detach", None)
    if callable(detach):
        value = detach()
    cpu = getattr(value, "cpu", None)
    if callable(cpu):
        value = cpu()
    numpy = getattr(value, "numpy", None)
    if callable(numpy):
        value = numpy()
    array = np.asarray(value, dtype=np.float64)
    if shape is not None and array.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, got {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} contains non-finite values")
    return array


def _torch_or_numpy(value: Any) -> np.ndarray:
    detach = getattr(value, "detach", None)
    if callable(detach):
        value = detach()
    cpu = getattr(value, "cpu", None)
    if callable(cpu):
        value = cpu()
    numpy = getattr(value, "numpy", None)
    if callable(numpy):
        value = numpy()
    return np.asarray(value, dtype=np.float64)


def _validate_inputs(
    *,
    vertices: np.ndarray,
    target_rgb: Any,
    target_alpha: Any,
    target_distance: Any,
    resolution: int,
    source_crop: dict[str, Any],
    source_size: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray, tuple[int, int], dict[str, int]]:
    if int(resolution) < 2:
        raise ValueError("resolution must be at least 2")
    vertices = _finite_array(vertices, name="vertices")
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not len(vertices):
        raise ValueError(f"vertices must be [V,3] and non-empty, got {vertices.shape}")
    rgb = _finite_array(target_rgb, name="target_rgb")
    alpha = _finite_array(target_alpha, name="target_alpha")
    distance = _finite_array(target_distance, name="target_distance")
    expected = (1, int(resolution), int(resolution))
    if rgb.shape != (*expected, 3):
        raise ValueError(f"target_rgb must have shape {(*expected, 3)}, got {rgb.shape}")
    if alpha.shape != (*expected, 1):
        raise ValueError(f"target_alpha must have shape {(*expected, 1)}, got {alpha.shape}")
    if distance.shape != expected:
        raise ValueError(f"target_distance must have shape {expected}, got {distance.shape}")
    if len(source_size) != 2:
        raise ValueError(f"source_size must be (width,height), got {source_size}")
    source_size = (int(source_size[0]), int(source_size[1]))
    if min(source_size) <= 0:
        raise ValueError(f"source_size must be positive, got {source_size}")
    required = ("left", "top", "size")
    if any(key not in source_crop for key in required):
        raise ValueError(f"source_crop must contain {required}")
    crop = {key: int(source_crop[key]) for key in required}
    if crop["size"] <= 0:
        raise ValueError(f"source_crop is invalid: {crop}")
    in_canvas = crop["left"] >= 0 and crop["top"] >= 0 and crop["left"] + crop["size"] <= source_size[0] and crop["top"] + crop["size"] <= source_size[1]
    canonical_size = max(source_size)
    canonical = (crop["size"] == canonical_size and
                 crop["left"] == -((canonical_size - source_size[0]) // 2) and
                 crop["top"] == -((canonical_size - source_size[1]) // 2))
    if not in_canvas and not canonical:
        raise ValueError(f"source_crop lies outside source_size: {crop} / {source_size}")
    target = np.clip(alpha[0, ..., 0], 0.0, 1.0)
    if not np.any(target > 0.0):
        raise ValueError("target_alpha has no foreground pixels")
    return vertices, target, source_size, crop


def _basis_yup(yaw_deg: float, pitch_deg: float) -> np.ndarray:
    yaw = np.deg2rad(float(yaw_deg))
    pitch = np.deg2rad(float(pitch_deg))
    right = np.asarray((np.cos(yaw), 0.0, np.sin(yaw)), dtype=np.float64)
    down = np.asarray(
        (-np.sin(pitch) * np.sin(yaw), -np.cos(pitch), np.sin(pitch) * np.cos(yaw)),
        dtype=np.float64,
    )
    forward = np.cross(right, down)
    forward /= max(float(np.linalg.norm(forward)), 1e-12)
    return np.stack((right, down, forward), axis=0)


def _target_bbox(target: np.ndarray) -> tuple[float, float, float, float]:
    ys, xs = np.where(np.asarray(target) > 0.0)
    if not len(xs):
        raise ValueError("target alpha has no foreground pixels")
    return float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())


def _bbox_scale_offset(
    vertices: np.ndarray,
    basis: np.ndarray,
    target_bbox: tuple[float, float, float, float],
) -> tuple[float, np.ndarray]:
    projected = np.asarray(vertices, dtype=np.float64) @ np.asarray(basis[:2], dtype=np.float64).T
    x0, y0, x1, y1 = target_bbox
    target_span = np.asarray((max(1.0, x1 - x0), max(1.0, y1 - y0)), dtype=np.float64)
    mesh_span = np.maximum(np.ptp(projected, axis=0), 1e-12)
    scale = float(np.min(target_span / mesh_span))
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("camera bbox scale is not finite and positive")
    target_center = np.asarray((0.5 * (x0 + x1), 0.5 * (y0 + y1)), dtype=np.float64)
    offset = target_center - scale * projected.mean(axis=0)
    if not np.isfinite(offset).all():
        raise ValueError("camera bbox offset is non-finite")
    return scale, offset


def _camera(
    basis: np.ndarray,
    *,
    scale: float,
    offset: np.ndarray,
    vertices: np.ndarray,
    source_size: tuple[int, int],
    source_crop: dict[str, int],
    resolution: int,
    yaw_deg: float,
    pitch_deg: float,
) -> dict[str, Any]:
    right, down, forward = np.asarray(basis, dtype=np.float64)
    depths = np.asarray(vertices, dtype=np.float64) @ forward
    depth_min = float(np.min(depths))
    depth_max = float(np.max(depths))
    depth_span = max(depth_max - depth_min, 1e-6)
    return {
        "right": right.copy(),
        "down": down.copy(),
        "forward": forward.copy(),
        "up": (-down).copy(),
        "scale": float(scale),
        "offset": np.asarray(offset, dtype=np.float64).copy(),
        "depth_center": 0.5 * (depth_min + depth_max),
        "depth_span": depth_span,
        "basisScreenRows": np.stack((right, down), axis=0).tolist(),
        "pxPerWorld": float(scale),
        "screenOffsetPx": np.asarray(offset, dtype=np.float64).tolist(),
        "yawDeg": float(yaw_deg),
        "pitchDeg": float(pitch_deg),
        "sourceSize": [int(source_size[0]), int(source_size[1])],
        "sourceCrop": dict(source_crop),
        "resolution": int(resolution),
    }


def _render_alpha(renderer: Any, vertices: np.ndarray, *, resolution: int) -> np.ndarray:
    return _render_images(renderer, vertices, resolution=resolution)[1]


def _render_images(renderer: Any, vertices: np.ndarray, *, resolution: int) -> tuple[np.ndarray, np.ndarray]:
    result = renderer.render(np.asarray(vertices, dtype=np.float64)[None, ...])
    if not isinstance(result, tuple) or len(result) != 2:
        raise TypeError("camera registration renderer.render must return (rgb, alpha)")
    rgb = _torch_or_numpy(result[0])
    alpha = _torch_or_numpy(result[1])
    if rgb.shape != (1, resolution, resolution, 3):
        raise ValueError(
            f"renderer RGB must have shape (1,{resolution},{resolution},3), got {rgb.shape}"
        )
    if alpha.shape != (1, resolution, resolution, 1):
        raise ValueError(
            f"renderer alpha must have shape (1,{resolution},{resolution},1), got {alpha.shape}"
        )
    return rgb[0], np.clip(alpha[0, ..., 0], 0.0, 1.0)


def _alpha_metrics(predicted: np.ndarray, target: np.ndarray) -> tuple[float, float, float]:
    pred = np.asarray(predicted, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    intersection = float((pred * target).sum())
    union = float((pred + target - pred * target).sum())
    if union <= 1e-12:
        return float("inf"), 0.0, float("inf")
    iou = intersection / union
    l1 = float(np.abs(pred - target).mean())
    return float(l1 + 1.0 - iou), float(iou), l1


def _chroma_error(
    predicted_rgb: np.ndarray,
    target_rgb: np.ndarray,
    predicted_alpha: np.ndarray,
    target_alpha: np.ndarray,
) -> float:
    """Compare normalized color only on overlapping foreground support.

    Alpha remains the primary registration objective.  Chroma is a parity
    tie-breaker so a front/back texture flip is not hidden by a symmetric
    silhouette; it never changes the captured motion or mesh geometry.
    """
    predicted = np.asarray(predicted_rgb, dtype=np.float64)
    target = np.asarray(target_rgb, dtype=np.float64)
    if predicted.shape != target.shape or predicted.ndim != 3 or predicted.shape[-1] != 3:
        raise ValueError("RGB images must have matching [H,W,3] shapes")
    pred_alpha = np.clip(np.asarray(predicted_alpha, dtype=np.float64), 0.0, 1.0)
    target_alpha = np.clip(np.asarray(target_alpha, dtype=np.float64), 0.0, 1.0)
    if pred_alpha.shape != target_alpha.shape or pred_alpha.shape != predicted.shape[:2]:
        raise ValueError("alpha images must match RGB height and width")
    pred_chroma = predicted / np.maximum(predicted.sum(axis=-1, keepdims=True), 1e-6)
    target_chroma = target / np.maximum(target.sum(axis=-1, keepdims=True), 1e-6)
    support = np.minimum(pred_alpha, target_alpha)
    denominator = max(float(support.sum()), 1e-12)
    return float((np.abs(pred_chroma - target_chroma).sum(axis=-1) * support).sum() / denominator)


def register_camera(
    renderer: Any,
    vertices: np.ndarray,
    target_rgb: Any,
    target_alpha: Any,
    target_distance: Any,
    resolution: int,
    source_crop: dict[str, Any],
    source_size: tuple[int, int],
    *,
    min_iou: float = MIN_REGISTERED_IOU,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Find and freeze one bounded current-Y-up camera from idle alpha.

    The renderer must expose ``set_camera(camera)`` and
    ``render([1,V,3]) -> (rgb, alpha)``.  Alpha remains the primary objective;
    target RGB is used only as a normalized-chroma tie-break for front/back
    parity, while depth is shape-checked and not used to choose the camera.
    """
    vertices, target, source_size, crop = _validate_inputs(
        vertices=vertices,
        target_rgb=target_rgb,
        target_alpha=target_alpha,
        target_distance=target_distance,
        resolution=int(resolution),
        source_crop=source_crop,
        source_size=source_size,
    )
    target_rgb_array = _torch_or_numpy(target_rgb)[0]
    bbox = _target_bbox(target)
    coarse: list[tuple[float, float, float, float, dict[str, Any]]] = []
    evaluations = 0

    def evaluate(yaw_deg: float, pitch_deg: float, scale_factor: float = 1.0,
                 dx_factor: float = 0.0, dy_factor: float = 0.0) -> tuple[float, float, float, dict[str, Any]]:
        nonlocal evaluations
        basis = _basis_yup(yaw_deg, pitch_deg)
        base_scale, base_offset = _bbox_scale_offset(vertices, basis, bbox)
        camera = _camera(
            basis,
            scale=base_scale * float(scale_factor),
            offset=base_offset + np.asarray((dx_factor * resolution, dy_factor * resolution)),
            vertices=vertices,
            source_size=source_size,
            source_crop=crop,
            resolution=int(resolution),
            yaw_deg=yaw_deg,
            pitch_deg=pitch_deg,
        )
        renderer.set_camera(camera)
        predicted_rgb, predicted_alpha = _render_images(renderer, vertices, resolution=int(resolution))
        loss, iou, l1 = _alpha_metrics(predicted_alpha, target)
        chroma = _chroma_error(predicted_rgb, target_rgb_array, predicted_alpha, target)
        evaluations += 1
        return iou, chroma, loss, l1, camera

    for yaw_deg in COARSE_YAWS_DEG:
        for pitch_deg in COARSE_PITCHES_DEG:
            coarse.append(evaluate(float(yaw_deg), float(pitch_deg)))
    coarse.sort(key=lambda item: (-item[0], item[1], item[2]))
    best_iou, best_chroma, best_loss, best_l1, best_camera = coarse[0]
    best_yaw = float(best_camera["yawDeg"])
    best_pitch = float(best_camera["pitchDeg"])

    # 90 coarse plus at most 243 local hypotheses. This remains one bounded
    # idle-only registration, not a camera adjustment during weight fitting.
    for yaw_deg in ((best_yaw - REFINE_STEP_DEG) % 360.0,
                    best_yaw,
                    (best_yaw + REFINE_STEP_DEG) % 360.0):
        for pitch_deg in (best_pitch - REFINE_STEP_DEG, best_pitch, best_pitch + REFINE_STEP_DEG):
            if not 0.0 <= pitch_deg <= 90.0:
                continue
            for scale_factor in REFINE_SCALE_FACTORS:
                for dx_factor in REFINE_OFFSET_FACTORS:
                    for dy_factor in REFINE_OFFSET_FACTORS:
                        iou, chroma, loss, l1, camera = evaluate(
                            yaw_deg, pitch_deg, scale_factor, dx_factor, dy_factor
                        )
                        better_iou = iou > best_iou + 1e-6
                        tied_iou = abs(iou - best_iou) <= 1e-6
                        if better_iou or (tied_iou and (chroma < best_chroma - 1e-7 or
                                                        (abs(chroma - best_chroma) <= 1e-7 and loss < best_loss))):
                            best_iou, best_chroma, best_loss, best_l1, best_camera = iou, chroma, loss, l1, camera

    report = {
        "status": "registered" if best_iou >= MIN_REGISTERED_IOU else "camera_rejected",
        "registrationPolicy": "bounded_current_yup_idle_alpha_grid_then_local_refine",
        "orientationSource": "current_frozen_glTF_Y_up_bounded_yaw_pitch",
        "orientationSearch": {
            "coarseYawDeg": list(COARSE_YAWS_DEG),
            "yawDomain": "full_azimuth_0_360",
            "coarsePitchDeg": list(COARSE_PITCHES_DEG),
            "refineStepDeg": REFINE_STEP_DEG,
            "refineScaleFactors": list(REFINE_SCALE_FACTORS),
            "refineOffsetFactors": list(REFINE_OFFSET_FACTORS),
        },
        "facingPolicy": "both_azimuth_parities_scored_against_idle_alpha",
        "colorTieBreak": "overlap_normalized_rgb_chroma",
        "historicalCameraArtifactUsed": False,
        "coordinateSpace": "current_glTF_y_up",
        "sourceSize": list(source_size),
        "sourceCrop": crop,
        "resolution": int(resolution),
        "sourceFrameHash": None,
        "sourceFrameHashPolicy": "caller_owned; registration API receives tensors, not a source path",
        "targetRgbUsed": False,
        "targetDistanceUsed": False,
        "evaluations": int(evaluations),
        "best": {
            "iou": float(best_iou),
            "loss": float(best_loss),
            "alphaL1": float(best_l1),
            "chromaError": float(best_chroma),
            "yawDeg": float(best_camera["yawDeg"]),
            "pitchDeg": float(best_camera["pitchDeg"]),
            "scale": float(best_camera["scale"]),
            "offset": np.asarray(best_camera["offset"], dtype=np.float64).tolist(),
        },
        "minimumIoU": float(min_iou),
    }
    if best_iou < float(min_iou):
        raise CameraRegistrationError(
            f"bounded current-Y-up idle registration failed: IoU {best_iou:.4f} < {float(min_iou):.4f}",
            report,
        )
    renderer.set_camera(best_camera)
    report["camera"] = {
        key: (value.tolist() if isinstance(value, np.ndarray) else value)
        for key, value in best_camera.items()
    }
    return best_camera, report
