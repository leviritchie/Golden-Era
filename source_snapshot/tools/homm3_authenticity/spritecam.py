"""The DEF-matched sprite camera as a pixel mapping in glTF space (numpy only, no torch).

Shared by board.py (renders through it), keypoints.py and joint_coverage.py (project GLB bones into DEF pixels).
build_unit.py exports the SpriteCam in Blender world (Z up); x = ox + s * dot(p, right), y = oy - s * dot(p, up).
"""
from __future__ import annotations

import math

import numpy as np


def ry(v, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    v = np.asarray(v, np.float64)
    return np.array([c * v[0] + s * v[2], v[1], -s * v[0] + c * v[2]])


def sprite_camera(sc: dict, deyaw_deg: float | None) -> dict:
    """build_unit.py SpriteCam (Blender world, Z up) as a pixel mapping in glTF space:
    x = ox + s * dot(p, right), y = oy - s * dot(p, up). Blender (x, y, z) = glTF (x, -z, y)."""
    b2g = lambda v: np.array([v[0], v[2], -v[1]], np.float64)  # noqa: E731
    r, u, f = b2g(sc["right"]), b2g(sc["up"]), b2g(sc["forward"])
    if deyaw_deg:
        # deyaw_glb.py premultiplied every Hips key by Ry(-yawDeg): turn the camera with the body
        r, u, f = ry(r, -deyaw_deg), ry(u, -deyaw_deg), ry(f, -deyaw_deg)
    return {"kind": "ortho", "eye": [0.0, 0.0, 0.0], "right": r, "up": u, "fwd": f, "scale": float(sc["pxPerUnit"]),
            "cx": float(sc["offset"][0]), "cy": float(sc["offset"][1]), "W": int(sc["size"][0]), "H": int(sc["size"][1])}


def view_yawed(cam: dict, yaw_deg: float | None) -> dict:
    """board.py --view-yaw: turn the camera about world up like the pose fitters' view yaw (proj.py / posefit.py
    rotate the SpriteCam forward by Rz(yaw) in Blender = ry(+yaw) in glTF)."""
    if not yaw_deg:
        return cam
    return dict(cam, right=ry(cam["right"], yaw_deg), up=ry(cam["up"], yaw_deg), fwd=ry(cam["fwd"], yaw_deg))


def project(cam: dict, P: np.ndarray) -> np.ndarray:
    """(..., 3) glTF points -> (..., 2) pixels of cam (ortho)."""
    P = np.asarray(P, np.float64)
    return np.stack([cam["cx"] + cam["scale"] * (P @ np.asarray(cam["right"])),
                     cam["cy"] - cam["scale"] * (P @ np.asarray(cam["up"]))], -1)
