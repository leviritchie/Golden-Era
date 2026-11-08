"""Meshy smart-rig preparation for the V2 CUDA renderer."""
from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .contracts import PreparedRig, fingerprint_paths


@dataclass(frozen=True)
class GpuPrimitive:
    node: int
    skin: int | None
    positions: Any
    indices: Any
    joints: Any | None
    weights: Any | None
    uv: Any | None
    texture: Any | None
    color_factor: Any
    vertex_color: Any
    material_name: str
    bone_owner: Any | None


def _read_rigidization(path: str | Path | None, *, expected_mesh: Path | None = None) -> Mapping[str, Any] | None:
    if path is None:
        return None
    report = Path(path).resolve()
    if not report.is_file():
        raise FileNotFoundError(f"Meshy rigidization report is missing: {report}")
    value = json.loads(report.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping) or not value.get("ok", True):
        raise ValueError(f"invalid Meshy rigidization report: {report}")
    if expected_mesh is not None:
        referenced = []
        for key in ("source", "output"):
            raw = value.get(key)
            if raw:
                candidate = Path(str(raw))
                if not candidate.is_absolute():
                    candidate = report.parent / candidate
                referenced.append(candidate.resolve())
        if referenced and expected_mesh.resolve() not in referenced:
            raise ValueError(
                "Meshy rigidization report does not describe the selected mesh: "
                f"mesh={expected_mesh.resolve()} report={report} references={referenced}"
            )
    return value


def _image_bytes(doc: Mapping[str, Any], blob: bytes, image_index: int) -> bytes | None:
    image = doc.get("images", [])[int(image_index)]
    if "bufferView" not in image:
        return None
    view = doc["bufferViews"][int(image["bufferView"])]
    start = int(view.get("byteOffset", 0))
    end = start + int(view["byteLength"])
    if end > len(blob):
        raise ValueError("embedded glTF image exceeds BIN chunk")
    return blob[start:end]


def _base_color(doc: Mapping[str, Any], blob: bytes, material_index: int | None) -> tuple[np.ndarray | None, tuple[float, float, float, float]]:
    if material_index is None:
        return None, (0.72, 0.72, 0.72, 1.0)
    materials = doc.get("materials", [])
    if int(material_index) >= len(materials):
        return None, (0.72, 0.72, 0.72, 1.0)
    material = materials[int(material_index)]
    pbr = material.get("pbrMetallicRoughness", {})
    factor = tuple(float(v) for v in pbr.get("baseColorFactor", (0.72, 0.72, 0.72, 1.0)))
    texture = pbr.get("baseColorTexture")
    if not isinstance(texture, Mapping):
        return None, factor
    textures = doc.get("textures", [])
    images = doc.get("images", [])
    tex_index = int(texture.get("index", -1))
    if tex_index < 0 or tex_index >= len(textures):
        return None, factor
    source = textures[tex_index].get("source")
    if source is None or int(source) >= len(images):
        return None, factor
    raw = _image_bytes(doc, blob, int(source))
    if raw is None:
        return None, factor
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as image:
        return np.asarray(image.convert("RGBA"), dtype=np.float32) / 255.0, factor


def _sample_vertex_colors(texture: np.ndarray | None, factor: tuple[float, float, float, float], uv: np.ndarray | None, count: int) -> np.ndarray:
    if texture is None or uv is None or len(uv) != count:
        return np.tile(np.asarray(factor, dtype=np.float32), (count, 1))
    height, width = texture.shape[:2]
    coords = np.asarray(uv, dtype=np.float64)
    x = np.mod(np.floor(coords[:, 0] * width).astype(np.int64), max(width, 1))
    y = np.mod(np.floor((1.0 - coords[:, 1]) * height).astype(np.int64), max(height, 1))
    sampled = texture[y, x]
    return np.asarray(sampled * np.asarray(factor, dtype=np.float32), dtype=np.float32)


def _node_depths(parents: tuple[int | None, ...]) -> tuple[int, ...]:
    result = []
    for index in range(len(parents)):
        depth = 0
        seen: set[int] = set()
        parent = parents[index]
        while parent is not None:
            if int(parent) in seen:
                raise ValueError("GLB node hierarchy contains a cycle")
            seen.add(int(parent))
            depth += 1
            parent = parents[int(parent)]
        result.append(depth)
    return tuple(result)


