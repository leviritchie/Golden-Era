#!/usr/bin/env python3
"""
Marker-driven IK pose fit: mesh surface points are primary, bone Eulers secondary.

Each frame:
  1. Start from the previous frame's solved pose (frame 0 = known-good bind).
  2. With the mesh in that pose, pick grab vertices by screen proximity to the
     *current* sprite landmarks (among verts skinned to the landmark's bones).
  3. Warp bone/root DOFs so those skinned vertices move toward the new targets.

So we never re-key grabs from bind/base on later frames — the previous mesh pose
is the assumption for "where is the tip/wrist on the model right now?"

Blender:
  blender -b --python blender_ik_markers.py -- --job job.json --keypoints kp.json --roles roles.json
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

_TOOL_DIR = Path(__file__).resolve().parent
ROOT = _TOOL_DIR.parent.parent
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))
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


def _clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _import_master(glb: Path):
    bpy.ops.import_scene.gltf(filepath=str(glb))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    # glTF re-splits UV seams on export; weld restores coherent edge connectivity
    # for Meshy masters that were cleaned with repair_meshy_prop_bridges.
    try:
        import bmesh

        bm = bmesh.new()
        bm.from_mesh(mesh.data)
        before = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-4)
        removed = before - len(bm.verts)
        bm.to_mesh(mesh.data)
        bm.free()
        mesh.data.update()
        if removed > 0:
            print(f"[marker-ik] weld-on-load removed {removed} duplicate verts", flush=True)
    except Exception as exc:
        raise RuntimeError(f"weld-on-load failed for {glb}: {exc}") from exc
    return arm, mesh


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


def _apply_pose(
    arm,
    rest: dict[str, Euler],
    names: list[str],
    vec: np.ndarray,
    *,
    root_rest: Vector,
    cam_axes: tuple[Vector, Vector, Vector],
    root_translate: bool,
) -> None:
    n_rot = len(names) * 3
    for i, name in enumerate(names):
        pb = arm.pose.bones[name]
        pb.rotation_mode = "XYZ"
        base = rest[name]
        o = i * 3
        pb.rotation_euler = Euler(
            (base.x + float(vec[o]), base.y + float(vec[o + 1]), base.z + float(vec[o + 2])),
            "XYZ",
        )
    if root_translate and len(vec) >= n_rot + 3:
        right, up, forward = cam_axes
        tr, tu, tf = float(vec[n_rot]), float(vec[n_rot + 1]), float(vec[n_rot + 2])
        arm.location = root_rest + right * tr + up * tu + forward * tf
    else:
        arm.location = Vector(root_rest)


def _bake_action(
    arm,
    rest: dict,
    names: list[str],
    pose_vectors: list[np.ndarray],
    *,
    root_rest: Vector,
    cam_axes: tuple[Vector, Vector, Vector],
    root_translate: bool,
    root_yaw_deg: float,
) -> None:
    _clear_animation(arm)
    arm.animation_data_create()
    action = bpy.data.actions.new(name="MarkerIkFit")
    arm.animation_data.action = action
    arm.rotation_mode = "XYZ"
    for i, vec in enumerate(pose_vectors):
        frame = i + 1
        bpy.context.scene.frame_set(frame)
        _apply_pose(
            arm,
            rest,
            names,
            np.asarray(vec, dtype=np.float64),
            root_rest=root_rest,
            cam_axes=cam_axes,
            root_translate=root_translate,
        )
        arm.rotation_euler[2] = math.radians(root_yaw_deg)
        for name in names:
            arm.pose.bones[name].keyframe_insert(data_path="rotation_euler", frame=frame)
        arm.keyframe_insert(data_path="rotation_euler", frame=frame)
        if root_translate:
            arm.keyframe_insert(data_path="location", frame=frame)


def _bone_end_world(arm, bone_name: str, end: str) -> Vector:
    pb = arm.pose.bones[bone_name]
    local = pb.tail if end == "tail" else pb.head
    return arm.matrix_world @ local


def _project_world_px(world: Vector, cam, scene, sw: float, sh: float) -> tuple[float, float]:
    from bpy_extras.object_utils import world_to_camera_view

    co = world_to_camera_view(scene, cam, world)
    return float(co.x) * sw, float(1.0 - co.y) * sh


def _group_index_map(mesh_obj) -> dict[str, int]:
    return {g.name: g.index for g in mesh_obj.vertex_groups}


def _skin_bones_for_joint(joint_name: str, role_bone: str, cfg: dict) -> list[str]:
    extras = dict(cfg.get("skinBoneExtras") or {})
    # Defaults for UniRig meshy46; Mixamo configs override via skinBoneExtras.
    extras.setdefault("WeaponTip", [role_bone])
    extras.setdefault("RWrist", [role_bone])
    extras.setdefault("LWrist", [role_bone])
    bones = [role_bone]
    for b in extras.get(joint_name, []):
        if b not in bones:
            bones.append(b)
    return bones




def _candidate_vert_indices(
    mesh_obj,
    bone_names: list[str],
    *,
    min_weight: float,
    group_map: dict[str, int],
) -> list[int]:
    group_ids = [group_map[b] for b in bone_names if b in group_map]
    if not group_ids:
        return []
    want = set(group_ids)
    out: list[int] = []
    for vi, v in enumerate(mesh_obj.data.vertices):
        wmax = 0.0
        for ge in v.groups:
            if ge.group in want:
                wmax = max(wmax, float(ge.weight))
        if wmax >= min_weight:
            out.append(vi)
    return out


def _index_to_group_name(mesh_obj) -> dict[int, str]:
    return {g.index: g.name for g in mesh_obj.vertex_groups}


def _vert_skin_influences(
    mesh_obj, vert_index: int, index_to_name: dict[int, str]
) -> list[tuple[str, float]]:
    v = mesh_obj.data.vertices[vert_index]
    infl: list[tuple[str, float]] = []
    for ge in v.groups:
        name = index_to_name.get(ge.group)
        if name is None:
            continue
        w = float(ge.weight)
        if w > 1e-6:
            infl.append((name, w))
    if not infl:
        raise RuntimeError(f"vertex {vert_index} has no skin weights")
    return infl


def _lbs_vert_world(arm, mesh_obj, bind_co: Vector, influences: list[tuple[str, float]]) -> Vector:
    """
    Linear-blend skinning for one bind-space vertex.
    Assumes the mesh is deformed by an Armature modifier on `arm` (UniRig master).
    """
    mesh_to_arm = arm.matrix_world.inverted() @ mesh_obj.matrix_world
    rest_arm = mesh_to_arm @ bind_co
    posed = Vector((0.0, 0.0, 0.0))
    wsum = 0.0
    for bone_name, w in influences:
        pb = arm.pose.bones.get(bone_name)
        if pb is None:
            continue
        deform = pb.matrix @ pb.bone.matrix_local.inverted()
        posed += w * (deform @ rest_arm)
        wsum += w
    if wsum <= 1e-8:
        raise RuntimeError("LBS weight sum is zero")
    if abs(wsum - 1.0) > 1e-3:
        posed /= wsum
    return arm.matrix_world @ posed


def _project_grabs_px(
    arm,
    mesh_obj,
    grabs: list[dict],
    cam,
    scene,
    sw: float,
    sh: float,
) -> np.ndarray:
    out = np.zeros((len(grabs), 2), dtype=np.float64)
    for i, g in enumerate(grabs):
        world = _lbs_vert_world(arm, mesh_obj, g["bind_co"], g["influences"])
        out[i, 0], out[i, 1] = _project_world_px(world, cam, scene, sw, sh)
    return out


def _grabs_from_markers(
    mesh_obj,
    markers: list[tuple[str, int, str, float]],
) -> list[dict]:
    index_to_name = _index_to_group_name(mesh_obj)
    grabs: list[dict] = []
    for jn, vi, bone, w in markers:
        bind_co = mesh_obj.data.vertices[vi].co.copy()
        influences = _vert_skin_influences(mesh_obj, vi, index_to_name)
        grabs.append(
            {
                "joint": jn,
                "vert": int(vi),
                "bone": bone,
                "weight": float(w),
                "bind_co": bind_co,
                "influences": influences,
            }
        )
    return grabs


def _project_mesh_markers_px(
    arm,
    mesh_obj,
    markers: list[tuple[str, int, str, float]],
    cam,
    scene,
    sw: float,
    sh: float,
) -> np.ndarray:
    """markers: (joint_name, vert_index, bone_name, weight). Uses LBS (fast)."""
    return _project_grabs_px(arm, mesh_obj, _grabs_from_markers(mesh_obj, markers), cam, scene, sw, sh)


def _sprite_targets(
    frame_joints: dict,
    roles: dict,
    cfg: dict,
) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Visible configured landmarks → names, targets Nx2, weights N."""
    joint_to_bone = roles["joints"]
    jw = roles.get("jointWeights") or {}
    wanted = list(cfg.get("markers") or roles.get("primaryJoints") or list(joint_to_bone.keys()))
    names: list[str] = []
    targets: list[list[float]] = []
    weights: list[float] = []
    for jn in wanted:
        if jn not in joint_to_bone:
            continue
        j = frame_joints.get(jn)
        if not j or not j.get("visible", False):
            continue
        names.append(jn)
        targets.append([float(j["x"]), float(j["y"])])
        weights.append(max(0.05, float(jw.get(jn, 1.0)) * float(j.get("score", 1.0))))
    if len(names) < 3:
        raise RuntimeError(f"need >=3 visible landmarks, got {len(names)}")
    return names, np.asarray(targets, dtype=np.float64), np.asarray(weights, dtype=np.float64)


def _vert_weight_on_bones(
    mesh_obj, vert_index: int, bone_names: list[str], group_map: dict[str, int]
) -> float:
    want = {group_map[b] for b in bone_names if b in group_map}
    if not want:
        return 0.0
    wmax = 0.0
    for ge in mesh_obj.data.vertices[vert_index].groups:
        if ge.group in want:
            wmax = max(wmax, float(ge.weight))
    return wmax


def _pick_mesh_markers_from_pose(
    *,
    mesh_obj,
    arm,
    cam,
    scene,
    joint_names: list[str],
    targets: np.ndarray,
    weights: np.ndarray,
    roles: dict,
    cfg: dict,
    sw: float,
    sh: float,
    prev_vert_by_joint: dict[str, int] | None,
) -> list[tuple[str, int, str, float]]:
    """
    Mesh must already be in the previous-frame pose.
    For each current sprite landmark, grab the skinned vertex nearest in screen
    space (among verts weighted to that landmark's bones). Prefer the previous
    frame's vertex when it is still competitive (temporal stickiness).
    WeaponTip can use tipPickMode=farthest_from_hand for attached mace props.
    """
    from bpy_extras.object_utils import world_to_camera_view

    min_w = float(cfg.get("minSkinWeight", 0.20))
    slack_px = float(cfg.get("preferPrevVertSlackPx", 14.0))
    tip_mode = str(cfg.get("tipPickMode", "screen_nearest"))
    group_map = _group_index_map(mesh_obj)
    joint_to_bone = roles["joints"]
    prev = prev_vert_by_joint or {}

    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = mesh_obj.evaluated_get(depsgraph)
    eval_mesh = eval_obj.to_mesh()
    mw = eval_obj.matrix_world

    def project_vi(vi: int) -> tuple[float, float]:
        co = world_to_camera_view(scene, cam, mw @ eval_mesh.vertices[vi].co)
        return float(co.x) * sw, float(1.0 - co.y) * sh

    markers: list[tuple[str, int, str, float]] = []
    used_verts: set[int] = set()
    for i, jn in enumerate(joint_names):
        bone = joint_to_bone[jn]
        bones = _skin_bones_for_joint(jn, bone, cfg)
        primary = bones[0]
        tx, ty = float(targets[i, 0]), float(targets[i, 1])

        if jn == "WeaponTip" and tip_mode == "farthest_from_hand":
            if jn in prev and prev[jn] not in used_verts:
                best_vi = int(prev[jn])
            else:
                best_vi = _pick_farthest_hand_tip_vert(
                    mesh_obj,
                    arm,
                    primary,
                    min_weight=min_w,
                    group_map=group_map,
                    exclude=used_verts,
                )
            used_verts.add(best_vi)
            markers.append((jn, int(best_vi), bone, float(weights[i])))
            continue

        cands = _candidate_vert_indices(mesh_obj, bones, min_weight=min_w, group_map=group_map)
        if not cands:
            raise RuntimeError(
                f"no skinned verts for landmark {jn} bones={bones} minSkinWeight={min_w}"
            )

        def pick_score(vi: int) -> float:
            px, py = project_vi(vi)
            dist = math.hypot(px - tx, py - ty)
            pw = _vert_weight_on_bones(mesh_obj, vi, [primary], group_map)
            return dist - 18.0 * pw

        best_vi = None
        best_s = 1e18
        for vi in cands:
            if vi in used_verts:
                continue
            s = pick_score(vi)
            if s < best_s:
                best_s = s
                best_vi = vi
        if best_vi is None:
            raise RuntimeError(f"all candidate verts already used for landmark {jn}")

        prev_vi = prev.get(jn)
        if (
            prev_vi is not None
            and prev_vi not in used_verts
            and prev_vi in set(cands)
        ):
            if pick_score(prev_vi) <= best_s + slack_px:
                best_vi = prev_vi

        used_verts.add(best_vi)
        markers.append((jn, int(best_vi), bone, float(weights[i])))

    eval_obj.to_mesh_clear()
    return markers


