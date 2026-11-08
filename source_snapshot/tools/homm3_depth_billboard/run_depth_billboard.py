#!/usr/bin/env python3
"""Render a Video Depth Anything clip as a 3D depth billboard.

Reuses the sprite billboard: opaque pixels stay samples of the original
animation. They are placed in 3D along the billboard normal from the VDA
depth map. No character mesh is built.

Real HoMM3 crusader move (CCRUSD group 0 native plates + VDA cache):

  python tools/homm3_depth_billboard/extract_ccrusd_move.py --bundle BUNDLE --out-dir SPRITES
  python tools/homm3_depth_billboard/run_depth_billboard.py --sprite-dir SPRITES --depth-dir VDA_CACHE --out-dir OUT

``--synthetic-geometry-fixture`` is a colored-rectangle depth test only. It is
not HoMM3 art and must not be presented as the crusader move clip.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
POSE_FIT = ROOT / "tools" / "homm3_silhouette_pose_fit"
if str(POSE_FIT) not in sys.path:
    sys.path.insert(0, str(POSE_FIT))

from run_vda_movement_depth import (  # noqa: E402
    PIPELINE_MANIFEST_NAME,
    assert_vda_pipeline_cache,
)

from geometry import billboard_points_from_frame, load_depth01  # noqa: E402
from render import render_billboard_points  # noqa: E402
from synthetic_crusader import (  # noqa: E402
    FRAME_COUNT,
    preview_panel,
    synthetic_crusader_move_frames,
)

ORBIT_YAWS = (0.0, 28.0, 55.0, 82.0)


def _pngs(directory: Path) -> list[Path]:
    paths = sorted(Path(directory).glob("*.png"), key=lambda p: p.stem)
    if not paths:
        raise FileNotFoundError(f"no PNG frames in {directory}")
    numbered = True
    try:
        paths = sorted(paths, key=lambda p: int(p.stem))
    except ValueError:
        numbered = False
        paths = sorted(paths, key=lambda p: p.name)
    if not numbered:
        raise ValueError(f"depth-billboard frames must be numbered PNG stems: {directory}")
    return paths


def _save_gif(path: Path, frames: list[Image.Image], fps: float) -> None:
    if not frames:
        raise ValueError("no frames to write")
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


def _upscale(image: Image.Image, factor: int) -> Image.Image:
    if factor < 1:
        raise ValueError("upscale factor must be >= 1")
    if factor == 1:
        return image
    return image.resize(
        (image.width * factor, image.height * factor),
        Image.Resampling.NEAREST,
    )


def _label(image: Image.Image, text: str) -> Image.Image:
    canvas = Image.new("RGBA", (image.width, image.height + 22), (12, 14, 18, 255))
    canvas.paste(image, (0, 22))
    ImageDraw.Draw(canvas).text((6, 4), text, fill=(230, 230, 230))
    return canvas


def load_vda_clip(sprite_dir: Path, depth_dir: Path) -> tuple[list[np.ndarray], list[np.ndarray], dict]:
    sprite_paths = _pngs(sprite_dir)
    depth_dir = Path(depth_dir)
    manifest = assert_vda_pipeline_cache(depth_dir)
    expected = [path.name for path in sprite_paths]
    if manifest.get("frameNames") != expected:
        raise RuntimeError(
            f"VDA cache frameNames {manifest.get('frameNames')} != sprite names {expected}"
        )
    sprites: list[np.ndarray] = []
    depths: list[np.ndarray] = []
    for path in sprite_paths:
        rgba = np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)
        depth_path = depth_dir / path.name
        if not depth_path.is_file():
            raise FileNotFoundError(f"missing VDA depth frame: {depth_path}")
        depth = load_depth01(depth_path)
        if depth.shape != rgba.shape[:2]:
            raise RuntimeError(
                f"depth {depth.shape} != sprite {rgba.shape[:2]} for {path.name}"
            )
        sprites.append(rgba)
        depths.append(depth)
    return sprites, depths, manifest


def render_clip(
    sprites: list[np.ndarray],
    depths: list[np.ndarray],
    out_dir: Path,
    *,
    depth_scale: float,
    fps: float,
    source: str,
    vda_manifest: dict | None,
    preview_scale: int = 4,
    gap_close_radius: int = 1,
    depth_smooth_radius: int = 1,
    splat_radius: int = 2,
    solid_front: bool = True,
) -> dict:
    if len(sprites) != len(depths):
        raise ValueError("sprite/depth count mismatch")
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"refusing to write into a non-empty directory: {out_dir}")
    front_dir = out_dir / "front"
    orbit_dir = out_dir / "orbit"
    compare_dir = out_dir / "compare"
    front_dir.mkdir(parents=True)
    orbit_dir.mkdir()
    compare_dir.mkdir()

    front_images: list[Image.Image] = []
    compare_images: list[Image.Image] = []
    point_counts: list[int] = []

    for index, (rgba, depth) in enumerate(zip(sprites, depths)):
        points = billboard_points_from_frame(
            rgba,
            depth,
            depth_scale=depth_scale,
            gap_close_radius=gap_close_radius,
            depth_smooth_radius=depth_smooth_radius,
        )
        point_counts.append(points.count)
        front = Image.fromarray(
            render_billboard_points(
                points,
                yaw_deg=0.0,
                perspective=False,
                splat_radius=1,
                solid_front=solid_front,
            ),
            "RGBA",
        )
        name = f"{index:02d}.png"
        front.save(front_dir / name)
        front_images.append(_upscale(front, preview_scale))

        yaw_renders = []
        for yaw in ORBIT_YAWS:
            view = Image.fromarray(
                render_billboard_points(
                    points,
                    yaw_deg=yaw,
                    pitch_deg=8.0 if yaw else 0.0,
                    perspective=True,
                    splat_radius=max(2, int(splat_radius)),
                    solid_front=False,
                ),
                "RGBA",
            )
            yaw_renders.append(_label(_upscale(view, preview_scale), f"yaw {yaw:.0f}°"))
        gap = 8
        strip_w = sum(im.width for im in yaw_renders) + gap * (len(yaw_renders) - 1)
        strip = Image.new("RGBA", (strip_w, yaw_renders[0].height), (12, 14, 18, 255))
        x = 0
        for im in yaw_renders:
            strip.paste(im, (x, 0))
            x += im.width + gap
        strip.save(compare_dir / name)
        compare_images.append(strip)
        preview_panel(rgba, depth).save(compare_dir / f"source_{name}")

    orbit_yaws = [float(i) * (90.0 / 23.0) for i in range(24)]
    freeze = billboard_points_from_frame(
        sprites[0],
        depths[0],
        depth_scale=depth_scale,
        gap_close_radius=gap_close_radius,
        depth_smooth_radius=depth_smooth_radius,
    )
    orbit_turn: list[Image.Image] = []
    for i, yaw in enumerate(orbit_yaws):
        view = Image.fromarray(
            render_billboard_points(
                freeze,
                yaw_deg=yaw,
                pitch_deg=12.0,
                perspective=True,
                splat_radius=max(2, int(splat_radius)),
                solid_front=False,
            ),
            "RGBA",
        )
        labeled = _label(_upscale(view, preview_scale), f"orbit yaw {yaw:.1f}°")
        labeled.save(orbit_dir / f"{i:02d}.png")
        orbit_turn.append(labeled)

    _save_gif(out_dir / "front.gif", front_images, fps)
    _save_gif(out_dir / "compare.gif", compare_images, fps)
    _save_gif(out_dir / "orbit.gif", orbit_turn, 12.0)

    manifest = {
        "schema": "homm3_depth_billboard.v1",
        "source": source,
        "frameCount": len(sprites),
        "depthScale": float(depth_scale),
        "fps": float(fps),
        "pointCounts": point_counts,
        "gapCloseRadius": int(gap_close_radius),
        "depthSmoothRadius": int(depth_smooth_radius),
        "splatRadius": int(splat_radius),
        "solidFront": bool(solid_front),
        "convention": {
            "space": "X right, Y up, +Z toward camera on the authored billboard normal",
            "depth": "Video Depth Anything near=bright; outside alpha is zero",
            "geometry": "unordered opaque pixels, no triangle mesh",
        },
        "vdaManifestPresent": vda_manifest is not None,
        "outputs": {
            "frontGif": str(out_dir / "front.gif"),
            "compareGif": str(out_dir / "compare.gif"),
            "orbitGif": str(out_dir / "orbit.gif"),
        },
    }
    if vda_manifest is not None:
        manifest["vdaModel"] = vda_manifest.get("model")
        manifest["vdaManifest"] = str(Path(out_dir) / PIPELINE_MANIFEST_NAME)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--synthetic-geometry-fixture",
        "--synthetic-crusader-move",
        dest="synthetic_geometry_fixture",
        action="store_true",
        help="Colored-rectangle depth fixture only. Not HoMM3 / CCRUSD art.",
    )
    parser.add_argument("--sprite-dir", type=Path)
    parser.add_argument("--depth-dir", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--depth-scale", type=float, default=0.35)
    parser.add_argument("--fps", type=float, default=8.0)
    parser.add_argument("--preview-scale", type=int, default=4)
    parser.add_argument(
        "--gap-close-radius",
        type=int,
        default=1,
        help="Morphological close radius for alpha holes before point extraction (0=off).",
    )
    parser.add_argument(
        "--depth-smooth-radius",
        type=int,
        default=1,
        help="Box-smooth VDA depth inside the filled silhouette (0=off).",
    )
    parser.add_argument(
        "--splat-radius",
        type=int,
        default=2,
        help="Pixel stamp size for perspective / orbit previews (>=2 recommended).",
    )
    parser.add_argument(
        "--no-solid-front",
        action="store_true",
        help="Do not composite the filled source sprite for orthographic front views.",
    )
    parser.add_argument(
        "--source-label",
        type=str,
        default=None,
        help="Override the manifest source string. Refused for the synthetic fixture.",
    )
    args = parser.parse_args()

    if args.synthetic_geometry_fixture:
        if args.sprite_dir is not None or args.depth_dir is not None:
            raise SystemExit("synthetic geometry fixture does not take --sprite-dir/--depth-dir")
        if args.source_label is not None:
            raise SystemExit("synthetic geometry fixture cannot take --source-label")
        clip = synthetic_crusader_move_frames(FRAME_COUNT)
        manifest = render_clip(
            clip.sprites,
            clip.depths,
            args.out_dir,
            depth_scale=args.depth_scale,
            fps=args.fps,
            source="synthetic_geometry_fixture",
            vda_manifest=None,
            preview_scale=args.preview_scale,
            gap_close_radius=args.gap_close_radius,
            depth_smooth_radius=args.depth_smooth_radius,
            splat_radius=args.splat_radius,
            solid_front=not args.no_solid_front,
        )
    else:
        if args.sprite_dir is None or args.depth_dir is None:
            raise SystemExit(
                "provide --sprite-dir and --depth-dir for a real clip "
                "(CCRUSD extract + VDA cache). "
                "--synthetic-geometry-fixture is a rectangle test only."
            )
        sprites, depths, vda = load_vda_clip(args.sprite_dir, args.depth_dir)
        manifest = render_clip(
            sprites,
            depths,
            args.out_dir,
            depth_scale=args.depth_scale,
            fps=args.fps,
            source=args.source_label or "vda_pipeline_cache",
            vda_manifest=vda,
            preview_scale=args.preview_scale,
            gap_close_radius=args.gap_close_radius,
            depth_smooth_radius=args.depth_smooth_radius,
            splat_radius=args.splat_radius,
            solid_front=not args.no_solid_front,
        )
    print(json.dumps({"ok": True, "out": str(args.out_dir.resolve()), "frames": manifest["frameCount"]}))


if __name__ == "__main__":
    main()
