#!/usr/bin/env python3
"""OfflineUnlockMod build-path wrapper for Direct State banned-surface validation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.repo_root.resolve()
    recovery = root / "experiments" / "olden_cs_recovery"
    sys.path.insert(0, str(recovery))
    from olden_cs_recovery.validate_banned_surfaces import main as validate_main

    return validate_main(["--repo-root", str(root)])


if __name__ == "__main__":
    raise SystemExit(main())
