"""Fail-closed owned-bind audits, including horse-leg rotate vs rider helmet."""

from __future__ import annotations

from typing import Any

import numpy as np


def lbs_delta_after_bone_rotate(
    positions: np.ndarray,
    joints: np.ndarray,
    weights: np.ndarray,
    heads: np.ndarray,
    parents: list[int | None],
    bone_index: int,
    axis: np.ndarray,
    angle_rad: float,
) -> np.ndarray:
    axis = np.asarray(axis, dtype=np.float64)
    axis = axis / max(float(np.linalg.norm(axis)), 1e-8)
    c = float(np.cos(angle_rad))
    s = float(np.sin(angle_rad))
    x, y, z = axis
    rot = np.array(
        [
            [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
            [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
            [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
        ],
        dtype=np.float64,
    )
    origin = heads[bone_index]
    affected = {bone_index}
    changed = True
    while changed:
        changed = False
        for i, parent in enumerate(parents):
            if parent in affected and i not in affected:
                affected.add(i)
                changed = True
    rest = positions.copy()
    posed = positions.copy()
    for vi in range(len(positions)):
        p = np.zeros(3, dtype=np.float64)
        for slot in range(4):
            w = float(weights[vi, slot])
            if w <= 0.0:
                continue
            bi = int(joints[vi, slot])
            vertex = rest[vi]
            if bi in affected:
                vertex = origin + (rot @ (vertex - origin))
            p += w * vertex
        posed[vi] = p
    return posed - rest


def audit_owned_bind(
    *,
    template: dict[str, Any],
    bone_names: list[str],
    positions: np.ndarray,
    labels: np.ndarray,
    joints: np.ndarray,
    weights: np.ndarray,
    heads: np.ndarray,
    parents: list[int | None],
    rotate_bone: str | None = None,
    still_move_max: float | None = None,
) -> dict[str, Any]:
    issues: list[str] = []
    required = [str(b["name"]) for b in template["bones"]]
    missing = [name for name in required if name not in bone_names]
    if missing:
        issues.append(f"missing template bones: {missing}")
    name_index = {name: i for i, name in enumerate(bone_names)}
    for i, name in enumerate(bone_names):
        owned = int(np.sum(np.any((joints == i) & (weights > 0.05), axis=1)))
        if owned <= 0:
            issues.append(f"bone {name} owns no vertices")

    walls: dict[str, list[str]] = template["skinWalls"]
    part_names = tuple(str(item) for item in template["parts"])
    allowed_ids = {
        part: {name_index[n] for n in bones if n in name_index} for part, bones in walls.items()
    }
    leaks = 0
    for vi, part_id in enumerate(labels):
        part = part_names[int(part_id)]
        allowed = allowed_ids[part]
        for slot in range(4):
            if float(weights[vi, slot]) < 0.05:
                continue
            if int(joints[vi, slot]) not in allowed:
                leaks += 1
                break
    if leaks:
        issues.append(f"cross-partition weight leaks: {leaks}")

    audit_cfg = template.get("audit") or {}
    proof_bone = rotate_bone or str(audit_cfg.get("rotateBone") or "HorseLeftShoulder")
    still_part = str(audit_cfg.get("stillPart") or "rider")
    still_q = float(audit_cfg.get("stillQuantile") or 0.85)
    still_axis = int(audit_cfg.get("stillQuantileAxis") or 2)
    move_max = float(still_move_max if still_move_max is not None else audit_cfg.get("stillMoveMax") or 0.02)
    if proof_bone not in name_index:
        issues.append(f"rotate proof bone missing: {proof_bone}")
        delta_max = None
    elif still_part not in part_names:
        issues.append(f"audit stillPart {still_part!r} is not in template parts")
        delta_max = None
    else:
        still = labels == part_names.index(still_part)
        if not np.any(still):
            issues.append(f"no {still_part} vertices for still-part proof")
            delta_max = None
        else:
            still_pos = positions[still]
            mask = still.copy()
            mask[still] = still_pos[:, still_axis] >= np.quantile(still_pos[:, still_axis], still_q)
            delta = lbs_delta_after_bone_rotate(
                positions,
                joints,
                weights,
                heads,
                parents,
                name_index[proof_bone],
                np.array([1.0, 0.0, 0.0]),
                np.deg2rad(30.0),
            )
            delta_max = float(np.linalg.norm(delta[mask], axis=1).max()) if np.any(mask) else None
            if delta_max is None or delta_max > move_max:
                issues.append(
                    f"{still_part} still-region moved {delta_max} after {proof_bone} rotate (max {move_max})"
                )

    return {
        "schema": "owned_bind_audit.v1",
        "ok": not issues,
        "issues": issues,
        "crossPartitionLeaks": leaks,
        "helmetDeltaMax": delta_max,
        "proof": "generated-artifact",
    }


audit_owned_bind = audit_owned_bind
lbs_delta_after_bone_rotate = lbs_delta_after_bone_rotate
rotate_bone_lbs_delta = lbs_delta_after_bone_rotate
