#!/usr/bin/env python3
"""Render a 360° lit orbit MP4 around a volume mesh OBJ.

  python tools/homm3_depth_billboard/render_volume_mesh_orbit.py \
      --mesh-dir artifacts/depth_billboard/ccrusd_walk_mesh_frame0
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DEPTH_BB = Path(__file__).resolve().parent
if str(DEPTH_BB) not in sys.path:
    sys.path.insert(0, str(DEPTH_BB))

from mesh_render import load_mesh_from_obj, render_orbit_frames  # noqa: E402


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh-dir", type=Path, required=True)
    parser.add_argument("--mesh-obj", type=Path, default=None)
    parser.add_argument("--sprite", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--yaw-steps", type=int, default=48)
    parser.add_argument("--yaw-max", type=float, default=360.0)
    parser.add_argument("--orbit-fps", type=float, default=12.0)
    parser.add_argument("--preview-scale", type=int, default=1)
    parser.add_argument("--pitch", type=float, default=12.0)
    parser.add_argument(
        "--lit",
        action="store_true",
        help="Apply diffuse lighting (default: flat vertex colors for texture read).",
    )
    args = parser.parse_args()

    mesh_dir = Path(args.mesh_dir)
    mesh_path = Path(args.mesh_obj) if args.mesh_obj else mesh_dir / "mesh.obj"
    sprite_path = Path(args.sprite) if args.sprite else mesh_dir / "sprite.png"
    out_dir = Path(args.out_dir) if args.out_dir else mesh_dir / "orbit360"
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"refusing to write into a non-empty directory: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    mesh = load_mesh_from_obj(mesh_path)
    base_w, base_h = 768, 576
    scale = max(1, int(args.preview_scale))
    frames_raw = render_orbit_frames(
        mesh,
        sprite_path,
        yaw_steps=args.yaw_steps,
        yaw_max_deg=args.yaw_max,
        pitch_deg=args.pitch,
        out_width=base_w * scale,
        out_height=base_h * scale,
        flat_shading=not bool(args.lit),
    )

    orbit_dir = out_dir / "frames"
    orbit_dir.mkdir()
    labeled: list[Image.Image] = []
    yaws: list[float] = []
    for index, (yaw, rgba) in enumerate(frames_raw):
        yaws.append(yaw)
        image = Image.fromarray(rgba, "RGBA")
        labeled_frame = _label(image, f"mesh orbit  yaw {yaw:.1f}°")
        labeled_frame.save(orbit_dir / f"{index:03d}.png")
        labeled.append(labeled_frame)

    gif_path = out_dir / "orbit.gif"
    _save_gif(gif_path, labeled, args.orbit_fps)
    mp4_path = _encode_mp4(gif_path)

    summary = {
        "schema": "homm3_depth_billboard_volume_mesh_orbit.v1",
        "meshObj": str(mesh_path.resolve()),
        "spritePng": str(sprite_path.resolve()),
        "yawSteps": int(args.yaw_steps),
        "yawMaxDeg": float(args.yaw_max),
        "orbitYaws": yaws,
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
