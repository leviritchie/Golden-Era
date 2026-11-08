"""Differentiable fixed-length FK and LBS for pose refinement.

Local extra rotations are axis-angle (radians) composed onto a frozen capture
local rotation. Bone offsets stay the bind offsets. This is the missing
rotation→FK gradient path; the skin-weight solver still precomputes and detaches
its transformed candidates and is not used here.

Wrap-safe geodesic distance treats ±2π as the same rotation. Axial twist is a
free parameter of the local rotation, not captured evidence.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

TWIST_POLICY = "minimum_change_prior_not_captured_evidence"


def clamp_axis_angle_magnitude_np(omega: np.ndarray, max_rad: float) -> np.ndarray:
    """Scale each axis-angle so ‖ω‖ ≤ max_rad. Does not clamp components independently."""
    values = np.asarray(omega, dtype=np.float64)
    if float(max_rad) <= 0:
        raise ValueError("max_rad must be positive")
    theta = np.linalg.norm(values, axis=-1, keepdims=True)
    scale = np.minimum(1.0, float(max_rad) / np.maximum(theta, 1e-12))
    return values * scale


def wrap_axis_angle_np(omega: np.ndarray) -> np.ndarray:
    """Map each axis-angle vector onto (-π, π] without changing the rotation."""
    values = np.asarray(omega, dtype=np.float64)
    theta = np.linalg.norm(values, axis=-1, keepdims=True)
    wrapped = np.mod(theta + math.pi, 2.0 * math.pi) - math.pi
    scale = np.ones_like(theta)
    nonzero = theta[..., 0] > 1e-8
    scale[nonzero] = wrapped[nonzero] / theta[nonzero]
    return values * scale


def so3_geodesic_np(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """Unsigned geodesic angle (radians) between rotation matrices."""
    a = np.asarray(first, dtype=np.float64)
    b = np.asarray(second, dtype=np.float64)
    relative = np.swapaxes(a, -1, -2) @ b
    trace = np.trace(relative, axis1=-2, axis2=-1)
    cosine = np.clip((trace - 1.0) * 0.5, -1.0, 1.0)
    return np.arccos(cosine)


def so3_exp_np(omega: np.ndarray) -> np.ndarray:
    """Rodrigues map. Zero vector is identity."""
    values = wrap_axis_angle_np(omega)
    theta = np.linalg.norm(values, axis=-1, keepdims=True)
    out = np.zeros(values.shape[:-1] + (3, 3), dtype=np.float64)
    eye = np.eye(3, dtype=np.float64)
    flat_w = values.reshape(-1, 3)
    flat_t = theta.reshape(-1, 1)
    flat_r = out.reshape(-1, 3, 3)
    for index, (vector, angle) in enumerate(zip(flat_w, flat_t[:, 0])):
        if float(angle) < 1e-8:
            flat_r[index] = eye
            continue
        axis = vector / float(angle)
        skew = np.array(
            [[0.0, -axis[2], axis[1]], [axis[2], 0.0, -axis[0]], [-axis[1], axis[0], 0.0]],
            dtype=np.float64,
        )
        flat_r[index] = eye + math.sin(float(angle)) * skew + (1.0 - math.cos(float(angle))) * (skew @ skew)
    return out


def compose_local_np(base: np.ndarray, omega: np.ndarray) -> np.ndarray:
    """R_new = exp(ω) @ R_capture. Extra rotation is applied in the parent frame."""
    return so3_exp_np(omega) @ np.asarray(base, dtype=np.float64)


def bone_lengths_from_world_np(world: np.ndarray, parents: np.ndarray) -> np.ndarray:
    parent = np.asarray(parents, dtype=np.int64)
    pos = np.asarray(world, dtype=np.float64)[..., :3, 3]
    lengths = np.zeros(pos.shape[:-1], dtype=np.float64)
    for index, parent_index in enumerate(parent):
        if int(parent_index) < 0:
            continue
        lengths[..., index] = np.linalg.norm(pos[..., index, :] - pos[..., int(parent_index), :], axis=-1)
    return lengths


def require_torch():
    import torch

    return torch


def clamp_axis_angle_magnitude(omega: Any, max_rad: float) -> Any:
    torch = require_torch()
    if float(max_rad) <= 0:
        raise ValueError("max_rad must be positive")
    values = omega if isinstance(omega, torch.Tensor) else torch.as_tensor(omega)
    theta = (values.square().sum(dim=-1, keepdim=True) + 1e-12).sqrt()
    scale = (float(max_rad) / theta).clamp(max=1.0)
    return values * scale


def wrap_axis_angle(omega: Any) -> Any:
    torch = require_torch()
    values = omega if isinstance(omega, torch.Tensor) else torch.as_tensor(omega)
    theta = torch.linalg.vector_norm(values, dim=-1, keepdim=True)
    wrapped = torch.remainder(theta + math.pi, 2.0 * math.pi) - math.pi
    scale = torch.where(theta > 1e-8, wrapped / theta, torch.ones_like(theta))
    return values * scale


def so3_geodesic(first: Any, second: Any) -> Any:
    """Unsigned geodesic angle. Measurement only — `acos` is not finite-grad at identity."""
    torch = require_torch()
    a = first if isinstance(first, torch.Tensor) else torch.as_tensor(first)
    b = second if isinstance(second, torch.Tensor) else torch.as_tensor(second)
    relative = a.transpose(-1, -2) @ b
    trace = relative.diagonal(dim1=-2, dim2=-1).sum(-1)
    cosine = ((trace - 1.0) * 0.5).clamp(-1.0, 1.0)
    return cosine.acos()


def so3_geodesic_sq(first: Any, second: Any) -> Any:
    """Smooth wrap-safe θ² proxy: ||A−B||_F² / 2 = 2(1−cos θ). Finite at identity."""
    a = first if hasattr(first, "shape") else require_torch().as_tensor(first)
    b = second if hasattr(second, "shape") else require_torch().as_tensor(second)
    delta = a - b
    return 0.5 * (delta * delta).sum(dim=(-1, -2))


def _skew(omega: Any) -> Any:
    torch = require_torch()
    x, y, z = omega.unbind(-1)
    zero = torch.zeros_like(x)
    return torch.stack(
        (
            torch.stack((zero, -z, y), dim=-1),
            torch.stack((z, zero, -x), dim=-1),
            torch.stack((-y, x, zero), dim=-1),
        ),
        dim=-2,
    )


def so3_exp(omega: Any) -> Any:
    """Rodrigues map using skew(ω). Uses sinc so the origin has finite gradients."""
    torch = require_torch()
    values = omega if isinstance(omega, torch.Tensor) else torch.as_tensor(omega)
    wedge = _skew(values)
    # sqrt(‖ω‖² + ε) keeps d‖ω‖/dω finite at the origin (plain ‖ω‖ is NaN there).
    theta = ((values * values).sum(dim=-1) + 1e-12).sqrt()
    coeff_a = torch.sin(theta) / theta
    coeff_b = (1.0 - torch.cos(theta)) / theta.square()
    eye = torch.eye(3, device=values.device, dtype=values.dtype)
    while eye.ndim < values.ndim + 1:
        eye = eye.unsqueeze(0)
    return eye + coeff_a[..., None, None] * wedge + coeff_b[..., None, None] * (wedge @ wedge)


def compose_local(base: Any, omega: Any) -> Any:
    return so3_exp(omega) @ base


def apply_joint_deltas(
    base_local: Any,
    omega_free: Any,
    *,
    free_frames: Any,
    free_joints: Any,
) -> Any:
    """Compose extra rotations onto free frames/joints. Other locals stay exact capture."""
    extra = so3_exp(omega_free)
    local = base_local.clone()
    for slot, joint in enumerate([int(index) for index in free_joints.tolist()]):
        local[free_frames, joint] = extra[:, slot] @ base_local[free_frames, joint]
    return local


def fk_world(
    local_rotation: Any,
    offsets: Any,
    parents: Any,
    root_world: Any,
) -> Any:
    """Batched fixed-length FK. `local_rotation` is [F,J,3,3], `root_world` is [F,3]."""
    torch = require_torch()
    rotation = local_rotation
    translation = offsets
    root = root_world
    parent = [int(index) for index in np.asarray(parents, dtype=np.int64).tolist()]
    frame_count, joint_count = int(rotation.shape[0]), int(rotation.shape[1])
    if translation.shape != (joint_count, 3):
        raise ValueError(f"offsets must be [J,3], got {tuple(translation.shape)}")
    if root.shape != (frame_count, 3):
        raise ValueError(f"root_world must be [F,3], got {tuple(root.shape)}")
    worlds = []
    for index, parent_index in enumerate(parent):
        if parent_index < 0:
            world_rot = rotation[:, index]
            world_pos = root
        else:
            if parent_index >= index:
                raise ValueError("parents must precede children")
            parent_rot = worlds[parent_index][:, :3, :3]
            world_rot = parent_rot @ rotation[:, index]
            world_pos = worlds[parent_index][:, :3, 3] + torch.einsum("fij,j->fi", parent_rot, translation[index])
        matrix = rotation.new_zeros((frame_count, 4, 4))
        matrix[:, :3, :3] = world_rot
        matrix[:, :3, 3] = world_pos
        matrix[:, 3, 3] = 1.0
        worlds.append(matrix)
    return torch.stack(worlds, dim=1)


def skin_lbs(world: Any, inverse_bind: Any, vertices: Any, weights: Any) -> Any:
    """Linear blend skinning. Gradients flow from vertices back through `world`."""
    torch = require_torch()
    rest = torch.cat((vertices, torch.ones(vertices.shape[0], 1, device=vertices.device, dtype=vertices.dtype)), dim=1)
    transforms = world @ inverse_bind
    candidates = torch.einsum("fjkl,vl->fvjk", transforms[:, :, :3], rest)
    return torch.einsum("fvjc,vj->fvc", candidates, weights)


def bone_lengths_from_world(world: Any, parents: Any) -> Any:
    torch = require_torch()
    parent = np.asarray(parents, dtype=np.int64)
    pos = world[..., :3, 3]
    lengths = pos.new_zeros(pos.shape[:-1])
    for index, parent_index in enumerate(parent.tolist()):
        if int(parent_index) < 0:
            continue
        delta = pos[..., index, :] - pos[..., int(parent_index), :]
        lengths[..., index] = (delta.square().sum(dim=-1) + 1e-12).sqrt()
    return lengths


def edge_strain(vertices: Any, edges: Any, rest_lengths: Any) -> tuple[Any, Any]:
    """Mean squared log length-ratio. Uses a squared-norm so a collapsed edge stays finite-grad."""
    torch = require_torch()
    diff = vertices[:, edges[:, 0]] - vertices[:, edges[:, 1]]
    actual = (diff.square().sum(dim=-1) + 1e-12).sqrt()
    ratio = (actual / rest_lengths).clamp_min(1e-4)
    return torch.log(ratio).square().mean(), ratio
