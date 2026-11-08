#!/usr/bin/env python3
"""Deep-budget score escape v4 (no sticks/IK): relax 5-min articulated cap.

Raises articulated_iterations and escape pass depth beyond notebook frugal
defaults (CASCADE_ARTICULATED_ITERATIONS=1). No LLM authorship.

Generated-artifact only; not OE runtime.
"""
from __future__ import annotations

import run_roc_idle1_score_escape_compare as base

ROOT = base.ROOT
OUT = ROOT / "artifacts/pose_picker_runs/h3_roc/idle1_start_move_end/score_escape_compare_v4_deep"

DEEP_KWARGS = {
    "articulated_iterations": 2,
    "score_escape_articulated_iterations": 2,
}

base.TRIALS = (
    {
        "id": "adaptive_artic2",
        "label": "adapt2",
        "reason": "2 articulated consensus rounds; no escape.",
        "overrides": {
            **DEEP_KWARGS,
            "score_escape_enabled": False,
        },
    },
    {
        "id": "adaptive_artic3",
        "label": "adapt3",
        "reason": "3 articulated rounds baseline.",
        "overrides": {
            "articulated_iterations": 3,
            "score_escape_articulated_iterations": 3,
            "score_escape_enabled": False,
        },
    },
    {
        "id": "deep_plat_noR8",
        "label": "plat8 noR",
        "reason": "artic2 + 8-round no-rescue plateau (min gain 0.001).",
        "overrides": {
            **DEEP_KWARGS,
            "score_escape_enabled": True,
            "score_escape_mode": "until_plateau_retry_coarse",
            "score_escape_max_rounds": 8,
            "score_escape_min_improvement": 0.001,
        },
    },
    {
        "id": "deep_plat_noR_artic3",
        "label": "plat8 a3",
        "reason": "artic3 + 8-round no-rescue plateau.",
        "overrides": {
            "articulated_iterations": 3,
            "score_escape_articulated_iterations": 3,
            "score_escape_enabled": True,
            "score_escape_mode": "until_plateau_retry_coarse",
            "score_escape_max_rounds": 8,
            "score_escape_min_improvement": 0.001,
        },
    },
    {
        "id": "deep_esc_artic3",
        "label": "esc3 plat8",
        "reason": "artic1 base; escape passes use 3 articulated iters.",
        "overrides": {
            "articulated_iterations": 1,
            "score_escape_articulated_iterations": 3,
            "score_escape_enabled": True,
            "score_escape_mode": "until_plateau_retry_coarse",
            "score_escape_max_rounds": 8,
            "score_escape_min_improvement": 0.001,
        },
    },
    {
        "id": "deep_retry4",
        "label": "retry4",
        "reason": "Four sequential escape adaptive retries (artic2 each).",
        "overrides": {
            **DEEP_KWARGS,
            "score_escape_enabled": True,
            "score_escape_mode": "deep_retry_4",
        },
    },
    {
        "id": "retry_then_plat",
        "label": "r+plat8",
        "reason": "One retry then 8-round no-rescue plateau (artic2).",
        "overrides": {
            **DEEP_KWARGS,
            "score_escape_enabled": True,
            "score_escape_mode": "retry_then_plateau",
            "score_escape_max_rounds": 8,
            "score_escape_min_improvement": 0.001,
        },
    },
)

if __name__ == "__main__":
    import sys

    argv = [
        sys.argv[0],
        "--out",
        str(OUT),
        "--gif-name",
        "idle1_score_escape_compare_v4_deep.gif",
    ]
    argv.extend(sys.argv[1:])
    sys.argv = argv
    raise SystemExit(base.main())
