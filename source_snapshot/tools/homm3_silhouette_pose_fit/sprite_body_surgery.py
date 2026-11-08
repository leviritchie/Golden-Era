"""Write previewable camera and body-surgery artifacts (GLB / poses / camera).

Does not write live fused-push or Meshy downloads. Caller must pass a work-tree path
through ``assert_write_path``.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from gpu_cascade_delivery import _read_glb, _write_glb, require_pose_units_degrees
from sprite_bilateral_axes import (
    ANATOMICAL_AXES,
    paired_anatomical_local_adds,
    orthonormal_rotation,
)
from sprite_pose_feasibility import (
    BONE_AXES,
    LBS_CONDITION_FLOOR,
    LBS_SKIP_FRACTION_CAP,
    REBIND_CHILD_WEIGHT,
    REST_LENGTH_SCALE_MAX,
    REST_LENGTH_SCALE_MIN,
    REST_SCULPT_MAX_BODY_LENGTHS,
    invert_lbs_image_plane,
    predict_channel_inertial,
    skip_fraction_reject,
)

COMPONENTS = {
    5120: (np.int8, 1),
    5121: (np.uint8, 1),
    5122: (np.int16, 2),
    5123: (np.uint16, 2),
    5125: (np.uint32, 4),
    5126: (np.float32, 4),
}
TYPE_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def load_glb(path: str | Path) -> tuple[dict[str, Any], bytearray]:
    doc, blob = _read_glb(Path(path))
    return doc, bytearray(blob)


def save_glb(path: str | Path, doc: Mapping[str, Any], blob: bytes) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = bytearray(blob)
    buffers = list(doc.get("buffers") or [{}])
    if not buffers:
        buffers = [{}]
    buffers[0] = dict(buffers[0])
    buffers[0]["byteLength"] = int(len(payload))
    written = dict(doc)
    written["buffers"] = buffers
    _write_glb(dest, written, payload)
    return dest


def _accessor_array(doc: Mapping[str, Any], blob: bytes, index: int) -> np.ndarray:
    acc = doc["accessors"][int(index)]
    view = doc["bufferViews"][int(acc["bufferView"])]
    dtype, _width = COMPONENTS[int(acc["componentType"])]
    comps = TYPE_WIDTH[str(acc["type"])]
    count = int(acc["count"])
    start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
    n = count * comps
    stride = int(view.get("byteStride") or 0)
    if stride and stride != dtype().nbytes * comps:
        raise ValueError(f"strided accessor {index} is not supported for surgery")
    raw = np.frombuffer(bytes(blob[start : start + n * dtype().nbytes]), dtype=dtype)
    if raw.size != n:
        raise ValueError(f"accessor {index} length mismatch")
    if str(acc["type"]) == "MAT4":
        return raw.astype(np.float64).reshape(count, 4, 4).copy()
    if comps == 1:
        return raw.copy()
    return raw.reshape(count, comps).copy()


def _write_accessor(doc: dict[str, Any], blob: bytearray, index: int, values: np.ndarray) -> None:
    acc = doc["accessors"][int(index)]
    view = doc["bufferViews"][int(acc["bufferView"])]
    dtype, _width = COMPONENTS[int(acc["componentType"])]
    comps = TYPE_WIDTH[str(acc["type"])]
    count = int(acc["count"])
    start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
    if str(acc["type"]) == "MAT4":
        packed = np.asarray(values, dtype=np.float32).reshape(count, 16)
    else:
        packed = np.asarray(values, dtype=dtype).reshape(count, comps) if comps > 1 else np.asarray(values, dtype=dtype).reshape(count)
    raw = packed.astype(dtype, copy=False).tobytes()
    end = start + len(raw)
    if end > len(blob):
        raise ValueError(f"accessor {index} write exceeds BIN chunk")
    blob[start:end] = raw


def _append_bin(blob: bytearray, payload: bytes) -> int:
    while len(blob) % 4:
        blob.append(0)
    start = len(blob)
    blob.extend(payload)
    while len(blob) % 4:
        blob.append(0)
    return start


def body_extent(positions: np.ndarray) -> float:
    pts = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
    if pts.shape[0] < 1:
        raise ValueError("mesh has no positions")
    span = pts.max(axis=0) - pts.min(axis=0)
    extent = float(np.linalg.norm(span))
    if not math.isfinite(extent) or extent <= 0.0:
        raise ValueError("mesh body extent must be positive")
    return extent


def first_skinned_primitive(doc: Mapping[str, Any]) -> tuple[int, int, dict[str, Any]]:
    meshes = doc.get("meshes")
    if not isinstance(meshes, list) or not meshes:
        raise ValueError("GLB has no meshes")
    for mesh_i, mesh in enumerate(meshes):
        for prim_i, prim in enumerate(mesh.get("primitives") or []):
            attrs = prim.get("attributes") or {}
            if "POSITION" in attrs and "JOINTS_0" in attrs and "WEIGHTS_0" in attrs:
                return int(mesh_i), int(prim_i), prim
    raise ValueError("GLB has no skinned primitive")


def primitive_rest_positions(doc: Mapping[str, Any], blob: bytes) -> np.ndarray:
    _mesh_i, _prim_i, prim = first_skinned_primitive(doc)
    positions = _accessor_array(doc, blob, int(prim["attributes"]["POSITION"]))
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ValueError("POSITION must be VEC3")
    return np.asarray(positions, dtype=np.float64)


def validate_skinned_glb(path: str | Path) -> dict[str, Any]:
    doc, blob = load_glb(path)
    _mesh_i, _prim_i, prim = first_skinned_primitive(doc)
    attrs = prim["attributes"]
    positions = _accessor_array(doc, blob, int(attrs["POSITION"]))
    joints = _accessor_array(doc, blob, int(attrs["JOINTS_0"])).astype(np.int64)
    weights = _accessor_array(doc, blob, int(attrs["WEIGHTS_0"])).astype(np.float64)
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ValueError("POSITION must be VEC3")
    if not np.isfinite(positions).all():
        raise ValueError("POSITION contains non-finite values")
    if joints.shape != weights.shape:
        raise ValueError("JOINTS_0 and WEIGHTS_0 shape mismatch")
    sums = weights.sum(axis=1)
    if np.any(np.abs(sums - 1.0) > 0.02):
        raise ValueError("skin weights do not sum to 1")
    skins = doc.get("skins")
    if not isinstance(skins, list) or not skins:
        raise ValueError("GLB has no skins")
    skin = skins[0]
    joint_nodes = [int(index) for index in skin["joints"]]
    if int(joints.max()) >= len(joint_nodes):
        raise ValueError("JOINTS_0 index exceeds skin.joints")
    if "inverseBindMatrices" in skin:
        ibm = _accessor_array(doc, blob, int(skin["inverseBindMatrices"]))
        if ibm.shape[0] != len(joint_nodes):
            raise ValueError("inverseBindMatrices count does not match skin.joints")
        if not np.isfinite(ibm).all():
            raise ValueError("inverseBindMatrices contain non-finite values")
    return {
        "vertexCount": int(positions.shape[0]),
        "jointCount": int(len(joint_nodes)),
        "path": str(Path(path).resolve()).replace("\\", "/"),
    }


def replace_positions(doc: dict[str, Any], blob: bytearray, positions: np.ndarray) -> None:
    _mesh_i, _prim_i, prim = first_skinned_primitive(doc)
    _write_accessor(doc, blob, int(prim["attributes"]["POSITION"]), positions)


def skinned_triangle_faces(doc: Mapping[str, Any], blob: bytes) -> np.ndarray:
    _mesh_i, _prim_i, prim = first_skinned_primitive(doc)
    if "indices" not in prim:
        raise ValueError("skinned primitive has no indices")
    raw = _accessor_array(doc, blob, int(prim["indices"])).astype(np.int64)
    if raw.size % 3 != 0:
        raise ValueError("skinned primitive indices are not triangles")
    return raw.reshape(-1, 3)


def replace_triangle_indices(doc: dict[str, Any], blob: bytearray, faces: np.ndarray) -> None:
    _mesh_i, _prim_i, prim = first_skinned_primitive(doc)
    if "indices" not in prim:
        raise ValueError("skinned primitive has no indices")
    triangles = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    if triangles.shape[0] < 1:
        raise ValueError("cannot write an empty triangle set")
    if int(triangles.min()) < 0:
        raise ValueError("triangle indices must be non-negative")
    acc_index = int(prim["indices"])
    acc = doc["accessors"][acc_index]
    dtype, _width = COMPONENTS[int(acc["componentType"])]
    if int(triangles.max()) > int(np.iinfo(dtype).max):
        raise ValueError("triangle index exceeds accessor component type")
    packed = triangles.reshape(-1).astype(dtype, copy=False)
    raw = packed.tobytes()
    start = _append_bin(blob, raw)
    views = doc.setdefault("bufferViews", [])
    view_index = len(views)
    views.append({"buffer": 0, "byteOffset": int(start), "byteLength": len(raw)})
    acc["bufferView"] = view_index
    acc["byteOffset"] = 0
    acc["count"] = int(packed.size)
    acc.pop("min", None)
    acc.pop("max", None)


def replace_skin(
    doc: dict[str, Any],
    blob: bytearray,
    *,
    joints: np.ndarray,
    weights: np.ndarray,
) -> None:
    _mesh_i, _prim_i, prim = first_skinned_primitive(doc)
    attrs = prim["attributes"]
    _write_accessor(doc, blob, int(attrs["JOINTS_0"]), joints)
    _write_accessor(doc, blob, int(attrs["WEIGHTS_0"]), weights)


def normalize_skin_weights(doc: dict[str, Any], blob: bytearray) -> dict[str, Any]:
    """Make WEIGHTS_0 rows sum to 1. Meshy copies often miss the 0.02 gate."""
    _mesh_i, _prim_i, prim = first_skinned_primitive(doc)
    attrs = prim["attributes"]
    weights = _accessor_array(doc, blob, int(attrs["WEIGHTS_0"])).astype(np.float32)
    sums = weights.sum(axis=1)
    empty = sums <= 1e-8
    safe = np.where(empty, 1.0, sums).astype(np.float32)
    out = weights / safe[:, None]
    out[empty] = 0.0
    out[empty, 0] = 1.0
    _write_accessor(doc, blob, int(attrs["WEIGHTS_0"]), out)
    return {
        "fixedVertices": int(np.count_nonzero(np.abs(sums - 1.0) > 0.02)),
        "emptyVertices": int(np.count_nonzero(empty)),
        "vertexCount": int(weights.shape[0]),
    }


def scale_bone_rest_translation(
    doc: dict[str, Any],
    blob: bytearray,
    *,
    joint_node: int,
    scale: float,
) -> None:
    factor = float(scale)
    if not math.isfinite(factor) or factor <= 0.0:
        raise ValueError("rest-length scale must be positive and finite")
    if factor < float(REST_LENGTH_SCALE_MIN) or factor > float(REST_LENGTH_SCALE_MAX):
        raise ValueError(
            f"rest-length scale {factor} is outside "
            f"[{REST_LENGTH_SCALE_MIN}, {REST_LENGTH_SCALE_MAX}]"
        )
    nodes = doc["nodes"]
    node = nodes[int(joint_node)]
    translation = [float(value) * factor for value in node.get("translation") or (0.0, 0.0, 0.0)]
    node["translation"] = translation
    skins = doc.get("skins") or []
    if not skins:
        raise ValueError("cannot recompute inverse bind without a skin")
    skin = skins[0]
    joints = [int(index) for index in skin["joints"]]
    if int(joint_node) not in joints:
        raise ValueError(f"node {joint_node} is not a skin joint")
    # Inverse bind is recomputed from node world matrices after the rest edit.
    ibm_index = int(skin["inverseBindMatrices"])
    ibm = _accessor_array(doc, blob, ibm_index)
    worlds = _node_world_matrices(doc)
    for slot, node_index in enumerate(joints):
        world = worlds[int(node_index)]
        ibm[slot] = np.linalg.inv(world).T
    _write_accessor(doc, blob, ibm_index, ibm)


def _node_local_matrix(node: Mapping[str, Any]) -> np.ndarray:
    t = np.asarray(node.get("translation") or (0.0, 0.0, 0.0), dtype=np.float64)
    r = np.asarray(node.get("rotation") or (0.0, 0.0, 0.0, 1.0), dtype=np.float64)
    s = np.asarray(node.get("scale") or (1.0, 1.0, 1.0), dtype=np.float64)
    qx, qy, qz, qw = r
    m = np.eye(4, dtype=np.float64)
    m[0, 0] = 1 - 2 * (qy * qy + qz * qz)
    m[0, 1] = 2 * (qx * qy - qz * qw)
    m[0, 2] = 2 * (qx * qz + qy * qw)
    m[1, 0] = 2 * (qx * qy + qz * qw)
    m[1, 1] = 1 - 2 * (qx * qx + qz * qz)
    m[1, 2] = 2 * (qy * qz - qx * qw)
    m[2, 0] = 2 * (qx * qz - qy * qw)
    m[2, 1] = 2 * (qy * qz + qx * qw)
    m[2, 2] = 1 - 2 * (qx * qx + qy * qy)
    m[:3, 3] = t
    m[0, :3] *= s
    m[1, :3] *= s
    m[2, :3] *= s
    return m


def _node_world_matrices(doc: Mapping[str, Any]) -> list[np.ndarray]:
    nodes = doc["nodes"]
    parents = [None] * len(nodes)
    for index, node in enumerate(nodes):
        for child in node.get("children") or []:
            parents[int(child)] = int(index)
    worlds = [np.eye(4, dtype=np.float64) for _ in nodes]
    order: list[int] = []
    remaining = set(range(len(nodes)))
    while remaining:
        progressed = False
        for index in list(remaining):
            parent = parents[index]
            if parent is None or parent not in remaining:
                parent_m = np.eye(4) if parent is None else worlds[parent]
                worlds[index] = parent_m @ _node_local_matrix(nodes[index])
                remaining.remove(index)
                order.append(index)
                progressed = True
        if not progressed:
            raise RuntimeError("node graph has a cycle")
    return worlds


def node_world_translation(doc: Mapping[str, Any], name: str) -> np.ndarray:
    index = node_index_by_name(doc, name)
    worlds = _node_world_matrices(doc)
    return np.asarray(worlds[int(index)][:3, 3], dtype=np.float64).copy()


def insert_child_bone(
    doc: dict[str, Any],
    blob: bytearray,
    *,
    parent_node: int,
    name: str,
    translation: Sequence[float],
    vertex_indices: Sequence[int],
) -> dict[str, Any]:
    verts = [int(index) for index in vertex_indices]
    if not verts:
        raise ValueError("insert-bone weight set is empty")
    nodes = doc["nodes"]
    parent = nodes[int(parent_node)]
    new_index = len(nodes)
    nodes.append(
        {
            "name": str(name),
            "translation": [float(axis) for axis in translation],
            "rotation": [0.0, 0.0, 0.0, 1.0],
            "scale": [1.0, 1.0, 1.0],
        }
    )
    children = list(parent.get("children") or [])
    children.append(new_index)
    parent["children"] = children
    skin = doc["skins"][0]
    joints = [int(index) for index in skin["joints"]]
    joints.append(new_index)
    skin["joints"] = joints
    ibm_index = int(skin["inverseBindMatrices"])
    ibm = _accessor_array(doc, blob, ibm_index)
    worlds = _node_world_matrices(doc)
    new_ibm = np.linalg.inv(worlds[new_index]).T.reshape(1, 4, 4)
    ibm = np.concatenate([ibm, new_ibm], axis=0)
    raw = np.asarray(ibm, dtype=np.float32).reshape(-1).tobytes()
    start = _append_bin(blob, raw)
    views = doc.setdefault("bufferViews", [])
    view_index = len(views)
    views.append({"buffer": 0, "byteOffset": int(start), "byteLength": len(raw)})
    acc = doc["accessors"][ibm_index]
    acc["bufferView"] = view_index
    acc["byteOffset"] = 0
    acc["count"] = int(ibm.shape[0])
    _mesh_i, _prim_i, prim = first_skinned_primitive(doc)
    attrs = prim["attributes"]
    joint_slots = _accessor_array(doc, blob, int(attrs["JOINTS_0"])).astype(np.uint16)
    weights = _accessor_array(doc, blob, int(attrs["WEIGHTS_0"])).astype(np.float32)
    new_slot = len(joints) - 1
    for vertex in verts:
        if vertex < 0 or vertex >= joint_slots.shape[0]:
            raise ValueError(f"insert-bone vertex {vertex} is out of range")
        joint_slots[vertex] = 0
        joint_slots[vertex, 0] = np.uint16(new_slot)
        weights[vertex] = 0.0
        weights[vertex, 0] = 1.0
    _write_accessor(doc, blob, int(attrs["JOINTS_0"]), joint_slots)
    _write_accessor(doc, blob, int(attrs["WEIGHTS_0"]), weights)
    return {
        "nodeIndex": int(new_index),
        "jointSlot": int(new_slot),
        "name": str(name),
        "vertexCount": int(len(verts)),
    }


def rest_sculpt_positions(
    rest: np.ndarray,
    blends: np.ndarray,
    *,
    deltas_world: np.ndarray,
    affected: np.ndarray,
    body_length: float,
    condition_floor: float = LBS_CONDITION_FLOOR,
    skip_cap: float = LBS_SKIP_FRACTION_CAP,
) -> dict[str, Any]:
    points = np.asarray(rest, dtype=np.float64).reshape(-1, 3)
    matrices = np.asarray(blends, dtype=np.float64).reshape(-1, 4, 4)
    delta = np.asarray(deltas_world, dtype=np.float64).reshape(-1, 3)
    mask = np.asarray(affected, dtype=bool).reshape(-1)
    if points.shape[0] != matrices.shape[0] or points.shape[0] != delta.shape[0]:
        raise ValueError("rest sculpt arrays must share a vertex count")
    affected_count = int(np.count_nonzero(mask))
    if affected_count < 1:
        raise ValueError("rest sculpt affected vertex set is empty")
    max_disp = float(REST_SCULPT_MAX_BODY_LENGTHS) * float(body_length)
    out = points.copy()
    skipped = 0
    moved = 0
    for index in np.nonzero(mask)[0]:
        new_rest, status = invert_lbs_image_plane(
            points[index],
            matrices[index],
            delta_world=delta[index],
            condition_floor=float(condition_floor),
            max_displacement=max_disp,
        )
        if new_rest is None:
            skipped += 1
            continue
        out[index] = new_rest
        moved += 1
    if skip_fraction_reject(skipped, affected_count, cap=float(skip_cap)):
        return {
            "rejected": True,
            "reason": "lbs_ill_conditioned",
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


def node_index_by_name(doc: Mapping[str, Any], name: str) -> int:
    for index, node in enumerate(doc.get("nodes") or []):
        if str(node.get("name") or "") == str(name):
            return int(index)
    raise ValueError(f"GLB has no node named {name!r}")


def joint_slot_for_node(doc: Mapping[str, Any], node_index: int) -> int:
    joints = [int(index) for index in doc["skins"][0]["joints"]]
    try:
        return int(joints.index(int(node_index)))
    except ValueError as exc:
        raise ValueError(f"node {node_index} is not a skin joint") from exc


def parent_joint_slot(doc: Mapping[str, Any], node_index: int) -> int | None:
    nodes = doc["nodes"]
    for parent_index, node in enumerate(nodes):
        if int(node_index) in [int(child) for child in (node.get("children") or [])]:
            joints = [int(index) for index in doc["skins"][0]["joints"]]
            if int(parent_index) in joints:
                return int(joints.index(int(parent_index)))
            return None
    return None


def rebind_vertices_to_joint(
    doc: dict[str, Any],
    blob: bytearray,
    *,
    vertex_indices: Sequence[int],
    target_node: int,
    child_weight: float = REBIND_CHILD_WEIGHT,
) -> dict[str, Any]:
    verts = [int(index) for index in vertex_indices]
    if not verts:
        raise ValueError("unique-region rebind vertex set is empty")
    target_slot = joint_slot_for_node(doc, int(target_node))
    parent_slot = parent_joint_slot(doc, int(target_node))
    mix = float(child_weight)
    if not math.isfinite(mix) or mix <= 0.0 or mix > 1.0:
        raise ValueError("rebind child_weight must be in (0, 1]")
    _mesh_i, _prim_i, prim = first_skinned_primitive(doc)
    attrs = prim["attributes"]
    joint_slots = _accessor_array(doc, blob, int(attrs["JOINTS_0"])).astype(np.uint16)
    weights = _accessor_array(doc, blob, int(attrs["WEIGHTS_0"])).astype(np.float32)
    for vertex in verts:
        if vertex < 0 or vertex >= joint_slots.shape[0]:
            raise ValueError(f"rebind vertex {vertex} is out of range")
        joint_slots[vertex] = 0
        weights[vertex] = 0.0
        joint_slots[vertex, 0] = np.uint16(target_slot)
        if parent_slot is None or mix >= 1.0:
            weights[vertex, 0] = 1.0
        else:
            joint_slots[vertex, 1] = np.uint16(parent_slot)
            weights[vertex, 0] = np.float32(mix)
            weights[vertex, 1] = np.float32(1.0 - mix)
    _write_accessor(doc, blob, int(attrs["JOINTS_0"]), joint_slots)
    _write_accessor(doc, blob, int(attrs["WEIGHTS_0"]), weights)
    return {
        "vertexCount": int(len(verts)),
        "targetNode": int(target_node),
        "targetSlot": int(target_slot),
        "parentSlot": None if parent_slot is None else int(parent_slot),
        "childWeight": float(mix),
    }


MOTION_ROOT_KEY = "__motion_root__"
MOTION_ROOT_ROTATION_KEY = "__motion_root_rotation__"
ROOT_ROTATION_AXES = ("camera_forward", "camera_right", "camera_up")
ROOT_TRANSLATION_AXES = ("forward", "lateral", "vertical")


def _bone_xyz(pose: Mapping[str, Any], name: str) -> dict[str, float]:
    bone = pose.get(name)
    if not isinstance(bone, Mapping):
        return {axis: 0.0 for axis in BONE_AXES}
    return {axis: float(bone.get(axis, 0.0)) for axis in BONE_AXES}


def rotate_bone_deg(
    poses: dict[int, dict[str, Any]],
    *,
    joint: str,
    frames: Sequence[int],
    axis: str,
    delta_deg: float,
    joint_limit_deg: float,
) -> None:
    """Add a degree-space axis rotation. Clip JSON pose units are degrees."""
    channel = str(axis).strip()
    if channel not in {"x", "y", "z"}:
        raise ValueError(f"bone axis must be x, y, or z; got {channel!r}")
    extra = float(delta_deg)
    limit = float(joint_limit_deg)
    if not math.isfinite(extra):
        raise ValueError("delta_deg must be finite")
    if not math.isfinite(limit) or limit <= 0.0:
        raise ValueError("joint_limit_deg must be positive")
    for frame in frames:
        pose = poses[int(frame)]
        entry = dict(pose.get(joint) or {"x": 0.0, "y": 0.0, "z": 0.0})
        next_value = float(entry.get(channel, 0.0)) + extra
        if abs(next_value) > limit + 1e-9:
            raise ValueError(
                f"{joint} {channel} would be {next_value:.3f} deg, over the {limit:.3f} deg joint limit"
            )
        entry[channel] = next_value
        pose[str(joint)] = {key: float(entry.get(key, 0.0)) for key in ("x", "y", "z")}


def rotate_bone_deg_within_limit(
    poses: dict[int, dict[str, Any]],
    *,
    joint: str,
    frames: Sequence[int],
    axis: str,
    delta_deg: float,
    joint_limit_deg: float,
    min_step_deg: float = 2.0,
) -> float:
    """Rotate, shrinking the step to remaining joint room instead of skipping.

    Frame 8 Roc Bone_001.x is already -135 deg. A 30 deg step would exceed
    the 150 deg cap and be skipped, so the last 15 deg of room is wasted.
    """
    channel = str(axis).strip()
    if channel not in {"x", "y", "z"}:
        raise ValueError(f"bone axis must be x, y, or z; got {channel!r}")
    extra = float(delta_deg)
    limit = float(joint_limit_deg)
    floor = float(min_step_deg)
    if not math.isfinite(extra) or extra == 0.0:
        raise ValueError("delta_deg must be a non-zero finite number")
    if not math.isfinite(limit) or limit <= 0.0:
        raise ValueError("joint_limit_deg must be positive")
    if not math.isfinite(floor) or floor < 0.0:
        raise ValueError("min_step_deg must be non-negative")
    applied = extra
    for frame in frames:
        pose = poses[int(frame)]
        entry = dict(pose.get(joint) or {"x": 0.0, "y": 0.0, "z": 0.0})
        current = float(entry.get(channel, 0.0))
        remaining = limit - abs(current)
        trial = extra
        if abs(current + extra) > limit + 1e-9:
            if remaining < floor + 1e-9:
                raise ValueError(
                    f"{joint} {channel} has {remaining:.3f} deg of room, under {floor:.3f} deg"
                )
            trial = math.copysign(remaining, extra)
        applied = trial
        entry[channel] = current + trial
        pose[str(joint)] = {key: float(entry.get(key, 0.0)) for key in ("x", "y", "z")}
    return float(applied)


def rotate_bone_deg_shared_within_limit(
    poses: dict[int, dict[str, Any]],
    *,
    joint: str,
    frames: Sequence[int],
    axis: str,
    delta_deg: float,
    joint_limit_deg: float,
    min_step_deg: float = 2.0,
) -> float:
    """Same Euler delta on every listed frame of one skeleton.

    Per-frame remaining-room shrink would apply different angles on neighboring
    frames and turn the clip into a flipbook.
    """
    channel = str(axis).strip()
    if channel not in {"x", "y", "z"}:
        raise ValueError(f"bone axis must be x, y, or z; got {channel!r}")
    extra = float(delta_deg)
    limit = float(joint_limit_deg)
    floor = float(min_step_deg)
    if not math.isfinite(extra) or extra == 0.0:
        raise ValueError("delta_deg must be a non-zero finite number")
    if not math.isfinite(limit) or limit <= 0.0:
        raise ValueError("joint_limit_deg must be positive")
    if not math.isfinite(floor) or floor < 0.0:
        raise ValueError("min_step_deg must be non-negative")
    ordered = [int(frame) for frame in frames]
    if not ordered:
        raise ValueError("shared rotate needs at least one frame")
    rooms: list[float] = []
    for frame in ordered:
        pose = poses[int(frame)]
        entry = dict(pose.get(joint) or {"x": 0.0, "y": 0.0, "z": 0.0})
        current = float(entry.get(channel, 0.0))
        remaining = limit - abs(current)
        if abs(current + extra) <= limit + 1e-9:
            rooms.append(extra)
            continue
        if remaining < floor + 1e-9:
            raise ValueError(
                f"{joint} {channel} has {remaining:.3f} deg of room, under {floor:.3f} deg"
            )
        rooms.append(math.copysign(remaining, extra))
    applied = min(rooms, key=lambda value: abs(float(value)))
    for frame in ordered:
        pose = poses[int(frame)]
        entry = dict(pose.get(joint) or {"x": 0.0, "y": 0.0, "z": 0.0})
        current = float(entry.get(channel, 0.0))
        if abs(current + applied) > limit + 1e-9:
            raise ValueError(f"{joint} {channel} shared step {applied:.3f} exceeds limit on frame {frame}")
        entry[channel] = current + applied
        pose[str(joint)] = {key: float(entry.get(key, 0.0)) for key in ("x", "y", "z")}
    return float(applied)


def add_axis_angle_deg_shared_within_limit(
    poses: dict[int, dict[str, Any]],
    *,
    joint: str,
    frames: Sequence[int],
    add_xyz: Sequence[float],
    joint_limit_deg: float,
) -> np.ndarray:
    """Add a local axis-angle vector on every listed frame, or fail closed."""
    add = np.asarray(add_xyz, dtype=np.float64).reshape(3)
    if not np.all(np.isfinite(add)):
        raise ValueError("axis-angle add must be finite")
    if float(np.linalg.norm(add)) <= 1e-12:
        raise ValueError("axis-angle add must be non-zero")
    limit = float(joint_limit_deg)
    if not math.isfinite(limit) or limit <= 0.0:
        raise ValueError("joint_limit_deg must be positive")
    ordered = [int(frame) for frame in frames]
    if not ordered:
        raise ValueError("shared rotate needs at least one frame")
    name = str(joint)
    for frame in ordered:
        pose = poses[int(frame)]
        entry = dict(pose.get(name) or {"x": 0.0, "y": 0.0, "z": 0.0})
        current = np.asarray(
            [float(entry.get(axis, 0.0)) for axis in BONE_AXES], dtype=np.float64
        )
        new = current + add
        if np.any(np.abs(new) > limit + 1e-9):
            raise ValueError(
                f"{name} model-axis add exceeds joint_limit_deg on frame {frame}"
            )
    for frame in ordered:
        pose = poses[int(frame)]
        entry = dict(pose.get(name) or {"x": 0.0, "y": 0.0, "z": 0.0})
        current = np.asarray(
            [float(entry.get(axis, 0.0)) for axis in BONE_AXES], dtype=np.float64
        )
        new = current + add
        pose[name] = {axis: float(new[index]) for index, axis in enumerate(BONE_AXES)}
    return add.copy()


def rotate_bone_model_axis_deg_shared(
    poses: dict[int, dict[str, Any]],
    *,
    joint: str,
    frames: Sequence[int],
    rest_rotation: np.ndarray,
    axis_world: Sequence[float],
    delta_deg: float,
    joint_limit_deg: float,
) -> float:
    """Add a model-frame axis rotation, converted into this bone's local delta."""
    extra = float(delta_deg)
    if not math.isfinite(extra) or extra == 0.0:
        raise ValueError("delta_deg must be a non-zero finite number")
    rest = orthonormal_rotation(rest_rotation)
    axis = np.asarray(axis_world, dtype=np.float64).reshape(3)
    length = float(np.linalg.norm(axis))
    if length <= 1e-12:
        raise ValueError("model axis must be non-zero")
    add = rest.T @ ((axis / length) * extra)
    add_axis_angle_deg_shared_within_limit(
        poses,
        joint=str(joint),
        frames=frames,
        add_xyz=add,
        joint_limit_deg=float(joint_limit_deg),
    )
    return extra


