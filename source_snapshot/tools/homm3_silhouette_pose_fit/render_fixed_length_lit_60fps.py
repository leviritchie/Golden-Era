#!/usr/bin/env python3
"""Lit 60fps mesh-only preview for fixed-length IK (no skeleton).

For each output frame: lerp unprojected landmark targets between source poses,
re-run rotate-only IK, render. Playback wall-clock matches stick-GIF default
(``PREVIEW_GIF_FRAME_MS`` per source frame), not job ``fps``.

Blender:
  blender -b --python render_fixed_length_lit_60fps.py -- \\
    --fit-dir artifacts/.../out_fit/g00_move_fixed_length
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import bpy
from mathutils import Vector

TOOL = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL))
from blender_fixed_length_ik import (  # noqa: E402
    _apply_captured_pose,
    _apply_frame0_lateral_plant,
    _camera_forward_world,
    _camera_up_world,
    _ground_anchor_settings,
    _min_foot_world_z,
    _pose_frame,
)
from blender_ground_truth_joints import (  # noqa: E402
    _bind_depths,
    _clear_pose,
    _disable_inherit_scale,
    _unproject_frame,
)
from homm3_landmark_sites import cache_tip_bind_local  # noqa: E402
from homm3_pose_camera import setup_pose_camera  # noqa: E402
from preview_timing import (  # noqa: E402
    PREVIEW_GIF_FRAME_MS,
    cycle_duration_s,
    interpolated_frame_count,
)
from render_mesh_lit_60fps import _setup_lit_scene  # noqa: E402


def _find_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    winget = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    if winget.is_dir():
        hits = sorted(winget.glob("*/ffmpeg*/bin/ffmpeg.exe"))
        if hits:
            return str(hits[-1])
    return None


def _encode_previews(
    frames_dir: Path,
    out_dir: Path,
    clip_id: str,
    out_fps: int,
    preview_loops: int,
    gif_fps: float,
) -> dict[str, str]:
    """Encode single-cycle mp4, looped review mp4, and infinite-loop GIF.

    ``gif_fps`` must preserve wall-clock vs stick GIF (typically 1000/180 ≈ 5.56).
    """
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH or WinGet Packages")

    single = out_dir / f"{clip_id}_lit_60fps.mp4"
    looped = out_dir / f"{clip_id}_lit_60fps_loop{preview_loops}x.mp4"
    gif = out_dir / f"{clip_id}_lit_loop.gif"
    pattern = str(frames_dir / "mesh_%04d.png")

    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-framerate",
            str(out_fps),
            "-i",
            pattern,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
            str(single),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    loops = max(1, int(preview_loops))
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-stream_loop",
            str(loops - 1),
            "-i",
            str(single),
            "-c",
            "copy",
            str(looped),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    # GIF: same wall-clock as stick preview (frame delay ≈ PREVIEW_GIF_FRAME_MS).
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-framerate",
            str(out_fps),
            "-i",
            pattern,
            "-vf",
            f"fps={gif_fps:.6f},scale=480:-1:flags=lanczos,split[s0][s1];"
            "[s0]palettegen=max_colors=128[p];[s1][p]paletteuse",
            "-loop",
            "0",
            str(gif),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    return {
        "mp4": str(single).replace("\\", "/"),
        "mp4Looped": str(looped).replace("\\", "/"),
        "gif": str(gif).replace("\\", "/"),
    }

def _argv_after_sep() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _reset_bones(arm) -> None:
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    arm.location = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()


def _lerp_targets(a: dict[str, Vector], b: dict[str, Vector], t: float) -> dict[str, Vector]:
    out = {}
    for k in a:
        out[k] = a[k] * (1.0 - t) + b[k] * t
    return out


def _lerp_pose(a: dict, b: dict, t: float) -> dict:
    loc_a = a["location"]
    loc_b = b["location"]
    loc = [
        float(loc_a[0]) * (1.0 - t) + float(loc_b[0]) * t,
        float(loc_a[1]) * (1.0 - t) + float(loc_b[1]) * t,
        float(loc_a[2]) * (1.0 - t) + float(loc_b[2]) * t,
    ]
    names = set(a["eulers"]) | set(b["eulers"])
    eulers = {}
    for name in names:
        ea = a["eulers"].get(name) or [0.0, 0.0, 0.0]
        eb = b["eulers"].get(name) or [0.0, 0.0, 0.0]
        eulers[name] = [
            float(ea[0]) * (1.0 - t) + float(eb[0]) * t,
            float(ea[1]) * (1.0 - t) + float(eb[1]) * t,
            float(ea[2]) * (1.0 - t) + float(eb[2]) * t,
        ]
    return {"location": loc, "eulers": eulers}


def _plant_after_pose(arm, job: dict, plant_state: dict | None) -> dict | None:
    cfg = job.get("fixedLengthIk") or {}
    ga_mode, ga_bones = _ground_anchor_settings(cfg)
    if ga_mode == "off":
        return plant_state
    if ga_mode == "frame0_lateral_lowest_foot":
        if plant_state is None:
            return {
                "groundZ": float(_min_foot_world_z(arm, ga_bones)),
                "loc0xy": (float(arm.location.x), float(arm.location.y)),
                "bones": ga_bones,
                "mode": ga_mode,
            }
        _apply_frame0_lateral_plant(
            arm,
            plant_state["bones"],
            ground_z=float(plant_state["groundZ"]),
            loc0_xy=tuple(plant_state["loc0xy"]),
        )
        return plant_state
    if ga_mode == "lowest_foot":
        if plant_state is None:
            return {
                "groundZ": float(_min_foot_world_z(arm, ga_bones)),
                "bones": ga_bones,
                "mode": ga_mode,
            }
        z_before = _min_foot_world_z(arm, plant_state["bones"])
        dz = float(plant_state["groundZ"]) - z_before
        arm.location = Vector((arm.location.x, arm.location.y, arm.location.z + dz))
        bpy.context.view_layer.update()
        return plant_state
    raise RuntimeError(f"unsupported groundAnchor.mode={ga_mode}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit-dir", type=Path, required=True)
    ap.add_argument("--out-fps", type=int, default=60)
    ap.add_argument("--width", type=int, default=720)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--preview-loops", type=int, default=6)
    ap.add_argument(
        "--gif-frame-ms",
        type=int,
        default=PREVIEW_GIF_FRAME_MS,
        help="Per-source-frame delay matching stick GIF (default 180ms)",
    )
    ap.add_argument(
        "--loopable",
        action="store_true",
        default=True,
        help="Wrap last→first for cycle timing (walk/idle). Default on.",
    )
    ap.add_argument("--no-loopable", action="store_false", dest="loopable")
    args = ap.parse_args(_argv_after_sep())

    fit_dir = args.fit_dir.resolve()
    job = json.loads((fit_dir / "job.resolved.json").read_text(encoding="utf-8"))
    kpt = json.loads((fit_dir / "sprite_landmarks" / "keypoints.json").read_text(encoding="utf-8"))
    report = json.loads((fit_dir / "fit_report.json").read_text(encoding="utf-8"))
    roles = json.loads(Path(job["boneRoles"]).read_text(encoding="utf-8"))
    src_fps = float(job.get("fps", 12))
    out_fps = int(args.out_fps)
    frame_ms = int(args.gif_frame_ms)
    pose_snaps = report.get("poseSnapshots")
    drive_from_poses = isinstance(pose_snaps, list) and len(pose_snaps) >= 2

    out_dir = fit_dir / "preview_lit_60fps"
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("mesh_*.png"):
        old.unlink()

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(job["masterGlb"])))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    # Match the game: Unity's SkinnedMeshRenderer blends multi-bone weights with
    # dual quaternions (SkinQuality Auto -> Bone4). Blender's glTF import leaves
    # LBS on, so previews showed candy-wrapper stretch the game never produces.
    for mod in mesh.modifiers:
        if mod.type == "ARMATURE":
            mod.use_deform_preserve_volume = True
    if arm.animation_data:
        arm.animation_data_clear()
    _disable_inherit_scale(arm)
    _clear_pose(arm)
    tip_cache = cache_tip_bind_local(arm, mesh, roles)

    _setup_lit_scene()
    cam = setup_pose_camera(job, arm, bpy_module=bpy)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 24
    scene.render.resolution_x = int(args.width)
    scene.render.resolution_y = int(args.height)
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.fps = out_fps

    depths = _bind_depths(arm, roles, mesh=mesh, tip_cache=tip_cache)
    src_frames = sorted(kpt["frames"], key=lambda f: int(f["frameIndex"]))

    # Precompute unprojected targets per source frame (fallback when no poseSnapshots).
    src_targets: list[dict[str, Vector]] = []
    if not drive_from_poses:
        for fr in src_frames:
            sw = float(fr["transform"]["srcWidth"])
            sh = float(fr["transform"]["srcHeight"])
            src_targets.append(_unproject_frame(scene, cam, fr["joints"], depths, sw, sh))

    n_src = len(pose_snaps) if drive_from_poses else len(src_targets)
    # Wall-clock = stick GIF default (n × 180ms), not job fps=12.
    duration_s = cycle_duration_s(n_src, frame_ms)
    n_out = interpolated_frame_count(n_src, out_fps, frame_ms)

    plant_state = None
    # Seed plant from frame0 pose/target before the interpolate loop.
    if drive_from_poses:
        _apply_captured_pose(arm, pose_snaps[0])
    else:
        _reset_bones(arm)
        _pose_frame(
            arm,
            mesh,
            roles,
            src_targets[0],
            tip_cache,
            prefer_up=_camera_up_world(cam),
            cam_forward=_camera_forward_world(cam),
        )
    plant_state = _plant_after_pose(arm, job, None)

    rendered = []
    for oi in range(n_out):
        if args.loopable:
            u = (oi / float(n_out)) * float(n_src)
            i0 = int(u) % n_src
            i1 = (i0 + 1) % n_src
            t = u - int(u)
        else:
            u = oi / float(max(1, n_out - 1)) * float(max(0, n_src - 1))
            i0 = int(u)
            i1 = min(i0 + 1, n_src - 1)
            t = u - i0
        if drive_from_poses:
            if i0 == i1:
                pose = pose_snaps[i0]
            else:
                pose = _lerp_pose(pose_snaps[i0], pose_snaps[i1], t)
            _apply_captured_pose(arm, pose)
        else:
            if i0 == i1:
                targets = src_targets[i0]
            else:
                targets = _lerp_targets(src_targets[i0], src_targets[i1], t)
            _reset_bones(arm)
            _pose_frame(
                arm,
                mesh,
                roles,
                targets,
                tip_cache,
                prefer_up=_camera_up_world(cam),
                cam_forward=_camera_forward_world(cam),
            )
        plant_state = _plant_after_pose(arm, job, plant_state)
        bpy.context.view_layer.update()
        path = frames_dir / f"mesh_{oi + 1:04d}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        rendered.append(path)
        if oi == 0 or oi == n_out - 1 or (oi + 1) % 10 == 0:
            print(
                f"[lit60-fl] render {oi + 1}/{n_out} (blend {i0}->{i1} t={t:.2f}) "
                f"drive={'poses' if drive_from_poses else 'ik'} "
                f"cycle={duration_s:.3f}s gifMs={frame_ms}",
                flush=True,
            )
    clip_id = str(job.get("clipId", "clip"))
    gif_fps = 1000.0 / float(frame_ms)
    encoded = _encode_previews(
        frames_dir,
        out_dir,
        clip_id,
        out_fps,
        int(args.preview_loops),
        gif_fps,
    )
    meta = {
        "ok": True,
        "method": (
            "fixed_length_ik_lit_60fps_pose_lerp"
            if drive_from_poses
            else "fixed_length_ik_lit_60fps_target_lerp"
        ),
        "drive": "poseSnapshots" if drive_from_poses else "keypoint_ik",
        "srcFps": src_fps,
        "outFps": out_fps,
        "gifFrameMs": frame_ms,
        "cycleDurationS": duration_s,
        "loopable": bool(args.loopable),
        "previewLoops": int(args.preview_loops),
        "frameCount": len(rendered),
        "mp4": encoded["mp4"],
        "mp4Looped": encoded["mp4Looped"],
        "gif": encoded["gif"],
        "framesDir": str(frames_dir).replace("\\", "/"),
        "proof": (
            "generated — lit mesh-only at stick-GIF wall-clock "
            f"({frame_ms}ms/src frame); not OE runtime"
        ),
    }
    (out_dir / "preview_lit_60fps_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ok": True,
                "frames": len(rendered),
                "mp4": meta["mp4"],
                "mp4Looped": meta["mp4Looped"],
                "gif": meta["gif"],
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
