"""Autonomous non-skeletal deformation experiments for cascade GPU scoring.

Four deformation lanes (hierarchical parenting, auto shape keys, lattice, vertex
arrays) optimize bind-space vertex offsets while bone joint vectors stay at
zero. Collision scoring stays enabled — offsets participate in mesh collision
the same way as the exact raster path.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from cascade_anatomy_bone_order import (
    CATALOG_TRANSIT_GROUP_VISIT_ORDER,
    CATALOG_TRANSIT_ROTATION_SCALE_BY_GROUP,
    load_json,
)
from roc_gpu_cascade_experiment import _axis_angle_matrix


DEFORM_METHODS = (
    "hierarchical_parent",
    "shape_keys",
    "lattice",
    "vertex_array",
)

FUSED_PUSH_PROFILE_REUSE = (
    Path(r"V:/Games/Olden Era Playtest Tweak")
    / "artifacts/pose_picker_runs/h3_roc/idle1_start_move_end/fused_push_080"
    / "fused_push_v10r_no_collision/initialization/profile_camera_fit.json"
)


def prepare_profile_camera_fit(
    hybrid,
    *,
    pilot: Path,
    target: Path,
    frame_indices: Sequence[int],
    output_dir: Path,
    profile_init_enabled: bool = True,
    profile_init_frame: int | None = None,
    profile_init_target_dir: str | Path | None = None,
    profile_init_fit_target_dir: str | Path | None = None,
    profile_init_resolution: tuple[int, int] | None = None,
    profile_init_max_dimension: int = 256,
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
    proxy_resolution: tuple[int, int] = (96, 86),
) -> tuple[Path, dict[str, Any] | None]:
    """Return profile-oriented camera fit for idle anchor frame 7 (profile heading)."""
    seed_camera = (
        Path(hybrid.camera_fit_path).resolve()
        if hybrid.camera_fit_path is not None
        else pilot / "roc_sprite_camera_fit.json"
    )
    if not seed_camera.is_file():
        raise FileNotFoundError(f"profile seed camera is missing: {seed_camera}")
    if not bool(profile_init_enabled):
        return seed_camera, None

    init_dir = Path(output_dir).resolve() / "initialization"
    profile_fit = init_dir / "profile_camera_fit.json"
    report_path = init_dir / "profile_camera_initialization.json"
    mesh_path = Path(hybrid.src_glb).resolve()
    if profile_fit.is_file() and report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report.setdefault("cameraFitPath", str(profile_fit))
        alignment = report.get("meshSpriteAlignment")
        source_mesh = str(report.get("sourceMesh") or "")
        if alignment and source_mesh == str(mesh_path):
            return profile_fit, report
        from gpu_depth_silhouette_solver import (
            _discover_idle_profile_target_dir,
            _resolve_profile_init_resolution,
        )
        from gpu_profile_camera_initializer import (
            ProfileCameraInitConfig,
            validate_profile_mesh_sprite_alignment,
        )

        explicit_init_target = profile_init_target_dir is not None
        init_target_dir = target if not explicit_init_target else Path(profile_init_target_dir)
        if not init_target_dir.is_absolute():
            init_target_dir = (pilot / init_target_dir).resolve()
        if not explicit_init_target:
            init_target_dir = _discover_idle_profile_target_dir(hybrid, pilot, target)
        init_frame = int(
            frame_indices[0]
            if profile_init_frame is None and init_target_dir != target
            else frame_indices[0]
            if profile_init_frame is None
            else profile_init_frame
        )
        alignment = validate_profile_mesh_sprite_alignment(
            src_glb=mesh_path,
            camera_fit=profile_fit,
            target_frame_dir=init_target_dir,
            frame_index=init_frame,
            config=ProfileCameraInitConfig(
                resolution=_resolve_profile_init_resolution(
                    init_target_dir,
                    init_frame,
                    profile_init_resolution,
                    int(profile_init_max_dimension),
                    tuple(int(value) for value in proxy_resolution),
                ),
            ),
        )
        report["meshSpriteAlignment"] = alignment
        report["sourceMesh"] = str(mesh_path)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return profile_fit, report

    if FUSED_PUSH_PROFILE_REUSE.is_file():
        init_dir.mkdir(parents=True, exist_ok=True)
        profile_fit.write_bytes(FUSED_PUSH_PROFILE_REUSE.read_bytes())
        reuse_report = FUSED_PUSH_PROFILE_REUSE.parent / "profile_camera_initialization.json"
        if reuse_report.is_file():
            report = json.loads(reuse_report.read_text(encoding="utf-8"))
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            report.setdefault("cameraFitPath", str(profile_fit))
            return profile_fit, report
        return profile_fit, {"cameraFitPath": str(profile_fit), "reusedFrom": str(FUSED_PUSH_PROFILE_REUSE)}

    from gpu_depth_silhouette_solver import (
        _discover_idle_profile_target_dir,
        _resolve_profile_init_resolution,
    )
    from gpu_profile_camera_initializer import (
        PROFILE_FACING_WEIGHT,
        ProfileCameraInitConfig,
        initialize_profile_camera,
    )

    explicit_init_target = profile_init_target_dir is not None
    init_target_dir = target if not explicit_init_target else Path(profile_init_target_dir)
    if not init_target_dir.is_absolute():
        init_target_dir = (pilot / init_target_dir).resolve()
    if not explicit_init_target:
        init_target_dir = _discover_idle_profile_target_dir(hybrid, pilot, target)
    fit_target_dir = target
    if profile_init_fit_target_dir is not None:
        fit_target_dir = Path(profile_init_fit_target_dir)
        if not fit_target_dir.is_absolute():
            fit_target_dir = (pilot / fit_target_dir).resolve()
    init_frame = int(
        frame_indices[0]
        if profile_init_frame is None and init_target_dir != target
        else frame_indices[0]
        if profile_init_frame is None
        else profile_init_frame
    )
    profile_resolution = _resolve_profile_init_resolution(
        init_target_dir,
        init_frame,
        profile_init_resolution,
        int(profile_init_max_dimension),
        tuple(int(value) for value in proxy_resolution),
    )
    initialization = initialize_profile_camera(
        src_glb=Path(hybrid.src_glb).resolve(),
        seed_camera_fit=seed_camera,
        target_frame_dir=init_target_dir,
        fit_target_frame_dir=fit_target_dir,
        frame_index=init_frame,
        output_dir=init_dir,
        config=ProfileCameraInitConfig(
            resolution=profile_resolution,
            alpha_threshold=int(getattr(hybrid, "proxy_target_alpha_threshold", 8)),
            predicted_alpha_threshold=0.01,
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
        progress=True,
    )
    return initialization.camera_fit_path, initialization.to_dict()


def frozen_root_tensors(experiment, batch: int) -> tuple[Any, Any]:
    """Profile-locked root pose used for every alternate-deform raster/score call."""
    import torch

    root_translation = getattr(experiment, "_alternate_deform_root_translation", None)
    root_rotation = getattr(experiment, "_alternate_deform_root_rotation", None)
    if root_translation is None or root_rotation is None:
        zeros = torch.zeros((batch, 3), dtype=torch.float32, device=experiment.device)
        return zeros, zeros
    root_t = root_translation.to(device=experiment.device, dtype=torch.float32)
    root_r = root_rotation.to(device=experiment.device, dtype=torch.float32)
    if int(root_t.shape[0]) == 1 and batch > 1:
        root_t = root_t.expand(batch, -1)
        root_r = root_r.expand(batch, -1)
    elif int(root_t.shape[0]) != batch:
        raise ValueError(f"alternate deform root batch {root_t.shape[0]} != {batch}")
    return root_t, root_r


def attach_profile_locked_root(experiment, profile_report: Mapping[str, Any] | None) -> None:
    """Store identity root with profile heading in camera fit (yaw baked into basis)."""
    import torch

    experiment._alternate_deform_profile_report = dict(profile_report or {})
    experiment._alternate_deform_root_translation = torch.zeros(
        (1, 3), dtype=torch.float32, device=experiment.device
    )
    experiment._alternate_deform_root_rotation = torch.zeros(
        (1, 3), dtype=torch.float32, device=experiment.device
    )
    best = (profile_report or {}).get("best") or {}
    yaw_deg = float(best.get("yawDeg", 0.0))
    roll_deg = float(best.get("rollDeg", 0.0))
    if abs(yaw_deg) > 1e-6 or abs(roll_deg) > 1e-6:
        # Profile search can leave residual heading in yaw/roll; apply on camera_up
        # only so we stay profile-honest (no sideways transit cheat).
        experiment._alternate_deform_root_rotation[0, 2] = math.radians(yaw_deg)
        if abs(roll_deg) > 1e-6:
            experiment._alternate_deform_root_rotation[0, 1] = math.radians(roll_deg)


@dataclass(frozen=True)
class AlternateDeformState:
    group_names: tuple[str, ...]
    group_masks: Any  # torch (G, V) bool
    bind_skinned: Any  # torch (V, 3)
    group_centroids: Any  # torch (G, 3)
    rotation_scales: np.ndarray  # (G,)
    camera_basis: Any  # torch (3, 3)
    vertex_count: int
    shape_key_bases: Any | None = None  # torch (B, V, 3)
    shape_key_basis_groups: tuple[int, ...] = ()
    shape_key_symmetry_pairs: tuple[tuple[int, int, bool], ...] = ()
    group_influence: Any | None = None  # torch (G, V) soft skin weights
    lattice_min: Any | None = None
    lattice_size: Any | None = None
    lattice_grid: int = 2


def _camera_basis_matrix(experiment) -> Any:
    import torch

    return torch.stack(
        (
            experiment.camera_forward,
            experiment.camera_right,
            experiment.camera_down,
        ),
        dim=0,
    )


def bind_skinned_vertices(experiment) -> Any:
    """Bind-pose skinned vertices at zero FK, concatenated across primitives."""
    import torch

    node_count = len(experiment.asset.nodes)
    zero_bones = torch.zeros((1, node_count, 3), dtype=torch.float32, device=experiment.device)
    worlds = experiment._forward_kinematics(zero_bones, bone_mask=experiment.active_node_mask)
    parts = []
    for primitive in experiment.primitives:
        parts.append(experiment._skinned_vertices(worlds, primitive)[0])
    return torch.cat(parts, dim=0)


def build_group_vertex_masks(
    experiment,
    *,
    groups_catalog: Mapping[str, Any],
    group_visit_order: Sequence[str],
    influence_threshold: float = 0.12,
) -> tuple[tuple[str, ...], Any]:
    """Exclusive vertex→group assignment from skin-weight peaks."""
    import torch

    bind = bind_skinned_vertices(experiment)
    vertex_count = int(bind.shape[0])
    group_names = tuple(str(name) for name in group_visit_order)
    group_count = len(group_names)
    influence = torch.zeros((group_count, vertex_count), dtype=torch.float32, device=experiment.device)
    primitive_cursor = 0
    for primitive in experiment.primitives:
        vertex_count_prim = int(primitive.positions.shape[0])
        if primitive.joints is None or primitive.normalized_weights is None:
            primitive_cursor += vertex_count_prim
            continue
        for group_index, group_name in enumerate(group_names):
            bones = groups_catalog["groups"][group_name]["bonesDependencyOrder"]
            bone_indices = [experiment.node_index[str(name)] for name in bones]
            mask = torch.zeros((vertex_count_prim,), dtype=torch.bool, device=experiment.device)
            for bone_index in bone_indices:
                matches = primitive.joints == int(bone_index)
                if bool(matches.any()):
                    mask = mask | matches.any(dim=-1)
            if not bool(mask.any()):
                continue
            weights = primitive.normalized_weights[mask]
            joint_rows = primitive.joints[mask]
            group_weight = torch.zeros((int(mask.sum().item()),), dtype=torch.float32, device=experiment.device)
            for bone_index in bone_indices:
                bone_matches = joint_rows == int(bone_index)
                if bool(bone_matches.any()):
                    group_weight = torch.maximum(
                        group_weight,
                        (weights * bone_matches.to(weights.dtype)).sum(dim=-1),
                    )
            global_index = torch.arange(vertex_count_prim, device=experiment.device)[mask]
            influence[group_index, global_index + primitive_cursor] = group_weight
        primitive_cursor += vertex_count_prim
    peak_group = influence.argmax(dim=0)
    peak_value = influence.max(dim=0).values
    assigned = peak_value >= float(influence_threshold)
    masks = torch.zeros((group_count, vertex_count), dtype=torch.bool, device=experiment.device)
    for group_index in range(group_count):
        masks[group_index] = assigned & (peak_group == group_index)
    uncovered = int((~assigned).sum().item())
    if uncovered > 0:
        raise RuntimeError(
            f"alternate deform left {uncovered} vertices without anatomy group assignment"
        )
    return group_names, masks


def build_group_influence_weights(
    experiment,
    *,
    groups_catalog: Mapping[str, Any],
    group_visit_order: Sequence[str],
) -> tuple[tuple[str, ...], Any]:
    """Per-group skin-weight influence per vertex (non-exclusive, overlapping allowed)."""
    import torch

    vertex_count = int(bind_skinned_vertices(experiment).shape[0])
    group_names = tuple(str(name) for name in group_visit_order)
    group_count = len(group_names)
    influence = torch.zeros((group_count, vertex_count), dtype=torch.float32, device=experiment.device)
    primitive_cursor = 0
    for primitive in experiment.primitives:
        vertex_count_prim = int(primitive.positions.shape[0])
        if primitive.joints is None or primitive.normalized_weights is None:
            primitive_cursor += vertex_count_prim
            continue
        for group_index, group_name in enumerate(group_names):
            bones = groups_catalog["groups"][group_name]["bonesDependencyOrder"]
            bone_indices = [experiment.node_index[str(name)] for name in bones]
            mask = torch.zeros((vertex_count_prim,), dtype=torch.bool, device=experiment.device)
            for bone_index in bone_indices:
                matches = primitive.joints == int(bone_index)
                if bool(matches.any()):
                    mask = mask | matches.any(dim=-1)
            if not bool(mask.any()):
                continue
            weights = primitive.normalized_weights[mask]
            joint_rows = primitive.joints[mask]
            group_weight = torch.zeros((int(mask.sum().item()),), dtype=torch.float32, device=experiment.device)
            for bone_index in bone_indices:
                bone_matches = joint_rows == int(bone_index)
                if bool(bone_matches.any()):
                    group_weight = torch.maximum(
                        group_weight,
                        (weights * bone_matches.to(weights.dtype)).sum(dim=-1),
                    )
            global_index = torch.arange(vertex_count_prim, device=experiment.device)[mask]
            influence[group_index, global_index + primitive_cursor] = torch.maximum(
                influence[group_index, global_index + primitive_cursor],
                group_weight,
            )
        primitive_cursor += vertex_count_prim
    return group_names, influence


def build_alternate_deform_state(
    experiment,
    *,
    groups_catalog_path: Path,
    group_visit_order: Sequence[str] | None = None,
    probe_deg: float = 18.0,
    lattice_grid: int = 2,
    shape_keys_mode: str = "legacy",
) -> AlternateDeformState:
    import torch

    catalog = load_json(groups_catalog_path)
    visit = tuple(group_visit_order or CATALOG_TRANSIT_GROUP_VISIT_ORDER)
    group_names, group_masks = build_group_vertex_masks(
        experiment,
        groups_catalog=catalog,
        group_visit_order=visit,
    )
    bind = bind_skinned_vertices(experiment)
    group_centroids = []
    for group_index in range(len(group_names)):
        mask = group_masks[group_index]
        if not bool(mask.any()):
            raise RuntimeError(f"group {group_names[group_index]!r} has empty vertex mask")
        group_centroids.append(bind[mask].mean(dim=0))
    rotation_scales = np.asarray(
        [float(CATALOG_TRANSIT_ROTATION_SCALE_BY_GROUP.get(name, 1.0)) for name in group_names],
        dtype=np.float64,
    )
    group_influence = None
    basis_groups: tuple[int, ...] = ()
    symmetry_pairs: tuple[tuple[int, int, bool], ...] = ()
    mode = str(shape_keys_mode)
    if mode == "rich":
        group_names_inf, group_influence = build_group_influence_weights(
            experiment,
            groups_catalog=catalog,
            group_visit_order=visit,
        )
        if group_names_inf != group_names:
            raise RuntimeError("group influence visit order drifted from exclusive masks")
        shape_bases, basis_groups, symmetry_pairs = _build_rich_shape_key_bases(
            experiment,
            catalog=catalog,
            group_names=group_names,
            group_influence=group_influence,
            bind=bind,
            probe_deg=float(probe_deg),
        )
    else:
        shape_bases = _build_auto_shape_key_bases(
            experiment,
            catalog=catalog,
            group_names=group_names,
            group_masks=group_masks,
            bind=bind,
            probe_deg=float(probe_deg),
        )
        basis_groups = tuple(range(len(group_names)))
    lattice_min = bind.min(dim=0).values
    lattice_size = (bind.max(dim=0).values - lattice_min).clamp_min(1e-4)
    return AlternateDeformState(
        group_names=group_names,
        group_masks=group_masks,
        bind_skinned=bind,
        group_centroids=torch.stack(group_centroids, dim=0),
        rotation_scales=rotation_scales,
        camera_basis=_camera_basis_matrix(experiment),
        vertex_count=int(bind.shape[0]),
        shape_key_bases=shape_bases,
        shape_key_basis_groups=basis_groups,
        shape_key_symmetry_pairs=symmetry_pairs,
        group_influence=group_influence,
        lattice_min=lattice_min,
        lattice_size=lattice_size,
        lattice_grid=int(lattice_grid),
    )


def _build_auto_shape_key_bases(
    experiment,
    *,
    catalog: Mapping[str, Any],
    group_names: Sequence[str],
    group_masks: Any,
    bind: Any,
    probe_deg: float,
) -> Any:
    """Probe +primary-bone rotation per group; store vertex displacement bases."""
    import torch

    angle = math.radians(float(probe_deg))
    bases = torch.zeros(
        (len(group_names), int(bind.shape[0]), 3),
        dtype=torch.float32,
        device=experiment.device,
    )
    node_count = len(experiment.asset.nodes)
    for group_index, group_name in enumerate(group_names):
        primary_bone = str(catalog["groups"][group_name]["bonesDependencyOrder"][0])
        bone_index = int(experiment.node_index[primary_bone])
        vectors = torch.zeros((1, node_count, 3), dtype=torch.float32, device=experiment.device)
        vectors[0, bone_index] = experiment.camera_right * angle
        worlds = experiment._forward_kinematics(vectors, bone_mask=experiment.active_node_mask)
        parts = []
        for primitive in experiment.primitives:
            parts.append(experiment._skinned_vertices(worlds, primitive)[0])
        posed = torch.cat(parts, dim=0)
        displacement = posed - bind
        mask = group_masks[group_index]
        bases[group_index] = displacement * mask.to(displacement.dtype).unsqueeze(-1)
    return bases


def _probe_bone_displacement(
    experiment,
    bind: Any,
    bone_index: int,
    axis_vector: Any,
    angle_rad: float,
) -> Any:
    import torch

    node_count = len(experiment.asset.nodes)
    vectors = torch.zeros((1, node_count, 3), dtype=torch.float32, device=experiment.device)
    vectors[0, int(bone_index)] = axis_vector * float(angle_rad)
    worlds = experiment._forward_kinematics(vectors, bone_mask=experiment.active_node_mask)
    parts = [experiment._skinned_vertices(worlds, primitive)[0] for primitive in experiment.primitives]
    return torch.cat(parts, dim=0) - bind


def _normalize_shape_basis(basis: Any, influence: Any, min_influence: float = 0.05) -> Any:
    import torch

    mask = influence >= float(min_influence)
    if not bool(mask.any()):
        return basis
    active = basis[mask]
    scale = active.abs().amax()
    if float(scale.item()) <= 1e-8:
        return basis
    return basis / scale


def _build_rich_shape_key_bases(
    experiment,
    *,
    catalog: Mapping[str, Any],
    group_names: Sequence[str],
    group_influence: Any,
    bind: Any,
    probe_deg: float,
) -> tuple[Any, tuple[int, ...], tuple[tuple[int, int, bool], ...]]:
    """Multi-bone ±axis probes with influence-weighted, unit-scaled displacement bases."""
    import torch

    angle = math.radians(float(probe_deg))
    axis_vectors = {
        "camera_right": experiment.camera_right,
        "camera_down": experiment.camera_down,
        "camera_forward": experiment.camera_forward,
    }
    bilateral = (("wing_a", "wing_b"), ("leg_a", "leg_b"))
    basis_meta: list[tuple[str, str, str, float]] = []
    bases: list[Any] = []
    basis_groups: list[int] = []
    for group_index, group_name in enumerate(group_names):
        bones = [str(b) for b in catalog["groups"][group_name]["bonesDependencyOrder"]]
        probe_bones: list[str] = [bones[0]]
        if len(bones) >= 2:
            probe_bones.append(bones[-1])
        influence = group_influence[group_index]
        for bone_name in probe_bones:
            bone_index = int(experiment.node_index[bone_name])
            for axis_name in ("camera_right", "camera_down"):
                axis = axis_vectors[axis_name]
                for sign in (-1.0, 1.0):
                    displacement = _probe_bone_displacement(
                        experiment,
                        bind,
                        bone_index,
                        axis,
                        angle * sign,
                    )
                    basis = displacement * influence.unsqueeze(-1)
                    basis = _normalize_shape_basis(basis, influence)
                    bases.append(basis)
                    basis_groups.append(int(group_index))
                    basis_meta.append((str(group_name), bone_name, axis_name, float(sign)))

    def _bone_role(group_name: str, bone_name: str) -> str:
        bones = [str(b) for b in catalog["groups"][group_name]["bonesDependencyOrder"]]
        if bone_name == bones[0]:
            return "proximal"
        if bone_name == bones[-1]:
            return "distal"
        return "mid"

    symmetry_pairs: list[tuple[int, int, bool]] = []
    for left_name, right_name in bilateral:
        left_entries = [
            (index, (_bone_role(left_name, bone), axis, sign))
            for index, (group_name, bone, axis, sign) in enumerate(basis_meta)
            if group_name == left_name
        ]
        right_by_key = {
            (_bone_role(right_name, bone), axis, sign): index
            for index, (group_name, bone, axis, sign) in enumerate(basis_meta)
            if group_name == right_name
        }
        for left_index, key in left_entries:
            right_index = right_by_key.get(key)
            if right_index is None:
                raise RuntimeError(
                    f"rich shape key symmetry missing counterpart for {left_name} {key!r}"
                )
            negate = key[1] in ("camera_right", "camera_forward")
            symmetry_pairs.append((int(left_index), int(right_index), bool(negate)))

    stacked = torch.stack(bases, dim=0)
    return stacked, tuple(basis_groups), tuple(symmetry_pairs)


def _rotation_from_camera_euler(
    state: AlternateDeformState,
    euler_deg: np.ndarray,
    device,
) -> Any:
    import torch

    radians = torch.as_tensor(np.deg2rad(euler_deg), dtype=torch.float32, device=device)
    axis_vectors = torch.matmul(radians.unsqueeze(0), state.camera_basis).squeeze(0)
    return _axis_angle_matrix(axis_vectors)


def offsets_hierarchical_parent(
    state: AlternateDeformState,
    params: np.ndarray,
    device,
) -> Any:
    """Visit-order sequential rigid groups in camera Euler + translation."""
    import torch

    group_count = len(state.group_names)
    current = state.bind_skinned.clone()
    param_cursor = 0
    for group_index in range(group_count):
        euler = params[param_cursor : param_cursor + 3]
        trans = params[param_cursor + 3 : param_cursor + 6]
        param_cursor += 6
        mask = state.group_masks[group_index]
        if not bool(mask.any()):
            continue
        centroid = current[mask].mean(dim=0)
        rotation = _rotation_from_camera_euler(state, euler, device)
        local = current[mask] - centroid
        rotated = torch.matmul(local, rotation.transpose(0, 1))
        camera_trans = torch.matmul(
            torch.as_tensor(trans, dtype=torch.float32, device=device),
            state.camera_basis,
        )
        current[mask] = rotated + centroid + camera_trans
    return current - state.bind_skinned


def offsets_shape_keys(state: AlternateDeformState, params: np.ndarray, device) -> Any:
    import torch

    weights = torch.as_tensor(params, dtype=torch.float32, device=device)
    if state.shape_key_bases is None:
        raise RuntimeError("shape_key_bases missing from AlternateDeformState")
    basis_count = int(state.shape_key_bases.shape[0])
    if basis_count == len(state.group_names):
        return torch.einsum("g,gvd->vd", weights, state.shape_key_bases)
    return torch.einsum("b,bvd->vd", weights, state.shape_key_bases)


def offsets_vertex_array(state: AlternateDeformState, params: np.ndarray, device) -> Any:
    import torch

    group_count = len(state.group_names)
    translations = torch.as_tensor(params, dtype=torch.float32, device=device).reshape(group_count, 3)
    camera_trans = torch.matmul(translations, state.camera_basis)
    delta = torch.zeros((state.vertex_count, 3), dtype=torch.float32, device=device)
    for group_index in range(group_count):
        mask = state.group_masks[group_index]
        delta[mask] = delta[mask] + camera_trans[group_index]
    return delta


def _lattice_weights(normalized: Any, grid: int) -> tuple[Any, Any, Any, Any]:
    import torch

    scaled = normalized * float(grid - 1)
    low = torch.floor(scaled).clamp(0.0, float(grid - 2))
    frac = scaled - low
    return low, frac, low + 1.0, frac


def offsets_lattice(state: AlternateDeformState, params: np.ndarray, device) -> Any:
    import torch

    grid = int(state.lattice_grid)
    control = torch.as_tensor(params, dtype=torch.float32, device=device).reshape(grid, grid, grid, 3)
    normalized = (state.bind_skinned - state.lattice_min) / state.lattice_size
    low, frac, high, _ = _lattice_weights(normalized, grid)
    ix = low[:, 0].long()
    iy = low[:, 1].long()
    iz = low[:, 2].long()
    fx = frac[:, 0]
    fy = frac[:, 1]
    fz = frac[:, 2]
    disp = torch.zeros((state.vertex_count, 3), dtype=torch.float32, device=device)
    for dx in (0, 1):
        wx = (1.0 - fx) if dx == 0 else fx
        for dy in (0, 1):
            wy = (1.0 - fy) if dy == 0 else fy
            for dz in (0, 1):
                wz = (1.0 - fz) if dz == 0 else fz
                weight = wx * wy * wz
                indices_x = ix + dx
                indices_y = iy + dy
                indices_z = iz + dz
                corner = control[indices_x, indices_y, indices_z]
                disp = disp + corner * weight.unsqueeze(-1)
    return disp


def params_dim(state: AlternateDeformState, method: str) -> int:
    group_count = len(state.group_names)
    if method == "hierarchical_parent":
        return group_count * 6
    if method in ("shape_keys", "shape_keys_rich"):
        if state.shape_key_bases is None:
            raise RuntimeError("shape_key_bases missing for shape key params_dim")
        return int(state.shape_key_bases.shape[0])
    if method == "vertex_array":
        return group_count * 3
    if method == "lattice":
        grid = int(state.lattice_grid)
        return grid * grid * grid * 3
    raise ValueError(f"unknown alternate deform method: {method!r}")


def offsets_from_params(state: AlternateDeformState, method: str, params: np.ndarray, device) -> Any:
    if method == "hierarchical_parent":
        return offsets_hierarchical_parent(state, params, device)
    if method in ("shape_keys", "shape_keys_rich"):
        return offsets_shape_keys(state, params, device)
    if method == "vertex_array":
        return offsets_vertex_array(state, params, device)
    if method == "lattice":
        return offsets_lattice(state, params, device)
    raise ValueError(f"unknown alternate deform method: {method!r}")


def _symmetry_mirror_params(
    state: AlternateDeformState,
    params: np.ndarray,
    method: str,
    *,
    pair_names: Sequence[tuple[str, str]],
) -> np.ndarray:
    mirrored = params.copy()
    if method == "hierarchical_parent":
        stride = 6
        for left, right in pair_names:
            left_index = state.group_names.index(left)
            right_index = state.group_names.index(right)
            mirrored[right_index * stride : (right_index + 1) * stride] = params[
                left_index * stride : (left_index + 1) * stride
            ]
            mirrored[right_index * stride + 1] *= -1.0
            mirrored[right_index * stride + 4] *= -1.0
    elif method == "shape_keys":
        for left, right in pair_names:
            left_index = state.group_names.index(left)
            right_index = state.group_names.index(right)
            mirrored[right_index] = params[left_index]
    elif method == "shape_keys_rich":
        for left_index, right_index, negate in state.shape_key_symmetry_pairs:
            value = float(params[left_index])
            mirrored[right_index] = -value if negate else value
    elif method == "vertex_array":
        stride = 3
        for left, right in pair_names:
            left_index = state.group_names.index(left)
            right_index = state.group_names.index(right)
            mirrored[right_index * stride : (right_index + 1) * stride] = params[
                left_index * stride : (left_index + 1) * stride
            ]
            mirrored[right_index * stride + 1] *= -1.0
    return mirrored


def evaluate_offsets(
    experiment,
    offsets: Any,
    *,
    frame_index: int | None = None,
) -> dict[str, Any]:
    import torch

    batch = int(offsets.shape[0])
    node_count = len(experiment.asset.nodes)
    bone_vectors = torch.zeros((batch, node_count, 3), dtype=torch.float32, device=experiment.device)
    root_translation, root_rotation = frozen_root_tensors(experiment, batch)
    frame_indices = None if frame_index is None else (int(frame_index),)
    return experiment.evaluate(
        bone_vectors,
        root_translation,
        root_rotation,
        frame_indices=frame_indices,
        vertex_offsets=offsets,
    )


def score_offsets(experiment, offsets: Any, *, frame_index: int) -> float:
    components = evaluate_offsets(experiment, offsets, frame_index=frame_index)
    return float(components["score"][0].detach().item())


def _step_sizes(state: AlternateDeformState, method: str) -> np.ndarray:
    group_count = len(state.group_names)
    if method == "hierarchical_parent":
        steps = np.zeros((group_count * 6,), dtype=np.float64)
        for group_index in range(group_count):
            scale = float(state.rotation_scales[group_index])
            base = group_index * 6
            steps[base : base + 3] = 6.0 * scale
            steps[base + 3 : base + 6] = 0.04 * scale
        return steps
    if method == "shape_keys":
        return np.full((params_dim(state, method),), 0.12, dtype=np.float64)
    if method == "shape_keys_rich":
        return np.full((params_dim(state, method),), 0.2, dtype=np.float64)
    if method == "vertex_array":
        return np.full((group_count * 3,), 0.03, dtype=np.float64)
    grid = int(state.lattice_grid)
    return np.full((grid * grid * grid * 3,), 0.02, dtype=np.float64)


def optimize_frame_offsets(
    experiment,
    state: AlternateDeformState,
    *,
    method: str,
    frame_index: int,
    seed_params: np.ndarray | None = None,
    max_rounds: int = 4,
    symmetry_pairs: Sequence[tuple[str, str]] = (),
) -> tuple[np.ndarray, float]:
    dim = params_dim(state, method)
    params = np.zeros((dim,), dtype=np.float64)
    if seed_params is not None:
        params = np.asarray(seed_params, dtype=np.float64).reshape(-1).copy()
        if params.shape[0] != dim:
            raise ValueError(f"seed params dim {params.shape[0]} != expected {dim}")
    steps = _step_sizes(state, method)
    device = experiment.device
    best_score = score_offsets(
        experiment,
        offsets_from_params(state, method, params, device).unsqueeze(0),
        frame_index=frame_index,
    )
    for _round in range(int(max_rounds)):
        improved = False
        for dim_index in range(dim):
            for direction in (-1.0, 1.0):
                trial = params.copy()
                trial[dim_index] += direction * steps[dim_index]
                if symmetry_pairs and method != "shape_keys_rich":
                    trial = _symmetry_mirror_params(state, trial, method, pair_names=symmetry_pairs)
                elif method == "shape_keys_rich":
                    trial = _symmetry_mirror_params(state, trial, method, pair_names=())
                offsets = offsets_from_params(state, method, trial, device).unsqueeze(0)
                trial_score = score_offsets(experiment, offsets, frame_index=frame_index)
                if trial_score > best_score:
                    params = trial
                    best_score = trial_score
                    improved = True
        if not improved:
            break
    return params, best_score


def optimize_clip_offsets(
    experiment,
    state: AlternateDeformState,
    *,
    method: str,
    max_rounds: int = 4,
    symmetry_pairs: Sequence[tuple[str, str]] = (
        ("wing_a", "wing_b"),
        ("leg_a", "leg_b"),
    ),
) -> dict[str, Any]:
    import torch

    frame_count = len(experiment.frame_indices)
    dim = params_dim(state, method)
    per_frame_params: list[np.ndarray] = []
    per_frame_scores: list[float] = []
    seed: np.ndarray | None = None
    for frame_index in experiment.frame_indices:
        params, frame_score = optimize_frame_offsets(
            experiment,
            state,
            method=method,
            frame_index=int(frame_index),
            seed_params=seed,
            max_rounds=max_rounds,
            symmetry_pairs=symmetry_pairs,
        )
        per_frame_params.append(params)
        per_frame_scores.append(frame_score)
        seed = params
    offsets = torch.stack(
        [
            offsets_from_params(state, method, params, experiment.device)
            for params in per_frame_params
        ],
        dim=0,
    )
    clip_components = evaluate_offsets(experiment, offsets)
    clip_scores = clip_components["score"].detach().cpu().numpy().tolist()
    clip_mean = float(np.mean(clip_scores))
    collision = clip_components.get("collisionError")
    collision_values = (
        collision.detach().cpu().numpy().tolist()
        if collision is not None
        else [0.0] * frame_count
    )
    return {
        "method": method,
        "score": clip_mean,
        "frameScores": clip_scores,
        "perFrameGreedyScores": per_frame_scores,
        "collisionError": collision_values,
        "paramsDim": int(dim),
        "perFrameParams": [params.tolist() for params in per_frame_params],
        "offsets": offsets,
        "config": {
            "collision_enabled": bool(experiment.config.collision_enabled),
            "collision_weight": float(experiment.config.collision_weight),
            "max_rounds": int(max_rounds),
        },
    }


def export_solved_rgb(
    experiment,
    offsets: Any,
    output_dir: Path,
) -> Path:
    import torch
    from PIL import Image

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    batch = int(offsets.shape[0])
    node_count = len(experiment.asset.nodes)
    bone_vectors = torch.zeros((batch, node_count, 3), dtype=torch.float32, device=experiment.device)
    root_translation, root_rotation = frozen_root_tensors(experiment, batch)
    rgb, alpha, depth = experiment.exact_triangle_rgb(
        bone_vectors,
        root_translation,
        root_rotation,
        vertex_offsets=offsets,
    )
    images = []
    for frame_position, frame in enumerate(experiment.frame_indices):
        array = (
            rgb[frame_position].detach().clamp(0.0, 1.0).mul(255.0).byte().cpu().numpy()
        )
        image = Image.fromarray(array, "RGB")
        stem = f"{int(frame):02d}"
        image.save(output_dir / f"{stem}.png", format="PNG", compress_level=0)
        images.append(image)
    gif_path = output_dir / "gpu_solved_rgb.gif"
    images[0].save(
        gif_path,
        save_all=True,
        append_images=images[1:],
        duration=83,
        loop=0,
        optimize=False,
    )
    return gif_path


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def persist_alternate_deform_result(
    result: Mapping[str, Any],
    output_dir: Path,
    *,
    experiment_config: Any,
    profile_initialization: Mapping[str, Any] | None = None,
) -> Path:
    from dataclasses import asdict, is_dataclass

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if is_dataclass(experiment_config):
        config_payload = _json_safe(asdict(experiment_config))
    elif isinstance(experiment_config, Mapping):
        config_payload = _json_safe(dict(experiment_config))
    else:
        config_payload = {}
    profile_payload = _json_safe(dict(profile_initialization or {}))
    serializable = {
        "solver": "alternate_deform",
        "method": result.get("method"),
        "score": result.get("score"),
        "frameScores": result.get("frameScores"),
        "perFrameGreedyScores": result.get("perFrameGreedyScores"),
        "collisionError": result.get("collisionError"),
        "paramsDim": result.get("paramsDim"),
        "perFrameParams": result.get("perFrameParams"),
        "config": config_payload,
        "alternateDeformConfig": result.get("config"),
        "profileCameraFitPath": profile_payload.get("cameraFitPath"),
        "profileInitialization": profile_payload or None,
    }
    path = output_dir / "gpu_clip_result.json"
    path.write_text(json.dumps(serializable, indent=2) + "\n", encoding="utf-8")
    return path


def run_alternate_deform_method(
    experiment,
    *,
    method: str,
    output_dir: Path,
    groups_catalog_path: Path,
    max_rounds: int = 4,
    probe_deg: float = 18.0,
    lattice_grid: int = 2,
    shape_keys_mode: str = "legacy",
) -> dict[str, Any]:
    started = time.perf_counter()
    resolved_shape_mode = "rich" if method == "shape_keys_rich" else str(shape_keys_mode)
    state = build_alternate_deform_state(
        experiment,
        groups_catalog_path=groups_catalog_path,
        probe_deg=probe_deg,
        lattice_grid=lattice_grid,
        shape_keys_mode=resolved_shape_mode,
    )
    result = optimize_clip_offsets(
        experiment,
        state,
        method=method,
        max_rounds=max_rounds,
    )
    offsets = result.pop("offsets")
    output_dir = Path(output_dir)
    export_solved_rgb(experiment, offsets, output_dir / "solved_rgb")
    persist_alternate_deform_result(
        result,
        output_dir,
        experiment_config=experiment.config,
        profile_initialization=getattr(experiment, "_alternate_deform_profile_report", None),
    )
    result["elapsedSec"] = round(time.perf_counter() - started, 1)
    result["outputDir"] = str(output_dir)
    result["shapeKeyBasisCount"] = (
        int(state.shape_key_bases.shape[0]) if state.shape_key_bases is not None else 0
    )
    result["shapeKeysMode"] = resolved_shape_mode
    (output_dir / "alternate_deform_report.json").write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    return result
