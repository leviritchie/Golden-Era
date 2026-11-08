"""Derive sparse IK stick targets from silhouette miss pairing.

Instead of LLM-authored keypoints.json, compare the current pose raster to the
sprite target:

- **Excess** (predicted & ~target): mesh sticking out where it should not.
- **Missing** (target & ~predicted): sprite figure the pose does not cover.

Pair one excess blob with one missing blob at similar depth. The missing tip
becomes the 2D IK goal for the searchable bone that most influences the excess
blob (skinning attribution), not the nearest projected pivot.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from gpu_depth_silhouette_solver import label_binary_components, missing_target_silhouette


@dataclass(frozen=True)
class SilhouetteMissPair:
    """One excess→missing silhouette pairing."""

    excess_tip: tuple[float, float]
    target_tip: tuple[float, float]
    predicted_depth: float
    target_depth: float
    excess_area: int
    missing_area: int
    excess_label_id: int
    missing_label_id: int
    tip_distance_sq: float

    @property
    def combined_area(self) -> int:
        return int(self.excess_area) + int(self.missing_area)


@dataclass(frozen=True)
class MissPair:
    """Resolved pair with assigned bone."""

    joint_name: str
    excess_tip: tuple[float, float]
    target_tip: tuple[float, float]
    predicted_depth: float
    target_depth: float
    excess_area: int
    missing_area: int


def excess_predicted_silhouette(
    target_mask: np.ndarray,
    predicted_mask: np.ndarray,
    *,
    threshold: float,
) -> np.ndarray:
    """Pixels the current pose covers that the target sprite does not."""
    target = np.asarray(target_mask, dtype=np.float32) > 0.5
    predicted = np.asarray(predicted_mask, dtype=np.float32) > float(threshold)
    if target.shape != predicted.shape:
        raise ValueError("target and predicted silhouette masks must have the same shape")
    return predicted & ~target


def _component_pixels(labels: np.ndarray, label_id: int) -> tuple[np.ndarray, np.ndarray]:
    rows, cols = np.nonzero(labels == int(label_id))
    return rows, cols


def _component_area(labels: np.ndarray, label_id: int) -> int:
    return int(np.count_nonzero(labels == int(label_id)))


def _component_median_depth(depth: np.ndarray, mask: np.ndarray) -> float:
    return _component_median_depth_on_mask(depth, mask)


def component_extremal_tip(
    labels: np.ndarray,
    label_id: int,
    *,
    reference_xy: tuple[float, float] | None = None,
) -> tuple[float, float]:
    """Return the pixel farthest from the reference point within one component."""
    rows, cols = _component_pixels(labels, int(label_id))
    if rows.size == 0:
        raise ValueError(f"component {label_id} is empty")
    if reference_xy is None:
        reference_xy = (float(np.mean(cols)), float(np.mean(rows)))
    ref_x, ref_y = reference_xy
    dx = cols.astype(np.float64) - float(ref_x)
    dy = rows.astype(np.float64) - float(ref_y)
    index = int(np.argmax(dx * dx + dy * dy))
    return float(cols[index]), float(rows[index])


def _depth_at_pixel(depth: np.ndarray, xy: tuple[float, float]) -> float:
    depth = np.asarray(depth, dtype=np.float32)
    x = int(round(float(xy[0])))
    y = int(round(float(xy[1])))
    height, width = depth.shape
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError(f"depth sample out of bounds: ({x}, {y}) for {width}x{height}")
    return float(depth[y, x])


def _component_centroid(labels: np.ndarray, label_id: int) -> tuple[float, float]:
    rows, cols = _component_pixels(labels, int(label_id))
    if rows.size == 0:
        raise ValueError(f"component {label_id} is empty")
    return float(np.mean(cols)), float(np.mean(rows))


def _component_median_depth_on_mask(depth: np.ndarray, mask: np.ndarray) -> float:
    values = np.asarray(depth, dtype=np.float32)[mask]
    if values.size == 0:
        raise ValueError("depth component is empty")
    return float(np.median(values))


def pair_silhouette_misses(
    target_mask: np.ndarray,
    predicted_mask: np.ndarray,
    target_depth: np.ndarray,
    predicted_depth: np.ndarray,
    *,
    predicted_alpha_threshold: float = 0.5,
    depth_tolerance: float = 0.12,
    min_component_area: int = 12,
    max_pairs: int = 2,
    max_tip_distance_px: float = 56.0,
    max_centroid_distance_px: float = 72.0,
    max_area_ratio: float = 4.0,
    min_displacement_alignment: float = 0.15,
) -> list[SilhouetteMissPair]:
    """Pair excess blobs with missing blobs that plausibly describe one displaced part.

    A valid pair must satisfy all of:
    - similar **median** depth on each blob;
    - excess and missing tips within ``max_tip_distance_px``;
    - centroids within ``max_centroid_distance_px``;
    - area ratio ``max(excess, missing) / min(excess, missing) <= max_area_ratio``;
    - centroid displacement aligns with tip displacement
      (``dot(centroid_vec, tip_vec) > 0`` and cosine >= ``min_displacement_alignment``).

    Returns the best globally disjoint assignments ranked by combined area, then
    tip distance.
    """
    if int(min_component_area) < 1:
        raise ValueError("min_component_area must be positive")
    if int(max_pairs) < 1:
        raise ValueError("max_pairs must be positive")
    if not math.isfinite(float(depth_tolerance)) or float(depth_tolerance) < 0.0:
        raise ValueError("depth_tolerance must be finite and non-negative")
    if not math.isfinite(float(max_tip_distance_px)) or float(max_tip_distance_px) <= 0.0:
        raise ValueError("max_tip_distance_px must be finite and positive")
    if not math.isfinite(float(max_centroid_distance_px)) or float(max_centroid_distance_px) <= 0.0:
        raise ValueError("max_centroid_distance_px must be finite and positive")
    if not math.isfinite(float(max_area_ratio)) or float(max_area_ratio) < 1.0:
        raise ValueError("max_area_ratio must be finite and at least 1")
    if not math.isfinite(float(min_displacement_alignment)):
        raise ValueError("min_displacement_alignment must be finite")

    missing = missing_target_silhouette(
        target_mask,
        predicted_mask,
        threshold=float(predicted_alpha_threshold),
    )
    excess = excess_predicted_silhouette(
        target_mask,
        predicted_mask,
        threshold=float(predicted_alpha_threshold),
    )
    miss_labels, miss_count = label_binary_components(missing)
    excess_labels, excess_count = label_binary_components(excess)

    candidates: list[SilhouetteMissPair] = []
    for excess_id in range(1, int(excess_count) + 1):
        excess_area = _component_area(excess_labels, excess_id)
        if excess_area < int(min_component_area):
            continue
        excess_mask = excess_labels == int(excess_id)
        excess_tip = component_extremal_tip(excess_labels, excess_id)
        excess_centroid = _component_centroid(excess_labels, excess_id)
        try:
            predicted_depth_value = _component_median_depth_on_mask(predicted_depth, excess_mask)
        except ValueError:
            continue
        for miss_id in range(1, int(miss_count) + 1):
            missing_area = _component_area(miss_labels, miss_id)
            if missing_area < int(min_component_area):
                continue
            area_ratio = max(excess_area, missing_area) / max(min(excess_area, missing_area), 1)
            if area_ratio > float(max_area_ratio):
                continue
            miss_mask = miss_labels == int(miss_id)
            target_depth_value = _component_median_depth_on_mask(target_depth, miss_mask)
            if abs(target_depth_value - predicted_depth_value) > float(depth_tolerance):
                continue
            miss_tip = component_extremal_tip(
                miss_labels,
                miss_id,
                reference_xy=excess_tip,
            )
            miss_centroid = _component_centroid(miss_labels, miss_id)
            tip_dx = float(miss_tip[0] - excess_tip[0])
            tip_dy = float(miss_tip[1] - excess_tip[1])
            tip_dist_sq = tip_dx * tip_dx + tip_dy * tip_dy
            if tip_dist_sq > float(max_tip_distance_px) ** 2:
                continue
            centroid_dx = float(miss_centroid[0] - excess_centroid[0])
            centroid_dy = float(miss_centroid[1] - excess_centroid[1])
            centroid_dist_sq = centroid_dx * centroid_dx + centroid_dy * centroid_dy
            if centroid_dist_sq > float(max_centroid_distance_px) ** 2:
                continue
            tip_norm = math.sqrt(tip_dist_sq)
            centroid_norm = math.sqrt(centroid_dist_sq)
            if tip_norm < 1e-6 or centroid_norm < 1e-6:
                continue
            alignment = (tip_dx * centroid_dx + tip_dy * centroid_dy) / (tip_norm * centroid_norm)
            if alignment < float(min_displacement_alignment):
                continue
            candidates.append(
                SilhouetteMissPair(
                    excess_tip=excess_tip,
                    target_tip=miss_tip,
                    predicted_depth=float(predicted_depth_value),
                    target_depth=float(target_depth_value),
                    excess_area=int(excess_area),
                    missing_area=int(missing_area),
                    excess_label_id=int(excess_id),
                    missing_label_id=int(miss_id),
                    tip_distance_sq=float(tip_dist_sq),
                )
            )

    candidates.sort(key=lambda item: (-item.combined_area, item.tip_distance_sq))
    chosen: list[SilhouetteMissPair] = []
    used_excess: set[int] = set()
    used_missing: set[int] = set()
    for pair in candidates:
        if pair.excess_label_id in used_excess or pair.missing_label_id in used_missing:
            continue
        chosen.append(pair)
        used_excess.add(pair.excess_label_id)
        used_missing.add(pair.missing_label_id)
        if len(chosen) >= int(max_pairs):
            break
    return chosen


def nearest_joint_name(
    joint_xy: Mapping[str, tuple[float, float]],
    point_xy: tuple[float, float],
    *,
    allowed: Sequence[str] | None = None,
) -> str:
    """Pick the stick joint whose projected site is closest to ``point_xy``."""
    if not joint_xy:
        raise ValueError("joint_xy is empty")
    allowed_set = None if allowed is None else {str(name) for name in allowed}
    best_name = None
    best_dist = math.inf
    px, py = float(point_xy[0]), float(point_xy[1])
    for name, (x, y) in joint_xy.items():
        if allowed_set is not None and str(name) not in allowed_set:
            continue
        dist = (float(x) - px) ** 2 + (float(y) - py) ** 2
        if dist < best_dist:
            best_dist = dist
            best_name = str(name)
    if best_name is None:
        raise ValueError("no allowed joint matched the excess tip")
    return best_name


def assign_joint_by_influence(
    influence: Mapping[str, float],
    *,
    allowed: Sequence[str],
    node_depth: Callable[[str], int],
    tie_fraction: float = 0.95,
) -> str | None:
    """Pick the allowed bone with highest skinning influence in an excess blob."""
    if not allowed:
        raise ValueError("allowed bones cannot be empty")
    allowed_set = {str(name) for name in allowed}
    scored = {
        str(name): float(influence.get(str(name), 0.0))
        for name in allowed_set
    }
    best_score = max(scored.values())
    if best_score <= 0.0:
        return None
    threshold = best_score * float(tie_fraction)
    candidates = [name for name, score in scored.items() if score >= threshold]
    return max(candidates, key=lambda name: int(node_depth(name)))


def build_frame_miss_keypoints(
    target_mask: np.ndarray,
    predicted_mask: np.ndarray,
    target_depth: np.ndarray,
    predicted_depth: np.ndarray,
    joint_xy: Mapping[str, tuple[float, float]],
    *,
    primary_joints: Sequence[str] | None = None,
    predicted_alpha_threshold: float = 0.5,
    depth_tolerance: float = 0.12,
    min_component_area: int = 12,
    max_pairs: int = 2,
    max_tip_distance_px: float = 56.0,
    max_centroid_distance_px: float = 72.0,
    max_area_ratio: float = 4.0,
    min_displacement_alignment: float = 0.15,
    assign_joint: Callable[[SilhouetteMissPair], str | None] | None = None,
) -> tuple[dict[str, tuple[float, float]], list[MissPair]]:
    """Build sparse joint→target-pixel map for one frame."""
    allowed = tuple(primary_joints) if primary_joints is not None else tuple(joint_xy)
    pairs = pair_silhouette_misses(
        target_mask,
        predicted_mask,
        target_depth,
        predicted_depth,
        predicted_alpha_threshold=float(predicted_alpha_threshold),
        depth_tolerance=float(depth_tolerance),
        min_component_area=int(min_component_area),
        max_pairs=int(max_pairs),
        max_tip_distance_px=float(max_tip_distance_px),
        max_centroid_distance_px=float(max_centroid_distance_px),
        max_area_ratio=float(max_area_ratio),
        min_displacement_alignment=float(min_displacement_alignment),
    )
    keypoints: dict[str, tuple[float, float]] = {}
    reports: list[MissPair] = []
    for pair in pairs:
        if assign_joint is not None:
            joint_name = assign_joint(pair)
            if joint_name is None:
                joint_name = nearest_joint_name(
                    joint_xy,
                    pair.excess_tip,
                    allowed=allowed,
                )
        else:
            joint_name = nearest_joint_name(
                joint_xy,
                pair.excess_tip,
                allowed=allowed,
            )
        if joint_name in keypoints:
            continue
        keypoints[joint_name] = pair.target_tip
        reports.append(
            MissPair(
                joint_name=str(joint_name),
                excess_tip=pair.excess_tip,
                target_tip=pair.target_tip,
                predicted_depth=float(pair.predicted_depth),
                target_depth=float(pair.target_depth),
                excess_area=int(pair.excess_area),
                missing_area=int(pair.missing_area),
            )
        )
    return keypoints, reports


def miss_keypoints_to_authored_payload(
    frames: Mapping[int, Mapping[str, tuple[float, float]]],
    *,
    source_width: int,
    source_height: int,
) -> dict[str, Any]:
    """Serialize dynamic keypoints in the human_eye_landmark_authoring shape."""
    return {
        "method": "silhouette_miss_pairing",
        "sourceWidth": int(source_width),
        "sourceHeight": int(source_height),
        "frames": [
            {
                "frameIndex": int(frame_index),
                "joints": {
                    name: {"x": float(xy[0]), "y": float(xy[1]), "visible": True}
                    for name, xy in sorted(joints.items())
                },
            }
            for frame_index, joints in sorted(frames.items())
        ],
    }
