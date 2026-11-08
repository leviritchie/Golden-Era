"""Load a donor character for hidden-proxy transfer. Capture packages stay immutable."""
from __future__ import annotations

from typing import Any

import numpy as np

from donor_eagle import (
    bind_world_matrices,
    compute_rest_joints,
    inverse_bind_matrices,
    load_donor_package,
    read_obj_template,
    skin_dense,
)
from paths import require_file
from pin import sha256_file
from vendor_reference import load_bvh_skeleton, load_complete_package, refuse_skeleton_mutation


def region_for_joint(name: str, region_joints: dict[str, tuple[str, ...]]) -> str:
    for region, names in region_joints.items():
        if name in names:
            return region
    raise KeyError(f"no anatomical region for joint {name!r}")


def joint_region_ids(names: list[str], region_joints: dict[str, tuple[str, ...]]) -> list[str]:
    mapped = [region_for_joint(name, region_joints) for name in names]
    extra = {item for group in region_joints.values() for item in group} - set(names)
    if extra:
        raise ValueError(f"region table names missing from skeleton: {sorted(extra)}")
    return mapped


def load_eagle_donor(profile: dict[str, Any]) -> dict[str, Any]:
    donor = load_donor_package()
    names = list(donor["captureSkeleton"]["jointNames"])
    refuse_skeleton_mutation(original_names=names, proposed_names=names)
    return {
        **donor,
        "regionJoints": profile["regionJoints"],
        "jointRegions": joint_region_ids(names, profile["regionJoints"]),
        "bindOffsets": np.asarray(donor["captureSkeleton"]["offsets"], dtype=np.float64),
        "bindParents": np.asarray(donor["captureSkeleton"]["parents"], dtype=np.int64),
        "jointNames": names,
        "meshVertices": np.asarray(donor["obj"]["vertices"], dtype=np.float64),
        "meshFaces": np.asarray(donor["obj"]["faces"], dtype=np.int64),
        "meshWeights": np.asarray(donor["weights"], dtype=np.float64),
        "objIsWeightRowAuthority": True,
        "blenderToObjVerified": True,
        "spaces": {
            "captureSpace": "eagle_landing_y15_bvh_and_pred_position",
            "donorMeshSpace": "base_mesh.obj",
            "targetBindSpace": "original_visible_mesh",
            "presentation": "target_bind_space_root_aligned_capture_no_baked_scale",
        },
    }


def _obj_weight_row_report(obj_vertices: np.ndarray, blender: np.ndarray) -> dict[str, Any]:
    if obj_vertices.shape != blender.shape:
        raise ValueError(f"OBJ {obj_vertices.shape} and blender_vertices {blender.shape} are not the same rows")
    raw = float(np.linalg.norm(obj_vertices - blender, axis=1).max())
    pc = blender - blender.mean(0)
    qc = obj_vertices - obj_vertices.mean(0)
    covariance = pc.T @ qc
    u, _singular, vh = np.linalg.svd(covariance)
    rotation = vh.T @ u.T
    if float(np.linalg.det(rotation)) < 0:
        vh[-1] *= -1
        rotation = vh.T @ u.T
    scale = float(np.linalg.norm(qc) / max(float(np.linalg.norm(pc)), 1e-12))
    translation = obj_vertices.mean(0) - scale * (rotation @ blender.mean(0))
    reconstructed = (scale * (rotation @ blender.T).T) + translation
    residual = float(np.linalg.norm(reconstructed - obj_vertices, axis=1).max())
    return {
        "objIsWeightRowAuthority": True,
        "rawBlenderObjMax": raw,
        "similarityResidualMax": residual,
        "similarityScale": scale,
        "similarityRotationDet": float(np.linalg.det(rotation)),
        "usedForSkinning": "obj_vertices_not_blender",
        "note": "Mixamo blender_vertices do not share Eagle's 1e-4 verified similarity; OBJ rows own the weights.",
    }


