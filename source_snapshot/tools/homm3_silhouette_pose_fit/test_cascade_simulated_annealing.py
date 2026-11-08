"""Simulated annealing: cooling schedule, random pose, perturbation, Metropolis.

The SA stage finds broad-strokes pose basins through random exploration with
temperature-scaled perturbation and Metropolis acceptance. These tests pin
the cooling schedule (monotonic decrease, correct endpoints), the random
initial pose (limits respected, only search bones non-zero, reproducibility),
the perturbation (limits respected, zero temperature produces near-zero
perturbation), the Metropolis criterion (always accepts improvement, never
accepts worsening at T→0), and the config/adapter plumbing.
"""

from __future__ import annotations

import inspect
import math

from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
from roc_gpu_cascade_experiment import (
    GpuCascadeConfig,
    sa_metropolis_accept,
    sa_perturb_pose,
    sa_random_initial_pose,
    sa_temperature,
)


def run() -> dict[str, object]:
    import torch

    # --- Config validation: fail-closed for invalid SA params ---
    config = GpuCascadeConfig()
    assert bool(config.sa_enabled) is False
    assert int(config.sa_restarts) == 4
    assert int(config.sa_iterations) == 200
    assert float(config.sa_initial_temperature) > 0.0
    assert float(config.sa_final_temperature) > 0.0
    assert float(config.sa_final_temperature) < float(config.sa_initial_temperature)
    assert float(config.sa_perturbation_scale_deg) > 0.0
    assert 0.0 < float(config.sa_bone_fraction) <= 1.0
    assert config.sa_seed is None
    assert bool(config.sa_seed_from_current) is True
    assert int(config.sa_min_bone_depth) == 3
    assert float(config.sa_collision_weight) == 0.0

    GpuCascadeConfig(
        sa_enabled=True,
        sa_restarts=2,
        sa_iterations=100,
        sa_initial_temperature=0.05,
        sa_final_temperature=0.005,
        sa_perturbation_scale_deg=30.0,
        sa_bone_fraction=0.3,
        sa_seed=42,
        sa_seed_from_current=False,
        sa_min_bone_depth=2,
        sa_collision_weight=None,
    ).validate()

    try:
        GpuCascadeConfig(sa_enabled=True, sa_restarts=0).validate()
        raise AssertionError("zero restarts must fail closed")
    except ValueError as exc:
        assert "restarts" in str(exc)

    try:
        GpuCascadeConfig(sa_enabled=True, sa_iterations=0).validate()
        raise AssertionError("zero iterations must fail closed")
    except ValueError as exc:
        assert "iterations" in str(exc)

    try:
        GpuCascadeConfig(sa_enabled=True, sa_initial_temperature=0.0).validate()
        raise AssertionError("zero initial temperature must fail closed")
    except ValueError as exc:
        assert "initial_temperature" in str(exc)

    try:
        GpuCascadeConfig(sa_enabled=True, sa_final_temperature=0.0).validate()
        raise AssertionError("zero final temperature must fail closed")
    except ValueError as exc:
        assert "final_temperature" in str(exc)

    try:
        GpuCascadeConfig(
            sa_enabled=True,
            sa_initial_temperature=0.001,
            sa_final_temperature=0.1,
        ).validate()
        raise AssertionError("inverted temperature range must fail closed")
    except ValueError as exc:
        assert "less than" in str(exc)

    try:
        GpuCascadeConfig(sa_enabled=True, sa_perturbation_scale_deg=0.0).validate()
        raise AssertionError("zero perturbation scale must fail closed")
    except ValueError as exc:
        assert "perturbation_scale_deg" in str(exc)

    try:
        GpuCascadeConfig(sa_enabled=True, sa_bone_fraction=0.0).validate()
        raise AssertionError("zero bone fraction must fail closed")
    except ValueError as exc:
        assert "bone_fraction" in str(exc)

    try:
        GpuCascadeConfig(sa_enabled=True, sa_bone_fraction=1.5).validate()
        raise AssertionError("bone fraction > 1 must fail closed")
    except ValueError as exc:
        assert "bone_fraction" in str(exc)

    # --- Adapter plumbing ---
    signature = inspect.signature(run_gpu_depth_fit_from_hybrid_config)
    for name in (
        "sa_enabled",
        "sa_restarts",
        "sa_iterations",
        "sa_initial_temperature",
        "sa_final_temperature",
        "sa_perturbation_scale_deg",
        "sa_bone_fraction",
        "sa_seed",
        "sa_seed_from_current",
        "sa_min_bone_depth",
        "sa_collision_weight",
        "physics_smooth_enabled",
        "physics_smooth_gravity_weight",
        "sprite_aligned_motion_keep_enabled",
        "sprite_aligned_motion_keep_min_improvement",
    ):
        assert name in signature.parameters, name

    # --- sa_temperature: monotonic decrease, correct endpoints ---
    t_start, t_end = 0.1, 0.001
    temps = [sa_temperature(i, 100, t_start, t_end) for i in range(100)]
    assert abs(temps[0] - t_start) < 1e-9
    assert abs(temps[-1] - t_end) < 1e-6
    for i in range(1, len(temps)):
        assert temps[i] < temps[i - 1], f"not monotonic at {i}"

    # Single iteration returns t_start.
    assert abs(sa_temperature(0, 1, t_start, t_end) - t_start) < 1e-9

    try:
        sa_temperature(0, 0, t_start, t_end)
        raise AssertionError("zero total_iterations must fail closed")
    except ValueError as exc:
        assert "total_iterations" in str(exc)

    try:
        sa_temperature(0, 100, 0.0, t_end)
        raise AssertionError("zero t_start must fail closed")
    except ValueError as exc:
        assert "t_start" in str(exc)

    try:
        sa_temperature(0, 100, t_start, t_start)
        raise AssertionError("t_end >= t_start must fail closed")
    except ValueError as exc:
        assert "less than" in str(exc)

    # --- sa_random_initial_pose ---
    device = torch.device("cpu")
    frame_count, node_count = 3, 5
    search_indices = [1, 3]
    joint_limit_rad = math.radians(150.0)
    scales = torch.ones(node_count, dtype=torch.float32)

    gen_a = torch.Generator(device=device)
    gen_a.manual_seed(123)
    pose_a = sa_random_initial_pose(
        frame_count, node_count, search_indices,
        joint_limit_rad, scales, device, gen_a,
    )
    assert pose_a.shape == (frame_count, node_count, 3)

    # Only search bones are non-zero.
    for bone_idx in range(node_count):
        if bone_idx in search_indices:
            assert float(pose_a[:, bone_idx].abs().max().item()) > 0.0, (
                f"search bone {bone_idx} should be non-zero"
            )
        else:
            assert float(pose_a[:, bone_idx].abs().max().item()) == 0.0, (
                f"non-search bone {bone_idx} should be zero"
            )

    # Limits respected: bounded values within ±80% of joint limit.
    bounded = torch.tanh(pose_a) * joint_limit_rad
    max_allowed = joint_limit_rad * 0.8
    assert float(bounded.abs().max().item()) <= max_allowed + 1e-5

    # Reproducibility with same seed.
    gen_b = torch.Generator(device=device)
    gen_b.manual_seed(123)
    pose_b = sa_random_initial_pose(
        frame_count, node_count, search_indices,
        joint_limit_rad, scales, device, gen_b,
    )
    assert torch.allclose(pose_a, pose_b)

    # Different seed gives different pose.
    gen_c = torch.Generator(device=device)
    gen_c.manual_seed(456)
    pose_c = sa_random_initial_pose(
        frame_count, node_count, search_indices,
        joint_limit_rad, scales, device, gen_c,
    )
    assert not torch.allclose(pose_a, pose_c)

    # --- sa_perturb_pose ---
    gen_d = torch.Generator(device=device)
    gen_d.manual_seed(789)
    current = torch.zeros((frame_count, node_count, 3), dtype=torch.float32)
    perturbed = sa_perturb_pose(
        current, 1.0, 0.5, 45.0, search_indices,
        joint_limit_rad, scales, gen_d,
    )
    assert perturbed.shape == current.shape

    # Perturbation respects joint limits.
    bounded_perturbed = torch.tanh(perturbed) * joint_limit_rad
    assert float(bounded_perturbed.abs().max().item()) <= joint_limit_rad + 1e-5

    # Zero temperature produces near-zero perturbation.
    gen_e = torch.Generator(device=device)
    gen_e.manual_seed(789)
    tiny = sa_perturb_pose(
        current, 0.0, 0.5, 45.0, search_indices,
        joint_limit_rad, scales, gen_e,
    )
    bounded_tiny = torch.tanh(tiny) * joint_limit_rad
    assert float(bounded_tiny.abs().max().item()) < 1e-6

    # Non-search bones stay zero.
    for bone_idx in range(node_count):
        if bone_idx not in search_indices:
            assert float(perturbed[:, bone_idx].abs().max().item()) == 0.0

    try:
        sa_perturb_pose(
            current, -0.1, 0.5, 45.0, search_indices,
            joint_limit_rad, scales, gen_d,
        )
        raise AssertionError("negative temperature must fail closed")
    except ValueError as exc:
        assert "normalized_temperature" in str(exc)

    try:
        sa_perturb_pose(
            current, 1.0, 0.0, 45.0, search_indices,
            joint_limit_rad, scales, gen_d,
        )
        raise AssertionError("zero bone_fraction must fail closed")
    except ValueError as exc:
        assert "bone_fraction" in str(exc)

    try:
        sa_perturb_pose(
            current, 1.0, 0.5, 45.0, [],
            joint_limit_rad, scales, gen_d,
        )
        raise AssertionError("empty search list must fail closed")
    except ValueError as exc:
        assert "at least one search bone" in str(exc)

    # --- sa_metropolis_accept ---
    gen_f = torch.Generator(device=device)
    gen_f.manual_seed(42)

    # Always accepts improvement.
    current_scores = torch.tensor([0.5, 0.5, 0.5])
    proposed_scores = torch.tensor([0.6, 0.7, 0.8])
    accept = sa_metropolis_accept(current_scores, proposed_scores, 0.01, gen_f)
    assert bool(accept.all())

    # Never accepts worsening at very low temperature.
    proposed_worse = torch.tensor([0.4, 0.3, 0.2])
    accept_worse = sa_metropolis_accept(current_scores, proposed_worse, 1e-10, gen_f)
    assert not bool(accept_worse.any())

    # At high temperature, some worsening moves are accepted.
    gen_g = torch.Generator(device=device)
    gen_g.manual_seed(42)
    n_trials = 1000
    current_rep = torch.full((n_trials,), 0.5)
    proposed_rep = torch.full((n_trials,), 0.4)  # delta = -0.1
    accept_high = sa_metropolis_accept(current_rep, proposed_rep, 0.5, gen_g)
    # Expected acceptance rate: exp(-0.1 / 0.5) = exp(-0.2) ≈ 0.819
    rate = float(accept_high.float().mean().item())
    assert 0.7 < rate < 0.9, f"acceptance rate {rate} outside expected range"

    try:
        sa_metropolis_accept(current_scores, proposed_scores, 0.0, gen_f)
        raise AssertionError("zero temperature must fail closed")
    except ValueError as exc:
        assert "temperature" in str(exc)

    try:
        sa_metropolis_accept(
            torch.tensor([0.5]),
            torch.tensor([0.6, 0.7]),
            0.01,
            gen_f,
        )
        raise AssertionError("shape mismatch must fail closed")
    except ValueError as exc:
        assert "shape" in str(exc)

    return {
        "ok": True,
        "temperatureMonotonic": True,
        "randomPoseReproducible": True,
        "perturbationRespectsLimits": True,
        "metropolisAlwaysAcceptsImprovement": True,
        "metropolisRejectsWorseningAtLowT": True,
        "metropolisAcceptanceRateAtHighT": round(rate, 3),
    }


if __name__ == "__main__":
    print(run())
