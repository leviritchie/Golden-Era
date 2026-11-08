#!/usr/bin/env python3
"""Dynamic movement-policy compare on roc idle1+start+move+end.

Builds on ik_hybrid_wild (frame_hybrid scoring + bold search). This pass tests
smarter *which part moves how far* decisions without LLM authorship:

- displacement-scaled step sizes
- deficit-first frame ordering
- priority blob ordering (area * miss distance)
- displacement-based chain unlock (skip distal-only on large misses)
- influence-dominance gating on ambiguous blobs
- per-blob dynamic stop targets

Generated-artifact only; not OE runtime.
"""
from __future__ import annotations

import json
import run_roc_idle1_score_escape_compare as base

ROOT = base.ROOT
TOOL = base.TOOL
OUT = ROOT / "artifacts/pose_picker_runs/h3_roc/idle1_start_move_end/ik_dynamic_compare"
ANATOMY_GROUPS = TOOL / "roc_smartrig_anatomy_groups.json"

from cascade_anatomy_bone_order import cascade_kwargs_from_catalog_transit

ANATOMY_KWARGS = cascade_kwargs_from_catalog_transit(
    groups_path=ANATOMY_GROUPS,
    clip="idle1_start_move_end",
)

WILD_IK = {
    "ik_enabled": True,
    "ik_keypoints_source": "silhouette_miss",
    "ik_keypoints_path": None,
    "ik_bone_roles_path": None,
    "ik_silhouette_score_mode": "frame_hybrid",
    "ik_miss_max_pairs": 8,
    "ik_miss_max_tip_distance_px": 120.0,
    "ik_miss_max_centroid_distance_px": 150.0,
    "ik_miss_max_area_ratio": 10.0,
    "ik_miss_min_displacement_alignment": 0.0,
    "ik_miss_min_component_area": 12,
    "ik_miss_depth_tolerance": 0.25,
    "ik_repair_dilate_px": 14,
    "ik_max_step_deg": 45.0,
    "ik_proximal_max_step_deg": 25.0,
    "ik_proximal_min_depth": 1,
    "ik_max_chain_depth": 12,
    "ik_blob_search_rounds": 14,
    "ik_iterations": 6,
    "ik_blob_iou_target": 0.55,
    "ik_require_improvement": False,
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

DYNAMIC_OFF = {
    "ik_job_order_mode": "pair_rank",
    "ik_step_scale_mode": "fixed",
    "ik_chain_start_mode": "distal",
    "ik_frame_order_mode": "clip",
    "ik_influence_dominance_min": 0.0,
    "ik_dynamic_stop_enabled": False,
}

# Viability screening budget — rank methods, not chase peak score.
FAST_IK_BUDGET = {
    "ik_iterations": 2,
    "ik_blob_search_rounds": 6,
    "ik_miss_max_pairs": 4,
}

FAST_TRIAL_IDS = frozenset(
    {
        "no_ik_baseline",
        "wild_static",
        "wild_disp_steps",
        "wild_deficit_frames",
        "wild_full_dynamic",
    }
)


def build_trials(fit_base: dict, wild_ik: dict) -> tuple[dict, ...]:
    return (
        {
            "id": "no_ik_baseline",
            "label": "no ik",
            "reason": "Anatomy+m2+rootP without IK.",
            "overrides": {**fit_base, "ik_enabled": False},
        },
        {
            "id": "wild_static",
            "label": "wild",
            "reason": "ik_hybrid_wild reference (dynamic policy off).",
            "overrides": {**fit_base, **wild_ik, **DYNAMIC_OFF},
        },
        {
            "id": "wild_disp_steps",
            "label": "disp step",
            "reason": "Scale IK steps by blob miss distance.",
            "overrides": {
                **fit_base,
                **wild_ik,
                **DYNAMIC_OFF,
                "ik_step_scale_mode": "displacement",
                "ik_step_displacement_ref_px": 48.0,
                "ik_step_scale_min": 0.45,
                "ik_step_scale_max": 1.75,
            },
        },
        {
            "id": "wild_disp_chain",
            "label": "disp chain",
            "reason": "Displacement steps + unlock longer chains on large misses.",
            "overrides": {
                **fit_base,
                **wild_ik,
                **DYNAMIC_OFF,
                "ik_step_scale_mode": "displacement",
                "ik_chain_start_mode": "displacement",
                "ik_chain_displacement_ref_px": 36.0,
            },
        },
        {
            "id": "wild_deficit_frames",
            "label": "deficit fr",
            "reason": "Worst hybrid-score frames first; combined step scaling.",
            "overrides": {
                **fit_base,
                **wild_ik,
                **DYNAMIC_OFF,
                "ik_frame_order_mode": "deficit",
                "ik_step_scale_mode": "combined",
                "ik_step_displacement_ref_px": 52.0,
            },
        },
        {
            "id": "wild_priority_jobs",
            "label": "prio jobs",
            "reason": "Large area*distance blobs first; displacement steps.",
            "overrides": {
                **fit_base,
                **wild_ik,
                **DYNAMIC_OFF,
                "ik_job_order_mode": "priority",
                "ik_step_scale_mode": "displacement",
            },
        },
        {
            "id": "wild_full_dynamic",
            "label": "full dyn",
            "reason": "All dynamic policies + influence gate + dynamic stop.",
            "overrides": {
                **fit_base,
                **wild_ik,
                "ik_job_order_mode": "priority",
                "ik_step_scale_mode": "combined",
                "ik_step_displacement_ref_px": 48.0,
                "ik_step_scale_min": 0.4,
                "ik_step_scale_max": 1.8,
                "ik_chain_start_mode": "displacement",
                "ik_chain_displacement_ref_px": 34.0,
                "ik_frame_order_mode": "deficit",
                "ik_influence_dominance_min": 0.42,
                "ik_dynamic_stop_enabled": True,
            },
        },
    )


base.TRIALS = build_trials(FIT_BASE, WILD_IK)


def apply_fast_mode(*, out: base.Path) -> None:
    """Cut search depth for viability ranking (not peak-score chasing)."""
    global OUT, base

    OUT = out
    fit_base = {**FIT_BASE, "articulated_iterations": 1}
    wild_ik = {**WILD_IK, **FAST_IK_BUDGET}
    base.TRIALS = tuple(
        t for t in build_trials(fit_base, wild_ik) if str(t["id"]) in FAST_TRIAL_IDS
    )


if __name__ == "__main__":
    import argparse
    import shutil
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Viability budget: 5 trials, 2 IK passes, 6 search rounds, 1 articulated walk.",
    )
    args, remainder = parser.parse_known_args()

    out_root = OUT
    gif_name = "idle1_ik_dynamic_compare.gif"
    if args.fast:
        out_root = OUT.parent / "ik_dynamic_compare_fast"
        gif_name = "idle1_ik_dynamic_compare_fast.gif"
        apply_fast_mode(out=out_root)
        baseline_src = OUT / "no_ik_baseline"
        baseline_dst = out_root / "no_ik_baseline"
        if baseline_src.is_dir() and not baseline_dst.is_dir():
            shutil.copytree(baseline_src, baseline_dst)

    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "ik_dynamic_compare_plan.json").write_text(
        json.dumps(
            {
                "proof": "generated experiment; dynamic IK movement policy",
                "mode": "fast_viability" if args.fast else "full",
                "foundation": "ik_hybrid_wild + anatomy m2 + primary_group_end root",
                "fastBudget": dict(FAST_IK_BUDGET) if args.fast else None,
                "policies": [
                    "ik_step_scale_mode",
                    "ik_chain_start_mode",
                    "ik_frame_order_mode",
                    "ik_job_order_mode",
                    "ik_influence_dominance_min",
                    "ik_dynamic_stop_enabled",
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    argv = [
        sys.argv[0],
        "--out",
        str(out_root),
        "--gif-name",
        gif_name,
        *remainder,
    ]
    sys.argv = argv
    raise SystemExit(base.main())
