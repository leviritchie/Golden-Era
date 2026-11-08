#!/usr/bin/env python3
"""Summarize Olden object footprint knowledge exposed by Homecoming grids."""

from __future__ import annotations

import argparse
import json
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import build_homecoming_single_layer_map as single
import build_homecoming_tile_object_grid as tile_grid
import port_homecoming_poc as poc

SCHEMA = "homm3.homecoming_olden_object_knowledge.v0"
STATUS = "generated_artifact_validated_runtime_unvalidated"
OUT_ROOT = single.BASE_OUT_ROOT / "olden_object_knowledge"
OUTPUT_PATH = OUT_ROOT / "homecoming.olden_object_knowledge.json"
REPORT_PATH = OUT_ROOT / "HOMECOMING_OLDEN_OBJECT_KNOWLEDGE.md"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_core_map_object_rows() -> dict[str, list[dict[str, Any]]]:
    rows_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as core:
        for name in sorted(core.namelist()):
            if not (name.startswith("DB/map/objects/") and name.endswith(".json")):
                continue
            doc = json.loads(core.read(name).decode("utf-8-sig"))
            rows = doc.get("array") if isinstance(doc, dict) else None
            if not isinstance(rows, list):
                raise ValueError(f"Core map-object member has no array rows: {name}")
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                    raise ValueError(f"Core map-object row in {name} has no string id: {row}")
                item = dict(row)
                item["_coreMember"] = name
                rows_by_id[item["id"]].append(item)
    alignment_path = single.OUT_ROOT / "core_overlay" / Path(single.HOMM3_PATHABILITY_ALIGNMENT_OBJECT_MEMBER)
    if alignment_path.exists():
        doc = read_json(alignment_path)
        rows = doc.get("array") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            raise ValueError(f"pathability alignment overlay has no array rows: {alignment_path}")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                raise ValueError(f"pathability alignment overlay row has no string id: {row}")
            item = dict(row)
            item["_coreMember"] = single.HOMM3_PATHABILITY_ALIGNMENT_OBJECT_MEMBER
            rows_by_id[item["id"]] = [item]
    return {sid: rows for sid, rows in sorted(rows_by_id.items())}


def used_missing_native_size_row(row: dict[str, Any]) -> bool:
    sid = str(row.get("sid"))
    if sid == single.HOMM3_PATHING_BLOCKER_SID or single.is_homm3_pathing_visual_sid(sid):
        return False
    if sid in single.POINT_ANCHOR_WITHOUT_NATIVE_FOOTPRINT_SIDS:
        footprint_sources = row.get("footprintSourceHistogram") if isinstance(row.get("footprintSourceHistogram"), dict) else {}
        if footprint_sources.get("explicit_point_anchor_without_native_size"):
            return False
    return row["footprintClass"] in {
        "missing_native_size_anchor_only",
        "not_in_native_core_zip",
        "nodes_without_size",
        "generator_building_size_without_object_size",
    }

