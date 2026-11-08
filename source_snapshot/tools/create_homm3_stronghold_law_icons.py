from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
MOD_DIR = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
PORTRAIT_DIR = MOD_DIR / "homm3_portraits"
OUT_DIR = MOD_DIR / "homm3_law_icons"

LAW_ICON_TO_UNIT = {
    "fraction_law_homm3_stronghold_4_icon": "h3_goblin",
    "fraction_law_homm3_stronghold_10_icon": "h3_wolf_rider",
    "fraction_law_homm3_stronghold_11_icon": "h3_orc",
    "fraction_law_homm3_stronghold_18_icon": "h3_ogre",
    "fraction_law_homm3_stronghold_19_icon": "h3_roc",
    "fraction_law_homm3_stronghold_25_icon": "h3_cyclops",
    "fraction_law_homm3_stronghold_31_icon": "h3_behemoth",
}


def make_icon(portrait: Image.Image) -> Image.Image:
    src = portrait.convert("RGBA").resize((86, 86), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Outer and inner law-medallion rings, tuned for readability at small UI sizes.
    draw.ellipse((8, 8, 120, 120), fill=(44, 27, 18, 238), outline=(226, 171, 72, 255), width=4)
    draw.ellipse((15, 15, 113, 113), fill=(72, 43, 24, 238), outline=(105, 66, 37, 255), width=3)
    draw.pieslice((18, 18, 110, 110), 205, 335, fill=(103, 62, 28, 120))

    shadow = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.ellipse((23, 24, 105, 106), fill=(0, 0, 0, 180))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(5)))

    mask = Image.new("L", (86, 86), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, 85, 85), fill=255)
    canvas.paste(src, (21, 19), mask)

    draw = ImageDraw.Draw(canvas)
    draw.ellipse((20, 18, 107, 105), outline=(248, 209, 112, 245), width=3)
    draw.arc((8, 8, 120, 120), 225, 315, fill=(255, 231, 139, 255), width=3)
    draw.arc((8, 8, 120, 120), 35, 145, fill=(126, 76, 34, 255), width=3)

    return canvas


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "sourceDir": str(PORTRAIT_DIR),
        "note": "Generated Stronghold law icons from HoMM3 unit portrait PNGs.",
        "lawIconToUnit": LAW_ICON_TO_UNIT,
    }
    for icon_sid, unit_sid in LAW_ICON_TO_UNIT.items():
        src_path = PORTRAIT_DIR / f"{unit_sid}.png"
        if not src_path.is_file():
            raise FileNotFoundError(src_path)
        icon = make_icon(Image.open(src_path))
        icon.save(OUT_DIR / f"{icon_sid}.png")
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {len(LAW_ICON_TO_UNIT)} law icons to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
