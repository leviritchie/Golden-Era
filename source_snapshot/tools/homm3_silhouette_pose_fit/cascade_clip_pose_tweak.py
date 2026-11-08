"""Manual freeze/rotate of GPU clip poses. Does not search or damp.

Agents inspect a ``gpu_clip_result.json``, apply named joint edits, and
re-raster unlit RGB. Search, keep/zero, and physics are not invoked.
"""
from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cascade_sprite_aligned_motion import SPRITE_ALIGNED_MIN_TRAVEL_DEG
from roc_gpu_cascade_experiment import MOTION_ROOT_KEY, MOTION_ROOT_ROTATION_KEY

BONE_AXES = ("x", "y", "z")
ROOT_TRANSLATION_AXES = ("forward", "lateral", "vertical")
ROOT_ROTATION_AXES = ("camera_forward", "camera_right", "camera_up")
ROOT_TRANSLATION_ALIASES = frozenset({MOTION_ROOT_KEY, "root_translation", "rootTranslation"})
ROOT_ROTATION_ALIASES = frozenset({MOTION_ROOT_ROTATION_KEY, "root_rotation", "rootRotation"})
ALLOWED_OPS = frozenset({"freeze", "rotate", "set", "copy_frame", "translate_root"})
STALE_AFTER_TWEAK = (
    "score",
    "frameScores",
    "frameIoU",
    "frameChromaQuality",
    "frameCollisionError",
    "frameDepthError",
    "frameMotionQuality",
    "frameDenseSemanticQuality",
    "evaluationCount",
    "elapsed",
    "collisionVetoCount",
    "chainSpaceHistory",
    "spriteAlignedMotionKeep",
    "physicsSmooth",
    "history",
    "rgbDir",
    "rgbGif",
    "previewGif",
    "gpuAlphaDir",
    "gpuAlphaGif",
    "depthComparison",
    "clipResultPath",
)


