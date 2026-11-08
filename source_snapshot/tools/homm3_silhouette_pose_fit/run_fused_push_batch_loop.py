#!/usr/bin/env python3
"""Repeat fused_push batch fits until pending clips are exhausted.

Uses the GPU lock inside each batch invocation (one clip batch at a time).
Default GPU lane: packed raster sized from each mesh (see fused_push_mesh_raster_budget).
Pass --memory-safe or --gpu-fed only as explicit constant overrides.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
BATCH = ROOT / "tools/homm3_silhouette_pose_fit/run_fused_push_batch_all_units.py"
LOCK = ROOT / "artifacts/pose_picker_runs/gpu_cascade_global.lock"
LOCK_WAIT_HINT = "GPU cascade batch lock already exists"


def _pending_jobs(*, resume: bool, faction: str, active_faction: bool) -> int:
    cmd = [sys.executable, str(BATCH), "--dry-run"]
    if resume:
        cmd.append("--resume")
    if faction:
        cmd.extend(["--faction", faction])
    elif active_faction:
        cmd.append("--active-faction")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "dry-run failed")
    match = re.search(r'"pendingJobs":\s*(\d+)', proc.stdout)
    if not match:
        raise RuntimeError("dry-run did not report pendingJobs")
    return int(match.group(1))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-clips", type=int, default=6, help="clips per batch round")
    parser.add_argument("--preview-gif", action="store_true", help="write preview_compare.gif per clip")
    parser.add_argument("--memory-safe", action="store_true")
    parser.add_argument(
        "--gpu-fed",
        action="store_true",
        help="opt-in 48/4 raster lane (may spill on 16GB cards)",
    )
    parser.add_argument(
        "--faction",
        default="",
        help="limit to one faction (e.g. castle); default uses --active-faction",
    )
    parser.add_argument(
        "--all-factions",
        action="store_true",
        help="disable faction scoping (flat catalog order; not recommended)",
    )
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=0,
        help="stop after N batch rounds (0 = until pending=0)",
    )
    parser.add_argument("--sleep-sec", type=float, default=3.0, help="pause between rounds")
    parser.add_argument(
        "--lock-wait-sec",
        type=float,
        default=30.0,
        help="when another cascade holds the GPU lock, wait this many seconds and retry",
    )
    parser.add_argument(
        "--lock-wait-max",
        type=int,
        default=240,
        help="max lock-wait retries per round (0 = fail immediately on lock contention)",
    )
    return parser.parse_args(argv)


def _log_mentions_lock(log_path: Path) -> bool:
    if not log_path.is_file():
        return False
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return LOCK_WAIT_HINT in text


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    use_active_faction = not bool(args.all_factions) and not str(args.faction or "").strip()
    round_n = 0
    while True:
        pending = _pending_jobs(
            resume=bool(args.resume),
            faction=str(args.faction or ""),
            active_faction=use_active_faction,
        )
        print(json.dumps({"round": round_n + 1, "pendingJobs": pending}, indent=2), flush=True)
        if pending <= 0:
            print("fused_push batch loop: no pending clips", flush=True)
            return 0
        round_n += 1
        if int(args.max_rounds) > 0 and round_n > int(args.max_rounds):
            print(f"max-rounds={args.max_rounds} reached; stopping", flush=True)
            return 0
        cmd = [
            sys.executable,
            str(BATCH),
            "--limit-clips",
            str(int(args.limit_clips)),
        ]
        if args.resume:
            cmd.append("--resume")
        if str(args.faction or "").strip():
            cmd.extend(["--faction", str(args.faction)])
        elif use_active_faction:
            cmd.append("--active-faction")
        if args.preview_gif:
            cmd.append("--preview-gif")
        if args.memory_safe:
            cmd.append("--memory-safe")
        if args.gpu_fed:
            cmd.append("--gpu-fed")
        print(f"round {round_n}: {' '.join(cmd)}", flush=True)
        (ROOT / "artifacts/fused_push_skinned_rollout/fit_runs").mkdir(parents=True, exist_ok=True)
        log_path = (
            ROOT
            / "artifacts/fused_push_skinned_rollout/fit_runs"
            / f"batch_round_{round_n:04d}.log"
        )
        lock_retries = 0
        while True:
            if LOCK.is_file() and int(args.lock_wait_max) > 0:
                print(
                    f"GPU lock present ({LOCK}); waiting {float(args.lock_wait_sec):.0f}s "
                    f"before round {round_n}",
                    flush=True,
                )
                time.sleep(float(args.lock_wait_sec))
            with log_path.open("w", encoding="utf-8") as log_handle:
                proc = subprocess.run(
                    cmd,
                    cwd=str(ROOT),
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                )
            if proc.returncode == 0:
                break
            if (
                _log_mentions_lock(log_path)
                and lock_retries < int(args.lock_wait_max)
            ):
                lock_retries += 1
                print(
                    f"round {round_n}: GPU lock contention "
                    f"(retry {lock_retries}/{int(args.lock_wait_max)}); "
                    f"sleep {float(args.lock_wait_sec):.0f}s",
                    flush=True,
                )
                time.sleep(float(args.lock_wait_sec))
                continue
            # Fit-clip errors are fatal; blocked/missing-DEF units alone should not stop the loop.
            pending_after = _pending_jobs(
                resume=bool(args.resume),
                faction=str(args.faction or ""),
                active_faction=use_active_faction,
            )
            if pending_after < pending:
                print(
                    f"batch round {round_n} exit={proc.returncode} but pending "
                    f"{pending} -> {pending_after}; continuing",
                    flush=True,
                )
                break
            print(
                f"batch round {round_n} failed exit={proc.returncode} "
                f"(pending unchanged at {pending}); see {log_path}",
                flush=True,
            )
            return proc.returncode
        if float(args.sleep_sec) > 0:
            time.sleep(float(args.sleep_sec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
