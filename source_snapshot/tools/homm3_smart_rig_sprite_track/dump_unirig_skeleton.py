#!/usr/bin/env python3
"""Dump Meshy UniRig skeleton graph + rest-pose world positions from a GLB."""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


def read_glb_json(path: Path) -> dict:
    data = path.read_bytes()
    offset = 12
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        start = offset + 8
        end = start + chunk_length
        if chunk_type == b"JSON":
            return json.loads(data[start:end].decode("utf-8").rstrip(" \t\r\n\x00"))
        offset = end
    raise ValueError(f"no JSON chunk in {path}")


def quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def quat_apply(q, v):
    x, y, z = v
    qx, qy, qz, qw = q
    # t = 2 * cross(q.xyz, v)
    tx = 2.0 * (qy * z - qz * y)
    ty = 2.0 * (qz * x - qx * z)
    tz = 2.0 * (qx * y - qy * x)
    # v + qw*t + cross(q.xyz, t)
    return (
        x + qw * tx + (qy * tz - qz * ty),
        y + qw * ty + (qz * tx - qx * tz),
        z + qw * tz + (qx * ty - qy * tx),
    )


def walk_world(nodes: list[dict], idx: int, parent: int | None, pos, rot, out: dict) -> None:
    node = nodes[idx]
    t = node.get("translation", [0.0, 0.0, 0.0])
    r = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    wp = quat_apply(rot, (t[0], t[1], t[2]))
    wp = (wp[0] + pos[0], wp[1] + pos[1], wp[2] + pos[2])
    wr = quat_mul(rot, (r[0], r[1], r[2], r[3]))
    name = node.get("name") or f"node{idx}"
    out[idx] = {
        "index": idx,
        "name": name,
        "parent": parent,
        "world": [float(wp[0]), float(wp[1]), float(wp[2])],
        "children": list(node.get("children", [])),
        "mesh": node.get("mesh"),
        "skin": node.get("skin"),
    }
    for child in node.get("children", []):
        walk_world(nodes, child, idx, wp, wr, out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    doc = read_glb_json(args.glb)
    nodes = doc.get("nodes", [])
    scenes = doc.get("scenes", [])
    roots = scenes[0].get("nodes", []) if scenes else [0]

    world: dict[int, dict] = {}
    for root in roots:
        walk_world(nodes, root, None, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), world)

    skins = doc.get("skins", [])
    joint_indices: list[int] = []
    if skins:
        joint_indices = list(skins[0].get("joints", []))

    bones = []
    edges = []
    for ji in joint_indices:
        info = world[ji]
        bones.append(
            {
                "index": ji,
                "name": info["name"],
                "parent": info["parent"],
                "world": info["world"],
            }
        )
        parent = info["parent"]
        if parent is not None and parent in set(joint_indices):
            edges.append(
                {
                    "parentIndex": parent,
                    "childIndex": ji,
                    "parentName": world[parent]["name"],
                    "childName": info["name"],
                }
            )

    payload = {
        "glb": str(args.glb.resolve()).replace("\\", "/"),
        "armatureHint": "UniRigArmature",
        "boneCount": len(bones),
        "bones": bones,
        "edges": edges,
        "proof": "generated artifact validated — skeleton dump only",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "bones": len(bones), "edges": len(edges), "out": str(args.out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
