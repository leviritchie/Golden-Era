#!/usr/bin/env python3
"""Bold silhouette_miss IK compare on roc idle1+start+move+end.

Prior ik_auto_compare kept regional blob IoU scoring and ignored ik_iterations
for silhouette_miss (only ik_blob_search_rounds applied). This harness tests:

- frame_hybrid scoring (same metric as articulated walk)
- relaxed blob pairing + large steps + deep chains
- ik_iterations as outer re-derive passes

Generated-artifact only; not OE runtime.
"""
from __future__ import annotations

import json
import run_roc_idle1_score_escape_compare as base

ROOT = base.ROOT
TOOL = base.TOOL
OUT = ROOT / "artifacts/pose_picker_runs/h3_roc/idle1_start_move_end/ik_bold_compare"
ANATOMY_GROUPS = TOOL / "roc_smartrig_anatomy_groups.json"

from cascade_anatomy_bone_order import cascade_kwargs_from_catalog_transit

ANATOMY_KWARGS = cascade_kwargs_from_catalog_transit(
    groups_path=ANATOMY_GROUPS,
    clip="idle1_start_move_end",
)

BOLD_IK_PAIRING = {
    "ik_miss_max_pairs": 8,
    "ik_miss_max_tip_distance_px": 120.0,
    "ik_miss_max_centroid_distance_px": 150.0,
    "ik_miss_max_area_ratio": 10.0,
    "ik_miss_min_displacement_alignment": 0.0,
    "ik_miss_min_component_area": 12,
    "ik_miss_depth_tolerance": 0.25,
    "ik_repair_dilate_px": 14,
}

BOLD_IK_SEARCH = {
    "ik_max_step_deg": 35.0,
    "ik_proximal_max_step_deg": 18.0,
    "ik_proximal_min_depth": 1,
    "ik_max_chain_depth": 12,
    "ik_blob_search_rounds": 10,
    "ik_iterations": 4,
}

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
        "reason": "Anatomy+m2+rootP without IK.",
        "overrides": {**FIT_BASE, "ik_enabled": False},
    },
    {
        "id": "ik_hybrid_bold",
        "label": "hybrid bold",
        "reason": "frame_hybrid score + bold pairing/search; keep only if clip improves.",
        "overrides": {
            **FIT_BASE,
            **IK_MISS,
            **BOLD_IK_PAIRING,
            **BOLD_IK_SEARCH,
            "ik_silhouette_score_mode": "frame_hybrid",
            "ik_blob_iou_target": 0.50,
            "ik_require_improvement": True,
        },
    },
    {
        "id": "ik_hybrid_bold_keep",
        "label": "hybrid keep",
        "reason": "frame_hybrid bold search; always keep IK init (no require_improvement).",
        "overrides": {
            **FIT_BASE,
            **IK_MISS,
            **BOLD_IK_PAIRING,
            **BOLD_IK_SEARCH,
            "ik_silhouette_score_mode": "frame_hybrid",
            "ik_blob_iou_target": 0.50,
            "ik_require_improvement": False,
        },
    },
    {
        "id": "ik_regional_bold",
        "label": "regional bold",
        "reason": "Legacy regional IoU but bold pairing/search + outer passes.",
        "overrides": {
            **FIT_BASE,
            **IK_MISS,
            **BOLD_IK_PAIRING,
            **BOLD_IK_SEARCH,
            "ik_silhouette_score_mode": "regional_iou",
            "ik_blob_iou_target": 0.88,
            "ik_require_improvement": False,
        },
    },
    {
        "id": "ik_hybrid_wild",
        "label": "hybrid wild",
        "reason": "frame_hybrid with even larger steps and 6 outer passes.",
        "overrides": {
            **FIT_BASE,
            **IK_MISS,
            **BOLD_IK_PAIRING,
            **BOLD_IK_SEARCH,
            "ik_silhouette_score_mode": "frame_hybrid",
            "ik_max_step_deg": 45.0,
            "ik_proximal_max_step_deg": 25.0,
            "ik_blob_search_rounds": 14,
            "ik_iterations": 6,
            "ik_blob_iou_target": 0.55,
            "ik_require_improvement": False,
        },
    },
)

if __name__ == "__main__":
    import sys

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ik_bold_compare_plan.json").write_text(
        json.dumps(
            {
                "proof": "generated experiment; bold silhouette_miss IK",
                "fixes": [
                    "ik_iterations now outer re-derive passes for silhouette_miss",
                    "ik_silhouette_score_mode frame_hybrid scores per-frame hybrid",
                ],
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
        "idle1_ik_bold_compare.gif",
    ]
    argv.extend(sys.argv[1:])
    sys.argv = argv
    raise SystemExit(base.main())
