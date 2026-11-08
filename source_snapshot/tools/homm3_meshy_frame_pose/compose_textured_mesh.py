"""Compose a regenerated body and a separate textured prop into one GLB source.

This is a preparation step for the owned re-rig lane.  The prop remains separate
geometry and is later extracted/owned by ``prop_attachment.v1``; the atlas only
makes the two independently generated materials available to the existing
single-primitive fit pipeline without borrowing an old body's skeleton.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from owned_rerig.glb_io import _append_array, _pad4, load_render_surface, read_glb, write_glb


def _rotation_from_y_axis(direction: np.ndarray) -> np.ndarray:
    """Return a proper rotation carrying local +Y onto ``direction``."""
    y = np.asarray(direction, dtype=np.float64)
    y /= np.linalg.norm(y)
    helper = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(y, helper))) > 0.92:
        helper = np.array([1.0, 0.0, 0.0])
    x = np.cross(helper, y)
    x /= np.linalg.norm(x)
    z = np.cross(x, y)
    z /= np.linalg.norm(z)
    return np.column_stack((x, y, z))


def _atlas_uv(uvs: np.ndarray, x: int, y: int, width: int, height: int,
              atlas_width: int, atlas_height: int) -> np.ndarray:
    mapped = np.asarray(uvs, dtype=np.float64).copy()
    mapped[:, 0] = (x + mapped[:, 0] * width) / atlas_width
    mapped[:, 1] = (y + mapped[:, 1] * height) / atlas_height
    return mapped


def compose(
    body_path: Path,
    prop_path: Path,
    output_path: Path,
    *,
    prop_grip: np.ndarray,
    prop_axis: np.ndarray,
    prop_local_grip: np.ndarray,
    prop_local_axis: np.ndarray,
) -> dict:
    body = load_render_surface(body_path)
    prop = load_render_surface(prop_path)
    rotation = _rotation_from_y_axis(prop_axis) @ _rotation_from_y_axis(prop_local_axis).T
    local_axis = np.asarray(prop_local_axis, dtype=np.float64)
    local_grip = np.asarray(prop_local_grip, dtype=np.float64)
    prop_positions = (prop["positions"] - local_grip) @ rotation.T + prop_grip
    prop_normals = None
    if prop["normals"] is not None:
        prop_normals = prop["normals"] @ rotation.T

    body_positions = body["positions"]
    positions = np.concatenate((body_positions, prop_positions), axis=0)
    normals = None
    if body["normals"] is not None and prop_normals is not None:
        normals = np.concatenate((body["normals"], prop_normals), axis=0)
    elif body["normals"] is not None or prop_normals is not None:
        raise ValueError("body and prop must either both have normals or both omit them")

    body_w, body_h = body["baseColorSize"]
    prop_w, prop_h = prop["baseColorSize"]
    atlas_w = int(body_w + prop_w)
    atlas_h = int(max(body_h, prop_h))
    atlas = Image.new("RGB", (atlas_w, atlas_h), (0, 0, 0))
    atlas.paste(Image.fromarray(body["baseColor"], mode="RGB"), (0, 0))
    atlas.paste(Image.fromarray(prop["baseColor"], mode="RGB"), (body_w, 0))
    atlas_array = np.asarray(atlas, dtype=np.uint8)
    body_uv = _atlas_uv(body["uvs"], 0, 0, body_w, body_h, atlas_w, atlas_h)
    prop_uv = _atlas_uv(prop["uvs"], body_w, 0, prop_w, prop_h, atlas_w, atlas_h)
    uvs = np.concatenate((body_uv, prop_uv), axis=0)
    indices = np.concatenate((body["indices"], prop["indices"] + len(body_positions)))

    import io

    png = io.BytesIO()
    atlas.save(png, format="PNG", optimize=True)
    image_bytes = png.getvalue()
    bin_blob = bytearray()
    views: list[dict] = []
    accessors: list[dict] = []
    pos_i = _append_array(bin_blob, views, accessors, positions.astype(np.float32), "VEC3", 5126)
    idx_i = _append_array(bin_blob, views, accessors, indices.astype(np.uint32), "SCALAR", 5125)
    uv_i = _append_array(bin_blob, views, accessors, uvs.astype(np.float32), "VEC2", 5126)
    attributes = {"POSITION": pos_i, "TEXCOORD_0": uv_i}
    if normals is not None:
        attributes["NORMAL"] = _append_array(
            bin_blob, views, accessors, normals.astype(np.float32), "VEC3", 5126
        )
    image_offset = len(bin_blob)
    bin_blob.extend(image_bytes)
    _pad4(bin_blob)
    views.append({"buffer": 0, "byteOffset": image_offset, "byteLength": len(image_bytes)})
    extras = {
        "schema": "homm3.composed_textured_mesh.v1",
        "bodySource": str(body_path).replace("\\", "/"),
        "bodySourceSha256": body["sourceSha256"],
        "propSource": str(prop_path).replace("\\", "/"),
        "propSourceSha256": prop["sourceSha256"],
        "propTransform": {
            "localGrip": local_grip.tolist(),
            "targetGrip": np.asarray(prop_grip, dtype=np.float64).tolist(),
            "targetAxis": np.asarray(prop_axis, dtype=np.float64).tolist(),
            "rotation": rotation.tolist(),
        },
        "atlasSize": [atlas_w, atlas_h],
        "bodyVertexCount": int(len(body_positions)),
        "propVertexCount": int(len(prop_positions)),
    }
    doc = {
        "asset": {"version": "2.0", "generator": "homm3_meshy_frame_pose.compose_textured_mesh"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "ComposedSource", "mesh": 0, "extras": extras}],
        "meshes": [{
            "name": "ComposedSource",
            "primitives": [{
                "attributes": attributes,
                "indices": idx_i,
                "material": 0,
            }],
        }],
        "materials": [{
            "name": "ComposedBaseColor",
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": 0},
                "metallicFactor": 0.0,
                "roughnessFactor": 1.0,
            },
        }],
        "textures": [{"source": 0}],
        "images": [{"name": "body_prop_atlas.png", "mimeType": "image/png", "bufferView": len(views) - 1}],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(bin_blob)}],
        "extras": extras,
    }
    write_glb(output_path, doc, bytes(bin_blob))
    output_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
    metadata = {**extras, "output": str(output_path).replace("\\", "/"), "outputSha256": output_hash}
    output_path.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--body", type=Path, required=True)
    parser.add_argument("--prop", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-grip", type=float, nargs=3, required=True)
    parser.add_argument("--target-axis", type=float, nargs=3, required=True)
    parser.add_argument("--local-grip", type=float, nargs=3, default=[0.0, 0.3, 0.0])
    parser.add_argument("--local-axis", type=float, nargs=3, default=[0.0, 0.7031218557, 0.0])
    args = parser.parse_args()
    metadata = compose(
        args.body,
        args.prop,
        args.output,
        prop_grip=np.asarray(args.target_grip, dtype=np.float64),
        prop_axis=np.asarray(args.target_axis, dtype=np.float64),
        prop_local_grip=np.asarray(args.local_grip, dtype=np.float64),
        prop_local_axis=np.asarray(args.local_axis, dtype=np.float64),
    )
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
