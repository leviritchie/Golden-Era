"""The one GPU gate of the full-3D town lane's model runs (SDXL inpaint, monocular depth).

    with town_full3d_gpu.gate("sdfill castle", need_vram_gb=11.0):
        ...load the model and run...

 Capacity is checked before either reservation. The town single-flight lock is then taken, followed by one nonblocking
 machine-wide gpuslot attempt. If the slot is busy, the town lock is released before retrying. Once both are held, the
 requested capacity is rechecked without waiting; a lost race releases both reservations before capacity is checked
 again. An impossible request (need plus the existing VRAM margin exceeds physical GPU memory) refuses immediately.
 The town lock is an atomic mkdir holding owner.json. A holder is broken as stale ONLY when its process is provably
 gone, confirmed twice STALE_CONFIRM_S apart. Access denied conservatively retains a live owner without a creation pin;
 other process-probe errors fail fast and preserve the lock. A lock with no owner.json is broken only after
 gpuslot.NO_OWNER_GRACE_S. The machine-wide gpuslot remains the
 same semaphore used by Blender bakes.
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import random
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "artifacts" / "homm3_town_full3d_locks" / "gpu"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "homm3_unit_look"))
sys.path.insert(0, str(ROOT / "tools" / "homm3_def_retarget"))
from resource_lock_guard import advisory_guard  # noqa: E402
import gpuslot  # noqa: E402
import memgate  # noqa: E402

MIN_RAM_GB = 5.0
STALE_CONFIRM_S = 5.0
VRAM_MARGIN_GB = 2.5


def vram_ok(free_gb: float, need_gb: float) -> bool:
    """Free VRAM covers the run's need plus the margin (fail closed: a NaN or missing reading is not enough)."""
    return bool(free_gb >= need_gb + VRAM_MARGIN_GB)


def _capacity_snapshot() -> tuple[float, float, float, float]:
    try:
        free_ram, total_ram = memgate.memory_gb()
        free_vram, total_vram = memgate.vram_gb()
    except memgate.ProbeError as e:
        raise SystemExit(f"town gpu: memgate probe failed ({e}); not starting") from e
    values = (free_ram, total_ram, free_vram, total_vram)
    if (any(not math.isfinite(value) for value in values) or free_ram < 0 or total_ram <= 0 or
            free_ram > total_ram or free_vram < 0 or total_vram <= 0 or free_vram > total_vram):
        raise SystemExit(f"town gpu: memgate returned invalid capacity snapshot {values!r}; not starting")
    return free_ram, total_ram, free_vram, total_vram


def _capacity_problem(need_vram_gb: float, snapshot=None) -> str | None:
    try:
        need_vram_gb = float(need_vram_gb)
    except (TypeError, ValueError) as e:
        raise SystemExit(f"town gpu: invalid VRAM request {need_vram_gb!r} GB") from e
    if not math.isfinite(need_vram_gb) or need_vram_gb < 0:
        raise SystemExit(f"town gpu: invalid VRAM request {need_vram_gb!r} GB")
    free_ram, total_ram, free_vram, total_vram = snapshot or _capacity_snapshot()

    required_vram = need_vram_gb + VRAM_MARGIN_GB
    if total_ram < MIN_RAM_GB:
        return f"impossible on this hardware: total RAM {total_ram:.1f} GB < required {MIN_RAM_GB:.1f} GB"
    if total_vram < required_vram:
        return (f"impossible on this hardware: total VRAM {total_vram:.1f} GB < required {need_vram_gb:.1f} GB "
                f"+ margin {VRAM_MARGIN_GB:.1f} GB")
    if free_ram < MIN_RAM_GB or not vram_ok(free_vram, need_vram_gb):
        return (f"free RAM {free_ram:.1f} GB / VRAM {free_vram:.1f} GB < required {MIN_RAM_GB:.1f} GB / "
                f"{need_vram_gb:.1f} GB + margin {VRAM_MARGIN_GB:.1f} GB")
    return None


def _wait_for_capacity(tag: str, need_vram_gb: float, deadline: float, wait_min: float) -> None:
    while True:
        problem = _capacity_problem(need_vram_gb)
        if problem is None:
            return
        if problem.startswith("impossible on this hardware"):
            raise SystemExit(f"town gpu: {problem}; not starting")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SystemExit(f"town gpu: {tag}: {problem} after {wait_min:.0f} min; not starting")
        print(f"TOWN GPU waiting for capacity {tag}: {problem}", flush=True)
        time.sleep(min(30 + random.uniform(0, 15), remaining))


def _creation_time(pid: int):
    """Return the shared PID/API probe result; unexpected Win32 failures remain diagnostic."""
    return gpuslot._process_state(pid)


