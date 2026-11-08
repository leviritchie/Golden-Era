#!/usr/bin/env python3
"""Rewalk + emit Seer's Hut QuestScript fixes across StoryHub campaign manifests.

Applies the confirmed stage FSM from ``seer_hut_quest.py`` by refreshing stale
object walks, rebuilding port manifests, and emitting raw_translation maps.

Unsupported v1 mission/reward types remain fail-closed for that mission (no
silent omit). Continues other missions and prints a structured report.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
sys.path.insert(0, str(POC))

from campaign_mission import load_batch_manifest, mission_by_id  # noqa: E402

DEFAULT_MANIFESTS: tuple[Path, ...] = (
    ROOT / "scenarios" / "roe_castle_campaign" / "batch_manifest.json",
    ROOT / "scenarios" / "roe_remaining_campaigns" / "batch_manifest.json",
    ROOT / "scenarios" / "ab_sod_campaigns" / "batch_manifest.json",
)


def _run(command: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(POC),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _mission_has_seer_records(mission: Any) -> bool:
    # Prefer object_port_manifest; fall back to object_walk.
    candidates: list[Path] = [
        mission.artifact_root / f"{mission.mission_id}.object_port_manifest.json",
        mission.artifact_root / "object_port_manifest.json",
    ]
    # Common layout under artifact_root
    for path in mission.artifact_root.rglob("*object_port_manifest.json"):
        candidates.append(path)
        break
    seen: set[Path] = set()
    scanned_manifest = False
    for path in candidates:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        if not path.is_file():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        records = doc.get("records") or doc.get("objects") or []
        if not isinstance(records, list):
            continue
        scanned_manifest = True
        for row in records:
            if not isinstance(row, dict):
                continue
            if row.get("payloadKind") == "seer_hut" or row.get("templateObjectId") == 83:
                return True
        # First readable port manifest with zero seers → skip (do not keep scanning).
        return False
    # Unknown: treat as candidate so rewalk can discover seers.
    return not scanned_manifest


def _process_mission(
    *,
    manifest_path: Path,
    mission_id: str,
    python: str,
    skip_emit: bool,
    env_base: dict[str, str],
) -> dict[str, Any]:
    batch = load_batch_manifest(manifest_path)
    mission = mission_by_id(batch, mission_id)
    env = env_base.copy()
    env["PYTHONUTF8"] = "1"
    env["HOMECOMING_POC_OUT_ROOT"] = str(mission.artifact_root)
    env["HOMECOMING_POC_ARTIFACT_ROOT"] = str(mission.artifact_root)
    env["HOMECOMING_POC_ALIGNMENT_PATH"] = str(mission.alignment_path)
    env["HOMECOMING_POC_SUBSTITUTION_PATH"] = str(mission.substitution_path)
    env["HOMECOMING_POC_SUBSTITUTION_BASENAME"] = mission.substitution_basename

    steps: list[tuple[str, list[str]]] = [
        (
            "object_walk",
            [
                python,
                str(POC / "walk_campaign_objects.py"),
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
                str(POC / "build_campaign_object_port_manifest.py"),
                "--manifest",
                str(manifest_path),
                "--mission",
                mission_id,
            ],
        ),
    ]
    if not skip_emit:
        steps.append(
            (
                "raw_translation_emit",
                [
                    python,
                    str(POC / "build_campaign_raw_translation_batch.py"),
                    "--manifest",
                    str(manifest_path),
                    "--mission",
                    mission_id,
                ],
            )
        )

    result: dict[str, Any] = {
        "manifest": str(manifest_path.relative_to(ROOT)),
        "missionId": mission_id,
        "ok": True,
        "steps": [],
    }
    for name, command in steps:
        proc = _run(command, env=env)
        step = {
            "step": name,
            "returncode": proc.returncode,
            "stderrTail": (proc.stderr or "")[-2000:],
            "stdoutTail": (proc.stdout or "")[-1000:],
        }
        result["steps"].append(step)
        if proc.returncode != 0:
            result["ok"] = False
            result["failedStep"] = name
            # Prefer last non-empty stderr line as reason.
            reason = ""
            for line in reversed((proc.stderr or proc.stdout or "").splitlines()):
                if line.strip():
                    reason = line.strip()
                    break
            result["reason"] = reason
            break
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        action="append",
        dest="manifests",
        type=Path,
        default=None,
        help="Batch manifest (repeatable; default: all three StoryHub campaign manifests)",
    )
    parser.add_argument("--mission", action="append", dest="missions", default=None)
    parser.add_argument(
        "--seer-missions-only",
        action="store_true",
        help="Skip missions with no known seer_hut records in existing port manifests",
    )
    parser.add_argument(
        "--skip-emit",
        action="store_true",
        help="Only rewalk + rebuild object_port_manifest (no raw_translation emit)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "artifacts" / "campaign_port_poc" / "seer_hut_quest_rollout_report.json",
    )
    args = parser.parse_args()

    manifests = [p.resolve() for p in (args.manifests or DEFAULT_MANIFESTS)]
    python = sys.executable
    env_base = os.environ.copy()
    results: list[dict[str, Any]] = []

    for manifest_path in manifests:
        batch = load_batch_manifest(manifest_path)
        selected = args.missions or [m.mission_id for m in batch.missions]
        for mission_id in selected:
            try:
                mission = mission_by_id(batch, mission_id)
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "manifest": str(manifest_path.relative_to(ROOT)),
                        "missionId": mission_id,
                        "ok": False,
                        "reason": str(exc),
                    }
                )
                continue
            if args.seer_missions_only and not _mission_has_seer_records(mission):
                results.append(
                    {
                        "manifest": str(manifest_path.relative_to(ROOT)),
                        "missionId": mission_id,
                        "ok": True,
                        "skipped": "no_seer_records",
                    }
                )
                continue
            print(f"apply seer quest: {manifest_path.name} / {mission_id}", flush=True)
            results.append(
                _process_mission(
                    manifest_path=manifest_path,
                    mission_id=mission_id,
                    python=python,
                    skip_emit=bool(args.skip_emit),
                    env_base=env_base,
                )
            )

    ok_count = sum(1 for row in results if row.get("ok") and not row.get("skipped"))
    skip_count = sum(1 for row in results if row.get("skipped"))
    fail_count = sum(1 for row in results if not row.get("ok"))
    report = {
        "schema": "homm3.seer_hut_quest_rollout_report.v1",
        "proofBoundary": "generated_artifact_rollout; runtime unproven except steadwick",
        "okCount": ok_count,
        "skipCount": skip_count,
        "failCount": fail_count,
        "results": results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("okCount", "skipCount", "failCount")}, indent=2))
    print(f"report={args.report}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
