"""Post-hoc cascade physics smoothing for serialized gpu_clip_result.json payloads.

The fused-push batch lane runs with ``physics_smooth_enabled=false`` (speed over
CURRENT_CASCADE_KEEP quality), so its exported clips carry per-frame solver
noise: bones swing tens of degrees frame-to-frame at 12 fps and read as
whole-body jitter in game. The cascade solver's own final step is the
metric-free physics post-pass
(``RocGpuCascadeExperiment._apply_cascade_physics_smooth``), which runs
immediately before ``_pose_dicts`` serialization and is the last mutation of
the pose parameters. This tool replays that exact pass on the serialized
payload:

    degrees payload -> radians -> smooth_cascade_clip -> degrees payload

No GPU, no re-fit: the smoother is deterministic and CPU-only, and running it
on the serialized poses is equivalent to the solver having run it as its final
step (the solver's tanh limit re-clip is a no-op for in-limit data, and a
critically damped spring does not overshoot).

Fail-closed rules:

- the payload must carry ``poseUnits == "degrees"``;
- every pose bone must be a node in the unit's master GLB;
- already-smoothed payloads (``physicsSmooth.enabled``) are skipped;
- the original bytes are preserved once as ``gpu_clip_result.presmooth.json``.

The smoothed poses are written back in the ``_pose_dicts`` contract (a bone
entry is present only when nonzero) and the smoother report is recorded under
``"physicsSmooth"`` with post-hoc provenance. ``"config"`` is the historical
solver configuration and is left untouched.

Usage:
    py -3 smooth_clip_result_physics.py --rollout-units <units dir>
    py -3 smooth_clip_result_physics.py --payload <gpu_clip_result.json> --mesh <master.glb>
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from cascade_physics_smooth import (
    PhysicsSmoothConfig,
    physics_smooth_config_from_mapping,
    quat_to_rotvec,
    rotvec_to_quat,
    quat_multiply,
    smooth_cascade_clip,
)
from gpu_cascade_delivery import _read_glb, require_pose_units_degrees
from roc_gpu_cascade_experiment import MOTION_ROOT_KEY, MOTION_ROOT_ROTATION_KEY

_BONE_AXES = ("x", "y", "z")
_ROOT_TRANSLATION_KEYS = ("forward", "lateral", "vertical")
_ROOT_ROTATION_KEYS = ("camera_forward", "camera_right", "camera_up")
_BACKUP_NAME = "gpu_clip_result.presmooth.json"


def _quat_xyzw_to_matrix(quat: np.ndarray) -> np.ndarray:
    x, y, z, w = np.asarray(quat, dtype=np.float64).reshape(4)
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm <= 1e-12:
        return np.eye(3, dtype=np.float64)
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    return np.asarray(
        (
            (1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)),
            (2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)),
            (2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)),
        ),
        dtype=np.float64,
    )


def _node_local_matrix(node: Mapping[str, Any]) -> np.ndarray:
    if "matrix" in node:
        return np.asarray(node["matrix"], dtype=np.float64).reshape(4, 4).T
    translation = np.asarray(node.get("translation", (0.0, 0.0, 0.0)), dtype=np.float64).reshape(3)
    rotation = np.asarray(node.get("rotation", (0.0, 0.0, 0.0, 1.0)), dtype=np.float64).reshape(4)
    scale = np.asarray(node.get("scale", (1.0, 1.0, 1.0)), dtype=np.float64).reshape(3)
    local = np.eye(4, dtype=np.float64)
    local[:3, :3] = _quat_xyzw_to_matrix(rotation) @ np.diag(scale)
    local[:3, 3] = translation
    return local


class GlbSkeleton:
    """Node names, hierarchy depths, and world-space bind directions from a master GLB.

    Mirrors RocGpuCascadeExperiment._bind_bone_directions_np: FK the rest pose,
    then each node's direction is the normalized mean of child-minus-parent
    origins, or local +Y for leaves.
    """

    def __init__(self, mesh_path: Path) -> None:
        doc, _blob = _read_glb(mesh_path)
        nodes = doc.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            raise ValueError(f"{mesh_path} has no nodes")
        self.names = [str(node.get("name") or f"node_{index}") for index, node in enumerate(nodes)]
        self._index = {name: index for index, name in enumerate(self.names)}
        parents: list[int | None] = [None] * len(nodes)
        for index, node in enumerate(nodes):
            for child in node.get("children", []) or []:
                parents[int(child)] = index
        depths: list[int] = []
        for index in range(len(nodes)):
            depth = 0
            parent = parents[index]
            while parent is not None:
                depth += 1
                parent = parents[parent]
            depths.append(depth)
        self.depths = np.asarray(depths, dtype=np.int32)

        locals_ = [_node_local_matrix(node) for node in nodes]
        worlds: list[np.ndarray | None] = [None] * len(nodes)

        def world(index: int) -> np.ndarray:
            cached = worlds[index]
            if cached is not None:
                return cached
            parent = parents[index]
            resolved = locals_[index] if parent is None else world(int(parent)) @ locals_[index]
            worlds[index] = resolved
            return resolved

        world_mats = np.stack([world(index) for index in range(len(nodes))])
        origins = world_mats[:, :3, 3]
        children: list[list[int]] = [[] for _ in nodes]
        for child, parent in enumerate(parents):
            if parent is not None:
                children[int(parent)].append(child)
        directions = np.zeros((len(nodes), 3), dtype=np.float64)
        for index in range(len(nodes)):
            kids = children[index]
            if kids:
                axis = np.mean(origins[np.asarray(kids)] - origins[index], axis=0)
            else:
                axis = world_mats[index, :3, :3] @ np.asarray((0.0, 1.0, 0.0), dtype=np.float64)
            norm = float(np.linalg.norm(axis))
            if norm > 1e-8:
                directions[index] = axis / norm
        self.directions = directions

    def require_index(self, bone: str, *, payload: Path) -> int:
        index = self._index.get(bone)
        if index is None:
            raise ValueError(f"{payload}: pose bone {bone!r} is not a node in the master GLB")
        return int(index)


def _pose_bone_names(poses: Mapping[str, Any]) -> list[str]:
    names: set[str] = set()
    for pose in poses.values():
        if not isinstance(pose, Mapping):
            raise TypeError("pose frames must be mappings")
        for key, value in pose.items():
            if key in (MOTION_ROOT_KEY, MOTION_ROOT_ROTATION_KEY):
                continue
            if value is not None:
                names.add(str(key))
    return sorted(names)


def _bone_vector(entry: Any) -> np.ndarray:
    if entry is None:
        return np.zeros(3, dtype=np.float64)
    if not isinstance(entry, Mapping):
        raise TypeError(f"bone pose entries must be xyz mappings, got {type(entry).__name__}")
    return np.asarray([float(entry.get(axis, 0.0)) for axis in _BONE_AXES], dtype=np.float64)


def _root_vector(pose: Mapping[str, Any], key: str, axes: tuple[str, ...]) -> np.ndarray:
    entry = pose.get(key)
    if entry is None:
        return np.zeros(3, dtype=np.float64)
    if not isinstance(entry, Mapping):
        raise TypeError(f"{key} must be a mapping")
    return np.asarray([float(entry.get(axis, 0.0)) for axis in axes], dtype=np.float64)


def jitter_stats_degrees(poses: Mapping[str, Any], bone_names: list[str]) -> dict[str, float]:
    """Mean/p95/max per-frame angular delta (degrees) across bones, including the loop seam."""
    frames = sorted((int(frame) for frame in poses), key=int)
    if len(frames) < 2 or not bone_names:
        return {"mean": 0.0, "p95": 0.0, "max": 0.0}
    deltas: list[float] = []
    for bone in bone_names:
        quats = []
        for frame in frames:
            entry = poses[str(frame)].get(bone)
            quats.append(rotvec_to_quat(np.radians(_bone_vector(entry))))
        for index in range(1, len(quats)):
            deltas.append(_angle_degrees(quats[index - 1], quats[index]))
        deltas.append(_angle_degrees(quats[-1], quats[0]))
    values = np.asarray(deltas, dtype=np.float64)
    return {
        "mean": float(values.mean()),
        "p95": float(np.percentile(values, 95)),
        "max": float(values.max()),
    }


def _angle_degrees(left: np.ndarray, right: np.ndarray) -> float:
    dot = abs(float(np.dot(left, right)))
    return 2.0 * math.degrees(math.acos(min(dot, 1.0)))


def smooth_payload(payload_path: Path, skeleton: GlbSkeleton, *, write: bool) -> dict[str, Any]:
    payload_path = Path(payload_path)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{payload_path} must contain a JSON object")
    require_pose_units_degrees(payload, source=str(payload_path))
    prior = payload.get("physicsSmooth")
    if isinstance(prior, Mapping) and bool(prior.get("enabled")):
        return {"path": str(payload_path), "smoothed": False, "reason": "already smoothed"}
    poses = payload.get("poses")
    if not isinstance(poses, Mapping) or not poses:
        raise ValueError(f"{payload_path} has no poses")
    config_mapping = payload.get("config")
    if not isinstance(config_mapping, Mapping):
        raise ValueError(f"{payload_path} has no solver config to derive physics_smooth settings from")
    config = replace(physics_smooth_config_from_mapping(config_mapping), enabled=True)

    frames = sorted((int(frame) for frame in poses), key=int)
    bone_names = _pose_bone_names(poses)
    node_indices = [skeleton.require_index(bone, payload=payload_path) for bone in bone_names]
    bones = np.zeros((len(frames), len(bone_names), 3), dtype=np.float64)
    translation = np.zeros((len(frames), 3), dtype=np.float64)
    rotation = np.zeros((len(frames), 3), dtype=np.float64)
    for frame_position, frame in enumerate(frames):
        pose = poses[str(frame)]
        for bone_position, bone in enumerate(bone_names):
            bones[frame_position, bone_position, :] = np.radians(_bone_vector(pose.get(bone)))
        translation[frame_position, :] = _root_vector(pose, MOTION_ROOT_KEY, _ROOT_TRANSLATION_KEYS)
        rotation[frame_position, :] = np.radians(_root_vector(pose, MOTION_ROOT_ROTATION_KEY, _ROOT_ROTATION_KEYS))

    before = jitter_stats_degrees(poses, bone_names)
    smoothed_bones, smoothed_translation, smoothed_rotation, report = smooth_cascade_clip(
        bones,
        translation,
        rotation,
        config=config,
        bone_depths=skeleton.depths[np.asarray(node_indices, dtype=np.int64)],
        bind_directions=skeleton.directions[np.asarray(node_indices, dtype=np.int64)],
    )

    new_poses: dict[str, Any] = {}
    degrees_bones = np.degrees(smoothed_bones)
    degrees_rotation = np.degrees(smoothed_rotation)
    for frame_position, frame in enumerate(frames):
        pose: dict[str, Any] = {}
        for bone_position, bone in enumerate(bone_names):
            values = degrees_bones[frame_position, bone_position, :]
            if float(np.max(np.abs(values))) > 1e-7:
                pose[bone] = {axis: float(values[axis_index]) for axis_index, axis in enumerate(_BONE_AXES)}
        pose[MOTION_ROOT_KEY] = {
            axis: float(smoothed_translation[frame_position, axis_index])
            for axis_index, axis in enumerate(_ROOT_TRANSLATION_KEYS)
        }
        pose[MOTION_ROOT_ROTATION_KEY] = {
            axis: float(degrees_rotation[frame_position, axis_index])
            for axis_index, axis in enumerate(_ROOT_ROTATION_KEYS)
        }
        new_poses[str(frame)] = pose
    after = jitter_stats_degrees(new_poses, bone_names)

    if write:
        backup = payload_path.with_name(_BACKUP_NAME)
        if not backup.is_file():
            shutil.copyfile(payload_path, backup)
        payload["poses"] = new_poses
        payload["physicsSmooth"] = {
            **report,
            "postHoc": True,
            "appliedBy": "tools/homm3_silhouette_pose_fit/smooth_clip_result_physics.py",
            "appliedUtc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "backup": backup.name,
        }
        payload_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    return {
        "path": str(payload_path),
        "smoothed": bool(write),
        "frames": len(frames),
        "bones": len(bone_names),
        "outlierBoneFrames": int(report["outlierBoneFrames"]),
        "outlierRootFrames": int(report["outlierRootFrames"]),
        "jitterBefore": before,
        "jitterAfter": after,
    }


def _rollout_payload_meshes(units_dir: Path) -> dict[Path, Path]:
    pairs: dict[Path, Path] = {}
    for sidecar in sorted(units_dir.glob("*/clips/*.json")):
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        clip_result = data.get("clipResultPath")
        source = data.get("source")
        if not clip_result or not source:
            raise ValueError(f"{sidecar} is missing clipResultPath/source")
        payload_path = Path(clip_result)
        mesh_path = Path(source)
        existing = pairs.get(payload_path)
        if existing is not None and existing != mesh_path:
            raise ValueError(f"{payload_path} is exported from two meshes: {existing} and {mesh_path}")
        pairs[payload_path] = mesh_path
    return pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--payload", type=Path, help="single gpu_clip_result.json")
    parser.add_argument("--mesh", type=Path, help="master GLB for --payload")
    parser.add_argument("--rollout-units", type=Path, help="rollout units dir; payloads+meshes come from clip sidecars")
    parser.add_argument("--write", action="store_true", help="write smoothed payloads (default is a dry-run report)")
    args = parser.parse_args(argv)

    if args.rollout_units and (args.payload or args.mesh):
        parser.error("--rollout-units cannot be combined with --payload/--mesh")
    if args.payload and not args.mesh:
        parser.error("--payload requires --mesh")

    if args.rollout_units:
        pairs = _rollout_payload_meshes(Path(args.rollout_units))
    elif args.payload:
        pairs = {Path(args.payload): Path(args.mesh)}
    else:
        parser.error("pass --rollout-units or --payload/--mesh")

    skeletons: dict[Path, GlbSkeleton] = {}
    results: list[dict[str, Any]] = []
    for payload_path, mesh_path in sorted(pairs.items(), key=lambda pair: str(pair[0])):
        if not payload_path.is_file():
            raise FileNotFoundError(f"payload missing: {payload_path}")
        if not mesh_path.is_file():
            raise FileNotFoundError(f"master GLB missing: {mesh_path}")
        skeleton = skeletons.get(mesh_path)
        if skeleton is None:
            skeleton = GlbSkeleton(mesh_path)
            skeletons[mesh_path] = skeleton
        results.append(smooth_payload(payload_path, skeleton, write=bool(args.write)))

    skipped = [result for result in results if not result.get("smoothed") and result.get("reason")]
    acted = [result for result in results if "jitterBefore" in result]
    for result in results:
        if "jitterBefore" not in result:
            print(f"SKIP {result['path']}: {result.get('reason')}")
            continue
        before = result["jitterBefore"]
        after = result["jitterAfter"]
        print(
            f"{'SMOOTH' if args.write else 'DRY'} {Path(result['path']).parent.parent.parent.name}/"
            f"{Path(result['path']).parent.parent.name}: "
            f"frames={result['frames']} bones={result['bones']} "
            f"outliers(bone={result['outlierBoneFrames']},root={result['outlierRootFrames']}) "
            f"jitter mean {before['mean']:.1f}->{after['mean']:.1f} "
            f"p95 {before['p95']:.1f}->{after['p95']:.1f} "
            f"max {before['max']:.1f}->{after['max']:.1f}"
        )
    if acted:
        means_before = np.asarray([result["jitterBefore"]["mean"] for result in acted])
        means_after = np.asarray([result["jitterAfter"]["mean"] for result in acted])
        p95_before = np.asarray([result["jitterBefore"]["p95"] for result in acted])
        p95_after = np.asarray([result["jitterAfter"]["p95"] for result in acted])
        max_before = max(result["jitterBefore"]["max"] for result in acted)
        max_after = max(result["jitterAfter"]["max"] for result in acted)
        print(
            f"TOTAL payloads={len(results)} smoothed={len(acted)} skipped={len(skipped)} "
            f"jitter-mean {means_before.mean():.2f}->{means_after.mean():.2f} "
            f"jitter-p95 {p95_before.mean():.2f}->{p95_after.mean():.2f} "
            f"jitter-max {max_before:.2f}->{max_after:.2f} "
            f"({'written' if args.write else 'dry-run'})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
