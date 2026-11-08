"""Blender-free geometric silhouette proxy for skinned GLB candidates.

This module deliberately implements only the cheap geometric lane: vertices are
skinned, projected orthographically, and splatted into a low-resolution point
mask.  It is a search proxy, not a replacement for Blender's triangle renderer.
"""
from __future__ import annotations

import functools
import base64
from io import BytesIO
import json
import math
import struct
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


COMPONENTS = {5120: (np.int8, 1), 5121: (np.uint8, 1), 5122: (np.int16, 2),
              5123: (np.uint16, 2), 5125: (np.uint32, 4), 5126: (np.float32, 4)}
TYPE_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
              "MAT2": 4, "MAT3": 9, "MAT4": 16}


@dataclass(frozen=True)
class Node:
    index: int
    name: str
    parent: int | None
    children: tuple[int, ...]
    translation: np.ndarray
    rotation: np.ndarray  # glTF order xyzw
    scale: np.ndarray
    mesh: int | None
    skin: int | None


@dataclass(frozen=True)
class Primitive:
    mesh: int
    node: int
    skin: int | None
    positions: np.ndarray
    joints: np.ndarray | None
    weights: np.ndarray | None
    indices: np.ndarray | None
    texcoords: np.ndarray | None = None
    material: int | None = None


@dataclass(frozen=True)
class Skin:
    index: int
    joints: tuple[int, ...]
    inverse_bind: np.ndarray


@dataclass(frozen=True)
class Material:
    """The material data needed for a Blender-free unlit RGB preview."""

    index: int
    base_color_factor: np.ndarray
    base_color_texture: int | None
    alpha_mode: str
    alpha_cutoff: float


def gltf_uv_to_grid_sample(uv):
    """Map glTF UV to ``grid_sample`` coordinates.

    glTF 2.0 places (0, 0) at the upper-left of the image, with V increasing
    downward. That matches a PIL/numpy texture tensor whose first row is the
    top of the PNG. ``grid_sample`` uses y=-1 for that first row. The older
    OpenGL ``1 - 2v`` mapping painted the albedo upside-down on the mesh.
    """
    import torch

    return torch.stack((uv[..., 0] * 2.0 - 1.0, uv[..., 1] * 2.0 - 1.0), dim=-1)


@dataclass(frozen=True)
class ProxyAsset:
    path: Path
    nodes: tuple[Node, ...]
    skins: tuple[Skin, ...]
    primitives: tuple[Primitive, ...]
    scenes: tuple[int, ...]
    materials: tuple[Material, ...] = ()
    texture_images: tuple[np.ndarray | None, ...] = ()


# The GLB is immutable during a search wave. Keep decoded CPU assets in the
# existing lru cache, and keep only a small LRU of static GPU tensors so a
# full-creature batch does not accumulate every unit's mesh in VRAM.
_GPU_ASSET_CACHE: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
_SAMPLE_INDEX_CACHE: OrderedDict[tuple[str, int, int | None], tuple[np.ndarray, ...]] = OrderedDict()
_GPU_ASSET_CACHE_DEFAULT_LIMIT = 2
_SAMPLE_INDEX_CACHE_LIMIT = 64


def _read_glb(path: Path) -> tuple[dict, bytes]:
    data = Path(path).read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError(f"not a GLB file: {path}")
    version, length = struct.unpack_from("<II", data, 4)
    if version != 2 or length > len(data):
        raise ValueError(f"unsupported or truncated GLB header: {path}")
    offset, doc, blob = 12, None, b""
    while offset + 8 <= length:
        size, kind = struct.unpack_from("<I4s", data, offset)
        start, end = offset + 8, offset + 8 + size
        if end > length:
            raise ValueError(f"truncated GLB chunk: {path}")
        if kind == b"JSON":
            doc = json.loads(data[start:end].decode("utf-8").rstrip(" \t\r\n\x00"))
        elif kind == b"BIN\x00":
            blob = data[start:end]
        offset = end
    if doc is None:
        raise ValueError(f"GLB has no JSON chunk: {path}")
    return doc, blob


def _read_accessor(doc: dict, blob: bytes, index: int) -> np.ndarray:
    """Decode a glTF accessor, including accessor offsets, stride, and sparse data."""
    acc = doc["accessors"][index]
    dtype, component_size = COMPONENTS[acc["componentType"]]
    width = TYPE_WIDTH[acc["type"]]
    count = int(acc["count"])
    if "bufferView" in acc:
        view = doc["bufferViews"][acc["bufferView"]]
        stride = int(view.get("byteStride", width * component_size))
        base = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
        raw = np.empty((count, width), dtype=dtype)
        item_bytes = width * component_size
        if stride < item_bytes:
            raise ValueError(f"accessor {index} has byteStride smaller than element")
        for row in range(count):
            start = base + row * stride
            end = start + item_bytes
            if end > len(blob):
                raise ValueError(f"accessor {index} exceeds BIN chunk")
            raw[row] = np.frombuffer(blob[start:end], dtype=dtype, count=width)
    else:
        raw = np.zeros((count, width), dtype=dtype)
    if acc.get("normalized"):
        if np.issubdtype(raw.dtype, np.signedinteger):
            denom = max(abs(np.iinfo(raw.dtype).min), np.iinfo(raw.dtype).max)
            raw = np.maximum(raw.astype(np.float32) / denom, -1.0)
        elif np.issubdtype(raw.dtype, np.unsignedinteger):
            raw = raw.astype(np.float32) / np.iinfo(raw.dtype).max
    else:
        raw = raw.copy()
    sparse = acc.get("sparse")
    if sparse:
        scount = int(sparse["count"])
        idx_info = sparse["indices"]
        idx_dtype, _ = COMPONENTS[idx_info["componentType"]]
        idx_view = doc["bufferViews"][idx_info["bufferView"]]
        idx_start = int(idx_view.get("byteOffset", 0)) + int(idx_info.get("byteOffset", 0))
        indices = np.frombuffer(blob, dtype=idx_dtype, count=scount, offset=idx_start)
        val_info = sparse["values"]
        val_view = doc["bufferViews"][val_info["bufferView"]]
        val_start = int(val_view.get("byteOffset", 0)) + int(val_info.get("byteOffset", 0))
        values = np.frombuffer(blob, dtype=dtype, count=scount * width, offset=val_start).reshape(scount, width)
        raw[indices.astype(np.int64)] = values
    return raw.reshape((count,) if width == 1 else (count, width))


