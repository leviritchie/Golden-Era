"""Minimal Blender-free depth/silhouette coordinate-descent solver.

This is intentionally a separate lane from ``roc_gpu_cascade_experiment``.
It uses the existing canonical Meshy FK/LBS and nvdiffrast triangle renderer,
but removes root hypotheses, gradients, and proxy cascades.  It uses a cheap
coordinate search for per-frame motion root translation/rotation, then
walks bones in dependency order.

The default articulated search is one bone at a time.  When
``pass_limit_deg`` is set, each visit may move that bone at most that far
on one axis before the solver continues to the next bone.  Later passes
repeat the walk so a joint can still travel its full limit across the
frame, without lingering on a 150-degree sweep of one bone.

When ``packed_axis_batch`` is positive, several of those 1D axis windows
are scored in one nvdiffrast batch.  Winners inside one raster are applied
together (they all saw the same start pose).  The next raster is built
from the updated pose, so later bones still see earlier bones' moves.

Branch pair-grids are still the full Cartesian product, but
``score_raster_batch`` splits that product across several rasters so LBS
and nvdiffrast stay inside dedicated VRAM.  0 is invalid, not "unlimited".

After each skeleton pass, the whole pose is scored.  A pass that is not
meaningfully better than the previous pass is stalled, and the solver
keeps that stalled pose and moves on.  Silhouette-hole unstick is off by
default: covering missing target pixels with a wide simultaneous joint
grid was observed to melt LBS and yank wrong limbs.  ``unstick_joint_count``
greater than zero is an explicit opt-in only.

After copying the previous pose and the per-frame root search, later
frames can swing distal bones toward pixels that appeared on the current
sprite and left the previous sprite. That primed pose is the start of the
ordinary one-bone walk. Empty sprite deltas stay unmoved.

On later frames the occupancy lane then: persists distal identity when
2D blobs merge, holds a limb whose unique visible region vanished, sorts
bones camera-near first from the current pose, and drops occupancy IoU
on pixels two bones both own. Chroma and depth still score those pixels.
Collision charges only extra contact past a slack so a legal drawing is
not treated as a 3D pretzel.

A sequential temporal penalty compares the current candidate to the
previous frame's accepted pose.  That is a score term, not a seed-only
hint.  Branch-block mode remains available as an explicit alternate.
"""
from __future__ import annotations

import itertools
import json
import math
import time
from collections import deque
from dataclasses import asdict, dataclass
import os
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image, ImageDraw

from gpu_raster_depth_animation import (
    AnimationSolveResult,
    render_pose_rgb_animation,
    render_pose_depth_animation,
    replace_owned_run_artifacts,
)
from gpu_profile_camera_initializer import (
    PROFILE_FACING_WEIGHT,
    ProfileCameraInitConfig,
    assert_solver_camera_is_registered_profile,
    initialize_profile_camera,
)
from gpu_geometry_score import (
    chroma_quality,
    collision_error_above_slack,
    compose_geometry_score,
    gpu_score_raster_resolution,
    silhouette_and_depth_quality,
    srgb_rgb_to_lab_ab,
)
from roc_gpu_cascade_experiment import (
    GpuCascadeConfig,
    GpuCascadeExperiment,
    crop_rgb_hwc_subject_square,
    persist_gpu_clip_result,
    rgb_hwc_batch_to_pil_images,
    score_dense_semantic_rgb_batch,
)


@dataclass(frozen=True)
class DepthSilhouetteConfig:
    """Only the controls needed by the stripped-down one-bone experiment."""

    resolution: tuple[int, int] = (96, 86)
    alpha_threshold: int = 8
    joint_limit_deg: float = 150.0
    coarse_step_deg: float = 15.0
    refine_step_deg: float = 2.5
    refine_radius_deg: float = 20.0
    search_axes: tuple[str, ...] = ("x", "y", "z")
    # asset: GLB node order. dependency: parent-then-child. explicit: bone_order
    # names then the rest. camera_near_to_far: bind joint origins along the
    # camera-to-subject ray (near first). pose_near_to_far: same ray, current
    # posed joint origins, recomputed each frame after root/sprite-delta.
    # leftover_gravity: greedy next bone from uncovered target pixels assigned
    # to the nearest unique-region (not soft 1/r^2 on every bone).
    # In branch mode camera/pose sorts only rank siblings; leftover_gravity
    # requires single-bone mode.
    bone_order_mode: str = "dependency"
    bone_order: tuple[str, ...] = ()
    leftover_gravity_max_assign_px: float = 24.0
    leftover_gravity_sigma_px: float = 8.0
    leftover_gravity_extra_weight: float = 0.25
    leftover_gravity_min_pull: float = 1.0
    leftover_gravity_depth_gate: float = 0.20
    multi_bone_mode: str = "single"
    multi_bone_block_size: int = 2
    multi_bone_rounds: int = 2
    multi_bone_global_sweep: bool = True
    multi_bone_search_radius_deg: float = 150.0
    multi_bone_search_step_deg: float = 15.0
    multi_bone_refine_radius_deg: float = 20.0
    multi_bone_refine_step_deg: float = 2.5
    multi_bone_max_candidates: int = 1024
    # Max poses per LBS + nvdiffrast + collision call. Branch global sweep
    # is 21x21=441 poses. nvdiffrast's CUDA context grows to the largest
    # batch it has seen; Windows then pages overflow into Shared GPU
    # memory (system RAM). This only chunks scoring. It does not shrink
    # the search.
    score_raster_batch: int = 128
    # When pass_limit_deg > 0, each single-bone axis visit searches only
    # current +/- pass_limit_deg instead of the full joint range.  Later
    # rounds of multi_bone_rounds walk the skeleton again.
    pass_limit_deg: float = 0.0
    pass_step_deg: float = 2.5
    # When pass_limit_deg > 0 and packed_axis_batch > 0, several whole 1D
    # axis windows share one nvdiffrast batch.  A job is never split.
    # 0 is an explicit serial ablation, not a silent fallback.
    packed_axis_batch: int = 128
    # After a skeleton pass, a score gain smaller than this is not a
    # meaningful improvement and triggers the stall path.
    pass_improve_epsilon: float = 0.005
    # Stalled scores below this floor used to try a wide multi-bone unstick
    # aimed at missing target silhouette.  That path is off (joint_count=0).
    # Set unstick_joint_count > 0 only for an explicit ablation.
    unstick_score_floor: float = 0.9
    unstick_joint_count: int = 0
    unstick_limit_deg: float = 60.0
    unstick_samples_per_bone: int = 3
    unstick_max_candidates: int = 512
    unstick_max_attempts: int = 3
    # After the one-bone walk, pair leftover silhouette blobs, attribute the
    # red excess to a distal skinned bone, and run a full joint-limit search
    # on that short chain. Candidates are scored by regional IoU inside the
    # leftover neighborhood, not by whole-image depth. Off is explicit.
    blob_exhaustive_enabled: bool = True
    blob_exhaustive_max_pairs: int = 2
    blob_exhaustive_min_component_area: int = 12
    blob_exhaustive_min_bone_depth: int = 3
    blob_exhaustive_max_chain_depth: int = 3
    blob_exhaustive_block_size: int = 2
    blob_exhaustive_dilate_px: int = 4
    blob_exhaustive_max_tip_distance_px: float = 96.0
    blob_exhaustive_max_centroid_distance_px: float = 96.0
    blob_exhaustive_max_area_ratio: float = 4.0
    blob_exhaustive_min_displacement_alignment: float = 0.15
    blob_exhaustive_depth_tolerance: float = 0.12
    blob_exhaustive_predicted_alpha_threshold: float = 0.5
    temporal_weight: float = 0.0
    temporal_scale_deg: float = 20.0
    temporal_root_scale_body_lengths: float = 0.15
    # Geodesically-distant mesh samples. Soft clip of limbs/props through
    # the torso or each other; rest contacts closer than the margin at bind
    # are excluded. Weight 0 with enabled=True is a config error, not off.
    collision_enabled: bool = True
    collision_sample_count: int = 256
    collision_geodesic_min_hops: int = 8
    collision_margin_body_lengths: float = 0.04
    collision_weight: float = 0.35
    # Extra contact below this is not charged. 0 is the old full penalty.
    collision_positive_abs_slack: float = 0.12
    # Mixed-influence triangle edges vs bind rest length. Occupancy ignore and
    # regional IoU do not see LBS blend stretch. Exclusive same-bone edges are
    # rigid under rotate-only joints and are excluded so the torso cannot dilute
    # a melted sleeve. Weight 0 with enabled=True is a config error, not off.
    strain_enabled: bool = True
    strain_weight: float = 0.80
    strain_tolerance: float = 0.08
    strain_exclusive_weight: float = 0.99
    strain_accept_slack: float = 0.04
    strain_min_rest_length_body_lengths: float = 1e-4
    # Occupancy abstains where two bones both have high skinning weight.
    occupancy_ignore_ambiguous: bool = True
    occupancy_ambiguous_ratio: float = 0.4
    occupancy_ambiguous_min_weight: float = 1.0
    # Merged leftover/delta blobs keep the distal unique-region bone.
    blob_identity_persist: bool = True
    blob_identity_min_overlap: int = 4
    # Distal bones whose unique visible region collapsed stay at last pose.
    unique_vanish_hold: bool = True
    unique_vanish_frac: float = 0.25
    unique_vanish_min_area: int = 12
    unique_vanish_min_bone_depth: int = 3
    root_translation_enabled: bool = True
    root_translation_axes: tuple[str, ...] = ("forward", "lateral", "vertical")
    root_translation_limit_body_lengths: float = 0.75
    root_translation_coarse_step_body_lengths: float = 0.10
    root_translation_refine_radius_body_lengths: float = 0.10
    root_translation_refine_step_body_lengths: float = 0.025
    root_rotation_enabled: bool = True
    root_rotation_axes: tuple[str, ...] = (
        "camera_forward",
        "camera_right",
        "camera_up",
    )
    root_rotation_limit_deg: float = 180.0
    # Frame 00 starts at the profile-registered heading. A full ±180 search
    # there can tumble the mesh onto its side because a hunched idle blob
    # coincidentally overlaps better. Later frames keep the wide envelope,
    # but each frame only steps this far from the current heading.
    root_rotation_first_frame_limit_deg: float = 30.0
    root_rotation_per_frame_limit_deg: float = 30.0
    # Ground-plane turn around camera_up. Profile sprites are already
    # registered; a 180° yaw is "walk the other way" and is not a HoMM3
    # in-place clip. Roll/pitch still use root_rotation_limit_deg.
    root_rotation_camera_up_limit_deg: float = 45.0
    # Initial root search scores the bind pose. Spread wings plus yaw is a
    # cheap silhouette win. Pose bones first, then search camera_up.
    root_rotation_defer_camera_up: bool = True
    root_rotation_coarse_step_deg: float = 30.0
    root_rotation_refine_radius_deg: float = 20.0
    root_rotation_refine_step_deg: float = 2.5
    depth_weight: float = 0.65
    silhouette_weight: float = 0.35
    depth_tolerance: float = 0.08
    depth_robust_delta: float = 0.12
    # Lab a,b on every candidate. Sprite vs unlit mesh albedo: lightness
    # disagrees, hue of skin/cloth/weapon still separates a front blob from
    # a back or a 90° tumble. 0 disables RGB raster and the chroma term.
    chroma_weight: float = 0.0
    chroma_tolerance: float = 0.10
    chroma_robust_delta: float = 0.12
    chroma_error_scale: float = 80.0
    # Integer upsample of ``resolution`` for the unlit RGB / Lab canvas when
    # chroma_weight > 0 and chroma_resolution is None. 96×86 is too coarse
    # for hue; 4× is 384×344.
    chroma_scale: int = 4
    chroma_resolution: tuple[int, int] | None = None
    seed_previous_frame: bool = True
    # After copying the previous pose and the root search, swing distal bones
    # toward pixels that appeared on the current sprite and left the previous
    # sprite. Local one-bone search then starts from that primed pose.
    sprite_delta_init_enabled: bool = True
    sprite_delta_init_max_pairs: int = 2
    sprite_delta_init_min_component_area: int = 12
    sprite_delta_init_min_bone_depth: int = 3
    sprite_delta_init_min_angle_deg: float = 8.0
    sprite_delta_init_min_radius_px: float = 4.0
    sprite_delta_init_max_tip_distance_px: float = 128.0
    sprite_delta_init_max_centroid_distance_px: float = 128.0
    sprite_delta_init_max_area_ratio: float = 4.0
    sprite_delta_init_min_displacement_alignment: float = 0.15
    sprite_delta_init_depth_tolerance: float = 0.12
    sprite_delta_init_dilate_px: int = 4
    predicted_alpha_threshold: float = 0.01
    # Optional RGB semantic interleave. Geometry remains the primary score;
    # every Nth exact proposal wave rescores its geometric leaders using the
    # unlit CUDA RGB raster, then folds that score back into the same wave.
    semantic_enabled: bool = False
    semantic_model_id: str = "google/siglip2-base-patch16-512"
    semantic_embedding_layer: str = "projected"
    semantic_embedding_layers: tuple[str, ...] = ("projected",)
    semantic_pooling: str = "mean"
    semantic_subject_crop: bool = True
    semantic_subject_padding_frac: float = 0.18
    semantic_weight: float = 0.15
    semantic_candidate_top_k: int = 4
    semantic_batch_size: int = 8
    semantic_interleave_every: int = 4
    semantic_eval_budget: int = 512
    # Optional dense patch-token comparator. It uses the same raster RGB image
    # but keeps spatial local matching separate from the global cosine channel.
    dense_semantic_enabled: bool = False
    dense_semantic_model_id: str = "google/siglip2-base-patch16-512"
    dense_semantic_feature_layers: tuple[str, ...] = ("last",)
    dense_semantic_local_radius: int = 1
    dense_semantic_position_weight: float = 0.15
    dense_semantic_weight: float = 0.10

    def validate(self) -> None:
        width, height = (int(value) for value in self.resolution)
        if width < 16 or height < 16:
            raise ValueError("resolution must be at least 16x16")
        if not 0 <= int(self.alpha_threshold) <= 255:
            raise ValueError("alpha_threshold must be between 0 and 255")
        if not math.isfinite(float(self.joint_limit_deg)) or float(self.joint_limit_deg) <= 0.0:
            raise ValueError("joint_limit_deg must be positive")
        if not math.isfinite(float(self.coarse_step_deg)) or float(self.coarse_step_deg) <= 0.0:
            raise ValueError("coarse_step_deg must be positive")
        if not math.isfinite(float(self.refine_step_deg)) or float(self.refine_step_deg) <= 0.0:
            raise ValueError("refine_step_deg must be positive")
        if not math.isfinite(float(self.refine_radius_deg)) or float(self.refine_radius_deg) <= 0.0:
            raise ValueError("refine_radius_deg must be positive")
        if not set(self.search_axes) <= {"x", "y", "z"} or not self.search_axes:
            raise ValueError("search_axes must contain one or more of x, y, z")
        if self.bone_order_mode not in {
            "asset",
            "dependency",
            "explicit",
            "camera_near_to_far",
            "pose_near_to_far",
            "leftover_gravity",
        }:
            raise ValueError(
                "bone_order_mode must be asset, dependency, explicit, "
                "camera_near_to_far, pose_near_to_far, or leftover_gravity"
            )
        if self.multi_bone_mode not in {"single", "branch"}:
            raise ValueError("multi_bone_mode must be single or branch")
        if self.bone_order_mode == "leftover_gravity" and self.multi_bone_mode != "single":
            raise ValueError("leftover_gravity requires multi_bone_mode='single'")
        if self.bone_order_mode == "leftover_gravity":
            for name, value in (
                ("leftover_gravity_max_assign_px", self.leftover_gravity_max_assign_px),
                ("leftover_gravity_sigma_px", self.leftover_gravity_sigma_px),
            ):
                if not math.isfinite(float(value)) or float(value) <= 0.0:
                    raise ValueError(f"{name} must be positive")
            for name, value in (
                ("leftover_gravity_extra_weight", self.leftover_gravity_extra_weight),
                ("leftover_gravity_min_pull", self.leftover_gravity_min_pull),
                ("leftover_gravity_depth_gate", self.leftover_gravity_depth_gate),
            ):
                if not math.isfinite(float(value)) or float(value) < 0.0:
                    raise ValueError(f"{name} must be finite and non-negative")
        if int(self.multi_bone_block_size) < 2 or int(self.multi_bone_block_size) > 8:
            raise ValueError("multi_bone_block_size must be between 2 and 8")
        if int(self.multi_bone_rounds) < 1:
            raise ValueError("multi_bone_rounds must be positive")
        for name, value in (
            ("multi_bone_search_radius_deg", self.multi_bone_search_radius_deg),
            ("multi_bone_search_step_deg", self.multi_bone_search_step_deg),
            ("multi_bone_refine_radius_deg", self.multi_bone_refine_radius_deg),
            ("multi_bone_refine_step_deg", self.multi_bone_refine_step_deg),
        ):
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if int(self.multi_bone_max_candidates) < 4:
            raise ValueError("multi_bone_max_candidates must be at least 4")
        if int(self.score_raster_batch) < 1:
            raise ValueError("score_raster_batch must be at least 1; it is the VRAM raster cap, not an off switch")
        if not set(self.root_translation_axes) <= {"forward", "lateral", "vertical"}:
            raise ValueError("root_translation_axes contains an unknown axis")
        if not set(self.root_rotation_axes) <= {
            "camera_forward",
            "camera_right",
            "camera_up",
        }:
            raise ValueError("root_rotation_axes contains an unknown axis")
        for name, value in (
            ("root_translation_limit_body_lengths", self.root_translation_limit_body_lengths),
            ("root_translation_coarse_step_body_lengths", self.root_translation_coarse_step_body_lengths),
            ("root_translation_refine_radius_body_lengths", self.root_translation_refine_radius_body_lengths),
            ("root_translation_refine_step_body_lengths", self.root_translation_refine_step_body_lengths),
            ("root_rotation_limit_deg", self.root_rotation_limit_deg),
            ("root_rotation_coarse_step_deg", self.root_rotation_coarse_step_deg),
            ("root_rotation_refine_radius_deg", self.root_rotation_refine_radius_deg),
            ("root_rotation_refine_step_deg", self.root_rotation_refine_step_deg),
        ):
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if (
            not math.isfinite(float(self.root_rotation_first_frame_limit_deg))
            or float(self.root_rotation_first_frame_limit_deg) < 0.0
        ):
            raise ValueError("root_rotation_first_frame_limit_deg must be finite and non-negative")
        if (
            not math.isfinite(float(self.root_rotation_per_frame_limit_deg))
            or float(self.root_rotation_per_frame_limit_deg) < 0.0
        ):
            raise ValueError("root_rotation_per_frame_limit_deg must be finite and non-negative")
        if (
            not math.isfinite(float(self.root_rotation_camera_up_limit_deg))
            or float(self.root_rotation_camera_up_limit_deg) < 0.0
        ):
            raise ValueError("root_rotation_camera_up_limit_deg must be finite and non-negative")
        if bool(self.root_rotation_defer_camera_up):
            if not bool(self.root_rotation_enabled):
                raise ValueError(
                    "root_rotation_defer_camera_up requires root_rotation_enabled"
                )
            if "camera_up" not in tuple(self.root_rotation_axes):
                raise ValueError(
                    "root_rotation_defer_camera_up requires camera_up in root_rotation_axes"
                )
            if float(self.root_rotation_camera_up_limit_deg) <= 0.0:
                raise ValueError(
                    "root_rotation_defer_camera_up requires a positive camera_up limit"
                )
            if max(
                abs(float(self.root_rotation_first_frame_limit_deg)),
                abs(float(self.root_rotation_per_frame_limit_deg)),
            ) <= 0.0:
                raise ValueError(
                    "root_rotation_defer_camera_up requires a positive first-frame "
                    "or per-frame rotation window"
                )
        for name, value in (
            ("depth_weight", self.depth_weight),
            ("silhouette_weight", self.silhouette_weight),
            ("chroma_weight", self.chroma_weight),
        ):
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if (
            float(self.depth_weight)
            + float(self.silhouette_weight)
            + float(self.chroma_weight)
            <= 0.0
        ):
            raise ValueError("depth_weight, silhouette_weight, and chroma_weight cannot all be zero")
        if float(self.chroma_weight) > 0.0:
            if not math.isfinite(float(self.chroma_tolerance)) or not 0.0 <= float(self.chroma_tolerance) < 1.0:
                raise ValueError("chroma_tolerance must be in [0, 1) when chroma_weight is set")
            if not math.isfinite(float(self.chroma_robust_delta)) or float(self.chroma_robust_delta) <= 0.0:
                raise ValueError("chroma_robust_delta must be positive when chroma_weight is set")
            if not math.isfinite(float(self.chroma_error_scale)) or float(self.chroma_error_scale) <= 0.0:
                raise ValueError("chroma_error_scale must be positive when chroma_weight is set")
            gpu_score_raster_resolution(
                tuple(int(value) for value in self.resolution),
                chroma_weight=float(self.chroma_weight),
                chroma_resolution=self.chroma_resolution,
                chroma_scale=int(self.chroma_scale),
            )
        if not math.isfinite(float(self.depth_tolerance)) or not 0.0 <= float(self.depth_tolerance) < 1.0:
            raise ValueError("depth_tolerance must be in [0, 1)")
        if not math.isfinite(float(self.depth_robust_delta)) or float(self.depth_robust_delta) <= 0.0:
            raise ValueError("depth_robust_delta must be positive")
        if not 0.0 < float(self.predicted_alpha_threshold) <= 1.0:
            raise ValueError("predicted_alpha_threshold must be in (0, 1]")
        if not math.isfinite(float(self.pass_limit_deg)) or float(self.pass_limit_deg) < 0.0:
            raise ValueError("pass_limit_deg must be finite and non-negative; 0 disables the per-pass cap")
        if int(self.packed_axis_batch) < 0:
            raise ValueError("packed_axis_batch must be non-negative; 0 disables packed rasters")
        if not math.isfinite(float(self.pass_improve_epsilon)) or float(self.pass_improve_epsilon) < 0.0:
            raise ValueError("pass_improve_epsilon must be finite and non-negative")
        if not math.isfinite(float(self.unstick_score_floor)) or float(self.unstick_score_floor) < 0.0:
            raise ValueError("unstick_score_floor must be finite and non-negative")
        if int(self.unstick_joint_count) < 0:
            raise ValueError("unstick_joint_count must be non-negative; 0 disables silhouette unstick")
        if int(self.unstick_joint_count) > 0:
            if not math.isfinite(float(self.unstick_limit_deg)) or float(self.unstick_limit_deg) <= 0.0:
                raise ValueError("unstick_limit_deg must be positive when unstick_joint_count is set")
            if int(self.unstick_samples_per_bone) < 3:
                raise ValueError("unstick_samples_per_bone must be at least 3")
            if int(self.unstick_max_candidates) < 1:
                raise ValueError("unstick_max_candidates must be positive")
            combo_bound = int(self.unstick_samples_per_bone) ** int(self.unstick_joint_count)
            if combo_bound > int(self.unstick_max_candidates):
                raise ValueError(
                    "unstick grid exceeds unstick_max_candidates: "
                    f"{self.unstick_samples_per_bone}^{self.unstick_joint_count}="
                    f"{combo_bound} max={int(self.unstick_max_candidates)}"
                )
            if int(self.unstick_max_attempts) < 1:
                raise ValueError("unstick_max_attempts must be positive when unstick_joint_count is set")
        if float(self.pass_limit_deg) > 0.0:
            if not math.isfinite(float(self.pass_step_deg)) or float(self.pass_step_deg) <= 0.0:
                raise ValueError("pass_step_deg must be positive when pass_limit_deg is set")
            if float(self.pass_step_deg) > float(self.pass_limit_deg):
                raise ValueError("pass_step_deg cannot exceed pass_limit_deg")
        if not math.isfinite(float(self.temporal_weight)) or float(self.temporal_weight) < 0.0:
            raise ValueError("temporal_weight must be finite and non-negative")
        if float(self.temporal_weight) > 0.0:
            if not math.isfinite(float(self.temporal_scale_deg)) or float(self.temporal_scale_deg) <= 0.0:
                raise ValueError("temporal_scale_deg must be positive when temporal_weight is set")
            if (
                not math.isfinite(float(self.temporal_root_scale_body_lengths))
                or float(self.temporal_root_scale_body_lengths) <= 0.0
            ):
                raise ValueError("temporal_root_scale_body_lengths must be positive when temporal_weight is set")
        if bool(self.collision_enabled):
            if int(self.collision_sample_count) < 2:
                raise ValueError("collision_sample_count must be at least 2")
            if int(self.collision_geodesic_min_hops) < 1:
                raise ValueError("collision_geodesic_min_hops must be at least 1")
            if (
                not math.isfinite(float(self.collision_margin_body_lengths))
                or float(self.collision_margin_body_lengths) <= 0.0
            ):
                raise ValueError("collision_margin_body_lengths must be positive when collision is enabled")
            if not math.isfinite(float(self.collision_weight)) or float(self.collision_weight) <= 0.0:
                raise ValueError(
                    "collision_weight must be positive when collision_enabled; "
                    "set collision_enabled=False to disable the penalty"
                )
        elif float(self.collision_weight) != 0.0:
            raise ValueError("collision_weight must be 0 when collision_enabled is False")
        if (
            not math.isfinite(float(self.collision_positive_abs_slack))
            or float(self.collision_positive_abs_slack) < 0.0
        ):
            raise ValueError("collision_positive_abs_slack must be finite and non-negative")
        if bool(self.strain_enabled):
            if not math.isfinite(float(self.strain_weight)) or float(self.strain_weight) <= 0.0:
                raise ValueError(
                    "strain_weight must be positive when strain_enabled; "
                    "set strain_enabled=False to disable the penalty"
                )
            if not math.isfinite(float(self.strain_tolerance)) or float(self.strain_tolerance) < 0.0:
                raise ValueError("strain_tolerance must be finite and non-negative")
            if (
                not math.isfinite(float(self.strain_exclusive_weight))
                or float(self.strain_exclusive_weight) <= 0.0
                or float(self.strain_exclusive_weight) > 1.0
            ):
                raise ValueError("strain_exclusive_weight must be in (0, 1]")
            if (
                not math.isfinite(float(self.strain_accept_slack))
                or float(self.strain_accept_slack) < 0.0
            ):
                raise ValueError("strain_accept_slack must be finite and non-negative")
            if (
                not math.isfinite(float(self.strain_min_rest_length_body_lengths))
                or float(self.strain_min_rest_length_body_lengths) <= 0.0
            ):
                raise ValueError("strain_min_rest_length_body_lengths must be positive")
        elif float(self.strain_weight) != 0.0:
            raise ValueError("strain_weight must be 0 when strain_enabled is False")
        if bool(self.occupancy_ignore_ambiguous) or bool(self.unique_vanish_hold):
            if (
                not math.isfinite(float(self.occupancy_ambiguous_ratio))
                or float(self.occupancy_ambiguous_ratio) <= 0.0
                or float(self.occupancy_ambiguous_ratio) > 1.0
            ):
                raise ValueError("occupancy_ambiguous_ratio must be in (0, 1]")
            if (
                not math.isfinite(float(self.occupancy_ambiguous_min_weight))
                or float(self.occupancy_ambiguous_min_weight) <= 0.0
            ):
                raise ValueError("occupancy_ambiguous_min_weight must be positive")
        if int(self.blob_identity_min_overlap) < 1:
            raise ValueError("blob_identity_min_overlap must be at least 1")
        if bool(self.unique_vanish_hold):
            if (
                not math.isfinite(float(self.unique_vanish_frac))
                or float(self.unique_vanish_frac) <= 0.0
                or float(self.unique_vanish_frac) > 1.0
            ):
                raise ValueError("unique_vanish_frac must be in (0, 1]")
            if int(self.unique_vanish_min_area) < 1:
                raise ValueError("unique_vanish_min_area must be at least 1")
            if int(self.unique_vanish_min_bone_depth) < 0:
                raise ValueError("unique_vanish_min_bone_depth must be non-negative")
        if int(self.blob_exhaustive_max_pairs) < 1:
            raise ValueError("blob_exhaustive_max_pairs must be at least 1")
        if int(self.blob_exhaustive_min_component_area) < 1:
            raise ValueError("blob_exhaustive_min_component_area must be at least 1")
        if int(self.blob_exhaustive_min_bone_depth) < 0:
            raise ValueError("blob_exhaustive_min_bone_depth must be non-negative")
        if int(self.blob_exhaustive_max_chain_depth) < 1:
            raise ValueError("blob_exhaustive_max_chain_depth must be at least 1")
        if int(self.blob_exhaustive_block_size) < 1:
            raise ValueError("blob_exhaustive_block_size must be at least 1")
        if int(self.blob_exhaustive_block_size) > int(self.blob_exhaustive_max_chain_depth):
            raise ValueError("blob_exhaustive_block_size cannot exceed blob_exhaustive_max_chain_depth")
        if int(self.blob_exhaustive_dilate_px) < 0:
            raise ValueError("blob_exhaustive_dilate_px must be non-negative")
        for name, value in (
            ("blob_exhaustive_max_tip_distance_px", self.blob_exhaustive_max_tip_distance_px),
            ("blob_exhaustive_max_centroid_distance_px", self.blob_exhaustive_max_centroid_distance_px),
            ("blob_exhaustive_max_area_ratio", self.blob_exhaustive_max_area_ratio),
            ("blob_exhaustive_depth_tolerance", self.blob_exhaustive_depth_tolerance),
        ):
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if not math.isfinite(float(self.blob_exhaustive_min_displacement_alignment)):
            raise ValueError("blob_exhaustive_min_displacement_alignment must be finite")
        if not 0.0 < float(self.blob_exhaustive_predicted_alpha_threshold) <= 1.0:
            raise ValueError("blob_exhaustive_predicted_alpha_threshold must be in (0, 1]")
        if bool(self.sprite_delta_init_enabled) and not bool(self.seed_previous_frame):
            raise ValueError("sprite_delta_init_enabled requires seed_previous_frame")
        if int(self.sprite_delta_init_max_pairs) < 1:
            raise ValueError("sprite_delta_init_max_pairs must be at least 1")
        if int(self.sprite_delta_init_min_component_area) < 1:
            raise ValueError("sprite_delta_init_min_component_area must be at least 1")
        if int(self.sprite_delta_init_min_bone_depth) < 0:
            raise ValueError("sprite_delta_init_min_bone_depth must be non-negative")
        if int(self.sprite_delta_init_dilate_px) < 0:
            raise ValueError("sprite_delta_init_dilate_px must be non-negative")
        if (
            not math.isfinite(float(self.sprite_delta_init_min_angle_deg))
            or float(self.sprite_delta_init_min_angle_deg) <= 0.0
        ):
            raise ValueError("sprite_delta_init_min_angle_deg must be positive")
        if (
            not math.isfinite(float(self.sprite_delta_init_min_radius_px))
            or float(self.sprite_delta_init_min_radius_px) <= 0.0
        ):
            raise ValueError("sprite_delta_init_min_radius_px must be positive")
        for name, value in (
            ("sprite_delta_init_max_tip_distance_px", self.sprite_delta_init_max_tip_distance_px),
            ("sprite_delta_init_max_centroid_distance_px", self.sprite_delta_init_max_centroid_distance_px),
            ("sprite_delta_init_max_area_ratio", self.sprite_delta_init_max_area_ratio),
            ("sprite_delta_init_depth_tolerance", self.sprite_delta_init_depth_tolerance),
        ):
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if not math.isfinite(float(self.sprite_delta_init_min_displacement_alignment)):
            raise ValueError("sprite_delta_init_min_displacement_alignment must be finite")
        if bool(self.semantic_enabled) or bool(self.dense_semantic_enabled):
            if int(self.semantic_candidate_top_k) < 1:
                raise ValueError("semantic_candidate_top_k must be positive")
            if int(self.semantic_batch_size) < 1:
                raise ValueError("semantic_batch_size must be positive")
            if int(self.semantic_interleave_every) < 1:
                raise ValueError("semantic_interleave_every must be positive")
            if int(self.semantic_eval_budget) < 0:
                raise ValueError("semantic_eval_budget must be non-negative; zero means unlimited")
        if bool(self.semantic_enabled):
            if not str(self.semantic_model_id).strip():
                raise ValueError("semantic_model_id cannot be empty when semantic_enabled")
            if not math.isfinite(float(self.semantic_weight)) or float(self.semantic_weight) < 0.0:
                raise ValueError("semantic_weight must be finite and non-negative")
            if not self.semantic_embedding_layers:
                raise ValueError("semantic_embedding_layers cannot be empty when semantic_enabled")
        if bool(self.dense_semantic_enabled):
            if not str(self.dense_semantic_model_id).strip():
                raise ValueError("dense_semantic_model_id cannot be empty when dense semantics are enabled")
            if not self.dense_semantic_feature_layers:
                raise ValueError("dense_semantic_feature_layers cannot be empty")
            if int(self.dense_semantic_local_radius) < 0:
                raise ValueError("dense_semantic_local_radius must be non-negative")
            if not math.isfinite(float(self.dense_semantic_position_weight)) or float(self.dense_semantic_position_weight) < 0.0:
                raise ValueError("dense_semantic_position_weight must be finite and non-negative")
            if not math.isfinite(float(self.dense_semantic_weight)) or float(self.dense_semantic_weight) < 0.0:
                raise ValueError("dense_semantic_weight must be finite and non-negative")

    def dense_semantic_active(self) -> bool:
        return bool(self.dense_semantic_enabled) and float(self.dense_semantic_weight) > 0.0


