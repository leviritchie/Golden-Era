#!/usr/bin/env python3
"""Audit triangle-level ownership in an owned GLB.

This is deliberately stricter than a bind-pose joint audit: every vertex must
have a clear owner, every triangle must be single-owner for rigid skin, and
each disconnected component is reported with its assigned bone and bounds.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import bpy


def _args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    return ap.parse_args(argv)


def _components(mesh):
    parent = list(range(len(mesh.data.vertices)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for poly in mesh.data.polygons:
        if len(poly.vertices) < 2:
            continue
        first = poly.vertices[0]
        for vi in poly.vertices[1:]:
            union(first, vi)
    out = defaultdict(list)
    for vi in range(len(mesh.data.vertices)):
        out[find(vi)].append(vi)
    return out


def main() -> int:
    args = _args()
    master = args.master.resolve()
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(master))
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    groups = {g.index: g.name for g in mesh.vertex_groups}
    bones = []
    for bone in arm.pose.bones:
        head = arm.matrix_world @ bone.head
        tail = arm.matrix_world @ bone.tail
        bones.append((bone.name, head, tail))

    def bone_distance(point, head, tail):
        seg = tail - head
        if seg.length_squared < 1e-12:
            return float((point - head).length)
        t = max(0.0, min(1.0, float((point - head).dot(seg) / seg.length_squared)))
        return float((point - (head + seg * t)).length)
    owner_by_vertex = {}
    ambiguous = []
    unowned = []
    for v in mesh.data.vertices:
        weights = sorted(
            ((groups.get(g.group, f"group_{g.group}"), float(g.weight)) for g in v.groups),
            key=lambda x: x[1],
            reverse=True,
        )
        if not weights:
            unowned.append(v.index)
            continue
        owner_by_vertex[v.index] = weights[0][0]
        if len(weights) > 1 and weights[1][1] > 0.05:
            ambiguous.append({"vertex": v.index, "weights": weights[:4]})

    component_rows = []
    for ci, indices in enumerate(_components(mesh).values()):
        owners = Counter(owner_by_vertex.get(vi, "UNOWNED") for vi in indices)
        points = [mesh.matrix_world @ mesh.data.vertices[vi].co for vi in indices]
        center = sum(points, points[0] * 0.0) / len(points)
        candidates = sorted(
            (bone_distance(center, head, tail), name)
            for name, head, tail in bones
        )
        assigned_owner = owners.most_common(1)[0][0]
        component_rows.append(
            {
                "component": ci,
                "vertices": len(indices),
                "triangles": sum(1 for p in mesh.data.polygons if any(vi in indices for vi in p.vertices)),
                "owners": dict(owners),
                "assignedOwner": assigned_owner,
                "nearestBone": candidates[0][1],
                "nearestBoneDistance": candidates[0][0],
                "nearestDistanceGap": candidates[1][0] - candidates[0][0],
                "ownerMatchesNearest": assigned_owner == candidates[0][1],
                "bounds": {
                    "min": [min(p[i] for p in points) for i in range(3)],
                    "max": [max(p[i] for p in points) for i in range(3)],
                },
            }
        )

    mixed_triangles = []
    triangle_owner_counts = Counter()
    for poly in mesh.data.polygons:
        owners = sorted({owner_by_vertex.get(vi, "UNOWNED") for vi in poly.vertices})
        if len(owners) != 1:
            mixed_triangles.append({"polygon": poly.index, "owners": owners, "vertices": list(poly.vertices)})
        triangle_owner_counts[owners[0] if len(owners) == 1 else "MIXED"] += 1

    report = {
        "ok": not unowned and not ambiguous and not mixed_triangles,
        "master": str(master).replace("\\", "/"),
        "mesh": mesh.name,
        "armature": arm.name,
        "vertexCount": len(mesh.data.vertices),
        "triangleCount": len(mesh.data.polygons),
        "boneCount": len(arm.data.bones),
        "vertexGroups": sorted(groups.values()),
        "unownedVertices": unowned,
        "ambiguousVertices": ambiguous,
        "mixedTriangles": mixed_triangles,
        "triangleOwnerCounts": dict(triangle_owner_counts),
        "components": component_rows,
        "componentOwnerMismatches": [
            row for row in component_rows if not row["ownerMatchesNearest"]
        ],
        "proof": "generated artifact skin ownership audit; not OE runtime",
    }
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": report["ok"],
        "vertices": report["vertexCount"],
        "triangles": report["triangleCount"],
        "components": len(component_rows),
        "unowned": len(unowned),
        "ambiguous": len(ambiguous),
        "mixedTriangles": len(mixed_triangles),
        "report": str(out).replace("\\", "/"),
    }, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
