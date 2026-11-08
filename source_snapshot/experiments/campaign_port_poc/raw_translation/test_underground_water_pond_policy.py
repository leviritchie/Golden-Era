#!/usr/bin/env python3
"""Unit tests for underground ocean -> pond scenery projection policy."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
for path in (POC / "raw_translation", POC / "approach_cell", POC):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

import layer_atlas as atlas


def _layer_map(width: int, height: int, water_cells: set[tuple[int, int]]) -> dict:
    count = width * height
    tiles = [6] * count
    water = [0] * count
    for x, y in water_cells:
        tiles[y * width + x] = atlas.H3_OCEAN_WATER_TERRAIN_ID
    return {
        "sizeX_": width,
        "sizeZ_": height,
        "tilesMap": tiles,
        "waterMap": water,
        "roadsMap": [0] * count,
    }


class UndergroundWaterPondPolicyTests(unittest.TestCase):
    def test_preserved_mission_skips_conversion(self) -> None:
        plan = atlas.plan_underground_water_to_pond_scenery(
            _layer_map(8, 8, {(2, 2), (3, 2)}),
            preserve_underground_ocean=True,
        )
        self.assertEqual(plan["status"], "preserved_underground_ocean")
        self.assertEqual(plan["placements"], [])

    def test_connected_components_emit_one_pond_each(self) -> None:
        plan = atlas.plan_underground_water_to_pond_scenery(
            _layer_map(
                10,
                10,
                {
                    (1, 1),
                    (2, 1),
                    (7, 7),
                    (8, 7),
                    (8, 8),
                },
            ),
            preserve_underground_ocean=False,
        )
        self.assertEqual(plan["status"], "converted_to_pond_scenery")
        self.assertEqual(plan["sourceWaterTileCount"], 5)
        self.assertEqual(plan["componentCount"], 2)
        self.assertEqual(len(plan["placements"]), 2)
        self.assertEqual(plan["placements"][0]["sid"], atlas.UNDERGROUND_POND_SCENERY_SMALL_SID)
        self.assertEqual(plan["placements"][1]["sid"], atlas.UNDERGROUND_POND_SCENERY_SMALL_SID)

    def test_large_component_uses_big_pond(self) -> None:
        cells = {(x, 0) for x in range(atlas.UNDERGROUND_POND_SCENERY_BIG_COMPONENT_MIN_TILES)}
        plan = atlas.plan_underground_water_to_pond_scenery(
            _layer_map(32, 4, cells),
            preserve_underground_ocean=False,
        )
        self.assertEqual(plan["componentCount"], 1)
        self.assertEqual(plan["placements"][0]["sid"], atlas.UNDERGROUND_POND_SCENERY_BIG_SID)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