def holder_state(h: dict) -> str:
    """Return live/gone or fail with a PID/API diagnostic; never downgrade probe failure to contention."""
    try:
        pid = int(h["pid"])
        if pid <= 0:
            raise ValueError("PID must be positive")
    except (KeyError, TypeError, ValueError) as exc:
        raise gpuslot.SlotProcessProbeError(f"town GPU lock has an invalid owner PID: {exc}") from exc
    try:
        state, ct = _creation_time(pid)
    except gpuslot.SlotProcessProbeError:
        raise
    except Exception as exc:
        raise gpuslot.SlotProcessProbeError(f"town GPU lock PID {pid} probe failed: {exc}") from exc
    if state not in ("alive", "gone"):
        raise gpuslot.SlotProcessProbeError(f"town GPU lock PID {pid} probe returned {state!r}")
    if state == "alive" and ct is not None and h.get("created") is not None:
        try:
            reused = int(h["created"]) != ct
        except (TypeError, ValueError) as exc:
            raise gpuslot.SlotMetadataError(f"town GPU lock has an invalid creation time for PID {pid}: {exc}") from exc
        if reused:
            return "gone"                                      # the PID now belongs to another process
    return state


def _take(tag: str) -> bool:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.mkdir(LOCK)
    except FileExistsError:
        _reap_stale_town_lock()
        return False
    try:
        state, created = _creation_time(os.getpid())
        if state != "alive":
            raise gpuslot.SlotProcessProbeError(
                f"town GPU lock owner PID {os.getpid()} was not confirmed alive during acquisition: {state!r}"
            )
        owner_path = LOCK / "owner.json"
        temporary_path = LOCK / f"owner.json.tmp-{os.getpid()}"
        temporary_path.write_text(json.dumps({"pid": os.getpid(), "created": created, "since": time.time(),
                                              "tag": tag}), encoding="utf-8")
        os.replace(temporary_path, owner_path)
    except BaseException:
        shutil.rmtree(LOCK, ignore_errors=True)
        raise
    return True


def _reap_stale_town_lock() -> bool:
    guard_path = LOCK.with_name(f".{LOCK.name}.reap.lock")
    with advisory_guard(guard_path) as acquired:
        if not acquired or not LOCK.is_dir():
            return False
        h = gpuslot.owner(str(LOCK))
        if h is None:
            if (LOCK / "owner.json").exists():
                return False
            try:
                stale = time.time() - LOCK.stat().st_mtime > gpuslot.NO_OWNER_GRACE_S
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise gpuslot.SlotMetadataError(
                    f"cannot inspect town GPU lock directory {LOCK}: {exc}; lock preserved. "
                    "Inspect the owner and repair/remove the lock only after confirming its process is stopped."
                ) from exc
            if stale and gpuslot.owner(str(LOCK)) is not None:
                return False
        else:
            if holder_state(h) != "gone":
                return False
            time.sleep(STALE_CONFIRM_S)
            h2 = gpuslot.owner(str(LOCK))
            if h2 != h or holder_state(h2) != "gone":
                return False
        print(f"TOWN GPU LOCK breaking stale holder {h} (provably gone)", flush=True)
        shutil.rmtree(LOCK, ignore_errors=True)
        return not LOCK.exists()


def _release_town_lock(expected_owner: dict | None) -> None:
    if not expected_owner:
        return
    guard_path = LOCK.with_name(f".{LOCK.name}.reap.lock")
    with advisory_guard(guard_path) as acquired:
        if acquired and gpuslot.owner(str(LOCK)) == expected_owner:
            shutil.rmtree(LOCK, ignore_errors=True)


@contextlib.contextmanager
def gate(tag: str, need_vram_gb: float, wait_min: float = 120.0):
    try:
        wait_min = float(wait_min)
    except (TypeError, ValueError) as e:
        raise SystemExit(f"town gpu: invalid wait timeout {wait_min!r} min") from e
    if not math.isfinite(wait_min) or wait_min < 0:
        raise SystemExit(f"town gpu: invalid wait timeout {wait_min!r} min")
    deadline = time.monotonic() + wait_min * 60
    while True:
        _wait_for_capacity(tag, need_vram_gb, deadline, wait_min)
        gpuslot.reap_stale_slots()
        if not _take(tag):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SystemExit(f"town gpu: lock held by {gpuslot.owner(str(LOCK))} for {wait_min:.0f} min; not starting")
            time.sleep(min(20 + random.uniform(0, 10), remaining))
            continue

        retry_reason = None
        town_owner = gpuslot.owner(str(LOCK))
        try:
            with gpuslot.try_slot([sys.executable, tag], unit=f"town:{tag}") as slot_path:
                if slot_path is None:
                    retry_reason = "machine-wide GPU slots are busy"
                else:
                    snapshot = _capacity_snapshot()
                    retry_reason = _capacity_problem(need_vram_gb, snapshot)
                    if retry_reason and retry_reason.startswith("impossible on this hardware"):
                        raise SystemExit(f"town gpu: {retry_reason}; not starting")
                    if retry_reason is None:
                        free_ram, _, free_vram, _ = snapshot
                        print(f"TOWN GPU OK {tag}: free RAM {free_ram:.1f} GB, free VRAM {free_vram:.1f} GB "
                              f"(need {need_vram_gb:.1f} GB + margin {VRAM_MARGIN_GB:.1f} GB)", flush=True)
                        yield
                        return
        finally:
            _release_town_lock(town_owner)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SystemExit(f"town gpu: {retry_reason or 'capacity changed during reservation'} after "
                             f"{wait_min:.0f} min; not starting")
        if retry_reason:
            print(f"TOWN GPU released reservations before retry: {tag}: {retry_reason}", flush=True)
            time.sleep(min(20 + random.uniform(0, 10), remaining))
