#!/usr/bin/env python3
"""Write a live Castle fused_push progress snapshot for operators/agents."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
BATCH = TOOL / "run_fused_push_batch_all_units.py"
OUT = ROOT / "artifacts/fused_push_skinned_rollout"
SNAP = OUT / "castle_progress_snapshot.json"
PLAN = OUT / "fit_plan.json"
INDEX = OUT / "rollout_index.json"
GPU_RUN_NAME = "fused_push_v24_pipeline"


def _last_json(text: str) -> dict:
    decoder = json.JSONDecoder()
    last = None
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
        raise RuntimeError("no JSON object in dry-run output")
    return last


def _per_unit_progress() -> list[dict]:
    """Compare fit_plan expected clips vs on-disk fused_push gpu_clip_result.json.

    Mid-round ``rollout_index.json`` is only rewritten at batch end, so disk scan is
    the live source of truth (same as batch resume / ``_write_rollout_index``).
    """
    if not PLAN.is_file():
        return []
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    units = list(plan.get("plan") or [])
    done_scores: dict[tuple[str, str], float] = {}
    picker = ROOT / "artifacts/pose_picker_runs"
    if picker.is_dir():
        for path in picker.glob(f"**/{GPU_RUN_NAME}/gpu_clip_result.json"):
            if "fused_push_regression" in path.parts:
                continue
            try:
                rel = path.relative_to(ROOT)
            except ValueError:
                continue
            parts = rel.parts
            if len(parts) < 5:
                continue
            sid, anim = parts[2], parts[3]
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                done_scores[(sid, anim)] = float(payload.get("score") or 0.0)
            except (TypeError, ValueError, json.JSONDecodeError, OSError):
                done_scores[(sid, anim)] = 0.0
    rows: list[dict] = []
    for unit in units:
        sid = str(unit.get("labSid") or "")
        expected = [
            str(choice.get("animation") or "")
            for choice in (unit.get("choices") or [])
            if choice.get("animation")
        ]
        pending = [anim for anim in expected if (sid, anim) not in done_scores]
        done_anims = [anim for anim in expected if (sid, anim) in done_scores]
        scores = [done_scores[(sid, anim)] for anim in done_anims]
        rows.append(
            {
                "labSid": sid,
                "expectedClips": len(expected),
                "completedClips": len(done_anims),
                "pendingClips": len(pending),
                "pendingAnimations": pending,
                "meanScore": (sum(scores) / len(scores)) if scores else None,
                "minScore": min(scores) if scores else None,
            }
        )
    return rows


def main() -> int:
    proc = subprocess.run(
        [
            sys.executable,
            str(BATCH),
            "--faction",
            "castle",
            "--resume",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr or proc.stdout or "dry-run failed")
    summary = _last_json(proc.stdout)
    completed: list = []
    if INDEX.is_file():
        completed = list(json.loads(INDEX.read_text(encoding="utf-8")).get("clips") or [])
    pending = int(summary.get("pendingJobs") or 0)
    clip_jobs = int(summary.get("clipJobs") or 0)
    done = clip_jobs - pending
    # Recent Castle clips are ~6-8 min; keep a slightly conservative 8 min/clip ETA.
    eta_min = pending * 8
    per_unit = _per_unit_progress()
    active_units = [row for row in per_unit if int(row["pendingClips"]) > 0]
    low_score = [
        {
            "labSid": row["labSid"],
            "meanScore": row["meanScore"],
            "minScore": row["minScore"],
            "completedClips": row["completedClips"],
        }
        for row in per_unit
        if row["meanScore"] is not None and float(row["meanScore"]) < 0.55
    ]
    payload = {
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "factionKey": summary.get("factionKey"),
        "clipJobs": clip_jobs,
        "pendingJobs": pending,
        "completedJobs": done,
        "completedFraction": (done / clip_jobs) if clip_jobs else 0.0,
        "etaMinutesRough": eta_min,
        "planBlocked": summary.get("planBlocked") or [],
        "activeUnits": [
            {
                "labSid": row["labSid"],
                "pendingClips": row["pendingClips"],
                "pendingAnimations": row["pendingAnimations"],
            }
            for row in active_units[:8]
        ],
        "lowScoreUnits": low_score,
        "perUnit": per_unit,
        "completedClipsSample": completed[-12:],
        "proofTier": "generated-artifact progress only; not Golden Era deploy proven",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    SNAP.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "updatedAt": payload["updatedAt"],
                "pendingJobs": pending,
                "completedJobs": done,
                "clipJobs": clip_jobs,
                "completedFraction": payload["completedFraction"],
                "etaMinutesRough": eta_min,
                "activeUnits": payload["activeUnits"][:4],
                "lowScoreUnits": low_score,
                "planBlocked": payload["planBlocked"],
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
