#!/usr/bin/env python3
"""Keep the exclusive SmartRig GPU cascade running until chosen clips finish.

Does not take the GPU lock while a cascade is alive. When the current fit
process dies, starts one successor: ``run_gpu_cascade_animation_set.py
--fit-only --skip-existing``. Never starts a second CUDA cascade.

If the live process (which may still hold an old in-memory rest list) starts
a ShootUp (14) or ShootDown (16) job, stop only that process and let the
successor load the updated disk plan.

This is a watcher, not a fitter. It does not install into Golden Era.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
OUT = ROOT / "artifacts/homm3_smartrig_skinned_rollout"
LOCK = ROOT / "artifacts/pose_picker_runs/gpu_cascade_global.lock"
RUNNER = TOOL / "run_gpu_cascade_animation_set.py"
LOG = OUT / "gpu_successor.log"
BATCH_LOG = OUT / "fit_batch.log"

FORBIDDEN_GROUPS = frozenset({14, 16})
FIT_LINE = re.compile(r"^fit (?P<anim>\S+) groups=\[(?P<groups>[^\]]*)\]")

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (  # noqa: E402
    list_python_processes,
    live_cascade_batch_pids,
    pid_is_alive,
    read_lock_pid,
)


def _log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    line = time.strftime("%Y-%m-%dT%H:%M:%S") + " " + message
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _live_cascade_pids() -> list[int]:
    return live_cascade_batch_pids(self_pid=0, processes=list_python_processes())


def _lock_owner() -> int | None:
    pid = read_lock_pid(LOCK)
    if pid is None:
        return None
    return pid if pid_is_alive(pid) else None


def _progress() -> dict:
    path = OUT / "progress.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_log_tail(max_bytes: int = 1048576) -> str:
    if not BATCH_LOG.is_file():
        return ""
    data = BATCH_LOG.read_bytes()
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    return data.decode("utf-8", errors="replace")


def _latest_fit_line(previous: str = "") -> str:
    last = previous
    for line in _read_log_tail().splitlines():
        if line.startswith("fit "):
            last = line
    return last


def _forbidden_job(line: str, progress: dict) -> str:
    if line:
        match = FIT_LINE.match(line)
        if match:
            anim = match.group("anim").lower()
            groups = []
            raw = match.group("groups").strip()
            if raw:
                groups = [int(part.strip()) for part in raw.split(",") if part.strip()]
            if "shoot_up" in anim or "shoot_down" in anim:
                return line
            if FORBIDDEN_GROUPS.intersection(groups):
                return line
        low = line.lower()
        if "shoot_up" in low or "shoot_down" in low:
            return line
    last = (progress.get("last") or [{}])[-1] if isinstance(progress.get("last"), list) else {}
    anim = str((last or {}).get("animation") or "").lower()
    groups = [int(g) for g in ((last or {}).get("groups") or [])]
    if "shoot_up" in anim or "shoot_down" in anim or FORBIDDEN_GROUPS.intersection(groups):
        return f"progress {anim} groups={groups}"
    return ""


def _terminate_pid(pid: int) -> None:
    pid = int(pid)
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(1, False, pid)
        if not handle:
            _log(f"OpenProcess {pid} failed")
            return
        ok = bool(kernel32.TerminateProcess(handle, 1))
        kernel32.CloseHandle(handle)
        _log(f"TerminateProcess {pid} ok={ok}")
        return
    try:
        os.kill(pid, signal.SIGTERM)
        _log(f"SIGTERM {pid}")
    except OSError as exc:
        _log(f"SIGTERM {pid} failed: {exc}")


def main() -> int:
    poll_s = 15
    last_fit = ""
    _log("watcher start; will not start a second CUDA cascade while one is live")
    while True:
        owner = _lock_owner()
        live = _live_cascade_pids()
        prog = _progress()
        if owner or live:
            last_fit = _latest_fit_line(last_fit)
            why = _forbidden_job(last_fit, prog) if live else ""
            fit_line = last_fit
            if why:
                _log(
                    f"stopping live cascade {live}: forbidden vertical clip ({why})"
                )
                for pid in live:
                    _terminate_pid(pid)
                last_fit = ""
                time.sleep(3)
                continue
            _log(
                f"gpu live owner={owner} pids={live} "
                f"okClips={prog.get('okClips')} updatedAt={prog.get('updatedAt')} "
                f"current={fit_line[:120]}"
            )
            time.sleep(poll_s)
            continue
        _log(
            "no live cascade; starting exclusive successor "
            "--fit-only --skip-existing"
        )
        log_handle = BATCH_LOG.open("a", encoding="utf-8")
        started = subprocess.Popen(
            [
                sys.executable,
                "-u",
                str(RUNNER),
                "--fit-only",
                "--skip-existing",
            ],
            cwd=str(ROOT),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        _log(f"successor pid {started.pid}")
        deadline = time.time() + 30
        while time.time() < deadline:
            if _lock_owner() or started.poll() is not None:
                break
            time.sleep(1)
        if started.poll() is not None:
            _log(f"successor {started.pid} exited immediately code={started.returncode}")
            return int(started.returncode or 1)
        time.sleep(poll_s)


if __name__ == "__main__":
    raise SystemExit(main())
