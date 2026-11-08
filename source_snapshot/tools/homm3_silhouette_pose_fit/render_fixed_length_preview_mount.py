#!/usr/bin/env python3
"""Preview fixed-length mount IK (rider_mount rigs)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from PIL import Image, ImageDraw

TOOL = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL))
from blender_fixed_length_ik import (  # noqa: E402
    _apply_captured_pose,
    _apply_frame0_lateral_plant,
    _camera_up_world,
    _min_foot_world_z,
)
from blender_fixed_length_ik_mount import (  # noqa: E402
    _mount_foot_settings,
    _pose_frame_mount,
)
from blender_ground_truth_joints import (  # noqa: E402
    _bind_depths,
    _clear_pose,
    _disable_inherit_scale,
    _measure_errors,
    _project_px,
    _unproject_frame,
)
from homm3_landmark_sites import cache_tip_bind_local, landmark_world  # noqa: E402
from homm3_pose_camera import setup_pose_camera  # noqa: E402
from preview_timing import PREVIEW_GIF_FRAME_MS  # noqa: E402
from render_ground_truth_preview import _draw_sticks, _fit_sprite  # noqa: E402

W, H = 480, 420
MOUNT_EDGES = [
    ("Saddle", "RiderHelmet"),
    ("Saddle", "HorseNose"),
    ("RWrist", "LanceTip"),
    ("LWrist", "HorseNose"),
    ("LHoofFore", "RHoofFore"),
    ("LHoofHind", "RHoofHind"),
]


def _argv_after_sep() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit-dir", type=Path, required=True)
    args = ap.parse_args(_argv_after_sep())
    fit_dir = args.fit_dir.resolve()
    job = json.loads((fit_dir / "job.resolved.json").read_text(encoding="utf-8"))
    kpt = json.loads((fit_dir / "sprite_landmarks" / "keypoints.json").read_text(encoding="utf-8"))
    report_path = fit_dir / "fit_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    roles = json.loads(Path(job["boneRoles"]).read_text(encoding="utf-8"))
    pose_snaps = report.get("poseSnapshots")
    drive_from_poses = isinstance(pose_snaps, list) and len(pose_snaps) == len(kpt["frames"])

    out_dir = fit_dir / "preview" / "fixed_length"
    out_dir.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(job["masterGlb"])))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    for mod in mesh.modifiers:
        if mod.type == "ARMATURE":
            mod.use_deform_preserve_volume = True
    _disable_inherit_scale(arm)
    _clear_pose(arm)
    tip_cache = cache_tip_bind_local(arm, mesh, roles)

    world = bpy.data.worlds.new("W")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.08, 0.09, 0.12, 1)
    bg.inputs["Strength"].default_value = 0.4

    cam = setup_pose_camera(job, arm, bpy_module=bpy)
    if job.get("cameraFitPath"):
        from roc_chroma_match_worker import setup_camera  # noqa: E402

        fit_data = json.loads(Path(job["cameraFitPath"]).read_text(encoding="utf-8"))
        for obj in list(bpy.data.objects):
            if obj.type == "CAMERA":
                bpy.data.objects.remove(obj, do_unlink=True)
        cam, _right, _up, _fwd, _profile = setup_camera(
            fit_data,
            arm,
            [mesh],
            detect_profile=False,
            honor_fit_screen_offset=True,
            fit_coordinate_basis=str(job.get("fitCoordinateBasis") or "native"),
        )
        print(f"[fixed-preview-mount] camera from fit {job['cameraFitPath']}", flush=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 8
    scene.render.resolution_x = W
    scene.render.resolution_y = H
    scene.render.image_settings.file_format = "PNG"

    depths = _bind_depths(arm, roles, mesh=mesh, tip_cache=tip_cache)
    frames = sorted(kpt["frames"], key=lambda f: int(f["frameIndex"]))
    ga_mode, ga_bones = _mount_foot_settings(job.get("fixedLengthIk") or {})
    plant_state = None
    gif_frames = []
    for idx, fr in enumerate(frames):
        fi = int(fr["frameIndex"])
        sw = float(fr["transform"]["srcWidth"])
        sh = float(fr["transform"]["srcHeight"])
        if drive_from_poses:
            _apply_captured_pose(arm, pose_snaps[idx])
        else:
            _clear_pose(arm)
            bpy.context.view_layer.update()
            targets = _unproject_frame(scene, cam, fr["joints"], depths, sw, sh)
            _pose_frame_mount(
                arm,
                mesh,
                roles,
                targets,
                tip_cache,
                prefer_up=_camera_up_world(cam),
            )
        if ga_mode == "frame0_lateral_lowest_foot":
            if plant_state is None:
                plant_state = {
                    "groundZ": float(_min_foot_world_z(arm, ga_bones)),
                    "loc0xy": (float(arm.location.x), float(arm.location.y)),
                }
            else:
                _apply_frame0_lateral_plant(
                    arm,
                    ga_bones,
                    ground_z=float(plant_state["groundZ"]),
                    loc0_xy=tuple(plant_state["loc0xy"]),
                )
        bpy.context.view_layer.update()
        errs = _measure_errors(
            arm, scene, cam, fr["joints"], roles, sw, sh, mesh=mesh, tip_cache=tip_cache
        )

        raw = out_dir / f"mesh_{fi:02d}.png"
        scene.render.filepath = str(raw)
        bpy.ops.render.render(write_still=True)
        mesh_im = Image.open(raw).convert("RGB")

        proof_canvas, scale, (ox, oy) = _fit_sprite(Path(fr["path"]), (W, H))
        authored = {
            jn: (ox + float(spec["x"]) * scale, oy + float(spec["y"]) * scale)
            for jn, spec in fr["joints"].items()
        }
        driven_sprite = {}
        for jn in fr["joints"]:
            sx, sy = _project_px(
                scene,
                cam,
                landmark_world(arm, mesh, roles, jn, tip_cache=tip_cache),
                sw,
                sh,
            )
            driven_sprite[jn] = (ox + sx * scale, oy + sy * scale)
        proof_im = _draw_sticks(
            proof_canvas,
            authored,
            color=(80, 200, 255),
            label=(
                f"cyan=authored green=driven f{fi:02d} "
                f"nose={errs.get('HorseNose', 0):.0f} lance={errs.get('LanceTip', 0):.0f}"
            ),
        )
        d = ImageDraw.Draw(proof_im)
        for a, b in MOUNT_EDGES:
            if a in driven_sprite and b in driven_sprite:
                d.line([driven_sprite[a], driven_sprite[b]], fill=(0, 255, 80), width=2)
        for _n, (x, y) in driven_sprite.items():
            d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(0, 255, 80))

        mesh_sticks = _draw_sticks(
            mesh_im,
            {
                jn: _project_px(
                    scene,
                    cam,
                    landmark_world(arm, mesh, roles, jn, tip_cache=tip_cache),
                    float(W),
                    float(H),
                )
                for jn in fr["joints"]
            },
            color=(0, 255, 80),
            label=f"fixed-length mount mesh f{fi:02d}",
        )
        canvas = Image.new("RGB", (W * 2 + 8, H), (0, 0, 0))
        canvas.paste(proof_im, (0, 0))
        canvas.paste(mesh_sticks, (W + 8, 0))
        canvas.save(out_dir / f"side_{fi:02d}.png")
        gif_frames.append(canvas)
        print(
            f"[fixed-preview-mount] frame {fi} "
            f"nose={errs.get('HorseNose', 0):.1f} lance={errs.get('LanceTip', 0):.1f}",
            flush=True,
        )

    gif = out_dir / f"{job.get('clipId', 'clip')}_fixed_length_side_by_side.gif"
    gif_frames[0].save(
        gif,
        save_all=True,
        append_images=gif_frames[1:],
        duration=PREVIEW_GIF_FRAME_MS,
        loop=0,
        optimize=False,
    )
    print(json.dumps({"ok": True, "gif": str(gif).replace("\\", "/")}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
