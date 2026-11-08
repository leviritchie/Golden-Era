#!/usr/bin/env python3
"""Extended score-gated escape compare (v2) on roc idle1+start+move+end.

Builds on v1 with multi-pass stacks, plateau/threshold loops, deep retry,
and worst-frame root bursts. Adaptive step stays on throughout.

Generated-artifact only; not OE runtime.
"""
from __future__ import annotations

import run_roc_idle1_score_escape_compare as base

ROOT = base.ROOT
OUT = ROOT / "artifacts/pose_picker_runs/h3_roc/idle1_start_move_end/score_escape_compare_v2"

# sprite + 8 panels → 3×3 grid
base.TRIALS = (
    {
        "id": "adaptive_baseline",
        "label": "adaptive",
        "reason": "Adaptive walk only; no escape.",
        "overrides": {"score_escape_enabled": False},
    },
    {
        "id": "escape_retry",
        "label": "retry",
        "reason": "v1 best single pass: second adaptive walk.",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "articulated_retry",
        },
    },
    {
        "id": "escape_full_stack",
        "label": "stack",
        "reason": "One gated round: retry → coarse → rescue.",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "full_stack",
        },
    },
    {
        "id": "escape_until_threshold",
        "label": "until0.8",
        "reason": "Repeat full stack up to 3 rounds until mean ≥ 0.80.",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "until_threshold",
            "score_escape_max_rounds": 3,
        },
    },
    {
        "id": "escape_until_plateau",
        "label": "plateau",
        "reason": "Repeat full stack until round gain < 0.005 (max 3).",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "until_plateau",
            "score_escape_max_rounds": 3,
            "score_escape_min_improvement": 0.005,
        },
    },
    {
        "id": "escape_deep_retry",
        "label": "deep2x",
        "reason": "Two sequential adaptive retries when still under 0.80.",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "deep_retry",
        },
    },
    {
        "id": "escape_worst_stack",
        "label": "worst",
        "reason": "Coarse push, then root search on 3 worst frames, then rescue.",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "worst_stack",
            "score_escape_worst_frame_count": 3,
        },
    },
    {
        "id": "escape_until_plateau5",
        "label": "plat5",
        "reason": "Plateau loop with up to 5 full-stack rounds.",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "until_plateau",
            "score_escape_max_rounds": 5,
            "score_escape_min_improvement": 0.003,
        },
    },
    {
        "id": "escape_until_keep",
        "label": "until+kb",
        "reason": "until_threshold + keep_best (retain peak mid-loop).",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "until_threshold",
            "score_escape_max_rounds": 3,
            "score_escape_keep_best": True,
        },
    },
)

if __name__ == "__main__":
    import sys

    argv = [sys.argv[0], "--out", str(OUT), "--gif-name", "idle1_score_escape_compare_v2.gif"]
    argv.extend(sys.argv[1:])
    sys.argv = argv
    raise SystemExit(base.main())