def prepare_rig(
    src_glb: str | Path,
    *,
    device: str = "cuda",
    mesh_scale: float = 1.0,
    rigidization_report: str | Path | None = None,
) -> PreparedRig:
    """Decode the Meshy GLB once and materialize immutable CUDA geometry."""
    import torch

    if not torch.cuda.is_available() or not str(device).startswith("cuda"):
        raise RuntimeError("V2 requires a CUDA device; CPU renderer fallback is disabled")
    from roc_geometric_proxy import _read_glb, _read_accessor, load_asset

    path = Path(src_glb).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"V2 mesh is missing: {path}")
    asset = load_asset(path)
    doc, blob = _read_glb(path)
    parents = tuple(node.parent for node in asset.nodes)
    depths = _node_depths(parents)
    rigidization = _read_rigidization(rigidization_report, expected_mesh=path)
    primitive_tensors: list[GpuPrimitive] = []
    primitive_cursor = 0
    for node in asset.nodes:
        if node.mesh is None:
            continue
        mesh = doc.get("meshes", [])[int(node.mesh)]
        for raw_primitive in mesh.get("primitives", []):
            if primitive_cursor >= len(asset.primitives):
                raise ValueError("GLB primitive ordering differs between decoders")
            source = asset.primitives[primitive_cursor]
            primitive_cursor += 1
            attributes = raw_primitive.get("attributes", {})
            uv = None
            if "TEXCOORD_0" in attributes:
                uv = np.asarray(_read_accessor(doc, blob, int(attributes["TEXCOORD_0"])), dtype=np.float32).reshape(-1, 2)
            color_texture, color_factor = _base_color(doc, blob, raw_primitive.get("material"))
            colors = _sample_vertex_colors(color_texture, color_factor, uv, len(source.positions))
            if source.indices is None:
                indices = np.arange((len(source.positions) // 3) * 3, dtype=np.int64).reshape(-1, 3)
            else:
                indices = np.asarray(source.indices, dtype=np.int64).reshape(-1, 3)
            # Keep the source geometry in the GLB coordinate system.  V2
            # applies mesh_scale once, after LBS, so skeleton translations,
            # inverse-bind matrices, registration, and Blender export all
            # observe the same global scale.
            positions = np.asarray(source.positions, dtype=np.float32)
            joints = None if source.joints is None else np.asarray(source.joints, dtype=np.int64)
            weights = None if source.weights is None else np.asarray(source.weights, dtype=np.float32)
            owner = None if joints is None or weights is None else np.take_along_axis(joints, np.argmax(weights, axis=1, keepdims=True), axis=1).reshape(-1)
            primitive_tensors.append(
                GpuPrimitive(
                    node=int(source.node),
                    skin=None if source.skin is None else int(source.skin),
                    positions=torch.as_tensor(np.c_[positions, np.ones(len(positions), dtype=np.float32)], device=device),
                    indices=torch.as_tensor(indices, dtype=torch.int32, device=device),
                    joints=None if joints is None else torch.as_tensor(joints, dtype=torch.long, device=device),
                    weights=None if weights is None else torch.as_tensor(weights, dtype=torch.float32, device=device),
                    uv=None if uv is None else torch.as_tensor(uv, dtype=torch.float32, device=device),
                    texture=None if color_texture is None else torch.as_tensor(color_texture, dtype=torch.float32, device=device),
                    color_factor=torch.as_tensor(color_factor[:3], dtype=torch.float32, device=device),
                    vertex_color=torch.as_tensor(colors[:, :3], dtype=torch.float32, device=device),
                    material_name=str(raw_primitive.get("material", "default")),
                    bone_owner=None if owner is None else torch.as_tensor(owner, dtype=torch.long, device=device),
                )
            )
    if primitive_cursor != len(asset.primitives):
        raise ValueError("GLB primitive ordering left unprepared primitives")
    points = np.concatenate([primitive.positions[:, :3].detach().cpu().numpy() for primitive in primitive_tensors], axis=0) if primitive_tensors else np.zeros((0, 3), dtype=np.float32)
    if len(points) == 0:
        raise ValueError(f"Mesh has no renderable vertices: {path}")
    pivot = torch.as_tensor(points.mean(axis=0), dtype=torch.float32, device=device)
    skeleton_indices = tuple(sorted({
        int(joint)
        for skin in asset.skins
        for joint in skin.joints
    }))
    fingerprint = fingerprint_paths([path, *([Path(rigidization_report)] if rigidization_report else [])], extra=f"mesh_scale={mesh_scale}")
    return PreparedRig(
        path=path,
        asset=asset,
        mesh_scale=float(mesh_scale),
        node_names=tuple(node.name for node in asset.nodes),
        parents=parents,
        node_depths=depths,
        pivot=pivot,
        primitives=tuple(primitive_tensors),
        rigidization=rigidization,
        fingerprint=fingerprint,
        device=str(device),
        semantic_surface_descriptors={
            "schemaVersion": 1,
            "primitiveCount": len(primitive_tensors),
            "texturedPrimitiveCount": sum(primitive.texture is not None for primitive in primitive_tensors),
            "materials": tuple(sorted({primitive.material_name for primitive in primitive_tensors})),
            "viewConditioned": False,
            "source": "Meshy GLB materials, UVs, and dominant skin owners",
        },
        skeleton_indices=skeleton_indices,
    )
