"""Root rotation on frame 00 is a tight window; later frames step from current."""
from __future__ import annotations

import numpy as np

from gpu_depth_silhouette_solver import (
    DepthSilhouetteConfig,
    _inclusive_grid,
    root_rotation_axis_envelope_deg,
    root_rotation_axis_envelopes_deg,
    root_rotation_axes_for_phase,
    root_rotation_search_bounds,
    root_rotation_search_limit_deg,
    root_rotation_search_window_deg,
)
from roc_gpu_cascade_experiment import invert_bounded_root_rotation


def run() -> dict[str, object]:
    first_window = root_rotation_search_window_deg(
        frame_position=0,
        limit_deg=180.0,
        first_frame_limit_deg=30.0,
        per_frame_limit_deg=30.0,
    )
    later_window = root_rotation_search_window_deg(
        frame_position=1,
        limit_deg=180.0,
        first_frame_limit_deg=30.0,
        per_frame_limit_deg=30.0,
    )
    frozen_first = root_rotation_search_window_deg(
        frame_position=0,
        limit_deg=180.0,
        first_frame_limit_deg=0.0,
        per_frame_limit_deg=30.0,
    )
    later_unfrozen = root_rotation_search_window_deg(
        frame_position=1,
        limit_deg=180.0,
        first_frame_limit_deg=0.0,
        per_frame_limit_deg=30.0,
    )
    clamped = root_rotation_search_limit_deg(
        20.0,
        frame_position=0,
        first_frame_limit_deg=30.0,
    )
    assert first_window == 30.0, first_window
    assert later_window == 30.0, later_window
    assert frozen_first == 0.0, frozen_first
    assert later_unfrozen == 30.0, later_unfrozen
    assert clamped == 20.0, clamped
    assert later_window != 180.0

    first_lo, first_hi = root_rotation_search_bounds(
        0.0,
        frame_position=0,
        limit_deg=180.0,
        first_frame_limit_deg=30.0,
        per_frame_limit_deg=30.0,
    )
    first_grid = _inclusive_grid(first_lo, first_hi, 30.0)
    assert 90.0 not in first_grid.tolist(), first_grid
    assert 0.0 in first_grid.tolist()
    assert 30.0 in first_grid.tolist()

    later_lo, later_hi = root_rotation_search_bounds(
        0.0,
        frame_position=1,
        limit_deg=180.0,
        first_frame_limit_deg=30.0,
        per_frame_limit_deg=30.0,
    )
    later_grid = _inclusive_grid(later_lo, later_hi, 30.0)
    assert 90.0 not in later_grid.tolist(), later_grid

    turned_lo, turned_hi = root_rotation_search_bounds(
        40.0,
        frame_position=2,
        limit_deg=180.0,
        first_frame_limit_deg=30.0,
        per_frame_limit_deg=30.0,
    )
    assert turned_lo == 10.0, turned_lo
    assert turned_hi == 70.0, turned_hi

    assert root_rotation_axis_envelope_deg(
        "camera_up", envelope_deg=180.0, camera_up_limit_deg=45.0
    ) == 45.0
    assert root_rotation_axis_envelope_deg(
        "camera_forward", envelope_deg=180.0, camera_up_limit_deg=45.0
    ) == 180.0
    assert root_rotation_axis_envelope_deg(
        "camera_right", envelope_deg=180.0, camera_up_limit_deg=45.0
    ) == 180.0
    assert root_rotation_axis_envelope_deg(
        "camera_up", envelope_deg=30.0, camera_up_limit_deg=45.0
    ) == 30.0
    try:
        root_rotation_axis_envelope_deg("world_up", envelope_deg=180.0, camera_up_limit_deg=45.0)
        raise AssertionError("unknown root rotation axis must fail closed")
    except ValueError as exc:
        assert "camera_forward" in str(exc)

    yaw_lo, yaw_hi = root_rotation_search_bounds(
        40.0,
        frame_position=2,
        limit_deg=45.0,
        first_frame_limit_deg=30.0,
        per_frame_limit_deg=30.0,
    )
    assert yaw_lo == 10.0, yaw_lo
    assert yaw_hi == 45.0, yaw_hi

    DepthSilhouetteConfig().validate()
    assert bool(DepthSilhouetteConfig().root_rotation_defer_camera_up) is True
    axes = ("camera_forward", "camera_right", "camera_up")
    assert root_rotation_axes_for_phase(
        axes, defer_camera_up=True, phase="initial"
    ) == ("camera_forward", "camera_right")
    assert root_rotation_axes_for_phase(
        axes, defer_camera_up=True, phase="after_joints"
    ) == ("camera_up",)
    try:
        root_rotation_axes_for_phase(axes, defer_camera_up=True, phase="bones")
        raise AssertionError("unknown root rotation phase must fail closed")
    except ValueError as exc:
        assert "initial or after_joints" in str(exc)

    envelopes = root_rotation_axis_envelopes_deg(
        envelope_deg=180.0,
        camera_up_limit_deg=45.0,
    )
    halves = np.radians(np.asarray(envelopes, dtype=np.float64))
    grid = np.radians(_inclusive_grid(-30.0, 30.0, 3.75))
    assert int(grid.shape[0]) == 17
    yaw_raw = invert_bounded_root_rotation(
        grid,
        center=0.0,
        halves=halves,
        axis_index=2,
    )
    assert tuple(yaw_raw.shape) == (17,)
    try:
        invert_bounded_root_rotation(grid, center=0.0, halves=halves)
        raise AssertionError("1D root grid without axis_index must fail closed")
    except ValueError as exc:
        assert "last-dim 3" in str(exc)
    stacked = np.stack((grid[:3], grid[3:6], grid[6:9]), axis=1)
    triple = invert_bounded_root_rotation(stacked, center=0.0, halves=halves)
    assert tuple(triple.shape) == (3, 3)

    return {
        "ok": True,
        "firstGrid": [float(value) for value in first_grid],
        "laterGrid": [float(value) for value in later_grid],
        "turned": [turned_lo, turned_hi],
        "oneBoneGrid": int(grid.shape[0]),
    }


if __name__ == "__main__":
    print(run())
