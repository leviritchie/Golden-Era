"""GPU prop landmark sites: skinned-vertex screen positions for prop IK / veto.

Prop polish must track visual mesh points (sprite landmarks), not raw bone heads.
Bind-pose ``jointSites`` resolve to skinned vertex indices; posed sites come from LBS.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

import numpy as np

from pathlib import Path

from anatomy_probe_veto import load_bone_roles, resolve_prop_joint_node_indices
from gpu_alternate_deform import bind_skinned_vertices


@dataclass(frozen=True)
class PropSiteBinding:
    joint_name: str
    mode: str
    bone_index: int | None = None
    bone_end: str = "head"
    primitive_index: int | None = None
    vertex_index: int | None = None
    global_vertex_index: int | None = None
    local_offset_xyz: tuple[float, float, float] | None = None
    per_frame_global_vertex_index: Mapping[int, int] | None = None
    per_frame_local_offset_xyz: Mapping[int, tuple[float, float, float]] | None = None


def _local_offset_tuple(value: Any) -> tuple[float, float, float]:
    parts = [float(value[index]) for index in range(3)]
    return (parts[0], parts[1], parts[2])


def binding_for_frame(binding: PropSiteBinding, frame_position: int, experiment: Any) -> PropSiteBinding:
    """Resolve per-frame bone-local or skinned-vert overrides from calibration."""
    frame_position = int(frame_position)
    if binding.per_frame_local_offset_xyz is not None:
        local_offset = binding.per_frame_local_offset_xyz.get(frame_position)
        if local_offset is not None:
            return replace(
                binding,
                mode="bone_local_offset",
                local_offset_xyz=_local_offset_tuple(local_offset),
                per_frame_global_vertex_index=None,
                per_frame_local_offset_xyz=None,
            )
    if binding.per_frame_global_vertex_index is None:
        return binding
    global_vertex_index = binding.per_frame_global_vertex_index.get(frame_position)
    if global_vertex_index is None:
        return binding
    primitive_index, vertex_index = _global_vertex_to_primitive_local(
        experiment,
        global_vertex_index=int(global_vertex_index),
    )
    return replace(
        binding,
        mode="skinned_vert",
        primitive_index=int(primitive_index),
        vertex_index=int(vertex_index),
        global_vertex_index=int(global_vertex_index),
        per_frame_global_vertex_index=None,
        per_frame_local_offset_xyz=None,
    )


def _bone_head_world(worlds, bone_index: int) -> np.ndarray:
    return np.asarray(worlds[0, int(bone_index), :3, 3].detach().cpu(), dtype=np.float64)


def _vertex_weight_on_bones(
    primitive: Any,
    *,
    vertex_index: int,
    bone_indices: set[int],
) -> float:
    import torch

    if primitive.joints is None or primitive.normalized_weights is None:
        return 0.0
    joints = primitive.joints[int(vertex_index)].detach().cpu().numpy()
    weights = primitive.normalized_weights[int(vertex_index)].detach().cpu().numpy()
    total = 0.0
    for joint_index, weight in zip(joints, weights, strict=False):
        if int(joint_index) in bone_indices:
            total = max(total, float(weight))
    return total


def _resolve_farthest_skinned_vertex(
    experiment: Any,
    *,
    skin_bone_names: Sequence[str],
    from_bone_name: str,
    min_weight: float,
) -> tuple[int, int]:
    import torch

    name_to_index = experiment.node_index
    skin_indices = {int(name_to_index[str(name)]) for name in skin_bone_names}
    from_index = int(name_to_index[str(from_bone_name)])
    zero_bones = torch.zeros(
        (1, len(experiment.asset.nodes), 3),
        dtype=torch.float32,
        device=experiment.device,
    )
    worlds = experiment._forward_kinematics(zero_bones, bone_mask=experiment.active_node_mask)
    from_pos = _bone_head_world(worlds, from_index)
    bind_verts = bind_skinned_vertices(experiment).detach().cpu().numpy()
    best_dist = -1.0
    best: tuple[int, int] | None = None
    cursor = 0
    for primitive_index, primitive in enumerate(experiment.primitives):
        vertex_count = int(primitive.positions.shape[0])
        for local_index in range(vertex_count):
            global_index = cursor + local_index
            weight = _vertex_weight_on_bones(
                primitive,
                vertex_index=int(local_index),
                bone_indices=skin_indices,
            )
            if weight < float(min_weight):
                continue
            dist = float(np.linalg.norm(bind_verts[global_index] - from_pos))
            if dist > best_dist:
                best_dist = dist
                best = (int(primitive_index), int(local_index))
        cursor += vertex_count
    if best is None:
        raise RuntimeError(
            f"farthest_skinned_vert found no verts for skinBones={list(skin_bone_names)} "
            f"minWeight={min_weight}"
        )
    return best


def _primitive_vertex_offsets(experiment: Any) -> tuple[int, ...]:
    cursor = 0
    offsets: list[int] = []
    for primitive in experiment.primitives:
        offsets.append(cursor)
        cursor += int(primitive.positions.shape[0])
    return tuple(offsets)


def _global_vertex_to_primitive_local(
    experiment: Any,
    *,
    global_vertex_index: int,
) -> tuple[int, int]:
    global_index = int(global_vertex_index)
    if global_index < 0:
        raise ValueError(f"global_vertex_index must be >= 0, got {global_index}")
    offsets = _primitive_vertex_offsets(experiment)
    for primitive_index, offset in enumerate(offsets):
        vertex_count = int(experiment.primitives[primitive_index].positions.shape[0])
        if global_index < offset + vertex_count:
            return int(primitive_index), int(global_index - offset)
    raise ValueError(
        f"global_vertex_index {global_index} out of mesh range "
        f"(vertex_count={offsets[-1] + int(experiment.primitives[-1].positions.shape[0]) if offsets else 0})"
    )


def _resolve_nearest_skinned_vertex_to_bone_head(
    experiment: Any,
    *,
    skin_bone_names: Sequence[str],
    anchor_bone_name: str,
    min_weight: float,
) -> tuple[int, int]:
    """Pick the weighted vert closest to anchor bone head (wrist grip sites)."""
    import torch

    name_to_index = experiment.node_index
    skin_indices = {int(name_to_index[str(name)]) for name in skin_bone_names}
    anchor_index = int(name_to_index[str(anchor_bone_name)])
    zero_bones = torch.zeros(
        (1, len(experiment.asset.nodes), 3),
        dtype=torch.float32,
        device=experiment.device,
    )
    worlds = experiment._forward_kinematics(zero_bones, bone_mask=experiment.active_node_mask)
    anchor_pos = _bone_head_world(worlds, anchor_index)
    bind_verts = bind_skinned_vertices(experiment).detach().cpu().numpy()
    best_dist = None
    best: tuple[int, int] | None = None
    cursor = 0
    for primitive_index, primitive in enumerate(experiment.primitives):
        vertex_count = int(primitive.positions.shape[0])
        for local_index in range(vertex_count):
            global_index = cursor + local_index
            weight = _vertex_weight_on_bones(
                primitive,
                vertex_index=int(local_index),
                bone_indices=skin_indices,
            )
            if weight < float(min_weight):
                continue
            dist = float(np.linalg.norm(bind_verts[global_index] - anchor_pos))
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best = (int(primitive_index), int(local_index))
        cursor += vertex_count
    if best is None:
        raise RuntimeError(
            f"nearest_skinned_vert found no verts for skinBones={list(skin_bone_names)} "
            f"minWeight={min_weight}"
        )
    return best


def resolve_prop_site_bindings(
    experiment: Any,
    *,
    bone_roles_path: str | Any,
    joint_names: Sequence[str],
) -> tuple[PropSiteBinding, ...]:
    roles = load_bone_roles(bone_roles_path)
    joints = roles.get("joints") or {}
    sites = roles.get("jointSites") or {}
    joint_nodes = resolve_prop_joint_node_indices(
        experiment.node_names,
        bone_roles=roles,
        joint_names=joint_names,
    )
    bindings: list[PropSiteBinding] = []
    global_offsets = _primitive_vertex_offsets(experiment)

    for joint_name in joint_names:
        site = sites.get(str(joint_name))
        bone_index = int(joint_nodes[str(joint_name)])
        site_mode = str((site or {}).get("mode") or "bone")
        if site is None or site_mode == "bone":
            bindings.append(
                PropSiteBinding(
                    joint_name=str(joint_name),
                    mode="bone",
                    bone_index=bone_index,
                    bone_end=str((site or {}).get("end") or "head"),
                )
            )
            continue
        if site_mode == "bone_local_offset":
            local = site.get("local")
            if local is None:
                raise ValueError(f"jointSites[{joint_name}] bone_local_offset missing local")
            bindings.append(
                PropSiteBinding(
                    joint_name=str(joint_name),
                    mode="bone_local_offset",
                    bone_index=bone_index,
                    local_offset_xyz=_local_offset_tuple(local),
                )
            )
            continue
        mode = site_mode
        if mode == "explicit_global_vertex":
            global_vertex_index = site.get("globalVertexIndex")
            if global_vertex_index is None:
                raise ValueError(f"jointSites[{joint_name}] explicit_global_vertex missing globalVertexIndex")
            primitive_index, vertex_index = _global_vertex_to_primitive_local(
                experiment,
                global_vertex_index=int(global_vertex_index),
            )
        else:
            skin_bones = [str(name) for name in site.get("skinBones") or []]
            if not skin_bones:
                raise ValueError(f"jointSites[{joint_name}] missing skinBones")
            min_weight = float(site.get("minWeight", 0.2))
            if mode == "farthest_skinned_vert":
                from_bone = str(site.get("fromBone") or joints.get(str(joint_name)))
                primitive_index, vertex_index = _resolve_farthest_skinned_vertex(
                    experiment,
                    skin_bone_names=skin_bones,
                    from_bone_name=from_bone,
                    min_weight=min_weight,
                )
            elif mode == "nearest_skinned_vert":
                anchor_bone = str(site.get("anchorBone") or joints.get(str(joint_name)))
                primitive_index, vertex_index = _resolve_nearest_skinned_vertex_to_bone_head(
                    experiment,
                    skin_bone_names=skin_bones,
                    anchor_bone_name=anchor_bone,
                    min_weight=min_weight,
                )
            else:
                raise ValueError(f"unsupported jointSites mode {mode!r} for {joint_name}")
        global_vertex_index = int(global_offsets[int(primitive_index)] + int(vertex_index))
        bindings.append(
            PropSiteBinding(
                joint_name=str(joint_name),
                mode="skinned_vert",
                bone_index=bone_index,
                primitive_index=int(primitive_index),
                vertex_index=int(vertex_index),
                global_vertex_index=int(global_vertex_index),
            )
        )
    return tuple(bindings)


def load_per_frame_local_offset_calibration(path: str | Any) -> Mapping[int, Mapping[str, tuple[float, float, float]]]:
    import json

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    frames = payload.get("frames") or {}
    out: dict[int, dict[str, tuple[float, float, float]]] = {}
    for frame_key, joint_map in frames.items():
        frame_position = int(frame_key)
        out[frame_position] = {}
        for joint_name, entry in dict(joint_map).items():
            if isinstance(entry, Mapping):
                local = entry.get("local")
                if local is None:
                    continue
                out[frame_position][str(joint_name)] = _local_offset_tuple(local)
            elif isinstance(entry, (list, tuple)) and len(entry) >= 3:
                out[frame_position][str(joint_name)] = _local_offset_tuple(entry)
    return out


def load_per_frame_site_calibration(path: str | Any) -> Mapping[int, Mapping[str, int]]:
    import json

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    frames = payload.get("frames") or {}
    out: dict[int, dict[str, int]] = {}
    for frame_key, joint_map in frames.items():
        frame_position = int(frame_key)
        out[frame_position] = {
            str(joint_name): int(entry.get("globalVertexIndex", entry))
            if isinstance(entry, Mapping)
            else int(entry)
            for joint_name, entry in dict(joint_map).items()
        }
    return out


def resolve_prop_site_bindings_with_calibration(
    experiment: Any,
    *,
    bone_roles_path: str | Any,
    joint_names: Sequence[str],
    per_frame_sites_path: str | Any | None = None,
    per_frame_local_offsets_path: str | Any | None = None,
) -> tuple[PropSiteBinding, ...]:
    bindings = resolve_prop_site_bindings(
        experiment,
        bone_roles_path=bone_roles_path,
        joint_names=joint_names,
    )
    per_frame: Mapping[int, Mapping[str, int]] = {}
    per_frame_local: Mapping[int, Mapping[str, tuple[float, float, float]]] = {}
    if per_frame_sites_path is not None:
        per_frame = load_per_frame_site_calibration(per_frame_sites_path)
    if per_frame_local_offsets_path is not None:
        per_frame_local = load_per_frame_local_offset_calibration(per_frame_local_offsets_path)
    if not per_frame and not per_frame_local:
        return bindings
    joint_to_frames: dict[str, dict[int, int]] = {name: {} for name in joint_names}
    joint_to_local: dict[str, dict[int, tuple[float, float, float]]] = {name: {} for name in joint_names}
    for frame_position, joint_map in per_frame.items():
        for joint_name, global_vertex_index in joint_map.items():
            if str(joint_name) in joint_to_frames:
                joint_to_frames[str(joint_name)][int(frame_position)] = int(global_vertex_index)
    for frame_position, joint_map in per_frame_local.items():
        for joint_name, local_offset in joint_map.items():
            if str(joint_name) in joint_to_local:
                joint_to_local[str(joint_name)][int(frame_position)] = _local_offset_tuple(local_offset)
    return tuple(
        replace(
            binding,
            per_frame_global_vertex_index=joint_to_frames.get(str(binding.joint_name)) or None,
            per_frame_local_offset_xyz=joint_to_local.get(str(binding.joint_name)) or None,
        )
        for binding in bindings
    )


def _world_to_screen(
    experiment: Any,
    points: Any,
    *,
    root_translation: Any,
    root_rotation: Any,
) -> Any:
    import torch

    transformed = experiment._root_transform(points, root_translation, root_rotation)
    screen_x = (
        torch.matmul(transformed, experiment.camera_right) * experiment.px_per_world[0]
        + experiment.camera_offset[0]
    )
    screen_y = (
        torch.matmul(transformed, experiment.camera_down) * experiment.px_per_world[1]
        + experiment.camera_offset[1]
    )
    return torch.stack((screen_x, screen_y), dim=-1)


def _asset_world_from_binding(
    experiment: Any,
    worlds: Any,
    frame_idx: int,
    binding: PropSiteBinding,
    *,
    skinned_by_primitive: dict[int, Any],
) -> Any:
    import torch

    if binding.mode == "bone":
        return worlds[int(frame_idx), int(binding.bone_index), :3, 3]
    if binding.mode == "bone_local_offset":
        bone_mat = worlds[int(frame_idx), int(binding.bone_index)]
        local = binding.local_offset_xyz or (0.0, 0.0, 0.0)
        hom = torch.tensor(
            [float(local[0]), float(local[1]), float(local[2]), 1.0],
            dtype=bone_mat.dtype,
            device=bone_mat.device,
        )
        return (bone_mat @ hom)[:3]
    primitive_index = int(binding.primitive_index)
    if primitive_index not in skinned_by_primitive:
        primitive = experiment.primitives[primitive_index]
        skinned_by_primitive[primitive_index] = experiment._skinned_vertices(worlds, primitive)
    return skinned_by_primitive[primitive_index][int(frame_idx), int(binding.vertex_index), :]


def _screen_binding_frames(
    experiment: Any,
    worlds: Any,
    root_translation: Any,
    root_rotation: Any,
    *,
    binding: PropSiteBinding,
    frame_indices: Sequence[int],
    joint_index: int,
    out: Any,
) -> None:
    skinned_by_primitive: dict[int, Any] = {}
    for frame_idx in frame_indices:
        frame_binding = binding_for_frame(binding, int(frame_idx), experiment)
        point = _asset_world_from_binding(
            experiment,
            worlds,
            int(frame_idx),
            frame_binding,
            skinned_by_primitive=skinned_by_primitive,
        )
        screen = _world_to_screen(
            experiment,
            point.unsqueeze(0).unsqueeze(0),
            root_translation=root_translation[int(frame_idx) : int(frame_idx) + 1],
            root_rotation=root_rotation[int(frame_idx) : int(frame_idx) + 1],
        )
        out[int(frame_idx), int(joint_index), :] = screen[0, 0, :]


def screen_prop_sites_xy(
    experiment: Any,
    bone_vectors: Any,
    root_translation: Any,
    root_rotation: Any,
    *,
    bindings: Sequence[PropSiteBinding],
) -> Any:
    """Return [frames, joints, 2] screen pixels for prop site bindings."""
    import torch

    worlds = experiment._forward_kinematics(
        experiment._bounded_bone_vectors(bone_vectors),
        bone_mask=experiment.active_node_mask,
    )
    frame_count = int(bone_vectors.shape[0])
    joint_count = len(bindings)
    out = torch.zeros((frame_count, joint_count, 2), dtype=torch.float32, device=bone_vectors.device)
    all_frames = tuple(range(frame_count))
    for joint_index, binding in enumerate(bindings):
        has_per_frame = bool(binding.per_frame_global_vertex_index) or bool(binding.per_frame_local_offset_xyz)
        if has_per_frame:
            if binding.mode == "bone" and binding.bone_index is not None:
                screen = experiment._screen_joint_xy(bone_vectors, root_translation, root_rotation)
                out[:, joint_index, :] = screen[:, int(binding.bone_index), :]
            override_frames: set[int] = set()
            if binding.per_frame_global_vertex_index:
                override_frames.update(int(frame_idx) for frame_idx in binding.per_frame_global_vertex_index)
            if binding.per_frame_local_offset_xyz:
                override_frames.update(int(frame_idx) for frame_idx in binding.per_frame_local_offset_xyz)
            _screen_binding_frames(
                experiment,
                worlds,
                root_translation,
                root_rotation,
                binding=binding,
                frame_indices=sorted(override_frames),
                joint_index=int(joint_index),
                out=out,
            )
            continue
        if binding.mode == "bone":
            screen = experiment._screen_joint_xy(bone_vectors, root_translation, root_rotation)
            out[:, joint_index, :] = screen[:, int(binding.bone_index), :]
            continue
        _screen_binding_frames(
            experiment,
            worlds,
            root_translation,
            root_rotation,
            binding=binding,
            frame_indices=all_frames,
            joint_index=int(joint_index),
            out=out,
        )
    return out
