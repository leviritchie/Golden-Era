"""Sprite leftover classification and clip-wide accept gates.

CPU-pure. GPU raster and GLB writes live in the surgery runner.
Proof: generated-artifact experiment under artifacts/sprite_feasibility/.
"""
from __future__ import annotations

import hashlib
import itertools
import math
from dataclasses import dataclass
from functools import cmp_to_key
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from gpu_profile_camera_initializer import PROFILE_MIN_PROFILE_FACING
from leftover_gravity import extra_predicted_mask, leftover_mask
from sprite_anatomy import (
    anatomy_attitude_bones,
    anatomy_bilateral_pairs,
    anatomy_bone_to_group,
    anatomy_central_search_groups,
    anatomy_group_bones,
    anatomy_visual_body_chain,
    anatomy_wing_chain,
)

WORK_TREE_RELATIVE = Path("artifacts") / "sprite_feasibility"
FORBIDDEN_WRITE_PARTS = frozenset({"meshy_downloads", "fused_push_v24_pipeline"})

# Rear/front-on selected cameras. Goblin idle fused-push facing ≈ 0.058.
PROFILE_REAR_FACING_VETO = 0.10

EPSILON_LEFTOVER = 0.02
EPSILON_EXTRA = 0.02
EPSILON_STRAIN = 0.01
# Cascade regional leftover uses this slack. Surgery leftover search must too:
# occupancy leftover does not see LBS melt.
STRAIN_ACCEPT_SLACK = 0.04
FEASIBLE_LEFTOVER = 0.04
FEASIBLE_EXTRA = 0.04

# Ordered anatomy-fit pipeline. Early steps stay mirrored. Divergence and
# missing bones come only after the T-pose rest and anatomy rotations exist.
ANATOMY_FIT_STAGES = (
    "tpose_straighten_spread",
    "snip_tpose_bridges",
    "anatomy_frame_rotation",
    "symmetric_bone_fit",
    "asymmetric_fine_tune",
    "shared_skeleton_temporal",
    "insert_missing_symmetric",
    "pose_new_bones",
)
TPOSE_BRIDGE_STRETCH_RATIO = 4.0
TPOSE_BRIDGE_FACE_FRACTION_CAP = 0.20
# Coarse shared Euler for anatomy stage 4. Not PIPELINE_REFINE 2–30°.
SYMMETRIC_BONE_STEPS_DEG = (90.0, -90.0, 45.0, -45.0)
# Combined-axis leftover search uses these magnitudes, small then large.
# Combos are anatomical (raise, sweep, twist) per bone, not bone-local x/y/z
# and not a shared world lateral/spine/ventral that lifts one wing and drops
# the other. A colliding combo prunes larger steps in the same signed axes;
# that is why this is not a full 5^3 raster of every anatomical-axis tuple.
TEMPORAL_COARSE_MAGNITUDES_DEG = (45.0, 90.0)
TEMPORAL_FINE_STEPS_DEG = (15.0, -15.0, 10.0, -10.0, 5.0, -5.0, 2.0, -2.0)
# Reject leftover ticks that do not move occupancy by a few percent.
SUBSTANTIAL_LEFTOVER_DROP = 0.004
SUBSTANTIAL_LEFTOVER_REL = 0.03
BONE_AXES = ("x", "y", "z")
ARCHITECTURE_ACCEPT_NAMES = frozenset(
    {
        "phase_baked_fly_rest",
        "phase_glide_rest_rotation",
        "phase_glide_wing_spread",
        "phase_glide_symmetric_wing_spread",
        "anatomy_tpose_snip_rotation",
        "symmetric_bone_fit",
        "asymmetric_fine_tune",
        "shared_skeleton_temporal",
        "insert_missing_symmetric",
        "symmetric_only",
    }
)
# Independent rest-length rungs for stage 5. Not occupancy rest-sculpt of the perch.
ASYMMETRIC_REST_LENGTH_SCALES = (1.25, 1.45, 1.60)


def next_anatomy_fit_stage(completed: Sequence[str]) -> str:
    done = [str(item) for item in completed]
    expected = list(ANATOMY_FIT_STAGES[: len(done)])
    if done != expected:
        raise ValueError(
            f"anatomyFitCompleted {done} is not a prefix of {list(ANATOMY_FIT_STAGES)}"
        )
    if len(done) >= len(ANATOMY_FIT_STAGES):
        raise ValueError("anatomy-fit pipeline is already complete")
    return str(ANATOMY_FIT_STAGES[len(done)])


