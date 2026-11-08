"""Small regression tests for the black-box clip search stages.

These tests stay renderer-free. They verify the search contract that the
notebook relies on: independent probes are batched, coherent adjacent-frame
moves can survive temporal regularization, and the adaptive/polish stages are
actually entered rather than being configuration no-ops.
"""
from __future__ import annotations

import sys
from pathlib import Path


TOOL = Path(__file__).resolve().parent
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from roc_temporal_clip_optimizer import (  # noqa: E402
    MOTION_ROOT_KEY,
    MOTION_ROOT_ROTATION_KEY,
    TemporalClipConfig,
    clip_objective,
    optimize_clip,
    temporal_terms,
)


def test_staged_clip_search_batches_and_finds_coherent_motion():
    batch_sizes = []

    def score_frame(frame, pose, label, live):
        del label, live
        x = float(pose["root"]["x"])
        target = 30.0
        return 1.0 - ((x - target) ** 2) / 10000.0, {"ok": True}, 0.001

    def score_frame_batch(frame, entries):
        del frame
        batch_sizes.append(len(entries))
        return [score_frame(0, pose, label, live) for pose, label, live in entries]

    config = TemporalClipConfig(
        rounds=1,
        refine_rounds=1,
        coarse_step_deg=8.0,
        refine_step_deg=2.0,
        candidate_mode="local",
        max_evaluations_per_axis=3,
        velocity_weight=0.08,
        robust_scale_deg=16.0,
        batch_candidates=True,
        probe_enabled=True,
        probe_step_deg=30.0,
        probe_top_k=4,
        probe_min_improvement=-1.0,
        adaptive_blocks_enabled=True,
        adaptive_block_size=2,
        adaptive_rounds=1,
        adaptive_step_deg=10.0,
        adaptive_beam_width=2,
        polish_enabled=True,
        polish_rounds=1,
        polish_step_deg=2.0,
        adaptive_groups=(("root",),),
    )
    result = optimize_clip(
        [0, 1],
        ["root"],
        {0: {}, 1: {}},
        score_frame,
        lambda _bone: (-90.0, 90.0),
        config,
        score_frame_batch=score_frame_batch,
        live_preview=False,
    )

    kinds = [row["kind"] for row in result["history"]]
    assert "clip_batch_probe" in kinds
    assert "clip_sparse_combo" in kinds
    assert "clip_adaptive_block" in kinds
    assert any(size > 1 for size in batch_sizes)
    combo = next(row for row in result["history"] if row["kind"] == "clip_sparse_combo")
    assert combo["accepted"]


def test_progress_callback_reports_each_unique_evaluation():
    events = []

    def score_frame(frame, pose, label, live):
        del frame, label, live
        x = float(pose["root"]["x"])
        return 1.0 - ((x - 8.0) ** 2) / 1000.0, {"ok": True}, 0.001

    config = TemporalClipConfig(
        rounds=1,
        refine_rounds=1,
        axes=("x",),
        coarse_step_deg=4.0,
        refine_step_deg=1.0,
        candidate_mode="local",
        max_evaluations_per_axis=3,
        batch_candidates=False,
        probe_enabled=False,
        adaptive_blocks_enabled=False,
        polish_enabled=False,
    )
    result = optimize_clip(
        [0],
        ["root"],
        {0: {}},
        score_frame,
        lambda _bone: (-20.0, 20.0),
        config,
        progress=events.append,
        live_preview=False,
    )

    assert len(events) == result["evaluations"]
    assert events
    assert [event["evaluation"] for event in events] == list(
        range(1, len(events) + 1)
    )
    assert all(event["kind"] == "evaluation" for event in events)


