"""Sprite-to-sprite change-map keep: excess motion vetoes a probe."""
from __future__ import annotations

import inspect

from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
from roc_gpu_cascade_experiment import (
    SPRITE_CHANGE_VETO_EPS,
    GpuCascadeConfig,
    dinov3_dense_cascade_config,
    excess_predicted_change,
    mask_sprite_change_excess_to_still_frames,
    previous_predicted_for_sprite_change_gate,
    sprite_frame_change_maps,
    veto_scores_on_sprite_change_excess,
)


def test_sprite_change_maps_zero_on_frame_zero() -> None:
    import torch

    rgb = torch.zeros((3, 2, 2, 3), dtype=torch.float32)
    rgb[1, 0, 0] = 1.0
    rgb[2] = rgb[1]
    change = sprite_frame_change_maps(rgb)
    assert tuple(change.shape) == (3, 2, 2)
    assert float(change[0].max().item()) == 0.0
    assert float(change[1, 0, 0].item()) == 1.0
    assert float(change[1, 0, 1].item()) == 0.0
    assert float(change[2].max().item()) == 0.0
    try:
        sprite_frame_change_maps(torch.zeros((2, 2, 3)))
        raise AssertionError("rank-3 RGB must fail closed")
    except ValueError as exc:
        assert "target RGB" in str(exc)


def test_excess_allows_sprite_motion_and_penalizes_more() -> None:
    import torch

    previous = torch.zeros((1, 2, 2, 3), dtype=torch.float32)
    predicted = torch.zeros((1, 2, 2, 3), dtype=torch.float32)
    predicted[0, 0, 0] = 0.4
    sprite = torch.zeros((1, 2, 2), dtype=torch.float32)
    sprite[0, 0, 0] = 0.4
    occupancy = torch.ones((1, 2, 2), dtype=torch.float32)
    allowed = excess_predicted_change(
        predicted, previous, sprite, occupancy, slack=0.0
    )
    assert float(allowed.item()) == 0.0
    predicted_over = predicted.clone()
    predicted_over[0, 0, 0] = 0.7
    extra = excess_predicted_change(
        predicted_over, previous, sprite, occupancy, slack=0.0
    )
    assert abs(float(extra.item()) - 0.075) < 1e-6
    slacked = excess_predicted_change(
        predicted_over, previous, sprite, occupancy, slack=0.3
    )
    assert float(slacked.item()) == 0.0
    background = torch.zeros((1, 2, 2), dtype=torch.float32)
    twitch = predicted_over.clone()
    twitch[0, 1, 1] = 0.5
    hidden = excess_predicted_change(
        twitch, previous, sprite, occupancy, slack=0.0
    )
    assert float(hidden.item()) > 0.0


def test_packed_hyps_use_same_frame_committed_plate() -> None:
    import torch

    committed = torch.zeros((2, 1, 1, 3), dtype=torch.float32)
    committed[0] = 0.1
    committed[1] = 0.2
    predicted = torch.zeros((4, 1, 1, 3), dtype=torch.float32)
    predicted[0] = 0.3
    predicted[1] = 0.4
    predicted[2] = 0.7
    predicted[3] = 0.8
    positions = torch.tensor([0, 1, 0, 1], dtype=torch.long)
    previous = previous_predicted_for_sprite_change_gate(
        predicted, positions, committed
    )
    assert abs(float(previous[0, 0, 0, 0].item()) - 0.1) < 1e-6
    assert abs(float(previous[1, 0, 0, 0].item()) - 0.2) < 1e-6
    assert abs(float(previous[2, 0, 0, 0].item()) - 0.1) < 1e-6
    assert abs(float(previous[3, 0, 0, 0].item()) - 0.2) < 1e-6
    single = torch.zeros((2, 1, 1, 3), dtype=torch.float32)
    single[0] = 0.9
    single[1] = 0.95
    one_frame = previous_predicted_for_sprite_change_gate(
        single,
        torch.tensor([1, 1], dtype=torch.long),
        committed,
    )
    assert abs(float(one_frame[0, 0, 0, 0].item()) - 0.2) < 1e-6
    assert abs(float(one_frame[1, 0, 0, 0].item()) - 0.2) < 1e-6


