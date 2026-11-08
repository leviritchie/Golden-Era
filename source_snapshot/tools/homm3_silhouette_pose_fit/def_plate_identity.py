#!/usr/bin/env python3
"""Recognise repeated DEF sprite plates, and measure a clip's loop seam.

Why a sequential tracker needs this
-----------------------------------
``def_continuous_pose_tracker`` solves frame N starting from frame N-1, so error
only ever accumulates: nothing pulls the pose back once it has wandered. HoMM3 DEF
clips make that failure measurable, because their idle sections repeat plates
*exactly*. On h3_roc ``idle_start_move_end`` frames 7, 22 and 29 are pixel-identical
to frame 0 (alpha IoU 1.0000, RGB MAD 0.0000), yet the drifted tracker scored frame
0 at 0.930 silhouette and frames 22-29 at 0.78-0.79 against that same image.

An identical plate has an identical best pose. So the pose already found for an
earlier copy of a plate is a legitimate warm start for the current one -- usually a
far better one than the drifted previous frame. The tracker offers it as a
*candidate* and lets the shared cost function choose, so a mistaken match loses on
measurement instead of being trusted.

Loop seams
----------
The same identity check tells us whether a clip is a cycle. If the last plate
equals the first, the pose at the seam must also match, or the animation pops when
it wraps. ``loop_seam_report`` measures that directly rather than assuming it.

Proof tier: source/static measurement over generated sprite plates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

ALPHA_THRESHOLD = 8


@dataclass(frozen=True)
class PlateDistance:
    """How far apart two sprite plates are, in the space the solver scores."""

    alpha_iou: float
    rgb_mad: float

    def matches(self, *, max_rgb_mad: float, min_alpha_iou: float) -> bool:
        return (
            float(self.rgb_mad) <= float(max_rgb_mad)
            and float(self.alpha_iou) >= float(min_alpha_iou)
        )


def plate_distance(
    rgb_a: np.ndarray,
    alpha_a: np.ndarray,
    rgb_b: np.ndarray,
    alpha_b: np.ndarray,
) -> PlateDistance:
    """Compare two plates by silhouette overlap and colour difference.

    Both channels are needed. Alpha IoU alone cannot tell a bird facing left from one
    facing right with the same outline; RGB difference alone is dominated by the
    shared empty background unless it is restricted to the union of the two
    silhouettes, which is what happens here.

    Inputs must be in **0..255**, matching ``_raster_frames`` and every other DEF
    plate reader in this lane. Guessing the scale from the data would silently turn a
    dim 0..255 plate into a 0..1 one and report a 255x smaller difference, which for
    an identity test means declaring unrelated plates identical.
    """
    mask_a = np.asarray(alpha_a) > ALPHA_THRESHOLD
    mask_b = np.asarray(alpha_b) > ALPHA_THRESHOLD
    union = mask_a | mask_b
    union_count = int(union.sum())
    if union_count == 0:
        raise ValueError(
            "both plates read as empty; if these are 0..1 normalised images, convert "
            "to 0..255 first rather than lowering ALPHA_THRESHOLD"
        )
    intersection = int((mask_a & mask_b).sum())
    left = np.asarray(rgb_a, dtype=np.float32)
    right = np.asarray(rgb_b, dtype=np.float32)
    if left.shape != right.shape:
        raise ValueError(f"plate shapes differ: {left.shape} vs {right.shape}")
    difference = np.abs(left - right).mean(axis=-1)[union]
    return PlateDistance(
        alpha_iou=float(intersection) / float(union_count),
        rgb_mad=float(difference.mean()) / 255.0,
    )


def earlier_plate_matches(
    rgbs: Sequence[np.ndarray],
    alphas: Sequence[np.ndarray],
    *,
    max_rgb_mad: float,
    min_alpha_iou: float,
) -> dict[int, list[tuple[int, PlateDistance]]]:
    """For each frame position, every *earlier* position whose plate is the same.

    Only earlier positions, because a sequential tracker can only reuse a pose it
    has already solved. Sorted closest-first.
    """
    if len(rgbs) != len(alphas):
        raise ValueError("rgb and alpha sequences must be the same length")
    matches: dict[int, list[tuple[int, PlateDistance]]] = {}
    for position in range(1, len(rgbs)):
        found: list[tuple[int, PlateDistance]] = []
        for earlier in range(position):
            distance = plate_distance(
                rgbs[position], alphas[position], rgbs[earlier], alphas[earlier]
            )
            if distance.matches(max_rgb_mad=max_rgb_mad, min_alpha_iou=min_alpha_iou):
                found.append((earlier, distance))
        found.sort(key=lambda entry: (entry[1].rgb_mad, -entry[1].alpha_iou))
        if found:
            matches[position] = found
    return matches


def _rotation_matrices(rotation_vectors: Any):
    """Rodrigues' formula, batched over the leading dimensions."""
    import torch

    vectors = torch.as_tensor(rotation_vectors, dtype=torch.float64)
    angle = torch.linalg.vector_norm(vectors, dim=-1, keepdim=True)
    axis = vectors / angle.clamp_min(1e-12)
    x, y, z = axis[..., 0], axis[..., 1], axis[..., 2]
    zero = torch.zeros_like(x)
    skew = torch.stack(
        (
            torch.stack((zero, -z, y), dim=-1),
            torch.stack((z, zero, -x), dim=-1),
            torch.stack((-y, x, zero), dim=-1),
        ),
        dim=-2,
    )
    sin = torch.sin(angle).unsqueeze(-1)
    cos = torch.cos(angle).unsqueeze(-1)
    identity = torch.eye(3, dtype=vectors.dtype, device=vectors.device).expand_as(skew)
    return identity + sin * skew + (1.0 - cos) * (skew @ skew)


