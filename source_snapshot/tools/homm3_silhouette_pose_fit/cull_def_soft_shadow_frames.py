#!/usr/bin/env python3
"""Cull HoMM3 DEF soft ground-shadows from sprite PNGs (fail-closed).

Writes culled RGBA next to or into --out-dir. Every frame must lose >=
--min-culled-per-frame shadow pixels (default 1) so a no-op cannot silently
pass when shadows are expected.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from def_soft_shadow import cull_def_soft_shadow_rgba


def cull_png(src: Path, dst: Path) -> int:
    arr = np.asarray(Image.open(src).convert("RGBA"), dtype=np.uint8)
    out, n = cull_def_soft_shadow_rgba(arr)
    dst.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(out, mode="RGBA").save(dst)
    return int(n)


def cull_frame_dir(
    src_dir: Path,
    dst_dir: Path,
    *,
    pattern: str = "frame_*.png",
    min_culled_per_frame: int = 1,
) -> dict:
    srcs = sorted(src_dir.glob(pattern))
    if not srcs:
        raise RuntimeError(f"no frames matching {pattern} under {src_dir}")
    rows = []
    for src in srcs:
        dst = dst_dir / src.name
        n = cull_png(src, dst)
        if n < min_culled_per_frame:
            raise RuntimeError(
                f"fail-closed: {src.name} culled only {n} soft-shadow px "
                f"(min={min_culled_per_frame}); refusing no-op cull"
            )
        rows.append({"frame": src.name, "culledPx": n})
    report = {
        "ok": True,
        "srcDir": str(src_dir).replace("\\", "/"),
        "outDir": str(dst_dir).replace("\\", "/"),
        "frameCount": len(rows),
        "totalCulledPx": int(sum(r["culledPx"] for r in rows)),
        "minCulledPerFrame": min_culled_per_frame,
        "frames": rows,
        "proof": "generated — DEF soft-shadow alpha zeroed (near-black + partial alpha)",
    }
    (dst_dir / "soft_shadow_cull_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src-dir", type=Path, required=True)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Default: write in-place over --src-dir (still fail-closed).",
    )
    ap.add_argument("--pattern", default="frame_*.png")
    ap.add_argument("--min-culled-per-frame", type=int, default=1)
    args = ap.parse_args()
    out = args.out_dir or args.src_dir
    # When out==src, cull via temp names then replace to avoid half-written reads.
    if out.resolve() == args.src_dir.resolve():
        tmp = args.src_dir / "_cull_tmp"
        if tmp.exists():
            for p in tmp.glob("*"):
                p.unlink()
        else:
            tmp.mkdir(parents=True, exist_ok=True)
        report = cull_frame_dir(
            args.src_dir,
            tmp,
            pattern=args.pattern,
            min_culled_per_frame=args.min_culled_per_frame,
        )
        for row in report["frames"]:
            name = row["frame"]
            (tmp / name).replace(args.src_dir / name)
        (tmp / "soft_shadow_cull_report.json").replace(
            args.src_dir / "soft_shadow_cull_report.json"
        )
        tmp.rmdir()
    else:
        report = cull_frame_dir(
            args.src_dir,
            out,
            pattern=args.pattern,
            min_culled_per_frame=args.min_culled_per_frame,
        )
    print(json.dumps({"ok": True, "totalCulledPx": report["totalCulledPx"], "frames": report["frameCount"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
