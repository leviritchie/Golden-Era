#!/usr/bin/env python3
"""Build a continuous CCRUSD depth-billboard clip: all bundle animations + idle gaps.

Each non-idle animation in the crusader billboard bundle is concatenated in
DEF group order (move, hitted, death, attack_front). One full idle loop is
inserted between each animation. Shadow-culled plates are sent to VDA as one
continuous temporal clip.

  python tools/homm3_depth_billboard/build_ccrusd_continuous_preview.py \
      --bundle dist/.../custom_units_castle_h3_crusader \
      --checkpoint artifacts/model_cache/video_depth_anything_vits.pth \
      --out-dir artifacts/depth_billboard/ccrusd_continuous
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POSE_FIT = ROOT / "tools" / "homm3_silhouette_pose_fit"
if str(POSE_FIT) not in sys.path:
    sys.path.insert(0, str(POSE_FIT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from alpha_shadow_cull import cull_alpha_shadows

from ccrusd_bundle import build_continuous_native_clip, write_numbered_sprites
from run_depth_billboard import load_vda_clip, render_clip
from run_vda_movement_depth import DEFAULT_CHECKPOINT, ensure_vda_pipeline_cache


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
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--vda-root", type=Path, default=None)
    parser.add_argument("--allow-cpu", action="store_true")
    parser.add_argument("--depth-scale", type=float, default=0.45)
    parser.add_argument("--preview-scale", type=int, default=4)
    parser.add_argument("--gap-close-radius", type=int, default=1)
    parser.add_argument("--depth-smooth-radius", type=int, default=1)
    parser.add_argument("--splat-radius", type=int, default=2)
    parser.add_argument("--no-solid-front", action="store_true")
    parser.add_argument(
        "--no-shadow-cull",
        action="store_true",
        help="Feed raw extracted sprites to VDA (default culls alpha shadows first).",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"refusing to write into a non-empty directory: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    sprites_raw = out_dir / "sprites_raw"
    sprites = out_dir / "sprites_shadow_culled"
    depth = out_dir / "vda_cache"
    preview = out_dir / "preview"

    frames, clip_manifest = build_continuous_native_clip(args.bundle)
    extract_manifest = write_numbered_sprites(frames, sprites_raw, clip_manifest)

    shadow_cull_manifest: dict | None = None
    if args.no_shadow_cull:
        sprites = sprites_raw
    else:
        cull_alpha_shadows(sprites_raw, sprites)
        shadow_cull_manifest = json.loads(
            (sprites / ".alpha_shadow_cull_manifest.json").read_text(encoding="utf-8")
        )

    cache = ensure_vda_pipeline_cache(
        source_dir=sprites,
        output_dir=depth,
        checkpoint=args.checkpoint,
        allow_cpu=args.allow_cpu,
        vda_root=args.vda_root,
    )
    sprites_loaded, depths, vda = load_vda_clip(sprites, depth)
    render_manifest = render_clip(
        sprites_loaded,
        depths,
        preview,
        depth_scale=args.depth_scale,
        fps=12.0,
        source="ccrusd_continuous_native_vda",
        vda_manifest=vda,
        preview_scale=args.preview_scale,
        gap_close_radius=args.gap_close_radius,
        depth_smooth_radius=args.depth_smooth_radius,
        splat_radius=args.splat_radius,
        solid_front=not args.no_solid_front,
    )

    summary = {
        "extract": extract_manifest,
        "spritesRawDir": str(sprites_raw.resolve()),
        "spritesVdaDir": str(sprites.resolve()),
        "alphaShadowCulled": not args.no_shadow_cull,
        "shadowCull": shadow_cull_manifest,
        "vdaCache": cache,
        "preview": render_manifest,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    exports: list[str] = []
    for name in ("front.gif", "orbit.gif", "compare.gif"):
        dest = out_dir / name
        shutil.copy2(preview / name, dest)
        exports.append(str(dest.resolve()))
        try:
            mp4 = _encode_mp4(dest)
            exports.append(str(mp4.resolve()))
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

    print(
        json.dumps(
            {
                "ok": True,
                "out": str(out_dir.resolve()),
                "totalFrames": extract_manifest["totalFrameCount"],
                "segments": extract_manifest["segments"],
                "exports": exports,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
