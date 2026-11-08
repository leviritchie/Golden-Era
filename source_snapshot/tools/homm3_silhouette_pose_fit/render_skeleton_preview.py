#!/usr/bin/env python3
"""Render fitted clip skeleton projections (iso camera) for inspection."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Euler
from PIL import Image, ImageDraw

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_attack_g11_chroma75_motion_iso_meshy46_reskin"
SKEL = OUT / "preview" / "skeleton"
sys.path.insert(0, str(ROOT / "tools/homm3_silhouette_pose_fit"))
from homm3_pose_camera import effective_root_yaw_deg, setup_pose_camera  # noqa: E402

W = H = 512


def main() -> int:
    SKEL.mkdir(parents=True, exist_ok=True)
    job = json.loads((OUT / "job.resolved.json").read_text(encoding="utf-8"))
    report = json.loads((OUT / "fit_report.json").read_text(encoding="utf-8"))
    names = list(report["optimizeBones"])
    pose_vectors = report["poseVectors"]
    optimize_set = set(names)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(job["masterGlb"])))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    mesh.hide_render = True

    rest = {}
    for n in names:
        pb = arm.pose.bones[n]
        pb.rotation_mode = "XYZ"
        rest[n] = pb.rotation_euler.copy()

    cam = setup_pose_camera(job, arm, bpy_module=bpy)
    scene = bpy.context.scene
    root_yaw = math.radians(effective_root_yaw_deg(job))
    arm.rotation_mode = "XYZ"
    sprites = [Path(fr["path"]) for fr in job["frames"]]

    def apply_pose(vec) -> None:
        for i, n in enumerate(names):
            base = rest[n]
            pb = arm.pose.bones[n]
            pb.rotation_mode = "XYZ"
            pb.rotation_euler = Euler(
                (
                    base.x + float(vec[3 * i]),
                    base.y + float(vec[3 * i + 1]),
                    base.z + float(vec[3 * i + 2]),
                ),
                "XYZ",
            )
        arm.rotation_euler[2] = root_yaw
        bpy.context.view_layer.update()

    def project() -> tuple[list, dict]:
        segs = []
        joints = {}
        for b in arm.pose.bones:
            h = arm.matrix_world @ b.head
            t = arm.matrix_world @ b.tail
            ch = world_to_camera_view(scene, cam, h)
            ct = world_to_camera_view(scene, cam, t)
            a = (ch.x * W, (1.0 - ch.y) * H)
            c = (ct.x * W, (1.0 - ct.y) * H)
            segs.append((b.name, a, c, b.name in optimize_set))
            joints[b.name] = a
        return segs, joints

    def draw_skel(base_rgb: Image.Image, segs, joints, label: str) -> Image.Image:
        im = base_rgb.convert("RGBA")
        overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        for _name, a, b, opt in segs:
            col = (80, 255, 120, 230) if opt else (110, 150, 200, 140)
            d.line([a, b], fill=col, width=3 if opt else 2)
        for name, (x, y) in joints.items():
            if name not in optimize_set:
                continue
            r = 6 if name == "Bone_033" else 3
            fill = (255, 40, 255, 255) if name == "Bone_033" else (255, 220, 80, 255)
            d.ellipse([x - r, y - r, x + r, y + r], fill=fill)
        out = Image.alpha_composite(im, overlay).convert("RGB")
        ImageDraw.Draw(out).text((8, 8), label, fill=(240, 240, 240))
        return out

    side_frames = []
    skel_frames = []
    for fi, vec in enumerate(pose_vectors):
        apply_pose(vec)
        segs, joints = project()
        black = Image.new("RGB", (W, H), (12, 12, 16))
        sk = draw_skel(black, segs, joints, f"skeleton frame {fi}")
        sk.save(SKEL / f"skel_{fi:02d}.png")
        skel_frames.append(sk)

        sp = Image.open(sprites[fi]).convert("RGBA")
        canvas = Image.new("RGBA", (W, H), (20, 20, 24, 255))
        scale = min(W / sp.width, H / sp.height) * 0.92
        nw, nh = max(1, int(sp.width * scale)), max(1, int(sp.height * scale))
        sp2 = sp.resize((nw, nh), Image.Resampling.NEAREST)
        canvas.paste(sp2, ((W - nw) // 2, (H - nh) // 2), sp2)
        over = draw_skel(canvas.convert("RGB"), segs, joints, f"skeleton over sprite f{fi}")
        over.save(SKEL / f"skel_on_sprite_{fi:02d}.png")

        mesh_prev = OUT / "preview" / "frames" / f"mesh_{fi:02d}.png"
        mp = (
            Image.open(mesh_prev).convert("RGB").resize((W, H), Image.Resampling.BILINEAR)
            if mesh_prev.is_file()
            else black
        )
        side = Image.new("RGB", (W * 3 + 16, H), (0, 0, 0))
        side.paste(over, (0, 0))
        side.paste(sk, (W + 8, 0))
        side.paste(mp, (2 * W + 16, 0))
        d = ImageDraw.Draw(side)
        d.text((8, H - 18), "sprite+skel", fill=(200, 200, 200))
        d.text((W + 16, H - 18), "skeleton", fill=(200, 200, 200))
        d.text((2 * W + 24, H - 18), "mesh", fill=(200, 200, 200))
        side.save(SKEL / f"side_{fi:02d}.png")
        side_frames.append(side)

    skel_frames[0].save(
        SKEL / "skeleton.gif",
        save_all=True,
        append_images=skel_frames[1:],
        duration=500,
        loop=0,
    )
    side_frames[0].save(
        SKEL / "skeleton_compare.gif",
        save_all=True,
        append_images=side_frames[1:],
        duration=500,
        loop=0,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "skeletonGif": str(SKEL / "skeleton.gif").replace("\\", "/"),
                "compareGif": str(SKEL / "skeleton_compare.gif").replace("\\", "/"),
                "dir": str(SKEL).replace("\\", "/"),
                "legend": "green=optimized bones, blue=other bones, magenta=Bone_033 tip, yellow=optimized joints",
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