def footprint_summary(rows: list[dict[str, Any]] | None, sid: str) -> dict[str, Any]:
    if not rows:
        return {
            "sid": sid,
            "source": "not_in_native_core_zip",
            "footprintClass": "not_in_native_core_zip",
            "sizeX": None,
            "sizeZ": None,
            "sizeGridCellCount": None,
            "nodesPresent": False,
            "nodesValidForSize": False,
            "occupiedNodeCount": None,
            "nodeValueHistogram": {},
        }
    if len(rows) != 1:
        return {
            "sid": sid,
            "source": "duplicate_native_core_rows",
            "duplicateSources": [str(row.get("_coreMember")) for row in rows],
            "duplicateRowCount": len(rows),
            "duplicateTags": sorted({str(row.get("tag")) for row in rows}),
            "duplicateBiomes": sorted({str(row.get("biome")) for row in rows}),
            "footprintClass": "duplicate_native_core_rows",
            "sizeX": None,
            "sizeZ": None,
            "sizeGridCellCount": None,
            "nodesPresent": False,
            "nodesValidForSize": False,
            "occupiedNodeCount": None,
            "nodeValueHistogram": {},
        }
    row = rows[0]
    size_x = row.get("sizeX")
    size_z = row.get("sizeZ")
    nodes = row.get("nodes")
    generator = row.get("generatorConfig")
    has_size = isinstance(size_x, int) and isinstance(size_z, int) and size_x > 0 and size_z > 0
    generator_size_x = generator.get("buildingSizeX") if isinstance(generator, dict) else None
    generator_size_z = generator.get("buildingSizeZ") if isinstance(generator, dict) else None
    has_generator_size = isinstance(generator_size_x, int) and isinstance(generator_size_z, int)
    nodes_present = isinstance(nodes, list)
    size_grid_cell_count = size_x * size_z if has_size else None
    nodes_valid = bool(has_size and nodes_present and len(nodes) == size_grid_cell_count)
    node_histogram: dict[str, int] = {}
    occupied_count: int | None = None
    if nodes_valid:
        counter = Counter(str(value) for value in nodes)
        node_histogram = dict(counter.most_common())
        occupied_count = sum(1 for value in nodes if value == 1)
    if has_size and nodes_valid and occupied_count and occupied_count > 0:
        footprint_class = "size_grid_with_occupied_nodes"
    elif has_size and nodes_valid:
        footprint_class = "size_grid_with_no_occupied_nodes"
    elif has_size and nodes_present:
        footprint_class = "size_grid_invalid_nodes_length"
    elif has_size:
        footprint_class = "size_grid_no_nodes"
    elif has_generator_size:
        footprint_class = "generator_building_size_without_object_size"
    elif nodes_present:
        footprint_class = "nodes_without_size"
    else:
        footprint_class = "missing_native_size_anchor_only"
    return {
        "sid": sid,
        "source": row.get("_coreMember"),
        "tag": row.get("tag"),
        "biome": row.get("biome"),
        "isInteractable": row.get("isInteractable"),
        "canBeMirrored": row.get("canBeMirrored"),
        "prefabCount": len(row.get("prefs") or []) if isinstance(row.get("prefs"), list) else 0,
        "footprintClass": footprint_class,
        "sizeX": size_x if isinstance(size_x, int) else None,
        "sizeZ": size_z if isinstance(size_z, int) else None,
        "sizeGridCellCount": size_grid_cell_count,
        "nodesPresent": nodes_present,
        "nodesValidForSize": nodes_valid,
        "occupiedNodeCount": occupied_count,
        "nodeValueHistogram": node_histogram,
        "generatorBuildingSize": [generator_size_x, generator_size_z] if has_generator_size else None,
    }


def used_olden_sections_by_sid(olden_grid: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_sid: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "sectionRoleHistogram": Counter(),
            "footprintSourceHistogram": Counter(),
            "nodeValueHistogram": Counter(),
            "objectIds": set(),
            "coveredNodes": set(),
            "exampleSections": [],
        }
    )
    for row in olden_grid.get("rows") or []:
        for cell in row:
            if not isinstance(cell, dict):
                continue
            for obj in cell.get("objects") or []:
                sid = obj.get("sid")
                if not isinstance(sid, str):
                    continue
                item = by_sid[sid]
                item["objectIds"].add(int(obj["id"]))
                item["coveredNodes"].add(int(cell["node"]))
                section = obj.get("section") if isinstance(obj, dict) else {}
                role = str(section.get("sectionRole"))
                item["sectionRoleHistogram"][role] += 1
                item["footprintSourceHistogram"][str(section.get("footprintSource"))] += 1
                item["nodeValueHistogram"][str(section.get("nodeValue"))] += 1
                if len(item["exampleSections"]) < 5:
                    item["exampleSections"].append({
                        "id": obj.get("id"),
                        "node": cell.get("node"),
                        "anchor": obj.get("anchor"),
                        "section": section,
                    })
    normalized: dict[str, dict[str, Any]] = {}
    for sid, item in by_sid.items():
        normalized[sid] = {
            "objectInstanceCount": len(item["objectIds"]),
            "coveredCellCount": len(item["coveredNodes"]),
            "sectionRoleHistogram": dict(item["sectionRoleHistogram"].most_common()),
            "footprintSourceHistogram": dict(item["footprintSourceHistogram"].most_common()),
            "nodeValueHistogram": dict(item["nodeValueHistogram"].most_common()),
            "objectIdRange": [min(item["objectIds"]), max(item["objectIds"])] if item["objectIds"] else None,
            "exampleSections": item["exampleSections"],
        }
    return normalized


