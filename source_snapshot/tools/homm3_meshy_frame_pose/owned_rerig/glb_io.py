"""Minimal GLB mesh/skin reader-writer used by owned re-rig (no Blender)."""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

COMPONENT = {
    5120: np.int8,
    5121: np.uint8,
    5122: np.int16,
    5123: np.uint16,
    5125: np.uint32,
    5126: np.float32,
}
COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


@dataclass
class GlbMesh:
    positions: np.ndarray
    indices: np.ndarray
    joints: np.ndarray | None = None
    weights: np.ndarray | None = None
    node_names: list[str] = field(default_factory=list)
    skin_joints: list[int] = field(default_factory=list)
    inverse_bind: np.ndarray | None = None
    extras: dict[str, Any] = field(default_factory=dict)


def read_glb(path: Path) -> dict[str, Any]:
    data = Path(path).read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError(f"not a GLB: {path}")
    json_doc = None
    bin_chunk = b""
    offset = 12
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        start = offset + 8
        end = start + chunk_length
        if chunk_type == b"JSON":
            json_doc = json.loads(data[start:end].decode("utf-8").rstrip(" \t\r\n\x00"))
        elif chunk_type == b"BIN\x00":
            bin_chunk = data[start:end]
        offset = end
    if json_doc is None:
        raise ValueError(f"GLB has no JSON chunk: {path}")
    return {"json": json_doc, "bin": bin_chunk, "sha256": hashlib.sha256(data).hexdigest()}


def write_glb(path: Path, doc: dict[str, Any], bin_blob: bytes) -> None:
    json_bytes = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    bin_bytes = bytes(bin_blob) + b"\x00" * ((4 - len(bin_blob) % 4) % 4)
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    out = bytearray()
    out += b"glTF"
    out += struct.pack("<II", 2, total)
    out += struct.pack("<I4s", len(json_bytes), b"JSON")
    out += json_bytes
    out += struct.pack("<I4s", len(bin_bytes), b"BIN\x00")
    out += bin_bytes
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(bytes(out))


def _accessor(doc: dict[str, Any], bin_chunk: bytes, index: int) -> np.ndarray:
    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    dtype = np.dtype(COMPONENT[acc["componentType"]])
    ncomp = COMPONENTS[acc["type"]]
    count = int(acc["count"])
    start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
    stride = int(view.get("byteStride") or dtype.itemsize * ncomp)
    if stride == dtype.itemsize * ncomp:
        raw = np.frombuffer(bin_chunk[start : start + count * ncomp * dtype.itemsize], dtype=dtype)
        return raw.reshape(count, ncomp) if ncomp > 1 else raw
    out = np.zeros((count, ncomp), dtype=dtype)
    for i in range(count):
        off = start + i * stride
        out[i] = np.frombuffer(bin_chunk[off : off + ncomp * dtype.itemsize], dtype=dtype)
    return out if ncomp > 1 else out.reshape(count)


def load_mesh(path: Path) -> GlbMesh:
    packed = read_glb(path)
    doc = packed["json"]
    blob = packed["bin"]
    nodes = doc.get("nodes") or []
    meshes = doc.get("meshes") or []
    if not meshes:
        raise ValueError(f"no meshes in {path}")
    prim = meshes[0]["primitives"][0]
    attrs = prim["attributes"]
    positions = _accessor(doc, blob, attrs["POSITION"]).astype(np.float64)
    if "indices" in prim:
        indices = _accessor(doc, blob, prim["indices"]).astype(np.int32).reshape(-1)
    else:
        indices = np.arange(len(positions), dtype=np.int32)
    joints = weights = None
    if "JOINTS_0" in attrs and "WEIGHTS_0" in attrs:
        joints = _accessor(doc, blob, attrs["JOINTS_0"]).astype(np.int32).reshape(-1, 4)
        weights = _accessor(doc, blob, attrs["WEIGHTS_0"]).astype(np.float64).reshape(-1, 4)
    skins = doc.get("skins") or []
    skin_joints: list[int] = []
    ibm = None
    if skins:
        skin_joints = [int(i) for i in skins[0].get("joints") or []]
        if "inverseBindMatrices" in skins[0]:
            ibm = _accessor(doc, blob, skins[0]["inverseBindMatrices"]).astype(np.float64).reshape(-1, 4, 4)
    names = [str(n.get("name") or f"node{i}") for i, n in enumerate(nodes)]
    return GlbMesh(
        positions=positions,
        indices=indices,
        joints=joints,
        weights=weights,
        node_names=names,
        skin_joints=skin_joints,
        inverse_bind=ibm,
        extras={"source": str(Path(path).resolve()).replace("\\", "/"), "nodeCount": len(nodes)},
    )


