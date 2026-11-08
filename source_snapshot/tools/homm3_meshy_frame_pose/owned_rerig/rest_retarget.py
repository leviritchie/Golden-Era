"""Retarget registered joint positions to a fitted rest skeleton, without losing rotations.

The indexing matches ``exact_bind.driver_transforms``: joint j drives its incoming
parent -> j link, anchored at j. This is NOT Mixamo's outgoing-bone convention.
For outgoing position-field weights, call ``outgoing_skin_transforms`` before
skinning. Do not call driver_transforms on the returned points: points alone
discard inherited axial rotation.

Positions do not determine independent axial twist. This module explicitly uses
parent-transported minimum swing for each incoming link, and the pelvis/spine
landmarks for the root orientation. It retains inherited twist, but does not
invent wrist twist or recover unobserved roll from position-only captures.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def _unit(vectors: np.ndarray, label: str) -> np.ndarray:
    lengths = np.linalg.norm(vectors, axis=-1, keepdims=True)
    if np.any(lengths <= 1e-12):
        raise ValueError(f"{label} contains a zero-length or collinear direction")
    return vectors / lengths


def _body_frame(points: np.ndarray, index: dict[str, int]) -> np.ndarray:
    """Columns are character-left, up and forward; no global Y-up assumption."""
    side = _unit(points[..., index["LeftUpLeg"], :] - points[..., index["RightUpLeg"], :],
                 "pelvis axis")
    up = points[..., index["Spine"], :] - points[..., index["Hips"], :]
    up = _unit(up - np.sum(up * side, axis=-1, keepdims=True) * side, "spine axis")
    return np.stack((side, up, np.cross(side, up)), axis=-1)


def corresponding_source_rest(
    source_reference: np.ndarray,
    target_rest: np.ndarray,
    parents: Sequence[int | None],
    names: Sequence[str],
) -> np.ndarray:
    """Build a source-space reference corresponding to the target's authored pose.

    Returns a new float64 (J,3) array retaining the source Hips anchor, body
    frame and every source link length. All target link directions are carried
    through one common rigid rotation; no captured frame is declared neutral.
    Inputs follow retarget_motion's named, single-root biped tree contract and
    are not mutated. Pass the result as source_rest, leaving source_frames alone.

    Apply source lengths BEFORE aligning body frames: unequal hip-length ratios
    can change the pelvis axis even when each target link direction is retained.
    Aligning the original target frame would therefore drift the source axes.
    A degenerate source, target or length-adjusted body frame is rejected.

    This helper does not select a pipeline route or recover independent roll.
    """
    source = np.asarray(source_reference, dtype=np.float64)
    target = np.asarray(target_rest, dtype=np.float64)
    count = len(parents)
    if source.shape != (count, 3) or target.shape != (count, 3):
        raise ValueError("reference arrays must both have shape (J,3)")
    if not np.isfinite(source).all() or not np.isfinite(target).all():
        raise ValueError("reference arrays must be finite")
    labels = [str(name).rsplit(":", 1)[-1] for name in names]
    if len(labels) != count or len(set(labels)) != count:
        raise ValueError("names must contain J unique joint names")
    index = {name: joint for joint, name in enumerate(labels)}
    required = {"Hips", "Spine", "LeftUpLeg", "RightUpLeg"}
    if required - index.keys():
        raise ValueError(f"missing body-frame joints: {sorted(required - index.keys())}")
    parent_ids: list[int | None] = []
    children: list[list[int]] = [[] for _ in parents]
    for joint, parent in enumerate(parents):
        integer = isinstance(parent, (int, np.integer)) and not isinstance(parent, (bool, np.bool_))
        if parent is None or (integer and parent == -1):
            parent_ids.append(None)
        elif integer and 0 <= parent < count and parent != joint:
            parent_ids.append(int(parent))
            children[int(parent)].append(joint)
        else:
            raise ValueError(f"invalid parent for joint {joint}: {parent}")
    root = index["Hips"]
    if [joint for joint, parent in enumerate(parent_ids) if parent is None] != [root]:
        raise ValueError("Hips must be the single root")
    order = [root]
    for joint in order:
        order.extend(children[joint])
    if len(order) != count:
        raise ValueError("parent tree must reach every joint without cycles")
    if any(parent_ids[index[name]] != root for name in required - {"Hips"}):
        raise ValueError("Spine and both UpLeg joints must be direct children of Hips")
    source_body = _body_frame(source, index)
    _body_frame(target, index)
    shaped = np.zeros_like(source)
    for joint in order[1:]:
        parent = parent_ids[joint]
        source_link = source[joint] - source[parent]
        _unit(source_link, f"source reference link {joint}")
        direction = _unit(target[joint] - target[parent], f"target rest link {joint}")
        shaped[joint] = shaped[parent] + np.linalg.norm(source_link) * direction
    rotation = source_body @ _body_frame(shaped, index).T
    return source[root] + shaped @ rotation.T


def _rest_frames(
    source: np.ndarray, target: np.ndarray, parents: list[int | None],
    source_body: np.ndarray, target_body: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Paired bone frames with +Y along each incoming link and consistent roll."""
    source_bases = np.empty((len(parents), 3, 3))
    target_bases = np.empty_like(source_bases)
    # Choose the same anatomical helper for both rests, away from either link.
    source_helpers, target_helpers = source_body[:, [2, 0, 1]], target_body[:, [2, 0, 1]]
    for joint, parent in enumerate(parents):
        if parent is None:
            source_bases[joint], target_bases[joint] = source_body, target_body
            continue
        sy = _unit(source[joint] - source[parent], f"source rest link {joint}")
        ty = _unit(target[joint] - target[parent], f"target rest link {joint}")
        helper = int(np.argmin(np.maximum(np.abs(sy @ source_helpers),
                                         np.abs(ty @ target_helpers))))
        for bases, y, helpers in ((source_bases, sy, source_helpers),
                                  (target_bases, ty, target_helpers)):
            z = _unit(helpers[:, helper] - y * (y @ helpers[:, helper]), "bone roll axis")
            bases[joint] = np.column_stack((np.cross(y, z), y, z))
    return source_bases, target_bases


