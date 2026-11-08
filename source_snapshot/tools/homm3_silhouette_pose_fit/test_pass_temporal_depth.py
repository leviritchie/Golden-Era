"""Helpers for interleaved 10-degree bone passes and sequential temporal penalties."""
from __future__ import annotations

import math

import numpy as np
import torch

from gpu_depth_silhouette_solver import (
    DepthSilhouetteConfig,
    label_binary_components,
    missing_target_silhouette,
    nearest_joint_indices,
    pack_axis_job_chunks,
    pass_angle_grid,
    score_meaningfully_higher,
    temporal_bone_penalty,
    unstick_angle_samples,
)


def run() -> dict[str, object]:
    grid = pass_angle_grid(
        40.0,
        joint_limit_deg=150.0,
        pass_limit_deg=10.0,
        pass_step_deg=2.5,
    )
    assert float(grid.min()) >= 30.0 - 1e-6, grid
    assert float(grid.max()) <= 50.0 + 1e-6, grid
    assert np.any(np.isclose(grid, 40.0)), grid
    assert not np.any(np.isclose(grid, 0.0)), grid

    clipped = pass_angle_grid(
        145.0,
        joint_limit_deg=150.0,
        pass_limit_deg=10.0,
        pass_step_deg=2.5,
    )
    assert float(clipped.max()) <= 150.0 + 1e-6, clipped
    assert float(clipped.min()) >= 135.0 - 1e-6, clipped

    try:
        pass_angle_grid(0.0, joint_limit_deg=150.0, pass_limit_deg=0.0, pass_step_deg=2.5)
        raise AssertionError("zero pass_limit_deg must stay fail-closed")
    except ValueError as exc:
        assert "positive pass_limit_deg" in str(exc)

    DepthSilhouetteConfig().validate()
    DepthSilhouetteConfig(pass_limit_deg=10.0, pass_step_deg=2.5, temporal_weight=0.12).validate()
    DepthSilhouetteConfig(pass_limit_deg=15.0, pass_step_deg=2.5, packed_axis_batch=128).validate()
    DepthSilhouetteConfig(pass_limit_deg=15.0, pass_step_deg=2.5, packed_axis_batch=0).validate()
    try:
        DepthSilhouetteConfig(packed_axis_batch=-1).validate()
        raise AssertionError("negative packed_axis_batch must stay fail-closed")
    except ValueError as exc:
        assert "packed_axis_batch" in str(exc)
    try:
        DepthSilhouetteConfig(pass_limit_deg=10.0, pass_step_deg=0.0).validate()
        raise AssertionError("zero pass_step_deg must stay fail-closed")
    except ValueError as exc:
        assert "pass_step_deg" in str(exc)
    try:
        DepthSilhouetteConfig(temporal_weight=0.12, temporal_scale_deg=0.0).validate()
        raise AssertionError("zero temporal_scale_deg must stay fail-closed")
    except ValueError as exc:
        assert "temporal_scale_deg" in str(exc)

    previous = torch.zeros((1, 4, 3), dtype=torch.float32)
    same = temporal_bone_penalty(previous.expand(3, -1, -1), previous, scale_deg=20.0)
    assert torch.allclose(same, torch.zeros(3)), same
    far = previous.clone()
    far[0, 0, 0] = math.radians(40.0)
    larger = temporal_bone_penalty(far.expand(3, -1, -1), previous, scale_deg=20.0)
    near = previous.clone()
    near[0, 0, 0] = math.radians(5.0)
    smaller = temporal_bone_penalty(near.expand(3, -1, -1), previous, scale_deg=20.0)
    ten = previous.clone()
    ten[0, 0, 0] = math.radians(10.0)
    ten_penalty = temporal_bone_penalty(ten.expand(3, -1, -1), previous, scale_deg=20.0)
    assert float(larger[0]) > float(ten_penalty[0]) > float(smaller[0]) > 0.0
    # One 10-degree axis must remain visible after tanh, not disappear into a 48-bone mean.
    assert float(ten_penalty[0]) > 0.2, ten_penalty

    window = pass_angle_grid(0.0, joint_limit_deg=150.0, pass_limit_deg=15.0, pass_step_deg=2.5)
    assert len(window) == 13, window
    twenty = (13,) * 20
    chunks = pack_axis_job_chunks(twenty, 128)
    assert chunks == ((0, 9), (9, 18), (18, 20)), chunks
    assert all(sum(twenty[start:end]) <= 128 for start, end in chunks)
    exact = pack_axis_job_chunks((13, 13), 13)
    assert exact == ((0, 1), (1, 2)), exact
    try:
        pack_axis_job_chunks((200,), 128)
        raise AssertionError("oversized axis window must stay fail-closed")
    except ValueError as exc:
        assert "increase packed_axis_batch or pass_step_deg" in str(exc)
    try:
        pack_axis_job_chunks((13,), 0)
        raise AssertionError("zero packed_axis_batch must stay fail-closed when packing")
    except ValueError as exc:
        assert "at least 1" in str(exc)

    DepthSilhouetteConfig().validate()
    assert int(DepthSilhouetteConfig().unstick_joint_count) == 0
    DepthSilhouetteConfig(unstick_joint_count=0).validate()
    try:
        DepthSilhouetteConfig(
            unstick_joint_count=5,
            unstick_samples_per_bone=5,
            unstick_max_candidates=128,
        ).validate()
        raise AssertionError("oversized unstick grid must stay fail-closed")
    except ValueError as exc:
        assert "unstick_max_candidates" in str(exc)

    assert score_meaningfully_higher(0.70, 0.72, 0.005)
    assert not score_meaningfully_higher(0.70, 0.703, 0.005)
    try:
        score_meaningfully_higher(0.70, float("nan"), 0.005)
        raise AssertionError("non-finite job score must stay fail-closed")
    except ValueError as exc:
        assert "finite" in str(exc)

    target = np.zeros((4, 5), dtype=np.float32)
    predicted = np.zeros((4, 5), dtype=np.float32)
    target[0:2, 0:2] = 1.0
    target[3, 4] = 1.0
    predicted[0, 0] = 1.0
    missing = missing_target_silhouette(target, predicted, threshold=0.5)
    labels, section_count = label_binary_components(missing)
    assert section_count == 2, (missing, labels, section_count)
    joints = np.asarray(((0.0, 0.0), (4.0, 3.0), (2.0, 2.0)), dtype=np.float64)
    closest, distances = nearest_joint_indices(joints, missing, 2)
    assert closest[0] == 1, (closest, distances)
    assert closest[1] == 0, (closest, distances)
    samples = unstick_angle_samples(
        10.0,
        unstick_limit_deg=60.0,
        joint_limit_deg=150.0,
        sample_count=3,
    )
    assert len(samples) == 3, samples
    assert np.any(np.isclose(samples, 10.0)), samples
    assert float(samples.min()) <= -50.0 + 1e-6, samples
    assert float(samples.max()) >= 70.0 - 1e-6, samples
    near_limit = unstick_angle_samples(
        140.0,
        unstick_limit_deg=60.0,
        joint_limit_deg=150.0,
        sample_count=3,
    )
    assert len(near_limit) == 3, near_limit
    assert np.any(np.isclose(near_limit, 140.0)), near_limit
    # Five joints at a clamped limit must stay at 3**5, not 4**3 * 3**2 = 576.
    combo = 1
    for current in (10.0, 40.0, 140.0, 145.0, -140.0):
        combo *= len(
            unstick_angle_samples(
                current,
                unstick_limit_deg=60.0,
                joint_limit_deg=150.0,
                sample_count=3,
            )
        )
    assert combo <= 3 ** 5, combo

    return {
        "ok": True,
        "passWindow": [float(grid.min()), float(grid.max())],
        "passCount": int(len(grid)),
        "packedChunks": [list(chunk) for chunk in chunks],
        "windowCount": int(len(window)),
        "farPenalty": float(larger[0]),
        "nearPenalty": float(smaller[0]),
    }


if __name__ == "__main__":
    print(run())
