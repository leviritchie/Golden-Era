"""Register bind rest to the idle sprite with one upright yaw.

Meshy built these meshes from the idle still. World Y stays screen-up.
The only free rotation is yaw around Y. Scale and offset then put the
projected bind AABB on the idle alpha AABB. No job-camera isometric.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from preview import idle_alpha_bbox, project_points

YAW_STEP_DEG = 10.0
YAW_REFINE_DEG = 2.0
SEARCH_HEIGHT = 128


def yaw_basis(yaw_deg: float) -> np.ndarray:
    yaw = np.deg2rad(float(yaw_deg))
    cosine = float(np.cos(yaw))
    sine = float(np.sin(yaw))
    return np.asarray(
        (
            (cosine, 0.0, sine),
            (0.0, -1.0, 0.0),
        ),
        dtype=np.float64,
    )


def _scale_offset(xy: np.ndarray, idle_bbox: tuple[float, float, float, float]) -> tuple[float, np.ndarray]:
    x0, y0, x1, y1 = idle_bbox
    span = np.maximum(xy.max(axis=0) - xy.min(axis=0), 1e-8)
    idle_w = max(1.0, x1 - x0)
    idle_h = max(1.0, y1 - y0)
    scale = min(idle_w / span[0], idle_h / span[1])
    if scale <= 0:
        raise ValueError("idle yaw scale is not positive")
    idle_center = np.asarray((0.5 * (x0 + x1), 0.5 * (y0 + y1)), dtype=np.float64)
    offset = idle_center - scale * xy.mean(axis=0)
    return float(scale), offset


def camera_from_yaw(
    *,
    yaw_deg: float,
    vertices: np.ndarray,
    idle_bbox: tuple[float, float, float, float],
) -> dict[str, Any]:
    basis = yaw_basis(yaw_deg)
    xy = (basis @ np.asarray(vertices, dtype=np.float64).T).T
    scale, offset = _scale_offset(xy, idle_bbox)
    return {
        "cameraPolicy": "idle_yaw_register",
        "basisName": "y_up_yaw",
        "yawDeg": float(yaw_deg),
        "basisScreenRows": basis.tolist(),
        "pxPerWorld": scale,
        "screenOffsetPx": offset.tolist(),
        "sourceFrame": 0,
        "screenUpWorldAlignment": 1.0,
    }


def occupancy_mask(
    *,
    vertices: np.ndarray,
    triangles: np.ndarray,
    camera: dict,
    width: int,
    height: int,
) -> np.ndarray:
    xy = project_points(vertices, camera)
    mask = np.zeros((height, width), dtype=bool)
    for i0, i1, i2 in np.asarray(triangles, dtype=np.int32):
        x0, y0 = xy[i0]
        x1, y1 = xy[i1]
        x2, y2 = xy[i2]
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-6:
            continue
        if area < 0:
            x1, y1, x2, y2 = x2, y2, x1, y1
            area = -area
        minx = max(0, int(np.floor(min(x0, x1, x2))))
        maxx = min(width - 1, int(np.ceil(max(x0, x1, x2))))
        miny = max(0, int(np.floor(min(y0, y1, y2))))
        maxy = min(height - 1, int(np.ceil(max(y0, y1, y2))))
        if minx > maxx or miny > maxy:
            continue
        xs = np.arange(minx, maxx + 1) + 0.5
        ys = np.arange(miny, maxy + 1) + 0.5
        grid_x, grid_y = np.meshgrid(xs, ys)
        w0 = ((x1 - grid_x) * (y2 - grid_y) - (x2 - grid_x) * (y1 - grid_y)) / area
        w1 = ((x2 - grid_x) * (y0 - grid_y) - (x0 - grid_x) * (y2 - grid_y)) / area
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if np.any(inside):
            mask[miny : maxy + 1, minx : maxx + 1] |= inside
    return mask


def _idle_alpha(idle_png: Path) -> np.ndarray:
    image = Image.open(idle_png).convert("RGBA")
    return np.asarray(image)[..., 3] > 0


def _iou(pred: np.ndarray, target: np.ndarray) -> float:
    both = np.logical_and(pred, target).sum()
    either = np.logical_or(pred, target).sum()
    if either == 0:
        return 0.0
    return float(both) / float(either)


def _score_yaw(
    *,
    yaw_deg: float,
    vertices: np.ndarray,
    triangles: np.ndarray,
    idle_bbox: tuple[float, float, float, float],
    target: np.ndarray,
) -> tuple[float, dict[str, Any]]:
    height, width = target.shape
    camera = camera_from_yaw(yaw_deg=yaw_deg, vertices=vertices, idle_bbox=idle_bbox)
    pred = occupancy_mask(
        vertices=vertices,
        triangles=triangles,
        camera=camera,
        width=width,
        height=height,
    )
    return _iou(pred, target), camera


def fit_idle_yaw_camera(
    *,
    vertices: np.ndarray,
    triangles: np.ndarray,
    idle_png: Path,
) -> dict[str, Any]:
    idle_alpha = _idle_alpha(idle_png)
    if not np.any(idle_alpha):
        raise ValueError(f"{idle_png} has no opaque pixels")
    full_bbox = idle_alpha_bbox(idle_png)
    height, width = idle_alpha.shape
    search_h = min(SEARCH_HEIGHT, height)
    scale = search_h / float(height)
    search_w = max(1, int(round(width * scale)))
    target = np.asarray(
        Image.fromarray(idle_alpha.astype(np.uint8) * 255).resize((search_w, search_h), Image.Resampling.NEAREST)
    ) > 0
    search_bbox = (
        full_bbox[0] * scale,
        full_bbox[1] * scale,
        full_bbox[2] * scale,
        full_bbox[3] * scale,
    )
    verts = np.asarray(vertices, dtype=np.float64)
    tris = np.asarray(triangles, dtype=np.int32)
    best_by_iou = -1.0
    best_front_right = -1.0
    yaw_by_iou = 0.0
    yaw_front_right = None
    for yaw in np.arange(0.0, 360.0, YAW_STEP_DEG):
        iou, _camera = _score_yaw(
            yaw_deg=float(yaw),
            vertices=verts,
            triangles=tris,
            idle_bbox=search_bbox,
            target=target,
        )
        if iou > best_by_iou:
            best_by_iou = iou
            yaw_by_iou = float(yaw)
        rad = np.deg2rad(float(yaw))
        if np.cos(rad) > 0.0 and np.sin(rad) >= 0.0 and iou > best_front_right:
            best_front_right = iou
            yaw_front_right = float(yaw)
    if yaw_front_right is not None and best_front_right >= 0.9 * best_by_iou:
        best_yaw = yaw_front_right
        best_iou = best_front_right
        facing = "glTF_front_face_right"
    else:
        best_yaw = yaw_by_iou
        best_iou = best_by_iou
        facing = "max_silhouette_iou"
    refine_from = best_yaw - YAW_STEP_DEG
    refine_to = best_yaw + YAW_STEP_DEG
    for yaw in np.arange(refine_from, refine_to + 0.5 * YAW_REFINE_DEG, YAW_REFINE_DEG):
        wrapped = float(yaw % 360.0)
        iou, _camera = _score_yaw(
            yaw_deg=wrapped,
            vertices=verts,
            triangles=tris,
            idle_bbox=search_bbox,
            target=target,
        )
        rad = np.deg2rad(wrapped)
        allow = True
        if facing == "glTF_front_face_right":
            allow = bool(np.cos(rad) > 0.0 and np.sin(rad) >= 0.0)
        if allow and iou > best_iou:
            best_iou = iou
            best_yaw = wrapped
    camera = camera_from_yaw(yaw_deg=best_yaw, vertices=verts, idle_bbox=full_bbox)
    full_pred = occupancy_mask(
        vertices=verts,
        triangles=tris,
        camera=camera,
        width=width,
        height=height,
    )
    camera["iou"] = _iou(full_pred, idle_alpha)
    camera["searchIou"] = float(best_iou)
    camera["searchSize"] = [search_w, search_h]
    camera["facingRule"] = facing
    if camera["iou"] < 0.15:
        raise ValueError(
            f"idle yaw register IoU {camera['iou']:.3f} is too low for {idle_png}"
        )
    return camera