def _swing(a: np.ndarray, b: np.ndarray, half_turn_axis: np.ndarray) -> np.ndarray:
    """Batch minimum swing; exact half turns use the transported bone's +X."""
    a, b = _unit(a, "predicted link"), _unit(b, "frame link")
    cross = np.cross(a, b)
    sine = np.linalg.norm(cross, axis=-1)
    cosine = np.clip(np.sum(a * b, axis=-1), -1.0, 1.0)
    axis = cross / np.maximum(sine[:, None], 1e-12)
    parallel = sine < 1e-12
    axis[parallel] = half_turn_axis[parallel]
    skew = np.zeros((len(a), 3, 3))
    skew[:, 0, 1], skew[:, 0, 2] = -axis[:, 2], axis[:, 1]
    skew[:, 1, 0], skew[:, 1, 2] = axis[:, 2], -axis[:, 0]
    skew[:, 2, 0], skew[:, 2, 1] = -axis[:, 1], axis[:, 0]
    return (cosine[:, None, None] * np.eye(3)
            + (1.0 - cosine)[:, None, None] * axis[:, :, None] * axis[:, None, :]
            + sine[:, None, None] * skew)


def retarget_motion(
    source_rest: np.ndarray,
    target_rest: np.ndarray,
    parents: Sequence[int | None],
    names: Sequence[str],
    source_frames: np.ndarray,
    *,
    root_translation_scale: float = 1.0,
) -> dict[str, np.ndarray]:
    """Transfer local motion between two rests sharing the Mixamo joint tree.

    Args:
        source_rest, target_rest: (J,3) joint positions, each in its own world
            coordinate frame. Both arrays and source_frames share joint order.
            These must represent corresponding poses: for a T-pose mesh, use
            the canonical source T-pose, NOT the source idle, and feed actual
            captured poses as source_frames. The source rest maps to target rest.
        parents: J parent indices; the Hips root is None or -1. Ordering need
            not be topological. All non-root links must have nonzero length.
        names: J unique names, optionally prefixed with ``mixamorig:``. Requires
            Hips, Spine, LeftUpLeg, RightUpLeg, with the latter three parented
            to Hips. The usual 25-joint biped needs no other configuration.
        source_frames: (F,J,3) registered positions in source_rest coordinates.
        root_translation_scale: Explicit root travel multiplier, default 1.
            Zero removes root travel. No automatic mesh/height scale is fitted.

    Returns:
        frame_joints: (F,J,3), in target coordinates, retaining target lengths.
        rotations: (F,J,3,3), proper rotations in target world coordinates.
        offsets: (F,J,3), such that ``R @ target_rest[j] + t = frame_joints[j]``.
        source_to_target_rotation: (3,3), source-to-target body frame rotation.

    Skin positions with sum(w * (R @ v + t)); skin authored normals with
    normalize(sum(w * R @ n)). These transforms already include inverse bind.
    Do not apply another rest correction, or reconstruct rotations from points.
    For outgoing bone_tails/position-field weights, first convert this result
    with outgoing_skin_transforms; these raw rotations drive incoming links.

    Source rest maps to target rest with identity skin transforms. For each
    incoming link, B is its rest frame and F its animated orientation. We form
    Ls0 = Bs_parent.T @ Bs_joint, Ls = Fs_parent.T @ Fs_joint, and transfer
    D = Ls0.T @ Ls through Ft_joint = Ft_parent @ Lt0 @ D. Thus the same LOCAL
    change is expressed through target rest axes, not wrong source directions.
    R = Ft_joint @ Bt_joint.T is retained explicitly for skin and normals.

    Runtime is O(F*J), vectorized over frames, with no per-vertex work, optimizer,
    temporal state, Blender dependency, or global coordinate-axis assumption.
    """
    source = np.asarray(source_rest, dtype=np.float64)
    target = np.asarray(target_rest, dtype=np.float64)
    frames = np.asarray(source_frames, dtype=np.float64)
    count = len(parents)
    if source.shape != (count, 3) or target.shape != (count, 3):
        raise ValueError("rest arrays must both have shape (J,3)")
    if frames.ndim != 3 or frames.shape[1:] != (count, 3):
        raise ValueError("source_frames must have shape (F,J,3)")
    if not all(np.isfinite(array).all() for array in (source, target, frames)):
        raise ValueError("rest and frame arrays must be finite")
    if not np.isfinite(root_translation_scale) or root_translation_scale < 0:
        raise ValueError("root_translation_scale must be finite and nonnegative")
    short_names = [str(name).rsplit(":", 1)[-1] for name in names]
    if len(short_names) != count or len(set(short_names)) != count:
        raise ValueError("names must contain J unique joint names")
    index = {name: joint for joint, name in enumerate(short_names)}
    required = {"Hips", "Spine", "LeftUpLeg", "RightUpLeg"}
    if required - index.keys():
        raise ValueError(f"missing body-frame joints: {sorted(required - index.keys())}")
    parent_ids: list[int | None] = []
    children: list[list[int]] = [[] for _ in parents]
    for joint, parent in enumerate(parents):
        if parent is None or (isinstance(parent, (int, np.integer)) and parent == -1):
            parent_ids.append(None)
        elif isinstance(parent, (int, np.integer)) and 0 <= parent < count and parent != joint:
            parent_ids.append(int(parent))
            children[int(parent)].append(joint)
        else:
            raise ValueError(f"invalid parent for joint {joint}: {parent}")
    root = index["Hips"]
    if [j for j, parent in enumerate(parent_ids) if parent is None] != [root]:
        raise ValueError("Hips must be the single root")
    order = [root]
    for joint in order:
        order.extend(children[joint])
    if len(order) != count:
        raise ValueError("parent tree must reach every joint without cycles")
    if any(parent_ids[index[name]] != root for name in required - {"Hips"}):
        raise ValueError("Spine and both UpLeg joints must be direct children of Hips")

    source_body, target_body = _body_frame(source, index), _body_frame(target, index)
    alignment = target_body @ source_body.T
    bs, bt = _rest_frames(source, target, parent_ids, source_body, target_body)
    nframes = len(frames)
    fs = np.empty((nframes, count, 3, 3))
    ft = np.empty_like(fs)
    rotations = np.empty_like(fs)
    points = np.empty((nframes, count, 3))
    fs[:, root] = _body_frame(frames, index)
    ft[:, root] = target_body @ (source_body.T @ fs[:, root])
    rotations[:, root] = ft[:, root] @ bt[root].T
    points[:, root] = target[root] + root_translation_scale * (
        (frames[:, root] - source[root]) @ alignment.T)
    for joint in order[1:]:
        parent = parent_ids[joint]
        # Transport the parent's full orientation before measuring local swing.
        inherited = fs[:, parent] @ bs[parent].T @ bs[joint]
        swing = _swing(inherited[:, :, 1], frames[:, joint] - frames[:, parent],
                       inherited[:, :, 0])
        fs[:, joint] = swing @ inherited
        source_local_rest = bs[parent].T @ bs[joint]
        source_local = fs[:, parent].transpose(0, 2, 1) @ fs[:, joint]
        local_change = source_local_rest.T @ source_local
        ft[:, joint] = ft[:, parent] @ (bt[parent].T @ bt[joint]) @ local_change
        rotations[:, joint] = ft[:, joint] @ bt[joint].T
        points[:, joint] = points[:, parent] + np.einsum(
            "fij,j->fi", rotations[:, joint], target[joint] - target[parent])
    offsets = points - np.einsum("fjab,jb->fja", rotations, target)
    return {
        "frame_joints": points,
        "rotations": rotations,
        "offsets": offsets,
        "source_to_target_rotation": alignment,
    }


