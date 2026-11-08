#!/usr/bin/env python3
"""Build the CCRUSD group-0 depth-billboard preview from the Golden Era bundle.

This is the crusader-move proof path. It does not use the rectangle fixture.

  python tools/homm3_depth_billboard/build_ccrusd_move_preview.py \
      --bundle custom_units_castle_h3_crusader \
      --checkpoint artifacts/model_cache/video_depth_anything_vits.pth \
      --out-dir artifacts/depth_billboard/ccrusd_g00
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POSE_FIT = ROOT / "tools" / "homm3_silhouette_pose_fit"
if str(POSE_FIT) not in sys.path:
    sys.path.insert(0, str(POSE_FIT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from alpha_shadow_cull import cull_alpha_shadows

from extract_ccrusd_move import extract_group0_native_from_bundle, write_native_clip
from run_depth_billboard import load_vda_clip, render_clip
from run_vda_movement_depth import DEFAULT_CHECKPOINT, ensure_vda_pipeline_cache


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
        help="Feed raw extracted sprites to VDA (shadows pollute depth; default culls first).",
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

    names, frames = extract_group0_native_from_bundle(args.bundle)
    extract_manifest = write_native_clip(
        frames,
        names,
        sprites_raw,
        crop=True,
        pad=16,
        source_bundle=args.bundle,
    )
    shadow_cull_manifest: dict | None = None
    if args.no_shadow_cull:
        sprites = sprites_raw
    else:
        cull_alpha_shadows(sprites_raw, sprites)
        manifest_path = sprites / ".alpha_shadow_cull_manifest.json"
        shadow_cull_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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
        source="ccrusd_g00_native_vda",
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
    for name in ("front.gif", "orbit.gif", "compare.gif"):
        shutil.copy2(preview / name, out_dir / name)
    print(json.dumps({"ok": True, "out": str(out_dir.resolve())}, indent=2))


if __name__ == "__main__":
    main()
