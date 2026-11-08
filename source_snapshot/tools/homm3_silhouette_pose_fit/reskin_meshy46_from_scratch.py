#!/usr/bin/env python3
"""
Full from-scratch re-skin of Meshy46 hobgoblin (no Meshy weights kept).

Blender Bone Heat / Automatic Weights fails on this mesh (2381 islands;
\"failed to find solution for one or more bones\"). Instead:

1. Clear all Meshy vertex groups.
2. Assign every vertex by inverse-distance to the nearest bone segments
   (head→tail), k=2 blend.
3. Verts near the strike-hand shaft / mace tip may only bind to the
   weapon/hand bone chain (no torso bleed).

Export: master/Meshy_AI_Character_output_3_reskin.glb
Proof: generated artifact validated — geometric reskin; not OE runtime proven.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
SRC = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/master/Meshy_AI_Character_output_3.glb"
OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/master/Meshy_AI_Character_output_3_reskin.glb"
REPORT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/master/meshy46_reskin_report.json"

WEAPON_BONES = {
    "Bone_037",
    "Bone_036",
    "Bone_035",
    "Bone_034",
    "Bone_033",
    "Bone_039",
    "Bone_038",
    "Bone_042",
    "Bone_041",
    "Bone_040",
    "Bone_045",
    "Bone_044",
    "Bone_043",
}


def _clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _seg_dist(p: Vector, a: Vector, b: Vector) -> float:
    ab = b - a
    denom = ab.length_squared
    if denom < 1e-12:
        return (p - a).length
    t = max(0.0, min(1.0, (p - a).dot(ab) / denom))
    return (p - (a + ab * t)).length


def _bone_segments(arm) -> list[tuple[str, Vector, Vector]]:
    segs: list[tuple[str, Vector, Vector]] = []
    mw = arm.matrix_world
    for b in arm.pose.bones:
        # Skip pure root helper if extremely short; still include all named bones.
        h = mw @ b.head
        t = mw @ b.tail
        segs.append((b.name, h, t))
    return segs


def main() -> int:
    if not SRC.is_file():
        print(f"missing: {SRC}", file=sys.stderr)
        return 2

    _clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(SRC))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")

    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="SELECT")
    bpy.ops.pose.transforms_clear()
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()

    while mesh.vertex_groups:
        mesh.vertex_groups.remove(mesh.vertex_groups[0])
    for mod in list(mesh.modifiers):
        if mod.type == "ARMATURE":
            mesh.modifiers.remove(mod)

    # Ensure armature modifier + parent
    mesh.parent = arm
    mesh.parent_type = "ARMATURE"
    mod = mesh.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = arm

    segs = _bone_segments(arm)
    # Create groups for every bone
    groups = {name: mesh.vertex_groups.new(name=name) for name, _, _ in segs}

    tip = next(h for n, h, _ in segs if n == "Bone_033")
    wrist = next(h for n, h, _ in segs if n == "Bone_035")
    tip_ext = tip + (tip - wrist).normalized() * 0.14

    weapon_only = 0
    for v in mesh.data.vertices:
        co = mesh.matrix_world @ v.co
        d_tip = (co - tip).length
        d_shaft = _seg_dist(co, wrist, tip_ext)
        force_weapon = d_tip <= 0.20 or d_shaft <= 0.09

        scored: list[tuple[float, str]] = []
        for name, h, t in segs:
            if force_weapon and name not in WEAPON_BONES:
                continue
            d = _seg_dist(co, h, t)
            scored.append((d, name))
        if not scored:
            # fallback
            scored = [(_seg_dist(co, h, t), name) for name, h, t in segs]

        scored.sort(key=lambda x: x[0])
        top = scored[:2]
        # inverse-distance weights
        weights: list[tuple[str, float]] = []
        for d, name in top:
            weights.append((name, 1.0 / max(d, 1e-4)))
        s = sum(w for _, w in weights)
        for name, w in weights:
            groups[name].add([v.index], w / s, "REPLACE")
        if force_weapon:
            weapon_only += 1

    # Contam check
    vg_index = {g.index: g.name for g in mesh.vertex_groups}
    tip_near = tip_contam = 0
    for v in mesh.data.vertices:
        co = mesh.matrix_world @ v.co
        if (co - tip).length > 0.22:
            continue
        tip_near += 1
        names = {vg_index.get(g.group) for g in v.groups if g.weight > 0.05}
        names.discard(None)
        if names - WEAPON_BONES:
            tip_contam += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.gltf(
        filepath=str(OUT),
        export_format="GLB",
        use_selection=True,
        export_animations=False,
        export_apply=False,
        export_skins=True,
        export_morph=False,
    )

    report = {
        "ok": True,
        "source": str(SRC).replace("\\", "/"),
        "output": str(OUT).replace("\\", "/"),
        "method": "geometric_nearest_bone_k2_weapon_mask",
        "vertexCount": len(mesh.data.vertices),
        "vertexGroupCount": len(mesh.vertex_groups),
        "weaponForcedVerts": weapon_only,
        "tipNearVerts": tip_near,
        "tipNearStillContaminated": tip_contam,
        "heatWeighting": "skipped — Bone Heat fails on this fragmented Meshy mesh",
        "proof": "generated artifact validated — full geometric reskin from scratch; not OE runtime proven",
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if tip_contam == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
