#!/usr/bin/env python3
"""Remove stale .meta under Unity homm3_lab extracted_battle (after RIFE mirror)."""
from __future__ import annotations

import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unity-project", type=Path, required=True)
    args = ap.parse_args()
    lab = args.unity_project.resolve() / "Assets" / "CustomUnits" / "homm3_lab"
    if not lab.is_dir():
        print(f"Missing {lab}")
        return 1
    removed = 0
    for meta in lab.glob("*/extracted_battle/**/*.meta"):
        meta.unlink()
        removed += 1
    print(f"Removed {removed} stale .meta file(s) under {lab}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
