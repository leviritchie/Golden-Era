#!/usr/bin/env python3
"""
Blender constrained 2D-reprojection pose fit from DWPose keypoints.

  blender -b --python blender_fit_from_keypoints.py -- --job job.json --keypoints keypoints.json --roles bone_roles.json
"""
from __future__ import annotations

import json
import math
import sys
import traceback
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Vector


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


def _clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _import_master(glb: Path):
    bpy.ops.import_scene.gltf(filepath=str(glb))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    return arm, mesh


def _setup_camera(job: dict, arm) -> bpy.types.Object:
    cam_data = bpy.data.cameras.new("PoseFitCam")
    cam_data.type = "ORTHO"
    cam = bpy.data.objects.new("PoseFitCam", cam_data)
    bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    cfg = job.get("camera", {})
    distance = float(cfg.get("distance", 3.0))
    height = float(cfg.get("height", 0.85))
    ortho_scale = float(cfg.get("orthoScale", 2.6))
    axis = str(cfg.get("axis", "-X")).upper()
    if axis == "-X":
        cam.location = Vector((-distance, 0.0, height))
        cam.rotation_euler = Euler((math.pi / 2.0, 0.0, -math.pi / 2.0), "XYZ")
    elif axis == "+X":
        cam.location = Vector((distance, 0.0, height))
        cam.rotation_euler = Euler((math.pi / 2.0, 0.0, math.pi / 2.0), "XYZ")
    else:
        raise RuntimeError(f"unsupported camera.axis={axis}")
    cam_data.ortho_scale = ortho_scale
    yaw = float(cfg.get("rootYawDeg", 0.0))
    if abs(yaw) > 1e-6:
        arm.rotation_mode = "XYZ"
        arm.rotation_euler[2] = math.radians(yaw)
    return cam


def _clear_animation(arm) -> None:
    if arm.animation_data is not None:
        arm.animation_data_clear()


def _collect_rest(arm, names: list[str]) -> dict[str, Euler]:
    out = {}
    for name in names:
        pb = arm.pose.bones.get(name)
        if pb is None:
            raise RuntimeError(f"missing bone {name}")
        pb.rotation_mode = "XYZ"
        out[name] = pb.rotation_euler.copy()
    return out


def _apply_deltas(arm, rest: dict[str, Euler], names: list[str], vec: np.ndarray) -> None:
    for i, name in enumerate(names):
        pb = arm.pose.bones[name]
        pb.rotation_mode = "XYZ"
        base = rest[name]
        o = i * 3
        pb.rotation_euler = Euler(
            (base.x + float(vec[o]), base.y + float(vec[o + 1]), base.z + float(vec[o + 2])),
            "XYZ",
        )


def _project_bone_heads(arm, bone_names: list[str], cam, scene) -> dict[str, tuple[float, float]]:
    """Project bone head world positions to normalized 0..1 image coords (top-left origin)."""
    from bpy_extras.object_utils import world_to_camera_view

    out = {}
    for name in bone_names:
        pb = arm.pose.bones[name]
        # Head in armature space → world
        head_world = arm.matrix_world @ pb.head
        co = world_to_camera_view(scene, cam, head_world)
        # co.x/y in 0..1 bottom-left; convert to top-left pixel-normalized
        out[name] = (float(co.x), float(1.0 - co.y))
    return out


def _sprite_targets_norm(frame_joints: dict, roles: dict, sprite_w: float, sprite_h: float) -> dict[str, tuple[float, float, float]]:
    """Map OpenPose joint → (nx, ny, score) in 0..1 top-left normalized sprite space for role bones."""
    joint_to_bone = roles["joints"]
    weights = roles.get("jointWeights") or {}
    out = {}
    for joint_name, bone_name in joint_to_bone.items():
        if joint_name not in roles.get("primaryJoints", joint_to_bone.keys()):
            continue
        j = frame_joints.get(joint_name)
        if not j or not j.get("visible", False):
            continue
        nx = float(j["x"]) / sprite_w
        ny = float(j["y"]) / sprite_h
        score = float(j["score"]) * float(weights.get(joint_name, 1.0))
        # Prefer WeaponTip over RWrist when both map to the same bone.
        if bone_name in out and joint_name != "WeaponTip":
            continue
        out[bone_name] = (nx, ny, score)
    return out


