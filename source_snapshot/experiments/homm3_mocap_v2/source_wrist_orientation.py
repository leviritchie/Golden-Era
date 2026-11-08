"""Bounded source-guided orientation change for a terminal wrist direction."""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy.spatial.transform import Rotation


def solve_projected_direction(current_direction: Any, target_screen_direction: Any,
                              camera_right: Any, camera_down: Any,
                              max_degrees: float) -> dict[str, Any]:
    current = np.array(current_direction, dtype=np.float64, copy=True).reshape(3)
    target = np.array(target_screen_direction, dtype=np.float64, copy=True).reshape(2)
    right = np.array(camera_right, dtype=np.float64, copy=True).reshape(3)
    down = np.array(camera_down, dtype=np.float64, copy=True).reshape(3)
    if not all(np.isfinite(x).all() for x in (current, target, right, down)):
        raise ValueError("direction and camera inputs must be finite")
    if not np.isfinite(max_degrees) or max_degrees < 0:
        raise ValueError("max_degrees must be finite and nonnegative")
    rn, dn, cn, tn = np.linalg.norm(right), np.linalg.norm(down), np.linalg.norm(current), np.linalg.norm(target)
    if rn < 1e-8 or dn < 1e-8 or cn < 1e-8 or tn < 1e-8:
        raise ValueError("direction, target, and camera basis must be nonzero")
    right /= rn; down /= dn
    if abs(float(right @ down)) > 1e-6:
        raise ValueError("camera plane basis must be orthogonal")
    forward = np.cross(right, down); fn = np.linalg.norm(forward)
    if fn < 1e-8:
        raise ValueError("camera basis is degenerate")
    forward /= fn
    current_unit = current / cn
    projection = np.array([current_unit @ right, current_unit @ down])
    projection_norm = np.linalg.norm(projection)
    if projection_norm < 1e-6:
        raise ValueError("current direction has no observable screen projection")
    target /= tn
    desired_unit = projection_norm * (target[0] * right + target[1] * down) + (current_unit @ forward) * forward
    desired_unit /= np.linalg.norm(desired_unit)
    desired = desired_unit * cn
    cross = np.cross(current_unit, desired_unit)
    cross_norm = float(np.linalg.norm(cross))
    dot = float(np.clip(current_unit @ desired_unit, -1.0, 1.0))
    if cross_norm <= 1e-12:
        if dot >= 0.0:
            rotation = np.eye(3, dtype=np.float64)
        else:
            axis = np.cross(current_unit, np.array([1.0, 0.0, 0.0]))
            if np.linalg.norm(axis) <= 1e-12:
                axis = np.cross(current_unit, np.array([0.0, 1.0, 0.0]))
            axis /= np.linalg.norm(axis)
            rotation = Rotation.from_rotvec(axis * np.pi).as_matrix()
    else:
        axis = cross / cross_norm
        rotation = Rotation.from_rotvec(axis * np.arctan2(cross_norm, dot)).as_matrix()
    angle = float(np.arccos(np.clip((current_unit @ desired_unit), -1.0, 1.0)))
    if np.rad2deg(angle) > float(max_degrees) + 1e-9:
        raise ValueError(f"required orientation change {np.rad2deg(angle):.6f} exceeds max_degrees")
    return {"rotation": rotation, "desiredDirection": desired, "angleRad": angle}


__all__ = ["solve_projected_direction"]
