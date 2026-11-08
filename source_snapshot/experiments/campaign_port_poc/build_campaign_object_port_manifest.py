#!/usr/bin/env python3
"""Build an object portability manifest for any campaign mission."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import build_homecoming_object_port_manifest as manifest_engine
from campaign_mission import default_batch_manifest_path, load_batch_manifest, mission_by_id


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_mission_manifest(mission) -> dict[str, Any]:
    manifest_engine.IR_PATH = mission.layered_ir_path
    manifest_engine.WALK_PATH = mission.object_walk_path
    manifest_engine.MANIFEST_PATH = mission.object_port_manifest_path
    manifest_engine.VALIDATION_PATH = mission.layered_ir_dir / f"{mission.mission_id}.object_port_manifest_validation.json"
    manifest_engine.REPORT_PATH = mission.layered_ir_dir / f"{mission.mission_id}.object_port_manifest_report.md"
    manifest_engine.OUT_ROOT = mission.layered_ir_dir

    ir, walk = manifest_engine.load_inputs()
    records = [manifest_engine.classify_record(record) for record in walk["records"]]
    counts = dict(sorted(Counter(item["category"] for item in records).items()))
    by_layer = defaultdict(int)
    for item in records:
        if item.get("emitToMap") is False:
            continue
        layer = int(str(item["sourceKey"]).split(":", 1)[0])
        by_layer[str(layer)] += 1
    manifest = {
        "schema": "homm3.homecoming_object_port_manifest.v0",
        "source": walk.get("source") or {
            "campaignEntry": mission.campaign_entry,
            "blockIndex": mission.block_index,
            "missionId": mission.mission_id,
        },
        "sourceObjectCount": len(walk["records"]),
        "categoryCounts": counts,
        "layerCounts": dict(sorted(by_layer.items())),
        "records": records,
        "silentFallbacksUsed": False,
    }
    validation = manifest_engine.validate_manifest(manifest, validation_profile="campaign_generic")
    manifest["validation"] = validation
    write_json(mission.object_port_manifest_path, manifest)
    write_json(manifest_engine.VALIDATION_PATH, validation)
    manifest_engine.update_ir(ir, manifest, validation)
    manifest_engine.write_report(manifest, validation)
    if validation["result"] != "PASS":
        raise ValueError(f"object port manifest validation failed for {mission.mission_id}: {validation['errors']}")
    return {"manifestPath": str(mission.object_port_manifest_path), "validation": validation}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=default_batch_manifest_path())
    parser.add_argument("--mission", required=True)
    args = parser.parse_args()
    batch = load_batch_manifest(args.manifest.resolve())
    mission = mission_by_id(batch, args.mission)
    if mission.reuse_existing_upstream and mission.object_port_manifest_path.exists():
        print(f"reusing existing object port manifest for {mission.mission_id}")
        return 0
    result = build_mission_manifest(mission)
    print(f"wrote {result['manifestPath']} validation={result['validation']['result']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
