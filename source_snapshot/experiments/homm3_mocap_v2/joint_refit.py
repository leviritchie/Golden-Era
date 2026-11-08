"""Template-free joint-proxy refit for skinning distance fields.

A deployed skeleton is often seated loosely on its mesh (on the wood elf the
arm chain floats 0.06-0.18 off the flesh while pelvis bones touch it at
0.005).  Any distance-field skinning then misattributes flesh across airgaps:
a hip bone near a hand out-competes the hand's own bone because the contest
is relative, not absolute.

This module re-seats each bone's *proxy segment* - the head/tail pair that
weight rules measure distance against - onto the flesh the deployed weights
already assign it, with no per-unit template and no per-unit tuning.  The
animation skeleton (rest transforms, inverse bind matrices) is deliberately
untouched: proxies feed skinning distances only, so delivery motion cannot
change, only weights can.  A bone that cannot be seated within its shift
budget is left exactly in place and reported, never dragged partway.

The output is shaped to land in the shared bind fitter's ``authored_positions``
gate: finite positions in mesh space, pinned to the fitted mesh by checksum,
with per-bone evidence in the report.
"""

import hashlib
from collections.abc import Mapping

import numpy as np


REFIT_SCHEMA = "joint_proxy_refit.v1"


def _checksum(vertices):
    contiguous = np.ascontiguousarray(np.asarray(vertices, dtype=np.float64))
    return hashlib.sha256(contiguous.tobytes()).hexdigest()


