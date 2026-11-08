#!/usr/bin/env python3
"""Give solved clips character: understate + slow idles, exaggerate everything else.

The tracker/fused-push payload (``gpu_clip_result.json``) reproduces the HoMM3 plates as
faithfully as the mesh allows. Played back on a 3D mesh that fidelity reads flat: idles
fidget at full amplitude at 12 fps, attacks and hits land without any overshoot. This
pass rewrites a payload's bone rotations per DEF group:

* For every bone, a **reference pose** is the rotation-mean over the payload's motion
  frames (all frames whose DEF group is not Idle; for an idle-only payload, all frames).
  One shared reference keeps MoveStart -> Move -> MoveEnd continuous.
* Each frame's rotation is decomposed as ``reference * deviation`` and the deviation's
  angle is multiplied by the group's ``gain`` (< 1 understates, > 1 exaggerates). Mean
  stance is preserved; only how far the pose departs from it changes.
* Idle spans inside a motion payload are posing prefixes stripped at export
  (``delivery_poses_by_group``) and are left untouched (gain 1) so nothing is done to
  frames that never ship.
* Root travel and root rotation (``__motion_root__``, ``__motion_root_rotation__``) are
  never touched: the engine owns locomotion.
* Resulting angles are clamped to the payload's solver joint limit
  (``config.joint_limit_deg``, default 150 deg); every clamp is counted in the report so
  an over-aggressive gain is visible rather than silently flattened.

Timing is not a payload property; ``frame_duration_by_suffix`` gives the exporter the
per-clip frame duration (``clip_lifecycle_row(frame_duration_seconds=...)``), so an Idle
at ``timeScale`` 1.6 plays at 7.5 fps instead of 12.

Rotation convention matches ``gpu_cascade_delivery.gpu_pose_local_rotation``: the local
joint rotation is ``rest * axis_angle(delta_deg)``; deltas are axis-angle vectors in
degrees, not Euler triples.

Proof tier: generated-artifact. Whether the result reads better in a Golden Era battle
is a user-visible judgement this module cannot make.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.spatial.transform import Rotation

from deliberate_motion_contract import AUTHENTIC_DEF_FRAME_DURATION_SECONDS
from gpu_cascade_delivery import CONTRACT_SUFFIX_BY_GROUP, IDLE_GROUP, group_frame_spans, require_pose_units_degrees

MOTION_ROOT_KEYS = ("__motion_root__", "__motion_root_rotation__")
DEFAULT_JOINT_LIMIT_DEG = 150.0
NEGLIGIBLE_DEG = 1e-6

# gain: multiplier on each frame's angular departure from the reference stance.
# timeScale: multiplier on the shipped clip's frame duration (1.6 -> 12 fps becomes 7.5 fps).
DEFAULT_CHARACTER_PROFILE: dict[str, dict[str, float]] = {
    "Idle": {"gain": 0.6, "timeScale": 1.6},
    "Mouseover": {"gain": 0.7, "timeScale": 1.3},
    "Move": {"gain": 1.25, "timeScale": 1.0},
    "MoveStart": {"gain": 1.25, "timeScale": 1.0},
    "MoveEnd": {"gain": 1.25, "timeScale": 1.0},
    "AttackFront": {"gain": 1.35, "timeScale": 1.0},
    "ShootFront": {"gain": 1.35, "timeScale": 1.0},
    "Hitted": {"gain": 1.35, "timeScale": 1.0},
    "Defence": {"gain": 1.2, "timeScale": 1.0},
    "Death": {"gain": 1.25, "timeScale": 1.0},
}


def frame_duration_by_suffix(profile: Mapping[str, Mapping[str, float]] = DEFAULT_CHARACTER_PROFILE) -> dict[str, float]:
    """Per-contract-suffix frame duration for ``export_choice_clips``."""
    return {suffix: AUTHENTIC_DEF_FRAME_DURATION_SECONDS * float(row["timeScale"]) for suffix, row in profile.items()}


def _pose_rotvec_deg(pose: Mapping[str, Any], bone: str) -> np.ndarray:
    entry = pose.get(bone)
    if entry is None:
        return np.zeros(3)
    return np.asarray([float(entry.get("x", 0.0)), float(entry.get("y", 0.0)), float(entry.get("z", 0.0))], dtype=np.float64)


def _frame_groups(payload: Mapping[str, Any], groups: Sequence[int], counts: Sequence[int]) -> list[int]:
    spans = group_frame_spans(tuple(int(g) for g in groups), tuple(int(c) for c in counts))
    total = sum(int(c) for c in counts)
    n_frames = len(payload["poses"])
    if total != n_frames:
        raise ValueError(f"payload has {n_frames} frames but DEF groups {tuple(groups)} x {tuple(counts)} describe {total}")
    per_frame = [0] * total
    for group, start, count in spans:
        for index in range(start, start + count):
            per_frame[index] = int(group)
    return per_frame


def apply_character_pass(
    payload: Mapping[str, Any],
    *,
    groups: Sequence[int],
    counts: Sequence[int],
    profile: Mapping[str, Mapping[str, float]] = DEFAULT_CHARACTER_PROFILE,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(new_payload, report)``; the input is not modified."""
    require_pose_units_degrees(payload, source="clip_character_pass")
    frame_groups = _frame_groups(payload, groups, counts)
    ordered_keys = sorted(payload["poses"], key=lambda k: int(k))
    poses = [payload["poses"][k] for k in ordered_keys]
    bones = sorted({b for pose in poses for b in pose if b not in MOTION_ROOT_KEYS})
    joint_limit = float((payload.get("config") or {}).get("joint_limit_deg") or DEFAULT_JOINT_LIMIT_DEG)

    motion_indices = [i for i, g in enumerate(frame_groups) if g != IDLE_GROUP]
    reference_indices = motion_indices if motion_indices else list(range(len(poses)))
    multi_group = len(set(frame_groups)) > 1

    gains: list[float] = []
    for group in frame_groups:
        suffix = CONTRACT_SUFFIX_BY_GROUP.get(int(group))
        if group == IDLE_GROUP and multi_group:
            gains.append(1.0)  # stripped posing prefix; never shipped
        elif suffix is None or suffix not in profile:
            raise KeyError(f"DEF group {group} ({suffix}) has no character profile row")
        else:
            gains.append(float(profile[suffix]["gain"]))

    new_poses: list[dict[str, Any]] = [
        {k: deepcopy(v) for k, v in pose.items() if k in MOTION_ROOT_KEYS} for pose in poses
    ]
    clamped = 0
    max_angle_before = 0.0
    max_angle_after = 0.0
    for bone in bones:
        rotvecs = np.stack([_pose_rotvec_deg(pose, bone) for pose in poses])
        rotations = Rotation.from_rotvec(np.radians(rotvecs))
        reference = Rotation.from_rotvec(np.radians(rotvecs[reference_indices])).mean()
        deviations = reference.inv() * rotations
        dev_rotvec = deviations.as_rotvec()
        scaled = Rotation.from_rotvec(dev_rotvec * np.asarray(gains)[:, None])
        result = (reference * scaled).as_rotvec()
        angles = np.linalg.norm(result, axis=1)
        max_angle_before = max(max_angle_before, float(np.degrees(np.linalg.norm(rotations.as_rotvec(), axis=1)).max()))
        over = np.degrees(angles) > joint_limit
        if over.any():
            clamped += int(over.sum())
            result[over] *= (np.radians(joint_limit) / angles[over])[:, None]
        max_angle_after = max(max_angle_after, float(np.degrees(np.linalg.norm(result, axis=1)).max()))
        result_deg = np.degrees(result)
        for index, vec in enumerate(result_deg):
            if np.abs(vec).max() > NEGLIGIBLE_DEG:
                new_poses[index][bone] = {"x": float(vec[0]), "y": float(vec[1]), "z": float(vec[2])}

    out = deepcopy(dict(payload))
    out["poses"] = {key: new_poses[i] for i, key in enumerate(ordered_keys)}
    report = {
        "enabled": True,
        "profile": {k: dict(v) for k, v in profile.items()},
        "defGroups": [int(g) for g in groups],
        "defCounts": [int(c) for c in counts],
        "gainPerFrame": gains,
        "referenceFrames": reference_indices,
        "jointLimitDeg": joint_limit,
        "clampedBoneFrames": clamped,
        "maxAngleDegBefore": round(max_angle_before, 3),
        "maxAngleDegAfter": round(max_angle_after, 3),
        "rootMotionTouched": False,
    }
    out["characterPass"] = report
    return out, report


def write_character_payload(
    source: Path, dest: Path, *, groups: Sequence[int], counts: Sequence[int],
    profile: Mapping[str, Mapping[str, float]] = DEFAULT_CHARACTER_PROFILE,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = json.loads(Path(source).read_text(encoding="utf-8"))
    out, report = apply_character_pass(payload, groups=groups, counts=counts, profile=profile)
    report["source"] = str(source)
    out["characterPass"] = report
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    Path(dest).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out, report
