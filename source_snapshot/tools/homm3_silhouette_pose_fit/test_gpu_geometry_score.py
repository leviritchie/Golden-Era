"""Cascade/one-bone shared geometry score: 0/1 occupancy is unchanged; floats are the gradient path."""
from __future__ import annotations

import torch

from gpu_geometry_score import chroma_quality, compose_geometry_score, occupancy_motion_quality, silhouette_and_depth_quality, srgb_rgb_to_lab_ab, unique_geometry_quality, unique_occupancy_quality
from roc_gpu_cascade_experiment import GpuCascadeConfig


def run() -> dict[str, object]:
    GpuCascadeConfig().validate()
    try:
        GpuCascadeConfig(exact_raster_enabled=False).validate()
        raise AssertionError("exact_raster_enabled=False must fail closed")
    except ValueError as exc:
        assert "exact_raster_enabled" in str(exc)
    try:
        GpuCascadeConfig(sdf_weight=0.12).validate()
        raise AssertionError("sdf_weight must stay out of cascade score")
    except ValueError as exc:
        assert "silhouette, depth, chroma, occupancy motion, and collision" in str(exc)
    GpuCascadeConfig(collision_enabled=False, collision_weight=0.0).validate()
    GpuCascadeConfig(
        motion_weight=1.0,
        silhouette_weight=0.0,
        depth_weight=0.0,
        chroma_weight=0.0,
    ).validate()
    try:
        GpuCascadeConfig(silhouette_weight=0.0).validate()
        raise AssertionError("all geometry weights zero must stay fail-closed")
    except ValueError as exc:
        assert "motion_weight" in str(exc)
    try:
        GpuCascadeConfig(collision_enabled=True, collision_weight=0.0).validate()
        raise AssertionError("collision_enabled with weight 0 must stay fail-closed")
    except ValueError as exc:
        assert "collision_weight must be positive" in str(exc)

    target_fg = torch.zeros((1, 8, 8), dtype=torch.bool)
    target_fg[0, 2:6, 2:6] = True
    pred_bool = target_fg.clone()
    pred_float = pred_bool.to(dtype=torch.float32)
    target_depth = torch.zeros((1, 8, 8), dtype=torch.float32)
    target_depth[0, 2:6, 2:6] = 0.4
    pred_depth = target_depth.clone()
    bool_terms = silhouette_and_depth_quality(
        target_foreground=target_fg,
        predicted_foreground=pred_bool,
        target_depth=target_depth,
        predicted_depth=pred_depth,
        depth_tolerance=0.08,
        depth_robust_delta=0.12,
    )
    float_terms = silhouette_and_depth_quality(
        target_foreground=target_fg,
        predicted_foreground=pred_float,
        target_depth=target_depth,
        predicted_depth=pred_depth,
        depth_tolerance=0.08,
        depth_robust_delta=0.12,
    )
    for key in ("silhouetteIoU", "depthQuality", "depthError"):
        delta = abs(float(bool_terms[key].item()) - float(float_terms[key].item()))
        assert delta < 1e-6, (key, delta, bool_terms[key], float_terms[key])

    occupancy = torch.zeros((1, 8, 8), dtype=torch.float32, requires_grad=True)
    scored = silhouette_and_depth_quality(
        target_foreground=target_fg.to(dtype=torch.float32),
        predicted_foreground=occupancy,
        target_depth=target_depth,
        predicted_depth=pred_depth,
        depth_tolerance=0.08,
        depth_robust_delta=0.12,
    )
    scored["silhouetteIoU"].sum().backward()
    assert occupancy.grad is not None
    assert float(occupancy.grad.abs().sum().item()) > 0.0

    ignore = torch.zeros((1, 8, 8), dtype=torch.float32)
    ignore[0, 2:6, 2:4] = 1.0
    pred_wrong_on_ignore = target_fg.clone()
    pred_wrong_on_ignore[0, 2:6, 2:4] = False
    pred_wrong_on_keep = target_fg.clone()
    pred_wrong_on_keep[0, 2:6, 4:6] = False
    ignored = silhouette_and_depth_quality(
        target_foreground=target_fg,
        predicted_foreground=pred_wrong_on_ignore,
        target_depth=target_depth,
        predicted_depth=pred_depth,
        depth_tolerance=0.08,
        depth_robust_delta=0.12,
        occupancy_ignore=ignore,
    )
    kept = silhouette_and_depth_quality(
        target_foreground=target_fg,
        predicted_foreground=pred_wrong_on_keep,
        target_depth=target_depth,
        predicted_depth=pred_depth,
        depth_tolerance=0.08,
        depth_robust_delta=0.12,
        occupancy_ignore=ignore,
    )
    full = silhouette_and_depth_quality(
        target_foreground=target_fg,
        predicted_foreground=target_fg,
        target_depth=target_depth,
        predicted_depth=pred_depth,
        depth_tolerance=0.08,
        depth_robust_delta=0.12,
        occupancy_ignore=ignore,
    )
    assert abs(float(ignored["silhouetteIoU"].item()) - float(full["silhouetteIoU"].item())) < 1e-6
    assert float(kept["silhouetteIoU"].item()) < float(full["silhouetteIoU"].item())
    assert float(ignored["depthError"].item()) > float(full["depthError"].item())

    from gpu_geometry_score import collision_error_above_slack
    raw = torch.tensor([0.05, 0.20], dtype=torch.float32)
    charged = collision_error_above_slack(raw, 0.12)
    assert abs(float(charged[0].item()) - 0.0) < 1e-6
    assert abs(float(charged[1].item()) - 0.08) < 1e-6

    green = torch.zeros((1, 8, 8, 3), dtype=torch.float32)
    green[..., 1] = 0.7
    green[..., 0] = 0.15
    green[..., 2] = 0.15
    ab = srgb_rgb_to_lab_ab(green)
    chroma_bool = chroma_quality(
        target_foreground=target_fg,
        predicted_foreground=pred_bool,
        target_ab=ab,
        predicted_ab=ab,
        chroma_tolerance=0.10,
        chroma_robust_delta=0.12,
        chroma_error_scale=80.0,
    )
    chroma_float = chroma_quality(
        target_foreground=target_fg,
        predicted_foreground=pred_float,
        target_ab=ab,
        predicted_ab=ab,
        chroma_tolerance=0.10,
        chroma_robust_delta=0.12,
        chroma_error_scale=80.0,
    )
    chroma_delta = abs(float(chroma_bool["chromaQuality"].item()) - float(chroma_float["chromaQuality"].item()))
    assert chroma_delta < 1e-6, chroma_delta

    far_pred = (ab + 80.0).detach().clone().requires_grad_(True)
    saturated = chroma_quality(
        target_foreground=target_fg,
        predicted_foreground=pred_float,
        target_ab=ab,
        predicted_ab=far_pred,
        chroma_tolerance=0.10,
        chroma_robust_delta=0.12,
        chroma_error_scale=80.0,
    )
    saturated["chromaQuality"].sum().backward()
    assert far_pred.grad is not None
    assert float(far_pred.grad.abs().sum().item()) > 0.0, "saturated Lab must still move Adam"

    black = torch.zeros((1, 8, 8, 3), dtype=torch.float32, requires_grad=True)
    black_ab = srgb_rgb_to_lab_ab(black)
    black_chroma = chroma_quality(
        target_foreground=target_fg,
        predicted_foreground=pred_float,
        target_ab=ab,
        predicted_ab=black_ab,
        chroma_tolerance=0.10,
        chroma_robust_delta=0.12,
        chroma_error_scale=80.0,
    )
    black_chroma["chromaQuality"].sum().backward()
    assert black.grad is not None
    assert bool(torch.isfinite(black.grad).all()), "sRGB black must not NaN Lab chroma grads"
    assert float(black.grad.abs().sum().item()) > 0.0, "sRGB black Lab must still move joint SGD"

    mix = compose_geometry_score(
        silhouette_iou=torch.tensor(0.50),
        depth_quality=torch.tensor(1.0),
        chroma_quality_value=torch.tensor(0.0),
        depth_weight=0.99,
        silhouette_weight=0.01,
        chroma_weight=0.0,
    )
    expected = (0.99 * 1.0 + 0.01 * 0.50) / 1.0
    assert abs(float(mix.item()) - expected) < 1e-6, mix

    body = torch.zeros((2, 8, 8), dtype=torch.float32)
    body[:, 2:6, 2:6] = 1.0
    walk_target = body.clone()
    walk_target[1, 2:6, 6:8] = 1.0
    shared_miss = unique_occupancy_quality(
        target_foreground=walk_target,
        predicted_foreground=body,
    )
    assert float(shared_miss["uniqueOccupancyQuality"][0]) > float(
        shared_miss["uniqueOccupancyQuality"][1]
    )
    explained = unique_occupancy_quality(
        target_foreground=walk_target,
        predicted_foreground=walk_target,
    )
    assert float(explained["uniqueOccupancyError"].max()) < 1e-6

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
    assert float(inside_blob["uniqueChromaError"][1]) > float(inside_blob["uniqueChromaError"][0])

    still = torch.zeros((2, 8, 8), dtype=torch.float32)
    still[:, 2:6, 2:6] = 1.0
    walked = still.clone()
    walked[1, 2:6, 6:8] = 1.0
    walked[1, 2:6, 2:4] = 0.0
    match = occupancy_motion_quality(
        target_foreground=walked,
        predicted_foreground=walked,
    )
    assert float(match["motionQuality"].min()) > 0.999
    frozen = occupancy_motion_quality(
        target_foreground=walked,
        predicted_foreground=still,
    )
    assert float(frozen["motionQuality"].max()) < 0.05
    opposite = still.clone()
    opposite[1, 2:6, 0:2] = 1.0
    opposite[1, 2:6, 2:4] = 0.0
    wrong_way = occupancy_motion_quality(
        target_foreground=walked,
        predicted_foreground=opposite,
    )
    assert float(wrong_way["motionQuality"].max()) < float(match["motionQuality"].min())
    packed = occupancy_motion_quality(
        target_foreground=torch.cat([walked, walked], dim=0),
        predicted_foreground=torch.cat([walked, still], dim=0),
        clip_frames=2,
    )
    assert float(packed["motionQuality"][0]) > 0.999
    assert float(packed["motionQuality"][2]) < 0.05
    pred = still.clone().requires_grad_(True)
    scored_motion = occupancy_motion_quality(
        target_foreground=walked,
        predicted_foreground=pred,
    )
    scored_motion["motionQuality"].sum().backward()
    assert pred.grad is not None
    assert float(pred.grad.abs().sum().item()) > 0.0
    mix_motion = compose_geometry_score(
        silhouette_iou=torch.tensor(0.50),
        depth_quality=torch.tensor(1.0),
        chroma_quality_value=torch.tensor(0.0),
        depth_weight=0.25,
        silhouette_weight=0.20,
        chroma_weight=0.20,
        motion_quality=torch.tensor(0.0),
        motion_weight=1.0,
    )
    expected_motion = (0.25 * 1.0 + 0.20 * 0.50 + 0.20 * 0.0 + 1.0 * 0.0) / 1.65
    assert abs(float(mix_motion.item()) - expected_motion) < 1e-6, mix_motion

    return {
        "ok": True,
        "iou": float(bool_terms["silhouetteIoU"].item()),
        "depthQuality": float(bool_terms["depthQuality"].item()),
        "chroma": float(chroma_bool["chromaQuality"].item()),
        "blackChroma": float(black_chroma["chromaQuality"].item()),
        "mix": float(mix.item()),
    }


if __name__ == "__main__":
    print(run())
