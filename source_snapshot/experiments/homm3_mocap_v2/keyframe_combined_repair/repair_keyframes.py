"""Shared weight (+ optional rest) repair driven by per-keyframe combined score.

For every deployed keyframe the repair renders the posed mesh with the
differentiable ``SkinImageRenderer`` and accumulates:

- silhouette loss (multiscale IoU + L1 + distance-weighted false positive,
  ``skin_image_objective.image_loss``),
- chroma loss (the same module's luma-normalized color term),
- a dense DINOv2 cosine loss: rendered RGB subject vs source-plate subject
  through ``facebook/dinov2-large`` (differentiable encoder; mean-pooled last
  hidden state, L2-normalized, like ``hybrid_dinov2.DinoEncoder``).

The optimized parameters are ONE shared ``TopologyWeightField`` (weld-respecting,
support-contained, <=8 influences, rows sum to 1) plus optionally ONE shared
``MeshField`` rest offset (bounded, ``project_mesh_step`` feasibility). Motion
(joint worlds), topology, UVs, albedo, and camera are frozen. There are no
per-frame parameters: every keyframe pulls on the same shared bind, which is
exactly what makes the combined score "well fit" across the reel instead of
overfit on one pose.

Proof: generated-artifact only. Not delivery input.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
# HERE is the module dir: parents[0]=homm3_mocap_v2, [1]=experiments, [2]=repo.
REPO = HERE.parents[2]
EXP = REPO / "experiments" / "homm3_mocap_v2"
# EXP first: sibling mocap modules win over HERE.
for _p in (str(HERE), str(REPO / "tools" / "homm3_silhouette_pose_fit")):
    if _p in sys.path:
        sys.path.remove(_p)
if str(EXP) not in sys.path:
    sys.path.insert(0, str(EXP))
sys.path.append(str(HERE))
sys.path.append(str(REPO / "tools" / "homm3_silhouette_pose_fit"))

from gpu_cascade_batch_lock import cascade_batch_lock  # noqa: E402
from skin_image_objective import SkinImageRenderer, image_loss  # noqa: E402
from skin_mesh_field import MeshField  # noqa: E402
from skin_surface_constraints import SurfaceConstraints  # noqa: E402
from topology_weight_field import TopologyWeightField  # noqa: E402


def dino_shard_indices(step: int, frames: int, shard_size: int) -> list[int]:
    """Deterministic rotating frame shard for the per-step DINO term.

    Pure python (no torch/CUDA) so contract tests can pin it. Consecutive
    steps cycle through ``ceil(frames / shard_size)`` shards whose union is
    every frame; the photo loss stays full-batch every step.
    """
    count = int(frames)
    shard = max(1, int(shard_size))
    if count <= 0:
        raise ValueError("frame count must be positive")
    shards = (count + shard - 1) // shard
    start = (int(step) % shards) * shard
    return list(range(start, min(start + shard, count)))


def dino_normalize(
    subjects: torch.Tensor, mean: torch.Tensor, std: torch.Tensor
) -> torch.Tensor:
    """Channel-normalize [N,3,H,W] float subjects, preserving autograd."""
    return (subjects - mean) / std


class DinoCosineLoss:
    """Differentiable dense DINOv2 cosine loss on white-composited subjects."""

    _FALLBACK_MEAN = (0.485, 0.456, 0.406)
    _FALLBACK_STD = (0.229, 0.224, 0.225)

    def __init__(self, *, device: str = "cuda", model_dtype: str = "float32") -> None:
        from transformers import AutoImageProcessor, Dinov2Model

        self.device = device
        self.processor = AutoImageProcessor.from_pretrained(
            "facebook/dinov2-large", do_center_crop=False
        )
        torch_dtype = torch.float16 if model_dtype == "float16" else torch.float32
        self.model = (
            Dinov2Model.from_pretrained("facebook/dinov2-large")
            .to(device, dtype=torch_dtype)
            .eval()
        )
        for param in self.model.parameters():
            param.requires_grad_(False)
        _mean = getattr(self.processor, "image_mean", None)
        if _mean is None:  # some processors report ndarray (ambiguous truth)
            _mean = self._FALLBACK_MEAN
        _std = getattr(self.processor, "image_std", None)
        if _std is None:
            _std = self._FALLBACK_STD
        self.image_mean = torch.as_tensor(list(_mean), device=device).reshape(1, 3, 1, 1)
        self.image_std = torch.as_tensor(list(_std), device=device).reshape(1, 3, 1, 1)

    def encode(self, rgb_subjects: torch.Tensor) -> torch.Tensor:
        """One-shot CPU-preprocessor encode; never use inside the loop."""
        from transformers import Dinov2Model as _M  # noqa: F401  (keeps import local)

        images = [
            (np.clip(frame.detach().cpu().numpy().transpose(1, 2, 0), 0.0, 1.0) * 255.0).astype(
                np.uint8
            )
            for frame in rgb_subjects
        ]
        inputs = self.processor(images=images, return_tensors="pt", do_center_crop=False)
        pixel = inputs["pixel_values"].to(self.device)
        hidden = self.model(pixel_values=pixel).last_hidden_state
        pooled = hidden.mean(dim=1)
        return torch.nn.functional.normalize(pooled, dim=-1)

    def encode_differentiable(
        self, rgb_subjects: torch.Tensor, *, batch: int = 8
    ) -> torch.Tensor:
        """GPU-only encode of [N,3,224,224] float subjects, grad-preserving.

        Normalizes on-device (no detach, no host roundtrip, no per-step
        preprocessor) and forwards in chunks to bound peak memory. The model
        stays frozen, so gradients land only on the input pixels and flow back
        into the mesh -- unlike encode, whose detach made the DINO term a
        constant. Deliberately no no_grad here.
        """
        if rgb_subjects.ndim != 4 or rgb_subjects.shape[1] != 3:
            raise ValueError("subjects must be [N,3,H,W]")
        target_dtype = next(self.model.parameters()).dtype
        normed = dino_normalize(
            rgb_subjects.to(dtype=torch.float32), self.image_mean, self.image_std
        )
        width = max(1, int(batch))
        parts = [
            self.model(pixel_values=normed[start : start + width].to(dtype=target_dtype))
            .last_hidden_state.mean(dim=1)
            for start in range(0, normed.shape[0], width)
        ]
        return torch.nn.functional.normalize(
            torch.cat(parts, dim=0).to(dtype=torch.float32), dim=-1
        )


def subject_window_from_alpha(alpha: np.ndarray, *, padding_ratio: float = 0.1) -> dict[str, int]:
    """Clip-locked union alpha AABB (square-padded) over [F,H,W] alpha."""
    rows, cols = np.where(np.any(alpha > 0.0039, axis=0))
    if len(rows) == 0:
        raise ValueError("keyframe reel has no alpha")
    x0, y0, x1, y1 = int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1
    width, height = x1 - x0, y1 - y0
    inner = max(width, height)
    pad_x0 = (inner - width) // 2
    pad_y0 = (inner - height) // 2
    margin = max(1, int(round(inner * padding_ratio)))
    return {
        "x0": x0 - pad_x0 - margin,
        "y0": y0 - pad_y0 - margin,
        "size": inner + 2 * margin,
    }


def crop_subjects(rgb: torch.Tensor, window: dict[str, int]) -> torch.Tensor:
    """Crop + bilinear-resize [F,3,H,W] subjects to 224x224 for DINOv2."""
    f, _, h, w = rgb.shape
    x0 = max(0, int(window["x0"]))
    y0 = max(0, int(window["y0"]))
    size = int(window["size"])
    x1 = min(w, x0 + size)
    y1 = min(h, y0 + size)
    cropped = rgb[:, :, y0:y1, x0:x1]
    return torch.nn.functional.interpolate(
        cropped, size=(224, 224), mode="bilinear", align_corners=False
    )


def repair_weights(
    *,
    rest_vertices: np.ndarray,
    triangles: np.ndarray,
    uvs: np.ndarray,
    albedo: np.ndarray,
    initial_weights: np.ndarray,
    joint_slots: np.ndarray,  # [V,S] deployed GLB joint ids per slot
    joint_worlds: np.ndarray,  # [F,J,4,4] frozen motion
    inverse_bind: np.ndarray,  # [J,4,4]
    camera: dict[str, object],
    source_rgb: np.ndarray,  # [F,H,W,3] float
    source_alpha: np.ndarray,  # [F,H,W,1] float
    source_distance: np.ndarray,  # [F,H,W] float
    resolution: int,
    iterations: int = 150,
    seconds: float = 600.0,
    allow_mesh: bool = False,
    dino_weight: float = 2.0,
    photo_weight: float = 10.0,
    dino_batch: int = 8,
    log: object = print,
) -> dict[str, object]:
    """Fit one shared weight field (+ optional shared rest) to all keyframes.

    Returns ``{"weights", "rest", "history", "elapsedSeconds", "dinoPolicy",
    "dinoShardSize"}``. The DINO term scores a rotating shard of ``dino_batch``
    frames per step (photo stays full-batch), so every frame steers the shared
    field over consecutive steps. Raises on
    non-finite objectives. Caller owns provenance + export gating.

    ``initial_weights`` is the slot-packed deployed skin ([V,S]); the field
    is built and returned in that same slot packing so support containment
    and the <=8-influence contract match the GLB the repair is scored
    against. ``joint_slots`` carries the deployed joint ids per slot.
    """
    from run_skin_mesh_pilot import deform, project_mesh_step, rest_barrier

    started = time.perf_counter()
    deadline = started + float(seconds)
    frames = len(joint_worlds)
    if not (len(source_rgb) == len(source_alpha) == len(source_distance) == frames):
        raise ValueError("keyframe/source count mismatch")
    if int(dino_batch) <= 0:
        raise ValueError("dino_batch must be positive")
    slots = np.asarray(joint_slots, dtype=np.int64)
    if slots.ndim != 2 or len(slots) != len(rest_vertices):
        raise ValueError("joint_slots must be [V,S] matching rest vertices")
    if np.asarray(initial_weights).shape != slots.shape:
        raise ValueError("initial_weights must be slot-packed [V,S] like the GLB")

    with cascade_batch_lock(REPO):
        field = TopologyWeightField(
            rest_vertices, triangles, initial_weights, rigid_rows=[], device="cuda"
        )
        slot_joints = torch.as_tensor(slots, device="cuda")
        regions = np.full(len(rest_vertices), "body")
        mesh_field = MeshField(
            rest_vertices, regions, frozen_regions=(), device="cuda"
        )
        surface = SurfaceConstraints(rest_vertices, triangles, device="cuda")
        renderer = SkinImageRenderer(triangles, uvs, albedo, camera, resolution)
        dino = DinoCosineLoss(device="cuda")

        transforms = torch.as_tensor(
            (joint_worlds @ inverse_bind[None])[:, :, :3],
            device="cuda",
            dtype=torch.float32,
        )
        rest_t = torch.as_tensor(rest_vertices, device="cuda", dtype=torch.float32)
        target_rgb = torch.as_tensor(source_rgb, device="cuda", dtype=torch.float32)
        target_alpha = torch.as_tensor(source_alpha, device="cuda", dtype=torch.float32)
        target_distance = torch.as_tensor(
            source_distance, device="cuda", dtype=torch.float32
        )
        # Targets are hoisted: validated once here, then image_loss runs with
        # validate=False every step (same-device no-op moves, no rescans).
        for _hoisted in (target_rgb, target_alpha, target_distance):
            if not torch.isfinite(_hoisted).all():
                raise ValueError("keyframe repair received non-finite target data")
        del _hoisted
        # DINO subjects are prepared once from the source plates (no grad).
        with torch.no_grad():
            window = subject_window_from_alpha(
                np.asarray(source_alpha[..., 0], dtype=np.float64)
            )
            src_nchw = (
                torch.as_tensor(source_rgb, device="cuda", dtype=torch.float32)
                .permute(0, 3, 1, 2)
                .contiguous()
            )
            src_subjects = crop_subjects(src_nchw, window)
            src_embeds = dino.encode(src_subjects).detach()

        parameters = list(field.parameters()) + (
            list(mesh_field.parameters()) if allow_mesh else []
        )
        optimizer = torch.optim.Adam(parameters, lr=0.025 if allow_mesh else 0.04)
        best = float("inf")
        best_state = None
        history: list[dict[str, object]] = []
        for step in range(int(iterations)):
            if time.perf_counter() >= deadline:
                break
            optimizer.zero_grad(set_to_none=True)
            slot_weights = field.weights()
            # Expand slot-packed rows to the dense [V,J] matrix deform()
            # contracts: each slot's weight lands on its joint id (scatter,
            # not one-hot matmul, because two slots may share a joint).
            weights = torch.zeros(
                (len(rest_vertices), int(slots.max()) + 1),
                device=slot_weights.device,
                dtype=slot_weights.dtype,
            )
            weights.scatter_add_(
                1,
                slot_joints,
                slot_weights,
            )
            rest = mesh_field.vertices() if allow_mesh else mesh_field.rest_vertices
            animated = deform(transforms, weights, rest)
            geometry = surface.loss(animated)
            regularity = field.penalty()
            rendered_rgb, rendered_alpha = renderer.render(animated)
            photo = image_loss(
                rendered_rgb, rendered_alpha, target_rgb, target_alpha, target_distance,
                validate=False,
            )["total"]
            # Rotating DINO shard; photo stays full-batch every step.
            shard = dino_shard_indices(step, frames, dino_batch)
            mesh_subjects = crop_subjects(
                rendered_rgb.permute(0, 3, 1, 2).contiguous(), window
            )
            mesh_embeds = dino.encode_differentiable(mesh_subjects[shard], batch=dino_batch)
            dino_loss = 1.0 - (mesh_embeds * src_embeds[shard]).sum(dim=1).mean()
            objective = (
                float(photo_weight) * photo
                + 3.0 * geometry
                + 25.0 * regularity
                + float(dino_weight) * dino_loss
            )
            if allow_mesh:
                objective = (
                    objective
                    + 10.0 * rest_barrier(rest, surface)
                    + 2.0 * mesh_field.penalty()
                )
            if not torch.isfinite(objective):
                raise ValueError("non-finite keyframe repair objective")
            score = float(objective.detach())
            if score < best:
                best = score
                best_state = (
                    {k: v.detach().clone() for k, v in field.state_dict().items()},
                    {k: v.detach().clone() for k, v in mesh_field.state_dict().items()},
                )
            objective.backward()
            torch.nn.utils.clip_grad_norm_(parameters, 2.0)
            previous_control = mesh_field.control.detach().clone()
            optimizer.step()
            if allow_mesh:
                project_mesh_step(mesh_field, surface, previous_control)
            if step % 25 == 0 or step == int(iterations) - 1:
                row = {
                    "step": step,
                    "objective": score,
                    "photo": float(photo.detach()),
                    "surface": float(geometry.detach()),
                    "dino": float(dino_loss.detach()),
                    "meshEnabled": allow_mesh,
                    "dinoFrames": len(shard),
                }
                history.append(row)
                log(str(row), flush=True) if hasattr(log, "__call__") else None
        if best_state is None:
            raise TimeoutError("budget expired before keyframe repair")
        field.load_state_dict(best_state[0])
        mesh_field.load_state_dict(best_state[1])
        field.validate()
        with torch.no_grad():
            learned_weights = field.weights().detach().cpu().numpy()
            learned_rest = (
                mesh_field.vertices().detach().cpu().numpy()
                if allow_mesh
                else np.asarray(rest_vertices, dtype=np.float64)
            )
    return {
        "weights": learned_weights,
        "rest": learned_rest,
        "history": history,
        "dinoPolicy": "rotating_shard_full_photo",
        "dinoShardSize": int(dino_batch),
        "elapsedSeconds": time.perf_counter() - started,
    }


__all__ = [
    "DinoCosineLoss",
    "subject_window_from_alpha",
    "crop_subjects",
    "dino_normalize",
    "dino_shard_indices",
    "repair_weights",
]