def test_motion_root_is_normalized_and_temporally_penalized_once():
    config = TemporalClipConfig(
        motion_root_enabled=True,
        motion_root_axes=("forward",),
        motion_root_forward_radius_body_lengths=0.20,
        motion_root_coarse_step_body_lengths=0.05,
        motion_root_refine_step_body_lengths=0.0125,
        motion_root_magnitude_weight=0.01,
        motion_root_velocity_weight=0.02,
        motion_root_acceleration_weight=0.01,
    )
    poses = {
        0: {"__motion_root__": {"forward": 0.0, "lateral": 0.0, "vertical": 0.0}},
        1: {"__motion_root__": {"forward": 0.10, "lateral": 0.0, "vertical": 0.0}},
        2: {"__motion_root__": {"forward": 0.20, "lateral": 0.0, "vertical": 0.0}},
    }
    terms = temporal_terms(poses, [0, 1, 2], ["__motion_root__"], config)
    assert terms["motionRootMagnitude"] > 0.0
    assert terms["motionRootVelocity"] > 0.0
    assert terms["motionRootAcceleration"] == 0.0
    score, details = clip_objective(
        {0: 0.5, 1: 0.5, 2: 0.5},
        poses,
        [0, 1, 2],
        ["__motion_root__"],
        config,
    )
    assert score < 0.5
    assert set(details["penalties"]) >= {
        "motionRootMagnitude",
        "motionRootVelocity",
        "motionRootAcceleration",
    }


def test_disabled_and_inactive_motion_root_axes_are_locked():
    poses = {
        0: {"__motion_root__": {"forward": 0.10, "lateral": 0.20, "vertical": 0.30}},
        1: {"__motion_root__": {"forward": 0.10, "lateral": 0.20, "vertical": 0.30}},
    }
    disabled = TemporalClipConfig(motion_root_enabled=False)
    terms = temporal_terms(poses, [0, 1], ["__motion_root__"], disabled)
    score, details = clip_objective(
        {0: 0.5, 1: 0.5}, poses, [0, 1], ["__motion_root__"], disabled
    )
    assert terms["motionRootMagnitude"] == 0.0
    assert terms["motionRootVelocity"] == 0.0
    assert score == 0.5
    assert all(value == 0.0 for value in details["penalties"].values())

    forward_only = TemporalClipConfig(
        motion_root_enabled=True,
        motion_root_axes=("forward",),
        motion_root_forward_radius_body_lengths=0.20,
    )
    with_inactive = temporal_terms(poses, [0, 1], ["__motion_root__"], forward_only)
    forward_only_poses = {
        frame: {"__motion_root__": {"forward": 0.10, "lateral": 0.0, "vertical": 0.0}}
        for frame in (0, 1)
    }
    without_inactive = temporal_terms(
        forward_only_poses, [0, 1], ["__motion_root__"], forward_only
    )
    assert with_inactive == without_inactive


def test_motion_root_loop_penalty_is_independent_of_generic_loop_switch():
    config = TemporalClipConfig(
        motion_root_enabled=True,
        motion_root_axes=("forward",),
        motion_root_forward_radius_body_lengths=0.20,
        motion_root_loop_weight=0.5,
        loop_enabled=False,
    )
    poses = {
        0: {"__motion_root__": {"forward": 0.0}},
        1: {"__motion_root__": {"forward": 0.10}},
    }
    score, details = clip_objective({0: 0.5, 1: 0.5}, poses, [0, 1], ["__motion_root__"], config)
    assert details["temporal"]["motionRootLoop"] > 0.0
    assert details["penalties"]["motionRootLoop"] > 0.0
    assert score < 0.5