def _decode_gltf_image(path: Path, doc: dict, blob: bytes, image_index: int) -> np.ndarray:
    """Decode one glTF image into immutable RGBA8 CPU data.

    The GPU renderer uploads this once per mesh.  Keeping decoding here makes
    the material contract explicit and prevents candidate evaluation from
    reopening image files or touching the filesystem.
    """
    image = doc.get("images", [])[int(image_index)]
    payload: bytes
    if "bufferView" in image:
        view = doc["bufferViews"][int(image["bufferView"])]
        start = int(view.get("byteOffset", 0))
        end = start + int(view["byteLength"])
        if start < 0 or end > len(blob):
            raise ValueError(f"image {image_index} bufferView exceeds GLB BIN chunk: {path}")
        payload = blob[start:end]
    elif str(image.get("uri", "")).startswith("data:"):
        uri = str(image["uri"])
        try:
            payload = base64.b64decode(uri.split(",", 1)[1], validate=True)
        except (IndexError, ValueError) as exc:
            raise ValueError(f"image {image_index} has an invalid data URI: {path}") from exc
    elif image.get("uri"):
        external = (path.parent / str(image["uri"])).resolve()
        if not external.is_file():
            raise FileNotFoundError(f"glTF image {image_index} is missing: {external}")
        payload = external.read_bytes()
    else:
        raise ValueError(f"image {image_index} has no bufferView or URI: {path}")
    try:
        from PIL import Image

        with Image.open(BytesIO(payload)) as decoded:
            rgba = np.asarray(decoded.convert("RGBA"), dtype=np.uint8)
    except Exception as exc:
        raise ValueError(f"could not decode glTF image {image_index} from {path}") from exc
    return np.ascontiguousarray(rgba)


def _quat_matrix(q: np.ndarray) -> np.ndarray:
    x, y, z, w = [float(v) for v in q]
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n < 1e-12:
        raise ValueError("zero-length node quaternion")
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y*y + z*z), 2 * (x*y - z*w), 2 * (x*z + y*w), 0],
                     [2 * (x*y + z*w), 1 - 2 * (x*x + z*z), 2 * (y*z - x*w), 0],
                     [2 * (x*z - y*w), 2 * (y*z + x*w), 1 - 2 * (x*x + y*y), 0],
                     [0, 0, 0, 1]], dtype=np.float64)


def _trs(t: np.ndarray, q: np.ndarray, s: np.ndarray) -> np.ndarray:
    out = _quat_matrix(q)
    out[:3, :3] *= np.asarray(s, dtype=np.float64)[None, :]
    out[:3, 3] = t
    return out


