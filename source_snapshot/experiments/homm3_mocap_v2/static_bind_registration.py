"""Static mesh-to-source registration and rigid skeleton compatibility.

Three proofs stay separate:

- source-view registration of the unbound textured mesh
- relative skeleton placement under one global similarity, plus optional
  per-bone rest-length scales that keep mocap parent-to-child directions
- skinning algebra (rest LBS identity)

None of those is treated as proof of another. A result is never ``accepted``
without explicit visual confirmation. Generated-artifact only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from scipy.spatial import cKDTree

SCHEMA = "homm3.static-bind-registration.v1"
CANONICAL_VIEW_YAW_DEG = 0.0
CANONICAL_VIEW_PITCH_DEG = 0.0
# Documented source-view camera. Not the flight-mesh 15/155 search.
SOURCE_VIEW_POLICY = "canonical_orthographic_y_up_yaw0_pitch0_mesh_is_rotated"
IOU_AMBIGUITY_SLACK = 0.03
MIN_DISTINCT_ANGLE_DEG = 25.0
MAX_VIEW_CANDIDATES = 5
BODY_BRANCHES = ("torso", "neck_head")
WING_BRANCHES = ("wing_left", "wing_right")
LEG_BRANCHES = ("leg_left", "leg_right")
WING_SPAN_RATIO_MAX = 1.35
WING_SURFACE_VS_BODY_SLACK = 2.5
BRANCH_NEAR_CORE_FRACTION = 0.45
BRANCH_MEAN_DISTANCE_DIAGONAL_MAX = 0.15
BRANCH_MAX_DISTANCE_DIAGONAL_MAX = 0.30


class StaticRegistrationError(ValueError):
    """Raised when a consumable bind is requested without an accepted static artifact."""


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def rotation_matrix(yaw_deg: float, pitch_deg: float, roll_deg: float) -> np.ndarray:
    """Yaw about +Y, then pitch about +X, then roll about +Z. Right-handed."""
    yaw = np.deg2rad(float(yaw_deg))
    pitch = np.deg2rad(float(pitch_deg))
    roll = np.deg2rad(float(roll_deg))
    cy, sy = np.cos(yaw), np.sin(yaw)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cr, sr = np.cos(roll), np.sin(roll)
    ry = np.asarray(((cy, 0.0, sy), (0.0, 1.0, 0.0), (-sy, 0.0, cy)), dtype=np.float64)
    rx = np.asarray(((1.0, 0.0, 0.0), (0.0, cp, -sp), (0.0, sp, cp)), dtype=np.float64)
    rz = np.asarray(((cr, -sr, 0.0), (sr, cr, 0.0), (0.0, 0.0, 1.0)), dtype=np.float64)
    return rz @ rx @ ry


def apply_similarity(points: np.ndarray, *, rotation: np.ndarray, scale: float, translation: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float64)
    rotation = np.asarray(rotation, dtype=np.float64)
    translation = np.asarray(translation, dtype=np.float64).reshape(3)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError(f"points must be [N,3], got {points.shape}")
    if rotation.shape != (3, 3):
        raise ValueError("rotation must be 3x3")
    if float(scale) <= 0.0 or not np.isfinite(scale):
        raise ValueError("scale must be finite and positive")
    if not np.isfinite(rotation).all() or not np.isfinite(translation).all() or not np.isfinite(points).all():
        raise ValueError("similarity inputs must be finite")
    if abs(float(np.linalg.det(rotation)) - 1.0) > 1e-5:
        raise ValueError("rotation must be a proper rotation")
    return float(scale) * (points @ rotation.T) + translation


def invert_similarity(points: np.ndarray, *, rotation: np.ndarray, scale: float, translation: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float64)
    rotation = np.asarray(rotation, dtype=np.float64)
    translation = np.asarray(translation, dtype=np.float64).reshape(3)
    return ((points - translation) / float(scale)) @ rotation


def canonical_source_view_basis() -> np.ndarray:
    """Right, down, forward for yaw=0, pitch=0. Mesh orientation is searched instead."""
    from skin_camera_registration import _basis_yup

    return _basis_yup(CANONICAL_VIEW_YAW_DEG, CANONICAL_VIEW_PITCH_DEG)


def project_points(points: np.ndarray, *, basis: np.ndarray, scale: float, offset: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float64)
    basis = np.asarray(basis, dtype=np.float64)
    offset = np.asarray(offset, dtype=np.float64).reshape(2)
    xy = points @ basis[:2].T
    return float(scale) * xy + offset


def project_direction(direction: np.ndarray, *, basis: np.ndarray) -> np.ndarray:
    direction = np.asarray(direction, dtype=np.float64).reshape(3)
    basis = np.asarray(basis, dtype=np.float64)
    screen = direction @ basis[:2].T
    norm = float(np.linalg.norm(screen))
    if norm <= 1e-12:
        raise ValueError("direction is parallel to the source-view forward axis")
    return screen / norm


def rotation_geodesic_deg(a: np.ndarray, b: np.ndarray) -> float:
    rel = np.asarray(a, dtype=np.float64).T @ np.asarray(b, dtype=np.float64)
    value = float(np.clip((np.trace(rel) - 1.0) * 0.5, -1.0, 1.0))
    return float(np.degrees(np.arccos(value)))


def bbox_scale_offset(points: np.ndarray, basis: np.ndarray, target_bbox: tuple[float, float, float, float]) -> tuple[float, np.ndarray]:
    from skin_camera_registration import _bbox_scale_offset

    return _bbox_scale_offset(points, basis, target_bbox)


def source_matches_render_canvas(source_rgb: np.ndarray, rendered_rgb: np.ndarray) -> None:
    if np.asarray(source_rgb).shape != np.asarray(rendered_rgb).shape:
        raise ValueError("source and render must share one canvas; independent letterbox/rescale is forbidden")


def joint_groups(names: list[str], region_joints: dict[str, tuple[str, ...] | list[str]]) -> dict[str, list[int]]:
    index = {name: i for i, name in enumerate(names)}
    groups: dict[str, list[int]] = {}
    for region, bones in region_joints.items():
        missing = [bone for bone in bones if bone not in index]
        if missing:
            raise ValueError(f"capture is missing declared {region} joints {missing}")
        groups[str(region)] = [index[bone] for bone in bones]
    return groups


def nearest_surface_distances(points: np.ndarray, vertices: np.ndarray) -> np.ndarray:
    tree = cKDTree(np.asarray(vertices, dtype=np.float64))
    distances, _ = tree.query(np.asarray(points, dtype=np.float64), k=1)
    return np.asarray(distances, dtype=np.float64)


def mesh_core_radius(vertices: np.ndarray, *, quantile: float = 0.45) -> float:
    centered = np.asarray(vertices, dtype=np.float64) - np.asarray(vertices, dtype=np.float64).mean(axis=0)
    radii = np.linalg.norm(centered, axis=1)
    return float(np.quantile(radii, quantile))


def branch_placement_report(
    *,
    joints: np.ndarray,
    names: list[str],
    vertices: np.ndarray,
    groups: dict[str, list[int]],
) -> dict[str, Any]:
    distances = nearest_surface_distances(joints, vertices)
    center = vertices.mean(axis=0)
    core = mesh_core_radius(vertices)
    rows = {}
    for region, indices in groups.items():
        if not indices:
            continue
        picked = distances[indices]
        joint_radii = np.linalg.norm(joints[indices] - center, axis=1)
        rows[region] = {
            "joints": [names[i] for i in indices],
            "meanSurfaceDistance": float(picked.mean()),
            "maxSurfaceDistance": float(picked.max()),
            "medianSurfaceDistance": float(np.median(picked)),
            "meanRadiusFromMeshCenter": float(joint_radii.mean()),
            "nearMeshCore": bool(float(joint_radii.mean()) < core),
        }
    return {
        "branches": rows,
        "meshCoreRadius": core,
        "bbox": {
            "jointsInside": bool(
                np.all(joints >= vertices.min(axis=0) - 1e-9) and np.all(joints <= vertices.max(axis=0) + 1e-9)
            ),
            "policy": "coarse_diagnostic_only",
        },
    }


def wing_span(joints: np.ndarray, groups: dict[str, list[int]]) -> float:
    left = joints[groups["wing_left"]]
    right = joints[groups["wing_right"]]
    return float(np.linalg.norm(left.mean(axis=0) - right.mean(axis=0)))


def mesh_lateral_span(vertices: np.ndarray, *, axis: int) -> float:
    return float(np.ptp(np.asarray(vertices, dtype=np.float64)[:, axis]))


def evaluate_rigid_compatibility(
    *,
    joints: np.ndarray,
    names: list[str],
    vertices: np.ndarray,
    groups: dict[str, list[int]],
    placement: dict[str, Any],
) -> dict[str, Any]:
    """Decide rigid compatibility. BBox containment is not acceptance."""
    branches = placement["branches"]
    body = [name for name in BODY_BRANCHES if name in branches]
    wings = [name for name in WING_BRANCHES if name in branches]
    if wings and not body:
        raise ValueError("wing compatibility requires declared torso or neck_head body joint groups")
    if len(wings) == 1:
        raise ValueError("wing compatibility requires both declared wing groups, not a partial pair")
    branch_screen = evaluate_declared_branch_compatibility(vertices=vertices, groups=groups, placement=placement)
    if not wings:
        incompatible = not branch_screen["passed"]
        return {
            "policy": "declared_branch_surface_distances_pending_visual",
            "compatibleUnderRigidAlignment": not incompatible,
            "reason": "capture_mesh_bind_pose_incompatible_under_rigid_alignment" if incompatible else "rigid_alignment_not_visually_confirmed",
            "declaredBranchScreen": branch_screen,
            "wingChecksApplied": False,
            "bboxContainmentIsNotAcceptance": True,
            "imageScoreIsNotAcceptance": True,
        }
    body_surface = float(np.mean([branches[name]["meanSurfaceDistance"] for name in body]))
    wing_surface = float(np.max([branches[name]["meanSurfaceDistance"] for name in wings]))
    span = wing_span(joints, groups)
    width = max(mesh_lateral_span(vertices, axis=0), mesh_lateral_span(vertices, axis=2))
    span_ratio = span / max(width, 1e-8)
    wings_in_core = all(branches[name]["nearMeshCore"] for name in wings)
    incompatible = bool(
        not branch_screen["passed"]
        or wing_surface > body_surface * WING_SURFACE_VS_BODY_SLACK
        or span_ratio > WING_SPAN_RATIO_MAX
        or wings_in_core
    )
    return {
        "policy": "declared_branch_surface_distances_plus_wing_pair_pending_visual",
        "declaredBranchScreen": branch_screen,
        "wingChecksApplied": True,
        "compatibleUnderRigidAlignment": not incompatible,
        "reason": (
            "capture_mesh_bind_pose_incompatible_under_rigid_alignment"
            if incompatible
            else "rigid_alignment_not_visually_confirmed"
        ),
        "bodyMeanSurfaceDistance": body_surface,
        "wingMeanSurfaceDistance": wing_surface,
        "wingSpan": span,
        "meshLateralSpan": width,
        "wingSpanOverMeshWidth": span_ratio,
        "wingsSitInMeshCore": wings_in_core,
        "bboxContainmentIsNotAcceptance": True,
        "imageScoreIsNotAcceptance": True,
    }


def evaluate_declared_branch_compatibility(*, vertices, groups, placement):
    """Coarse all-branch rejection screen, never anatomical/visual acceptance.

    Distances are to sampled mesh vertices, not exact triangle distance. The
    deliberately broad scale-relative limits require a separate visual review.
    """
    mesh = np.asarray(vertices, dtype=np.float64)
    if mesh.ndim != 2 or mesh.shape[1] != 3 or not len(mesh) or not np.isfinite(mesh).all():
        raise ValueError("branch compatibility needs finite nonempty mesh vertices")
    diagonal = float(np.linalg.norm(np.ptp(mesh, axis=0)))
    if not np.isfinite(diagonal) or diagonal <= 0:
        raise ValueError("branch compatibility needs nonzero mesh extent")
    declared = [name for name, indices in groups.items() if len(indices)]
    if not declared:
        raise ValueError("no populated declared branches")
    rows = {}
    for name in declared:
        source = placement["branches"].get(name)
        if source is None:
            raise ValueError(f"missing placement for declared branch {name}")
        mean = float(source["meanSurfaceDistance"]) / diagonal
        maximum = float(source["maxSurfaceDistance"]) / diagonal
        if not np.isfinite([mean, maximum]).all() or mean < 0 or maximum < mean:
            raise ValueError(f"invalid surface distances for branch {name}")
        rows[name] = {"meanDistanceOverDiagonal": mean, "maxDistanceOverDiagonal": maximum,
                      "passed": mean <= BRANCH_MEAN_DISTANCE_DIAGONAL_MAX and maximum <= BRANCH_MAX_DISTANCE_DIAGONAL_MAX}
    return {"passed": all(row["passed"] for row in rows.values()), "branches": rows,
            "failedBranches": [name for name, row in rows.items() if not row["passed"]],
            "meanLimit": BRANCH_MEAN_DISTANCE_DIAGONAL_MAX, "maxLimit": BRANCH_MAX_DISTANCE_DIAGONAL_MAX,
            "distancePolicy": "nearest_mesh_vertex_normalized_by_mesh_diagonal"}


def rest_lbs_identity_error(vertices: np.ndarray, weights: np.ndarray, joints: np.ndarray, parents: np.ndarray) -> float:
    """Exact rest LBS reconstruction error. Zero does not imply anatomy."""
    from donor_eagle import bind_world_matrices, inverse_bind_matrices, skin_dense

    offsets = np.zeros_like(joints)
    offsets[0] = joints[0]
    for i, parent in enumerate(parents):
        if int(parent) >= 0:
            offsets[i] = joints[i] - joints[int(parent)]
    world = bind_world_matrices(offsets, parents)
    ibm = inverse_bind_matrices(world)
    posed = skin_dense(vertices, weights, world, ibm)
    return float(np.linalg.norm(posed - vertices, axis=1).max())


def nearest_bone_weights(vertices: np.ndarray, joints: np.ndarray) -> np.ndarray:
    tree = cKDTree(np.asarray(joints, dtype=np.float64))
    _, nearest = tree.query(np.asarray(vertices, dtype=np.float64), k=1)
    weights = np.zeros((len(vertices), len(joints)), dtype=np.float64)
    weights[np.arange(len(vertices)), nearest] = 1.0
    return weights


def misplaced_skeleton_inside_bbox_rejected(
    *,
    vertices: np.ndarray,
    joints: np.ndarray,
    names: list[str],
    groups: dict[str, list[int]],
) -> dict[str, Any]:
    placement = branch_placement_report(joints=joints, names=names, vertices=vertices, groups=groups)
    inside = placement["bbox"]["jointsInside"]
    compatibility = evaluate_rigid_compatibility(
        joints=joints, names=names, vertices=vertices, groups=groups, placement=placement
    )
    if inside and compatibility["compatibleUnderRigidAlignment"]:
        raise AssertionError("fixture expected bbox-inside + anatomical reject")
    return {"bboxInside": inside, "compatibility": compatibility, "placement": placement}


def distinct_view_candidates(
    scored: list[dict[str, Any]],
    *,
    min_angle_deg: float = MIN_DISTINCT_ANGLE_DEG,
    max_keep: int = MAX_VIEW_CANDIDATES,
    iou_slack: float = IOU_AMBIGUITY_SLACK,
) -> dict[str, Any]:
    ordered = sorted(scored, key=lambda row: (-float(row["iou"]), float(row["total"])))
    kept: list[dict[str, Any]] = []
    for row in ordered:
        rotation = np.asarray(row["rotation"], dtype=np.float64)
        if any(rotation_geodesic_deg(rotation, np.asarray(other["rotation"], dtype=np.float64)) < min_angle_deg for other in kept):
            continue
        kept.append(row)
        if len(kept) >= max_keep:
            break
    if not kept:
        raise ValueError("no view candidates survived clustering")
    best_iou = float(kept[0]["iou"])
    competitors = [
        row
        for row in kept[1:]
        if best_iou - float(row["iou"]) <= iou_slack
        and rotation_geodesic_deg(np.asarray(kept[0]["rotation"]), np.asarray(row["rotation"])) >= min_angle_deg
    ]
    ambiguous = bool(competitors)
    return {
        "candidates": kept,
        "ambiguousOrientation": ambiguous,
        "selectedAutomatically": False,
        "reason": "competing_source_views" if ambiguous else "single_distinct_mode_pending_visual",
    }


def require_mesh_space_rest_report(report, *, mesh_sha256, capture_sha256, unit, bind_frame):
    """Verify coordinate provenance only; this does not accept a registration."""
    expected = {"meshSha256": mesh_sha256, "captureSha256": capture_sha256,
                "unit": unit, "referenceFrame": 0, "restCoordinateSpace": "source_mesh"}
    if bind_frame != 0 or isinstance(bind_frame, bool):
        raise ValueError("mesh-space rest provenance requires bind frame zero")
    for key, value in expected.items():
        if key not in report or report[key] != value or type(report[key]) is not type(value):
            raise ValueError(f"mesh-space rest provenance mismatch: {key}")
    for value in (mesh_sha256, capture_sha256):
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("mesh-space rest provenance requires SHA256 hashes")
    return report


def _complete_joint_branches(groups, joint_count):
    branches = {name: list(indices) for name, indices in groups.items() if len(indices)}
    indices = [index for members in branches.values() for index in members]
    if (not indices or any(isinstance(index, (bool, np.bool_)) or not isinstance(index, (int, np.integer))
                           or index < 0 or index >= joint_count for index in indices)
            or set(indices) != set(range(joint_count)) or len(indices) != len(set(indices))):
        raise ValueError("similarity branches must cover every joint exactly once")
    return branches


def mesh_space_rest_similarity(joints, vertices, groups, *, rotation, yaw_deg, pitch_deg, roll_deg):
    """Preserve verified source-mesh rest placement under the mesh's rotation."""
    joints = np.asarray(joints, dtype=np.float64)
    vertices = np.asarray(vertices, dtype=np.float64)
    rotation = np.asarray(rotation, dtype=np.float64)
    if (joints.ndim != 2 or joints.shape[1] != 3 or not len(joints) or not np.isfinite(joints).all()
            or vertices.ndim != 2 or vertices.shape[1] != 3 or not len(vertices) or not np.isfinite(vertices).all()
            or rotation.shape != (3, 3) or not np.isfinite(rotation).all()
            or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-8)
            or not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-8)):
        raise ValueError("mesh-space rest requires finite geometry and a proper rotation")
    branches = _complete_joint_branches(groups, len(joints))
    placed = joints @ rotation.T
    distances = cKDTree(vertices).query(placed, k=1)[0]
    means = {name: float(distances[indices].mean()) for name, indices in branches.items()}
    diagonal = float(np.linalg.norm(np.ptp(vertices, axis=0)))
    if diagonal <= 0:
        raise ValueError("mesh-space rest requires nonzero mesh extent")
    body = [index for name in BODY_BRANCHES for index in groups.get(name, ())]
    return {"rotation": rotation, "yawDeg": yaw_deg, "pitchDeg": pitch_deg, "rollDeg": roll_deg,
            "scale": 1.0, "translation": np.zeros(3), "joints": placed,
            "bodySurfaceMean": float(distances[body].mean()) if body else None,
            "branchSurfaceMeans": means, "branchBalancedSurfaceMean": float(np.mean(list(means.values()))),
            "skeletonToMeshExtentRatio": float(np.linalg.norm(np.ptp(placed, axis=0))) / diagonal,
            "extentRatioBounds": None, "policy": "verified_source_mesh_rest_same_mesh_rotation_no_refit"}


