#!/usr/bin/env python3
"""Orchestrate digitize → cull → 3D consensus → sprite-2D projection."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parent
ROOT = TOOL.parents[1]
sys.path.insert(0, str(TOOL))
from constants import MANIFEST, OUT  # noqa: E402


def _run(script: str, extra: list[str] | None = None) -> int:
    cmd = [sys.executable, str(TOOL / script), *(extra or [])]
    print("Running:", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--require-min-overlays", type=int, default=1)
    args = ap.parse_args()
    if not args.manifest.is_file():
        print(f"missing manifest {args.manifest}", file=sys.stderr)
        return 2
    overlays = list((OUT / "overlays").glob("f*/**/*.png"))
    if len(overlays) < args.require_min_overlays:
        print(
            f"need >= {args.require_min_overlays} overlays under {OUT / 'overlays'} "
            f"(found {len(overlays)}). Generate via Cursor GenerateImage checklist in README.",
            file=sys.stderr,
        )
        return 2

    for script in (
        "upscale_sprites_nn.py",
        "digitize_overlays.py",
        "cull_outliers.py",
        "consensus_3d.py",
        "project_sprite_2d.py",
    ):
        rc = _run(script)
        if rc != 0:
            print(f"{script} failed rc={rc}", file=sys.stderr)
            return rc

    summary = {
        "ok": True,
        "overlays": len(overlays),
        "digitize": str(OUT / "digitize" / "samples.jsonl").replace("\\", "/"),
        "culled": str(OUT / "digitize" / "culled_report.json").replace("\\", "/"),
        "joints3d": str(OUT / "consensus" / "joints_3d.json").replace("\\", "/"),
        "joints2d": str(OUT / "consensus" / "joints_2d_sprite.json").replace("\\", "/"),
        "keypoints": str(OUT / "consensus" / "keypoints.json").replace("\\", "/"),
        "proof": "generated artifact validated — dense consensus pipeline; attack-read unproven",
    }
    (OUT / "pilot_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