def _load_uncached(path: str | Path, *, decode_images: bool = False) -> ProxyAsset:
    path = Path(path).resolve()
    doc, blob = _read_glb(path)
    raw_nodes = doc.get("nodes", [])
    parents: dict[int, int] = {}
    for parent, node in enumerate(raw_nodes):
        for child in node.get("children", []):
            if child in parents:
                raise ValueError(f"node {child} has multiple parents")
            parents[int(child)] = parent
    nodes = tuple(Node(i, str(n.get("name") or f"node{i}"), parents.get(i), tuple(n.get("children", ())),
                       np.asarray(n.get("translation", (0, 0, 0)), dtype=np.float64),
                       np.asarray(n.get("rotation", (0, 0, 0, 1)), dtype=np.float64),
                       np.asarray(n.get("scale", (1, 1, 1)), dtype=np.float64),
                       n.get("mesh"), n.get("skin")) for i, n in enumerate(raw_nodes))
    skins = []
    for si, skin in enumerate(doc.get("skins", [])):
        if "inverseBindMatrices" in skin:
            ibm = _read_accessor(doc, blob, int(skin["inverseBindMatrices"])).reshape(-1, 4, 4)
            ibm = np.transpose(ibm, (0, 2, 1)).astype(np.float64)
        else:
            ibm = np.repeat(np.eye(4, dtype=np.float64)[None, :, :], len(skin["joints"]), axis=0)
        if len(ibm) != len(skin["joints"]):
            raise ValueError(f"skin {si} inverse bind count does not match joints")
        skins.append(Skin(si, tuple(int(j) for j in skin["joints"]), ibm))
    texture_images = (
        tuple(
            _decode_gltf_image(path, doc, blob, image_index)
            for image_index in range(len(doc.get("images", [])))
        )
        if decode_images
        else ()
    )
    materials: list[Material] = []
    for material_index, material in enumerate(doc.get("materials", [])):
        pbr = material.get("pbrMetallicRoughness", {})
        factor = np.asarray(pbr.get("baseColorFactor", (1.0, 1.0, 1.0, 1.0)), dtype=np.float32).reshape(-1)
        if factor.shape != (4,):
            raise ValueError(f"material {material_index} baseColorFactor must have four channels")
        texture_info = pbr.get("baseColorTexture") or {}
        texture_index = texture_info.get("index")
        image_index = None
        if texture_index is not None:
            textures = doc.get("textures", [])
            if not 0 <= int(texture_index) < len(textures):
                raise ValueError(f"material {material_index} references unknown texture {texture_index}")
            image_index = textures[int(texture_index)].get("source")
            if decode_images and image_index is not None and not 0 <= int(image_index) < len(texture_images):
                raise ValueError(f"material {material_index} references unknown image {image_index}")
        materials.append(
            Material(
                index=material_index,
                base_color_factor=factor,
                # Store the resolved image index, not the glTF texture index.
                # A texture object can be shared by multiple materials.
                base_color_texture=None if image_index is None else int(image_index),
                alpha_mode=str(material.get("alphaMode", "OPAQUE")).upper(),
                alpha_cutoff=float(material.get("alphaCutoff", 0.5)),
            )
        )
    primitives: list[Primitive] = []
    for node in nodes:
        if node.mesh is None:
            continue
        mesh = doc["meshes"][int(node.mesh)]
        for p in mesh.get("primitives", []):
            attrs = p.get("attributes", {})
            if "POSITION" not in attrs:
                raise ValueError(f"mesh {node.mesh} primitive has no POSITION")
            positions = np.asarray(_read_accessor(doc, blob, int(attrs["POSITION"])), dtype=np.float64).reshape(-1, 3)
            # Meshy exports commonly use JOINTS_0/WEIGHTS_0 plus a second
            # influence set. Blender evaluates every set; dropping JOINTS_1
            # makes the GPU bind silhouette differ from the rendered mesh.
            joint_keys = sorted(
                (key for key in attrs if str(key).startswith("JOINTS_")),
                key=lambda key: int(str(key).split("_")[-1]),
            )
            weight_keys = sorted(
                (key for key in attrs if str(key).startswith("WEIGHTS_")),
                key=lambda key: int(str(key).split("_")[-1]),
            )
            if len(joint_keys) != len(weight_keys):
                raise ValueError(
                    f"mesh {node.mesh} primitive has mismatched JOINTS_n/WEIGHTS_n sets: "
                    f"{joint_keys!r} vs {weight_keys!r}"
                )
            if joint_keys:
                joints = np.concatenate(
                    [
                        np.asarray(_read_accessor(doc, blob, int(attrs[key])), dtype=np.int64).reshape(-1, 4)
                        for key in joint_keys
                    ],
                    axis=1,
                )
                weights = np.concatenate(
                    [
                        np.asarray(_read_accessor(doc, blob, int(attrs[key])), dtype=np.float64).reshape(-1, 4)
                        for key in weight_keys
                    ],
                    axis=1,
                )
            else:
                joints = weights = None
            if (joints is None) != (weights is None) or (
                joints is not None
                and (len(joints) != len(positions) or len(weights) != len(positions))
            ):
                raise ValueError("POSITION, JOINTS_0, and WEIGHTS_0 counts are inconsistent")
            indices = None if "indices" not in p else np.asarray(_read_accessor(doc, blob, int(p["indices"])), dtype=np.int64).reshape(-1)
            texcoords = None
            if "TEXCOORD_0" in attrs:
                texcoords = np.asarray(_read_accessor(doc, blob, int(attrs["TEXCOORD_0"])), dtype=np.float32).reshape(-1, 2)
                if len(texcoords) != len(positions):
                    raise ValueError(f"mesh {node.mesh} TEXCOORD_0 count does not match POSITION")
            material_index = p.get("material")
            if material_index is not None and not 0 <= int(material_index) < len(materials):
                raise ValueError(f"mesh {node.mesh} references unknown material {material_index}")
            primitives.append(
                Primitive(
                    int(node.mesh), node.index, node.skin, positions, joints, weights, indices,
                    texcoords=texcoords, material=None if material_index is None else int(material_index),
                )
            )
    scene_index = int(doc.get("scene", 0))
    scenes = tuple(int(x) for x in doc.get("scenes", [{}])[scene_index].get("nodes", ())) if doc.get("scenes") else ()
    return ProxyAsset(
        path, nodes, tuple(skins), tuple(primitives), scenes,
        materials=tuple(materials), texture_images=texture_images,
    )


@functools.lru_cache(maxsize=16)
def load_asset(path: str | Path, *, decode_images: bool = False) -> ProxyAsset:
    """Load and cache an immutable proxy asset by resolved path.

    Geometry callers avoid decoding large embedded textures. The exact RGB
    renderer opts in explicitly because it owns the material upload.
    """
    return _load_uncached(str(Path(path).resolve()), decode_images=bool(decode_images))


def clear_asset_cache() -> None:
    load_asset.cache_clear()
    _GPU_ASSET_CACHE.clear()
    _SAMPLE_INDEX_CACHE.clear()


def _sample_indices_cached(
    asset: ProxyAsset,
    *,
    point_stride: int,
    max_points: int | None,
) -> tuple[np.ndarray, ...]:
    key = (str(asset.path), max(1, int(point_stride)), None if max_points is None else int(max_points))
    cached = _SAMPLE_INDEX_CACHE.get(key)
    if cached is not None:
        _SAMPLE_INDEX_CACHE.move_to_end(key)
        return cached
    samples = tuple(
        _sample_indices(len(primitive.positions), point_stride=point_stride, max_points=cap)
        for primitive, cap in zip(
            asset.primitives,
            _primitive_caps(asset, max_points=max_points),
        )
    )
    _SAMPLE_INDEX_CACHE[key] = samples
    _SAMPLE_INDEX_CACHE.move_to_end(key)
    while len(_SAMPLE_INDEX_CACHE) > _SAMPLE_INDEX_CACHE_LIMIT:
        _SAMPLE_INDEX_CACHE.popitem(last=False)
    return samples


