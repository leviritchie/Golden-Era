#!/usr/bin/env python3
"""Dump the owned-bind GLB node tree with world transforms, focusing on the
head/nose/weapon sites to determine the model's authored forward direction."""
import json
import struct
import sys

def read_json_chunk(path):
    data = path.read_bytes()
    version, total_length = struct.unpack_from("<II", data, 4)
    offset = 12
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        start = offset + 8
        end = start + chunk_length
        if chunk_type == b"JSON":
            return json.loads(data[start:end].decode("utf-8").rstrip(" \t\r\n\x00"))
        offset = end
    raise ValueError("no JSON chunk")

def quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )

def quat_conj(q):
    return (-q[0], -q[1], -q[2], q[3])

def quat_apply(q, v):
    qv = (v[0], v[1], v[2], 0.0)
    qc = quat_conj(q)
    t = quat_mul(q, qv)
    r = quat_mul(t, qc)
    return (r[0], r[1], r[2])

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("usage: dump_glb_nodes.py <file.glb>")
        return 1
    doc = read_json_chunk(__import__("pathlib").Path(path))
    nodes = doc.get("nodes", [])
    scenes = doc.get("scenes", [])
    roots = scenes[0].get("nodes", []) if scenes else [0]

    world_pos = {}
    world_rot = {}
    def walk(idx, parent, pos, rot):
        node = nodes[idx]
        t = node.get("translation", [0.0, 0.0, 0.0])
        r = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
        local_pos = (t[0], t[1], t[2])
        local_rot = (r[0], r[1], r[2], r[3])
        wp = quat_apply(rot, local_pos)
        wp = (wp[0] + pos[0], wp[1] + pos[1], wp[2] + pos[2])
        wr = quat_mul(rot, local_rot)
        world_pos[idx] = wp
        world_rot[idx] = wr
        mesh = node.get("mesh", -1)
        skin = node.get("skin", -1)
        name = node.get("name") or f"node{idx}"
        print(f"{idx:3d} parent={parent!s:>4} mesh={mesh!s:>3} skin={skin!s:>3} pos=({wp[0]:8.4f},{wp[1]:8.4f},{wp[2]:8.4f}) name={name}")
        for child in node.get("children", []):
            walk(child, idx, wp, wr)

    for root in roots:
        walk(root, None, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
    return 0

if __name__ == "__main__":
    sys.exit(main())
