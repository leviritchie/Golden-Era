"""Memory gate: run before starting any Blender process.

Usage: python tools/homm3_def_retarget/memgate.py [--wait MINUTES]
Prints "MEMGATE OK ..." and exits 0 when free RAM >= 5 GB and free VRAM >= 3 GB, otherwise
"MEMGATE FULL ..." and exits 1. With --wait, rechecks every 30 s (with jitter, so agents that
checked together do not all start at once) for up to MINUTES before giving up.

Probe failures are FULL immediately; never assume missing measurements mean free capacity.
Agent protocol: if the gate is still FULL after --wait 6, do not start the process; update your
handoff, then stop and report "paused: memory full" to the lead, who will resume you.
"""
import ctypes
from ctypes import wintypes
import math
import random
import subprocess
import sys
import time

MIN_RAM_GB, MIN_VRAM_GB = 5.0, 3.0


class ProbeError(RuntimeError):
    pass


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def memory_gb():
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        probe = kernel32.GlobalMemoryStatusEx
        probe.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
        probe.restype = wintypes.BOOL
        if not probe(ctypes.byref(status)):
            raise ProbeError(f"GlobalMemoryStatusEx failed (WinError {ctypes.get_last_error()})")
    except OSError as exc:
        raise ProbeError(f"GlobalMemoryStatusEx unavailable: {exc}") from exc
    gib = 1024 ** 3
    return status.ullAvailPhys / gib, status.ullTotalPhys / gib


def free_ram_gb():
    return memory_gb()[0]


def vram_gb(timeout_s: float = 15.0):
    try:
        timeout_s = float(timeout_s)
    except (TypeError, ValueError) as exc:
        raise ProbeError(f"invalid nvidia-smi timeout: {timeout_s!r}") from exc
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ProbeError(f"invalid nvidia-smi timeout: {timeout_s!r}")
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeError(f"nvidia-smi unavailable: {exc}") from exc
    if result.returncode != 0:
        raise ProbeError(f"nvidia-smi exited {result.returncode}: {result.stderr.strip()}")
    try:
        fields = result.stdout.strip().splitlines()[0].split(",")
        if len(fields) != 2:
            raise ValueError("expected total and free memory")
        total_mib, free_mib = (int(field.strip()) for field in fields)
    except (IndexError, ValueError) as exc:
        raise ProbeError("nvidia-smi returned no valid total/free memory values") from exc
    if total_mib <= 0 or free_mib < 0 or free_mib > total_mib:
        raise ProbeError("nvidia-smi returned invalid total/free memory values")
    return free_mib / 1024, total_mib / 1024


def free_vram_gb(timeout_s: float = 15.0):
    return vram_gb(timeout_s=timeout_s)[0]


def check(timeout_s: float = 15.0):
    r, v = free_ram_gb(), free_vram_gb(timeout_s=timeout_s)
    return r >= MIN_RAM_GB and v >= MIN_VRAM_GB, r, v


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        wait = float(argv[argv.index("--wait") + 1]) if "--wait" in argv else 0.0
    except (IndexError, ValueError):
        print("MEMGATE FULL invalid --wait value; expected finite nonnegative minutes")
        return 2
    if not math.isfinite(wait) or wait < 0:
        print("MEMGATE FULL invalid --wait value; expected finite nonnegative minutes")
        return 2
    deadline = time.monotonic() + wait * 60
    while True:
        try:
            ok, r, v = check()
        except ProbeError as exc:
            print(f"MEMGATE FULL probe failed: {exc}")
            return 1
        if ok:
            print(f"MEMGATE OK free RAM {r:.1f} GB, free VRAM {v:.1f} GB")
            return 0
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(f"MEMGATE FULL free RAM {r:.1f} GB (need {MIN_RAM_GB}), free VRAM {v:.1f} GB (need {MIN_VRAM_GB})")
            return 1
        time.sleep(min(30 + random.uniform(0, 15), remaining))


if __name__ == "__main__":
    raise SystemExit(main())
