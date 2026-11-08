#!/usr/bin/env python3
"""Build the vanilla_stock regression sample (RoE/AB/SoD required; HotA soft)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from build_vanilla_stock_batch import main as batch_main  # noqa: E402


DEFAULT_MANIFEST = REPO / "scenarios" / "vanilla_stock" / "regression_manifest.json"


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if "--manifest" not in args:
        args = ["--manifest", str(DEFAULT_MANIFEST), *args]
    return batch_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
