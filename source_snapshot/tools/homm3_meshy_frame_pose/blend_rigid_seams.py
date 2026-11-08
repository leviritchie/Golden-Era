#!/usr/bin/env python3
"""Seam-blend + plate-expansion post-processor for the rigid-component crusader master.

The pure-rigid connected-component skin (weight 1.0 per vertex) keeps plates from
warping, but under the authored DEF poses islands anchored to different bones
separate: measured at the mouseover/idle pose, the Head island opens ~30cm from the
neck, RightArm ~21cm. This tool rewrites the master GLB's skin weights so every
non-trunk island blends a controlled fraction toward its parent bone (uniform per
island - the island stays rigid, only its attachment softens) and expands each
island slightly around its owning bone's joint origin so seam surfaces overlap.

Clips are rotation-only on the same bone hierarchy, so no clip or fit re-run is
needed: skinning is evaluated per frame from JOINTS/WEIGHTS + bone transforms.

Output is written in place (backup first). Values are patched in the existing BIN
chunk; all accessor offsets and types are preserved.
"""
from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
from pathlib import Path

import numpy as np


# parent bone name -> (blend toward parent, expansion factor around owner joint origin)
POLICY = {
    # Head/neck: the helmet island orbits the neck pivot under the DEF poses; 25% neck
    # pull + 12% expansion closes the measured 30cm head opening.
    "Head": ("neck", 0.25, 1.12),
    "neck": ("Spine02", 0.20, 1.08),
    "head_end": ("Head", 0.15, 1.0),
    # Arms: pauldron/arm plates open ~21cm from the torso under the sword poses.
    "LeftShoulder": ("Spine02", 0.18, 1.10),
    "RightShoulder": ("Spine02", 0.18, 1.10),
    "LeftArm": ("LeftShoulder", 0.22, 1.10),
    "RightArm": ("RightShoulder", 0.22, 1.10),
    "LeftForeArm": ("LeftArm", 0.18, 1.08),
    "RightForeArm": ("RightArm", 0.18, 1.08),
    "LeftHand": ("LeftForeArm", 0.15, 1.06),
    "RightHand": ("RightForeArm", 0.15, 1.06),
    # Legs.
    "LeftUpLeg": ("Hips", 0.18, 1.08),
    "RightUpLeg": ("Hips", 0.18, 1.08),
    "LeftLeg": ("LeftUpLeg", 0.15, 1.06),
    "RightLeg": ("RightUpLeg", 0.15, 1.06),
    "LeftFoot": ("LeftLeg", 0.12, 1.04),
    "RightFoot": ("RightLeg", 0.12, 1.04),
    "LeftToeBase": ("LeftFoot", 0.10, 1.0),
    "RightToeBase": ("RightFoot", 0.10, 1.0),
    # Blade stays stiff on the hand; only a tiny pull so it never reads as detached.
    "RightWeaponTip": ("RightHand", 0.06, 1.0),
}


def _read_glb(path: Path) -> tuple[dict, bytearray]:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError(f"not a GLB file: {path}")
    offset = 12
    json_doc = None
    bin_chunk = bytearray()
    chunks = []
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        start = offset + 8
        end = start + chunk_length
        if end > len(data):
            raise ValueError(f"truncated GLB chunk: {path}")
        if chunk_type == b"JSON":
            json_doc = json.loads(data[start:end].decode("utf-8").rstrip(" \t\r\n\x00"))
        elif chunk_type == b"BIN\x00":
            bin_chunk = bytearray(data[start:end])
        chunks.append((chunk_type, chunk_length, start))
        offset = end
    if json_doc is None:
        raise ValueError(f"GLB has no JSON chunk: {path}")
    return json_doc, bin_chunk


