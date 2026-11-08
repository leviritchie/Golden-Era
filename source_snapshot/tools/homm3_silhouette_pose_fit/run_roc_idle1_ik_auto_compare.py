#!/usr/bin/env python3
"""Auto-detected IK compare on roc idle1+start+move+end (no LLM authorship).

Uses ``ik_keypoints_source=silhouette_miss``: pairs red excess / blue missing
blobs from raster vs sprite, assigns bones by skinning influence, incremental
blob IK before the articulated walk. No authored keypoints or bone_roles.

Generated-artifact only; not OE runtime.
"""
from __future__ import annotations

import json
import run_roc_idle1_score_escape_compare as base

ROOT = base.ROOT
TOOL = base.TOOL
OUT = ROOT / "artifacts/pose_picker_runs/h3_roc/idle1_start_move_end/ik_auto_compare"
ANATOMY_GROUPS = TOOL / "roc_smartrig_anatomy_groups.json"

from cascade_anatomy_bone_order import cascade_kwargs_from_catalog_transit

ANATOMY_KWARGS = cascade_kwargs_from_catalog_transit(
    groups_path=ANATOMY_GROUPS,
    clip="idle1_start_move_end",
)

FIT_BASE = {
    "score_mode": "geometry",
    "motion_weight": 1.0,
    "depth_weight": 0.25,
    "silhouette_weight": 0.2,
    "chroma_weight": 0.2,
    "collision_enabled": True,
    "collision_weight": 0.35,
    "sa_enabled": False,
    "gradient_ladder_enabled": False,
    "chain_space_enabled": False,
    "physics_smooth_enabled": False,
    "joint_temporal_consensus_enabled": True,
    "sprite_aligned_motion_keep_enabled": False,
    "live_preview": False,
    "articulated_iterations": 2,
    "fine_iterations": 0,
    "base_pose_enabled": True,
    "mid_pose_enabled": True,
    "branch_rescue_enabled": False,
    "skip_tiny_bones": False,
    "bone_order_mode": "dependency",
    "root_search_enabled": False,
    "root_refit_after_base_enabled": False,
    "articulated_root_interleave_enabled": True,
    "articulated_root_interleave_rotation_deg": 8.0,
    "articulated_root_interleave_rotation_step_deg": 4.0,
    "articulated_root_interleave_include_translation": False,
    "articulated_root_interleave_policy": "primary_group_end",
    "articulated_multi_bone_enabled": True,
    "articulated_multi_bone_block_size": 2,
    "seed_previous_frame": True,
    "idle_prefix_frames": 1,
    "idle_suffix_frames": 0,
    "joint_temporal_consensus_idle_end": False,
    **ANATOMY_KWARGS,
}

IK_MISS = {
    "ik_enabled": True,
    "ik_keypoints_source": "silhouette_miss",
    "ik_keypoints_path": None,
    "ik_bone_roles_path": None,
}

base.TRIALS = (
    {
        "id": "no_ik_baseline",
        "label": "no ik",
        "reason": "Anatomy+m2+rootP baseline without IK init.",
        "overrides": {
            **FIT_BASE,
            "ik_enabled": False,
        },
    },
    {
        "id": "ik_miss_default",
        "label": "ik miss",
        "reason": "Default silhouette_miss blob IK before articulated walk.",
        "overrides": {
            **FIT_BASE,
            **IK_MISS,
        },
    },
    {
        "id": "ik_miss_deep",
        "label": "ik deep",
        "reason": "More IK iterations, chain depth, and blob search rounds.",
        "overrides": {
            **FIT_BASE,
            **IK_MISS,
            "ik_iterations": 28,
            "ik_max_chain_depth": 8,
            "ik_blob_search_rounds": 5,
            "ik_max_step_deg": 18.0,
        },
    },
    {
        "id": "ik_miss_shallow",
        "label": "ik shallow",
        "reason": "Lower proximal depth + more miss pairs (wing/tip reach).",
        "overrides": {
            **FIT_BASE,
            **IK_MISS,
            "ik_proximal_min_depth": 2,
            "ik_miss_max_pairs": 4,
            "ik_miss_max_tip_distance_px": 72.0,
        },
    },
    {
        "id": "ik_miss_tight_blob",
        "label": "ik tight",
        "reason": "Higher regional IoU target (0.95) per blob repair.",
        "overrides": {
            **FIT_BASE,
            **IK_MISS,
            "ik_blob_iou_target": 0.95,
            "ik_repair_dilate_px": 6,
        },
    },
    {
        "id": "ik_miss_keep_any",
        "label": "ik keep",
        "reason": "silhouette_miss with ik_require_improvement off (keep interim).",
        "overrides": {
            **FIT_BASE,
            **IK_MISS,
            "ik_require_improvement": False,
        },
    },
)

if __name__ == "__main__":
    import sys

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ik_auto_compare_plan.json").write_text(
        json.dumps(
            {
                "proof": "generated experiment; silhouette_miss IK — no LLM sprite authorship",
                "ikSource": "silhouette_miss",
                "foundation": "catalog anatomy + m2 + primary_group_end root",
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
        "idle1_ik_auto_compare.gif",
    ]
    argv.extend(sys.argv[1:])
    sys.argv = argv
    raise SystemExit(base.main())
