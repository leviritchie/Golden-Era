#!/usr/bin/env python3
"""Render fitted mesh-only clip at 60fps with lit EEVEE shading.

Interpolates marker-IK pose vectors from source fps (usually 12) to 60fps
so motion reads smoothly. Mesh only — no sprite side panel.

Blender:
  blender -b --python render_mesh_lit_60fps.py -- \\
    --job out/.../job.resolved.json --report out/.../fit_report.json
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

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _parse() -> dict:
    args = _argv()
    out = {
        "job": None,
        "report": None,
        "out_fps": 60,
        "src_fps": None,
        "width": 720,
        "height": 720,
    }
    i = 0
    while i < len(args):
        if args[i] == "--job" and i + 1 < len(args):
            out["job"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--report" and i + 1 < len(args):
            out["report"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--out-fps" and i + 1 < len(args):
            out["out_fps"] = int(args[i + 1])
            i += 2
        elif args[i] == "--src-fps" and i + 1 < len(args):
            out["src_fps"] = float(args[i + 1])
            i += 2
        elif args[i] == "--width" and i + 1 < len(args):
            out["width"] = int(args[i + 1])
            i += 2
        elif args[i] == "--height" and i + 1 < len(args):
            out["height"] = int(args[i + 1])
            i += 2
        else:
            i += 1
    if not out["job"] or not out["report"]:
        raise SystemExit("need --job and --report")
    return out


def _clear() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _setup_lit_scene() -> None:
    world = bpy.data.worlds.new("LitWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.12, 0.13, 0.16, 1.0)
    bg.inputs["Strength"].default_value = 0.55

    key = bpy.data.lights.new(name="Key", type="AREA")
    key.energy = 280.0
    key.size = 1.4
    key_o = bpy.data.objects.new(name="Key", object_data=key)
    bpy.context.collection.objects.link(key_o)
    key_o.location = (1.6, -1.8, 2.4)
    key_o.rotation_euler = Euler((math.radians(50), math.radians(10), math.radians(35)), "XYZ")

    fill = bpy.data.lights.new(name="Fill", type="AREA")
    fill.energy = 90.0
    fill.size = 2.0
    fill_o = bpy.data.objects.new(name="Fill", object_data=fill)
    bpy.context.collection.objects.link(fill_o)
    fill_o.location = (-1.8, -0.6, 1.6)
    fill_o.rotation_euler = Euler((math.radians(55), math.radians(-25), math.radians(-40)), "XYZ")

    rim = bpy.data.lights.new(name="Rim", type="SUN")
    rim.energy = 1.6
    rim_o = bpy.data.objects.new(name="Rim", object_data=rim)
    bpy.context.collection.objects.link(rim_o)
    rim_o.rotation_euler = Euler((math.radians(25), math.radians(160), math.radians(10)), "XYZ")

    # Soft ground disc for contact read (not a gameplay ground claim).
    bpy.ops.mesh.primitive_circle_add(vertices=64, radius=1.35, fill_type="NGON", location=(0, 0, 0.01))
    ground = bpy.context.active_object
    ground.name = "GroundDisc"
    mat = bpy.data.materials.new(name="GroundMat")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.07, 0.075, 0.09, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.85
        if "Specular" in bsdf.inputs:
            bsdf.inputs["Specular"].default_value = 0.15
    ground.data.materials.append(mat)


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


def _resample_pose_vectors(pose_vectors: list, *, src_fps: float, out_fps: int) -> np.ndarray:
    src = np.asarray(pose_vectors, dtype=np.float64)
    if src.ndim != 2 or src.shape[0] < 2:
        raise RuntimeError("need >=2 pose vectors to resample")
    n_src = src.shape[0]
    duration_s = (n_src - 1) / float(src_fps)
    n_out = max(2, int(round(duration_s * float(out_fps))) + 1)
    t_src = np.linspace(0.0, 1.0, n_src)
    t_out = np.linspace(0.0, 1.0, n_out)
    out = np.empty((n_out, src.shape[1]), dtype=np.float64)
    for d in range(src.shape[1]):
        out[:, d] = np.interp(t_out, t_src, src[:, d])
    return out


def main() -> int:
    opts = _parse()
    job_path = opts["job"] if opts["job"].is_absolute() else ROOT / opts["job"]
    report_path = opts["report"] if opts["report"].is_absolute() else ROOT / opts["report"]
    job = json.loads(job_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    src_fps = float(
        opts["src_fps"]
        if opts["src_fps"] is not None
        else report.get("fps") or job.get("fps", 12)
    )
    out_fps = int(opts["out_fps"])
    out_dir = Path(job["outputDir"]) / "preview_lit_60fps"
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    _clear()
    bpy.ops.import_scene.gltf(filepath=str(Path(job["masterGlb"])))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next((o for o in bpy.data.objects if o.type == "MESH"), None)
    if mesh is None:
        raise RuntimeError("no mesh in master GLB")
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
        print(f"[lit60] weld-on-load removed {removed}", flush=True)
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

    _setup_lit_scene()
    # Place ground under bind feet (approximate from ankle bones if present).
    ground = bpy.data.objects.get("GroundDisc")
    if ground is not None:
        z_candidates = []
        for bname in ("RightFoot", "LeftFoot", "RightToeBase", "LeftToeBase"):
            if bname in arm.pose.bones:
                z_candidates.append(float((arm.matrix_world @ arm.pose.bones[bname].head).z))
        if z_candidates:
            ground.location.z = min(z_candidates) - 0.02

    cam = setup_pose_camera(job, arm, bpy_module=bpy)
    m = cam.matrix_world.to_3x3()
    cam_axes = (
        (m @ Vector((1.0, 0.0, 0.0))).normalized(),
        (m @ Vector((0.0, 1.0, 0.0))).normalized(),
        (m @ Vector((0.0, 0.0, -1.0))).normalized(),
    )

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 16
    scene.eevee.use_bloom = True
    scene.eevee.bloom_intensity = 0.05
    scene.render.resolution_x = int(opts["width"])
    scene.render.resolution_y = int(opts["height"])
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    scene.render.fps = out_fps

    resampled = _resample_pose_vectors(report["poseVectors"], src_fps=src_fps, out_fps=out_fps)
    print(
        f"[lit60] srcKeys={len(report['poseVectors'])}@{src_fps}fps -> "
        f"{len(resampled)} frames @{out_fps}fps",
        flush=True,
    )

    for i, vec in enumerate(resampled):
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
        render_path = frames_dir / f"frame_{i:04d}.png"
        scene.render.filepath = str(render_path)
        bpy.ops.render.render(write_still=True)
        if i % 10 == 0 or i + 1 == len(resampled):
            print(f"[lit60] rendered {i + 1}/{len(resampled)}", flush=True)

    meta = {
        "ok": True,
        "outDir": str(out_dir).replace("\\", "/"),
        "framesDir": str(frames_dir).replace("\\", "/"),
        "frameCount": int(len(resampled)),
        "srcFps": src_fps,
        "outFps": out_fps,
        "width": int(opts["width"]),
        "height": int(opts["height"]),
        "proof": (
            "generated artifact validated — lit EEVEE mesh preview with pose-vector "
            "resample to 60fps; not OE runtime proven"
        ),
    }
    (out_dir / "preview_lit_60fps_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(meta, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
