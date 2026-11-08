#!/usr/bin/env python3
"""Bake the vanilla ecz facing convention into the crusader delivery GLBs.

Measured in combat (Homm3BattleAttackFacingHook skinnedDelta): vanilla points the
orientation root (cfkt -> our prefab root) at enemyDir - 90 degrees and expects the
mesh content to carry a +90 degree yaw bake (vanilla unit meshes do). Our mesh has
no bake, so the crusader faced 90 degrees left of the enemy.

IMPORTANT (verified in the imported prefab, 2026-08-10): the Unity glTF importer
flips the sign of Y rotations (right-handed -> left-handed conversion). A +90 yaw
written into the GLB imports as -90 in Unity, which made the crusader face exactly
backwards (the facing diag marker, being Unity-side, reported +90 and looked fine).
So this tool writes -90 yaw into the GLB so Unity imports +90.

Fix: insert (or rewrite) an 'Orientation' group node (rotation -90 glTF yaw, i.e.
+90 Unity yaw) between the scene root and the skeleton root. The SkinnedMeshRenderer
stays on its own mesh node under the root (case A), so the deformation carries a
constant +90 degree offset in the Unity root-local frame while the bone animation is
preserved (world*IBM math unchanged: root*Orient*(Jb*Ja*Jb^-1)*root^-1).

Applied to the master GLB and every delivery clip GLB so the rebased Unity clip
paths ('Orientation/Hips/...') match the prefab hierarchy. The lane marker in the
lab prefab is set to the same Unity-side +90 so Homm3ImportVisuals target-facing
stays consistent.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

ROTATION_MINUS_90_YAW = [0.0, -0.7071067811865476, 0.0, 0.7071067811865476]


def _read_json(path: Path) -> dict:
    data = path.read_bytes()
    offset = 12
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        start = offset + 8
        if chunk_type == b"JSON":
            return json.loads(data[start:start + chunk_length].decode("utf-8").rstrip(" \t\r\n\x00"))
        offset = start + chunk_length
    raise ValueError(f"no JSON chunk: {path}")


def _write_json(path: Path, doc: dict) -> None:
    data = path.read_bytes()
    # Locate the BIN chunk and keep it verbatim.
    bin_chunk = b""
    offset = 12
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        start = offset + 8
        if chunk_type == b"BIN\x00":
            bin_chunk = data[start:start + chunk_length]
        offset = start + chunk_length
    json_bytes = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    bin_bytes = bin_chunk + b"\x00" * ((4 - len(bin_chunk) % 4) % 4)
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    out = bytearray()
    out += b"glTF"
    out += struct.pack("<II", 2, total)
    out += struct.pack("<I4s", len(json_bytes), b"JSON")
    out += json_bytes
    out += struct.pack("<I4s", len(bin_bytes), b"BIN\x00")
    out += bin_bytes
    path.write_bytes(bytes(out))


def process(path: Path, rewrite: bool = False) -> dict:
    doc = _read_json(path)
    nodes = doc["nodes"]
    root_index = doc["scenes"][0]["nodes"][0]
    root = nodes[root_index]
    existing = next((i for i, n in enumerate(nodes) if n.get("name") == "Orientation"), None)
    if existing is not None:
        if not rewrite:
            return {"source": str(path), "status": "already has Orientation; pass --rewrite to set the -90 glTF yaw"}
        nodes[existing]["rotation"] = ROTATION_MINUS_90_YAW
        _write_json(path, doc)
        return {"source": str(path), "status": "rewrote Orientation to -90 glTF yaw (imports as +90 Unity)"}
    children = list(root.get("children", []))
    # The mesh node carries mesh/skin; the skeleton root is the other child (Hips).
    mesh_node = next((c for c in children if nodes[c].get("mesh") is not None), None)
    skeleton_root = next((c for c in children if c != mesh_node), None)
    if skeleton_root is None:
        raise ValueError(f"no skeleton root child found under {nodes[root_index].get('name')}: {children}")
    orientation_index = len(nodes)
    nodes.append({
        "name": "Orientation",
        "rotation": ROTATION_MINUS_90_YAW,
        "children": [skeleton_root],
    })
    remaining = [c for c in children if c != skeleton_root]
    root["children"] = remaining + [orientation_index]
    _write_json(path, doc)
    return {
        "source": str(path).replace("\\", "/"),
        "root": nodes[root_index].get("name"),
        "skeletonRoot": nodes[skeleton_root].get("name"),
        "orientationNode": orientation_index,
        "rotationYawDeg": -90.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--glb", required=True, type=Path, action="append")
    parser.add_argument("--rewrite", action="store_true", help="update the yaw sign of an existing Orientation node")
    args = parser.parse_args()
    reports = [process(p.resolve(), rewrite=args.rewrite) for p in args.glb]
    print(json.dumps(reports, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
