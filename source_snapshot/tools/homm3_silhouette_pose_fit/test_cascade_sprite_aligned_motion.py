"""Keep-or-zero occupancy-motion finish pass: no damping, no GPU."""
from __future__ import annotations

import inspect
import math

import torch

from cascade_sprite_aligned_motion import (
    SPRITE_ALIGNED_KEEP_MIN_IMPROVEMENT,
    SPRITE_ALIGNED_MIN_TRAVEL_RAD,
    affected_pair_quality_indices,
    hold_raw_bone_at_frame,
    hold_raw_vector_at_frame,
    pair_qualities_for_frame,
    should_keep_local_pairs,
    should_keep_travel,
    traveling_frame_indices,
)
from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
from roc_gpu_cascade_experiment import GpuCascadeConfig
from run_chain_space_surface_compare import (
    DEFAULT_OUT,
    MATCHED_OUT,
    SHARED_EXPERIMENT,
    _control_search_eval_budget,
    _finish_knobs_match,
)


def run() -> dict[str, object]:
    assert should_keep_travel(0.50, 0.40, min_improvement=1e-6) is True
    assert should_keep_travel(0.40, 0.50, min_improvement=1e-6) is False
    assert should_keep_travel(0.50, 0.50, min_improvement=1e-6) is False
    assert should_keep_travel(0.50, 0.50, min_improvement=0.0) is False
    assert should_keep_travel(0.500002, 0.50, min_improvement=1e-6) is True
    try:
        should_keep_travel(float("nan"), 0.50, min_improvement=1e-6)
        raise AssertionError("non-finite motion mean must fail closed")
    except ValueError as exc:
        assert "finite" in str(exc)
    try:
        should_keep_travel(0.50, 0.40, min_improvement=-1e-6)
        raise AssertionError("negative min_improvement must fail closed")
    except ValueError as exc:
        assert "min_improvement" in str(exc)

    assert affected_pair_quality_indices(1, 4) == (1, 2)
    assert affected_pair_quality_indices(3, 4) == (3,)
    try:
        affected_pair_quality_indices(0, 4)
        raise AssertionError("frame 0 has no hold pairs")
    except ValueError as exc:
        assert "at least 1" in str(exc)
    # Frame 0 duplicates pair 0 on motionQuality. Holding frame 1 must
    # not count that copy as a third pair.
    row = (0.125, 0.25, 0.375, 0.5)
    assert pair_qualities_for_frame(row, 1) == (0.25, 0.375)
    assert pair_qualities_for_frame(row, 3) == (0.5,)
    tensor_row = torch.tensor(row, dtype=torch.float32)
    assert pair_qualities_for_frame(tensor_row, 1) == (0.25, 0.375)

    extra = SPRITE_ALIGNED_KEEP_MIN_IMPROVEMENT
    assert extra == 0.01
    # One-pixel / clip-mean 1e-6 noise must not keep a swing.
    assert should_keep_local_pairs((0.50003,), (0.50,), min_improvement=extra) is False
    assert should_keep_local_pairs((0.50, 0.50), (0.50, 0.50), min_improvement=extra) is False
    assert should_keep_local_pairs((0.62, 0.58), (0.40, 0.41), min_improvement=extra) is True
    # Compensating pop: mean can rise while one pair gets worse.
    assert should_keep_local_pairs((0.70, 0.40), (0.50, 0.45), min_improvement=extra) is False
    try:
        should_keep_local_pairs((0.62,), (0.40, 0.41), min_improvement=extra)
        raise AssertionError("pair length mismatch must fail closed")
    except ValueError as exc:
        assert "length" in str(exc)

    series = torch.zeros((4, 3), dtype=torch.float32)
    series[2, 0] = 0.4
    series[3, 0] = 0.4
    moved = traveling_frame_indices(series, min_travel=SPRITE_ALIGNED_MIN_TRAVEL_RAD)
    assert moved == (2,), moved
    still = traveling_frame_indices(torch.zeros((4, 3)), min_travel=SPRITE_ALIGNED_MIN_TRAVEL_RAD)
    assert still == ()

    limit = math.radians(150.0)
    scales = torch.ones(2, dtype=torch.float32)
    raw = torch.zeros((4, 2, 3), dtype=torch.float32)
    raw[2, 1, 0] = math.atanh(math.radians(40.0) / limit)
    raw[3, 1, 0] = math.atanh(math.radians(-20.0) / limit)
    held = hold_raw_bone_at_frame(
        raw,
        bone_index=1,
        frame=2,
        joint_limit_rad=limit,
        bone_limit_scales=scales,
    )
    bounded_held = torch.tanh(held) * limit
    bounded_raw = torch.tanh(raw) * limit
    assert abs(float(bounded_held[2, 1, 0].item())) < 1e-5
    assert abs(float(bounded_held[3, 1, 0].item()) - math.radians(-20.0)) < 1e-5
    assert torch.allclose(bounded_held[:, 0, :], bounded_raw[:, 0, :])
    assert torch.allclose(bounded_held[0], bounded_raw[0])
    assert torch.allclose(bounded_held[1], bounded_raw[1])
    try:
        hold_raw_bone_at_frame(
            raw,
            bone_index=1,
            frame=0,
            joint_limit_rad=limit,
            bone_limit_scales=scales,
        )
        raise AssertionError("holding frame 0 must fail closed")
    except ValueError as exc:
        assert "at least 1" in str(exc)

    root = torch.zeros((3, 3), dtype=torch.float32)
    root[1] = torch.tensor([0.2, -0.1, 0.05])
    root[2] = torch.tensor([0.4, 0.0, 0.0])
    held_root = hold_raw_vector_at_frame(root, frame=1)
    assert torch.allclose(held_root[1], held_root[0])
    assert torch.allclose(held_root[2], root[2])

    default = GpuCascadeConfig()
    assert bool(default.sprite_aligned_motion_keep_enabled) is False
    assert abs(float(default.sprite_aligned_motion_keep_min_improvement) - extra) <= 1e-12
    assert bool(default.physics_smooth_enabled) is True
    GpuCascadeConfig(
        sprite_aligned_motion_keep_enabled=True,
        physics_smooth_enabled=False,
        motion_weight=1.0,
        silhouette_weight=0.0,
        depth_weight=0.0,
        chroma_weight=0.0,
    ).validate()
    try:
        GpuCascadeConfig(
            sprite_aligned_motion_keep_enabled=True,
            physics_smooth_enabled=True,
            motion_weight=1.0,
        ).validate()
        raise AssertionError("sprite-aligned keep cannot mix physics damping")
    except ValueError as exc:
        assert "sprite_aligned_motion_keep_enabled" in str(exc)
        assert "physics_smooth" in str(exc)
    try:
        GpuCascadeConfig(
            sprite_aligned_motion_keep_enabled=True,
            physics_smooth_enabled=False,
            motion_weight=0.0,
        ).validate()
        raise AssertionError("sprite-aligned keep requires occupancy motion")
    except ValueError as exc:
        assert "motion_weight" in str(exc)
    try:
        GpuCascadeConfig(
            sprite_aligned_motion_keep_enabled=True,
            physics_smooth_enabled=False,
            motion_weight=1.0,
            score_mode="dinov3_dense",
            depth_weight=0.0,
            silhouette_weight=0.0,
            chroma_weight=0.0,
            collision_enabled=False,
            collision_weight=0.0,
            joint_unique_gain_weight=0.0,
            fine_unique_gain_weight=0.0,
            root_iterations=0,
        ).validate()
        raise AssertionError("sprite-aligned keep cannot mix dinov3_dense")
    except ValueError as exc:
        assert "sprite_aligned_motion_keep_enabled" in str(exc)

    from pathlib import Path as _Path

    cascade_text = _Path(__file__).with_name("roc_gpu_cascade_experiment.py").read_text(
        encoding="utf-8"
    )
    optimize_body = cascade_text[
        cascade_text.index("def optimize_clip(") : cascade_text.index(
            "def initialize_gpu_cascade("
        )
    ]
    assert optimize_body.index("_apply_sprite_aligned_motion_keep(") < optimize_body.index(
        "_apply_cascade_physics_smooth("
    )

    apply_body = cascade_text[
        cascade_text.index("def _apply_sprite_aligned_motion_keep(") : cascade_text.index(
            "def _skinned_vertices("
        )
    ]
    assert "should_keep_local_pairs(" in apply_body
    assert "pair_qualities_for_frame(" in apply_body
    assert "_clip_mean_motion(" not in apply_body
    assert "should_keep_travel(" not in apply_body

    signature = inspect.signature(run_gpu_depth_fit_from_hybrid_config)
    for name in (
        "sprite_aligned_motion_keep_enabled",
        "sprite_aligned_motion_keep_min_improvement",
    ):
        assert name in signature.parameters, name
    assert (
        abs(
            float(signature.parameters["sprite_aligned_motion_keep_min_improvement"].default)
            - extra
        )
        <= 1e-12
    )

    assert "tight" in DEFAULT_OUT.name
    assert "tight" in MATCHED_OUT.name
    assert SHARED_EXPERIMENT["joint_temporal_consensus_enabled"] is True
    assert SHARED_EXPERIMENT["physics_smooth_enabled"] is False
    assert SHARED_EXPERIMENT["sprite_aligned_motion_keep_enabled"] is True
    assert (
        abs(
            float(SHARED_EXPERIMENT["sprite_aligned_motion_keep_min_improvement"]) - extra
        )
        <= 1e-12
    )
    finish_ok = {
        "joint_temporal_consensus_enabled": True,
        "physics_smooth_enabled": False,
        "sprite_aligned_motion_keep_enabled": True,
        "sprite_aligned_motion_keep_min_improvement": extra,
    }
    assert _finish_knobs_match(finish_ok) is True
    assert _finish_knobs_match({**finish_ok, "sprite_aligned_motion_keep_min_improvement": 1e-6}) is False
    assert _finish_knobs_match({**finish_ok, "physics_smooth_enabled": True}) is False
    search_budget = _control_search_eval_budget(
        {
            "evaluationCount": 967,
            "spriteAlignedMotionKeep": {"enabled": True, "evaluations": 307},
        }
    )
    assert search_budget == 660, search_budget
    try:
        _control_search_eval_budget({"evaluationCount": 100})
        raise AssertionError("missing keep report must fail closed")
    except RuntimeError as exc:
        assert "spriteAlignedMotionKeep" in str(exc)
    return {"ok": True}


if __name__ == "__main__":
    print(run())
