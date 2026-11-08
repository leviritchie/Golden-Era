#!/usr/bin/env python3
"""
Render fitted poses onto the exact sprite pixel grid (same camera, same WxH).

Used for absolute chroma/pixel success checks. Side-by-side GIF framing is not authority.

Blender:
  blender -b --python render_absolute_match_frames.py -- --job job.json --report fit_report.json
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
from PIL import Image

_TOOL_DIR = Path(__file__).resolve().parent
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))
from absolute_chroma_match import compare_absolute  # noqa: E402
from homm3_pose_camera import setup_pose_camera  # noqa: E402


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _parse() -> dict:
    args = _argv()
    out = {"job": None, "report": None}
    i = 0
    while i < len(args):
        if args[i] == "--job" and i + 1 < len(args):
            out["job"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--report" and i + 1 < len(args):
            out["report"] = Path(args[i + 1])
            i += 2
        else:
            i += 1
    if not out["job"] or not out["report"]:
        raise SystemExit("need --job and --report")
    return out


def _apply_deltas(arm, rest, names, vec, *, root_rest, cam_axes, root_translate: bool) -> None:
    n_rot = len(names) * 3
    for i, name in enumerate(names):
        pb = arm.pose.bones[name]
        pb.rotation_mode = "XYZ"
        base = rest[name]
        dx, dy, dz = float(vec[i * 3]), float(vec[i * 3 + 1]), float(vec[i * 3 + 2])
        pb.rotation_euler = Euler((base.x + dx, base.y + dy, base.z + dz), "XYZ")
    if root_translate:
        right, up, forward = cam_axes
        tr, tu, tf = float(vec[n_rot]), float(vec[n_rot + 1]), float(vec[n_rot + 2])
        arm.location = root_rest + right * tr + up * tu + forward * tf
    else:
        arm.location = Vector(root_rest)


def _force_unlit_baked(mesh_obj) -> None:
    for mat in mesh_obj.data.materials:
        if mat is None or not mat.use_nodes:
            continue
        nt = mat.node_tree
        nodes = nt.nodes
        links = nt.links
        out = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
        bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
        if out is None or bsdf is None:
            continue
        base_in = bsdf.inputs.get("Base Color")
        emit = nodes.new(type="ShaderNodeEmission")
        emit.location = (bsdf.location.x + 200.0, bsdf.location.y)
        emit.inputs["Strength"].default_value = 1.0
        if base_in is not None and base_in.is_linked:
            links.new(base_in.links[0].from_socket, emit.inputs["Color"])
        elif base_in is not None:
            emit.inputs["Color"].default_value = tuple(base_in.default_value)
        links.new(emit.outputs["Emission"], out.inputs["Surface"])


def run(job_path: Path, report_path: Path) -> dict:
    job = json.loads(job_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    out_dir = Path(job["outputDir"]) / "absolute_match"
    frames_dir = out_dir / "mesh_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    match_cfg = job.get("absoluteMatch") or {}
    palette_normalize = bool(match_cfg.get("paletteNormalize", True))
    alpha_thr = float(match_cfg.get("alphaThr", 8.0))
    max_chroma = match_cfg.get("failClosedMaxChromaMae")
    max_rgb = match_cfg.get("failClosedMaxRgbMae")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=job["masterGlb"])
    arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("no mesh after import")
    import bmesh

    for mesh in meshes:
        bm = bmesh.new()
        bm.from_mesh(mesh.data)
        before = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-4)
        removed = before - len(bm.verts)
        bm.to_mesh(mesh.data)
        bm.free()
        mesh.data.update()
        if removed:
            print(f"[abs-match] weld-on-load removed {removed} duplicate verts", flush=True)
        _force_unlit_baked(mesh)

    names = list(report["optimizeBones"])
    rest = {}
    for name in names:
        pb = arm.pose.bones[name]
        pb.rotation_mode = "XYZ"
        rest[name] = pb.rotation_euler.copy()
    root_rest = arm.location.copy()
    root_translate = bool(report.get("rootTranslate", False))
    cam = setup_pose_camera(job, arm, bpy_module=bpy)
    m = cam.matrix_world.to_3x3()
    cam_axes = (
        (m @ Vector((1.0, 0.0, 0.0))).normalized(),
        (m @ Vector((0.0, 1.0, 0.0))).normalized(),
        (m @ Vector((0.0, 0.0, -1.0))).normalized(),
    )

    world = bpy.data.worlds.new("AbsMatchWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1)
    bg.inputs["Strength"].default_value = 0.0

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 8
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = True

    pose_vectors = report["poseVectors"]
    frame_reports = []
    errors = []

    for i, vec in enumerate(pose_vectors):
        sprite_path = Path(job["frames"][i]["path"])
        spr = Image.open(sprite_path).convert("RGBA")
        sw, sh = spr.size
        scene.render.resolution_x = int(sw)
        scene.render.resolution_y = int(sh)
        scene.render.resolution_percentage = 100

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
        mesh_path = frames_dir / f"mesh_{i:02d}.png"
        scene.render.filepath = str(mesh_path)
        bpy.ops.render.render(write_still=True)

        # Ensure exact grid size (Blender can pad).
        mesh_im = Image.open(mesh_path).convert("RGBA")
        if mesh_im.size != (sw, sh):
            canvas = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
            canvas.paste(mesh_im.resize((sw, sh), Image.Resampling.BILINEAR), (0, 0))
            mesh_im = canvas
            mesh_im.save(mesh_path)

        cmp = compare_absolute(
            np.asarray(spr, dtype=np.float32),
            np.asarray(mesh_im, dtype=np.float32),
            alpha_thr=alpha_thr,
            palette_normalize=palette_normalize,
        )
        fr = {
            "frameIndex": i,
            "sprite": str(sprite_path).replace("\\", "/"),
            "mesh": str(mesh_path).replace("\\", "/"),
            **cmp,
        }
        frame_reports.append(fr)
        print(
            f"[abs-match] frame {i} rgbMae={cmp['rgbMae']:.2f} chromaMae={cmp['chromaMae']:.2f} "
            f"pixels={cmp['pixelCount']}",
            flush=True,
        )
        if max_chroma is not None and cmp["chromaMae"] > float(max_chroma):
            errors.append(
                f"frame {i} chromaMae {cmp['chromaMae']:.3f} > failClosedMaxChromaMae={max_chroma}"
            )
        if max_rgb is not None and cmp["rgbMae"] > float(max_rgb):
            errors.append(
                f"frame {i} rgbMae {cmp['rgbMae']:.3f} > failClosedMaxRgbMae={max_rgb}"
            )

    summary = {
        "ok": len(errors) == 0,
        "errors": errors,
        "paletteNormalize": palette_normalize,
        "alphaThr": alpha_thr,
        "failClosedMaxChromaMae": max_chroma,
        "failClosedMaxRgbMae": max_rgb,
        "meanRgbMae": float(np.mean([f["rgbMae"] for f in frame_reports])) if frame_reports else None,
        "meanChromaMae": float(np.mean([f["chromaMae"] for f in frame_reports])) if frame_reports else None,
        "frames": frame_reports,
        "proof": (
            "generated artifact validated — absolute chroma/pixel match on sprite grid; "
            "joints are not the success metric; not OE runtime proven"
        ),
    }
    out_json = out_dir / "absolute_match_report.json"
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": summary["ok"], "report": str(out_json), "errors": errors}, indent=2), flush=True)
    if errors:
        raise RuntimeError(
            "fail-closed: absolute chroma/pixel match failed: "
            + "; ".join(errors)
            + ". Fix pose/camera/mesh — do not treat joint loss as success."
        )
    return summary


def main() -> int:
    try:
        opts = _parse()
        run(opts["job"], opts["report"])
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
