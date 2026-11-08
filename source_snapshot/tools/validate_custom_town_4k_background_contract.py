#!/usr/bin/env python3
"""Fail-closed contract for owned custom-town 4K outpainted backgrounds."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

FACTIONS = [
    "bulwark",
    "castle",
    "conflux",
    "cove",
    "dungeon",
    "factory",
    "fortress",
    "inferno",
    "necropolis",
    "rampart",
    "stronghold",
    "tower",
]
EXPECTED_CANVAS = {"w": 3840, "h": 2160}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.repo_root.resolve()
    plugin = root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
    town_refs = plugin / "homm3_runtime_assets" / "town_scene_refs"
    finals = root / "artifacts" / "custom_town_4k_finals"
    errors: list[str] = []

    visuals = plugin / "Homm3FactoryCityWorldVisuals.cs"
    source = visuals.read_text(encoding="utf-8") if visuals.is_file() else ""
    for token in (
        "UpscaledBackgroundFileSuffix",
        "Exists(upscaledPath)",
        "_background_upscaled_3840x2160.png",
    ):
        if token not in source:
            errors.append(f"compositor missing prefer-upscaled token {token!r}")

    for faction in FACTIONS:
        name = f"homm3_{faction}_background_upscaled_3840x2160.png"
        live = town_refs / f"homm3_{faction}" / "mockups" / name
        final = finals / name
        positions = town_refs / f"homm3_{faction}" / "layers" / "positions.json"
        for path in (live, final):
            if not path.is_file():
                errors.append(f"missing {path.relative_to(root).as_posix()}")
                continue
            try:
                with Image.open(path) as image:
                    if image.size != (3840, 2160):
                        errors.append(f"{path.name} size drifted: {image.size}")
                    if image.mode != "RGBA":
                        errors.append(f"{path.name} is not RGBA: {image.mode}")
            except Exception as exc:
                errors.append(f"cannot read {path}: {exc}")
        if not positions.is_file():
            errors.append(f"missing positions for {faction}")
            continue
        basis = (json.loads(positions.read_text(encoding="utf-8")).get("coordinateBasis") or {})
        if basis.get("referenceCanvas") != EXPECTED_CANVAS:
            errors.append(f"{faction} referenceCanvas drifted: {basis.get('referenceCanvas')}")
        if basis.get("uniformScale") != 3.6:
            errors.append(f"{faction} uniformScale expected 3.6, got {basis.get('uniformScale')!r}")

    if errors:
        print("FAIL: " + "; ".join(errors))
        return 1
    print(f"OK: custom town 4K background contract ({len(FACTIONS)} factions).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