def test_rigid_root_rotation_can_cross_the_upright_local_minimum():
    def score_frame(frame, pose, label, live):
        del frame, label, live
        angle = float(
            pose.get(MOTION_ROOT_ROTATION_KEY, {}).get("camera_forward", 0.0)
        )
        # A lying sprite is represented by a large screen-plane roll. The
        # escape stage must reach it without depending on local bone probes.
        return 1.0 - min(abs(abs(angle) - 90.0), 180.0) / 180.0, {"ok": True}, 0.001

    config = TemporalClipConfig(
        motion_root_enabled=True,
        motion_root_axes=("forward",),
        motion_root_forward_radius_body_lengths=0.05,
        motion_root_coarse_step_body_lengths=0.05,
        motion_root_refine_step_body_lengths=0.0125,
        motion_root_rotation_enabled=True,
        motion_root_rotation_axes=("camera_forward",),
        motion_root_rotation_escape_axes=("camera_forward",),
        motion_root_rotation_escape_angles_deg=(-90.0, 90.0),
        motion_root_rotation_escape_force_image_best=True,
        motion_root_rotation_coarse_step_deg=30.0,
        motion_root_rotation_refine_step_deg=10.0,
        motion_root_rotation_magnitude_weight=0.0,
        motion_root_rotation_velocity_weight=0.0,
        motion_root_rotation_acceleration_weight=0.0,
        probe_enabled=False,
        adaptive_blocks_enabled=False,
        polish_enabled=False,
        rounds=1,
        refine_rounds=1,
        axes=("x",),
    )
    result = optimize_clip(
        [0],
        [],
        {0: {}},
        score_frame,
        lambda _bone: (-90.0, 90.0),
        config,
        live_preview=False,
    )
    chosen = float(
        result["poses"][0][MOTION_ROOT_ROTATION_KEY]["camera_forward"]
    )
    assert abs(abs(chosen) - 90.0) < 1e-6
    escape = next(
        row
        for row in result["history"]
        if row["kind"] == "clip_motion_root_rigid_escape"
    )
    assert escape["frames"][0]["chosen"] is not None
    assert any(
        row["kind"] == "clip_motion_root_rigid_escape"
        for row in result["history"]
    )
    assert not any(
        row["kind"] == "clip_motion_root_rotation_escape"
        for row in result["history"]
    )


def test_rigid_root_couples_translation_and_attitude_before_clip_search():
    def score_frame(frame, pose, label, live):
        del frame, label, live
        translation = float(pose.get(MOTION_ROOT_KEY, {}).get("forward", 0.0))
        rotation = float(
            pose.get(MOTION_ROOT_ROTATION_KEY, {}).get("camera_forward", 0.0)
        )
        return (
            1.0
            - abs(translation - 0.10) * 2.0
            - abs(abs(rotation) - 90.0) / 180.0,
            {"ok": True},
            0.001,
        )

    config = TemporalClipConfig(
        motion_root_enabled=True,
        motion_root_axes=("forward",),
        motion_root_forward_radius_body_lengths=0.10,
        motion_root_coarse_step_body_lengths=0.05,
        motion_root_refine_step_body_lengths=0.0125,
        motion_root_rotation_enabled=True,
        motion_root_rotation_axes=("camera_forward",),
        motion_root_rotation_escape_axes=("camera_forward",),
        motion_root_rotation_escape_angles_deg=(-90.0, 90.0),
        motion_root_rotation_escape_force_image_best=True,
        motion_root_rotation_escape_relax_enabled=False,
        motion_root_rotation_magnitude_weight=0.0,
        motion_root_rotation_velocity_weight=0.0,
        motion_root_rotation_acceleration_weight=0.0,
        motion_root_coupled_blocks_enabled=True,
        motion_root_rotation_coupled_blocks_enabled=True,
        probe_enabled=False,
        adaptive_blocks_enabled=False,
        polish_enabled=False,
        rounds=1,
        refine_rounds=1,
        axes=("x",),
    )
    result = optimize_clip(
        [0],
        [],
        {0: {}},
        score_frame,
        lambda _bone: (-90.0, 90.0),
        config,
        live_preview=False,
    )
    pose = result["poses"][0]
    assert abs(float(pose[MOTION_ROOT_KEY]["forward"]) - 0.10) < 1e-6
    assert abs(abs(float(pose[MOTION_ROOT_ROTATION_KEY]["camera_forward"])) - 90.0) < 1e-6
    rigid_escape = next(
        row
        for row in result["history"]
        if row["kind"] == "clip_motion_root_rigid_escape"
    )
    assert rigid_escape["frames"][0]["coupledCandidates"] > 1
    assert rigid_escape["frames"][0]["chosen"] is not None


