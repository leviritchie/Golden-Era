#!/usr/bin/env python3
"""Build cell-level HoMM3/Olden tile-object grids for Homecoming diagnostics."""

from __future__ import annotations

import argparse
import json
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import build_homecoming_single_layer_map as single
import port_homecoming_poc as poc

SCHEMA = "homm3.homecoming_tile_object_grid.v0"
DIFF_SCHEMA = "homm3.homecoming_tile_object_grid_diff.v0"
STATUS = "generated_artifact_validated_runtime_unvalidated"
FOOTPRINT_PROOF = "source_static_h3m_masks_and_olden_object_config_size_grid"
OUT_ROOT = single.BASE_OUT_ROOT / "tile_object_grid"
HOMM3_SURFACE_GRID_PATH = OUT_ROOT / "homecoming.homm3_surface_80x80_tile_object_grid.json"
OLDEN_SINGLE_LAYER_GRID_PATH = OUT_ROOT / "homecoming.olden_single_layer_80x80_tile_object_grid.json"
DIFF_PATH = OUT_ROOT / "homecoming.single_layer_tile_object_grid_diff.json"
REPORT_PATH = OUT_ROOT / "HOMECOMING_TILE_OBJECT_GRID_REPORT.md"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def target_xy_from_source_padding(source_x: int, source_y: int) -> tuple[int, int, int]:
    node = single.target_node_allowing_source_padding(source_x, source_y)
    return node % single.OLDEN_WIDTH, node // single.OLDEN_WIDTH, node


def raw_source_for_olden_xy(surface_map_data: dict[str, Any], x: int, y: int) -> dict[str, Any]:
    source_x = x - single.SOURCE_OFFSET_X
    source_y = single.SOURCE_HEIGHT - 1 - (y - single.SOURCE_OFFSET_Y)
    in_source_bounds = 0 <= source_x < single.SOURCE_WIDTH and 0 <= source_y < single.SOURCE_HEIGHT
    result: dict[str, Any] = {
        "sourceX": source_x,
        "sourceY": source_y,
        "inSourceBounds": in_source_bounds,
    }
    if not in_source_bounds:
        return result
    raw_node = source_y * single.SOURCE_WIDTH + source_x
    result.update({
        "sourceNode": raw_node,
        "h3Terrain": surface_map_data["tilesMap"][raw_node],
        "h3Road": surface_map_data["roadsMap"][raw_node],
        "h3River": surface_map_data["waterMap"][raw_node],
        "h3Mirror": (surface_map_data.get("rawMirror") or [0] * (single.SOURCE_WIDTH * single.SOURCE_HEIGHT))[raw_node],
    })
    return result


def make_empty_grid(width: int, height: int, terrain_factory: Any) -> list[list[dict[str, Any]]]:
    rows: list[list[dict[str, Any]]] = []
    for y in range(height):
        row: list[dict[str, Any]] = []
        for x in range(width):
            node = y * width + x
            row.append({
                "x": x,
                "y": y,
                "node": node,
                "terrain": terrain_factory(x, y, node),
                "objects": [],
            })
        rows.append(row)
    return rows


def require_h3_mask(entity: dict[str, Any], key: str) -> list[int]:
    mask = entity.get(key)
    if not isinstance(mask, list) or len(mask) != single.H3M_MASK_HEIGHT:
        raise ValueError(f"HoMM3 entity {entity.get('sourceKey')} has invalid {key}: {mask!r}")
    for raw in mask:
        if not isinstance(raw, int) or raw < 0 or raw > 255:
            raise ValueError(f"HoMM3 entity {entity.get('sourceKey')} has invalid {key} byte: {raw!r}")
    return mask


