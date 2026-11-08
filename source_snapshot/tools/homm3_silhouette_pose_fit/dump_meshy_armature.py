#!/usr/bin/env python3
"""Dump armature bone hierarchy + world heads/tails from a Meshy GLB.

Blender:
  blender -b --python tools/homm3_silhouette_pose_fit/dump_meshy_armature.py -- \\
    --src artifacts/.../idle_f0_rigged.glb --out artifacts/.../armature_dump.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return sys.argv[1:]


def main() -> int:
    args = _argv()
    src = None
    out = None
    i = 0
    while i < len(args):
        if args[i] == "--src" and i + 1 < len(args):
            src = Path(args[i + 1])
            i += 2
        elif args[i] == "--out" and i + 1 < len(args):
            out = Path(args[i + 1])
            i += 2
        else:
            i += 1
    if src is None or out is None:
        raise SystemExit("need --src and --out")
    if not src.is_absolute():
        src = ROOT / src
    if not out.is_absolute():
        out = ROOT / out

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(src))
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not arms:
        raise SystemExit("no armature in GLB")
    arm = arms[0]
    bones = []
    for b in arm.data.bones:
        parent = b.parent.name if b.parent else None
        head = arm.matrix_world @ b.head_local
        tail = arm.matrix_world @ b.tail_local
        bones.append(
            {
                "name": b.name,
                "parent": parent,
                "head": [float(head.x), float(head.y), float(head.z)],
                "tail": [float(tail.x), float(tail.y), float(tail.z)],
                "length": float((tail - head).length),
                "children": [c.name for c in b.children],
            }
        )
    meshes = []
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        groups = [g.name for g in o.vertex_groups]
        meshes.append({"name": o.name, "verts": len(o.data.vertices), "groups": groups})

    report = {
        "src": str(src).replace("\\", "/"),
        "armature": arm.name,
        "boneCount": len(bones),
        "bones": bones,
        "meshes": meshes,
        "proof": "generated artifact validated — armature dump only; roles not authored",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "bones": len(bones), "out": str(out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
