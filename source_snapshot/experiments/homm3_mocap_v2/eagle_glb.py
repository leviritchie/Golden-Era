"""Write a skinned GLB and reload it. Influence truncation is measured, not silent."""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from glb_skeleton import BindSkeleton, load_bind_skeleton
from glb_skeleton import _compose_matrix, _topological_order
from mesh_preview import skin_vertices

RELOAD_IDENTITY_FACTOR = 1e-5

OWN_BIND_IDENTITY_REL = 1e-5
IBM_REST_IDENTITY_ABS = 1e-5


def _pad4(data: bytes) -> bytes:
    return data + b"\x00" * ((4 - (len(data) % 4)) % 4)


def _pad_json4(data: bytes) -> bytes:
    """Pad a glTF JSON chunk with spaces, as required by the GLB spec."""
    return data + b" " * ((4 - (len(data) % 4)) % 4)


def _top_influences(weights: np.ndarray, slots: int = 8) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    values = np.asarray(weights, dtype=np.float64)
    order = np.argsort(-values, axis=1)[:, :slots]
    kept = np.take_along_axis(values, order, axis=1)
    dropped = values.sum(axis=1) - kept.sum(axis=1)
    kept = kept / np.maximum(kept.sum(axis=1, keepdims=True), 1e-8)
    return order.astype(np.uint16), kept.astype(np.float32), {
        "maxDroppedWeight": float(dropped.max()),
        "meanDroppedWeight": float(dropped.mean()),
        "slots": int(slots),
    }


