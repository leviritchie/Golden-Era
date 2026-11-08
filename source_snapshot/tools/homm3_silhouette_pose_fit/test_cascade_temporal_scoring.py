"""Velocity/acceleration-only temporal scoring mode guards."""
from __future__ import annotations

import unittest

from roc_gpu_cascade_experiment import GpuCascadeConfig


class CascadeTemporalScoringTests(unittest.TestCase):
    def test_velocity_only_requires_zero_motion_weight(self) -> None:
        cfg = GpuCascadeConfig(
            temporal_scoring_mode="velocity_acceleration_only",
            motion_weight=0.1,
            exact_raster_enabled=True,
            depth_weight=0.25,
            silhouette_weight=0.2,
        )
        with self.assertRaises(ValueError):
            cfg.validate()

    def test_velocity_only_accepts_zero_motion_weight(self) -> None:
        cfg = GpuCascadeConfig(
            temporal_scoring_mode="velocity_acceleration_only",
            motion_weight=0.0,
            exact_raster_enabled=True,
            silhouette_weight=0.2,
        )
        cfg.validate()

    def test_loop_wrap_defaults_off_and_does_not_need_loop_enabled(self) -> None:
        default = GpuCascadeConfig()
        self.assertFalse(bool(default.temporal_loop_wrap_enabled))
        wrapped = GpuCascadeConfig(
            temporal_loop_wrap_enabled=True,
            loop_enabled=False,
            exact_raster_enabled=True,
            silhouette_weight=0.2,
        )
        wrapped.validate()
        self.assertTrue(bool(wrapped.temporal_loop_wrap_enabled))

    def test_wrap_velocity_sees_last_to_first_jump(self) -> None:
        import torch
        from roc_gpu_cascade_experiment import GpuCascadeExperiment

        series = torch.zeros((8, 1, 3), dtype=torch.float32)
        series[-1, 0, 0] = 4.0
        linear_vel, linear_acc = GpuCascadeExperiment._channel_velocity_acceleration(
            None, series, scale=1.0, wrap=False
        )
        wrap_vel, wrap_acc = GpuCascadeExperiment._channel_velocity_acceleration(
            None, series, scale=1.0, wrap=True
        )
        self.assertGreater(float(wrap_vel), float(linear_vel))
        self.assertGreater(float(wrap_acc), float(linear_acc))


if __name__ == "__main__":
    unittest.main()
