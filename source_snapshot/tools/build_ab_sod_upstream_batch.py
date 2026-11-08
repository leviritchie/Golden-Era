#!/usr/bin/env python3
"""Run AB/SoD upstream IR→walk→align→substitution without layered-atlas emit."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POC_DIR = ROOT / "experiments" / "campaign_port_poc"
sys.path.insert(0, str(POC_DIR))

from campaign_mission import load_batch_manifest, mission_by_id  # noqa: E402


def run_step(command: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=POC_DIR, env=env, text=True, capture_output=True, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "scenarios" / "ab_sod_campaigns" / "batch_manifest.json",
    )
    parser.add_argument("--mission", action="append", dest="missions", default=None)
    parser.add_argument("--start-from", type=str, default=None)
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
    batch = load_batch_manifest(manifest_path)
    selected = args.missions or [m.mission_id for m in batch.missions]
    if args.start_from:
        if args.start_from not in selected:
            raise SystemExit(f"--start-from {args.start_from!r} not in selection")
        selected = selected[selected.index(args.start_from) :]

    results: list[dict] = []
    python = sys.executable
    for mission_id in selected:
        mission = mission_by_id(batch, mission_id)
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["HOMECOMING_POC_OUT_ROOT"] = str(mission.artifact_root)
        env["HOMECOMING_POC_ARTIFACT_ROOT"] = str(mission.artifact_root)
        env["HOMECOMING_POC_ALIGNMENT_PATH"] = str(mission.alignment_path)
        env["HOMECOMING_POC_SUBSTITUTION_PATH"] = str(mission.substitution_path)
        env["HOMECOMING_POC_SUBSTITUTION_BASENAME"] = mission.substitution_basename
        steps = [
            (
                "layered_ir",
                [
                    python,
                    str(POC_DIR / "build_campaign_layered_ir.py"),
                    "--manifest",
                    str(manifest_path),
                    "--mission",
                    mission_id,
                ],
            ),
            (
                "object_walk",
                [
                    python,
                    str(POC_DIR / "walk_campaign_objects.py"),
                    "--manifest",
                    str(manifest_path),
                    "--mission",
                    mission_id,
                ],
            ),
            (
                "object_port_manifest",
                [
                    python,
                    str(POC_DIR / "build_campaign_object_port_manifest.py"),
                    "--manifest",
                    str(manifest_path),
                    "--mission",
                    mission_id,
                ],
            ),
            (
                "alignment",
                [
                    python,
                    str(POC_DIR / "build_campaign_alignment.py"),
                    "--manifest",
                    str(manifest_path),
                    "--mission",
                    mission_id,
                ],
            ),
            (
                "substitution_map",
                [python, str(POC_DIR / "build_homecoming_entity_substitution_map.py")],
            ),
        ]
        failed = None
        for step_name, command in steps:
            result = run_step(command, env=env)
            if result.returncode != 0:
                detail = "\n".join(
                    part
                    for part in ((result.stdout or "").strip(), (result.stderr or "").strip())
                    if part
                )
                failed = f"{step_name}: {detail or 'non-zero exit'}"
                break
        if failed:
            print(f"FAIL {mission_id}: {failed[:500]}")
            results.append({"missionId": mission_id, "status": "failed", "detail": failed})
            # Fail closed: stop so the fault is fixed before continuing.
            out = ROOT / "artifacts" / "campaign_port_poc" / "ab_sod_campaigns" / "upstream_batch_report.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"results": results}, indent=2) + "\n", encoding="utf-8")
            return 1
        print(f"OK {mission_id}")
        results.append({"missionId": mission_id, "status": "ok"})

    out = ROOT / "artifacts" / "campaign_port_poc" / "ab_sod_campaigns" / "upstream_batch_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"results": results}, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out} ok={len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
