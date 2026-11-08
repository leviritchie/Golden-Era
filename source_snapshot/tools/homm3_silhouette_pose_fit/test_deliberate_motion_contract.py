"""Deliberate-motion fixtures, seams, and Animator graph contract."""
from __future__ import annotations

from deliberate_motion_animator_contract import (
    owned_ground_controller_contract,
    simulate_ground_chain,
    validate_controller_graph,
)
from deliberate_motion_boundaries import cycle_seam_report
from deliberate_motion_contract import (
    AUTHENTIC_DEF_FRAME_DURATION_SECONDS,
    PREVIEW_FRAME_DURATION_SECONDS,
    build_unit_contract,
    clip_lifecycle_row,
    cycle_duration_seconds,
    cycle_key_count,
    loop_time_for_role,
    sample_times_seconds,
)
from deliberate_motion_gate import (
    MotionIsland,
    decide_branch,
    hold_branch_at_entry,
    motion_islands_from_evidence,
    motion_recall,
)


def _pose(yaw: float) -> dict[str, dict[str, float]]:
    return {"arm": {"x": 0.0, "y": yaw, "z": 0.0}}


def run() -> dict[str, object]:
    idle = clip_lifecycle_row(clip_name="Unit_Idle", def_group=2, source_frame_count=8)
    assert idle["lifecycleRole"] == "cycle"
    assert idle["loopTime"] is True
    assert idle["keyCount"] == 9
    assert idle["timingOwner"] == "authentic_def_group_playback"
    assert abs(idle["previewFrameDurationSeconds"] - PREVIEW_FRAME_DURATION_SECONDS) < 1e-12
    assert abs(cycle_duration_seconds(8) - 8 * AUTHENTIC_DEF_FRAME_DURATION_SECONDS) < 1e-12
    assert sample_times_seconds(8, role="cycle")[-1] == 8 * AUTHENTIC_DEF_FRAME_DURATION_SECONDS
    start = clip_lifecycle_row(clip_name="Unit_MoveStart", def_group=20, source_frame_count=1)
    assert start["lifecycleRole"] == "entry"
    assert start["loopTime"] is False
    assert start["fullAnimationReadiness"] == "blocked_one_pose_transition"
    assert loop_time_for_role("terminal") is False
    assert cycle_key_count(8) == 9

    contract = build_unit_contract(
        "h3_goblin",
        [
            clip_lifecycle_row(clip_name="Unit_Idle", def_group=2, source_frame_count=8),
            clip_lifecycle_row(clip_name="Unit_Move", def_group=0, source_frame_count=8),
        ],
    )
    assert contract["canonicalIdle"] == "Unit_Idle"
    assert contract["canonicalMove"] == "Unit_Move"
    try:
        build_unit_contract(
            "dup",
            [
                clip_lifecycle_row(clip_name="Unit_Idle", def_group=2, source_frame_count=8),
                clip_lifecycle_row(clip_name="Unit_Idle", def_group=2, source_frame_count=8),
            ],
        )
        raise AssertionError("duplicate Idle producers must fail")
    except ValueError as exc:
        assert "duplicate" in str(exc)

    island = MotionIsland("arm", ("arm",), 1, 1)
    still = {0: _pose(0.0), 1: _pose(40.0), 2: _pose(40.0)}
    pop = decide_branch(
        island=island,
        current_pairs=(0.50003, 0.50),
        hold_pairs=(0.50, 0.50),
        poses=still,
        landmark_current=0.50,
        landmark_hold=0.50,
        rendered_or_landmark_gain=0.00003,
        rendered_motion=0.0,
        source_island_present=False,
    )
    assert pop.retained is False, pop
    held = hold_branch_at_entry(still, island)
    assert held[1]["arm"] == held[0]["arm"]

    recall_ok, recall_reason = motion_recall(
        source_island_present=True, rendered_motion=0.0, landmark_motion=0.0
    )
    assert recall_ok is False and recall_reason == "frozen_over_source_motion"

    adjacent = decide_branch(
        island=island,
        current_pairs=(0.70, 0.40),
        hold_pairs=(0.50, 0.45),
        poses=still,
        landmark_current=0.70,
        landmark_hold=0.50,
        regional_appearance_supports=True,
        rendered_or_landmark_gain=0.1,
    )
    assert adjacent.retained is False
    assert adjacent.reason == "local_pairs"

    swing_poses = {0: _pose(0.0), 1: _pose(20.0), 2: _pose(40.0)}
    swing_island = MotionIsland("arm", ("arm",), 0, 2, evidence=("landmark", "occupancy"))
    swing = decide_branch(
        island=swing_island,
        current_pairs=(0.62, 0.58),
        hold_pairs=(0.40, 0.41),
        poses=swing_poses,
        landmark_current=0.70,
        landmark_hold=0.40,
        rendered_or_landmark_gain=0.20,
        rendered_motion=0.8,
        landmark_motion=0.3,
    )
    assert swing.retained is True, swing

    internal = decide_branch(
        island=swing_island,
        current_pairs=(0.50, 0.50),
        hold_pairs=(0.50, 0.50),
        poses=swing_poses,
        landmark_current=0.50,
        landmark_hold=0.50,
        rendered_or_landmark_gain=0.0,
        rendered_motion=0.0,
        landmark_motion=0.0,
        source_island_present=False,
    )
    assert internal.retained is False

    root_island = MotionIsland(
        "root",
        ("root",),
        0,
        1,
        expected_direction=(1.0, 0.0, 0.0),
        evidence=("occupancy",),
    )
    root_reject = decide_branch(
        island=root_island,
        current_pairs=(0.80,),
        hold_pairs=(0.40,),
        poses={0: {"root": {"x": 0.0, "y": 0.0, "z": 0.0}}, 1: {"root": {"x": 0.0, "y": 30.0, "z": 0.0}}},
        landmark_current=0.80,
        landmark_hold=0.40,
        regional_appearance_supports=True,
        rendered_or_landmark_gain=0.40,
        root_step=(0.0, 1.0, 0.0),
    )
    assert root_reject.retained is False
    assert root_reject.reason == "root_direction"

    flags = [False, True, True, True, False]
    islands = motion_islands_from_evidence(
        branch="arm", bones=("arm",), frame_evidence=flags, evidence=("occupancy",)
    )
    assert len(islands) == 1
    assert islands[0].frame_start == 1 and islands[0].frame_end == 3

    closed = {0: _pose(0.0), 1: _pose(10.0), 2: _pose(0.0)}
    closed_report = cycle_seam_report(
        closed, frame_duration_seconds=AUTHENTIC_DEF_FRAME_DURATION_SECONDS, c0_limit_deg=1.0
    )
    assert closed_report["c0Pass"] is True
    open_loop = {0: _pose(0.0), 1: _pose(10.0), 2: _pose(40.0)}
    open_report = cycle_seam_report(
        open_loop, frame_duration_seconds=AUTHENTIC_DEF_FRAME_DURATION_SECONDS, c0_limit_deg=1.0
    )
    assert open_report["c0Pass"] is False
    motion_ok_wrap_bad = decide_branch(
        island=swing_island,
        current_pairs=(0.62, 0.58),
        hold_pairs=(0.40, 0.41),
        poses=open_loop,
        landmark_current=0.70,
        landmark_hold=0.40,
        rendered_or_landmark_gain=0.20,
        rendered_motion=0.8,
        landmark_motion=0.3,
    )
    assert motion_ok_wrap_bad.retained is True
    assert open_report["c0Pass"] is False

    graph = owned_ground_controller_contract()
    assert validate_controller_graph(graph) == []
    bypass = dict(graph)
    bypass["transitions"] = list(graph["transitions"]) + [{"from": "22.Idle", "to": "01.Walk"}]
    assert any("forbidden" in item for item in validate_controller_graph(bypass))
    poller = dict(graph)
    poller["updatePoller"] = True
    assert any("poller" in item.lower() or "Play" in item for item in validate_controller_graph(poller))

    chain = simulate_ground_chain(
        move_asserted_frames=[False, True, True, True, True, False, False, False],
        move_start_length=2,
        move_length=2,
        move_end_length=2,
    )
    assert chain[0] == "22.Idle"
    assert "ground.MoveStart" in chain
    assert "01.Walk" in chain
    assert "ground.MoveEnd" in chain
    assert chain[-1] == "22.Idle"

    cancel = simulate_ground_chain(
        move_asserted_frames=[True, False, False, False],
        move_start_length=3,
        move_length=4,
        move_end_length=2,
    )
    assert cancel == [
        "22.Idle",
        "ground.MoveStart",
        "ground.MoveEnd",
        "22.Idle",
    ]
    restart = simulate_ground_chain(
        move_asserted_frames=[True, True, False, True, True, True],
        move_start_length=2,
        move_length=2,
        move_end_length=3,
    )
    assert "ground.MoveEnd" in restart
    assert restart.count("ground.MoveStart") == 2
    return {"ok": True}


if __name__ == "__main__":
    print(run())