load_mesh = load_mesh


def _pad4(buf: bytearray) -> None:
    buf.extend(b"\x00" * ((4 - len(buf) % 4) % 4))


def _append_array(
    bin_blob: bytearray,
    views: list[dict],
    accessors: list[dict],
    data: np.ndarray,
    typ: str,
    component: int,
) -> int:
    raw = np.ascontiguousarray(data).tobytes()
    offset = len(bin_blob)
    bin_blob.extend(raw)
    _pad4(bin_blob)
    views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw)})
    acc: dict[str, Any] = {
        "bufferView": len(views) - 1,
        "componentType": component,
        "count": int(data.shape[0]),
        "type": typ,
    }
    if component == 5126:
        flat = np.ascontiguousarray(data).reshape(data.shape[0], -1)
        acc["max"] = [float(v) for v in flat.max(axis=0)]
        acc["min"] = [float(v) for v in flat.min(axis=0)]
    accessors.append(acc)
    return len(accessors) - 1


def load_render_surface(path: Path) -> dict[str, Any]:
    """Positions, indices, UVs, normals and the base-colour texture of a bind GLB.

    A preview that shades from the DEF plate instead of the mesh's own texture is not showing the
    asset: the plate is a 39x77 px sprite, so one flat colour per face is all it can supply.  This
    reads what the mesh actually carries so the render can be textured.
    """
    packed = read_glb(path)
    doc = packed["json"]
    blob = packed["bin"]
    meshes = doc.get("meshes") or []
    if not meshes:
        raise ValueError(f"no meshes in {path}")
    prim = meshes[0]["primitives"][0]
    attrs = prim["attributes"]
    positions = _accessor(doc, blob, attrs["POSITION"]).astype(np.float64)
    indices = _accessor(doc, blob, prim["indices"]).astype(np.int64).reshape(-1)
    if "TEXCOORD_0" not in attrs:
        raise ValueError(f"{path}: the mesh has no UVs, so its texture cannot be applied")
    uvs = _accessor(doc, blob, attrs["TEXCOORD_0"]).astype(np.float64).reshape(-1, 2)
    normals = (
        _accessor(doc, blob, attrs["NORMAL"]).astype(np.float64).reshape(-1, 3)
        if "NORMAL" in attrs
        else None
    )
    texture = None
    material = (doc.get("materials") or [{}])[0]
    texture_index = ((material.get("pbrMetallicRoughness") or {}).get("baseColorTexture") or {}).get(
        "index"
    )
    if texture_index is not None:
        texture = _decode_image(doc, blob, int((doc["textures"][int(texture_index)])["source"]))
    if texture is None:
        raise ValueError(
            f"{path}: the mesh has no base-colour image, so a textured preview cannot be drawn"
        )
    return {
        "positions": positions,
        "indices": indices,
        "uvs": uvs,
        "normals": normals,
        "baseColor": texture,
        "baseColorSize": (int(texture.shape[1]), int(texture.shape[0])),
        "sourceSha256": packed["sha256"],
    }


def _decode_image(doc: dict[str, Any], blob: bytes, image_index: int) -> np.ndarray | None:
    """Decode an embedded glTF image to an ``(H, W, 3)`` uint8 array."""
    import io

    import numpy as np
    from PIL import Image

    images = doc.get("images") or []
    if not 0 <= image_index < len(images):
        return None
    image = images[image_index]
    if "bufferView" not in image:
        return None
    view = doc["bufferViews"][int(image["bufferView"])]
    start = int(view.get("byteOffset", 0))
    raw = blob[start : start + int(view["byteLength"])]
    decoded = Image.open(io.BytesIO(raw))
    if decoded.mode not in ("RGB", "RGBA"):
        decoded = decoded.convert("RGB")
    return np.asarray(decoded, dtype=np.uint8)[:, :, :3]


