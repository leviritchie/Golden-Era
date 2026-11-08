#!/usr/bin/env python3
"""Fixed-length rotate-only IK for owned rider_mount rigs (cavalier).

Uses roles.jointSites + primaryJoints from bone_roles_cavalier_owned.json.
Sprite landmarks drive horse head, rider helmet, lance tip, four hooves, wrists.

Blender:
  blender -b --python blender_fixed_length_ik_mount.py -- \\
    --job job.resolved.json --keypoints kp.json --roles roles.json
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

_TOOL = Path(__file__).resolve().parent
if str(_TOOL) not in sys.path:
    sys.path.insert(0, str(_TOOL))
from blender_fixed_length_ik import (  # noqa: E402
    _apply_captured_pose,
    _apply_frame0_lateral_plant,
    _camera_up_world,
    _capture_pose,
    _ccd_effector,
    _min_foot_world_z,
    _smooth_pose_eulers,
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

DEFAULT_MOUNT_FOOT_BONES = [
    "HorseLeftForeHoof",
    "HorseRightForeHoof",
    "HorseLeftHindHoof",
    "HorseRightHindHoof",
]


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _parse() -> dict:
    args = _argv()
    out = {"job": None, "keypoints": None, "roles": None}
    i = 0
    while i < len(args):
        if args[i] in {"--job", "--keypoints", "--roles"} and i + 1 < len(args):
            out[args[i][2:]] = Path(args[i + 1])
            i += 2
        else:
            i += 1
    if not out["job"] or not out["keypoints"] or not out["roles"]:
        raise SystemExit("need --job --keypoints --roles")
    return out


def _mount_foot_settings(cfg: dict) -> tuple[str, list[str]]:
    raw = cfg.get("groundAnchor")
    if not raw:
        return "off", list(DEFAULT_MOUNT_FOOT_BONES)
    if isinstance(raw, str):
        return raw, list(DEFAULT_MOUNT_FOOT_BONES)
    if isinstance(raw, dict):
        mode = str(raw.get("mode") or "off")
        bones = list(raw.get("bones") or DEFAULT_MOUNT_FOOT_BONES)
        return mode, bones
    raise RuntimeError(f"fixedLengthIk.groundAnchor must be str or object, got {type(raw)}")


def _align_root_saddle(arm, saddle_w: Vector) -> None:
    bpy.context.view_layer.update()
    pb = arm.pose.bones.get("Saddle")
    if pb is None:
        pb = arm.pose.bones.get("MountRoot")
        if pb is None:
            raise RuntimeError("mount IK: missing Saddle or MountRoot bone")
    cur = arm.matrix_world @ pb.head
    arm.location = arm.location + (saddle_w - cur)
    bpy.context.view_layer.update()


def _register_camera_scale_mount(
    job: dict,
    arm,
    scene,
    joints0: dict,
    depths: dict[str, Vector],
    sw: float,
    sh: float,
) -> object:
    """Scale ortho so Saddle→LanceTip projected length matches authored sprite span."""
    authored = math.hypot(
        float(joints0["LanceTip"]["x"]) - float(joints0["Saddle"]["x"]),
        float(joints0["LanceTip"]["y"]) - float(joints0["Saddle"]["y"]),
    )
    if authored < 8.0:
        raise RuntimeError("authored Saddle→LanceTip length too small for camera register")
    base = float((job.get("camera") or {}).get("orthoScale", 4.2))
    best_scale = base
    best_err = 1e18
    saddle_bone = arm.pose.bones.get("Saddle") or arm.pose.bones.get("MountRoot")
    lance_bone = arm.pose.bones.get("LanceTip")
    if saddle_bone is None or lance_bone is None:
        raise RuntimeError("camera register needs Saddle/MountRoot and LanceTip bones")
    for scale in np.linspace(base * 0.55, base * 1.55, 21):
        job_cam = json.loads(json.dumps(job))
        job_cam.setdefault("camera", {})["orthoScale"] = float(scale)
        for obj in list(bpy.data.objects):
            if obj.type == "CAMERA":
                bpy.data.objects.remove(obj, do_unlink=True)
        cam = setup_pose_camera(job_cam, arm, bpy_module=bpy)
        _clear_pose(arm)
        bpy.context.view_layer.update()
        bs = arm.matrix_world @ saddle_bone.head
        bt = arm.matrix_world @ lance_bone.head
        p0 = _project_px(scene, cam, bs, sw, sh)
        p1 = _project_px(scene, cam, bt, sw, sh)
        proj = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        err = abs(proj - authored)
        if err < best_err:
            best_err = err
            best_scale = float(scale)
    job.setdefault("camera", {})["orthoScale"] = best_scale
    for obj in list(bpy.data.objects):
        if obj.type == "CAMERA":
            bpy.data.objects.remove(obj, do_unlink=True)
    cam = setup_pose_camera(job, arm, bpy_module=bpy)
    print(
        f"[fixed-ik-mount] camera register orthoScale={best_scale:.3f} "
        f"lanceSpanErrPx={best_err:.2f}",
        flush=True,
    )
    return cam


def _pose_frame_mount(
    arm,
    mesh,
    roles: dict,
    targets: dict[str, Vector],
    tip_cache: dict,
    *,
    prefer_up: Vector | None = None,
    align_saddle: bool = True,
) -> None:
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()

    if align_saddle:
        _align_root_saddle(arm, targets["Saddle"])

    def eff_joint(name: str):
        return landmark_world(arm, mesh, roles, name, tip_cache=tip_cache)

    def eff_bone_head(name: str):
        return arm.matrix_world @ arm.pose.bones[name].head

    # Horse: short chains only — never rotate MountRoot (ground plant owns translation).
    _ccd_effector(
        arm,
        ["HorseSpine1", "HorseSpine2"],
        targets["HorseNose"],
        lambda: eff_bone_head("HorseSpine2"),
        iterations=12,
    )
    _ccd_effector(
        arm,
        ["HorseNeck", "HorseHead"],
        targets["HorseNose"],
        lambda: eff_joint("HorseNose"),
        iterations=20,
        prefer_up=prefer_up,
        prefer_up_weight=0.12,
        prefer_up_bones={"HorseNeck", "HorseHead"},
    )

    for bones, hoof_j in (
        (["HorseLeftShoulder", "HorseLeftForeLeg", "HorseLeftForeHoof"], "LHoofFore"),
        (["HorseRightShoulder", "HorseRightForeLeg", "HorseRightForeHoof"], "RHoofFore"),
        (["HorseLeftHip", "HorseLeftHindLeg", "HorseLeftHindHoof"], "LHoofHind"),
        (["HorseRightHip", "HorseRightHindLeg", "HorseRightHindHoof"], "RHoofHind"),
    ):
        _ccd_effector(
            arm,
            bones,
            targets[hoof_j],
            lambda bn=bones[-1]: eff_bone_head(bn),
            iterations=18,
        )

    _ccd_effector(
        arm,
        ["RiderSpine", "RiderChest", "RiderNeck", "RiderHead"],
        targets["RiderHelmet"],
        lambda: eff_joint("RiderHelmet"),
        iterations=22,
        prefer_up=prefer_up,
        prefer_up_weight=0.15,
        prefer_up_bones={"RiderNeck", "RiderHead"},
    )

    _ccd_effector(
        arm,
        ["RiderRightShoulder", "RiderRightArm", "RiderRightHand"],
        targets["RWrist"],
        lambda: eff_bone_head("RiderRightHand"),
        iterations=16,
    )
    _ccd_effector(
        arm,
        ["Lance"],
        targets["LanceTip"],
        lambda: eff_joint("LanceTip"),
        iterations=18,
    )

    _ccd_effector(
        arm,
        ["RiderLeftShoulder", "RiderLeftArm", "RiderLeftHand"],
        targets["LWrist"],
        lambda: eff_bone_head("RiderLeftHand"),
        iterations=16,
    )

    for pb in arm.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def _refine_mount_after_plant(
    arm,
    mesh,
    roles: dict,
    targets: dict[str, Vector],
    tip_cache: dict,
    *,
    prefer_up: Vector | None = None,
) -> None:
    """Re-aim rider/lance/head after ground plant without resetting legs or root."""
    def eff_joint(name: str):
        return landmark_world(arm, mesh, roles, name, tip_cache=tip_cache)

    def eff_bone_head(name: str):
        return arm.matrix_world @ arm.pose.bones[name].head

    _ccd_effector(
        arm,
        ["HorseNeck", "HorseHead"],
        targets["HorseNose"],
        lambda: eff_joint("HorseNose"),
        iterations=12,
    )
    _ccd_effector(
        arm,
        ["RiderNeck", "RiderHead"],
        targets["RiderHelmet"],
        lambda: eff_joint("RiderHelmet"),
        iterations=12,
    )
    _ccd_effector(
        arm,
        ["RiderRightArm", "RiderRightHand", "Lance"],
        targets["LanceTip"],
        lambda: eff_joint("LanceTip"),
        iterations=16,
    )
    _ccd_effector(
        arm,
        ["RiderLeftArm", "RiderLeftHand"],
        targets["LWrist"],
        lambda: eff_bone_head("RiderLeftHand"),
        iterations=10,
    )
    for pb in arm.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def main() -> int:
    opts = _parse()
    job = json.loads(opts["job"].read_text(encoding="utf-8"))
    kpt = json.loads(opts["keypoints"].read_text(encoding="utf-8"))
    roles = json.loads(opts["roles"].read_text(encoding="utf-8"))
    cfg = job.get("fixedLengthIk") or {}
    register_cam = bool(cfg.get("frame0CameraRegister", True))
    ga_mode, ga_bones = _mount_foot_settings(cfg)
    post_smooth_sigma = float(cfg.get("postSmoothSigma") or 0.0)
    post_smooth_include = cfg.get("postSmoothIncludeBones")
    post_smooth_exclude = cfg.get("postSmoothExcludeBones")
    if post_smooth_include is not None:
        post_smooth_include = list(post_smooth_include)
    if post_smooth_exclude is not None:
        post_smooth_exclude = list(post_smooth_exclude)

    out_dir = Path(job["outputDir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(job["masterGlb"])))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    _disable_inherit_scale(arm)
    _clear_pose(arm)

    tip_cache = cache_tip_bind_local(arm, mesh, roles)
    horse_site = (roles.get("jointSites") or {}).get("HorseNose") or {}
    if horse_site.get("mode") in ("farthest_skinned_vert", "highest_skinned_vert"):
        if "HorseNose" not in tip_cache:
            raise RuntimeError("HorseNose skinned site failed to cache")
    lance_site = (roles.get("jointSites") or {}).get("LanceTip") or {}
    if lance_site.get("mode") == "bone" and "LanceTip" not in arm.pose.bones:
        raise RuntimeError("LanceTip bone missing on master")

    print(f"[fixed-ik-mount] groundAnchor={ga_mode} bones={ga_bones}", flush=True)

    scene = bpy.context.scene
    depths = _bind_depths(arm, roles, mesh=mesh, tip_cache=tip_cache)
    frames = sorted(kpt["frames"], key=lambda f: int(f["frameIndex"]))
    sw0 = float(frames[0]["transform"]["srcWidth"])
    sh0 = float(frames[0]["transform"]["srcHeight"])

    required = list(roles.get("primaryJoints") or []) + ["Saddle"]
    for jn in required:
        if jn not in frames[0]["joints"]:
            raise RuntimeError(f"keypoints missing joint {jn}")
        if jn not in roles.get("joints", {}):
            raise RuntimeError(f"roles missing joint {jn}")

    if register_cam and not job.get("cameraFitPath"):
        cam = _register_camera_scale_mount(job, arm, scene, frames[0]["joints"], depths, sw0, sh0)
    elif job.get("cameraFitPath"):
        from roc_chroma_match_worker import setup_camera  # noqa: E402

        fit_data = json.loads(Path(job["cameraFitPath"]).read_text(encoding="utf-8"))
        cam, _right, _up, _fwd, _profile = setup_camera(
            fit_data,
            arm,
            [mesh],
            detect_profile=False,
            honor_fit_screen_offset=True,
            fit_coordinate_basis=str(job.get("fitCoordinateBasis") or "native"),
        )
        print(f"[fixed-ik-mount] camera from fit {job['cameraFitPath']}", flush=True)
    else:
        cam = setup_pose_camera(job, arm, bpy_module=bpy)

    _clear_pose(arm)
    bpy.context.view_layer.update()
    tip_cache = cache_tip_bind_local(arm, mesh, roles)
    depths = _bind_depths(arm, roles, mesh=mesh, tip_cache=tip_cache)

    solved_poses: list[dict] = []
    frame_targets: list[dict[str, Vector]] = []
    plant_stats: list[dict] = []
    ground_z: float | None = None
    loc0_xy: tuple[float, float] | None = None

    for fr in frames:
        fi = int(fr["frameIndex"])
        sw = float(fr["transform"]["srcWidth"])
        sh = float(fr["transform"]["srcHeight"])
        _clear_pose(arm)
        bpy.context.view_layer.update()
        targets = _unproject_frame(scene, cam, fr["joints"], depths, sw, sh)
        prefer_up = _camera_up_world(cam)
        _pose_frame_mount(arm, mesh, roles, targets, tip_cache, prefer_up=prefer_up)

        ga_stat: dict = {}
        if ga_mode == "frame0_lateral_lowest_foot":
            if fi == 0:
                ground_z = _min_foot_world_z(arm, ga_bones)
                loc0_xy = (float(arm.location.x), float(arm.location.y))
                ga_stat.update(
                    {"groundZ": float(ground_z), "loc0xy": list(loc0_xy), "deltaZ": 0.0, "role": "frame0_reference"}
                )
            else:
                assert loc0_xy is not None and ground_z is not None
                ga_stat.update(
                    _apply_frame0_lateral_plant(arm, ga_bones, ground_z=ground_z, loc0_xy=loc0_xy)
                )
                _refine_mount_after_plant(
                    arm, mesh, roles, targets, tip_cache, prefer_up=prefer_up
                )
                ga_stat["afterRefine"] = _apply_frame0_lateral_plant(
                    arm, ga_bones, ground_z=ground_z, loc0_xy=loc0_xy
                )
        elif ga_mode == "lowest_foot":
            if ground_z is None:
                ground_z = _min_foot_world_z(arm, ga_bones)
                ga_stat.update({"groundZ": float(ground_z), "deltaZ": 0.0, "role": "frame0_reference"})
            else:
                z_before = _min_foot_world_z(arm, ga_bones)
                dz = float(ground_z) - z_before
                arm.location = Vector((arm.location.x, arm.location.y, arm.location.z + dz))
                bpy.context.view_layer.update()
                _refine_mount_after_plant(
                    arm, mesh, roles, targets, tip_cache, prefer_up=prefer_up
                )
                z_before2 = _min_foot_world_z(arm, ga_bones)
                dz2 = float(ground_z) - z_before2
                arm.location = Vector((arm.location.x, arm.location.y, arm.location.z + dz2))
                bpy.context.view_layer.update()
                ga_stat.update(
                    {
                        "groundZ": float(ground_z),
                        "zBefore": float(z_before),
                        "zAfter": float(_min_foot_world_z(arm, ga_bones)),
                        "deltaZ": float(dz),
                    }
                )
        elif ga_mode != "off":
            raise RuntimeError(f"unsupported groundAnchor.mode={ga_mode}")

        plant_stats.append({"frameIndex": fi, **ga_stat})
        frame_targets.append(targets)
        solved_poses.append(_capture_pose(arm))
        print(f"[fixed-ik-mount] solved frame {fi} plant_dz={ga_stat.get('deltaZ', 0.0):+.4f}", flush=True)

    if post_smooth_sigma > 0.0:
        solved_poses = _smooth_pose_eulers(
            solved_poses,
            sigma=post_smooth_sigma,
            include_bones=post_smooth_include,
            exclude_bones=post_smooth_exclude,
        )
        if ga_mode == "frame0_lateral_lowest_foot" and ground_z is not None and loc0_xy is not None:
            for i, pose in enumerate(solved_poses):
                _apply_captured_pose(arm, pose)
                _apply_frame0_lateral_plant(arm, ga_bones, ground_z=ground_z, loc0_xy=loc0_xy)
                _refine_mount_after_plant(
                    arm,
                    mesh,
                    roles,
                    frame_targets[i],
                    tip_cache,
                    prefer_up=_camera_up_world(cam),
                )
                _apply_frame0_lateral_plant(arm, ga_bones, ground_z=ground_z, loc0_xy=loc0_xy)
                solved_poses[i] = _capture_pose(arm)

    frame_reports = []
    for fr, pose, ga_stat in zip(frames, solved_poses, plant_stats):
        fi = int(fr["frameIndex"])
        sw = float(fr["transform"]["srcWidth"])
        sh = float(fr["transform"]["srcHeight"])
        _apply_captured_pose(arm, pose)
        errs = _measure_errors(
            arm, scene, cam, fr["joints"], roles, sw, sh, mesh=mesh, tip_cache=tip_cache
        )
        primary = list(roles.get("primaryJoints") or [])
        body = [errs[k] for k in primary if k in errs and k != "LanceTip"]
        frame_reports.append(
            {
                "frameIndex": fi,
                "lossPx": float(np.mean(list(errs.values()))),
                "bodyMeanLossPx": float(np.mean(body)) if body else 0.0,
                "maxBodyErrorPx": float(max(body)) if body else 0.0,
                "lanceTipErrorPx": float(errs.get("LanceTip", 0.0)),
                "horseNoseErrorPx": float(errs.get("HorseNose", 0.0)),
                "perJointErrorPx": errs,
                "groundAnchor": ga_stat,
                "minFootWorldZ": float(_min_foot_world_z(arm, ga_bones)),
            }
        )
        print(
            f"[fixed-ik-mount] frame {fi} bodyMean={frame_reports[-1]['bodyMeanLossPx']:.1f} "
            f"lance={frame_reports[-1]['lanceTipErrorPx']:.1f} "
            f"nose={frame_reports[-1]['horseNoseErrorPx']:.1f}",
            flush=True,
        )

    arm.animation_data_create()
    action = bpy.data.actions.new(name="FixedLengthIkMount")
    arm.animation_data.action = action
    for fr, pose in zip(frames, solved_poses):
        fi = int(fr["frameIndex"])
        scene.frame_set(fi + 1)
        _apply_captured_pose(arm, pose)
        arm.keyframe_insert(data_path="location", frame=fi + 1)
        for pb in arm.pose.bones:
            pb.keyframe_insert(data_path="location", frame=fi + 1)
            pb.keyframe_insert(data_path="rotation_euler", frame=fi + 1)
            pb.keyframe_insert(data_path="scale", frame=fi + 1)

    glb_path = out_dir / f"{job.get('clipId', 'clip')}_fixed_length_ik_mount.glb"
    for obj in bpy.data.objects:
        obj.select_set(obj.type in {"ARMATURE", "MESH"})
    bpy.context.view_layer.objects.active = arm
    scene.frame_start = 1
    scene.frame_end = len(frames)
    bpy.ops.export_scene.gltf(
        filepath=str(glb_path),
        export_format="GLB",
        use_selection=True,
        export_animations=True,
        export_force_sampling=True,
    )

    report = {
        "ok": True,
        "unitSid": job.get("unitSid"),
        "clipId": job.get("clipId"),
        "method": "fixed_length_ik_mount_rotate_only",
        "tipCache": tip_cache,
        "jointSites": roles.get("jointSites"),
        "frameCount": len(frames),
        "meanBodyLossPx": float(np.mean([f["bodyMeanLossPx"] for f in frame_reports])),
        "meanLanceTipErrorPx": float(np.mean([f["lanceTipErrorPx"] for f in frame_reports])),
        "meanHorseNoseErrorPx": float(np.mean([f["horseNoseErrorPx"] for f in frame_reports])),
        "maxBodyErrorPx": float(max(f["maxBodyErrorPx"] for f in frame_reports)),
        "frames": frame_reports,
        "poseSnapshots": solved_poses,
        "groundAnchor": {"mode": ga_mode, "bones": ga_bones, "groundZ": ground_z},
        "glb": str(glb_path),
    }
    report_path = out_dir / "fit_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "meanBodyLossPx": report["meanBodyLossPx"], "glb": str(glb_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
