#!/usr/bin/env python3
"""Run no-runtime overlay dry-runs for custom law Core generation.

This validator intentionally does not deploy, launch the game, or mutate the
live Core.zip. It runs apply_release_core_overlay.py in --dry-run mode and lets
the existing candidate Core validators prove generated law rows.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OVERLAY_SCRIPT = ROOT / "tools" / "release_port" / "apply_release_core_overlay.py"
ARTIFACT_DIR = ROOT / "artifacts" / "custom_law_static" / "overlay_dry_runs"
TIMEOUT_SECONDS = 300
FAILURE_TAIL_LINES = 80


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def write_log(name: str, text: str) -> Path:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACT_DIR / f"{name}.log"
    path.write_text(text, encoding="utf-8", errors="replace")
    return path


def print_failure_tail(name: str, text: str) -> None:
    lines = text.splitlines()
    tail = lines[-FAILURE_TAIL_LINES:]
    print(f"[{name}] last {len(tail)} output lines:", file=sys.stderr)
    for line in tail:
        print(line, file=sys.stderr)


def run_overlay_dry_run(name: str, extra_args: list[str]) -> int:
    cmd = [
        sys.executable,
        str(OVERLAY_SCRIPT),
        "--dry-run",
        "--validate-no-compromise-law-core-metadata",
        "--require-no-compromise-law-static",
        *extra_args,
    ]
    print(f"[{name}] running non-deploy overlay dry-run", flush=True)
    try:
        completed = subprocess.run(
            cmd,
            cwd=ROOT,
            timeout=TIMEOUT_SECONDS,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.output or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        log_path = write_log(
            name,
            output + f"\n[{name}] timed out after {TIMEOUT_SECONDS}s\n",
        )
        print(f"[{name}] timed out after {TIMEOUT_SECONDS}s", file=sys.stderr)
        print(f"[{name}] log={relative(log_path)}", file=sys.stderr)
        if output:
            print_failure_tail(name, output)
        return 1

    log_path = write_log(name, completed.stdout)
    print(f"[{name}] exit={completed.returncode} log={relative(log_path)}", flush=True)
    if completed.returncode != 0:
        print_failure_tail(name, completed.stdout)
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate playable and/or strict custom law overlay Core generation by running non-deploy dry-runs. "
            "This proves candidate Core generation only; it does not prove runtime behavior."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("both", "playable", "strict"),
        default="both",
        help="Which overlay source path to dry-run.",
    )
    args = parser.parse_args()

    failures: list[str] = []
    if args.mode in {"both", "playable"}:
        if run_overlay_dry_run("playable-law-overrides", []) != 0:
            failures.append("playable-law-overrides")
    if args.mode in {"both", "strict"}:
        if run_overlay_dry_run("strict-no-compromise-law-overrides", ["--use-strict-no-compromise-law-overrides"]) != 0:
            failures.append("strict-no-compromise-law-overrides")

    if failures:
        print("custom law overlay dry-run validation failed: " + ", ".join(failures), file=sys.stderr)
        return 1
    print("custom law overlay dry-run validation passed")
    print("Note: dry-runs prove candidate Core generation/validation only, not deployment or runtime law behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
