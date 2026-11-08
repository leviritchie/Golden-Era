#!/usr/bin/env python3
"""Prebake HoMM3 town layer coordinates into the runtime reference canvas.

The source town placements remain native VCMI/HoMM3 top-left coordinates.
Runtime rendering consumes the prebaked reference rect fields so the C# side
does not rederive faction-specific coordinate math during town entry.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
TOWN_SCENE_ROOT = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_runtime_assets" / "town_scene_refs"

SOURCE_W = 800
SOURCE_H = 600
REFERENCE_W = 1920
REFERENCE_H = 1080
UNIFORM_SCALE = REFERENCE_H / SOURCE_H
REFERENCE_PLATE_W = round(SOURCE_W * UNIFORM_SCALE)
REFERENCE_PLATE_H = REFERENCE_H
REFERENCE_PLATE_X = 0
REFERENCE_PLATE_Y = 0
X_SCALE = UNIFORM_SCALE
Y_SCALE = UNIFORM_SCALE
BACKGROUND_SUFFIX = "-in-background.png"


def rounded(value: float) -> int | float:
    rounded_value = round(value, 3)
    if float(rounded_value).is_integer():
        return int(rounded_value)
    return rounded_value


def prebake_positions_file(path: Path) -> bool:
    layers_dir = path.parent
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    changed = False

    expected_basis = {
        "source": "vcmi-top-left-800x374-on-black-800x600-town-plate-uniform-scale-left-aligned",
        "referenceCanvas": {"w": REFERENCE_W, "h": REFERENCE_H},
        "referencePlate": {"x": REFERENCE_PLATE_X, "y": REFERENCE_PLATE_Y, "w": REFERENCE_PLATE_W, "h": REFERENCE_PLATE_H},
        "sourceCanvas": {"w": SOURCE_W, "h": SOURCE_H},
        "uniformScale": UNIFORM_SCALE,
        "xScale": X_SCALE,
        "yScale": Y_SCALE,
    }
    if data.get("coordinateBasis") != expected_basis:
        data["coordinateBasis"] = expected_basis
        changed = True

    for row in data.get("layers", []):
        if not isinstance(row, dict):
            continue
        sprite = row.get("sprite")
        if not isinstance(sprite, str) or not sprite.strip():
            raise ValueError(f"{path}: layer {row.get('id')} is missing explicit sprite metadata")
        image_path = layers_dir / sprite
        if not image_path.is_file():
            raise FileNotFoundError(f"{path}: missing layer sprite {sprite}")
        with Image.open(image_path) as image:
            width, height = image.size
        x = int(row.get("x", 0))
        y = int(row.get("y", 0))
        baked = {
            "reference_x": rounded(x * X_SCALE),
            "reference_y": rounded(y * Y_SCALE),
            "reference_w": rounded(width * X_SCALE),
            "reference_h": rounded(height * Y_SCALE),
        }
        for key, value in baked.items():
            if row.get(key) != value:
                row[key] = value
                changed = True

    mockup_changed = prebake_mockup_for_positions_file(path)
    if changed:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return changed or mockup_changed


def prebake_mockup(source_path: Path, out_path: Path) -> bool:
    with Image.open(source_path) as source_image:
        source = source_image.convert("RGBA")
    if source.size == (SOURCE_W, SOURCE_H):
        plate = source
    elif source.width == SOURCE_W and source.height <= SOURCE_H:
        plate = Image.new("RGBA", (SOURCE_W, SOURCE_H), (0, 0, 0, 255))
        plate.alpha_composite(source, (0, 0))
    else:
        raise RuntimeError(f"{source_path}: expected {SOURCE_W}x{SOURCE_H} or {SOURCE_W}x<= {SOURCE_H}, got {source.size}")

    mockup = Image.new("RGBA", (REFERENCE_W, REFERENCE_H), (0, 0, 0, 255))
    scaled_plate = plate.resize((REFERENCE_PLATE_W, REFERENCE_PLATE_H), Image.Resampling.LANCZOS)
    mockup.alpha_composite(scaled_plate, (REFERENCE_PLATE_X, REFERENCE_PLATE_Y))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    mockup.save(tmp_path, format="PNG", optimize=True)
    changed = not out_path.exists() or out_path.read_bytes() != tmp_path.read_bytes()
    if changed:
        tmp_path.replace(out_path)
    else:
        tmp_path.unlink()
    return changed


def prebake_mockup_for_positions_file(path: Path) -> bool:
    faction_dir = path.parent.parent
    source_candidates = sorted(
        p
        for p in faction_dir.glob(f"*{BACKGROUND_SUFFIX}")
        if p.parent == faction_dir
    )
    if len(source_candidates) != 1:
        raise RuntimeError(f"{faction_dir}: expected exactly one *{BACKGROUND_SUFFIX} source, found {len(source_candidates)}")
    source_path = source_candidates[0]
    sid = faction_dir.name
    out_path = faction_dir / "mockups" / f"{sid}_background_mock_{REFERENCE_W}x{REFERENCE_H}.png"
    return prebake_mockup(source_path, out_path)


def iter_position_files(faction: str | None) -> list[Path]:
    if faction:
        return [TOWN_SCENE_ROOT / faction / "layers" / "positions.json"]
    return sorted(TOWN_SCENE_ROOT.glob("homm3_*/layers/positions.json"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--faction", help="Optional homm3_* faction folder to update.")
    args = parser.parse_args()

    changed = 0
    for path in iter_position_files(args.faction):
        if not path.is_file():
            raise FileNotFoundError(path)
        if prebake_positions_file(path):
            changed += 1
            print(f"updated {path.relative_to(ROOT)}")
        else:
            print(f"unchanged {path.relative_to(ROOT)}")
    print(f"prebaked town scene files changed: {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
