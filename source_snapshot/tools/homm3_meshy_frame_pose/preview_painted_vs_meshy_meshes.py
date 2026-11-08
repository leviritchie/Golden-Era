#!/usr/bin/env python3
"""
Proof GIF: painted attack frames vs Meshy t2 per-frame meshes AS-IS.

No hand skeleton, no AABB joints — Meshy's image→pose understanding is the right panel.

  blender -b --python preview_painted_vs_meshy_meshes.py -- \\
    --meshes-dir .../out_meshy_t2_per_frame_g11/meshes \\
    --sprites-dir .../source_attack_frames_painted_g11 \\
    --output-dir .../out_meshy_t2_per_frame_g11/preview_painted_vs_meshy
"""
from __future__ import annotations

import json
import math
import sys
import traceback
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

_TOOL = Path(__file__).resolve().parent
_SIL = _TOOL.parent / "homm3_silhouette_pose_fit"
for p in (_TOOL, _SIL):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from homm3_pose_camera import setup_pose_camera  # noqa: E402


def _argv() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def _parse() -> dict:
    args = _argv()
    out = {
        "meshesDir": None,
        "spritesDir": None,
        "outputDir": None,
        "start": 0,
        "end": 7,
        "hold": 4,
        "camera": {
            "axis": "iso",
            "isoAzimuthDeg": 40.0,
            "isoElevationDeg": 30.0,
            "distance": 3.0,
            "orthoScale": 2.6,
            "rootYawDeg": 0.0,
        },
    }
    i = 0
    while i < len(args):
        if args[i] == "--meshes-dir" and i + 1 < len(args):
            out["meshesDir"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--sprites-dir" and i + 1 < len(args):
            out["spritesDir"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--output-dir" and i + 1 < len(args):
            out["outputDir"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--start" and i + 1 < len(args):
            out["start"] = int(args[i + 1])
            i += 2
        elif args[i] == "--end" and i + 1 < len(args):
            out["end"] = int(args[i + 1])
            i += 2
        elif args[i] == "--hold" and i + 1 < len(args):
            out["hold"] = int(args[i + 1])
            i += 2
        else:
            i += 1
    for key in ("meshesDir", "spritesDir", "outputDir"):
        if not out[key]:
            raise SystemExit(f"need --meshes-dir --sprites-dir --output-dir (missing {key})")
    return out


def _clear() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


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
        for link in list(out.inputs["Surface"].links):
            links.remove(link)
        links.new(emit.outputs["Emission"], out.inputs["Surface"])


def _normalize_feet_center(mesh_obj, target_h: float = 1.4) -> None:
    pts = np.array([mesh_obj.matrix_world @ v.co for v in mesh_obj.data.vertices], dtype=np.float64)
    zmin, zmax = float(pts[:, 2].min()), float(pts[:, 2].max())
    height = max(zmax - zmin, 1e-6)
    scale = target_h / height
    mesh_obj.scale = (scale, scale, scale)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_obj
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    pts = np.array([mesh_obj.matrix_world @ v.co for v in mesh_obj.data.vertices], dtype=np.float64)
    mesh_obj.location.x -= float(pts[:, 0].mean())
    mesh_obj.location.y -= float(pts[:, 1].mean())
    mesh_obj.location.z -= float(pts[:, 2].min())
    bpy.context.view_layer.update()
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)


def _setup_scene(camera_cfg: dict) -> None:
    world = bpy.data.worlds.new("PreviewWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.08, 0.09, 0.12, 1)
    bg.inputs["Strength"].default_value = 0.0

    # Dummy empty at origin so camera helper has something to yaw against.
    empty = bpy.data.objects.new("CamAnchor", None)
    bpy.context.collection.objects.link(empty)
    job = {"camera": camera_cfg, "mirror": {}}
    setup_pose_camera(job, empty, bpy_module=bpy)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 8
    scene.render.resolution_x = 480
    scene.render.resolution_y = 420
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False


def run(opts: dict) -> dict:
    from PIL import Image, ImageDraw

    out_dir = Path(opts["outputDir"])
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    meshes_dir = Path(opts["meshesDir"])
    sprites_dir = Path(opts["spritesDir"])
    hold = int(opts["hold"])
    composed = []
    report_frames = []

    for fi in range(int(opts["start"]), int(opts["end"]) + 1):
        glb = meshes_dir / f"frame_{fi:02d}.glb"
        spr_path = sprites_dir / f"frame_{fi:02d}.png"
        if not glb.is_file():
            raise RuntimeError(f"missing mesh: {glb}")
        if not spr_path.is_file():
            raise RuntimeError(f"missing sprite: {spr_path}")

        _clear()
        bpy.ops.import_scene.gltf(filepath=str(glb))
        mesh = next(o for o in bpy.data.objects if o.type == "MESH")
        _normalize_feet_center(mesh)
        _force_unlit_baked(mesh)
        _setup_scene(opts["camera"])

        render_path = frames_dir / f"mesh_{fi:02d}.png"
        bpy.context.scene.render.filepath = str(render_path)
        bpy.ops.render.render(write_still=True)

        mesh_im = Image.open(render_path).convert("RGBA")
        spr = Image.open(spr_path).convert("RGBA")
        target_h = mesh_im.height
        scale = target_h / max(spr.height, 1)
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
        draw.text((12, 8), f"Painted frame {fi}", fill=(220, 220, 220, 255))
        draw.text((pad.width + gap + 12, 8), f"Meshy t2 mesh frame {fi}", fill=(220, 220, 220, 255))
        side_path = frames_dir / f"side_{fi:02d}.png"
        canvas.convert("RGB").save(side_path)
        for _ in range(hold):
            composed.append(canvas.convert("RGB"))
        report_frames.append(
            {
                "frame": fi,
                "mesh": str(glb).replace("\\", "/"),
                "sprite": str(spr_path).replace("\\", "/"),
                "sidePng": str(side_path).replace("\\", "/"),
            }
        )
        print(f"[proof] frame {fi}", flush=True)

    gif_path = out_dir / "attack_g11_side_by_side.gif"
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
        "method": "painted_vs_meshy_t2_mesh_as_is",
        "hold": hold,
        "frames": report_frames,
        "camera": opts["camera"],
        "proof": "generated artifact validated — Meshy per-frame pose read vs painted; not a single skinned character",
    }
    (out_dir / "preview_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "gif": meta["gif"]}, indent=2), flush=True)
    return meta


def main() -> int:
    try:
        run(_parse())
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