def _write_glb(path: Path, json_doc: dict, bin_chunk: bytes) -> None:
    json_bytes = json.dumps(json_doc, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    bin_bytes = bytes(bin_chunk)
    bin_bytes += b"\x00" * ((4 - len(bin_bytes) % 4) % 4)
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    out = bytearray()
    out += b"glTF"
    out += struct.pack("<II", 2, total)
    out += struct.pack("<I4s", len(json_bytes), b"JSON")
    out += json_bytes
    out += struct.pack("<I4s", len(bin_bytes), b"BIN\x00")
    out += bin_bytes
    path.write_bytes(bytes(out))


def _read_accessor(json_doc: dict, bin_chunk: bytearray, accessor_index: int) -> np.ndarray:
    acc = json_doc["accessors"][accessor_index]
    bv = json_doc["bufferViews"][acc["bufferView"]]
    comptype_to_np = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
    type_to_components = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
    dtype = np.dtype(comptype_to_np[acc["componentType"]])
    count = acc["count"] * type_to_components[acc["type"]]
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    nbytes = count * dtype.itemsize
    arr = np.frombuffer(bytes(bin_chunk[start: start + nbytes]), dtype=dtype).copy()
    if acc.get("normalized"):
        info = np.iinfo(dtype)
        arr = arr.astype(np.float32) / float(info.max)
    return arr


def _write_accessor(json_doc: dict, bin_chunk: bytearray, accessor_index: int, values: np.ndarray) -> None:
    acc = json_doc["accessors"][accessor_index]
    bv = json_doc["bufferViews"][acc["bufferView"]]
    comptype_to_np = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
    dtype = np.dtype(comptype_to_np[acc["componentType"]])
    if values.dtype != dtype:
        values = values.astype(dtype)
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    bin_chunk[start: start + values.nbytes] = values.tobytes()


def process(path: Path, backup: bool = True) -> dict:
    path = path.resolve()
    if backup:
        backup_path = path.with_name(path.stem + "_purerigid_backup.glb")
        shutil.copyfile(path, backup_path)

    json_doc, bin_chunk = _read_glb(path)
    nodes = json_doc["nodes"]
    parent_of = {}
    for i, node in enumerate(nodes):
        for child in node.get("children", []):
            parent_of[child] = i
    name_of = {i: (nodes[i].get("name") or f"node{i}") for i in range(len(nodes))}
    skin = json_doc["skins"][0]
    joints = skin["joints"]
    joint_index_of_node = {node_index: k for k, node_index in enumerate(joints)}

    mesh = json_doc["meshes"][0]
    prim = mesh["primitives"][0]
    attrs = prim["attributes"]
    positions = _read_accessor(json_doc, bin_chunk, attrs["POSITION"]).reshape(-1, 3).astype(np.float64)
    joint_ids = _read_accessor(json_doc, bin_chunk, attrs["JOINTS_0"]).astype(np.int64).reshape(-1, 4)
    weights = _read_accessor(json_doc, bin_chunk, attrs["WEIGHTS_0"]).reshape(-1, 4).astype(np.float64)

    if joint_ids.shape[1] < 2:
        raise ValueError("JOINTS_0 must have at least 2 columns for seam blending")
    if not np.allclose(weights.sum(axis=1), 1.0):
        raise ValueError("weights do not sum to 1; refusing to rewrite an unexpected sheet")

    # Joint origins in mesh space: node world position (root has identity TRS).
    world_positions = {}
    def _world_pos(i: int) -> np.ndarray:
        if i in world_positions:
            return world_positions[i]
        t = np.array(nodes[i].get("translation", [0.0, 0.0, 0.0]))
        p = parent_of.get(i)
        world_positions[i] = _world_pos(p) + t if p is not None else t
        return world_positions[i]
    for i in range(len(nodes)):
        _world_pos(i)

    changed_verts = 0
    applied = {}
    policy_by_node = {}
    for bone_name, (parent_name, blend, expansion) in POLICY.items():
        bone_node = next((i for i, n in enumerate(nodes) if n.get("name") == bone_name), None)
        parent_node = next((i for i, n in enumerate(nodes) if n.get("name") == parent_name), None)
        if bone_node is None or parent_node is None:
            raise ValueError(f"policy references missing node: {bone_name} -> {parent_name}")
        policy_by_node[bone_node] = (parent_node, blend, expansion)
        applied[bone_name] = {"parent": parent_name, "blend": blend, "expansion": expansion}

    owners = joint_ids[:, 0]
    for bone_node, (parent_node, blend, expansion) in policy_by_node.items():
        sel = owners == bone_node
        if not sel.any():
            continue
        parent_k = joint_index_of_node.get(parent_node)
        if parent_k is None:
            raise ValueError(f"parent {name_of[parent_node]} is not a skin joint")
        joint_ids[sel, 1] = parent_node
        weights[sel, 0] = 1.0 - blend
        weights[sel, 1] = blend
        if expansion != 1.0:
            origin = world_positions[bone_node]
            positions[sel] = origin + (positions[sel] - origin) * expansion
        changed_verts += int(sel.sum())

    _write_accessor(json_doc, bin_chunk, attrs["JOINTS_0"], joint_ids.astype(np.int64))
    _write_accessor(json_doc, bin_chunk, attrs["WEIGHTS_0"], weights)
    _write_accessor(json_doc, bin_chunk, attrs["POSITION"], positions)
    _write_glb(path, json_doc, bin_chunk)

    return {
        "source": str(path).replace("\\", "/"),
        "changedVerts": changed_verts,
        "totalVerts": len(owners),
        "applied": applied,
        "note": "seam blend + plate expansion; pure-rigid backup written alongside",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--glb", required=True, type=Path)
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()
    report = process(args.glb.resolve(), backup=not args.no_backup)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
