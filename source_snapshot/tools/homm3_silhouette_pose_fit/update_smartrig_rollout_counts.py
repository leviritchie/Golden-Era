#!/usr/bin/env python3
"""Refresh rollout_status.json clip counts from the live plan and clip log.

Does not take the GPU lock. Does not install into Golden Era.
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
OUT = ROOT / "artifacts/homm3_smartrig_skinned_rollout"
SKIP = frozenset({7, 8, 11, 13, 14, 16})
IDLE = 2
SUFFIX = {
    0: "Move",
    1: "Mouseover",
    2: "Idle",
    3: "Hitted",
    4: "Defence",
    5: "Death",
    12: "AttackFront",
    15: "ShootFront",
    20: "MoveStart",
    21: "MoveEnd",
}


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def recount() -> dict:
    plan = _load(OUT / "fit_plan.json")
    idle_jobs = 0
    rest_jobs = 0
    planned: Counter[str] = Counter()
    for row in plan.get("plan") or []:
        if row.get("error"):
            continue
        for choice in row.get("choices") or []:
            groups = [int(group) for group in choice["groups"]]
            motion = [group for group in groups if group != IDLE]
            if not motion:
                idle_jobs += 1
                planned["Idle"] += 1
                continue
            rest_jobs += 1
            seen = set()
            for group in motion:
                if group in SKIP or group not in SUFFIX or group in seen:
                    continue
                seen.add(group)
                planned[SUFFIX[group]] += 1

    fitted: Counter[str] = Counter()
    idle_sids = set()
    idle_failed_sids = set()
    rest_ok = 0
    rest_failed = 0
    clip_log = OUT / "clip_log.jsonl"
    if clip_log.is_file():
        for line in clip_log.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            anim = str(event.get("animation") or "")
            groups = [int(group) for group in (event.get("groups") or [])]
            if event.get("error"):
                if anim == "idle" or groups == [2]:
                    if event.get("labSid"):
                        idle_failed_sids.add(event["labSid"])
                elif anim:
                    rest_failed += 1
                continue
            if anim == "idle" or groups == [2]:
                fitted["Idle"] += 1
                if event.get("labSid"):
                    idle_sids.add(event["labSid"])
                continue
            rest_ok += 1
            seen = set()
            for group in groups:
                if group == IDLE or group in SKIP or group not in SUFFIX or group in seen:
                    continue
                seen.add(group)
                fitted[SUFFIX[group]] += 1

    per_category = {}
    for name in (
        "Idle",
        "Move",
        "Mouseover",
        "Hitted",
        "Defence",
        "Death",
        "AttackFront",
        "ShootFront",
        "MoveStart",
        "MoveEnd",
    ):
        planned_n = int(planned.get(name, 0))
        fitted_n = int(fitted.get(name, 0))
        per_category[name] = {
            "planned": planned_n,
            "fittedKeep": fitted_n,
            "remaining": max(0, planned_n - fitted_n),
        }
    return {
        "idleJobs": idle_jobs,
        "restJobs": rest_jobs,
        "idleFitted": len(idle_sids) if idle_sids else int(fitted.get("Idle", 0)),
        "idleFailed": len(idle_failed_sids),
        "idleFailedSids": sorted(idle_failed_sids),
        "restFitted": rest_ok,
        "restFailed": rest_failed,
        "perCategory": per_category,
    }


def apply_status(counts: dict) -> dict:
    status_path = OUT / "rollout_status.json"
    status = _load(status_path) if status_path.is_file() else {}
    progress = _load(OUT / "progress.json") if (OUT / "progress.json").is_file() else {}
    idle_left = max(0, counts["idleJobs"] - counts["idleFitted"] - counts["idleFailed"])
    rest_left = max(0, counts["restJobs"] - counts["restFitted"] - counts["restFailed"])
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    status["updatedAt"] = now
    gpu = status.setdefault("gpuBatch", {})
    gpu["idleJobs"] = counts["idleJobs"]
    gpu["restJobs"] = counts["restJobs"]
    gpu["okClipsAtWrite"] = progress.get("okClips")
    gpu["idleFittedAtWrite"] = counts["idleFitted"]
    gpu["idleFailedAtWrite"] = counts["idleFailed"]
    gpu["restFittedAtWrite"] = counts["restFitted"]
    gpu["restFailedAtWrite"] = counts["restFailed"]
    gpu["lockAliveNote"] = f"progress updatedAt={progress.get('updatedAt')}"
    done = status.setdefault("clipsDoneVsRemaining", {})
    done["idleOwnGlbJobs"] = counts["idleJobs"]
    done["idleFittedKeepMatching"] = counts["idleFitted"]
    done["idleFailClosed"] = counts["idleFailed"]
    done["idleFailClosedSids"] = counts["idleFailedSids"]
    done["idleOwnGlbRemainingToFit"] = idle_left
    done["restJobsPlanned"] = counts["restJobs"]
    done["restJobsFittedKeepMatching"] = counts["restFitted"]
    done["restJobsRemaining"] = rest_left
    done["perCategory"] = counts["perCategory"]
    done["notPlanned"] = ["AttackUp", "AttackDown", "ShootUp", "ShootDown"]
    done["idleOnlyUntilRestFits"] = counts["restFitted"] == 0
    _dump(status_path, status)
    _dump(
        OUT / "clip_category_counts.json",
        {
            "jobAccounting": "Idle = idle-only GPU jobs. Other categories = rest jobs that deliver that motion DEF group.",
            "idleJobs": counts["idleJobs"],
            "idleFittedKeep": counts["idleFitted"],
            "idleRemaining": idle_left,
            "restJobs": counts["restJobs"],
            "restFittedKeep": counts["restFitted"],
            "restRemaining": rest_left,
            "perCategory": counts["perCategory"],
        },
    )
    return {
        "updatedAt": now,
        "idleFitted": counts["idleFitted"],
        "idleFailed": counts["idleFailed"],
        "idleRemaining": idle_left,
        "restFitted": counts["restFitted"],
        "restFailed": counts["restFailed"],
        "restRemaining": rest_left,
        "okClips": progress.get("okClips"),
        "progressUpdatedAt": progress.get("updatedAt"),
        "complete": idle_left == 0 and rest_left == 0,
    }


def main() -> int:
    summary = apply_status(recount())
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if summary["complete"] else 2


if __name__ == "__main__":
    sys.exit(main())
