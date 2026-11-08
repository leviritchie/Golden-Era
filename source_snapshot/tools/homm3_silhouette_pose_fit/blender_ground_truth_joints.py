#!/usr/bin/env python3
"""Ground-truth joint driver: authored 2D landmarks are the pose.

For each frame:
  1. Unproject every landmark through the pipeline ortho camera, keeping the
     bind-pose depth of that role bone (plane parallel to the camera).
  2. Aim+stretch Mixamo bones so each role bone head sits on its landmark
     (WeaponTip = RightHand tail). Intermediate spine/shoulder bones follow
     the polyline between authored joints.
  3. Fail-closed if any landmark projects farther than maxErrorPx from its
     authored target.

This is NOT marker IK. Residual above epsilon is a hard failure.

Blender:
  blender -b --python blender_ground_truth_joints.py -- \\
    --job job.resolved.json --keypoints kp.json --roles roles.json
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

_TOOL = Path(__file__).resolve().parent
if str(_TOOL) not in sys.path:
    sys.path.insert(0, str(_TOOL))
from homm3_pose_camera import setup_pose_camera  # noqa: E402


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


def _clear_pose(arm) -> None:
    if arm.animation_data:
        arm.animation_data_clear()
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    arm.location = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()


def _project_px(scene, cam, world: Vector, sw: float, sh: float) -> tuple[float, float]:
    co = world_to_camera_view(scene, cam, world)
    return float(co.x) * sw, float(1.0 - co.y) * sh


def _shift_to_pixel(
    scene,
    cam,
    world_pt: Vector,
    px: float,
    py: float,
    sw: float,
    sh: float,
) -> Vector:
    """Move point in the camera plane so it projects exactly to (px, py)."""
    right = (cam.matrix_world.to_3x3() @ Vector((1.0, 0.0, 0.0))).normalized()
    up = (cam.matrix_world.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()
    pt = Vector(world_pt)
    for _ in range(4):
        cx, cy = _project_px(scene, cam, pt, sw, sh)
        err = Vector((px - cx, py - cy))
        if err.length < 1e-4:
            break
        eps = 0.02
        rx, ry = _project_px(scene, cam, pt + right * eps, sw, sh)
        ux, uy = _project_px(scene, cam, pt + up * eps, sw, sh)
        J = np.array(
            [
                [(rx - cx) / eps, (ux - cx) / eps],
                [(ry - cy) / eps, (uy - cy) / eps],
            ],
            dtype=np.float64,
        )
        try:
            delta = np.linalg.solve(J, np.array([err.x, err.y], dtype=np.float64))
        except np.linalg.LinAlgError as exc:
            raise RuntimeError(f"unproject Jacobian singular at px=({px},{py})") from exc
        pt = pt + right * float(delta[0]) + up * float(delta[1])
    return pt


def _basis_y(direction: Vector, roll_hint: Vector) -> Matrix:
    y = direction.normalized()
    x = y.cross(roll_hint)
    if x.length < 1e-6:
        fallback = Vector((0.0, 0.0, 1.0)) if abs(y.z) < 0.9 else Vector((1.0, 0.0, 0.0))
        x = y.cross(fallback)
    x.normalize()
    z = x.cross(y)
    z.normalize()
    return Matrix((x, y, z)).transposed().to_4x4()


def _set_bone_head_tail(arm, bone_name: str, head_w: Vector, tip_w: Vector) -> None:
    """Place bone head/tip in world via armature-space pose matrix + Y stretch.

    Requires arm.data.bones[*].inherit_scale == 'NONE' so parent stretch does not
    detonate child chains on scaled Mixamo GLB imports.
    """
    pb = arm.pose.bones.get(bone_name)
    if pb is None:
        raise RuntimeError(f"missing bone {bone_name}")
    rest_len = float(pb.bone.length)
    if rest_len < 1e-8:
        raise RuntimeError(f"bone {bone_name} has zero rest length")

    for _ in range(2):
        aw_inv = arm.matrix_world.inverted()
        head_a = aw_inv @ head_w
        tip_a = aw_inv @ tip_w
        direction = tip_a - head_a
        length = float(direction.length)
        if length < 1e-5:
            raise RuntimeError(f"bone {bone_name}: head/tip collapsed ({length:.2e})")
        rest_y = (pb.bone.tail_local - pb.bone.head_local).normalized()
        roll_hint = Vector((0.0, 0.0, 1.0))
        if abs(direction.normalized().dot(roll_hint)) > 0.95:
            roll_hint = rest_y
        rot = _basis_y(direction, roll_hint)
        scale = length / rest_len
        pb.matrix = Matrix.Translation(head_a) @ rot @ Matrix.Diagonal((1.0, scale, 1.0, 1.0))
        bpy.context.view_layer.update()

    got_head = arm.matrix_world @ pb.head
    got_tip = arm.matrix_world @ pb.tail
    if (got_head - head_w).length > 1e-3 or (got_tip - tip_w).length > 1e-3:
        raise RuntimeError(
            f"bone {bone_name} pose miss head={(got_head - head_w).length:.4f} "
            f"tip={(got_tip - tip_w).length:.4f}"
        )


def _disable_inherit_scale(arm) -> None:
    for bone in arm.data.bones:
        bone.inherit_scale = "NONE"


def _lerp(a: Vector, b: Vector, t: float) -> Vector:
    return a * (1.0 - t) + b * t


def _polyline_heads(start: Vector, end: Vector, rest_lengths: list[float]) -> list[Vector]:
    """Bone-head positions along start→end; last head lands exactly on end."""
    total = float(sum(rest_lengths))
    if total < 1e-8:
        raise RuntimeError("polyline rest lengths sum to 0")
    heads: list[Vector] = []
    acc = 0.0
    for L in rest_lengths:
        acc += float(L)
        heads.append(_lerp(start, end, acc / total))
    return heads


def _bind_depths(arm, roles: dict, mesh=None, tip_cache=None) -> dict[str, Vector]:
    from homm3_landmark_sites import bind_depth_anchors

    return bind_depth_anchors(arm, mesh, roles, tip_cache=tip_cache)


def _landmark_world(arm, jn: str, roles: dict, mesh=None, tip_cache=None) -> Vector:
    from homm3_landmark_sites import landmark_world

    return landmark_world(arm, mesh, roles, jn, tip_cache=tip_cache)


def _unproject_frame(
    scene,
    cam,
    joints: dict,
    depths: dict[str, Vector],
    sw: float,
    sh: float,
) -> dict[str, Vector]:
    targets = {}
    for jn, spec in joints.items():
        if not spec.get("visible", True):
            raise RuntimeError(f"ground-truth requires visible joint: {jn}")
        if jn not in depths:
            raise RuntimeError(f"no depth anchor for joint {jn}")
        targets[jn] = _shift_to_pixel(
            scene,
            cam,
            depths[jn],
            float(spec["x"]),
            float(spec["y"]),
            sw,
            sh,
        )
    return targets


def _apply_targets(arm, targets: dict[str, Vector]) -> None:
    """Aim+stretch bones so role heads (and hand tip) match unprojected targets."""
    # --- Legs (Hips head = MidHip; leg bones heads = hip/knee/ankle) ---
    hips_tip = _lerp(targets["MidHip"], targets["Neck"], 0.18)
    _set_bone_head_tail(arm, "Hips", targets["MidHip"], hips_tip)

    _set_bone_head_tail(arm, "RightUpLeg", targets["RHip"], targets["RKnee"])
    _set_bone_head_tail(arm, "RightLeg", targets["RKnee"], targets["RAnkle"])
    # Foot tip: extend slightly beyond ankle along ankle-knee direction flipped.
    rankle_dir = targets["RAnkle"] - targets["RKnee"]
    if rankle_dir.length < 1e-6:
        rankle_dir = Vector((0.0, 0.15, 0.0))
    _set_bone_head_tail(
        arm,
        "RightFoot",
        targets["RAnkle"],
        targets["RAnkle"] + rankle_dir.normalized() * max(0.05, rankle_dir.length * 0.25),
    )

    _set_bone_head_tail(arm, "LeftUpLeg", targets["LHip"], targets["LKnee"])
    _set_bone_head_tail(arm, "LeftLeg", targets["LKnee"], targets["LAnkle"])
    lankle_dir = targets["LAnkle"] - targets["LKnee"]
    if lankle_dir.length < 1e-6:
        lankle_dir = Vector((0.0, 0.15, 0.0))
    _set_bone_head_tail(
        arm,
        "LeftFoot",
        targets["LAnkle"],
        targets["LAnkle"] + lankle_dir.normalized() * max(0.05, lankle_dir.length * 0.25),
    )

    # --- Spine: heads along MidHip→Neck; neck.head lands on Neck ---
    spine_names = ["Spine02", "Spine01", "Spine", "neck"]
    rest_lens = [float(arm.pose.bones[n].bone.length) for n in spine_names]
    spine_heads = _polyline_heads(targets["MidHip"], targets["Neck"], rest_lens)
    for i, name in enumerate(spine_names):
        head = spine_heads[i]
        if i + 1 < len(spine_heads):
            tip = spine_heads[i + 1]
        else:
            nose_dir = targets["Nose"] - targets["Neck"]
            if nose_dir.length < 1e-6:
                nose_dir = Vector((0.0, 0.0, 0.1))
            tip = targets["Neck"] + nose_dir.normalized() * max(
                0.05, nose_dir.length * 0.35
            )
        _set_bone_head_tail(arm, name, head, tip)

    nose_dir = targets["Nose"] - targets["Neck"]
    if nose_dir.length < 1e-6:
        nose_dir = Vector((0.0, 0.0, 0.1))
    _set_bone_head_tail(
        arm,
        "Head",
        targets["Nose"],
        targets["Nose"] + nose_dir.normalized() * max(0.05, nose_dir.length * 0.5),
    )

    # --- Arms: shoulder bone then arm chain; hand tip = WeaponTip on right ---
    spine_tail = targets["Neck"]
    # Right shoulder bone spans toward RShoulder landmark.
    _set_bone_head_tail(
        arm,
        "RightShoulder",
        _lerp(spine_tail, targets["RShoulder"], 0.15),
        targets["RShoulder"],
    )
    _set_bone_head_tail(arm, "RightArm", targets["RShoulder"], targets["RElbow"])
    _set_bone_head_tail(arm, "RightForeArm", targets["RElbow"], targets["RWrist"])
    _set_bone_head_tail(arm, "RightHand", targets["RWrist"], targets["WeaponTip"])

    _set_bone_head_tail(
        arm,
        "LeftShoulder",
        _lerp(spine_tail, targets["LShoulder"], 0.15),
        targets["LShoulder"],
    )
    _set_bone_head_tail(arm, "LeftArm", targets["LShoulder"], targets["LElbow"])
    _set_bone_head_tail(arm, "LeftForeArm", targets["LElbow"], targets["LWrist"])
    # Left hand tip: extend beyond wrist along forearm direction.
    lw_dir = targets["LWrist"] - targets["LElbow"]
    if lw_dir.length < 1e-6:
        lw_dir = Vector((0.0, 0.1, 0.0))
    _set_bone_head_tail(
        arm,
        "LeftHand",
        targets["LWrist"],
        targets["LWrist"] + lw_dir.normalized() * max(0.05, lw_dir.length * 0.35),
    )


def _measure_errors(
    arm,
    scene,
    cam,
    joints: dict,
    roles: dict,
    sw: float,
    sh: float,
    *,
    mesh=None,
    tip_cache=None,
) -> dict[str, float]:
    errs = {}
    for jn, spec in joints.items():
        w = _landmark_world(arm, jn, roles, mesh=mesh, tip_cache=tip_cache)
        px, py = _project_px(scene, cam, w, sw, sh)
        errs[jn] = float(math.hypot(px - float(spec["x"]), py - float(spec["y"])))
    return errs


def _register_camera_scale(
    job: dict,
    arm,
    scene,
    joints0: dict,
    depths: dict[str, Vector],
    sw: float,
    sh: float,
) -> object:
    """Scale ortho so MidHip→Nose projected length matches authored (translation via unproject)."""
    authored = math.hypot(
        float(joints0["Nose"]["x"]) - float(joints0["MidHip"]["x"]),
        float(joints0["Nose"]["y"]) - float(joints0["MidHip"]["y"]),
    )
    if authored < 1.0:
        raise RuntimeError("authored MidHip→Nose length too small")
    base = float((job.get("camera") or {}).get("orthoScale", 4.2))
    best_scale = base
    best_err = 1e18
    best_cam = None
    for scale in np.linspace(base * 0.55, base * 1.55, 21):
        job_cam = json.loads(json.dumps(job))
        job_cam.setdefault("camera", {})["orthoScale"] = float(scale)
        # Remove previous camera objects.
        for obj in list(bpy.data.objects):
            if obj.type == "CAMERA":
                bpy.data.objects.remove(obj, do_unlink=True)
        cam = setup_pose_camera(job_cam, arm, bpy_module=bpy)
        mid = _shift_to_pixel(
            scene,
            cam,
            depths["MidHip"],
            float(joints0["MidHip"]["x"]),
            float(joints0["MidHip"]["y"]),
            sw,
            sh,
        )
        nose = _shift_to_pixel(
            scene,
            cam,
            depths["Nose"],
            float(joints0["Nose"]["x"]),
            float(joints0["Nose"]["y"]),
            sw,
            sh,
        )
        # Projected length after placing those worlds (by construction ~authored,
        # but ortho scale changes world spacing vs sprite). Use bind-depth unproject
        # spacing in pixels of MidHip→Nose at identity without shift as meter.
        _clear_pose(arm)
        bpy.context.view_layer.update()
        bmid = arm.matrix_world @ arm.pose.bones["Hips"].head
        bnose = arm.matrix_world @ arm.pose.bones["Head"].head
        p0 = _project_px(scene, cam, bmid, sw, sh)
        p1 = _project_px(scene, cam, bnose, sw, sh)
        proj = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        err = abs(proj - authored)
        if err < best_err:
            best_err = err
            best_scale = float(scale)
            best_cam = cam
            _ = (mid, nose)  # depth anchors validated
    job.setdefault("camera", {})["orthoScale"] = best_scale
    # Rebuild final camera at best scale.
    for obj in list(bpy.data.objects):
        if obj.type == "CAMERA":
            bpy.data.objects.remove(obj, do_unlink=True)
    cam = setup_pose_camera(job, arm, bpy_module=bpy)
    print(
        f"[gt-joints] camera register orthoScale={best_scale:.3f} "
        f"torsoScaleErrPx={best_err:.2f}",
        flush=True,
    )
    return cam


def main() -> int:
    opts = _parse()
    job = json.loads(opts["job"].read_text(encoding="utf-8"))
    kpt = json.loads(opts["keypoints"].read_text(encoding="utf-8"))
    roles = json.loads(opts["roles"].read_text(encoding="utf-8"))
    gt = job.get("groundTruthJoints") or job.get("markerIk") or {}
    max_err = float(gt.get("maxErrorPx", job.get("maxErrorPx", 2.0)))
    register_cam = bool(gt.get("frame0CameraRegister", True))

    out_dir = Path(job["outputDir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(job["masterGlb"])))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    _disable_inherit_scale(arm)
    _clear_pose(arm)

    required = [
        "Nose",
        "Neck",
        "RShoulder",
        "RElbow",
        "RWrist",
        "WeaponTip",
        "LShoulder",
        "LElbow",
        "LWrist",
        "MidHip",
        "RHip",
        "RKnee",
        "RAnkle",
        "LHip",
        "LKnee",
        "LAnkle",
    ]
    for jn in required:
        if jn not in roles.get("joints", {}):
            raise RuntimeError(f"roles missing joint {jn}")

    scene = bpy.context.scene
    depths = _bind_depths(arm, roles)
    frames = sorted(kpt["frames"], key=lambda f: int(f["frameIndex"]))
    if not frames:
        raise RuntimeError("no keypoint frames")

    sw0 = float(frames[0]["transform"]["srcWidth"])
    sh0 = float(frames[0]["transform"]["srcHeight"])
    if register_cam:
        cam = _register_camera_scale(job, arm, scene, frames[0]["joints"], depths, sw0, sh0)
    else:
        cam = setup_pose_camera(job, arm, bpy_module=bpy)

    # Refresh depth anchors after camera/arm yaw setup.
    _clear_pose(arm)
    bpy.context.view_layer.update()
    depths = _bind_depths(arm, roles)

    arm.animation_data_create()
    action = bpy.data.actions.new(name="GroundTruthJoints")
    arm.animation_data.action = action

    frame_reports = []
    max_seen = 0.0
    for fr in frames:
        fi = int(fr["frameIndex"])
        sw = float(fr["transform"]["srcWidth"])
        sh = float(fr["transform"]["srcHeight"])
        _clear_pose(arm)
        # Keep camera root yaw from setup_pose_camera.
        bpy.context.view_layer.update()
        targets = _unproject_frame(scene, cam, fr["joints"], depths, sw, sh)
        _apply_targets(arm, targets)
        bpy.context.view_layer.update()

        # Keyframe all pose channels used.
        scene.frame_set(fi + 1)
        for pb in arm.pose.bones:
            pb.keyframe_insert(data_path="location", frame=fi + 1)
            pb.keyframe_insert(data_path="rotation_euler", frame=fi + 1)
            pb.keyframe_insert(data_path="scale", frame=fi + 1)

        errs = _measure_errors(arm, scene, cam, fr["joints"], roles, sw, sh)
        worst = max(errs.values()) if errs else 0.0
        max_seen = max(max_seen, worst)
        frame_reports.append(
            {
                "frameIndex": fi,
                "lossPx": float(np.mean(list(errs.values()))),
                "maxErrorPx": worst,
                "perJointErrorPx": errs,
            }
        )
        print(
            f"[gt-joints] frame {fi} mean={frame_reports[-1]['lossPx']:.3f} "
            f"max={worst:.3f}",
            flush=True,
        )
        if worst > max_err:
            offenders = {k: v for k, v in errs.items() if v > max_err}
            raise RuntimeError(
                f"ground-truth fail-closed: frame {fi} maxErrorPx={worst:.3f} "
                f"> {max_err} offenders={offenders}"
            )

    # Export posed GLB (animated).
    glb_path = out_dir / f"{job.get('clipId', 'clip')}_ground_truth_joints.glb"
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
        "method": "ground_truth_joints",
        "frameCount": len(frames),
        "maxErrorPxLimit": max_err,
        "maxErrorPxObserved": max_seen,
        "meanLossPx": float(np.mean([f["lossPx"] for f in frame_reports])),
        "frames": frame_reports,
        "exportGlb": str(glb_path).replace("\\", "/"),
        "camera": job.get("camera"),
        "proof": (
            "generated artifact validated — authored 2D landmarks driven exactly "
            f"(per-joint error ≤ {max_err}px); not OE runtime"
        ),
    }
    (out_dir / "fit_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out_dir / "job.resolved.json").write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "meanLossPx": report["meanLossPx"], "maxErrorPx": max_seen, "glb": report["exportGlb"]}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        raise
