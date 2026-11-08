"""Rest-skeleton placement diagnostics: bbox report and front/side/top overlay PNG."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

REGION_COLORS = {
    "torso": (200, 200, 200),
    "neck_head": (255, 80, 80),
    "beak": (255, 200, 0),
    "tail": (80, 200, 255),
    "wing_left": (80, 255, 80),
    "wing_right": (255, 120, 255),
    "leg_left": (255, 160, 60),
    "leg_right": (160, 100, 255),
}

# Idle-0 front (XY) is the authoritative bind view. Side and top are the
# correction views used to catch depth/width errors a single plate cannot see.
BIND_VIEWS: tuple[tuple[str, tuple[int, int]], ...] = (
    ("front", (0, 1)),
    ("side", (2, 1)),
    ("top", (0, 2)),
)


def view_containment(
    vertices: np.ndarray,
    joints: np.ndarray,
    axes: tuple[int, int],
    *,
    margin_fraction: float = 0.05,
) -> dict[str, Any]:
    """How far projected joints sit outside the mesh's projected AABB."""
    vertices = np.asarray(vertices, dtype=np.float64)
    joints = np.asarray(joints, dtype=np.float64)
    mesh_xy = vertices[:, list(axes)]
    joint_xy = joints[:, list(axes)]
    lo = mesh_xy.min(axis=0)
    hi = mesh_xy.max(axis=0)
    span = hi - lo
    if not np.isfinite(span).all() or float(np.linalg.norm(span)) <= 1e-12:
        raise ValueError("projected mesh AABB is degenerate")
    margin = span * float(margin_fraction)
    lo_m, hi_m = lo - margin, hi + margin
    outside = np.maximum(lo_m - joint_xy, 0.0) + np.maximum(joint_xy - hi_m, 0.0)
    distance = np.linalg.norm(outside, axis=1)
    diag = float(np.linalg.norm(span))
    joint_span = float(np.linalg.norm(np.ptp(joint_xy, axis=0)))
    return {
        "axes": [int(axes[0]), int(axes[1])],
        "meshBbox": [float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1])],
        "outsideFraction": float((distance > 0.0).mean()),
        "jointsOutsideCount": int((distance > 0.0).sum()),
        "jointCount": int(len(joints)),
        "maxDistanceOutsideFractionOfDiagonal": float(distance.max() / diag),
        "coverage": joint_span / diag,
        "diagonal": diag,
    }


def multi_view_placement_report(
    vertices: np.ndarray,
    joints: np.ndarray,
    names: list[str] | None = None,
    *,
    margin_fraction: float = 0.05,
) -> dict[str, Any]:
    """3D AABB plus front/side/top projected containment."""
    vertices = np.asarray(vertices, dtype=np.float64)
    joints = np.asarray(joints, dtype=np.float64)
    if names is None:
        names = [f"j{i:02d}" for i in range(len(joints))]
    volume = skeleton_placement_report(
        vertices, joints, list(names), margin_fraction=margin_fraction
    )
    views = {
        name: view_containment(vertices, joints, axes, margin_fraction=margin_fraction)
        for name, axes in BIND_VIEWS
    }
    worst_outside = max(row["outsideFraction"] for row in views.values())
    worst_distance = max(row["maxDistanceOutsideFractionOfDiagonal"] for row in views.values())
    return {
        **volume,
        "views": views,
        "worstViewOutsideFraction": float(worst_outside),
        "worstViewMaxDistanceOutsideFractionOfDiagonal": float(worst_distance),
    }


def skeleton_placement_report(
    vertices: np.ndarray,
    joints: np.ndarray,
    names: list[str],
    *,
    margin_fraction: float = 0.05,
) -> dict[str, Any]:
    """How far each rest joint lies outside the mesh bounding box (0 = inside)."""
    lo = vertices.min(axis=0)
    hi = vertices.max(axis=0)
    margin = (hi - lo) * margin_fraction
    lo_m, hi_m = lo - margin, hi + margin
    outside = np.maximum(lo_m - joints, 0.0) + np.maximum(joints - hi_m, 0.0)
    distance = np.linalg.norm(outside, axis=1)
    diag = float(np.linalg.norm(hi - lo))
    return {
        "meshBboxMin": lo.tolist(),
        "meshBboxMax": hi.tolist(),
        "meshBboxDiagonal": diag,
        "marginFraction": margin_fraction,
        "jointsOutsideBbox": [
            {"joint": names[i], "distanceOutside": float(distance[i]), "fractionOfDiagonal": float(distance[i] / diag)}
            for i in range(len(names))
            if distance[i] > 0.0
        ],
        "jointsOutsideCount": int((distance > 0.0).sum()),
        "jointCount": int(len(names)),
        "maxDistanceOutsideFractionOfDiagonal": float(distance.max() / diag),
    }


def write_skeleton_overlay(
    path: Path,
    *,
    vertices: np.ndarray,
    regions: np.ndarray,
    joints: np.ndarray,
    parents: np.ndarray,
    names: list[str],
    title: str,
) -> None:
    """Front / side / top orthographic point cloud (colored by region) with the rest skeleton."""
    from PIL import Image, ImageDraw

    size, pad = 320, 20
    allpts = np.concatenate([vertices, joints])
    lo = allpts.min(axis=0)
    span = float(np.ptp(allpts, axis=0).max())

    def project(points: np.ndarray, axes: tuple[int, int]) -> np.ndarray:
        x = (points[:, axes[0]] - lo[axes[0]]) / span * (size - 2 * pad) + pad
        y = size - ((points[:, axes[1]] - lo[axes[1]]) / span * (size - 2 * pad) + pad)
        return np.stack([x, y], axis=1)

    image = Image.new("RGB", (size * 3, size + 24), (10, 10, 14))
    draw = ImageDraw.Draw(image)
    draw.text((4, 4), title, fill="white")
    labels = regions.astype(str)
    for column, (axes, label) in enumerate([((0, 1), "front XY"), ((2, 1), "side ZY"), ((0, 2), "top XZ")]):
        ox = column * size
        pv = project(vertices, axes)
        pj = project(joints, axes)
        for k in range(0, len(vertices), 2):
            color = REGION_COLORS.get(labels[k], (120, 120, 120))
            image.putpixel((int(ox + pv[k, 0]), int(pv[k, 1] + 24)), color)
        for i, parent in enumerate(parents):
            if parent >= 0:
                draw.line(
                    [(ox + pj[parent, 0], pj[parent, 1] + 24), (ox + pj[i, 0], pj[i, 1] + 24)],
                    fill=(255, 255, 0),
                    width=2,
                )
        for i in range(len(joints)):
            x, y = pj[i]
            draw.ellipse([ox + x - 3, y + 21, ox + x + 3, y + 27], fill=(255, 40, 40))
            draw.text((ox + x + 4, y + 20), names[i][-3:], fill=(255, 255, 120))
        draw.text((ox + 4, 26), label, fill=(180, 180, 200))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
