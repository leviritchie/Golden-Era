#!/usr/bin/env python3
"""Validate the Homecoming tile-object grid diagnostics."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_ROOT = REPO_ROOT / "experiments" / "campaign_port_poc"
sys.path.insert(0, str(CAMPAIGN_ROOT))

import build_homecoming_single_layer_map as single
import build_homecoming_tile_object_grid as grid_builder
import port_homecoming_poc as poc

EXPECTED_SCHEMA = grid_builder.SCHEMA
EXPECTED_DIFF_SCHEMA = grid_builder.DIFF_SCHEMA
EXPECTED_STATUS = grid_builder.STATUS


def read_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"cannot read JSON {path}: {exc}")
        return {}


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_rows_shape(grid: dict[str, Any], label: str, errors: list[str]) -> None:
    require(grid.get("schema") == EXPECTED_SCHEMA, f"{label} schema mismatch: {grid.get('schema')}", errors)
    require(grid.get("status") == EXPECTED_STATUS, f"{label} status mismatch: {grid.get('status')}", errors)
    coordinate = grid.get("coordinateSystem") if isinstance(grid.get("coordinateSystem"), dict) else {}
    width = coordinate.get("width")
    height = coordinate.get("height")
    require(width == single.OLDEN_WIDTH and height == single.OLDEN_HEIGHT, f"{label} coordinate size mismatch: {width}x{height}", errors)
    rows = grid.get("rows")
    require(isinstance(rows, list) and len(rows) == single.OLDEN_HEIGHT, f"{label} rows must be {single.OLDEN_HEIGHT} high", errors)
    if not isinstance(rows, list):
        return
    object_section_count = 0
    occupied_cells = 0
    for y, row in enumerate(rows):
        require(isinstance(row, list) and len(row) == single.OLDEN_WIDTH, f"{label} row {y} must be {single.OLDEN_WIDTH} cells", errors)
        if not isinstance(row, list):
            continue
        for x, cell in enumerate(row):
            if not isinstance(cell, dict):
                errors.append(f"{label} cell {x},{y} is not an object")
                continue
            node = y * single.OLDEN_WIDTH + x
            require(cell.get("x") == x and cell.get("y") == y and cell.get("node") == node, f"{label} cell coordinate mismatch at {x},{y}: {cell}", errors)
            require(isinstance(cell.get("terrain"), dict), f"{label} cell {x},{y} missing terrain object", errors)
            objects = cell.get("objects")
            require(isinstance(objects, list), f"{label} cell {x},{y} missing objects list", errors)
            if isinstance(objects, list) and objects:
                occupied_cells += 1
                object_section_count += len(objects)
                for obj in objects:
                    require(isinstance(obj, dict) and isinstance(obj.get("id"), int), f"{label} cell {x},{y} object row missing integer id: {obj}", errors)
                    section = obj.get("section") if isinstance(obj, dict) else None
                    require(isinstance(section, dict) and isinstance(section.get("sectionRole"), str), f"{label} cell {x},{y} object row missing section role: {obj}", errors)
    stats = grid.get("stats") if isinstance(grid.get("stats"), dict) else {}
    require(stats.get("cellCount") == single.OLDEN_WIDTH * single.OLDEN_HEIGHT, f"{label} cellCount stat mismatch", errors)
    require(stats.get("occupiedCellCount") == occupied_cells, f"{label} occupiedCellCount stat mismatch: {stats.get('occupiedCellCount')} != {occupied_cells}", errors)
    indexed_sections = sum(int(item.get("sectionCount") or 0) for item in grid.get("objectIndex") or [] if isinstance(item, dict))
    require(indexed_sections == object_section_count, f"{label} objectIndex sectionCount total mismatch: {indexed_sections} != {object_section_count}", errors)


def covered_ids(grid: dict[str, Any]) -> set[int]:
    ids: set[int] = set()
    for item in grid.get("objectIndex") or []:
        if isinstance(item, dict) and isinstance(item.get("id"), int):
            ids.add(int(item["id"]))
    return ids


def h3_visit_mask_offsets(mask: Any, source_key: str) -> set[tuple[int, int]]:
    if not isinstance(mask, list) or len(mask) != single.H3M_MASK_HEIGHT:
        raise ValueError(f"{source_key} has invalid templateVisitMask: {mask!r}")
    offsets: set[tuple[int, int]] = set()
    for row_index, raw in enumerate(mask):
        if not isinstance(raw, int) or raw < 0 or raw > 255:
            raise ValueError(f"{source_key} has invalid templateVisitMask byte: {raw!r}")
        for col_index in range(single.H3M_MASK_WIDTH):
            if raw & (1 << col_index):
                offsets.add((col_index - single.H3M_MASK_ANCHOR_X, row_index - single.H3M_MASK_ANCHOR_Y))
    return offsets


def h3_block_mask_offsets(mask: Any, source_key: str) -> set[tuple[int, int]]:
    return single.h3m_blocked_mask_offsets(mask)


def expected_homm3_grid_section_stats(surface_entities: list[dict[str, Any]]) -> tuple[dict[str, int], int]:
    counts: Counter[str] = Counter()
    off_grid = 0
    for entity in surface_entities:
        source_key = str(entity.get("sourceKey"))
        source_x = entity.get("sourceX")
        source_y = entity.get("sourceY")
        if not isinstance(source_x, int) or not isinstance(source_y, int):
            raise ValueError(f"{source_key} missing source coordinates")
        blocks = h3_block_mask_offsets(entity.get("templateBlockMask"), source_key)
        visits = h3_visit_mask_offsets(entity.get("templateVisitMask"), source_key)
        offsets = set(blocks) | set(visits)
        anchor_was_masked = (0, 0) in offsets
        if not offsets:
            offsets.add((0, 0))
        elif not anchor_was_masked:
            offsets.add((0, 0))
        for dx, dy in offsets:
            role = "mask_section" if (dx, dy) in blocks or (dx, dy) in visits else "anchor_marker"
            try:
                single.target_node_allowing_source_padding(source_x + dx, source_y + dy)
            except ValueError:
                off_grid += 1
                continue
            counts[role] += 1
    return dict(counts.most_common()), off_grid

def validate_homm3_grid(grid: dict[str, Any], repo_root: Path, errors: list[str]) -> None:
    alignment = read_json(repo_root / single.ALIGNMENT_PATH, errors)
    try:
        entities = alignment["alignment"]["globalObjectProperties"]["propEntities"]
    except Exception as exc:
        errors.append(f"cannot read alignment propEntities: {exc}")
        return
    surface_entities = [entity for entity in entities if isinstance(entity, dict) and entity.get("sourceLayer") == single.SOURCE_LAYER]
    expected_ids = {int(entity["sourceIndex"]) for entity in surface_entities if isinstance(entity.get("sourceIndex"), int)}
    object_ids = covered_ids(grid)
    off_grid_ids = {
        int(row["id"])
        for row in ((grid.get("stats") or {}).get("offGridSectionExamples") or [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }
    require((object_ids | off_grid_ids) == expected_ids, f"HoMM3 grid object coverage mismatch: missing={sorted(expected_ids - (object_ids | off_grid_ids))[:20]} extra={sorted((object_ids | off_grid_ids) - expected_ids)[:20]}", errors)
    require((grid.get("stats") or {}).get("sourceObjectCount") == len(expected_ids), "HoMM3 sourceObjectCount stat mismatch", errors)
    try:
        expected_section_histogram, expected_off_grid = expected_homm3_grid_section_stats(surface_entities)
    except Exception as exc:
        errors.append(f"cannot compute expected HoMM3 mask section stats: {exc}")
        return
    stats = grid.get("stats") if isinstance(grid.get("stats"), dict) else {}
    require(stats.get("gridSectionRoleHistogram") == expected_section_histogram, f"HoMM3 mask section histogram mismatch: {stats.get('gridSectionRoleHistogram')} != {expected_section_histogram}", errors)
    require(stats.get("offGridSectionCount") == expected_off_grid, f"HoMM3 offGridSectionCount mismatch: {stats.get('offGridSectionCount')} != {expected_off_grid}", errors)
    require(grid.get("kind") == "homm3_source_surface_aligned_to_single_layer_olden_envelope", f"HoMM3 grid kind mismatch: {grid.get('kind')}", errors)


def validate_olden_grid(grid: dict[str, Any], repo_root: Path, errors: list[str]) -> None:
    map_path = repo_root / single.OUT_ROOT / "maps" / f"{single.MAP_SID}.map"
    try:
        map_data = poc.read_olden_map_container(map_path).chunks[1]
    except Exception as exc:
        errors.append(f"cannot read Olden generated map {map_path}: {exc}")
        return
    expected_ids: set[int] = set()
    for group in map_data.get("objects") or []:
        if not isinstance(group, dict):
            continue
        ids = group.get("ids")
        nodes = group.get("nodes")
        rotations = group.get("rotations")
        levels = group.get("levels")
        require(all(isinstance(value, list) for value in (ids, nodes, rotations, levels)), f"Olden map object group invalid shape: {group}", errors)
        if all(isinstance(value, list) for value in (ids, nodes, rotations, levels)):
            require(len(ids) == len(nodes) == len(rotations) == len(levels), f"Olden map object group length mismatch: {group.get('sid')}", errors)
            expected_ids.update(int(item) for item in ids if isinstance(item, int))
    object_ids = covered_ids(grid)
    require(object_ids == expected_ids, f"Olden grid object coverage mismatch: missing={sorted(expected_ids - object_ids)[:20]} extra={sorted(object_ids - expected_ids)[:20]}", errors)
    require((grid.get("stats") or {}).get("objectInstanceCount") == len(expected_ids), "Olden objectInstanceCount stat mismatch", errors)
    require((grid.get("stats") or {}).get("offGridSectionCount") == 0, "Olden grid must not place object sections outside the 80x80 map", errors)
    require(grid.get("kind") == "olden_generated_single_layer_map", f"Olden grid kind mismatch: {grid.get('kind')}", errors)


def validate_diff(diff: dict[str, Any], homm3_grid: dict[str, Any], olden_grid: dict[str, Any], errors: list[str]) -> None:
    require(diff.get("schema") == EXPECTED_DIFF_SCHEMA, f"diff schema mismatch: {diff.get('schema')}", errors)
    require(diff.get("status") == EXPECTED_STATUS, f"diff status mismatch: {diff.get('status')}", errors)
    require(diff.get("terrainMismatchCount") == 0, f"terrain projection must match Olden generated map, found {diff.get('terrainMismatchCount')}", errors)
    require(diff.get("terrainMismatches") == [], "terrain mismatch list must be empty when count is zero", errors)
    require(diff.get("cellObjectMismatchCount") == len(diff.get("cellObjectMismatches") or []), "cellObjectMismatchCount does not match list length", errors)
    require(diff.get("sourceOnlyObjectCount") == len(diff.get("sourceOnlyObjects") or []), "sourceOnlyObjectCount does not match list length", errors)
    require(diff.get("oldenOnlyObjectCount") == len(diff.get("oldenOnlyObjects") or []), "oldenOnlyObjectCount does not match list length", errors)
    require(diff.get("commonObjectFootprintMismatchCount") == len(diff.get("commonObjectFootprintMismatches") or []), "commonObjectFootprintMismatchCount does not match list length", errors)
    summary = diff.get("summary") if isinstance(diff.get("summary"), dict) else {}
    h3_ids = covered_ids(homm3_grid)
    olden_ids = covered_ids(olden_grid)
    require(summary.get("homm3ObjectCount") == len(h3_ids), "diff summary HoMM3 object count mismatch", errors)
    require(summary.get("oldenObjectCount") == len(olden_ids), "diff summary Olden object count mismatch", errors)
    require(summary.get("commonObjectCount") == len(h3_ids & olden_ids), "diff summary common object count mismatch", errors)
    require(summary.get("terrainProjectedMatchesOlden") is True, "diff summary must record terrainProjectedMatchesOlden=true", errors)
    recomputed = grid_builder.build_grid_diff(homm3_grid, olden_grid)
    require(diff == recomputed, "diff artifact is stale or does not match the recomputed HoMM3-vs-Olden grid diff", errors)


def maybe_generate(repo_root: Path, skip_generate: bool) -> None:
    if skip_generate:
        return
    subprocess.run(
        [sys.executable, str(repo_root / "experiments" / "campaign_port_poc" / "build_homecoming_tile_object_grid.py")],
        cwd=repo_root,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    errors: list[str] = []
    maybe_generate(repo_root, args.skip_generate)

    homm3_grid = read_json(repo_root / grid_builder.HOMM3_SURFACE_GRID_PATH, errors)
    olden_grid = read_json(repo_root / grid_builder.OLDEN_SINGLE_LAYER_GRID_PATH, errors)
    diff = read_json(repo_root / grid_builder.DIFF_PATH, errors)

    if homm3_grid:
        validate_rows_shape(homm3_grid, "HoMM3 source tile-object grid", errors)
        validate_homm3_grid(homm3_grid, repo_root, errors)
    if olden_grid:
        validate_rows_shape(olden_grid, "Olden single-layer tile-object grid", errors)
        validate_olden_grid(olden_grid, repo_root, errors)
    if diff and homm3_grid and olden_grid:
        validate_diff(diff, homm3_grid, olden_grid, errors)

    if errors:
        print("Homecoming tile-object grid contract validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Homecoming tile-object grid contract validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
