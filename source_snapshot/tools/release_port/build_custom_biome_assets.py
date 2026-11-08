#!/usr/bin/env python3
"""Build sidecar terrain textures and runtime biome definitions for custom biomes."""

from __future__ import annotations

import argparse
import colorsys
import json
import subprocess
import shutil
import sys
from pathlib import Path
from typing import Callable

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = (
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
PLUGIN_ROOT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
CUSTOM_BIOME_ROOT = PLUGIN_ROOT / "homm3_runtime_assets" / "custom_biomes"
DEFINITION_PATH = CUSTOM_BIOME_ROOT / "custom_biomes.json"
CANONICAL_PREVIEW_SCRIPT = ROOT / "tools" / "release_port" / "build_vcmi_faction_canonical_terrain_previews.py"
CANONICAL_PREVIEW_ROOT = ROOT / "artifacts" / "custom_biome_work" / "homm3_faction_terrain_sim"
# Ocean tiles 18-22 are not custom-biome texture rows. Runtime clones the native Sand seabed
# under the waterMap mesh via AppendNativeWaterTerrainBiomesFromCatalog.


DONORS = {
    "Grass": {"tile": 1, "files": ["grass1.png", "grass2.png", "grass3.png"]},
    "Sand": {"tile": 2, "files": ["sand1.png", "sand2.png", "sand3.png"]},
    "Deathland": {"tile": 3, "files": ["dead_ground1.png", "dead_ground2.png", "dead_ground3.png"]},
    "Snow": {"tile": 4, "files": ["Snow1.png", "Snow2.png", "Snow4.png"]},
    "Autumn": {"tile": 5, "files": ["autumn_ground4.png", "autumn_ground1.png", "autumn_ground2.png"]},
    "Lava": {"tile": 6, "files": ["lava_blank.png", "lava_cracks.png", "lava_glowy.png"]},
    "Dirt": {"tile": 7, "files": ["dirt_ground1.png", "dirt_ground2.png", "dirt_ground3.png"]},
}


BIOMES = [
    {"id": "swamp", "name": "Swamp", "tileCode": 8, "donor": "Autumn", "soundDonor": "Grass", "textureDir": "homm3_runtime_assets/terrain_tint_proofs/swamp", "files": ["autumn_ground4.png", "autumn_ground1.png", "autumn_ground2.png"], "markerDir": "homm3_runtime_assets/terrain_tint_proofs/autumn_fallback_marker"},
    {"id": "tundra", "name": "Tundra", "tileCode": 9, "donor": "Snow", "soundDonor": "Snow", "materialAliasOnly": False},
    {"id": "hills", "name": "Hills", "tileCode": 10, "donor": "Grass", "soundDonor": "Grass", "materialAliasOnly": False},
    {"id": "wasteland", "name": "Wasteland", "tileCode": 11, "donor": "Sand", "soundDonor": "Sand", "variant": "wasteland_tan"},
    {"id": "tropical", "name": "Tropical", "tileCode": 12, "donor": "Sand", "soundDonor": "Sand", "materialAliasOnly": False},
    {"id": "greenlands", "name": "Greenlands", "tileCode": 13, "donor": "Grass", "soundDonor": "Grass", "variant": "greenlands_vibrant"},
    {"id": "curselands", "name": "Curselands", "tileCode": 14, "donor": "Deathland", "soundDonor": "Deathland", "variant": "curselands_grey"},
    {"id": "burrow", "name": "Burrow", "tileCode": 15, "donor": "Dirt", "soundDonor": "Dirt", "variant": "burrow_darker"},
    {"id": "valleys", "name": "Valleys", "tileCode": 16, "donor": "Grass", "soundDonor": "Grass", "materialAliasOnly": False},
    {"id": "molten", "name": "Molten", "tileCode": 17, "donor": "Lava", "soundDonor": "Lava", "materialAliasOnly": False},
    {"id": "void", "name": "Void", "tileCode": 23, "donor": "Dirt", "soundDonor": "Dirt", "variant": "void_black"},
    # 24-28 are retired display-water Sand aliases; do not reuse those tile codes.
    {"id": "foundry", "name": "Foundry", "tileCode": 29, "donor": "Sand", "soundDonor": "Sand", "variant": "copy"},
    {"id": "permafrost", "name": "Permafrost", "tileCode": 30, "donor": "Snow", "soundDonor": "Snow", "variant": "copy"},
]

CANONICAL_RANGE49_68_BY_BIOME = {
    "valleys": "homm3_castle_sim_range49_68_512_nn2x.png",
    "hills": "homm3_rampart_sim_range49_68_512_nn2x.png",
    "wasteland": "homm3_stronghold_sim_range49_68_512_nn2x.png",
    "molten": "homm3_inferno_sim_range49_68_512_nn2x.png",
    "tundra": "homm3_tower_sim_range49_68_512_nn2x.png",
    "tropical": "homm3_cove_sim_range49_68_512_nn2x.png",
}


def clamp(value: float) -> int:
    return max(0, min(255, round(value)))


def transform_pixel(r: int, g: int, b: int, a: int, variant: str) -> tuple[int, int, int, int]:
    if a == 0 or variant == "copy":
        return r, g, b, a
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    if variant == "wasteland_tan":
        if v < 0.08:
            return r, g, b, a
        nh = 0.095
        ns = min(0.62, max(0.22, s * 0.9 + 0.10))
        nv = min(0.84, max(0.15, v * 0.94 + 0.05))
        nr, ng, nb = colorsys.hsv_to_rgb(nh, ns, nv)
        return clamp(nr * 255), clamp(ng * 255), clamp(nb * 255), a
    if variant == "greenlands_vibrant":
        if v < 0.08:
            return r, g, b, a
        nh = 0.30 if 0.16 <= h <= 0.48 else h
        ns = min(0.86, s * 1.28 + 0.08)
        nv = min(0.92, v * 1.10 + 0.04)
        nr, ng, nb = colorsys.hsv_to_rgb(nh, ns, nv)
        return clamp(nr * 255), clamp(ng * 255), clamp(nb * 255), a
    if variant == "curselands_grey":
        grey = (r * 0.299 + g * 0.587 + b * 0.114)
        return clamp(grey * 0.92), clamp(grey * 0.92), clamp(grey * 0.96), a
    if variant == "burrow_darker":
        return clamp(r * 0.78), clamp(g * 0.74), clamp(b * 0.70), a
    if variant == "void_black":
        return 0, 0, 0, a
    return r, g, b, a


def build_texture(source: Path, output: Path, variant: str) -> dict[str, object]:
    output.parent.mkdir(parents=True, exist_ok=True)
    if variant == "copy":
        shutil.copy2(source, output)
        return {"source": str(source), "output": str(output), "variant": variant, "changedPixels": 0}
    image = Image.open(source).convert("RGBA")
    pixels = image.load()
    changed = 0
    width, height = image.size
    for y in range(height):
        for x in range(width):
            old = pixels[x, y]
            new = transform_pixel(*old, variant)
            if new != old:
                changed += 1
                pixels[x, y] = new
    image.save(output)
    return {"source": str(source), "output": str(output), "variant": variant, "size": [width, height], "changedPixels": changed}


def ensure_canonical_previews() -> None:
    # Keep overlay output deterministic: always regenerate canonical preview inputs.
    subprocess.check_call([sys.executable, str(CANONICAL_PREVIEW_SCRIPT)], cwd=str(ROOT))


def definition_row(biome: dict[str, object], donor: dict[str, object], sound_donor: dict[str, object], texture_dir: str, files: list[str]) -> dict[str, object]:
    row = {
        "id": biome["id"],
        "enabled": True,
        "name": biome["name"],
        "tileCode": biome["tileCode"],
        "materialDonorName": biome["donor"],
        "materialDonorTileCode": donor["tile"],
        "soundDonorTileCode": sound_donor["tile"],
        "materialAliasOnly": bool(biome.get("materialAliasOnly", False)),
        "textureAssetDir": texture_dir,
        "markerBiomeName": biome["donor"],
        "markerTileCode": donor["tile"],
        "markerTextureAssetDir": biome.get("markerDir"),
        "textureFiles": files,
    }
    for key in (
        "texturesCount",
        "mode",
        "blendDepth",
        "tiling0",
        "heightmapScale0",
        "tiling1",
        "heightmapScale1",
        "tiling2",
        "heightmapScale2",
    ):
        if key in biome:
            row[key] = biome[key]
    return row


def build_assets() -> dict[str, object]:
    ensure_canonical_previews()
    definition_rows = []
    report = []
    for biome in BIOMES:
        donor = DONORS[biome["donor"]]
        sound_donor = DONORS[biome["soundDonor"]]
        texture_dir = biome.get("textureDir") or f"homm3_runtime_assets/custom_biomes/{biome['id']}"
        files = biome.get("files") or donor["files"]
        prebuild_script = biome.get("prebuildScript")
        if prebuild_script:
            subprocess.check_call([sys.executable, str(prebuild_script)], cwd=str(ROOT))
            out_dir = PLUGIN_ROOT / texture_dir
            missing = [name for name in files if not (out_dir / name).exists()]
            if missing:
                raise FileNotFoundError(f"{biome['id']} prebuild did not emit expected texture(s): {missing}")
            report_path = out_dir / f"{biome['id']}_terrain_report.json"
            if not report_path.exists():
                raise FileNotFoundError(report_path)
            rows = json.loads(report_path.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                raise ValueError(f"{report_path} must contain a list")
            report.extend(rows)
            definition_rows.append(definition_row(biome, donor, sound_donor, texture_dir, files))
            continue
        canonical_name = CANONICAL_RANGE49_68_BY_BIOME.get(biome["id"])
        if canonical_name:
            src = CANONICAL_PREVIEW_ROOT / canonical_name
            if not src.exists():
                raise FileNotFoundError(src)
            rows = []
            out_dir = PLUGIN_ROOT / texture_dir
            for name in files:
                dst = out_dir / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                rows.append({"source": str(src), "output": str(dst), "variant": "canonical_range49_68", "changedPixels": 0})
            (out_dir / f"{biome['id']}_terrain_report.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
            report.extend(rows)
            definition_rows.append(definition_row(biome, donor, sound_donor, texture_dir, files))
            continue
        if "variant" in biome:
            rows = []
            out_dir = PLUGIN_ROOT / texture_dir
            for name in files:
                source = SOURCE_DIR / name
                if not source.exists():
                    raise FileNotFoundError(source)
                rows.append(build_texture(source, out_dir / name, biome["variant"]))
            (out_dir / f"{biome['id']}_terrain_report.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
            report.extend(rows)
        definition_rows.append(definition_row(biome, donor, sound_donor, texture_dir, files))
    DEFINITION_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFINITION_PATH.write_text(json.dumps({"biomes": definition_rows}, indent=2) + "\n", encoding="utf-8")
    return {"definitionPath": str(DEFINITION_PATH), "definitions": definition_rows, "textures": report}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(build_assets(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
