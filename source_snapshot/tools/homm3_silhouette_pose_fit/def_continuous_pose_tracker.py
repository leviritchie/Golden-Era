#!/usr/bin/env python3
"""Continuous DEF-native pose tracking: no per-frame landmark locking.

Why this exists
---------------
The articulation-centroid and texture-anchor lanes both *lock a point* per frame:
each frame independently re-decides "the wing tip is at (x, y)", then prop IK is
asked to reach that point. Independent per-frame detection is unstable by
construction -- the detector has no memory, so its answer jitters, and the IK
either chases the jitter or (with an aggregate-improvement gate) rejects every
step.

This module removes the landmark representation entirely. The only state is the
pose. Frame i is solved by warm-starting from the *solved* pose of frame i-1 and
pushing it with measured image motion:

    target_s(i) = project(pose_{i-1}, sample_s) + flow_{i-1->i}( project(pose_{i-1}, sample_s) )

A "target" is therefore never detected -- it is where the model surface already
was, displaced by optical flow. Correspondence is free because the tracked
points are fixed barycentric samples on fixed mesh triangles, so sample ``s`` is
the same material point in every frame.

Tracked points are mesh SURFACE samples, not bone joint centres
--------------------------------------------------------------
A first version of this tracker sampled flow at projected bone joint positions
and produced a null result: mean flow residual of 0.05 px, essentially no motion
signal at all. Root cause: joint centres project into the *interior* of the
sprite, and the interior of a flat-shaded HoMM3 creature has almost no image
gradient, so dense optical flow there is ~0 by construction. Optical flow only
carries information where the image has structure -- silhouette edges, feather
and armour detail, colour boundaries. Surface samples spread over the whole
projected mesh do land on those places, so that is what this module tracks.

Energy minimised per frame (all terms in raster pixels):

    E = flow_weight   * mean_s w_s * || P_s - target_s ||^2       (continuous motion)
      + inside_weight * mean_all relu(D_out(P))^2                 (absolute anchor, kills drift)
      + smooth_weight * mean_s || P_s - P_s(pose_{i-1}) ||^2      (jitter damping)

``D_out`` is the distance transform outside the frame's own alpha mask, applied
to every surface sample, so the posed mesh is continuously pulled back inside the
authentic sprite silhouette. That term is what stops pure flow integration from
drifting away across 30 frames; without it this lane would be a dead end.

``w_s`` is a per-sample trust weight: zero unless the sample sat inside the
previous frame's silhouette AND on locally structured image content, then scaled
down where the local flow field disagrees with itself (ambiguous or occluded
regions).

Solver is batched steepest descent on the existing rotate-only primitive
(``offset_raw_bone_direction``). Rotate-only plus small frame-to-frame motion is
why this works where the earlier bind->frame_N dense visual servoing failed:
that attempt linearised large rotations, this one only ever takes small steps
between adjacent frames.

Proof tier: generated artifact. Not OE battle runtime.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from def_mocap_bootstrap import bootstrap_flow_mocap_experiment  # noqa: E402
from def_anatomy_limits import (  # noqa: E402
    bone_limit_overrides_from_anatomy_order,
    node_names_from_mesh,
)
from def_plate_identity import (  # noqa: E402
    _rotation_matrices,
    earlier_plate_matches,
    loop_seam_report,
)
from gpu_mesh_collision import (  # noqa: E402
    build_backend_collision_table,
    penetration_norm_from_table,
)
from literature_polish_common import (  # noqa: E402
    assert_write_path,
    poses_from_tensors,
    raster_literature_preview,
    rescore_tensors,
    unit_mesh,
    write_polished_clip,
)
from preview_timing import PREVIEW_GIF_FRAME_MS  # noqa: E402
from roc_gpu_cascade_experiment import offset_raw_bone_direction  # noqa: E402

ALPHA_THRESHOLD = 8

# Six cardinal rotation-vector probes. The full 18-axis set used by prop IK buys
# little here because every accepted step is small and descent re-probes from the
# new pose, so diagonals are reachable as two cardinal steps.
CARDINAL_PROBE_AXES: tuple[tuple[float, float, float], ...] = (
    (1.0, 0.0, 0.0),
    (-1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, -1.0, 0.0),
    (0.0, 0.0, 1.0),
    (0.0, 0.0, -1.0),
)

DIAGONAL_PROBE_AXES: tuple[tuple[float, float, float], ...] = CARDINAL_PROBE_AXES + (
    (1.0, 1.0, 0.0),
    (1.0, -1.0, 0.0),
    (-1.0, 1.0, 0.0),
    (-1.0, -1.0, 0.0),
    (1.0, 0.0, 1.0),
    (-1.0, 0.0, -1.0),
    (0.0, 1.0, 1.0),
    (0.0, -1.0, -1.0),
)


@dataclass(frozen=True)
class ContinuousTrackConfig:
    """Weights are relative; every energy term is in squared raster px."""

    flow_weight: float = 1.0
    inside_weight: float = 0.30
    smooth_weight: float = 0.05
    # Matches the projected sample cloud's centroid and 2D spread to the sprite
    # alpha's. Measured to be the wrong anchor: a surface-sample cloud and a
    # filled silhouette have systematically different second moments (thin wings
    # contribute lots of surface area but little silhouette), so minimising the
    # difference has a large irreducible bias and trades away flow accuracy.
    # Default off; retained only so the effect stays inspectable.
    moment_weight: float = 0.0
    step_schedule_deg: tuple[float, ...] = (5.0, 2.0)
    max_accepted_steps: int = 20
    min_energy_gain: float = 5e-4
    # Local flow disagreement (px) at which a sample's target is half-trusted.
    flow_coherence_scale_px: float = 1.5
    # Keep only surface samples landing on the most structured image content;
    # flat interior regions carry no optical-flow information.
    structure_percentile: float = 70.0
    max_track_samples: int = 1200
    min_track_samples: int = 40
    probe_axes: tuple[tuple[float, float, float], ...] = CARDINAL_PROBE_AXES
    # Whole-body attitude and position. A take-off or turn clip is dominated by
    # rigid body motion; without these the solver can only fake it by contorting
    # the skeleton, which destroys the silhouette.
    track_root_rotation: bool = True
    track_root_translation: bool = True
    # Ties root translation granularity to the same annealing schedule as the
    # angular steps, so one schedule controls the whole descent.
    root_translation_step_per_deg: float = 0.004
    # Correction stage: rasterised silhouette agreement with this frame's sprite.
    # Flow is only a prediction; the sprite is the measurement, which is what
    # keeps the track from drifting away from the artwork.
    correct_step_schedule_deg: tuple[float, ...] = (4.0, 2.0, 1.0)
    correct_max_accepted_steps: int = 24
    correct_min_score_gain: float = 2e-4
    # Frame 0 has no previous frame to predict from, so it is corrected alone
    # with a larger budget. Flow advection is only meaningful once the model
    # actually sits on the sprite, so this seed pass is a precondition.
    seed_step_schedule_deg: tuple[float, ...] = (8.0, 4.0, 2.0, 1.0)
    seed_max_accepted_steps: int = 60
    # Silhouette agreement alone rewards hiding a body part inside the body: the
    # covered pixels stay covered, and an outline bump the sprite lacks disappears.
    # Unpenalised, this lane drove the roc's head through its own wing on most
    # frames. Weight multiplies the unsaturated penetration norm (units of
    # collision margin), which is *not* the cascade's tanh collision scale.
    #
    # 0.05 is calibrated, not guessed: measured on h3_roc/idle_start_move_end the
    # norm is exactly 0.0 at bind and spans 0.24..2.27 across the unguarded solve,
    # so the worst frame carries ~0.11 of cost against silhouette scores near 0.8 --
    # decisive against burying a part, without swamping the fit. Step-level
    # discrimination also stays above correct_min_score_gain.
    penetration_weight: float = 0.05
    penetration_sample_count: int = 512
    penetration_margin_body_lengths: float = 0.04
    # Sequential tracking accumulates error with nothing to pull it back. HoMM3 DEF
    # idle sections repeat plates exactly, which both exposes the drift and supplies
    # the cure: an identical plate has an identical best pose, so the pose solved for
    # an earlier copy is a better warm start than the drifted previous frame.
    # Offered as a *candidate* only -- the shared cost decides -- so a wrong match
    # loses on measurement rather than being trusted.
    plate_anchor_enabled: bool = True
    # Tight on purpose: this is plate *identity*, not plate similarity. Measured on
    # h3_roc idle_start_move_end, exact repeats sit at RGB MAD 0.0000 / IoU 1.0000
    # while adjacent idle frames already reach 0.0063 / 0.9958.
    plate_anchor_max_rgb_mad: float = 0.004
    plate_anchor_min_alpha_iou: float = 0.999
    # The correction stage fits one frame's outline with no reference to the previous
    # frame, so it is free to land on a mirrored solution that scores the same. A
    # roughly planar wing looks similar rotated +theta or -theta, and the search hops
    # between those between frames: measured single-frame joint changes reached 110
    # deg with a flat limit and 178 deg once authored limits pushed the search into
    # the wings, against a 2-3 deg per-frame average. Nothing in the objective
    # objected, because both poses match the sprite equally well.
    #
    # Penalises each joint's geodesic rotation change beyond a free allowance, so
    # ordinary 12 fps motion is unpenalised while a half-turn flip is not. Genuine
    # large motion still wins when it is worth enough silhouette: the f21->f22 idle
    # snap gains ~0.41 of cost, far more than this term charges.
    temporal_weight: float = 0.30
    temporal_free_deg: float = 25.0


def cheap_track_config() -> ContinuousTrackConfig:
    """Fast review pass: cardinal probes, two step levels, few accepted steps."""
    return ContinuousTrackConfig()


def quality_track_config() -> ContinuousTrackConfig:
    return ContinuousTrackConfig(
        step_schedule_deg=(6.0, 3.0, 1.5, 0.75),
        max_accepted_steps=48,
        max_track_samples=2400,
        probe_axes=DIAGONAL_PROBE_AXES,
    )


def _raster_frames(
    frame_dir: Path,
    frame_indices: Sequence[int],
    raster: tuple[int, int],
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Load DEF frames resampled to the solver raster so flow and projection share one space."""
    width, height = int(raster[0]), int(raster[1])
    rgbs: list[np.ndarray] = []
    alphas: list[np.ndarray] = []
    for index in frame_indices:
        path = frame_dir / f"{int(index):02d}.png"
        if not path.is_file():
            path = frame_dir / f"{int(index)}.png"
        if not path.is_file():
            raise FileNotFoundError(f"missing DEF frame {index} under {frame_dir}")
        image = Image.open(path).convert("RGBA").resize((width, height), Image.Resampling.LANCZOS)
        rgba = np.asarray(image)
        rgbs.append(np.ascontiguousarray(rgba[..., :3]))
        alphas.append(np.ascontiguousarray(rgba[..., 3]))
    return rgbs, alphas


