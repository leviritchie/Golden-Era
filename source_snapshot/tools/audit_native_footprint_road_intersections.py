#!/usr/bin/env python3
"""Find source-road cells covered by native building footprint candidates."""

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

from audit_raw_translation_building_footprints import (
    DEFAULT_BATCH_MANIFEST,
    DEFAULT_CORE,
    find_ground_truth,
    is_building_like,
    load_core_configs,
    load_local_configs,
    load_mission_dirs,
)
from native_footprint_model import model_native_footprint


VIEW_SECTION_SIZE = 16


def find_layered_ir(mission_dir: Path) -> Path | None:
    matches = sorted((mission_dir / "layered_ir").glob("*layered_map_ir.json"))
    return matches[0] if matches else None


def source_road_nodes(layered_ir: Path) -> tuple[set[int], dict[str, Any]]:
    """Project the source surface into the first layer of its emitted atlas."""
    payload = json.loads(layered_ir.read_text(encoding="utf-8-sig"))
    layers = [row for row in payload.get("layers") or [] if isinstance(row, dict)]
    surface = next((row for row in layers if row.get("sid") == "surface"), None)
    if not isinstance(surface, dict):
        return set(), {"status": "missing_surface_layer"}
    width = surface.get("width")
    height = surface.get("height")
    tiles = surface.get("tiles")
    if not isinstance(width, int) or not isinstance(height, int) or not isinstance(tiles, list):
        return set(), {"status": "invalid_surface_layer"}
    layer_count = len(layers)
    if layer_count <= 0:
        return set(), {"status": "invalid_layer_count"}

    layer_width = ((width + VIEW_SECTION_SIZE - 1) // VIEW_SECTION_SIZE) * VIEW_SECTION_SIZE
    layer_height = ((height + VIEW_SECTION_SIZE - 1) // VIEW_SECTION_SIZE) * VIEW_SECTION_SIZE
    raw_width = layer_width * layer_count
    raw_height = layer_height
    offset_x = (layer_width - width) // 2
    offset_y = (layer_height - height) // 2
    road_nodes: set[int] = set()
    for tile in tiles:
        if not isinstance(tile, dict) or not tile.get("road"):
            continue
        x = tile.get("x")
        y = tile.get("y")
        if not isinstance(x, int) or not isinstance(y, int):
            continue
        raw_x = x + offset_x
        raw_y = (height - 1 - y) + offset_y
        if 0 <= raw_x < layer_width and 0 <= raw_y < raw_height:
            road_nodes.add(raw_y * raw_width + raw_x)
    return road_nodes, {
        "status": "road_projection_ready",
        "sourceWidth": width,
        "sourceHeight": height,
        "layerCount": layer_count,
        "layerWidth": layer_width,
        "layerHeight": layer_height,
        "atlasWidth": raw_width,
        "atlasHeight": raw_height,
        "offsetX": offset_x,
        "offsetY": offset_y,
        "roadTileCount": len(road_nodes),
    }


def audit(repo_root: Path, core: Path, batch_manifest: Path | None, example_limit: int) -> dict[str, Any]:
    base_configs = load_core_configs(core)
    mission_dirs = load_mission_dirs(repo_root, batch_manifest)
    stats: Counter[str] = Counter()
    sid_native: Counter[str] = Counter()
    sid_legacy: Counter[str] = Counter()
    missing_ir: list[str] = []
    unsupported_ir: list[dict[str, Any]] = []
    examples: list[dict[str, Any]] = []
    bashing_examples: list[dict[str, Any]] = []

    for mission_dir in mission_dirs:
        gt_path = find_ground_truth(mission_dir)
        ir_path = find_layered_ir(mission_dir)
        if gt_path is None or ir_path is None:
            if gt_path is not None and ir_path is None:
                missing_ir.append(str(mission_dir))
            continue
        road_nodes, ir_status = source_road_nodes(ir_path)
        if ir_status.get("status") != "road_projection_ready":
            unsupported_ir.append({"mission": mission_dir.name, "path": str(ir_path), **ir_status})
            continue
        stats["missionsWithRoadProjection"] += 1
        stats["roadTiles"] += len(road_nodes)
        payload = json.loads(gt_path.read_text(encoding="utf-8-sig"))
        local_configs = load_local_configs(base_configs, mission_dir)
        width = int(ir_status["atlasWidth"])
        height = int(ir_status["atlasHeight"])
        for placement in payload.get("placements") or []:
            if not isinstance(placement, dict) or placement.get("emitStatus") != "emitted":
                continue
            olden = placement.get("olden")
            if not isinstance(olden, dict):
                continue
            sid = olden.get("sid")
            config = local_configs.get(str(sid)) if isinstance(sid, str) else None
            if not isinstance(config, dict) or not is_building_like(config):
                continue
            node = olden.get("node")
            rotation = olden.get("rotation", 0)
            if not isinstance(node, int) or not isinstance(rotation, int):
                continue
            model = model_native_footprint(str(sid), config, node, rotation, width=width, height=height)
            native_road = model.occupied_cells & road_nodes
            legacy_road = model.legacy_occupied_cells & road_nodes
            if native_road:
                stats["nativeRoadIntersectionInstances"] += 1
                stats["nativeRoadCells"] += len(native_road)
                sid_native[str(sid)] += 1
            if legacy_road:
                stats["legacyRoadIntersectionInstances"] += 1
                stats["legacyRoadCells"] += len(legacy_road)
                sid_legacy[str(sid)] += 1
            native_only_road = native_road - model.legacy_occupied_cells
            legacy_only_road = legacy_road - model.occupied_cells
            if native_only_road:
                stats["nativeOnlyRoadIntersectionInstances"] += 1
                stats["nativeOnlyRoadCells"] += len(native_only_road)
                row = {
                    "mission": mission_dir.name,
                    "sourceKey": placement.get("sourceKey") or (placement.get("h3") or {}).get("sourceKey"),
                    "objectId": olden.get("objectId"),
                    "sid": str(sid),
                    "atlasWidth": width,
                    "atlasHeight": height,
                    "anchorNode": node,
                    "rotation": rotation,
                    "nativeOnlyRoadCells": sorted(native_only_road),
                    "legacyRoadCells": sorted(legacy_road),
                    "nativeOccupiedCells": sorted(model.occupied_cells),
                    "legacyOccupiedCells": sorted(model.legacy_occupied_cells),
                    "runtimeModelStatus": model.runtime_model_status,
                }
                if len(examples) < example_limit:
                    examples.append(row)
                if mission_dir.name == "bashing_skulls" and len(bashing_examples) < example_limit:
                    bashing_examples.append(row)
            if legacy_only_road:
                stats["legacyOnlyRoadIntersectionInstances"] += 1
                stats["legacyOnlyRoadCells"] += len(legacy_only_road)

    return {
        "schema": "olden.raw_translation.native_footprint_road_intersection_audit.v2",
        "status": "static_candidate_audit_only",
        "proofBoundary": (
            "source layered-IR road cells are projected into the surface layer of each emitted side-by-side atlas; "
            "native ObjectConfig nodes are the recovered bvf projection; runtime pathfinder proof is separate"
        ),
        "core": str(core),
        "batchManifest": str(batch_manifest) if batch_manifest is not None else None,
        "missionCount": len(mission_dirs),
        "missingLayeredIr": missing_ir,
        "unsupportedLayeredIr": unsupported_ir,
        "stats": dict(stats),
        "topNativeRoadBlockingSids": sid_native.most_common(30),
        "topLegacyRoadBlockingSids": sid_legacy.most_common(30),
        "nativeOnlyRoadExamples": examples,
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
