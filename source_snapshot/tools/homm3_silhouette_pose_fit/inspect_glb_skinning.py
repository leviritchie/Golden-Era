#!/usr/bin/env python3
"""Inspect GLB skinning and animation data without Blender.

Answers three delivery questions with numbers:

1. Bind consistency: does each skin joint's inverseBindMatrix match the node's
   world rest transform (rest == bind)? Any mismatch means a Unity importer will
   separate rigid armor islands even at rest.
2. Node scale: any non-identity or non-uniform node scales are a Unity-import
   hazard for SkinnedMeshRenderer bone rest poses.
3. Clip loop closure: for an animation GLB, how far is the last frame's bone
   rotation from the first frame's (a true cycle has ~0 delta), and how far is
   frame 0 from the bind pose (rigid islands separate by this much at clip start).
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np

MAT4 = np.float64


def _read_glb(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError(f"not a GLB file: {path}")
    offset = 12
    json_doc = None
    bin_chunk = b""
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        start = offset + 8
        end = start + chunk_length
        if end > len(data):
            raise ValueError(f"truncated GLB chunk: {path}")
        if chunk_type == b"JSON":
            json_doc = json.loads(data[start:end].decode("utf-8").rstrip(" \t\r\n\x00"))
        elif chunk_type == b"BIN\x00":
            bin_chunk = data[start:end]
        offset = end
    if json_doc is None:
        raise ValueError(f"GLB has no JSON chunk: {path}")
    return {"json": json_doc, "bin": bin_chunk}


def _accessor(doc: dict, bin_chunk: bytes, accessor_index: int) -> np.ndarray:
    json_doc = doc["json"]
    acc = json_doc["accessors"][accessor_index]
    bv = json_doc["bufferViews"][acc["bufferView"]]
    component_type = acc["componentType"]
    comptype_to_np = {
        5120: np.int8, 5121: np.uint8, 5122: np.int16,
        5123: np.uint16, 5125: np.uint32, 5126: np.float32,
    }
    type_to_components = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
    dtype = np.dtype(comptype_to_np[component_type])
    count = acc["count"] * type_to_components[acc["type"]]
    if "byteStride" in bv and bv["byteStride"]:
        itemsize = dtype.itemsize
        stride = bv["byteStride"]
        raw = bin_chunk[bv["byteOffset"]: bv["byteOffset"] + stride * count]
        out = np.zeros((count,), dtype=dtype)
        for i in range(count):
            out[i] = np.frombuffer(raw[i * stride: i * stride + itemsize], dtype=dtype)[0]
    else:
        start = bv.get("byteOffset", 0)
        nbytes = count * dtype.itemsize
        out = np.frombuffer(bin_chunk[start: start + nbytes], dtype=dtype).copy()
    if acc.get("normalized"):
        info = np.iinfo(dtype)
        out = out.astype(np.float32) / float(info.max if not np.issubdtype(dtype, np.signedinteger) else max(-info.min, info.max))
    return out




def _compose_matrix(t: np.ndarray, r: np.ndarray, s: np.ndarray) -> np.ndarray:
    qx, qy, qz, qw = r
    m = np.eye(4, dtype=MAT4)
    m[0, 0] = 1 - 2 * (qy * qy + qz * qz)
    m[0, 1] = 2 * (qx * qy - qz * qw)
    m[0, 2] = 2 * (qx * qz + qy * qw)
    m[1, 0] = 2 * (qx * qy + qz * qw)
    m[1, 1] = 1 - 2 * (qx * qx + qz * qz)
    m[1, 2] = 2 * (qy * qz - qx * qw)
    m[2, 0] = 2 * (qx * qz - qy * qw)
    m[2, 1] = 2 * (qy * qz + qx * qw)
    m[2, 2] = 1 - 2 * (qx * qx + qy * qy)
    m[:3, 3] = t
    m[0, 0] *= s[0]; m[0, 1] *= s[1]; m[0, 2] *= s[2]
    m[1, 0] *= s[0]; m[1, 1] *= s[1]; m[1, 2] *= s[2]
    m[2, 0] *= s[0]; m[2, 1] *= s[1]; m[2, 2] *= s[2]
    return m


def _node_matrix(doc: dict, node_index: int) -> np.ndarray:
    node = doc["json"]["nodes"][node_index]
    t = np.array(node.get("translation", [0.0, 0.0, 0.0]), dtype=MAT4)
    r = np.array(node.get("rotation", [0.0, 0.0, 0.0, 1.0]), dtype=MAT4)
    s = np.array(node.get("scale", [1.0, 1.0, 1.0]), dtype=MAT4)
    return _compose_matrix(t, r, s)


def _world_matrix(doc: dict, node_index: int, cache: dict) -> np.ndarray:
    if node_index in cache:
        return cache[node_index]
    local = _node_matrix(doc, node_index)
    node = doc["json"]["nodes"][node_index]
    parents = [i for i, n in enumerate(doc["json"]["nodes"]) if node_index in n.get("children", [])]
    if parents:
        world = _world_matrix(doc, parents[0], cache) @ local
    else:
        world = local
    cache[node_index] = world
    return world


def _quat_from_matrix(m: np.ndarray) -> np.ndarray:
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        q = np.array([(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s,
                      (m[1, 0] - m[0, 1]) / s, s / 4.0])
    else:
        i = int(np.argmax(np.diag(m)[:3]))
        j = (i + 1) % 3
        k = (j + 1) % 3
        s = np.sqrt(max(0.0, m[i, i] - m[j, j] - m[k, k] + 1.0)) * 2
        q = np.zeros(4)
        q[i] = s / 4.0
        q[3] = (m[k, j] - m[j, k]) / s
        q[j] = (m[j, i] + m[i, j]) / s
        q[k] = (m[k, i] + m[i, k]) / s
    q /= np.linalg.norm(q)
    return q


def _quat_delta_deg(qa: np.ndarray, qb: np.ndarray) -> float:
    dot = abs(float(np.dot(qa, qb)))
    return float(np.degrees(2.0 * np.arccos(np.clip(dot, -1.0, 1.0))))


def _skin_report(doc: dict, bin_chunk: bytes) -> dict:
    json_doc = doc["json"]
    skins = json_doc.get("skins", [])
    nodes = json_doc.get("nodes", [])
    reports = []
    for skin_index, skin in enumerate(skins):
        joints = skin.get("joints", [])
        ibm = None
        if "inverseBindMatrices" in skin:
            raw = _accessor(doc, bin_chunk, skin["inverseBindMatrices"])
            ibm = raw.reshape(-1, 4, 4)
        cache: dict = {}
        joint_rows = []
        for j, joint_index in enumerate(joints):
            node = nodes[joint_index]
            name = node.get("name") or f"node{joint_index}"
            local = _node_matrix(doc, joint_index)
            world = _world_matrix(doc, joint_index, cache)
            s = node.get("scale", [1.0, 1.0, 1.0])
            scale = np.array(s, dtype=MAT4)
            nonuniform = not np.allclose(scale, scale[0]) or not np.allclose(scale, 1.0)
            rest_ok = None
            rest_dev = None
            if ibm is not None and j < len(ibm):
                expected = np.linalg.inv(world)
                # GLB stores matrices column-major; the raw read is row-major, so
                # transpose the raw form before comparing against the row-major
                # world matrix computed here.
                rest_dev = float(np.max(np.abs(ibm[j].T - expected)))
                rest_ok = rest_dev < 1e-3
            joint_rows.append({
                "joint": joint_index,
                "name": name,
                "scale": [round(float(v), 6) for v in scale],
                "nonIdentityScale": not np.allclose(scale, 1.0),
                "nonUniformScale": bool(nonuniform),
                "bindMatchesRest": rest_ok,
                "bindMaxAbsDev": None if rest_dev is None else round(rest_dev, 6),
            })
        reports.append({
            "skin": skin_index,
            "jointCount": len(joints),
            "joints": joint_rows,
            "hasInverseBindMatrices": ibm is not None,
        })
    return {"skins": reports}


def _weights_report(doc: dict, bin_chunk: bytes) -> dict:
    json_doc = doc["json"]
    meshes = json_doc.get("meshes", [])
    rows = []
    for mesh_index, mesh in enumerate(meshes):
        for prim in mesh.get("primitives", []):
            attrs = prim.get("attributes", {})
            if "JOINTS_0" not in attrs or "WEIGHTS_0" not in attrs:
                continue
            joints = _accessor(doc, bin_chunk, attrs["JOINTS_0"]).astype(np.int32).reshape(-1, 4)
            weights = _accessor(doc, bin_chunk, attrs["WEIGHTS_0"]).reshape(-1, 4)
            maxw = weights.max(axis=1)
            rigid = float((maxw >= 0.999).mean())
            rows.append({
                "mesh": mesh_index,
                "name": mesh.get("name"),
                "vertexCount": int(len(weights)),
                "maxWeightMean": round(float(maxw.mean()), 4),
                "rigidFraction": round(rigid, 4),
                "multiBoneVerts": int((weights > 0.01).sum(axis=1).clip(max=4).max()),
            })
    return {"meshes": rows}


def _clip_report(doc: dict, bin_chunk: bytes) -> dict:
    json_doc = doc["json"]
    anims = json_doc.get("animations", [])
    nodes = json_doc.get("nodes", [])
    if not anims:
        return {"animations": []}
    cache: dict = {}
    bind_quats = {}
    for i, node in enumerate(nodes):
        bind_quats[i] = _quat_from_matrix(_world_matrix(doc, i, cache))
    rows = []
    for anim in anims:
        channel_rows = []
        quat_curves = {}
        for channel in anim.get("channels", []):
            sampler = anim["samplers"][channel["sampler"]]
            target = channel["target"]
            if target.get("path") != "rotation":
                continue
            input_acc = _accessor(doc, bin_chunk, sampler["input"])
            output_acc = _accessor(doc, bin_chunk, sampler["output"]).reshape(-1, 4)
            quat_curves.setdefault(target["node"], []).append((input_acc, output_acc))
        for node_index, curves in quat_curves.items():
            name = nodes[node_index].get("name") or f"node{node_index}"
            for input_acc, output_acc in curves:
                first = output_acc[0]
                last = output_acc[-1]
                bind_q = bind_quats.get(node_index)
                channel_rows.append({
                    "node": node_index,
                    "name": name,
                    "frames": int(len(input_acc)),
                    "duration": round(float(input_acc[-1]), 4),
                    "loopClosureDeg": round(_quat_delta_deg(first, last), 2),
                    "frame0VsBindDeg": None if bind_q is None else round(_quat_delta_deg(first, bind_q), 2),
                })
        if not channel_rows:
            continue
        rows.append({
            "animation": anim.get("name") or f"anim{anims.index(anim)}",
            "duration": round(float(max(r["duration"] for r in channel_rows)), 4),
            "rotatedBoneCount": len(channel_rows),
            "loopClosureMaxDeg": round(max(r["loopClosureDeg"] for r in channel_rows), 2),
            "loopClosureMeanDeg": round(sum(r["loopClosureDeg"] for r in channel_rows) / len(channel_rows), 2),
            "frame0VsBindMaxDeg": round(max(r["frame0VsBindDeg"] for r in channel_rows if r["frame0VsBindDeg"] is not None), 2),
            "frame0VsBindMeanDeg": round(sum(r["frame0VsBindDeg"] for r in channel_rows if r["frame0VsBindDeg"] is not None) / len(channel_rows), 2),
            "worstBones": sorted(channel_rows, key=lambda r: r["loopClosureDeg"], reverse=True)[:5],
        })
    return {"animations": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--glb", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    doc = _read_glb(args.glb.resolve())
    report = {
        "source": str(args.glb.resolve()).replace("\\", "/"),
        "nodeCount": len(doc["json"].get("nodes", [])),
        "animationCount": len(doc["json"].get("animations", [])),
        "skin": _skin_report(doc, doc["bin"]),
        "weights": _weights_report(doc, doc["bin"]),
        "clips": _clip_report(doc, doc["bin"]),
    }
    if args.out:
        args.out.resolve().parent.mkdir(parents=True, exist_ok=True)
        args.out.resolve().write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
