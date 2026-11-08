#!/usr/bin/env python3
"""Detect and apply LLM-authored coil-on-coil weld cuts on a Meshy GLB.

Usage:

  py -3 tools/homm3_silhouette_pose_fit/repair_meshy_coil_welds.py detect \\
    --src artifacts/meshy_downloads/hota_cove_haspid_smartrigged.glb \\
    --sprite artifacts/creature_aaa_3d_upscale/hota_cove_haspid.png \\
    --out-dir artifacts/haspid_pose_pipeline/coil_weld/

  py -3 tools/homm3_silhouette_pose_fit/repair_meshy_coil_welds.py apply \\
    --src artifacts/meshy_downloads/hota_cove_haspid_smartrigged.glb \\
    --authored artifacts/haspid_pose_pipeline/coil_weld/coil_weld_authored.json \\
    --out artifacts/haspid_pose_pipeline/coil_weld/hota_cove_haspid_coilfix.glb \\
    --report artifacts/haspid_pose_pipeline/coil_weld/coil_weld_apply.json

Detect writes an overlay and an authorship template. Apply refuses the
template until every cluster id is listed as cut or keep. Output is mesh +
PBR textures. Skin is stripped because topology changed; owned bind is next.

Proof: generated GLB + overlay. Not OE runtime.
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from coil_weld_repair import (
    AUTHORING_METHOD,
    CoilWeldDetectResult,
    CoilWeldDetectSettings,
    apply_coil_weld_cuts,
    authorship_template,
    body_extent,
    compute_vertex_normals,
    cut_source_faces_from_authorship,
    detect_coil_weld_clusters,
)

ROOT = Path(__file__).resolve().parents[2]
COMPONENTS = {
    5120: (np.int8, 1),
    5121: (np.uint8, 1),
    5122: (np.int16, 2),
    5123: (np.uint16, 2),
    5125: (np.uint32, 4),
    5126: (np.float32, 4),
}
TYPE_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _read_glb(path: Path) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError(f"not a GLB file: {path}")
    version, length = struct.unpack_from("<II", data, 4)
    if version != 2 or length > len(data):
        raise ValueError(f"unsupported or truncated GLB header: {path}")
    offset = 12
    doc = None
    blob = b""
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


def _read_accessor(doc: Mapping[str, Any], blob: bytes, index: int) -> np.ndarray:
    acc = doc["accessors"][index]
    dtype, component_size = COMPONENTS[acc["componentType"]]
    width = TYPE_WIDTH[acc["type"]]
    count = int(acc["count"])
    if "bufferView" not in acc:
        return np.zeros((count, width), dtype=dtype).reshape((count,) if width == 1 else (count, width))
    view = doc["bufferViews"][acc["bufferView"]]
    stride = int(view.get("byteStride", width * component_size))
    base = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
    item = width * component_size
    if stride < item:
        raise ValueError(f"accessor {index} has byteStride smaller than element")
    if stride == item:
        raw = np.frombuffer(blob, dtype=dtype, count=count * width, offset=base)
        values = raw.reshape((count,) if width == 1 else (count, width)).copy()
    else:
        values = np.empty((count, width), dtype=dtype)
        for row in range(count):
            start = base + row * stride
            values[row] = np.frombuffer(blob[start : start + item], dtype=dtype, count=width)
        if width == 1:
            values = values.reshape(count)
    if acc.get("sparse"):
        raise ValueError(f"accessor {index} uses sparse data; coil-weld repair does not")
    return values


def load_glb_triangles(path: Path) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray], dict[str, Any]]:
    doc, blob = _read_glb(path)
    meshes = doc.get("meshes")
    if not isinstance(meshes, list) or not meshes:
        raise ValueError(f"{path} has no meshes")
    if len(meshes) != 1:
        raise ValueError(f"{path} has {len(meshes)} meshes; coil-weld repair needs exactly one")
    primitives = meshes[0].get("primitives")
    if not isinstance(primitives, list) or not primitives:
        raise ValueError(f"{path} mesh 0 has no primitives")
    vert_blocks: list[np.ndarray] = []
    face_blocks: list[np.ndarray] = []
    uv_blocks: list[np.ndarray] = []
    has_uv = None
    cursor = 0
    for prim_index, primitive in enumerate(primitives):
        mode = int(primitive.get("mode", 4))
        if mode != 4:
            raise ValueError(f"{path} primitive {prim_index} is not triangles (mode={mode})")
        attrs = primitive.get("attributes") or {}
        if "POSITION" not in attrs:
            raise ValueError(f"{path} primitive {prim_index} has no POSITION")
        positions = np.asarray(_read_accessor(doc, blob, int(attrs["POSITION"])), dtype=np.float64).reshape(-1, 3)
        if "indices" not in primitive:
            raise ValueError(f"{path} primitive {prim_index} has no indices")
        indices = np.asarray(_read_accessor(doc, blob, int(primitive["indices"])), dtype=np.int64).reshape(-1)
        if indices.size % 3 != 0:
            raise ValueError(f"{path} primitive {prim_index} index count is not a multiple of 3")
        faces = indices.reshape(-1, 3)
        uv_present = "TEXCOORD_0" in attrs
        if has_uv is None:
            has_uv = uv_present
        elif uv_present != has_uv:
            raise ValueError(f"{path} primitives disagree about TEXCOORD_0")
        if uv_present:
            uvs = np.asarray(_read_accessor(doc, blob, int(attrs["TEXCOORD_0"])), dtype=np.float32).reshape(-1, 2)
            if int(uvs.shape[0]) != int(positions.shape[0]):
                raise ValueError(f"{path} primitive {prim_index} UV count does not match POSITION")
            uv_blocks.append(uvs)
        vert_blocks.append(positions)
        face_blocks.append(faces + cursor)
        cursor += int(positions.shape[0])
    verts = np.concatenate(vert_blocks, axis=0)
    faces = np.concatenate(face_blocks, axis=0)
    attributes: dict[str, np.ndarray] = {}
    if has_uv:
        attributes["TEXCOORD_0"] = np.concatenate(uv_blocks, axis=0)
    extras = {"doc": doc, "blob": blob, "path": path}
    return verts, faces, attributes, extras


def _write_glb(path: Path, doc: Mapping[str, Any], bin_blob: bytes) -> None:
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))


def _copy_embedded_images(
    src_doc: Mapping[str, Any],
    src_blob: bytes,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], bytes]:
    images = src_doc.get("images") or []
    textures = src_doc.get("textures") or []
    samplers = src_doc.get("samplers") or []
    if not images:
        return [], [], [], [], b""
    blob = bytearray()
    out_images: list[dict[str, Any]] = []
    views: list[dict[str, Any]] = []
    for image in images:
        if "bufferView" not in image:
            raise ValueError("coil-weld repair needs embedded glTF images, not external URIs")
        view = src_doc["bufferViews"][int(image["bufferView"])]
        start = int(view.get("byteOffset", 0))
        end = start + int(view["byteLength"])
        payload = src_blob[start:end]
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(payload)})
        blob.extend(payload)
        copied: dict[str, Any] = {"bufferView": len(views) - 1}
        if "mimeType" in image:
            copied["mimeType"] = image["mimeType"]
        out_images.append(copied)
    out_textures = [dict(texture) for texture in textures]
    out_samplers = [dict(sampler) for sampler in samplers] if samplers else []
    return views, out_images, out_textures, out_samplers, bytes(blob)


def write_mesh_glb(
    path: Path,
    verts: np.ndarray,
    faces: np.ndarray,
    attributes: Mapping[str, np.ndarray],
    *,
    source_doc: Mapping[str, Any],
    source_blob: bytes,
) -> None:
    positions = np.asarray(verts, dtype=np.float32).reshape(-1, 3)
    indices = np.asarray(faces, dtype=np.uint32).reshape(-1)
    normals = compute_vertex_normals(verts, faces).astype(np.float32)
    blob = bytearray()
    views: list[dict[str, Any]] = []
    accessors: list[dict[str, Any]] = []

    def add_array(array: np.ndarray, *, kind: str) -> int:
        raw = np.ascontiguousarray(array).tobytes()
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(raw)})
        blob.extend(raw)
        accessor: dict[str, Any] = {
            "bufferView": len(views) - 1,
            "componentType": 5126 if array.dtype == np.float32 else 5125,
            "count": int(array.shape[0]),
            "type": kind,
        }
        if kind == "VEC3" and array.dtype == np.float32:
            accessor["min"] = [float(value) for value in array.min(axis=0)]
            accessor["max"] = [float(value) for value in array.max(axis=0)]
        accessors.append(accessor)
        return len(accessors) - 1

    attr_map = {
        "POSITION": add_array(positions, kind="VEC3"),
        "NORMAL": add_array(normals, kind="VEC3"),
    }
    if "TEXCOORD_0" in attributes:
        uvs = np.asarray(attributes["TEXCOORD_0"], dtype=np.float32).reshape(-1, 2)
        if int(uvs.shape[0]) != int(positions.shape[0]):
            raise ValueError("TEXCOORD_0 length does not match POSITION after cut")
        attr_map["TEXCOORD_0"] = add_array(uvs, kind="VEC2")
    elif any("TEXCOORD_0" in (prim.get("attributes") or {}) for prim in source_doc["meshes"][0]["primitives"]):
        raise ValueError("source mesh has UVs but the cut mesh dropped TEXCOORD_0")
    index_accessor = add_array(np.ascontiguousarray(indices, dtype=np.uint32), kind="SCALAR")
    image_views, images, textures, samplers, image_blob = _copy_embedded_images(source_doc, source_blob)
    view_offset = len(views)
    views.extend(image_views)
    for image in images:
        image["bufferView"] = int(image["bufferView"]) + view_offset
    blob.extend(image_blob)
    primitive: dict[str, Any] = {
        "attributes": attr_map,
        "indices": index_accessor,
    }
    materials = source_doc.get("materials") or []
    if materials:
        primitive["material"] = 0
    doc: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "repair_meshy_coil_welds"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "coil_weld_repaired"}],
        "meshes": [{"name": "coil_weld_repaired", "primitives": [primitive]}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": views,
        "accessors": accessors,
    }
    if materials:
        doc["materials"] = materials
    if images:
        doc["images"] = images
    if textures:
        doc["textures"] = textures
    if samplers:
        doc["samplers"] = samplers
    _write_glb(path, doc, bytes(blob))


def _settings_from_args(args: argparse.Namespace) -> CoilWeldDetectSettings:
    return CoilWeldDetectSettings(
        same_sheet_weld_body_lengths=float(args.same_sheet_weld_body_lengths),
        contact_edge_scale=float(args.contact_edge_scale),
        opposed_normal_dot=float(args.opposed_normal_dot),
        max_dual_hops=int(args.max_dual_hops),
        min_cluster_faces=int(args.min_cluster_faces),
        max_cluster_face_fraction=float(args.max_cluster_face_fraction),
    )


def _settings_from_payload(payload: Mapping[str, Any]) -> CoilWeldDetectSettings:
    settings = payload.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("authored JSON is missing detect settings")
    return CoilWeldDetectSettings(
        same_sheet_weld_body_lengths=float(settings["sameSheetWeldBodyLengths"]),
        same_sheet_reference_body_lengths=float(settings["sameSheetReferenceBodyLengths"]),
        same_sheet_unique_rel_tol=float(settings["sameSheetUniqueRelTol"]),
        contact_edge_scale=float(settings["contactEdgeScale"]),
        opposed_normal_dot=float(settings["opposedNormalDot"]),
        max_dual_hops=int(settings["maxDualHops"]),
        min_cluster_faces=int(settings["minClusterFaces"]),
        max_cluster_face_fraction=float(settings["maxClusterFaceFraction"]),
    )


def render_detect_overlay(
    path: Path,
    verts: np.ndarray,
    faces: np.ndarray,
    result: CoilWeldDetectResult,
    sprite_path: Path,
) -> None:
    mesh = _render_cluster_mesh(verts, faces, result)
    sprite = Image.open(sprite_path).convert("RGBA")
    sprite_h = 900
    scale = sprite_h / max(sprite.size[1], 1)
    sprite = sprite.resize((max(1, int(sprite.size[0] * scale)), sprite_h), Image.Resampling.NEAREST)
    gap = 16
    legend_h = 80
    width = sprite.size[0] + gap + mesh.size[0]
    height = max(sprite.size[1], mesh.size[1]) + legend_h
    canvas = Image.new("RGB", (width, height), (18, 18, 22))
    canvas.paste(sprite.convert("RGB"), (0, 0), sprite)
    canvas.paste(mesh, (sprite.size[0] + gap, 0))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    draw.text(
        (12, height - 72),
        "Left: sprite. Right: proposed contact clusters. Author every cluster id as cut or keep.",
        fill=(230, 230, 230),
        font=font,
    )
    draw.text(
        (12, height - 52),
        f"clusters={len(result.clusters)} tinyIgnored={result.ignored_tiny_clusters} "
        f"weldedV={result.welded_vertex_count} geodesicHops={result.geodesic_diameter_hops}",
        fill=(200, 200, 200),
        font=font,
    )
    draw.text(
        (12, height - 32),
        "Cut coil-on-coil welds. Keep mouth, fins, horns, and scale grooves.",
        fill=(200, 200, 200),
        font=font,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def _render_cluster_mesh(
    verts: np.ndarray,
    faces: np.ndarray,
    result: CoilWeldDetectResult,
) -> Image.Image:
    points = np.asarray(verts, dtype=np.float64)
    triangles = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    extent = points.max(axis=0) - points.min(axis=0)
    axis_u, axis_v = (int(index) for index in np.argsort(extent)[::-1][:2])
    uv = np.stack((points[:, axis_u], points[:, axis_v]), axis=1)
    lo = uv.min(axis=0)
    span = uv.max(axis=0) - lo
    span[span < 1e-8] = 1.0
    width = height = 900
    margin = 48
    px = (uv - lo) / span
    xy = np.stack(
        (
            margin + px[:, 0] * (width - 2 * margin),
            height - margin - px[:, 1] * (height - 2 * margin),
        ),
        axis=1,
    )
    image = Image.new("RGB", (width, height), (24, 24, 28))
    draw = ImageDraw.Draw(image)
    palette = [
        (220, 70, 70),
        (70, 160, 230),
        (240, 200, 70),
        (80, 200, 120),
        (200, 90, 200),
        (240, 140, 60),
        (90, 220, 220),
        (180, 180, 180),
        (250, 120, 160),
        (120, 180, 80),
    ]
    face_cluster = np.full(int(triangles.shape[0]), -1, dtype=np.int32)
    for cluster in result.clusters:
        face_cluster[np.asarray(cluster.source_face_indices, dtype=np.int64)] = int(cluster.cluster_id)
    order = np.argsort(uv[triangles].mean(axis=1)[:, 1])
    for face_index in order.tolist():
        pts = [tuple(map(float, xy[int(vertex)])) for vertex in triangles[face_index]]
        cluster_id = int(face_cluster[face_index])
        fill = palette[cluster_id % len(palette)] if cluster_id >= 0 else (72, 72, 80)
        draw.polygon(pts, fill=fill)
    font = ImageFont.load_default()
    for cluster in result.clusters:
        centroid = xy[triangles[np.asarray(cluster.source_face_indices, dtype=np.int64)].reshape(-1)].mean(axis=0)
        draw.text((float(centroid[0]), float(centroid[1])), str(cluster.cluster_id), fill=(255, 255, 255), font=font)
    return image


def _assert_authorship_matches_detect(payload: Mapping[str, Any], result: CoilWeldDetectResult) -> None:
    recorded = payload.get("clusters")
    if not isinstance(recorded, list):
        raise ValueError("authored JSON is missing the detect cluster snapshot")
    if len(recorded) != len(result.clusters):
        raise ValueError(
            "authored cluster count does not match a fresh detect "
            f"({len(recorded)} vs {len(result.clusters)}); re-author from the current overlay"
        )
    for cluster, row in zip(result.clusters, recorded):
        if int(row["clusterId"]) != int(cluster.cluster_id):
            raise ValueError("authored cluster ids drifted from detect order")
        if int(row["faceCount"]) != int(cluster.face_count):
            raise ValueError(
                f"cluster {cluster.cluster_id} face count drifted "
                f"({row['faceCount']} vs {cluster.face_count})"
            )
        recorded_centroid = np.asarray(row["centroid"], dtype=np.float64).reshape(3)
        delta = float(np.linalg.norm(recorded_centroid - cluster.centroid))
        if delta > 1e-4 * result.body_extent:
            raise ValueError(
                f"cluster {cluster.cluster_id} centroid drifted by {delta:.6f}; re-author"
            )


def _cmd_detect(args: argparse.Namespace) -> int:
    src = _resolve(args.src).resolve()
    sprite = _resolve(args.sprite).resolve()
    out_dir = _resolve(args.out_dir).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"source GLB not found: {src}")
    if not sprite.is_file():
        raise FileNotFoundError(f"sprite not found: {sprite}")
    verts, faces, _attributes, _extras = load_glb_triangles(src)
    result = detect_coil_weld_clusters(verts, faces, _settings_from_args(args))
    out_dir.mkdir(parents=True, exist_ok=True)
    detect_path = out_dir / "coil_weld_detect.json"
    overlay_path = out_dir / "coil_weld_overlay.png"
    template_path = out_dir / "coil_weld_authored.template.json"
    payload = result.to_dict()
    payload["srcGlb"] = str(src).replace("\\", "/")
    payload["sprite"] = str(sprite).replace("\\", "/")
    detect_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    template = authorship_template(result, src_glb=payload["srcGlb"], sprite=payload["sprite"])
    template["settings"] = payload["settings"]
    template["clusters"] = [
        {
            "clusterId": cluster.cluster_id,
            "faceCount": cluster.face_count,
            "centroid": [float(axis) for axis in cluster.centroid],
            "tooLarge": cluster.too_large,
        }
        for cluster in result.clusters
    ]
    template_path.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    render_detect_overlay(overlay_path, verts, faces, result, sprite)
    print(
        json.dumps(
            {
                "ok": True,
                "command": "detect",
                "clusters": int(len(result.clusters)),
                "ignoredTinyClusters": int(result.ignored_tiny_clusters),
                "detect": str(detect_path),
                "overlay": str(overlay_path),
                "template": str(template_path),
                "geodesicDiameterHops": int(result.geodesic_diameter_hops),
            },
            indent=2,
        )
    )
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    src = _resolve(args.src).resolve()
    authored_path = _resolve(args.authored).resolve()
    out = _resolve(args.out).resolve()
    report_path = _resolve(args.report).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"source GLB not found: {src}")
    if not authored_path.is_file():
        raise FileNotFoundError(f"authored JSON not found: {authored_path}")
    payload = json.loads(authored_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("authored JSON must be an object")
    if payload.get("method") != AUTHORING_METHOD:
        raise ValueError(f"refusing to apply authorship method {payload.get('method')!r}")
    verts, faces, attributes, extras = load_glb_triangles(src)
    result = detect_coil_weld_clusters(verts, faces, _settings_from_payload(payload))
    _assert_authorship_matches_detect(payload, result)
    cut_faces = cut_source_faces_from_authorship(result, payload)
    out_verts, out_faces, out_attrs, cut_report = apply_coil_weld_cuts(
        verts,
        faces,
        cut_faces,
        attributes,
        min_largest_component_fraction=float(args.min_largest_component_fraction),
        same_sheet_weld_body_lengths=float(payload["settings"]["sameSheetWeldBodyLengths"]),
        same_sheet_reference_body_lengths=float(payload["settings"]["sameSheetReferenceBodyLengths"]),
        same_sheet_unique_rel_tol=float(payload["settings"]["sameSheetUniqueRelTol"]),
    )
    write_mesh_glb(
        out,
        out_verts,
        out_faces,
        out_attrs,
        source_doc=extras["doc"],
        source_blob=extras["blob"],
    )
    report = {
        "status": "pass",
        "method": AUTHORING_METHOD,
        "srcGlb": str(src).replace("\\", "/"),
        "authored": str(authored_path).replace("\\", "/"),
        "outputGlb": str(out).replace("\\", "/"),
        "skinStripped": True,
        "proof": "generated-artifact — coil-weld cut + overlay; not OE runtime",
        "detect": result.to_dict(),
        "apply": cut_report,
        "notes": payload.get("notes"),
        "bodyExtent": body_extent(out_verts),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "command": "apply", "output": str(out), "report": str(report_path)}, indent=2))
    return 0


def _add_detect_settings(parser: argparse.ArgumentParser) -> None:
    defaults = CoilWeldDetectSettings()
    parser.add_argument("--same-sheet-weld-body-lengths", type=float, default=defaults.same_sheet_weld_body_lengths)
    parser.add_argument("--contact-edge-scale", type=float, default=defaults.contact_edge_scale)
    parser.add_argument("--opposed-normal-dot", type=float, default=defaults.opposed_normal_dot)
    parser.add_argument("--max-dual-hops", type=int, default=defaults.max_dual_hops)
    parser.add_argument("--min-cluster-faces", type=int, default=defaults.min_cluster_faces)
    parser.add_argument("--max-cluster-face-fraction", type=float, default=defaults.max_cluster_face_fraction)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    detect = sub.add_parser("detect", help="Write overlay + authorship template")
    detect.add_argument("--src", required=True, type=Path)
    detect.add_argument("--sprite", required=True, type=Path)
    detect.add_argument("--out-dir", required=True, type=Path)
    _add_detect_settings(detect)
    detect.set_defaults(func=_cmd_detect)

    apply = sub.add_parser("apply", help="Cut authored clusters and write mesh+PBR GLB")
    apply.add_argument("--src", required=True, type=Path)
    apply.add_argument("--authored", required=True, type=Path)
    apply.add_argument("--out", required=True, type=Path)
    apply.add_argument("--report", required=True, type=Path)
    apply.add_argument("--min-largest-component-fraction", type=float, default=0.85)
    apply.set_defaults(func=_cmd_apply)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        raise
