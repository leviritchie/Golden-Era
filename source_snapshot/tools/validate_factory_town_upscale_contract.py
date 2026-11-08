#!/usr/bin/env python3
"""Fail-closed contract for the Factory 4K town-scene upscale lane."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


BACKGROUND_NAME = "homm3_factory_background_upscaled_3840x2160.png"
EXPECTED_CANVAS = {"w": 3840, "h": 2160}
EXPECTED_LAYOUT = "factory_4k_outpaint_v1"
MAX_STATIC_SIDE = 1024


def resolve_paths(repo_root: Path, plugin_root: Path | None) -> tuple[Path, Path, Path]:
    root = plugin_root or (
        repo_root
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
    )
    town = root / "homm3_runtime_assets" / "town_scene_refs" / "homm3_factory"
    return (
        root,
        town / "layers",
        town / "mockups" / BACKGROUND_NAME,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--plugin-root", type=Path)
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    _, layers, background = resolve_paths(repo_root, args.plugin_root.resolve() if args.plugin_root else None)
    errors: list[str] = []

    world_visuals = (
        repo_root
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "Homm3FactoryCityWorldVisuals.cs"
    )
    if not world_visuals.is_file():
        errors.append(f"missing world compositor source: {world_visuals}")
    else:
        source = world_visuals.read_text(encoding="utf-8")
        for token in (
            "_background_upscaled_3840x2160.png",
            "UpscaledBackgroundFileSuffix",
            "factory4k-v10",
            "referenceCanvas",
            "ResolveBackdropMockRelativePath",
            "Exists(upscaledPath)",
        ):
            if token not in source:
                errors.append(f"Factory compositor is missing upscale token {token!r}")

    positions_path = layers / "positions.json"
    metadata_path = layers / "anims" / "metadata.json"
    layer_map_path = layers / "building_layer_map.json"
    for required in (positions_path, metadata_path, layer_map_path):
        if not required.is_file():
            errors.append(f"missing Factory scene contract file: {required}")
    if errors:
        print("FAIL: " + "; ".join(errors))
        return 1

    positions = json.loads(positions_path.read_text(encoding="utf-8"))
    basis = positions.get("coordinateBasis") or {}
    if basis.get("referenceCanvas") != EXPECTED_CANVAS:
        errors.append(f"Factory reference canvas drifted: {basis.get('referenceCanvas')}")
    if basis.get("runtimeLayout") != EXPECTED_LAYOUT:
        errors.append(f"Factory runtime layout drifted: {basis.get('runtimeLayout')!r}")
    if basis.get("uniformScale") != 3.6:
        errors.append(f"Factory uniformScale expected 3.6, got {basis.get('uniformScale')!r}")

    rows = positions.get("layers") or []
    by_id = {str(row.get("id")): row for row in rows}
    animated = {
        str(row["id"])
        for row in json.loads(metadata_path.read_text(encoding="utf-8"))
        if row.get("id")
    }
    mapped = {
        str(layer_id)
        for levels in (json.loads(layer_map_path.read_text(encoding="utf-8")).get("nativeLevels") or {}).values()
        for layer_id in (levels or {}).values()
    }
    if len(rows) != 41:
        errors.append(f"Factory positions expected 41 source rows, got {len(rows)}")
    if len(animated) != 11:
        errors.append(f"Factory animation metadata expected 11 IDs, got {len(animated)}")

    missing_mapped = sorted(mapped - set(by_id))
    for layer_id in missing_mapped:
        errors.append(f"mapped Factory layer missing from positions: {layer_id}")

    static_ids = set(by_id) - animated
    for layer_id in sorted(static_ids):
        row = by_id.get(layer_id)
        if row is None:
            errors.append(f"Factory source layer missing from positions: {layer_id}")
            continue
        for key in ("reference_x", "reference_y"):
            if not isinstance(row.get(key), (int, float)) or row[key] < 0:
                errors.append(f"Factory layer {layer_id} has invalid {key}")
        for key in ("reference_w", "reference_h"):
            if not isinstance(row.get(key), (int, float)) or row[key] <= 0:
                errors.append(f"Factory layer {layer_id} has invalid {key}")
        png = layers / f"{layer_id}.png"
        if not png.is_file():
            errors.append(f"Factory source layer missing PNG: {png}")
            continue
        try:
            with Image.open(png) as image:
                if layer_id in animated:
                    # Animation bases intentionally stay on the old source lane.
                    continue
                if max(image.size) > MAX_STATIC_SIDE:
                    errors.append(
                        f"static Factory layer {layer_id} exceeds {MAX_STATIC_SIDE}px: {image.size}"
                    )
                if max(image.size) < 512:
                    errors.append(
                        f"static Factory layer {layer_id} is still source-sized: {image.size}"
                    )
                if image.mode != "RGBA":
                    errors.append(f"static Factory layer {layer_id} is not RGBA: {image.mode}")
                if image.getchannel("A").getbbox() is None:
                    errors.append(f"static Factory layer {layer_id} is fully transparent")
        except Exception as exc:
            errors.append(f"cannot read Factory layer {png}: {exc}")

    if not background.is_file():
        errors.append(f"missing Factory 4K background: {background}")
    else:
        try:
            with Image.open(background) as image:
                if image.size != (3840, 2160):
                    errors.append(f"Factory background size drifted: {image.size}")
                if image.mode != "RGBA":
                    errors.append(f"Factory background is not RGBA: {image.mode}")
                corners = [
                    image.getpixel((0, 0)),
                    image.getpixel((image.width - 1, 0)),
                    image.getpixel((0, image.height - 1)),
                    image.getpixel((image.width - 1, image.height - 1)),
                ]
                if any(sum(pixel[:3]) == 0 for pixel in corners):
                    errors.append(f"Factory background has black corner(s): {corners}")
        except Exception as exc:
            errors.append(f"cannot read Factory background {background}: {exc}")

    if errors:
        print("FAIL: " + "; ".join(errors))
        return 1
    print(
        "OK: Factory 4K town upscale contract "
        f"(static layers={len(static_ids)}, mapped static layers={len(mapped - animated)}, "
        f"animation IDs excluded={len(animated)}, "
        "background=3840x2160)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
