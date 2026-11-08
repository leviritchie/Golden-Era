"""Sparse, region-constrained weight field for silhouette/color pilots."""
from __future__ import annotations

from typing import Iterable, Mapping
import numpy as np
import torch
from torch import nn


def _duplicate_groups(vertices: np.ndarray, triangles: np.ndarray, regions: np.ndarray):
    vertices = np.asarray(vertices, dtype=float)
    triangles = np.asarray(triangles, dtype=np.int64)
    regions = np.asarray(regions).astype(str)
    if triangles.ndim != 2 or triangles.shape[1] != 3 or np.any(triangles < 0) or np.any(triangles >= len(vertices)):
        raise ValueError("triangles must be a valid [F,3] topology")
    normals = np.zeros_like(vertices)
    face = np.cross(vertices[triangles[:, 1]] - vertices[triangles[:, 0]], vertices[triangles[:, 2]] - vertices[triangles[:, 0]])
    for corner in range(3):
        np.add.at(normals, triangles[:, corner], face)
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    buckets: dict[tuple[float, ...], list[int]] = {}
    for index, point in enumerate(map(tuple, np.round(vertices, 6))):
        buckets.setdefault(point, []).append(index)
    group_ids = np.full(len(vertices), -1, dtype=np.int64)
    groups: list[list[int]] = []
    for members in buckets.values():
        for index in members:
            if group_ids[index] >= 0:
                continue
            group = [index]
            group_ids[index] = len(groups)
            for other in members:
                if group_ids[other] < 0 and regions[index] == regions[other] and float(normals[index] @ normals[other]) >= 0.5:
                    group_ids[other] = group_ids[index]
                    group.append(other)
            groups.append(group)
    return group_ids, groups


class WeightField(nn.Module):
    def __init__(self, vertices, triangles, initial_weights, regions, names, region_joints: Mapping[str, Iterable[str]], device="cpu", train_regions=None, frozen_vertices=None):
        super().__init__()
        self.vertices = np.asarray(vertices, dtype=float)
        self.triangles = np.asarray(triangles, dtype=np.int64)
        self.regions = np.asarray(regions).astype(str)
        self.names = list(names)
        self.initial = np.asarray(initial_weights, dtype=float)
        if self.vertices.ndim != 2 or self.vertices.shape[1] != 3 or not np.isfinite(self.vertices).all():
            raise ValueError("vertices must be finite [V,3]")
        if len(self.regions) != len(self.vertices):
            raise ValueError("regions must contain one value per vertex")
        if self.initial.shape != (len(self.vertices), len(self.names)) or not np.isfinite(self.initial).all() or np.any(self.initial < 0):
            raise ValueError("initial_weights must be finite nonnegative [V,J]")
        if not np.allclose(self.initial.sum(axis=1), 1.0, atol=1e-6):
            raise ValueError("initial weights must sum to one")
        self.group_id, self.groups = _duplicate_groups(self.vertices, self.triangles, self.regions)
        self.region_joints = {str(key): tuple(str(value) for value in values) for key, values in region_joints.items()}
        self.train_regions = set(self.region_joints) if train_regions is None else {str(value) for value in train_regions}
        unknown = self.train_regions - set(self.region_joints)
        if unknown:
            raise ValueError(f"unsupported train regions: {sorted(unknown)}")
        self.region_names = tuple(sorted(self.train_regions))
        self.region_index = {name: index for index, name in enumerate(self.region_names)}
        self.allowed = np.zeros((len(self.region_names), len(self.names)), dtype=bool)
        name_index = {name: index for index, name in enumerate(self.names)}
        for row, region in enumerate(self.region_names):
            for joint in self.region_joints[region]:
                if joint not in name_index:
                    raise ValueError(f"unknown joint {joint} in region {region}")
                self.allowed[row, name_index[joint]] = True
        if np.any(self.allowed.sum(axis=1) > 8) or np.any(self.allowed.sum(axis=1) == 0):
            raise ValueError("candidate support must contain between 1 and maximum 8 influences")
        for vertex, region in enumerate(self.regions):
            if region in self.train_regions:
                allowed = self.allowed[self.region_index[region]]
                if np.any(self.initial[vertex] > 1e-8) and np.any((self.initial[vertex] > 1e-8) & ~allowed):
                    raise ValueError(f"initial weight outside allowed support at vertex {vertex}")
        self.base = np.zeros((len(self.groups), len(self.names)), dtype=float)
        for group, members in enumerate(self.groups):
            self.base[group] = self.initial[members].mean(axis=0)
        self.region_logits = nn.Parameter(torch.zeros((len(self.region_names), len(self.names)), device=device))
        self.group_logits = nn.Parameter(torch.zeros((len(self.groups), len(self.names)), device=device))
        freeze_mask = np.zeros(len(self.vertices), dtype=bool)
        if frozen_vertices is not None:
            ids = np.asarray(frozen_vertices, dtype=np.int64)
            if ids.ndim != 1 or np.any(ids < 0) or np.any(ids >= len(self.vertices)):
                raise ValueError("frozen_vertices must be integer ids in vertex range")
            freeze_mask[ids] = True
        region_ids = [(-1 if freeze_mask[index] else self.region_index.get(region, -1))
                      for index, region in enumerate(self.regions)]
        edges = {(min(a, b), max(a, b)) for a, b, c in self.triangles for a, b in ((a, b), (b, c), (c, a)) if a != b and self.regions[a] == self.regions[b]}
        self.register_buffer("group_ids", torch.tensor(self.group_id, dtype=torch.long, device=device))
        self.register_buffer("region_ids", torch.tensor(region_ids, dtype=torch.long, device=device))
        self.register_buffer("allowed_mask", torch.tensor(self.allowed, dtype=torch.bool, device=device))
        self.register_buffer("base_weights", torch.tensor(self.base, dtype=torch.float32, device=device))
        self.register_buffer("initial_weights", torch.tensor(self.initial, dtype=torch.float32, device=device))
        self.register_buffer("same_region_edges", torch.tensor(list(edges), dtype=torch.long, device=device).reshape(-1, 2))

    def weights(self):
        if not self.region_names:
            return self.initial_weights
        safe = self.region_ids.clamp_min(0)
        trainable = self.region_ids >= 0
        logits = torch.log(self.base_weights[self.group_ids] + 1e-6) + self.group_logits[self.group_ids] + self.region_logits[safe]
        logits = logits.masked_fill(~self.allowed_mask[safe], -1e9)
        learned = torch.softmax(logits, dim=1)
        return torch.where(trainable[:, None], learned, self.initial_weights)

    def penalty(self, weights=None):
        values = self.weights() if weights is None else weights
        prior = ((values - self.initial_weights) ** 2).mean()
        if self.same_region_edges.numel() == 0:
            return prior
        delta = values - self.initial_weights
        edge_delta = delta[self.same_region_edges[:, 0]] - delta[self.same_region_edges[:, 1]]
        return prior + (edge_delta ** 2).mean()

    def support_stats(self):
        values = self.weights().detach().cpu().numpy()
        return {"vertexCount": len(values), "groupCount": len(self.groups), "trainRegions": sorted(self.train_regions), "maxInfluences": int((values > 1e-8).sum(axis=1).max()), "allowedSupport": {region: [self.names[i] for i in np.where(self.allowed[row])[0]] for row, region in enumerate(self.region_names)}, "originalMeanAbsDelta": float(np.abs(values - self.initial).mean())}
