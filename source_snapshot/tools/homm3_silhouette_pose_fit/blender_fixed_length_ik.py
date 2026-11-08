#!/usr/bin/env python3
"""Fixed-length skeletal IK: rotate-only bones (armor-suit LBS).

Uses roles.jointSites so Nose/WeaponTip track sprite-analog mesh points
(head_end / farthest RightHand-skinned tip), not skull-base / hand-tail.

Blender:
  blender -b --python blender_fixed_length_ik.py -- \\
    --job job.resolved.json --keypoints kp.json --roles roles.json
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

_TOOL = Path(__file__).resolve().parent
if str(_TOOL) not in sys.path:
    sys.path.insert(0, str(_TOOL))
from blender_ground_truth_joints import (  # noqa: E402
    _bind_depths,
    _clear_pose,
    _disable_inherit_scale,
    _measure_errors,
    _register_camera_scale,
    _unproject_frame,
)
from homm3_landmark_sites import cache_tip_bind_local, landmark_world  # noqa: E402
from homm3_pose_camera import setup_pose_camera  # noqa: E402

DEFAULT_FOOT_BONES = ["LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase"]


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


def _ground_anchor_settings(cfg: dict) -> tuple[str, list[str]]:
    raw = cfg.get("groundAnchor")
    if not raw:
        return "off", list(DEFAULT_FOOT_BONES)
    if isinstance(raw, str):
        mode = raw
        bones = list(DEFAULT_FOOT_BONES)
    elif isinstance(raw, dict):
        mode = str(raw.get("mode") or "off")
        bones = list(raw.get("bones") or DEFAULT_FOOT_BONES)
    else:
        raise RuntimeError(f"fixedLengthIk.groundAnchor must be str or object, got {type(raw)}")
    if mode in {"lowest_foot", "frame0_lateral_lowest_foot"} and not bones:
        bones = list(DEFAULT_FOOT_BONES)
    return mode, bones


def _min_foot_world_z(arm, bone_names: list[str]) -> float:
    zs: list[float] = []
    for name in bone_names:
        pb = arm.pose.bones.get(name)
        if pb is None:
            continue
        head = arm.matrix_world @ pb.head
        tail = arm.matrix_world @ pb.tail
        zs.append(float(min(head.z, tail.z)))
    if not zs:
        raise RuntimeError(
            f"groundAnchor lowest_foot: none of bones present on armature: {bone_names}"
        )
    return float(min(zs))


def _apply_frame0_lateral_plant(
    arm,
    foot_bones: list[str],
    *,
    ground_z: float,
    loc0_xy: tuple[float, float],
) -> dict[str, float]:
    """Plant lowest foot on ground_z; pin armature world XY to frame0."""
    bpy.context.view_layer.update()
    z_before = _min_foot_world_z(arm, foot_bones)
    dz = float(ground_z) - z_before
    arm.location = Vector(
        (float(loc0_xy[0]), float(loc0_xy[1]), float(arm.location.z + dz))
    )
    bpy.context.view_layer.update()
    z_after = _min_foot_world_z(arm, foot_bones)
    return {
        "zBefore": float(z_before),
        "zAfter": float(z_after),
        "deltaZ": float(dz),
        "groundZ": float(ground_z),
    }


def _bake_pose_eulers(arm) -> None:
    """Sync rotation_euler from matrix_basis after CCD writes via pb.matrix."""
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
        basis = pb.matrix_basis
        pb.rotation_euler = basis.to_euler("XYZ")
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def _capture_pose(arm) -> dict:
    _bake_pose_eulers(arm)
    return {
        "location": [float(arm.location.x), float(arm.location.y), float(arm.location.z)],
        "eulers": {
            pb.name: [
                float(pb.rotation_euler.x),
                float(pb.rotation_euler.y),
                float(pb.rotation_euler.z),
            ]
            for pb in arm.pose.bones
        },
    }


def _apply_captured_pose(arm, pose: dict) -> None:
    loc = pose["location"]
    arm.location = Vector((float(loc[0]), float(loc[1]), float(loc[2])))
    eulers = pose["eulers"]
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
        eul = eulers.get(pb.name)
        if eul is None:
            pb.rotation_euler = (0.0, 0.0, 0.0)
        else:
            pb.rotation_euler = (float(eul[0]), float(eul[1]), float(eul[2]))
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def _gaussian_kernel(radius: int, sigma: float) -> np.ndarray:
    xs = np.arange(-radius, radius + 1, dtype=np.float64)
    k = np.exp(-0.5 * (xs / max(sigma, 1e-6)) ** 2)
    k /= float(np.sum(k))
    return k


def _smooth_pose_eulers(
    poses: list[dict],
    *,
    sigma: float,
    include_bones: list[str] | None = None,
    exclude_bones: list[str] | None = None,
) -> list[dict]:
    """Gaussian-smooth selected bone Euler channels. Locations unchanged."""
    if sigma <= 0.0 or len(poses) < 2:
        return [dict(p) for p in poses]
    all_names = sorted(poses[0]["eulers"].keys())
    include = set(include_bones) if include_bones else set(all_names)
    exclude = set(exclude_bones or [])
    names = [n for n in all_names if n in include and n not in exclude]
    if not names:
        return [dict(p) for p in poses]
    n = len(poses)
    radius = max(1, int(round(sigma * 2)))
    kernel = _gaussian_kernel(radius, sigma)
    data = np.zeros((n, len(names), 3), dtype=np.float64)
    for t, pose in enumerate(poses):
        for j, name in enumerate(names):
            data[t, j] = np.asarray(pose["eulers"][name], dtype=np.float64)
    out = data.copy()
    for j in range(len(names)):
        for c in range(3):
            padded = np.pad(data[:, j, c], (radius, radius), mode="edge")
            out[:, j, c] = np.convolve(padded, kernel, mode="valid")
    smoothed: list[dict] = []
    for t, pose in enumerate(poses):
        eulers = {k: list(v) for k, v in pose["eulers"].items()}
        for j, name in enumerate(names):
            eulers[name] = [float(out[t, j, 0]), float(out[t, j, 1]), float(out[t, j, 2])]
        smoothed.append({"location": list(pose["location"]), "eulers": eulers})
    return smoothed


def _align_root_midhip(arm, midhip_w: Vector) -> None:
    bpy.context.view_layer.update()
    cur = arm.matrix_world @ arm.pose.bones["Hips"].head
    arm.location = arm.location + (midhip_w - cur)
    bpy.context.view_layer.update()


def _quat_cap(q: Quaternion, max_ang: float) -> Quaternion:
    if q.angle <= max_ang:
        return q
    return Quaternion(q.axis, max_ang)


def _rotate_about_head(arm, bone_name: str, q: Quaternion) -> None:
    pb = arm.pose.bones[bone_name]
    head = arm.matrix_world @ pb.head
    mw = arm.matrix_world @ pb.matrix
    R = q.to_matrix().to_4x4()
    new_world = Matrix.Translation(head) @ R @ Matrix.Translation(-head) @ mw
    pb.matrix = arm.matrix_world.inverted() @ new_world
    bpy.context.view_layer.update()
    pb.location = (0.0, 0.0, 0.0)
    pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def _ccd_effector(
    arm,
    bone_names: list[str],
    end_target_w: Vector,
    effector_fn,
    *,
    iterations: int = 28,
    max_step_deg: float = 22.0,
    prefer_up: Vector | None = None,
    prefer_up_weight: float = 0.0,
    prefer_up_bones: set[str] | None = None,
) -> None:
    """CCD rotating bones so effector_fn() approaches end_target_w.

    When prefer_up is set, blend a fraction of each step toward aligning the bone
    axis (head→tail) with prefer_up — keeps Head from folding into camera depth.
    """
    max_step = math.radians(max_step_deg)
    up_bones = prefer_up_bones or set()
    for _ in range(iterations):
        tip = effector_fn()
        if (tip - end_target_w).length < 1e-3:
            break
        for bname in reversed(bone_names):
            pb = arm.pose.bones[bname]
            pivot = arm.matrix_world @ pb.head
            cur = effector_fn()
            v0 = cur - pivot
            v1 = end_target_w - pivot
            if v0.length < 1e-8 or v1.length < 1e-8:
                continue
            q = v0.normalized().rotation_difference(v1.normalized())
            if (
                prefer_up is not None
                and prefer_up_weight > 0.0
                and bname in up_bones
            ):
                axis = (arm.matrix_world @ pb.tail) - pivot
                if axis.length > 1e-8:
                    q_up = axis.normalized().rotation_difference(prefer_up.normalized())
                    # Partial blend: keep tip aim dominant, bias away from depth fold.
                    q = q.slerp(q_up, float(prefer_up_weight))
            if q.angle < 1e-5:
                continue
            q = _quat_cap(q, max_step)
            _rotate_about_head(arm, bname, q)


def _camera_up_world(cam) -> Vector:
    """World-space camera up (billboard 'sky' direction)."""
    return (cam.matrix_world.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()


def _camera_forward_world(cam) -> Vector:
    """World-space camera look direction (−Z in Blender camera local)."""
    return (cam.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()


def _unwrap_head_depth_fold(
    arm,
    mesh,
    roles: dict,
    tip_cache: dict,
    prefer_up: Vector,
    *,
    cam_forward: Vector | None = None,
    max_twist_deg: float = 90.0,
) -> None:
    """Twist Head around the pivot→Nose axis so the skull is upright without moving the tip.

    CCD alone can fold Head into camera depth while still hitting Nose in screen space.
    Rotating about the tip-preserving axis unwraps that fold.
    """
    if "Head" not in arm.pose.bones:
        return
    pb = arm.pose.bones["Head"]
    pivot = arm.matrix_world @ pb.head
    tip = landmark_world(arm, mesh, roles, "Nose", tip_cache=tip_cache)
    tip_axis = tip - pivot
    if tip_axis.length < 1e-6:
        return
    tip_axis.normalize()
    bone_axis = (arm.matrix_world @ pb.tail) - pivot
    if bone_axis.length < 1e-6:
        return
    bone_axis.normalize()

    # Project prefer_up onto plane perpendicular to tip_axis (pole target).
    up = prefer_up.normalized()
    up_proj = up - tip_axis * up.dot(tip_axis)
    bone_proj = bone_axis - tip_axis * bone_axis.dot(tip_axis)
    if up_proj.length < 1e-6 or bone_proj.length < 1e-6:
        return
    up_proj.normalize()
    bone_proj.normalize()

    # Always unwrap toward camera-up on the tip-preserving axis.
    # (Previously gated on |bone·cam_forward|; that missed many sunk-skull frames.)
    q = bone_proj.rotation_difference(up_proj)
    if q.angle < 1e-4:
        return
    max_rad = math.radians(max_twist_deg)
    if q.angle > max_rad:
        q = _quat_cap(q, max_rad)
    _rotate_about_head(arm, "Head", q)
    bpy.context.view_layer.update()


def _pose_frame(
    arm,
    mesh,
    roles: dict,
    targets: dict[str, Vector],
    tip_cache: dict,
    *,
    prefer_up: Vector | None = None,
    cam_forward: Vector | None = None,
) -> None:
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()

    _align_root_midhip(arm, targets["MidHip"])

    def eff_nose():
        return landmark_world(arm, mesh, roles, "Nose", tip_cache=tip_cache)

    def eff_tip():
        return landmark_world(arm, mesh, roles, "WeaponTip", tip_cache=tip_cache)

    def eff_bone_head(name: str):
        return arm.matrix_world @ arm.pose.bones[name].head

    def eff_bone_tail(name: str):
        return arm.matrix_world @ arm.pose.bones[name].tail

    # Spine to Neck (neck bone head).
    _ccd_effector(
        arm,
        ["Spine02", "Spine01", "Spine", "neck"],
        targets["Neck"],
        lambda: eff_bone_head("neck"),
        iterations=20,
    )
    # Head chain: aim crown at Nose (tip-accurate CCD), then unwrap depth fold.
    _ccd_effector(
        arm,
        ["neck", "Head"],
        targets["Nose"],
        eff_nose,
        iterations=28,
    )
    _ccd_effector(
        arm,
        ["Head"],
        targets["Nose"],
        eff_nose,
        iterations=12,
    )
    if prefer_up is not None:
        _unwrap_head_depth_fold(
            arm,
            mesh,
            roles,
            tip_cache,
            prefer_up,
            cam_forward=cam_forward,
        )
        # Recover Nose after twist (tip may drift slightly on skinned landmark).
        _ccd_effector(
            arm,
            ["Head"],
            targets["Nose"],
            eff_nose,
            iterations=8,
        )

    # Legs → ankles; soft knee via Leg head.
    for bones, knee_j, ankle_j in (
        (["RightUpLeg", "RightLeg", "RightFoot"], "RKnee", "RAnkle"),
        (["LeftUpLeg", "LeftLeg", "LeftFoot"], "LKnee", "LAnkle"),
    ):
        _ccd_effector(
            arm,
            bones,
            targets[ankle_j],
            lambda bn=bones[-1]: eff_bone_head(bn),
            iterations=24,
        )
        _ccd_effector(
            arm,
            bones[:2],
            targets[knee_j],
            lambda bn=bones[1]: eff_bone_head(bn),
            iterations=12,
        )
        _ccd_effector(
            arm,
            bones,
            targets[ankle_j],
            lambda bn=bones[-1]: eff_bone_head(bn),
            iterations=12,
        )

    # Arms → wrists, then tip / left aim.
    for bones, el_j, wr_j, tip_j in (
        (
            ["RightShoulder", "RightArm", "RightForeArm", "RightHand"],
            "RElbow",
            "RWrist",
            "WeaponTip",
        ),
        (
            ["LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand"],
            "LElbow",
            "LWrist",
            None,
        ),
    ):
        _ccd_effector(
            arm,
            bones,
            targets[wr_j],
            lambda bn=bones[-1]: eff_bone_head(bn),
            iterations=24,
        )
        _ccd_effector(
            arm,
            bones[:3],
            targets[el_j],
            lambda bn=bones[2]: eff_bone_head(bn),
            iterations=12,
        )
        _ccd_effector(
            arm,
            bones,
            targets[wr_j],
            lambda bn=bones[-1]: eff_bone_head(bn),
            iterations=12,
        )
        if tip_j is not None:
            _ccd_effector(arm, bones, targets[tip_j], eff_tip, iterations=28)
        else:
            _ccd_effector(
                arm,
                bones,
                targets[wr_j] + (targets[wr_j] - targets[el_j]),
                lambda bn=bones[-1]: eff_bone_tail(bn),
                iterations=8,
            )

    for pb in arm.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def _refine_head_after_plant(
    arm,
    mesh,
    roles: dict,
    targets: dict[str, Vector],
    tip_cache: dict,
    *,
    prefer_up: Vector | None = None,
    cam_forward: Vector | None = None,
) -> None:
    """Re-aim neck/head so Nose (head_end) tracks the authored target after a root plant.

    Only rotates neck/Head — does not touch smoothed spine/hip bones.
    """

    def eff_nose():
        return landmark_world(arm, mesh, roles, "Nose", tip_cache=tip_cache)

    def eff_bone_head(name: str):
        return arm.matrix_world @ arm.pose.bones[name].head

    _ccd_effector(
        arm,
        ["neck"],
        targets["Neck"],
        lambda: eff_bone_head("neck"),
        iterations=12,
    )
    _ccd_effector(
        arm,
        ["neck", "Head"],
        targets["Nose"],
        eff_nose,
        iterations=24,
    )
    if prefer_up is not None:
        _unwrap_head_depth_fold(
            arm,
            mesh,
            roles,
            tip_cache,
            prefer_up,
            cam_forward=cam_forward,
        )
        _ccd_effector(
            arm,
            ["Head"],
            targets["Nose"],
            eff_nose,
            iterations=8,
        )
    for pb in arm.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def _refine_arms_after_plant(arm, mesh, roles: dict, targets: dict[str, Vector], tip_cache: dict) -> None:
    """Re-aim arms/tip after a root plant so weapon aim tracks world targets again."""

    def eff_tip():
        return landmark_world(arm, mesh, roles, "WeaponTip", tip_cache=tip_cache)

    def eff_bone_head(name: str):
        return arm.matrix_world @ arm.pose.bones[name].head

    def eff_bone_tail(name: str):
        return arm.matrix_world @ arm.pose.bones[name].tail

    for bones, el_j, wr_j, tip_j in (
        (
            ["RightShoulder", "RightArm", "RightForeArm", "RightHand"],
            "RElbow",
            "RWrist",
            "WeaponTip",
        ),
        (
            ["LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand"],
            "LElbow",
            "LWrist",
            None,
        ),
    ):
        _ccd_effector(
            arm,
            bones,
            targets[wr_j],
            lambda bn=bones[-1]: eff_bone_head(bn),
            iterations=16,
        )
        _ccd_effector(
            arm,
            bones[:3],
            targets[el_j],
            lambda bn=bones[2]: eff_bone_head(bn),
            iterations=8,
        )
        _ccd_effector(
            arm,
            bones,
            targets[wr_j],
            lambda bn=bones[-1]: eff_bone_head(bn),
            iterations=8,
        )
        if tip_j is not None:
            _ccd_effector(arm, bones, targets[tip_j], eff_tip, iterations=20)
        else:
            _ccd_effector(
                arm,
                bones,
                targets[wr_j] + (targets[wr_j] - targets[el_j]),
                lambda bn=bones[-1]: eff_bone_tail(bn),
                iterations=6,
            )
    for pb in arm.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def _refine_upper_after_plant(
    arm,
    mesh,
    roles: dict,
    targets: dict[str, Vector],
    tip_cache: dict,
    *,
    prefer_up: Vector | None = None,
    cam_forward: Vector | None = None,
) -> None:
    """Re-aim head then arms after foot plant (plant translates the whole armature)."""
    _refine_head_after_plant(
        arm,
        mesh,
        roles,
        targets,
        tip_cache,
        prefer_up=prefer_up,
        cam_forward=cam_forward,
    )
    _refine_arms_after_plant(arm, mesh, roles, targets, tip_cache)


def main() -> int:
    opts = _parse()
    job = json.loads(opts["job"].read_text(encoding="utf-8"))
    kpt = json.loads(opts["keypoints"].read_text(encoding="utf-8"))
    roles = json.loads(opts["roles"].read_text(encoding="utf-8"))
    cfg = job.get("fixedLengthIk") or {}
    register_cam = bool(cfg.get("frame0CameraRegister", True))
    ga_mode, ga_bones = _ground_anchor_settings(cfg)
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
    nose_site = (roles.get("jointSites") or {}).get("Nose") or {}
    if nose_site.get("mode") in ("farthest_skinned_vert", "highest_skinned_vert"):
        if "Nose" not in tip_cache:
            raise RuntimeError("Nose skinned site failed to cache crown/snout vert")
        crown_d = float(tip_cache["Nose"]["bindDist"])
        if crown_d < 0.12:
            raise RuntimeError(
                f"Nose crown bindDist too small ({crown_d:.3f}) — Head skin site is not crown/snout"
            )
    elif str(nose_site.get("bone") or "") == "head_end" and "head_end" not in arm.pose.bones:
        raise RuntimeError("roles.jointSites.Nose needs head_end bone on this master")

    print(
        f"[fixed-ik] tipCache vert={tip_cache.get('vertIndex')} "
        f"bindDist={tip_cache.get('bindDist'):.3f} "
        f"noseSite={nose_site.get('mode') or nose_site.get('bone')} "
        f"noseBindDist={(tip_cache.get('Nose') or {}).get('bindDist')}",
        flush=True,
    )
    if ga_mode != "off":
        print(f"[fixed-ik] groundAnchor={ga_mode} bones={ga_bones}", flush=True)
    if post_smooth_sigma > 0.0:
        print(
            f"[fixed-ik] postSmoothSigma={post_smooth_sigma} "
            f"include={post_smooth_include} exclude={post_smooth_exclude}",
            flush=True,
        )

    scene = bpy.context.scene
    depths = _bind_depths(arm, roles, mesh=mesh, tip_cache=tip_cache)
    frames = sorted(kpt["frames"], key=lambda f: int(f["frameIndex"]))
    sw0 = float(frames[0]["transform"]["srcWidth"])
    sh0 = float(frames[0]["transform"]["srcHeight"])
    if register_cam:
        cam = _register_camera_scale(job, arm, scene, frames[0]["joints"], depths, sw0, sh0)
    else:
        cam = setup_pose_camera(job, arm, bpy_module=bpy)

    _clear_pose(arm)
    bpy.context.view_layer.update()
    tip_cache = cache_tip_bind_local(arm, mesh, roles)
    depths = _bind_depths(arm, roles, mesh=mesh, tip_cache=tip_cache)

    # Sanity: Nose site above Neck; tip far from wrist.
    nose_z = landmark_world(arm, mesh, roles, "Nose", tip_cache=tip_cache).z
    neck_z = landmark_world(arm, mesh, roles, "Neck", tip_cache=tip_cache).z
    if nose_z <= neck_z:
        raise RuntimeError(f"Nose site not above Neck (nose_z={nose_z:.3f} neck_z={neck_z:.3f})")
    tip_d = float(tip_cache["bindDist"])
    if tip_d < 0.25:
        raise RuntimeError(f"WeaponTip bindDist too small ({tip_d:.3f}) — not a blade tip")

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
        cam_forward = _camera_forward_world(cam)
        _pose_frame(
            arm,
            mesh,
            roles,
            targets,
            tip_cache,
            prefer_up=prefer_up,
            cam_forward=cam_forward,
        )

        for pb in arm.pose.bones:
            if max(abs(pb.scale.x - 1.0), abs(pb.scale.y - 1.0), abs(pb.scale.z - 1.0)) > 0.02:
                raise RuntimeError(f"scale nonzero on {pb.name}: {tuple(pb.scale)}")
            if pb.location.length > 1e-3:
                raise RuntimeError(f"location nonzero on {pb.name}: {tuple(pb.location)}")

        ga_stat: dict = {"mode": ga_mode}
        if ga_mode == "frame0_lateral_lowest_foot":
            if ground_z is None:
                ground_z = _min_foot_world_z(arm, ga_bones)
                loc0_xy = (float(arm.location.x), float(arm.location.y))
                ga_stat.update(
                    {
                        "groundZ": float(ground_z),
                        "loc0xy": [float(loc0_xy[0]), float(loc0_xy[1])],
                        "deltaZ": 0.0,
                        "role": "frame0_reference",
                    }
                )
            else:
                assert loc0_xy is not None
                ga_stat.update(
                    _apply_frame0_lateral_plant(
                        arm, ga_bones, ground_z=ground_z, loc0_xy=loc0_xy
                    )
                )
                _refine_upper_after_plant(
                    arm,
                    mesh,
                    roles,
                    targets,
                    tip_cache,
                    prefer_up=prefer_up,
                    cam_forward=cam_forward,
                )
                # Plant once more in case arm refine nudged skinned foot verts via root-only path (no-op expected).
                ga_stat["afterArmRefine"] = _apply_frame0_lateral_plant(
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
                _refine_upper_after_plant(
                    arm,
                    mesh,
                    roles,
                    targets,
                    tip_cache,
                    prefer_up=prefer_up,
                    cam_forward=cam_forward,
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
            raise RuntimeError(f"unsupported fixedLengthIk.groundAnchor.mode={ga_mode}")

        plant_stats.append({"frameIndex": fi, **ga_stat})
        frame_targets.append(targets)
        solved_poses.append(_capture_pose(arm))
        print(
            f"[fixed-ik] solved frame {fi} plant_dz={ga_stat.get('deltaZ', 0.0):+.4f}",
            flush=True,
        )

    if post_smooth_sigma > 0.0:
        solved_poses = _smooth_pose_eulers(
            solved_poses,
            sigma=post_smooth_sigma,
            include_bones=post_smooth_include,
            exclude_bones=post_smooth_exclude,
        )
        # Re-plant after Euler smooth so feet cannot drift underground.
        if ga_mode == "frame0_lateral_lowest_foot":
            if ground_z is None or loc0_xy is None:
                raise RuntimeError("postSmooth requires frame0 ground plant state")
            for i, pose in enumerate(solved_poses):
                _apply_captured_pose(arm, pose)
                stat = _apply_frame0_lateral_plant(
                    arm, ga_bones, ground_z=ground_z, loc0_xy=loc0_xy
                )
                _refine_upper_after_plant(
                    arm,
                    mesh,
                    roles,
                    frame_targets[i],
                    tip_cache,
                    prefer_up=_camera_up_world(cam),
                    cam_forward=_camera_forward_world(cam),
                )
                stat2 = _apply_frame0_lateral_plant(
                    arm, ga_bones, ground_z=ground_z, loc0_xy=loc0_xy
                )
                solved_poses[i] = _capture_pose(arm)
                plant_stats[i]["postSmoothPlant"] = stat
                plant_stats[i]["postSmoothPlantAfterArm"] = stat2
        elif ga_mode == "lowest_foot":
            if ground_z is None:
                raise RuntimeError("postSmooth requires groundZ")
            for i, pose in enumerate(solved_poses):
                _apply_captured_pose(arm, pose)
                z_before = _min_foot_world_z(arm, ga_bones)
                dz = float(ground_z) - z_before
                arm.location = Vector((arm.location.x, arm.location.y, arm.location.z + dz))
                bpy.context.view_layer.update()
                _refine_upper_after_plant(
                    arm,
                    mesh,
                    roles,
                    frame_targets[i],
                    tip_cache,
                    prefer_up=_camera_up_world(cam),
                    cam_forward=_camera_forward_world(cam),
                )
                z_before2 = _min_foot_world_z(arm, ga_bones)
                dz2 = float(ground_z) - z_before2
                arm.location = Vector((arm.location.x, arm.location.y, arm.location.z + dz2))
                bpy.context.view_layer.update()
                solved_poses[i] = _capture_pose(arm)
                plant_stats[i]["postSmoothPlant"] = {
                    "zBefore": float(z_before),
                    "zAfter": float(_min_foot_world_z(arm, ga_bones)),
                    "deltaZ": float(dz),
                    "groundZ": float(ground_z),
                }

    # Measure on live solved poses before any Action exists. Assigning an Action and
    # calling frame_set evaluates FCurves and would stomp a pose applied beforehand.
    frame_reports = []
    for fr, pose, ga_stat in zip(frames, solved_poses, plant_stats):
        fi = int(fr["frameIndex"])
        sw = float(fr["transform"]["srcWidth"])
        sh = float(fr["transform"]["srcHeight"])
        _apply_captured_pose(arm, pose)
        errs = _measure_errors(
            arm, scene, cam, fr["joints"], roles, sw, sh, mesh=mesh, tip_cache=tip_cache
        )
        body = {k: v for k, v in errs.items() if k != "WeaponTip"}
        frame_reports.append(
            {
                "frameIndex": fi,
                "lossPx": float(np.mean(list(errs.values()))),
                "bodyMeanLossPx": float(np.mean(list(body.values()))),
                "maxBodyErrorPx": float(max(body.values())),
                "tipErrorPx": float(errs.get("WeaponTip", 0.0)),
                "noseErrorPx": float(errs.get("Nose", 0.0)),
                "perJointErrorPx": errs,
                "groundAnchor": ga_stat,
                "minFootWorldZ": float(_min_foot_world_z(arm, ga_bones)),
            }
        )
        print(
            f"[fixed-ik] frame {fi} bodyMean={frame_reports[-1]['bodyMeanLossPx']:.1f} "
            f"nose={frame_reports[-1]['noseErrorPx']:.1f} "
            f"tip={frame_reports[-1]['tipErrorPx']:.1f} "
            f"footZ={frame_reports[-1]['minFootWorldZ']:.4f}",
            flush=True,
        )

    arm.animation_data_create()
    action = bpy.data.actions.new(name="FixedLengthIk")
    arm.animation_data.action = action
    for fr, pose in zip(frames, solved_poses):
        fi = int(fr["frameIndex"])
        scene.frame_set(fi + 1)
        _apply_captured_pose(arm, pose)  # after frame_set so eval cannot wipe it
        arm.keyframe_insert(data_path="location", frame=fi + 1)
        for pb in arm.pose.bones:
            pb.keyframe_insert(data_path="location", frame=fi + 1)
            pb.keyframe_insert(data_path="rotation_euler", frame=fi + 1)
            pb.keyframe_insert(data_path="scale", frame=fi + 1)

    glb_path = out_dir / f"{job.get('clipId', 'clip')}_fixed_length_ik.glb"
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
        "method": "fixed_length_ik_rotate_only",
        "tipCache": tip_cache,
        "jointSites": roles.get("jointSites"),
        "frameCount": len(frames),
        "meanBodyLossPx": float(np.mean([f["bodyMeanLossPx"] for f in frame_reports])),
        "meanNoseErrorPx": float(np.mean([f["noseErrorPx"] for f in frame_reports])),
        "meanTipErrorPx": float(np.mean([f["tipErrorPx"] for f in frame_reports])),
        "maxBodyErrorPx": float(max(f["maxBodyErrorPx"] for f in frame_reports)),
        "frames": frame_reports,
        "poseSnapshots": solved_poses,
        "groundAnchor": {
            "mode": ga_mode,
            "bones": ga_bones,
            "groundZ": ground_z,
            "loc0xy": list(loc0_xy) if loc0_xy is not None else None,
        },
        "postSmoothSigma": post_smooth_sigma,
        "postSmoothIncludeBones": post_smooth_include,
        "postSmoothExcludeBones": post_smooth_exclude,
        "exportGlb": str(glb_path).replace("\\", "/"),
        "camera": job.get("camera"),
        "proof": (
            "generated — rotate-only CCD; Nose=Head-skinned crown/snout site; "
            "WeaponTip=hand-skinned tip; "
            f"groundAnchor={ga_mode}; postSmoothSigma={post_smooth_sigma}; "
            "not exact stick match; not OE runtime"
        ),
    }
    (out_dir / "fit_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out_dir / "job.resolved.json").write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "meanBodyLossPx": report["meanBodyLossPx"],
                "meanNoseErrorPx": report["meanNoseErrorPx"],
                "meanTipErrorPx": report["meanTipErrorPx"],
                "groundAnchor": report["groundAnchor"],
                "postSmoothSigma": post_smooth_sigma,
                "postSmoothIncludeBones": post_smooth_include,
                "glb": report["exportGlb"],
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        raise
