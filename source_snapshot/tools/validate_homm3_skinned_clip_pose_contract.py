#!/usr/bin/env python3
"""Validate shipped fused-push clip GLBs against their fit-result poses.

The clip GLB is the artifact the Unity lab build turns into ``.anim`` clips,
so this is the last cheap gate before a bad pose contract reaches the game.
For every ``units/*/clips/*.glb`` under the rollout directory:

1. The sidecar ``.json`` must name a ``clipResultPath`` payload whose
   ``poseUnits`` marker is ``degrees`` (fail-closed via
   ``require_pose_units_degrees``; pre-marker radians-era results melted
   skinned meshes when the exporter read degrees as radians).
2. The payload must record ``physicsSmooth.enabled`` — the fused-push batch
   lane runs with ``physics_smooth_enabled=false`` for speed, and unsmoothed
   fits carry per-frame solver noise that plays as whole-body jitter in game.
   ``smooth_clip_result_physics.py`` replays the solver's final post-pass on
   serialized payloads.
3. Every skinned-joint rotation channel must equal, frame for frame,
   ``rest * axis-angle(radians(delta))`` recomputed independently from the
   payload poses (frame selection via the same ``delivery_poses_by_group``
   the exporter used). Missing bones must compose to the exact rest pose.

This validator deliberately re-implements the quaternion composition instead
of calling ``gpu_pose_local_rotation`` so an exporter units regression cannot
mirror itself into the check.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FIT_TOOLS = ROOT / "tools" / "homm3_silhouette_pose_fit"
sys.path.insert(0, str(FIT_TOOLS))

from gpu_cascade_delivery import (  # noqa: E402
    delivery_poses_by_group,
    require_pose_units_degrees,
    select_unit_delivery_choices,
)

DEFAULT_ROLLOUT = ROOT / "artifacts" / "fused_push_skinned_rollout"
ATOL = 2e-4  # exporter writes float32; recompute in float64


def _read_glb(path: Path) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    if data[:4] != b"glTF":
        raise ValueError(f"not a GLB: {path}")
    json_doc: dict[str, Any] | None = None
    bin_blob = b""
    offset = 12
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        start = offset + 8
        payload = data[start : start + chunk_length]
        if chunk_type == b"JSON":
            json_doc = json.loads(payload.decode("utf-8").rstrip(" \t\r\n\x00"))
        elif chunk_type == b"BIN\x00":
            bin_blob = payload
        offset = start + chunk_length
    if json_doc is None:
        raise ValueError(f"no JSON chunk: {path}")
    return json_doc, bin_blob


def _accessor_f4(doc: Mapping[str, Any], bin_blob: bytes, index: int) -> np.ndarray:
    accessor = doc["accessors"][int(index)]
    view = doc["bufferViews"][accessor["bufferView"]]
    components = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[accessor["type"]]
    if int(accessor["componentType"]) != 5126:
        raise ValueError(f"accessor {index} is not float32")
    offset = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    return np.frombuffer(
        bin_blob, dtype="<f4", count=int(accessor["count"]) * components, offset=offset
    ).reshape(int(accessor["count"]), components)


def _quat_multiply(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    lx, ly, lz, lw = left
    rx, ry, rz, rw = right
    value = np.asarray(
        (
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
            lw * rw - lx * rx - ly * ry - lz * rz,
        ),
        dtype=np.float64,
    )
    norm = float(np.linalg.norm(value))
    if norm <= 1e-12:
        raise ValueError("quaternion multiplication produced a zero quaternion")
    return value / norm


def _axis_angle_quaternion_degrees(xyz_deg: np.ndarray) -> np.ndarray:
    vector = np.radians(np.asarray(xyz_deg, dtype=np.float64).reshape(3))
    angle = float(np.linalg.norm(vector))
    if angle <= 1e-12:
        return np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float64)
    axis = vector / angle
    half = angle * 0.5
    return np.asarray(
        (axis[0] * math.sin(half), axis[1] * math.sin(half), axis[2] * math.sin(half), math.cos(half)),
        dtype=np.float64,
    )


def _pose_delta_degrees(pose: Mapping[str, Any], bone: str) -> np.ndarray:
    entry = pose.get(bone)
    if entry is None:
        return np.zeros(3, dtype=np.float64)
    return np.asarray([float(entry.get(axis, 0.0)) for axis in ("x", "y", "z")], dtype=np.float64)


def validate_clip(
    clip_path: Path,
    *,
    choices_by_sid: Mapping[str, Any],
    errors: list[str],
) -> None:
    sidecar_path = clip_path.with_suffix(".json")
    label = clip_path.relative_to(ROOT) if clip_path.is_relative_to(ROOT) else clip_path
    if not sidecar_path.is_file():
        errors.append(f"{label}: missing sidecar {sidecar_path.name}")
        return
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    result_path = Path(str(sidecar.get("clipResultPath") or ""))
    if not result_path.is_file():
        errors.append(f"{label}: clipResultPath missing on disk: {result_path}")
        return
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    try:
        require_pose_units_degrees(payload, source=str(result_path))
    except RuntimeError as exc:
        errors.append(f"{label}: {exc}")
        return
    physics_smooth = payload.get("physicsSmooth")
    if not isinstance(physics_smooth, Mapping) or not bool(physics_smooth.get("enabled")):
        errors.append(
            f"{label}: source payload {result_path.name} was not physics-smoothed "
            "(fused-push lanes run physics_smooth_enabled=false; unsmoothed fits carry "
            "per-frame solver noise that reads as whole-body jitter in game — run "
            "tools/homm3_silhouette_pose_fit/smooth_clip_result_physics.py)"
        )
        return

    unit_sid = clip_path.parents[1].name
    choices = choices_by_sid.get(unit_sid)
    if choices is None:
        try:
            choices = select_unit_delivery_choices(choices_by_sid["all"], unit_sid)
            choices_by_sid[unit_sid] = choices
        except RuntimeError as exc:
            errors.append(f"{label}: cannot resolve delivery choices for {unit_sid}: {exc}")
            return
    choice = next(
        (item for item in choices if str(item.animation_name) == str(sidecar.get("fitAnimation"))),
        None,
    )
    if choice is None:
        errors.append(f"{label}: no delivery choice matches fitAnimation={sidecar.get('fitAnimation')!r}")
        return
    groups = tuple(int(group) for group in choice.def_lab_groups)
    counts = tuple(int(count) for count in choice.def_expected_counts)
    group = int(sidecar.get("defGroup"))
    delivered = delivery_poses_by_group(payload["poses"], groups, counts)
    if group not in delivered:
        errors.append(f"{label}: defGroup {group} not in delivered groups {sorted(delivered)}")
        return
    poses = delivered[group]
    frames = tuple(sorted(int(frame) for frame in poses))

    doc, bin_blob = _read_glb(clip_path)
    animations = doc.get("animations") or []
    if len(animations) != 1:
        errors.append(f"{label}: expected exactly one animation, got {len(animations)}")
        return
    animation = animations[0]
    if animation.get("name") != sidecar.get("contractName"):
        errors.append(
            f"{label}: animation name {animation.get('name')!r} != contractName {sidecar.get('contractName')!r}"
        )
        return

    source = Path(str(sidecar.get("source") or ""))
    if not source.is_file():
        errors.append(f"{label}: sidecar source mesh missing: {source}")
        return
    source_doc, _ = _read_glb(source)
    source_nodes = source_doc["nodes"]
    joints = [int(index) for index in doc["skins"][0]["joints"]]
    nodes = doc["nodes"]

    channels = animation.get("channels") or []
    rotation_channels = [item for item in channels if item.get("target", {}).get("path") == "rotation"]
    if sorted(int(item["target"]["node"]) for item in rotation_channels) != sorted(joints):
        errors.append(f"{label}: rotation channels do not cover every skin joint exactly once")
        return

    times = _accessor_f4(doc, bin_blob, animation["samplers"][rotation_channels[0]["sampler"]]["input"])
    role = str(sidecar.get("lifecycleRole") or "")
    dt = float(sidecar.get("frameDurationSeconds") or (1.0 / float(sidecar.get("fps") or 12.0)))
    source_count = int(sidecar.get("sourceFrameCount") or len(frames))
    if role == "cycle":
        expected_times = np.asarray(
            [index * dt for index in range(source_count + 1)], dtype=np.float32
        ).reshape(-1, 1)
        if times.shape[0] != source_count + 1 or not np.allclose(times, expected_times, atol=1e-6):
            errors.append(
                f"{label}: cycle sampler times do not match sourceFrameCount={source_count} "
                f"plus closing key at {source_count}*frameDuration"
            )
            return
        if len(frames) != source_count:
            errors.append(f"{label}: delivery poses {len(frames)} != sourceFrameCount {source_count}")
            return
    else:
        expected_times = np.asarray([index * dt for index in range(len(frames))], dtype=np.float32).reshape(-1, 1)
        if times.shape[0] != len(frames) or not np.allclose(times, expected_times, atol=1e-6):
            errors.append(f"{label}: sampler times do not match {len(frames)} frames at dt={dt}")
            return

    for channel in rotation_channels:
        node_index = int(channel["target"]["node"])
        name = str(nodes[node_index].get("name") or "")
        rest = np.asarray(
            source_nodes[node_index].get("rotation", (0.0, 0.0, 0.0, 1.0)), dtype=np.float64
        )
        norm = float(np.linalg.norm(rest))
        if norm <= 1e-12:
            errors.append(f"{label}: joint {name} has a zero rest quaternion in the source mesh")
            break
        rest /= norm
        actual = _accessor_f4(doc, bin_blob, animation["samplers"][channel["sampler"]]["output"])
        expected_keys = source_count + 1 if role == "cycle" else len(frames)
        if actual.shape[0] != expected_keys:
            errors.append(f"{label}: joint {name} has {actual.shape[0]} keys, expected {expected_keys}")
            break
        previous: np.ndarray | None = None
        first_expected: np.ndarray | None = None
        for row, frame in enumerate(frames):
            expected = _quat_multiply(rest, _axis_angle_quaternion_degrees(_pose_delta_degrees(poses[frame], name)))
            if previous is not None and float(np.dot(previous, expected)) < 0.0:
                expected = -expected
            previous = expected
            if first_expected is None:
                first_expected = expected
            if not np.allclose(actual[row].astype(np.float64), expected, atol=ATOL):
                errors.append(
                    f"{label}: joint {name} frame {frame} value {np.round(actual[row], 5).tolist()} "
                    f"!= rest*axis-angle(radians(delta)) {np.round(expected, 5).tolist()} "
                    "(pose units/exporter contract violation)"
                )
                break
        else:
            if role == "cycle":
                closing = first_expected
                if previous is not None and float(np.dot(previous, closing)) < 0.0:
                    closing = -closing
                if not np.allclose(actual[-1].astype(np.float64), closing, atol=ATOL):
                    errors.append(
                        f"{label}: joint {name} cycle closing key is not a sign-aligned copy of frame 0"
                    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rollout-dir", type=Path, default=DEFAULT_ROLLOUT)
    parser.add_argument(
        "--unit",
        default="",
        help="optional single unit SID (directory name under units/) for a scoped check",
    )
    args = parser.parse_args(argv)

    units_dir = args.rollout_dir / "units"
    if not units_dir.is_dir():
        print(f"ERROR: rollout units directory is missing: {units_dir}", file=sys.stderr)
        return 1
    clips = sorted(units_dir.glob(f"{args.unit or '*'}/clips/*.glb"))
    if not clips:
        print(f"ERROR: no clip GLBs found under {units_dir} (unit={args.unit or 'all'})", file=sys.stderr)
        return 1

    # Current mocap delivery has a separate provenance contract.  Do not route it
    # through the fused-push validator, which intentionally requires physicsSmooth.
    current_manifests = []
    for manifest_path in sorted(units_dir.glob("*/delivery_manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(manifest.get("provenance"), Mapping) and manifest["provenance"].get("schema") == "homm3_mocap_v2_delivery_provenance.v1":
            current_manifests.append(manifest_path)
    if current_manifests:
        from validate_homm3_mocap_delivery_contract import validate as validate_current_mocap

        errors = validate_current_mocap(
            rollout_dir=args.rollout_dir,
            selection_path=ROOT / "experiments/homm3_mocap_v2/stronghold_ingame_test.json",
            unit=args.unit,
        )
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print(
            f"current mocap delivery contract validation passed: {len(current_manifests)} manifest(s)",
            flush=True,
        )
        return 0

    import roc_semantic_hybrid_widgets as widgets  # noqa: E402

    all_choices = widgets.discover_asset_choices(ROOT)
    choices_by_sid: dict[str, Any] = {"all": all_choices}

    errors: list[str] = []
    for clip_path in clips:
        validate_clip(clip_path, choices_by_sid=choices_by_sid, errors=errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        f"skinned clip pose contract validation passed: {len(clips)} clip GLBs under {units_dir}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