def _png_bytes(albedo: np.ndarray) -> bytes:
    image = Image.fromarray(np.asarray(albedo, dtype=np.uint8), mode="RGBA")
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def write_skinned_glb(
    path: Path,
    *,
    names: list[str],
    parents: np.ndarray,
    rest_local_rotation: np.ndarray,
    rest_local_translation: np.ndarray,
    inverse_bind: np.ndarray,
    vertices: np.ndarray,
    triangles: np.ndarray,
    uvs: np.ndarray,
    albedo: np.ndarray,
    weights: np.ndarray,
    animation: dict[str, np.ndarray] | None = None,
) -> dict[str, Any]:
    names, parents, rest_local_rotation, rest_local_translation, inverse_bind, weights, animation = _match_loader_order(
        names,
        parents,
        rest_local_rotation,
        rest_local_translation,
        inverse_bind,
        weights,
        animation,
    )
    _require_gltf_rest_inverts_ibm(
        parents=parents,
        rest_local_rotation=rest_local_rotation,
        rest_local_translation=rest_local_translation,
        inverse_bind=inverse_bind,
    )
    joints, skin_w, truncation = _top_influences(weights, slots=8)
    normals = _vertex_normals(vertices, triangles)
    bin_parts: list[bytes] = []
    accessors = []
    buffer_views = []

    def add_array(array: np.ndarray, typ: str, component: int, target: int | None = None) -> int:
        data = np.ascontiguousarray(array)
        raw = data.tobytes()
        offset = sum(len(part) for part in bin_parts)
        bin_parts.append(_pad4(raw))
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(raw)}
        if target is not None:
            view["target"] = target
        buffer_views.append(view)
        acc: dict[str, Any] = {
            "bufferView": len(buffer_views) - 1,
            "componentType": component,
            "count": int(data.shape[0]),
            "type": typ,
        }
        if data.dtype.kind == "f":
            flat = data.reshape(data.shape[0], -1)
            acc["min"] = flat.min(axis=0).astype(float).tolist()
            acc["max"] = flat.max(axis=0).astype(float).tolist()
        accessors.append(acc)
        return len(accessors) - 1

    pos_acc = add_array(vertices.astype(np.float32), "VEC3", 5126, 34962)
    nrm_acc = add_array(normals.astype(np.float32), "VEC3", 5126, 34962)
    uv_acc = add_array(uvs.astype(np.float32), "VEC2", 5126, 34962)
    j0_acc = add_array(joints[:, :4], "VEC4", 5123, 34962)
    w0_acc = add_array(skin_w[:, :4], "VEC4", 5126, 34962)
    j1_acc = add_array(joints[:, 4:8], "VEC4", 5123, 34962)
    w1_acc = add_array(skin_w[:, 4:8], "VEC4", 5126, 34962)
    idx_acc = add_array(triangles.astype(np.uint32).reshape(-1), "SCALAR", 5125, 34963)
    ibm = np.transpose(inverse_bind.astype(np.float32), (0, 2, 1)).reshape(len(names), 16)
    ibm_acc = add_array(ibm, "MAT4", 5126)

    png = _png_bytes(albedo)
    img_offset = sum(len(part) for part in bin_parts)
    bin_parts.append(_pad4(png))
    buffer_views.append({"buffer": 0, "byteOffset": img_offset, "byteLength": len(png)})

    nodes = []
    for index, name in enumerate(names):
        # glTF root translation is world. Do not write the in-memory FK
        # convention of local_t[0]=0 with a separate rest_world[0].
        rotation = _matrix_to_xyzw(rest_local_rotation[index])
        translation = rest_local_translation[index].astype(float).tolist()
        node: dict[str, Any] = {
            "name": name,
            "rotation": rotation,
            "translation": translation,
        }
        children = [int(child) for child, parent in enumerate(parents) if int(parent) == index]
        if children:
            node["children"] = children
        nodes.append(node)
    mesh_node = len(nodes)
    nodes.append({"name": "RocCopyMesh", "mesh": 0, "skin": 0})
    root_nodes = [int(index) for index, parent in enumerate(parents) if int(parent) < 0] + [mesh_node]

    doc: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "eagle_skinned_roc"},
        "scenes": [{"nodes": root_nodes}],
        "scene": 0,
        "nodes": nodes,
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": pos_acc,
                            "NORMAL": nrm_acc,
                            "TEXCOORD_0": uv_acc,
                            "JOINTS_0": j0_acc,
                            "WEIGHTS_0": w0_acc,
                            "JOINTS_1": j1_acc,
                            "WEIGHTS_1": w1_acc,
                        },
                        "indices": idx_acc,
                        "material": 0,
                    }
                ]
            }
        ],
        "skins": [{"joints": list(range(len(names))), "inverseBindMatrices": ibm_acc}],
        "materials": [
            {
                "pbrMetallicRoughness": {
                    "baseColorTexture": {"index": 0},
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.8,
                }
            }
        ],
        "textures": [{"source": 0}],
        "images": [{"bufferView": len(buffer_views) - 1, "mimeType": "image/png"}],
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": sum(len(part) for part in bin_parts)}],
    }
    if animation is not None:
        _attach_animation(doc, add_array, animation, joint_count=len(names))
    blob = b"".join(bin_parts)
    doc["buffers"][0]["byteLength"] = len(blob)
    # JSON chunks may only use ASCII space padding.  NUL padding is valid for
    # BIN chunks but rejected by Blender and some strict glTF readers.
    json_bytes = _pad_json4(json.dumps(doc, separators=(",", ":")).encode("utf-8"))
    glb = b"glTF" + struct.pack("<I", 2)
    glb += struct.pack("<I", 12 + 8 + len(json_bytes) + 8 + len(blob))
    glb += struct.pack("<I", len(json_bytes)) + b"JSON" + json_bytes
    glb += struct.pack("<I", len(blob)) + b"BIN\x00" + blob
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(glb)
    return {"path": str(path).replace("\\", "/"), "truncation": truncation, "wroteAnimation": animation is not None}


