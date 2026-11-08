#!/usr/bin/env python3
"""Render fitted fixed-length poses as transparent DEF-sized billboard PNGs.

Blender:
  blender -b --python render_fitted_def_billboard_frames.py -- \\
    --fit-dir artifacts/.../g00_move_fixed_length \\
    --out-dir artifacts/.../def_billboard_frames/g00 \\
    --frame-count 40 --width 450 --height 400
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

TOOL = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL))
from blender_fixed_length_ik import (  # noqa: E402
    _apply_captured_pose,
)
from blender_ground_truth_joints import (  # noqa: E402
    _clear_pose,
    _disable_inherit_scale,
)
from homm3_landmark_sites import cache_tip_bind_local  # noqa: E402
from homm3_pose_camera import setup_pose_camera  # noqa: E402
from render_fixed_length_lit_60fps import (  # noqa: E402
    _lerp_pose,
    _plant_after_pose,
)
from render_mesh_lit_60fps import _setup_lit_scene  # noqa: E402


def _argv_after_sep() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--frame-count", type=int, required=True)
    ap.add_argument("--width", type=int, default=450)
    ap.add_argument("--height", type=int, default=400)
    ap.add_argument("--pose-start", type=int, default=0)
    ap.add_argument("--pose-end", type=int, default=-1, help="Exclusive; -1 = all")
    ap.add_argument(
        "--loopable",
        action="store_true",
        default=True,
        help="Wrap last→first when sampling (walk/idle).",
    )
    ap.add_argument("--no-loopable", action="store_false", dest="loopable")
    ap.add_argument(
        "--name-prefix",
        type=str,
        default="",
        help="Optional filename prefix like '00_' (names become 00_0000.png).",
    )
    ap.add_argument(
        "--name-width",
        type=int,
        default=4,
        help="Zero-pad width for frame index in filename.",
    )
    args = ap.parse_args(_argv_after_sep())

    fit_dir = args.fit_dir.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()

    job = json.loads((fit_dir / "job.resolved.json").read_text(encoding="utf-8"))
    report = json.loads((fit_dir / "fit_report.json").read_text(encoding="utf-8"))
    roles = json.loads(Path(job["boneRoles"]).read_text(encoding="utf-8"))
    pose_snaps = report.get("poseSnapshots")
    if not isinstance(pose_snaps, list) or len(pose_snaps) < 1:
        raise RuntimeError(f"{fit_dir}: fit_report.json missing poseSnapshots")

    start = max(0, int(args.pose_start))
    end = len(pose_snaps) if int(args.pose_end) < 0 else min(len(pose_snaps), int(args.pose_end))
    if end <= start:
        raise RuntimeError(f"empty pose slice [{start}:{end}] from {len(pose_snaps)} poses")
    pose_snaps = pose_snaps[start:end]
    n_src = len(pose_snaps)
    n_out = int(args.frame_count)
    if n_out < 1:
        raise RuntimeError("frame-count must be >= 1")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(job["masterGlb"])))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    if arm.animation_data:
        arm.animation_data_clear()
    _disable_inherit_scale(arm)
    _clear_pose(arm)
    tip_cache = cache_tip_bind_local(arm, mesh, roles)

    _setup_lit_scene()
    # Billboard frames must be mesh-only on transparent alpha (no ground disc).
    ground = bpy.data.objects.get("GroundDisc")
    if ground is not None:
        bpy.data.objects.remove(ground, do_unlink=True)
    cam = setup_pose_camera(job, arm, bpy_module=bpy)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 24
    scene.render.resolution_x = int(args.width)
    scene.render.resolution_y = int(args.height)
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = True

    # Seed plant from first pose.
    _apply_captured_pose(arm, pose_snaps[0])
    plant_state = _plant_after_pose(arm, job, None)

    rendered: list[str] = []
    for oi in range(n_out):
        if n_src == 1:
            pose = pose_snaps[0]
        elif args.loopable:
            u = (oi / float(n_out)) * float(n_src)
            i0 = int(u) % n_src
            i1 = (i0 + 1) % n_src
            t = u - int(u)
            pose = pose_snaps[i0] if i0 == i1 else _lerp_pose(pose_snaps[i0], pose_snaps[i1], t)
        else:
            u = oi / float(max(1, n_out - 1)) * float(max(0, n_src - 1))
            i0 = int(u)
            i1 = min(i0 + 1, n_src - 1)
            t = u - i0
            pose = pose_snaps[i0] if i0 == i1 else _lerp_pose(pose_snaps[i0], pose_snaps[i1], t)
        _apply_captured_pose(arm, pose)
        plant_state = _plant_after_pose(arm, job, plant_state)
        bpy.context.view_layer.update()

        name = f"{args.name_prefix}{oi:0{int(args.name_width)}d}.png"
        path = out_dir / name
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        rendered.append(str(path).replace("\\", "/"))
        if oi == 0 or oi == n_out - 1 or (oi + 1) % 10 == 0:
            print(f"[def-billboard] render {oi + 1}/{n_out} -> {name}", flush=True)

    meta = {
        "fitDir": str(fit_dir).replace("\\", "/"),
        "outDir": str(out_dir).replace("\\", "/"),
        "poseStart": start,
        "poseEnd": end,
        "sourcePoseCount": n_src,
        "frameCount": n_out,
        "width": int(args.width),
        "height": int(args.height),
        "loopable": bool(args.loopable),
        "frames": rendered,
        "proof": "generated-artifact; not OE runtime until bundled+deployed",
    }
    (out_dir / "render_manifest.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"ok": True, "n": n_out, "out": str(out_dir).replace("\\", "/")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