def _root_normalize(points: np.ndarray, root_idx: int, scale_idx: int) -> np.ndarray:
    """
    Translate by root joint and scale by distance(root, scale_idx joint).
    points: (N,2)
    """
    root = points[root_idx]
    p = points - root
    span = float(np.linalg.norm(p[scale_idx]))
    if span < 1e-6:
        span = 1.0
    return p / span


def _optimize_frame(
    *,
    arm,
    cam,
    scene,
    rest,
    names,
    targets_norm: dict[str, tuple[float, float, float]],
    x0: np.ndarray,
    job: dict,
    frame_index: int,
    roles: dict,
) -> tuple[np.ndarray, float, dict]:
    from scipy.optimize import minimize

    opt = job.get("keypointOptimizer", job.get("optimizer", {}))
    bound = float(opt.get("boundRad", math.radians(40)))
    rest_w = float(opt.get("restWeight", 0.05))
    maxiter = int(opt.get("maxiter", 200))
    maxfev = int(opt.get("maxfev", 800))

    bone_names = list(targets_norm.keys())
    # Prefer MidHip as root and Neck as scale reference when present.
    joint_to_bone = roles.get("joints", {})
    root_bone = joint_to_bone.get("MidHip")
    scale_bone = joint_to_bone.get("Neck") or joint_to_bone.get("Nose")
    if root_bone not in bone_names:
        root_bone = bone_names[0]
    if scale_bone not in bone_names or scale_bone == root_bone:
        scale_bone = bone_names[min(1, len(bone_names) - 1)]
    root_idx = bone_names.index(root_bone)
    scale_idx = bone_names.index(scale_bone)

    tgt = np.array([[targets_norm[b][0], targets_norm[b][1]] for b in bone_names], dtype=np.float64)
    tw = np.array([max(0.05, targets_norm[b][2]) for b in bone_names], dtype=np.float64)
    tgt_n = _root_normalize(tgt, root_idx, scale_idx)

    def objective(vec: np.ndarray) -> float:
        if np.any(np.abs(vec) > bound * 1.05):
            return 50.0 + float(np.sum(np.clip(np.abs(vec) - bound, 0, None)))
        _apply_deltas(arm, rest, names, vec)
        bpy.context.view_layer.update()
        proj_map = _project_bone_heads(arm, bone_names, cam, scene)
        pred = np.array([proj_map[b] for b in bone_names], dtype=np.float64)
        pred_n = _root_normalize(pred, root_idx, scale_idx)
        err = float(np.sum(tw * np.sum((pred_n - tgt_n) ** 2, axis=1)) / (float(np.sum(tw)) + 1e-8))
        err += rest_w * float(np.mean(vec ** 2))
        return err

    x = np.clip(np.array(x0, dtype=np.float64, copy=True), -bound, bound)
    best0 = float(objective(x))
    rng = np.random.default_rng(int(opt.get("seed", 7)) + frame_index * 13)
    candidates = [x]
    for _ in range(int(opt.get("restarts", 5))):
        candidates.append(rng.uniform(-bound * 0.7, bound * 0.7, size=x.shape))

    best_x = x
    best = best0
    total_fev = 0
    for cand in candidates:
        result = minimize(
            objective,
            np.clip(cand, -bound, bound),
            method="L-BFGS-B",
            bounds=[(-bound, bound)] * len(x),
            options={"maxiter": maxiter, "maxfun": maxfev, "ftol": 1e-10},
        )
        total_fev += int(getattr(result, "nfev", 0))
        xx = np.clip(np.asarray(result.x, dtype=np.float64), -bound, bound)
        val = float(objective(xx))
        if val < best:
            best = val
            best_x = xx

    print(
        f"[kpt-fit] frame {frame_index} loss={best:.5f} start={best0:.5f} evals~{total_fev}",
        flush=True,
    )
    return best_x, best, {"startLoss": best0, "nfev": total_fev}


