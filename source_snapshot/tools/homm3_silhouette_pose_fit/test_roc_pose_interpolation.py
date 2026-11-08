from __future__ import annotations

import math

import numpy as np

from roc_pose_interpolation import (
    MOTION_ROOT_KEY,
    _as_euler_radians,
    interpolate_clip,
    interpolate_pose,
)


def _pose(x: float, z: float, forward: float) -> dict:
    return {
        "Bone": {"x": x, "y": 0.0, "z": z},
        MOTION_ROOT_KEY: {"forward": forward, "lateral": 0.0, "vertical": 0.0},
    }


def test_linear_clip_count_and_root_are_temporally_uniform():
    poses = interpolate_clip(
        [_pose(0.0, 0.0, 0.0), _pose(1.2, 0.0, 0.2)],
        method="euler_linear",
        samples_per_interval=2,
        loop=False,
    )
    assert len(poses) == 3
    assert abs(poses[1][MOTION_ROOT_KEY]["forward"] - 0.1) < 1e-9
    assert abs(poses[1]["Bone"]["x"] - 0.6) < 1e-9


def test_quaternion_methods_keep_source_endpoints_and_differ_in_timing():
    start = _pose(0.2, 0.4, 0.0)
    end = _pose(1.1, -0.7, 0.2)
    linear = interpolate_pose(start, end, 0.25, method="euler_linear")
    slerp = interpolate_pose(start, end, 0.25, method="quaternion_slerp")
    eased = interpolate_pose(start, end, 0.25, method="quaternion_smoothstep")
    for t, expected in ((0.0, start), (1.0, end)):
        actual = interpolate_pose(start, end, t, method="quaternion_slerp")
        assert actual["Bone"]["quaternionOrder"] == "wxyz"
        assert np.allclose(
            _as_euler_radians(actual["Bone"]),
            _as_euler_radians(expected["Bone"]),
        )
        assert actual[MOTION_ROOT_KEY] == expected[MOTION_ROOT_KEY]
    assert slerp["Bone"] != linear["Bone"]
    assert eased["Bone"] != slerp["Bone"]
    assert eased[MOTION_ROOT_KEY] == linear[MOTION_ROOT_KEY]


def test_loop_resampling_omits_duplicate_terminal_frame():
    poses = interpolate_clip(
        [_pose(0.0, 0.0, 0.0), _pose(0.1, 0.0, 0.1), _pose(0.2, 0.0, 0.2)],
        method="quaternion_slerp",
        samples_per_interval=5,
        loop=True,
    )
    assert len(poses) == 15
    assert np.allclose(
        _as_euler_radians(poses[0]["Bone"]),
        _as_euler_radians(_pose(0.0, 0.0, 0.0)["Bone"]),
    )
    assert poses[-1][MOTION_ROOT_KEY]["forward"] != 0.0