def rotate_bilateral_pair_deg_shared(
    poses: dict[int, dict[str, Any]],
    *,
    bone_a: str,
    bone_b: str,
    frames: Sequence[int],
    axis: str,
    delta_deg: float,
    joint_limit_deg: float,
    rest_rotations: Mapping[str, np.ndarray],
    model_frame: Mapping[str, np.ndarray],
    bone_dirs: Mapping[str, np.ndarray],
) -> float:
    """Same anatomical raise/sweep/twist on both sides of a catalog pair."""
    left = str(bone_a)
    right = str(bone_b)
    if left == right:
        raise ValueError("bilateral pair bones must be distinct")
    name = str(axis)
    if name not in ANATOMICAL_AXES:
        raise ValueError(f"bilateral pair axis must be one of {ANATOMICAL_AXES}, got {name!r}")
    missing = [bone for bone in (left, right) if bone not in rest_rotations or bone not in bone_dirs]
    if missing:
        raise ValueError(f"bilateral pair missing rest or distal direction {missing}")
    add_a, add_b = paired_anatomical_local_adds(
        rest_rotations[left],
        rest_rotations[right],
        bone_dirs[left],
        bone_dirs[right],
        model_frame,
        name,
        float(delta_deg),
    )
    add_axis_angle_deg_shared_within_limit(
        poses,
        joint=left,
        frames=frames,
        add_xyz=add_a,
        joint_limit_deg=float(joint_limit_deg),
    )
    add_axis_angle_deg_shared_within_limit(
        poses,
        joint=right,
        frames=frames,
        add_xyz=add_b,
        joint_limit_deg=float(joint_limit_deg),
    )
    return float(delta_deg)