def load_mixamo_donor(profile: dict[str, Any]) -> dict[str, Any]:
    package = load_complete_package(str(profile["donorKind"]), str(profile["donorRefSeq"]))
    folder = profile["donorCharacterDir"]
    obj_path = require_file(folder / "base_mesh.obj", label="Mixamo OBJ")
    blender_path = require_file(folder / "blender_vertices.npy", label="Mixamo blender_vertices")
    weight_path = require_file(folder / "skinning_weights.npy", label="Mixamo skinning_weights")
    rest_bvh = require_file(folder / "rest.bvh", label="Mixamo rest.bvh")
    ffs_bvh = require_file(folder / f"{folder.name}_ffs.bvh", label="Mixamo ffs.bvh")
    obj = read_obj_template(obj_path)
    blender = np.asarray(np.load(blender_path), dtype=np.float64)
    weights = np.asarray(np.load(weight_path), dtype=np.float64)
    rest_skel = load_bvh_skeleton(rest_bvh)
    ffs_skel = load_bvh_skeleton(ffs_bvh)
    capture_names = list(package["jointNames"])
    refuse_skeleton_mutation(original_names=capture_names, proposed_names=list(rest_skel["jointNames"]))
    refuse_skeleton_mutation(original_names=capture_names, proposed_names=list(ffs_skel["jointNames"]))
    if weights.shape[0] != obj["vertexCount"]:
        raise ValueError(f"weight rows {weights.shape[0]} != OBJ vertices {obj['vertexCount']}")
    if weights.shape[1] != len(capture_names):
        raise ValueError(f"weight columns {weights.shape[1]} != joints {len(capture_names)}")
    indexing = _obj_weight_row_report(obj["vertices"], blender)
    ffs_off = np.asarray(ffs_skel["offsets"], dtype=np.float64)
    rest_off = np.asarray(rest_skel["offsets"], dtype=np.float64)
    package_off = np.asarray(package["offsets"], dtype=np.float64)
    if float(np.abs(ffs_off - package_off).max()) > 1e-4:
        raise ValueError("Mixamo ffs.bvh offsets drifted from the capture package")
    ratio = np.linalg.norm(rest_off, axis=1) / np.maximum(np.linalg.norm(ffs_off, axis=1), 1e-12)
    nonzero = np.linalg.norm(ffs_off, axis=1) > 1e-8
    if float(np.max(np.abs(ratio[nonzero] - 100.0))) > 5.0:
        raise ValueError("Mixamo rest.bvh is not 100x capture-scale ffs offsets")
    bind = bind_world_matrices(ffs_off, ffs_skel["parents"])
    ibm = inverse_bind_matrices(bind)
    posed = skin_dense(obj["vertices"], weights, bind, ibm)
    bind_err = float(np.linalg.norm(posed - obj["vertices"], axis=1).max())
    if bind_err > 1e-5:
        raise ValueError(f"Mixamo bind-pose skinning is not identity: max {bind_err}")
    names = capture_names
    return {
        "package": package,
        "characterDir": folder,
        "objPath": obj_path,
        "obj": obj,
        "blenderVertices": blender,
        "weights": weights,
        "restSkeleton": rest_skel,
        "ffsSkeleton": ffs_skel,
        "captureSkeleton": {
            "jointNames": names,
            "parents": np.asarray(package["parents"], dtype=np.int64),
            "offsets": package_off,
        },
        "texturePath": None,
        "fileSha256": {
            "obj": sha256_file(obj_path),
            "blenderVertices": sha256_file(blender_path),
            "weights": sha256_file(weight_path),
            "restBvh": sha256_file(rest_bvh),
            "ffsBvh": sha256_file(ffs_bvh),
            "captureBvh": package["fileSha256"]["bvh"],
        },
        "regionJoints": profile["regionJoints"],
        "jointRegions": joint_region_ids(names, profile["regionJoints"]),
        "bindOffsets": package_off,
        "bindParents": np.asarray(package["parents"], dtype=np.int64),
        "jointNames": names,
        "meshVertices": np.asarray(obj["vertices"], dtype=np.float64),
        "meshFaces": np.asarray(obj["faces"], dtype=np.int64),
        "meshWeights": weights,
        "objWeightRowReport": indexing,
        "objIsWeightRowAuthority": True,
        "blenderToObjVerified": False,
        "spaces": {
            "captureSpace": str(profile["donorRefSeq"]),
            "donorMeshSpace": "base_mesh.obj_weight_row_authority",
            "targetBindSpace": "original_visible_mesh",
            "presentation": "target_bind_space_root_aligned_capture_no_baked_scale",
        },
    }


def load_shape_donor(profile: dict[str, Any]) -> dict[str, Any]:
    kind = str(profile["donorKind"])
    if kind == "zoo":
        return load_eagle_donor(profile)
    if kind == "obj":
        return load_mixamo_donor(profile)
    raise ValueError(f"unsupported donor kind {kind!r}")


def donor_rest_joints(donor: dict[str, Any]) -> np.ndarray:
    return compute_rest_joints(donor["bindOffsets"], donor["bindParents"])
