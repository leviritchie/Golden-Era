#!/usr/bin/env python3
"""Render a unit's bind mesh on a yaw turntable under fixed light directions.

Purpose: a visual check of whether a single pre-baked light direction would make the
mesh read like the DEF sprite. The profile-camera initializer scores unlit albedo
chroma (Lab a,b) against a sprite that has HoMM3's studio lighting baked in, so this
sheet shows what each yaw looks like once lit, next to the real sprite plate.

Runs under Blender (CPU Cycles on purpose: the GPU cascade may be holding the only
CUDA context and this must not contend with it) and then composes a contact sheet
with Pillow from the host interpreter.

Usage (host):
    py -3 tools/homm3_silhouette_pose_fit/render_static_lighting_angles.py \
        --glb artifacts/meshy_downloads/h3_hobgoblin_smartrigged_rigidized.glb \
        --sprite artifacts/pose_picker_runs/h3_hobgoblin/idle_start_move_end/\
frames_def12_nn_idle_start_move_end_shadow_culled/00.png \
        --out artifacts/pose_picker_runs/h3_hobgoblin/lighting_angles

Proof tier: generated artifact (offline render). Nothing here changes a solve.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

BLENDER = os.environ.get("HOMM3_POSE_FIT_BLENDER", "V:/Tools/blender-3.5.1/blender.exe")

# Yaw is rotation about the world-up axis applied to the mesh, in degrees. 0 keeps the
# glTF import orientation; the sheet labels each column so the viewer maps them to the
# profile initializer's candidates by eye rather than by assuming a shared convention.
DEFAULT_YAWS = (-135, -105, -90, -45, 0, 45, 90, 135)

# Light directions relative to the camera, as (azimuth_deg, elevation_deg). Azimuth 0
# is straight from the camera; positive azimuth swings the light to the viewer's right.
DEFAULT_LIGHTS = {
    "front": (0.0, 20.0),
    "upper_left": (-50.0, 45.0),
    "upper_right": (50.0, 45.0),
    "top": (0.0, 80.0),
}


def _blender_side(argv: list[str]) -> None:
    import bpy  # type: ignore
    from mathutils import Euler, Vector  # type: ignore

    parser = argparse.ArgumentParser()
    parser.add_argument("--glb", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--yaws", required=True)
    parser.add_argument("--lights", required=True)
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--samples", type=int, default=24)
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    yaws = [float(v) for v in args.yaws.split(",")]
    lights: dict[str, tuple[float, float]] = json.loads(args.lights)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(args.glb).resolve()))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"no mesh objects imported from {args.glb}")

    # Parent every imported object under one pivot so yaw is a single rotation.
    pivot = bpy.data.objects.new("turntable_pivot", None)
    bpy.context.scene.collection.objects.link(pivot)
    roots = [obj for obj in bpy.context.scene.objects if obj.parent is None and obj is not pivot]
    for obj in roots:
        obj.parent = pivot

    bpy.context.view_layer.update()
    # Bounds from the evaluated (armature-deformed) geometry: object bound_box on a
    # skinned mesh reports the undeformed data and cropped heads/feet in practice.
    depsgraph = bpy.context.evaluated_depsgraph_get()
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for obj in meshes:
        evaluated = obj.evaluated_get(depsgraph)
        matrix = evaluated.matrix_world
        for vertex in evaluated.data.vertices:
            world = matrix @ vertex.co
            lo = Vector(min(a, b) for a, b in zip(lo, world))
            hi = Vector(max(a, b) for a, b in zip(hi, world))
    center = (lo + hi) * 0.5
    height = hi.z - lo.z
    if not math.isfinite(height) or height <= 0.0:
        raise RuntimeError("degenerate mesh bounds")
    # Rotate about the mesh's own vertical axis, not the armature origin.
    pivot.location = center
    bpy.context.view_layer.update()
    for obj in roots:
        obj.matrix_parent_inverse = pivot.matrix_world.inverted()
    bpy.context.view_layer.update()
    print(f"turntable bounds lo={tuple(round(v, 3) for v in lo)} hi={tuple(round(v, 3) for v in hi)} height={height:.3f}")

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = int(args.samples)
    scene.cycles.use_denoising = True
    scene.render.resolution_x = int(args.size)
    scene.render.resolution_y = int(args.size)
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"

    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = height * 1.25
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam_distance = height * 4.0
    cam.location = center + Vector((0.0, -cam_distance, 0.0))
    cam.rotation_euler = Euler((math.radians(90.0), 0.0, 0.0), "XYZ")

    sun_data = bpy.data.lights.new("sun", "SUN")
    sun_data.energy = 3.0
    sun_data.angle = math.radians(5.0)
    sun = bpy.data.objects.new("sun", sun_data)
    scene.collection.objects.link(sun)
    # A dim uniform fill so unlit sides are dark grey rather than black; the sprite
    # itself has visible detail in shadow.
    world = bpy.data.worlds.new("world")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
    bg.inputs[1].default_value = 0.15

    manifest: list[dict[str, object]] = []
    for light_name, (azimuth_deg, elevation_deg) in lights.items():
        # Camera looks along +Y. Build the light direction in camera-relative terms and
        # point the sun *from* that direction toward the subject.
        az = math.radians(azimuth_deg)
        el = math.radians(elevation_deg)
        from_dir = Vector(
            (math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el))
        )
        sun.rotation_euler = (-from_dir).to_track_quat("-Z", "Y").to_euler()
        for yaw in yaws:
            pivot.rotation_euler = Euler((0.0, 0.0, math.radians(yaw)), "XYZ")
            name = f"{light_name}_yaw{int(yaw):+04d}.png"
            scene.render.filepath = str(out / name)
            bpy.ops.render.render(write_still=True)
            manifest.append(
                {
                    "file": name,
                    "light": light_name,
                    "lightAzimuthDeg": azimuth_deg,
                    "lightElevationDeg": elevation_deg,
                    "yawDeg": yaw,
                }
            )
    (out / "renders.json").write_text(
        json.dumps(
            {
                "proof": "generated-artifact",
                "glb": str(Path(args.glb).resolve()),
                "camera": "orthographic, horizontal, screen-up = world-up",
                "engine": "cycles-cpu",
                "renders": manifest,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _compose_sheet(out: Path, sprite: Path | None, size: int) -> Path:
    from PIL import Image, ImageDraw

    manifest = json.loads((out / "renders.json").read_text(encoding="utf-8"))
    renders = manifest["renders"]
    lights = list(dict.fromkeys(r["light"] for r in renders))
    yaws = list(dict.fromkeys(r["yawDeg"] for r in renders))
    label_h = 18
    cols = len(yaws) + (1 if sprite is not None else 0)
    rows = len(lights)
    sheet = Image.new("RGB", (cols * size, rows * (size + label_h)), (40, 40, 40))
    draw = ImageDraw.Draw(sheet)

    def fit(img: Image.Image) -> Image.Image:
        img = img.convert("RGBA")
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
        scale = min((size - 8) / max(1, img.width), (size - 8) / max(1, img.height))
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
        tile = Image.new("RGBA", (size, size), (40, 40, 40, 255))
        tile.alpha_composite(img, ((size - img.width) // 2, (size - img.height) // 2))
        return tile.convert("RGB")

    for row, light in enumerate(lights):
        y0 = row * (size + label_h)
        col = 0
        if sprite is not None:
            sheet.paste(fit(Image.open(sprite)), (0, y0 + label_h))
            draw.text((4, y0 + 2), "sprite f0 (DEF lighting)", fill=(255, 255, 255))
            col = 1
        for yaw in yaws:
            entry = next(r for r in renders if r["light"] == light and r["yawDeg"] == yaw)
            sheet.paste(fit(Image.open(out / entry["file"])), (col * size, y0 + label_h))
            draw.text(
                (col * size + 4, y0 + 2),
                f"{light} az{entry['lightAzimuthDeg']:+.0f} el{entry['lightElevationDeg']:.0f} | yaw {yaw:+.0f}",
                fill=(255, 255, 255),
            )
            col += 1
    sheet_path = out / "lighting_angles_sheet.png"
    sheet.save(sheet_path)
    return sheet_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--glb", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--sprite", default=None, help="Sprite PNG shown in the first column.")
    parser.add_argument("--yaws", default=",".join(str(v) for v in DEFAULT_YAWS))
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--samples", type=int, default=24)
    args = parser.parse_args()

    out = Path(args.out)
    blender = Path(BLENDER)
    if not blender.is_file():
        raise FileNotFoundError(blender)
    command = [
        str(blender),
        "-b",
        "--python",
        str(Path(__file__).resolve()),
        "--",
        "--glb",
        str(Path(args.glb).resolve()),
        "--out",
        str(out.resolve()),
        f"--yaws={args.yaws}",
        "--lights",
        json.dumps(DEFAULT_LIGHTS),
        "--size",
        str(args.size),
        "--samples",
        str(args.samples),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, timeout=1800)
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout[-3000:] + completed.stderr[-3000:])
        raise SystemExit(f"blender render failed with exit {completed.returncode}")
    sheet = _compose_sheet(out, Path(args.sprite) if args.sprite else None, int(args.size))
    print(sheet)
    return 0


def _inside_blender() -> bool:
    try:
        import bpy  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


if __name__ == "__main__":
    if _inside_blender():
        _blender_side(sys.argv[sys.argv.index("--") + 1 :])
    else:
        raise SystemExit(main())