def load_clip_result(path: str | Path) -> dict[str, Any]:
    clip_path = Path(path).resolve()
    if not clip_path.is_file():
        raise FileNotFoundError(f"gpu clip result is missing: {clip_path}")
    payload = json.loads(clip_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{clip_path} is not a JSON object")
    poses = payload.get("poses")
    if not isinstance(poses, Mapping) or not poses:
        raise ValueError(f"{clip_path} has no poses")
    frames = payload.get("frameIndices")
    if not isinstance(frames, Sequence) or not frames:
        raise ValueError(f"{clip_path} has no frameIndices")
    return payload


def clip_frame_indices(payload: Mapping[str, Any]) -> tuple[int, ...]:
    return tuple(int(frame) for frame in payload["frameIndices"])


def clone_poses(payload: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    poses: dict[int, dict[str, Any]] = {}
    for raw_frame, pose in payload["poses"].items():
        if not isinstance(pose, Mapping):
            raise ValueError(f"pose for frame {raw_frame!r} is not an object")
        poses[int(raw_frame)] = copy.deepcopy(dict(pose))
    missing = [frame for frame in clip_frame_indices(payload) if frame not in poses]
    if missing:
        raise ValueError(f"poses are missing frames: {missing}")
    return poses


def known_joint_names(payload: Mapping[str, Any]) -> frozenset[str]:
    names = set()
    for key in ("skinnedBones", "bones", "searchBones"):
        values = payload.get(key)
        if isinstance(values, Sequence):
            names.update(str(name) for name in values)
    for pose in payload["poses"].values():
        if isinstance(pose, Mapping):
            names.update(
                str(name)
                for name in pose
                if name not in {MOTION_ROOT_KEY, MOTION_ROOT_ROTATION_KEY}
            )
    names.update(ROOT_TRANSLATION_ALIASES)
    names.update(ROOT_ROTATION_ALIASES)
    return frozenset(names)


def canonicalize_joint_name(name: str, known: frozenset[str]) -> str:
    token = str(name).strip()
    if not token:
        raise ValueError("joint name must be non-empty")
    if token in ROOT_TRANSLATION_ALIASES:
        return MOTION_ROOT_KEY
    if token in ROOT_ROTATION_ALIASES:
        return MOTION_ROOT_ROTATION_KEY
    if token not in known:
        raise ValueError(f"unknown joint {token!r}")
    return token


def parse_frame_spec(spec: Any, frame_indices: Sequence[int]) -> tuple[int, ...]:
    allowed = tuple(int(frame) for frame in frame_indices)
    allowed_set = set(allowed)
    if spec is None or spec == "all":
        return allowed
    if isinstance(spec, bool) or spec is None:
        raise ValueError(f"illegal frame spec: {spec!r}")
    if isinstance(spec, int):
        values = [int(spec)]
    elif isinstance(spec, str):
        text = spec.strip()
        if text == "all":
            return allowed
        values = []
        for part in text.split(","):
            token = part.strip()
            if not token:
                raise ValueError(f"empty entry in frame spec {spec!r}")
            if "-" in token:
                ends = token.split("-")
                if len(ends) != 2 or not ends[0].strip() or not ends[1].strip():
                    raise ValueError(f"frame range must be start-end, got {token!r}")
                start = int(ends[0])
                end = int(ends[1])
                if end < start:
                    raise ValueError(f"frame range {token!r} is reversed")
                values.extend(range(start, end + 1))
            else:
                values.append(int(token))
    elif isinstance(spec, Sequence):
        values = [int(item) for item in spec]
    else:
        raise ValueError(f"illegal frame spec: {spec!r}")
    if not values:
        raise ValueError("frame spec selected no frames")
    unknown = [frame for frame in values if frame not in allowed_set]
    if unknown:
        raise ValueError(f"frames {unknown} are not in this clip")
    seen: set[int] = set()
    ordered: list[int] = []
    for frame in values:
        if frame not in seen:
            seen.add(frame)
            ordered.append(frame)
    return tuple(ordered)


def load_hierarchy(mesh_glb: str | Path) -> dict[str, dict[str, Any]]:
    from roc_geometric_proxy import load_asset

    asset = load_asset(Path(mesh_glb).resolve(), decode_images=False)
    names = [str(node.name) for node in asset.nodes]
    if len(set(names)) != len(names):
        raise ValueError(f"{mesh_glb} has duplicate node names")
    hierarchy: dict[str, dict[str, Any]] = {}
    for node in asset.nodes:
        parent = None if node.parent is None else str(asset.nodes[int(node.parent)].name)
        children = tuple(str(asset.nodes[int(child)].name) for child in node.children)
        hierarchy[str(node.name)] = {
            "index": int(node.index),
            "parent": parent,
            "children": children,
        }
    return hierarchy


def expand_descendants(names: Sequence[str], hierarchy: Mapping[str, Mapping[str, Any]]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()

    def _walk(name: str) -> None:
        if name in {MOTION_ROOT_KEY, MOTION_ROOT_ROTATION_KEY}:
            raise ValueError("include_descendants cannot apply to the motion root")
        if name not in hierarchy:
            raise ValueError(f"hierarchy has no joint {name!r}")
        if name not in seen:
            seen.add(name)
            ordered.append(name)
        for child in hierarchy[name]["children"]:
            _walk(str(child))

    for name in names:
        _walk(str(name))
    return tuple(ordered)


def _zero_root_translation() -> dict[str, float]:
    return {axis: 0.0 for axis in ROOT_TRANSLATION_AXES}


def _zero_root_rotation() -> dict[str, float]:
    return {axis: 0.0 for axis in ROOT_ROTATION_AXES}


def _zero_bone() -> dict[str, float]:
    return {axis: 0.0 for axis in BONE_AXES}


def bone_angles_rad(pose: Mapping[str, Any], bone: str) -> dict[str, float]:
    entry = pose.get(bone)
    if not isinstance(entry, Mapping):
        return _zero_bone()
    return {axis: float(entry.get(axis, 0.0)) for axis in BONE_AXES}


def root_translation(pose: Mapping[str, Any]) -> dict[str, float]:
    entry = pose.get(MOTION_ROOT_KEY)
    if not isinstance(entry, Mapping):
        return _zero_root_translation()
    return {axis: float(entry.get(axis, 0.0)) for axis in ROOT_TRANSLATION_AXES}


def root_rotation_deg(pose: Mapping[str, Any]) -> dict[str, float]:
    entry = pose.get(MOTION_ROOT_ROTATION_KEY)
    if not isinstance(entry, Mapping):
        return _zero_root_rotation()
    return {axis: float(entry.get(axis, 0.0)) for axis in ROOT_ROTATION_AXES}


def _write_bone(pose: dict[str, Any], bone: str, angles: Mapping[str, float]) -> None:
    if all(abs(float(angles[axis])) <= 1e-7 for axis in BONE_AXES):
        pose.pop(bone, None)
        return
    pose[bone] = {axis: float(angles[axis]) for axis in BONE_AXES}


def _copy_joint(source: Mapping[str, Any], dest: dict[str, Any], joint: str) -> None:
    if joint == MOTION_ROOT_KEY:
        dest[MOTION_ROOT_KEY] = root_translation(source)
        return
    if joint == MOTION_ROOT_ROTATION_KEY:
        dest[MOTION_ROOT_ROTATION_KEY] = root_rotation_deg(source)
        return
    if joint not in source:
        dest.pop(joint, None)
        return
    dest[joint] = copy.deepcopy(source[joint])


def _bind_joint(dest: dict[str, Any], joint: str) -> None:
    if joint == MOTION_ROOT_KEY:
        dest[MOTION_ROOT_KEY] = _zero_root_translation()
        return
    if joint == MOTION_ROOT_ROTATION_KEY:
        dest[MOTION_ROOT_ROTATION_KEY] = _zero_root_rotation()
        return
    dest.pop(joint, None)


def joint_limit_rad(payload: Mapping[str, Any], bone: str) -> float:
    config = payload.get("config") if isinstance(payload.get("config"), Mapping) else {}
    limit_deg = float(config.get("joint_limit_deg", 150.0))
    if not math.isfinite(limit_deg) or limit_deg <= 0.0:
        raise ValueError("joint_limit_deg must be finite and positive")
    scale = 1.0
    overrides = config.get("bone_limit_scale_overrides") or ()
    for entry in overrides:
        if not isinstance(entry, Sequence) or len(entry) != 2:
            continue
        if str(entry[0]) == bone:
            scale = float(entry[1])
            break
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError(f"limit scale for {bone!r} must be positive")
    return math.radians(limit_deg * scale)


def _require_finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def apply_freeze(
    poses: dict[int, dict[str, Any]],
    *,
    joints: Sequence[str],
    frames: Sequence[int],
    source: str,
    frame_indices: Sequence[int],
) -> None:
    origin = str(source).strip()
    index_by_frame = {int(frame): position for position, frame in enumerate(frame_indices)}
    for frame in frames:
        dest = poses[int(frame)]
        if origin == "bind":
            for joint in joints:
                _bind_joint(dest, joint)
            continue
        if origin == "previous":
            position = index_by_frame[int(frame)]
            if position < 1:
                raise ValueError(
                    f"cannot freeze frame {int(frame)} from previous; it is the first clip frame"
                )
            src_frame = int(frame_indices[position - 1])
        elif origin.startswith("frame:"):
            src_frame = int(origin.split(":", 1)[1])
            if src_frame not in poses:
                raise ValueError(f"freeze source frame {src_frame} is not in this clip")
        else:
            raise ValueError(
                "freeze source must be 'previous', 'bind', or 'frame:N'; "
                f"got {origin!r}"
            )
        if src_frame == int(frame):
            raise ValueError(f"freeze source frame {src_frame} is the destination")
        src = poses[src_frame]
        for joint in joints:
            _copy_joint(src, dest, joint)


def apply_rotate(
    poses: dict[int, dict[str, Any]],
    *,
    joint: str,
    frames: Sequence[int],
    axis: str,
    delta_deg: float,
    payload: Mapping[str, Any],
) -> None:
    extra = math.radians(_require_finite("delta_deg", delta_deg))
    channel = str(axis).strip()
    if joint == MOTION_ROOT_KEY:
        raise ValueError("rotate cannot move root translation; use translate_root")
    if joint == MOTION_ROOT_ROTATION_KEY:
        if channel not in ROOT_ROTATION_AXES:
            raise ValueError(f"root rotation axis must be one of {ROOT_ROTATION_AXES}")
        for frame in frames:
            current = root_rotation_deg(poses[int(frame)])
            current[channel] = current[channel] + _require_finite("delta_deg", delta_deg)
            poses[int(frame)][MOTION_ROOT_ROTATION_KEY] = current
        return
    if channel not in BONE_AXES:
        raise ValueError(f"bone axis must be one of {BONE_AXES}")
    limit = joint_limit_rad(payload, joint)
    for frame in frames:
        angles = bone_angles_rad(poses[int(frame)], joint)
        angles[channel] = angles[channel] + extra
        if abs(angles[channel]) > limit + 1e-9:
            raise ValueError(
                f"{joint} {channel} would be {math.degrees(angles[channel]):.3f} deg, "
                f"over the {math.degrees(limit):.3f} deg joint limit"
            )
        _write_bone(poses[int(frame)], joint, angles)


def apply_set(
    poses: dict[int, dict[str, Any]],
    *,
    joint: str,
    frames: Sequence[int],
    values_deg: Mapping[str, float],
    payload: Mapping[str, Any],
) -> None:
    if not values_deg:
        raise ValueError("set requires at least one axis")
    if joint == MOTION_ROOT_KEY:
        illegal = [name for name in values_deg if name not in ROOT_TRANSLATION_AXES]
        if illegal:
            raise ValueError(f"root translation set keys must be {ROOT_TRANSLATION_AXES}, got {illegal}")
        for frame in frames:
            current = root_translation(poses[int(frame)])
            for axis, value in values_deg.items():
                current[axis] = _require_finite(axis, value)
            poses[int(frame)][MOTION_ROOT_KEY] = current
        return
    if joint == MOTION_ROOT_ROTATION_KEY:
        illegal = [name for name in values_deg if name not in ROOT_ROTATION_AXES]
        if illegal:
            raise ValueError(f"root rotation set keys must be {ROOT_ROTATION_AXES}, got {illegal}")
        for frame in frames:
            current = root_rotation_deg(poses[int(frame)])
            for axis, value in values_deg.items():
                current[axis] = _require_finite(axis, value)
            poses[int(frame)][MOTION_ROOT_ROTATION_KEY] = current
        return
    illegal = [name for name in values_deg if name not in BONE_AXES]
    if illegal:
        raise ValueError(f"bone set keys must be {BONE_AXES}, got {illegal}")
    limit = joint_limit_rad(payload, joint)
    for frame in frames:
        angles = bone_angles_rad(poses[int(frame)], joint)
        for axis, value in values_deg.items():
            radians = math.radians(_require_finite(axis, value))
            if abs(radians) > limit + 1e-9:
                raise ValueError(
                    f"{joint} {axis} set to {float(value):.3f} deg is over the "
                    f"{math.degrees(limit):.3f} deg joint limit"
                )
            angles[axis] = radians
        _write_bone(poses[int(frame)], joint, angles)


def apply_translate_root(
    poses: dict[int, dict[str, Any]],
    *,
    frames: Sequence[int],
    axis: str,
    delta: float,
) -> None:
    channel = str(axis).strip()
    if channel not in ROOT_TRANSLATION_AXES:
        raise ValueError(f"root translation axis must be one of {ROOT_TRANSLATION_AXES}")
    extra = _require_finite("delta", delta)
    for frame in frames:
        current = root_translation(poses[int(frame)])
        current[channel] = current[channel] + extra
        poses[int(frame)][MOTION_ROOT_KEY] = current


def apply_copy_frame(
    poses: dict[int, dict[str, Any]],
    *,
    source_frame: int,
    frames: Sequence[int],
) -> None:
    src = int(source_frame)
    if src not in poses:
        raise ValueError(f"copy_frame source {src} is not in this clip")
    template = copy.deepcopy(poses[src])
    for frame in frames:
        if int(frame) == src:
            raise ValueError(f"copy_frame destination {frame} is the source")
        poses[int(frame)] = copy.deepcopy(template)


def _operation_joints(
    operation: Mapping[str, Any],
    *,
    known: frozenset[str],
    hierarchy: Mapping[str, Mapping[str, Any]] | None,
) -> tuple[str, ...]:
    include_descendants = bool(operation.get("include_descendants", False))
    if "bones" in operation and "bone" in operation:
        raise ValueError("operation cannot set both bone and bones")
    if "bones" in operation:
        raw = operation["bones"]
        if isinstance(raw, str):
            names = [raw]
        elif isinstance(raw, Sequence):
            names = [str(item) for item in raw]
        else:
            raise ValueError("bones must be a string or a list of names")
    elif "bone" in operation:
        names = [str(operation["bone"])]
    else:
        raise ValueError("operation needs bone or bones")
    if not names:
        raise ValueError("operation listed no joints")
    joints = tuple(canonicalize_joint_name(name, known) for name in names)
    if include_descendants:
        if hierarchy is None:
            raise ValueError("include_descendants requires --mesh hierarchy")
        return expand_descendants(joints, hierarchy)
    return joints


def apply_operations(
    payload: Mapping[str, Any],
    operations: Sequence[Mapping[str, Any]],
    *,
    hierarchy: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[int, dict[str, Any]]:
    if not operations:
        raise ValueError("no operations to apply")
    known = known_joint_names(payload)
    frames_all = clip_frame_indices(payload)
    poses = clone_poses(payload)
    for index, operation in enumerate(operations):
        if not isinstance(operation, Mapping):
            raise ValueError(f"operation {index} is not an object")
        op_name = str(operation.get("op") or "").strip()
        if op_name not in ALLOWED_OPS:
            raise ValueError(f"operation {index} has unknown op {op_name!r}")
        if op_name == "copy_frame":
            dest_frames = parse_frame_spec(operation.get("frames"), frames_all)
            if "from" not in operation:
                raise ValueError("copy_frame requires from")
            apply_copy_frame(
                poses,
                source_frame=int(operation["from"]),
                frames=dest_frames,
            )
            continue
        dest_frames = parse_frame_spec(operation.get("frames"), frames_all)
        if op_name == "translate_root":
            apply_translate_root(
                poses,
                frames=dest_frames,
                axis=str(operation.get("axis") or ""),
                delta=float(operation.get("delta")),
            )
            continue
        joints = _operation_joints(operation, known=known, hierarchy=hierarchy)
        if op_name == "freeze":
            apply_freeze(
                poses,
                joints=joints,
                frames=dest_frames,
                source=str(operation.get("source") or "previous"),
                frame_indices=frames_all,
            )
            continue
        if len(joints) != 1:
            raise ValueError(f"{op_name} acts on one joint; got {joints}")
        joint = joints[0]
        if op_name == "rotate":
            if "delta_deg" not in operation:
                raise ValueError("rotate requires delta_deg")
            apply_rotate(
                poses,
                joint=joint,
                frames=dest_frames,
                axis=str(operation.get("axis") or ""),
                delta_deg=float(operation["delta_deg"]),
                payload=payload,
            )
            continue
        values = {
            str(axis): float(operation[axis])
            for axis in (*BONE_AXES, *ROOT_TRANSLATION_AXES, *ROOT_ROTATION_AXES)
            if axis in operation
        }
        apply_set(
            poses,
            joint=joint,
            frames=dest_frames,
            values_deg=values,
            payload=payload,
        )
    return poses


def inspect_clip(
    payload: Mapping[str, Any],
    *,
    hierarchy: Mapping[str, Mapping[str, Any]] | None = None,
    min_travel_deg: float = SPRITE_ALIGNED_MIN_TRAVEL_DEG,
) -> dict[str, Any]:
    frames = clip_frame_indices(payload)
    poses = clone_poses(payload)
    extra = math.radians(_require_finite("min_travel_deg", min_travel_deg))
    skinned = [str(name) for name in (payload.get("skinnedBones") or [])]
    if hierarchy is not None:
        bones = [name for name in hierarchy if name in set(skinned) or name in known_joint_names(payload)]
        if not bones:
            bones = list(hierarchy)
    else:
        bones = list(skinned) if skinned else sorted(
            name
            for name in known_joint_names(payload)
            if name not in ROOT_TRANSLATION_ALIASES
            and name not in ROOT_ROTATION_ALIASES
        )
    bone_rows = []
    for bone in bones:
        travels: list[float] = []
        moved_frames: list[int] = []
        for position in range(1, len(frames)):
            previous = bone_angles_rad(poses[frames[position - 1]], bone)
            current = bone_angles_rad(poses[frames[position]], bone)
            delta = math.sqrt(
                sum((current[axis] - previous[axis]) ** 2 for axis in BONE_AXES)
            )
            travels.append(delta)
            if delta > extra:
                moved_frames.append(int(frames[position]))
        max_travel = max(travels) if travels else 0.0
        parent = None
        children: tuple[str, ...] = ()
        if hierarchy is not None and bone in hierarchy:
            parent = hierarchy[bone]["parent"]
            children = tuple(str(child) for child in hierarchy[bone]["children"])
        bone_rows.append(
            {
                "bone": bone,
                "parent": parent,
                "children": list(children),
                "movedFrames": moved_frames,
                "maxTravelDeg": math.degrees(max_travel),
            }
        )
    bone_rows.sort(key=lambda row: (-float(row["maxTravelDeg"]), str(row["bone"])))
    root_moved: list[int] = []
    for position in range(1, len(frames)):
        prev_r = root_rotation_deg(poses[frames[position - 1]])
        cur_r = root_rotation_deg(poses[frames[position]])
        rot = math.sqrt(sum((cur_r[axis] - prev_r[axis]) ** 2 for axis in ROOT_ROTATION_AXES))
        prev_t = root_translation(poses[frames[position - 1]])
        cur_t = root_translation(poses[frames[position]])
        trans = math.sqrt(sum((cur_t[axis] - prev_t[axis]) ** 2 for axis in ROOT_TRANSLATION_AXES))
        if rot > min_travel_deg or trans > 1e-4:
            root_moved.append(int(frames[position]))
    return {
        "frameIndices": list(frames),
        "cameraFitPath": payload.get("cameraFitPath"),
        "targetFrameDir": str(Path(str((payload.get("targetPaths") or ["."])[0])).parent)
        if payload.get("targetPaths")
        else None,
        "jointLimitDeg": (payload.get("config") or {}).get("joint_limit_deg"),
        "rootMovedFrames": root_moved,
        "bones": bone_rows,
        "proof": "inspect of generated poses; not a new solve",
    }


def build_tweaked_payload(
    payload: Mapping[str, Any],
    poses: Mapping[int, Mapping[str, Any]],
    *,
    source_clip: str | Path,
    operations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    result = {
        key: copy.deepcopy(value)
        for key, value in payload.items()
        if key not in STALE_AFTER_TWEAK and key != "poses"
    }
    result["poses"] = {str(int(frame)): poses[int(frame)] for frame in clip_frame_indices(payload)}
    result["solver"] = "cascade_manual_tweak"
    result["tweakReport"] = {
        "sourceClip": str(Path(source_clip).resolve()).replace("\\", "/"),
        "operations": copy.deepcopy(list(operations)),
        "previousSolver": payload.get("solver"),
        "searched": False,
        "damped": False,
    }
    return result


def load_operations(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, Mapping) and "operations" in payload:
        rows = payload["operations"]
    else:
        rows = payload
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ValueError("operations file must be a list or {operations: [...]}")
    operations = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("each operation must be an object")
        operations.append(dict(row))
    return operations


def target_frame_dir_from_clip(payload: Mapping[str, Any]) -> Path:
    paths = payload.get("targetPaths")
    if not isinstance(paths, Sequence) or not paths:
        raise ValueError("clip result has no targetPaths")
    parents = {Path(str(path)).resolve().parent for path in paths}
    if len(parents) != 1:
        raise ValueError(f"targetPaths do not share one directory: {sorted(str(item) for item in parents)}")
    directory = next(iter(parents))
    if not directory.is_dir():
        raise FileNotFoundError(f"target frame directory is missing: {directory}")
    return directory


def occupancy_iou(predicted_alpha: Any, target_mask: Any) -> dict[str, float]:
    """Shared / union occupancy on one frame. Alpha and mask are 0/1 arrays."""
    import numpy as np

    predicted = np.asarray(predicted_alpha) > 0.5
    target = np.asarray(target_mask) > 0.5
    if predicted.shape != target.shape:
        raise ValueError(
            f"occupancy shapes differ: predicted {predicted.shape} vs target {target.shape}"
        )
    shared = np.logical_and(predicted, target)
    union = np.logical_or(predicted, target)
    union_count = int(union.sum())
    shared_count = int(shared.sum())
    target_only = int(np.logical_and(target, np.logical_not(predicted)).sum())
    predicted_only = int(np.logical_and(predicted, np.logical_not(target)).sum())
    return {
        "iou": (float(shared_count) / float(union_count)) if union_count else 0.0,
        "shared": float(shared_count),
        "targetOnly": float(target_only),
        "predictedOnly": float(predicted_only),
        "union": float(union_count),
    }


def build_axis_probe_trials(
    *,
    joints: Sequence[str],
    known: frozenset[str],
    delta_deg: float,
    translate_delta: float,
) -> tuple[dict[str, Any], ...]:
    """Named ±axis trials. Does not raster."""
    if not joints:
        raise ValueError("probe needs at least one joint")
    delta = _require_finite("delta_deg", delta_deg)
    if delta <= 0.0:
        raise ValueError("delta_deg must be positive")
    shift = _require_finite("translate_delta", translate_delta)
    if shift <= 0.0:
        raise ValueError("translate_delta must be positive")
    trials: list[dict[str, Any]] = []
    for raw_name in joints:
        joint = canonicalize_joint_name(str(raw_name), known)
        if joint == MOTION_ROOT_KEY:
            for axis in ROOT_TRANSLATION_AXES:
                for sign in (1.0, -1.0):
                    trials.append(
                        {
                            "id": f"{joint}:{axis}:{sign * shift:+.3f}",
                            "joint": joint,
                            "axis": axis,
                            "op": "translate_root",
                            "delta": sign * shift,
                        }
                    )
            continue
        axes = ROOT_ROTATION_AXES if joint == MOTION_ROOT_ROTATION_KEY else BONE_AXES
        for axis in axes:
            for sign in (1.0, -1.0):
                trials.append(
                    {
                        "id": f"{joint}:{axis}:{sign * delta:+.1f}",
                        "joint": joint,
                        "axis": axis,
                        "op": "rotate",
                        "delta_deg": sign * delta,
                    }
                )
    return tuple(trials)


def _raster_pose_alpha(experiment: Any, pose: Mapping[str, Any], frame: int):
    import torch

    bone_vectors, root_translation, root_rotation = experiment._initial_pose_tensors(
        {int(frame): dict(pose)}
    )
    bone_vectors = experiment._bounded_bone_vectors(bone_vectors)
    with torch.no_grad():
        _rgb, alpha, _depth = experiment.exact_triangle_rgb(
            bone_vectors,
            root_translation,
            root_rotation,
            bone_mask=experiment.active_node_mask,
        )
    return alpha[0].detach().cpu().numpy()


def probe_axis_deltas(
    *,
    payload: Mapping[str, Any],
    mesh_glb: str | Path,
    frame: int,
    joints: Sequence[str],
    delta_deg: float,
    translate_delta: float,
) -> dict[str, Any]:
    """Raster ±axis probes on one frame. Does not search. One GPU init."""
    from nvdiffrast_local import ensure_local_nvdiffrast
    from roc_gpu_cascade_experiment import GpuCascadeExperiment

    frames = clip_frame_indices(payload)
    if int(frame) not in set(frames):
        raise ValueError(f"probe frame {frame} is not in this clip")
    camera = payload.get("cameraFitPath")
    if not camera:
        raise ValueError("clip result has no cameraFitPath")
    config = payload.get("config")
    if not isinstance(config, Mapping):
        raise ValueError("clip result has no config")
    known = known_joint_names(payload)
    trials = build_axis_probe_trials(
        joints=joints,
        known=known,
        delta_deg=delta_deg,
        translate_delta=translate_delta,
    )
    ensure_local_nvdiffrast(required=True)
    experiment = GpuCascadeExperiment(
        src_glb=Path(mesh_glb).resolve(),
        camera_fit=Path(str(camera)).resolve(),
        target_frame_dir=target_frame_dir_from_clip(payload),
        frame_indices=(int(frame),),
        config=gpu_config_for_preview(config),
    )
    poses = clone_poses(payload)
    baseline_alpha = _raster_pose_alpha(experiment, poses[int(frame)], int(frame))
    target = experiment.target_masks[0].detach().cpu().numpy()
    baseline = occupancy_iou(baseline_alpha, target)
    rows: list[dict[str, Any]] = []
    for trial in trials:
        operation: dict[str, Any] = {
            "op": trial["op"],
            "bone": trial["joint"],
            "frames": [int(frame)],
            "axis": trial["axis"],
        }
        if trial["op"] == "translate_root":
            operation["delta"] = trial["delta"]
        else:
            operation["delta_deg"] = trial["delta_deg"]
        try:
            probed = apply_operations(payload, [operation])
            alpha = _raster_pose_alpha(experiment, probed[int(frame)], int(frame))
            scores = occupancy_iou(alpha, target)
            rows.append({**trial, **scores, "deltaIou": scores["iou"] - baseline["iou"]})
        except ValueError as exc:
            rows.append({**trial, "error": str(exc), "iou": None, "deltaIou": None})
    rows.sort(
        key=lambda row: (
            row["deltaIou"] is None,
            -(row["deltaIou"] if row["deltaIou"] is not None else -1.0),
        )
    )
    del experiment
    return {
        "frame": int(frame),
        "baseline": baseline,
        "deltaDeg": float(delta_deg),
        "translateDelta": float(translate_delta),
        "trials": rows,
        "searched": False,
        "proof": "one-frame occupancy IoU of named axis probes; not a new solve",
    }


def _gpu_config_from_saved(saved: Mapping[str, Any], *, overrides: Mapping[str, Any]):
    from dataclasses import fields
    from roc_gpu_cascade_experiment import GpuCascadeConfig

    def _tupleize(value: Any) -> Any:
        if isinstance(value, list):
            return tuple(_tupleize(item) for item in value)
        return value

    kwargs: dict[str, Any] = {}
    allowed = {item.name for item in fields(GpuCascadeConfig)}
    for name, value in saved.items():
        if name not in allowed:
            continue
        kwargs[name] = _tupleize(value)
    for name, value in overrides.items():
        if name in allowed:
            kwargs[name] = value
    if str(kwargs.get("score_mode") or "geometry") == "dinov3_dense":
        raise ValueError("refuses dinov3_dense clips; use geometry rescore/preview")
    kwargs["score_mode"] = "geometry"
    return GpuCascadeConfig(**kwargs)


def gpu_config_for_preview(saved: Mapping[str, Any]):
    return _gpu_config_from_saved(
        saved,
        overrides={
            "collision_enabled": False,
            "collision_weight": 0.0,
            "sprite_aligned_motion_keep_enabled": False,
            "physics_smooth_enabled": False,
            "depth_target_dir": None,
            "depth_weight": 0.0,
            "motion_weight": 0.0,
            "exact_raster_enabled": True,
            "return_masks": True,
        },
    )


def gpu_config_for_rescore(saved: Mapping[str, Any]):
    """Replay clip scoring with the saved fit weights (collision/depth/chroma intact).

    Unlike ``gpu_config_for_preview``, this keeps the cascade objective that
    produced ``gpu_clip_result.json`` so rescore parity checks are meaningful.
    """
    return _gpu_config_from_saved(
        saved,
        overrides={
            "sprite_aligned_motion_keep_enabled": False,
            "physics_smooth_enabled": False,
            "motion_weight": 0.0,
            "exact_raster_enabled": True,
            "return_masks": True,
        },
    )


def raster_tweak_preview(
    *,
    payload: Mapping[str, Any],
    mesh_glb: str | Path,
    output_dir: str | Path,
    frame_indices: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Raster edited poses. Does not optimize."""
    import numpy as np
    import torch
    from PIL import Image
    from gpu_depth_silhouette_solver import render_chroma_occupancy_preview
    from gpu_raster_depth_animation import (
        occupancy_stack_for_preview,
        preview_target_rgb_stack,
        replace_owned_run_artifacts,
        RASTER_RUN_CHILDREN,
    )
    from nvdiffrast_local import ensure_local_nvdiffrast
    from preview_timing import PREVIEW_GIF_FRAME_MS
    from roc_gpu_cascade_experiment import GpuCascadeExperiment, persist_gpu_clip_result

    out = Path(output_dir).resolve()
    frames = (
        clip_frame_indices(payload)
        if frame_indices is None
        else parse_frame_spec(frame_indices, clip_frame_indices(payload))
    )
    camera = payload.get("cameraFitPath")
    if not camera:
        raise ValueError("clip result has no cameraFitPath")
    config = payload.get("config")
    if not isinstance(config, Mapping):
        raise ValueError("clip result has no config")
    replace_owned_run_artifacts(out, children=RASTER_RUN_CHILDREN)
    ensure_local_nvdiffrast(required=True)
    experiment = GpuCascadeExperiment(
        src_glb=Path(mesh_glb).resolve(),
        camera_fit=Path(str(camera)).resolve(),
        target_frame_dir=target_frame_dir_from_clip(payload),
        frame_indices=frames,
        config=gpu_config_for_preview(config),
    )
    poses_all = clone_poses(payload)
    subset_poses = {int(frame): poses_all[int(frame)] for frame in frames}
    clip_path = persist_gpu_clip_result(payload, out)
    rgb_dir = out / "solved_rgb"
    if rgb_dir.exists():
        raise FileExistsError(f"refusing to overwrite raster RGB output: {rgb_dir}")
    rgb_dir.mkdir(parents=True)
    alpha_dir = out / "solved_alpha"
    alpha_dir.mkdir(parents=True, exist_ok=True)
    bone_vectors, root_translation, root_rotation = experiment._initial_pose_tensors(subset_poses)
    bone_vectors = experiment._bounded_bone_vectors(bone_vectors)
    with torch.no_grad():
        rgb, alpha, _depth = experiment.exact_triangle_rgb(
            bone_vectors,
            root_translation,
            root_rotation,
            bone_mask=experiment.active_node_mask,
        )
    rgb_images: list[Image.Image] = []
    alpha_images: list[Image.Image] = []
    for position, frame in enumerate(frames):
        rgb_array = np.rint(
            rgb[position].clamp(0.0, 1.0).detach().cpu().numpy() * 255.0
        ).astype(np.uint8)
        rgb_image = Image.fromarray(rgb_array, "RGB")
        rgb_image.save(rgb_dir / f"{int(frame):02d}.png", format="PNG", compress_level=0)
        rgb_images.append(rgb_image)
        alpha_array = np.rint(
            alpha[position].clamp(0.0, 1.0).detach().cpu().numpy() * 255.0
        ).astype(np.uint8)
        alpha_image = Image.fromarray(alpha_array, "L")
        alpha_image.save(alpha_dir / f"{int(frame):02d}.png")
        alpha_images.append(alpha_image.convert("RGB"))
    rgb_gif = rgb_dir / "gpu_solved_rgb.gif"
    rgb_images[0].save(
        rgb_gif,
        save_all=True,
        append_images=rgb_images[1:],
        duration=int(PREVIEW_GIF_FRAME_MS),
        loop=0,
        optimize=False,
    )
    alpha_gif = alpha_dir / "gpu_solved_alpha.gif"
    alpha_images[0].save(
        alpha_gif,
        save_all=True,
        append_images=alpha_images[1:],
        duration=int(PREVIEW_GIF_FRAME_MS),
        loop=0,
        optimize=False,
    )
    predicted_rgb = np.stack(
        [
            np.asarray(image, dtype=np.float32) / 255.0
            for image in rgb_images
        ]
    )
    target_rgb = preview_target_rgb_stack(
        experiment,
        width=int(predicted_rgb.shape[2]),
        height=int(predicted_rgb.shape[1]),
    )
    target_masks, predicted_masks = occupancy_stack_for_preview(
        experiment,
        alpha_dir=alpha_dir,
        frame_indices=tuple(frames),
        height=int(predicted_rgb.shape[1]),
        width=int(predicted_rgb.shape[2]),
    )
    preview_payload = {
        "config": dict(config),
        "targetRgb": target_rgb,
        "predictedRgb": predicted_rgb,
        "targetMasks": target_masks,
        "predictedMasks": predicted_masks,
    }
    preview_gif = render_chroma_occupancy_preview(
        preview_payload,
        output_dir=out / "preview",
        frame_indices=tuple(frames),
        duration_ms=int(PREVIEW_GIF_FRAME_MS),
        scale=1,
    )
    report = {
        "clipResultPath": str(clip_path).replace("\\", "/"),
        "rgbDir": str(rgb_dir).replace("\\", "/"),
        "rgbGif": str(rgb_gif).replace("\\", "/"),
        "previewGif": str(preview_gif).replace("\\", "/"),
        "gpuAlphaDir": str(alpha_dir).replace("\\", "/"),
        "frames": list(frames),
        "searched": False,
        "proof": "generated unlit raster of edited poses; not delivery validated",
    }
    (out / "tweak_preview.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
