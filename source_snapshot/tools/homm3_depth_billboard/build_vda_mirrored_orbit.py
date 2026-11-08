#!/usr/bin/env python3
"""VDA depth-billboard orbit with tuned inference + connected depth volume.

Re-runs VDA-S on the full shadow-culled sprite folder (temporal context), then
renders an orbit with reduced depth scale and a solid connected volume. Use
``--animate-walk`` to advance native move frames during the yaw sweep.

  python tools/homm3_depth_billboard/build_vda_mirrored_orbit.py \
      --sprite-dir artifacts/depth_billboard/ccrusd_continuous/sprites_shadow_culled \
      --out-dir artifacts/depth_billboard/ccrusd_continuous_frame0_vda_mirrored \
      --reinfer-vda
"""
from __future__ import annotations

import argparse
import json
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

from geometry import (  # noqa: E402
    build_connected_depth_volume,
    load_depth01,
)
from render import render_billboard_points  # noqa: E402
from run_vda_movement_depth import (  # noqa: E402
    DEFAULT_CHECKPOINT,
    ensure_vda_pipeline_cache,
)

ORBIT_YAWS = [float(i) * (90.0 / 23.0) for i in range(24)]


def _frame_png_path(directory: Path, frame_index: int) -> Path:
    for name in (f"{frame_index}.png", f"{frame_index:02d}.png", f"{frame_index:03d}.png"):
        path = directory / name
        if path.is_file():
            return path
    raise FileNotFoundError(f"no frame {frame_index} under {directory}")


