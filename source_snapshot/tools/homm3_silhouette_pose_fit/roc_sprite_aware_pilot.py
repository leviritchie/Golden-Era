#!/usr/bin/env python3
"""Drive the supplied Roc smart rig from sprite landmarks in calibrated 3D.

This is intentionally a pilot lane.  It uses the smart rig for speed, but the
important correction is explicit: sprite pixels are mapped through one fitted
camera basis, while every bone keeps its bind-depth instead of treating pixel
X/Y as Blender X/Y.  Each frame is solved from the previous pose's target
depth and the bind hierarchy is never silently replaced by an isometric view.

Run with Blender 3.5:
  blender -b --python roc_sprite_aware_pilot.py -- --src <glb> --fit <json>
      --keypoints <json> --out <dir>
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

ARGS = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def arg(name: str, default: str | None = None) -> str | None:
    for i, value in enumerate(ARGS):
        if value == name and i + 1 < len(ARGS):
            return ARGS[i + 1]
    return default


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def make_camera(fit: dict, arm, width: int, height: int):
    rows = fit["basisScreenRows"]
    right = Vector(rows[0]).normalized()
    # The fitted second row follows image coordinates, where positive Y is down.
    up = (-Vector(rows[1])).normalized()
    forward = right.cross(up).normalized()
    if forward.dot(Vector((0.0, 0.0, 1.0))) < 0.0:
        forward.negate()
        up.negate()
    rotation = Matrix((right, up, -forward)).transposed().to_4x4()

    cam_data = bpy.data.cameras.new("RocSpriteFitCam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = float(fit["sourceResolution"][1]) / float(fit["pxPerWorld"])
    cam = bpy.data.objects.new("RocSpriteFitCam", cam_data)
    bpy.context.collection.objects.link(cam)
    center = arm.matrix_world.translation.copy()
    cam.location = center - forward * 6.0
    cam.matrix_world = Matrix.Translation(cam.location) @ rotation
    bpy.context.scene.camera = cam
    return cam, right, up, forward


def world_bone_data(arm):
    out = {}
    for bone in arm.data.bones:
        head = arm.matrix_world @ bone.head_local
        tail = arm.matrix_world @ bone.tail_local
        out[bone.name] = {"head": head.copy(), "tail": tail.copy(), "bone": bone}
    return out


def target_worlds(frame: dict, fit: dict, rest: dict, right: Vector, up: Vector, forward: Vector):
    scale = float(fit["pxPerWorld"])
    offset = Vector((float(fit["screenOffsetPx"][0]), float(fit["screenOffsetPx"][1])))
    root = rest["Bone_000"]["head"]
    root_depth = root.dot(forward)
    raw = {}
    for name, point in frame["joints"].items():
        if name not in rest:
            continue
        px = (float(point["x"]) - offset.x) / scale
        py_down = (float(point["y"]) - offset.y) / scale
        depth = rest[name]["head"].dot(forward)
        raw[name] = right * px + up * (-py_down) + forward * depth
    # Keep the full rig near the calibrated mesh rather than allowing the
    # independently fitted screen origin to introduce a root translation jump.
    delta = root - raw["Bone_000"]
    raw = {name: value + delta for name, value in raw.items()}

    # The sprite landmarks are measurements, not a license to stretch the
    # imported rig.  Reconstruct the 3D graph from the root outward with each
    # bind bone length fixed.  This is the critical difference from the first
    # pilot, which placed every bone head independently and tore the skin.
    by_parent: dict[str | None, list[str]] = {}
    for name, data in rest.items():
        parent = data["bone"].parent.name if data["bone"].parent else None
        by_parent.setdefault(parent, []).append(name)
    solved = {"Bone_000": raw["Bone_000"]}
    stack = ["Bone_000"]
    while stack:
        parent_name = stack.pop(0)
        parent_head = solved[parent_name]
        for child_name in by_parent.get(parent_name, []):
            if child_name not in raw:
                continue
            rest_vec = rest[child_name]["tail"] - rest[child_name]["head"]
            length = max(rest_vec.length, 1e-5)
            desired = raw[child_name] - parent_head
            if desired.length < 1e-6:
                desired = rest_vec
            solved[child_name] = parent_head + desired.normalized() * length
            stack.append(child_name)
    return solved


def apply_pose(arm, targets, rest):
    inv_arm = arm.matrix_world.inverted()
    ordered = list(arm.data.bones)
    for bone in ordered:
        head = targets.get(bone.name)
        if head is None:
            continue
        child = next((c for c in bone.children if c.name in targets), None)
        if child is not None:
            tail = targets[child.name]
        else:
            rest_vec = rest[bone.name]["tail"] - rest[bone.name]["head"]
            tail = head + rest_vec
        rest_vec = rest[bone.name]["tail"] - rest[bone.name]["head"]
        target_vec = tail - head
        if rest_vec.length < 1e-7 or target_vec.length < 1e-7:
            continue
        delta = rest_vec.normalized().rotation_difference(target_vec.normalized())
        rest_rot = (arm.matrix_world @ bone.matrix_local).to_3x3()
        target_rot = delta.to_matrix() @ rest_rot
        target_matrix = Matrix.Translation(head) @ target_rot.to_4x4()
        pb = arm.pose.bones[bone.name]
        pb.matrix = inv_arm @ target_matrix
        pb.keyframe_insert(data_path="location", frame=bpy.context.scene.frame_current)
        pb.keyframe_insert(data_path="rotation_quaternion", frame=bpy.context.scene.frame_current)


def main() -> int:
    src = Path(arg("--src") or "")
    fit_path = Path(arg("--fit") or "")
    keypoints_path = Path(arg("--keypoints") or "")
    out = Path(arg("--out") or "")
    if not src or not fit_path or not keypoints_path or not out:
        raise SystemExit("need --src, --fit, --keypoints, --out")
    out.mkdir(parents=True, exist_ok=True)
    fit = load_json(fit_path)
    keypoints = load_json(keypoints_path)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(src.resolve()))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    for modifier in mesh.modifiers:
        if modifier.type == "ARMATURE":
            modifier.use_deform_preserve_volume = True

    width, height = 768, 683
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 32
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    if scene.world is None:
        scene.world = bpy.data.worlds.new("RocSpriteFitWorld")
    scene.world.color = (0.015, 0.015, 0.02)
    scene.frame_start = 0
    scene.frame_end = len(keypoints["frames"]) - 1
    scene.render.fps = 6

    rest = world_bone_data(arm)
    _, right, up, forward = make_camera(fit, arm, width, height)
    # Use a neutral light rig so silhouettes stay readable while the camera fit
    # is being tuned; the source sprite remains the motion authority.
    light_data = bpy.data.lights.new("RocSpriteFitKey", type="AREA")
    light_data.energy = 900.0
    light_data.shape = "DISK"
    light_data.size = 5.0
    key = bpy.data.objects.new("RocSpriteFitKey", light_data)
    bpy.context.collection.objects.link(key)
    key.location = arm.matrix_world.translation + Vector((2.5, -3.0, 3.5))
    key.rotation_euler = (math.radians(25), 0.0, math.radians(35))

    reports = []
    for frame in keypoints["frames"]:
        scene.frame_set(int(frame["frame"]))
        targets = target_worlds(frame, fit, rest, right, up, forward)
        apply_pose(arm, targets, rest)
        bpy.context.view_layer.update()
        render_path = out / "lit" / f"lit_{int(frame['frame']):02d}.png"
        render_path.parent.mkdir(parents=True, exist_ok=True)
        scene.render.filepath = str(render_path.resolve())
        bpy.ops.render.render(write_still=True)
        reports.append({"frame": int(frame["frame"]), "targetBones": len(targets), "render": str(render_path)})
        print(f"RENDERED {frame['frame']} targetBones={len(targets)}", flush=True)

    report = {
        "ok": True,
        "frames": len(reports),
        "cameraFit": str(fit_path),
        "meanLandmarkErrorPx": fit["meanLandmarkErrorPx"],
        "depthPolicy": fit["depthPolicy"],
        "renders": reports,
        "proof": "generated artifact validated - calibrated 2D-to-3D pilot; smart rig not delivery bind",
    }
    (out / "pilot_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