def _bake_action(arm, rest, names, pose_vectors, root_yaw_deg: float) -> None:
    _clear_animation(arm)
    arm.animation_data_create()
    action = bpy.data.actions.new(name="KeypointFit")
    arm.animation_data.action = action
    arm.rotation_mode = "XYZ"
    for i, vec in enumerate(pose_vectors):
        frame = i + 1
        bpy.context.scene.frame_set(frame)
        _apply_deltas(arm, rest, names, np.asarray(vec, dtype=np.float64))
        arm.rotation_euler[2] = math.radians(root_yaw_deg)
        for name in names:
            arm.pose.bones[name].keyframe_insert(data_path="rotation_euler", frame=frame)
        arm.keyframe_insert(data_path="rotation_euler", frame=frame)


def run(job_path: Path, keypoints_path: Path, roles_path: Path) -> dict:
    job = json.loads(job_path.read_text(encoding="utf-8"))
    kpt_report = json.loads(keypoints_path.read_text(encoding="utf-8"))
    roles = json.loads(roles_path.read_text(encoding="utf-8"))
    if not kpt_report.get("ok"):
        raise RuntimeError(f"keypoints not ok: {keypoints_path}")

    out_dir = Path(job["outputDir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    _clear_scene()
    arm, mesh = _import_master(Path(job["masterGlb"]))
    _clear_animation(arm)
    cam = _setup_camera(job, arm)
    scene = bpy.context.scene

    names = list(roles.get("optimizeBones") or job.get("optimizeBones") or [])
    if not names:
        raise RuntimeError("optimizeBones empty")
    rest = _collect_rest(arm, names)

    # Align sprite aspect into camera framing: use first frame sprite size for norm.
    frames = sorted(kpt_report["frames"], key=lambda f: f["frameIndex"])
    pose_vectors: list[np.ndarray] = []
    losses: list[float] = []
    frame_reports = []
    x = np.zeros(len(names) * 3, dtype=np.float64)
    root_yaw = float(job.get("camera", {}).get("rootYawDeg", 0.0))

    for fr in frames:
        i = int(fr["frameIndex"])
        sw = float(fr["transform"]["srcWidth"])
        sh = float(fr["transform"]["srcHeight"])
        targets = _sprite_targets_norm(fr["joints"], roles, sw, sh)
        if len(targets) < 4:
            raise RuntimeError(f"frame {i}: too few visible mapped joints ({len(targets)})")
        _clear_animation(arm)
        scene.frame_set(1)
        x, best, stats = _optimize_frame(
            arm=arm,
            cam=cam,
            scene=scene,
            rest=rest,
            names=names,
            targets_norm=targets,
            x0=x,
            job=job,
            frame_index=i,
            roles=roles,
        )
        pose_vectors.append(np.array(x, dtype=np.float64, copy=True))
        losses.append(best)
        frame_reports.append({"frameIndex": i, "loss": best, **stats, "targetCount": len(targets)})

    _bake_action(arm, rest, names, pose_vectors, root_yaw)
    scene.frame_start = 1
    scene.frame_end = len(pose_vectors)
    scene.render.fps = int(round(float(job.get("fps", 12))))

    export_glb = out_dir / f"{job.get('clipId', 'clip')}_kpt_fitted.glb"
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.gltf(
        filepath=str(export_glb),
        export_format="GLB",
        use_selection=True,
        export_animations=True,
        export_force_sampling=True,
        export_nla_strips=False,
        export_apply=False,
    )

    # Also write pose vectors for textured preview (uses master GLB + vectors).
    report = {
        "unitSid": job.get("unitSid"),
        "clipId": job.get("clipId"),
        "method": job.get("method", "keypoint_reprojection"),
        "frameCount": len(pose_vectors),
        "losses": losses,
        "meanLoss": float(np.mean(losses)) if losses else None,
        "poseVectors": [v.tolist() for v in pose_vectors],
        "optimizeBones": names,
        "exportGlb": str(export_glb).replace("\\", "/"),
        "frames": frame_reports,
        "proof": "generated artifact validated — keypoint reprojection fit; not OE runtime proven",
    }
    report_path = out_dir / "fit_report_kpt.json"
    # Compatibility: also overwrite fit_report.json so render_preview can reuse it.
    (out_dir / "fit_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(report_path)}, indent=2), flush=True)
    return report


def main() -> int:
    try:
        opts = _parse()
        run(opts["job"], opts["keypoints"], opts["roles"])
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
