"""Campaign ocean representation: the single raw_translation path.

HoMM3 ocean is emitted the way native Olden Era maps store sea: a depressed basin
(``levelsMap == -1``) that carries a ``waterMap`` water body. Native maps such as
Glittering_Strait and Broken_Alliance do this on ordinary land tiles. Campaign
ocean uses:

- seabed tile: native Sand (``DB/map/tiles`` id 2, biome ``Sand``);
- water body: native ``water sand`` (``DB/map/waters`` id 2, material ``water_2``);
- basin: ``levelsMap = -1``, with perimeter ramp climbs from
  ``h3m_scenario_translation.NATIVE_OCEAN_BASIN_*``.

Tile id 2 and water id 2 carry those rows in the Golden Era Core and in Steam
25509697. ``core_ocean_table_errors`` reads them from a Core's own tables.

The Golden Era-only ocean ids are retired: tile ids 18-22 (``Water`` and
``Water Shore North/South/West/East``) and waterMap id 18 (``water water``). A
campaign map that still carries any of them is a failed check. There is no
second path and no fallback.

Ocean identity is the triple (tile 2, waterMap 2, levelsMap -1), the native
rule that deep water is water in a depressed basin:
- the canon scenery pass paints land Sand as tile 2 with waterMap 0;
- it also rewrites a river channel on Sand to tile 2 + waterMap 2 ("water sand"
  river) at its land level (0 or above).
So neither the tile nor the (tile, water) pair alone is the ocean once a map is
written. Inside the emitter, before the canon pass, rivers carry only water ids
1, 4, 7 and 15, so ``is_emitter_ocean_pair`` is exact there and only there.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

OCEAN_TILE_CODE = 2
OCEAN_TILE_BIOME = "Sand"
OCEAN_WATER_MAP_ID = 2
OCEAN_WATER_MAP_NAME = "water sand"
OCEAN_BASIN_LEVEL = -1
OCEAN_POLICY = "h3_ocean_to_native_sand_tile_2_water_sand_2_basin_level_minus_one"

RETIRED_GE_WATER_TILE_CODES: frozenset[int] = frozenset({18, 19, 20, 21, 22})
RETIRED_GE_OCEAN_WATER_MAP_ID = 18

CORE_TILES_MEMBER = "DB/map/tiles/tiles.json"
CORE_WATERS_MEMBER = "DB/map/waters/waters.json"


def is_emitter_ocean_pair(tile: Any, water: Any) -> bool:
    """Ocean test inside the emitter, before the canon scenery pass writes Sand river channels."""
    return int(tile) == OCEAN_TILE_CODE and int(water or 0) == OCEAN_WATER_MAP_ID


def is_ocean_cell(tile: Any, water: Any, level: Any) -> bool:
    """True for a written campaign ocean cell: seabed tile + ocean water body in the basin."""
    return is_emitter_ocean_pair(tile, water) and int(level) == OCEAN_BASIN_LEVEL


def ocean_cell_count(map_data: Mapping[str, Any]) -> int:
    tiles = map_data.get("tilesMap") or []
    water = map_data.get("waterMap") or []
    levels = map_data.get("levelsMap") or []
    return sum(1 for tile, wm, level in zip(tiles, water, levels) if is_ocean_cell(tile, wm, level))


def map_ocean_errors(map_data: Mapping[str, Any], *, label: str = "map") -> list[str]:
    """Fail-closed audit of one map's MapData chunk against the ocean contract."""
    errors: list[str] = []
    tiles = map_data.get("tilesMap")
    water = map_data.get("waterMap")
    levels = map_data.get("levelsMap")
    if not isinstance(tiles, list) or not isinstance(water, list) or not isinstance(levels, list):
        return [f"{label}: MapData must carry list tilesMap/waterMap/levelsMap"]
    if not (len(tiles) == len(water) == len(levels)):
        return [
            f"{label}: tilesMap/waterMap/levelsMap lengths differ "
            f"({len(tiles)}/{len(water)}/{len(levels)})"
        ]
    retired_tiles: list[int] = []
    retired_water: list[int] = []
    off_seabed: list[int] = []
    off_basin: list[int] = []
    for node, (tile, wm, level) in enumerate(zip(tiles, water, levels)):
        tile = int(tile)
        wm = int(wm or 0)
        if tile in RETIRED_GE_WATER_TILE_CODES:
            retired_tiles.append(node)
        if wm == RETIRED_GE_OCEAN_WATER_MAP_ID:
            retired_water.append(node)
        if wm == OCEAN_WATER_MAP_ID and tile != OCEAN_TILE_CODE:
            off_seabed.append(node)
        if wm != 0 and int(level) == OCEAN_BASIN_LEVEL and not is_emitter_ocean_pair(tile, wm):
            off_basin.append(node)
    if retired_tiles:
        errors.append(
            f"{label}: {len(retired_tiles)} cell(s) emit retired Golden Era water tile ids "
            f"{sorted(RETIRED_GE_WATER_TILE_CODES)} (first nodes {retired_tiles[:8]})"
        )
    if retired_water:
        errors.append(
            f"{label}: {len(retired_water)} cell(s) emit retired Golden Era ocean waterMap id "
            f"{RETIRED_GE_OCEAN_WATER_MAP_ID} (first nodes {retired_water[:8]})"
        )
    if off_seabed:
        errors.append(
            f"{label}: {len(off_seabed)} waterMap {OCEAN_WATER_MAP_ID} cell(s) are not on Sand "
            f"tile {OCEAN_TILE_CODE} (first nodes {off_seabed[:8]})"
        )
    if off_basin:
        errors.append(
            f"{label}: {len(off_basin)} water cell(s) at basin level {OCEAN_BASIN_LEVEL} are not the "
            f"ocean (tile {OCEAN_TILE_CODE}, water {OCEAN_WATER_MAP_ID}) (first nodes {off_basin[:8]})"
        )
    return errors


