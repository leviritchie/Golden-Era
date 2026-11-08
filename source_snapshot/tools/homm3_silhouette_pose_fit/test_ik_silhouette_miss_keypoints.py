"""Tests for silhouette-miss IK keypoint derivation."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ik_silhouette_miss_keypoints import (
    assign_joint_by_influence,
    build_frame_miss_keypoints,
    component_extremal_tip,
    excess_predicted_silhouette,
    label_binary_components,
    pair_silhouette_misses,
)


def _blank(size: int = 32) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    target_mask = np.zeros((size, size), dtype=np.float32)
    predicted_mask = np.zeros((size, size), dtype=np.float32)
    target_depth = np.zeros((size, size), dtype=np.float32)
    predicted_depth = np.zeros((size, size), dtype=np.float32)
    return target_mask, predicted_mask, target_depth, predicted_depth


def test_excess_and_missing_are_complements_on_disagreement() -> None:
    target_mask, predicted_mask, _, _ = _blank()
    target_mask[10:20, 10:20] = 1.0
    predicted_mask[10:20, 14:24] = 1.0
    missing = target_mask > 0.5
    missing &= ~(predicted_mask > 0.5)
    excess = excess_predicted_silhouette(target_mask, predicted_mask, threshold=0.5)
    assert int(np.count_nonzero(missing)) > 0
    assert int(np.count_nonzero(excess)) > 0
    assert not np.any(missing & excess)


def test_depth_gate_pairs_nearby_layers_only() -> None:
    size = 48
    target_mask, predicted_mask, target_depth, predicted_depth = _blank(size)
    target_mask[8:18, 8:18] = 1.0
    target_mask[30:40, 30:40] = 1.0
    predicted_mask[8:18, 14:24] = 1.0
    predicted_mask[30:40, 24:34] = 1.0
    target_depth[8:18, 8:18] = 0.25
    target_depth[30:40, 30:40] = 0.80
    predicted_depth[8:18, 14:24] = 0.25
    predicted_depth[30:40, 24:34] = 0.25

    pairs_loose = pair_silhouette_misses(
        target_mask,
        predicted_mask,
        target_depth,
        predicted_depth,
        depth_tolerance=0.2,
        min_component_area=4,
    )
    pairs_tight = pair_silhouette_misses(
        target_mask,
        predicted_mask,
        target_depth,
        predicted_depth,
        depth_tolerance=0.05,
        min_component_area=4,
    )
    assert len(pairs_loose) >= 1
    assert len(pairs_tight) <= len(pairs_loose)


def test_pair_ranking_prefers_larger_combined_area() -> None:
    size = 64
    target_mask, predicted_mask, target_depth, predicted_depth = _blank(size)
    target_mask[8:14, 8:14] = 1.0
    predicted_mask[8:14, 12:18] = 1.0
    target_mask[40:52, 40:52] = 1.0
    predicted_mask[40:52, 48:60] = 1.0
    target_depth[8:14, 8:14] = 0.3
    target_depth[40:52, 40:52] = 0.3
    predicted_depth[8:14, 12:18] = 0.3
    predicted_depth[40:52, 48:60] = 0.3

    pairs = pair_silhouette_misses(
        target_mask,
        predicted_mask,
        target_depth,
        predicted_depth,
        min_component_area=4,
        max_pairs=1,
        max_tip_distance_px=80.0,
        max_centroid_distance_px=80.0,
        max_area_ratio=8.0,
    )
    assert len(pairs) == 1
    assert pairs[0].combined_area > 100


def test_area_ratio_gate_rejects_mismatched_blob_sizes() -> None:
    size = 64
    target_mask, predicted_mask, target_depth, predicted_depth = _blank(size)
    target_mask[10:30, 10:18] = 1.0
    predicted_mask[10:14, 18:24] = 1.0
    target_depth[10:30, 10:18] = 0.4
    predicted_depth[10:14, 18:24] = 0.42
    loose = pair_silhouette_misses(
        target_mask,
        predicted_mask,
        target_depth,
        predicted_depth,
        min_component_area=4,
        max_area_ratio=8.0,
        max_tip_distance_px=80.0,
        max_centroid_distance_px=80.0,
        min_displacement_alignment=0.0,
    )
    strict = pair_silhouette_misses(
        target_mask,
        predicted_mask,
        target_depth,
        predicted_depth,
        min_component_area=4,
        max_area_ratio=2.0,
        max_tip_distance_px=80.0,
        max_centroid_distance_px=80.0,
        min_displacement_alignment=0.0,
    )
    assert len(loose) == 1
    assert len(strict) == 0


def test_component_extremal_tip_prefers_farther_missing_point() -> None:
    mask = np.zeros((20, 20), dtype=bool)
    mask[10, 5:15] = True
    labels, count = label_binary_components(mask)
    assert count == 1
    tip = component_extremal_tip(labels, 1, reference_xy=(12.0, 10.0))
    assert tip[0] in {5.0, 14.0}


def test_assign_joint_by_influence_prefers_distal_bone() -> None:
    assigned = assign_joint_by_influence(
        {"Shoulder": 2.0, "Hand": 1.9},
        allowed=("Shoulder", "Hand"),
        node_depth=lambda name: 2 if name == "Shoulder" else 5,
    )
    assert assigned == "Hand"


def test_build_frame_miss_keypoints_uses_assign_callback() -> None:
    size = 40
    target_mask, predicted_mask, target_depth, predicted_depth = _blank(size)
    target_mask[10:22, 6:14] = 1.0
    predicted_mask[10:22, 12:20] = 1.0
    target_depth[10:22, 6:14] = 0.4
    predicted_depth[10:22, 12:20] = 0.42
    joint_xy = {
        "RWrist": (16.0, 16.0),
        "WeaponTip": (18.0, 16.0),
        "LAnkle": (30.0, 30.0),
    }

    def assign(_pair):
        return "WeaponTip"

    keypoints, reports = build_frame_miss_keypoints(
        target_mask,
        predicted_mask,
        target_depth,
        predicted_depth,
        joint_xy,
        primary_joints=("RWrist", "WeaponTip", "LAnkle"),
        min_component_area=4,
        assign_joint=assign,
    )
    assert reports
    assert reports[0].joint_name == "WeaponTip"
    assert "WeaponTip" in keypoints


def _crusader_idle_start_move_live(root: Path) -> dict[str, Path]:
    from materialize_rife_source_frames import require_idle_leading_source_manifest

    pilot = root / "artifacts/pose_picker_runs/h3_crusader/idle_start_move"
    frames = pilot / "frames_def12_nn_idle_start_move"
    culled = pilot / "frames_def12_nn_idle_start_move_shadow_culled"
    depth = pilot / "frames_def12_nn_idle_start_move_depth_vda"
    camera = pilot / "roc_sprite_camera_fit.json"
    groups = require_idle_leading_source_manifest(frames / "def_frames.json")
    if groups != (2, 20, 0):
        raise AssertionError(f"idle_start_move must be idle then start then walk: {groups}")
    for path in (culled / "00.png", culled / "10.png", depth / "00.png", depth / "10.png", camera):
        if not path.is_file():
            raise FileNotFoundError(path)
    return {
        "pilot": pilot,
        "frames": frames,
        "culled": culled,
        "depth": depth,
        "camera": camera,
    }


def test_project_search_bones_xy_non_empty() -> None:
    from pathlib import Path

    from roc_gpu_cascade_experiment import (
        GpuCascadeConfig,
        GpuCascadeExperiment,
        project_search_bones_xy,
    )

    root = Path(r"V:/Games/Olden Era Playtest Tweak")
    live = _crusader_idle_start_move_live(root)
    cfg = GpuCascadeConfig(
        depth_target_dir=str(live["depth"]),
        ik_keypoints_source="silhouette_miss",
    )
    exp = GpuCascadeExperiment(
        src_glb=root / "artifacts/meshy_downloads/h3_crusader_smartrigged_rigidized.glb",
        camera_fit=live["camera"],
        target_frame_dir=live["culled"],
        frame_indices=(0, 10),
        config=cfg,
    )
    import torch

    bone_vectors = torch.zeros((2, len(exp.asset.nodes), 3), device=exp.device)
    root_t = torch.zeros((2, 3), device=exp.device)
    root_r = torch.zeros((2, 3), device=exp.device)
    joint_xy = project_search_bones_xy(
        exp, bone_vectors, root_t, root_r, frame_position=0
    )
    assert joint_xy
    assert all(name.startswith("Bone_") for name in joint_xy)


def test_compute_search_bone_influence_in_mask_runs() -> None:
    from pathlib import Path

    import torch

    from roc_gpu_cascade_experiment import (
        GpuCascadeConfig,
        GpuCascadeExperiment,
        compute_search_bone_influence_in_mask,
        derive_ik_keypoints_from_silhouette_misses,
    )

    root = Path(r"V:/Games/Olden Era Playtest Tweak")
    live = _crusader_idle_start_move_live(root)
    cfg = GpuCascadeConfig(
        depth_target_dir=str(live["depth"]),
        ik_keypoints_source="silhouette_miss",
        ik_miss_min_component_area=4,
    )
    exp = GpuCascadeExperiment(
        src_glb=root / "artifacts/meshy_downloads/h3_crusader_smartrigged_rigidized.glb",
        camera_fit=live["camera"],
        target_frame_dir=live["culled"],
        frame_indices=(0,),
        config=cfg,
    )
    bone_vectors = torch.zeros((1, len(exp.asset.nodes), 3), device=exp.device)
    root_t = torch.zeros((1, 3), device=exp.device)
    root_r = torch.zeros((1, 3), device=exp.device)
    region = np.zeros((int(cfg.resolution[1]), int(cfg.resolution[0])), dtype=bool)
    region[40:80, 40:80] = True
    influence = compute_search_bone_influence_in_mask(
        exp,
        bone_vectors,
        root_t,
        root_r,
        frame_position=0,
        region_mask=region,
    )
    assert isinstance(influence, dict)
    keypoints = derive_ik_keypoints_from_silhouette_misses(
        exp,
        bone_vectors,
        root_t,
        root_r,
    )
    assert isinstance(keypoints, dict)


def run() -> dict[str, object]:
    test_excess_and_missing_are_complements_on_disagreement()
    test_depth_gate_pairs_nearby_layers_only()
    test_pair_ranking_prefers_larger_combined_area()
    test_area_ratio_gate_rejects_mismatched_blob_sizes()
    test_component_extremal_tip_prefers_farther_missing_point()
    test_assign_joint_by_influence_prefers_distal_bone()
    test_build_frame_miss_keypoints_uses_assign_callback()
    test_project_search_bones_xy_non_empty()
    test_compute_search_bone_influence_in_mask_runs()
    return {"ok": True}


if __name__ == "__main__":
    print(run())
