"""Differentiable, rest-topology surface constraints for skinned mesh proposals.

The public functions operate on vertices shaped ``[F, V, 3]`` (a single frame
may be supplied as ``[V, 3]``).  Metrics are always detached before conversion
to JSON.  Faces whose *reference* area is below ``relative_area_threshold``
times the largest reference face are excluded; no deformed-face filtering is
performed, so a collapsed proposal remains visible in the loss.
"""
from __future__ import annotations

from typing import Any
import numpy as np
import torch
import torch.nn.functional as functional


def _frames(value: torch.Tensor | np.ndarray, name: str) -> torch.Tensor:
    value = torch.as_tensor(value, dtype=torch.float32)
    if value.ndim == 2 and value.shape[-1] == 3:
        value = value.unsqueeze(0)
    if value.ndim != 3 or value.shape[-1] != 3:
        raise ValueError(f"{name} must have shape [F,V,3] or [V,3]")
    if not torch.isfinite(value).all():
        raise ValueError(f"{name} contains non-finite values")
    return value


def _topology(rest: torch.Tensor, triangles: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    triangles = torch.as_tensor(triangles, dtype=torch.long, device=rest.device)
    if triangles.ndim != 2 or triangles.shape[1] != 3 or triangles.numel() == 0:
        raise ValueError("triangles must have shape [T,3] and not be empty")
    if torch.any(triangles < 0) or torch.any(triangles >= rest.shape[0]):
        raise ValueError("triangles contain an out-of-range vertex")
    p = rest[triangles]
    e1, e2 = p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]
    cross = torch.cross(e1, e2, dim=-1)
    area2 = torch.linalg.vector_norm(cross, dim=-1)
    return p, e1, e2, area2


