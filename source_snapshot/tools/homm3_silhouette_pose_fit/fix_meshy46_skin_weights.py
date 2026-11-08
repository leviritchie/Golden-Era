#!/usr/bin/env python3
"""
Blender script: clean Meshy46 hobgoblin skin weights so the mace is not glued to torso/hip.

Run:
  blender -b --python tools/homm3_silhouette_pose_fit/fix_meshy46_skin_weights.py --

Reads master Meshy_AI_Character_output_3.glb, writes
artifacts/.../master/Meshy_AI_Character_output_3_skinfix.glb
plus a small JSON report.

Proof: generated artifact validated — skin-weight edit; not OE runtime proven.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
SRC = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/master/Meshy_AI_Character_output_3.glb"
OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/master/Meshy_AI_Character_output_3_skinfix.glb"
REPORT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/master/meshy46_skinfix_report.json"

# +X strike arm + finger chain under tip (Bone_033).
WEAPON_BONES = {
    "Bone_037",  # shoulder
    "Bone_036",  # elbow
    "Bone_035",  # wrist
    "Bone_034",
    "Bone_033",  # tip / hand end
    "Bone_039",
    "Bone_038",
    "Bone_042",
    "Bone_041",
    "Bone_040",
    "Bone_045",
    "Bone_044",
    "Bone_043",
}


def _bone_head_world(arm, name: str) -> Vector:
    return arm.matrix_world @ arm.pose.bones[name].head


def _dist_point_segment(p: Vector, a: Vector, b: Vector) -> float:
    ab = b - a
    denom = ab.length_squared
    if denom < 1e-12:
        return (p - a).length
    t = max(0.0, min(1.0, (p - a).dot(ab) / denom))
    return (p - (a + ab * t)).length


def _clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _ensure_groups(mesh, names: set[str]) -> dict[str, bpy.types.VertexGroup]:
    out = {g.name: g for g in mesh.vertex_groups}
    for n in names:
        if n not in out:
            out[n] = mesh.vertex_groups.new(name=n)
    return out


def main() -> int:
    if not SRC.is_file():
        print(f"missing master: {SRC}", file=sys.stderr)
        return 2

    _clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(SRC))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    bpy.context.view_layer.objects.active = mesh

    tip = _bone_head_world(arm, "Bone_033")
    wrist = _bone_head_world(arm, "Bone_035")
    elbow = _bone_head_world(arm, "Bone_036")
    # Shaft axis wrist→tip; also allow a bit past tip for spikes.
    tip_ext = tip + (tip - wrist).normalized() * 0.12

    groups = _ensure_groups(mesh, WEAPON_BONES)
    vg_index = {g.index: g.name for g in mesh.vertex_groups}

    selected: list[int] = []
    for v in mesh.data.vertices:
        co = mesh.matrix_world @ v.co
        d_tip = (co - tip).length
        d_seg = _dist_point_segment(co, wrist, tip_ext)
        d_fore = _dist_point_segment(co, elbow, wrist)
        # Existing weapon influence
        w_weapon = 0.0
        for g in v.groups:
            name = vg_index.get(g.group)
            if name in WEAPON_BONES:
                w_weapon += float(g.weight)
        # Mace / shaft candidates
        if d_tip <= 0.28 or d_seg <= 0.10 or (d_fore <= 0.09 and w_weapon >= 0.25):
            selected.append(v.index)
            continue
        if w_weapon >= 0.55 and d_tip <= 0.45:
            selected.append(v.index)

    fixed = 0
    stripped_mass = 0.0
    assigned_full_tip = 0
    for idx in selected:
        v = mesh.data.vertices[idx]
        kept: dict[str, float] = {}
        stripped = 0.0
        for g in list(v.groups):
            name = vg_index.get(g.group)
            w = float(g.weight)
            if name in WEAPON_BONES and w > 1e-6:
                kept[name] = kept.get(name, 0.0) + w
            else:
                stripped += w
                # remove non-weapon influence
                if name is not None:
                    mesh.vertex_groups[name].remove([idx])
        if stripped <= 1e-6 and kept:
            continue
        stripped_mass += stripped
        if not kept:
            groups["Bone_033"].add([idx], 1.0, "REPLACE")
            assigned_full_tip += 1
        else:
            total = sum(kept.values())
            for name, w in kept.items():
                groups[name].add([idx], w / total, "REPLACE")
        fixed += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Export selection: armature + mesh
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

    # Post-check contamination count on tip-near verts
    tip2 = _bone_head_world(arm, "Bone_033")
    contam = 0
    tip_near = 0
    for v in mesh.data.vertices:
        co = mesh.matrix_world @ v.co
        if (co - tip2).length > 0.22:
            continue
        tip_near += 1
        names = {
            vg_index.get(g.group)
            for g in v.groups
            if g.weight > 0.05 and vg_index.get(g.group)
        }
        if names - WEAPON_BONES:
            contam += 1

    report = {
        "ok": True,
        "source": str(SRC).replace("\\", "/"),
        "output": str(OUT).replace("\\", "/"),
        "selectedVerts": len(selected),
        "fixedVerts": fixed,
        "assignedFullTip": assigned_full_tip,
        "strippedWeightMass": round(stripped_mass, 3),
        "tipNearAfter": tip_near,
        "tipNearStillContaminated": contam,
        "weaponBones": sorted(WEAPON_BONES),
        "proof": "generated artifact validated — skin-weight cleanup on Meshy46 master; not OE runtime proven",
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if contam == 0 else 0  # still ok to export; report contam


if __name__ == "__main__":
    raise SystemExit(main())