def symmetric_bone_fit_pairs(
    catalog: Mapping[str, Any], names: Sequence[str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for left, right in anatomy_bilateral_pairs(catalog):
        chain_a = anatomy_wing_chain(catalog, left, names)
        chain_b = anatomy_wing_chain(catalog, right, names)
        if len(chain_a) != len(chain_b):
            raise ValueError(
                f"bilateral pair {left}/{right} chains have different lengths "
                f"({len(chain_a)} vs {len(chain_b)})"
            )
        rows.append(
            {
                "groupA": str(left),
                "groupB": str(right),
                "bonesA": list(chain_a),
                "bonesB": list(chain_b),
            }
        )
    if not rows:
        raise ValueError("symmetric bone fit found no bilateral pairs")
    return rows


def asymmetric_distal_bones(
    catalog: Mapping[str, Any], names: Sequence[str]
) -> list[dict[str, str]]:
    """One distal bone per side of each bilateral pair. Stage 5 rest-length."""
    rows: list[dict[str, str]] = []
    for pair in symmetric_bone_fit_pairs(catalog, names):
        rows.append({"group": str(pair["groupA"]), "bone": str(pair["bonesA"][-1])})
        rows.append({"group": str(pair["groupB"]), "bone": str(pair["bonesB"][-1])})
    return rows


def unique_joint_pose_count(
    poses: Mapping[int, Mapping[str, Any]], frames: Sequence[int]
) -> int:
    """How many distinct joint Euler snapshots exist on the listed frames.

    Root translation is ignored. One pose copied across a phase scores as 1.
    """
    signatures: set[tuple[tuple[str, float, float, float], ...]] = set()
    for frame in frames:
        pose = poses.get(int(frame)) or {}
        items: list[tuple[str, float, float, float]] = []
        for key in sorted(pose):
            if str(key).startswith("__"):
                continue
            entry = pose[key]
            if not isinstance(entry, Mapping):
                continue
            items.append(
                (
                    str(key),
                    float(entry.get("x", 0.0)),
                    float(entry.get("y", 0.0)),
                    float(entry.get("z", 0.0)),
                )
            )
        signatures.add(tuple(items))
    return len(signatures)


def insert_child_bone_name(group: str) -> str:
    """Catalog group child. Not Bone_FeasibilityInsert and not a Bone_* index guess."""
    label = str(group).strip()
    if not label:
        raise ValueError("insert child needs an anatomy group name")
    return f"Bone_{label}_insert"


def leftover_symmetric_insert_parents(
    catalog: Mapping[str, Any],
    unique_bones: Sequence[str],
) -> list[dict[str, Any]]:
    """Causal leftover unique-region bones → symmetric insert parents.

    Trunk leftover is attitude, not a missing bone. Leftover on any bone of a
    bilateral pair inserts a child of both distal bones. Leftover on a midline
    group inserts one child of that group's distal bone.
    """
    unique = [str(bone) for bone in unique_bones if str(bone)]
    if not unique:
        raise ValueError("leftover unique region is empty")
    mapping = anatomy_bone_to_group(catalog)
    unknown = [bone for bone in unique if bone not in mapping]
    if unknown:
        raise ValueError(f"leftover unique bones are not in the anatomy catalog: {unknown}")
    groups: list[str] = []
    for bone in unique:
        group = str(mapping[bone])
        if group not in groups:
            groups.append(group)
    leftover_groups = {group for group in groups if group != "trunk"}
    if not leftover_groups:
        raise ValueError("leftover unique region is only trunk (attitude, not a missing bone)")
    central = set(anatomy_central_search_groups(catalog))
    used: set[str] = set()
    rows: list[dict[str, Any]] = []
    for left, right in anatomy_bilateral_pairs(catalog):
        if left not in leftover_groups and right not in leftover_groups:
            continue
        parent_a = anatomy_group_bones(catalog, left)[-1]
        parent_b = anatomy_group_bones(catalog, right)[-1]
        rows.append(
            {
                "kind": "bilateral",
                "groupA": str(left),
                "groupB": str(right),
                "parentA": str(parent_a),
                "parentB": str(parent_b),
                "childA": insert_child_bone_name(left),
                "childB": insert_child_bone_name(right),
            }
        )
        used.add(str(left))
        used.add(str(right))
    for group in groups:
        if group in used or group == "trunk":
            continue
        if group not in central:
            raise ValueError(f"leftover group {group!r} is not bilateral or central")
        parent = anatomy_group_bones(catalog, group)[-1]
        rows.append(
            {
                "kind": "central",
                "group": str(group),
                "parent": str(parent),
                "child": insert_child_bone_name(group),
            }
        )
        used.add(group)
    if not rows:
        raise ValueError("leftover unique region mapped to no insert parents")
    return rows


def anatomy_joints_xy(
    catalog: Mapping[str, Any],
    joints_xy: Mapping[str, tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    """Keep catalog bones only. Helper nodes are not leftover unique-region owners."""
    mapping = anatomy_bone_to_group(catalog)
    filtered = {
        str(name): (float(xy[0]), float(xy[1]))
        for name, xy in joints_xy.items()
        if str(name) in mapping
    }
    if not filtered:
        raise ValueError("leftover unique-region has no anatomy catalog joints")
    return filtered


def distal_owner_vertex_indices(
    rest: np.ndarray,
    owner_names: Sequence[str],
    parent: str,
    keel_origin: np.ndarray,
    *,
    fraction: float = 0.15,
) -> list[int]:
    """Farthest parent-owned verts from the keel. Empty leftover uses these."""
    names = [str(name) for name in owner_names]
    idxs = [index for index, name in enumerate(names) if name == str(parent)]
    if not idxs:
        raise ValueError(f"parent {parent} owns no vertices")
    points = np.asarray(rest, dtype=np.float64).reshape(-1, 3)
    if points.shape[0] != len(names):
        raise ValueError("rest and owner_names must share a vertex count")
    origin = np.asarray(keel_origin, dtype=np.float64).reshape(3)
    owned = points[np.asarray(idxs, dtype=np.int64)]
    dists = np.linalg.norm(owned - origin, axis=1)
    keep = max(1, int(math.ceil(float(fraction) * float(len(idxs)))))
    order = np.argsort(dists)[-keep:]
    return [int(idxs[int(index)]) for index in order]


def symmetric_bone_trial_better(before: OccupancyFractions, after: OccupancyFractions) -> bool:
    leftover_drop = float(before.leftover) - float(after.leftover)
    extra_growth = float(after.extra) - float(before.extra)
    return leftover_drop > 1e-9 and extra_growth <= leftover_drop + 1e-9


def substantial_occupancy_better(
    before: OccupancyFractions,
    after: OccupancyFractions,
    *,
    before_strain: float | None = None,
    after_strain: float | None = None,
    strain_slack: float = STRAIN_ACCEPT_SLACK,
) -> bool:
    """Keep only a leftover drop that is large enough to be a real pose change.

    Tiny leftover ticks (1e-9 class) are how 45° flap jitter survived. Extra
    still may not grow more than leftover fell. Strain growth past the cascade
    slack is LBS melt, not a keep.
    """
    if (before_strain is None) != (after_strain is None):
        raise ValueError("before_strain and after_strain must be passed together")
    leftover_drop = float(before.leftover) - float(after.leftover)
    extra_growth = float(after.extra) - float(before.extra)
    threshold = max(
        float(SUBSTANTIAL_LEFTOVER_DROP),
        float(SUBSTANTIAL_LEFTOVER_REL) * float(before.leftover),
    )
    if leftover_drop + 1e-12 < threshold or extra_growth > leftover_drop + 1e-9:
        return False
    if before_strain is not None:
        if float(after_strain) - float(before_strain) > float(strain_slack) + 1e-12:
            return False
    return True


def occupancy_collision_unacceptable(seed: OccupancyFractions, trial: OccupancyFractions) -> bool:
    """Extra grew too far vs the seed. Further motion in this direction is excluded."""
    leftover_drop = float(seed.leftover) - float(trial.leftover)
    extra_growth = float(trial.extra) - float(seed.extra)
    return extra_growth > leftover_drop + 1e-9 or extra_growth > float(EPSILON_EXTRA) + 1e-12


def leftover_trial_illegal(
    seed: OccupancyFractions,
    trial: OccupancyFractions,
    *,
    seed_strain: float,
    trial_strain: float,
    strain_slack: float = STRAIN_ACCEPT_SLACK,
) -> bool:
    """Occupancy extra explosion or LBS melt. Further motion in this direction is excluded."""
    if occupancy_collision_unacceptable(seed, trial):
        return True
    return float(trial_strain) - float(seed_strain) > float(strain_slack) + 1e-12


def temporal_coarse_combos() -> tuple[tuple[float, float, float], ...]:
    """Combined model-frame coarse deltas, smaller magnitude first so collision can prune."""
    values = (0.0,)
    for mag in TEMPORAL_COARSE_MAGNITUDES_DEG:
        values = values + (float(mag), -float(mag))
    combos = [
        (dx, dy, dz)
        for dx, dy, dz in itertools.product(values, repeat=3)
        if abs(dx) > 1e-9 or abs(dy) > 1e-9 or abs(dz) > 1e-9
    ]
    combos.sort(
        key=lambda combo: (
            max(abs(value) for value in combo),
            sum(abs(value) for value in combo),
            sum(1 for value in combo if abs(value) > 1e-9),
            combo,
        )
    )
    return tuple(combos)


def combo_beyond_collision_bound(
    combo: tuple[float, float, float],
    bound: tuple[float, float, float],
) -> bool:
    """True if combo is further along the same signed axes as a colliding bound.

    A bound does not prune combos that start moving a previously-zero axis:
    (45,0,0) colliding still allows (45,45,0). (45,45,45) colliding prunes
    (90,45,45) and the other larger steps in that octant.
    """
    if len(combo) != 3 or len(bound) != 3:
        raise ValueError("coarse combos are (x, y, z) degree triples")
    equal = True
    for channel, limit in zip(combo, bound):
        channel_v = float(channel)
        limit_v = float(limit)
        if abs(limit_v) <= 1e-9:
            if abs(channel_v) > 1e-9:
                return False
            continue
        if channel_v * limit_v < -1e-12:
            return False
        if abs(channel_v) + 1e-9 < abs(limit_v):
            return False
        if abs(channel_v - limit_v) > 1e-9:
            equal = False
    return not equal


def combo_pruned_by_collision_bounds(
    combo: tuple[float, float, float],
    bounds: Sequence[tuple[float, float, float]],
) -> bool:
    return any(combo_beyond_collision_bound(combo, bound) for bound in bounds)


def predict_channel_inertial(history: Sequence[float]) -> float:
    """Next sample from previous value plus velocity plus acceleration (dt = 1)."""
    values = [float(value) for value in history]
    if not values:
        raise ValueError("inertial predict needs at least one sample")
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        previous, latest = values
        return latest + (latest - previous)
    older, previous, latest = values[-3], values[-2], values[-1]
    velocity = latest - previous
    acceleration = velocity - (previous - older)
    return latest + velocity + acceleration

# Standing idle plates are portrait; HoMM3 flyer Move plates go landscape.
# Pitch ±90 shows the bird's back or belly to the occupancy camera (top-down
# of a flyer). Vision check rejected that: the plate is a SIDE view. Standing
# to flying is neck/spine/wing bone pose under identity root, not a root pitch
# that changes which face of the mesh we see.
FLIGHT_MOVE_MIN_ASPECT = 1.25
FLIGHT_ASPECT_VS_IDLE = 1.35
FLIGHT_PITCH_SIGNS = (90.0, -90.0)
FLIGHT_PITCH_DEG = (70.0, 80.0, 90.0, 100.0, 110.0)
FLIGHT_YAW_CAP_DEG = 180.0
FLIGHT_YAW_SIGNS = (90.0, -90.0)
FLIGHT_PRIOR = "side_view_identity_root"
# Image-plane spine pitch for standing → flying. Distal leftover search cannot
# invent this; occupancy leftover also cannot tell a belly-on dive from a
# side-view flyer, so the keep vetoes a drop in camera-right / camera-forward span.
FLIGHT_SPINE_STEPS_DEG = (-120.0, -90.0, -60.0, -45.0, 45.0, 60.0, 90.0, 120.0)
FLIGHT_BELLY_ROLL_STEPS_DEG = (-150.0, -120.0, -90.0, -60.0, 60.0, 90.0, 120.0, 150.0)
FLIGHT_PER_FRAME_SPINE_STEPS_DEG = (
    -120.0,
    -90.0,
    -60.0,
    -45.0,
    -30.0,
    -20.0,
    -12.0,
    -6.0,
    -4.0,
    -2.0,
    2.0,
    4.0,
    6.0,
    12.0,
    20.0,
    30.0,
    45.0,
    60.0,
    90.0,
    120.0,
)
# Refine a proven pipeline pose. Do not apply 45–120° from-scratch pitches.
PIPELINE_REFINE_SPINE_STEPS_DEG = (
    -30.0,
    -20.0,
    -12.0,
    -6.0,
    -4.0,
    -2.0,
    2.0,
    4.0,
    6.0,
    12.0,
    20.0,
    30.0,
)
FLIGHT_TAKEOFF_AXIS_XY = (0.7071067811865476, -0.7071067811865476)
FLIGHT_CRUISE_AXIS_XY = (1.0, 0.0)
FLIGHT_LANDING_AXIS_XY = (0.5, -0.8660254037844386)
FLIGHT_SPINE_CHAIN_LENGTH = 3
FLIGHT_SPINE_RIGHT_MIN = 0.65
FLIGHT_REST_RIGHT_MIN = 0.45
FLIGHT_BELLY_DOWN_MIN = 0.50
FLIGHT_BROAD_STROKE_MIN_SCORE = 0.85
FLYER_TAIL_TIP_CANDIDATES = ("Bone_012", "Bone_013")
FLYER_HEAD_TIP_CANDIDATES = ("Bone_014", "Bone_015", "Bone_016")
FLYER_BROAD_STROKE_SEARCH_CANDIDATES = (
    "Bone_001",
    "Bone_003",
    "Bone_002",
    "Bone_014",
    "Bone_015",
    "Bone_016",
    "Bone_012",
    "Bone_013",
)
SIDE_VIEW_RATIO_SLACK = 0.05
IDENTITY_SIDE_VIEW_ROUND_IDS = ("round_25", "round_03")
POSE_VELOCITY_EPS_DEG = 2.0
POSE_VELOCITY_TRAP_EPS_DEG = 8.0
POSE_VELOCITY_SKIP_BONES = frozenset({"Bone_000"})

# Extra viewpoints for a vision check. Occupancy leftover is the profile camera
# only; a screen-space cheat can pass leftover and still be a flat/wrong 3D pose.
VISION_CHECK_FIXED_CAMERAS = (
    {"id": "profile", "yawDeg": 0.0, "pitchDeg": 0.0, "role": "occupancy_camera"},
    {"id": "side_pos", "yawDeg": 90.0, "pitchDeg": 0.0, "role": "turntable_plus_90"},
    {"id": "side_neg", "yawDeg": -90.0, "pitchDeg": 0.0, "role": "turntable_minus_90"},
    {"id": "rear", "yawDeg": 180.0, "pitchDeg": 0.0, "role": "opposite_profile"},
    {"id": "top", "yawDeg": 0.0, "pitchDeg": -75.0, "role": "look_down"},
)
VISION_CHECK_ORBIT_YAW_DEG = (0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0)
VISION_CHECK_QUESTIONS = (
    "orbit: is this a 3D volume, not a flat card that only reads from the profile camera?",
    "top: is the belly toward the ground (back/wings on top) on fly frames?",
    "side: does the fly frame read as horizontal flight, not a standing perch spun in place?",
    "idle: do idle frames stay an upright perch from yaw-left, yaw-right, and rear?",
)

LBS_CONDITION_FLOOR = 1e-3
LBS_SKIP_FRACTION_CAP = 0.25
MAX_ASSIGN_PX = 24.0
MAX_BODY_ROUNDS = 3
REST_SCULPT_MAX_BODY_LENGTHS = 0.08
DEBT_PROBE_DEG = 15.0
OWNER_AGREE_FRACTION = 0.75
REST_LENGTH_SCALE_MIN = 0.70
REST_LENGTH_SCALE_MAX = 1.60
REST_LENGTH_EXTRA_SCALE = 0.90
REBIND_CHILD_WEIGHT = 0.85
STRAIN_TOLERANCE = 0.08
STRAIN_EXCLUSIVE_WEIGHT = 0.99
OCCUPANCY_UNIQUE_MIN_WEIGHT = 1.0
OCCUPANCY_AMBIGUOUS_RATIO = 0.4

PREDICTED_ALPHA_THRESHOLD = 0.5
COMPARE_GIF_MAX_PANEL_PX = 1440


def compare_gif_panel_size(
    src_width: int,
    src_height: int,
    *,
    max_panel_px: int = COMPARE_GIF_MAX_PANEL_PX,
) -> tuple[int, int, int]:
    """Integer nearest-neighbor panel size for spot-check GIFs.

    Occupancy rasters stay at native sprite resolution. The GIF only upscales
    those stills. Bilinear fit into a 260px cell is what made the plates grainy.
    """
    width = int(src_width)
    height = int(src_height)
    if width < 1 or height < 1:
        raise ValueError("compare GIF source size must be positive")
    cap = int(max_panel_px)
    if cap < 1:
        raise ValueError("max_panel_px must be positive")
    scale = max(1, min(8, cap // width))
    return width * scale, height * scale, scale

CLASS_CAMERA_MISMATCH = "camera_mismatch"
CLASS_CAMERA_RESOLVED_POSE_STALE = "camera_resolved_pose_stale"
CLASS_CAMERA_MISMATCH_UNRESOLVED = "camera_mismatch_unresolved"
CLASS_POSE_SEARCH_DEBT = "pose_search_debt"
CLASS_BODY_INFEASIBLE_REST = "body_infeasible_rest"
CLASS_BODY_INFEASIBLE_LENGTH = "body_infeasible_length"
CLASS_WRONG_OWNER = "wrong_owner"
CLASS_MISSING_JOINT = "missing_joint"
CLASS_MISSING_GEOMETRY = "missing_geometry"
CLASS_NEEDS_GEOMETRY_AUTHORING = "needs_geometry_authoring"
CLASS_TOPOLOGY_FUSED = "topology_fused"
CLASS_WRONG_RIG_LANE = "wrong_rig_lane"
CLASS_LBS_ILL_CONDITIONED = "lbs_ill_conditioned"
CLASS_FEASIBLE = "feasible"
CLASS_PARTIAL_SURGERY_EXHAUSTED = "partial_surgery_exhausted"
CLASS_NEEDS_BLENDSHAPE_OR_REJECT = "needs_blendshape_or_reject"
CLASS_SURGERY_REJECTED = "surgery_rejected"
CLASS_CAMERA_OK = "camera_ok"

ALL_CLASSES = frozenset(
    {
        CLASS_CAMERA_MISMATCH,
        CLASS_CAMERA_RESOLVED_POSE_STALE,
        CLASS_CAMERA_MISMATCH_UNRESOLVED,
        CLASS_POSE_SEARCH_DEBT,
        CLASS_BODY_INFEASIBLE_REST,
        CLASS_BODY_INFEASIBLE_LENGTH,
        CLASS_WRONG_OWNER,
        CLASS_MISSING_JOINT,
        CLASS_MISSING_GEOMETRY,
        CLASS_NEEDS_GEOMETRY_AUTHORING,
        CLASS_TOPOLOGY_FUSED,
        CLASS_WRONG_RIG_LANE,
        CLASS_LBS_ILL_CONDITIONED,
        CLASS_FEASIBLE,
        CLASS_PARTIAL_SURGERY_EXHAUSTED,
        CLASS_NEEDS_BLENDSHAPE_OR_REJECT,
        CLASS_SURGERY_REJECTED,
        CLASS_CAMERA_OK,
    }
)

BODY_OPERATOR_ORDER = (
    CLASS_WRONG_OWNER,
    CLASS_BODY_INFEASIBLE_REST,
    CLASS_BODY_INFEASIBLE_LENGTH,
    CLASS_MISSING_JOINT,
)

OPERATOR_BY_CLASS = {
    CLASS_CAMERA_MISMATCH: "camera",
    CLASS_POSE_SEARCH_DEBT: "rotate_only_reaim",
    CLASS_WRONG_OWNER: "unique_region_rebind",
    CLASS_BODY_INFEASIBLE_REST: "rest_sculpt",
    CLASS_BODY_INFEASIBLE_LENGTH: "rest_length",
    CLASS_MISSING_JOINT: "insert_bone",
}

ARTICULATION_ACCEPTANCE_CLASSES = frozenset({CLASS_MISSING_JOINT, CLASS_WRONG_OWNER})


@dataclass(frozen=True)
class OccupancyFractions:
    leftover: float
    extra: float
    sprite_pixels: int
    leftover_pixels: int
    extra_pixels: int


def sha256_file(path: str | Path) -> str:
    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest()


def work_tree_root(repo_root: str | Path) -> Path:
    return Path(repo_root).resolve() / WORK_TREE_RELATIVE


def assert_write_path(path: str | Path, *, repo_root: str | Path) -> Path:
    """Refuse writes outside the experiment tree or into live fused-push / Meshy."""
    resolved = Path(path).resolve()
    root = Path(repo_root).resolve()
    work = work_tree_root(root)
    try:
        resolved.relative_to(work)
    except ValueError as exc:
        raise RuntimeError(
            f"sprite feasibility may only write under {work}; got {resolved}"
        ) from exc
    if any(part in FORBIDDEN_WRITE_PARTS for part in resolved.parts):
        raise RuntimeError(
            f"sprite feasibility must not write live payload paths: {resolved}"
        )
    return resolved


def idle_band_from_payload(payload: Mapping[str, Any]) -> tuple[int, int]:
    config = payload.get("config") if isinstance(payload.get("config"), Mapping) else {}
    prefix = int(config.get("idle_prefix_frames") or 0)
    suffix = int(config.get("idle_suffix_frames") or 0)
    if prefix < 0 or suffix < 0:
        raise ValueError("idle prefix/suffix must be non-negative")
    return prefix, suffix


def move_frame_positions(frame_count: int, prefix: int, suffix: int) -> list[int]:
    count = int(frame_count)
    start = int(prefix)
    end = count - int(suffix)
    if count < 1:
        raise ValueError("frame_count must be positive")
    if start < 0 or int(suffix) < 0 or start > count or int(suffix) > count:
        raise ValueError("idle bands do not fit the clip")
    if start >= end:
        return []
    return list(range(start, end))


def flight_phase_sprite_axis(
    frame_index: int,
    *,
    prefix: int,
    suffix: int,
    frame_count: int,
) -> tuple[float, float]:
    """Body long-axis prior for a flyer move frame. Wing-hull PCA cannot see this.

    Takeoff climbs. Mid-move cruise is level side flight. Landing flares up.
    Full-silhouette PCA follows raised wings and reads cruise as vertical.
    """
    move = move_frame_positions(int(frame_count), int(prefix), int(suffix))
    if int(frame_index) not in move:
        raise ValueError("flight_phase_sprite_axis is for move frames")
    start = int(move[0])
    end = int(move[-1])
    t = 0.0 if end == start else (int(frame_index) - start) / float(end - start)
    if t <= 0.15:
        return FLIGHT_TAKEOFF_AXIS_XY
    if t >= 0.85:
        return FLIGHT_LANDING_AXIS_XY
    return FLIGHT_CRUISE_AXIS_XY


def flight_phase_name(
    frame_index: int,
    *,
    prefix: int,
    suffix: int,
    frame_count: int,
) -> str:
    axis = flight_phase_sprite_axis(
        int(frame_index), prefix=prefix, suffix=suffix, frame_count=frame_count
    )
    if axis == FLIGHT_TAKEOFF_AXIS_XY:
        return "takeoff"
    if axis == FLIGHT_LANDING_AXIS_XY:
        return "landing"
    return "cruise"


def flight_phase_groups(
    move_frames: Sequence[int],
    *,
    prefix: int,
    suffix: int,
    frame_count: int,
) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = {"takeoff": [], "cruise": [], "landing": []}
    for frame in move_frames:
        groups[
            flight_phase_name(
                int(frame), prefix=prefix, suffix=suffix, frame_count=frame_count
            )
        ].append(int(frame))
    return groups


def frame_rest_source(
    frame_index: int,
    *,
    prefix: int,
    suffix: int,
    frame_count: int,
) -> str:
    """Idle bands keep the perch rest. Move frames use the phase fly rest."""
    move = move_frame_positions(int(frame_count), int(prefix), int(suffix))
    if int(frame_index) not in move:
        return "perch"
    return flight_phase_name(
        int(frame_index),
        prefix=int(prefix),
        suffix=int(suffix),
        frame_count=int(frame_count),
    )


def flight_phase_representative_frames(
    frames: Sequence[int],
    *,
    prefix: int,
    suffix: int,
) -> dict[str, int]:
    """Clip frame numbers for each fly-phase rest bake.

    Takeoff uses the first climb frame. Cruise uses the mid-phase frame.
    Landing uses the last flare frame. Idle bands are not representatives.
    """
    ordered = [int(frame) for frame in frames]
    count = len(ordered)
    move_frames = [
        ordered[pos] for pos in move_frame_positions(count, int(prefix), int(suffix))
    ]
    groups = flight_phase_groups(
        move_frames, prefix=int(prefix), suffix=int(suffix), frame_count=count
    )
    reps: dict[str, int] = {}
    if groups["takeoff"]:
        reps["takeoff"] = int(groups["takeoff"][0])
    if groups["cruise"]:
        cruise = groups["cruise"]
        reps["cruise"] = int(cruise[len(cruise) // 2])
    if groups["landing"]:
        reps["landing"] = int(groups["landing"][-1])
    if not reps:
        raise ValueError("flight_phase_representative_frames needs move frames")
    return reps


def clip_wraps_temporally(clip_name: str, payload: Mapping[str, Any]) -> bool:
    """Idle/Move cycles wrap last↔first. Concatenated start-move-end clips do not."""
    prefix, suffix = idle_band_from_payload(payload)
    if int(prefix) > 0 or int(suffix) > 0:
        return False
    name = str(clip_name or "").lower()
    for token in ("start_move", "entry", "exit", "attack", "hit", "death", "one_shot"):
        if token in name:
            return False
    return True


def wrapped_deg_delta(current: np.ndarray, other: np.ndarray) -> np.ndarray:
    return (np.asarray(current, dtype=np.float64) - np.asarray(other, dtype=np.float64) + 180.0) % 360.0 - 180.0


def pose_bone_euler(frame_pose: Mapping[str, Any], bone: str) -> np.ndarray | None:
    row = frame_pose.get(bone) or frame_pose.get(str(bone))
    if not isinstance(row, Mapping):
        return None
    return np.asarray((float(row["x"]), float(row["y"]), float(row["z"])), dtype=np.float64)


def pose_pair_velocity_rms(
    poses: Mapping[int, Mapping[str, Any]],
    frame_a: int,
    frame_b: int,
    bones: Sequence[str],
) -> float:
    pa = poses[int(frame_a)]
    pb = poses[int(frame_b)]
    squares: list[float] = []
    for bone in bones:
        if str(bone) in POSE_VELOCITY_SKIP_BONES:
            continue
        ea = pose_bone_euler(pa, str(bone))
        eb = pose_bone_euler(pb, str(bone))
        if ea is None or eb is None:
            continue
        delta = wrapped_deg_delta(ea, eb)
        squares.extend((delta * delta).tolist())
    if not squares:
        return 0.0
    return float(np.sqrt(np.mean(np.asarray(squares, dtype=np.float64))))


def temporal_neighbor_indices(index: int, count: int, wrap: bool) -> tuple[int | None, int | None]:
    if int(count) < 1:
        raise ValueError("clip must contain at least one frame")
    prev = (int(index) - 1) % int(count) if wrap else (int(index) - 1 if int(index) > 0 else None)
    nxt = (int(index) + 1) % int(count) if wrap else (int(index) + 1 if int(index) + 1 < int(count) else None)
    return prev, nxt


def pose_bidirectional_velocity_rms(
    poses: Mapping[int, Mapping[str, Any]],
    *,
    frame: int,
    frames: Sequence[int],
    bones: Sequence[str],
    wrap: bool,
) -> float:
    """Forward (i vs i-1) and backward (i vs i+1) Euler velocity on one skeleton."""
    ordered = [int(item) for item in frames]
    try:
        index = ordered.index(int(frame))
    except ValueError as exc:
        raise ValueError(f"frame {frame} is not in the clip") from exc
    prev, nxt = temporal_neighbor_indices(index, len(ordered), bool(wrap))
    parts: list[float] = []
    if prev is not None:
        parts.append(pose_pair_velocity_rms(poses, ordered[index], ordered[prev], bones))
    if nxt is not None:
        parts.append(pose_pair_velocity_rms(poses, ordered[index], ordered[nxt], bones))
    if not parts:
        return 0.0
    return float(sum(parts) / len(parts))


def clip_pose_velocity_rms(
    poses: Mapping[int, Mapping[str, Any]],
    frames: Sequence[int],
    bones: Sequence[str],
    *,
    wrap: bool,
) -> float:
    ordered = [int(item) for item in frames]
    if not ordered:
        return 0.0
    return float(
        np.mean(
            [
                pose_bidirectional_velocity_rms(
                    poses, frame=frame, frames=ordered, bones=bones, wrap=wrap
                )
                for frame in ordered
            ]
        )
    )


def flyer_frame_is_perch_trap(align: Mapping[str, float], axis_xy: Sequence[float]) -> bool:
    """Standing leftover on a fly plate that should be takeoff or cruise, not landing flare."""
    return (
        abs(float(axis_xy[0])) >= 0.5
        and abs(float(axis_xy[1])) < 0.75
        and abs(float(align["down"])) > 0.85
    )


def flyer_frame_is_flat_trap(align: Mapping[str, float], axis_xy: Sequence[float]) -> bool:
    """Level cruise leftover on a landing-flare plate."""
    return (
        abs(float(axis_xy[1])) >= 0.5
        and abs(float(align["right"])) > 0.95
        and abs(float(align["down"])) < 0.25
    )


def flyer_frame_is_pitch_trap(align: Mapping[str, float], axis_xy: Sequence[float]) -> bool:
    """Still climbing when the plate wants level cruise."""
    return abs(float(axis_xy[1])) < 0.25 and abs(float(align["down"])) > 0.10


def flyer_frame_is_camera_trap(align: Mapping[str, float]) -> bool:
    """Spine points too much at the occupancy camera for a side-view plate."""
    return abs(float(align["forward"])) > 0.40


def mask_bbox_aspect(mask: np.ndarray) -> float:
    occupied = np.asarray(mask, dtype=bool)
    if occupied.ndim != 2:
        raise ValueError("mask must be 2D")
    rows, cols = np.nonzero(occupied)
    if cols.size < 1:
        return 0.0
    width = float(int(cols.max()) - int(cols.min()) + 1)
    height = float(int(rows.max()) - int(rows.min()) + 1)
    return width / max(height, 1.0)


def flight_attitude_needed(
    masks: Sequence[np.ndarray],
    prefix: int,
    suffix: int,
    *,
    min_move_aspect: float = FLIGHT_MOVE_MIN_ASPECT,
    vs_idle: float = FLIGHT_ASPECT_VS_IDLE,
) -> bool:
    """True when move plates are landscape relative to idle perch plates."""
    count = len(masks)
    move = move_frame_positions(count, prefix, suffix)
    idle = list(range(0, int(prefix))) + list(range(count - int(suffix), count))
    if not move or not idle:
        return False
    idle_aspect = float(np.mean([mask_bbox_aspect(masks[index]) for index in idle]))
    move_aspect = float(np.mean([mask_bbox_aspect(masks[index]) for index in move]))
    if idle_aspect <= 1e-9:
        return False
    return move_aspect >= float(min_move_aspect) and move_aspect >= float(vs_idle) * idle_aspect


def closer_aspect(candidates: Sequence[float], target: float) -> int:
    """Index of the candidate whose bbox aspect is nearest the target."""
    if not candidates:
        raise ValueError("closer_aspect needs at least one candidate")
    target_v = float(target)
    errors = [abs(float(value) - target_v) for value in candidates]
    return int(min(range(len(errors)), key=errors.__getitem__))


def flyer_attitude_bones(
    names: Sequence[str],
    parents: Sequence[int | None],
    *,
    root_name: str = "Bone_000",
    generations: int = 4,
) -> list[str]:
    """Spine and first wing/neck forks. Skip Bone_000: rotating it is a whole-body
    spin that shows the belly to the occupancy camera, the same cheat as pitch 90.
    Distal leftover owners cannot invent flight.
    """
    labels = [str(name) for name in names]
    if str(root_name) not in labels:
        return []
    if len(parents) != len(labels):
        raise ValueError("parents must match names")
    children: list[list[int]] = [[] for _ in labels]
    for child, parent in enumerate(parents):
        if parent is None:
            continue
        parent_i = int(parent)
        if parent_i < 0 or parent_i >= len(labels):
            raise ValueError("parent index out of range")
        children[parent_i].append(int(child))
    ordered: list[str] = []
    frontier = [labels.index(str(root_name))]
    for _ in range(int(generations)):
        nxt: list[int] = []
        for node in frontier:
            label = labels[int(node)]
            if label.startswith("Bone_") and label not in ordered:
                ordered.append(label)
            nxt.extend(children[int(node)])
        frontier = nxt
    return [name for name in ordered if name != str(root_name)]


def flyer_spine_chain_bones(
    names: Sequence[str],
    parents: Sequence[int | None],
    *,
    root_name: str = "Bone_000",
    length: int = FLIGHT_SPINE_CHAIN_LENGTH,
) -> list[str]:
    """Longest Bone_* chain under the root, excluding Bone_000.

    Wing forks are not the body axis. A 90° image-plane pitch of this chain
    turns a standing perch into horizontal flight without a whole-body spin.
    """
    labels = [str(name) for name in names]
    if str(root_name) not in labels:
        return []
    if len(parents) != len(labels):
        raise ValueError("parents must match names")
    if int(length) < 1:
        raise ValueError("spine chain length must be positive")
    children: list[list[int]] = [[] for _ in labels]
    for child, parent in enumerate(parents):
        if parent is None:
            continue
        parent_i = int(parent)
        if parent_i < 0 or parent_i >= len(labels):
            raise ValueError("parent index out of range")
        children[parent_i].append(int(child))

    def longest(node: int) -> list[int]:
        bone_kids = [child for child in children[int(node)] if labels[int(child)].startswith("Bone_")]
        if not bone_kids:
            return [int(node)]
        best = max((longest(int(child)) for child in bone_kids), key=len)
        return [int(node), *best]

    chain = longest(labels.index(str(root_name)))
    bones = [labels[index] for index in chain if labels[index] != str(root_name)]
    return bones[: int(length)]


def flyer_visual_body_chain(
    names: Sequence[str],
    parents: Sequence[int | None],
    *,
    catalog: Mapping[str, Any],
) -> list[str]:
    """Tail tip to head tip from the unit anatomy catalog.

    Parent-chain walks and Bone_* index candidates are not anatomy.
    """
    del parents
    return anatomy_visual_body_chain(catalog, names)


def flyer_broad_stroke_search_bones(
    names: Sequence[str],
    parents: Sequence[int | None],
    *,
    catalog: Mapping[str, Any],
) -> list[str]:
    """Trunk plus neck and tail from the catalog. Wings are leftover fill."""
    del parents
    return anatomy_attitude_bones(catalog, names)


def flyer_broad_stroke_frame_ok(
    align: Mapping[str, float],
    axis_xy: Sequence[float],
    belly: Mapping[str, float] | None = None,
    *,
    min_score: float = FLIGHT_BROAD_STROKE_MIN_SCORE,
) -> bool:
    """True when this fly frame's visual body matches that plate's long axis."""
    if flyer_frame_is_camera_trap(align):
        return False
    if not spine_is_image_plane(align):
        return False
    if float(axis_xy[0]) > 0.0 and float(align["rightSigned"]) <= 0.0:
        return False
    if spine_sprite_axis_score(align, axis_xy) < float(min_score):
        return False
    if belly is not None and not belly_is_down(belly):
        return False
    return True


def flyer_broad_stroke_ok(
    rows: Sequence[Mapping[str, Any]],
    *,
    min_score: float = FLIGHT_BROAD_STROKE_MIN_SCORE,
) -> bool:
    """Every move frame must pass. Cruise-only leftover is not a flyer."""
    if not rows:
        return False
    for row in rows:
        if bool(row.get("perchTrap")) or bool(row.get("flatTrap")) or bool(row.get("pitchTrap")):
            return False
        align = row.get("spineAlign") or {}
        axis = row.get("spriteAxis") or ()
        if not flyer_broad_stroke_frame_ok(
            align,
            axis,
            row.get("bellyAlign"),
            min_score=min_score,
        ):
            return False
    return True


def flyer_phase_needs_right_seed(align: Mapping[str, float], axis_xy: Sequence[float]) -> bool:
    """Left-facing fly plate cannot yaw through the camera in small Euler steps."""
    return float(axis_xy[0]) > 0.0 and float(align["rightSigned"]) <= 0.0


def leftover_primary_better(
    before: OccupancyFractions,
    trial: OccupancyFractions,
    *,
    leftover_tie: float = 0.005,
    allow_leftover_growth: bool = True,
) -> bool:
    leftover_drop = float(before.leftover) - float(trial.leftover)
    extra_drop = float(before.extra) - float(trial.extra)
    band = float(leftover_tie)
    if leftover_drop > band:
        return True
    if leftover_drop > 1e-9 and extra_drop >= -1e-12:
        return True
    if allow_leftover_growth:
        return leftover_drop >= -band and extra_drop > 1e-9
    return leftover_drop >= -1e-12 and extra_drop > 1e-9


def flyer_attitude_occupancy_allows(
    before: OccupancyFractions,
    trial: OccupancyFractions,
    *,
    camera_trap: bool,
    trap: bool,
) -> bool:
    """Camera-trap yaw may raise leftover; extra must stay bounded.

    Occupancy leftover of a more profile bird can rise when the spine leaves a
    camera-facing cover pose. That leftover is not a veto. Extra growth is.
    """
    extra_growth = float(trial.extra) - float(before.extra)
    if camera_trap:
        return extra_growth <= float(EPSILON_EXTRA) + 1e-12
    leftover_growth = float(trial.leftover) - float(before.leftover)
    leftover_cap = float(EPSILON_LEFTOVER) * (3.0 if trap else 1.0)
    return leftover_growth <= leftover_cap + 1e-12


def leftover_extend_scale(
    joint_xy: np.ndarray,
    parent_xy: np.ndarray,
    leftover_xy: np.ndarray,
    *,
    scale_min: float = REST_LENGTH_SCALE_MIN,
    scale_max: float = REST_LENGTH_SCALE_MAX,
    empty_scale: float = 1.15,
) -> float:
    """Scale a bone so rest length reaches leftover along the parent→joint axis.

    Leftover pixels are measured relative to the parent joint. Comparing raw
    image coordinates to bone length treats the image origin as the parent.
    """
    joint = np.asarray(joint_xy, dtype=np.float64).reshape(2)
    parent = np.asarray(parent_xy, dtype=np.float64).reshape(2)
    leftover = np.asarray(leftover_xy, dtype=np.float64).reshape(-1, 2)
    axis = joint - parent
    bone_span = float(np.linalg.norm(axis))
    if bone_span < 1e-3 or leftover.shape[0] < 1:
        return float(empty_scale)
    axis_u = axis / bone_span
    proj = (leftover - parent) @ axis_u
    extra = max(0.0, float(np.max(proj)) - bone_span)
    return float(np.clip((bone_span + extra) / bone_span, float(scale_min), float(scale_max)))


LEFTOVER_EXTEND_SKIP_BONES = frozenset({"Bone_000", "Bone_001", "Bone_002", "Bone_003"})


def leftover_extend_target_name(
    unique_region: Sequence[str],
    *,
    insert_name: str = "Bone_FeasibilityInsert",
    skip: Sequence[str] | None = None,
) -> str | None:
    """Pick the distal leftover bone. Spine stretch is not leftover fill."""
    skip_set = {str(name) for name in (LEFTOVER_EXTEND_SKIP_BONES if skip is None else skip)}
    ordered = [str(name) for name in unique_region if str(name) not in skip_set]
    if not ordered:
        return None
    if insert_name in ordered:
        return str(insert_name)
    return ordered[0]


def flyer_camera_trap_search_bones(
    spine: Sequence[str],
    names: Sequence[str],
    *,
    root_name: str = "Bone_000",
) -> list[str]:
    """Camera-trap yaw may use Bone_000. Large belly-spins still fail the down/belly gates."""
    bones = [str(name) for name in spine]
    if str(root_name) in {str(name) for name in names} and str(root_name) not in bones:
        return [str(root_name), *bones]
    return bones


def camera_axis_spans(
    points: np.ndarray,
    right: np.ndarray,
    down: np.ndarray,
    forward: np.ndarray,
) -> dict[str, float]:
    """AABB extents of world points along occupancy-camera axes."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if pts.shape[0] < 1:
        raise ValueError("camera_axis_spans needs at least one point")
    axes = {
        "right": np.asarray(right, dtype=np.float64).reshape(3),
        "down": np.asarray(down, dtype=np.float64).reshape(3),
        "forward": np.asarray(forward, dtype=np.float64).reshape(3),
    }
    spans: dict[str, float] = {}
    for name, axis in axes.items():
        length = float(np.linalg.norm(axis))
        if length <= 1e-12:
            raise ValueError(f"camera {name} axis must be non-zero")
        unit = axis / length
        projected = pts @ unit
        spans[name] = float(projected.max() - projected.min())
    return spans


def side_view_ratio(spans: Mapping[str, float]) -> float:
    """Screen-right span over depth span. Belly-on cards drop this ratio."""
    right = float(spans["right"])
    forward = float(spans["forward"])
    return right / max(forward, 1e-9)


def horizontal_ratio(spans: Mapping[str, float]) -> float:
    """Screen-right span over screen-down span. Head-down dives stay portrait in 3D."""
    right = float(spans["right"])
    down = float(spans["down"])
    return right / max(down, 1e-9)


def spine_camera_align(
    points: np.ndarray,
    right: np.ndarray,
    down: np.ndarray,
    forward: np.ndarray,
) -> dict[str, float]:
    """Unit spine axis dotted with occupancy-camera axes.

    Mesh AABB is dominated by spread wings, so a head-down dive can look
    landscape. The bone chain from chest to neck is the body axis: side-view
    flight is camera-right, perch/dive is camera-down, belly-on is camera-forward.
    """
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if pts.shape[0] < 2:
        raise ValueError("spine_camera_align needs at least two joints")
    axis = pts[-1] - pts[0]
    length = float(np.linalg.norm(axis))
    if length <= 1e-12:
        raise ValueError("spine joints must not coincide")
    unit = axis / length
    axes = {
        "right": np.asarray(right, dtype=np.float64).reshape(3),
        "down": np.asarray(down, dtype=np.float64).reshape(3),
        "forward": np.asarray(forward, dtype=np.float64).reshape(3),
    }
    out: dict[str, float] = {}
    for name, camera_axis in axes.items():
        cam_len = float(np.linalg.norm(camera_axis))
        if cam_len <= 1e-12:
            raise ValueError(f"camera {name} axis must be non-zero")
        signed = float(np.dot(unit, camera_axis / cam_len))
        out[name] = abs(signed)
        out[f"{name}Signed"] = signed
    return out


def spine_is_side_view_flight(align: Mapping[str, float], *, min_right: float = FLIGHT_SPINE_RIGHT_MIN) -> bool:
    right = float(align["right"])
    down = float(align["down"])
    forward = float(align["forward"])
    return right >= float(min_right) and right + 1e-9 >= down and right + 1e-9 >= forward


def spine_level_score(align: Mapping[str, float]) -> float:
    """Higher when the spine is along screen-right and not diving or climbing."""
    return float(align["right"]) - abs(float(align["down"]))


def binary_erode(mask: np.ndarray) -> np.ndarray:
    src = np.asarray(mask, dtype=bool)
    if src.ndim != 2:
        raise ValueError("binary_erode needs a 2D mask")
    padded = np.pad(src, 1, mode="constant", constant_values=False)
    stay = src.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            stay = stay & padded[1 + dy : 1 + dy + src.shape[0], 1 + dx : 1 + dx + src.shape[1]]
    return stay


def mask_body_core(mask: np.ndarray, *, min_frac: float = 0.25) -> np.ndarray:
    """Erode wing-thin pixels so PCA sees the body, not the wing hull."""
    work = np.asarray(mask, dtype=bool)
    start = int(np.count_nonzero(work))
    if start < 16:
        return work
    last = work
    while True:
        nxt = binary_erode(last)
        count = int(np.count_nonzero(nxt))
        if count < 8:
            return last
        if count < float(min_frac) * start:
            return nxt
        last = nxt


def mask_principal_axis_xy(mask: np.ndarray) -> tuple[float, float]:
    """Largest 2D PCA axis of a silhouette, signed toward screen-right.

    Image y is down. A takeoff sprite that climbs toward the top-right has
    negative dy. Cruise sprites are near (1, 0). Landing flares are steeper.
    """
    ys, xs = np.nonzero(np.asarray(mask, dtype=bool))
    if xs.size < 2:
        raise ValueError("mask_principal_axis_xy needs at least two silhouette pixels")
    pts = np.stack((xs.astype(np.float64), ys.astype(np.float64)), axis=1)
    centered = pts - pts.mean(axis=0)
    cov = np.cov(centered, rowvar=False)
    if cov.ndim == 0:
        raise ValueError("mask_principal_axis_xy needs 2D covariance")
    evals, evecs = np.linalg.eigh(np.asarray(cov, dtype=np.float64).reshape(2, 2))
    axis = np.asarray(evecs[:, int(np.argmax(evals))], dtype=np.float64).reshape(2)
    if float(axis[0]) < 0.0:
        axis = -axis
    length = float(np.linalg.norm(axis))
    if length <= 1e-12:
        raise ValueError("mask principal axis must be non-zero")
    return float(axis[0] / length), float(axis[1] / length)


def mask_body_core_axis_xy(mask: np.ndarray) -> tuple[float, float]:
    return mask_principal_axis_xy(mask_body_core(mask))


def spine_is_image_plane(align: Mapping[str, float]) -> bool:
    """True when the spine is not pointing at the occupancy camera."""
    forward = abs(float(align["forward"]))
    return forward <= max(abs(float(align["right"])), abs(float(align["down"]))) + 1e-9


def spine_sprite_axis_score(align: Mapping[str, float], axis_xy: Sequence[float]) -> float:
    """How well the signed spine projection matches the sprite's 2D long axis."""
    proj = np.asarray(
        (float(align["rightSigned"]), float(align["downSigned"])),
        dtype=np.float64,
    )
    axis = np.asarray(axis_xy, dtype=np.float64).reshape(2)
    proj_len = float(np.linalg.norm(proj))
    axis_len = float(np.linalg.norm(axis))
    if proj_len <= 1e-12 or axis_len <= 1e-12:
        raise ValueError("spine_sprite_axis_score needs non-zero projected axes")
    return float(np.dot(proj / proj_len, axis / axis_len))


def remove_axis_component(vector: np.ndarray, axis: np.ndarray) -> np.ndarray:
    offset = np.asarray(vector, dtype=np.float64).reshape(3)
    direction = np.asarray(axis, dtype=np.float64).reshape(3)
    length = float(np.linalg.norm(direction))
    if length <= 1e-12:
        raise ValueError("axis must be non-zero")
    unit = direction / length
    return offset - unit * float(np.dot(offset, unit))


def orthonormal_basis(primary: np.ndarray, secondary: np.ndarray) -> np.ndarray:
    """Columns are primary, secondary (orthogonalized), and their cross product."""
    first = np.asarray(primary, dtype=np.float64).reshape(3)
    first_len = float(np.linalg.norm(first))
    if first_len <= 1e-12:
        raise ValueError("primary axis must be non-zero")
    first = first / first_len
    second = remove_axis_component(secondary, first)
    second_len = float(np.linalg.norm(second))
    if second_len <= 1e-12:
        raise ValueError("secondary axis must be independent of primary")
    second = second / second_len
    third = np.cross(first, second)
    third_len = float(np.linalg.norm(third))
    if third_len <= 1e-12:
        raise ValueError("axis basis must be non-degenerate")
    third = third / third_len
    return np.stack((first, second, third), axis=1)


def rotation_aligning_bases(
    src_primary: np.ndarray,
    src_secondary: np.ndarray,
    dst_primary: np.ndarray,
    dst_secondary: np.ndarray,
) -> np.ndarray:
    """Rotation that maps the source primary/secondary pair onto the destination pair."""
    source = orthonormal_basis(src_primary, src_secondary)
    dest = orthonormal_basis(dst_primary, dst_secondary)
    return dest @ source.T


def rotation_mapping_vector(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Minimal rotation that maps src onto dst. Fail-closed on zero vectors."""
    source = np.asarray(src, dtype=np.float64).reshape(3)
    dest = np.asarray(dst, dtype=np.float64).reshape(3)
    source_len = float(np.linalg.norm(source))
    dest_len = float(np.linalg.norm(dest))
    if source_len <= 1e-12 or dest_len <= 1e-12:
        raise ValueError("rotation_mapping_vector needs non-zero src and dst")
    source = source / source_len
    dest = dest / dest_len
    cosine = float(np.clip(np.dot(source, dest), -1.0, 1.0))
    if cosine > 1.0 - 1e-9:
        return np.eye(3, dtype=np.float64)
    if cosine < -1.0 + 1e-9:
        helper = np.array((1.0, 0.0, 0.0), dtype=np.float64)
        axis = np.cross(source, helper)
        if float(np.linalg.norm(axis)) <= 1e-8:
            helper = np.array((0.0, 1.0, 0.0), dtype=np.float64)
            axis = np.cross(source, helper)
        axis = axis / float(np.linalg.norm(axis))
        return (2.0 * np.outer(axis, axis)) - np.eye(3, dtype=np.float64)
    skew_axis = np.cross(source, dest)
    skew = np.array(
        (
            (0.0, -skew_axis[2], skew_axis[1]),
            (skew_axis[2], 0.0, -skew_axis[0]),
            (-skew_axis[1], skew_axis[0], 0.0),
        ),
        dtype=np.float64,
    )
    sine_sq = float(np.dot(skew_axis, skew_axis))
    return np.eye(3, dtype=np.float64) + skew + (skew @ skew) * ((1.0 - cosine) / sine_sq)


def rotate_points_about_pivot(
    points: np.ndarray,
    rotation: np.ndarray,
    pivot: np.ndarray,
) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    rot = np.asarray(rotation, dtype=np.float64).reshape(3, 3)
    origin = np.asarray(pivot, dtype=np.float64).reshape(3)
    return (pts - origin) @ rot.T + origin


def require_unit3(vector: np.ndarray, name: str) -> np.ndarray:
    axis = np.asarray(vector, dtype=np.float64).reshape(3)
    length = float(np.linalg.norm(axis))
    if length <= 1e-12:
        raise ValueError(f"{name} must be non-zero")
    return axis / length


def assign_opposite_wing_spans(
    src_a: np.ndarray,
    src_b: np.ndarray,
    span: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Map labeled wings onto opposite span directions without crossing."""
    axis = require_unit3(span, "wing span axis")
    left = np.asarray(src_a, dtype=np.float64).reshape(3)
    right = np.asarray(src_b, dtype=np.float64).reshape(3)
    same = float(np.dot(left, axis) + np.dot(right, -axis))
    crossed = float(np.dot(left, -axis) + np.dot(right, axis))
    if same >= crossed:
        return axis, -axis
    return -axis, axis


def symmetric_limb_destinations(
    src_a: np.ndarray,
    src_b: np.ndarray,
    *,
    spine: np.ndarray,
    ventral: np.ndarray,
    pole: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Mirrored T-pose aims for one bilateral pair.

    Lateral is spine × ventral. Wings raise to dorsal±lateral. Legs spread
    to ventral±lateral. Assignment only uncrosses.
    """
    spine_u = require_unit3(spine, "spine")
    ventral_u = require_unit3(ventral, "ventral")
    if pole == "dorsal":
        pole_axis = -ventral_u
    elif pole == "ventral":
        pole_axis = ventral_u
    else:
        raise ValueError(f"T-pose pole must be dorsal or ventral, not {pole!r}")
    lateral = require_unit3(np.cross(spine_u, ventral_u), "sagittal lateral (spine × ventral)")
    dest_plus = require_unit3(pole_axis + lateral, "T-pose +lateral limb")
    dest_minus = require_unit3(pole_axis - lateral, "T-pose -lateral limb")
    left = np.asarray(src_a, dtype=np.float64).reshape(3)
    right = np.asarray(src_b, dtype=np.float64).reshape(3)
    same = float(np.dot(left, dest_plus) + np.dot(right, dest_minus))
    crossed = float(np.dot(left, dest_minus) + np.dot(right, dest_plus))
    if same >= crossed:
        return dest_plus, dest_minus
    return dest_minus, dest_plus


def symmetric_raised_wing_destinations(
    src_a: np.ndarray,
    src_b: np.ndarray,
    *,
    spine: np.ndarray,
    ventral: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Both wings raised equally, mirrored across the sagittal plane."""
    return symmetric_limb_destinations(
        src_a, src_b, spine=spine, ventral=ventral, pole="dorsal"
    )


def spread_labeled_wing_vertices(
    positions: np.ndarray,
    *,
    origins: Mapping[str, np.ndarray],
    owner_names: Sequence[str],
    catalog: Mapping[str, Any],
    names: Sequence[str],
    destinations: tuple[np.ndarray, np.ndarray],
    group_a: str = "wing_a",
    group_b: str = "wing_b",
) -> dict[str, Any]:
    """Rotate verts owned by a catalog bilateral pair onto given destinations."""
    pts = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
    if len(owner_names) != pts.shape[0]:
        raise ValueError("limb spread owner list must match vertex count")
    if len(destinations) != 2:
        raise ValueError("limb spread needs exactly two destinations")
    out = pts.copy()
    chain_a = anatomy_wing_chain(catalog, group_a, names)
    chain_b = anatomy_wing_chain(catalog, group_b, names)
    missing = [bone for bone in (chain_a[0], chain_a[-1], chain_b[0], chain_b[-1]) if bone not in origins]
    if missing:
        raise ValueError(f"limb spread missing joint origins {missing}")
    dst_a = require_unit3(destinations[0], f"{group_a} destination")
    dst_b = require_unit3(destinations[1], f"{group_b} destination")
    report: dict[str, Any] = {"limbs": {}}
    for group, chain, dest in ((str(group_a), chain_a, dst_a), (str(group_b), chain_b, dst_b)):
        allowed = {str(bone) for bone in chain}
        mask = np.asarray([str(name) in allowed for name in owner_names], dtype=bool)
        count = int(np.count_nonzero(mask))
        if count < 8:
            raise ValueError(f"anatomy group {group} owns too few vertices to spread ({count})")
        src = np.asarray(origins[chain[-1]], dtype=np.float64) - np.asarray(
            origins[chain[0]], dtype=np.float64
        )
        rotation = rotation_mapping_vector(src, dest)
        shoulder = np.asarray(origins[chain[0]], dtype=np.float64)
        out[mask] = rotate_points_about_pivot(out[mask], rotation, shoulder)
        report["limbs"][group] = {
            "shoulder": chain[0],
            "tip": chain[-1],
            "vertices": count,
            "destination": dest.tolist(),
        }
    report["wings"] = dict(report["limbs"])
    report["positions"] = out
    return report


def tpose_stretched_bridge_faces(
    perch: np.ndarray,
    tpose: np.ndarray,
    faces: np.ndarray,
    owner_names: Sequence[str],
    catalog: Mapping[str, Any],
    *,
    stretch_ratio: float = TPOSE_BRIDGE_STRETCH_RATIO,
) -> dict[str, Any]:
    """Faces whose mixed-anatomy edges exploded from perch to T-pose.

    Shoulder wing-trunk faces stay: they do not stretch. Wing-tip welded to
    the body, or wing welded to the other wing, does stretch and is cut.
    """
    bind = np.asarray(perch, dtype=np.float64).reshape(-1, 3)
    posed = np.asarray(tpose, dtype=np.float64).reshape(-1, 3)
    triangles = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    if bind.shape != posed.shape:
        raise ValueError("T-pose snip perch and tpose vertex counts must match")
    if len(owner_names) != bind.shape[0]:
        raise ValueError("T-pose snip owner list must match vertex count")
    if triangles.shape[0] < 1:
        raise ValueError("T-pose snip needs triangle faces")
    ratio = float(stretch_ratio)
    if not math.isfinite(ratio) or ratio <= 1.0:
        raise ValueError("T-pose bridge stretch ratio must be > 1")
    groups = anatomy_bone_to_group(catalog)
    owner_group = []
    for name in owner_names:
        group = groups.get(str(name))
        if group is None:
            raise ValueError(f"T-pose snip owner {name!r} is not in the anatomy catalog")
        owner_group.append(group)
    cut: list[int] = []
    samples: list[dict[str, Any]] = []
    for face_i, corners in enumerate(triangles):
        mixed_stretch = False
        ids = (int(corners[0]), int(corners[1]), int(corners[2]))
        for i in range(3):
            left, right = ids[i], ids[(i + 1) % 3]
            if owner_group[left] == owner_group[right]:
                continue
            perch_len = float(np.linalg.norm(bind[left] - bind[right]))
            tpose_len = float(np.linalg.norm(posed[left] - posed[right]))
            if perch_len <= 1e-12:
                stretched = tpose_len > 1e-8
                measured = float("inf") if stretched else 0.0
            else:
                measured = tpose_len / perch_len
                stretched = measured >= ratio
            if stretched:
                mixed_stretch = True
                if len(samples) < 16:
                    samples.append(
                        {
                            "face": int(face_i),
                            "groups": [owner_group[left], owner_group[right]],
                            "ratio": float(measured),
                        }
                    )
        if mixed_stretch:
            cut.append(int(face_i))
    fraction = float(len(cut)) / float(triangles.shape[0])
    if fraction > float(TPOSE_BRIDGE_FACE_FRACTION_CAP):
        raise ValueError(
            f"T-pose snip would delete {fraction:.3f} of faces; "
            f"cap is {TPOSE_BRIDGE_FACE_FRACTION_CAP}"
        )
    return {
        "faceIndices": np.asarray(cut, dtype=np.int64),
        "fraction": fraction,
        "samples": samples,
        "faceCount": int(triangles.shape[0]),
        "cutCount": int(len(cut)),
        "stretchRatio": ratio,
    }


def bind_chest_toward_camera(camera_forward: np.ndarray) -> np.ndarray:
    """Standing occupancy: the pale chest faces the camera. That is fly-belly.

    A Y-cut below the spine selects feet, not chest. Mapping feet onto
    screen-down leaves the chest aimed at the camera. Map camera-forward
    onto camera-down so the side of the bird faces the plate.
    """
    axis = np.asarray(camera_forward, dtype=np.float64).reshape(3)
    length = float(np.linalg.norm(axis))
    if length <= 1e-12:
        raise ValueError("camera_forward must be non-zero")
    return axis / length


def belly_camera_align(
    offset: np.ndarray,
    down: np.ndarray,
    forward: np.ndarray,
) -> dict[str, float]:
    """Signed ventral direction vs occupancy camera.

    Use a vector from the spine toward rest-space lower (belly/leg) vertices,
    with the spine axis removed so this is roll, not pitch. Positive down is
    belly toward the bottom of the plate. Positive forward is belly toward
    the occupancy camera — the remaining cheat after a horizontal spine.
    """
    vector = np.asarray(offset, dtype=np.float64).reshape(3)
    length = float(np.linalg.norm(vector))
    if length <= 1e-12:
        raise ValueError("belly offset must be non-zero")
    unit = vector / length
    axes = {
        "down": np.asarray(down, dtype=np.float64).reshape(3),
        "forward": np.asarray(forward, dtype=np.float64).reshape(3),
    }
    out: dict[str, float] = {}
    for name, camera_axis in axes.items():
        cam_len = float(np.linalg.norm(camera_axis))
        if cam_len <= 1e-12:
            raise ValueError(f"camera {name} axis must be non-zero")
        out[name] = float(np.dot(unit, camera_axis / cam_len))
    return out


def belly_is_down(align: Mapping[str, float], *, min_down: float = FLIGHT_BELLY_DOWN_MIN) -> bool:
    down = float(align["down"])
    forward = float(align["forward"])
    return down >= float(min_down) and down + 1e-9 >= abs(forward)


def side_view_flight_better(
    before: OccupancyFractions,
    trial: OccupancyFractions,
    *,
    before_spans: Mapping[str, float],
    trial_spans: Mapping[str, float],
    sprite_aspect: float,
    before_aspect: float,
    trial_aspect: float,
    leftover_growth_cap: float = 0.0,
    ratio_slack: float = SIDE_VIEW_RATIO_SLACK,
    prefer_aspect: bool = False,
) -> bool:
    """Keep a fly pose that fills leftover / matches plate aspect without going belly-on.

    Occupancy leftover of a belly-on dive can beat a thin side-view flyer on the
    same landscape plate. Reject any trial that shortens camera-right relative
    to camera-forward (body turning into the occupancy camera).
    """
    if side_view_ratio(trial_spans) + float(ratio_slack) < side_view_ratio(before_spans):
        return False
    leftover_drop = float(before.leftover) - float(trial.leftover)
    extra_drop = float(before.extra) - float(trial.extra)
    leftover_growth = -leftover_drop
    aspect_err_before = abs(float(before_aspect) - float(sprite_aspect))
    aspect_err_trial = abs(float(trial_aspect) - float(sprite_aspect))
    if leftover_growth > float(leftover_growth_cap) + 1e-12:
        return False
    if prefer_aspect:
        if aspect_err_trial + 1e-9 < aspect_err_before:
            return True
        return leftover_drop > 1e-9 and aspect_err_trial <= aspect_err_before + 1e-9
    if leftover_drop > 1e-9:
        return True
    if aspect_err_trial + 1e-9 < aspect_err_before:
        return True
    return leftover_drop >= -1e-12 and extra_drop > 1e-9


def rotation_matrix_deg(axis: np.ndarray, degrees: float) -> np.ndarray:
    vector = np.asarray(axis, dtype=np.float64).reshape(3)
    length = float(np.linalg.norm(vector))
    if length <= 1e-12:
        raise ValueError("rotation axis must be non-zero")
    unit = vector / length
    radians = math.radians(float(degrees))
    cosine = math.cos(radians)
    sine = math.sin(radians)
    x, y, z = (float(unit[0]), float(unit[1]), float(unit[2]))
    cross = np.asarray(
        ((0.0, -z, y), (z, 0.0, -x), (-y, x, 0.0)),
        dtype=np.float64,
    )
    identity = np.eye(3, dtype=np.float64)
    return identity + sine * cross + (1.0 - cosine) * (cross @ cross)


def orbit_camera_vectors(
    right: np.ndarray,
    down: np.ndarray,
    *,
    yaw_deg: float,
    pitch_deg: float,
    world_up: Sequence[float] = (0.0, 1.0, 0.0),
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Rotate the view around world-up (yaw) then camera-right (pitch)."""
    right_v = np.asarray(right, dtype=np.float64).reshape(3)
    down_v = np.asarray(down, dtype=np.float64).reshape(3)
    up_axis = np.asarray(world_up, dtype=np.float64).reshape(3)
    up_len = float(np.linalg.norm(up_axis))
    if up_len <= 1e-12:
        raise ValueError("world_up must be non-zero")
    up_axis = up_axis / up_len
    rotated_right = rotation_matrix_deg(up_axis, yaw_deg) @ right_v
    rotated_down = rotation_matrix_deg(up_axis, yaw_deg) @ down_v
    if abs(float(pitch_deg)) > 1e-12:
        pitch = rotation_matrix_deg(rotated_right, pitch_deg)
        rotated_down = pitch @ rotated_down
    right_n = rotated_right / max(float(np.linalg.norm(rotated_right)), 1e-12)
    down_n = rotated_down - right_n * float(np.dot(rotated_down, right_n))
    down_n = down_n / max(float(np.linalg.norm(down_n)), 1e-12)
    up_n = -down_n
    forward_n = np.cross(up_n, right_n)
    forward_n = forward_n / max(float(np.linalg.norm(forward_n)), 1e-12)
    return right_n, down_n, up_n, forward_n


def orbit_projection(
    *,
    right: np.ndarray,
    down: np.ndarray,
    offset: np.ndarray,
    px_per_world: np.ndarray,
    pivot: np.ndarray,
    yaw_deg: float,
    pitch_deg: float,
    world_up: Sequence[float] = (0.0, 1.0, 0.0),
) -> dict[str, Any]:
    """New projection that keeps the pivot on the same screen pixel."""
    right_v = np.asarray(right, dtype=np.float64).reshape(3)
    down_v = np.asarray(down, dtype=np.float64).reshape(3)
    offset_v = np.asarray(offset, dtype=np.float64).reshape(2)
    px = np.asarray(px_per_world, dtype=np.float64).reshape(2)
    pivot_v = np.asarray(pivot, dtype=np.float64).reshape(3)
    screen = np.asarray(
        (
            float(np.dot(pivot_v, right_v) * px[0] + offset_v[0]),
            float(np.dot(pivot_v, down_v) * px[1] + offset_v[1]),
        ),
        dtype=np.float64,
    )
    right_n, down_n, up_n, forward_n = orbit_camera_vectors(
        right_v,
        down_v,
        yaw_deg=yaw_deg,
        pitch_deg=pitch_deg,
        world_up=world_up,
    )
    offset_n = np.asarray(
        (
            float(screen[0] - np.dot(pivot_v, right_n) * px[0]),
            float(screen[1] - np.dot(pivot_v, down_n) * px[1]),
        ),
        dtype=np.float64,
    )
    return {
        "right": right_n,
        "down": down_n,
        "up": up_n,
        "forward": forward_n,
        "offset": offset_n,
        "pxPerWorld": px,
        "yawDeg": float(yaw_deg),
        "pitchDeg": float(pitch_deg),
        "screenPivot": screen,
    }


def vision_check_frame_positions(frame_count: int, prefix: int, suffix: int) -> list[int]:
    """Idle, takeoff, mid-move, land, last idle. Occupancy leftover is not this list."""
    count = int(frame_count)
    chosen = [0]
    move = move_frame_positions(count, prefix, suffix)
    if move:
        chosen.extend((move[0], move[len(move) // 2], move[-1]))
    last = count - 1
    if last >= 0:
        chosen.append(last)
    ordered: list[int] = []
    for index in chosen:
        value = int(index)
        if 0 <= value < count and value not in ordered:
            ordered.append(value)
    return ordered


def occupancy_fractions(
    leftover: np.ndarray,
    extra: np.ndarray,
    sprite: np.ndarray,
) -> OccupancyFractions:
    miss = np.asarray(leftover, dtype=bool)
    extra_mask = np.asarray(extra, dtype=bool)
    target = np.asarray(sprite, dtype=bool)
    if miss.shape != extra_mask.shape or miss.shape != target.shape:
        raise ValueError("leftover, extra, and sprite masks must match")
    sprite_pixels = int(np.count_nonzero(target))
    leftover_pixels = int(np.count_nonzero(miss))
    extra_pixels = int(np.count_nonzero(extra_mask))
    if sprite_pixels < 1:
        raise ValueError("sprite occupancy is empty; leftover fractions are undefined")
    return OccupancyFractions(
        leftover=float(leftover_pixels) / float(sprite_pixels),
        extra=float(extra_pixels) / float(sprite_pixels),
        sprite_pixels=sprite_pixels,
        leftover_pixels=leftover_pixels,
        extra_pixels=extra_pixels,
    )


def fractions_from_masks(
    target_mask: np.ndarray,
    predicted_mask: np.ndarray,
    *,
    predicted_threshold: float = PREDICTED_ALPHA_THRESHOLD,
) -> OccupancyFractions:
    leftover = leftover_mask(
        target_mask,
        predicted_mask,
        None,
        predicted_threshold=float(predicted_threshold),
    )
    extra = extra_predicted_mask(
        target_mask,
        predicted_mask,
        None,
        predicted_threshold=float(predicted_threshold),
    )
    sprite = np.asarray(target_mask, dtype=np.float32) > 0.5
    return occupancy_fractions(leftover, extra, sprite)


def clip_wide_mean(rows: Sequence[OccupancyFractions]) -> OccupancyFractions:
    if not rows:
        raise ValueError("clip-wide mean needs at least one frame")
    leftover = float(np.mean([row.leftover for row in rows]))
    extra = float(np.mean([row.extra for row in rows]))
    sprite_pixels = int(sum(row.sprite_pixels for row in rows))
    leftover_pixels = int(sum(row.leftover_pixels for row in rows))
    extra_pixels = int(sum(row.extra_pixels for row in rows))
    return OccupancyFractions(
        leftover=leftover,
        extra=extra,
        sprite_pixels=sprite_pixels,
        leftover_pixels=leftover_pixels,
        extra_pixels=extra_pixels,
    )


def is_feasible(fractions: OccupancyFractions) -> bool:
    return (
        float(fractions.leftover) <= FEASIBLE_LEFTOVER
        and float(fractions.extra) <= FEASIBLE_EXTRA
    )


def accept_surgery(
    before: OccupancyFractions,
    after: OccupancyFractions,
    *,
    strain_before: float,
    strain_after: float,
    epsilon_leftover: float = EPSILON_LEFTOVER,
    epsilon_extra: float = EPSILON_EXTRA,
    epsilon_strain: float = EPSILON_STRAIN,
) -> dict[str, Any]:
    leftover_drop = float(before.leftover) - float(after.leftover)
    extra_growth = float(after.extra) - float(before.extra)
    strain_growth = float(strain_after) - float(strain_before)
    ok = (
        leftover_drop >= float(epsilon_leftover)
        and extra_growth <= float(epsilon_extra)
        and strain_growth <= float(epsilon_strain)
    )
    return {
        "accepted": bool(ok),
        "leftoverDrop": leftover_drop,
        "extraGrowth": extra_growth,
        "strainGrowth": strain_growth,
        "epsilonLeftover": float(epsilon_leftover),
        "epsilonExtra": float(epsilon_extra),
        "epsilonStrain": float(epsilon_strain),
        "before": {"leftover": float(before.leftover), "extra": float(before.extra)},
        "after": {"leftover": float(after.leftover), "extra": float(after.extra)},
        "strainBefore": float(strain_before),
        "strainAfter": float(strain_after),
    }


def argmax_round(
    candidates: Sequence[Mapping[str, Any]],
    *,
    leftover_tie: float = EPSILON_LEFTOVER,
    extra_tie: float = EPSILON_EXTRA,
    strain_tie: float = EPSILON_STRAIN,
) -> dict[str, Any]:
    """Lexicographic leftover, extra, strain. Original plus accepted rounds only."""
    if not candidates:
        raise ValueError("argmax needs at least the original round")
    rows = []
    for item in candidates:
        if not bool(item.get("accepted", False)) and str(item.get("roundId")) != "round_00":
            continue
        leftover = float(item["leftover"])
        extra = float(item["extra"])
        strain = float(item["strain"])
        for name, value in (("leftover", leftover), ("extra", extra), ("strain", strain)):
            if not math.isfinite(value):
                raise ValueError(f"argmax {name} must be finite")
        rows.append(item)
    if not rows:
        raise RuntimeError("argmax has no accepted rounds or original")

    leftover_band = float(leftover_tie)
    extra_band = float(extra_tie)
    strain_band = float(strain_tie)

    def _cmp(left: Mapping[str, Any], right: Mapping[str, Any]) -> int:
        leftover_delta = float(left["leftover"]) - float(right["leftover"])
        if abs(leftover_delta) > leftover_band:
            return -1 if leftover_delta < 0.0 else 1
        extra_delta = float(left["extra"]) - float(right["extra"])
        if abs(extra_delta) > extra_band:
            return -1 if extra_delta < 0.0 else 1
        strain_delta = float(left["strain"]) - float(right["strain"])
        if abs(strain_delta) > strain_band:
            return -1 if strain_delta < 0.0 else 1
        left_id = str(left["roundId"])
        right_id = str(right["roundId"])
        if left_id < right_id:
            return -1
        if left_id > right_id:
            return 1
        return 0

    chosen = sorted(rows, key=cmp_to_key(_cmp))[0]
    return dict(chosen)


def _candidate_facing(item: Mapping[str, Any]) -> float:
    return float(item.get("facingScore") or 0.0)


def screen_right_candidates(
    candidates: Sequence[Mapping[str, Any]],
    *,
    min_facing: float = PROFILE_MIN_PROFILE_FACING,
) -> list[dict[str, Any]]:
    if not candidates:
        raise ValueError("camera classification needs at least one candidate")
    floor = float(min_facing)
    return [
        dict(item)
        for item in candidates
        if _candidate_facing(item) >= floor
    ]


def pick_highest_facing_profile(
    candidates: Sequence[Mapping[str, Any]],
    *,
    min_facing: float = PROFILE_MIN_PROFILE_FACING,
) -> dict[str, Any] | None:
    """One scorer: highest facing among cameras that pass the profile floor."""
    pool = screen_right_candidates(candidates, min_facing=min_facing)
    if not pool:
        return None
    return max(
        pool,
        key=lambda item: (
            _candidate_facing(item),
            float(item.get("silhouetteScore") or item.get("iou") or 0.0),
            -abs(float(item.get("yawDeg") or 0.0)),
        ),
    )


def classify_camera_from_init(
    init: Mapping[str, Any],
    *,
    rear_veto: float = PROFILE_REAR_FACING_VETO,
    min_facing: float = PROFILE_MIN_PROFILE_FACING,
) -> dict[str, Any]:
    """Classify the stored profile camera. Does not raster."""
    selection = init.get("selection")
    best = init.get("best")
    candidates = init.get("candidates")
    if not isinstance(selection, Mapping):
        raise ValueError("profile init is missing selection")
    if not isinstance(best, Mapping):
        raise ValueError("profile init is missing best")
    if not isinstance(candidates, Sequence) or not candidates:
        raise ValueError("profile init is missing candidates")
    selected_facing = float(
        selection.get("selectedFacingScore")
        if selection.get("selectedFacingScore") is not None
        else best.get("facingScore") or 0.0
    )
    selected_yaw = float(
        selection.get("selectedYawDeg")
        if selection.get("selectedYawDeg") is not None
        else best.get("yawDeg") or 0.0
    )
    profile = pick_highest_facing_profile(candidates, min_facing=min_facing)
    if selected_facing < float(rear_veto):
        if profile is None:
            primary = CLASS_CAMERA_MISMATCH_UNRESOLVED
        else:
            primary = CLASS_CAMERA_MISMATCH
    else:
        primary = CLASS_CAMERA_OK
    return {
        "primaryClass": primary,
        "selectedFacing": selected_facing,
        "selectedYawDeg": selected_yaw,
        "profileCandidate": None
        if profile is None
        else {
            "yawDeg": float(profile["yawDeg"]),
            "rollDeg": float(profile.get("rollDeg") or 0.0),
            "facingScore": _candidate_facing(profile),
            "silhouetteScore": float(profile.get("silhouetteScore") or 0.0),
        },
        "rearVeto": float(rear_veto),
        "minFacing": float(min_facing),
    }


def classify_occupancy_body(
    *,
    leftover_near: bool,
    leftover_far: bool,
    unassigned_far: bool,
    geometry_projects_near: bool,
    debt_helps: bool,
    owner_agrees: bool,
    unique_owner: str | None,
) -> str:
    """Causal body class after camera is already OK. One primary class."""
    if leftover_far and unassigned_far and not geometry_projects_near:
        return CLASS_MISSING_GEOMETRY
    if leftover_far and unassigned_far and geometry_projects_near:
        return CLASS_MISSING_JOINT
    if debt_helps:
        return CLASS_POSE_SEARCH_DEBT
    if leftover_near and unique_owner and not owner_agrees:
        return CLASS_WRONG_OWNER
    if leftover_near:
        return CLASS_BODY_INFEASIBLE_REST
    return CLASS_FEASIBLE


def next_body_class(tried: Sequence[str]) -> str | None:
    seen = {str(name) for name in tried}
    for name in BODY_OPERATOR_ORDER:
        if name not in seen:
            return name
    return None


def agreed_rebind_vertices(
    vote: Mapping[str, Any],
    target_name: str | None,
) -> tuple[list[int], str | None]:
    """Rebind agreed leftover verts whose owner is not the attributed bone.

    Vertices that disagree across frames stay unchanged. Disagreement is not a
    reason to abort the whole operator.
    """
    if not target_name:
        return [], "no unique leftover owner"
    agreed = vote.get("agreed") or {}
    verts = [int(vertex) for vertex, owner in agreed.items() if str(owner) != str(target_name)]
    if not verts:
        return [], "rebind vertex set is empty"
    return verts, None


def leftover_flip_is_blendshape(*, clip_name: str, leftover_far: bool) -> bool:
    """A leftover-direction flip on a still Idle plate can mean a second rest.

    Move leftover that flips across the clip is walking motion, not blendshape.
    Occupancy rest sculpt does not use this: it moves each vertex toward the
    nearest leftover or sprite pixel on frame 0.
    """
    return str(clip_name) == "idle" and not bool(leftover_far)


OCCUPANCY_DELTA_FRACTION = 0.5
OCCUPANCY_REST_FILL_MAX_ASSIGN_PX = 24.0
OCCUPANCY_REST_FILL_TIGHT_PX = 3.0
OCCUPANCY_REST_EXTRA_FACING_PX = 2.0
OCCUPANCY_REST_UNIQUE_MIN_FRAC = 0.10
UNIQUE_REGION_VOLUME_SHRINK_FRAC = 0.15


def unique_region_bones_from_pixels(
    xs: np.ndarray,
    ys: np.ndarray,
    joints_xy: Mapping[str, tuple[float, float]],
    *,
    min_frac: float = OCCUPANCY_REST_UNIQUE_MIN_FRAC,
) -> list[str]:
    """Nearest-joint unique region for leftover or extra pixels.

    A leftover or extra blob belongs to the joints that sit nearest those
    pixels. Occupancy rest then moves only verts whose dominant skin owner
    is one of those joints, instead of the whole mesh rim.
    """
    if not joints_xy:
        raise ValueError("unique-region bones need at least one joint")
    xs_v = np.asarray(xs, dtype=np.float64).reshape(-1)
    ys_v = np.asarray(ys, dtype=np.float64).reshape(-1)
    if xs_v.shape != ys_v.shape:
        raise ValueError("xs and ys must match")
    if xs_v.size < 1:
        return []
    names = [str(name) for name in joints_xy]
    joint_xy = np.asarray([joints_xy[name] for name in names], dtype=np.float64).reshape(-1, 2)
    counts = np.zeros(len(names), dtype=np.int64)
    for x, y in zip(xs_v, ys_v):
        dist2 = (joint_xy[:, 0] - float(x)) ** 2 + (joint_xy[:, 1] - float(y)) ** 2
        counts[int(np.argmin(dist2))] += 1
    total = int(counts.sum())
    if total < 1:
        return []
    floor = max(1, int(math.ceil(float(min_frac) * float(total))))
    peak = int(counts.max())
    ranked = sorted(
        (
            (int(count), names[index])
            for index, count in enumerate(counts)
            if int(count) >= floor or int(count) == peak
        ),
        key=lambda item: (-item[0], item[1]),
    )
    return [name for _count, name in ranked]


def occupancy_assigned_unique_bones(
    assigned_counts: Mapping[str, Any],
    unique_owner: str | None,
    *,
    min_frac: float = OCCUPANCY_REST_UNIQUE_MIN_FRAC,
) -> list[str]:
    """Leftover unique-region bones from occupancy assignment, not nearest joint.

    Nearest-joint attribution can pick a neighbor of the leftover blob.
    Occupancy assignment attributes leftover pixels to unique skin lanes.
    """
    counts = {
        str(name): int(count)
        for name, count in dict(assigned_counts or {}).items()
        if int(count) > 0
    }
    chosen: list[str] = []
    total = int(sum(counts.values()))
    if total > 0:
        floor = max(1, int(math.ceil(float(min_frac) * float(total))))
        peak = int(max(counts.values()))
        chosen = [name for name, count in counts.items() if int(count) >= floor or int(count) == peak]
    owner = str(unique_owner or "")
    if owner and owner not in chosen:
        chosen.append(owner)
    return chosen


def unique_region_centroid_shrink_deltas(
    rest: np.ndarray,
    owner_names: Sequence[str],
    unique_bones: Sequence[str],
    *,
    frac: float = UNIQUE_REGION_VOLUME_SHRINK_FRAC,
    vert_allow: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Move unique extra verts toward their unique-bone rest centroid.

    Extra on a fat rest is volume, not rim pixels. Bone-length scale and
    extra-facing image-plane rest do not remove that volume. Unique-region
    verts contract in rest space toward the centroid of that bone's verts.
    """
    points = np.asarray(rest, dtype=np.float64).reshape(-1, 3)
    names = [str(name) for name in owner_names]
    if len(names) != int(points.shape[0]):
        raise ValueError("owner_names must match rest vertex count")
    amount = float(frac)
    if not math.isfinite(amount) or amount <= 0.0 or amount > 1.0:
        raise ValueError("volume shrink frac must be in (0, 1]")
    allowed = {str(name) for name in unique_bones}
    if not allowed:
        raise ValueError("unique-region volume shrink needs at least one bone")
    centroids: dict[str, np.ndarray] = {}
    for bone in allowed:
        idxs = [index for index, name in enumerate(names) if name == bone]
        if not idxs:
            continue
        centroids[bone] = points[idxs].mean(axis=0)
    deltas = np.zeros_like(points)
    affected = np.zeros((points.shape[0],), dtype=bool)
    allow = None if vert_allow is None else np.asarray(vert_allow, dtype=bool).reshape(-1)
    if allow is not None and allow.shape[0] != points.shape[0]:
        raise ValueError("vert_allow must match rest vertex count")
    for index, name in enumerate(names):
        if allow is not None and not bool(allow[index]):
            continue
        origin = centroids.get(name)
        if origin is None:
            continue
        deltas[index] = amount * (origin - points[index])
        affected[index] = True
    return deltas, affected


def extra_on_vertex_mask(
    xs: np.ndarray,
    ys: np.ndarray,
    extra: np.ndarray,
) -> np.ndarray:
    """True for verts whose projection lands on an extra pixel."""
    extra_mask = np.asarray(extra, dtype=bool)
    if extra_mask.ndim != 2:
        raise ValueError("extra must be 2D")
    height, width = extra_mask.shape
    xs_v = np.asarray(xs, dtype=np.float64).reshape(-1)
    ys_v = np.asarray(ys, dtype=np.float64).reshape(-1)
    if xs_v.shape != ys_v.shape:
        raise ValueError("xs and ys must match")
    on_extra = np.zeros((xs_v.shape[0],), dtype=bool)
    for index, (x, y) in enumerate(zip(xs_v, ys_v)):
        px = int(round(float(x)))
        py = int(round(float(y)))
        if 0 <= px < width and 0 <= py < height and bool(extra_mask[py, px]):
            on_extra[index] = True
    return on_extra

def apply_rest_space_deltas(
    rest: np.ndarray,
    deltas: np.ndarray,
    affected: np.ndarray,
    *,
    max_displacement: float,
    skip_cap: float = LBS_SKIP_FRACTION_CAP,
) -> dict[str, Any]:
    """Apply rest-space deltas. Skip verts whose step exceeds max_displacement."""
    points = np.asarray(rest, dtype=np.float64).reshape(-1, 3)
    step = np.asarray(deltas, dtype=np.float64).reshape(-1, 3)
    mask = np.asarray(affected, dtype=bool).reshape(-1)
    if points.shape[0] != step.shape[0] or points.shape[0] != mask.shape[0]:
        raise ValueError("rest-space delta arrays must share a vertex count")
    affected_count = int(np.count_nonzero(mask))
    if affected_count < 1:
        raise ValueError("rest-space affected vertex set is empty")
    cap = float(max_displacement)
    if not math.isfinite(cap) or cap <= 0.0:
        raise ValueError("max_displacement must be positive and finite")
    out = points.copy()
    skipped = 0
    moved = 0
    for index in np.nonzero(mask)[0]:
        disp = float(np.linalg.norm(step[index]))
        if disp > cap:
            skipped += 1
            continue
        out[index] = points[index] + step[index]
        moved += 1
    if skip_fraction_reject(skipped, affected_count, cap=float(skip_cap)):
        return {
            "rejected": True,
            "reason": "displacement_cap",
            "skipped": skipped,
            "affected": affected_count,
            "moved": moved,
            "positions": None,
        }
    return {
        "rejected": False,
        "reason": "moved",
        "skipped": skipped,
        "affected": affected_count,
        "moved": moved,
        "positions": out,
    }


def occupancy_rest_modes(
    leftover: float,
    extra: float,
    *,
    feasible_leftover: float = FEASIBLE_LEFTOVER,
    feasible_extra: float = FEASIBLE_EXTRA,
) -> tuple[bool, bool]:
    """Choose leftover fill or extra shrink from the dominant occupancy error.

    Unique leftover-facing and extra-facing rims do not fight. Apply only the
    side that currently dominates and is still above the feasible floor.
    """
    leftover_over = float(leftover) > float(feasible_leftover)
    extra_over = float(extra) > float(feasible_extra)
    fill_leftover = leftover_over and float(leftover) >= float(extra)
    shrink_extra = extra_over and float(extra) >= float(leftover)
    return bool(fill_leftover), bool(shrink_extra)


def occupancy_rest_frame_index(
    leftover_masks: Sequence[Any],
    extra_masks: Sequence[Any],
    *,
    fill_leftover: bool,
    shrink_extra: bool,
    candidates: Sequence[int] | None = None,
) -> int:
    """Use the leftover-heaviest or extra-heaviest frame for occupancy rest.

    Move-clip extra is often on later wing/stride frames. Frame 0 leftover
    fill cannot see that extra, and sculpting the wrong frame inflates it.
    A standing leftover blob on a fly plate (Roc frame 9) is not a fill target.
    """
    leftover_sizes = [int(np.count_nonzero(np.asarray(mask, dtype=bool))) for mask in leftover_masks]
    extra_sizes = [int(np.count_nonzero(np.asarray(mask, dtype=bool))) for mask in extra_masks]
    if candidates is not None:
        allowed = {int(index) for index in candidates}
        if not allowed:
            raise ValueError("occupancy_rest_frame_index candidates is empty")
        leftover_sizes = [
            size if index in allowed else -1 for index, size in enumerate(leftover_sizes)
        ]
        extra_sizes = [
            size if index in allowed else -1 for index, size in enumerate(extra_sizes)
        ]
    if not leftover_sizes and not extra_sizes:
        return 0
    if shrink_extra and not fill_leftover and extra_sizes:
        return int(np.argmax(extra_sizes))
    if fill_leftover and not shrink_extra and leftover_sizes:
        return int(np.argmax(leftover_sizes))
    if extra_sizes and leftover_sizes:
        peak_extra = int(np.argmax(extra_sizes))
        peak_leftover = int(np.argmax(leftover_sizes))
        if extra_sizes[peak_extra] >= leftover_sizes[peak_leftover]:
            return peak_extra
        return peak_leftover
    if extra_sizes:
        return int(np.argmax(extra_sizes))
    return int(np.argmax(leftover_sizes)) if leftover_sizes else 0


def occupancy_vertex_deltas_px(
    xs: np.ndarray,
    ys: np.ndarray,
    leftover: np.ndarray,
    extra: np.ndarray,
    sprite: np.ndarray,
    *,
    max_assign_px: float = MAX_ASSIGN_PX,
    delta_frac: float = OCCUPANCY_DELTA_FRACTION,
    fill_leftover: bool = True,
    shrink_extra: bool = True,
    owner_allow: np.ndarray | None = None,
    extra_facing_px: float = OCCUPANCY_REST_EXTRA_FACING_PX,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-vertex pixel deltas from leftover fill and extra shrink.

    Leftover-facing rim verts (near leftover, closer to leftover than extra)
    move toward leftover. Extra-on verts move toward the nearest sprite pixel.
    Extra-facing rim verts (near extra, closer to extra than leftover) move
    away from extra so triangle coverage that spills past the silhouette
    pulls in. The two rims are complementary unique regions. When
    ``owner_allow`` is set, only those verts may move.
    """
    leftover_mask = np.asarray(leftover, dtype=bool)
    extra_mask = np.asarray(extra, dtype=bool)
    sprite_mask = np.asarray(sprite, dtype=bool)
    height, width = leftover_mask.shape
    xs_v = np.asarray(xs, dtype=np.float64).reshape(-1)
    ys_v = np.asarray(ys, dtype=np.float64).reshape(-1)
    if xs_v.shape != ys_v.shape:
        raise ValueError("xs and ys must match")
    n = int(xs_v.shape[0])
    deltas = np.zeros((n, 2), dtype=np.float64)
    affected = np.zeros((n,), dtype=bool)
    frac = float(delta_frac)
    if not math.isfinite(frac) or frac <= 0.0 or frac > 1.0:
        raise ValueError("delta_frac must be in (0, 1]")
    cap = float(max_assign_px)
    leftover_ys, leftover_xs = np.nonzero(leftover_mask)
    leftover_xs_f = leftover_xs.astype(np.float64)
    leftover_ys_f = leftover_ys.astype(np.float64)
    extra_ys, extra_xs = np.nonzero(extra_mask)
    extra_xs_f = extra_xs.astype(np.float64)
    extra_ys_f = extra_ys.astype(np.float64)
    sprite_ys, sprite_xs = np.nonzero(sprite_mask)
    sprite_xs_f = sprite_xs.astype(np.float64)
    sprite_ys_f = sprite_ys.astype(np.float64)
    do_fill = bool(fill_leftover)
    do_shrink = bool(shrink_extra)
    if not do_fill and not do_shrink:
        raise ValueError("occupancy rest needs leftover fill or extra shrink")
    allow = None if owner_allow is None else np.asarray(owner_allow, dtype=bool).reshape(-1)
    if allow is not None and allow.shape[0] != n:
        raise ValueError("owner_allow must match vertex count")
    for index in range(n):
        if allow is not None and not bool(allow[index]):
            continue
        x = float(xs_v[index])
        y = float(ys_v[index])
        px = int(round(x))
        py = int(round(y))
        if not (0 <= px < width and 0 <= py < height):
            continue
        on_leftover = bool(leftover_mask[py, px])
        on_extra = bool(extra_mask[py, px])
        extra_dist = float("inf")
        leftover_dist = float("inf")
        extra_nearest = -1
        leftover_nearest = -1
        if leftover_xs_f.size:
            leftover_d2 = (leftover_xs_f - x) ** 2 + (leftover_ys_f - y) ** 2
            leftover_nearest = int(np.argmin(leftover_d2))
            leftover_dist = float(np.sqrt(leftover_d2[leftover_nearest]))
        if extra_xs_f.size:
            extra_d2 = (extra_xs_f - x) ** 2 + (extra_ys_f - y) ** 2
            extra_nearest = int(np.argmin(extra_d2))
            extra_dist = float(np.sqrt(extra_d2[extra_nearest]))
        if do_fill and leftover_xs_f.size and (not on_leftover) and (not on_extra):
            leftover_facing = 0.5 < leftover_dist <= cap
            if leftover_facing and extra_xs_f.size:
                leftover_facing = leftover_dist + 1.0 < extra_dist
            if leftover_facing:
                deltas[index, 0] += frac * (float(leftover_xs_f[leftover_nearest]) - x)
                deltas[index, 1] += frac * (float(leftover_ys_f[leftover_nearest]) - y)
                affected[index] = True
        if do_shrink and extra_xs_f.size:
            if on_extra and sprite_xs_f.size:
                dist2 = (sprite_xs_f - x) ** 2 + (sprite_ys_f - y) ** 2
                nearest = int(np.argmin(dist2))
                deltas[index, 0] += frac * (float(sprite_xs_f[nearest]) - x)
                deltas[index, 1] += frac * (float(sprite_ys_f[nearest]) - y)
                affected[index] = True
            elif (not on_leftover) and (not on_extra):
                extra_facing = 0.5 < extra_dist <= float(extra_facing_px)
                if extra_facing and leftover_xs_f.size:
                    extra_facing = extra_dist + 1.0 < leftover_dist
                if extra_facing:
                    deltas[index, 0] += frac * (x - float(extra_xs_f[extra_nearest]))
                    deltas[index, 1] += frac * (y - float(extra_ys_f[extra_nearest]))
                    affected[index] = True
    return deltas, affected


def accept_occupancy_rest(
    before: OccupancyFractions,
    after: OccupancyFractions,
    *,
    epsilon_leftover: float = EPSILON_LEFTOVER,
    epsilon_extra: float = EPSILON_EXTRA,
) -> dict[str, Any]:
    """Accept occupancy rest when leftover or extra improves and neither blows up.

    Strain is not a veto: smartrig rest edits can raise strain while occupancy
    still gets closer to the plate. Extra shrink is a win even if leftover does
    not drop by EPSILON_LEFTOVER.
    """
    leftover_drop = float(before.leftover) - float(after.leftover)
    extra_drop = float(before.extra) - float(after.extra)
    leftover_growth = float(after.leftover) - float(before.leftover)
    extra_growth = float(after.extra) - float(before.extra)
    net_drop = leftover_drop + extra_drop
    ok = net_drop > 1e-9 and leftover_growth <= float(epsilon_leftover) + 1e-12
    return {
        "accepted": bool(ok),
        "leftoverDrop": leftover_drop,
        "extraDrop": extra_drop,
        "extraGrowth": extra_growth,
        "leftoverGrowth": leftover_growth,
        "netDrop": net_drop,
        "epsilonLeftover": float(epsilon_leftover),
        "epsilonExtra": float(epsilon_extra),
        "before": {"leftover": float(before.leftover), "extra": float(before.extra)},
        "after": {"leftover": float(after.leftover), "extra": float(after.extra)},
    }


def next_pending_class(
    *,
    tried: Sequence[str],
    consecutive_rejects: int,
    diagnosed: str | None,
) -> str | None:
    """Keep walking BODY_OPERATOR_ORDER. Two rejects do not skip the diagnosed class."""
    pending = next_body_class(tried)
    if pending is not None:
        return pending
    if consecutive_rejects >= 2 and diagnosed in BODY_OPERATOR_ORDER and str(diagnosed) not in {str(name) for name in tried}:
        return str(diagnosed)
    return None


def lbs_condition_number(matrix: np.ndarray) -> float:
    values = np.linalg.svd(np.asarray(matrix, dtype=np.float64)[:3, :3], compute_uv=False)
    peak = float(values[0])
    floor = float(values[-1])
    if not math.isfinite(peak) or not math.isfinite(floor):
        raise ValueError("LBS blend matrix SVD must be finite")
    if floor <= 0.0:
        return float("inf")
    return peak / floor


def invert_lbs_posed_to_rest(
    blend: np.ndarray,
    posed: np.ndarray,
    *,
    condition_floor: float = LBS_CONDITION_FLOOR,
) -> tuple[np.ndarray | None, str]:
    """Map a posed LBS vertex back through the identity-bone blend to rest."""
    matrix = np.asarray(blend, dtype=np.float64).reshape(4, 4)
    cond = lbs_condition_number(matrix)
    if not math.isfinite(cond) or cond > (1.0 / max(float(condition_floor), 1e-12)):
        return None, "ill_conditioned"
    try:
        inverse = np.linalg.inv(matrix)
    except np.linalg.LinAlgError:
        return None, "ill_conditioned"
    posed_h = np.ones(4, dtype=np.float64)
    posed_h[:3] = np.asarray(posed, dtype=np.float64).reshape(3)
    new_h = inverse @ posed_h
    new_rest = new_h[:3] / max(abs(float(new_h[3])), 1e-8)
    if not np.isfinite(new_rest).all():
        return None, "ill_conditioned"
    return new_rest.astype(np.float64), "moved"


def bake_lbs_pose_to_rest(
    identity_blends: np.ndarray,
    posed_lbs: np.ndarray,
    *,
    condition_floor: float = LBS_CONDITION_FLOOR,
) -> dict[str, Any]:
    """Bake posed vertices into rest so identity bones reproduce that pose.

    Any ill-conditioned vertex rejects the whole bake. A partial bake that
    left perch rest on those vertices would mix two bodies in one mesh.
    """
    blends = np.asarray(identity_blends, dtype=np.float64).reshape(-1, 4, 4)
    posed = np.asarray(posed_lbs, dtype=np.float64).reshape(-1, 3)
    if blends.shape[0] != posed.shape[0]:
        raise ValueError("identity blends and posed vertices must share a vertex count")
    out = np.zeros_like(posed)
    skipped = 0
    for index in range(posed.shape[0]):
        new_rest, _status = invert_lbs_posed_to_rest(
            blends[index],
            posed[index],
            condition_floor=float(condition_floor),
        )
        if new_rest is None:
            skipped += 1
            continue
        out[index] = new_rest
    affected = int(posed.shape[0])
    if skipped:
        return {
            "rejected": True,
            "reason": "lbs_ill_conditioned",
            "skipped": skipped,
            "affected": affected,
            "moved": int(affected - skipped),
            "positions": None,
        }
    return {
        "rejected": False,
        "reason": "baked",
        "skipped": 0,
        "affected": affected,
        "moved": affected,
        "positions": out,
    }


def invert_lbs_image_plane(
    rest: np.ndarray,
    blend: np.ndarray,
    *,
    delta_world: np.ndarray,
    condition_floor: float = LBS_CONDITION_FLOOR,
    max_displacement: float,
) -> tuple[np.ndarray | None, str]:
    """Map an image-plane world delta at fixed posed depth back to rest.

    ``blend`` is the 4x4 LBS matrix B. Depth along camera forward is not
    estimated: ``delta_world`` must already be in the camera plane.
    """
    rest_h = np.ones(4, dtype=np.float64)
    rest_h[:3] = np.asarray(rest, dtype=np.float64).reshape(3)
    matrix = np.asarray(blend, dtype=np.float64).reshape(4, 4)
    cond = lbs_condition_number(matrix)
    if not math.isfinite(cond) or cond > (1.0 / max(float(condition_floor), 1e-12)):
        return None, "ill_conditioned"
    posed_h = matrix @ rest_h
    posed = posed_h[:3] / max(abs(float(posed_h[3])), 1e-8)
    target = posed + np.asarray(delta_world, dtype=np.float64).reshape(3)
    try:
        inverse = np.linalg.inv(matrix)
    except np.linalg.LinAlgError:
        return None, "ill_conditioned"
    target_h = np.ones(4, dtype=np.float64)
    target_h[:3] = target
    new_h = inverse @ target_h
    new_rest = new_h[:3] / max(abs(float(new_h[3])), 1e-8)
    delta = new_rest - rest_h[:3]
    length = float(np.linalg.norm(delta))
    if length > float(max_displacement):
        new_rest = rest_h[:3] + delta * (float(max_displacement) / length)
    if not np.isfinite(new_rest).all():
        return None, "ill_conditioned"
    return new_rest.astype(np.float64), "moved"


def skip_fraction_reject(skipped: int, affected: int, *, cap: float = LBS_SKIP_FRACTION_CAP) -> bool:
    if affected < 1:
        raise ValueError("rest sculpt affected vertex set is empty")
    return (float(skipped) / float(affected)) > float(cap)


def assign_leftover_pixels(
    leftover: np.ndarray,
    unique_distance: Mapping[str, np.ndarray],
    *,
    max_assign_px: float = MAX_ASSIGN_PX,
) -> dict[str, Any]:
    """Nearest unique-region assignment. Pixels farther than the cap stay unassigned."""
    miss = np.asarray(leftover, dtype=bool)
    if miss.ndim != 2:
        raise ValueError("leftover mask must be 2D")
    names = tuple(str(name) for name in unique_distance)
    if not names:
        raise ValueError("unique_distance cannot be empty")
    limit = float(max_assign_px)
    if not math.isfinite(limit) or limit <= 0.0:
        raise ValueError("max_assign_px must be positive")
    height, width = miss.shape
    best = np.full((height, width), np.inf, dtype=np.float64)
    labels = np.full((height, width), -1, dtype=np.int32)
    for index, name in enumerate(names):
        distance = np.asarray(unique_distance[name], dtype=np.float64)
        if distance.shape != miss.shape:
            raise ValueError(f"distance map for {name} does not match leftover")
        closer = miss & (distance < best) & (distance <= limit)
        best[closer] = distance[closer]
        labels[closer] = int(index)
    labels = np.where(miss, labels, -1)
    counts = {name: int(np.count_nonzero(labels == index)) for index, name in enumerate(names)}
    unassigned = int(np.count_nonzero(miss & (labels < 0)))
    return {
        "boneNames": names,
        "labels": labels,
        "counts": counts,
        "unassigned": unassigned,
        "leftoverPixels": int(np.count_nonzero(miss)),
    }


def aggregate_vertex_owners(
    owners_per_frame: Sequence[Mapping[int, str]],
    *,
    agree_frac: float = OWNER_AGREE_FRACTION,
) -> dict[str, Any]:
    """Clip-wide unique-region owners. A vertex is disagreed if no owner reaches agree_frac."""
    if not owners_per_frame:
        raise ValueError("unique-region owner aggregation needs at least one frame")
    floor = float(agree_frac)
    if not math.isfinite(floor) or floor <= 0.5 or floor > 1.0:
        raise ValueError("agree_frac must be in (0.5, 1]")
    votes: dict[int, list[str]] = {}
    for frame_owners in owners_per_frame:
        for vertex, owner in frame_owners.items():
            votes.setdefault(int(vertex), []).append(str(owner))
    agreed: dict[int, str] = {}
    disagreed: list[int] = []
    for vertex, names in votes.items():
        counts: dict[str, int] = {}
        for name in names:
            counts[name] = counts.get(name, 0) + 1
        winner, wins = max(counts.items(), key=lambda item: (item[1], item[0]))
        if (float(wins) / float(len(names))) >= floor:
            agreed[int(vertex)] = winner
        else:
            disagreed.append(int(vertex))
    return {
        "agreed": agreed,
        "disagreed": tuple(sorted(disagreed)),
        "agreeFrac": floor,
        "vertexCount": int(len(votes)),
    }
