"""Cascade joints keep absolute+unique gain; 15° and 45° are siblings."""
from __future__ import annotations

import math

from gpu_geometry_score import unique_geometry_quality, unique_occupancy_quality
from roc_gpu_cascade_experiment import (
    GpuCascadeConfig,
    axis_rung_after,
    extra_collision_keep_score,
    first_axis_window_deg,
    gather_per_frame_winners,
    offset_raw_bone_axis,
)


def run() -> dict[str, object]:
    import torch

    config = GpuCascadeConfig()
    config.validate()
    assert float(config.joint_step_deg) == 15.0, config.joint_step_deg
    assert float(config.joint_pass_limit_deg) == 0.0, config.joint_pass_limit_deg
    assert int(config.joint_probe_rungs) == 3, config.joint_probe_rungs
    assert int(config.joint_score_raster_batch) == 512, config.joint_score_raster_batch
    assert int(config.joint_diagonal_axes) == 6, config.joint_diagonal_axes
    assert float(config.joint_absolute_gain_weight) == 1.0
    assert first_axis_window_deg(15.0, rungs=3, limit_deg=150.0) == (
        15.0,
        -15.0,
        30.0,
        -30.0,
        45.0,
        -45.0,
    )
    assert axis_rung_after(45.0, step_deg=15.0, limit_deg=150.0) == 60.0
    assert float(config.proximal_bone_limit_scale) == 1.0, config.proximal_bone_limit_scale
    assert int(config.articulated_iterations) == 2, config.articulated_iterations
    assert int(config.adam_stall_reject_streak) == 3, config.adam_stall_reject_streak
    assert bool(config.joint_round_followup_neighbors) is True
    assert axis_rung_after(15.0, step_deg=15.0, limit_deg=150.0) == 30.0
    assert axis_rung_after(-15.0, step_deg=15.0, limit_deg=150.0) == -30.0
    assert axis_rung_after(150.0, step_deg=15.0, limit_deg=150.0) is None

    body = torch.zeros((2, 8, 8), dtype=torch.float32)
    body[:, 2:6, 2:6] = 1.0
    walk = body.clone()
    walk[1, 2:6, 6:8] = 1.0
    predicted_rest = body.clone()
    unique_rest = unique_occupancy_quality(
        target_foreground=walk,
        predicted_foreground=predicted_rest,
    )
    idle_q = float(unique_rest["uniqueOccupancyQuality"][0])
    walk_q = float(unique_rest["uniqueOccupancyQuality"][1])
    assert idle_q > walk_q, (idle_q, walk_q)
    predicted_walk = walk.clone()
    unique_explained = unique_occupancy_quality(
        target_foreground=walk,
        predicted_foreground=predicted_walk,
    )
    assert float(unique_explained["uniqueOccupancyQuality"][1]) > walk_q
    mixed = predicted_rest.clone()
    mixed[1] = walk[1]
    unique_mixed = unique_occupancy_quality(
        target_foreground=walk,
        predicted_foreground=mixed,
    )
    assert abs(
        float(unique_mixed["uniqueOccupancyError"][0]) - float(unique_rest["uniqueOccupancyError"][0])
    ) < 1e-6
    assert float(unique_mixed["uniqueOccupancyError"][1]) < float(unique_rest["uniqueOccupancyError"][1])

    same_blob = torch.zeros((2, 8, 8), dtype=torch.float32)
    same_blob[:, 2:6, 2:6] = 1.0
    chroma_err = torch.full((2, 8, 8), 0.10, dtype=torch.float32)
    chroma_err[1, 2:6, 2:6] = 0.80
    target_ab = torch.zeros((2, 8, 8, 2), dtype=torch.float32)
    target_ab[0, 2:6, 2:6, 0] = 20.0
    target_ab[1, 2:6, 2:6, 1] = 20.0
    inside_blob = unique_geometry_quality(
        target_foreground=same_blob,
        predicted_foreground=same_blob,
        pixel_chroma_error=chroma_err,
        target_ab=target_ab,
        silhouette_weight=0.01,
        chroma_weight=0.50,
    )
    assert float(inside_blob["uniqueOccupancyError"].max()) < 1e-6
    assert float(inside_blob["uniqueGeometryQuality"][0]) > float(
        inside_blob["uniqueGeometryQuality"][1]
    )

    scales = torch.ones(3, dtype=torch.float32)
    raw = torch.zeros((2, 3, 3), dtype=torch.float32)
    moved = offset_raw_bone_axis(
        raw,
        bone_index=1,
        axis_index=0,
        delta_rad=math.radians(15.0),
        joint_limit_rad=math.radians(150.0),
        bone_limit_scales=scales,
    )
    moved_45 = offset_raw_bone_axis(
        raw,
        bone_index=1,
        axis_index=0,
        delta_rad=math.radians(45.0),
        joint_limit_rad=math.radians(150.0),
        bone_limit_scales=scales,
    )
    chroma_now = inside_blob["uniqueGeometryQuality"]
    plus15 = chroma_now.clone()
    plus15[1] = chroma_now[1] - 0.02
    plus45 = chroma_now.clone()
    plus45[1] = chroma_now[1] + 0.20
    _blended, chroma_winner, _chosen = gather_per_frame_winners(
        [raw, moved, moved_45],
        [chroma_now, plus15, plus45],
    )
    assert chroma_winner.tolist() == [0, 2], chroma_winner.tolist()

    current_unique = torch.tensor([0.90, 0.40])
    plus_unique = torch.tensor([0.88, 0.72])
    minus_unique = torch.tensor([0.89, 0.41])
    blended, winner, chosen = gather_per_frame_winners(
        [raw, moved, offset_raw_bone_axis(
            raw,
            bone_index=1,
            axis_index=0,
            delta_rad=math.radians(-15.0),
            joint_limit_rad=math.radians(150.0),
            bone_limit_scales=scales,
        )],
        [current_unique, plus_unique, minus_unique],
    )
    assert winner.tolist() == [0, 1], winner.tolist()
    assert torch.equal(blended[0], raw[0])
    assert torch.equal(blended[1], moved[1])

    current_geom = torch.tensor([0.50, 0.40])
    nibble_geom = torch.tensor([0.49, 0.39])
    current_col = torch.tensor([0.20, 0.20])
    nibble_col = torch.tensor([0.05, 0.05])
    pretzel_geom = torch.tensor([0.70, 0.70])
    pretzel_col = torch.tensor([0.90, 0.90])
    nibble_keep = extra_collision_keep_score(
        nibble_geom,
        nibble_col,
        current_col,
        collision_weight=0.35,
    )
    pretzel_keep = extra_collision_keep_score(
        pretzel_geom,
        pretzel_col,
        current_col,
        collision_weight=0.35,
    )
    current_keep = extra_collision_keep_score(
        current_geom,
        current_col,
        current_col,
        collision_weight=0.35,
    )
    assert float(nibble_keep[0]) < float(current_keep[0])
    assert float(pretzel_keep[0]) < float(current_keep[0])

    return {
        "ok": True,
        "idleUnique": idle_q,
        "walkUnique": walk_q,
        "chromaWinners": chroma_winner.tolist(),
        "winners": winner.tolist(),
    }


if __name__ == "__main__":
    print(run())
