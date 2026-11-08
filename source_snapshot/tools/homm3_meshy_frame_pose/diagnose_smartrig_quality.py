#!/usr/bin/env python3
"""Diagnose whether a Meshy/Mixamo smart-rig is unfit for delivery."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from owned_rerig.diagnose import diagnose_smartrig_quality  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--glb", type=Path, required=True)
    parser.add_argument("--species", default="rider_mount")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = diagnose_smartrig_quality(args.glb, expected_species=args.species)
    text = json.dumps(report, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0 if report["verdict"] in {"keep", "replace"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
