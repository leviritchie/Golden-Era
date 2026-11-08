"""Later cascade rounds skip settled bones; Adam leaves after consecutive rejects.

Consensus after a no-move probe is skipped — it would rescore the same pose.
"""
from __future__ import annotations

from roc_gpu_cascade_experiment import (
    GpuCascadeConfig,
    adam_stage_stalled,
    joint_probe_should_run_consensus,
    joint_round_followup_bones,
    joint_round_should_run_consensus,
    joint_score_hyps_per_launch,
)


def run() -> dict[str, object]:
    config = GpuCascadeConfig()
    config.validate()
    assert int(config.adam_stall_reject_streak) == 3, config.adam_stall_reject_streak
    assert bool(config.joint_round_followup_neighbors) is True
    try:
        GpuCascadeConfig(adam_stall_reject_streak=-1).validate()
        raise AssertionError("negative adam stall patience must fail closed")
    except ValueError as exc:
        assert "adam_stall_reject_streak" in str(exc)

    assert adam_stage_stalled(2, 3) is False
    assert adam_stage_stalled(3, 3) is True
    assert adam_stage_stalled(12, 3) is True
    assert joint_score_hyps_per_launch(pose_budget=16, frame_count=28) == 1
    assert joint_score_hyps_per_launch(pose_budget=512, frame_count=28) == 18
    assert joint_score_hyps_per_launch(pose_budget=512, frame_count=18) == 28
    try:
        joint_score_hyps_per_launch(pose_budget=0, frame_count=18)
        raise AssertionError("zero pose budget must fail closed")
    except ValueError as exc:
        assert "pose_budget" in str(exc)

    assert joint_probe_should_run_consensus(probe_moved=0) is False
    assert joint_probe_should_run_consensus(probe_moved=1) is True
    assert joint_probe_should_run_consensus(probe_moved=8) is True
    try:
        joint_probe_should_run_consensus(probe_moved=-1)
        raise AssertionError("negative probe_moved must fail closed")
    except ValueError as exc:
        assert "probe_moved" in str(exc)

    assert joint_round_should_run_consensus(
        probe_moved_count=0, combo_moved_count=0, shared_keep=False
    ) is False
    assert joint_round_should_run_consensus(
        probe_moved_count=2, combo_moved_count=0, shared_keep=False
    ) is True
    assert joint_round_should_run_consensus(
        probe_moved_count=0, combo_moved_count=4, shared_keep=False
    ) is True
    assert joint_round_should_run_consensus(
        probe_moved_count=8, combo_moved_count=8, shared_keep=True
    ) is False
    try:
        joint_round_should_run_consensus(
            probe_moved_count=-1, combo_moved_count=0, shared_keep=False
        )
        raise AssertionError("negative probe_moved_count must fail closed")
    except ValueError as exc:
        assert "probe_moved_count" in str(exc)

    # Chain 0→1→2→3. Order is the search walk, not sorted ids.
    bones = (10, 11, 12, 13)
    parent_of = {10: None, 11: 10, 12: 11, 13: 12}

    empty = joint_round_followup_bones(bones, (), parent_of)
    assert empty == (), empty

    # Consensus-only "accept" is not a probe mover: next round would rescore
    # the same ±15° window on the same pose.
    consensus_only = joint_round_followup_bones(bones, [], parent_of)
    assert consensus_only == (), consensus_only

    leaf_only = joint_round_followup_bones(bones, (13,), parent_of)
    assert leaf_only == (12, 13), leaf_only

    mid_pair = joint_round_followup_bones(bones, (11, 12), parent_of)
    assert mid_pair == (10, 11, 12, 13), mid_pair

    root_only = joint_round_followup_bones(bones, (10,), parent_of)
    assert root_only == (10, 11), root_only

    # Unknown mover ids are ignored; search order is preserved.
    ordered = joint_round_followup_bones((13, 10, 12, 11), (12, 99), parent_of)
    assert ordered == (13, 12, 11), ordered

    # skip_tiny can drop a mid-chain bone. The next search ancestor is still
    # a neighbor on the search graph.
    gapped = {10: None, 11: 10, 12: 11, 13: 12}
    across_gap = joint_round_followup_bones((10, 12, 13), (12,), gapped)
    assert across_gap == (10, 12, 13), across_gap

    return {
        "ok": True,
        "leafOnly": list(leaf_only),
        "midPair": list(mid_pair),
        "adamPatience": int(config.adam_stall_reject_streak),
    }


if __name__ == "__main__":
    print(run())
