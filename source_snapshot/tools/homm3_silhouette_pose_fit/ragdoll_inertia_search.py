"""Fused-pose inertial consolidation for the ragdoll experiment.

CPU plant post-pass after fused-push. Reverse-order GPU search is not the
delivery path. Not pose-pipeline delivery.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from cascade_physics_smooth import compose_rotvec, relative_rotvec, slerp_rotvec
from ragdoll_inertia_plant import (
    CLAMP_FRAC,
    COLLISION_FRAME_SLACK,
    COLLISION_MEAN_SLACK,
    DT,
    EPSILON_OMEGA_DEG_S,
    EPSILON_THETA_DEG,
    FRAME_FLOOR_SLACK,
    FUSED_INERTIA_MIX,
    JOINT_DIAGONAL_AXES,
    JOINT_LIMIT_DEG,
    KEEP_IMPROVE,
    MAX_FORWARD_SWEEPS,
    MAX_REVERSE_SWEEPS,
    MOTION_KEEP_FRAC,
    RUNGS,
    SCORE_COLLISION_WEIGHT,
    SKIP_SEARCH_BONES,
    STRAIN_SLACK,
    TOP_K_CELLS,
    WALL_CLOCK_CAP_S,
    WALL_CLOCK_PACK_SIZE,
    RagdollPlant,
    RagdollPlantConfig,
    RagdollState,
    clamp_rotvecs,
    deserialize_pose_radians,
    forward_kinematics,
    geodesic_deg,
    integrate_frame,
    plant_mass_report,
    posed_vertices,
    serialize_pose_degrees,
    strain_max_ratio,
    suffix_residual,
)
from roc_gpu_cascade_experiment import (
    MOTION_ROOT_KEY,
    MOTION_ROOT_ROTATION_KEY,
    joint_score_hyps_per_launch,
    joint_search_directions,
)

REQUIRED_SCORE_CONFIG = {
    "score_mode": "geometry",
    "depth_weight": 0.25,
    "silhouette_weight": 0.2,
    "chroma_weight": 0.2,
    "chroma_scale": 2,
    "collision_enabled": True,
    "collision_weight": 0.35,
    "collision_sample_count": 256,
    "collision_geodesic_min_hops": 8,
    "collision_margin_body_lengths": 0.04,
    "temporal_scoring_mode": "velocity_acceleration_only",
    "velocity_weight": 0.04,
    "acceleration_weight": 0.025,
    "root_velocity_weight": 0.02,
    "root_acceleration_weight": 0.01,
    "root_rotation_velocity_weight": 0.02,
    "root_rotation_acceleration_weight": 0.01,
    "joint_limit_deg": 150.0,
    "robust_scale_deg": 32.0,
    "loop_enabled": False,
    "temporal_loop_wrap_enabled": False,
}

PRESMOOTH_SCORE = 0.6473305225372314
PRESMOOTH_TOLERANCE = 1e-3
IDLE_COLLAPSE_DROP = 0.15
IDLE_REST_MAX_DEG = 60.0
SEARCH_IDLE_CLIP = "idle"


@dataclass(frozen=True)
class ClipBands:
    frame_count: int
    prefix: int
    suffix: int
    lock_suffix: bool
    free_frames: tuple[int, ...]

    def last_free(self) -> int:
        if not self.free_frames:
            raise RuntimeError("clip has no free frames")
        return int(self.free_frames[-1])


def clip_bands(
    *,
    frame_count: int,
    prefix: int,
    suffix: int,
    lock_suffix: bool,
) -> ClipBands:
    total = int(frame_count)
    pre = max(0, int(prefix))
    suf = max(0, int(suffix)) if bool(lock_suffix) else 0
    if bool(lock_suffix) and pre + suf >= total:
        raise ValueError("idle prefix/suffix leave no free frames")
    if bool(lock_suffix):
        free = tuple(range(pre, total - suf))
    else:
        free = tuple(range(pre, total))
    if not free:
        raise ValueError("clip has no free frames to search")
    return ClipBands(
        frame_count=total,
        prefix=pre,
        suffix=suf,
        lock_suffix=bool(lock_suffix),
        free_frames=free,
    )


@dataclass
class ClipTrajectory:
    rotvecs: np.ndarray
    omega: np.ndarray
    alpha_control: np.ndarray
    clamp_counts: np.ndarray
    idle_rotvecs: np.ndarray
    prefix_poses: np.ndarray
    suffix_poses: np.ndarray | None


def copy_trajectory(trajectory: ClipTrajectory) -> ClipTrajectory:
    return ClipTrajectory(
        rotvecs=np.asarray(trajectory.rotvecs, dtype=np.float64).copy(),
        omega=np.asarray(trajectory.omega, dtype=np.float64).copy(),
        alpha_control=np.asarray(trajectory.alpha_control, dtype=np.float64).copy(),
        clamp_counts=np.asarray(trajectory.clamp_counts, dtype=np.int64).copy(),
        idle_rotvecs=np.asarray(trajectory.idle_rotvecs, dtype=np.float64).copy(),
        prefix_poses=np.asarray(trajectory.prefix_poses, dtype=np.float64).copy(),
        suffix_poses=(
            None
            if trajectory.suffix_poses is None
            else np.asarray(trajectory.suffix_poses, dtype=np.float64).copy()
        ),
    )


def frame_step_rms_deg(rotvecs: np.ndarray, frames: Sequence[int]) -> float:
    order = [int(frame) for frame in frames]
    if len(order) < 2:
        return 0.0
    steps: list[float] = []
    poses = np.asarray(rotvecs, dtype=np.float64)
    for prev, current in zip(order[:-1], order[1:]):
        for joint in range(int(poses.shape[1])):
            steps.append(geodesic_deg(poses[int(prev), int(joint)], poses[int(current), int(joint)]))
    return float(np.sqrt(np.mean(np.square(steps))))


def pose_from_rest_rms_deg(rotvecs: np.ndarray, frames: Sequence[int], rest: np.ndarray) -> float:
    order = [int(frame) for frame in frames]
    if not order:
        return 0.0
    poses = np.asarray(rotvecs, dtype=np.float64)
    origin = np.asarray(rest, dtype=np.float64)
    mags: list[float] = []
    for frame in order:
        for joint in range(int(poses.shape[1])):
            mags.append(geodesic_deg(poses[int(frame), int(joint)], origin[int(joint)]))
    return float(np.sqrt(np.mean(np.square(mags))))


def motion_keep_report(
    fused: np.ndarray,
    consolidated: np.ndarray,
    frames: Sequence[int],
    rest: np.ndarray,
) -> dict[str, Any]:
    before = pose_from_rest_rms_deg(fused, frames, rest)
    after = pose_from_rest_rms_deg(consolidated, frames, rest)
    ok = after + 1e-12 >= float(MOTION_KEEP_FRAC) * before
    return {
        "ok": bool(ok),
        "fusedPoseRmsDeg": float(before),
        "consolidatedPoseRmsDeg": float(after),
        "keepFrac": float(after / before) if before > 1e-12 else 1.0,
        "keepFracLimit": float(MOTION_KEEP_FRAC),
        "reason": "" if ok else "motion_damped",
    }


def consolidate_fused_clip(
    plant: RagdollPlant,
    trajectory: ClipTrajectory,
    bands: ClipBands,
    *,
    config: RagdollPlantConfig | None = None,
    inertia_mix: float | None = None,
) -> tuple[ClipTrajectory, dict[str, Any]]:
    """Keep fused poses and add a fading leftover from earlier joint changes.

    Leftover is coasted through the plant with gravity off. The fused pose is
    not replaced, so a walk is not flattened.
    """
    cfg = config or RagdollPlantConfig()
    cfg.validate()
    mix = float(FUSED_INERTIA_MIX if inertia_mix is None else inertia_mix)
    if not (0.0 <= mix < 1.0):
        raise ValueError("inertia_mix must be in [0, 1)")
    fused = np.asarray(trajectory.rotvecs, dtype=np.float64)
    out = fused.copy()
    omega = np.zeros_like(fused)
    clamps = np.zeros((int(bands.frame_count), plant.joint_count()), dtype=np.int64)
    root = int(plant.frozen_root)
    free = list(bands.free_frames)
    if not free:
        raise RuntimeError("clip has no free frames")
    leftover_pose = np.zeros((plant.joint_count(), 3), dtype=np.float64)
    leftover_omega = np.zeros((plant.joint_count(), 3), dtype=np.float64)
    zeros = np.zeros(3, dtype=np.float64)
    prev_fused = fused[int(free[0])].copy()
    prev_out = fused[int(free[0])].copy()
    started = False
    for frame in free:
        faded = leftover_pose
        extra = np.zeros((plant.joint_count(),), dtype=np.int64)
        if started:
            coasted = integrate_frame(
                plant,
                RagdollState(
                    rotvecs=leftover_pose,
                    omega=leftover_omega,
                    alpha_control=np.zeros_like(leftover_pose),
                    clamp_counts=np.zeros((plant.joint_count(),), dtype=np.int64),
                ),
                config=cfg,
            )
            faded = np.zeros_like(leftover_pose)
            for joint in range(plant.joint_count()):
                if int(joint) == root:
                    continue
                faded[int(joint)] = slerp_rotvec(zeros, coasted.rotvecs[int(joint)], mix)
            leftover_omega = coasted.omega * mix
            leftover_omega[root] = 0.0
        blended = np.zeros_like(fused[int(frame)])
        for joint in range(plant.joint_count()):
            if int(joint) == root:
                blended[int(joint)] = 0.0
                continue
            blended[int(joint)] = compose_rotvec(fused[int(frame), int(joint)], faded[int(joint)])
        blended, extra = clamp_rotvecs(plant, blended)
        blended[root] = 0.0
        out[int(frame)] = blended
        if started:
            for joint in range(plant.joint_count()):
                omega[int(frame), int(joint)] = relative_rotvec(
                    blended[int(joint)], prev_out[int(joint)]
                ) / float(DT)
            omega[int(frame), root] = 0.0
        injected = np.zeros_like(leftover_pose)
        for joint in range(plant.joint_count()):
            if int(joint) == root:
                continue
            delta = relative_rotvec(fused[int(frame), int(joint)], prev_fused[int(joint)])
            injected[int(joint)] = compose_rotvec(faded[int(joint)], delta)
        leftover_pose = injected
        leftover_pose[root] = 0.0
        clamps[int(frame)] = extra
        prev_fused = fused[int(frame)].copy()
        prev_out = blended
        started = True
    if int(bands.prefix) > 0:
        _copy_band(out, fused, range(0, int(bands.prefix)))
        omega[: int(bands.prefix)] = 0.0
        clamps[: int(bands.prefix)] = 0
    if bool(bands.lock_suffix) and int(bands.suffix) > 0:
        start_suffix = int(bands.frame_count) - int(bands.suffix)
        _copy_band(out, fused, range(start_suffix, int(bands.frame_count)))
        omega[start_suffix:] = 0.0
        clamps[start_suffix:] = 0
    keep = motion_keep_report(fused, out, free, rest=trajectory.idle_rotvecs)
    if not bool(keep["ok"]):
        raise RuntimeError(
            "fused inertial post-pass damped motion: "
            f"poseRms {keep['consolidatedPoseRmsDeg']:.4f} deg "
            f"< {keep['keepFracLimit']:.2f} * fused {keep['fusedPoseRmsDeg']:.4f} deg"
        )
    picked = ClipTrajectory(
        rotvecs=out,
        omega=omega,
        alpha_control=np.zeros_like(out),
        clamp_counts=clamps,
        idle_rotvecs=trajectory.idle_rotvecs.copy(),
        prefix_poses=trajectory.prefix_poses.copy(),
        suffix_poses=None if trajectory.suffix_poses is None else trajectory.suffix_poses.copy(),
    )
    report = {
        "mode": "fused_post_pass",
        "inertiaMix": mix,
        "gravity": float(cfg.gravity),
        **keep,
    }
    return picked, report


def _copy_band(dest: np.ndarray, source: np.ndarray, frames: range) -> None:
    for index in frames:
        dest[int(index)] = source[int(index)]


def integrate_clip(
    plant: RagdollPlant,
    trajectory: ClipTrajectory,
    bands: ClipBands,
    *,
    config: RagdollPlantConfig | None = None,
) -> ClipTrajectory:
    cfg = config or RagdollPlantConfig()
    frames = int(bands.frame_count)
    joints = plant.joint_count()
    rotvecs = np.zeros((frames, joints, 3), dtype=np.float64)
    omega = np.zeros((frames, joints, 3), dtype=np.float64)
    clamps = np.zeros((frames, joints), dtype=np.int64)
    if int(bands.prefix) > 0:
        _copy_band(rotvecs, trajectory.prefix_poses, range(0, int(bands.prefix)))
        start_pose = trajectory.prefix_poses[int(bands.prefix) - 1].copy()
        next_frames = bands.free_frames
        state = RagdollState(
            rotvecs=start_pose,
            omega=np.zeros((joints, 3), dtype=np.float64),
            alpha_control=np.zeros((joints, 3), dtype=np.float64),
            clamp_counts=np.zeros((joints,), dtype=np.int64),
        )
    else:
        start_pose = trajectory.idle_rotvecs.copy()
        state = RagdollState(
            rotvecs=start_pose,
            omega=np.zeros((joints, 3), dtype=np.float64),
            alpha_control=trajectory.alpha_control[0].copy(),
            clamp_counts=np.zeros((joints,), dtype=np.int64),
        )
        state = integrate_frame(plant, state, config=cfg)
        rotvecs[0] = state.rotvecs
        omega[0] = state.omega
        clamps[0] = state.clamp_counts
        state.alpha_control = np.zeros((joints, 3), dtype=np.float64)
        next_frames = bands.free_frames[1:]
    for frame in next_frames:
        state = RagdollState(
            rotvecs=state.rotvecs.copy(),
            omega=state.omega.copy(),
            alpha_control=trajectory.alpha_control[int(frame)].copy(),
            clamp_counts=np.zeros((joints,), dtype=np.int64),
        )
        state = integrate_frame(plant, state, config=cfg)
        rotvecs[int(frame)] = state.rotvecs
        omega[int(frame)] = state.omega
        clamps[int(frame)] = state.clamp_counts
        state.alpha_control = np.zeros((joints, 3), dtype=np.float64)
    if bool(bands.lock_suffix) and int(bands.suffix) > 0:
        start_suffix = frames - int(bands.suffix)
        if trajectory.suffix_poses is None:
            raise RuntimeError("suffix lock requires suffix poses")
        _copy_band(rotvecs, trajectory.suffix_poses, range(start_suffix, frames))
        omega[start_suffix:] = 0.0
        clamps[start_suffix:] = 0
    return ClipTrajectory(
        rotvecs=rotvecs,
        omega=omega,
        alpha_control=np.asarray(trajectory.alpha_control, dtype=np.float64).copy(),
        clamp_counts=clamps,
        idle_rotvecs=trajectory.idle_rotvecs.copy(),
        prefix_poses=trajectory.prefix_poses.copy(),
        suffix_poses=None if trajectory.suffix_poses is None else trajectory.suffix_poses.copy(),
    )


def boundary_report(plant: RagdollPlant, trajectory: ClipTrajectory, bands: ClipBands) -> dict[str, Any]:
    if bool(bands.lock_suffix):
        last = trajectory.rotvecs[int(bands.last_free())]
        last_omega = trajectory.omega[int(bands.last_free())]
        report = suffix_residual(plant, last, last_omega, trajectory.idle_rotvecs)
        report["mode"] = "suffix"
        return report
    report = suffix_residual(
        plant,
        trajectory.rotvecs[-1],
        trajectory.omega[-1],
        trajectory.rotvecs[0],
    )
    report["mode"] = "loop"
    return report


def strain_of_clip(plant: RagdollPlant, trajectory: ClipTrajectory) -> float:
    worst = 0.0
    for frame in range(int(trajectory.rotvecs.shape[0])):
        worlds = forward_kinematics(plant, trajectory.rotvecs[int(frame)])
        verts = posed_vertices(plant, worlds)
        worst = max(worst, strain_max_ratio(plant, verts))
    return float(worst)


@dataclass
class ScoreBreakdown:
    clip_objective: float
    score_mean: float
    image_mean: np.ndarray
    collision: np.ndarray
    temporal: float


KeepDecision = tuple[bool, str]


def keep_probe(
    *,
    current: ScoreBreakdown,
    candidate: ScoreBreakdown,
    trajectory: ClipTrajectory,
    bands: ClipBands,
    plant: RagdollPlant,
    prefix_ok: bool,
    suffix_ok: bool,
) -> KeepDecision:
    if not bool(prefix_ok):
        return False, "prefix_changed"
    if not bool(suffix_ok):
        return False, "suffix_changed"
    residual = boundary_report(plant, trajectory, bands)
    if not bool(residual["ok"]):
        return False, "idle_end"
    if int(np.sum(trajectory.clamp_counts)) > 0:
        return False, "clamp"
    if float(candidate.clip_objective) < float(current.clip_objective) + float(KEEP_IMPROVE):
        return False, "objective"
    delta_image = np.asarray(candidate.image_mean, dtype=np.float64) - np.asarray(
        current.image_mean, dtype=np.float64
    )
    if float(np.min(delta_image)) < -float(FRAME_FLOOR_SLACK):
        return False, "frame_floor"
    if float(np.mean(candidate.collision)) > float(np.mean(current.collision)) + float(COLLISION_MEAN_SLACK):
        return False, "collision_mean"
    if float(np.max(candidate.collision)) > float(np.max(current.collision)) + float(COLLISION_FRAME_SLACK):
        return False, "collision_frame"
    if strain_of_clip(plant, trajectory) > float(STRAIN_SLACK):
        return False, "strain"
    return True, "keep"


def prefix_unchanged(trajectory: ClipTrajectory, bands: ClipBands) -> bool:
    if int(bands.prefix) <= 0:
        return True
    return bool(np.allclose(trajectory.rotvecs[: int(bands.prefix)], trajectory.prefix_poses[: int(bands.prefix)]))


def suffix_unchanged(trajectory: ClipTrajectory, bands: ClipBands) -> bool:
    if not bool(bands.lock_suffix) or int(bands.suffix) <= 0:
        return True
    start = int(bands.frame_count) - int(bands.suffix)
    if trajectory.suffix_poses is None:
        return False
    return bool(np.allclose(trajectory.rotvecs[start:], trajectory.suffix_poses[start:]))


def searchable_joints(plant: RagdollPlant, search_indices: Sequence[int] | None = None) -> tuple[int, ...]:
    if search_indices is None:
        indices = range(plant.joint_count())
    else:
        indices = search_indices
    allowed: list[int] = []
    for index in indices:
        joint = int(index)
        if joint == int(plant.frozen_root):
            continue
        if str(plant.node_names[joint]) in SKIP_SEARCH_BONES:
            continue
        if joint in set(plant.massless_joints):
            continue
        allowed.append(joint)
    if not allowed:
        raise RuntimeError("no searchable joints after Bone_000 exclusion")
    return tuple(allowed)


def nudge_delta(plant: RagdollPlant, joint: int, direction: Sequence[float], rung: float) -> np.ndarray:
    axis = np.asarray(direction, dtype=np.float64).reshape(3)
    norm = float(np.linalg.norm(axis))
    if norm <= 1e-12:
        raise ValueError("nudge direction is zero")
    axis = axis / norm
    scale = float(rung) * float(plant.tau_budget) / float(plant.lambda_max[int(joint)])
    return axis * scale


def apply_nudge(
    alpha_control: np.ndarray,
    *,
    frame: int,
    joint: int,
    direction: Sequence[float],
    rung: float,
    plant: RagdollPlant,
) -> np.ndarray:
    out = np.asarray(alpha_control, dtype=np.float64).copy()
    out[int(frame), int(joint)] += nudge_delta(plant, int(joint), direction, float(rung))
    return out


ScoreFn = Callable[[ClipTrajectory], ScoreBreakdown]
ScoreManyFn = Callable[[Sequence[ClipTrajectory]], list[ScoreBreakdown]]
RankFn = Callable[[ClipTrajectory, bool], tuple[tuple[int, int], ...]]


def rank_cells_from_grad(
    grad: np.ndarray,
    *,
    plant: RagdollPlant,
    joints: Sequence[int],
    free_frames: Sequence[int],
    top_k: int = TOP_K_CELLS,
    reverse_order: bool = False,
) -> tuple[tuple[int, int], ...]:
    per_cell: list[tuple[float, int, int]] = []
    for joint in joints:
        length = max(float(plant.bone_lengths[int(joint)]), 1e-12)
        for frame in free_frames:
            mag = float(np.linalg.norm(grad[int(frame), int(joint)]))
            per_cell.append((mag / length, int(frame), int(joint)))
    per_cell.sort(key=lambda item: (-item[0], -item[1] if reverse_order else item[1], item[2]))
    picked: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for _score, frame, joint in per_cell:
        key = (int(frame), int(joint))
        if key in seen:
            continue
        seen.add(key)
        picked.append(key)
        if len(picked) >= int(top_k):
            break
    if not picked:
        raise RuntimeError("gradient ranking produced no cells")
    return tuple(picked)


def mock_grad(trajectory: ClipTrajectory, joints: Sequence[int], free_frames: Sequence[int]) -> np.ndarray:
    grad = np.zeros_like(trajectory.rotvecs)
    for frame in free_frames:
        for joint in joints:
            grad[int(frame), int(joint)] = trajectory.rotvecs[int(frame), int(joint)] + 0.01
    return grad


def _probe_specs(cells: Sequence[tuple[int, int]]) -> tuple[tuple[int, int, tuple[float, float, float], float], ...]:
    directions = joint_search_directions(("x", "y", "z"), int(JOINT_DIAGONAL_AXES))
    specs: list[tuple[int, int, tuple[float, float, float], float]] = []
    for frame, joint in cells:
        for direction in directions:
            for rung in RUNGS:
                specs.append((int(frame), int(joint), direction, float(rung)))
    return tuple(specs)


def _integrate_specs(
    current: ClipTrajectory,
    specs: Sequence[tuple[int, int, tuple[float, float, float], float]],
    *,
    plant: RagdollPlant,
    bands: ClipBands,
    config: RagdollPlantConfig | None,
) -> list[ClipTrajectory]:
    probes: list[ClipTrajectory] = []
    for frame, joint, direction, rung in specs:
        if int(frame) not in bands.free_frames:
            raise RuntimeError("ranked a locked frame")
        probe = copy_trajectory(current)
        probe.alpha_control = apply_nudge(
            current.alpha_control,
            frame=int(frame),
            joint=int(joint),
            direction=direction,
            rung=float(rung),
            plant=plant,
        )
        probes.append(integrate_clip(plant, probe, bands, config=config))
    return probes


def run_sweeps(
    *,
    plant: RagdollPlant,
    trajectory: ClipTrajectory,
    bands: ClipBands,
    joints: Sequence[int],
    score_fn: ScoreFn,
    rank_fn: RankFn,
    reverse_order: bool,
    max_sweeps: int,
    deadline: float,
    config: RagdollPlantConfig | None = None,
    score_many: ScoreManyFn | None = None,
    pack_size: int | None = None,
) -> tuple[ClipTrajectory, ScoreBreakdown, dict[str, Any]]:
    current = integrate_clip(plant, trajectory, bands, config=config)
    current_score = score_fn(current)
    accepted = 0
    sweeps = 0
    aborted = False
    abort_reason = ""
    batch_score = score_many or (lambda trajs: [score_fn(item) for item in trajs])
    for sweep in range(int(max_sweeps)):
        if time.perf_counter() > float(deadline):
            aborted = True
            abort_reason = "wall_clock"
            break
        sweeps = sweep + 1
        print(
            f"ragdoll sweep {sweeps}/{max_sweeps} reverse={bool(reverse_order)} "
            f"accepted={accepted} objective={current_score.clip_objective:.6f}",
            flush=True,
        )
        if time.perf_counter() > float(deadline):
            aborted = True
            abort_reason = "wall_clock"
            break
        cells = rank_fn(current, bool(reverse_order))
        specs = _probe_specs(cells)
        chunk = int(pack_size) if pack_size is not None else len(specs)
        if chunk < 1:
            raise RuntimeError("pack_size must be at least 1")
        kept_this_sweep = False
        for start in range(0, len(specs), chunk):
            if time.perf_counter() > float(deadline):
                aborted = True
                abort_reason = "wall_clock"
                break
            probes = _integrate_specs(
                current,
                specs[start : start + chunk],
                plant=plant,
                bands=bands,
                config=config,
            )
            scores = batch_score(probes)
            if len(scores) != len(probes):
                raise RuntimeError("packed score count does not match probe count")
            best: tuple[ClipTrajectory, ScoreBreakdown] | None = None
            for probe, candidate in zip(probes, scores):
                keep, _reason = keep_probe(
                    current=current_score,
                    candidate=candidate,
                    trajectory=probe,
                    bands=bands,
                    plant=plant,
                    prefix_ok=prefix_unchanged(probe, bands),
                    suffix_ok=suffix_unchanged(probe, bands),
                )
                if not keep:
                    continue
                if best is None or float(candidate.clip_objective) > float(best[1].clip_objective):
                    best = (probe, candidate)
            if best is None:
                continue
            current, current_score = best
            accepted += 1
            kept_this_sweep = True
            print(
                f"ragdoll keep sweep={sweeps} reverse={bool(reverse_order)} "
                f"objective={current_score.clip_objective:.6f} scoreMean={current_score.score_mean:.6f}",
                flush=True,
            )
            break
        if aborted:
            break
        if not kept_this_sweep:
            break
    return current, current_score, {
        "sweeps": int(sweeps),
        "accepted": int(accepted),
        "aborted": bool(aborted),
        "abortReason": abort_reason,
        "reverseOrder": bool(reverse_order),
    }


def assert_not_idle_search_clip(clip: str) -> None:
    """Walk already contains idle prefix/suffix. Do not search idle alone."""
    if str(clip) == SEARCH_IDLE_CLIP:
        raise RuntimeError(
            "do not search goblin idle as its own clip; "
            "idle_start_move_end already contains locked idle prefix and suffix"
        )


def rest_drift_deg(trajectory: ClipTrajectory, bands: ClipBands) -> float:
    rest = np.asarray(trajectory.idle_rotvecs, dtype=np.float64)
    free = list(bands.free_frames)
    if not free:
        return 0.0
    delta = np.asarray(trajectory.rotvecs[free], dtype=np.float64) - rest[None, :, :]
    return float(np.max(np.linalg.norm(delta, axis=-1)) * (180.0 / np.pi))


def idle_stability_report(
    *,
    seed_score: ScoreBreakdown,
    picked_score: ScoreBreakdown,
    trajectory: ClipTrajectory,
    bands: ClipBands,
) -> dict[str, Any]:
    """Locked idle prefix/suffix inside a motion clip, not a separate idle search."""
    drop = float(seed_score.clip_objective) - float(picked_score.clip_objective)
    drift = rest_drift_deg(trajectory, bands)
    collapse = drop > float(IDLE_COLLAPSE_DROP)
    drifted = drift > float(IDLE_REST_MAX_DEG)
    reason = ""
    if collapse:
        reason = "objective_collapse"
    elif drifted:
        reason = "rest_drift"
    return {
        "ok": (not collapse) and (not drifted),
        "seedObjective": float(seed_score.clip_objective),
        "pickedObjective": float(picked_score.clip_objective),
        "drop": float(drop),
        "collapseDropLimit": float(IDLE_COLLAPSE_DROP),
        "restDriftDeg": float(drift),
        "restDriftLimitDeg": float(IDLE_REST_MAX_DEG),
        "reason": reason,
    }


def pick_whole_trajectory(
    forward: tuple[ClipTrajectory, ScoreBreakdown, dict[str, Any]],
    reverse: tuple[ClipTrajectory, ScoreBreakdown, dict[str, Any]],
) -> tuple[ClipTrajectory, ScoreBreakdown, dict[str, Any], str]:
    if float(reverse[1].clip_objective) > float(forward[1].clip_objective):
        return reverse[0], reverse[1], reverse[2], "reverse"
    return forward[0], forward[1], forward[2], "forward"


def search_clip(
    *,
    plant: RagdollPlant,
    trajectory: ClipTrajectory,
    bands: ClipBands,
    joints: Sequence[int],
    score_fn: ScoreFn,
    rank_fn: RankFn,
    config: RagdollPlantConfig | None = None,
    score_many: ScoreManyFn | None = None,
    deadline: float | None = None,
    max_forward: int = MAX_FORWARD_SWEEPS,
    max_reverse: int = MAX_REVERSE_SWEEPS,
    pack_size: int | None = None,
) -> tuple[ClipTrajectory, ScoreBreakdown, dict[str, Any]]:
    cap = time.perf_counter() + float(WALL_CLOCK_CAP_S) if deadline is None else float(deadline)
    seed = copy_trajectory(trajectory)
    probe_pack = int(WALL_CLOCK_PACK_SIZE if pack_size is None else pack_size)
    forward = run_sweeps(
        plant=plant,
        trajectory=copy_trajectory(seed),
        bands=bands,
        joints=joints,
        score_fn=score_fn,
        rank_fn=rank_fn,
        reverse_order=False,
        max_sweeps=int(max_forward),
        deadline=cap,
        config=config,
        score_many=score_many,
        pack_size=probe_pack,
    )
    if time.perf_counter() > cap or bool(forward[2].get("aborted")):
        picked, score, stats, winner = forward[0], forward[1], forward[2], "forward"
        merged = {
            "forward": forward[2],
            "reverse": {
                "sweeps": 0,
                "accepted": 0,
                "aborted": True,
                "abortReason": "wall_clock",
                "reverseOrder": True,
            },
            "winner": winner,
            "aborted": True,
            "abortReason": str(forward[2].get("abortReason") or "wall_clock"),
            "sweeps": int(forward[2].get("sweeps") or 0),
            "accepted": int(forward[2].get("accepted") or 0),
        }
        stats = dict(stats)
        stats.update(merged)
        return picked, score, stats
    reverse = run_sweeps(
        plant=plant,
        trajectory=copy_trajectory(seed),
        bands=bands,
        joints=joints,
        score_fn=score_fn,
        rank_fn=rank_fn,
        reverse_order=True,
        max_sweeps=int(max_reverse),
        deadline=cap,
        config=config,
        score_many=score_many,
        pack_size=probe_pack,
    )
    picked, score, stats, winner = pick_whole_trajectory(forward, reverse)
    merged = {
        "forward": forward[2],
        "reverse": reverse[2],
        "winner": winner,
        "aborted": bool(forward[2]["aborted"] or reverse[2]["aborted"]),
        "abortReason": forward[2]["abortReason"] or reverse[2]["abortReason"],
        "accepted": int(forward[2]["accepted"] + reverse[2]["accepted"]),
        "sweeps": int(forward[2]["sweeps"] + reverse[2]["sweeps"]),
    }
    return picked, score, merged


def poses_from_trajectory(plant: RagdollPlant, trajectory: ClipTrajectory) -> dict[int, dict[str, Any]]:
    poses: dict[int, dict[str, Any]] = {}
    for frame in range(int(trajectory.rotvecs.shape[0])):
        poses[int(frame)] = serialize_pose_degrees(plant, trajectory.rotvecs[int(frame)])
    return poses


def idle_and_bands_from_payload(
    plant: RagdollPlant,
    payload: Mapping[str, Any],
    *,
    lock_suffix: bool,
) -> tuple[ClipTrajectory, ClipBands]:
    frames = tuple(int(frame) for frame in payload["frameIndices"])
    poses = {int(key): value for key, value in payload["poses"].items()}
    config = payload.get("config") if isinstance(payload.get("config"), Mapping) else {}
    prefix = int(config.get("idle_prefix_frames") or 0)
    suffix = int(config.get("idle_suffix_frames") or 0)
    bands = clip_bands(
        frame_count=len(frames),
        prefix=prefix,
        suffix=suffix,
        lock_suffix=bool(lock_suffix),
    )
    rotvecs = np.zeros((len(frames), plant.joint_count(), 3), dtype=np.float64)
    for position, frame in enumerate(frames):
        rotvecs[int(position)] = deserialize_pose_radians(plant, poses[int(frame)])
    idle = rotvecs[0].copy()
    prefix_poses = rotvecs.copy()
    suffix_poses = rotvecs.copy() if bool(lock_suffix) else None
    alpha = np.zeros_like(rotvecs)
    return (
        ClipTrajectory(
            rotvecs=rotvecs,
            omega=np.zeros_like(rotvecs),
            alpha_control=alpha,
            clamp_counts=np.zeros((len(frames), plant.joint_count()), dtype=np.int64),
            idle_rotvecs=idle,
            prefix_poses=prefix_poses,
            suffix_poses=suffix_poses,
        ),
        bands,
    )


def zero_motion_seed(plant: RagdollPlant, source: ClipTrajectory, bands: ClipBands) -> ClipTrajectory:
    """Keep locked idle bands; free frames start from last prefix / idle with zero control."""
    rotvecs = source.rotvecs.copy()
    if int(bands.prefix) > 0:
        start = source.prefix_poses[int(bands.prefix) - 1]
    else:
        start = source.idle_rotvecs
    for frame in bands.free_frames:
        rotvecs[int(frame)] = start
    if source.suffix_poses is not None and bool(bands.lock_suffix):
        start_suffix = int(bands.frame_count) - int(bands.suffix)
        rotvecs[start_suffix:] = source.suffix_poses[start_suffix:]
    return ClipTrajectory(
        rotvecs=rotvecs,
        omega=np.zeros_like(rotvecs),
        alpha_control=np.zeros_like(rotvecs),
        clamp_counts=np.zeros((int(bands.frame_count), plant.joint_count()), dtype=np.int64),
        idle_rotvecs=source.idle_rotvecs.copy(),
        prefix_poses=source.prefix_poses.copy(),
        suffix_poses=None if source.suffix_poses is None else source.suffix_poses.copy(),
    )


def _config_value(config: Any, key: str) -> Any:
    if hasattr(config, key) and not isinstance(config, Mapping):
        return getattr(config, key)
    if isinstance(config, Mapping):
        if key not in config and key == "temporal_loop_wrap_enabled":
            return False
        if key not in config:
            raise RuntimeError(f"score config missing {key}")
        return config[key]
    raise RuntimeError(f"score config missing {key}")


def assert_score_config(config: Any, *, chroma_scale: int | None = None) -> None:
    expected = dict(REQUIRED_SCORE_CONFIG)
    if chroma_scale is not None:
        expected["chroma_scale"] = int(chroma_scale)
    for key, want in expected.items():
        got = _config_value(config, key)
        if isinstance(want, bool):
            if bool(got) is not bool(want):
                raise RuntimeError(f"score config {key}={got!r} != {want!r}")
        elif isinstance(want, float):
            if abs(float(got) - float(want)) > 1e-9:
                raise RuntimeError(f"score config {key}={got!r} != {want!r}")
        elif isinstance(want, int) and not isinstance(want, bool):
            if int(got) != int(want):
                raise RuntimeError(f"score config {key}={got!r} != {want!r}")
        else:
            if got != want:
                raise RuntimeError(f"score config {key}={got!r} != {want!r}")


def frozen_root_raw(experiment: Any, pose_count: int):
    import torch

    zeros = torch.zeros((int(pose_count), 3), dtype=torch.float32, device=experiment.device)
    return zeros, zeros


def physical_to_evaluate(experiment: Any, rotvecs: np.ndarray):
    import torch

    return torch.as_tensor(np.asarray(rotvecs, dtype=np.float32), device=experiment.device)


def _pose_dim_tensor(value: Any, pose_count: int) -> bool:
    import torch

    if not isinstance(value, torch.Tensor):
        return False
    return int(value.ndim) >= 1 and int(value.shape[0]) == int(pose_count)


def slice_packed(packed: Mapping[str, Any], start: int, end: int, pose_count: int) -> dict[str, Any]:
    sliced: dict[str, Any] = {}
    for key, value in packed.items():
        if _pose_dim_tensor(value, pose_count):
            sliced[str(key)] = value[int(start) : int(end)]
        else:
            sliced[str(key)] = value
    return sliced


def breakdown_from_packed(
    experiment: Any,
    packed: Mapping[str, Any],
    rotvecs: np.ndarray,
    root_t: Any,
    root_r: Any,
) -> ScoreBreakdown:
    import torch

    geometry = packed["geometryScore"].detach()
    collision = packed["collisionError"].detach() if "collisionError" in packed else torch.zeros_like(geometry)
    image = geometry - float(SCORE_COLLISION_WEIGHT) * collision
    bones = physical_to_evaluate(experiment, rotvecs)
    clip_obj = float(experiment._clip_objective_mean(bones, root_t, root_r, packed))
    score_mean = float(packed["score"].mean().item())
    temporal = float(experiment._temporal_penalty(bones, root_t, root_r).detach().item())
    return ScoreBreakdown(
        clip_objective=clip_obj,
        score_mean=score_mean,
        image_mean=image.detach().cpu().numpy().astype(np.float64),
        collision=collision.detach().cpu().numpy().astype(np.float64),
        temporal=temporal,
    )


def score_trajectory_gpu(experiment: Any, plant: RagdollPlant, trajectory: ClipTrajectory) -> ScoreBreakdown:
    frames = int(trajectory.rotvecs.shape[0])
    bones = physical_to_evaluate(experiment, trajectory.rotvecs)
    root_t, root_r = frozen_root_raw(experiment, frames)
    packed = experiment.evaluate(bones, root_t, root_r, bone_mask=experiment.active_node_mask)
    return breakdown_from_packed(experiment, packed, trajectory.rotvecs, root_t, root_r)


def score_trajectories_gpu(
    experiment: Any,
    plant: RagdollPlant,
    trajectories: Sequence[ClipTrajectory],
) -> list[ScoreBreakdown]:
    import torch

    if not trajectories:
        return []
    frames = int(trajectories[0].rotvecs.shape[0])
    hyps = joint_score_hyps_per_launch(
        pose_budget=int(experiment.config.joint_score_raster_batch),
        frame_count=frames,
    )
    out: list[ScoreBreakdown] = []
    for start in range(0, len(trajectories), hyps):
        chunk = list(trajectories[start : start + hyps])
        bones = torch.cat([physical_to_evaluate(experiment, item.rotvecs) for item in chunk], dim=0)
        pose_count = int(bones.shape[0])
        if pose_count % frames != 0:
            raise RuntimeError("packed pose batch is not a multiple of clip length")
        root_t, root_r = frozen_root_raw(experiment, pose_count)
        packed = experiment.evaluate(bones, root_t, root_r, bone_mask=experiment.active_node_mask)
        for index, item in enumerate(chunk):
            sl_start = index * frames
            sl_end = sl_start + frames
            sub = slice_packed(packed, sl_start, sl_end, pose_count)
            out.append(
                breakdown_from_packed(
                    experiment,
                    sub,
                    item.rotvecs,
                    root_t[sl_start:sl_end],
                    root_r[sl_start:sl_end],
                )
            )
    return out


def rank_cells_gpu(
    experiment: Any,
    plant: RagdollPlant,
    trajectory: ClipTrajectory,
    joints: Sequence[int],
    bands: ClipBands,
    *,
    reverse_order: bool,
    top_k: int = TOP_K_CELLS,
) -> tuple[tuple[int, int], ...]:
    import torch

    frames = int(trajectory.rotvecs.shape[0])
    bones = torch.nn.Parameter(physical_to_evaluate(experiment, trajectory.rotvecs))
    root_t, root_r = frozen_root_raw(experiment, frames)
    packed = experiment.evaluate(bones, root_t, root_r, bone_mask=experiment.active_node_mask)
    packed["geometryScore"].sum().backward()
    if bones.grad is None:
        raise RuntimeError("evaluate() produced no physical-space bone gradient")
    grad = bones.grad.detach().cpu().numpy().astype(np.float64)
    return rank_cells_from_grad(
        grad,
        plant=plant,
        joints=joints,
        free_frames=bands.free_frames,
        top_k=int(top_k),
        reverse_order=bool(reverse_order),
    )


def rescore_presmooth_payload(experiment: Any, payload: Mapping[str, Any]) -> float:
    poses = {int(key): value for key, value in payload["poses"].items()}
    bones, root_t, root_r = experiment._initial_pose_tensors(poses)
    bounded = experiment._bounded_bone_vectors(bones)
    packed = experiment.evaluate(bounded, root_t, root_r, bone_mask=experiment.active_node_mask)
    return float(packed["score"].mean().item())


def assert_presmooth_parity(experiment: Any, payload: Mapping[str, Any]) -> float:
    mean = rescore_presmooth_payload(experiment, payload)
    if abs(float(mean) - float(PRESMOOTH_SCORE)) > float(PRESMOOTH_TOLERANCE):
        raise RuntimeError(
            f"presmooth adapter score {mean:.7f} != {PRESMOOTH_SCORE:.7f} ± {PRESMOOTH_TOLERANCE}"
        )
    return float(mean)


def plant_constants(plant: RagdollPlant, config: RagdollPlantConfig) -> dict[str, Any]:
    return {
        **plant_mass_report(plant),
        "dt": float(config.dt),
        "substeps": int(config.substeps),
        "zeta": float(config.zeta),
        "mu": float(config.mu),
        "gravity": float(config.gravity),
        "clampFrac": float(CLAMP_FRAC),
        "jointLimitDeg": float(JOINT_LIMIT_DEG),
        "epsilonThetaDeg": float(EPSILON_THETA_DEG),
        "epsilonOmegaDegS": float(EPSILON_OMEGA_DEG_S),
        "rungs": [float(value) for value in RUNGS],
        "topK": int(TOP_K_CELLS),
        "strainSlack": float(STRAIN_SLACK),
        "wallClockCapS": float(WALL_CLOCK_CAP_S),
        "fusedInertiaMix": float(FUSED_INERTIA_MIX),
        "motionKeepFrac": float(MOTION_KEEP_FRAC),
        "gyroscopicTerm": False,
        "motionRootKey": MOTION_ROOT_KEY,
        "motionRootRotationKey": MOTION_ROOT_ROTATION_KEY,
    }
