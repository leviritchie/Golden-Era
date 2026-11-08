#!/usr/bin/env python3
"""Build throwaway Swamp-tint terrain textures from Autumn ground textures.

This is a proof asset path for the custom-biome spike. It deliberately creates
sidecar textures for the mod to load at runtime; it does not mutate exported
Unity reference assets or Steam resources.assets.
"""

from __future__ import annotations

import argparse
import colorsys
import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_DIR = (
    ROOT
    / "tools"
    / "reference"
    / "assetripper_olden_demo_unity"
    / "ExportedProject"
    / "Assets"
    / "Resources"
    / "tiles"
    / "textures"
)
DEFAULT_SWAMP_OUTPUT_DIR = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_runtime_assets"
    / "terrain_tint_proofs"
    / "swamp"
)
DEFAULT_AUTUMN_MARKER_OUTPUT_DIR = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_runtime_assets"
    / "terrain_tint_proofs"
    / "autumn_fallback_marker"
)
TEXTURE_NAMES = ("autumn_ground4.png", "autumn_ground1.png", "autumn_ground2.png")


def is_autumn_warm_terrain(r: int, g: int, b: int) -> bool:
    if max(r, g, b) < 32:
        return False
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    if s < 0.14 or v < 0.12:
        return False
    red_or_orange_or_magenta = h <= 0.16 or h >= 0.78
    return red_or_orange_or_magenta and r > g + 4


def tint_pixel(r: int, g: int, b: int, a: int, *, hue: float, value_scale: float) -> tuple[int, int, int, int]:
    if not is_autumn_warm_terrain(r, g, b):
        return r, g, b, a
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    # Preserve terrain contrast while making proof output visually unmistakable.
    new_h = hue
    new_s = max(0.44, min(0.86, s * 0.95 + 0.04))
    new_v = max(0.18, min(0.86, v * value_scale + 0.06))
    nr, ng, nb = colorsys.hsv_to_rgb(new_h, new_s, new_v)
    return round(nr * 255), round(ng * 255), round(nb * 255), a


def tint_image(source: Path, output: Path, *, variant: str, hue: float, value_scale: float) -> dict[str, object]:
    image = Image.open(source).convert("RGBA")
    pixels = image.load()
    changed = 0
    width, height = image.size
    for y in range(height):
        for x in range(width):
            old = pixels[x, y]
            new = tint_pixel(*old, hue=hue, value_scale=value_scale)
            if new != old:
                changed += 1
                pixels[x, y] = new
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return {
        "source": str(source),
        "output": str(output),
        "variant": variant,
        "size": [width, height],
        "changedPixels": changed,
        "totalPixels": width * height,
        "changedPercent": round(changed * 100.0 / max(1, width * height), 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--swamp-output-dir", type=Path, default=DEFAULT_SWAMP_OUTPUT_DIR)
    parser.add_argument("--autumn-marker-output-dir", type=Path, default=DEFAULT_AUTUMN_MARKER_OUTPUT_DIR)
    args = parser.parse_args()

    report = {"swamp": [], "autumnFallbackMarker": []}
    for name in TEXTURE_NAMES:
        source = args.source_dir / name
        if not source.exists():
            raise FileNotFoundError(source)
        report["swamp"].append(
            tint_image(
                source,
                args.swamp_output_dir / name,
                variant="swamp_bright_green",
                hue=0.32,
                value_scale=1.12,
            )
        )
        report["autumnFallbackMarker"].append(
            tint_image(
                source,
                args.autumn_marker_output_dir / name,
                variant="autumn_fallback_blue_marker",
                hue=0.56,
                value_scale=0.82,
            )
        )

    swamp_report_path = args.swamp_output_dir / "swamp_tint_report.json"
    autumn_report_path = args.autumn_marker_output_dir / "autumn_fallback_marker_report.json"
    swamp_report_path.write_text(json.dumps(report["swamp"], indent=2) + "\n", encoding="utf-8")
    autumn_report_path.write_text(json.dumps(report["autumnFallbackMarker"], indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "swampOutputDir": str(args.swamp_output_dir),
                "autumnMarkerOutputDir": str(args.autumn_marker_output_dir),
                "textures": report,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
