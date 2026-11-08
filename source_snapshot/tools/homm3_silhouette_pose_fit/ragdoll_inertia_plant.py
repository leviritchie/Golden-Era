"""Inertial carry post-pass after fused poses.

Experiment lane only (``ragdoll_inertia_v1``). Not pose-pipeline delivery and
not a ship payload. Gravity is off. A fused joint change is coasted into later
frames and fades; the pass must not flatten fused motion. JSON poses are
degrees through ``serialize_pose_degrees`` — never ``_pose_dicts``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from cascade_physics_smooth import (
    _rotvec_matrix,
    compose_rotvec,
    geodesic_radians,
)
from gpu_mesh_collision import (
    bind_extent_length,
    build_mesh_collision_pairs,
    collision_margin_from_bind,
)
from gpu_mesh_strain import posed_edge_lengths, rest_edge_lengths, unique_triangle_edges
from roc_gpu_cascade_experiment import (
    IDLE_END_ANCHOR_SKIP_DEF_GROUPS,
    MOTION_ROOT_KEY,
    MOTION_ROOT_ROTATION_KEY,
    clip_uses_idle_end_anchor,
)

SOLVER_ID = "ragdoll_inertia_v1"
FORBIDDEN_WRITE_PARTS = frozenset({"meshy_downloads", "fused_push_v24_pipeline"})
REPO_ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
WRITE_ROOT_RELATIVE = Path("artifacts") / "pose_picker_runs"

DT = 1.0 / 12.0
SUBSTEPS = 4
ZETA = 0.03
MU = 0.6
GRAVITY = 0.0
FUSED_INERTIA_MIX = 0.25
MOTION_KEEP_FRAC = 0.85
WORLD_UP = (0.0, 1.0, 0.0)
JOINT_LIMIT_DEG = 150.0
CLAMP_FRAC = 0.995
NUDGE_DEG_PER_FRAME = 15.0
RUNGS = (1.0 / 3.0, 2.0 / 3.0, 1.0)
EPSILON_THETA_DEG = 1.0
EPSILON_OMEGA_DEG_S = 2.0
TOP_K_CELLS = 64
MAX_FORWARD_SWEEPS = 30
MAX_REVERSE_SWEEPS = 30
STRAIN_SLACK = 0.04
KEEP_IMPROVE = 1e-4
FRAME_FLOOR_SLACK = 0.02
COLLISION_MEAN_SLACK = 0.01
COLLISION_FRAME_SLACK = 0.05
JOINT_DIAGONAL_AXES = 6
SKIP_SEARCH_BONES = frozenset({"Bone_000"})
WALL_CLOCK_CAP_S = 300.0
WALL_CLOCK_PACK_SIZE = 1
CONTACT_STABILITY = 0.3
EIGEN_REL_FLOOR = 1e-6
LAMBDA_ABS_SCALE = 1e-12
COLLISION_SAMPLE_COUNT = 256
COLLISION_GEODESIC_MIN_HOPS = 8
COLLISION_MARGIN_BODY_LENGTHS = 0.04
SCORE_COLLISION_WEIGHT = 0.35


def assert_ragdoll_write_path(path: str | Path, *, repo_root: str | Path = REPO_ROOT) -> Path:
    """Refuse fused-push / Meshy writes. Require the ragdoll experiment tree."""
    resolved = Path(path).resolve()
    root = Path(repo_root).resolve()
    allowed = (root / WRITE_ROOT_RELATIVE).resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise RuntimeError(
            f"ragdoll_inertia_v1 may only write under {allowed}; got {resolved}"
        ) from exc
    if any(part in FORBIDDEN_WRITE_PARTS for part in resolved.parts):
        raise RuntimeError(f"ragdoll_inertia_v1 must not write live payload paths: {resolved}")
    if SOLVER_ID not in resolved.parts:
        raise RuntimeError(
            f"ragdoll_inertia_v1 writes must include {SOLVER_ID} in the path; got {resolved}"
        )
    return resolved


def idle_end_required(def_groups: Sequence[int]) -> bool:
    return bool(clip_uses_idle_end_anchor(tuple(int(group) for group in def_groups)))


def death_skips_idle_end(def_groups: Sequence[int]) -> bool:
    sequence = tuple(int(group) for group in def_groups)
    if not sequence:
        return False
    last = sequence[-1]
    while last == 2 and len(sequence) > 1:
        sequence = sequence[:-1]
        last = sequence[-1]
    return last in IDLE_END_ANCHOR_SKIP_DEF_GROUPS


@dataclass(frozen=True)
class RagdollPlantConfig:
    dt: float = DT
    substeps: int = SUBSTEPS
    zeta: float = ZETA
    mu: float = MU
    gravity: float = GRAVITY
    world_up: tuple[float, float, float] = WORLD_UP
    joint_limit_deg: float = JOINT_LIMIT_DEG
    clamp_frac: float = CLAMP_FRAC
    collision_stiffness: float | None = None
    contact_stability: float = CONTACT_STABILITY

    def validate(self) -> None:
        if float(self.dt) <= 0.0 or int(self.substeps) < 1:
            raise ValueError("dt must be positive and substeps >= 1")
        if not (0.0 <= float(self.zeta) < 1.0):
            raise ValueError("zeta must be in [0, 1)")
        if float(self.mu) < 0.0 or float(self.gravity) < 0.0:
            raise ValueError("mu and gravity must be non-negative")
        if not (0.0 < float(self.clamp_frac) < 1.0):
            raise ValueError("clamp_frac must be in (0, 1)")
        if float(self.joint_limit_deg) <= 0.0:
            raise ValueError("joint_limit_deg must be positive")
        if float(self.contact_stability) <= 0.0:
            raise ValueError("contact_stability must be positive")


@dataclass
class RagdollPlant:
    node_names: tuple[str, ...]
    parents: tuple[int | None, ...]
    frozen_root: int
    translations: np.ndarray
    base_rotations: np.ndarray
    bind_origins: np.ndarray
    bind_world_rotations: np.ndarray
    bind_positions: np.ndarray
    triangles: np.ndarray
    peak_owner: np.ndarray
    rest_local_offsets: np.ndarray
    owned_mass: np.ndarray
    composite_mass: np.ndarray
    inertia_rest: np.ndarray
    lambda_max: np.ndarray
    inertia_inv_rest: np.ndarray
    bone_limit_scales: np.ndarray
    bone_lengths: np.ndarray
    descendants: tuple[tuple[int, ...], ...]
    ancestors: tuple[tuple[int, ...], ...]
    collision_pairs: np.ndarray
    collision_samples: np.ndarray
    collision_margin: float
    ground_y: float
    ground_delta_to_lowest: float
    contact_stiffness: float
    clamped_eigenvalues: tuple[tuple[int, int, float], ...]
    total_mass: float
    bind_extent: float
    tau_budget: float
    rest_edges: np.ndarray
    rest_edge_len: np.ndarray
    massless_joints: tuple[int, ...]

    def joint_count(self) -> int:
        return int(len(self.node_names))

    def clamp_limit_rad(self) -> np.ndarray:
        return (
            math.radians(float(JOINT_LIMIT_DEG))
            * float(CLAMP_FRAC)
            * np.asarray(self.bone_limit_scales, dtype=np.float64)
        )


@dataclass
class RagdollState:
    rotvecs: np.ndarray
    omega: np.ndarray
    alpha_control: np.ndarray
    clamp_counts: np.ndarray


def _require_finite(name: str, array: np.ndarray) -> None:
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must be finite")


def descendants_table(parents: Sequence[int | None]) -> tuple[tuple[int, ...], ...]:
    count = len(parents)
    children: list[list[int]] = [[] for _ in range(count)]
    for child, parent in enumerate(parents):
        if parent is None:
            continue
        if int(parent) < 0 or int(parent) >= count:
            raise ValueError(f"parent index {parent} is outside the skeleton")
        children[int(parent)].append(int(child))
    out: list[tuple[int, ...]] = []
    for index in range(count):
        stack = list(children[index])
        seen: list[int] = []
        while stack:
            node = int(stack.pop())
            if node in seen:
                raise ValueError("skeleton has a cycle")
            seen.append(node)
            stack.extend(children[node])
        out.append(tuple(seen))
    return tuple(out)


def ancestors_table(
    parents: Sequence[int | None],
    *,
    frozen_root: int,
) -> tuple[tuple[int, ...], ...]:
    count = len(parents)
    frozen = int(frozen_root)
    out: list[tuple[int, ...]] = []
    for index in range(count):
        chain: list[int] = []
        cursor: int | None = int(index)
        guard = 0
        while cursor is not None:
            if cursor == frozen:
                break
            chain.append(int(cursor))
            cursor = parents[int(cursor)]
            guard += 1
            if guard > count:
                raise ValueError("skeleton has a cycle")
        out.append(tuple(chain))
    return tuple(out)


def exclusive_peak_owners(
    *,
    joints: np.ndarray,
    weights: np.ndarray,
    vertex_count: int,
) -> np.ndarray:
    slots = np.asarray(joints, dtype=np.int64)
    skin = np.asarray(weights, dtype=np.float64)
    if slots.shape != skin.shape or slots.ndim != 2:
        raise ValueError("joints and weights must share shape (vertices, influences)")
    if int(slots.shape[0]) != int(vertex_count):
        raise ValueError("skin vertex count does not match bind positions")
    peak = np.argmax(skin, axis=1)
    peak_weight = skin[np.arange(int(vertex_count)), peak]
    if np.any(peak_weight <= 0.0):
        missing = int(np.sum(peak_weight <= 0.0))
        raise RuntimeError(f"{missing} skinned vertices have no peak bone")
    owners = slots[np.arange(int(vertex_count)), peak]
    if np.any(owners < 0):
        raise RuntimeError("peak joint index is negative")
    return owners.astype(np.int64)


def lumped_vertex_mass(positions: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    points = np.asarray(positions, dtype=np.float64)
    faces = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    mass = np.zeros((int(points.shape[0]),), dtype=np.float64)
    for a, b, c in faces:
        area = 0.5 * float(np.linalg.norm(np.cross(points[b] - points[a], points[c] - points[a])))
        share = area / 3.0
        mass[int(a)] += share
        mass[int(b)] += share
        mass[int(c)] += share
    if float(mass.sum()) <= 0.0:
        raise ValueError("lumped vertex mass is zero")
    return mass


def _inertia_about_origin(offsets: np.ndarray, masses: np.ndarray) -> np.ndarray:
    tensor = np.zeros((3, 3), dtype=np.float64)
    for offset, mass in zip(offsets, masses):
        radius = np.asarray(offset, dtype=np.float64).reshape(3)
        weight = float(mass)
        if weight <= 0.0:
            continue
        mag2 = float(np.dot(radius, radius))
        tensor += weight * (mag2 * np.eye(3) - np.outer(radius, radius))
    return tensor


def regularize_inertia(
    tensor: np.ndarray,
    *,
    joint_index: int,
    total_mass: float,
    bind_extent: float,
) -> tuple[np.ndarray, float, tuple[tuple[int, int, float], ...]]:
    matrix = np.asarray(tensor, dtype=np.float64).reshape(3, 3)
    matrix = 0.5 * (matrix + matrix.T)
    values, vectors = np.linalg.eigh(matrix)
    lambda_max = float(np.max(values))
    abs_floor = float(LAMBDA_ABS_SCALE) * float(total_mass) * (float(bind_extent) ** 2)
    if not math.isfinite(lambda_max) or lambda_max < abs_floor:
        raise RuntimeError(
            f"joint {joint_index} inertia lambda_max={lambda_max} is below "
            f"absolute floor {abs_floor}"
        )
    rel_floor = float(EIGEN_REL_FLOOR) * lambda_max
    clamped: list[tuple[int, int, float]] = []
    fixed = values.copy()
    for axis, value in enumerate(values.tolist()):
        if float(value) < rel_floor:
            clamped.append((int(joint_index), int(axis), float(value)))
            fixed[axis] = rel_floor
    regularized = vectors @ np.diag(fixed) @ vectors.T
    return regularized, lambda_max, tuple(clamped)


def contact_stiffness_for_mass(mass: float, *, dt_sub: float, stability: float = CONTACT_STABILITY) -> float:
    if float(mass) <= 0.0:
        raise ValueError("contact stiffness needs positive mass")
    omega_max = float(stability) / float(dt_sub)
    return float((omega_max ** 2) * float(mass) * 0.5)


def build_plant(
    *,
    node_names: Sequence[str],
    parents: Sequence[int | None],
    translations: np.ndarray,
    base_rotations: np.ndarray,
    bind_positions: np.ndarray,
    triangles: np.ndarray,
    joints: np.ndarray,
    weights: np.ndarray,
    frozen_root: int = 0,
    bone_limit_scales: np.ndarray | None = None,
    collision_sample_count: int = 8,
    collision_geodesic_min_hops: int = 2,
    collision_margin_body_lengths: float = COLLISION_MARGIN_BODY_LENGTHS,
    config: RagdollPlantConfig | None = None,
) -> RagdollPlant:
    cfg = config or RagdollPlantConfig()
    cfg.validate()
    names = tuple(str(name) for name in node_names)
    parent_list = tuple(None if parent is None else int(parent) for parent in parents)
    joint_count = len(names)
    if len(parent_list) != joint_count:
        raise ValueError("parents must match node_names")
    if int(frozen_root) < 0 or int(frozen_root) >= joint_count:
        raise ValueError("frozen_root is outside the skeleton")
    trans = np.asarray(translations, dtype=np.float64).reshape(joint_count, 3)
    bases = np.asarray(base_rotations, dtype=np.float64).reshape(joint_count, 3, 3)
    positions = np.asarray(bind_positions, dtype=np.float64)
    faces = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    if positions.ndim != 2 or int(positions.shape[1]) != 3:
        raise ValueError("bind_positions must have shape (vertices, 3)")
    owners = exclusive_peak_owners(joints=joints, weights=weights, vertex_count=int(positions.shape[0]))
    if int(owners.max()) >= joint_count:
        raise RuntimeError("peak owner is outside the skeleton")
    vertex_mass = lumped_vertex_mass(positions, faces)
    owned_mass = np.zeros((joint_count,), dtype=np.float64)
    for vertex, owner in enumerate(owners.tolist()):
        owned_mass[int(owner)] += float(vertex_mass[int(vertex)])
    desc = descendants_table(parent_list)
    anc = ancestors_table(parent_list, frozen_root=int(frozen_root))
    bind_world = _fk_worlds(np.zeros((joint_count, 3), dtype=np.float64), trans, bases, parent_list)
    bind_origins = bind_world[:, :3, 3].copy()
    bind_rot = bind_world[:, :3, :3].copy()
    rest_local = np.zeros_like(positions)
    for vertex, owner in enumerate(owners.tolist()):
        rest_local[int(vertex)] = bind_rot[int(owner)].T @ (positions[int(vertex)] - bind_origins[int(owner)])
    total_mass = float(vertex_mass.sum())
    extent = bind_extent_length(positions)
    abs_floor = float(LAMBDA_ABS_SCALE) * float(total_mass) * (float(extent) ** 2)
    composite_mass = np.zeros((joint_count,), dtype=np.float64)
    inertia = np.zeros((joint_count, 3, 3), dtype=np.float64)
    lambda_max = np.zeros((joint_count,), dtype=np.float64)
    inertia_inv = np.zeros((joint_count, 3, 3), dtype=np.float64)
    clamped: list[tuple[int, int, float]] = []
    massless: list[int] = []

    def _dummy_tensor() -> tuple[np.ndarray, float, np.ndarray]:
        dummy = np.eye(3, dtype=np.float64) * max(float(abs_floor), 1.0)
        return dummy, float(np.max(np.linalg.eigvalsh(dummy))), np.linalg.inv(dummy)

    for joint in range(joint_count):
        subtree = (int(joint),) + desc[int(joint)]
        mask = np.isin(owners, np.asarray(subtree, dtype=np.int64))
        composite_mass[joint] = float(vertex_mass[mask].sum())
        if int(joint) == int(frozen_root) or float(composite_mass[joint]) <= 0.0:
            dummy, lam, inverse = _dummy_tensor()
            inertia[joint] = dummy
            lambda_max[joint] = lam
            inertia_inv[joint] = inverse
            if int(joint) != int(frozen_root):
                massless.append(int(joint))
            continue
        offsets_world = positions[mask] - bind_origins[joint]
        offsets_rest = (bind_rot[joint].T @ offsets_world.T).T
        raw = _inertia_about_origin(offsets_rest, vertex_mass[mask])
        raw = 0.5 * (raw + raw.T)
        trial_lambda = float(np.max(np.linalg.eigvalsh(raw)))
        if not math.isfinite(trial_lambda) or trial_lambda < abs_floor:
            dummy, lam, inverse = _dummy_tensor()
            inertia[joint] = dummy
            lambda_max[joint] = lam
            inertia_inv[joint] = inverse
            massless.append(int(joint))
            continue
        regularized, lam, hits = regularize_inertia(
            raw,
            joint_index=int(joint),
            total_mass=total_mass,
            bind_extent=extent,
        )
        inertia[joint] = regularized
        lambda_max[joint] = lam
        inertia_inv[joint] = np.linalg.inv(regularized)
        clamped.extend(hits)
    scales = (
        np.ones((joint_count,), dtype=np.float64)
        if bone_limit_scales is None
        else np.asarray(bone_limit_scales, dtype=np.float64).reshape(joint_count)
    )
    lengths = np.zeros((joint_count,), dtype=np.float64)
    for child, parent in enumerate(parent_list):
        if parent is None:
            continue
        lengths[int(child)] = float(np.linalg.norm(bind_origins[int(child)] - bind_origins[int(parent)]))
    margin = collision_margin_from_bind(positions, float(collision_margin_body_lengths))
    sample_count = min(int(collision_sample_count), int(positions.shape[0]))
    pairs = build_mesh_collision_pairs(
        triangles=faces,
        bind_positions=positions,
        sample_count=max(2, sample_count),
        geodesic_min_hops=int(collision_geodesic_min_hops),
        margin=margin,
    )
    samples = np.asarray(pairs.sample_vertices, dtype=np.int64)
    sample_y = positions[samples, 1]
    lowest_vertex_y = float(np.min(positions[:, 1]))
    ground_y = float(np.min(sample_y))
    dt_sub = float(cfg.dt) / float(cfg.substeps)
    movable = [
        index
        for index in range(joint_count)
        if index != int(frozen_root) and index not in set(massless)
    ]
    if not movable:
        raise RuntimeError("plant has no joints with mesh mass")
    min_mass = float(np.min(composite_mass[np.asarray(movable, dtype=np.int64)]))
    stiffness = (
        float(cfg.collision_stiffness)
        if cfg.collision_stiffness is not None
        else contact_stiffness_for_mass(min_mass, dt_sub=dt_sub, stability=float(cfg.contact_stability))
    )
    omega = math.sqrt(stiffness / min_mass)
    if omega * dt_sub >= float(cfg.contact_stability):
        raise RuntimeError(
            f"contact spring violates semi-implicit bound: sqrt(k/m)*dt_sub={omega * dt_sub} "
            f">= {cfg.contact_stability}"
        )
    searchable = [lambda_max[index] for index in movable]
    if not searchable:
        raise RuntimeError("plant has no movable joints")
    median_lambda = float(np.median(np.asarray(searchable, dtype=np.float64)))
    tau_budget = median_lambda * (math.radians(float(NUDGE_DEG_PER_FRAME)) / float(cfg.dt))
    edges = unique_triangle_edges(faces)
    rest_len = rest_edge_lengths(positions, edges)
    return RagdollPlant(
        node_names=names,
        parents=parent_list,
        frozen_root=int(frozen_root),
        translations=trans,
        base_rotations=bases,
        bind_origins=bind_origins,
        bind_world_rotations=bind_rot,
        bind_positions=positions,
        triangles=faces,
        peak_owner=owners,
        rest_local_offsets=rest_local,
        owned_mass=owned_mass,
        composite_mass=composite_mass,
        inertia_rest=inertia,
        lambda_max=lambda_max,
        inertia_inv_rest=inertia_inv,
        bone_limit_scales=scales,
        bone_lengths=lengths,
        descendants=desc,
        ancestors=anc,
        collision_pairs=np.asarray(pairs.pairs, dtype=np.int64),
        collision_samples=samples,
        collision_margin=float(pairs.margin),
        ground_y=ground_y,
        ground_delta_to_lowest=float(ground_y - lowest_vertex_y),
        contact_stiffness=stiffness,
        clamped_eigenvalues=tuple(clamped),
        total_mass=total_mass,
        bind_extent=extent,
        tau_budget=tau_budget,
        rest_edges=edges,
        rest_edge_len=rest_len,
        massless_joints=tuple(massless),
    )


def topological_joint_order(parents: Sequence[int | None]) -> tuple[int, ...]:
    """Parents before children. Node index order is not hierarchy order."""
    count = len(parents)
    remaining = set(range(count))
    order: list[int] = []
    while remaining:
        ready = [
            index
            for index in remaining
            if parents[index] is None or int(parents[index]) not in remaining
        ]
        if not ready:
            raise RuntimeError("skeleton parent graph is cyclic")
        ready.sort()
        order.extend(int(index) for index in ready)
        remaining.difference_update(ready)
    return tuple(order)


def resolve_frozen_root(names: Sequence[str], parents: Sequence[int | None]) -> int:
    if "Bone_000" in names:
        return int(tuple(names).index("Bone_000"))
    roots = [index for index, parent in enumerate(parents) if parent is None]
    if len(roots) != 1:
        raise RuntimeError(f"expected one hierarchy root, got {roots}")
    return int(roots[0])


def _fk_worlds(
    rotvecs: np.ndarray,
    translations: np.ndarray,
    base_rotations: np.ndarray,
    parents: Sequence[int | None],
) -> np.ndarray:
    joint_count = int(rotvecs.shape[0])
    worlds = np.zeros((joint_count, 4, 4), dtype=np.float64)
    for index in topological_joint_order(parents):
        local = np.eye(4, dtype=np.float64)
        delta = _rotvec_matrix(rotvecs[int(index)])
        local[:3, :3] = base_rotations[int(index)] @ delta
        local[:3, 3] = translations[int(index)]
        parent = parents[int(index)]
        worlds[int(index)] = local if parent is None else worlds[int(parent)] @ local
    return worlds


def forward_kinematics(plant: RagdollPlant, rotvecs: np.ndarray) -> np.ndarray:
    vectors = np.asarray(rotvecs, dtype=np.float64).reshape(plant.joint_count(), 3)
    _require_finite("rotvecs", vectors)
    return _fk_worlds(vectors, plant.translations, plant.base_rotations, plant.parents)


def posed_vertices(plant: RagdollPlant, worlds: np.ndarray) -> np.ndarray:
    points = np.zeros_like(plant.bind_positions)
    origins = worlds[:, :3, 3]
    rotations = worlds[:, :3, :3]
    for vertex, owner in enumerate(plant.peak_owner.tolist()):
        points[int(vertex)] = origins[int(owner)] + rotations[int(owner)] @ plant.rest_local_offsets[int(vertex)]
    return points


def strain_max_ratio(plant: RagdollPlant, vertices: np.ndarray) -> float:
    posed = posed_edge_lengths(vertices[None, ...], plant.rest_edges)[0]
    rest = plant.rest_edge_len
    ratio = posed / np.maximum(rest, 1e-12)
    return float(np.max(np.abs(ratio - 1.0)))


def _add_force(
    tau_world: np.ndarray,
    plant: RagdollPlant,
    *,
    owner: int,
    point: np.ndarray,
    force: np.ndarray,
    origins: np.ndarray,
) -> None:
    if int(owner) == int(plant.frozen_root):
        chain = ()
    else:
        chain = plant.ancestors[int(owner)]
    for joint in chain:
        lever = np.asarray(point, dtype=np.float64).reshape(3) - origins[int(joint)]
        tau_world[int(joint)] += np.cross(lever, np.asarray(force, dtype=np.float64).reshape(3))


def _plant_alpha(
    plant: RagdollPlant,
    rotvecs: np.ndarray,
    omega: np.ndarray,
    *,
    config: RagdollPlantConfig,
) -> np.ndarray:
    worlds = forward_kinematics(plant, rotvecs)
    origins = worlds[:, :3, 3]
    rotations = worlds[:, :3, :3]
    vertices = posed_vertices(plant, worlds)
    tau_world = np.zeros((plant.joint_count(), 3), dtype=np.float64)
    gravity = -float(config.gravity) * np.asarray(config.world_up, dtype=np.float64)
    for joint in range(plant.joint_count()):
        if int(joint) == int(plant.frozen_root):
            continue
        mass = float(plant.owned_mass[int(joint)])
        if mass <= 0.0:
            continue
        owned = plant.peak_owner == int(joint)
        if not bool(np.any(owned)):
            continue
        com = vertices[owned].mean(axis=0)
        _add_force(
            tau_world,
            plant,
            owner=int(joint),
            point=com,
            force=mass * gravity,
            origins=origins,
        )
    pairs = plant.collision_pairs
    if int(pairs.shape[0]) > 0:
        left = vertices[pairs[:, 0]]
        right = vertices[pairs[:, 1]]
        delta = left - right
        distance = np.linalg.norm(delta, axis=1)
        margin = float(plant.collision_margin)
        for index in range(int(pairs.shape[0])):
            dist = float(distance[index])
            if dist >= margin or dist <= 1e-12:
                continue
            axis = delta[index] / dist
            depth = margin - dist
            force = float(plant.contact_stiffness) * depth * axis
            _add_force(
                tau_world,
                plant,
                owner=int(plant.peak_owner[int(pairs[index, 0])]),
                point=left[index],
                force=force,
                origins=origins,
            )
            _add_force(
                tau_world,
                plant,
                owner=int(plant.peak_owner[int(pairs[index, 1])]),
                point=right[index],
                force=-force,
                origins=origins,
            )
    up = np.asarray(config.world_up, dtype=np.float64)
    up = up / float(np.linalg.norm(up))
    samples = plant.collision_samples
    for sample in samples.tolist():
        point = vertices[int(sample)]
        penetration = float(plant.ground_y - point[1])
        if penetration <= 0.0:
            continue
        owner = int(plant.peak_owner[int(sample)])
        normal_force = float(plant.contact_stiffness) * penetration * up
        _add_force(tau_world, plant, owner=owner, point=point, force=normal_force, origins=origins)
        worlds_omega = rotations[owner] @ omega[owner]
        vel = np.cross(worlds_omega, point - origins[owner])
        tangent = vel - up * float(np.dot(vel, up))
        speed = float(np.linalg.norm(tangent))
        if speed > 1e-8:
            friction = -tangent / speed * float(config.mu) * float(np.linalg.norm(normal_force))
            _add_force(tau_world, plant, owner=owner, point=point, force=friction, origins=origins)
    alpha = np.zeros((plant.joint_count(), 3), dtype=np.float64)
    for joint in range(plant.joint_count()):
        if int(joint) == int(plant.frozen_root):
            continue
        parent = plant.parents[int(joint)]
        r_joint = rotations[int(joint)]
        r_bind = plant.bind_world_rotations[int(joint)]
        r_delta = r_bind.T @ r_joint
        tau_body = r_joint.T @ tau_world[int(joint)]
        inertia_body = r_delta @ plant.inertia_rest[int(joint)] @ r_delta.T
        try:
            alpha_body = np.linalg.solve(inertia_body, tau_body)
        except np.linalg.LinAlgError as exc:
            raise RuntimeError(f"joint {joint} inertia is singular during integrate") from exc
        r_parent = np.eye(3, dtype=np.float64) if parent is None else rotations[int(parent)]
        alpha[int(joint)] = r_parent.T @ r_joint @ alpha_body
    return alpha


def clamp_rotvecs(plant: RagdollPlant, rotvecs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    vectors = np.asarray(rotvecs, dtype=np.float64).reshape(plant.joint_count(), 3).copy()
    limits = plant.clamp_limit_rad()
    counts = np.zeros((plant.joint_count(),), dtype=np.int64)
    for joint in range(plant.joint_count()):
        if int(joint) == int(plant.frozen_root):
            vectors[int(joint)] = 0.0
            continue
        mag = float(np.linalg.norm(vectors[int(joint)]))
        limit = float(limits[int(joint)])
        if mag > limit:
            vectors[int(joint)] *= limit / mag
            counts[int(joint)] += 1
    return vectors, counts


def integrate_substep(
    plant: RagdollPlant,
    state: RagdollState,
    *,
    config: RagdollPlantConfig,
) -> RagdollState:
    cfg = config
    dt_sub = float(cfg.dt) / float(cfg.substeps)
    alpha_plant = _plant_alpha(plant, state.rotvecs, state.omega, config=cfg)
    alpha = alpha_plant + np.asarray(state.alpha_control, dtype=np.float64)
    omega = np.asarray(state.omega, dtype=np.float64) + alpha * dt_sub
    omega *= 1.0 - float(cfg.zeta)
    omega[int(plant.frozen_root)] = 0.0
    rotvecs = np.asarray(state.rotvecs, dtype=np.float64).copy()
    for joint in range(plant.joint_count()):
        if int(joint) == int(plant.frozen_root):
            rotvecs[int(joint)] = 0.0
            continue
        rotvecs[int(joint)] = compose_rotvec(rotvecs[int(joint)], omega[int(joint)] * dt_sub)
    rotvecs, extra = clamp_rotvecs(plant, rotvecs)
    counts = np.asarray(state.clamp_counts, dtype=np.int64) + extra
    omega[int(plant.frozen_root)] = 0.0
    rotvecs[int(plant.frozen_root)] = 0.0
    return RagdollState(
        rotvecs=rotvecs,
        omega=omega,
        alpha_control=np.asarray(state.alpha_control, dtype=np.float64).copy(),
        clamp_counts=counts,
    )


def integrate_frame(
    plant: RagdollPlant,
    state: RagdollState,
    *,
    config: RagdollPlantConfig | None = None,
) -> RagdollState:
    cfg = config or RagdollPlantConfig()
    cfg.validate()
    current = state
    for _ in range(int(cfg.substeps)):
        current = integrate_substep(plant, current, config=cfg)
    return current


def geodesic_deg(left: np.ndarray, right: np.ndarray) -> float:
    return math.degrees(float(geodesic_radians(left, right)))


def suffix_residual(
    plant: RagdollPlant,
    rotvecs: np.ndarray,
    omega: np.ndarray,
    idle_rotvecs: np.ndarray,
) -> dict[str, float]:
    max_deg = 0.0
    for joint in range(plant.joint_count()):
        if int(joint) == int(plant.frozen_root):
            continue
        max_deg = max(max_deg, geodesic_deg(rotvecs[int(joint)], idle_rotvecs[int(joint)]))
    omega_deg = math.degrees(float(np.max(np.linalg.norm(omega, axis=-1))))
    return {
        "thetaDeg": float(max_deg),
        "omegaDegS": float(omega_deg),
        "ok": bool(max_deg <= float(EPSILON_THETA_DEG) and omega_deg <= float(EPSILON_OMEGA_DEG_S)),
    }


def serialize_pose_degrees(
    plant: RagdollPlant,
    rotvecs: np.ndarray,
    *,
    root_translation: Sequence[float] = (0.0, 0.0, 0.0),
    root_rotation_deg: Sequence[float] = (0.0, 0.0, 0.0),
) -> dict[str, Any]:
    pose: dict[str, Any] = {}
    vectors = np.asarray(rotvecs, dtype=np.float64).reshape(plant.joint_count(), 3)
    degrees = np.degrees(vectors)
    for index, name in enumerate(plant.node_names):
        if int(index) == int(plant.frozen_root):
            continue
        values = degrees[int(index)]
        if float(np.max(np.abs(values))) <= 1e-12:
            continue
        pose[str(name)] = {
            "x": float(values[0]),
            "y": float(values[1]),
            "z": float(values[2]),
        }
    root = np.asarray(root_translation, dtype=np.float64).reshape(3)
    rotation = np.asarray(root_rotation_deg, dtype=np.float64).reshape(3)
    pose[MOTION_ROOT_KEY] = {
        "forward": float(root[0]),
        "lateral": float(root[1]),
        "vertical": float(root[2]),
    }
    pose[MOTION_ROOT_ROTATION_KEY] = {
        "camera_forward": float(rotation[0]),
        "camera_right": float(rotation[1]),
        "camera_up": float(rotation[2]),
    }
    return pose


def deserialize_pose_radians(plant: RagdollPlant, pose: Mapping[str, Any]) -> np.ndarray:
    vectors = np.zeros((plant.joint_count(), 3), dtype=np.float64)
    for index, name in enumerate(plant.node_names):
        entry = pose.get(str(name))
        if not isinstance(entry, Mapping):
            continue
        vectors[int(index)] = np.radians(
            np.asarray((entry.get("x", 0.0), entry.get("y", 0.0), entry.get("z", 0.0)), dtype=np.float64)
        )
    vectors[int(plant.frozen_root)] = 0.0
    return vectors


def bounded_round_trip_radians(
    rotvecs: np.ndarray,
    *,
    joint_limit_deg: float,
    bone_limit_scales: np.ndarray,
) -> np.ndarray:
    """CPU stand-in for ``_initial_pose_tensors`` + ``_bounded_bone_vectors``."""
    physical = np.asarray(rotvecs, dtype=np.float64)
    limit = math.radians(float(joint_limit_deg)) * np.asarray(bone_limit_scales, dtype=np.float64).reshape(-1, 1)
    ratio = np.clip(physical / np.maximum(limit, 1e-12), -0.999, 0.999)
    raw = np.arctanh(ratio)
    return np.tanh(raw) * limit


def make_chain_fixture(*, tilt_deg: float = 20.0) -> tuple[RagdollPlant, RagdollState]:
    """Three-bone chain for CPU tests: frozen root, shoulder, elbow."""
    names = ("Root", "Shoulder", "Elbow")
    parents: tuple[int | None, ...] = (None, 0, 1)
    translations = np.asarray(
        ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 1.0, 0.0)),
        dtype=np.float64,
    )
    bases = np.stack([np.eye(3, dtype=np.float64)] * 3)
    positions = np.asarray(
        (
            (-0.2, 0.0, -0.2),
            (0.2, 0.0, -0.2),
            (0.2, 0.0, 0.2),
            (-0.2, 0.0, 0.2),
            (-0.15, 1.0, -0.15),
            (0.15, 1.0, -0.15),
            (0.15, 1.0, 0.15),
            (-0.15, 1.0, 0.15),
            (-0.1, 2.1, -0.1),
            (0.2, 2.1, -0.1),
            (0.2, 2.1, 0.1),
            (-0.1, 2.1, 0.1),
        ),
        dtype=np.float64,
    )
    triangles = np.asarray(
        (
            (0, 1, 2),
            (0, 2, 3),
            (4, 5, 6),
            (4, 6, 7),
            (8, 9, 10),
            (8, 10, 11),
        ),
        dtype=np.int64,
    )
    joints = np.asarray(
        (
            (0, 0),
            (0, 0),
            (0, 0),
            (0, 0),
            (1, 1),
            (1, 1),
            (1, 1),
            (1, 1),
            (2, 2),
            (2, 2),
            (2, 2),
            (2, 2),
        ),
        dtype=np.int64,
    )
    weights = np.ones((12, 2), dtype=np.float64)
    weights[:, 1] = 0.0
    plant = build_plant(
        node_names=names,
        parents=parents,
        translations=translations,
        base_rotations=bases,
        bind_positions=positions,
        triangles=triangles,
        joints=joints,
        weights=weights,
        frozen_root=0,
        collision_sample_count=8,
        collision_geodesic_min_hops=1,
    )
    rotvecs = np.zeros((3, 3), dtype=np.float64)
    rotvecs[2, 0] = math.radians(float(tilt_deg))
    state = RagdollState(
        rotvecs=rotvecs,
        omega=np.zeros((3, 3), dtype=np.float64),
        alpha_control=np.zeros((3, 3), dtype=np.float64),
        clamp_counts=np.zeros((3,), dtype=np.int64),
    )
    return plant, state


def plant_mass_report(plant: RagdollPlant) -> dict[str, Any]:
    return {
        "solver": SOLVER_ID,
        "jointCount": plant.joint_count(),
        "totalMass": float(plant.total_mass),
        "bindExtent": float(plant.bind_extent),
        "tauBudget": float(plant.tau_budget),
        "groundY": float(plant.ground_y),
        "groundDeltaToLowest": float(plant.ground_delta_to_lowest),
        "contactStiffness": float(plant.contact_stiffness),
        "clampedEigenvalues": [
            {"joint": int(joint), "axis": int(axis), "lambda": float(value)}
            for joint, axis, value in plant.clamped_eigenvalues
        ],
        "lambdaMax": [float(value) for value in plant.lambda_max.tolist()],
        "ownedMass": [float(value) for value in plant.owned_mass.tolist()],
        "compositeMass": [float(value) for value in plant.composite_mass.tolist()],
        "masslessJoints": [
            {"index": int(index), "name": str(plant.node_names[int(index)])}
            for index in plant.massless_joints
        ],
        "proof": "generated-artifact; not pose-pipeline compliant; experiment lane only",
    }


def plant_from_experiment(experiment: Any, *, config: RagdollPlantConfig | None = None) -> RagdollPlant:
    """Extract a CPU plant from a loaded ``GpuCascadeExperiment``."""
    import torch

    node_count = len(experiment.asset.nodes)
    zeros = torch.zeros((1, node_count, 3), dtype=torch.float32, device=experiment.device)
    worlds = experiment._forward_kinematics(zeros)
    positions_parts: list[np.ndarray] = []
    triangle_parts: list[np.ndarray] = []
    joint_parts: list[np.ndarray] = []
    weight_parts: list[np.ndarray] = []
    cursor = 0
    for primitive in experiment.primitives:
        if (
            primitive.normalized_weights is None
            or primitive.joints is None
            or primitive.skin_joints is None
        ):
            raise RuntimeError("ragdoll plant requires skinned primitives")
        verts = experiment._skinned_vertices(worlds, primitive)[0].detach().cpu().numpy()
        faces = primitive.indices.detach().cpu().numpy().astype(np.int64).reshape(-1, 3) + cursor
        weights = primitive.normalized_weights.detach().cpu().numpy()
        slots = primitive.joints.detach().cpu().numpy().astype(np.int64)
        skin_to_node = primitive.skin_joints.detach().cpu().numpy().reshape(-1)
        mapped = np.where(slots >= 0, skin_to_node[np.clip(slots, 0, int(skin_to_node.shape[0]) - 1)], -1)
        positions_parts.append(np.asarray(verts, dtype=np.float64))
        triangle_parts.append(faces)
        joint_parts.append(mapped.astype(np.int64))
        weight_parts.append(np.asarray(weights, dtype=np.float64))
        cursor += int(verts.shape[0])
    positions = np.concatenate(positions_parts, axis=0)
    triangles = np.concatenate(triangle_parts, axis=0)
    joints = np.concatenate(joint_parts, axis=0)
    weights = np.concatenate(weight_parts, axis=0)
    parents = tuple(None if parent is None else int(parent) for parent in experiment.parents)
    translations = experiment.translations.detach().cpu().numpy().astype(np.float64)
    bases = experiment.base_rotations.detach().cpu().numpy().astype(np.float64)
    scales = experiment.bone_limit_scales.detach().cpu().numpy().astype(np.float64)
    return build_plant(
        node_names=tuple(str(name) for name in experiment.node_names),
        parents=parents,
        translations=translations,
        base_rotations=bases,
        bind_positions=positions,
        triangles=triangles,
        joints=joints,
        weights=weights,
        frozen_root=resolve_frozen_root(tuple(str(name) for name in experiment.node_names), parents),
        bone_limit_scales=scales,
        collision_sample_count=int(
            getattr(experiment.config, "collision_sample_count", COLLISION_SAMPLE_COUNT)
        ),
        collision_geodesic_min_hops=int(
            getattr(experiment.config, "collision_geodesic_min_hops", COLLISION_GEODESIC_MIN_HOPS)
        ),
        collision_margin_body_lengths=float(
            getattr(
                experiment.config,
                "collision_margin_body_lengths",
                COLLISION_MARGIN_BODY_LENGTHS,
            )
        ),
        config=config,
    )
