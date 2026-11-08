"""Explicit hand/capsule clearance on incoming retarget transforms, without smoothing."""
from __future__ import annotations

from copy import deepcopy

import numpy as np

from .rest_retarget import _swing


def _positive(value, label):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be finite and positive")
    try:
        value = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be finite and positive") from error
    if not np.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be finite and positive")
    return value


def _radial(point, start, end):
    segment = end - start
    squared = float(segment @ segment)
    if squared <= 1e-24:
        raise ValueError("singular collider segment")
    # Segment projection is bounded by the capsule end caps, not an IK reach clamp.
    fraction = np.clip((point - start) @ segment / squared, 0.0, 1.0)
    radial = point - (start + fraction * segment)
    return radial, float(np.linalg.norm(radial))


def apply_hand_clearance(motion, heads, parents, names, config, source_sha256):
    """Return a copied incoming motion dict with a JSON-safe clearanceReport.

    Config requires schema retarget_clearance.v1, matching sourceMeshSha256,
    positive maxCorrection and nonempty constraints of hand/colliderStart/
    colliderEnd/radius. The explicit hand's parent and grandparent define its
    two-bone IK chain. Hands must be leaves and elbows must have only that hand.
    Constraints cannot share moved joints or move another constraint's collider.

    Each penetrating wrist moves radially onto its named capsule. Exact IK
    retains both original link lengths and the old elbow pole projected normal
    to the new reach direction. Minimum-swing deltas premultiply the incoming
    rotations, retaining their roll. No capture edit, smoothing or reach clamp.
    maxCorrection bounds BOTH elbow and wrist displacement per frame.

    Invalid/singular/unreachable corrections reject the entire call without
    mutating inputs. Geometry-conditioned retargeting is not visual acceptance.
    Apply before outgoing_skin_transforms, and at most once.
    """
    if "skin_rotation_sources" in motion:
        raise ValueError("hand clearance requires incoming motion, not already outgoing transforms")
    if "clearanceReport" in motion:
        raise ValueError("hand clearance has already been applied")
    if not isinstance(config, dict) or config.get("schema") != "retarget_clearance.v1":
        raise ValueError("config schema must be retarget_clearance.v1")
    if (not isinstance(source_sha256, str) or not source_sha256
            or config.get("sourceMeshSha256") != source_sha256):
        raise ValueError("sourceMeshSha256 must exactly match source_sha256")
    maximum = _positive(config.get("maxCorrection"), "maxCorrection")
    constraints = config.get("constraints")
    if not isinstance(constraints, list) or not constraints:
        raise ValueError("constraints must be an explicit nonempty list")
    count = len(parents)
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError("names must contain nonempty joint names")
    labels = [name.rsplit(":", 1)[-1] for name in names]
    if len(labels) != count or len(set(labels)) != count:
        raise ValueError("names must contain J unique joint names")
    index = {name: j for j, name in enumerate(labels)}
    parent_ids, children = [], [[] for _ in parents]
    for j, parent in enumerate(parents):
        integer = isinstance(parent, (int, np.integer)) and not isinstance(parent, (bool, np.bool_))
        if parent is None or (integer and parent == -1):
            parent_ids.append(None)
        elif integer and 0 <= parent < count and parent != j:
            parent_ids.append(int(parent))
            children[int(parent)].append(j)
        else:
            raise ValueError(f"invalid parent for joint {j}")
    rest = np.asarray(heads, dtype=np.float64)
    points = np.asarray(motion["frame_joints"], dtype=np.float64)
    rotations = np.asarray(motion["rotations"], dtype=np.float64)
    offsets = np.asarray(motion["offsets"], dtype=np.float64)
    if (rest.shape != (count, 3) or points.ndim != 3 or points.shape[1:] != (count, 3)
            or rotations.shape != points.shape[:2] + (3, 3) or offsets.shape != points.shape):
        raise ValueError("heads and incoming motion arrays have invalid shapes")
    if not all(np.isfinite(a).all() for a in (rest, points, rotations, offsets)):
        raise ValueError("heads and incoming motion arrays must be finite")
    if (not np.allclose(rotations @ rotations.swapaxes(-1, -2), np.eye(3), atol=1e-7, rtol=0)
            or not np.allclose(np.linalg.det(rotations), 1, atol=1e-7, rtol=0)):
        raise ValueError("incoming rotations must be proper rotations")
    if not np.allclose(np.einsum("fjab,jb->fja", rotations, rest) + offsets, points,
                       atol=1e-7, rtol=0):
        raise ValueError("incoming offsets must anchor rotations at frame joints")
    resolved, moved = [], set()
    for constraint in constraints:
        if not isinstance(constraint, dict):
            raise ValueError("each constraint must be an explicit object")
        ids = []
        for key in ("hand", "colliderStart", "colliderEnd"):
            name = constraint.get(key)
            if not isinstance(name, str) or name not in index:
                raise ValueError(f"constraint {key} names an unknown joint: {name!r}")
            ids.append(index[name])
        hand, start, end = ids
        elbow = parent_ids[hand]
        arm = parent_ids[elbow] if elbow is not None else None
        if (arm is None or len({arm, elbow, hand}) != 3
                or children[hand] or children[elbow] != [hand]):
            raise ValueError("hand requires a leaf-ended two-bone chain without elbow branches")
        if moved.intersection((elbow, hand)):
            raise ValueError("constraints must not share moved joints")
        moved.update((elbow, hand))
        resolved.append((arm, elbow, hand, start, end, _positive(constraint.get("radius"), "radius")))
    if any(start in moved or end in moved for _, _, _, start, end, _ in resolved):
        raise ValueError("colliders must not be moved by clearance constraints")
    out = deepcopy(motion)
    out["frame_joints"], out["rotations"], out["offsets"] = points.copy(), rotations.copy(), offsets.copy()
    changes = []
    max_residual = 0.0
    for arm, elbow, hand, start, end, radius in resolved:
        for f, p in enumerate(out["frame_joints"]):
            a, b, c = p[[arm, elbow, hand]].copy()
            radial, distance = _radial(c, p[start], p[end])
            if distance >= radius:
                continue
            if distance <= 1e-12:
                raise ValueError(f"frame {f} {labels[hand]}: singular radial direction")
            goal = c + radial * ((radius - distance) / distance)
            upper, lower = float(np.linalg.norm(b - a)), float(np.linalg.norm(c - b))
            reach = float(np.linalg.norm(goal - a))
            if min(upper, lower, reach) <= 1e-12:
                raise ValueError(f"frame {f} {labels[hand]}: singular IK chain")
            if reach > upper + lower or reach < abs(upper - lower):
                raise ValueError(f"frame {f} {labels[hand]}: desired clearance is unreachable")
            direction = (goal - a) / reach
            pole = b - a - direction * ((b - a) @ direction)
            pole_length = float(np.linalg.norm(pole))
            if pole_length <= 1e-12:
                raise ValueError(f"frame {f} {labels[hand]}: singular elbow pole")
            along = (upper * upper - lower * lower + reach * reach) / (2 * reach)
            height_squared = upper * upper - along * along
            if height_squared < 0:
                raise ValueError(f"frame {f} {labels[hand]}: desired IK solution is unreachable")
            new_elbow = a + along * direction + np.sqrt(height_squared) * pole / pole_length
            wrist_move = float(np.linalg.norm(goal - c))
            elbow_move = float(np.linalg.norm(new_elbow - b))
            if max(wrist_move, elbow_move) > maximum:
                raise ValueError(f"frame {f} {labels[hand]}: correction exceeds maxCorrection")
            for joint, old_vector, new_vector in ((elbow, b - a, new_elbow - a),
                                                   (hand, c - b, goal - new_elbow)):
                old_rotation = rotations[f, joint]
                delta = _swing(old_vector[None], new_vector[None], old_rotation[:, 0][None])[0]
                if not np.allclose(delta @ old_vector, new_vector, atol=1e-9, rtol=1e-9):
                    raise ValueError(f"frame {f} {labels[hand]}: singular swing or changed bone length")
                out["rotations"][f, joint] = delta @ old_rotation
            p[elbow], p[hand] = new_elbow, goal
            for joint in (elbow, hand):
                out["offsets"][f, joint] = p[joint] - out["rotations"][f, joint] @ rest[joint]
            _, achieved = _radial(p[hand], p[start], p[end])
            residual = max(0.0, radius - achieved)
            max_residual = max(max_residual, residual)
            if residual > 1e-9:
                raise ValueError(f"frame {f} {labels[hand]}: achieved clearance not satisfied")
            changes.append({"frame": f, "hand": labels[hand], "distanceBefore": distance,
                            "distanceAfter": achieved, "wristCorrection": wrist_move,
                            "elbowCorrection": elbow_move})
    out["clearanceReport"] = {
        "schema": "retarget_clearance_report.v1",
        "sourceMeshSha256": source_sha256,
        "config": deepcopy(config),
        "policy": "geometry-conditioned retarget; source motion unchanged; no smoothing",
        "changedFrames": len({row["frame"] for row in changes}),
        "changedWristFrames": len(changes),
        "maxCorrection": max((max(row["wristCorrection"], row["elbowCorrection"]) for row in changes), default=0.0),
        "maxWristCorrection": max((row["wristCorrection"] for row in changes), default=0.0),
        "maxResidual": max_residual,
        "changes": changes,
        "accepted": False,
    }
    return out