def fit_skeleton_similarity(
    joints: np.ndarray,
    vertices: np.ndarray,
    groups: dict[str, list[int]],
) -> dict[str, Any]:
    """Bounded global similarity scored equally across every declared branch.

    Whole-skeleton extent and center avoid fitting a torso to the entire mesh.
    The extent band prevents nearest-surface error from winning by shrinking
    the skeleton into a small mesh patch. This remains pending visual review.
    """
    joints = np.asarray(joints, dtype=np.float64)
    vertices = np.asarray(vertices, dtype=np.float64)
    for label, points in (("joints", joints), ("vertices", vertices)):
        if points.ndim != 2 or points.shape[1] != 3 or len(points) < 2 or not np.isfinite(points).all():
            raise ValueError(f"similarity {label} must be finite nonempty [N,3]")
    branches = _complete_joint_branches(groups, len(joints))
    body_idx = [i for name in BODY_BRANCHES for i in branches.get(name, ())]
    mesh_center = (vertices.max(axis=0) + vertices.min(axis=0)) * 0.5
    mesh_span = float(np.linalg.norm(np.ptp(vertices, axis=0)))
    if mesh_span <= 0 or float(np.linalg.norm(np.ptp(joints, axis=0))) <= 0:
        raise ValueError("similarity inputs must have nonzero extent")
    extent_bounds = (0.75, 1.25)
    surface = cKDTree(vertices)
    best = None
    for yaw in range(0, 360, 30):
        for pitch in (-30, 0, 30):
            for roll in (-30, 0, 30):
                rotation = rotation_matrix(yaw, pitch, roll)
                rotated = joints @ rotation.T
                skeleton_center = (rotated.max(axis=0) + rotated.min(axis=0)) * 0.5
                base_scale = mesh_span / float(np.linalg.norm(np.ptp(rotated, axis=0)))
                for scale_factor in (0.75, 0.875, 1.0, 1.125, 1.25):
                    scale = base_scale * scale_factor
                    translation = mesh_center - scale * skeleton_center
                    placed = apply_similarity(joints, rotation=rotation, scale=scale, translation=translation)
                    extent_ratio = float(np.linalg.norm(np.ptp(placed, axis=0))) / mesh_span
                    if not extent_bounds[0] - 1e-9 <= extent_ratio <= extent_bounds[1] + 1e-9:
                        raise RuntimeError("similarity candidate escaped its full-skeleton extent band")
                    distances = surface.query(placed, k=1)[0]
                    branch_means = {name: float(distances[members].mean()) for name, members in branches.items()}
                    score = float(np.mean(list(branch_means.values())))
                    candidate = {
                        "rotation": rotation,
                        "yawDeg": float(yaw),
                        "pitchDeg": float(pitch),
                        "rollDeg": float(roll),
                        "scale": float(scale),
                        "translation": translation,
                        # Legacy wing diagnostic is not applicable to other naming schemas.
                        "bodySurfaceMean": float(distances[body_idx].mean()) if body_idx else None,
                        "branchBalancedSurfaceMean": score,
                        "branchSurfaceMeans": branch_means,
                        "skeletonToMeshExtentRatio": extent_ratio,
                        "extentRatioBounds": list(extent_bounds),
                        "policy": "whole_skeleton_bbox_bounded_similarity_equal_declared_branch_distance",
                        "joints": placed,
                    }
                    if best is None or score < best["branchBalancedSurfaceMean"]:
                        best = candidate
    if best is None:
        raise RuntimeError("skeleton similarity search produced no candidate")
    return best


