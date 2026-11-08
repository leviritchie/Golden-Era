#!/usr/bin/env python3
"""Render a side-by-side preview video of fitted poses vs HoMM3 sprites.

Blender invocation:
  blender -b --python render_preview.py -- --job out/.../job.resolved.json --report out/.../fit_report.json
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


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _parse() -> dict:
    args = _argv()
    out = {"job": None, "report": None, "hold": 4}
    i = 0
    while i < len(args):
        if args[i] == "--job":
            out["job"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--report":
            out["report"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--hold":
            out["hold"] = int(args[i + 1])
            i += 2
        else:
            i += 1
    if not out["job"] or not out["report"]:
        raise SystemExit("need --job and --report")
    return out


def _clear() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _setup_lights() -> None:
    light_data = bpy.data.lights.new(name="Key", type="SUN")
    light_data.energy = 2.5
    light = bpy.data.objects.new(name="Key", object_data=light_data)
    bpy.context.collection.objects.link(light)
    light.rotation_euler = Euler((math.radians(40), math.radians(15), math.radians(30)), "XYZ")

    fill_data = bpy.data.lights.new(name="Fill", type="SUN")
    fill_data.energy = 0.8
    fill = bpy.data.objects.new(name="Fill", object_data=fill_data)
    bpy.context.collection.objects.link(fill)
    fill.rotation_euler = Euler((math.radians(60), math.radians(-40), math.radians(-20)), "XYZ")


def _apply_deltas(arm, rest, names, vec, *, root_rest, cam_axes, root_translate: bool) -> None:
    n_rot = len(names) * 3
    for i, name in enumerate(names):
        pb = arm.pose.bones[name]
        pb.rotation_mode = "XYZ"
        base = rest[name]
        o = i * 3
        pb.rotation_euler = Euler(
            (base.x + float(vec[o]), base.y + float(vec[o + 1]), base.z + float(vec[o + 2])),
            "XYZ",
        )
    if root_translate and len(vec) >= n_rot + 3:
        right, up, forward = cam_axes
        tr, tu, tf = float(vec[n_rot]), float(vec[n_rot + 1]), float(vec[n_rot + 2])
        arm.location = root_rest + right * tr + up * tu + forward * tf
    else:
        arm.location = Vector(root_rest)


def main() -> int:
    from PIL import Image, ImageDraw, ImageFont

    opts = _parse()
    job = json.loads(opts["job"].read_text(encoding="utf-8"))
    report = json.loads(opts["report"].read_text(encoding="utf-8"))
    out_dir = Path(job["outputDir"]) / "preview"
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    _clear()
    bpy.ops.import_scene.gltf(filepath=str(Path(job["masterGlb"])))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next((o for o in bpy.data.objects if o.type == "MESH"), None)
    if mesh is not None:
        import bmesh

        bm = bmesh.new()
        bm.from_mesh(mesh.data)
        before = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-4)
        removed = before - len(bm.verts)
        bm.to_mesh(mesh.data)
        bm.free()
        mesh.data.update()
        if removed:
            print(f"[preview] weld-on-load removed {removed} duplicate verts", flush=True)
    if arm.animation_data:
        arm.animation_data_clear()

    names = list(report["optimizeBones"])
    rest = {}
    for name in names:
        pb = arm.pose.bones[name]
        pb.rotation_mode = "XYZ"
        rest[name] = pb.rotation_euler.copy()
    root_rest = arm.location.copy()
    root_translate = bool(report.get("rootTranslate", False))

    world = bpy.data.worlds.new("PreviewWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.08, 0.09, 0.12, 1)
    bg.inputs["Strength"].default_value = 0.4

    cam = setup_pose_camera(job, arm, bpy_module=bpy)
    m = cam.matrix_world.to_3x3()
    cam_axes = (
        (m @ Vector((1.0, 0.0, 0.0))).normalized(),
        (m @ Vector((0.0, 1.0, 0.0))).normalized(),
        (m @ Vector((0.0, 0.0, -1.0))).normalized(),
    )
    _setup_lights()

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 8
    # Higher res preview for video
    scene.render.resolution_x = 480
    scene.render.resolution_y = 420
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False

    pose_vectors = report["poseVectors"]
    sprite_paths = [Path(fr["path"]) for fr in job["frames"]]
    hold = int(opts["hold"])
    composed = []

    for i, vec in enumerate(pose_vectors):
        _apply_deltas(
            arm,
            rest,
            names,
            np.asarray(vec, dtype=np.float64),
            root_rest=root_rest,
            cam_axes=cam_axes,
            root_translate=root_translate,
        )
        bpy.context.view_layer.update()
        render_path = frames_dir / f"mesh_{i:02d}.png"
        scene.render.filepath = str(render_path)
        bpy.ops.render.render(write_still=True)

        mesh_im = Image.open(render_path).convert("RGBA")
        spr = Image.open(sprite_paths[i]).convert("RGBA")
        # Upscale sprite nearest to similar height
        target_h = mesh_im.height
        scale = target_h / spr.height
        spr_big = spr.resize((max(1, int(spr.width * scale)), target_h), Image.Resampling.NEAREST)
        pad = Image.new("RGBA", (spr_big.width + 40, target_h), (20, 22, 28, 255))
        pad.paste(spr_big, (20, 0), spr_big)

        gap = 16
        label_h = 36
        total_w = pad.width + gap + mesh_im.width
        total_h = target_h + label_h
        canvas = Image.new("RGBA", (total_w, total_h), (20, 22, 28, 255))
        canvas.paste(pad, (0, label_h), pad)
        canvas.paste(mesh_im, (pad.width + gap, label_h), mesh_im)
        draw = ImageDraw.Draw(canvas)
        draw.text((12, 8), f"HoMM3 sprite  frame {i}", fill=(220, 220, 220, 255))
        draw.text((pad.width + gap + 12, 8), f"Fitted mesh  frame {i}", fill=(220, 220, 220, 255))
        out_frame = frames_dir / f"side_{i:02d}.png"
        canvas.convert("RGB").save(out_frame)
        for _ in range(hold):
            composed.append(canvas.convert("RGB"))
        print(f"[preview] frame {i}", flush=True)

    gif_path = out_dir / "attack_g11_side_by_side.gif"
    mp4_frames_dir = out_dir / "mp4_frames"
    mp4_frames_dir.mkdir(exist_ok=True)
    for i, im in enumerate(composed):
        im.save(mp4_frames_dir / f"f_{i:04d}.png")

    # hold copies per source frame => each copy lasts 1/(12*hold) seconds to keep clip at 12fps timing
    duration_ms = max(1, int(round(1000.0 / (12.0 * hold))))
    composed[0].save(
        gif_path,
        save_all=True,
        append_images=composed[1:],
        duration=duration_ms,
        loop=0,
    )

    meta = {
        "gif": str(gif_path).replace("\\", "/"),
        "mp4FramesDir": str(mp4_frames_dir).replace("\\", "/"),
        "frameCount": len(pose_vectors),
        "hold": hold,
    }
    (out_dir / "preview_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, **meta}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
