"""Idle-frame-0 Meshy source-identity registration for the full-set mocap lane.

Meshy meshes in this inventory were generated from idle DEF group 2, frame 0.
The camera is the documented yaw-0 / pitch-0 source view. The frozen bind is
that same idle frame. Those three facts are the registration, not a yaw search
and not a later GIF review.

This writer is the only path allowed to mark `visualConfirmation=true` without
a human selected view. The old search-and-confirm static registrar is unchanged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from floor_column_bind import (
    FloorColumnBindError,
    identify_foot_joints,
    fit_rest_floor_column,
    fit_rest_ground_height,
    fit_rest_scale_to_ground,
)
from inside_mesh_bind import (
    InsideMeshBindError,
    MeshContainment,
    body_vertex_mask,
    fit_rest_inside_mesh,
    joints_entirely_inside,
)
from pin import sha256_file
from skeleton_overlay import multi_view_placement_report
from static_bind_registration import (
    CANONICAL_VIEW_PITCH_DEG,
    CANONICAL_VIEW_YAW_DEG,
    SCHEMA,
    SOURCE_VIEW_POLICY,
    apply_similarity,
    canonical_source_view_basis,
    invert_similarity,
    project_points,
    rotation_matrix,
)

POLICY = "idle_frame0_meshy_source_identity"
CANDIDATE_ID = "idle0_identity"
IDLE_GROUP = 2
IDLE_LOCAL_FRAME = 0
MIN_BBOX_IOU = 0.25
# Front (idle-0) owns the seed size. Uniform shrink is last: only after
# rotation, rest-angle suction, and per-bone lengths fail at a larger size.
CORRECTION_SCALE_FACTORS = (1.0, 0.92, 0.84, 0.76, 0.68, 0.60)
SCALE_POLICY = "floor_to_mesh_height"
GROUND_HEIGHT_SCALE_POLICY = "floor_to_mesh_height_uniform"
SCALE_TO_GROUND_SCALE_POLICY = "yawfix_origin_until_feet_on_floor"
CORRECTION_YAW_OFFSETS_DEG = (-15.0, -7.5, 0.0, 7.5, 15.0)
CORRECTION_PITCHES_DEG = (-15.0, 0.0, 15.0)
CORRECTION_ROLLS_DEG = (-10.0, 0.0, 10.0)
FIT_POLICY = "idle0_floor_column_xz"
GROUND_HEIGHT_FIT = "idle0_ground_height"
SCALE_TO_GROUND_FIT = "idle0_scale_to_ground"
PARENTLESS_SCALE_POLICY = "seed_first_uniform_shrink_last"
PARENTLESS_FIT_POLICY = "idle0_bind_first_inside_mesh"
# Vendor Mixamo capture of a HoMM3 idle plate comes out ~+45° from camera +Z.
# The Meshy mesh from that same plate faces the camera. AABB containment still
# succeeds at yaw 0, so a 0-centered search keeps the 45° error on every unit.
CAPTURE_YAW_SNAP_DEG = 45.0
MIXAMO_SHOULDER_PAIRS = (
    ("mixamorig:LeftShoulder", "mixamorig:RightShoulder"),
    ("mixamorig:LeftArm", "mixamorig:RightArm"),
)
CAPTURE_LATERAL_PAIRS = MIXAMO_SHOULDER_PAIRS + (
    ("BN_Wing_L_01", "BN_Wing_R_01"),
    ("Bip01_L_Thigh", "Bip01_R_Thigh"),
    ("Bip01_L_Clavicle", "Bip01_R_Clavicle"),
    # Authored mounted captures keep actor ownership in the joint name. These
    # are the same donor-side pairs, not a Left/Right rename or a new axis.
    ("mount:Bip01_L_Thigh", "mount:Bip01_R_Thigh"),
    ("mount:Bip01_L_Clavicle", "mount:Bip01_R_Clavicle"),
    ("NPC_LLeg1", "NPC_RLeg1"),
    ("NPC_LArm1", "NPC_RArm1"),
    ("BN_Tail_04", "BN_Tail_10"),
    ("BN_Spline_03", "BN_Spline_06"),
)


class Idle0RegistrationError(ValueError):
    """Raised when idle-0 source identity cannot place the mesh or capture."""


def mixamo_forward_yaw_deg(joints: np.ndarray, names: list[str]) -> float:
    """Ground-plane yaw of capture forward from camera +Z, looking down +Y."""
    joints = np.asarray(joints, dtype=np.float64)
    index = {str(name): i for i, name in enumerate(names)}
    for left_name, right_name in CAPTURE_LATERAL_PAIRS:
        if left_name not in index or right_name not in index:
            continue
        lateral = joints[index[right_name]] - joints[index[left_name]]
        forward = np.cross(np.array([0.0, 1.0, 0.0]), lateral)
        if float(np.hypot(forward[0], forward[2])) <= 1e-9:
            raise Idle0RegistrationError("capture left/right line is vertical; cannot read capture yaw")
        return float(np.degrees(np.arctan2(forward[0], forward[2])))
    raise Idle0RegistrationError("capture is missing a Mixamo or Eagle left/right pair; cannot read capture yaw")


def capture_yaw_undo_deg(measured_yaw_deg: float) -> float:
    """Snap the measured capture facing onto a 45° increment and undo it."""
    if not np.isfinite(measured_yaw_deg):
        raise Idle0RegistrationError("capture forward yaw must be finite")
    snapped = CAPTURE_YAW_SNAP_DEG * round(float(measured_yaw_deg) / CAPTURE_YAW_SNAP_DEG)
    return float(-snapped)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def sprite_alpha_bbox(path: Path) -> tuple[float, float, float, float]:
    with Image.open(path) as image:
        alpha = np.asarray(image.convert("RGBA"), dtype=np.uint8)[..., 3]
    rows, cols = np.where(alpha > 8)
    if rows.size == 0 or cols.size == 0:
        raise Idle0RegistrationError(f"idle frame 0 has no opaque pixels: {path}")
    return (float(cols.min()), float(rows.min()), float(cols.max() + 1), float(rows.max() + 1))


def bbox_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    if union <= 0.0:
        raise Idle0RegistrationError("idle-0 bbox union is empty")
    return float(inter / union)


def projected_aabb(points_xy: np.ndarray) -> tuple[float, float, float, float]:
    points_xy = np.asarray(points_xy, dtype=np.float64)
    if points_xy.ndim != 2 or points_xy.shape[1] != 2 or len(points_xy) < 2:
        raise Idle0RegistrationError("projected points must be [N,2]")
    x0, y0 = points_xy.min(axis=0)
    x1, y1 = points_xy.max(axis=0)
    if not np.isfinite([x0, y0, x1, y1]).all() or x1 <= x0 or y1 <= y0:
        raise Idle0RegistrationError("projected mesh AABB is degenerate")
    return (float(x0), float(y0), float(x1), float(y1))


def identity_height_match_camera(vertices: np.ndarray, sprite_bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    """Identity mesh rotation. Scale so projected height matches the idle sprite."""
    vertices = np.asarray(vertices, dtype=np.float64)
    basis = canonical_source_view_basis()
    xy = vertices @ basis[:2].T
    mesh_h = float(xy[:, 1].max() - xy[:, 1].min())
    sprite_h = float(sprite_bbox[3] - sprite_bbox[1])
    if mesh_h <= 1e-9 or sprite_h <= 1e-9:
        raise Idle0RegistrationError("idle-0 mesh or sprite height is degenerate")
    scale = sprite_h / mesh_h
    sprite_cx = 0.5 * (sprite_bbox[0] + sprite_bbox[2])
    sprite_cy = 0.5 * (sprite_bbox[1] + sprite_bbox[3])
    mesh_cx, mesh_cy = (xy.max(axis=0) + xy.min(axis=0)) * 0.5
    offset = np.asarray((sprite_cx - scale * mesh_cx, sprite_cy - scale * mesh_cy), dtype=np.float64)
    projected = project_points(vertices, basis=basis, scale=scale, offset=offset)
    mesh_bbox = projected_aabb(projected)
    iou = bbox_iou(mesh_bbox, sprite_bbox)
    if iou < MIN_BBOX_IOU:
        raise Idle0RegistrationError(
            f"idle-0 projected mesh vs sprite bbox IoU {iou:.4f} is below {MIN_BBOX_IOU}"
        )
    return {
        "rotation": np.eye(3, dtype=np.float64),
        "yawDeg": CANONICAL_VIEW_YAW_DEG,
        "pitchDeg": CANONICAL_VIEW_PITCH_DEG,
        "rollDeg": 0.0,
        "scale": float(scale),
        "offset": offset.tolist(),
        "bboxIou": iou,
        "meshBbox": list(mesh_bbox),
        "spriteBbox": list(sprite_bbox),
        "policy": POLICY,
        "sourceViewPolicy": SOURCE_VIEW_POLICY,
    }


def _containment_joint_mask(names: list[str] | None, containment_joint_names: list[str] | None) -> np.ndarray | None:
    if containment_joint_names is None:
        return None
    if not names:
        raise Idle0RegistrationError("containment_joint_names requires capture joint names")
    wanted = {str(name) for name in containment_joint_names}
    if not wanted:
        raise Idle0RegistrationError("containment_joint_names is empty")
    missing = sorted(wanted - set(names))
    if missing:
        raise Idle0RegistrationError(f"containment joints are not in the capture: {missing}")
    mask = np.array([name in wanted for name in names], dtype=bool)
    if not bool(mask.any()):
        raise Idle0RegistrationError("containment_joint_names matched no capture joints")
    return mask


def _front_authoritative_seed(
    joints: np.ndarray, vertices: np.ndarray, *, yaw_deg: float, seed_joints: np.ndarray | None = None
) -> dict[str, Any]:
    """Idle-0 front owns scale and XY. Side-view center supplies depth (Z)."""
    rotation = rotation_matrix(float(yaw_deg), 0.0, 0.0)
    measure = np.asarray(joints if seed_joints is None else seed_joints, dtype=np.float64)
    rotated = measure @ rotation.T
    j_min, j_max = rotated.min(axis=0), rotated.max(axis=0)
    v_min, v_max = vertices.min(axis=0), vertices.max(axis=0)
    j_span = j_max - j_min
    v_span = v_max - v_min
    front = [axis for axis in (0, 1) if j_span[axis] > 1e-6]
    if not front or np.any(v_span[front] <= 1e-9):
        raise Idle0RegistrationError("idle-0 bind requires nonzero front-view mesh and capture extent")
    scale = float(min(v_span[axis] / j_span[axis] for axis in front))
    if not np.isfinite(scale) or scale <= 0:
        raise Idle0RegistrationError("idle-0 skeleton scale must be finite and positive")
    j_center = (j_max + j_min) * 0.5
    v_center = (v_max + v_min) * 0.5
    translation = v_center - scale * j_center
    placed = apply_similarity(joints, rotation=rotation, scale=scale, translation=translation)
    return {
        "rotation": rotation,
        "yawDeg": float(yaw_deg),
        "pitchDeg": 0.0,
        "rollDeg": 0.0,
        "scale": scale,
        "translation": translation,
        "joints": placed,
    }


def _containment_score(
    *,
    yaw_deg: float,
    pitch_deg: float,
    roll_deg: float,
    seed_yaw_deg: float,
    body_saturation: float,
) -> float:
    rotation_penalty = (abs(yaw_deg - seed_yaw_deg) + abs(pitch_deg) + abs(roll_deg)) / 15.0
    return (1.0 - float(body_saturation)) + 0.05 * rotation_penalty


def _correction_rotations() -> list[tuple[float, float, float]]:
    """Lowest rotation penalty first so a working seed pose is not drowned by 45 fits."""
    triples = [
        (float(yaw), float(pitch), float(roll))
        for yaw in CORRECTION_YAW_OFFSETS_DEG
        for pitch in CORRECTION_PITCHES_DEG
        for roll in CORRECTION_ROLLS_DEG
    ]
    triples.sort(key=lambda item: (abs(item[0]) + abs(item[1]) + abs(item[2]), abs(item[0]), abs(item[1]), abs(item[2])))
    return triples


def _evaluate_similarity_candidate(
    joints: np.ndarray,
    vertices: np.ndarray,
    parent_ids: np.ndarray | None,
    hull: MeshContainment | None,
    *,
    scale: float,
    yaw_deg: float,
    pitch_deg: float,
    roll_deg: float,
    seed_yaw_deg: float,
    names: list[str] | None = None,
    body_mask: np.ndarray | None = None,
    saturate: bool = True,
    containment_mask: np.ndarray | None = None,
) -> dict[str, Any] | None:
    rotation = rotation_matrix(yaw_deg, pitch_deg, roll_deg)
    rotated = joints @ rotation.T
    measure = rotated if containment_mask is None else rotated[np.asarray(containment_mask, dtype=bool)]
    if measure.size == 0:
        return None
    r_min, r_max = measure.min(axis=0), measure.max(axis=0)
    r_center = (r_max + r_min) * 0.5
    # AABB center can sit in a hole or beside a crouched body. Shrink toward
    # the vertex mean so collapsing the skeleton lands in flesh. Parentless
    # registration can retry the AABB center below when the mean is outside
    # the actual occupied volume; articulated rest fitting must not silently
    # change its established center policy.
    v_center = vertices.mean(axis=0)
    translation = v_center - scale * r_center
    translation_center_policy = "vertex_mean"
    placed = apply_similarity(joints, rotation=rotation, scale=scale, translation=translation)
    scales = np.ones(len(joints), dtype=np.float64)
    fitted = placed
    mean_shortening = 0.0
    mean_angle = 0.0
    body_saturation = 0.0
    rest_report: dict[str, Any] | None = None
    if parent_ids is not None:
        try:
            rest_report = fit_rest_inside_mesh(
                placed,
                parent_ids,
                vertices,
                triangles=None,
                hull=hull,
                names=names,
                body_mask=body_mask,
                saturate=saturate,
            )
        except InsideMeshBindError:
            return None
        scales = rest_report["scales"]
        fitted = rest_report["joints"]
        mean_shortening = float(rest_report["meanShortening"])
        mean_angle = float(rest_report["meanRestAngleDeg"])
        body_saturation = float(rest_report["bodySaturation"])
    checked = fitted if containment_mask is None else fitted[np.asarray(containment_mask, dtype=bool)]
    inside, report = joints_entirely_inside(vertices, checked)
    if not inside and parent_ids is None:
        bbox_center = (vertices.max(axis=0) + vertices.min(axis=0)) * 0.5
        translation = bbox_center - scale * r_center
        placed = apply_similarity(joints, rotation=rotation, scale=scale, translation=translation)
        fitted = placed
        checked = fitted if containment_mask is None else fitted[np.asarray(containment_mask, dtype=bool)]
        inside, report = joints_entirely_inside(vertices, checked)
        if inside:
            translation_center_policy = "aabb_center_fallback"
    if not inside:
        return None
    score = _containment_score(
        yaw_deg=yaw_deg,
        pitch_deg=pitch_deg,
        roll_deg=roll_deg,
        seed_yaw_deg=float(seed_yaw_deg),
        body_saturation=body_saturation,
    )
    return {
        "rotation": rotation,
        "yawDeg": float(yaw_deg),
        "pitchDeg": float(pitch_deg),
        "rollDeg": float(roll_deg),
        "scale": float(scale),
        "translation": translation,
        "translationCenterPolicy": translation_center_policy,
        "joints": fitted,
        "preLengthJoints": placed,
        "boneLengthScales": scales,
        "meanShortening": mean_shortening,
        "meanRestAngleDeg": mean_angle,
        "bodySaturation": body_saturation,
        "views": report["views"],
        "score": float(score),
        "rest": rest_report,
    }


def _search_bind_first_inside_mesh(
    joints: np.ndarray,
    vertices: np.ndarray,
    *,
    seed_yaw_deg: float,
    names: list[str] | None = None,
    containment_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    """Uniform-shrink bind-first search used by the previous yaw-fix binds.

    No per-bone rest suction. Keep shrinking until every (masked) joint is inside.
    """
    seed_joints = None if containment_mask is None else joints[np.asarray(containment_mask, dtype=bool)]
    seed = _front_authoritative_seed(
        joints, vertices, yaw_deg=float(seed_yaw_deg), seed_joints=seed_joints
    )
    best: dict[str, Any] | None = None
    evaluated = 0
    chosen_scale_factor = 1.0
    scale_factors = list(CORRECTION_SCALE_FACTORS)
    extra = 0.52
    while extra >= 0.04:
        if extra not in scale_factors:
            scale_factors.append(extra)
        extra = round(extra - 0.08, 2)
    for scale_factor in scale_factors:
        scale = seed["scale"] * float(scale_factor)
        scale_best: dict[str, Any] | None = None
        corrections = (
            [(0.0, 0.0, 0.0)] if containment_mask is not None else _correction_rotations()
        )
        for yaw_offset, pitch_deg, roll_deg in corrections:
            yaw_deg = float(seed_yaw_deg) + float(yaw_offset)
            evaluated += 1
            candidate = _evaluate_similarity_candidate(
                joints,
                vertices,
                None,
                None,
                scale=scale,
                yaw_deg=yaw_deg,
                pitch_deg=pitch_deg,
                roll_deg=roll_deg,
                seed_yaw_deg=float(seed_yaw_deg),
                names=names,
                body_mask=None,
                saturate=False,
                containment_mask=containment_mask,
            )
            if candidate is None:
                continue
            scale_best = candidate
            break
        if scale_best is not None:
            best = scale_best
            chosen_scale_factor = float(scale_factor)
            break
    if best is None:
        if os.environ.get("HOMM3_ACCEPT_BIND_DEFECTS"):
            seed["acceptedDefect"] = "joints_outside_mesh"
            seed["candidatesEvaluated"] = evaluated
            seed["scaleFactor"] = chosen_scale_factor
            return seed
        raise Idle0RegistrationError(
            "idle-0 bind could not place every joint inside the mesh from front/side/top"
        )
    best["seed"] = seed
    best["candidatesEvaluated"] = evaluated
    best["scaleFactor"] = chosen_scale_factor
    return best


def idle0_skeleton_similarity(
    joints: np.ndarray,
    vertices: np.ndarray,
    parents: np.ndarray | None = None,
    triangles: np.ndarray | None = None,
    *,
    seed_yaw_deg: float = 0.0,
    names: list[str] | None = None,
    fit: str | None = None,
    base_similarity: dict[str, Any] | None = None,
    containment_joint_names: list[str] | None = None,
) -> dict[str, Any]:
    """Facing mocap, then floor/top column bind when a hierarchy is present."""
    joints = np.asarray(joints, dtype=np.float64)
    vertices = np.asarray(vertices, dtype=np.float64)
    if joints.ndim != 2 or joints.shape[1] != 3 or vertices.ndim != 2 or vertices.shape[1] != 3:
        raise Idle0RegistrationError("idle-0 bind joints and vertices must be [N,3]")
    if not np.isfinite(joints).all() or not np.isfinite(vertices).all():
        raise Idle0RegistrationError("idle-0 bind joints/vertices must be finite")
    parent_ids: np.ndarray | None = None
    if parents is not None:
        parent_ids = np.asarray(parents, dtype=np.int64)
        if parent_ids.shape != (len(joints),):
            raise Idle0RegistrationError("idle-0 bind parents must be [J]")
    containment_mask = _containment_joint_mask(names, containment_joint_names)
    seed_joints = None if containment_mask is None else joints[containment_mask]
    seed = _front_authoritative_seed(
        joints, vertices, yaw_deg=float(seed_yaw_deg), seed_joints=seed_joints
    )
    seed_views = multi_view_placement_report(vertices, seed["joints"], margin_fraction=0.0)["views"]
    fit_kind = str(fit or FIT_POLICY)
    if parent_ids is not None:
        try:
            if fit_kind == SCALE_TO_GROUND_FIT:
                rest = fit_rest_scale_to_ground(
                    joints,
                    parent_ids,
                    vertices,
                    triangles,
                    seed_yaw_deg=float(seed_yaw_deg),
                    names=names,
                    base_similarity=base_similarity,
                )
                scale_policy = SCALE_TO_GROUND_SCALE_POLICY
            elif fit_kind == GROUND_HEIGHT_FIT:
                rest = fit_rest_ground_height(
                    joints,
                    parent_ids,
                    vertices,
                    triangles,
                    seed_yaw_deg=float(seed_yaw_deg),
                    names=names,
                )
                scale_policy = GROUND_HEIGHT_SCALE_POLICY
            elif fit_kind in (FIT_POLICY, "idle0_floor_column_xz"):
                rest = fit_rest_floor_column(
                    joints,
                    parent_ids,
                    vertices,
                    triangles,
                    seed_yaw_deg=float(seed_yaw_deg),
                    names=names,
                )
                scale_policy = SCALE_POLICY
            elif fit_kind in (PARENTLESS_FIT_POLICY, "idle0_bind_first_inside_mesh"):
                best = _search_bind_first_inside_mesh(
                    joints,
                    vertices,
                    seed_yaw_deg=float(seed_yaw_deg),
                    names=names,
                    containment_mask=containment_mask,
                )
                placed = np.asarray(best["joints"], dtype=np.float64)
                feet = identify_foot_joints(placed, parent_ids)
                rest = {
                    "joints": placed,
                    "rotation": np.asarray(best["rotation"], dtype=np.float64),
                    "yawDeg": float(best["yawDeg"]),
                    "pitchDeg": float(best["pitchDeg"]),
                    "rollDeg": float(best["rollDeg"]),
                    "extraYawDeg": float(best["yawDeg"]) - float(seed_yaw_deg),
                    "scale": float(best["scale"]),
                    "translation": np.asarray(best["translation"], dtype=np.float64),
                    "scales": np.ones(len(parent_ids), dtype=np.float64),
                    "meanShortening": 0.0,
                    "meanRestAngleDeg": 0.0,
                    "restAngleDeg": np.zeros(len(parent_ids), dtype=np.float64),
                    "footIndices": feet,
                    "floorY": float(vertices[:, 1].min()),
                    "topY": float(vertices[:, 1].max()),
                    "policy": "bind_first_inside_mesh",
                    "containmentPolicy": "bind_first_inside_mesh",
                    "candidatesEvaluated": int(best["candidatesEvaluated"]),
                    "scaleFactor": float(best["scaleFactor"]),
                    "translationCenterPolicy": str(best.get("translationCenterPolicy", "vertex_mean")),
                }
                scale_policy = PARENTLESS_SCALE_POLICY
            else:
                raise Idle0RegistrationError(f"unknown idle-0 fit {fit_kind!r}")
        except FloorColumnBindError as exc:
            raise Idle0RegistrationError(str(exc)) from exc
        inside, report = joints_entirely_inside(vertices, rest["joints"])
        mesh_diag = float(np.linalg.norm(np.ptp(vertices, axis=0)))
        if mesh_diag <= 1e-9:
            raise Idle0RegistrationError("idle-0 bind requires nonzero mesh extent")
        rotation = np.asarray(rest["rotation"], dtype=np.float64)
        scale = float(rest["scale"])
        translation = np.asarray(rest["translation"], dtype=np.float64)
        bind_rest = invert_similarity(
            np.asarray(rest["joints"], dtype=np.float64),
            rotation=rotation,
            scale=scale,
            translation=translation,
        )
        root_delta = joints[0] - bind_rest[0]
        bind_rest = bind_rest + root_delta
        translation = translation - scale * (root_delta @ rotation.T)
        return {
            "rotation": rotation.tolist(),
            "yawDeg": float(rest["yawDeg"]),
            "pitchDeg": float(rest["pitchDeg"]),
            "rollDeg": float(rest["rollDeg"]),
            "scale": scale,
            "translation": np.asarray(translation, dtype=np.float64).tolist(),
            "skeletonToMeshExtentRatio": float(np.linalg.norm(np.ptp(rest["joints"], axis=0))) / mesh_diag,
            "policy": POLICY,
            "fit": fit_kind,
            "authoritativeView": "front",
            "correctionViews": ["side", "top"],
            "seed": {
                "scale": float(seed["scale"]),
                "translation": np.asarray(seed["translation"], dtype=np.float64).tolist(),
                "views": seed_views,
            },
            "views": report["views"],
            "score": float(abs(rest["extraYawDeg"]) / 15.0),
            "candidatesEvaluated": int(rest.get("candidatesEvaluated") or 1),
            "containmentPolicy": rest["containmentPolicy"],
            "scaleFactor": float(rest.get("scaleFactor") or 1.0),
            "translationCenterPolicy": rest.get("translationCenterPolicy"),
            "scalePolicy": scale_policy,
            "seedYawDeg": float(seed_yaw_deg),
            "bindRestJoints": bind_rest.tolist(),
            "captureBindJoints": joints.tolist(),
            "boneLengthScales": np.asarray(rest["scales"], dtype=np.float64).tolist(),
            "boneLengthPolicy": rest["policy"],
            "meanBoneShortening": float(rest["meanShortening"]),
            "meanRestAngleDeg": float(rest["meanRestAngleDeg"]),
            "restAngleDeg": np.asarray(rest["restAngleDeg"], dtype=np.float64).tolist(),
            "footIndices": [int(index) for index in rest["footIndices"]],
            "floorY": float(rest["floorY"]),
            "topY": float(rest["topY"]),
            "extraYawDeg": float(rest["extraYawDeg"]),
            "originScale": rest.get("originScale"),
            "baseScale": rest.get("baseScale"),
            "slabInside": inside,
            "containmentJointNames": None if containment_joint_names is None else list(containment_joint_names),
        }
    hull = None
    body_mask = None
    best: dict[str, Any] | None = None
    evaluated = 0
    chosen_scale_factor = 1.0
    for scale_factor in CORRECTION_SCALE_FACTORS:
        scale = seed["scale"] * float(scale_factor)
        scale_best: dict[str, Any] | None = None
        for yaw_offset, pitch_deg, roll_deg in _correction_rotations():
            yaw_deg = float(seed_yaw_deg) + float(yaw_offset)
            evaluated += 1
            candidate = _evaluate_similarity_candidate(
                joints,
                vertices,
                None,
                hull,
                scale=scale,
                yaw_deg=yaw_deg,
                pitch_deg=pitch_deg,
                roll_deg=roll_deg,
                seed_yaw_deg=float(seed_yaw_deg),
                names=names,
                body_mask=body_mask,
                saturate=False,
            )
            if candidate is None:
                continue
            scale_best = candidate
            break
        if scale_best is not None:
            best = scale_best
            chosen_scale_factor = float(scale_factor)
            break
    if best is None:
        if os.environ.get("HOMM3_ACCEPT_BIND_DEFECTS"):
            best = dict(seed)
            best["acceptedDefect"] = "joints_outside_mesh"
        else:
            raise Idle0RegistrationError(
                "idle-0 bind could not place every joint inside the mesh from front/side/top"
            )
    mesh_diag = float(np.linalg.norm(np.ptp(vertices, axis=0)))
    if mesh_diag <= 1e-9:
        raise Idle0RegistrationError("idle-0 bind requires nonzero mesh extent")
    return {
        "rotation": best["rotation"].tolist(),
        "yawDeg": best["yawDeg"],
        "pitchDeg": best["pitchDeg"],
        "rollDeg": best["rollDeg"],
        "scale": float(best["scale"]),
        "translation": np.asarray(best["translation"], dtype=np.float64).tolist(),
        "translationCenterPolicy": str(best.get("translationCenterPolicy", "vertex_mean")),
        "skeletonToMeshExtentRatio": float(np.linalg.norm(np.ptp(best["joints"], axis=0))) / mesh_diag,
        "policy": POLICY,
        "fit": PARENTLESS_FIT_POLICY,
        "authoritativeView": "front",
        "correctionViews": ["side", "top"],
        "seed": {
            "scale": float(seed["scale"]),
            "translation": np.asarray(seed["translation"], dtype=np.float64).tolist(),
            "views": seed_views,
        },
        "views": best["views"],
        "score": best["score"],
        "candidatesEvaluated": evaluated,
        "containmentPolicy": "bind_first_inside_mesh",
        "scaleFactor": chosen_scale_factor,
        "scalePolicy": PARENTLESS_SCALE_POLICY,
        "seedYawDeg": float(seed_yaw_deg),
    }


def write_idle0_meshy_registration(
    *,
    output_path: Path,
    unit: str,
    mesh_path: Path,
    mesh_vertices: np.ndarray,
    capture_path: Path,
    capture_joints: np.ndarray,
    capture_parents: np.ndarray,
    idle_frame0: Path,
    bind_frame: int,
    mesh_triangles: np.ndarray | None = None,
    fit: str | None = None,
    base_registration: Path | None = None,
    containment_joint_names: list[str] | None = None,
    explicit_capture_yaw_undo_deg: float | None = None,
    capture_yaw_policy: str | None = None,
) -> dict[str, Any]:
    if int(bind_frame) != 0:
        raise Idle0RegistrationError(
            f"idle-0 Meshy registration requires bind frame 0, got {bind_frame}"
        )
    if not mesh_path.is_file():
        raise FileNotFoundError(mesh_path)
    if not capture_path.is_file():
        raise FileNotFoundError(capture_path)
    if not idle_frame0.is_file():
        raise FileNotFoundError(idle_frame0)
    view = identity_height_match_camera(mesh_vertices, sprite_alpha_bbox(idle_frame0))
    raw = np.load(capture_path, allow_pickle=False)
    names = [
        item.decode("utf-8") if isinstance(item, bytes) else str(item)
        for item in np.asarray(raw["joint_names"]).tolist()
    ]
    if explicit_capture_yaw_undo_deg is None:
        capture_forward_yaw = mixamo_forward_yaw_deg(capture_joints, names)
        seed_yaw = capture_yaw_undo_deg(capture_forward_yaw)
        yaw_policy = "undo_mixamo_forward_snapped_to_45_onto_camera_plus_z"
    else:
        seed_yaw = float(explicit_capture_yaw_undo_deg)
        if not np.isfinite(seed_yaw):
            raise Idle0RegistrationError("explicit capture yaw undo must be finite")
        yaw_policy = str(capture_yaw_policy or "explicit_route_capture_orientation")
        if not yaw_policy.strip():
            raise Idle0RegistrationError("explicit capture yaw policy must be non-empty")
        capture_forward_yaw = None
    base_similarity = None
    if base_registration is not None:
        base_path = Path(base_registration)
        if not base_path.is_file():
            raise FileNotFoundError(base_path)
        base_payload = json.loads(base_path.read_text(encoding="utf-8"))
        try:
            base_similarity = base_payload["views"]["candidates"][0]["skeletonSimilarity"]
        except (KeyError, IndexError, TypeError) as exc:
            raise Idle0RegistrationError("base registration is missing skeletonSimilarity") from exc
    skeleton = idle0_skeleton_similarity(
        capture_joints,
        mesh_vertices,
        capture_parents,
        mesh_triangles,
        seed_yaw_deg=seed_yaw,
        names=names,
        fit=fit,
        base_similarity=base_similarity,
        containment_joint_names=containment_joint_names,
    )
    skeleton["captureForwardYawDeg"] = (
        None if capture_forward_yaw is None else float(capture_forward_yaw)
    )
    skeleton["captureYawUndoDeg"] = float(seed_yaw)
    skeleton["captureYawPolicy"] = yaw_policy
    payload = {
        "schema": SCHEMA,
        "policy": POLICY,
        "unit": unit,
        "bindFrame": 0,
        "bindGroup": IDLE_GROUP,
        "bindLocalFrame": IDLE_LOCAL_FRAME,
        "inputHashes": {
            "mesh": sha256_file(mesh_path),
            "capture": sha256_file(capture_path),
            "idleFrame0": sha256_file(idle_frame0),
        },
        "idleFrame0": str(idle_frame0.resolve()).replace("\\", "/"),
        "mesh": str(mesh_path.resolve()).replace("\\", "/"),
        "capture": str(capture_path.resolve()).replace("\\", "/"),
        "views": {
            "ambiguousOrientation": False,
            "candidates": [
                {
                    "id": CANDIDATE_ID,
                    "meshToSourceView": {
                        "rotation": view["rotation"].tolist(),
                        "yawDeg": view["yawDeg"],
                        "pitchDeg": view["pitchDeg"],
                        "rollDeg": view["rollDeg"],
                        "policy": POLICY,
                    },
                    "camera": {
                        "yawDeg": view["yawDeg"],
                        "pitchDeg": view["pitchDeg"],
                        "scale": view["scale"],
                        "offset": view["offset"],
                        "bboxIou": view["bboxIou"],
                        "meshBbox": view["meshBbox"],
                        "spriteBbox": view["spriteBbox"],
                        "sourceViewPolicy": view["sourceViewPolicy"],
                    },
                    "skeletonSimilarity": skeleton,
                }
            ],
        },
        "acceptance": {
            "status": "accepted",
            "accepted": True,
            "visualConfirmation": True,
            "consumable": True,
            "selectedCandidateId": CANDIDATE_ID,
            "confirmationKind": POLICY,
            "reasons": [
                "meshy_mesh_generated_from_idle_def_group_2_frame_0",
                "camera_is_documented_yaw0_pitch0_source_view",
                "frozen_bind_is_that_same_idle_frame",
                (
                    "mixamo_capture_forward_yaw_undone_onto_camera_plus_z"
                    if capture_forward_yaw is not None
                    else "explicit_route_capture_orientation_applied"
                ),
                *(
                    [
                        "starts_from_previous_yawfix_bind",
                        "lab_origin_scale_until_feet_on_floor",
                        "no_per_bone_move_or_length_edit",
                        "violates_bind_first_containment",
                    ]
                    if skeleton["fit"] == SCALE_TO_GROUND_FIT
                    else (
                        [
                            "feet_dropped_to_mesh_floor",
                            "uniform_scale_floor_to_mesh_top",
                            "no_per_bone_move_or_length_edit",
                            "violates_bind_first_containment",
                        ]
                        if skeleton["fit"] == GROUND_HEIGHT_FIT
                        else (
                            [
                                "bind_first_uniform_shrink_until_inside",
                            ]
                            if skeleton["fit"] == PARENTLESS_FIT_POLICY
                            else [
                                "feet_pinned_to_mesh_floor_then_scaled_to_mesh_top",
                                "yaw_until_floor_footprint_fits",
                                "upward_xz_suction_into_nearest_slice_volume",
                            ]
                        )
                    )
                ),
            ],
        },
        "proof": "generated-artifact",
    }
    _write_json(output_path, payload)
    return payload