def decide_static_outcome(
    *,
    views: dict[str, Any],
    compatibility_by_view: list[dict[str, Any]],
) -> dict[str, Any]:
    if views["ambiguousOrientation"]:
        return {
            "status": "ambiguous_orientation",
            "accepted": False,
            "visualConfirmation": False,
            "consumable": False,
            "doesNotProveMeshUnusable": True,
            "nextTaskIfIncompatible": "mesh_specific_rest_skeleton_or_capture_retarget_separately_planned",
            "reasons": ["competing_source_views"],
        }
    if not compatibility_by_view:
        raise ValueError("compatibility_by_view is empty")
    if all(not row["compatibleUnderRigidAlignment"] for row in compatibility_by_view):
        return {
            "status": "incompatible_bind_pose",
            "accepted": False,
            "visualConfirmation": False,
            "consumable": False,
            "doesNotProveMeshUnusable": True,
            "nextTaskIfIncompatible": "mesh_specific_rest_skeleton_or_capture_retarget_separately_planned",
            "reasons": ["capture_mesh_bind_pose_incompatible_under_rigid_alignment"],
        }
    return {
        "status": "pending_visual_confirmation",
        "accepted": False,
        "visualConfirmation": False,
        "consumable": False,
        "doesNotProveMeshUnusable": True,
        "nextTaskIfIncompatible": "mesh_specific_rest_skeleton_or_capture_retarget_separately_planned",
        "reasons": ["visual_confirmation_required"],
    }