def test_veto_zeros_excess_and_does_not_mix() -> None:
    import torch

    scores = torch.tensor([0.96, 0.94, 0.50], dtype=torch.float32)
    excess = torch.tensor([0.0, SPRITE_CHANGE_VETO_EPS * 2.0, 0.0], dtype=torch.float32)
    vetoed = veto_scores_on_sprite_change_excess(scores, excess)
    assert abs(float(vetoed[0].item()) - 0.96) < 1e-6
    assert float(vetoed[1].item()) == 0.0
    assert abs(float(vetoed[2].item()) - 0.50) < 1e-6
    assert int(torch.argmax(vetoed).item()) == 0
    mixed = scores - excess
    assert abs(float(mixed[1].item()) - (0.94 - SPRITE_CHANGE_VETO_EPS * 2.0)) < 1e-6
    assert float(vetoed[1].item()) != float(mixed[1].item())
    try:
        veto_scores_on_sprite_change_excess(scores, excess[:2])
        raise AssertionError("mismatched veto shapes must fail closed")
    except ValueError as exc:
        assert "shapes must match" in str(exc)


def test_excess_veto_only_on_still_plates() -> None:
    import torch

    excess = torch.tensor([0.2, 0.3, 0.4, 0.5], dtype=torch.float32)
    still = torch.tensor([False, True, False, True], dtype=torch.bool)
    positions = torch.tensor([0, 1, 2, 3], dtype=torch.long)
    masked = mask_sprite_change_excess_to_still_frames(excess, still, positions)
    assert float(masked[0].item()) == 0.0
    assert abs(float(masked[1].item()) - 0.3) < 1e-6
    assert float(masked[2].item()) == 0.0
    assert abs(float(masked[3].item()) - 0.5) < 1e-6
    packed = torch.tensor([0, 1, 0, 1], dtype=torch.long)
    packed_excess = torch.tensor([0.9, 0.8, 0.7, 0.6], dtype=torch.float32)
    packed_masked = mask_sprite_change_excess_to_still_frames(
        packed_excess, still[:2], packed
    )
    assert float(packed_masked[0].item()) == 0.0
    assert abs(float(packed_masked[1].item()) - 0.8) < 1e-6
    assert float(packed_masked[2].item()) == 0.0
    assert abs(float(packed_masked[3].item()) - 0.6) < 1e-6


def test_gate_config_defaults_and_mutex() -> None:
    default = GpuCascadeConfig()
    assert default.joint_keep_sprite_change_gate is False
    assert float(default.joint_keep_sprite_change_weight) == 1.0
    assert float(default.joint_keep_sprite_change_slack) == 0.0
    dinov3_dense_cascade_config(joint_keep_sprite_change_gate=True).validate()
    try:
        dinov3_dense_cascade_config(
            joint_keep_sprite_change_gate=True,
            joint_keep_still_sprite_lock=True,
        ).validate()
        raise AssertionError("gate plus whole-pose lock must fail closed")
    except ValueError as exc:
        assert "cannot mix" in str(exc)
    try:
        GpuCascadeConfig(joint_keep_sprite_change_gate=True).validate()
        raise AssertionError("geometry without RGB raster must fail closed")
    except ValueError as exc:
        assert "RGB raster" in str(exc)
    try:
        dinov3_dense_cascade_config(
            joint_keep_sprite_change_gate=True,
            joint_keep_sprite_change_weight=0.0,
        ).validate()
        raise AssertionError("zero gate weight must fail closed")
    except ValueError as exc:
        assert "joint_keep_sprite_change_weight" in str(exc)
    try:
        dinov3_dense_cascade_config(
            joint_keep_sprite_change_gate=True,
            joint_keep_sprite_change_slack=-0.1,
        ).validate()
        raise AssertionError("negative slack must fail closed")
    except ValueError as exc:
        assert "joint_keep_sprite_change_slack" in str(exc)

    signature = inspect.signature(run_gpu_depth_fit_from_hybrid_config)
    for name in (
        "joint_keep_sprite_change_gate",
        "joint_keep_sprite_change_weight",
        "joint_keep_sprite_change_slack",
    ):
        assert name in signature.parameters, name
        assert signature.parameters[name].default == getattr(default, name)


def run() -> dict[str, object]:
    test_sprite_change_maps_zero_on_frame_zero()
    test_excess_allows_sprite_motion_and_penalizes_more()
    test_packed_hyps_use_same_frame_committed_plate()
    test_veto_zeros_excess_and_does_not_mix()
    test_excess_veto_only_on_still_plates()
    test_gate_config_defaults_and_mutex()
    return {"ok": True}


if __name__ == "__main__":
    print(run())
