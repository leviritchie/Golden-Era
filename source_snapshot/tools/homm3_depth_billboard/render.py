"""Software rasterizer for depth-displaced billboard points.

The camera looks at the origin. Yaw 0 is the authored front (camera on +Z,
looking toward −Z), so a front render reconstructs the original sprite. Yaw
rotates around Y so a profile view shows the depth relief.
"""
from __future__ import annotations

import math

import numpy as np

from geometry import BillboardPoints


def _look_rotation(yaw_deg: float, pitch_deg: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    forward = np.array((-sy * cp, sp, -cy * cp), dtype=np.float32)
    right = np.array((cy, 0.0, -sy), dtype=np.float32)
    up = np.cross(right, forward)
    up_norm = float(np.linalg.norm(up))
    if up_norm < 1e-6:
        raise ValueError("camera up is degenerate")
    up = (up / up_norm).astype(np.float32)
    return forward, right, up.astype(np.float32)


def _splat_offsets(radius: int) -> list[tuple[int, int]]:
    if radius < 1:
        raise ValueError("splat_radius must be >= 1")
    offsets: list[tuple[int, int]] = []
    for dr in range(radius):
        for dc in range(radius):
            offsets.append((dr, dc))
    return offsets


def render_billboard_points(
    points: BillboardPoints,
    *,
    yaw_deg: float = 0.0,
    pitch_deg: float = 0.0,
    out_width: int | None = None,
    out_height: int | None = None,
    background: tuple[int, int, int, int] = (18, 22, 28, 255),
    perspective: bool = False,
    camera_distance: float = 2.4,
    splat_radius: int = 1,
    solid_front: bool = True,
) -> np.ndarray:
    """Rasterize independent pixel splats. Returns HxWx4 uint8.

    Front orthographic (yaw=0, perspective=False) can composite the filled source
    sprite so the authored view stays solid. ``splat_radius`` expands stamps for
    perspective / orbit previews to hide pinholes between depth layers.
    """
    width = int(out_width or points.width)
    height = int(out_height or points.height)
    if width < 1 or height < 1:
        raise ValueError("output size must be positive")
    if int(splat_radius) < 1:
        raise ValueError("splat_radius must be >= 1")

    if (
        solid_front
        and not perspective
        and abs(yaw_deg) < 1e-6
        and abs(pitch_deg) < 1e-6
        and points.source_rgba is not None
        and width == points.width
        and height == points.height
    ):
        return points.source_rgba.copy()

    forward, right, up = _look_rotation(yaw_deg, pitch_deg)
    xyz = points.xyz()
    cam_x = xyz @ right
    cam_y = xyz @ up
    cam_z = xyz @ forward

    aspect = points.aspect
    canvas = np.zeros((height, width, 4), dtype=np.uint8)
    canvas[:] = np.array(background, dtype=np.uint8)

    if perspective:
        view_depth = camera_distance + cam_z
        visible = view_depth > 1e-4
        scale = camera_distance / np.clip(view_depth, 0.35, None)
        scale = np.minimum(scale, 2.5)
        proj_x = cam_x * scale
        proj_y = cam_y * scale
        sort_z = view_depth
    else:
        visible = np.ones(points.count, dtype=bool)
        proj_x = cam_x
        proj_y = cam_y
        sort_z = cam_z

    if points.facing is not None:
        view_along_billboard_z = float(-forward[2])
        facing = points.facing
        shell_visible = np.zeros(points.count, dtype=bool)
        if view_along_billboard_z > 0.12:
            shell_visible |= facing > 0
        if view_along_billboard_z < -0.12:
            shell_visible |= facing < 0
        if abs(view_along_billboard_z) <= 0.35:
            shell_visible |= facing == 0
        visible &= shell_visible

    cols = np.floor((proj_x / aspect + 0.5) * width).astype(np.int32)
    rows = np.floor((0.5 - proj_y) * height).astype(np.int32)
    offsets = _splat_offsets(int(splat_radius))

    for dr, dc in offsets:
        stamp = (
            visible
            & (cols + dc >= 0)
            & (cols + dc < width)
            & (rows + dr >= 0)
            & (rows + dr < height)
        )
        if not stamp.any():
            continue
        idx = np.nonzero(stamp)[0]
        nearest = np.argsort(sort_z[idx], kind="stable")
        idx = idx[nearest]
        linear = (rows[idx] + dr) * width + (cols[idx] + dc)
        _, first = np.unique(linear, return_index=True)
        canvas.reshape(-1, 4)[linear[first]] = points.rgba[idx[first]]
    return canvas
