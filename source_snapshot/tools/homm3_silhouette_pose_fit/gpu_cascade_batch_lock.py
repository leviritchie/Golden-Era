"""Exclusive lock so two GPU cascade batches cannot share one machine.

Windows WDDM keeps each nvdiffrast CUDA context in system RAM. A second
``run_crusader_gpu_cascade_animation_set.py`` (or a leftover Jupyter kernel)
does not make clips more thorough — it pages the first process until a
16-frame fit looks like a 40-minute clip.
"""
from __future__ import annotations

import json
import math
import os
import random
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from resource_lock_guard import advisory_guard

SCRIPT_TOKENS = (
    "run_crusader_gpu_cascade_animation_set.py",
    "run_gpu_cascade_animation_set.py",
    "run_dinov3_branch_vector_examples.py",
    "run_chain_space_surface_compare.py",
    "run_angel_dinov3_score_norm_compare.py",
    "run_angel_dinov3_sprite_change_gate.py",
    "run_angel_dinov3_still_sprite_lock.py",
    "run_angel_bone_order_compare.py",
    "run_angel_cascade_knob_compare.py",
    "run_angel_wing_dominance_compare.py",
    "tweak_gpu_clip_poses.py",
    "apply_circular_temporal_after_setup.py",
    "sprite_pose_feasibility.py",
    "sprite_body_surgery.py",
    "run_sprite_feasibility_surgery.py",
    "run_ragdoll_inertia_goblin.py",
    "run_roc_owned_silhouette_from_bind.py",
    "run_roc_stacked_small_pass.py",
    "run_roc_stacked_small_ik_pass.py",
    "run_roc_stacked_solve_compare.py",
    "run_roc_stacked_chain_space_root.py",
    "run_roc_stacked_dinov3_pass.py",
    "run_roc_stacked_dinov3_fast.py",
    "run_roc_stacked_dinov3_quick.py",
    "run_consolidated_walk_pipeline.py",
    "run_idle_prefix_refine.py",
    "run_prop_ik_polish.py",
    "run_clip_temporal_polish.py",
    "run_walk_plausibility_polish.py",
    "run_sprite_joint_rotation_mocap.py",
    "run_sprite_look_synth.py",
    "run_sprite_pose_head.py",
)
LOCK_FILENAME = "crusader_gpu_cascade_animation_set.lock"
GLOBAL_LOCK_RELATIVE_PATH = Path("artifacts/pose_picker_runs/gpu_cascade_global.lock")
PROCESS_QUERY_TIMEOUT_SEC = 10


class ProcessProbeError(RuntimeError):
    """Process inventory could not establish that legacy GPU work is absent."""


class CascadeLockError(RuntimeError):
    """The on-disk cascade lock is invalid or could not be read safely."""


class CascadeBusyError(RuntimeError):
    """Another cascade owner or legacy worker currently holds the GPU lane."""


class CascadeWaitTimeoutError(RuntimeError):
    """The caller's bounded wait expired before the cascade lane became free."""


def global_cascade_batch_lock_path(repo_root: Path) -> Path:
    """Return the one lock shared by every repo-local cascade runner."""

    return Path(repo_root) / GLOBAL_LOCK_RELATIVE_PATH


def pid_is_alive(pid: int) -> bool:
    pid = int(pid)
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        process_query_limited_information = 0x1000
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        ctypes.set_last_error(0)
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        error = ctypes.get_last_error()
        if error == 5:  # Access denied still proves the process exists.
            return True
        if error == 87:  # ERROR_INVALID_PARAMETER means there is no such PID.
            return False
        raise ProcessProbeError(
            f"cannot determine whether cascade lock owner pid {pid} is alive "
            f"(OpenProcess error {error})"
        )
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        raise ProcessProbeError(
            f"cannot determine whether cascade lock owner pid {pid} is alive: {exc}"
        ) from exc
    return True


