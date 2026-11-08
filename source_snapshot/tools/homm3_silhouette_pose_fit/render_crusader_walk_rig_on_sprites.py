#!/usr/bin/env python3
"""Experiment: project crusader Mixamo bind rig onto each walk sprite frame.

Side-by-side GIF:
  left  — sprite with projected skeleton (rig applied onto the 2D frame)
  right — mesh bind render with skeleton overlay (same pipeline camera)

Blender:
  blender -b --python render_crusader_walk_rig_on_sprites.py -- \\
    [--frames-dir DIR] [--out DIR] [--master GLB]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
from PIL import Image, ImageDraw

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL))
from homm3_pose_camera import setup_pose_camera  # noqa: E402

DEFAULT_MASTER = (
    ROOT
    / "artifacts/crusader_pose_pipeline/out_meshy_t2_idle_f0/rigged"
    / "idle_f0_rigged_meshy6_bridgefix_hand.glb"
)
DEFAULT_FRAMES = ROOT / "artifacts/crusader_pose_pipeline/source_frames/nn_upscale_g00_move"
DEFAULT_OUT = ROOT / "artifacts/crusader_pose_pipeline/out_fit/walk_rig_on_sprites"
W = H = 512


def _argv_after_sep() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _clear_anim(arm) -> None:
    if arm.animation_data:
        arm.animation_data_clear()
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)


def _emission_mesh(mesh) -> None:
    for mat in mesh.data.materials:
        if mat is None or not mat.use_nodes:
            continue
        nt = mat.node_tree
        nodes = nt.nodes
        links = nt.links
        outn = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
        bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
        if not outn or not bsdf:
            continue
        base = bsdf.inputs.get("Base Color")
        emit = nodes.new("ShaderNodeEmission")
        emit.inputs["Strength"].default_value = 1.0
        if base is not None and base.is_linked:
            links.new(base.links[0].from_socket, emit.inputs["Color"])
        elif base is not None:
            emit.inputs["Color"].default_value = tuple(base.default_value)
        for link in list(outn.inputs["Surface"].links):
            links.remove(link)
        links.new(emit.outputs["Emission"], outn.inputs["Surface"])


def _project(scene, cam, world_pt) -> tuple[float, float, float]:
    c = world_to_camera_view(scene, cam, world_pt)
    return float(c.x * W), float((1.0 - c.y) * H), float(c.z)


def _bone_segs(arm, scene, cam, optimize: set[str]) -> list:
    segs = []
    for b in arm.pose.bones:
        h = arm.matrix_world @ b.head
        t = arm.matrix_world @ b.tail
        hx, hy, hz = _project(scene, cam, h)
        tx, ty, tz = _project(scene, cam, t)
        # Ortho depth can sit outside 0..1; still draw if on-screen in XY.
        if not (-0.5 <= hx <= W + 0.5 and -0.5 <= hy <= H + 0.5):
            continue
        if not (-0.5 <= tx <= W + 0.5 and -0.5 <= ty <= H + 0.5):
            continue
        segs.append(
            (
                b.name,
                (int(round(hx)), int(round(hy))),
                (int(round(tx)), int(round(ty))),
                b.name in optimize,
            )
        )
    return segs


def _content_bbox(im: Image.Image, *, thr: int = 18) -> tuple[int, int, int, int] | None:
    arr = list(im.convert("RGB").getdata())
    w, h = im.size
    xs, ys = [], []
    for y in range(h):
        row = arr[y * w : (y + 1) * w]
        for x, (r, g, b) in enumerate(row):
            if r > thr or g > thr or b > thr:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _map_segs(
    segs: list,
    src_bbox: tuple[int, int, int, int],
    dst_bbox: tuple[int, int, int, int],
) -> list:
    x0, y0, x1, y1 = src_bbox
    u0, v0, u1, v1 = dst_bbox
    sw = max(1, x1 - x0)
    sh = max(1, y1 - y0)
    dw = max(1, u1 - u0)
    dh = max(1, v1 - v0)
    sx = dw / sw
    sy = dh / sh
    s = min(sx, sy)
    # Center within destination bbox.
    cx = u0 + dw * 0.5
    cy = v0 + dh * 0.5
    ox = x0 + sw * 0.5
    oy = y0 + sh * 0.5

    def xform(p):
        x, y = p
        return (int(round(cx + (x - ox) * s)), int(round(cy + (y - oy) * s)))

    out = []
    for name, a, b, opt in segs:
        out.append((name, xform(a), xform(b), opt))
    return out


def _draw_skel(im: Image.Image, segs: list, *, label: str) -> Image.Image:
    out = im.convert("RGB")
    d = ImageDraw.Draw(out)
    for name, a, b, opt in segs:
        # High-contrast: black outline then neon stroke (visible on sprite + mesh).
        col = (0, 255, 80) if opt else (80, 200, 255)
        d.line([a, b], fill=(0, 0, 0), width=7)
        d.line([a, b], fill=col, width=4)
        r = 5
        d.ellipse([a[0] - r - 1, a[1] - r - 1, a[0] + r + 1, a[1] + r + 1], fill=(0, 0, 0))
        d.ellipse([a[0] - r, a[1] - r, a[0] + r, a[1] + r], fill=(255, 40, 255))
    d.text((8, 8), label, fill=(255, 255, 0))
    d.text((8, 24), f"bones={len(segs)}", fill=(255, 255, 0))
    return out


def _alpha_bbox_from_rgba(path: Path, *, thr: int = 8) -> tuple[int, int, int, int] | None:
    im = Image.open(path).convert("RGBA")
    a = im.split()[-1]
    # Threshold alpha so fringe doesn't explode the box.
    mask = a.point(lambda v: 255 if v > thr else 0)
    return mask.getbbox()


def _fit_sprite_to_bbox(path: Path, bbox: tuple[int, int, int, int]) -> Image.Image:
    """Place sprite into the mesh content bbox so camera-space bones line up."""
    sp = Image.open(path).convert("RGBA")
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    x0, y0, x1, y1 = bbox
    bw = max(1, x1 - x0 + 1)
    bh = max(1, y1 - y0 + 1)
    ab = sp.split()[-1].getbbox()
    if ab is None:
        raise RuntimeError(f"sprite has empty alpha: {path}")
    cropped = sp.crop(ab)
    scale = min(bw / cropped.width, bh / cropped.height)
    nw = max(1, int(round(cropped.width * scale)))
    nh = max(1, int(round(cropped.height * scale)))
    resized = cropped.resize((nw, nh), Image.Resampling.NEAREST)
    px = x0 + (bw - nw) // 2
    py = y0 + (bh - nh) // 2
    canvas.paste(resized, (px, py), resized)
    return canvas.convert("RGB")


def _fit_sprite(path: Path) -> Image.Image:
    sp = Image.open(path).convert("RGBA")
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    scale = min(W / sp.width, H / sp.height) * 0.92
    nw, nh = max(1, int(sp.width * scale)), max(1, int(sp.height * scale))
    sp2 = sp.resize((nw, nh), Image.Resampling.NEAREST)
    canvas.paste(sp2, ((W - nw) // 2, (H - nh) // 2), sp2)
    return canvas.convert("RGB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    ap.add_argument("--frames-dir", type=Path, default=DEFAULT_FRAMES)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(_argv_after_sep())

    master = args.master.resolve()
    frames_dir = args.frames_dir.resolve()
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = sorted(frames_dir.glob("frame_*.png"))
    if not frames:
        # Fallback to raw NN group 0 tiles.
        alt = ROOT / "artifacts/crusader_pose_pipeline/source_frames/nn_upscale"
        frames = sorted(alt.glob("00_*.png"))
    if not frames:
        raise SystemExit(f"no walk frames under {frames_dir}")
    if not master.is_file():
        raise SystemExit(f"master missing: {master}")

    optimize = {
        "Hips",
        "Spine02",
        "Spine01",
        "Spine",
        "neck",
        "Head",
        "RightShoulder",
        "RightArm",
        "RightForeArm",
        "RightHand",
        "LeftShoulder",
        "LeftArm",
        "LeftForeArm",
        "LeftHand",
        "RightUpLeg",
        "RightLeg",
        "RightFoot",
        "LeftUpLeg",
        "LeftLeg",
        "LeftFoot",
    }

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(master))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    _clear_anim(arm)
    _emission_mesh(mesh)
    bpy.context.view_layer.update()

    world = bpy.data.worlds.new("W")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.06, 0.06, 0.08, 1.0)
    bg.inputs["Strength"].default_value = 0.35

    job = {
        "camera": {
            "axis": "iso",
            "isoAzimuthDeg": 40.0,
            "isoElevationDeg": 30.0,
            "distance": 3.0,
            "orthoScale": 4.2,
            "rootYawDeg": 0.0,
        }
    }
    cam = setup_pose_camera(job, arm, bpy_module=bpy)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 12
    scene.render.resolution_x = W
    scene.render.resolution_y = H
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = True

    segs = _bone_segs(arm, scene, cam, optimize)
    print(f"[walk-rig] projected bones={len(segs)}", flush=True)
    if len(segs) < 8:
        raise SystemExit(f"too few projected bones ({len(segs)}); camera/projection failed")

    side_frames = []
    frame_paths = []
    for i, fr in enumerate(frames):
        raw = out_dir / f"mesh_{i:02d}.png"
        scene.render.filepath = str(raw)
        bpy.ops.render.render(write_still=True)
        mesh_im = Image.open(raw).convert("RGB")
        mesh_skel = _draw_skel(mesh_im, segs, label=f"bind mesh+skel f{i:02d}")

        mesh_bb = _content_bbox(mesh_im, thr=22)
        if mesh_bb is None:
            raise SystemExit(f"frame {i}: empty mesh content bbox")
        # Same camera-space bones as the mesh panel — sprite is scaled into the mesh bbox.
        sprite = _fit_sprite_to_bbox(fr, mesh_bb)
        sprite_skel = _draw_skel(sprite, segs, label=f"sprite+skel f{i:02d}")

        canvas = Image.new("RGB", (W * 2 + 8, H), (0, 0, 0))
        canvas.paste(sprite_skel, (0, 0))
        canvas.paste(mesh_skel, (W + 8, 0))
        ImageDraw.Draw(canvas).text(
            (8, H - 18),
            "experiment: bind rig projected onto walk sprites (not IK posed)",
            fill=(180, 180, 180),
        )
        out_frame = out_dir / f"side_{i:02d}.png"
        canvas.save(out_frame)
        side_frames.append(canvas)
        frame_paths.append(str(out_frame).replace("\\", "/"))
        print(f"[walk-rig] frame {i}/{len(frames)-1}", flush=True)

    gif_path = out_dir / "walk_bind_rig_on_sprites.gif"
    if side_frames:
        side_frames[0].save(
            gif_path,
            save_all=True,
            append_images=side_frames[1:],
            duration=180,
            loop=0,
            optimize=False,
        )

    report = {
        "ok": True,
        "masterGlb": str(master).replace("\\", "/"),
        "framesDir": str(frames_dir).replace("\\", "/"),
        "frameCount": len(frames),
        "gif": str(gif_path).replace("\\", "/"),
        "frames": frame_paths,
        "pose": "bind_identity",
        "notes": (
            "Same bind skeleton projected onto every walk sprite via pipeline iso camera. "
            "Mismatch across the cycle shows where IK must move legs/torso — not a fitted pose."
        ),
        "proof": "generated — bind-rig-on-sprites experiment; not OE runtime",
    }
    (out_dir / "walk_rig_on_sprites_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"ok": True, "gif": report["gif"], "frames": len(frames)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
