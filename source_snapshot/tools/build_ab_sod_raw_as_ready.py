#!/usr/bin/env python3
"""Build AB/SoD raw_translation maps for missions whose upstream artifacts exist."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
sys.path.insert(0, str(POC))

from campaign_mission import load_batch_manifest, mission_by_id  # noqa: E402
from campaign_profile_derive import map_sid_to_raw_translation  # noqa: E402


def upstream_ready(mission) -> bool:
    return mission.alignment_path.is_file() and mission.substitution_path.is_file()


def raw_map_path(mission) -> Path:
    map_sid = map_sid_to_raw_translation(mission.map_sid)
    return mission.artifact_root / "raw_translation_map" / "maps" / f"{map_sid}.map"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "scenarios" / "ab_sod_campaigns" / "batch_manifest.json",
    )
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--max-wait-seconds", type=float, default=0.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Record mission failures and continue the queue (still exits non-zero if any failed).",
    )
    args = parser.parse_args()
    batch = load_batch_manifest(args.manifest.resolve())
    started = time.time()
    results: dict[str, str] = {}
    pending = [m.mission_id for m in batch.missions]
    failures: list[str] = []

    while pending:
        progressed = False
        still: list[str] = []
        for mission_id in pending:
            mission = mission_by_id(batch, mission_id)
            out = raw_map_path(mission)
            if out.is_file() and out.stat().st_size > 0:
                results[mission_id] = "already_ok"
                progressed = True
                print(f"SKIP {mission_id}: raw map exists", flush=True)
                continue
            if not upstream_ready(mission):
                still.append(mission_id)
                continue
            cmd = [
                sys.executable,
                str(POC / "build_campaign_raw_translation_batch.py"),
                "--manifest",
                str(args.manifest.resolve()),
                "--mission",
                mission_id,
            ]
            print(f"BUILD {mission_id}", flush=True)
            proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True)
            if proc.returncode != 0:
                detail = (proc.stdout or "")[-2000:] + "\n" + (proc.stderr or "")[-2000:]
                results[mission_id] = f"failed:{detail}"
                failures.append(mission_id)
                report = {
                    "results": results,
                    "pending": still + pending[pending.index(mission_id) + 1 :],
                    "failures": failures,
                }
                out_report = (
                    ROOT
                    / "artifacts"
                    / "campaign_port_poc"
                    / "ab_sod_campaigns"
                    / "raw_batch_report.json"
                )
                out_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                print(f"FAIL {mission_id}", flush=True)
                print(detail[-1500:], flush=True)
                if args.continue_on_error:
                    progressed = True
                    continue
                return 1
            if not out.is_file():
                results[mission_id] = "failed:missing_output"
                failures.append(mission_id)
                print(f"FAIL {mission_id}: missing output {out}", flush=True)
                if args.continue_on_error:
                    progressed = True
                    continue
                return 1
            results[mission_id] = "ok"
            progressed = True
            print(f"OK {mission_id}", flush=True)
        pending = still
        if args.once:
            break
        if not pending:
            break
        if args.max_wait_seconds and (time.time() - started) > args.max_wait_seconds:
            print(f"TIMEOUT pending={pending}", flush=True)
            return 2
        if not progressed:
            print(f"WAIT {args.poll_seconds}s pending={len(pending)}", flush=True)
            time.sleep(args.poll_seconds)

    out_report = (
        ROOT / "artifacts" / "campaign_port_poc" / "ab_sod_campaigns" / "raw_batch_report.json"
    )
    out_report.write_text(
        json.dumps({"results": results, "pending": pending, "failures": failures}, indent=2) + "\n",
        encoding="utf-8",
    )
    ok = sum(1 for v in results.values() if v in ("ok", "already_ok"))
    print(f"Wrote {out_report} ok={ok} failed={len(failures)} pending={len(pending)}", flush=True)
    if failures:
        return 1
    return 0 if not pending else 3


if __name__ == "__main__":
    raise SystemExit(main())
