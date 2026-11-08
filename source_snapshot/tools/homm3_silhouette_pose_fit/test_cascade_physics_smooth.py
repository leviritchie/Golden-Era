"""Metric-free cascade physics post-pass tests. No GPU, no sprite scores."""
from __future__ import annotations

import inspect
import math
import unittest

import numpy as np

from cascade_physics_smooth import (
    PhysicsSmoothConfig,
    _rotvec_matrix,
    geodesic_radians,
    smooth_cascade_clip,
)


FORBIDDEN_SCORE_NAMES = (
    "score",
    "iou",
    "chroma",
    "collision",
    "silhouette",
    "keep",
)


def _clip(
    bones: np.ndarray,
    translation: np.ndarray | None = None,
    rotation: np.ndarray | None = None,
    *,
    config: PhysicsSmoothConfig,
    bone_depths: np.ndarray | None = None,
    bind_directions: np.ndarray | None = None,
):
    frames = int(bones.shape[0])
    if translation is None:
        translation = np.zeros((frames, 3), dtype=np.float64)
    if rotation is None:
        rotation = np.zeros((frames, 3), dtype=np.float64)
    return smooth_cascade_clip(
        bones,
        translation,
        rotation,
        config=config,
        bone_depths=bone_depths,
        bind_directions=bind_directions,
    )


