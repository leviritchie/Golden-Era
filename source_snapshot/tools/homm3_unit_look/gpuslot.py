"""Machine-wide GPU slot semaphore for Blender bakes (mirrors tools/homm3_vfx/unitylock.py).

memgate only checks free memory; it does not see a GPU that is saturated by bakes that already
hold their memory. Every Blender launch from look.py takes one of N slots first, so the whole
machine runs at most N Blender bakes at once no matter how many agents drive look.py:

    with gpuslot.slot(cmd, unit):      # blocks until a slot is free, then runs launch_guard inside it
        subprocess.run(cmd, ...)

A slot is an atomic ``os.mkdir`` of ``artifacts/homm3_unit_look/_gpu_slots/slot_<i>`` holding
``owner.json`` {pid, created, since, cmd, unit}. A slot is broken only when its holder is provably
gone (``holder_state``: OpenProcess reports no such PID (ERROR_INVALID_PARAMETER) or an exited
process, or the PID's creation time differs from the recorded ``created``, i.e. the PID was reused),
confirmed twice STALE_CONFIRM_S apart. Access denied conservatively retains the slot without a
creation pin; any other probe error fails fast and preserves it. A dir with no owner.json yet is only broken once it is older than a
minute, so a racing mkdir is not stolen. Release is an rmtree in ``finally``, including after a
failure or timeout.

Knobs (environment): HOMM3_BLENDER_SLOTS (default 3), HOMM3_BLENDER_SLOT_WAIT minutes to wait
for a slot before giving up (default 240). Blender launches outside look.py are not counted.

    python tools/homm3_unit_look/gpuslot.py status     # shows the holders
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import random
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from resource_lock_guard import advisory_guard

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SLOTS_DIR = os.path.join(ROOT, "artifacts", "homm3_unit_look", "_gpu_slots")
LAUNCH_GUARD = os.path.join(ROOT, "tools", "homm3_def_retarget", "launch_guard.py")
NO_OWNER_GRACE_S = 60
STALE_CONFIRM_S = 5.0


class SlotError(Exception):
    pass


class SlotMetadataError(SlotError):
    pass


class SlotProcessProbeError(SlotError):
    pass


def n_slots() -> int:
    try:
        return max(1, int(os.environ.get("HOMM3_BLENDER_SLOTS", "3")))
    except ValueError:
        raise SlotError(f"HOMM3_BLENDER_SLOTS={os.environ['HOMM3_BLENDER_SLOTS']!r} is not an integer")


def wait_minutes() -> float:
    try:
        return float(os.environ.get("HOMM3_BLENDER_SLOT_WAIT", "240"))
    except ValueError:
        raise SlotError(f"HOMM3_BLENDER_SLOT_WAIT={os.environ['HOMM3_BLENDER_SLOT_WAIT']!r} is not a number")


def _process_state(pid: int):
    """Return ('alive'|'gone', creation FILETIME) or raise a diagnostic probe error.

    Access denied proves the PID may still be alive. GetProcessTimes failure after STILL_ACTIVE
    also retains the live owner but omits the creation pin; it cannot justify breaking a lock.
    """
    import ctypes
    from ctypes import wintypes
    probe_failed = False
    try:
        pid = int(pid)
        if pid <= 0:
            raise ValueError("PID must be positive")
        if pid > 0xFFFFFFFF:
            raise ValueError("PID exceeds the Win32 DWORD range")
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    except Exception as exc:
        raise SlotProcessProbeError(f"OpenProcess setup failed for PID {pid!r}: {exc}") from exc
    try:
        h = k32.OpenProcess(0x1000, False, pid)              # PROCESS_QUERY_LIMITED_INFORMATION
    except Exception as exc:
        raise SlotProcessProbeError(f"OpenProcess failed for PID {pid}: {exc}") from exc
    if not h:
        try:
            error = ctypes.get_last_error()
        except Exception as exc:
            raise SlotProcessProbeError(f"OpenProcess failed for PID {pid}; could not read Win32 error: {exc}") from exc
        if error == 87:                                      # ERROR_INVALID_PARAMETER: PID does not exist
            return "gone", None
        if error == 5:                                       # ERROR_ACCESS_DENIED: do not break its reservation
            return "alive", None
        raise SlotProcessProbeError(f"OpenProcess failed for PID {pid}: WinError {error}")
    try:
        code = wintypes.DWORD()
        try:
            exit_ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        except Exception as exc:
            raise SlotProcessProbeError(f"GetExitCodeProcess failed for PID {pid}: {exc}") from exc
        if not exit_ok:
            try:
                error = ctypes.get_last_error()
            except Exception as exc:
                raise SlotProcessProbeError(
                    f"GetExitCodeProcess failed for PID {pid}; could not read Win32 error: {exc}"
                ) from exc
            raise SlotProcessProbeError(f"GetExitCodeProcess failed for PID {pid}: WinError {error}")
        if code.value != 259:                                  # STILL_ACTIVE
            return "gone", None
        c, e, kt, ut = (wintypes.FILETIME() for _ in range(4))
        try:
            times_ok = k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut))
        except Exception as exc:
            raise SlotProcessProbeError(f"GetProcessTimes raised for live PID {pid}: {exc}") from exc
        if not times_ok:
            return "alive", None
        return "alive", (c.dwHighDateTime << 32) | c.dwLowDateTime
    except BaseException:
        probe_failed = True
        raise
    finally:
        try:
            close_ok = k32.CloseHandle(h)
        except Exception as exc:
            if not probe_failed:
                raise SlotProcessProbeError(f"CloseHandle failed for PID {pid}: {exc}") from exc
        else:
            if not close_ok and not probe_failed:
                try:
                    error = ctypes.get_last_error()
                except Exception as exc:
                    raise SlotProcessProbeError(
                        f"CloseHandle failed for PID {pid}; could not read Win32 error: {exc}"
                    ) from exc
                raise SlotProcessProbeError(f"CloseHandle failed for PID {pid}: WinError {error}")


def process_created(pid: int):
    """Return a creation pin when available; access denial is live but has no pin."""
    try:
        state, ct = _process_state(pid)
    except SlotProcessProbeError:
        raise
    except Exception as exc:
        raise SlotProcessProbeError(f"process creation probe failed for PID {pid}: {exc}") from exc
    if state != "alive":
        raise SlotProcessProbeError(f"process creation probe found PID {pid} is not alive")
    return ct


def holder_state(h: dict) -> str:
    """Return live/gone or fail with a PID/API diagnostic; never turn probe errors into contention."""
    try:
        pid = int(h["pid"])
        if pid <= 0:
            raise ValueError("PID must be positive")
    except (KeyError, TypeError, ValueError) as exc:
        raise SlotProcessProbeError(f"GPU reservation has an invalid owner PID: {exc}") from exc
    try:
        state, ct = _process_state(pid)
    except SlotProcessProbeError:
        raise
    except Exception as exc:
        raise SlotProcessProbeError(f"process liveness probe failed for PID {pid}: {exc}") from exc
    if state not in ("alive", "gone"):
        raise SlotProcessProbeError(f"process liveness probe returned {state!r} for PID {pid}")
    if state == "alive" and ct is not None and h.get("created") is not None:
        try:
            reused = int(h["created"]) != ct
        except (TypeError, ValueError) as exc:
            raise SlotMetadataError(f"GPU reservation has an invalid creation time for PID {pid}: {exc}") from exc
        if reused:
            return "gone"                                      # the PID now belongs to another process
    return state


def owner(path: str):
    """Read a complete owner record; absence is a creation race, corruption fails closed."""
    owner_path = os.path.join(path, "owner.json")
    try:
        with open(owner_path, encoding="utf-8") as f:
            value = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SlotMetadataError(
            f"cannot read GPU reservation metadata at {owner_path}: {exc}; lock preserved. "
            "Inspect the owner and repair/remove the reservation only after confirming its process is stopped."
        ) from exc
    if not isinstance(value, dict):
        raise SlotMetadataError(
            f"invalid GPU reservation metadata at {owner_path}: expected a JSON object; lock preserved. "
            "Inspect the owner and repair/remove the reservation only after confirming its process is stopped."
        )
    try:
        raw_pid = value["pid"]
        if isinstance(raw_pid, bool) or not isinstance(raw_pid, (int, str)):
            raise TypeError("pid must be an integer")
        pid = int(raw_pid)
    except (KeyError, TypeError, ValueError) as exc:
        raise SlotMetadataError(
            f"invalid GPU reservation metadata at {owner_path}: missing or invalid pid; lock preserved. "
            "Inspect the owner and repair/remove the reservation only after confirming its process is stopped."
        ) from exc
    if pid <= 0:
        raise SlotMetadataError(
            f"invalid GPU reservation metadata at {owner_path}: pid must be positive; lock preserved. "
            "Inspect the owner and repair/remove the reservation only after confirming its process is stopped."
        )
    if value.get("created") is not None:
        try:
            created = value["created"]
            if isinstance(created, bool) or not isinstance(created, (int, str)):
                raise TypeError("created time must be an integer")
            int(created)
        except (TypeError, ValueError) as exc:
            raise SlotMetadataError(
                f"invalid GPU reservation metadata at {owner_path}: invalid created time; lock preserved. "
                "Inspect the owner and repair/remove the reservation only after confirming its process is stopped."
            ) from exc
    return value


def _stale(path: str) -> bool:
    h = owner(path)
    if h is None:
        if os.path.exists(os.path.join(path, "owner.json")):
            return False
        try:
            return time.time() - os.path.getmtime(path) > NO_OWNER_GRACE_S
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise SlotMetadataError(f"cannot inspect GPU reservation directory {path}: {exc}; lock preserved") from exc
    if holder_state(h) != "gone":
        return False
    time.sleep(STALE_CONFIRM_S)                                # confirm twice before breaking a live holder's slot
    h2 = owner(path)
    return h2 == h and holder_state(h2) == "gone"


def _reap_stale_slot(path: str) -> bool:
    guard = os.path.join(SLOTS_DIR, f".{os.path.basename(path)}.reap.lock")
    with advisory_guard(guard) as acquired:
        if not acquired or not _stale(path):
            return False
        print(f"GPUSLOT breaking stale {os.path.basename(path)} {owner(path)}", flush=True)
        shutil.rmtree(path, ignore_errors=True)
        return not os.path.exists(path)


def _try_take(cmd, unit, *, reap_stale=True):
    for i in range(n_slots()):
        p = os.path.join(SLOTS_DIR, f"slot_{i}")
        try:
            os.mkdir(p)
        except FileExistsError:
            if reap_stale:
                _reap_stale_slot(p)
            continue
        try:
            owner_path = os.path.join(p, "owner.json")
            temporary_path = owner_path + f".tmp-{os.getpid()}"
            with open(temporary_path, "x", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "created": process_created(os.getpid()), "since": time.time(), "unit": unit, "cmd": " ".join(map(str, cmd))[:300]}, f)
            os.replace(temporary_path, owner_path)
        except BaseException:
            shutil.rmtree(p, ignore_errors=True)
            raise
        return p
    return None


def reap_stale_slots():
    """Clear provably stale slots without reserving a GPU slot."""
    if not os.path.isdir(SLOTS_DIR):
        return
    for name in sorted(os.listdir(SLOTS_DIR)):
        if name.startswith("slot_"):
            _reap_stale_slot(os.path.join(SLOTS_DIR, name))


def holders():
    if not os.path.isdir(SLOTS_DIR):
        return {}
    return {d: owner(os.path.join(SLOTS_DIR, d)) for d in sorted(os.listdir(SLOTS_DIR)) if d.startswith("slot_")}


@contextlib.contextmanager
def slot(cmd, unit="", on_wait=None):
    """Hold one GPU slot, with launch guard passed inside it, for the duration of the block."""
    os.makedirs(SLOTS_DIR, exist_ok=True)
    wait_min = wait_minutes()
    if not math.isfinite(wait_min) or wait_min < 0:
        raise SlotError(f"HOMM3_BLENDER_SLOT_WAIT={wait_min!r} is not a finite nonnegative number")
    deadline = time.monotonic() + wait_min * 60
    told = False
    while True:
        p = _try_take(cmd, unit)
        if p:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SlotError(f"all {n_slots()} GPU slots stayed busy for {wait_min:.0f} min: {holders()}")
        if not told and on_wait:
            on_wait(f"waiting for a GPU slot ({n_slots()} busy: "
                    + ", ".join(f"{(h or {}).get('unit', '?')}" for h in holders().values()) + ")")
            told = True
        time.sleep(min(20 + random.uniform(0, 10), remaining))
    try:
        if subprocess.run([sys.executable, LAUNCH_GUARD]).returncode != 0:
            raise SlotError("launch guard refused; not launching Blender")
        yield p
    finally:
        shutil.rmtree(p, ignore_errors=True)


@contextlib.contextmanager
def try_slot(cmd, unit=""):
    """Try once without waiting or reaping stale owners; yield None when no slot is free."""
    os.makedirs(SLOTS_DIR, exist_ok=True)
    p = _try_take(cmd, unit, reap_stale=False)
    if not p:
        yield None
        return
    try:
        if subprocess.run([sys.executable, LAUNCH_GUARD]).returncode != 0:
            raise SlotError("launch guard refused; not launching Blender")
        yield p
    finally:
        shutil.rmtree(p, ignore_errors=True)


def main():
    if sys.argv[1:2] == ["status"]:
        h = holders()
        print(f"GPUSLOT {len(h)}/{n_slots()} held")
        for k, v in h.items():
            print(f"  {k}: {v}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