def bone_delta_degrees(bones_a: Any, bones_b: Any) -> tuple[float, float]:
    """Mean and max per-bone rotation difference in degrees between two poses.

    Uses the geodesic angle between the two orientations, not the Euclidean distance
    between their rotation vectors. Those disagree badly near the half-turn boundary:
    rotation vectors of +150 deg and -150 deg about the same axis are 300 deg apart as
    vectors while the orientations differ by only 60 deg. Measuring in vector space
    reported a 324 deg single-frame "jump" on the roc clip, which is not even a
    possible orientation change -- the geodesic distance is bounded by 180 deg.
    """
    import torch

    left = _rotation_matrices(bones_a)
    right = _rotation_matrices(bones_b)
    relative = left.transpose(-1, -2) @ right
    trace = relative[..., 0, 0] + relative[..., 1, 1] + relative[..., 2, 2]
    cosine = ((trace - 1.0) * 0.5).clamp(-1.0, 1.0)
    degrees = torch.rad2deg(torch.arccos(cosine))
    return float(degrees.mean().item()), float(degrees.max().item())


def loop_seam_report(
    *,
    rgbs: Sequence[np.ndarray],
    alphas: Sequence[np.ndarray],
    bones: Any,
    root_translation: Any,
    root_rotation: Any,
) -> dict[str, Any]:
    """Measure whether the clip wraps cleanly from its last frame back to its first.

    ``seamPopRatio`` compares the seam's pose change against the mean interior
    frame-to-frame change. A cycle whose first and last plates are identical should
    show a seam far *smaller* than a typical interior step; a ratio above 1 means the
    wrap moves more than an ordinary frame does and will read as a pop.
    """
    count = int(len(rgbs))
    if count < 3:
        raise ValueError("a loop seam needs at least three frames to have an interior")
    seam_plate = plate_distance(rgbs[-1], alphas[-1], rgbs[0], alphas[0])
    seam_mean, seam_max = bone_delta_degrees(bones[-1], bones[0])

    interior_means: list[float] = []
    interior_maxes: list[float] = []
    for position in range(1, count):
        mean_delta, max_delta = bone_delta_degrees(bones[position], bones[position - 1])
        interior_means.append(mean_delta)
        interior_maxes.append(max_delta)
    interior_mean = float(np.mean(interior_means))

    import torch

    translation_delta = float(
        torch.linalg.vector_norm(
            torch.as_tensor(root_translation[-1]) - torch.as_tensor(root_translation[0])
        ).item()
    )
    rotation_mean, rotation_max = bone_delta_degrees(
        torch.as_tensor(root_rotation[-1]).reshape(1, -1),
        torch.as_tensor(root_rotation[0]).reshape(1, -1),
    )
    return {
        "plateIdentical": bool(
            seam_plate.matches(max_rgb_mad=1e-4, min_alpha_iou=0.9999)
        ),
        "plateAlphaIou": round(float(seam_plate.alpha_iou), 5),
        "plateRgbMad": round(float(seam_plate.rgb_mad), 5),
        "seamMeanBoneDeltaDeg": round(seam_mean, 3),
        "seamMaxBoneDeltaDeg": round(seam_max, 3),
        "interiorMeanBoneDeltaDeg": round(interior_mean, 3),
        "interiorMaxBoneDeltaDeg": round(float(np.max(interior_maxes)), 3),
        "seamPopRatio": (
            None if interior_mean <= 0.0 else round(seam_mean / interior_mean, 3)
        ),
        "seamRootTranslationDelta": round(translation_delta, 5),
        "seamRootRotationDeltaDeg": round(rotation_max, 3),
    }
