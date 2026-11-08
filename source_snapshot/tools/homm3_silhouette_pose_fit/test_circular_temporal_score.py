"""Circular forward/backward velocity and acceleration across loop seams."""
from __future__ import annotations

import math

import numpy as np

from circular_temporal_score import (
    CircularTemporalConfig,
    apply_circular_temporal_clip,
    circular_acceleration_rms,
    circular_backward_first_difference,
    circular_first_difference,
    circular_second_difference,
    circular_velocity_rms,
    linear_velocity_rms,
    wrap_velocity_rms,
)


def run() -> dict[str, object]:
    sine = np.zeros((8, 3), dtype=np.float64)
    for index in range(8):
        sine[index, 0] = math.sin(2.0 * math.pi * index / 8.0)
    linear = linear_velocity_rms(sine)
    circular = circular_velocity_rms(sine)
    # A closed sinusoid's wrap step matches interior steps; circular must
    # not invent extra energy relative to the linear interior mean.
    assert abs(circular - linear) < 0.05, (circular, linear)

    popped = sine.copy()
    popped[-1, 0] = 4.0
    assert wrap_velocity_rms(popped) > wrap_velocity_rms(sine)
    assert circular_velocity_rms(popped) > circular_velocity_rms(sine)
    # Linear scoring misses the last→first jump.
    assert linear_velocity_rms(popped) < circular_velocity_rms(popped)

    forward = circular_first_difference(popped)
    backward = circular_backward_first_difference(popped)
    np.testing.assert_allclose(forward[0], popped[0] - popped[-1])
    np.testing.assert_allclose(backward[-1], popped[-1] - popped[0])
    np.testing.assert_allclose(wrap_velocity_rms(popped), wrap_velocity_rms(popped[::-1]))

    second = circular_second_difference(popped)
    np.testing.assert_allclose(second[0], popped[1] - 2.0 * popped[0] + popped[-1])
    np.testing.assert_allclose(second[-1], popped[0] - 2.0 * popped[-1] + popped[-2])

    bones = np.zeros((8, 1, 3), dtype=np.float64)
    bones[:, 0, 0] = sine[:, 0]
    bones[-1, 0, 0] = 2.5
    translation = np.zeros((8, 3), dtype=np.float64)
    rotation = np.zeros((8, 3), dtype=np.float64)
    before_wrap = wrap_velocity_rms(bones[:, 0, :])
    before_acc = circular_acceleration_rms(bones[:, 0, :])
    out_b, out_t, out_r, report = apply_circular_temporal_clip(
        bones,
        translation,
        rotation,
        config=CircularTemporalConfig(stiffness=180.0, blend=1.0),
        wrap=True,
    )
    assert report["applied"] is True
    assert report["direction"] == "forward_and_backward"
    after_wrap = wrap_velocity_rms(out_b[:, 0, :])
    after_acc = circular_acceleration_rms(out_b[:, 0, :])
    assert after_wrap < before_wrap, (before_wrap, after_wrap, report)
    assert after_acc <= before_acc + 1e-6, (before_acc, after_acc)
    assert out_t.shape == translation.shape
    assert out_r.shape == rotation.shape

    identity_b, _, _, skipped = apply_circular_temporal_clip(
        bones[:1],
        translation[:1],
        rotation[:1],
        wrap=True,
    )
    assert skipped["applied"] is False
    np.testing.assert_allclose(identity_b, bones[:1])

    nowrap_b, nowrap_t, nowrap_r, nowrap_report = apply_circular_temporal_clip(
        bones,
        translation,
        rotation,
        wrap=False,
    )
    assert nowrap_report["applied"] is False
    np.testing.assert_allclose(nowrap_b, bones)
    np.testing.assert_allclose(nowrap_t, translation)
    np.testing.assert_allclose(nowrap_r, rotation)

    from roc_gpu_cascade_experiment import GpuCascadeConfig

    default = GpuCascadeConfig()
    assert bool(default.temporal_loop_wrap_enabled) is False
    GpuCascadeConfig(temporal_loop_wrap_enabled=True, loop_enabled=False).validate()
    return {"ok": True, "wrapBefore": before_wrap, "wrapAfter": after_wrap}


if __name__ == "__main__":
    print(run())
