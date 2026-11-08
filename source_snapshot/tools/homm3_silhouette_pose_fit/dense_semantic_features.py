#!/usr/bin/env python3
"""GPU dense semantic features for positional sprite-to-pose comparison.

This module is intentionally standalone.  It does not alter the existing
pooled SigLIP2 matcher.  :class:`DenseFeatureScorer` loads a configurable
SigLIP2 or DINO-family encoder lazily, calls its vision tower, and returns
L2-normalized patch-token grids.  The model-dependent class is optional at
runtime; the NumPy and torch scoring helpers can be unit tested without a
model download.

The local-window score is a symmetric positional constraint.  For each target
token it takes the best cosine similarity from the candidate tokens within a
square radius around the same grid coordinate, converts that similarity to
``1 - cosine``, and averages both target-to-candidate directions.  A radius of
zero is strict same-position comparison.
"""

from __future__ import annotations

import math
import os
from typing import Any, Sequence


DEFAULT_SIGLIP2_MODEL = "google/siglip2-base-patch16-512"
# Keep the comparison condition explicit. A failed DINOv3 load must be
# visible instead of silently falling back to an older dense encoder.
# Explicit opt-in checkpoint. Hugging Face access is gated and must not be the
# default for a runnable notebook; DenseFeatureScorer defaults to public
# SigLIP2 instead.
DEFAULT_DINO_MODEL = "facebook/dinov3-vits16-pretrain-lvd1689m"


def _require_numpy():
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError("NumPy is required for the NumPy dense-feature helpers") from exc
    return np


def _require_torch():
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "PyTorch is required for dense model inference and torch scoring helpers"
        ) from exc
    return torch


def require_cuda(device: str = "cuda:0") -> Any:
    """Return a CUDA device or fail before any model is downloaded."""

    torch = _require_torch()
    requested = torch.device(device)
    if requested.type != "cuda":
        raise RuntimeError(
            "Dense semantic feature inference requires CUDA; refusing CPU device "
            f"{requested}. Use a CUDA device or the model-free NumPy helpers."
        )
    if not torch.cuda.is_available():
        raise RuntimeError(
            "Dense semantic feature inference requires CUDA, but no CUDA device "
            "is available; refusing CPU inference."
        )
    if requested.index is None:
        requested = torch.device("cuda", int(torch.cuda.current_device()))
    if requested.index >= torch.cuda.device_count():
        raise RuntimeError(
            f"Requested CUDA device {requested} is not available; "
            f"device count is {torch.cuda.device_count()}"
        )
    return requested


def cuda_device_index(device: Any) -> int:
    """Return the CUDA index. Bare ``cuda`` means the current device."""

    torch = _require_torch()
    resolved = torch.device(getattr(device, "device", device))
    if resolved.type != "cuda":
        raise ValueError(f"expected a CUDA device, got {resolved}")
    if resolved.index is None:
        if not torch.cuda.is_available():
            raise RuntimeError("cannot resolve bare cuda without a CUDA device")
        return int(torch.cuda.current_device())
    return int(resolved.index)


def same_cuda_device(left: Any, right: Any) -> bool:
    """True when both sides are the same GPU. ``cuda`` and ``cuda:0`` match."""

    torch = _require_torch()
    left_dev = torch.device(getattr(left, "device", left))
    right_dev = torch.device(getattr(right, "device", right))
    if left_dev.type != "cuda" or right_dev.type != "cuda":
        return False
    return cuda_device_index(left_dev) == cuda_device_index(right_dev)


