#!/usr/bin/env python3
"""Compose 3 outpaint variants per faction and emit picker-ready 1080 previews.

Uses the shared Factory-approved recipe from compose_custom_town_4k_background
(including SEAM_FEATHER=256 progressive blur settings).
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

import compose_custom_town_4k_background as recipe

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "artifacts" / "custom_town_4k_work"
AI_DIR = WORK / "_ai_outpaints"
PICKER = WORK / "picker"
VARIANTS = ("v1", "v2", "v3")
FACTIONS = list(recipe.FACTIONS)


def compose_variant(faction: str, variant: str) -> dict:
    ai = AI_DIR / f"homm3_{faction}_background_outpaint_{variant}.png"
    if not ai.is_file():
        raise FileNotFoundError(ai)
    # Temporarily compose into work/{faction}, then rename outputs for the variant.
    meta = recipe.compose_faction(faction, ai, write_final=False)
    faction_work = WORK / faction
    composed = faction_work / f"homm3_{faction}_background_upscaled_3840x2160.png"
    variant_4k = faction_work / f"compose_{variant}_3840x2160.png"
    shutil.copy2(composed, variant_4k)

    preview_dir = PICKER / "previews" / faction
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview = Image.open(variant_4k).convert("RGB").resize((960, 540), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(preview)
    draw.rectangle([0, 0, 220, 30], fill=(0, 0, 0))
    draw.text((8, 8), f"{faction} {variant}", fill=(255, 255, 0))
    preview_path = preview_dir / f"{variant}_1080.png"
    preview.save(preview_path)

    # Do not leave a provisional "final" from intermediate variants.
    provisional_final = recipe.FINALS / f"homm3_{faction}_background_upscaled_3840x2160.png"
    if provisional_final.is_file() and faction != "factory":
        # Keep factory final until selections applied; other provisional finals from
        # earlier single-pass installs may remain — picker apply owns promotion.
        pass

    meta_out = {
        "faction": faction,
        "variant": variant,
        "aiSource": ai.as_posix(),
        "compose4k": variant_4k.as_posix(),
        "preview1080": preview_path.as_posix(),
        "pasteTx": meta["pasteTx"],
        "pasteTy": meta["pasteTy"],
        "alignMad": meta["alignMad"],
        "seamFeather": recipe.SEAM_FEATHER,
        "maxBlurR": recipe.MAX_BLUR_R,
    }
    (faction_work / f"compose_{variant}_meta.json").write_text(
        json.dumps(meta_out, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"{faction}/{variant}: paste=({meta['pasteTx']},{meta['pasteTy']}) "
        f"mad={meta['alignMad']:.2f} feather={recipe.SEAM_FEATHER}"
    )
    return meta_out


def write_manifest(rows: list[dict]) -> Path:
    PICKER.mkdir(parents=True, exist_ok=True)
    by_faction: dict[str, list[dict]] = {}
    for row in rows:
        by_faction.setdefault(row["faction"], []).append(
            {
                "variant": row["variant"],
                "preview": f"previews/{row['faction']}/{row['variant']}_1080.png",
                "compose4k": Path(row["compose4k"]).name,
                "pasteTx": row["pasteTx"],
                "pasteTy": row["pasteTy"],
                "alignMad": row["alignMad"],
            }
        )
    manifest = {
        "seamFeather": recipe.SEAM_FEATHER,
        "maxBlurR": recipe.MAX_BLUR_R,
        "blurFalloffPx": recipe.BLUR_FALLOFF_PX,
        "seamBlurR": recipe.SEAM_BLUR_R,
        "factions": [
            {"id": faction, "variants": by_faction.get(faction, [])}
            for faction in FACTIONS
            if faction in by_faction
        ],
    }
    path = PICKER / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    template = PICKER / "index.template.html"
    if template.is_file():
        html = template.read_text(encoding="utf-8").replace(
            "__MANIFEST_JSON__", json.dumps(manifest, separators=(",", ":"))
        )
        (PICKER / "index.html").write_text(html, encoding="utf-8")
        print(f"wrote {PICKER / 'index.html'}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--faction", action="append", default=[])
    parser.add_argument("--variant", action="append", default=[])
    args = parser.parse_args()
    factions = args.faction or FACTIONS
    variants = args.variant or list(VARIANTS)
    if recipe.SEAM_FEATHER != 256:
        raise SystemExit(f"expected SEAM_FEATHER=256, got {recipe.SEAM_FEATHER}")
    rows: list[dict] = []
    for faction in factions:
        for variant in variants:
            rows.append(compose_variant(faction, variant))
    # Merge with any existing metas if doing a partial run.
    if args.faction or args.variant:
        for faction in FACTIONS:
            for variant in VARIANTS:
                meta_path = WORK / faction / f"compose_{variant}_meta.json"
                if not meta_path.is_file():
                    continue
                if any(r["faction"] == faction and r["variant"] == variant for r in rows):
                    continue
                rows.append(json.loads(meta_path.read_text(encoding="utf-8")))
    path = write_manifest(rows)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
