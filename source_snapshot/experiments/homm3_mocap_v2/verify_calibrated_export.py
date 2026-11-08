"""Replay serialized GLB animation and compare it with the in-memory meshes."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from eagle_glb import gltf_world_matrices
from glb_skeleton import _accessor, read_glb, load_bind_skeleton
from mesh_preview import skin_vertices


def _quat_to_matrix(quaternion: np.ndarray) -> np.ndarray:
    """Decode a glTF XYZW quaternion as a local 4x4 transform."""
    values = np.asarray(quaternion, dtype=np.float64).reshape(4)
    norm = float(np.linalg.norm(values))
    if norm <= 1e-12 or not np.isfinite(norm):
        raise ValueError("serialized animation contains a zero or non-finite quaternion")
    x, y, z, w = values / norm
    matrix = np.eye(4, dtype=np.float64)
    matrix[0, 0] = 1.0 - 2.0 * (y * y + z * z)
    matrix[0, 1] = 2.0 * (x * y - z * w)
    matrix[0, 2] = 2.0 * (x * z + y * w)
    matrix[1, 0] = 2.0 * (x * y + z * w)
    matrix[1, 1] = 1.0 - 2.0 * (x * x + z * z)
    matrix[1, 2] = 2.0 * (y * z - x * w)
    matrix[2, 0] = 2.0 * (x * z - y * w)
    matrix[2, 1] = 2.0 * (y * z + x * w)
    matrix[2, 2] = 1.0 - 2.0 * (x * x + y * y)
    return matrix


def _serialized_local_rotations(path: Path, *, allow_root_motion: bool = False) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    document = read_glb(path)
    json_doc = document["json"]
    animations = json_doc.get("animations") or []
    if len(animations) != 1:
        raise ValueError(f"calibrated export must contain exactly one animation, got {len(animations)}")
    skeleton = load_bind_skeleton(path)
    node_to_joint = {int(node): index for index, node in enumerate(skeleton.node_indices)}
    animation = animations[0]
    samplers = animation.get("samplers") or []
    channels = animation.get("channels") or []
    rotations: np.ndarray | None = None
    translations: np.ndarray | None = None
    times: np.ndarray | None = None
    seen: set[int] = set()
    translation_channels = 0
    translation_joints: set[int] = set()
    root_indices = np.flatnonzero(np.asarray(skeleton.parents, dtype=np.int64) < 0)
    if len(root_indices) != 1:
        raise ValueError("serialized skeleton must contain exactly one root joint")
    root_joint = int(root_indices[0])
    for channel in channels:
        target = channel.get("target") or {}
        target_node = int(target.get("node", -1))
        path_name = str(target.get("path") or "")
        if path_name == "translation":
            translation_channels += 1
            if not allow_root_motion:
                raise ValueError("calibrated rotation-only export contains translation channels")
            if target_node not in node_to_joint:
                raise ValueError(f"serialized translation targets non-joint node {target_node}")
            joint = node_to_joint[target_node]
            if joint in translation_joints:
                raise ValueError(f"duplicate serialized translation channel for joint {joint}")
            translation_joints.add(joint)
            sampler_index = int(channel.get("sampler", -1))
            if sampler_index < 0 or sampler_index >= len(samplers):
                raise ValueError(f"serialized translation channel has invalid sampler {sampler_index}")
            sampler = samplers[sampler_index]
            if sampler.get("interpolation", "LINEAR") != "LINEAR":
                raise ValueError("calibrated export must use LINEAR translation interpolation")
            channel_times = _accessor(document, document["bin"], int(sampler["input"])).reshape(-1).astype(np.float64)
            if not len(channel_times) or not np.isfinite(channel_times).all() or np.any(np.diff(channel_times) <= 0):
                raise ValueError("serialized time axis must be nonempty, finite, and strictly increasing")
            channel_values = _accessor(document, document["bin"], int(sampler["output"])).reshape(-1, 3).astype(np.float64)
            if len(channel_times) != len(channel_values) or not np.isfinite(channel_values).all():
                raise ValueError(f"serialized translation channel {joint} has invalid time/value data")
            if joint != root_joint:
                rest = np.asarray(skeleton.rest_local_translation[joint], dtype=np.float64)
                if not np.allclose(channel_values, rest[None, :], atol=1e-6, rtol=0.0):
                    raise ValueError(f"serialized non-root translation channel {joint} moves from rest")
            if times is None:
                times = channel_times
                rotations = np.zeros((len(times), len(skeleton.names), 3, 3), dtype=np.float64)
                translations = np.broadcast_to(np.asarray(skeleton.rest_local_translation, dtype=np.float64),
                                               (len(times), len(skeleton.names), 3)).copy()
            elif not np.array_equal(times, channel_times):
                raise ValueError("serialized translation channels do not share one time axis")
            assert translations is not None
            translations[:, joint] = channel_values
            continue
        if path_name != "rotation":
            raise ValueError(f"unsupported serialized animation channel path {path_name!r}")
        if target_node not in node_to_joint:
            raise ValueError(f"serialized rotation targets non-joint node {target_node}")
        joint = node_to_joint[target_node]
        if joint in seen:
            raise ValueError(f"duplicate serialized rotation channel for joint {joint}")
        seen.add(joint)
        sampler_index = int(channel.get("sampler", -1))
        if sampler_index < 0 or sampler_index >= len(samplers):
            raise ValueError(f"serialized rotation channel has invalid sampler {sampler_index}")
        sampler = samplers[sampler_index]
        if sampler.get("interpolation", "LINEAR") != "LINEAR":
            raise ValueError("calibrated export must use LINEAR quaternion interpolation")
        channel_times = _accessor(document, document["bin"], int(sampler["input"])).reshape(-1).astype(np.float64)
        if not len(channel_times) or not np.isfinite(channel_times).all() or np.any(np.diff(channel_times) <= 0):
            raise ValueError("serialized time axis must be nonempty, finite, and strictly increasing")
        channel_values = _accessor(document, document["bin"], int(sampler["output"])).reshape(-1, 4)
        if len(channel_times) != len(channel_values):
            raise ValueError(f"serialized rotation channel {joint} has mismatched time/value counts")
        if times is None:
            times = channel_times
            rotations = np.zeros((len(times), len(skeleton.names), 3, 3), dtype=np.float64)
            translations = np.broadcast_to(np.asarray(skeleton.rest_local_translation, dtype=np.float64),
                                           (len(times), len(skeleton.names), 3)).copy()
        elif not np.array_equal(times, channel_times):
            raise ValueError("serialized rotation channels do not share one time axis")
        assert rotations is not None
        for frame, quaternion in enumerate(channel_values):
            rotations[frame, joint] = _quat_to_matrix(quaternion)[:3, :3]
    if translation_channels and not allow_root_motion:
        raise ValueError("calibrated rotation-only export contains translation channels")
    if times is None or rotations is None:
        raise ValueError("serialized animation contains no rotation channels")
    if len(seen) != len(skeleton.names):
        missing = [skeleton.names[index] for index in range(len(skeleton.names)) if index not in seen]
        raise ValueError(f"serialized animation is missing rotation channels: {missing[:8]}")
    assert translations is not None
    return times, rotations, translations, {"translationChannels": translation_channels,
                                             "translationJoints": sorted(translation_joints),
                                             "rootJoint": root_joint,
                                             "channelCount": len(channels)}


def verify_calibrated_export(
    path: Path,
    *,
    expected_meshes: np.ndarray,
    expected_times: np.ndarray | None = None,
    idle_frame: int | None = None,
    tolerance: float | None = None,
    allow_root_motion: bool = False,
) -> dict[str, Any]:
    """Replay every serialized keyframe and fail if it differs from the preview.

    This is a serialization/parity check only. It does not assess whether the
    motion is visually good or whether the learned capture is correct.
    """
    if not path.is_file():
        raise FileNotFoundError(f"calibrated export is missing: {path}")
    expected = np.asarray(expected_meshes, dtype=np.float64)
    if expected.ndim != 3 or expected.shape[-1] != 3 or not len(expected) or not np.isfinite(expected).all():
        raise ValueError(f"expected meshes must be finite [T,V,3], got {expected.shape}")
    skeleton = load_bind_skeleton(path)
    if skeleton.vertices is None:
        raise ValueError("calibrated export has no skinned vertices")
    if expected.shape[1:] != (len(skeleton.vertices), 3):
        raise ValueError(
            f"expected meshes {expected.shape} do not match serialized vertices "
            f"({len(skeleton.vertices)}, 3)"
        )
    times, local_rotations, local_translations, channel_info = _serialized_local_rotations(
        path, allow_root_motion=allow_root_motion)
    if len(times) != len(expected):
        raise ValueError(f"serialized frame count {len(times)} != preview frame count {len(expected)}")
    if expected_times is not None and not np.array_equal(times, np.asarray(expected_times, dtype=np.float32).astype(np.float64)):
        raise ValueError("serialized time axis differs from the expected preview timing")
    translations = np.asarray(skeleton.rest_local_translation, dtype=np.float64)
    parents = np.asarray(skeleton.parents, dtype=np.int64)
    actual = []
    for frame in range(len(times)):
        worlds = gltf_world_matrices(
            local_rotation=local_rotations[frame],
            local_translation=local_translations[frame] if allow_root_motion else translations,
            parents=parents,
        )
        actual.append(skin_vertices(skeleton, worlds))
    replayed = np.stack(actual)
    per_frame_max = np.linalg.norm(replayed - expected, axis=-1).max(axis=1)
    per_frame_mean = np.linalg.norm(replayed - expected, axis=-1).mean(axis=1)
    bbox = float(np.linalg.norm(np.asarray(skeleton.vertices).max(0) - np.asarray(skeleton.vertices).min(0)))
    gate = float(tolerance if tolerance is not None else 1e-5 * bbox)
    if not np.isfinite(gate) or gate <= 0.0:
        raise ValueError(f"animation parity tolerance must be finite and positive, got {gate}")
    idle_max = None
    if idle_frame is not None:
        if not 0 <= int(idle_frame) < len(expected):
            raise IndexError(f"idle frame {idle_frame} is outside serialized frame range")
        idle_max = float(per_frame_max[int(idle_frame)])
    payload = {
        "ok": bool(float(per_frame_max.max()) <= gate),
        "proof": "serialized-animation-parity",
        "visualAcceptance": "not_assessed",
        "glb": path.as_posix(),
        "frameCount": int(len(times)),
        "timingValidated": expected_times is not None,
        "jointCount": int(len(skeleton.names)),
        "vertexCount": int(len(skeleton.vertices)),
        "tolerance": gate,
        "perFrameMax": per_frame_max.tolist(),
        "perFrameMean": per_frame_mean.tolist(),
        "maxError": float(per_frame_max.max()),
        "idleFrame": None if idle_frame is None else int(idle_frame),
        "idleFrameMax": idle_max,
        "channelInfo": channel_info,
    }
    if not payload["ok"]:
        raise ValueError(
            "serialized animation does not replay the in-memory preview: "
            f"max {payload['maxError']} > {gate}; perFrameMax={payload['perFrameMax']}"
        )
    return payload
