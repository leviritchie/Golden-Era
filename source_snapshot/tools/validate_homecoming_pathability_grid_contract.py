#!/usr/bin/env python3
"""Validate the Homecoming per-tile pathability grid artifact."""

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

import build_homecoming_pathability_grid as path_builder
import build_homecoming_single_layer_map as single
import build_homecoming_tile_object_grid as tile_grid

EXPECTED_UNKNOWN_OLDEN_PATHABILITY_CELL_COUNT = 0
EXPECTED_DIRECTION_HISTOGRAM = {
    "olden_more_restrictive": 61,
}
EXPECTED_DOMAIN_TRANSITION_HISTOGRAM = {
    "land -> land": 59,
    "water -> water": 2,
}
EXPECTED_DIRECTION_BY_DOMAIN_HISTOGRAM = {
    "land -> land / olden_more_restrictive": 59,
    "water -> water / olden_more_restrictive": 2,
}
EXPECTED_MISMATCH_KIND_COMBINATION_HISTOGRAM = {
    "land_pathable+object_blocking+pathing_class": 39,
    "land_pathable+pathing_class": 20,
    "object_blocking+pathing_class+water_pathable": 2,
}
EXPECTED_TOP_PATHING_CLASS_TRANSITIONS = {
    "land_pathable -> land_blocked": 39,
    "land_visitable_blocked -> land_blocked": 20,
    "water_pathable -> water_blocked": 2,
}
EXPECTED_TOP_HOMM3_MORE_OPEN_BLOCKERS: dict[str, int] = {}
EXPECTED_TOP_HOMM3_MORE_OPEN_SOURCE_KEYS: dict[str, int] = {}
EXPECTED_TOP_OLDEN_MORE_RESTRICTIVE_BLOCKERS = {
    "homm3_castle_city": 5,
    "mine_wood": 4,
    "windmill": 4,
    "barracks_homm3_castle_4": 4,
    "watchtower": 3,
}
EXPECTED_UNKNOWN_OLDEN_PATHABILITY_SIDS: set[str] = set()
EXPECTED_UNKNOWN_OLDEN_SIZE_SID_HISTOGRAM: dict[str, int] = {}