def rotate_root_deg(
    poses: dict[int, dict[str, Any]],
    *,
    frames: Sequence[int],
    axis: str,
    delta_deg: float,
    limit_deg: float,
) -> None:
    """Add a camera-axis root rotation in degrees. Do not use radian apply_rotate."""
    channel = str(axis).strip()
    if channel not in ROOT_ROTATION_AXES:
        raise ValueError(f"root rotation axis must be one of {ROOT_ROTATION_AXES}")
    extra = float(delta_deg)
    limit = float(limit_deg)
    if not math.isfinite(extra):
        raise ValueError("delta_deg must be finite")
    if not math.isfinite(limit) or limit <= 0.0:
        raise ValueError("limit_deg must be positive")
    zeros = {name: 0.0 for name in ROOT_ROTATION_AXES}
    for frame in frames:
        pose = poses[int(frame)]
        entry = dict(pose.get(MOTION_ROOT_ROTATION_KEY) or zeros)
        next_value = float(entry.get(channel, 0.0)) + extra
        if abs(next_value) > limit + 1e-9:
            raise ValueError(
                f"root {channel} would be {next_value:.3f} deg, over the {limit:.3f} deg limit"
            )
        entry[channel] = next_value
        pose[MOTION_ROOT_ROTATION_KEY] = {name: float(entry.get(name, 0.0)) for name in ROOT_ROTATION_AXES}