def accepted_mesh_alignment(payload: dict[str, Any]) -> dict[str, Any]:
    """Compose the selected mesh view with inverse capture-to-view similarity.

    Projection scale/offset are camera parameters, not 3D mesh transforms.
    Capture joint *directions* stay unchanged. Optional boneLengthScales on
    the selected skeletonSimilarity shorten rest offsets in capture space.
    Row-vector vertices use x @ rotation.T.
    """
    selected = (payload.get("acceptance") or {}).get("selectedCandidateId")
    candidates = (payload.get("views") or {}).get("candidates")
    if not isinstance(selected, str) or not selected or not isinstance(candidates, list):
        raise StaticRegistrationError("accepted registration requires selectedCandidateId and view candidates")
    matches = [row for row in candidates if isinstance(row, dict) and row.get("id") == selected]
    if len(matches) != 1:
        raise StaticRegistrationError("selectedCandidateId must identify exactly one candidate")
    candidate = matches[0]

    def rotation(block: dict[str, Any], label: str) -> np.ndarray:
        value = np.asarray(block.get("rotation"), dtype=np.float64)
        if (value.shape != (3, 3) or not np.isfinite(value).all()
                or not np.allclose(value.T @ value, np.eye(3), atol=1e-6, rtol=0)
                or not np.isclose(np.linalg.det(value), 1.0, atol=1e-6, rtol=0)):
            raise StaticRegistrationError(f"{label}.rotation must be a finite proper orthonormal matrix")
        return value

    try:
        mesh = candidate["meshToSourceView"]
        skeleton = candidate["skeletonSimilarity"]
        rm = rotation(mesh, "meshToSourceView")
        rs = rotation(skeleton, "skeletonSimilarity")
        scale = float(skeleton["scale"])
        translation = np.asarray(skeleton["translation"], dtype=np.float64)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise StaticRegistrationError(f"invalid selected registration transform: {exc}") from exc
    if not np.isfinite(scale) or scale <= 0:
        raise StaticRegistrationError("skeletonSimilarity.scale must be finite and positive")
    if translation.shape != (3,) or not np.isfinite(translation).all():
        raise StaticRegistrationError("skeletonSimilarity.translation must be a finite 3-vector")
    result = {
        "policy": "accepted_static_registration_mesh_to_capture",
        "selectedCandidateId": selected,
        "rotation": (rs.T @ rm).tolist(),
        "scale": 1.0 / scale,
        "translation": (-(translation @ rs) / scale).tolist(),
    }
    if not np.isfinite(result["scale"]) or not np.isfinite(result["translation"]).all():
        raise StaticRegistrationError("selected registration produces a nonfinite inverse similarity")
    return result