def test_rigid_root_rotation_has_independent_temporal_terms():
    config = TemporalClipConfig(
        motion_root_rotation_enabled=True,
        motion_root_rotation_axes=("camera_forward",),
        motion_root_rotation_limit_deg=180.0,
        motion_root_rotation_velocity_weight=0.25,
        motion_root_rotation_acceleration_weight=0.15,
        motion_root_rotation_magnitude_weight=0.05,
    )
    poses = {
        0: {MOTION_ROOT_ROTATION_KEY: {"camera_forward": 0.0}},
        1: {MOTION_ROOT_ROTATION_KEY: {"camera_forward": 90.0}},
        2: {MOTION_ROOT_ROTATION_KEY: {"camera_forward": 180.0}},
    }
    terms = temporal_terms(
        poses,
        [0, 1, 2],
        [MOTION_ROOT_ROTATION_KEY],
        config,
    )
    assert terms["motionRootRotationMagnitude"] > 0.0
    assert terms["motionRootRotationVelocity"] > 0.0
    assert terms["motionRootRotationAcceleration"] == 0.0
    score, details = clip_objective(
        {0: 0.5, 1: 0.5, 2: 0.5},
        poses,
        [0, 1, 2],
        [MOTION_ROOT_ROTATION_KEY],
        config,
    )
    assert score < 0.5
    assert details["penalties"]["motionRootRotationVelocity"] > 0.0


def test_rigid_root_escape_relaxes_ordered_major_bones_before_accepting():
    def score_frame(frame, pose, label, live):
        del frame, label, live
        root = float(
            pose.get(MOTION_ROOT_ROTATION_KEY, {}).get("camera_forward", 0.0)
        )
        local = float(pose.get("major", {}).get("x", 0.0)) * 180.0 / 3.141592653589793
        return (
            1.0
            - 0.003 * abs(abs(root) - 90.0)
            - 0.01 * abs(local - 12.0),
            {"ok": True},
            0.001,
        )

    config = TemporalClipConfig(
        motion_root_rotation_enabled=True,
        motion_root_rotation_axes=("camera_forward",),
        motion_root_rotation_escape_axes=("camera_forward",),
        motion_root_rotation_escape_angles_deg=(-90.0, 90.0),
        motion_root_rotation_escape_top_k=2,
        motion_root_rotation_escape_relax_enabled=True,
        motion_root_rotation_escape_relax_bone_count=1,
        motion_root_rotation_escape_relax_rounds=1,
        motion_root_rotation_escape_relax_step_deg=12.0,
        motion_root_rotation_escape_relax_refine_step_deg=4.0,
        motion_root_rotation_magnitude_weight=0.0,
        motion_root_rotation_velocity_weight=0.0,
        motion_root_rotation_acceleration_weight=0.0,
        probe_enabled=False,
        adaptive_blocks_enabled=False,
        polish_enabled=False,
        rounds=1,
        refine_rounds=1,
        axes=("x",),
    )
    result = optimize_clip(
        [0],
        ["major"],
        {0: {}},
        score_frame,
        lambda _bone: (-90.0, 90.0),
        config,
        live_preview=False,
    )
    pose = result["poses"][0]
    assert abs(abs(float(pose[MOTION_ROOT_ROTATION_KEY]["camera_forward"])) - 90.0) < 1e-6
    assert abs(float(pose["major"]["x"]) - (12.0 * 3.141592653589793 / 180.0)) < 1e-6
    escape = next(
        row
        for row in result["history"]
        if row["kind"] == "clip_motion_root_rotation_escape"
    )
    assert escape["frames"][0]["chosen"]["relaxTrials"] > 0


def test_batch_scoring_receives_required_image_scores_and_scalar_incumbent():
    captured = []

    def score_frame(frame, pose, label, live):
        del frame, pose, label, live
        return 0.5, {"ok": True}, 0.001

    def score_frame_batch(
        frame,
        entries,
        incumbent_score=None,
        required_image_scores=None,
    ):
        captured.append((incumbent_score, required_image_scores, len(entries)))
        return [score_frame(frame, pose, label, live) for pose, label, live in entries]

    config = TemporalClipConfig(
        rounds=1,
        refine_rounds=1,
        candidate_mode="local",
        max_evaluations_per_axis=2,
        batch_candidates=True,
        probe_enabled=False,
        adaptive_blocks_enabled=False,
        polish_enabled=False,
        axes=("x",),
    )
    optimize_clip(
        [0, 1],
        ["bone"],
        {0: {}, 1: {}},
        score_frame,
        lambda _bone: (-90.0, 90.0),
        config,
        score_frame_batch=score_frame_batch,
        live_preview=False,
    )
    assert captured
    assert any(item[0] is not None for item in captured)
    assert any(
        isinstance(item[1], list) and len(item[1]) == item[2]
        for item in captured
    )
    assert all(
        all(isinstance(value, float) for value in item[1])
        for item in captured
        if item[1] is not None
    )


