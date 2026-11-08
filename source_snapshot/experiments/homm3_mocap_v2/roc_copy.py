"""Duplicate Roc geometry and materials. Original GLB is not written."""
from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from glb_skeleton import BindSkeleton, _accessor, _base_color_albedo, load_bind_skeleton, read_glb
from pin import sha256_file
from scipy.spatial import cKDTree

ROC_REGION_BONES = {
    "torso": ("Bone_000", "Bone_001", "Bone_003", "Bone_002"),
    "neck_head": ("Bone_016", "Bone_015", "Bone_014"),
    "beak": ("Bone_014",),
    "wing_right": ("Bone_019", "Bone_018", "Bone_017"),
    "wing_left": ("Bone_022", "Bone_021", "Bone_020"),
    "tail": ("Bone_013", "Bone_012"),
    "leg_left": ("Bone_007", "Bone_006", "Bone_005", "Bone_004"),
    "leg_right": ("Bone_011", "Bone_010", "Bone_009", "Bone_008"),
}

# Global-similarity landmarks only. Per-bone repose uses semanticBranches.
ROC_TO_EAGLE_LANDMARKS = (
    ("Bone_000", "Hips"),
    ("Bone_001", "Bip01_Pelvis"),
    ("Bone_016", "Bip01_Neck"),
    ("Bone_014", "Bip01_Head"),
    ("Bone_020", "BN_Wing_L_04"),
    ("Bone_017", "BN_Wing_R_04"),
    ("Bone_022", "BN_Wing_L_01"),
    ("Bone_019", "BN_Wing_R_01"),
    ("Bone_004", "Bip01_L_Foot"),
    ("Bone_008", "Bip01_R_Foot"),
    ("Bone_012", "BN_Tai_R_02"),
)

BINDING_PATH = Path(__file__).with_name("roc_eagle_capture_binding.json")
FOOT_BONES = ("Bone_004", "Bone_008")
HEAD_BONE = "Bone_014"


def roc_to_eagle_bones() -> dict[str, str]:
    payload = json.loads(BINDING_PATH.read_text(encoding="utf-8"))
    branches = payload["semanticBranches"]
    if not isinstance(branches, dict) or not branches:
        raise ValueError("capture binding is missing semanticBranches")
    return {str(src): str(dst) for src, dst in branches.items()}


def _bbox_diagonal(points: np.ndarray) -> float:
    values = np.asarray(points, dtype=np.float64)
    return float(np.linalg.norm(values.max(axis=0) - values.min(axis=0)))


