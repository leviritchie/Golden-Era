"""Named cascade bone-visit rankings. One mode is one ranking rule.

``asset`` and ``dependency`` fix the visit list when the search set is built.
The other modes re-rank that same set at the start of each discrete joint
round. Ties keep the incoming order. Equal scores are not a switch to another
mode.
"""
from __future__ import annotations

import math
from typing import Mapping, Sequence


STATIC_BONE_ORDER_MODES = ("asset", "dependency")
DYNAMIC_BONE_ORDER_MODES = (
    "error_driven",
    "gradient_magnitude",
    "expected_gain",
    "temporal_disagreement",
    "screen_space_leverage",
    "error_leverage",
)
CASCADE_BONE_ORDER_MODES = STATIC_BONE_ORDER_MODES + DYNAMIC_BONE_ORDER_MODES


def validate_cascade_bone_order_mode(mode: str) -> str:
    token = str(mode)
    if token not in CASCADE_BONE_ORDER_MODES:
        raise ValueError(
            "bone_order_mode must be one of: " + ", ".join(CASCADE_BONE_ORDER_MODES)
        )
    return token


def is_dynamic_bone_order_mode(mode: str) -> bool:
    return validate_cascade_bone_order_mode(mode) in DYNAMIC_BONE_ORDER_MODES


def rank_bones_by_score(
    bones: Sequence[int],
    scores: Mapping[int, float],
    *,
    original_order: Sequence[int],
) -> tuple[int, ...]:
    """Highest score first. Ties keep ``original_order``."""
    ordered = [int(index) for index in bones]
    if not ordered:
        raise ValueError("bone ranking requires at least one bone")
    original_rank = {int(index): position for position, index in enumerate(original_order)}
    missing_original = [index for index in ordered if index not in original_rank]
    if missing_original:
        raise ValueError(f"original_order is missing bones: {missing_original[:8]}")
    missing_scores = [index for index in ordered if int(index) not in scores]
    if missing_scores:
        raise ValueError(f"bone ranking scores are missing bones: {missing_scores[:8]}")
    extras = [index for index in scores if int(index) not in set(ordered)]
    if extras:
        raise ValueError(f"bone ranking scores include bones outside the set: {extras[:8]}")
    ranked_scores: list[float] = []
    for index in ordered:
        value = float(scores[int(index)])
        if not math.isfinite(value):
            raise ValueError(f"bone ranking score for {index} is not finite")
        ranked_scores.append(value)
    return tuple(
        sorted(
            ordered,
            key=lambda index: (
                -float(scores[int(index)]),
                int(original_rank[int(index)]),
            ),
        )
    )


def rank_bones_by_keys(
    bones: Sequence[int],
    keys: Mapping[int, tuple[float, ...]],
    *,
    original_order: Sequence[int],
) -> tuple[int, ...]:
    """Lexicographic rank. Each key coordinate is higher-is-better."""
    ordered = [int(index) for index in bones]
    if not ordered:
        raise ValueError("bone ranking requires at least one bone")
    original_rank = {int(index): position for position, index in enumerate(original_order)}
    missing_original = [index for index in ordered if index not in original_rank]
    if missing_original:
        raise ValueError(f"original_order is missing bones: {missing_original[:8]}")
    missing_keys = [index for index in ordered if int(index) not in keys]
    if missing_keys:
        raise ValueError(f"bone ranking keys are missing bones: {missing_keys[:8]}")
    width = None
    for index in ordered:
        key = tuple(float(part) for part in keys[int(index)])
        if any(not math.isfinite(part) for part in key):
            raise ValueError(f"bone ranking key for {index} is not finite")
        if width is None:
            width = len(key)
        elif len(key) != width:
            raise ValueError("bone ranking keys must share one length")
    if width is None:
        raise ValueError("bone ranking keys are empty")
    return tuple(
        sorted(
            ordered,
            key=lambda index: tuple(
                [-float(part) for part in keys[int(index)]] + [int(original_rank[int(index)])]
            ),
        )
    )