def group_common_mismatches_by_olden_sid(diff: dict[str, Any]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "missingNodeCount": 0, "extraNodeCount": 0, "examples": []})
    for row in diff.get("commonObjectFootprintMismatches") or []:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("oldenSid"))
        item = grouped[sid]
        missing = row.get("missingNodesInOlden") if isinstance(row.get("missingNodesInOlden"), list) else []
        extra = row.get("extraNodesInOlden") if isinstance(row.get("extraNodesInOlden"), list) else []
        item["count"] += 1
        item["missingNodeCount"] += len(missing)
        item["extraNodeCount"] += len(extra)
        if len(item["examples"]) < 5:
            item["examples"].append({
                "id": row.get("id"),
                "sourceKey": row.get("sourceKey"),
                "templateObjectId": row.get("templateObjectId"),
                "templateAnimation": row.get("templateAnimation"),
                "homm3CoveredCellCount": row.get("homm3CoveredCellCount"),
                "oldenCoveredCellCount": row.get("oldenCoveredCellCount"),
                "missingNodeCount": len(missing),
                "extraNodeCount": len(extra),
            })
    return {sid: grouped[sid] for sid in sorted(grouped)}


def build_artifact() -> dict[str, Any]:
    olden_grid = read_json(tile_grid.OLDEN_SINGLE_LAYER_GRID_PATH)
    diff = read_json(tile_grid.DIFF_PATH)
    core_rows = read_core_map_object_rows()
    used_by_sid = used_olden_sections_by_sid(olden_grid)
    core_raw_row_count = sum(len(rows) for rows in core_rows.values())
    all_core_footprints = [footprint_summary(row, sid) for sid, row in sorted(core_rows.items())]
    used_summaries: list[dict[str, Any]] = []
    for sid in sorted(used_by_sid):
        footprint = footprint_summary(core_rows.get(sid), sid)
        used_summaries.append({**footprint, **used_by_sid[sid]})

    core_class_histogram = Counter(row["footprintClass"] for row in all_core_footprints)
    core_tag_histogram = Counter(str(row.get("tag")) for row in all_core_footprints)
    used_class_histogram = Counter(row["footprintClass"] for row in used_summaries)
    used_duplicate_native_core_rows = [row for row in used_summaries if row["footprintClass"] == "duplicate_native_core_rows"]
    used_section_role_histogram: Counter[str] = Counter()
    used_node_value_histogram: Counter[str] = Counter()
    used_footprint_source_histogram: Counter[str] = Counter()
    for row in used_summaries:
        used_section_role_histogram.update(row.get("sectionRoleHistogram") or {})
        used_node_value_histogram.update(row.get("nodeValueHistogram") or {})
        used_footprint_source_histogram.update(row.get("footprintSourceHistogram") or {})

    used_missing_native_size = [row for row in used_summaries if used_missing_native_size_row(row)]
    core_missing_native_size = [
        row for row in all_core_footprints
        if row["footprintClass"] in {"missing_native_size_anchor_only", "nodes_without_size", "generator_building_size_without_object_size"}
    ]
    core_duplicate_native_rows = [row for row in all_core_footprints if row["footprintClass"] == "duplicate_native_core_rows"]
    common_mismatch_by_sid = group_common_mismatches_by_olden_sid(diff)

    artifact = {
        "schema": SCHEMA,
        "status": STATUS,
        "proofBoundary": "source/static/generated-artifact only; runtime object rendering and pathing exactness remain unvalidated",
        "sources": {
            "coreZip": str(poc.OLDEN_CORE_ZIP),
            "oldenGrid": str(tile_grid.OLDEN_SINGLE_LAYER_GRID_PATH),
            "diff": str(tile_grid.DIFF_PATH),
            "mapSid": single.MAP_SID,
        },
        "learnedFacts": [
            "Olden generated maps place objects as grouped sid/ids/nodes/rotations/levels arrays; node is the top-left/anchor cell for the ObjectConfig footprint grid.",
            "For Core ObjectConfig rows with sizeX/sizeZ, every size-grid cell can be represented as a visual section; nodes value 1 is the currently validated occupied-footprint evidence.",
            "Rows without usable sizeX/sizeZ cannot safely be expanded to multi-cell sections; Homecoming diagnostics separate native-config missing-size anchors from explicit point-anchor no-footprint policies.",
            "The Homecoming single-layer terrain projection and generated Olden terrain arrays currently match exactly in the tile-object diff.",
        ],
        "coreObjectFootprintSummary": {
            "coreRawObjectRowCount": core_raw_row_count,
            "coreUniqueObjectIdCount": len(all_core_footprints),
            "duplicateNativeCoreIdCount": len(core_duplicate_native_rows),
            "duplicateNativeCoreIdExamples": core_duplicate_native_rows[:40],
            "footprintClassHistogram": dict(core_class_histogram.most_common()),
            "tagHistogram": dict(core_tag_histogram.most_common()),
            "missingNativeSizeCount": len(core_missing_native_size),
            "missingNativeSizeExamples": core_missing_native_size[:40],
        },
        "homecomingOldenUsageSummary": {
            "usedSidCount": len(used_summaries),
            "objectInstanceCount": (olden_grid.get("stats") or {}).get("objectInstanceCount"),
            "coveredCellCount": (olden_grid.get("stats") or {}).get("occupiedCellCount"),
            "footprintClassHistogram": dict(used_class_histogram.most_common()),
            "sectionRoleHistogram": dict(used_section_role_histogram.most_common()),
            "footprintSourceHistogram": dict(used_footprint_source_histogram.most_common()),
            "nodeValueHistogram": dict(used_node_value_histogram.most_common()),
            "usedMissingNativeSizeSidCount": len(used_missing_native_size),
            "usedMissingNativeSizeSids": [row["sid"] for row in used_missing_native_size],
            "usedDuplicateNativeCoreRowCount": len(used_duplicate_native_core_rows),
        },
        "diffKnowledgeSummary": {
            "terrainMismatchCount": diff.get("terrainMismatchCount"),
            "sourceOnlyObjectCount": diff.get("sourceOnlyObjectCount"),
            "oldenOnlyObjectCount": diff.get("oldenOnlyObjectCount"),
            "commonObjectFootprintMismatchCount": diff.get("commonObjectFootprintMismatchCount"),
            "commonFootprintMismatchByOldenSid": common_mismatch_by_sid,
        },
        "usedOldenObjects": used_summaries,
        "knownHoles": {
            "usedOldenSidsMissingNativeSize": used_missing_native_size,
            "coreRowsMissingNativeSize": core_missing_native_size,
            "sourceOnlyObjects": diff.get("sourceOnlyObjects") or [],
            "oldenOnlyObjects": diff.get("oldenOnlyObjects") or [],
        },
        "silentFallbacksUsed": False,
    }
    return artifact


