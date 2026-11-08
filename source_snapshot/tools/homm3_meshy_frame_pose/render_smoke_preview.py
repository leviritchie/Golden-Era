#!/usr/bin/env python3
"""
Blender: render retargeted master mesh still for smoke preview.

  blender -b --python render_smoke_preview.py -- \\
    --master-posed posed.glb --output-png mesh_00.png [--camera-json camera.json]
"""
from __future__ import annotations

import json
import math
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Euler, Vector


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _parse() -> dict:
    args = _argv()
    out = {"masterPosed": None, "outputPng": None, "camera": {}}
    i = 0
    while i < len(args):
        if args[i] == "--master-posed" and i + 1 < len(args):
            out["masterPosed"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--output-png" and i + 1 < len(args):
            out["outputPng"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--camera-json" and i + 1 < len(args):
            out["camera"] = json.loads(Path(args[i + 1]).read_text(encoding="utf-8"))
            i += 2
        else:
            i += 1
    if not out["masterPosed"] or not out["outputPng"]:
        raise SystemExit("need --master-posed --output-png")
    return out


def _clear() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def run(opts: dict) -> dict:
    _clear()
    bpy.ops.import_scene.gltf(filepath=str(opts["masterPosed"]))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")

    cam_data = bpy.data.cameras.new("SmokeCam")
    cam_data.type = "ORTHO"
    cam = bpy.data.objects.new("SmokeCam", cam_data)
    bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    cfg = opts.get("camera") or {}
    distance = float(cfg.get("distance", 3.0))
    height = float(cfg.get("height", 0.85))
    ortho_scale = float(cfg.get("orthoScale", 2.6))
    cam.location = Vector((-distance, 0.0, height))
    cam.rotation_euler = Euler((math.pi / 2.0, 0.0, -math.pi / 2.0), "XYZ")
    cam_data.ortho_scale = ortho_scale
    yaw = float(cfg.get("rootYawDeg", 0.0))
    if abs(yaw) > 1e-6:
        arm.rotation_mode = "XYZ"
        arm.rotation_euler[2] = math.radians(yaw)

    light_data = bpy.data.lights.new(name="Key", type="SUN")
    light_data.energy = 2.5
    light = bpy.data.objects.new(name="Key", object_data=light_data)
    bpy.context.collection.objects.link(light)
    light.rotation_euler = Euler((math.radians(40), math.radians(15), math.radians(30)), "XYZ")

    scene = bpy.context.scene
    scene.frame_set(1)
    out_png = Path(opts["outputPng"])
    out_png.parent.mkdir(parents=True, exist_ok=True)
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.filepath = str(out_png)
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    print(json.dumps({"ok": True, "meshPng": str(out_png).replace("\\", "/")}, indent=2), flush=True)
    return {"ok": True, "meshPng": str(out_png)}


def main() -> int:
    try:
        run(_parse())
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
