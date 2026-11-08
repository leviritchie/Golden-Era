"""Incremental silhouette-blob IK: regional IoU, chain growth, keep-best."""

from __future__ import annotations

import inspect
import math

import numpy as np
import torch

from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
from ik_incremental_blob import (
    chain_prefixes,
    distal_first_parent_chain,
    dilate_binary_mask,
    grow_chain_keep_best,
    keep_best_interim,
    IncrementalBlobStep,
    region_iou,
    repair_region_from_blobs,
    search_chain_local_axes,
    step_deg_for_bone_depth,
)
from roc_gpu_cascade_experiment import GpuCascadeConfig, offset_raw_bone_direction


def test_region_iou_perfect_and_empty_union() -> None:
    predicted = np.zeros((8, 8), dtype=np.float32)
    target = np.zeros((8, 8), dtype=np.float32)
    region = np.zeros((8, 8), dtype=bool)
    region[2:6, 2:6] = True
    predicted[2:6, 2:6] = 1.0
    target[2:6, 2:6] = 1.0
    assert region_iou(predicted, target, region) == 1.0

    predicted_empty = np.zeros((8, 8), dtype=np.float32)
    target_empty = np.zeros((8, 8), dtype=np.float32)
    assert region_iou(predicted_empty, target_empty, region) == 1.0

    predicted_excess = np.zeros((8, 8), dtype=np.float32)
    predicted_excess[2:6, 2:6] = 1.0
    assert region_iou(predicted_excess, target_empty, region) == 0.0


def test_region_iou_empty_region_fails_closed() -> None:
    try:
        region_iou(np.zeros((4, 4)), np.zeros((4, 4)), np.zeros((4, 4), dtype=bool))
        raise AssertionError("empty region must fail closed")
    except ValueError as exc:
        assert "non-empty region" in str(exc)


def test_repair_region_covers_red_and_blue() -> None:
    excess = np.zeros((16, 16), dtype=bool)
    missing = np.zeros((16, 16), dtype=bool)
    excess[4, 4] = True
    missing[4, 8] = True
    region = repair_region_from_blobs(excess, missing, dilate_px=2)
    assert bool(region[4, 4])
    assert bool(region[4, 8])
    assert bool(region[4, 6])
    dilated = dilate_binary_mask(excess, 1)
    assert int(dilated.sum()) > 1


def test_distal_first_chain_omits_root_and_grows_prefixes() -> None:
    # 0 root, 1 spine, 2 arm, 3 hand
    parents = [None, 0, 1, 2]
    chain = distal_first_parent_chain(3, parents, max_joints=6)
    assert chain == [3, 2, 1], chain
    prefixes = chain_prefixes(chain)
    assert prefixes[0] == (3,)
    assert prefixes[1] == (3, 2)
    assert prefixes[2] == (3, 2, 1)
    short = distal_first_parent_chain(3, parents, max_joints=1)
    assert short == [3]


def test_distal_first_chain_root_end_fails_closed() -> None:
    try:
        distal_first_parent_chain(0, [None, 0], max_joints=4)
        raise AssertionError("root end effector must fail closed")
    except ValueError as exc:
        assert "empty" in str(exc)


def test_distal_first_chain_cycle_fails_closed() -> None:
    try:
        distal_first_parent_chain(1, [None, 2, 1], max_joints=4)
        raise AssertionError("parent cycle must fail closed")
    except ValueError as exc:
        assert "cycle" in str(exc)


def test_spinal_bones_get_small_step() -> None:
    limb = step_deg_for_bone_depth(
        5,
        proximal_min_depth=3,
        limb_step_deg=15.0,
        proximal_step_deg=5.0,
    )
    spine = step_deg_for_bone_depth(
        2,
        proximal_min_depth=3,
        limb_step_deg=15.0,
        proximal_step_deg=5.0,
    )
    assert limb == 15.0
    assert spine == 5.0


def test_keep_best_interim_prefers_shorter_on_tie() -> None:
    steps = (
        IncrementalBlobStep(0, (), 0.4, False),
        IncrementalBlobStep(1, (3,), 0.7, False),
        IncrementalBlobStep(2, (3, 2), 0.7, False),
        IncrementalBlobStep(3, (3, 2, 1), 0.65, False),
    )
    kept = keep_best_interim(steps)
    assert kept.chain_length == 1
    assert kept.chain_indices == (3,)


