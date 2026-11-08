"""Shared global similarity alignment for immutable source motion palettes.

The module is intentionally CPU-testable and contains no renderer or per-frame
optimization.  A single proper transform B is conjugated through every
source-space bone palette D[t,j].
"""
from __future__ import annotations

from typing import Any

import torch


_LOG2 = 0.6931471805599453


def _validate_palettes(palettes: torch.Tensor) -> tuple[int, int]:
    if not isinstance(palettes, torch.Tensor) or palettes.ndim != 4 or palettes.shape[-2:] != (4, 4):
        raise ValueError("palettes must be a tensor with shape [T,J,4,4]")
    if palettes.shape[0] < 1 or palettes.shape[1] < 1 or not torch.isfinite(palettes).all():
        raise ValueError("palettes must be non-empty and finite")
    expected = palettes.new_tensor([0.0, 0.0, 0.0, 1.0])
    if not torch.allclose(palettes[..., 3, :], expected, atol=1e-6, rtol=0.0):
        raise ValueError("palettes must have affine homogeneous bottom rows")
    return int(palettes.shape[0]), int(palettes.shape[1])


def _raw_params(raw: torch.Tensor | None, mode: str, *, dtype: torch.dtype, device: torch.device) -> torch.Tensor:
    count = 3 if mode == "rotation" else 7 if mode == "similarity" else 0
    if not count:
        raise ValueError("mode must be 'rotation' or 'similarity'")
    if raw is None:
        return torch.zeros(count, dtype=dtype, device=device)
    result = raw if isinstance(raw, torch.Tensor) else torch.as_tensor(raw, dtype=dtype, device=device)
    result = result.to(device=device, dtype=dtype).reshape(-1)
    if result.numel() != count or not torch.isfinite(result).all():
        raise ValueError(f"raw_params must have finite shape [{count}]")
    return result


def _skew(rotvec: torch.Tensor) -> torch.Tensor:
    x, y, z = rotvec.unbind()
    zero = torch.zeros((), dtype=rotvec.dtype, device=rotvec.device)
    return torch.stack((zero, -z, y, z, zero, -x, -y, x, zero)).reshape(3, 3)


def build_alignment_matrix(
    raw_params: torch.Tensor | None,
    *,
    mode: str,
    mesh_span: float,
    pivot: torch.Tensor | Any,
    dtype: torch.dtype = torch.float64,
    device: torch.device | str = "cpu",
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Construct B and differentiable transform statistics from bounded params."""
    if not torch.isfinite(torch.as_tensor(mesh_span)) or float(mesh_span) <= 0.0:
        raise ValueError("mesh_span must be finite and positive")
    dev = torch.device(device)
    p = torch.as_tensor(pivot, dtype=dtype, device=dev).reshape(-1)
    if p.numel() != 3 or not torch.isfinite(p).all():
        raise ValueError("pivot must be finite [3]")
    raw = _raw_params(raw_params, mode, dtype=dtype, device=dev)
    rotvec = raw[:3]
    rotation = torch.matrix_exp(_skew(rotvec))
    if mode == "rotation":
        scale = torch.ones((), dtype=dtype, device=dev)
        delta = torch.zeros(3, dtype=dtype, device=dev)
    else:
        scale = torch.exp(_LOG2 * torch.tanh(raw[3]))
        delta = (0.25 * float(mesh_span)) * torch.tanh(raw[4:7])
    linear = scale * rotation
    translation = p + delta - linear @ p
    matrix = torch.eye(4, dtype=dtype, device=dev)
    matrix = matrix.clone()
    matrix[:3, :3] = linear
    matrix[:3, 3] = translation
    return matrix, {"rotation": rotation, "scale": scale, "translationDelta": delta, "pivot": p}


def transform_motion_palettes(
    palettes: torch.Tensor,
    *,
    mode: str = "similarity",
    raw_params: torch.Tensor | None = None,
    mesh_span: float,
    pivot: torch.Tensor | Any,
) -> dict[str, Any]:
    """Return one shared B-conjugated palette set without mutating source data."""
    _validate_palettes(palettes)
    source = palettes.detach().clone()
    matrix, stats = build_alignment_matrix(raw_params, mode=mode, mesh_span=mesh_span,
                                            pivot=pivot, dtype=palettes.dtype, device=palettes.device)
    inverse = torch.linalg.inv(matrix)
    transformed = matrix @ source @ inverse
    bottom = transformed[..., 3, :]
    if not torch.allclose(bottom, source.new_tensor([0.0, 0.0, 0.0, 1.0]), atol=1e-6, rtol=0.0):
        raise ValueError("aligned palettes lost affine homogeneous bottom rows")
    rotation = stats["rotation"]
    report = {
        "mode": mode,
        "parameterCount": 3 if mode == "rotation" else 7,
        "scale": float(stats["scale"].detach().cpu()),
        "translationDelta": stats["translationDelta"].detach().cpu().tolist(),
        "rotationDeterminant": float(torch.linalg.det(rotation).detach().cpu()),
        "sourceImmutable": True,
        "sharedTransform": True,
        "sourcePalettes": source,
    }
    return {"matrix": matrix, "palettes": transformed, "report": report}


class GlobalMotionAlignment(torch.nn.Module):
    """Train only one correction; the fixed source palette is a detached buffer."""

    def __init__(self, palettes, *, pivot, span, mode):
        super().__init__()
        _validate_palettes(palettes)
        build_alignment_matrix(None, mode=mode, mesh_span=span, pivot=pivot,
                               dtype=palettes.dtype, device=palettes.device)
        self.register_buffer('source', palettes.detach().clone())
        self.register_buffer('pivot', torch.as_tensor(pivot, dtype=palettes.dtype, device=palettes.device).detach().clone())
        self.raw = torch.nn.Parameter(palettes.new_zeros(3 if mode == 'rotation' else 7))
        self.span, self.mode = float(span), mode

    def matrix(self):
        return build_alignment_matrix(self.raw, mode=self.mode, mesh_span=self.span,
            pivot=self.pivot, dtype=self.source.dtype, device=self.source.device)[0]

    def forward(self):
        matrix = self.matrix()
        return matrix @ self.source @ torch.linalg.inv(matrix)

    def stats(self):
        matrix, stats = build_alignment_matrix(self.raw, mode=self.mode, mesh_span=self.span,
            pivot=self.pivot, dtype=self.source.dtype, device=self.source.device)
        return {'mode': self.mode, 'parameterCount': self.raw.numel(),
                'matrix': matrix.detach().cpu().tolist(), 'rawParameters': self.raw.detach().cpu().tolist(),
                'scale': float(stats['scale'].detach()),
                'translationDelta': stats['translationDelta'].detach().cpu().tolist(),
                'rotationDeterminant': float(torch.linalg.det(stats['rotation']).detach()),
                'sharedTransform': True}


__all__ = ["build_alignment_matrix", "transform_motion_palettes", "GlobalMotionAlignment"]
