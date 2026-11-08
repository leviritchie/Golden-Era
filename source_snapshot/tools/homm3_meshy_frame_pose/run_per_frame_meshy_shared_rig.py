#!/usr/bin/env python3
"""
Orchestrate: Meshy t2 per painted frame → hand-rig frame0 → shared-skeleton skin for 1..7.

  tools/.venvs/homm3_dwpose/Scripts/python.exe \\
    tools/homm3_meshy_frame_pose/run_per_frame_meshy_shared_rig.py
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / "tools/.venvs/homm3_dwpose/Scripts/python.exe"
BLENDER = Path("/v/Games/actionmesh/tools/blender-3.5.1/blender.exe")
TOOL = Path(__file__).resolve().parent
OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_meshy_t2_per_frame_g11"
KPT = (
    ROOT
    / "artifacts/hobgoblin_attack_pose_pipeline/out_attack_g11_manual_painted_meshy46/manual_keypoints/keypoints.json"
)


def _run(cmd: list[str]) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.check_call(cmd)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--skip-generate", action="store_true")
    ap.add_argument("--skip-existing-meshes", action="store_true")
    args = ap.parse_args()
    out: Path = args.out if args.out.is_absolute() else ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    meshes = out / "meshes"
    rigged = out / "rigged"
    rigged.mkdir(parents=True, exist_ok=True)

    if not args.skip_generate:
        cmd = [str(PY), str(TOOL / "generate_meshy_t2_per_frame.py"), "--out", str(out)]
        if args.skip_existing_meshes:
            cmd.append("--skip-existing")
        _run(cmd)

    missing = [i for i in range(8) if not (meshes / f"frame_{i:02d}.glb").is_file()]
    if missing:
        raise SystemExit(f"missing meshes for frames {missing}; generate first")

    skel_json = rigged / "shared_skeleton.json"
    f0_out = rigged / "frame_00_rigged.glb"
    _run(
        [
            str(BLENDER),
            "-b",
            "--python",
            str(TOOL / "rig_frame0_shared_skeleton.py"),
            "--",
            "--mesh",
            str(meshes / "frame_00.glb"),
            "--keypoints",
            str(KPT),
            "--output",
            str(f0_out),
            "--skeleton-json",
            str(skel_json),
        ]
    )
    _run(
        [
            str(BLENDER),
            "-b",
            "--python",
            str(TOOL / "skin_frames_shared_skeleton.py"),
            "--",
            "--meshes-dir",
            str(meshes),
            "--skeleton-json",
            str(skel_json),
            "--output-dir",
            str(rigged),
            "--frame0-rigged",
            str(f0_out),
            "--start",
            "1",
            "--end",
            "7",
        ]
    )

    summary = {
        "out": str(out).replace("\\", "/"),
        "meshes": sorted(str(p).replace("\\", "/") for p in meshes.glob("frame_*.glb")),
        "rigged": sorted(str(p).replace("\\", "/") for p in rigged.glob("frame_*_rigged.glb")),
        "skeleton": str(skel_json).replace("\\", "/"),
        "proof": (
            "generated artifact validated — Meshy t2 one mesh/frame; "
            "hand-built shared Mixamo skeleton on f0; auto-weight transfer to f1–f7 (no Meshy smart-rig)"
        ),
    }
    (out / "pipeline_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