def h3_object_sections(entity: dict[str, Any]) -> list[dict[str, Any]]:
    require_h3_mask(entity, "templateBlockMask")
    require_h3_mask(entity, "templateVisitMask")
    blocks = single.entity_blocked_mask_offsets(entity)
    visits = single.source_visit_offsets(entity)
    offsets = set(blocks) | set(visits)
    anchor_was_masked = (0, 0) in offsets
    if not offsets:
        offsets.add((0, 0))
    elif not anchor_was_masked:
        offsets.add((0, 0))

    sections: list[dict[str, Any]] = []
    for dx, dy in sorted(offsets, key=lambda item: (item[1], item[0])):
        mask_kinds: list[str] = []
        if (dx, dy) in blocks:
            mask_kinds.append("block")
        if (dx, dy) in visits:
            mask_kinds.append("visit")
        section_role = "mask_section" if mask_kinds else "anchor_marker"
        sections.append({
            "sectionRole": section_role,
            "coverage": section_role == "mask_section" or not anchor_was_masked and len(offsets) == 1,
            "h3Offset": [dx, dy],
            "maskKinds": mask_kinds,
            "maskPolicy": "vcmi_readMap_blockMask_bit_0_is_blocked_visitMask_bit_1_is_visitable",
            "isAnchor": dx == 0 and dy == 0,
        })
    return sections


def append_homm3_objects(rows: list[list[dict[str, Any]]], entities: list[dict[str, Any]]) -> dict[str, Any]:
    off_grid: list[dict[str, Any]] = []
    section_counts = Counter()
    object_ids: set[int] = set()
    object_details: dict[int, dict[str, Any]] = {}
    for entity in entities:
        source_index = entity.get("sourceIndex")
        source_x = entity.get("sourceX")
        source_y = entity.get("sourceY")
        if not isinstance(source_index, int) or not isinstance(source_x, int) or not isinstance(source_y, int):
            raise ValueError(f"HoMM3 entity missing source index or coordinates: {entity}")
        object_ids.add(source_index)
        object_details[source_index] = {
            "sid": entity.get("sid"),
            "sourceKey": entity.get("sourceKey"),
            "sourceLayer": entity.get("sourceLayer"),
            "sourceAnchor": [source_x, source_y],
            "templateObjectId": entity.get("templateObjectId"),
            "templateSubtype": entity.get("templateSubtype"),
            "templateAnimation": entity.get("templateAnimation"),
            "category": entity.get("category"),
            "payloadKind": entity.get("payloadKind"),
        }
        for section in h3_object_sections(entity):
            dx, dy = section["h3Offset"]
            section_source_x = source_x + dx
            section_source_y = source_y + dy
            try:
                grid_x, grid_y, node = target_xy_from_source_padding(section_source_x, section_source_y)
            except ValueError:
                off_grid.append({
                    "id": source_index,
                    "sourceKey": entity.get("sourceKey"),
                    "templateObjectId": entity.get("templateObjectId"),
                    "templateAnimation": entity.get("templateAnimation"),
                    "sectionSource": [section_source_x, section_source_y],
                    "section": section,
                })
                continue
            entry = {"id": source_index, "sourceSection": [section_source_x, section_source_y], "section": section}
            rows[grid_y][grid_x]["objects"].append(entry)
            section_counts[section["sectionRole"]] += 1
            if node != rows[grid_y][grid_x]["node"]:
                raise AssertionError("grid node indexing mismatch")
    return {
        "sourceObjectCount": len(object_ids),
        "objectDetails": object_details,
        "gridSectionRoleHistogram": dict(section_counts.most_common()),
        "offGridSectionCount": len(off_grid),
        "offGridSectionExamples": off_grid[:25],
    }


def sort_grid_objects(rows: list[list[dict[str, Any]]]) -> None:
    for row in rows:
        for cell in row:
            cell["objects"].sort(
                key=lambda item: (
                    int(item.get("id") or -1),
                    str(item.get("sid") or ""),
                    str((item.get("section") or {}).get("sectionRole") or ""),
                    json.dumps((item.get("section") or {}), sort_keys=True),
                )
            )


def terrain_histogram(rows: list[list[dict[str, Any]]], key: str) -> dict[str, int]:
    values = Counter()
    for row in rows:
        for cell in row:
            terrain = cell.get("terrain") or {}
            value = terrain.get(key)
            values[str(value)] += 1
    return dict(values.most_common())


def projected_terrain_histogram(rows: list[list[dict[str, Any]]], key: str) -> dict[str, int]:
    values = Counter()
    for row in rows:
        for cell in row:
            projected = ((cell.get("terrain") or {}).get("projectedOlden") or {})
            values[str(projected.get(key))] += 1
    return dict(values.most_common())