def _huggingface_load_kwargs(
    *,
    revision: str | None = None,
    trust_remote_code: bool = False,
    local_files_only: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build Hugging Face from_pretrained kwargs. Token stays in the environment."""

    load_kwargs = dict(extra or {})
    if revision is not None:
        load_kwargs["revision"] = revision
    load_kwargs.setdefault("trust_remote_code", trust_remote_code)
    load_kwargs.setdefault("local_files_only", bool(local_files_only))
    hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN")
    if hf_token:
        load_kwargs.setdefault("token", hf_token)
    return load_kwargs


def _processor_size_dim(size: Any, name: str) -> int | None:
    if size is None:
        return None
    value = getattr(size, name, None)
    if value is None and isinstance(size, dict):
        value = size.get(name)
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def dense_processor_input_hw(processor: Any) -> tuple[int, int]:
    """Return the processor's ``(height, width)`` input size.

    DINOv3 square-resizes to this size. The cascade raster stays an integer
    scale of the proxy so the camera aspect is unchanged; this size only
    decides how many proxy pixels to cover before that square resize.
    """

    size = getattr(processor, "size", None)
    if size is None:
        raise ValueError("dense image processor has no size")
    height = _processor_size_dim(size, "height")
    width = _processor_size_dim(size, "width")
    if height is not None and width is not None:
        if height < 16 or width < 16:
            raise ValueError(
                f"dense image processor size {width}x{height} is smaller than 16x16"
            )
        return (height, width)
    shortest = _processor_size_dim(size, "shortest_edge")
    if shortest is not None:
        if shortest < 16:
            raise ValueError(
                f"dense image processor shortest_edge={shortest} is smaller than 16"
            )
        return (shortest, shortest)
    raise ValueError(
        "dense image processor size must include height and width, or shortest_edge"
    )


def assert_processor_gpu_rgb_supported(processor: Any) -> None:
    """Refuse processors that would need a silent CPU/PIL preprocess path."""

    if bool(getattr(processor, "do_pad", False)):
        raise ValueError("dense GPU RGB preprocess does not support padded image processors")
    if bool(getattr(processor, "do_center_crop", False)):
        raise ValueError(
            "dense GPU RGB preprocess does not support center-crop image processors"
        )
    if not bool(getattr(processor, "do_resize", False)):
        raise ValueError("dense GPU RGB preprocess requires do_resize")
    if not callable(getattr(processor, "process_image", None)):
        raise ValueError(
            "dense GPU RGB preprocess requires a torchvision-backend image processor"
        )
    dense_processor_input_hw(processor)


def dense_semantic_raster_scale_for_proxy(
    proxy_resolution: tuple[int, int],
    processor: Any,
    *,
    min_scale: int = 2,
) -> int:
    """Integer proxy scale that covers the processor input on the long side.

    The nvdiffrast canvas keeps the camera aspect (``proxy * scale``). The
    processor still square-resizes afterward. ``min_scale`` is 2 so RGB
    scoring never runs on the 96×86 proxy.
    """

    proxy_width, proxy_height = (int(proxy_resolution[0]), int(proxy_resolution[1]))
    if proxy_width < 16 or proxy_height < 16:
        raise ValueError("proxy_resolution must be at least 16x16")
    if int(min_scale) < 2:
        raise ValueError("min_scale must be at least 2")
    proc_height, proc_width = dense_processor_input_hw(processor)
    target = max(int(proc_height), int(proc_width))
    proxy_long = max(proxy_width, proxy_height)
    scale = int(math.ceil(target / float(proxy_long)))
    if scale < int(min_scale):
        scale = int(min_scale)
    return scale


def load_dense_image_processor(
    model_id: str,
    *,
    family: str = "auto",
    revision: str | None = None,
    trust_remote_code: bool = False,
    local_files_only: bool = True,
    processor_kwargs: dict[str, Any] | None = None,
) -> Any:
    """Load only the image processor. Used to derive raster scale before the ViT."""

    try:
        from transformers import AutoImageProcessor, AutoProcessor
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "Transformers is required to load a SigLIP2 or DINO-family encoder"
        ) from exc
    resolved_family = _canonical_family(str(model_id), family)
    processor_class = AutoProcessor if resolved_family == "siglip2" else AutoImageProcessor
    load_kwargs = _huggingface_load_kwargs(
        revision=revision,
        trust_remote_code=trust_remote_code,
        local_files_only=local_files_only,
        extra=processor_kwargs,
    )
    try:
        processor = processor_class.from_pretrained(str(model_id), **load_kwargs)
    except Exception as exc:
        token_present = bool(os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN"))
        raise RuntimeError(
            "failed to load dense image processor "
            f"model_id={model_id!r}, family={resolved_family!r}, "
            f"local_files_only={bool(local_files_only)}, "
            f"huggingface_token_present={token_present}"
        ) from exc
    assert_processor_gpu_rgb_supported(processor)
    return processor


def rgb_hwc_batch_to_uint8_images(rgb: Any) -> list[Any]:
    """Convert ``(B, H, W, 3)`` or a list of ``(H, W, 3)`` GPU RGB in ``[0, 1]`` to uint8 HWC."""

    torch = _require_torch()

    def _one(frame: Any) -> Any:
        if not isinstance(frame, torch.Tensor):
            raise TypeError("RGB frames must be torch.Tensor instances")
        if frame.ndim != 3 or int(frame.shape[-1]) != 3:
            raise ValueError("each RGB frame must have shape (H, W, 3)")
        return (frame.detach().float().clamp(0.0, 1.0) * 255.0).round().to(torch.uint8)

    if isinstance(rgb, (list, tuple)):
        frames = [_one(frame) for frame in rgb]
        if not frames:
            raise ValueError("RGB batch must contain at least one frame")
        return frames
    if not isinstance(rgb, torch.Tensor):
        raise TypeError("predicted RGB must be a torch.Tensor")
    if rgb.ndim != 4 or int(rgb.shape[-1]) != 3:
        raise ValueError("predicted RGB must have shape (B, H, W, 3)")
    if int(rgb.shape[0]) < 1:
        raise ValueError("predicted RGB batch must contain at least one frame")
    uint8 = (rgb.detach().float().clamp(0.0, 1.0) * 255.0).round().to(torch.uint8)
    return [uint8[index] for index in range(int(uint8.shape[0]))]


def _processor_autograd_config(
    processor: Any,
) -> tuple[tuple[int, int], tuple[float, float, float], tuple[float, float, float]]:
    """Return the supported DINOv3 float-input preprocessing contract.

    The differentiable path intentionally supports one known transform order:
    RGB ``[0, 1]`` -> bilinear resize with antialiasing -> ImageNet normalize.
    DINOv3's processor performs the equivalent uint8 rescale before resize. Any
    processor drift is rejected instead of being approximated silently.
    """

    declared_type = str(getattr(processor, "image_processor_type", ""))
    class_name = type(processor).__name__
    supported_types = {
        "DINOv3ViTImageProcessor",
        "DINOv3ViTImageProcessorFast",
    }
    if declared_type not in supported_types and class_name not in supported_types:
        raise ValueError(
            "dense autograd RGB preprocess supports only the DINOv3 ViT image "
            f"processor, got declared={declared_type!r} class={class_name!r}"
        )
    if bool(getattr(processor, "do_pad", False)):
        raise ValueError("dense autograd RGB preprocess does not support padding")
    if bool(getattr(processor, "do_center_crop", False)):
        raise ValueError("dense autograd RGB preprocess does not support center crop")
    if not bool(getattr(processor, "do_resize", False)):
        raise ValueError("dense autograd RGB preprocess requires resize")

    size = getattr(processor, "size", None)
    height = _processor_size_dim(size, "height")
    width = _processor_size_dim(size, "width")
    if height is None or width is None:
        raise ValueError(
            "dense autograd RGB preprocess requires explicit processor height and width"
        )
    if height < 16 or width < 16:
        raise ValueError(
            f"dense autograd processor size {width}x{height} is smaller than 16x16"
        )

    resample = getattr(processor, "resample", None)
    try:
        resample_value = int(resample)
    except (TypeError, ValueError) as exc:
        raise ValueError("dense autograd RGB preprocess requires bilinear resampling") from exc
    # PIL.Image.Resampling.BILINEAR has stable numeric value 2, which is also
    # what the Hugging Face DINOv3 processor serializes.
    if resample_value != 2:
        raise ValueError(
            "dense autograd RGB preprocess requires bilinear resampling "
            f"(value 2), got {resample!r}"
        )

    if not bool(getattr(processor, "do_rescale", False)):
        raise ValueError("dense autograd RGB preprocess requires uint8 rescaling")
    try:
        rescale_factor = float(getattr(processor, "rescale_factor"))
    except (TypeError, ValueError) as exc:
        raise ValueError("dense autograd RGB preprocess has no valid rescale_factor") from exc
    if not math.isfinite(rescale_factor) or not math.isclose(
        rescale_factor,
        1.0 / 255.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError(
            "dense autograd RGB preprocess requires rescale_factor=1/255, "
            f"got {rescale_factor!r}"
        )

    if not bool(getattr(processor, "do_normalize", False)):
        raise ValueError("dense autograd RGB preprocess requires normalization")

    def _channel_values(name: str) -> tuple[float, float, float]:
        raw = getattr(processor, name, None)
        if isinstance(raw, (str, bytes)):
            raw = None
        try:
            values = tuple(float(value) for value in raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"dense autograd RGB preprocess requires three {name} values"
            ) from exc
        if len(values) != 3 or not all(math.isfinite(value) for value in values):
            raise ValueError(
                f"dense autograd RGB preprocess requires three finite {name} values"
            )
        return values[0], values[1], values[2]

    mean = _channel_values("image_mean")
    std = _channel_values("image_std")
    if any(value <= 0.0 for value in std):
        raise ValueError("dense autograd RGB preprocess requires positive image_std values")

    data_format = getattr(processor, "data_format", "channels_first")
    data_format = getattr(data_format, "value", data_format)
    if str(data_format) != "channels_first":
        raise ValueError(
            "dense autograd RGB preprocess requires channels_first processor output, "
            f"got {data_format!r}"
        )
    return (height, width), mean, std


def assert_processor_autograd_rgb_supported(processor: Any) -> None:
    """Fail unless ``processor`` has the exact supported DINOv3 transform contract."""

    _processor_autograd_config(processor)


def preprocess_rgb_hwc_autograd(rgb: Any, processor: Any) -> Any:
    """Differentiably preprocess float ``(B, H, W, 3)`` RGB in ``[0, 1]``.

    No image tensor is detached, quantized, converted to PIL/NumPy, or moved to
    CPU. The caller therefore retains gradients from DINOv3 features back to
    its rendered RGB and, transitively, pose parameters.
    """

    torch = _require_torch()
    if not isinstance(rgb, torch.Tensor):
        raise TypeError("autograd RGB input must be a torch.Tensor")
    if rgb.ndim != 4 or int(rgb.shape[-1]) != 3:
        raise ValueError("autograd RGB input must have shape (B, H, W, 3)")
    if int(rgb.shape[0]) < 1 or int(rgb.shape[1]) < 1 or int(rgb.shape[2]) < 1:
        raise ValueError("autograd RGB input must have positive batch and image dimensions")
    if not torch.is_floating_point(rgb):
        raise TypeError("autograd RGB input must use a floating-point dtype")
    if not bool(torch.isfinite(rgb).all().item()):
        raise ValueError("autograd RGB input contains non-finite values")
    minimum = float(rgb.amin().item())
    maximum = float(rgb.amax().item())
    if minimum < 0.0 or maximum > 1.0:
        raise ValueError(
            "autograd RGB input must stay in [0, 1], "
            f"got range [{minimum}, {maximum}]"
        )

    (height, width), mean_values, std_values = _processor_autograd_config(processor)
    values = rgb.permute(0, 3, 1, 2).contiguous().float()
    values = torch.nn.functional.interpolate(
        values,
        size=(height, width),
        mode="bilinear",
        align_corners=False,
        antialias=True,
    )
    mean = values.new_tensor(mean_values).view(1, 3, 1, 1)
    std = values.new_tensor(std_values).view(1, 3, 1, 1)
    return (values - mean) / std


def _freeze_dense_model_parameters(model: Any) -> Any:
    """Freeze encoder weights while leaving autograd enabled for model inputs."""

    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    return model


def _validate_radius(window_radius: int) -> int:
    if isinstance(window_radius, bool) or int(window_radius) != window_radius:
        raise ValueError("window_radius must be a non-negative integer")
    radius = int(window_radius)
    if radius < 0:
        raise ValueError("window_radius must be a non-negative integer")
    return radius


def l2_normalize_tokens_numpy(tokens: Any, eps: float = 1e-12) -> Any:
    """Return tokens normalized along the final feature dimension.

    Accepts ``[..., channels]`` arrays and preserves the array shape.  Zero
    vectors remain zero instead of becoming NaN.
    """

    np = _require_numpy()
    array = np.asarray(tokens)
    if array.ndim < 2:
        raise ValueError("tokens must have at least two dimensions: ... x channels")
    if array.shape[-1] <= 0:
        raise ValueError("tokens must have a non-empty feature dimension")
    if eps <= 0:
        raise ValueError("eps must be positive")
    array = array.astype(np.float32, copy=False)
    norms = np.linalg.norm(array, axis=-1, keepdims=True)
    return array / np.maximum(norms, np.float32(eps))


def l2_normalize_tokens_torch(tokens: Any, eps: float = 1e-12) -> Any:
    """Torch equivalent of :func:`l2_normalize_tokens_numpy`."""

    torch = _require_torch()
    if not isinstance(tokens, torch.Tensor):
        raise TypeError("tokens must be a torch.Tensor")
    if tokens.ndim < 2:
        raise ValueError("tokens must have at least two dimensions: ... x channels")
    if tokens.shape[-1] <= 0:
        raise ValueError("tokens must have a non-empty feature dimension")
    if eps <= 0:
        raise ValueError("eps must be positive")
    values = tokens.float()
    norms = torch.linalg.vector_norm(values, dim=-1, keepdim=True)
    return values / norms.clamp_min(float(eps))


def infer_spatial_grid_shape(
    token_count: int,
    *,
    prefix_tokens: int = 0,
    grid_shape: tuple[int, int] | None = None,
) -> tuple[int, int]:
    """Validate or infer ``(height, width)`` for a patch-token sequence.

    The default requires a square patch grid.  Supplying ``grid_shape`` is
    required for non-square processor outputs and is deliberately explicit so
    a malformed token sequence cannot be silently scored with a wrong layout.
    """

    if isinstance(token_count, bool) or int(token_count) != token_count:
        raise ValueError("token_count must be a positive integer")
    token_count = int(token_count)
    if isinstance(prefix_tokens, bool) or int(prefix_tokens) != prefix_tokens:
        raise ValueError("prefix_tokens must be a non-negative integer")
    prefix_tokens = int(prefix_tokens)
    if prefix_tokens < 0:
        raise ValueError("prefix_tokens must be a non-negative integer")
    spatial_tokens = token_count - prefix_tokens
    if spatial_tokens <= 0:
        raise ValueError(
            f"prefix_tokens={prefix_tokens} removes all {token_count} output tokens"
        )

    if grid_shape is not None:
        if len(grid_shape) != 2:
            raise ValueError("grid_shape must contain (height, width)")
        height, width = (int(grid_shape[0]), int(grid_shape[1]))
        if height <= 0 or width <= 0 or height * width != spatial_tokens:
            raise ValueError(
                f"grid_shape={grid_shape} does not match {spatial_tokens} spatial tokens"
            )
        return height, width

    side = math.isqrt(spatial_tokens)
    if side * side != spatial_tokens:
        raise ValueError(
            f"cannot infer a square spatial grid from {spatial_tokens} tokens; "
            "pass grid_shape=(height, width)"
        )
    return side, side


def _validate_grid_numpy(target: Any, candidate: Any) -> tuple[Any, Any, int, int, int, int]:
    np = _require_numpy()
    target = np.asarray(target, dtype=np.float32)
    candidate = np.asarray(candidate, dtype=np.float32)
    if target.ndim == 3:
        target = target[None, ...]
    if candidate.ndim == 3:
        candidate = candidate[None, ...]
    if target.ndim != 4 or candidate.ndim != 4:
        raise ValueError("feature grids must have shape (H, W, D) or (B, H, W, D)")
    if target.shape != candidate.shape:
        raise ValueError(
            f"target and candidate grids must have the same shape, got "
            f"{target.shape} and {candidate.shape}"
        )
    batch, height, width, channels = target.shape
    if batch <= 0 or height <= 0 or width <= 0 or channels <= 0:
        raise ValueError("feature grids must have positive dimensions")
    return target, candidate, batch, height, width, channels


def _directional_local_similarity_numpy(
    target: Any, candidate: Any, radius: int, position_weight: float
) -> Any:
    np = _require_numpy()
    _batch, height, width, _channels = target.shape
    best = np.full((target.shape[0], height, width), -1.0, dtype=np.float32)
    for dy in range(-radius, radius + 1):
        target_y0 = max(0, -dy)
        target_y1 = min(height, height - dy)
        candidate_y0 = target_y0 + dy
        candidate_y1 = target_y1 + dy
        for dx in range(-radius, radius + 1):
            target_x0 = max(0, -dx)
            target_x1 = min(width, width - dx)
            candidate_x0 = target_x0 + dx
            candidate_x1 = target_x1 + dx
            cosine = np.sum(
                target[:, target_y0:target_y1, target_x0:target_x1, :]
                * candidate[:, candidate_y0:candidate_y1, candidate_x0:candidate_x1, :],
                axis=-1,
            )
            if position_weight:
                offset = float(math.sqrt(dx * dx + dy * dy)) / max(float(radius), 1.0)
                cosine = cosine - float(position_weight) * offset
            best[:, target_y0:target_y1, target_x0:target_x1] = np.maximum(
                best[:, target_y0:target_y1, target_x0:target_x1], cosine
            )
    return best


def local_window_cosine_distance_numpy(
    target: Any,
    candidate: Any,
    *,
    window_radius: int = 1,
    symmetric: bool = True,
    position_weight: float = 0.0,
) -> float:
    """Return local-window cosine distance for NumPy feature grids.

    Inputs may be ``(H, W, D)`` or batched ``(B, H, W, D)``.  The grids are
    normalized inside this helper as well, making it safe to use directly in
    model-free tests.  Batched scores are averaged into one scalar.
    """

    np = _require_numpy()
    radius = _validate_radius(window_radius)
    if not math.isfinite(float(position_weight)) or float(position_weight) < 0.0:
        raise ValueError("position_weight must be finite and non-negative")
    target, candidate, _batch, _height, _width, _channels = _validate_grid_numpy(
        target, candidate
    )
    target = l2_normalize_tokens_numpy(target)
    candidate = l2_normalize_tokens_numpy(candidate)
    target_best = _directional_local_similarity_numpy(
        target, candidate, radius, float(position_weight)
    )
    distances = 1.0 - target_best
    if symmetric:
        candidate_best = _directional_local_similarity_numpy(
            candidate, target, radius, float(position_weight)
        )
        distances = 0.5 * (distances + (1.0 - candidate_best))
    return float(np.mean(distances))


def _validate_grid_torch(target: Any, candidate: Any) -> tuple[Any, Any]:
    torch = _require_torch()
    if not isinstance(target, torch.Tensor) or not isinstance(candidate, torch.Tensor):
        raise TypeError("feature grids must be torch.Tensor instances")
    if target.ndim == 3:
        target = target.unsqueeze(0)
    if candidate.ndim == 3:
        candidate = candidate.unsqueeze(0)
    if target.ndim != 4 or candidate.ndim != 4:
        raise ValueError("feature grids must have shape (H, W, D) or (B, H, W, D)")
    if target.shape != candidate.shape:
        raise ValueError(
            f"target and candidate grids must have the same shape, got "
            f"{tuple(target.shape)} and {tuple(candidate.shape)}"
        )
    if any(int(size) <= 0 for size in target.shape):
        raise ValueError("feature grids must have positive dimensions")
    if target.device != candidate.device:
        raise ValueError("target and candidate grids must be on the same device")
    return target, candidate


def _directional_local_similarity_torch(
    target: Any, candidate: Any, radius: int, position_weight: float
) -> Any:
    torch = _require_torch()
    import torch.nn.functional as F

    _batch, height, width, _channels = target.shape
    candidates = []
    for dy in range(-radius, radius + 1):
        target_y0 = max(0, -dy)
        target_y1 = min(height, height - dy)
        candidate_y0 = target_y0 + dy
        candidate_y1 = target_y1 + dy
        for dx in range(-radius, radius + 1):
            target_x0 = max(0, -dx)
            target_x1 = min(width, width - dx)
            candidate_x0 = target_x0 + dx
            candidate_x1 = target_x1 + dx
            cosine = (
                target[:, target_y0:target_y1, target_x0:target_x1, :]
                * candidate[:, candidate_y0:candidate_y1, candidate_x0:candidate_x1, :]
            ).sum(dim=-1)
            if position_weight:
                offset = float(math.sqrt(dx * dx + dy * dy)) / max(float(radius), 1.0)
                cosine = cosine - float(position_weight) * offset
            candidates.append(
                F.pad(
                    cosine,
                    (
                        target_x0,
                        width - target_x1,
                        target_y0,
                        height - target_y1,
                    ),
                    value=float("-inf"),
                )
            )
    return torch.stack(candidates, dim=0).amax(dim=0)


def local_window_cosine_distance_torch(
    target: Any,
    candidate: Any,
    *,
    window_radius: int = 1,
    symmetric: bool = True,
    position_weight: float = 0.0,
) -> Any:
    """Return local-window cosine distance as a scalar torch tensor."""

    return local_window_cosine_distances_torch(
        target,
        candidate,
        window_radius=window_radius,
        symmetric=symmetric,
        position_weight=position_weight,
    ).mean()


def local_window_cosine_distances_torch(
    target: Any,
    candidate: Any,
    *,
    window_radius: int = 1,
    symmetric: bool = True,
    position_weight: float = 0.0,
) -> Any:
    """Return one local-window cosine distance per batch item.

    The scalar API above is retained for existing callers.  The vector form
    lets the pose solver score a whole candidate render batch after one dense
    encoder forward pass instead of extracting each candidate independently.
    """

    radius = _validate_radius(window_radius)
    if not math.isfinite(float(position_weight)) or float(position_weight) < 0.0:
        raise ValueError("position_weight must be finite and non-negative")
    if getattr(target, "ndim", None) == 3:
        target = target.unsqueeze(0)
    if getattr(candidate, "ndim", None) == 3:
        candidate = candidate.unsqueeze(0)
    if (
        getattr(target, "ndim", None) == 4
        and getattr(candidate, "ndim", None) == 4
        and int(target.shape[0]) == 1
        and int(candidate.shape[0]) > 1
    ):
        target = target.expand(candidate.shape[0], -1, -1, -1)
    target, candidate = _validate_grid_torch(target, candidate)
    target = l2_normalize_tokens_torch(target)
    candidate = l2_normalize_tokens_torch(candidate)
    target_best = _directional_local_similarity_torch(
        target, candidate, radius, float(position_weight)
    )
    distances = 1.0 - target_best
    if symmetric:
        candidate_best = _directional_local_similarity_torch(
            candidate, target, radius, float(position_weight)
        )
        distances = 0.5 * (distances + (1.0 - candidate_best))
    return distances.flatten(1).mean(dim=1)


def _canonical_family(model_id: str, family: str) -> str:
    value = str(family).strip().lower().replace("_", "-")
    if value in {"siglip", "siglip2"}:
        return "siglip2"
    if value in {"dino", "dino2", "dino3", "dino-family"}:
        return "dino"
    if value != "auto":
        raise ValueError("family must be 'auto', 'siglip2', or 'dino'")
    lowered = model_id.lower()
    if "siglip" in lowered:
        return "siglip2"
    if "dino" in lowered:
        return "dino"
    raise ValueError(
        f"cannot infer encoder family from model_id={model_id!r}; "
        "pass family='siglip2' or family='dino'"
    )


def _config_value(model: Any, *names: str) -> int | None:
    configs = [getattr(model, "config", None)]
    vision_config = getattr(configs[0], "vision_config", None)
    if vision_config is not None:
        configs.insert(0, vision_config)
    for config in configs:
        for name in names:
            value = getattr(config, name, None)
            if value is not None:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
                if value >= 0:
                    return value
    return None


def _infer_prefix_tokens(
    model: Any,
    family: str,
    token_count: int,
    *,
    explicit_prefix_tokens: int | None,
    grid_shape: tuple[int, int] | None,
) -> int:
    if explicit_prefix_tokens is not None:
        prefix = int(explicit_prefix_tokens)
        infer_spatial_grid_shape(token_count, prefix_tokens=prefix, grid_shape=grid_shape)
        return prefix

    configured_prefix = _config_value(model, "num_prefix_tokens")
    registers = _config_value(model, "num_register_tokens")
    candidates: list[int] = []
    if configured_prefix is not None:
        candidates.append(configured_prefix)
    if family == "dino":
        candidates.extend([1 + (registers or 0), 1, 0])
    else:
        candidates.extend([0, 1])
    seen: set[int] = set()
    for prefix in candidates:
        if prefix in seen or prefix < 0:
            continue
        seen.add(prefix)
        try:
            infer_spatial_grid_shape(token_count, prefix_tokens=prefix, grid_shape=grid_shape)
        except ValueError:
            continue
        return prefix
    raise ValueError(
        f"cannot infer spatial patch grid from {token_count} vision tokens for "
        f"family={family!r}; pass prefix_tokens and/or grid_shape explicitly"
    )


def _select_spatial_tokens(
    output: Any,
    *,
    model: Any,
    family: str,
    feature_layer: str | int,
    prefix_tokens: int | None,
    grid_shape: tuple[int, int] | None,
) -> tuple[Any, tuple[int, int]]:
    hidden = getattr(output, "last_hidden_state", None)
    if isinstance(feature_layer, int) or str(feature_layer).lower() not in {"last", "final"}:
        states = getattr(output, "hidden_states", None)
        if states is None:
            raise RuntimeError(
                "the vision encoder did not return hidden_states; "
                "feature_layer must be 'last' for this model"
            )
        index = feature_layer
        if isinstance(feature_layer, str):
            raw = feature_layer.strip().lower()
            if raw.startswith("hidden:"):
                index = int(raw.split(":", 1)[1])
            else:
                try:
                    index = int(raw)
                except ValueError as exc:
                    raise ValueError(
                        "feature_layer must be 'last', 'final', or an integer/hidden:<index>"
                    ) from exc
        try:
            hidden = states[index]
        except IndexError as exc:
            raise ValueError(f"feature_layer index {index} is outside hidden_states") from exc
    if hidden is None or getattr(hidden, "ndim", None) != 3:
        raise RuntimeError(
            "the vision encoder did not return rank-3 spatial tokens in last_hidden_state"
        )
    batch, token_count, channels = hidden.shape
    if batch <= 0 or channels <= 0:
        raise RuntimeError("vision encoder returned an empty feature tensor")
    prefix = _infer_prefix_tokens(
        model,
        family,
        int(token_count),
        explicit_prefix_tokens=prefix_tokens,
        grid_shape=grid_shape,
    )
    height, width = infer_spatial_grid_shape(
        int(token_count), prefix_tokens=prefix, grid_shape=grid_shape
    )
    spatial = hidden[:, prefix:, :]
    return spatial.reshape(batch, height, width, channels), (height, width)


class DenseFeatureScorer:
    """CUDA-only dense patch-feature extractor and local-window scorer.

    Parameters
    ----------
    model_id:
        Hugging Face model id or local model directory.  The defaults are
        ``google/siglip2-base-patch16-512`` by default. DINOv3 remains an
        explicit opt-in through ``model_id`` and requires Hugging Face access.
    family:
        ``"siglip2"``, ``"dino"``, or ``"auto"`` to infer from the id.
    feature_layer:
        ``"last"``/``"final"`` or a hidden-state index (also ``"hidden:N"``).
    prefix_tokens, grid_shape:
        Optional explicit output-layout controls.  They are useful for a
        custom DINO variant or a non-square image processor.
    """

    def __init__(
        self,
        model_id: str = DEFAULT_SIGLIP2_MODEL,
        *,
        family: str = "auto",
        device: str = "cuda:0",
        feature_layer: str | int = "last",
        feature_layers: Sequence[str | int] | str | None = None,
        prefix_tokens: int | None = None,
        grid_shape: tuple[int, int] | None = None,
        revision: str | None = None,
        trust_remote_code: bool = False,
        local_files_only: bool = False,
        model_kwargs: dict[str, Any] | None = None,
        processor_kwargs: dict[str, Any] | None = None,
    ):
        torch = _require_torch()
        self.device = require_cuda(device)
        self.model_id = str(model_id)
        self.family = _canonical_family(self.model_id, family)
        if feature_layers is None:
            layers = [feature_layer]
        elif isinstance(feature_layers, str):
            layers = [item.strip() for item in feature_layers.split(",") if item.strip()]
        else:
            layers = list(feature_layers)
        if not layers:
            raise ValueError("feature_layers must contain at least one layer")
        self.feature_layers = tuple(layers)
        self.feature_layer = self.feature_layers[0]
        self.prefix_tokens = prefix_tokens
        self.grid_shape = grid_shape
        self.torch = torch

        try:
            from transformers import AutoImageProcessor, AutoModel, AutoProcessor
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise RuntimeError(
                "Transformers is required to load a SigLIP2 or DINO-family encoder"
            ) from exc

        load_kwargs = _huggingface_load_kwargs(
            revision=revision,
            trust_remote_code=trust_remote_code,
            local_files_only=local_files_only,
            extra=model_kwargs,
        )
        processor_load_kwargs = _huggingface_load_kwargs(
            revision=revision,
            trust_remote_code=trust_remote_code,
            local_files_only=local_files_only,
            extra=processor_kwargs,
        )

        processor_class = AutoProcessor if self.family == "siglip2" else AutoImageProcessor
        try:
            self.processor = processor_class.from_pretrained(self.model_id, **processor_load_kwargs)
            self.model = _freeze_dense_model_parameters(
                AutoModel.from_pretrained(self.model_id, **load_kwargs).to(self.device)
            )
        except Exception as exc:
            token_present = bool(os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN"))
            raise RuntimeError(
                "failed to load dense vision encoder "
                f"model_id={self.model_id!r}, family={self.family!r}, "
                f"local_files_only={bool(local_files_only)}, "
                f"huggingface_token_present={token_present}; "
                "for gated DINOv3, load HF_TOKEN into the kernel before constructing "
                "the scorer and verify the checkpoint cache"
            ) from exc

    def _needs_hidden_states(self) -> bool:
        return any(
            isinstance(layer, int)
            or (isinstance(layer, str) and layer.strip().lower() not in {"last", "final"})
            for layer in self.feature_layers
        )

    def _encode_from_processor_inputs(
        self,
        inputs: Any,
        *,
        require_cuda_inputs: bool,
    ) -> dict[str | int, Any]:
        """ViT forward in fp16 autocast; L2-normalized grids stay float32."""

        torch = self.torch
        model_inputs: dict[str, Any] = {}
        for key, value in inputs.items():
            if not hasattr(value, "to"):
                model_inputs[key] = value
                continue
            if require_cuda_inputs:
                if not same_cuda_device(value, self.device):
                    raise RuntimeError(
                        f"dense image processor moved {key} off {self.device} onto "
                        f"{value.device}; GPU preprocess is required (no CPU/PIL fallback)"
                    )
                model_inputs[key] = value
            else:
                model_inputs[key] = value.to(self.device)
        vision_model = getattr(self.model, "vision_model", self.model)
        needs_hidden_states = self._needs_hidden_states()
        with torch.inference_mode():
            try:
                with torch.autocast(device_type="cuda", dtype=torch.float16):
                    output = vision_model(
                        **model_inputs,
                        output_hidden_states=needs_hidden_states,
                        return_dict=True,
                    )
            except TypeError as exc:
                raise RuntimeError(
                    "the selected vision encoder does not expose a compatible "
                    "spatial vision-tower forward path"
                ) from exc
            return {
                layer: l2_normalize_tokens_torch(
                    _select_spatial_tokens(
                        output,
                        model=self.model,
                        family=self.family,
                        feature_layer=layer,
                        prefix_tokens=self.prefix_tokens,
                        grid_shape=self.grid_shape,
                    )[0]
                )
                for layer in self.feature_layers
            }

    def _encode_from_processor_inputs_autograd(
        self,
        inputs: Any,
    ) -> dict[str | int, Any]:
        """Run the frozen ViT while retaining gradients to CUDA image inputs."""

        torch = self.torch
        model_inputs: dict[str, Any] = {}
        has_input_gradient = False
        for key, value in inputs.items():
            if not isinstance(value, torch.Tensor):
                raise TypeError(
                    "dense autograd encoder inputs must all be torch.Tensor instances; "
                    f"got {key}={type(value).__name__}"
                )
            if not same_cuda_device(value, self.device):
                raise RuntimeError(
                    f"dense autograd input {key} is on {value.device}, expected "
                    f"{self.device}; CPU transfer is forbidden"
                )
            has_input_gradient = has_input_gradient or bool(value.requires_grad)
            model_inputs[key] = value
        if not model_inputs:
            raise ValueError("dense autograd encoder inputs must not be empty")
        if not has_input_gradient:
            raise RuntimeError(
                "dense autograd encoder received a detached input; rendered RGB must "
                "require gradients"
            )
        if any(parameter.requires_grad for parameter in self.model.parameters()):
            raise RuntimeError(
                "dense autograd encoder parameters must be frozen before candidate scoring"
            )

        vision_model = getattr(self.model, "vision_model", self.model)
        needs_hidden_states = self._needs_hidden_states()
        try:
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                output = vision_model(
                    **model_inputs,
                    output_hidden_states=needs_hidden_states,
                    return_dict=True,
                )
        except TypeError as exc:
            raise RuntimeError(
                "the selected vision encoder does not expose a compatible "
                "spatial vision-tower autograd path"
            ) from exc
        grids = {
            layer: l2_normalize_tokens_torch(
                _select_spatial_tokens(
                    output,
                    model=self.model,
                    family=self.family,
                    feature_layer=layer,
                    prefix_tokens=self.prefix_tokens,
                    grid_shape=self.grid_shape,
                )[0]
            )
            for layer in self.feature_layers
        }
        detached = [layer for layer, grid in grids.items() if not bool(grid.requires_grad)]
        if detached:
            raise RuntimeError(
                "dense autograd encoder detached feature layer(s): "
                f"{detached}"
            )
        return grids

    def extract(self, images: Sequence[Any]) -> Any:
        """Extract normalized ``(B, H, W, D)`` patch grids from PIL images."""

        return self.extract_layers(images)[self.feature_layer]

    def extract_layers(self, images: Sequence[Any]) -> dict[str | int, Any]:
        """Extract all configured spatial layers in one vision forward pass."""

        if not images:
            raise ValueError("images must contain at least one image")
        inputs = self.processor(images=list(images), return_tensors="pt")
        return self._encode_from_processor_inputs(inputs, require_cuda_inputs=False)

    def extract_layers_from_rgb_hwc(self, rgb: Any) -> dict[str | int, Any]:
        """Extract patch grids from GPU RGB in ``[0, 1]`` without a CPU/PIL round-trip.

        ``rgb`` is ``(B, H, W, 3)`` or a list of ``(H, W, 3)`` tensors already on
        this scorer's CUDA device. The torchvision processor must keep
        ``pixel_values`` on that device.
        """

        assert_processor_gpu_rgb_supported(self.processor)
        frames = rgb_hwc_batch_to_uint8_images(rgb)
        for frame in frames:
            if not same_cuda_device(frame, self.device):
                raise ValueError(
                    "RGB tensors must already be on the scorer CUDA device; "
                    f"got {frame.device}, expected {self.device}"
                )
        inputs = self.processor(images=frames, return_tensors="pt")
        return self._encode_from_processor_inputs(inputs, require_cuda_inputs=True)

    def extract_layers_from_rgb_hwc_autograd(self, rgb: Any) -> dict[str | int, Any]:
        """Extract DINOv3 grids while preserving gradients to float CUDA HWC RGB."""

        torch = self.torch
        if not isinstance(rgb, torch.Tensor):
            raise TypeError("autograd RGB batch must be a torch.Tensor")
        if not same_cuda_device(rgb, self.device):
            raise ValueError(
                "autograd RGB must already be on the scorer CUDA device; "
                f"got {rgb.device}, expected {self.device}"
            )
        if not bool(rgb.requires_grad):
            raise RuntimeError(
                "autograd RGB is detached; rendered candidate RGB must require gradients"
            )
        pixel_values = preprocess_rgb_hwc_autograd(rgb, self.processor)
        return self._encode_from_processor_inputs_autograd(
            {"pixel_values": pixel_values}
        )

    def score_grids(
        self,
        target_grid: Any,
        candidate_grid: Any,
        *,
        window_radius: int = 1,
        position_weight: float = 0.0,
    ) -> float:
        """Score two already-extracted grids without another model call."""

        score = local_window_cosine_distance_torch(
            target_grid,
            candidate_grid,
            window_radius=window_radius,
            position_weight=position_weight,
        )
        return float(score.detach().cpu().item())

    def score_grid_layers(
        self,
        target_grids: dict[str | int, Any],
        candidate_grids: dict[str | int, Any],
        *,
        window_radius: int = 1,
        position_weight: float = 0.0,
    ) -> dict[str | int, float]:
        """Score each configured layer independently without another model call."""

        missing = [layer for layer in self.feature_layers if layer not in target_grids or layer not in candidate_grids]
        if missing:
            raise ValueError(f"missing dense feature layer(s): {missing}")
        return {
            layer: self.score_grids(
                target_grids[layer],
                candidate_grids[layer],
                window_radius=window_radius,
                position_weight=position_weight,
            )
            for layer in self.feature_layers
        }

    def score_grid_layers_mean(
        self,
        target_grids: dict[str | int, Any],
        candidate_grids: dict[str | int, Any],
        *,
        window_radius: int = 1,
        position_weight: float = 0.0,
    ) -> tuple[float, dict[str | int, float]]:
        """Return mean local-window distance and the per-layer distances."""

        scores = self.score_grid_layers(
            target_grids,
            candidate_grids,
            window_radius=window_radius,
            position_weight=position_weight,
        )
        return float(sum(scores.values()) / len(scores)), scores

    def score_grid_layers_batch_mean_torch(
        self,
        target_grids: dict[str | int, Any],
        candidate_grids: dict[str | int, Any],
        *,
        window_radius: int = 1,
        position_weight: float = 0.0,
    ) -> Any:
        """Return one mean local-window distance per candidate on the scoring device.

        ``target_grids`` may be one image (broadcast) or a matching candidate
        batch so mixed sprite frames can share one encoder forward.
        """

        torch = self.torch
        missing = [
            layer
            for layer in self.feature_layers
            if layer not in target_grids or layer not in candidate_grids
        ]
        if missing:
            raise ValueError(f"missing dense feature layer(s): {missing}")
        layer_distances = []
        expected_batch: int | None = None
        for layer in self.feature_layers:
            target = target_grids[layer]
            candidate = candidate_grids[layer]
            if getattr(target, "ndim", None) == 3:
                target = target.unsqueeze(0)
            if getattr(candidate, "ndim", None) != 4:
                raise ValueError("candidate dense grids must have shape (B, H, W, D)")
            batch = int(candidate.shape[0])
            if expected_batch is None:
                expected_batch = batch
            elif batch != expected_batch:
                raise ValueError("candidate dense layers must share a batch size")
            target_batch = int(target.shape[0])
            if target_batch == 1 and batch > 1:
                target = target.expand(batch, -1, -1, -1)
            elif target_batch != batch:
                raise ValueError(
                    "target dense grids must have batch 1 or match the candidate batch, "
                    f"got target={target_batch} candidate={batch}"
                )
            if tuple(target.shape[1:]) != tuple(candidate.shape[1:]):
                raise ValueError(
                    "target and candidate dense grids must have matching spatial dimensions"
                )
            layer_distances.append(
                local_window_cosine_distances_torch(
                    target,
                    candidate,
                    window_radius=window_radius,
                    position_weight=position_weight,
                )
            )
        stacked = torch.stack(layer_distances, dim=0)
        return stacked.mean(dim=0)

    def score_grid_layers_batch_mean(
        self,
        target_grids: dict[str | int, Any],
        candidate_grids: dict[str | int, Any],
        *,
        window_radius: int = 1,
        position_weight: float = 0.0,
    ) -> list[tuple[float, dict[str | int, float]]]:
        """Score target grid(s) against a batch of candidate grids.

        ``target_grids`` may contain one target image or ``B`` targets aligned
        with ``candidate_grids``. Feature extraction is already batched by
        :meth:`extract_layers` / :meth:`extract_layers_from_rgb_hwc`; this
        method keeps the local-window metric on the same CUDA device and
        returns one averaged distance per candidate.
        """

        missing = [
            layer
            for layer in self.feature_layers
            if layer not in target_grids or layer not in candidate_grids
        ]
        if missing:
            raise ValueError(f"missing dense feature layer(s): {missing}")
        mean_distances = self.score_grid_layers_batch_mean_torch(
            target_grids,
            candidate_grids,
            window_radius=window_radius,
            position_weight=position_weight,
        )
        per_layer: list[dict[str | int, float]] = [
            {} for _ in range(int(mean_distances.shape[0]))
        ]
        for layer in self.feature_layers:
            target = target_grids[layer]
            candidate = candidate_grids[layer]
            if getattr(target, "ndim", None) == 3:
                target = target.unsqueeze(0)
            target_batch = int(target.shape[0])
            batch = int(candidate.shape[0])
            if target_batch == 1 and batch > 1:
                target = target.expand(batch, -1, -1, -1)
            distances = local_window_cosine_distances_torch(
                target,
                candidate,
                window_radius=window_radius,
                position_weight=position_weight,
            )
            for index, value in enumerate(distances.detach().cpu().tolist()):
                per_layer[index][layer] = float(value)
        return [
            (
                float(mean_distances[index].detach().cpu().item()),
                per_layer[index],
            )
            for index in range(int(mean_distances.shape[0]))
        ]

    def score_images(
        self,
        targets: Sequence[Any],
        candidates: Sequence[Any],
        *,
        window_radius: int = 1,
    ) -> list[float]:
        """Extract and score corresponding target/candidate image pairs."""

        targets = list(targets)
        candidates = list(candidates)
        if len(targets) != len(candidates):
            raise ValueError(
                f"targets and candidates must have the same length, got "
                f"{len(targets)} and {len(candidates)}"
            )
        if not targets:
            return []
        target_grid = self.extract(targets)
        candidate_grid = self.extract(candidates)
        return [
            self.score_grids(target_grid[index], candidate_grid[index], window_radius=window_radius)
            for index in range(len(targets))
        ]


__all__ = [
    "DEFAULT_DINO_MODEL",
    "DEFAULT_SIGLIP2_MODEL",
    "DenseFeatureScorer",
    "assert_processor_autograd_rgb_supported",
    "assert_processor_gpu_rgb_supported",
    "dense_processor_input_hw",
    "dense_semantic_raster_scale_for_proxy",
    "infer_spatial_grid_shape",
    "l2_normalize_tokens_numpy",
    "l2_normalize_tokens_torch",
    "load_dense_image_processor",
    "local_window_cosine_distance_numpy",
    "local_window_cosine_distance_torch",
    "local_window_cosine_distances_torch",
    "preprocess_rgb_hwc_autograd",
    "require_cuda",
    "rgb_hwc_batch_to_uint8_images",
    "same_cuda_device",
]
