"""Exact Eagle donor contract for the Roc-copy skinning experiment.

The capture skeleton is the unmodified Eagle#Eagle-Landing/y15 BVH. Character
folder `rest.bvh` is the same hierarchy at 100x Blender scale and is not the
capture bind. Landing frame 0 is a posed clip; bind is T-pose from offsets.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from mesh_preview import fk_world_matrices
from paths import VENDOR, VENDOR_DEMO, require_file
from pin import sha256_file
from vendor_reference import load_bvh_skeleton, load_complete_package, refuse_skeleton_mutation

EAGLE_REF_SEQ = "Eagle#Eagle-Landing/y15"
EAGLE_KIND = "zoo"
EXPECTED_JOINT_COUNT = 50
EXPECTED_WEIGHT_ROWS = 2234
BIND_IDENTITY_MAX = 1e-5
INDEX_ALIGN_MAX = 1e-5
OFFSET_SCALE_REST_TO_CAPTURE = 100.0
OFFSET_SCALE_TOL = 0.05

# Verified blender_vertices -> OBJ: Q = s R P + t, det(R)=+1, same row index.
BLENDER_TO_OBJ_SCALE = 1.0e-4
BLENDER_TO_OBJ_ROTATION = np.array(
    ((0.0, -1.0, 0.0), (0.0, 0.0, -1.0), (1.0, 0.0, 0.0)),
    dtype=np.float64,
)

REGION_JOINTS = {
    "torso": ("Hips", "Bip01_Pelvis", "Bip01_Spine", "Bip01_Spine1"),
    "neck_head": ("Bip01_Neck", "Bip01_Neck1", "Bip01_Neck2", "Bip01_Head"),
    "beak": ("BN_Jaw",),
    "wing_left": (
        "BN_Wing_L_01",
        "BN_Wing_L_02",
        "BN_Wing_L_03",
        "BN_Wing_L_04",
        "BN_Wing_L_05",
        "BN_Wing_L_06",
    ),
    "wing_right": (
        "BN_Wing_R_01",
        "BN_Wing_R_02",
        "BN_Wing_R_03",
        "BN_Wing_R_04",
        "BN_Wing_R_05",
        "BN_Wing_R_06",
    ),
    "tail": ("BN_Tai_01", "BN_Tai_R_01", "BN_Tai_R_02", "BN_Tai_L_01", "BN_Tai_L_02"),
    "leg_left": (
        "Bip01_L_Thigh",
        "Bip01_L_Calf",
        "Bip01_L_HorseLink",
        "Bip01_L_Foot",
        "BN_Toe_L_00",
        "BN_Toe_L_01",
        "BN_Toe_L_10",
        "BN_Toe_L_11",
        "BN_Toe_L_20",
        "BN_Toe_L_21",
        "BN_Toe_L_30",
        "BN_Toe_L_31",
    ),
    "leg_right": (
        "Bip01_R_Thigh",
        "Bip01_R_Calf",
        "Bip01_R_HorseLink",
        "Bip01_R_Foot",
        "BN_Toe_R_00",
        "BN_Toe_R_01",
        "BN_Toe_R_10",
        "BN_Toe_R_11",
        "BN_Toe_R_20",
        "BN_Toe_R_21",
        "BN_Toe_R_30",
        "BN_Toe_R_31",
    ),
}

RIGID_REGIONS = frozenset({"beak"})
CLAW_JOINTS = frozenset(
    {
        "Bip01_L_Foot",
        "Bip01_R_Foot",
        "BN_Toe_L_00",
        "BN_Toe_L_01",
        "BN_Toe_L_10",
        "BN_Toe_L_11",
        "BN_Toe_L_20",
        "BN_Toe_L_21",
        "BN_Toe_L_30",
        "BN_Toe_L_31",
        "BN_Toe_R_00",
        "BN_Toe_R_01",
        "BN_Toe_R_10",
        "BN_Toe_R_11",
        "BN_Toe_R_20",
        "BN_Toe_R_21",
        "BN_Toe_R_30",
        "BN_Toe_R_31",
    }
)


def _vendor_on_path() -> None:
    vendor = str(VENDOR)
    if vendor not in sys.path:
        sys.path.insert(0, vendor)


def character_dir() -> Path:
    return VENDOR_DEMO / "zoo1030" / "characters_fix_facezplus" / "Eagle"


def read_obj_template(obj_path: Path) -> dict[str, Any]:
    """Parse OBJ with vendor vertex indexing. Faces are 0-based v / vt corners."""
    _vendor_on_path()
    from utils.mesh import read_obj_mesh

    vertices, faces, uvs, face_uvs = read_obj_mesh(str(require_file(obj_path, label="donor OBJ")))
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise ValueError(f"OBJ vertices must be [V,3], got {vertices.shape}")
    if faces.ndim != 2 or faces.shape[1] != 3:
        raise ValueError(f"OBJ faces must be [F,3], got {faces.shape}")
    if int(faces.min()) < 0 or int(faces.max()) >= len(vertices):
        raise ValueError("OBJ face indices are outside the vertex list")
    uv_arr = None if uvs is None else np.asarray(uvs, dtype=np.float64)
    face_uv_arr = None if face_uvs is None else np.asarray(face_uvs, dtype=np.int64)
    unique_v = len({tuple(np.round(row, 6)) for row in vertices})
    return {
        "vertices": vertices,
        "faces": faces,
        "uvs": uv_arr,
        "faceUvs": face_uv_arr,
        "vertexCount": int(len(vertices)),
        "faceCount": int(len(faces)),
        "uvCount": None if uv_arr is None else int(len(uv_arr)),
        "uniquePositionCount": int(unique_v),
        "cornerCount": int(faces.size),
        "usesSeparateUvIndex": bool(uv_arr is not None and face_uv_arr is not None),
    }


def blender_to_obj(points: np.ndarray) -> np.ndarray:
    values = np.asarray(points, dtype=np.float64)
    return (BLENDER_TO_OBJ_SCALE * (BLENDER_TO_OBJ_ROTATION @ values.T).T)


def compute_rest_joints(offsets: np.ndarray, parents: np.ndarray) -> np.ndarray:
    bone = np.asarray(offsets, dtype=np.float64)
    parent = np.asarray(parents, dtype=np.int64)
    joints = np.zeros_like(bone)
    for index in range(len(parent)):
        parent_index = int(parent[index])
        if parent_index < 0:
            joints[index] = bone[index]
        else:
            joints[index] = joints[parent_index] + bone[index]
    return joints


def identity_local_rotation(joint_count: int) -> np.ndarray:
    out = np.zeros((joint_count, 3, 3), dtype=np.float64)
    out[:] = np.eye(3, dtype=np.float64)
    return out


def bind_world_matrices(offsets: np.ndarray, parents: np.ndarray) -> np.ndarray:
    rest = compute_rest_joints(offsets, parents)
    parent = np.asarray(parents, dtype=np.int64)
    local_t = np.asarray(offsets, dtype=np.float64).copy()
    local_t[0] = 0.0
    return fk_world_matrices(
        local_rotation=identity_local_rotation(len(parent)),
        local_translation=local_t,
        parents=parent,
        root_world=rest[0],
    )


def inverse_bind_matrices(bind_world: np.ndarray) -> np.ndarray:
    out = np.zeros_like(bind_world)
    for index, matrix in enumerate(bind_world):
        out[index] = np.linalg.inv(matrix)
    return out


def skin_dense(
    vertices: np.ndarray,
    weights: np.ndarray,
    joint_world: np.ndarray,
    inverse_bind: np.ndarray,
) -> np.ndarray:
    verts = np.asarray(vertices, dtype=np.float64)
    skin = np.asarray(weights, dtype=np.float64)
    if skin.shape[0] != len(verts):
        raise ValueError(f"weights {skin.shape} do not match vertices {verts.shape}")
    if skin.shape[1] != joint_world.shape[0]:
        raise ValueError(f"weight columns {skin.shape[1]} do not match joints {joint_world.shape[0]}")
    if not np.isfinite(skin).all() or np.any(skin < -1e-8):
        raise ValueError("skin weights must be finite and nonnegative")
    row = skin.sum(axis=1)
    if np.any(row < 1e-6):
        raise ValueError("skin weights leave vertices uncovered")
    skin = skin / row[:, None]
    palette = np.matmul(joint_world, inverse_bind)
    hom = np.concatenate([verts, np.ones((len(verts), 1), dtype=np.float64)], axis=1)
    posed = np.zeros_like(verts)
    for joint_index in range(skin.shape[1]):
        posed += skin[:, joint_index : joint_index + 1] * (hom @ palette[joint_index].T)[:, :3]
    return posed


def region_for_joint(name: str) -> str:
    for region, names in REGION_JOINTS.items():
        if name in names:
            return region
    raise KeyError(f"no anatomical region for joint {name!r}")


def joint_region_ids(names: list[str]) -> list[str]:
    mapped = [region_for_joint(name) for name in names]
    extra = {item for group in REGION_JOINTS.values() for item in group} - set(names)
    if extra:
        raise ValueError(f"region table names missing from skeleton: {sorted(extra)}")
    return mapped


def load_donor_package() -> dict[str, Any]:
    package = load_complete_package(EAGLE_KIND, EAGLE_REF_SEQ)
    folder = character_dir()
    obj_path = require_file(folder / "base_mesh.obj", label="Eagle OBJ")
    blender_path = require_file(folder / "blender_vertices.npy", label="Eagle blender_vertices")
    weight_path = require_file(folder / "skinning_weights.npy", label="Eagle skinning_weights")
    rest_bvh = require_file(folder / "rest.bvh", label="Eagle rest.bvh")
    ffs_bvh = require_file(folder / "Eagle_ffs.bvh", label="Eagle_ffs.bvh")
    texture = require_file(folder / "texmap0.png", label="Eagle texmap0")
    front_path = require_file(folder / "front.npy", label="Eagle front.npy")
    symmetry_path = require_file(folder / "symmetry_info.json", label="Eagle symmetry_info")
    obj = read_obj_template(obj_path)
    blender = np.load(blender_path)
    weights = np.load(weight_path)
    rest_skel = load_bvh_skeleton(rest_bvh)
    ffs_skel = load_bvh_skeleton(ffs_bvh)
    capture_skel = {
        "jointNames": list(package["jointNames"]),
        "parents": np.asarray(package["parents"], dtype=np.int64),
        "offsets": np.asarray(package["offsets"], dtype=np.float64),
    }
    refuse_skeleton_mutation(
        original_names=capture_skel["jointNames"],
        proposed_names=list(rest_skel["jointNames"]),
    )
    refuse_skeleton_mutation(
        original_names=capture_skel["jointNames"],
        proposed_names=list(ffs_skel["jointNames"]),
    )
    return {
        "package": package,
        "characterDir": folder,
        "objPath": obj_path,
        "obj": obj,
        "blenderVertices": np.asarray(blender, dtype=np.float64),
        "weights": np.asarray(weights, dtype=np.float64),
        "restSkeleton": rest_skel,
        "ffsSkeleton": ffs_skel,
        "captureSkeleton": capture_skel,
        "texturePath": texture,
        "frontBlender": np.asarray(np.load(front_path), dtype=np.float64),
        "symmetry": json.loads(symmetry_path.read_text(encoding="utf-8")),
        "fileSha256": {
            "obj": sha256_file(obj_path),
            "blenderVertices": sha256_file(blender_path),
            "weights": sha256_file(weight_path),
            "restBvh": sha256_file(rest_bvh),
            "ffsBvh": sha256_file(ffs_bvh),
            "texture": sha256_file(texture),
            "captureBvh": package["fileSha256"]["bvh"],
            "pose": package["fileSha256"]["pose"],
            "train": package["fileSha256"]["train"],
        },
    }


def verify_vertex_indexing(donor: dict[str, Any]) -> dict[str, Any]:
    obj_v = donor["obj"]["vertices"]
    blender = donor["blenderVertices"]
    weights = donor["weights"]
    names = donor["captureSkeleton"]["jointNames"]
    if obj_v.shape[0] != EXPECTED_WEIGHT_ROWS:
        raise ValueError(f"OBJ vertex count {obj_v.shape[0]} != expected {EXPECTED_WEIGHT_ROWS}")
    if blender.shape != (EXPECTED_WEIGHT_ROWS, 3):
        raise ValueError(f"blender_vertices shape {blender.shape} != ({EXPECTED_WEIGHT_ROWS}, 3)")
    if weights.shape != (EXPECTED_WEIGHT_ROWS, EXPECTED_JOINT_COUNT):
        raise ValueError(
            f"skinning_weights shape {weights.shape} != ({EXPECTED_WEIGHT_ROWS}, {EXPECTED_JOINT_COUNT})"
        )
    if len(names) != EXPECTED_JOINT_COUNT:
        raise ValueError(f"capture joint count {len(names)} != {EXPECTED_JOINT_COUNT}")
    reconstructed = blender_to_obj(blender)
    index_err = np.linalg.norm(reconstructed - obj_v, axis=1)
    if float(index_err.max()) > INDEX_ALIGN_MAX:
        raise ValueError(
            f"OBJ vertex rows are not the same mesh as blender_vertices under the verified "
            f"similarity (max {index_err.max()})"
        )
    unique_obj = donor["obj"]["uniquePositionCount"]
    unique_blender = len({tuple(np.round(row, 6)) for row in blender})
    if unique_obj == obj_v.shape[0] and unique_blender == blender.shape[0]:
        weld_note = "no welded duplicates"
    else:
        weld_note = (
            f"OBJ unique positions {unique_obj}/{obj_v.shape[0]}; "
            f"blender unique {unique_blender}/{blender.shape[0]}; "
            "UV/exporter duplicates exist; weights stay on the 2234 exported rows, not the unique set"
        )
    if donor["obj"]["usesSeparateUvIndex"]:
        uv_note = (
            f"OBJ stores {donor['obj']['uvCount']} vt entries and {donor['obj']['faceCount']} "
            "face-corner UV indices separate from v indices"
        )
    else:
        uv_note = "OBJ has no separate UV index"
    if not np.isfinite(weights).all() or np.any(weights < -1e-8):
        raise ValueError("donor weights are not finite nonnegative")
    row_sum = weights.sum(axis=1)
    if np.any(row_sum < 0.999) or np.any(row_sum > 1.001):
        raise ValueError("donor weights are not normalized per vertex")
    joint_regions = joint_region_ids(names)
    left_x = compute_rest_joints(
        donor["captureSkeleton"]["offsets"], donor["captureSkeleton"]["parents"]
    )
    name_index = {name: index for index, name in enumerate(names)}
    left_wing = left_x[name_index["BN_Wing_L_04"]] - left_x[name_index["Hips"]]
    right_wing = left_x[name_index["BN_Wing_R_04"]] - left_x[name_index["Hips"]]
    if float(left_wing[0]) <= 0 or float(right_wing[0]) >= 0:
        raise ValueError(
            f"anatomical L/R failed: left wing X={left_wing[0]}, right wing X={right_wing[0]}"
        )
    det = float(np.linalg.det(BLENDER_TO_OBJ_ROTATION))
    if det <= 0:
        raise ValueError("blender-to-OBJ rotation is not orientation-preserving")
    return {
        "objVertexCount": int(obj_v.shape[0]),
        "blenderVertexCount": int(blender.shape[0]),
        "weightRows": int(weights.shape[0]),
        "weightColumns": int(weights.shape[1]),
        "sameRowIndex": True,
        "indexAlignMax": float(index_err.max()),
        "blenderToObjScale": BLENDER_TO_OBJ_SCALE,
        "blenderToObjRotation": BLENDER_TO_OBJ_ROTATION.tolist(),
        "blenderToObjDet": det,
        "uniquePositions": weld_note,
        "uvIndexing": uv_note,
        "jointRegions": joint_regions,
        "leftWingRestOffset": left_wing.tolist(),
        "rightWingRestOffset": right_wing.tolist(),
        "leftIsPlusX": True,
    }


def verify_bind_and_scale(donor: dict[str, Any]) -> dict[str, Any]:
    capture = donor["captureSkeleton"]
    rest = donor["restSkeleton"]
    ffs = donor["ffsSkeleton"]
    cap_off = np.asarray(capture["offsets"], dtype=np.float64)
    rest_off = np.asarray(rest["offsets"], dtype=np.float64)
    ffs_off = np.asarray(ffs["offsets"], dtype=np.float64)
    ratio = np.linalg.norm(rest_off, axis=1) / np.maximum(np.linalg.norm(cap_off, axis=1), 1e-12)
    nonzero = np.linalg.norm(cap_off, axis=1) > 1e-8
    if float(np.max(np.abs(ratio[nonzero] - OFFSET_SCALE_REST_TO_CAPTURE))) > OFFSET_SCALE_TOL * OFFSET_SCALE_REST_TO_CAPTURE:
        raise ValueError(f"rest.bvh offsets are not {OFFSET_SCALE_REST_TO_CAPTURE}x capture offsets")
    if float(np.abs(ffs_off - cap_off).max()) > 1e-4:
        raise ValueError("Eagle_ffs.bvh offsets drifted from the capture BVH")
    bind = bind_world_matrices(cap_off, capture["parents"])
    ibm = inverse_bind_matrices(bind)
    identity = np.matmul(bind, ibm)
    ident_err = float(np.abs(identity - np.eye(4)[None, :, :]).max())
    if ident_err > 1e-8:
        raise ValueError(f"inverse bind is not inverse of bind world ({ident_err})")
    posed = skin_dense(donor["obj"]["vertices"], donor["weights"], bind, ibm)
    bind_err = np.linalg.norm(posed - donor["obj"]["vertices"], axis=1)
    if float(bind_err.max()) > BIND_IDENTITY_MAX:
        raise ValueError(f"bind-pose skinning is not identity: max {bind_err.max()}")
    landing = donor["package"]["anim"]
    frame0_aa = _quat_to_axis_angle(np.asarray(landing.rotations[0]))
    if float(np.linalg.norm(frame0_aa, axis=-1).max()) < 1e-4:
        raise ValueError("landing frame 0 is identity; the posed-vs-bind distinction was not checked")
    return {
        "captureOffsetEqualsPackage": True,
        "restBvhIs100xCaptureOffsets": True,
        "ffsMatchesCaptureOffsets": True,
        "bindIsOffsetTPose": True,
        "landingFrame0IsPosed": True,
        "landingFrame0AxisAngleMax": float(np.linalg.norm(frame0_aa, axis=-1).max()),
        "bindSkinIdentityMax": float(bind_err.max()),
        "inverseBindIdentityMax": ident_err,
        "rootCenteredCapture": True,
    }


def _quat_to_axis_angle(quat_wxyz: np.ndarray) -> np.ndarray:
    values = np.asarray(quat_wxyz, dtype=np.float64)
    if values.shape[-1] != 4:
        raise ValueError(f"quaternion must be [...,4], got {values.shape}")
    w = np.clip(values[..., 0], -1.0, 1.0)
    xyz = values[..., 1:4]
    angle = 2.0 * np.arccos(np.abs(w))
    axis = xyz / np.maximum(np.linalg.norm(xyz, axis=-1, keepdims=True), 1e-12)
    sign = np.where(w[..., None] < 0.0, -1.0, 1.0)
    return axis * (angle[..., None] * sign)


def quat_wxyz_to_matrix(quat_wxyz: np.ndarray) -> np.ndarray:
    values = np.asarray(quat_wxyz, dtype=np.float64)
    w, x, y, z = values[..., 0], values[..., 1], values[..., 2], values[..., 3]
    matrix = np.empty(values.shape[:-1] + (3, 3), dtype=np.float64)
    matrix[..., 0, 0] = 1 - 2 * (y * y + z * z)
    matrix[..., 0, 1] = 2 * (x * y - z * w)
    matrix[..., 0, 2] = 2 * (x * z + y * w)
    matrix[..., 1, 0] = 2 * (x * y + z * w)
    matrix[..., 1, 1] = 1 - 2 * (x * x + z * z)
    matrix[..., 1, 2] = 2 * (y * z - x * w)
    matrix[..., 2, 0] = 2 * (x * z - y * w)
    matrix[..., 2, 1] = 2 * (y * z + x * w)
    matrix[..., 2, 2] = 1 - 2 * (x * x + y * y)
    return matrix


def verify_known_motion_joints(donor: dict[str, Any]) -> dict[str, Any]:
    """FK from landing BVH local rotations vs vendor LBS joints, T-pose bind."""
    capture = donor["captureSkeleton"]
    anim = donor["package"]["anim"]
    local = quat_wxyz_to_matrix(np.asarray(anim.rotations, dtype=np.float64))
    offsets = np.asarray(capture["offsets"], dtype=np.float64).copy()
    root_offset = offsets[0].copy()
    offsets[0] = 0.0
    parents = np.asarray(capture["parents"], dtype=np.int64)
    rest = compute_rest_joints(capture["offsets"], parents)
    bind = bind_world_matrices(capture["offsets"], parents)
    ibm = inverse_bind_matrices(bind)
    trans = np.asarray(anim.positions, dtype=np.float64)[:, 0] - root_offset
    fk_pos = []
    for frame, rotation in enumerate(local):
        world = fk_world_matrices(
            local_rotation=rotation,
            local_translation=offsets,
            parents=parents,
            root_world=rest[0] + trans[frame],
        )
        fk_pos.append(world[:, :3, 3])
    fk_pos = np.stack(fk_pos)
    sample = [0, len(local) // 2, len(local) - 1]
    verts0 = skin_dense(donor["obj"]["vertices"], donor["weights"], bind, ibm)
    bind_move = float(np.linalg.norm(verts0 - donor["obj"]["vertices"], axis=1).max())
    mid = sample[1]
    world_mid = fk_world_matrices(
        local_rotation=local[mid],
        local_translation=offsets,
        parents=parents,
        root_world=rest[0] + trans[mid],
    )
    verts_mid = skin_dense(donor["obj"]["vertices"], donor["weights"], world_mid, ibm)
    motion = float(np.linalg.norm(verts_mid - verts0, axis=1).max())
    if motion < 1e-3:
        raise ValueError("known-motion donor mesh did not move")
    return {
        "frameCount": int(len(local)),
        "bindSkinIdentityMax": bind_move,
        "knownMotionVertexTravelMax": motion,
        "fkRootUsesBvhTranslation": True,
        "sampleFrames": sample,
        "fkPositionsShape": list(fk_pos.shape),
    }


def explicit_spaces(donor: dict[str, Any]) -> dict[str, Any]:
    """One named transform chain. Presentation is capture/OBJ space, not per-panel fit."""
    front_obj = BLENDER_TO_OBJ_ROTATION @ donor["frontBlender"]
    rest = compute_rest_joints(
        donor["captureSkeleton"]["offsets"], donor["captureSkeleton"]["parents"]
    )
    return {
        "captureSpace": "eagle_landing_y15_bvh_and_pred_position",
        "objMeshSpace": "base_mesh.obj_equals_capture_scale_family",
        "blenderMeshSpace": "blender_vertices.npy",
        "blenderToObj": {
            "scale": BLENDER_TO_OBJ_SCALE,
            "rotation": BLENDER_TO_OBJ_ROTATION.tolist(),
            "det": float(np.linalg.det(BLENDER_TO_OBJ_ROTATION)),
            "sameRowIndex": True,
        },
        "bindJoints": "compute_rest_joints(y15.offsets) T-pose, identity local rotation",
        "notBind": [
            "landing BVH frame 0 (posed)",
            "Roc flight capture frame 0",
            "character rest.bvh 100x offsets",
        ],
        "frontBlender": donor["frontBlender"].tolist(),
        "frontObj": front_obj.tolist(),
        "handedness": "det(blenderToObj)=+1; Eagle left wing is +X in capture/OBJ rest",
        "presentation": {
            "space": "captureSpace",
            "frontBasis": ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
            "sideBasis": ((0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
            "topBasis": ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0)),
            "undersideBasis": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            "perPanelAutofit": False,
        },
        "restJointSpan": (rest.max(0) - rest.min(0)).tolist(),
    }


def obj_vertex_uvs(obj: dict[str, Any]) -> np.ndarray:
    """Promote face-corner UVs onto vertex rows. Seams keep the first corner."""
    count = int(obj["vertexCount"])
    uvs = np.zeros((count, 2), dtype=np.float64)
    vt = obj["uvs"]
    face_uvs = obj["faceUvs"]
    if vt is None or face_uvs is None:
        return uvs
    assigned = np.zeros(count, dtype=bool)
    for face, corners in zip(obj["faces"], face_uvs):
        for vertex, uv_index in zip(face, corners):
            if not assigned[int(vertex)]:
                uvs[int(vertex)] = vt[int(uv_index)]
                assigned[int(vertex)] = True
    return uvs


def verify_donor_contract() -> dict[str, Any]:
    donor = load_donor_package()
    indexing = verify_vertex_indexing(donor)
    bind = verify_bind_and_scale(donor)
    motion = verify_known_motion_joints(donor)
    spaces = explicit_spaces(donor)
    return {
        "ok": True,
        "refSeq": EAGLE_REF_SEQ,
        "jointNames": donor["captureSkeleton"]["jointNames"],
        "indexing": indexing,
        "bind": bind,
        "knownMotion": motion,
        "spaces": spaces,
        "fileSha256": donor["fileSha256"],
        "characterDir": str(donor["characterDir"]).replace("\\", "/"),
    }