def accepted_bone_length_scales(payload: dict[str, Any], joint_count: int) -> np.ndarray:
    """Per-bone rest-length scales from the selected candidate, or ones if omitted."""
    selected = (payload.get("acceptance") or {}).get("selectedCandidateId")
    candidates = (payload.get("views") or {}).get("candidates")
    if not isinstance(selected, str) or not selected or not isinstance(candidates, list):
        raise StaticRegistrationError("accepted registration requires selectedCandidateId and view candidates")
    matches = [row for row in candidates if isinstance(row, dict) and row.get("id") == selected]
    if len(matches) != 1:
        raise StaticRegistrationError("selectedCandidateId must identify exactly one candidate")
    skeleton = matches[0].get("skeletonSimilarity")
    if not isinstance(skeleton, dict):
        raise StaticRegistrationError("selected candidate is missing skeletonSimilarity")
    raw = skeleton.get("boneLengthScales")
    if raw is None:
        return np.ones(int(joint_count), dtype=np.float64)
    scales = np.asarray(raw, dtype=np.float64)
    if scales.shape != (int(joint_count),) or not np.isfinite(scales).all() or np.any(scales <= 0):
        raise StaticRegistrationError(
            f"skeletonSimilarity.boneLengthScales must be {joint_count} positive finite values"
        )
    return scales


