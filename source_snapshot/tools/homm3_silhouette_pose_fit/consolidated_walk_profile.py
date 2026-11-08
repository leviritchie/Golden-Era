"""One consolidated walk-solve profile assembled from recorded user verdicts.

Every knob below is traceable to a user verdict in the saved chat transcripts.
This module is the single place that profile lives; runners must not re-tune it
inline. Provenance tags used in comments:

  [KEEP 2026-08-27] "That's the best one in awhile." — judged
      ``run_roc_stacked_dinov3_quick.py --dense-only --from-rest --loose`` on
      h3_roc idle_start_move_end (dinov3_dense 0.947, ~113 s). Most recent
      approval of a fitted walk, and the only approval tied to a runtime the
      user called acceptable. Contested knobs resolve to this run.
  [LOOP 2026-08-27] Same message, second sentence: "We need to enforce the
      loops somehow though." Requested, then verified at the same score.
  [NORM 2026-08-20] "Logit wins. Wire that in." — chose ``logit_minmax`` over
      raw / clip_minmax / rank / robust_z for keep-score normalization. Also a
      fail-closed CURRENT_CASCADE_KEEP requirement.
  [SPRITE 2026-08-17] "Make a commit. This is pretty good here." — judged the
      run where sprite match became the joint-keep authority: neighbour
      consensus on, unique remainder demoted to tie-break.
  [UNLOCK 2026-08-26] "we have to unlock restrictions on joint adjustment or
      they will never get anywhere."
  [ROOT 2026-08-26/27] "This needs to be a DIFFERENT articulation method.
      Don't seed it with the fused poses." plus "still turns to the camera, and
      even worse than before." — per-frame root search re-rooted every frame
      and hid joint work, so the root is frozen after its stage.
  [SEED 2026-08-27] "I want to see this without the geometry ik seed, it's
      dominating."

Deliberately excluded, with the verdict that excludes each:

  * Geometry score mix (depth 0.99 / chroma 0.50 / silhouette 0.01) and mesh
    collision, both approved 2026-08-17. ``dinov3_dense`` fail-closes on them
    (``_validate_dinov3_dense_score``), so they cannot coexist with [KEEP].
    They are not silently dropped — choosing this profile is choosing DINOv3
    as the sole keep authority.
  * ``physics_smooth_enabled``. No user verdict approves it. The only two
    mentions are cautionary ("I want to focus on WHY it happens first";
    "it needs to be accurate and not completely dampen motion").
  * Root search, the unstick escape, rim/appendage silhouette weights, the
    still-sprite lock, the sprite-change gate, simulated annealing, the
    gradient ladder, chain space, geometry-IK pose seeding, and RIFE source
    frames — each explicitly rejected by the user.
  * base/mid/fine pose stages (approved 2026-08-17 for the geometry lane).
    [KEEP] ran without them; re-adding them is a step-count change the user
    has not seen, and it costs minutes against the stated 5-minute goal.

Proof tier: generated artifact (clip JSON + preview GIF). Not OE battle
runtime.
"""
from __future__ import annotations

from typing import Any

from roc_stacked_solve_common import STACKED_UNLOCK_BASE
from run_roc_stacked_dinov3_pass import DINOV3_SEMANTIC

# Wall-clock the user named as the iteration goal: "25 minutes is still way too
# long for test iterations like this. 5 is a better goal."
RUNTIME_GOAL_SEC = 300.0

