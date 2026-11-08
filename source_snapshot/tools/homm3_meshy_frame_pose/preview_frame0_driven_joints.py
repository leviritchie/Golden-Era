#!/usr/bin/env python3
"""
RETIRED as the primary pose hook.

This drove frame_00_rigged with AABB / aim-preserve-roll joints from other
per-frame Meshy meshes. That throws away Meshy's and the painted frames' pose
understanding and caused bind/roll explosions.

Primary hooks instead:
  - tools/homm3_meshy_frame_pose/preview_painted_vs_meshy_meshes.py
    (painted vs Meshy mesh as-is)
  - tools/homm3_silhouette_pose_fit/run_fit.py + DWPose on painted frames
    driving master/hobgoblin_apose_mace_attach.glb

Kept for archaeology only. Do not extend this path for attack-read work.

  blender -b --python preview_frame0_driven_joints.py -- \\
    --master .../rigged/frame_00_rigged.glb \\
    --rigged-dir .../rigged \\
    --sprites-dir .../source_attack_frames_painted_g11 \\
    --output-dir .../out_meshy_t2_per_frame_g11/preview_frame0_driven
"""
from __future__ import annotations

import json
import math
import sys
import traceback
from pathlib import Path

import bpy
import numpy as np
from mathutils import Quaternion

_TOOL = Path(__file__).resolve().parent
_SIL = _TOOL.parent / "homm3_silhouette_pose_fit"
for p in (_TOOL, _SIL):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from homm3_pose_camera import setup_pose_camera  # noqa: E402
from rig_frame0_shared_skeleton import HIERARCHY  # noqa: E402


