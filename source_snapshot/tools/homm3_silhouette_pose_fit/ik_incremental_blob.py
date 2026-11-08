"""Incremental silhouette-blob IK: distal joint first, grow toward the root.

This is the GPU cascade silhouette_miss solver. It does **not** run CCD on a
full parent chain. For each excess (red) blob:

1. Attribute the blob to the skinning-dominant searchable bone.
2. Search local axis-angle steps on that bone only.
3. If regional IoU stays below the target, unlock one parent and search both.
4. Spinal / central bones use a smaller step so the whole mesh does not spin.
5. Keep the interim chain length with the best regional IoU, not the last try.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class IncrementalBlobStep:
    """One recorded chain-length attempt for a blob."""

    chain_length: int
    chain_indices: tuple[int, ...]
    score: float
    stopped_at_target: bool


@dataclass(frozen=True)
class IncrementalBlobSolve:
    """Best kept pose after growing a chain against one repair region."""

    pose: Any
    score: float
    kept_chain_length: int
    steps: tuple[IncrementalBlobStep, ...]


def dilate_binary_mask(mask: np.ndarray, radius: int) -> np.ndarray:
    """Disk-dilate a 2D boolean mask. Radius 0 returns a bool copy."""
    if int(radius) < 0:
        raise ValueError("dilation radius must be non-negative")
    source = np.asarray(mask, dtype=bool)
    if source.ndim != 2:
        raise ValueError("mask must be 2D")
    if int(radius) == 0:
        return source.copy()
    height, width = source.shape
    out = source.copy()
    rad = int(radius)
    rad_sq = rad * rad
    for dy in range(-rad, rad + 1):
        for dx in range(-rad, rad + 1):
            if dx * dx + dy * dy > rad_sq:
                continue
            y_src0 = max(0, -dy)
            y_src1 = min(height, height - dy)
            x_src0 = max(0, -dx)
            x_src1 = min(width, width - dx)
            y_dst0 = max(0, dy)
            y_dst1 = min(height, height + dy)
            x_dst0 = max(0, dx)
            x_dst1 = min(width, width + dx)
            if y_src0 >= y_src1 or x_src0 >= x_src1:
                continue
            out[y_dst0:y_dst1, x_dst0:x_dst1] |= source[y_src0:y_src1, x_src0:x_src1]
    return out


def repair_region_from_blobs(
    excess_mask: np.ndarray,
    missing_mask: np.ndarray,
    *,
    dilate_px: int,
) -> np.ndarray:
    """Neighborhood covering the original red excess and paired blue missing blobs."""
    excess = np.asarray(excess_mask, dtype=bool)
    missing = np.asarray(missing_mask, dtype=bool)
    if excess.shape != missing.shape:
        raise ValueError("excess and missing masks must have the same shape")
    if excess.ndim != 2:
        raise ValueError("blob masks must be 2D")
    combined = excess | missing
    if not bool(combined.any()):
        raise ValueError("repair region needs a non-empty excess or missing blob")
    return dilate_binary_mask(combined, int(dilate_px))


def region_iou(
    predicted: np.ndarray,
    target: np.ndarray,
    region: np.ndarray,
    *,
    predicted_threshold: float = 0.5,
    target_threshold: float = 0.5,
) -> float:
    """Silhouette IoU inside ``region``. Empty union scores 1.0 (both absent)."""
    if not math.isfinite(float(predicted_threshold)):
        raise ValueError("predicted_threshold must be finite")
    if not math.isfinite(float(target_threshold)):
        raise ValueError("target_threshold must be finite")
    pred = np.asarray(predicted)
    tgt = np.asarray(target)
    area = np.asarray(region, dtype=bool)
    if pred.shape != tgt.shape or pred.shape != area.shape:
        raise ValueError("predicted, target, and region must have the same shape")
    if area.ndim != 2:
        raise ValueError("region must be 2D")
    if not bool(area.any()):
        raise ValueError("region IoU requires a non-empty region")
    pred_on = (pred > float(predicted_threshold)) & area
    tgt_on = (tgt > float(target_threshold)) & area
    intersection = int(np.count_nonzero(pred_on & tgt_on))
    union = int(np.count_nonzero(pred_on | tgt_on))
    if union == 0:
        return 1.0
    return float(intersection) / float(union)


def distal_first_parent_chain(
    end_index: int,
    parents: Sequence[int | None],
    *,
    max_joints: int,
) -> list[int]:
    """Walk from the assigned bone toward the root, omitting the skeleton root.

    Result order is distal-first: ``[assigned, parent, grandparent, ...]``.
    """
    if int(max_joints) < 1:
        raise ValueError("max_joints must be at least 1")
    node_count = len(parents)
    end = int(end_index)
    if end < 0 or end >= node_count:
        raise ValueError(f"end effector {end} is outside 0..{node_count - 1}")
    chain: list[int] = []
    current: int | None = end
    seen: set[int] = set()
    while current is not None and int(current) >= 0:
        if int(current) in seen:
            raise ValueError(f"parent cycle while growing IK chain at node {current}")
        seen.add(int(current))
        parent = parents[int(current)]
        parent_index = None if parent is None else int(parent)
        if parent_index is None or parent_index < 0:
            break
        chain.append(int(current))
        if len(chain) >= int(max_joints):
            break
        current = parent_index
    if not chain:
        raise ValueError(f"IK chain for end effector {end_index} is empty")
    return chain


def chain_prefixes(chain: Sequence[int]) -> list[tuple[int, ...]]:
    """Growing prefixes: first the distal bone, then +parent, then +grandparent."""
    if not chain:
        raise ValueError("chain must contain at least one bone")
    return [tuple(int(index) for index in chain[:length]) for length in range(1, len(chain) + 1)]


def step_deg_for_bone_depth(
    depth: int,
    *,
    proximal_min_depth: int,
    limb_step_deg: float,
    proximal_step_deg: float,
) -> float:
    """Limb bones get the full step. Shallower spinal bones get the small cap."""
    if int(proximal_min_depth) < 0:
        raise ValueError("proximal_min_depth must be non-negative")
    if not math.isfinite(float(limb_step_deg)) or float(limb_step_deg) <= 0.0:
        raise ValueError("limb_step_deg must be finite and positive")
    if not math.isfinite(float(proximal_step_deg)) or float(proximal_step_deg) <= 0.0:
        raise ValueError("proximal_step_deg must be finite and positive")
    if int(depth) < int(proximal_min_depth):
        return float(proximal_step_deg)
    return float(limb_step_deg)


def keep_best_interim(steps: Sequence[IncrementalBlobStep]) -> IncrementalBlobStep:
    """Highest score wins. Tie prefers the shorter chain (less whole-body motion)."""
    if not steps:
        raise ValueError("keep_best_interim requires at least one recorded step")
    return max(steps, key=lambda step: (float(step.score), -int(step.chain_length)))


def grow_chain_keep_best(
    opening_pose: Any,
    opening_score: float,
    prefixes: Sequence[Sequence[int]],
    *,
    search_prefix: Callable[[Any, tuple[int, ...]], tuple[Any, float]],
    target_score: float,
    on_step: Callable[[IncrementalBlobStep, Any], None] | None = None,
) -> IncrementalBlobSolve:
    """Grow one parent at a time, stop at ``target_score``, keep the best interim.

    Each longer prefix is searched from the best pose found so far, so an extra
    joint can move together with the distal bones without compounding a worse
    later try. The returned pose is the best recorded step, which may be shorter
    than the last prefix attempted.
    """
    if not math.isfinite(float(opening_score)):
        raise ValueError("opening_score must be finite")
    if not math.isfinite(float(target_score)) or not 0.0 < float(target_score) <= 1.0:
        raise ValueError("target_score must be in (0, 1]")
    opening_hit = float(opening_score) >= float(target_score)
    steps: list[IncrementalBlobStep] = [
        IncrementalBlobStep(
            chain_length=0,
            chain_indices=(),
            score=float(opening_score),
            stopped_at_target=bool(opening_hit),
        )
    ]
    best_pose = opening_pose
    best_score = float(opening_score)
    best_length = 0
    if opening_hit:
        return IncrementalBlobSolve(
            pose=best_pose,
            score=best_score,
            kept_chain_length=best_length,
            steps=tuple(steps),
        )
    for prefix in prefixes:
        if not prefix:
            raise ValueError("chain prefix must not be empty")
        prefix_indices = tuple(int(index) for index in prefix)
        trial_pose, trial_score = search_prefix(best_pose, prefix_indices)
        if not math.isfinite(float(trial_score)):
            raise ValueError("search_prefix returned a non-finite score")
        hit = float(trial_score) >= float(target_score)
        steps.append(
            IncrementalBlobStep(
                chain_length=len(prefix_indices),
                chain_indices=prefix_indices,
                score=float(trial_score),
                stopped_at_target=bool(hit),
            )
        )
        if on_step is not None:
            on_step(steps[-1], trial_pose)
        if float(trial_score) > best_score:
            best_pose = trial_pose
            best_score = float(trial_score)
            best_length = len(prefix_indices)
        if hit:
            break
    kept = keep_best_interim(steps)
    if int(kept.chain_length) != int(best_length):
        raise RuntimeError(
            "keep-best chain length disagrees with the running best; "
            "interim scoring must be deterministic"
        )
    return IncrementalBlobSolve(
        pose=best_pose,
        score=best_score,
        kept_chain_length=best_length,
        steps=tuple(steps),
    )


def search_chain_local_axes(
    pose,
    chain_indices: Sequence[int],
    *,
    directions: Sequence[Sequence[float]],
    step_rad_by_index: Mapping[int, float],
    joint_limit_rad: float,
    bone_limit_scales,
    offset_fn: Callable[..., Any],
    score_batch_fn: Callable[[Any], Sequence[float]],
    rounds: int,
    stop_score: float,
    on_improvement: Callable[[Any, float], None] | None = None,
) -> tuple[Any, float, list[float]]:
    """Coordinate local-axis search over ``chain_indices``. Distal bones first.

    ``pose`` has shape ``(1, bones, 3)`` in the cascade's raw tanh storage.
    ``offset_fn`` must match ``offset_raw_bone_direction``.
    ``score_batch_fn`` scores a stacked ``(N, bones, 3)`` batch and returns N floats.
    """
    import torch

    if int(rounds) < 1:
        raise ValueError("rounds must be at least 1")
    if not chain_indices:
        raise ValueError("chain_indices must contain at least one bone")
    if not directions:
        raise ValueError("directions must contain at least one local axis")
    if not math.isfinite(float(joint_limit_rad)) or float(joint_limit_rad) <= 0.0:
        raise ValueError("joint_limit_rad must be finite and positive")
    if not math.isfinite(float(stop_score)):
        raise ValueError("stop_score must be finite")

    current = pose.detach().clone()
    if int(current.dim()) != 3 or int(current.shape[0]) != 1 or int(current.shape[2]) != 3:
        raise ValueError("pose must have shape (1, bones, 3)")
    opening_scores = [float(value) for value in score_batch_fn(current)]
    if len(opening_scores) != 1:
        raise ValueError("score_batch_fn must return one score per stacked pose")
    best_score = float(opening_scores[0])
    round_scores = [best_score]
    if best_score >= float(stop_score):
        return current, best_score, round_scores

    probes: list[tuple[tuple[float, float, float], float]] = []
    for raw_direction in directions:
        axis = tuple(float(part) for part in raw_direction)
        if len(axis) != 3:
            raise ValueError("each direction must have 3 components")
        probes.append((axis, 1.0))
        probes.append((axis, -1.0))

    for _round in range(int(rounds)):
        improved = False
        for bone_index in (int(index) for index in chain_indices):
            step_rad = float(step_rad_by_index[int(bone_index)])
            if not math.isfinite(step_rad) or step_rad <= 0.0:
                raise ValueError(f"step_rad for bone {bone_index} must be finite and positive")
            trials = []
            for axis, sign in probes:
                trials.append(
                    offset_fn(
                        current,
                        bone_index=int(bone_index),
                        direction=axis,
                        delta_rad=float(sign) * step_rad,
                        joint_limit_rad=float(joint_limit_rad),
                        bone_limit_scales=bone_limit_scales,
                    )
                )
            stacked = torch.cat(trials, dim=0)
            scores = [float(value) for value in score_batch_fn(stacked)]
            if len(scores) != int(stacked.shape[0]):
                raise ValueError(
                    f"score_batch_fn returned {len(scores)} scores for "
                    f"{int(stacked.shape[0])} poses"
                )
            winner = int(max(range(len(scores)), key=lambda index: scores[index]))
            winner_score = float(scores[winner])
            if winner_score > best_score:
                current = stacked[winner : winner + 1].detach().clone()
                best_score = winner_score
                improved = True
                if on_improvement is not None:
                    on_improvement(current, best_score)
                if best_score >= float(stop_score):
                    round_scores.append(best_score)
                    return current, best_score, round_scores
        round_scores.append(best_score)
        if not improved:
            break
    return current, best_score, round_scores
