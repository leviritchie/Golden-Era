#!/usr/bin/env python3
"""Run the validated DEF continuous-tracking method across the Stronghold roster.

Method under test (all measured on h3_roc idle_start_move_end)
--------------------------------------------------------------
* plate-identity anchoring -- loop seam pose jump 17.5 deg -> 0.29 deg, idle tail fit
  0.79 -> 0.93, mean fit 0.809 -> 0.848
* unsaturated penetration guard -- head-chain self-intersection 20/30 frames -> 0/30
* temporal continuity (RMS form) -- penetration 0.091 -> 0.028, large joint steps 13 -> 7

Every one of those numbers comes from one unit. This batch exists to find out whether
the method generalises, so it runs the same settings unchanged on all 21 Stronghold
units (base, upgrade, alternate upgrade per tier) and audits each result the same way. No per-unit tuning, because a method that
needs hand-tuning per unit has not been shown to generalise.

Deliberately NOT passed: ``--anatomy-order``. Only h3_roc has an authored file, and
applying it measured *worse* on that unit (mean per-joint step 2.74 -> 10.45 deg), so
including it would vary two things at once and reintroduce a known regression.

Batch conduct
-------------
A unit that fails is recorded with its stderr tail and the batch continues, because one
bad mesh should not cost the whole night. Failures are reported as failures and never
counted as passes. ``--deadline`` stops *starting* new units after a wall-clock time so
the run does not spill into the morning; anything not started is reported as skipped
with that reason.

Proof tier: generated artifact. Produces solved clips, audits, and GIFs; runtime
gameplay in Olden Era is not addressed here.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

# Lab SIDs for the full Golden Era Stronghold roster: 7 tiers x (base, upgrade,
# alternate upgrade) = 21, per custom_factions/homm3_stronghold.json unitLines.
# Alternate upgrades use the `toa_*` lab SIDs. Every unit has its own Meshy mesh and
# texture (verified 2026-09-01 by geometry/texture hash) except toa_boar_rider, whose
# Meshy smart rig failed twice and has no GLB or frame tree yet; it is listed so the
# batch reports it as unavailable instead of silently shipping 20 as "all".
STRONGHOLD_UNITS = (
    "h3_goblin",
    "h3_hobgoblin",
    "toa_goblin_trapper",
    "h3_wolf_rider",
    "h3_wolf_raider",
    "toa_boar_rider",
    "h3_orc",
    "h3_orc_chieftain",
    "toa_orc_berserker",
    "h3_ogre",
    "h3_ogre_mage",
    "toa_ogre_brute",
    "h3_roc",
    "h3_thunderbird",
    "toa_shahrokh",
    "h3_cyclops",
    "h3_cyclops_king",
    "toa_blood_eyed_cyclops",
    "h3_behemoth",
    "h3_ancient_behemoth",
    "toa_ghost_behemoth",
)

DEFAULT_CLIP = "idle_start_move_end"
DEFAULT_LANE = "def_continuous_stronghold"


def head_chain_bones(unit: str) -> tuple[list[str], str]:
    """Head/neck bones for penetration attribution, from the unit's anatomy groups.

    Most anatomy-group files list each group as a full root-to-tip chain, so the "head"
    group also contains the armature root and hips (h3_goblin's head group opens with
    ``UniRigArmature, Bone_000, Bone_001``). Attributing self-intersection to a "head
    chain" that includes the hips would measure the whole body while still printing a
    plausible number -- a wrong metric is worse than a missing one.

    So bones shared with any other group are dropped: a bone every chain passes through
    is not specific to the head. If nothing unique remains, the head metric is reported
    as unresolved rather than as a clean zero, which would be indistinguishable from a
    genuinely clean result.
    """
    candidates = sorted(TOOL.glob(f"{unit}_smartrig_anatomy_groups.json"))
    if not candidates:
        # Some units predate the sid-prefixed naming (roc, behemoth, hobgoblin).
        short = unit[3:] if unit.startswith("h3_") else unit
        candidates = sorted(TOOL.glob(f"{short}_smartrig_anatomy_groups.json"))
    if not candidates:
        return [], f"no anatomy groups file for {unit}"
    payload = json.loads(candidates[0].read_text(encoding="utf-8"))
    groups = payload.get("groups") or {}
    head_name: str | None = None
    for name in groups:
        lowered = str(name).lower()
        if "head" in lowered or "neck" in lowered or "cranial" in lowered:
            head_name = str(name)
            break
    if head_name is None:
        return [], f"{candidates[0].name} has no head/neck group"

    def bones_of(name: str) -> list[str]:
        return [str(bone) for bone in (groups[name].get("bonesDependencyOrder") or [])]

    shared: set[str] = set()
    for name in groups:
        if name == head_name:
            continue
        shared.update(bones_of(name))
    unique = [bone for bone in bones_of(head_name) if bone not in shared]
    if not unique:
        return [], (
            f"{candidates[0].name} group {head_name!r} shares every bone with other "
            "groups, so no head-specific chain exists"
        )
    return unique, f"{candidates[0].name} group {head_name!r} minus shared bones"


def run_step(
    command: list[str], *, log: Path, timeout_sec: float
) -> tuple[bool, str]:
    """Run one subprocess, tee its output to a log, and report success plus a tail."""
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(timeout_sec),
        )
    except subprocess.TimeoutExpired:
        log.write_text(
            f"command timed out after {timeout_sec:.0f}s\n{' '.join(command)}\n",
            encoding="utf-8",
        )
        return False, f"timeout after {timeout_sec:.0f}s"
    body = (completed.stdout or "") + (completed.stderr or "")
    log.write_text(
        f"# {' '.join(command)}\n# exit={completed.returncode} "
        f"elapsed={time.time() - started:.1f}s\n\n{body}",
        encoding="utf-8",
    )
    if completed.returncode == 0:
        return True, ""
    tail = "\n".join(body.strip().splitlines()[-12:])
    return False, tail


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clip", default=DEFAULT_CLIP)
    parser.add_argument("--lane", default=DEFAULT_LANE)
    parser.add_argument(
        "--units",
        default=None,
        help="Comma-separated subset of the Stronghold roster; default is all 21.",
    )
    parser.add_argument(
        "--deadline",
        default=None,
        help=(
            "Local HH:MM after which no new unit is started, e.g. 08:00. Interpreted as "
            "the next occurrence of that time."
        ),
    )
    parser.add_argument(
        "--per-unit-timeout-sec",
        type=float,
        default=2700.0,
        help="Hard cap per tracker run. h3_roc takes ~430s at these settings.",
    )
    parser.add_argument("--correct-steps", type=int, default=60)
    parser.add_argument("--correct-schedule", default="4,2,1,0.5")
    parser.add_argument(
        "--out",
        default=None,
        help="Summary JSON path; defaults under artifacts/pose_picker_runs/_batches.",
    )
    return parser.parse_args()


def resolve_deadline(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    hour, _, minute = str(raw).partition(":")
    now = datetime.now()
    target = now.replace(hour=int(hour), minute=int(minute or 0), second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return target


def main() -> int:
    args = parse_args()
    clip = str(args.clip)
    lane = str(args.lane)
    units = (
        list(STRONGHOLD_UNITS)
        if args.units is None
        else [part.strip() for part in str(args.units).split(",") if part.strip()]
    )
    unknown = [unit for unit in units if unit not in STRONGHOLD_UNITS]
    if unknown:
        raise ValueError(f"not Stronghold roster units: {unknown}")
    deadline = resolve_deadline(args.deadline)

    batch_root = ROOT / "artifacts/pose_picker_runs/_batches" / f"stronghold_{lane}"
    batch_root.mkdir(parents=True, exist_ok=True)
    out_path = (
        Path(str(args.out))
        if args.out is not None
        else batch_root / "stronghold_continuous_batch.json"
    )

    print(
        f"stronghold batch: {len(units)} units clip={clip} lane={lane} "
        f"deadline={deadline.isoformat() if deadline else 'none'}",
        flush=True,
    )

    results: list[dict[str, Any]] = []
    for position, unit in enumerate(units, start=1):
        if deadline is not None and datetime.now() >= deadline:
            results.append(
                {
                    "unit": unit,
                    "status": "skipped",
                    "reason": f"deadline {deadline.isoformat()} reached before start",
                }
            )
            print(f"[{position}/{len(units)}] {unit}: SKIPPED (deadline)", flush=True)
            continue

        frame_dir = (
            ROOT
            / "artifacts/pose_picker_runs"
            / unit
            / clip
            / f"frames_def12_nn_{clip}_shadow_culled"
        )
        if not frame_dir.is_dir():
            results.append(
                {
                    "unit": unit,
                    "status": "unavailable",
                    "reason": f"missing frame dir {frame_dir}",
                }
            )
            print(f"[{position}/{len(units)}] {unit}: NO FRAMES", flush=True)
            continue

        unit_log_dir = batch_root / unit
        started = time.time()
        print(f"[{position}/{len(units)}] {unit}: tracking...", flush=True)
        ok, tail = run_step(
            [
                sys.executable,
                str(TOOL / "def_continuous_pose_tracker.py"),
                "--unit",
                unit,
                "--clip",
                clip,
                "--quality",
                "--correct-steps",
                str(int(args.correct_steps)),
                "--correct-schedule",
                str(args.correct_schedule),
                "--out-lane",
                lane,
            ],
            log=unit_log_dir / "track.log",
            timeout_sec=float(args.per_unit_timeout_sec),
        )
        entry: dict[str, Any] = {
            "unit": unit,
            "clip": clip,
            "lane": lane,
            "trackSec": round(time.time() - started, 1),
        }
        if not ok:
            entry.update({"status": "failed", "stage": "track", "error": tail})
            results.append(entry)
            print(f"[{position}/{len(units)}] {unit}: TRACK FAILED", flush=True)
            _write(out_path, results, units, clip, lane, deadline)
            continue

        report_path = (
            ROOT
            / "artifacts/pose_picker_runs"
            / unit
            / clip
            / lane
            / f"{unit}_continuous_track_report.json"
        )
        if not report_path.is_file():
            entry.update(
                {
                    "status": "failed",
                    "stage": "report",
                    "error": f"tracker reported success but {report_path} is absent",
                }
            )
            results.append(entry)
            _write(out_path, results, units, clip, lane, deadline)
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        # The tracker writes its fit numbers under "track"; a missing key here is a
        # contract break, not a null result, so it is recorded as a failure.
        track = report.get("track")
        required = ("meanSilhouetteAfter", "meanPenetrationAfter", "anchoredFrames", "loopSeam")
        if not isinstance(track, dict) or any(key not in track for key in required):
            missing = [key for key in required if not isinstance(track, dict) or key not in track]
            entry.update(
                {
                    "status": "failed",
                    "stage": "report",
                    "error": f"{report_path.name} lacks track keys {missing}",
                }
            )
            results.append(entry)
            _write(out_path, results, units, clip, lane, deadline)
            continue
        entry["bindMeanScore"] = report.get("bindMeanScore")
        entry["meanSilhouette"] = track["meanSilhouetteAfter"]
        entry["meanPenetration"] = track["meanPenetrationAfter"]
        entry["maxPenetration"] = track.get("maxPenetrationAfter")
        entry["anchoredFrames"] = track["anchoredFrames"]
        entry["loopSeam"] = track["loopSeam"]
        entry["solveSec"] = track.get("solveSec")

        # Independent audits: the tracker grading its own output is not a check.
        seam_ok, seam_tail = run_step(
            [
                sys.executable,
                str(TOOL / "def_loop_seam_audit.py"),
                "--unit",
                unit,
                "--clip",
                clip,
                "--lane",
                lane,
            ],
            log=unit_log_dir / "loop_seam_audit.log",
            timeout_sec=600.0,
        )
        entry["loopSeamAudit"] = "ok" if seam_ok else f"failed: {seam_tail[-400:]}"

        head_bones, head_note = head_chain_bones(unit)
        entry["headBonesSource"] = head_note
        entry["headAttribution"] = "measured" if head_bones else "disabled"
        # Total penetration is measured either way; only the head breakdown depends on
        # a head-specific chain existing, and its absence is reported as null.
        head_args = (
            ["--head-bones", ",".join(head_bones)]
            if head_bones
            else ["--no-head-attribution"]
        )
        pen_ok, pen_tail = run_step(
            [
                sys.executable,
                str(TOOL / "def_self_intersection_audit.py"),
                "--unit",
                unit,
                "--clip",
                clip,
                "--lane",
                lane,
                *head_args,
            ],
            log=unit_log_dir / "self_intersection_audit.log",
            timeout_sec=900.0,
        )
        entry["selfIntersectionAudit"] = "ok" if pen_ok else f"failed: {pen_tail[-400:]}"

        entry["status"] = "ok"
        entry["compareGif"] = str(
            ROOT
            / "artifacts/pose_picker_runs"
            / unit
            / clip
            / lane
            / "sprite_vs_bind_vs_track.gif"
        ).replace("\\", "/")
        results.append(entry)
        seam = entry.get("loopSeam") or {}
        print(
            f"[{position}/{len(units)}] {unit}: ok silh={entry['meanSilhouette']} "
            f"pen={entry['meanPenetration']} seam={seam.get('seamMeanBoneDeltaDeg')}deg "
            f"ratio={seam.get('seamPopRatio')} identical={seam.get('plateIdentical')} "
            f"({entry['trackSec']}s)",
            flush=True,
        )
        _write(out_path, results, units, clip, lane, deadline)

    _write(out_path, results, units, clip, lane, deadline)
    ok_count = sum(1 for entry in results if entry.get("status") == "ok")
    print(
        f"\nstronghold batch done: {ok_count}/{len(units)} tracked, summary {out_path}",
        flush=True,
    )
    return 0


def _write(
    out_path: Path,
    results: list[dict[str, Any]],
    units: list[str],
    clip: str,
    lane: str,
    deadline: datetime | None,
) -> None:
    """Rewrite the summary after every unit so a crash still leaves partial results."""
    payload = {
        "proof": "generated-artifact",
        "method": "plate anchoring + unsaturated penetration guard + RMS temporal continuity",
        "methodValidatedOn": "h3_roc idle_start_move_end only; this batch tests generalisation",
        "clip": clip,
        "lane": lane,
        "requestedUnits": units,
        "deadline": None if deadline is None else deadline.isoformat(),
        "written": datetime.now().isoformat(timespec="seconds"),
        "counts": {
            status: sum(1 for entry in results if entry.get("status") == status)
            for status in ("ok", "failed", "skipped", "unavailable")
        },
        "results": results,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
