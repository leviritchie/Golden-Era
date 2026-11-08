"""Gradient ladder: coupled direction, bounded offsets, and fail-closed knobs.

The ladder stage takes one backward pass on absolute sprite match to get a
coupled all-bone direction, then scores discrete magnitudes along that
direction with the exact raster. These tests pin the direction construction
(masking, per-frame normalization, gradient floor), the bounded-space offset
(round-trip, clamping, shape checks), and the config/adapter plumbing.
"""

from __future__ import annotations

import inspect
import math

from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
from roc_gpu_cascade_experiment import (
    GpuCascadeConfig,
    commit_pose_parameter_,
    gradient_ladder_directions,
    offset_raw_bounded_direction,
)


def run() -> dict[str, object]:
    import torch

    # Default is off; enabling requires sane knobs.
    config = GpuCascadeConfig()
    assert bool(config.gradient_ladder_enabled) is False
    assert int(config.gradient_ladder_iterations) == 1
    assert tuple(config.gradient_ladder_step_degs) == (2.5, 5.0, 10.0)
    assert float(config.gradient_ladder_min_gradient_norm) > 0.0
    GpuCascadeConfig(
        gradient_ladder_enabled=True,
        gradient_ladder_iterations=2,
        gradient_ladder_step_degs=(5.0,),
        gradient_ladder_min_gradient_norm=1e-5,
    ).validate()
    try:
        GpuCascadeConfig(
            gradient_ladder_enabled=True, gradient_ladder_iterations=0
        ).validate()
        raise AssertionError("enabled ladder with zero iterations must fail closed")
    except ValueError as exc:
        assert "iterations" in str(exc)
    try:
        GpuCascadeConfig(
            gradient_ladder_enabled=True, gradient_ladder_step_degs=()
        ).validate()
        raise AssertionError("empty ladder steps must fail closed")
    except ValueError as exc:
        assert "step_degs" in str(exc)
    try:
        GpuCascadeConfig(
            gradient_ladder_enabled=True, gradient_ladder_step_degs=(5.0, 0.0)
        ).validate()
        raise AssertionError("non-positive ladder step must fail closed")
    except ValueError as exc:
        assert "step_degs" in str(exc)
    try:
        GpuCascadeConfig(
            gradient_ladder_enabled=True, gradient_ladder_min_gradient_norm=0.0
        ).validate()
        raise AssertionError("zero gradient floor must fail closed")
    except ValueError as exc:
        assert "min_gradient_norm" in str(exc)

    signature = inspect.signature(run_gpu_depth_fit_from_hybrid_config)
    for name in (
        "gradient_ladder_enabled",
        "gradient_ladder_iterations",
        "gradient_ladder_step_degs",
        "gradient_ladder_min_gradient_norm",
    ):
        assert name in signature.parameters, name

    # Direction construction: masked to search bones, unit norm per frame,
    # flat frames zeroed.
    grad = torch.zeros((3, 4, 3), dtype=torch.float32)
    grad[0, 1, 0] = 3.0
    grad[0, 2, 1] = 4.0  # 3-4-5 norm on frame 0
    grad[1, 1, 0] = 1e-8  # below the floor
    grad[2, 0, 2] = 2.0  # bone 0 is not in the search set
    directions, norms = gradient_ladder_directions(
        grad,
        [1, 2],
        min_gradient_norm=1e-6,
    )
    assert abs(float(norms[0].item()) - 5.0) < 1e-5
    assert abs(float(directions[0, 1, 0].item()) - 0.6) < 1e-6
    assert abs(float(directions[0, 2, 1].item()) - 0.8) < 1e-6
    assert float(directions[1].abs().max().item()) == 0.0  # flat frame zeroed
    assert float(directions[2].abs().max().item()) == 0.0  # bone 0 masked out
    assert float(directions[0, 0].abs().max().item()) == 0.0
    try:
        gradient_ladder_directions(grad, [], min_gradient_norm=1e-6)
        raise AssertionError("empty bone list must fail closed")
    except ValueError as exc:
        assert "at least one bone" in str(exc)

    # Bounded offset: zero delta round-trips; a known delta lands exactly.
    limit = math.radians(150.0)
    scales = torch.ones(4, dtype=torch.float32)
    raw = torch.zeros((2, 4, 3), dtype=torch.float32)
    deltas = torch.zeros((2, 4, 3), dtype=torch.float32)
    same = offset_raw_bounded_direction(
        raw,
        deltas,
        joint_limit_rad=limit,
        bone_limit_scales=scales,
    )
    assert torch.allclose(
        torch.tanh(same) * limit, torch.zeros((2, 4, 3)), atol=1e-6
    )
    deltas[0, 1, 0] = math.radians(10.0)
    moved = offset_raw_bounded_direction(
        raw,
        deltas,
        joint_limit_rad=limit,
        bone_limit_scales=scales,
    )
    moved_bounded = torch.tanh(moved) * limit
    assert abs(float(moved_bounded[0, 1, 0].item()) - math.radians(10.0)) < 1e-5
    assert float(moved_bounded[1].abs().max().item()) < 1e-6
    # A huge delta clamps at the joint limit instead of wrapping.
    deltas.zero_()
    deltas[:, :, 0] = math.radians(720.0)
    clamped = offset_raw_bounded_direction(
        raw,
        deltas,
        joint_limit_rad=limit,
        bone_limit_scales=scales,
    )
    clamped_bounded = torch.tanh(clamped) * limit
    assert float(clamped_bounded[..., 0].max().item()) <= limit + 1e-5
    # Shape mismatch fails closed.
    try:
        offset_raw_bounded_direction(
            raw,
            torch.zeros((2, 4, 2)),
            joint_limit_rad=limit,
            bone_limit_scales=scales,
        )
        raise AssertionError("mismatched delta shape must fail closed")
    except ValueError as exc:
        assert "shape" in str(exc)

    # Pose tensors are Parameters. copy_ while autograd is on is the
    # "leaf Variable that requires grad is being used in an in-place
    # operation" crash; the ladder helper must survive that default.
    parameter = torch.nn.Parameter(torch.zeros((2, 4, 3), dtype=torch.float32))
    winner = torch.ones((2, 4, 3), dtype=torch.float32)
    assert bool(torch.is_grad_enabled())
    try:
        parameter.copy_(winner)
        raise AssertionError("raw Parameter.copy_ must raise while autograd is on")
    except RuntimeError as exc:
        assert "in-place" in str(exc).lower() or "leaf" in str(exc).lower()
    commit_pose_parameter_(parameter, winner)
    assert torch.allclose(parameter, winner)
    try:
        commit_pose_parameter_(parameter, torch.zeros((2, 4, 2)))
        raise AssertionError("mismatched pose write shape must fail closed")
    except ValueError as exc:
        assert "shape" in str(exc)

    return {
        "ok": True,
        "frame0Norm": float(norms[0].item()),
        "flatFrameZeroed": bool(float(directions[1].abs().max().item()) == 0.0),
        "maskedBoneZeroed": bool(float(directions[0, 0].abs().max().item()) == 0.0),
        "parameterWriteSurvivedAutograd": True,
    }


if __name__ == "__main__":
    print(run())
