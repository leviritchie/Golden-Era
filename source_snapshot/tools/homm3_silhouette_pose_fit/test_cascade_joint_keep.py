"""Joint keep is gain versus the current pose; unique remainder is not the keep."""
from __future__ import annotations

import inspect
import math

from gpu_geometry_score import unique_occupancy_quality
from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
from roc_gpu_cascade_experiment import (
    GpuCascadeConfig,
    apply_cluster_raw_bone,
    bidirectional_cluster_adopt,
    clip_uses_idle_end_anchor,
    cluster_bone_angles,
    copy_raw_bone_from_neighbor,
    gather_clip_winner,
    gather_per_frame_winners,
    independent_cluster_walks,
    joint_keep_score,
    joint_search_directions,
    lerp_raw_bone_from_neighbors,
    neighbor_copy_keep,
    offset_raw_bone_axis,
    offset_raw_bone_direction,
    idle_prefix_frame_count,
    idle_suffix_frame_count,
    pick_temporal_pose_pass,
    seed_end_cluster,
    sequential_cluster_adopt,
)


def run() -> dict[str, object]:
    import torch

    GpuCascadeConfig().validate()
    config = GpuCascadeConfig()
    assert float(config.joint_absolute_gain_weight) == 1.0
    assert float(config.joint_unique_gain_weight) == 0.35
    assert float(config.fine_unique_gain_weight) == 0.0
    assert float(config.joint_collision_positive_abs_slack) == 0.12
    assert bool(config.joint_temporal_consensus_enabled)
    assert float(config.joint_temporal_consensus_tie_bonus) == 1e-5
    assert bool(config.joint_temporal_consensus_bidirectional)
    assert bool(config.joint_temporal_consensus_idle_end)
    assert bool(config.joint_temporal_consensus_independent_passes)
    assert bool(config.joint_temporal_consensus_whole_pose)
    assert float(config.root_rotation_camera_up_limit_deg) == 45.0
    assert bool(config.root_rotation_defer_camera_up) is True
    assert bool(config.base_pose_enabled)
    assert int(config.base_pose_iterations) == 2
    assert bool(config.mid_pose_enabled)
    assert int(config.mid_pose_iterations) == 1
    assert float(config.mid_joint_step_deg) == 5.0
    assert int(config.fine_iterations) == 2
    assert bool(config.physics_smooth_enabled)
    assert bool(config.sprite_aligned_motion_keep_enabled) is False
    assert bool(config.joint_adaptive_step_enabled)
    assert float(config.joint_step_score_coarse) == 0.45
    assert float(config.joint_step_score_fine) == 0.80
    assert str(config.joint_step_score_norm) == "logit_minmax"
    assert bool(config.root_refit_after_base_enabled)
    assert bool(config.branch_rescue_enabled)
    assert int(config.joint_diagonal_axes) == 6
    try:
        GpuCascadeConfig(joint_absolute_gain_weight=0.0, joint_unique_gain_weight=0.0).validate()
        raise AssertionError("both joint gain weights zero must fail closed")
    except ValueError as exc:
        assert "cannot both be zero" in str(exc)

    signature = inspect.signature(run_gpu_depth_fit_from_hybrid_config)
    for name in (
        "root_translation_axes",
        "root_translation_limit_body_lengths",
        "seed_previous_frame",
        "joint_absolute_gain_weight",
        "joint_unique_gain_weight",
        "joint_collision_positive_abs_slack",
        "joint_temporal_consensus_enabled",
        "joint_temporal_consensus_tie_bonus",
        "joint_temporal_consensus_bidirectional",
        "joint_temporal_consensus_idle_end",
        "joint_temporal_consensus_independent_passes",
        "joint_temporal_consensus_whole_pose",
        "root_rotation_camera_up_limit_deg",
        "root_rotation_defer_camera_up",
        "base_pose_enabled",
        "mid_pose_enabled",
        "mid_joint_step_deg",
        "root_refit_after_base_enabled",
        "branch_rescue_enabled",
        "skip_tiny_bones",
        "joint_diagonal_axes",
        "physics_smooth_enabled",
        "physics_smooth_stiffness",
        "physics_smooth_gravity_weight",
        "sprite_aligned_motion_keep_enabled",
        "sprite_aligned_motion_keep_min_improvement",
        "joint_adaptive_step_enabled",
        "joint_step_score_coarse",
        "joint_step_score_fine",
        "joint_step_score_norm",
    ):
        assert name in signature.parameters, name

    current_abs = torch.tensor([0.50, 0.50])
    current_unique = torch.tensor([0.80, 0.80])
    current_col = torch.tensor([0.10, 0.10])
    zero_keep = joint_keep_score(
        absolute_geometry=current_abs,
        unique_geometry=current_unique,
        current_absolute=current_abs,
        current_unique=current_unique,
        collision=current_col,
        current_collision=current_col,
        absolute_gain_weight=1.0,
        unique_gain_weight=0.35,
        collision_weight=0.35,
        collision_enabled=True,
    )
    assert float(zero_keep.max().item()) == 0.0, zero_keep

    better_abs = torch.tensor([0.62, 0.61])
    worse_unique = torch.tensor([0.79, 0.78])
    abs_keep = joint_keep_score(
        absolute_geometry=better_abs,
        unique_geometry=worse_unique,
        current_absolute=current_abs,
        current_unique=current_unique,
        collision=current_col,
        current_collision=current_col,
        absolute_gain_weight=1.0,
        unique_gain_weight=0.35,
        collision_weight=0.35,
        collision_enabled=True,
    )
    unique_only = joint_keep_score(
        absolute_geometry=better_abs,
        unique_geometry=worse_unique,
        current_absolute=current_abs,
        current_unique=current_unique,
        collision=current_col,
        current_collision=current_col,
        absolute_gain_weight=0.0,
        unique_gain_weight=1.0,
        collision_weight=0.35,
        collision_enabled=True,
    )
    assert float(abs_keep.min().item()) > 0.0, abs_keep
    assert abs(float(unique_only.max().item())) < 1e-6, unique_only

    unique_veto_keep = joint_keep_score(
        absolute_geometry=better_abs,
        unique_geometry=worse_unique,
        current_absolute=current_abs,
        current_unique=current_unique,
        collision=current_col,
        current_collision=current_col,
        absolute_gain_weight=1.0,
        unique_gain_weight=0.35,
        collision_weight=0.35,
        collision_enabled=True,
    )
    assert float(unique_veto_keep.min().item()) > 0.0, unique_veto_keep

    worse_abs = torch.tensor([0.45, 0.44])
    better_unique = torch.tensor([0.99, 0.99])
    unique_rescue = joint_keep_score(
        absolute_geometry=worse_abs,
        unique_geometry=better_unique,
        current_absolute=current_abs,
        current_unique=current_unique,
        collision=current_col,
        current_collision=current_col,
        absolute_gain_weight=1.0,
        unique_gain_weight=0.35,
        collision_weight=0.35,
        collision_enabled=False,
    )
    assert float(unique_rescue.max().item()) < 0.0, unique_rescue

    sprite_neutral = joint_keep_score(
        absolute_geometry=current_abs,
        unique_geometry=better_unique,
        current_absolute=current_abs,
        current_unique=current_unique,
        collision=current_col,
        current_collision=current_col,
        absolute_gain_weight=1.0,
        unique_gain_weight=0.35,
        collision_enabled=False,
        collision_weight=0.35,
    )
    assert float(sprite_neutral.min().item()) > 0.0, sprite_neutral

    pretzel_col = torch.tensor([0.90, 0.90])
    pretzel_keep = joint_keep_score(
        absolute_geometry=better_abs,
        unique_geometry=current_unique,
        current_absolute=current_abs,
        current_unique=current_unique,
        collision=pretzel_col,
        current_collision=current_col,
        absolute_gain_weight=1.0,
        unique_gain_weight=0.35,
        collision_weight=0.35,
        collision_enabled=True,
    )
    assert float(pretzel_keep.max().item()) < 0.0, pretzel_keep

    modest_contact = joint_keep_score(
        absolute_geometry=better_abs,
        unique_geometry=current_unique,
        current_absolute=current_abs,
        current_unique=current_unique,
        collision=torch.tensor([0.18, 0.18]),
        current_collision=current_col,
        absolute_gain_weight=1.0,
        unique_gain_weight=0.35,
        collision_weight=0.35,
        collision_enabled=True,
        collision_positive_abs_slack=0.12,
    )
    assert float(modest_contact.min().item()) > 0.0, modest_contact

    # Common raised-arm target in every frame: unique remainder is empty,
    # but covering the arm still improves the absolute score.
    body = torch.zeros((2, 8, 8), dtype=torch.float32)
    body[:, 2:6, 2:6] = 1.0
    raised = body.clone()
    raised[:, 2:6, 6:8] = 1.0
    unique_common = unique_occupancy_quality(
        target_foreground=raised,
        predicted_foreground=body,
    )
    assert float(unique_common["uniqueOccupancyError"].max().item()) < 1e-6, unique_common
    unique_covered = unique_occupancy_quality(
        target_foreground=raised,
        predicted_foreground=raised,
    )
    assert float(unique_covered["uniqueOccupancyError"].max().item()) < 1e-6
    bind_abs = torch.tensor([0.40, 0.40])
    covered_abs = torch.tensor([0.70, 0.70])
    common_keep = joint_keep_score(
        absolute_geometry=covered_abs,
        unique_geometry=unique_covered["uniqueOccupancyQuality"],
        current_absolute=bind_abs,
        current_unique=unique_common["uniqueOccupancyQuality"],
        collision=torch.zeros(2),
        current_collision=torch.zeros(2),
        absolute_gain_weight=1.0,
        unique_gain_weight=0.35,
        collision_weight=0.35,
        collision_enabled=False,
    )
    unique_keep = joint_keep_score(
        absolute_geometry=covered_abs,
        unique_geometry=unique_covered["uniqueOccupancyQuality"],
        current_absolute=bind_abs,
        current_unique=unique_common["uniqueOccupancyQuality"],
        collision=torch.zeros(2),
        current_collision=torch.zeros(2),
        absolute_gain_weight=0.0,
        unique_gain_weight=1.0,
        collision_weight=0.35,
        collision_enabled=False,
    )
    assert float(common_keep.min().item()) > 0.0, common_keep
    assert abs(float(unique_keep.max().item())) < 1e-6, unique_keep

    directions = joint_search_directions(("x", "y", "z"), 6)
    assert directions[:3] == ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    assert len(directions) == 9
    xy = tuple(round(part, 6) for part in directions[3])
    expected_xy = tuple(round(part / math.sqrt(2.0), 6) for part in (1.0, 1.0, 0.0))
    assert xy == expected_xy, (xy, expected_xy)

    scales = torch.ones(3, dtype=torch.float32)
    raw = torch.zeros((2, 3, 3), dtype=torch.float32)
    axis_moved = offset_raw_bone_axis(
        raw,
        bone_index=1,
        axis_index=0,
        delta_rad=math.radians(15.0),
        joint_limit_rad=math.radians(150.0),
        bone_limit_scales=scales,
    )
    dir_moved = offset_raw_bone_direction(
        raw,
        bone_index=1,
        direction=(1.0, 0.0, 0.0),
        delta_rad=math.radians(15.0),
        joint_limit_rad=math.radians(150.0),
        bone_limit_scales=scales,
    )
    assert torch.allclose(axis_moved, dir_moved, atol=1e-6)
    diagonal_moved = offset_raw_bone_direction(
        raw,
        bone_index=1,
        direction=(1.0, 0.0, 1.0),
        delta_rad=math.radians(15.0),
        joint_limit_rad=math.radians(150.0),
        bone_limit_scales=scales,
    )
    assert float(diagonal_moved[:, 1, 0].abs().min().item()) > 0.0
    assert float(diagonal_moved[:, 1, 2].abs().min().item()) > 0.0
    assert float(diagonal_moved[:, 1, 1].abs().max().item()) < 1e-6

    limit = math.radians(150.0)
    neighbor_raw = torch.zeros((3, 2, 3), dtype=torch.float32)
    neighbor_raw[1, 1, 0] = math.atanh(math.radians(15.0) / limit)
    neighbor_raw[2, 1, 0] = math.atanh(math.radians(-15.0) / limit)
    copied_prev = copy_raw_bone_from_neighbor(
        neighbor_raw,
        bone_index=1,
        source_offset=-1,
        joint_limit_rad=limit,
        bone_limit_scales=torch.ones(2, dtype=torch.float32),
    )
    copied_bounded = torch.tanh(copied_prev) * limit
    assert float(copied_bounded[0, 1, 0].abs().item()) < 1e-6
    assert abs(float(copied_bounded[1, 1, 0].item()) - 0.0) < 1e-5
    assert abs(float(copied_bounded[2, 1, 0].item()) - math.radians(15.0)) < 1e-5
    lerped = lerp_raw_bone_from_neighbors(
        neighbor_raw,
        bone_index=1,
        joint_limit_rad=limit,
        bone_limit_scales=torch.ones(2, dtype=torch.float32),
    )
    lerped_bounded = torch.tanh(lerped) * limit
    assert abs(float(lerped_bounded[1, 1, 0].item()) - math.radians(-7.5)) < 1e-5
    equal_keep = neighbor_copy_keep(
        torch.tensor([0.50, 0.50]),
        torch.tensor([0.50, 0.50]),
        tie_bonus=1e-5,
    )
    worse_keep = neighbor_copy_keep(
        torch.tensor([0.49, 0.49]),
        torch.tensor([0.50, 0.50]),
        tie_bonus=1e-5,
    )
    better_keep = neighbor_copy_keep(
        torch.tensor([0.52, 0.52]),
        torch.tensor([0.50, 0.50]),
        tie_bonus=1e-5,
    )
    assert float(equal_keep.min().item()) > 0.0
    assert float(worse_keep.max().item()) < 0.0
    assert float(better_keep.min().item()) > 0.02

    # A real tie budget trades a bounded amount of sprite score for the
    # smoother neighbor angle; loss beyond the budget still refuses the copy.
    budget_keep = neighbor_copy_keep(
        torch.tensor([0.492, 0.480]),
        torch.tensor([0.50, 0.50]),
        tie_bonus=0.01,
    )
    assert float(budget_keep[0].item()) > 0.0  # -0.008 is within the 0.01 budget
    assert float(budget_keep[1].item()) < 0.0  # -0.020 exceeds the budget
    try:
        GpuCascadeConfig(joint_temporal_consensus_tie_bonus=0.0).validate()
        raise AssertionError("zero tie bonus must fail closed")
    except ValueError as exc:
        assert "tie_bonus must be positive" in str(exc)

    tiny = torch.tensor([0.0, 1e-9])
    plus = torch.tensor([0.0, 1e-9])
    big = torch.tensor([0.0, 0.20])
    _blended, winner, _chosen = gather_per_frame_winners(
        [raw, axis_moved, diagonal_moved],
        [tiny, plus, big],
        min_improvement=1e-6,
    )
    assert winner.tolist() == [0, 2], winner.tolist()

    clip_raw, clip_winner, _clip_scores = gather_clip_winner(
        [raw, axis_moved],
        [torch.tensor([0.10, 0.10]), torch.tensor([0.40, 0.40])],
        min_improvement=1e-6,
    )
    assert int(clip_winner) == 1
    assert torch.equal(clip_raw, axis_moved)

    clustered, unique = cluster_bone_angles(
        (
            (0.1, 0.0, 0.0),
            (0.1, 0.0, 0.0),
            (0.0, 0.2, 0.0),
            (0.0, 0.2, 0.0),
        )
    )
    assert clustered.tolist() == [0, 0, 1, 1]
    assert unique.shape == (2, 3)

    chain_scores = (
        (0.90, 0.90, 0.90, 0.90),
        (0.50, 0.50, 0.50, 0.50),
    )
    start_early = (0, 1, 1, 1)
    frozen = list(start_early)
    original = list(start_early)
    for index in range(1, 4):
        source = original[index - 1]
        current = original[index]
        if source == current:
            continue
        if (chain_scores[source][index] - chain_scores[current][index]) + 0.01 > 0.0:
            frozen[index] = source
    assert frozen == [0, 0, 1, 1], frozen
    forward, n_fwd = sequential_cluster_adopt(
        start_early, chain_scores, tie_bonus=0.01, reverse=False
    )
    assert forward.tolist() == [0, 0, 0, 0], forward.tolist()
    assert n_fwd == 3
    reverse, n_rev = sequential_cluster_adopt(
        (1, 1, 1, 0), chain_scores, tie_bonus=0.01, reverse=True
    )
    assert reverse.tolist() == [0, 0, 0, 0], reverse.tolist()
    assert n_rev == 3
    def cluster_frame_abs(assignment, scores):
        return tuple(
            float(scores[int(label)][index]) for index, label in enumerate(assignment)
        )

    fwd_both, rev_both, both_fwd, both_rev, both_end = independent_cluster_walks(
        (1, 1, 1, 0), chain_scores, tie_bonus=0.01
    )
    assert fwd_both.tolist() == [1, 1, 1, 0]
    assert rev_both.tolist() == [0, 0, 0, 0]
    assert both_fwd == 0
    assert both_rev == 3
    assert both_end == 0
    wrapped = bidirectional_cluster_adopt((1, 1, 1, 0), chain_scores, tie_bonus=0.01)
    assert wrapped[0].tolist() == fwd_both.tolist()
    assert wrapped[1].tolist() == rev_both.tolist()
    choice_both, both_rev_pick = pick_temporal_pose_pass(
        cluster_frame_abs((1, 1, 1, 0), chain_scores),
        cluster_frame_abs(fwd_both, chain_scores),
        cluster_frame_abs(rev_both, chain_scores),
    )
    assert choice_both.tolist() == [2, 2, 2, 0]
    assert both_rev_pick == 3

    fwd_idle, rev_idle, idle_fwd, idle_rev, idle_end = independent_cluster_walks(
        (0, 1, 1, 1),
        chain_scores,
        tie_bonus=0.01,
        end_cluster=0,
    )
    assert fwd_idle.tolist() == [0, 0, 0, 0], fwd_idle.tolist()
    assert rev_idle.tolist() == [0, 0, 0, 0], rev_idle.tolist()
    assert idle_fwd == 3
    assert idle_end == 1
    assert idle_rev == 2
    choice_idle, idle_rev_pick = pick_temporal_pose_pass(
        cluster_frame_abs((0, 1, 1, 1), chain_scores),
        cluster_frame_abs(fwd_idle, chain_scores),
        cluster_frame_abs(rev_idle, chain_scores),
    )
    assert choice_idle.tolist() == [0, 2, 2, 2]
    assert idle_rev_pick == 3

    from_end_scores = (
        (0.90, 0.40, 0.40, 0.90),
        (0.50, 0.80, 0.80, 0.50),
    )
    fwd_from_end, rev_from_end, from_end_fwd, from_end_rev, from_end_idle = independent_cluster_walks(
        (0, 1, 1, 1),
        from_end_scores,
        tie_bonus=0.01,
        end_cluster=0,
    )
    assert fwd_from_end.tolist() == [0, 1, 1, 1]
    assert rev_from_end.tolist() == [0, 1, 1, 0], rev_from_end.tolist()
    assert from_end_fwd == 0
    assert from_end_idle == 1
    assert from_end_rev == 0
    choice_from_end, from_end_rev_pick = pick_temporal_pose_pass(
        cluster_frame_abs((0, 1, 1, 1), from_end_scores),
        cluster_frame_abs(fwd_from_end, from_end_scores),
        cluster_frame_abs(rev_from_end, from_end_scores),
    )
    assert choice_from_end.tolist() == [0, 0, 0, 2]
    assert from_end_rev_pick == 1

    # Strike in the middle, recovery near the end looks like rest: reverse
    # starts from idle on its own copy. Whole-pose pick keeps that recovery
    # idle without mixing a forward strike joint into a reverse body turn.
    recovery_scores = (
        (0.90, 0.40, 0.85, 0.90),
        (0.50, 0.80, 0.50, 0.50),
    )
    fwd_recovery, rev_recovery, recovery_fwd, recovery_rev, recovery_idle = independent_cluster_walks(
        (0, 1, 1, 1),
        recovery_scores,
        tie_bonus=0.01,
        end_cluster=0,
    )
    assert fwd_recovery.tolist() == [0, 1, 1, 1]
    assert rev_recovery.tolist() == [0, 1, 0, 0], rev_recovery.tolist()
    assert recovery_fwd == 0
    assert recovery_idle == 1
    assert recovery_rev == 1
    choice_recovery, recovery_rev_pick = pick_temporal_pose_pass(
        cluster_frame_abs((0, 1, 1, 1), recovery_scores),
        cluster_frame_abs(fwd_recovery, recovery_scores),
        cluster_frame_abs(rev_recovery, recovery_scores),
    )
    assert choice_recovery.tolist() == [0, 0, 2, 2]
    assert recovery_rev_pick == 2

    # Forward copies a swing onto a late off-rails frame. Reverse must still
    # start from idle on the original last frame, not from that swing. The
    # whole-pose pick then keeps reverse's last-frame idle, not a mix of
    # forward swing + reverse root.
    rails_scores = (
        (0.90, 0.35, 0.35, 0.88),
        (0.40, 0.80, 0.80, 0.50),
        (0.30, 0.40, 0.40, 0.45),
    )
    original_rails = (0, 1, 1, 2)
    polluted_fwd, _ = sequential_cluster_adopt(
        original_rails, rails_scores, tie_bonus=0.01, reverse=False
    )
    assert polluted_fwd.tolist() == [0, 1, 1, 1], polluted_fwd.tolist()
    fwd_rails, rev_rails, rails_fwd, rails_rev, rails_idle = independent_cluster_walks(
        original_rails,
        rails_scores,
        tie_bonus=0.01,
        end_cluster=0,
    )
    assert rails_fwd == 1
    assert rails_idle == 1
    assert rails_rev == 0
    assert fwd_rails.tolist() == [0, 1, 1, 1]
    assert rev_rails.tolist() == [0, 1, 1, 0], rev_rails.tolist()
    choice_rails, rails_rev_pick = pick_temporal_pose_pass(
        cluster_frame_abs(original_rails, rails_scores),
        cluster_frame_abs(fwd_rails, rails_scores),
        cluster_frame_abs(rev_rails, rails_scores),
    )
    assert choice_rails.tolist() == [0, 0, 0, 2]
    assert rails_rev_pick == 1

    # Same local joint numbers can point different world directions when
    # parent/root rotation differs. Orig wins exact ties; if orig loses and
    # reverse ties forward, keep reverse as a complete pose, not bone-wise.
    choice_pose, n_rev_pose = pick_temporal_pose_pass(
        (0.50, 0.40, 0.50),
        (0.50, 0.80, 0.70),
        (0.50, 0.80, 0.60),
    )
    assert choice_pose.tolist() == [0, 2, 1]
    assert n_rev_pose == 1

    assert clip_uses_idle_end_anchor((2, 13)) is True
    assert clip_uses_idle_end_anchor((2, 21)) is True
    assert clip_uses_idle_end_anchor((2, 1)) is True
    assert clip_uses_idle_end_anchor((2, 3)) is True
    assert clip_uses_idle_end_anchor((2, 4)) is True
    assert clip_uses_idle_end_anchor((2, 14)) is True
    assert clip_uses_idle_end_anchor((2, 20, 0)) is True
    assert clip_uses_idle_end_anchor((2, 20, 0, 21, 2)) is True
    assert clip_uses_idle_end_anchor((2, 12, 2)) is True
    assert clip_uses_idle_end_anchor((2, 5)) is False
    assert clip_uses_idle_end_anchor((2, 6)) is False
    assert clip_uses_idle_end_anchor((2, 20)) is True
    assert clip_uses_idle_end_anchor((2,)) is False
    assert idle_prefix_frame_count((2, 13), (8, 13)) == 8
    assert idle_suffix_frame_count((2, 12, 2), (8, 13, 8)) == 8
    assert idle_suffix_frame_count((2, 20, 0), (8, 2, 8)) == 0
    seeded, n_seeded = seed_end_cluster(
        (0, 1, 1, 1),
        (
            (0.90, 0.40, 0.40, 0.90),
            (0.50, 0.80, 0.80, 0.50),
        ),
        end_cluster=0,
        tie_bonus=0.01,
        suffix_frames=2,
    )
    assert seeded.tolist() == [0, 1, 1, 0], seeded.tolist()
    assert n_seeded == 1

    refuse_scores = (
        (0.90, 0.90, 0.10, 0.90),
        (0.50, 0.50, 0.50, 0.50),
    )
    refused, _ = sequential_cluster_adopt(
        (0, 1, 1, 1), refuse_scores, tie_bonus=0.01, reverse=False
    )
    assert refused.tolist() == [0, 0, 1, 1], refused.tolist()

    raw_clusters = torch.zeros((4, 2, 3), dtype=torch.float32)
    raw_clusters[0, 1, 0] = 0.4
    raw_clusters[1, 1, 0] = 0.1
    applied = apply_cluster_raw_bone(
        raw_clusters,
        bone_index=1,
        unique_raw=((0.4, 0.0, 0.0), (0.1, 0.0, 0.0)),
        assignment=(0, 0, 0, 0),
    )
    assert float(applied[:, 1, 0].min().item()) > 0.39

    return {
        "ok": True,
        "commonKeep": float(common_keep.mean().item()),
        "uniqueKeep": float(unique_keep.mean().item()),
        "directions": len(directions),
        "clipWinner": int(clip_winner),
    }


if __name__ == "__main__":
    print(run())
