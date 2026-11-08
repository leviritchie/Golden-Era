#!/usr/bin/env python3
"""Anatomy-ordered multi-bone compare on roc idle1+start+move+end.

Uses mesh-catalog transit anatomy (wings→trunk→…) without LLM sprite authorship.
Multi-bone parent-child combos run per anatomy group after single-bone walk.
Root rotation defers to primary groups (wing_a, wing_b, trunk) so joints lead.

Generated-artifact only; not OE runtime.
"""
from __future__ import annotations

import json
import run_roc_idle1_score_escape_compare as base

ROOT = base.ROOT
TOOL = base.TOOL
OUT = ROOT / "artifacts/pose_picker_runs/h3_roc/idle1_start_move_end/anatomy_multibone_compare"
ANATOMY_GROUPS = TOOL / "roc_smartrig_anatomy_groups.json"

from cascade_anatomy_bone_order import cascade_kwargs_from_catalog_transit

ANATOMY_KWARGS = cascade_kwargs_from_catalog_transit(
    groups_path=ANATOMY_GROUPS,
    clip="idle1_start_move_end",
)

WEAVE_BASE = {
    "score_mode": "geometry",
    "motion_weight": 1.0,
    "depth_weight": 0.25,
    "silhouette_weight": 0.2,
    "chroma_weight": 0.2,
    "collision_enabled": True,
    "collision_weight": 0.35,
    "sa_enabled": False,
    "gradient_ladder_enabled": False,
    "ik_enabled": False,
    "physics_smooth_enabled": False,
    "joint_temporal_consensus_enabled": True,
    "sprite_aligned_motion_keep_enabled": False,
    "live_preview": False,
    "chain_space_enabled": False,
    "articulated_iterations": 2,
    "fine_iterations": 0,
    "base_pose_enabled": True,
    "mid_pose_enabled": True,
    "branch_rescue_enabled": False,
    "skip_tiny_bones": False,
    "root_search_enabled": False,
    "root_refit_after_base_enabled": False,
    "articulated_root_interleave_enabled": True,
    "articulated_root_interleave_rotation_deg": 8.0,
    "articulated_root_interleave_rotation_step_deg": 4.0,
    "articulated_root_interleave_include_translation": False,
    "seed_previous_frame": True,
    "idle_prefix_frames": 1,
    "idle_suffix_frames": 0,
    "joint_temporal_consensus_idle_end": False,
    **ANATOMY_KWARGS,
}

base.TRIALS = (
    {
        "id": "anatomy_single_root_per_accept",
        "label": "anat+root",
        "reason": "Catalog anatomy order; root after each accept (legacy).",
        "overrides": {
            **WEAVE_BASE,
            "articulated_root_interleave_policy": "per_accept",
            "articulated_multi_bone_enabled": False,
        },
    },
    {
        "id": "anatomy_multi2_root_primary",
        "label": "m2+rootP",
        "reason": "2-bone combos per group; root only on wing/trunk groups.",
        "overrides": {
            **WEAVE_BASE,
            "articulated_multi_bone_enabled": True,
            "articulated_multi_bone_block_size": 2,
            "articulated_root_interleave_policy": "primary_group_end",
        },
    },
    {
        "id": "anatomy_multi3_root_primary",
        "label": "m3+rootP",
        "reason": "3-bone beams per group; root on primary groups only.",
        "overrides": {
            **WEAVE_BASE,
            "articulated_multi_bone_enabled": True,
            "articulated_multi_bone_block_size": 3,
            "articulated_root_interleave_policy": "primary_group_end",
        },
    },
    {
        "id": "anatomy_multi2_no_root",
        "label": "m2 noR",
        "reason": "2-bone combos; root interleave off (joints only).",
        "overrides": {
            **WEAVE_BASE,
            "articulated_multi_bone_enabled": True,
            "articulated_multi_bone_block_size": 2,
            "articulated_root_interleave_enabled": False,
        },
    },
    {
        "id": "gradient_mag_control",
        "label": "grad ctrl",
        "reason": "gradient_magnitude re-rank (breaks anatomy order).",
        "overrides": {
            **WEAVE_BASE,
            "bone_order_mode": "gradient_magnitude",
            "search_bones": (),
            "include_unlisted_search_bones": True,
            "bone_limit_scale_overrides": (),
            "anatomy_groups_catalog_path": "",
            "anatomy_group_visit_order": (),
            "articulated_multi_bone_enabled": False,
            "articulated_root_interleave_policy": "per_accept",
        },
    },
)

if __name__ == "__main__":
    import sys

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "anatomy_plan.json").write_text(
        json.dumps(
            {
                "proof": "generated experiment; catalog anatomy not LLM sprite authorship",
                "anatomyMethod": "catalog_transit_importance",
                "anatomyKwargs": {k: list(v) if isinstance(v, tuple) else v for k, v in ANATOMY_KWARGS.items()},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    argv = [
        sys.argv[0],
        "--out",
        str(OUT),
        "--gif-name",
        "idle1_anatomy_multibone_compare.gif",
    ]
    argv.extend(sys.argv[1:])
    sys.argv = argv
    raise SystemExit(base.main())