def _build_orbit_schedule(
    *,
    animate_walk: bool,
    walk_count: int,
    walk_loops: int,
    steps_per_walk_frame: int,
    orbit_yaw_min: float,
    orbit_yaw_max: float,
    orbit_steps: int | None,
) -> tuple[list[float], list[int]]:
    """Return (yaws, walk_frame_indices) for one orbit render pass."""
    if walk_loops < 1:
        raise ValueError("walk_loops must be >= 1")
    if steps_per_walk_frame < 1:
        raise ValueError("steps_per_walk_frame must be >= 1")
    if walk_count < 1:
        raise ValueError("walk_count must be >= 1")

    if animate_walk and (walk_loops > 1 or orbit_yaw_max != 90.0 or orbit_steps is not None):
        frame_count = (
            int(orbit_steps)
            if orbit_steps is not None
            else walk_loops * walk_count * steps_per_walk_frame
        )
        if frame_count < 2:
            raise ValueError("orbit schedule needs at least 2 frames")
        yaws = [
            orbit_yaw_min + (orbit_yaw_max - orbit_yaw_min) * (i / (frame_count - 1))
            for i in range(frame_count)
        ]
        walk_indices = [
            (i // steps_per_walk_frame) % walk_count for i in range(frame_count)
        ]
        return yaws, walk_indices

    if animate_walk:
        yaws = list(ORBIT_YAWS)
        walk_indices = [
            min(
                walk_count - 1,
                int(index * walk_count / max(1, len(ORBIT_YAWS) - 1)),
            )
            for index in range(len(ORBIT_YAWS))
        ]
        return yaws, walk_indices

    yaws = list(ORBIT_YAWS)
    return yaws, [0] * len(yaws)


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
    parser.add_argument("--sprite-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--depth-dir", type=Path, default=None)
    parser.add_argument("--frame-index", type=int, default=0)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--vda-root", type=Path, default=None)
    parser.add_argument("--allow-cpu", action="store_true")
    parser.add_argument("--input-size", type=int, default=518)
    parser.add_argument("--fps", type=float, default=12.0)
    parser.add_argument("--fp32", action="store_true")
    parser.add_argument("--norm-low", type=float, default=5.0)
    parser.add_argument("--norm-high", type=float, default=95.0)
    parser.add_argument(
        "--norm-mode",
        choices=("clip", "per_frame"),
        default="clip",
        help="clip = one percentile range across the whole movement; per_frame = per-frame range.",
    )
    parser.add_argument("--alpha-opaque", type=float, default=0.08)
    parser.add_argument(
        "--reinfer-vda",
        action="store_true",
        help="Run VDA-S on the full sprite-dir (temporal) into out-dir/vda_cache.",
    )
    parser.add_argument("--depth-scale", type=float, default=0.25)
    parser.add_argument("--preview-scale", type=int, default=4)
    parser.add_argument("--gap-close-radius", type=int, default=1)
    parser.add_argument("--depth-smooth-radius", type=int, default=1)
    parser.add_argument(
        "--depth-bow-vertical",
        type=float,
        default=0.8,
        help="Flatten VDA vertical U-bow using interior row profile (0=off).",
    )
    parser.add_argument(
        "--depth-bow-edge",
        type=float,
        default=0.85,
        help="Lift silhouette edges toward local interior depth max (0=off).",
    )
    parser.add_argument(
        "--depth-bow-radius",
        type=int,
        default=7,
        help="Grey-dilation radius for local interior depth max (pixels).",
    )
    parser.add_argument(
        "--depth-edge-strength",
        type=float,
        default=0.0,
        help="Legacy column-max edge lift (0=off). Prefer --depth-bow-edge.",
    )
    parser.add_argument(
        "--depth-edge-falloff",
        type=float,
        default=3.0,
        help="Edge-correction falloff in pixels from the silhouette boundary.",
    )
    parser.add_argument("--splat-radius", type=int, default=2)
    parser.add_argument("--orbit-fps", type=float, default=12.0)
    parser.add_argument(
        "--fill-spacing",
        type=float,
        default=1.0,
        help="Z sample spacing in sprite-pixel units for the clam-shell fill.",
    )
    parser.add_argument(
        "--thickness-scale",
        type=float,
        default=2.0,
        help=(
            "Backward extrusion per pixel = thickness-scale * distance to the "
            "nearest silhouette edge (in pixels). Thin features stay thin."
        ),
    )
    parser.add_argument(
        "--animate-walk",
        action="store_true",
        help="Cycle native move frames during the orbit (default: frozen frame-index).",
    )
    parser.add_argument("--walk-start", type=int, default=0)
    parser.add_argument("--walk-count", type=int, default=8)
    parser.add_argument(
        "--walk-loops",
        type=int,
        default=1,
        help="Repeat the native walk cycle this many times during the orbit.",
    )
    parser.add_argument(
        "--steps-per-walk-frame",
        type=int,
        default=3,
        help="Orbit frames shown per walk frame when using extended orbit.",
    )
    parser.add_argument(
        "--orbit-yaw-min",
        type=float,
        default=0.0,
        help="Starting camera yaw in degrees (front = 0).",
    )
    parser.add_argument(
        "--orbit-yaw-max",
        type=float,
        default=90.0,
        help="Ending camera yaw in degrees. Use 180+ to show the far side.",
    )
    parser.add_argument(
        "--orbit-steps",
        type=int,
        default=None,
        help=(
            "Total orbit frames. Default: walk-loops * walk-count * "
            "steps-per-walk-frame when walk-loops>1 or orbit-yaw-max!=90."
        ),
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"refusing to write into a non-empty directory: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    sprite_dir = Path(args.sprite_dir)
    depth_dir = Path(args.depth_dir) if args.depth_dir is not None else out_dir / "vda_cache"
    if args.reinfer_vda:
        cache = ensure_vda_pipeline_cache(
            source_dir=sprite_dir,
            output_dir=depth_dir,
            checkpoint=args.checkpoint,
            input_size=args.input_size,
            fps=args.fps,
            allow_cpu=args.allow_cpu,
            vda_root=args.vda_root,
            fp32=args.fp32,
            norm_lower_percentile=args.norm_low,
            norm_upper_percentile=args.norm_high,
            norm_mode=args.norm_mode,
            alpha_opaque=args.alpha_opaque,
        )
        vda_cache_info = cache
    else:
        if not depth_dir.is_dir():
            raise SystemExit(f"depth-dir is missing and --reinfer-vda was not set: {depth_dir}")
        vda_cache_info = {"status": "external", "output_dir": str(depth_dir.resolve())}

    walk_start = int(args.walk_start)
    walk_count = int(args.walk_count)
    if walk_count < 1:
        raise SystemExit("walk-count must be >= 1")

    def _load_clip(frame_index: int) -> tuple[np.ndarray, np.ndarray]:
        sprite_path = _frame_png_path(sprite_dir, frame_index)
        depth_path = _frame_png_path(depth_dir, frame_index)
        rgba = np.asarray(Image.open(sprite_path).convert("RGBA"), dtype=np.uint8)
        return rgba, load_depth01(depth_path)

    def _volume_for_frame(frame_index: int):
        rgba, depth = _load_clip(frame_index)
        return build_connected_depth_volume(
            rgba,
            depth,
            depth_scale=args.depth_scale,
            gap_close_radius=args.gap_close_radius,
            depth_smooth_radius=args.depth_smooth_radius,
            fill_spacing_pixels=args.fill_spacing,
            thickness_scale=args.thickness_scale,
            depth_edge_strength=args.depth_edge_strength,
            depth_edge_falloff_pixels=args.depth_edge_falloff,
            depth_bow_vertical_strength=args.depth_bow_vertical,
            depth_bow_edge_strength=args.depth_bow_edge,
            depth_bow_local_radius=args.depth_bow_radius,
            depth_bow_edge_falloff_pixels=args.depth_edge_falloff,
        )

    if args.animate_walk:
        for offset in range(walk_count):
            frame_index = walk_start + offset
            _load_clip(frame_index)
    else:
        _load_clip(args.frame_index)

    orbit_yaws, orbit_walk_indices = _build_orbit_schedule(
        animate_walk=bool(args.animate_walk),
        walk_count=walk_count,
        walk_loops=int(args.walk_loops),
        steps_per_walk_frame=int(args.steps_per_walk_frame),
        orbit_yaw_min=float(args.orbit_yaw_min),
        orbit_yaw_max=float(args.orbit_yaw_max),
        orbit_steps=args.orbit_steps,
    )

    orbit_frames: list[Image.Image] = []
    orbit_dir = out_dir / "orbit"
    orbit_dir.mkdir()
    point_counts: list[int] = []
    walk_indices: list[int] = []
    for index, (yaw, walk_idx) in enumerate(zip(orbit_yaws, orbit_walk_indices)):
        if args.animate_walk:
            frame_index = walk_start + walk_idx
        else:
            walk_idx = 0
            frame_index = args.frame_index
        walk_indices.append(frame_index)
        points = _volume_for_frame(frame_index)
        point_counts.append(points.count)
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
        label = (
            f"walk {frame_index}  yaw {yaw:.1f}°"
            if args.animate_walk
            else f"orbit yaw {yaw:.1f}°"
        )
        labeled = _label(_upscale(view, args.preview_scale), label)
        labeled.save(orbit_dir / f"{index:03d}.png")
        orbit_frames.append(labeled)

    gif_path = out_dir / "orbit.gif"
    _save_gif(gif_path, orbit_frames, args.orbit_fps)
    mp4_path = _encode_mp4(gif_path)

    summary = {
        "schema": "homm3_depth_billboard_vda_mirrored_orbit.v3",
        "depthModel": "Video-Depth-Anything-Small",
        "vdaCache": vda_cache_info,
        "vdaInputSize": int(args.input_size),
        "vdaFp32": bool(args.fp32),
        "vdaNormLow": float(args.norm_low),
        "vdaNormHigh": float(args.norm_high),
        "vdaAlphaOpaque": float(args.alpha_opaque),
        "depthScale": float(args.depth_scale),
        "connectedVolume": True,
        "volumeStyle": "anchored_clam_shell_fill",
        "fillSpacingPixels": float(args.fill_spacing),
        "thicknessScale": float(args.thickness_scale),
        "depthBowVerticalStrength": float(args.depth_bow_vertical),
        "depthBowEdgeStrength": float(args.depth_bow_edge),
        "depthBowLocalRadius": int(args.depth_bow_radius),
        "depthEdgeStrength": float(args.depth_edge_strength),
        "depthEdgeFalloffPixels": float(args.depth_edge_falloff),
        "animateWalk": bool(args.animate_walk),
        "walkStart": walk_start,
        "walkCount": walk_count,
        "walkLoops": int(args.walk_loops),
        "stepsPerWalkFrame": int(args.steps_per_walk_frame),
        "orbitYawMin": float(args.orbit_yaw_min),
        "orbitYawMax": float(args.orbit_yaw_max),
        "orbitSteps": len(orbit_yaws),
        "walkFrameIndices": walk_indices,
        "pointCounts": point_counts,
        "orbitYaws": orbit_yaws,
        "outputs": {
            "orbitGif": str(gif_path.resolve()),
            "orbitMp4": str(mp4_path.resolve()),
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, **summary}, indent=2))


if __name__ == "__main__":
    main()
