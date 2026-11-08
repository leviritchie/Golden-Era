#!/usr/bin/env python3
"""Preview ground-truth joint drive vs authored sprite sticks.

Left: sprite + authored landmarks
Right: fitted mesh + projected driven landmarks (must coincide with authored)

Blender:
  blender -b --python render_ground_truth_preview.py -- --fit-dir <out_fit/g00_move_ground_truth>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from PIL import Image, ImageDraw

TOOL = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL))
from blender_ground_truth_joints import (  # noqa: E402
    _apply_targets,
    _bind_depths,
    _clear_pose,
    _disable_inherit_scale,
    _landmark_world,
    _measure_errors,
    _project_px,
    _unproject_frame,
)
from homm3_pose_camera import setup_pose_camera  # noqa: E402

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
W = 480
H = 420

EDGES = [
    ("Nose", "Neck"),
    ("Neck", "RShoulder"),
    ("RShoulder", "RElbow"),
    ("RElbow", "RWrist"),
    ("RWrist", "WeaponTip"),
    ("Neck", "LShoulder"),
    ("LShoulder", "LElbow"),
    ("LElbow", "LWrist"),
    ("Neck", "MidHip"),
    ("MidHip", "RHip"),
    ("RHip", "RKnee"),
    ("RKnee", "RAnkle"),
    ("MidHip", "LHip"),
    ("LHip", "LKnee"),
    ("LKnee", "LAnkle"),
]


def _argv_after_sep() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _draw_sticks(im: Image.Image, joints_xy: dict[str, tuple[float, float]], *, color, label: str) -> Image.Image:
    out = im.convert("RGB")
    d = ImageDraw.Draw(out)
    for a, b in EDGES:
        if a not in joints_xy or b not in joints_xy:
            continue
        d.line([joints_xy[a], joints_xy[b]], fill=(0, 0, 0), width=5)
        d.line([joints_xy[a], joints_xy[b]], fill=color, width=3)
    for _n, (x, y) in joints_xy.items():
        r = 4
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 40, 255))
    d.text((8, 8), label, fill=(255, 255, 0))
    return out


def _fit_sprite(path: Path, size: tuple[int, int]) -> Image.Image:
    sp = Image.open(path).convert("RGBA")
    canvas = Image.new("RGBA", size, (20, 22, 28, 255))
    scale = min(size[0] / sp.width, size[1] / sp.height) * 0.92
    nw, nh = max(1, int(sp.width * scale)), max(1, int(sp.height * scale))
    sp2 = sp.resize((nw, nh), Image.Resampling.NEAREST)
    canvas.paste(sp2, ((size[0] - nw) // 2, (size[1] - nh) // 2), sp2)
    return canvas.convert("RGB"), scale, ((size[0] - nw) // 2, (size[1] - nh) // 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit-dir", type=Path, required=True)
    args = ap.parse_args(_argv_after_sep())
    fit_dir = args.fit_dir.resolve()
    job = json.loads((fit_dir / "job.resolved.json").read_text(encoding="utf-8"))
    kpt = json.loads((fit_dir / "sprite_landmarks" / "keypoints.json").read_text(encoding="utf-8"))
    roles = json.loads(Path(job["boneRoles"]).read_text(encoding="utf-8"))
    report = json.loads((fit_dir / "fit_report.json").read_text(encoding="utf-8"))

    out_dir = fit_dir / "preview" / "ground_truth"
    out_dir.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(job["masterGlb"])))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    _disable_inherit_scale(arm)
    _clear_pose(arm)

    world = bpy.data.worlds.new("W")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.08, 0.09, 0.12, 1)
    bg.inputs["Strength"].default_value = 0.4

    cam = setup_pose_camera(job, arm, bpy_module=bpy)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 8
    scene.render.resolution_x = W
    scene.render.resolution_y = H
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False

    # Match GT camera ortho from fit report / job after register.
    depths = _bind_depths(arm, roles)

    frames = sorted(kpt["frames"], key=lambda f: int(f["frameIndex"]))
    gif_frames = []
    for fr in frames:
        fi = int(fr["frameIndex"])
        sw = float(fr["transform"]["srcWidth"])
        sh = float(fr["transform"]["srcHeight"])
        _clear_pose(arm)
        bpy.context.view_layer.update()
        targets = _unproject_frame(scene, cam, fr["joints"], depths, sw, sh)
        _apply_targets(arm, targets)
        bpy.context.view_layer.update()

        errs = _measure_errors(arm, scene, cam, fr["joints"], roles, sw, sh)
        worst = max(errs.values())
        if worst > float(report.get("maxErrorPxLimit", 2.0)):
            raise SystemExit(f"preview fail-closed frame {fi} maxErr={worst}")

        raw = out_dir / f"mesh_{fi:02d}.png"
        scene.render.filepath = str(raw)
        bpy.ops.render.render(write_still=True)
        mesh_im = Image.open(raw).convert("RGB")

        # Proof panel: authored + driven in the SAME sprite pixel space (must overlap).
        proof = Image.open(Path(fr["path"])).convert("RGB")
        # letterbox to W×H for gif uniformity
        proof_canvas, scale, (ox, oy) = _fit_sprite(Path(fr["path"]), (W, H))
        authored = {}
        driven_sprite = {}
        for jn, spec in fr["joints"].items():
            authored[jn] = (ox + float(spec["x"]) * scale, oy + float(spec["y"]) * scale)
            wpt = _landmark_world(arm, jn, roles)
            # Project into original sprite pixel space, then into letterbox.
            sx, sy = _project_px(scene, cam, wpt, sw, sh)
            driven_sprite[jn] = (ox + sx * scale, oy + sy * scale)
        proof_im = _draw_sticks(
            proof_canvas,
            authored,
            color=(80, 200, 255),
            label=f"cyan=authored green=driven f{fi:02d} maxErr={worst:.3f}px",
        )
        # draw driven on top in green
        d = ImageDraw.Draw(proof_im)
        for a, b in EDGES:
            if a not in driven_sprite or b not in driven_sprite:
                continue
            d.line([driven_sprite[a], driven_sprite[b]], fill=(0, 255, 80), width=2)
        for _n, (x, y) in driven_sprite.items():
            r = 3
            d.ellipse([x - r, y - r, x + r, y + r], fill=(0, 255, 80))

        mesh_sticks = _draw_sticks(
            mesh_im,
            {
                jn: _project_px(scene, cam, _landmark_world(arm, jn, roles), float(W), float(H))
                for jn in fr["joints"]
            },
            color=(0, 255, 80),
            label=f"mesh + driven joints f{fi:02d}",
        )

        canvas = Image.new("RGB", (W * 2 + 8, H), (0, 0, 0))
        canvas.paste(proof_im, (0, 0))
        canvas.paste(mesh_sticks, (W + 8, 0))
        out_frame = out_dir / f"side_{fi:02d}.png"
        canvas.save(out_frame)
        gif_frames.append(canvas)
        print(f"[gt-preview] frame {fi} maxErrPx={worst:.4f}", flush=True)

    gif = out_dir / f"{job.get('clipId', 'clip')}_ground_truth_side_by_side.gif"
    gif_frames[0].save(
        gif,
        save_all=True,
        append_images=gif_frames[1:],
        duration=180,
        loop=0,
        optimize=False,
    )
    print(json.dumps({"ok": True, "gif": str(gif).replace('\\', '/')}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