def _weighted_mae(pred: np.ndarray, tgt: np.ndarray, w: np.ndarray) -> float:
    err = np.linalg.norm(pred - tgt, axis=1)
    return float(np.sum(w * err) / (float(np.sum(w)) + 1e-8))


def _arm_chain_names(names: list[str], roles: dict | None = None, cfg: dict | None = None) -> list[str]:
    cfg = cfg or {}
    roles = roles or {}
    prefer = list(cfg.get("armChain") or roles.get("rArmChain") or [])
    if not prefer:
        # UniRig meshy46 strike arm only (not left arm — left DOFs tangled tip chase).
        prefer = [
            "Bone_037",
            "Bone_036",
            "Bone_035",
            "Bone_034",
            "Bone_033",
        ]
    have = set(names)
    return [b for b in prefer if b in have]


def _spine_chain_names(names: list[str], roles: dict | None = None, cfg: dict | None = None) -> list[str]:
    cfg = cfg or {}
    roles = roles or {}
    prefer = list(cfg.get("spineChain") or [])
    if not prefer:
        prefer = [
            b
            for b in (
                "Hips",
                "Spine02",
                "Spine01",
                "Spine",
                "neck",
                "Head",
                "Bone_001",
                "Bone_002",
                "Bone_003",
                "Bone_014",
                "Bone_015",
                "Bone_025",
            )
            if True
        ]
    have = set(names)
    return [b for b in prefer if b in have]


def _pick_farthest_hand_tip_vert(
    mesh_obj,
    arm,
    hand_bone: str,
    *,
    min_weight: float,
    group_map: dict[str, int],
    exclude: set[int],
) -> int:
    """Mace tip ≈ farthest heavy hand-skinned vert from the hand bone head."""
    cands = _candidate_vert_indices(
        mesh_obj, [hand_bone], min_weight=min_weight, group_map=group_map
    )
    cands = [vi for vi in cands if vi not in exclude]
    if not cands:
        raise RuntimeError(f"no tip candidates on {hand_bone} minSkinWeight={min_weight}")
    hand_head = arm.matrix_world @ arm.pose.bones[hand_bone].head
    mw = mesh_obj.matrix_world
    best_vi = cands[0]
    best_d = -1.0
    for vi in cands:
        w = mw @ mesh_obj.data.vertices[vi].co
        d = (w - hand_head).length_squared
        if d > best_d:
            best_d = d
            best_vi = vi
    return int(best_vi)


def _ccd_marker_screen(
    *,
    arm,
    mesh_obj,
    cam,
    scene,
    rest,
    names: list[str],
    x: np.ndarray,
    grab: dict,
    target_xy: np.ndarray,
    chain: list[str],
    sw: float,
    sh: float,
    root_rest: Vector,
    cam_axes: tuple[Vector, Vector, Vector],
    root_translate: bool,
    bound_rad: float,
    root_bound: float,
    iterations: int,
    ang_cap_hi: float = 0.55,
    ang_cap_lo: float = 0.28,
    lo: np.ndarray | None = None,
    hi: np.ndarray | None = None,
    step_fracts: tuple[float, ...] = (1.0, 0.5, 0.25, 0.12),
) -> np.ndarray:
    """CCD one grab toward one screen target over a bone chain.

    Uses signed screen-plane angle with multi-fraction Euler-axis trials.
    Bounds come from caller lo/hi when provided (arm vs spine DOF limits).
    """
    from bpy_extras.object_utils import world_to_camera_view

    n_rot = len(names) * 3
    n_dof = n_rot + (3 if root_translate else 0)
    x = np.asarray(x, dtype=np.float64).copy()
    if len(x) != n_dof:
        x = np.zeros(n_dof, dtype=np.float64)
    if lo is None or hi is None:
        lo = np.full(n_dof, -bound_rad, dtype=np.float64)
        hi = np.full(n_dof, bound_rad, dtype=np.float64)
        if root_translate:
            lo[n_rot:] = -root_bound
            hi[n_rot:] = root_bound
    else:
        lo = np.asarray(lo, dtype=np.float64)
        hi = np.asarray(hi, dtype=np.float64)
    if not chain:
        return x
    tx, ty = float(target_xy[0]), float(target_xy[1])

    def apply_and_proj() -> tuple[float, float]:
        _apply_pose(
            arm,
            rest,
            names,
            x,
            root_rest=root_rest,
            cam_axes=cam_axes,
            root_translate=root_translate,
        )
        bpy.context.view_layer.update()
        world = _lbs_vert_world(arm, mesh_obj, grab["bind_co"], grab["influences"])
        co = world_to_camera_view(scene, cam, world)
        return float(co.x) * sw, float(1.0 - co.y) * sh

    for _it in range(max(1, iterations)):
        px0, py0 = apply_and_proj()
        if math.hypot(px0 - tx, py0 - ty) < 3.0:
            break
        tip_px, tip_py = px0, py0
        for bname in reversed(chain):
            bi = names.index(bname)
            pb = arm.pose.bones[bname]
            pivot = arm.matrix_world @ pb.head
            pco = world_to_camera_view(scene, cam, pivot)
            px, py = float(pco.x) * sw, float(1.0 - pco.y) * sh
            ax, ay = tip_px - px, tip_py - py
            bx, by = tx - px, ty - py
            na = math.hypot(ax, ay)
            nb = math.hypot(bx, by)
            if na < 1e-3 or nb < 1e-3:
                continue
            cross = ax * by - ay * bx
            dot = ax * bx + ay * by
            ang = math.atan2(cross, dot)
            ang_cap = ang_cap_hi if _it < iterations // 2 else ang_cap_lo
            ang = max(-ang_cap, min(ang_cap, ang))
            if abs(ang) < 1e-5:
                continue
            o = bi * 3
            # Skip fully locked bones (authored DOF pins set lo==hi per axis).
            free_axes = [
                a
                for a in (0, 1, 2)
                if float(hi[o + a] - lo[o + a]) > 1e-12
            ]
            if not free_axes:
                continue
            best_local = x[o : o + 3].copy()
            best_err = math.hypot(tip_px - tx, tip_py - ty)
            for axis in free_axes:
                for frac in step_fracts:
                    for sgn in (1.0, -1.0):
                        trial = x.copy()
                        trial[o + axis] = float(
                            np.clip(
                                trial[o + axis] + sgn * ang * frac,
                                lo[o + axis],
                                hi[o + axis],
                            )
                        )
                        x[:] = trial
                        tpx, tpy = apply_and_proj()
                        err = math.hypot(tpx - tx, tpy - ty)
                        if err < best_err:
                            best_err = err
                            best_local = trial[o : o + 3].copy()
                            tip_px, tip_py = tpx, tpy
            x[o : o + 3] = best_local
            x = np.clip(x, lo, hi)
    apply_and_proj()
    return x


def _dof_mask_for_bones(
    names: list[str],
    n_dof: int,
    bone_names: list[str],
    *,
    root_translate: bool,
    freeze_root_up: bool = False,
    freeze_root_translate: bool = False,
) -> np.ndarray:
    want = set(bone_names)
    mask = np.zeros(n_dof, dtype=bool)
    for i, name in enumerate(names):
        if name in want:
            mask[i * 3 : i * 3 + 3] = True
    if root_translate and n_dof >= 3:
        mask[-3:] = True
        if freeze_root_translate:
            # frame0_root owns overall position — no rt/ru/rf optimization.
            mask[-3:] = False
        elif freeze_root_up:
            # Camera-up component (tu) is locked when lowest_foot owns world height.
            mask[-2] = False
    return mask


_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def _parse_axis_list(raw: object, *, bone: str) -> tuple[bool, bool, bool]:
    if raw is None:
        raise RuntimeError(f"boneEulerAxes: bone '{bone}' missing axes list")
    if not isinstance(raw, list):
        raise RuntimeError(f"boneEulerAxes: bone '{bone}' axes must be a list")
    free = [False, False, False]
    for item in raw:
        key = str(item).strip().lower()
        if key not in _AXIS_INDEX:
            raise RuntimeError(
                f"boneEulerAxes: bone '{bone}' unknown axis '{item}' (want x|y|z)"
            )
        free[_AXIS_INDEX[key]] = True
    return bool(free[0]), bool(free[1]), bool(free[2])


def _resolve_repo_path(path_str: str) -> Path:
    p = Path(path_str)
    if not p.is_absolute():
        p = ROOT / p
    return p


