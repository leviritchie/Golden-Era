#!/usr/bin/env python3
"""Validate that RoE Castle campaign H3C blocks fully decode through the shared object walker."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED_COMPLETE_MISSIONS = {
    "homecoming",
    "guardian_angels",
    "griffin_cliff",
    "steadwick_liberation",
    "deal_with_the_devil",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    parser.add_argument(
        "--manifest",
        default="scenarios/roe_castle_campaign/batch_manifest.json",
        help="Campaign batch manifest with mission H3C block references",
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))

    import h3m_object_walk as walk_engine
    from campaign_mission import load_batch_manifest
    from h3c_mission_source import load_h3c_block

    errors: list[str] = []
    warnings: list[str] = []
    results: list[dict[str, object]] = []
    manifest_path = (repo_root / args.manifest).resolve()
    if not manifest_path.is_file():
        print(f"H3M campaign object-walk contract FAIL\n- missing manifest: {manifest_path}")
        return 1

    manifest = load_batch_manifest(manifest_path)
    for mission in manifest.missions:
        mission_id = mission.mission_id
        try:
            source = load_h3c_block(mission.campaign_entry, mission.block_index)
        except FileNotFoundError as exc:
            errors.append(f"{mission_id}: {exc}")
            continue
        # Full walk attaches global timed events and refuses synthetic briefing absorption
        # of the post-object event table.
        walk = walk_engine.walk_objects(
            source.h3m_data,
            source.summary,
            source.templates,
            walk_engine.make_source_metadata(
                extra={
                    "campaignEntry": mission.campaign_entry,
                    "blockIndex": mission.block_index,
                    "missionId": mission_id,
                    "h3mSha256": source.h3m_sha256,
                }
            ),
        )
        table = walk["objectTable"]
        declared = int(table["declaredCount"])
        decoded = int(table["decodedCount"])
        ratio = decoded / declared if declared else 0.0
        complete = bool(table["complete"])
        stop = table.get("unsupportedStop") or {}
        gte = walk.get("globalTimedEvents") or {}
        synth = sum(1 for row in (walk.get("records") or []) if row.get("syntheticHeader"))
        result = {
            "missionId": mission_id,
            "h3mVersion": source.summary.version,
            "declaredCount": declared,
            "decodedCount": decoded,
            "decodedRatio": round(ratio, 4),
            "complete": complete,
            "unsupportedStop": stop,
            "globalTimedEventStatus": gte.get("status"),
            "globalTimedEventCount": gte.get("eventCount"),
            "stoppedAtPostObjectGlobalTimedEvents": table.get("stoppedAtPostObjectGlobalTimedEvents"),
            "syntheticBriefingRecords": synth,
        }
        results.append(result)
        if mission_id in REQUIRED_COMPLETE_MISSIONS:
            if not complete:
                errors.append(
                    f"{mission_id}: required full walk failed at record {stop.get('index')} "
                    f"object id {(stop.get('record') or {}).get('templateObjectId')}: {stop.get('error')}"
                )
            if gte.get("status") != "decoded":
                errors.append(f"{mission_id}: globalTimedEvents must decode; status={gte.get('status')!r}")
            if synth:
                errors.append(
                    f"{mission_id}: synthetic ROE campaign briefing records must be 0 after event-boundary fix; got {synth}"
                )
        elif not complete:
            errors.append(f"{mission_id}: unexpected incomplete walk: {stop.get('error')}")

    if errors:
        print("H3M campaign object-walk contract FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("H3M campaign object-walk contract PASS")
    for warning in warnings:
        print(f"warning: {warning}")
    print(
        json.dumps(
            {
                "manifest": str(manifest_path.relative_to(repo_root)),
                "missions": results,
                "warnings": warnings,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