def write_skinned_mesh(
    path: Path,
    *,
    positions: np.ndarray,
    indices: np.ndarray,
    bone_names: list[str],
    parents: list[int | None],
    heads: np.ndarray,
    joints: np.ndarray,
    weights: np.ndarray,
    extras: dict[str, Any] | None = None,
    source_glb: Path | None = None,
    uvs: np.ndarray | None = None,
    normals: np.ndarray | None = None,
) -> None:
    if len(bone_names) != len(parents) or len(bone_names) != len(heads):
        raise ValueError("bone_names, parents, and heads must be the same length")
    # A repaired surface may duplicate seam/contact vertices and rotate its normals.
    # Explicit attributes are then authoritative; the source still owns the materials.
    for name, values, width in (("uvs", uvs, 2), ("normals", normals, 3)):
        if values is not None:
            values = np.asarray(values)
            if values.shape != (len(positions), width) or not np.isfinite(values).all():
                raise ValueError(f"{name} must have finite rows matching positions")
    bin_blob = bytearray()
    views: list[dict] = []
    accessors: list[dict] = []
    pos_i = _append_array(bin_blob, views, accessors, positions.astype(np.float32), "VEC3", 5126)
    idx_i = _append_array(bin_blob, views, accessors, indices.astype(np.uint32).reshape(-1), "SCALAR", 5125)
    jnt_i = _append_array(bin_blob, views, accessors, joints.astype(np.uint8), "VEC4", 5121)
    wgt_i = _append_array(bin_blob, views, accessors, weights.astype(np.float32), "VEC4", 5126)

    children: dict[int, list[int]] = {i: [] for i in range(len(bone_names))}
    for i, parent in enumerate(parents):
        if parent is None:
            continue
        if parent < 0 or parent >= len(bone_names) or parent == i:
            raise ValueError(f"invalid parent for {bone_names[i]}: {parent}")
        children[parent].append(i)

    world = heads.astype(np.float64)
    ibm = np.zeros((len(bone_names), 4, 4), dtype=np.float32)
    nodes: list[dict[str, Any]] = []
    for i, name in enumerate(bone_names):
        parent = parents[i]
        local = world[i] if parent is None else world[i] - world[parent]
        node: dict[str, Any] = {
            "name": name,
            "translation": [float(local[0]), float(local[1]), float(local[2])],
        }
        if children[i]:
            node["children"] = children[i]
        nodes.append(node)
        matrix = np.eye(4, dtype=np.float32)
        matrix[:3, 3] = world[i]
        ibm[i] = np.linalg.inv(matrix)

    # glTF MAT4 is column-major. The cascade loader transposes after reshape.
    ibm_colmajor = np.transpose(ibm, (0, 2, 1)).astype(np.float32)
    ibm_i = _append_array(bin_blob, views, accessors, ibm_colmajor.reshape(len(bone_names), 16), "MAT4", 5126)
    attributes: dict[str, int] = {"POSITION": pos_i, "JOINTS_0": jnt_i, "WEIGHTS_0": wgt_i}
    images_out: list[dict[str, Any]] = []
    textures_out: list[dict[str, Any]] = []
    samplers_out: list[dict[str, Any]] = []
    materials_out: list[dict[str, Any]] = []
    src_samplers: list[Any] = []
    if source_glb is not None:
        packed = read_glb(source_glb)
        src_doc = packed["json"]
        src_blob = packed["bin"]
        src_samplers = list(src_doc.get("samplers") or [])
        prim = ((src_doc.get("meshes") or [{}])[0].get("primitives") or [{}])[0]
        attrs = prim.get("attributes") or {}
        if uvs is not None or "TEXCOORD_0" in attrs:
            uvs = (np.asarray(uvs, dtype=np.float32) if uvs is not None else
                   _accessor(src_doc, src_blob, attrs["TEXCOORD_0"]).astype(np.float32))
            if uvs.ndim == 1:
                uvs = uvs.reshape(-1, 2)
            if len(uvs) != len(positions):
                raise ValueError(
                    f"source UV count {len(uvs)} does not match positions {len(positions)}"
                )
            attributes["TEXCOORD_0"] = _append_array(bin_blob, views, accessors, uvs, "VEC2", 5126)
        # The authored normals travel with the mesh.  Without them a consumer must invent normals,
        # and on a mesh made of hundreds of disconnected patches there is nothing to average
        # across a patch boundary, so the surface reads as faceted rather than shaded.
        if normals is not None or "NORMAL" in attrs:
            normals = (np.asarray(normals, dtype=np.float32) if normals is not None else
                       _accessor(src_doc, src_blob, attrs["NORMAL"]).astype(np.float32))
            if normals.ndim == 1:
                normals = normals.reshape(-1, 3)
            if len(normals) != len(positions):
                raise ValueError(
                    f"source normal count {len(normals)} does not match positions {len(positions)}"
                )
            attributes["NORMAL"] = _append_array(
                bin_blob, views, accessors, normals, "VEC3", 5126
            )
        image_index_map: dict[int, int] = {}
        for i, image in enumerate(src_doc.get("images") or []):
            if "bufferView" not in image:
                continue
            view = src_doc["bufferViews"][int(image["bufferView"])]
            start = int(view.get("byteOffset", 0))
            raw = src_blob[start : start + int(view["byteLength"])]
            offset = len(bin_blob)
            bin_blob.extend(raw)
            _pad4(bin_blob)
            views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw)})
            image_index_map[i] = len(images_out)
            images_out.append(
                {
                    "mimeType": image.get("mimeType") or "image/png",
                    "bufferView": len(views) - 1,
                    **({"name": image["name"]} if image.get("name") else {}),
                }
            )
        for tex in src_doc.get("textures") or []:
            src_img = tex.get("source")
            if src_img not in image_index_map:
                continue
            out_tex: dict[str, Any] = {"source": image_index_map[int(src_img)]}
            # Carry the sampler across.  A conforming loader defaults to linear filtering, but the
            # authored choice is part of the material and dropping it invites a nearest-filtered
            # import that reads as blocky texture.
            sampler = tex.get("sampler")
            if sampler is not None and 0 <= int(sampler) < len(src_samplers):
                out_tex["sampler"] = int(sampler)
            textures_out.append(out_tex)
        for sampler in src_samplers:
            if isinstance(sampler, dict):
                samplers_out.append(dict(sampler))
        if textures_out and src_doc.get("materials"):
            materials_out = list(src_doc["materials"])
    elif uvs is not None or normals is not None:
        for name, values, typ, width in (("TEXCOORD_0", uvs, "VEC2", 2),
                                         ("NORMAL", normals, "VEC3", 3)):
            if values is not None:
                values = np.asarray(values, dtype=np.float32)
                if values.shape != (len(positions), width):
                    raise ValueError(f"{name} shape must match positions")
                attributes[name] = _append_array(bin_blob, views, accessors, values, typ, 5126)
    mesh_node = len(nodes)
    nodes.append({"name": "OwnedMesh", "mesh": 0, "skin": 0})
    roots = [i for i, parent in enumerate(parents) if parent is None]
    primitive: dict[str, Any] = {"attributes": attributes, "indices": idx_i}
    if materials_out:
        primitive["material"] = 0
    doc: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "owned_rerig"},
        "scene": 0,
        "scenes": [{"nodes": roots + [mesh_node]}],
        "nodes": nodes,
        "meshes": [
            {
                "name": "OwnedMesh",
                "primitives": [primitive],
            }
        ],
        "skins": [
            {
                "name": "OwnedBind",
                "joints": list(range(len(bone_names))),
                "inverseBindMatrices": ibm_i,
                "skeleton": roots[0],
            }
        ],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(bin_blob)}],
    }
    if images_out:
        doc["images"] = images_out
    if textures_out:
        doc["textures"] = textures_out
    if samplers_out:
        doc["samplers"] = samplers_out
    if materials_out:
        doc["materials"] = materials_out
    if extras:
        doc["extras"] = extras
        nodes[-1]["extras"] = extras
    write_glb(path, doc, bytes(bin_blob))


