"""Correspondence-aware skin initialization for meshes driven by mocap bones.

The mocap skeleton is the sole articulation owner. Unlike nearest-joint
weights, this initializer measures distance to bone *segments* and derives a
small, normalized support around each segment. That keeps a torso vertex on
the spine chain and an arm vertex on the arm chain before any image-supervised
refinement is attempted. Camera-free alternatives use triangle-surface
geodesics or 3-D anatomical region capsules; image projections are not part of
their fit or ownership decisions.
"""
from __future__ import annotations

import numpy as np
import torch
from scipy.spatial import cKDTree
from itertools import permutations, product


def rest_world_from_offsets(offsets: np.ndarray, parents: np.ndarray) -> np.ndarray:
    offsets = np.asarray(offsets, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    if offsets.ndim != 2 or offsets.shape[1] != 3 or parents.shape != (len(offsets),) or not np.isfinite(offsets).all():
        raise ValueError("offsets/parents have invalid shapes")
    worlds = np.repeat(np.eye(4, dtype=np.float64)[None], len(offsets), axis=0)
    for index, parent in enumerate(parents):
        if int(parent) < -1 or int(parent) >= index:
            raise ValueError("parents must be root-first ordered")
        worlds[index, :3, 3] = offsets[index] if int(parent) < 0 else worlds[int(parent), :3, 3] + offsets[index]
    return worlds


def local_offsets_from_world(world: np.ndarray, parents: np.ndarray) -> np.ndarray:
    """Convert absolute joint positions to parent-relative bind offsets.

    The capsule initializer consumes local offsets and performs FK itself.  A
    fitted skeleton is usually represented as world matrices, so passing its
    translations directly would accumulate every ancestor twice.
    """
    world = np.asarray(world, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    if world.ndim != 3 or world.shape[1:] != (4, 4) or parents.shape != (len(world),):
        raise ValueError("world/parents have invalid shapes")
    positions = world[:, :3, 3]
    offsets = positions.copy()
    for index, parent in enumerate(parents):
        if int(parent) >= 0:
            if int(parent) >= index:
                raise ValueError("parents must be root-first ordered")
            offsets[index] = positions[index] - positions[int(parent)]
    return offsets


def _segment_distance(points: np.ndarray, start: np.ndarray, end: np.ndarray) -> np.ndarray:
    axis = end - start
    length_sq = float(axis @ axis)
    if length_sq < 1e-12:
        return np.linalg.norm(points - start[None], axis=1)
    t = np.clip(((points - start[None]) @ axis) / length_sq, 0.0, 1.0)
    nearest = start[None] + t[:, None] * axis[None]
    return np.linalg.norm(points - nearest, axis=1)


def capsule_bone_weights(
    vertices: np.ndarray,
    offsets: np.ndarray,
    parents: np.ndarray,
    *,
    max_influences: int = 4,
    radius_scale: float = 0.55,
    temperature: float = 0.18,
    side_axis: np.ndarray | None = None,
    side_labels: np.ndarray | None = None,
    side_origin: np.ndarray | None = None,
    side_margin: float = 0.06,
    torso_mask: np.ndarray | None = None,
    torso_bias: float = 0.0,
    torso_radius_scale: float = 0.35,
    terminal_radius_scale: float = 0.15,
    allowed_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Return sparse, segment-aware weights with <= ``max_influences`` entries.

    Segment distance is combined with a scale-aware capsule radius.  A small
    support is selected before normalization, so later differentiable fitting
    cannot teleport a vertex between unrelated limbs.
    """
    vertices = np.asarray(vertices, dtype=np.float64)
    offsets = np.asarray(offsets, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all():
        raise ValueError("vertices must be finite [V,3]")
    if max_influences < 1 or max_influences > len(offsets):
        raise ValueError("invalid max_influences")
    if not np.isfinite(torso_bias) or torso_bias < 0.0:
        raise ValueError("torso_bias must be finite and nonnegative")
    if not np.isfinite(torso_radius_scale) or torso_radius_scale <= 0.0:
        raise ValueError("torso_radius_scale must be finite and positive")
    if not np.isfinite(terminal_radius_scale) or terminal_radius_scale <= 0.0:
        raise ValueError("terminal_radius_scale must be finite and positive")
    if torso_mask is not None:
        torso_mask = np.asarray(torso_mask, dtype=bool)
        if torso_mask.shape != (len(offsets),) or not np.any(torso_mask):
            raise ValueError("torso_mask must select at least one bone")
    if allowed_mask is not None:
        allowed_mask = np.asarray(allowed_mask, dtype=bool)
        if allowed_mask.shape != (len(offsets),) or not np.any(allowed_mask):
            raise ValueError("allowed_mask must select at least one bone")
    worlds = rest_world_from_offsets(offsets, parents)
    joints = worlds[:, :3, 3]
    span = float(np.max(vertices.max(0) - vertices.min(0)))
    lengths = np.zeros(len(joints), dtype=np.float64)
    distances = np.empty((len(vertices), len(joints)), dtype=np.float64)
    for index, parent in enumerate(parents):
        if int(parent) < 0:
            children = np.where(parents == index)[0]
            end = joints[int(children[0])] if len(children) else joints[index] + np.array([0.0, span * 0.08, 0.0])
            start = joints[index]
        else:
            start, end = joints[int(parent)], joints[index]
        length = max(float(np.linalg.norm(end - start)), span * 0.015)
        lengths[index] = length
        distances[:, index] = _segment_distance(vertices, start, end)
    if side_axis is not None or side_labels is not None:
        if side_axis is None or side_labels is None:
            raise ValueError("side_axis and side_labels must be provided together")
        axis = np.asarray(side_axis, dtype=np.float64).reshape(3)
        axis_norm = float(np.linalg.norm(axis))
        labels = np.asarray(side_labels, dtype=np.int8)
        origin = joints[0] if side_origin is None else np.asarray(side_origin, dtype=np.float64).reshape(3)
        if axis_norm <= 1e-8 or labels.shape != (len(joints),) or not np.isfinite(axis).all():
            raise ValueError("invalid bilateral correspondence gate")
        axis /= axis_norm
        vertex_side = (vertices - origin[None]) @ axis
        threshold = max(float(side_margin) * span, 1e-8)
        for joint in range(len(joints)):
            label = int(labels[joint])
            if label:
                incompatible = (vertex_side * label) < -threshold
                distances[incompatible, joint] = np.inf
    if allowed_mask is not None:
        distances[:, ~allowed_mask] = np.inf
    radii = np.maximum(lengths * float(radius_scale), span * 0.025)
    # Terminal capture joints (head-top/toe-end/hand tips) are helper points,
    # not broad anatomical regions.  Keep their endpoint support while
    # preventing the whole torso from being claimed by a short terminal
    # segment when a generated mesh has no authored skin.
    child_count = np.bincount(parents[parents >= 0], minlength=len(joints))
    terminal = child_count == 0
    radii[terminal] *= float(terminal_radius_scale)
    log_scores = -0.5 * (distances / radii[None]) ** 2
    log_scores -= distances / max(float(temperature) * span, 1e-6)
    if torso_mask is not None and float(torso_bias) > 0.0:
        torso_distance = np.min(distances[:, torso_mask], axis=1)
        torso_core = np.exp(-0.5 * (torso_distance / max(float(torso_radius_scale) * span, 1e-8)) ** 2)
        log_scores[:, torso_mask] += float(torso_bias) * torso_core[:, None]
    row_max = np.max(log_scores, axis=1, keepdims=True)
    if not np.isfinite(row_max).all():
        raise ValueError("capsule correspondence gate removed every bone for a vertex")
    scores = np.exp(log_scores - row_max)
    scores[~np.isfinite(distances)] = 0.0
    nearest = np.argpartition(-scores, kth=max_influences - 1, axis=1)[:, :max_influences]
    picked = np.take_along_axis(scores, nearest, axis=1)
    picked = np.maximum(picked, 0.0)
    totals = picked.sum(axis=1, keepdims=True)
    if np.any(totals <= 1e-12):
        raise ValueError("capsule correspondence gate removed every selected bone")
    picked /= totals
    dense = np.zeros((len(vertices), len(joints)), dtype=np.float64)
    dense[np.arange(len(vertices))[:, None], nearest] = picked
    return dense


def validate_weights(weights: np.ndarray, *, max_influences: int = 4) -> None:
    weights = np.asarray(weights, dtype=np.float64)
    if weights.ndim != 2 or not np.isfinite(weights).all() or np.any(weights < -1e-8):
        raise ValueError("weights must be finite and nonnegative")
    if not np.allclose(weights.sum(1), 1.0, atol=1e-6):
        raise ValueError("weights must be row-normalized")
    if int((weights > 1e-8).sum(1).max()) > max_influences:
        raise ValueError("weights exceed influence budget")


def sparsify_weights(weights: np.ndarray, *, max_influences: int) -> np.ndarray:
    """Keep the strongest influences per vertex and renormalize."""
    dense = np.asarray(weights, dtype=np.float64)
    if dense.ndim != 2 or not np.isfinite(dense).all() or np.any(dense < 0.0):
        raise ValueError("weights must be finite and nonnegative")
    if max_influences < 1 or max_influences > dense.shape[1]:
        raise ValueError("invalid max_influences")
    keep = np.argpartition(-dense, kth=max_influences - 1, axis=1)[:, :max_influences]
    sparse = np.zeros_like(dense)
    sparse[np.arange(len(dense))[:, None], keep] = np.take_along_axis(dense, keep, axis=1)
    totals = sparse.sum(axis=1, keepdims=True)
    if np.any(totals <= 1e-12):
        raise ValueError("weights contain an empty row")
    sparse /= totals
    return sparse


def topology_weight_support(
    weights: np.ndarray,
    edge_pairs: np.ndarray,
    *,
    max_influences: int,
    neighbor_vote: float = 0.20,
) -> np.ndarray:
    """Build a deterministic sparse support that can cross smooth topology.

    A per-vertex top-k truncation can give adjacent triangles disjoint joint
    supports, especially when a generated mesh has uneven tessellation. This
    support builder adds one-ring dominant-joint votes before ranking, while
    retaining the strongest local influences. The optimizer can then adjust a
    boundary continuously instead of inventing a new unrelated bone through a
    zero-weight tie.
    """
    dense = np.asarray(weights, dtype=np.float64)
    edges = np.asarray(edge_pairs, dtype=np.int64)
    if dense.ndim != 2 or not np.isfinite(dense).all() or np.any(dense < 0.0):
        raise ValueError("weights must be finite and nonnegative")
    if edges.ndim != 2 or edges.shape[1] != 2 or np.any(edges < 0) or np.any(edges >= len(dense)):
        raise ValueError("edge_pairs must be [E,2] within the weight rows")
    if max_influences < 1 or max_influences > dense.shape[1] or not np.isfinite(neighbor_vote) or neighbor_vote < 0.0:
        raise ValueError("invalid topology support parameters")
    dominant = np.argmax(dense, axis=1)
    votes = np.zeros_like(dense)
    np.add.at(votes, (edges[:, 0], dominant[edges[:, 1]]), 1.0)
    np.add.at(votes, (edges[:, 1], dominant[edges[:, 0]]), 1.0)
    degree = np.bincount(edges.reshape(-1), minlength=len(dense)).astype(np.float64)
    votes /= np.maximum(degree[:, None], 1.0)
    score = dense + float(neighbor_vote) * votes
    support = np.argpartition(-score, kth=max_influences - 1, axis=1)[:, :max_influences]
    # Preserve the dominant original influence even when a heavily connected
    # neighbor vote outranks it.
    missing = ~np.any(support == dominant[:, None], axis=1)
    support[missing, -1] = dominant[missing]
    return support.astype(np.int64, copy=False)


def region_capsule_weights(
    vertices: np.ndarray,
    offsets: np.ndarray,
    parents: np.ndarray,
    names: list[str],
    view_basis: np.ndarray,
    region_joints: dict[str, tuple[str, ...]],
    *,
    max_influences: int = 2,
    region_widths: dict[str, float] | None = None,
    radius_scale: float = 0.30,
    terminal_radius_scale: float = 0.15,
) -> np.ndarray:
    """Build sparse weights after assigning each vertex to an expanded region.

    A generated biped often puts a thigh or forearm capsule through the torso.
    Choosing the nearest raw capsule therefore lets a limb own the body.  This
    pass compares *screen-space* distances to anatomical region polylines,
    expands the torso by a broad body radius, and then solves 3-D capsule
    weights only inside the selected region.  It is a generic Mixamo-style
    correspondence prior; no donor mesh or image-fit loop is involved.
    """
    vertices = np.asarray(vertices, dtype=np.float64)
    offsets = np.asarray(offsets, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    names = list(names)
    basis = np.asarray(view_basis, dtype=np.float64)
    if len(names) != len(offsets) or basis.shape != (3, 3) or not np.isfinite(basis).all():
        raise ValueError("region correspondence inputs have invalid shapes")
    index = {name: i for i, name in enumerate(names)}
    region_indices: dict[str, np.ndarray] = {}
    claimed: set[int] = set()
    for region, members in region_joints.items():
        indices = np.asarray([index[name] for name in members if name in index], dtype=np.int64)
        if len(indices) == 0:
            raise ValueError(f"region {region!r} has no matching joints")
        overlap = claimed.intersection(int(value) for value in indices)
        if overlap:
            raise ValueError(f"region joints overlap: {sorted(overlap)}")
        claimed.update(int(value) for value in indices)
        region_indices[str(region)] = indices
    missing = sorted(set(range(len(names))) - claimed)
    if missing:
        raise ValueError(f"region joints do not cover skeleton: {[names[i] for i in missing]}")
    widths = {str(region): 0.10 for region in region_indices}
    widths.update({str(key): float(value) for key, value in (region_widths or {}).items()})
    if any(not np.isfinite(value) or value < 0.0 for value in widths.values()):
        raise ValueError("region widths must be finite and nonnegative")
    worlds = rest_world_from_offsets(offsets, parents)
    joints = worlds[:, :3, 3]
    projected_vertices = vertices @ basis[:2].T
    projected_joints = joints @ basis[:2].T
    span = max(float(np.ptp(projected_vertices, axis=0).max()), 1e-8)
    region_distance = []
    regions = list(region_indices)
    for region in regions:
        distances = []
        for joint in region_indices[region]:
            parent = int(parents[joint])
            start = projected_joints[joint] if parent < 0 else projected_joints[parent]
            end = projected_joints[joint] if parent >= 0 else projected_joints[joint] + np.array([0.0, span * 0.08])
            distances.append(_segment_distance(projected_vertices, start, end))
        region_distance.append(np.min(np.stack(distances, axis=1), axis=1) - widths[region] * span)
    region_labels = np.argmin(np.stack(region_distance, axis=1), axis=1)
    result = np.zeros((len(vertices), len(names)), dtype=np.float64)
    for label, region in enumerate(regions):
        selected = region_labels == label
        if not np.any(selected):
            continue
        allowed = np.zeros(len(names), dtype=bool)
        allowed[region_indices[region]] = True
        result[selected] = capsule_bone_weights(
            vertices[selected], offsets, parents,
            max_influences=min(int(max_influences), int(allowed.sum())),
            radius_scale=radius_scale,
            terminal_radius_scale=terminal_radius_scale,
            allowed_mask=allowed,
        )
    validate_weights(result, max_influences=max_influences)
    return result


def region_capsule_weights_3d(
    vertices: np.ndarray,
    offsets: np.ndarray,
    parents: np.ndarray,
    names: list[str],
    region_joints: dict[str, tuple[str, ...]],
    *,
    max_influences: int = 2,
    radius_scale: float = 0.30,
    terminal_radius_scale: float = 0.15,
    region_temperature: float = 0.08,
    torso_preference: float = 0.80,
    torso_margin: float = 0.12,
    exclusive_region_tokens: tuple[str, ...] = ("head", "neck", "face", "skull", "jaw"),
    exclusive_region_max_influences: int = 1,
) -> np.ndarray:
    """Assign capsule weights from 3-D anatomical regions only.

    Unlike :func:`region_capsule_weights`, this policy never projects the
    mesh or skeleton into a camera basis.  It first computes each region's
    nearest 3-D bone-segment distance, applies a small torso preference when
    a limb is not clearly closer, and then blends the region-local capsule
    weights.  The preference is a bounded ownership prior, not an image-fit
    heuristic: a hand or foot still wins when it is substantially closer to
    its own chain, while a thigh capsule cannot own an unrelated torso merely
    because both overlap in one view.

    Cranial regions are exclusive at their nearest 3-D surface. A soft
    region mixture is useful at broad anatomical boundaries, but allowing an
    arm capsule to retain a secondary share on a face or muzzle makes that
    geometry follow the arm during a clip. Region names are the authored
    semantic contract; the token match is generic across profiles and does
    not special-case any asset. Within an exclusive region, the local capsule
    is also sparse to ``exclusive_region_max_influences`` (one by default),
    so a muzzle cannot shear between neck and head joints.
    """
    vertices = np.asarray(vertices, dtype=np.float64)
    offsets = np.asarray(offsets, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    names = list(names)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all():
        raise ValueError("vertices must be finite [V,3]")
    if len(names) != len(offsets) or max_influences < 1 or max_influences > len(names):
        raise ValueError("invalid 3-D region correspondence inputs")
    if not np.isfinite(region_temperature) or region_temperature <= 0.0:
        raise ValueError("region_temperature must be finite and positive")
    if not np.isfinite(torso_preference) or not 0.0 < torso_preference <= 1.0:
        raise ValueError("torso_preference must be in (0,1]")
    if not np.isfinite(torso_margin) or torso_margin < 0.0:
        raise ValueError("torso_margin must be finite and nonnegative")
    if not isinstance(exclusive_region_tokens, tuple) or not all(
        isinstance(token, str) and token.strip() for token in exclusive_region_tokens
    ):
        raise ValueError("exclusive_region_tokens must be a tuple of non-empty strings")
    if int(exclusive_region_max_influences) < 1 or int(exclusive_region_max_influences) > int(max_influences):
        raise ValueError("exclusive_region_max_influences must be in [1, max_influences]")
    index = {name: i for i, name in enumerate(names)}
    region_indices: dict[str, np.ndarray] = {}
    claimed: set[int] = set()
    for region, members in region_joints.items():
        indices = np.asarray([index[name] for name in members if name in index], dtype=np.int64)
        if len(indices) == 0:
            raise ValueError(f"region {region!r} has no matching joints")
        overlap = claimed.intersection(int(value) for value in indices)
        if overlap:
            raise ValueError(f"region joints overlap: {sorted(overlap)}")
        claimed.update(int(value) for value in indices)
        region_indices[str(region)] = indices
    missing = sorted(set(range(len(names))) - claimed)
    if missing:
        raise ValueError(f"region joints do not cover skeleton: {[names[i] for i in missing]}")

    worlds = rest_world_from_offsets(offsets, parents)
    joints = worlds[:, :3, 3]
    span = max(float(np.ptp(vertices, axis=0).max()), 1e-8)

    def segment_distance_for_joint(joint: int) -> np.ndarray:
        parent = int(parents[joint])
        if parent < 0:
            children = np.where(parents == joint)[0]
            end = joints[int(children[0])] if len(children) else joints[joint] + np.array([0.0, span * 0.08, 0.0])
            return _segment_distance(vertices, joints[joint], end)
        return _segment_distance(vertices, joints[parent], joints[joint])

    regions = list(region_indices)
    distances = np.stack(
        [np.min(np.stack([segment_distance_for_joint(int(j)) for j in region_indices[region]], axis=1), axis=1)
         for region in regions], axis=1
    )
    scores = distances.copy()
    torso_index = next((i for i, region in enumerate(regions) if region == "torso"), None)
    if torso_index is not None:
        torso_distance = distances[:, torso_index]
        # A limb must be clearly closer than the torso before it can win.
        # This is expressed as a bounded world-space margin, so it remains
        # stable under global scale and does not encode a viewing direction.
        limb = np.arange(len(regions)) != torso_index
        protected = distances[:, limb] >= torso_preference * torso_distance[:, None]
        scores[:, limb] += protected * (float(torso_margin) * span)
    logits = -(scores - np.min(scores, axis=1, keepdims=True)) / max(float(region_temperature) * span, 1e-8)
    region_mix = np.exp(np.clip(logits, -60.0, 0.0))
    region_mix /= np.maximum(region_mix.sum(axis=1, keepdims=True), 1e-12)

    # Preserve articulated anatomy at the 3-D ownership boundary. The
    # nearest region is already the camera-free geometric winner; making a
    # semantic cranial region exclusive there prevents a nearby shoulder or
    # arm capsule from becoming a second influence on muzzle/face vertices.
    exclusive_regions = [
        i for i, region in enumerate(regions)
        if any(token.lower() in region.lower() for token in exclusive_region_tokens)
    ]
    if exclusive_regions:
        nearest_region = np.argmin(distances, axis=1)
        exclusive_mask = np.isin(nearest_region, np.asarray(exclusive_regions, dtype=np.int64))
        if np.any(exclusive_mask):
            region_mix[exclusive_mask] = 0.0
            region_mix[exclusive_mask, nearest_region[exclusive_mask]] = 1.0

    result = np.zeros((len(vertices), len(names)), dtype=np.float64)
    for region_index, region in enumerate(regions):
        allowed = np.zeros(len(names), dtype=bool)
        allowed[region_indices[region]] = True
        local = capsule_bone_weights(
            vertices, offsets, parents,
            max_influences=min(
                int(max_influences),
                int(allowed.sum()),
                int(exclusive_region_max_influences)
                if region_index in exclusive_regions else int(max_influences),
            ),
            radius_scale=radius_scale,
            terminal_radius_scale=terminal_radius_scale,
            allowed_mask=allowed,
        )
        result += region_mix[:, region_index, None] * local
    result = sparsify_weights(result, max_influences=max_influences)
    validate_weights(result, max_influences=max_influences)
    return result


def transfer_weights_from_donor(
    vertices: np.ndarray,
    donor_vertices: np.ndarray,
    donor_weights: np.ndarray,
    *,
    neighbors: int = 8,
    max_influences: int = 4,
) -> np.ndarray:
    """Transfer known mocap skin by geometric correspondence, not bone proximity.

    The donor is an already validated mocap-owned skin in the same bind
    coordinate system.  Inverse-distance blending over a local donor surface
    preserves anatomical regions better than assigning each target vertex to
    the nearest joint or bone segment.
    """
    vertices = np.asarray(vertices, dtype=np.float64)
    donor_vertices = np.asarray(donor_vertices, dtype=np.float64)
    donor_weights = np.asarray(donor_weights, dtype=np.float64)
    if vertices.ndim != 2 or donor_vertices.ndim != 2 or donor_vertices.shape[1] != 3 or vertices.shape[1] != 3:
        raise ValueError("vertices/donor_vertices must be [N,3]")
    if donor_weights.shape[0] != len(donor_vertices) or not np.isfinite(donor_weights).all():
        raise ValueError("donor weights do not match donor surface")
    if neighbors < 1 or neighbors > len(donor_vertices):
        raise ValueError("invalid donor neighbor count")
    tree = cKDTree(donor_vertices)
    distances, ids = tree.query(vertices, k=neighbors, workers=-1)
    distances = np.atleast_2d(distances)
    ids = np.atleast_2d(ids)
    if distances.shape[0] != len(vertices):
        distances, ids = distances.T, ids.T
    influence = donor_weights.shape[1]
    dense = np.zeros((len(vertices), influence), dtype=np.float64)
    exact = distances[:, 0] < 1e-8
    dense[exact] = donor_weights[ids[exact, 0]]
    active = ~exact
    if np.any(active):
        kernel = 1.0 / np.maximum(distances[active], 1e-8) ** 2
        kernel /= kernel.sum(axis=1, keepdims=True)
        dense[active] = np.einsum("nk,nkj->nj", kernel, donor_weights[ids[active]])
    if max_influences < influence:
        keep = np.argpartition(-dense, kth=max_influences - 1, axis=1)[:, :max_influences]
        sparse = np.zeros_like(dense)
        sparse[np.arange(len(vertices))[:, None], keep] = np.take_along_axis(dense, keep, axis=1)
        dense = sparse
    dense /= np.maximum(dense.sum(axis=1, keepdims=True), 1e-12)
    return dense


def fit_rest_skeleton_to_surface(
    rest_world: np.ndarray,
    vertices: np.ndarray,
    parents: np.ndarray | None = None,
    *,
    anisotropy_limit: float = 2.0,
    objective: str = "bone_surface",
) -> tuple[np.ndarray, np.ndarray]:
    """Fit mocap bind joints to a target surface with a robust anisotropic AABB.

    This changes only bind translations. Local rotations and hierarchy remain
    mocap-owned, while per-axis scale prevents a generated mesh's arbitrary
    normalization from making every bone effectively the wrong length. The
    default ``bone_surface`` objective scores transformed bone samples against
    the surface; ``symmetric_3d`` additionally scores surface coverage against
    the bone cloud, and neither objective uses a camera.
    """
    joints = np.asarray(rest_world, dtype=np.float64).copy()
    vertices = np.asarray(vertices, dtype=np.float64)
    parents = np.full(len(joints), -1, dtype=np.int64) if parents is None else np.asarray(parents, dtype=np.int64)
    if joints.ndim != 3 or joints.shape[1:] != (4, 4) or vertices.ndim != 2 or vertices.shape[1] != 3 or parents.shape != (len(joints),):
        raise ValueError("rest_world/vertices have invalid shapes")
    if float(anisotropy_limit) < 1.0 or not np.isfinite(anisotropy_limit):
        raise ValueError("anisotropy_limit must be finite and at least one")
    if objective not in {"bone_surface", "symmetric_3d"}:
        raise ValueError("objective must be 'bone_surface' or 'symmetric_3d'")
    points = joints[:, :3, 3]
    lo, hi = np.percentile(vertices, (2.0, 98.0), axis=0)
    mesh_center = 0.5 * (lo + hi)
    joint_center = 0.5 * (points.min(0) + points.max(0))
    mesh_axes = np.linalg.eigh(np.cov((vertices - vertices.mean(0)).T))[1][:, ::-1]
    joint_axes = np.linalg.eigh(np.cov((points - points.mean(0)).T))[1][:, ::-1]
    mesh_span = np.maximum(np.ptp((vertices - mesh_center) @ mesh_axes, axis=0), 1e-6)
    joint_span = np.maximum(np.ptp((points - joint_center) @ joint_axes, axis=0), 1e-6)
    sample = vertices[::max(1, len(vertices) // 12000)]
    tree = cKDTree(sample)
    best = None
    for perm in permutations(range(3)):
        permutation = np.eye(3)[:, perm]
        candidate_span = joint_span[np.asarray(perm, dtype=np.int64)]
        candidate_scale = mesh_span / np.maximum(candidate_span, 1e-6)
        # A generated mesh can have a different aspect ratio, but unconstrained
        # per-axis fitting turns a compact mocap rig into a stretched one. Cap
        # the ratio so correspondence remains anatomically plausible.
        median_scale = float(np.median(candidate_scale))
        ratio = float(anisotropy_limit)
        candidate_scale = np.clip(
            candidate_scale,
            median_scale / np.sqrt(ratio),
            median_scale * np.sqrt(ratio),
        )
        for signs in product((-1.0, 1.0), repeat=3):
            rotation = mesh_axes @ (permutation * np.asarray(signs)[None, :]) @ joint_axes.T
            if np.linalg.det(rotation) < 0.0:
                continue
            # Work in the mesh principal basis, where ``candidate_scale`` is
            # defined. Scaling after rotating into world axes mixes the OBB
            # axes and was the source of the previous stretched bind.
            principal = (points - joint_center) @ joint_axes
            principal = principal[:, np.asarray(perm, dtype=np.int64)] * np.asarray(signs)[None, :]
            transformed_points = (principal * candidate_scale[None, :]) @ mesh_axes.T + mesh_center
            clouds = []
            for index, parent in enumerate(parents):
                if int(parent) >= 0:
                    clouds.append(np.linspace(transformed_points[int(parent)], transformed_points[index], 9))
            bone_cloud = np.concatenate(clouds) if clouds else transformed_points
            forward = tree.query(bone_cloud, k=1, workers=-1)[0]
            if objective == "bone_surface":
                score = float(np.median(forward))
            else:
                # A one-way bone-to-surface median can accept a skeleton that
                # passes through the target body while leaving large surface
                # regions unsupported.  The symmetric objective remains fully
                # 3D: it balances bone-to-surface fit with surface coverage
                # against the transformed bone cloud, using robust quantiles so
                # wings, claws, and small Meshy outliers do not dominate.
                reverse = cKDTree(bone_cloud).query(sample, k=1, workers=-1)[0]
                score = float(
                    0.35 * np.median(forward)
                    + 0.45 * np.median(reverse)
                    + 0.20 * np.quantile(reverse, 0.90)
                )
            if best is None or score < best[0]:
                best = (score, rotation, transformed_points, candidate_scale)
    if best is None:
        raise ValueError("could not find a proper skeleton-to-surface orientation")
    transformed = joints.copy()
    transformed[:, :3, 3] = best[2]
    return transformed, best[3]


def _quat_mul(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    ax, ay, az, aw = a.unbind(-1)
    bx, by, bz, bw = b.unbind(-1)
    return torch.stack((aw * bx + ax * bw + ay * bz - az * by,
                        aw * by - ax * bz + ay * bw + az * bx,
                        aw * bz + ax * by - ay * bx + az * bw,
                        aw * bw - ax * bx - ay * by - az * bz), dim=-1)


def dual_quaternion_skin(vertices: torch.Tensor, weights: torch.Tensor, transforms: torch.Tensor) -> torch.Tensor:
    """Skin ``[V,3]`` vertices with weighted dual quaternions.

    ``transforms`` are frame/joint affine matrices already multiplied by the
    inverse bind.  Sign alignment before blending avoids quaternion
    antipodality; dual-quaternion blending preserves volume better than LBS
    through the large rotations present in sprite mocap.
    """
    if vertices.ndim != 2 or vertices.shape[-1] != 3 or weights.ndim != 2 or transforms.ndim != 4:
        raise ValueError("invalid dual-quaternion skin shapes")
    rotation = transforms[..., :3, :3].detach().cpu().numpy()
    from eagle_glb import matrices_to_xyzw
    q_np = matrices_to_xyzw(rotation)
    q = torch.as_tensor(q_np, dtype=vertices.dtype, device=vertices.device)
    translation = transforms[..., :3, 3]
    t_quat = torch.cat((translation, torch.zeros_like(translation[..., :1])), dim=-1)
    dual = 0.5 * _quat_mul(t_quat, q)
    # Align each joint to the hemisphere of the strongest influencing joint
    # for that vertex.  A single global reference (usually joint 0) can be on
    # the opposite side of a near-180-degree limb and cause cancellation.
    anchor_q = q[:, torch.argmax(weights, dim=1)]
    blended_real = torch.zeros((q.shape[0], vertices.shape[0], 4), dtype=q.dtype, device=q.device)
    blended_dual = torch.zeros_like(blended_real)
    for joint in range(q.shape[1]):
        sign = torch.where((q[:, joint, None, :] * anchor_q).sum(-1) < 0.0, -1.0, 1.0)
        weighted = weights[:, joint][None, :, None] * sign[..., None]
        blended_real = blended_real + weighted * q[:, joint, None, :]
        blended_dual = blended_dual + weighted * dual[:, joint, None, :]
    norm = torch.linalg.vector_norm(blended_real, dim=-1, keepdim=True).clamp_min(1e-8)
    real = blended_real / norm
    dual = blended_dual / norm
    conjugate = torch.cat((-real[..., :3], real[..., 3:]), dim=-1)
    corrected_dual = dual - real * (real * dual).sum(-1, keepdim=True)
    point = torch.cat((vertices.expand(real.shape[0], -1, -1), torch.zeros((real.shape[0], len(vertices), 1), dtype=vertices.dtype, device=vertices.device)), dim=-1)
    rotated = _quat_mul(_quat_mul(real, point), conjugate)[..., :3]
    offset = 2.0 * _quat_mul(corrected_dual, conjugate)[..., :3]
    return rotated + offset


def optimize_mocap_weights(
    vertices: np.ndarray,
    initial_weights: np.ndarray,
    transforms: torch.Tensor,
    renderer,
    targets: tuple[torch.Tensor, torch.Tensor, torch.Tensor],
    *,
    max_influences: int = 4,
    steps: int = 200,
    learning_rate: float = 0.03,
    prior_weight: float = 20.0,
    edge_pairs: np.ndarray | None = None,
    edge_lengths: np.ndarray | None = None,
) -> tuple[np.ndarray, list[dict[str, float]]]:
    """Fit sparse mocap weights against sprite images with fixed bones.

    The optimization owns only vertex-to-mocap influence logits.  Bones,
    bind transforms, camera, texture, and target frames remain fixed.  This
    makes the step generic across units and keeps image supervision from
    silently changing the motion source.  Optional edge strain regularizes
    volume without requiring a validated donor skin.
    """
    if int(steps) < 1:
        raise ValueError("steps must be positive")
    device = transforms.device
    field = MocapSparseWeightField(initial_weights, max_influences=max_influences, device=str(device))
    optimizer = torch.optim.Adam(field.parameters(), lr=float(learning_rate))
    vertex_tensor = torch.as_tensor(vertices, dtype=torch.float32, device=device)
    target_rgb, target_alpha, target_distance = targets
    edges = None if edge_pairs is None else torch.as_tensor(edge_pairs, dtype=torch.long, device=device)
    lengths = None if edge_lengths is None else torch.as_tensor(edge_lengths, dtype=torch.float32, device=device)
    from skin_image_objective import image_loss

    best_loss = float("inf")
    best_state = None
    history: list[dict[str, float]] = []
    for step in range(int(steps)):
        optimizer.zero_grad(set_to_none=True)
        weights = field.weights()
        posed = dual_quaternion_skin(vertex_tensor, weights, transforms)
        rgb, alpha = renderer.render(posed)
        losses = image_loss(rgb, alpha, target_rgb, target_alpha, target_distance)
        objective = losses["total"] + float(prior_weight) * field.penalty()
        strain = torch.zeros((), dtype=objective.dtype, device=device)
        if edges is not None and lengths is not None:
            actual = torch.linalg.vector_norm(posed[:, edges[:, 0]] - posed[:, edges[:, 1]], dim=-1)
            strain = torch.log((actual / lengths).clamp_min(1e-4)).square().mean()
            objective = objective + 0.15 * strain
        if not torch.isfinite(objective):
            raise ValueError("nonfinite mocap weight objective")
        objective.backward()
        torch.nn.utils.clip_grad_norm_(field.parameters(), 1.0)
        optimizer.step()
        score = float(objective.detach())
        row = {"step": float(step), "objective": score, "silhouette": float(losses["silhouette"].detach()),
               "color": float(losses["color"].detach()), "iou": float(losses["iou"].detach()),
               "strain": float(strain.detach())}
        if step % 25 == 0 or step == int(steps) - 1:
            history.append(row)
        if score < best_loss:
            best_loss = score
            best_state = {key: value.detach().clone() for key, value in field.state_dict().items()}
    if best_state is None:
        raise RuntimeError("mocap weight optimization produced no candidate")
    field.load_state_dict(best_state)
    return field.weights().detach().cpu().numpy(), history


def optimize_sequence_weights_3d(
    vertices: np.ndarray,
    triangles: np.ndarray,
    initial_weights: np.ndarray,
    transforms: torch.Tensor,
    *,
    max_influences: int = 2,
    steps: int = 80,
    learning_rate: float = 0.03,
    prior_weight: float = 2.0,
    rigidity_weight: float = 1.0,
    length_weight: float = 0.35,
    area_weight: float = 0.15,
    smoothness_weight: float = 0.08,
    motion_weight: float = 0.50,
    motion_floor: float = 0.70,
    max_total_variation: float = 0.25,
    max_edges: int = 16000,
    max_triangles: int = 8000,
    articulation_regions: list[np.ndarray] | None = None,
    articulation_targets: np.ndarray | None = None,
    articulation_weight: float = 0.75,
    vertex_motion_targets: np.ndarray | None = None,
    vertex_motion_confidence: np.ndarray | None = None,
    vertex_motion_weight: float = 0.25,
) -> tuple[np.ndarray, list[dict[str, float]]]:
    """Learn sparse weights from a complete 3-D pose sequence.

    This is indirect, example-based supervision: the mocap transforms are
    fixed, while weights are optimized so neighboring vertices follow a
    coherent locally-rigid trajectory across every supplied frame.  The
    rigidity term is a local-global ARAP step: each sampled triangle gets its
    own best-fit rotation for the current iterate, then the weight field is
    updated against that detached rotation.  Unlike a dominant-bone edge
    target, this does not force a triangle crossing an articulation boundary to
    follow one bone.  Edge length, triangle area, and support smoothness remain
    bounded regularizers.  A lower-bound motion prior penalizes the optimizer
    for obtaining a low rigidity loss by attaching articulated geometry to
    the root: candidate per-vertex motion energy below
    ``motion_floor`` of the geometry-derived initialization incurs an
    additional loss. The result is therefore a sequence-aware rigging pass,
    not an image-fitting pass.
    """
    if int(steps) < 1:
        raise ValueError("steps must be positive")
    if transforms.ndim != 4 or transforms.shape[-2:] != (4, 4):
        raise ValueError("transforms must have shape [F,J,4,4]")
    verts = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(triangles, dtype=np.int64)
    initial = np.asarray(initial_weights, dtype=np.float64)
    if verts.ndim != 2 or verts.shape[1] != 3 or not np.isfinite(verts).all():
        raise ValueError("vertices must be finite [V,3]")
    if faces.ndim != 2 or faces.shape[1] != 3 or len(faces) == 0:
        raise ValueError("triangles must be nonempty [T,3]")
    if np.any(faces < 0) or np.any(faces >= len(verts)):
        raise ValueError("triangles reference vertices outside the mesh")
    validate_weights(initial, max_influences=max_influences)
    if transforms.shape[1] != initial.shape[1]:
        raise ValueError("transform joint count does not match weights")
    if int(max_edges) < 1 or int(max_triangles) < 1:
        raise ValueError("max_edges and max_triangles must be positive")
    if float(motion_weight) < 0.0 or not 0.0 < float(motion_floor) <= 1.0:
        raise ValueError("motion_weight must be nonnegative and motion_floor must be in (0,1]")
    if not 0.0 < float(max_total_variation) <= 2.0:
        raise ValueError("max_total_variation must be in (0,2]")
    if float(articulation_weight) < 0.0:
        raise ValueError("articulation_weight must be nonnegative")
    if float(vertex_motion_weight) < 0.0:
        raise ValueError("vertex_motion_weight must be nonnegative")
    if (articulation_regions is None) != (articulation_targets is None):
        raise ValueError("articulation_regions and articulation_targets must be supplied together")
    if (vertex_motion_targets is None) != (vertex_motion_confidence is None):
        raise ValueError("vertex_motion_targets and vertex_motion_confidence must be supplied together")

    # Deterministic topology samples keep the optimizer bounded for dense
    # Meshy outputs while retaining every edge/triangle on small meshes.
    edge_pairs = np.unique(
        np.sort(np.concatenate((faces[:, :2], faces[:, 1:], faces[:, [0, 2]]), axis=0), axis=1),
        axis=0,
    )
    if len(edge_pairs) > int(max_edges):
        ids = np.linspace(0, len(edge_pairs) - 1, int(max_edges), dtype=np.int64)
        edge_pairs = edge_pairs[ids]
    tri_ids = np.arange(len(faces), dtype=np.int64)
    if len(tri_ids) > int(max_triangles):
        tri_ids = np.linspace(0, len(tri_ids) - 1, int(max_triangles), dtype=np.int64)
    sampled_faces = faces[tri_ids]

    e0, e1 = edge_pairs[:, 0], edge_pairs[:, 1]
    rest_edges = verts[e1] - verts[e0]
    rest_lengths = np.linalg.norm(rest_edges, axis=1)
    valid_edges = rest_lengths > 1e-8
    if not np.any(valid_edges):
        raise ValueError("sequence fit requires at least one nondegenerate mesh edge")
    edge_pairs = edge_pairs[valid_edges]
    rest_edges = rest_edges[valid_edges]
    rest_lengths = rest_lengths[valid_edges]
    e0, e1 = edge_pairs[:, 0], edge_pairs[:, 1]
    edge_agreement = np.einsum("ij,ij->i", initial[e0], initial[e1])
    edge_confidence = np.clip(0.15 + edge_agreement, 0.15, 1.15)
    tri_v0, tri_v1, tri_v2 = sampled_faces.T
    rest_cross = np.cross(verts[tri_v1] - verts[tri_v0], verts[tri_v2] - verts[tri_v0])
    rest_area2 = np.linalg.norm(rest_cross, axis=1)
    # Reject only triangles that are numerically collinear relative to this
    # mesh.  A fixed absolute threshold would discard valid small units or
    # retain unstable slivers after a unit-scale change.
    area_floor = max(float(np.median(rest_lengths)) ** 2 * 1e-8, 1e-12)
    valid_triangles = rest_area2 > area_floor
    if not np.any(valid_triangles):
        raise ValueError("sequence fit requires at least one nondegenerate mesh triangle")
    tri_v0, tri_v1, tri_v2 = tri_v0[valid_triangles], tri_v1[valid_triangles], tri_v2[valid_triangles]
    rest_area2 = rest_area2[valid_triangles]
    tri_confidence = np.clip(
        0.15 + (np.einsum("ij,ij->i", initial[tri_v0], initial[tri_v1])
                + np.einsum("ij,ij->i", initial[tri_v1], initial[tri_v2])
                + np.einsum("ij,ij->i", initial[tri_v2], initial[tri_v0])) / 3.0,
        0.15, 1.15,
    )
    tri_area_weight = np.clip(
        rest_area2 / max(float(np.median(rest_area2)), 1e-12), 0.25, 4.0
    )

    device = transforms.device
    support = topology_weight_support(initial, edge_pairs, max_influences=max_influences)
    field = MocapSparseWeightField(
        initial, max_influences=max_influences, device=str(device), support=support
    )
    optimizer = torch.optim.Adam(field.parameters(), lr=float(learning_rate))
    vertex_tensor = torch.as_tensor(verts, dtype=torch.float32, device=device)
    edge_ids = torch.as_tensor(edge_pairs, dtype=torch.long, device=device)
    rest_edge_tensor = torch.as_tensor(rest_edges, dtype=torch.float32, device=device)
    rest_length_tensor = torch.as_tensor(rest_lengths, dtype=torch.float32, device=device)
    edge_conf_tensor = torch.as_tensor(edge_confidence, dtype=torch.float32, device=device)
    tri_ids_tensor = torch.as_tensor(np.stack((tri_v0, tri_v1, tri_v2), axis=1), dtype=torch.long, device=device)
    rest_area_tensor = torch.as_tensor(rest_area2, dtype=torch.float32, device=device)
    tri_conf_tensor = torch.as_tensor(tri_confidence, dtype=torch.float32, device=device)
    tri_area_weight_tensor = torch.as_tensor(tri_area_weight, dtype=torch.float32, device=device)
    arap_weight_tensor = tri_conf_tensor * tri_area_weight_tensor
    # Triangle-local ARAP is evaluated in the optimizer loop.  Keeping the
    # rest triangles centered makes the polar fit insensitive to translation;
    # the detached rotation is the usual local step in an alternating ARAP
    # solve and avoids learning a camera- or bone-specific deformation.
    rest_triangles = vertex_tensor[tri_ids_tensor]
    rest_tri_centered = rest_triangles - rest_triangles.mean(dim=1, keepdim=True)
    rest_tri_scale = torch.linalg.vector_norm(rest_tri_centered, dim=-1).mean(dim=-1).clamp_min(1e-5)
    initial_tensor = torch.as_tensor(initial, dtype=torch.float32, device=device)
    region_ids_tensor: list[torch.Tensor] = []
    articulation_target_tensor = None
    articulation_scale_tensor = None
    if articulation_regions is not None and articulation_targets is not None:
        target_array = np.asarray(articulation_targets, dtype=np.float64)
        if target_array.ndim != 3 or target_array.shape[2] != 3 or target_array.shape[0] != int(transforms.shape[0]):
            raise ValueError("articulation_targets must have shape [F,R,3] matching transforms")
        if len(articulation_regions) != target_array.shape[1] or not np.isfinite(target_array).all():
            raise ValueError("articulation region/target count mismatch or nonfinite target")
        for ids in articulation_regions:
            ids_array = np.asarray(ids, dtype=np.int64)
            if ids_array.ndim != 1 or len(ids_array) < 1 or np.any(ids_array < 0) or np.any(ids_array >= len(verts)):
                raise ValueError("articulation regions must contain valid vertex ids")
            region_ids_tensor.append(torch.as_tensor(ids_array, dtype=torch.long, device=device))
        articulation_target_tensor = torch.as_tensor(target_array, dtype=torch.float32, device=device)
        target_delta = articulation_target_tensor - articulation_target_tensor[:1]
        articulation_scale_tensor = torch.linalg.vector_norm(target_delta, dim=-1).square().mean(dim=0).clamp_min(1e-6).sqrt()
    vertex_target_tensor = None
    vertex_confidence_tensor = None
    vertex_motion_scale_tensor = None
    if vertex_motion_targets is not None and vertex_motion_confidence is not None:
        vertex_targets = np.asarray(vertex_motion_targets, dtype=np.float64)
        confidence = np.asarray(vertex_motion_confidence, dtype=np.float64)
        if vertex_targets.shape != (int(transforms.shape[0]), len(verts), 3) or not np.isfinite(vertex_targets).all():
            raise ValueError("vertex_motion_targets must have shape [F,V,3] matching transforms")
        if confidence.shape != (len(verts),) or not np.isfinite(confidence).all() or np.any(confidence < 0.0):
            raise ValueError("vertex_motion_confidence must be finite and nonnegative [V]")
        vertex_target_tensor = torch.as_tensor(vertex_targets, dtype=torch.float32, device=device)
        vertex_confidence_tensor = torch.as_tensor(confidence, dtype=torch.float32, device=device)
        vertex_delta = vertex_target_tensor - vertex_target_tensor[:1]
        vertex_motion_scale_tensor = torch.linalg.vector_norm(vertex_delta, dim=-1).square().mean(dim=0).clamp_min(1e-6).sqrt()
    with torch.no_grad():
        reference_posed = dual_quaternion_skin(vertex_tensor, initial_tensor, transforms)
        reference_centered = reference_posed - reference_posed.mean(dim=0, keepdim=True)
        reference_motion = reference_centered.square().sum(-1).mean(dim=0)
    motion_mask = reference_motion > 1e-8

    best_loss = float("inf")
    best_state = None
    history: list[dict[str, float]] = []
    for step in range(int(steps)):
        optimizer.zero_grad(set_to_none=True)
        weights = field.weights()
        posed = dual_quaternion_skin(vertex_tensor, weights, transforms)
        posed_centered = posed - posed.mean(dim=0, keepdim=True)
        motion_energy = posed_centered.square().sum(-1).mean(dim=0)
        motion_required = float(motion_floor) * reference_motion
        motion_deficit = torch.relu(motion_required - motion_energy) / motion_required.clamp_min(1e-8)
        motion_loss = (
            motion_deficit[motion_mask].mean()
            if bool(torch.any(motion_mask))
            else torch.zeros((), dtype=posed.dtype, device=posed.device)
        )
        articulation_loss = torch.zeros((), dtype=posed.dtype, device=posed.device)
        if articulation_target_tensor is not None and region_ids_tensor:
            observed_centroids = torch.stack([posed[:, ids].mean(dim=1) for ids in region_ids_tensor], dim=1)
            observed_delta = observed_centroids - observed_centroids[:1]
            target_delta = articulation_target_tensor - articulation_target_tensor[:1]
            normalized_error = (observed_delta - target_delta) / articulation_scale_tensor[None, :, None]
            articulation_loss = normalized_error.square().sum(-1).mean()
        vertex_motion_loss = torch.zeros((), dtype=posed.dtype, device=posed.device)
        if vertex_target_tensor is not None and vertex_confidence_tensor is not None:
            observed_delta = posed - posed[:1]
            target_delta = vertex_target_tensor - vertex_target_tensor[:1]
            normalized_error = (observed_delta - target_delta) / vertex_motion_scale_tensor[None, :, None]
            per_vertex = normalized_error.square().sum(-1).mean(dim=0)
            vertex_motion_loss = (per_vertex * vertex_confidence_tensor).sum() / vertex_confidence_tensor.sum().clamp_min(1e-8)
        weight_total_variation = torch.abs(weights - initial_tensor).sum(dim=1)
        trust_violation = torch.relu(weight_total_variation - float(max_total_variation)).square().mean()
        posed_edges = posed[:, edge_ids[:, 1]] - posed[:, edge_ids[:, 0]]
        posed_triangles = posed[:, tri_ids_tensor]
        posed_tri_centered = posed_triangles - posed_triangles.mean(dim=2, keepdim=True)
        covariance = torch.einsum("tni,ftnj->ftij", rest_tri_centered, posed_tri_centered)
        u, _singular, vh = torch.linalg.svd(covariance)
        rotation = vh.transpose(-2, -1) @ u.transpose(-2, -1)
        # Reflection-safe polar factor.  A flipped triangle is penalized by
        # the residual/area terms rather than silently becoming a free mirror.
        determinant = torch.det(rotation)
        correction = torch.eye(3, dtype=rotation.dtype, device=rotation.device).expand(rotation.shape).clone()
        correction[..., -1, -1] = torch.where(determinant < 0.0, -1.0, 1.0)
        # Alternate local and global steps: the polar factor is a local
        # measurement for this iterate, not another parameter through which
        # the weight optimizer can game the objective.
        rotation = (vh.transpose(-2, -1) @ correction @ u.transpose(-2, -1)).detach()
        rigid_target = torch.einsum("tni,ftji->ftnj", rest_tri_centered, rotation)
        normalized = rest_tri_scale[None, :, None, None]
        rigidity = ((posed_tri_centered - rigid_target) / normalized).square().sum(-1).mean(-1)
        actual_lengths = torch.linalg.vector_norm(posed_edges, dim=-1)
        length_error = torch.log((actual_lengths / rest_length_tensor[None]).clamp_min(1e-4)).square()
        rigidity_loss = (
            rigidity * arap_weight_tensor[None]
        ).sum() / (arap_weight_tensor.sum() * rigidity.shape[0]).clamp_min(1e-8)
        length_loss = (length_error * edge_conf_tensor[None]).mean()

        tri_edges_a = posed[:, tri_ids_tensor[:, 1]] - posed[:, tri_ids_tensor[:, 0]]
        tri_edges_b = posed[:, tri_ids_tensor[:, 2]] - posed[:, tri_ids_tensor[:, 0]]
        posed_area = torch.linalg.vector_norm(torch.cross(tri_edges_a, tri_edges_b, dim=-1), dim=-1)
        area_error = torch.log((posed_area / rest_area_tensor[None]).clamp_min(1e-4)).square()
        area_loss = (area_error * tri_conf_tensor[None]).mean()

        edge_weights = weights[edge_ids]
        smooth_loss = ((edge_weights[:, 1] - edge_weights[:, 0]).square().sum(-1) * edge_conf_tensor).mean()
        objective = (
            float(rigidity_weight) * rigidity_loss
            + float(length_weight) * length_loss
            + float(area_weight) * area_loss
            + float(smoothness_weight) * smooth_loss
            + float(prior_weight) * field.penalty()
            + float(motion_weight) * motion_loss
            + float(articulation_weight) * articulation_loss
            + float(vertex_motion_weight) * vertex_motion_loss
            + (100.0 * float(prior_weight)) * trust_violation
        )
        if not torch.isfinite(objective):
            raise ValueError("nonfinite 3-D sequence weight objective")
        score = float(objective.detach())
        row = {
            "step": float(step), "objective": score,
            "rigidity": float(rigidity_loss.detach()),
            "arap": float(rigidity_loss.detach()),
            "length": float(length_loss.detach()),
            "area": float(area_loss.detach()),
            "smoothness": float(smooth_loss.detach()),
            "prior": float(field.penalty().detach()),
            "motion": float(motion_loss.detach()),
            "articulation": float(articulation_loss.detach()),
            "vertexMotion": float(vertex_motion_loss.detach()),
            "trustViolation": float(trust_violation.detach()),
        }
        if step % 10 == 0 or step == int(steps) - 1:
            history.append(row)
        if score < best_loss:
            best_loss = score
            best_state = {key: value.detach().clone() for key, value in field.state_dict().items()}
        objective.backward()
        torch.nn.utils.clip_grad_norm_(field.parameters(), 1.0)
        optimizer.step()
    if best_state is None:
        raise RuntimeError("3-D sequence weight optimization produced no candidate")
    field.load_state_dict(best_state)
    return field.weights().detach().cpu().numpy(), history


def pose_corrective_residuals_3d(
    rest_vertices: np.ndarray,
    posed_vertices: np.ndarray,
    triangles: np.ndarray,
    weights: np.ndarray,
    transforms: np.ndarray | torch.Tensor,
    *,
    steps: int = 2,
    strength: float = 0.25,
    max_displacement_ratio: float = 0.06,
) -> tuple[np.ndarray, list[dict[str, float]]]:
    """Project pose-dependent residuals toward local 3-D rigidity.

    This is a small, deterministic analogue of pose-corrective blend shapes:
    the skeleton and sparse weights remain unchanged, but each supplied pose
    receives a bounded residual only where high-agreement mesh edges disagree
    with the dominant bone's rigid trajectory. It is trained from the complete
    3-D sequence, uses no camera or sprite targets, and leaves joint-crossing
    edges mostly unconstrained so articulation is not ironed flat.
    """
    rest = np.asarray(rest_vertices, dtype=np.float64)
    posed = np.asarray(posed_vertices, dtype=np.float64)
    faces = np.asarray(triangles, dtype=np.int64)
    dense = np.asarray(weights, dtype=np.float64)
    matrix = transforms.detach().cpu().numpy() if isinstance(transforms, torch.Tensor) else np.asarray(transforms, dtype=np.float64)
    if rest.ndim != 2 or rest.shape[1] != 3 or posed.ndim != 3 or posed.shape[1:] != rest.shape:
        raise ValueError("rest_vertices/posed_vertices have invalid shapes")
    if faces.ndim != 2 or faces.shape[1] != 3 or np.any(faces < 0) or np.any(faces >= len(rest)):
        raise ValueError("triangles have invalid shape or indices")
    if dense.shape[0] != len(rest) or not np.isfinite(dense).all():
        raise ValueError("weights do not match rest_vertices")
    if matrix.shape != (len(posed), dense.shape[1], 4, 4) or not np.isfinite(matrix).all():
        raise ValueError("transforms do not match the pose sequence")
    if int(steps) < 1 or not np.isfinite(strength) or not 0.0 < strength <= 1.0:
        raise ValueError("steps/strength are invalid")
    if not np.isfinite(max_displacement_ratio) or max_displacement_ratio <= 0.0:
        raise ValueError("max_displacement_ratio must be positive")
    edge_pairs = np.unique(
        np.sort(np.concatenate((faces[:, :2], faces[:, 1:], faces[:, [0, 2]]), axis=0), axis=1),
        axis=0,
    )
    e0, e1 = edge_pairs[:, 0], edge_pairs[:, 1]
    rest_edges = rest[e1] - rest[e0]
    rest_lengths = np.linalg.norm(rest_edges, axis=1)
    valid = rest_lengths > 1e-8
    edge_pairs, rest_edges, rest_lengths = edge_pairs[valid], rest_edges[valid], rest_lengths[valid]
    e0, e1 = edge_pairs[:, 0], edge_pairs[:, 1]
    dominant = np.argmax(dense[e0] + dense[e1], axis=1)
    agreement = np.clip(np.einsum("ij,ij->i", dense[e0], dense[e1]), 0.0, 1.0)
    rotation = matrix[:, dominant, :3, :3]
    rigid_edges = np.einsum("feij,ej->fei", rotation, rest_edges)
    span = max(float(np.ptp(rest, axis=0).max()), 1e-8)
    residuals = np.zeros_like(posed)
    history: list[dict[str, float]] = []
    for frame in range(len(posed)):
        current = posed[frame].copy()
        frame_before = current.copy()
        for _ in range(int(steps)):
            actual = current[e1] - current[e0]
            error = rigid_edges[frame] - actual
            normalized_error = np.linalg.norm(error, axis=1) / np.maximum(rest_lengths, 1e-8)
            # High-agreement edges are likely one rigid patch. Joint-crossing
            # edges retain only a small contribution to avoid freezing motion.
            edge_weight = (0.15 + agreement) * np.clip(normalized_error / 0.20, 0.0, 1.0)
            delta0 = -0.5 * error
            delta1 = 0.5 * error
            accum = np.zeros_like(current)
            totals = np.zeros(len(current), dtype=np.float64)
            np.add.at(accum, e0, delta0 * edge_weight[:, None])
            np.add.at(accum, e1, delta1 * edge_weight[:, None])
            np.add.at(totals, e0, edge_weight)
            np.add.at(totals, e1, edge_weight)
            update = accum / np.maximum(totals[:, None], 1e-8)
            norm = np.linalg.norm(update, axis=1)
            limit = float(max_displacement_ratio) * span
            update *= np.minimum(1.0, limit / np.maximum(norm, 1e-8))[:, None]
            current += float(strength) * update
        residuals[frame] = current - frame_before
        history.append({
            "frame": float(frame),
            "meanResidual": float(np.linalg.norm(residuals[frame], axis=1).mean()),
            "maxResidual": float(np.linalg.norm(residuals[frame], axis=1).max()),
        })
    return residuals, history


class MocapSparseWeightField(torch.nn.Module):
    """Differentiable sparse weights for an arbitrary mesh and mocap rig.

    The support is derived only from the target mesh and mocap bone capsules;
    no unit-specific donor or Meshy skeleton is required.  Optimization can
    therefore use sprite losses while retaining a bounded influence budget.
    """

    def __init__(self, initial_weights: np.ndarray, *, max_influences: int = 4,
                 device: str = "cuda", support: np.ndarray | None = None):
        super().__init__()
        initial = np.asarray(initial_weights, dtype=np.float32)
        if initial.ndim != 2 or not np.isfinite(initial).all() or np.any(initial < 0):
            raise ValueError("initial_weights must be finite and nonnegative [V,J]")
        if not np.allclose(initial.sum(1), 1.0, atol=1e-5):
            raise ValueError("initial_weights must be normalized")
        if max_influences < 1 or max_influences > initial.shape[1]:
            raise ValueError("invalid max_influences")
        if support is None:
            ids = np.argpartition(-initial, kth=max_influences - 1, axis=1)[:, :max_influences]
        else:
            ids = np.asarray(support, dtype=np.int64)
            if ids.shape != (len(initial), int(max_influences)) or np.any(ids < 0) or np.any(ids >= initial.shape[1]):
                raise ValueError("support must have shape [V,max_influences] within joint range")
            if np.any(np.sort(ids, axis=1)[:, 1:] == np.sort(ids, axis=1)[:, :-1]):
                raise ValueError("support rows must contain unique joints")
        values = np.take_along_axis(initial, ids, axis=1)
        if np.any(values.sum(1) <= 1e-12):
            raise ValueError("support leaves a vertex with no initial influence")
        values /= np.maximum(values.sum(1, keepdims=True), 1e-8)
        self.vertex_count, self.joint_count = initial.shape
        self.max_influences = int(max_influences)
        self.register_buffer("support", torch.as_tensor(ids, dtype=torch.long, device=device))
        self.register_buffer("initial_sparse", torch.as_tensor(values, dtype=torch.float32, device=device))
        self.logits = torch.nn.Parameter(torch.log(self.initial_sparse.clamp_min(1e-6)))

    def weights(self) -> torch.Tensor:
        sparse = torch.softmax(self.logits, dim=1)
        dense = torch.zeros((self.vertex_count, self.joint_count), dtype=sparse.dtype, device=sparse.device)
        return dense.scatter(1, self.support, sparse)

    def penalty(self) -> torch.Tensor:
        return ((self.weights().gather(1, self.support) - self.initial_sparse) ** 2).mean()