def test_grow_stops_when_target_hit_without_unlocking_parent() -> None:
    calls: list[tuple[int, ...]] = []

    def search_prefix(pose, prefix):
        calls.append(prefix)
        return f"pose-{len(prefix)}", 0.95

    result = grow_chain_keep_best(
        "opening",
        0.4,
        [(3,), (3, 2), (3, 2, 1)],
        search_prefix=search_prefix,
        target_score=0.9,
    )
    assert calls == [(3,)]
    assert result.kept_chain_length == 1
    assert result.score == 0.95
    assert result.pose == "pose-1"


def test_grow_keeps_best_interim_not_last_worse_extension() -> None:
    def search_prefix(pose, prefix):
        scores = {1: 0.72, 2: 0.81, 3: 0.60}
        return f"pose-{len(prefix)}", scores[len(prefix)]

    result = grow_chain_keep_best(
        "opening",
        0.40,
        [(3,), (3, 2), (3, 2, 1)],
        search_prefix=search_prefix,
        target_score=0.9,
    )
    assert result.kept_chain_length == 2
    assert result.score == 0.81
    assert result.pose == "pose-2"
    assert len(result.steps) == 4


def test_local_axis_search_moves_rewarded_bone() -> None:
    joint_limit_rad = math.radians(150.0)
    scales = torch.ones(4, dtype=torch.float32)
    pose = torch.zeros((1, 4, 3), dtype=torch.float32)

    def score_batch(stacked):
        bounded = torch.tanh(stacked) * joint_limit_rad
        return [float(bounded[index, 3, 0].item()) for index in range(int(stacked.shape[0]))]

    result, score, _rounds = search_chain_local_axes(
        pose,
        (3,),
        directions=((1.0, 0.0, 0.0),),
        step_rad_by_index={3: math.radians(15.0)},
        joint_limit_rad=joint_limit_rad,
        bone_limit_scales=scales,
        offset_fn=offset_raw_bone_direction,
        score_batch_fn=score_batch,
        rounds=2,
        stop_score=1.0,
    )
    bounded = torch.tanh(result) * joint_limit_rad
    assert float(bounded[0, 3, 0].item()) > 0.0
    assert score > 0.0
    assert float(bounded[0, 1, 0].item()) == 0.0


def test_local_axis_search_records_smaller_step_on_proximal_bone() -> None:
    joint_limit_rad = math.radians(150.0)
    scales = torch.ones(4, dtype=torch.float32)
    pose = torch.zeros((1, 4, 3), dtype=torch.float32)
    seen_steps: dict[int, float] = {}

    def offset_fn(raw, *, bone_index, direction, delta_rad, joint_limit_rad, bone_limit_scales):
        seen_steps[int(bone_index)] = abs(float(delta_rad))
        return offset_raw_bone_direction(
            raw,
            bone_index=bone_index,
            direction=direction,
            delta_rad=delta_rad,
            joint_limit_rad=joint_limit_rad,
            bone_limit_scales=bone_limit_scales,
        )

    def score_batch(stacked):
        return [0.0 for _ in range(int(stacked.shape[0]))]

    search_chain_local_axes(
        pose,
        (3, 1),
        directions=((1.0, 0.0, 0.0),),
        step_rad_by_index={
            3: math.radians(15.0),
            1: math.radians(5.0),
        },
        joint_limit_rad=joint_limit_rad,
        bone_limit_scales=scales,
        offset_fn=offset_fn,
        score_batch_fn=score_batch,
        rounds=1,
        stop_score=0.9,
    )
    assert abs(seen_steps[3] - math.radians(15.0)) < 1e-9
    assert abs(seen_steps[1] - math.radians(5.0)) < 1e-9


