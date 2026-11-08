#!/usr/bin/env python3
"""Seed frame-0 joints from the mesh bind pose under the visual-match camera.

Joints come from projected armature landmarks (WeaponTip = farthest hand-skinned
mesh vert), not from reading the sprite. Overlay is drawn on the mesh render.

Blender:
  blender -b --python seed_joints_from_mesh_bind.py -- \\
    --job job.resolved.json --roles roles.json --sprite frame_00.png --out-dir DIR
"""
from __future__ import annotations

import json
import math
import sys
import traceback
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Vector

_TOOL_DIR = Path(__file__).resolve().parent
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))
from homm3_pose_camera import setup_pose_camera  # noqa: E402

EDGES = [
    ("Nose", "Neck"),
    ("Neck", "MidHip"),
    ("Neck", "RShoulder"),
    ("RShoulder", "RElbow"),
    ("RElbow", "RWrist"),
    ("RWrist", "WeaponTip"),
    ("Neck", "LShoulder"),
    ("LShoulder", "LElbow"),
    ("LElbow", "LWrist"),
    ("MidHip", "RHip"),
    ("RHip", "RKnee"),
    ("RKnee", "RAnkle"),
    ("MidHip", "LHip"),
    ("LHip", "LKnee"),
    ("LKnee", "LAnkle"),
]

# Which bone end to project for each joint role.
JOINT_ENDS = {
    "Nose": "head",
    "Neck": "head",
    "MidHip": "head",
    "RShoulder": "head",
    "RElbow": "head",
    "RWrist": "head",
    "LShoulder": "head",
    "LElbow": "head",
    "LWrist": "head",
    "RHip": "head",
    "RKnee": "head",
    "RAnkle": "tail",
    "LHip": "head",
    "LKnee": "head",
    "LAnkle": "tail",
}


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _parse() -> dict:
    args = _argv()
    out = {"job": None, "roles": None, "sprite": None, "out_dir": None}
    i = 0
    while i < len(args):
        if args[i] in {"--job", "--roles", "--sprite", "--out-dir"} and i + 1 < len(args):
            key = "out_dir" if args[i] == "--out-dir" else args[i][2:]
            out[key] = Path(args[i + 1])
            i += 2
        else:
            i += 1
    if not out["job"] or not out["roles"] or not out["sprite"] or not out["out_dir"]:
        raise SystemExit("need --job --roles --sprite --out-dir")
    return out


def _weld(mesh) -> int:
    import bmesh

    bm = bmesh.new()
    bm.from_mesh(mesh.data)
    before = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-4)
    removed = before - len(bm.verts)
    bm.to_mesh(mesh.data)
    bm.free()
    mesh.data.update()
    return removed


def _bone_end_world(arm, bone_name: str, end: str) -> Vector:
    pb = arm.pose.bones[bone_name]
    local = pb.tail if end == "tail" else pb.head
    return arm.matrix_world @ local


def _project_world_px(world: Vector, cam, scene, sw: float, sh: float) -> tuple[float, float]:
    from bpy_extras.object_utils import world_to_camera_view

    co = world_to_camera_view(scene, cam, world)
    return float(co.x) * sw, float(1.0 - co.y) * sh


def _farthest_tip_world(arm, mesh_obj, hand_bone: str, *, min_weight: float = 0.20) -> Vector:
    gmap = {g.name: g.index for g in mesh_obj.vertex_groups}
    if hand_bone not in gmap:
        raise RuntimeError(f"missing vertex group {hand_bone}")
    gi = gmap[hand_bone]
    hand_head = arm.matrix_world @ arm.pose.bones[hand_bone].head
    mw = mesh_obj.matrix_world
    best = None
    best_d = -1.0
    for vi, v in enumerate(mesh_obj.data.vertices):
        w = 0.0
        for g in v.groups:
            if g.group == gi:
                w = float(g.weight)
                break
        if w < min_weight:
            continue
        world = mw @ v.co
        d = (world - hand_head).length_squared
        if d > best_d:
            best_d = d
            best = world
    if best is None:
        raise RuntimeError(f"no tip verts on {hand_bone}")
    return best


def _setup_lights() -> None:
    key = bpy.data.lights.new(name="Key", type="SUN")
    key.energy = 2.5
    key_o = bpy.data.objects.new(name="Key", object_data=key)
    bpy.context.collection.objects.link(key_o)
    key_o.rotation_euler = Euler((math.radians(40), math.radians(15), math.radians(30)), "XYZ")
    fill = bpy.data.lights.new(name="Fill", type="SUN")
    fill.energy = 0.8
    fill_o = bpy.data.objects.new(name="Fill", object_data=fill)
    bpy.context.collection.objects.link(fill_o)
    fill_o.rotation_euler = Euler((math.radians(60), math.radians(-40), math.radians(-20)), "XYZ")


