#!/usr/bin/env python3
"""Depth-billboard orbit from a single sprite frame using DA3 (non-temporal).

Matches the frozen-frame orbit in ``run_depth_billboard.render_clip`` (frame 0,
24 yaw steps) but uses Depth Anything 3 instead of Video Depth Anything.

  python tools/homm3_depth_billboard/build_da3_billboard_orbit.py \
      --sprite artifacts/depth_billboard/ccrusd_continuous/sprites_shadow_culled/0.png \
      --out-dir artifacts/depth_billboard/ccrusd_continuous_frame0_da3
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
POSE_FIT = ROOT / "tools" / "homm3_silhouette_pose_fit"
DEPTH_BB = Path(__file__).resolve().parent
if str(POSE_FIT) not in sys.path:
    sys.path.insert(0, str(POSE_FIT))
if str(DEPTH_BB) not in sys.path:
    sys.path.insert(0, str(DEPTH_BB))

from compare_sprite_depth_models import (  # noqa: E402
    DA3_MODEL,
    _load_da3,
    _predict_da3_sequence,
    _rgba_and_rgb,
)
from geometry import billboard_points_from_frame  # noqa: E402
from render import render_billboard_points  # noqa: E402

ORBIT_YAWS = [float(i) * (90.0 / 23.0) for i in range(24)]
ALPHA_OPAQUE = 0.08


def _font(size: int):
    try:
        from PIL import ImageFont

        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        from PIL import ImageFont

        return ImageFont.load_default()


def _label(image: Image.Image, text: str) -> Image.Image:
    canvas = Image.new("RGBA", (image.width, image.height + 22), (12, 14, 18, 255))
    canvas.paste(image, (0, 22))
    ImageDraw.Draw(canvas).text((6, 4), text, fill=(230, 230, 230), font=_font(16))
    return canvas


def _upscale(image: Image.Image, factor: int) -> Image.Image:
    if factor <= 1:
        return image
    return image.resize(
        (image.width * factor, image.height * factor),
        Image.Resampling.NEAREST,
    )


def _save_gif(path: Path, frames: list[Image.Image], fps: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    parser.add_argument("--sprite", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, default=DA3_MODEL)
    parser.add_argument("--reference-view", type=str, default="middle")
    parser.add_argument("--process-res", type=int, default=504)
    parser.add_argument("--depth-scale", type=float, default=0.45)
    parser.add_argument("--preview-scale", type=int, default=4)
    parser.add_argument("--gap-close-radius", type=int, default=1)
    parser.add_argument("--depth-smooth-radius", type=int, default=1)
    parser.add_argument("--splat-radius", type=int, default=2)
    parser.add_argument("--orbit-fps", type=float, default=12.0)
    args = parser.parse_args()

    sprite_path = Path(args.sprite)
    if not sprite_path.is_file():
        raise SystemExit(f"sprite is missing: {sprite_path}")

    out_dir = Path(args.out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"refusing to write into a non-empty directory: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    rgba, rgb = _rgba_and_rgb(sprite_path)
    mask = rgba[..., 3].astype(np.float32) / 255.0 > ALPHA_OPAQUE

    model, torch = _load_da3(args.model_dir)
    depths, timing = _predict_da3_sequence(
        model,
        torch,
        [rgb],
        [mask],
        reference_view=args.reference_view,
        process_res=args.process_res,
    )
    depth = depths[0]

    depth_u16 = np.clip(np.rint(depth * 65535.0), 0, 65535).astype(np.uint16)
    Image.fromarray(depth_u16, mode="I;16").save(out_dir / "da3_depth_u16.png")

    points = billboard_points_from_frame(
        rgba,
        depth,
        depth_scale=args.depth_scale,
        gap_close_radius=args.gap_close_radius,
        depth_smooth_radius=args.depth_smooth_radius,
    )

    orbit_frames: list[Image.Image] = []
    orbit_dir = out_dir / "orbit"
    orbit_dir.mkdir()
    for index, yaw in enumerate(ORBIT_YAWS):
        view = Image.fromarray(
            render_billboard_points(
                points,
                yaw_deg=yaw,
                pitch_deg=12.0,
                perspective=True,
                splat_radius=max(2, int(args.splat_radius)),
                solid_front=False,
            ),
            "RGBA",
        )
        labeled = _label(_upscale(view, args.preview_scale), f"orbit yaw {yaw:.1f}°")
        labeled.save(orbit_dir / f"{index:02d}.png")
        orbit_frames.append(labeled)

    gif_path = out_dir / "orbit.gif"
    _save_gif(gif_path, orbit_frames, args.orbit_fps)
    mp4_path = _encode_mp4(gif_path)

    summary = {
        "schema": "homm3_depth_billboard_da3_orbit.v1",
        "sprite": str(sprite_path.resolve()),
        "depthModel": "depth-anything-3/DA3-LARGE-1.1",
        "modelDir": str(Path(args.model_dir).resolve()),
        "referenceView": args.reference_view,
        "processRes": int(args.process_res),
        "depthScale": float(args.depth_scale),
        "orbitYaws": ORBIT_YAWS,
        "pointCount": points.count,
        "timing": timing,
        "outputs": {
            "orbitGif": str(gif_path.resolve()),
            "orbitMp4": str(mp4_path.resolve()),
            "depthPng": str((out_dir / "da3_depth_u16.png").resolve()),
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, **summary}, indent=2))


if __name__ == "__main__":
    main()