def test_grow_chain_on_step_reports_each_prefix() -> None:
    seen: list[tuple[int, float]] = []

    def search_prefix(pose, prefix):
        return f"pose-{len(prefix)}", 0.5 + 0.1 * len(prefix)

    def on_step(step, pose):
        seen.append((int(step.chain_length), float(step.score)))

    grow_chain_keep_best(
        "opening",
        0.40,
        [(3,), (3, 2)],
        search_prefix=search_prefix,
        target_score=0.9,
        on_step=on_step,
    )
    assert seen == [(1, 0.6), (2, 0.7)]


def test_search_chain_on_improvement_fires_for_winning_probe() -> None:
    joint_limit_rad = math.radians(150.0)
    scales = torch.ones(4, dtype=torch.float32)
    pose = torch.zeros((1, 4, 3), dtype=torch.float32)
    seen: list[float] = []

    def score_batch(stacked):
        bounded = torch.tanh(stacked) * joint_limit_rad
        return [float(bounded[index, 3, 0].item()) for index in range(int(stacked.shape[0]))]

    search_chain_local_axes(
        pose,
        (3,),
        directions=((1.0, 0.0, 0.0),),
        step_rad_by_index={3: math.radians(15.0)},
        joint_limit_rad=joint_limit_rad,
        bone_limit_scales=scales,
        offset_fn=offset_raw_bone_direction,
        score_batch_fn=score_batch,
        rounds=1,
        stop_score=0.9,
        on_improvement=lambda trial, score: seen.append(float(score)),
    )
    assert len(seen) == 1
    assert seen[0] > 0.0


def test_config_and_adapter_plumb_blob_ik_knobs() -> None:
    config = GpuCascadeConfig()
    assert config.ik_blob_iou_target == 0.9
    assert config.ik_proximal_min_depth == 3
    assert config.ik_proximal_max_step_deg == 5.0
    assert config.ik_max_chain_depth == 6
    assert config.ik_repair_dilate_px == 4
    assert config.ik_blob_search_rounds == 3

    GpuCascadeConfig(ik_enabled=True, ik_keypoints_source="silhouette_miss").validate()

    try:
        GpuCascadeConfig(
            ik_enabled=True,
            ik_keypoints_source="silhouette_miss",
            ik_blob_iou_target=0.0,
        ).validate()
        raise AssertionError("zero blob IoU target must fail closed")
    except ValueError as exc:
        assert "ik_blob_iou_target" in str(exc)

    try:
        GpuCascadeConfig(
            ik_enabled=True,
            ik_keypoints_source="silhouette_miss",
            ik_max_chain_depth=0,
        ).validate()
        raise AssertionError("zero max chain depth must fail closed")
    except ValueError as exc:
        assert "ik_max_chain_depth" in str(exc)

    try:
        GpuCascadeConfig(
            ik_enabled=True,
            ik_keypoints_source="silhouette_miss",
            ik_blob_search_rounds=0,
        ).validate()
        raise AssertionError("zero blob search rounds must fail closed")
    except ValueError as exc:
        assert "ik_blob_search_rounds" in str(exc)

    signature = inspect.signature(run_gpu_depth_fit_from_hybrid_config)
    for name in (
        "ik_blob_iou_target",
        "ik_proximal_min_depth",
        "ik_proximal_max_step_deg",
        "ik_max_chain_depth",
        "ik_repair_dilate_px",
        "ik_blob_search_rounds",
        "live_preview",
        "preview_every",
        "live_preview_scale",
    ):
        assert name in signature.parameters, name


def run() -> dict[str, object]:
    test_region_iou_perfect_and_empty_union()
    test_region_iou_empty_region_fails_closed()
    test_repair_region_covers_red_and_blue()
    test_distal_first_chain_omits_root_and_grows_prefixes()
    test_distal_first_chain_root_end_fails_closed()
    test_distal_first_chain_cycle_fails_closed()
    test_spinal_bones_get_small_step()
    test_keep_best_interim_prefers_shorter_on_tie()
    test_grow_stops_when_target_hit_without_unlocking_parent()
    test_grow_keeps_best_interim_not_last_worse_extension()
    test_local_axis_search_moves_rewarded_bone()
    test_local_axis_search_records_smaller_step_on_proximal_bone()
    test_config_and_adapter_plumb_blob_ik_knobs()
    return {"ok": True}


if __name__ == "__main__":
    print(run())