def accepted_bind_rest_joints(payload: dict[str, Any], joint_count: int) -> np.ndarray | None:
    """Bind-first rest joints in capture space, if the selected candidate recorded them."""
    selected = (payload.get("acceptance") or {}).get("selectedCandidateId")
    candidates = (payload.get("views") or {}).get("candidates")
    if not isinstance(selected, str) or not selected or not isinstance(candidates, list):
        raise StaticRegistrationError("accepted registration requires selectedCandidateId and view candidates")
    matches = [row for row in candidates if isinstance(row, dict) and row.get("id") == selected]
    if len(matches) != 1:
        raise StaticRegistrationError("selectedCandidateId must identify exactly one candidate")
    skeleton = matches[0].get("skeletonSimilarity")
    if not isinstance(skeleton, dict):
        raise StaticRegistrationError("selected candidate is missing skeletonSimilarity")
    raw = skeleton.get("bindRestJoints")
    if raw is None:
        return None
    joints = np.asarray(raw, dtype=np.float64)
    if joints.shape != (int(joint_count), 3) or not np.isfinite(joints).all():
        raise StaticRegistrationError(
            f"skeletonSimilarity.bindRestJoints must be [{joint_count},3] finite coordinates"
        )
    return joints


def require_bind_registration(sidecar: dict[str, Any], payload: dict[str, Any], registration_sha256: str) -> None:
    """Reject cached binds made with a different or unrecorded placement."""
    expected = accepted_mesh_alignment(payload)
    provenance = sidecar.get("staticRegistration") or {}
    if (provenance.get("sha256") != registration_sha256
            or provenance.get("selectedCandidateId") != expected["selectedCandidateId"]
            or sidecar.get("surfaceAlignment") != expected):
        raise StaticRegistrationError("bind placement does not match accepted static registration; rebuild the bind explicitly")


