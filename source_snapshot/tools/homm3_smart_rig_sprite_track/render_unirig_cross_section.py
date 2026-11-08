#!/usr/bin/env python3
"""Render smart-rig mesh from multiple angles and dump projected bone pixels."""
from __future__ import annotations

import json
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

OUT = Path(r"V:/Games/Olden Era Playtest Tweak/artifacts/roc_pose_pipeline/smart_rig_move_pilot/rig_cross_section")
GLB = Path(r"V:/Games/Olden Era Playtest Tweak/artifacts/roc_pose_pipeline/smart_rig_move_pilot/griffon_smart_rigged.glb")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(GLB))
    arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.context.scene.objects if o.type == "MESH")

    pts = [mesh.matrix_world @ Vector(c) for c in mesh.bound_box]
    for pb in arm.pose.bones:
        pts.append(arm.matrix_world @ pb.head)
        pts.append(arm.matrix_world @ pb.tail)
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    zs = [p.z for p in pts]
    cx, cy, cz = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2
    span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 0.1)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.film_transparent = True
    scene.render.resolution_x = 1000
    scene.render.resolution_y = 800
    scene.render.image_settings.file_format = "PNG"

    light_data = bpy.data.lights.new("Key", "AREA")
    light_data.energy = 500
    light_data.size = span * 3
    key = bpy.data.objects.new("Key", light_data)
    scene.collection.objects.link(key)
    fill_data = bpy.data.lights.new("Fill", "AREA")
    fill_data.energy = 180
    fill_data.size = span * 3
    fill = bpy.data.objects.new("Fill", fill_data)
    scene.collection.objects.link(fill)

    cam_data = bpy.data.cameras.new("XSecCam")
    cam_data.lens = 55
    cam = bpy.data.objects.new("XSecCam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    beak = arm.matrix_world @ arm.pose.bones["Bone_028"].head
    tail = arm.matrix_world @ arm.pose.bones["Bone_004"].head
    root = arm.matrix_world @ arm.pose.bones["Bone_000"].head
    print("PROBE beak", list(beak), "tail", list(tail), "root", list(root))

    views = {
        "profile_mX": {"loc": (cx - span * 1.7, cy, cz), "up": "Z"},
        "profile_pX": {"loc": (cx + span * 1.7, cy, cz), "up": "Z"},
        "top": {"loc": (cx, cy, cz + span * 1.9), "up": "Y"},
        "front_mY": {"loc": (cx, cy - span * 1.7, cz + span * 0.15), "up": "Z"},
        "front_pY": {"loc": (cx, cy + span * 1.7, cz + span * 0.15), "up": "Z"},
    }

    results = {}
    for name, spec in views.items():
        cam.location = Vector(spec["loc"])
        direction = Vector((cx, cy, cz)) - cam.location
        cam.rotation_euler = direction.to_track_quat("-Z", spec["up"]).to_euler()
        key.location = Vector(spec["loc"]) + Vector((0.0, span * 0.4, span * 0.8))
        fill.location = Vector((cx, cy, cz)) + Vector((span * 0.6, -span * 0.4, span * 0.3))
        scene.render.filepath = str(OUT / f"mesh_{name}.png")
        bpy.ops.render.render(write_still=True)

        bones = {}
        for pb in arm.pose.bones:
            wh = arm.matrix_world @ pb.head
            wt = arm.matrix_world @ pb.tail
            coh = world_to_camera_view(scene, cam, wh)
            cot = world_to_camera_view(scene, cam, wt)
            bones[pb.name] = {
                "head": [float(wh.x), float(wh.y), float(wh.z)],
                "tail": [float(wt.x), float(wt.y), float(wt.z)],
                "px": float(coh.x * scene.render.resolution_x),
                "py": float((1.0 - coh.y) * scene.render.resolution_y),
                "tpx": float(cot.x * scene.render.resolution_x),
                "tpy": float((1.0 - cot.y) * scene.render.resolution_y),
            }
        edges = [{"parent": pb.parent.name, "child": pb.name} for pb in arm.pose.bones if pb.parent]
        payload = {
            "view": name,
            "camLoc": list(cam.location),
            "center": [cx, cy, cz],
            "span": span,
            "res": [scene.render.resolution_x, scene.render.resolution_y],
            "bones": bones,
            "edges": edges,
            "beakPx": bones["Bone_028"]["px"],
            "tailPx": bones["Bone_004"]["px"],
        }
        (OUT / f"proj_{name}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        results[name] = {"beakPx": payload["beakPx"], "tailPx": payload["tailPx"]}
        print("VIEW", name, "beakPx", round(payload["beakPx"], 1), "tailPx", round(payload["tailPx"], 1))

    (OUT / "view_summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("DONE")


if __name__ == "__main__":
    main()