def run(opts: dict) -> dict:
    from PIL import Image, ImageDraw, ImageFont

    job = json.loads(opts["job"].read_text(encoding="utf-8"))
    roles = json.loads(opts["roles"].read_text(encoding="utf-8"))
    sprite = Image.open(opts["sprite"]).convert("RGBA")
    sw, sh = sprite.size
    out_dir = Path(opts["out_dir"]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(job["masterGlb"])))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    removed = _weld(mesh)
    if removed:
        print(f"[mesh-seed] weld-on-load removed {removed}", flush=True)
    if arm.animation_data:
        arm.animation_data_clear()

    world = bpy.data.worlds.new("SeedWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.08, 0.09, 0.12, 1)
    bg.inputs["Strength"].default_value = 0.4

    cam = setup_pose_camera(job, arm, bpy_module=bpy)
    _setup_lights()
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 8
    scene.render.resolution_x = int(sw)
    scene.render.resolution_y = int(sh)
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    bpy.context.view_layer.update()

    joint_bones = roles["joints"]
    tip_bone = joint_bones["WeaponTip"]
    tip_world = _farthest_tip_world(arm, mesh, tip_bone, min_weight=0.20)

    joints = {}
    for jn, bone in joint_bones.items():
        if jn == "WeaponTip":
            px, py = _project_world_px(tip_world, cam, scene, sw, sh)
        else:
            end = JOINT_ENDS.get(jn, "head")
            px, py = _project_world_px(_bone_end_world(arm, bone, end), cam, scene, sw, sh)
        joints[jn] = {
            "x": float(px),
            "y": float(py),
            "score": 1.0,
            "visible": True,
            "source": "mesh_bind_project",
            "bone": bone,
        }
        print(f"[mesh-seed] {jn}@{bone} -> ({px:.1f},{py:.1f})", flush=True)

    mesh_png = out_dir / "mesh_bind_00.png"
    scene.render.filepath = str(mesh_png)
    bpy.ops.render.render(write_still=True)

    # Overlay skeleton on mesh render.
    mesh_im = Image.open(mesh_png).convert("RGBA")
    draw = ImageDraw.Draw(mesh_im)
    stroke = max(2, min(mesh_im.size) // 180)
    try:
        font = ImageFont.truetype("arial.ttf", max(12, min(mesh_im.size) // 55))
    except OSError:
        font = ImageFont.load_default()
    for a, b in EDGES:
        if a in joints and b in joints:
            pa = (joints[a]["x"], joints[a]["y"])
            pb = (joints[b]["x"], joints[b]["y"])
            draw.line([pa, pb], fill=(0, 255, 255, 255), width=stroke)
    for name, j in joints.items():
        x, y = j["x"], j["y"]
        r = stroke + (3 if name == "WeaponTip" else 2)
        col = (255, 140, 0, 255) if name == "WeaponTip" else (255, 255, 0, 255)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=col)
        draw.text(
            (x + r + 2, y - r - 2),
            name,
            fill=(255, 255, 255, 255),
            font=font,
            stroke_width=1,
            stroke_fill=(0, 0, 0, 255),
        )
    overlay_path = out_dir / "mesh_bind_00_skeleton.png"
    mesh_im.save(overlay_path)

    seed_joints = {}
    for k, v in joints.items():
        seed_joints[k] = {
            "x": v["x"],
            "y": v["y"],
            "score": v["score"],
            "visible": v["visible"],
            "source": v["source"],
            "bone": v["bone"],
        }
    seed = {
        "ok": True,
        "frameIndex": 0,
        "spritePath": opts["sprite"].resolve().as_posix(),
        "masterGlb": Path(job["masterGlb"]).resolve().as_posix(),
        "srcWidth": int(sw),
        "srcHeight": int(sh),
        "coordinateSpace": "mesh_bind_visual_match_camera",
        "camera": job.get("camera"),
        "joints": seed_joints,
        "jointSet": list(joints.keys()),
        "notes": (
            "Frame-0 seed projected from UniRig bind pose under the visual-match iso camera. "
            "WeaponTip = farthest Bone_033-skinned mesh vert from the hand bone head. "
            "Not authored from sprite pixels."
        ),
        "proof": "generated artifact validated — mesh-bind screen projection; not OE runtime proven",
        "overlay": overlay_path.resolve().as_posix(),
        "meshRender": mesh_png.resolve().as_posix(),
    }
    seed_path = out_dir / "seed_joints_f00_mesh_bind.json"
    seed_path.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "seed": str(seed_path), "overlay": str(overlay_path)}, indent=2))
    return seed


def main() -> int:
    try:
        run(_parse())
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
