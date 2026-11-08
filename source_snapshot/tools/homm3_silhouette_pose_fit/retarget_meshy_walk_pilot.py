#!/usr/bin/env python3
"""A/B pilot: drive OUR owned-skinned crusader mesh with MESHY's own Walking clip.

Loads the Meshy merged-animations GLB and our strong-rigged crusader GLB,
copies the Walking clip's per-bone rotation tracks (and Hips root translation,
scaled to our units) onto our armature by bone name, then renders lit DQS
frames of OUR mesh so the user can judge mesh+motion without our DEF-fit.

Run from Blender:
  blender -b --python retarget_meshy_walk_pilot.py -- --out <dir>
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

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
OUR_MASTER = Path(
    r"V:/Games/Olden Era Playtest Tweak/artifacts/crusader_pose_pipeline"
    r"/owned_bind/crusader_enhanced_rigged_strong.glb"
)
# Meshy's Hips translation track is in cm (mesh bbox 0..1.7 m); ours is meters
# (bbox 0..1.4 m). Key only deltas from frame 0 so our bind height is preserved.
HIPS_CM_TO_OURS = 0.01 * (1.4 / 1.7)


def _glb(path: Path):
    d = path.read_bytes()
    off = 12
    chunks = []
    while off < len(d):
        clen, ctype = struct.unpack("<I4s", d[off : off + 8])
        chunks.append((ctype, d[off + 8 : off + 8 + clen]))
        off += 8 + clen
    j = json.loads(chunks[0][1].decode("utf-8"))
    return j, next(b for c, b in chunks if c == b"BIN\x00")


def _acc(doc, binbuf, i):
    a = doc["accessors"][i]
    bv = doc["bufferViews"][a["bufferView"]]
    buf = binbuf[bv["byteOffset"] : bv["byteOffset"] + bv["byteLength"]]
    ncomp = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    dt = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2", 5125: "u4", 5126: "f4"}[a["componentType"]]
    import numpy as np

    return np.frombuffer(buf, dtype=np.dtype(dt), count=a["count"] * ncomp).reshape(-1, ncomp)


def _walk_tracks():
    doc, binbuf = _glb(MESHY_ANIM)
    j = doc
    names = {i: n.get("name") for i, n in enumerate(j["nodes"])}
    anim = next(a for a in j["animations"] if "alk" in (a.get("name") or ""))
    rotations: dict[str, list] = {}
    translations: dict[str, list] = {}
    times = None
    for ch in anim["channels"]:
        name = names[ch["target"]["node"]]
        path = ch["target"]["path"]
        samp = anim["samplers"][ch["sampler"]]
        t = _acc(doc, binbuf, samp["input"])[:, 0]
        if times is None:
            times = t
        if path == "rotation":
            rotations[name] = _acc(doc, binbuf, samp["output"])
        elif path == "translation":
            translations[name] = _acc(doc, binbuf, samp["output"])
    return times, rotations, translations


def main() -> int:
    out = Path(ARGS[1] if len(ARGS) > 1 else "artifacts/crusader_pose_pipeline/out_fit_meshywalk_pilot")
    out.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(OUR_MASTER.resolve()))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    for mod in mesh.modifiers:
        if mod.type == "ARMATURE":
            mod.use_deform_preserve_volume = True  # DQS, matches Unity

    times, rotations, translations = _walk_tracks()
    n_keys = len(times)
    bpy.context.scene.frame_start = 0
    bpy.context.scene.frame_end = n_keys - 1
    bpy.context.scene.render.fps = int(round(n_keys / max(times[-1], 1e-6)))

    for bone in arm.pose.bones:
        bone.rotation_mode = "QUATERNION"
    for k in range(n_keys):
        bpy.context.scene.frame_set(k)
        for name, quats in rotations.items():
            pb = arm.pose.bones.get(name)
            if pb is None or k >= len(quats):
                continue
            q = quats[k]
            pb.rotation_quaternion = Quaternion((float(q[3]), float(q[0]), float(q[1]), float(q[2])))
            pb.keyframe_insert(data_path="rotation_quaternion", frame=k)
    hips0 = translations.get("Hips")
    if hips0 is not None:
        hips0 = hips0[0]
        for k in range(n_keys):
            if k >= len(hips0):
                continue
            bpy.context.scene.frame_set(k)
            pb = arm.pose.bones.get("Hips")
            if pb is None:
                break
            d = translations["Hips"][k] - hips0
            pb.location = Vector(
                (float(d[0]) * HIPS_CM_TO_OURS, float(d[1]) * HIPS_CM_TO_OURS, float(d[2]) * HIPS_CM_TO_OURS)
            )
            pb.keyframe_insert(data_path="location", frame=k)

    # --- diagnostics: prove the action exists and keyframes were inserted ---
    act = arm.animation_data.action if (arm.animation_data and arm.animation_data.action) else None
    diag = {
        "n_keys": n_keys,
        "rot_channels": len(rotations),
        "tr_channels": len(translations),
        "action": act.name if act else None,
        "fcurves": len(act.fcurves) if act else 0,
        "bone_names_pose": sorted(b.name for b in arm.pose.bones),
    }
    if act:
        for bn in ("Hips", "Spine", "LeftUpLeg", "RightArm", "Head", "neck"):
            path = f'pose.bones["{bn}"].rotation_quaternion'
            diag[f"fcurves_{bn}"] = sum(1 for fc in act.fcurves if fc.data_path == path)
    print("DIAG " + json.dumps(diag), flush=True)

    # Lit scene: same recipe as the accepted strong-fit previews.
    bpy.context.scene.render.engine = "BLENDER_EEVEE"
    bpy.context.scene.eevee.taa_render_samples = 24
    bpy.context.scene.render.resolution_x = 720
    bpy.context.scene.render.resolution_y = 720
    bpy.context.scene.render.image_settings.file_format = "PNG"
    _setup_lit_scene()
    cam = setup_pose_camera(
        {"camera": {"axis": "iso", "isoAzimuthDeg": 40.0, "isoElevationDeg": 30.0, "distance": 3.0, "orthoScale": 4.2, "rootYawDeg": 0.0}},
        arm,
        bpy_module=bpy,
    )

    frames = [int(round(i * (n_keys - 1) / 11)) for i in range(12)]
    pose_samples = []
    for i, k in enumerate(frames):
        bpy.context.scene.frame_set(k)
        bpy.context.view_layer.update()
        pose_samples.append(
            {
                "frame": k,
                "LeftUpLeg": [round(v, 4) for v in arm.pose.bones["LeftUpLeg"].rotation_quaternion],
                "RightArm": [round(v, 4) for v in arm.pose.bones["RightArm"].rotation_quaternion],
                "Hips_loc": [round(v, 4) for v in arm.pose.bones["Hips"].location],
            }
        )
        bpy.context.scene.render.filepath = str(out / f"meshywalk_{i:02d}.png")
        bpy.ops.render.render(write_still=True)
        h = hashlib.md5((out / f"meshywalk_{i:02d}.png").read_bytes()).hexdigest()[:10]
        pose_samples[-1]["png_md5"] = h

    diag["pose_samples"] = pose_samples
    (out / "diagnostics.json").write_text(json.dumps(diag, indent=2), encoding="utf-8")

    print(json.dumps({"ok": True, "out": str(out.resolve()), "keys": n_keys, "frames": len(frames)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
