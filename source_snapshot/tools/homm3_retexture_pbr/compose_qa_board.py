"""Compose compact labeled Hex/Lit QA board PNGs from render_batch_qa tiles."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from def_sprite_loader import DEFAULT_REPO_ROOT, make_single_def_tile  # noqa: E402

TILE = 384


def _font(size: int = 16):
    for p in ("C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/arial.ttf"):
        if Path(p).is_file():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def compose_batch(
    units: list[str],
    work_dir: Path,
    out_path: Path,
    repo_root: Path = DEFAULT_REPO_ROOT,
    shipped_label: str = "Old Shipped Front3/4",
    compare_pbr: bool = False,
) -> Path:
    fh, fr = _font(18), _font(16)
    cols = [
        ("def", "HoMM3 DEF"),
        ("front_34_shipped", shipped_label),
        ("front_34_hexlit_pbr", "New Hex/Lit PBR Front3/4"),
        ("rear_34_hexlit_pbr", "New Hex/Lit PBR Rear3/4"),
        ("head_hexlit_pbr", "New Hex/Lit PBR Head"),
    ]
    if compare_pbr:
        cols.append(("front_34_cycles_pbr", "Cycles Full PBR Front3/4"))

    label_w, hdr_h = 230, 44
    board = Image.new("RGB", (label_w + len(cols) * TILE, hdr_h + len(units) * TILE), (26, 28, 26))
    draw = ImageDraw.Draw(board)
    for ci, (_, cname) in enumerate(cols):
        draw.text((label_w + ci * TILE + 12, 12), cname, fill=(240, 240, 220), font=fh)

    for ri, u in enumerate(units):
        y0 = hdr_h + ri * TILE
        draw.text((12, y0 + TILE // 2 - 10), u, fill=(225, 225, 205), font=fr)
        tdir = work_dir / u / "renders/qa_tiles"
        for ci, (ckey, _) in enumerate(cols):
            if ckey == "def":
                im = make_single_def_tile(u, repo_root=repo_root, tile_size=TILE, bg_rgb=(44, 46, 44))
            else:
                im = Image.open(tdir / f"{ckey}.png").convert("RGB").resize((TILE, TILE), Image.Resampling.LANCZOS)
            board.paste(im, (label_w + ci * TILE, y0))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    board.save(out_path)
    print(f"Wrote QA board {out_path} ({board.size})")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--units", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    ap.add_argument("--shipped-label", default="Old Shipped Front3/4")
    ap.add_argument("--compare-pbr", action="store_true")
    args = ap.parse_args()
    units = [u.strip() for u in args.units.split(",") if u.strip()]
    compose_batch(units, args.work_dir, args.out, repo_root=args.repo_root, shipped_label=args.shipped_label, compare_pbr=args.compare_pbr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