def set_root_rotation_deg(
    poses: dict[int, dict[str, Any]],
    *,
    frames: Sequence[int],
    values_deg: Mapping[str, float],
) -> None:
    """Write named camera-axis root rotations in degrees. Unlisted axes stay."""
    if not values_deg:
        raise ValueError("set_root_rotation_deg requires at least one axis")
    illegal = [name for name in values_deg if str(name) not in ROOT_ROTATION_AXES]
    if illegal:
        raise ValueError(f"root rotation keys must be {ROOT_ROTATION_AXES}, got {illegal}")
    zeros = {name: 0.0 for name in ROOT_ROTATION_AXES}
    for frame in frames:
        pose = poses[int(frame)]
        entry = dict(pose.get(MOTION_ROOT_ROTATION_KEY) or zeros)
        for axis, value in values_deg.items():
            angle = float(value)
            if not math.isfinite(angle):
                raise ValueError(f"root {axis} must be finite degrees")
            entry[str(axis)] = angle
        pose[MOTION_ROOT_ROTATION_KEY] = {
            name: float(entry.get(name, 0.0)) for name in ROOT_ROTATION_AXES
        }


def translate_root(
    poses: dict[int, dict[str, Any]],
    *,
    frames: Sequence[int],
    axis: str,
    delta: float,
    limit: float,
) -> None:
    channel = str(axis).strip()
    if channel not in ROOT_TRANSLATION_AXES:
        raise ValueError(f"root translation axis must be one of {ROOT_TRANSLATION_AXES}")
    extra = float(delta)
    cap = float(limit)
    if not math.isfinite(extra):
        raise ValueError("delta must be finite")
    if not math.isfinite(cap) or cap <= 0.0:
        raise ValueError("limit must be positive")
    zeros = {name: 0.0 for name in ROOT_TRANSLATION_AXES}
    for frame in frames:
        pose = poses[int(frame)]
        entry = dict(pose.get(MOTION_ROOT_KEY) or zeros)
        next_value = float(entry.get(channel, 0.0)) + extra
        if abs(next_value) > cap + 1e-9:
            raise ValueError(
                f"root {channel} would be {next_value:.3f}, over the {cap:.3f} translation limit"
            )
        entry[channel] = next_value
        pose[MOTION_ROOT_KEY] = {name: float(entry.get(name, 0.0)) for name in ROOT_TRANSLATION_AXES}


