#!/usr/bin/env python3
"""Extract one front_shell mesh per walk frame into a clip manifest.

  python tools/homm3_depth_billboard/extract_depth_volume_clip.py \
      --sprite-dir artifacts/depth_billboard/ccrusd_continuous/sprites_shadow_culled \
      --depth-dir artifacts/depth_billboard/ccrusd_continuous_frame0_vda_connected/vda_cache \
      --frame-start 0 --frame-count 8 \
      --out-dir artifacts/depth_billboard/ccrusd_walk_shell_clip_debowed85
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

DEPTH_BB = Path(__file__).resolve().parent
if str(DEPTH_BB) not in sys.path:
    sys.path.insert(0, str(DEPTH_BB))

from geometry import load_depth01  # noqa: E402
from volume_mesh import extract_depth_mesh, mesh_summary, write_obj_mesh  # noqa: E402


def _frame_path(directory: Path, index: int) -> Path:
    for name in (f"{index}.png", f"{index:02d}.png", f"{index:03d}.png"):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"no sprite/depth frame {index} under {directory}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sprite-dir", type=Path, required=True)
    parser.add_argument("--depth-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--frame-start", type=int, default=0)
    parser.add_argument("--frame-count", type=int, default=8)
    parser.add_argument("--style", choices=("front_shell", "voxel"), default="front_shell")
    parser.add_argument("--depth-scale", type=float, default=0.25)
    parser.add_argument("--gap-close-radius", type=int, default=1)
    parser.add_argument("--depth-smooth-radius", type=int, default=1)
    parser.add_argument("--thickness-scale", type=float, default=2.0)
    parser.add_argument("--depth-edge-strength", type=float, default=0.0)
    parser.add_argument("--depth-edge-falloff", type=float, default=3.0)
    parser.add_argument("--depth-bow-vertical", type=float, default=0.8)
    parser.add_argument("--depth-bow-edge", type=float, default=0.85)
    parser.add_argument("--depth-bow-radius", type=int, default=7)
    parser.add_argument("--depth-wing-lateral", type=float, default=0.0)
    parser.add_argument("--depth-wing-upper-fraction", type=float, default=0.5)
    parser.add_argument("--depth-wing-body-fraction", type=float, default=0.5)
    parser.add_argument("--grid-stride", type=int, default=1)
    parser.add_argument("--no-back-cap", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"refusing to write into a non-empty directory: {out_dir}")
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    frame_entries: list[dict] = []
    total_ms = 0
    for offset in range(int(args.frame_count)):
        frame_index = int(args.frame_start) + offset
        sprite_path = _frame_path(Path(args.sprite_dir), frame_index)
        depth_path = _frame_path(Path(args.depth_dir), frame_index)
        frame_out = frames_dir / f"{frame_index:02d}"
        frame_out.mkdir(parents=True, exist_ok=True)

        rgba = np.asarray(Image.open(sprite_path).convert("RGBA"), dtype=np.uint8)
        depth01 = load_depth01(depth_path)

        started = time.perf_counter()
        mesh = extract_depth_mesh(
            rgba,
            depth01,
            style=args.style,
            depth_scale=args.depth_scale,
            gap_close_radius=args.gap_close_radius,
            depth_smooth_radius=args.depth_smooth_radius,
            thickness_scale=args.thickness_scale,
            depth_edge_strength=args.depth_edge_strength,
            depth_edge_falloff_pixels=args.depth_edge_falloff,
            depth_bow_vertical_strength=args.depth_bow_vertical,
            depth_bow_edge_strength=args.depth_bow_edge,
            depth_bow_local_radius=args.depth_bow_radius,
            depth_wing_lateral_strength=args.depth_wing_lateral,
            depth_wing_lateral_upper_fraction=args.depth_wing_upper_fraction,
            depth_wing_lateral_body_lower_fraction=args.depth_wing_body_fraction,
            grid_stride=args.grid_stride,
            include_back_cap=not args.no_back_cap,
            cell_stride=4,
            z_layers_max=24,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        total_ms += elapsed_ms

        mesh_path = frame_out / "mesh.obj"
        texture_path = frame_out / "sprite.png"
        write_obj_mesh(mesh_path, mesh)
        shutil.copy2(sprite_path, texture_path)

        frame_entries.append(
            {
                "index": frame_index,
                "sprite": str(sprite_path.resolve()),
                "depth": str(depth_path.resolve()),
                "meshObj": str(mesh_path.resolve()),
                "spritePng": str(texture_path.resolve()),
                "mesh": mesh_summary(mesh),
                "extractMs": elapsed_ms,
            }
        )
        print(f"frame {frame_index}: {mesh_summary(mesh)['triangleCount']} tris in {elapsed_ms}ms")

    manifest = {
        "schema": "homm3_depth_billboard_volume_mesh_clip.v1",
        "frameStart": int(args.frame_start),
        "frameCount": int(args.frame_count),
        "params": {
            "style": str(args.style),
            "depthScale": float(args.depth_scale),
            "thicknessScale": float(args.thickness_scale),
            "depthEdgeStrength": float(args.depth_edge_strength),
            "depthBowVerticalStrength": float(args.depth_bow_vertical),
            "depthBowEdgeStrength": float(args.depth_bow_edge),
            "depthBowLocalRadius": int(args.depth_bow_radius),
            "depthSmoothRadius": int(args.depth_smooth_radius),
            "depthWingLateralStrength": float(args.depth_wing_lateral),
            "gridStride": int(args.grid_stride),
            "includeBackCap": not bool(args.no_back_cap),
        },
        "frames": frame_entries,
        "extractMsTotal": total_ms,
        "framesDir": str(frames_dir.resolve()),
    }
    manifest_path = out_dir / "clip_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "manifest": str(manifest_path.resolve()), **manifest}, indent=2))


if __name__ == "__main__":
    main()
