"""Bind-pose + profile-camera bootstrap for DEF-native motion capture."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import torch

from literature_polish_common import poses_from_tensors, unit_mesh
from roc_gpu_cascade_experiment import GpuCascadeConfig, GpuCascadeExperiment

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
ALPHA_THRESHOLD = 8
MOCAP_RASTER = (288, 258)


def sprite_camera_seed(clip_base: Path, unit: str) -> Path:
    for candidate in (
        clip_base / "roc_sprite_camera_fit.json",
        clip_base / f"{unit}_sprite_camera_fit.json",
        ROOT / "artifacts" / "pose_picker_runs" / unit / "roc_sprite_camera_fit.json",
    ):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"missing sprite camera seed for {unit} under {clip_base}")


def mocap_cascade_config(
    *,
    bone_limit_scale_overrides: tuple[tuple[str, float], ...] = (),
) -> GpuCascadeConfig:
    """Objective for the DEF mocap / continuous-tracker lane.

    Self-intersection is a real problem in this lane -- a pure silhouette score is
    indifferent to a head pushed inside the chest, because the torso already covers
    those pixels, so burying the head costs nothing and can even help by removing an
    outline bump the sprite does not have. Measured on h3_roc/idle_start_move_end:
    penetration was 0.0 at bind and saturated from frame 14 on, with the neck/head
    pair Bone_015~Bone_022 the worst offender on 20 of 30 frames.

    The cascade's own ``collision_enabled`` penalty is nevertheless left **off**
    here, and that is deliberate rather than an oversight. It ends in
    ``tanh(sum(violation^2))``, which is flat once a pose interpenetrates deeply;
    an incremental tracker is already in that flat tail before correction starts, so
    the term supplies no descent direction at any weight. Enabling it was tried and
    moved mean penetration only 0.689 -> 0.549, still saturating.

    ``def_continuous_pose_tracker`` therefore owns an unsaturated penalty built on
    ``penetration_norm_from_table``. Turning this flag on as well would double-count
    and add a constant to reported scores without improving the pose.
    """
    return GpuCascadeConfig(
        device="cuda",
        resolution=MOCAP_RASTER,
        alpha_threshold=ALPHA_THRESHOLD,
        score_mode="geometry",
        silhouette_weight=1.0,
        depth_weight=0.0,
        chroma_weight=0.0,
        motion_weight=0.0,
        collision_enabled=False,
        collision_weight=0.0,
        # Empty means one flat joint limit for every bone, which lets the search
        # flail parts the sprite gives no evidence about (roc legs reached 143 deg
        # under a 150 deg flat limit). Supply authored per-group scales via
        # def_anatomy_limits when the unit has them.
        bone_limit_scale_overrides=tuple(bone_limit_scale_overrides),
        root_search_enabled=False,
        root_hypotheses=1,
        root_iterations=0,
        articulated_iterations=0,
        fine_iterations=0,
        optimize_root_translation=False,
        optimize_root_rotation=False,
        root_rotation_defer_camera_up=False,
        optimize_bones=True,
        exact_raster_enabled=True,
    )


def bootstrap_camera_fit(
    *,
    mesh: Path,
    seed_camera: Path,
    frame_dir: Path,
    frame_index: int,
    init_dir: Path,
) -> Path:
    from gpu_depth_silhouette_solver import _resolve_profile_init_resolution
    from gpu_profile_camera_initializer import ProfileCameraInitConfig, initialize_profile_camera

    init_dir.mkdir(parents=True, exist_ok=True)
    profile_fit = init_dir / "profile_camera_fit.json"
    if profile_fit.is_file():
        return profile_fit
    resolution = _resolve_profile_init_resolution(frame_dir, int(frame_index), None, 256, MOCAP_RASTER)
    initialize_profile_camera(
        src_glb=mesh,
        seed_camera_fit=seed_camera,
        target_frame_dir=frame_dir,
        frame_index=int(frame_index),
        output_dir=init_dir,
        config=ProfileCameraInitConfig(resolution=resolution, alpha_threshold=ALPHA_THRESHOLD),
        progress=True,
    )
    if not profile_fit.is_file():
        raise FileNotFoundError(profile_fit)
    return profile_fit


def bind_shell_payload(experiment: GpuCascadeExperiment, camera_fit: Path) -> dict[str, Any]:
    bones, root_t, root_r = experiment._initial_pose_tensors(None)
    poses = poses_from_tensors(experiment, bones, root_t, root_r)
    return {
        "poseUnits": "degrees",
        "poses": poses,
        "cameraFitPath": str(camera_fit.resolve()),
        "config": experiment.config.__dict__.copy(),
        "frameIndices": list(experiment.frame_indices),
        "targetPaths": [str(path) for path in experiment.target_paths],
        "bones": [experiment.node_names[index] for index in experiment.search_node_indices],
        "skinnedBones": [experiment.node_names[index] for index in experiment.active_node_indices],
        "searchBones": list(experiment.search_bone_names),
        "fineBones": list(experiment.fine_bone_names),
        "bindReport": experiment.bind_report,
        "rootPivot": [float(value) for value in experiment.root_pivot.detach().cpu().tolist()],
        "solver": "def_native_mocap",
        "backend": "def_native_mocap_bootstrap",
    }


def bootstrap_flow_mocap_experiment(
    *,
    unit: str,
    clip: str,
    frame_dir: Path,
    frame_indices: list[int],
    init_dir: Path,
    bone_limit_scale_overrides: tuple[tuple[str, float], ...] = (),
) -> tuple[GpuCascadeExperiment, torch.Tensor, torch.Tensor, torch.Tensor, Path, dict[str, Any]]:
    clip_base = ROOT / "artifacts" / "pose_picker_runs" / unit / clip
    mesh = unit_mesh(unit, clip)
    seed_camera = sprite_camera_seed(clip_base, unit)
    camera_fit = bootstrap_camera_fit(
        mesh=mesh,
        seed_camera=seed_camera,
        frame_dir=frame_dir,
        frame_index=int(frame_indices[0]),
        init_dir=init_dir,
    )
    experiment = GpuCascadeExperiment(
        src_glb=mesh,
        camera_fit=camera_fit,
        target_frame_dir=frame_dir,
        frame_indices=frame_indices,
        config=mocap_cascade_config(
            bone_limit_scale_overrides=tuple(bone_limit_scale_overrides)
        ),
    )
    bones, root_t, root_r = experiment._initial_pose_tensors(None)
    shell = bind_shell_payload(experiment, camera_fit)
    return experiment, bones, root_t, root_r, camera_fit, shell
