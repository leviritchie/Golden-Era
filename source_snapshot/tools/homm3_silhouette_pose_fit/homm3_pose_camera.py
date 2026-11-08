#!/usr/bin/env python3
"""
Shared camera contract for HoMM3 sprite pose fit.

HoMM3 battle sprites are isometric / three-quarter views — never flat side profiles.
Use camera.axis = "iso" (default for new configs) with azimuth from character front
toward the profile that reads as facing-right on screen.
"""
from __future__ import annotations

import math
from typing import Any

from mathutils import Euler, Vector


def effective_root_yaw_deg(job: dict) -> float:
    cam = job.get("camera") or {}
    mirror = job.get("mirror") or {}
    return float(cam.get("rootYawDeg", 0.0)) + float(mirror.get("reorientYawDeg", 0.0))


def setup_pose_camera(job: dict, arm, *, bpy_module, link_to_scene: bool = True):
    """
    Create ortho camera matching job['camera'].

    axis:
      iso  — isometric / 3/4 (required default for HoMM3 sprites)
      -X/+X/-Y/+Y — legacy cardinal views (diagnostic only)
    isoAzimuthDeg: 0 = front (-Y), 90 = -X profile (facing-right silhouette). Typical 35–45.
    isoElevationDeg: look-down angle from horizontal. Typical 25–35 for battle sprites.
    """
    import bpy as _bpy

    bpy = bpy_module or _bpy
    cfg = job.get("camera") or {}
    axis = str(cfg.get("axis", "iso")).upper()
    if axis == "ISO":
        axis = "iso"
    distance = float(cfg.get("distance", 3.0))
    height = float(cfg.get("height", 0.85))
    ortho_scale = float(cfg.get("orthoScale", 2.6))

    cam_data = bpy.data.cameras.new("PoseFitCam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ortho_scale
    cam = bpy.data.objects.new("PoseFitCam", cam_data)
    if link_to_scene:
        bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    if axis == "iso":
        az = math.radians(float(cfg.get("isoAzimuthDeg", 40.0)))
        el = math.radians(float(cfg.get("isoElevationDeg", 30.0)))
        # Radius in XY from distance; elevation sets Z.
        r = distance * math.cos(el)
        x = -r * math.sin(az)
        y = -r * math.cos(az)
        z = distance * math.sin(el) + float(cfg.get("isoZOffset", 0.35))
        cam.location = Vector((x, y, z))
        target = Vector((0.0, 0.0, float(cfg.get("lookAtZ", 0.75))))
        direction = target - cam.location
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    elif axis == "-X":
        cam.location = Vector((-distance, 0.0, height))
        cam.rotation_euler = Euler((math.pi / 2.0, 0.0, -math.pi / 2.0), "XYZ")
    elif axis == "+X":
        cam.location = Vector((distance, 0.0, height))
        cam.rotation_euler = Euler((math.pi / 2.0, 0.0, math.pi / 2.0), "XYZ")
    elif axis == "-Y":
        cam.location = Vector((0.0, -distance, height))
        cam.rotation_euler = Euler((math.pi / 2.0, 0.0, 0.0), "XYZ")
    elif axis == "+Y":
        cam.location = Vector((0.0, distance, height))
        cam.rotation_euler = Euler((math.pi / 2.0, 0.0, math.pi), "XYZ")
    else:
        raise RuntimeError(
            f"unsupported camera.axis={axis!r}; use 'iso' for HoMM3 sprites "
            f"(or legacy -X/+X/-Y/+Y for diagnostics)"
        )

    yaw = effective_root_yaw_deg(job)
    arm.rotation_mode = "XYZ"
    arm.rotation_euler = Euler((0.0, 0.0, math.radians(yaw)), "XYZ")
    bpy.context.view_layer.update()
    return cam


def camera_report(job: dict) -> dict[str, Any]:
    cfg = job.get("camera") or {}
    axis = str(cfg.get("axis", "iso"))
    out = {
        "axis": axis,
        "orthoScale": float(cfg.get("orthoScale", 2.6)),
        "rootYawDeg": effective_root_yaw_deg(job),
    }
    if axis.lower() == "iso":
        out["isoAzimuthDeg"] = float(cfg.get("isoAzimuthDeg", 40.0))
        out["isoElevationDeg"] = float(cfg.get("isoElevationDeg", 30.0))
    return out