def _rows(doc: Any) -> list[dict[str, Any]]:
    if isinstance(doc, dict):
        doc = doc.get("array")
    if not isinstance(doc, list):
        return []
    return [row for row in doc if isinstance(row, dict)]


def read_core_ocean_tables_from_archive(
    archive: zipfile.ZipFile,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tiles = json.loads(archive.read(CORE_TILES_MEMBER).decode("utf-8-sig"))
    waters = json.loads(archive.read(CORE_WATERS_MEMBER).decode("utf-8-sig"))
    return _rows(tiles), _rows(waters)


def read_core_ocean_tables(core_zip: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with zipfile.ZipFile(core_zip) as archive:
        return read_core_ocean_tables_from_archive(archive)


def core_ocean_table_errors(
    tile_rows: Sequence[Mapping[str, Any]],
    water_rows: Sequence[Mapping[str, Any]],
    *,
    label: str = "Core",
) -> list[str]:
    """The Core's own tables must resolve the ocean seabed tile and water body ids."""
    errors: list[str] = []
    tiles = {row.get("id"): row for row in tile_rows}
    waters = {row.get("id"): row for row in water_rows}
    tile = tiles.get(OCEAN_TILE_CODE)
    if tile is None:
        errors.append(f"{label}: {CORE_TILES_MEMBER} has no ocean seabed tile id {OCEAN_TILE_CODE}")
    elif tile.get("biome") != OCEAN_TILE_BIOME:
        errors.append(
            f"{label}: tile id {OCEAN_TILE_CODE} biome is {tile.get('biome')!r}, expected {OCEAN_TILE_BIOME!r}"
        )
    water = waters.get(OCEAN_WATER_MAP_ID)
    if water is None:
        errors.append(f"{label}: {CORE_WATERS_MEMBER} has no ocean water id {OCEAN_WATER_MAP_ID}")
    elif water.get("name") != OCEAN_WATER_MAP_NAME:
        errors.append(
            f"{label}: water id {OCEAN_WATER_MAP_ID} name is {water.get('name')!r}, expected {OCEAN_WATER_MAP_NAME!r}"
        )
    return errors


def core_zip_ocean_errors(core_zip: Path, *, label: str | None = None) -> list[str]:
    tiles, waters = read_core_ocean_tables(core_zip)
    return core_ocean_table_errors(tiles, waters, label=label or str(core_zip))


def core_archive_ocean_errors(
    archive: zipfile.ZipFile, *, label: str = "Core"
) -> list[str]:
    tiles, waters = read_core_ocean_tables_from_archive(archive)
    return core_ocean_table_errors(tiles, waters, label=label)


def describe() -> dict[str, Any]:
    return {
        "policy": OCEAN_POLICY,
        "seabedTileId": OCEAN_TILE_CODE,
        "seabedTileBiome": OCEAN_TILE_BIOME,
        "waterMapId": OCEAN_WATER_MAP_ID,
        "waterMapName": OCEAN_WATER_MAP_NAME,
        "basinLevel": OCEAN_BASIN_LEVEL,
        "identity": "tile == seabedTileId and waterMap == waterMapId and levelsMap == basinLevel",
        "retiredGoldenEraWaterTileIds": sorted(RETIRED_GE_WATER_TILE_CODES),
        "retiredGoldenEraOceanWaterMapId": RETIRED_GE_OCEAN_WATER_MAP_ID,
    }
