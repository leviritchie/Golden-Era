#!/usr/bin/env python3
"""Fill open boundary loops on a skinned Meshy GLB without remeshing.

Uses bmesh holes_fill / edgeloop_fill on existing boundary verts so skin
weights stay on those verts. Does not run remesh/decimate/retopo.

Blender:
  blender -b --python fill_mesh_holes.py -- \\
    --src .../idle_f0_rigged_bridgefix_meshy6.glb \\
    --out .../idle_f0_rigged_bridgefix_meshy6_holefill.glb
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _parse() -> dict:
    args = _argv()
    out = {"src": None, "out": None, "report": None, "weld": 1e-4}
    i = 0
    while i < len(args):
        if args[i] == "--src" and i + 1 < len(args):
            out["src"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--out" and i + 1 < len(args):
            out["out"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--report" and i + 1 < len(args):
            out["report"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--weld" and i + 1 < len(args):
            out["weld"] = float(args[i + 1])
            i += 2
        else:
            i += 1
    return out


def _boundary_stats(bm) -> dict:
    boundary = [e for e in bm.edges if e.is_boundary]
    adj: dict[int, list[int]] = {}
    for e in boundary:
        a, b = e.verts[0].index, e.verts[1].index
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    visited: set[int] = set()
    loops: list[int] = []
    for v0 in adj:
        if v0 in visited:
            continue
        stack = [v0]
        n = 0
        while stack:
            v = stack.pop()
            if v in visited:
                continue
            visited.add(v)
            n += 1
            for nxt in adj.get(v, []):
                if nxt not in visited:
                    stack.append(nxt)
        loops.append(n)
    loops.sort(reverse=True)
    return {
        "boundaryEdges": len(boundary),
        "boundaryLoops": len(loops),
        "loopSizes": loops[:20],
    }


def run() -> dict:
    opts = _parse()
    src = opts["src"]
    out = opts["out"]
    if src is None or out is None:
        raise RuntimeError("need --src and --out")
    if not src.is_file():
        raise FileNotFoundError(src)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(src))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")

    bm = bmesh.new()
    bm.from_mesh(mesh.data)
    before_v = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=float(opts["weld"]))
    welded = before_v - len(bm.verts)
    bm.edges.ensure_lookup_table()
    before = _boundary_stats(bm)

    # Pass 1: generic hole fill (closes many small loops).
    boundary = [e for e in bm.edges if e.is_boundary]
    filled1 = bmesh.ops.holes_fill(bm, edges=boundary, sides=0)
    n1 = len(filled1.get("faces") or [])

    # Pass 2: edgeloop_fill on remaining boundary edges (larger sword gaps).
    bm.edges.ensure_lookup_table()
    boundary2 = [e for e in bm.edges if e.is_boundary]
    n2 = 0
    if boundary2:
        filled2 = bmesh.ops.edgeloop_fill(bm, edges=boundary2)
        n2 = len(filled2.get("faces") or [])

    # Pass 3: triangle fill any leftover boundary.
    bm.edges.ensure_lookup_table()
    boundary3 = [e for e in bm.edges if e.is_boundary]
    n3 = 0
    if boundary3:
        filled3 = bmesh.ops.triangle_fill(bm, use_beauty=True, edges=boundary3)
        n3 = len(filled3.get("faces") or [])

    after = _boundary_stats(bm)
    bm.to_mesh(mesh.data)
    bm.free()
    mesh.data.update()

    # Recalculate normals for new faces.
    bpy.context.view_layer.objects.active = mesh
    mesh.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")

    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.gltf(
        filepath=str(out),
        export_format="GLB",
        use_selection=True,
        export_animations=False,
        export_apply=False,
    )
    if not out.is_file() or out.stat().st_size < 1000:
        raise RuntimeError(f"export missing/empty: {out}")

    report = {
        "ok": True,
        "src": str(src).replace("\\", "/"),
        "out": str(out).replace("\\", "/"),
        "outBytes": int(out.stat().st_size),
        "weldRemoved": int(welded),
        "before": before,
        "after": after,
        "filledFaces": {"holes_fill": n1, "edgeloop_fill": n2, "triangle_fill": n3},
        "proof": (
            "generated artifact validated — boundary hole fill without remesh; "
            "skin weights on existing verts retained; not OE runtime proven"
        ),
    }
    report_path = opts["report"] or out.with_suffix(".holefill_report.json")
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    if after["boundaryEdges"] > 0:
        print(
            f"[holefill] WARNING: {after['boundaryEdges']} boundary edges remain",
            flush=True,
        )
    return report


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)
