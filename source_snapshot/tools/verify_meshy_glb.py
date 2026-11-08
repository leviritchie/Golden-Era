#!/usr/bin/env python3
"""Quick GLB sanity check: verts > 0, exactly 1 skin, joints present."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path


def load_glb(path: Path) -> dict:
    data = path.read_bytes()
    if data[:4] != b"glTF":
        raise ValueError("not glb")
    off = 12
    gltf = None
    while off < len(data):
        chunk_len, chunk_type = struct.unpack_from("<II", data, off)
        off += 8
        chunk = data[off : off + chunk_len]
        off += chunk_len
        if chunk_type == 0x4E4F534A:  # JSON
            gltf = json.loads(chunk.decode("utf-8"))
    if gltf is None:
        raise ValueError("no json chunk")
    return gltf


def verify(path: Path) -> dict:
    gltf = load_glb(path)
    meshes = gltf.get("meshes") or []
    accessors = gltf.get("accessors") or []
    skins = gltf.get("skins") or []
    nodes = gltf.get("nodes") or []
    vert_count = 0
    for mesh in meshes:
        for prim in mesh.get("primitives") or []:
            pos = prim.get("attributes", {}).get("POSITION")
            if pos is not None:
                vert_count += accessors[pos].get("count", 0)
    joint_nodes = set()
    for skin in skins:
        for j in skin.get("joints") or []:
            joint_nodes.add(j)
    return {
        "path": str(path),
        "vertices": vert_count,
        "meshes": len(meshes),
        "skins": len(skins),
        "joints": len(joint_nodes),
        "nodes": len(nodes),
        "ok": vert_count > 0 and len(skins) == 1 and len(joint_nodes) > 0,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: verify_meshy_glb.py <glb> [dest]")
        return 2
    src = Path(sys.argv[1])
    rep = verify(src)
    print(json.dumps(rep, indent=2))
    if not rep["ok"]:
        return 1
    if len(sys.argv) >= 3:
        dest = Path(sys.argv[2])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        print(f"copied -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