def _center_scale_align(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Put source vertices into target's center/scale frame for correspondence."""
    src = np.asarray(source, dtype=np.float64)
    dst = np.asarray(target, dtype=np.float64)
    src_center = src.mean(axis=0)
    dst_center = dst.mean(axis=0)
    src_span = _bbox_diagonal(src)
    dst_span = _bbox_diagonal(dst)
    if src_span <= 1e-8 or dst_span <= 1e-8:
        raise ValueError("cannot align degenerate vertex spans")
    scale = dst_span / src_span
    return (src - src_center) * scale + dst_center


def _load_unskinned_triangle_surface(mesh_glb: Path) -> dict[str, Any]:
    doc = read_glb(mesh_glb)
    json_doc = doc["json"]
    for mesh in json_doc.get("meshes") or ():
        for primitive in mesh.get("primitives") or ():
            attrs = primitive.get("attributes") or {}
            if "POSITION" not in attrs:
                continue
            vertices = _accessor(doc, doc["bin"], int(attrs["POSITION"])).reshape(-1, 3).astype(np.float64)
            uvs = None
            if "TEXCOORD_0" in attrs:
                uvs = _accessor(doc, doc["bin"], int(attrs["TEXCOORD_0"])).reshape(-1, 2).astype(np.float64)
            triangles = None
            if "indices" in primitive:
                triangles = _accessor(doc, doc["bin"], int(primitive["indices"])).astype(np.int32)
                if triangles.size % 3 != 0:
                    raise ValueError(f"{mesh_glb} indices are not triangles")
                triangles = triangles.reshape(-1, 3)
            albedo = _base_color_albedo(doc, primitive)
            if triangles is None or len(vertices) < 32:
                continue
            if uvs is None:
                raise ValueError(f"{mesh_glb} is missing TEXCOORD_0")
            if albedo is None:
                if not os.environ.get("HOMM3_ACCEPT_BIND_DEFECTS"):
                    raise ValueError(f"{mesh_glb} is missing packed albedo")
                albedo = np.full((8, 8, 4), 255, dtype=np.uint8)
            return {
                "vertices": vertices,
                "triangles": triangles.astype(np.int64),
                "uvs": uvs,
                "albedo": np.asarray(albedo).copy(),
            }
    raise ValueError(f"{mesh_glb} has no triangle surface")


def duplicate_roc_surface(target_glb: Path, reference_glb: Path) -> dict[str, Any]:
    """Build a Roc copy dict from an unskinned Meshy surface + SmartRig reference metadata.

    Region labels and Roc-bone LBS seeds are transferred from the reference mesh by
    nearest-vertex correspondence after center/scale alignment. The returned
    vertices are the *aligned* surface, because the returned skeleton (rest world,
    inverse bind) lives in the reference mesh's coordinate space; returning raw
    Meshy coordinates would place the mesh outside its own skeleton while the
    bind-identity check still passes. The reference GLB is read-only evidence; it
    is not modified.
    """
    ref = duplicate_roc(reference_glb)
    surface = _load_unskinned_triangle_surface(target_glb)
    raw_vertices = np.asarray(surface["vertices"], dtype=np.float64)
    aligned = _center_scale_align(raw_vertices, ref["vertices"])
    src_center = raw_vertices.mean(axis=0)
    dst_center = np.asarray(ref["vertices"], dtype=np.float64).mean(axis=0)
    scale = _bbox_diagonal(np.asarray(ref["vertices"], dtype=np.float64)) / _bbox_diagonal(raw_vertices)
    tree = cKDTree(np.asarray(ref["vertices"], dtype=np.float64))
    _, nearest = tree.query(aligned)
    nearest = np.asarray(nearest, dtype=np.int64)
    regions = ref["vertexRegions"][nearest]
    dense = ref["sourceDenseWeights"][nearest]
    components = connected_components(surface["triangles"], len(aligned))
    coincidences = coincidence_groups(aligned, dense)
    return {
        "sourceMesh": str(target_glb).replace("\\", "/"),
        "sourceSha256": sha256_file(target_glb),
        "referenceMesh": str(reference_glb).replace("\\", "/"),
        "referenceSha256": ref["sourceSha256"],
        "regionTransfer": "nearest_vertex_after_center_scale_align",
        "surfaceAlignment": {
            "policy": "uniform_scale_bbox_diagonal_then_centroid_to_reference_centroid",
            "scale": float(scale),
            "sourceCentroid": src_center.tolist(),
            "referenceCentroid": dst_center.tolist(),
            "verticesReturnedInReferenceSpace": True,
        },
        "names": list(ref["names"]),
        "parents": np.asarray(ref["parents"], dtype=np.int64).copy(),
        "restWorld": np.asarray(ref["restWorld"], dtype=np.float64).copy(),
        "restLocalRotation": np.asarray(ref["restLocalRotation"], dtype=np.float64).copy(),
        "restLocalTranslation": np.asarray(ref["restLocalTranslation"], dtype=np.float64).copy(),
        "vertices": np.asarray(aligned, dtype=np.float64).copy(),
        "triangles": np.asarray(surface["triangles"], dtype=np.int64).copy(),
        "uvs": np.asarray(surface["uvs"], dtype=np.float64).copy(),
        "normals": None,
        "albedo": np.asarray(surface["albedo"]).copy(),
        "sourceDenseWeights": dense,
        "vertexRegions": regions,
        "componentIds": components,
        "componentCount": int(components.max()) + 1 if len(components) else 0,
        "coincidenceGroups": coincidences,
        "nameIndex": {name: index for index, name in enumerate(ref["names"])},
        "topologyPreserved": True,
        "materialsPreserved": True,
        "boneMap": roc_to_eagle_bones(),
    }


def duplicate_roc(mesh_glb) -> dict[str, Any]:
    skeleton = load_bind_skeleton(mesh_glb)
    if skeleton.vertices is None or skeleton.triangles is None or skeleton.uvs is None:
        raise ValueError("Roc GLB is missing vertices, triangles, or UVs")
    if skeleton.vertex_weights is None or skeleton.vertex_joints is None:
        raise ValueError("Roc GLB is missing skin weights needed to initialize regions")
    if skeleton.albedo is None:
        raise ValueError("Roc GLB is missing packed albedo")
    names = list(skeleton.names)
    name_index = {name: index for index, name in enumerate(names)}
    dense = _dense_weights(skeleton)
    regions = _vertex_regions(
        dense,
        names,
        vertices=np.asarray(skeleton.vertices, dtype=np.float64),
        rest_world=np.asarray(skeleton.rest_world, dtype=np.float64),
    )
    components = connected_components(skeleton.triangles, len(skeleton.vertices))
    coincidences = coincidence_groups(
        np.asarray(skeleton.vertices, dtype=np.float64),
        dense,
    )
    return {
        "sourceMesh": str(mesh_glb).replace("\\", "/"),
        "sourceSha256": sha256_file(mesh_glb),
        "names": names,
        "parents": np.asarray(skeleton.parents, dtype=np.int64),
        "restWorld": np.asarray(skeleton.rest_world, dtype=np.float64).copy(),
        "restLocalRotation": np.asarray(skeleton.rest_local_rotation, dtype=np.float64).copy(),
        "restLocalTranslation": np.asarray(skeleton.rest_local_translation, dtype=np.float64).copy(),
        "vertices": np.asarray(skeleton.vertices, dtype=np.float64).copy(),
        "triangles": np.asarray(skeleton.triangles, dtype=np.int64).copy(),
        "uvs": np.asarray(skeleton.uvs, dtype=np.float64).copy(),
        "normals": None if skeleton.normals is None else np.asarray(skeleton.normals, dtype=np.float64).copy(),
        "albedo": np.asarray(skeleton.albedo).copy(),
        "sourceDenseWeights": dense,
        "vertexRegions": regions,
        "componentIds": components,
        "componentCount": int(components.max()) + 1 if len(components) else 0,
        "coincidenceGroups": coincidences,
        "nameIndex": name_index,
        "topologyPreserved": True,
        "materialsPreserved": True,
        "boneMap": roc_to_eagle_bones(),
    }


def _dense_weights(skeleton: BindSkeleton) -> np.ndarray:
    joints = np.asarray(skeleton.vertex_joints, dtype=np.int32)
    weights = np.asarray(skeleton.vertex_weights, dtype=np.float64)
    dense = np.zeros((len(skeleton.vertices), len(skeleton.names)), dtype=np.float64)
    for slot in range(joints.shape[1]):
        valid = weights[:, slot] > 1e-8
        dense[np.arange(len(dense))[valid], joints[valid, slot]] += weights[valid, slot]
    row = dense.sum(axis=1, keepdims=True)
    dense = np.divide(dense, np.where(row < 1e-8, 1.0, row))
    return dense


def _vertex_regions(
    dense: np.ndarray,
    names: list[str],
    *,
    vertices: np.ndarray,
    rest_world: np.ndarray,
) -> np.ndarray:
    bone_region = {}
    for region, bones in ROC_REGION_BONES.items():
        if region == "beak":
            continue
        for bone in bones:
            bone_region[bone] = region
    labels = []
    for index, name in enumerate(names):
        labels.append(bone_region.get(name, "torso"))
    argmax = np.argmax(dense, axis=1)
    regions = np.array([labels[int(index)] for index in argmax], dtype=object)
    names_index = {name: index for index, name in enumerate(names)}
    head = names_index[HEAD_BONE]
    neck = names_index["Bone_015"]
    verts = np.asarray(vertices, dtype=np.float64)
    rest = np.asarray(rest_world, dtype=np.float64)
    head_axis = rest[head] - rest[neck]
    axis_norm = float(np.linalg.norm(head_axis))
    if axis_norm < 1e-8:
        raise ValueError("Roc head-neck axis is degenerate")
    head_axis = head_axis / axis_norm
    along = (verts - rest[head]) @ head_axis
    head_owned = argmax == head
    beak = np.zeros(len(verts), dtype=bool)
    if np.any(head_owned):
        cutoff = float(np.quantile(along[head_owned], 0.92))
        beak = head_owned & (along >= cutoff)
    regions[beak] = "beak"
    return regions


def connected_components(triangles: np.ndarray, vertex_count: int) -> np.ndarray:
    parent = np.arange(vertex_count, dtype=np.int32)

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = int(parent[index])
        return index

    for a, b, c in triangles:
        ra, rb, rc = find(int(a)), find(int(b)), find(int(c))
        parent[rb] = ra
        parent[rc] = ra
    ids = np.array([find(index) for index in range(vertex_count)], dtype=np.int32)
    remap = {int(old): new for new, old in enumerate(sorted(set(ids.tolist())))}
    return np.array([remap[int(value)] for value in ids], dtype=np.int32)


def coincidence_groups(vertices: np.ndarray, weights: np.ndarray, *, decimals: int = 6) -> list[np.ndarray]:
    """UV-split vertices: same rest position and same dominant bone. Topology is not welded."""
    verts = np.asarray(vertices, dtype=np.float64)
    argmax = np.argmax(np.asarray(weights, dtype=np.float64), axis=1)
    buckets: dict[tuple, list[int]] = defaultdict(list)
    rounded = np.round(verts, decimals)
    for index, point in enumerate(rounded):
        buckets[(float(point[0]), float(point[1]), float(point[2]), int(argmax[index]))].append(index)
    return [np.asarray(group, dtype=np.int64) for group in buckets.values() if len(group) > 1]


def coalesce_coincidences(vertices: np.ndarray, groups: list[np.ndarray]) -> np.ndarray:
    out = np.asarray(vertices, dtype=np.float64).copy()
    for group in groups:
        if len(group) < 2:
            continue
        out[group] = out[group].mean(axis=0)
    return out


def component_representatives(component_ids: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """One offset-preserving handle vertex per connected component (max weight, not a joint center)."""
    ids = np.asarray(component_ids, dtype=np.int32)
    dense = np.asarray(weights, dtype=np.float64)
    strength = dense.max(axis=1)
    chosen = []
    for component in range(int(ids.max()) + 1 if len(ids) else 0):
        members = np.where(ids == component)[0]
        if members.size == 0:
            continue
        chosen.append(int(members[int(np.argmax(strength[members]))]))
    return np.asarray(chosen, dtype=np.int64)