def load_static_registration(path: Path) -> dict[str, Any]:
    if path is None:
        raise StaticRegistrationError("static registration artifact path is missing")
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise StaticRegistrationError(f"static registration schema must be {SCHEMA}")
    return payload


def require_accepted_static_registration(
    path: Path | None,
    *,
    mesh_sha256: str,
    capture_sha256: str,
    bind_frame: int,
) -> dict[str, Any]:
    if path is None:
        raise StaticRegistrationError(
            "downstream bind/skin fitting requires an accepted static registration artifact"
        )
    payload = load_static_registration(Path(path))
    acceptance = payload.get("acceptance") or {}
    hashes = payload.get("inputHashes") or {}
    if hashes.get("mesh") != mesh_sha256:
        raise StaticRegistrationError("static registration mesh hash does not match this mesh")
    if hashes.get("capture") != capture_sha256:
        raise StaticRegistrationError("static registration capture hash does not match this capture")
    if int(payload.get("bindFrame", -1)) != int(bind_frame):
        raise StaticRegistrationError("static registration bind frame does not match this bind frame")
    if acceptance.get("status") != "accepted" or acceptance.get("visualConfirmation") is not True or acceptance.get("accepted") is not True:
        raise StaticRegistrationError(
            f"static registration is not accepted (status={acceptance.get('status')!r}); "
            "fitting cannot consume an unverified registration"
        )
    if acceptance.get("consumable") is not True:
        raise StaticRegistrationError("static registration is not marked consumable")
    accepted_mesh_alignment(payload)
    return payload