def _load_bone_euler_axes_file(path: Path, names: list[str]) -> dict[str, tuple[bool, bool, bool]]:
    if not path.is_file():
        raise RuntimeError(f"boneEulerAxes file missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    bones = data.get("bones")
    if not isinstance(bones, dict) or not bones:
        raise RuntimeError(f"boneEulerAxes file has no bones object: {path}")
    missing = [n for n in names if n not in bones]
    if missing:
        raise RuntimeError(
            f"boneEulerAxes file {path.name} missing optimizeBones entries: {missing}"
        )
    extra = [n for n in bones if n not in names]
    if extra:
        raise RuntimeError(
            f"boneEulerAxes file {path.name} has unknown bones not in optimizeBones: {extra}"
        )
    out: dict[str, tuple[bool, bool, bool]] = {}
    for name in names:
        entry = bones[name]
        if not isinstance(entry, dict):
            raise RuntimeError(f"boneEulerAxes: bone '{name}' entry must be an object")
        out[name] = _parse_axis_list(entry.get("axes"), bone=name)
    return out


def _bone_euler_axes_for_frame(
    cfg: dict, names: list[str], frame_index: int
) -> dict[str, tuple[bool, bool, bool]] | None:
    """Return per-bone (x,y,z) free flags for this frame, or None if authoring omitted."""
    schedule = cfg.get("boneEulerAxesSchedule")
    inline = cfg.get("boneEulerAxes")
    if schedule is None and inline is None:
        return None
    if schedule is not None and inline is not None:
        raise RuntimeError("Specify only one of boneEulerAxesSchedule or boneEulerAxes")

    if inline is not None:
        if not isinstance(inline, dict):
            raise RuntimeError("boneEulerAxes must be an object keyed by bone name")
        # Allow either {Bone: ["x"]} or {Bone: {axes:[...]}} 
        out: dict[str, tuple[bool, bool, bool]] = {}
        missing = [n for n in names if n not in inline]
        if missing:
            raise RuntimeError(f"boneEulerAxes missing optimizeBones: {missing}")
        for name in names:
            entry = inline[name]
            if isinstance(entry, dict):
                out[name] = _parse_axis_list(entry.get("axes"), bone=name)
            else:
                out[name] = _parse_axis_list(entry, bone=name)
        return out

    if not isinstance(schedule, list) or not schedule:
        raise RuntimeError("boneEulerAxesSchedule must be a non-empty list")
    match = None
    for band in schedule:
        if not isinstance(band, dict):
            raise RuntimeError("boneEulerAxesSchedule entries must be objects")
        lo = int(band.get("frameFrom", -1))
        hi = int(band.get("frameTo", -1))
        if lo < 0 or hi < lo:
            raise RuntimeError(f"boneEulerAxesSchedule bad frame range: {band}")
        if lo <= frame_index <= hi:
            match = band
            break
    if match is None:
        raise RuntimeError(
            f"boneEulerAxesSchedule has no band covering frame {frame_index}"
        )
    path = match.get("path")
    if not path:
        raise RuntimeError(f"boneEulerAxesSchedule band missing path: {match}")
    return _load_bone_euler_axes_file(_resolve_repo_path(str(path)), names)


def _euler_axis_dof_mask(
    names: list[str],
    n_dof: int,
    axes: dict[str, tuple[bool, bool, bool]],
    *,
    root_translate: bool,
    freeze_root_up: bool = False,
    freeze_root_translate: bool = False,
) -> np.ndarray:
    mask = np.zeros(n_dof, dtype=bool)
    for i, name in enumerate(names):
        free = axes[name]
        for a in range(3):
            mask[i * 3 + a] = bool(free[a])
    if root_translate and n_dof >= 3:
        mask[-3:] = True
        if freeze_root_translate:
            mask[-3:] = False
        elif freeze_root_up:
            mask[-2] = False
    return mask


def _pin_locked_euler_bounds(
    lo: np.ndarray,
    hi: np.ndarray,
    x0: np.ndarray,
    names: list[str],
    axes: dict[str, tuple[bool, bool, bool]],
) -> None:
    """Freeze locked Euler components to the warm-start value (fail-closed)."""
    for i, name in enumerate(names):
        free = axes[name]
        for a in range(3):
            if free[a]:
                continue
            idx = i * 3 + a
            v = float(x0[idx])
            lo[idx] = v
            hi[idx] = v


def _arm_chain_dof_mask(
    names: list[str],
    n_dof: int,
    root_translate: bool,
    roles: dict | None = None,
    cfg: dict | None = None,
    *,
    freeze_root_up: bool = False,
    freeze_root_translate: bool = False,
) -> np.ndarray:
    """Strike-arm (+ optional root) only — never spine. Spine-in-arm was the fold cheat."""
    return _dof_mask_for_bones(
        names,
        n_dof,
        _arm_chain_names(names, roles, cfg),
        root_translate=root_translate,
        freeze_root_up=freeze_root_up,
        freeze_root_translate=freeze_root_translate,
    )


def _spine_chain_dof_mask(
    names: list[str],
    n_dof: int,
    root_translate: bool,
    roles: dict | None = None,
    cfg: dict | None = None,
    *,
    freeze_root_up: bool = False,
    freeze_root_translate: bool = False,
) -> np.ndarray:
    return _dof_mask_for_bones(
        names,
        n_dof,
        _spine_chain_names(names, roles, cfg),
        root_translate=root_translate,
        freeze_root_up=freeze_root_up,
        freeze_root_translate=freeze_root_translate,
    )


def _ground_anchor_settings(cfg: dict) -> tuple[str, list[str]]:
    """Return (mode, foot_bone_names). mode 'off' disables anchoring."""
    raw = cfg.get("groundAnchor")
    if not isinstance(raw, dict):
        return "off", []
    mode = str(raw.get("mode") or "off").strip().lower()
    if mode in {"", "off", "none", "false"}:
        return "off", []
    bones = [str(b).strip() for b in (raw.get("bones") or []) if str(b).strip()]
    if mode in {"lowest_foot", "frame0_lateral_lowest_foot"} and not bones:
        bones = ["LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase"]
    return mode, bones


def _root_freeze_flags(ga_mode: str) -> tuple[bool, bool]:
    """Return (freeze_root_translate, freeze_root_up) for groundAnchor mode."""
    if ga_mode in {"frame0_root", "frame0_lateral_lowest_foot"}:
        # Freeze root DOFs during the solve; post-pass owns any height plant.
        return True, False
    if ga_mode == "lowest_foot":
        return False, True
    return False, False


def _collision_bias_settings(cfg: dict) -> dict | None:
    raw = cfg.get("collisionBias")
    if not isinstance(raw, dict):
        return None
    if not bool(raw.get("enabled", False)):
        return None
    return {
        "sampleCount": max(32, int(raw.get("sampleCount", 320))),
        "geodesicMinHops": max(1, int(raw.get("geodesicMinHops", 8))),
        "margin": float(raw.get("margin", 0.045)),
        "weight": float(raw.get("weight", 40.0)),
    }


def _midline_bias_settings(cfg: dict) -> dict | None:
    """Per-bone sagittal midline: keep each bone on its bind side of the hips plane.

    Soft penalty is inside eval_pose so DLS/CCD search alternate reaches instead of
    folding limbs through the torso. Hard reject refuses crossed poses.

    Lateral axis is the bind LeftShoulder→RightShoulder direction stored in armature
    space (not pose-bone local X — Mixamo hips axes are not character left/right).
    """
    raw = cfg.get("midlineBias")
    if not isinstance(raw, dict):
        return None
    if not bool(raw.get("enabled", False)):
        return None
    return {
        "margin": float(raw.get("margin", 0.02)),
        "weight": float(raw.get("weight", 80.0)),
        "hardReject": bool(raw.get("hardReject", True)),
        "minBindAbs": float(raw.get("minBindAbs", 0.025)),
        "hipsBone": str(raw.get("hipsBone") or "").strip() or None,
        "leftRefBone": str(raw.get("leftRefBone") or "LeftShoulder").strip(),
        "rightRefBone": str(raw.get("rightRefBone") or "RightShoulder").strip(),
        "sampleEnds": [str(e).strip().lower() for e in (raw.get("sampleEnds") or ["head"])],
    }


def _bone_head_world(arm, bone_name: str) -> Vector:
    pb = arm.pose.bones.get(bone_name)
    if pb is None:
        raise RuntimeError(f"midlineBias: bone '{bone_name}' missing on armature")
    return arm.matrix_world @ pb.head


def _midline_origin_and_left(arm, midline: dict) -> tuple[Vector, Vector]:
    """Hips head origin + character-left axis (armature-stable bind direction)."""
    origin = _bone_head_world(arm, midline["hipsBone"])
    aw = arm.matrix_world.to_3x3()
    left_local = Vector(midline["leftAxisArmLocal"])
    left = (aw @ left_local).normalized()
    if left.length < 1e-8:
        raise RuntimeError("midlineBias: character-left axis degenerate")
    return origin, left


def _bone_lateral_samples(
    arm, bone_name: str, origin: Vector, left: Vector, sample_ends: list[str]
) -> list[tuple[str, float]]:
    pb = arm.pose.bones.get(bone_name)
    if pb is None:
        return []
    out: list[tuple[str, float]] = []
    for end in sample_ends:
        if end == "head":
            pt = arm.matrix_world @ pb.head
        elif end == "tail":
            pt = arm.matrix_world @ pb.tail
        else:
            raise RuntimeError(f"midlineBias: unknown sample end '{end}'")
        out.append((end, float((pt - origin).dot(left))))
    return out


def _build_midline_bias(
    arm,
    bone_names: list[str],
    settings: dict,
    *,
    hips_bone: str,
) -> dict:
    """Capture bind-side signs at the current (rest) pose for optimize bones."""
    left_ref = str(settings["leftRefBone"])
    right_ref = str(settings["rightRefBone"])
    left_w = _bone_head_world(arm, left_ref)
    right_w = _bone_head_world(arm, right_ref)
    left_axis_world = left_w - right_w
    # Drop world-up so spine height cannot flip left/right labels (Mixamo shoulders
    # sit above hips; an unprojected L−R vector is mostly vertical noise).
    up = Vector((0.0, 0.0, 1.0))
    left_axis_world = left_axis_world - up * float(left_axis_world.dot(up))
    if left_axis_world.length < 1e-6:
        raise RuntimeError(
            f"midlineBias: {left_ref}/{right_ref} heads are collinear with world-up; "
            "cannot define horizontal lateral axis"
        )
    left_axis_world.normalize()
    # Store in armature local so root yaw follows; hips Euler does not redefine the plane.
    aw_inv = arm.matrix_world.to_3x3().inverted()
    left_axis_arm = aw_inv @ left_axis_world
    if left_axis_arm.length < 1e-8:
        raise RuntimeError("midlineBias: failed to store left axis in armature space")
    left_axis_arm.normalize()

    origin = _bone_head_world(arm, hips_bone)
    sample_ends = list(settings.get("sampleEnds") or ["head"])
    if not sample_ends:
        raise RuntimeError("midlineBias: sampleEnds empty")
    margin = float(settings["margin"])
    min_abs = float(settings["minBindAbs"])
    constrained: list[dict] = []
    skipped: list[dict] = []
    for name in bone_names:
        if name == hips_bone:
            skipped.append({"name": name, "reason": "hips_origin"})
            continue
        samples = _bone_lateral_samples(arm, name, origin, left_axis_world, sample_ends)
        if not samples:
            skipped.append({"name": name, "reason": "missing"})
            continue
        mean_lat = float(sum(v for _e, v in samples) / len(samples))
        abs_lat = abs(mean_lat)
        if abs_lat < min_abs:
            skipped.append(
                {
                    "name": name,
                    "reason": "near_midline",
                    "bindAbs": abs_lat,
                }
            )
            continue
        sign = 1.0 if mean_lat >= 0.0 else -1.0
        constrained.append(
            {
                "name": name,
                "sign": sign,
                "bindAbs": abs_lat,
                "bindSamples": {e: float(v) for e, v in samples},
            }
        )
    if not constrained:
        raise RuntimeError(
            "midlineBias: no optimize bones cleared minBindAbs "
            f"(minBindAbs={min_abs}); cannot enforce side plane"
        )
    return {
        "hipsBone": hips_bone,
        "leftRefBone": left_ref,
        "rightRefBone": right_ref,
        "leftAxisArmLocal": [float(left_axis_arm.x), float(left_axis_arm.y), float(left_axis_arm.z)],
        "sampleEnds": sample_ends,
        "margin": margin,
        "weight": float(settings["weight"]),
        "hardReject": bool(settings["hardReject"]),
        "minBindAbs": min_abs,
        "bones": constrained,
        "skipped": skipped,
        "constrainedCount": len(constrained),
    }


def _midline_penalty(arm, midline: dict) -> tuple[float, int, list[str]]:
    """Soft cost when a bone sample approaches or crosses the hips sagittal plane."""
    origin, left = _midline_origin_and_left(arm, midline)
    margin = float(midline["margin"])
    weight = float(midline["weight"])
    sample_ends = list(midline["sampleEnds"])
    pen = 0.0
    hits = 0
    offenders: list[str] = []
    for entry in midline["bones"]:
        sign = float(entry["sign"])
        for end, lat in _bone_lateral_samples(arm, entry["name"], origin, left, sample_ends):
            side = lat * sign
            if side >= margin:
                continue
            excess = margin - side
            pen += weight * excess * excess
            hits += 1
            offenders.append(f"{entry['name']}.{end}")
    return float(pen), int(hits), offenders


def _midline_ok(arm, midline: dict | None) -> tuple[bool, str]:
    """Hard reject when any constrained bone sample crosses past the midpoint."""
    if midline is None or not bool(midline.get("hardReject", True)):
        return True, "ok"
    origin, left = _midline_origin_and_left(arm, midline)
    sample_ends = list(midline["sampleEnds"])
    for entry in midline["bones"]:
        sign = float(entry["sign"])
        for end, lat in _bone_lateral_samples(arm, entry["name"], origin, left, sample_ends):
            if lat * sign < 0.0:
                return False, f"midline_cross:{entry['name']}.{end}"
    return True, "ok"


def _build_collision_bias(mesh_obj, settings: dict) -> dict:
    """Precompute geodesically-distant sample pairs for soft self-collision loss.

    Samples face centroids via a representative vertex; hop distance is BFS on the
    welded vertex graph. Pairs that are already closer than margin at bind are
    dropped so rest contacts (armpits, etc.) are not fought.
    """
    me = mesh_obj.data
    n_verts = len(me.vertices)
    n_faces = len(me.polygons)
    if n_verts < 8 or n_faces < 8:
        raise RuntimeError("collisionBias: mesh too small")

    sample_count = min(int(settings["sampleCount"]), n_faces)
    stride = max(1, n_faces // sample_count)
    face_ids = list(range(0, n_faces, stride))[:sample_count]
    vert_indices = [int(me.polygons[fi].vertices[0]) for fi in face_ids]
    # Deduplicate representative verts while preserving order.
    seen: set[int] = set()
    uniq: list[int] = []
    for vi in vert_indices:
        if vi not in seen:
            seen.add(vi)
            uniq.append(vi)
    vert_indices = uniq
    n_s = len(vert_indices)
    if n_s < 8:
        raise RuntimeError("collisionBias: too few unique sample verts")

    adj: list[list[int]] = [[] for _ in range(n_verts)]
    for e in me.edges:
        a, b = int(e.vertices[0]), int(e.vertices[1])
        adj[a].append(b)
        adj[b].append(a)

    from collections import deque

    def _hops(src: int) -> list[int]:
        dist = [-1] * n_verts
        dist[src] = 0
        q: deque[int] = deque([src])
        while q:
            u = q.popleft()
            du = dist[u]
            for v in adj[u]:
                if dist[v] < 0:
                    dist[v] = du + 1
                    q.append(v)
        return dist

    mw = mesh_obj.matrix_world
    bind_pos = np.array(
        [(mw @ me.vertices[vi].co) for vi in vert_indices], dtype=np.float64
    )
    gmin = int(settings["geodesicMinHops"])
    margin = float(settings["margin"])
    pairs: list[tuple[int, int]] = []
    cross_component = 0
    for i in range(n_s):
        dist = _hops(vert_indices[i])
        for j in range(i + 1, n_s):
            hop = dist[vert_indices[j]]
            # Unreachable (different mesh islands) counts as infinitely distant —
            # critical for bridge-fixed props/swords that are intentionally detached.
            if hop >= 0 and hop < gmin:
                continue
            if hop < 0:
                cross_component += 1
            d0 = float(np.linalg.norm(bind_pos[i] - bind_pos[j]))
            if d0 < margin:
                continue
            pairs.append((i, j))
    if not pairs:
        raise RuntimeError(
            "collisionBias: no geodesically-distant pairs survived filters "
            f"(samples={n_s} gmin={gmin} margin={margin})"
        )
    return {
        "vertIndices": np.asarray(vert_indices, dtype=np.int32),
        "pairs": np.asarray(pairs, dtype=np.int32),
        "margin": margin,
        "weight": float(settings["weight"]),
        "sampleCount": n_s,
        "pairCount": len(pairs),
        "geodesicMinHops": gmin,
        "crossComponentPairs": int(cross_component),
    }


def _sample_world_positions(mesh_obj, vert_indices: np.ndarray) -> np.ndarray:
    """World positions for sample verts (vectorized foreach_get + mat4)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = mesh_obj.evaluated_get(depsgraph)
    em = eval_obj.to_mesh()
    try:
        n = len(em.vertices)
        flat = np.empty(n * 3, dtype=np.float64)
        em.vertices.foreach_get("co", flat)
        local = flat.reshape(n, 3)
        mw = np.array(eval_obj.matrix_world, dtype=np.float64)
        r = mw[:3, :3]
        t = mw[:3, 3]
        idx = np.asarray(vert_indices, dtype=np.int64)
        return local[idx] @ r.T + t
    finally:
        eval_obj.to_mesh_clear()


def _collision_penalty(mesh_obj, bias: dict) -> tuple[float, int]:
    """Return (weighted_penalty, hit_count) for distant samples closer than margin."""
    pos = _sample_world_positions(mesh_obj, bias["vertIndices"])
    pairs = bias["pairs"]
    margin = float(bias["margin"])
    weight = float(bias["weight"])
    a = pos[pairs[:, 0]]
    b = pos[pairs[:, 1]]
    # Squared distance then sqrt only for violators is more branches; full norm is fine
    # and stays bit-stable vs the prior pair loop.
    d = np.linalg.norm(a - b, axis=1)
    viol = np.maximum(0.0, margin - d)
    hits = int(np.count_nonzero(viol > 0.0))
    pen = float(weight * np.sum(viol * viol))
    return pen, hits


def _clamp_max_step_rad(
    vec: np.ndarray,
    x0: np.ndarray,
    n_rot: int,
    max_step_rad: float,
) -> tuple[np.ndarray, int, float]:
    """Hard-cap per-component Euler change vs previous pose. Root DOFs untouched.

    Returns (clamped_vec, clamp_count, max_excess_rad).
    """
    out = np.asarray(vec, dtype=np.float64).copy()
    if max_step_rad <= 0.0 or n_rot <= 0:
        return out, 0, 0.0
    ref = np.asarray(x0, dtype=np.float64)
    if len(ref) < n_rot or len(out) < n_rot:
        raise RuntimeError("maxStepRad clamp: pose vector shorter than n_rot")
    clamps = 0
    max_excess = 0.0
    for i in range(n_rot):
        d = float(out[i] - ref[i])
        ad = abs(d)
        if ad > max_step_rad:
            clamps += 1
            max_excess = max(max_excess, ad - max_step_rad)
            out[i] = float(ref[i] + math.copysign(max_step_rad, d))
    return out, clamps, max_excess


def _min_foot_world_z(arm, bone_names: list[str]) -> float:
    zs: list[float] = []
    for name in bone_names:
        pb = arm.pose.bones.get(name)
        if pb is None:
            continue
        # Prefer foot head (ankle/ball); include tip of toe bones via tail.
        head = arm.matrix_world @ pb.head
        tail = arm.matrix_world @ pb.tail
        zs.append(float(min(head.z, tail.z)))
    if not zs:
        raise RuntimeError(
            f"groundAnchor lowest_foot: none of bones present on armature: {bone_names}"
        )
    return float(min(zs))


def _root_components_from_location(
    location: Vector,
    root_rest: Vector,
    cam_axes: tuple[Vector, Vector, Vector],
) -> tuple[float, float, float]:
    right, up, forward = cam_axes
    delta = location - root_rest
    return float(delta.dot(right)), float(delta.dot(up)), float(delta.dot(forward))


def _apply_lowest_foot_ground_lock(
    *,
    arm,
    rest: dict,
    names: list[str],
    x: np.ndarray,
    root_rest: Vector,
    cam_axes: tuple[Vector, Vector, Vector],
    root_translate: bool,
    ground_z: float,
    foot_bones: list[str],
) -> tuple[np.ndarray, float, float]:
    """Shift root world-Z so min foot Z == ground_z; rewrite pose root DOFs.

    Returns (x_corrected, min_foot_z_before, min_foot_z_after).
    """
    if not root_translate:
        raise RuntimeError("groundAnchor requires rootTranslate")
    n_rot = len(names) * 3
    if len(x) < n_rot + 3:
        raise RuntimeError("pose vector missing root translate DOFs for groundAnchor")

    _apply_pose(
        arm,
        rest,
        names,
        x,
        root_rest=root_rest,
        cam_axes=cam_axes,
        root_translate=True,
    )
    bpy.context.view_layer.update()
    z_before = _min_foot_world_z(arm, foot_bones)
    dz = float(ground_z) - z_before
    if abs(dz) > 1e-9:
        arm.location = Vector((arm.location.x, arm.location.y, arm.location.z + dz))
        bpy.context.view_layer.update()
    tr, tu, tf = _root_components_from_location(arm.location, root_rest, cam_axes)
    out = np.asarray(x, dtype=np.float64).copy()
    out[n_rot] = tr
    out[n_rot + 1] = tu
    out[n_rot + 2] = tf
    # Re-apply through the canonical pose path so rest state matches stored x.
    _apply_pose(
        arm,
        rest,
        names,
        out,
        root_rest=root_rest,
        cam_axes=cam_axes,
        root_translate=True,
    )
    bpy.context.view_layer.update()
    z_after = _min_foot_world_z(arm, foot_bones)
    return out, z_before, z_after


def _apply_frame0_lateral_lowest_foot_lock(
    *,
    arm,
    rest: dict,
    names: list[str],
    x: np.ndarray,
    root_rest: Vector,
    cam_axes: tuple[Vector, Vector, Vector],
    root_translate: bool,
    ground_z: float,
    foot_bones: list[str],
    loc0_xy: tuple[float, float],
) -> tuple[np.ndarray, float, float, float]:
    """Plant feet on ground_z while keeping root world XY at frame0.

    Hips (and other) Eulers may move the mesh relative to the root; this restores
    gravity contact without allowing lateral ice-skating. Returns
    (x_corrected, min_foot_z_before, min_foot_z_after, delta_z).
    """
    if not root_translate:
        raise RuntimeError("groundAnchor requires rootTranslate")
    n_rot = len(names) * 3
    if len(x) < n_rot + 3:
        raise RuntimeError("pose vector missing root translate DOFs for groundAnchor")

    _apply_pose(
        arm,
        rest,
        names,
        x,
        root_rest=root_rest,
        cam_axes=cam_axes,
        root_translate=True,
    )
    bpy.context.view_layer.update()
    z_before = _min_foot_world_z(arm, foot_bones)
    dz = float(ground_z) - z_before
    # Gravity plant (world Z) then restore frame0 lateral so hips crouch cannot skate.
    arm.location = Vector(
        (float(loc0_xy[0]), float(loc0_xy[1]), float(arm.location.z + dz))
    )
    bpy.context.view_layer.update()
    tr, tu, tf = _root_components_from_location(arm.location, root_rest, cam_axes)
    out = np.asarray(x, dtype=np.float64).copy()
    out[n_rot] = tr
    out[n_rot + 1] = tu
    out[n_rot + 2] = tf
    _apply_pose(
        arm,
        rest,
        names,
        out,
        root_rest=root_rest,
        cam_axes=cam_axes,
        root_translate=True,
    )
    bpy.context.view_layer.update()
    z_after = _min_foot_world_z(arm, foot_bones)
    return out, z_before, z_after, float(dz)


def _torso_dir_world(arm, roles: dict) -> Vector | None:
    joints = roles.get("joints") or {}
    mid_n = joints.get("MidHip")
    nose_n = joints.get("Nose")
    if not mid_n or not nose_n:
        return None
    mid_b = arm.pose.bones.get(mid_n)
    nose_b = arm.pose.bones.get(nose_n)
    if mid_b is None or nose_b is None:
        return None
    mid = arm.matrix_world @ mid_b.head
    nose = arm.matrix_world @ nose_b.head
    d = nose - mid
    if d.length < 1e-6:
        return None
    return d.normalized()


def _max_body_err_px(pred: np.ndarray, targets: np.ndarray, grabs: list[dict]) -> float:
    worst = 0.0
    for bn in ("MidHip", "Nose", "Neck"):
        bi = next((i for i, g in enumerate(grabs) if g["joint"] == bn), None)
        if bi is None:
            continue
        worst = max(worst, float(np.linalg.norm(pred[bi] - targets[bi])))
    return worst


def _body_integrity_ok(
    pred: np.ndarray,
    targets: np.ndarray,
    grabs: list[dict],
    *,
    arm,
    roles: dict,
    torso_ref: Vector | None,
    body_start_err_px: float,
    body_slack_px: float,
    body_abs_ceil_px: float,
    torso_min_dot: float,
    check_body_landmarks: bool = True,
) -> tuple[bool, str]:
    """Reject torso flips always; optionally reject body-landmark regression (spine/full)."""
    if check_body_landmarks:
        body_err = _max_body_err_px(pred, targets, grabs)
        limit = min(body_abs_ceil_px, body_start_err_px + body_slack_px)
        if body_err > limit:
            return False, f"body_err_px={body_err:.1f}>{limit:.1f}"
    if torso_ref is not None and torso_min_dot > -1.0:
        cur = _torso_dir_world(arm, roles)
        if cur is not None and float(cur.dot(torso_ref)) < torso_min_dot:
            return False, f"torso_flip_dot={float(cur.dot(torso_ref)):.2f}<{torso_min_dot:.2f}"
    return True, "ok"


def _solve_frame_ik(
    *,
    arm,
    mesh_obj,
    cam,
    scene,
    rest,
    names: list[str],
    markers: list[tuple[str, int, str, float]],
    targets: np.ndarray,
    x0: np.ndarray,
    sw: float,
    sh: float,
    cfg: dict,
    root_rest: Vector,
    cam_axes: tuple[Vector, Vector, Vector],
    root_translate: bool,
    bound_rad: float,
    root_bound: float,
    frame_index: int,
    roles: dict | None = None,
    collision_bias: dict | None = None,
    midline_bias: dict | None = None,
) -> tuple[np.ndarray, dict]:
    roles = roles or {}
    n_rot = len(names) * 3
    n_dof = n_rot + (3 if root_translate else 0)
    x = np.asarray(x0, dtype=np.float64).copy()
    if len(x) != n_dof:
        x = np.zeros(n_dof, dtype=np.float64)

    grabs = _grabs_from_markers(mesh_obj, markers)
    w_base = np.array([g["weight"] for g in grabs], dtype=np.float64)
    tip_i = next((i for i, g in enumerate(grabs) if g["joint"] == "WeaponTip"), None)
    tip_boost = float(cfg.get("tipWeightBoost", 1.8))

    max_steps = max(1, int(cfg.get("maxSteps", 60)))
    damping = float(cfg.get("damping", 0.20))
    eps = float(cfg.get("eps", 0.02))
    loss_floor = float(cfg.get("lossFloorPx", 2.0))
    jolt_frac = float(cfg.get("joltFrac", 0.22))
    jolt_grow = float(cfg.get("joltGrow", 1.12))
    jolt_frac_max = float(cfg.get("joltFracMax", 0.75))
    ccd_iters = max(0, int(cfg.get("ccdTipIterations", 24)))
    plateau_steps = max(2, int(cfg.get("plateauSteps", 6)))
    seed = int(cfg.get("seed", 11)) + frame_index * 17
    rng = np.random.default_rng(seed)
    last_collision_pen = 0.0
    last_collision_hits = 0
    last_midline_pen = 0.0
    last_midline_hits = 0
    last_midline_offenders: list[str] = []
    midline_rejects = 0

    lo = np.full(n_dof, -bound_rad, dtype=np.float64)
    hi = np.full(n_dof, bound_rad, dtype=np.float64)
    if root_translate:
        lo[n_rot:] = -root_bound
        hi[n_rot:] = root_bound
    ga_mode, _ga_bones = _ground_anchor_settings(cfg)
    freeze_root_translate, freeze_root_up = _root_freeze_flags(ga_mode)
    max_step_rad = float(cfg.get("maxStepRad", 0.0) or 0.0)
    step_clamps = 0
    step_max_excess = 0.0

    authored_axes = _bone_euler_axes_for_frame(cfg, names, frame_index)
    authored_axis_mask: np.ndarray | None = None
    if authored_axes is not None:
        _pin_locked_euler_bounds(lo, hi, x, names, authored_axes)
        # Locked components stay at warm-start even if x drifts before clamp.
        for i, name in enumerate(names):
            free = authored_axes[name]
            for a in range(3):
                if not free[a]:
                    x[i * 3 + a] = float(x0[i * 3 + a])
        authored_axis_mask = _euler_axis_dof_mask(
            names,
            n_dof,
            authored_axes,
            root_translate=root_translate,
            freeze_root_up=freeze_root_up,
            freeze_root_translate=freeze_root_translate,
        )
        free_n = int(np.count_nonzero(authored_axis_mask[:n_rot]))
        print(
            f"[marker-ik] frame {frame_index} authoredEulerAxes freeRotDof={free_n}/{n_rot}",
            flush=True,
        )
        # Scale solver budget by free DOFs (idle≈4 should not burn full attack budget).
        # Caps only — never raises above config.
        step_cap = max(14, 6 + free_n * 2)
        if step_cap < max_steps:
            print(
                f"[marker-ik] frame {frame_index} maxSteps {max_steps}→{step_cap} (freeRotDof scale)",
                flush=True,
            )
            max_steps = step_cap
        ccd_cap = max(8, free_n * 3)
        if ccd_iters > 0 and ccd_cap < ccd_iters:
            print(
                f"[marker-ik] frame {frame_index} ccdTipIterations {ccd_iters}→{ccd_cap} (freeRotDof scale)",
                flush=True,
            )
            ccd_iters = ccd_cap

    def clamp_step(vec: np.ndarray) -> np.ndarray:
        nonlocal step_clamps, step_max_excess
        out, n_c, excess = _clamp_max_step_rad(vec, x0, n_rot, max_step_rad)
        step_clamps += int(n_c)
        step_max_excess = max(step_max_excess, float(excess))
        return out

    if freeze_root_translate and root_translate:
        # Pin rt/ru/rf to warm-start (frame0_root restores to absolute frame0 outside).
        for k in range(3):
            v = float(x[n_rot + k])
            lo[n_rot + k] = v
            hi[n_rot + k] = v
            x[n_rot + k] = v
    elif freeze_root_up and root_translate:
        # Keep camera-up DOF at current value (normally 0); ground lock owns height.
        tu = float(x[n_rot + 1]) if len(x) > n_rot + 1 else 0.0
        lo[n_rot + 1] = tu
        hi[n_rot + 1] = tu
        x[n_rot + 1] = tu

    arm_mask = _arm_chain_dof_mask(
        names,
        n_dof,
        root_translate,
        roles,
        cfg,
        freeze_root_up=freeze_root_up,
        freeze_root_translate=freeze_root_translate,
    )
    spine_mask = _spine_chain_dof_mask(
        names,
        n_dof,
        root_translate,
        roles,
        cfg,
        freeze_root_up=freeze_root_up,
        freeze_root_translate=freeze_root_translate,
    )

    if authored_axis_mask is not None:
        arm_mask = arm_mask & authored_axis_mask
        spine_mask = spine_mask & authored_axis_mask

    def full_dof_mask() -> np.ndarray:
        m = np.ones(n_dof, dtype=bool)
        if freeze_root_translate and root_translate:
            m[-3:] = False
        elif freeze_root_up and root_translate:
            m[-2] = False
        if authored_axis_mask is not None:
            m = m & authored_axis_mask
        return m
    tip_guard_px = float(cfg.get("skipFullBodyIfTipErrorPx", 70.0))
    body_slack = float(cfg.get("bodyGuardSlackPx", 40.0))
    body_abs_ceil = float(cfg.get("bodyGuardAbsCeilPx", cfg.get("ccdBodyGuardPx", 160.0)))
    torso_min_dot = float(cfg.get("torsoMinDot", 0.20))
    arm_bound = float(cfg.get("armBoundRad", bound_rad))
    spine_bound = float(cfg.get("spineBoundRad", min(bound_rad, 0.70)))
    ccd_ang_hi = float(cfg.get("ccdAngCapHi", 0.95))
    ccd_ang_lo = float(cfg.get("ccdAngCapLo", 0.45))

    # Per-chain Euler bounds: arms need reach; spine stays tight (fold path).
    arm_bones = set(_arm_chain_names(names, roles, cfg))
    spine_bones = set(_spine_chain_names(names, roles, cfg))
    for i, name in enumerate(names):
        if name in arm_bones:
            lo[i * 3 : i * 3 + 3] = -arm_bound
            hi[i * 3 : i * 3 + 3] = arm_bound
        elif name in spine_bones:
            lo[i * 3 : i * 3 + 3] = -spine_bound
            hi[i * 3 : i * 3 + 3] = spine_bound
    # Authored locks win over chain bounds — re-pin after arm/spine limit expand.
    if authored_axes is not None:
        _pin_locked_euler_bounds(lo, hi, x0, names, authored_axes)

    def loss_weights(*, tip_priority: bool, body_boost: bool = False) -> np.ndarray:
        w = w_base.copy()
        if tip_priority and tip_i is not None:
            w[tip_i] *= tip_boost
        if body_boost:
            boost = float(cfg.get("bodyLandmarkBoost", 2.2))
            for bn in ("MidHip", "Nose", "Neck"):
                bi = next((i for i, g in enumerate(grabs) if g["joint"] == bn), None)
                if bi is not None:
                    w[bi] *= boost
        return w

    def eval_pose(
        vec: np.ndarray,
        w: np.ndarray,
        *,
        include_collision: bool = True,
        include_midline: bool = True,
    ) -> tuple[np.ndarray, float]:
        nonlocal last_collision_pen, last_collision_hits
        nonlocal last_midline_pen, last_midline_hits, last_midline_offenders
        _apply_pose(
            arm,
            rest,
            names,
            vec,
            root_rest=root_rest,
            cam_axes=cam_axes,
            root_translate=root_translate,
        )
        bpy.context.view_layer.update()
        pred = _project_grabs_px(arm, mesh_obj, grabs, cam, scene, sw, sh)
        loss = _weighted_mae(pred, targets, w)
        rest_w = float(cfg.get("restWeight", 0.035))
        motion_w = float(cfg.get("motionWeight", 0.08))
        if rest_w > 0.0:
            loss += rest_w * float(np.linalg.norm(vec[:n_rot]))
        if motion_w > 0.0:
            loss += motion_w * float(np.linalg.norm(vec - x0))
        # Midline first so the Jacobian prefers side-safe reaches before collision polish.
        if include_midline and midline_bias is not None:
            pen_m, hits_m, offenders = _midline_penalty(arm, midline_bias)
            last_midline_pen = pen_m
            last_midline_hits = hits_m
            last_midline_offenders = offenders
            loss += pen_m
        if include_collision and collision_bias is not None:
            pen, hits = _collision_penalty(mesh_obj, collision_bias)
            last_collision_pen = pen
            last_collision_hits = hits
            loss += pen
        return pred, loss

    def tip_err_px(pred: np.ndarray) -> float:
        if tip_i is None:
            return 0.0
        return float(np.linalg.norm(pred[tip_i] - targets[tip_i]))

    def accept_pose(
        vec: np.ndarray,
        w: np.ndarray,
        *,
        check_body_landmarks: bool = True,
        check_midline: bool = True,
    ) -> tuple[bool, np.ndarray, float, str]:
        nonlocal midline_rejects
        pred, loss = eval_pose(vec, w)
        # Soft midline is always in `loss` via eval_pose (early; Jacobian feels it).
        # Hard reject only once the tip is already near — otherwise tip CCD / early DLS
        # cannot seed a reach, and the solver never gets a chance to find a side-safe path.
        tip_now = tip_err_px(pred)
        midline_tip_gate = float(cfg.get("midlineHardRejectMaxTipPx", tip_guard_px))
        if check_midline and tip_now <= midline_tip_gate:
            ok_m, reason_m = _midline_ok(arm, midline_bias)
            if not ok_m:
                midline_rejects += 1
                return False, pred, loss, reason_m
        ok, reason = _body_integrity_ok(
            pred,
            targets,
            grabs,
            arm=arm,
            roles=roles,
            torso_ref=torso_ref,
            body_start_err_px=body_start_err,
            body_slack_px=body_slack,
            body_abs_ceil_px=body_abs_ceil,
            torso_min_dot=torso_min_dot,
            check_body_landmarks=check_body_landmarks,
        )
        return ok, pred, loss, reason

    w = loss_weights(tip_priority=True)
    pred0, _start_boost = eval_pose(x, w)
    # Torso direction + body landmark error at warm-start — reject folds relative to this.
    torso_ref = _torso_dir_world(arm, roles)
    body_start_err = _max_body_err_px(pred0, targets, grabs)
    best_x = x.copy()
    jolts = 0
    ccd_used = 0
    body_rejects = 0
    stop_reason = "max_steps"

    def run_tip_ccd(cur: np.ndarray) -> np.ndarray:
        if tip_i is None:
            return cur
        _apply_pose(
            arm,
            rest,
            names,
            cur,
            root_rest=root_rest,
            cam_axes=cam_axes,
            root_translate=root_translate,
        )
        bpy.context.view_layer.update()
        if tip_err_px(_project_grabs_px(arm, mesh_obj, grabs, cam, scene, sw, sh)) <= 8.0:
            return cur
        return _ccd_marker_screen(
            arm=arm,
            mesh_obj=mesh_obj,
            cam=cam,
            scene=scene,
            rest=rest,
            names=names,
            x=cur,
            grab=grabs[tip_i],
            target_xy=targets[tip_i],
            chain=_arm_chain_names(names, roles, cfg),
            sw=sw,
            sh=sh,
            root_rest=root_rest,
            cam_axes=cam_axes,
            root_translate=root_translate,
            bound_rad=arm_bound,
            root_bound=root_bound,
            iterations=ccd_iters,
            ang_cap_hi=ccd_ang_hi,
            ang_cap_lo=ccd_ang_lo,
            lo=lo,
            hi=hi,
        )

    def run_spine_ccd(cur: np.ndarray) -> np.ndarray:
        nose_i = next((i for i, g in enumerate(grabs) if g["joint"] == "Nose"), None)
        if nose_i is None:
            return cur
        return _ccd_marker_screen(
            arm=arm,
            mesh_obj=mesh_obj,
            cam=cam,
            scene=scene,
            rest=rest,
            names=names,
            x=cur,
            grab=grabs[nose_i],
            target_xy=targets[nose_i],
            chain=_spine_chain_names(names, roles, cfg),
            sw=sw,
            sh=sh,
            root_rest=root_rest,
            cam_axes=cam_axes,
            root_translate=root_translate,
            bound_rad=spine_bound,
            root_bound=root_bound,
            iterations=max(8, ccd_iters // 3),
            ang_cap_hi=min(0.35, ccd_ang_hi * 0.35),
            ang_cap_lo=min(0.18, ccd_ang_lo * 0.35),
            lo=lo,
            hi=hi,
        )

    # Uniform CCD order every frame: tip on strike-arm, then gentle spine lean.
    # Tip stage: torso-flip only. Spine stage: body-landmark slack.
    if ccd_iters > 0:
        arm_chain = _arm_chain_names(names, roles, cfg)
        spine_chain = _spine_chain_names(names, roles, cfg)

        def _chain_has_free_euler(chain: list[str]) -> bool:
            for bname in chain:
                if bname not in names:
                    continue
                o = names.index(bname) * 3
                for a in range(3):
                    if float(hi[o + a] - lo[o + a]) > 1e-12:
                        return True
            return False

        trial = x.copy()
        if tip_i is not None and _chain_has_free_euler(arm_chain):
            trial = run_tip_ccd(trial)
            ok_tip, _p, _loss, reason_tip = accept_pose(
                trial, w, check_body_landmarks=False, check_midline=False
            )
            if not ok_tip:
                body_rejects += 1
                trial = np.asarray(x0, dtype=np.float64).copy()
                ccd_used = 0
                print(
                    f"[marker-ik] frame {frame_index} tip CCD rejected ({reason_tip})",
                    flush=True,
                )
            else:
                ccd_used = ccd_iters
                tip_kept = trial.copy()
                if _chain_has_free_euler(spine_chain):
                    spine_trial = run_spine_ccd(trial)
                    ok_spine, _p, _loss, reason_spine = accept_pose(
                        spine_trial, w, check_body_landmarks=True
                    )
                    if ok_spine:
                        trial = spine_trial
                    else:
                        body_rejects += 1
                        trial = tip_kept
                        print(
                            f"[marker-ik] frame {frame_index} spine CCD rejected ({reason_spine}); keep tip CCD",
                            flush=True,
                        )
        x = clamp_step(trial)
        best_x = x.copy()

    _apply_pose(
        arm, rest, names, best_x, root_rest=root_rest, cam_axes=cam_axes, root_translate=root_translate
    )
    bpy.context.view_layer.update()
    tip_after_ccd = tip_err_px(_project_grabs_px(arm, mesh_obj, grabs, cam, scene, sw, sh))
    # Tip still far → arm-only DLS. Never open spine/legs until tip is close enough.
    if tip_after_ccd >= tip_guard_px:
        stages = [("tip_arm", True, False, arm_mask, max_steps, False)]
    else:
        stages = [
            ("tip_arm", True, False, arm_mask, max(10, max_steps // 2), False),
            ("spine", False, True, spine_mask, max(8, max_steps // 3), True),
            ("full", False, True, full_dof_mask(), max_steps, True),
        ]

    for _stage_name, tip_priority, body_boost, dof_mask, stage_steps, check_body in stages:
        w = loss_weights(tip_priority=tip_priority, body_boost=body_boost)
        x = best_x.copy()
        # Warm start is always the previous accepted pose; integrity is relative to
        # frame-start body error, so arm-only stages still run even if body landmarks
        # have not yet caught the new sprite targets.
        _p0, best = eval_pose(x, w)
        active = np.where(dof_mask)[0]
        if active.size == 0:
            continue

        stall = 0
        stage_stop = None
        for _step in range(stage_steps):
            if best <= loss_floor:
                stage_stop = "loss_floor"
                break

            # Marker Jacobian only — collision/midline priors stay on accept_pose.
            # Finite-diff mesh samples for collision dominate runtime and muddy tip J.
            pred, _cur = eval_pose(
                x, w, include_collision=False, include_midline=False
            )
            residual = (targets - pred).reshape(-1)
            w2 = np.repeat(w, 2)
            residual_w = residual * w2

            J = np.zeros((residual.shape[0], active.size), dtype=np.float64)
            for col, d in enumerate(active):
                x[d] += eps
                pred_p, _ = eval_pose(
                    x, w, include_collision=False, include_midline=False
                )
                x[d] -= 2.0 * eps
                pred_m, _ = eval_pose(
                    x, w, include_collision=False, include_midline=False
                )
                x[d] += eps
                jp = (pred_p - pred_m).reshape(-1) / (2.0 * eps)
                J[:, col] = jp * w2

            jt = J.T
            a = jt @ J
            a += (damping * damping) * np.eye(active.size)
            try:
                dx_active = np.linalg.solve(a, jt @ residual_w)
            except np.linalg.LinAlgError:
                dx_active = jt @ residual_w
                nrm = float(np.linalg.norm(dx_active)) + 1e-8
                dx_active = dx_active / nrm * min(0.15, nrm)

            improved = False
            for scale in (1.0, 0.5, 0.25, 0.12, 0.06):
                trial = x.copy()
                trial[active] = trial[active] + scale * dx_active
                trial = clamp_step(np.clip(trial, lo, hi))
                ok_t, _pt, trial_loss, _rt = accept_pose(
                    trial, w, check_body_landmarks=check_body
                )
                if not ok_t:
                    body_rejects += 1
                    continue
                if trial_loss < best - 1e-4:
                    x = trial
                    best = trial_loss
                    best_x = x.copy()
                    improved = True
                    break

            if improved:
                stall = 0
                continue

            stall += 1
            if stall >= plateau_steps:
                stage_stop = "plateau"
                break

            frac = min(jolt_frac_max, jolt_frac * (jolt_grow**jolts))
            span = hi - lo
            noise = np.zeros(n_dof, dtype=np.float64)
            noise[active] = rng.uniform(-1.0, 1.0, size=active.size) * (
                span[active] * frac * 0.5
            )
            trial = clamp_step(np.clip(best_x + noise, lo, hi))
            jolts += 1
            ok_j, _pj, jolt_loss, _rj = accept_pose(
                trial, w, check_body_landmarks=check_body
            )
            if not ok_j:
                body_rejects += 1
                x = best_x.copy()
                continue
            x = trial
            if jolt_loss < best:
                best = jolt_loss
                best_x = x.copy()
                stall = 0

        if stage_stop == "loss_floor":
            stop_reason = "loss_floor"
            break
        if stage_stop == "plateau":
            stop_reason = "plateau"

    best_x = clamp_step(best_x)

    # Report marker MAE without rest/motion/collision regularizers.
    w_report = loss_weights(tip_priority=False)
    _apply_pose(
        arm, rest, names, x0, root_rest=root_rest, cam_axes=cam_axes, root_translate=root_translate
    )
    bpy.context.view_layer.update()
    pred_start = _project_grabs_px(arm, mesh_obj, grabs, cam, scene, sw, sh)
    start_report = _weighted_mae(pred_start, targets, w_report)
    _apply_pose(
        arm,
        rest,
        names,
        best_x,
        root_rest=root_rest,
        cam_axes=cam_axes,
        root_translate=root_translate,
    )
    bpy.context.view_layer.update()
    pred_best = _project_grabs_px(arm, mesh_obj, grabs, cam, scene, sw, sh)
    best_report = _weighted_mae(pred_best, targets, w_report)
    if collision_bias is not None:
        last_collision_pen, last_collision_hits = _collision_penalty(mesh_obj, collision_bias)
    if midline_bias is not None:
        last_midline_pen, last_midline_hits, last_midline_offenders = _midline_penalty(
            arm, midline_bias
        )

    return best_x, {
        "startLossPx": start_report,
        "lossPx": best_report,
        "steps": None if stop_reason in ("loss_floor", "plateau") else max_steps,
        "maxSteps": max_steps,
        "jolts": jolts,
        "ccdTipIterations": ccd_used,
        "bodyRejects": body_rejects,
        "bodyStartErrPx": body_start_err,
        "stopReason": stop_reason,
        "plateauSteps": plateau_steps,
        "markerCount": len(markers),
        "markerNames": [m[0] for m in markers],
        "markerVerts": [m[1] for m in markers],
        "tipErrorPx": tip_err_px(pred_best),
        "maxStepRad": max_step_rad,
        "stepClamps": int(step_clamps),
        "stepMaxExcessRad": float(step_max_excess),
        "collisionPenalty": float(last_collision_pen),
        "collisionHits": int(last_collision_hits),
        "midlinePenalty": float(last_midline_pen),
        "midlineHits": int(last_midline_hits),
        "midlineRejects": int(midline_rejects),
        "midlineOffenders": list(last_midline_offenders[:12]),
        "authoredEulerAxes": (
            None
            if authored_axes is None
            else {
                name: [ax for ax, on in zip(("x", "y", "z"), free) if on]
                for name, free in authored_axes.items()
            }
        ),
        "authoredFreeRotDof": (
            None
            if authored_axis_mask is None
            else int(np.count_nonzero(authored_axis_mask[:n_rot]))
        ),
    }


def _register_camera_to_frame0(
    *,
    job: dict,
    arm,
    scene,
    rest,
    names: list[str],
    midhip_bone: str,
    nose_bone: str | None,
    targets_by_joint: dict[str, tuple[float, float]],
    sw: float,
    sh: float,
    root_rest: Vector,
) -> tuple[object, tuple[Vector, Vector, Vector], float]:
    """Tune orthoScale using bone MidHip/Nose as a coarse framing meter (pre-mesh pick)."""
    cfg = dict(job.get("camera") or {})
    base = float(cfg.get("orthoScale", 2.6))
    best_scale = base
    best_err = 1e18
    x0 = np.zeros(len(names) * 3, dtype=np.float64)
    joints = [("MidHip", midhip_bone, "head")]
    if nose_bone:
        joints.append(("Nose", nose_bone, "head"))

    for scale in np.linspace(max(0.8, base * 0.55), base * 1.55, 21):
        for obj in list(scene.objects):
            if obj.type == "CAMERA":
                bpy.data.objects.remove(obj, do_unlink=True)
        job_cam = dict(job)
        job_cam["camera"] = dict(cfg)
        job_cam["camera"]["orthoScale"] = float(scale)
        cam = setup_pose_camera(job_cam, arm, bpy_module=bpy)
        m = cam.matrix_world.to_3x3()
        axes = (
            (m @ Vector((1.0, 0.0, 0.0))).normalized(),
            (m @ Vector((0.0, 1.0, 0.0))).normalized(),
            (m @ Vector((0.0, 0.0, -1.0))).normalized(),
        )
        _apply_pose(
            arm, rest, names, x0, root_rest=root_rest, cam_axes=axes, root_translate=False
        )
        bpy.context.view_layer.update()
        err = 0.0
        n = 0
        for jn, bone, end in joints:
            if jn not in targets_by_joint:
                continue
            px, py = _project_world_px(_bone_end_world(arm, bone, end), cam, scene, sw, sh)
            tx, ty = targets_by_joint[jn]
            err += math.hypot(px - tx, py - ty)
            n += 1
        if n == 0:
            continue
        err /= n
        if err < best_err:
            best_err = err
            best_scale = float(scale)

    # Rebuild the winning camera once (search loop deletes cameras each trial).
    for obj in list(scene.objects):
        if obj.type == "CAMERA":
            bpy.data.objects.remove(obj, do_unlink=True)
    job_cam = dict(job)
    job_cam["camera"] = dict(cfg)
    job_cam["camera"]["orthoScale"] = float(best_scale)
    best_cam = setup_pose_camera(job_cam, arm, bpy_module=bpy)
    m = best_cam.matrix_world.to_3x3()
    best_axes = (
        (m @ Vector((1.0, 0.0, 0.0))).normalized(),
        (m @ Vector((0.0, 1.0, 0.0))).normalized(),
        (m @ Vector((0.0, 0.0, -1.0))).normalized(),
    )
    scene.camera = best_cam
    print(
        f"[marker-ik] frame0 camera register orthoScale={best_scale:.3f} "
        f"(from {base:.3f}) boneMeterLossPx={best_err:.2f}",
        flush=True,
    )
    job.setdefault("camera", {})["orthoScale"] = best_scale
    return best_cam, best_axes, best_scale


def _root_align_midhip_mesh(
    *,
    arm,
    mesh_obj,
    cam,
    scene,
    rest,
    names,
    markers: list[tuple[str, int, str, float]],
    targets: np.ndarray,
    sw,
    sh,
    root_rest,
    cam_axes,
    root_bound: float,
    root_translate: bool,
    freeze_root_up: bool = False,
) -> np.ndarray:
    n_rot = len(names) * 3
    n_dof = n_rot + (3 if root_translate else 0)
    x = np.zeros(n_dof, dtype=np.float64)
    mid_i = next((i for i, m in enumerate(markers) if m[0] == "MidHip"), None)
    if mid_i is None or not root_translate:
        return x
    best = 1e9
    best_x = x.copy()
    tu_vals = [0.0] if freeze_root_up else list(np.linspace(-root_bound, root_bound, 11))
    for tr in np.linspace(-root_bound, root_bound, 11):
        for tu in tu_vals:
            x[n_rot] = tr
            x[n_rot + 1] = tu
            x[n_rot + 2] = 0.0
            _apply_pose(
                arm, rest, names, x, root_rest=root_rest, cam_axes=cam_axes, root_translate=True
            )
            bpy.context.view_layer.update()
            pred = _project_mesh_markers_px(arm, mesh_obj, markers, cam, scene, sw, sh)
            err = float(np.linalg.norm(pred[mid_i] - targets[mid_i]))
            if err < best:
                best = err
                best_x = x.copy()
    return best_x


def run(job_path: Path, keypoints_path: Path, roles_path: Path) -> dict:
    job = json.loads(job_path.read_text(encoding="utf-8"))
    kpt_report = json.loads(keypoints_path.read_text(encoding="utf-8"))
    roles = json.loads(roles_path.read_text(encoding="utf-8"))
    if not kpt_report.get("ok"):
        raise RuntimeError(f"keypoints not ok: {keypoints_path}")

    cfg = dict(job.get("markerIk") or {})
    out_dir = Path(job["outputDir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    _clear_scene()
    arm, mesh = _import_master(Path(job["masterGlb"]))
    _clear_animation(arm)
    cam = setup_pose_camera(job, arm, bpy_module=bpy)
    scene = bpy.context.scene
    m = cam.matrix_world.to_3x3()
    cam_axes = (
        (m @ Vector((1.0, 0.0, 0.0))).normalized(),
        (m @ Vector((0.0, 1.0, 0.0))).normalized(),
        (m @ Vector((0.0, 0.0, -1.0))).normalized(),
    )

    names = list(
        cfg.get("optimizeBones")
        or roles.get("optimizeBones")
        or job.get("optimizeBones")
        or []
    )
    if not names:
        raise RuntimeError("optimizeBones empty")
    rest = _collect_rest(arm, names)
    root_rest = arm.location.copy()

    root_translate = bool(cfg.get("rootTranslate", True))
    bound_rad = float(cfg.get("boundRad", 1.10))
    root_bound = float(cfg.get("rootTranslateBound", 0.85))
    identity_f0 = bool(cfg.get("identityFrame0", True))
    f0_root_align = bool(cfg.get("frame0RootAlign", True))
    f0_cam_register = bool(cfg.get("frame0CameraRegister", True))
    ga_mode, ga_bones = _ground_anchor_settings(cfg)
    freeze_root_translate, freeze_root_up = _root_freeze_flags(ga_mode)
    if (freeze_root_translate or freeze_root_up) and not root_translate:
        raise RuntimeError(
            f"groundAnchor.mode={ga_mode} requires markerIk.rootTranslate=true"
        )
    ground_z: float | None = None
    root0: tuple[float, float, float] | None = None
    loc0_xy: tuple[float, float] | None = None
    if ga_mode == "lowest_foot":
        print(
            f"[marker-ik] groundAnchor=lowest_foot bones={ga_bones} (freeze camera-up root DOF)",
            flush=True,
        )
    elif ga_mode == "frame0_root":
        print(
            "[marker-ik] groundAnchor=frame0_root (freeze all root translate DOFs after frame0)",
            flush=True,
        )
    elif ga_mode == "frame0_lateral_lowest_foot":
        print(
            "[marker-ik] groundAnchor=frame0_lateral_lowest_foot "
            "(pin root XY to frame0; plant lowest foot on frame0 ground Z)",
            flush=True,
        )
    max_step_rad_cfg = float(cfg.get("maxStepRad", 0.0) or 0.0)
    if max_step_rad_cfg > 0.0:
        print(f"[marker-ik] maxStepRad={max_step_rad_cfg:.3f}", flush=True)
    collision_settings = _collision_bias_settings(cfg)
    collision_bias: dict | None = None
    if collision_settings is not None:
        print(
            f"[marker-ik] collisionBias samples={collision_settings['sampleCount']} "
            f"gmin={collision_settings['geodesicMinHops']} "
            f"margin={collision_settings['margin']:.4f} "
            f"weight={collision_settings['weight']:.2f}",
            flush=True,
        )
        collision_bias = _build_collision_bias(mesh, collision_settings)
        print(
            f"[marker-ik] collisionBias built samples={collision_bias['sampleCount']} "
            f"pairs={collision_bias['pairCount']}",
            flush=True,
        )
    midline_settings = _midline_bias_settings(cfg)
    midline_bias: dict | None = None
    if midline_settings is not None:
        hips_bone = midline_settings.get("hipsBone") or (roles.get("joints") or {}).get(
            "MidHip"
        )
        if not hips_bone:
            raise RuntimeError(
                "midlineBias enabled but hipsBone / roles.joints.MidHip is missing"
            )
        # Capture bind-side signs at rest (identity) before any frame solve.
        _apply_pose(
            arm,
            rest,
            names,
            np.zeros(len(names) * 3 + (3 if root_translate else 0), dtype=np.float64),
            root_rest=root_rest,
            cam_axes=cam_axes,
            root_translate=root_translate,
        )
        bpy.context.view_layer.update()
        midline_bias = _build_midline_bias(
            arm, names, midline_settings, hips_bone=str(hips_bone)
        )
        print(
            f"[marker-ik] midlineBias bones={midline_bias['constrainedCount']} "
            f"skipped={len(midline_bias['skipped'])} margin={midline_bias['margin']:.4f} "
            f"weight={midline_bias['weight']:.2f} hardReject={midline_bias['hardReject']}",
            flush=True,
        )
        for entry in midline_bias["bones"]:
            print(
                f"[marker-ik] midline side {entry['name']} sign={entry['sign']:+.0f} "
                f"bindAbs={entry['bindAbs']:.4f}",
                flush=True,
            )
    frames = sorted(kpt_report["frames"], key=lambda f: f["frameIndex"])
    n_rot = len(names) * 3
    n_dof = n_rot + (3 if root_translate else 0)
    x = np.zeros(n_dof, dtype=np.float64)
    pose_vectors: list[np.ndarray] = []
    frame_reports = []
    prev_vert_by_joint: dict[str, int] = {}

    print(
        f"[marker-ik] mesh-vert grabs; temporal key=previous pose; "
        f"bones={len(names)} dof={n_dof} identityFrame0={identity_f0}",
        flush=True,
    )

    for fr in frames:
        i = int(fr["frameIndex"])
        sw = float(fr["transform"]["srcWidth"])
        sh = float(fr["transform"]["srcHeight"])
        joint_names, targets, weights = _sprite_targets(fr["joints"], roles, cfg)

        # Always begin from previous solved pose (identity on frame 0).
        _apply_pose(
            arm,
            rest,
            names,
            x,
            root_rest=root_rest,
            cam_axes=cam_axes,
            root_translate=root_translate,
        )
        bpy.context.view_layer.update()

        if i == 0 and f0_cam_register:
            tmap = {jn: (float(targets[k, 0]), float(targets[k, 1])) for k, jn in enumerate(joint_names)}
            cam, cam_axes, _scale = _register_camera_to_frame0(
                job=job,
                arm=arm,
                scene=scene,
                rest=rest,
                names=names,
                midhip_bone=roles["joints"]["MidHip"],
                nose_bone=roles["joints"].get("Nose"),
                targets_by_joint=tmap,
                sw=sw,
                sh=sh,
                root_rest=root_rest,
            )
            _apply_pose(
                arm,
                rest,
                names,
                x,
                root_rest=root_rest,
                cam_axes=cam_axes,
                root_translate=root_translate,
            )
            bpy.context.view_layer.update()

        # Grab verts: frame 0 picks from current (A-pose) mesh; later frames keep
        # those surface points. Optional tip re-key from previous posed mesh.
        lock_grabs = bool(cfg.get("lockGrabVertsAfterFrame0", True))
        if lock_grabs and i > 0 and prev_vert_by_joint:
            joint_to_bone = roles["joints"]
            markers = []
            need_pick_names: list[str] = []
            need_pick_idx: list[int] = []
            for k, jn in enumerate(joint_names):
                if jn in prev_vert_by_joint:
                    markers.append(
                        (jn, int(prev_vert_by_joint[jn]), joint_to_bone[jn], float(weights[k]))
                    )
                else:
                    markers.append(None)  # type: ignore[arg-type]
                    need_pick_names.append(jn)
                    need_pick_idx.append(k)
            if need_pick_names:
                extra = _pick_mesh_markers_from_pose(
                    mesh_obj=mesh,
                    arm=arm,
                    cam=cam,
                    scene=scene,
                    joint_names=need_pick_names,
                    targets=targets[need_pick_idx],
                    weights=weights[need_pick_idx],
                    roles=roles,
                    cfg=cfg,
                    sw=sw,
                    sh=sh,
                    prev_vert_by_joint=prev_vert_by_joint,
                )
                by_name = {m[0]: m for m in extra}
                markers = [
                    by_name[jn] if m is None else m for jn, m in zip(joint_names, markers)
                ]
            rekey_px = float(cfg.get("rekeyTipIfErrorPx", 90.0))
            tip_entry = next((m for m in markers if m[0] == "WeaponTip"), None)
            tip_mode = str(cfg.get("tipPickMode", "screen_nearest"))
            # farthest_from_hand tip stays locked; do not screen-rekey onto the wrist.
            if tip_entry is not None and rekey_px > 0 and tip_mode != "farthest_from_hand":
                grabs_tmp = _grabs_from_markers(mesh, [tip_entry])
                tip_pred = _project_grabs_px(arm, mesh, grabs_tmp, cam, scene, sw, sh)[0]
                tip_tgt = targets[joint_names.index("WeaponTip")]
                if float(np.linalg.norm(tip_pred - tip_tgt)) >= rekey_px:
                    tip_only = _pick_mesh_markers_from_pose(
                        mesh_obj=mesh,
                        arm=arm,
                        cam=cam,
                        scene=scene,
                        joint_names=["WeaponTip"],
                        targets=np.asarray([tip_tgt], dtype=np.float64),
                        weights=np.asarray(
                            [weights[joint_names.index("WeaponTip")]], dtype=np.float64
                        ),
                        roles=roles,
                        cfg=cfg,
                        sw=sw,
                        sh=sh,
                        prev_vert_by_joint={"WeaponTip": tip_entry[1]},
                    )
                    markers = [tip_only[0] if m[0] == "WeaponTip" else m for m in markers]
        else:
            markers = _pick_mesh_markers_from_pose(
                mesh_obj=mesh,
                arm=arm,
                cam=cam,
                scene=scene,
                joint_names=joint_names,
                targets=targets,
                weights=weights,
                roles=roles,
                cfg=cfg,
                sw=sw,
                sh=sh,
                prev_vert_by_joint=prev_vert_by_joint,
            )
        print(
            f"[marker-ik] frame {i} grabs "
            + ", ".join(f"{jn}@v{vi}" for jn, vi, _b, _w in markers),
            flush=True,
        )

        if i == 0 and f0_root_align and root_translate:
            x = _root_align_midhip_mesh(
                arm=arm,
                mesh_obj=mesh,
                cam=cam,
                scene=scene,
                rest=rest,
                names=names,
                markers=markers,
                targets=targets,
                sw=sw,
                sh=sh,
                root_rest=root_rest,
                cam_axes=cam_axes,
                root_bound=root_bound,
                root_translate=root_translate,
                freeze_root_up=freeze_root_up,
            )
            _apply_pose(
                arm,
                rest,
                names,
                x,
                root_rest=root_rest,
                cam_axes=cam_axes,
                root_translate=root_translate,
            )
            bpy.context.view_layer.update()

        if i == 0 and identity_f0:
            pred = _project_mesh_markers_px(arm, mesh, markers, cam, scene, sw, sh)
            loss = _weighted_mae(pred, targets, weights)
            stats = {
                "startLossPx": loss,
                "lossPx": loss,
                "steps": 0,
                "maxSteps": 0,
                "jolts": 0,
                "stopReason": "identity_frame0",
                "markerCount": len(markers),
                "markerNames": [m[0] for m in markers],
                "markerVerts": [m[1] for m in markers],
                "frame0RootAlign": bool(f0_root_align and root_translate),
                "frame0CameraRegister": f0_cam_register,
                "orthoScale": float((job.get("camera") or {}).get("orthoScale", 2.6)),
            }
            if collision_bias is not None:
                pen, hits = _collision_penalty(mesh, collision_bias)
                stats["collisionPenalty"] = pen
                stats["collisionHits"] = hits
            if midline_bias is not None:
                pen_m, hits_m, offenders = _midline_penalty(arm, midline_bias)
                stats["midlinePenalty"] = pen_m
                stats["midlineHits"] = hits_m
                stats["midlineRejects"] = 0
                stats["midlineOffenders"] = offenders[:12]
            print(
                f"[marker-ik] frame 0 IDENTITY lossPx={stats['lossPx']:.2f} "
                f"ortho={stats['orthoScale']:.3f} grabs "
                + ", ".join(f"{jn}@v{vi}" for jn, vi, _b, _w in markers),
                flush=True,
            )
        else:
            x, stats = _solve_frame_ik(
                arm=arm,
                mesh_obj=mesh,
                cam=cam,
                scene=scene,
                rest=rest,
                names=names,
                markers=markers,
                targets=targets,
                x0=x,
                sw=sw,
                sh=sh,
                cfg=cfg,
                root_rest=root_rest,
                cam_axes=cam_axes,
                root_translate=root_translate,
                bound_rad=bound_rad,
                root_bound=root_bound,
                frame_index=i,
                roles=roles,
                collision_bias=collision_bias,
                midline_bias=midline_bias,
            )
            print(
                f"[marker-ik] frame {i} start={stats['startLossPx']:.2f} "
                f"best={stats['lossPx']:.2f} tipErr={stats.get('tipErrorPx', -1):.1f} "
                f"jolts={stats['jolts']} ccd={stats.get('ccdTipIterations', 0)} "
                f"bodyRejects={stats.get('bodyRejects', 0)} "
                f"midRejects={stats.get('midlineRejects', 0)} "
                f"midHits={stats.get('midlineHits', 0)} "
                f"collHits={stats.get('collisionHits', 0)} "
                f"collPen={stats.get('collisionPenalty', 0.0):.3f} "
                f"stop={stats['stopReason']}",
                flush=True,
            )

        if ga_mode == "frame0_root":
            if not root_translate or len(x) < n_rot + 3:
                raise RuntimeError("frame0_root requires root translate DOFs")
            if i == 0:
                root0 = (float(x[n_rot]), float(x[n_rot + 1]), float(x[n_rot + 2]))
                stats["groundAnchor"] = {
                    "mode": ga_mode,
                    "root0": list(root0),
                    "locked": False,
                }
                print(
                    f"[marker-ik] root0=({root0[0]:+.4f},{root0[1]:+.4f},{root0[2]:+.4f}) "
                    f"(frame0 overall position)",
                    flush=True,
                )
            else:
                if root0 is None:
                    raise RuntimeError("groundAnchor missing frame0 root0")
                x = np.asarray(x, dtype=np.float64).copy()
                x[n_rot] = root0[0]
                x[n_rot + 1] = root0[1]
                x[n_rot + 2] = root0[2]
                _apply_pose(
                    arm,
                    rest,
                    names,
                    x,
                    root_rest=root_rest,
                    cam_axes=cam_axes,
                    root_translate=root_translate,
                )
                bpy.context.view_layer.update()
                stats["groundAnchor"] = {
                    "mode": ga_mode,
                    "root0": list(root0),
                    "root": [float(x[n_rot]), float(x[n_rot + 1]), float(x[n_rot + 2])],
                    "locked": True,
                }
                print(
                    f"[marker-ik] frame {i} rootLock "
                    f"rt={x[n_rot]:+.4f} ru={x[n_rot + 1]:+.4f} rf={x[n_rot + 2]:+.4f}",
                    flush=True,
                )
        elif ga_mode == "frame0_lateral_lowest_foot":
            if not root_translate or len(x) < n_rot + 3:
                raise RuntimeError(
                    "frame0_lateral_lowest_foot requires root translate DOFs"
                )
            if i == 0:
                root0 = (float(x[n_rot]), float(x[n_rot + 1]), float(x[n_rot + 2]))
                _apply_pose(
                    arm,
                    rest,
                    names,
                    x,
                    root_rest=root_rest,
                    cam_axes=cam_axes,
                    root_translate=root_translate,
                )
                bpy.context.view_layer.update()
                loc0_xy = (float(arm.location.x), float(arm.location.y))
                ground_z = _min_foot_world_z(arm, ga_bones)
                stats["groundAnchor"] = {
                    "mode": ga_mode,
                    "bones": ga_bones,
                    "root0": list(root0),
                    "loc0xy": list(loc0_xy),
                    "groundZ": ground_z,
                    "locked": False,
                }
                print(
                    f"[marker-ik] root0=({root0[0]:+.4f},{root0[1]:+.4f},{root0[2]:+.4f}) "
                    f"loc0xy=({loc0_xy[0]:+.4f},{loc0_xy[1]:+.4f}) "
                    f"groundZ={ground_z:.4f}",
                    flush=True,
                )
            else:
                if ground_z is None or loc0_xy is None or root0 is None:
                    raise RuntimeError(
                        "groundAnchor missing frame0 groundZ/loc0xy/root0"
                    )
                x, z_before, z_after, dz = _apply_frame0_lateral_lowest_foot_lock(
                    arm=arm,
                    rest=rest,
                    names=names,
                    x=x,
                    root_rest=root_rest,
                    cam_axes=cam_axes,
                    root_translate=root_translate,
                    ground_z=ground_z,
                    foot_bones=ga_bones,
                    loc0_xy=loc0_xy,
                )
                stats["groundAnchor"] = {
                    "mode": ga_mode,
                    "bones": ga_bones,
                    "root0": list(root0),
                    "loc0xy": list(loc0_xy),
                    "groundZ": ground_z,
                    "minFootZBefore": z_before,
                    "minFootZAfter": z_after,
                    "deltaZ": dz,
                    "root": [float(x[n_rot]), float(x[n_rot + 1]), float(x[n_rot + 2])],
                    "locked": True,
                }
                print(
                    f"[marker-ik] frame {i} plant dz={dz:+.4f} "
                    f"footZ {z_before:.4f}->{z_after:.4f} "
                    f"root=({x[n_rot]:+.4f},{x[n_rot + 1]:+.4f},{x[n_rot + 2]:+.4f})",
                    flush=True,
                )
        elif ga_mode == "lowest_foot":
            if i == 0:
                _apply_pose(
                    arm,
                    rest,
                    names,
                    x,
                    root_rest=root_rest,
                    cam_axes=cam_axes,
                    root_translate=root_translate,
                )
                bpy.context.view_layer.update()
                ground_z = _min_foot_world_z(arm, ga_bones)
                stats["groundAnchor"] = {
                    "mode": ga_mode,
                    "bones": ga_bones,
                    "groundZ": ground_z,
                    "locked": False,
                }
                print(f"[marker-ik] groundZ={ground_z:.4f} (frame0 contact)", flush=True)
            else:
                if ground_z is None:
                    raise RuntimeError("groundAnchor missing frame0 groundZ")
                x, z_before, z_after = _apply_lowest_foot_ground_lock(
                    arm=arm,
                    rest=rest,
                    names=names,
                    x=x,
                    root_rest=root_rest,
                    cam_axes=cam_axes,
                    root_translate=root_translate,
                    ground_z=ground_z,
                    foot_bones=ga_bones,
                )
                stats["groundAnchor"] = {
                    "mode": ga_mode,
                    "bones": ga_bones,
                    "groundZ": ground_z,
                    "minFootZBefore": z_before,
                    "minFootZAfter": z_after,
                    "deltaZ": float(ground_z - z_before),
                    "locked": True,
                }
                print(
                    f"[marker-ik] frame {i} groundLock dz={ground_z - z_before:+.4f} "
                    f"footZ {z_before:.4f}->{z_after:.4f}",
                    flush=True,
                )

        if max_step_rad_cfg > 0.0 and int(stats.get("stepClamps", 0) or 0) > 0:
            print(
                f"[marker-ik] frame {i} stepClamps={stats.get('stepClamps')} "
                f"maxExcess={float(stats.get('stepMaxExcessRad', 0.0)):.4f}",
                flush=True,
            )

        prev_vert_by_joint = {m[0]: m[1] for m in markers}
        pose_vectors.append(np.array(x, dtype=np.float64, copy=True))
        frame_reports.append({"frameIndex": i, **stats})

    job_path.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")

    root_yaw = float(job.get("camera", {}).get("rootYawDeg", 0.0))
    _bake_action(
        arm,
        rest,
        names,
        pose_vectors,
        root_rest=root_rest,
        cam_axes=cam_axes,
        root_translate=root_translate,
        root_yaw_deg=root_yaw,
    )
    scene.frame_start = 1
    scene.frame_end = max(1, len(pose_vectors))
    scene.render.fps = int(round(float(job.get("fps", 12))))

    export_glb = out_dir / f"{job.get('clipId', 'clip')}_marker_ik.glb"
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
    if not export_glb.is_file() or export_glb.stat().st_size < 1000:
        raise RuntimeError(f"marker IK GLB export missing/empty: {export_glb}")

    report = {
        "unitSid": job.get("unitSid"),
        "clipId": job.get("clipId"),
        "method": "marker_ik_mesh_verts",
        "frameCount": len(pose_vectors),
        "poseVectors": [v.tolist() for v in pose_vectors],
        "optimizeBones": names,
        "rootTranslate": root_translate,
        "groundAnchor": {
            "mode": ga_mode,
            "bones": ga_bones,
            "groundZ": ground_z,
            "root0": list(root0) if root0 is not None else None,
            "loc0xy": list(loc0_xy) if loc0_xy is not None else None,
            "freezeRootTranslate": freeze_root_translate,
            "freezeRootUp": freeze_root_up,
        },
        "maxStepRad": max_step_rad_cfg,
        "collisionBias": (
            None
            if collision_bias is None
            else {
                "enabled": True,
                "sampleCount": int(collision_bias["sampleCount"]),
                "pairCount": int(collision_bias["pairCount"]),
                "geodesicMinHops": int(collision_bias["geodesicMinHops"]),
                "margin": float(collision_bias["margin"]),
                "weight": float(collision_bias["weight"]),
                "crossComponentPairs": int(collision_bias.get("crossComponentPairs", 0)),
            }
        ),
        "midlineBias": (
            None
            if midline_bias is None
            else {
                "enabled": True,
                "hipsBone": midline_bias["hipsBone"],
                "leftRefBone": midline_bias["leftRefBone"],
                "rightRefBone": midline_bias["rightRefBone"],
                "leftAxisArmLocal": midline_bias["leftAxisArmLocal"],
                "sampleEnds": midline_bias["sampleEnds"],
                "margin": float(midline_bias["margin"]),
                "weight": float(midline_bias["weight"]),
                "hardReject": bool(midline_bias["hardReject"]),
                "minBindAbs": float(midline_bias["minBindAbs"]),
                "constrainedCount": int(midline_bias["constrainedCount"]),
                "bones": midline_bias["bones"],
                "skipped": midline_bias["skipped"],
            }
        ),
        "boneEulerAxesSchedule": cfg.get("boneEulerAxesSchedule"),
        "poseVectorLayout": (
            "euler_xyz_per_optimizeBone_then_optional_camera_plane_root_translate_rt_ru_rf"
        ),
        "exportGlb": str(export_glb).replace("\\", "/"),
        "exportBytes": int(export_glb.stat().st_size),
        "frames": frame_reports,
        "meanLossPx": float(np.mean([f["lossPx"] for f in frame_reports])),
        "proof": (
            "generated artifact validated — mesh-vertex marker IK keyed from previous "
            "frame pose; animated GLB exported; not OE runtime proven"
        ),
    }
    (out_dir / "fit_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out_dir / "fit_report_kpt.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(out_dir / "fit_report.json"), "glb": str(export_glb)}, indent=2), flush=True)
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
