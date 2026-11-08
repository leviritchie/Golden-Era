#!/usr/bin/env python3
"""Validate the Homecoming Olden object knowledge artifact."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_ROOT = REPO_ROOT / "experiments" / "campaign_port_poc"
sys.path.insert(0, str(CAMPAIGN_ROOT))

import build_homecoming_olden_object_knowledge as knowledge_builder
import build_homecoming_single_layer_map as single
import build_homecoming_tile_object_grid as tile_grid

EXPECTED_MISSING_SIZE_CLASSES = {
    "missing_native_size_anchor_only",
    "not_in_native_core_zip",
    "nodes_without_size",
    "generator_building_size_without_object_size",
}
EXPECTED_ANCHOR_ONLY_USED_SIDS: set[str] = set()
EXPECTED_EXPLICIT_POINT_ANCHOR_USED_SIDS = {
    "dirt_stones_1",
    "flowers_1",
    "flowers_2",
    "fx_map_light",
    "grass_1",
    "grass_snow_1",
    "grass_stones_1",
    "mushrooms_1",
    "mushrooms_2",
    "mushrooms_3",
    "mushrooms_4",
    "snow_stones_1",
    "water_reed_1",
}
EXPECTED_PATHABILITY_OVERLAY_USED_SIDS = {
    single.HOMM3_PATHING_BLOCKER_SID,
    "homm3_pathing_visual_34041aab52_pool_snow_small_1",
    "homm3_pathing_visual_4b985051a3_wind_rose",
    "homm3_pathing_visual_4fea46cd84_mountain_water_small_1",
    "homm3_pathing_visual_636899a358_college_of_wonder",
    "homm3_pathing_visual_7ca0d70191_chest",
    "homm3_pathing_visual_7fcfc34baa_mountain_snow_small_1",
    "homm3_pathing_visual_8fd16068ee_pool_small",
    "homm3_pathing_visual_9c53e37738_pinetree_snow_1",
    "homm3_pathing_visual_d22fb0234e_mountain_green_small_1",
    "homm3_pathing_visual_e0577b6108_pinetree_1",
}
EXPECTED_NATIVE_MISSING_SIZE_USED_SIDS = EXPECTED_ANCHOR_ONLY_USED_SIDS - EXPECTED_EXPLICIT_POINT_ANCHOR_USED_SIDS


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
        [sys.executable, str(repo_root / "experiments" / "campaign_port_poc" / "build_homecoming_olden_object_knowledge.py"), "--repo-root", str(repo_root)],
        cwd=repo_root,
        check=True,
    )


def validate_summary(artifact: dict[str, Any], errors: list[str]) -> None:
    require(artifact.get("schema") == knowledge_builder.SCHEMA, f"schema mismatch: {artifact.get('schema')}", errors)
    require(artifact.get("status") == knowledge_builder.STATUS, f"status mismatch: {artifact.get('status')}", errors)
    require(artifact.get("silentFallbacksUsed") is False, "artifact must explicitly report silentFallbacksUsed=false", errors)
    sources = artifact.get("sources") if isinstance(artifact.get("sources"), dict) else {}
    require(sources.get("mapSid") == single.MAP_SID, f"mapSid mismatch: {sources.get('mapSid')}", errors)
    require(sources.get("oldenGrid") == str(tile_grid.OLDEN_SINGLE_LAYER_GRID_PATH), "Olden grid source path drift", errors)
    require(sources.get("diff") == str(tile_grid.DIFF_PATH), "tile diff source path drift", errors)

    core = artifact.get("coreObjectFootprintSummary") if isinstance(artifact.get("coreObjectFootprintSummary"), dict) else {}
    usage = artifact.get("homecomingOldenUsageSummary") if isinstance(artifact.get("homecomingOldenUsageSummary"), dict) else {}
    diff = artifact.get("diffKnowledgeSummary") if isinstance(artifact.get("diffKnowledgeSummary"), dict) else {}
    holes = artifact.get("knownHoles") if isinstance(artifact.get("knownHoles"), dict) else {}

    raw_count = core.get("coreRawObjectRowCount")
    unique_count = core.get("coreUniqueObjectIdCount")
    require(isinstance(raw_count, int) and raw_count > 0, "core raw object row count must be positive", errors)
    require(isinstance(unique_count, int) and unique_count > 0, "core unique object ID count must be positive", errors)
    if isinstance(raw_count, int) and isinstance(unique_count, int):
        require(raw_count >= unique_count, "core raw row count must be greater than or equal to unique object ID count", errors)
    require(isinstance(core.get("missingNativeSizeCount"), int) and core["missingNativeSizeCount"] > 0, "missing native size count must be positive", errors)
    require(isinstance(usage.get("usedSidCount"), int) and usage["usedSidCount"] > 0, "used SID count must be positive", errors)
    require(isinstance(usage.get("objectInstanceCount"), int) and usage["objectInstanceCount"] > 0, "object instance count must be positive", errors)
    require(diff.get("terrainMismatchCount") == 0, f"terrain mismatch drift: {diff.get('terrainMismatchCount')}", errors)
    require(usage.get("usedMissingNativeSizeSidCount") == len(usage.get("usedMissingNativeSizeSids") or []), "used missing-size SID count mismatch", errors)
    require(set(usage.get("usedMissingNativeSizeSids") or []) == EXPECTED_ANCHOR_ONLY_USED_SIDS, f"unexpected used missing-size SIDs: {usage.get('usedMissingNativeSizeSids')}", errors)
    used_sids = {
        str(row.get("sid"))
        for row in (artifact.get("usedOldenObjects") or [])
        if isinstance(row, dict) and isinstance(row.get("sid"), str)
    }
    require(EXPECTED_PATHABILITY_OVERLAY_USED_SIDS.issubset(used_sids), f"missing expected pathability overlay SIDs from usage: {sorted(EXPECTED_PATHABILITY_OVERLAY_USED_SIDS - used_sids)}", errors)
    require(usage.get("usedDuplicateNativeCoreRowCount") == 0, f"used duplicate native Core row count must remain zero: {usage.get('usedDuplicateNativeCoreRowCount')}", errors)

    hole_rows = holes.get("usedOldenSidsMissingNativeSize") if isinstance(holes.get("usedOldenSidsMissingNativeSize"), list) else []
    require(len(hole_rows) == len(EXPECTED_ANCHOR_ONLY_USED_SIDS), "known hole row count does not match expected anchor-only SID count", errors)
    for row in hole_rows:
        if not isinstance(row, dict):
            errors.append(f"known hole row must be an object: {row}")
            continue
        sid = row.get("sid")
        require(sid in EXPECTED_ANCHOR_ONLY_USED_SIDS, f"unexpected known-hole SID: {sid}", errors)
        require(row.get("footprintClass") in EXPECTED_MISSING_SIZE_CLASSES, f"{sid} is not an explicit missing-size class: {row.get('footprintClass')}", errors)
        section_roles = row.get("sectionRoleHistogram") if isinstance(row.get("sectionRoleHistogram"), dict) else {}
        footprint_sources = row.get("footprintSourceHistogram") if isinstance(row.get("footprintSourceHistogram"), dict) else {}
        covered_count = row.get("coveredCellCount")
        instance_count = row.get("objectInstanceCount")
        require(covered_count == instance_count, f"{sid} missing-size objects must remain anchor-only in the grid", errors)
        if sid in EXPECTED_PATHABILITY_OVERLAY_USED_SIDS:
            if sid == single.HOMM3_PATHING_BLOCKER_SID:
                require(footprint_sources.get("native_object_config_size_grid", 0) == covered_count, f"{sid} must use native overlay size grid sections", errors)
                require(section_roles.get("native_size_grid_section", 0) == covered_count, f"{sid} native size-grid section count drifted", errors)
            else:
                require(single.is_homm3_pathing_visual_sid(sid), f"{sid} must be a translator pathing visual clone SID", errors)
                require(footprint_sources.get("native_object_config_size_grid", 0) == covered_count, f"{sid} must use native overlay size grid sections", errors)
        elif sid in EXPECTED_EXPLICIT_POINT_ANCHOR_USED_SIDS:
            require(footprint_sources.get("explicit_point_anchor_without_native_size", 0) == covered_count, f"{sid} must stay an explicit point-anchor no-native-size SID", errors)
            require(section_roles.get("native_size_grid_section", 0) == covered_count, f"{sid} explicit point-anchor section count drifted", errors)
        elif sid in EXPECTED_NATIVE_MISSING_SIZE_USED_SIDS:
            require(footprint_sources.get("native_config_missing_size_anchor_only", 0) == covered_count, f"{sid} must stay a native-config missing-size anchor-only SID", errors)
            require(section_roles.get("anchor_only_missing_native_size", 0) == covered_count, f"{sid} anchor-only missing-size section count drifted", errors)
        else:
            errors.append(f"{sid} is not assigned to a validated missing-size handling policy")


def validate_recomputed(artifact: dict[str, Any], errors: list[str]) -> None:
    try:
        expected = knowledge_builder.build_artifact()
    except Exception as exc:
        errors.append(f"cannot recompute knowledge artifact: {exc}")
        return
    require(artifact == expected, "Olden object knowledge artifact is stale or differs from recomputed Core.zip/grid evidence", errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    errors: list[str] = []
    maybe_generate(repo_root, args.skip_generate)

    artifact = read_json(repo_root / knowledge_builder.OUTPUT_PATH, errors)
    if artifact:
        validate_summary(artifact, errors)
        validate_recomputed(artifact, errors)

    if errors:
        print("Homecoming Olden object knowledge contract validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Homecoming Olden object knowledge contract validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
