#!/usr/bin/env python3
"""Gate + status for faction-scoped fused_push rollout before Golden Era deploy.

Fail-closed: a faction is deployable only when every non-blocked own-GLB unit has
all delivery clips on disk (gpu_clip_result.json under fused_push_v24_pipeline).
Blocked units (missing lab DEF) are reported separately and do not count as done.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
BATCH = TOOL / "run_fused_push_batch_all_units.py"
OUT = ROOT / "artifacts/fused_push_skinned_rollout"
PREPARE = TOOL / "prepare_smartrig_skinned_import.py"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from faction_rollout import (  # noqa: E402
    bundle_names_for_faction,
    faction_tier_lab_sids,
    normalize_faction_key,
)


def _parse_last_json_object(text: str) -> dict[str, Any]:
    """Decode the last top-level JSON object from mixed stdout."""
    decoder = json.JSONDecoder()
    last: dict[str, Any] | None = None
    index = 0
    while True:
        start = text.find("{", index)
        if start < 0:
            break
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(value, dict):
            last = value
        index = end
    if last is None:
        raise RuntimeError("dry-run produced no JSON summary")
    return last


def _dry_run(faction: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(BATCH),
        "--faction",
        faction,
        "--dry-run",
        "--resume",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "dry-run failed")
    return _parse_last_json_object(proc.stdout)


def _completed_clip_index() -> set[tuple[str, str]]:
    picker = ROOT / "artifacts/pose_picker_runs"
    done: set[tuple[str, str]] = set()
    for path in picker.glob("**/fused_push_v24_pipeline/gpu_clip_result.json"):
        if "fused_push_regression" in path.parts:
            continue
        parts = path.relative_to(ROOT).parts
        # artifacts/pose_picker_runs/<sid>/<anim>/fused_push_v24_pipeline/...
        try:
            i = parts.index("pose_picker_runs")
            done.add((parts[i + 1], parts[i + 2]))
        except (ValueError, IndexError):
            continue
    return done


def build_status(faction: str) -> dict[str, Any]:
    faction_key = normalize_faction_key(faction)
    summary = _dry_run(faction_key)
    blocked = {
        str(row.get("labSid")): str(row.get("reason") or row.get("error") or "blocked")
        for row in (summary.get("planBlocked") or [])
        if row.get("labSid")
    }
    pending = int(summary.get("pendingJobs") or 0)
    clip_jobs = int(summary.get("clipJobs") or 0)
    done_on_disk = sorted(
        [
            {"labSid": sid, "animation": anim}
            for sid, anim in _completed_clip_index()
            if sid in set(faction_tier_lab_sids(faction_key))
        ],
        key=lambda row: (row["labSid"], row["animation"]),
    )
    deployable = pending == 0 and clip_jobs > 0
    return {
        "factionKey": faction_key,
        "proofTier": "generated-artifact",
        "clipJobs": clip_jobs,
        "pendingJobs": pending,
        "completedOnDisk": len(done_on_disk),
        "completedClips": done_on_disk,
        "blockedUnits": blocked,
        "bundleNames": bundle_names_for_faction(faction_key),
        "deployable": deployable,
        "goldenEraNextSteps": [
            f"python {PREPARE.relative_to(ROOT).as_posix()} --rollout-dir {OUT.as_posix()} "
            f"--require-chosen-set --write-import --write-units-manifest",
            "Run Homm3OwnedSkinnedLabBuild / Unity lab batch for faction units",
            "BuildCustomUnitBundles for custom_units_<faction>_* rows",
            "dotnet build OfflineUnlockMod with -p:DeployHomm3BundleName=... "
            "(or scoped faction prefixes) after audio+payload validators pass",
            "Validate adventure-map mesh/import rows + Homm3LabClipAudioDriver contracts",
        ],
        "dryRun": summary,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--faction", required=True, help="e.g. castle or homm3_castle")
    parser.add_argument(
        "--require-deployable",
        action="store_true",
        help="exit 1 unless pendingJobs==0 for non-blocked clip set",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"write {OUT / 'faction_gate'}/<faction>.json",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status = build_status(str(args.faction))
    if args.write:
        out = OUT / "faction_gate" / f"{status['factionKey']}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        status["gatePath"] = str(out)
    print(json.dumps(status, indent=2), flush=True)
    if args.require_deployable and not status["deployable"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
