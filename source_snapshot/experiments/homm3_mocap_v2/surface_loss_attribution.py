"""Pure tensor attribution of boundary surface-loss concentration."""
from __future__ import annotations

import torch


def attribute_surface(stretches, valid, areas):
    """Attribute stretch-boundary violations to the worst original triangles.

    ``stretches`` contains the two principal stretch values for each frame and
    triangle.  Invalid triangles are excluded from every aggregate, but their
    original indices are retained in the returned top-index values.
    """
    values = torch.as_tensor(stretches)
    if not values.is_floating_point():
        raise ValueError('stretches must use a floating-point dtype')
    mask = torch.as_tensor(valid, device=values.device)
    area = torch.as_tensor(areas, dtype=values.dtype, device=values.device)
    if values.ndim != 3 or values.shape[-1] != 2 or values.shape[0] == 0 or values.shape[1] == 0:
        raise ValueError("stretches must have nonempty shape [F,T,2]")
    frames, triangles = values.shape[:2]
    if mask.shape != (triangles,) or mask.dtype != torch.bool:
        raise ValueError("valid must be boolean [T]")
    if area.shape != (triangles,):
        raise ValueError("areas must have shape [T]")
    if not bool(torch.isfinite(values[:,mask]).all()) or not bool((values[:,mask] > 0).all()):
        raise ValueError("stretches must be finite and strictly positive")
    if not bool(torch.isfinite(area).all()) or not bool((area >= 0).all()):
        raise ValueError("areas must be finite and nonnegative")
    if not bool(mask.any()) or not bool((area[mask] > 0).all()):
        raise ValueError("valid triangles must have positive area")

    upper = torch.relu(values - 1.5)
    lower = torch.relu(0.67 - values)
    boundary = (upper.square() + lower.square()).mean(dim=-1)
    valid_boundary = boundary[:, mask]
    valid_area = area[mask]
    scores = valid_boundary.mean(dim=0)
    count = int(mask.sum())
    top_count = max(1, (count + 99) // 100)
    order = torch.argsort(scores, descending=True, stable=True)[:top_count]
    original_indices = torch.arange(triangles, device=values.device, dtype=torch.long)[mask][order]
    top_boundary = valid_boundary[:, order]
    total_boundary = valid_boundary.sum()
    top_boundary_sum = top_boundary.sum()
    total_area = valid_area.sum()
    top_area = valid_area[order].sum()
    if float(total_boundary) == 0.0:
        boundary_share = 0.0
        per_frame = torch.zeros(frames, dtype=values.dtype, device=values.device)
    else:
        boundary_share = float(top_boundary_sum / total_boundary)
        frame_totals = valid_boundary.sum(dim=1)
        per_frame = torch.where(frame_totals > 0, top_boundary.sum(dim=1) / frame_totals,
                                torch.zeros_like(frame_totals))

    violation = ((values > 1.5) | (values < 0.67)).any(dim=-1)
    valid_violation = violation[:, mask]
    count_fraction = float(valid_violation.to(values.dtype).mean())
    area_fraction = float((valid_violation.to(values.dtype) * valid_area[None]).sum()
                          / (valid_area.sum() * frames))
    return {
        "topTriangleIndices": [int(value) for value in original_indices.detach().cpu().tolist()],
        "topCount": top_count,
        "topBoundaryContributionShare": boundary_share,
        "topRestAreaShare": float(top_area / total_area),
        "perFrameBoundaryContributionFractions": per_frame.detach().cpu().tolist(),
        "countViolationFraction": count_fraction,
        "areaWeightedViolationFraction": area_fraction,
        "validTriangleCount": count,
        "boundaryThresholds": {"min": 0.67, "max": 1.5},
    }


__all__ = ["attribute_surface"]