def outgoing_skin_transforms(
    motion: dict[str, np.ndarray],
    target_rest: np.ndarray,
    parents: Sequence[int | None],
    names: Sequence[str],
    *,
    branch_children: dict[str, str] | None = None,
) -> dict[str, np.ndarray]:
    """Adapt retarget_motion's incoming rotations to outgoing skin ownership.

    Each single-child bone uses its child's incoming rotation, anchored at its
    OWN frame joint. Spine2 uses Neck, never a shoulder branch. Hips retains
    its body rotation; leaves retain their incoming rotation. Other branching
    bones require an explicit branch_children owner -> direct-child map rather
    than an arbitrary first child. This map expresses skin ownership, not a
    claim that one rigid transform can follow independently moving branches.

    Returns a new motion dict with unchanged frame_joints and metadata, replaced
    rotations/offsets, and skin_rotation_sources (J,) recording the index map.
    Inputs are not mutated. Apply exactly once before skinning or NPZ export;
    applying it to an already converted result raises ValueError.
    """
    if "skin_rotation_sources" in motion:
        raise ValueError("motion already contains outgoing skin transforms")
    count = len(parents)
    rest = np.asarray(target_rest, dtype=np.float64)
    points = np.asarray(motion["frame_joints"], dtype=np.float64)
    incoming = np.asarray(motion["rotations"], dtype=np.float64)
    if rest.shape != (count, 3) or points.ndim != 3 or points.shape[1:] != (count, 3):
        raise ValueError("target_rest/frame_joints must have shapes (J,3)/(F,J,3)")
    if incoming.shape != (len(points), count, 3, 3):
        raise ValueError("rotations must have shape (F,J,3,3)")
    if not all(np.isfinite(array).all() for array in (rest, points, incoming)):
        raise ValueError("rest, joints and rotations must be finite")
    short_names = [str(name).rsplit(":", 1)[-1] for name in names]
    if len(short_names) != count or len(set(short_names)) != count:
        raise ValueError("names must contain J unique joint names")
    children: list[list[int]] = [[] for _ in parents]
    for joint, parent in enumerate(parents):
        if parent is None or (isinstance(parent, (int, np.integer)) and parent == -1):
            continue
        if not isinstance(parent, (int, np.integer)) or not 0 <= parent < count or parent == joint:
            raise ValueError(f"invalid parent for joint {joint}: {parent}")
        children[int(parent)].append(joint)
    sources = np.arange(count, dtype=np.int64)
    overrides = {} if branch_children is None else dict(branch_children)
    lookup = {name: joint for joint, name in enumerate(short_names)}
    for owner, child in overrides.items():
        if owner not in lookup or child not in lookup:
            raise ValueError(f"unknown outgoing branch mapping: {owner} -> {child}")
        joint, target = lookup[owner], lookup[child]
        if (short_names[joint] in ("Hips", "Spine2") or len(children[joint]) < 2
                or target not in children[joint]):
            raise ValueError(f"mapping must select a direct child of an unsupported branch: {owner} -> {child}")
    for joint, kids in enumerate(children):
        if short_names[joint] == "Hips" or not kids:
            continue
        if short_names[joint] == "Spine2":
            neck = [child for child in kids if short_names[child] == "Neck"]
            if len(neck) != 1:
                raise ValueError("Spine2 must have a Neck child for outgoing skin")
            sources[joint] = neck[0]
        elif len(kids) == 1:
            sources[joint] = kids[0]
        elif short_names[joint] in overrides:
            sources[joint] = lookup[overrides[short_names[joint]]]
        else:
            raise ValueError(f"unsupported outgoing skin branch: {short_names[joint]}")
    rotations = incoming[:, sources].copy()
    offsets = points - np.einsum("fjab,jb->fja", rotations, rest)
    return {**motion, "rotations": rotations, "offsets": offsets,
            "skin_rotation_sources": sources}