def write_report(artifact: dict[str, Any]) -> None:
    usage = artifact["homecomingOldenUsageSummary"]
    core = artifact["coreObjectFootprintSummary"]
    diff = artifact["diffKnowledgeSummary"]
    lines = [
        "# Homecoming Olden Object Knowledge",
        "",
        f"Schema: `{SCHEMA}`",
        f"Status: `{STATUS}`",
        "",
        "## What Changed",
        "- The tile-object grid now exposes object footprint knowledge as data instead of relying on visual runtime inspection.",
        "- Native Core rows with no declared size are explicit knowledge holes, not inferred 1x1 objects.",
        "",
        "## Core Object Footprints",
        f"- Core map object rows: {core['coreRawObjectRowCount']}",
        f"- Core unique object IDs: {core['coreUniqueObjectIdCount']}",
        f"- Core rows missing native size: {core['missingNativeSizeCount']}",
        f"- Duplicate native Core object IDs: {core['duplicateNativeCoreIdCount']}",
        f"- Footprint classes: {core['footprintClassHistogram']}",
        "",
        "## Homecoming Olden Usage",
        f"- Used Olden SIDs: {usage['usedSidCount']}",
        f"- Object instances: {usage['objectInstanceCount']}",
        f"- Used SIDs missing native size: {usage['usedMissingNativeSizeSidCount']} ({', '.join(usage['usedMissingNativeSizeSids'][:20])})",
        f"- Section roles: {usage['sectionRoleHistogram']}",
        f"- Footprint sources: {usage['footprintSourceHistogram']}",
        "",
        "## Diff Knowledge",
        f"- Terrain mismatches: {diff['terrainMismatchCount']}",
        f"- Source-only objects: {diff['sourceOnlyObjectCount']}",
        f"- Olden-only objects: {diff['oldenOnlyObjectCount']}",
        f"- Common object footprint mismatches: {diff['commonObjectFootprintMismatchCount']}",
        "",
        "## Proof Boundary",
        artifact["proofBoundary"],
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[2], type=Path)
    args = parser.parse_args()
    expected_root = Path(__file__).resolve().parents[2].resolve()
    if args.repo_root.resolve() != expected_root:
        raise ValueError(f"--repo-root must point to this checkout: {expected_root}")
    artifact = build_artifact()
    write_json(OUTPUT_PATH, artifact)
    write_report(artifact)
    usage = artifact["homecomingOldenUsageSummary"]
    print(f"generated {OUTPUT_PATH}")
    print(f"usedSids={usage['usedSidCount']} usedMissingNativeSizeSids={usage['usedMissingNativeSizeSidCount']} terrainMismatches={artifact['diffKnowledgeSummary']['terrainMismatchCount']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