def _dense_flow(
    rgb_a: np.ndarray,
    rgb_b: np.ndarray,
    alpha_a: np.ndarray,
    alpha_b: np.ndarray,
) -> np.ndarray:
    gray_a = cv2.cvtColor(rgb_a, cv2.COLOR_RGB2GRAY)
    gray_b = cv2.cvtColor(rgb_b, cv2.COLOR_RGB2GRAY)
    flow = cv2.calcOpticalFlowFarneback(
        gray_a, gray_b, None,
        pyr_scale=0.5, levels=4, winsize=15, iterations=4,
        poly_n=5, poly_sigma=1.2, flags=0,
    )
    union = (alpha_a >= ALPHA_THRESHOLD) | (alpha_b >= ALPHA_THRESHOLD)
    flow[~union] = 0.0
    return flow.astype(np.float32)


def _structure_magnitude(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Sobel gradient magnitude, with the alpha boundary treated as structure.

    Silhouette edges are the strongest motion cue on flat-shaded HoMM3 sprites,
    but an interior-only gradient misses them because the sprite is composited on
    transparent black. Folding in the alpha gradient keeps outline samples.
    """
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    alpha_f = alpha.astype(np.float32)
    magnitude = np.zeros_like(gray)
    for channel in (gray, alpha_f):
        dx = cv2.Sobel(channel, cv2.CV_32F, 1, 0, ksize=3)
        dy = cv2.Sobel(channel, cv2.CV_32F, 0, 1, ksize=3)
        magnitude = np.maximum(magnitude, cv2.magnitude(dx, dy))
    return magnitude.astype(np.float32)


def _flow_local_disagreement(flow: np.ndarray, ksize: int = 5) -> np.ndarray:
    """Per-pixel std of the flow field in a small window (ambiguity proxy)."""
    mean = cv2.blur(flow, (ksize, ksize))
    mean_sq = cv2.blur(flow * flow, (ksize, ksize))
    variance = np.clip(mean_sq - mean * mean, 0.0, None)
    return np.sqrt(variance.sum(axis=2)).astype(np.float32)


def _outside_distance(alpha: np.ndarray) -> np.ndarray:
    """0 inside the sprite, growing euclidean px distance outside it."""
    inside = (alpha >= ALPHA_THRESHOLD).astype(np.uint8)
    if not int(inside.max()):
        raise ValueError("DEF frame alpha is empty; cannot anchor tracking to a silhouette")
    outside = (1 - inside).astype(np.uint8)
    return cv2.distanceTransform(outside, cv2.DIST_L2, 3).astype(np.float32)


def _alpha_moments(alpha: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Centroid [2] and covariance [xx, yy, xy] of the sprite's occupied pixels, in px."""
    mask = (alpha >= ALPHA_THRESHOLD).astype(np.float32)
    total = float(mask.sum())
    if total <= 0.0:
        raise ValueError("DEF frame alpha is empty; cannot measure silhouette moments")
    height, width = alpha.shape
    ys, xs = np.mgrid[0:height, 0:width]
    xs = xs.astype(np.float32)
    ys = ys.astype(np.float32)
    centroid_x = float((mask * xs).sum() / total)
    centroid_y = float((mask * ys).sum() / total)
    dx = xs - centroid_x
    dy = ys - centroid_y
    covariance = np.asarray(
        [
            float((mask * dx * dx).sum() / total),
            float((mask * dy * dy).sum() / total),
            float((mask * dx * dy).sum() / total),
        ],
        dtype=np.float32,
    )
    return np.asarray([centroid_x, centroid_y], dtype=np.float32), covariance


def _sample_bilinear(field: np.ndarray, xy: np.ndarray) -> np.ndarray:
    """Bilinear sample of an [H, W] or [H, W, C] field at float [K, 2] xy points."""
    height, width = field.shape[:2]
    x = np.clip(xy[:, 0], 0.0, width - 1.0)
    y = np.clip(xy[:, 1], 0.0, height - 1.0)
    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    x1 = np.clip(x0 + 1, 0, width - 1)
    y1 = np.clip(y0 + 1, 0, height - 1)
    fx = (x - x0)[:, None] if field.ndim == 3 else (x - x0)
    fy = (y - y0)[:, None] if field.ndim == 3 else (y - y0)
    top = field[y0, x0] * (1.0 - fx) + field[y0, x1] * fx
    bottom = field[y1, x0] * (1.0 - fx) + field[y1, x1] * fx
    return top * (1.0 - fy) + bottom * fy


class _SurfaceEnergy:
    """Continuous per-frame energy over projected mesh surface samples."""

    def __init__(
        self,
        experiment: Any,
        *,
        raster: tuple[int, int],
        config: ContinuousTrackConfig,
    ) -> None:
        self._experiment = experiment
        self._config = config
        self._width, self._height = int(raster[0]), int(raster[1])
        self._device = experiment.bone_limit_scales.device
        self._indices: torch.Tensor | None = None
        self._targets: torch.Tensor | None = None
        self._weights: torch.Tensor | None = None
        self._weight_sum: float = 0.0
        self._previous: torch.Tensor | None = None
        self._distance_map: torch.Tensor | None = None
        self._sprite_centroid: torch.Tensor | None = None
        self._sprite_covariance: torch.Tensor | None = None

    def project(
        self,
        raws: torch.Tensor,
        root_translation: torch.Tensor,
        root_rotation: torch.Tensor,
    ) -> torch.Tensor:
        """Projected surface sample positions, [B, S, 2] in raster px."""
        with torch.no_grad():
            return self._experiment.render_points(
                self._experiment._bounded_bone_vectors(raws),
                root_translation,
                root_rotation,
                bone_mask=self._experiment.active_node_mask,
            )

    def set_frame(
        self,
        *,
        sample_indices: np.ndarray,
        targets_xy: np.ndarray,
        weights: np.ndarray,
        previous_xy: np.ndarray,
        outside_distance: np.ndarray,
        sprite_centroid: np.ndarray,
        sprite_covariance: np.ndarray,
    ) -> None:
        self._indices = torch.as_tensor(sample_indices, dtype=torch.long, device=self._device)
        self._targets = torch.as_tensor(targets_xy, dtype=torch.float32, device=self._device)
        self._weights = torch.as_tensor(weights, dtype=torch.float32, device=self._device)
        self._weight_sum = float(self._weights.sum().item())
        if self._weight_sum <= 0.0:
            raise ValueError("no surface sample carries a trusted flow measurement for this frame")
        self._previous = torch.as_tensor(previous_xy, dtype=torch.float32, device=self._device)
        self._distance_map = torch.as_tensor(
            outside_distance, dtype=torch.float32, device=self._device
        ).reshape(1, 1, self._height, self._width)
        self._sprite_centroid = torch.as_tensor(
            sprite_centroid, dtype=torch.float32, device=self._device
        )
        self._sprite_covariance = torch.as_tensor(
            sprite_covariance, dtype=torch.float32, device=self._device
        )

    def _moment_penalty(self, points: torch.Tensor) -> torch.Tensor:
        """Squared-px disagreement between the sample cloud's shape and the sprite's."""
        centroid = points.mean(dim=1)
        centered = points - centroid.unsqueeze(1)
        covariance = torch.stack(
            (
                (centered[..., 0] * centered[..., 0]).mean(dim=1),
                (centered[..., 1] * centered[..., 1]).mean(dim=1),
                (centered[..., 0] * centered[..., 1]).mean(dim=1),
            ),
            dim=-1,
        )
        centroid_error = (centroid - self._sprite_centroid.unsqueeze(0)).pow(2).sum(-1)
        difference = covariance - self._sprite_covariance.unsqueeze(0)
        # Frobenius norm of the 2x2 covariance difference; the off-diagonal is
        # counted twice because the matrix is symmetric. Units are px^2, matching
        # the squared-px centroid error and the other energy terms.
        spread_error = torch.sqrt(
            difference[..., 0].pow(2)
            + difference[..., 1].pow(2)
            + 2.0 * difference[..., 2].pow(2)
            + 1e-12
        )
        return centroid_error + spread_error

    def _outside_penalty(self, points: torch.Tensor) -> torch.Tensor:
        batch = int(points.shape[0])
        grid_x = 2.0 * points[..., 0] / max(self._width - 1, 1) - 1.0
        grid_y = 2.0 * points[..., 1] / max(self._height - 1, 1) - 1.0
        grid = torch.stack((grid_x, grid_y), dim=-1).unsqueeze(1)
        sampled = F.grid_sample(
            self._distance_map.expand(batch, -1, -1, -1),
            grid,
            mode="bilinear",
            padding_mode="border",
            align_corners=True,
        ).reshape(batch, -1)
        # grid_sample clamps at the border, so distance for samples projected off
        # frame is added explicitly instead of silently saturating.
        over_x = torch.relu(-points[..., 0]) + torch.relu(points[..., 0] - (self._width - 1))
        over_y = torch.relu(-points[..., 1]) + torch.relu(points[..., 1] - (self._height - 1))
        return sampled + torch.sqrt(over_x * over_x + over_y * over_y + 1e-12)

    def evaluate(
        self,
        raws: torch.Tensor,
        root_translation: torch.Tensor,
        root_rotation: torch.Tensor,
    ) -> torch.Tensor:
        if self._indices is None or self._targets is None or self._distance_map is None:
            raise RuntimeError("_SurfaceEnergy.set_frame must run before evaluate")
        points = self.project(raws, root_translation, root_rotation)
        tracked = points[:, self._indices, :]

        residual = tracked - self._targets.unsqueeze(0)
        flow_term = (self._weights.unsqueeze(0) * (residual * residual).sum(-1)).sum(-1)
        flow_term = flow_term / self._weight_sum

        drift = tracked - self._previous.unsqueeze(0)
        smooth_term = (drift * drift).sum(-1).mean(-1)

        outside = self._outside_penalty(points)
        inside_term = (outside * outside).mean(-1)
        moment_term = self._moment_penalty(points)

        return (
            float(self._config.flow_weight) * flow_term
            + float(self._config.inside_weight) * inside_term
            + float(self._config.smooth_weight) * smooth_term
            + float(self._config.moment_weight) * moment_term
        )

    def term_breakdown(
        self,
        raws: torch.Tensor,
        root_translation: torch.Tensor,
        root_rotation: torch.Tensor,
    ) -> dict[str, float]:
        """Unweighted per-term values for one pose, so a solve can be inspected."""
        points = self.project(raws, root_translation, root_rotation)
        tracked = points[:, self._indices, :]
        residual = tracked - self._targets.unsqueeze(0)
        flow_term = float(
            (
                (self._weights.unsqueeze(0) * (residual * residual).sum(-1)).sum(-1)
                / self._weight_sum
            )[0].item()
        )
        drift = tracked - self._previous.unsqueeze(0)
        outside = self._outside_penalty(points)
        return {
            "flowPx2": round(flow_term, 4),
            "insidePx2": round(float((outside * outside).mean(-1)[0].item()), 4),
            "smoothPx2": round(float((drift * drift).sum(-1).mean(-1)[0].item()), 4),
            "momentPx2": round(float(self._moment_penalty(points)[0].item()), 4),
        }

    def flow_residual_px(
        self,
        raws: torch.Tensor,
        root_translation: torch.Tensor,
        root_rotation: torch.Tensor,
    ) -> float:
        """Trust-weighted mean L2 px between tracked samples and their flow-advected targets."""
        tracked = self.project(raws, root_translation, root_rotation)[0, self._indices, :]
        distance = torch.linalg.vector_norm(tracked - self._targets, dim=-1)
        return float(((self._weights * distance).sum() / self._weight_sum).item())


def _select_tracked_samples(
    previous_xy: np.ndarray,
    *,
    alpha_previous: np.ndarray,
    structure: np.ndarray,
    flow: np.ndarray,
    disagreement: np.ndarray,
    config: ContinuousTrackConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pick surface samples whose flow measurement is trustworthy this frame."""
    alpha_at = _sample_bilinear(alpha_previous.astype(np.float32), previous_xy)
    structure_at = _sample_bilinear(structure, previous_xy)
    disagreement_at = _sample_bilinear(disagreement, previous_xy)
    flow_at = _sample_bilinear(flow, previous_xy)

    inside = alpha_at >= float(ALPHA_THRESHOLD)
    if not bool(inside.any()):
        raise RuntimeError(
            "no surface sample projects inside the previous DEF silhouette; the seed pose or "
            "camera fit is wrong, so continuous tracking has nothing to measure"
        )
    floor = float(np.percentile(structure_at[inside], float(config.structure_percentile)))
    trusted = inside & (structure_at >= floor)
    candidates = np.flatnonzero(trusted)
    if candidates.size < int(config.min_track_samples):
        raise RuntimeError(
            f"only {candidates.size} surface samples landed on structured content inside the "
            f"previous silhouette (need {config.min_track_samples}); lower structure_percentile "
            "or check the camera fit"
        )

    weights = 1.0 / (1.0 + disagreement_at[candidates] / float(config.flow_coherence_scale_px))
    if candidates.size > int(config.max_track_samples):
        keep = np.argsort(-weights)[: int(config.max_track_samples)]
        candidates = candidates[keep]
        weights = weights[keep]

    targets = previous_xy[candidates] + flow_at[candidates]
    return candidates.astype(np.int64), targets.astype(np.float32), weights.astype(np.float32)


def _root_rotation_offset(
    experiment: Any,
    raw_rotation: torch.Tensor,
    *,
    axis_index: int,
    delta_rad: float,
) -> torch.Tensor:
    """Step one root rotation axis by ``delta_rad``, re-encoded through its bounded envelope."""
    radians_values = experiment._bounded_root_rotation(raw_rotation)[0].detach().cpu().numpy()
    updated = float(radians_values[int(axis_index)]) + float(delta_rad)
    raw_axis = float(
        experiment._root_rotation_raw_inverse(
            np.asarray([updated], dtype=np.float64), axis_index=int(axis_index)
        )[0]
    )
    result = raw_rotation.detach().clone()
    result[0, int(axis_index)] = raw_axis
    return result


def _root_translation_offset(
    experiment: Any,
    raw_translation: torch.Tensor,
    *,
    axis_index: int,
    delta_body_lengths: float,
) -> torch.Tensor:
    """Step one root translation axis, re-encoded through the tanh body-length limit."""
    limit = float(experiment.config.root_translation_limit_body_lengths)
    current = float(torch.tanh(raw_translation)[0, int(axis_index)].item()) * limit
    ratio = float(np.clip((current + float(delta_body_lengths)) / limit, -0.999, 0.999))
    result = raw_translation.detach().clone()
    result[0, int(axis_index)] = float(np.arctanh(ratio))
    return result


def _active_axis_indices(mask: torch.Tensor) -> list[int]:
    return [index for index in range(int(mask.numel())) if float(mask[index].item()) > 0.0]


def _build_trials(
    experiment: Any,
    *,
    bones: torch.Tensor,
    root_translation: torch.Tensor,
    root_rotation: torch.Tensor,
    bone_indices: Sequence[int],
    probe_axes: Sequence[tuple[float, float, float]],
    rotation_axes: Sequence[int],
    translation_axes: Sequence[int],
    step_deg: float,
    translation_step: float,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, list[bool]]:
    """One candidate per (bone, axis) plus one per signed root DOF, as stacked batches."""
    joint_limit_rad = math.radians(float(experiment.config.joint_limit_deg))
    step_rad = math.radians(float(step_deg))
    bone_trials: list[torch.Tensor] = []
    root_t_trials: list[torch.Tensor] = []
    root_r_trials: list[torch.Tensor] = []
    is_root: list[bool] = []

    for bone_index in bone_indices:
        for axis in probe_axes:
            bone_trials.append(
                offset_raw_bone_direction(
                    bones.unsqueeze(0),
                    bone_index=int(bone_index),
                    direction=axis,
                    delta_rad=step_rad,
                    joint_limit_rad=joint_limit_rad,
                    bone_limit_scales=experiment.bone_limit_scales,
                )[0]
            )
            root_t_trials.append(root_translation[0])
            root_r_trials.append(root_rotation[0])
            is_root.append(False)

    for axis_index in rotation_axes:
        for sign in (-1.0, 1.0):
            bone_trials.append(bones)
            root_t_trials.append(root_translation[0])
            root_r_trials.append(
                _root_rotation_offset(
                    experiment, root_rotation, axis_index=axis_index, delta_rad=sign * step_rad
                )[0]
            )
            is_root.append(True)

    for axis_index in translation_axes:
        for sign in (-1.0, 1.0):
            bone_trials.append(bones)
            root_t_trials.append(
                _root_translation_offset(
                    experiment,
                    root_translation,
                    axis_index=axis_index,
                    delta_body_lengths=sign * float(translation_step),
                )[0]
            )
            root_r_trials.append(root_rotation[0])
            is_root.append(True)

    return (
        torch.stack(bone_trials, dim=0),
        torch.stack(root_t_trials, dim=0),
        torch.stack(root_r_trials, dim=0),
        is_root,
    )


def silhouette_scores(
    experiment: Any,
    bones: torch.Tensor,
    root_translation: torch.Tensor,
    root_rotation: torch.Tensor,
    *,
    frame_index: int,
) -> torch.Tensor:
    """Rasterised silhouette score for every candidate pose against one target frame.

    ``evaluate`` normally maps its batch dimension onto clip frames. Passing a
    single ``frame_indices`` entry makes it broadcast that one target across the
    whole batch, which is how many hypotheses are scored per GPU launch.
    """
    slots = max(1, int(experiment.config.joint_score_raster_batch))
    chunks: list[torch.Tensor] = []
    for start in range(0, int(bones.shape[0]), slots):
        stop = start + slots
        with torch.no_grad():
            packed = experiment.evaluate(
                experiment._bounded_bone_vectors(bones[start:stop]),
                root_translation[start:stop],
                root_rotation[start:stop],
                frame_indices=(int(frame_index),),
                bone_mask=experiment.active_node_mask,
            )
        chunks.append(packed["score"].detach().reshape(-1))
    return torch.cat(chunks, dim=0)


def _descend(
    experiment: Any,
    *,
    objective: Any,
    bones: torch.Tensor,
    root_translation: torch.Tensor,
    root_rotation: torch.Tensor,
    bone_indices: Sequence[int],
    probe_axes: Sequence[tuple[float, float, float]],
    rotation_axes: Sequence[int],
    translation_axes: Sequence[int],
    step_schedule_deg: Sequence[float],
    translation_step_per_deg: float,
    max_accepted_steps: int,
    min_gain: float,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, dict[str, Any]]:
    """Batched steepest descent on ``objective`` over bone rotations and root DOFs."""
    current_bones = bones.detach().clone()
    current_root_t = root_translation.detach().clone()
    current_root_r = root_rotation.detach().clone()
    current = float(
        objective(current_bones.unsqueeze(0), current_root_t, current_root_r)[0].item()
    )
    opening = current
    accepted = 0
    accepted_root = 0

    for step_deg in step_schedule_deg:
        while accepted < int(max_accepted_steps):
            bone_batch, root_t_batch, root_r_batch, is_root = _build_trials(
                experiment,
                bones=current_bones,
                root_translation=current_root_t,
                root_rotation=current_root_r,
                bone_indices=bone_indices,
                probe_axes=probe_axes,
                rotation_axes=rotation_axes,
                translation_axes=translation_axes,
                step_deg=float(step_deg),
                translation_step=float(translation_step_per_deg) * float(step_deg),
            )
            values = objective(bone_batch, root_t_batch, root_r_batch)
            best = int(torch.argmin(values).item())
            best_value = float(values[best].item())
            if current - best_value < float(min_gain):
                break
            current_bones = bone_batch[best].detach().clone()
            current_root_t = root_t_batch[best].detach().clone().unsqueeze(0)
            current_root_r = root_r_batch[best].detach().clone().unsqueeze(0)
            current = best_value
            accepted += 1
            if is_root[best]:
                accepted_root += 1

    return current_bones, current_root_t, current_root_r, {
        "objectiveBefore": opening,
        "objectiveAfter": current,
        "acceptedSteps": accepted,
        "acceptedRootSteps": accepted_root,
    }


def track_clip(
    experiment: Any,
    bone_vectors: torch.Tensor,
    root_translation: torch.Tensor,
    root_rotation: torch.Tensor,
    *,
    frame_dir: Path,
    frame_indices: Sequence[int],
    flow_cache_dir: Path,
    config: ContinuousTrackConfig,
    progress: bool = True,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, dict[str, Any]]:
    """Sequentially track every frame from the previous solved pose. Frame 0 keeps its seed.

    Returns tracked bone vectors plus tracked root translation and rotation, since
    whole-body attitude is part of the solved state.
    """
    raster = (int(experiment.config.resolution[0]), int(experiment.config.resolution[1]))
    rgbs, alphas = _raster_frames(frame_dir, frame_indices, raster)
    bone_indices = [int(index) for index in experiment.search_node_indices]
    if not bone_indices:
        raise RuntimeError("experiment exposes no searchable bones to move")

    energy = _SurfaceEnergy(experiment, raster=raster, config=config)
    penetration_table = None
    if float(config.penetration_weight) > 0.0:
        penetration_table = build_backend_collision_table(
            experiment,
            sample_count=int(config.penetration_sample_count),
            geodesic_min_hops=int(experiment.config.collision_geodesic_min_hops),
            margin_body_lengths=float(config.penetration_margin_body_lengths),
        )
        print(
            "continuous track penetration guard: "
            f"samples={penetration_table['report']['sampleCount']} "
            f"pairs={penetration_table['report']['pairCount']} "
            f"margin={float(penetration_table['margin']):.4f} "
            f"weight={float(config.penetration_weight):.3f}",
            flush=True,
        )
    tracked = bone_vectors.detach().clone()
    tracked_root_t = root_translation.detach().clone()
    tracked_root_r = root_rotation.detach().clone()
    flow_cache_dir.mkdir(parents=True, exist_ok=True)

    rotation_axes = (
        _active_axis_indices(experiment.root_rotation_mask)
        if bool(config.track_root_rotation)
        else []
    )
    translation_axes = (
        _active_axis_indices(experiment.root_translation_mask)
        if bool(config.track_root_translation)
        else []
    )

    def _penetration(bones: torch.Tensor) -> torch.Tensor:
        if penetration_table is None:
            return torch.zeros(
                (int(bones.shape[0]),),
                dtype=torch.float32,
                device=experiment.bone_limit_scales.device,
            )
        return penetration_norm_from_table(
            experiment, penetration_table, experiment._bounded_bone_vectors(bones)
        )

    def _temporal_excess(bones: torch.Tensor, reference: torch.Tensor | None) -> torch.Tensor:
        """RMS per-joint rotation change beyond the free allowance, as a 0..1 cost.

        Deliberately an average over joints, not a maximum, even though the defect
        being priced is *one* joint flipping. A maximum was measured and is worse: it
        charges the worst joint at full size, which makes the single large corrective
        jump that a plate anchor needs unaffordable. On h3_roc frame 22 the anchor then
        cost 0.4212 against 0.1480 for drifting onward, so the anchor lost, the idle
        tail stayed at 0.855 instead of 0.93, and the loop seam reopened to a pop ratio
        of 8.6 from 0.11. Suppressing flips and closing the loop are in tension; the
        averaged form is what satisfies both.

        Normalised by 90 degrees so a half-turn-scale excess reads ~1.0 and the weight
        stays interpretable against silhouette cost. Uses geodesic angle, since
        rotation-vector distance overstates changes near the half-turn boundary.
        """
        if reference is None:
            return torch.zeros(
                (int(bones.shape[0]),),
                dtype=torch.float32,
                device=experiment.bone_limit_scales.device,
            )
        current = _rotation_matrices(experiment._bounded_bone_vectors(bones))
        previous = _rotation_matrices(
            experiment._bounded_bone_vectors(reference.unsqueeze(0))
        )
        relative = previous.transpose(-1, -2) @ current
        trace = relative[..., 0, 0] + relative[..., 1, 1] + relative[..., 2, 2]
        degrees = torch.rad2deg(torch.arccos(((trace - 1.0) * 0.5).clamp(-1.0, 1.0)))
        excess = torch.clamp(degrees - float(config.temporal_free_deg), min=0.0)
        return torch.sqrt((excess * excess).mean(dim=-1)).to(torch.float32) / 90.0

    def _frame_cost(
        bones: torch.Tensor,
        root_t: torch.Tensor,
        root_r: torch.Tensor,
        *,
        frame_index: int,
        reference_bones: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """What correction minimises: silhouette disagreement, penetration, and jitter.

        Every accept/reject decision in the clip must read this same number. Judging
        the descent on one objective and the hold-vs-solve choice on another lets a
        rejected pose win the comparison and land in the clip anyway.
        """
        cost = 1.0 - silhouette_scores(
            experiment, bones, root_t, root_r, frame_index=int(frame_index)
        )
        cost = cost + float(config.penetration_weight) * _penetration(bones)
        if float(config.temporal_weight) > 0.0:
            cost = cost + float(config.temporal_weight) * _temporal_excess(
                bones, reference_bones
            )
        return cost

    def _correct(
        bones: torch.Tensor,
        root_t: torch.Tensor,
        root_r: torch.Tensor,
        *,
        frame_index: int,
        schedule: Sequence[float],
        max_steps: int,
        reference_bones: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, dict[str, Any]]:
        """Agree with this frame's sprite silhouette without passing through itself.

        ``reference_bones`` is the previous frame's solved pose, charged identically to
        every candidate. Exempting the plate-anchor candidate would hand it a discount
        no measurement justifies.
        """

        def objective(
            bone_batch: torch.Tensor, root_t_batch: torch.Tensor, root_r_batch: torch.Tensor
        ) -> torch.Tensor:
            return _frame_cost(
                bone_batch,
                root_t_batch,
                root_r_batch,
                frame_index=int(frame_index),
                reference_bones=reference_bones,
            )

        return _descend(
            experiment,
            objective=objective,
            bones=bones,
            root_translation=root_t,
            root_rotation=root_r,
            bone_indices=bone_indices,
            probe_axes=config.probe_axes,
            rotation_axes=rotation_axes,
            translation_axes=translation_axes,
            step_schedule_deg=schedule,
            translation_step_per_deg=float(config.root_translation_step_per_deg),
            max_accepted_steps=int(max_steps),
            min_gain=float(config.correct_min_score_gain),
        )

    # Frame 0 has nothing to predict from, and flow advection is only valid once
    # the model sits on the sprite. Settle the seed against frame 0 first.
    seed_bones, seed_root_t, seed_root_r, seed_report = _correct(
        tracked[0],
        tracked_root_t[0].unsqueeze(0),
        tracked_root_r[0].unsqueeze(0),
        frame_index=int(frame_indices[0]),
        schedule=config.seed_step_schedule_deg,
        max_steps=int(config.seed_max_accepted_steps),
    )
    tracked[0] = seed_bones
    tracked_root_t[0] = seed_root_t[0]
    tracked_root_r[0] = seed_root_r[0]
    # objectiveBefore/After are the combined cost, not silhouette. Naming them
    # "silhouette" would overstate the fit whenever the penetration term is active.
    seed_summary = {
        "frameIndex": int(frame_indices[0]),
        "costBefore": round(float(seed_report["objectiveBefore"]), 4),
        "costAfter": round(float(seed_report["objectiveAfter"]), 4),
        "silhouetteAfter": round(
            float(
                silhouette_scores(
                    experiment,
                    seed_bones.unsqueeze(0),
                    seed_root_t,
                    seed_root_r,
                    frame_index=int(frame_indices[0]),
                )[0].item()
            ),
            4,
        ),
        "penetrationAfter": round(float(_penetration(seed_bones.unsqueeze(0))[0].item()), 4),
        "acceptedSteps": int(seed_report["acceptedSteps"]),
        "acceptedRootSteps": int(seed_report["acceptedRootSteps"]),
    }
    if progress:
        print(
            f"[seed ] frame {frame_indices[0]:>3} "
            f"cost {seed_summary['costBefore']:.4f} -> {seed_summary['costAfter']:.4f} "
            f"silh {seed_summary['silhouetteAfter']:.4f} "
            f"pen {seed_summary['penetrationAfter']:.4f} "
            f"steps={seed_summary['acceptedSteps']}"
            f"(root {seed_summary['acceptedRootSteps']})",
            flush=True,
        )

    plate_matches: dict[int, list[Any]] = {}
    if bool(config.plate_anchor_enabled):
        plate_matches = earlier_plate_matches(
            rgbs,
            alphas,
            max_rgb_mad=float(config.plate_anchor_max_rgb_mad),
            min_alpha_iou=float(config.plate_anchor_min_alpha_iou),
        )
        if progress:
            summary_text = ", ".join(
                f"f{int(frame_indices[position])}<-f{int(frame_indices[entries[0][0]])}"
                for position, entries in sorted(plate_matches.items())
            )
            print(
                "continuous track plate anchors: "
                f"{len(plate_matches)} frames repeat an earlier plate"
                f"{' (' + summary_text + ')' if summary_text else ''}",
                flush=True,
            )

    frame_reports: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    surface_sample_count = 0
    held_frames = 0
    anchored_frames = 0
    # Cost achieved per position, so an anchor can start from the *best* earlier copy
    # of a plate rather than merely the first one.
    achieved_cost: dict[int, float] = {
        0: float(seed_report["objectiveAfter"]),
    }

    for position in range(1, len(frame_indices)):
        previous = position - 1
        cache = flow_cache_dir / f"raster_flow_{previous:02d}_{position:02d}.npy"
        if cache.is_file():
            flow = np.load(cache)
        else:
            flow = _dense_flow(rgbs[previous], rgbs[position], alphas[previous], alphas[position])
            np.save(cache, flow)

        # Warm start is the previous frame's *solved* state, root DOFs included.
        previous_root_t = tracked_root_t[previous].detach().clone().unsqueeze(0)
        previous_root_r = tracked_root_r[previous].detach().clone().unsqueeze(0)
        previous_xy = (
            energy.project(
                tracked[previous].unsqueeze(0), previous_root_t, previous_root_r
            )[0]
            .detach()
            .cpu()
            .numpy()
            .astype(np.float32)
        )
        surface_sample_count = int(previous_xy.shape[0])

        sample_indices, targets_xy, weights = _select_tracked_samples(
            previous_xy,
            alpha_previous=alphas[previous],
            structure=_structure_magnitude(rgbs[previous], alphas[previous]),
            flow=flow,
            disagreement=_flow_local_disagreement(flow),
            config=config,
        )
        sprite_centroid, sprite_covariance = _alpha_moments(alphas[position])
        energy.set_frame(
            sample_indices=sample_indices,
            targets_xy=targets_xy,
            weights=weights,
            previous_xy=previous_xy[sample_indices],
            outside_distance=_outside_distance(alphas[position]),
            sprite_centroid=sprite_centroid,
            sprite_covariance=sprite_covariance,
        )

        residual_before = energy.flow_residual_px(
            tracked[previous].unsqueeze(0), previous_root_t, previous_root_r
        )

        # Predict: advect the previous solved pose along measured image motion.
        predicted, predicted_root_t, predicted_root_r, predict_report = _descend(
            experiment,
            objective=energy.evaluate,
            bones=tracked[previous],
            root_translation=previous_root_t,
            root_rotation=previous_root_r,
            bone_indices=bone_indices,
            probe_axes=config.probe_axes,
            rotation_axes=rotation_axes,
            translation_axes=translation_axes,
            step_schedule_deg=config.step_schedule_deg,
            translation_step_per_deg=float(config.root_translation_step_per_deg),
            max_accepted_steps=int(config.max_accepted_steps),
            min_gain=float(config.min_energy_gain),
        )
        residual_predicted = energy.flow_residual_px(
            predicted.unsqueeze(0), predicted_root_t, predicted_root_r
        )

        # Correct: the sprite silhouette is the measurement that anchors the track.
        target_frame = int(frame_indices[position])
        reference_bones = tracked[previous].detach().clone()
        solved, solved_root_t, solved_root_r, correct_report = _correct(
            predicted,
            predicted_root_t,
            predicted_root_r,
            frame_index=target_frame,
            schedule=config.correct_step_schedule_deg,
            max_steps=int(config.correct_max_accepted_steps),
            reference_bones=reference_bones,
        )
        cost_solved = float(correct_report["objectiveAfter"])

        # Three estimates compete for this frame on one cost:
        #   predict+correct   - advect the previous pose, then fit the silhouette
        #   hold              - keep the previous pose unchanged
        #   plate anchor      - correct from the pose solved for an identical plate
        # Holding and anchoring are estimates, not fallbacks: each is scored by the
        # same _frame_cost and only wins by measuring better. Anchoring is what stops
        # a sequential track from drifting forever, since the drifted previous frame
        # is a poor warm start whenever the sprite returns to a pose already solved.
        candidates: list[tuple[str, float, torch.Tensor, torch.Tensor, torch.Tensor]] = [
            ("solve", cost_solved, solved, solved_root_t, solved_root_r)
        ]

        cost_held = float(
            _frame_cost(
                tracked[previous].unsqueeze(0),
                previous_root_t,
                previous_root_r,
                frame_index=target_frame,
                reference_bones=reference_bones,
            )[0].item()
        )
        candidates.append(
            (
                "hold",
                cost_held,
                tracked[previous].detach().clone(),
                previous_root_t.detach().clone(),
                previous_root_r.detach().clone(),
            )
        )

        anchor_source: int | None = None
        anchor_cost: float | None = None
        entries = plate_matches.get(position, [])
        if entries:
            # Best-solved earlier copy of this plate, not merely the first copy.
            anchor_source = min(
                (int(entry[0]) for entry in entries),
                key=lambda earlier: achieved_cost.get(int(earlier), float("inf")),
            )
            anchored, anchored_root_t, anchored_root_r, anchor_report = _correct(
                tracked[anchor_source].detach().clone(),
                tracked_root_t[anchor_source].detach().clone().unsqueeze(0),
                tracked_root_r[anchor_source].detach().clone().unsqueeze(0),
                frame_index=target_frame,
                schedule=config.correct_step_schedule_deg,
                max_steps=int(config.correct_max_accepted_steps),
                reference_bones=reference_bones,
            )
            anchor_cost = float(anchor_report["objectiveAfter"])
            candidates.append(
                ("anchor", anchor_cost, anchored, anchored_root_t, anchored_root_r)
            )

        winner, cost_solved, solved, solved_root_t, solved_root_r = min(
            candidates, key=lambda entry: entry[1]
        )
        held = winner == "hold"
        if held:
            held_frames += 1
        if winner == "anchor":
            anchored_frames += 1
        achieved_cost[position] = cost_solved

        # Reported separately from the combined cost, because "the outline matches"
        # and "the mesh does not pass through itself" are different claims.
        silhouette_solved = float(
            silhouette_scores(
                experiment,
                solved.unsqueeze(0),
                solved_root_t,
                solved_root_r,
                frame_index=target_frame,
            )[0].item()
        )
        silhouette_held = float(
            silhouette_scores(
                experiment,
                tracked[previous].unsqueeze(0),
                previous_root_t,
                previous_root_r,
                frame_index=target_frame,
            )[0].item()
        )
        penetration_solved = float(_penetration(solved.unsqueeze(0))[0].item())

        tracked[position] = solved
        tracked_root_t[position] = solved_root_t[0]
        tracked_root_r[position] = solved_root_r[0]
        residual_after = energy.flow_residual_px(
            solved.unsqueeze(0), solved_root_t, solved_root_r
        )
        solved_xy = (
            energy.project(solved.unsqueeze(0), solved_root_t, solved_root_r)[
                0, sample_indices, :
            ]
            .detach()
            .cpu()
            .numpy()
            .astype(np.float32)
        )
        demanded = float(
            np.linalg.norm(targets_xy - previous_xy[sample_indices], axis=-1).mean()
        )

        frame_reports.append(
            {
                "frameIndex": target_frame,
                "trackedSamples": int(sample_indices.size),
                "demandedMotionPx": round(demanded, 3),
                "flowResidualBeforePx": round(residual_before, 3),
                "flowResidualPredictedPx": round(residual_predicted, 3),
                "flowResidualAfterPx": round(residual_after, 3),
                "silhouetteHeld": round(silhouette_held, 4),
                "silhouetteAfter": round(silhouette_solved, 4),
                "penetrationAfter": round(penetration_solved, 4),
                "costHeld": round(cost_held, 4),
                "costPredicted": round(float(correct_report["objectiveBefore"]), 4),
                "costSolve": round(float(correct_report["objectiveAfter"]), 4),
                "costAnchor": None if anchor_cost is None else round(anchor_cost, 4),
                "costAfter": round(cost_solved, 4),
                "winner": str(winner),
                "plateAnchorSource": None
                if anchor_source is None
                else int(frame_indices[int(anchor_source)]),
                "heldPreviousPose": bool(held),
                "predictSteps": int(predict_report["acceptedSteps"]),
                "correctSteps": int(correct_report["acceptedSteps"]),
                "correctRootSteps": int(correct_report["acceptedRootSteps"]),
            }
        )
        diagnostics.append(
            {
                "framePosition": position,
                "previousXy": previous_xy[sample_indices],
                "targetsXy": targets_xy,
                "solvedXy": solved_xy,
            }
        )
        if progress:
            print(
                f"[track] frame {target_frame:>3} "
                f"demand={demanded:5.2f}px "
                f"resid {residual_before:5.2f} ->pred {residual_predicted:5.2f} "
                f"->corr {residual_after:5.2f} | "
                f"silh {silhouette_held:.4f}->{silhouette_solved:.4f} "
                f"pen {penetration_solved:6.3f} "
                f"cost {cost_held:.4f}->{cost_solved:.4f} "
                f"win={winner}"
                f"{'' if anchor_source is None else f'(anchor f{int(frame_indices[int(anchor_source)])} {anchor_cost:.4f})'} "
                f"steps p{predict_report['acceptedSteps']}/c{correct_report['acceptedSteps']}",
                flush=True,
            )

    def _mean(key: str) -> float | None:
        if not frame_reports:
            return None
        return round(float(np.mean([row[key] for row in frame_reports])), 3)

    summary = {
        "method": "def_continuous_surface_track_predict_correct",
        "landmarkLocking": False,
        "predictSignal": "dense_optical_flow_advection",
        "correctSignal": "rasterised_sprite_silhouette",
        "seed": seed_summary,
        "heldFrames": held_frames,
        "trackedGeometry": "mesh_surface_samples",
        "surfaceSamples": surface_sample_count,
        "movedBones": len(bone_indices),
        "raster": [raster[0], raster[1]],
        "config": {
            "flowWeight": float(config.flow_weight),
            "insideWeight": float(config.inside_weight),
            "smoothWeight": float(config.smooth_weight),
            "stepScheduleDeg": [float(value) for value in config.step_schedule_deg],
            "maxAcceptedSteps": int(config.max_accepted_steps),
            "correctStepScheduleDeg": [float(v) for v in config.correct_step_schedule_deg],
            "correctMaxAcceptedSteps": int(config.correct_max_accepted_steps),
            "seedStepScheduleDeg": [float(v) for v in config.seed_step_schedule_deg],
            "seedMaxAcceptedSteps": int(config.seed_max_accepted_steps),
            "momentWeight": float(config.moment_weight),
            "structurePercentile": float(config.structure_percentile),
            "maxTrackSamples": int(config.max_track_samples),
            "probeAxes": len(config.probe_axes),
            "trackRootRotation": bool(config.track_root_rotation),
            "trackRootTranslation": bool(config.track_root_translation),
        },
        "frames": frame_reports,
        "meanDemandedMotionPx": _mean("demandedMotionPx"),
        "meanFlowResidualBeforePx": _mean("flowResidualBeforePx"),
        "meanFlowResidualPredictedPx": _mean("flowResidualPredictedPx"),
        "meanFlowResidualAfterPx": _mean("flowResidualAfterPx"),
        "meanSilhouetteHeld": _mean("silhouetteHeld"),
        "meanSilhouetteAfter": _mean("silhouetteAfter"),
        "meanPenetrationAfter": _mean("penetrationAfter"),
        "temporalWeight": float(config.temporal_weight),
        "temporalFreeDeg": float(config.temporal_free_deg),
        "anchoredFrames": anchored_frames,
        "plateAnchorEnabled": bool(config.plate_anchor_enabled),
        # A cycle whose first and last plates are identical must also close in pose,
        # or the animation pops on wrap. Measured, not assumed.
        "loopSeam": loop_seam_report(
            rgbs=rgbs,
            alphas=alphas,
            bones=tracked,
            root_translation=tracked_root_t,
            root_rotation=tracked_root_r,
        ),
        "maxPenetrationAfter": (
            None
            if not frame_reports
            else round(float(max(row["penetrationAfter"] for row in frame_reports)), 4)
        ),
        "rootStepsAccepted": int(sum(row["correctRootSteps"] for row in frame_reports)),
    }
    return (
        tracked,
        tracked_root_t,
        tracked_root_r,
        {"summary": summary, "diagnostics": diagnostics, "rgbs": rgbs},
    )


_SITE_COLORS = {
    "previous": (90, 160, 255),
    "target": (80, 235, 120),
    "solved": (255, 95, 95),
}


def write_track_diagnostic_gif(
    *,
    rgbs: Sequence[np.ndarray],
    diagnostics: Sequence[dict[str, Any]],
    out: Path,
    upscale: int = 3,
    stride: int = 6,
) -> Path:
    """Sprite with previous samples, flow-advected targets, and solved sample positions.

    ``stride`` thins the drawn samples so the overlay stays readable; the solve
    itself uses every selected sample.
    """
    panels: list[Image.Image] = []
    for entry in diagnostics:
        position = int(entry["framePosition"])
        base = Image.fromarray(rgbs[position]).convert("RGB")
        width, height = base.size
        canvas = base.resize((width * upscale, height * upscale), Image.Resampling.NEAREST)
        draw = ImageDraw.Draw(canvas)
        previous_xy = entry["previousXy"][::stride] * upscale
        targets_xy = entry["targetsXy"][::stride] * upscale
        solved_xy = entry["solvedXy"][::stride] * upscale
        for site in range(len(previous_xy)):
            px, py = previous_xy[site]
            tx, ty = targets_xy[site]
            sx, sy = solved_xy[site]
            draw.line((px, py, tx, ty), fill=_SITE_COLORS["target"], width=1)
            draw.point((px, py), fill=_SITE_COLORS["previous"])
            draw.ellipse((tx - 1, ty - 1, tx + 1, ty + 1), outline=_SITE_COLORS["target"])
            draw.ellipse((sx - 2, sy - 2, sx + 2, sy + 2), outline=_SITE_COLORS["solved"])
        draw.text((4, 4), "blue=prev  green=flow target  red=solved", fill=(235, 235, 235))
        panels.append(canvas)
    panels[0].save(
        out, save_all=True, append_images=panels[1:], duration=PREVIEW_GIF_FRAME_MS, loop=0
    )
    return out


def compose_sprite_bind_track_gif(
    *,
    sprite_dir: Path,
    bind_rgb_dir: Path,
    track_rgb_dir: Path,
    frame_indices: Sequence[int],
    out: Path,
) -> Path:
    panels: list[Image.Image] = []
    for index in frame_indices:
        sprite_rgba = np.asarray(Image.open(sprite_dir / f"{int(index):02d}.png").convert("RGBA"))
        sprite = sprite_rgba[..., :3].copy()
        sprite[sprite_rgba[..., 3] < ALPHA_THRESHOLD] = 0
        bind = np.asarray(Image.open(bind_rgb_dir / f"{int(index):02d}.png").convert("RGB"))
        track = np.asarray(Image.open(track_rgb_dir / f"{int(index):02d}.png").convert("RGB"))
        height = max(sprite.shape[0], bind.shape[0], track.shape[0])

        def _fit(image: np.ndarray) -> np.ndarray:
            scale = height / image.shape[0]
            width = max(1, int(round(image.shape[1] * scale)))
            return np.asarray(
                Image.fromarray(image).resize((width, height), Image.Resampling.LANCZOS)
            )

        panels.append(
            Image.fromarray(np.concatenate([_fit(sprite), _fit(bind), _fit(track)], axis=1))
        )
    panels[0].save(
        out, save_all=True, append_images=panels[1:], duration=PREVIEW_GIF_FRAME_MS, loop=0
    )
    return out


def _frame_indices_from_dir(frame_dir: Path) -> list[int]:
    indices = [int(path.stem) for path in sorted(frame_dir.glob("*.png")) if path.stem.isdigit()]
    if not indices:
        raise FileNotFoundError(f"no numbered PNG frames in {frame_dir}")
    return sorted(indices)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", default="h3_roc")
    parser.add_argument("--clip", default="idle_start_move_end")
    parser.add_argument("--out-lane", default="def_continuous_track_cheap")
    parser.add_argument(
        "--quality",
        action="store_true",
        help="Four step levels, diagonal probes, 48 accepted steps per frame (slower).",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=0,
        help="Track only the first N frames (0 = whole clip). Review knob, not a solve knob.",
    )
    parser.add_argument("--inside-weight", type=float, default=None)
    parser.add_argument("--smooth-weight", type=float, default=None)
    parser.add_argument("--moment-weight", type=float, default=None)
    parser.add_argument(
        "--correct-steps",
        type=int,
        default=None,
        help="Accepted silhouette-correction steps per frame. Raise when the log shows the cap being hit.",
    )
    parser.add_argument(
        "--correct-schedule",
        default=None,
        help=(
            "Comma-separated degrees for the correction anneal, e.g. 4,2,1,0.5. "
            "Finer tails are needed before a stalled frame can be called rig-limited."
        ),
    )
    parser.add_argument(
        "--no-root",
        action="store_true",
        help="Bone rotations only. Whole-body attitude then cannot be represented.",
    )
    parser.add_argument("--structure-percentile", type=float, default=None)
    parser.add_argument(
        "--penetration-weight",
        type=float,
        default=None,
        help=(
            "Weight on the unsaturated penetration norm in the correction objective. "
            "Silhouette agreement alone rewards hiding a part inside the body, since "
            "the hidden pixels stay covered; without this the head buries itself. "
            "Set 0 to reproduce the earlier unguarded behaviour."
        ),
    )
    parser.add_argument(
        "--penetration-sample-count",
        type=int,
        default=None,
        help="Surface samples used for pair penetration. Too few and thin parts slip through.",
    )
    parser.add_argument(
        "--temporal-weight",
        type=float,
        default=None,
        help=(
            "Weight on per-joint rotation change beyond --temporal-free-deg. Without it "
            "the correction stage can flip a joint by a half turn between frames onto an "
            "equally well scoring mirrored pose. Set 0 to reproduce that."
        ),
    )
    parser.add_argument(
        "--temporal-free-deg",
        type=float,
        default=None,
        help="Per-joint rotation change allowed per frame before the temporal term charges.",
    )
    parser.add_argument(
        "--anatomy-order",
        default=None,
        help=(
            "Authored anatomy-order JSON whose rotationScaleByGroup becomes per-bone "
            "rotation limits. Without it every joint shares one flat limit and the "
            "search freely flails parts the sprite gives no evidence about."
        ),
    )
    parser.add_argument(
        "--anatomy-limit-groups",
        default=None,
        help=(
            "Comma-separated anatomy groups to clamp, e.g. leg_a,leg_b,tail. Omit to "
            "apply the whole authored policy, which on h3_roc also clamped trunk and "
            "neck and made motion markedly less smooth."
        ),
    )
    parser.add_argument(
        "--no-plate-anchor",
        action="store_true",
        help=(
            "Do not offer the pose from an identical earlier plate as a warm start. "
            "Sequential tracking then drifts with nothing to pull it back; use only to "
            "reproduce that drift."
        ),
    )
    parser.add_argument("--skip-gif", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    unit = str(args.unit)
    clip = str(args.clip)
    clip_base = ROOT / "artifacts" / "pose_picker_runs" / unit / clip
    frame_dir = clip_base / f"frames_def12_nn_{clip}_shadow_culled"
    if not frame_dir.is_dir():
        raise FileNotFoundError(frame_dir)

    frame_indices = _frame_indices_from_dir(frame_dir)
    if int(args.max_frames) > 0:
        frame_indices = frame_indices[: int(args.max_frames)]

    out_root = assert_write_path(clip_base / str(args.out_lane))
    out_root.mkdir(parents=True, exist_ok=True)

    config = quality_track_config() if args.quality else cheap_track_config()
    if args.inside_weight is not None:
        config = replace(config, inside_weight=float(args.inside_weight))
    if args.smooth_weight is not None:
        config = replace(config, smooth_weight=float(args.smooth_weight))
    if args.moment_weight is not None:
        config = replace(config, moment_weight=float(args.moment_weight))
    if args.correct_steps is not None:
        config = replace(config, correct_max_accepted_steps=int(args.correct_steps))
    if args.correct_schedule is not None:
        schedule = tuple(
            float(part) for part in str(args.correct_schedule).split(",") if part.strip()
        )
        if not schedule:
            raise ValueError("--correct-schedule needs at least one degree value")
        config = replace(config, correct_step_schedule_deg=schedule)
    if args.structure_percentile is not None:
        config = replace(config, structure_percentile=float(args.structure_percentile))
    if args.penetration_weight is not None:
        config = replace(config, penetration_weight=float(args.penetration_weight))
    if args.penetration_sample_count is not None:
        config = replace(config, penetration_sample_count=int(args.penetration_sample_count))
    if args.no_plate_anchor:
        config = replace(config, plate_anchor_enabled=False)
    if args.temporal_weight is not None:
        config = replace(config, temporal_weight=float(args.temporal_weight))
    if args.temporal_free_deg is not None:
        config = replace(config, temporal_free_deg=float(args.temporal_free_deg))
    if args.no_root:
        config = replace(config, track_root_rotation=False, track_root_translation=False)

    limit_overrides: tuple[tuple[str, float], ...] = ()
    limit_provenance: dict[str, Any] | None = None
    if args.anatomy_order is not None:
        limit_overrides, limit_provenance = bone_limit_overrides_from_anatomy_order(
            anatomy_order_path=Path(str(args.anatomy_order)).resolve(),
            node_names=node_names_from_mesh(unit_mesh(unit, clip)),
            only_groups=(
                None
                if args.anatomy_limit_groups is None
                else [
                    part.strip()
                    for part in str(args.anatomy_limit_groups).split(",")
                    if part.strip()
                ]
            ),
        )
        print(
            "continuous track anatomy limits: "
            f"{limit_provenance['overrideCount']} bones scaled from "
            f"{Path(limit_provenance['anatomyOrderPath']).name} "
            + ", ".join(
                f"{group}x{entry['scale']}"
                for group, entry in limit_provenance["perGroup"].items()
                if entry["applied"]
            ),
            flush=True,
        )

    experiment, bones, root_t, root_r, _camera_fit, payload = bootstrap_flow_mocap_experiment(
        unit=unit,
        clip=clip,
        frame_dir=frame_dir,
        frame_indices=frame_indices,
        init_dir=out_root / "initialization",
        bone_limit_scale_overrides=limit_overrides,
    )

    started = time.perf_counter()
    tracked, tracked_root_t, tracked_root_r, track_out = track_clip(
        experiment,
        bones,
        root_t,
        root_r,
        frame_dir=frame_dir,
        frame_indices=frame_indices,
        flow_cache_dir=out_root / "flow",
        config=config,
        progress=True,
    )
    summary = dict(track_out["summary"])
    summary["solveSec"] = round(time.perf_counter() - started, 2)
    summary["seedMode"] = "bind_pose_profile_camera"
    summary["penetrationWeight"] = float(config.penetration_weight)
    summary["penetrationSampleCount"] = int(config.penetration_sample_count)
    summary["anatomyLimits"] = limit_provenance

    clip_path = write_polished_clip(
        source_payload=payload,
        experiment=experiment,
        bone_vectors=tracked,
        root_translation=tracked_root_t,
        root_rotation=tracked_root_r,
        output_dir=out_root / "solve",
        polish_report=summary,
        require_pose_units=True,
    )
    rescored = rescore_tensors(experiment, tracked, tracked_root_t, tracked_root_r)
    bind_scored = rescore_tensors(experiment, bones, root_t, root_r)

    diagnostic_gif = None
    compare_gif = None
    if not bool(args.skip_gif):
        diagnostic_gif = write_track_diagnostic_gif(
            rgbs=track_out["rgbs"],
            diagnostics=track_out["diagnostics"],
            out=out_root / "continuous_track_targets.gif",
        )
        tracked_payload = json.loads(clip_path.read_text(encoding="utf-8"))
        mesh = unit_mesh(unit, clip)
        raster_literature_preview(
            payload=tracked_payload, mesh=mesh, output_dir=out_root / "preview"
        )
        bind_shell = dict(payload)
        bind_shell["poses"] = poses_from_tensors(experiment, bones, root_t, root_r)
        raster_literature_preview(
            payload=bind_shell, mesh=mesh, output_dir=out_root / "bind_preview"
        )
        compare_gif = compose_sprite_bind_track_gif(
            sprite_dir=frame_dir,
            bind_rgb_dir=out_root / "bind_preview" / "solved_rgb",
            track_rgb_dir=out_root / "preview" / "solved_rgb",
            frame_indices=frame_indices,
            out=out_root / "sprite_vs_bind_vs_track.gif",
        )

    report_path = out_root / f"{unit}_continuous_track_report.json"
    report_path.write_text(
        json.dumps(
            {
                "proof": "generated-artifact",
                "unit": unit,
                "clip": clip,
                "frames": frame_indices,
                "clipResult": str(clip_path).replace("\\", "/"),
                "bindMeanScore": bind_scored["meanScore"],
                "trackedMeanScore": rescored["meanScore"],
                "track": summary,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "ok": True,
                "mode": "quality" if args.quality else "cheap",
                "frames": len(frame_indices),
                "bindMeanScore": bind_scored["meanScore"],
                "trackedMeanScore": rescored["meanScore"],
                "meanDemandedMotionPx": summary["meanDemandedMotionPx"],
                "meanFlowResidualBeforePx": summary["meanFlowResidualBeforePx"],
                "meanFlowResidualPredictedPx": summary["meanFlowResidualPredictedPx"],
                "meanSilhouetteAfter": summary["meanSilhouetteAfter"],
                "meanPenetrationAfter": summary["meanPenetrationAfter"],
                "anchoredFrames": summary["anchoredFrames"],
                "loopSeam": summary["loopSeam"],
                "meanFlowResidualAfterPx": summary["meanFlowResidualAfterPx"],
                "seed": summary["seed"],
                "heldFrames": summary["heldFrames"],
                "rootStepsAccepted": summary["rootStepsAccepted"],
                "solveSec": summary["solveSec"],
                "report": str(report_path).replace("\\", "/"),
                "targetsGif": str(diagnostic_gif).replace("\\", "/") if diagnostic_gif else None,
                "compareGif": str(compare_gif).replace("\\", "/") if compare_gif else None,
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