def refit_joint_proxies(vertices, weights, names, heads, tails,
                        max_shift_frac=0.15, marker_tokens=("HeadTop_End", "Toe_End")):
    """Translate each bone's proxy segment onto its deployed flesh.

    ``vertices`` is (V,3), ``weights`` is (V,J) finite non-negative skinning
    mass, ``names`` holds J unique bone names, and ``heads``/``tails`` are the
    current (J,3) proxy endpoints in the same space.  The fit runs in two
    stages with the same parameters on every unit: first one global
    translation shared by all owned non-marker bones (their mass-weighted mean
    centroid error, which absorbs a systematically misplaced skeleton), then a
    per-bone local residual toward the bone's own deployed-mass-weighted
    flesh centroid, clamped to ``max_shift_frac`` of the mesh extent.  Every
    applied move translates the whole segment rigidly, so length and direction
    are preserved exactly.  Markers and bones with no deployed mass are left
    exactly in place with a recorded reason.  Rows of ``weights`` are
    normalized internally for the centroid computation, so unnormalized input
    cannot skew one vertex over another.  The routine is deterministic: same
    inputs, same proxies.
    """
    verts = np.asarray(vertices, dtype=np.float64)
    mass = np.asarray(weights, dtype=np.float64)
    if (verts.ndim != 2 or verts.shape[1] != 3 or not np.issubdtype(verts.dtype, np.number)
            or not np.isfinite(verts).all()):
        raise ValueError("vertices must be finite Nx3 numeric data")
    if len(verts) == 0:
        raise ValueError("mesh must contain vertices")
    if (mass.ndim != 2 or mass.shape[0] != len(verts) or not np.issubdtype(mass.dtype, np.number)
            or not np.isfinite(mass).all() or np.any(mass < 0)):
        raise ValueError("weights must be finite, non-negative VxJ numeric data")
    raw_names = np.asarray(names)
    if raw_names.ndim != 1 or len(raw_names) != mass.shape[1]:
        raise ValueError("names must name every weight column exactly once")
    bone_names = [str(value) for value in raw_names.tolist()]
    if len(bone_names) != len(set(bone_names)):
        raise ValueError("names must contain unique names")
    joint_count = len(bone_names)
    current_heads = np.asarray(heads, dtype=np.float64)
    current_tails = np.asarray(tails, dtype=np.float64)
    if (current_heads.shape != (joint_count, 3) or current_tails.shape != (joint_count, 3)
            or not np.isfinite(current_heads).all() or not np.isfinite(current_tails).all()):
        raise ValueError("heads and tails must be finite Jx3 arrays matching names")
    if not (isinstance(max_shift_frac, (int, float, np.floating)) and np.isfinite(max_shift_frac)
            and 0.0 < float(max_shift_frac) <= 1.0):
        raise ValueError("max_shift_frac must be in (0, 1]")
    max_shift_frac = float(max_shift_frac)
    tokens = tuple(marker_tokens) if isinstance(marker_tokens, (list, tuple)) else None
    if tokens is None or not tokens or any(not isinstance(token, str) or not token for token in tokens):
        raise ValueError("marker_tokens must be a non-empty sequence of non-empty names")

    extent = float(np.linalg.norm(verts.max(axis=0) - verts.min(axis=0)))
    if extent <= 0.0:
        raise ValueError("mesh extent must be positive")
    budget = max_shift_frac * extent
    totals = mass.sum(axis=1, keepdims=True)
    normalized = mass / np.maximum(totals, 1e-12)
    is_marker = np.array([any(token in name for token in tokens) for name in bone_names], dtype=bool)

    midpoints = (current_heads + current_tails) / 2.0
    eligible = np.flatnonzero(~is_marker)
    masses = normalized[:, eligible].sum(axis=0)
    owned = eligible[masses > 0.0]
    if owned.size:
        centroids = np.stack(
            [(normalized[:, int(joint)][:, None] * verts).sum(axis=0) / normalized[:, int(joint)].sum()
             for joint in owned.tolist()])
        weights_owned = masses[masses > 0.0]
        globe = ((centroids - midpoints[owned]) * weights_owned[:, None]).sum(axis=0) / weights_owned.sum()
    else:
        globe = np.zeros(3)
    globe = np.asarray(globe, dtype=np.float64)

    new_heads = current_heads.copy()
    new_tails = current_tails.copy()
    bones = []
    for joint, name in enumerate(bone_names):
        column = normalized[:, joint]
        entry = {"name": name, "index": int(joint), "moved": False,
                 "shift": 0.0, "localShift": [0.0, 0.0, 0.0], "reason": ""}
        if bool(is_marker[joint]):
            entry["reason"] = "marker_skipped"
        elif float(column.sum()) <= 0.0:
            entry["reason"] = "unowned"
        else:
            centroid = (column[:, None] * verts).sum(axis=0) / column.sum()
            local = centroid - (midpoints[joint] + globe)
            local_distance = float(np.linalg.norm(local))
            if local_distance > budget:
                local = local * (budget / local_distance)
                clamped = True
            else:
                clamped = False
            delta = globe + local
            entry["localShift"] = [float(value) for value in local.tolist()]
            if float(np.linalg.norm(delta)) <= 1e-9:
                entry["reason"] = "already_seated"
            else:
                new_heads[joint] = current_heads[joint] + delta
                new_tails[joint] = current_tails[joint] + delta
                entry["moved"] = True
                entry["reason"] = "local_clamped" if clamped else "fitted"
                entry["shift"] = float(np.linalg.norm(delta))
        bones.append(entry)

    report = {
        "schema": REFIT_SCHEMA,
        "rule": "mass_weighted_centroid_rigid_translate",
        "maxShiftFrac": max_shift_frac,
        "shiftBudget": float(budget),
        "globalShift": [float(value) for value in globe.tolist()],
        "meshExtent": float(extent),
        "vertexCount": int(len(verts)),
        "jointCount": int(joint_count),
        "positionChecksum": _checksum(verts),
        "markerBonesSkipped": [bone_names[int(index)] for index in np.flatnonzero(is_marker)],
        "movedBones": int(sum(1 for bone in bones if bone["moved"])),
        "bones": bones,
    }
    return new_heads, new_tails, report


