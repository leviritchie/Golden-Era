"""Source-owned runtime for the Roc enabled-feature hybrid notebook.

The notebook is intentionally a thin control surface. Setup, solver, and
delivery code live in neighboring source files and are executed in one
namespace so Blender state and live preview state remain shared.
"""
from __future__ import annotations

import math
import re
import json
import hashlib
import shutil
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Sequence

from PIL import Image

from pose_fit_blender import resolve_pose_fit_blender

TOOL_DIR = Path(__file__).resolve().parent

def _read_source(name: str) -> str:
    return (TOOL_DIR / name).read_text(encoding="utf-8")

SETUP_SOURCE = _read_source("roc_semantic_hybrid_setup.py")
SOLVER_SOURCE = _read_source("roc_semantic_hybrid_solver_body.py")
FULL_SOURCE = _read_source("roc_semantic_hybrid_delivery.py")
REPORT_SOURCE = _read_source("roc_semantic_hybrid_report.py")


@dataclass
class RocHybridConfig:
    root: Path = Path(r"V:/Games/Olden Era Playtest Tweak")
    src_glb: Path = Path(r"C:/Users/<user>/Downloads/griffon_smart_rigged.glb")
    # Optional post-rig proof produced by run_meshy_rigidization.py.  When set,
    # initialize verifies that the selected GLB is the audited output and that
    # the Meshy armature was preserved before starting Blender workers.
    meshy_rigidization_report: Path | None = None
    require_meshy_rigidization: bool = False
    unit_name: str = "roc"
    unit_sid: str | None = None
    animation_name: str = "move_g0"
    pilot_dir: Path | None = None
    camera_fit_path: Path | None = None
    target_frame_dir: str = "frames_ground_truth"
    shadow_culled_frame_dir: str = "frames_ground_truth_shadow_culled"
    target_depth_dir: str = "frames_ground_truth_depth_vda"
    # Optional HoMM3 lab RIFE source. An int is one DEF group. A sequence
    # concatenates those groups in order (idle, then move-start, then walk)
    # so later frames seed from the previous clip instead of from bind.
    # Do not enable this together with authentic DEF source: RIFE can drop a
    # prop for one interpolated frame and keep it gone.
    rife_lab_frame_dir: Path | None = None
    rife_lab_group: int | Sequence[int] | None = None
    rife_expected_count: int | Sequence[int] | None = None
    depth_video_fps: float = 12.0
    rife_nn_upscale_meta: Path | None = None
    # Deprecated. RIFE now stays on the pose-fit camera; do not point this at a
    # native-plate rescale of pxPerWorld.
    rife_camera_fit_path: Path | None = None
    # Authentic 12 fps DEF extract (GG_FF.png). Same concatenation contract as
    # RIFE, but never interpolated. Point at extracted_battle_source_12fps.
    def_lab_frame_dir: Path | None = None
    def_lab_group: int | Sequence[int] | None = None
    def_expected_count: int | Sequence[int] | None = None
    def_nn_upscale_meta: Path | None = None
    score_mode: str = "depth"
    semantic_only: bool = True
    # New name for the semantic activation switch; semantic_only remains a
    # compatibility alias for existing notebook cells.
    semantic_enabled: bool | None = None
    semantic_model_id: str = "google/siglip2-base-patch16-512"
    semantic_embedding_layer: str = "projected"
    # Select one or more image-embedding layers. Cosines are computed per
    # layer and averaged; vectors are never concatenated across dimensions.
    semantic_embedding_layers: tuple[str, ...] | str | None = None
    semantic_pooling: str = "model"
    # Number of candidate renders sent to the vision encoder together. Keep
    # this at 1 on 16 GB GPUs unless the model footprint has been measured.
    semantic_batch_size: int = 1
    # The two enabled semantic encoders need not have the same optimal batch.
    # None preserves the compatibility value above for that encoder.
    semantic_global_batch_size: int | None = None
    semantic_dense_batch_size: int | None = None
    semantic_subject_crop: bool = False
    semantic_subject_padding_frac: float = 0.18
    # Dense semantic features are a separate spatial signal.  A null model id
    # reuses the global semantic model when the runtime supports patch tokens.
    semantic_dense_enabled: bool = False
    semantic_dense_model_id: str | None = None
    semantic_dense_embedding_layers: tuple[str, ...] | str = ("last",)
    semantic_dense_weight: float = 0.0
    semantic_dense_local_radius: int = 1
    semantic_dense_position_weight: float = 0.15
    semantic_dense_view_index: int = 0
    semantic_multiview: bool = True
    semantic_view_angles_deg: tuple[float, ...] = (0.0, 180.0, 90.0)
    semantic_view_elevations_deg: tuple[float, ...] = (0.0, 0.0, 12.0)
    semantic_view_weights: tuple[float, ...] = (1.0, 1.0, 1.0)
    hybrid_semantic_weight: float = 0.70
    hybrid_depth_weight: float = 0.30  # legacy alias for hybrid_geometry_weight
    # The worker term is the complete enabled geometric objective, not depth
    # alone: it preserves depth/silhouette, chroma, zone, edge, reverse-view,
    # and anatomical-box scoring selected below.
    hybrid_geometry_enabled: bool = True
    hybrid_geometry_weight: float | None = None
    # Blender render-plan override. None derives the required buffer from the
    # enabled geometric/reverse-profile terms; False keeps semantic-only runs
    # on the cheaper RGB/alpha path; True is useful for a depth ablation.
    render_depth_for_scoring: bool | None = None
    # Blender 3.5 background compositor renders do not expose a usable
    # in-memory Render Result; keep the correctness-preserving PNG path on.
    render_result_in_memory: bool = False
    # PNG is lossless either way; zero minimizes CPU time spent compressing
    # the short-lived search RGB/depth buffers.
    render_png_compression: int = 0
    # Lighting ablation for semantic RGB renders. flat_emission is the proven
    # control; sun_above uses a real Eevee Sun aimed from above the subject.
    render_lighting_mode: str = "flat_emission"
    render_sun_energy: float = 2.0
    render_sun_azimuth_deg: float = -35.0
    render_sun_elevation_deg: float = 55.0
    render_sun_angle_deg: float = 5.0
    incremental_pose_application: bool = True
    # Optional worker-side silhouette triage before expensive semantic
    # encoding. The heuristic rank/fraction gate is separately opt-in below;
    # the normal path uses the exact staged hybrid bound.
    triage_enabled: bool = True
    triage_silhouette_enabled: bool = True
    # The old silhouette rank/fraction gate is intentionally opt-in: it can
    # discard a candidate that a later semantic term would prefer. The normal
    # path uses only the exact staged hybrid bound.
    triage_silhouette_heuristic_enabled: bool = False
    triage_silhouette_floor: float = 0.02
    triage_silhouette_keep_fraction: float = 0.25
    triage_silhouette_min_candidates: int = 2
    # Optional hard cap. Zero means use the fraction/minimum policy only.
    # Two keeps the dense/global encoder focused on the strongest silhouettes
    # without changing the cheap worker-side ranking.
    triage_silhouette_max_candidates: int = 2
    # Blender-free geometric candidate cascade. This is deliberately separate
    # from the legacy worker-side silhouette gate above: proxy rejection must
    # happen before any Blender request, while Blender remains authoritative
    # for the exact geometry/depth/RGB score.
    proxy_enabled: bool = False
    proxy_device: str = "auto"
    # Do not pay for proxy setup/evaluation unless the wave is large enough to
    # eliminate work. The comparison is strict: n <= this value bypasses it.
    proxy_min_candidates: int = 8
    # High-information stages can define the search coordinate system and must
    # be fully scored. Values match the explicit proxy_stage supplied by the
    # solver, not human-facing candidate labels.
    proxy_protected_stages: tuple[str, ...] | str = ("rotation_vector",)
    # Sample proxy rejects through the complete renderer/score path before
    # allowing a search class to rely on hard pruning.
    proxy_audit_enabled: bool = True
    proxy_audit_fraction: float = 0.10
    proxy_audit_max_candidates: int = 4
    proxy_audit_regret_tolerance: float = 0.0
    proxy_gpu_tensor_cache_enabled: bool = True
    proxy_gpu_asset_cache_max_entries: int = 2
    proxy_resolution: tuple[int, int] = (96, 86)
    proxy_level0_enabled: bool = True
    proxy_level0_points_per_bone: int = 48
    proxy_level0_keep_fraction: float = 0.50
    proxy_level0_min_candidates: int = 4
    proxy_level0_max_candidates: int = 0
    proxy_level1_enabled: bool = True
    proxy_level1_max_vertices: int = 6000
    proxy_level1_keep_fraction: float = 0.50
    proxy_level1_min_candidates: int = 4
    proxy_level1_max_candidates: int = 0
    proxy_point_radius: int = 1
    proxy_target_alpha_threshold: int = 8
    proxy_centroid_weight: float = 0.10
    proxy_occupancy_weight: float = 0.05
    # Persistent CUDA proposal advisor. It never replaces the original
    # Blender/chroma/depth/DINO/SigLIP scorer; it only suggests directions and
    # a bounded root shortlist that the authoritative scorer must verify.
    gpu_pose_advisor_enabled: bool = False
    gpu_pose_advisor_device: str = "cuda"
    gpu_pose_advisor_direction_enabled: bool = True
    gpu_pose_advisor_root_enabled: bool = True
    gpu_pose_advisor_max_points: int = 6000
    gpu_pose_advisor_sdf_weight: float = 1.0
    gpu_pose_advisor_centroid_weight: float = 0.35
    gpu_pose_advisor_extent_weight: float = 0.25
    gpu_pose_advisor_min_gradient_norm: float = 1e-5
    # Relative projected-sensitivity bands for proposal breadth.  High-signal
    # bones get gradient, opposite, and escape probes; medium bones get only
    # the direct pair; low-signal bones skip coarse vector probes and remain
    # available to the original refinement/multi-bone stages.
    gpu_pose_advisor_medium_sensitivity_ratio: float = 0.08
    gpu_pose_advisor_high_sensitivity_ratio: float = 0.35
    gpu_pose_advisor_orthogonal_count: int = 1
    gpu_pose_advisor_root_hypothesis_count: int = 256
    gpu_pose_advisor_root_keep: int = 8
    gpu_pose_advisor_seed: int = 17
    gpu_pose_advisor_fallback_rotation_vectors: bool = True
    # The bound is exact for the normalized hybrid ledger: unknown semantic
    # components can contribute at most one. It is only applied when a caller
    # supplies a current incumbent, so clip temporal acceptance is untouched.
    semantic_branch_bound_enabled: bool = True
    semantic_branch_bound_margin: float = 0.0
    semantic_candidate_cache_enabled: bool = True
    semantic_candidate_cache_max_entries: int = 4096
    # Image decode/crop cache is shared by global and dense semantic lanes.
    semantic_image_cache_max_entries: int = 256
    # Dense cache stores candidate patch grids, not target-specific scores.
    semantic_dense_grid_cache_max_entries: int = 128
    # Process-wide caches survive initialize()/close() between animations in a
    # batch run. Disable this only for memory-isolation tests.
    semantic_service_enabled: bool = True
    # Bump this after changing encoder implementation or local checkpoint
    # contents so a live notebook cannot reuse an older model instance.
    semantic_service_cache_generation: str = "v1"
    semantic_service_encoder_cache_max_entries: int = 2
    semantic_service_target_cache_max_entries: int = 512
    semantic_service_dense_target_cache_max_entries: int = 128
    silhouette_depth_weight: float = 1.0
    blue_zone_penalty: float = 2.5
    red_zone_penalty: float = 1.0
    silhouette_edge_bonus: float = 0.0
    reverse_profile_enabled: bool = False
    reverse_profile_weight: float = 0.5
    profile_half_bias: float = 0.5
    reverse_profile_raw_frame_dir: str = "frames_src_reverse_profile"
    reverse_profile_frame_dir: str = "frames_src_reverse_profile_shadow_culled"
    reverse_profile_depth_dir: str = "frames_src_depth_vda_reverse"
    # Relative to the detected side-profile camera: negative turns toward the
    # roc's front, while positive turns toward its rear. 90 degrees is a
    # longitudinal head-on view and is not an action-camera angle.
    action_camera_angle_deg: float = -45.0
    action_camera_elevation_deg: float = 18.0
    detect_profile_enabled: bool = True
    # Provisional picker cameras are authored in the selected mesh's source
    # frame. Do not rotate the asset into a guessed canonical frame by default.
    mesh_orientation_mode: str = "none"
    profile_samples: int = 72
    semantic_text_enabled: bool = False
    semantic_text_prompt: str = "a roc flying in side profile"
    hybrid_text_weight: float = 0.0
    semantic_negative_text_enabled: bool = False
    semantic_negative_text_prompt: str = ""
    hybrid_negative_text_weight: float = 0.0
    live_preview: bool = True
    preview_every: int = 1
    # Local approved-vocabulary detector/scoring. The selected feature set is
    # generated per frame; keep preview visibility separate
    # so boxes can be scored without drawing them over the live preview.
    anatomical_boxes_enabled: bool = False
    anatomical_part_weight: float = 0.20
    hybrid_anatomical_weight: float = 0.0
    anatomical_max_features: int = 8
    anatomical_min_area_frac: float = 0.001
    anatomical_center_weight: float = 0.70
    anatomical_extent_weight: float = 0.30
    anatomical_laterality_enabled: bool = True
    # Profile laterality is biological, not screen-space. The depth source
    # ranks camera-near/far instances and maps them through this contract.
    anatomical_laterality_source: str = "depth"
    anatomical_laterality_near_side: str = "R"
    anatomical_laterality_depth_margin: float = 0.04
    # Retained as a compatibility field for older notebook cells. It is no
    # longer used to split boxes by image X.
    anatomical_laterality_center_margin_frac: float = 0.025
    show_anatomical_boxes: bool = False
    # Temporary broad-motion diagnostic. This is the symmetric per-bone
    # freedom used by the scalable range builder; it is not unit-specific.
    joint_free_deg: float = 150.0
    # Delivered whole-model motion. These values are normalized to the mesh
    # body length and are applied above the armature, so they are independent
    # of the fitted camera's pixel scale.
    motion_root_enabled: bool | None = None
    motion_root_axes: tuple[str, ...] | str = ("forward",)
    motion_root_forward_radius_body_lengths: float = 0.20
    motion_root_lateral_radius_body_lengths: float = 0.05
    motion_root_vertical_radius_body_lengths: float = 0.0
    motion_root_coarse_step_body_lengths: float = 0.05
    motion_root_refine_step_body_lengths: float = 0.0125
    motion_root_magnitude_weight: float = 0.01
    motion_root_velocity_weight: float = 0.02
    motion_root_acceleration_weight: float = 0.01
    motion_root_loop_weight: float = 0.0
    motion_root_loop_velocity_weight: float = 0.0
    motion_root_coupled_blocks_enabled: bool = True
    # Rigid-body attitude is applied above the Meshy armature in a fixed
    # camera-relative basis. It is not a local Hips/Spine degree of freedom.
    motion_root_rotation_enabled: bool = False
    motion_root_rotation_basis: str = "camera"
    motion_root_rotation_axes: tuple[str, ...] | str = ("camera_forward",)
    motion_root_rotation_limit_deg: float = 180.0
    motion_root_rotation_coarse_step_deg: float = 30.0
    motion_root_rotation_refine_step_deg: float = 10.0
    motion_root_rotation_escape_enabled: bool = True
    motion_root_rotation_escape_axes: tuple[str, ...] | str = ("camera_forward",)
    motion_root_rotation_escape_angles_deg: tuple[float, ...] = (
        -180.0,
        -150.0,
        -120.0,
        -90.0,
        -60.0,
        -30.0,
        30.0,
        60.0,
        90.0,
        120.0,
        150.0,
        180.0,
    )
    motion_root_rotation_escape_top_k: int = 4
    motion_root_rotation_escape_force_image_best: bool = True
    motion_root_rotation_escape_min_image_improvement: float = 0.0
    motion_root_rotation_escape_relax_enabled: bool = True
    motion_root_rotation_escape_relax_bone_count: int = 3
    motion_root_rotation_escape_relax_rounds: int = 1
    motion_root_rotation_escape_relax_step_deg: float = 12.0
    motion_root_rotation_escape_relax_refine_step_deg: float = 4.0
    motion_root_rotation_magnitude_weight: float = 0.0
    motion_root_rotation_velocity_weight: float = 0.02
    motion_root_rotation_acceleration_weight: float = 0.01
    motion_root_rotation_loop_weight: float = 0.0
    motion_root_rotation_loop_velocity_weight: float = 0.0
    motion_root_rotation_coupled_blocks_enabled: bool = True
    # Compatibility aliases for notebooks/configs written before the root
    # motion contract. They are no longer the primary search representation.
    body_translation_enabled: bool = False
    body_translation_radius_px: float = 48.0
    body_translation_coarse_step_px: float = 12.0
    body_translation_refine_step_px: float = 3.0
    coarse_step_deg: float = 16.0
    refine_step_deg: float = 4.0
    compound_cd_rounds: int = 2
    compound_pair_step_mult: float = 1.0
    # Search all local Euler axes. The worker strips twist using each bone's
    # actual rest-space shaft, so excluding global Y is not valid for arbitrary
    # imported rigs whose bones are not aligned to the same local axis.
    search_axes: tuple[str, ...] = ("x", "y", "z")
    exclude_bone_roll: bool = True
    # Imported rig axes are not guaranteed to be an anatomical search frame.
    # The optional rotation-vector shell searches around the rest-space bone
    # shaft and can continue a promising direction past the first probe.
    rotation_vector_search_enabled: bool = False
    rotation_vector_probe_count: int = 8
    rotation_vector_probe_step_deg: float = 16.0
    directional_continuation_enabled: bool = False
    directional_max_steps: int = 4
    directional_step_multiplier: float = 2.0
    directional_top_k: int = 2
    directional_min_improvement: float = 0.0
    # adaptive keeps the established swing-only Euler path, while the vector
    # search adds explicit twist candidates and lets the score accept them.
    bone_twist_policy: str = "adaptive"
    bone_twist_overrides: dict[str, str] = field(default_factory=dict)
    skip_tiny_bones: bool = True
    semantic_optimizer: bool = False
    # Global clip fitting. This is disabled by default so the established
    # per-frame path remains the control condition for ablations.
    clip_optimization_enabled: bool = False
    clip_warm_start: str = "previous"
    clip_rounds: int = 1
    clip_refine_rounds: int = 1
    # Fine search is local refinement. Do not spend a second full clip pass
    # on axes whose coarse proposals never improved the global objective.
    clip_refine_accepted_only: bool = True
    clip_velocity_weight: float = 0.08
    clip_acceleration_weight: float = 0.04
    clip_contact_weight: float = 0.0
    clip_loop_weight: float = 0.0
    clip_loop_velocity_weight: float = 0.0
    clip_loop_enabled: bool = False
    clip_motion_root_magnitude_weight: float | None = None
    clip_motion_root_velocity_weight: float | None = None
    clip_motion_root_acceleration_weight: float | None = None
    clip_motion_root_loop_weight: float | None = None
    clip_motion_root_loop_velocity_weight: float | None = None
    clip_body_translation_velocity_weight: float | None = None
    clip_body_translation_acceleration_weight: float | None = None
    clip_contact_bones: tuple[str, ...] = ()
    clip_robust_scale_deg: float = 16.0
    clip_coarse_step_deg: float = 16.0
    clip_refine_step_deg: float = 4.0
    clip_max_evaluations_per_axis: int = 3
    clip_candidate_mode: str = "range_extremes"
    clip_acceptance_margin: float = 0.001
    clip_acceptance_relative_margin: float = 0.0
    clip_preview_candidates: bool = False
    clip_batch_candidates: bool = True
    # Combined optimizer path: batched independent probes, dependency-aware
    # sparse block search, a small beam, then coordinate polish.
    clip_probe_enabled: bool = True
    clip_probe_step_deg: float = 30.0
    clip_probe_top_k: int = 12
    clip_probe_min_improvement: float = -0.005
    clip_adaptive_blocks_enabled: bool = True
    clip_adaptive_block_size: int = 3
    clip_adaptive_rounds: int = 1
    clip_adaptive_step_deg: float = 10.0
    clip_adaptive_beam_width: int = 4
    clip_polish_enabled: bool = True
    clip_polish_rounds: int = 1
    clip_polish_step_deg: float = 2.0
    clip_sensitivity_enabled: bool = True
    clip_sensitivity_score_epsilon: float = 0.002
    clip_polish_include_neighbors: bool = True
    # Blender is the dominant per-candidate cost. Four persistent workers keep
    # the proposal waves full on the workstation used by this experiment.
    parallel_candidate_rendering: bool = True
    render_worker_count: int = 4
    run_frame0_pilot: bool = True
    # Empty means: discover the numbered original frames in target_frame_dir.
    # Do not default to the 30-frame RIFE presentation lane.
    frame_indices: tuple[int, ...] = ()
    seed_from_previous: bool = True
    mesh_scale: float = 1.0
    search_scale: float = 0.35
    # Generic picker cameras are provisional job-camera seeds. Calibrate their
    # scale and subject center against frame 00 before searching; authoritative
    # fitted cameras are never modified by this pass.
    auto_frame0_camera_fit: bool = True
    frame0_fit_alpha_threshold: int = 8
    frame0_fit_margin: float = 1.04
    frame0_fit_passes: int = 2
    multi_axis_mode: str = "compound"
    axis_probe_first: bool = True
    compound_pair_step_mult: float = 1.0
    bone_order_mode: str = "dependency"
    branch_walk_camera_bias: str = "none"
    bone_order: tuple[str, ...] = ()
    search_bones: tuple[str, ...] = ()
    include_unlisted_search_bones: bool = True
    near_bone_refinement_enabled: bool = False
    near_bone_refinement_step_deg: float = 1.0
    # Optional multi-bone search. `single` preserves the established
    # coarse/fine one-bone-at-a-time path.
    multi_bone_mode: str = "single"
    multi_bone_grouping: str = "window"
    multi_bone_block_size: int = 2
    multi_bone_rounds: int = 1
    multi_bone_step_deg: float = 4.0
    multi_bone_candidate_pattern: str = "star"
    multi_bone_beam_width: int = 2
    multi_bone_probe_enabled: bool = True
    multi_bone_probe_step_deg: float = 30.0
    multi_bone_probe_top_k: int = 12
    multi_bone_probe_min_improvement: float = -0.005
    multi_bone_adaptive_blocks_enabled: bool = True
    multi_bone_intermediate_step_deg: float = 10.0
    multi_bone_intermediate_rounds: int = 1
    multi_bone_polish_enabled: bool = True
    multi_bone_polish_rounds: int = 1
    multi_bone_polish_step_deg: float = 2.0
    ik_enabled: bool = False
    ik_mode: str = "off"
    ik_bones: tuple[str, ...] = ()
    ik_targets: dict[str, tuple[float, float]] | None = None
    ik_auto_targets: bool = True
    ik_target_source: Path | None = None
    ik_target_search_enabled: bool = False
    ik_target_search_only: bool = False
    ik_target_search_bones: tuple[str, ...] = ()
    ik_target_coarse_step_px: float = 24.0
    ik_target_refine_step_px: float = 6.0
    ik_target_search_radius_px: float = 48.0
    ik_target_min_improvement: float = 0.0
    ik_chain_length: int = 1
    ik_iterations: int = 8
    ik_strength: float = 1.0
    ik_depth: float = 6.0
    match_dir_name: str = "roc_hybrid_match_v1"

    def __post_init__(self) -> None:
        if self.semantic_enabled is None:
            self.semantic_enabled = bool(self.semantic_only)
        else:
            self.semantic_enabled = bool(self.semantic_enabled)
            self.semantic_only = bool(self.semantic_enabled)
        # Migrate the old toggle without allowing its pixel-space values to
        # become the new optimizer's coordinate system.
        if self.motion_root_enabled is None:
            self.motion_root_enabled = bool(self.body_translation_enabled)
        else:
            self.motion_root_enabled = bool(self.motion_root_enabled)
        self.body_translation_enabled = bool(self.motion_root_enabled)
        if isinstance(self.motion_root_axes, str):
            self.motion_root_axes = tuple(
                part.strip().lower()
                for part in self.motion_root_axes.split(",")
                if part.strip()
            )
        else:
            self.motion_root_axes = tuple(
                str(axis).strip().lower()
                for axis in self.motion_root_axes
                if str(axis).strip()
            )
        allowed_motion_axes = {"forward", "lateral", "vertical"}
        if any(axis not in allowed_motion_axes for axis in self.motion_root_axes):
            raise ValueError(
                "motion_root_axes must be a subset of forward, lateral, vertical"
            )
        if self.motion_root_enabled and not self.motion_root_axes:
            raise ValueError("motion_root_axes must be non-empty when motion root is enabled")
        self.motion_root_rotation_basis = str(
            self.motion_root_rotation_basis
        ).strip().lower()
        if isinstance(self.motion_root_rotation_axes, str):
            self.motion_root_rotation_axes = tuple(
                part.strip().lower()
                for part in self.motion_root_rotation_axes.split(",")
                if part.strip()
            )
        else:
            self.motion_root_rotation_axes = tuple(
                str(axis).strip().lower()
                for axis in self.motion_root_rotation_axes
                if str(axis).strip()
            )
        if isinstance(self.motion_root_rotation_escape_axes, str):
            self.motion_root_rotation_escape_axes = tuple(
                part.strip().lower()
                for part in self.motion_root_rotation_escape_axes.split(",")
                if part.strip()
            )
        else:
            self.motion_root_rotation_escape_axes = tuple(
                str(axis).strip().lower()
                for axis in self.motion_root_rotation_escape_axes
                if str(axis).strip()
            )
        self.motion_root_rotation_escape_angles_deg = tuple(
            float(angle) for angle in self.motion_root_rotation_escape_angles_deg
        )
        allowed_rotation_axes = {
            "camera_forward",
            "camera_right",
            "camera_up",
        }
        if self.motion_root_rotation_basis != "camera":
            raise ValueError("motion_root_rotation_basis must be 'camera'")
        if any(axis not in allowed_rotation_axes for axis in self.motion_root_rotation_axes):
            raise ValueError(
                "motion_root_rotation_axes must be a subset of "
                "camera_forward, camera_right, camera_up"
            )
        if any(
            axis not in allowed_rotation_axes
            for axis in self.motion_root_rotation_escape_axes
        ):
            raise ValueError(
                "motion_root_rotation_escape_axes must be a subset of "
                "camera_forward, camera_right, camera_up"
            )
        if not set(self.motion_root_rotation_escape_axes).issubset(
            set(self.motion_root_rotation_axes)
        ):
            raise ValueError(
                "motion_root_rotation_escape_axes must be a subset of "
                "motion_root_rotation_axes"
            )
        if self.clip_motion_root_magnitude_weight is None:
            self.clip_motion_root_magnitude_weight = float(self.motion_root_magnitude_weight)
        if self.clip_motion_root_velocity_weight is None:
            self.clip_motion_root_velocity_weight = float(self.motion_root_velocity_weight)
        if self.clip_motion_root_acceleration_weight is None:
            self.clip_motion_root_acceleration_weight = float(self.motion_root_acceleration_weight)
        if self.clip_motion_root_loop_weight is None:
            self.clip_motion_root_loop_weight = float(self.motion_root_loop_weight)
        if self.clip_motion_root_loop_velocity_weight is None:
            self.clip_motion_root_loop_velocity_weight = float(self.motion_root_loop_velocity_weight)
        self.clip_body_translation_velocity_weight = float(self.clip_motion_root_velocity_weight)
        self.clip_body_translation_acceleration_weight = float(self.clip_motion_root_acceleration_weight)
        if self.semantic_embedding_layers is None:
            self.semantic_embedding_layers = (str(self.semantic_embedding_layer),)
        elif isinstance(self.semantic_embedding_layers, str):
            self.semantic_embedding_layers = tuple(
                part.strip()
                for part in self.semantic_embedding_layers.split(",")
                if part.strip()
            )
        else:
            self.semantic_embedding_layers = tuple(
                str(layer).strip() for layer in self.semantic_embedding_layers if str(layer).strip()
            )
        if not self.semantic_embedding_layers:
            raise ValueError("semantic_embedding_layers must contain at least one layer")
        # Keep the old singular field meaningful for notebook summaries and
        # callers that still inspect it.
        self.semantic_embedding_layer = self.semantic_embedding_layers[0]
        if isinstance(self.semantic_dense_embedding_layers, str):
            self.semantic_dense_embedding_layers = tuple(
                part.strip()
                for part in self.semantic_dense_embedding_layers.split(",")
                if part.strip()
            )
        else:
            self.semantic_dense_embedding_layers = tuple(
                str(layer).strip()
                for layer in self.semantic_dense_embedding_layers
                if str(layer).strip()
            )
        if not self.semantic_dense_embedding_layers:
            raise ValueError("semantic_dense_embedding_layers must contain at least one layer")
        # Keep the dense ablation on the same model family by default. A
        # different model, such as DINOv3, remains an explicit config choice.
        if self.semantic_dense_model_id is None:
            self.semantic_dense_model_id = self.semantic_model_id
        if isinstance(self.clip_contact_bones, str):
            self.clip_contact_bones = (
                (self.clip_contact_bones.strip(),)
                if self.clip_contact_bones.strip()
                else ()
            )
        else:
            self.clip_contact_bones = tuple(
                str(bone).strip() for bone in self.clip_contact_bones if str(bone).strip()
            )
        if self.hybrid_geometry_weight is None:
            self.hybrid_geometry_weight = float(self.hybrid_depth_weight)
        for name, value in (
            ("silhouette_depth_weight", self.silhouette_depth_weight),
            ("reverse_profile_weight", self.reverse_profile_weight),
            ("profile_half_bias", self.profile_half_bias),
            ("ik_strength", self.ik_strength),
            ("anatomical_part_weight", self.anatomical_part_weight),
            ("anatomical_center_weight", self.anatomical_center_weight),
            ("anatomical_extent_weight", self.anatomical_extent_weight),
            (
                "anatomical_laterality_center_margin_frac",
                self.anatomical_laterality_center_margin_frac,
            ),
            ("anatomical_laterality_depth_margin", self.anatomical_laterality_depth_margin),
        ):
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1, got {value!r}")
        for name, value in (
            ("blue_zone_penalty", self.blue_zone_penalty),
            ("red_zone_penalty", self.red_zone_penalty),
            ("silhouette_edge_bonus", self.silhouette_edge_bonus),
            ("hybrid_text_weight", self.hybrid_text_weight),
            ("hybrid_negative_text_weight", self.hybrid_negative_text_weight),
            ("hybrid_geometry_weight", self.hybrid_geometry_weight),
            ("hybrid_anatomical_weight", self.hybrid_anatomical_weight),
            ("semantic_dense_weight", self.semantic_dense_weight),
            ("semantic_dense_position_weight", self.semantic_dense_position_weight),
            ("anatomical_min_area_frac", self.anatomical_min_area_frac),
            ("ik_target_coarse_step_px", self.ik_target_coarse_step_px),
            ("ik_target_refine_step_px", self.ik_target_refine_step_px),
            ("ik_target_search_radius_px", self.ik_target_search_radius_px),
            ("ik_target_min_improvement", self.ik_target_min_improvement),
        ):
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError(f"{name} must be finite and non-negative, got {value!r}")
        if not math.isfinite(float(self.triage_silhouette_floor)) or not 0.0 <= float(self.triage_silhouette_floor) <= 1.0:
            raise ValueError("triage_silhouette_floor must be between 0 and 1")
        if not math.isfinite(float(self.triage_silhouette_keep_fraction)) or not 0.0 < float(self.triage_silhouette_keep_fraction) <= 1.0:
            raise ValueError("triage_silhouette_keep_fraction must be in (0, 1]")
        if int(self.triage_silhouette_min_candidates) < 1:
            raise ValueError("triage_silhouette_min_candidates must be at least 1")
        if int(self.triage_silhouette_max_candidates) < 0:
            raise ValueError("triage_silhouette_max_candidates must be non-negative")
        if (
            int(self.triage_silhouette_max_candidates) > 0
            and int(self.triage_silhouette_max_candidates)
            < int(self.triage_silhouette_min_candidates)
        ):
            raise ValueError(
                "triage_silhouette_max_candidates must be zero or at least "
                "triage_silhouette_min_candidates"
            )
        if str(self.proxy_device).lower() not in {"auto", "cpu", "cuda"} and not str(self.proxy_device).lower().startswith("cuda:"):
            raise ValueError("proxy_device must be auto, cpu, cuda, or cuda:<index>")
        if int(self.proxy_min_candidates) < 1:
            raise ValueError("proxy_min_candidates must be at least 1")
        protected_stages = (
            tuple(str(value).strip() for value in self.proxy_protected_stages.split(","))
            if isinstance(self.proxy_protected_stages, str)
            else tuple(str(value).strip() for value in self.proxy_protected_stages)
        )
        if any(not value for value in protected_stages):
            raise ValueError("proxy_protected_stages cannot contain empty values")
        if not math.isfinite(float(self.proxy_audit_fraction)) or not 0.0 <= float(self.proxy_audit_fraction) <= 1.0:
            raise ValueError("proxy_audit_fraction must be between 0 and 1")
        if int(self.proxy_audit_max_candidates) < 0:
            raise ValueError("proxy_audit_max_candidates must be non-negative")
        if not math.isfinite(float(self.proxy_audit_regret_tolerance)) or float(self.proxy_audit_regret_tolerance) < 0.0:
            raise ValueError("proxy_audit_regret_tolerance must be finite and non-negative")
        if int(self.proxy_gpu_asset_cache_max_entries) < 1:
            raise ValueError("proxy_gpu_asset_cache_max_entries must be at least 1")
        if len(tuple(self.proxy_resolution)) != 2 or any(int(value) < 16 for value in self.proxy_resolution):
            raise ValueError("proxy_resolution must contain two dimensions >= 16")
        if int(self.proxy_level0_points_per_bone) < 4:
            raise ValueError("proxy_level0_points_per_bone must be at least 4")
        if int(self.proxy_level1_max_vertices) < 32:
            raise ValueError("proxy_level1_max_vertices must be at least 32")
        if int(self.proxy_point_radius) < 0:
            raise ValueError("proxy_point_radius must be non-negative")
        if not 0 <= int(self.proxy_target_alpha_threshold) <= 255:
            raise ValueError("proxy_target_alpha_threshold must be between 0 and 255")
        for name in (
            "proxy_level0_keep_fraction",
            "proxy_level1_keep_fraction",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must be in (0, 1]")
        for name in (
            "proxy_level0_min_candidates",
            "proxy_level1_min_candidates",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be at least 1")
        for name in (
            "proxy_level0_max_candidates",
            "proxy_level1_max_candidates",
        ):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be non-negative")
        if not 0.0 <= float(self.proxy_centroid_weight) <= 1.0:
            raise ValueError("proxy_centroid_weight must be between 0 and 1")
        if not 0.0 <= float(self.proxy_occupancy_weight) <= 1.0:
            raise ValueError("proxy_occupancy_weight must be between 0 and 1")
        advisor_device = str(self.gpu_pose_advisor_device).lower()
        if advisor_device != "cuda" and not advisor_device.startswith("cuda:"):
            raise ValueError("gpu_pose_advisor_device must be cuda or cuda:<index>")
        if int(self.gpu_pose_advisor_max_points) < 32:
            raise ValueError("gpu_pose_advisor_max_points must be at least 32")
        medium_sensitivity_ratio = float(self.gpu_pose_advisor_medium_sensitivity_ratio)
        high_sensitivity_ratio = float(self.gpu_pose_advisor_high_sensitivity_ratio)
        if not math.isfinite(medium_sensitivity_ratio) or not 0.0 <= medium_sensitivity_ratio <= 1.0:
            raise ValueError("gpu_pose_advisor_medium_sensitivity_ratio must be between 0 and 1")
        if not math.isfinite(high_sensitivity_ratio) or not 0.0 <= high_sensitivity_ratio <= 1.0:
            raise ValueError("gpu_pose_advisor_high_sensitivity_ratio must be between 0 and 1")
        if medium_sensitivity_ratio > high_sensitivity_ratio:
            raise ValueError(
                "gpu_pose_advisor_medium_sensitivity_ratio must not exceed "
                "gpu_pose_advisor_high_sensitivity_ratio"
            )
        if int(self.gpu_pose_advisor_orthogonal_count) not in {0, 1, 2}:
            raise ValueError("gpu_pose_advisor_orthogonal_count must be 0, 1, or 2")
        if int(self.gpu_pose_advisor_root_hypothesis_count) < 1:
            raise ValueError("gpu_pose_advisor_root_hypothesis_count must be positive")
        if int(self.gpu_pose_advisor_root_keep) < 1:
            raise ValueError("gpu_pose_advisor_root_keep must be positive")
        for name in (
            "gpu_pose_advisor_sdf_weight",
            "gpu_pose_advisor_centroid_weight",
            "gpu_pose_advisor_extent_weight",
            "gpu_pose_advisor_min_gradient_norm",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if float(self.ik_target_coarse_step_px) <= 0.0:
            raise ValueError("ik_target_coarse_step_px must be positive")
        if float(self.ik_target_refine_step_px) <= 0.0:
            raise ValueError("ik_target_refine_step_px must be positive")
        if float(self.ik_target_search_radius_px) <= 0.0:
            raise ValueError("ik_target_search_radius_px must be positive")
        if self.semantic_text_enabled and not str(self.semantic_text_prompt).strip():
            raise ValueError("semantic_text_prompt must be non-empty when semantic_text_enabled=True")
        if self.semantic_negative_text_enabled and not str(self.semantic_negative_text_prompt).strip():
            raise ValueError(
                "semantic_negative_text_prompt must be non-empty when semantic_negative_text_enabled=True"
            )
        if float(self.hybrid_negative_text_weight) > 0.0 and not self.semantic_negative_text_enabled:
            raise ValueError(
                "hybrid_negative_text_weight requires semantic_negative_text_enabled=True"
            )
        if str(self.ik_mode).lower() not in {"off", "replace", "replace_all", "add", "add_all"}:
            raise ValueError("ik_mode must be off, replace, replace_all, add, or add_all")
        if str(self.mesh_orientation_mode).lower() not in {"auto", "none"}:
            raise ValueError("mesh_orientation_mode must be auto or none")
        if str(self.bone_order_mode).lower() not in {
            "dependency",
            "reverse_dependency",
            "alphabetical",
            "explicit",
            "branch_walk",
        }:
            raise ValueError(
                "bone_order_mode must be dependency, reverse_dependency, alphabetical, explicit, or branch_walk"
            )
        if str(self.branch_walk_camera_bias).lower() not in {"none", "default_camera"}:
            raise ValueError(
                "branch_walk_camera_bias must be none or default_camera"
            )
        if not math.isfinite(float(self.near_bone_refinement_step_deg)) or float(self.near_bone_refinement_step_deg) <= 0.0:
            raise ValueError("near_bone_refinement_step_deg must be finite and positive")
        if float(self.refine_step_deg) <= 0.0:
            raise ValueError("refine_step_deg must be positive")
        if float(self.near_bone_refinement_step_deg) > float(self.refine_step_deg):
            raise ValueError("near_bone_refinement_step_deg must not exceed refine_step_deg")
        if int(self.rotation_vector_probe_count) < 4:
            raise ValueError("rotation_vector_probe_count must be at least 4")
        for name in ("rotation_vector_probe_step_deg", "directional_step_multiplier"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if float(self.directional_step_multiplier) <= 1.0:
            raise ValueError("directional_step_multiplier must be greater than 1")
        if int(self.directional_max_steps) < 1:
            raise ValueError("directional_max_steps must be at least 1")
        if int(self.directional_top_k) < 1:
            raise ValueError("directional_top_k must be at least 1")
        if not math.isfinite(float(self.directional_min_improvement)):
            raise ValueError("directional_min_improvement must be finite")
        twist_policy = str(self.bone_twist_policy).strip().lower()
        if twist_policy not in {"adaptive", "include", "exclude"}:
            raise ValueError("bone_twist_policy must be adaptive, include, or exclude")
        if not isinstance(self.bone_twist_overrides, dict):
            raise ValueError("bone_twist_overrides must be a mapping of bone name to policy")
        invalid_twist = {
            str(name): str(policy)
            for name, policy in self.bone_twist_overrides.items()
            if str(policy).strip().lower() not in {"adaptive", "include", "exclude"}
        }
        if invalid_twist:
            raise ValueError(
                "bone_twist_overrides contains invalid policies: "
                f"{invalid_twist}"
            )
        if str(self.multi_bone_mode).lower() not in {
            "single",
            "block_coordinate",
            "joint_beam",
        }:
            raise ValueError(
                "multi_bone_mode must be single, block_coordinate, or joint_beam"
            )
        if str(self.multi_bone_grouping).lower() not in {"window", "branch"}:
            raise ValueError("multi_bone_grouping must be window or branch")
        if int(self.multi_bone_block_size) < 2:
            raise ValueError("multi_bone_block_size must be at least 2")
        if int(self.multi_bone_rounds) < 1:
            raise ValueError("multi_bone_rounds must be at least 1")
        if not math.isfinite(float(self.multi_bone_step_deg)) or float(self.multi_bone_step_deg) <= 0.0:
            raise ValueError("multi_bone_step_deg must be finite and positive")
        if str(self.multi_bone_candidate_pattern).lower() not in {"star", "cube"}:
            raise ValueError("multi_bone_candidate_pattern must be star or cube")
        if int(self.multi_bone_beam_width) < 1:
            raise ValueError("multi_bone_beam_width must be at least 1")
        for name in (
            "multi_bone_probe_step_deg",
            "multi_bone_intermediate_step_deg",
            "multi_bone_polish_step_deg",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if int(self.multi_bone_probe_top_k) < 1:
            raise ValueError("multi_bone_probe_top_k must be positive")
        if not math.isfinite(float(self.multi_bone_probe_min_improvement)):
            raise ValueError("multi_bone_probe_min_improvement must be finite")
        if int(self.multi_bone_intermediate_rounds) < 1 or int(self.multi_bone_polish_rounds) < 1:
            raise ValueError("multi_bone intermediate/polish rounds must be at least 1")
        if float(self.multi_bone_intermediate_step_deg) > float(self.multi_bone_probe_step_deg):
            raise ValueError("multi_bone_intermediate_step_deg must not exceed multi_bone_probe_step_deg")
        if float(self.multi_bone_polish_step_deg) > float(self.multi_bone_intermediate_step_deg):
            raise ValueError("multi_bone_polish_step_deg must not exceed multi_bone_intermediate_step_deg")
        if self.hybrid_anatomical_weight > 0.0 and not self.anatomical_boxes_enabled:
            raise ValueError(
                "hybrid_anatomical_weight requires anatomical_boxes_enabled=True"
            )
        if self.semantic_dense_weight > 0.0 and not self.semantic_dense_enabled:
            raise ValueError("semantic_dense_weight requires semantic_dense_enabled=True")
        if self.semantic_dense_enabled and not self.semantic_enabled:
            raise ValueError("semantic_dense_enabled requires semantic_enabled=True")
        if int(self.semantic_batch_size) < 1:
            raise ValueError("semantic_batch_size must be positive")
        if self.semantic_global_batch_size is None:
            self.semantic_global_batch_size = int(self.semantic_batch_size)
        if self.semantic_dense_batch_size is None:
            self.semantic_dense_batch_size = int(self.semantic_batch_size)
        for name in ("semantic_global_batch_size", "semantic_dense_batch_size"):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be positive")
        if not math.isfinite(float(self.semantic_branch_bound_margin)) or float(self.semantic_branch_bound_margin) < 0.0:
            raise ValueError("semantic_branch_bound_margin must be finite and non-negative")
        if int(self.semantic_candidate_cache_max_entries) < 1:
            raise ValueError("semantic_candidate_cache_max_entries must be positive")
        if int(self.semantic_image_cache_max_entries) < 1:
            raise ValueError("semantic_image_cache_max_entries must be positive")
        if int(self.semantic_dense_grid_cache_max_entries) < 1:
            raise ValueError("semantic_dense_grid_cache_max_entries must be positive")
        if int(self.semantic_service_encoder_cache_max_entries) < 1:
            raise ValueError("semantic_service_encoder_cache_max_entries must be positive")
        if not str(self.semantic_service_cache_generation).strip():
            raise ValueError("semantic_service_cache_generation must be non-empty")
        if int(self.semantic_service_target_cache_max_entries) < 1:
            raise ValueError("semantic_service_target_cache_max_entries must be positive")
        if int(self.semantic_service_dense_target_cache_max_entries) < 1:
            raise ValueError(
                "semantic_service_dense_target_cache_max_entries must be positive"
            )
        if not 0 <= int(self.render_png_compression) <= 100:
            raise ValueError("render_png_compression must be between 0 and 100")
        if int(self.semantic_dense_local_radius) < 0:
            raise ValueError("semantic_dense_local_radius must be non-negative")
        if int(self.semantic_dense_view_index) < 0:
            raise ValueError("semantic_dense_view_index must be non-negative")
        if str(self.clip_warm_start).lower() not in {"bind", "previous", "frame0"}:
            raise ValueError("clip_warm_start must be bind, previous, or frame0")
        for name, value in (
            ("clip_velocity_weight", self.clip_velocity_weight),
            ("clip_acceleration_weight", self.clip_acceleration_weight),
            ("clip_body_translation_velocity_weight", self.clip_body_translation_velocity_weight),
            ("clip_body_translation_acceleration_weight", self.clip_body_translation_acceleration_weight),
            ("clip_contact_weight", self.clip_contact_weight),
            ("clip_loop_weight", self.clip_loop_weight),
            ("clip_loop_velocity_weight", self.clip_loop_velocity_weight),
            ("clip_motion_root_loop_velocity_weight", self.clip_motion_root_loop_velocity_weight),
        ):
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if str(self.render_lighting_mode).lower() not in {"flat_emission", "sun_above"}:
            raise ValueError("render_lighting_mode must be flat_emission or sun_above")
        for name, value in (
            ("render_sun_energy", self.render_sun_energy),
            ("render_sun_angle_deg", self.render_sun_angle_deg),
        ):
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if int(self.clip_rounds) < 1 or int(self.clip_refine_rounds) < 1:
            raise ValueError("clip rounds must be at least 1")
        if float(self.clip_coarse_step_deg) <= 0.0 or float(self.clip_refine_step_deg) <= 0.0:
            raise ValueError("clip proposal steps must be positive")
        if float(self.clip_refine_step_deg) > float(self.clip_coarse_step_deg):
            raise ValueError("clip_refine_step_deg must not exceed clip_coarse_step_deg")
        if int(self.clip_max_evaluations_per_axis) < 1:
            raise ValueError("clip_max_evaluations_per_axis must be positive")
        for name in (
            "clip_probe_step_deg",
            "clip_adaptive_step_deg",
            "clip_polish_step_deg",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if int(self.clip_probe_top_k) < 1:
            raise ValueError("clip_probe_top_k must be positive")
        if not math.isfinite(float(self.clip_probe_min_improvement)):
            raise ValueError("clip_probe_min_improvement must be finite")
        if int(self.clip_adaptive_block_size) < 2:
            raise ValueError("clip_adaptive_block_size must be at least 2")
        if int(self.clip_adaptive_beam_width) < 1:
            raise ValueError("clip_adaptive_beam_width must be positive")
        if int(self.clip_adaptive_rounds) < 1 or int(self.clip_polish_rounds) < 1:
            raise ValueError("clip adaptive/polish rounds must be at least 1")
        if float(self.clip_adaptive_step_deg) > float(self.clip_probe_step_deg):
            raise ValueError("clip_adaptive_step_deg must not exceed clip_probe_step_deg")
        if float(self.clip_polish_step_deg) > float(self.clip_adaptive_step_deg):
            raise ValueError("clip_polish_step_deg must not exceed clip_adaptive_step_deg")
        if not math.isfinite(float(self.clip_sensitivity_score_epsilon)) or float(self.clip_sensitivity_score_epsilon) < 0.0:
            raise ValueError("clip_sensitivity_score_epsilon must be finite and non-negative")
        if str(self.clip_candidate_mode).lower() not in {"local", "range_extremes"}:
            raise ValueError("clip_candidate_mode must be local or range_extremes")
        for name in ("clip_acceptance_margin", "clip_acceptance_relative_margin"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if int(self.render_worker_count) < 1:
            raise ValueError("render_worker_count must be positive")
        if not math.isfinite(float(self.clip_robust_scale_deg)) or float(self.clip_robust_scale_deg) <= 0.0:
            raise ValueError("clip_robust_scale_deg must be finite and positive")
        if int(self.anatomical_max_features) < 1:
            raise ValueError("anatomical_max_features must be at least 1")
        if float(self.anatomical_min_area_frac) > 1.0:
            raise ValueError("anatomical_min_area_frac must not exceed 1")
        if not math.isfinite(float(self.anatomical_laterality_center_margin_frac)) or not 0.0 <= float(self.anatomical_laterality_center_margin_frac) <= 0.5:
            raise ValueError("anatomical_laterality_center_margin_frac must be between 0 and 0.5")
        if str(self.anatomical_laterality_source).lower().strip() not in {"depth", "none"}:
            raise ValueError("anatomical_laterality_source must be 'depth' or 'none'")
        if str(self.anatomical_laterality_near_side).upper().strip() not in {"L", "R"}:
            raise ValueError("anatomical_laterality_near_side must be 'L' or 'R'")
        if int(self.frame0_fit_alpha_threshold) < 0 or int(self.frame0_fit_alpha_threshold) > 255:
            raise ValueError("frame0_fit_alpha_threshold must be between 0 and 255")
        if not math.isfinite(float(self.frame0_fit_margin)) or float(self.frame0_fit_margin) < 1.0:
            raise ValueError("frame0_fit_margin must be finite and at least 1")
        if int(self.frame0_fit_passes) < 1 or int(self.frame0_fit_passes) > 2:
            raise ValueError("frame0_fit_passes must be 1 or 2")
        if self.anatomical_center_weight + self.anatomical_extent_weight <= 0.0:
            raise ValueError("anatomical center/extent weights must have a positive sum")
        if str(self.ik_mode).lower() != "off" and not self.ik_enabled:
            raise ValueError(f"ik_mode={self.ik_mode!r} requires ik_enabled=True")
        if self.ik_target_search_enabled and (
            not self.ik_enabled or str(self.ik_mode).lower() == "off"
        ):
            raise ValueError(
                "ik_target_search_enabled requires ik_enabled=True and ik_mode other than 'off'"
            )
        if int(self.ik_chain_length) < 1:
            raise ValueError("ik_chain_length must be at least 1")
        if int(self.ik_iterations) < 1:
            raise ValueError("ik_iterations must be at least 1")
        if not math.isfinite(float(self.joint_free_deg)) or float(self.joint_free_deg) <= 0.0:
            raise ValueError("joint_free_deg must be finite and positive")
        for name in (
            "motion_root_forward_radius_body_lengths",
            "motion_root_lateral_radius_body_lengths",
            "motion_root_vertical_radius_body_lengths",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        motion_root_radii = {
            "forward": float(self.motion_root_forward_radius_body_lengths),
            "lateral": float(self.motion_root_lateral_radius_body_lengths),
            "vertical": float(self.motion_root_vertical_radius_body_lengths),
        }
        if self.motion_root_enabled:
            for axis in self.motion_root_axes:
                if motion_root_radii[axis] <= 0.0:
                    raise ValueError(
                        f"motion_root_{axis}_radius_body_lengths must be positive "
                        f"when {axis!r} is enabled"
                    )
        for name in (
            "motion_root_coarse_step_body_lengths",
            "motion_root_refine_step_body_lengths",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if self.motion_root_refine_step_body_lengths > self.motion_root_coarse_step_body_lengths:
            raise ValueError(
                "motion_root_refine_step_body_lengths must not exceed "
                "motion_root_coarse_step_body_lengths"
            )
        for name in (
            "motion_root_rotation_limit_deg",
            "motion_root_rotation_coarse_step_deg",
            "motion_root_rotation_refine_step_deg",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if self.motion_root_rotation_refine_step_deg > self.motion_root_rotation_coarse_step_deg:
            raise ValueError(
                "motion_root_rotation_refine_step_deg must not exceed "
                "motion_root_rotation_coarse_step_deg"
            )
        if self.motion_root_rotation_enabled and not self.motion_root_rotation_axes:
            raise ValueError(
                "motion_root_rotation_axes must be non-empty when "
                "motion_root_rotation_enabled is true"
            )
        if not self.motion_root_rotation_escape_angles_deg:
            raise ValueError("motion_root_rotation_escape_angles_deg must not be empty")
        if any(
            not math.isfinite(float(angle))
            or abs(float(angle)) > self.motion_root_rotation_limit_deg + 1e-8
            for angle in self.motion_root_rotation_escape_angles_deg
        ):
            raise ValueError(
                "motion_root_rotation_escape_angles_deg must stay within "
                "motion_root_rotation_limit_deg"
            )
        if int(self.motion_root_rotation_escape_top_k) < 1:
            raise ValueError("motion_root_rotation_escape_top_k must be positive")
        if int(self.motion_root_rotation_escape_relax_bone_count) < 0:
            raise ValueError(
                "motion_root_rotation_escape_relax_bone_count must be non-negative"
            )
        if int(self.motion_root_rotation_escape_relax_rounds) < 1:
            raise ValueError(
                "motion_root_rotation_escape_relax_rounds must be positive"
            )
        for name in (
            "motion_root_rotation_escape_relax_step_deg",
            "motion_root_rotation_escape_relax_refine_step_deg",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if (
            float(self.motion_root_rotation_escape_relax_refine_step_deg)
            > float(self.motion_root_rotation_escape_relax_step_deg)
        ):
            raise ValueError(
                "motion_root_rotation_escape_relax_refine_step_deg must not exceed "
                "motion_root_rotation_escape_relax_step_deg"
            )
        if not math.isfinite(float(self.motion_root_rotation_escape_min_image_improvement)):
            raise ValueError(
                "motion_root_rotation_escape_min_image_improvement must be finite"
            )
        for name in (
            "motion_root_magnitude_weight",
            "motion_root_velocity_weight",
            "motion_root_acceleration_weight",
            "motion_root_loop_weight",
            "motion_root_loop_velocity_weight",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        for name in (
            "motion_root_rotation_magnitude_weight",
            "motion_root_rotation_velocity_weight",
            "motion_root_rotation_acceleration_weight",
            "motion_root_rotation_loop_weight",
            "motion_root_rotation_loop_velocity_weight",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        for name in (
            "body_translation_radius_px",
            "body_translation_coarse_step_px",
            "body_translation_refine_step_px",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if float(self.body_translation_refine_step_px) > float(self.body_translation_coarse_step_px):
            raise ValueError("body_translation_refine_step_px must not exceed body_translation_coarse_step_px")
        rife_dir_set = self.rife_lab_frame_dir is not None
        rife_group_set = self.rife_lab_group is not None
        if rife_dir_set != rife_group_set:
            raise ValueError("rife_lab_frame_dir and rife_lab_group must be set together")
        def_dir_set = self.def_lab_frame_dir is not None
        def_group_set = self.def_lab_group is not None
        if def_dir_set != def_group_set:
            raise ValueError("def_lab_frame_dir and def_lab_group must be set together")
        if rife_dir_set and def_dir_set:
            raise ValueError("cannot enable RIFE interpolation and authentic DEF source together")
        reserved_truth = {
            "frames_ground_truth",
            "frames_ground_truth_shadow_culled",
            "frames_ground_truth_depth_vda",
        }
        if rife_dir_set or def_dir_set:
            frames = _reload_source_frame_helpers()
        if rife_dir_set:
            self.rife_lab_frame_dir = Path(self.rife_lab_frame_dir)
            plan = frames.normalize_rife_group_plan(self.rife_lab_group, self.rife_expected_count)
            if plan is None:
                raise ValueError("rife_lab_frame_dir and rife_lab_group must be set together")
            groups, counts = plan
            self.rife_lab_group = groups if len(groups) > 1 else groups[0]
            if counts[0] is None:
                self.rife_expected_count = None
            else:
                self.rife_expected_count = counts if len(counts) > 1 else counts[0]
            if Path(self.target_frame_dir).name in reserved_truth:
                raise ValueError("RIFE source must not overwrite frames_ground_truth")
            if Path(self.shadow_culled_frame_dir).name in reserved_truth:
                raise ValueError("RIFE source must not overwrite frames_ground_truth_shadow_culled")
            if Path(self.target_depth_dir).name in reserved_truth:
                raise ValueError("RIFE source must not overwrite frames_ground_truth_depth_vda")
            if not math.isfinite(float(self.depth_video_fps)) or float(self.depth_video_fps) <= 0.0:
                raise ValueError("depth_video_fps must be finite and positive")
            if self.rife_nn_upscale_meta is None:
                raise ValueError(
                    "RIFE pose-fit requires rife_nn_upscale_meta so interpolated plates "
                    "land on the recorded nn-upscale canvas; native 450x400 plates are not "
                    "interchangeable with the 1098x876 camera"
                )
            self.rife_nn_upscale_meta = Path(self.rife_nn_upscale_meta)
            if self.rife_camera_fit_path is not None:
                raise ValueError(
                    "rife_camera_fit_path is no longer used. RIFE frames are nn-upscaled onto "
                    "the pose-fit canvas, so camera_fit_path stays the existing 1098x876 "
                    "contract. Do not scale pxPerWorld by native plate width."
                )
        if def_dir_set:
            self.def_lab_frame_dir = Path(self.def_lab_frame_dir)
            plan = frames.normalize_def_group_plan(self.def_lab_group, self.def_expected_count)
            if plan is None:
                raise ValueError("def_lab_frame_dir and def_lab_group must be set together")
            groups, counts = plan
            allow_idle_only = len(groups) == 1 and groups[0] == frames.IDLE_GROUP
            frames.require_authentic_def_pose_groups(
                groups,
                sequence_label="authentic DEF pose-fit",
                allow_idle_only=allow_idle_only,
            )
            self.def_lab_group = groups if len(groups) > 1 else groups[0]
            if counts[0] is None:
                raise ValueError("authentic DEF source requires def_expected_count")
            self.def_expected_count = counts if len(counts) > 1 else counts[0]
            if Path(self.target_frame_dir).name in reserved_truth:
                raise ValueError("authentic DEF sequence must not overwrite frames_ground_truth")
            if Path(self.shadow_culled_frame_dir).name in reserved_truth:
                raise ValueError("authentic DEF sequence must not overwrite frames_ground_truth_shadow_culled")
            if Path(self.target_depth_dir).name in reserved_truth:
                raise ValueError("authentic DEF sequence must not overwrite frames_ground_truth_depth_vda")
            if Path(self.target_frame_dir).name.startswith("frames_rife"):
                raise ValueError("authentic DEF sequence must not write into a RIFE target_frame_dir")
            if not math.isfinite(float(self.depth_video_fps)) or float(self.depth_video_fps) <= 0.0:
                raise ValueError("depth_video_fps must be finite and positive")
            if self.def_nn_upscale_meta is None:
                raise ValueError(
                    "authentic DEF pose-fit requires def_nn_upscale_meta so native plates "
                    "land on the recorded nn-upscale canvas; native 450x400 plates are not "
                    "interchangeable with the 1098x876 camera"
                )
            self.def_nn_upscale_meta = Path(self.def_nn_upscale_meta)

    def namespace(self) -> dict[str, Any]:
        pilot = Path(self.pilot_dir) if self.pilot_dir is not None else self.root / "artifacts/roc_pose_pipeline/smart_rig_move_pilot"
        tool = self.root / "tools/homm3_silhouette_pose_fit"
        camera_fit = Path(self.camera_fit_path) if self.camera_fit_path is not None else pilot / "roc_sprite_camera_fit.json"

        def pilot_path(value: str | Path) -> Path:
            path = Path(value)
            return path if path.is_absolute() else pilot / path

        return {
            "ROOT": self.root,
            "TOOL": tool,
            "PILOT": pilot,
            "SRC_GLB": self.src_glb,
            "MESHY_RIGIDIZATION_REPORT": self.meshy_rigidization_report,
            "REQUIRE_MESHY_RIGIDIZATION": self.require_meshy_rigidization,
            "UNIT_NAME": self.unit_name,
            "UNIT_SID": self.unit_sid,
            "ANIMATION_NAME": self.animation_name,
            "RAW_ANIMATION_TARGET_FRAMES": pilot_path(self.target_frame_dir),
            "ANIMATION_TARGET_FRAMES": pilot_path(self.shadow_culled_frame_dir),
            "TARGET_FRAMES": pilot_path(self.shadow_culled_frame_dir),
            "TARGET_DEPTH": pilot_path(self.target_depth_dir),
            "CAMERA_FIT": camera_fit,
            "RIFE_LAB_FRAME_DIR": None if self.rife_lab_frame_dir is None else Path(self.rife_lab_frame_dir),
            "RIFE_LAB_GROUP": self.rife_lab_group,
            "RIFE_EXPECTED_COUNT": self.rife_expected_count,
            "RIFE_NN_UPSCALE_META": None if self.rife_nn_upscale_meta is None else Path(self.rife_nn_upscale_meta),
            "RIFE_CAMERA_FIT_PATH": None if self.rife_camera_fit_path is None else Path(self.rife_camera_fit_path),
            "DEF_LAB_FRAME_DIR": None if self.def_lab_frame_dir is None else Path(self.def_lab_frame_dir),
            "DEF_LAB_GROUP": self.def_lab_group,
            "DEF_EXPECTED_COUNT": self.def_expected_count,
            "DEF_NN_UPSCALE_META": None if self.def_nn_upscale_meta is None else Path(self.def_nn_upscale_meta),
            "DEPTH_VIDEO_FPS": float(self.depth_video_fps),
            "WORKER": tool / "roc_chroma_match_worker.py",
            "BLENDER": resolve_pose_fit_blender(),
            "WIDTH": 768,
            "HEIGHT": 683,
            "SCORE_MODE": self.score_mode,
            "SEMANTIC_ONLY": self.semantic_only,
            "SEMANTIC_ENABLED": self.semantic_enabled,
            "SEMANTIC_MODEL_ID": self.semantic_model_id,
            "SEMANTIC_EMBEDDING_LAYER": self.semantic_embedding_layer,
            "SEMANTIC_EMBEDDING_LAYERS": self.semantic_embedding_layers,
            "SEMANTIC_POOLING": self.semantic_pooling,
            "SEMANTIC_BATCH_SIZE": self.semantic_batch_size,
            "SEMANTIC_GLOBAL_BATCH_SIZE": self.semantic_global_batch_size,
            "SEMANTIC_DENSE_BATCH_SIZE": self.semantic_dense_batch_size,
            "SEMANTIC_SUBJECT_CROP": self.semantic_subject_crop,
            "SEMANTIC_SUBJECT_PADDING_FRAC": self.semantic_subject_padding_frac,
            "SEMANTIC_DENSE_ENABLED": self.semantic_dense_enabled,
            "SEMANTIC_DENSE_MODEL_ID": self.semantic_dense_model_id,
            "SEMANTIC_DENSE_EMBEDDING_LAYERS": self.semantic_dense_embedding_layers,
            "SEMANTIC_DENSE_WEIGHT": self.semantic_dense_weight,
            "SEMANTIC_DENSE_LOCAL_RADIUS": self.semantic_dense_local_radius,
            "SEMANTIC_DENSE_POSITION_WEIGHT": self.semantic_dense_position_weight,
            "SEMANTIC_DENSE_VIEW_INDEX": self.semantic_dense_view_index,
            "SEMANTIC_MULTIVIEW": self.semantic_multiview,
            "SEMANTIC_VIEW_ANGLES_DEG": self.semantic_view_angles_deg,
            "SEMANTIC_VIEW_ELEVATIONS_DEG": self.semantic_view_elevations_deg,
            "SEMANTIC_VIEW_WEIGHTS": self.semantic_view_weights,
            "HYBRID_SEMANTIC_WEIGHT": self.hybrid_semantic_weight,
            "HYBRID_DEPTH_WEIGHT": self.hybrid_depth_weight,
            "HYBRID_GEOMETRY_ENABLED": self.hybrid_geometry_enabled,
            "HYBRID_GEOMETRY_WEIGHT": self.hybrid_geometry_weight,
            "RENDER_DEPTH_FOR_SCORING": self.render_depth_for_scoring,
            "RENDER_RESULT_IN_MEMORY": self.render_result_in_memory,
            "RENDER_PNG_COMPRESSION": self.render_png_compression,
            "RENDER_LIGHTING_MODE": self.render_lighting_mode,
            "RENDER_SUN_ENERGY": self.render_sun_energy,
            "RENDER_SUN_AZIMUTH_DEG": self.render_sun_azimuth_deg,
            "RENDER_SUN_ELEVATION_DEG": self.render_sun_elevation_deg,
            "RENDER_SUN_ANGLE_DEG": self.render_sun_angle_deg,
            "INCREMENTAL_POSE_APPLICATION": self.incremental_pose_application,
            "TRIAGE_ENABLED": self.triage_enabled,
            "TRIAGE_SILHOUETTE_ENABLED": self.triage_silhouette_enabled,
            "TRIAGE_SILHOUETTE_HEURISTIC_ENABLED": self.triage_silhouette_heuristic_enabled,
            "TRIAGE_SILHOUETTE_FLOOR": self.triage_silhouette_floor,
            "TRIAGE_SILHOUETTE_KEEP_FRACTION": self.triage_silhouette_keep_fraction,
            "TRIAGE_SILHOUETTE_MIN_CANDIDATES": self.triage_silhouette_min_candidates,
            "TRIAGE_SILHOUETTE_MAX_CANDIDATES": self.triage_silhouette_max_candidates,
            "PROXY_ENABLED": self.proxy_enabled,
            "PROXY_DEVICE": self.proxy_device,
            "PROXY_MIN_CANDIDATES": self.proxy_min_candidates,
            "PROXY_PROTECTED_STAGES": (
                tuple(part.strip() for part in self.proxy_protected_stages.split(",") if part.strip())
                if isinstance(self.proxy_protected_stages, str)
                else tuple(str(part).strip() for part in self.proxy_protected_stages if str(part).strip())
            ),
            "PROXY_AUDIT_ENABLED": self.proxy_audit_enabled,
            "PROXY_AUDIT_FRACTION": self.proxy_audit_fraction,
            "PROXY_AUDIT_MAX_CANDIDATES": self.proxy_audit_max_candidates,
            "PROXY_AUDIT_REGRET_TOLERANCE": self.proxy_audit_regret_tolerance,
            "PROXY_GPU_TENSOR_CACHE_ENABLED": self.proxy_gpu_tensor_cache_enabled,
            "PROXY_GPU_ASSET_CACHE_MAX_ENTRIES": self.proxy_gpu_asset_cache_max_entries,
            "PROXY_RESOLUTION": self.proxy_resolution,
            "PROXY_LEVEL0_ENABLED": self.proxy_level0_enabled,
            "PROXY_LEVEL0_POINTS_PER_BONE": self.proxy_level0_points_per_bone,
            "PROXY_LEVEL0_KEEP_FRACTION": self.proxy_level0_keep_fraction,
            "PROXY_LEVEL0_MIN_CANDIDATES": self.proxy_level0_min_candidates,
            "PROXY_LEVEL0_MAX_CANDIDATES": self.proxy_level0_max_candidates,
            "PROXY_LEVEL1_ENABLED": self.proxy_level1_enabled,
            "PROXY_LEVEL1_MAX_VERTICES": self.proxy_level1_max_vertices,
            "PROXY_LEVEL1_KEEP_FRACTION": self.proxy_level1_keep_fraction,
            "PROXY_LEVEL1_MIN_CANDIDATES": self.proxy_level1_min_candidates,
            "PROXY_LEVEL1_MAX_CANDIDATES": self.proxy_level1_max_candidates,
            "PROXY_POINT_RADIUS": self.proxy_point_radius,
            "PROXY_TARGET_ALPHA_THRESHOLD": self.proxy_target_alpha_threshold,
            "PROXY_CENTROID_WEIGHT": self.proxy_centroid_weight,
            "PROXY_OCCUPANCY_WEIGHT": self.proxy_occupancy_weight,
            "GPU_POSE_ADVISOR_ENABLED": self.gpu_pose_advisor_enabled,
            "GPU_POSE_ADVISOR_DEVICE": self.gpu_pose_advisor_device,
            "GPU_POSE_ADVISOR_DIRECTION_ENABLED": self.gpu_pose_advisor_direction_enabled,
            "GPU_POSE_ADVISOR_ROOT_ENABLED": self.gpu_pose_advisor_root_enabled,
            "GPU_POSE_ADVISOR_MAX_POINTS": self.gpu_pose_advisor_max_points,
            "GPU_POSE_ADVISOR_SDF_WEIGHT": self.gpu_pose_advisor_sdf_weight,
            "GPU_POSE_ADVISOR_CENTROID_WEIGHT": self.gpu_pose_advisor_centroid_weight,
            "GPU_POSE_ADVISOR_EXTENT_WEIGHT": self.gpu_pose_advisor_extent_weight,
            "GPU_POSE_ADVISOR_MIN_GRADIENT_NORM": self.gpu_pose_advisor_min_gradient_norm,
            "GPU_POSE_ADVISOR_MEDIUM_SENSITIVITY_RATIO": self.gpu_pose_advisor_medium_sensitivity_ratio,
            "GPU_POSE_ADVISOR_HIGH_SENSITIVITY_RATIO": self.gpu_pose_advisor_high_sensitivity_ratio,
            "GPU_POSE_ADVISOR_ORTHOGONAL_COUNT": self.gpu_pose_advisor_orthogonal_count,
            "GPU_POSE_ADVISOR_ROOT_HYPOTHESIS_COUNT": self.gpu_pose_advisor_root_hypothesis_count,
            "GPU_POSE_ADVISOR_ROOT_KEEP": self.gpu_pose_advisor_root_keep,
            "GPU_POSE_ADVISOR_SEED": self.gpu_pose_advisor_seed,
            "GPU_POSE_ADVISOR_FALLBACK_ROTATION_VECTORS": self.gpu_pose_advisor_fallback_rotation_vectors,
            "SEMANTIC_BRANCH_BOUND_ENABLED": self.semantic_branch_bound_enabled,
            "SEMANTIC_BRANCH_BOUND_MARGIN": self.semantic_branch_bound_margin,
            "SEMANTIC_CANDIDATE_CACHE_ENABLED": self.semantic_candidate_cache_enabled,
            "SEMANTIC_CANDIDATE_CACHE_MAX_ENTRIES": self.semantic_candidate_cache_max_entries,
            "SEMANTIC_IMAGE_CACHE_MAX_ENTRIES": self.semantic_image_cache_max_entries,
            "SEMANTIC_DENSE_GRID_CACHE_MAX_ENTRIES": self.semantic_dense_grid_cache_max_entries,
            "SEMANTIC_SERVICE_ENABLED": self.semantic_service_enabled,
            "SEMANTIC_SERVICE_CACHE_GENERATION": self.semantic_service_cache_generation,
            "SEMANTIC_SERVICE_ENCODER_CACHE_MAX_ENTRIES": self.semantic_service_encoder_cache_max_entries,
            "SEMANTIC_SERVICE_TARGET_CACHE_MAX_ENTRIES": self.semantic_service_target_cache_max_entries,
            "SEMANTIC_SERVICE_DENSE_TARGET_CACHE_MAX_ENTRIES": self.semantic_service_dense_target_cache_max_entries,
            "SILHOUETTE_DEPTH_WEIGHT": self.silhouette_depth_weight,
            "BLUE_ZONE_PENALTY": self.blue_zone_penalty,
            "RED_ZONE_PENALTY": self.red_zone_penalty,
            "SILHOUETTE_EDGE_BONUS": self.silhouette_edge_bonus,
            "REVERSE_PROFILE_ENABLED": self.reverse_profile_enabled,
            "REVERSE_PROFILE_WEIGHT": self.reverse_profile_weight,
            "PROFILE_HALF_BIAS": self.profile_half_bias,
            "REVERSE_RAW_TARGET_FRAMES": pilot_path(self.reverse_profile_raw_frame_dir),
            "REVERSE_TARGET_FRAMES": pilot_path(self.reverse_profile_frame_dir),
            "REVERSE_TARGET_DEPTH": pilot_path(self.reverse_profile_depth_dir),
            "ACTION_CAMERA_ANGLE_DEG": self.action_camera_angle_deg,
            "ACTION_CAMERA_ELEVATION_DEG": self.action_camera_elevation_deg,
            "DETECT_PROFILE_ENABLED": self.detect_profile_enabled,
            "MESH_ORIENTATION_MODE": self.mesh_orientation_mode,
            "PROFILE_SAMPLES": self.profile_samples,
            "SEMANTIC_TEXT_ENABLED": self.semantic_text_enabled,
            "SEMANTIC_TEXT_PROMPT": self.semantic_text_prompt,
            "HYBRID_TEXT_WEIGHT": self.hybrid_text_weight,
            "SEMANTIC_NEGATIVE_TEXT_ENABLED": self.semantic_negative_text_enabled,
            "SEMANTIC_NEGATIVE_TEXT_PROMPT": self.semantic_negative_text_prompt,
            "HYBRID_NEGATIVE_TEXT_WEIGHT": self.hybrid_negative_text_weight,
            "LIVE_PREVIEW": self.live_preview,
            "PREVIEW_EVERY": self.preview_every,
            "ANATOMICAL_BOXES_ENABLED": self.anatomical_boxes_enabled,
            "ANATOMICAL_PART_WEIGHT": self.anatomical_part_weight,
            "HYBRID_ANATOMICAL_WEIGHT": self.hybrid_anatomical_weight,
            "ANATOMICAL_MAX_FEATURES": self.anatomical_max_features,
            "ANATOMICAL_MIN_AREA_FRAC": self.anatomical_min_area_frac,
            "ANATOMICAL_CENTER_WEIGHT": self.anatomical_center_weight,
            "ANATOMICAL_EXTENT_WEIGHT": self.anatomical_extent_weight,
            "ANATOMICAL_LATERALITY_ENABLED": self.anatomical_laterality_enabled,
            "ANATOMICAL_LATERALITY_SOURCE": self.anatomical_laterality_source,
            "ANATOMICAL_LATERALITY_NEAR_SIDE": self.anatomical_laterality_near_side,
            "ANATOMICAL_LATERALITY_DEPTH_MARGIN": self.anatomical_laterality_depth_margin,
            "ANATOMICAL_LATERALITY_CENTER_MARGIN_FRAC": self.anatomical_laterality_center_margin_frac,
            "SHOW_ANATOMICAL_BOXES": self.show_anatomical_boxes,
            "JOINT_FREE_DEG": self.joint_free_deg,
            "MOTION_ROOT_ENABLED": self.motion_root_enabled,
            "MOTION_ROOT_AXES": self.motion_root_axes,
            "MOTION_ROOT_FORWARD_RADIUS_BODY_LENGTHS": self.motion_root_forward_radius_body_lengths,
            "MOTION_ROOT_LATERAL_RADIUS_BODY_LENGTHS": self.motion_root_lateral_radius_body_lengths,
            "MOTION_ROOT_VERTICAL_RADIUS_BODY_LENGTHS": self.motion_root_vertical_radius_body_lengths,
            "MOTION_ROOT_COARSE_STEP_BODY_LENGTHS": self.motion_root_coarse_step_body_lengths,
            "MOTION_ROOT_REFINE_STEP_BODY_LENGTHS": self.motion_root_refine_step_body_lengths,
            "MOTION_ROOT_MAGNITUDE_WEIGHT": self.motion_root_magnitude_weight,
            "MOTION_ROOT_VELOCITY_WEIGHT": self.motion_root_velocity_weight,
            "MOTION_ROOT_ACCELERATION_WEIGHT": self.motion_root_acceleration_weight,
            "MOTION_ROOT_LOOP_WEIGHT": self.motion_root_loop_weight,
            "MOTION_ROOT_LOOP_VELOCITY_WEIGHT": self.motion_root_loop_velocity_weight,
            "MOTION_ROOT_COUPLED_BLOCKS_ENABLED": self.motion_root_coupled_blocks_enabled,
            "MOTION_ROOT_ROTATION_ENABLED": self.motion_root_rotation_enabled,
            "MOTION_ROOT_ROTATION_BASIS": self.motion_root_rotation_basis,
            "MOTION_ROOT_ROTATION_AXES": self.motion_root_rotation_axes,
            "MOTION_ROOT_ROTATION_LIMIT_DEG": self.motion_root_rotation_limit_deg,
            "MOTION_ROOT_ROTATION_COARSE_STEP_DEG": self.motion_root_rotation_coarse_step_deg,
            "MOTION_ROOT_ROTATION_REFINE_STEP_DEG": self.motion_root_rotation_refine_step_deg,
            "MOTION_ROOT_ROTATION_ESCAPE_ENABLED": self.motion_root_rotation_escape_enabled,
            "MOTION_ROOT_ROTATION_ESCAPE_AXES": self.motion_root_rotation_escape_axes,
            "MOTION_ROOT_ROTATION_ESCAPE_ANGLES_DEG": self.motion_root_rotation_escape_angles_deg,
            "MOTION_ROOT_ROTATION_ESCAPE_TOP_K": self.motion_root_rotation_escape_top_k,
            "MOTION_ROOT_ROTATION_ESCAPE_FORCE_IMAGE_BEST": self.motion_root_rotation_escape_force_image_best,
            "MOTION_ROOT_ROTATION_ESCAPE_MIN_IMAGE_IMPROVEMENT": self.motion_root_rotation_escape_min_image_improvement,
            "MOTION_ROOT_ROTATION_ESCAPE_RELAX_ENABLED": self.motion_root_rotation_escape_relax_enabled,
            "MOTION_ROOT_ROTATION_ESCAPE_RELAX_BONE_COUNT": self.motion_root_rotation_escape_relax_bone_count,
            "MOTION_ROOT_ROTATION_ESCAPE_RELAX_ROUNDS": self.motion_root_rotation_escape_relax_rounds,
            "MOTION_ROOT_ROTATION_ESCAPE_RELAX_STEP_DEG": self.motion_root_rotation_escape_relax_step_deg,
            "MOTION_ROOT_ROTATION_ESCAPE_RELAX_REFINE_STEP_DEG": self.motion_root_rotation_escape_relax_refine_step_deg,
            "MOTION_ROOT_ROTATION_MAGNITUDE_WEIGHT": self.motion_root_rotation_magnitude_weight,
            "MOTION_ROOT_ROTATION_VELOCITY_WEIGHT": self.motion_root_rotation_velocity_weight,
            "MOTION_ROOT_ROTATION_ACCELERATION_WEIGHT": self.motion_root_rotation_acceleration_weight,
            "MOTION_ROOT_ROTATION_LOOP_WEIGHT": self.motion_root_rotation_loop_weight,
            "MOTION_ROOT_ROTATION_LOOP_VELOCITY_WEIGHT": self.motion_root_rotation_loop_velocity_weight,
            "MOTION_ROOT_ROTATION_COUPLED_BLOCKS_ENABLED": self.motion_root_rotation_coupled_blocks_enabled,
            "BODY_TRANSLATION_ENABLED": self.body_translation_enabled,
            "BODY_TRANSLATION_RADIUS_PX": self.body_translation_radius_px,
            "BODY_TRANSLATION_COARSE_STEP_PX": self.body_translation_coarse_step_px,
            "BODY_TRANSLATION_REFINE_STEP_PX": self.body_translation_refine_step_px,
            "COARSE_STEP_DEG": self.coarse_step_deg,
            "REFINE_STEP_DEG": self.refine_step_deg,
            "COMPOUND_CD_ROUNDS": self.compound_cd_rounds,
            "COMPOUND_PAIR_STEP_MULT": self.compound_pair_step_mult,
            "SEARCH_AXES": self.search_axes,
            "EXCLUDE_BONE_ROLL": self.exclude_bone_roll,
            "ROTATION_VECTOR_SEARCH_ENABLED": self.rotation_vector_search_enabled,
            "ROTATION_VECTOR_PROBE_COUNT": self.rotation_vector_probe_count,
            "ROTATION_VECTOR_PROBE_STEP_DEG": self.rotation_vector_probe_step_deg,
            "DIRECTIONAL_CONTINUATION_ENABLED": self.directional_continuation_enabled,
            "DIRECTIONAL_MAX_STEPS": self.directional_max_steps,
            "DIRECTIONAL_STEP_MULTIPLIER": self.directional_step_multiplier,
            "DIRECTIONAL_TOP_K": self.directional_top_k,
            "DIRECTIONAL_MIN_IMPROVEMENT": self.directional_min_improvement,
            "BONE_TWIST_POLICY": self.bone_twist_policy,
            "BONE_TWIST_OVERRIDES": dict(self.bone_twist_overrides),
            "SKIP_TINY_BONES": self.skip_tiny_bones,
            "SEMANTIC_OPTIMIZER": self.semantic_optimizer,
            "CLIP_OPTIMIZATION_ENABLED": self.clip_optimization_enabled,
            "CLIP_WARM_START": self.clip_warm_start,
            "CLIP_ROUNDS": self.clip_rounds,
            "CLIP_REFINE_ROUNDS": self.clip_refine_rounds,
            "CLIP_REFINE_ACCEPTED_ONLY": self.clip_refine_accepted_only,
            "CLIP_VELOCITY_WEIGHT": self.clip_velocity_weight,
            "CLIP_ACCELERATION_WEIGHT": self.clip_acceleration_weight,
            "CLIP_CONTACT_WEIGHT": self.clip_contact_weight,
            "CLIP_LOOP_WEIGHT": self.clip_loop_weight,
            "CLIP_LOOP_VELOCITY_WEIGHT": self.clip_loop_velocity_weight,
            "CLIP_LOOP_ENABLED": self.clip_loop_enabled,
            "CLIP_MOTION_ROOT_MAGNITUDE_WEIGHT": self.clip_motion_root_magnitude_weight,
            "CLIP_MOTION_ROOT_VELOCITY_WEIGHT": self.clip_motion_root_velocity_weight,
            "CLIP_MOTION_ROOT_ACCELERATION_WEIGHT": self.clip_motion_root_acceleration_weight,
            "CLIP_MOTION_ROOT_LOOP_WEIGHT": self.clip_motion_root_loop_weight,
            "CLIP_MOTION_ROOT_LOOP_VELOCITY_WEIGHT": self.clip_motion_root_loop_velocity_weight,
            "CLIP_BODY_TRANSLATION_VELOCITY_WEIGHT": self.clip_body_translation_velocity_weight,
            "CLIP_BODY_TRANSLATION_ACCELERATION_WEIGHT": self.clip_body_translation_acceleration_weight,
            "CLIP_CONTACT_BONES": self.clip_contact_bones,
            "CLIP_ROBUST_SCALE_DEG": self.clip_robust_scale_deg,
            "CLIP_COARSE_STEP_DEG": self.clip_coarse_step_deg,
            "CLIP_REFINE_STEP_DEG": self.clip_refine_step_deg,
            "CLIP_MAX_EVALUATIONS_PER_AXIS": self.clip_max_evaluations_per_axis,
            "CLIP_CANDIDATE_MODE": self.clip_candidate_mode,
            "CLIP_ACCEPTANCE_MARGIN": self.clip_acceptance_margin,
            "CLIP_ACCEPTANCE_RELATIVE_MARGIN": self.clip_acceptance_relative_margin,
            "CLIP_PREVIEW_CANDIDATES": self.clip_preview_candidates,
            "CLIP_BATCH_CANDIDATES": self.clip_batch_candidates,
            "CLIP_PROBE_ENABLED": self.clip_probe_enabled,
            "CLIP_PROBE_STEP_DEG": self.clip_probe_step_deg,
            "CLIP_PROBE_TOP_K": self.clip_probe_top_k,
            "CLIP_PROBE_MIN_IMPROVEMENT": self.clip_probe_min_improvement,
            "CLIP_ADAPTIVE_BLOCKS_ENABLED": self.clip_adaptive_blocks_enabled,
            "CLIP_ADAPTIVE_BLOCK_SIZE": self.clip_adaptive_block_size,
            "CLIP_ADAPTIVE_ROUNDS": self.clip_adaptive_rounds,
            "CLIP_ADAPTIVE_STEP_DEG": self.clip_adaptive_step_deg,
            "CLIP_ADAPTIVE_BEAM_WIDTH": self.clip_adaptive_beam_width,
            "CLIP_POLISH_ENABLED": self.clip_polish_enabled,
            "CLIP_POLISH_ROUNDS": self.clip_polish_rounds,
            "CLIP_POLISH_STEP_DEG": self.clip_polish_step_deg,
            "CLIP_SENSITIVITY_ENABLED": self.clip_sensitivity_enabled,
            "CLIP_SENSITIVITY_SCORE_EPSILON": self.clip_sensitivity_score_epsilon,
            "CLIP_POLISH_INCLUDE_NEIGHBORS": self.clip_polish_include_neighbors,
            "PARALLEL_CANDIDATE_RENDERING": self.parallel_candidate_rendering,
            "RENDER_WORKER_COUNT": self.render_worker_count,
            "RUN_FRAME0_PILOT": self.run_frame0_pilot,
            "FRAME_INDICES": self.frame_indices,
            "SEED_FROM_PREVIOUS": self.seed_from_previous,
            "SEARCH_SCALE": self.mesh_scale,
            "SEARCH_BUFFER_SCALE": self.search_scale,
            "AUTO_FRAME0_CAMERA_FIT": self.auto_frame0_camera_fit,
            "FRAME0_FIT_ALPHA_THRESHOLD": self.frame0_fit_alpha_threshold,
            "FRAME0_FIT_MARGIN": self.frame0_fit_margin,
            "FRAME0_FIT_PASSES": self.frame0_fit_passes,
            "MULTI_AXIS_MODE": self.multi_axis_mode,
            "AXIS_PROBE_FIRST": self.axis_probe_first,
            "COMPOUND_PAIR_STEP_MULT": self.compound_pair_step_mult,
            "BONE_ORDER_MODE": self.bone_order_mode,
            "BRANCH_WALK_CAMERA_BIAS": self.branch_walk_camera_bias,
            "BONE_ORDER": self.bone_order,
            "SEARCH_BONES": self.search_bones,
            "INCLUDE_UNLISTED_SEARCH_BONES": self.include_unlisted_search_bones,
            "NEAR_BONE_REFINEMENT_ENABLED": self.near_bone_refinement_enabled,
            "NEAR_BONE_REFINEMENT_STEP_DEG": self.near_bone_refinement_step_deg,
            "MULTI_BONE_MODE": self.multi_bone_mode,
            "MULTI_BONE_GROUPING": self.multi_bone_grouping,
            "MULTI_BONE_BLOCK_SIZE": self.multi_bone_block_size,
            "MULTI_BONE_ROUNDS": self.multi_bone_rounds,
            "MULTI_BONE_STEP_DEG": self.multi_bone_step_deg,
            "MULTI_BONE_CANDIDATE_PATTERN": self.multi_bone_candidate_pattern,
            "MULTI_BONE_BEAM_WIDTH": self.multi_bone_beam_width,
            "MULTI_BONE_PROBE_ENABLED": self.multi_bone_probe_enabled,
            "MULTI_BONE_PROBE_STEP_DEG": self.multi_bone_probe_step_deg,
            "MULTI_BONE_PROBE_TOP_K": self.multi_bone_probe_top_k,
            "MULTI_BONE_PROBE_MIN_IMPROVEMENT": self.multi_bone_probe_min_improvement,
            "MULTI_BONE_ADAPTIVE_BLOCKS_ENABLED": self.multi_bone_adaptive_blocks_enabled,
            "MULTI_BONE_INTERMEDIATE_STEP_DEG": self.multi_bone_intermediate_step_deg,
            "MULTI_BONE_INTERMEDIATE_ROUNDS": self.multi_bone_intermediate_rounds,
            "MULTI_BONE_POLISH_ENABLED": self.multi_bone_polish_enabled,
            "MULTI_BONE_POLISH_ROUNDS": self.multi_bone_polish_rounds,
            "MULTI_BONE_POLISH_STEP_DEG": self.multi_bone_polish_step_deg,
            "IK_ENABLED": self.ik_enabled,
            "IK_MODE": self.ik_mode,
            "IK_BONES": self.ik_bones,
            "IK_TARGETS": self.ik_targets or {},
            "IK_AUTO_TARGETS": self.ik_auto_targets,
            "IK_TARGET_SOURCE": self.ik_target_source,
            "IK_TARGET_SEARCH_ENABLED": self.ik_target_search_enabled,
            "IK_TARGET_SEARCH_ONLY": self.ik_target_search_only,
            "IK_TARGET_SEARCH_BONES": self.ik_target_search_bones,
            "IK_TARGET_COARSE_STEP_PX": self.ik_target_coarse_step_px,
            "IK_TARGET_REFINE_STEP_PX": self.ik_target_refine_step_px,
            "IK_TARGET_SEARCH_RADIUS_PX": self.ik_target_search_radius_px,
            "IK_TARGET_MIN_IMPROVEMENT": self.ik_target_min_improvement,
            "IK_CHAIN_LENGTH": self.ik_chain_length,
            "IK_ITERATIONS": self.ik_iterations,
            "IK_STRENGTH": self.ik_strength,
            "IK_DEPTH": self.ik_depth,
            "MATCH_OUT": pilot / self.match_dir_name,
        }


@dataclass
class RocHybridExperiment:
    config: RocHybridConfig
    namespace: dict[str, Any]
    _closed: bool = False

    def summary(self) -> dict[str, Any]:
        ns = self.namespace
        return {
            "unit": self.config.unit_name,
            "animation": self.config.animation_name,
            "pilot": str(self.config.pilot_dir or (self.config.root / "artifacts/roc_pose_pipeline/smart_rig_move_pilot")),
            "mesh": str(self.config.src_glb),
            "meshResolved": str(Path(self.config.src_glb).expanduser().resolve()),
            "meshUsedByBlender": ns.get("init_result", {}).get("sourceMesh"),
            "meshUsedByBlenderSha256": ns.get("init_result", {}).get("sourceMeshSha256"),
            "meshyRigidizationReport": str(self.config.meshy_rigidization_report) if self.config.meshy_rigidization_report else None,
            "requireMeshyRigidization": self.config.require_meshy_rigidization,
            "frames": len(self.config.frame_indices),
            "scoreMode": ns.get("SCORE_MODE"),
            "semanticModel": ns.get("SEMANTIC_MODEL_ID"),
            "semanticEmbeddingLayer": ns.get("SEMANTIC_EMBEDDING_LAYER"),
            "semanticEmbeddingLayers": ns.get("SEMANTIC_EMBEDDING_LAYERS"),
            "semanticEncoderLayers": ns.get("SEMANTIC_ENCODER_LAYERS"),
            "semanticPooling": ns.get("SEMANTIC_POOLING"),
            "semanticBatchSize": ns.get("SEMANTIC_BATCH_SIZE"),
            "semanticSubjectCrop": ns.get("SEMANTIC_SUBJECT_CROP"),
            "semanticDenseEnabled": ns.get("SEMANTIC_DENSE_ENABLED"),
            "semanticDenseModel": ns.get("SEMANTIC_DENSE_MODEL_ID"),
            "semanticDenseEmbeddingLayers": ns.get("SEMANTIC_DENSE_EMBEDDING_LAYERS"),
            "semanticDenseWeight": ns.get("SEMANTIC_DENSE_WEIGHT"),
            "semanticGlobalBatchSize": ns.get("SEMANTIC_GLOBAL_BATCH_SIZE"),
            "semanticDenseBatchSize": ns.get("SEMANTIC_DENSE_BATCH_SIZE"),
            "triageSilhouetteKeepFraction": ns.get("TRIAGE_SILHOUETTE_KEEP_FRACTION"),
            "triageSilhouetteHeuristicEnabled": ns.get("TRIAGE_SILHOUETTE_HEURISTIC_ENABLED"),
            "triageSilhouetteMinCandidates": ns.get("TRIAGE_SILHOUETTE_MIN_CANDIDATES"),
            "triageSilhouetteMaxCandidates": ns.get("TRIAGE_SILHOUETTE_MAX_CANDIDATES"),
            "proxyEnabled": ns.get("PROXY_ENABLED"),
            "proxyDevice": ns.get("PROXY_DEVICE"),
            "proxyMinCandidates": ns.get("PROXY_MIN_CANDIDATES"),
            "proxyProtectedStages": ns.get("PROXY_PROTECTED_STAGES"),
            "proxyAuditEnabled": ns.get("PROXY_AUDIT_ENABLED"),
            "proxyAuditFraction": ns.get("PROXY_AUDIT_FRACTION"),
            "proxyAuditMaxCandidates": ns.get("PROXY_AUDIT_MAX_CANDIDATES"),
            "proxyAuditRegretTolerance": ns.get("PROXY_AUDIT_REGRET_TOLERANCE"),
            "proxyGpuTensorCacheEnabled": ns.get("PROXY_GPU_TENSOR_CACHE_ENABLED"),
            "proxyGpuAssetCacheMaxEntries": ns.get("PROXY_GPU_ASSET_CACHE_MAX_ENTRIES"),
            "proxyResolution": ns.get("PROXY_RESOLUTION"),
            "proxyLevel0Enabled": ns.get("PROXY_LEVEL0_ENABLED"),
            "proxyLevel0PointsPerBone": ns.get("PROXY_LEVEL0_POINTS_PER_BONE"),
            "proxyLevel0KeepFraction": ns.get("PROXY_LEVEL0_KEEP_FRACTION"),
            "proxyLevel0MinCandidates": ns.get("PROXY_LEVEL0_MIN_CANDIDATES"),
            "proxyLevel0MaxCandidates": ns.get("PROXY_LEVEL0_MAX_CANDIDATES"),
            "proxyLevel1Enabled": ns.get("PROXY_LEVEL1_ENABLED"),
            "proxyLevel1MaxVertices": ns.get("PROXY_LEVEL1_MAX_VERTICES"),
            "proxyLevel1KeepFraction": ns.get("PROXY_LEVEL1_KEEP_FRACTION"),
            "proxyLevel1MinCandidates": ns.get("PROXY_LEVEL1_MIN_CANDIDATES"),
            "proxyLevel1MaxCandidates": ns.get("PROXY_LEVEL1_MAX_CANDIDATES"),
            "proxyPointRadius": ns.get("PROXY_POINT_RADIUS"),
            "proxyTargetAlphaThreshold": ns.get("PROXY_TARGET_ALPHA_THRESHOLD"),
            "proxyCentroidWeight": ns.get("PROXY_CENTROID_WEIGHT"),
            "proxyOccupancyWeight": ns.get("PROXY_OCCUPANCY_WEIGHT"),
            "proxyBindReport": ns.get("geometric_proxy_bind_report"),
            "gpuPoseAdvisorEnabled": ns.get("GPU_POSE_ADVISOR_ENABLED"),
            "gpuPoseAdvisorDevice": ns.get("GPU_POSE_ADVISOR_DEVICE"),
            "gpuPoseAdvisorDirectionEnabled": ns.get("GPU_POSE_ADVISOR_DIRECTION_ENABLED"),
            "gpuPoseAdvisorRootEnabled": ns.get("GPU_POSE_ADVISOR_ROOT_ENABLED"),
            "gpuPoseAdvisorMaxPoints": ns.get("GPU_POSE_ADVISOR_MAX_POINTS"),
            "gpuPoseAdvisorMediumSensitivityRatio": ns.get("GPU_POSE_ADVISOR_MEDIUM_SENSITIVITY_RATIO"),
            "gpuPoseAdvisorHighSensitivityRatio": ns.get("GPU_POSE_ADVISOR_HIGH_SENSITIVITY_RATIO"),
            "gpuPoseAdvisorRootHypothesisCount": ns.get("GPU_POSE_ADVISOR_ROOT_HYPOTHESIS_COUNT"),
            "gpuPoseAdvisorRootKeep": ns.get("GPU_POSE_ADVISOR_ROOT_KEEP"),
            "gpuPoseAdvisorSummary": (
                ns.get("gpu_pose_advisor").summary()
                if ns.get("gpu_pose_advisor") is not None
                else None
            ),
            "semanticBranchBoundEnabled": ns.get("SEMANTIC_BRANCH_BOUND_ENABLED"),
            "semanticBranchBoundMargin": ns.get("SEMANTIC_BRANCH_BOUND_MARGIN"),
            "semanticCandidateCacheEnabled": ns.get("SEMANTIC_CANDIDATE_CACHE_ENABLED"),
            "semanticCandidateCacheMaxEntries": ns.get("SEMANTIC_CANDIDATE_CACHE_MAX_ENTRIES"),
            "semanticImageCacheMaxEntries": ns.get("SEMANTIC_IMAGE_CACHE_MAX_ENTRIES"),
            "semanticDenseGridCacheMaxEntries": ns.get("SEMANTIC_DENSE_GRID_CACHE_MAX_ENTRIES"),
            "semanticServiceEnabled": ns.get("SEMANTIC_SERVICE_ENABLED"),
            "semanticServiceCacheGeneration": ns.get("SEMANTIC_SERVICE_CACHE_GENERATION"),
            "semanticServiceEncoderCacheMaxEntries": ns.get(
                "SEMANTIC_SERVICE_ENCODER_CACHE_MAX_ENTRIES"
            ),
            "semanticServiceTargetCacheMaxEntries": ns.get(
                "SEMANTIC_SERVICE_TARGET_CACHE_MAX_ENTRIES"
            ),
            "semanticServiceDenseTargetCacheMaxEntries": ns.get(
                "SEMANTIC_SERVICE_DENSE_TARGET_CACHE_MAX_ENTRIES"
            ),
            "renderPngCompression": ns.get("RENDER_PNG_COMPRESSION"),
            "semanticDenseLocalRadius": ns.get("SEMANTIC_DENSE_LOCAL_RADIUS"),
            "semanticDensePositionWeight": ns.get("SEMANTIC_DENSE_POSITION_WEIGHT"),
            "semanticDenseViewIndex": ns.get("SEMANTIC_DENSE_VIEW_INDEX"),
            "semanticWeight": ns.get("HYBRID_SEMANTIC_WEIGHT"),
            "depthWeight": ns.get("HYBRID_DEPTH_WEIGHT"),  # legacy name
            "geometryWeight": ns.get("HYBRID_GEOMETRY_WEIGHT"),
            "geometryEnabled": ns.get("HYBRID_GEOMETRY_ENABLED"),
            "silhouetteDepthWeight": ns.get("SILHOUETTE_DEPTH_WEIGHT"),
            "blueZonePenalty": ns.get("BLUE_ZONE_PENALTY"),
            "redZonePenalty": ns.get("RED_ZONE_PENALTY"),
            "silhouetteEdgeBonus": ns.get("SILHOUETTE_EDGE_BONUS"),
            "reverseProfileEnabled": ns.get("REVERSE_PROFILE_ENABLED"),
            "reverseProfileWeight": ns.get("REVERSE_PROFILE_WEIGHT"),
            "profileHalfBias": ns.get("PROFILE_HALF_BIAS"),
            "actionCameraAngleDeg": ns.get("ACTION_CAMERA_ANGLE_DEG"),
            "actionCameraElevationDeg": ns.get("ACTION_CAMERA_ELEVATION_DEG"),
            "detectProfileEnabled": ns.get("DETECT_PROFILE_ENABLED"),
            "meshOrientationMode": ns.get("MESH_ORIENTATION_MODE"),
            "textEnabled": ns.get("SEMANTIC_TEXT_ENABLED"),
            "textPrompt": ns.get("SEMANTIC_TEXT_PROMPT"),
            "textWeight": ns.get("HYBRID_TEXT_WEIGHT"),
            "negativeTextEnabled": ns.get("SEMANTIC_NEGATIVE_TEXT_ENABLED"),
            "negativeTextPrompt": ns.get("SEMANTIC_NEGATIVE_TEXT_PROMPT"),
            "negativeTextWeight": ns.get("HYBRID_NEGATIVE_TEXT_WEIGHT"),
            "searchAxes": ns.get("SEARCH_AXES"),
            "rotationVectorSearchEnabled": ns.get("ROTATION_VECTOR_SEARCH_ENABLED"),
            "rotationVectorProbeCount": ns.get("ROTATION_VECTOR_PROBE_COUNT"),
            "rotationVectorProbeStepDeg": ns.get("ROTATION_VECTOR_PROBE_STEP_DEG"),
            "directionalContinuationEnabled": ns.get("DIRECTIONAL_CONTINUATION_ENABLED"),
            "directionalMaxSteps": ns.get("DIRECTIONAL_MAX_STEPS"),
            "directionalStepMultiplier": ns.get("DIRECTIONAL_STEP_MULTIPLIER"),
            "directionalTopK": ns.get("DIRECTIONAL_TOP_K"),
            "directionalMinImprovement": ns.get("DIRECTIONAL_MIN_IMPROVEMENT"),
            "boneTwistPolicy": ns.get("BONE_TWIST_POLICY"),
            "coarseStepDeg": ns.get("COARSE_STEP_DEG"),
            "refineStepDeg": ns.get("REFINE_STEP_DEG"),
            "motionRootEnabled": ns.get("MOTION_ROOT_ENABLED"),
            "motionRootAxes": ns.get("MOTION_ROOT_AXES"),
            "motionRootForwardRadiusBodyLengths": ns.get("MOTION_ROOT_FORWARD_RADIUS_BODY_LENGTHS"),
            "motionRootLateralRadiusBodyLengths": ns.get("MOTION_ROOT_LATERAL_RADIUS_BODY_LENGTHS"),
            "motionRootVerticalRadiusBodyLengths": ns.get("MOTION_ROOT_VERTICAL_RADIUS_BODY_LENGTHS"),
            "motionRootCoarseStepBodyLengths": ns.get("MOTION_ROOT_COARSE_STEP_BODY_LENGTHS"),
            "motionRootRefineStepBodyLengths": ns.get("MOTION_ROOT_REFINE_STEP_BODY_LENGTHS"),
            "motionRootMagnitudeWeight": ns.get("MOTION_ROOT_MAGNITUDE_WEIGHT"),
            "motionRootVelocityWeight": ns.get("MOTION_ROOT_VELOCITY_WEIGHT"),
            "motionRootAccelerationWeight": ns.get("MOTION_ROOT_ACCELERATION_WEIGHT"),
            "motionRootLoopWeight": ns.get("MOTION_ROOT_LOOP_WEIGHT"),
            "motionRootLoopVelocityWeight": ns.get("MOTION_ROOT_LOOP_VELOCITY_WEIGHT"),
            "motionRootCoupledBlocksEnabled": ns.get("MOTION_ROOT_COUPLED_BLOCKS_ENABLED"),
            "motionRootRotationEnabled": ns.get("MOTION_ROOT_ROTATION_ENABLED"),
            "motionRootRotationBasis": ns.get("MOTION_ROOT_ROTATION_BASIS"),
            "motionRootRotationAxes": ns.get("MOTION_ROOT_ROTATION_AXES"),
            "motionRootRotationLimitDeg": ns.get("MOTION_ROOT_ROTATION_LIMIT_DEG"),
            "motionRootRotationCoarseStepDeg": ns.get("MOTION_ROOT_ROTATION_COARSE_STEP_DEG"),
            "motionRootRotationRefineStepDeg": ns.get("MOTION_ROOT_ROTATION_REFINE_STEP_DEG"),
            "motionRootRotationEscapeEnabled": ns.get("MOTION_ROOT_ROTATION_ESCAPE_ENABLED"),
            "motionRootRotationEscapeAxes": ns.get("MOTION_ROOT_ROTATION_ESCAPE_AXES"),
            "motionRootRotationEscapeAnglesDeg": ns.get("MOTION_ROOT_ROTATION_ESCAPE_ANGLES_DEG"),
            "motionRootRotationEscapeTopK": ns.get("MOTION_ROOT_ROTATION_ESCAPE_TOP_K"),
            "motionRootRotationEscapeRelaxEnabled": ns.get("MOTION_ROOT_ROTATION_ESCAPE_RELAX_ENABLED"),
            "motionRootRotationEscapeRelaxBoneCount": ns.get("MOTION_ROOT_ROTATION_ESCAPE_RELAX_BONE_COUNT"),
            "motionRootRotationEscapeRelaxRounds": ns.get("MOTION_ROOT_ROTATION_ESCAPE_RELAX_ROUNDS"),
            "motionRootRotationEscapeRelaxStepDeg": ns.get("MOTION_ROOT_ROTATION_ESCAPE_RELAX_STEP_DEG"),
            "motionRootRotationEscapeRelaxRefineStepDeg": ns.get("MOTION_ROOT_ROTATION_ESCAPE_RELAX_REFINE_STEP_DEG"),
            "motionRootRotationMagnitudeWeight": ns.get("MOTION_ROOT_ROTATION_MAGNITUDE_WEIGHT"),
            "motionRootRotationVelocityWeight": ns.get("MOTION_ROOT_ROTATION_VELOCITY_WEIGHT"),
            "motionRootRotationAccelerationWeight": ns.get("MOTION_ROOT_ROTATION_ACCELERATION_WEIGHT"),
            "motionRootRotationCoupledBlocksEnabled": ns.get("MOTION_ROOT_ROTATION_COUPLED_BLOCKS_ENABLED"),
            "livePreview": ns.get("LIVE_PREVIEW"),
            "anatomicalBoxesEnabled": ns.get("ANATOMICAL_BOXES_ENABLED"),
            "anatomicalPartWeight": ns.get("ANATOMICAL_PART_WEIGHT"),
            "hybridAnatomicalWeight": ns.get("HYBRID_ANATOMICAL_WEIGHT"),
            "anatomicalMaxFeatures": ns.get("ANATOMICAL_MAX_FEATURES"),
            "anatomicalMinAreaFrac": ns.get("ANATOMICAL_MIN_AREA_FRAC"),
            "anatomicalCenterWeight": ns.get("ANATOMICAL_CENTER_WEIGHT"),
            "anatomicalExtentWeight": ns.get("ANATOMICAL_EXTENT_WEIGHT"),
            "anatomicalLateralityEnabled": ns.get("ANATOMICAL_LATERALITY_ENABLED"),
            "anatomicalLateralitySource": ns.get("ANATOMICAL_LATERALITY_SOURCE"),
            "anatomicalLateralityNearSide": ns.get("ANATOMICAL_LATERALITY_NEAR_SIDE"),
            "anatomicalLateralityDepthMargin": ns.get("ANATOMICAL_LATERALITY_DEPTH_MARGIN"),
            "anatomicalLateralityCenterMarginFrac": ns.get("ANATOMICAL_LATERALITY_CENTER_MARGIN_FRAC"),
            "targetFrameDir": self.config.target_frame_dir,
            "targetDepthDir": self.config.target_depth_dir,
            "shadowCulledFrameDir": self.config.shadow_culled_frame_dir,
            "searchBones": len(ns.get("pilot_bones", [])),
            "boneOrderMode": ns.get("BONE_ORDER_MODE"),
            "branchWalkCameraBias": ns.get("BRANCH_WALK_CAMERA_BIAS"),
            "nearBoneRefinementEnabled": ns.get("NEAR_BONE_REFINEMENT_ENABLED"),
            "nearBoneRefinementStepDeg": ns.get("NEAR_BONE_REFINEMENT_STEP_DEG"),
            "multiBoneMode": ns.get("MULTI_BONE_MODE"),
            "multiBoneGrouping": ns.get("MULTI_BONE_GROUPING"),
            "multiBoneBlockSize": ns.get("MULTI_BONE_BLOCK_SIZE"),
            "multiBoneRounds": ns.get("MULTI_BONE_ROUNDS"),
            "multiBoneStepDeg": ns.get("MULTI_BONE_STEP_DEG"),
            "multiBoneCandidatePattern": ns.get("MULTI_BONE_CANDIDATE_PATTERN"),
            "multiBoneBeamWidth": ns.get("MULTI_BONE_BEAM_WIDTH"),
            "meshScale": ns.get("SEARCH_SCALE"),
            "ikEnabled": ns.get("IK_ENABLED"),
            "ikMode": ns.get("IK_MODE"),
            "ikBones": ns.get("IK_BONES"),
            "ikTargetSearchEnabled": ns.get("IK_TARGET_SEARCH_ENABLED"),
            "ikTargetSearchOnly": ns.get("IK_TARGET_SEARCH_ONLY"),
            "ikTargetSearchBones": ns.get("IK_TARGET_SEARCH_BONES"),
            "ikTargetCoarseStepPx": ns.get("IK_TARGET_COARSE_STEP_PX"),
            "ikTargetRefineStepPx": ns.get("IK_TARGET_REFINE_STEP_PX"),
            "ikTargetSearchRadiusPx": ns.get("IK_TARGET_SEARCH_RADIUS_PX"),
            "ikTargetMinImprovement": ns.get("IK_TARGET_MIN_IMPROVEMENT"),
            "clipOptimizationEnabled": ns.get("CLIP_OPTIMIZATION_ENABLED"),
            "clipWarmStart": ns.get("CLIP_WARM_START"),
            "clipRounds": ns.get("CLIP_ROUNDS"),
            "clipRefineRounds": ns.get("CLIP_REFINE_ROUNDS"),
            "clipRefineAcceptedOnly": ns.get("CLIP_REFINE_ACCEPTED_ONLY"),
            "clipVelocityWeight": ns.get("CLIP_VELOCITY_WEIGHT"),
            "clipAccelerationWeight": ns.get("CLIP_ACCELERATION_WEIGHT"),
            "clipContactWeight": ns.get("CLIP_CONTACT_WEIGHT"),
            "clipContactBones": ns.get("CLIP_CONTACT_BONES"),
            "clipLoopWeight": ns.get("CLIP_LOOP_WEIGHT"),
            "clipLoopVelocityWeight": ns.get("CLIP_LOOP_VELOCITY_WEIGHT"),
            "clipLoopEnabled": ns.get("CLIP_LOOP_ENABLED"),
            "clipMotionRootMagnitudeWeight": ns.get("CLIP_MOTION_ROOT_MAGNITUDE_WEIGHT"),
            "clipMotionRootVelocityWeight": ns.get("CLIP_MOTION_ROOT_VELOCITY_WEIGHT"),
            "clipMotionRootAccelerationWeight": ns.get("CLIP_MOTION_ROOT_ACCELERATION_WEIGHT"),
            "clipMotionRootLoopWeight": ns.get("CLIP_MOTION_ROOT_LOOP_WEIGHT"),
            "clipMotionRootLoopVelocityWeight": ns.get("CLIP_MOTION_ROOT_LOOP_VELOCITY_WEIGHT"),
            "clipRobustScaleDeg": ns.get("CLIP_ROBUST_SCALE_DEG"),
            "clipCoarseStepDeg": ns.get("CLIP_COARSE_STEP_DEG"),
            "clipRefineStepDeg": ns.get("CLIP_REFINE_STEP_DEG"),
            "clipMaxEvaluationsPerAxis": ns.get("CLIP_MAX_EVALUATIONS_PER_AXIS"),
            "clipBatchCandidates": ns.get("CLIP_BATCH_CANDIDATES"),
            "clipSensitivityEnabled": ns.get("CLIP_SENSITIVITY_ENABLED"),
            "clipSensitivityScoreEpsilon": ns.get("CLIP_SENSITIVITY_SCORE_EPSILON"),
            "clipPolishIncludeNeighbors": ns.get("CLIP_POLISH_INCLUDE_NEIGHBORS"),
            "parallelCandidateRendering": ns.get("PARALLEL_CANDIDATE_RENDERING"),
            "renderWorkerCount": ns.get("RENDER_WORKER_COUNT"),
        }

    def close(self) -> None:
        if not self._closed:
            if self.namespace.get("worker_pool_owned", True):
                worker_pool = self.namespace.get("worker_pool")
                if worker_pool is not None:
                    worker_pool.close()
                else:
                    worker = self.namespace.get("worker")
                    if worker is not None:
                        worker.close()
            self._closed = True


def _exec(source: str, namespace: dict[str, Any]) -> None:
    exec(compile(source, "roc_semantic_hybrid_runtime.py", "exec"), namespace, namespace)


def _reload_source_frame_helpers():
    """Return the on-disk source-frame helper, not a stale Jupyter import.

    The notebook reloads ``roc_semantic_hybrid_experiment`` but keeps an older
    ``materialize_rife_source_frames`` in ``sys.modules``. ``from ... import``
    then fails for names added after that first import.
    """
    import importlib
    import sys

    module_name = "materialize_rife_source_frames"
    module = sys.modules.get(module_name)
    if module is None:
        module = importlib.import_module(module_name)
    else:
        module = importlib.reload(module)
    return module


def _reload_runtime_helpers() -> None:
    """Refresh source-owned helpers before executing the runtime bundle.

    The notebook executes ``roc_semantic_hybrid_solver_body.py`` into a fresh
    namespace, but that source imports normal Python modules.  A kernel that
    previously loaded an older helper therefore can combine a new solver
    call-site with an old dataclass definition.  Reload the helpers that are
    embedded into the solver contract so notebook reruns cannot retain that
    half-updated state.
    """
    import importlib
    import sys

    _reload_source_frame_helpers()
    for module_name in (
        "roc_rotation_search",
        "roc_temporal_clip_optimizer",
        "dense_semantic_features",
    ):
        module = sys.modules.get(module_name)
        if module is None:
            importlib.import_module(module_name)
        else:
            importlib.reload(module)
    # roc_semantic_services is intentionally not reloaded: its singleton is
    # the process-wide model/target cache shared by sequential animations.


def _migrate_legacy_picker_source_lane(config: RocHybridConfig, pilot: Path) -> None:
    """Upgrade old picker outputs without promoting arbitrary RIFE folders.

    Older widget versions materialized verified generic source inventories as
    ``pose_picker_runs/.../frames_src``. Those directories are safe to migrate
    only when their pilot path and provisional camera metadata identify the
    picker-owned job; an arbitrary ``frames_src`` is never accepted.
    """
    target = pilot / config.target_frame_dir
    legacy = pilot / "frames_src"
    if target.is_dir() or not legacy.is_dir():
        return
    if "pose_picker_runs" not in str(pilot).lower():
        return
    camera_fit = Path(config.camera_fit_path) if config.camera_fit_path else pilot / "roc_sprite_camera_fit.json"
    try:
        camera_payload = json.loads(camera_fit.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if camera_payload.get("cameraPolicy") != "provisional_job_camera":
        return
    frames = sorted(
        path for path in legacy.glob("*.png")
        if re.fullmatch(r"(?:frame_)?\d+\.png", path.name, re.IGNORECASE)
    )
    if not frames:
        return
    target.mkdir(parents=True, exist_ok=True)
    for index, source in enumerate(frames):
        shutil.copy2(source, target / f"{index:02d}.png")
    (target / "original_frames.json").write_text(
        json.dumps({
            "unit": config.unit_name,
            "animation": config.animation_name,
            "frameDir": str(target),
            "frameCount": len(frames),
            "frameIndices": list(range(len(frames))),
            "sourceKind": "vcmi_def",
            "provenance": "migrated from picker-owned verified source inventory; no RIFE interpolation",
        }, indent=2) + "\n",
        encoding="utf-8",
    )


def _source_frame_indices(config: RocHybridConfig) -> tuple[int, ...]:
    """Resolve and validate indices against the original source-frame lane."""
    pilot = config.pilot_dir or (
        config.root / "artifacts/roc_pose_pipeline/smart_rig_move_pilot"
    )
    _migrate_legacy_picker_source_lane(config, Path(pilot))
    source_dir = pilot / config.target_frame_dir
    if not source_dir.is_dir():
        raise FileNotFoundError(f"original source-frame directory is missing: {source_dir}")
    discovered = tuple(
        sorted(
            int(match.group(1))
            for path in source_dir.glob("*.png")
            if (match := re.fullmatch(r"(\d+)\.png", path.name, re.IGNORECASE))
        )
    )
    if not discovered:
        raise FileNotFoundError(f"no numbered original frames found in: {source_dir}")
    requested = tuple(int(frame) for frame in config.frame_indices)
    if not requested:
        return discovered
    missing = tuple(frame for frame in requested if frame not in discovered)
    if missing:
        raise ValueError(
            "requested frame indices are not present in the original source-frame lane "
            f"{source_dir}: {missing}"
        )
    return requested


def _validate_meshy_rigidization(config: RocHybridConfig) -> dict[str, Any] | None:
    """Fail closed when a run explicitly requires the post-rig proof."""
    report_value = config.meshy_rigidization_report
    if report_value is None:
        if config.require_meshy_rigidization:
            raise ValueError(
                "require_meshy_rigidization=True requires meshy_rigidization_report"
            )
        return None
    report_path = Path(report_value)
    if not report_path.is_absolute():
        report_path = config.root / report_path
    report_path = report_path.resolve()
    if not report_path.is_file():
        raise FileNotFoundError(f"Meshy rigidization report is missing: {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("schema") != "meshy_rigidization_report.v1":
        raise ValueError(f"unsupported Meshy rigidization report schema: {report.get('schema')!r}")
    if report.get("status") != "pass":
        raise ValueError(f"Meshy rigidization report is not passing: {report.get('status')!r}")
    if report.get("armatureAuthority") != "meshy_auto_rig":
        raise ValueError("Meshy rigidization report does not identify the Meshy armature as authority")
    output_value = report.get("output")
    if not output_value:
        raise ValueError("Meshy rigidization report has no output path")
    output_path = Path(str(output_value))
    if not output_path.is_absolute():
        output_path = config.root / output_path
    output_path = output_path.resolve()
    source_path = Path(config.src_glb)
    if not source_path.is_absolute():
        source_path = config.root / source_path
    source_path = source_path.resolve()
    if output_path != source_path:
        raise ValueError(
            "selected src_glb is not the audited rigidized output: "
            f"selected={source_path} report={output_path}"
        )
    output_hash = report.get("outputSha256")
    if output_hash:
        digest = hashlib.sha256()
        with source_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != output_hash:
            raise ValueError("selected rigidized GLB hash does not match its audit report")
    return report


def _materialize_def_source(config: RocHybridConfig) -> RocHybridConfig:
    """Place authentic 12 fps DEF group(s) onto the pose-fit nn-upscale canvas."""
    if config.def_lab_frame_dir is None:
        return config
    frames = _reload_source_frame_helpers()
    plan = frames.normalize_def_group_plan(config.def_lab_group, config.def_expected_count)
    if plan is None:
        raise ValueError("def_lab_frame_dir and def_lab_group must be set together")
    groups, counts = plan
    if any(count is None for count in counts):
        raise ValueError("authentic DEF source requires def_expected_count for every group")
    allow_idle_only = len(groups) == 1 and groups[0] == frames.IDLE_GROUP
    frames.require_authentic_def_pose_groups(
        groups,
        sequence_label="authentic DEF pose-fit",
        allow_idle_only=allow_idle_only,
    )
    pilot = Path(config.pilot_dir) if config.pilot_dir is not None else (
        Path(config.root) / "artifacts/roc_pose_pipeline/smart_rig_move_pilot"
    )
    target = Path(config.target_frame_dir)
    if not target.is_absolute():
        target = pilot / target
    seed = Path(config.camera_fit_path) if config.camera_fit_path is not None else (
        pilot / "roc_sprite_camera_fit.json"
    )
    if not seed.is_absolute():
        seed = pilot / seed
    if config.def_nn_upscale_meta is None:
        raise ValueError("authentic DEF pose-fit requires def_nn_upscale_meta")
    manifest = frames.materialize_def_group_sequence(
        Path(config.def_lab_frame_dir),
        target,
        groups=groups,
        expected_counts=tuple(int(count) for count in counts),
        target_fps=float(config.depth_video_fps),
        nn_upscale_meta=Path(config.def_nn_upscale_meta),
        camera_fit=seed,
    )
    clip_note = ", ".join(
        f"{clip['name']} g{int(clip['group']):02d}:{int(clip['frameCount'])}"
        for clip in manifest["clips"]
    )
    canvas = manifest["sourceResolution"]
    print(
        f"authentic DEF source ready: {target} ({manifest['frameCount']} frames @ "
        f"{manifest['targetFps']:g} fps, nn canvas {canvas[0]}x{canvas[1]}, {clip_note})"
    )
    return config


def _materialize_pose_source(config: RocHybridConfig) -> RocHybridConfig:
    if config.rife_lab_frame_dir is not None and config.def_lab_frame_dir is not None:
        raise ValueError("cannot enable RIFE interpolation and authentic DEF source together")
    if config.def_lab_frame_dir is not None:
        return _materialize_def_source(config)
    return _materialize_rife_source(config)


def _materialize_rife_source(config: RocHybridConfig) -> RocHybridConfig:
    """Place lab RIFE group(s) onto the pose-fit nn-upscale canvas before frame discovery."""
    if config.rife_lab_frame_dir is None:
        return config
    frames = _reload_source_frame_helpers()

    plan = frames.normalize_rife_group_plan(config.rife_lab_group, config.rife_expected_count)
    if plan is None:
        raise ValueError("rife_lab_frame_dir and rife_lab_group must be set together")
    groups, counts = plan
    pilot = Path(config.pilot_dir) if config.pilot_dir is not None else (
        Path(config.root) / "artifacts/roc_pose_pipeline/smart_rig_move_pilot"
    )
    target = Path(config.target_frame_dir)
    if not target.is_absolute():
        target = pilot / target
    seed = Path(config.camera_fit_path) if config.camera_fit_path is not None else (
        pilot / "roc_sprite_camera_fit.json"
    )
    if not seed.is_absolute():
        seed = pilot / seed
    if config.rife_nn_upscale_meta is None:
        raise ValueError("RIFE pose-fit requires rife_nn_upscale_meta")
    if len(groups) == 1:
        manifest = frames.materialize_rife_group_frames(
            Path(config.rife_lab_frame_dir),
            target,
            group=int(groups[0]),
            expected_count=counts[0],
            target_fps=float(config.depth_video_fps),
            nn_upscale_meta=Path(config.rife_nn_upscale_meta),
            camera_fit=seed,
        )
        clip_note = f"group {int(groups[0]):02d}"
    else:
        if any(count is None for count in counts):
            raise ValueError("concatenated RIFE groups require rife_expected_count for every group")
        manifest = frames.materialize_rife_group_sequence(
            Path(config.rife_lab_frame_dir),
            target,
            groups=groups,
            expected_counts=tuple(int(count) for count in counts),
            target_fps=float(config.depth_video_fps),
            nn_upscale_meta=Path(config.rife_nn_upscale_meta),
            camera_fit=seed,
        )
        clip_note = ", ".join(
            f"{clip['name']} g{int(clip['group']):02d}:{int(clip['frameCount'])}"
            for clip in manifest["clips"]
        )
    canvas = manifest["sourceResolution"]
    print(
        f"RIFE source ready: {target} ({manifest['frameCount']} frames @ {manifest['targetFps']:g} fps, "
        f"nn canvas {canvas[0]}x{canvas[1]}, {clip_note})"
    )
    return config


def prepare_gpu_fit_config(config: RocHybridConfig) -> RocHybridConfig:
    """Materialize authentic DEF or RIFE frames if requested, then shadow-cull and write VDA depth.

    The GPU notebook path does not call ``initialize``, so this is the source
    and depth cache entry point for that lane. It does not start Blender.
    """
    import hashlib
    import json
    import sys

    import numpy as np
    from PIL import Image

    config = _materialize_pose_source(config)
    resolved_indices = _source_frame_indices(config)
    if resolved_indices != config.frame_indices:
        config = replace(config, frame_indices=resolved_indices)
    tool = Path(config.root) / "tools/homm3_silhouette_pose_fit"
    if str(tool) not in sys.path:
        sys.path.insert(0, str(tool))
    _setup_base, setup_rest = SETUP_SOURCE.split("\n\n# Predicted depth cache\n\n", 1)
    del _setup_base
    depth_source, _unused = setup_rest.split("\n\n# Bone range placeholders\n\n", 1)
    from alpha_shadow_cull import alpha_cull_signature, cull_alpha_shadows

    ns: dict[str, Any] = {
        "__name__": "__pose_fit_prep__",
        "__file__": __file__,
        "Path": Path,
        "hashlib": hashlib,
        "json": json,
        "sys": sys,
        "np": np,
        "numpy": np,
        "Image": Image,
        "cull_alpha_shadows": cull_alpha_shadows,
        "_alpha_cull_signature": alpha_cull_signature,
    }
    ns.update(config.namespace())
    _exec(depth_source, ns)
    return config


def initialize(
    config: RocHybridConfig | None = None,
    *,
    persistent_worker_pool=None,
) -> RocHybridExperiment:
    config = config or RocHybridConfig()
    _validate_meshy_rigidization(config)
    _reload_runtime_helpers()
    config = _materialize_pose_source(config)
    resolved_indices = _source_frame_indices(config)
    if resolved_indices != config.frame_indices:
        config = replace(config, frame_indices=resolved_indices)
    previous = globals().get("_ACTIVE_EXPERIMENT")
    if previous is not None:
        previous.close()
    ns: dict[str, Any] = {
        "__name__": "__roc_semantic_hybrid__",
        "__file__": __file__,
        "PERSISTENT_WORKER_POOL": persistent_worker_pool,
    }
    setup_base, setup_rest = SETUP_SOURCE.split("\n\n# Predicted depth cache\n\n", 1)
    depth_source, setup_rest = setup_rest.split("\n\n# Bone range placeholders\n\n", 1)
    ranges_source, setup_rest = setup_rest.split("\n\n# Persistent Blender worker and hierarchy init\n\n", 1)
    worker_source, boxes_source = setup_rest.split("\n\n# Optional anatomical detector\n\n", 1)
    _exec(setup_base, ns)
    ns.update(config.namespace())
    _exec(depth_source, ns)
    _exec(ranges_source, ns)
    _exec(worker_source, ns)
    _exec(boxes_source, ns)
    _exec(SOLVER_SOURCE, ns)
    experiment = RocHybridExperiment(config, ns)
    globals()["_ACTIVE_EXPERIMENT"] = experiment
    return experiment


def run_frame0_pilot(experiment: RocHybridExperiment):
    ns = experiment.namespace
    if not experiment.config.run_frame0_pilot:
        ns["pose0"], ns["history0"], ns["seconds0"], ns["timings0"] = {}, [], 0.0, []
        ns["ik_targets0"] = {}
        print("frame-0 pilot disabled")
        return ns["pose0"], ns["history0"], ns["seconds0"], ns["timings0"]
    fn = ns["optimize_frame_semantic"] if ns.get("SEMANTIC_ONLY") and ns.get("SEMANTIC_OPTIMIZER") else ns["optimize_frame"]
    result = fn(0, bones=ns["pilot_bones"], progress=True, live_preview=ns.get("LIVE_PREVIEW", True))
    ns["pose0"], ns["history0"], ns["seconds0"], ns["timings0"] = result
    ns["ik_targets0"] = (
        ns["_frame_ik_targets"](0)
        if ns.get("IK_TARGET_SEARCH_ENABLED") and ns.get("_frame_ik_targets")
        else {}
    )
    print("pilot seconds:", ns["seconds0"], "trials:", sum(h.get("trials", 0) for h in ns["history0"]))
    return result


def run_clip_pilot(experiment: RocHybridExperiment):
    """Run the global clip solver without requiring the delivery loop."""

    ns = experiment.namespace
    if not ns.get("CLIP_OPTIMIZATION_ENABLED"):
        raise ValueError(
            "clip optimization is disabled; set clip_optimization_enabled=True first"
        )
    result = ns["run_clip_optimization"](
        frame_indices=ns.get("FRAME_INDICES"),
        bones=ns.get("pilot_bones"),
        progress=True,
        live_preview=ns.get("LIVE_PREVIEW", True),
    )
    ns["clip_result"] = result
    ns["clip_poses"] = result["poses"]
    if 0 in result["poses"]:
        ns["pose0"] = result["poses"][0]
    print(
        "clip pilot seconds:",
        f"{result['elapsed']:.2f}",
        "evaluations:",
        result["evaluations"],
        "accepted:",
        result["accepted"],
    )
    return result


def export_clip_result(
    experiment: RocHybridExperiment,
    output_dir: str | Path | None = None,
    *,
    frame_duration_ms: int = 120,
    fps: int = 60,
) -> dict[str, Any]:
    """Render and encode an existing clip result without running optimization."""
    ns = experiment.namespace
    result = ns.get("clip_result")
    if not isinstance(result, dict) or not result.get("poses"):
        raise RuntimeError(
            "no in-memory clip_result is available; run run_clip_pilot first"
        )
    worker = ns.get("worker")
    if worker is None:
        raise RuntimeError("the persistent Blender worker is not available")
    frames = [int(frame) for frame in result.get("config", {}).get("frameIndices", ())]
    if not frames:
        frames = sorted(int(frame) for frame in result["poses"])
    out = Path(output_dir) if output_dir is not None else experiment.config.pilot_dir / "clip_export"
    out.mkdir(parents=True, exist_ok=True)
    frame_paths = []
    for frame in frames:
        pose = result["poses"][frame]
        worker.request({"cmd": "set_pose", "angles": pose})
        frame_path = out / f"frame_{frame:02d}.png"
        worker.request({"cmd": "save_render", "out": str(frame_path)})
        if not frame_path.is_file() or frame_path.stat().st_size <= 0:
            raise RuntimeError(f"export render was not written: {frame_path}")
        frame_paths.append(frame_path)

    images = [Image.open(path).convert("RGB") for path in frame_paths]
    gif_path = out / "roc_clip.gif"
    images[0].save(
        gif_path,
        save_all=True,
        append_images=images[1:],
        duration=int(frame_duration_ms),
        loop=0,
        optimize=False,
    )
    for image in images:
        image.close()

    mp4_path = out / "roc_clip_60fps.mp4"
    try:
        import cv2

        first = Image.open(frame_paths[0]).convert("RGB")
        width, height = first.size
        first.close()
        writer = cv2.VideoWriter(
            str(mp4_path), cv2.VideoWriter_fourcc(*"mp4v"), int(fps), (width, height)
        )
        if not writer.isOpened():
            raise RuntimeError("OpenCV could not open the MP4 writer")
        try:
            for path in frame_paths:
                image = cv2.imread(str(path))
                if image is None:
                    raise RuntimeError(f"could not read export frame: {path}")
                writer.write(image)
        finally:
            writer.release()
    except Exception as exc:
        mp4_path = None
        print(f"MP4 export unavailable: {exc}")

    pose_path = out / "clip_poses.json"
    pose_path.write_text(
        json.dumps(result["poses"], indent=2, default=float), encoding="utf-8"
    )
    pilot_dir = Path(
        experiment.config.pilot_dir
        or (experiment.config.root / "artifacts/roc_pose_pipeline/smart_rig_move_pilot")
    ).resolve()
    source_mesh = Path(experiment.config.src_glb).resolve()
    camera_fit = Path(
        experiment.config.camera_fit_path
        or (pilot_dir / "roc_sprite_camera_fit.json")
    )
    if not camera_fit.is_absolute():
        camera_fit = (pilot_dir / camera_fit).resolve()

    def _sha256(path: Path) -> str | None:
        if not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    provenance_path = out / "clip_poses.provenance.json"
    provenance_path.write_text(
        json.dumps(
            {
                "unit": experiment.config.unit_name,
                "animation": experiment.config.animation_name,
                "pilot": str(pilot_dir),
                "sourceMesh": str(source_mesh),
                "sourceMeshSha256": _sha256(source_mesh),
                "meshyRigidizationReport": (
                    str(Path(experiment.config.meshy_rigidization_report).resolve())
                    if experiment.config.meshy_rigidization_report
                    else None
                ),
                "cameraFit": str(camera_fit),
                "cameraFitSha256": _sha256(camera_fit),
                "sourceFrameDir": str((pilot_dir / experiment.config.target_frame_dir).resolve()),
                "frameIndices": frames,
                "poseFormat": (
                    "local_xyz_euler_radians_plus_motion_root_translation_and_"
                    "camera_relative_rotation"
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("wrote GIF:", gif_path)
    if mp4_path is not None:
        print("wrote MP4:", mp4_path)
    return {
        "frames": frames,
        "framePaths": [str(path) for path in frame_paths],
        "gif": str(gif_path),
        "mp4": str(mp4_path) if mp4_path is not None else None,
        "poses": str(pose_path),
        "provenance": str(provenance_path),
        "source": "in-memory clip_result; no optimization rerun",
    }


def display_clip_result(
    experiment: RocHybridExperiment,
    output_dir: str | Path | None = None,
    *,
    frame_duration_ms: int = 120,
    display_id: str = "roc_clip_result",
):
    """Display the existing clip GIF inline without rerunning optimization."""
    from IPython.display import Image as IPythonImage, display

    export = export_clip_result(
        experiment,
        output_dir=output_dir,
        frame_duration_ms=frame_duration_ms,
    )
    gif_path = Path(export["gif"])
    image = IPythonImage(filename=str(gif_path), format="gif")
    display(image, display_id=display_id)
    return export


def run_full_animation(experiment: RocHybridExperiment):
    ns = experiment.namespace
    _exec(FULL_SOURCE, ns)
    return ns.get("all_history", [])


def run_semantic_report(experiment: RocHybridExperiment):
    ns = experiment.namespace
    _exec(REPORT_SOURCE, ns)
    return ns.get("semantic_report")
