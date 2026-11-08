#!/usr/bin/env python3
"""Quick pose probe renders for smash/overhead candidates."""
from __future__ import annotations

import sys
from pathlib import Path

import bpy
from mathutils import Euler

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "homm3_silhouette_pose_fit"))
from homm3_pose_camera import setup_pose_camera

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_apose_mace_attach/smash_probe"
MASTER = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/master/hobgoblin_apose_mace_attach.glb"

CANDIDATES = {
    "overhead": {
        "Spine": (-0.35, 0.12, 0.1),
        "Spine01": (-0.25, 0.1, 0.08),
        "Hips": (-0.05, 0.12, 0),
        "LeftShoulder": (-1.2, 0.5, 0.4),
        "LeftArm": (-0.8, 0.3, -1.2),
        "LeftForeArm": (0.6, 0.1, -0.5),
        "LeftHand": (0.3, 0.7, 0.5),
        "RightShoulder": (-0.7, -0.25, -0.3),
        "RightArm": (-0.65, -0.2, 0.7),
        "RightForeArm": (0.75, 0, 0.3),
        "LeftUpLeg": (-0.2, 0.05, 0.06),
        "LeftLeg": (0.4, 0, 0),
        "RightUpLeg": (-0.2, -0.05, -0.06),
        "RightLeg": (0.4, 0, 0),
    },
    "apex": {
        "Spine": (0.08, -0.04, 0.05),
        "Spine01": (0.1, -0.02, 0.03),
        "Hips": (0.05, -0.02, 0.04),
        "LeftShoulder": (-1.3, 0.1, 0.5),
        "LeftArm": (-1.0, 0.1, -1.3),
        "LeftForeArm": (0.35, 0, -0.3),
        "LeftHand": (0.2, 0.5, 0.3),
        "RightShoulder": (-1.0, -0.1, -0.4),
        "RightArm": (-0.9, -0.1, 0.9),
        "RightForeArm": (0.5, 0, 0.2),
        "LeftUpLeg": (-0.16, 0.04, 0.05),
        "LeftLeg": (0.32, 0, 0),
        "RightUpLeg": (-0.16, -0.04, -0.05),
        "RightLeg": (0.32, 0, 0),
    },
    "smash_low": {
        "Hips": (0.18, -0.12, 0.12),
        "Spine": (0.5, -0.12, 0.05),
        "Spine01": (0.4, -0.1, 0.02),
        "Spine02": (0.22, -0.06, 0.02),
        "neck": (0.2, -0.08, -0.02),
        "Head": (0.22, -0.1, -0.04),
        "LeftShoulder": (0.35, 0.25, 0.45),
        "LeftArm": (1.15, 0.35, -0.1),
        "LeftForeArm": (0.05, 0.0, -0.75),
        "LeftHand": (0.55, 0.15, 0.05),
        "RightShoulder": (0.25, -0.2, -0.3),
        "RightArm": (0.95, -0.3, 0.3),
        "RightForeArm": (0.55, 0.0, 0.1),
        "RightHand": (0.1, -0.1, 0.05),
        "LeftUpLeg": (-0.32, 0.1, 0.12),
        "LeftLeg": (0.65, 0, 0),
        "RightUpLeg": (-0.32, -0.1, -0.12),
        "RightLeg": (0.65, 0, 0),
    },
    "smash_fwd": {
        "Hips": (0.16, -0.1, 0.1),
        "Spine": (0.42, -0.1, 0.04),
        "Spine01": (0.32, -0.08, 0.02),
        "LeftShoulder": (0.2, 0.15, 0.4),
        "LeftArm": (0.95, 0.2, -0.45),
        "LeftForeArm": (0.15, 0.0, -0.6),
        "LeftHand": (0.45, 0.25, 0.15),
        "RightShoulder": (0.15, -0.15, -0.25),
        "RightArm": (0.8, -0.25, 0.35),
        "RightForeArm": (0.5, 0.0, 0.12),
        "LeftUpLeg": (-0.3, 0.08, 0.1),
        "LeftLeg": (0.6, 0, 0),
        "RightUpLeg": (-0.3, -0.08, -0.1),
        "RightLeg": (0.6, 0, 0),
    },
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(MASTER))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    for m in [o for o in bpy.data.objects if o.type == "MESH"]:
        for mat in m.data.materials:
            if not mat or not mat.use_nodes:
                continue
            nt = mat.node_tree
            nodes, links = nt.nodes, nt.links
            outn = next(n for n in nodes if n.type == "OUTPUT_MATERIAL")
            bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
            emit = nodes.new("ShaderNodeEmission")
            emit.inputs["Strength"].default_value = 1
            base = bsdf.inputs["Base Color"]
            if base.is_linked:
                links.new(base.links[0].from_socket, emit.inputs["Color"])
            else:
                emit.inputs["Color"].default_value = tuple(base.default_value)
            for link in list(outn.inputs["Surface"].links):
                links.remove(link)
            links.new(emit.outputs["Emission"], outn.inputs["Surface"])

    setup_pose_camera(
        {"camera": {"axis": "iso", "isoAzimuthDeg": 40, "isoElevationDeg": 30, "distance": 3, "orthoScale": 2.6}},
        arm,
        bpy_module=bpy,
    )
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    rest = {}
    for n in arm.pose.bones:
        arm.pose.bones[n.name].rotation_mode = "XYZ"
        rest[n.name] = arm.pose.bones[n.name].rotation_euler.copy()

    for name, deltas in CANDIDATES.items():
        for n, e in rest.items():
            arm.pose.bones[n].rotation_euler = e.copy()
        for n, (dx, dy, dz) in deltas.items():
            b = rest[n]
            arm.pose.bones[n].rotation_euler = Euler((b.x + dx, b.y + dy, b.z + dz), "XYZ")
        bpy.context.view_layer.update()
        lh = arm.matrix_world @ arm.pose.bones["LeftHand"].head
        sc = bpy.context.scene
        sc.render.engine = "BLENDER_EEVEE"
        sc.render.resolution_x = 360
        sc.render.resolution_y = 320
        sc.render.film_transparent = True
        sc.render.filepath = str(OUT / f"{name}.png")
        sc.render.image_settings.file_format = "PNG"
        bpy.ops.render.render(write_still=True)
        print(name, [round(c, 3) for c in lh], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
