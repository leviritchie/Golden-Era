"""Bounded, shared rest-mesh deformation field for mocap fitting.

The field is deliberately independent of clips and frames.  A single coarse
trilinear lattice describes a rest-space correction which can be consumed by
any clip, while the original rest vertices remain immutable.
"""
from __future__ import annotations

from collections.abc import Iterable
import numpy as np
import torch
from torch import nn
from scipy.spatial import cKDTree


class MeshField(nn.Module):
    """Learn a bounded spatial displacement over one rest mesh.

    ``regions`` is one anatomical label per vertex. ``frozen_regions`` names
    labels which must remain exact.  Duplicate rest positions share a field
    value naturally; if any duplicate is frozen, the complete position group
    is frozen.
    """

    def __init__(self, vertices, regions, frozen_regions: Iterable[str] = (),
                 max_displacement_fraction: float = .03, grid_resolution: int = 6,
                 device="cpu"):
        super().__init__()
        rest = np.asarray(vertices, dtype=np.float32)
        labels = np.asarray(regions).astype(str)
        if rest.ndim != 2 or rest.shape[1] != 3 or len(rest) == 0 or not np.isfinite(rest).all():
            raise ValueError("vertices must be finite, non-empty [V,3]")
        if labels.ndim != 1 or len(labels) != len(rest):
            raise ValueError("regions must contain one value per vertex")
        if not np.isfinite(max_displacement_fraction) or max_displacement_fraction < 0:
            raise ValueError("max_displacement_fraction must be finite and nonnegative")
        if not isinstance(grid_resolution, (int, np.integer)) or not 2 <= int(grid_resolution) <= 6:
            raise ValueError("grid_resolution must be an integer in [2,6]")
        frozen_names = {str(x) for x in frozen_regions}
        if not frozen_names.issubset(set(labels)):
            raise ValueError(f"unknown frozen regions: {sorted(frozen_names - set(labels))}")

        lo, hi = rest.min(axis=0), rest.max(axis=0)
        diag = float(np.linalg.norm(hi - lo))
        if not np.isfinite(diag) or diag <= 0:
            raise ValueError("vertices must span a non-zero bounding box")
        self.register_buffer("rest_vertices", torch.as_tensor(rest, device=device))
        self.rest = rest.copy()  # immutable source copy for diagnostics
        self.regions = labels.copy()
        self.grid_resolution = int(grid_resolution)
        self.bbox_diag = diag
        self.max_displacement = float(max_displacement_fraction) * diag

        # Position groups enforce the UV-duplicate/no-crack rule without
        # relying on topology or region labels.
        groups: dict[tuple[float, float, float], list[int]] = {}
        for i, p in enumerate(rest):
            groups.setdefault(tuple(np.round(p, 6)), []).append(i)
        frozen = np.zeros(len(rest), dtype=bool)
        group_ids = np.empty(len(rest), dtype=np.int64)
        group_list = list(groups.values())
        for group_index, members in enumerate(group_list):
            group_ids[members] = group_index
            if any(labels[i] in frozen_names for i in members):
                frozen[members] = True
        self.register_buffer("frozen_mask", torch.as_tensor(frozen, device=device))
        self.register_buffer("group_ids", torch.as_tensor(group_ids, dtype=torch.long, device=device))
        group_frozen = np.asarray([frozen[members].any() for members in group_list], dtype=bool)
        group_taper = np.ones(len(group_list), dtype=np.float32)

        n = self.grid_resolution
        # A regular lattice includes both bbox faces. Degenerate axes are
        # expanded only for interpolation; mesh coordinates remain untouched.
        span = np.maximum(hi - lo, diag * 1e-6)
        xyz = (rest - lo) / span * (n - 1)
        base = np.floor(xyz).astype(np.int64).clip(0, n - 2)
        frac = xyz - base
        indices, weights = [], []
        for mask in range(8):
            corner = base + np.array([(mask >> a) & 1 for a in range(3)])
            indices.append(corner[:, 0] * n * n + corner[:, 1] * n + corner[:, 2])
            weights.append(np.prod(np.where(np.array([(mask >> a) & 1 for a in range(3)]) > 0, frac, 1.0 - frac), axis=1))
        self.register_buffer("corner_indices", torch.as_tensor(np.stack(indices, 1), dtype=torch.long, device=device))
        self.register_buffer("corner_weights", torch.as_tensor(np.stack(weights, 1), dtype=torch.float32, device=device))
        taper = self._make_taper(rest, frozen, diag)
        # A rounded duplicate group receives one conservative taper value.
        for group_index, members in enumerate(group_list):
            group_taper[group_index] = float(taper[members].min())
        self.register_buffer("taper", torch.as_tensor(taper, dtype=torch.float32, device=device))
        self.register_buffer("group_taper", torch.as_tensor(group_taper, dtype=torch.float32, device=device))
        self.register_buffer("group_frozen", torch.as_tensor(group_frozen, device=device))
        self.control = nn.Parameter(torch.zeros((n ** 3, 3), dtype=torch.float32, device=device))

    @staticmethod
    def _make_taper(vertices, frozen, diag):
        if not frozen.any():
            return np.ones(len(vertices), dtype=np.float32)
        frozen_points = vertices[frozen]
        # Do not materialize V x F distances: production meshes have many
        # vertices and frozen anatomical points.
        distance, _ = cKDTree(frozen_points).query(vertices, k=1)
        return np.clip(distance / (.08 * diag), 0.0, 1.0).astype(np.float32)

    def _control_delta(self):
        if self.max_displacement == 0:
            return self.control * 0
        # Convex interpolation of these controls cannot exceed the requested
        # per-vertex vector-magnitude bound.
        bounded = torch.tanh(self.control)
        # Bound the complete vector, rather than each component, so the
        # contract is on Euclidean displacement magnitude.
        norm = torch.linalg.vector_norm(bounded, dim=1, keepdim=True).clamp_min(1.0)
        return bounded / norm * self.max_displacement

    def displacement(self):
        controls = self._control_delta()
        values = controls[self.corner_indices]
        delta = (values * self.corner_weights[..., None]).sum(dim=1)
        # Average first so rounded UV duplicates cannot crack even when their
        # coordinates differ by less than the duplicate-group tolerance.
        sums = torch.zeros((self.group_taper.shape[0], 3), dtype=delta.dtype, device=delta.device)
        sums.index_add_(0, self.group_ids, delta)
        counts = torch.bincount(self.group_ids, minlength=sums.shape[0]).to(delta.dtype).unsqueeze(1)
        delta = sums[self.group_ids] / counts[self.group_ids]
        delta = delta * self.group_taper[self.group_ids, None]
        return torch.where(self.frozen_mask[:, None], torch.zeros_like(delta), delta)

    def vertices(self):
        """Return current vertices as a differentiable CPU/device tensor."""
        return self.rest_vertices + self.displacement()

    def penalty(self, vertices=None):
        """Smooth neighboring controls plus a rest-displacement prior."""
        delta = self._control_delta()
        n = self.grid_resolution
        grid = delta.reshape(n, n, n, 3)
        smooth = ((grid[1:] - grid[:-1]) ** 2).mean()
        smooth = smooth + ((grid[:, 1:] - grid[:, :-1]) ** 2).mean()
        smooth = smooth + ((grid[:, :, 1:] - grid[:, :, :-1]) ** 2).mean()
        values = self.vertices() if vertices is None else vertices
        prior = ((values - self.rest_vertices) / max(self.bbox_diag, 1e-12)).square().mean()
        return smooth + prior

    def stats(self):
        delta = self.displacement().detach()
        magnitude = torch.linalg.vector_norm(delta, dim=1)
        return {"vertexCount": len(self.rest), "controlCount": self.grid_resolution ** 3,
                "frozenVertexCount": int(self.frozen_mask.sum()), "bboxDiag": self.bbox_diag,
                "maxDisplacement": float(magnitude.max()), "maxAllowedDisplacement": self.max_displacement,
                "frozenRegions": sorted({r for r, f in zip(self.regions, self.frozen_mask.cpu().numpy()) if f}),
                "trainableTaperedVertexCount": int(((self.taper > 0) & (self.taper < 1)).sum())}


def validate_rest_field(field: MeshField, *, atol: float = 1e-6) -> bool:
    """Fail-closed contract check for frozen anatomy and duplicate positions."""
    values = field.vertices().detach().cpu().numpy()
    rest = field.rest
    if not np.isfinite(values).all():
        raise ValueError("rest field produced non-finite vertices")
    frozen = field.frozen_mask.detach().cpu().numpy()
    # Frozen rows are a byte-for-byte rest copy, not merely approximately so.
    if not np.array_equal(values[frozen], rest[frozen]):
        raise ValueError("frozen rest vertices changed")
    displacement = values - rest
    groups: dict[tuple[float, float, float], list[int]] = {}
    for i, point in enumerate(rest):
        groups.setdefault(tuple(np.round(point, 6)), []).append(i)
    for members in groups.values():
        if len(members) > 1 and not np.allclose(displacement[members], displacement[members[0]], atol=atol, rtol=0):
            raise ValueError("duplicate rest positions received different deltas")
    return True
