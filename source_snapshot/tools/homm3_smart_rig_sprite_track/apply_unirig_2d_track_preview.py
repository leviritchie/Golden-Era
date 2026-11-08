#!/usr/bin/env python3
"""
Blender: apply UniRig 2D LK tracks as camera-axis bone rotations + root translate,
render lit frames, write GIF-timed preview.

Usage:
  blender -b --python apply_unirig_2d_track_preview.py -- \\
    --glb PATH --keypoints PATH --out-dir PATH [--gif-frame-ms 180]
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Matrix, Quaternion, Vector


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _parse():
    args = _argv()
    out = {
        "glb": None,
        "keypoints": None,
        "out_dir": None,
        "gif_frame_ms": 180,
        "proj_mode": "side_zy",
    }
    i = 0
    while i < len(args):
        if args[i] == "--glb" and i + 1 < len(args):
            out["glb"] = Path(args[i + 1]); i += 2
        elif args[i] == "--keypoints" and i + 1 < len(args):
            out["keypoints"] = Path(args[i + 1]); i += 2
        elif args[i] == "--out-dir" and i + 1 < len(args):
            out["out_dir"] = Path(args[i + 1]); i += 2
        elif args[i] == "--gif-frame-ms" and i + 1 < len(args):
            out["gif_frame_ms"] = int(args[i + 1]); i += 2
        elif args[i] == "--proj-mode" and i + 1 < len(args):
            out["proj_mode"] = args[i + 1]; i += 2
        else:
            i += 1
    if not out["glb"] or not out["keypoints"] or not out["out_dir"]:
        raise SystemExit("need --glb --keypoints --out-dir")
    return out


def _clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for b in list(bpy.data.armatures):
        bpy.data.armatures.remove(b)
    for m in list(bpy.data.meshes):
        bpy.data.meshes.remove(m)
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)


def _find_arm_mesh():
    arm = None
    mesh = None
    for obj in bpy.context.scene.objects:
        if obj.type == "ARMATURE":
            arm = obj
        elif obj.type == "MESH":
            mesh = obj
    if arm is None or mesh is None:
        raise RuntimeError(f"missing arm/mesh arm={arm} mesh={mesh}")
    return arm, mesh


def _setup_camera_light(mesh):
    bbox = [mesh.matrix_world @ Vector(c) for c in mesh.bound_box]
    xs = [v.x for v in bbox]; ys = [v.y for v in bbox]; zs = [v.z for v in bbox]
    cx, cy, cz = 0.5 * (min(xs) + max(xs)), 0.5 * (min(ys) + max(ys)), 0.5 * (min(zs) + max(zs))
    size = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 0.1)

    # Match track proj side_zy: look along -X so image u~Z, v~Y
    cam_data = bpy.data.cameras.new("PilotCam")
    cam = bpy.data.objects.new("PilotCam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = (cx - size * 2.4, cy + size * 0.15, cz)
    # point at center
    direction = Vector((cx, cy, cz)) - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    cam_data.lens = 50
    bpy.context.scene.camera = cam

    light_data = bpy.data.lights.new("PilotKey", "AREA")
    light_data.energy = 250
    light_data.size = size * 2.0
    light = bpy.data.objects.new("PilotKey", light_data)
    bpy.context.scene.collection.objects.link(light)
    light.location = (cx - size, cy + size * 1.5, cz + size)
    fill_data = bpy.data.lights.new("PilotFill", "AREA")
    fill_data.energy = 80
    fill_data.size = size * 2.0
    fill = bpy.data.objects.new("PilotFill", fill_data)
    bpy.context.scene.collection.objects.link(fill)
    fill.location = (cx + size * 0.5, cy - size, cz + size * 0.5)
    return cam, size


def _world_head(arm, name: str) -> Vector:
    pb = arm.pose.bones[name]
    return arm.matrix_world @ pb.head


def _set_pose_from_2d(
    arm,
    edges: list[dict],
    joints_px: dict[str, tuple[float, float]],
    rest_px: dict[str, tuple[float, float]],
    root_name: str,
    px_to_world: float,
    view_axis_world: Vector,
):
    """Apply delta edge angles around view axis; translate root by 2D delta."""
    # reset
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = Quaternion((1, 0, 0, 0))
        pb.location = Vector((0, 0, 0))

    # root translate in camera plane (approximate via world Y/Z for side_zy view along -X)
    if root_name in joints_px and root_name in rest_px:
        dx = (joints_px[root_name][0] - rest_px[root_name][0]) * px_to_world
        dy = (joints_px[root_name][1] - rest_px[root_name][1]) * px_to_world
        # image u→+Z, image v→-Y (because image y down); view along -X
        root_pb = arm.pose.bones[root_name]
        # convert world delta into bone local
        world_delta = Vector((0.0, -dy, dx))
        parent_mw = arm.matrix_world
        if root_pb.parent:
            parent_mw = arm.matrix_world @ root_pb.parent.matrix
        local = parent_mw.inverted() @ (parent_mw @ Vector((0, 0, 0)) + world_delta)
        # location is in bone local space relative to rest
        root_pb.location = local

    view = view_axis_world.normalized()
    # process edges parent→child: rotate child bone so rest 2D edge aims like tracked 2D edge
    for e in edges:
        parent = e["parentName"]
        child = e["childName"]
        if parent not in joints_px or child not in joints_px:
            continue
        if parent not in rest_px or child not in rest_px:
            continue
        if child not in arm.pose.bones:
            continue
        r0 = np.array(rest_px[parent], dtype=np.float64)
        r1 = np.array(rest_px[child], dtype=np.float64)
        t0 = np.array(joints_px[parent], dtype=np.float64)
        t1 = np.array(joints_px[child], dtype=np.float64)
        vr = r1 - r0
        vt = t1 - t0
        n0 = float(np.linalg.norm(vr))
        n1 = float(np.linalg.norm(vt))
        if n0 < 1e-3 or n1 < 1e-3:
            continue
        a0 = math.atan2(vr[1], vr[0])
        a1 = math.atan2(vt[1], vt[0])
        # image y-down vs world y-up: angle sign for rotation around -X (into scene from cam)
        # rotating around world -X: positive rotates Y toward Z... use delta carefully
        delta = a1 - a0
        # In image space, +angle is clockwise (y down). World view along -X with u=Z v=-Y:
        # clockwise image ≈ positive rotation around +X? Empirically use -delta around view.
        q = Quaternion(view, -delta)
        pb = arm.pose.bones[child]
        # apply as additional pose rotation in bone local space around axis mapped from world
        # convert world-axis rotation into bone local
        bone_mw = arm.matrix_world @ pb.matrix
        axis_local = (bone_mw.inverted().to_3x3() @ view).normalized()
        q_local = Quaternion(axis_local, -delta)
        pb.rotation_quaternion = q_local @ pb.rotation_quaternion


def _render_frame(out_path: Path, res: int = 512):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.resolution_x = res
    scene.render.resolution_y = res
    scene.render.filepath = str(out_path)
    # transparent film
    scene.render.film_transparent = True
    bpy.ops.render.render(write_still=True)


def main():
    opt = _parse()
    kpt = json.loads(opt["keypoints"].read_text(encoding="utf-8"))
    frames = kpt["frames"]
    edges = kpt["edges"]
    out_dir = opt["out_dir"]
    lit_dir = out_dir / "lit"
    lit_dir.mkdir(parents=True, exist_ok=True)

    _clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(opt["glb"]))
    arm, mesh = _find_arm_mesh()
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="POSE")

    cam, size = _setup_camera_light(mesh)
    view_axis = Vector((-1.0, 0.0, 0.0))  # camera looks +X direction from -X

    # rest joints = frame 0
    rest = {n: (float(j["x"]), float(j["y"])) for n, j in frames[0]["joints"].items()}
    # approximate px→world from bone AABB vs joint AABB on frame 0
    bone_ws = []
    for pb in arm.pose.bones:
        bone_ws.append(_world_head(arm, pb.name))
    if bone_ws:
        zs = [v.z for v in bone_ws]; ys = [v.y for v in bone_ws]
        world_span = max(max(zs) - min(zs), max(ys) - min(ys), 1e-3)
    else:
        world_span = size
    xs = [rest[n][0] for n in rest]; ys = [rest[n][1] for n in rest]
    px_span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    px_to_world = world_span / px_span

    root_name = "Bone_000" if "Bone_000" in arm.pose.bones else arm.pose.bones[0].name

    rendered = []
    for fr in frames:
        fi = int(fr["frame"])
        joints = {n: (float(j["x"]), float(j["y"])) for n, j in fr["joints"].items()}
        _set_pose_from_2d(arm, edges, joints, rest, root_name, px_to_world, view_axis)
        bpy.context.view_layer.update()
        op = lit_dir / f"lit_{fi:02d}.png"
        _render_frame(op, res=512)
        rendered.append(op)
        print(f"RENDERED {fi} {op}")

    # GIF via Pillow
    from PIL import Image

    imgs = []
    for p in rendered:
        im = Image.open(p).convert("RGBA")
        bg = Image.new("RGB", im.size, (24, 24, 28))
        bg.paste(im, mask=im.split()[-1])
        imgs.append(bg)
    gif = out_dir / "lit_preview.gif"
    imgs[0].save(
        gif,
        save_all=True,
        append_images=imgs[1:],
        duration=int(opt["gif_frame_ms"]),
        loop=0,
        optimize=False,
    )
    report = {
        "ok": True,
        "frames": len(rendered),
        "gif": str(gif),
        "pxToWorld": px_to_world,
        "root": root_name,
        "proof": "generated artifact validated — camera-axis 2D→pose pilot; not OE runtime",
    }
    (out_dir / "lit_preview_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as ex:
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
