#!/usr/bin/env python3
"""Keep the Castle fused_push batch loop alive until pendingJobs==0.

Restarts the loop if the process exits unexpectedly. Does not start a second
CUDA cascade while a batch child holds the GPU lock — the loop script already
waits on lock contention.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
LOOP = ROOT / "tools/homm3_silhouette_pose_fit/run_fused_push_batch_loop.py"
BATCH = ROOT / "tools/homm3_silhouette_pose_fit/run_fused_push_batch_all_units.py"
SNAPSHOT = ROOT / "tools/homm3_silhouette_pose_fit/castle_fused_push_progress_snapshot.py"
OUT = ROOT / "artifacts/fused_push_skinned_rollout"


def _pending(faction: str) -> int:
    proc = subprocess.run(
        [
            sys.executable,
            str(BATCH),
            "--faction",
            faction,
            "--resume",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "dry-run failed")
    text = proc.stdout or ""
    # last pendingJobs in the summary JSON
    key = '"pendingJobs"'
    idx = text.rfind(key)
    if idx < 0:
        raise RuntimeError("dry-run missing pendingJobs")
    fragment = text[idx : idx + 40]
    digits = "".join(ch for ch in fragment.split(":", 1)[1] if ch.isdigit())
    return int(digits)


def _log_path(faction: str) -> Path:
    slug = str(faction or "faction").strip().replace("homm3_", "")
    return OUT / "fit_runs" / f"{slug}_fused_push_keepalive.log"


LOG = _log_path("castle")


def _fit_proc_rows() -> list[tuple[int, str]]:
    """(pid, commandLine) for batch loop / unit batch only (not keepalive)."""
    out = subprocess.check_output(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
            "| Where-Object { "
            "$_.CommandLine -like '*run_fused_push_batch_loop.py*' "
            "-or $_.CommandLine -like '*run_fused_push_batch_all_units.py*' "
            "} | ForEach-Object { "
            "Write-Output ($_.ProcessId.ToString() + '|' + $_.CommandLine) "
            "}",
        ],
        text=True,
        errors="replace",
    )
    rows: list[tuple[int, str]] = []
    for line in out.splitlines():
        if "|" not in line:
            continue
        pid_s, cmd = line.split("|", 1)
        pid_s = pid_s.strip()
        if pid_s.isdigit():
            rows.append((int(pid_s), cmd))
    return rows


def _fit_pids() -> list[int]:
    """PIDs for the batch loop / unit batch only (not this keepalive)."""
    return [pid for pid, _cmd in _fit_proc_rows()]


def _loop_limit_mismatch(desired: int) -> list[int]:
    """Return loop PIDs whose --limit-clips does not match desired."""
    import re

    bad: list[int] = []
    for pid, cmd in _fit_proc_rows():
        if "run_fused_push_batch_loop.py" not in cmd:
            continue
        match = re.search(r"--limit-clips(?:\s+|=)(\d+)", cmd)
        if match is None or int(match.group(1)) != int(desired):
            bad.append(pid)
    return bad


def _all_units_running() -> bool:
    return any("run_fused_push_batch_all_units.py" in cmd for _pid, cmd in _fit_proc_rows())


def _start_loop(faction: str, limit_clips: int, preview_gif: bool, log) -> None:
    cmd = [
        sys.executable,
        str(LOOP),
        "--faction",
        faction,
        "--limit-clips",
        str(int(limit_clips)),
        "--resume",
    ]
    if preview_gif:
        cmd.append("--preview-gif")
    log(f"keepalive: restarting loop {' '.join(cmd)}")
    with LOG.open("a", encoding="utf-8") as handle:
        subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=handle,
            stderr=subprocess.STDOUT,
        )


def _try_export_ready(faction: str, log) -> None:
    """Export any unit whose delivery clips are already on disk (no GPU lock)."""
    cmd = [
        sys.executable,
        str(BATCH),
        "--faction",
        faction,
        "--resume",
        "--export-only",
    ]
    log(f"keepalive: export-ready {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, errors="replace")
    tail = (proc.stdout or "")[-1200:]
    if tail.strip():
        log(tail)
    if proc.returncode != 0:
        log(f"keepalive: export-ready exit={proc.returncode}")


def _write_progress_snapshot(log) -> None:
    """Refresh castle_progress_snapshot.json (dry-run inventory; no GPU)."""
    if not SNAPSHOT.is_file():
        log(f"keepalive: snapshot script missing: {SNAPSHOT}")
        return
    proc = subprocess.run(
        [sys.executable, str(SNAPSHOT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        errors="replace",
    )
    if proc.returncode != 0:
        log(f"keepalive: snapshot exit={proc.returncode} {(proc.stderr or proc.stdout or '')[-400:]}")
        return
    # Prefer compact one-liner from written file over full stdout.
    snap_path = OUT / "castle_progress_snapshot.json"
    if snap_path.is_file():
        try:
            payload = json.loads(snap_path.read_text(encoding="utf-8"))
            log(
                json.dumps(
                    {
                        "snapshot": True,
                        "pendingJobs": payload.get("pendingJobs"),
                        "completedJobs": payload.get("completedJobs"),
                        "clipJobs": payload.get("clipJobs"),
                        "completedFraction": payload.get("completedFraction"),
                        "etaMinutesRough": payload.get("etaMinutesRough"),
                        "activeUnits": (payload.get("activeUnits") or [])[:3],
                        "lowScoreUnits": (payload.get("lowScoreUnits") or [])[:3],
                        "planBlocked": payload.get("planBlocked") or [],
                    }
                )
            )
        except Exception as exc:
            log(f"keepalive: snapshot parse failed: {exc}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--faction", default="castle")
    parser.add_argument("--limit-clips", type=int, default=12)
    parser.add_argument("--preview-gif", action="store_true", default=True)
    parser.add_argument("--poll-sec", type=float, default=60.0)
    parser.add_argument(
        "--export-every",
        type=int,
        default=5,
        help="attempt --export-only every N polls (0 disables)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    global LOG
    args = parse_args(argv)
    faction = str(args.faction)
    LOG = _log_path(faction)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    poll_n = 0

    def log(msg: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
        print(line, flush=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    while True:
        pending = _pending(faction)
        log(json.dumps({"pendingJobs": pending, "fitPids": _fit_pids()}))
        if str(faction).replace("homm3_", "") == "castle":
            try:
                _write_progress_snapshot(log)
            except Exception as exc:
                log(f"keepalive: snapshot failed: {exc}")
        if pending <= 0:
            _try_export_ready(faction, log)
            log("keepalive: pendingJobs=0; fit wave complete (non-blocked)")
            return 0

        pids = _fit_pids()
        mismatch = _loop_limit_mismatch(int(args.limit_clips))
        if mismatch:
            if _all_units_running():
                # Kill only the stale loop parent; leave the GPU fit alone.
                # When all_units exits, keepalive will start a limit-matched loop.
                log(
                    f"keepalive: loop limit-clips mismatch pids={mismatch} "
                    f"desired={int(args.limit_clips)}; killing stale loop "
                    "(all_units continues)"
                )
                for pid in mismatch:
                    subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False)
                time.sleep(1)
                pids = _fit_pids()
            else:
                log(
                    f"keepalive: loop limit-clips mismatch pids={mismatch} "
                    f"desired={int(args.limit_clips)}; recycling"
                )
                for pid in mismatch:
                    subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False)
                time.sleep(2)
                pids = _fit_pids()
        if not pids:
            _start_loop(
                faction,
                int(args.limit_clips),
                bool(args.preview_gif),
                log,
            )

        poll_n += 1
        if int(args.export_every) > 0 and poll_n % int(args.export_every) == 0:
            try:
                _try_export_ready(faction, log)
            except Exception as exc:
                log(f"keepalive: export-ready failed: {exc}")

        time.sleep(float(args.poll_sec))


if __name__ == "__main__":
    raise SystemExit(main())