def encode_dense_target_grids_from_rgb_hwc(
    scorer,
    rgb,
    *,
    batch_size: int,
    subject_crop: bool,
    subject_padding_frac: float,
) -> list[dict[str, Any]]:
    """Cache one DINOv3 grid dict per sprite from GPU RGB at the score raster size."""
    if not callable(getattr(scorer, "extract_layers_from_rgb_hwc", None)):
        raise TypeError("dense semantic scorer must implement extract_layers_from_rgb_hwc")
    if int(batch_size) < 1:
        raise ValueError("semantic_batch_size must be positive")
    rgb_batch = rgb
    if bool(subject_crop):
        rgb_batch = crop_rgb_hwc_subject_square(
            rgb,
            float(subject_padding_frac),
        )
    if isinstance(rgb_batch, (list, tuple)):
        frames = list(rgb_batch)
    else:
        frames = [rgb_batch[index] for index in range(int(rgb_batch.shape[0]))]
    if not frames:
        raise ValueError("dense semantic target RGB batch is empty")
    grids: list[dict[str, Any]] = []
    for start in range(0, len(frames), int(batch_size)):
        chunk = frames[start : start + int(batch_size)]
        extracted = scorer.extract_layers_from_rgb_hwc(chunk)
        count = int(next(iter(extracted.values())).shape[0])
        if count != len(chunk):
            raise RuntimeError(
                "dense semantic target encode length drifted: "
                f"grids={count} rgb={len(chunk)}"
            )
        for local in range(count):
            grids.append(
                {
                    layer: values[local : local + 1].detach()
                    for layer, values in extracted.items()
                }
            )
    if len(grids) != len(frames):
        raise RuntimeError(
            "dense semantic target grid count does not match RGB frames: "
            f"{len(grids)} vs {len(frames)}"
        )
    return grids


def _axis_index(axis: str) -> int:
    return {"x": 0, "y": 1, "z": 2}[axis]


def _inclusive_grid(minimum: float, maximum: float, step: float) -> np.ndarray:
    """Return a stable degree grid with both endpoints and zero when possible."""
    values = np.arange(float(minimum), float(maximum) + float(step) * 0.5, float(step))
    values = np.clip(values, float(minimum), float(maximum))
    values = np.concatenate((values, np.asarray((minimum, maximum, 0.0), dtype=np.float64)))
    return np.unique(np.round(values, decimals=7))


ROOT_ROTATION_AXIS_ORDER = ("camera_forward", "camera_right", "camera_up")


def root_rotation_axis_envelope_deg(
    axis: str,
    *,
    envelope_deg: float,
    camera_up_limit_deg: float,
) -> float:
    """Absolute extra-rotation cap for one camera axis, from identity.

    ``camera_up`` is the ground-plane turn (facing the other walk direction).
    Roll around ``camera_forward`` and pitch around ``camera_right`` keep
    ``envelope_deg``.
    """
    name = str(axis)
    if name not in ROOT_ROTATION_AXIS_ORDER:
        raise ValueError(
            "root rotation axis must be camera_forward, camera_right, or camera_up"
        )
    general = abs(float(envelope_deg))
    if name != "camera_up":
        return general
    return min(general, abs(float(camera_up_limit_deg)))


def root_rotation_axis_envelopes_deg(
    *,
    envelope_deg: float,
    camera_up_limit_deg: float,
) -> tuple[float, float, float]:
    return tuple(
        root_rotation_axis_envelope_deg(
            axis,
            envelope_deg=envelope_deg,
            camera_up_limit_deg=camera_up_limit_deg,
        )
        for axis in ROOT_ROTATION_AXIS_ORDER
    )


def root_rotation_axes_for_phase(
    axes: Sequence[str],
    *,
    defer_camera_up: bool,
    phase: str,
) -> tuple[str, ...]:
    """Which camera axes may rotate during one root-search phase.

    ``initial`` runs on the bind pose. ``after_joints`` runs after bones have
    been posed. Deferring ``camera_up`` keeps spread-wing bind silhouettes
    from winning by turning the whole body.
    """
    ordered = tuple(str(axis) for axis in axes)
    unknown = [axis for axis in ordered if axis not in ROOT_ROTATION_AXIS_ORDER]
    if unknown:
        raise ValueError(
            "root rotation axis must be camera_forward, camera_right, or camera_up"
        )
    if phase not in {"initial", "after_joints"}:
        raise ValueError("root rotation phase must be initial or after_joints")
    if not bool(defer_camera_up):
        return ordered
    if "camera_up" not in ordered:
        raise ValueError(
            "root_rotation_defer_camera_up requires camera_up in root_rotation_axes"
        )
    if phase == "initial":
        return tuple(axis for axis in ordered if axis != "camera_up")
    return ("camera_up",)


def root_rotation_search_window_deg(
    *,
    frame_position: int,
    limit_deg: float,
    first_frame_limit_deg: float,
    per_frame_limit_deg: float,
) -> float:
    """How far one frame may move from the current heading.

    Frame 00 uses ``first_frame_limit_deg`` (profile heading is already
    registered). Later frames use ``per_frame_limit_deg`` so a 90° tumble
    cannot win in a single step. Both are clipped to ``limit_deg``.
    """
    envelope = abs(float(limit_deg))
    first = abs(float(first_frame_limit_deg))
    per_frame = abs(float(per_frame_limit_deg))
    window = first if int(frame_position) == 0 else per_frame
    return min(envelope, window)


def root_rotation_search_bounds(
    current_deg: float,
    *,
    frame_position: int,
    limit_deg: float,
    first_frame_limit_deg: float,
    per_frame_limit_deg: float,
) -> tuple[float, float]:
    """Inclusive degree interval for one root-rotation axis on one frame."""
    envelope = abs(float(limit_deg))
    window = root_rotation_search_window_deg(
        frame_position=frame_position,
        limit_deg=envelope,
        first_frame_limit_deg=first_frame_limit_deg,
        per_frame_limit_deg=per_frame_limit_deg,
    )
    current = float(current_deg)
    return max(-envelope, current - window), min(envelope, current + window)


def root_rotation_search_limit_deg(
    limit_deg: float,
    *,
    frame_position: int,
    first_frame_limit_deg: float,
    per_frame_limit_deg: float | None = None,
) -> float:
    """Window used for the coarse root-rotation grid on one frame."""
    per_frame = (
        float(first_frame_limit_deg)
        if per_frame_limit_deg is None
        else float(per_frame_limit_deg)
    )
    return root_rotation_search_window_deg(
        frame_position=frame_position,
        limit_deg=limit_deg,
        first_frame_limit_deg=first_frame_limit_deg,
        per_frame_limit_deg=per_frame,
    )


def pass_angle_grid(
    current_deg: float,
    *,
    joint_limit_deg: float,
    pass_limit_deg: float,
    pass_step_deg: float,
) -> np.ndarray:
    """Return the angles allowed on one bone axis during one interleaved pass.

    The window is ``current +/- pass_limit_deg``, clipped to the joint limit.
    Zero is not injected: a rest-pose 0 degree sample would skip the 10-degree
    cap when the bone is already away from rest.
    """
    current = float(current_deg)
    joint_limit = float(joint_limit_deg)
    pass_limit = float(pass_limit_deg)
    step = float(pass_step_deg)
    if pass_limit <= 0.0:
        raise ValueError("pass_angle_grid requires a positive pass_limit_deg")
    if step <= 0.0:
        raise ValueError("pass_angle_grid requires a positive pass_step_deg")
    lo = max(-joint_limit, current - pass_limit)
    hi = min(joint_limit, current + pass_limit)
    if hi < lo:
        raise ValueError("pass_angle_grid produced an empty window")
    values = np.arange(lo, hi + step * 0.5, step)
    values = np.clip(values, lo, hi)
    values = np.concatenate((values, np.asarray((lo, hi, current), dtype=np.float64)))
    return np.unique(np.round(values, decimals=7))


def order_indices_camera_near_to_far(
    indices: Sequence[int],
    origins: np.ndarray,
    camera_forward: np.ndarray,
) -> tuple[int, ...]:
    """Return ``indices`` sorted from camera-near to camera-far.

    ``camera_forward`` is the camera-to-subject ray. A larger projection onto
    that ray is farther into the scene. Equal depths keep input order.
    """
    nodes = tuple(int(index) for index in indices)
    if not nodes:
        raise ValueError("camera_near_to_far bone order requires at least one bone")
    points = np.asarray(origins, dtype=np.float64)
    if points.shape != (len(nodes), 3):
        raise ValueError(
            "camera_near_to_far origins must have shape (bones, 3) aligned with indices"
        )
    if not np.isfinite(points).all():
        raise ValueError("camera_near_to_far origins must be finite")
    forward = np.asarray(camera_forward, dtype=np.float64).reshape(-1)
    if forward.shape != (3,) or not np.isfinite(forward).all():
        raise ValueError("camera_near_to_far requires a finite 3-vector camera_forward")
    length = float(np.linalg.norm(forward))
    if length <= 1e-8:
        raise ValueError("camera_near_to_far camera_forward is degenerate")
    depth = points @ (forward / length)
    order = np.argsort(depth, kind="stable")
    return tuple(nodes[int(index)] for index in order.tolist())


def pack_axis_job_chunks(job_lengths: Sequence[int], max_batch: int) -> tuple[tuple[int, int], ...]:
    """Pack whole 1D axis jobs into rasters that stay within ``max_batch`` poses.

    A job is never split.  If one job is larger than the batch cap, that is
    a configuration error rather than a silent partial search.
    """
    if int(max_batch) < 1:
        raise ValueError("packed_axis_batch must be at least 1 when packing axis jobs")
    lengths = [int(value) for value in job_lengths]
    if any(length < 1 for length in lengths):
        raise ValueError("axis jobs must contain at least one candidate")
    too_large = [length for length in lengths if length > int(max_batch)]
    if too_large:
        raise ValueError(
            "an axis window has more candidates than packed_axis_batch: "
            f"job={max(too_large)} packed_axis_batch={int(max_batch)}; "
            "increase packed_axis_batch or pass_step_deg"
        )
    chunks: list[tuple[int, int]] = []
    start = 0
    used = 0
    for index, length in enumerate(lengths):
        if start < index and used + length > int(max_batch):
            chunks.append((start, index))
            start = index
            used = 0
        used += length
    if lengths:
        chunks.append((start, len(lengths)))
    return tuple(chunks)


def score_raster_chunks(count: int, max_batch: int) -> tuple[tuple[int, int], ...]:
    """Split a candidate wave into rasters that stay within ``max_batch`` poses.

    The search is not reduced. Each slice is scored completely, then the
    scalar scores are concatenated. A zero or negative cap is a config error.
    """
    if int(max_batch) < 1:
        raise ValueError("score_raster_batch must be at least 1")
    total = int(count)
    if total < 1:
        raise ValueError("score raster needs at least one candidate")
    width = int(max_batch)
    return tuple((start, min(start + width, total)) for start in range(0, total, width))


def score_meaningfully_higher(previous_score: float, current_score: float, epsilon: float) -> bool:
    """True when current is a real gain over the previous job, not noise."""
    if not math.isfinite(float(previous_score)):
        raise ValueError("previous job score must be finite")
    if not math.isfinite(float(current_score)):
        raise ValueError("current job score must be finite")
    if not math.isfinite(float(epsilon)) or float(epsilon) < 0.0:
        raise ValueError("pass_improve_epsilon must be finite and non-negative")
    return float(current_score) > float(previous_score) + float(epsilon)


def missing_target_silhouette(target_mask: np.ndarray, predicted_mask: np.ndarray, *, threshold: float) -> np.ndarray:
    """Pixels the target treats as figure that the current pose does not cover."""
    target = np.asarray(target_mask, dtype=np.float32) > 0.5
    predicted = np.asarray(predicted_mask, dtype=np.float32) > float(threshold)
    if target.shape != predicted.shape:
        raise ValueError("target and predicted silhouette masks must have the same shape")
    return target & ~predicted


def label_binary_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """4-connected labels for a boolean mask.  Background stays 0."""
    binary = np.asarray(mask, dtype=bool)
    if binary.ndim != 2:
        raise ValueError("silhouette masks must be 2D")
    labels = np.zeros(binary.shape, dtype=np.int32)
    height, width = binary.shape
    count = 0
    for row in range(height):
        for column in range(width):
            if not binary[row, column] or labels[row, column] != 0:
                continue
            count += 1
            pending = [(row, column)]
            labels[row, column] = count
            while pending:
                current_row, current_column = pending.pop()
                for next_row, next_column in (
                    (current_row - 1, current_column),
                    (current_row + 1, current_column),
                    (current_row, current_column - 1),
                    (current_row, current_column + 1),
                ):
                    if (
                        0 <= next_row < height
                        and 0 <= next_column < width
                        and binary[next_row, next_column]
                        and labels[next_row, next_column] == 0
                    ):
                        labels[next_row, next_column] = count
                        pending.append((next_row, next_column))
    return labels, count


def nearest_joint_indices(
    joint_xy: np.ndarray,
    missing_mask: np.ndarray,
    count: int,
) -> tuple[tuple[int, ...], np.ndarray]:
    """Return the ``count`` joint indices closest to any missing silhouette pixel."""
    joints = np.asarray(joint_xy, dtype=np.float64)
    if joints.ndim != 2 or joints.shape[1] != 2:
        raise ValueError("joint_xy must have shape (joints, 2)")
    if int(count) < 1:
        raise ValueError("unstick_joint_count must be positive when selecting joints")
    missing = np.asarray(missing_mask, dtype=bool)
    hole_rows, hole_cols = np.nonzero(missing)
    if hole_rows.size == 0:
        raise ValueError("no missing target silhouette pixels")
    hole_xy = np.stack((hole_cols, hole_rows), axis=1).astype(np.float64)
    distances = np.sqrt(((joints[:, None, :] - hole_xy[None, :, :]) ** 2).sum(axis=2)).min(axis=1)
    order = np.argsort(distances, kind="stable")
    keep = int(min(int(count), int(len(order))))
    chosen = tuple(int(index) for index in order[:keep].tolist())
    return chosen, distances[list(chosen)]


def unstick_angle_samples(
    current_deg: float,
    *,
    unstick_limit_deg: float,
    joint_limit_deg: float,
    sample_count: int,
) -> np.ndarray:
    """Wide 1D samples around the current angle, always including the current value.

    Samples are ``current + linspace(-limit, +limit)`` and then clamped to the
    joint limit.  Linspace over the already-clamped interval would put the
    midpoint at ``(lo+hi)/2`` instead of ``current``; concatenating ``current``
    afterward then creates ``sample_count+1`` values and the Cartesian product
    exceeds ``unstick_max_candidates``.
    """
    if int(sample_count) < 3:
        raise ValueError("unstick_samples_per_bone must be at least 3")
    current = float(current_deg)
    limit = float(unstick_limit_deg)
    joint_limit = float(joint_limit_deg)
    if not math.isfinite(current) or not math.isfinite(limit) or not math.isfinite(joint_limit):
        raise ValueError("unstick angle samples require finite current, limit, and joint_limit")
    if limit <= 0.0:
        raise ValueError("unstick_limit_deg must be positive")
    if joint_limit <= 0.0:
        raise ValueError("joint_limit_deg must be positive")
    offsets = np.linspace(-limit, limit, int(sample_count), dtype=np.float64)
    if not np.any(np.isclose(offsets, 0.0, atol=1e-9, rtol=0.0)):
        offsets[int(np.argmin(np.abs(offsets)))] = 0.0
    values = np.clip(current + offsets, -joint_limit, joint_limit)
    unique = np.unique(np.round(values, decimals=7))
    if unique.size < 2:
        raise ValueError("unstick angle window collapsed to a single sample")
    if int(unique.size) > int(sample_count):
        raise ValueError(
            "unstick_angle_samples produced more values than sample_count: "
            f"{int(unique.size)} > {int(sample_count)}"
        )
    return unique


def occupied_visible_depth(depth: np.ndarray, occupied: np.ndarray) -> np.ndarray:
    """Keep far occupied pixels visible; empty stays 0, same as unscored background."""
    visible = np.asarray(depth, dtype=np.float32).copy()
    filled = np.asarray(occupied, dtype=bool)
    if filled.any():
        visible[filled] = np.maximum(visible[filled], np.float32(16.0 / 255.0))
    visible[~filled] = np.float32(0.0)
    return visible


def compose_depth_silhouette_panel(
    target_depth: np.ndarray,
    predicted_depth: np.ndarray,
    target_mask: np.ndarray,
    predicted_mask: np.ndarray,
    *,
    frame: int,
    label: str = "",
    scale: int = 4,
    predicted_alpha_threshold: float = 0.01,
) -> Image.Image:
    """Build the 3-panel target | candidate | overlay image used by live preview and GIFs."""
    target_depth = np.asarray(target_depth, dtype=np.float32)
    predicted_depth = np.asarray(predicted_depth, dtype=np.float32)
    target_mask = np.asarray(target_mask, dtype=np.float32)
    predicted_mask = np.asarray(predicted_mask, dtype=np.float32)
    if target_depth.ndim != 2 or predicted_depth.shape != target_depth.shape:
        raise ValueError("depth panels must be matching 2D arrays")
    if target_mask.shape != target_depth.shape or predicted_mask.shape != target_depth.shape:
        raise ValueError("mask panels must match the depth panel shape")
    if int(scale) < 1:
        raise ValueError("preview scale must be positive")
    height, width = target_depth.shape
    threshold = float(predicted_alpha_threshold)
    target_foreground = target_mask > 0.5
    predicted_foreground = predicted_mask > threshold
    target = Image.fromarray(
        np.clip(np.rint(occupied_visible_depth(target_depth, target_foreground) * 255.0), 0, 255).astype(np.uint8),
        "L",
    ).convert("RGB")
    candidate = Image.fromarray(
        np.clip(np.rint(occupied_visible_depth(predicted_depth, predicted_foreground) * 255.0), 0, 255).astype(np.uint8),
        "L",
    ).convert("RGB")
    overlay = np.zeros((height, width, 3), dtype=np.uint8)
    overlay[target_foreground & ~predicted_foreground] = (235, 45, 45)
    overlay[predicted_foreground & ~target_foreground] = (45, 105, 240)
    overlay[target_foreground & predicted_foreground] = (35, 210, 100)
    caption = str(label).strip() or f"target depth f{int(frame):02d}"
    panel_height = height + 18
    canvas = Image.new("RGB", (width * 3, panel_height), (24, 24, 24))
    canvas.paste(target, (0, 18))
    canvas.paste(candidate, (width, 18))
    canvas.paste(Image.fromarray(overlay, "RGB"), (width * 2, 18))
    draw = ImageDraw.Draw(canvas)
    draw.text((4, 3), caption[:72], fill=(240, 240, 240))
    draw.text((width + 4, 3), "GPU candidate depth", fill=(240, 240, 240))
    draw.text((width * 2 + 4, 3), "overlay R=target B=candidate G=shared", fill=(240, 240, 240))
    if int(scale) != 1:
        canvas = canvas.resize((canvas.width * int(scale), canvas.height * int(scale)), Image.Resampling.NEAREST)
    return canvas


def compose_chroma_occupancy_panel(
    target_rgb: np.ndarray,
    predicted_rgb: np.ndarray,
    target_mask: np.ndarray,
    predicted_mask: np.ndarray,
    *,
    frame: int,
    label: str = "",
    scale: int = 4,
    predicted_alpha_threshold: float = 0.01,
) -> Image.Image:
    """Build target RGB | unlit mesh RGB | occupancy overlay for chroma search."""
    target_rgb = np.asarray(target_rgb, dtype=np.float32)
    predicted_rgb = np.asarray(predicted_rgb, dtype=np.float32)
    target_mask = np.asarray(target_mask, dtype=np.float32)
    predicted_mask = np.asarray(predicted_mask, dtype=np.float32)
    if target_rgb.ndim != 3 or target_rgb.shape[-1] != 3:
        raise ValueError("chroma target must be HxWx3")
    if predicted_rgb.shape != target_rgb.shape:
        raise ValueError("chroma candidate RGB must match the target RGB shape")
    if target_mask.shape != target_rgb.shape[:2] or predicted_mask.shape != target_rgb.shape[:2]:
        raise ValueError("chroma masks must match the RGB panel shape")
    if int(scale) < 1:
        raise ValueError("preview scale must be positive")
    height, width = target_mask.shape
    threshold = float(predicted_alpha_threshold)
    target_foreground = target_mask > 0.5
    predicted_foreground = predicted_mask > threshold
    target = Image.fromarray(
        np.clip(np.rint(np.clip(target_rgb, 0.0, 1.0) * 255.0), 0, 255).astype(np.uint8),
        "RGB",
    )
    candidate = Image.fromarray(
        np.clip(np.rint(np.clip(predicted_rgb, 0.0, 1.0) * 255.0), 0, 255).astype(np.uint8),
        "RGB",
    )
    overlay = np.zeros((height, width, 3), dtype=np.uint8)
    overlay[target_foreground & ~predicted_foreground] = (235, 45, 45)
    overlay[predicted_foreground & ~target_foreground] = (45, 105, 240)
    overlay[target_foreground & predicted_foreground] = (35, 210, 100)
    caption = str(label).strip() or f"target chroma f{int(frame):02d}"
    panel_height = height + 18
    canvas = Image.new("RGB", (width * 3, panel_height), (24, 24, 24))
    canvas.paste(target, (0, 18))
    canvas.paste(candidate, (width, 18))
    canvas.paste(Image.fromarray(overlay, "RGB"), (width * 2, 18))
    draw = ImageDraw.Draw(canvas)
    draw.text((4, 3), caption[:72], fill=(240, 240, 240))
    draw.text((width + 4, 3), "GPU unlit RGB", fill=(240, 240, 240))
    draw.text((width * 2 + 4, 3), "overlay R=target B=candidate G=shared", fill=(240, 240, 240))
    if int(scale) != 1:
        canvas = canvas.resize((canvas.width * int(scale), canvas.height * int(scale)), Image.Resampling.NEAREST)
    return canvas


def live_preview_due(
    *,
    visit: int,
    every: int,
    elapsed_s: float,
    min_interval_s: float,
    force: bool,
) -> bool:
    """Decide whether this visit may push a new live panel.

    ``preview_every`` still means “every N bone visits.”  ``min_interval_s``
    caps how often the notebook frontend is asked to replace a large PNG.
    Depth-only search visits bones faster than Cursor can ack widget/image
    updates; unthrottled refreshes stall the kernel while the solver waits.
    """
    if int(every) < 1:
        raise ValueError("preview_every must be at least 1")
    if int(visit) < 1:
        raise ValueError("preview visit must be at least 1")
    if not math.isfinite(float(min_interval_s)) or float(min_interval_s) <= 0.0:
        raise ValueError("live preview min_interval_s must be positive")
    if bool(force):
        return True
    if int(visit) % int(every) != 0:
        return False
    return float(elapsed_s) >= float(min_interval_s)


class GpuDepthLivePreview:
    """Refresh one notebook output with the current GPU depth overlay.

    This is the one_bone_depth analog of the hybrid notebook's live preview.
    PNG bytes go through IPython's ``display_id`` path so a reused filename
    cannot stay stale.  ipywidgets is not used: Cursor's widget comms block
    the kernel after a burst of updates.
    """

    display_id = "gpu_depth_live_preview"
    heartbeat_s = 5.0

    def __init__(
        self,
        path: str | Path,
        *,
        every: int,
        scale: int,
        alpha_threshold: float,
        min_interval_s: float = 1.0,
    ) -> None:
        if int(every) < 1:
            raise ValueError("preview_every must be at least 1")
        if int(scale) < 1:
            raise ValueError("live preview scale must be at least 1")
        if not math.isfinite(float(min_interval_s)) or float(min_interval_s) <= 0.0:
            raise ValueError("live preview min_interval_s must be positive")
        try:
            from IPython.display import display, update_display, Image as IPImage
        except ImportError as exc:
            raise RuntimeError(
                "live_preview=True requires IPython.display in the notebook kernel"
            ) from exc
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.every = int(every)
        self.scale = int(scale)
        self.alpha_threshold = float(alpha_threshold)
        self.min_interval_s = float(min_interval_s)
        self._display = display
        self._update_display = update_display
        self._IPImage = IPImage
        self._n = 0
        self._started = False
        self._last_shown: float | None = None

    def will_emit(self, *, force: bool) -> bool:
        elapsed = math.inf if self._last_shown is None else (time.perf_counter() - self._last_shown)
        return live_preview_due(
            visit=self._n + 1,
            every=self.every,
            elapsed_s=elapsed,
            min_interval_s=self.min_interval_s,
            force=force,
        )

    def skip_visit(self) -> None:
        self._n += 1

    def show(
        self,
        *,
        frame: int,
        label: str,
        target_depth: np.ndarray,
        predicted_depth: np.ndarray,
        target_mask: np.ndarray,
        predicted_mask: np.ndarray,
        target_rgb: np.ndarray | None = None,
        predicted_rgb: np.ndarray | None = None,
        force: bool = False,
    ) -> None:
        if not self.will_emit(force=force):
            self.skip_visit()
            return
        if target_rgb is not None or predicted_rgb is not None:
            if target_rgb is None or predicted_rgb is None:
                raise ValueError("chroma live preview requires both target_rgb and predicted_rgb")
            canvas = compose_chroma_occupancy_panel(
                target_rgb,
                predicted_rgb,
                target_mask,
                predicted_mask,
                frame=int(frame),
                label=label,
                scale=self.scale,
                predicted_alpha_threshold=self.alpha_threshold,
            )
        else:
            canvas = compose_depth_silhouette_panel(
                target_depth,
                predicted_depth,
                target_mask,
                predicted_mask,
                frame=int(frame),
                label=label,
                scale=self.scale,
                predicted_alpha_threshold=self.alpha_threshold,
            )
        self.emit_canvas(canvas)

    def emit_canvas(self, canvas: Image.Image) -> None:
        """Push an already-composed panel. Caller already decided this visit emits."""
        buffer = BytesIO()
        canvas.save(buffer, format="PNG", compress_level=0)
        png_bytes = buffer.getvalue()
        self.path.write_bytes(png_bytes)
        image = self._IPImage(data=png_bytes, format="png")
        if self._started:
            self._update_display(image, display_id=self.display_id)
        else:
            self._display(image, display_id=self.display_id)
            self._started = True
        self._n += 1
        self._last_shown = time.perf_counter()