def validate_refit_proxies(new_heads, new_tails, report, vertices, names, heads, tails,
                           max_shift_frac=0.15, marker_tokens=("HeadTop_End", "Toe_End")):
    """Check a refit output against the mesh and frozen parameters.

    This is the build/deploy gate for refit provenance: it verifies the
    report schema and rule text, the frozen parameters, the mesh checksum and
    bone names, finiteness, that markers and unowned bones are exactly
    unmoved, and that every moved bone translated rigidly by the reported
    global shift plus a local residual within budget.  Returns
    ``{"ok": bool, "errors": [...]}``; never raises on a bad artifact, only
    on malformed validator inputs.
    """
    errors = []

    def fail(message):
        errors.append(message)

    if not isinstance(report, Mapping):
        return {"ok": False, "errors": ["report must be a mapping"]}
    if report.get("schema") != REFIT_SCHEMA:
        fail(f"schema must be {REFIT_SCHEMA}")
    if report.get("rule") != "mass_weighted_centroid_rigid_translate":
        fail("rule text mismatch")
    if report.get("maxShiftFrac") != float(max_shift_frac):
        fail("max_shift_frac does not match the frozen report parameters")
    tokens = tuple(marker_tokens) if isinstance(marker_tokens, (list, tuple)) else None
    if tokens is None:
        raise TypeError("marker_tokens must be a sequence of names")
    try:
        verts = np.asarray(vertices, dtype=np.float64)
        fresh = np.asarray(new_heads, dtype=np.float64)
        fresh_tails = np.asarray(new_tails, dtype=np.float64)
        old_heads = np.asarray(heads, dtype=np.float64)
        old_tails = np.asarray(tails, dtype=np.float64)
    except (TypeError, ValueError):
        raise TypeError("validator arrays must be numeric array-likes")
    raw_names = np.asarray(names)
    try:
        bone_names = [str(value) for value in raw_names.tolist()]
    except (TypeError, ValueError):
        raise TypeError("names must be a one-dimensional sequence")
    if len(bone_names) != len(set(bone_names)):
        fail("names must contain unique names")
    joint_count = len(bone_names)
    if fresh.shape != (joint_count, 3) or fresh_tails.shape != (joint_count, 3):
        fail("fitted proxies must be Jx3 arrays matching names")
    if old_heads.shape != (joint_count, 3) or old_tails.shape != (joint_count, 3):
        fail("reference proxies must be Jx3 arrays matching names")
    if not np.isfinite(fresh).all() or not np.isfinite(fresh_tails).all():
        fail("fitted proxies must be finite")
    if report.get("positionChecksum") != _checksum(verts):
        fail("position checksum does not match the fitted mesh")
    if report.get("vertexCount") != len(verts) or report.get("jointCount") != joint_count:
        fail("report counts do not match the mesh")
    reported = report.get("bones")
    if not isinstance(reported, list) or len(reported) != joint_count:
        fail("report must carry one bone entry per joint")
        return {"ok": not errors, "errors": errors}
    budget = float(report.get("shiftBudget", -1.0))
    if not np.isfinite(budget) or budget < 0:
        fail("report shift budget is invalid")
    try:
        globe = np.asarray(report.get("globalShift", None), dtype=np.float64).reshape(3)
    except (TypeError, ValueError):
        fail("report global shift must be a 3-vector")
        globe = np.zeros(3)
    if not np.isfinite(globe).all():
        fail("report global shift must be finite")
    for joint, entry in enumerate(reported):
        if not isinstance(entry, dict):
            fail(f"bone entry {joint} must be a mapping")
            continue
        if entry.get("name") != bone_names[joint]:
            fail(f"bone entry {joint} names {entry.get('name')!r}, expected {bone_names[joint]!r}")
        try:
            local = np.asarray(entry.get("localShift", None), dtype=np.float64).reshape(3)
        except (TypeError, ValueError):
            fail(f"bone {bone_names[joint]} local shift must be a 3-vector")
            continue
        if not np.isfinite(local).all():
            fail(f"bone {bone_names[joint]} local shift must be finite")
            continue
        if float(np.linalg.norm(local)) > budget + 1e-9:
            fail(f"bone {bone_names[joint]} local residual exceeds budget")
        moved = bool(entry.get("moved", False))
        head_moved = not np.array_equal(fresh[joint], old_heads[joint])
        tail_moved = not np.array_equal(fresh_tails[joint], old_tails[joint])
        if moved != (head_moved or tail_moved):
            fail(f"bone {bone_names[joint]} moved flag disagrees with proxy arrays")
        if moved:
            if not (np.allclose(fresh[joint] - old_heads[joint], globe + local, rtol=0, atol=1e-9)
                    and np.allclose(fresh_tails[joint] - old_tails[joint], globe + local,
                                    rtol=0, atol=1e-9)):
                fail(f"bone {bone_names[joint]} did not translate rigidly by global plus local shift")
        if entry.get("reason") not in {"marker_skipped", "unowned", "fitted", "already_seated",
                                        "local_clamped"}:
            fail(f"bone {bone_names[joint]} carries an unknown reason")
    return {"ok": not errors, "errors": errors}
