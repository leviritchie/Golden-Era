"""Cascade root search always scores the profile heading (zero extra rotation)."""
from __future__ import annotations

import inspect

from roc_gpu_cascade_experiment import (
    GpuCascadeConfig,
    GpuCascadeExperiment,
    root_hypothesis_unit_offsets,
)
from gpu_depth_silhouette_solver import (
    root_rotation_axis_envelopes_deg,
    root_rotation_axes_for_phase,
    root_rotation_search_bounds,
    root_rotation_search_window_deg,
)


def _assert_raises(message: str, **kwargs) -> None:
    try:
        GpuCascadeConfig(**kwargs).validate()
    except ValueError as exc:
        assert message in str(exc), exc
        return
    raise AssertionError(f"expected fail-closed validate for {kwargs}")


def run() -> dict[str, object]:
    GpuCascadeConfig().validate()
    config = GpuCascadeConfig()
    assert float(config.root_rotation_first_frame_limit_deg) == 30.0
    assert float(config.root_rotation_per_frame_limit_deg) == 30.0
    assert float(config.root_rotation_camera_up_limit_deg) == 45.0
    assert bool(config.root_rotation_defer_camera_up) is True
    assert config._joint_stage_configured() is True

    offsets = root_hypothesis_unit_offsets(32, 6)
    assert tuple(offsets.shape) == (32, 6), offsets.shape
    assert float(offsets[0].abs().max().item()) == 0.0, offsets[0]
    assert float(offsets[1:].abs().max().item()) > 0.0

    first = root_rotation_search_window_deg(
        frame_position=0,
        limit_deg=180.0,
        first_frame_limit_deg=30.0,
        per_frame_limit_deg=30.0,
    )
    assert first == 30.0, first
    envelopes = root_rotation_axis_envelopes_deg(
        envelope_deg=180.0,
        camera_up_limit_deg=float(config.root_rotation_camera_up_limit_deg),
    )
    assert envelopes == (180.0, 180.0, 45.0), envelopes
    yaw_lo, yaw_hi = root_rotation_search_bounds(
        40.0,
        frame_position=2,
        limit_deg=envelopes[2],
        first_frame_limit_deg=30.0,
        per_frame_limit_deg=30.0,
    )
    assert yaw_lo == 10.0, yaw_lo
    assert yaw_hi == 45.0, yaw_hi

    axes = ("camera_forward", "camera_right", "camera_up")
    assert root_rotation_axes_for_phase(axes, defer_camera_up=False, phase="initial") == axes
    assert root_rotation_axes_for_phase(axes, defer_camera_up=True, phase="initial") == (
        "camera_forward",
        "camera_right",
    )
    assert root_rotation_axes_for_phase(axes, defer_camera_up=True, phase="after_joints") == (
        "camera_up",
    )
    try:
        root_rotation_axes_for_phase(axes, defer_camera_up=True, phase="mid")
        raise AssertionError("unknown root rotation phase must fail closed")
    except ValueError as exc:
        assert "initial or after_joints" in str(exc)
    try:
        root_rotation_axes_for_phase(
            ("camera_forward",),
            defer_camera_up=True,
            phase="initial",
        )
        raise AssertionError("defer without camera_up must fail closed")
    except ValueError as exc:
        assert "camera_up" in str(exc)

    _assert_raises(
        "optimize_root_rotation",
        root_rotation_defer_camera_up=True,
        optimize_root_rotation=False,
    )
    _assert_raises(
        "camera_up in root_rotation_axes",
        root_rotation_defer_camera_up=True,
        root_rotation_axes=("camera_forward", "camera_right"),
    )
    _assert_raises(
        "positive camera_up limit",
        root_rotation_defer_camera_up=True,
        root_rotation_camera_up_limit_deg=0.0,
    )
    _assert_raises(
        "joint stage",
        root_rotation_defer_camera_up=True,
        optimize_bones=False,
    )
    _assert_raises(
        "joint stage",
        root_rotation_defer_camera_up=True,
        articulated_iterations=0,
        base_pose_enabled=False,
        mid_pose_enabled=False,
        fine_iterations=0,
        gradient_ladder_enabled=False,
        sa_enabled=False,
        ik_enabled=False,
        branch_rescue_enabled=False,
    )
    GpuCascadeConfig(
        root_rotation_defer_camera_up=True,
        articulated_iterations=0,
        base_pose_enabled=False,
        mid_pose_enabled=False,
        fine_iterations=0,
        gradient_ladder_enabled=True,
        gradient_ladder_iterations=1,
        sa_enabled=False,
        ik_enabled=False,
        branch_rescue_enabled=False,
    ).validate()

    hypothesis_src = inspect.getsource(GpuCascadeExperiment._root_hypothesis_start)
    assert "_root_rotation_search_mask" in hypothesis_src
    assert "rootYawDeferred=" in hypothesis_src
    clip_src = inspect.getsource(GpuCascadeExperiment.optimize_clip)
    assert 'label="root_yaw"' in clip_src
    assert 'phase="after_joints"' in clip_src
    assert 'phase="initial"' in clip_src

    return {
        "ok": True,
        "firstWindow": first,
        "zeroFirstRow": True,
        "yawCap": envelopes[2],
        "deferCameraUp": True,
    }


if __name__ == "__main__":
    print(run())
