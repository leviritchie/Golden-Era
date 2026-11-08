#!/usr/bin/env python3
"""Run owned species bind for a failed smart-rig (Cavalier / rider_mount default)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from owned_rerig.pipeline import run_owned_rerig_pipeline  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--src", type=Path)
    parser.add_argument("--part-map", type=Path)
    parser.add_argument("--species", default="rider_mount")
    parser.add_argument("--unit-sid", default="h3_cavalier")
    parser.add_argument(
        "--allow-synthetic-fixture",
        action="store_true",
        help="Use the labeled Mixamo-on-mount fixture when the Cavalier GLB is not in the worktree.",
    )
    parser.add_argument(
        "--landmarks-3d",
        type=Path,
        help="Optional JSON object mapping bone names to [x,y,z] heads (overrides AABB).",
    )
    args = parser.parse_args()
    landmarks = None
    if args.landmarks_3d is not None:
        payload = json.loads(Path(args.landmarks_3d).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("landmarks-3d JSON must be an object of bone name -> [x,y,z]")
        if isinstance(payload.get("bones"), dict):
            payload = payload["bones"]
        landmarks = {}
        for name, xyz in payload.items():
            if name in {"schema", "unitSid", "method", "notes", "bones"}:
                continue
            landmarks[str(name)] = [float(v) for v in xyz]
        if not landmarks:
            raise ValueError("landmarks-3d JSON has no bone -> [x,y,z] entries")
    report = run_owned_rerig_pipeline(
        dest_dir=args.out_dir,
        src_glb=args.src,
        part_map_path=args.part_map,
        species=args.species,
        unit_sid=args.unit_sid,
        allow_synthetic_fixture=args.allow_synthetic_fixture,
        landmarks_3d=landmarks,
    )
    print(json.dumps({k: report[k] for k in report if k not in {"quality", "audit"}} | {"auditOk": report["audit"]["ok"], "verdict": report["quality"]["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