def read_json(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"missing JSON artifact: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"cannot read JSON {path}: {exc}")
        return {}


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def maybe_generate(repo_root: Path, skip_generate: bool) -> None:
    if skip_generate:
        return
    subprocess.run(
        [sys.executable, str(repo_root / "experiments" / "campaign_port_poc" / "build_homecoming_tile_object_grid.py"), "--repo-root", str(repo_root)],
        cwd=repo_root,
        check=True,
    )
    subprocess.run(
        [sys.executable, str(repo_root / "experiments" / "campaign_port_poc" / "build_homecoming_pathability_grid.py"), "--repo-root", str(repo_root)],
        cwd=repo_root,
        check=True,
    )


def cell_pathing_class(domain: str, object_blocked: bool, visitable_destination: bool = False, pathability_known: bool = True) -> str:
    if domain == "padding":
        return "source_padding"
    if not pathability_known:
        state = "unknown"
    elif object_blocked and visitable_destination:
        state = "visitable_blocked"
    else:
        state = "blocked" if object_blocked else "pathable"
    return f"{domain}_{state}"


def validate_homm3_mask_offset_contract(errors: list[str]) -> None:
    for row_index in range(single.H3M_MASK_HEIGHT):
        for col_index in range(single.H3M_MASK_WIDTH):
            mask = [0] * single.H3M_MASK_HEIGHT
            mask[row_index] = 1 << col_index
            expected = single.h3m_mask_offsets(mask)
            actual = {path_builder.h3_raw_mask_offset(row_index, col_index)}
            require(actual == expected, f"HoMM3 raw mask offset projection drift at row={row_index} col={col_index}: {actual} != {expected}", errors)


def validate_homm3_visit_projection(repo_root: Path, errors: list[str]) -> None:
    alignment = read_json(repo_root / single.ALIGNMENT_PATH, errors)
    if not alignment:
        return
    try:
        entities = alignment["alignment"]["globalObjectProperties"]["propEntities"]
    except Exception as exc:
        errors.append(f"cannot read alignment propEntities for HoMM3 visit projection: {exc}")
        return
    movement_index = path_builder.build_homm3_movement_index(alignment)
    actual: set[tuple[int, int]] = set()
    for node, buckets in movement_index.items():
        for marker in buckets.get("visitable") or []:
            if isinstance(marker, dict) and isinstance(marker.get("id"), int):
                actual.add((int(marker["id"]), int(node)))
    expected: set[tuple[int, int]] = set()
    for entity in entities:
        if not isinstance(entity, dict) or entity.get("sourceLayer") != single.SOURCE_LAYER:
            continue
        source_index = entity.get("sourceIndex")
        source_x = entity.get("sourceX")
        source_y = entity.get("sourceY")
        if not all(isinstance(value, int) for value in (source_index, source_x, source_y)):
            errors.append(f"HoMM3 entity missing visit-projection coordinates: {entity}")
            continue
        for dx, dy in single.source_visit_offsets(entity):
            try:
                node = single.target_node_allowing_source_padding(source_x + dx, source_y + dy)
            except ValueError:
                continue
            expected.add((int(source_index), node))
    require(actual == expected, f"HoMM3 visit mask projection drift: missing={sorted(expected - actual)[:10]} extra={sorted(actual - expected)[:10]}", errors)


def validate_cell_shape(cell: dict[str, Any], x: int, y: int, errors: list[str]) -> None:
    require(cell.get("x") == x and cell.get("y") == y, f"cell coordinate mismatch at {x},{y}: {cell}", errors)
    require(cell.get("node") == y * single.OLDEN_WIDTH + x, f"cell node mismatch at {x},{y}: {cell.get('node')}", errors)
    require(isinstance(cell.get("homm3"), dict), f"cell {x},{y} missing homm3 object", errors)
    require(isinstance(cell.get("olden"), dict), f"cell {x},{y} missing olden object", errors)
    require(isinstance(cell.get("comparison"), dict), f"cell {x},{y} missing comparison object", errors)


def validate_homm3_cell(homm3: dict[str, Any], comparison: dict[str, Any], x: int, y: int, errors: list[str]) -> None:
    in_source = homm3.get("inSourceBounds") is True
    domain = homm3.get("domain")
    object_blocked = homm3.get("objectBlocked") is True
    visitable_destination = homm3.get("visitableDestination") is True
    effective_pathable = in_source and (not object_blocked or visitable_destination)
    require(comparison.get("sourceComparable") is in_source, f"HoMM3 sourceComparable drift at {x},{y}", errors)
    require((homm3.get("blockerCount") or 0) == len(homm3.get("blockers") or []), f"HoMM3 blockerCount list mismatch at {x},{y}", errors)
    require(object_blocked == ((homm3.get("blockerCount") or 0) > 0), f"HoMM3 objectBlocked/count mismatch at {x},{y}", errors)
    require(visitable_destination == ((homm3.get("visitMarkerCount") or 0) > 0), f"HoMM3 visitable/count mismatch at {x},{y}", errors)
    require(homm3.get("clearPathable") is (in_source and not object_blocked), f"HoMM3 clearPathable formula drift at {x},{y}", errors)
    require(homm3.get("landPathable") is (domain == "land" and effective_pathable), f"HoMM3 landPathable formula drift at {x},{y}", errors)
    require(homm3.get("waterPathable") is (domain == "water" and effective_pathable), f"HoMM3 waterPathable formula drift at {x},{y}", errors)
    require(homm3.get("pathingClass") == cell_pathing_class(str(domain), object_blocked, visitable_destination), f"HoMM3 pathingClass formula drift at {x},{y}", errors)
    require(homm3.get("proofSource") == "vcmi_h3m_template_blockMask_bit_0_blocked_visitMask_bit_1_visitable_plus_terrain8_water_domain", f"HoMM3 proof source drift at {x},{y}", errors)


def validate_olden_cell(olden: dict[str, Any], x: int, y: int, errors: list[str]) -> None:
    domain = olden.get("domain")
    object_blocked = olden.get("objectBlocked") is True
    unknown_count = olden.get("nativeSizeUnknownCount") or 0
    pathability_known = bool(object_blocked or unknown_count == 0)
    if pathability_known:
        expected_land_pathable: bool | None = domain == "land" and not object_blocked
        expected_water_pathable: bool | None = domain == "water" and not object_blocked
        expected_unknown_reason = None
    else:
        expected_land_pathable = None if domain == "land" else False
        expected_water_pathable = None if domain == "water" else False
        expected_unknown_reason = "native_size_missing_on_unblocked_cell"
    require(domain in {"land", "water"}, f"Olden domain drift at {x},{y}: {domain}", errors)
    require((olden.get("blockerCount") or 0) == len(olden.get("blockers") or []), f"Olden blockerCount list mismatch at {x},{y}", errors)
    require(unknown_count == len(olden.get("nativeSizeUnknownObjects") or []), f"Olden nativeSizeUnknownCount list mismatch at {x},{y}", errors)
    require(object_blocked == ((olden.get("blockerCount") or 0) > 0), f"Olden objectBlocked/count mismatch at {x},{y}", errors)
    require(olden.get("pathabilityKnown") is pathability_known, f"Olden pathabilityKnown formula drift at {x},{y}", errors)
    require(olden.get("landPathable") == expected_land_pathable, f"Olden landPathable formula drift at {x},{y}", errors)
    require(olden.get("waterPathable") == expected_water_pathable, f"Olden waterPathable formula drift at {x},{y}", errors)
    require(olden.get("pathingClass") == cell_pathing_class(str(domain), object_blocked, pathability_known=pathability_known), f"Olden pathingClass formula drift at {x},{y}", errors)
    require(olden.get("pathabilityUnknownReason") == expected_unknown_reason, f"Olden pathabilityUnknownReason drift at {x},{y}", errors)
    require(olden.get("proofSource") == "olden_generated_terrain_water_domain_plus_object_config_nodes_value_1", f"Olden proof source drift at {x},{y}", errors)


def validate_comparison_cell(homm3: dict[str, Any], olden: dict[str, Any], comparison: dict[str, Any], x: int, y: int, errors: list[str]) -> None:
    source_comparable = homm3.get("inSourceBounds") is True
    expected_mismatch_kinds: list[str] = []
    if source_comparable:
        functional_pathability_matches = (
            homm3.get("landPathable") == olden.get("landPathable")
            and homm3.get("waterPathable") == olden.get("waterPathable")
        )
        if not functional_pathability_matches:
            if homm3.get("domain") != olden.get("domain"):
                expected_mismatch_kinds.append("domain")
            if homm3.get("objectBlocked") != olden.get("objectBlocked"):
                expected_mismatch_kinds.append("object_blocking")
            if homm3.get("landPathable") != olden.get("landPathable"):
                expected_mismatch_kinds.append("land_pathable")
            if homm3.get("waterPathable") != olden.get("waterPathable"):
                expected_mismatch_kinds.append("water_pathable")
            if homm3.get("pathingClass") != olden.get("pathingClass"):
                expected_mismatch_kinds.append("pathing_class")
        if olden.get("pathabilityKnown") is not True:
            expected_mismatch_kinds.append("olden_pathability_unknown")
    require(comparison.get("sourceComparable") is source_comparable, f"comparison sourceComparable drift at {x},{y}", errors)
    require(comparison.get("domainMatches") is ((not source_comparable) or homm3.get("domain") == olden.get("domain")), f"comparison domainMatches drift at {x},{y}", errors)
    require(comparison.get("objectBlockingMatches") is ((not source_comparable) or homm3.get("objectBlocked") == olden.get("objectBlocked")), f"comparison objectBlockingMatches drift at {x},{y}", errors)
    require(comparison.get("landPathableMatches") is ((not source_comparable) or homm3.get("landPathable") == olden.get("landPathable")), f"comparison landPathableMatches drift at {x},{y}", errors)
    require(comparison.get("waterPathableMatches") is ((not source_comparable) or homm3.get("waterPathable") == olden.get("waterPathable")), f"comparison waterPathableMatches drift at {x},{y}", errors)
    require(comparison.get("pathingClassMatches") is ((not source_comparable) or homm3.get("pathingClass") == olden.get("pathingClass")), f"comparison pathingClassMatches drift at {x},{y}", errors)
    require(comparison.get("oldenPathabilityKnown") is (olden.get("pathabilityKnown") is True), f"comparison oldenPathabilityKnown drift at {x},{y}", errors)
    require(comparison.get("mismatchKinds") == expected_mismatch_kinds, f"comparison mismatchKinds drift at {x},{y}: {comparison.get('mismatchKinds')} != {expected_mismatch_kinds}", errors)


def validate_rows(artifact: dict[str, Any], errors: list[str]) -> None:
    rows = artifact.get("rows")
    require(isinstance(rows, list) and len(rows) == single.OLDEN_HEIGHT, f"rows must be {single.OLDEN_HEIGHT} high", errors)
    if not isinstance(rows, list):
        return
    stats: Counter[str] = Counter()
    mismatch_histogram: Counter[str] = Counter()
    mismatch_count = 0
    unknown_count = 0
    unknown_sids: set[str] = set()
    for y, row in enumerate(rows):
        require(isinstance(row, list) and len(row) == single.OLDEN_WIDTH, f"row {y} must be {single.OLDEN_WIDTH} cells", errors)
        if not isinstance(row, list):
            continue
        for x, cell in enumerate(row):
            if not isinstance(cell, dict):
                errors.append(f"cell {x},{y} is not an object")
                continue
            validate_cell_shape(cell, x, y, errors)
            homm3 = cell.get("homm3") if isinstance(cell.get("homm3"), dict) else {}
            olden = cell.get("olden") if isinstance(cell.get("olden"), dict) else {}
            comparison = cell.get("comparison") if isinstance(cell.get("comparison"), dict) else {}
            validate_homm3_cell(homm3, comparison, x, y, errors)
            validate_olden_cell(olden, x, y, errors)
            validate_comparison_cell(homm3, olden, comparison, x, y, errors)
            stats["cellCount"] += 1
            if comparison.get("sourceComparable") is True:
                stats["sourceComparableCellCount"] += 1
            else:
                stats["sourcePaddingCellCount"] += 1
            stats[f"homm3.{homm3.get('pathingClass')}"] += 1
            stats[f"olden.{olden.get('pathingClass')}"] += 1
            if homm3.get("landPathable") is True:
                stats["homm3LandPathableCount"] += 1
            if homm3.get("waterPathable") is True:
                stats["homm3WaterPathableCount"] += 1
            if olden.get("landPathable") is True:
                stats["oldenLandPathableTotalCount"] += 1
            if olden.get("waterPathable") is True:
                stats["oldenWaterPathableTotalCount"] += 1
            if comparison.get("sourceComparable") is True and olden.get("landPathable") is True:
                stats["oldenLandPathableComparableCount"] += 1
            if comparison.get("sourceComparable") is True and olden.get("waterPathable") is True:
                stats["oldenWaterPathableComparableCount"] += 1
            if comparison.get("sourceComparable") is True and olden.get("pathabilityKnown") is not True:
                unknown_count += 1
                for obj in olden.get("nativeSizeUnknownObjects") or []:
                    if isinstance(obj, dict) and isinstance(obj.get("sid"), str):
                        unknown_sids.add(obj["sid"])
            mismatch_kinds = comparison.get("mismatchKinds") if isinstance(comparison.get("mismatchKinds"), list) else []
            if mismatch_kinds:
                mismatch_count += 1
                for kind in mismatch_kinds:
                    mismatch_histogram[str(kind)] += 1
    artifact_stats = artifact.get("stats") if isinstance(artifact.get("stats"), dict) else {}
    for key, value in stats.items():
        require(artifact_stats.get(key) == value, f"stats {key} mismatch: {artifact_stats.get(key)} != {value}", errors)
    require(artifact_stats.get("mismatchCount") == mismatch_count, f"mismatchCount stat mismatch: {artifact_stats.get('mismatchCount')} != {mismatch_count}", errors)
    require(artifact_stats.get("unknownOldenPathabilityCellCount") == unknown_count, f"unknownOldenPathabilityCellCount stat mismatch: {artifact_stats.get('unknownOldenPathabilityCellCount')} != {unknown_count}", errors)
    require(artifact_stats.get("mismatchKindHistogram") == dict(mismatch_histogram.most_common()), "mismatchKindHistogram stat mismatch", errors)
    require(stats.get("cellCount") == single.OLDEN_WIDTH * single.OLDEN_HEIGHT, "cell count formula drift", errors)
    require(stats.get("sourceComparableCellCount") == single.SOURCE_WIDTH * single.SOURCE_HEIGHT, "source comparable count drift", errors)
    require(stats.get("sourcePaddingCellCount") == single.OLDEN_WIDTH * single.OLDEN_HEIGHT - single.SOURCE_WIDTH * single.SOURCE_HEIGHT, "source padding count drift", errors)
    require(artifact_stats.get("unknownOldenPathabilityCellCount") == EXPECTED_UNKNOWN_OLDEN_PATHABILITY_CELL_COUNT, f"unknown Olden pathability cell count drift: {artifact_stats.get('unknownOldenPathabilityCellCount')}", errors)
    require(unknown_sids == EXPECTED_UNKNOWN_OLDEN_PATHABILITY_SIDS, f"unknown Olden pathability SID drift: {sorted(unknown_sids)}", errors)
    require((artifact_stats.get("homm3.land_visitable_blocked") or 0) > 0, "HoMM3 visitable-blocked land cells must remain explicitly represented", errors)
    require((artifact_stats.get("homm3.water_visitable_blocked") or 0) > 0, "HoMM3 visitable-blocked water cells must remain explicitly represented", errors)


def validate_summary(artifact: dict[str, Any], errors: list[str]) -> None:
    require(artifact.get("schema") == path_builder.SCHEMA, f"schema mismatch: {artifact.get('schema')}", errors)
    require(artifact.get("status") == path_builder.STATUS, f"status mismatch: {artifact.get('status')}", errors)
    require(artifact.get("mapSid") == single.MAP_SID, f"mapSid mismatch: {artifact.get('mapSid')}", errors)
    require(artifact.get("silentFallbacksUsed") is False, "artifact must explicitly report silentFallbacksUsed=false", errors)
    require("runtime pathfinder behavior remains unvalidated" in str(artifact.get("proofBoundary")), "proof boundary drift", errors)
    inputs = artifact.get("inputs") if isinstance(artifact.get("inputs"), dict) else {}
    require(inputs.get("homm3Grid") == str(tile_grid.HOMM3_SURFACE_GRID_PATH), "HoMM3 grid input path drift", errors)
    require(inputs.get("oldenGrid") == str(tile_grid.OLDEN_SINGLE_LAYER_GRID_PATH), "Olden grid input path drift", errors)
    require(inputs.get("alignment") == str(single.ALIGNMENT_PATH), "alignment input path drift", errors)
    coordinate = artifact.get("coordinateSystem") if isinstance(artifact.get("coordinateSystem"), dict) else {}
    require(coordinate.get("width") == single.OLDEN_WIDTH and coordinate.get("height") == single.OLDEN_HEIGHT, f"coordinate size mismatch: {coordinate}", errors)
    require(coordinate.get("sourceWidth") == single.SOURCE_WIDTH and coordinate.get("sourceHeight") == single.SOURCE_HEIGHT, f"source coordinate size mismatch: {coordinate}", errors)
    model = artifact.get("pathabilityModel") if isinstance(artifact.get("pathabilityModel"), dict) else {}
    require("blockMask bit 0" in str(model.get("homm3")) and "visitMask bit 1" in str(model.get("homm3")), "HoMM3 pathability model must document VCMI mask polarity", errors)
    require("ObjectConfig.nodes value 1" in str(model.get("olden")), "Olden pathability model must document native node occupancy", errors)
    require("pathabilityKnown=false" in str(model.get("olden")) and "fields null" in str(model.get("olden")), "Olden pathability model must document unknown tri-state handling", errors)
    require("landPathable or waterPathable differ" in str(model.get("comparison")), "comparison model must document functional-only mismatch policy", errors)
    require(model.get("runtimeProofStatus") == "runtime_unvalidated_static_prediction", f"runtime proof status drift: {model.get('runtimeProofStatus')}", errors)


def validate_lists(artifact: dict[str, Any], errors: list[str]) -> None:
    mismatches = artifact.get("mismatches") if isinstance(artifact.get("mismatches"), list) else []
    unknown = artifact.get("unknownOldenPathabilityCells") if isinstance(artifact.get("unknownOldenPathabilityCells"), list) else []
    stats = artifact.get("stats") if isinstance(artifact.get("stats"), dict) else {}
    require(stats.get("mismatchCount") == len(mismatches), "mismatchCount does not match mismatch list length", errors)
    require(stats.get("unknownOldenPathabilityCellCount") == len(unknown), "unknownOldenPathabilityCellCount does not match list length", errors)
    for row in unknown:
        if not isinstance(row, dict):
            errors.append(f"unknown Olden pathability row is not an object: {row}")
            continue
        require("olden_pathability_unknown" in (row.get("mismatchKinds") or []), f"unknown row missing mismatch kind: {row}", errors)
        olden = row.get("olden") if isinstance(row.get("olden"), dict) else {}
        require(olden.get("pathabilityKnown") is False, f"unknown row has pathabilityKnown true: {row}", errors)
        require((olden.get("nativeSizeUnknownCount") or 0) > 0, f"unknown row lacks native size evidence: {row}", errors)


def count_rows_to_dict(rows: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    if not isinstance(rows, list):
        return result
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("key"), str) and isinstance(row.get("count"), int):
            result[row["key"]] = row["count"]
    return result


def require_expected_subset(actual: dict[str, int], expected: dict[str, int], label: str, errors: list[str]) -> None:
    for key, count in expected.items():
        require(actual.get(key) == count, f"{label} drift for {key}: {actual.get(key)} != {count}", errors)


def summary_side_pathable(row: dict[str, Any]) -> bool:
    return row.get("landPathable") is True or row.get("waterPathable") is True


def summary_direction(homm3: dict[str, Any], olden: dict[str, Any]) -> str:
    homm3_pathable = summary_side_pathable(homm3)
    olden_pathable = summary_side_pathable(olden)
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


def summary_blocker_key(row: dict[str, Any], preferred: str) -> str:
    value = row.get(preferred)
    if value is not None:
        return str(value)
    for key in ("sid", "templateAnimation"):
        value = row.get(key)
        if value is not None:
            return str(value)
    object_id = row.get("templateObjectId")
    if object_id is not None:
        return f"object:{object_id}:subtype:{row.get('templateSubtype')}"
    return f"id:{row.get('id')}"


def recompute_summary_histograms_from_rows(artifact: dict[str, Any]) -> dict[str, Counter[str]]:
    counters: dict[str, Counter[str]] = {
        "directionHistogram": Counter(),
        "domainTransitionHistogram": Counter(),
        "directionByDomainHistogram": Counter(),
        "pathingClassTransitionHistogram": Counter(),
        "mismatchKindCombinationHistogram": Counter(),
        "topHomm3BlockerSections": Counter(),
        "topHomm3BlockerSourceKeys": Counter(),
        "topOldenBlockerSections": Counter(),
        "unknownOldenSizeSids": Counter(),
        "topHomm3BlockerSectionsByDirection.olden_more_open": Counter(),
        "topHomm3BlockerSourceKeysByDirection.olden_more_open": Counter(),
        "topOldenBlockerSectionsByDirection.olden_more_restrictive": Counter(),
    }
    for row in artifact.get("rows") or []:
        if not isinstance(row, list):
            continue
        for cell in row:
            if not isinstance(cell, dict):
                continue
            comparison = cell.get("comparison") if isinstance(cell.get("comparison"), dict) else {}
            mismatch_kinds = comparison.get("mismatchKinds") if isinstance(comparison.get("mismatchKinds"), list) else []
            if not mismatch_kinds:
                continue
            homm3 = cell.get("homm3") if isinstance(cell.get("homm3"), dict) else {}
            olden = cell.get("olden") if isinstance(cell.get("olden"), dict) else {}
            direction = summary_direction(homm3, olden)
            domain_transition = f"{homm3.get('domain')} -> {olden.get('domain')}"
            counters["directionHistogram"][direction] += 1
            counters["domainTransitionHistogram"][domain_transition] += 1
            counters["directionByDomainHistogram"][f"{domain_transition} / {direction}"] += 1
            counters["pathingClassTransitionHistogram"][f"{homm3.get('pathingClass')} -> {olden.get('pathingClass')}"] += 1
            counters["mismatchKindCombinationHistogram"]["+".join(sorted(str(kind) for kind in mismatch_kinds))] += 1
            for blocker in homm3.get("blockers") or []:
                if not isinstance(blocker, dict):
                    continue
                blocker_key = summary_blocker_key(blocker, "templateAnimation")
                source_key = summary_blocker_key(blocker, "sourceKey")
                counters["topHomm3BlockerSections"][blocker_key] += 1
                counters["topHomm3BlockerSourceKeys"][source_key] += 1
                if direction == "olden_more_open":
                    counters["topHomm3BlockerSectionsByDirection.olden_more_open"][blocker_key] += 1
                    counters["topHomm3BlockerSourceKeysByDirection.olden_more_open"][source_key] += 1
            for blocker in olden.get("blockers") or []:
                if not isinstance(blocker, dict):
                    continue
                blocker_key = summary_blocker_key(blocker, "sid")
                counters["topOldenBlockerSections"][blocker_key] += 1
                if direction == "olden_more_restrictive":
                    counters["topOldenBlockerSectionsByDirection.olden_more_restrictive"][blocker_key] += 1
            for unknown in olden.get("nativeSizeUnknownObjects") or []:
                if isinstance(unknown, dict):
                    counters["unknownOldenSizeSids"][summary_blocker_key(unknown, "sid")] += 1
    return counters


def validate_share_rows(rows: Any, denominator: int, share_field: str, forbidden_share_field: str, label: str, errors: list[str]) -> None:
    require(isinstance(rows, list), f"{label} rows must be a list", errors)
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            errors.append(f"{label} row must be an object: {row}")
            continue
        key = row.get("key")
        count = row.get("count")
        require(isinstance(key, str), f"{label} row key must be a string: {row}", errors)
        require(isinstance(count, int), f"{label} row count must be an integer: {row}", errors)
        require(share_field in row, f"{label} row missing {share_field}: {row}", errors)
        require(forbidden_share_field not in row, f"{label} row must not use {forbidden_share_field}: {row}", errors)
        if isinstance(count, int):
            expected = round(count / denominator, 6) if denominator else 0.0
            require(row.get(share_field) == expected, f"{label} share drift for {key}: {row.get(share_field)} != {expected}", errors)


def validate_statistical_summary(artifact: dict[str, Any], errors: list[str]) -> None:
    summary = artifact.get("statisticalSummary") if isinstance(artifact.get("statisticalSummary"), dict) else {}
    stats = artifact.get("stats") if isinstance(artifact.get("stats"), dict) else {}
    require(bool(summary), "artifact missing statisticalSummary", errors)
    if not summary:
        return
    source_cells = stats.get("sourceComparableCellCount")
    mismatch_count = stats.get("mismatchCount")
    require(summary.get("sourceComparableCellCount") == source_cells, "statisticalSummary sourceComparableCellCount mismatch", errors)
    require(summary.get("mismatchCellCount") == mismatch_count, "statisticalSummary mismatchCellCount mismatch", errors)
    expected_rate = round((mismatch_count or 0) / (source_cells or 1), 6) if source_cells else 0.0
    require(summary.get("mismatchRateOfSourceComparableCells") == expected_rate, f"statisticalSummary mismatch rate drift: {summary.get('mismatchRateOfSourceComparableCells')} != {expected_rate}", errors)
    recomputed = recompute_summary_histograms_from_rows(artifact)
    direction_histogram = summary.get("directionHistogram") if isinstance(summary.get("directionHistogram"), dict) else {}
    require(direction_histogram == dict(recomputed["directionHistogram"].most_common()), f"direction histogram does not match full row recompute: {direction_histogram}", errors)
    require(direction_histogram == EXPECTED_DIRECTION_HISTOGRAM, f"direction histogram drift: {direction_histogram}", errors)
    require(sum(int(value) for value in direction_histogram.values()) == mismatch_count, "direction histogram must sum to mismatch count", errors)
    require(count_rows_to_dict(summary.get("directionRows")) == direction_histogram, "directionRows must mirror directionHistogram", errors)
    validate_share_rows(summary.get("directionRows"), mismatch_count or 0, "shareOfMismatchCells", "shareOfOccurrences", "directionRows", errors)
    domain_histogram = summary.get("domainTransitionHistogram") if isinstance(summary.get("domainTransitionHistogram"), dict) else {}
    require(domain_histogram == dict(recomputed["domainTransitionHistogram"].most_common()), f"domain transition histogram does not match full row recompute: {domain_histogram}", errors)
    require(domain_histogram == EXPECTED_DOMAIN_TRANSITION_HISTOGRAM, f"domain transition histogram drift: {domain_histogram}", errors)
    require(sum(int(value) for value in domain_histogram.values()) == mismatch_count, "domain transition histogram must sum to mismatch count", errors)
    direction_by_domain = summary.get("directionByDomainHistogram") if isinstance(summary.get("directionByDomainHistogram"), dict) else {}
    require(direction_by_domain == dict(recomputed["directionByDomainHistogram"].most_common()), f"direction-by-domain histogram does not match full row recompute: {direction_by_domain}", errors)
    require(direction_by_domain == EXPECTED_DIRECTION_BY_DOMAIN_HISTOGRAM, f"direction-by-domain histogram drift: {direction_by_domain}", errors)
    require(count_rows_to_dict(summary.get("directionByDomainRows")) == direction_by_domain, "directionByDomainRows must mirror directionByDomainHistogram", errors)
    validate_share_rows(summary.get("directionByDomainRows"), mismatch_count or 0, "shareOfMismatchCells", "shareOfOccurrences", "directionByDomainRows", errors)
    transition_histogram = summary.get("pathingClassTransitionHistogram") if isinstance(summary.get("pathingClassTransitionHistogram"), dict) else {}
    require(transition_histogram == dict(recomputed["pathingClassTransitionHistogram"].most_common()), f"pathing class transition histogram does not match full row recompute: {transition_histogram}", errors)
    require(sum(int(value) for value in transition_histogram.values()) == mismatch_count, "pathing class transition histogram must sum to mismatch count", errors)
    require(count_rows_to_dict(summary.get("pathingClassTransitionRows")) == transition_histogram, "pathingClassTransitionRows must mirror pathingClassTransitionHistogram", errors)
    validate_share_rows(summary.get("pathingClassTransitionRows"), mismatch_count or 0, "shareOfMismatchCells", "shareOfOccurrences", "pathingClassTransitionRows", errors)
    require_expected_subset(transition_histogram, EXPECTED_TOP_PATHING_CLASS_TRANSITIONS, "pathing transition", errors)
    require(summary.get("mismatchKindHistogram") == stats.get("mismatchKindHistogram"), "summary mismatchKindHistogram must mirror stats", errors)
    combo_histogram = summary.get("mismatchKindCombinationHistogram") if isinstance(summary.get("mismatchKindCombinationHistogram"), dict) else {}
    require(combo_histogram == dict(recomputed["mismatchKindCombinationHistogram"].most_common()), f"mismatch kind combination histogram does not match full row recompute: {combo_histogram}", errors)
    require(combo_histogram == EXPECTED_MISMATCH_KIND_COMBINATION_HISTOGRAM, f"mismatch kind combination histogram drift: {combo_histogram}", errors)
    require(count_rows_to_dict(summary.get("mismatchKindCombinationRows")) == combo_histogram, "mismatchKindCombinationRows must mirror mismatchKindCombinationHistogram", errors)
    validate_share_rows(summary.get("mismatchKindCombinationRows"), mismatch_count or 0, "shareOfMismatchCells", "shareOfOccurrences", "mismatchKindCombinationRows", errors)
    unknown_rows = count_rows_to_dict(summary.get("unknownOldenSizeSids"))
    require(unknown_rows == dict(recomputed["unknownOldenSizeSids"].most_common()), f"unknown Olden size SID histogram does not match full row recompute: {unknown_rows}", errors)
    require(unknown_rows == EXPECTED_UNKNOWN_OLDEN_SIZE_SID_HISTOGRAM, f"unknown Olden size SID histogram drift: {unknown_rows}", errors)
    validate_share_rows(summary.get("topHomm3BlockerSections"), sum(recomputed["topHomm3BlockerSections"].values()), "shareOfOccurrences", "shareOfMismatchCells", "topHomm3BlockerSections", errors)
    validate_share_rows(summary.get("topHomm3BlockerSourceKeys"), sum(recomputed["topHomm3BlockerSourceKeys"].values()), "shareOfOccurrences", "shareOfMismatchCells", "topHomm3BlockerSourceKeys", errors)
    validate_share_rows(summary.get("topOldenBlockerSections"), sum(recomputed["topOldenBlockerSections"].values()), "shareOfOccurrences", "shareOfMismatchCells", "topOldenBlockerSections", errors)
    validate_share_rows(summary.get("unknownOldenSizeSids"), sum(recomputed["unknownOldenSizeSids"].values()), "shareOfOccurrences", "shareOfMismatchCells", "unknownOldenSizeSids", errors)
    h3_by_direction = summary.get("topHomm3BlockerSectionsByDirection") if isinstance(summary.get("topHomm3BlockerSectionsByDirection"), dict) else {}
    olden_by_direction = summary.get("topOldenBlockerSectionsByDirection") if isinstance(summary.get("topOldenBlockerSectionsByDirection"), dict) else {}
    require_expected_subset(count_rows_to_dict(summary.get("topHomm3BlockerSections")), dict(recomputed["topHomm3BlockerSections"].most_common(20)), "HoMM3 blocker table", errors)
    require_expected_subset(count_rows_to_dict(summary.get("topHomm3BlockerSourceKeys")), dict(recomputed["topHomm3BlockerSourceKeys"].most_common(20)), "HoMM3 sourceKey table", errors)
    require_expected_subset(count_rows_to_dict(summary.get("topOldenBlockerSections")), dict(recomputed["topOldenBlockerSections"].most_common(20)), "Olden blocker table", errors)
    validate_share_rows(h3_by_direction.get("olden_more_open") or [], sum(recomputed["topHomm3BlockerSectionsByDirection.olden_more_open"].values()), "shareOfOccurrences", "shareOfMismatchCells", "topHomm3BlockerSectionsByDirection.olden_more_open", errors)
    require_expected_subset(count_rows_to_dict(h3_by_direction.get("olden_more_open")), dict(recomputed["topHomm3BlockerSectionsByDirection.olden_more_open"].most_common(10)), "HoMM3 more-open blocker recompute", errors)
    require_expected_subset(count_rows_to_dict(h3_by_direction.get("olden_more_open")), EXPECTED_TOP_HOMM3_MORE_OPEN_BLOCKERS, "HoMM3 more-open blocker", errors)
    h3_source_keys_by_direction = summary.get("topHomm3BlockerSourceKeysByDirection") if isinstance(summary.get("topHomm3BlockerSourceKeysByDirection"), dict) else {}
    validate_share_rows(h3_source_keys_by_direction.get("olden_more_open") or [], sum(recomputed["topHomm3BlockerSourceKeysByDirection.olden_more_open"].values()), "shareOfOccurrences", "shareOfMismatchCells", "topHomm3BlockerSourceKeysByDirection.olden_more_open", errors)
    require_expected_subset(count_rows_to_dict(h3_source_keys_by_direction.get("olden_more_open")), dict(recomputed["topHomm3BlockerSourceKeysByDirection.olden_more_open"].most_common(10)), "HoMM3 more-open sourceKey recompute", errors)
    require_expected_subset(count_rows_to_dict(h3_source_keys_by_direction.get("olden_more_open")), EXPECTED_TOP_HOMM3_MORE_OPEN_SOURCE_KEYS, "HoMM3 more-open sourceKey", errors)
    validate_share_rows(olden_by_direction.get("olden_more_restrictive"), sum(recomputed["topOldenBlockerSectionsByDirection.olden_more_restrictive"].values()), "shareOfOccurrences", "shareOfMismatchCells", "topOldenBlockerSectionsByDirection.olden_more_restrictive", errors)
    require_expected_subset(count_rows_to_dict(olden_by_direction.get("olden_more_restrictive")), dict(recomputed["topOldenBlockerSectionsByDirection.olden_more_restrictive"].most_common(10)), "Olden more-restrictive blocker recompute", errors)
    require_expected_subset(count_rows_to_dict(olden_by_direction.get("olden_more_restrictive")), EXPECTED_TOP_OLDEN_MORE_RESTRICTIVE_BLOCKERS, "Olden more-restrictive blocker", errors)


def validate_recomputed(artifact: dict[str, Any], errors: list[str]) -> None:
    try:
        expected = path_builder.build_pathability_artifact()
    except Exception as exc:
        errors.append(f"cannot recompute pathability artifact: {exc}")
        return
    require(artifact == expected, "pathability artifact is stale or differs from recomputed HoMM3/Olden grid evidence", errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    errors: list[str] = []
    maybe_generate(repo_root, args.skip_generate)

    artifact = read_json(repo_root / path_builder.OUTPUT_PATH, errors)
    if artifact:
        validate_summary(artifact, errors)
        validate_homm3_mask_offset_contract(errors)
        validate_homm3_visit_projection(repo_root, errors)
        validate_rows(artifact, errors)
        validate_lists(artifact, errors)
        validate_statistical_summary(artifact, errors)
        validate_recomputed(artifact, errors)

    if errors:
        print("Homecoming pathability grid contract validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Homecoming pathability grid contract validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())