def _primitive_caps(asset: ProxyAsset, *, max_points: int | None) -> tuple[int | None, ...]:
    if max_points is None:
        return tuple(None for _ in asset.primitives)
    total = sum(len(primitive.positions) for primitive in asset.primitives)
    return tuple(
        max(1, int(round(int(max_points) * len(primitive.positions) / max(total, 1))))
        for primitive in asset.primitives
    )


def _gpu_asset(
    asset: ProxyAsset,
    *,
    device: str,
    cache_max_entries: int = _GPU_ASSET_CACHE_DEFAULT_LIMIT,
    cache_enabled: bool = True,
):
    """Materialize immutable decoded GLB tensors once per mesh/device pair."""
    import torch  # type: ignore

    torch_device = torch.device(device)
    key = (str(asset.path), str(torch_device))
    if cache_enabled:
        cached = _GPU_ASSET_CACHE.get(key)
        if cached is not None:
            _GPU_ASSET_CACHE.move_to_end(key)
            return cached
    primitive_tensors = []
    for primitive in asset.primitives:
        primitive_tensors.append(
            {
                "node": int(primitive.node),
                "skin": None if primitive.skin is None else int(primitive.skin),
                "positions": torch.as_tensor(
                    np.c_[primitive.positions, np.ones(len(primitive.positions))],
                    dtype=torch.float32,
                    device=torch_device,
                ),
                "joints": None
                if primitive.joints is None
                else torch.as_tensor(primitive.joints, dtype=torch.long, device=torch_device),
                "weights": None
                if primitive.weights is None
                else torch.as_tensor(primitive.weights, dtype=torch.float32, device=torch_device),
            }
        )
    skin_tensors = tuple(
        {
            "joints": torch.as_tensor(skin.joints, dtype=torch.long, device=torch_device),
            "inverse_bind": torch.as_tensor(
                skin.inverse_bind, dtype=torch.float32, device=torch_device
            ),
        }
        for skin in asset.skins
    )
    cached = {"primitives": tuple(primitive_tensors), "skins": skin_tensors}
    if cache_enabled:
        _GPU_ASSET_CACHE[key] = cached
        _GPU_ASSET_CACHE.move_to_end(key)
        limit = max(1, int(cache_max_entries))
        while len(_GPU_ASSET_CACHE) > limit:
            _GPU_ASSET_CACHE.popitem(last=False)
    return cached


def _world_matrices(asset: ProxyAsset, pose: Mapping[str, Any] | None) -> np.ndarray:
    pose = pose or {}
    locals_: list[np.ndarray] = []
    for node in asset.nodes:
        delta = _delta_quaternion(pose[node.name]) if node.name in pose else np.array([0, 0, 0, 1.], dtype=np.float64)
        q = _quat_multiply(node.rotation, delta)
        locals_.append(_trs(node.translation, q, node.scale))
    world = [None] * len(asset.nodes)
    def visit(i: int) -> np.ndarray:
        if world[i] is None:
            world[i] = locals_[i] if asset.nodes[i].parent is None else visit(asset.nodes[i].parent) @ locals_[i]
        return world[i]
    return np.stack([visit(i) for i in range(len(asset.nodes))]) if world else np.zeros((0, 4, 4))


def _quat_multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ax, ay, az, aw = a; bx, by, bz, bw = b
    q = np.array([aw*bx + ax*bw + ay*bz - az*by, aw*by - ax*bz + ay*bw + az*bx,
                  aw*bz + ax*by - ay*bx + az*bw, aw*bw - ax*bx - ay*by - az*bz], dtype=np.float64)
    return q / np.linalg.norm(q)


