#!/usr/bin/env python3
"""Score escape v3: no-rescue stacks + SA/chain_space (no LLM authorship).

Skips branch_rescue in multi-round loops where keep-best showed rescue mostly
reverts. Compares against adaptive baseline and classic escape passes.

Generated-artifact only; not OE runtime.
"""
from __future__ import annotations

import run_roc_idle1_score_escape_compare as base

ROOT = base.ROOT
OUT = ROOT / "artifacts/pose_picker_runs/h3_roc/idle1_start_move_end/score_escape_compare_v3"

base.TRIALS = (
    {
        "id": "adaptive_baseline",
        "label": "adaptive",
        "reason": "Adaptive walk only; no escape.",
        "overrides": {"score_escape_enabled": False},
    },
    {
        "id": "escape_plateau_ref",
        "label": "plat+rescue",
        "reason": "v2 best: until_plateau full stack (retry+coarse+rescue).",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "until_plateau",
            "score_escape_max_rounds": 3,
            "score_escape_min_improvement": 0.005,
        },
    },
    {
        "id": "escape_plateau_no_rescue",
        "label": "plat noR",
        "reason": "until_plateau_retry_coarse: skip rescue passes.",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "until_plateau_retry_coarse",
            "score_escape_max_rounds": 5,
            "score_escape_min_improvement": 0.003,
        },
    },
    {
        "id": "escape_plateau_no_rescue7",
        "label": "plat7 noR",
        "reason": "No-rescue plateau up to 7 rounds, min gain 0.002.",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "until_plateau_retry_coarse",
            "score_escape_max_rounds": 7,
            "score_escape_min_improvement": 0.002,
        },
    },
    {
        "id": "escape_retry_coarse",
        "label": "retry+coarse",
        "reason": "Single retry then coarse push (no rescue).",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "retry_coarse",
        },
    },
    {
        "id": "escape_sa_nudge",
        "label": "sa",
        "reason": "Simulated annealing nudge when under 0.80.",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "sa_nudge",
        },
    },
    {
        "id": "escape_chain_space",
        "label": "chain",
        "reason": "Chain-space escape pass (no LLM anatomy).",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "chain_space",
            "chain_space_enabled": True,
        },
    },
    {
        "id": "escape_no_consensus",
        "label": "noCons",
        "reason": "Adaptive retry with temporal consensus disabled.",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "no_consensus_retry",
        },
    },
    {
        "id": "escape_coarse_lo",
        "label": "coarse80",
        "reason": "Coarse push with 0.80 coarse threshold (finer steps).",
        "overrides": {
            "score_escape_enabled": True,
            "score_escape_mode": "coarse_push",
            "score_escape_coarse_push_coarse": 0.80,
            "score_escape_coarse_push_fine": 0.88,
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
        "idle1_score_escape_compare_v3.gif",
    ]
    argv.extend(sys.argv[1:])
    sys.argv = argv
    raise SystemExit(base.main())
