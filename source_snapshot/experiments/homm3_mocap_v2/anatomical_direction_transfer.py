"""Explicit-gauge direction transport for one anatomical branch.

This is a diagnostic primitive only.  A plane hint is mandatory: world-axis
fallbacks would make the result depend on the camera or scene coordinates.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from direction_retarget import bone_frame


_EPS = 1.0e-8


def _unit(value: Any, label: str) -> np.ndarray:
    vector = np.asarray(value, dtype=np.float64).reshape(-1)
    if vector.size != 3 or not np.isfinite(vector).all():
        raise ValueError(f"{label} must be finite [3]")
    norm = float(np.linalg.norm(vector))
    if norm <= _EPS:
        raise ValueError(f"{label} must be nonzero")
    return vector / norm


def _basis(direction: Any, plane_hint: Any, prefix: str) -> np.ndarray:
    axis = _unit(direction, f"{prefix}_rest_direction")
    hint = _unit(plane_hint, f"{prefix}_plane_hint")
    projected = hint - axis * float(np.dot(axis, hint))
    norm = float(np.linalg.norm(projected))
    if norm <= 1.0e-6:
        raise ValueError(f"{prefix}_plane_hint is collinear with rest direction")
    # Reuse the established frame constructor only after strict validation;
    # its historical axis fallbacks are therefore unreachable here.
    basis = bone_frame(axis, projected / norm)
    if not np.allclose(basis.T @ basis, np.eye(3), atol=1e-10, rtol=0.0):
        raise ValueError(f"{prefix} anatomical basis is not orthonormal")
    if float(np.linalg.det(basis)) <= 0.0:
        raise ValueError(f"{prefix} anatomical basis is not proper")
    return basis


def transfer_direction(
    capture_rest_direction: Any,
    target_rest_direction: Any,
    capture_pose_direction: Any,
    capture_plane_hint: Any,
    target_plane_hint: Any,
) -> np.ndarray:
    """Transport a posed source direction through explicit source/target gauges."""
    source_basis = _basis(capture_rest_direction, capture_plane_hint, "capture")
    target_basis = _basis(target_rest_direction, target_plane_hint, "target")
    pose = _unit(capture_pose_direction, "capture_pose_direction")
    local = source_basis.T @ pose
    result = target_basis @ local
    return _unit(result, "transferred_direction")


__all__ = ["transfer_direction"]
