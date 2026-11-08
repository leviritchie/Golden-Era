"""Fail-closed pre-Blender launch check for the DEF retarget and look lanes.

Usage: python tools/homm3_def_retarget/launch_guard.py
       python tools/homm3_def_retarget/launch_guard.py --game-only
       python tools/homm3_def_retarget/launch_guard.py --exec -- <blender> <args...>
Checks the exact game process, V: workspace free space, RAM/VRAM through memgate,
then the game again immediately before the caller launches Blender.

Every pipeline Blender child gets its environment from blender_env() (the one definition of
BLENDER_CHILD_ENV): run_unit.sh through --exec, fleet_rebuild.py, emphasis deliver.py and unit
look.py by passing env=blender_env(). The OK line names that child env so every build log records it.
"""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import importlib.util
import sys

# memgate is loaded from its file, not through sys.path: importers such as look.py must not get this folder
# (its Blender-only review.py) put ahead of their own modules (65bc42533f broke look.py that way).
_spec = importlib.util.spec_from_file_location("homm3_launch_guard_memgate", Path(__file__).resolve().parent / "memgate.py")
memgate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(memgate)


ROOT = Path(__file__).resolve().parents[2]
MIN_FREE_DISK_GB = 20.0
GAME_QUERY = (
    "$ErrorActionPreference='Stop'; "
    "$p=Get-Process | Where-Object { $_.ProcessName -eq 'HeroesOldenEra' } | Select-Object -First 1; "
    "if ($null -ne $p) { 'RUNNING' } else { 'ABSENT' }"
)


# Blender 5.2.2's oneTBB tbbmalloc_proxy cannot hook ucrtbase.dll `free` on this machine since 2026-09-27
# ("Failed to replace function free in module ucrtbase.dll"; blender --version exits 3221226505). The user
# approved disabling that replacement on each Blender child process only: never system-wide, never a DLL swap.
BLENDER_CHILD_ENV = {"TBB_MALLOC_DISABLE_REPLACEMENT": "1"}


def blender_env(base: dict | None = None) -> dict:
    """A copy of base (default os.environ) with BLENDER_CHILD_ENV set; the caller's environment is untouched."""
    env = dict(os.environ if base is None else base)
    env.update(BLENDER_CHILD_ENV)
    return env


def child_env_note() -> str:
    return "child env " + " ".join(f"{k}={v}" for k, v in sorted(BLENDER_CHILD_ENV.items()))


class LaunchRefused(RuntimeError):
    pass


def game_running() -> bool:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", GAME_QUERY],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LaunchRefused(f"game process query unavailable: {exc}") from exc
    answer = result.stdout.strip()
    if result.returncode != 0 or answer not in {"ABSENT", "RUNNING"}:
        raise LaunchRefused(f"game process query failed (exit {result.returncode}, output {answer!r}, error {result.stderr.strip()!r})")
    return answer == "RUNNING"


def check() -> tuple[float, float, float]:
    if game_running():
        raise LaunchRefused("HeroesOldenEra is running")
    try:
        free_disk = shutil.disk_usage(ROOT).free / (1024 ** 3)
    except OSError as exc:
        raise LaunchRefused(f"V: free-space query failed: {exc}") from exc
    if free_disk < MIN_FREE_DISK_GB:
        raise LaunchRefused(f"V: has {free_disk:.1f} GB free (need {MIN_FREE_DISK_GB:.1f})")
    try:
        ok, ram, vram = memgate.check()
    except memgate.ProbeError as exc:
        raise LaunchRefused(f"memgate probe failed: {exc}") from exc
    if not ok:
        raise LaunchRefused(f"memgate FULL free RAM {ram:.1f} GB (need {memgate.MIN_RAM_GB}), free VRAM {vram:.1f} GB (need {memgate.MIN_VRAM_GB})")
    if game_running():
        raise LaunchRefused("HeroesOldenEra started during resource check")
    return free_disk, ram, vram


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd = None
    if argv == ["--game-only"]:
        try:
            running = game_running()
        except LaunchRefused as exc:
            print(f"LAUNCH_GUARD REFUSED {exc}", file=sys.stderr)
            return 1
        if running:
            print("LAUNCH_GUARD REFUSED HeroesOldenEra is running", file=sys.stderr)
            return 1
        print("LAUNCH_GUARD OK HeroesOldenEra is absent", flush=True)
        return 0
    if argv[:1] == ["--exec"]:
        cmd = argv[2:] if argv[1:2] == ["--"] else argv[1:]
        if not cmd:
            print("LAUNCH_GUARD REFUSED --exec needs a command", file=sys.stderr)
            return 2
    elif argv:
        print(f"LAUNCH_GUARD REFUSED unknown arguments {argv}", file=sys.stderr)
        return 2
    try:
        disk, ram, vram = check()
    except LaunchRefused as exc:
        print(f"LAUNCH_GUARD REFUSED {exc}", file=sys.stderr)
        return 1
    print(f"LAUNCH_GUARD OK V: {disk:.1f} GB free, RAM {ram:.1f} GB free, VRAM {vram:.1f} GB free; {child_env_note()}",
          flush=True)
    if cmd is None:
        return 0
    return subprocess.run(cmd, env=blender_env()).returncode


if __name__ == "__main__":
    raise SystemExit(main())
