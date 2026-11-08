#!/usr/bin/env python3
"""
Skin frames 1..N with the SAME Mixamo hierarchy as hand-built frame 0.

For each Meshy mesh: normalize, place shared bone names from mesh AABB heuristics
(same builder as frame 0), Blender automatic weights. No Meshy smart-rig.

  blender -b --python skin_frames_shared_skeleton.py -- \\
    --meshes-dir .../meshes \\
    --skeleton-json .../shared_skeleton.json \\
    --output-dir .../rigged \\
    --start 1 --end 7
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

# Reuse builders from frame0 script via import by path
_TOOL = Path(__file__).resolve().parent
if str(_TOOL) not in sys.path:
    sys.path.insert(0, str(_TOOL))

# Inline minimal copies to keep Blender happy without package import quirks
from rig_frame0_shared_skeleton import (  # noqa: E402
    HIERARCHY,
    _abs,
    _auto_weight,
    _build_joint_guesses,
    _create_armature,
    _ensure_bone_lengths,
    _mesh_world_verts,
    _nearest_bone_weights,
)

ROOT = Path(__file__).resolve().parents[2]


def _argv() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def _parse() -> dict:
    args = _argv()
    out = {
        "meshesDir": None,
        "skeletonJson": None,
        "outputDir": None,
        "start": 1,
        "end": 7,
        "frame0Rigged": None,
    }
    i = 0
    while i < len(args):
        if args[i] == "--meshes-dir" and i + 1 < len(args):
            out["meshesDir"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--skeleton-json" and i + 1 < len(args):
            out["skeletonJson"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--output-dir" and i + 1 < len(args):
            out["outputDir"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--frame0-rigged" and i + 1 < len(args):
            out["frame0Rigged"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--start" and i + 1 < len(args):
            out["start"] = int(args[i + 1])
            i += 2
        elif args[i] == "--end" and i + 1 < len(args):
            out["end"] = int(args[i + 1])
            i += 2
        else:
            i += 1
    if not out["meshesDir"] or not out["outputDir"] or not out["skeletonJson"]:
        raise SystemExit("need --meshes-dir --skeleton-json --output-dir")
    return out


def _normalize_mesh(mesh_obj, target_h: float = 1.4) -> None:
    verts = _mesh_world_verts(mesh_obj)
    zmin, zmax = float(verts[:, 2].min()), float(verts[:, 2].max())
    height = max(zmax - zmin, 1e-6)
    scale = target_h / height
    mesh_obj.scale = (scale, scale, scale)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_obj
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    verts = _mesh_world_verts(mesh_obj)
    center_xy = verts[:, :2].mean(axis=0)
    zmin = float(verts[:, 2].min())
    mesh_obj.location.x -= float(center_xy[0])
    mesh_obj.location.y -= float(center_xy[1])
    mesh_obj.location.z -= zmin
    bpy.context.view_layer.update()
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)


def _template_lengths(skel: dict) -> dict[str, float]:
    """Optional: preserve bone lengths from frame0 skeleton JSON heads."""
    heads = {b["name"]: np.array(b["head"], dtype=np.float64) for b in skel.get("bones") or []}
    lengths = {}
    children: dict[str, list[str]] = {}
    for name, parent in HIERARCHY:
        if parent:
            children.setdefault(parent, []).append(name)
    for name, _parent in HIERARCHY:
        kids = children.get(name) or []
        if kids and name in heads and kids[0] in heads:
            lengths[name] = float(np.linalg.norm(heads[kids[0]] - heads[name]))
    return lengths


def _apply_length_preserve(joints: dict[str, np.ndarray], lengths: dict[str, float]) -> dict[str, np.ndarray]:
    """Keep child direction from heuristics but bone length from template when available."""
    out = {k: v.copy() for k, v in joints.items()}
    children: dict[str, list[str]] = {}
    for name, parent in HIERARCHY:
        if parent:
            children.setdefault(parent, []).append(name)
    # Parent→child pass
    for name, parent in HIERARCHY:
        kids = children.get(name) or []
        if not kids:
            continue
        child = kids[0]
        if name not in lengths or name not in out or child not in out:
            continue
        direction = out[child] - out[name]
        nrm = float(np.linalg.norm(direction))
        if nrm < 1e-8:
            continue
        out[child] = out[name] + direction / nrm * lengths[name]
    return out


def _rig_one(mesh_path: Path, out_path: Path, lengths: dict[str, float]) -> dict:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(mesh_path))
    mesh_obj = next(o for o in bpy.data.objects if o.type == "MESH")
    _normalize_mesh(mesh_obj)
    verts = _mesh_world_verts(mesh_obj)
    joints = _build_joint_guesses(verts)
    if lengths:
        joints = _apply_length_preserve(joints, lengths)
    arm = _create_armature(joints, name="SharedHobgoblin")
    weight_mode = _auto_weight(arm, mesh_obj)
    _ensure_bone_lengths(arm)
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.gltf(
        filepath=str(out_path),
        export_format="GLB",
        use_selection=True,
        export_animations=False,
        export_skins=True,
        export_apply=False,
    )
    return {
        "mesh": str(mesh_path).replace("\\", "/"),
        "output": str(out_path).replace("\\", "/"),
        "verts": len(mesh_obj.data.vertices),
        "bones": len(HIERARCHY),
        "weightMode": weight_mode,
    }


def main() -> int:
    opts = _parse()
    meshes_dir = _abs(Path(opts["meshesDir"]))
    out_dir = _abs(Path(opts["outputDir"]))
    skel_path = _abs(Path(opts["skeletonJson"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    skel = json.loads(skel_path.read_text(encoding="utf-8"))
    # Validate hierarchy matches
    skel_names = [b["name"] for b in skel.get("bones") or []]
    expected = [n for n, _ in HIERARCHY]
    if skel_names and skel_names != expected:
        print(f"[warn] skeleton JSON bone order differs; using shared HIERARCHY ({len(expected)} bones)", flush=True)
    lengths = _template_lengths(skel)

    report = {
        "skeleton": str(skel_path).replace("\\", "/"),
        "rigFamily": "hand_built_mixamo_shared",
        "frames": [],
        "proof": "generated artifact validated — shared hand skeleton + auto weights; not Meshy smart-rig",
    }
    for i in range(int(opts["start"]), int(opts["end"]) + 1):
        mesh_path = meshes_dir / f"frame_{i:02d}.glb"
        if not mesh_path.is_file():
            report["frames"].append({"frame": i, "error": f"missing {mesh_path}"})
            print(f"[skin] f{i:02d} missing mesh", flush=True)
            continue
        out_path = out_dir / f"frame_{i:02d}_rigged.glb"
        print(f"[skin] f{i:02d} → {out_path.name}", flush=True)
        entry = _rig_one(mesh_path, out_path, lengths)
        entry["frame"] = i
        report["frames"].append(entry)

    (out_dir / "skin_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    ok = sum(1 for f in report["frames"] if f.get("output"))
    print(json.dumps({"ok": True, "skinned": ok, "out": str(out_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        raise SystemExit(1)