def list_python_processes(
    *, timeout_sec: float = PROCESS_QUERY_TIMEOUT_SEC, self_pid: int | None = None
) -> list[dict[str, object]]:
    if os.name != "nt":
        raise ProcessProbeError("legacy GPU process inventory requires Windows CIM")
    command = r"""
$ErrorActionPreference = 'Stop'
$WarningPreference = 'Stop'
try {
    $rows = @(Get-CimInstance -ClassName Win32_Process |
        Where-Object { $_.Name -match 'python' } |
        Select-Object @{Name='ProcessId';Expression={[int]$_.ProcessId}},
                      @{Name='CommandLine';Expression={$_.CommandLine}})
    if ($rows.Count -eq 0) { throw 'CIM returned no Python processes' }
    $json = ConvertTo-Json -InputObject $rows -Compress -Depth 3
    Write-Output 'QUERY_OK'
    Write-Output $json
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 2
}
"""
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(0.001, float(timeout_sec)),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProcessProbeError(f"Windows CIM process inventory failed: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "no diagnostic").strip()
        raise ProcessProbeError(
            f"Windows CIM process inventory exited {completed.returncode}: {detail}"
        )
    if completed.stderr.strip():
        raise ProcessProbeError(
            f"Windows CIM process inventory emitted an error: {completed.stderr.strip()}"
        )
    lines = completed.stdout.splitlines()
    if len(lines) != 2 or lines[0].strip() != "QUERY_OK" or not lines[1].strip():
        raise ProcessProbeError("Windows CIM process inventory returned empty or malformed output")
    try:
        rows = json.loads(lines[1])
    except json.JSONDecodeError as exc:
        raise ProcessProbeError(f"Windows CIM process inventory returned invalid JSON: {exc}") from exc
    if not isinstance(rows, list) or not rows:
        raise ProcessProbeError("Windows CIM process inventory returned null or an empty process list")
    own_pid = os.getpid() if self_pid is None else int(self_pid)
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ProcessProbeError(f"Windows CIM process row {index} is not an object")
        process_id = row.get("ProcessId")
        command_line = row.get("CommandLine")
        if type(process_id) is not int or process_id <= 0:
            raise ProcessProbeError(f"Windows CIM process row {index} has invalid fields")
        if process_id == own_pid and (
            command_line is None
            or (isinstance(command_line, str) and not command_line.strip())
        ):
            row["CommandLine"] = ""
            continue
        if not isinstance(command_line, str) or not command_line.strip():
            raise ProcessProbeError(
                f"Windows CIM process row {index} has an unknown command line"
            )
    return rows


def live_cascade_batch_pids(
    *,
    self_pid: int,
    processes: Iterable[dict[str, object] | tuple[int, str]],
) -> list[int]:
    found: list[int] = []
    for process in processes:
        if isinstance(process, dict):
            pid = process.get("ProcessId")
            command_line = process.get("CommandLine")
        else:
            pid, command_line = process
        if type(pid) is not int or pid <= 0:
            raise ProcessProbeError("process inventory contains a row with invalid fields")
        if int(pid) == int(self_pid):
            continue
        if not isinstance(command_line, str) or not command_line.strip():
            raise ProcessProbeError("process inventory contains an unknown command line")
        folded_command_line = command_line.casefold()
        if any(token.casefold() in folded_command_line for token in SCRIPT_TOKENS):
            found.append(pid)
    return sorted(set(found))


def read_lock_pid(lock_path: Path) -> int | None:
    path = Path(lock_path)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as exc:
        raise CascadeLockError(f"cannot read GPU cascade batch lock {path}: {exc}") from exc
    if not text:
        raise CascadeLockError(f"GPU cascade batch lock is empty or malformed: {path}")
    try:
        owner = int(text[0].strip())
    except ValueError as exc:
        raise CascadeLockError(
            f"GPU cascade batch lock is empty or malformed (invalid first-line PID): {path}"
        ) from exc
    if owner <= 0:
        raise CascadeLockError(f"GPU cascade batch lock has an invalid PID {owner}: {path}")
    return owner


def _mutation_guard_path(path: Path) -> str:
    return str(path) + ".mutation.guard"


def acquire_cascade_batch_lock(
    lock_path: Path,
    *,
    pid: int | None = None,
    pid_alive: Callable[[int], bool] | None = None,
    processes: Iterable[dict[str, object] | tuple[int, str]] | None = None,
    list_processes: Callable[[], Iterable[dict[str, object] | tuple[int, str]]] | None = None,
    deadline: float | None = None,
) -> Path:
    path = Path(lock_path)
    self_pid = os.getpid() if pid is None else int(pid)
    checker = pid_is_alive if pid_alive is None else pid_alive
    path.parent.mkdir(parents=True, exist_ok=True)
    guard_path = _mutation_guard_path(path)

    # A live owner makes the common wait path a cheap PID check; do not invoke
    # PowerShell/CIM on every retry while another batch holds the lock.
    with advisory_guard(guard_path) as guarded:
        if not guarded:
            raise CascadeBusyError(f"GPU cascade lock mutation is busy: {path}")
        observed_owner = read_lock_pid(path)
        if observed_owner is not None and checker(observed_owner):
            raise CascadeBusyError(
                f"GPU cascade batch lock already exists for live pid {observed_owner}: {path}"
            )

    if processes is None:
        enumerator = list_python_processes if list_processes is None else list_processes
        if deadline is not None and list_processes is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CascadeBusyError("GPU cascade lock wait deadline expired before process inventory")
            processes = list_python_processes(
                timeout_sec=min(PROCESS_QUERY_TIMEOUT_SEC, remaining), self_pid=self_pid
            )
        else:
            processes = (
                list_python_processes(self_pid=self_pid)
                if list_processes is None
                else enumerator()
            )
    process_rows = list(processes)
    others = live_cascade_batch_pids(self_pid=self_pid, processes=process_rows)
    if others:
        raise CascadeBusyError(
            "another GPU cascade batch is running "
            f"(pid {', '.join(str(pid) for pid in others)}); refusing to overlap CUDA contexts"
        )
    if deadline is not None and time.monotonic() >= deadline:
        raise CascadeBusyError("GPU cascade lock wait deadline expired during process inventory")

    kernels = sorted(
        {
            int(row["ProcessId"] if isinstance(row, dict) else row[0])
            for row in process_rows
            if "ipykernel_launcher"
            in str(row.get("CommandLine", "") if isinstance(row, dict) else row[1]).casefold()
        }
    )
    if kernels:
        print(
            "WARNING: Jupyter kernel still running "
            f"(pid {', '.join(str(pid) for pid in kernels)}). "
            "It may retain a CUDA context in system RAM",
            flush=True,
        )

    # Serialize the final owner check, stale reap, exclusive create, and release
    # against other cooperating runners. Never reap an owner that appeared while
    # the one-off legacy-worker inventory was running.
    with advisory_guard(guard_path) as guarded:
        if not guarded:
            raise CascadeBusyError(f"GPU cascade lock mutation is busy: {path}")
        if deadline is not None and time.monotonic() >= deadline:
            raise CascadeBusyError("GPU cascade lock wait deadline expired before lock mutation")
        current_owner = read_lock_pid(path)
        if current_owner != observed_owner:
            raise CascadeBusyError(
                f"GPU cascade lock owner changed during acquisition: {path}"
            )
        if current_owner is not None:
            if checker(current_owner):
                raise CascadeBusyError(
                    f"GPU cascade batch lock already exists for live pid {current_owner}: {path}"
                )
            path.unlink(missing_ok=True)
            print(f"removed stale GPU cascade lock for dead pid {current_owner}: {path}", flush=True)
        try:
            handle = path.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raced_pid = read_lock_pid(path)
            raise CascadeBusyError(
                "another GPU cascade batch acquired the global lock"
                + (f" (pid {raced_pid})" if raced_pid is not None else "")
                + f": {path}"
            ) from exc
        created_stat = None
        try:
            try:
                created_stat = os.fstat(handle.fileno())
            except (AttributeError, OSError, ValueError):
                pass
            with handle:
                handle.write(f"{self_pid}\n")
        except BaseException:
            if created_stat is not None and getattr(created_stat, "st_ino", 0):
                try:
                    current_stat = path.stat()
                except OSError:
                    current_stat = None
                if current_stat is not None and (
                    current_stat.st_dev,
                    current_stat.st_ino,
                ) == (created_stat.st_dev, created_stat.st_ino):
                    path.unlink(missing_ok=True)
            raise
    return path


def release_cascade_batch_lock(lock_path: Path, *, pid: int | None = None) -> None:
    path = Path(lock_path)
    self_pid = os.getpid() if pid is None else int(pid)
    with advisory_guard(_mutation_guard_path(path)) as guarded:
        if not guarded:
            return
        try:
            existing = read_lock_pid(path)
        except CascadeLockError as exc:
            print(f"WARNING: preserving unreadable GPU cascade lock {path}: {exc}", flush=True)
            return
        if existing == self_pid:
            path.unlink(missing_ok=True)


@contextmanager
def cascade_batch_lock(repo_root: Path) -> Iterator[Path]:
    """Hold the global GPU cascade lock until the with-block exits, including abort."""
    path = global_cascade_batch_lock_path(Path(repo_root))
    acquired = acquire_cascade_batch_lock(path)
    try:
        yield acquired
    finally:
        release_cascade_batch_lock(acquired)


@contextmanager
def wait_for_cascade_batch_lock(
    repo_root: Path,
    *,
    timeout_sec: float = 1800.0,
    poll_sec: float = 5.0,
) -> Iterator[tuple[Path, float]]:
    """Wait for the shared lock with capped backoff; only typed busy errors retry."""
    timeout = float(timeout_sec)
    poll = float(poll_sec)
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("cascade lock timeout_sec must be finite and nonnegative")
    if not math.isfinite(poll) or poll <= 0:
        raise ValueError("cascade lock poll_sec must be finite and positive")
    started = time.monotonic()
    deadline = started + timeout
    retry_delay = min(30.0, max(5.0, poll))
    lock_path = global_cascade_batch_lock_path(Path(repo_root))

    while True:
        try:
            acquired = acquire_cascade_batch_lock(lock_path, deadline=deadline)
        except CascadeBusyError as exc:
            now = time.monotonic()
            remaining = deadline - now
            if remaining <= 0:
                waited = now - started
                raise CascadeWaitTimeoutError(
                    f"timed out waiting for GPU lock after {waited:.1f}s: {exc}"
                ) from exc
            waited = now - started
            sleep_sec = min(retry_delay * random.uniform(0.8, 1.2), 30.0, remaining)
            print(f"waiting for GPU lock ({waited:.0f}s): {exc}", flush=True)
            time.sleep(sleep_sec)
            retry_delay = min(30.0, retry_delay * 2.0)
            continue
        break

    try:
        yield acquired, time.monotonic() - started
    finally:
        release_cascade_batch_lock(acquired)