def _match_loader_order(
    names: list[str],
    parents: np.ndarray,
    rest_local_rotation: np.ndarray,
    rest_local_translation: np.ndarray,
    inverse_bind: np.ndarray,
    weights: np.ndarray,
    animation: dict[str, np.ndarray] | None,
) -> tuple:
    order = _topological_order([int(value) for value in np.asarray(parents).tolist()])
    if order == list(range(len(names))):
        return names, parents, rest_local_rotation, rest_local_translation, inverse_bind, weights, animation
    inv = np.empty(len(order), dtype=np.int64)
    for new, old in enumerate(order):
        inv[old] = new
    names = [names[index] for index in order]
    parents = np.asarray([-1 if int(parents[index]) < 0 else int(inv[int(parents[index])]) for index in order], dtype=np.int64)
    rest_local_rotation = np.asarray(rest_local_rotation)[order]
    rest_local_translation = np.asarray(rest_local_translation)[order]
    inverse_bind = np.asarray(inverse_bind)[order]
    weights = np.asarray(weights)[:, order]
    if animation is not None:
        animation = dict(animation)
        if "rotations" in animation:
            animation["rotations"] = np.asarray(animation["rotations"])[:, order]
        if "translations" in animation:
            animation["translations"] = np.asarray(animation["translations"])[:, order]
    return names, parents, rest_local_rotation, rest_local_translation, inverse_bind, weights, animation


def gltf_world_matrices(
    *,
    local_rotation: np.ndarray,
    local_translation: np.ndarray,
    parents: np.ndarray,
) -> np.ndarray:
    """Compose node worlds the way a glTF loader does: root world is local TRS.

    ``fk_world_matrices`` is different: it ignores the root local translation and
    uses ``root_world`` instead. Serializing that zeroed in-memory offset as the
    glTF root ``translation`` shifts every joint by -offsets[0].
    """
    rotation = np.asarray(local_rotation, dtype=np.float64)
    translation = np.asarray(local_translation, dtype=np.float64)
    parent = np.asarray(parents, dtype=np.int64)
    worlds = np.zeros((len(parent), 4, 4), dtype=np.float64)
    for index in _topological_order([int(value) for value in parent.tolist()]):
        local = np.eye(4, dtype=np.float64)
        local[:3, :3] = rotation[index]
        local[:3, 3] = translation[index]
        parent_index = int(parent[index])
        if parent_index < 0:
            worlds[index] = local
        else:
            worlds[index] = worlds[parent_index] @ local
    return worlds


def _require_gltf_rest_inverts_ibm(
    *,
    parents: np.ndarray,
    rest_local_rotation: np.ndarray,
    rest_local_translation: np.ndarray,
    inverse_bind: np.ndarray,
) -> None:
    worlds = gltf_world_matrices(
        local_rotation=rest_local_rotation,
        local_translation=rest_local_translation,
        parents=parents,
    )
    palette = np.matmul(worlds, np.asarray(inverse_bind, dtype=np.float64))
    err = float(np.abs(palette - np.eye(4, dtype=np.float64)[None, :, :]).max())
    if err > IBM_REST_IDENTITY_ABS:
        root = next(index for index, parent in enumerate(parents) if int(parent) < 0)
        bind_origin = np.linalg.inv(np.asarray(inverse_bind[root], dtype=np.float64))[:3, 3]
        written = np.asarray(rest_local_translation[root], dtype=np.float64)
        raise ValueError(
            "written node rest worlds are not the inverse of IBM "
            f"(max {err}). Root translation is {written.tolist()} but IBM implies "
            f"bind origin {bind_origin.tolist()}. Pass the bind-pose world "
            "translation of the root (capture offsets[0]); do not write the "
            "zeroed in-memory FK offset."
        )


