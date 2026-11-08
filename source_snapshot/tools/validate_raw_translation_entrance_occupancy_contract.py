#!/usr/bin/env python3
"""Static contract for the raw_translation entrance occupancy / H3-floor pass.

Fail-closed checks:
- pass module exists and declares the coastline-safe policy
- raw builder imports and calls it after visual scenery, before placement GT
- pass does not touch ocean / shoreline / waterMap / climbs
- focused unit tests pass
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PASS = (
    ROOT
    / "experiments"
    / "campaign_port_poc"
    / "raw_translation"
    / "entrance_occupancy.py"
)
BUILDER = (
    ROOT
    / "experiments"
    / "campaign_port_poc"
    / "raw_translation"
    / "build_raw_translation_map.py"
)
TESTS = (
    ROOT
    / "experiments"
    / "campaign_port_poc"
    / "raw_translation"
    / "test_entrance_occupancy.py"
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
COASTLINE_HELPERS = (
    "apply_native_ocean_basin_geometry",
    "build_ocean_shoreline_rivers",
    "H3_SURFACE_RIVER_TO_OLDEN_WATER",
    "project_ocean_tile_code",
)


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    errors: list[str] = []

    require(PASS.is_file(), f"missing entrance occupancy module: {PASS}", errors)
    require(BUILDER.is_file(), f"missing raw builder: {BUILDER}", errors)
    require(TESTS.is_file(), f"missing entrance occupancy tests: {TESTS}", errors)
    if errors:
        print("FAIL entrance occupancy contract:")
        for row in errors:
            print(f"  - {row}")
        return 1

    pass_src = PASS.read_text(encoding="utf-8")
    builder_src = BUILDER.read_text(encoding="utf-8")
    surface_src = SURFACE_EMIT.read_text(encoding="utf-8") if SURFACE_EMIT.is_file() else ""
    layer_src = LAYER_ATLAS.read_text(encoding="utf-8") if LAYER_ATLAS.is_file() else ""

    require(
        'SCHEMA = "homm3.raw_translation.entrance_occupancy.v1"' in pass_src,
        "pass must declare schema homm3.raw_translation.entrance_occupancy.v1",
        errors,
    )
    require(
        "do_not_mutate_waterMap_levelsMap_climbsMap_or_ocean_geometry" in pass_src,
        "pass policy must refuse coastline / waterMap / climbs mutation",
        errors,
    )
    require(
        "apply_raw_translation_accessibility_pass" in pass_src,
        "pass must expose apply_raw_translation_accessibility_pass",
        errors,
    )
    require(
        "build_h3_ground_truth_walkable_nodes" in pass_src,
        "pass must build H3 ground-truth walkable nodes from source terrain + block masks",
        errors,
    )
    require(
        "H3_WATER_TERRAIN_ID = 8" in pass_src,
        "pass must treat H3 terrain 8 as non-walkable water",
        errors,
    )
    require(
        "entity_nonvisitable_block_offsets" in pass_src,
        "H3 floor must use non-visitable block offsets (visit cells stay walkable)",
        errors,
    )
    for token in COASTLINE_HELPERS:
        require(
            token not in pass_src,
            f"entrance_occupancy.py must not contain coastline helper {token!r}",
            errors,
        )

    require(
        "import entrance_occupancy" in builder_src,
        "raw builder must import entrance_occupancy",
        errors,
    )
    require(
        "apply_raw_translation_accessibility_pass" in builder_src,
        "raw builder must call apply_raw_translation_accessibility_pass",
        errors,
    )
    require(
        '"entranceOccupancy"' in builder_src,
        "raw builder must record postPasses.entranceOccupancy",
        errors,
    )
    visual_at = builder_src.find("apply_visual_scenery_canon_postpass")
    access_at = builder_src.find("apply_raw_translation_accessibility_pass")
    gt_at = builder_src.find("build_placement_ground_truth")
    require(visual_at != -1, "builder must still call visual scenery postpass", errors)
    require(access_at != -1, "builder must call entrance occupancy pass", errors)
    require(gt_at != -1, "builder must still build placement ground truth", errors)
    require(
        visual_at < access_at < gt_at,
        "entrance occupancy must run after visual scenery postpass and before placement GT",
        errors,
    )

    require(
        "entrance_occupancy" not in surface_src,
        "surface_emit.py must not absorb the entrance occupancy pass",
        errors,
    )
    require(
        "entrance_occupancy" not in layer_src,
        "layer_atlas.py must not absorb the entrance occupancy pass",
        errors,
    )
    require(
        "H3_SURFACE_TO_OLDEN_TILE" in surface_src,
        "surface_emit must keep H3_SURFACE_TO_OLDEN_TILE (this pass does not remap terrain)",
        errors,
    )

    if TESTS.is_file():
        result = subprocess.run(
            [sys.executable, str(TESTS)],
            cwd=str(ROOT),
            check=False,
            capture_output=True,
            text=True,
        )
        require(
            result.returncode == 0,
            "entrance occupancy unit tests failed:\n"
            + (result.stdout or "")
            + (result.stderr or ""),
            errors,
        )

    if errors:
        print("FAIL entrance occupancy contract:")
        for row in errors:
            print(f"  - {row}")
        return 1
    print("OK entrance occupancy contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
