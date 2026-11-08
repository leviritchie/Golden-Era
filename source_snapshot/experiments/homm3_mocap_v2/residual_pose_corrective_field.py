"""Capacity-expanded pose corrective field for a bounded diagnostic trial."""
from __future__ import annotations

from collections.abc import Iterable, Mapping

import numpy as np
import torch

from pose_corrective_field import PoseCorrectiveField, _validate_rotations
from skin_mesh_field import MeshField


class ResidualPoseCorrectiveField(PoseCorrectiveField):
    """Retain the legacy four modes and add a bounded PCA residual head."""

    def __init__(self, vertices, regions, train_local_rotations,
                 neutral_local_rotations, frozen_regions: Iterable[str] = (),
                 max_displacement_fraction: float = .10,
                 grid_resolution: int = 4, target_energy: float = .95,
                 device="cpu"):
        if not np.isfinite(target_energy) or not 0.0 < target_energy <= 1.0:
            raise ValueError("target_energy must be finite in (0, 1]")

        # The base constructor is authoritative for the original four modes.
        super().__init__(vertices, regions, train_local_rotations,
                         neutral_local_rotations,
                         frozen_regions=frozen_regions,
                         max_displacement_fraction=max_displacement_fraction,
                         grid_resolution=grid_resolution, device=device)
        self._legacy_state_keys = tuple(super().state_dict().keys())

        neutral = np.array(neutral_local_rotations, dtype=np.float64, copy=True)
        train = np.array(train_local_rotations, dtype=np.float64, copy=True)
        train = _validate_rotations(train, "train_local_rotations", train.shape)
        features = (train - neutral[None]).reshape(train.shape[0], -1)
        _, singular, vt = np.linalg.svd(features, full_matrices=False)
        supported = int(np.count_nonzero(singular > 1e-8))
        if supported < 4:
            raise ValueError("training rotation features must support rank 4")
        total = float(np.square(singular[:supported]).sum())
        cumulative = np.cumsum(np.square(singular[:supported])) / total
        rank = int(np.searchsorted(cumulative, target_energy, side="left") + 1)
        if rank <= 4:
            raise ValueError(
                "target_energy is already reached by four modes; residual rank must exceed 4"
            )
        if rank > supported:
            raise ValueError("training features have no supported residual rank")

        # Recompute the same arrays and assert that the base buffers were not
        # altered by dtype/device conversion before retaining the residual.
        basis = vt[:4].T
        scales = singular[:4] / np.sqrt(len(train))
        np.testing.assert_array_equal(
            self.feature_basis.detach().cpu().numpy(), basis.astype(np.float32)
        )
        np.testing.assert_array_equal(
            self.feature_scales.detach().cpu().numpy(), scales.astype(np.float32)
        )
        residual_basis = vt[4:rank].T.astype(np.float32)
        residual_scales = (singular[4:rank] / np.sqrt(len(train))).astype(np.float32)
        self.register_buffer(
            "residual_basis",
            torch.as_tensor(residual_basis, device=self.feature_basis.device),
        )
        self.register_buffer(
            "residual_scales",
            torch.as_tensor(residual_scales, device=self.feature_basis.device),
        )
        self.residual_rank = rank
        self.target_energy = float(target_energy)

        for _ in range(rank - 4):
            self.modes.append(MeshField(
                vertices, regions, frozen_regions=frozen_regions,
                max_displacement_fraction=max_displacement_fraction,
                grid_resolution=grid_resolution, device=self.feature_basis.device,
            ))

    def coefficients(self, local_rotations):
        legacy = super().coefficients(local_rotations)
        features = self._features(local_rotations)
        residual = torch.tanh(
            (features @ self.residual_basis) / self.residual_scales
        ) / float(self.residual_rank - 4)
        headroom = (1.0 - legacy.abs().sum(dim=-1, keepdim=True)).clamp_min(0.0)
        return torch.cat((legacy, headroom * residual), dim=-1)

    def load_four_mode_state(self, state: Mapping[str, torch.Tensor]):
        """Import only a legacy four-mode state into this expanded field."""
        if not isinstance(state, Mapping):
            raise TypeError("state must be a mapping")
        expected = set(self._legacy_state_keys)
        actual = set(state.keys())
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ValueError(f"legacy state inventory mismatch; missing={missing}, extra={extra}")

        # This importer is a warm-start only.  It must not silently overwrite
        # an already-trained residual state.
        for index in range(4, len(self.modes)):
            if bool(self.modes[index].control.detach().abs().any()):
                raise ValueError("residual controls must be zero before legacy import")

        current = super().state_dict()
        control_keys = {f"modes.{index}.control" for index in range(4)}
        controls = {}
        for key in self._legacy_state_keys:
            source = torch.as_tensor(state[key], device=current[key].device)
            if not torch.isfinite(source).all():
                raise ValueError(f"legacy state contains non-finite tensor: {key}")
            if source.shape != current[key].shape:
                raise ValueError(f"legacy state shape mismatch: {key}")
            if source.dtype != current[key].dtype:
                raise ValueError(f"legacy state dtype mismatch: {key}")
            if key not in control_keys and not torch.equal(source, current[key]):
                raise ValueError(f"legacy non-control buffer differs: {key}")
            if key in control_keys:
                controls[int(key.split(".")[1])] = source

        with torch.no_grad():
            for index, source in controls.items():
                self.modes[index].control.copy_(source)
        return self


__all__ = ["ResidualPoseCorrectiveField"]
