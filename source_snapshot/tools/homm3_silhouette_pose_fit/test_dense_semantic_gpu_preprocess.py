"""GPU DINOv3 preprocess stays on CUDA and matches the PIL processor path."""
from __future__ import annotations

import torch

from dense_semantic_features import (
    DEFAULT_DINO_MODEL,
    DenseFeatureScorer,
    _select_spatial_tokens,
    dense_semantic_raster_scale_for_proxy,
    l2_normalize_tokens_torch,
    load_dense_image_processor,
    local_window_cosine_distances_torch,
    rgb_hwc_batch_to_uint8_images,
    same_cuda_device,
)
from roc_gpu_cascade_experiment import rgb_hwc_batch_to_pil_images


def run() -> dict[str, object]:
    processor = load_dense_image_processor(DEFAULT_DINO_MODEL, family="dino", local_files_only=True)
    derived = dense_semantic_raster_scale_for_proxy((96, 86), processor)
    if derived != 3:
        raise AssertionError(f"DINOv3 224 vs 96x86 proxy must derive scale 3, got {derived}")

    if not torch.cuda.is_available():
        raise RuntimeError("dense GPU preprocess test requires CUDA")

    torch.manual_seed(0)
    rgb = torch.rand(4, 48, 40, 3, device="cuda")
    pil_images = rgb_hwc_batch_to_pil_images(rgb)
    pil_pixels = processor(images=pil_images, return_tensors="pt")["pixel_values"]
    gpu_frames = rgb_hwc_batch_to_uint8_images(rgb)
    gpu_pixels = processor(images=gpu_frames, return_tensors="pt")["pixel_values"]
    if gpu_pixels.device.type != "cuda":
        raise RuntimeError(f"processor moved GPU RGB onto {gpu_pixels.device}")
    delta = float((gpu_pixels.float().cpu() - pil_pixels.float()).abs().max())
    if delta > 2e-4:
        raise AssertionError(f"GPU processor pixels diverged from PIL: max delta {delta}")

    if not same_cuda_device("cuda", "cuda:0"):
        raise AssertionError("bare cuda must match cuda:0 on the current GPU")
    if same_cuda_device("cpu", "cuda:0"):
        raise AssertionError("cpu must not match a CUDA device")

    scorer = DenseFeatureScorer(
        DEFAULT_DINO_MODEL,
        family="dino",
        device="cuda",
        local_files_only=True,
    )
    gpu_grids = scorer.extract_layers_from_rgb_hwc(rgb[:2])
    pil_grids = scorer.extract_layers(pil_images[:2])
    token_delta = float((gpu_grids["last"].float() - pil_grids["last"].float()).abs().max())
    # fp16 encode vs a second fp16 encode of PIL-preprocessed pixels should stay close.
    if token_delta > 5e-3:
        raise AssertionError(f"GPU RGB extract diverged from PIL extract: max delta {token_delta}")

    pixel_values = gpu_pixels[:2].to(scorer.device)
    vision_model = getattr(scorer.model, "vision_model", scorer.model)
    with torch.inference_mode():
        fp32_out = vision_model(
            pixel_values=pixel_values.float(),
            return_dict=True,
        )
        with torch.autocast(device_type="cuda", dtype=torch.float16):
            fp16_out = vision_model(
                pixel_values=pixel_values.float(),
                return_dict=True,
            )

    fp32_grid = l2_normalize_tokens_torch(
        _select_spatial_tokens(
            fp32_out,
            model=scorer.model,
            family=scorer.family,
            feature_layer="last",
            prefix_tokens=scorer.prefix_tokens,
            grid_shape=scorer.grid_shape,
        )[0]
    )
    fp16_grid = l2_normalize_tokens_torch(
        _select_spatial_tokens(
            fp16_out,
            model=scorer.model,
            family=scorer.family,
            feature_layer="last",
            prefix_tokens=scorer.prefix_tokens,
            grid_shape=scorer.grid_shape,
        )[0]
    )
    flipped = fp32_grid.flip(0)
    fp32_distance = local_window_cosine_distances_torch(fp32_grid, flipped, window_radius=1, position_weight=1.0)
    fp16_distance = local_window_cosine_distances_torch(fp16_grid, fp16_grid.flip(0), window_radius=1, position_weight=1.0)
    distance_delta = float((fp32_distance - fp16_distance).abs().max())
    if distance_delta > 5e-3:
        raise AssertionError(f"fp16 vs fp32 local-window distance delta {distance_delta} is too large")

    return {
        "ok": True,
        "derivedRasterScale": derived,
        "processorPixelDelta": delta,
        "tokenDelta": token_delta,
        "fp16DistanceDelta": distance_delta,
        "keepTieNote": "joint_keep_min_improvement=1e-6 can still flip vs pure fp32",
    }


if __name__ == "__main__":
    print(run())
