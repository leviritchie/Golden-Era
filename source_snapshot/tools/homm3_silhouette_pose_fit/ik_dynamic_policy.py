"""Dynamic movement policy for silhouette_miss incremental blob IK.

Chooses which blobs/joints to move first, how long the parent chain should be,
and how large local-axis steps should be — without LLM authorship.
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

from ik_incremental_blob import chain_prefixes


def clamp_step_scale(
    raw_scale: float,
    *,
    min_scale: float,
    max_scale: float,
) -> float:
    if not math.isfinite(float(raw_scale)):
        raise ValueError("step scale must be finite")
    if not math.isfinite(float(min_scale)) or float(min_scale) <= 0.0:
        raise ValueError("min_scale must be finite and positive")
    if not math.isfinite(float(max_scale)) or float(max_scale) < float(min_scale):
        raise ValueError("max_scale must be finite and >= min_scale")
    return max(float(min_scale), min(float(max_scale), float(raw_scale)))


def displacement_step_scale(
    displacement_px: float,
    *,
    ref_px: float,
) -> float:
    if not math.isfinite(float(displacement_px)) or float(displacement_px) < 0.0:
        raise ValueError("displacement_px must be finite and non-negative")
    if not math.isfinite(float(ref_px)) or float(ref_px) <= 0.0:
        raise ValueError("ref_px must be finite and positive")
    return float(displacement_px) / float(ref_px)


def scale_step_deg(
    base_deg: float,
    *,
    mode: str,
    displacement_px: float,
    frame_deficit: float,
    ref_px: float,
    min_scale: float,
    max_scale: float,
) -> float:
    """Scale a limb/proximal step from blob displacement and/or frame error."""
    if not math.isfinite(float(base_deg)) or float(base_deg) <= 0.0:
        raise ValueError("base_deg must be finite and positive")
    if mode == "fixed":
        scale = 1.0
    elif mode == "displacement":
        scale = displacement_step_scale(displacement_px, ref_px=ref_px)
    elif mode == "deficit":
        if not math.isfinite(float(frame_deficit)) or float(frame_deficit) < 0.0:
            raise ValueError("frame_deficit must be finite and non-negative")
        scale = 0.35 + float(frame_deficit)
    elif mode == "combined":
        if not math.isfinite(float(frame_deficit)) or float(frame_deficit) < 0.0:
            raise ValueError("frame_deficit must be finite and non-negative")
        scale = displacement_step_scale(displacement_px, ref_px=ref_px) * (
            0.35 + float(frame_deficit)
        )
    else:
        raise ValueError(f"unsupported ik_step_scale_mode: {mode!r}")
    return float(base_deg) * clamp_step_scale(scale, min_scale=min_scale, max_scale=max_scale)


def chain_start_length(
    displacement_px: float,
    max_chain_length: int,
    *,
    ref_px: float,
) -> int:
    """Map miss distance to an initial unlocked chain length (distal-first)."""
    if int(max_chain_length) < 1:
        raise ValueError("max_chain_length must be at least 1")
    if not math.isfinite(float(displacement_px)) or float(displacement_px) < 0.0:
        raise ValueError("displacement_px must be finite and non-negative")
    if not math.isfinite(float(ref_px)) or float(ref_px) <= 0.0:
        raise ValueError("ref_px must be finite and positive")
    if float(displacement_px) <= float(ref_px) * 0.5:
        return 1
    grown = 1 + int(math.floor(float(displacement_px) / float(ref_px)))
    return max(1, min(int(max_chain_length), int(grown)))


def filter_chain_prefixes(
    prefixes: Sequence[Sequence[int]],
    *,
    mode: str,
    displacement_px: float,
    ref_px: float,
) -> tuple[tuple[int, ...], ...]:
    """Optionally skip short chain prefixes when the miss is large."""
    ordered = tuple(tuple(int(index) for index in prefix) for prefix in prefixes)
    if not ordered:
        raise ValueError("prefixes must contain at least one chain")
    if mode == "distal":
        return ordered
    if mode != "displacement":
        raise ValueError(f"unsupported ik_chain_start_mode: {mode!r}")
    start_len = chain_start_length(
        displacement_px,
        len(ordered),
        ref_px=ref_px,
    )
    if int(start_len) <= 1:
        return ordered
    trimmed = ordered[int(start_len) - 1 :]
    if not trimmed:
        raise RuntimeError("displacement chain trim removed every prefix")
    return trimmed


def sort_blob_jobs(jobs: Sequence, *, mode: str) -> list:
    """Reorder blob jobs within one frame."""
    items = list(jobs)
    if mode == "pair_rank":
        return items
    if mode == "displacement":
        return sorted(
            items,
            key=lambda job: float(getattr(job, "tip_displacement_px", 0.0)),
            reverse=True,
        )
    if mode == "priority":
        return sorted(
            items,
            key=lambda job: float(getattr(job, "priority_score", 0.0)),
            reverse=True,
        )
    raise ValueError(f"unsupported ik_job_order_mode: {mode!r}")


def passes_influence_dominance(
    influence: Mapping[str, float],
    bone_name: str,
    *,
    min_ratio: float,
) -> bool:
    """Require the assigned bone to own enough of the excess blob influence."""
    if float(min_ratio) <= 0.0:
        return True
    if not math.isfinite(float(min_ratio)) or float(min_ratio) > 1.0:
        raise ValueError("min_ratio must be in [0, 1]")
    total = sum(float(value) for value in influence.values())
    if total <= 0.0:
        return False
    owned = float(influence.get(str(bone_name), 0.0))
    return owned / total >= float(min_ratio)


def dynamic_stop_score(
    opening_score: float,
    target_score: float,
    *,
    displacement_px: float,
    ref_px: float,
    min_gain: float = 0.25,
    max_gain: float = 1.0,
) -> float:
    """Per-blob stop threshold: large misses aim closer to the global target."""
    if not math.isfinite(float(opening_score)) or not math.isfinite(float(target_score)):
        raise ValueError("opening_score and target_score must be finite")
    if float(target_score) <= float(opening_score):
        return float(target_score)
    gain = displacement_step_scale(displacement_px, ref_px=ref_px)
    gain = max(float(min_gain), min(float(max_gain), float(gain)))
    return float(opening_score) + gain * (float(target_score) - float(opening_score))
