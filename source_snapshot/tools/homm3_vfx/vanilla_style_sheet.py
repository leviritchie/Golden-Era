"""Stack units' lab hero pages (OLD | NEW | VANILLA) into one comparison sheet plus a json index.

    python tools/homm3_vfx/vanilla_style_sheet.py --name <faction> <unit> [<unit> ...]

Writes artifacts/vanilla_vfx_style/lab/<name>_comparison.png and <name>_comparison.json (per unit: hero, clip
sheets, compare.mp4; missing units are listed, never silently dropped). Lab-render tier only.
"""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

LAB = Path(__file__).resolve().parents[2] / "artifacts/vanilla_vfx_style/lab"
W = 1800


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="sheet name, e.g. the faction")
    ap.add_argument("units", nargs="+")
    a = ap.parse_args()
    rows, index = [], []
    for u in a.units:
        d = LAB / u
        hero = d / "hero.png"
        if not hero.is_file():
            index.append({"unit": u, "missing": True})
            continue
        im = Image.open(hero).convert("RGB")
        im = im.resize((W, round(im.height * W / im.width)), Image.LANCZOS)
        band = Image.new("RGB", (W, im.height + 28), (24, 24, 24))
        band.paste(im, (0, 28))
        ImageDraw.Draw(band).text((8, 7), u, fill=(255, 220, 120))
        rows.append(band)
        index.append({"unit": u, "hero": str(hero), "sheets": sorted(str(p) for p in d.glob("sheet_*.png")),
                      "video": str(d / "compare.mp4")})
    if not rows:
        raise SystemExit("no unit has a lab hero.png; run vanilla_style_lab.py first")
    sheet = Image.new("RGB", (W, sum(r.height for r in rows)), (24, 24, 24))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height
    out = LAB / f"{a.name}_comparison.png"
    sheet.save(out, optimize=True)
    (LAB / f"{a.name}_comparison.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    missing = [i["unit"] for i in index if i.get("missing")]
    print(out, sheet.size, "missing:", missing)
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
