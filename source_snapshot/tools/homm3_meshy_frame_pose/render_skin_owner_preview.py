#!/usr/bin/env python3
"""Render an owned-master rest-pose preview colored by rigid triangle owner."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import bpy
from mathutils import Vector

TOOL = Path(__file__).resolve().parents[1] / "homm3_silhouette_pose_fit"
sys.path.insert(0, str(TOOL))
from homm3_pose_camera import setup_pose_camera  # noqa: E402


PALETTE = {
    "Head": (0.92, 0.12, 0.12, 1.0),
    "neck": (1.0, 0.45, 0.05, 1.0),
    "Spine": (1.0, 0.82, 0.05, 1.0),
    "Spine01": (0.2, 0.82, 0.15, 1.0),
    "Spine02": (0.05, 0.72, 0.75, 1.0),
    "Hips": (0.1, 0.35, 0.95, 1.0),
    "LeftShoulder": (0.7, 0.15, 0.9, 1.0),
    "LeftArm": (0.45, 0.1, 0.65, 1.0),
    "LeftForeArm": (0.25, 0.05, 0.45, 1.0),
    "LeftHand": (0.1, 0.02, 0.25, 1.0),
    "RightShoulder": (0.1, 0.75, 0.35, 1.0),
    "RightArm": (0.05, 0.55, 0.2, 1.0),
    "RightForeArm": (0.02, 0.35, 0.12, 1.0),
    "RightHand": (0.01, 0.18, 0.05, 1.0),
    "RightWeaponTip": (0.95, 0.05, 0.7, 1.0),
    "LeftUpLeg": (0.1, 0.45, 0.95, 1.0),
    "LeftLeg": (0.05, 0.2, 0.65, 1.0),
    "LeftFoot": (0.02, 0.08, 0.35, 1.0),
    "RightUpLeg": (0.95, 0.35, 0.05, 1.0),
    "RightLeg": (0.7, 0.15, 0.02, 1.0),
    "RightFoot": (0.4, 0.05, 0.01, 1.0),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.master.resolve()))
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    groups = {g.index: g.name for g in mesh.vertex_groups}
    mats = {}
    for name, color in PALETTE.items():
        mat = bpy.data.materials.new("Owner_" + name)
        mat.diffuse_color = color
        mat.use_nodes = True
        bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        bsdf.inputs["Base Color"].default_value = color
        if bsdf.inputs.get("Emission") is not None:
            bsdf.inputs["Emission"].default_value = color
        if bsdf.inputs.get("Emission Strength") is not None:
            bsdf.inputs["Emission Strength"].default_value = 1.0
        bsdf.inputs["Roughness"].default_value = 0.78
        mats[name] = mat
        mesh.data.materials.append(mat)

    owner_counts = Counter()
    for poly in mesh.data.polygons:
        owners = []
        for vi in poly.vertices:
            v = mesh.data.vertices[vi]
            if not v.groups:
                owners.append("UNOWNED")
                continue
            group = max(v.groups, key=lambda g: g.weight)
            owners.append(groups.get(group.group, "UNOWNED"))
        owner = Counter(owners).most_common(1)[0][0]
        owner_counts[owner] += 1
        if owner not in mats:
            mat = bpy.data.materials.new("Owner_" + owner)
            mat.diffuse_color = (0.6, 0.6, 0.6, 1.0)
            mats[owner] = mat
            mesh.data.materials.append(mat)
        poly.material_index = list(mesh.data.materials).index(mats[owner])

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 16
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    world = bpy.data.worlds.new("OwnerPreviewWorld")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.025, 0.025, 0.035, 1.0)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.3
    setup_pose_camera(
        {"camera": {"axis": "iso", "distance": 3.0, "isoAzimuthDeg": 40.0, "isoElevationDeg": 30.0, "orthoScale": 2.0, "lookAtZ": 0.7}},
        arm,
        bpy_module=bpy,
    )
    scene.render.filepath = str(args.out.resolve())
    bpy.ops.render.render(write_still=True)
    args.out.with_suffix(".json").write_text(json.dumps({"triangleOwnerCounts": dict(owner_counts), "palette": PALETTE}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "preview": str(args.out).replace("\\", "/"), "owners": dict(owner_counts)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