def own_bind_identity_gate(skeleton: BindSkeleton) -> dict[str, float]:
    """Skin at this skeleton's own node locals. ``rest_world[0]`` is not a substitute."""
    if skeleton.vertices is None:
        raise ValueError("GLB has no vertices")
    worlds = gltf_world_matrices(
        local_rotation=skeleton.rest_local_rotation,
        local_translation=skeleton.rest_local_translation,
        parents=np.asarray(skeleton.parents, dtype=np.int64),
    )
    posed = skin_vertices(skeleton, worlds)
    err = np.linalg.norm(posed - skeleton.vertices, axis=1)
    bbox = float(np.linalg.norm(skeleton.vertices.max(0) - skeleton.vertices.min(0)))
    gate = OWN_BIND_IDENTITY_REL * bbox
    max_err = float(err.max())
    return {
        "loadedOwnBindIdentityMax": max_err,
        "meshBBoxDiagonal": bbox,
        "bindIdentityGate": gate,
    }


def _attach_animation(
    doc: dict[str, Any],
    add_array,
    animation: dict[str, np.ndarray],
    *,
    joint_count: int,
) -> None:
    times = np.asarray(animation["times"], dtype=np.float32).reshape(-1)
    rotations = np.asarray(animation["rotations"], dtype=np.float32)
    if rotations.shape != (len(times), joint_count, 4):
        raise ValueError(f"animation rotations must be [T,J,4], got {rotations.shape}")
    rotations = _continuous_xyzw(rotations)
    translations = animation.get("translations")
    time_acc = add_array(times, "SCALAR", 5126)
    samplers: list[dict[str, Any]] = []
    channels: list[dict[str, Any]] = []
    for joint in range(joint_count):
        rot_acc = add_array(rotations[:, joint], "VEC4", 5126)
        samplers.append({"input": time_acc, "output": rot_acc, "interpolation": "LINEAR"})
        channels.append({"sampler": len(samplers) - 1, "target": {"node": joint, "path": "rotation"}})
        if translations is not None:
            trans = np.asarray(translations, dtype=np.float32)
            if trans.shape != (len(times), joint_count, 3):
                raise ValueError(f"animation translations must be [T,J,3], got {trans.shape}")
            t_acc = add_array(trans[:, joint], "VEC3", 5126)
            samplers.append({"input": time_acc, "output": t_acc, "interpolation": "LINEAR"})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": joint, "path": "translation"}})
    doc["animations"] = [{"name": str(animation.get("name") or "clip"), "samplers": samplers, "channels": channels}]


def _continuous_xyzw(rotations: np.ndarray) -> np.ndarray:
    out = np.asarray(rotations, dtype=np.float32).copy()
    for joint in range(out.shape[1]):
        for frame in range(1, out.shape[0]):
            if float(np.dot(out[frame, joint], out[frame - 1, joint])) < 0.0:
                out[frame, joint] *= -1.0
    return out


def matrices_to_xyzw(matrices: np.ndarray) -> np.ndarray:
    values = np.asarray(matrices, dtype=np.float64)
    out = np.empty(values.shape[:-2] + (4,), dtype=np.float32)
    iterator = np.ndindex(values.shape[:-2])
    for index in iterator:
        out[index] = _matrix_to_xyzw(values[index])
    return out


def _matrix_to_xyzw(matrix: np.ndarray) -> list[float]:
    m = np.asarray(matrix, dtype=np.float64)
    trace = float(np.trace(m))
    if trace > 0:
        s = 0.5 / np.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (m[2, 1] - m[1, 2]) * s
        y = (m[0, 2] - m[2, 0]) * s
        z = (m[1, 0] - m[0, 1]) * s
    else:
        if m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
            s = 2.0 * np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
            w = (m[2, 1] - m[1, 2]) / s
            x = 0.25 * s
            y = (m[0, 1] + m[1, 0]) / s
            z = (m[0, 2] + m[2, 0]) / s
        elif m[1, 1] > m[2, 2]:
            s = 2.0 * np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
            w = (m[0, 2] - m[2, 0]) / s
            x = (m[0, 1] + m[1, 0]) / s
            y = 0.25 * s
            z = (m[1, 2] + m[2, 1]) / s
        else:
            s = 2.0 * np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
            w = (m[1, 0] - m[0, 1]) / s
            x = (m[0, 2] + m[2, 0]) / s
            y = (m[1, 2] + m[2, 1]) / s
            z = 0.25 * s
    quat = np.array((x, y, z, w), dtype=np.float64)
    quat /= max(float(np.linalg.norm(quat)), 1e-12)
    return quat.tolist()


