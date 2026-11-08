"""Differentiable fixed-camera image objective for skin/pose experiments.

This module intentionally has one renderer: CUDA nvdiffrast.  It does not
silently fall back to a CPU rasterizer, since that would change the gradients
being optimized.
"""
from __future__ import annotations

from typing import Any

import numpy as np


def _require_torch():
    import torch
    from pathlib import Path
    import sys

    tool = Path(__file__).resolve().parents[2] / "tools" / "homm3_silhouette_pose_fit"
    if str(tool) not in sys.path:
        sys.path.insert(0, str(tool))
    from nvdiffrast_local import ensure_local_nvdiffrast

    ensure_local_nvdiffrast(required=True)
    import nvdiffrast.torch as dr
    return torch, dr


def _tensor(value: Any, *, torch: Any, device: Any, dtype: Any) -> Any:
    result = value if isinstance(value, torch.Tensor) else torch.as_tensor(value)
    result = result.to(device=device, dtype=dtype)
    if not torch.isfinite(result).all():
        raise ValueError("skin image objective received non-finite tensor data")
    return result


class SkinImageRenderer:
    """Render batched world-space vertices into a top-down image tensor."""

    def __init__(self, triangles: np.ndarray, uvs: np.ndarray, albedo: np.ndarray,
                 camera: dict[str, Any], resolution: int, device: str = "cuda") -> None:
        if int(resolution) < 2:
            raise ValueError("resolution must be at least 2")
        if device == "cpu" or not str(device).startswith("cuda"):
            raise ValueError("SkinImageRenderer requires a CUDA device")
        self.torch, self.dr = _require_torch()
        torch = self.torch
        self.device = torch.device(device)
        if not torch.cuda.is_available():
            raise RuntimeError("SkinImageRenderer requires CUDA")
        tri = np.asarray(triangles)
        uv = np.asarray(uvs)
        tex = np.asarray(albedo)
        if tri.ndim != 2 or tri.shape[1] != 3 or not np.issubdtype(tri.dtype, np.integer):
            raise ValueError("triangles must be an integer [T,3] array")
        if len(tri) and (int(tri.min()) < 0 or int(tri.max()) >= len(uv)):
            raise ValueError("triangle index is outside the UV vertex range")
        if uv.ndim != 2 or uv.shape[1] != 2 or not np.isfinite(uv).all():
            raise ValueError("uvs must be finite [V,2]")
        if tex.ndim != 3 or tex.shape[2] not in (3, 4):
            raise ValueError("albedo must be [H,W,3|4]")
        if not np.isfinite(tex.astype(np.float32)).all():
            raise ValueError("albedo contains non-finite values")
        self.resolution = int(resolution)
        self.triangles = torch.as_tensor(tri.astype(np.int32), device=self.device, dtype=torch.int32)
        self.uvs = torch.as_tensor(uv, device=self.device, dtype=torch.float32)
        # glTF UV v=0 addresses the image's first row, as in sample_albedo_uv.
        # Raster image orientation is handled separately after rasterization.
        texf = tex[..., :3].astype(np.float32) / (255.0 if tex.dtype == np.uint8 else 1.0)
        self.texture = torch.as_tensor(texf.copy(), device=self.device).unsqueeze(0)
        required = ("right", "down", "forward", "scale", "offset", "depth_center", "depth_span")
        missing = [key for key in required if key not in camera]
        if missing:
            raise ValueError(f"camera missing required fields: {missing}")
        self.ctx = self.dr.RasterizeCudaContext(device=self.device)
        self.set_camera(camera)

    def set_camera(self, camera: dict[str, Any]) -> None:
        """Update camera tensors while retaining the registered CUDA context."""
        torch = self.torch
        required = ("right", "down", "forward", "scale", "offset", "depth_center", "depth_span")
        missing = [key for key in required if key not in camera]
        if missing:
            raise ValueError(f"camera missing required fields: {missing}")
        self.right = _tensor(camera["right"], torch=torch, device=self.device, dtype=torch.float32).reshape(3)
        self.down = _tensor(camera["down"], torch=torch, device=self.device, dtype=torch.float32).reshape(3)
        self.forward = _tensor(camera["forward"], torch=torch, device=self.device, dtype=torch.float32).reshape(3)
        self.scale = float(camera["scale"])
        self.offset = _tensor(camera["offset"], torch=torch, device=self.device, dtype=torch.float32).reshape(2)
        self.depth_center = float(camera["depth_center"])
        self.depth_span = float(camera["depth_span"])
        if not np.isfinite([self.scale, self.depth_center, self.depth_span]).all() or self.scale <= 0 or self.depth_span <= 0:
            raise ValueError("camera scale/depth parameters must be finite and positive")

    def _rasterize(self, vertices: Any):
        torch, dr = self.torch, self.dr
        verts = _tensor(vertices, torch=torch, device=self.device, dtype=torch.float32)
        if verts.ndim != 3 or verts.shape[2] != 3:
            raise ValueError(f"vertices must have shape [F,V,3], got {tuple(verts.shape)}")
        rel = verts
        x = torch.einsum("fvi,i->fv", rel, self.right)
        y = torch.einsum("fvi,i->fv", rel, self.down)
        z = torch.einsum("fvi,i->fv", rel, self.forward)
        px = x * self.scale + self.offset[0]
        py = y * self.scale + self.offset[1]
        ndc_x = 2.0 * px / (self.resolution - 1) - 1.0
        ndc_y = 1.0 - 2.0 * py / (self.resolution - 1)
        ndc_z = (z - self.depth_center) / self.depth_span
        clip = torch.stack((ndc_x, ndc_y, ndc_z, torch.ones_like(ndc_z)), dim=-1)
        rast, _ = dr.rasterize(self.ctx, clip, self.triangles, resolution=[self.resolution, self.resolution])
        return verts, clip, rast

    def render(self, vertices: Any) -> tuple[Any, Any]:
        torch, dr = self.torch, self.dr
        _verts, clip, rast = self._rasterize(vertices)
        uv, _ = dr.interpolate(self.uvs[None], rast, self.triangles)
        sampled = dr.texture(self.texture, uv, filter_mode="linear")
        alpha = (rast[..., 3:4] > 0).to(sampled.dtype)
        sampled = dr.antialias(sampled * alpha, rast, clip, self.triangles)
        alpha = dr.antialias(alpha, rast, clip, self.triangles).clamp(0.0, 1.0)
        rgb = sampled
        # Raster output is bottom-up; objective tensors follow top-down source
        # sprite order. This flip is part of the camera contract, not a metric.
        return torch.flip(rgb, dims=(1,)), torch.flip(alpha, dims=(1,))

    def render_buffers(self, vertices: Any) -> dict[str, Any]:
        torch, dr = self.torch, self.dr
        _verts, clip, rast = self._rasterize(vertices)
        uv, _ = dr.interpolate(self.uvs[None], rast, self.triangles)
        sampled = dr.texture(self.texture, uv, filter_mode="linear")
        covered = (rast[..., 3:4] > 0).to(sampled.dtype)
        sampled = dr.antialias(sampled * covered, rast, clip, self.triangles)
        alpha = dr.antialias(covered, rast, clip, self.triangles).clamp(0.0, 1.0)
        triangle_id = rast[..., 3].to(torch.long) - 1
        bary = torch.stack(
            (
                1.0 - rast[..., 0] - rast[..., 1],
                rast[..., 0],
                rast[..., 1],
            ),
            dim=-1,
        )
        return {
            "rgb": torch.flip(sampled, dims=(1,)),
            "alpha": torch.flip(alpha, dims=(1,)),
            "triangleId": torch.flip(triangle_id, dims=(1,)),
            "barycentric": torch.flip(bary, dims=(1,)),
        }