class CascadePhysicsSmoothTests(unittest.TestCase):
    def test_signature_has_no_sprite_or_geometry_scores(self) -> None:
        names = set(inspect.signature(smooth_cascade_clip).parameters)
        for forbidden in FORBIDDEN_SCORE_NAMES:
            hits = [name for name in names if forbidden in name.lower()]
            self.assertEqual(hits, [], f"smooth_cascade_clip must not take {forbidden} inputs")
        self.assertNotIn("depth", names)
        self.assertNotIn("depth_weight", names)

    def test_disabled_is_identity(self) -> None:
        rng = np.random.default_rng(17)
        bones = rng.normal(scale=0.2, size=(8, 4, 3))
        translation = rng.normal(scale=0.05, size=(8, 3))
        rotation = rng.normal(scale=0.1, size=(8, 3))
        config = PhysicsSmoothConfig(enabled=False)
        out_b, out_t, out_r, report = _clip(bones, translation, rotation, config=config)
        np.testing.assert_allclose(out_b, bones)
        np.testing.assert_allclose(out_t, translation)
        np.testing.assert_allclose(out_r, rotation)
        self.assertFalse(report["enabled"])

    def test_one_frame_spike_is_pulled_in(self) -> None:
        bones = np.zeros((7, 1, 3), dtype=np.float64)
        bones[3, 0, 0] = math.radians(45.0)
        config = PhysicsSmoothConfig(enabled=True, gravity_weight=0.0)
        out_b, _, _, report = _clip(bones, config=config)
        peak_after = float(np.max(np.linalg.norm(out_b, axis=-1))) * (180.0 / math.pi)
        self.assertGreater(report["outlierBoneFrames"], 0)
        self.assertLess(peak_after, 8.0)

    def test_high_frequency_jitter_rms_accel_drops(self) -> None:
        bones = np.zeros((12, 1, 3), dtype=np.float64)
        bones[:, 0, 0] = np.array(
            [0.0, 0.12, 0.0, 0.12, 0.0, 0.12, 0.0, 0.12, 0.0, 0.12, 0.0, 0.12],
            dtype=np.float64,
        )
        config = PhysicsSmoothConfig(
            enabled=True,
            outlier_min_deg=20.0,
            gravity_weight=0.0,
        )
        out_b, _, _, _ = _clip(bones, config=config)
        before = bones[2:, 0] - 2.0 * bones[1:-1, 0] + bones[:-2, 0]
        after = out_b[2:, 0] - 2.0 * out_b[1:-1, 0] + out_b[:-2, 0]
        rms_before = float(np.sqrt(np.mean(np.sum(before * before, axis=-1))))
        rms_after = float(np.sqrt(np.mean(np.sum(after * after, axis=-1))))
        self.assertLess(rms_after, 0.55 * rms_before)

    def test_step_input_has_inertial_lag(self) -> None:
        bones = np.zeros((8, 1, 3), dtype=np.float64)
        bones[4:, 0, 0] = math.radians(30.0)
        config = PhysicsSmoothConfig(
            enabled=True,
            outlier_min_deg=40.0,
            gravity_weight=0.0,
        )
        out_b, _, _, _ = _clip(bones, config=config)
        arrived = abs(float(out_b[4, 0, 0]))
        target = math.radians(30.0)
        self.assertLess(arrived, 0.7 * target)
        self.assertGreater(arrived, 0.05 * target)

    def test_gravity_pulls_distal_outlier_down(self) -> None:
        bones = np.zeros((7, 1, 3), dtype=np.float64)
        bones[3, 0, 0] = math.radians(80.0)
        bind = np.asarray(((0.0, 1.0, 0.0),), dtype=np.float64)
        depths = np.asarray((3,), dtype=np.int32)
        none_b, _, _, _ = _clip(
            bones,
            config=PhysicsSmoothConfig(gravity_weight=0.0),
            bone_depths=depths,
            bind_directions=bind,
        )
        grav_b, _, _, report = _clip(
            bones,
            config=PhysicsSmoothConfig(gravity_weight=1.0, gravity=80.0),
            bone_depths=depths,
            bind_directions=bind,
        )
        self.assertGreater(report["outlierBoneFrames"], 0)
        down = np.asarray((0.0, -1.0, 0.0), dtype=np.float64)

        def _downness(rotvec: np.ndarray) -> float:
            direction = _rotvec_matrix(rotvec) @ bind[0]
            direction = direction / max(float(np.linalg.norm(direction)), 1e-12)
            return float(np.dot(direction, down))

        self.assertGreater(_downness(grav_b[3, 0]), _downness(none_b[3, 0]))

    def test_constant_raised_pose_does_not_droop(self) -> None:
        bones = np.zeros((8, 1, 3), dtype=np.float64)
        bones[:, 0, 0] = math.radians(30.0)
        bind = np.asarray(((0.0, 1.0, 0.0),), dtype=np.float64)
        depths = np.asarray((3,), dtype=np.int32)
        out_b, _, _, report = _clip(
            bones,
            config=PhysicsSmoothConfig(enabled=True, gravity_weight=1.0, gravity=9.81),
            bone_depths=depths,
            bind_directions=bind,
        )
        self.assertEqual(report["outlierBoneFrames"], 0)
        for index in range(int(bones.shape[0])):
            self.assertLess(geodesic_radians(out_b[index, 0], bones[index, 0]), math.radians(1.0))

    def test_root_gravity_lowers_vertical_outlier_vs_neighbor_fill(self) -> None:
        translation = np.zeros((7, 3), dtype=np.float64)
        translation[3, 2] = 0.9
        bones = np.zeros((7, 1, 3), dtype=np.float64)
        none_t = _clip(
            bones,
            translation,
            config=PhysicsSmoothConfig(gravity_weight=0.0),
        )[1]
        grav_t = _clip(
            bones,
            translation,
            config=PhysicsSmoothConfig(gravity_weight=1.0, gravity=9.81, root_vertical_axis=2),
        )[1]
        self.assertLess(float(grav_t[3, 2]), float(none_t[3, 2]))

    def test_invalid_config_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            PhysicsSmoothConfig(outlier_window=4).validate()
        with self.assertRaises(ValueError):
            PhysicsSmoothConfig(stiffness=-1.0).validate()
        with self.assertRaises(ValueError):
            PhysicsSmoothConfig(dt=0.0).validate()
        with self.assertRaises(ValueError):
            PhysicsSmoothConfig(world_up=(0.0, 0.0, 0.0)).validate()
        with self.assertRaises(ValueError):
            smooth_cascade_clip(
                np.zeros((3, 1, 3)),
                np.zeros((3, 3)),
                np.zeros((3, 3)),
                config=PhysicsSmoothConfig(outlier_window=2),
            )


if __name__ == "__main__":
    unittest.main()
