#!/usr/bin/env python3
"""Animate the Roc mesh from an action reading, not independent pixel IK.

The sprite motion is interpreted as a wingbeat.  The sprite supplies the
screen-space direction of named body/wing chains; the mesh keeps its 3D bone
lengths and hidden legs stay in the bind pose instead of being dragged onto
feather pixels.
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


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def make_camera(fit: dict, arm):
    rows = fit["basisScreenRows"]
    right = Vector(rows[0]).normalized()
    up = (-Vector(rows[1])).normalized()
    forward = right.cross(up).normalized()
    if forward.dot(Vector((0.0, 0.0, 1.0))) < 0.0:
        forward.negate()
        up.negate()
    rotation = Matrix((right, up, -forward)).transposed().to_4x4()
    data = bpy.data.cameras.new("RocActionCamera")
    data.type = "ORTHO"
    data.ortho_scale = float(fit["sourceResolution"][1]) / float(fit["pxPerWorld"])
    camera = bpy.data.objects.new("RocActionCamera", data)
    bpy.context.collection.objects.link(camera)
    camera.location = arm.matrix_world.translation - forward * 6.0
    camera.matrix_world = Matrix.Translation(camera.location) @ rotation
    bpy.context.scene.camera = camera
    return camera, right, up, forward


def visible_bone(name: str) -> bool:
    return name.startswith(("Bone_00", "Bone_01", "Bone_02", "Bone_03", "Bone_04", "Bone_05", "Bone_06", "Bone_017", "Bone_018", "Bone_019", "Bone_020", "Bone_021", "Bone_022", "Bone_023", "Bone_024", "Bone_025", "Bone_026", "Bone_027", "Bone_028", "Bone_029", "Bone_030", "Bone_031", "Bone_032", "Bone_033", "Bone_034", "Bone_035", "Bone_036", "Bone_037", "Bone_038", "Bone_039", "Bone_040", "Bone_041", "Bone_042", "Bone_043", "Bone_044", "Bone_045")) and not name in {"Bone_007", "Bone_008", "Bone_009", "Bone_010", "Bone_011", "Bone_012", "Bone_013", "Bone_014", "Bone_015", "Bone_016"}


def screen_target_direction(frame, bone_name, child_name, fit, right, up, forward, current_vec):
    a = frame["joints"].get(bone_name)
    b = frame["joints"].get(child_name)
    if not a or not b:
        return current_vec.normalized()
    dx = float(b["x"]) - float(a["x"])
    dy = float(b["y"]) - float(a["y"])
    screen = Vector((dx, -dy, 0.0))
    if screen.length < 1e-5:
        return current_vec.normalized()
    # Scale only controls the amount of screen direction used.  The current
    # depth component is retained, so a profile sprite cannot flatten the rig.
    depth = current_vec.dot(forward)
    desired = right * screen.x + up * screen.y + forward * (depth * 8.0)
    return desired.normalized()


def solve_chain(arm, frame, fit, right, up, forward):
    inv = arm.matrix_world.inverted()
    order = [b for b in arm.pose.bones if b.parent is None or b.parent.name in {x.name for x in arm.pose.bones}]
    # Blender's armature collection is parent-before-child for imported GLBs;
    # sort explicitly to make the action deterministic.
    order.sort(key=lambda b: len(list(iter_parents(b))))
    for pb in order:
        if not visible_bone(pb.name) or not pb.children:
            continue
        child = next((c for c in pb.children if visible_bone(c.name)), None)
        if child is None:
            continue
        bpy.context.view_layer.update()
        head_world = arm.matrix_world @ pb.head
        current_vec = arm.matrix_world.to_3x3() @ (pb.tail - pb.head)
        desired = screen_target_direction(frame, pb.name, child.name, fit, right, up, forward, current_vec)
        delta = current_vec.normalized().rotation_difference(desired)
        current_rot = (arm.matrix_world @ pb.matrix).to_3x3()
        target_rot = delta.to_matrix() @ current_rot
        pb.matrix = inv @ (Matrix.Translation(head_world) @ target_rot.to_4x4())


def iter_parents(pb):
    while pb.parent is not None:
        yield pb.parent
        pb = pb.parent


def main() -> int:
    src = Path(arg("--src") or "")
    fit = load(Path(arg("--fit") or ""))
    keypoints = load(Path(arg("--keypoints") or ""))
    out = Path(arg("--out") or "")
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(src.resolve()))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    for modifier in mesh.modifiers:
        if modifier.type == "ARMATURE":
            modifier.use_deform_preserve_volume = True

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 24
    scene.render.resolution_x = 768
    scene.render.resolution_y = 683
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    if scene.world is None:
        scene.world = bpy.data.worlds.new("RocActionWorld")
    scene.world.color = (0.015, 0.015, 0.02)
    scene.render.fps = 6
    _, right, up, forward = make_camera(fit, arm)

    light_data = bpy.data.lights.new("RocActionKey", type="AREA")
    light_data.energy = 900.0
    light_data.shape = "DISK"
    light_data.size = 5.0
    light = bpy.data.objects.new("RocActionKey", light_data)
    bpy.context.collection.objects.link(light)
    light.location = arm.matrix_world.translation + Vector((2.5, -3.0, 3.5))
    light.rotation_euler = (math.radians(25), 0.0, math.radians(35))

    rendered = []
    for frame in keypoints["frames"]:
        index = int(frame["frame"])
        scene.frame_set(index)
        solve_chain(arm, frame, fit, right, up, forward)
        bpy.context.view_layer.update()
        path = out / f"mesh_{index:02d}.png"
        scene.render.filepath = str(path.resolve())
        bpy.ops.render.render(write_still=True)
        rendered.append(str(path))
        print(f"RENDERED frame={index}", flush=True)
    (out / "action_report.json").write_text(json.dumps({
        "interpretation": "near wing deep downstroke to high upstroke and return; far wing foreshortened; head forward; tail follows; legs bind/occluded",
        "frames": len(rendered),
        "proof": "generated mesh preview; not owned delivery bind or runtime proof",
        "renders": rendered,
    }, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
