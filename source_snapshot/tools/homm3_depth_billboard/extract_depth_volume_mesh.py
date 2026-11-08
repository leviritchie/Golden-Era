#!/usr/bin/env python3
"""Extract a lit-ready mesh from one VDA depth-billboard frame.

Default style is ``front_shell``: full-resolution VDA depth surface plus a
silhouette skirt/back cap. Use ``--style voxel`` for the coarse marching-cubes
prototype. Exports OBJ + albedo PNG for Unity experiments.

  python tools/homm3_depth_billboard/extract_depth_volume_mesh.py \
      --sprite artifacts/depth_billboard/ccrusd_continuous/sprites_shadow_culled/0.png \
      --depth artifacts/depth_billboard/ccrusd_continuous_frame0_vda_connected/vda_cache/0.png \
      --out-dir artifacts/depth_billboard/ccrusd_walk_shell_frame0
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

ROOT = Path(__file__).resolve().parents[2]
DEPTH_BB = Path(__file__).resolve().parent
if str(DEPTH_BB) not in sys.path:
    sys.path.insert(0, str(DEPTH_BB))

from geometry import load_depth01  # noqa: E402
from volume_mesh import extract_depth_mesh, mesh_summary, write_obj_mesh  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sprite", type=Path, required=True)
    parser.add_argument("--depth", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--style",
        choices=("front_shell", "voxel"),
        default="front_shell",
        help="front_shell = full-res depth surface + skirt; voxel = marching cubes.",
    )
    parser.add_argument("--depth-scale", type=float, default=0.25)
    parser.add_argument("--gap-close-radius", type=int, default=1)
    parser.add_argument("--depth-smooth-radius", type=int, default=1)
    parser.add_argument("--thickness-scale", type=float, default=2.0)
    parser.add_argument("--depth-edge-strength", type=float, default=0.0)
    parser.add_argument("--depth-edge-falloff", type=float, default=3.0)
    parser.add_argument("--depth-bow-vertical", type=float, default=0.8)
    parser.add_argument("--depth-bow-edge", type=float, default=0.85)
    parser.add_argument("--depth-bow-radius", type=int, default=7)
    parser.add_argument(
        "--grid-stride",
        type=int,
        default=1,
        help="XY sample stride for front_shell (1 = full sprite resolution).",
    )
    parser.add_argument(
        "--no-back-cap",
        action="store_true",
        help="Omit the back cap from front_shell meshes.",
    )
    parser.add_argument(
        "--cell-stride",
        type=int,
        default=4,
        help="XY downsample factor for voxel occupancy (4 = ~48x36 from 192x144).",
    )
    parser.add_argument(
        "--z-layers-max",
        type=int,
        default=24,
        help="Cap Z voxel resolution for performance.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"refusing to write into a non-empty directory: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    rgba = np.asarray(Image.open(args.sprite).convert("RGBA"), dtype=np.uint8)
    depth01 = load_depth01(args.depth)

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
        grid_stride=args.grid_stride,
        include_back_cap=not args.no_back_cap,
        cell_stride=args.cell_stride,
        z_layers_max=args.z_layers_max,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    mesh_path = out_dir / "mesh.obj"
    texture_path = out_dir / "sprite.png"
    write_obj_mesh(mesh_path, mesh)
    shutil.copy2(args.sprite, texture_path)

    summary = {
        "schema": "homm3_depth_billboard_volume_mesh.v1",
        "sprite": str(Path(args.sprite).resolve()),
        "depth": str(Path(args.depth).resolve()),
        "mesh": mesh_summary(mesh),
        "params": {
            "style": str(args.style),
            "depthScale": float(args.depth_scale),
            "gridStride": int(args.grid_stride),
            "includeBackCap": not bool(args.no_back_cap),
            "cellStride": int(args.cell_stride),
            "zLayersMax": int(args.z_layers_max),
            "depthEdgeStrength": float(args.depth_edge_strength),
            "depthBowVerticalStrength": float(args.depth_bow_vertical),
            "depthBowEdgeStrength": float(args.depth_bow_edge),
        },
        "extractMs": elapsed_ms,
        "outputs": {
            "meshObj": str(mesh_path.resolve()),
            "spritePng": str(texture_path.resolve()),
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, **summary}, indent=2))


if __name__ == "__main__":
    main()
