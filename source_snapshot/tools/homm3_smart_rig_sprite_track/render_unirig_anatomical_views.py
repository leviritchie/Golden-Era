#!/usr/bin/env python3
"""Render anatomical profile / top / front of UniRig mesh with tight framing."""
from __future__ import annotations

import json
import math
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

OUT = Path(
    r"V:/Games/Olden Era Playtest Tweak/artifacts/roc_pose_pipeline/smart_rig_move_pilot/rig_cross_section"
)
GLB = Path(
    r"V:/Games/Olden Era Playtest Tweak/artifacts/roc_pose_pipeline/smart_rig_move_pilot/griffon_smart_rigged.glb"
)


def look_at(cam: bpy.types.Object, target: Vector, up: Vector) -> None:
    direction = (target - cam.location).normalized()
    # build basis: -Z looks at target, Y is up
    z_axis = -direction
    x_axis = up.normalized().cross(z_axis).normalized()
    if x_axis.length < 1e-6:
        x_axis = Vector((1, 0, 0)).cross(z_axis).normalized()
    y_axis = z_axis.cross(x_axis).normalized()
    mat = Matrix(
        (
            (x_axis.x, y_axis.x, z_axis.x, cam.location.x),
            (x_axis.y, y_axis.y, z_axis.y, cam.location.y),
            (x_axis.z, y_axis.z, z_axis.z, cam.location.z),
            (0.0, 0.0, 0.0, 1.0),
        )
    )
    cam.matrix_world = mat


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(GLB))
    arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.context.scene.objects if o.type == "MESH")

    def bone_head(name: str) -> Vector:
        return arm.matrix_world @ arm.pose.bones[name].head

    beak = bone_head("Bone_028")
    tip_tail = bone_head("Bone_004")
    root = bone_head("Bone_000")
    wing_l = bone_head("Bone_035")  # wingA
    wing_r = bone_head("Bone_043")  # wingB

    # Anatomical axes from bones
    forward = (beak - tip_tail)
    forward.z = 0.0
    if forward.length < 1e-4:
        forward = (beak - root)
        forward.z = 0.0
    forward.normalize()
    up = Vector((0.0, 0.0, 1.0))
    right = forward.cross(up).normalized()  # bird's right
    # ensure right points toward wingB/right tip
    if (wing_r - root).dot(right) < 0:
        right = -right
    forward = up.cross(right).normalized()

    pts = [mesh.matrix_world @ Vector(c) for c in mesh.bound_box]
    for pb in arm.pose.bones:
        pts.append(arm.matrix_world @ pb.head)
    cx = sum(p.x for p in pts) / len(pts)
    cy = sum(p.y for p in pts) / len(pts)
    cz = sum(p.z for p in pts) / len(pts)
    center = Vector((cx, cy, cz))
    span = max((max(p[i] for p in pts) - min(p[i] for p in pts)) for i in range(3))

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.film_transparent = True
    scene.render.resolution_x = 1100
    scene.render.resolution_y = 850
    scene.render.image_settings.file_format = "PNG"

    light_data = bpy.data.lights.new("Key", "AREA")
    light_data.energy = 550
    light_data.size = span * 3
    key = bpy.data.objects.new("Key", light_data)
    scene.collection.objects.link(key)
    fill_data = bpy.data.lights.new("Fill", "AREA")
    fill_data.energy = 160
    fill_data.size = span * 3
    fill = bpy.data.objects.new("Fill", fill_data)
    scene.collection.objects.link(fill)

    cam_data = bpy.data.cameras.new("AnatCam")
    cam_data.lens = 50
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = span * 1.35
    cam = bpy.data.objects.new("AnatCam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    views = {
        # profile from bird's RIGHT so left wing is far, right wing near — common sprite feel
        "profile": {
            "loc": center + right * (span * 1.6) + up * (span * 0.05),
            "up": up,
            "note": "from bird RIGHT; beak should be image-right if forward matches",
        },
        "profile_left": {
            "loc": center - right * (span * 1.6) + up * (span * 0.05),
            "up": up,
            "note": "from bird LEFT",
        },
        "top": {
            "loc": center + up * (span * 1.8),
            "up": forward,
            "note": "top-down; +forward toward image up",
        },
        "front": {
            "loc": center + forward * (span * 1.7) + up * (span * 0.1),
            "up": up,
            "note": "front from beak",
        },
    }

    axes = {
        "forward": [float(forward.x), float(forward.y), float(forward.z)],
        "right": [float(right.x), float(right.y), float(right.z)],
        "up": [float(up.x), float(up.y), float(up.z)],
        "beak": [float(beak.x), float(beak.y), float(beak.z)],
        "tail": [float(tip_tail.x), float(tip_tail.y), float(tip_tail.z)],
        "wingA_035": [float(wing_l.x), float(wing_l.y), float(wing_l.z)],
        "wingB_043": [float(wing_r.x), float(wing_r.y), float(wing_r.z)],
    }
    (OUT / "anatomical_axes.json").write_text(json.dumps(axes, indent=2), encoding="utf-8")

    summary = {}
    for name, spec in views.items():
        cam.location = Vector(spec["loc"])
        look_at(cam, center, Vector(spec["up"]))
        key.location = cam.location + up * (span * 0.6) + right * (span * 0.2)
        fill.location = center - right * (span * 0.5) + up * (span * 0.2)
        scene.render.filepath = str(OUT / f"anat_mesh_{name}.png")
        bpy.ops.render.render(write_still=True)

        bones = {}
        for pb in arm.pose.bones:
            wh = arm.matrix_world @ pb.head
            co = world_to_camera_view(scene, cam, wh)
            bones[pb.name] = {
                "head": [float(wh.x), float(wh.y), float(wh.z)],
                "px": float(co.x * scene.render.resolution_x),
                "py": float((1.0 - co.y) * scene.render.resolution_y),
            }
        edges = [{"parent": pb.parent.name, "child": pb.name} for pb in arm.pose.bones if pb.parent]
        payload = {
            "view": name,
            "note": spec["note"],
            "camLoc": list(cam.location),
            "res": [scene.render.resolution_x, scene.render.resolution_y],
            "bones": bones,
            "edges": edges,
            "beakPx": bones["Bone_028"]["px"],
            "tailPx": bones["Bone_004"]["px"],
            "beakPy": bones["Bone_028"]["py"],
            "tailPy": bones["Bone_004"]["py"],
        }
        (OUT / f"anat_proj_{name}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        summary[name] = {
            "beakPx": payload["beakPx"],
            "tailPx": payload["tailPx"],
            "beakPy": payload["beakPy"],
            "tailPy": payload["tailPy"],
            "wingA_035": (bones["Bone_035"]["px"], bones["Bone_035"]["py"]),
            "wingB_043": (bones["Bone_043"]["px"], bones["Bone_043"]["py"]),
        }
        print(
            "VIEW",
            name,
            "beak",
            round(payload["beakPx"]),
            round(payload["beakPy"]),
            "tail",
            round(payload["tailPx"]),
            round(payload["tailPy"]),
            "wA",
            tuple(round(v) for v in summary[name]["wingA_035"]),
            "wB",
            tuple(round(v) for v in summary[name]["wingB_043"]),
        )

    (OUT / "anat_view_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("AXES", axes)
    print("DONE")


if __name__ == "__main__":
    main()
