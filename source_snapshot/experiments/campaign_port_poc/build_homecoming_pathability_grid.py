#!/usr/bin/env python3
"""Build a per-cell HoMM3-vs-Olden pathability grid for Homecoming."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import build_homecoming_single_layer_map as single
import build_homecoming_tile_object_grid as tile_grid

SCHEMA = "homm3.homecoming_pathability_grid.v3"
STATUS = "generated_artifact_validated_runtime_unvalidated"
OUT_ROOT = single.BASE_OUT_ROOT / "pathability_grid"
OUTPUT_PATH = OUT_ROOT / "homecoming.surface_pathability_grid.json"
REPORT_PATH = OUT_ROOT / "HOMECOMING_PATHABILITY_GRID_REPORT.md"
UNKNOWN_NATIVE_SIZE_FOOTPRINT_SOURCE = "native_config_missing_size_anchor_only"
EXPLICIT_POINT_ANCHOR_FOOTPRINT_SOURCE = "explicit_point_anchor_without_native_size"
NATIVE_OBJECT_CONFIG_FOOTPRINT_SOURCE = "native_object_config_size_grid"
NATIVE_GENERATOR_FOOTPRINT_SOURCE = "native_generator_building_size_grid"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def compact_object(obj: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": obj.get("id"),
        "sid": obj.get("sid"),
        "sourceKey": obj.get("sourceKey"),
        "templateObjectId": obj.get("templateObjectId"),
        "templateAnimation": obj.get("templateAnimation"),
        "section": obj.get("section"),
    }


def compact_homm3_entity(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entity.get("sourceIndex"),
        "sourceKey": entity.get("sourceKey"),
        "templateObjectId": entity.get("templateObjectId"),
        "templateSubtype": entity.get("templateSubtype"),
        "templateAnimation": entity.get("templateAnimation"),
        "category": entity.get("category"),
        "payloadKind": entity.get("payloadKind"),
    }


def require_h3_mask(entity: dict[str, Any], key: str) -> list[int]:
    mask = entity.get(key)
    if not isinstance(mask, list) or len(mask) != single.H3M_MASK_HEIGHT:
        raise ValueError(f"HoMM3 entity {entity.get('sourceKey')} has invalid {key}: {mask!r}")
    for raw in mask:
        if not isinstance(raw, int) or raw < 0 or raw > 255:
            raise ValueError(f"HoMM3 entity {entity.get('sourceKey')} has invalid {key} byte: {raw!r}")
    return mask


def h3_mask_bit(mask: list[int], row_index: int, col_index: int) -> int:
    return (mask[row_index] >> col_index) & 1


def h3_raw_mask_offset(row_index: int, col_index: int) -> tuple[int, int]:
    # VCMI reads raw bits into usedTiles[5 - row][7 - col], then blocked offsets
    # are relative to the bottom-right anchor as (-usedX, -usedY).
    return col_index - single.H3M_MASK_ANCHOR_X, row_index - single.H3M_MASK_ANCHOR_Y


def build_homm3_movement_index(alignment: dict[str, Any]) -> dict[int, dict[str, list[dict[str, Any]]]]:
    by_node: dict[int, dict[str, list[dict[str, Any]]]] = {}
    entities = [
        entity
        for entity in alignment["alignment"]["globalObjectProperties"]["propEntities"]
        if isinstance(entity, dict) and entity.get("sourceLayer") == single.SOURCE_LAYER
    ]
    for entity in entities:
        source_x = entity.get("sourceX")
        source_y = entity.get("sourceY")
        if not isinstance(source_x, int) or not isinstance(source_y, int):
            raise ValueError(f"HoMM3 entity missing source coordinates: {entity}")
        block_mask = require_h3_mask(entity, "templateBlockMask")
        visit_mask = require_h3_mask(entity, "templateVisitMask")
        summary = compact_homm3_entity(entity)
        for row_index in range(single.H3M_MASK_HEIGHT):
            for col_index in range(single.H3M_MASK_WIDTH):
                dx, dy = h3_raw_mask_offset(row_index, col_index)
                section_source_x = source_x + dx
                section_source_y = source_y + dy
                try:
                    node = single.target_node_allowing_source_padding(section_source_x, section_source_y)
                except ValueError:
                    continue
                item = by_node.setdefault(node, {"blockers": [], "visitable": []})
                # VCMI ObjectTemplate::readMap treats blockMask bit 0 as BLOCKED and bit 1 as unblocked.
                if h3_mask_bit(block_mask, row_index, col_index) == 0:
                    item["blockers"].append({
                        **summary,
                        "sourceSection": [section_source_x, section_source_y],
                        "h3Offset": [dx, dy],
                        "maskPolicy": "vcmi_readMap_blockMask_bit_0_is_blocked",
                    })
                if h3_mask_bit(visit_mask, row_index, col_index) != 0:
                    item["visitable"].append({
                        **summary,
                        "sourceSection": [section_source_x, section_source_y],
                        "h3Offset": [dx, dy],
                        "maskPolicy": "vcmi_readMap_visitMask_bit_1_is_visitable",
                    })
    return by_node


def pathing_class(in_domain: bool, water_domain: bool, object_blocked: bool, visitable_destination: bool = False, pathability_known: bool = True) -> str:
    if not in_domain:
        return "source_padding"
    domain = "water" if water_domain else "land"
    if not pathability_known:
        state = "unknown"
    elif object_blocked and visitable_destination:
        state = "visitable_blocked"
    else:
        state = "blocked" if object_blocked else "pathable"
    return f"{domain}_{state}"


def homm3_pathability(cell: dict[str, Any], movement_index: dict[int, dict[str, list[dict[str, Any]]]]) -> dict[str, Any]:
    terrain = cell.get("terrain") if isinstance(cell.get("terrain"), dict) else {}
    source = terrain.get("source") if isinstance(terrain.get("source"), dict) else {}
    in_source_bounds = source.get("inSourceBounds") is True
    h3_terrain = source.get("h3Terrain")
    h3_river = source.get("h3River")
    water_domain = bool(in_source_bounds and h3_terrain == 8)
    movement = movement_index.get(int(cell["node"]), {"blockers": [], "visitable": []})
    blockers = list(movement.get("blockers") or [])
    visit_markers = list(movement.get("visitable") or [])
    anchor_markers: list[dict[str, Any]] = []
    visual_mask_section_count = 0
    for obj in cell.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        section = obj.get("section") if isinstance(obj.get("section"), dict) else {}
        section_role = section.get("sectionRole")
        if section_role == "mask_section":
            visual_mask_section_count += 1
        if section_role == "anchor_marker":
            anchor_markers.append(compact_object(obj))
    object_blocked = bool(blockers)
    visitable_destination = bool(visit_markers)
    effective_pathable = bool(in_source_bounds and (not object_blocked or visitable_destination))
    return {
        "inSourceBounds": in_source_bounds,
        "source": source,
        "terrainId": h3_terrain if isinstance(h3_terrain, int) else None,
        "riverId": h3_river if isinstance(h3_river, int) else None,
        "domain": "padding" if not in_source_bounds else ("water" if water_domain else "land"),
        "objectBlocked": object_blocked,
        "blockerCount": len(blockers),
        "visitMarkerCount": len(visit_markers),
        "anchorMarkerCount": len(anchor_markers),
        "visualMaskSectionCount": visual_mask_section_count,
        "blockers": blockers,
        "visitMarkers": visit_markers[:10],
        "landPathable": bool(not water_domain and effective_pathable),
        "waterPathable": bool(water_domain and effective_pathable),
        "clearPathable": bool(in_source_bounds and not object_blocked),
        "visitableDestination": visitable_destination,
        "pathingClass": pathing_class(in_source_bounds, water_domain, object_blocked, visitable_destination),
        "proofSource": "vcmi_h3m_template_blockMask_bit_0_blocked_visitMask_bit_1_visitable_plus_terrain8_water_domain",
    }

def olden_water_domain(terrain: dict[str, Any]) -> bool:
    tile_id = terrain.get("tilesMap")
    water_id = terrain.get("waterMap")
    return tile_id in set(single.NATIVE_WATER_TILE_CODES) or water_id == single.VANILLA_OCEAN_WATER_ID


def olden_pathability(cell: dict[str, Any]) -> dict[str, Any]:
    terrain = cell.get("terrain") if isinstance(cell.get("terrain"), dict) else {}
    water_domain = olden_water_domain(terrain)
    blockers: list[dict[str, Any]] = []
    native_size_unknown: list[dict[str, Any]] = []
    explicit_point_anchors: list[dict[str, Any]] = []
    native_size_sections = 0
    for obj in cell.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        section = obj.get("section") if isinstance(obj.get("section"), dict) else {}
        footprint_source = section.get("footprintSource")
        if section.get("occupied") is True:
            blockers.append(compact_object(obj))
        if footprint_source == UNKNOWN_NATIVE_SIZE_FOOTPRINT_SOURCE:
            native_size_unknown.append(compact_object(obj))
        elif footprint_source == EXPLICIT_POINT_ANCHOR_FOOTPRINT_SOURCE:
            explicit_point_anchors.append(compact_object(obj))
        elif footprint_source in {NATIVE_OBJECT_CONFIG_FOOTPRINT_SOURCE, NATIVE_GENERATOR_FOOTPRINT_SOURCE}:
            native_size_sections += 1
    object_blocked = bool(blockers)
    pathability_known = bool(object_blocked or not native_size_unknown)
    if pathability_known:
        land_pathable: bool | None = bool(not water_domain and not object_blocked)
        water_pathable: bool | None = bool(water_domain and not object_blocked)
    else:
        land_pathable = None if not water_domain else False
        water_pathable = None if water_domain else False
    return {
        "terrain": terrain,
        "domain": "water" if water_domain else "land",
        "objectBlocked": object_blocked,
        "blockerCount": len(blockers),
        "nativeSizeUnknownCount": len(native_size_unknown),
        "explicitPointAnchorCount": len(explicit_point_anchors),
        "nativeSizeSectionCount": native_size_sections,
        "blockers": blockers,
        "nativeSizeUnknownObjects": native_size_unknown,
        "explicitPointAnchors": explicit_point_anchors[:10],
        "landPathable": land_pathable,
        "waterPathable": water_pathable,
        "pathingClass": pathing_class(True, water_domain, object_blocked, pathability_known=pathability_known),
        "pathabilityKnown": pathability_known,
        "pathabilityUnknownReason": None if pathability_known else "native_size_missing_on_unblocked_cell",
        "proofSource": "olden_generated_terrain_water_domain_plus_object_config_nodes_value_1",
    }


def comparison_for_cell(homm3: dict[str, Any], olden: dict[str, Any]) -> dict[str, Any]:
    source_comparable = homm3["inSourceBounds"]
    mismatch_kinds: list[str] = []
    if source_comparable:
        functional_pathability_matches = (
            homm3["landPathable"] == olden["landPathable"]
            and homm3["waterPathable"] == olden["waterPathable"]
        )
        if not functional_pathability_matches:
            if homm3["domain"] != olden["domain"]:
                mismatch_kinds.append("domain")
            if homm3["objectBlocked"] != olden["objectBlocked"]:
                mismatch_kinds.append("object_blocking")
            if homm3["landPathable"] != olden["landPathable"]:
                mismatch_kinds.append("land_pathable")
            if homm3["waterPathable"] != olden["waterPathable"]:
                mismatch_kinds.append("water_pathable")
            if homm3["pathingClass"] != olden["pathingClass"]:
                mismatch_kinds.append("pathing_class")
        if not olden["pathabilityKnown"]:
            mismatch_kinds.append("olden_pathability_unknown")
    return {
        "sourceComparable": source_comparable,
        "domainMatches": (not source_comparable) or homm3["domain"] == olden["domain"],
        "objectBlockingMatches": (not source_comparable) or homm3["objectBlocked"] == olden["objectBlocked"],
        "landPathableMatches": (not source_comparable) or homm3["landPathable"] == olden["landPathable"],
        "waterPathableMatches": (not source_comparable) or homm3["waterPathable"] == olden["waterPathable"],
        "pathingClassMatches": (not source_comparable) or homm3["pathingClass"] == olden["pathingClass"],
        "oldenPathabilityKnown": olden["pathabilityKnown"],
        "mismatchKinds": mismatch_kinds,
    }


def mismatch_entry(cell: dict[str, Any]) -> dict[str, Any]:
    homm3 = cell["homm3"]
    olden = cell["olden"]
    return {
        "node": cell["node"],
        "x": cell["x"],
        "y": cell["y"],
        "source": homm3["source"],
        "mismatchKinds": cell["comparison"]["mismatchKinds"],
        "homm3": {
            "domain": homm3["domain"],
            "objectBlocked": homm3["objectBlocked"],
            "landPathable": homm3["landPathable"],
            "waterPathable": homm3["waterPathable"],
            "pathingClass": homm3["pathingClass"],
            "blockerCount": homm3["blockerCount"],
            "blockers": homm3["blockers"][:10],
        },
        "olden": {
            "domain": olden["domain"],
            "objectBlocked": olden["objectBlocked"],
            "landPathable": olden["landPathable"],
            "waterPathable": olden["waterPathable"],
            "pathingClass": olden["pathingClass"],
            "pathabilityKnown": olden["pathabilityKnown"],
            "blockerCount": olden["blockerCount"],
            "nativeSizeUnknownCount": olden["nativeSizeUnknownCount"],
            "blockers": olden["blockers"][:10],
            "nativeSizeUnknownObjects": olden["nativeSizeUnknownObjects"][:10],
        },
    }


def is_pathable(row: dict[str, Any]) -> bool:
    return row.get("landPathable") is True or row.get("waterPathable") is True


def mismatch_direction(homm3: dict[str, Any], olden: dict[str, Any]) -> str:
    homm3_pathable = is_pathable(homm3)
    olden_pathable = is_pathable(olden)
    if olden.get("pathabilityKnown") is not True:
        return "olden_unknown"
    if olden_pathable and not homm3_pathable:
        return "olden_more_open"
    if homm3_pathable and not olden_pathable:
        return "olden_more_restrictive"
    if homm3.get("domain") != olden.get("domain"):
        return "domain_changed_same_pathability"
    if homm3.get("objectBlocked") != olden.get("objectBlocked"):
        return "blocking_changed_same_pathability"
    return "classification_only"


def counter_rows(counter: Counter[str], total: int, limit: int | None = None, share_field: str = "share") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    items = counter.most_common(limit)
    for key, count in items:
        rows.append({
            "key": key,
            "count": count,
            share_field: round(count / total, 6) if total else 0.0,
        })
    return rows


def top_nested_counter_rows(counters: dict[str, Counter[str]], limit: int = 10, share_field: str = "share") -> dict[str, list[dict[str, Any]]]:
    return {key: counter_rows(counter, sum(counter.values()), limit, share_field) for key, counter in sorted(counters.items())}


def blocker_key(row: dict[str, Any], preferred: str) -> str:
    value = row.get(preferred)
    if value is not None:
        return str(value)
    sid = row.get("sid")
    if sid is not None:
        return str(sid)
    animation = row.get("templateAnimation")
    if animation is not None:
        return str(animation)
    object_id = row.get("templateObjectId")
    if object_id is not None:
        subtype = row.get("templateSubtype")
        return f"object:{object_id}:subtype:{subtype}"
    return f"id:{row.get('id')}"


def build_statistical_summary(mismatch_cells: list[dict[str, Any]], source_comparable_count: int) -> dict[str, Any]:
    direction_histogram: Counter[str] = Counter()
    transition_histogram: Counter[str] = Counter()
    domain_transition_histogram: Counter[str] = Counter()
    direction_by_domain_histogram: Counter[str] = Counter()
    mismatch_kind_histogram: Counter[str] = Counter()
    mismatch_kind_combination_histogram: Counter[str] = Counter()
    homm3_blocker_histogram: Counter[str] = Counter()
    homm3_blocker_source_key_histogram: Counter[str] = Counter()
    olden_blocker_histogram: Counter[str] = Counter()
    unknown_olden_sid_histogram: Counter[str] = Counter()
    homm3_blockers_by_direction: dict[str, Counter[str]] = {}
    homm3_blocker_source_keys_by_direction: dict[str, Counter[str]] = {}
    olden_blockers_by_direction: dict[str, Counter[str]] = {}
    unknown_sids_by_direction: dict[str, Counter[str]] = {}

    for mismatch in mismatch_cells:
        homm3 = mismatch["homm3"]
        olden = mismatch["olden"]
        comparison = mismatch.get("comparison") if isinstance(mismatch.get("comparison"), dict) else None
        if not isinstance(comparison, dict) or not isinstance(comparison.get("mismatchKinds"), list):
            raise ValueError("statistical summary requires full mismatch cells with comparison.mismatchKinds")
        mismatch_kinds = comparison["mismatchKinds"]
        direction = mismatch_direction(homm3, olden)
        direction_histogram[direction] += 1
        transition_histogram[f"{homm3['pathingClass']} -> {olden['pathingClass']}"] += 1
        domain_transition = f"{homm3['domain']} -> {olden['domain']}"
        domain_transition_histogram[domain_transition] += 1
        direction_by_domain_histogram[f"{domain_transition} / {direction}"] += 1
        mismatch_kind_combination_histogram["+".join(sorted(str(kind) for kind in mismatch_kinds))] += 1
        for kind in mismatch_kinds:
            mismatch_kind_histogram[str(kind)] += 1
        for blocker in homm3.get("blockers") or []:
            key = blocker_key(blocker, "templateAnimation")
            homm3_blocker_histogram[key] += 1
            homm3_blockers_by_direction.setdefault(direction, Counter())[key] += 1
            source_key = blocker_key(blocker, "sourceKey")
            homm3_blocker_source_key_histogram[source_key] += 1
            homm3_blocker_source_keys_by_direction.setdefault(direction, Counter())[source_key] += 1
        for blocker in olden.get("blockers") or []:
            key = blocker_key(blocker, "sid")
            olden_blocker_histogram[key] += 1
            olden_blockers_by_direction.setdefault(direction, Counter())[key] += 1
        for unknown in olden.get("nativeSizeUnknownObjects") or []:
            key = blocker_key(unknown, "sid")
            unknown_olden_sid_histogram[key] += 1
            unknown_sids_by_direction.setdefault(direction, Counter())[key] += 1

    total = len(mismatch_cells)
    return {
        "sourceComparableCellCount": source_comparable_count,
        "mismatchCellCount": total,
        "mismatchRateOfSourceComparableCells": round(total / source_comparable_count, 6) if source_comparable_count else 0.0,
        "directionHistogram": dict(direction_histogram.most_common()),
        "directionRows": counter_rows(direction_histogram, total, share_field="shareOfMismatchCells"),
        "pathingClassTransitionHistogram": dict(transition_histogram.most_common()),
        "pathingClassTransitionRows": counter_rows(transition_histogram, total, 20, "shareOfMismatchCells"),
        "domainTransitionHistogram": dict(domain_transition_histogram.most_common()),
        "directionByDomainHistogram": dict(direction_by_domain_histogram.most_common()),
        "directionByDomainRows": counter_rows(direction_by_domain_histogram, total, 20, "shareOfMismatchCells"),
        "mismatchKindHistogram": dict(mismatch_kind_histogram.most_common()),
        "mismatchKindCombinationHistogram": dict(mismatch_kind_combination_histogram.most_common()),
        "mismatchKindCombinationRows": counter_rows(mismatch_kind_combination_histogram, total, 20, "shareOfMismatchCells"),
        "topHomm3BlockerSections": counter_rows(homm3_blocker_histogram, sum(homm3_blocker_histogram.values()), 20, "shareOfOccurrences"),
        "topHomm3BlockerSourceKeys": counter_rows(homm3_blocker_source_key_histogram, sum(homm3_blocker_source_key_histogram.values()), 20, "shareOfOccurrences"),
        "topOldenBlockerSections": counter_rows(olden_blocker_histogram, sum(olden_blocker_histogram.values()), 20, "shareOfOccurrences"),
        "unknownOldenSizeSids": counter_rows(unknown_olden_sid_histogram, sum(unknown_olden_sid_histogram.values()), 20, "shareOfOccurrences"),
        "topHomm3BlockerSectionsByDirection": top_nested_counter_rows(homm3_blockers_by_direction, share_field="shareOfOccurrences"),
        "topHomm3BlockerSourceKeysByDirection": top_nested_counter_rows(homm3_blocker_source_keys_by_direction, share_field="shareOfOccurrences"),
        "topOldenBlockerSectionsByDirection": top_nested_counter_rows(olden_blockers_by_direction, share_field="shareOfOccurrences"),
        "unknownOldenSizeSidsByDirection": top_nested_counter_rows(unknown_sids_by_direction, share_field="shareOfOccurrences"),
    }


def build_pathability_artifact() -> dict[str, Any]:
    homm3_grid = read_json(tile_grid.HOMM3_SURFACE_GRID_PATH)
    olden_grid = read_json(tile_grid.OLDEN_SINGLE_LAYER_GRID_PATH)
    alignment = read_json(single.ALIGNMENT_PATH)
    homm3_movement_index = build_homm3_movement_index(alignment)
    rows: list[list[dict[str, Any]]] = []
    stats: Counter[str] = Counter()
    mismatch_histogram: Counter[str] = Counter()
    mismatches: list[dict[str, Any]] = []
    mismatch_cells_for_summary: list[dict[str, Any]] = []
    unknown_cells: list[dict[str, Any]] = []
    for y in range(single.OLDEN_HEIGHT):
        row: list[dict[str, Any]] = []
        for x in range(single.OLDEN_WIDTH):
            h3_cell = homm3_grid["rows"][y][x]
            olden_cell = olden_grid["rows"][y][x]
            if h3_cell["node"] != olden_cell["node"]:
                raise ValueError(f"grid node mismatch at {x},{y}: {h3_cell['node']} != {olden_cell['node']}")
            homm3 = homm3_pathability(h3_cell, homm3_movement_index)
            olden = olden_pathability(olden_cell)
            comparison = comparison_for_cell(homm3, olden)
            cell = {
                "x": x,
                "y": y,
                "node": h3_cell["node"],
                "homm3": homm3,
                "olden": olden,
                "comparison": comparison,
            }
            row.append(cell)
            stats["cellCount"] += 1
            if comparison["sourceComparable"]:
                stats["sourceComparableCellCount"] += 1
            else:
                stats["sourcePaddingCellCount"] += 1
            stats[f"homm3.{homm3['pathingClass']}"] += 1
            stats[f"olden.{olden['pathingClass']}"] += 1
            if homm3["landPathable"]:
                stats["homm3LandPathableCount"] += 1
            if homm3["waterPathable"]:
                stats["homm3WaterPathableCount"] += 1
            if olden["landPathable"]:
                stats["oldenLandPathableTotalCount"] += 1
            if olden["waterPathable"]:
                stats["oldenWaterPathableTotalCount"] += 1
            if comparison["sourceComparable"] and olden["landPathable"]:
                stats["oldenLandPathableComparableCount"] += 1
            if comparison["sourceComparable"] and olden["waterPathable"]:
                stats["oldenWaterPathableComparableCount"] += 1
            if not olden["pathabilityKnown"] and comparison["sourceComparable"]:
                unknown_cells.append(mismatch_entry(cell))
            if comparison["mismatchKinds"]:
                entry = mismatch_entry(cell)
                mismatches.append(entry)
                mismatch_cells_for_summary.append(cell)
                for kind in comparison["mismatchKinds"]:
                    mismatch_histogram[kind] += 1
        rows.append(row)
    stats_payload = {
        **dict(stats.most_common()),
        "mismatchCount": len(mismatches),
        "unknownOldenPathabilityCellCount": len(unknown_cells),
        "mismatchKindHistogram": dict(mismatch_histogram.most_common()),
    }
    statistical_summary = build_statistical_summary(mismatch_cells_for_summary, stats_payload["sourceComparableCellCount"])
    return {
        "schema": SCHEMA,
        "status": STATUS,
        "mapSid": single.MAP_SID,
        "proofBoundary": "source/static/generated-artifact pathability prediction; native runtime pathfinder behavior remains unvalidated",
        "inputs": {
            "homm3Grid": str(tile_grid.HOMM3_SURFACE_GRID_PATH),
            "oldenGrid": str(tile_grid.OLDEN_SINGLE_LAYER_GRID_PATH),
            "alignment": str(single.ALIGNMENT_PATH),
        },
        "coordinateSystem": homm3_grid["coordinateSystem"],
        "pathabilityModel": {
            "homm3": "land is source terrain != 8; water is source terrain == 8; object blocking comes from VCMI-compatible H3M template blockMask bit 0; visitMask bit 1 marks a visitable destination",
            "olden": "water is native water tile ids 18-22 or waterMap 18; object blocking comes from ObjectConfig.nodes value 1; unblocked native rows with no size and no explicit point-anchor policy make pathabilityKnown=false and pathable fields null for that domain",
            "comparison": "mismatchKinds are emitted only when landPathable or waterPathable differ; HoMM3 visitable_blocked vs Olden pathable classification-only deltas are excluded",
            "homm3PrimarySource": "VCMI ObjectTemplate::readMap: blockMask bit 0 is BLOCKED; visitMask bit 1 is VISITABLE",
            "runtimeProofStatus": "runtime_unvalidated_static_prediction",
        },
        "rows": rows,
        "mismatches": mismatches,
        "unknownOldenPathabilityCells": unknown_cells,
        "stats": stats_payload,
        "statisticalSummary": statistical_summary,
        "silentFallbacksUsed": False,
    }


def append_count_table(
    lines: list[str],
    title: str,
    rows: list[dict[str, Any]],
    key_header: str,
    limit: int = 10,
    share_field: str = "shareOfMismatchCells",
    share_header: str = "Share of mismatch cells",
) -> None:
    lines.extend(["", title, "", f"| {key_header} | Count | {share_header} |", "| --- | ---: | ---: |"])
    for row in rows[:limit]:
        lines.append(f"| `{row['key']}` | {row['count']} | {row[share_field]:.1%} |")


def write_report(artifact: dict[str, Any]) -> None:
    stats = artifact["stats"]
    summary = artifact["statisticalSummary"]
    lines = [
        "# Homecoming Pathability Grid",
        "",
        f"Schema: `{SCHEMA}`",
        f"Status: `{STATUS}`",
        "",
        "## Artifacts",
        f"- Pathability grid: `{OUTPUT_PATH}`",
        f"- HoMM3 tile-object grid: `{tile_grid.HOMM3_SURFACE_GRID_PATH}`",
        f"- Olden tile-object grid: `{tile_grid.OLDEN_SINGLE_LAYER_GRID_PATH}`",
        "",
        "## Summary",
        f"- Source-comparable cells: {stats['sourceComparableCellCount']}",
        f"- Source padding cells: {stats['sourcePaddingCellCount']}",
        f"- HoMM3 land pathable cells: {stats['homm3LandPathableCount']}",
        f"- Olden land pathable cells in source area: {stats['oldenLandPathableComparableCount']}",
        f"- HoMM3 water pathable cells: {stats['homm3WaterPathableCount']}",
        f"- Olden water pathable cells in source area: {stats['oldenWaterPathableComparableCount']}",
        f"- Pathability mismatch cells: {stats['mismatchCount']}",
        f"- Unknown Olden pathability cells: {stats['unknownOldenPathabilityCellCount']}",
        f"- Mismatch kinds: {stats['mismatchKindHistogram']}",
        "",
        "## Difference Statistics",
        f"- Mismatch rate within source area: {summary['mismatchCellCount']} / {summary['sourceComparableCellCount']} ({summary['mismatchRateOfSourceComparableCells']:.1%})",
        f"- Direction histogram: {summary['directionHistogram']}",
        f"- Domain transitions: {summary['domainTransitionHistogram']}",
    ]
    append_count_table(lines, "### Mismatch-Kind Combinations", summary["mismatchKindCombinationRows"], "Combination")
    append_count_table(lines, "### Direction", summary["directionRows"], "Direction")
    append_count_table(lines, "### Direction By Domain", summary["directionByDomainRows"], "Domain / direction")
    append_count_table(lines, "### Pathing-Class Transitions", summary["pathingClassTransitionRows"], "Transition")
    append_count_table(lines, "### Top HoMM3 Blocker Sections", summary["topHomm3BlockerSections"], "HoMM3 blocker", share_field="shareOfOccurrences", share_header="Share of blocker-section occurrences")
    append_count_table(lines, "### Top HoMM3 Blocker Source Keys", summary["topHomm3BlockerSourceKeys"], "HoMM3 sourceKey", share_field="shareOfOccurrences", share_header="Share of blocker-section occurrences")
    append_count_table(lines, "### Top Olden Blocker Sections", summary["topOldenBlockerSections"], "Olden blocker", share_field="shareOfOccurrences", share_header="Share of blocker-section occurrences")
    append_count_table(lines, "### Unknown Olden Size SIDs", summary["unknownOldenSizeSids"], "Olden SID", share_field="shareOfOccurrences", share_header="Share of unknown-anchor occurrences")
    if summary["topHomm3BlockerSectionsByDirection"].get("olden_more_open"):
        append_count_table(lines, "### HoMM3 Blockers When Olden Is More Open", summary["topHomm3BlockerSectionsByDirection"]["olden_more_open"], "HoMM3 blocker", share_field="shareOfOccurrences", share_header="Share of this direction's blocker-section occurrences")
    if summary["topHomm3BlockerSourceKeysByDirection"].get("olden_more_open"):
        append_count_table(lines, "### HoMM3 Source Keys When Olden Is More Open", summary["topHomm3BlockerSourceKeysByDirection"]["olden_more_open"], "HoMM3 sourceKey", share_field="shareOfOccurrences", share_header="Share of this direction's blocker-section occurrences")
    if summary["topOldenBlockerSectionsByDirection"].get("olden_more_restrictive"):
        append_count_table(lines, "### Olden Blockers When Olden Is More Restrictive", summary["topOldenBlockerSectionsByDirection"]["olden_more_restrictive"], "Olden blocker", share_field="shareOfOccurrences", share_header="Share of this direction's blocker-section occurrences")
    lines.extend([
        "",
        "## Proof Boundary",
        artifact["proofBoundary"],
    ])
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[2], type=Path)
    args = parser.parse_args()
    expected_root = Path(__file__).resolve().parents[2].resolve()
    if args.repo_root.resolve() != expected_root:
        raise ValueError(f"--repo-root must point to this checkout: {expected_root}")
    artifact = build_pathability_artifact()
    write_json(OUTPUT_PATH, artifact)
    write_report(artifact)
    stats = artifact["stats"]
    print(f"generated {OUTPUT_PATH}")
    print(
        f"mismatchCells={stats['mismatchCount']} "
        f"unknownOldenPathabilityCells={stats['unknownOldenPathabilityCellCount']} "
        f"homm3Land={stats['homm3LandPathableCount']} oldenLand={stats['oldenLandPathableComparableCount']} "
        f"homm3Water={stats['homm3WaterPathableCount']} oldenWater={stats['oldenWaterPathableComparableCount']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