def test_rotation_vector_fallback_limits_legacy_probe_to_rescue_bones():
    def score_frame(frame, pose, label, live):
        del frame, pose, live
        if "clip vector" in label and "alpha" in label:
            return 0.95, {"ok": True}, 0.001
        if "clip vector" in label and "beta" in label:
            return 0.05, {"ok": True}, 0.001
        if "clip probe" in label and "beta" in label:
            return 0.90, {"ok": True}, 0.001
        return 0.10, {"ok": True}, 0.001

    config = TemporalClipConfig(
        rotation_vector_search_enabled=True,
        rotation_vector_probe_count=4,
        rotation_vector_probe_step_deg=16.0,
        rotation_vector_legacy_euler_fallback_enabled=True,
        rotation_vector_informative_min_improvement=0.10,
        probe_enabled=True,
        probe_min_improvement=-1.0,
        adaptive_blocks_enabled=False,
        polish_enabled=False,
        rounds=1,
        refine_rounds=1,
        axes=("x", "y", "z"),
        bone_vectors={
            "alpha": (1.0, 0.0, 0.0),
            "beta": (0.0, 1.0, 0.0),
        },
    )
    result = optimize_clip(
        [0],
        ["alpha", "beta"],
        {0: {}},
        score_frame,
        lambda _bone: (-90.0, 90.0),
        config,
        live_preview=False,
    )
    vector_history = next(
        row for row in result["history"] if row["kind"] == "clip_rotation_vector_probe"
    )
    assert vector_history["informativeBones"] == ["alpha"]
    assert vector_history["legacyEulerRescueBones"] == ["beta"]
    probe_history = next(
        row for row in result["history"] if row["kind"] == "clip_batch_probe"
    )
    assert {row["bone"] for row in probe_history["rows"]} == {"beta"}


def test_adaptive_blocks_use_learned_rotation_vectors_with_euler_fallback():
    def score_frame(frame, pose, label, live):
        del frame, pose, live
        if "clip vector" in label and "alpha" in label:
            return 0.95, {"ok": True}, 0.001
        if "clip vector" in label and "beta" in label:
            return 0.05, {"ok": True}, 0.001
        if "clip probe" in label and "beta" in label:
            return 0.90, {"ok": True}, 0.001
        if "clip block" in label and "learned" in label and "alpha" in label:
            return 0.97, {"ok": True}, 0.001
        if "clip block" in label and "beta" in label and "legacy" in label:
            return 0.80, {"ok": True}, 0.001
        return 0.10, {"ok": True}, 0.001

    config = TemporalClipConfig(
        rotation_vector_search_enabled=True,
        rotation_vector_probe_count=4,
        rotation_vector_probe_step_deg=16.0,
        rotation_vector_legacy_euler_fallback_enabled=True,
        rotation_vector_informative_min_improvement=0.10,
        probe_enabled=True,
        adaptive_blocks_enabled=True,
        adaptive_block_learned_directions_enabled=True,
        adaptive_block_size=2,
        adaptive_rounds=1,
        adaptive_step_deg=10.0,
        adaptive_beam_width=2,
        adaptive_groups=(("alpha", "beta"),),
        polish_enabled=False,
        rounds=1,
        refine_rounds=1,
        axes=("x", "y", "z"),
        bone_vectors={
            "alpha": (1.0, 0.0, 0.0),
            "beta": (0.0, 1.0, 0.0),
        },
    )
    result = optimize_clip(
        [0],
        ["alpha", "beta"],
        {0: {}},
        score_frame,
        lambda _bone: (-90.0, 90.0),
        config,
        live_preview=False,
    )
    block_history = next(
        row for row in result["history"] if row["kind"] == "clip_adaptive_block"
    )
    assert "alpha" in block_history["learnedDirectionalBones"]
    assert "beta" in block_history["legacyEulerBones"]
    assert any(
        row["proposalMode"] == "learned_vector" and row["bone"] == "alpha"
        for row in block_history["trials"]
    )
    assert any(
        row["proposalMode"] == "legacy_euler" and row["bone"] == "beta"
        for row in block_history["trials"]
    )
