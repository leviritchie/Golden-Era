#!/usr/bin/env python3
"""
Build a flat proximity pseudo-rig from an unrigged Meshy mesh.

Blender usage:
  blender -b --python build_pseudo_rig.py -- \\
    --mesh path/to/unrigged.glb \\
    --out-glb path/to/crusader_pseudo_master.glb \\
    --out-catalog path/to/handle_catalog.json \\
    --handle-count 48
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MESH = ROOT / (
    "artifacts/crusader_pose_pipeline/out_meshy_t2_idle_f0/meshes/"
    "idle_f0_meshy6_retexture.glb"
)
DEFAULT_OUT_GLB = ROOT / (
    "artifacts/crusader_pose_pipeline/pseudo_rig/owned_bind/crusader_pseudo_master.glb"
)
DEFAULT_CATALOG = ROOT / (
    "artifacts/crusader_pose_pipeline/pseudo_rig/owned_bind/handle_catalog.json"
)


def _argv_after_double_dash() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return sys.argv[1:]


def _clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _import_mesh(glb: Path) -> bpy.types.Object:
    bpy.ops.import_scene.gltf(filepath=str(glb))
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"no mesh in {glb}")
    # Prefer the largest mesh if multiple arrive.
    meshes.sort(key=lambda o: len(o.data.vertices), reverse=True)
    mesh = meshes[0]
    # Drop any imported armatures / empties so the master is ours alone.
    for obj in list(bpy.data.objects):
        if obj != mesh:
            bpy.data.objects.remove(obj, do_unlink=True)
    return mesh


def _world_positions(mesh_obj: bpy.types.Object) -> np.ndarray:
    mw = mesh_obj.matrix_world
    verts = mesh_obj.data.vertices
    out = np.zeros((len(verts), 3), dtype=np.float64)
    for i, v in enumerate(verts):
        p = mw @ v.co
        out[i] = (p.x, p.y, p.z)
    return out


def _farthest_point_sample(positions: np.ndarray, count: int, *, seed: int = 0) -> list[int]:
    n = int(positions.shape[0])
    if n < 1:
        raise RuntimeError("mesh has no vertices")
    k = min(int(count), n)
    rng = np.random.default_rng(seed)
    # Seed with the vertex farthest from the AABB center (stable spatial start).
    center = positions.mean(axis=0)
    d0 = np.linalg.norm(positions - center[None, :], axis=1)
    first = int(np.argmax(d0))
    chosen = [first]
    min_dist = np.linalg.norm(positions - positions[first][None, :], axis=1)
    for _ in range(1, k):
        nxt = int(np.argmax(min_dist))
        # Tiny jitter only if exact ties; otherwise pure FPS.
        if min_dist[nxt] <= 1e-12:
            nxt = int(rng.integers(0, n))
        chosen.append(nxt)
        d_new = np.linalg.norm(positions - positions[nxt][None, :], axis=1)
        min_dist = np.minimum(min_dist, d_new)
    return chosen


def _create_armature(
    mesh_obj: bpy.types.Object,
    sample_indices: list[int],
    positions: np.ndarray,
) -> bpy.types.Object:
    arm_data = bpy.data.armatures.new("PseudoRig")
    arm_obj = bpy.data.objects.new("PseudoRig", arm_data)
    bpy.context.collection.objects.link(arm_obj)

    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")

    # ROOT bone at origin; deform stubs parented flat under ROOT.
    root = arm_data.edit_bones.new("ROOT")
    root.head = Vector((0.0, 0.0, 0.0))
    root.tail = Vector((0.0, 0.05, 0.0))

    # Stub length: small fraction of mesh diagonal so weights use bone heads as points.
    diag = float(np.linalg.norm(positions.max(axis=0) - positions.min(axis=0)))
    stub = max(0.01, diag * 0.02)

    handles = []
    for i, vi in enumerate(sample_indices):
        name = f"deform_{i:03d}"
        eb = arm_data.edit_bones.new(name)
        p = positions[vi]
        head = Vector((float(p[0]), float(p[1]), float(p[2])))
        # Offset slightly along +Z so head != tail; keep stub short.
        eb.head = head
        eb.tail = head + Vector((0.0, 0.0, stub))
        eb.parent = root
        eb.use_connect = False
        handles.append(
            {
                "name": name,
                "vertexIndex": int(vi),
                "restPosition": [float(p[0]), float(p[1]), float(p[2])],
            }
        )

    bpy.ops.object.mode_set(mode="OBJECT")
    return arm_obj, handles


def _assign_proximity_weights(
    arm_obj: bpy.types.Object,
    mesh_obj: bpy.types.Object,
    handle_names: list[str],
    *,
    k: int = 4,
    power: float = 2.0,
) -> dict:
    while mesh_obj.vertex_groups:
        mesh_obj.vertex_groups.remove(mesh_obj.vertex_groups[0])
    for mod in list(mesh_obj.modifiers):
        if mod.type == "ARMATURE":
            mesh_obj.modifiers.remove(mod)

    # Pose-bone heads in world space (point handles).
    bpy.context.view_layer.update()
    heads = []
    for name in handle_names:
        pb = arm_obj.pose.bones.get(name)
        if pb is None:
            raise RuntimeError(f"missing pose bone {name}")
        h = arm_obj.matrix_world @ pb.head
        heads.append((name, np.array([h.x, h.y, h.z], dtype=np.float64)))
        mesh_obj.vertex_groups.new(name=name)

    mw = mesh_obj.matrix_world
    k_use = max(1, min(int(k), len(heads)))
    eps = 1e-4
    empty_groups = {name: 0 for name, _ in heads}
    weight_sum_errors = 0
    for vi, v in enumerate(mesh_obj.data.vertices):
        p = mw @ v.co
        p_np = np.array([p.x, p.y, p.z], dtype=np.float64)
        dists = []
        for name, head in heads:
            d = float(np.linalg.norm(p_np - head))
            dists.append((d, name))
        dists.sort(key=lambda x: x[0])
        picked = dists[:k_use]
        weights = [(name, 1.0 / ((d + eps) ** power)) for d, name in picked]
        total = sum(w for _, w in weights) or 1.0
        acc = 0.0
        for name, w in weights:
            nw = float(w / total)
            mesh_obj.vertex_groups[name].add([vi], nw, "REPLACE")
            empty_groups[name] += 1
            acc += nw
        if abs(acc - 1.0) > 1e-3:
            weight_sum_errors += 1

    mesh_obj.parent = arm_obj
    mesh_obj.parent_type = "OBJECT"
    mod = mesh_obj.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = arm_obj
    mod.use_vertex_groups = True

    vacant = [n for n, c in empty_groups.items() if c == 0]
    if vacant:
        raise RuntimeError(f"empty vertex groups (fail-closed): {vacant}")
    if weight_sum_errors:
        raise RuntimeError(f"weight sum errors on {weight_sum_errors} verts")

    return {
        "vertexCount": len(mesh_obj.data.vertices),
        "handleCount": len(handle_names),
        "k": k_use,
        "power": power,
        "emptyGroups": 0,
        "weightSumErrors": 0,
        "influencesPerHandle": {n: int(c) for n, c in empty_groups.items()},
    }


def _export_glb(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        export_skins=True,
        export_animations=False,
        export_apply=False,
        export_texcoords=True,
        export_normals=True,
        export_materials="EXPORT",
    )


def run(args: argparse.Namespace) -> dict:
    mesh_path = Path(args.mesh)
    out_glb = Path(args.out_glb)
    out_catalog = Path(args.out_catalog)
    if not mesh_path.is_file():
        raise FileNotFoundError(f"mesh not found: {mesh_path}")

    _clear_scene()
    mesh_obj = _import_mesh(mesh_path)
    positions = _world_positions(mesh_obj)
    sample_indices = _farthest_point_sample(
        positions, int(args.handle_count), seed=int(args.seed)
    )
    arm_obj, handles = _create_armature(mesh_obj, sample_indices, positions)
    handle_names = [h["name"] for h in handles]
    audit = _assign_proximity_weights(
        arm_obj,
        mesh_obj,
        handle_names,
        k=int(args.k),
        power=float(args.power),
    )

    # Select armature + mesh for export.
    bpy.ops.object.select_all(action="DESELECT")
    arm_obj.select_set(True)
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj
    _export_glb(out_glb)

    catalog = {
        "schema": "homm3_pseudo_rig_handle_catalog.v1",
        "unitSid": str(args.unit_sid),
        "sourceMesh": str(mesh_path.resolve()),
        "outputGlb": str(out_glb.resolve()),
        "handleCount": len(handles),
        "handles": handles,
        "skin": {
            "mode": "proximity_point_k_nearest",
            "k": int(args.k),
            "power": float(args.power),
        },
        "audit": audit,
        "proof": "generated-artifact validated — pseudo-rig master; not OE runtime",
    }
    out_catalog.parent.mkdir(parents=True, exist_ok=True)
    out_catalog.write_text(json.dumps(catalog, indent=2), encoding="utf-8")

    # Bone count gate (ROOT + 48 deform).
    n_bones = len(arm_obj.data.bones)
    expected = 1 + len(handles)
    if n_bones != expected:
        raise RuntimeError(f"bone count {n_bones} != expected {expected}")
    if len(handles) != int(args.handle_count):
        raise RuntimeError(
            f"handle count {len(handles)} != requested {args.handle_count}"
        )

    print(
        json.dumps(
            {
                "ok": True,
                "outGlb": str(out_glb),
                "catalog": str(out_catalog),
                "handleCount": len(handles),
                "vertexCount": audit["vertexCount"],
            }
        ),
        flush=True,
    )
    return catalog


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mesh", type=Path, default=DEFAULT_MESH)
    ap.add_argument("--out-glb", type=Path, default=DEFAULT_OUT_GLB)
    ap.add_argument("--out-catalog", type=Path, default=DEFAULT_CATALOG)
    ap.add_argument("--handle-count", type=int, default=48)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--power", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--unit-sid", type=str, default="h3_crusader")
    args = ap.parse_args(_argv_after_double_dash())
    try:
        run(args)
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
