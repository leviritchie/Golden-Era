#!/usr/bin/env python3
"""Rebuild the per-mission entity substitution maps for campaign batch manifests.

``build_campaign_raw_translation_batch.py`` reads ``<artifactRoot>/entity_substitutions/
<mission>.olden_entity_substitution_map.json`` but never rebuilds it, so a change to
``build_homecoming_entity_substitution_map.py`` reaches the maps only through this tool.

Fail-closed: every requested mission must rebuild; any failure exits non-zero and is listed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
sys.path.insert(0, str(POC))

from campaign_mission import load_batch_manifest  # noqa: E402

DEFAULT_MANIFESTS = (
    "scenarios/roe_castle_campaign/batch_manifest.json",
    "scenarios/roe_remaining_campaigns/batch_manifest.json",
    "scenarios/ab_sod_campaigns/batch_manifest.json",
)


def _bind(sub_mod, mission) -> None:
    artifact_root = mission.artifact_root
    alignment = mission.alignment_path
    if not alignment.is_file():
        raise FileNotFoundError(f"missing alignment {alignment}")
    basename = mission.substitution_basename
    os.environ["HOMECOMING_POC_OUT_ROOT"] = str(artifact_root)
    os.environ["HOMECOMING_POC_ARTIFACT_ROOT"] = str(artifact_root)
    os.environ["HOMECOMING_POC_ALIGNMENT_PATH"] = str(alignment)
    os.environ["HOMECOMING_POC_SUBSTITUTION_PATH"] = str(mission.substitution_path)
    os.environ["HOMECOMING_POC_SUBSTITUTION_BASENAME"] = basename
    # Module path globals are bound at import time; rebind them per mission.
    sub_mod.OUT_ROOT = artifact_root
    sub_mod.ALIGNMENT_PATH = alignment
    sub_mod.OUT_DIR = artifact_root / "entity_substitutions"
    sub_mod._SUBSTITUTION_BASENAME = basename
    sub_mod.OUT_PATH = sub_mod.OUT_DIR / f"{basename}.json"
    sub_mod._REPORT_BASENAME = basename.replace(".olden_entity_substitution_map", "")
    sub_mod.REPORT_PATH = sub_mod.OUT_DIR / f"{sub_mod._REPORT_BASENAME.upper()}_OLDEN_ENTITY_SUBSTITUTION_MAP_REPORT.md"
    if sub_mod.OUT_PATH != mission.substitution_path:
        raise ValueError(f"{mission.mission_id}: substitution path drift {sub_mod.OUT_PATH} != {mission.substitution_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", action="append", help="batch manifest (repeatable); default: the three campaign manifests")
    parser.add_argument("--mission", action="append", help="restrict to these mission ids")
    args = parser.parse_args()

    import build_homecoming_entity_substitution_map as sub_mod

    missions = []
    for manifest_path in args.manifest or DEFAULT_MANIFESTS:
        missions.extend(load_batch_manifest(Path(manifest_path)).missions)
    if args.mission:
        wanted = set(args.mission)
        missions = [m for m in missions if m.mission_id in wanted]
        missing = wanted - {m.mission_id for m in missions}
        if missing:
            raise SystemExit(f"unknown mission ids: {sorted(missing)}")

    failures: list[dict] = []
    t0 = time.perf_counter()
    for index, mission in enumerate(missions, 1):
        try:
            _bind(sub_mod, mission)
            code = sub_mod.main()
        except Exception as exc:  # reported and fails the run
            failures.append({"missionId": mission.mission_id, "error": f"{type(exc).__name__}: {exc}"})
            print(f"[{index}/{len(missions)}] FAIL {mission.mission_id}: {exc}", flush=True)
            continue
        if code != 0:
            failures.append({"missionId": mission.mission_id, "error": f"exit {code}"})
            print(f"[{index}/{len(missions)}] FAIL {mission.mission_id}: exit {code}", flush=True)
            continue
        print(f"[{index}/{len(missions)}] ok {mission.mission_id}", flush=True)
    report = {
        "ok": not failures,
        "missionCount": len(missions),
        "failures": failures,
        "elapsedSec": round(time.perf_counter() - t0, 2),
    }
    print(json.dumps(report, indent=2), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
