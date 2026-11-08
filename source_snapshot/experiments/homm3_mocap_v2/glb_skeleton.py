"""Read a GLB skin skeleton without converting to FBX or deleting bones."""
from __future__ import annotations

import io
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

MAT4 = np.float64


def read_glb(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError(f"not a GLB file: {path}")
    offset = 12
    json_doc = None
    bin_chunk = b""
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        start = offset + 8
        end = start + chunk_length
        if end > len(data):
            raise ValueError(f"truncated GLB chunk: {path}")
        if chunk_type == b"JSON":
            json_doc = json.loads(data[start:end].decode("utf-8").rstrip(" \t\r\n\x00"))
        elif chunk_type == b"BIN\x00":
            bin_chunk = data[start:end]
        offset = end
    if json_doc is None:
        raise ValueError(f"GLB has no JSON chunk: {path}")
    return {"json": json_doc, "bin": bin_chunk}


def _accessor(doc: dict[str, Any], bin_chunk: bytes, accessor_index: int) -> np.ndarray:
    json_doc = doc["json"]
    acc = json_doc["accessors"][accessor_index]
    bv = json_doc["bufferViews"][acc["bufferView"]]
    dtype = {
        5120: np.int8,
        5121: np.uint8,
        5122: np.int16,
        5123: np.uint16,
        5125: np.uint32,
        5126: np.float32,
    }[acc["componentType"]]
    components = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[acc["type"]]
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    itemsize = np.dtype(dtype).itemsize
    stride = int(bv.get("byteStride") or itemsize * components)
    if stride == itemsize * components:
        nbytes = acc["count"] * components * itemsize
        raw = np.frombuffer(bin_chunk[start : start + nbytes], dtype=dtype).copy()
    else:
        raw = np.empty(acc["count"] * components, dtype=dtype)
        span = components * itemsize
        for index in range(acc["count"]):
            offset = start + index * stride
            raw[index * components : (index + 1) * components] = np.frombuffer(
                bin_chunk[offset : offset + span], dtype=dtype
            )
    return raw


def _compose_matrix(translation: np.ndarray, rotation_xyzw: np.ndarray, scale: np.ndarray) -> np.ndarray:
    qx, qy, qz, qw = rotation_xyzw
    matrix = np.eye(4, dtype=MAT4)
    matrix[0, 0] = 1 - 2 * (qy * qy + qz * qz)
    matrix[0, 1] = 2 * (qx * qy - qz * qw)
    matrix[0, 2] = 2 * (qx * qz + qy * qw)
    matrix[1, 0] = 2 * (qx * qy + qz * qw)
    matrix[1, 1] = 1 - 2 * (qx * qx + qz * qz)
    matrix[1, 2] = 2 * (qy * qz - qx * qw)
    matrix[2, 0] = 2 * (qx * qz - qy * qw)
    matrix[2, 1] = 2 * (qy * qz + qx * qw)
    matrix[2, 2] = 1 - 2 * (qx * qx + qy * qy)
    matrix[:3, 3] = translation
    matrix[0, 0] *= scale[0]
    matrix[0, 1] *= scale[1]
    matrix[0, 2] *= scale[2]
    matrix[1, 0] *= scale[0]
    matrix[1, 1] *= scale[1]
    matrix[1, 2] *= scale[2]
    matrix[2, 0] *= scale[0]
    matrix[2, 1] *= scale[1]
    matrix[2, 2] *= scale[2]
    return matrix


def _node_local_matrix(node: dict[str, Any]) -> np.ndarray:
    translation = np.array(node.get("translation", [0.0, 0.0, 0.0]), dtype=MAT4)
    rotation = np.array(node.get("rotation", [0.0, 0.0, 0.0, 1.0]), dtype=MAT4)
    scale = np.array(node.get("scale", [1.0, 1.0, 1.0]), dtype=MAT4)
    return _compose_matrix(translation, rotation, scale)


def _world_matrix(nodes: list[dict[str, Any]], node_index: int, cache: dict[int, np.ndarray]) -> np.ndarray:
    if node_index in cache:
        return cache[node_index]
    local = _node_local_matrix(nodes[node_index])
    parents = [index for index, node in enumerate(nodes) if node_index in node.get("children", ())]
    if len(parents) > 1:
        raise ValueError(f"GLB node {node_index} has multiple parents")
    if parents:
        world = _world_matrix(nodes, parents[0], cache) @ local
    else:
        world = local
    cache[node_index] = world
    return world


@dataclass(frozen=True)
class BindSkeleton:
    names: tuple[str, ...]
    node_indices: tuple[int, ...]
    parents: tuple[int, ...]
    rest_world: np.ndarray
    rest_local_rotation: np.ndarray
    rest_local_translation: np.ndarray
    inverse_bind: np.ndarray | None
    vertices: np.ndarray | None
    vertex_joints: np.ndarray | None
    vertex_weights: np.ndarray | None
    triangles: np.ndarray | None
    uvs: np.ndarray | None
    normals: np.ndarray | None
    albedo: np.ndarray | None


def _base_color_albedo(doc: dict[str, Any], primitive: dict[str, Any]) -> np.ndarray | None:
    json_doc = doc["json"]
    material_index = primitive.get("material")
    if material_index is None:
        return None
    material = json_doc["materials"][int(material_index)]
    pbr = material.get("pbrMetallicRoughness") or {}
    texture_info = pbr.get("baseColorTexture")
    if not texture_info:
        return None
    texture = json_doc["textures"][int(texture_info["index"])]
    image = json_doc["images"][int(texture["source"])]
    if "bufferView" not in image:
        raise ValueError("base color image is not packed in the GLB")
    view = json_doc["bufferViews"][int(image["bufferView"])]
    start = int(view.get("byteOffset", 0))
    payload = doc["bin"][start : start + int(view["byteLength"])]
    decoded = Image.open(io.BytesIO(payload)).convert("RGBA")
    return np.asarray(decoded, dtype=np.uint8)


def load_bind_skeleton(mesh_glb: Path) -> BindSkeleton:
    doc = read_glb(mesh_glb)
    json_doc = doc["json"]
    nodes = json_doc.get("nodes") or []
    skins = json_doc.get("skins") or []
    if not skins:
        raise ValueError(f"{mesh_glb} has no skins")
    if len(skins) != 1:
        raise ValueError(f"{mesh_glb} has {len(skins)} skins; expected exactly one")
    skin = skins[0]
    joint_nodes = tuple(int(index) for index in skin.get("joints") or ())
    if not joint_nodes:
        raise ValueError(f"{mesh_glb} skin has no joints")
    if len(joint_nodes) > 150:
        raise ValueError(f"{mesh_glb} has {len(joint_nodes)} joints; vendor pad limit is 150")
    node_to_joint = {node_index: joint_index for joint_index, node_index in enumerate(joint_nodes)}
    parents: list[int] = []
    names: list[str] = []
    world_cache: dict[int, np.ndarray] = {}
    rest_world = np.zeros((len(joint_nodes), 3), dtype=np.float64)
    rest_local_rotation = np.zeros((len(joint_nodes), 3, 3), dtype=np.float64)
    rest_local_translation = np.zeros((len(joint_nodes), 3), dtype=np.float64)
    for joint_index, node_index in enumerate(joint_nodes):
        node = nodes[node_index]
        names.append(str(node.get("name") or f"node{node_index}"))
        local = _node_local_matrix(node)
        rest_local_rotation[joint_index] = local[:3, :3]
        rest_local_translation[joint_index] = local[:3, 3]
        rest_world[joint_index] = _world_matrix(nodes, node_index, world_cache)[:3, 3]
        parent_node = None
        current = node_index
        seen = {current}
        while True:
            found = [index for index, candidate in enumerate(nodes) if current in candidate.get("children", ())]
            if not found:
                break
            if len(found) != 1:
                raise ValueError(f"ambiguous parent for node {current}")
            current = found[0]
            if current in seen:
                raise ValueError(f"parent cycle at node {current}")
            seen.add(current)
            if current in node_to_joint:
                parent_node = current
                break
        parents.append(-1 if parent_node is None else int(node_to_joint[parent_node]))

    inverse_bind = None
    if "inverseBindMatrices" in skin:
        raw = _accessor(doc, doc["bin"], int(skin["inverseBindMatrices"])).reshape(-1, 4, 4)
        inverse_bind = np.transpose(raw, (0, 2, 1)).astype(np.float64)
        if inverse_bind.shape[0] != len(joint_nodes):
            raise ValueError("inverse bind count does not match joint count")

    vertices = vertex_joints = vertex_weights = triangles = uvs = normals = albedo = None
    for mesh in json_doc.get("meshes") or ():
        for primitive in mesh.get("primitives") or ():
            attrs = primitive.get("attributes") or {}
            if "POSITION" not in attrs or "JOINTS_0" not in attrs or "WEIGHTS_0" not in attrs:
                continue
            if vertices is not None:
                raise ValueError(f"{mesh_glb} has multiple skinned primitives")
            vertices = _accessor(doc, doc["bin"], int(attrs["POSITION"])).reshape(-1, 3).astype(np.float64)
            joint_sets = []
            weight_sets = []
            index = 0
            while f"JOINTS_{index}" in attrs and f"WEIGHTS_{index}" in attrs:
                joint_sets.append(
                    _accessor(doc, doc["bin"], int(attrs[f"JOINTS_{index}"])).astype(np.int32).reshape(-1, 4)
                )
                weight_sets.append(
                    _accessor(doc, doc["bin"], int(attrs[f"WEIGHTS_{index}"])).reshape(-1, 4).astype(np.float64)
                )
                index += 1
            vertex_joints = np.concatenate(joint_sets, axis=1)
            vertex_weights = np.concatenate(weight_sets, axis=1)
            if "TEXCOORD_0" in attrs:
                uvs = _accessor(doc, doc["bin"], int(attrs["TEXCOORD_0"])).reshape(-1, 2).astype(np.float64)
            if "NORMAL" in attrs:
                normals = _accessor(doc, doc["bin"], int(attrs["NORMAL"])).reshape(-1, 3).astype(np.float64)
            if "indices" in primitive:
                triangles = _accessor(doc, doc["bin"], int(primitive["indices"])).astype(np.int32).reshape(-1, 3)
            albedo = _base_color_albedo(doc, primitive)

    order = _topological_order(parents)
    names = [names[index] for index in order]
    joint_nodes = tuple(joint_nodes[index] for index in order)
    rest_world = rest_world[list(order)]
    rest_local_rotation = rest_local_rotation[list(order)]
    rest_local_translation = rest_local_translation[list(order)]
    remap = {old: new for new, old in enumerate(order)}
    parents = [(-1 if parents[index] < 0 else remap[int(parents[index])]) for index in order]
    if inverse_bind is not None:
        inverse_bind = inverse_bind[list(order)]
    if vertex_joints is not None:
        remap_lut = np.zeros((len(order),), dtype=np.int32)
        for new, old in enumerate(order):
            remap_lut[old] = new
        vertex_joints = remap_lut[vertex_joints]

    return BindSkeleton(
        names=tuple(names),
        node_indices=joint_nodes,
        parents=tuple(parents),
        rest_world=rest_world,
        rest_local_rotation=rest_local_rotation,
        rest_local_translation=rest_local_translation,
        inverse_bind=inverse_bind,
        vertices=vertices,
        vertex_joints=vertex_joints,
        vertex_weights=vertex_weights,
        triangles=triangles,
        uvs=uvs,
        normals=normals,
        albedo=albedo,
    )


def _topological_order(parents: list[int]) -> list[int]:
    children: dict[int, list[int]] = {}
    roots: list[int] = []
    for index, parent in enumerate(parents):
        if parent < 0:
            roots.append(index)
            continue
        children.setdefault(int(parent), []).append(index)
    if len(roots) != 1:
        raise ValueError(f"expected one root, got {roots}")
    order: list[int] = []
    stack = list(roots)
    seen: set[int] = set()
    while stack:
        node = stack.pop(0)
        if node in seen:
            raise ValueError(f"cycle at joint {node}")
        seen.add(node)
        order.append(node)
        stack.extend(sorted(children.get(node, ())))
    if len(order) != len(parents):
        raise ValueError("topological order missed joints")
    return order
