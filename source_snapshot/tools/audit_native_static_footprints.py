#!/usr/bin/env python3
"""Audit native footprints for non-removable buildings and scenery.

Resources, armies, and other interaction payloads are intentionally excluded.
This is a diagnostic model only: it does not alter object placement or map
generation.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
POC = ROOT / "experiments" / "campaign_port_poc"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(POC))

from audit_native_footprint_road_intersections import find_layered_ir, source_road_nodes
from audit_raw_translation_building_footprints import (
    DEFAULT_BATCH_MANIFEST,
    DEFAULT_CORE,
    find_ground_truth,
    is_building_like,
    load_core_configs,
    load_local_configs,
    load_mission_dirs,
    mission_envelope,
)
from native_footprint_model import model_native_footprint


def footprint_kind(config: dict[str, Any]) -> str | None:
    if is_building_like(config):
        return "building"
    if config.get("tag") == "Environment":
        nodes = config.get("nodes")
        size_x = config.get("sizeX")
        size_z = config.get("sizeZ")
        if isinstance(nodes, list) and isinstance(size_x, int) and isinstance(size_z, int):
            return "scenery"
    return None


def placement_key(placement: dict[str, Any]) -> Any:
    return placement.get("sourceKey") or (placement.get("h3") or {}).get("sourceKey")


def audit(repo_root: Path, core: Path, batch_manifest: Path | None, example_limit: int) -> dict[str, Any]:
    base_configs = load_core_configs(core)
    mission_dirs = load_mission_dirs(repo_root, batch_manifest)
    stats: Counter[str] = Counter()
    kind_instances: Counter[str] = Counter()
    kind_differences: Counter[str] = Counter()
    kind_native_cells: Counter[str] = Counter()
    kind_legacy_cells: Counter[str] = Counter()
    kind_native_only: Counter[str] = Counter()
    kind_legacy_only: Counter[str] = Counter()
    kind_native_road_instances: Counter[str] = Counter()
    kind_legacy_road_instances: Counter[str] = Counter()
    kind_native_road_cells: Counter[str] = Counter()
    kind_legacy_road_cells: Counter[str] = Counter()
    sid_differences: Counter[str] = Counter()
    sid_native_road: Counter[str] = Counter()
    unresolved: Counter[str] = Counter()
    envelopes: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    road_examples: list[dict[str, Any]] = []
    bashing_examples: list[dict[str, Any]] = []
    missing_ground_truth: list[str] = []
    missing_envelope: list[str] = []
    missing_road_ir: list[str] = []

    for mission_dir in mission_dirs:
        gt_path = find_ground_truth(mission_dir)
        if gt_path is None:
            missing_ground_truth.append(str(mission_dir))
            continue
        envelope = mission_envelope(mission_dir)
        if envelope is None:
            missing_envelope.append(str(mission_dir))
            continue
        width, height, envelope_meta = envelope
        envelopes[f"{width}x{height}"] += 1
        ir_path = find_layered_ir(mission_dir)
        road_nodes: set[int] = set()
        if ir_path is not None:
            road_nodes, road_status = source_road_nodes(ir_path)
            if road_status.get("status") != "road_projection_ready":
                missing_road_ir.append(str(mission_dir))
        else:
            missing_road_ir.append(str(mission_dir))

        payload = json.loads(gt_path.read_text(encoding="utf-8-sig"))
        local_configs = load_local_configs(base_configs, mission_dir)
        for placement in payload.get("placements") or []:
            if not isinstance(placement, dict) or placement.get("emitStatus") != "emitted":
                continue
            olden = placement.get("olden")
            if not isinstance(olden, dict):
                continue
            sid = olden.get("sid")
            config = local_configs.get(str(sid)) if isinstance(sid, str) else None
            if not isinstance(config, dict):
                continue
            tag = config.get("tag")
            if tag == "Environment":
                stats["emittedEnvironmentPlacements"] += 1
            kind = footprint_kind(config)
            if kind is None:
                continue
            stats[f"emitted{kind.title()}Placements"] += 1
            node = olden.get("node")
            rotation = olden.get("rotation", 0)
            object_id = olden.get("objectId")
            if not isinstance(node, int) or not isinstance(rotation, int) or not isinstance(object_id, int):
                stats[f"invalid{kind.title()}Placements"] += 1
                continue
            model = model_native_footprint(str(sid), config, node, rotation, width=width, height=height)
            kind_instances[kind] += 1
            kind_native_cells[kind] += len(model.occupied_cells)
            kind_legacy_cells[kind] += len(model.legacy_occupied_cells)
            if model.native_only_occupied_cells or model.legacy_only_occupied_cells:
                kind_differences[kind] += 1
                kind_native_only[kind] += len(model.native_only_occupied_cells)
                kind_legacy_only[kind] += len(model.legacy_only_occupied_cells)
                sid_differences[str(sid)] += 1
                if len(examples) < example_limit:
                    examples.append({
                        "mission": mission_dir.name,
                        "kind": kind,
                        "sourceKey": placement_key(placement),
                        "objectId": object_id,
                        "sid": str(sid),
                        "atlasWidth": width,
                        "atlasHeight": height,
                        "anchorNode": node,
                        "rotation": rotation,
                        "nativeOccupiedCells": sorted(model.occupied_cells),
                        "legacyOccupiedCells": sorted(model.legacy_occupied_cells),
                        "nativeOnlyOccupiedCells": sorted(model.native_only_occupied_cells),
                        "legacyOnlyOccupiedCells": sorted(model.legacy_only_occupied_cells),
                        "runtimeModelStatus": model.runtime_model_status,
                        "unresolved": list(model.unresolved),
                    })
            native_road = model.occupied_cells & road_nodes
            legacy_road = model.legacy_occupied_cells & road_nodes
            native_only_road = native_road - model.legacy_occupied_cells
            if native_road:
                kind_native_road_instances[kind] += 1
                kind_native_road_cells[kind] += len(native_road)
                sid_native_road[str(sid)] += 1
            if legacy_road:
                kind_legacy_road_instances[kind] += 1
                kind_legacy_road_cells[kind] += len(legacy_road)
            if native_only_road:
                row = {
                    "mission": mission_dir.name,
                    "kind": kind,
                    "sourceKey": placement_key(placement),
                    "objectId": object_id,
                    "sid": str(sid),
                    "atlasWidth": width,
                    "atlasHeight": height,
                    "anchorNode": node,
                    "rotation": rotation,
                    "nativeOnlyRoadCells": sorted(native_only_road),
                    "nativeOccupiedCells": sorted(model.occupied_cells),
                    "legacyOccupiedCells": sorted(model.legacy_occupied_cells),
                    "runtimeModelStatus": model.runtime_model_status,
                }
                if len(road_examples) < example_limit:
                    road_examples.append(row)
                if mission_dir.name == "bashing_skulls" and len(bashing_examples) < example_limit:
                    bashing_examples.append(row)
            for reason in model.unresolved:
                unresolved[f"{kind}:{reason}"] += 1

    return {
        "schema": "olden.raw_translation.native_static_footprint_audit.v1",
        "status": "static_candidate_audit_only",
        "proofBoundary": (
            "buildings are generator-backed interactable ObjectConfigs and scenery is Environment-tagged with a native nodes grid; "
            "resources and armies are excluded; native nodes use the recovered bvf projection; "
            "generator rectangles, presentation offsets, and final runtime pathfinder behavior remain separate"
        ),
        "core": str(core),
        "batchManifest": str(batch_manifest) if batch_manifest is not None else None,
        "missionCount": len(mission_dirs),
        "missingGroundTruth": missing_ground_truth,
        "missingEnvelope": missing_envelope,
        "missingRoadIr": missing_road_ir,
        "envelopeCounts": dict(envelopes),
        "stats": {
            **dict(stats),
            "modeledInstances": dict(kind_instances),
            "instancesWithNativeLegacyProjectionDifference": dict(kind_differences),
            "nativeOccupiedCells": dict(kind_native_cells),
            "legacyOccupiedCells": dict(kind_legacy_cells),
            "nativeOnlyOccupiedCells": dict(kind_native_only),
            "legacyOnlyOccupiedCells": dict(kind_legacy_only),
            "nativeRoadIntersectionInstances": dict(kind_native_road_instances),
            "legacyRoadIntersectionInstances": dict(kind_legacy_road_instances),
            "nativeRoadIntersectionCells": dict(kind_native_road_cells),
            "legacyRoadIntersectionCells": dict(kind_legacy_road_cells),
        },
        "topProjectionDifferenceSids": sid_differences.most_common(40),
        "topNativeRoadIntersectionSids": sid_native_road.most_common(40),
        "unresolvedReasons": unresolved.most_common(),
        "projectionDifferenceExamples": examples,
        "nativeOnlyRoadExamples": road_examples,
        "bashingSkullsExamples": bashing_examples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--batch-manifest", type=Path, default=DEFAULT_BATCH_MANIFEST)
    parser.add_argument("--without-batch", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--example-limit", type=int, default=50)
    args = parser.parse_args()
    batch_manifest = None if args.without_batch else args.batch_manifest.resolve()
    report = audit(args.repo_root.resolve(), args.core.resolve(), batch_manifest, max(0, args.example_limit))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "stats": report["stats"], "out": str(args.out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
