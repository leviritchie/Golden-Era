"""One frozen presentation camera in capture/OBJ space. No per-panel auto-fit."""
from __future__ import annotations

from typing import Any

import numpy as np

from preview import project_points

VIEW_BASES = {
    "front": np.array(((1.0, 0.0, 0.0), (0.0, -1.0, 0.0)), dtype=np.float64),
    "side": np.array(((0.0, 0.0, 1.0), (0.0, -1.0, 0.0)), dtype=np.float64),
    "top": np.array(((1.0, 0.0, 0.0), (0.0, 0.0, -1.0)), dtype=np.float64),
    "underside": np.array(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), dtype=np.float64),
}


def freeze_shared_camera(
    points: np.ndarray,
    *,
    width: int,
    height: int,
    margin: float = 0.08,
    space: str = "captureSpace",
) -> dict[str, Any]:
    values = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if values.shape[0] < 2:
        raise ValueError("shared camera needs at least two points")
    cameras: dict[str, Any] = {
        "space": str(space),
        "perPanelAutofit": False,
        "width": int(width),
        "height": int(height),
    }
    for name, basis in VIEW_BASES.items():
        xy = (basis @ values.T).T
        span = np.maximum(xy.max(axis=0) - xy.min(axis=0), 1e-8)
        scale = (1.0 - 2.0 * margin) * min(width / span[0], height / span[1])
        if scale <= 0:
            raise ValueError(f"{name} shared scale is not positive")
        offset = np.array((width * 0.5, height * 0.5), dtype=np.float64) - scale * xy.mean(axis=0)
        cameras[name] = {
            "cameraPolicy": "shared_capture_space",
            "basisName": f"capture_{name}",
            "basisScreenRows": basis.tolist(),
            "pxPerWorld": float(scale),
            "screenOffsetPx": offset.tolist(),
            "screenUpWorldAlignment": 1.0,
        }
    return cameras


def project_view(points: np.ndarray, cameras: dict[str, Any], view: str) -> np.ndarray:
    if cameras.get("perPanelAutofit"):
        raise ValueError("refusing a camera marked per-panel auto-fit")
    camera = cameras[view]
    if camera.get("cameraPolicy") != "shared_capture_space":
        raise ValueError(f"{view} is not the frozen shared camera")
    return project_points(points, camera)
