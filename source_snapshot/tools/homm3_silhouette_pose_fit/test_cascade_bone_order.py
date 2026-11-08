"""Named cascade bone-order rankings: one mode is one rule."""
from __future__ import annotations

from cascade_bone_order import (
    CASCADE_BONE_ORDER_MODES,
    area_normalized_scores,
    error_leverage_keys,
    error_leverage_scores,
    is_dynamic_bone_order_mode,
    length_normalized_scores,
    rank_bones_by_keys,
    rank_bones_by_score,
    validate_cascade_bone_order_mode,
)
from cascade_idle_fused_stack import IDLE_FUSED_IMPORTANCE_MODES
from roc_gpu_cascade_experiment import GpuCascadeConfig
from run_roc_idle1_fused_push_080 import PUSH_OVERRIDES


def run() -> dict[str, object]:
    validate_cascade_bone_order_mode("dependency")
    validate_cascade_bone_order_mode("error_leverage")
    try:
        validate_cascade_bone_order_mode("leftover_gravity")
        raise AssertionError("unknown cascade bone order must fail closed")
    except ValueError as exc:
        assert "error_driven" in str(exc)

    GpuCascadeConfig().validate()
    for mode in CASCADE_BONE_ORDER_MODES:
        GpuCascadeConfig(bone_order_mode=mode).validate()
    try:
        GpuCascadeConfig(bone_order_mode="camera_near_to_far").validate()
        raise AssertionError("one_bone leftover/camera modes are not cascade modes")
    except ValueError as exc:
        assert "bone_order_mode must be one of" in str(exc)

    bones = (4, 1, 7)
    original = (1, 4, 7)
    ranked = rank_bones_by_score(bones, {4: 0.2, 1: 0.9, 7: 0.2}, original_order=original)
    assert ranked == (1, 4, 7), ranked

    try:
        rank_bones_by_score(bones, {4: 0.2, 1: 0.9}, original_order=original)
        raise AssertionError("missing scores must fail closed")
    except ValueError as exc:
        assert "missing bones" in str(exc)

    try:
        rank_bones_by_score(bones, {4: 0.2, 1: float("nan"), 7: 0.1}, original_order=original)
        raise AssertionError("non-finite scores must fail closed")
    except ValueError as exc:
        assert "not finite" in str(exc)

    torso_wins_count = area_normalized_scores({0: 100.0, 1: 20.0}, {0: 1000.0, 1: 20.0})
    assert torso_wins_count[1] > torso_wins_count[0]
    zero_area = area_normalized_scores({0: 0.0, 1: 5.0}, {0: 0.0, 1: 5.0})
    assert zero_area[0] == 0.0
    assert zero_area[1] == 1.0

    grad = length_normalized_scores({0: 2.0, 1: 2.0}, {0: 4.0, 1: 1.0})
    assert grad[1] > grad[0]

    keys = error_leverage_keys({0: 0.1, 1: 0.1, 2: 0.4}, {0: 9.0, 1: 1.0, 2: 0.5})
    lex = rank_bones_by_keys((0, 1, 2), keys, original_order=(0, 1, 2))
    assert lex == (2, 0, 1), lex
    product = error_leverage_scores({0: 0.1, 1: 0.1, 2: 0.4}, {0: 9.0, 1: 1.0, 2: 0.5})
    assert product[0] == 0.9
    assert product[2] == 0.2
    hybrid = rank_bones_by_score((0, 1, 2), product, original_order=(0, 1, 2))
    assert hybrid == (0, 2, 1), hybrid
    zero_reach = error_leverage_scores({0: 1.0, 1: 0.2}, {0: 0.0, 1: 4.0})
    assert zero_reach[0] == 0.0
    assert zero_reach[1] == 0.8

    assert is_dynamic_bone_order_mode("error_driven") is True
    assert is_dynamic_bone_order_mode("dependency") is False
    assert "leftover_gravity" not in CASCADE_BONE_ORDER_MODES
    assert "camera_near_to_far" not in CASCADE_BONE_ORDER_MODES

    import inspect
    from roc_gpu_cascade_experiment import GpuCascadeExperiment

    clip_src = inspect.getsource(GpuCascadeExperiment.optimize_clip)
    assert "_rank_joint_bones" in clip_src
    rank_src = inspect.getsource(GpuCascadeExperiment._rank_joint_bones)
    for mode in (
        "error_driven",
        "gradient_magnitude",
        "expected_gain",
        "temporal_disagreement",
        "screen_space_leverage",
        "error_leverage",
    ):
        assert mode in rank_src, mode
    GpuCascadeConfig(
        idle_fused_macro_enabled=True,
        idle_fused_importance_mode="error_leverage",
        score_escape_collision_burst_enabled=True,
    ).validate()
    try:
        GpuCascadeConfig(
            idle_fused_macro_enabled=True,
            idle_fused_importance_mode="expected_gain",
        ).validate()
        raise AssertionError("idle fused must refuse expected_gain importance")
    except ValueError as exc:
        assert "error_leverage" in str(exc)
    assert PUSH_OVERRIDES["bone_order_mode"] == "error_leverage"
    assert PUSH_OVERRIDES["idle_fused_importance_mode"] == "error_leverage"
    assert PUSH_OVERRIDES["articulated_funnel_force_gradient_order"] is False
    assert "error_leverage" in IDLE_FUSED_IMPORTANCE_MODES
    return {
        "ok": True,
        "modes": list(CASCADE_BONE_ORDER_MODES),
        "hybrid": list(hybrid),
    }


if __name__ == "__main__":
    print(run())