def _vertex_normals(vertices: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    normals = np.zeros_like(vertices, dtype=np.float64)
    tris = vertices[triangles]
    face = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    for corner in range(3):
        np.add.at(normals, triangles[:, corner], face)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    return normals / np.where(lengths < 1e-8, 1.0, lengths)


def make_bind_skeleton(
    *,
    names: list[str],
    parents: np.ndarray,
    rest_world: np.ndarray,
    rest_local_rotation: np.ndarray,
    rest_local_translation: np.ndarray,
    inverse_bind: np.ndarray,
    vertices: np.ndarray,
    triangles: np.ndarray,
    uvs: np.ndarray,
    weights: np.ndarray,
    albedo: np.ndarray,
    normals: np.ndarray | None = None,
    influence_slots: int = 8,
) -> BindSkeleton:
    orig_parents = np.asarray(parents, dtype=np.int64)
    order = _topological_order([int(value) for value in orig_parents.tolist()])
    rest_world = np.asarray(rest_world, dtype=np.float64)[order]
    names, parents, rest_local_rotation, rest_local_translation, inverse_bind, weights, _anim = _match_loader_order(
        names,
        orig_parents,
        rest_local_rotation,
        rest_local_translation,
        inverse_bind,
        weights,
        None,
    )
    joints, skin_w, _trunc = _top_influences(weights, slots=influence_slots)
    return BindSkeleton(
        names=tuple(names),
        node_indices=tuple(range(len(names))),
        parents=tuple(int(value) for value in parents),
        rest_world=np.asarray(rest_world, dtype=np.float64),
        rest_local_rotation=np.asarray(rest_local_rotation, dtype=np.float64),
        rest_local_translation=np.asarray(rest_local_translation, dtype=np.float64),
        inverse_bind=np.asarray(inverse_bind, dtype=np.float64),
        vertices=np.asarray(vertices, dtype=np.float64),
        vertex_joints=joints.astype(np.int32),
        vertex_weights=skin_w.astype(np.float64),
        triangles=np.asarray(triangles, dtype=np.int32),
        uvs=np.asarray(uvs, dtype=np.float64),
        normals=None if normals is None else np.asarray(normals, dtype=np.float64),
        albedo=np.asarray(albedo),
    )


def inspect_glb_animation(path: Path) -> dict[str, Any]:
    from glb_skeleton import read_glb

    doc = read_glb(path)["json"]
    animations = doc.get("animations") or []
    skins = doc.get("skins") or []
    materials = doc.get("materials") or []
    nodes = doc.get("nodes") or []
    joint_names = []
    if skins:
        for index in skins[0].get("joints") or ():
            joint_names.append(str(nodes[int(index)].get("name") or f"node{index}"))
    channels = []
    if animations:
        channels = [item["target"]["path"] for item in animations[0].get("channels") or []]
    primitive = (((doc.get("meshes") or [{}])[0]).get("primitives") or [{}])[0]
    attrs = primitive.get("attributes") or {}
    return {
        "animationCount": len(animations),
        "jointCount": len(joint_names),
        "jointNames": joint_names,
        "channelPaths": channels,
        "rotationChannels": int(sum(1 for path_name in channels if path_name == "rotation")),
        "translationChannels": int(sum(1 for path_name in channels if path_name == "translation")),
        "materialCount": len(materials),
        "hasBaseColor": bool(
            ((materials[0].get("pbrMetallicRoughness") or {}).get("baseColorTexture") if materials else None)
        ),
        "jointSets": int(sum(1 for key in attrs if key.startswith("JOINTS_"))),
        "hasScaleChannel": any(path_name == "scale" for path_name in channels),
    }


def _skeleton_in_name_order(skeleton: BindSkeleton, names: list[str]) -> BindSkeleton:
    index = {name: i for i, name in enumerate(skeleton.names)}
    order = [index[name] for name in names]
    inv = np.empty(len(order), dtype=np.int32)
    for new, old in enumerate(order):
        inv[old] = new
    parents = []
    for old in order:
        parent = int(skeleton.parents[old])
        parents.append(-1 if parent < 0 else int(inv[parent]))
    vertex_joints = None if skeleton.vertex_joints is None else inv[np.asarray(skeleton.vertex_joints)]
    return BindSkeleton(
        names=tuple(names),
        node_indices=tuple(skeleton.node_indices[old] for old in order),
        parents=tuple(parents),
        rest_world=np.asarray(skeleton.rest_world)[order],
        rest_local_rotation=np.asarray(skeleton.rest_local_rotation)[order],
        rest_local_translation=np.asarray(skeleton.rest_local_translation)[order],
        inverse_bind=None if skeleton.inverse_bind is None else np.asarray(skeleton.inverse_bind)[order],
        vertices=skeleton.vertices,
        vertex_joints=vertex_joints,
        vertex_weights=skeleton.vertex_weights,
        triangles=skeleton.triangles,
        uvs=skeleton.uvs,
        normals=skeleton.normals,
        albedo=skeleton.albedo,
    )


def reload_and_compare(path: Path, working: BindSkeleton, joint_world: np.ndarray | None = None) -> dict[str, float]:
    loaded = load_bind_skeleton(path)
    if set(loaded.names) != set(working.names) or len(loaded.names) != len(working.names):
        raise ValueError("reload dropped or reordered joints")
    if list(loaded.names) != list(working.names):
        loaded = _skeleton_in_name_order(loaded, list(working.names))
    if loaded.vertex_weights is None or working.vertex_weights is None:
        raise ValueError("reload lost skin weights")
    if loaded.vertices is None or working.vertices is None:
        raise ValueError("reload lost vertices")
    own_loaded = own_bind_identity_gate(loaded)
    own_working = own_bind_identity_gate(working)
    if own_loaded["loadedOwnBindIdentityMax"] > own_loaded["bindIdentityGate"]:
        raise ValueError(
            "reloaded GLB skinned at its own bind does not recover vertices: "
            f"max {own_loaded['loadedOwnBindIdentityMax']} > {own_loaded['bindIdentityGate']} "
            "(1e-5 * mesh bbox diagonal). Research NPZ is not a substitute."
        )
    if own_working["loadedOwnBindIdentityMax"] > own_working["bindIdentityGate"]:
        raise ValueError(
            "working bind skinned at its own rest does not recover vertices: "
            f"max {own_working['loadedOwnBindIdentityMax']} > {own_working['bindIdentityGate']}"
        )
    vertex_err = float(np.linalg.norm(np.asarray(loaded.vertices) - np.asarray(working.vertices), axis=1).max())
    gate = own_loaded["bindIdentityGate"]
    payload = {
        "loadedOwnBindIdentityMax": own_loaded["loadedOwnBindIdentityMax"],
        "workingOwnBindIdentityMax": own_working["loadedOwnBindIdentityMax"],
        "vertexExportMax": vertex_err,
        "meshBBoxDiagonal": own_loaded["meshBBoxDiagonal"],
        "bindIdentityGate": gate,
        "vertexCount": float(len(loaded.vertices)),
        "ok": bool(
            own_loaded["loadedOwnBindIdentityMax"] <= gate
            and own_working["loadedOwnBindIdentityMax"] <= gate
            and vertex_err <= gate
        ),
    }
    if joint_world is not None:
        # Diagnostic only. Never the export gate: it can hide a bad rest pose.
        payload["workingMatrixPoseDelta"] = float(
            np.linalg.norm(
                skin_vertices(working, joint_world) - skin_vertices(loaded, joint_world),
                axis=1,
            ).max()
        )
    return payload
