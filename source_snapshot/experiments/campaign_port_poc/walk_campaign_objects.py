#!/usr/bin/env python3
"""Sequential object-table walk for any campaign mission in the batch manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import port_homecoming_poc as poc
import h3m_object_walk as walk_engine
from campaign_mission import default_batch_manifest_path, load_batch_manifest, mission_by_id
from h3c_mission_source import load_h3c_block


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def walk_mission(mission) -> dict[str, Any]:
    if not mission.layered_ir_path.exists():
        raise FileNotFoundError(f"layered IR is required before object walking: {mission.layered_ir_path}")
    ir = json.loads(mission.layered_ir_path.read_text(encoding="utf-8"))
    source = load_h3c_block(mission.campaign_entry, mission.block_index)
    walk = walk_engine.walk_objects(
        source.h3m_data,
        source.summary,
        source.templates,
        walk_engine.make_source_metadata(
            extra={
                "campaignEntry": mission.campaign_entry,
                "blockIndex": mission.block_index,
                "missionId": mission.mission_id,
                "h3mSha256": source.h3m_sha256,
            }
        ),
    )
    validation = walk_engine.validate_generic_walk(walk)
    walk["validation"] = validation
    walk["source"] = {
        "campaignEntry": mission.campaign_entry,
        "blockIndex": mission.block_index,
        "missionId": mission.mission_id,
        "missionTitle": source.summary.title,
        "h3mSha256": source.h3m_sha256,
    }
    write_json(mission.object_walk_path, walk)
    write_json(mission.layered_ir_dir / f"{mission.mission_id}.object_walk_validation.json", validation)
    if validation["result"] != "PASS":
        stop = walk["objectTable"].get("unsupportedStop")
        raise ValueError(f"object walk failed for {mission.mission_id}: {stop or validation['errors']}")
    return {"walkPath": str(mission.object_walk_path), "validation": validation}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=default_batch_manifest_path())
    parser.add_argument("--mission", required=True)
    args = parser.parse_args()
    manifest = load_batch_manifest(args.manifest.resolve())
    mission = mission_by_id(manifest, args.mission)
    if mission.reuse_existing_upstream and mission.object_walk_path.exists():
        print(f"reusing existing object walk for {mission.mission_id}: {mission.object_walk_path}")
        return 0
    result = walk_mission(mission)
    print(f"wrote {result['walkPath']} validation={result['validation']['result']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
