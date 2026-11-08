#!/usr/bin/env python3
"""Write turntable stills for LLM/human part-map authorship. Requires Blender."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _inside_blender() -> bool:
    return "bpy" in sys.modules


def render(mesh: Path, out_dir: Path) -> dict:
    import bpy

    out_dir.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(mesh))
    mesh_obj = next(obj for obj in bpy.data.objects if obj.type == "MESH")
    bpy.ops.object.select_all(action="DESELECT")
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_obj
    cam_data = bpy.data.cameras.new("Turntable")
    cam = bpy.data.objects.new("Turntable", cam_data)
    bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    bpy.context.scene.render.resolution_x = 768
    bpy.context.scene.render.resolution_y = 768
    bpy.context.scene.render.film_transparent = True
    light_data = bpy.data.lights.new("Key", "SUN")
    light = bpy.data.objects.new("Key", light_data)
    light.rotation_euler = (0.6, 0.2, 0.3)
    bpy.context.collection.objects.link(light)
    radius = 3.2
    views = {
        "front": (0.0, -radius, 1.1),
        "side": (radius, 0.0, 1.1),
        "top": (0.0, 0.0, radius),
    }
    written = []
    for name, loc in views.items():
        cam.location = loc
        if name == "top":
            cam.rotation_euler = (0.0, 0.0, 0.0)
        else:
            cam.rotation_euler = (math.atan2(1.1, radius), 0.0, math.atan2(loc[0], -loc[1]) if name == "side" else 0.0)
        dest = out_dir / f"{name}.png"
        bpy.context.scene.render.filepath = str(dest)
        bpy.ops.render.render(write_still=True)
        written.append(str(dest))
    template = {
        "schema": "owned_bind_part_map.v1",
        "method": "human_eye_part_authoring",
        "unitSid": "h3_cavalier",
        "views": written,
        "seeds": [
            {"part": "horse", "point": [0.0, 0.0, 0.0]},
            {"part": "rider", "point": [0.0, 0.0, 0.0]},
            {"part": "lance", "point": [0.0, 0.0, 0.0]},
            {"part": "saddle_band", "point": [0.0, 0.0, 0.0]},
        ],
        "note": "Replace seed points with world-space mesh locations authored against the stills. Do not height-cut.",
    }
    authored = out_dir / "part_map_authored.template.json"
    authored.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    return {"views": written, "template": str(authored)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--blender", type=Path, default=Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe"))
    args = parser.parse_args()
    if _inside_blender():
        argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
        mesh = Path(argv[argv.index("--mesh") + 1])
        out_dir = Path(argv[argv.index("--out-dir") + 1])
        print(json.dumps(render(mesh, out_dir), indent=2))
        return 0
    blender = args.blender
    if not blender.is_file():
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from owned_rerig.glb_io import load_mesh
        from owned_rerig.preview import render_turntable_ppms

        mesh = load_mesh(args.mesh)
        written = render_turntable_ppms(mesh.positions, args.out_dir)
        print(json.dumps({"views": written, "renderer": "numpy_ortho_ppm"}, indent=2))
        return 0
    import subprocess

    cmd = [
        str(blender),
        "-b",
        "--python",
        str(Path(__file__).resolve()),
        "--",
        "--mesh",
        str(args.mesh.resolve()),
        "--out-dir",
        str(args.out_dir.resolve()),
    ]
    proc = subprocess.run(cmd, cwd=str(ROOT))
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
