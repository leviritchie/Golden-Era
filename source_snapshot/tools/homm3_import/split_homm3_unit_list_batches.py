#!/usr/bin/env python3
"""Split a HoMM3 unit list into N batch files for memory-safe Unity bundle builds."""
from __future__ import annotations

import argparse
from pathlib import Path


def read_sids(path: Path) -> list[str]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def write_batches(sids: list[str], out_dir: Path, batches: int, prefix: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    n = len(sids)
    if n == 0:
        raise SystemExit("No unit SIDs to batch.")
    size = (n + batches - 1) // batches
    written: list[Path] = []
    for i in range(batches):
        chunk = sids[i * size : (i + 1) * size]
        if not chunk:
            continue
        path = out_dir / f"{prefix}_batch{i + 1}.txt"
        body = "\n".join(chunk) + "\n"
        path.write_text(body, encoding="utf-8")
        written.append(path)
        print(f"{path.name}: {len(chunk)} units ({chunk[0]} .. {chunk[-1]})")
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--unit-list",
        type=Path,
        default=Path(__file__).resolve().parent
        / "rife_production_logs"
        / "manifest_eligible_no_temple_fangarm.txt",
    )
    ap.add_argument("--batches", type=int, default=3)
    ap.add_argument("--prefix", default="manifest_bundle")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "rife_production_logs",
    )
    args = ap.parse_args()
    if args.batches < 1:
        raise SystemExit("--batches must be >= 1")
    if not args.unit_list.is_file():
        raise SystemExit(f"Unit list not found: {args.unit_list}")
    write_batches(read_sids(args.unit_list), args.out_dir, args.batches, args.prefix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
