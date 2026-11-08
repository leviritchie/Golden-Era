#!/usr/bin/env python3
"""Apply an authored horse/rider/lance/saddle_band part map and fail closed on fused shares."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from owned_rerig.glb_io import load_mesh  # noqa: E402
from owned_rerig.part_map import apply_part_map, load_part_map  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh", type=Path, required=True)
    parser.add_argument("--part-map", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-horse", type=float, default=0.40)
    parser.add_argument("--min-rider", type=float, default=0.10)
    parser.add_argument("--min-lance", type=float, default=0.002)
    parser.add_argument("--max-saddle-band", type=float, default=0.25)
    args = parser.parse_args()
    mesh = load_mesh(args.mesh)
    authored = load_part_map(args.part_map)
    labels = apply_part_map(
        mesh.positions,
        mesh.indices,
        authored,
        min_share={"horse": args.min_horse, "rider": args.min_rider, "lance": args.min_lance},
        max_share={"saddle_band": args.max_saddle_band},
    )
    payload = {
        "schema": "owned_bind_part_labels.v1",
        "mesh": str(args.mesh.resolve()).replace("\\", "/"),
        "partMap": str(args.part_map.resolve()).replace("\\", "/"),
        "labels": [int(v) for v in labels],
        "counts": {
            "horse": int((labels == 0).sum()),
            "rider": int((labels == 1).sum()),
            "lance": int((labels == 2).sum()),
            "saddle_band": int((labels == 3).sum()),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(args.out), "counts": payload["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