def y_up_to_z_up(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float64)
    return np.column_stack((pts[:, 0], -pts[:, 2], pts[:, 1]))


def z_up_to_y_up(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float64)
    return np.column_stack((pts[:, 0], pts[:, 2], -pts[:, 1]))


def should_reorient_y_up(positions: np.ndarray) -> bool:
    extent = positions.max(axis=0) - positions.min(axis=0)
    return float(extent[1]) > float(extent[2]) * 1.05


def write_static_mesh_keep_pbr(
    src: Path,
    dest: Path,
    *,
    positions: np.ndarray,
    indices: np.ndarray,
    normals: np.ndarray | None = None,
    uvs: np.ndarray | None = None,
    extras: dict[str, Any] | None = None,
) -> None:
    """Write an unskinned mesh, copying NORMAL/UV/PBR images from src when present.

    ``normals`` and ``uvs`` replace what ``src`` carries.  A rebuilt surface needs that: a remesh or a
    retopology authors its own vertices, so the source's per-vertex attributes are the wrong length and
    cannot be copied onto them.  Omitting both keeps the copy-from-source behaviour unchanged.
    """
    vertices = np.asarray(positions, dtype=np.float64)
    packed = read_glb(src)
    doc = packed["json"]
    blob = packed["bin"]
    prim = ((doc.get("meshes") or [{}])[0].get("primitives") or [{}])[0]
    attrs = prim.get("attributes") or {}
    if normals is not None and len(normals) != len(vertices):
        raise ValueError(
            f"normals must name every vertex: got {len(normals)} for {len(vertices)} positions"
        )
    if uvs is not None and len(uvs) != len(vertices):
        raise ValueError(f"uvs must name every vertex: got {len(uvs)} for {len(vertices)} positions")
    bin_blob = bytearray()
    views: list[dict] = []
    accessors: list[dict] = []
    pos_i = _append_array(bin_blob, views, accessors, positions.astype(np.float32), "VEC3", 5126)
    idx_i = _append_array(bin_blob, views, accessors, indices.astype(np.uint32).reshape(-1), "SCALAR", 5125)
    attributes = {"POSITION": pos_i}
    if normals is not None:
        attributes["NORMAL"] = _append_array(
            bin_blob, views, accessors, np.asarray(normals, dtype=np.float32), "VEC3", 5126
        )
    elif "NORMAL" in attrs:
        authored = _accessor(doc, blob, attrs["NORMAL"]).astype(np.float64)
        if should_reorient_y_up(_accessor(doc, blob, attrs["POSITION"]).astype(np.float64)):
            authored = y_up_to_z_up(authored)
        attributes["NORMAL"] = _append_array(bin_blob, views, accessors, authored.astype(np.float32), "VEC3", 5126)
    if uvs is not None:
        supplied = np.asarray(uvs, dtype=np.float32)
        if supplied.ndim == 1:
            supplied = supplied.reshape(-1, 2)
        if supplied.shape[1] != 2:
            raise ValueError(f"uvs must be (N,2); got {supplied.shape}")
        attributes["TEXCOORD_0"] = _append_array(bin_blob, views, accessors, supplied, "VEC2", 5126)
    elif "TEXCOORD_0" in attrs:
        uvs_in = _accessor(doc, blob, attrs["TEXCOORD_0"]).astype(np.float32)
        if uvs_in.ndim == 1:
            uvs_in = uvs_in.reshape(-1, 2)
        attributes["TEXCOORD_0"] = _append_array(bin_blob, views, accessors, uvs_in, "VEC2", 5126)

    image_index_map: dict[int, int] = {}
    images_out: list[dict[str, Any]] = []
    for i, image in enumerate(doc.get("images") or []):
        if "bufferView" not in image:
            continue
        view = doc["bufferViews"][int(image["bufferView"])]
        start = int(view.get("byteOffset", 0))
        raw = blob[start : start + int(view["byteLength"])]
        offset = len(bin_blob)
        bin_blob.extend(raw)
        _pad4(bin_blob)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw)})
        image_index_map[i] = len(images_out)
        images_out.append(
            {
                "mimeType": image.get("mimeType") or "image/png",
                "bufferView": len(views) - 1,
                **({"name": image["name"]} if image.get("name") else {}),
            }
        )
    textures_out = []
    for tex in doc.get("textures") or []:
        src_img = tex.get("source")
        if src_img not in image_index_map:
            continue
        textures_out.append({"source": image_index_map[int(src_img)]})
    materials_out = []
    if textures_out and doc.get("materials"):
        materials_out = doc["materials"]
    primitive: dict[str, Any] = {"attributes": attributes, "indices": idx_i}
    if materials_out:
        primitive["material"] = 0
    out_doc: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "owned_rerig_strip"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Mesh", "mesh": 0}],
        "meshes": [{"name": "Mesh", "primitives": [primitive]}],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(bin_blob)}],
    }
    if images_out:
        out_doc["images"] = images_out
    if textures_out:
        out_doc["textures"] = textures_out
    if materials_out:
        out_doc["materials"] = materials_out
    if extras:
        out_doc["extras"] = extras
    write_glb(dest, out_doc, bytes(bin_blob))


def write_unskinned_mesh(
    path: Path,
    positions: np.ndarray,
    indices: np.ndarray,
    extras: dict[str, Any] | None = None,
) -> None:
    bin_blob = bytearray()
    views: list[dict] = []
    accessors: list[dict] = []
    pos_i = _append_array(bin_blob, views, accessors, positions.astype(np.float32), "VEC3", 5126)
    idx_i = _append_array(bin_blob, views, accessors, indices.astype(np.uint32).reshape(-1), "SCALAR", 5125)
    doc: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "owned_rerig_strip"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Mesh", "mesh": 0}],
        "meshes": [{"name": "Mesh", "primitives": [{"attributes": {"POSITION": pos_i}, "indices": idx_i}]}],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(bin_blob)}],
    }
    if extras:
        doc["extras"] = extras
    write_glb(path, doc, bytes(bin_blob))


load_mesh = load_mesh
write_skinned_mesh = write_skinned_mesh
write_unskinned_mesh = write_unskinned_mesh
