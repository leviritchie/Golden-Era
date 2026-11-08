#!/usr/bin/env python3
"""Diagnose whether frame_00_rigged is already exploded at rest (bind/skin issue)."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import bpy
import numpy as np

OUT = Path(
    r"V:/Games/Olden Era Playtest Tweak/artifacts/hobgoblin_attack_pose_pipeline/out_meshy_t2_per_frame_g11"
)


def _clear() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _bounds(obj, *, deps: bool) -> dict:
    if deps:
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        try:
            pts = np.array([ev.matrix_world @ v.co for v in me.vertices], dtype=np.float64)
        finally:
            ev.to_mesh_clear()
    else:
        pts = np.array([obj.matrix_world @ v.co for v in obj.data.vertices], dtype=np.float64)
    return {
        "min": pts.min(0).tolist(),
        "max": pts.max(0).tolist(),
        "span": (pts.max(0) - pts.min(0)).tolist(),
        "n": int(len(pts)),
    }


def main() -> int:
    report: dict = {}

    _clear()
    bpy.ops.import_scene.gltf(filepath=str(OUT / "meshes" / "frame_00.glb"))
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    report["A_unrigged"] = _bounds(mesh, deps=True)

    _clear()
    bpy.ops.import_scene.gltf(filepath=str(OUT / "rigged" / "frame_00_rigged.glb"))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    report["B_rigged_eval"] = _bounds(mesh, deps=True)
    report["B_rigged_raw"] = _bounds(mesh, deps=False)
    heads = []
    for pb in arm.pose.bones:
        h = arm.matrix_world @ pb.head
        heads.append([float(h.x), float(h.y), float(h.z)])
    H = np.asarray(heads, dtype=np.float64)
    report["bones"] = {
        "min": H.min(0).tolist(),
        "max": H.max(0).tolist(),
        "span": (H.max(0) - H.min(0)).tolist(),
        "count": int(len(H)),
    }

    for m in mesh.modifiers:
        if m.type == "ARMATURE":
            m.show_viewport = False
            m.show_render = False
    bpy.context.view_layer.update()
    report["D_mod_off_eval"] = _bounds(mesh, deps=True)

    c: Counter[str] = Counter()
    ungrouped = 0
    for v in mesh.data.vertices:
        if not v.groups:
            ungrouped += 1
            continue
        best = max(v.groups, key=lambda g: g.weight)
        c[mesh.vertex_groups[best.group].name] += 1
    report["weights"] = {
        "ungrouped": ungrouped,
        "perBoneDominant": dict(c),
        "vgCount": len(mesh.vertex_groups),
    }

    out = OUT / "preview_frame0_driven" / "diag" / "bounds_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