def clone_pose_map(poses: Mapping[int, Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for frame, pose in poses.items():
        copied: dict[str, Any] = {}
        for key, value in pose.items():
            copied[str(key)] = dict(value) if isinstance(value, Mapping) else value
        out[int(frame)] = copied
    return out


def bind_like_poses(
    poses: Mapping[int, Mapping[str, Any]],
    frames: Sequence[int],
) -> dict[int, dict[str, Any]]:
    """Zero joint and root rotation. Keep root translation so framing stays."""
    out: dict[int, dict[str, Any]] = {}
    for frame in frames:
        src = poses.get(int(frame), {})
        entry: dict[str, Any] = {}
        root = src.get(MOTION_ROOT_KEY)
        if isinstance(root, Mapping):
            entry[MOTION_ROOT_KEY] = {
                name: float(root.get(name, 0.0)) for name in ROOT_TRANSLATION_AXES
            }
        out[int(frame)] = entry
    return out


def identity_joint_keep_root_poses(
    poses: Mapping[int, Mapping[str, Any]],
    frames: Sequence[int],
) -> dict[int, dict[str, Any]]:
    """Zero joint Euler. Keep motion-root translation and rotation.

    Phase-baked fly rest already contains the representative body. Joint
    identity on move frames must not also zero the camera-axis root, or the
    bird leaves the occupancy camera.
    """
    out: dict[int, dict[str, Any]] = {}
    for frame in frames:
        src = poses.get(int(frame), {})
        entry: dict[str, Any] = {}
        root = src.get(MOTION_ROOT_KEY)
        if isinstance(root, Mapping):
            entry[MOTION_ROOT_KEY] = {
                name: float(root.get(name, 0.0)) for name in ROOT_TRANSLATION_AXES
            }
        rotation = src.get(MOTION_ROOT_ROTATION_KEY)
        if isinstance(rotation, Mapping):
            entry[MOTION_ROOT_ROTATION_KEY] = {
                name: float(rotation.get(name, 0.0)) for name in ROOT_ROTATION_AXES
            }
        out[int(frame)] = entry
    return out


def copy_joints_keep_dest_root(
    poses: dict[int, dict[str, Any]],
    *,
    dest_frame: int,
    src_frame: int,
) -> None:
    """Copy joint Euler from src onto dest. Keep dest motion-root translation and rotation."""
    dest = int(dest_frame)
    src = int(src_frame)
    if dest not in poses:
        raise ValueError(f"copy joints missing dest frame {dest}")
    if src not in poses:
        raise ValueError(f"copy joints missing src frame {src}")
    dest_pose = poses[dest]
    src_pose = poses[src]
    copied: dict[str, Any] = {}
    for key, value in src_pose.items():
        if str(key).startswith("__"):
            continue
        copied[str(key)] = dict(value) if isinstance(value, Mapping) else value
    root = dest_pose.get(MOTION_ROOT_KEY)
    if isinstance(root, Mapping):
        copied[MOTION_ROOT_KEY] = {
            name: float(root.get(name, 0.0)) for name in ROOT_TRANSLATION_AXES
        }
    rotation = dest_pose.get(MOTION_ROOT_ROTATION_KEY)
    if isinstance(rotation, Mapping):
        copied[MOTION_ROOT_ROTATION_KEY] = {
            name: float(rotation.get(name, 0.0)) for name in ROOT_ROTATION_AXES
        }
    poses[dest] = copied


def seed_frame_from_inertial(
    poses: dict[int, dict[str, Any]],
    *,
    dest_frame: int,
    history_frames: Sequence[int],
    joint_limit_deg: float,
) -> None:
    """Seed dest joints from previous pose plus velocity and acceleration.

    Keep dest motion-root translation and rotation. Axis-angle add is the
    init only; leftover search runs after this write.
    """
    dest = int(dest_frame)
    history = [int(frame) for frame in history_frames]
    if dest not in poses:
        raise ValueError(f"inertial seed missing dest frame {dest}")
    if not history:
        raise ValueError("inertial seed needs at least one previous frame")
    missing = [frame for frame in history if frame not in poses]
    if missing:
        raise ValueError(f"inertial seed missing history frames {missing}")
    limit = float(joint_limit_deg)
    if not math.isfinite(limit) or limit <= 0.0:
        raise ValueError("joint_limit_deg must be positive")
    dest_pose = poses[dest]
    names: list[str] = []
    seen: set[str] = set()
    for frame in history:
        for key in poses[int(frame)]:
            name = str(key)
            if name.startswith("__") or name in seen:
                continue
            seen.add(name)
            names.append(name)
    seeded: dict[str, Any] = {}
    for name in names:
        channels = {
            axis: predict_channel_inertial(
                [_bone_xyz(poses[int(frame)], name)[axis] for frame in history]
            )
            for axis in BONE_AXES
        }
        seeded[name] = {
            axis: max(-limit, min(limit, float(channels[axis]))) for axis in BONE_AXES
        }
    root = dest_pose.get(MOTION_ROOT_KEY)
    if isinstance(root, Mapping):
        seeded[MOTION_ROOT_KEY] = {
            name: float(root.get(name, 0.0)) for name in ROOT_TRANSLATION_AXES
        }
    rotation = dest_pose.get(MOTION_ROOT_ROTATION_KEY)
    if isinstance(rotation, Mapping):
        seeded[MOTION_ROOT_ROTATION_KEY] = {
            name: float(rotation.get(name, 0.0)) for name in ROOT_ROTATION_AXES
        }
    poses[dest] = seeded


def seed_frame_pipeline_relative(
    dest_poses: dict[int, dict[str, Any]],
    pipeline_poses: Mapping[int, Mapping[str, Any]],
    *,
    dest_frame: int,
    reference_frame: int,
    joint_limit_deg: float,
) -> None:
    """Seed dest joints as pipeline[dest] minus pipeline[reference].

    Phase-baked fly rest already contains the representative pose, so identity
    is that body. Other frames need the pipeline delta from that representative,
    not leftover-invented 90° Euler. Keep dest motion-root translation and rotation.
    """
    dest = int(dest_frame)
    reference = int(reference_frame)
    if dest not in dest_poses:
        raise ValueError(f"pipeline-relative seed missing dest frame {dest}")
    if dest not in pipeline_poses:
        raise ValueError(f"pipeline-relative seed missing pipeline dest frame {dest}")
    if reference not in pipeline_poses:
        raise ValueError(f"pipeline-relative seed missing pipeline reference frame {reference}")
    limit = float(joint_limit_deg)
    if not math.isfinite(limit) or limit <= 0.0:
        raise ValueError("joint_limit_deg must be positive")
    dest_pose = dest_poses[dest]
    src = pipeline_poses[int(dest)]
    ref = pipeline_poses[int(reference)]
    names: list[str] = []
    seen: set[str] = set()
    for pose in (src, ref):
        for key in pose:
            name = str(key)
            if name.startswith("__") or name in seen:
                continue
            seen.add(name)
            names.append(name)
    seeded: dict[str, Any] = {}
    for name in names:
        src_xyz = _bone_xyz(src, name)
        ref_xyz = _bone_xyz(ref, name)
        seeded[name] = {
            axis: max(-limit, min(limit, src_xyz[axis] - ref_xyz[axis])) for axis in BONE_AXES
        }
    root = dest_pose.get(MOTION_ROOT_KEY)
    if isinstance(root, Mapping):
        seeded[MOTION_ROOT_KEY] = {
            name: float(root.get(name, 0.0)) for name in ROOT_TRANSLATION_AXES
        }
    rotation = dest_pose.get(MOTION_ROOT_ROTATION_KEY)
    if isinstance(rotation, Mapping):
        seeded[MOTION_ROOT_ROTATION_KEY] = {
            name: float(rotation.get(name, 0.0)) for name in ROOT_ROTATION_AXES
        }
    dest_poses[dest] = seeded


def write_camera_fit_from_candidate(
    seed_path: str | Path,
    dest_path: str | Path,
    candidate: Mapping[str, Any],
    *,
    source_resolution: Sequence[int],
) -> Path:
    data = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    width, height = (int(value) for value in source_resolution)
    fit_res = data.get("sourceResolution") or (width, height)
    src_w, src_h = (int(fit_res[0]), int(fit_res[1]))
    right = np.asarray(candidate["right"], dtype=np.float64).reshape(3)
    down = np.asarray(candidate["down"], dtype=np.float64).reshape(3)
    px = np.asarray(candidate["pxPerWorld"], dtype=np.float64).reshape(2)
    offset = np.asarray(candidate["screenOffsetPx"], dtype=np.float64).reshape(2)
    scale_x = width / max(src_w, 1)
    scale_y = height / max(src_h, 1)
    # Candidates were scored at init resolution; the fit file stores source pixels.
    data["basisScreenRows"] = [right.tolist(), down.tolist()]
    data["pxPerWorld"] = float(px[0]) / max(scale_x, 1e-8)
    data["screenOffsetPx"] = [
        float(offset[0]) / max(scale_x, 1e-8),
        float(offset[1]) / max(scale_y, 1e-8),
    ]
    data["cameraPolicy"] = "sprite_feasibility_camera_surgery"
    metrics = dict(data.get("profileMetrics") or {})
    metrics["bestYawDeg"] = float(candidate["yawDeg"])
    metrics["bestRollDeg"] = float(candidate.get("rollDeg") or 0.0)
    metrics["facingScore"] = float(candidate.get("facingScore") or 0.0)
    metrics["bestScore"] = float(candidate.get("score") or candidate.get("silhouetteScore") or 0.0)
    metrics["bestIoU"] = float(candidate.get("iou") or 0.0)
    data["profileMetrics"] = metrics
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return dest


def write_after_poses(
    dest_path: str | Path,
    poses: Mapping[int, Mapping[str, Any]],
    *,
    frame_indices: Sequence[int],
    camera_fit_path: str | Path,
) -> Path:
    payload = {
        "poseUnits": "degrees",
        "poses": {str(int(frame)): dict(poses[int(frame)]) for frame in frame_indices},
        "frameIndices": [int(frame) for frame in frame_indices],
        "cameraFitPath": str(Path(camera_fit_path).resolve()),
    }
    require_pose_units_degrees(payload, source=str(dest_path))
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return dest


def write_minimal_skinned_glb(path: str | Path) -> Path:
    """Two-joint bar used by unit tests. Root at origin, child along +Y."""
    positions = np.asarray(
        (
            (0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.2, 0.0, 0.0),
            (0.2, 1.0, 0.0),
            (0.0, 1.6, 0.0),
            (0.2, 1.6, 0.0),
        ),
        dtype=np.float32,
    )
    indices = np.asarray((0, 1, 2, 1, 3, 2, 1, 4, 3, 4, 5, 3), dtype=np.uint16)
    joints = np.asarray(
        (
            (0, 0, 0, 0),
            (1, 0, 0, 0),
            (0, 0, 0, 0),
            (1, 0, 0, 0),
            (1, 0, 0, 0),
            (1, 0, 0, 0),
        ),
        dtype=np.uint16,
    )
    weights = np.zeros((6, 4), dtype=np.float32)
    weights[:, 0] = 1.0
    ibm = np.stack([np.eye(4, dtype=np.float32), np.eye(4, dtype=np.float32)])
    ibm[1, 1, 3] = -1.0
    chunks: list[bytes] = []
    offsets: list[int] = []

    def add(array: np.ndarray) -> int:
        raw = np.asarray(array).tobytes()
        while len(b"".join(chunks)) % 4:
            chunks.append(b"\x00")
        start = sum(len(item) for item in chunks)
        chunks.append(raw)
        offsets.append(start)
        return start

    pos_off = add(positions)
    idx_off = add(indices)
    joint_off = add(joints)
    weight_off = add(weights)
    ibm_off = add(ibm.reshape(-1))
    blob = bytearray(b"".join(chunks))
    doc = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": pos_off, "byteLength": positions.nbytes},
            {"buffer": 0, "byteOffset": idx_off, "byteLength": indices.nbytes},
            {"buffer": 0, "byteOffset": joint_off, "byteLength": joints.nbytes},
            {"buffer": 0, "byteOffset": weight_off, "byteLength": weights.nbytes},
            {"buffer": 0, "byteOffset": ibm_off, "byteLength": ibm.nbytes},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 6,
                "type": "VEC3",
                "min": positions.min(axis=0).tolist(),
                "max": positions.max(axis=0).tolist(),
            },
            {"bufferView": 1, "componentType": 5123, "count": 12, "type": "SCALAR"},
            {"bufferView": 2, "componentType": 5123, "count": 6, "type": "VEC4"},
            {"bufferView": 3, "componentType": 5126, "count": 6, "type": "VEC4"},
            {"bufferView": 4, "componentType": 5126, "count": 2, "type": "MAT4"},
        ],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "JOINTS_0": 2, "WEIGHTS_0": 3},
                        "indices": 1,
                    }
                ]
            }
        ],
        "nodes": [
            {"name": "Root", "children": [1], "translation": [0.0, 0.0, 0.0]},
            {"name": "Bone_A", "translation": [0.0, 1.0, 0.0]},
        ],
        "skins": [{"joints": [0, 1], "inverseBindMatrices": 4}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    save_glb(dest, doc, blob)
    validate_skinned_glb(dest)
    return dest
