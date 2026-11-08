#!/usr/bin/env python3
"""AI-style portrait upscaler for HoMM3 unit portraits.

Uses Lanczos resampling + adaptive unsharp masking to upscale 32x32 CPRSMALL frames
to larger sizes with simulated detail enhancement. No external ML models required.

Supports:
  --scale N  : upscale factor (default 4, 32->128)
  --sharpen  : radii for unsharp mask (default 1.5,0.8)
  --source   : input directory of PNGs named by SID
  --output   : output directory for upscaled PNGs
"""

import argparse
import os
import shutil
import sys

from PIL import Image, ImageFilter


CPRSMALL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extracted", "cprsmall.dir")

STRONGHOLD_MAP = {
    86: ["h3_goblin"],
    87: ["h3_goblin_upg", "h3_goblin_upg_alt"],
    88: ["h3_wolf_rider"],
    89: ["h3_wolf_rider_upg", "h3_wolf_rider_upg_alt"],
    90: ["h3_orc"],
    91: ["h3_orc_upg", "h3_orc_upg_alt"],
    92: ["h3_ogre"],
    93: ["h3_ogre_upg", "h3_ogre_upg_alt"],
    94: ["h3_roc"],
    95: ["h3_roc_upg", "h3_roc_upg_alt"],
    96: ["h3_cyclops"],
    97: ["h3_cyclops_upg", "h3_cyclops_upg_alt"],
    98: ["h3_behemoth"],
    99: ["h3_behemoth_upg", "h3_behemoth_upg_alt"],
}

DEFAULT_SCALE = 4  # 32 -> 128


def upscale_portrait(img: Image.Image, scale: int, sharpen_radius: float, sharpen_amount: float) -> Image.Image:
    """Upscale with Lanczos + adaptive unsharp mask for detail enhancement."""
    w, h = img.size
    new_size = (w * scale, h * scale)

    # Step 1: Lanczos upscale (best quality for pixel art)
    upscaled = img.resize(new_size, Image.Resampling.LANCZOS)

    # Step 2: Adaptive unsharp mask — enhances edges without over-smoothing flat areas
    if sharpen_radius > 0 and sharpen_amount > 0:
        upscaled = upscaled.filter(ImageFilter.UnsharpMask(radius=sharpen_radius, percent=int(sharpen_amount * 100)))

    return upscaled


def main():
    ap = argparse.ArgumentParser(description="AI-style upscale HoMM3 portraits")
    ap.add_argument("--scale", type=int, default=DEFAULT_SCALE, help=f"Upscale factor (default {DEFAULT_SCALE})")
    ap.add_argument("--sharpen", type=str, default="1.5,0.8", help="sharpen radius,amount (default 1.5,0.8)")
    ap.add_argument("--source", type=str, default=None, help="Source directory with frame PNGs (default: generated CPRSMALL dir)")
    ap.add_argument("--output", type=str, default=None, help="Output directory for upscaled portraits")
    args = ap.parse_args()

    # Parse sharpen params
    sharpen_parts = args.sharpen.split(",")
    sharpen_radius = float(sharpen_parts[0]) if len(sharpen_parts) >= 1 else 1.5
    sharpen_amount = float(sharpen_parts[1]) if len(sharpen_parts) >= 2 else 0.8

    source_dir = args.source or CPRSMALL_DIR
    if not os.path.isdir(source_dir):
        print(f"ERROR: source directory not found: {source_dir}", file=sys.stderr)
        sys.exit(1)

    # Default output: mod portraits directory
    if args.output:
        out_dir = args.output
    else:
        out_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "Heroes of Might & Magic Olden Era Playtest",
            "OfflineUnlockMod",
            "homm3_portraits"
        )
    os.makedirs(out_dir, exist_ok=True)

    print(f"Upscaling {args.scale}x (32 -> {32 * args.scale}) with sharpen radius={sharpen_radius} amount={sharpen_amount}")
    print(f"Source: {source_dir}")
    print(f"Output: {out_dir}")
    print()

    copied = 0

    # Also handle arbitrary SID -> PNG if user provided a different source
    # First check if source has sid-named PNGs directly
    sid_files = {}
    for f in os.listdir(source_dir):
        if f.endswith(".png"):
            sid = os.path.splitext(f)[0]
            sid_files[sid] = os.path.join(source_dir, f)

    all_sids = []
    for frame_idx, sids in sorted(STRONGHOLD_MAP.items()):
        all_sids.extend(sids)

    for sid in all_sids:
        # Try sid-named file first, then CPRSMALL frame
        src_file = sid_files.get(sid)
        if src_file and os.path.exists(src_file):
            img = Image.open(src_file)
        else:
            # Try CPRSMALL frame
            frame_idx = None
            for fid, sids in STRONGHOLD_MAP.items():
                if sid in sids:
                    frame_idx = fid
                    break
            if frame_idx is None:
                print(f"  SKIP {sid}: no frame mapping")
                continue
            src_file = os.path.join(source_dir, f"00_{frame_idx:02d}.png")
            if not os.path.exists(src_file):
                print(f"  SKIP {sid}: frame {frame_idx} not found")
                continue
            img = Image.open(src_file)

        # Upscale
        upscaled = upscale_portrait(img, args.scale, sharpen_radius, sharpen_amount)

        out_path = os.path.join(out_dir, f"{sid}.png")
        upscaled.save(out_path, "PNG")
        print(f"  {sid}.png  {img.size} -> {upscaled.size}")
        copied += 1

    print(f"\nUpscaled {copied} portraits -> {out_dir}")
    print(f"Scale: {args.scale}x, Sharpen: radius={sharpen_radius} amount={sharpen_amount}")


if __name__ == "__main__":
    main()