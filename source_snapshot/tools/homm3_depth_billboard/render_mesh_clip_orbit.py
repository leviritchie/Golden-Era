#!/usr/bin/env python3
"""Render an animated mesh orbit from a volume-mesh clip manifest.

Matches the extended walk+yaw schedule used by build_vda_mirrored_orbit.py.

  python tools/homm3_depth_billboard/render_mesh_clip_orbit.py \
      --clip-dir artifacts/depth_billboard/ccrusd_walk_shell_clip_debowed85
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

DEPTH_BB = Path(__file__).resolve().parent
if str(DEPTH_BB) not in sys.path:
    sys.path.insert(0, str(DEPTH_BB))

from build_vda_mirrored_orbit import _build_orbit_schedule  # noqa: E402
from mesh_render import _load_texture_rgba, load_mesh_from_obj, render_mesh_frame  # noqa: E402
from volume_mesh import VolumeMesh  # noqa: E402


def _font(size: int):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _label(image: Image.Image, text: str) -> Image.Image:
    canvas = Image.new("RGBA", (image.width, image.height + 22), (12, 14, 18, 255))
    canvas.paste(image, (0, 22))
    ImageDraw.Draw(canvas).text((6, 4), text, fill=(230, 230, 230), font=_font(16))
    return canvas


def _save_gif(path: Path, frames: list[Image.Image], fps: float) -> None:
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=max(1, round(1000.0 / fps)),
        loop=0,
        disposal=2,
        optimize=False,
    )


def _encode_mp4(gif_path: Path) -> Path:
    mp4_path = gif_path.with_suffix(".mp4")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(gif_path),
            "-movflags",
            "+faststart",
            "-pix_fmt",
            "yuv420p",
            str(mp4_path),
        ],
        check=True,
    )
    return mp4_path


def _load_clip(clip_dir: Path) -> tuple[dict, list[tuple[int, VolumeMesh, np.ndarray]]]:
    manifest_path = clip_dir / "clip_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing clip manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    loaded: list[tuple[int, VolumeMesh, np.ndarray]] = []
    for entry in manifest["frames"]:
        frame_index = int(entry["index"])
        mesh_path = Path(entry["meshObj"])
        sprite_path = Path(entry["spritePng"])
        mesh = load_mesh_from_obj(mesh_path)
        texture = _load_texture_rgba(sprite_path)
        loaded.append((frame_index, mesh, texture))
    loaded.sort(key=lambda item: item[0])
    return manifest, loaded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clip-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--walk-loops", type=int, default=4)
    parser.add_argument("--steps-per-walk-frame", type=int, default=3)
    parser.add_argument("--orbit-yaw-min", type=float, default=0.0)
    parser.add_argument("--orbit-yaw-max", type=float, default=180.0)
    parser.add_argument("--orbit-steps", type=int, default=96)
    parser.add_argument("--orbit-fps", type=float, default=12.0)
    parser.add_argument("--preview-scale", type=int, default=2)
    parser.add_argument("--pitch", type=float, default=12.0)
    parser.add_argument(
        "--lit",
        action="store_true",
        help="Apply diffuse lighting (default: flat UV texture for max sprite detail).",
    )
    args = parser.parse_args()

    clip_dir = Path(args.clip_dir)
    out_dir = Path(args.out_dir) if args.out_dir else clip_dir / "orbit_walk"
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"refusing to write into a non-empty directory: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest, clip_frames = _load_clip(clip_dir)
    mesh_by_index = {index: (mesh, texture) for index, mesh, texture in clip_frames}
    walk_count = len(clip_frames)

    yaws, walk_indices = _build_orbit_schedule(
        animate_walk=True,
        walk_count=walk_count,
        walk_loops=int(args.walk_loops),
        steps_per_walk_frame=int(args.steps_per_walk_frame),
        orbit_yaw_min=float(args.orbit_yaw_min),
        orbit_yaw_max=float(args.orbit_yaw_max),
        orbit_steps=int(args.orbit_steps),
    )

    base_w, base_h = 768, 576
    scale = max(1, int(args.preview_scale))
    out_w, out_h = base_w * scale, base_h * scale

    orbit_dir = out_dir / "frames"
    orbit_dir.mkdir()
    labeled: list[Image.Image] = []
    for step, (yaw, walk_idx) in enumerate(zip(yaws, walk_indices)):
        frame_index = clip_frames[walk_idx][0]
        mesh, texture = mesh_by_index[frame_index]
        rgba = render_mesh_frame(
            mesh,
            texture,
            yaw_deg=yaw,
            pitch_deg=args.pitch,
            out_width=out_w,
            out_height=out_h,
            flat_shading=not bool(args.lit),
            texture_sampling=True,
        )
        image = Image.fromarray(rgba, "RGBA")
        labeled_frame = _label(image, f"mesh walk orbit  frame {frame_index}  yaw {yaw:.1f}°")
        labeled_frame.save(orbit_dir / f"{step:03d}.png")
        labeled.append(labeled_frame)
        if step % 12 == 0:
            print(f"rendered {step + 1}/{len(yaws)}  frame={frame_index}  yaw={yaw:.1f}")

    gif_path = out_dir / "orbit.gif"
    _save_gif(gif_path, labeled, args.orbit_fps)
    mp4_path = _encode_mp4(gif_path)

    summary = {
        "schema": "homm3_depth_billboard_volume_mesh_clip_orbit.v1",
        "clipManifest": str((clip_dir / "clip_manifest.json").resolve()),
        "walkLoops": int(args.walk_loops),
        "stepsPerWalkFrame": int(args.steps_per_walk_frame),
        "orbitYawMin": float(args.orbit_yaw_min),
        "orbitYawMax": float(args.orbit_yaw_max),
        "orbitSteps": int(args.orbit_steps),
        "walkFrameIndices": walk_indices,
        "orbitYaws": yaws,
        "previewScale": int(args.preview_scale),
        "textureSampling": "uv_bilinear",
        "outputs": {
            "orbitGif": str(gif_path.resolve()),
            "orbitMp4": str(mp4_path.resolve()),
            "framesDir": str(orbit_dir.resolve()),
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, **summary}, indent=2))


if __name__ == "__main__":
    main()
