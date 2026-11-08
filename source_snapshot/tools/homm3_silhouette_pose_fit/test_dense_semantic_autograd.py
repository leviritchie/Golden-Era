"""Differentiable DINOv3 preprocessing and frozen-encoder contract."""
from __future__ import annotations

from types import SimpleNamespace

import torch

from dense_semantic_features import (
    DEFAULT_DINO_MODEL,
    DenseFeatureScorer,
    _freeze_dense_model_parameters,
    assert_processor_autograd_rgb_supported,
    load_dense_image_processor,
    preprocess_rgb_hwc_autograd,
)


class DINOv3ViTImageProcessor:
    image_processor_type = "DINOv3ViTImageProcessor"
    size = {"height": 16, "width": 16}
    resample = 2
    do_resize = True
    do_center_crop = False
    do_pad = False
    do_rescale = True
    rescale_factor = 1.0 / 255.0
    do_normalize = True
    image_mean = (0.485, 0.456, 0.406)
    image_std = (0.229, 0.224, 0.225)
    data_format = "channels_first"


class _FakeVisionModel(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.projection = torch.nn.Conv2d(3, 6, kernel_size=1, bias=False)

    def forward(
        self,
        pixel_values: torch.Tensor,
        *,
        output_hidden_states: bool,
        return_dict: bool,
    ) -> SimpleNamespace:
        del output_hidden_states
        if not return_dict:
            raise AssertionError("fake vision model requires return_dict=True")
        features = self.projection(pixel_values)
        features = torch.nn.functional.adaptive_avg_pool2d(features, (4, 4))
        tokens = features.flatten(2).transpose(1, 2)
        return SimpleNamespace(last_hidden_state=tokens)


def _reference_preprocess(rgb: torch.Tensor, processor: object) -> torch.Tensor:
    """Independent torchvision-style reference used by the HF backend."""

    values = rgb.permute(0, 3, 1, 2).contiguous()
    values = torch.nn.functional.interpolate(
        values,
        size=(16, 16),
        mode="bilinear",
        align_corners=False,
        antialias=True,
    )
    mean = values.new_tensor(getattr(processor, "image_mean")).view(1, 3, 1, 1)
    std = values.new_tensor(getattr(processor, "image_std")).view(1, 3, 1, 1)
    return (values - mean) / std


def _fake_scorer(device: torch.device, processor: object) -> DenseFeatureScorer:
    scorer = DenseFeatureScorer.__new__(DenseFeatureScorer)
    scorer.device = device
    scorer.model_id = "fake/dinov3"
    scorer.family = "dino"
    scorer.feature_layers = ("last",)
    scorer.feature_layer = "last"
    scorer.prefix_tokens = 0
    scorer.grid_shape = (4, 4)
    scorer.torch = torch
    scorer.processor = processor
    scorer.model = _freeze_dense_model_parameters(_FakeVisionModel().to(device))
    return scorer


def run() -> dict[str, object]:
    processor = DINOv3ViTImageProcessor()
    assert_processor_autograd_rgb_supported(processor)

    # Exact 8-bit fractions remove quantization as a variable when comparing
    # the continuous path with the processor's established uint8 semantics.
    generator = torch.Generator(device="cpu").manual_seed(17)
    quantized = torch.randint(0, 256, (2, 11, 13, 3), generator=generator)
    rgb = quantized.float().div(255.0).requires_grad_(True)
    actual = preprocess_rgb_hwc_autograd(rgb, processor)
    expected = _reference_preprocess(rgb, processor)
    parity_delta = float((actual - expected).abs().max().item())
    if parity_delta > 1e-6:
        raise AssertionError(f"autograd preprocess parity delta {parity_delta} exceeds 1e-6")

    official_processor = load_dense_image_processor(
        DEFAULT_DINO_MODEL,
        family="dino",
        local_files_only=True,
    )
    official_pixels = official_processor(
        images=[quantized[index].to(torch.uint8) for index in range(2)],
        return_tensors="pt",
    )["pixel_values"]
    differentiable_pixels = preprocess_rgb_hwc_autograd(rgb, official_processor)
    official_parity_delta = float(
        (differentiable_pixels - official_pixels).abs().max().item()
    )
    if official_parity_delta > 2e-6:
        raise AssertionError(
            "autograd preprocess diverged from the cached official DINOv3 "
            f"processor: max delta {official_parity_delta}"
        )
    actual.square().mean().backward()
    if rgb.grad is None or not bool(torch.isfinite(rgb.grad).all().item()):
        raise AssertionError("preprocess did not produce finite RGB gradients")
    if float(rgb.grad.abs().sum().item()) <= 0.0:
        raise AssertionError("preprocess RGB gradient is zero")

    bad_processor = DINOv3ViTImageProcessor()
    bad_processor.rescale_factor = 1.0
    try:
        assert_processor_autograd_rgb_supported(bad_processor)
        raise AssertionError("unsupported rescale factor must fail closed")
    except ValueError as exc:
        if "rescale_factor=1/255" not in str(exc):
            raise

    if not torch.cuda.is_available():
        raise RuntimeError("frozen-encoder autograd contract requires CUDA")
    device = torch.device("cuda", torch.cuda.current_device())
    scorer = _fake_scorer(device, processor)
    candidate = torch.rand((2, 11, 13, 3), device=device, requires_grad=True)
    grids = scorer.extract_layers_from_rgb_hwc_autograd(candidate)
    grid = grids["last"]
    weights = torch.linspace(
        0.1,
        1.0,
        grid.numel(),
        device=device,
        dtype=grid.dtype,
    ).reshape_as(grid)
    loss = (grid * weights).mean()
    loss.backward()
    if candidate.grad is None or not bool(torch.isfinite(candidate.grad).all().item()):
        raise AssertionError("fake DINOv3 encoder did not produce finite RGB gradients")
    rgb_gradient_l1 = float(candidate.grad.abs().sum().item())
    if rgb_gradient_l1 <= 0.0:
        raise AssertionError("fake DINOv3 encoder RGB gradient is zero")
    if any(parameter.requires_grad for parameter in scorer.model.parameters()):
        raise AssertionError("fake DINOv3 model parameters were not frozen")
    if any(parameter.grad is not None for parameter in scorer.model.parameters()):
        raise AssertionError("frozen DINOv3 model accumulated parameter gradients")

    score_candidate = torch.rand((2, 11, 13, 3), device=device, requires_grad=True)
    score_grids = scorer.extract_layers_from_rgb_hwc_autograd(score_candidate)
    target_grids = {
        "last": torch.roll(score_grids["last"].detach(), shifts=1, dims=2)
    }
    score_distances = scorer.score_grid_layers_batch_mean_torch(
        target_grids,
        score_grids,
        window_radius=1,
        position_weight=1.0,
    )
    score_distances.mean().backward()
    if score_candidate.grad is None or not bool(torch.isfinite(score_candidate.grad).all()):
        raise AssertionError("dense local-window score did not produce finite RGB gradients")
    score_gradient_l1 = float(score_candidate.grad.abs().sum().item())
    if score_gradient_l1 <= 0.0:
        raise AssertionError("dense local-window score RGB gradient is zero")

    detached = candidate.detach()
    try:
        scorer.extract_layers_from_rgb_hwc_autograd(detached)
        raise AssertionError("detached candidate RGB must fail closed")
    except RuntimeError as exc:
        if "detached" not in str(exc):
            raise

    return {
        "ok": True,
        "preprocessParityMaxDelta": parity_delta,
        "officialProcessorParityMaxDelta": official_parity_delta,
        "preprocessGradientL1": float(rgb.grad.abs().sum().item()),
        "featureGradientL1": rgb_gradient_l1,
        "scoreGradientL1": score_gradient_l1,
        "device": str(device),
        "model": "lightweight fake DINOv3 vision encoder",
    }


if __name__ == "__main__":
    print(run())
