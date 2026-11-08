#!/usr/bin/env python3
"""Render fitted mesh animation with projected skeleton overlay.

Blender:
  blender -b --python render_fitted_mesh_skeleton.py -- \\
    --fit-dir artifacts/crusader_pose_pipeline/out_fit/g00_move_authored_minimal

Uses the same poseVectors / camera as the fit preview. Overlay is projected
from the posed armature onto each rendered mesh frame.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Euler, Vector
from PIL import Image, ImageDraw

TOOL = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL))
from homm3_pose_camera import effective_root_yaw_deg, setup_pose_camera  # noqa: E402

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
W = 480
H = 420


def _argv_after_sep() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _apply_deltas(arm, rest, names, vec, *, root_rest, cam_axes, root_translate: bool, root_yaw_deg: float) -> None:
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
    arm.rotation_mode = "XYZ"
    arm.rotation_euler[2] = math.radians(root_yaw_deg)
    if root_translate and len(vec) >= n_rot + 3:
        right, up, forward = cam_axes
        tr, tu, tf = float(vec[n_rot]), float(vec[n_rot + 1]), float(vec[n_rot + 2])
        arm.location = root_rest + right * tr + up * tu + forward * tf
    else:
        arm.location = Vector(root_rest)


def _project_segs(arm, scene, cam, optimize: set[str]) -> list:
    segs = []
    for b in arm.pose.bones:
        h = arm.matrix_world @ b.head
        t = arm.matrix_world @ b.tail
        ch = world_to_camera_view(scene, cam, h)
        ct = world_to_camera_view(scene, cam, t)
        a = (int(round(ch.x * W)), int(round((1.0 - ch.y) * H)))
        c = (int(round(ct.x * W)), int(round((1.0 - ct.y) * H)))
        if not (-40 <= a[0] <= W + 40 and -40 <= a[1] <= H + 40):
            continue
        if not (-40 <= c[0] <= W + 40 and -40 <= c[1] <= H + 40):
            continue
        segs.append((b.name, a, c, b.name in optimize))
    return segs


def _draw_skel(im: Image.Image, segs: list, *, label: str) -> Image.Image:
    out = im.convert("RGB")
    d = ImageDraw.Draw(out)
    for _name, a, b, opt in segs:
        col = (0, 255, 80) if opt else (80, 200, 255)
        d.line([a, b], fill=(0, 0, 0), width=7)
        d.line([a, b], fill=col, width=4)
        r = 5
        d.ellipse([a[0] - r - 1, a[1] - r - 1, a[0] + r + 1, a[1] + r + 1], fill=(0, 0, 0))
        d.ellipse([a[0] - r, a[1] - r, a[0] + r, a[1] + r], fill=(255, 40, 255))
    d.text((8, 8), label, fill=(255, 255, 0))
    d.text((8, 24), f"bones={len(segs)}  green=optimized", fill=(255, 255, 0))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit-dir", type=Path, required=True)
    ap.add_argument("--reuse-mesh-frames", action="store_true", default=True)
    ap.add_argument("--rerender", action="store_true", help="Re-render mesh instead of reusing preview frames")
    args = ap.parse_args(_argv_after_sep())
    if args.rerender:
        args.reuse_mesh_frames = False

    fit_dir = args.fit_dir.resolve()
    if not fit_dir.is_absolute():
        fit_dir = (ROOT / args.fit_dir).resolve()
    job_path = fit_dir / "job.resolved.json"
    report_path = fit_dir / "fit_report.json"
    if not job_path.is_file() or not report_path.is_file():
        raise SystemExit(f"missing job/report under {fit_dir}")

    job = json.loads(job_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    out_dir = fit_dir / "preview" / "mesh_skeleton"
    out_dir.mkdir(parents=True, exist_ok=True)
    mesh_src = fit_dir / "preview" / "frames"

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(job["masterGlb"])))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    if arm.animation_data:
        arm.animation_data_clear()

    names = list(report["optimizeBones"])
    optimize = set(names)
    rest = {}
    for name in names:
        pb = arm.pose.bones[name]
        pb.rotation_mode = "XYZ"
        rest[name] = pb.rotation_euler.copy()
    root_rest = arm.location.copy()
    root_translate = bool(report.get("rootTranslate", False))
    root_yaw = effective_root_yaw_deg(job)

    world = bpy.data.worlds.new("W")
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

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 8
    scene.render.resolution_x = W
    scene.render.resolution_y = H
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False

    if not args.reuse_mesh_frames:
        # Match preview lighting when re-rendering.
        key = bpy.data.lights.new(name="Key", type="SUN")
        key.energy = 2.5
        key_o = bpy.data.objects.new(name="Key", object_data=key)
        bpy.context.collection.objects.link(key_o)
        key_o.rotation_euler = Euler((math.radians(40), math.radians(15), math.radians(30)), "XYZ")

    gif_frames = []
    paths = []
    for i, vec in enumerate(report["poseVectors"]):
        _apply_deltas(
            arm,
            rest,
            names,
            np.asarray(vec, dtype=np.float64),
            root_rest=root_rest,
            cam_axes=cam_axes,
            root_translate=root_translate,
            root_yaw_deg=root_yaw,
        )
        bpy.context.view_layer.update()
        segs = _project_segs(arm, scene, cam, optimize)
        if len(segs) < 8:
            raise SystemExit(f"frame {i}: too few projected bones ({len(segs)})")

        mesh_path = mesh_src / f"mesh_{i:02d}.png"
        if args.reuse_mesh_frames and mesh_path.is_file():
            mesh_im = Image.open(mesh_path).convert("RGB")
            if mesh_im.size != (W, H):
                mesh_im = mesh_im.resize((W, H), Image.Resampling.BILINEAR)
        else:
            raw = out_dir / f"mesh_raw_{i:02d}.png"
            scene.render.filepath = str(raw)
            bpy.ops.render.render(write_still=True)
            mesh_im = Image.open(raw).convert("RGB")

        labeled = _draw_skel(mesh_im, segs, label=f"fitted mesh+skel f{i:02d}")
        out_frame = out_dir / f"mesh_skel_{i:02d}.png"
        labeled.save(out_frame)
        gif_frames.append(labeled)
        paths.append(str(out_frame).replace("\\", "/"))
        print(f"[mesh-skel] frame {i}/{len(report['poseVectors'])-1} bones={len(segs)}", flush=True)

    clip = str(report.get("clipId") or "fitted")
    gif_path = out_dir / f"{clip}_mesh_skeleton.gif"
    gif_frames[0].save(
        gif_path,
        save_all=True,
        append_images=gif_frames[1:],
        duration=180,
        loop=0,
        optimize=False,
    )
    report_out = {
        "ok": True,
        "fitDir": str(fit_dir).replace("\\", "/"),
        "gif": str(gif_path).replace("\\", "/"),
        "frames": paths,
        "frameCount": len(paths),
        "reuseMeshFrames": bool(args.reuse_mesh_frames),
        "proof": "generated — fitted mesh with projected skeleton; not OE runtime",
    }
    (out_dir / "mesh_skeleton_report.json").write_text(
        json.dumps(report_out, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report_out, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
