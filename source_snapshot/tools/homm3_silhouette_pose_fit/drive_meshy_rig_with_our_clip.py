#!/usr/bin/env python3
"""A/B pilot v4: Meshy rig driven by our walk — world targets + Blender-rest solve.

Host-side `retarget_our_clip_to_meshy.py` computes W_A (our clip's world
rotations, verified 0.0 deg) and stores them as expected_worlds. This script
imports ONLY Meshy's GLB and solves pose-local quaternions that reproduce
each W_A in BLENDER's own rest frame (bone.matrix_local), because the glTF
importer reinterprets bone rest vs the raw GLB node TRS. Formula verified by
the minimal rest-convention test. Renders lit DQS frames and verifies the
readback world == W_A.

Run from Blender:
  blender -b --python drive_meshy_rig_with_our_clip.py -- --out <dir>
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion

ARGS = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []

_TOOL = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOL))
from homm3_pose_camera import setup_pose_camera  # noqa: E402
from render_mesh_lit_60fps import _setup_lit_scene  # noqa: E402

MESHY_ANIM = Path(
    r"C:/Users/<user>/Downloads/Meshy_AI_Azure_Knight_of_the_E_biped"
    r"/Meshy_AI_Azure_Knight_of_the_E_biped"
    r"/Meshy_AI_Azure_Knight_of_the_E_biped_Meshy_AI_Meshy_Merged_Animations.glb"
)
RETARGET_JSON = Path(
    r"V:/Games/Olden Era Playtest Tweak/artifacts/crusader_pose_pipeline"
    r"/out_meshyrig_ourwalk/retarget_pose_locals.json"
)


def _depth(arm, name) -> int:
    d = 0
    b = arm.data.bones.get(name)
    while b and b.parent:
        d += 1
        b = b.parent
    return d


def main() -> int:
    out = Path(ARGS[1] if len(ARGS) > 1 else "artifacts/crusader_pose_pipeline/out_meshyrig_ourwalk")
    out.mkdir(parents=True, exist_ok=True)

    data = json.loads(RETARGET_JSON.read_text(encoding="utf-8"))
    shared = data["shared"]
    times = data["times"]
    expected_worlds = data["expected_worlds"]
    n_keys = len(times)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(MESHY_ANIM.resolve()))
    b_arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    if b_arm.animation_data:
        b_arm.animation_data_clear()
    b_mesh = next(o for o in bpy.data.objects if o.type == "MESH" and o.parent is b_arm)
    for mod in b_mesh.modifiers:
        if mod.type == "ARMATURE":
            mod.use_deform_preserve_volume = True  # DQS, matches Unity

    for pb in b_arm.pose.bones:
        pb.rotation_mode = "QUATERNION"

    order = sorted(shared, key=lambda nm: (_depth(b_arm, nm), nm))
    # Pass 1: compute + store pose_locals with PURE quaternion math (no
    # depsgraph reads): each bone's world is accumulated from the stored pose
    # locals and Blender's own rest, so parents are never stale.
    rest_world = {}
    parent_of = {}
    for name in order:
        b = b_arm.data.bones[name]
        rest_world[name] = (b_arm.matrix_world @ b.matrix_local).to_quaternion()
        parent_of[name] = b.parent.name if b.parent else None
    identity = Quaternion((1.0, 0.0, 0.0, 0.0))
    stored: dict[str, list] = {nm: [] for nm in shared}
    for k in range(n_keys):
        world: dict[str, Quaternion] = {}
        for name in order:
            q_target = Quaternion([float(v) for v in expected_worlds[name][k]])
            p_name = parent_of[name]
            p_world = world.get(p_name) if p_name else identity
            if p_name is None:
                rest_local = rest_world[name]
            else:
                rest_local = (rest_world.get(p_name) or identity).inverted() @ rest_world[name]
            pose_local = rest_local.inverted() @ p_world.inverted() @ q_target
            stored[name].append([float(v) for v in pose_local])
            world[name] = p_world @ rest_local @ pose_local  # == q_target by construction

    # Pass 2: write keyframe values directly (keyframe_insert() snapshots a
    # possibly action-overridden value, so never use it here).
    b_arm.animation_data_create()
    act = bpy.data.actions.new("MeshyOurWalk")
    b_arm.animation_data.action = act
    for name in order:
        path = f'pose.bones["{name}"].rotation_quaternion'
        fcs = [act.fcurves.new(path, index=i) for i in range(4)]
        for k in range(n_keys):
            v = stored[name][k]
            for i in range(4):
                fcs[i].keyframe_points.insert(frame=k, value=float(v[i]))

    # Lit scene + camera framed for a ~1.7m unit.
    bpy.context.scene.render.engine = "BLENDER_EEVEE"
    bpy.context.scene.eevee.taa_render_samples = 24
    bpy.context.scene.render.resolution_x = 720
    bpy.context.scene.render.resolution_y = 720
    bpy.context.scene.render.image_settings.file_format = "PNG"
    _setup_lit_scene()
    cam = setup_pose_camera(
        {"camera": {"axis": "iso", "isoAzimuthDeg": 40.0, "isoElevationDeg": 30.0, "distance": 3.0, "orthoScale": 4.2, "rootYawDeg": 0.0, "lookAtZ": 0.9}},
        b_arm,
        bpy_module=bpy,
    )

    n_out = 12
    frames = [int(round(i * (n_keys - 1) / (n_out - 1))) for i in range(n_out)]
    pose_samples = []
    readback_worst = []
    for i, k in enumerate(frames):
        bpy.context.scene.frame_set(k)
        bpy.context.view_layer.update()
        worst = []
        for name in shared:
            got = (b_arm.matrix_world @ b_arm.pose.bones[name].matrix).to_quaternion()
            exp = Quaternion([float(v) for v in expected_worlds[name][k]])
            d = abs(float(got.dot(exp)))
            ang = 2 * math.degrees(math.acos(min(1.0, d)))
            worst.append((ang, name))
        worst.sort(reverse=True)
        readback_worst.append({"frame": k, "worst3": [(nm, round(a, 3)) for a, nm in worst[:3]]})
        pose_samples.append(
            {
                "frame": k,
                "LeftUpLeg_world": [round(v, 4) for v in (b_arm.matrix_world @ b_arm.pose.bones["LeftUpLeg"].matrix).to_quaternion()],
                "RightArm_world": [round(v, 4) for v in (b_arm.matrix_world @ b_arm.pose.bones["RightArm"].matrix).to_quaternion()],
                "Hips_world": [round(v, 4) for v in (b_arm.matrix_world @ b_arm.pose.bones["Hips"].matrix).to_quaternion()],
            }
        )
        bpy.context.scene.render.filepath = str(out / f"ourwalk_{i:02d}.png")
        bpy.ops.render.render(write_still=True)
        h = hashlib.md5((out / f"ourwalk_{i:02d}.png").read_bytes()).hexdigest()[:10]
        pose_samples[-1]["png_md5"] = h

    diag = {
        "ok": True,
        "n_keys": n_keys,
        "times": times,
        "readback_worst": readback_worst,
        "pose_samples": pose_samples,
    }
    (out / "diagnostics.json").write_text(json.dumps(diag, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out.resolve()), "keys": n_keys, "frames": len(frames)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