def temporal_bone_penalty(candidate_bones, previous_bones, *, scale_deg: float):
    """Return a [batch] tanh penalty for bounded bone-vector deltas.

    This uses the Frobenius norm of the whole pose delta.  A mean over every
    bone and axis would hide a 10-degree move on one joint inside a 48-bone
    skeleton.
    """
    import torch

    scale = max(math.radians(float(scale_deg)), 1e-6)
    delta = candidate_bones - previous_bones
    return torch.tanh(torch.linalg.vector_norm(delta, dim=(1, 2)) / scale)


class DepthSilhouetteSolver:
    """Exact CUDA depth/silhouette coordinate descent.

    ``multi_bone_mode='single'`` walks one bone at a time in dependency
    order.  When ``pass_limit_deg`` is positive, each axis visit is a short
    local grid and ``multi_bone_rounds`` repeats that walk.  A positive
    ``packed_axis_batch`` scores several of those 1D windows in one raster.
    A stalled pass below ``unstick_score_floor`` runs a GPU multi-bone
    search of the joints nearest missing target silhouette.
    ``'branch'`` mode still tests small connected blocks with the original
    wide search.

    After the skeleton walk, leftover silhouette blobs can name a distal
    bone by skinning influence. ``blob_exhaustive_enabled`` then runs a
    full joint-limit search on that short chain, scored only inside the
    leftover neighborhood.
    """

    def __init__(
        self,
        *,
        src_glb: str | Path,
        camera_fit: str | Path,
        target_frame_dir: str | Path,
        target_depth_dir: str | Path,
        frame_indices: Sequence[int],
        config: DepthSilhouetteConfig | None = None,
    ) -> None:
        import torch

        self.config = config or DepthSilhouetteConfig()
        self.config.validate()
        score_resolution = gpu_score_raster_resolution(
            tuple(int(value) for value in self.config.resolution),
            chroma_weight=float(self.config.chroma_weight),
            chroma_resolution=self.config.chroma_resolution,
            chroma_scale=int(self.config.chroma_scale),
            rgb_upsample=bool(self.config.dense_semantic_active()),
        )
        backend_config = GpuCascadeConfig(
            device="cuda",
            resolution=score_resolution,
            alpha_threshold=int(self.config.alpha_threshold),
            # The exact triangle path does not use the sampled proxy, but the
            # constructor still builds its resident asset tables. Keep those
            # tables at their smallest valid setting for this experiment.
            max_triangles_per_primitive=2048,
            samples_per_triangle=3,
            root_search_enabled=False,
            root_hypotheses=1,
            root_iterations=0,
            articulated_iterations=0,
            fine_iterations=0,
            optimize_root_translation=bool(self.config.root_translation_enabled),
            optimize_root_rotation=bool(self.config.root_rotation_enabled),
            root_translation_axes=tuple(self.config.root_translation_axes),
            root_rotation_axes=tuple(self.config.root_rotation_axes),
            root_translation_limit_body_lengths=float(self.config.root_translation_limit_body_lengths),
            root_rotation_limit_deg=float(self.config.root_rotation_limit_deg),
            root_rotation_limit_optimization_deg=float(self.config.root_rotation_limit_deg),
            root_rotation_camera_up_limit_deg=float(self.config.root_rotation_camera_up_limit_deg),
            # Raster tables only. one_bone owns defer via DepthSilhouetteConfig
            # and root_rotation_axes_for_phase; this config never runs cascade
            # optimize_clip, so it must not demand cascade joint stages.
            root_rotation_defer_camera_up=False,
            optimize_bones=True,
            freeze_root_after_root_stage=True,
            fine_root_enabled=False,
            joint_limit_deg=float(self.config.joint_limit_deg),
            proximal_bone_limit_depth=0,
            proximal_bone_limit_scale=1.0,
            exact_raster_enabled=True,
            depth_target_dir=Path(target_depth_dir).resolve(),
            depth_weight=float(self.config.depth_weight),
            silhouette_weight=float(self.config.silhouette_weight),
            depth_tolerance=float(self.config.depth_tolerance),
            depth_robust_delta=float(self.config.depth_robust_delta),
            chroma_weight=float(self.config.chroma_weight),
            chroma_tolerance=float(self.config.chroma_tolerance),
            chroma_robust_delta=float(self.config.chroma_robust_delta),
            chroma_error_scale=float(self.config.chroma_error_scale),
            chroma_scale=int(self.config.chroma_scale),
            chroma_resolution=self.config.chroma_resolution,
            collision_enabled=bool(self.config.collision_enabled),
            collision_sample_count=int(self.config.collision_sample_count),
            collision_geodesic_min_hops=int(self.config.collision_geodesic_min_hops),
            collision_margin_body_lengths=float(self.config.collision_margin_body_lengths),
            collision_weight=float(self.config.collision_weight),
            skip_tiny_bones=False,
            ik_miss_depth_tolerance=float(self.config.blob_exhaustive_depth_tolerance),
            ik_miss_min_component_area=int(self.config.blob_exhaustive_min_component_area),
            ik_miss_max_pairs=int(self.config.blob_exhaustive_max_pairs),
            ik_miss_predicted_alpha_threshold=float(
                self.config.blob_exhaustive_predicted_alpha_threshold
            ),
            ik_miss_max_tip_distance_px=float(self.config.blob_exhaustive_max_tip_distance_px),
            ik_miss_max_centroid_distance_px=float(
                self.config.blob_exhaustive_max_centroid_distance_px
            ),
            ik_miss_max_area_ratio=float(self.config.blob_exhaustive_max_area_ratio),
            ik_miss_min_displacement_alignment=float(
                self.config.blob_exhaustive_min_displacement_alignment
            ),
            ik_proximal_min_depth=int(self.config.blob_exhaustive_min_bone_depth),
            ik_max_chain_depth=int(self.config.blob_exhaustive_max_chain_depth),
            ik_repair_dilate_px=int(self.config.blob_exhaustive_dilate_px),
            score_centroid_weight=0.0,
            score_occupancy_weight=0.0,
            sdf_weight=0.0,
            return_masks=True,
        )
        self.backend = GpuCascadeExperiment(
            src_glb=src_glb,
            camera_fit=camera_fit,
            target_frame_dir=target_frame_dir,
            frame_indices=frame_indices,
            config=backend_config,
        )
        if self.backend.target_depth is None:
            raise ValueError("depth/silhouette solver requires target_depth_dir")
        if not bool(torch.any(self.backend.target_masks > 0.5).item()):
            raise ValueError("target alpha masks contain no foreground pixels")
        self.frame_indices = self.backend.frame_indices
        self.node_names = self.backend.node_names
        self.bone_indices = self._resolve_bone_order()
        self.bone_names = tuple(self.node_names[index] for index in self.bone_indices)
        self.branch_blocks = self._resolve_branch_blocks()
        self._frame_walk_indices = self.bone_indices
        self._occupancy_ignore_hw: np.ndarray | None = None
        self._lane_previous_unique: dict[str, np.ndarray] | None = None
        self._held_bone_names: set[str] = set()
        self._sprite_delta_moved_bones: set[str] = set()
        self._gravity_unique: dict[str, np.ndarray] | None = None
        self._gravity_fallback_names: tuple[str, ...] = ()
        self._gravity_joint_xy: dict[str, tuple[float, float]] = {}
        self._gravity_unique_depth: dict[str, float] = {}
        self._bone_limit_scale_cpu = self.backend.bone_limit_scales.detach().cpu().numpy()
        self.evaluation_count = 0
        self.semantic_batch_count = 0
        self.semantic_evaluation_count = 0
        self.semantic_embedder = None
        self.semantic_target_vectors: dict[str, np.ndarray] = {}
        self.dense_semantic_scorer = None
        self.dense_semantic_target_grids: list[dict[str, Any]] = []
        self.semantic_target_images: list[Image.Image] = []
        self._temporal_reference = None
        self._live_preview: GpuDepthLivePreview | None = None
        self._solve_started = 0.0
        self._last_heartbeat = 0.0
        self._collision_table = self.backend._collision_table
        self._strain_table = None
        if bool(self.config.dense_semantic_active()) and self.backend.target_rgb is None:
            self.backend._initialize_target_rgb()
        self.target_rgb = self.backend.target_rgb
        self.target_lab_ab = self.backend.target_lab_ab
        print(
            "GPU score raster batch: "
            f"{int(self.config.score_raster_batch)} "
            "(branch pair-grids larger than this are scored in slices; "
            "the search is not reduced)",
            flush=True,
        )
        print(
            "GPU root rotation: "
            f"frame 00 ±{float(self.config.root_rotation_first_frame_limit_deg):.0f}° "
            f"from profile, later ±{float(self.config.root_rotation_per_frame_limit_deg):.0f}° "
            f"from the previous heading (envelope ±{float(self.config.root_rotation_limit_deg):.0f}°, "
            f"camera_up yaw ±{float(self.config.root_rotation_camera_up_limit_deg):.0f}°"
            f", rootYawDeferred={int(bool(self.config.root_rotation_defer_camera_up))}"
            f"{', deferred until after joints' if bool(self.config.root_rotation_defer_camera_up) else ''})",
            flush=True,
        )
        self._initialize_mesh_strain()
        if float(self.config.chroma_weight) > 0.0:
            print(
                "GPU chroma: Lab a,b on every candidate "
                f"(weight={float(self.config.chroma_weight):.2f}, "
                f"raster={int(score_resolution[0])}x{int(score_resolution[1])}, "
                f"proxy={int(self.config.resolution[0])}x{int(self.config.resolution[1])}, "
                f"scale={float(self.config.chroma_error_scale):.0f})",
                flush=True,
            )
        elif bool(self.config.dense_semantic_active()):
            print(
                "GPU dense RGB raster: "
                f"{int(score_resolution[0])}x{int(score_resolution[1])} "
                f"(proxy={int(self.config.resolution[0])}x{int(self.config.resolution[1])}, "
                f"chroma_scale={int(self.config.chroma_scale)})",
                flush=True,
            )
        if (
            (bool(self.config.semantic_enabled) and float(self.config.semantic_weight) > 0.0)
            or (
                bool(self.config.dense_semantic_enabled)
                and float(self.config.dense_semantic_weight) > 0.0
            )
        ):
            self._initialize_semantic_interleave(target_frame_dir)

    def _initialize_mesh_strain(self) -> None:
        if not bool(self.config.strain_enabled):
            self._strain_table = None
            return
        from gpu_mesh_strain import build_backend_strain_table

        self._strain_table = build_backend_strain_table(
            self.backend,
            exclusive_weight=float(self.config.strain_exclusive_weight),
            min_rest_length_body_lengths=float(self.config.strain_min_rest_length_body_lengths),
        )
        report = self._strain_table["report"]
        print(
            "GPU mesh strain: "
            f"edges={report['edgeCount']} primitives={report['primitiveCount']} "
            f"exclusive>={float(report['exclusiveWeight']):.2f} "
            f"minRest={float(report['minRest']):.6f} "
            f"tol={float(self.config.strain_tolerance):.3f} "
            f"weight={float(self.config.strain_weight):.2f} "
            f"acceptSlack={float(self.config.strain_accept_slack):.3f}",
            flush=True,
        )

    def _initialize_semantic_interleave(self, target_frame_dir: str | Path) -> None:
        """Load the paired target RGB frames and cache their vectors once."""
        from dense_semantic_features import DenseFeatureScorer
        from roc_semantic_embedding_match import RocSemanticEmbedder

        paths = [Path(target_frame_dir) / f"{int(frame):02d}.png" for frame in self.frame_indices]
        missing = [path for path in paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"semantic target RGB frame(s) are missing: {missing}")
        global_semantic = bool(self.config.semantic_enabled) and float(self.config.semantic_weight) > 0.0
        if global_semantic:
            # Keep transparent source pixels from becoming black RGB input. The
            # candidate raster uses the same neutral 32/255 matte.
            images = [RocSemanticEmbedder.load_image(path) for path in paths]
            self.semantic_target_images = images
            self.semantic_embedder = RocSemanticEmbedder(
                self.config.semantic_model_id,
                embedding_layer=self.config.semantic_embedding_layer,
                embedding_layers=self.config.semantic_embedding_layers,
                pooling=self.config.semantic_pooling,
                subject_crop=self.config.semantic_subject_crop,
                subject_padding_frac=self.config.semantic_subject_padding_frac,
            )
            for start in range(0, len(images), int(self.config.semantic_batch_size)):
                batch = images[start : start + int(self.config.semantic_batch_size)]
                vectors = self.semantic_embedder.embed_layers(batch)
                for layer, values in vectors.items():
                    self.semantic_target_vectors.setdefault(layer, []).extend(values)
            self.semantic_target_vectors = {
                layer: np.asarray(values, dtype=np.float32)
                for layer, values in self.semantic_target_vectors.items()
            }
            if set(self.semantic_target_vectors) != set(self.semantic_embedder.embedding_layers):
                raise RuntimeError(
                    "semantic target embedding layers do not match the configured layers: "
                    f"expected {self.semantic_embedder.embedding_layers}, got {tuple(self.semantic_target_vectors)}"
                )
        if bool(self.config.dense_semantic_active()):
            if self.backend.target_rgb is None:
                raise RuntimeError(
                    "one_bone dense semantics need GPU target RGB at the score raster size"
                )
            model_id = str(self.config.dense_semantic_model_id)
            family = "dino" if "dino" in model_id.lower() else "auto"
            if family == "dino":
                token_present = bool(os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN"))
                if not token_present:
                    raise RuntimeError(
                        "dense DINOv3 is enabled, but this process has no HF_TOKEN. "
                        "Set the user-scoped HF_TOKEN and start a fresh Python process."
                    )
            self.dense_semantic_scorer = DenseFeatureScorer(
                model_id,
                family=family,
                feature_layer=self.config.dense_semantic_feature_layers[0],
                feature_layers=self.config.dense_semantic_feature_layers,
                device="cuda",
                local_files_only=True,
            )
            self.dense_semantic_target_grids = encode_dense_target_grids_from_rgb_hwc(
                self.dense_semantic_scorer,
                self.backend.target_rgb,
                batch_size=int(self.config.semantic_batch_size),
                subject_crop=bool(self.config.semantic_subject_crop),
                subject_padding_frac=float(self.config.semantic_subject_padding_frac),
            )
            if len(self.dense_semantic_target_grids) != len(self.frame_indices):
                raise RuntimeError(
                    "one_bone dense target grid count does not match frames: "
                    f"{len(self.dense_semantic_target_grids)} vs {len(self.frame_indices)}"
                )
            width, height = (int(value) for value in self.backend.config.resolution)
            print(
                "GPU one_bone dense: CUDA RGB encode fp16 / keep fp32 "
                f"model={model_id} "
                f"raster={width}x{height} "
                f"batch={int(self.config.semantic_batch_size)} "
                "(no PIL; not cascade score_mode)",
                flush=True,
            )

    def _resolve_bone_order(self) -> tuple[int, ...]:
        active = tuple(int(index) for index in self.backend.active_node_indices)
        active_set = set(active)
        if self.config.bone_order_mode == "explicit":
            requested = list(self.config.bone_order)
            unknown = [name for name in requested if name not in self.backend.node_index]
            if unknown:
                raise ValueError(f"bone_order contains unknown bones: {unknown}")
            inactive = [
                name for name in requested
                if self.backend.node_index[name] not in active_set
            ]
            if inactive:
                raise ValueError(f"bone_order contains non-skinned bones: {inactive}")
            ordered = [self.backend.node_index[name] for name in requested]
            ordered.extend(index for index in active if index not in ordered)
            return tuple(ordered)
        if self.config.bone_order:
            requested = list(self.config.bone_order)
            unknown = [name for name in requested if name not in self.backend.node_index]
            if unknown:
                raise ValueError(f"bone_order contains unknown bones: {unknown}")
            ordered = [self.backend.node_index[name] for name in requested]
            ordered.extend(index for index in active if index not in ordered)
            active = tuple(ordered)
        if self.config.bone_order_mode in {"dependency", "leftover_gravity"}:
            return tuple(sorted(active, key=lambda index: (self.backend.node_depths[index], index)))
        if self.config.bone_order_mode in {"camera_near_to_far", "pose_near_to_far"}:
            return self._camera_near_to_far_bone_order(active)
        return tuple(active)

    def _camera_near_to_far_bone_order(self, active: Sequence[int]) -> tuple[int, ...]:
        """Sort bind joint origins from camera-near to camera-far."""
        import torch

        nodes = tuple(int(index) for index in active)
        zero_bones = torch.zeros(
            (1, len(self.backend.asset.nodes), 3),
            dtype=torch.float32,
            device=self.backend.device,
        )
        with torch.no_grad():
            worlds = self.backend._forward_kinematics(
                zero_bones,
                bone_mask=self.backend.active_node_mask,
            )
            origins = worlds[0, list(nodes), :3, 3].detach().cpu().numpy()
            forward = self.backend.camera_forward.detach().cpu().numpy()
        ordered = order_indices_camera_near_to_far(nodes, origins, forward)
        names = [self.node_names[index] for index in ordered]
        print(
            "GPU bone order camera_near_to_far: "
            f"near={','.join(names[:4])} ... far={','.join(names[-4:])} "
            f"bones={len(names)}",
            flush=True,
        )
        return ordered

    def _pose_near_to_far_bone_order(
        self,
        active: Sequence[int],
        state_raw,
        root_translation_raw,
        root_rotation_raw,
    ) -> tuple[int, ...]:
        """Sort current posed joint origins from camera-near to camera-far."""
        import torch

        nodes = tuple(int(index) for index in active)
        bounded = self.backend._bounded_bone_vectors(state_raw)
        with torch.no_grad():
            worlds = self.backend._forward_kinematics(
                bounded,
                bone_mask=self.backend.active_node_mask,
            )
            points = self.backend._root_transform(
                worlds[:, :, :3, 3],
                root_translation_raw,
                root_rotation_raw,
            )
            origins = points[0, list(nodes), :].detach().cpu().numpy()
            forward = self.backend.camera_forward.detach().cpu().numpy()
        return order_indices_camera_near_to_far(nodes, origins, forward)

    def _occupancy_ignore_tensor(self, device, dtype, *, batch: int):
        import torch

        del dtype, batch
        if self._occupancy_ignore_hw is None:
            return None
        return torch.as_tensor(
            self._occupancy_ignore_hw,
            dtype=torch.float32,
            device=device,
        )

    def _lane_node_depth(self, name: str) -> int:
        return int(self.backend.node_depths[int(self.backend.node_index[str(name)])])

    def _lane_influence_maps(self, state_raw, root_translation_raw, root_rotation_raw, *, frame_position: int):
        from roc_gpu_cascade_experiment import compute_search_bone_influence_maps

        height, width = self.backend.target_masks[int(frame_position)].shape[-2:]
        frame_count = len(self.frame_indices)
        clip_bones = state_raw.expand(frame_count, -1, -1).contiguous().clone()
        clip_translation = root_translation_raw.expand(frame_count, -1).contiguous().clone()
        clip_rotation = root_rotation_raw.expand(frame_count, -1).contiguous().clone()
        clip_bones[int(frame_position)] = state_raw[0]
        clip_translation[int(frame_position)] = root_translation_raw[0]
        clip_rotation[int(frame_position)] = root_rotation_raw[0]
        return compute_search_bone_influence_maps(
            self.backend,
            clip_bones,
            clip_translation,
            clip_rotation,
            frame_position=int(frame_position),
            node_indices=self.bone_indices,
            height=int(height),
            width=int(width),
        )

    def _lane_maps(self, state_raw, root_translation_raw, root_rotation_raw, *, frame_position: int):
        from occupancy_lane import occupancy_lane_maps, sprite_visible_unique

        weights = self._lane_influence_maps(
            state_raw,
            root_translation_raw,
            root_rotation_raw,
            frame_position=int(frame_position),
        )
        maps = occupancy_lane_maps(
            weights,
            min_weight=float(self.config.occupancy_ambiguous_min_weight),
            ambiguous_ratio=float(self.config.occupancy_ambiguous_ratio),
        )
        sprite = self.backend.target_masks[int(frame_position)].detach().cpu().numpy() > 0.5
        visible = sprite_visible_unique(maps.unique, sprite)
        return maps, visible

    def _persist_blob_bone(self, blob_mask: np.ndarray, *, min_bone_depth: int) -> str | None:
        from occupancy_lane import persist_blob_bone

        if not bool(self.config.blob_identity_persist):
            return None
        if self._lane_previous_unique is None:
            return None
        unique = {
            name: mask
            for name, mask in self._lane_previous_unique.items()
            if int(self._lane_node_depth(name)) >= int(min_bone_depth)
        }
        if not unique:
            return None
        return persist_blob_bone(
            blob_mask,
            unique,
            node_depth=self._lane_node_depth,
            min_overlap=int(self.config.blob_identity_min_overlap),
        )

    def _apply_occupancy_lane(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
        frame: int,
        progress: bool,
        history: list[dict[str, Any]],
    ):
        """Set occupancy ignore, hold set, and visible-first walk order for this frame."""
        from occupancy_lane import vanished_unique_bones

        self._occupancy_ignore_hw = None
        self._held_bone_names = set()
        self._frame_walk_indices = self.bone_indices
        maps = None
        visible = None
        if (
            bool(self.config.occupancy_ignore_ambiguous)
            or bool(self.config.unique_vanish_hold)
            or self.config.bone_order_mode == "leftover_gravity"
        ):
            maps, visible = self._lane_maps(
                state_raw,
                root_translation_raw,
                root_rotation_raw,
                frame_position=int(frame_position),
            )
        if bool(self.config.occupancy_ignore_ambiguous):
            if maps is None:
                raise RuntimeError("occupancy_ignore_ambiguous requires skinning influence maps")
            self._occupancy_ignore_hw = np.asarray(maps.ambiguous, dtype=np.float32)
        if bool(self.config.unique_vanish_hold) and self._lane_previous_unique is not None:
            if visible is None:
                raise RuntimeError("unique_vanish_hold requires unique influence maps")
            held = vanished_unique_bones(
                self._lane_previous_unique,
                visible,
                min_area=int(self.config.unique_vanish_min_area),
                vanish_frac=float(self.config.unique_vanish_frac),
                min_bone_depth=int(self.config.unique_vanish_min_bone_depth),
                node_depth=self._lane_node_depth,
                exclude=tuple(self._sprite_delta_moved_bones),
            )
            self._held_bone_names = set(held)
        if self.config.bone_order_mode in {"pose_near_to_far", "leftover_gravity"}:
            ordered = self._pose_near_to_far_bone_order(
                self.bone_indices,
                state_raw,
                root_translation_raw,
                root_rotation_raw,
            )
            if self.config.bone_order_mode == "pose_near_to_far":
                self.bone_indices = ordered
                self.bone_names = tuple(self.node_names[index] for index in ordered)
                self.branch_blocks = self._resolve_branch_blocks()
            self._gravity_fallback_names = tuple(
                self.node_names[int(index)]
                for index in ordered
                if str(self.node_names[int(index)]) not in self._held_bone_names
            )
        else:
            self._gravity_fallback_names = ()
        walk = tuple(
            index
            for index in self.bone_indices
            if str(self.node_names[int(index)]) not in self._held_bone_names
        )
        if not walk:
            raise RuntimeError("occupancy lane held every searchable bone")
        self._frame_walk_indices = walk
        if self.config.bone_order_mode == "leftover_gravity":
            if maps is None:
                raise RuntimeError("leftover_gravity requires unique-region influence maps")
            self._prepare_leftover_gravity_tables(
                maps,
                state_raw,
                root_translation_raw,
                root_rotation_raw,
                frame_position=int(frame_position),
            )
        else:
            self._gravity_unique = None
            self._gravity_joint_xy = {}
            self._gravity_unique_depth = {}
        ignore_count = (
            0
            if self._occupancy_ignore_hw is None
            else int(np.count_nonzero(self._occupancy_ignore_hw > 0.5))
        )
        report = {
            "frame": int(frame),
            "framePosition": int(frame_position),
            "stage": "occupancy_lane",
            "ignorePixels": ignore_count,
            "heldBones": sorted(self._held_bone_names),
            "walkNear": [self.node_names[int(index)] for index in self._frame_walk_indices[:4]],
            "walkFar": [self.node_names[int(index)] for index in self._frame_walk_indices[-4:]],
            "spriteDeltaMoved": sorted(self._sprite_delta_moved_bones),
        }
        history.append(report)
        if progress:
            held = ",".join(report["heldBones"]) or "none"
            print(
                f"depth f{int(frame):02d} occupancy-lane "
                f"ignore={ignore_count}px hold={held} "
                f"walk={len(self._frame_walk_indices)}/{len(self.bone_indices)}"
                f"{' gravity' if self.config.bone_order_mode == 'leftover_gravity' else ''}",
                flush=True,
            )
        return state_raw, root_translation_raw, root_rotation_raw

    def _prepare_leftover_gravity_tables(
        self,
        maps,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
    ) -> None:
        from leftover_gravity import unique_median_depths

        unique = {str(name): np.asarray(mask, dtype=bool) for name, mask in maps.unique.items()}
        if not unique:
            raise RuntimeError("leftover_gravity unique-region maps are empty")
        joints = self._projected_joint_xy(state_raw, root_translation_raw, root_rotation_raw)
        joint_xy: dict[str, tuple[float, float]] = {}
        for index in self._frame_walk_indices:
            name = str(self.node_names[int(index)])
            joint_xy[name] = (
                float(joints[0, int(index), 0].item()),
                float(joints[0, int(index), 1].item()),
            )
            if name not in unique:
                raise RuntimeError(f"leftover_gravity is missing a unique map for {name}")
        sprite = self.backend.target_masks[int(frame_position)].detach().cpu().numpy() > 0.5
        depth = self.backend.target_depth[int(frame_position)].detach().cpu().numpy()
        self._gravity_unique = unique
        self._gravity_joint_xy = joint_xy
        self._gravity_unique_depth = unique_median_depths(unique, depth, sprite)

    def _leftover_gravity_reports(
        self,
        predicted_mask: np.ndarray,
        *,
        remaining_names: Sequence[str],
        frame_position: int,
    ) -> dict[str, dict[str, float]]:
        from leftover_gravity import (
            bone_distance_map,
            extra_predicted_mask,
            leftover_gravity_pull,
            leftover_mask,
        )

        if self._gravity_unique is None:
            raise RuntimeError("leftover_gravity tables were not built for this frame")
        target = self.backend.target_masks[int(frame_position)].detach().cpu().numpy()
        leftover = leftover_mask(
            target,
            predicted_mask,
            self._occupancy_ignore_hw,
            predicted_threshold=float(self.config.predicted_alpha_threshold),
        )
        extra = extra_predicted_mask(
            target,
            predicted_mask,
            self._occupancy_ignore_hw,
            predicted_threshold=float(self.config.predicted_alpha_threshold),
        )
        shape = leftover.shape
        distance = {
            name: bone_distance_map(
                self._gravity_unique[name],
                self._gravity_joint_xy[name],
                shape=shape,
            )
            for name in remaining_names
        }
        depth = None
        if float(self.config.leftover_gravity_depth_gate) > 0.0:
            depth = self.backend.target_depth[int(frame_position)].detach().cpu().numpy()
        blocked = None
        if self._lane_previous_unique is not None and self._held_bone_names:
            blocked = {
                name: self._lane_previous_unique[name]
                for name in self._held_bone_names
                if name in self._lane_previous_unique
            }
        return leftover_gravity_pull(
            leftover,
            remaining=remaining_names,
            unique_distance=distance,
            unique_masks=self._gravity_unique,
            previous_unique=self._lane_previous_unique,
            node_depth=self._lane_node_depth,
            extra=extra,
            extra_weight=float(self.config.leftover_gravity_extra_weight),
            max_assign_px=float(self.config.leftover_gravity_max_assign_px),
            sigma_px=float(self.config.leftover_gravity_sigma_px),
            depth=depth,
            unique_median_depth=self._gravity_unique_depth,
            depth_gate=float(self.config.leftover_gravity_depth_gate),
            blocked_unique=blocked,
        )

    def _scan_leftover_gravity_pass(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
        frame: int,
        progress: bool,
        history: list[dict[str, Any]],
    ):
        """Visit remaining bones by leftover pull, then recompute uncovered pixels."""
        from leftover_gravity import leftover_mask, pick_next_gravity_bone

        remaining = [
            str(self.node_names[int(index)]) for index in self._frame_walk_indices
        ]
        fallback = self._gravity_fallback_names or tuple(remaining)
        visited: list[int] = []
        picks: list[dict[str, Any]] = []
        quality = self._current_pose_quality(
            state_raw,
            root_translation_raw,
            root_rotation_raw,
            frame_position=int(frame_position),
        )
        predicted = quality["predictedMask"]
        while remaining:
            reports = self._leftover_gravity_reports(
                predicted,
                remaining_names=remaining,
                frame_position=int(frame_position),
            )
            name = pick_next_gravity_bone(
                reports,
                remaining,
                fallback=fallback,
                min_pull=float(self.config.leftover_gravity_min_pull),
            )
            node_index = int(self.backend.node_index[name])
            remaining = [other for other in remaining if other != name]
            visited.append(node_index)
            leftover = leftover_mask(
                self.backend.target_masks[int(frame_position)].detach().cpu().numpy(),
                predicted,
                self._occupancy_ignore_hw,
                predicted_threshold=float(self.config.predicted_alpha_threshold),
            )
            pick = {
                "bone": name,
                "pull": float(reports[name]["pull"]),
                "assigned": int(reports[name]["assigned"]),
                "extra": float(reports[name]["extra"]),
                "leftoverPixels": int(np.count_nonzero(leftover)),
                "remaining": int(len(remaining)),
            }
            picks.append(pick)
            if progress:
                print(
                    f"depth f{int(frame):02d} leftover-gravity "
                    f"pick={name} pull={pick['pull']:.2f} "
                    f"assigned={pick['assigned']} leftover={pick['leftoverPixels']} "
                    f"remaining={pick['remaining']}",
                    flush=True,
                )
            for axis in self.config.search_axes:
                state_raw, root_translation_raw, root_rotation_raw = self._scan_axis(
                    state_raw,
                    root_translation_raw,
                    root_rotation_raw,
                    frame_position=frame_position,
                    frame=int(frame),
                    node_index=node_index,
                    axis=axis,
                    progress=progress,
                    history=history,
                )
            self._refresh_live_preview(
                frame=int(frame),
                frame_position=frame_position,
                label=f"f{int(frame):02d} gravity {name}",
                state_raw=state_raw,
                root_translation_raw=root_translation_raw,
                root_rotation_raw=root_rotation_raw,
            )
            quality = self._current_pose_quality(
                state_raw,
                root_translation_raw,
                root_rotation_raw,
                frame_position=int(frame_position),
            )
            predicted = quality["predictedMask"]
        self._frame_walk_indices = tuple(visited)
        history.append(
            {
                "frame": int(frame),
                "framePosition": int(frame_position),
                "stage": "leftover_gravity",
                "picks": picks,
            }
        )
        return state_raw, root_translation_raw, root_rotation_raw

    def _commit_occupancy_lane_unique(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
    ) -> None:
        if (
            not bool(self.config.blob_identity_persist)
            and not bool(self.config.unique_vanish_hold)
            and self.config.bone_order_mode != "leftover_gravity"
        ):
            self._lane_previous_unique = None
            return
        _maps, visible = self._lane_maps(
            state_raw,
            root_translation_raw,
            root_rotation_raw,
            frame_position=int(frame_position),
        )
        self._lane_previous_unique = visible

    def _resolve_branch_blocks(self) -> tuple[tuple[int, ...], ...]:
        """Return connected dependency blocks in root-to-leaf traversal order.

        A block follows a chain while a node has exactly one active child.  A
        branch point ends that block and its children are then traversed in
        the configured bone order.  This gives the requested dependency /
        branch ordering without assuming that any node is a wing, arm, leg,
        or other creature-specific part.
        """
        active = set(int(index) for index in self.bone_indices)
        rank = {int(index): position for position, index in enumerate(self.bone_indices)}
        children: dict[int, list[int]] = {index: [] for index in active}
        for index in active:
            parent = self.backend.parents[index]
            if parent is not None and int(parent) in active:
                children[int(parent)].append(index)
        for values in children.values():
            values.sort(key=lambda index: (rank.get(index, len(rank)), index))
        roots = sorted(
            (index for index in active if self.backend.parents[index] is None or int(self.backend.parents[index]) not in active),
            key=lambda index: (self.backend.node_depths[index], rank.get(index, len(rank)), index),
        )
        blocks: list[tuple[int, ...]] = []
        visited: set[int] = set()
        block_size = int(self.config.multi_bone_block_size)

        def visit(start: int) -> None:
            if start in visited:
                return
            chain: list[int] = []
            current = int(start)
            while current not in visited:
                visited.add(current)
                chain.append(current)
                next_children = children[current]
                if len(next_children) != 1:
                    break
                current = next_children[0]
            for begin in range(0, len(chain), block_size):
                blocks.append(tuple(chain[begin : begin + block_size]))
            for child in children[current]:
                visit(child)

        for root in roots:
            visit(root)
        for index in self.bone_indices:
            visit(int(index))
        return tuple(blocks)

    def _multi_bone_offset_grid(self, group_size: int, radius_deg: float, step_deg: float) -> np.ndarray:
        """Build a bounded Cartesian offset grid and always retain zero."""
        values = _inclusive_grid(-float(radius_deg), float(radius_deg), float(step_deg))
        max_candidates = int(self.config.multi_bone_max_candidates)
        value_count = 2
        while (value_count + 1) ** int(group_size) <= max_candidates:
            value_count += 1
        if len(values) > value_count:
            indexes = np.linspace(0, len(values) - 1, value_count).round().astype(int)
            values = values[np.unique(indexes)]
        if not np.any(np.isclose(values, 0.0)):
            values = np.sort(np.concatenate((values, np.asarray((0.0,), dtype=np.float64))))
            if len(values) ** int(group_size) > max_candidates:
                values = values[: max(2, value_count)]
                values[np.argmin(np.abs(values))] = 0.0
        combinations = np.asarray(
            list(itertools.product(values.tolist(), repeat=int(group_size))),
            dtype=np.float32,
        )
        if len(combinations) > max_candidates:
            raise RuntimeError(
                "multi-bone candidate grid exceeded its bound: "
                f"group={group_size} values={len(values)} candidates={len(combinations)} "
                f"max={max_candidates}"
            )
        return combinations

    def _raw_for_angle(self, angle_deg: np.ndarray, node_index: int):
        import torch

        limit = math.radians(float(self.config.joint_limit_deg) * float(self._bone_limit_scale_cpu[node_index]))
        if limit <= 0.0:
            raise ValueError(f"bone has no usable rotation range: {self.node_names[node_index]}")
        normalized = np.clip(np.radians(angle_deg) / limit, -0.999, 0.999)
        return torch.atanh(
            torch.as_tensor(normalized, dtype=torch.float32, device=self.backend.device)
        )

    @staticmethod
    def _root_axis_index(axis: str, *, rotation: bool) -> int:
        names = (
            ("camera_forward", "camera_right", "camera_up")
            if rotation
            else ("forward", "lateral", "vertical")
        )
        try:
            return names.index(str(axis))
        except ValueError as exc:
            kind = "rotation" if rotation else "translation"
            raise ValueError(f"unknown root {kind} axis: {axis}") from exc

    def _raw_for_root_translation(self, values: np.ndarray):
        import torch

        limit = float(self.config.root_translation_limit_body_lengths)
        normalized = np.clip(np.asarray(values, dtype=np.float64) / limit, -0.999, 0.999)
        return torch.atanh(
            torch.as_tensor(normalized, dtype=torch.float32, device=self.backend.device)
        )

    def _raw_for_root_rotation(self, values_deg: np.ndarray, *, axis_index: int):
        import torch

        radians = np.radians(np.asarray(values_deg, dtype=np.float64))
        raw = self.backend._root_rotation_raw_inverse(radians, axis_index=int(axis_index))
        return torch.as_tensor(raw, dtype=torch.float32, device=self.backend.device)

    def _collision_error_batch(self, bone_vectors, root_translation_raw, root_rotation_raw):
        """Score self-intersection; rigid root motion does not change relative distances."""
        import torch
        from gpu_mesh_collision import collision_error_from_table

        del root_translation_raw, root_rotation_raw
        with torch.no_grad():
            return collision_error_from_table(
                self.backend,
                self.backend._collision_table,
                bone_vectors,
            )

    def _strain_error_batch(self, bone_vectors):
        """Score mixed-edge stretch; rigid root motion does not change rest lengths."""
        import torch
        from gpu_mesh_strain import strain_error_from_table

        if not bool(self.config.strain_enabled):
            return torch.zeros(
                (int(bone_vectors.shape[0]),),
                dtype=torch.float32,
                device=self.backend.device,
            )
        if self._strain_table is None:
            raise RuntimeError("strain is enabled but the mixed-edge table was not built")
        with torch.no_grad():
            return strain_error_from_table(
                self.backend,
                self._strain_table,
                bone_vectors,
                tolerance=float(self.config.strain_tolerance),
            )

    def _strain_error_raw_batch(self, raw_bones):
        import torch

        count = int(raw_bones.shape[0])
        if count < 1:
            raise ValueError("strain raster requires at least one pose")
        if not bool(self.config.strain_enabled):
            return torch.zeros((count,), dtype=torch.float32, device=self.backend.device)
        chunks = score_raster_chunks(count, int(self.config.score_raster_batch))
        parts = []
        with torch.no_grad():
            for start, end in chunks:
                bounded = self.backend._bounded_bone_vectors(raw_bones[start:end])
                parts.append(self._strain_error_batch(bounded))
        return torch.cat(parts, dim=0)

    @staticmethod
    def _score_info(scored: dict[str, Any], best_index: int) -> dict[str, Any]:
        return {
            "bestIndex": int(best_index),
            "bestScore": float(scored["score"][best_index].item()),
            "bestDepthError": float(scored["depthError"][best_index].item()),
            "bestDepthRobustError": float(scored["depthRobustError"][best_index].item()),
            "bestDepthQuality": float(scored["depthQuality"][best_index].item()),
            "bestSilhouetteIoU": float(scored["silhouetteIoU"][best_index].item()),
            "bestChromaQuality": float(scored["chromaQuality"][best_index].item()),
            "bestTemporalPenalty": float(scored["temporalPenalty"][best_index].item()),
            "bestCollisionError": float(scored["collisionError"][best_index].item()),
            "bestStrainError": float(scored["strainError"][best_index].item()),
        }

    def _current_pose_quality(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
    ) -> dict[str, Any]:
        """Score the accepted whole pose, not a packed 1D candidate row."""
        scored = self._score_batch(
            state_raw,
            frame_position,
            root_translation_raw,
            root_rotation_raw,
        )
        quality = {
            "score": float(scored["score"][0].item()),
            "iou": float(scored["silhouetteIoU"][0].item()),
            "chromaQuality": float(scored["chromaQuality"][0].item()),
            "depthError": float(scored["depthError"][0].item()),
            "temporalPenalty": float(scored["temporalPenalty"][0].item()),
            "collisionError": float(scored["collisionError"][0].item()),
            "strainError": float(scored["strainError"][0].item()),
            "predictedMask": scored["predictedAlpha"][0].detach().cpu().numpy(),
        }
        if not math.isfinite(quality["score"]):
            raise ValueError("pose quality score must be finite")
        return quality

    def _start_pass_quality(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
        frame: int,
        progress: bool,
    ) -> dict[str, Any]:
        quality = self._current_pose_quality(
            state_raw,
            root_translation_raw,
            root_rotation_raw,
            frame_position=frame_position,
        )
        if progress:
            print(
                f"depth f{int(frame):02d} bone baseline "
                f"score={quality['score']:.4f} "
                f"iou={quality['iou']:.4f} "
                f"chroma={quality['chromaQuality']:.4f} "
                f"coll={quality['collisionError']:.4f} "
                f"strain={quality['strainError']:.4f} "
                f"improveEps={float(self.config.pass_improve_epsilon):.4f} "
                f"unstickFloor={float(self.config.unstick_score_floor):.2f}",
                flush=True,
            )
        return {
            "previousScore": quality["score"],
            "unstickAttempts": 0,
            "allowUntil": None,
            "state": state_raw.clone(),
            "translation": root_translation_raw.clone(),
            "rotation": root_rotation_raw.clone(),
        }

    def _projected_joint_xy(self, state_raw, root_translation_raw, root_rotation_raw):
        """Project every node origin into PNG pixel coordinates."""
        import torch

        bounded = self.backend._bounded_bone_vectors(state_raw)
        worlds = self.backend._forward_kinematics(
            bounded,
            bone_mask=self.backend.active_node_mask,
        )
        points = worlds[:, :, :3, 3]
        points = self.backend._root_transform(points, root_translation_raw, root_rotation_raw)
        x = (
            torch.matmul(points, self.backend.camera_right) * self.backend.px_per_world[0]
            + self.backend.camera_offset[0]
        )
        y = (
            torch.matmul(points, self.backend.camera_down) * self.backend.px_per_world[1]
            + self.backend.camera_offset[1]
        )
        return torch.stack((x, y), dim=-1)

    def _score_pose_rows(
        self,
        candidates,
        candidate_translation,
        candidate_rotation,
        *,
        frame_position: int,
    ):
        """Score an arbitrary pose batch in GPU chunks. Never drop rows."""
        import torch

        count = int(candidates.shape[0])
        if count < 1:
            raise ValueError("unstick raster requires at least one pose")
        chunk = int(self.config.packed_axis_batch) if int(self.config.packed_axis_batch) > 0 else 128
        best_score = None
        best_row = None
        offset = 0
        while offset < count:
            stop = min(offset + chunk, count)
            scored = self._score_batch(
                candidates[offset:stop],
                frame_position,
                candidate_translation[offset:stop],
                candidate_rotation[offset:stop],
            )
            local = int(torch.argmax(scored["score"]).item())
            value = float(scored["score"][local].item())
            if best_score is None or value > best_score:
                best_score = value
                best_row = candidates[offset + local : offset + local + 1].clone()
            offset = stop
        if best_row is None or best_score is None:
            raise ValueError("unstick raster produced no scores")
        return best_row, float(best_score)

    def _unstick_missing_silhouette(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
        frame: int,
        predicted_mask: np.ndarray,
        progress: bool,
        history: list[dict[str, Any]],
    ):
        """Wide simultaneous search of joints nearest uncovered target silhouette."""
        import torch

        target_mask = self.backend.target_masks[frame_position].detach().cpu().numpy()
        missing = missing_target_silhouette(
            target_mask,
            predicted_mask,
            threshold=float(self.config.predicted_alpha_threshold),
        )
        _labels, section_count = label_binary_components(missing)
        if int(np.count_nonzero(missing)) <= 0:
            if progress:
                print(
                    f"depth f{int(frame):02d} unstick skipped; no missing target silhouette",
                    flush=True,
                )
            return None, {
                "reason": "no_missing_silhouette",
                "sectionCount": 0,
                "score": None,
            }
        joint_xy = self._projected_joint_xy(
            state_raw, root_translation_raw, root_rotation_raw
        )[0].detach().cpu().numpy()
        searchable = np.asarray(self.bone_indices, dtype=np.int64)
        if searchable.size == 0:
            raise ValueError("unstick requires searchable bones")
        local_chosen, local_distances = nearest_joint_indices(
            joint_xy[searchable],
            missing,
            int(min(int(self.config.unstick_joint_count), int(searchable.size))),
        )
        node_indices = tuple(int(searchable[index]) for index in local_chosen)
        hole_rows, hole_cols = np.nonzero(missing)
        hole_centroid = np.asarray(
            (float(np.mean(hole_cols)), float(np.mean(hole_rows))),
            dtype=np.float64,
        )
        probe_deg = min(10.0, float(self.config.unstick_limit_deg))
        probe_count = len(node_indices) * len(self.config.search_axes)
        probes = state_raw.expand(probe_count, -1, -1).clone()
        probe_translation = root_translation_raw.expand(probe_count, -1).clone()
        probe_rotation = root_rotation_raw.expand(probe_count, -1).clone()
        probe_meta: list[tuple[int, str]] = []
        slot = 0
        bounded = torch.rad2deg(self.backend._bounded_bone_vectors(state_raw)[0]).detach().cpu().numpy()
        joint_limit = float(self.config.joint_limit_deg)
        for node_index in node_indices:
            current = {
                axis: float(bounded[node_index, _axis_index(axis)])
                for axis in self.config.search_axes
            }
            for axis in self.config.search_axes:
                probes[slot, node_index, _axis_index(axis)] = self._raw_for_angle(
                    np.asarray((current[axis] + probe_deg,), dtype=np.float64),
                    node_index,
                )[0]
                probe_meta.append((node_index, axis))
                slot += 1
        rest_xy = joint_xy
        probe_xy = self._projected_joint_xy(
            probes, probe_translation, probe_rotation
        ).detach().cpu().numpy()
        chosen_axes: list[str] = []
        for node_index in node_indices:
            rest = rest_xy[node_index]
            toward = hole_centroid - rest
            best_axis = self.config.search_axes[0]
            best_dot = -math.inf
            for axis in self.config.search_axes:
                row = probe_meta.index((node_index, axis))
                moved = probe_xy[row, node_index] - rest
                dotted = float(np.dot(moved, toward))
                if dotted > best_dot:
                    best_dot = dotted
                    best_axis = axis
            chosen_axes.append(best_axis)
        sample_sets = [
            unstick_angle_samples(
                float(bounded[node_index, _axis_index(axis)]),
                unstick_limit_deg=float(self.config.unstick_limit_deg),
                joint_limit_deg=joint_limit,
                sample_count=int(self.config.unstick_samples_per_bone),
            )
            for node_index, axis in zip(node_indices, chosen_axes)
        ]
        combo_count = int(np.prod([len(values) for values in sample_sets], dtype=np.int64))
        if combo_count > int(self.config.unstick_max_candidates):
            raise ValueError(
                "unstick combination count exceeds unstick_max_candidates: "
                f"combos={combo_count} max={int(self.config.unstick_max_candidates)}"
            )
        candidates = state_raw.expand(combo_count, -1, -1).clone()
        candidate_translation = root_translation_raw.expand(combo_count, -1).clone()
        candidate_rotation = root_rotation_raw.expand(combo_count, -1).clone()
        for combo_index, combo in enumerate(itertools.product(*sample_sets)):
            for bone_slot, (node_index, axis) in enumerate(zip(node_indices, chosen_axes)):
                candidates[combo_index, node_index, _axis_index(axis)] = self._raw_for_angle(
                    np.asarray((combo[bone_slot],), dtype=np.float64),
                    node_index,
                )[0]
        best_row, best_score = self._score_pose_rows(
            candidates,
            candidate_translation,
            candidate_rotation,
            frame_position=frame_position,
        )
        names = [self.node_names[index] for index in node_indices]
        if progress:
            print(
                f"depth f{int(frame):02d} unstick sections={section_count} "
                f"holes={int(np.count_nonzero(missing))} "
                f"joints={','.join(names)} "
                f"axes={','.join(chosen_axes)} "
                f"combos={combo_count} "
                f"score={best_score:.4f} "
                f"near={','.join(f'{value:.1f}px' for value in local_distances.tolist())}",
                flush=True,
            )
        history.append(
            {
                "frame": int(frame),
                "framePosition": int(frame_position),
                "unstick": True,
                "sectionCount": int(section_count),
                "missingPixels": int(np.count_nonzero(missing)),
                "bones": names,
                "axes": list(chosen_axes),
                "candidateCount": combo_count,
                "score": float(best_score),
                "jointDistancesPx": [float(value) for value in local_distances.tolist()],
            }
        )
        return best_row, {
            "reason": "scored",
            "score": float(best_score),
            "sectionCount": int(section_count),
            "bones": names,
        }

    def _evaluate_job_and_maybe_unstick(
        self,
        tracker: dict[str, Any],
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
        frame: int,
        pass_index: int,
        pass_count: int,
        progress: bool,
        history: list[dict[str, Any]],
    ):
        """Compare this job to the previous one; unstick or move on if it stalled."""
        quality = self._current_pose_quality(
            state_raw,
            root_translation_raw,
            root_rotation_raw,
            frame_position=frame_position,
        )
        previous = float(tracker["previousScore"])
        improved = score_meaningfully_higher(
            previous,
            quality["score"],
            float(self.config.pass_improve_epsilon),
        )
        if progress:
            print(
                f"depth f{int(frame):02d} pass {int(pass_index)}/{int(pass_count)} "
                f"{'improved' if improved else 'stalled'} "
                f"score={quality['score']:.4f} "
                f"prev={previous:.4f} "
                f"iou={quality['iou']:.4f} "
                f"coll={quality['collisionError']:.4f}",
                flush=True,
            )
        if improved:
            tracker["previousScore"] = quality["score"]
            tracker["state"] = state_raw.clone()
            tracker["translation"] = root_translation_raw.clone()
            tracker["rotation"] = root_rotation_raw.clone()
            return state_raw, root_translation_raw, root_rotation_raw, None, True
        if quality["score"] >= float(self.config.unstick_score_floor):
            if progress:
                print(
                    f"depth f{int(frame):02d} stalled at score {quality['score']:.4f} "
                    f">= floor {float(self.config.unstick_score_floor):.2f}; "
                    "moving on to the next frame",
                    flush=True,
                )
            return state_raw, root_translation_raw, root_rotation_raw, "score_floor", False
        if int(self.config.unstick_joint_count) <= 0:
            if progress:
                print(
                    f"depth f{int(frame):02d} stalled below floor with unstick disabled; "
                    "moving on to the next frame",
                    flush=True,
                )
            return (
                tracker["state"].clone(),
                tracker["translation"].clone(),
                tracker["rotation"].clone(),
                "unstick_disabled",
                False,
            )
        if int(tracker["unstickAttempts"]) >= int(self.config.unstick_max_attempts):
            if progress:
                print(
                    f"depth f{int(frame):02d} unstick attempts exhausted "
                    f"({int(self.config.unstick_max_attempts)}); moving on to the next frame",
                    flush=True,
                )
            return (
                tracker["state"].clone(),
                tracker["translation"].clone(),
                tracker["rotation"].clone(),
                "unstick_budget",
                False,
            )
        tracker["unstickAttempts"] = int(tracker["unstickAttempts"]) + 1
        unstick_pose, unstick_info = self._unstick_missing_silhouette(
            state_raw,
            root_translation_raw,
            root_rotation_raw,
            frame_position=frame_position,
            frame=int(frame),
            predicted_mask=quality["predictedMask"],
            progress=progress,
            history=history,
        )
        if unstick_pose is None or unstick_info.get("score") is None:
            if progress:
                print(
                    f"depth f{int(frame):02d} unstick could not target a hole; "
                    "moving on to the next frame",
                    flush=True,
                )
            return (
                tracker["state"].clone(),
                tracker["translation"].clone(),
                tracker["rotation"].clone(),
                "unstick_no_missing_silhouette",
                False,
            )
        escaped = score_meaningfully_higher(
            previous,
            float(unstick_info["score"]),
            float(self.config.pass_improve_epsilon),
        )
        if escaped:
            if progress:
                print(
                    f"depth f{int(frame):02d} unstick escaped minima "
                    f"score={float(unstick_info['score']):.4f} "
                    f"prev={previous:.4f}; another job pass",
                    flush=True,
                )
            tracker["previousScore"] = float(unstick_info["score"])
            tracker["state"] = unstick_pose.clone()
            tracker["translation"] = root_translation_raw.clone()
            tracker["rotation"] = root_rotation_raw.clone()
            tracker["grantExtra"] = True
            return unstick_pose, root_translation_raw, root_rotation_raw, None, True
        if progress:
            print(
                f"depth f{int(frame):02d} unstick failed to beat previous job "
                f"score={float(unstick_info['score']):.4f} "
                f"prev={previous:.4f}; moving on to the next frame",
                flush=True,
            )
        return (
            tracker["state"].clone(),
            tracker["translation"].clone(),
            tracker["rotation"].clone(),
            "unstick_failed",
            False,
        )

    def _root_candidate_wave(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
        axis: str,
        values: np.ndarray,
        rotation: bool,
    ) -> tuple[Any, Any, Any, dict[str, Any]]:
        """Evaluate one root channel while keeping all bones unchanged."""
        import torch

        count = int(len(values))
        candidates = state_raw.expand(count, -1, -1).clone()
        candidate_translation = root_translation_raw.expand(count, -1).clone()
        candidate_rotation = root_rotation_raw.expand(count, -1).clone()
        axis_index = self._root_axis_index(axis, rotation=rotation)
        if rotation:
            candidate_rotation[:, axis_index] = self._raw_for_root_rotation(
                values,
                axis_index=axis_index,
            )
        else:
            candidate_translation[:, axis_index] = self._raw_for_root_translation(values)
        scored = self._score_batch(
            candidates,
            frame_position,
            candidate_translation,
            candidate_rotation,
        )
        best_index = int(torch.argmax(scored["score"]).item())
        info = self._score_info(scored, best_index)
        info.update(
            {
                "axis": str(axis),
                "rotation": bool(rotation),
                "bestValue": float(values[best_index]),
                "candidateValues": [float(value) for value in values.tolist()],
            }
        )
        return (
            candidates[best_index : best_index + 1].clone(),
            candidate_translation[best_index : best_index + 1].clone(),
            candidate_rotation[best_index : best_index + 1].clone(),
            info,
        )

    def _scan_root_axis(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
        frame: int,
        axis: str,
        rotation: bool,
        progress: bool,
        history: list[dict[str, Any]],
    ):
        import torch

        if rotation:
            axis_limit = root_rotation_axis_envelope_deg(
                axis,
                envelope_deg=float(self.config.root_rotation_limit_deg),
                camera_up_limit_deg=float(self.config.root_rotation_camera_up_limit_deg),
            )
            window = root_rotation_search_window_deg(
                frame_position=int(frame_position),
                limit_deg=axis_limit,
                first_frame_limit_deg=float(self.config.root_rotation_first_frame_limit_deg),
                per_frame_limit_deg=float(self.config.root_rotation_per_frame_limit_deg),
            )
            step = float(self.config.root_rotation_coarse_step_deg)
            refine_step = float(self.config.root_rotation_refine_step_deg)
            refine_radius = (
                0.0
                if window <= 0.0
                else min(float(self.config.root_rotation_refine_radius_deg), float(window))
            )
            axis_index = self._root_axis_index(axis, rotation=True)
            current = float(
                torch.rad2deg(self.backend._bounded_root_rotation(root_rotation_raw)[0, axis_index]).item()
            )
            lo, hi = root_rotation_search_bounds(
                current,
                frame_position=int(frame_position),
                limit_deg=axis_limit,
                first_frame_limit_deg=float(self.config.root_rotation_first_frame_limit_deg),
                per_frame_limit_deg=float(self.config.root_rotation_per_frame_limit_deg),
            )
            coarse = _inclusive_grid(lo, hi, step)
            clip_min, clip_max = lo, hi
        else:
            limit = float(self.config.root_translation_limit_body_lengths)
            step = float(self.config.root_translation_coarse_step_body_lengths)
            refine_radius = float(self.config.root_translation_refine_radius_body_lengths)
            refine_step = float(self.config.root_translation_refine_step_body_lengths)
            axis_index = self._root_axis_index(axis, rotation=False)
            current = float(
                torch.tanh(root_translation_raw)[0, axis_index].item() * limit
            )
            coarse = _inclusive_grid(-limit, limit, step)
            clip_min, clip_max = -limit, limit
        coarse = np.unique(np.concatenate((coarse, np.asarray((current,), dtype=np.float64))))
        state_raw, root_translation_raw, root_rotation_raw, coarse_info = self._root_candidate_wave(
            state_raw,
            root_translation_raw,
            root_rotation_raw,
            frame_position=frame_position,
            axis=axis,
            values=coarse,
            rotation=rotation,
        )
        coarse_best = float(coarse_info["bestValue"])
        refine = _inclusive_grid(
            max(clip_min, coarse_best - refine_radius),
            min(clip_max, coarse_best + refine_radius),
            refine_step,
        )
        refine = np.unique(np.concatenate((refine, np.asarray((coarse_best,), dtype=np.float64))))
        state_raw, root_translation_raw, root_rotation_raw, refine_info = self._root_candidate_wave(
            state_raw,
            root_translation_raw,
            root_rotation_raw,
            frame_position=frame_position,
            axis=axis,
            values=refine,
            rotation=rotation,
        )
        history.append(
            {
                "frame": int(frame),
                "framePosition": int(frame_position),
                "mode": "motion_root",
                "axis": str(axis),
                "rotation": bool(rotation),
                "coarse": coarse_info,
                "refine": refine_info,
                "evaluations": int(len(coarse) + len(refine)),
            }
        )
        if progress:
            kind = "rootRot" if rotation else "rootMove"
            print(
                f"depth f{frame:02d} {kind} {axis} "
                f"score={refine_info['bestScore']:.4f} "
                f"iou={refine_info['bestSilhouetteIoU']:.4f} "
                f"chroma={refine_info['bestChromaQuality']:.4f} "
                f"value={refine_info['bestValue']:.4f} "
                f"evals={self.evaluation_count}",
                flush=True,
            )
        return state_raw, root_translation_raw, root_rotation_raw

    def _semantic_interleave_scores(
        self,
        bounded,
        root_translation,
        root_rotation,
        frame_position: int,
        geometry_score,
        *,
        force: bool = False,
        predicted_rgb=None,
    ):
        """Rescore geometric leaders at a bounded cadence, in the same wave.

        This is intentionally not a finalist-only pass. The first wave and
        every configured cadence wave are eligible, and the caller can force a
        final check for a scan. Unselected candidates receive a neutral 0.5
        semantic score, so geometry still ranks them without pretending they
        were embedded.
        """
        import torch

        count = int(bounded.shape[0])
        global_score = torch.full(
            (count,), 0.5, dtype=torch.float32, device=self.backend.device,
        )
        dense_score = torch.full(
            (count,), 0.5, dtype=torch.float32, device=self.backend.device,
        )
        semantic_evaluated = torch.zeros((count,), dtype=torch.bool, device=self.backend.device)
        if self.semantic_embedder is None and self.dense_semantic_scorer is None:
            return global_score, dense_score, semantic_evaluated
        if count == 0:
            return global_score, dense_score, semantic_evaluated
        dense_required = (
            self.dense_semantic_scorer is not None
            and float(self.config.dense_semantic_weight) > 0.0
        )
        self.semantic_batch_count += 1
        cadence = max(int(self.config.semantic_interleave_every), 1)
        if not force and not dense_required and (self.semantic_batch_count - 1) % cadence != 0:
            return global_score, dense_score, semantic_evaluated
        if dense_required:
            top_k = count
        else:
            top_k = min(int(self.config.semantic_candidate_top_k), count)
        budget = int(self.config.semantic_eval_budget)
        if budget > 0:
            remaining = max(budget - int(self.semantic_evaluation_count), 0)
            if dense_required and remaining < top_k:
                raise RuntimeError(
                    "dense semantic eval budget would drop candidates to "
                    "geometry-only scoring. Increase semantic_eval_budget or set "
                    "it to 0 for unlimited, or disable dense_semantic_enabled."
                )
            top_k = min(top_k, remaining)
        if top_k <= 0:
            if dense_required:
                raise RuntimeError(
                    "dense semantic scoring is enabled but no candidate budget remains"
                )
            return global_score, dense_score, semantic_evaluated
        candidate_indices = torch.topk(geometry_score, k=top_k, largest=True).indices
        if predicted_rgb is not None:
            rgb = predicted_rgb.index_select(0, candidate_indices)
        else:
            if dense_required:
                raise RuntimeError(
                    "dense semantic scoring needs predicted RGB from the geometry raster"
                )
            with torch.no_grad():
                rgb, _alpha, _depth = self.backend.exact_triangle_rgb(
                    bounded.index_select(0, candidate_indices),
                    root_translation.index_select(0, candidate_indices),
                    root_rotation.index_select(0, candidate_indices),
                    bone_mask=self.backend.active_node_mask,
                )
        target_index = int(frame_position)
        if self.semantic_embedder is not None:
            images = rgb_hwc_batch_to_pil_images(rgb)
            layer_batches: dict[str, list[np.ndarray]] = {
                layer: [] for layer in self.semantic_embedder.embedding_layers
            }
            for start in range(0, len(images), int(self.config.semantic_batch_size)):
                batch_images = images[start : start + int(self.config.semantic_batch_size)]
                vectors = self.semantic_embedder.embed_layers(batch_images)
                for layer in self.semantic_embedder.embedding_layers:
                    target = self.semantic_target_vectors[layer][target_index]
                    values = np.asarray(vectors[layer], dtype=np.float32)
                    layer_batches[layer].append(np.sum(values * target[None, :], axis=1))
            per_layer = [
                np.concatenate(layer_batches[layer], axis=0)
                for layer in self.semantic_embedder.embedding_layers
            ]
            cosine = np.mean(np.stack(per_layer, axis=0), axis=0)
            normalized = np.clip((cosine + 1.0) * 0.5, 0.0, 1.0).astype(np.float32)
            global_score[candidate_indices] = torch.as_tensor(normalized, device=self.backend.device)
        if self.dense_semantic_scorer is not None:
            if not self.dense_semantic_target_grids:
                raise RuntimeError("dense semantic scoring is enabled but target grids were not cached")
            frame_positions = torch.full(
                (int(rgb.shape[0]),),
                int(frame_position),
                dtype=torch.long,
                device=rgb.device,
            )
            qualities = score_dense_semantic_rgb_batch(
                self.dense_semantic_scorer,
                target_grids_by_frame=self.dense_semantic_target_grids,
                predicted_rgb=rgb,
                frame_positions=frame_positions,
                batch_size=int(self.config.semantic_batch_size),
                window_radius=int(self.config.dense_semantic_local_radius),
                position_weight=float(self.config.dense_semantic_position_weight),
                subject_crop=bool(self.config.semantic_subject_crop),
                subject_padding_frac=float(self.config.semantic_subject_padding_frac),
            )
            dense_score[candidate_indices] = qualities
        semantic_evaluated[candidate_indices] = True
        self.semantic_evaluation_count += int(top_k)
        return global_score, dense_score, semantic_evaluated

    def _temporal_penalty_batch(self, bounded, root_translation, root_rotation):
        """Compare a candidate batch against the previous frame's accepted pose."""
        import torch

        count = int(bounded.shape[0])
        zeros = torch.zeros((count,), dtype=torch.float32, device=self.backend.device)
        if self._temporal_reference is None or float(self.config.temporal_weight) <= 0.0:
            return zeros
        prev_bones, prev_translation, prev_rotation = self._temporal_reference
        prev_bounded = self.backend._bounded_bone_vectors(prev_bones)
        bone = temporal_bone_penalty(
            bounded,
            prev_bounded,
            scale_deg=float(self.config.temporal_scale_deg),
        )
        limit = float(self.config.root_translation_limit_body_lengths)
        root_scale = max(float(self.config.temporal_root_scale_body_lengths), 1e-6)
        translation = torch.tanh(
            torch.linalg.vector_norm(
                torch.tanh(root_translation) * limit
                - torch.tanh(prev_translation) * limit,
                dim=1,
            )
            / root_scale
        )
        angle_scale = max(math.radians(float(self.config.temporal_scale_deg)), 1e-6)
        rotation = torch.tanh(
            torch.linalg.vector_norm(
                self.backend._bounded_root_rotation(root_rotation)
                - self.backend._bounded_root_rotation(prev_rotation),
                dim=1,
            )
            / angle_scale
        )
        return (bone + translation + rotation) / 3.0

    def _live_preview_rasters(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
        """Raster the current accepted pose for display only.

        This does not increment evaluation_count or run DINOv3.  Live
        preview is a watch of the pose already chosen, not another search.
        """
        bounded = self.backend._bounded_bone_vectors(state_raw)
        if float(self.config.chroma_weight) > 0.0:
            predicted_rgb, predicted_alpha, predicted_depth = self.backend.exact_triangle_rgb(
                bounded,
                root_translation_raw,
                root_rotation_raw,
                bone_mask=self.backend.active_node_mask,
            )
            return (
                predicted_alpha[0].detach().cpu().numpy(),
                predicted_depth[0].detach().cpu().numpy(),
                predicted_rgb[0].detach().cpu().numpy(),
            )
        predicted_alpha, predicted_depth = self.backend._exact_triangle_raster(
            bounded,
            root_translation_raw,
            root_rotation_raw,
            bone_mask=self.backend.active_node_mask,
        )
        return (
            predicted_alpha[0].detach().cpu().numpy(),
            predicted_depth[0].detach().cpu().numpy(),
            None,
        )

    def _maybe_heartbeat(self, *, frame: int, label: str, progress: bool) -> None:
        """Print a still-alive line even when a bone does not rotate.

        Pass-limited walks skip the per-axis line when delta is ~0, so a
        geometry-only run can look frozen for tens of seconds while it is
        still scoring quiet bones.
        """
        if not progress:
            return
        now = time.perf_counter()
        if now - self._last_heartbeat < float(GpuDepthLivePreview.heartbeat_s):
            return
        self._last_heartbeat = now
        print(
            f"depth f{int(frame):02d} running {label} "
            f"evals={self.evaluation_count} "
            f"elapsed={now - self._solve_started:.1f}s",
            flush=True,
        )

    def _refresh_live_preview(
        self,
        *,
        frame: int,
        frame_position: int,
        label: str,
        state_raw=None,
        root_translation_raw=None,
        root_rotation_raw=None,
        predicted_mask: np.ndarray | None = None,
        predicted_depth: np.ndarray | None = None,
        predicted_rgb: np.ndarray | None = None,
        force: bool = False,
    ) -> None:
        if self._live_preview is None:
            return
        if not self._live_preview.will_emit(force=force):
            self._live_preview.skip_visit()
            return
        if predicted_mask is None or predicted_depth is None or (
            float(self.config.chroma_weight) > 0.0 and predicted_rgb is None
        ):
            if state_raw is None or root_translation_raw is None or root_rotation_raw is None:
                raise ValueError("live preview raster requires the current pose tensors")
            predicted_mask, predicted_depth, predicted_rgb = self._live_preview_rasters(
                state_raw,
                root_translation_raw,
                root_rotation_raw,
            )
        target_mask = self.backend.target_masks[frame_position].detach().cpu().numpy()
        target_depth = self.backend.target_depth[frame_position].detach().cpu().numpy()
        target_rgb = None
        if predicted_rgb is not None:
            if self.target_rgb is None:
                raise RuntimeError("chroma live preview is missing loaded target RGB")
            target_rgb = self.target_rgb[frame_position].detach().cpu().numpy()
        self._live_preview.show(
            frame=int(frame),
            label=label,
            target_depth=target_depth,
            predicted_depth=np.asarray(predicted_depth, dtype=np.float32),
            target_mask=target_mask,
            predicted_mask=np.asarray(predicted_mask, dtype=np.float32),
            target_rgb=None if target_rgb is None else np.asarray(target_rgb, dtype=np.float32),
            predicted_rgb=None if predicted_rgb is None else np.asarray(predicted_rgb, dtype=np.float32),
            force=force,
        )

    def _score_geometry_chunk(
        self,
        raw_bones,
        frame_position: int,
        root_translation_raw,
        root_rotation_raw,
    ) -> dict[str, Any]:
        """Raster and score one VRAM-sized slice. No semantic model here."""
        import torch

        count = int(raw_bones.shape[0])
        bounded = self.backend._bounded_bone_vectors(raw_bones)
        with torch.no_grad():
            chroma_weight = float(self.config.chroma_weight)
            need_rgb = chroma_weight > 0.0 or bool(self.config.dense_semantic_active())
            predicted_rgb = None
            if need_rgb:
                if chroma_weight > 0.0 and self.target_lab_ab is None:
                    raise RuntimeError("chroma_weight is set but Lab a,b targets were not loaded")
                predicted_rgb, predicted_alpha, predicted_depth = self.backend.exact_triangle_rgb(
                    bounded,
                    root_translation_raw,
                    root_rotation_raw,
                    bone_mask=self.backend.active_node_mask,
                )
            else:
                predicted_alpha, predicted_depth = self.backend._exact_triangle_raster(
                    bounded,
                    root_translation_raw,
                    root_rotation_raw,
                    bone_mask=self.backend.active_node_mask,
                )
            target_alpha = self.backend.target_masks[frame_position]
            target_depth = self.backend.target_depth[frame_position]
            target_foreground = target_alpha > 0.5
            predicted_foreground = predicted_alpha > float(self.config.predicted_alpha_threshold)
            geometry = silhouette_and_depth_quality(
                target_foreground=target_foreground.unsqueeze(0),
                predicted_foreground=predicted_foreground,
                target_depth=target_depth.unsqueeze(0),
                predicted_depth=predicted_depth,
                depth_tolerance=float(self.config.depth_tolerance),
                depth_robust_delta=float(self.config.depth_robust_delta),
                occupancy_ignore=self._occupancy_ignore_tensor(
                    predicted_foreground.device,
                    predicted_foreground.dtype,
                    batch=int(predicted_foreground.shape[0]),
                ),
            )
            silhouette_iou = geometry["silhouetteIoU"]
            depth_quality = geometry["depthQuality"]
            absolute_depth_error = geometry["depthError"]
            robust_depth_error = geometry["depthRobustError"]
            zeros = torch.zeros((count,), dtype=torch.float32, device=self.backend.device)
            if chroma_weight > 0.0:
                if predicted_rgb is None:
                    raise RuntimeError("chroma_weight is set but the geometry raster did not return RGB")
                predicted_ab = srgb_rgb_to_lab_ab(predicted_rgb)
                chroma = chroma_quality(
                    target_foreground=target_foreground.unsqueeze(0),
                    predicted_foreground=predicted_foreground,
                    target_ab=self.target_lab_ab[frame_position].unsqueeze(0),
                    predicted_ab=predicted_ab,
                    chroma_tolerance=float(self.config.chroma_tolerance),
                    chroma_robust_delta=float(self.config.chroma_robust_delta),
                    chroma_error_scale=float(self.config.chroma_error_scale),
                )
                chroma_quality_value = chroma["chromaQuality"]
                chroma_error = chroma["chromaError"]
                chroma_robust_error = chroma["chromaRobustError"]
            else:
                chroma_quality_value = zeros
                chroma_error = zeros
                chroma_robust_error = zeros
            geometry_score = compose_geometry_score(
                silhouette_iou=silhouette_iou,
                depth_quality=depth_quality,
                chroma_quality_value=chroma_quality_value,
                depth_weight=float(self.config.depth_weight),
                silhouette_weight=float(self.config.silhouette_weight),
                chroma_weight=chroma_weight,
            )
        temporal_penalty = self._temporal_penalty_batch(bounded, root_translation_raw, root_rotation_raw)
        collision_error = self._collision_error_batch(bounded, root_translation_raw, root_rotation_raw)
        strain_error = self._strain_error_batch(bounded)
        if int(geometry_score.shape[0]) != count:
            raise RuntimeError(
                "geometry chunk score length drifted from the candidate slice: "
                f"scores={int(geometry_score.shape[0])} poses={count}"
            )
        return {
            "bounded": bounded,
            "geometryScore": geometry_score,
            "temporalPenalty": temporal_penalty,
            "collisionError": collision_error,
            "strainError": strain_error,
            "depthError": absolute_depth_error,
            "depthRobustError": robust_depth_error,
            "depthQuality": depth_quality,
            "silhouetteIoU": silhouette_iou,
            "chromaQuality": chroma_quality_value,
            "chromaError": chroma_error,
            "chromaRobustError": chroma_robust_error,
            "predictedAlpha": predicted_alpha,
            "predictedDepth": predicted_depth,
            "predictedRgb": predicted_rgb,
        }

    def _score_batch(
        self,
        raw_bones,
        frame_position: int,
        root_translation_raw=None,
        root_rotation_raw=None,
        *,
        semantic_force: bool = False,
    ) -> dict[str, Any]:
        """Score exact triangles with depth as a tolerant signal on the target.

        Occupancy, including far limbs, is silhouette IoU. Depth is measured
        on every target-occupied pixel. Empty raster depth is 0 and far
        surfaces also encode near 0, so ``|0 - far|`` inside the depth
        tolerance would treat a missed back foot as a match. Uncovered target
        pixels are a full miss instead. The depth tolerance is for estimator
        noise on overlapping pixels, not for occupancy. Rim or thin-appendage
        reweighting is rejected: covering outline crumbs with any nearby mesh
        produces extreme bone rotations and LBS melt.

        When chroma_weight is set, every candidate is rastered as unlit RGB
        and scored with Lab a,b on the same target-occupied pixels. This is
        a decision term, not a later filter.

        Branch pair-grids may contain hundreds of poses. Each raster stays
        within ``score_raster_batch`` so LBS/nvdiffrast do not grow into
        Windows Shared GPU memory. Semantic ranking still sees the full wave.
        """
        import torch

        count = int(raw_bones.shape[0])
        root_translation = (
            root_translation_raw
            if root_translation_raw is not None
            else torch.zeros((count, 3), dtype=torch.float32, device=self.backend.device)
        )
        root_rotation = (
            root_rotation_raw
            if root_rotation_raw is not None
            else torch.zeros((count, 3), dtype=torch.float32, device=self.backend.device)
        )
        chunks = score_raster_chunks(count, int(self.config.score_raster_batch))
        parts = [
            self._score_geometry_chunk(
                raw_bones[start:end],
                frame_position,
                root_translation[start:end],
                root_rotation[start:end],
            )
            for start, end in chunks
        ]
        bounded = torch.cat([part["bounded"] for part in parts], dim=0)
        geometry_score = torch.cat([part["geometryScore"] for part in parts], dim=0)
        temporal_penalty = torch.cat([part["temporalPenalty"] for part in parts], dim=0)
        collision_error = torch.cat([part["collisionError"] for part in parts], dim=0)
        strain_error = torch.cat([part["strainError"] for part in parts], dim=0)
        absolute_depth_error = torch.cat([part["depthError"] for part in parts], dim=0)
        robust_depth_error = torch.cat([part["depthRobustError"] for part in parts], dim=0)
        depth_quality = torch.cat([part["depthQuality"] for part in parts], dim=0)
        silhouette_iou = torch.cat([part["silhouetteIoU"] for part in parts], dim=0)
        chroma_quality_value = torch.cat([part["chromaQuality"] for part in parts], dim=0)
        chroma_error = torch.cat([part["chromaError"] for part in parts], dim=0)
        chroma_robust_error = torch.cat([part["chromaRobustError"] for part in parts], dim=0)
        predicted_alpha = torch.cat([part["predictedAlpha"] for part in parts], dim=0)
        predicted_depth = torch.cat([part["predictedDepth"] for part in parts], dim=0)
        rgb_parts = [part.get("predictedRgb") for part in parts]
        if all(part is None for part in rgb_parts):
            predicted_rgb = None
        elif any(part is None for part in rgb_parts):
            raise RuntimeError("geometry chunks mixed RGB and non-RGB rasters")
        else:
            predicted_rgb = torch.cat(rgb_parts, dim=0)
        global_semantic_score, dense_semantic_score, semantic_evaluated = self._semantic_interleave_scores(
            bounded,
            root_translation,
            root_rotation,
            frame_position,
            geometry_score,
            force=semantic_force,
            predicted_rgb=predicted_rgb,
        )
        global_weight = float(self.config.semantic_weight) if self.semantic_embedder is not None else 0.0
        dense_weight = float(self.config.dense_semantic_weight) if self.dense_semantic_scorer is not None else 0.0
        semantic_weight = global_weight + dense_weight
        semantic_score = (
            global_weight * global_semantic_score + dense_weight * dense_semantic_score
        ) / max(semantic_weight, 1e-6)
        # Candidates outside the current semantic shortlist remain geometry-only.
        # A neutral placeholder is useful for diagnostics, but it must not be
        # treated as a real semantic opinion and penalize the unembedded tail.
        semantic_term = global_weight * global_semantic_score + dense_weight * dense_semantic_score
        score_with_semantics = (geometry_score + semantic_term) / (1.0 + semantic_weight)
        score = torch.where(semantic_evaluated, score_with_semantics, geometry_score)
        score = score - float(self.config.temporal_weight) * temporal_penalty
        if bool(self.config.collision_enabled):
            charged = collision_error_above_slack(
                collision_error,
                float(self.config.collision_positive_abs_slack),
            )
            score = score - float(self.config.collision_weight) * charged
        if bool(self.config.strain_enabled):
            score = score - float(self.config.strain_weight) * strain_error
        self.evaluation_count += count
        return {
            "score": score,
            "geometryScore": geometry_score,
            "semanticScore": semantic_score,
            "globalSemanticScore": global_semantic_score,
            "denseSemanticScore": dense_semantic_score,
            "semanticEvaluated": semantic_evaluated,
            "temporalPenalty": temporal_penalty,
            "collisionError": collision_error,
            "strainError": strain_error,
            "depthError": absolute_depth_error,
            "depthRobustError": robust_depth_error,
            "depthQuality": depth_quality,
            "silhouetteIoU": silhouette_iou,
            "chromaQuality": chroma_quality_value,
            "chromaError": chroma_error,
            "chromaRobustError": chroma_robust_error,
            "predictedAlpha": predicted_alpha,
            "predictedDepth": predicted_depth,
        }

    def _candidate_wave(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
        node_index: int,
        axis: str,
        angles_deg: np.ndarray,
    ) -> tuple[Any, Any, Any, dict[str, Any]]:
        import torch

        axis_index = _axis_index(axis)
        candidates = state_raw.expand(len(angles_deg), -1, -1).clone()
        candidate_translation = root_translation_raw.expand(len(angles_deg), -1).clone()
        candidate_rotation = root_rotation_raw.expand(len(angles_deg), -1).clone()
        candidates[:, node_index, axis_index] = self._raw_for_angle(angles_deg, node_index)
        scored = self._score_batch(
            candidates,
            frame_position,
            candidate_translation,
            candidate_rotation,
        )
        best_index = int(torch.argmax(scored["score"]).item())
        best = candidates[best_index : best_index + 1].clone()
        info = self._score_info(scored, best_index)
        info.update({
            "bestAngleDeg": float(angles_deg[best_index]),
            "candidateAnglesDeg": [float(value) for value in angles_deg.tolist()],
        })
        return (
            best,
            candidate_translation[best_index : best_index + 1].clone(),
            candidate_rotation[best_index : best_index + 1].clone(),
            info,
        )

    def _multi_bone_absolute_grid(
        self,
        node_indices: Sequence[int],
        step_deg: float,
    ) -> np.ndarray:
        """Build a full per-bone joint-limit grid for a branch block.

        Branch mode normally searches offsets around the accepted pose.  The
        first global sweep deliberately ignores that center so a bad bind or
        previous-frame seed cannot prevent a large action rotation from being
        considered.  This is kept as an explicit bounded grid rather than a
        hidden fallback: if the requested Cartesian product exceeds the cap,
        fail with the setting that must be changed.
        """
        nodes = tuple(int(index) for index in node_indices)
        values_by_node: list[np.ndarray] = []
        for node_index in nodes:
            limit = float(self.config.joint_limit_deg) * float(
                self.backend.bone_limit_scales[node_index].detach().cpu().item()
            )
            values_by_node.append(_inclusive_grid(-limit, limit, float(step_deg)))
        candidate_count = int(np.prod([len(values) for values in values_by_node], dtype=np.int64))
        max_candidates = int(self.config.multi_bone_max_candidates)
        if candidate_count > max_candidates:
            raise RuntimeError(
                "multi-bone global candidate grid exceeded its bound: "
                f"group={len(nodes)} values={[len(values) for values in values_by_node]} "
                f"candidates={candidate_count} max={max_candidates}; "
                "increase multi_bone_max_candidates, increase the search step, "
                "or reduce multi_bone_block_size"
            )
        return np.asarray(
            list(itertools.product(*(values.tolist() for values in values_by_node))),
            dtype=np.float32,
        )

    def _branch_candidate_wave(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
        node_indices: Sequence[int],
        axis: str,
        center_angles_deg: Sequence[float],
        radius_deg: float,
        step_deg: float,
        absolute: bool = False,
    ) -> tuple[Any, Any, Any, dict[str, Any]]:
        """Score bounded combinations for one axis across a dependency block.

        ``absolute=True`` performs a full joint-limit sweep.  Local waves are
        still used for later rounds because they provide inexpensive basin
        refinement after the broad sweep has found a plausible region.
        """
        import torch

        nodes = tuple(int(index) for index in node_indices)
        if len(nodes) < 2:
            raise ValueError("branch candidate waves require at least two bones")
        if len(center_angles_deg) != len(nodes):
            raise ValueError("branch candidate centers do not match node count")
        centers = np.asarray(tuple(float(value) for value in center_angles_deg), dtype=np.float32)
        if absolute:
            angle_matrix = self._multi_bone_absolute_grid(nodes, step_deg)
            offsets = angle_matrix - centers[None, :]
        else:
            offsets = self._multi_bone_offset_grid(len(nodes), radius_deg, step_deg)
            angle_matrix = centers[None, :] + offsets
        for column, node_index in enumerate(nodes):
            node_limit = float(self.config.joint_limit_deg) * float(
                self.backend.bone_limit_scales[node_index].detach().cpu().item()
            )
            angle_matrix[:, column] = np.clip(angle_matrix[:, column], -node_limit, node_limit)
        candidates = state_raw.expand(len(angle_matrix), -1, -1).clone()
        candidate_translation = root_translation_raw.expand(len(angle_matrix), -1).clone()
        candidate_rotation = root_rotation_raw.expand(len(angle_matrix), -1).clone()
        axis_index = _axis_index(axis)
        for column, node_index in enumerate(nodes):
            candidates[:, node_index, axis_index] = self._raw_for_angle(
                angle_matrix[:, column], node_index
            )
        scored = self._score_batch(
            candidates,
            frame_position,
            candidate_translation,
            candidate_rotation,
        )
        best_index = int(torch.argmax(scored["score"]).item())
        best = candidates[best_index : best_index + 1].clone()
        info = self._score_info(scored, best_index)
        info.update({
            "bestAnglesDeg": [float(value) for value in angle_matrix[best_index].tolist()],
            "candidateCount": int(len(angle_matrix)),
            "candidateOffsetsDeg": offsets.tolist(),
            "searchSpace": "absolute" if absolute else "local",
            "searchRadiusDeg": float(radius_deg),
            "searchStepDeg": float(step_deg),
        })
        return (
            best,
            candidate_translation[best_index : best_index + 1].clone(),
            candidate_rotation[best_index : best_index + 1].clone(),
            info,
        )

    def _packed_axis_jobs(
        self,
        state_raw,
        remaining: Sequence[tuple[int, str]],
        max_batch: int,
    ) -> list[dict[str, Any]]:
        """Take the next whole-axis 1D jobs that fit in one raster."""
        import torch

        if not remaining:
            return []
        bounded = torch.rad2deg(self.backend._bounded_bone_vectors(state_raw)[0]).detach().cpu().numpy()
        jobs: list[dict[str, Any]] = []
        used = 0
        limit = float(self.config.joint_limit_deg)
        for node_index, axis in remaining:
            current_angle = float(bounded[int(node_index), _axis_index(axis)])
            angles = pass_angle_grid(
                current_angle,
                joint_limit_deg=limit,
                pass_limit_deg=float(self.config.pass_limit_deg),
                pass_step_deg=float(self.config.pass_step_deg),
            )
            width = int(len(angles))
            if width > int(max_batch):
                raise ValueError(
                    "an axis window has more candidates than packed_axis_batch: "
                    f"job={width} packed_axis_batch={int(max_batch)}; "
                    "increase packed_axis_batch or pass_step_deg"
                )
            if jobs and used + width > int(max_batch):
                break
            jobs.append(
                {
                    "nodeIndex": int(node_index),
                    "axis": str(axis),
                    "anglesDeg": angles,
                    "startAngleDeg": current_angle,
                }
            )
            used += width
        if not jobs:
            raise ValueError(
                "packed_axis_batch is smaller than the first axis window: "
                f"packed_axis_batch={int(max_batch)}"
            )
        return jobs

    def _score_packed_axis_jobs(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
        frame: int,
        jobs: Sequence[Mapping[str, Any]],
        progress: bool,
        history: list[dict[str, Any]],
    ):
        """Score several 1D axis windows against one start pose, then apply every winner."""
        import torch

        lengths = [len(job["anglesDeg"]) for job in jobs]
        count = int(sum(lengths))
        candidates = state_raw.expand(count, -1, -1).clone()
        candidate_translation = root_translation_raw.expand(count, -1).clone()
        candidate_rotation = root_rotation_raw.expand(count, -1).clone()
        offset = 0
        slices: list[slice] = []
        for job in jobs:
            angles = np.asarray(job["anglesDeg"], dtype=np.float64)
            node_index = int(job["nodeIndex"])
            axis_index = _axis_index(str(job["axis"]))
            width = int(len(angles))
            slot = slice(offset, offset + width)
            candidates[slot, node_index, axis_index] = self._raw_for_angle(angles, node_index)
            slices.append(slot)
            offset += width
        scored = self._score_batch(
            candidates,
            frame_position,
            candidate_translation,
            candidate_rotation,
        )
        updated = state_raw.clone()
        moved_names: list[str] = []
        for job, slot in zip(jobs, slices):
            local_best = int(torch.argmax(scored["score"][slot]).item())
            absolute = int(slot.start) + local_best
            node_index = int(job["nodeIndex"])
            axis_index = _axis_index(str(job["axis"]))
            updated[0, node_index, axis_index] = candidates[absolute, node_index, axis_index]
            info = self._score_info(scored, absolute)
            angles = np.asarray(job["anglesDeg"], dtype=np.float64)
            best_angle = float(angles[local_best])
            start_angle = float(job["startAngleDeg"])
            info.update(
                {
                    "bestAngleDeg": best_angle,
                    "candidateAnglesDeg": [float(value) for value in angles.tolist()],
                    "candidateCount": int(len(angles)),
                }
            )
            history.append(
                {
                    "frame": int(frame),
                    "framePosition": int(frame_position),
                    "bone": self.node_names[node_index],
                    "boneIndex": node_index,
                    "axis": str(job["axis"]),
                    "coarse": {"skipped": "packed_axis_batch"},
                    "refine": info,
                    "evaluations": int(len(angles)),
                    "passLimitDeg": float(self.config.pass_limit_deg),
                    "startAngleDeg": start_angle,
                    "packed": True,
                    "packedBatch": count,
                }
            )
            delta = best_angle - start_angle
            moved = abs(delta) >= max(float(self.config.pass_step_deg) * 0.5, 1e-6)
            label = f"{self.node_names[node_index]} {job['axis']}"
            if progress and moved:
                print(
                    f"depth f{frame:02d} {label} "
                    f"score={info['bestScore']:.4f} "
                    f"iou={info['bestSilhouetteIoU']:.4f} "
                    f"angle={best_angle:.1f} "
                    f"delta={delta:+.1f} "
                    f"temp={info.get('bestTemporalPenalty', 0.0):.4f} "
                    f"coll={info.get('bestCollisionError', 0.0):.4f} "
                    f"strain={info.get('bestStrainError', 0.0):.4f} "
                    f"evals={self.evaluation_count}",
                    flush=True,
                )
                self._last_heartbeat = time.perf_counter()
                moved_names.append(label)
            elif progress:
                self._maybe_heartbeat(frame=int(frame), label=label, progress=True)
        if progress:
            print(
                f"depth f{int(frame):02d} packed jobs={len(jobs)} poses={count} "
                f"moved={len(moved_names)} evals={self.evaluation_count}",
                flush=True,
            )
        return updated, root_translation_raw, root_rotation_raw

    def _scan_packed_pass(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
        frame: int,
        progress: bool,
        history: list[dict[str, Any]],
    ):
        """Walk dependency-ordered axes, scoring as many 1D windows as fit in one raster."""
        remaining: deque[tuple[int, str]] = deque(
            (int(node_index), str(axis))
            for node_index in self._frame_walk_indices
            for axis in self.config.search_axes
        )
        max_batch = int(self.config.packed_axis_batch)
        while remaining:
            jobs = self._packed_axis_jobs(state_raw, remaining, max_batch)
            for _ in jobs:
                remaining.popleft()
            state_raw, root_translation_raw, root_rotation_raw = self._score_packed_axis_jobs(
                state_raw,
                root_translation_raw,
                root_rotation_raw,
                frame_position=frame_position,
                frame=int(frame),
                jobs=jobs,
                progress=progress,
                history=history,
            )
            last = jobs[-1]
            self._refresh_live_preview(
                frame=int(frame),
                frame_position=frame_position,
                label=(
                    f"f{int(frame):02d} packed {self.node_names[int(last['nodeIndex'])]}"
                ),
                state_raw=state_raw,
                root_translation_raw=root_translation_raw,
                root_rotation_raw=root_rotation_raw,
            )
        return state_raw, root_translation_raw, root_rotation_raw

    def _score_region_iou_batch(
        self,
        raw_bones,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
        region: np.ndarray,
        target_mask: np.ndarray,
    ) -> list[float]:
        """Raster candidates and return leftover-neighborhood IoU per pose."""
        import torch

        from ik_incremental_blob import region_iou

        count = int(raw_bones.shape[0])
        scores: list[float] = []
        threshold = float(self.config.blob_exhaustive_predicted_alpha_threshold)
        chunks = score_raster_chunks(count, int(self.config.score_raster_batch))
        for start, end in chunks:
            bounded = self.backend._bounded_bone_vectors(raw_bones[start:end])
            with torch.no_grad():
                predicted_alpha, _predicted_depth = self.backend._exact_triangle_raster(
                    bounded,
                    root_translation_raw[start:end],
                    root_rotation_raw[start:end],
                    bone_mask=self.backend.active_node_mask,
                )
            predicted = predicted_alpha.detach().cpu().numpy()
            for index in range(int(predicted.shape[0])):
                scores.append(
                    region_iou(
                        predicted[index],
                        target_mask,
                        region,
                        predicted_threshold=threshold,
                    )
                )
        if len(scores) != count:
            raise RuntimeError(
                f"blob exhaustive scored {len(scores)} poses for a batch of {count}"
            )
        self.evaluation_count += count
        return scores

    def _accept_regional_winner(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        candidates,
        candidate_translation,
        candidate_rotation,
        *,
        frame_position: int,
        region: np.ndarray,
        target_mask: np.ndarray,
    ):
        """Keep candidate 0 unless a later pose has strictly higher regional IoU
        and does not raise mixed-edge strain past the opening plus slack.
        Occupancy ignore and leftover-blob search do not see LBS melt.
        """
        from gpu_mesh_strain import regional_winner_index

        scores = self._score_region_iou_batch(
            candidates,
            candidate_translation,
            candidate_rotation,
            frame_position=frame_position,
            region=region,
            target_mask=target_mask,
        )
        strain_errors = None
        if bool(self.config.strain_enabled):
            strain = self._strain_error_raw_batch(candidates)
            strain_errors = [float(value) for value in strain.detach().cpu().tolist()]
        winner = regional_winner_index(
            scores,
            strain_errors,
            strain_slack=float(self.config.strain_accept_slack),
        )
        return (
            candidates[winner : winner + 1].clone(),
            candidate_translation[winner : winner + 1].clone(),
            candidate_rotation[winner : winner + 1].clone(),
            {
                "openingIoU": float(scores[0]),
                "bestIoU": float(scores[winner]),
                "openingStrain": None if strain_errors is None else float(strain_errors[0]),
                "bestStrain": None if strain_errors is None else float(strain_errors[winner]),
                "winnerIndex": winner,
                "candidateCount": int(len(scores)),
                "improved": int(winner) != 0,
            },
        )

    def _scan_blob_axis(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
        node_index: int,
        axis: str,
        angles_deg: np.ndarray,
        region: np.ndarray,
        target_mask: np.ndarray,
    ):
        import torch

        count = int(len(angles_deg))
        if count < 1:
            raise ValueError("blob exhaustive axis grid is empty")
        candidates = state_raw.expand(count, -1, -1).clone()
        candidate_translation = root_translation_raw.expand(count, -1).clone()
        candidate_rotation = root_rotation_raw.expand(count, -1).clone()
        candidates[:, int(node_index), _axis_index(axis)] = self._raw_for_angle(
            angles_deg, int(node_index)
        )
        candidates[0] = state_raw[0]
        return self._accept_regional_winner(
            state_raw,
            root_translation_raw,
            root_rotation_raw,
            candidates,
            candidate_translation,
            candidate_rotation,
            frame_position=frame_position,
            region=region,
            target_mask=target_mask,
        )

    def _scan_blob_cartesian(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
        node_indices: Sequence[int],
        axis: str,
        region: np.ndarray,
        target_mask: np.ndarray,
    ):
        import torch

        from blob_exhaustive import require_blob_grid_fits

        nodes = tuple(int(index) for index in node_indices)
        if len(nodes) < 2:
            raise ValueError("blob exhaustive Cartesian search needs at least two bones")
        angles = _inclusive_grid(
            -float(self.config.joint_limit_deg),
            float(self.config.joint_limit_deg),
            float(self.config.coarse_step_deg),
        )
        require_blob_grid_fits(
            bone_count=len(nodes),
            angle_count=int(len(angles)),
            max_candidates=int(self.config.multi_bone_max_candidates),
        )
        angle_matrix = self._multi_bone_absolute_grid(nodes, float(self.config.coarse_step_deg))
        if int(len(angle_matrix)) > int(self.config.multi_bone_max_candidates):
            raise RuntimeError(
                "blob exhaustive Cartesian grid exceeds max_candidates: "
                f"candidates={int(len(angle_matrix))} "
                f"max={int(self.config.multi_bone_max_candidates)}"
            )
        candidates = state_raw.expand(len(angle_matrix) + 1, -1, -1).clone()
        candidate_translation = root_translation_raw.expand(len(angle_matrix) + 1, -1).clone()
        candidate_rotation = root_rotation_raw.expand(len(angle_matrix) + 1, -1).clone()
        axis_index = _axis_index(axis)
        for column, node_index in enumerate(nodes):
            candidates[1:, node_index, axis_index] = self._raw_for_angle(
                angle_matrix[:, column], node_index
            )
        candidates[0] = state_raw[0]
        return self._accept_regional_winner(
            state_raw,
            root_translation_raw,
            root_rotation_raw,
            candidates,
            candidate_translation,
            candidate_rotation,
            frame_position=frame_position,
            region=region,
            target_mask=target_mask,
        )

    def _sprite_delta_init_pass(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
        frame: int,
        progress: bool,
        history: list[dict[str, Any]],
    ):
        """Prime later-frame bones from sprite-to-sprite occupancy, then keep if regional IoU rises."""
        import torch

        from ik_incremental_blob import repair_region_from_blobs
        from ik_silhouette_miss_keypoints import (
            assign_joint_by_influence,
            excess_predicted_silhouette,
            pair_silhouette_misses,
        )
        from roc_gpu_cascade_experiment import compute_search_bone_influence_in_mask
        from sprite_delta_init import clipped_axis_targets, sprite_delta_moves_from_pairs

        if not bool(self.config.sprite_delta_init_enabled):
            return state_raw, root_translation_raw, root_rotation_raw
        if int(frame_position) < 1:
            return state_raw, root_translation_raw, root_rotation_raw
        previous_mask = self.backend.target_masks[int(frame_position) - 1].detach().cpu().numpy()
        current_mask = self.backend.target_masks[int(frame_position)].detach().cpu().numpy()
        previous_depth = self.backend.target_depth[int(frame_position) - 1].detach().cpu().numpy()
        current_depth = self.backend.target_depth[int(frame_position)].detach().cpu().numpy()
        pairs = pair_silhouette_misses(
            current_mask,
            previous_mask,
            current_depth,
            previous_depth,
            predicted_alpha_threshold=0.5,
            depth_tolerance=float(self.config.sprite_delta_init_depth_tolerance),
            min_component_area=int(self.config.sprite_delta_init_min_component_area),
            max_pairs=int(self.config.sprite_delta_init_max_pairs),
            max_tip_distance_px=float(self.config.sprite_delta_init_max_tip_distance_px),
            max_centroid_distance_px=float(self.config.sprite_delta_init_max_centroid_distance_px),
            max_area_ratio=float(self.config.sprite_delta_init_max_area_ratio),
            min_displacement_alignment=float(self.config.sprite_delta_init_min_displacement_alignment),
        )
        disappeared = excess_predicted_silhouette(
            current_mask,
            previous_mask,
            threshold=0.5,
        )
        appeared = missing_target_silhouette(
            current_mask,
            previous_mask,
            threshold=0.5,
        )
        excess_labels, _excess_count = label_binary_components(disappeared)
        miss_labels, _miss_count = label_binary_components(appeared)
        projected = self._projected_joint_xy(state_raw, root_translation_raw, root_rotation_raw)[0]
        joint_xy = {
            str(self.node_names[int(index)]): (
                float(projected[int(index), 0].item()),
                float(projected[int(index), 1].item()),
            )
            for index in self.bone_indices
            if int(self.backend.node_depths[int(index)])
            >= int(self.config.sprite_delta_init_min_bone_depth)
        }
        allowed = tuple(joint_xy)
        frame_count = len(self.frame_indices)
        clip_bones = state_raw.expand(frame_count, -1, -1).contiguous().clone()
        clip_translation = root_translation_raw.expand(frame_count, -1).contiguous().clone()
        clip_rotation = root_rotation_raw.expand(frame_count, -1).contiguous().clone()
        clip_bones[int(frame_position)] = state_raw[0]
        clip_translation[int(frame_position)] = root_translation_raw[0]
        clip_rotation[int(frame_position)] = root_rotation_raw[0]

        def bone_name_for_pair(pair):
            if not allowed:
                return None
            excess_mask = excess_labels == int(pair.excess_label_id)
            persisted = self._persist_blob_bone(
                excess_mask,
                min_bone_depth=int(self.config.sprite_delta_init_min_bone_depth),
            )
            if persisted is not None:
                return persisted
            influence = compute_search_bone_influence_in_mask(
                self.backend,
                clip_bones,
                clip_translation,
                clip_rotation,
                frame_position=int(frame_position),
                region_mask=excess_mask,
                min_bone_depth=int(self.config.sprite_delta_init_min_bone_depth),
            )
            return assign_joint_by_influence(
                influence,
                allowed=allowed,
                node_depth=lambda name: int(
                    self.backend.node_depths[self.backend.node_index[str(name)]]
                ),
            )

        moves = sprite_delta_moves_from_pairs(
            pairs,
            joint_xy=joint_xy,
            bone_name_for_pair=bone_name_for_pair,
            min_radius_px=float(self.config.sprite_delta_init_min_radius_px),
            min_angle_deg=float(self.config.sprite_delta_init_min_angle_deg),
        )
        if progress:
            print(
                f"depth f{int(frame):02d} sprite-delta init "
                f"pairs={len(pairs)} moves={len(moves)}",
                flush=True,
            )
        move_reports: list[dict[str, Any]] = []
        for move in moves:
            node_index = int(self.backend.node_index[str(move.bone_name)])
            matching = [
                pair
                for pair in pairs
                if abs(float(pair.excess_tip[0]) - float(move.disappeared_tip[0])) < 1e-6
                and abs(float(pair.excess_tip[1]) - float(move.disappeared_tip[1])) < 1e-6
            ]
            if not matching:
                raise RuntimeError(f"sprite-delta move lost its occupancy pair: {move.bone_name}")
            pair = matching[0]
            region = repair_region_from_blobs(
                excess_labels == int(pair.excess_label_id),
                miss_labels == int(pair.missing_label_id),
                dilate_px=int(self.config.sprite_delta_init_dilate_px),
            )
            bounded = torch.rad2deg(self.backend._bounded_bone_vectors(state_raw)[0]).detach().cpu().numpy()
            current_by_axis = {
                str(axis): float(bounded[node_index, _axis_index(axis)])
                for axis in self.config.search_axes
            }
            limit = float(self.config.joint_limit_deg) * float(self._bone_limit_scale_cpu[node_index])
            targets = clipped_axis_targets(
                current_by_axis,
                float(move.angle_deg),
                joint_limit_deg=limit,
            )
            candidate_count = 1 + len(targets)
            candidates = state_raw.expand(candidate_count, -1, -1).clone()
            candidate_translation = root_translation_raw.expand(candidate_count, -1).clone()
            candidate_rotation = root_rotation_raw.expand(candidate_count, -1).clone()
            for slot, (axis, angle) in enumerate(targets, start=1):
                raw = self._raw_for_angle(np.asarray((angle,), dtype=np.float64), node_index)
                candidates[slot, node_index, _axis_index(axis)] = raw[0]
            candidates[0] = state_raw[0]
            state_raw, root_translation_raw, root_rotation_raw, accept = self._accept_regional_winner(
                state_raw,
                root_translation_raw,
                root_rotation_raw,
                candidates,
                candidate_translation,
                candidate_rotation,
                frame_position=int(frame_position),
                region=region,
                target_mask=current_mask,
            )
            winner = int(accept["winnerIndex"])
            chosen_axis = None if winner == 0 else str(targets[winner - 1][0])
            chosen_angle = None if winner == 0 else float(targets[winner - 1][1])
            move_reports.append(
                {
                    "bone": str(move.bone_name),
                    "requestedDeg": float(move.angle_deg),
                    "chosenAxis": chosen_axis,
                    "chosenDeg": chosen_angle,
                    "improved": bool(accept["improved"]),
                    "openingIoU": float(accept["openingIoU"]),
                    "bestIoU": float(accept["bestIoU"]),
                    "openingStrain": accept["openingStrain"],
                    "bestStrain": accept["bestStrain"],
                    "disappearedArea": int(move.disappeared_area),
                    "appearedArea": int(move.appeared_area),
                }
            )
            if progress:
                print(
                    f"depth f{int(frame):02d} sprite-delta {move.bone_name} "
                    f"req={float(move.angle_deg):.1f}deg "
                    f"axis={chosen_axis or 'none'} "
                    f"kept={0.0 if chosen_angle is None else chosen_angle:.1f} "
                    f"iou={float(accept['openingIoU']):.4f}->{float(accept['bestIoU']):.4f} "
                    f"strain={0.0 if accept['openingStrain'] is None else float(accept['openingStrain']):.4f}"
                    f"->{0.0 if accept['bestStrain'] is None else float(accept['bestStrain']):.4f} "
                    f"accepted={bool(accept['improved'])}",
                    flush=True,
                )
            if bool(accept["improved"]):
                self._sprite_delta_moved_bones.add(str(move.bone_name))
            clip_bones[int(frame_position)] = state_raw[0]
            clip_translation[int(frame_position)] = root_translation_raw[0]
            clip_rotation[int(frame_position)] = root_rotation_raw[0]
        history.append(
            {
                "frame": int(frame),
                "framePosition": int(frame_position),
                "stage": "sprite_delta_init",
                "pairCount": int(len(pairs)),
                "moveCount": int(len(moves)),
                "moves": move_reports,
            }
        )
        if moves:
            self._refresh_live_preview(
                frame=int(frame),
                frame_position=frame_position,
                label=f"f{int(frame):02d} sprite-delta init",
                state_raw=state_raw,
                root_translation_raw=root_translation_raw,
                root_rotation_raw=root_rotation_raw,
                force=True,
            )
        return state_raw, root_translation_raw, root_rotation_raw

    def _blob_exhaustive_pass(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
        frame: int,
        progress: bool,
        history: list[dict[str, Any]],
    ):
        """Attribute leftover blobs, then exhaust the distal chain regionally."""
        import torch

        from blob_exhaustive import (
            blob_exhaustive_chain,
            split_blob_exhaustive_search,
        )
        from roc_gpu_cascade_experiment import derive_ik_blob_jobs

        if not bool(self.config.blob_exhaustive_enabled):
            return state_raw, root_translation_raw, root_rotation_raw
        frame_count = len(self.frame_indices)
        clip_bones = state_raw.expand(frame_count, -1, -1).contiguous().clone()
        clip_translation = root_translation_raw.expand(frame_count, -1).contiguous().clone()
        clip_rotation = root_rotation_raw.expand(frame_count, -1).contiguous().clone()
        clip_bones[int(frame_position)] = state_raw[0]
        clip_translation[int(frame_position)] = root_translation_raw[0]
        clip_rotation[int(frame_position)] = root_rotation_raw[0]
        jobs_by_position = derive_ik_blob_jobs(
            self.backend,
            clip_bones,
            clip_translation,
            clip_rotation,
            frame_positions=(int(frame_position),),
        )
        jobs = jobs_by_position.get(int(frame_position), [])
        from dataclasses import replace as replace_dataclass

        rewritten: list[Any] = []
        used_bones: set[str] = set()
        skipped_hold: list[str] = []
        for job in jobs:
            persisted = self._persist_blob_bone(
                job.excess_mask,
                min_bone_depth=int(self.config.blob_exhaustive_min_bone_depth),
            )
            name = persisted or str(job.bone_name)
            if name in self._held_bone_names:
                skipped_hold.append(name)
                continue
            if name in used_bones:
                continue
            if name != str(job.bone_name):
                if name not in self.backend.node_index:
                    raise RuntimeError(f"persisted blob bone {name!r} is not in the skeleton")
                job = replace_dataclass(
                    job,
                    bone_name=str(name),
                    bone_index=int(self.backend.node_index[str(name)]),
                )
            rewritten.append(job)
            used_bones.add(str(name))
        jobs = rewritten
        if progress:
            print(
                f"depth f{int(frame):02d} blob exhaustive "
                f"pairs={len(jobs)} "
                f"heldSkip={len(skipped_hold)} "
                f"minDepth={int(self.config.blob_exhaustive_min_bone_depth)} "
                f"block={int(self.config.blob_exhaustive_block_size)}",
                flush=True,
            )
        if not jobs:
            history.append(
                {
                    "frame": int(frame),
                    "framePosition": int(frame_position),
                    "stage": "blob_exhaustive",
                    "pairCount": 0,
                    "jobs": [],
                }
            )
            return state_raw, root_translation_raw, root_rotation_raw
        target_mask = self.backend.target_masks[int(frame_position)].detach().cpu().numpy()
        job_reports: list[dict[str, Any]] = []
        limit = float(self.config.joint_limit_deg)
        for job in jobs:
            try:
                chain = blob_exhaustive_chain(
                    int(job.bone_index),
                    self.backend.parents,
                    self.backend.node_depths,
                    max_joints=int(self.config.blob_exhaustive_max_chain_depth),
                    min_bone_depth=int(self.config.blob_exhaustive_min_bone_depth),
                )
            except ValueError as exc:
                job_reports.append(
                    {
                        "bone": str(job.bone_name),
                        "skipped": str(exc),
                        "excessArea": int(job.excess_area),
                        "missingArea": int(job.missing_area),
                    }
                )
                continue
            cartesian, remaining = split_blob_exhaustive_search(
                chain,
                block_size=int(self.config.blob_exhaustive_block_size),
            )
            region = np.asarray(job.repair_region, dtype=bool)
            opening_scores = self._score_region_iou_batch(
                state_raw,
                root_translation_raw,
                root_rotation_raw,
                frame_position=int(frame_position),
                region=region,
                target_mask=target_mask,
            )
            opening_iou = float(opening_scores[0])
            axis_reports: list[dict[str, Any]] = []
            for axis in self.config.search_axes:
                if len(cartesian) >= 2:
                    state_raw, root_translation_raw, root_rotation_raw, info = self._scan_blob_cartesian(
                        state_raw,
                        root_translation_raw,
                        root_rotation_raw,
                        frame_position=int(frame_position),
                        node_indices=cartesian,
                        axis=str(axis),
                        region=region,
                        target_mask=target_mask,
                    )
                    axis_reports.append({"axis": str(axis), "mode": "cartesian", **info})
                else:
                    for node_index in cartesian:
                        current_angle = float(
                            torch.rad2deg(
                                self.backend._bounded_bone_vectors(state_raw)[
                                    0, int(node_index), _axis_index(axis)
                                ]
                            ).item()
                        )
                        coarse = _inclusive_grid(-limit, limit, float(self.config.coarse_step_deg))
                        coarse = np.unique(
                            np.concatenate((coarse, np.asarray((current_angle,), dtype=np.float64)))
                        )
                        state_raw, root_translation_raw, root_rotation_raw, info = self._scan_blob_axis(
                            state_raw,
                            root_translation_raw,
                            root_rotation_raw,
                            frame_position=int(frame_position),
                            node_index=int(node_index),
                            axis=str(axis),
                            angles_deg=coarse,
                            region=region,
                            target_mask=target_mask,
                        )
                        axis_reports.append(
                            {
                                "axis": str(axis),
                                "mode": "axis",
                                "bone": self.node_names[int(node_index)],
                                **info,
                            }
                        )
            for node_index in remaining:
                for axis in self.config.search_axes:
                    current_angle = float(
                        torch.rad2deg(
                            self.backend._bounded_bone_vectors(state_raw)[
                                0, int(node_index), _axis_index(axis)
                            ]
                        ).item()
                    )
                    coarse = _inclusive_grid(-limit, limit, float(self.config.coarse_step_deg))
                    coarse = np.unique(
                        np.concatenate((coarse, np.asarray((current_angle,), dtype=np.float64)))
                    )
                    state_raw, root_translation_raw, root_rotation_raw, info = self._scan_blob_axis(
                        state_raw,
                        root_translation_raw,
                        root_rotation_raw,
                        frame_position=int(frame_position),
                        node_index=int(node_index),
                        axis=str(axis),
                        angles_deg=coarse,
                        region=region,
                        target_mask=target_mask,
                    )
                    axis_reports.append(
                        {
                            "axis": str(axis),
                            "mode": "parent_axis",
                            "bone": self.node_names[int(node_index)],
                            **info,
                        }
                    )
            for node_index in chain:
                for axis in self.config.search_axes:
                    current_angle = float(
                        torch.rad2deg(
                            self.backend._bounded_bone_vectors(state_raw)[
                                0, int(node_index), _axis_index(axis)
                            ]
                        ).item()
                    )
                    refine = _inclusive_grid(
                        max(-limit, current_angle - float(self.config.refine_radius_deg)),
                        min(limit, current_angle + float(self.config.refine_radius_deg)),
                        float(self.config.refine_step_deg),
                    )
                    refine = np.unique(
                        np.concatenate((refine, np.asarray((current_angle,), dtype=np.float64)))
                    )
                    state_raw, root_translation_raw, root_rotation_raw, info = self._scan_blob_axis(
                        state_raw,
                        root_translation_raw,
                        root_rotation_raw,
                        frame_position=int(frame_position),
                        node_index=int(node_index),
                        axis=str(axis),
                        angles_deg=refine,
                        region=region,
                        target_mask=target_mask,
                    )
                    axis_reports.append(
                        {
                            "axis": str(axis),
                            "mode": "refine",
                            "bone": self.node_names[int(node_index)],
                            **info,
                        }
                    )
            closing_scores = self._score_region_iou_batch(
                state_raw,
                root_translation_raw,
                root_rotation_raw,
                frame_position=int(frame_position),
                region=region,
                target_mask=target_mask,
            )
            report = {
                "bone": str(job.bone_name),
                "chain": [self.node_names[int(index)] for index in chain],
                "cartesian": [self.node_names[int(index)] for index in cartesian],
                "remaining": [self.node_names[int(index)] for index in remaining],
                "excessArea": int(job.excess_area),
                "missingArea": int(job.missing_area),
                "openingIoU": opening_iou,
                "closingIoU": float(closing_scores[0]),
                "axes": axis_reports,
            }
            job_reports.append(report)
            if progress:
                print(
                    f"depth f{int(frame):02d} blob {job.bone_name} "
                    f"chain={'+'.join(report['chain'])} "
                    f"iou {opening_iou:.3f}->{report['closingIoU']:.3f}",
                    flush=True,
                )
            self._refresh_live_preview(
                frame=int(frame),
                frame_position=int(frame_position),
                label=f"f{int(frame):02d} blob {job.bone_name}",
                state_raw=state_raw,
                root_translation_raw=root_translation_raw,
                root_rotation_raw=root_rotation_raw,
            )
        history.append(
            {
                "frame": int(frame),
                "framePosition": int(frame_position),
                "stage": "blob_exhaustive",
                "pairCount": int(len(jobs)),
                "jobs": job_reports,
            }
        )
        return state_raw, root_translation_raw, root_rotation_raw

    def _scan_axis(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
        frame: int,
        node_index: int,
        axis: str,
        progress: bool,
        history: list[dict[str, Any]],
    ):
        import torch

        limit = float(self.config.joint_limit_deg)
        current_angle = float(
            torch.rad2deg(self.backend._bounded_bone_vectors(state_raw)[0, node_index, _axis_index(axis)]).item()
        )
        if float(self.config.pass_limit_deg) > 0.0:
            angles = pass_angle_grid(
                current_angle,
                joint_limit_deg=limit,
                pass_limit_deg=float(self.config.pass_limit_deg),
                pass_step_deg=float(self.config.pass_step_deg),
            )
            state_raw, root_translation_raw, root_rotation_raw, pass_info = self._candidate_wave(
                state_raw,
                root_translation_raw,
                root_rotation_raw,
                frame_position=frame_position,
                node_index=node_index,
                axis=axis,
                angles_deg=angles,
            )
            refine_info = pass_info
            coarse_info = {
                "skipped": "pass_limit_deg",
                "windowDeg": [float(angles[0]), float(angles[-1])],
                "candidateCount": int(len(angles)),
            }
            evaluations = int(len(angles))
        else:
            coarse = _inclusive_grid(-limit, limit, float(self.config.coarse_step_deg))
            coarse = np.unique(np.concatenate((coarse, np.asarray((current_angle,), dtype=np.float64))))
            state_raw, root_translation_raw, root_rotation_raw, coarse_info = self._candidate_wave(
                state_raw,
                root_translation_raw,
                root_rotation_raw,
                frame_position=frame_position,
                node_index=node_index,
                axis=axis,
                angles_deg=coarse,
            )
            coarse_best = float(coarse_info["bestAngleDeg"])
            refine = _inclusive_grid(
                max(-limit, coarse_best - float(self.config.refine_radius_deg)),
                min(limit, coarse_best + float(self.config.refine_radius_deg)),
                float(self.config.refine_step_deg),
            )
            refine = np.unique(np.concatenate((refine, np.asarray((coarse_best,), dtype=np.float64))))
            state_raw, root_translation_raw, root_rotation_raw, refine_info = self._candidate_wave(
                state_raw,
                root_translation_raw,
                root_rotation_raw,
                frame_position=frame_position,
                node_index=node_index,
                axis=axis,
                angles_deg=refine,
            )
            evaluations = int(len(coarse) + len(refine))
        entry = {
            "frame": int(frame),
            "framePosition": int(frame_position),
            "bone": self.node_names[node_index],
            "boneIndex": int(node_index),
            "axis": axis,
            "coarse": coarse_info,
            "refine": refine_info,
            "evaluations": evaluations,
            "passLimitDeg": float(self.config.pass_limit_deg),
            "startAngleDeg": float(current_angle),
        }
        history.append(entry)
        if progress:
            delta = float(refine_info["bestAngleDeg"]) - float(current_angle)
            moved = abs(delta) >= max(float(self.config.pass_step_deg if self.config.pass_limit_deg > 0 else self.config.refine_step_deg) * 0.5, 1e-6)
            label = f"{self.node_names[node_index]} {axis}"
            if moved or float(self.config.pass_limit_deg) <= 0.0:
                print(
                    f"depth f{frame:02d} {label} "
                    f"score={refine_info['bestScore']:.4f} "
                    f"iou={refine_info['bestSilhouetteIoU']:.4f} "
                    f"angle={refine_info['bestAngleDeg']:.1f} "
                    f"delta={delta:+.1f} "
                    f"temp={refine_info.get('bestTemporalPenalty', 0.0):.4f} "
                    f"evals={self.evaluation_count}",
                    flush=True,
                )
                self._last_heartbeat = time.perf_counter()
            else:
                self._maybe_heartbeat(frame=int(frame), label=label, progress=True)
        return state_raw, root_translation_raw, root_rotation_raw

    def _scan_branch_block(
        self,
        state_raw,
        root_translation_raw,
        root_rotation_raw,
        *,
        frame_position: int,
        frame: int,
        node_indices: Sequence[int],
        branch_index: int,
        branch_round: int,
        progress: bool,
        history: list[dict[str, Any]],
        global_sweep: bool = False,
    ):
        """Optimize a connected dependency block while preserving branch order."""
        import torch

        nodes = tuple(int(index) for index in node_indices)
        node_names = [self.node_names[index] for index in nodes]
        for axis in self.config.search_axes:
            bounded = self.backend._bounded_bone_vectors(state_raw)[0]
            axis_index = _axis_index(axis)
            centers = [
                float(torch.rad2deg(bounded[node_index, axis_index]).item())
                for node_index in nodes
            ]
            state_raw, root_translation_raw, root_rotation_raw, coarse_info = self._branch_candidate_wave(
                state_raw,
                root_translation_raw,
                root_rotation_raw,
                frame_position=frame_position,
                node_indices=nodes,
                axis=axis,
                center_angles_deg=centers,
                radius_deg=float(self.config.multi_bone_search_radius_deg),
                step_deg=float(self.config.multi_bone_search_step_deg),
                absolute=bool(global_sweep),
            )
            state_raw, root_translation_raw, root_rotation_raw, refine_info = self._branch_candidate_wave(
                state_raw,
                root_translation_raw,
                root_rotation_raw,
                frame_position=frame_position,
                node_indices=nodes,
                axis=axis,
                center_angles_deg=coarse_info["bestAnglesDeg"],
                radius_deg=float(self.config.multi_bone_refine_radius_deg),
                step_deg=float(self.config.multi_bone_refine_step_deg),
            )
            entry = {
                "frame": int(frame),
                "framePosition": int(frame_position),
                "branchIndex": int(branch_index),
                "branchRound": int(branch_round),
                "bones": node_names,
                "boneIndices": [int(index) for index in nodes],
                "axis": axis,
                "mode": "branch_multi_bone",
                "globalSweep": bool(global_sweep),
                "coarse": coarse_info,
                "refine": refine_info,
                "evaluations": int(coarse_info["candidateCount"] + refine_info["candidateCount"]),
            }
            history.append(entry)
            if progress:
                print(
                    f"depth f{frame:02d} branch {branch_index + 1}/{len(self.branch_blocks)} "
                    f"r{branch_round + 1} [{','.join(node_names)}] {axis} "
                    f"score={refine_info['bestScore']:.4f} "
                    f"iou={refine_info['bestSilhouetteIoU']:.4f} "
                    f"angles={','.join(f'{value:.1f}' for value in refine_info['bestAnglesDeg'])} "
                    f"evals={self.evaluation_count}",
                    flush=True,
                )
        return state_raw, root_translation_raw, root_rotation_raw

    def solve(
        self,
        *,
        initial_poses: Mapping[int, Mapping[str, Any]] | None = None,
        progress: bool = True,
        live_preview: bool = False,
        preview_every: int = 1,
        live_preview_path: str | Path | None = None,
        live_preview_scale: int = 4,
        live_preview_host: GpuDepthLivePreview | None = None,
    ) -> dict[str, Any]:
        """Solve frames sequentially, scanning exactly one bone axis at a time."""
        import torch

        started = time.perf_counter()
        self._solve_started = started
        self._last_heartbeat = started
        initial_bones, initial_root_translation, initial_root_rotation = self.backend._initial_pose_tensors(initial_poses)
        initial_bones = initial_bones.detach()
        initial_root_translation = initial_root_translation.detach()
        initial_root_rotation = initial_root_rotation.detach()
        solved_states: list[Any] = []
        solved_root_translations: list[Any] = []
        solved_root_rotations: list[Any] = []
        history: list[dict[str, Any]] = []
        frame_scores: list[float] = []
        frame_depth_errors: list[float] = []
        frame_depth_robust_errors: list[float] = []
        frame_ious: list[float] = []
        frame_strain_errors: list[float] = []
        frame_stop_reasons: list[str] = []
        frame_pass_counts: list[int] = []
        predicted_masks: list[np.ndarray] = []
        predicted_depths: list[np.ndarray] = []
        previous_state = None
        self._temporal_reference = None
        if live_preview_host is not None:
            self._live_preview = live_preview_host
        elif live_preview:
            if live_preview_path is None:
                raise ValueError("live_preview=True requires live_preview_path")
            self._live_preview = GpuDepthLivePreview(
                live_preview_path,
                every=int(preview_every),
                scale=int(live_preview_scale),
                alpha_threshold=float(self.config.predicted_alpha_threshold),
            )
        else:
            self._live_preview = None

        for frame_position, frame in enumerate(self.frame_indices):
            self._temporal_reference = previous_state
            self._occupancy_ignore_hw = None
            self._sprite_delta_moved_bones = set()
            self._held_bone_names = set()
            self._frame_walk_indices = self.bone_indices
            if previous_state is not None and self.config.seed_previous_frame:
                state_raw, root_translation_raw, root_rotation_raw = (
                    value.clone() for value in previous_state
                )
            else:
                state_raw = initial_bones[frame_position : frame_position + 1].clone()
                root_translation_raw = initial_root_translation[frame_position : frame_position + 1].clone()
                root_rotation_raw = initial_root_rotation[frame_position : frame_position + 1].clone()
            if progress:
                print(
                    f"depth f{frame:02d} start mode={self.config.multi_bone_mode} "
                    f"bones={len(self.bone_indices)} groups={len(self.branch_blocks)} "
                    f"axes={','.join(self.config.search_axes)} "
                    f"rootMove={bool(self.config.root_translation_enabled)} "
                    f"rootRot={bool(self.config.root_rotation_enabled)} "
                    f"passLimit={float(self.config.pass_limit_deg):.1f} "
                    f"passes={int(self.config.multi_bone_rounds)} "
                    f"packed={int(self.config.packed_axis_batch)} "
                    f"raster={int(self.config.score_raster_batch)} "
                    f"unstickFloor={float(self.config.unstick_score_floor):.2f} "
                    f"collision={float(self.config.collision_weight) if self.config.collision_enabled else 0.0:.2f} "
                    f"strain={float(self.config.strain_weight) if self.config.strain_enabled else 0.0:.2f} "
                    f"temporal={float(self.config.temporal_weight):.3f} "
                    f"rootRotWindow={root_rotation_search_window_deg(frame_position=int(frame_position), limit_deg=float(self.config.root_rotation_limit_deg), first_frame_limit_deg=float(self.config.root_rotation_first_frame_limit_deg), per_frame_limit_deg=float(self.config.root_rotation_per_frame_limit_deg)):.1f}",
                    flush=True,
                )
            self._refresh_live_preview(
                frame=int(frame),
                frame_position=frame_position,
                label=f"f{int(frame):02d} start",
                state_raw=state_raw,
                root_translation_raw=root_translation_raw,
                root_rotation_raw=root_rotation_raw,
                force=True,
            )
            if self.config.root_translation_enabled:
                for axis in self.config.root_translation_axes:
                    state_raw, root_translation_raw, root_rotation_raw = self._scan_root_axis(
                        state_raw,
                        root_translation_raw,
                        root_rotation_raw,
                        frame_position=frame_position,
                        frame=int(frame),
                        axis=axis,
                        rotation=False,
                        progress=progress,
                        history=history,
                    )
                self._refresh_live_preview(
                    frame=int(frame),
                    frame_position=frame_position,
                    label=f"f{int(frame):02d} root translation",
                    state_raw=state_raw,
                    root_translation_raw=root_translation_raw,
                    root_rotation_raw=root_rotation_raw,
                    force=True,
                )
            if self.config.root_rotation_enabled:
                initial_axes = root_rotation_axes_for_phase(
                    self.config.root_rotation_axes,
                    defer_camera_up=bool(self.config.root_rotation_defer_camera_up),
                    phase="initial",
                )
                for axis in initial_axes:
                    state_raw, root_translation_raw, root_rotation_raw = self._scan_root_axis(
                        state_raw,
                        root_translation_raw,
                        root_rotation_raw,
                        frame_position=frame_position,
                        frame=int(frame),
                        axis=axis,
                        rotation=True,
                        progress=progress,
                        history=history,
                    )
                self._refresh_live_preview(
                    frame=int(frame),
                    frame_position=frame_position,
                    label=f"f{int(frame):02d} root rotation",
                    state_raw=state_raw,
                    root_translation_raw=root_translation_raw,
                    root_rotation_raw=root_rotation_raw,
                    force=True,
                )
            state_raw, root_translation_raw, root_rotation_raw = self._sprite_delta_init_pass(
                state_raw,
                root_translation_raw,
                root_rotation_raw,
                frame_position=frame_position,
                frame=int(frame),
                progress=progress,
                history=history,
            )
            state_raw, root_translation_raw, root_rotation_raw = self._apply_occupancy_lane(
                state_raw,
                root_translation_raw,
                root_rotation_raw,
                frame_position=frame_position,
                frame=int(frame),
                progress=progress,
                history=history,
            )
            if self.config.multi_bone_mode == "branch":
                bone_pass_count = int(self.config.multi_bone_rounds)
            elif float(self.config.pass_limit_deg) > 0.0:
                bone_pass_count = int(self.config.multi_bone_rounds)
            else:
                bone_pass_count = 1
            completed_passes = 0
            stop_reason = "completed"
            allow_until = bone_pass_count
            job_quality = self._start_pass_quality(
                state_raw,
                root_translation_raw,
                root_rotation_raw,
                frame_position=frame_position,
                frame=int(frame),
                progress=progress,
            )
            if self.config.multi_bone_mode == "branch":
                search_round = 0
                while search_round < allow_until:
                    for branch_index, branch in enumerate(self.branch_blocks):
                        walk_set = set(int(index) for index in self._frame_walk_indices)
                        branch = tuple(int(index) for index in branch if int(index) in walk_set)
                        if not branch:
                            continue
                        if len(branch) < 2:
                            for node_index in branch:
                                for axis in self.config.search_axes:
                                    state_raw, root_translation_raw, root_rotation_raw = self._scan_axis(
                                        state_raw,
                                        root_translation_raw,
                                        root_rotation_raw,
                                        frame_position=frame_position,
                                        frame=int(frame),
                                        node_index=node_index,
                                        axis=axis,
                                        progress=progress,
                                        history=history,
                                    )
                                self._refresh_live_preview(
                                    frame=int(frame),
                                    frame_position=frame_position,
                                    label=(
                                        f"f{int(frame):02d} r{search_round + 1} "
                                        f"{self.node_names[node_index]}"
                                    ),
                                    state_raw=state_raw,
                                    root_translation_raw=root_translation_raw,
                                    root_rotation_raw=root_rotation_raw,
                                )
                            continue
                        state_raw, root_translation_raw, root_rotation_raw = self._scan_branch_block(
                            state_raw,
                            root_translation_raw,
                            root_rotation_raw,
                            frame_position=frame_position,
                            frame=int(frame),
                            node_indices=branch,
                            branch_index=branch_index,
                            branch_round=search_round,
                            progress=progress,
                            history=history,
                            global_sweep=(
                                bool(self.config.multi_bone_global_sweep)
                                and search_round == 0
                            ),
                        )
                        self._refresh_live_preview(
                            frame=int(frame),
                            frame_position=frame_position,
                            label=(
                                f"f{int(frame):02d} r{search_round + 1} "
                                f"branch {branch_index + 1}"
                            ),
                            state_raw=state_raw,
                            root_translation_raw=root_translation_raw,
                            root_rotation_raw=root_rotation_raw,
                        )
                    completed_passes = search_round + 1
                    state_raw, root_translation_raw, root_rotation_raw, maybe_stop, keep_going = (
                        self._evaluate_job_and_maybe_unstick(
                            job_quality,
                            state_raw,
                            root_translation_raw,
                            root_rotation_raw,
                            frame_position=frame_position,
                            frame=int(frame),
                            pass_index=completed_passes,
                            pass_count=allow_until,
                            progress=progress,
                            history=history,
                        )
                    )
                    self._refresh_live_preview(
                        frame=int(frame),
                        frame_position=frame_position,
                        label=f"f{int(frame):02d} r{completed_passes}/{allow_until} done",
                        state_raw=state_raw,
                        root_translation_raw=root_translation_raw,
                        root_rotation_raw=root_rotation_raw,
                    )
                    if keep_going:
                        if bool(job_quality.pop("grantExtra", False)):
                            allow_until = max(allow_until, completed_passes + 1)
                        search_round += 1
                        continue
                    stop_reason = str(maybe_stop or "unstick_failed")
                    break
            else:
                limited_passes = float(self.config.pass_limit_deg) > 0.0
                packed_pass = limited_passes and int(self.config.packed_axis_batch) > 0
                search_round = 0
                while search_round < allow_until:
                    if progress and allow_until > 1:
                        print(
                            f"depth f{frame:02d} pass {search_round + 1}/{allow_until} "
                            f"limit={float(self.config.pass_limit_deg):.1f}deg "
                            f"packed={int(self.config.packed_axis_batch)} "
                            f"bones={len(self.bone_indices)}",
                            flush=True,
                        )
                    if self.config.bone_order_mode == "leftover_gravity":
                        state_raw, root_translation_raw, root_rotation_raw = self._scan_leftover_gravity_pass(
                            state_raw,
                            root_translation_raw,
                            root_rotation_raw,
                            frame_position=frame_position,
                            frame=int(frame),
                            progress=progress,
                            history=history,
                        )
                    elif packed_pass:
                        state_raw, root_translation_raw, root_rotation_raw = self._scan_packed_pass(
                            state_raw,
                            root_translation_raw,
                            root_rotation_raw,
                            frame_position=frame_position,
                            frame=int(frame),
                            progress=progress,
                            history=history,
                        )
                    else:
                        for node_index in self._frame_walk_indices:
                            for axis in self.config.search_axes:
                                state_raw, root_translation_raw, root_rotation_raw = self._scan_axis(
                                    state_raw,
                                    root_translation_raw,
                                    root_rotation_raw,
                                    frame_position=frame_position,
                                    frame=int(frame),
                                    node_index=node_index,
                                    axis=axis,
                                    progress=progress,
                                    history=history,
                                )
                            self._refresh_live_preview(
                                frame=int(frame),
                                frame_position=frame_position,
                                label=(
                                    f"f{int(frame):02d} pass {search_round + 1}/{allow_until} "
                                    f"{self.node_names[node_index]}"
                                ),
                                state_raw=state_raw,
                                root_translation_raw=root_translation_raw,
                                root_rotation_raw=root_rotation_raw,
                            )
                    completed_passes = search_round + 1
                    state_raw, root_translation_raw, root_rotation_raw, maybe_stop, keep_going = (
                        self._evaluate_job_and_maybe_unstick(
                            job_quality,
                            state_raw,
                            root_translation_raw,
                            root_rotation_raw,
                            frame_position=frame_position,
                            frame=int(frame),
                            pass_index=completed_passes,
                            pass_count=allow_until,
                            progress=progress,
                            history=history,
                        )
                    )
                    self._refresh_live_preview(
                        frame=int(frame),
                        frame_position=frame_position,
                        label=f"f{int(frame):02d} pass {search_round + 1}/{allow_until} done",
                        state_raw=state_raw,
                        root_translation_raw=root_translation_raw,
                        root_rotation_raw=root_rotation_raw,
                    )
                    if keep_going:
                        if bool(job_quality.pop("grantExtra", False)):
                            allow_until = max(allow_until, completed_passes + 1)
                        search_round += 1
                        continue
                    stop_reason = str(maybe_stop or "unstick_failed")
                    break
            state_raw, root_translation_raw, root_rotation_raw = self._blob_exhaustive_pass(
                state_raw,
                root_translation_raw,
                root_rotation_raw,
                frame_position=frame_position,
                frame=int(frame),
                progress=progress,
                history=history,
            )
            if self.config.root_rotation_enabled and bool(self.config.root_rotation_defer_camera_up):
                for axis in root_rotation_axes_for_phase(
                    self.config.root_rotation_axes,
                    defer_camera_up=True,
                    phase="after_joints",
                ):
                    state_raw, root_translation_raw, root_rotation_raw = self._scan_root_axis(
                        state_raw,
                        root_translation_raw,
                        root_rotation_raw,
                        frame_position=frame_position,
                        frame=int(frame),
                        axis=axis,
                        rotation=True,
                        progress=progress,
                        history=history,
                    )
                self._refresh_live_preview(
                    frame=int(frame),
                    frame_position=frame_position,
                    label=f"f{int(frame):02d} root yaw after joints",
                    state_raw=state_raw,
                    root_translation_raw=root_translation_raw,
                    root_rotation_raw=root_rotation_raw,
                    force=True,
                )
            self._commit_occupancy_lane_unique(
                state_raw,
                root_translation_raw,
                root_rotation_raw,
                frame_position=int(frame_position),
            )
            final = self._score_batch(
                state_raw,
                frame_position,
                root_translation_raw,
                root_rotation_raw,
                semantic_force=True,
            )
            solved_states.append(state_raw[0].clone())
            solved_root_translations.append(root_translation_raw[0].clone())
            solved_root_rotations.append(root_rotation_raw[0].clone())
            previous_state = (state_raw, root_translation_raw, root_rotation_raw)
            frame_scores.append(float(final["score"][0].item()))
            frame_depth_errors.append(float(final["depthError"][0].item()))
            frame_depth_robust_errors.append(float(final["depthRobustError"][0].item()))
            frame_ious.append(float(final["silhouetteIoU"][0].item()))
            frame_strain_errors.append(float(final["strainError"][0].item()))
            frame_stop_reasons.append(str(stop_reason))
            frame_pass_counts.append(int(completed_passes))
            predicted_masks.append(final["predictedAlpha"][0].detach().cpu().numpy())
            predicted_depths.append(final["predictedDepth"][0].detach().cpu().numpy())
            if progress:
                print(
                    f"depth f{frame:02d} done score={frame_scores[-1]:.4f} "
                    f"iou={frame_ious[-1]:.4f} "
                    f"chroma={float(final['chromaQuality'][0].item()):.4f} "
                    f"depthError={frame_depth_errors[-1]:.4f} "
                    f"robustDepth={frame_depth_robust_errors[-1]:.4f} "
                    f"temp={float(final['temporalPenalty'][0].item()):.4f} "
                    f"strain={float(final['strainError'][0].item()):.4f} "
                    f"stop={stop_reason} passes={completed_passes} "
                    f"semanticEvals={self.semantic_evaluation_count} "
                    f"elapsed={time.perf_counter() - started:.1f}s",
                    flush=True,
                )
            self._refresh_live_preview(
                frame=int(frame),
                frame_position=frame_position,
                label=f"f{int(frame):02d} done iou={frame_ious[-1]:.3f}",
                state_raw=state_raw,
                root_translation_raw=root_translation_raw,
                root_rotation_raw=root_rotation_raw,
                predicted_mask=predicted_masks[-1],
                predicted_depth=predicted_depths[-1],
                force=True,
            )

        all_bones = torch.stack(solved_states, dim=0)
        all_root_translations = torch.stack(solved_root_translations, dim=0)
        all_root_rotations = torch.stack(solved_root_rotations, dim=0)
        result = {
            "poses": self.backend._pose_dicts(
                all_bones,
                all_root_translations,
                all_root_rotations,
            ),
            "history": history,
            "score": float(np.mean(frame_scores)),
            "frameScores": frame_scores,
            "frameDepthError": frame_depth_errors,
            "frameDepthRobustError": frame_depth_robust_errors,
            "frameIoU": frame_ious,
            "frameStrainError": frame_strain_errors,
            "frameStopReasons": frame_stop_reasons,
            "framePassCounts": frame_pass_counts,
            "elapsed": time.perf_counter() - started,
            "evaluationCount": int(self.evaluation_count),
            "semanticEnabled": bool(
                self.semantic_embedder is not None or self.dense_semantic_scorer is not None
            ),
            "globalSemanticEnabled": bool(self.semantic_embedder is not None),
            "denseSemanticEnabled": bool(self.dense_semantic_scorer is not None),
            "semanticEvaluationCount": int(self.semantic_evaluation_count),
            "semanticInterleaveEvery": int(self.config.semantic_interleave_every),
            "device": str(self.backend.device),
            "backend": "nvdiffrast_exact_depth_silhouette_coordinate_descent",
            "solver": (
                "branch_multi_bone_coordinate_descent"
                if self.config.multi_bone_mode == "branch"
                else (
                    "one_bone_packed_pass_coordinate_descent"
                    if float(self.config.pass_limit_deg) > 0.0
                    and int(self.config.packed_axis_batch) > 0
                    else (
                        "one_bone_limited_pass_coordinate_descent"
                        if float(self.config.pass_limit_deg) > 0.0
                        else "one_bone_at_a_time"
                    )
                )
            ),
            "seedPreviousFrame": bool(self.config.seed_previous_frame),
            "spriteDeltaInitEnabled": bool(self.config.sprite_delta_init_enabled),
            "temporalWeight": float(self.config.temporal_weight),
            "passLimitDeg": float(self.config.pass_limit_deg),
            "packedAxisBatch": int(self.config.packed_axis_batch),
            "scoreRasterBatch": int(self.config.score_raster_batch),
            "passImproveEpsilon": float(self.config.pass_improve_epsilon),
            "unstickScoreFloor": float(self.config.unstick_score_floor),
            "unstickJointCount": int(self.config.unstick_joint_count),
            "unstickLimitDeg": float(self.config.unstick_limit_deg),
            "blobExhaustiveEnabled": bool(self.config.blob_exhaustive_enabled),
            "blobExhaustiveBlockSize": int(self.config.blob_exhaustive_block_size),
            "blobExhaustiveMinBoneDepth": int(self.config.blob_exhaustive_min_bone_depth),
            "collisionEnabled": bool(self.config.collision_enabled),
            "collisionWeight": float(self.config.collision_weight),
            "collisionPositiveAbsSlack": float(self.config.collision_positive_abs_slack),
            "strainEnabled": bool(self.config.strain_enabled),
            "strainWeight": float(self.config.strain_weight),
            "strainTolerance": float(self.config.strain_tolerance),
            "strainAcceptSlack": float(self.config.strain_accept_slack),
            "occupancyIgnoreAmbiguous": bool(self.config.occupancy_ignore_ambiguous),
            "blobIdentityPersist": bool(self.config.blob_identity_persist),
            "uniqueVanishHold": bool(self.config.unique_vanish_hold),
            "boneOrderMode": str(self.config.bone_order_mode),
            "collision": None if self._collision_table is None else dict(self._collision_table["report"]),
            "strain": None if self._strain_table is None else dict(self._strain_table["report"]),
            "rootTranslationEnabled": bool(self.config.root_translation_enabled),
            "rootRotationEnabled": bool(self.config.root_rotation_enabled),
            "bones": list(self.bone_names),
            "branchGroups": [
                [self.node_names[index] for index in branch]
                for branch in self.branch_blocks
            ],
            "targetPaths": [str(path) for path in self.backend.target_paths],
            "targetDepthPaths": [str(path) for path in self.backend.target_depth_paths],
            "config": asdict(self.config),
            "rootPivot": [float(value) for value in self.backend.root_pivot.detach().cpu().tolist()],
            "targetMasks": self.backend.target_masks.detach().cpu().numpy(),
            "predictedMasks": np.stack(predicted_masks),
            "targetDepth": self.backend.target_depth.detach().cpu().numpy(),
            "predictedDepth": np.stack(predicted_depths),
        }
        return result


def render_chroma_occupancy_preview(
    pose_result: Mapping[str, Any],
    *,
    output_dir: str | Path,
    frame_indices: Sequence[int],
    duration_ms: int = 83,
    scale: int = 1,
) -> Path:
    """Write sprite RGB | unlit mesh RGB | occupancy overlay as a GIF."""
    target_rgb = np.asarray(pose_result.get("targetRgb"), dtype=np.float32)
    predicted_rgb = np.asarray(pose_result.get("predictedRgb"), dtype=np.float32)
    target_masks = np.asarray(pose_result.get("targetMasks"), dtype=np.float32)
    predicted_masks = np.asarray(pose_result.get("predictedMasks"), dtype=np.float32)
    if target_rgb.ndim != 4 or target_rgb.shape[-1] != 3:
        raise ValueError("GPU color preview requires targetRgb shaped [frame,height,width,3]")
    if predicted_rgb.shape != target_rgb.shape:
        raise ValueError("GPU color preview predictedRgb must match targetRgb")
    if target_masks.ndim != 3 or predicted_masks.shape != target_masks.shape:
        raise ValueError("GPU color preview requires matching target/predicted mask arrays")
    frame_indices = tuple(int(frame) for frame in frame_indices)
    if len(frame_indices) != target_rgb.shape[0]:
        raise ValueError("GPU color preview frame count does not match RGB arrays")
    if target_masks.shape[0] != target_rgb.shape[0] or target_masks.shape[1:] != target_rgb.shape[1:3]:
        raise ValueError("GPU color preview masks must match the RGB raster size")
    if int(scale) < 1:
        raise ValueError("GPU color preview scale must be positive")
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    threshold = float((pose_result.get("config") or {}).get("predicted_alpha_threshold", 0.01))
    frames: list[Image.Image] = []
    for position, frame in enumerate(frame_indices):
        canvas = compose_chroma_occupancy_panel(
            target_rgb[position],
            predicted_rgb[position],
            target_masks[position],
            predicted_masks[position],
            frame=int(frame),
            label=f"target chroma f{int(frame):02d}",
            scale=int(scale),
            predicted_alpha_threshold=threshold,
        )
        frame_path = output / f"preview_{frame:02d}.png"
        canvas.save(frame_path)
        frames.append(canvas)
    gif_path = output / "gpu_unlit_rgb_preview.gif"
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=int(duration_ms),
        loop=0,
        optimize=False,
    )
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "renderer": "nvdiffrast RasterizeCudaContext",
                "preview": "target RGB | GPU unlit mesh RGB | target/candidate silhouette overlay",
                "color": "unlit_base_color_texture_neutral_matte",
                "frame_indices": list(frame_indices),
                "overlay_colors": {"target_only": "red", "candidate_only": "blue", "shared": "green"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return gif_path


def render_depth_silhouette_preview(
    pose_result: Mapping[str, Any],
    *,
    output_dir: str | Path,
    frame_indices: Sequence[int],
    duration_ms: int = 83,
    scale: int = 4,
) -> Path:
    """Write a raster-only target/candidate/overlay convergence GIF.

    This deliberately shows depth and silhouette diagnostics rather than
    pretending that an untextured raster is a lit mesh render.  The overlay
    uses red for target-only pixels, blue for candidate-only pixels, and green
    for shared silhouette pixels.
    """
    target_depth = np.asarray(pose_result.get("targetDepth"), dtype=np.float32)
    predicted_depth = np.asarray(pose_result.get("predictedDepth"), dtype=np.float32)
    target_masks = np.asarray(pose_result.get("targetMasks"), dtype=np.float32)
    predicted_masks = np.asarray(pose_result.get("predictedMasks"), dtype=np.float32)
    arrays = (target_depth, predicted_depth, target_masks, predicted_masks)
    if any(array.ndim != 3 for array in arrays):
        raise ValueError("GPU preview requires target/predicted depth and mask arrays shaped [frame,height,width]")
    frame_indices = tuple(int(frame) for frame in frame_indices)
    if len(frame_indices) != target_depth.shape[0]:
        raise ValueError("GPU preview frame count does not match result arrays")
    if any(array.shape != target_depth.shape for array in arrays):
        raise ValueError("GPU preview target/candidate depth and mask shapes must match")
    if int(scale) < 1:
        raise ValueError("GPU preview scale must be positive")
    output = Path(output_dir).resolve()
    # This directory is disposable convergence output.  Reusing it is
    # intentional so the notebook can be rerun without manual cleanup.
    output.mkdir(parents=True, exist_ok=True)
    threshold = float((pose_result.get("config") or {}).get("predicted_alpha_threshold", 0.01))
    frames: list[Image.Image] = []
    for position, frame in enumerate(frame_indices):
        canvas = compose_depth_silhouette_panel(
            target_depth[position],
            predicted_depth[position],
            target_masks[position],
            predicted_masks[position],
            frame=int(frame),
            label=f"target depth f{int(frame):02d}",
            scale=int(scale),
            predicted_alpha_threshold=threshold,
        )
        frame_path = output / f"preview_{frame:02d}.png"
        canvas.save(frame_path)
        frames.append(canvas)
    gif_path = output / "gpu_depth_silhouette_preview.gif"
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=int(duration_ms),
        loop=0,
        optimize=False,
    )
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "renderer": "nvdiffrast RasterizeCudaContext",
                "preview": "target depth | GPU candidate depth | target/candidate silhouette overlay",
                "frame_indices": list(frame_indices),
                "depth_convention": "near_bright",
                "overlay_colors": {"target_only": "red", "candidate_only": "blue", "shared": "green"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return gif_path


def _discover_idle_profile_target_dir(config: Any, pilot: Path, target_dir: Path) -> Path:
    """Require an authentic idle silhouette for camera yaw.

    Idle-leading DEF sequences put idle in frame 00 of the selected folder.
    Motion-only authentic DEF clips look in the sibling ``idle`` folder's
    ``frames_def12_nn_idle_shadow_culled`` plates, then materialize lab group 2
    there if needed. They must not reuse the current clip's folder name under
    idle/ (that searched ``idle/frames_def12_nn_attack_front_shadow_culled``).
    Searching only the current clip, then quietly using a walk frame, would
    register yaw from a stride pose instead of the bind pose.
    """
    groups = getattr(config, "def_lab_group", None)
    if isinstance(groups, (str, bytes)):
        groups = None
    elif isinstance(groups, Sequence) and groups:
        groups = tuple(int(value) for value in groups)
    elif groups is not None:
        groups = (int(groups),)
    if groups and int(groups[0]) == 2:
        resolved = Path(target_dir)
        if not resolved.is_absolute():
            resolved = (Path(pilot) / resolved).resolve()
        if resolved.is_dir() and (resolved / "00.png").is_file():
            return resolved

    identifiers: list[str] = []
    for value in (
        getattr(config, "unit_sid", None),
        getattr(config, "unit_name", None),
    ):
        if not value:
            continue
        text = str(value).strip()
        if text and text not in identifiers:
            identifiers.append(text)
        prefixed = text if text.startswith("h3_") else f"h3_{text}"
        if prefixed not in identifiers:
            identifiers.append(prefixed)

    candidates: list[Path] = []
    seen: set[Path] = set()

    def _add(path: Path) -> None:
        resolved = path if path.is_absolute() else path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        candidates.append(resolved)

    for animation in ("idle", "idle_g2", "g02_idle"):
        for dir_name in (
            "frames_def12_nn_idle_shadow_culled",
            "frames_def12_nn_idle",
            "frames_ground_truth_shadow_culled",
            "frames_rife60_nn_shadow_culled",
        ):
            _add(Path(pilot).parent / animation / dir_name)
            for identifier in identifiers:
                _add(
                    Path(config.root).resolve()
                    / "artifacts"
                    / "pose_picker_runs"
                    / identifier
                    / animation
                    / dir_name
                )

    for candidate in candidates:
        if candidate.is_dir() and (candidate / "00.png").is_file():
            return candidate.resolve()

    lab = getattr(config, "def_lab_frame_dir", None)
    meta = getattr(config, "def_nn_upscale_meta", None)
    if lab is not None and meta is not None:
        from materialize_rife_source_frames import ensure_authentic_def_idle_profile_dir

        idle_pilot = Path(pilot).parent / "idle"
        prepared = ensure_authentic_def_idle_profile_dir(
            idle_pilot=idle_pilot,
            lab_dir=Path(lab),
            nn_upscale_meta=Path(meta),
            target_fps=float(getattr(config, "depth_video_fps", 12.0) or 12.0),
        )
        print(f"profile idle plates: {prepared}")
        return prepared

    looked = ", ".join(str(path) for path in candidates[:12])
    raise FileNotFoundError(
        "profile initialization needs an idle bind silhouette for camera yaw; "
        f"looked in: {looked}. Pass profile_init_target_dir explicitly if idle lives elsewhere."
    )


def _resolve_profile_init_resolution(
    target_dir: Path,
    frame_index: int,
    requested: tuple[int, int] | None,
    max_dimension: int,
    fallback: tuple[int, int],
) -> tuple[int, int]:
    """Choose an aspect-preserving registration resolution.

    The solver intentionally runs at a small proxy resolution.  Reusing that
    resolution for camera registration can reduce a standing unit to only a
    handful of pixels, making a one-pixel change look like a different yaw.
    When no explicit size is supplied, use the source idle frame's aspect ratio
    and downscale it only to the configured maximum dimension.
    """
    if requested is not None:
        width, height = (int(value) for value in requested)
        if width < 16 or height < 16:
            raise ValueError("profile_init_resolution must be at least 16x16")
        return width, height
    if int(max_dimension) < 16:
        raise ValueError("profile_init_max_dimension must be at least 16")
    source_path = target_dir / f"{int(frame_index):02d}.png"
    if source_path.is_file():
        with Image.open(source_path) as image:
            source_width, source_height = (int(value) for value in image.size)
        scale = min(1.0, float(max_dimension) / max(source_width, source_height, 1))
        return (
            max(16, int(round(source_width * scale))),
            max(16, int(round(source_height * scale))),
        )
    return tuple(int(value) for value in fallback)


def run_simple_depth_silhouette_from_hybrid_config(
    config: Any,
    *,
    output_dir: str | Path | None = None,
    resolution: tuple[int, int] | None = None,
    joint_limit_deg: float = 150.0,
    coarse_step_deg: float = 15.0,
    refine_step_deg: float = 2.5,
    refine_radius_deg: float = 20.0,
    search_axes: Sequence[str] = ("x", "y", "z"),
    bone_order_mode: str = "dependency",
    bone_order: Sequence[str] = (),
    leftover_gravity_max_assign_px: float = 24.0,
    leftover_gravity_sigma_px: float = 8.0,
    leftover_gravity_extra_weight: float = 0.25,
    leftover_gravity_min_pull: float = 1.0,
    leftover_gravity_depth_gate: float = 0.20,
    multi_bone_mode: str = "single",
    multi_bone_block_size: int = 2,
    multi_bone_rounds: int = 2,
    multi_bone_global_sweep: bool = True,
    multi_bone_search_radius_deg: float = 150.0,
    multi_bone_search_step_deg: float = 15.0,
    multi_bone_refine_radius_deg: float = 20.0,
    multi_bone_refine_step_deg: float = 2.5,
    multi_bone_max_candidates: int = 1024,
    score_raster_batch: int = 128,
    pass_limit_deg: float = 0.0,
    pass_step_deg: float = 2.5,
    packed_axis_batch: int = 128,
    pass_improve_epsilon: float = 0.005,
    unstick_score_floor: float = 0.9,
    unstick_joint_count: int = 0,
    unstick_limit_deg: float = 60.0,
    unstick_samples_per_bone: int = 3,
    unstick_max_candidates: int = 512,
    unstick_max_attempts: int = 3,
    blob_exhaustive_enabled: bool = True,
    blob_exhaustive_max_pairs: int = 2,
    blob_exhaustive_min_component_area: int = 12,
    blob_exhaustive_min_bone_depth: int = 3,
    blob_exhaustive_max_chain_depth: int = 3,
    blob_exhaustive_block_size: int = 2,
    blob_exhaustive_dilate_px: int = 4,
    blob_exhaustive_max_tip_distance_px: float = 96.0,
    blob_exhaustive_max_centroid_distance_px: float = 96.0,
    blob_exhaustive_max_area_ratio: float = 4.0,
    blob_exhaustive_min_displacement_alignment: float = 0.15,
    blob_exhaustive_depth_tolerance: float = 0.12,
    blob_exhaustive_predicted_alpha_threshold: float = 0.5,
    sprite_delta_init_enabled: bool = True,
    sprite_delta_init_max_pairs: int = 2,
    sprite_delta_init_min_component_area: int = 12,
    sprite_delta_init_min_bone_depth: int = 3,
    sprite_delta_init_min_angle_deg: float = 8.0,
    sprite_delta_init_min_radius_px: float = 4.0,
    sprite_delta_init_max_tip_distance_px: float = 128.0,
    sprite_delta_init_max_centroid_distance_px: float = 128.0,
    sprite_delta_init_max_area_ratio: float = 4.0,
    sprite_delta_init_min_displacement_alignment: float = 0.15,
    sprite_delta_init_depth_tolerance: float = 0.12,
    sprite_delta_init_dilate_px: int = 4,
    temporal_weight: float = 0.0,
    temporal_scale_deg: float = 20.0,
    temporal_root_scale_body_lengths: float = 0.15,
    collision_enabled: bool = True,
    collision_sample_count: int = 256,
    collision_geodesic_min_hops: int = 8,
    collision_margin_body_lengths: float = 0.04,
    collision_weight: float = 0.35,
    collision_positive_abs_slack: float = 0.12,
    strain_enabled: bool = True,
    strain_weight: float = 0.80,
    strain_tolerance: float = 0.08,
    strain_exclusive_weight: float = 0.99,
    strain_accept_slack: float = 0.04,
    strain_min_rest_length_body_lengths: float = 1e-4,
    occupancy_ignore_ambiguous: bool = True,
    occupancy_ambiguous_ratio: float = 0.4,
    occupancy_ambiguous_min_weight: float = 1.0,
    blob_identity_persist: bool = True,
    blob_identity_min_overlap: int = 4,
    unique_vanish_hold: bool = True,
    unique_vanish_frac: float = 0.25,
    unique_vanish_min_area: int = 12,
    unique_vanish_min_bone_depth: int = 3,
    root_translation_enabled: bool = True,
    root_translation_axes: Sequence[str] = ("forward", "lateral", "vertical"),
    root_translation_limit_body_lengths: float = 0.75,
    root_translation_coarse_step_body_lengths: float = 0.10,
    root_translation_refine_radius_body_lengths: float = 0.10,
    root_translation_refine_step_body_lengths: float = 0.025,
    root_rotation_enabled: bool = True,
    root_rotation_axes: Sequence[str] = (
        "camera_forward",
        "camera_right",
        "camera_up",
    ),
    root_rotation_limit_deg: float = 180.0,
    root_rotation_first_frame_limit_deg: float = 30.0,
    root_rotation_per_frame_limit_deg: float = 30.0,
    root_rotation_camera_up_limit_deg: float = 45.0,
    root_rotation_defer_camera_up: bool = True,
    root_rotation_coarse_step_deg: float = 30.0,
    root_rotation_refine_radius_deg: float = 20.0,
    root_rotation_refine_step_deg: float = 2.5,
    depth_weight: float = 0.65,
    silhouette_weight: float = 0.35,
    depth_tolerance: float = 0.08,
    depth_robust_delta: float = 0.12,
    chroma_weight: float = 0.0,
    chroma_tolerance: float = 0.10,
    chroma_robust_delta: float = 0.12,
    chroma_error_scale: float = 80.0,
    chroma_scale: int = 4,
    chroma_resolution: tuple[int, int] | None = None,
    seed_previous_frame: bool = True,
    predicted_alpha_threshold: float = 0.01,
    semantic_enabled: bool = False,
    semantic_model_id: str = "google/siglip2-base-patch16-512",
    semantic_embedding_layer: str = "projected",
    semantic_embedding_layers: Sequence[str] = ("projected",),
    semantic_pooling: str = "mean",
    semantic_subject_crop: bool = True,
    semantic_subject_padding_frac: float = 0.18,
    semantic_weight: float = 0.15,
    semantic_candidate_top_k: int = 4,
    semantic_batch_size: int = 8,
    semantic_interleave_every: int = 4,
    semantic_eval_budget: int = 512,
    dense_semantic_enabled: bool = False,
    dense_semantic_model_id: str = "google/siglip2-base-patch16-512",
    dense_semantic_feature_layers: Sequence[str] = ("last",),
    dense_semantic_local_radius: int = 1,
    dense_semantic_position_weight: float = 0.15,
    dense_semantic_weight: float = 0.10,
    profile_init_enabled: bool = True,
    profile_init_frame: int | None = None,
    profile_init_target_dir: str | Path | None = None,
    profile_init_fit_target_dir: str | Path | None = None,
    profile_init_yaw_min_deg: float = -180.0,
    profile_init_yaw_max_deg: float = 180.0,
    profile_init_yaw_step_deg: float = 15.0,
    profile_init_roll_range_deg: float = 8.0,
    profile_init_roll_step_deg: float = 8.0,
    profile_init_facing_weight: float | None = None,
    profile_init_rank_metric: str | None = None,
    profile_init_fit_margin: float = 0.96,
    profile_init_top_k: int = 8,
    profile_init_camera_basis_mode: str = "upright_turntable",
    profile_init_world_up_axis: Sequence[float] = (0.0, 1.0, 0.0),
    profile_init_resolution: tuple[int, int] | None = None,
    profile_init_max_dimension: int = 256,
    progress: bool = True,
    live_preview: bool | None = None,
    preview_every: int | None = None,
    live_preview_scale: int = 4,
) -> AnimationSolveResult:
    """Adapter for the original notebook's asset selector/config contract."""
    from roc_semantic_hybrid_experiment import prepare_gpu_fit_config

    config = prepare_gpu_fit_config(config)
    root = Path(config.root).resolve()
    pilot = Path(config.pilot_dir or (root / "artifacts/roc_pose_pipeline/smart_rig_move_pilot")).resolve()
    target_dir = Path(config.shadow_culled_frame_dir)
    target_dir = target_dir if target_dir.is_absolute() else (pilot / target_dir).resolve()
    depth_dir = Path(config.target_depth_dir)
    depth_dir = depth_dir if depth_dir.is_absolute() else (pilot / depth_dir).resolve()
    camera_fit = Path(config.camera_fit_path or (pilot / "roc_sprite_camera_fit.json"))
    camera_fit = camera_fit if camera_fit.is_absolute() else (pilot / camera_fit)
    camera_fit = camera_fit.resolve()
    if not target_dir.is_dir():
        raise FileNotFoundError(f"simple depth solver requires alpha-shadow-culled frames: {target_dir}")
    if not depth_dir.is_dir():
        raise FileNotFoundError(f"simple depth solver requires Video Depth Anything frames: {depth_dir}")
    from run_vda_movement_depth import assert_vda_pipeline_cache

    assert_vda_pipeline_cache(depth_dir)
    if not camera_fit.is_file():
        raise FileNotFoundError(f"simple depth solver camera fit is missing: {camera_fit}")
    assert_solver_camera_is_registered_profile(
        camera_fit,
        profile_init_enabled=bool(profile_init_enabled),
        world_up_axis=tuple(float(value) for value in profile_init_world_up_axis),
    )
    frame_indices = tuple(int(frame) for frame in config.frame_indices)
    if not frame_indices:
        raise ValueError("simple depth solver requires explicit frame_indices")
    output = replace_owned_run_artifacts(Path(output_dir or (pilot / "gpu_depth_silhouette_simple")))
    preview_dir = output / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    use_live_preview = bool(getattr(config, "live_preview", False)) if live_preview is None else bool(live_preview)
    use_preview_every = int(getattr(config, "preview_every", 1)) if preview_every is None else int(preview_every)
    live_preview_host = None
    if use_live_preview:
        live_preview_host = GpuDepthLivePreview(
            preview_dir / "live_preview.png",
            every=use_preview_every,
            scale=int(live_preview_scale),
            alpha_threshold=float(predicted_alpha_threshold),
        )
        proxy = tuple(int(value) for value in (resolution or getattr(config, "proxy_resolution", (96, 86))))
        width, height = int(proxy[0]), int(proxy[1])
        waiting = np.zeros((height, width), dtype=np.float32)
        live_preview_host.show(
            frame=int(frame_indices[0]),
            label="waiting for camera / solver init",
            target_depth=waiting,
            predicted_depth=waiting,
            target_mask=waiting,
            predicted_mask=waiting,
            force=True,
        )
        if progress:
            print(
                f"live preview: {GpuDepthLivePreview.display_id} "
                f"every={use_preview_every} path={preview_dir / 'live_preview.png'}",
                flush=True,
            )
    initialization = None
    if bool(profile_init_enabled):
        explicit_init_target = profile_init_target_dir is not None
        init_target_dir = target_dir if not explicit_init_target else Path(profile_init_target_dir)
        if not init_target_dir.is_absolute():
            init_target_dir = (pilot / init_target_dir).resolve()
        if not explicit_init_target:
            init_target_dir = _discover_idle_profile_target_dir(config, pilot, target_dir)
        fit_target_dir = target_dir
        if profile_init_fit_target_dir is not None:
            fit_target_dir = Path(profile_init_fit_target_dir)
            if not fit_target_dir.is_absolute():
                fit_target_dir = (pilot / fit_target_dir).resolve()
        init_frame = int(
            0 if profile_init_frame is None and init_target_dir != target_dir else
            frame_indices[0] if profile_init_frame is None else profile_init_frame
        )
        profile_resolution = _resolve_profile_init_resolution(
            init_target_dir,
            init_frame,
            profile_init_resolution,
            int(profile_init_max_dimension),
            tuple(int(value) for value in (resolution or getattr(config, "proxy_resolution", (96, 86)))),
        )
        initialization = initialize_profile_camera(
            src_glb=Path(config.src_glb).resolve(),
            seed_camera_fit=camera_fit,
            target_frame_dir=init_target_dir,
            fit_target_frame_dir=fit_target_dir,
            frame_index=init_frame,
            output_dir=output / "initialization",
            config=ProfileCameraInitConfig(
                resolution=profile_resolution,
                alpha_threshold=int(getattr(config, "proxy_target_alpha_threshold", 8)),
                predicted_alpha_threshold=float(predicted_alpha_threshold),
                yaw_min_deg=float(profile_init_yaw_min_deg),
                yaw_max_deg=float(profile_init_yaw_max_deg),
                yaw_step_deg=float(profile_init_yaw_step_deg),
                roll_range_deg=float(profile_init_roll_range_deg),
                roll_step_deg=float(profile_init_roll_step_deg),
                fit_margin=float(profile_init_fit_margin),
                top_k=int(profile_init_top_k),
                camera_basis_mode=str(profile_init_camera_basis_mode),
                world_up_axis=tuple(float(value) for value in profile_init_world_up_axis),
                facing_weight=(
                    float(PROFILE_FACING_WEIGHT)
                    if profile_init_facing_weight is None
                    else float(profile_init_facing_weight)
                ),
                rank_metric=(
                    "composite"
                    if profile_init_rank_metric is None
                    else str(profile_init_rank_metric)
                ),
            ),
            progress=progress,
        )
        camera_fit = initialization.camera_fit_path
    solver_config = DepthSilhouetteConfig(
        resolution=tuple(int(value) for value in (resolution or getattr(config, "proxy_resolution", (96, 86)))),
        alpha_threshold=int(getattr(config, "proxy_target_alpha_threshold", 8)),
        joint_limit_deg=float(joint_limit_deg),
        coarse_step_deg=float(coarse_step_deg),
        refine_step_deg=float(refine_step_deg),
        refine_radius_deg=float(refine_radius_deg),
        search_axes=tuple(str(axis) for axis in search_axes),
        bone_order_mode=str(bone_order_mode),
        bone_order=tuple(str(name) for name in bone_order),
        leftover_gravity_max_assign_px=float(leftover_gravity_max_assign_px),
        leftover_gravity_sigma_px=float(leftover_gravity_sigma_px),
        leftover_gravity_extra_weight=float(leftover_gravity_extra_weight),
        leftover_gravity_min_pull=float(leftover_gravity_min_pull),
        leftover_gravity_depth_gate=float(leftover_gravity_depth_gate),
        multi_bone_mode=str(multi_bone_mode),
        multi_bone_block_size=int(multi_bone_block_size),
        multi_bone_rounds=int(multi_bone_rounds),
        multi_bone_global_sweep=bool(multi_bone_global_sweep),
        multi_bone_search_radius_deg=float(multi_bone_search_radius_deg),
        multi_bone_search_step_deg=float(multi_bone_search_step_deg),
        multi_bone_refine_radius_deg=float(multi_bone_refine_radius_deg),
        multi_bone_refine_step_deg=float(multi_bone_refine_step_deg),
        multi_bone_max_candidates=int(multi_bone_max_candidates),
        score_raster_batch=int(score_raster_batch),
        pass_limit_deg=float(pass_limit_deg),
        pass_step_deg=float(pass_step_deg),
        packed_axis_batch=int(packed_axis_batch),
        pass_improve_epsilon=float(pass_improve_epsilon),
        unstick_score_floor=float(unstick_score_floor),
        unstick_joint_count=int(unstick_joint_count),
        unstick_limit_deg=float(unstick_limit_deg),
        unstick_samples_per_bone=int(unstick_samples_per_bone),
        unstick_max_candidates=int(unstick_max_candidates),
        unstick_max_attempts=int(unstick_max_attempts),
        blob_exhaustive_enabled=bool(blob_exhaustive_enabled),
        blob_exhaustive_max_pairs=int(blob_exhaustive_max_pairs),
        blob_exhaustive_min_component_area=int(blob_exhaustive_min_component_area),
        blob_exhaustive_min_bone_depth=int(blob_exhaustive_min_bone_depth),
        blob_exhaustive_max_chain_depth=int(blob_exhaustive_max_chain_depth),
        blob_exhaustive_block_size=int(blob_exhaustive_block_size),
        blob_exhaustive_dilate_px=int(blob_exhaustive_dilate_px),
        blob_exhaustive_max_tip_distance_px=float(blob_exhaustive_max_tip_distance_px),
        blob_exhaustive_max_centroid_distance_px=float(blob_exhaustive_max_centroid_distance_px),
        blob_exhaustive_max_area_ratio=float(blob_exhaustive_max_area_ratio),
        blob_exhaustive_min_displacement_alignment=float(blob_exhaustive_min_displacement_alignment),
        blob_exhaustive_depth_tolerance=float(blob_exhaustive_depth_tolerance),
        blob_exhaustive_predicted_alpha_threshold=float(blob_exhaustive_predicted_alpha_threshold),
        sprite_delta_init_enabled=bool(sprite_delta_init_enabled),
        sprite_delta_init_max_pairs=int(sprite_delta_init_max_pairs),
        sprite_delta_init_min_component_area=int(sprite_delta_init_min_component_area),
        sprite_delta_init_min_bone_depth=int(sprite_delta_init_min_bone_depth),
        sprite_delta_init_min_angle_deg=float(sprite_delta_init_min_angle_deg),
        sprite_delta_init_min_radius_px=float(sprite_delta_init_min_radius_px),
        sprite_delta_init_max_tip_distance_px=float(sprite_delta_init_max_tip_distance_px),
        sprite_delta_init_max_centroid_distance_px=float(sprite_delta_init_max_centroid_distance_px),
        sprite_delta_init_max_area_ratio=float(sprite_delta_init_max_area_ratio),
        sprite_delta_init_min_displacement_alignment=float(sprite_delta_init_min_displacement_alignment),
        sprite_delta_init_depth_tolerance=float(sprite_delta_init_depth_tolerance),
        sprite_delta_init_dilate_px=int(sprite_delta_init_dilate_px),
        temporal_weight=float(temporal_weight),
        temporal_scale_deg=float(temporal_scale_deg),
        temporal_root_scale_body_lengths=float(temporal_root_scale_body_lengths),
        collision_enabled=bool(collision_enabled),
        collision_sample_count=int(collision_sample_count),
        collision_geodesic_min_hops=int(collision_geodesic_min_hops),
        collision_margin_body_lengths=float(collision_margin_body_lengths),
        collision_weight=float(collision_weight),
        collision_positive_abs_slack=float(collision_positive_abs_slack),
        strain_enabled=bool(strain_enabled),
        strain_weight=float(strain_weight),
        strain_tolerance=float(strain_tolerance),
        strain_exclusive_weight=float(strain_exclusive_weight),
        strain_accept_slack=float(strain_accept_slack),
        strain_min_rest_length_body_lengths=float(strain_min_rest_length_body_lengths),
        occupancy_ignore_ambiguous=bool(occupancy_ignore_ambiguous),
        occupancy_ambiguous_ratio=float(occupancy_ambiguous_ratio),
        occupancy_ambiguous_min_weight=float(occupancy_ambiguous_min_weight),
        blob_identity_persist=bool(blob_identity_persist),
        blob_identity_min_overlap=int(blob_identity_min_overlap),
        unique_vanish_hold=bool(unique_vanish_hold),
        unique_vanish_frac=float(unique_vanish_frac),
        unique_vanish_min_area=int(unique_vanish_min_area),
        unique_vanish_min_bone_depth=int(unique_vanish_min_bone_depth),
        root_translation_enabled=bool(root_translation_enabled),
        root_translation_axes=tuple(str(axis) for axis in root_translation_axes),
        root_translation_limit_body_lengths=float(root_translation_limit_body_lengths),
        root_translation_coarse_step_body_lengths=float(root_translation_coarse_step_body_lengths),
        root_translation_refine_radius_body_lengths=float(root_translation_refine_radius_body_lengths),
        root_translation_refine_step_body_lengths=float(root_translation_refine_step_body_lengths),
        root_rotation_enabled=bool(root_rotation_enabled),
        root_rotation_axes=tuple(str(axis) for axis in root_rotation_axes),
        root_rotation_limit_deg=float(root_rotation_limit_deg),
        root_rotation_first_frame_limit_deg=float(root_rotation_first_frame_limit_deg),
        root_rotation_per_frame_limit_deg=float(root_rotation_per_frame_limit_deg),
        root_rotation_camera_up_limit_deg=float(root_rotation_camera_up_limit_deg),
        root_rotation_defer_camera_up=bool(root_rotation_defer_camera_up),
        root_rotation_coarse_step_deg=float(root_rotation_coarse_step_deg),
        root_rotation_refine_radius_deg=float(root_rotation_refine_radius_deg),
        root_rotation_refine_step_deg=float(root_rotation_refine_step_deg),
        depth_weight=float(depth_weight),
        silhouette_weight=float(silhouette_weight),
        depth_tolerance=float(depth_tolerance),
        depth_robust_delta=float(depth_robust_delta),
        chroma_weight=float(chroma_weight),
        chroma_tolerance=float(chroma_tolerance),
        chroma_robust_delta=float(chroma_robust_delta),
        chroma_error_scale=float(chroma_error_scale),
        chroma_scale=int(chroma_scale),
        chroma_resolution=(
            None
            if chroma_resolution is None
            else (int(chroma_resolution[0]), int(chroma_resolution[1]))
        ),
        seed_previous_frame=bool(seed_previous_frame),
        predicted_alpha_threshold=float(predicted_alpha_threshold),
        semantic_enabled=bool(semantic_enabled),
        semantic_model_id=str(semantic_model_id),
        semantic_embedding_layer=str(semantic_embedding_layer),
        semantic_embedding_layers=tuple(str(layer) for layer in semantic_embedding_layers),
        semantic_pooling=str(semantic_pooling),
        semantic_subject_crop=bool(semantic_subject_crop),
        semantic_subject_padding_frac=float(semantic_subject_padding_frac),
        semantic_weight=float(semantic_weight),
        semantic_candidate_top_k=int(semantic_candidate_top_k),
        semantic_batch_size=int(semantic_batch_size),
        semantic_interleave_every=int(semantic_interleave_every),
        semantic_eval_budget=int(semantic_eval_budget),
        dense_semantic_enabled=bool(dense_semantic_enabled),
        dense_semantic_model_id=str(dense_semantic_model_id),
        dense_semantic_feature_layers=tuple(str(layer) for layer in dense_semantic_feature_layers),
        dense_semantic_local_radius=int(dense_semantic_local_radius),
        dense_semantic_position_weight=float(dense_semantic_position_weight),
        dense_semantic_weight=float(dense_semantic_weight),
    )
    solver = DepthSilhouetteSolver(
        src_glb=Path(config.src_glb).resolve(),
        camera_fit=camera_fit,
        target_frame_dir=target_dir,
        target_depth_dir=depth_dir,
        frame_indices=frame_indices,
        config=solver_config,
    )
    pose_result = solver.solve(
        progress=progress,
        live_preview_host=live_preview_host,
    )
    source_dir = Path(config.target_frame_dir)
    source_dir = source_dir if source_dir.is_absolute() else (pilot / source_dir).resolve()
    rife_manifest_path = source_dir / "rife_frames.json"
    if rife_manifest_path.is_file():
        rife_manifest = json.loads(rife_manifest_path.read_text(encoding="utf-8"))
        if rife_manifest.get("sourceKind") == "lab_rife_nn_upscale_sequence":
            clips = rife_manifest.get("clips")
            if not clips:
                raise ValueError(f"RIFE sequence manifest is missing clips: {rife_manifest_path}")
            pose_result["rifeClips"] = clips
            pose_result["rifeSourceKind"] = rife_manifest["sourceKind"]
    def_manifest_path = source_dir / "def_frames.json"
    if def_manifest_path.is_file():
        def_manifest = json.loads(def_manifest_path.read_text(encoding="utf-8"))
        if def_manifest.get("sourceKind") == "authentic_def_nn_upscale_sequence":
            clips = def_manifest.get("clips")
            if not clips:
                raise ValueError(f"DEF sequence manifest is missing clips: {def_manifest_path}")
            pose_result["defClips"] = clips
            pose_result["defSourceKind"] = def_manifest["sourceKind"]
        else:
            raise ValueError(
                f"DEF sequence manifest has unexpected sourceKind {def_manifest.get('sourceKind')!r}: "
                f"{def_manifest_path}"
            )
    depth_output, depth_gif = render_pose_depth_animation(
        solver.backend,
        pose_result,
        output_dir=output / "solved_depth",
        frame_indices=frame_indices,
    )
    preview_gif = render_depth_silhouette_preview(
        pose_result,
        output_dir=output / "preview",
        frame_indices=frame_indices,
        scale=int(live_preview_scale),
    )
    pose_result["depthGif"] = str(depth_gif)
    pose_result["previewGif"] = str(preview_gif)
    pose_result["depthDir"] = str(depth_output)
    pose_result["outputDir"] = str(output)
    pose_result["cameraFitPath"] = str(camera_fit)
    pose_result["seedCameraFitPath"] = str(Path(config.camera_fit_path or (pilot / "roc_sprite_camera_fit.json")).resolve())
    pose_result["initialization"] = initialization.to_dict() if initialization is not None else None
    rgb_output = None
    rgb_gif = None
    if (
        (bool(solver_config.semantic_enabled) and float(solver_config.semantic_weight) > 0.0)
        or (
            bool(solver_config.dense_semantic_enabled)
            and float(solver_config.dense_semantic_weight) > 0.0
        )
    ):
        rgb_output, rgb_gif = render_pose_rgb_animation(
            solver.backend,
            pose_result,
            output_dir=output / "solved_rgb",
            frame_indices=frame_indices,
        )
        pose_result["rgbDir"] = str(rgb_output)
        pose_result["rgbGif"] = str(rgb_gif)
    pose_result["clipResultPath"] = str(persist_gpu_clip_result(pose_result, output))
    return AnimationSolveResult(
        pose_result,
        depth_output,
        depth_gif,
        None,
        preview_gif,
        rgb_dir=rgb_output,
        rgb_gif_path=rgb_gif,
    )
