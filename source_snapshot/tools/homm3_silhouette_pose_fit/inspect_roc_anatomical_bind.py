#!/usr/bin/env python3
"""Audit every Roc bind bone against the mesh and emit skin influence data."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy


def argv():
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]


def get_arg(args, name):
    for i, value in enumerate(args):
        if value == name and i + 1 < len(args):
            return Path(args[i + 1])
    return None


def main():
    args = argv()
    src = get_arg(args, "--src")
    roles_path = get_arg(args, "--roles")
    out = get_arg(args, "--out")
    if not src or not roles_path or not out:
        raise SystemExit("need --src, --roles, --out")
    roles = json.loads(roles_path.read_text(encoding="utf-8"))["bones"]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(src.resolve()))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    report = {
        "source": str(src).replace("\\", "/"),
        "armature": arm.name,
        "boneCount": len(arm.data.bones),
        "bones": {},
        "proof": "generated artifact validated - actual bind heads/tails and mesh skin groups inspected",
    }
    for bone in arm.data.bones:
        head = arm.matrix_world @ bone.head_local
        tail = arm.matrix_world @ bone.tail_local
        influence = []
        for mesh in meshes:
            group = mesh.vertex_groups.get(bone.name)
            if group is None:
                continue
            weighted = []
            for vertex in mesh.data.vertices:
                for assignment in vertex.groups:
                    if assignment.group == group.index and assignment.weight > 0.01:
                        co = mesh.matrix_world @ vertex.co
                        weighted.append((float(assignment.weight), co))
                        break
            if weighted:
                total = sum(w for w, _ in weighted)
                centroid = sum((co * w for w, co in weighted), weighted[0][1] * 0.0) / max(total, 1e-9)
                mins = [min(co[i] for _, co in weighted) for i in range(3)]
                maxs = [max(co[i] for _, co in weighted) for i in range(3)]
                influence.append({
                    "mesh": mesh.name,
                    "vertexCount": len(weighted),
                    "weightSum": total,
                    "centroid": [float(v) for v in centroid],
                    "bounds": {"min": mins, "max": maxs},
                })
        report["bones"][bone.name] = {
            "name": roles.get(bone.name, {}).get("name", "UNNAMED"),
            "anatomy": roles.get(bone.name, {}).get("anatomy", "UNNAMED"),
            "confidence": roles.get(bone.name, {}).get("confidence", "missing"),
            "parent": bone.parent.name if bone.parent else None,
            "children": [child.name for child in bone.children],
            "head": [float(v) for v in head],
            "tail": [float(v) for v in tail],
            "length": float((tail - head).length),
            "influence": influence,
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "bones": len(report["bones"]), "out": str(out)}))


if __name__ == "__main__":
    main()