def _delta_quaternion(value: Any) -> np.ndarray:
    if isinstance(value, (int, float)):
        angle, axis = float(value), np.array([0., 0., 1.])
    elif isinstance(value, Mapping) and "quaternion" in value:
        raw = np.asarray(value["quaternion"], dtype=np.float64)
        if len(raw) != 4:
            raise ValueError("quaternion pose entry must contain four values")
        if str(value.get("quaternionOrder", "wxyz")).lower() == "xyzw":
            return raw / np.linalg.norm(raw)
        return np.array([raw[1], raw[2], raw[3], raw[0]]) / np.linalg.norm(raw)
    elif isinstance(value, Mapping) and "axis" in value:
        axis = np.asarray(({"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}.get(str(value["axis"]).lower(), value["axis"])), dtype=np.float64)
        angle = float(value.get("angle", value.get("rad", 0.0)))
    elif isinstance(value, Mapping):
        e = np.asarray([float(value.get(k, 0.0)) for k in ("x", "y", "z")], dtype=np.float64)
        cx, cy, cz = np.cos(e / 2); sx, sy, sz = np.sin(e / 2)
        return np.array([sx*cy*cz + cx*sy*sz, cx*sy*cz - sx*cy*sz, cx*cy*sz + sx*sy*cz, cx*cy*cz - sx*sy*sz])
    else:
        raise TypeError(f"unsupported pose entry: {type(value)!r}")
    axis = axis / np.linalg.norm(axis)
    s = math.sin(angle / 2)
    return np.array([axis[0]*s, axis[1]*s, axis[2]*s, math.cos(angle / 2)], dtype=np.float64)


def _sample_indices(count: int, *, point_stride: int = 1, max_points: int | None = None) -> np.ndarray:
    indices = np.arange(0, int(count), max(1, int(point_stride)), dtype=np.int64)
    if max_points is not None and len(indices) > int(max_points):
        indices = np.linspace(0, len(indices) - 1, int(max_points), dtype=np.int64)
        indices = np.arange(0, int(count), max(1, int(point_stride)), dtype=np.int64)[indices]
    return indices


def _primitive_points(
    asset: ProxyAsset,
    prim: Primitive,
    worlds: np.ndarray,
    level: int,
    *,
    indices: np.ndarray | None = None,
) -> np.ndarray:
    if indices is None:
        indices = np.arange(len(prim.positions), dtype=np.int64)
    positions = prim.positions[indices]
    local = np.c_[positions, np.ones(len(positions))]
    if prim.skin is None or prim.joints is None or prim.weights is None:
        return (worlds[prim.node] @ local.T).T[:, :3]
    skin = asset.skins[int(prim.skin)]
    joint_mats = np.stack([worlds[node] @ ibm for node, ibm in zip(skin.joints, skin.inverse_bind)])
    joints = prim.joints[indices]
    weights = prim.weights[indices]
    if np.any(joints >= len(joint_mats)):
        raise ValueError("primitive joint index exceeds skin joint count")
    if level == 0:
        chosen = np.argmax(weights, axis=1)
        mats = joint_mats[joints[np.arange(len(joints)), chosen]]
        return np.einsum("nij,nj->ni", mats, local)[:, :3]
    if level != 1:
        raise ValueError("level must be 0 or 1")
    weights = weights / np.maximum(weights.sum(axis=1, keepdims=True), 1e-12)
    transformed = np.stack(
        [
            np.einsum("nij,nj->ni", joint_mats[joints[:, k]], local)
            for k in range(joints.shape[1])
        ],
        axis=1,
    )
    skinned = np.sum(transformed * weights[:, :, None], axis=1)
    return (worlds[prim.node] @ skinned.T).T[:, :3]


def _primitive_sampling(asset: ProxyAsset, *, point_stride: int, max_points: int | None) -> list[np.ndarray]:
    return list(
        _sample_indices_cached(
            asset,
            point_stride=point_stride,
            max_points=max_points,
        )
    )


def _root_transform(pose: Mapping[str, Any] | None, context: Mapping[str, Any] | None) -> np.ndarray:
    """Return the worker-compatible transform above the imported armature."""
    if not context:
        return np.eye(4, dtype=np.float64)
    pose = pose or {}
    basis = context.get("basis") or {}
    translation = pose.get("__motion_root__")
    displacement = np.zeros(3, dtype=np.float64)
    if isinstance(translation, Mapping):
        length = float(context.get("referenceLengthWorld", 1.0))
        for axis in ("forward", "lateral", "vertical"):
            vector = np.asarray(basis.get(axis, (0.0, 0.0, 0.0)), dtype=np.float64)
            displacement += vector * float(translation.get(axis, 0.0)) * length

    rotation_context = context.get("rotation") or {}
    rotation_values = pose.get("__motion_root_rotation__")
    rotation = np.eye(4, dtype=np.float64)
    if isinstance(rotation_values, Mapping):
        rotation_basis = rotation_context.get("basisVectors") or {}
        # Match the worker's fixed composition order. The values are degrees.
        for axis in ("camera_forward", "camera_right", "camera_up"):
            angle = float(rotation_values.get(axis, 0.0))
            if abs(angle) <= 1e-12:
                continue
            axis_vector = np.asarray(rotation_basis.get(axis, (0.0, 0.0, 0.0)), dtype=np.float64)
            norm = float(np.linalg.norm(axis_vector))
            if norm <= 1e-12:
                continue
            axis_vector /= norm
            x, y, z = axis_vector
            c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            one_minus_c = 1.0 - c
            axis_rotation = np.array(
                [
                    [c + x*x*one_minus_c, x*y*one_minus_c - z*s, x*z*one_minus_c + y*s, 0.0],
                    [y*x*one_minus_c + z*s, c + y*y*one_minus_c, y*z*one_minus_c - x*s, 0.0],
                    [z*x*one_minus_c - y*s, z*y*one_minus_c + x*s, c + z*z*one_minus_c, 0.0],
                    [0.0, 0.0, 0.0, 1.0],
                ],
                dtype=np.float64,
            )
            rotation = axis_rotation @ rotation
    pivot = np.asarray(rotation_context.get("pivot", (0.0, 0.0, 0.0)), dtype=np.float64)
    translate = np.eye(4, dtype=np.float64)
    translate[:3, 3] = displacement
    to_pivot = np.eye(4, dtype=np.float64); to_pivot[:3, 3] = pivot
    from_pivot = np.eye(4, dtype=np.float64); from_pivot[:3, 3] = -pivot
    return translate @ to_pivot @ rotation @ from_pivot


def evaluate_points(
    asset: ProxyAsset,
    pose: Mapping[str, Any] | None = None,
    *,
    level: int = 1,
    point_stride: int = 1,
    max_points: int | None = None,
    world_scale: float = 1.0,
    root_context: Mapping[str, Any] | None = None,
) -> np.ndarray:
    """Return proxy points; ``point_stride`` makes Level 1 deliberately sparse."""
    worlds = _world_matrices(asset, pose)
    samples = _primitive_sampling(asset, point_stride=point_stride, max_points=max_points)
    points = np.concatenate(
        [_primitive_points(asset, p, worlds, level, indices=indices) for p, indices in zip(asset.primitives, samples)],
        axis=0,
    ) if asset.primitives else np.zeros((0, 3))
    points = points * float(world_scale)
    root = _root_transform(pose, root_context)
    return (root @ np.c_[points, np.ones(len(points))].T).T[:, :3] if len(points) else points


def _torch_points_batch(
    asset: ProxyAsset,
    poses: Sequence[Mapping[str, Any]],
    *,
    level: int,
    point_stride: int = 1,
    max_points: int | None = None,
    world_scale: float = 1.0,
    device: str = "cpu",
    root_context: Mapping[str, Any] | None = None,
    prepared: Mapping[str, Any] | None = None,
    pose_indices: Sequence[int] | None = None,
    gpu_asset_cache_max_entries: int = _GPU_ASSET_CACHE_DEFAULT_LIMIT,
    gpu_asset_cache_enabled: bool = True,
):
    """Batch weighted-LBS points; immutable mesh tensors and worlds are reused."""
    import torch  # type: ignore

    if prepared is None:
        prepared = prepare_batch(
            asset,
            poses,
            device=device,
            world_scale=world_scale,
            root_context=root_context,
            gpu_asset_cache_max_entries=gpu_asset_cache_max_entries,
            gpu_asset_cache_enabled=gpu_asset_cache_enabled,
        )
    torch_device = torch.device(str(prepared["device"]))
    dtype = torch.float32
    world_batches = prepared["worldBatches"]
    root_batches = prepared.get("rootBatches")
    if pose_indices is not None:
        indices = torch.as_tensor(tuple(int(index) for index in pose_indices), dtype=torch.long, device=torch_device)
        world_batches = world_batches.index_select(0, indices)
        if root_batches is not None:
            root_batches = root_batches.index_select(0, indices)
    static_asset = prepared.get("gpuAsset") or _gpu_asset(
        asset,
        device=str(torch_device),
        cache_max_entries=gpu_asset_cache_max_entries,
        cache_enabled=gpu_asset_cache_enabled,
    )
    chunks = []
    samples = _primitive_sampling(asset, point_stride=point_stride, max_points=max_points)
    for static_primitive, sample_indices in zip(static_asset["primitives"], samples):
        sample_tensor = torch.as_tensor(sample_indices, dtype=torch.long, device=torch_device)
        local = static_primitive["positions"].index_select(0, sample_tensor)
        if (
            static_primitive["skin"] is None
            or static_primitive["joints"] is None
            or static_primitive["weights"] is None
        ):
            points = torch.einsum(
                "bkl,nl->bnk",
                world_batches[:, static_primitive["node"]],
                local,
            )
        else:
            skin = static_asset["skins"][int(static_primitive["skin"])]
            ibm = skin["inverse_bind"]
            joints = skin["joints"]
            joint_mats = torch.matmul(world_batches[:, joints], ibm[None, :, :, :])
            transformed = torch.einsum("bjkl,nl->bjnk", joint_mats, local)
            prim_joints = static_primitive["joints"].index_select(0, sample_tensor).T
            indices = prim_joints
            batch_size = int(world_batches.shape[0])
            point_count = int(local.shape[0])
            # Meshy exports are not limited to JOINTS_0/WEIGHTS_0's common
            # four influences.  Some smart-rigs carry eight influences per
            # vertex; derive the width from the decoded accessor instead of
            # hard-coding four and failing only when a larger mesh is fitted.
            influence_count = int(indices.shape[0])
            gather_index = indices[None, :, :, None].expand(
                batch_size, influence_count, point_count, 4
            )
            selected = torch.gather(transformed, 1, gather_index)
            if level == 0:
                chosen = torch.argmax(
                    static_primitive["weights"].index_select(0, sample_tensor), dim=1
                )
                chosen_index = chosen[None, None, :, None].expand(batch_size, 1, point_count, 4)
                selected = torch.gather(transformed, 1, chosen_index).squeeze(1)
            elif level == 1:
                weights = static_primitive["weights"].index_select(0, sample_tensor)
                weights = weights / torch.clamp(weights.sum(dim=1, keepdim=True), min=1e-12)
                selected = (selected * weights.T[None, :, :, None]).sum(dim=1)
            else:
                raise ValueError("level must be 0 or 1")
            points = torch.einsum(
                "bkl,bnl->bnk",
                world_batches[:, static_primitive["node"]],
                selected,
            )
        chunks.append(points[..., :3] * float(prepared.get("worldScale", world_scale)))
    points = torch.cat(chunks, dim=1) if chunks else torch.zeros((len(poses), 0, 3), dtype=dtype, device=torch_device)
    if root_batches is not None and points.shape[1]:
        points = torch.einsum(
            "bkl,bnl->bnk",
            root_batches,
            torch.cat(
                (points, torch.ones((*points.shape[:2], 1), dtype=dtype, device=torch_device)),
                dim=2,
            ),
        )[..., :3]
    return points


def prepare_batch(
    asset: ProxyAsset,
    poses: Sequence[Mapping[str, Any]],
    *,
    device: str = "auto",
    world_scale: float = 1.0,
    root_context: Mapping[str, Any] | None = None,
    gpu_asset_cache_max_entries: int = _GPU_ASSET_CACHE_DEFAULT_LIMIT,
    gpu_asset_cache_enabled: bool = True,
) -> dict[str, Any]:
    """Prepare one candidate wave for reuse across Level 0 and Level 1.

    Pose-dependent world matrices are computed once per wave.  The decoded
    GLB tensors (positions, weights, joints, and inverse binds) are shared by
    every wave for the same mesh/device pair.
    """
    import torch  # type: ignore

    selected_device = _select_torch_device(device)
    dtype = torch.float32
    worlds = np.stack(
        [_world_matrices(asset, pose) for pose in poses],
        axis=0,
    ) if poses else np.zeros((0, len(asset.nodes), 4, 4), dtype=np.float32)
    root_matrices = None
    if root_context and poses:
        root_matrices = np.stack(
            [_root_transform(pose, root_context) for pose in poses],
            axis=0,
        )
    torch_device = torch.device(selected_device)
    return {
        "assetKey": str(asset.path),
        "device": str(torch_device),
        "worldScale": float(world_scale),
        "worldBatches": torch.as_tensor(worlds, dtype=dtype, device=torch_device),
        "rootBatches": None
        if root_matrices is None
        else torch.as_tensor(root_matrices, dtype=dtype, device=torch_device),
        "gpuAsset": _gpu_asset(
            asset,
            device=str(torch_device),
            cache_max_entries=gpu_asset_cache_max_entries,
            cache_enabled=gpu_asset_cache_enabled,
        ),
        "poseCount": len(poses),
    }


def validate_bind_pose(asset: ProxyAsset, *, level: int = 1, tolerance: float = 1e-5) -> dict[str, Any]:
    expected = []
    for p in asset.primitives:
        expected.append((_world_matrices(asset, None)[p.node] @ np.c_[p.positions, np.ones(len(p.positions))].T).T[:, :3])
    actual = evaluate_points(asset, level=level)
    ref = np.concatenate(expected, axis=0) if expected else np.zeros((0, 3))
    error = np.max(np.linalg.norm(actual - ref, axis=1)) if len(ref) else 0.0
    return {"ok": bool(error <= tolerance), "maxError": float(error), "tolerance": float(tolerance), "pointCount": int(len(ref))}


def project_points(points: np.ndarray, camera: Mapping[str, Any], *, width: int, height: int) -> np.ndarray:
    if "basisScreenRows" in camera:
        rows = np.asarray(camera["basisScreenRows"], dtype=np.float64)
        # The worker's second screen row is already image-down.  Keep the
        # proxy camera in image coordinates so its y convention matches the
        # alpha target mask and the low-resolution rasterizer.
        right, up = rows[0], rows[1]
        forward = np.cross(up, right)
        px = float(camera["pxPerWorld"])
    else:
        right, up, forward = (np.asarray(camera[k], dtype=np.float64) for k in ("right", "up", "forward"))
        px = float(camera["pxPerWorld"])
    del forward  # retained in the contract for callers that need depth ordering
    offset = np.asarray(camera.get("screenOffset", (width / 2, height / 2)), dtype=np.float64)
    return np.column_stack((points @ right * px + offset[0], points @ up * px + offset[1]))


def point_mask(projected: np.ndarray, *, width: int, height: int, radius: int = 1) -> np.ndarray:
    projected = np.asarray(projected, dtype=np.float64).reshape(-1, 2)
    out = np.zeros((int(height), int(width)), dtype=np.uint8)
    if not len(projected):
        return out
    radius = max(0, int(radius))
    rounded = np.floor(projected + 0.5).astype(np.int64)
    yy, xx = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    offsets = np.column_stack((xx.ravel(), yy.ravel()))
    offsets = offsets[(offsets[:, 0] ** 2 + offsets[:, 1] ** 2) <= radius * radius]
    for dx, dy in offsets:
        x = rounded[:, 0] + int(dx)
        y = rounded[:, 1] + int(dy)
        valid = (x >= 0) & (x < int(width)) & (y >= 0) & (y < int(height))
        np.add.at(out, (y[valid], x[valid]), 1)
    return (out > 0).astype(np.uint8)


def _point_mask_batch_torch(projected, *, width: int, height: int, radius: int):
    """Rasterize B x N projected points with GPU scatter, not a point loop."""
    import torch  # type: ignore

    batch_size = int(projected.shape[0])
    flat = torch.zeros(
        (batch_size, int(width) * int(height)),
        dtype=torch.int32,
        device=projected.device,
    )
    if projected.shape[1] == 0:
        return flat.reshape(batch_size, int(height), int(width)).to(torch.uint8)
    radius = max(0, int(radius))
    rounded = torch.floor(projected + 0.5).to(torch.long)
    offsets = [
        (dx, dy)
        for dy in range(-radius, radius + 1)
        for dx in range(-radius, radius + 1)
        if dx * dx + dy * dy <= radius * radius
    ]
    for dx, dy in offsets:
        x = rounded[..., 0] + int(dx)
        y = rounded[..., 1] + int(dy)
        valid = (x >= 0) & (x < int(width)) & (y >= 0) & (y < int(height))
        linear = (y * int(width) + x).clamp(0, int(width) * int(height) - 1)
        flat.scatter_add_(1, linear, valid.to(torch.int32))
    return (flat > 0).reshape(batch_size, int(height), int(width)).to(torch.uint8)


def score_masks(predicted: np.ndarray, target_alpha: np.ndarray) -> dict[str, float]:
    return score_masks_batch(np.asarray(predicted)[None, ...], target_alpha)[0]


def score_masks_batch(predicted: np.ndarray, target_alpha: np.ndarray) -> list[dict[str, float]]:
    """Score a batch of masks with array operations and no candidate loop."""
    pred = np.asarray(predicted, dtype=bool)
    if pred.ndim != 3:
        raise ValueError("predicted masks must have shape (batch, height, width)")
    target = np.asarray(target_alpha) > 0
    if target.shape != pred.shape[1:]:
        raise ValueError(
            f"target alpha shape {target.shape} does not match mask shape {pred.shape[1:]}"
        )
    target_f = target.astype(np.float32)
    pred_f = pred.astype(np.float32)
    inter = np.logical_and(pred, target[None, ...]).sum(axis=(1, 2)).astype(np.float64)
    union = np.logical_or(pred, target[None, ...]).sum(axis=(1, 2)).astype(np.float64)
    pred_count = pred_f.sum(axis=(1, 2))
    target_count = float(target_f.sum())
    height, width = pred.shape[1:]
    xs = np.arange(width, dtype=np.float32)[None, None, :]
    ys = np.arange(height, dtype=np.float32)[None, :, None]
    pred_x = (pred_f * xs).sum(axis=(1, 2)) / np.maximum(pred_count, 1.0)
    pred_y = (pred_f * ys).sum(axis=(1, 2)) / np.maximum(pred_count, 1.0)
    target_x = float((target_f * xs[0]).sum() / max(target_count, 1.0))
    target_y = float((target_f * ys[0]).sum() / max(target_count, 1.0))
    centroid = np.hypot(pred_x - target_x, pred_y - target_y)
    empty = (pred_count <= 0.0) | (target_count <= 0.0)
    centroid = np.where(empty, float(max(height, width)), centroid)
    denom = max(1.0, math.hypot(width, height))
    occupancy = np.abs(pred_f.mean(axis=(1, 2)) - target_f.mean())
    iou = np.divide(inter, union, out=np.ones_like(inter), where=union > 0.0)
    score = iou - centroid / denom - occupancy
    return [
        {
            "iou": float(iou[index]),
            "centroidDistancePx": float(centroid[index]),
            "occupancyError": float(occupancy[index]),
            "score": float(score[index]),
        }
        for index in range(pred.shape[0])
    ]


def _select_torch_device(device: str) -> str:
    import torch  # type: ignore
    requested = str(device or "auto").lower()
    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError(f"geometric proxy requested {device!r}, but CUDA is unavailable")
    return requested


def evaluate_batch(
    asset: ProxyAsset,
    poses: Sequence[Mapping[str, Any]],
    camera: Mapping[str, Any],
    *,
    width: int,
    height: int,
    level: int = 1,
    point_radius: int = 1,
    point_stride: int = 1,
    max_points: int | None = None,
    world_scale: float = 1.0,
    device: str = "auto",
    root_context: Mapping[str, Any] | None = None,
    target_alpha: np.ndarray | None = None,
    prepared: Mapping[str, Any] | None = None,
    pose_indices: Sequence[int] | None = None,
    gpu_asset_cache_max_entries: int = _GPU_ASSET_CACHE_DEFAULT_LIMIT,
    gpu_asset_cache_enabled: bool = True,
) -> dict[str, Any]:
    """Evaluate a candidate wave with cached GPU geometry and batched rasterization."""
    try:
        import torch  # type: ignore
        torch_available = True
    except ImportError:
        torch_available = False
    masks = np.zeros((0, int(height), int(width)), dtype=np.uint8)
    scores = []
    selected_device = None
    if poses and torch_available:
        import torch  # type: ignore
        selected_device = _select_torch_device(device)
        if prepared is None:
            prepared = prepare_batch(
                asset,
                poses,
                device=selected_device,
                world_scale=world_scale,
                root_context=root_context,
                gpu_asset_cache_max_entries=gpu_asset_cache_max_entries,
                gpu_asset_cache_enabled=gpu_asset_cache_enabled,
            )
        points_tensor = _torch_points_batch(
            asset,
            poses,
            level=level,
            point_stride=point_stride,
            max_points=max_points,
            world_scale=world_scale,
            device=selected_device,
            root_context=root_context,
            prepared=prepared,
            pose_indices=pose_indices,
            gpu_asset_cache_max_entries=gpu_asset_cache_max_entries,
        )
        if "basisScreenRows" in camera:
            rows = np.asarray(camera["basisScreenRows"], dtype=np.float64)
            right, up = rows[0], rows[1]
        else:
            right = np.asarray(camera["right"], dtype=np.float64)
            up = np.asarray(camera["up"], dtype=np.float64)
        px = float(camera["pxPerWorld"])
        offset = np.asarray(camera.get("screenOffset", (width / 2, height / 2)), dtype=np.float64)
        basis = torch.as_tensor(np.stack((right, up)), dtype=points_tensor.dtype, device=points_tensor.device)
        projected_batches = torch.einsum("bnd,sd->bns", points_tensor, basis) * px
        projected_batches += torch.as_tensor(offset, dtype=points_tensor.dtype, device=points_tensor.device)
        masks = _point_mask_batch_torch(
            projected_batches,
            width=width,
            height=height,
            radius=point_radius,
        ).detach().cpu().numpy()
    else:
        projected_list = [
            project_points(
                evaluate_points(
                    asset,
                    pose,
                    level=level,
                    point_stride=point_stride,
                    max_points=max_points,
                    world_scale=world_scale,
                    root_context=root_context,
                ),
                camera,
                width=width,
                height=height,
            )
            for pose in poses
        ]
        masks = np.stack(
            [
                point_mask(projected, width=width, height=height, radius=point_radius)
                for projected in projected_list
            ]
        ) if projected_list else np.zeros((0, height, width), dtype=np.uint8)
    if target_alpha is not None:
        scores = score_masks_batch(masks, target_alpha)
    else:
        scores = [None for _ in range(len(masks))]
    return {
        "masks": masks,
        "scores": scores,
        "backend": f"torch:{selected_device}" if selected_device else "numpy",
        "level": int(level),
        "rasterizer": "torch_scatter" if selected_device else "numpy",
        "preparedBatchReused": bool(prepared is not None),
    }


__all__ = [
    "ProxyAsset",
    "load_asset",
    "clear_asset_cache",
    "evaluate_points",
    "evaluate_batch",
    "prepare_batch",
    "project_points",
    "point_mask",
    "score_masks",
    "score_masks_batch",
    "validate_bind_pose",
]
