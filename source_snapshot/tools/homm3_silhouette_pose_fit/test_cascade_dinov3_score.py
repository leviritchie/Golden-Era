"""Cascade dinov3_dense score_mode: one flag, no geometry mix-in."""
from __future__ import annotations

import inspect

import numpy as np
from PIL import Image

from gpu_cascade_delivery import clip_result_matches_current_keep
from gpu_geometry_score import gpu_score_raster_resolution
from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
from roc_gpu_cascade_experiment import (
    GpuCascadeConfig,
    GpuCascadeExperiment,
    cascade_live_preview_depth_panel,
    dense_semantic_quality_from_distance,
    dinov3_dense_cascade_config,
    rgb_hwc_batch_to_pil_images,
    score_dense_semantic_rgb_batch,
)


class _FakeDenseScorer:
    feature_layers = ("last",)

    def extract_layers(self, images):
        import torch

        grids = []
        for image in images:
            pixels = np.asarray(image, dtype=np.float32) / 255.0
            mean = pixels.reshape(-1, 3).mean(axis=0)
            grid = np.zeros((2, 2, 8), dtype=np.float32)
            grid[..., :3] = mean
            grids.append(torch.from_numpy(grid))
        return {"last": torch.stack(grids, dim=0)}

    def extract_layers_from_rgb_hwc(self, rgb):
        import torch

        if isinstance(rgb, (list, tuple)):
            frames = list(rgb)
        else:
            frames = [rgb[index] for index in range(int(rgb.shape[0]))]
        grids = []
        for frame in frames:
            mean = frame.float().reshape(-1, 3).mean(dim=0)
            grid = torch.zeros((2, 2, 8), dtype=torch.float32, device=frame.device)
            grid[..., :3] = mean
            grids.append(grid)
        return {"last": torch.stack(grids, dim=0)}

    def extract_layers_from_rgb_hwc_autograd(self, rgb):
        if not bool(rgb.requires_grad):
            raise RuntimeError("fake autograd RGB is detached")
        return self.extract_layers_from_rgb_hwc(rgb)

    def score_grid_layers_batch_mean_torch(
        self,
        target_grids,
        candidate_grids,
        *,
        window_radius: int = 1,
        position_weight: float = 0.0,
    ):
        import torch

        target = target_grids["last"]
        candidate = candidate_grids["last"]
        if target.ndim == 3:
            target = target.unsqueeze(0)
        batch = int(candidate.shape[0])
        if int(target.shape[0]) == 1 and batch > 1:
            target = target.expand(batch, -1, -1, -1)
        elif int(target.shape[0]) != batch:
            raise ValueError("fake scorer target batch must be 1 or match candidates")
        target_mean = target[..., :3].reshape(batch, -1, 3).mean(dim=1)
        candidate_mean = candidate[..., :3].reshape(batch, -1, 3).mean(dim=1)
        return torch.linalg.vector_norm(candidate_mean - target_mean, dim=1)

    def score_grid_layers_batch_mean(
        self,
        target_grids,
        candidate_grids,
        *,
        window_radius: int = 1,
        position_weight: float = 0.0,
    ):
        distances = self.score_grid_layers_batch_mean_torch(
            target_grids,
            candidate_grids,
            window_radius=window_radius,
            position_weight=position_weight,
        )
        return [
            (float(value), {"last": float(value)})
            for value in distances.detach().cpu().tolist()
        ]


