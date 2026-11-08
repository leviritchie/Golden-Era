"""CPU-testable per-joint anatomical-axis calibration diagnostic."""
from __future__ import annotations

import torch


def _skew(v):
    x, y, z = v.unbind(-1)
    zero = torch.zeros_like(x)
    return torch.stack((zero, -z, y, z, zero, -x, -y, x, zero), -1).reshape(v.shape[:-1] + (3, 3))


def _validate_rotation(value, label):
    if not isinstance(value, torch.Tensor) or value.ndim != 4 or value.shape[-2:] != (3, 3) or not torch.isfinite(value).all():
        raise ValueError(f"{label} must be finite [F,J,3,3]")
    eye = torch.eye(3, dtype=value.dtype, device=value.device)
    if not torch.allclose(value.transpose(-1, -2) @ value, eye, atol=1e-5, rtol=0.) or not torch.all(torch.linalg.det(value) > 0):
        raise ValueError(f"{label} must contain proper SO(3) matrices")


class JointAxisCalibration(torch.nn.Module):
    """Train only non-root local-axis conjugations; source and roots are frozen."""

    def __init__(self, source_local, root_positions, offsets, parents):
        super().__init__()
        source = (source_local.detach().clone() if isinstance(source_local, torch.Tensor) else torch.as_tensor(source_local, dtype=torch.float64)).detach().clone()
        if source.ndim != 4 or source.shape[0] < 1 or source.shape[1] < 1:
            raise ValueError("source_local must have non-empty [F,J,3,3] shape")
        roots = (root_positions.detach().clone() if isinstance(root_positions, torch.Tensor) else torch.as_tensor(root_positions, dtype=source.dtype)).detach().clone().to(dtype=source.dtype, device=source.device)
        off = (offsets.detach().clone() if isinstance(offsets, torch.Tensor) else torch.as_tensor(offsets, dtype=source.dtype)).detach().clone().to(dtype=source.dtype, device=source.device)
        par = (parents.detach().clone() if isinstance(parents, torch.Tensor) else torch.as_tensor(parents, dtype=torch.long)).detach().clone().to(device=source.device)
        _validate_rotation(source, "source_local")
        if roots.ndim != 2 or roots.shape != (source.shape[0], 3) or not torch.isfinite(roots).all():
            raise ValueError("root_positions must be finite [F,3]")
        if off.ndim != 2 or off.shape != (source.shape[1], 3) or not torch.isfinite(off).all():
            raise ValueError("offsets must be finite [J,3]")
        if par.ndim != 1 or par.shape[0] != source.shape[1] or par.dtype not in (torch.int32, torch.int64):
            raise ValueError("parents must be integer [J]")
        if int(par[0]) != -1 or any(int(p) < 0 or int(p) >= i for i, p in enumerate(par[1:].tolist(), 1)):
            raise ValueError("parents must be root-first ordered with one root")
        self.register_buffer("source_local", source)
        self.register_buffer("root_positions", roots)
        self.register_buffer("offsets", off)
        self.register_buffer("parents", par.to(torch.long))
        self.raw = torch.nn.Parameter(torch.zeros((source.shape[1] - 1, 3), dtype=source.dtype, device=source.device))

    def locals(self):
        correction = torch.matrix_exp(_skew(self.raw))
        root = self.source_local[:, :1]
        nonroot = self.source_local[:, 1:]
        if nonroot.shape[1] == 0:
            return root
        corrected = correction[None] @ nonroot @ correction.transpose(-1, -2)[None]
        return torch.cat((root, corrected), dim=1)

    def forward(self):
        local = self.locals()
        frames, joints = local.shape[:2]
        world_r_list = []
        world_t_list = []
        for joint in range(joints):
            parent = int(self.parents[joint])
            if parent < 0:
                rotation = local[:, joint]
                translation = self.root_positions
            else:
                rotation = world_r_list[parent] @ local[:, joint]
                translation = world_t_list[parent] + torch.einsum("fij,j->fi", world_r_list[parent], self.offsets[joint])
            world_r_list.append(rotation)
            world_t_list.append(translation)
        world_r = torch.stack(world_r_list, dim=1)
        world_t = torch.stack(world_t_list, dim=1)
        result = torch.eye(4, dtype=local.dtype, device=local.device).expand(frames, joints, 4, 4).clone()
        result[:, :, :3, :3] = world_r
        result[:, :, :3, 3] = world_t
        return result


__all__ = ["JointAxisCalibration"]
