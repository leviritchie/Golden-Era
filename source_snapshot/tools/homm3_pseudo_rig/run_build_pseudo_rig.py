#!/usr/bin/env python3
"""Host launcher: Blender build_pseudo_rig.py → crusader_pseudo_master.glb."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
DEFAULT_BLENDER = Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")
DEFAULT_MESH = ROOT / (
    "artifacts/crusader_pose_pipeline/out_meshy_t2_idle_f0/meshes/"
    "idle_f0_meshy6_retexture.glb"
)
DEFAULT_OUT_GLB = ROOT / (
    "artifacts/crusader_pose_pipeline/pseudo_rig/owned_bind/crusader_pseudo_master.glb"
)
DEFAULT_CATALOG = ROOT / (
    "artifacts/crusader_pose_pipeline/pseudo_rig/owned_bind/handle_catalog.json"
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--blender",
        type=Path,
        default=Path(os.environ.get("HOMM3_POSE_FIT_BLENDER", str(DEFAULT_BLENDER))),
    )
    ap.add_argument("--mesh", type=Path, default=DEFAULT_MESH)
    ap.add_argument("--out-glb", type=Path, default=DEFAULT_OUT_GLB)
    ap.add_argument("--out-catalog", type=Path, default=DEFAULT_CATALOG)
    ap.add_argument("--handle-count", type=int, default=48)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--power", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--unit-sid", type=str, default="h3_crusader")
    args = ap.parse_args()

    if not args.blender.is_file():
        print(f"Blender missing: {args.blender}", file=sys.stderr)
        return 2
    if not args.mesh.is_file():
        print(f"mesh missing: {args.mesh}", file=sys.stderr)
        return 2

    cmd = [
        str(args.blender),
        "--background",
        "--python",
        str(TOOL / "build_pseudo_rig.py"),
        "--",
        "--mesh",
        str(args.mesh.resolve()),
        "--out-glb",
        str(args.out_glb.resolve()),
        "--out-catalog",
        str(args.out_catalog.resolve()),
        "--handle-count",
        str(args.handle_count),
        "--k",
        str(args.k),
        "--power",
        str(args.power),
        "--seed",
        str(args.seed),
        "--unit-sid",
        str(args.unit_sid),
    ]
    print("Running:", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT))
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