def run() -> dict[str, object]:
    import torch

    autograd_branch = {
        "joint_solver_mode": "branch_vector",
        "chain_space_enabled": True,
        "chain_space_mode": "branch_trust",
        "dense_semantic_autograd_enabled": True,
        "dense_semantic_subject_crop": False,
        "root_search_enabled": False,
        "root_rotation_defer_camera_up": False,
        "root_refit_after_base_enabled": False,
        "joint_adaptive_step_enabled": False,
        "joint_temporal_consensus_enabled": False,
        "base_pose_enabled": False,
        "mid_pose_enabled": False,
        "branch_rescue_enabled": False,
        "physics_smooth_enabled": False,
        "fine_root_enabled": False,
        "skip_tiny_bones": False,
        "fine_only_leaf_length_frac": 0.0,
        "include_unlisted_search_bones": True,
        "articulated_iterations": 0,
        "fine_iterations": 0,
    }

    default = GpuCascadeConfig()
    assert default.score_mode == "geometry"
    default.validate()
    dinov3_dense_cascade_config().validate()

    try:
        GpuCascadeConfig(score_mode="dinov3_dense").validate()
        raise AssertionError("default geometry weights must not mix into dinov3_dense")
    except ValueError as exc:
        text = str(exc)
        assert all(name in text for name in ("silhouette", "depth", "chroma"))

    try:
        dinov3_dense_cascade_config(chroma_weight=0.5).validate()
        raise AssertionError("chroma mix-in must fail closed")
    except ValueError as exc:
        assert "chroma" in str(exc)

    try:
        dinov3_dense_cascade_config(collision_enabled=True, collision_weight=0.35).validate()
        raise AssertionError("collision mix-in must fail closed")
    except ValueError as exc:
        assert "collision" in str(exc)

    try:
        dinov3_dense_cascade_config(joint_unique_gain_weight=0.35).validate()
        raise AssertionError("unique occupancy mix-in must fail closed")
    except ValueError as exc:
        assert "unique occupancy" in str(exc)

    try:
        dinov3_dense_cascade_config(root_iterations=20).validate()
        raise AssertionError("Adam root must fail closed for dinov3_dense")
    except ValueError as exc:
        assert "root_iterations=0" in str(exc)

    try:
        dinov3_dense_cascade_config(gradient_ladder_enabled=True).validate()
        raise AssertionError("gradient ladder must fail closed for dinov3_dense")
    except ValueError as exc:
        assert "gradient ladder" in str(exc)

    try:
        dinov3_dense_cascade_config(chain_space_enabled=True).validate()
        raise AssertionError("chain space must fail closed for dinov3_dense")
    except ValueError as exc:
        text = str(exc).lower()
        assert "chain" in text or "dinov3" in text
    dinov3_dense_cascade_config(**autograd_branch).validate()
    try:
        dinov3_dense_cascade_config(
            joint_solver_mode="branch_vector",
            dense_semantic_autograd_enabled=True,
            chain_space_enabled=False,
        ).validate()
        raise AssertionError("DINOv3 autograd without branch space must fail closed")
    except ValueError as exc:
        assert "chain_space_enabled" in str(exc)

    try:
        dinov3_dense_cascade_config(ik_enabled=True).validate()
        raise AssertionError("IK mix-in must fail closed for dinov3_dense")
    except ValueError as exc:
        assert "IK" in str(exc)

    try:
        dinov3_dense_cascade_config(bone_order_mode="error_driven").validate()
        raise AssertionError("error-driven bone order must fail closed")
    except ValueError as exc:
        assert "bone order" in str(exc)

    try:
        dinov3_dense_cascade_config(
            dense_semantic_model_id="google/siglip2-base-patch16-512"
        ).validate()
        raise AssertionError("SigLIP dense must not count as DINOv3")
    except ValueError as exc:
        assert "DINO-family" in str(exc) or "DINOv3" in str(exc)

    try:
        dinov3_dense_cascade_config(
            dense_semantic_model_id="facebook/dinov2-base"
        ).validate()
        raise AssertionError("DINOv2 must not count as DINOv3")
    except ValueError as exc:
        assert "DINOv3" in str(exc)

    try:
        dinov3_dense_cascade_config(score_mode="dino_plus_chroma").validate()
        raise AssertionError("unknown score_mode must fail closed")
    except ValueError as exc:
        assert "score_mode" in str(exc)

    assert dense_semantic_quality_from_distance(0.25) == 0.75
    rgb = torch.zeros((2, 4, 4, 3), dtype=torch.float32)
    rgb[0, :, :, 0] = 1.0
    rgb[1, :, :, 1] = 1.0
    images = rgb_hwc_batch_to_pil_images(rgb)
    assert [image.mode for image in images] == ["RGB", "RGB"]
    assert images[0].getpixel((0, 0)) == (255, 0, 0)
    assert images[1].getpixel((0, 0)) == (0, 255, 0)

    scorer = _FakeDenseScorer()
    target_grid = scorer.extract_layers([images[0]])
    qualities = score_dense_semantic_rgb_batch(
        scorer,
        target_grids_by_frame=[{"last": target_grid["last"]}],
        predicted_rgb=rgb,
        frame_positions=torch.zeros((2,), dtype=torch.long),
        batch_size=2,
        window_radius=1,
        position_weight=1.0,
    )
    assert float(qualities[0].item()) > float(qualities[1].item()), qualities
    try:
        score_dense_semantic_rgb_batch(
            scorer,
            target_grids_by_frame=[{"last": target_grid["last"]}],
            predicted_rgb=rgb,
            frame_positions=torch.zeros((1,), dtype=torch.long),
            batch_size=2,
            window_radius=1,
            position_weight=1.0,
        )
        raise AssertionError("one frame_position for two poses must fail closed")
    except ValueError as exc:
        assert "frame_positions" in str(exc)
    try:
        score_dense_semantic_rgb_batch(
            scorer,
            target_grids_by_frame=[{"last": target_grid["last"]}],
            predicted_rgb=rgb,
            frame_positions=torch.zeros((2,), dtype=torch.long),
            batch_size=2,
            window_radius=1,
            position_weight=1.0,
            crop_fn=lambda image: image,
        )
        raise AssertionError("PIL crop_fn must fail closed")
    except ValueError as exc:
        assert "crop_fn" in str(exc)

    mixed_rgb = torch.zeros((2, 4, 4, 3), dtype=torch.float32)
    mixed_rgb[0, :, :, 0] = 1.0
    mixed_rgb[1, :, :, 1] = 1.0
    green_target = scorer.extract_layers_from_rgb_hwc(mixed_rgb[1:2])
    mixed_qualities = score_dense_semantic_rgb_batch(
        scorer,
        target_grids_by_frame=[
            {"last": target_grid["last"]},
            {"last": green_target["last"]},
        ],
        predicted_rgb=mixed_rgb,
        frame_positions=torch.tensor([0, 1], dtype=torch.long),
        batch_size=2,
        window_radius=1,
        position_weight=1.0,
    )
    assert float(mixed_qualities[0].item()) > 0.99, mixed_qualities
    assert float(mixed_qualities[1].item()) > 0.99, mixed_qualities

    autograd_rgb = mixed_rgb.clone().requires_grad_(True)
    autograd_qualities = score_dense_semantic_rgb_batch(
        scorer,
        target_grids_by_frame=[
            {"last": target_grid["last"].detach()},
            {"last": target_grid["last"].detach()},
        ],
        predicted_rgb=autograd_rgb,
        frame_positions=torch.tensor([0, 1], dtype=torch.long),
        batch_size=1,
        window_radius=1,
        position_weight=1.0,
        autograd_enabled=True,
    )
    autograd_qualities.sum().backward()
    assert autograd_rgb.grad is not None
    assert bool(torch.isfinite(autograd_rgb.grad).all())
    assert float(autograd_rgb.grad.abs().sum()) > 0.0

    # The production branch solver releases each ViT graph after a frame
    # microbatch, then backpropagates the temporal term once across the clip.
    frame_count = 5
    seed_pose = torch.linspace(-0.7, 0.8, frame_count * 3).reshape(frame_count, 3)
    target_rgb = torch.linspace(0.1, 0.9, frame_count * 3).reshape(frame_count, 1, 1, 3)
    target_rgb = target_rgb.expand(-1, 4, 4, -1).contiguous()
    target_grids_by_frame = []
    for frame_index in range(frame_count):
        grids = scorer.extract_layers_from_rgb_hwc(target_rgb[frame_index : frame_index + 1])
        target_grids_by_frame.append({"last": grids["last"].detach()})

    full_pose = seed_pose.clone().requires_grad_(True)
    full_rgb = torch.sigmoid(full_pose[:, None, None, :]).expand(-1, 4, 4, -1)
    full_quality = score_dense_semantic_rgb_batch(
        scorer,
        target_grids_by_frame=target_grids_by_frame,
        predicted_rgb=full_rgb,
        frame_positions=torch.arange(frame_count),
        batch_size=frame_count,
        window_radius=1,
        position_weight=1.0,
        autograd_enabled=True,
    ).mean()
    full_temporal = (full_pose[1:] - full_pose[:-1]).square().mean() * 0.17
    (full_quality - full_temporal).backward()
    full_gradient = full_pose.grad.detach().clone()

    chunked_pose = seed_pose.clone().requires_grad_(True)
    for start in range(0, frame_count, 2):
        stop = min(frame_count, start + 2)
        chunk_rgb = torch.sigmoid(chunked_pose[start:stop, None, None, :]).expand(
            -1, 4, 4, -1
        )
        chunk_quality = score_dense_semantic_rgb_batch(
            scorer,
            target_grids_by_frame=target_grids_by_frame,
            predicted_rgb=chunk_rgb,
            frame_positions=torch.arange(start, stop),
            batch_size=2,
            window_radius=1,
            position_weight=1.0,
            autograd_enabled=True,
        )
        (chunk_quality.sum() / float(frame_count)).backward()
    chunked_temporal = (chunked_pose[1:] - chunked_pose[:-1]).square().mean() * 0.17
    (-chunked_temporal).backward()
    chunked_gradient = chunked_pose.grad.detach().clone()
    assert bool(torch.isfinite(chunked_gradient).all())
    assert float(chunked_gradient.abs().sum()) > 0.0
    assert torch.allclose(chunked_gradient, full_gradient, atol=1e-7, rtol=1e-6), (
        chunked_gradient - full_gradient
    ).abs().max()

    from dense_semantic_features import dense_semantic_raster_scale_for_proxy

    class _Size:
        height = 224
        width = 224

    class _Processor:
        size = _Size()
        do_resize = True
        do_pad = False
        do_center_crop = False
        process_image = staticmethod(lambda image: image)

    derived_scale = dense_semantic_raster_scale_for_proxy((96, 86), _Processor())
    assert derived_scale == 3, derived_scale
    assert gpu_score_raster_resolution(
        (96, 86),
        chroma_weight=0.0,
        chroma_resolution=None,
        chroma_scale=derived_scale,
        rgb_upsample=True,
    ) == (288, 258)

    signature = inspect.signature(run_gpu_depth_fit_from_hybrid_config)
    for name in (
        "score_mode",
        "dense_semantic_model_id",
        "dense_semantic_raster_scale",
        "dense_semantic_autograd_enabled",
        "joint_solver_mode",
        "root_search_enabled",
        "joint_keep_still_sprite_lock",
        "joint_keep_still_sprite_rgb_mad",
        "joint_keep_sprite_change_gate",
        "joint_keep_sprite_change_weight",
        "joint_keep_sprite_change_slack",
    ):
        assert name in signature.parameters, name

    assert default.joint_keep_still_sprite_lock is False
    assert default.joint_keep_sprite_change_gate is False
    GpuCascadeConfig(joint_keep_still_sprite_lock=True).validate()
    try:
        GpuCascadeConfig(
            joint_keep_still_sprite_lock=True,
            joint_keep_still_sprite_rgb_mad=0.0,
        ).validate()
        raise AssertionError("zero still-sprite MAD must fail closed")
    except ValueError as exc:
        assert "joint_keep_still_sprite_rgb_mad" in str(exc)

    keep_payload = {
        "solver": "cascade",
        "config": {
            "joint_collision_positive_abs_slack": 0.12,
            "joint_temporal_consensus_enabled": True,
            "joint_temporal_consensus_bidirectional": True,
            "joint_temporal_consensus_idle_end": True,
            "joint_temporal_consensus_independent_passes": True,
            "joint_temporal_consensus_whole_pose": True,
            "root_rotation_camera_up_limit_deg": 45.0,
            "root_rotation_defer_camera_up": True,
            "base_pose_iterations": 2,
            "mid_pose_enabled": True,
            "fine_iterations": 2,
            "physics_smooth_enabled": True,
            "score_mode": "dinov3_dense",
        },
        "poses": {"0": {"Bone_000": {"x": 0.1}}},
    }
    assert clip_result_matches_current_keep(keep_payload) is False

    mask = np.ones((6, 6), dtype=np.float32)
    placeholder = cascade_live_preview_depth_panel(None, mask, uses_rgb=True)
    assert placeholder.shape == mask.shape
    assert float(placeholder.max()) == 0.0
    refresh_src = inspect.getsource(GpuCascadeExperiment._refresh_live_preview)
    assert "cascade_live_preview_depth_panel" in refresh_src
    assert "loaded target depth maps" not in refresh_src

    return {
        "ok": True,
        "matchQuality": float(qualities[0].item()),
        "mismatchQuality": float(qualities[1].item()),
    }


if __name__ == "__main__":
    print(run())
