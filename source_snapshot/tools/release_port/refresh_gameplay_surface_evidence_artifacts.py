#!/usr/bin/env python3
"""Refresh and validate gameplay surface evidence artifacts.

This is the patch-update entry point for the custom law gameplay-surface matrix.
It regenerates conservative runtime candidate enrichment, rebuilds focused weak
surface dossiers, then validates both the matrix and generated dossier index.

Boundary: static/decomp pipeline only. This does not build the mod, launch the
game, use the live bridge, or promote gameplay.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RELEASE_PORT = ROOT / "tools" / "release_port"


STEPS = [
    (
        "enrich-matrix",
        [
            sys.executable,
            str(RELEASE_PORT / "enrich_gameplay_surface_evidence_matrix.py"),
            "--write-matrix",
        ],
    ),
    (
        "build-weak-dossiers",
        [
            sys.executable,
            str(RELEASE_PORT / "build_gameplay_surface_weak_dossiers.py"),
        ],
    ),
    (
        "enrich-matrix-from-weak-dossiers",
        [
            sys.executable,
            str(RELEASE_PORT / "enrich_gameplay_surface_evidence_matrix.py"),
            "--write-matrix",
        ],
    ),
    (
        "validate-matrix",
        [
            sys.executable,
            str(RELEASE_PORT / "validate_gameplay_surface_evidence_matrix.py"),
        ],
    ),
    (
        "validate-weak-dossiers",
        [
            sys.executable,
            str(RELEASE_PORT / "validate_gameplay_surface_weak_dossier_index.py"),
        ],
    ),
    (
        "report-runtime-candidate-coverage",
        [
            sys.executable,
            str(RELEASE_PORT / "report_gameplay_surface_runtime_candidate_coverage.py"),
        ],
    ),
    (
        "validate-runtime-candidate-coverage",
        [
            sys.executable,
            str(RELEASE_PORT / "validate_gameplay_surface_runtime_candidate_coverage.py"),
        ],
    ),
]


def run_step(name: str, command: list[str], *, dry_run: bool) -> int:
    display = " ".join(command)
    if dry_run:
        print(f"[{name}] {display}")
        return 0
    print(f"[{name}] running {display}")
    completed = subprocess.run(command, cwd=ROOT)
    print(f"[{name}] exit={completed.returncode}")
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without running them.",
    )
    args = parser.parse_args()

    failures: list[str] = []
    for name, command in STEPS:
        if run_step(name, command, dry_run=args.dry_run) != 0:
            failures.append(name)
            break

    if failures:
        print("gameplay surface evidence refresh failed: " + ", ".join(failures), file=sys.stderr)
        return 1
    if args.dry_run:
        print("gameplay surface evidence refresh dry-run complete")
    else:
        print("gameplay surface evidence artifacts refreshed and validated")
        print("Note: static pass does not prove runtime law behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
