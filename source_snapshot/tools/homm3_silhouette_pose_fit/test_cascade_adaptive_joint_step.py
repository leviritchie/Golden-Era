"""Per-frame joint unit step follows the current keep score."""
from __future__ import annotations

import math

from roc_gpu_cascade_experiment import (
    GpuCascadeConfig,
    JOINT_STEP_SCORE_NORMS,
    joint_unit_step_deg,
    normalize_keep_scores_for_joint_step,
    offset_raw_bone_direction,
)


def run() -> dict[str, object]:
    import torch

    config = GpuCascadeConfig()
    config.validate()
    assert bool(config.joint_adaptive_step_enabled)
    assert float(config.joint_step_score_fine) == 0.80
    assert float(config.joint_step_score_coarse) == 0.45
    assert str(config.joint_step_score_norm) == "logit_minmax"
    assert JOINT_STEP_SCORE_NORMS == ("raw", "clip_minmax", "logit_minmax", "rank", "robust_z")
    fine = float(config.fine_joint_step_deg)
    coarse = float(config.joint_step_deg)
    kwargs = dict(
        coarse_deg=coarse,
        fine_deg=fine,
        coarse_score=0.45,
        fine_score=0.80,
    )
    assert abs(joint_unit_step_deg(0.80, **kwargs) - fine) < 1e-9
    assert abs(joint_unit_step_deg(0.99, **kwargs) - fine) < 1e-9
    assert abs(joint_unit_step_deg(0.45, **kwargs) - coarse) < 1e-9
    assert abs(joint_unit_step_deg(0.10, **kwargs) - coarse) < 1e-9
    mid = joint_unit_step_deg(0.625, **kwargs)
    expected = fine + 0.5 * (coarse - fine)
    assert abs(mid - expected) < 1e-6, (mid, expected)
    idle_after_profile = joint_unit_step_deg(0.7933, **kwargs)
    assert idle_after_profile < 3.0, idle_after_profile
    scores = torch.tensor([0.79, 0.50], dtype=torch.float32)
    steps = joint_unit_step_deg(scores, **kwargs)
    assert float(steps[0].item()) < 3.0
    assert float(steps[1].item()) > 10.0
    try:
        GpuCascadeConfig(joint_step_score_fine=0.2, joint_step_score_coarse=0.4).validate()
        raise AssertionError("fine_score <= coarse_score must fail closed")
    except ValueError as exc:
        assert "joint_step_score_fine" in str(exc)
    try:
        GpuCascadeConfig(joint_step_score_norm="sprite_mad").validate()
        raise AssertionError("unknown joint_step_score_norm must fail closed")
    except ValueError as exc:
        assert "joint_step_score_norm" in str(exc)

    compressed = torch.tensor([0.960, 0.955, 0.948, 0.940], dtype=torch.float32)
    raw = normalize_keep_scores_for_joint_step(compressed, mode="raw")
    assert float((raw - compressed).abs().max().item()) < 1e-7
    raw_steps = joint_unit_step_deg(raw, **kwargs)
    assert float(raw_steps.min().item()) == fine
    stretched = normalize_keep_scores_for_joint_step(compressed, mode="clip_minmax")
    assert abs(float(stretched.min().item()) - 0.0) < 1e-6
    assert abs(float(stretched.max().item()) - 1.0) < 1e-6
    stretched_steps = joint_unit_step_deg(stretched, **kwargs)
    assert float(stretched_steps[-1].item()) == coarse
    assert float(stretched_steps[0].item()) == fine
    logit = normalize_keep_scores_for_joint_step(compressed, mode="logit_minmax")
    assert abs(float(logit.min().item()) - 0.0) < 1e-5
    assert abs(float(logit.max().item()) - 1.0) < 1e-5
    ranked = normalize_keep_scores_for_joint_step(compressed, mode="rank")
    assert abs(float(ranked[0].item()) - 1.0) < 1e-6
    assert abs(float(ranked[-1].item()) - 0.0) < 1e-6
    robust = normalize_keep_scores_for_joint_step(compressed, mode="robust_z")
    assert 0.0 < float(robust.min().item()) < float(robust.max().item()) < 1.0
    flat = torch.full((4,), 0.95, dtype=torch.float32)
    for mode in JOINT_STEP_SCORE_NORMS:
        if mode == "raw":
            continue
        mapped = normalize_keep_scores_for_joint_step(flat, mode=mode)
        assert abs(float(mapped.mean().item()) - 0.5) < 1e-6, (mode, mapped)

    raw = torch.zeros((2, 2, 3), dtype=torch.float32)
    scales = torch.ones(2, dtype=torch.float32)
    moved = offset_raw_bone_direction(
        raw,
        bone_index=0,
        direction=(1.0, 0.0, 0.0),
        delta_rad=torch.tensor([math.radians(2.5), math.radians(15.0)]),
        joint_limit_rad=math.radians(150.0),
        bone_limit_scales=scales,
    )
    idle = float(moved[0, 0, 0].abs().item())
    walk = float(moved[1, 0, 0].abs().item())
    assert walk > idle * 3.0, (idle, walk)
    return {"ok": True}


if __name__ == "__main__":
    print(run())