CONSOLIDATED_WALK_PROFILE: dict[str, Any] = {
    # [UNLOCK] + [ROOT] + [SEED]: unlocked joints, sparse probes, frozen root,
    # no imported pose seed. STACKED_UNLOCK_BASE is the shared owner of those.
    **STACKED_UNLOCK_BASE,
    # [KEEP]: DINOv3 ViT-S/16 dense patch scoring.
    **DINOV3_SEMANTIC,
    # [KEEP]: 2x proxy raster, not the 4x default. Tied to the ~2 min runtime.
    "dense_semantic_raster_scale": 2,
    # [KEEP]: DINOv3 is the sole keep authority. dinov3_dense fail-closes
    # unless every geometry term is exactly zero.
    "score_mode": "dinov3_dense",
    "depth_weight": 0.0,
    "silhouette_weight": 0.0,
    "chroma_weight": 0.0,
    "motion_weight": 0.0,
    "collision_enabled": False,
    "collision_weight": 0.0,
    "joint_unique_gain_weight": 0.0,
    "fine_unique_gain_weight": 0.0,
    # [KEEP]: DINOv3 cannot score occupancy-only probes; IK stays off.
    "cheap_joint_probe_occupancy_only": False,
    "ik_enabled": False,
    # [KEEP]: full DINOv3 scoring on the worst 8 walk frames per probe instead
    # of the whole clip. This is the single reason the approved lane finishes in
    # ~2 min; STACKED_UNLOCK_BASE ships 0 (whole clip), which costs ~11 min.
    "cheap_joint_probe_frame_count": 8,
    # [KEEP]: later rounds re-probe only bones that kept a new angle, without
    # pulling in parent/child neighbours.
    "joint_round_followup_neighbors": False,
    # [KEEP]: loose joint search. Tighter steps drew "far, far too stiff".
    "articulated_iterations": 3,
    "joint_step_deg": 12.0,
    "fine_joint_step_deg": 8.0,
    "joint_pass_limit_deg": 45.0,
    "joint_probe_rungs": 3,
    "bone_order_mode": "dependency",
    # [NORM]: keep-score normalization for step sizing. Adaptive stepping stays
    # off because [KEEP] ran with fixed loose rungs.
    "joint_adaptive_step_enabled": False,
    "joint_step_score_norm": "logit_minmax",
    # [SPRITE]: neighbour consensus is the approved cure for adjacent frames
    # flipping independently. STACKED_UNLOCK_BASE disabled it because that lane
    # was an ablation; this is the consolidation that puts it back.
    "joint_temporal_consensus_enabled": True,
    "joint_temporal_consensus_tie_bonus": 0.01,
    "joint_temporal_consensus_bidirectional": True,
    "joint_temporal_consensus_independent_passes": True,
    "joint_temporal_consensus_whole_pose": True,
    "joint_temporal_consensus_idle_end": True,
    # [LOOP]: idle suffix mirrors the solved idle prefix so the cycle closes.
    "idle_suffix_mirror_prefix_enabled": True,
}

# Phase-B anatomy veto during articulated probe keep. DINO stays keep authority;
# strain/collision/prop only hard-reject or break DINO ties inside the band.
ANATOMY_VETO_BASE: dict[str, Any] = {
    "anatomy_veto_enabled": True,
    "anatomy_veto_strain_enabled": True,
    "anatomy_veto_collision_enabled": True,
    "anatomy_veto_prop_enabled": False,
    "anatomy_veto_strain_tolerance": 0.08,
    "anatomy_veto_strain_slack": 0.02,
    "anatomy_veto_collision_slack": 0.12,
    "anatomy_veto_prop_slack_px": 12.0,
    "anatomy_veto_hard_strain_margin": 0.03,
    "anatomy_veto_hard_collision_margin": 0.05,
    "anatomy_veto_hard_prop_margin_px": 24.0,
    "anatomy_veto_dino_tie_band": 0.002,
    "anatomy_veto_soft_weight": 0.05,
}


def consolidated_walk_overrides() -> dict[str, Any]:
    """Return a fresh copy of the profile for one solve."""
    return dict(CONSOLIDATED_WALK_PROFILE)


def consolidated_walk_anatomy_veto_overrides() -> dict[str, Any]:
    """Consolidated walk plus Phase-B anatomy veto during probe keep."""
    return {**consolidated_walk_overrides(), **ANATOMY_VETO_BASE}


def assert_dense_keep_authority(kwargs: dict[str, Any]) -> None:
    """Fail closed if a caller reintroduced a term dinov3_dense forbids.

    ``run_gpu_depth_fit_from_hybrid_config`` force-zeroes these, which would
    silently mask a caller that thought it had enabled collision or silhouette.
    Refusing here keeps the profile's scoring authority explicit.
    """
    if str(kwargs.get("score_mode")) != "dinov3_dense":
        raise RuntimeError(
            "consolidated walk profile is the dinov3_dense lane; "
            f"got score_mode={kwargs.get('score_mode')!r}"
        )
    forbidden = {
        "depth_weight": 0.0,
        "silhouette_weight": 0.0,
        "chroma_weight": 0.0,
        "motion_weight": 0.0,
        "collision_weight": 0.0,
        "joint_unique_gain_weight": 0.0,
        "fine_unique_gain_weight": 0.0,
    }
    offenders = {
        key: kwargs.get(key)
        for key, expected in forbidden.items()
        if float(kwargs.get(key) or 0.0) != expected
    }
    if bool(kwargs.get("collision_enabled")):
        offenders["collision_enabled"] = True
    if bool(kwargs.get("ik_enabled")):
        offenders["ik_enabled"] = True
    if offenders:
        raise RuntimeError(
            "dinov3_dense keep authority violated by: "
            + ", ".join(f"{key}={value!r}" for key, value in sorted(offenders.items()))
        )
    if not bool(kwargs.get("joint_temporal_consensus_enabled")):
        raise RuntimeError(
            "consolidated profile requires joint_temporal_consensus_enabled "
            "(user-approved cure for frame-to-frame flipping)"
        )
    if int(kwargs.get("cheap_joint_probe_frame_count") or 0) < 1:
        raise RuntimeError(
            "consolidated profile requires sparse joint probes "
            "(cheap_joint_probe_frame_count >= 1); whole-clip DINOv3 probes "
            "measured ~11 min on the roc walk against a 5 min goal"
        )
