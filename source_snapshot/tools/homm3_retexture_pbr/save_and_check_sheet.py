"""Convert a generated JPG/PNG 2x2 repaint sheet to 2048x2048 PNG and verify panel IoUs."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_unit import extract_panels, register_panel_to_alpha, sheet_views  # noqa: E402


def save_and_check(
    unit: str,
    work_dir: Path,
    sheet: str,
    src: Path,
    min_iou: float = 0.85,
) -> tuple[bool, float, dict[str, dict]]:
    unit_dir = work_dir / unit
    out_dir = unit_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"repaint_{sheet}.png"

    with Image.open(src) as raw:
        im = raw.convert("RGB")
        if im.size != (2048, 2048):
            im = im.resize((2048, 2048), Image.Resampling.LANCZOS)
        im.save(dst)

    vnames = sheet_views(sheet)
    panels = extract_panels(dst, vnames, 1024)
    summary: list[str] = []
    reports: dict[str, dict] = {}
    worst = 1.0
    for vn in vnames:
        alpha = np.load(unit_dir / "views" / f"{vn}_alpha.npy")
        _, _, rep = register_panel_to_alpha(panels[vn], alpha, f"{unit}/{vn}")
        reports[vn] = rep
        worst = min(worst, float(rep["iouPost"]))
        summary.append(f"{vn}={rep['iouPost']:.3f}(pre={rep['iouPre']:.3f})")
    print(f"{unit} [{sheet}] -> {dst.name}: " + ", ".join(summary))
    return worst >= min_iou, worst, reports


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--unit", required=True)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--sheet", required=True, choices=["primary", "secondary", "tertiary"])
    ap.add_argument("--src", required=True, type=Path)
    ap.add_argument("--min-iou", type=float, default=0.85)
    args = ap.parse_args()

    ok, worst, _ = save_and_check(args.unit, args.work_dir, args.sheet, args.src, min_iou=args.min_iou)
    if not ok:
        print(f"WARN: worst IoU {worst:.3f} < {args.min_iou:.2f}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
