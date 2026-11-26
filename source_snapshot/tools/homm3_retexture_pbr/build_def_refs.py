"""Build 2x2 HoMM3 DEF sprite reference sheets (<work-dir>/<unit>/ref/def_ref_2x2.png)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from def_sprite_loader import DEFAULT_REPO_ROOT, pick_diverse_def_crops  # noqa: E402


def build_unit_ref(unit: str, work_dir: Path, repo_root: Path = DEFAULT_REPO_ROOT) -> Path:
    picks = pick_diverse_def_crops(unit, repo_root=repo_root, count=4, bg_rgb=(127, 127, 127))
    w_tile = 512
    canvas = Image.new("RGB", (w_tile * 2, w_tile * 2), (127, 127, 127))
    draw = ImageDraw.Draw(canvas)
    for k, (idx, crop) in enumerate(picks):
        im = Image.fromarray(crop)
        scale = max(1, min(440 // max(1, im.width), 430 // max(1, im.height)))
        up = im.resize((im.width * scale, im.height * scale), Image.Resampling.NEAREST)
        ox = (k % 2) * w_tile + (w_tile - up.width) // 2
        oy = (k // 2) * w_tile + (w_tile - up.height) // 2 + 12
        canvas.paste(up, (ox, oy))
        draw.text(((k % 2) * w_tile + 16, (k // 2) * w_tile + 10), f"{unit} DEF #{idx}", fill=(245, 245, 245))

    out_p = work_dir / unit / "ref/def_ref_2x2.png"
    out_p.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_p)
    print(f"Wrote {out_p} (frames={[p[0] for p in picks]})")
    return out_p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--units", default="", help="Comma-separated labSids")
    ap.add_argument("--selection", default="", help="Optional path to slice JSON")
    ap.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    args = ap.parse_args()

    units: list[str] = []
    if args.selection:
        sel = json.loads(Path(args.selection).read_text(encoding="utf-8"))
        units.extend(r["labSid"] for r in sel["units"])
    if args.units:
        units.extend(u.strip() for u in args.units.split(",") if u.strip())
    if not units:
        ap.error("Provide --units or --selection")

    for u in units:
        build_unit_ref(u, work_dir=args.work_dir, repo_root=args.repo_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
