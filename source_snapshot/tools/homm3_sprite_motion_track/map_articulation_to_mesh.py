#!/usr/bin/env python3
"""Driver: map articulation parts onto the mesh and pose via part/hinge DOFs.

  tools/.venvs/homm3_dwpose/Scripts/python.exe \\
    tools/homm3_sprite_motion_track/map_articulation_to_mesh.py
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BLENDER = Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")
DEFAULT_CONFIG = (
    ROOT
    / "tools/homm3_silhouette_pose_fit/configs/h3_hobgoblin_attack_g11_sprite_motion_track_meshy46_v4_visual_match.json"
)
DEFAULT_ARTICULATION = (
    ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_articulation_motion_g11/articulation_report.json"
)
DEFAULT_OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_articulation_motion_g11/mesh_map"


def _resolve_job(cfg_path: Path, out_dir: Path) -> Path:
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    job = dict(cfg)
    # Absolutize paths used by Blender.
    job["masterGlb"] = str((ROOT / cfg["masterGlb"]).resolve()) if not Path(cfg["masterGlb"]).is_absolute() else cfg["masterGlb"]
    frames = []
    for fr in cfg["frames"]:
        p = Path(fr["path"])
        frames.append({"path": str((ROOT / p).resolve() if not p.is_absolute() else p)})
    job["frames"] = frames
    job["outputDir"] = str(out_dir.resolve())
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved = out_dir / "job.resolved.json"
    resolved.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    return resolved


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--articulation", type=Path, default=DEFAULT_ARTICULATION)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--blender",
        type=Path,
        default=Path(os.environ.get("HOMM3_POSE_FIT_BLENDER", str(DEFAULT_BLENDER))),
    )
    args = ap.parse_args()

    cfg = args.config if args.config.is_absolute() else ROOT / args.config
    art = args.articulation if args.articulation.is_absolute() else ROOT / args.articulation
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    if not art.is_file():
        print(f"missing articulation report: {art}", file=sys.stderr)
        return 2
    art_obj = json.loads(art.read_text(encoding="utf-8"))
    tracks = Path(art_obj.get("tracks") or "")
    if not tracks.is_file() or "partCentroidsPerFrame" not in art_obj:
        print(
            "articulation report lacks tracks.npz / partCentroidsPerFrame — re-run discover_articulation_from_motion.py",
            file=sys.stderr,
        )
        return 2
    if not args.blender.is_file():
        print(f"Blender missing: {args.blender}", file=sys.stderr)
        return 2

    resolved = _resolve_job(cfg, out_dir)
    script = Path(__file__).resolve().parent / "blender_map_articulation_parts.py"
    cmd = [
        str(args.blender),
        "-b",
        "--python",
        str(script),
        "--",
        "--job",
        str(resolved),
        "--articulation",
        str(art.resolve()),
        "--out-dir",
        str(out_dir.resolve()),
    ]
    print(" ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT))
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
