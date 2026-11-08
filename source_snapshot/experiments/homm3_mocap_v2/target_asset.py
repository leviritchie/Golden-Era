"""Load the original visible target without conforming it."""
from __future__ import annotations

import os
from typing import Any

import numpy as np

from glb_skeleton import BindSkeleton, load_bind_skeleton
from pin import sha256_file
from roc_copy import coincidence_groups, connected_components


def dense_weights(skeleton: BindSkeleton) -> np.ndarray:
    if skeleton.vertices is None or skeleton.vertex_weights is None or skeleton.vertex_joints is None:
        raise ValueError("target GLB is missing vertices or skin weights needed as region evidence")
    joints = np.asarray(skeleton.vertex_joints, dtype=np.int32)
    weights = np.asarray(skeleton.vertex_weights, dtype=np.float64)
    dense = np.zeros((len(skeleton.vertices), len(skeleton.names)), dtype=np.float64)
    for slot in range(joints.shape[1]):
        valid = weights[:, slot] > 1e-8
        dense[np.arange(len(dense))[valid], joints[valid, slot]] += weights[valid, slot]
    row = dense.sum(axis=1, keepdims=True)
    return np.divide(dense, np.where(row < 1e-8, 1.0, row))


def vertex_regions_from_profile(
    dense: np.ndarray,
    names: list[str],
    profile: dict[str, Any],
    *,
    vertices: np.ndarray,
    rest_world: np.ndarray,
) -> np.ndarray:
    bone_region: dict[str, str] = {}
    for region, bones in profile["regionBones"].items():
        if region == "beak":
            continue
        for bone in bones:
            bone_region[str(bone)] = str(region)
    labels = [bone_region.get(name, "torso") for name in names]
    argmax = np.argmax(dense, axis=1)
    regions = np.array([labels[int(index)] for index in argmax], dtype=object)
    quantile = profile.get("beakFromHeadQuantile")
    if quantile is None:
        return regions
    name_index = {name: index for index, name in enumerate(names)}
    head = name_index[str(profile["headBone"])]
    neck = name_index[str(profile["neckBone"])]
    head_axis = rest_world[head] - rest_world[neck]
    axis_norm = float(np.linalg.norm(head_axis))
    if axis_norm < 1e-8:
        raise ValueError("head-neck axis is degenerate")
    head_axis = head_axis / axis_norm
    along = (np.asarray(vertices, dtype=np.float64) - rest_world[head]) @ head_axis
    head_owned = argmax == head
    if np.any(head_owned):
        cutoff = float(np.quantile(along[head_owned], float(quantile)))
        regions[head_owned & (along >= cutoff)] = "beak"
    return regions


def validate_complete_region_coverage(names: list[str], profile: dict[str, Any]) -> None:
    """Validate an opt-in profile's one-to-one source-bone region contract."""
    if not profile.get("requireCompleteRegionCoverage", False):
        return
    available = set(str(name) for name in names)
    seen: set[str] = set()
    region_joints = profile.get("regionJoints", {})
    if not isinstance(region_joints, dict):
        raise ValueError("complete region coverage requires regionJoints mapping")
    rigid = {}
    for entry in profile.get("rigidAttachments", ()):
        if not isinstance(entry, dict) or not entry.get("region"):
            raise ValueError("rigidAttachments entries require a region")
        rigid[str(entry["region"])] = entry
    for region, bones in profile.get("regionBones", {}).items():
        region = str(region)
        if region not in region_joints and region not in rigid:
            raise ValueError(f"region {region} is absent from regionJoints and is not rigid")
        if not isinstance(bones, (tuple, list)) or not bones:
            raise ValueError(f"region {region} has no source bones")
        for bone in bones:
            bone = str(bone)
            if bone not in available:
                raise ValueError(f"region {region} source bone is missing: {bone}")
            if bone in seen:
                raise ValueError(f"source bone is assigned to multiple regions: {bone}")
            seen.add(bone)
    missing = sorted(available - seen)
    if missing:
        raise ValueError(f"source bones missing region assignment: {missing}")
    donors = {str(joint) for joints in region_joints.values() for joint in joints}
    for region, entry in rigid.items():
        donor_joints = entry.get("donorJoints")
        if not isinstance(donor_joints, (tuple, list)) or not donor_joints:
            raise ValueError(f"rigid region {region} requires donorJoints")
        missing = [str(joint) for joint in donor_joints if str(joint) not in donors]
        if missing:
            raise ValueError(f"rigid region {region} has donor joints not present in regionJoints: {missing}")


def load_target_asset(profile: dict[str, Any]) -> dict[str, Any]:
    from mounted_asset_identity import validate_profile_identity
    if 'assetId' in profile:
        validate_profile_identity(profile)
    mesh = profile["mesh"]
    skeleton = load_bind_skeleton(mesh)
    if skeleton.vertices is None or skeleton.triangles is None or skeleton.uvs is None:
        raise ValueError("target GLB is missing vertices, triangles, or UVs")
    if skeleton.albedo is None:
        if not os.environ.get("HOMM3_ACCEPT_BIND_DEFECTS"):
            raise ValueError("target GLB is missing packed albedo")
        skeleton.albedo = np.full((8, 8, 4), 255, dtype=np.uint8)
    names = list(skeleton.names)
    validate_complete_region_coverage(names, profile)
    dense = dense_weights(skeleton)
    rest_world = np.asarray(skeleton.rest_world, dtype=np.float64).copy()
    vertices = np.asarray(skeleton.vertices, dtype=np.float64).copy()
    triangles = np.asarray(skeleton.triangles, dtype=np.int64).copy()
    regions = vertex_regions_from_profile(
        dense,
        names,
        profile,
        vertices=vertices,
        rest_world=rest_world,
    )
    components = connected_components(triangles, len(vertices))
    coincidences = coincidence_groups(vertices, dense)
    digest = sha256_file(mesh)
    expected = str(profile.get("expectedMeshSha256") or "")
    if expected and digest != expected:
        raise ValueError(f"target mesh hash {digest} != pinned {expected}")
    result = {
        "sourceMesh": str(mesh).replace("\\", "/"),
        "sourceSha256": digest,
        "names": names,
        "parents": np.asarray(skeleton.parents, dtype=np.int64),
        "restWorld": rest_world,
        "restLocalRotation": np.asarray(skeleton.rest_local_rotation, dtype=np.float64).copy(),
        "restLocalTranslation": np.asarray(skeleton.rest_local_translation, dtype=np.float64).copy(),
        "vertices": vertices,
        "triangles": triangles,
        "uvs": np.asarray(skeleton.uvs, dtype=np.float64).copy(),
        "normals": None if skeleton.normals is None else np.asarray(skeleton.normals, dtype=np.float64).copy(),
        "albedo": np.asarray(skeleton.albedo).copy(),
        "sourceDenseWeights": dense,
        "vertexRegions": regions,
        "componentIds": components,
        "componentCount": int(components.max()) + 1 if len(components) else 0,
        "coincidenceGroups": coincidences,
        "nameIndex": {name: index for index, name in enumerate(names)},
        "topologyPreserved": True,
        "materialsPreserved": True,
        "visibleMeshUnchanged": True,
    }
    if "geometryOwnership" in profile:
        from geometry_ownership import apply_ownership
        result = apply_ownership(result, profile)
        result["componentIds"] = connected_components(result["triangles"], len(result["vertices"]))
        result["componentCount"] = int(result["componentIds"].max()) + 1
        result["coincidenceGroups"] = coincidence_groups(result["vertices"], result["sourceDenseWeights"])
    return result
