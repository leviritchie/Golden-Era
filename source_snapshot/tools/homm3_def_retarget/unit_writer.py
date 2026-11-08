"""Hold one OS lock for an existing per-unit command chain.

Usage: python tools/homm3_def_retarget/unit_writer.py UNIT -- COMMAND [ARG ...]

The command can be a shell chain containing run_unit.sh and fleet_rebuild.py, or a
single existing unit-look operation. This is not a queue or a resource gate. A
blocked child is assigned to a Windows kill-on-close Job Object before it may run.
The supervisor and child hold different bytes of one per-unit lock file: the
supervisor keeps its byte through Job cleanup, while the child keeps its byte
through the command. Lock files stay on disk; OS locks release on process exit.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import re
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
UNIT_CONFIGS = ROOT / "tools/homm3_def_retarget/units"
LOCK_DIR = ROOT / "artifacts/homm3_def_retarget/_unit_writer_locks"
UNIT_KEY = re.compile(r"[a-z][a-z0-9_]*\Z")


class UnitLockUnavailable(RuntimeError):
    pass


def validate_unit(unit: str) -> None:
    if not UNIT_KEY.fullmatch(unit) or not (UNIT_CONFIGS / f"{unit}.json").is_file():
        raise ValueError(f"unknown or noncanonical unit key: {unit!r}")


def _lock_file(handle, offset: int, length: int) -> None:
    if os.name == "nt":
        import msvcrt
        handle.seek(offset)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, length)
    else:
        import fcntl
        fcntl.lockf(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB, length, offset)


def _unlock_file(handle, offset: int, length: int) -> None:
    if os.name == "nt":
        import msvcrt
        handle.seek(offset)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, length)
    else:
        import fcntl
        fcntl.lockf(handle.fileno(), fcntl.LOCK_UN, length, offset)


@contextmanager
def hold_unit_lock(unit: str, lock_dir: Path = LOCK_DIR, role: str = "all"):
    validate_unit(unit)
    offsets = {"all": (0, 2), "supervisor": (0, 1), "writer": (1, 1)}
    if role not in offsets:
        raise ValueError(f"invalid unit lock role: {role!r}")
    offset, length = offsets[role]
    lock_dir.mkdir(parents=True, exist_ok=True)
    path = lock_dir / f"{unit}.lock"
    try:
        with path.open("a+b") as handle:
            size = handle.seek(0, os.SEEK_END)
            if size < 2:
                handle.write(b"\0" * (2 - size))
                handle.flush()
            try:
                _lock_file(handle, offset, length)
            except OSError as exc:
                raise UnitLockUnavailable(f"{unit}: another writer is active or the lock is unavailable: {exc}") from exc
            try:
                yield path
            finally:
                _unlock_file(handle, offset, length)
    except OSError as exc:
        raise UnitLockUnavailable(f"{unit}: lock file unavailable: {exc}") from exc


def _command_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("unit")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command after -- is required")
    validate_unit(args.unit)
    return args.unit, command


def _child(argv) -> int:
    unit, command = _command_args(argv)
    if sys.stdin.buffer.read(1) != b"1":
        print("UNIT_WRITER REFUSED supervisor did not assign job", file=sys.stderr, flush=True)
        return 1
    try:
        with hold_unit_lock(unit, role="writer"):
            print(f"UNIT_WRITER ACQUIRED {unit}", flush=True)
            return subprocess.run(command, cwd=ROOT).returncode
    except (ValueError, UnitLockUnavailable, OSError) as exc:
        print(f"UNIT_WRITER REFUSED {exc}", file=sys.stderr, flush=True)
        return 1


def _drain_job(job, win32job) -> None:
    win32job.TerminateJobObject(job, 1)
    deadline = time.monotonic() + 30
    while win32job.QueryInformationJobObject(job, win32job.JobObjectBasicAccountingInformation)["ActiveProcesses"]:
        if time.monotonic() >= deadline:
            raise UnitLockUnavailable("Job Object did not drain after termination")
        time.sleep(.05)


def _supervised_run(unit: str, command: list[str]) -> int:
    try:
        import win32api
        import win32con
        import win32job
    except ImportError as exc:
        raise UnitLockUnavailable(f"pywin32 Job Object support is required: {exc}") from exc

    with hold_unit_lock(unit, role="supervisor"):
        job = win32job.CreateJobObject(None, "")
        limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        limits["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        child = None
        assigned = False
        try:
            child = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--_child", unit, "--", *command],
                stdin=subprocess.PIPE, cwd=ROOT,
            )
            process = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, child.pid)
            try:
                win32job.AssignProcessToJobObject(job, process)
                assigned = True
            finally:
                process.Close()
            child.stdin.write(b"1")
            child.stdin.close()
            return child.wait()
        finally:
            if child is not None and child.stdin is not None and not child.stdin.closed:
                child.stdin.close()
            try:
                if assigned:
                    _drain_job(job, win32job)
            finally:
                job.Close()
            if child is not None and child.poll() is None:
                if not assigned:
                    child.terminate()
                child.wait(timeout=10)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--_child"]:
        return _child(argv[1:])
    try:
        unit, command = _command_args(argv)
        return _supervised_run(unit, command)
    except (ValueError, UnitLockUnavailable, OSError) as exc:
        print(f"UNIT_WRITER REFUSED {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