def area_normalized_scores(
    mass: Mapping[int, float],
    area: Mapping[int, float],
) -> dict[int, float]:
    """``mass / area`` so a large torso does not win by pixel count alone.

    A bone with area 0 has score 0. That is a defined rank, not a fallback
    to another mode.
    """
    names = sorted(int(index) for index in mass)
    if set(names) != {int(index) for index in area}:
        raise ValueError("mass and area must cover the same bones")
    if not names:
        raise ValueError("area-normalized scores need at least one bone")
    out: dict[int, float] = {}
    for index in names:
        raw_mass = float(mass[index])
        raw_area = float(area[index])
        if not math.isfinite(raw_mass) or raw_mass < 0.0:
            raise ValueError(f"error mass for bone {index} must be finite and non-negative")
        if not math.isfinite(raw_area) or raw_area < 0.0:
            raise ValueError(f"influence area for bone {index} must be finite and non-negative")
        out[index] = 0.0 if raw_area <= 0.0 else raw_mass / raw_area
    return out


def length_normalized_scores(
    magnitude: Mapping[int, float],
    length: Mapping[int, float],
) -> dict[int, float]:
    """``magnitude / length`` so a long lever does not dominate a short joint."""
    names = sorted(int(index) for index in magnitude)
    if set(names) != {int(index) for index in length}:
        raise ValueError("magnitude and length must cover the same bones")
    if not names:
        raise ValueError("length-normalized scores need at least one bone")
    out: dict[int, float] = {}
    for index in names:
        raw_mag = float(magnitude[index])
        raw_len = float(length[index])
        if not math.isfinite(raw_mag) or raw_mag < 0.0:
            raise ValueError(f"gradient magnitude for bone {index} must be finite and non-negative")
        if not math.isfinite(raw_len) or raw_len < 0.0:
            raise ValueError(f"bone length for {index} must be finite and non-negative")
        out[index] = raw_mag if raw_len <= 1e-12 else raw_mag / raw_len
    return out


def error_leverage_keys(
    error_scores: Mapping[int, float],
    leverage_scores: Mapping[int, float],
) -> dict[int, tuple[float, float]]:
    """Lexicographic (error, reach) keys. Ranking uses ``error_leverage_scores``."""
    names = sorted(int(index) for index in error_scores)
    if set(names) != {int(index) for index in leverage_scores}:
        raise ValueError("error and leverage must cover the same bones")
    if not names:
        raise ValueError("error_leverage keys need at least one bone")
    out: dict[int, tuple[float, float]] = {}
    for index in names:
        error = float(error_scores[index])
        leverage = float(leverage_scores[index])
        if not math.isfinite(error) or not math.isfinite(leverage):
            raise ValueError(f"error_leverage key for bone {index} is not finite")
        out[index] = (error, leverage)
    return out


def error_leverage_scores(
    error_scores: Mapping[int, float],
    leverage_scores: Mapping[int, float],
) -> dict[int, float]:
    """Occupancy leftover × screen joint reach.

    A bone must both sit on leftover pixels and be able to move a long
    screen lever. Error-only ranking spends visits on tiny high-density
    patches. Reach-only ranking moves bones where the picture is already
    correct. Product is 0 if either term is 0.
    """
    names = sorted(int(index) for index in error_scores)
    if set(names) != {int(index) for index in leverage_scores}:
        raise ValueError("error and leverage must cover the same bones")
    if not names:
        raise ValueError("error_leverage scores need at least one bone")
    out: dict[int, float] = {}
    for index in names:
        error = float(error_scores[index])
        leverage = float(leverage_scores[index])
        if not math.isfinite(error) or error < 0.0:
            raise ValueError(f"error for bone {index} must be finite and non-negative")
        if not math.isfinite(leverage) or leverage < 0.0:
            raise ValueError(f"leverage for bone {index} must be finite and non-negative")
        out[index] = error * leverage
    return out
