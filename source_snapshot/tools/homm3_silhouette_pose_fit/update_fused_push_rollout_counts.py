#!/usr/bin/env python3
"""Refresh fused_push rollout_status.json from fit_plan + clip_log."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
OUT = ROOT / "artifacts/fused_push_skinned_rollout"

# Reuse accounting from the smartrig rollout counter; only OUT root differs.
import update_smartrig_rollout_counts as base  # noqa: E402

base.OUT = OUT


def main() -> int:
    summary = base.apply_status(base.recount())
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if summary["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
