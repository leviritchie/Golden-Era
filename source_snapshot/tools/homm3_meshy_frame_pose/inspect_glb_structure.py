#!/usr/bin/env python3
"""Inspect the structural JSON of a GLB without importing it into Blender.

This distinguishes source scene-graph structure from viewer-generated overlays.
It intentionally reports nodes, meshes, primitives, vertex attributes, and
metadata only; it does not infer semantic part names from geometry.
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


def _read_json_chunk(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError(f"not a GLB file: {path}")
    version, total_length = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise ValueError(f"unsupported GLB version {version}: {path}")
    if total_length != len(data):
        raise ValueError(f"GLB length header mismatch: {path}")
    offset = 12
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        start = offset + 8
        end = start + chunk_length
        if end > len(data):
            raise ValueError(f"truncated GLB chunk: {path}")
        if chunk_type == b"JSON":
            return json.loads(data[start:end].decode("utf-8").rstrip(" \t\r\n\x00"))
        offset = end
    raise ValueError(f"GLB has no JSON chunk: {path}")


def inspect(path: Path) -> dict:
    doc = _read_json_chunk(path)
    nodes = doc.get("nodes", [])
    meshes = doc.get("meshes", [])
    materials = doc.get("materials", [])
    node_rows = [
        {
            "index": index,
            "name": node.get("name"),
            "mesh": node.get("mesh"),
            "skin": node.get("skin"),
            "children": node.get("children", []),
            "hasExtras": bool(node.get("extras")),
        }
        for index, node in enumerate(nodes)
    ]
    mesh_rows = []
    attributes = set()
    for index, mesh in enumerate(meshes):
        primitives = []
        for primitive_index, primitive in enumerate(mesh.get("primitives", [])):
            names = sorted(primitive.get("attributes", {}).keys())
            attributes.update(names)
            primitives.append(
                {
                    "index": primitive_index,
                    "mode": primitive.get("mode"),
                    "material": primitive.get("material"),
                    "attributes": names,
                    "hasTargets": bool(primitive.get("targets")),
                }
            )
        mesh_rows.append({"index": index, "name": mesh.get("name"), "primitives": primitives})
    return {
        "schema": "glb_structure_inspection.v1",
        "source": str(path.resolve()).replace("\\", "/"),
        "sceneCount": len(doc.get("scenes", [])),
        "rootScene": doc.get("scene"),
        "nodeCount": len(nodes),
        "meshCount": len(meshes),
        "primitiveCount": sum(len(mesh.get("primitives", [])) for mesh in meshes),
        "materialCount": len(materials),
        "skinCount": len(doc.get("skins", [])),
        "hasNodeExtras": any(bool(node.get("extras")) for node in nodes),
        "hasMeshExtras": any(bool(mesh.get("extras")) for mesh in meshes),
        "hasMaterialExtras": any(bool(material.get("extras")) for material in materials),
        "vertexAttributes": sorted(attributes),
        "hasSemanticVertexColors": "COLOR_0" in attributes,
        "nodes": node_rows,
        "meshes": mesh_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--glb", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = inspect(args.glb.resolve())
    if args.out:
        args.out.resolve().parent.mkdir(parents=True, exist_ok=True)
        args.out.resolve().write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
