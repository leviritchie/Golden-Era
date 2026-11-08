"""Stock-native projection of HoMM3 scenery block masks."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import exact_homm3_footprint as exact_fp


SCHEMA = "homm3.vanilla_stock.scenery_footprint.v1"
POLICY = "raw_translation_exact_catalog_else_explicit_stock_1x1_mask_tiling"
H3M_MASK_WIDTH = 8
H3M_MASK_HEIGHT = 6
H3M_MASK_ANCHOR_X = 7
H3M_MASK_ANCHOR_Y = 5


class VanillaStockSceneryFootprintError(ValueError):
    """Raised when stock scenery cannot reproduce the source blocked cells."""


def load_stock_object_configs(core: Path) -> dict[str, dict[str, Any]]:
    configs: dict[str, dict[str, Any]] = {}
    try:
        with zipfile.ZipFile(core) as archive:
            for member in archive.namelist():
                normalized = member.replace("\\", "/")
                if not normalized.startswith("DB/map/objects/") or not normalized.endswith(".json"):
                    continue
                payload = json.loads(archive.read(member).decode("utf-8-sig"))
                rows = payload.get("array") if isinstance(payload, dict) else None
                if not isinstance(rows, list):
                    raise VanillaStockSceneryFootprintError(
                        f"stock ObjectConfig member has no array: {member}"
                    )
                for row in rows:
                    if isinstance(row, dict) and isinstance(row.get("id"), str):
                        configs[row["id"]] = row
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as ex:
        raise VanillaStockSceneryFootprintError(f"cannot load stock ObjectConfigs from {core}: {ex}") from ex
    if not configs:
        raise VanillaStockSceneryFootprintError(f"stock Core has no ObjectConfigs: {core}")
    return configs


def source_block_offsets(mask: Any) -> set[tuple[int, int]]:
    if not isinstance(mask, list) or len(mask) != H3M_MASK_HEIGHT:
        raise VanillaStockSceneryFootprintError(f"scenery block mask must contain 6 bytes: {mask!r}")
    offsets: set[tuple[int, int]] = set()
    for row_index, raw in enumerate(mask):
        if not isinstance(raw, int) or not 0 <= raw <= 255:
            raise VanillaStockSceneryFootprintError(f"invalid H3M scenery block-mask byte: {raw!r}")
        for col_index in range(H3M_MASK_WIDTH):
            if (raw >> col_index) & 1 == 0:
                offsets.add((col_index - H3M_MASK_ANCHOR_X, row_index - H3M_MASK_ANCHOR_Y))
    return offsets


def _size(config: dict[str, Any]) -> tuple[int, int]:
    size_x = config.get("sizeX")
    size_z = config.get("sizeZ")
    nodes = config.get("nodes")
    if not isinstance(size_x, int) or not isinstance(size_z, int) or size_x <= 0 or size_z <= 0:
        raise VanillaStockSceneryFootprintError(f"ObjectConfig {config.get('id')!r} has no valid size")
    if not isinstance(nodes, list) or len(nodes) != size_x * size_z:
        raise VanillaStockSceneryFootprintError(f"ObjectConfig {config.get('id')!r} has no valid nodes grid")
    return size_x, size_z


def is_one_cell_blocker(config: dict[str, Any]) -> bool:
    try:
        return _size(config) == (1, 1) and config.get("nodes") == [1]
    except VanillaStockSceneryFootprintError:
        return False


def occupied_nodes_for_instance(
    config: dict[str, Any], *, anchor_node: int, rotation: int, width: int, height: int
) -> set[int]:
    if rotation != 0:
        raise VanillaStockSceneryFootprintError(f"scenery footprint validator only accepts rotation 0, got {rotation}")
    if not exact_fp.occupied_br_offsets_from_config(config):
        return set()
    size_x, size_z = _size(config)
    anchor_x, anchor_y = anchor_node % width, anchor_node // width
    occupied: set[int] = set()
    for config_z in range(size_z):
        for config_x in range(size_x):
            if config["nodes"][config_z * size_x + config_x] != 1:
                continue
            x = anchor_x + config_x
            y = anchor_y + (size_z - 1 - config_z)
            if not 0 <= x < width or not 0 <= y < height:
                raise VanillaStockSceneryFootprintError(
                    f"ObjectConfig {config.get('id')!r} footprint exits map at {x},{y}"
                )
            occupied.add(y * width + x)
    return occupied


def plan_stock_scenery(
    *, record: dict[str, Any], preferred_sid: str, footprint_fill_sid: str | None,
    footprint_pathable_sid: str | None,
    configs: dict[str, dict[str, Any]], source_width: int, source_height: int,
) -> dict[str, Any]:
    source_x, source_y = int(record["x"]), int(record["y"])
    offsets = source_block_offsets(record.get("templateBlockMask"))
    expected_count = record.get("expectedSourceBlockCount")
    if expected_count is not None and int(expected_count) != len(offsets):
        raise VanillaStockSceneryFootprintError(
            f"{record.get('key')} sourceBlockCount {expected_count} != decoded mask {len(offsets)}"
        )
    in_bounds = {
        (dx, dy) for dx, dy in offsets
        if 0 <= source_x + dx < source_width and 0 <= source_y + dy < source_height
    }
    clipped = len(offsets) - len(in_bounds)
    preferred = configs.get(preferred_sid)
    if preferred is None:
        raise VanillaStockSceneryFootprintError(f"missing preferred stock ObjectConfig {preferred_sid!r}")

    if not offsets:
        pathable = configs.get(str(footprint_pathable_sid)) if footprint_pathable_sid else None
        if pathable is None or exact_fp.occupied_br_offsets_from_config(pathable):
            raise VanillaStockSceneryFootprintError(
                f"{record.get('key')} requires an explicit stock pathable scenery SID, got {footprint_pathable_sid!r}"
            )
        return {
            "mode": "stock_pathable_decoration",
            "sourceBlockOffsets": [],
            "sourceBlockCount": 0,
            "clippedSourceBlockCount": 0,
            "placements": [
                {"sid": str(footprint_pathable_sid), "sourceX": source_x, "sourceY": source_y}
            ],
        }

    match = exact_fp.find_catalog_scenery_match(
        block_offsets=offsets, configs=configs, preferred_donor=preferred_sid
    )
    if match is not None and clipped == 0:
        config = configs[match]
        size_x, _ = _size(config)
        anchor_x = source_x - (size_x - 1)
        if 0 <= anchor_x < source_width:
            return {
                "mode": "catalog_exact",
                "sourceBlockOffsets": [list(v) for v in sorted(offsets)],
                "sourceBlockCount": len(offsets),
                "clippedSourceBlockCount": 0,
                "placements": [{"sid": match, "sourceX": anchor_x, "sourceY": source_y}],
            }

    if not in_bounds:
        raise VanillaStockSceneryFootprintError(f"{record.get('key')} scenery has no in-bounds blocked cells")
    fill_sid = preferred_sid if is_one_cell_blocker(preferred) else footprint_fill_sid
    fill = configs.get(str(fill_sid)) if fill_sid else None
    if fill is None or not is_one_cell_blocker(fill):
        raise VanillaStockSceneryFootprintError(
            f"{record.get('key')} requires an explicit stock 1x1 blocker, got {fill_sid!r}"
        )
    ordered = sorted(in_bounds, key=lambda value: (value != (0, 0), value[1], value[0]))
    return {
        "mode": "stock_1x1_tiled",
        "sourceBlockOffsets": [list(v) for v in sorted(offsets)],
        "sourceBlockCount": len(offsets),
        "clippedSourceBlockCount": clipped,
        "placements": [
            {"sid": str(fill_sid), "sourceX": source_x + dx, "sourceY": source_y + dy}
            for dx, dy in ordered
        ],
    }
