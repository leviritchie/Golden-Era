#!/usr/bin/env python3
"""Diagnose Meshy28 bind pose vs frame_00 under isometric + legacy cameras."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
from PIL import Image, ImageDraw

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = Path(__file__).resolve().parent
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))
from homm3_pose_camera import setup_pose_camera  # noqa: E402

OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_meshy28_bind_diag"
MASTER = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/master/Meshy_AI_Character_output_2.glb"
SPRITE = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/source_attack_frames/canonical_group_11/frame_00.png"


def _force_unlit(mesh) -> None:
    for mat in mesh.data.materials:
        if mat is None or not mat.use_nodes:
            continue
        nt = mat.node_tree
        nodes = nt.nodes
        links = nt.links
        outn = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
        bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
        if outn is None or bsdf is None:
            continue
        base = bsdf.inputs.get("Base Color")
        emit = nodes.new("ShaderNodeEmission")
        emit.inputs["Strength"].default_value = 1.0
        if base is not None and base.is_linked:
            links.new(base.links[0].from_socket, emit.inputs["Color"])
        elif base is not None:
            emit.inputs["Color"].default_value = tuple(base.default_value)
        for link in list(outn.inputs["Surface"].links):
            links.remove(link)
        links.new(emit.outputs["Emission"], outn.inputs["Surface"])


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(MASTER))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    if arm.animation_data:
        arm.animation_data_clear()
    _force_unlit(mesh)

    world = bpy.data.worlds.new("W")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.08, 0.09, 0.12, 1)
    bg.inputs["Strength"].default_value = 0.0

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 8
    scene.render.resolution_x = 480
    scene.render.resolution_y = 420
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False

    variants = [
        ("bind_iso40_el30", "iso", 40.0, 30.0),
        ("bind_iso35_el28", "iso", 35.0, 28.0),
        ("bind_iso45_el32", "iso", 45.0, 32.0),
        ("bind_cam-Y_yaw0", "-Y", 0.0, 0.0),
        ("bind_cam-X_yaw0", "-X", 0.0, 0.0),
    ]
    rendered = []
    for name, axis, a, e in variants:
        for o in list(bpy.data.objects):
            if o.type == "CAMERA":
                bpy.data.objects.remove(o, do_unlink=True)
        job = {
            "camera": {
                "axis": axis,
                "isoAzimuthDeg": a,
                "isoElevationDeg": e,
                "distance": 3.0,
                "orthoScale": 2.6,
                "rootYawDeg": 0.0,
            },
            "mirror": {},
        }
        setup_pose_camera(job, arm, bpy_module=bpy)
        fp = OUT / f"{name}.png"
        scene.render.filepath = str(fp)
        bpy.ops.render.render(write_still=True)
        rendered.append((name, fp))
        print(f"WROTE {name}", flush=True)

    spr = Image.open(SPRITE).convert("RGBA")
    scale = max(1, 300 // max(spr.size))
    spr_big = spr.resize((spr.width * scale, spr.height * scale), Image.Resampling.NEAREST)

    cols = [spr_big.convert("RGB")]
    labels = ["sprite f0"]
    for name, fp in rendered:
        cols.append(Image.open(fp).convert("RGB"))
        labels.append(name.replace("bind_", ""))

    h = max(c.height for c in cols)
    pad = 8
    strip = Image.new("RGB", (sum(c.width for c in cols) + pad * (len(cols) + 1), h + 40), (20, 20, 24))
    draw = ImageDraw.Draw(strip)
    x = pad
    for lab, c in zip(labels, cols):
        y = 40 + (h - c.height) // 2
        strip.paste(c, (x, y))
        draw.text((x + 4, 8), lab, fill=(220, 220, 220))
        x += c.width + pad
    strip_path = OUT / "bind_iso_sweep_vs_sprite.png"
    strip.save(strip_path)
    print(json.dumps({"ok": True, "strip": str(strip_path).replace("\\", "/")}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