def _argv() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def _parse() -> dict:
    args = _argv()
    out = {
        "master": None,
        "riggedDir": None,
        "spritesDir": None,
        "outputDir": None,
        "start": 0,
        "end": 7,
        "hold": 4,
        "camera": {
            "axis": "iso",
            "isoAzimuthDeg": 40.0,
            "isoElevationDeg": 30.0,
            "distance": 3.0,
            "orthoScale": 2.6,
            "rootYawDeg": 0.0,
        },
    }
    i = 0
    while i < len(args):
        if args[i] == "--master" and i + 1 < len(args):
            out["master"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--rigged-dir" and i + 1 < len(args):
            out["riggedDir"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--sprites-dir" and i + 1 < len(args):
            out["spritesDir"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--output-dir" and i + 1 < len(args):
            out["outputDir"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--start" and i + 1 < len(args):
            out["start"] = int(args[i + 1])
            i += 2
        elif args[i] == "--end" and i + 1 < len(args):
            out["end"] = int(args[i + 1])
            i += 2
        elif args[i] == "--hold" and i + 1 < len(args):
            out["hold"] = int(args[i + 1])
            i += 2
        else:
            i += 1
    for key in ("master", "riggedDir", "spritesDir", "outputDir"):
        if not out[key]:
            raise SystemExit(f"need --master --rigged-dir --sprites-dir --output-dir (missing {key})")
    return out


def _clear() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _force_unlit_baked(mesh_obj) -> None:
    for mat in mesh_obj.data.materials:
        if mat is None or not mat.use_nodes:
            continue
        nt = mat.node_tree
        nodes = nt.nodes
        links = nt.links
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


def _bone_heads_world(arm) -> dict[str, list[float]]:
    out = {}
    for pb in arm.pose.bones:
        h = arm.matrix_world @ pb.head
        out[pb.name] = [float(h.x), float(h.y), float(h.z)]
    return out


def _extract_joints(glb: Path) -> dict[str, list[float]]:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    added = [o for o in bpy.data.objects if o not in before]
    arms = [o for o in added if o.type == "ARMATURE"]
    if not arms:
        raise RuntimeError(f"no armature in {glb}")
    bpy.context.view_layer.update()
    joints = _bone_heads_world(arms[0])
    for o in added:
        bpy.data.objects.remove(o, do_unlink=True)
    return joints


def _reset_pose(arm) -> None:
    arm.location = (0.0, 0.0, 0.0)
    arm.rotation_mode = "XYZ"
    arm.rotation_euler = (0.0, 0.0, 0.0)
    arm.scale = (1.0, 1.0, 1.0)
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = Quaternion()
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def _children_map() -> dict[str, list[str]]:
    kids: dict[str, list[str]] = {n: [] for n, _ in HIERARCHY}
    for name, parent in HIERARCHY:
        if parent:
            kids[parent].append(name)
    return kids


def _aim_bones_preserve_roll(
    arm,
    targets: dict[str, list[float]],
    *,
    strength: float = 0.45,
) -> list[str]:
    """
    Rotate each bone just enough to aim its existing axis toward the target
    head→child direction. Uses rotation_difference so bind roll is preserved.
    `strength` blends toward the target (1=full aim); full aim from foreign
    per-frame AABB joints over-rotates this Meshy mesh into collapse.
    """
    from mathutils import Matrix, Vector

    kids = _children_map()
    strength = float(max(0.0, min(1.0, strength)))
    aimed: list[str] = []
    for name, _parent in HIERARCHY:
        child_names = kids.get(name) or []
        if not child_names:
            continue
        child = child_names[0]
        if name not in targets or child not in targets:
            continue
        pb = arm.pose.bones.get(name)
        if pb is None:
            continue

        bpy.context.view_layer.update()
        head_w = arm.matrix_world @ pb.head
        tail_w = arm.matrix_world @ pb.tail
        cur_dir = (tail_w - head_w)
        if cur_dir.length < 1e-8:
            continue
        cur_dir.normalize()

        desired = Vector(targets[child]) - Vector(targets[name])
        if desired.length < 1e-8:
            continue
        desired.normalize()

        corr = cur_dir.rotation_difference(desired)
        if strength < 1.0:
            corr = Quaternion((1.0, 0.0, 0.0, 0.0)).slerp(corr, strength)
        world = arm.matrix_world @ pb.matrix
        loc, rot_q, scale = world.decompose()
        new_world = (
            Matrix.Translation(loc)
            @ (corr @ rot_q).to_matrix().to_4x4()
            @ Matrix.Diagonal((scale.x, scale.y, scale.z, 1.0))
        )
        local = arm.convert_space(pose_bone=pb, matrix=new_world, from_space="WORLD", to_space="LOCAL")
        _loc, quat, _scale = local.decompose()
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = quat
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
        aimed.append(name)
        bpy.context.view_layer.update()
    return aimed


def _apply_frame_pose(
    master_arm,
    *,
    frame_index: int,
    targets: dict[str, list[float]] | None,
    aim_strength: float = 0.45,
) -> dict:
    """
    Frame 0: leave master at true bind/rest pose.
    Frames 1+: damped aim toward that frame's joint directions (preserve bind roll).
    """
    _reset_pose(master_arm)
    if frame_index == 0 or not targets:
        return {
            "mode": "true_rest",
            "aimedBones": [],
            "meanHeadError": 0.0,
            "maxHeadError": 0.0,
            "aimStrength": 0.0,
        }

    aimed = _aim_bones_preserve_roll(master_arm, targets, strength=aim_strength)

    hips = master_arm.pose.bones.get("Hips")
    if hips is not None and "Hips" in targets:
        from mathutils import Vector

        cur = master_arm.matrix_world @ hips.head
        tgt = Vector(targets["Hips"])
        # Only horizontal/height nudge at reduced strength — full snap fights the dampened pose.
        delta = (tgt - cur) * float(aim_strength)
        master_arm.location = master_arm.location + delta
        bpy.context.view_layer.update()

    achieved = _bone_heads_world(master_arm)
    errs = []
    for name, tgt in targets.items():
        if name not in achieved:
            continue
        a = np.asarray(achieved[name], dtype=np.float64)
        b = np.asarray(tgt, dtype=np.float64)
        errs.append(float(np.linalg.norm(a - b)))

    return {
        "mode": "aim_preserve_roll",
        "aimedBones": aimed,
        "meanHeadError": float(np.mean(errs)) if errs else 0.0,
        "maxHeadError": float(np.max(errs)) if errs else 0.0,
        "aimStrength": float(aim_strength),
    }


def run(opts: dict) -> dict:
    from PIL import Image, ImageDraw

    out_dir = Path(opts["outputDir"])
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # Pass 1: extract joint heads from each per-frame rigged GLB (temporary scene).
    joints_by_frame: dict[str, dict[str, list[float]]] = {}
    _clear()
    for fi in range(int(opts["start"]), int(opts["end"]) + 1):
        glb = Path(opts["riggedDir"]) / f"frame_{fi:02d}_rigged.glb"
        if not glb.is_file():
            raise RuntimeError(f"missing rigged glb: {glb}")
        joints_by_frame[f"{fi:02d}"] = _extract_joints(glb)
        print(f"[preview] extracted joints frame {fi:02d}", flush=True)

    joints_path = out_dir / "joints_per_frame.json"
    joints_path.write_text(json.dumps(joints_by_frame, indent=2), encoding="utf-8")

    # Pass 2: load master once, drive + render.
    _clear()
    bpy.ops.import_scene.gltf(filepath=str(opts["master"]))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    if arm.animation_data:
        arm.animation_data_clear()

    world = bpy.data.worlds.new("PreviewWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.08, 0.09, 0.12, 1)
    bg.inputs["Strength"].default_value = 0.0

    job = {"camera": opts["camera"], "mirror": {}}
    setup_pose_camera(job, arm, bpy_module=bpy)
    _force_unlit_baked(mesh)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 8
    scene.render.resolution_x = 480
    scene.render.resolution_y = 420
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False

    hold = int(opts["hold"])
    composed = []
    drive_report = []
    sprites_dir = Path(opts["spritesDir"])

    for fi in range(int(opts["start"]), int(opts["end"]) + 1):
        key = f"{fi:02d}"
        fit = _apply_frame_pose(
            arm,
            frame_index=fi,
            targets=joints_by_frame.get(key),
        )
        render_path = frames_dir / f"mesh_{fi:02d}.png"
        scene.render.filepath = str(render_path)
        bpy.ops.render.render(write_still=True)

        mesh_im = Image.open(render_path).convert("RGBA")
        spr_path = sprites_dir / f"frame_{fi:02d}.png"
        if not spr_path.is_file():
            raise RuntimeError(f"missing sprite: {spr_path}")
        spr = Image.open(spr_path).convert("RGBA")
        target_h = mesh_im.height
        scale = target_h / max(spr.height, 1)
        spr_big = spr.resize((max(1, int(spr.width * scale)), target_h), Image.Resampling.NEAREST)
        pad = Image.new("RGBA", (spr_big.width + 40, target_h), (20, 22, 28, 255))
        pad.paste(spr_big, (20, 0), spr_big)

        gap = 16
        label_h = 36
        total_w = pad.width + gap + mesh_im.width
        total_h = target_h + label_h
        canvas = Image.new("RGBA", (total_w, total_h), (20, 22, 28, 255))
        canvas.paste(pad, (0, label_h), pad)
        canvas.paste(mesh_im, (pad.width + gap, label_h), mesh_im)
        draw = ImageDraw.Draw(canvas)
        draw.text((12, 8), f"Painted frame {fi}", fill=(220, 220, 220, 255))
        right_label = (
            "Frame0 mesh (true rest)"
            if fit.get("mode") == "true_rest"
            else f"Frame0 mesh @ aim-roll f{fi}"
        )
        draw.text((pad.width + gap + 12, 8), right_label, fill=(220, 220, 220, 255))
        side_path = frames_dir / f"side_{fi:02d}.png"
        canvas.convert("RGB").save(side_path)
        for _ in range(hold):
            composed.append(canvas.convert("RGB"))
        rec = {"frame": fi, "meshPng": str(render_path).replace("\\", "/"), **fit}
        drive_report.append(rec)
        print(
            f"[preview] frame {fi} mode={fit['mode']} meanHeadErr={fit['meanHeadError']:.4f} max={fit['maxHeadError']:.4f}",
            flush=True,
        )

    gif_path = out_dir / "attack_g11_side_by_side.gif"
    duration_ms = max(1, int(round(1000.0 / (12.0 * hold))))
    composed[0].save(
        gif_path,
        save_all=True,
        append_images=composed[1:],
        duration=duration_ms,
        loop=0,
    )

    meta = {
        "gif": str(gif_path).replace("\\", "/"),
        "jointsJson": str(joints_path).replace("\\", "/"),
        "master": str(opts["master"]).replace("\\", "/"),
        "method": "frame0_true_rest_plus_aim_preserve_roll",
        "hold": hold,
        "drive": drive_report,
        "camera": opts["camera"],
        "proof": "generated artifact validated — f0 true rest; f1-7 aim-preserve-roll from per-frame joints; attack-read unproven",
    }
    (out_dir / "preview_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "gif": meta["gif"]}, indent=2), flush=True)
    return meta


def main() -> int:
    try:
        run(_parse())
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