def build_object_index(rows: list[list[dict[str, Any]]], details_by_id: dict[int, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    entries: dict[int, dict[str, Any]] = {}
    real_section_by_id: dict[int, bool] = defaultdict(bool)
    for row in rows:
        for cell in row:
            for obj in cell["objects"]:
                object_id = int(obj["id"])
                section = obj.get("section") or {}
                if section.get("sectionRole") != "anchor_marker":
                    real_section_by_id[object_id] = True
    for row in rows:
        for cell in row:
            for obj in cell["objects"]:
                object_id = int(obj["id"])
                section = obj.get("section") or {}
                role = section.get("sectionRole")
                covered = role != "anchor_marker" or not real_section_by_id[object_id]
                detail = dict((details_by_id or {}).get(object_id, {}))
                detail.update({
                    "id": object_id,
                    "sid": detail.get("sid", obj.get("sid")),
                    "templateObjectId": detail.get("templateObjectId", obj.get("templateObjectId")),
                    "templateAnimation": detail.get("templateAnimation", obj.get("templateAnimation")),
                    "sourceKey": detail.get("sourceKey", obj.get("sourceKey")),
                    "coveredNodes": [],
                    "anchorMarkerNodes": [],
                    "sectionCount": 0,
                })
                item = entries.setdefault(object_id, detail)
                item["sectionCount"] += 1
                if covered:
                    item["coveredNodes"].append(cell["node"])
                else:
                    item["anchorMarkerNodes"].append(cell["node"])
    for item in entries.values():
        item["coveredNodes"] = sorted(set(item["coveredNodes"]))
        item["anchorMarkerNodes"] = sorted(set(item["anchorMarkerNodes"]))
        item["coveredCellCount"] = len(item["coveredNodes"])
    return [entries[key] for key in sorted(entries)]


def build_homm3_surface_grid(alignment: dict[str, Any]) -> dict[str, Any]:
    surface_map_data = alignment["container"]["chunks"][1]
    projected = single.project_arrays(surface_map_data)

    def terrain_factory(x: int, y: int, node: int) -> dict[str, Any]:
        source = raw_source_for_olden_xy(surface_map_data, x, y)
        return {
            "domain": "homm3_raw_source_with_olden_projection",
            "source": source,
            "projectedOlden": {
                "tilesMap": projected["tilesMap"][node],
                "levelsMap": projected["levelsMap"][node],
                "climbsMap": projected["climbsMap"][node],
                "roadsMap": projected["roadsMap"][node],
                "waterMap": projected["waterMap"][node],
                "customAreasPainting": projected["customAreasPainting"][node],
            },
        }

    rows = make_empty_grid(single.OLDEN_WIDTH, single.OLDEN_HEIGHT, terrain_factory)
    entities = [
        entity
        for entity in alignment["alignment"]["globalObjectProperties"]["propEntities"]
        if entity.get("sourceLayer") == single.SOURCE_LAYER
    ]
    object_stats = append_homm3_objects(rows, entities)
    object_details = object_stats.pop("objectDetails")
    sort_grid_objects(rows)
    object_index = build_object_index(rows, object_details)
    occupied_cells = sum(1 for row in rows for cell in row if cell["objects"])
    return {
        "schema": SCHEMA,
        "status": STATUS,
        "kind": "homm3_source_surface_aligned_to_single_layer_olden_envelope",
        "mapSid": single.MAP_SID,
        "coordinateSystem": {
            "width": single.OLDEN_WIDTH,
            "height": single.OLDEN_HEIGHT,
            "node": "y * width + x",
            "x": "Olden grid x; sourceX = x - sourceOffsetX for source cells",
            "y": "Olden top-origin y; sourceY = sourceHeight - 1 - (y - sourceOffsetY) for source cells",
            "sourceOffsetX": single.SOURCE_OFFSET_X,
            "sourceOffsetY": single.SOURCE_OFFSET_Y,
            "sourceWidth": single.SOURCE_WIDTH,
            "sourceHeight": single.SOURCE_HEIGHT,
        },
        "footprintProof": FOOTPRINT_PROOF,
        "runtimeProofStatus": "runtime_unvalidated_visual_prediction",
        "rows": rows,
        "objectIndex": object_index,
        "stats": {
            **object_stats,
            "width": single.OLDEN_WIDTH,
            "height": single.OLDEN_HEIGHT,
            "cellCount": single.OLDEN_WIDTH * single.OLDEN_HEIGHT,
            "occupiedCellCount": occupied_cells,
            "objectIndexCount": len(object_index),
            "projectedTileHistogram": projected_terrain_histogram(rows, "tilesMap"),
            "projectedWaterHistogram": projected_terrain_histogram(rows, "waterMap"),
        },
    }


def load_core_object_configs(sids: set[str]) -> dict[str, dict[str, Any]]:
    configs: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
        for name in core.namelist():
            if not (name.startswith("DB/map/objects/") and name.endswith(".json")):
                continue
            doc = json.loads(core.read(name).decode("utf-8-sig"))
            rows = doc.get("array") if isinstance(doc, dict) else None
            if not isinstance(rows, list):
                raise ValueError(f"Core map-object member has no array rows: {name}")
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"] in sids:
                    configs[row["id"]] = row
    overlay_root = single.OUT_ROOT / "core_overlay" / "DB" / "map" / "objects"
    if overlay_root.exists():
        for path in sorted(overlay_root.rglob("*.json")):
            doc = read_json(path)
            rows = doc.get("array") if isinstance(doc, dict) else None
            if not isinstance(rows, list):
                raise ValueError(f"generated Core overlay map-object member has no array rows: {path}")
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"] in sids:
                    configs[row["id"]] = row
    if single.HOMM3_BOAT_SID in sids:
        configs[single.HOMM3_BOAT_SID] = single.homm3_boat_object_row()
    if single.HOMM3_SUBTERRANEAN_GATE_PORTAL_SID in sids and single.HOMM3_SUBTERRANEAN_GATE_PORTAL_SID not in configs:
        donor = configs.get(single.HOMM3_SUBTERRANEAN_GATE_PORTAL_DONOR_SID)
        if not isinstance(donor, dict):
            raise ValueError(f"missing {single.HOMM3_SUBTERRANEAN_GATE_PORTAL_DONOR_SID} donor config for {single.HOMM3_SUBTERRANEAN_GATE_PORTAL_SID}")
        configs[single.HOMM3_SUBTERRANEAN_GATE_PORTAL_SID] = single.homm3_subterranean_gate_portal_object_row(donor)
    single.inject_homm3_landon_object_configs(configs, sids)
    for row in single.homecoming_water_tile_overlay_object_rows():
        if row["id"] in sids:
            configs[row["id"]] = row
    missing = sorted(sids - set(configs))
    if missing:
        raise ValueError(f"missing Olden object config rows for emitted SIDs: {missing[:25]}")
    return configs


def native_grid_sections(sid: str, config: dict[str, Any], rotation: int) -> list[dict[str, Any]]:
    size_x = config.get("sizeX")
    size_z = config.get("sizeZ")
    footprint_source = "native_object_config_size_grid"
    if not isinstance(size_x, int) or not isinstance(size_z, int) or size_x <= 0 or size_z <= 0:
        generator_config = config.get("generatorConfig")
        if isinstance(generator_config, dict) and isinstance(generator_config.get("buildingSizeX"), int) and isinstance(generator_config.get("buildingSizeZ"), int):
            size_x = int(generator_config["buildingSizeX"])
            size_z = int(generator_config["buildingSizeZ"])
            footprint_source = "native_generator_building_size_grid"
        elif sid in single.POINT_ANCHOR_WITHOUT_NATIVE_FOOTPRINT_SIDS:
            size_x = 1
            size_z = 1
            footprint_source = "explicit_point_anchor_without_native_size"
        else:
            return [{
                "sectionRole": "anchor_only_missing_native_size",
                "coverage": True,
                "footprintSource": "native_config_missing_size_anchor_only",
                "sizeX": None,
                "sizeZ": None,
                "configOffset": [0, 0],
                "placedOffset": [0, 0],
                "nodeValue": None,
                "occupied": False,
                "mirroredByRotation": False,
                "rotation": rotation,
                "runtimeProofStatus": "native_size_unknown_diagnostic_anchor_only",
            }]
    nodes = config.get("nodes")
    if nodes is not None and (not isinstance(nodes, list) or len(nodes) != size_x * size_z):
        raise ValueError(f"Olden object config for {sid} has invalid nodes length for {size_x}x{size_z}: {nodes}")
    mirrored = rotation == single.OLDEN_MIRRORED_ROTATION and config.get("canBeMirrored") is True
    sections: list[dict[str, Any]] = []
    for config_z in range(size_z):
        for config_x in range(size_x):
            node_value = nodes[config_z * size_x + config_x] if isinstance(nodes, list) else None
            placed_dx = size_x - 1 - config_x if mirrored else config_x
            sections.append({
                "sectionRole": "native_size_grid_section",
                "coverage": True,
                "footprintSource": footprint_source,
                "sizeX": size_x,
                "sizeZ": size_z,
                "configOffset": [config_x, config_z],
                "placedOffset": [placed_dx, size_z - 1 - config_z],
                "nodeValue": node_value,
                "occupied": node_value == 1,
                "mirroredByRotation": mirrored,
                "rotation": rotation,
                "runtimeProofStatus": "rotation_section_mirroring_inferred_from_current_translator_policy",
            })
    return sections


def append_olden_objects(rows: list[list[dict[str, Any]]], map_data: dict[str, Any], configs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    prop_entities = {
        int(entity["id"]): entity
        for entity in (map_data.get("objectsProperties") or {}).get("propEntities", [])
        if isinstance(entity, dict) and isinstance(entity.get("id"), int)
    }
    off_grid: list[dict[str, Any]] = []
    section_counts = Counter()
    object_count = 0
    for group in map_data.get("objects") or []:
        if not isinstance(group, dict):
            raise ValueError(f"Olden object group is not an object: {group}")
        sid = group.get("sid")
        ids = group.get("ids")
        nodes = group.get("nodes")
        rotations = group.get("rotations")
        levels = group.get("levels")
        if not isinstance(sid, str) or not all(isinstance(value, list) for value in (ids, nodes, rotations, levels)):
            raise ValueError(f"Olden object group has invalid shape: {group}")
        if not (len(ids) == len(nodes) == len(rotations) == len(levels)):
            raise ValueError(f"Olden object group arrays differ in length for {sid}")
        config = configs[sid]
        for object_id, anchor_node, rotation, level in zip(ids, nodes, rotations, levels):
            if not isinstance(object_id, int) or not isinstance(anchor_node, int) or not isinstance(rotation, int):
                raise ValueError(f"Olden object instance has invalid id/node/rotation in {sid}: {object_id}, {anchor_node}, {rotation}")
            object_count += 1
            anchor_x = anchor_node % single.OLDEN_WIDTH
            anchor_y = anchor_node // single.OLDEN_WIDTH
            source_entity = prop_entities.get(object_id)
            for section in native_grid_sections(sid, config, rotation):
                dx, dy = section["placedOffset"]
                grid_x = anchor_x + dx
                grid_y = anchor_y + dy
                if not (0 <= grid_x < single.OLDEN_WIDTH and 0 <= grid_y < single.OLDEN_HEIGHT):
                    off_grid.append({
                        "id": object_id,
                        "sid": sid,
                        "anchorNode": anchor_node,
                        "anchor": [anchor_x, anchor_y],
                        "section": section,
                    })
                    continue
                entry = {
                    "id": object_id,
                    "sid": sid,
                    "node": anchor_node,
                    "anchor": [anchor_x, anchor_y],
                    "rotation": rotation,
                    "level": level,
                    "sourceKey": source_entity.get("sourceKey") if isinstance(source_entity, dict) else None,
                    "sourceLayer": source_entity.get("sourceLayer") if isinstance(source_entity, dict) else None,
                    "templateObjectId": source_entity.get("templateObjectId") if isinstance(source_entity, dict) else None,
                    "templateAnimation": source_entity.get("templateAnimation") if isinstance(source_entity, dict) else None,
                    "section": section,
                }
                rows[grid_y][grid_x]["objects"].append(entry)
                section_counts[section["sectionRole"]] += 1
    return {
        "objectInstanceCount": object_count,
        "gridSectionRoleHistogram": dict(section_counts.most_common()),
        "offGridSectionCount": len(off_grid),
        "offGridSectionExamples": off_grid[:25],
    }


def build_olden_single_layer_grid() -> dict[str, Any]:
    map_path = single.OUT_ROOT / "maps" / f"{single.MAP_SID}.map"
    container = poc.read_olden_map_container(map_path)
    map_data = container.chunks[1]
    width = map_data.get("sizeX_")
    height = map_data.get("sizeZ_")
    if width != single.OLDEN_WIDTH or height != single.OLDEN_HEIGHT:
        raise ValueError(f"expected {single.OLDEN_WIDTH}x{single.OLDEN_HEIGHT} Olden map, found {width}x{height}")
    for key in ("tilesMap", "levelsMap", "climbsMap", "roadsMap", "waterMap", "customAreasPainting"):
        value = map_data.get(key)
        if not isinstance(value, list) or len(value) != width * height:
            raise ValueError(f"Olden map has invalid {key} length")

    def terrain_factory(_x: int, _y: int, node: int) -> dict[str, Any]:
        return {
            "domain": "olden_generated_map",
            "tilesMap": map_data["tilesMap"][node],
            "levelsMap": map_data["levelsMap"][node],
            "climbsMap": map_data["climbsMap"][node],
            "roadsMap": map_data["roadsMap"][node],
            "waterMap": map_data["waterMap"][node],
            "customAreasPainting": map_data["customAreasPainting"][node],
        }

    rows = make_empty_grid(width, height, terrain_factory)
    sids = {
        group["sid"]
        for group in map_data.get("objects") or []
        if isinstance(group, dict) and isinstance(group.get("sid"), str)
    }
    configs = load_core_object_configs(sids)
    object_stats = append_olden_objects(rows, map_data, configs)
    sort_grid_objects(rows)
    object_index = build_object_index(rows)
    occupied_cells = sum(1 for row in rows for cell in row if cell["objects"])
    return {
        "schema": SCHEMA,
        "status": STATUS,
        "kind": "olden_generated_single_layer_map",
        "mapSid": single.MAP_SID,
        "sourceMap": str(map_path),
        "coordinateSystem": {
            "width": width,
            "height": height,
            "node": "y * width + x",
            "x": "Olden grid x",
            "y": "Olden top-origin y",
        },
        "footprintProof": FOOTPRINT_PROOF,
        "runtimeProofStatus": "runtime_unvalidated_visual_prediction",
        "rows": rows,
        "objectIndex": object_index,
        "stats": {
            **object_stats,
            "width": width,
            "height": height,
            "cellCount": width * height,
            "occupiedCellCount": occupied_cells,
            "objectIndexCount": len(object_index),
            "tileHistogram": terrain_histogram(rows, "tilesMap"),
        },
    }


def covered_nodes_by_object(grid: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in grid.get("objectIndex") or []:
        object_id = int(item["id"])
        result[object_id] = {
            "id": object_id,
            "sid": item.get("sid"),
            "templateObjectId": item.get("templateObjectId"),
            "templateAnimation": item.get("templateAnimation"),
            "sourceKey": item.get("sourceKey"),
            "coveredNodes": set(int(node) for node in item.get("coveredNodes") or []),
        }
    return result


def cell_object_ids(cell: dict[str, Any]) -> set[int]:
    ids: set[int] = set()
    for obj in cell.get("objects") or []:
        section = obj.get("section") or {}
        if section.get("sectionRole") == "anchor_marker":
            continue
        ids.add(int(obj["id"]))
    return ids


def grid_dimensions(grid: dict[str, Any]) -> tuple[int, int]:
    coordinate = grid.get("coordinateSystem") if isinstance(grid.get("coordinateSystem"), dict) else {}
    width = coordinate.get("width")
    height = coordinate.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise ValueError(f"grid missing coordinateSystem width/height: {grid.get('kind')}")
    return width, height


def build_grid_diff(homm3_grid: dict[str, Any], olden_grid: dict[str, Any]) -> dict[str, Any]:
    h3_rows = homm3_grid["rows"]
    olden_rows = olden_grid["rows"]
    width, height = grid_dimensions(homm3_grid)
    olden_width, olden_height = grid_dimensions(olden_grid)
    if (width, height) != (olden_width, olden_height):
        raise ValueError(f"grid dimension mismatch: homm3={width}x{height} olden={olden_width}x{olden_height}")
    terrain_mismatches: list[dict[str, Any]] = []
    cell_object_mismatches: list[dict[str, Any]] = []
    for y in range(height):
        for x in range(width):
            h3_cell = h3_rows[y][x]
            olden_cell = olden_rows[y][x]
            projected = (h3_cell.get("terrain") or {}).get("projectedOlden") or {}
            olden_terrain = olden_cell.get("terrain") or {}
            for key in ("tilesMap", "levelsMap", "climbsMap", "roadsMap", "waterMap", "customAreasPainting"):
                if projected.get(key) != olden_terrain.get(key):
                    terrain_mismatches.append({
                        "node": h3_cell["node"],
                        "x": x,
                        "y": y,
                        "field": key,
                        "homm3Projected": projected.get(key),
                        "olden": olden_terrain.get(key),
                    })
            h3_ids = cell_object_ids(h3_cell)
            olden_ids = cell_object_ids(olden_cell)
            if h3_ids != olden_ids:
                cell_object_mismatches.append({
                    "node": h3_cell["node"],
                    "x": x,
                    "y": y,
                    "homm3ObjectIds": sorted(h3_ids),
                    "oldenObjectIds": sorted(olden_ids),
                    "missingInOlden": sorted(h3_ids - olden_ids),
                    "extraInOlden": sorted(olden_ids - h3_ids),
                })
    h3_objects = covered_nodes_by_object(homm3_grid)
    olden_objects = covered_nodes_by_object(olden_grid)
    h3_ids = set(h3_objects)
    olden_ids = set(olden_objects)
    common_diffs: list[dict[str, Any]] = []
    for object_id in sorted(h3_ids & olden_ids):
        h3_nodes = h3_objects[object_id]["coveredNodes"]
        olden_nodes = olden_objects[object_id]["coveredNodes"]
        if h3_nodes == olden_nodes:
            continue
        common_diffs.append({
            "id": object_id,
            "sourceKey": h3_objects[object_id].get("sourceKey") or olden_objects[object_id].get("sourceKey"),
            "templateObjectId": h3_objects[object_id].get("templateObjectId") or olden_objects[object_id].get("templateObjectId"),
            "templateAnimation": h3_objects[object_id].get("templateAnimation") or olden_objects[object_id].get("templateAnimation"),
            "oldenSid": olden_objects[object_id].get("sid"),
            "missingNodesInOlden": sorted(h3_nodes - olden_nodes),
            "extraNodesInOlden": sorted(olden_nodes - h3_nodes),
            "homm3CoveredCellCount": len(h3_nodes),
            "oldenCoveredCellCount": len(olden_nodes),
        })
    source_only = [
        {
            "id": object_id,
            "sourceKey": h3_objects[object_id].get("sourceKey"),
            "templateObjectId": h3_objects[object_id].get("templateObjectId"),
            "templateAnimation": h3_objects[object_id].get("templateAnimation"),
            "coveredCellCount": len(h3_objects[object_id]["coveredNodes"]),
        }
        for object_id in sorted(h3_ids - olden_ids)
    ]
    olden_only = [
        {
            "id": object_id,
            "sid": olden_objects[object_id].get("sid"),
            "sourceKey": olden_objects[object_id].get("sourceKey"),
            "templateObjectId": olden_objects[object_id].get("templateObjectId"),
            "templateAnimation": olden_objects[object_id].get("templateAnimation"),
            "coveredCellCount": len(olden_objects[object_id]["coveredNodes"]),
        }
        for object_id in sorted(olden_ids - h3_ids)
    ]
    return {
        "schema": DIFF_SCHEMA,
        "status": STATUS,
        "mapSid": single.MAP_SID,
        "coordinateSystem": homm3_grid["coordinateSystem"],
        "inputs": {
            "homm3Grid": str(HOMM3_SURFACE_GRID_PATH),
            "oldenGrid": str(OLDEN_SINGLE_LAYER_GRID_PATH),
        },
        "terrainMismatchCount": len(terrain_mismatches),
        "terrainMismatches": terrain_mismatches,
        "cellObjectMismatchCount": len(cell_object_mismatches),
        "cellObjectMismatches": cell_object_mismatches,
        "sourceOnlyObjectCount": len(source_only),
        "sourceOnlyObjects": source_only,
        "oldenOnlyObjectCount": len(olden_only),
        "oldenOnlyObjects": olden_only,
        "commonObjectFootprintMismatchCount": len(common_diffs),
        "commonObjectFootprintMismatches": common_diffs,
        "summary": {
            "homm3ObjectCount": len(h3_ids),
            "oldenObjectCount": len(olden_ids),
            "commonObjectCount": len(h3_ids & olden_ids),
            "terrainProjectedMatchesOlden": len(terrain_mismatches) == 0,
        },
    }


def write_report(diff: dict[str, Any], homm3_grid: dict[str, Any], olden_grid: dict[str, Any]) -> None:
    lines = [
        "# Homecoming Tile Object Grid",
        "",
        f"Schema: `{SCHEMA}`",
        f"Status: `{STATUS}`",
        "",
        "## Artifacts",
        f"- HoMM3 source grid: `{HOMM3_SURFACE_GRID_PATH}`",
        f"- Olden generated grid: `{OLDEN_SINGLE_LAYER_GRID_PATH}`",
        f"- Cell/object diff: `{DIFF_PATH}`",
        "",
        "## Scope",
        "- Generates 80x80 row/column JSON grids for the Homecoming surface layer and generated Olden single-layer map.",
        "- HoMM3 sections come from H3M template block/visit masks projected into the Olden 80x80 envelope.",
        "- Olden sections come from map object instances plus `ObjectConfig.sizeX/sizeZ/nodes`; mirror sections follow the current translator's rotation-10 policy and remain runtime-unvalidated.",
        "",
        "## Summary",
        f"- HoMM3 source objects represented: {homm3_grid['stats']['sourceObjectCount']}",
        f"- Olden generated objects represented: {olden_grid['stats']['objectInstanceCount']}",
        f"- Terrain projection mismatches: {diff['terrainMismatchCount']}",
        f"- Cell object mismatches: {diff['cellObjectMismatchCount']}",
        f"- Source-only objects: {diff['sourceOnlyObjectCount']}",
        f"- Olden-only objects: {diff['oldenOnlyObjectCount']}",
        f"- Common object footprint mismatches: {diff['commonObjectFootprintMismatchCount']}",
        "",
        "## Proof Boundary",
        "This is source/static/generated-artifact evidence for pre-runtime review. It is not proof that Unity renders every mirrored section exactly this way.",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_artifacts() -> dict[str, Any]:
    alignment = read_json(single.ALIGNMENT_PATH)
    homm3_grid = build_homm3_surface_grid(alignment)
    olden_grid = build_olden_single_layer_grid()
    diff = build_grid_diff(homm3_grid, olden_grid)
    write_json(HOMM3_SURFACE_GRID_PATH, homm3_grid)
    write_json(OLDEN_SINGLE_LAYER_GRID_PATH, olden_grid)
    write_json(DIFF_PATH, diff)
    write_report(diff, homm3_grid, olden_grid)
    return {
        "homm3Grid": str(HOMM3_SURFACE_GRID_PATH),
        "oldenGrid": str(OLDEN_SINGLE_LAYER_GRID_PATH),
        "diff": str(DIFF_PATH),
        "report": str(REPORT_PATH),
        "summary": diff["summary"],
        "terrainMismatchCount": diff["terrainMismatchCount"],
        "cellObjectMismatchCount": diff["cellObjectMismatchCount"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[2], type=Path)
    args = parser.parse_args()
    expected_root = Path(__file__).resolve().parents[2].resolve()
    if args.repo_root.resolve() != expected_root:
        raise ValueError(f"--repo-root must point to this checkout: {expected_root}")
    result = build_artifacts()
    print(f"generated {result['homm3Grid']}")
    print(f"generated {result['oldenGrid']}")
    print(f"generated {result['diff']}")
    print(
        f"terrainMismatches={result['terrainMismatchCount']} "
        f"cellObjectMismatches={result['cellObjectMismatchCount']} "
        f"summary={result['summary']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
