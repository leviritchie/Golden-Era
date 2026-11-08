#!/usr/bin/env python3
"""Static contract for the raw_translation visual scenery / canon terrain postpass.

Fail-closed checks:
- postpass module exists and owns the native-first remap table
- skip flag / env are wired
- merge path requires solid OCC + exclusive prior occupancy (source tokens)
- surface_emit / layer_atlas were not given the remap/merge logic
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTPASS = (
    ROOT
    / "experiments"
    / "campaign_port_poc"
    / "raw_translation"
    / "visual_scenery_canon_postpass.py"
)
BUILDER = (
    ROOT
    / "experiments"
    / "campaign_port_poc"
    / "raw_translation"
    / "build_raw_translation_map.py"
)
SURFACE_EMIT = (
    ROOT
    / "experiments"
    / "campaign_port_poc"
    / "approach_cell"
    / "surface_emit.py"
)
LAYER_ATLAS = (
    ROOT
    / "experiments"
    / "campaign_port_poc"
    / "approach_cell"
    / "layer_atlas.py"
)


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    errors: list[str] = []

    require(POSTPASS.is_file(), f"missing postpass module: {POSTPASS}", errors)
    require(BUILDER.is_file(), f"missing raw builder: {BUILDER}", errors)
    if errors:
        print("FAIL visual scenery canon postpass contract:")
        for row in errors:
            print(f"  - {row}")
        return 1

    postpass_src = POSTPASS.read_text(encoding="utf-8")
    builder_src = BUILDER.read_text(encoding="utf-8")
    surface_src = SURFACE_EMIT.read_text(encoding="utf-8") if SURFACE_EMIT.is_file() else ""
    layer_src = LAYER_ATLAS.read_text(encoding="utf-8") if LAYER_ATLAS.is_file() else ""

    require(
        'SCHEMA = "homm3.raw_translation.visual_scenery_canon_postpass.v1"' in postpass_src,
        "postpass must declare schema homm3.raw_translation.visual_scenery_canon_postpass.v1",
        errors,
    )
    require(
        "RAW_TRANSLATION_SKIP_VISUAL_SCENERY_POSTPASS" in postpass_src,
        "postpass must honor RAW_TRANSLATION_SKIP_VISUAL_SCENERY_POSTPASS",
        errors,
    )
    require(
        "CANON_H3_TO_OLDEN" in postpass_src and "LOSSY_H3_TO_OLDEN" in postpass_src,
        "postpass must define LOSSY_H3_TO_OLDEN and CANON_H3_TO_OLDEN",
        errors,
    )
    # Native-first pins: Sand→2, Swamp→8, Lava→6, Rough→7
    require("1: 2," in postpass_src or "1: 2,   # Sand" in postpass_src, "canon table must map H3 sand→2", errors)
    require(
        "4: 8," in postpass_src or "4: 8,   # Swamp" in postpass_src,
        "canon table must map H3 swamp→8",
        errors,
    )
    require("7: 6," in postpass_src or "7: 6,   # Lava" in postpass_src, "canon table must map H3 lava→6", errors)
    require(
        "5: 7," in postpass_src or "5: 7,   # Rough" in postpass_src,
        "canon table must map H3 rough→7 Dirt",
        errors,
    )
    require(
        "config_fingerprint" in postpass_src and "is_fully_solid_square" in postpass_src,
        "postpass must fingerprint ObjectConfig footprints (not name heuristics alone)",
        errors,
    )
    require(
        "occupied_nodes_for_anchor" in postpass_src,
        "postpass must compute multi-tile OCC from SW-at-anchor placement math",
        errors,
    )
    require(
        "occ != set(cells)" in postpass_src or "occ is None or occ != set(cells)" in postpass_src,
        "mountain merge must require big-SID OCC == pre-covered solid square",
        errors,
    )
    require(
        "write_pre_postpass_backup" in postpass_src and "restore_from_backup" in postpass_src,
        "postpass must provide backup write + restore helpers",
        errors,
    )

    require(
        "import visual_scenery_canon_postpass" in builder_src,
        "raw builder must import the separate visual scenery postpass",
        errors,
    )
    require(
        "apply_visual_scenery_canon_postpass" in builder_src,
        "raw builder must call apply_visual_scenery_canon_postpass",
        errors,
    )
    require(
        "--skip-visual-scenery-postpass" in builder_src,
        "raw builder CLI must expose --skip-visual-scenery-postpass",
        errors,
    )
    require(
        '"visualSceneryCanon"' in builder_src,
        "raw builder must record postPasses.visualSceneryCanon",
        errors,
    )
    require(
        "write_pre_postpass_backup" in builder_src,
        "raw builder must write the pre-postpass .map backup when applied",
        errors,
    )

    # Existing emit modules must not absorb this dangerous remapper.
    forbidden_tokens = (
        "CANON_H3_TO_OLDEN",
        "visual_scenery_canon_postpass",
        "apply_visual_scenery_canon_postpass",
        "RAW_TRANSLATION_SKIP_VISUAL_SCENERY_POSTPASS",
    )
    for token in forbidden_tokens:
        require(
            token not in surface_src,
            f"surface_emit.py must not contain postpass token {token!r}",
            errors,
        )
        require(
            token not in layer_src,
            f"layer_atlas.py must not contain postpass token {token!r}",
            errors,
        )

    # surface_emit must still keep its lossy table (postpass is additive, not a rewrite of emit).
    require(
        "H3_SURFACE_TO_OLDEN_TILE" in surface_src,
        "surface_emit must keep H3_SURFACE_TO_OLDEN_TILE (postpass is separate)",
        errors,
    )

    if errors:
        print("FAIL visual scenery canon postpass contract:")
        for row in errors:
            print(f"  - {row}")
        return 1
    print("OK visual scenery canon postpass contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
