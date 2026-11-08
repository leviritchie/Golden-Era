#!/usr/bin/env python3
"""
Hand-author CHGOBL attack g11 on A-pose + mace-attach master via Mixamo euler deltas.

No IK (visual_transform_apply was unreliable). Axis probe notes (Left = strike/+X):
  LeftShoulder X-  → hand high
  LeftArm Z-       → hand high +X
  LeftArm X-       → hand forward-high (-Y)
  Spine X+         → lean forward into smash

Blender:
  blender -b --python author_apose_mace_attack_clip.py -- \\
    --master .../hobgoblin_apose_mace_attach.glb \\
    --out .../out_attack_g11_authored_apose_mace
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Euler

_TOOL = Path(__file__).resolve().parent
_POSE = _TOOL.parent / "homm3_silhouette_pose_fit"
if str(_POSE) not in sys.path:
    sys.path.insert(0, str(_POSE))
from homm3_pose_camera import setup_pose_camera  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MASTER = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/master/hobgoblin_apose_mace_attach.glb"
DEFAULT_OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_attack_g11_authored_apose_mace"
SPRITE_DIR = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/source_attack_frames/canonical_group_11"

OPTIMIZE = [
    "Hips",
    "Spine02",
    "Spine01",
    "Spine",
    "neck",
    "Head",
    "LeftShoulder",
    "LeftArm",
    "LeftForeArm",
    "LeftHand",
    "RightShoulder",
    "RightArm",
    "RightForeArm",
    "RightHand",
    "LeftUpLeg",
    "LeftLeg",
    "RightUpLeg",
    "RightLeg",
]

# Bone -> (dx, dy, dz) radians added to rest XYZ euler. Attack read from painted/canonical g11.
# f0 ready → f3 deep backswing → f4 apex overhead → f5–f6 smash → f7 recover.
FRAMES: list[dict[str, tuple[float, float, float]]] = [
    # f0 ready — slight crouch, mace at hip/waist (near rest; small polish)
    {
        "Hips": (0.05, 0.0, 0.06),
        "Spine02": (0.04, 0.0, 0.02),
        "Spine01": (0.05, 0.0, 0.0),
        "Spine": (0.06, 0.0, 0.02),
        "LeftShoulder": (-0.15, 0.05, 0.10),
        "LeftArm": (0.10, 0.05, -0.20),
        "LeftForeArm": (0.15, 0.0, -0.25),
        "LeftHand": (0.0, 0.4, 0.2),
        "RightShoulder": (0.05, -0.05, -0.08),
        "RightArm": (0.25, -0.15, 0.35),
        "RightForeArm": (0.45, 0.0, 0.20),
        "RightHand": (0.0, -0.2, 0.0),
        "LeftUpLeg": (-0.12, 0.04, 0.06),
        "LeftLeg": (0.22, 0.0, 0.0),
        "RightUpLeg": (-0.12, -0.04, -0.06),
        "RightLeg": (0.22, 0.0, 0.0),
    },
    # f1 tip rising — start lifting strike arm
    {
        "Hips": (0.02, 0.04, 0.04),
        "Spine02": (-0.02, 0.03, 0.03),
        "Spine01": (-0.04, 0.02, 0.02),
        "Spine": (-0.05, 0.04, 0.04),
        "neck": (-0.05, 0.0, 0.03),
        "Head": (-0.06, 0.0, 0.04),
        "LeftShoulder": (-0.45, 0.15, 0.20),
        "LeftArm": (-0.25, 0.10, -0.55),
        "LeftForeArm": (0.35, 0.0, -0.35),
        "LeftHand": (-0.6, 0.4, 0.2),
        "RightShoulder": (-0.25, -0.12, -0.18),
        "RightArm": (-0.20, -0.12, 0.50),
        "RightForeArm": (0.55, 0.0, 0.22),
        "RightHand": (0.0, -0.15, 0.1),
        "LeftUpLeg": (-0.14, 0.04, 0.05),
        "LeftLeg": (0.28, 0.0, 0.0),
        "RightUpLeg": (-0.14, -0.04, -0.05),
        "RightLeg": (0.28, 0.0, 0.0),
    },
    # f2 tip high — LeftHand X- flips tip ABOVE hand
    {
        "Hips": (-0.02, 0.08, 0.02),
        "Spine02": (-0.10, 0.06, 0.05),
        "Spine01": (-0.14, 0.06, 0.04),
        "Spine": (-0.18, 0.08, 0.06),
        "neck": (-0.12, 0.04, 0.05),
        "Head": (-0.12, 0.05, 0.06),
        "LeftShoulder": (-0.85, 0.35, 0.35),
        "LeftArm": (-0.55, 0.20, -0.95),
        "LeftForeArm": (0.55, 0.10, -0.45),
        "LeftHand": (-1.2, 0.35, 0.15),
        "RightShoulder": (-0.70, -0.25, -0.30),
        "RightArm": (-0.55, -0.20, 0.85),
        "RightForeArm": (0.70, 0.0, 0.28),
        "RightHand": (0.1, -0.2, 0.12),
        "LeftUpLeg": (-0.18, 0.05, 0.06),
        "LeftLeg": (0.35, 0.0, 0.0),
        "RightUpLeg": (-0.18, -0.05, -0.06),
        "RightLeg": (0.35, 0.0, 0.0),
    },
    # f3 deep backswing — tip up/back, support hand on shaft
    {
        "Hips": (-0.06, 0.12, 0.0),
        "Spine02": (-0.18, 0.10, 0.08),
        "Spine01": (-0.28, 0.12, 0.08),
        "Spine": (-0.38, 0.14, 0.10),
        "neck": (-0.22, 0.08, 0.08),
        "Head": (-0.25, 0.10, 0.10),
        "LeftShoulder": (-1.15, 0.55, 0.45),
        "LeftArm": (-0.75, 0.35, -1.15),
        "LeftForeArm": (0.65, 0.15, -0.55),
        "LeftHand": (-1.25, 0.45, 0.2),
        "RightShoulder": (-0.95, -0.35, -0.40),
        "RightArm": (-0.75, -0.30, 1.00),
        "RightForeArm": (0.85, 0.05, 0.40),
        "RightHand": (0.15, -0.30, 0.2),
        "LeftUpLeg": (-0.22, 0.06, 0.08),
        "LeftLeg": (0.42, 0.0, 0.0),
        "RightUpLeg": (-0.22, -0.06, -0.08),
        "RightLeg": (0.42, 0.0, 0.0),
    },
    # f4 apex — tip high forward; two-hand overhead
    {
        "Hips": (0.05, -0.02, 0.04),
        "Spine02": (0.06, -0.02, 0.04),
        "Spine01": (0.10, -0.02, 0.03),
        "Spine": (0.12, -0.04, 0.05),
        "neck": (0.04, -0.03, 0.03),
        "Head": (0.05, -0.04, 0.04),
        "LeftShoulder": (-1.25, 0.15, 0.55),
        "LeftArm": (-0.95, 0.15, -1.25),
        "LeftForeArm": (0.40, 0.0, -0.35),
        "LeftHand": (-1.15, 0.25, 0.15),
        "RightShoulder": (-1.05, -0.18, -0.50),
        "RightArm": (-0.90, -0.15, 1.05),
        "RightForeArm": (0.60, 0.0, 0.30),
        "RightHand": (0.1, -0.25, 0.18),
        "LeftUpLeg": (-0.16, 0.04, 0.05),
        "LeftLeg": (0.32, 0.0, 0.0),
        "RightUpLeg": (-0.16, -0.04, -0.05),
        "RightLeg": (0.32, 0.0, 0.0),
    },
    # f5 smash — lean + tip DOWN/forward (LeftHand X+)
    {
        "Hips": (0.20, -0.12, 0.12),
        "Spine02": (0.30, -0.06, 0.02),
        "Spine01": (0.50, -0.10, 0.02),
        "Spine": (0.70, -0.12, 0.04),
        "neck": (0.22, -0.08, -0.02),
        "Head": (0.24, -0.10, -0.04),
        "LeftShoulder": (0.12, 0.12, 0.22),
        "LeftArm": (0.25, -1.15, -0.25),
        "LeftForeArm": (0.25, 0.0, -0.45),
        "LeftHand": (1.0, 0.2, 0.1),
        "RightShoulder": (0.10, -0.12, -0.18),
        "RightArm": (0.30, 0.70, 0.22),
        "RightForeArm": (0.45, 0.0, 0.12),
        "RightHand": (0.1, -0.15, 0.08),
        "LeftUpLeg": (-0.35, 0.10, 0.12),
        "LeftLeg": (0.70, 0.0, 0.0),
        "RightUpLeg": (-0.35, -0.10, -0.12),
        "RightLeg": (0.70, 0.0, 0.0),
    },
    # f6 follow-through
    {
        "Hips": (0.16, -0.10, 0.10),
        "Spine02": (0.24, -0.05, 0.02),
        "Spine01": (0.40, -0.08, 0.02),
        "Spine": (0.55, -0.10, 0.03),
        "neck": (0.16, -0.06, -0.01),
        "Head": (0.18, -0.07, -0.02),
        "LeftShoulder": (0.08, 0.10, 0.18),
        "LeftArm": (0.20, -1.05, -0.22),
        "LeftForeArm": (0.28, 0.0, -0.40),
        "LeftHand": (0.85, 0.18, 0.08),
        "RightShoulder": (0.08, -0.10, -0.15),
        "RightArm": (0.25, 0.60, 0.18),
        "RightForeArm": (0.42, 0.0, 0.10),
        "RightHand": (0.08, -0.12, 0.06),
        "LeftUpLeg": (-0.30, 0.08, 0.10),
        "LeftLeg": (0.60, 0.0, 0.0),
        "RightUpLeg": (-0.30, -0.08, -0.10),
        "RightLeg": (0.60, 0.0, 0.0),
    },
    # f7 recovery toward ready
    {
        "Hips": (0.06, -0.02, 0.05),
        "Spine02": (0.06, -0.01, 0.02),
        "Spine01": (0.08, -0.01, 0.01),
        "Spine": (0.10, -0.02, 0.02),
        "neck": (0.02, -0.01, 0.0),
        "Head": (0.02, -0.01, 0.0),
        "LeftShoulder": (-0.20, 0.08, 0.20),
        "LeftArm": (0.15, 0.08, -0.35),
        "LeftForeArm": (0.20, 0.0, -0.30),
        "LeftHand": (0.3, 0.3, 0.1),
        "RightShoulder": (0.05, -0.08, -0.12),
        "RightArm": (0.20, -0.10, 0.30),
        "RightForeArm": (0.40, 0.0, 0.15),
        "RightHand": (0.05, -0.12, 0.05),
        "LeftUpLeg": (-0.14, 0.04, 0.05),
        "LeftLeg": (0.28, 0.0, 0.0),
        "RightUpLeg": (-0.14, -0.04, -0.05),
        "RightLeg": (0.28, 0.0, 0.0),
    },
]


def _parse() -> dict:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    out = {"master": DEFAULT_MASTER, "out": DEFAULT_OUT, "width": 504, "height": 456}
    i = 0
    while i < len(argv):
        if argv[i] == "--master" and i + 1 < len(argv):
            out["master"] = Path(argv[i + 1])
            i += 2
        elif argv[i] == "--out" and i + 1 < len(argv):
            out["out"] = Path(argv[i + 1])
            i += 2
        else:
            i += 1
    return out


def _force_unlit(mesh_obj) -> None:
    for mat in mesh_obj.data.materials:
        if mat is None or not mat.use_nodes:
            continue
        nt = mat.node_tree
        nodes, links = nt.nodes, nt.links
        out = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
        bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
        if out is None or bsdf is None:
            continue
        base_in = bsdf.inputs.get("Base Color")
        emit = nodes.new(type="ShaderNodeEmission")
        emit.location = (bsdf.location.x + 200.0, bsdf.location.y)
        emit.inputs["Strength"].default_value = 1.0
        if base_in is not None and base_in.is_linked:
            links.new(base_in.links[0].from_socket, emit.inputs["Color"])
        elif base_in is not None:
            emit.inputs["Color"].default_value = tuple(base_in.default_value)
        for link in list(out.inputs["Surface"].links):
            links.remove(link)
        links.new(emit.outputs["Emission"], out.inputs["Surface"])


def _capture_rest(arm) -> dict:
    rest = {}
    for name in arm.pose.bones.keys():
        pb = arm.pose.bones[name]
        pb.rotation_mode = "XYZ"
        rest[name] = pb.rotation_euler.copy()
    return rest


def _apply_pose(arm, rest: dict, deltas: dict[str, tuple[float, float, float]]) -> None:
    for name, e in rest.items():
        pb = arm.pose.bones[name]
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = e.copy()
    for name, (dx, dy, dz) in deltas.items():
        if name not in arm.pose.bones:
            continue
        pb = arm.pose.bones[name]
        base = rest[name]
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = Euler((base.x + dx, base.y + dy, base.z + dz), "XYZ")


def _pose_vector(arm, rest: dict) -> list[float]:
    vec: list[float] = []
    for name in OPTIMIZE:
        pb = arm.pose.bones[name]
        pb.rotation_mode = "XYZ"
        base = rest[name]
        e = pb.rotation_euler
        vec.extend([e.x - base.x, e.y - base.y, e.z - base.z])
    return vec


def _render(path: Path, width: int, height: int) -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.film_transparent = True
    scene.render.filepath = str(path)
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    bpy.ops.render.render(write_still=True)


def main() -> int:
    opts = _parse()
    master = Path(opts["master"])
    master = master.resolve() if master.is_absolute() else (ROOT / master).resolve()
    out_dir = Path(opts["out"])
    out_dir = out_dir.resolve() if out_dir.is_absolute() else (ROOT / out_dir).resolve()
    preview = out_dir / "preview" / "frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    preview.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(master))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    for m in meshes:
        _force_unlit(m)

    job = {
        "unitSid": "h3_hobgoblin",
        "clipId": "attack_g11",
        "fps": 12,
        "masterGlb": str(master.relative_to(ROOT)).replace("\\", "/"),
        "outputDir": str(out_dir.relative_to(ROOT)).replace("\\", "/"),
        "optimizeBones": OPTIMIZE,
        "camera": {
            "axis": "iso",
            "isoAzimuthDeg": 40.0,
            "isoElevationDeg": 30.0,
            "distance": 3.0,
            "orthoScale": 2.6,
            "rootYawDeg": 0.0,
        },
        "frames": [
            {"path": str((SPRITE_DIR / f"frame_{i:02d}.png").relative_to(ROOT)).replace("\\", "/")}
            for i in range(8)
        ],
        "method": "manual_authored_euler",
        "notes": "Hand-authored Mixamo euler deltas on A-pose+mace master. Attack-read, not pixel fit.",
    }
    (out_dir / "job.resolved.json").write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")

    setup_pose_camera(job, arm, bpy_module=bpy)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    rest = _capture_rest(arm)

    pose_vectors: list[list[float]] = []
    tip_trace = []
    bpy.context.scene.frame_start = 0
    bpy.context.scene.frame_end = 7

    for fi, deltas in enumerate(FRAMES):
        _apply_pose(arm, rest, deltas)
        bpy.context.view_layer.update()
        lh = arm.matrix_world @ arm.pose.bones["LeftHand"].head
        tip_trace.append({"frame": fi, "leftHand": [round(lh.x, 3), round(lh.y, 3), round(lh.z, 3)]})
        vec = _pose_vector(arm, rest)
        pose_vectors.append(vec)
        for name in OPTIMIZE:
            arm.pose.bones[name].keyframe_insert(data_path="rotation_euler", frame=fi)
        bpy.context.scene.frame_set(fi)
        mesh_path = preview / f"mesh_{fi:02d}.png"
        _render(mesh_path, int(opts["width"]), int(opts["height"]))
        print(f"[author] f{fi} LeftHand={tip_trace[-1]['leftHand']} -> {mesh_path.name}", flush=True)

    bpy.ops.object.mode_set(mode="OBJECT")
    glb_path = out_dir / "attack_g11_authored.glb"
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    for m in meshes:
        m.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.gltf(
        filepath=str(glb_path),
        export_format="GLB",
        use_selection=True,
        export_animations=True,
        export_apply=False,
    )

    report = {
        "unitSid": "h3_hobgoblin",
        "clipId": "attack_g11",
        "method": "manual_authored_euler",
        "frameCount": 8,
        "losses": [0.0] * 8,
        "meanLoss": 0.0,
        "poseVectors": pose_vectors,
        "optimizeBones": OPTIMIZE,
        "wholeModelBones": [],
        "mirror": {"x": False, "y": False, "z": False, "reorientYawDeg": 0.0},
        "effectiveRootYawDeg": 0.0,
        "exportGlb": str(glb_path).replace("\\", "/"),
        "tipTrace": tip_trace,
        "proof": "generated artifact validated — hand-authored euler clip; not OE runtime proven",
        "notes": "Mace 100% LeftHand. Poses authored for overhead smash read vs canonical g11.",
        "frames": [{"frameIndex": i, "loss": 0.0} for i in range(8)],
    }
    (out_dir / "fit_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out_dir / "authored_pose_deltas.json").write_text(json.dumps(FRAMES, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out_dir), "tipTrace": tip_trace}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        raise SystemExit(1)