def triangle_principal_stretches(
    vertices: torch.Tensor | np.ndarray,
    rest_vertices: torch.Tensor | np.ndarray,
    triangles: torch.Tensor | np.ndarray,
    *, relative_area_threshold: float = 1e-8,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Return ``(stretches[F,T,2], valid[T], reference_area[T])``.

    The two singular values are those of the local 3D deformation gradient
    from each reference triangle.  The Gram construction is rotation
    invariant.  A small analytic discriminant stabilizer avoids the undefined
    eigenvector gradient at the repeated identity eigenvalue.
    """
    x, r = _frames(vertices, "vertices"), _frames(rest_vertices, "rest_vertices")
    if x.shape[1] != r.shape[1]:
        raise ValueError("vertices and rest_vertices have different vertex counts")
    _, re1, re2, area2 = _topology(r[0], triangles)
    # An orthonormal reference basis makes the local map independent of edge scale.
    u = functional.normalize(re1, dim=-1, eps=1e-12)
    n = functional.normalize(torch.cross(re1, re2, dim=-1), dim=-1, eps=1e-12)
    v = torch.cross(n, u, dim=-1)
    ref = torch.stack((torch.sum(re1 * u, -1), torch.sum(re1 * v, -1)), -1)
    ref2 = torch.stack((torch.sum(re2 * u, -1), torch.sum(re2 * v, -1)), -1)
    max_area = torch.clamp(area2.max(), min=torch.finfo(area2.dtype).eps)
    valid = area2 / max_area > float(relative_area_threshold)
    # Edge vectors are columns in the 2-D reference matrix.
    refmat = torch.stack((ref, ref2), -1)
    safe_refmat = torch.where(valid[:, None, None], refmat, torch.eye(2, device=r.device, dtype=r.dtype)[None])
    inv = torch.linalg.inv(safe_refmat)
    dp = x[:, triangles]
    de1, de2 = dp[:, :, 1] - dp[:, :, 0], dp[:, :, 2] - dp[:, :, 0]
    # columns are deformed edge vectors; right multiplication maps reference coords.
    deformation = torch.stack((de1, de2), -1) @ inv.unsqueeze(0)
    gram = deformation.transpose(-1, -2) @ deformation
    a, c, b = gram[..., 0, 0], gram[..., 1, 1], gram[..., 0, 1]
    half = (a + c) * 0.5
    # One ulp is enough to define a finite direction at repeated eigenvalues;
    # subtracting its square root keeps the identity value exact in practice.
    eps = torch.as_tensor(1e-12, dtype=gram.dtype, device=gram.device)
    discriminant = ((a - c) * 0.5) ** 2 + b * b
    # Equivalent to sqrt(discriminant) away from zero, but has a finite
    # derivative at identity (avoid evaluating an unused sqrt(0) branch).
    radius = discriminant / (torch.sqrt(discriminant + eps) + torch.sqrt(eps))
    eig_hi, eig_lo = half + radius, half - radius
    stretches = torch.sqrt(torch.clamp(torch.stack((eig_hi, eig_lo), -1), min=eps))
    return stretches, valid, area2 * 0.5


def surface_constraint_loss(
    vertices: torch.Tensor,
    rest_vertices: torch.Tensor | np.ndarray,
    triangles: torch.Tensor | np.ndarray,
    *, relative_area_threshold: float = 1e-8,
    stretch_limit: float = 1.5,
    compression_limit: float = 0.67,
    boundary_weight: float = 8.0,
    mean_log_weight: float = 1.0,
    tail_weight: float = 2.0,
    return_metrics: bool = True,
) -> tuple[torch.Tensor, dict[str, Any]]:
    """Compute a bounded surface loss and detached diagnostic metrics."""
    stretches, valid, areas = triangle_principal_stretches(vertices, rest_vertices, triangles, relative_area_threshold=relative_area_threshold)
    s = stretches[:, valid]
    w = areas[valid]
    if not s.shape[1]:
        zero = vertices.sum() * 0.0
        return (zero, {"recordCount": 0, "validTriangleCount": 0}) if return_metrics else zero
    log_s = torch.log(torch.clamp(s, min=1e-6))
    abs_log = torch.abs(log_s).amax(-1)
    weights = w / torch.clamp(w.sum(), min=1e-12)
    mean_log = (torch.abs(log_s).mean(-1) * weights).sum(-1).mean()
    violations = functional.relu(s - stretch_limit) ** 2 + functional.relu(compression_limit - s) ** 2
    boundary = violations.mean()
    k = max(1, int(np.ceil(abs_log.shape[1] * 0.01)))
    tail = torch.topk(abs_log, k=k, dim=1).values.mean()
    loss = boundary_weight * boundary + mean_log_weight * mean_log + tail_weight * tail
    return (loss, surface_constraint_metrics(stretches, valid, areas)) if return_metrics else loss


def surface_constraint_metrics(stretches, valid, areas) -> dict[str, Any]:
    """Produce JSON-safe, detached per-frame strain summaries."""
    s = torch.as_tensor(stretches).detach().cpu()
    valid = torch.as_tensor(valid, dtype=torch.bool).detach().cpu()
    a = torch.as_tensor(areas).detach().cpu()
    if s.ndim == 2: s = s.unsqueeze(0)
    s = s[:, valid]
    if not s.shape[1]:
        return {"recordCount": 0, "validTriangleCount": 0, "perFrame": []}
    strain = s.amax(-1)
    comp = s.amin(-1)
    logmag = torch.abs(torch.log(torch.clamp(s, min=1e-6))).amax(-1)
    out = []
    for i in range(s.shape[0]):
        out.append({"p95": float(torch.quantile(strain[i], .95)), "p99": float(torch.quantile(strain[i], .99)), "max": float(strain[i].max()), "min": float(comp[i].min()), "stretchViolationFraction": float((s[i] > 1.5).any(-1).float().mean()), "compressionViolationFraction": float((s[i] < .67).any(-1).float().mean()), "worst1pctLogStrain": float(torch.topk(logmag[i], max(1, int(np.ceil(logmag.shape[1] * .01)))).values.mean())})
    return {"recordCount": int(s.shape[0] * s.shape[1]), "validTriangleCount": int(s.shape[1]), "perFrame": out}


def rest_mesh_gate(original_vertices, candidate_vertices, triangles, *, relative_area_threshold=1e-8, max_displacement_fraction=.03, ratio_limits=(.8, 1.25), raise_on_fail=False) -> dict[str, Any]:
    """Check that a proposed rest mesh remains a plausible copy of the original."""
    original = _frames(original_vertices, "original_vertices")[0].detach().cpu().numpy()
    candidate = _frames(candidate_vertices, "candidate_vertices")[0].detach().cpu().numpy()
    tri = torch.as_tensor(triangles).detach().cpu().numpy().astype(np.int64)
    finite = bool(np.isfinite(original).all() and np.isfinite(candidate).all())
    diag = float(np.linalg.norm(original.max(0) - original.min(0)))
    max_disp = float(np.linalg.norm(candidate - original, axis=1).max()) if finite else float("inf")
    stretch, valid, areas = triangle_principal_stretches(candidate, original, tri, relative_area_threshold=relative_area_threshold)
    ratios = stretch[0, valid].detach().cpu().numpy() if bool(valid.any()) else np.empty((0, 2))
    ratio_bad = ((ratios < ratio_limits[0]) | (ratios > ratio_limits[1])).any(1) if len(ratios) else np.empty(0, dtype=bool)
    op = original[tri]; cp = candidate[tri]
    on = np.cross(op[:, 1]-op[:, 0], op[:, 2]-op[:, 0]); cn = np.cross(cp[:, 1]-cp[:, 0], cp[:, 2]-cp[:, 0])
    normal_flip = (np.sum(on * cn, axis=1) < 0) & (np.linalg.norm(on, axis=1) > 0) & (np.linalg.norm(cn, axis=1) > 0)
    result = {"ok": bool(finite and max_disp <= max_displacement_fraction * max(diag, 1e-12) and (not ratio_bad.any()) and (not normal_flip.any())), "finite": finite, "maxDisplacement": max_disp, "maxDisplacementLimit": max_displacement_fraction * max(diag, 1e-12), "restTriangleCount": int(valid.sum()), "triangleRatioViolationFraction": float(ratio_bad.mean()) if len(ratio_bad) else 0.0, "normalFlipFraction": float(normal_flip[valid.cpu().numpy()].mean()) if bool(valid.any()) else 0.0}
    if raise_on_fail and not result["ok"]: raise ValueError(f"rest mesh gate failed: {result}")
    return result


class SurfaceConstraints:
    """Small stateful adapter used by the skin solver.

    ``vertices`` is the immutable original rest mesh.  ``loss`` accepts one
    or more animated vertex frames; ``metrics`` and ``rest_gate`` are detached
    reporting paths and never participate in autograd.
    """

    def __init__(self, vertices, triangles, device="cpu", **kwargs):
        self.vertices = torch.as_tensor(vertices, dtype=torch.float32, device=device)
        if self.vertices.ndim != 2 or self.vertices.shape[-1] != 3:
            raise ValueError("vertices must have shape [V,3]")
        self.triangles = torch.as_tensor(triangles, dtype=torch.long, device=device)
        # Validate topology and cache the reference-face accounting once.
        _, _, _, area2 = _topology(self.vertices, self.triangles)
        threshold = float(kwargs.pop("relative_area_threshold", 1e-8))
        self.relative_area_threshold = threshold
        self._valid = area2 / torch.clamp(area2.max(), min=torch.finfo(area2.dtype).eps) > threshold
        self._areas = area2 * .5
        self.options = kwargs

    def loss(self, animated):
        return surface_constraint_loss(animated, self.vertices, self.triangles, relative_area_threshold=self.relative_area_threshold, return_metrics=False, **self.options)

    def metrics(self, animated):
        stretches, valid, areas = triangle_principal_stretches(animated, self.vertices, self.triangles, relative_area_threshold=self.relative_area_threshold)
        return surface_constraint_metrics(stretches, valid, areas)

    def rest_gate(self, learned_vertices):
        return rest_mesh_gate(self.vertices, learned_vertices, self.triangles, relative_area_threshold=self.relative_area_threshold)