def image_loss(rgb: Any, alpha: Any, target_rgb: Any, target_alpha: Any,
               target_distance: Any, *, validate: bool = True) -> dict[str, Any]:
    """Return differentiable silhouette, color, and total losses.

    ``validate=False`` skips the per-call finiteness scans and host-to-device
    moves, for callers that hoisted loop-invariant targets once (same device
    and float32 dtype required). Shape checks always run. Default ``True``
    preserves the fail-closed contract for every existing caller.
    """
    import torch
    pred_rgb = rgb if isinstance(rgb, torch.Tensor) else torch.as_tensor(rgb, dtype=torch.float32)
    pred_a = alpha if isinstance(alpha, torch.Tensor) else torch.as_tensor(alpha, dtype=torch.float32)
    device = pred_rgb.device
    pred_rgb = pred_rgb.float()
    pred_a = pred_a.float()
    if validate:
        target_rgb = _tensor(target_rgb, torch=torch, device=device, dtype=torch.float32)
        target_a = _tensor(target_alpha, torch=torch, device=device, dtype=torch.float32)
        distance = _tensor(target_distance, torch=torch, device=device, dtype=torch.float32)
    else:
        target_rgb = target_rgb.to(device=device, dtype=torch.float32)
        target_a = target_alpha.to(device=device, dtype=torch.float32)
        distance = target_distance.to(device=device, dtype=torch.float32)
    if pred_rgb.ndim != 4 or pred_rgb.shape[-1] != 3 or pred_a.shape != (*pred_rgb.shape[:3], 1):
        raise ValueError("rgb/alpha must be [F,H,W,3]/[F,H,W,1]")
    if target_rgb.shape != pred_rgb.shape or target_a.shape != pred_a.shape or distance.shape != pred_a.shape[:-1]:
        raise ValueError("target image tensors do not match prediction shapes")
    pred_a = pred_a.clamp(0, 1)
    target_a = target_a.clamp(0, 1)
    intersection = (pred_a * target_a).mean((1, 2, 3))
    union = (pred_a + target_a - pred_a * target_a).mean((1, 2, 3))
    iou = intersection / union.clamp_min(1e-6)
    fp_weight = 1.0 + distance.unsqueeze(-1) / distance.detach().mean().clamp_min(1e-6)
    false_positive = (torch.relu(pred_a - target_a) * fp_weight).mean((1, 2, 3))
    alpha_l1 = torch.abs(pred_a - target_a).mean((1, 2, 3))
    silhouette_levels = [alpha_l1 + (1.0 - iou) + false_positive]
    for factor in (2, 4):
        if pred_a.shape[1] >= factor and pred_a.shape[2] >= factor:
            pooled_a = torch.nn.functional.avg_pool2d(pred_a.permute(0, 3, 1, 2), factor).permute(0, 2, 3, 1)
            pooled_t = torch.nn.functional.avg_pool2d(target_a.permute(0, 3, 1, 2), factor).permute(0, 2, 3, 1)
            level_inter = torch.minimum(pooled_a, pooled_t).mean((1, 2, 3))
            # Downsampling turns binary masks into coverage values. Use the
            # soft max-union here so an identical fractional mask remains a
            # zero-loss fixed point (the full-resolution term retains the
            # standard soft IoU union).
            level_union = torch.maximum(pooled_a, pooled_t).mean((1, 2, 3)).clamp_min(1e-6)
            level_l1 = torch.abs(pooled_a - pooled_t).mean((1, 2, 3))
            silhouette_levels.append(level_l1 + (1.0 - level_inter / level_union))
    silhouette = torch.stack([level.mean() for level in silhouette_levels]).mean()
    overlap = (pred_a * target_a).detach() + 0.05 * target_a
    pred_luma = (pred_rgb * torch.tensor((0.299, 0.587, 0.114), device=device)).sum(-1, keepdim=True)
    target_luma = (target_rgb * torch.tensor((0.299, 0.587, 0.114), device=device)).sum(-1, keepdim=True)
    pred_chroma = pred_rgb / pred_luma.clamp_min(1e-3)
    target_chroma = target_rgb / target_luma.clamp_min(1e-3)
    color = (torch.abs(pred_chroma - target_chroma) * overlap).sum() / overlap.sum().clamp_min(1e-6)
    total = silhouette + 0.1 * color
    return {"silhouette": silhouette, "color": color, "total": total, "iou": iou.mean(),
            "alphaL1": alpha_l1.mean(), "falsePositive": false_positive.mean()}


def image_metrics(rgb: Any, alpha: Any, target_rgb: Any, target_alpha: Any) -> list[dict[str, float]]:
    torch = __import__("torch")
    r = rgb if isinstance(rgb, torch.Tensor) else torch.as_tensor(rgb)
    a = alpha if isinstance(alpha, torch.Tensor) else torch.as_tensor(alpha)
    tr = target_rgb if isinstance(target_rgb, torch.Tensor) else torch.as_tensor(target_rgb, device=r.device)
    ta = target_alpha if isinstance(target_alpha, torch.Tensor) else torch.as_tensor(target_alpha, device=r.device)
    inter = (a * ta).mean((1, 2, 3))
    union = (a + ta - a * ta).mean((1, 2, 3)).clamp_min(1e-6)
    overlap = (a * ta).clamp_min(0)
    color = (torch.abs(r - tr) * (overlap + 0.05 * ta)).sum((1, 2, 3)) / (overlap + 0.05 * ta).sum((1, 2, 3)).clamp_min(1e-6)
    return [{"iou": float(i), "color": float(c)} for i, c in zip((inter / union).detach().cpu(), color.detach().cpu())]
