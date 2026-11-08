"""Pose-conditioned, bounded corrective mesh fields (diagnostic pilot only)."""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import torch
from torch import nn

from skin_mesh_field import MeshField


def _validate_rotations(value, name, shape):
    rotations = np.array(value, dtype=np.float64, copy=True)
    if rotations.shape != shape or not np.isfinite(rotations).all():
        raise ValueError(f"{name} must be finite with shape {shape}")
    gram = np.matmul(np.swapaxes(rotations, -1, -2), rotations)
    if not np.allclose(gram, np.eye(3), rtol=0.0, atol=2e-5):
        raise ValueError(f"{name} must contain orthonormal rotations")
    determinant = np.linalg.det(rotations)
    if np.any(determinant <= 0.0) or not np.allclose(determinant, 1.0, rtol=0.0, atol=2e-5):
        raise ValueError(f"{name} must contain proper SO(3) rotations")
    return rotations


class PoseCorrectiveField(nn.Module):
    """Four shared spatial fields driven only by local rotation deviations.

    The fields are independent of clip/frame identity. Zero neutral features
    make the neutral mesh exactly unchanged, while each coefficient is bounded
    to one quarter in magnitude so the four mode sum remains bounded.
    """

    def __init__(self, vertices, regions, train_local_rotations,
                 neutral_local_rotations, frozen_regions: Iterable[str] = (),
                 max_displacement_fraction: float = .10, grid_resolution: int = 4,
                 device="cpu"):
        super().__init__()
        rest = np.array(vertices, dtype=np.float32, copy=True)
        labels = np.asarray(regions).astype(str)
        if rest.ndim != 2 or rest.shape[1] != 3 or len(rest) == 0 or not np.isfinite(rest).all():
            raise ValueError("vertices must be finite, non-empty [V,3]")
        if labels.ndim != 1 or len(labels) != len(rest):
            raise ValueError("regions must contain one value per vertex")
        neutral_raw = np.array(neutral_local_rotations, dtype=np.float64, copy=True)
        if neutral_raw.ndim != 3 or neutral_raw.shape[1:] != (3, 3) or neutral_raw.shape[0] == 0:
            raise ValueError("neutral_local_rotations must have shape [J,3,3]")
        neutral = _validate_rotations(neutral_raw, "neutral_local_rotations", neutral_raw.shape)
        train = np.array(train_local_rotations, dtype=np.float64, copy=True)
        if train.ndim != 4 or train.shape[1:] != neutral.shape or train.shape[0] == 0:
            raise ValueError("train_local_rotations must have shape [T,J,3,3]")
        train = _validate_rotations(train, "train_local_rotations", train.shape)
        features = (train - neutral[None]).reshape(train.shape[0], -1)
        _, singular, vt = np.linalg.svd(features, full_matrices=False)
        supported = int(np.count_nonzero(singular > 1e-8))
        if supported < 4 or len(singular) < 4:
            raise ValueError("training rotation features must support rank 4")
        basis = vt[:4].T
        # RMS projections, not singular values: duplicating the training set
        # must not attenuate every corrective coefficient by sqrt(2).
        scales = singular[:4].copy() / np.sqrt(len(train))
        if not np.isfinite(basis).all() or not np.isfinite(scales).all() or np.any(scales <= 1e-8):
            raise ValueError("training feature basis is degenerate")
        self.register_buffer("neutral_local_rotations", torch.as_tensor(neutral.astype(np.float32), device=device))
        self.register_buffer("feature_basis", torch.as_tensor(basis.astype(np.float32), device=device))
        self.register_buffer("feature_scales", torch.as_tensor(scales.astype(np.float32), device=device))
        self.modes = nn.ModuleList([
            MeshField(rest, labels, frozen_regions=frozen_regions,
                      max_displacement_fraction=max_displacement_fraction,
                      grid_resolution=grid_resolution, device=device)
            for _ in range(4)
        ])
        self.bbox_diag = self.modes[0].bbox_diag
        self.max_displacement = self.modes[0].max_displacement

    def _features(self, local_rotations):
        if isinstance(local_rotations, torch.Tensor):
            rotations = local_rotations.to(device=self.feature_basis.device, dtype=torch.float32)
        else:
            rotations = torch.as_tensor(local_rotations, dtype=torch.float32,
                                        device=self.feature_basis.device)
        if rotations.ndim != 4 or rotations.shape[1:] != tuple(self.neutral_local_rotations.shape):
            raise ValueError("local_rotations must have shape [F,J,3,3]")
        if rotations.shape[0] == 0 or not bool(torch.isfinite(rotations).all()):
            raise ValueError("local_rotations must be nonempty and finite")
        gram = torch.matmul(rotations.transpose(-1, -2), rotations)
        eye = torch.eye(3, dtype=rotations.dtype, device=rotations.device)
        if not bool(torch.allclose(gram, eye, rtol=0.0, atol=2e-4)):
            raise ValueError("local_rotations must contain orthonormal rotations")
        det = torch.linalg.det(rotations)
        if not bool(torch.allclose(det, torch.ones_like(det), rtol=0.0, atol=2e-4)):
            raise ValueError("local_rotations must contain proper SO(3) rotations")
        return (rotations - self.neutral_local_rotations).reshape(rotations.shape[0], -1)

    def coefficients(self, local_rotations):
        features = self._features(local_rotations)
        projected = features @ self.feature_basis
        return torch.tanh(projected / self.feature_scales) / 4.0

    def displacement(self, local_rotations):
        coefficients = self.coefficients(local_rotations)
        mode_displacements = torch.stack([mode.displacement() for mode in self.modes], dim=0)
        return torch.einsum("fm,mvc->fvc", coefficients, mode_displacements)

    def penalty(self):
        return sum((mode.penalty() for mode in self.modes), torch.zeros((), device=self.feature_basis.device))


__all__ = ["PoseCorrectiveField"]
