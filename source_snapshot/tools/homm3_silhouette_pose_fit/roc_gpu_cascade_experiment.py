"""GPU-first experimental pose fitting lane.

This module is deliberately separate from the production Blender-backed
semantic hybrid runtime. It implements the first research milestone from the
GPU cascade proposal:

* decode a Meshy GLB once;
* keep skinning data and triangle-surface samples on CUDA;
* evaluate a batch of poses without Blender, PNGs, or per-vertex Python work;
* register the clip with a discrete root solve, then a shared base pose,
  a small root refit, per-frame dynamic joints, optional coupled rescue,
  and absolute fine polish;
* score that solve with the same silhouette, Huber depth, Lab chroma, and
  collision terms as ``one_bone_depth``, or with an explicit
  ``score_mode='dinov3_dense'`` ablation that replaces those terms;
* use the same filled-triangle CUDA raster for optimization and preview when
  ``exact_raster_enabled`` is true.

Centroid, occupancy-count, and SDF mix-ins are rejected: they hid occupancy
and depth misses behind a second score. The sampled-surface raster remains in
the module for diagnostics; cascade fitting requires filled triangles.
"""
from __future__ import annotations

import itertools
import json
import math
import os
import copy
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image, ImageDraw

from roc_geometric_proxy import ProxyAsset, gltf_uv_to_grid_sample, load_asset, validate_bind_pose
from pose_fit_blender import resolve_pose_fit_blender


MOTION_ROOT_KEY = "__motion_root__"
MOTION_ROOT_ROTATION_KEY = "__motion_root_rotation__"
CASCADE_SCORE_MODES = ("geometry", "dinov3_dense", "dinov3_geometry_consensus")
DEFAULT_CASCADE_DINO_V3_MODEL_ID = "facebook/dinov3-vits16-pretrain-lvd1689m"
JOINT_SOLVER_MODES = ("discrete", "branch_vector")
DINOV3_DENSE_BONE_ORDER_MODES = ("asset", "dependency")
CASCADE_LIVE_PREVIEW_MAX_FRAMES = 4
CASCADE_LIVE_PREVIEW_PANE_WIDTH = 96
CASCADE_LIVE_PREVIEW_CHANGE_GAIN = 4.0
GLTF_TO_BLENDER_BASIS = np.asarray(
    ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    dtype=np.float64,
)


def _normalize_preview_matte(
    value: tuple[int, int, int] | str | None,
) -> tuple[int, int, int] | None:
    """Normalize the inspection matte without changing the RGBA render.

    The Blender proof remains transparent.  GIF/MP4 viewers commonly composite
    transparent pixels against black, which makes dark armor and boots appear
    to vanish.  Delivery previews therefore use a neutral matte by default,
    while the original ``frame_*.png`` files retain their alpha channel.
    """
    if value is None:
        return None
    if isinstance(value, str):
        token = value.strip().lstrip("#")
        if len(token) == 3:
            token = "".join(char * 2 for char in token)
        if len(token) != 6:
            raise ValueError("preview_matte must be #RRGGBB, RGB, or None")
        try:
            value = tuple(int(token[index : index + 2], 16) for index in (0, 2, 4))
        except ValueError as exc:
            raise ValueError("preview_matte must be #RRGGBB, RGB, or None") from exc
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise ValueError("preview_matte must be #RRGGBB, RGB, or None")
    channels = tuple(int(channel) for channel in value)
    if any(channel < 0 or channel > 255 for channel in channels):
        raise ValueError("preview_matte channels must be in the range 0..255")
    return channels


def _write_preview_matte(
    source_path: Path,
    destination_path: Path,
    matte: tuple[int, int, int] | None,
) -> None:
    """Write an RGB inspection frame composited from the exact RGBA proof."""
    with Image.open(source_path) as source:
        rgba = source.convert("RGBA")
        if matte is None:
            preview = rgba.convert("RGB")
        else:
            background = Image.new("RGBA", rgba.size, (*matte, 255))
            background.alpha_composite(rgba)
            preview = background.convert("RGB")
        preview.save(destination_path, format="PNG", compress_level=0)
        preview.close()


class _GpuPreviewWorker:
    """Small export-only worker independent of the dynamic hybrid runtime."""

    def __init__(self, *, blender: Path, worker_script: Path):
        fd, stderr_name = tempfile.mkstemp(prefix="gpu_preview_blender_", suffix=".stderr.log")
        os.close(fd)
        self._stderr_path = Path(stderr_name)
        self._stderr = self._stderr_path.open("w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [str(blender), "-b", "--python", str(worker_script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            text=True,
            bufsize=1,
        )

    def request(self, command: Mapping[str, Any]) -> dict[str, Any]:
        if self.proc.poll() is not None:
            self._stderr.flush()
            raise RuntimeError({
                "ok": False,
                "error": "GPU preview Blender worker exited before request",
                "returncode": self.proc.returncode,
                "command": command.get("cmd"),
                "stderr": self._stderr_path.read_text(encoding="utf-8", errors="replace")[-8000:],
            })
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        self.proc.stdin.write(json.dumps(dict(command)) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                self._stderr.flush()
                raise RuntimeError({
                    "ok": False,
                    "error": "GPU preview Blender worker exited",
                    "returncode": self.proc.poll(),
                    "command": command.get("cmd"),
                    "stderr": self._stderr_path.read_text(encoding="utf-8", errors="replace")[-8000:],
                })
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(response, dict):
                raise RuntimeError({"ok": False, "error": "invalid Blender worker response", "response": response})
            return response

    def close(self) -> None:
        try:
            if self.proc.poll() is None:
                try:
                    self.request({"cmd": "quit"})
                finally:
                    self.proc.wait(timeout=10)
        finally:
            self._stderr.close()


def _select_device(value: str) -> str:
    import torch

    requested = str(value).strip().lower()
    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested.startswith("cuda"):
        if not torch.cuda.is_available():
            raise RuntimeError("GPU cascade requested CUDA, but torch.cuda.is_available() is false")
        return requested
    if requested == "cpu":
        return requested
    raise ValueError("device must be auto, cuda, cuda:<index>, or cpu")


def capability_report() -> dict[str, Any]:
    """Report the installed backends without importing optional CUDA packages."""
    import importlib.util

    from nvdiffrast_local import ensure_local_nvdiffrast

    ensure_local_nvdiffrast(required=False)
    try:
        import torch
    except Exception as exc:  # pragma: no cover - environment diagnostic
        return {
            "torch": False,
            "torchError": repr(exc),
            "cuda": False,
            "nvdiffrast": bool(importlib.util.find_spec("nvdiffrast")),
        }
    nvdiffrast_available = bool(importlib.util.find_spec("nvdiffrast"))
    return {
        "torch": True,
        "torchVersion": str(torch.__version__),
        "cuda": bool(torch.cuda.is_available()),
        "cudaDevice": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "nvdiffrast": nvdiffrast_available,
        "candidateRenderer": "torch_soft_triangle_surface",
        "exactTriangleRenderer": "nvdiffrast" if nvdiffrast_available else None,
    }


def rgb_hwc_batch_to_pil_images(rgb) -> list[Image.Image]:
    """Convert a ``(B, H, W, 3)`` float RGB tensor in ``[0, 1]`` to PIL images."""
    import torch

    if not isinstance(rgb, torch.Tensor):
        raise TypeError("predicted RGB must be a torch.Tensor")
    if rgb.ndim != 4 or int(rgb.shape[-1]) != 3:
        raise ValueError("predicted RGB must have shape (B, H, W, 3)")
    cpu = rgb.detach().float().clamp(0.0, 1.0).cpu().numpy()
    images: list[Image.Image] = []
    for frame in cpu:
        pixels = np.ascontiguousarray((frame * 255.0).round().astype(np.uint8))
        images.append(Image.fromarray(pixels, mode="RGB"))
    return images


def dense_semantic_unit_interval(dense_semantic_quality):
    """Map cascade DINOv3 quality onto ``[0, 1]``.

    Dense keep stores ``1 - cosine_distance`` with distance in ``[0, 2]``, so
    the raw value lives in ``[-1, 1]``. Geometric means with silhouette IoU
    need the unit interval; this is ``1 - distance/2``.
    """
    return (dense_semantic_quality.clamp(-1.0, 1.0) + 1.0) * 0.5


def _minmax_normalize_keep_channel(values, *, flat_fill: float = 1.0, flat_eps: float = 1e-6):
    """Affine-map a channel to ``[0, 1]``; flat contrast becomes ``flat_fill``."""
    lo = values.min()
    hi = values.max()
    span = hi - lo
    if float(span.detach().item()) <= float(flat_eps):
        return values.new_full(values.shape, float(flat_fill))
    return (values - lo) / span


def dinov3_geometry_consensus_score(
    silhouette_iou,
    dense_semantic_quality,
    *,
    frame_positions=None,
    flat_eps: float = 1e-6,
):
    """Geometric mean of IoU and soft within-frame-normalized DINOv3.

    Raw DINOv3 quality is ``1 - cosine_distance`` on ``[0, 2]``, so values
    cluster near ~0.9. A geometric mean against that raw band is monotone in
    IoU alone. This:

    1. maps DINO onto ``[0, 1]`` via ``1 - distance/2``;
    2. logit-min-maxes that band **within each frame's candidate pack** so
       relative DINO contrast has full dynamic range (flat packs -> ``0.5``);
    3. softens with ``0.5 + 0.5 * dino_n`` before the geometric mean so the
       worst-in-pack DINO cannot hard-zero a strong silhouette.

    Keep score: ``sqrt(iou * (0.5 + 0.5 * dino_n))``.
    """
    import torch

    if not isinstance(silhouette_iou, torch.Tensor) or not isinstance(
        dense_semantic_quality, torch.Tensor
    ):
        raise TypeError("consensus score requires torch tensors")
    if int(silhouette_iou.shape[0]) != int(dense_semantic_quality.shape[0]):
        raise ValueError(
            "consensus silhouette and dense batches differ: "
            f"iou={int(silhouette_iou.shape[0])} dense={int(dense_semantic_quality.shape[0])}"
        )
    iou = silhouette_iou.clamp_min(0.0).to(dtype=torch.float32)
    dino_unit = dense_semantic_unit_interval(dense_semantic_quality).to(dtype=torch.float32)
    batch = int(iou.shape[0])
    if batch < 1:
        raise ValueError("consensus score batch is empty")
    if frame_positions is None:
        positions = torch.zeros((batch,), dtype=torch.long, device=iou.device)
    else:
        positions = frame_positions.detach().to(device=iou.device, dtype=torch.long)
        if int(positions.numel()) == 1 and batch > 1:
            positions = positions.expand(batch)
        elif int(positions.numel()) != batch:
            raise ValueError(
                "consensus frame_positions do not match batch: "
                f"poses={batch} frames={int(positions.numel())}"
            )
    # flat_eps reserved for callers / future span gates; logit_minmax already
    # treats near-flat packs as 0.5 via normalize_keep_scores_for_joint_step.
    _ = float(flat_eps)
    consensus = torch.empty((batch,), dtype=torch.float32, device=iou.device)
    for frame_id in torch.unique(positions).tolist():
        mask = positions == int(frame_id)
        iou_g = iou[mask]
        dino_g = dino_unit[mask]
        dino_n = normalize_keep_scores_for_joint_step(dino_g, mode="logit_minmax")
        dino_soft = 0.5 + 0.5 * dino_n.clamp(0.0, 1.0)
        consensus[mask] = (iou_g * dino_soft).sqrt()
    return consensus


def dense_semantic_quality_from_distance(distance: float) -> float:
    """Convert a local-window dense distance in ``[0, 2]`` into a keep score."""
    value = 1.0 - float(distance)
    if not math.isfinite(value):
        raise RuntimeError(f"dense semantic quality is not finite: distance={distance}")
    return value


def crop_rgb_hwc_subject_square(
    rgb,
    padding_frac: float,
    *,
    background_rgb: tuple[int, int, int] = (32, 32, 32),
):
    """GPU subject crop matching opaque-RGB ``load_subject_image_from_image``.

    Predicted cascade RGB has no alpha, so the PIL path used the top-left 8×8
    median and a gray square pad. Each frame can have a different square size.
    """
    import torch

    if not isinstance(rgb, torch.Tensor):
        raise TypeError("predicted RGB must be a torch.Tensor")
    if rgb.ndim != 4 or int(rgb.shape[-1]) != 3:
        raise ValueError("predicted RGB must have shape (B, H, W, 3)")
    if not math.isfinite(float(padding_frac)) or float(padding_frac) < 0.0:
        raise ValueError("subject_padding_frac must be finite and non-negative")
    batch, height, width, _channels = (int(size) for size in rgb.shape)
    if height < 8 or width < 8:
        raise ValueError("subject crop needs at least 8x8 RGB")
    fill = torch.tensor(
        [component / 255.0 for component in background_rgb],
        dtype=torch.float32,
        device=rgb.device,
    )
    uint8 = rgb.detach().float().clamp(0.0, 1.0) * 255.0
    cropped = []
    for index in range(batch):
        frame = uint8[index]
        background = frame[:8, :8].reshape(-1, 3).median(dim=0).values
        distance = torch.linalg.vector_norm(frame - background, dim=-1)
        mask = distance > 18.0
        source = rgb[index].detach().float().clamp(0.0, 1.0)
        if not bool(mask.any()):
            cropped.append(source)
            continue
        ys, xs = torch.where(mask)
        x0 = int(xs.min().item())
        x1 = int(xs.max().item()) + 1
        y0 = int(ys.min().item())
        y1 = int(ys.max().item()) + 1
        pad = int(round(max(x1 - x0, y1 - y0) * float(padding_frac)))
        x0c = max(0, x0 - pad)
        y0c = max(0, y0 - pad)
        x1c = min(width, x1 + pad)
        y1c = min(height, y1 + pad)
        crop = source[y0c:y1c, x0c:x1c]
        side = max(int(crop.shape[0]), int(crop.shape[1]))
        canvas = fill.view(1, 1, 3).expand(side, side, 3).clone()
        origin_y = (side - int(crop.shape[0])) // 2
        origin_x = (side - int(crop.shape[1])) // 2
        canvas[
            origin_y : origin_y + int(crop.shape[0]),
            origin_x : origin_x + int(crop.shape[1]),
        ] = crop
        cropped.append(canvas)
    return cropped


def _stack_dense_target_grids(target_grids_by_frame: Sequence[Mapping[str, Any]], layers):
    import torch

    stacked: dict[str, Any] = {}
    for layer in layers:
        pieces = []
        for frame_index, frame_grids in enumerate(target_grids_by_frame):
            if layer not in frame_grids:
                raise ValueError(
                    f"dense semantic target grids missing layer {layer!r} on frame {frame_index}"
                )
            grid = frame_grids[layer]
            if getattr(grid, "ndim", None) == 3:
                grid = grid.unsqueeze(0)
            if int(grid.shape[0]) != 1:
                raise ValueError("each cached target grid must be a single image")
            pieces.append(grid)
        stacked[layer] = torch.cat(pieces, dim=0)
    return stacked


def score_dense_semantic_rgb_batch(
    scorer,
    *,
    target_grids_by_frame: Sequence[Mapping[str, Any]],
    predicted_rgb,
    frame_positions,
    batch_size: int,
    window_radius: int,
    position_weight: float,
    autograd_enabled: bool = False,
    crop_fn=None,
    subject_crop: bool = False,
    subject_padding_frac: float = 0.18,
):
    """Score every RGB candidate against its frame's cached DINOv3 grids.

    Geometry terms are not consulted. Mixed sprite frames share one ViT
    microbatch; each row is scored against that frame's cached target grid.
    """
    import torch

    if crop_fn is not None:
        raise ValueError(
            "score_dense_semantic_rgb_batch does not accept a PIL crop_fn; "
            "set subject_crop=True for the GPU subject crop"
        )
    extractor_name = (
        "extract_layers_from_rgb_hwc_autograd"
        if bool(autograd_enabled)
        else "extract_layers_from_rgb_hwc"
    )
    extractor = getattr(scorer, extractor_name, None)
    if not callable(extractor):
        raise TypeError(f"dense semantic scorer must implement {extractor_name}")
    if not callable(getattr(scorer, "score_grid_layers_batch_mean_torch", None)):
        raise TypeError(
            "dense semantic scorer must implement score_grid_layers_batch_mean_torch"
        )
    if int(batch_size) < 1:
        raise ValueError("dense_semantic_batch_size must be at least 1")
    if predicted_rgb.ndim != 4 or int(predicted_rgb.shape[-1]) != 3:
        raise ValueError("predicted RGB must have shape (B, H, W, 3)")
    batch = int(predicted_rgb.shape[0])
    if int(frame_positions.numel()) != batch:
        raise ValueError(
            "dense semantic batch does not match frame_positions: "
            f"poses={batch} frames={int(frame_positions.numel())}"
        )
    if not target_grids_by_frame:
        raise ValueError("dense semantic target grids are empty")
    layers = tuple(getattr(scorer, "feature_layers"))
    if not layers:
        raise ValueError("dense semantic scorer feature_layers cannot be empty")
    stacked_targets = _stack_dense_target_grids(target_grids_by_frame, layers)
    positions = frame_positions.detach().to(
        device=stacked_targets[layers[0]].device,
        dtype=torch.long,
    )
    if bool((positions < 0).any() or (positions >= len(target_grids_by_frame)).any()):
        raise ValueError(
            "dense semantic frame_position is outside "
            f"0..{len(target_grids_by_frame) - 1}"
        )
    rgb_batch = predicted_rgb
    if bool(subject_crop):
        rgb_batch = crop_rgb_hwc_subject_square(
            predicted_rgb,
            float(subject_padding_frac),
        )
    qualities = torch.empty((batch,), dtype=torch.float32, device=predicted_rgb.device)
    for start in range(0, batch, int(batch_size)):
        end = min(start + int(batch_size), batch)
        chunk_rgb = rgb_batch[start:end]
        chunk_positions = positions[start:end]
        candidate_grids = extractor(chunk_rgb)
        target_chunk = {
            layer: stacked_targets[layer].index_select(0, chunk_positions)
            for layer in layers
        }
        distances = scorer.score_grid_layers_batch_mean_torch(
            target_chunk,
            candidate_grids,
            window_radius=int(window_radius),
            position_weight=float(position_weight),
        )
        if int(distances.shape[0]) != (end - start):
            raise RuntimeError(
                "dense semantic scorer returned "
                f"{int(distances.shape[0])} scores for {end - start} candidates"
            )
        qualities[start:end] = 1.0 - distances.float()
    if not bool(torch.isfinite(qualities).all()):
        raise RuntimeError("dense semantic qualities are not finite")
    return qualities


# Process-local collision tables keyed by (mesh, sample, hops, margin, device).
# Same rigidized GLB across clips of one unit should not rebuild geodesic pairs.
_MESH_COLLISION_TABLE_CACHE: dict[tuple, dict] = {}


@dataclass(frozen=True)
class GpuCascadeConfig:
    """Controls for the isolated GPU experiment.

    Values are intentionally independent of ``RocHybridConfig``. This keeps
    an experimental optimizer from silently changing the proven Blender lane.
    """

    device: str = "cuda"
    resolution: tuple[int, int] = (96, 86)
    alpha_threshold: int = 8
    max_triangles_per_primitive: int = 2048
    samples_per_triangle: int = 5
    raster_sigma_px: float = 1.6
    raster_point_chunk: int = 256
    score_centroid_weight: float = 0.0
    score_occupancy_weight: float = 0.0
    # One-sided target signed-distance guidance. This gives projected surface
    # points a useful long-range gradient while they are outside the sprite.
    sdf_weight: float = 0.0
    sdf_max_distance_px: float = 24.0
    # Early 64-hypothesis whole-body extra-rotation + translation, before joints.
    # False keeps the profile heading (identity extra-rotation). Deferred yaw
    # after joints still runs when root_rotation_defer_camera_up is True.
    root_search_enabled: bool = True
    root_hypotheses: int = 64
    root_rotation_limit_deg: float = 180.0
    # Frame 00 is a tight window around the profile camera heading
    # (identity extra rotation). Later frames step from the previous
    # heading. A ±180 Sobol search plus chroma_weight >> silhouette
    # discards a silhouette-correct idle in favor of a Lab-better spin.
    root_rotation_first_frame_limit_deg: float = 30.0
    root_rotation_per_frame_limit_deg: float = 30.0
    # Ground-plane turn around camera_up (walk the opposite direction).
    # Roll around camera_forward still uses root_rotation_limit_deg so a
    # Meshy bind can align to the profile camera.
    root_rotation_camera_up_limit_deg: float = 45.0
    # Initial root hypothesis scores bind bones. Spread wings plus yaw is a
    # cheap silhouette win. Keep camera_up at the profile heading until
    # after joint stages, then search it against the posed mesh.
    root_rotation_defer_camera_up: bool = True
    # When defer is on, the late ``root_yaw`` pass searches camera_up only.
    # Profile sprites should keep heading via bone articulation and
    # forward/right macro root instead of a post-joint sideways spin.
    root_rotation_after_joints_yaw_enabled: bool = True
    root_translation_radius_body_lengths: float = 0.35
    # Camera-space channels that are allowed to act as a rigid-body seed. A
    # profile sprite usually needs roll around camera-forward to align a Meshy
    # bind pose, but allowing yaw/pitch at the same time creates cheap
    # rear-view and upside-down minima.
    root_rotation_axes: tuple[str, ...] = (
        "camera_forward",
        "camera_right",
        "camera_up",
    )
    root_translation_axes: tuple[str, ...] = ("lateral", "vertical")
    # None searches each selected frame independently; an integer searches
    # one anchor frame and seeds the same broad hypothesis into the clip.
    root_search_frame: int | None = None
    root_iterations: int = 20
    articulated_iterations: int = 2
    fine_iterations: int = 2
    learning_rate: float = 0.045
    fine_learning_rate: float = 0.012
    # Root Adam uses ``learning_rate`` as a whole-mesh translation step.
    # Joint keep is improvement versus the current pose.
    # The meshes were built around the sprites, so absolute
    # depth/chroma/silhouette is the pose authority. Unique remainder
    # may only break ties or add extra credit when the sprite match
    # does not get worse. Extra collision still vetoes a pretzel, but
    # modest contact that the sprite itself shows (sword on torso)
    # must not block a sprite-improving move
    # (``joint_collision_positive_abs_slack``). Candidate zero has
    # keep 0. Fine and mid polish use absolute gain only. After
    # independent per-frame winners, consensus walks 0→N and N→0 on
    # separate copies (including root rotation), then keeps one complete
    # pose per frame. A local joint angle is not a world direction: mixing
    # joints across those copies is wrong when parent or root rotation
    # differs. Adopt when the sprite stays within
    # ``joint_temporal_consensus_tie_bonus``. One snapshot copy only moves
    # one hop; the reverse sweep is how a late walk pose can correct early
    # frames. A real budget (for example 0.01) trades bounded sprite score
    # for temporal agreement; 1e-5 breaks exact ties only.
    # ``joint_probe_rungs`` scores ±1..N steps as siblings so
    # 15° worse and 45° better still keeps 45°. Local X/Y/Z and optional
    # diagonal directions are scored as one family. Grow past that window
    # only when a frame's winner sits on the current edge. Pack those
    # probes into ``joint_score_raster_batch`` **pose slots** (hypotheses ×
    # clip frames). ``hyps_per_launch = pose_slots // frame_count``. A slot
    # count below the clip length packs **one** hypothesis per GPU launch and
    # starves the raster. Fused-push uses ≥512 so an 18–32 frame clip still
    # packs many hypotheses. ``joint_pass_limit_deg``
    # 0 means ``joint_limit_deg``. ``articulated_iterations`` is max
    # skeleton rounds. A round with no new probe keep stops early, and
    # later rounds only re-probe movers plus parent/child neighbors.
    # Adam root stops after ``adam_stall_reject_streak`` rejected steps.
    # Temporal consensus runs only after a probe kept a new angle.
    # When ``joint_adaptive_step_enabled``, base/mid/fine/rescue do not
    # run. One articulated walk includes fine-only leaves. Each frame's
    # unit step is lerped from ``fine_joint_step_deg`` to
    # ``joint_step_deg`` using that frame's current geometryScore:
    # score >= ``joint_step_score_fine`` -> fine tweaks only; score <=
    # ``joint_step_score_coarse`` -> the old 15/30/45 window. Idle
    # after a good profile init must not be offered a 45 deg neck yank.
    joint_step_deg: float = 15.0
    fine_joint_step_deg: float = 2.5
    joint_adaptive_step_enabled: bool = True
    joint_step_score_coarse: float = 0.45
    joint_step_score_fine: float = 0.80
    # How keep scores are stretched before the 0.45/0.80 step lerp.
    # ``logit_minmax`` is keep: logit then min-max so a tight band near 1
    # still splits idle (fine rungs) from walk (coarse rungs). ``raw``
    # treats every high DINOv3 frame as fine.
    joint_step_score_norm: str = "logit_minmax"
    joint_pass_limit_deg: float = 0.0
    fine_joint_pass_limit_deg: float = 0.0
    joint_probe_rungs: int = 3
    joint_score_raster_batch: int = 512
    # Occupancy+depth joint probes: skip Lab RGB only. Collision still
    # scores. Raster only free frames (and optionally the worst N of those).
    # When > 0 and occupancy_only is false, articulated probes still raster
    # only that worst-N subset but run the active score mode (including DINO).
    # Experiment lane.
    cheap_joint_probe_occupancy_only: bool = False
    cheap_joint_probe_frame_count: int = 0
    joint_search_axes: tuple[str, ...] = ("x", "y", "z")
    joint_diagonal_axes: int = 6
    joint_absolute_gain_weight: float = 1.0
    joint_unique_gain_weight: float = 0.35
    fine_unique_gain_weight: float = 0.0
    joint_keep_min_improvement: float = 1e-6
    # When on, a frame whose target PNG barely changed vs the previous
    # frame cannot keep a different probe. That tests whether idle wiggle
    # is per-frame DINOv3 argmax on still sprites. Off by default.
    joint_keep_still_sprite_lock: bool = False
    joint_keep_still_sprite_rgb_mad: float = 0.015
    # Sprite-to-sprite change map keep: a probe may change a still plate
    # only as much as that sprite changed versus the previous PNG. Excess
    # is a veto on still plates only; DINOv3 is not mixed. Mixing a change
    # penalty into keep dropped angel dinov3 from ~0.96 to 0.82. A veto on
    # every plate froze frames 01–27 (first step off bind exceeds sprite
    # delta). Walk plates keep unconstrained DINOv3.
    joint_keep_sprite_change_gate: bool = False
    joint_keep_sprite_change_weight: float = 1.0
    joint_keep_sprite_change_slack: float = 0.0
    # Extra collision below this amount cannot veto a move that improved
    # absolute sprite match. Units are the same as ``collisionError``.
    joint_collision_positive_abs_slack: float = 0.12
    joint_temporal_consensus_enabled: bool = True
    joint_temporal_consensus_tie_bonus: float = 1e-5
    # Sequential 0→N then N→0 adopt. False keeps the old one-hop
    # copy-prev / copy-next / lerp from a single snapshot.
    joint_temporal_consensus_bidirectional: bool = True
    # Forward and reverse walks are independent copies of the per-frame
    # winners. Reverse starts from the locked idle pose at the end of the
    # chained sequence (trailing idle / move-end then idle). Death does not.
    # Per frame, keep one whole pose (all joints + root rotation) from
    # original, forward, or reverse after scoring those complete poses.
    # Mixing one joint from forward with another from reverse is wrong:
    # the same local angle points a different way if parent/root rotation
    # differs. Death does not return to idle.
    joint_temporal_consensus_idle_end: bool = True
    joint_temporal_consensus_independent_passes: bool = True
    joint_temporal_consensus_whole_pose: bool = True
    idle_prefix_frames: int = 0
    idle_suffix_frames: int = 0
    idle_end_anchor: bool = False
    # When True, trailing idle suffix clip-local frames mirror the leading idle
    # prefix during joint probes (suffix locked) and again before export.
    idle_suffix_mirror_prefix_enabled: bool = False
    # Coupled all-bone gradient ladder between root refit and articulated.
    # One backward pass on absolute sprite match gives a coupled direction;
    # the exact raster then scores each magnitude in
    # ``gradient_ladder_step_degs`` per frame, and the step still has to win
    # the same sprite-match keep as the discrete walk. Placement is early on
    # purpose: gradient signal is strongest while the pose is far from the
    # sprite, and the ladder's job is to hand articulated a better basin,
    # not to polish one already chosen. Frames whose masked gradient norm is
    # below ``gradient_ladder_min_gradient_norm`` keep the current pose.
    gradient_ladder_enabled: bool = False
    gradient_ladder_iterations: int = 1
    gradient_ladder_step_degs: tuple[float, ...] = (2.5, 5.0, 10.0)
    gradient_ladder_min_gradient_norm: float = 1e-6
    # Chain-space surface navigation after root refit, before articulated.
    # The target is a point in the chain's X-joint space identified by the
    # occupancy/chroma surface, not a tip keypoint. chain_grad uses equal
    # per-bone angle share so overlapping hips→leaf paths cannot spend the
    # whole step on the torso. branch_trust uses disjoint segments and a
    # per-frame trust radius (not a clip-wide pose). Disabled by default.
    # CURRENT_CASCADE_KEEP refuses enabled runs.
    joint_solver_mode: str = "discrete"
    chain_space_enabled: bool = False
    chain_space_mode: str = "chain_grad"
    chain_space_iterations: int = 3
    chain_space_step_degs: tuple[float, ...] = (5.0, 10.0, 20.0, 40.0)
    chain_space_min_gradient_norm: float = 1e-6
    chain_space_trust_radius_deg: float = 20.0
    chain_space_trust_radius_min_deg: float = 1.25
    chain_space_trust_radius_max_deg: float = 40.0
    chain_space_min_clip_improvement: float = 1e-6
    # Stop chain-space after this many clip evaluations (the same counter
    # control reports). None keeps the iteration cap and the no-move stop.
    chain_space_eval_budget: int | None = None
    # Simulated annealing broad-pose search between root Adam and base pose.
    # Every other cascade stage starts from bind and makes local moves; when
    # the correct pose is in a different basin (limb swapped, weapon turned),
    # no local step escapes. SA explores globally: each restart samples a
    # random pose within joint limits, then iterates with geometric cooling.
    # Perturbation magnitude and bone count both scale with temperature, so
    # early iterations move many bones by large angles (broad strokes) and
    # late iterations move few bones by small angles (basin settling).
    # Metropolis acceptance lets worsening moves through with probability
    # exp(delta/T), which is how the search crosses between basins.
    # Per-frame independent chains: each frame finds its own basin against
    # its own sprite target. Temporal consistency is downstream's job.
    # Root is not perturbed; root search + Adam already handle placement.
    sa_enabled: bool = False
    sa_restarts: int = 4
    sa_iterations: int = 200
    sa_initial_temperature: float = 0.1
    sa_final_temperature: float = 0.001
    sa_perturbation_scale_deg: float = 45.0
    sa_bone_fraction: float = 0.5
    sa_seed: int | None = None
    # Restart from the current best pose (post-root bind) with a full-T
    # perturbation instead of a fully random pose. Random inits score badly
    # under collision and never beat bind, which looks like a stiff mesh that
    # only the motion root rotates.
    sa_seed_from_current: bool = True
    # Skip proximal hierarchy bones during SA. Rotating Bone_000/Bone_001 reads
    # as whole-body spin; limbs start at depth 3 on crusader.
    sa_min_bone_depth: int = 3
    # Collision weight used only while scoring SA proposals. None keeps the
    # normal cascade collision_weight. 0.0 avoids collision-penalty hell on
    # broad exploratory poses; downstream stages restore full collision.
    sa_collision_weight: float | None = 0.0
    # IK-based broad-pose initialization between root Adam and base pose.
    # authored: LLM stick figures + CCD. silhouette_miss: incremental blob IK
    # (distal local-axis search, grow one parent at a time, keep best interim).
    ik_enabled: bool = False
    ik_keypoints_path: str | None = None
    ik_bone_roles_path: str | None = None
    # authored: LLM/human keypoints.json. silhouette_miss: derive sparse targets
    # from excess→missing blob pairing after root Adam (no per-clip stick files).
    ik_keypoints_source: str = "authored"
    ik_miss_depth_tolerance: float = 0.12
    ik_miss_min_component_area: int = 24
    ik_miss_max_pairs: int = 2
    ik_miss_predicted_alpha_threshold: float = 0.5
    ik_miss_max_tip_distance_px: float = 56.0
    ik_miss_max_centroid_distance_px: float = 72.0
    ik_miss_max_area_ratio: float = 4.0
    ik_miss_min_displacement_alignment: float = 0.15
    ik_iterations: int = 16
    ik_max_step_deg: float = 15.0
    ik_require_improvement: bool = True
    # silhouette_miss incremental blob IK. Regional IoU is measured in the
    # dilated union of the red excess blob and its paired blue missing blob.
    # Distal assigned bone moves first; parents unlock only while IoU stays
    # below the target. Spinal bones (depth < proximal_min_depth) get a small
    # rotation cap. Best interim chain length is kept.
    ik_blob_iou_target: float = 0.9
    ik_proximal_min_depth: int = 3
    ik_proximal_max_step_deg: float = 5.0
    ik_max_chain_depth: int = 6
    ik_repair_dilate_px: int = 4
    ik_blob_search_rounds: int = 3
    # silhouette_miss scoring during blob search. regional_iou: IoU inside the
    # dilated excess+missing repair neighborhood (legacy). frame_hybrid: full
    # per-frame hybrid score so IK moves toward the same metric articulated walk
    # optimizes. ik_iterations is the number of outer passes that re-derive blob
    # jobs from the current interim pose (authored CCD still uses ik_iterations
    # as max CCD steps per chain).
    ik_silhouette_score_mode: str = "regional_iou"
    # Dynamic movement policy for silhouette_miss (no LLM authorship).
    ik_job_order_mode: str = "pair_rank"
    ik_step_scale_mode: str = "fixed"
    ik_step_displacement_ref_px: float = 56.0
    ik_step_scale_min: float = 0.4
    ik_step_scale_max: float = 1.6
    ik_chain_start_mode: str = "distal"
    ik_chain_displacement_ref_px: float = 40.0
    ik_frame_order_mode: str = "clip"
    ik_influence_dominance_min: float = 0.0
    ik_dynamic_stop_enabled: bool = False
    # Post-articulated per-frame head pin from local anatomical box detection on
    # target sprites (Grounding DINO). CCD on the cervical chain only; each frame
    # keeps the pin only when hybrid score improves.
    anatomy_head_pin_enabled: bool = False
    anatomy_head_pin_parts: tuple[str, ...] = ("head",)
    anatomy_head_pin_bone_roles_path: str = ""
    anatomy_head_pin_chain_bones: tuple[str, ...] = (
        "Bone_016",
        "Bone_015",
        "Bone_014",
    )
    anatomy_head_pin_iterations: int = 16
    anatomy_head_pin_max_step_deg: float = 12.0
    anatomy_head_pin_require_improvement: bool = True
    anatomy_head_pin_skip_idle_prefix: bool = False
    # hybrid: full per-frame hybrid. geometry: geometryScore only. silhouette: IoU only.
    anatomy_head_pin_accept_metric: str = "hybrid"
    # Macro init before articulated walk: idle snapshot + error_leverage-led
    # coarse root yaw + top-bone combo probes (transit clips; no LLM authorship).
    idle_fused_macro_enabled: bool = False
    # When initial_poses are supplied, skip macro init so seeded solutions are not remacroed.
    idle_fused_skip_macro_when_seeded: bool = True
    idle_fused_skip_reroot_when_seeded: bool = True
    # When initial_poses are supplied, skip root Adam + articulated funnel so seeds are not remacroed.
    root_skip_when_seeded: bool = True
    articulated_skip_when_seeded: bool = True
    idle_fused_importance_mode: str = "error_leverage"
    idle_fused_worst_frame_count: int = 4
    idle_fused_top_bone_count: int = 4
    idle_fused_macro_chain_count: int = 2
    idle_fused_root_window_deg: float = 45.0
    idle_fused_root_step_deg: float = 15.0
    idle_fused_macro_step_deg: float = 22.0
    # Macro whole-body root refit axes before articulated funnel. None uses
    # defer_camera_up policy (forward/right only) or pre-yaw macro pairing.
    idle_fused_macro_root_rotation_axes: tuple[str, ...] | None = None
    idle_fused_per_frame_root_enabled: bool = True
    idle_fused_per_frame_root_count: int = 5
    idle_fused_shared_transit_yaw_enabled: bool = False
    idle_fused_shared_transit_yaw_window_deg: float = 90.0
    idle_fused_shared_transit_yaw_step_deg: float = 15.0
    # Greedy error_leverage bone nudges per yaw candidate before clip-mean compare.
    idle_fused_shared_transit_yaw_bone_adapt_rounds: int = 0
    idle_fused_shared_transit_yaw_bone_adapt_top_bones: int = 4
    idle_fused_shared_transit_yaw_post_articulated_iterations: int = 0
    # When motion_weight > 0, clip-mean hybrid can reject a macro yaw that
    # improves silhouette/depth/chroma before bones adapt. Selection uses
    # geometryScore mean; final reporting still uses full hybrid.
    idle_fused_shared_transit_yaw_ignore_motion: bool = False
    # Macro yaw before articulated funnel so bones adapt under a turned heading.
    idle_fused_shared_transit_yaw_pre_articulated: bool = False
    idle_fused_shared_transit_yaw_post_articulated: bool = True
    live_status_path: str = ""
    idle_fused_reroot_transit_after_articulated: bool = False
    idle_fused_reroot_all_transit: bool = True
    base_pose_enabled: bool = True
    base_pose_iterations: int = 2
    mid_pose_enabled: bool = True
    mid_pose_iterations: int = 1
    mid_joint_step_deg: float = 5.0
    mid_joint_pass_limit_deg: float = 0.0
    root_refit_after_base_enabled: bool = True
    root_refit_translation_body_lengths: float = 0.05
    root_refit_translation_step_body_lengths: float = 0.025
    root_refit_rotation_deg: float = 5.0
    root_refit_rotation_step_deg: float = 2.5
    # After each articulated joint round, micro-step whole-body root with the
    # same keep gate as joints. Prefer this over a ±180° discrete root_search
    # when body turn must follow limb motion instead of leading it.
    articulated_root_interleave_enabled: bool = False
    articulated_root_interleave_rotation_deg: float = 8.0
    articulated_root_interleave_rotation_step_deg: float = 4.0
    articulated_root_interleave_include_translation: bool = False
    # per_accept — root after each accepted bone and each bone visit (legacy).
    # accept_only — root only after a bone accept, not every visit.
    # primary_group_end — root only after primary anatomy groups, after multi-bone.
    articulated_root_interleave_policy: str = "per_accept"
    articulated_root_interleave_primary_groups: tuple[str, ...] = ()
    articulated_multi_bone_enabled: bool = False
    articulated_multi_bone_block_size: int = 2
    # Broad-to-fine articulated funnel: exhaust large joint probes first, then
    # the normal adaptive articulated walk refines.
    articulated_funnel_enabled: bool = False
    articulated_funnel_broad_step_deg: float = 45.0
    articulated_funnel_broad_probe_rungs: int = 4
    articulated_funnel_broad_rounds: int = 1
    articulated_funnel_broad_min_improvement: float = 0.0
    articulated_funnel_force_gradient_order: bool = True
    articulated_funnel_broad_multi_bone_block_size: int = 3
    # During articulated_broad shared-clip keeps, up-weight worst transit frames
    # so macro probes prioritize mid-transit silhouette misses.
    articulated_funnel_worst_frame_keep_enabled: bool = False
    articulated_funnel_worst_frame_keep_count: int = 4
    articulated_funnel_worst_frame_keep_weight: float = 2.0
    anatomy_groups_catalog_path: str = ""
    anatomy_group_visit_order: tuple[str, ...] = ()
    # Early visits: bilateral pairs move identically; central groups probe only
    # profile-plane local axes (default x/y). Pairs default from catalog
    # symmetry.bilateralGroupPairs when config pairs are empty.
    early_symmetry_enabled: bool = False
    early_symmetry_visit_limit: int = 24
    early_symmetry_bilateral_group_pairs: tuple[tuple[str, str], ...] = ()
    early_symmetry_central_groups: tuple[str, ...] = ()
    early_symmetry_central_joint_axes: tuple[str, ...] = ("x", "y")
    branch_rescue_enabled: bool = True
    branch_rescue_block_size: int = 2
    branch_rescue_values_per_bone: int = 3
    skip_tiny_bones: bool = True
    min_leaf_length_frac: float = 0.45
    fine_only_leaf_length_frac: float = 0.75
    bone_order_mode: str = "dependency"
    search_bones: tuple[str, ...] = ()
    include_unlisted_search_bones: bool = True
    seed_previous_frame: bool = False
    adaptive_learning_rate_enabled: bool = True
    adaptive_learning_rate_reject_patience: int = 1
    adaptive_learning_rate_multiplier: float = 2.0
    adaptive_learning_rate_max_multiplier: float = 256.0
    joint_limit_deg: float = 150.0
    # Same joint_limit on every bone. Depth 1–2 used to be scaled to 0.35 so
    # bone-Adam could not become a second root. Discrete search does not
    # need that shrink; one_bone_depth already uses scale 1.0.
    proximal_bone_limit_depth: int = 2
    proximal_bone_limit_scale: float = 1.0
    # Named per-bone limit scales for units where one chain legitimately
    # moves far more than the rest. Each pair replaces the depth rule for
    # that node, so ("Bone_012", 0.3) with a 150° limit caps that bone at
    # 45°. See cascade_bone_limits.py.
    bone_limit_scale_overrides: tuple[tuple[str, float], ...] = ()
    root_translation_limit_body_lengths: float = 0.45
    root_rotation_limit_optimization_deg: float = 180.0
    # Optional signed interval for the in-plane root channel. This is useful
    # when a profile silhouette has a known facing convention: a symmetric
    # [-limit, +limit] search can treat an upside-down/reversed silhouette as
    # equivalent even though the mesh's anatomical front is not equivalent.
    root_rotation_min_deg: float | None = None
    root_rotation_max_deg: float | None = None
    velocity_weight: float = 0.015
    acceleration_weight: float = 0.010
    robust_scale_deg: float = 32.0
    root_velocity_weight: float = 0.010
    root_acceleration_weight: float = 0.005
    # A 2D silhouette alone cannot distinguish many equivalent 3D poses. These
    # priors keep the GPU experiment from spending its score budget on
    # saturated root turns or arbitrary joint flips that look acceptable only
    # in the proxy mask and become visibly implausible in Blender.
    bone_pose_prior_weight: float = 0.002
    root_translation_prior_weight: float = 0.010
    root_rotation_prior_weight: float = 0.015
    root_rotation_velocity_weight: float = 0.010
    root_rotation_acceleration_weight: float = 0.005
    loop_enabled: bool = False
    loop_weight: float = 0.0
    loop_velocity_weight: float = 0.0
    # When True, velocity/acceleration sample the loop seam in both time
    # directions (last↔first). Default False so CURRENT_CASCADE_KEEP fingerprints
    # stay unchanged; cycle clips get this after initial setup.
    temporal_loop_wrap_enabled: bool = False
    # ``default``: pose priors + velocity/acceleration (+ optional loop).
    # ``velocity_acceleration_only``: exclusive temporal regularizer; requires
    # motion_weight=0 (no occupancy-motion blend in geometry score).
    temporal_scoring_mode: str = "default"
    hierarchical_unlock_enabled: bool = False
    hierarchical_proximal_depth: int = 2
    optimize_root_translation: bool = True
    optimize_root_rotation: bool = True
    optimize_bones: bool = True
    # Keep global registration from being pulled into a local joint solution.
    freeze_root_after_root_stage: bool = False
    fine_root_enabled: bool = True
    return_masks: bool = True
    progress_every: int = 1
    # 0 keeps every Adam iteration. A positive value leaves the stage after
    # this many consecutive rejected steps; the pose is already the best.
    adam_stall_reject_streak: int = 3
    # Later joint rounds only re-probe bones that took a new angle, plus
    # their parent and child. Consensus-only copies do not schedule a rerun.
    joint_round_followup_neighbors: bool = True
    # Exact CUDA triangle evaluation. This is the Blender-free fitting path;
    # the soft sampled surface remains the explicit fast proxy when disabled.
    exact_raster_enabled: bool = True
    depth_target_dir: str | Path | None = None
    # Same blend as one_bone_depth: these are mix weights, not a subtracted
    # L1 scale. Collision is subtracted after the blend.
    depth_weight: float = 0.0
    silhouette_weight: float = 1.0
    depth_tolerance: float = 0.08
    depth_robust_delta: float = 0.12
    chroma_weight: float = 0.0
    # Frame-to-frame occupancy appear/disappear match. 0 keeps the old
    # per-frame fill blend. A positive weight cannot ship
    # (CURRENT_CASCADE_KEEP).
    motion_weight: float = 0.0
    # Idle-prefix frames are anchor plates: do not charge occupancy-motion on
    # the 0->1 transition against the frozen idle pose.
    motion_exempt_idle_prefix: bool = False
    chroma_tolerance: float = 0.10
    chroma_robust_delta: float = 0.12
    chroma_error_scale: float = 80.0
    chroma_scale: int = 4
    chroma_resolution: tuple[int, int] | None = None
    # geometry: silhouette / Huber depth / Lab chroma / occupancy motion,
    # then collision.
    # dinov3_dense: every candidate is scored with gated DINOv3 patch
    # grids only. That ablation cannot ship (CURRENT_CASCADE_KEEP).
    score_mode: str = "geometry"
    dense_semantic_model_id: str = DEFAULT_CASCADE_DINO_V3_MODEL_ID
    dense_semantic_feature_layers: tuple[str, ...] = ("last",)
    dense_semantic_local_radius: int = 1
    dense_semantic_position_weight: float = 1.0
    # Explicit experiment gate for gradients through RGB preprocessing and the
    # frozen DINOv3 encoder. Inference scoring remains the default path.
    dense_semantic_autograd_enabled: bool = False
    # Packed mixed-frame ViT microbatch. Frame grouping is not required.
    dense_semantic_batch_size: int = 32
    # Resolved integer proxy scale. The adapter passes 0 to derive
    # ceil(processor_long / proxy_long) before constructing this config.
    dense_semantic_raster_scale: int = 4
    dense_semantic_subject_crop: bool = False
    dense_semantic_subject_padding_frac: float = 0.18
    collision_enabled: bool = False
    collision_sample_count: int = 256
    collision_geodesic_min_hops: int = 8
    collision_margin_body_lengths: float = 0.04
    collision_weight: float = 0.0
    # Phase-B anatomy veto during articulated probe keep. Separate from DINO
    # keep authority and from collision_enabled (which mixes into geometry score).
    anatomy_veto_enabled: bool = False
    anatomy_veto_strain_enabled: bool = True
    anatomy_veto_collision_enabled: bool = True
    anatomy_veto_prop_enabled: bool = False
    anatomy_veto_strain_tolerance: float = 0.08
    anatomy_veto_strain_exclusive_weight: float = 0.99
    anatomy_veto_strain_min_rest_length_body_lengths: float = 0.02
    anatomy_veto_strain_slack: float = 0.02
    anatomy_veto_collision_slack: float = 0.12
    anatomy_veto_prop_slack_px: float = 12.0
    anatomy_veto_hard_strain_margin: float = 0.03
    anatomy_veto_hard_collision_margin: float = 0.05
    anatomy_veto_hard_prop_margin_px: float = 24.0
    anatomy_veto_dino_tie_band: float = 0.002
    anatomy_veto_soft_weight: float = 0.05
    anatomy_veto_bone_roles_path: str = ""
    anatomy_veto_prop_coords_path: str = ""
    # Metric-free post-pass after fine. Pulls one-frame spikes, damps jitter
    # with inertia, and applies gravity only on outlier frames. Does not read
    # silhouette, depth, chroma, or collision.
    physics_smooth_enabled: bool = True
    physics_smooth_outlier_window: int = 5
    physics_smooth_outlier_sigma: float = 3.5
    physics_smooth_outlier_min_deg: float = 10.0
    physics_smooth_outlier_min_translation: float = 0.08
    physics_smooth_stiffness: float = 180.0
    physics_smooth_dt: float = 1.0 / 12.0
    physics_smooth_substeps: int = 4
    physics_smooth_gravity: float = 9.81
    physics_smooth_gravity_weight: float = 0.6
    physics_smooth_gravity_min_bone_depth: int = 3
    physics_smooth_root_vertical_axis: int = 2
    physics_smooth_world_up: tuple[float, float, float] = (0.0, 1.0, 0.0)
    # Occupancy-motion keep-or-zero finish pass. Travel that raises the
    # occupancy pairs this frame actually changes stays at full strength.
    # Travel that does not, or that makes a neighboring pair worse, is
    # copied from the previous frame. Cannot mix with physics_smooth (that
    # damps every frame). Cannot ship (CURRENT_CASCADE_KEEP).
    sprite_aligned_motion_keep_enabled: bool = False
    sprite_aligned_motion_keep_min_improvement: float = 0.01
    # When hybrid mean score stays below ``score_escape_threshold`` after the
    # normal adaptive articulated walk, run one named escape pass. Adaptive
    # step stays on; this is not a second discrete ladder.
    score_escape_enabled: bool = False
    score_escape_threshold: float = 0.80
    # articulated_retry | branch_rescue | sa_nudge | coarse_push | chain_space |
    # no_consensus_retry | root_burst | combo (retry + rescue) |
    # full_stack | retry_coarse | until_threshold | until_plateau |
    # until_plateau_retry_coarse | deep_retry | deep_retry_4 | retry_then_plateau |
    # worst_stack
    score_escape_mode: str = ""
    score_escape_coarse_push_coarse: float = 0.85
    score_escape_coarse_push_fine: float = 0.92
    score_escape_root_window_deg: float = 12.0
    score_escape_root_step_deg: float = 4.0
    score_escape_sa_restarts: int = 2
    score_escape_sa_iterations: int = 80
    score_escape_sa_perturbation_deg: float = 25.0
    score_escape_sa_bone_fraction: float = 0.35
    score_escape_max_rounds: int = 3
    score_escape_min_improvement: float = 0.005
    score_escape_worst_frame_count: int = 3
    # Blend collisionError into worst-frame root bursts: deficiency =
    # (1 - hybrid) + weight * collisionError. 0 keeps score-only selection.
    score_escape_worst_frame_collision_weight: float = 0.0
    score_escape_keep_best: bool = True
    # When True, skip later escape passes (rescue / root bursts) after a pass
    # reverts with no score gain. Cuts wasted full_stack / worst_stack evals.
    score_escape_fail_fast: bool = True
    # Abort remaining worst-frame root-search after this many consecutive
    # held (no improvement) frames inside one escape root burst. 0 = disabled.
    score_escape_root_held_abort: int = 3
    # When True, escape threshold / keep_best / plateau use hybrid mean (packed score)
    # instead of velocity-only clip objective. Required when targeting hybrid >= 0.8
    # under temporal_scoring_mode=velocity_acceleration_only.
    score_escape_threshold_uses_hybrid_mean: bool = False
    # Skip coarse-push and articulated-broad escape passes when loading seeded poses.
    score_escape_skip_coarse_broad_when_seeded: bool = False
    # When > 0 and escape-entry mean is below this, skip coarse/broad (and the
    # articulated-retry substitute). Saves minutes on hopeless basins that cannot
    # reach score_escape_threshold via re-search (e.g. pikeman ~0.40 vs 0.70).
    score_escape_skip_coarse_broad_below_mean: float = 0.0
    score_escape_shared_transit_yaw_enabled: bool = False
    score_escape_skip_articulated_retry_when_seeded: bool = True
    # When > 0, escape articulated passes use this instead of articulated_iterations.
    score_escape_articulated_iterations: int = 0
    score_escape_collision_burst_enabled: bool = False
    score_escape_collision_burst_threshold: float = 0.15
    # Per-frame whole-body root translation burst (e.g. vertical bob) during escape.
    score_escape_translation_burst_enabled: bool = False
    score_escape_translation_burst_mode: str = "all_transit"
    score_escape_translation_window_body_lengths: float = 0.12
    score_escape_translation_hypotheses: int = 48
    score_escape_translation_axes: tuple[str, ...] = ("vertical",)
    # transit_wave: sinusoidal whole-body bob across transit frames (amplitude+phase).
    # transit_uniform: same translation offset on every transit frame.
    score_escape_translation_wave_phase_span_rad: float = math.pi

    def physics_smooth_config(self):
        from cascade_physics_smooth import physics_smooth_config_from_mapping

        return physics_smooth_config_from_mapping(self.__dict__)

    def uses_dinov3_dense_score(self) -> bool:
        return str(self.score_mode) == "dinov3_dense"

    def uses_dinov3_geometry_consensus(self) -> bool:
        return str(self.score_mode) == "dinov3_geometry_consensus"

    def uses_dense_semantic_encoder(self) -> bool:
        return self.uses_dinov3_dense_score() or self.uses_dinov3_geometry_consensus()

    def uses_rgb_raster(self) -> bool:
        return float(self.chroma_weight) > 0.0 or self.uses_dense_semantic_encoder()

    def _validate_dinov3_dense_score(self) -> None:
        from dense_semantic_features import _canonical_family

        if (
            float(self.depth_weight) != 0.0
            or float(self.silhouette_weight) != 0.0
            or float(self.chroma_weight) != 0.0
            or float(self.motion_weight) != 0.0
        ):
            raise ValueError(
                "dinov3_dense score_mode cannot mix silhouette, depth, chroma, "
                "or occupancy motion; set depth_weight, silhouette_weight, "
                "chroma_weight, and motion_weight to 0"
            )
        if bool(self.collision_enabled) or float(self.collision_weight) != 0.0:
            raise ValueError(
                "dinov3_dense score_mode cannot mix collision; "
                "set collision_enabled=False and collision_weight=0"
            )
        if float(self.joint_unique_gain_weight) != 0.0 or float(self.fine_unique_gain_weight) != 0.0:
            raise ValueError(
                "dinov3_dense score_mode cannot mix unique occupancy keep; "
                "set joint_unique_gain_weight and fine_unique_gain_weight to 0"
            )
        if int(self.root_iterations) != 0:
            raise ValueError(
                "dinov3_dense score_mode does not support Adam root optimization; "
                "set root_iterations=0"
            )
        if bool(self.gradient_ladder_enabled):
            raise ValueError(
                "dinov3_dense score_mode cannot run the gradient ladder; "
                "set gradient_ladder_enabled=False"
            )
        if bool(self.dense_semantic_autograd_enabled):
            if str(self.joint_solver_mode) != "branch_vector":
                raise ValueError(
                    "DINOv3 autograd requires joint_solver_mode='branch_vector'"
                )
            if not bool(self.chain_space_enabled):
                raise ValueError(
                    "dense_semantic_autograd_enabled requires chain_space_enabled=True"
                )
            if str(self.chain_space_mode) != "branch_trust":
                raise ValueError(
                    "DINOv3 autograd requires chain_space_mode='branch_trust' so "
                    "whole-clip trust candidates are accepted atomically"
                )
            if bool(self.dense_semantic_subject_crop):
                raise ValueError(
                    "DINOv3 autograd requires dense_semantic_subject_crop=False; "
                    "dynamic crop bounds are not a differentiable contract"
                )
            incompatible = {
                "root_search_enabled": bool(self.root_search_enabled),
                "root_rotation_defer_camera_up": bool(
                    self.root_rotation_defer_camera_up
                ),
                "root_refit_after_base_enabled": bool(
                    self.root_refit_after_base_enabled
                ),
                "joint_adaptive_step_enabled": bool(
                    self.joint_adaptive_step_enabled
                ),
                "joint_keep_still_sprite_lock": bool(
                    self.joint_keep_still_sprite_lock
                ),
                "joint_keep_sprite_change_gate": bool(
                    self.joint_keep_sprite_change_gate
                ),
                "joint_temporal_consensus_enabled": bool(
                    self.joint_temporal_consensus_enabled
                ),
                "base_pose_enabled": bool(self.base_pose_enabled),
                "mid_pose_enabled": bool(self.mid_pose_enabled),
                "branch_rescue_enabled": bool(self.branch_rescue_enabled),
                "physics_smooth_enabled": bool(self.physics_smooth_enabled),
                "sprite_aligned_motion_keep_enabled": bool(
                    self.sprite_aligned_motion_keep_enabled
                ),
                "fine_root_enabled": bool(self.fine_root_enabled),
                "articulated_iterations": int(self.articulated_iterations) != 0,
                "fine_iterations": int(self.fine_iterations) != 0,
            }
            active = [name for name, enabled in incompatible.items() if enabled]
            if active:
                raise ValueError(
                    "DINOv3 branch_vector cannot mix other proposal, root, or "
                    "post-processing stages; disable: " + ", ".join(active)
                )
            if bool(self.skip_tiny_bones):
                raise ValueError(
                    "DINOv3 branch_vector requires skip_tiny_bones=False for "
                    "complete deforming-joint coverage"
                )
            if float(self.fine_only_leaf_length_frac) != 0.0:
                raise ValueError(
                    "DINOv3 branch_vector requires fine_only_leaf_length_frac=0 "
                    "because the fine stage is disabled"
                )
            if not bool(self.include_unlisted_search_bones):
                raise ValueError(
                    "DINOv3 branch_vector requires "
                    "include_unlisted_search_bones=True"
                )
        elif bool(self.chain_space_enabled):
            raise ValueError(
                "dinov3_dense chain space requires the explicit "
                "dense_semantic_autograd_enabled=True experiment gate"
            )
        if bool(self.ik_enabled):
            raise ValueError(
                "dinov3_dense score_mode cannot mix IK basin selection; "
                "set ik_enabled=False"
            )
        if str(self.bone_order_mode) not in DINOV3_DENSE_BONE_ORDER_MODES:
            raise ValueError(
                "dinov3_dense score_mode cannot use occupancy or gradient bone order; "
                "set bone_order_mode to asset or dependency"
            )
        if not str(self.dense_semantic_model_id).strip():
            raise ValueError("dense_semantic_model_id cannot be empty for dinov3_dense")
        family = _canonical_family(str(self.dense_semantic_model_id), "auto")
        if family != "dino":
            raise ValueError(
                "dinov3_dense score_mode requires a DINO-family model_id; "
                f"got family={family!r} model_id={self.dense_semantic_model_id!r}"
            )
        if "dinov3" not in str(self.dense_semantic_model_id).lower():
            raise ValueError(
                "dinov3_dense score_mode requires a DINOv3 checkpoint id; "
                f"got {self.dense_semantic_model_id!r}"
            )
        if not self.dense_semantic_feature_layers:
            raise ValueError("dense_semantic_feature_layers cannot be empty for dinov3_dense")
        if int(self.dense_semantic_local_radius) < 0:
            raise ValueError("dense_semantic_local_radius must be non-negative")
        if (
            not math.isfinite(float(self.dense_semantic_position_weight))
            or float(self.dense_semantic_position_weight) < 0.0
        ):
            raise ValueError("dense_semantic_position_weight must be finite and non-negative")
        if int(self.dense_semantic_batch_size) < 1:
            raise ValueError("dense_semantic_batch_size must be at least 1")
        if int(self.dense_semantic_raster_scale) < 2:
            raise ValueError("dense_semantic_raster_scale must be at least 2")
        if bool(self.dense_semantic_subject_crop):
            padding = float(self.dense_semantic_subject_padding_frac)
            if not math.isfinite(padding) or padding < 0.0:
                raise ValueError(
                    "dense_semantic_subject_padding_frac must be finite and non-negative "
                    "when subject crop is on"
                )

    def _validate_dinov3_geometry_consensus(self) -> None:
        """DINOv3 + silhouette keep: both terms must be present and finite."""
        from dense_semantic_features import _canonical_family

        if float(self.silhouette_weight) <= 0.0:
            raise ValueError(
                "dinov3_geometry_consensus requires silhouette_weight > 0; "
                "silhouette IoU is the geometry veto term"
            )
        if bool(self.dense_semantic_autograd_enabled):
            raise ValueError(
                "dinov3_geometry_consensus does not support dense_semantic_autograd_enabled; "
                "set dense_semantic_autograd_enabled=False"
            )
        if not str(self.dense_semantic_model_id).strip():
            raise ValueError(
                "dense_semantic_model_id cannot be empty for dinov3_geometry_consensus"
            )
        family = _canonical_family(str(self.dense_semantic_model_id), "auto")
        if family != "dino":
            raise ValueError(
                "dinov3_geometry_consensus requires a DINO-family model_id; "
                f"got family={family!r} model_id={self.dense_semantic_model_id!r}"
            )
        if "dinov3" not in str(self.dense_semantic_model_id).lower():
            raise ValueError(
                "dinov3_geometry_consensus requires a DINOv3 checkpoint id; "
                f"got {self.dense_semantic_model_id!r}"
            )
        if not self.dense_semantic_feature_layers:
            raise ValueError(
                "dense_semantic_feature_layers cannot be empty for dinov3_geometry_consensus"
            )
        if int(self.dense_semantic_local_radius) < 0:
            raise ValueError("dense_semantic_local_radius must be non-negative")
        if (
            not math.isfinite(float(self.dense_semantic_position_weight))
            or float(self.dense_semantic_position_weight) < 0.0
        ):
            raise ValueError("dense_semantic_position_weight must be finite and non-negative")
        if int(self.dense_semantic_batch_size) < 1:
            raise ValueError("dense_semantic_batch_size must be at least 1")
        if int(self.dense_semantic_raster_scale) < 2:
            raise ValueError("dense_semantic_raster_scale must be at least 2")
        if bool(self.dense_semantic_subject_crop):
            padding = float(self.dense_semantic_subject_padding_frac)
            if not math.isfinite(padding) or padding < 0.0:
                raise ValueError(
                    "dense_semantic_subject_padding_frac must be finite and non-negative "
                    "when subject crop is on"
                )

    def _joint_stage_configured(self) -> bool:
        if int(self.articulated_iterations) > 0:
            return True
        if bool(self.base_pose_enabled) and int(self.base_pose_iterations) > 0:
            return True
        if bool(self.mid_pose_enabled) and int(self.mid_pose_iterations) > 0:
            return True
        if int(self.fine_iterations) > 0:
            return True
        if bool(self.gradient_ladder_enabled) and int(self.gradient_ladder_iterations) > 0:
            return True
        if bool(self.chain_space_enabled) and int(self.chain_space_iterations) > 0:
            return True
        if bool(self.sa_enabled):
            return True
        if bool(self.ik_enabled):
            return True
        if bool(self.branch_rescue_enabled):
            return True
        return False

    def validate(self) -> None:
        width, height = (int(value) for value in self.resolution)
        if width < 16 or height < 16:
            raise ValueError("resolution must be at least 16x16")
        if not 0 <= int(self.alpha_threshold) <= 255:
            raise ValueError("alpha_threshold must be between 0 and 255")
        if int(self.max_triangles_per_primitive) < 1:
            raise ValueError("max_triangles_per_primitive must be positive")
        if int(self.samples_per_triangle) < 3:
            raise ValueError("samples_per_triangle must be at least 3")
        if float(self.raster_sigma_px) <= 0.0:
            raise ValueError("raster_sigma_px must be positive")
        if int(self.raster_point_chunk) < 1:
            raise ValueError("raster_point_chunk must be positive")
        if int(self.root_hypotheses) < 1:
            raise ValueError("root_hypotheses must be positive")
        for name in (
            "root_rotation_limit_deg",
            "root_translation_radius_body_lengths",
            "root_translation_limit_body_lengths",
            "joint_limit_deg",
            "root_rotation_limit_optimization_deg",
            "robust_scale_deg",
        ):
            if not math.isfinite(float(getattr(self, name))) or float(getattr(self, name)) <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        for name in (
            "root_rotation_first_frame_limit_deg",
            "root_rotation_per_frame_limit_deg",
            "root_rotation_camera_up_limit_deg",
        ):
            if not math.isfinite(float(getattr(self, name))) or float(getattr(self, name)) < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if bool(self.root_rotation_defer_camera_up):
            if not bool(self.optimize_root_rotation):
                raise ValueError(
                    "root_rotation_defer_camera_up requires optimize_root_rotation"
                )
            if "camera_up" not in tuple(self.root_rotation_axes):
                raise ValueError(
                    "root_rotation_defer_camera_up requires camera_up in root_rotation_axes"
                )
            if float(self.root_rotation_camera_up_limit_deg) <= 0.0:
                raise ValueError(
                    "root_rotation_defer_camera_up requires a positive camera_up limit"
                )
            if max(
                abs(float(self.root_rotation_first_frame_limit_deg)),
                abs(float(self.root_rotation_per_frame_limit_deg)),
            ) <= 0.0:
                raise ValueError(
                    "root_rotation_defer_camera_up requires a positive first-frame "
                    "or per-frame rotation window"
                )
            if not bool(self.optimize_bones) or not self._joint_stage_configured():
                raise ValueError(
                    "root_rotation_defer_camera_up requires a joint stage before "
                    "the after-joints yaw pass"
                )
        for name in (
            "score_centroid_weight",
            "score_occupancy_weight",
            "sdf_weight",
            "velocity_weight",
            "acceleration_weight",
            "root_velocity_weight",
            "root_acceleration_weight",
            "bone_pose_prior_weight",
            "root_translation_prior_weight",
            "root_rotation_prior_weight",
            "root_rotation_velocity_weight",
            "root_rotation_acceleration_weight",
            "loop_weight",
            "loop_velocity_weight",
            "depth_weight",
            "silhouette_weight",
            "chroma_weight",
            "motion_weight",
            "joint_absolute_gain_weight",
            "joint_unique_gain_weight",
            "fine_unique_gain_weight",
            "joint_keep_min_improvement",
            "joint_keep_still_sprite_rgb_mad",
            "joint_keep_sprite_change_weight",
            "joint_keep_sprite_change_slack",
            "joint_collision_positive_abs_slack",
            "joint_temporal_consensus_tie_bonus",
            "sprite_aligned_motion_keep_min_improvement",
            "root_refit_translation_body_lengths",
            "root_refit_translation_step_body_lengths",
            "root_refit_rotation_deg",
            "root_refit_rotation_step_deg",
            "articulated_root_interleave_rotation_deg",
            "articulated_root_interleave_rotation_step_deg",
            "min_leaf_length_frac",
            "fine_only_leaf_length_frac",
        ):
            if not math.isfinite(float(getattr(self, name))) or float(getattr(self, name)) < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if bool(self.articulated_root_interleave_enabled):
            if float(self.articulated_root_interleave_rotation_deg) <= 0.0:
                raise ValueError(
                    "articulated_root_interleave_rotation_deg must be > 0 when "
                    "articulated_root_interleave_enabled"
                )
            if float(self.articulated_root_interleave_rotation_step_deg) <= 0.0:
                raise ValueError(
                    "articulated_root_interleave_rotation_step_deg must be > 0 when "
                    "articulated_root_interleave_enabled"
                )
            if float(self.articulated_root_interleave_rotation_step_deg) > float(
                self.articulated_root_interleave_rotation_deg
            ):
                raise ValueError(
                    "articulated_root_interleave_rotation_step_deg cannot exceed "
                    "articulated_root_interleave_rotation_deg"
                )
            if not bool(self.optimize_root_rotation):
                raise ValueError(
                    "articulated_root_interleave_enabled requires optimize_root_rotation"
                )
        policy = str(self.articulated_root_interleave_policy).strip()
        allowed_root_policy = frozenset({"per_accept", "accept_only", "primary_group_end"})
        if policy not in allowed_root_policy:
            raise ValueError(
                "articulated_root_interleave_policy must be one of "
                f"{sorted(allowed_root_policy)}; got {policy!r}"
            )
        if int(self.articulated_multi_bone_block_size) not in {2, 3}:
            raise ValueError("articulated_multi_bone_block_size must be 2 or 3")
        if bool(self.articulated_funnel_enabled):
            if float(self.articulated_funnel_broad_step_deg) <= 0.0:
                raise ValueError("articulated_funnel_broad_step_deg must be positive")
            if int(self.articulated_funnel_broad_probe_rungs) < 1:
                raise ValueError("articulated_funnel_broad_probe_rungs must be at least 1")
            if int(self.articulated_funnel_broad_rounds) < 1:
                raise ValueError("articulated_funnel_broad_rounds must be at least 1")
            if float(self.articulated_funnel_broad_min_improvement) < 0.0:
                raise ValueError(
                    "articulated_funnel_broad_min_improvement must be non-negative"
                )
            if int(self.articulated_funnel_broad_multi_bone_block_size) not in {2, 3}:
                raise ValueError(
                    "articulated_funnel_broad_multi_bone_block_size must be 2 or 3"
                )
            if bool(self.articulated_funnel_worst_frame_keep_enabled):
                if int(self.articulated_funnel_worst_frame_keep_count) < 1:
                    raise ValueError(
                        "articulated_funnel_worst_frame_keep_count must be at least 1"
                    )
                if float(self.articulated_funnel_worst_frame_keep_weight) <= 0.0:
                    raise ValueError(
                        "articulated_funnel_worst_frame_keep_weight must be positive"
                    )
        if bool(self.early_symmetry_enabled):
            if int(self.early_symmetry_visit_limit) < 1:
                raise ValueError("early_symmetry_visit_limit must be at least 1")
            axes = tuple(str(axis) for axis in self.early_symmetry_central_joint_axes)
            if axes and not set(axes) <= {"x", "y", "z"}:
                raise ValueError("early_symmetry_central_joint_axes must be x, y, and/or z")
            if not str(self.anatomy_groups_catalog_path or "").strip():
                raise ValueError(
                    "early_symmetry_enabled requires anatomy_groups_catalog_path"
                )
            if not tuple(self.anatomy_group_visit_order):
                raise ValueError(
                    "early_symmetry_enabled requires anatomy_group_visit_order"
                )
        if bool(self.motion_exempt_idle_prefix):
            if float(self.motion_weight) <= 0.0:
                raise ValueError(
                    "motion_exempt_idle_prefix requires motion_weight > 0"
                )
            if int(self.idle_prefix_frames) <= 0:
                raise ValueError(
                    "motion_exempt_idle_prefix requires idle_prefix_frames > 0"
                )
        if bool(self.articulated_multi_bone_enabled) and not bool(self.search_bones):
            raise ValueError(
                "articulated_multi_bone_enabled requires explicit search_bones "
                "(anatomy visit order)"
            )
        if bool(self.joint_keep_still_sprite_lock):
            threshold = float(self.joint_keep_still_sprite_rgb_mad)
            if not math.isfinite(threshold) or threshold <= 0.0 or threshold >= 1.0:
                raise ValueError(
                    "joint_keep_still_sprite_rgb_mad must be in (0, 1) when "
                    "joint_keep_still_sprite_lock is on"
                )
        if bool(self.joint_keep_sprite_change_gate) and bool(self.joint_keep_still_sprite_lock):
            raise ValueError(
                "joint_keep_sprite_change_gate cannot mix with "
                "joint_keep_still_sprite_lock; the whole-pose copy freezes idle"
            )
        if bool(self.joint_keep_sprite_change_gate):
            if not self.uses_rgb_raster():
                raise ValueError(
                    "joint_keep_sprite_change_gate requires RGB raster "
                    "(dinov3_dense or chroma_weight)"
                )
            weight = float(self.joint_keep_sprite_change_weight)
            slack = float(self.joint_keep_sprite_change_slack)
            if not math.isfinite(weight) or weight <= 0.0:
                raise ValueError(
                    "joint_keep_sprite_change_weight must be finite and positive "
                    "when joint_keep_sprite_change_gate is on"
                )
            if not math.isfinite(slack) or slack < 0.0:
                raise ValueError(
                    "joint_keep_sprite_change_slack must be finite and non-negative"
                )
        if str(self.joint_solver_mode) not in JOINT_SOLVER_MODES:
            raise ValueError(
                f"joint_solver_mode must be one of {JOINT_SOLVER_MODES}; "
                f"got {self.joint_solver_mode!r}"
            )
        if str(self.joint_solver_mode) == "branch_vector" and not bool(
            self.chain_space_enabled
        ):
            raise ValueError(
                "joint_solver_mode='branch_vector' requires chain_space_enabled=True"
            )
        if str(self.joint_solver_mode) == "branch_vector" and str(
            self.chain_space_mode
        ) != "branch_trust":
            raise ValueError(
                "joint_solver_mode='branch_vector' requires "
                "chain_space_mode='branch_trust'"
            )
        if str(self.score_mode) not in CASCADE_SCORE_MODES:
            raise ValueError(
                "score_mode must be 'geometry', 'dinov3_dense', or "
                f"'dinov3_geometry_consensus'; got {self.score_mode!r}"
            )
        if bool(self.sprite_aligned_motion_keep_enabled):
            if bool(self.physics_smooth_enabled):
                raise ValueError(
                    "sprite_aligned_motion_keep_enabled cannot mix with "
                    "physics_smooth_enabled; physics damps every frame"
                )
            if str(self.score_mode) != "geometry":
                raise ValueError(
                    "sprite_aligned_motion_keep_enabled requires score_mode='geometry'"
                )
            if float(self.motion_weight) <= 0.0:
                raise ValueError(
                    "sprite_aligned_motion_keep_enabled requires motion_weight > 0; "
                    "occupancy appear/disappear is the keep-or-zero authority"
                )
        if bool(self.score_escape_enabled):
            mode = str(self.score_escape_mode).strip()
            allowed = frozenset(
                {
                    "articulated_retry",
                    "branch_rescue",
                    "sa_nudge",
                    "coarse_push",
                    "chain_space",
                    "no_consensus_retry",
                    "root_burst",
                    "combo",
                    "full_stack",
                    "retry_coarse",
                    "until_threshold",
                    "until_plateau",
                    "until_plateau_retry_coarse",
                    "deep_retry",
                    "deep_retry_4",
                    "retry_then_plateau",
                    "worst_stack",
                }
            )
            if mode not in allowed:
                raise ValueError(
                    f"score_escape_mode must be one of {sorted(allowed)}; got {mode!r}"
                )
            if not math.isfinite(float(self.score_escape_threshold)):
                raise ValueError("score_escape_threshold must be finite")
            if int(self.score_escape_max_rounds) < 1:
                raise ValueError("score_escape_max_rounds must be at least 1")
            if float(self.score_escape_min_improvement) < 0.0:
                raise ValueError("score_escape_min_improvement must be non-negative")
            if int(self.score_escape_worst_frame_count) < 1:
                raise ValueError("score_escape_worst_frame_count must be at least 1")
            if not math.isfinite(float(self.score_escape_worst_frame_collision_weight)):
                raise ValueError(
                    "score_escape_worst_frame_collision_weight must be finite"
                )
            if float(self.score_escape_worst_frame_collision_weight) < 0.0:
                raise ValueError(
                    "score_escape_worst_frame_collision_weight must be non-negative"
                )
            if int(self.score_escape_articulated_iterations) < 0:
                raise ValueError("score_escape_articulated_iterations must be non-negative")
            if bool(self.score_escape_translation_burst_enabled):
                burst_mode = str(self.score_escape_translation_burst_mode).strip()
                if burst_mode not in {
                    "all_transit",
                    "worst",
                    "transit_wave",
                    "transit_uniform",
                    "transit_sprite_centroid",
                }:
                    raise ValueError(
                        "score_escape_translation_burst_mode must be all_transit, worst, "
                        "transit_wave, transit_uniform, or transit_sprite_centroid"
                    )
                phase_span = float(self.score_escape_translation_wave_phase_span_rad)
                if not math.isfinite(phase_span) or phase_span <= 0.0:
                    raise ValueError(
                        "score_escape_translation_wave_phase_span_rad must be positive"
                    )
                window = float(self.score_escape_translation_window_body_lengths)
                if not math.isfinite(window) or window <= 0.0:
                    raise ValueError(
                        "score_escape_translation_window_body_lengths must be positive"
                    )
                if int(self.score_escape_translation_hypotheses) < 1:
                    raise ValueError("score_escape_translation_hypotheses must be at least 1")
                allowed_translation_axes = {"forward", "lateral", "vertical"}
                if not set(self.score_escape_translation_axes) <= allowed_translation_axes:
                    raise ValueError(
                        "score_escape_translation_axes must be forward, lateral, or vertical"
                    )
                if not set(self.score_escape_translation_axes):
                    raise ValueError("score_escape_translation_axes must be non-empty")
        temporal_mode = str(self.temporal_scoring_mode).strip()
        if temporal_mode not in ("default", "velocity_acceleration_only"):
            raise ValueError(
                "temporal_scoring_mode must be 'default' or "
                f"'velocity_acceleration_only'; got {temporal_mode!r}"
            )
        if temporal_mode == "velocity_acceleration_only" and float(self.motion_weight) > 0.0:
            raise ValueError(
                "temporal_scoring_mode='velocity_acceleration_only' requires "
                "motion_weight=0 (occupancy motion is not the temporal term)"
            )
        if self.uses_dinov3_dense_score():
            self._validate_dinov3_dense_score()
        elif self.uses_dinov3_geometry_consensus():
            self._validate_dinov3_geometry_consensus()
        elif (
            float(self.depth_weight)
            + float(self.silhouette_weight)
            + float(self.chroma_weight)
            + float(self.motion_weight)
            <= 0.0
        ):
            raise ValueError(
                "depth_weight, silhouette_weight, chroma_weight, and "
                "motion_weight cannot all be zero"
            )
        if not bool(self.exact_raster_enabled):
            raise ValueError(
                "cascade geometry scoring requires exact_raster_enabled; "
                "filled-triangle nvdiffrast is the cascade renderer"
            )
        for name in ("score_centroid_weight", "score_occupancy_weight", "sdf_weight"):
            if float(getattr(self, name)) != 0.0:
                raise ValueError(
                    f"{name} must be 0; cascade score is silhouette, depth, chroma, "
                    "occupancy motion, and collision, or dinov3_dense"
                )
        if float(self.depth_weight) > 0.0:
            if self.depth_target_dir is None:
                raise ValueError("depth_weight is set but depth_target_dir is missing")
            if not math.isfinite(float(self.depth_tolerance)) or not 0.0 <= float(self.depth_tolerance) < 1.0:
                raise ValueError("depth_tolerance must be in [0, 1) when depth_weight is set")
            if not math.isfinite(float(self.depth_robust_delta)) or float(self.depth_robust_delta) <= 0.0:
                raise ValueError("depth_robust_delta must be positive when depth_weight is set")
        if float(self.chroma_weight) > 0.0:
            if not math.isfinite(float(self.chroma_tolerance)) or not 0.0 <= float(self.chroma_tolerance) < 1.0:
                raise ValueError("chroma_tolerance must be in [0, 1) when chroma_weight is set")
            if not math.isfinite(float(self.chroma_robust_delta)) or float(self.chroma_robust_delta) <= 0.0:
                raise ValueError("chroma_robust_delta must be positive when chroma_weight is set")
            if not math.isfinite(float(self.chroma_error_scale)) or float(self.chroma_error_scale) <= 0.0:
                raise ValueError("chroma_error_scale must be positive when chroma_weight is set")
            if int(self.chroma_scale) < 2 and self.chroma_resolution is None:
                raise ValueError("chroma_scale must be at least 2 when chroma_weight is set")
        if bool(self.collision_enabled):
            if int(self.collision_sample_count) < 2:
                raise ValueError("collision_sample_count must be at least 2")
            if int(self.collision_geodesic_min_hops) < 1:
                raise ValueError("collision_geodesic_min_hops must be at least 1")
            if (
                not math.isfinite(float(self.collision_margin_body_lengths))
                or float(self.collision_margin_body_lengths) <= 0.0
            ):
                raise ValueError("collision_margin_body_lengths must be positive when collision is enabled")
            if not math.isfinite(float(self.collision_weight)) or float(self.collision_weight) <= 0.0:
                raise ValueError(
                    "collision_weight must be positive when collision_enabled; "
                    "set collision_enabled=False to disable the penalty"
                )
        elif float(self.collision_weight) != 0.0:
            raise ValueError("collision_weight must be 0 when collision_enabled is False")
        from anatomy_probe_veto import validate_anatomy_veto_config

        validate_anatomy_veto_config(self)
        for name in ("root_iterations", "articulated_iterations", "fine_iterations"):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be non-negative")
        if int(self.adam_stall_reject_streak) < 0:
            raise ValueError("adam_stall_reject_streak must be non-negative")
        if int(self.proximal_bone_limit_depth) < 0:
            raise ValueError("proximal_bone_limit_depth must be non-negative")
        if not math.isfinite(float(self.proximal_bone_limit_scale)) or not 0.0 < float(self.proximal_bone_limit_scale) <= 1.0:
            raise ValueError("proximal_bone_limit_scale must be in (0, 1]")
        from cascade_bone_limits import validate_bone_limit_scale_overrides

        validate_bone_limit_scale_overrides(self.bone_limit_scale_overrides)
        if float(self.sdf_max_distance_px) <= 0.0:
            raise ValueError("sdf_max_distance_px must be positive")
        if int(self.hierarchical_proximal_depth) < 0:
            raise ValueError("hierarchical_proximal_depth must be non-negative")
        if float(self.learning_rate) <= 0.0 or float(self.fine_learning_rate) <= 0.0:
            raise ValueError("learning rates must be positive")
        if not math.isfinite(float(self.joint_step_deg)) or float(self.joint_step_deg) <= 0.0:
            raise ValueError("joint_step_deg must be finite and positive")
        if not math.isfinite(float(self.fine_joint_step_deg)) or float(self.fine_joint_step_deg) <= 0.0:
            raise ValueError("fine_joint_step_deg must be finite and positive")
        if float(self.fine_joint_step_deg) - float(self.joint_step_deg) > 1e-12:
            raise ValueError("fine_joint_step_deg must be <= joint_step_deg")
        if not math.isfinite(float(self.joint_step_score_coarse)):
            raise ValueError("joint_step_score_coarse must be finite")
        if not math.isfinite(float(self.joint_step_score_fine)):
            raise ValueError("joint_step_score_fine must be finite")
        if float(self.joint_step_score_fine) <= float(self.joint_step_score_coarse):
            raise ValueError("joint_step_score_fine must be greater than joint_step_score_coarse")
        if str(self.joint_step_score_norm) not in JOINT_STEP_SCORE_NORMS:
            raise ValueError(
                "joint_step_score_norm must be one of "
                + ", ".join(JOINT_STEP_SCORE_NORMS)
            )
        if not math.isfinite(float(self.joint_pass_limit_deg)) or float(self.joint_pass_limit_deg) < 0.0:
            raise ValueError("joint_pass_limit_deg must be finite and non-negative")
        if float(self.joint_pass_limit_deg) > 0.0 and float(self.joint_pass_limit_deg) < float(self.joint_step_deg):
            raise ValueError("joint_pass_limit_deg must be 0 (full joint_limit_deg) or at least joint_step_deg")
        if not math.isfinite(float(self.fine_joint_pass_limit_deg)) or float(self.fine_joint_pass_limit_deg) < 0.0:
            raise ValueError("fine_joint_pass_limit_deg must be finite and non-negative")
        if float(self.fine_joint_pass_limit_deg) > 0.0 and float(self.fine_joint_pass_limit_deg) < float(self.fine_joint_step_deg):
            raise ValueError("fine_joint_pass_limit_deg must be 0 (full joint_limit_deg) or at least fine_joint_step_deg")
        if (
            float(self.joint_absolute_gain_weight) + float(self.joint_unique_gain_weight) <= 0.0
        ):
            raise ValueError("joint_absolute_gain_weight and joint_unique_gain_weight cannot both be zero")
        if (
            float(self.joint_absolute_gain_weight) + float(self.fine_unique_gain_weight) <= 0.0
        ):
            raise ValueError("joint_absolute_gain_weight and fine_unique_gain_weight cannot both be zero")
        if int(self.joint_diagonal_axes) < 0 or int(self.joint_diagonal_axes) > 10:
            raise ValueError("joint_diagonal_axes must be in 0..10")
        if int(self.base_pose_iterations) < 0:
            raise ValueError("base_pose_iterations must be non-negative")
        if int(self.mid_pose_iterations) < 0:
            raise ValueError("mid_pose_iterations must be non-negative")
        if not math.isfinite(float(self.mid_joint_step_deg)) or float(self.mid_joint_step_deg) <= 0.0:
            raise ValueError("mid_joint_step_deg must be finite and positive")
        if not math.isfinite(float(self.mid_joint_pass_limit_deg)) or float(self.mid_joint_pass_limit_deg) < 0.0:
            raise ValueError("mid_joint_pass_limit_deg must be finite and non-negative")
        if float(self.mid_joint_pass_limit_deg) > 0.0 and float(self.mid_joint_pass_limit_deg) < float(self.mid_joint_step_deg):
            raise ValueError("mid_joint_pass_limit_deg must be 0 (full joint_limit_deg) or at least mid_joint_step_deg")
        if float(self.joint_temporal_consensus_tie_bonus) <= 0.0:
            raise ValueError("joint_temporal_consensus_tie_bonus must be positive")
        if int(self.idle_prefix_frames) < 0:
            raise ValueError("idle_prefix_frames must be non-negative")
        if int(self.idle_suffix_frames) < 0:
            raise ValueError("idle_suffix_frames must be non-negative")
        if bool(self.idle_suffix_mirror_prefix_enabled) and int(self.idle_suffix_frames) <= 0:
            raise ValueError(
                "idle_suffix_mirror_prefix_enabled requires idle_suffix_frames > 0"
            )
        if bool(self.gradient_ladder_enabled):
            if int(self.gradient_ladder_iterations) < 1:
                raise ValueError(
                    "gradient_ladder_iterations must be at least 1 when the ladder is enabled"
                )
            if not self.gradient_ladder_step_degs:
                raise ValueError(
                    "gradient_ladder_step_degs must be non-empty when the ladder is enabled"
                )
            for step_deg in self.gradient_ladder_step_degs:
                if not math.isfinite(float(step_deg)) or float(step_deg) <= 0.0:
                    raise ValueError("gradient_ladder_step_degs must be finite and positive")
            if (
                not math.isfinite(float(self.gradient_ladder_min_gradient_norm))
                or float(self.gradient_ladder_min_gradient_norm) <= 0.0
            ):
                raise ValueError("gradient_ladder_min_gradient_norm must be finite and positive")
        if bool(self.chain_space_enabled):
            from cascade_chain_space import validate_chain_space_config

            if bool(self.sa_enabled):
                raise ValueError(
                    "chain_space_enabled cannot mix sa_enabled; one basin method"
                )
            if bool(self.gradient_ladder_enabled):
                raise ValueError(
                    "chain_space_enabled cannot mix gradient_ladder_enabled; "
                    "one coupled-gradient stage"
                )
            if bool(self.ik_enabled):
                raise ValueError(
                    "chain_space_enabled cannot mix ik_enabled; "
                    "chain space inverts a surface, not a tip"
                )
            validate_chain_space_config(
                enabled=True,
                mode=str(self.chain_space_mode),
                iterations=int(self.chain_space_iterations),
                step_degs=tuple(self.chain_space_step_degs),
                min_gradient_norm=float(self.chain_space_min_gradient_norm),
                trust_radius_deg=float(self.chain_space_trust_radius_deg),
                trust_radius_min_deg=float(self.chain_space_trust_radius_min_deg),
                trust_radius_max_deg=float(self.chain_space_trust_radius_max_deg),
                min_clip_improvement=float(self.chain_space_min_clip_improvement),
                eval_budget=self.chain_space_eval_budget,
            )
        if bool(self.sa_enabled):
            if int(self.sa_restarts) < 1:
                raise ValueError("sa_restarts must be at least 1 when SA is enabled")
            if int(self.sa_iterations) < 1:
                raise ValueError("sa_iterations must be at least 1 when SA is enabled")
            if (
                not math.isfinite(float(self.sa_initial_temperature))
                or float(self.sa_initial_temperature) <= 0.0
            ):
                raise ValueError("sa_initial_temperature must be finite and positive")
            if (
                not math.isfinite(float(self.sa_final_temperature))
                or float(self.sa_final_temperature) <= 0.0
            ):
                raise ValueError("sa_final_temperature must be finite and positive")
            if float(self.sa_final_temperature) >= float(self.sa_initial_temperature):
                raise ValueError("sa_final_temperature must be less than sa_initial_temperature")
            if (
                not math.isfinite(float(self.sa_perturbation_scale_deg))
                or float(self.sa_perturbation_scale_deg) <= 0.0
            ):
                raise ValueError("sa_perturbation_scale_deg must be finite and positive")
            if (
                not math.isfinite(float(self.sa_bone_fraction))
                or not 0.0 < float(self.sa_bone_fraction) <= 1.0
            ):
                raise ValueError("sa_bone_fraction must be in (0, 1]")
            if int(self.sa_min_bone_depth) < 0:
                raise ValueError("sa_min_bone_depth must be non-negative")
            if self.sa_collision_weight is not None and (
                not math.isfinite(float(self.sa_collision_weight))
                or float(self.sa_collision_weight) < 0.0
            ):
                raise ValueError("sa_collision_weight must be finite and non-negative when set")
        if bool(self.ik_enabled):
            source = str(self.ik_keypoints_source)
            if source not in {"authored", "silhouette_miss"}:
                raise ValueError("ik_keypoints_source must be authored or silhouette_miss")
            if source == "authored" and not self.ik_keypoints_path:
                raise ValueError("ik_keypoints_path is required when IK uses authored keypoints")
            if source == "authored" and not self.ik_bone_roles_path:
                raise ValueError("ik_bone_roles_path is required when IK uses authored keypoints")
            if int(self.ik_iterations) < 1:
                raise ValueError("ik_iterations must be at least 1 when IK is enabled")
            if (
                not math.isfinite(float(self.ik_max_step_deg))
                or float(self.ik_max_step_deg) <= 0.0
            ):
                raise ValueError("ik_max_step_deg must be finite and positive")
            if (
                not math.isfinite(float(self.ik_blob_iou_target))
                or not 0.0 < float(self.ik_blob_iou_target) <= 1.0
            ):
                raise ValueError("ik_blob_iou_target must be in (0, 1]")
            if int(self.ik_proximal_min_depth) < 0:
                raise ValueError("ik_proximal_min_depth must be non-negative")
            if (
                not math.isfinite(float(self.ik_proximal_max_step_deg))
                or float(self.ik_proximal_max_step_deg) <= 0.0
            ):
                raise ValueError("ik_proximal_max_step_deg must be finite and positive")
            if int(self.ik_max_chain_depth) < 1:
                raise ValueError("ik_max_chain_depth must be at least 1")
            if int(self.ik_repair_dilate_px) < 0:
                raise ValueError("ik_repair_dilate_px must be non-negative")
            if int(self.ik_blob_search_rounds) < 1:
                raise ValueError("ik_blob_search_rounds must be at least 1")
            score_mode = str(self.ik_silhouette_score_mode)
            if score_mode not in {"regional_iou", "frame_hybrid"}:
                raise ValueError(
                    "ik_silhouette_score_mode must be regional_iou or frame_hybrid"
                )
            for field_name, allowed in (
                ("ik_job_order_mode", {"pair_rank", "displacement", "priority"}),
                ("ik_step_scale_mode", {"fixed", "displacement", "deficit", "combined"}),
                ("ik_chain_start_mode", {"distal", "displacement"}),
                ("ik_frame_order_mode", {"clip", "deficit"}),
            ):
                value = str(getattr(self, field_name))
                if value not in allowed:
                    raise ValueError(f"{field_name} must be one of {sorted(allowed)}")
            if (
                not math.isfinite(float(self.ik_step_displacement_ref_px))
                or float(self.ik_step_displacement_ref_px) <= 0.0
            ):
                raise ValueError("ik_step_displacement_ref_px must be finite and positive")
            if (
                not math.isfinite(float(self.ik_chain_displacement_ref_px))
                or float(self.ik_chain_displacement_ref_px) <= 0.0
            ):
                raise ValueError("ik_chain_displacement_ref_px must be finite and positive")
            if (
                not math.isfinite(float(self.ik_step_scale_min))
                or float(self.ik_step_scale_min) <= 0.0
            ):
                raise ValueError("ik_step_scale_min must be finite and positive")
            if (
                not math.isfinite(float(self.ik_step_scale_max))
                or float(self.ik_step_scale_max) < float(self.ik_step_scale_min)
            ):
                raise ValueError("ik_step_scale_max must be finite and >= ik_step_scale_min")
            dominance = float(self.ik_influence_dominance_min)
            if not math.isfinite(dominance) or dominance < 0.0 or dominance > 1.0:
                raise ValueError("ik_influence_dominance_min must be in [0, 1]")
        if bool(self.anatomy_head_pin_enabled):
            parts = tuple(str(part) for part in self.anatomy_head_pin_parts)
            if not parts:
                raise ValueError("anatomy_head_pin_parts must be non-empty")
            chain = tuple(str(bone) for bone in self.anatomy_head_pin_chain_bones)
            if not chain:
                raise ValueError("anatomy_head_pin_chain_bones must be non-empty")
            if int(self.anatomy_head_pin_iterations) < 1:
                raise ValueError("anatomy_head_pin_iterations must be at least 1")
            if (
                not math.isfinite(float(self.anatomy_head_pin_max_step_deg))
                or float(self.anatomy_head_pin_max_step_deg) <= 0.0
            ):
                raise ValueError("anatomy_head_pin_max_step_deg must be finite and positive")
            metric = str(self.anatomy_head_pin_accept_metric).strip().lower()
            if metric not in {"hybrid", "geometry", "silhouette"}:
                raise ValueError(
                    "anatomy_head_pin_accept_metric must be hybrid, geometry, or silhouette"
                )
        if bool(self.score_escape_collision_burst_enabled):
            threshold = float(self.score_escape_collision_burst_threshold)
            if not math.isfinite(threshold) or threshold < 0.0:
                raise ValueError("score_escape_collision_burst_threshold must be non-negative")
        if bool(self.idle_fused_macro_enabled):
            from cascade_idle_fused_stack import IDLE_FUSED_IMPORTANCE_MODES

            mode = str(self.idle_fused_importance_mode)
            if mode not in IDLE_FUSED_IMPORTANCE_MODES:
                raise ValueError(
                    "idle_fused_importance_mode must be one of: "
                    + ", ".join(IDLE_FUSED_IMPORTANCE_MODES)
                )
            if int(self.idle_fused_worst_frame_count) < 1:
                raise ValueError("idle_fused_worst_frame_count must be at least 1")
            if int(self.idle_fused_top_bone_count) < 2:
                raise ValueError("idle_fused_top_bone_count must be at least 2")
            if int(self.idle_fused_macro_chain_count) < 1:
                raise ValueError("idle_fused_macro_chain_count must be at least 1")
            if float(self.idle_fused_root_window_deg) <= 0.0:
                raise ValueError("idle_fused_root_window_deg must be positive")
            if float(self.idle_fused_root_step_deg) <= 0.0:
                raise ValueError("idle_fused_root_step_deg must be positive")
            if float(self.idle_fused_macro_step_deg) <= 0.0:
                raise ValueError("idle_fused_macro_step_deg must be positive")
            if int(self.idle_fused_per_frame_root_count) < 1:
                raise ValueError("idle_fused_per_frame_root_count must be at least 1")
            if bool(self.idle_fused_shared_transit_yaw_enabled):
                if float(self.idle_fused_shared_transit_yaw_window_deg) <= 0.0:
                    raise ValueError(
                        "idle_fused_shared_transit_yaw_window_deg must be positive"
                    )
                if float(self.idle_fused_shared_transit_yaw_step_deg) <= 0.0:
                    raise ValueError(
                        "idle_fused_shared_transit_yaw_step_deg must be positive"
                    )
                if int(self.idle_fused_shared_transit_yaw_bone_adapt_rounds) < 0:
                    raise ValueError(
                        "idle_fused_shared_transit_yaw_bone_adapt_rounds must be non-negative"
                    )
                if int(self.idle_fused_shared_transit_yaw_bone_adapt_top_bones) < 1:
                    raise ValueError(
                        "idle_fused_shared_transit_yaw_bone_adapt_top_bones must be at least 1"
                    )
                if int(self.idle_fused_shared_transit_yaw_post_articulated_iterations) < 0:
                    raise ValueError(
                        "idle_fused_shared_transit_yaw_post_articulated_iterations must be non-negative"
                    )
        if int(self.branch_rescue_block_size) not in {2, 3}:
            raise ValueError("branch_rescue_block_size must be 2 or 3")
        if int(self.branch_rescue_values_per_bone) < 2:
            raise ValueError("branch_rescue_values_per_bone must be at least 2")
        from cascade_bone_order import validate_cascade_bone_order_mode

        validate_cascade_bone_order_mode(str(self.bone_order_mode))
        if float(self.min_leaf_length_frac) <= 0.0:
            raise ValueError("min_leaf_length_frac must be positive")
        if int(self.joint_probe_rungs) < 1:
            raise ValueError("joint_probe_rungs must be at least 1")
        if int(self.joint_score_raster_batch) < 1:
            raise ValueError("joint_score_raster_batch must be at least 1; it is the VRAM raster cap, not an off switch")
        if int(self.cheap_joint_probe_frame_count) < 0:
            raise ValueError("cheap_joint_probe_frame_count must be >= 0 (0 = every free frame)")
        if not set(self.joint_search_axes) <= {"x", "y", "z"} or not self.joint_search_axes:
            raise ValueError("joint_search_axes must contain one or more of x, y, z")
        if int(self.adaptive_learning_rate_reject_patience) < 1:
            raise ValueError("adaptive_learning_rate_reject_patience must be positive")
        if not math.isfinite(float(self.adaptive_learning_rate_multiplier)) or float(self.adaptive_learning_rate_multiplier) <= 1.0:
            raise ValueError("adaptive_learning_rate_multiplier must be greater than 1")
        if not math.isfinite(float(self.adaptive_learning_rate_max_multiplier)) or float(self.adaptive_learning_rate_max_multiplier) < 1.0:
            raise ValueError("adaptive_learning_rate_max_multiplier must be at least 1")
        if float(self.adaptive_learning_rate_max_multiplier) < float(self.adaptive_learning_rate_multiplier):
            raise ValueError("adaptive_learning_rate_max_multiplier must be at least adaptive_learning_rate_multiplier")
        if (self.root_rotation_min_deg is None) != (self.root_rotation_max_deg is None):
            raise ValueError(
                "root_rotation_min_deg and root_rotation_max_deg must be supplied together"
            )
        if self.root_rotation_min_deg is not None:
            minimum = float(self.root_rotation_min_deg)
            maximum = float(self.root_rotation_max_deg)
            limit = float(self.root_rotation_limit_optimization_deg)
            if not math.isfinite(minimum) or not math.isfinite(maximum) or minimum >= maximum:
                raise ValueError("root rotation bounds must be finite and min < max")
            if minimum < -limit or maximum > limit:
                raise ValueError(
                    "root rotation bounds must lie within root_rotation_limit_optimization_deg"
                )
        allowed_rotation_axes = {"camera_forward", "camera_right", "camera_up"}
        if not set(self.root_rotation_axes) <= allowed_rotation_axes:
            raise ValueError(
                "root_rotation_axes must contain only camera_forward, "
                "camera_right, or camera_up"
            )
        allowed_translation_axes = {"forward", "lateral", "vertical"}
        if not set(self.root_translation_axes) <= allowed_translation_axes:
            raise ValueError(
                "root_translation_axes must contain only forward, lateral, or vertical"
            )
        self.physics_smooth_config().validate()


def _quat_to_matrix(quaternion: np.ndarray) -> np.ndarray:
    q = np.asarray(quaternion, dtype=np.float64).reshape(4)
    norm = float(np.linalg.norm(q))
    if norm <= 1e-12:
        raise ValueError("node quaternion has zero length")
    x, y, z, w = q / norm
    return np.asarray(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=np.float32,
    )


def _quat_multiply(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    lx, ly, lz, lw = np.asarray(left, dtype=np.float64).reshape(4)
    rx, ry, rz, rw = np.asarray(right, dtype=np.float64).reshape(4)
    value = np.asarray(
        (
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
            lw * rw - lx * rx - ly * ry - lz * rz,
        ),
        dtype=np.float64,
    )
    norm = float(np.linalg.norm(value))
    if norm <= 1e-12:
        raise ValueError("quaternion multiplication produced a zero quaternion")
    return value / norm


def _axis_angle_quaternion_np(vector: Any) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float64).reshape(3)
    angle = float(np.linalg.norm(vector))
    if angle <= 1e-12:
        return np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float64)
    axis = vector / angle
    half = angle * 0.5
    return np.asarray(
        (
            axis[0] * math.sin(half),
            axis[1] * math.sin(half),
            axis[2] * math.sin(half),
            math.cos(half),
        ),
        dtype=np.float64,
    )


def _gpu_world_matrices(asset: ProxyAsset, pose: Mapping[str, Any] | None) -> np.ndarray:
    """Reconstruct the GPU proxy's raw glTF joint worlds on the CPU.

    This is used only at final-preview cadence. The optimizer remains fully
    GPU-resident; the matrices let Blender consume exact relative skinning
    deformations without guessing each imported bone's local roll.
    """
    pose = pose or {}
    locals_: list[np.ndarray] = []
    for node in asset.nodes:
        value = pose.get(node.name)
        if isinstance(value, Mapping):
            vector = [float(value.get(axis, 0.0)) for axis in ("x", "y", "z")]
        else:
            vector = (0.0, 0.0, 0.0)
        rotation = _quat_to_matrix(
            _quat_multiply(node.rotation, _axis_angle_quaternion_np(vector))
        ).astype(np.float64)
        local = np.eye(4, dtype=np.float64)
        local[:3, :3] = rotation @ np.diag(np.asarray(node.scale, dtype=np.float64))
        local[:3, 3] = np.asarray(node.translation, dtype=np.float64)
        locals_.append(local)
    worlds: list[np.ndarray | None] = [None] * len(asset.nodes)

    def visit(index: int) -> np.ndarray:
        if worlds[index] is None:
            parent = asset.nodes[index].parent
            worlds[index] = locals_[index] if parent is None else visit(int(parent)) @ locals_[index]
        return worlds[index]

    return np.stack([visit(index) for index in range(len(asset.nodes))])


def _gpu_pose_deformation_matrices(
    asset: ProxyAsset,
    rest_worlds: np.ndarray,
    pose: Mapping[str, Any],
) -> dict[str, list[list[float]]]:
    """Return Blender-basis relative skinning matrices for one GPU pose."""
    current_worlds = _gpu_world_matrices(asset, pose)
    basis = np.eye(4, dtype=np.float64)
    basis[:3, :3] = GLTF_TO_BLENDER_BASIS
    inverse_basis = basis.T
    result: dict[str, list[list[float]]] = {}
    for index, node in enumerate(asset.nodes):
        raw_deformation = current_worlds[index] @ np.linalg.inv(rest_worlds[index])
        blender_deformation = basis @ raw_deformation @ inverse_basis
        result[node.name] = blender_deformation.tolist()
    return result


def _axis_angle_matrix_np(axis: np.ndarray, angle: float) -> np.ndarray:
    """Return one Rodrigues rotation matrix for the export-only CPU bridge."""
    axis = np.asarray(axis, dtype=np.float64).reshape(3)
    norm = float(np.linalg.norm(axis))
    if norm <= 1e-12 or abs(float(angle)) <= 1e-12:
        return np.eye(3, dtype=np.float64)
    axis = axis / norm
    x, y, z = axis
    c = math.cos(float(angle))
    s = math.sin(float(angle))
    one_minus_c = 1.0 - c
    return np.asarray(
        (
            (c + x * x * one_minus_c, x * y * one_minus_c - z * s, x * z * one_minus_c + y * s),
            (y * x * one_minus_c + z * s, c + y * y * one_minus_c, y * z * one_minus_c - x * s),
            (z * x * one_minus_c - y * s, z * y * one_minus_c + x * s, c + z * z * one_minus_c),
        ),
        dtype=np.float64,
    )


def _gpu_deformed_vertex_buffers(
    asset: ProxyAsset,
    pose: Mapping[str, Any],
    *,
    camera: Mapping[str, Any],
    root_pivot: np.ndarray,
    mesh_scale: float,
) -> dict[str, list[list[float]]]:
    """Evaluate the exact GPU LBS triangles for the Blender preview bridge.

    The optimizer and the final preview must not have two independent pose
    interpreters.  This function mirrors ``GpuCascadeExperiment``'s complete
    vertex path, including camera-space motion-root rotation/translation, and
    sends the resulting vertex buffer to Blender only after optimization.
    """
    current_worlds = _gpu_world_matrices(asset, pose)
    root_basis = np.asarray(
        (camera["forward"], camera["right"], camera["up"]),
        dtype=np.float64,
    )
    root_translation = pose.get(MOTION_ROOT_KEY, {})
    root_rotation = pose.get(MOTION_ROOT_ROTATION_KEY, {})
    translation_values = np.asarray(
        [
            float(root_translation.get(axis, 0.0))
            if isinstance(root_translation, Mapping)
            else 0.0
            for axis in ("forward", "lateral", "vertical")
        ],
        dtype=np.float64,
    )
    rotation_values = np.asarray(
        [
            math.radians(float(root_rotation.get(axis, 0.0)))
            if isinstance(root_rotation, Mapping)
            else 0.0
            for axis in ("camera_forward", "camera_right", "camera_up")
        ],
        dtype=np.float64,
    )
    root_rotation_matrix = np.eye(3, dtype=np.float64)
    for axis_index in range(3):
        root_rotation_matrix = (
            _axis_angle_matrix_np(root_basis[axis_index], rotation_values[axis_index])
            @ root_rotation_matrix
        )
    displacement = translation_values @ root_basis

    buffers: dict[str, list[list[float]]] = {}
    for primitive in asset.primitives:
        positions = np.concatenate(
            (
                np.asarray(primitive.positions, dtype=np.float64),
                np.ones((len(primitive.positions), 1)),
            ),
            axis=1,
        )
        if primitive.skin is None or primitive.joints is None or primitive.weights is None:
            skinned = positions
        else:
            skin = asset.skins[int(primitive.skin)]
            joint_matrices = np.stack(
                [
                    current_worlds[node] @ inverse_bind
                    for node, inverse_bind in zip(skin.joints, skin.inverse_bind)
                ],
                axis=0,
            )
            transformed = np.einsum("jkl,nl->jnk", joint_matrices, positions)
            vertex_indices = np.arange(len(positions), dtype=np.int64)[:, None]
            selected = transformed[primitive.joints, vertex_indices, :]
            weights = np.asarray(primitive.weights, dtype=np.float64)
            weights = weights / np.maximum(weights.sum(axis=1, keepdims=True), 1e-12)
            skinned = np.sum(selected * weights[:, :, None], axis=1)
        world = (current_worlds[int(primitive.node)] @ skinned.T).T[:, :3]
        centered = world - np.asarray(root_pivot, dtype=np.float64).reshape(1, 3)
        world = centered @ root_rotation_matrix.T + np.asarray(root_pivot, dtype=np.float64).reshape(1, 3)
        world = world + displacement.reshape(1, 3)
        blender_world = (GLTF_TO_BLENDER_BASIS @ world.T).T * float(mesh_scale)
        object_name = asset.nodes[int(primitive.node)].name
        if object_name in buffers:
            raise ValueError(
                "GPU preview vertex bridge requires one primitive per mesh node; "
                f"node {object_name!r} has multiple primitives"
            )
        buffers[object_name] = blender_world.tolist()
    return buffers


def _axis_angle_matrix(vector):
    """Differentiable Rodrigues rotation for a batch of rotation vectors."""
    import torch

    angle = torch.linalg.vector_norm(vector, dim=-1, keepdim=True)
    half = angle * 0.5
    safe_angle = torch.clamp(angle, min=1e-7)
    scale = torch.where(
        angle > 1e-7,
        torch.sin(half) / safe_angle,
        0.5 - (angle * angle) / 48.0,
    )
    xyz = vector * scale
    x, y, z = xyz.unbind(dim=-1)
    w = torch.cos(half[..., 0])
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return torch.stack(
        (
            1.0 - 2.0 * (yy + zz),
            2.0 * (xy - wz),
            2.0 * (xz + wy),
            2.0 * (xy + wz),
            1.0 - 2.0 * (xx + zz),
            2.0 * (yz - wx),
            2.0 * (xz - wy),
            2.0 * (yz + wx),
            1.0 - 2.0 * (xx + yy),
        ),
        dim=-1,
    ).reshape(*vector.shape[:-1], 3, 3)


def backtracked_learning_rate(
    *,
    current: float,
    base: float,
    reject_streak: int,
    patience: int,
    divisor: float,
    max_divisor: float,
) -> float:
    """Return the learning rate after a worse optimizer step.

    Growing ``lr`` after a reject takes a larger overshoot. This shrinks
    toward ``base / max_divisor``.
    """
    current_value = float(current)
    base_value = float(base)
    if int(reject_streak) < int(patience):
        return current_value
    floor = base_value / float(max_divisor)
    shrunk = current_value / float(divisor)
    if shrunk < floor:
        return floor
    return shrunk


def joint_line_search_radians(base_rad: float, halves: int) -> tuple[float, ...]:
    """Kept for root-stage tests. Joint stages no longer slope-step."""
    if not math.isfinite(float(base_rad)) or float(base_rad) <= 0.0:
        raise ValueError("base_rad must be positive")
    if int(halves) < 0:
        raise ValueError("halves must be non-negative")
    return tuple(float(base_rad) / (2 ** stage) for stage in range(int(halves) + 1))


JOINT_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def signed_step_grid_deg(step_deg: float, limit_deg: float) -> tuple[float, ...]:
    """``±step, ±2step, ...`` up to ``limit``. 0 is the current pose, scored separately."""
    step = float(step_deg)
    limit = float(limit_deg)
    if not math.isfinite(step) or step <= 0.0:
        raise ValueError("step_deg must be positive")
    if not math.isfinite(limit) or limit < step:
        raise ValueError("limit_deg must be at least step_deg")
    values: list[float] = []
    n = 1
    while n * step <= limit + 1e-9:
        values.append(n * step)
        values.append(-n * step)
        n += 1
    return tuple(values)


def axis_rung_after(delta_deg: float, *, step_deg: float, limit_deg: float) -> float | None:
    """Next larger same-sign delta, or None past ``limit_deg``."""
    grown = math.copysign(abs(float(delta_deg)) + float(step_deg), float(delta_deg))
    if abs(grown) <= float(limit_deg) + 1e-9:
        return float(grown)
    return None


def joint_score_hyps_per_launch(*, pose_budget: int, frame_count: int) -> int:
    """How many clip-length hypotheses fit in one packed ``evaluate`` call.

    ``joint_score_raster_batch`` is pose slots, not hypotheses. Hypotheses per
    launch are ``pose_budget // frame_count`` (at least 1). A budget smaller
    than the clip length is GPU starvation: every probe becomes its own kernel.
    """
    frames = int(frame_count)
    budget = int(pose_budget)
    if frames < 1:
        raise ValueError("frame_count must be at least 1")
    if budget < 1:
        raise ValueError("pose_budget must be at least 1")
    return max(1, budget // frames)


def adam_stage_stalled(reject_streak: int, patience: int) -> bool:
    """True when consecutive rejected Adam steps mean later steps will restore the same best."""
    if int(patience) <= 0:
        return False
    return int(reject_streak) >= int(patience)


def joint_probe_should_run_consensus(*, probe_moved: int) -> bool:
    """Walk 0→N / N→0 consensus only after a probe kept a new angle.

    Consensus on an unchanged pose repeats the same keep surface and is the
    dominant cost of a settled articulated round.
    """
    moved = int(probe_moved)
    if moved < 0:
        raise ValueError("probe_moved must be non-negative")
    return moved > 0


def joint_round_should_run_consensus(
    *,
    probe_moved_count: int,
    combo_moved_count: int,
    shared_keep: bool,
) -> bool:
    """One temporal-consensus pass per articulated round, after probes and combo.

    Shared-keep stages (base / articulated_broad) already force a common pose
    per bone; neighbor-copy consensus there overfits and repeats clip evals.
    """
    if int(probe_moved_count) < 0:
        raise ValueError("probe_moved_count must be non-negative")
    if int(combo_moved_count) < 0:
        raise ValueError("combo_moved_count must be non-negative")
    if bool(shared_keep):
        return False
    return joint_probe_should_run_consensus(
        probe_moved=int(probe_moved_count) + int(combo_moved_count)
    )


def joint_round_followup_bones(
    all_bones: Sequence[int],
    moved_bones: Sequence[int],
    parent_of: Mapping[int, int | None],
) -> tuple[int, ...]:
    """Bones worth another probe after a round: movers and their parent/child neighbors.

    A bone that did not keep a new angle, and is not next to one that did, would
    see the same step window on the same pose. Re-probing it is a wasted phase
    step. An empty result means this stage is stalled and the next cascade
    phase should start. Neighbor copies that did not change the probe winner
    do not count as movers.
    """
    allowed = {int(bone) for bone in all_bones}
    moved = {int(bone) for bone in moved_bones if int(bone) in allowed}
    if not moved:
        return ()

    def first_allowed_parent(bone: int) -> int | None:
        seen: set[int] = set()
        current = parent_of.get(int(bone))
        while current is not None:
            cur = int(current)
            if cur in seen:
                return None
            seen.add(cur)
            if cur in allowed:
                return cur
            current = parent_of.get(cur)
        return None

    children: dict[int, list[int]] = {}
    search_parent: dict[int, int | None] = {}
    for bone in allowed:
        parent = first_allowed_parent(int(bone))
        search_parent[int(bone)] = parent
        if parent is not None:
            children.setdefault(parent, []).append(int(bone))
    follow = set(moved)
    for bone in moved:
        parent = search_parent.get(int(bone))
        if parent is not None:
            follow.add(int(parent))
        follow.update(children.get(int(bone), ()))
    return tuple(bone for bone in all_bones if int(bone) in follow)



JOINT_STEP_SCORE_NORMS = ("raw", "clip_minmax", "logit_minmax", "rank", "robust_z")


def normalize_keep_scores_for_joint_step(scores, *, mode: str):
    """Expand a compressed keep-score band so idle vs walk can differ.

    ``raw`` leaves qualities alone. ``clip_minmax`` affines the current
    clip to 0..1. ``logit_minmax`` (keep) does that after a logit so
    values near 1 spread out. ``rank`` uses only order. ``robust_z`` is a
    median/MAD sigmoid. A clip with no contrast maps to 0.5, which is the
    mid step, not a silent copy of the raw band.
    """
    name = str(mode)
    if name not in JOINT_STEP_SCORE_NORMS:
        raise ValueError(
            "joint_step_score_norm must be one of " + ", ".join(JOINT_STEP_SCORE_NORMS)
        )
    import torch

    if not isinstance(scores, torch.Tensor):
        tensor = torch.as_tensor(scores, dtype=torch.float32)
    else:
        tensor = scores.to(dtype=torch.float32)
    if int(tensor.numel()) < 1:
        raise ValueError("keep scores are empty")
    if not bool(torch.isfinite(tensor).all()):
        raise ValueError("keep scores must be finite")
    if name == "raw":
        return tensor
    flat = tensor.reshape(-1)

    def minmax(values):
        lo = values.min()
        hi = values.max()
        span = hi - lo
        if float(span.detach().item()) <= 1e-8:
            return torch.full_like(values, 0.5)
        return (values - lo) / span

    if name == "clip_minmax":
        return minmax(tensor)
    if name == "logit_minmax":
        eps = 1e-6
        clamped = tensor.clamp(eps, 1.0 - eps)
        logit = torch.log(clamped) - torch.log1p(-clamped)
        return minmax(logit)
    if name == "rank":
        count = int(flat.numel())
        if count == 1:
            return torch.full_like(tensor, 0.5)
        order = torch.argsort(flat)
        ranks = torch.empty_like(flat)
        ranks[order] = torch.arange(count, device=flat.device, dtype=flat.dtype)
        return (ranks / float(count - 1)).view_as(tensor)
    median = flat.median()
    mad = (flat - median).abs().median()
    if float(mad.detach().item()) <= 1e-8:
        return torch.full_like(tensor, 0.5)
    z = 0.6745 * (tensor - median) / mad
    return torch.sigmoid(z)


def joint_unit_step_deg(
    score,
    *,
    coarse_deg: float,
    fine_deg: float,
    coarse_score: float,
    fine_score: float,
):
    """Per-frame joint unit step from the current keep score.

    geometryScore at/above fine_score uses fine_deg. At/below coarse_score
    uses coarse_deg. Between those scores the step lerps linearly. A
    high-scoring idle therefore never sees the 15/45 window; a low-scoring
    walk frame still does.
    """
    if not math.isfinite(float(coarse_deg)) or float(coarse_deg) <= 0.0:
        raise ValueError("coarse_deg must be finite and positive")
    if not math.isfinite(float(fine_deg)) or float(fine_deg) <= 0.0:
        raise ValueError("fine_deg must be finite and positive")
    if float(fine_deg) - float(coarse_deg) > 1e-12:
        raise ValueError("fine_deg must be <= coarse_deg")
    if not math.isfinite(float(coarse_score)):
        raise ValueError("coarse_score must be finite")
    if not math.isfinite(float(fine_score)):
        raise ValueError("fine_score must be finite")
    if float(fine_score) <= float(coarse_score):
        raise ValueError("fine_score must be greater than coarse_score")
    span = float(fine_score) - float(coarse_score)
    coarse = float(coarse_deg)
    fine = float(fine_deg)

    def lerp_from_score(value: float) -> float:
        if not math.isfinite(float(value)):
            raise ValueError("score must be finite")
        if float(value) >= float(fine_score):
            return fine
        if float(value) <= float(coarse_score):
            return coarse
        t = (float(fine_score) - float(value)) / span
        return fine + t * (coarse - fine)

    try:
        import torch
    except ImportError:
        torch = None
    if torch is not None and isinstance(score, torch.Tensor):
        if not bool(torch.isfinite(score).all()):
            raise ValueError("score must be finite")
        high = score >= float(fine_score)
        low = score <= float(coarse_score)
        t = (float(fine_score) - score) / span
        lerped = fine + t * (coarse - fine)
        return torch.where(high, torch.full_like(score, fine), torch.where(low, torch.full_like(score, coarse), lerped))
    return lerp_from_score(float(score))


def first_axis_window_deg(step_deg: float, *, rungs: int, limit_deg: float) -> tuple[float, ...]:
    """``±step … ±rungs*step`` scored as siblings, clipped to ``limit_deg``.

    Growing only after ±step is kept never tries 45° when 15° is worse.
    The opening window must include those larger rungs.
    """
    if int(rungs) < 1:
        raise ValueError("rungs must be at least 1")
    values: list[float] = []
    for index in range(1, int(rungs) + 1):
        delta = float(index) * float(step_deg)
        if delta > float(limit_deg) + 1e-9:
            break
        values.append(delta)
        values.append(-delta)
    if not values:
        raise ValueError("limit_deg must be at least step_deg")
    return tuple(values)


def offset_raw_bone_axis(
    raw,
    *,
    bone_index: int,
    axis_index: int,
    delta_rad: float,
    joint_limit_rad: float,
    bone_limit_scales,
):
    """Add ``delta_rad`` to one bone axis on every frame, then invert tanh."""
    import torch

    if not math.isfinite(float(delta_rad)) or float(delta_rad) == 0.0:
        raise ValueError("delta_rad must be a nonzero finite angle")
    scales = bone_limit_scales.to(device=raw.device, dtype=raw.dtype).reshape(-1)
    joint = int(bone_index)
    axis = int(axis_index)
    if joint < 0 or joint >= int(scales.numel()):
        raise ValueError(f"bone_index {joint} is outside 0..{int(scales.numel()) - 1}")
    if axis not in (0, 1, 2):
        raise ValueError(f"axis_index {axis} must be 0, 1, or 2")
    limit = float(joint_limit_rad) * float(scales[joint].detach().item())
    if limit <= 1e-12:
        raise ValueError(f"bone {joint} has a zero joint limit")
    bounded = torch.tanh(raw) * float(joint_limit_rad) * scales.view(1, -1, 1)
    new_angle = (bounded[:, joint, axis] + float(delta_rad)).clamp(-limit, limit)
    ratio = (new_angle / limit).clamp(-0.999, 0.999)
    out = raw.detach().clone()
    out[:, joint, axis] = torch.atanh(ratio)
    return out


def gather_per_frame_winners(raw_choices, score_choices, *, min_improvement: float = 0.0):
    """Keep, independently per frame, the candidate with the highest image score.

    Candidate 0 is the current pose. A walk frame can keep +45° while idle
    keeps 0°. Clip-mean accept/reject is how a 15° walk used to be vetoed.
    """
    import torch

    if len(raw_choices) != len(score_choices) or not raw_choices:
        raise ValueError("raw_choices and score_choices must be non-empty and the same length")
    stacked_scores = torch.stack([score.reshape(-1) for score in score_choices], dim=0)
    stacked_raw = torch.stack(list(raw_choices), dim=0)
    if int(stacked_raw.shape[1]) != int(stacked_scores.shape[1]):
        raise ValueError(
            "pose batch does not match score frames: "
            f"poses={int(stacked_raw.shape[1])} scores={int(stacked_scores.shape[1])}"
        )
    winner = stacked_scores.argmax(dim=0)
    frame_index = torch.arange(winner.shape[0], device=winner.device)
    if float(min_improvement) > 0.0:
        chosen_scores = stacked_scores[winner, frame_index]
        current_scores = stacked_scores[0]
        winner = torch.where(
            chosen_scores > current_scores + float(min_improvement),
            winner,
            torch.zeros_like(winner),
        )
    blended = stacked_raw[winner, frame_index]
    chosen_scores = stacked_scores[winner, frame_index]
    return blended, winner, chosen_scores


def consecutive_sprite_rgb_mad(frame_paths: Sequence[Path]) -> tuple[float, ...]:
    """Mean-abs RGB of each PNG versus the previous file. Frame 0 is 1.0."""
    paths = [Path(path) for path in frame_paths]
    if not paths:
        raise ValueError("consecutive_sprite_rgb_mad requires at least one PNG")
    arrays: list[np.ndarray] = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"still-sprite lock target PNG is missing: {path}")
        with Image.open(path) as image:
            arrays.append(np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0)
    mads: list[float] = [1.0]
    for index in range(1, len(arrays)):
        if arrays[index].shape != arrays[index - 1].shape:
            raise ValueError(
                "still-sprite lock frames must share a resolution: "
                f"{paths[index - 1].name} {arrays[index - 1].shape} vs "
                f"{paths[index].name} {arrays[index].shape}"
            )
        mads.append(float(np.mean(np.abs(arrays[index] - arrays[index - 1]))))
    return tuple(mads)


def still_sprite_lock_mask(
    mads: Sequence[float],
    *,
    threshold: float,
) -> tuple[bool, ...]:
    """Frame 0 is never still. Later frames lock when MAD is below threshold.

    Empty and all-but-first still masks fail closed: the first means the
    threshold never fires, the second would freeze the whole clip.
    """
    if not mads:
        raise ValueError("still_sprite_lock_mask requires consecutive MAD values")
    if not math.isfinite(float(threshold)) or float(threshold) <= 0.0 or float(threshold) >= 1.0:
        raise ValueError("still-sprite RGB MAD threshold must be in (0, 1)")
    still = [False]
    for mad in mads[1:]:
        still.append(float(mad) < float(threshold))
    still_count = sum(still)
    if still_count == 0:
        raise ValueError(
            "joint_keep_still_sprite_lock found no still frames; "
            f"threshold {float(threshold):.4f} is too low"
        )
    if still_count == len(still) - 1:
        raise ValueError(
            "joint_keep_still_sprite_lock would freeze every frame after 0; "
            f"threshold {float(threshold):.4f} is too high"
        )
    return tuple(still)


def lock_winner_indices_to_previous(
    winners: Sequence[int],
    still: Sequence[bool],
) -> list[int]:
    """Copy the previous frame's winner onto still frames, in order."""
    if len(winners) != len(still):
        raise ValueError(
            "winner count must match the still-sprite mask: "
            f"{len(winners)} winners, {len(still)} flags"
        )
    locked = [int(value) for value in winners]
    for index in range(1, len(locked)):
        if still[index]:
            locked[index] = locked[index - 1]
    return locked


def sprite_frame_change_maps(target_rgb):
    """Per-pixel mean-abs RGB of each sprite versus the previous plate.

    Frame 0 has no previous plate, so its map is zeros. This is the same
    quantity as the solver-watch change row, except the inputs are consecutive
    *sprites* rather than consecutive solver steps.
    """
    import torch

    if target_rgb.ndim != 4 or int(target_rgb.shape[-1]) != 3:
        raise ValueError("target RGB must have shape (F, H, W, 3)")
    if int(target_rgb.shape[0]) < 1:
        raise ValueError("sprite_frame_change_maps requires at least one frame")
    change = torch.zeros(
        target_rgb.shape[:3],
        dtype=target_rgb.dtype,
        device=target_rgb.device,
    )
    if int(target_rgb.shape[0]) > 1:
        change[1:] = (target_rgb[1:] - target_rgb[:-1]).abs().mean(dim=-1)
    return change


def excess_predicted_change(
    predicted_rgb,
    previous_rgb,
    sprite_change,
    occupancy,
    *,
    slack: float,
):
    """Occupancy-weighted mean of predicted change beyond the sprite change map.

    ``predicted_rgb`` is this candidate. ``previous_rgb`` is the previous clip
    frame of the same pose sequence (or the committed live plate when this
    batch is one sprite). Pixels may move as much as the sprite did, plus
    ``slack``. Extra motion is the keep penalty. Pixels where the prediction
    moved are always in the mean, so a twitch into empty background still
    counts.
    """
    import torch

    if predicted_rgb.shape != previous_rgb.shape:
        raise ValueError(
            "predicted and previous RGB shapes must match: "
            f"{tuple(predicted_rgb.shape)} vs {tuple(previous_rgb.shape)}"
        )
    if predicted_rgb.ndim != 4 or int(predicted_rgb.shape[-1]) != 3:
        raise ValueError("predicted RGB must have shape (B, H, W, 3)")
    if tuple(sprite_change.shape) != tuple(predicted_rgb.shape[:3]):
        raise ValueError(
            "sprite change map must be (B, H, W): "
            f"got {tuple(sprite_change.shape)} for RGB {tuple(predicted_rgb.shape)}"
        )
    if tuple(occupancy.shape) != tuple(predicted_rgb.shape[:3]):
        raise ValueError(
            "occupancy must be (B, H, W): "
            f"got {tuple(occupancy.shape)} for RGB {tuple(predicted_rgb.shape)}"
        )
    if not math.isfinite(float(slack)) or float(slack) < 0.0:
        raise ValueError("slack must be finite and non-negative")
    pred_change = (predicted_rgb - previous_rgb).abs().mean(dim=-1)
    excess = (pred_change - sprite_change - float(slack)).clamp_min(0.0)
    mass = occupancy.clamp_min(0.0)
    moved = (pred_change > 1e-6).to(dtype=mass.dtype)
    mass = torch.maximum(mass, moved)
    denom = mass.reshape(int(mass.shape[0]), -1).sum(dim=1).clamp_min(1e-6)
    numbered = (excess * mass).reshape(int(mass.shape[0]), -1).sum(dim=1)
    return numbered / denom


SPRITE_CHANGE_VETO_EPS = 1e-6


def veto_scores_on_sprite_change_excess(scores, excess, *, eps: float = SPRITE_CHANGE_VETO_EPS):
    """Zero DINOv3-style scores on rows that moved still pixels.

    Do not subtract excess from the score. Mixing RGB MAD into keep made the
    solver optimize the wrong objective.
    """
    import torch

    if scores.shape != excess.shape:
        raise ValueError(
            "score and excess shapes must match: "
            f"{tuple(scores.shape)} vs {tuple(excess.shape)}"
        )
    if not math.isfinite(float(eps)) or float(eps) < 0.0:
        raise ValueError("veto eps must be finite and non-negative")
    return torch.where(excess > float(eps), torch.zeros_like(scores), scores)


def mask_sprite_change_excess_to_still_frames(excess, still_mask, positions):
    """Zero excess on moving plates and on frame 0.

    A veto on every plate froze later frames: leaving bind changes more RGB
    than consecutive sprites do. Walk plates must keep DINOv3.
    """
    import torch

    if int(positions.numel()) != int(excess.shape[0]):
        raise ValueError(
            "positions must match excess rows: "
            f"{int(positions.numel())} vs {int(excess.shape[0])}"
        )
    still = still_mask.index_select(0, positions).to(dtype=torch.bool)
    masked = torch.where(still, excess, torch.zeros_like(excess))
    return torch.where(positions == 0, torch.zeros_like(masked), masked)


def invert_bounded_root_rotation(
    radians_values: np.ndarray,
    *,
    center: float,
    halves: np.ndarray,
    axis_index: int | None = None,
) -> np.ndarray:
    """Map camera-space root radians to tanh-raw using per-axis envelopes.

    One-bone root search feeds a 1D angle grid for one camera axis. Cascade
    feeds last-dim 3. After ``camera_up`` got a tighter envelope, halves is
    length 3 and a 1D grid can no longer broadcast.
    """
    values = np.asarray(radians_values, dtype=np.float64)
    axis_halves = np.asarray(halves, dtype=np.float64).reshape(-1)
    if int(axis_halves.size) != 3:
        raise ValueError(
            "root rotation halves must have 3 axes: "
            f"got {tuple(np.asarray(halves).shape)}"
        )
    if not math.isfinite(float(center)):
        raise ValueError("root rotation center must be finite")
    if bool(np.any(~np.isfinite(axis_halves))) or bool(np.any(axis_halves <= 0.0)):
        raise ValueError("root rotation halves must be finite and positive")
    if axis_index is not None:
        index = int(axis_index)
        if index not in (0, 1, 2):
            raise ValueError(f"root rotation axis_index must be 0, 1, or 2; got {axis_index!r}")
        half = float(axis_halves[index])
        normalized = (values - float(center)) / half
        return np.arctanh(np.clip(normalized, -0.999, 0.999)).astype(np.float32)
    if values.ndim == 0 or int(values.shape[-1]) != 3:
        raise ValueError(
            "root rotation inverse without axis_index requires last-dim 3; "
            f"got shape {tuple(values.shape)}"
        )
    normalized = (values - float(center)) / axis_halves
    return np.arctanh(np.clip(normalized, -0.999, 0.999)).astype(np.float32)


def previous_predicted_for_sprite_change_gate(
    predicted_rgb,
    frame_positions,
    committed_rgb,
):
    """Committed live plate for each batch row of a sprite-change gate.

    This is the solver-watch pairing (this step versus the last accepted
    picture of the *same* plate). The sprite change map is only the
    allowance. Packed hyps must not compare to another clip frame of the
    same hyp: that damped walk and left idle twitching.
    """
    import torch

    if predicted_rgb.ndim != 4 or int(predicted_rgb.shape[-1]) != 3:
        raise ValueError("predicted RGB must have shape (B, H, W, 3)")
    if committed_rgb.ndim != 4 or int(committed_rgb.shape[-1]) != 3:
        raise ValueError("committed RGB must have shape (F, H, W, 3)")
    if int(frame_positions.numel()) != int(predicted_rgb.shape[0]):
        raise ValueError(
            "frame_positions must match the predicted batch: "
            f"{int(frame_positions.numel())} vs {int(predicted_rgb.shape[0])}"
        )
    positions = frame_positions.detach().to(
        device=predicted_rgb.device,
        dtype=torch.long,
    )
    frame_count = int(committed_rgb.shape[0])
    if bool((positions < 0).any()) or bool((positions >= frame_count).any()):
        raise ValueError(
            "frame_positions contains indices outside the committed clip: "
            f"F={frame_count}, positions={positions.detach().cpu().tolist()}"
        )
    return committed_rgb.index_select(0, positions)


def extra_collision_keep_score(
    unique_geometry,
    collision,
    current_collision,
    *,
    collision_weight: float,
):
    """Penalize collision that is worse than the pose already on that frame.

    Subtracting the absolute collision term from unique keep rewarded a rest
    nibble that lowered self-intersection while unique remainder rose.
    Extra collision still rejects a pretzel. Reducing collision without a
    unique-geometry gain does not win the keep.
    """
    extra = (collision - current_collision).clamp_min(0.0)
    return unique_geometry - float(collision_weight) * extra


_PLANAR_DIAGONAL_AXES = (
    (1.0, 1.0, 0.0),
    (1.0, -1.0, 0.0),
    (1.0, 0.0, 1.0),
    (1.0, 0.0, -1.0),
    (0.0, 1.0, 1.0),
    (0.0, 1.0, -1.0),
)
_SPACE_DIAGONAL_AXES = (
    (1.0, 1.0, 1.0),
    (1.0, 1.0, -1.0),
    (1.0, -1.0, 1.0),
    (1.0, -1.0, -1.0),
)


def joint_search_directions(
    axes: Sequence[str],
    extra_diagonal_count: int,
) -> tuple[tuple[float, float, float], ...]:
    """Local XYZ plus optional cube-diagonal rotation-vector directions."""
    directions: list[tuple[float, float, float]] = []
    for axis in axes:
        token = str(axis)
        if token not in JOINT_AXIS_INDEX:
            raise ValueError(f"joint search axis {token!r} must be x, y, or z")
        vector = [0.0, 0.0, 0.0]
        vector[JOINT_AXIS_INDEX[token]] = 1.0
        directions.append((vector[0], vector[1], vector[2]))
    extras = _PLANAR_DIAGONAL_AXES + _SPACE_DIAGONAL_AXES
    count = int(extra_diagonal_count)
    if count < 0:
        raise ValueError("extra_diagonal_count must be non-negative")
    for raw in extras[:count]:
        norm = math.sqrt(sum(part * part for part in raw))
        directions.append(tuple(part / norm for part in raw))
    if not directions:
        raise ValueError("joint_search_directions produced no axes")
    return tuple(directions)


def joint_keep_score(
    *,
    absolute_geometry,
    unique_geometry,
    current_absolute,
    current_unique,
    collision,
    current_collision,
    absolute_gain_weight: float,
    unique_gain_weight: float,
    collision_weight: float,
    collision_enabled: bool,
    collision_positive_abs_slack: float = 0.0,
):
    """Keep is gain versus the current pose. Candidate zero therefore scores 0.

    Absolute geometry includes depth, chroma, and silhouette. The meshes were
    built around the sprites, so a worse sprite match never wins. Unique
    remainder may add extra credit or break a sprite-neutral tie; it cannot
    veto a sprite-improving move and cannot rescue a sprite-worsening one.

    Extra collision still vetoes a pretzel. Modest extra contact below
    ``collision_positive_abs_slack`` cannot veto a positive absolute gain,
    because the sprites themselves often show limb-on-torso overlap. Extra
    collision is still charged in full when absolute geometry does not
    improve, so a rest nibble that only lowers self-intersection does not win.
    """
    abs_gain = absolute_geometry - current_absolute
    unique_gain = unique_geometry - current_unique
    unique_term = unique_gain.where(abs_gain >= 0, unique_gain.new_zeros(unique_gain.shape))
    unique_term = unique_term.where(abs_gain <= 0, unique_gain.clamp_min(0.0))
    keep = float(absolute_gain_weight) * abs_gain + float(unique_gain_weight) * unique_term
    if bool(collision_enabled):
        extra = (collision - current_collision).clamp_min(0.0)
        slack = float(collision_positive_abs_slack)
        if not math.isfinite(slack) or slack < 0.0:
            raise ValueError("collision_positive_abs_slack must be finite and non-negative")
        charged = extra.where(abs_gain <= 0, (extra - slack).clamp_min(0.0))
        keep = keep - float(collision_weight) * charged
    return keep


def neighbor_copy_keep(copy_absolute, current_absolute, *, tie_bonus: float):
    """Keep a neighbor copy when it stays within the sprite-match tie budget.

    Independent per-frame winners can pick opposite angles on adjacent
    frames. ``tie_bonus`` is the per-frame absolute-geometry score a copy
    may give up and still win: equal sprite match prefers the smoother
    pose, and with a real budget (for example 0.01) a copy that worsens
    the sprite match by less than the budget also wins, trading a bounded
    amount of sprite accuracy for temporal agreement.
    """
    if not math.isfinite(float(tie_bonus)) or float(tie_bonus) <= 0.0:
        raise ValueError("tie_bonus must be finite and positive")
    abs_gain = copy_absolute - current_absolute
    return abs_gain + float(tie_bonus)


def copy_raw_bone_from_neighbor(
    raw,
    *,
    bone_index: int,
    source_offset: int,
    joint_limit_rad: float,
    bone_limit_scales,
):
    """Copy this bone's bounded angles from frame i+offset onto frame i.

    Frames whose neighbor does not exist keep their current raw value.
    """
    import torch

    offset = int(source_offset)
    if offset == 0:
        raise ValueError("source_offset must be nonzero")
    if not math.isfinite(float(joint_limit_rad)) or float(joint_limit_rad) <= 0.0:
        raise ValueError("joint_limit_rad must be finite and positive")
    scales = bone_limit_scales.to(device=raw.device, dtype=raw.dtype).reshape(-1)
    joint = int(bone_index)
    if joint < 0 or joint >= int(scales.numel()):
        raise ValueError(f"bone_index {joint} is outside 0..{int(scales.numel()) - 1}")
    limit = float(joint_limit_rad) * float(scales[joint].detach().item())
    if limit <= 1e-12:
        raise ValueError(f"bone {joint} has a zero joint limit")
    bounded = torch.tanh(raw) * float(joint_limit_rad) * scales.view(1, -1, 1)
    frame_count = int(raw.shape[0])
    destinations = torch.arange(frame_count, device=raw.device)
    sources = destinations + offset
    valid = (sources >= 0) & (sources < frame_count)
    copied = bounded[sources.clamp(0, max(frame_count - 1, 0)), joint, :]
    current = bounded[:, joint, :]
    new_angles = torch.where(valid.unsqueeze(-1), copied, current).clamp(-limit, limit)
    out = raw.detach().clone()
    out[:, joint, :] = torch.atanh((new_angles / limit).clamp(-0.999, 0.999))
    return out


def lerp_raw_bone_from_neighbors(
    raw,
    *,
    bone_index: int,
    joint_limit_rad: float,
    bone_limit_scales,
):
    """Replace interior frames with the midpoint of the previous and next angles."""
    import torch

    if not math.isfinite(float(joint_limit_rad)) or float(joint_limit_rad) <= 0.0:
        raise ValueError("joint_limit_rad must be finite and positive")
    scales = bone_limit_scales.to(device=raw.device, dtype=raw.dtype).reshape(-1)
    joint = int(bone_index)
    if joint < 0 or joint >= int(scales.numel()):
        raise ValueError(f"bone_index {joint} is outside 0..{int(scales.numel()) - 1}")
    limit = float(joint_limit_rad) * float(scales[joint].detach().item())
    if limit <= 1e-12:
        raise ValueError(f"bone {joint} has a zero joint limit")
    bounded = torch.tanh(raw) * float(joint_limit_rad) * scales.view(1, -1, 1)
    frame_count = int(raw.shape[0])
    destinations = torch.arange(frame_count, device=raw.device)
    interior = (destinations > 0) & (destinations < frame_count - 1)
    prev_idx = (destinations - 1).clamp(min=0)
    next_idx = (destinations + 1).clamp(max=max(frame_count - 1, 0))
    current = bounded[:, joint, :]
    midpoint = 0.5 * (bounded[prev_idx, joint, :] + bounded[next_idx, joint, :])
    new_angles = torch.where(interior.unsqueeze(-1), midpoint, current).clamp(-limit, limit)
    out = raw.detach().clone()
    out[:, joint, :] = torch.atanh((new_angles / limit).clamp(-0.999, 0.999))
    return out


IDLE_DEF_GROUP = 2
# Death stays down. Everything else in the idle-leading chain returns to rest.
IDLE_END_ANCHOR_SKIP_DEF_GROUPS = frozenset({5, 6})


def pose_sequence_without_trailing_idle(groups: Sequence[int]) -> tuple[int, ...]:
    sequence = tuple(int(group) for group in groups)
    while len(sequence) > 1 and sequence[-1] == IDLE_DEF_GROUP:
        sequence = sequence[:-1]
    return sequence


def clip_uses_idle_end_anchor(groups: Sequence[int]) -> bool:
    """True when reverse may start from the locked idle pose.

    Idle is prefixed for posing. Sequences that return to standing also get
    a trailing idle (and walk includes move-end). Reverse walks that whole
    chain backward from rest. Death does not return to idle.
    """
    sequence = tuple(int(group) for group in groups)
    if len(sequence) < 2 or sequence[0] != IDLE_DEF_GROUP:
        return False
    last = int(pose_sequence_without_trailing_idle(sequence)[-1])
    if last == IDLE_DEF_GROUP:
        return False
    return last not in IDLE_END_ANCHOR_SKIP_DEF_GROUPS


def idle_prefix_frame_count(groups: Sequence[int], counts: Sequence[int] | None) -> int:
    sequence = tuple(int(group) for group in groups)
    if not sequence or sequence[0] != IDLE_DEF_GROUP or counts is None:
        return 0
    values = (int(counts),) if isinstance(counts, int) else tuple(int(value) for value in counts)
    if not values:
        return 0
    return int(values[0])


def idle_suffix_frame_count(groups: Sequence[int], counts: Sequence[int] | None) -> int:
    sequence = tuple(int(group) for group in groups)
    if (
        len(sequence) < 3
        or sequence[0] != IDLE_DEF_GROUP
        or sequence[-1] != IDLE_DEF_GROUP
        or counts is None
    ):
        return 0
    values = (int(counts),) if isinstance(counts, int) else tuple(int(value) for value in counts)
    if len(values) != len(sequence):
        return 0
    return int(values[-1])


def cluster_bone_angles(angles, *, atol: float = 1e-5):
    """Group equal rotation vectors. Returns assignment (F,) and unique (K, 3)."""
    array = np.asarray(angles, dtype=np.float64)
    if array.ndim != 2 or int(array.shape[-1]) != 3:
        raise ValueError("bone angles must have shape (frames, 3)")
    if int(array.shape[0]) < 1:
        raise ValueError("bone angles must contain at least one frame")
    unique: list[np.ndarray] = []
    assignment = np.zeros(int(array.shape[0]), dtype=np.int64)
    for index, row in enumerate(array):
        found = None
        for cluster_index, representative in enumerate(unique):
            if np.allclose(row, representative, atol=float(atol), rtol=0.0):
                found = cluster_index
                break
        if found is None:
            found = len(unique)
            unique.append(np.asarray(row, dtype=np.float64).copy())
        assignment[index] = found
    return assignment, np.stack(unique, axis=0)


def sequential_cluster_adopt(
    assignment,
    cluster_abs,
    *,
    tie_bonus: float,
    reverse: bool,
):
    """Copy a neighbor cluster onto this frame when sprite keep allows.

    Sequential: frame i sees the already-updated neighbor, so a pose can
    travel the whole clip. Parallel one-hop copy from a frozen snapshot
    cannot. ``cluster_abs[k, i]`` is frame i's absolute sprite score with
    this bone at unique angle k. Keep is the same rule as
    ``neighbor_copy_keep``: adopt when copy_abs - current_abs + bonus > 0.
    """
    labels = np.asarray(assignment, dtype=np.int64).reshape(-1)
    scores = np.asarray(cluster_abs, dtype=np.float64)
    if scores.ndim != 2:
        raise ValueError("cluster_abs must have shape (clusters, frames)")
    cluster_count, frame_count = (int(scores.shape[0]), int(scores.shape[1]))
    if int(labels.shape[0]) != frame_count:
        raise ValueError("assignment length must match cluster_abs frames")
    if cluster_count < 1:
        raise ValueError("cluster_abs must contain at least one cluster")
    if int(labels.min()) < 0 or int(labels.max()) >= cluster_count:
        raise ValueError("assignment cluster is outside cluster_abs")
    if not math.isfinite(float(tie_bonus)) or float(tie_bonus) <= 0.0:
        raise ValueError("tie_bonus must be finite and positive")
    if frame_count < 2:
        return labels.copy(), 0
    out = labels.copy()
    order = range(frame_count - 2, -1, -1) if reverse else range(1, frame_count)
    neighbor_delta = 1 if reverse else -1
    moved = 0
    for index in order:
        source = int(out[index + neighbor_delta])
        current = int(out[index])
        if source == current:
            continue
        copy_abs = float(scores[source, index])
        current_abs = float(scores[current, index])
        if not math.isfinite(copy_abs) or not math.isfinite(current_abs):
            raise ValueError("non-finite consensus score")
        if (copy_abs - current_abs) + float(tie_bonus) > 0.0:
            out[index] = source
            moved += 1
    return out, moved


def seed_end_cluster(
    assignment,
    cluster_abs,
    *,
    end_cluster: int,
    tie_bonus: float,
    suffix_frames: int = 0,
):
    """Offer the locked idle pose to the trailing frames of one reverse seed.

    This does not read the forward pass. ``suffix_frames`` is the trailing
    idle block when the sequence ends on rest; 0 still seeds the last frame.
    """
    labels = np.asarray(assignment, dtype=np.int64).reshape(-1).copy()
    scores = np.asarray(cluster_abs, dtype=np.float64)
    if scores.ndim != 2:
        raise ValueError("cluster_abs must have shape (clusters, frames)")
    cluster_index = int(end_cluster)
    if cluster_index < 0 or cluster_index >= int(scores.shape[0]):
        raise ValueError("end_cluster is outside cluster_abs")
    if int(labels.shape[0]) != int(scores.shape[1]):
        raise ValueError("assignment length must match cluster_abs frames")
    if not math.isfinite(float(tie_bonus)) or float(tie_bonus) <= 0.0:
        raise ValueError("tie_bonus must be finite and positive")
    frame_count = int(labels.shape[0])
    width = int(suffix_frames)
    if width < 1:
        width = 1
    if width > frame_count:
        width = frame_count
    moved = 0
    for index in range(frame_count - width, frame_count):
        current = int(labels[index])
        if current == cluster_index:
            continue
        copy_abs = float(scores[cluster_index, index])
        current_abs = float(scores[current, index])
        if not math.isfinite(copy_abs) or not math.isfinite(current_abs):
            raise ValueError("non-finite consensus score")
        if (copy_abs - current_abs) + float(tie_bonus) > 0.0:
            labels[index] = cluster_index
            moved += 1
    return labels, moved


def pick_temporal_pose_pass(original_abs, forward_abs, reverse_abs):
    """Choose original, forward, or reverse for each frame as a whole pose.

    Scores are full-skeleton sprite matches. A local joint angle is not a
    world direction: if root or a parent differs, the same numbers point
    different ways, so bones must not be mixed across passes.
    """
    orig = np.asarray(original_abs, dtype=np.float64).reshape(-1)
    fwd = np.asarray(forward_abs, dtype=np.float64).reshape(-1)
    rev = np.asarray(reverse_abs, dtype=np.float64).reshape(-1)
    if not (orig.shape == fwd.shape == rev.shape):
        raise ValueError("original, forward, and reverse scores must match length")
    choice = np.zeros(int(orig.shape[0]), dtype=np.int64)
    n_rev_pick = 0
    for index in range(int(orig.shape[0])):
        orig_abs = float(orig[index])
        fwd_abs = float(fwd[index])
        rev_abs = float(rev[index])
        if not math.isfinite(orig_abs) or not math.isfinite(fwd_abs) or not math.isfinite(rev_abs):
            raise ValueError("non-finite consensus score")
        best = max(orig_abs, fwd_abs, rev_abs)
        if orig_abs == best:
            choice[index] = 0
            continue
        if rev_abs == best:
            choice[index] = 2
            n_rev_pick += 1
            continue
        choice[index] = 1
    return choice, n_rev_pick


def independent_cluster_walks(
    assignment,
    cluster_abs,
    *,
    tie_bonus: float,
    end_cluster: int | None = None,
    suffix_frames: int = 0,
):
    """Independent 0→N and N→0 walks. Reverse never reads the forward labels.

    ``end_cluster`` is the locked idle pose seeded onto the reverse walk's
    trailing frames only. Sprite keep still refuses frames that do not match.
    """
    base = np.asarray(assignment, dtype=np.int64).reshape(-1)
    forward, n_forward = sequential_cluster_adopt(
        base, cluster_abs, tie_bonus=tie_bonus, reverse=False
    )
    rev_start = base.copy()
    n_end = 0
    if end_cluster is not None:
        rev_start, n_end = seed_end_cluster(
            base,
            cluster_abs,
            end_cluster=end_cluster,
            tie_bonus=tie_bonus,
            suffix_frames=suffix_frames,
        )
    reverse, n_reverse = sequential_cluster_adopt(
        rev_start, cluster_abs, tie_bonus=tie_bonus, reverse=True
    )
    return forward, reverse, n_forward, n_reverse, n_end


def bidirectional_cluster_adopt(
    assignment,
    cluster_abs,
    *,
    tie_bonus: float,
    end_cluster: int | None = None,
    suffix_frames: int = 0,
):
    """Independent walks only. Whole-pose pick happens after all bones.

    Kept as a wrapper so older tests can still call one name. It does not
    mix per-bone labels by sprite score; that mix is wrong when parent
    rotation differs between the passes.
    """
    return independent_cluster_walks(
        assignment,
        cluster_abs,
        tie_bonus=tie_bonus,
        end_cluster=end_cluster,
        suffix_frames=suffix_frames,
    )


def apply_cluster_raw_bone(raw, *, bone_index: int, unique_raw, assignment):
    """Write each frame's bone raw row from ``unique_raw[assignment[i]]``."""
    import torch

    joint = int(bone_index)
    labels = np.asarray(assignment, dtype=np.int64).reshape(-1)
    rows = np.asarray(unique_raw, dtype=np.float64)
    if rows.ndim != 2 or int(rows.shape[-1]) != 3:
        raise ValueError("unique_raw must have shape (clusters, 3)")
    if int(raw.shape[0]) != int(labels.shape[0]):
        raise ValueError("assignment length must match raw frames")
    if joint < 0 or joint >= int(raw.shape[1]):
        raise ValueError(f"bone_index {joint} is outside 0..{int(raw.shape[1]) - 1}")
    if int(labels.min()) < 0 or int(labels.max()) >= int(rows.shape[0]):
        raise ValueError("assignment cluster is outside unique_raw")
    out = raw.detach().clone()
    unique_t = torch.as_tensor(rows, dtype=raw.dtype, device=raw.device)
    labels_t = torch.as_tensor(labels, dtype=torch.int64, device=raw.device)
    out[:, joint, :] = unique_t[labels_t]
    return out


def offset_raw_bone_direction(
    raw,
    *,
    bone_index: int,
    direction: Sequence[float],
    delta_rad,
    joint_limit_rad: float,
    bone_limit_scales,
):
    """Add ``delta_rad`` along a unit rotation-vector direction, then invert tanh.

    ``delta_rad`` is one nonzero angle for every frame, or a length-F tensor.
    """
    import torch

    axis = [float(part) for part in direction]
    if len(axis) != 3:
        raise ValueError("direction must have 3 components")
    norm = math.sqrt(sum(part * part for part in axis))
    if norm <= 1e-12:
        raise ValueError("direction must be a nonzero vector")
    unit = torch.as_tensor(
        [part / norm for part in axis],
        dtype=raw.dtype,
        device=raw.device,
    )
    scales = bone_limit_scales.to(device=raw.device, dtype=raw.dtype).reshape(-1)
    joint = int(bone_index)
    if joint < 0 or joint >= int(scales.numel()):
        raise ValueError(f"bone_index {joint} is outside 0..{int(scales.numel()) - 1}")
    limit = float(joint_limit_rad) * float(scales[joint].detach().item())
    if limit <= 1e-12:
        raise ValueError(f"bone {joint} has a zero joint limit")
    frame_count = int(raw.shape[0])
    if isinstance(delta_rad, torch.Tensor):
        delta = delta_rad.detach().to(device=raw.device, dtype=raw.dtype).reshape(-1)
        if int(delta.numel()) != frame_count:
            raise ValueError(
                "delta_rad tensor must have one angle per frame: "
                f"got {int(delta.numel())} for {frame_count} frames"
            )
        if not bool(torch.isfinite(delta).all()):
            raise ValueError("delta_rad must be finite")
        if bool((delta == 0).any()):
            raise ValueError("delta_rad must be nonzero on every frame")
        delta = delta.view(-1, 1)
    else:
        if not math.isfinite(float(delta_rad)) or float(delta_rad) == 0.0:
            raise ValueError("delta_rad must be a nonzero finite angle")
        delta = float(delta_rad)
    bounded = torch.tanh(raw) * float(joint_limit_rad) * scales.view(1, -1, 1)
    new_angles = (bounded[:, joint, :] + delta * unit.view(1, 3)).clamp(-limit, limit)
    ratio = (new_angles / limit).clamp(-0.999, 0.999)
    out = raw.detach().clone()
    out[:, joint, :] = torch.atanh(ratio)
    return out


def gradient_ladder_directions(
    grad,
    bone_indices,
    *,
    min_gradient_norm: float,
):
    """Per-frame unit directions from an all-bone bounded-angle gradient.

    ``grad`` is d(absolute sprite match)/d(bone angle) with shape
    (frames, bones, 3). Only ``bone_indices`` may move. Each frame's
    direction is normalized over its (bones, axes) block, so a ladder step
    of N degrees moves the whole pose by N degrees of root-sum-square
    rotation along the coupled gradient. Frames whose masked gradient norm
    is below ``min_gradient_norm`` get a zero direction; their ladder
    candidates then equal the current pose and cannot win the keep.
    """
    import torch

    if not math.isfinite(float(min_gradient_norm)) or float(min_gradient_norm) <= 0.0:
        raise ValueError("min_gradient_norm must be finite and positive")
    if int(grad.dim()) != 3 or int(grad.shape[2]) != 3:
        raise ValueError("grad must have shape (frames, bones, 3)")
    indices = [int(index) for index in bone_indices]
    if not indices:
        raise ValueError("gradient ladder requires at least one bone")
    masked = torch.zeros_like(grad)
    masked[:, indices, :] = grad[:, indices, :]
    norms = masked.reshape(int(grad.shape[0]), -1).norm(dim=1)
    active = norms > float(min_gradient_norm)
    safe_norms = torch.where(active, norms, torch.ones_like(norms))
    directions = masked / safe_norms.view(-1, 1, 1)
    return torch.where(active.view(-1, 1, 1), directions, torch.zeros_like(directions)), norms


def offset_raw_bounded_direction(
    raw,
    deltas,
    *,
    joint_limit_rad: float,
    bone_limit_scales,
):
    """Add per-frame bounded-space deltas on every bone, then invert tanh.

    ``deltas`` has shape (frames, bones, 3) in radians of bounded rotation.
    """
    import torch

    if not math.isfinite(float(joint_limit_rad)) or float(joint_limit_rad) <= 0.0:
        raise ValueError("joint_limit_rad must be finite and positive")
    if tuple(deltas.shape) != tuple(raw.shape):
        raise ValueError(
            f"deltas shape {tuple(deltas.shape)} does not match raw shape {tuple(raw.shape)}"
        )
    scales = bone_limit_scales.to(device=raw.device, dtype=raw.dtype).reshape(-1)
    limit = float(joint_limit_rad) * scales.view(1, -1, 1)
    if not bool((limit > 1e-12).all()):
        raise ValueError("every bone needs a positive joint limit for a bounded offset")
    bounded = torch.tanh(raw) * limit
    new_angles = torch.maximum(torch.minimum(bounded + deltas, limit), -limit)
    ratio = (new_angles / limit).clamp(-0.999, 0.999)
    return torch.atanh(ratio)


def commit_pose_parameter_(parameter, value):
    """Write a discrete winner into a pose Parameter while autograd is on.

    ``torch.nn.Parameter`` is a leaf with ``requires_grad=True``. An in-place
    ``copy_`` on that leaf raises ``RuntimeError`` whenever grad mode is
    enabled, which is the default inside ``optimize_clip``. Joint stages
    avoid this by wrapping their whole walk in ``torch.no_grad``; the
    ladder cannot, because it needs one backward pass first. This helper
    is the same write the other stages already do, scoped to the copy.
    """
    import torch

    if tuple(parameter.shape) != tuple(value.shape):
        raise ValueError(
            f"pose write shape {tuple(value.shape)} does not match "
            f"parameter shape {tuple(parameter.shape)}"
        )
    with torch.no_grad():
        parameter.copy_(value.detach())


def sa_temperature(iteration: int, total_iterations: int, t_start: float, t_end: float) -> float:
    """Geometric cooling schedule for simulated annealing.

    Returns ``t_start`` at iteration 0 and ``t_end`` at the final iteration.
    """
    if int(total_iterations) < 1:
        raise ValueError("total_iterations must be at least 1")
    if not math.isfinite(float(t_start)) or float(t_start) <= 0.0:
        raise ValueError("t_start must be finite and positive")
    if not math.isfinite(float(t_end)) or float(t_end) <= 0.0:
        raise ValueError("t_end must be finite and positive")
    if float(t_end) >= float(t_start):
        raise ValueError("t_end must be less than t_start")
    if int(total_iterations) == 1:
        return float(t_start)
    fraction = int(iteration) / (int(total_iterations) - 1)
    return float(t_start) * (float(t_end) / float(t_start)) ** fraction


def sa_random_initial_pose(
    frame_count: int,
    node_count: int,
    search_node_indices,
    joint_limit_rad: float,
    bone_limit_scales,
    device,
    generator,
):
    """Random pose in raw (arctanh-bounded) space, within ±80% of joint limits.

    Only ``search_node_indices`` bones are randomized; all others stay at zero
    (bind). The 0.8 factor avoids extreme contortions that are clearly wrong.
    """
    import torch

    if int(frame_count) < 1 or int(node_count) < 1:
        raise ValueError("frame_count and node_count must be positive")
    if not math.isfinite(float(joint_limit_rad)) or float(joint_limit_rad) <= 0.0:
        raise ValueError("joint_limit_rad must be finite and positive")
    scales = bone_limit_scales.to(device=device, dtype=torch.float32).reshape(-1)
    if int(scales.numel()) != int(node_count):
        raise ValueError(
            f"bone_limit_scales has {int(scales.numel())} entries, expected {int(node_count)}"
        )
    limits = float(joint_limit_rad) * scales.view(1, -1, 1)
    bounded = (torch.rand(int(frame_count), int(node_count), 3, device=device, generator=generator) * 2.0 - 1.0) * limits * 0.8
    search_mask = torch.zeros(int(node_count), device=device)
    search_mask[list(int(index) for index in search_node_indices)] = 1.0
    bounded = bounded * search_mask.view(1, -1, 1)
    ratio = (bounded / limits).clamp(-0.999, 0.999)
    return torch.atanh(ratio)


def sa_perturb_pose(
    current_raw,
    normalized_temperature: float,
    bone_fraction: float,
    max_angle_deg: float,
    search_node_indices,
    joint_limit_rad: float,
    bone_limit_scales,
    generator,
):
    """Random perturbation scaled by temperature, applied via bounded-space offset.

    At ``normalized_temperature=1.0`` (start), perturbs ``bone_fraction`` of
    search bones by up to ``max_angle_deg``. At ``normalized_temperature≈0``
    (end), perturbs one bone by a tiny amount. Returns a new raw tensor.
    """
    import torch

    if not math.isfinite(float(normalized_temperature)) or float(normalized_temperature) < 0.0:
        raise ValueError("normalized_temperature must be finite and non-negative")
    if not math.isfinite(float(bone_fraction)) or not 0.0 < float(bone_fraction) <= 1.0:
        raise ValueError("bone_fraction must be in (0, 1]")
    if not math.isfinite(float(max_angle_deg)) or float(max_angle_deg) <= 0.0:
        raise ValueError("max_angle_deg must be finite and positive")
    if not math.isfinite(float(joint_limit_rad)) or float(joint_limit_rad) <= 0.0:
        raise ValueError("joint_limit_rad must be finite and positive")
    frame_count, node_count, axis_count = current_raw.shape
    if axis_count != 3:
        raise ValueError("current_raw must have shape (frames, nodes, 3)")
    device = current_raw.device
    search_list = [int(index) for index in search_node_indices]
    if not search_list:
        raise ValueError("sa_perturb_pose requires at least one search bone")
    norm_t = float(normalized_temperature)
    bones_to_move = max(1, int(round(len(search_list) * float(bone_fraction) * norm_t)))
    max_angle_rad = math.radians(float(max_angle_deg)) * norm_t

    # Random subset of search bones, same subset across all frames.
    perm = torch.randperm(len(search_list), generator=generator, device=device)[:bones_to_move]
    selected = [search_list[int(i)] for i in perm]

    # Random axis (Gaussian on sphere) and angle per frame per selected bone.
    random_vec = torch.randn(frame_count, bones_to_move, 3, device=device, generator=generator)
    random_axis = random_vec / random_vec.norm(dim=-1, keepdim=True).clamp_min(1e-12)
    random_angle = (torch.rand(frame_count, bones_to_move, 1, device=device, generator=generator) * 2.0 - 1.0) * max_angle_rad

    deltas = torch.zeros_like(current_raw)
    for slot, bone_index in enumerate(selected):
        deltas[:, bone_index, :] = random_axis[:, slot, :] * random_angle[:, slot, :]

    return offset_raw_bounded_direction(
        current_raw,
        deltas,
        joint_limit_rad=joint_limit_rad,
        bone_limit_scales=bone_limit_scales,
    )


def sa_metropolis_accept(current_scores, proposed_scores, temperature: float, generator):
    """Per-frame Metropolis acceptance mask.

    Always accepts improvement (proposed > current). Accepts worsening moves
    with probability ``exp(delta / T)``. Returns a boolean tensor of the same
    shape as the score vectors.
    """
    import torch

    if not math.isfinite(float(temperature)) or float(temperature) <= 0.0:
        raise ValueError("temperature must be finite and positive")
    if tuple(current_scores.shape) != tuple(proposed_scores.shape):
        raise ValueError(
            f"score shape mismatch: current={tuple(current_scores.shape)} "
            f"proposed={tuple(proposed_scores.shape)}"
        )
    delta = proposed_scores - current_scores
    accept_prob = torch.where(
        delta > 0.0,
        torch.ones_like(delta),
        torch.exp(delta / float(temperature)),
    )
    return torch.rand_like(accept_prob, generator=generator) < accept_prob


def load_ik_keypoints(path: str | Path) -> dict[int, dict[str, tuple[float, float]]]:
    """Load LLM-authored stick figures from keypoints.json.

    Returns a mapping from frame index to a dict of joint name → (x, y)
    pixel coordinates in the source image space.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("method") not in {"human_eye_landmark_authoring", "silhouette_miss_pairing"}:
        raise ValueError(
            "keypoints method must be human_eye_landmark_authoring or silhouette_miss_pairing, "
            f"got {data.get('method')!r}"
        )
    frames: dict[int, dict[str, tuple[float, float]]] = {}
    for frame in data.get("frames", []):
        frame_index = int(frame["frameIndex"])
        joints: dict[str, tuple[float, float]] = {}
        for name, entry in frame.get("joints", {}).items():
            if not entry.get("visible", False):
                continue
            joints[str(name)] = (float(entry["x"]), float(entry["y"]))
        frames[frame_index] = joints
    return frames


def load_ik_bone_roles(path: str | Path) -> dict[str, str]:
    """Load bone roles mapping from stick joint names to skeleton bone names."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    joints = data.get("joints", {})
    if not joints:
        raise ValueError(f"bone roles file has no joints mapping: {path}")
    return {str(k): str(v) for k, v in joints.items()}


def ik_unproject_2d_to_3d(
    x: float,
    y: float,
    depth: float,
    camera_right,
    camera_down,
    camera_forward,
    camera_offset,
    camera_px_per_world,
):
    """Unproject a 2D screen point to 3D using the orthographic camera basis.

    The cascade camera is orthographic: screen_x = dot(p, right) * px + offset,
    screen_y = dot(p, down) * py + offset_y. Inverting gives the in-plane
    components; the depth along the forward axis comes from the sprite's
    depth map.
    """
    import torch

    right = torch.as_tensor(camera_right, dtype=torch.float32)
    down = torch.as_tensor(camera_down, dtype=torch.float32)
    forward = torch.as_tensor(camera_forward, dtype=torch.float32)
    offset = torch.as_tensor(camera_offset, dtype=torch.float32)
    px = torch.as_tensor(camera_px_per_world, dtype=torch.float32)

    in_plane_x = (float(x) - float(offset[0])) / float(px[0])
    in_plane_y = (float(y) - float(offset[1])) / float(px[1])
    return in_plane_x * right + in_plane_y * down + float(depth) * forward


_IK_AUTHORED_STEM_BY_GROUP = {
    0: "g00_move",
    1: "g01_mouseover",
    2: "g02_idle",
    3: "g03_hitted",
    4: "g04_defence",
    5: "g05_death",
    7: "g07_turn_left",
    8: "g08_turn_right",
    9: "g09_unused_a",
    10: "g10_unused_b",
    11: "g11_attack_up",
    12: "idle_attack_front",
    13: "g13_attack_down",
    20: "g20_move_start",
    21: "g21_move_end",
}
_IK_ANIMATION_ALIASES = {
    "move": "g00_move",
    "move_g0": "g00_move",
    "start": "g20_move_start",
    "move_start": "g20_move_start",
    "end": "g21_move_end",
    "move_end": "g21_move_end",
    "idle": "g02_idle",
}


def _normalize_int_sequence(value) -> tuple[int, ...] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        raise TypeError("DEF group/count value must be an int or a sequence of ints")
    if isinstance(value, Sequence):
        return tuple(int(item) for item in value)
    return (int(value),)


def _ik_authored_keypoints_candidates(root: Path, unit: str, stem: str) -> tuple[Path, ...]:
    fit = Path(root) / "artifacts" / f"{unit}_pose_pipeline" / "out_fit"
    return (
        fit / f"{stem}_authored" / "sprite_landmarks" / "keypoints.json",
        fit / stem / "sprite_landmarks" / "keypoints.json",
    )


def _first_existing_keypoints(candidates: Sequence[Path]) -> Path | None:
    for path in candidates:
        if path.is_file():
            return path.resolve()
    return None


def _stitch_sequence_ik_keypoints(
    *,
    root: Path,
    unit: str,
    animation: str,
    groups: Sequence[int],
    counts: Sequence[int],
    segment_paths: Sequence[Path],
) -> Path:
    """Concatenate per-DEF authored sticks into sequence frame indices.

    Frame 0 of the second clip becomes the first frame after the first clip,
    matching how idle_start_move concatenates DEF groups.
    """
    if len(groups) != len(counts) or len(groups) != len(segment_paths):
        raise ValueError("IK sequence stitch requires groups, counts, and paths of the same length")
    combined_frames: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    offset = 0
    for group, count, path in zip(groups, counts, segment_paths):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("method") != "human_eye_landmark_authoring":
            raise ValueError(
                f"IK sequence stitch refuses non-authored keypoints {path} "
                f"(method={payload.get('method')!r})"
            )
        frames = list(payload.get("frames") or [])
        frames.sort(key=lambda frame: int(frame.get("frameIndex", -1)))
        if len(frames) != int(count):
            raise ValueError(
                f"IK sequence stitch expected {count} authored frames for DEF group {group} "
                f"in {path}, found {len(frames)}"
            )
        for local_index, frame in enumerate(frames):
            if int(frame.get("frameIndex", local_index)) != local_index:
                raise ValueError(
                    f"IK sequence stitch requires dense 0..n-1 frameIndex in {path}; "
                    f"frame {local_index} has frameIndex={frame.get('frameIndex')!r}"
                )
            copied = copy.deepcopy(frame)
            copied["frameIndex"] = offset + local_index
            combined_frames.append(copied)
        sources.append({"group": int(group), "path": str(Path(path).resolve()), "frameCount": int(count)})
        offset += int(count)
    out = (
        Path(root) / "artifacts" / f"{unit}_pose_pipeline" / "out_fit"
        / "_cascade_ik_stitched" / f"{animation}_keypoints.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "ok": True,
                "method": "human_eye_landmark_authoring",
                "clipId": animation,
                "unitSid": f"h3_{unit}",
                "stitchedFrom": sources,
                "proof": (
                    "concatenated LLM-authored per-DEF sticks to sequence frame indices; "
                    "not a substitute for missing idle authorship"
                ),
                "frames": combined_frames,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return out.resolve()


def _resolve_local_ik_keypoints_path(
    *,
    root: Path,
    unit: str,
    animation: str,
    def_lab_groups: Sequence[int] | int | None = None,
    def_expected_counts: Sequence[int] | int | None = None,
) -> Path | None:
    groups = _normalize_int_sequence(def_lab_groups)
    counts = _normalize_int_sequence(def_expected_counts)
    stems: list[str] = []
    if groups:
        stems = [_IK_AUTHORED_STEM_BY_GROUP.get(int(group), f"g{int(group):02d}") for group in groups]
        if counts is not None and len(counts) != len(groups):
            raise ValueError("def_expected_counts must match def_lab_groups")
        if len(groups) > 1:
            if counts is None:
                raise ValueError(
                    "IK sequence auto-detect requires def_expected_counts so concatenated "
                    "DEF groups can be mapped onto sequence frame indices"
                )
            found: list[Path | None] = []
            missing: list[str] = []
            for group, stem in zip(groups, stems):
                path = _first_existing_keypoints(_ik_authored_keypoints_candidates(root, unit, stem))
                found.append(path)
                if path is None:
                    missing.append(
                        f"DEF g{int(group):02d} ({stem}): "
                        + ", ".join(str(candidate) for candidate in _ik_authored_keypoints_candidates(root, unit, stem))
                    )
            if missing:
                return None
            return _stitch_sequence_ik_keypoints(
                root=Path(root),
                unit=unit,
                animation=animation,
                groups=groups,
                counts=counts,
                segment_paths=[path for path in found if path is not None],
            )
    alias = _IK_ANIMATION_ALIASES.get(animation, animation)
    candidate_stems = []
    for stem in (animation, alias, *stems):
        if stem and stem not in candidate_stems:
            candidate_stems.append(stem)
    candidates: list[Path] = []
    for stem in candidate_stems:
        candidates.extend(_ik_authored_keypoints_candidates(root, unit, stem))
    return _first_existing_keypoints(candidates)


def _default_smartrig_glb(lab_sid: str, root: Path) -> Path | None:
    from upgrade_line_keypoints import default_smartrig_glb

    return default_smartrig_glb(lab_sid, root)


def resolve_ik_keypoints_path(
    *,
    root: Path,
    unit_name: str,
    animation_name: str,
    explicit: str | Path | None,
    def_lab_groups: Sequence[int] | int | None = None,
    def_expected_counts: Sequence[int] | int | None = None,
    src_glb: str | Path | None = None,
    lab_sid: str | None = None,
) -> Path:
    """Resolve authored stick figures. Explicit path wins; otherwise the clip's authored keypoints."""
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = Path(root) / path
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"IK keypoints file is missing: {path}")
        return path
    unit = str(unit_name or "").strip()
    animation = str(animation_name or "").strip()
    if not unit or not animation:
        raise ValueError(
            "IK keypoints auto-detect requires unit_name and animation_name; "
            "set CASCADE_IK_KEYPOINTS_PATH to the authored sprite_landmarks/keypoints.json"
        )
    groups = _normalize_int_sequence(def_lab_groups)
    counts = _normalize_int_sequence(def_expected_counts)
    if groups and len(groups) > 1 and counts is None:
        raise ValueError(
            "IK sequence auto-detect requires def_expected_counts so concatenated "
            "DEF groups can be mapped onto sequence frame indices"
        )
    local = _resolve_local_ik_keypoints_path(
        root=Path(root),
        unit=unit,
        animation=animation,
        def_lab_groups=def_lab_groups,
        def_expected_counts=def_expected_counts,
    )
    if local is not None:
        return local
    if src_glb is not None:
        from upgrade_line_keypoints import (
            lab_sid_family_peers,
            lab_sid_from_unit_name,
            skeleton_signatures_match,
            unit_name_from_lab_sid,
            write_borrowed_keypoints,
        )

        target_glb = Path(src_glb).resolve()
        target_sid = str(lab_sid or lab_sid_from_unit_name(unit))
        for peer_sid in lab_sid_family_peers(target_sid):
            if peer_sid == target_sid:
                continue
            peer_unit = unit_name_from_lab_sid(peer_sid)
            donor_path = _resolve_local_ik_keypoints_path(
                root=Path(root),
                unit=peer_unit,
                animation=animation,
                def_lab_groups=def_lab_groups,
                def_expected_counts=def_expected_counts,
            )
            if donor_path is None:
                continue
            donor_glb = _default_smartrig_glb(peer_sid, Path(root))
            if donor_glb is None or not skeleton_signatures_match(donor_glb, target_glb):
                continue
            borrowed = write_borrowed_keypoints(
                root=Path(root),
                unit=unit,
                animation=animation,
                donor_path=donor_path,
                donor_lab_sid=peer_sid,
                target_glb=target_glb,
            )
            print(
                f"IK keypoints upgrade-line borrow: {peer_sid} -> {target_sid} "
                f"animation={animation!r} donor={donor_path}",
                flush=True,
            )
            return borrowed
    stems = [_IK_AUTHORED_STEM_BY_GROUP.get(int(group), f"g{int(group):02d}") for group in groups] if groups else []
    if groups and len(groups) > 1:
        missing = [
            f"DEF g{int(group):02d} ({stem})"
            for group, stem in zip(groups, stems)
        ]
        raise FileNotFoundError(
            f"IK keypoints auto-detect cannot run {animation!r}: it concatenates DEF "
            f"groups {list(groups)} ({'+'.join(stems)}). "
            "Do not point CASCADE_IK_KEYPOINTS_PATH at one child clip while this "
            "sequence is selected — those frame indices would paste the wrong sticks "
            "onto earlier frames. Missing authored segments:\n  "
            + "\n  ".join(missing)
            + "\nTo test cascade IK now, select a single authored clip in the "
            "animation dropdown (walk is g00_move)."
        )
    alias = _IK_ANIMATION_ALIASES.get(animation, animation)
    candidate_stems = []
    for stem in (animation, alias, *stems):
        if stem and stem not in candidate_stems:
            candidate_stems.append(stem)
    candidates: list[Path] = []
    for stem in candidate_stems:
        candidates.extend(_ik_authored_keypoints_candidates(root, unit, stem))
    tried = "\n".join(f"  {path}" for path in candidates)
    raise FileNotFoundError(
        f"IK keypoints auto-detect found no authored sticks for unit={unit!r} "
        f"animation={animation!r}. Set CASCADE_IK_KEYPOINTS_PATH to that clip's "
        f"sprite_landmarks/keypoints.json. Tried:\n{tried}"
    )


def resolve_ik_bone_roles_path(
    *,
    unit_name: str,
    src_glb: Path,
    explicit: str | Path | None,
    tools_dir: Path | None = None,
) -> Path:
    """Resolve joint→bone mapping. Explicit path wins; otherwise match owned vs Meshy roles to the mesh."""
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = (Path(tools_dir) if tools_dir is not None else Path(__file__).resolve().parent) / path
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"IK bone roles file is missing: {path}")
        return path
    unit = str(unit_name or "").strip()
    if not unit:
        raise ValueError(
            "IK bone-roles auto-detect requires unit_name; "
            "set CASCADE_IK_BONE_ROLES_PATH to bone_roles_<unit>_*.json"
        )
    tools = Path(tools_dir) if tools_dir is not None else Path(__file__).resolve().parent
    owned = (tools / f"bone_roles_{unit}_owned.json").resolve()
    meshy = (tools / f"bone_roles_{unit}_meshy_t2.json").resolve()
    smartrig = (tools / f"bone_roles_{unit}_smartrig.json").resolve()
    glb_text = str(Path(src_glb)).replace("\\", "/").lower()
    glb_stem = Path(src_glb).stem.lower()
    preferred: Path | None = None
    if "owned_bind" in glb_text or glb_stem.endswith("_owned") or "_owned_" in glb_stem:
        preferred = owned
    elif "meshy" in glb_text or "smartrig" in glb_text:
        preferred = smartrig if smartrig.is_file() else meshy
    if preferred is not None and preferred.is_file():
        return preferred
    existing = [path for path in (smartrig, owned, meshy) if path.is_file()]
    if len(existing) == 1:
        return existing[0]
    tried = "\n".join(f"  {path}" for path in (owned, meshy))
    raise FileNotFoundError(
        f"IK bone-roles auto-detect could not choose a file for unit={unit!r} "
        f"mesh={src_glb}. Set CASCADE_IK_BONE_ROLES_PATH. Tried:\n{tried}"
    )


def ik_chains_from_bone_roles(
    bone_roles: Mapping[str, str],
    node_index: Mapping[str, int],
    parents: Sequence[int | None],
) -> list[tuple[list[int], str, int]]:
    """Build CCD chains from stick joint → bone mapping and the skeleton parents.

    Last mapping wins when several stick joints share a bone (WeaponTip over RWrist).
    The skeleton root is omitted so IK does not redo root Adam.
    """
    end_to_joint: dict[int, str] = {}
    joint_priority = {
        "WeaponTip": 100,
        "Nose": 90,
        "Head": 90,
        "head": 90,
        "RAnkle": 80,
        "LAnkle": 80,
        "RWrist": 70,
        "LWrist": 70,
    }
    for joint_name, bone_name in bone_roles.items():
        if bone_name not in node_index:
            continue
        end_index = int(node_index[bone_name])
        previous = end_to_joint.get(end_index)
        if previous is not None and int(joint_priority.get(str(joint_name), 0)) < int(joint_priority.get(previous, 0)):
            continue
        end_to_joint[end_index] = str(joint_name)
    chains: list[tuple[list[int], str, int]] = []
    for end_index, joint_name in end_to_joint.items():
        chain: list[int] = []
        current: int | None = int(end_index)
        seen: set[int] = set()
        while current is not None and int(current) >= 0:
            if int(current) in seen:
                raise ValueError(f"parent cycle while building IK chain at node {current}")
            seen.add(int(current))
            chain.append(int(current))
            parent = parents[int(current)]
            current = None if parent is None else int(parent)
            if current is not None and current < 0:
                current = None
        chain.reverse()
        if chain and parents[chain[0]] is None:
            chain = chain[1:]
        if len(chain) < 1:
            continue
        chains.append((chain, joint_name, int(end_index)))
    if not chains:
        raise ValueError("IK bone roles mapped to no skeleton bones; check bone_roles vs the loaded GLB")
    return chains


def ik_chain_to_end_effector(
    end_index: int,
    parents: Sequence[int | None],
) -> list[int]:
    """Build one root-to-end-effector chain from the skeleton parent table."""
    chain: list[int] = []
    current: int | None = int(end_index)
    seen: set[int] = set()
    while current is not None and int(current) >= 0:
        if int(current) in seen:
            raise ValueError(f"parent cycle while building IK chain at node {current}")
        seen.add(int(current))
        chain.append(int(current))
        parent = parents[int(current)]
        current = None if parent is None else int(parent)
    chain.reverse()
    if chain and parents[chain[0]] is None:
        chain = chain[1:]
    if len(chain) < 1:
        raise ValueError(f"IK chain for end effector {end_index} is empty")
    return chain


def _project_world_positions_xy(
    world_positions,
    camera_right,
    camera_down,
    camera_offset,
    px_per_world,
) -> tuple[float, float]:
    import torch

    pos = world_positions
    sx = float(
        torch.matmul(pos, camera_right) * px_per_world[0] + camera_offset[0]
    )
    sy = float(
        torch.matmul(pos, camera_down) * px_per_world[1] + camera_offset[1]
    )
    return sx, sy


def project_search_bones_xy(
    experiment: GpuCascadeExperiment,
    bone_vectors,
    root_translation,
    root_rotation,
    *,
    frame_position: int,
    min_bone_depth: int = 3,
) -> dict[str, tuple[float, float]]:
    """Project cascade search bones to raster pixels, keyed by skeleton bone name."""
    import torch

    bounded = experiment._bounded_bone_vectors(bone_vectors)
    frame_bounded = bounded[frame_position : frame_position + 1]
    world = experiment._forward_kinematics(
        frame_bounded,
        bone_mask=experiment.active_node_mask,
    )[0]
    joint_xy: dict[str, tuple[float, float]] = {}
    for index in experiment.search_node_indices:
        if int(experiment.node_depths[int(index)]) < int(min_bone_depth):
            continue
        name = str(experiment.node_names[int(index)])
        joint_xy[name] = _project_world_positions_xy(
            world[int(index), :3, 3],
            experiment.camera_right,
            experiment.camera_down,
            experiment.camera_offset,
            experiment.px_per_world,
        )
    return joint_xy


def compute_search_bone_influence_in_mask(
    experiment: GpuCascadeExperiment,
    bone_vectors,
    root_translation,
    root_rotation,
    *,
    frame_position: int,
    region_mask: np.ndarray,
    min_bone_depth: int = 3,
) -> dict[str, float]:
    """Accumulate skinning weight for searchable bones under ``region_mask`` pixels."""
    import torch

    region = np.asarray(region_mask, dtype=bool)
    if region.ndim != 2:
        raise ValueError("region_mask must be 2D")
    height, width = region.shape

    bounded = experiment._bounded_bone_vectors(bone_vectors)
    frame_bounded = bounded[frame_position : frame_position + 1]
    frame_root_t = root_translation[frame_position : frame_position + 1]
    frame_root_r = root_rotation[frame_position : frame_position + 1]
    worlds = experiment._forward_kinematics(
        frame_bounded,
        bone_mask=experiment.active_node_mask,
    )

    searchable: dict[int, str] = {
        int(index): str(experiment.node_names[int(index)])
        for index in experiment.search_node_indices
        if int(experiment.node_depths[int(index)]) >= int(min_bone_depth)
    }
    influence = {name: 0.0 for name in searchable.values()}

    with torch.no_grad():
        for primitive in experiment.primitives:
            if (
                primitive.normalized_weights is None
                or primitive.joints is None
                or primitive.skin_joints is None
            ):
                continue
            vertices = experiment._skinned_vertices(worlds, primitive)[0]
            vertices = experiment._root_transform(
                vertices.unsqueeze(0),
                frame_root_t,
                frame_root_r,
            )[0]
            projected = torch.stack(
                (
                    torch.matmul(vertices, experiment.camera_right)
                    * experiment.px_per_world[0]
                    + experiment.camera_offset[0],
                    torch.matmul(vertices, experiment.camera_down)
                    * experiment.px_per_world[1]
                    + experiment.camera_offset[1],
                ),
                dim=-1,
            ).detach().cpu().numpy()
            weights = primitive.normalized_weights.detach().cpu().numpy()
            joint_slots = primitive.joints.detach().cpu().numpy()
            skin_to_node = primitive.skin_joints.detach().cpu().numpy().reshape(-1)
            if joint_slots.ndim != 2 or weights.ndim != 2:
                continue
            if tuple(joint_slots.shape) != tuple(weights.shape):
                continue
            joint_count = int(joint_slots.shape[1])
            for vertex_index in range(int(projected.shape[0])):
                px = int(round(float(projected[vertex_index, 0])))
                py = int(round(float(projected[vertex_index, 1])))
                if not (0 <= px < width and 0 <= py < height):
                    continue
                if not region[py, px]:
                    continue
                for slot in range(joint_count):
                    skin_joint_index = int(joint_slots[vertex_index, slot])
                    if skin_joint_index < 0 or skin_joint_index >= int(skin_to_node.shape[0]):
                        continue
                    bone_index = int(skin_to_node[skin_joint_index])
                    weight = float(weights[vertex_index, slot])
                    if weight <= 0.0:
                        continue
                    name = searchable.get(bone_index)
                    if name is None:
                        continue
                    influence[name] += weight
    return influence


def compute_search_bone_influence_maps(
    experiment: GpuCascadeExperiment,
    bone_vectors,
    root_translation,
    root_rotation,
    *,
    frame_position: int,
    node_indices: Sequence[int],
    height: int,
    width: int,
) -> dict[str, np.ndarray]:
    """Per-pixel accumulated skinning weight for each searchable bone."""
    import torch

    if int(height) < 1 or int(width) < 1:
        raise ValueError("influence maps need a positive raster size")
    nodes = tuple(int(index) for index in node_indices)
    if not nodes:
        raise ValueError("influence maps need at least one bone")
    names = [str(experiment.node_names[int(index)]) for index in nodes]
    maps = {
        name: np.zeros((int(height), int(width)), dtype=np.float64) for name in names
    }
    index_by_name = {
        str(experiment.node_names[int(index)]): int(index) for index in nodes
    }
    searchable = {int(index): str(experiment.node_names[int(index)]) for index in nodes}

    bounded = experiment._bounded_bone_vectors(bone_vectors)
    frame_bounded = bounded[frame_position : frame_position + 1]
    frame_root_t = root_translation[frame_position : frame_position + 1]
    frame_root_r = root_rotation[frame_position : frame_position + 1]
    worlds = experiment._forward_kinematics(
        frame_bounded,
        bone_mask=experiment.active_node_mask,
    )

    with torch.no_grad():
        for primitive in experiment.primitives:
            if (
                primitive.normalized_weights is None
                or primitive.joints is None
                or primitive.skin_joints is None
            ):
                continue
            vertices = experiment._skinned_vertices(worlds, primitive)[0]
            vertices = experiment._root_transform(
                vertices.unsqueeze(0),
                frame_root_t,
                frame_root_r,
            )[0]
            projected = torch.stack(
                (
                    torch.matmul(vertices, experiment.camera_right)
                    * experiment.px_per_world[0]
                    + experiment.camera_offset[0],
                    torch.matmul(vertices, experiment.camera_down)
                    * experiment.px_per_world[1]
                    + experiment.camera_offset[1],
                ),
                dim=-1,
            ).detach().cpu().numpy()
            weights = primitive.normalized_weights.detach().cpu().numpy()
            joint_slots = primitive.joints.detach().cpu().numpy()
            skin_to_node = primitive.skin_joints.detach().cpu().numpy().reshape(-1)
            if joint_slots.ndim != 2 or weights.ndim != 2:
                continue
            if tuple(joint_slots.shape) != tuple(weights.shape):
                continue
            joint_count = int(joint_slots.shape[1])
            for vertex_index in range(int(projected.shape[0])):
                px = int(round(float(projected[vertex_index, 0])))
                py = int(round(float(projected[vertex_index, 1])))
                if not (0 <= px < int(width) and 0 <= py < int(height)):
                    continue
                for slot in range(joint_count):
                    skin_joint_index = int(joint_slots[vertex_index, slot])
                    if skin_joint_index < 0 or skin_joint_index >= int(skin_to_node.shape[0]):
                        continue
                    bone_index = int(skin_to_node[skin_joint_index])
                    weight = float(weights[vertex_index, slot])
                    if weight <= 0.0:
                        continue
                    name = searchable.get(bone_index)
                    if name is None:
                        continue
                    maps[name][py, px] += weight
    del index_by_name
    return maps


@dataclass(frozen=True)
class IncrementalBlobJob:
    """One excess blob assigned to a bone, with the local repair neighborhood."""

    frame_position: int
    frame_index: int
    bone_name: str
    bone_index: int
    excess_mask: np.ndarray
    missing_mask: np.ndarray
    repair_region: np.ndarray
    excess_area: int
    missing_area: int
    target_tip: tuple[float, float]
    excess_tip: tuple[float, float] = (0.0, 0.0)
    tip_displacement_px: float = 0.0
    priority_score: float = 0.0


def derive_ik_blob_jobs(
    experiment: GpuCascadeExperiment,
    bone_vectors,
    root_translation,
    root_rotation,
    *,
    frame_positions: Sequence[int] | None = None,
) -> dict[int, list[IncrementalBlobJob]]:
    """Pair red excess blobs with blue missing blobs and attribute a distal bone."""
    from gpu_depth_silhouette_solver import label_binary_components, missing_target_silhouette
    from ik_incremental_blob import repair_region_from_blobs
    from ik_silhouette_miss_keypoints import (
        assign_joint_by_influence,
        excess_predicted_silhouette,
        nearest_joint_name,
        pair_silhouette_misses,
    )

    config = experiment.config
    min_bone_depth = int(config.ik_proximal_min_depth)
    threshold = float(config.ik_miss_predicted_alpha_threshold)
    jobs_by_position: dict[int, list[IncrementalBlobJob]] = {}
    bounded = experiment._bounded_bone_vectors(bone_vectors)
    frame_count = len(experiment.frame_indices)
    if frame_positions is None:
        selected_positions = tuple(range(frame_count))
    else:
        selected_positions = tuple(int(index) for index in frame_positions)
        invalid = [index for index in selected_positions if index < 0 or index >= frame_count]
        if invalid:
            raise ValueError(
                f"frame_positions contains indices outside 0..{frame_count - 1}: {invalid}"
            )
    for frame_position in selected_positions:
        frame_index = experiment.frame_indices[int(frame_position)]
        frame_bounded = bounded[frame_position : frame_position + 1]
        frame_root_t = root_translation[frame_position : frame_position + 1]
        frame_root_r = root_rotation[frame_position : frame_position + 1]
        predicted, predicted_depth = experiment._exact_triangle_raster(
            frame_bounded,
            frame_root_t,
            frame_root_r,
            bone_mask=experiment.active_node_mask,
        )
        if experiment.target_depth is None:
            raise RuntimeError("silhouette_miss IK requires target depth maps")
        target_mask = experiment.target_masks[frame_position].detach().cpu().numpy()
        predicted_mask = predicted[0].detach().cpu().numpy()
        target_depth = experiment.target_depth[frame_position].detach().cpu().numpy()
        pred_depth = predicted_depth[0].detach().cpu().numpy()
        joint_xy = project_search_bones_xy(
            experiment,
            bone_vectors,
            root_translation,
            root_rotation,
            frame_position=frame_position,
            min_bone_depth=min_bone_depth,
        )
        if not joint_xy:
            raise RuntimeError(
                "silhouette_miss IK found no searchable distal bones to project; "
                "check search_node_indices and ik_proximal_min_depth"
            )
        excess = excess_predicted_silhouette(
            target_mask,
            predicted_mask,
            threshold=threshold,
        )
        missing = missing_target_silhouette(
            target_mask,
            predicted_mask,
            threshold=threshold,
        )
        excess_labels, _excess_count = label_binary_components(excess)
        missing_labels, _missing_count = label_binary_components(missing)
        primary_joints = tuple(joint_xy)
        pairs = pair_silhouette_misses(
            target_mask,
            predicted_mask,
            target_depth,
            pred_depth,
            predicted_alpha_threshold=threshold,
            depth_tolerance=float(config.ik_miss_depth_tolerance),
            min_component_area=int(config.ik_miss_min_component_area),
            max_pairs=int(config.ik_miss_max_pairs),
            max_tip_distance_px=float(config.ik_miss_max_tip_distance_px),
            max_centroid_distance_px=float(config.ik_miss_max_centroid_distance_px),
            max_area_ratio=float(config.ik_miss_max_area_ratio),
            min_displacement_alignment=float(config.ik_miss_min_displacement_alignment),
        )
        frame_jobs: list[IncrementalBlobJob] = []
        used_bones: set[str] = set()
        for pair in pairs:
            excess_mask = excess_labels == int(pair.excess_label_id)
            missing_mask = missing_labels == int(pair.missing_label_id)
            influence = compute_search_bone_influence_in_mask(
                experiment,
                bone_vectors,
                root_translation,
                root_rotation,
                frame_position=frame_position,
                region_mask=excess_mask,
                min_bone_depth=min_bone_depth,
            )
            bone_name = assign_joint_by_influence(
                influence,
                allowed=primary_joints,
                node_depth=lambda name: int(
                    experiment.node_depths[int(experiment.node_index[str(name)])]
                ),
            )
            if bone_name is None:
                bone_name = nearest_joint_name(
                    joint_xy,
                    pair.excess_tip,
                    allowed=primary_joints,
                )
            from ik_dynamic_policy import passes_influence_dominance

            if not passes_influence_dominance(
                influence,
                str(bone_name),
                min_ratio=float(config.ik_influence_dominance_min),
            ):
                continue
            if bone_name in used_bones:
                continue
            if bone_name not in experiment.node_index:
                raise RuntimeError(f"assigned IK bone {bone_name!r} is not in the loaded skeleton")
            repair_region = repair_region_from_blobs(
                excess_mask,
                missing_mask,
                dilate_px=int(config.ik_repair_dilate_px),
            )
            used_bones.add(str(bone_name))
            tip_displacement = math.sqrt(float(pair.tip_distance_sq))
            frame_jobs.append(
                IncrementalBlobJob(
                    frame_position=int(frame_position),
                    frame_index=int(frame_index),
                    bone_name=str(bone_name),
                    bone_index=int(experiment.node_index[str(bone_name)]),
                    excess_mask=np.asarray(excess_mask, dtype=bool),
                    missing_mask=np.asarray(missing_mask, dtype=bool),
                    repair_region=np.asarray(repair_region, dtype=bool),
                    excess_area=int(pair.excess_area),
                    missing_area=int(pair.missing_area),
                    target_tip=(float(pair.target_tip[0]), float(pair.target_tip[1])),
                    excess_tip=(float(pair.excess_tip[0]), float(pair.excess_tip[1])),
                    tip_displacement_px=float(tip_displacement),
                    priority_score=float(pair.combined_area) * float(tip_displacement),
                )
            )
        if frame_jobs:
            from ik_dynamic_policy import sort_blob_jobs

            jobs_by_position[int(frame_position)] = sort_blob_jobs(
                frame_jobs,
                mode=str(config.ik_job_order_mode),
            )
    return jobs_by_position


def derive_ik_keypoints_from_silhouette_misses(
    experiment: GpuCascadeExperiment,
    bone_vectors,
    root_translation,
    root_rotation,
) -> dict[int, dict[str, tuple[float, float]]]:
    """Build sparse per-frame stick targets from silhouette disagreement."""
    from gpu_depth_silhouette_solver import label_binary_components
    from ik_silhouette_miss_keypoints import (
        assign_joint_by_influence,
        build_frame_miss_keypoints,
        excess_predicted_silhouette,
    )

    config = experiment.config
    scale_x, scale_y = (float(v) for v in experiment.camera["rasterScale"])
    if scale_x <= 0.0 or scale_y <= 0.0:
        raise ValueError("camera rasterScale must be positive for silhouette-miss IK")

    bounded = experiment._bounded_bone_vectors(bone_vectors)
    keypoints_by_frame: dict[int, dict[str, tuple[float, float]]] = {}
    for frame_position, frame_index in enumerate(experiment.frame_indices):
        frame_bounded = bounded[frame_position : frame_position + 1]
        frame_root_t = root_translation[frame_position : frame_position + 1]
        frame_root_r = root_rotation[frame_position : frame_position + 1]
        predicted, predicted_depth = experiment._exact_triangle_raster(
            frame_bounded,
            frame_root_t,
            frame_root_r,
            bone_mask=experiment.active_node_mask,
        )
        if experiment.target_depth is None:
            raise RuntimeError("silhouette_miss IK requires target depth maps")
        target_mask = experiment.target_masks[frame_position].detach().cpu().numpy()
        predicted_mask = predicted[0].detach().cpu().numpy()
        target_depth = experiment.target_depth[frame_position].detach().cpu().numpy()
        pred_depth = predicted_depth[0].detach().cpu().numpy()

        joint_xy = project_search_bones_xy(
            experiment,
            bone_vectors,
            root_translation,
            root_rotation,
            frame_position=frame_position,
            min_bone_depth=int(config.ik_proximal_min_depth),
        )
        if not joint_xy:
            raise RuntimeError(
                "silhouette_miss IK found no searchable distal bones to project; "
                "check search_node_indices and ik_proximal_min_depth"
            )

        excess = excess_predicted_silhouette(
            target_mask,
            predicted_mask,
            threshold=float(config.ik_miss_predicted_alpha_threshold),
        )
        excess_labels, _excess_count = label_binary_components(excess)
        primary_joints = tuple(joint_xy)

        def _assign_joint(pair, *, _frame_position=frame_position):
            excess_mask = excess_labels == int(pair.excess_label_id)
            influence = compute_search_bone_influence_in_mask(
                experiment,
                bone_vectors,
                root_translation,
                root_rotation,
                frame_position=_frame_position,
                region_mask=excess_mask,
                min_bone_depth=int(config.ik_proximal_min_depth),
            )
            return assign_joint_by_influence(
                influence,
                allowed=primary_joints,
                node_depth=lambda name: int(
                    experiment.node_depths[int(experiment.node_index[str(name)])]
                ),
            )

        frame_keypoints, _reports = build_frame_miss_keypoints(
            target_mask,
            predicted_mask,
            target_depth,
            pred_depth,
            joint_xy,
            primary_joints=primary_joints,
            predicted_alpha_threshold=float(config.ik_miss_predicted_alpha_threshold),
            depth_tolerance=float(config.ik_miss_depth_tolerance),
            min_component_area=int(config.ik_miss_min_component_area),
            max_pairs=int(config.ik_miss_max_pairs),
            max_tip_distance_px=float(config.ik_miss_max_tip_distance_px),
            max_centroid_distance_px=float(config.ik_miss_max_centroid_distance_px),
            max_area_ratio=float(config.ik_miss_max_area_ratio),
            min_displacement_alignment=float(config.ik_miss_min_displacement_alignment),
            assign_joint=_assign_joint,
        )
        if not frame_keypoints:
            continue
        keypoints_by_frame[int(frame_index)] = {
            name: (xy[0] / scale_x, xy[1] / scale_y)
            for name, xy in frame_keypoints.items()
        }
    return keypoints_by_frame


def ik_ccd_chain(
    bone_vectors,
    chain_indices: list[int],
    target_position,
    end_effector_index: int,
    fk_fn,
    *,
    joint_limit_rad: float,
    bone_limit_scales,
    max_iterations: int = 28,
    max_step_rad: float = 0.384,
):
    """Run CCD IK on a single kinematic chain in raw pose storage space.

    ``fk_fn`` receives bounded bone vectors with shape ``(1, bones, 3)``.
    Each accepted CCD step uses the same bounded→clamp→inverse-tanh path as
    discrete joint search.
    """
    import torch

    if not chain_indices:
        return bone_vectors
    if not math.isfinite(float(joint_limit_rad)) or float(joint_limit_rad) <= 0.0:
        raise ValueError("joint_limit_rad must be finite and positive")
    bone_vectors = bone_vectors.clone()
    for _ in range(int(max_iterations)):
        world = fk_fn(bone_vectors.unsqueeze(0))[0]
        end_pos = world[end_effector_index][:3, 3]
        to_target = target_position - end_pos
        if float(to_target.norm().item()) < 1e-6:
            break
        for bone_index in reversed(chain_indices):
            world = fk_fn(bone_vectors.unsqueeze(0))[0]
            end_pos = world[end_effector_index][:3, 3]
            bone_head = world[bone_index][:3, 3]
            to_end = end_pos - bone_head
            to_tgt = target_position - bone_head
            to_end_norm = float(to_end.norm().item())
            to_tgt_norm = float(to_tgt.norm().item())
            if to_end_norm < 1e-8 or to_tgt_norm < 1e-8:
                continue
            to_end = to_end / to_end_norm
            to_tgt = to_tgt / to_tgt_norm
            axis = torch.linalg.cross(to_end, to_tgt)
            axis_norm = float(axis.norm().item())
            if axis_norm < 1e-8:
                continue
            axis = axis / axis_norm
            dot = float(torch.dot(to_end, to_tgt).clamp(-1.0, 1.0).item())
            angle = min(math.acos(dot), float(max_step_rad))
            if angle <= 0.0:
                continue
            bone_vectors = offset_raw_bone_direction(
                bone_vectors.unsqueeze(0),
                bone_index=int(bone_index),
                direction=(
                    float(axis[0].item()),
                    float(axis[1].item()),
                    float(axis[2].item()),
                ),
                delta_rad=float(angle),
                joint_limit_rad=float(joint_limit_rad),
                bone_limit_scales=bone_limit_scales,
            )[0]
    return bone_vectors


def gather_clip_winner(raw_choices, score_choices, *, min_improvement: float = 0.0, frame_weights=None):
    """Keep one clip-wide candidate. Used for the shared base pose."""
    import torch

    if len(raw_choices) != len(score_choices) or not raw_choices:
        raise ValueError("raw_choices and score_choices must be non-empty and the same length")
    if frame_weights is not None:
        weights = torch.as_tensor(frame_weights, dtype=torch.float32)
        if int(weights.numel()) != int(score_choices[0].reshape(-1).numel()):
            raise ValueError("frame_weights must match the clip frame count")
        norm = float(weights.sum().item())
        if norm <= 0.0:
            raise ValueError("frame_weights must sum to a positive value")
        means = torch.stack(
            [
                (score.reshape(-1) * weights).sum() / norm
                for score in score_choices
            ],
            dim=0,
        )
    else:
        means = torch.stack([score.reshape(-1).mean() for score in score_choices], dim=0)
    winner = int(torch.argmax(means).item())
    if winner != 0 and float(means[winner].item()) <= float(means[0].item()) + float(min_improvement):
        winner = 0
    return raw_choices[winner], winner, score_choices[winner]


def worst_frame_indices(scores, *, keep_count: int = 1):
    """Lowest-scoring frames in one clip-wide solve. Idle must not veto a walk."""
    import torch

    if int(keep_count) < 1:
        raise ValueError("keep_count must be at least 1")
    flat = scores.detach().reshape(-1)
    count = int(flat.numel())
    if count < 1:
        raise ValueError("scores must contain at least one frame")
    keep = min(count, int(keep_count))
    return torch.topk(flat, keep, largest=False).indices


def escape_worst_frame_indices(
    scores,
    collision_error,
    *,
    keep_count: int = 1,
    collision_weight: float = 0.0,
):
    """Worst frames for escape root bursts; optionally weight high collision."""
    import torch

    weight = float(collision_weight)
    if weight <= 0.0:
        return worst_frame_indices(scores, keep_count=keep_count)
    score_flat = scores.detach().reshape(-1).to(dtype=torch.float32)
    collision_flat = collision_error.detach().reshape(-1).to(dtype=torch.float32)
    if int(score_flat.numel()) != int(collision_flat.numel()):
        raise ValueError(
            "escape worst-frame scores and collision batches differ: "
            f"scores={int(score_flat.numel())} collision={int(collision_flat.numel())}"
        )
    if int(keep_count) < 1:
        raise ValueError("keep_count must be at least 1")
    count = int(score_flat.numel())
    if count < 1:
        raise ValueError("scores must contain at least one frame")
    keep = min(count, int(keep_count))
    deficiency = (1.0 - score_flat.clamp(0.0, 1.0)) + weight * collision_flat.clamp_min(0.0)
    return torch.topk(deficiency, keep, largest=True).indices


def apply_per_frame_coordinate_joint_step(
    bone_vectors,
    *,
    frame_position: int,
    bone_mask,
    bone_limit_scales,
    joint_limit_rad: float,
    step_rad: float,
    tabu_indices=None,
    tabu_length: int = 12,
    forced_bone_index: int | None = None,
) -> dict[str, Any]:
    """Move one bone on one frame by ``step_rad`` along −grad of the bounded angle.

    Cascade still scores the whole clip in one backward. This helper is the
    per-frame write used by that clip-wide step. Do not copy idle onto later
    frames first: that makes hip 15° look like a mean-score regression.
    """
    import torch

    if bone_vectors.grad is None:
        raise RuntimeError("coordinate joint step requires bone_vectors.grad")
    if not math.isfinite(float(step_rad)) or float(step_rad) <= 0.0:
        raise ValueError("step_rad must be positive")
    if not math.isfinite(float(joint_limit_rad)) or float(joint_limit_rad) <= 0.0:
        raise ValueError("joint_limit_rad must be positive")
    raw = bone_vectors
    grad = raw.grad
    frame_count, joint_count, axis_count = raw.shape
    if axis_count != 3:
        raise ValueError("bone_vectors must have shape (frames, joints, 3)")
    position = int(frame_position)
    if position < 0 or position >= frame_count:
        raise ValueError(f"frame_position {position} is outside 0..{frame_count - 1}")
    device = raw.device
    effective_tabu = min(int(tabu_length), max(joint_count - 1, 0))
    scales = bone_limit_scales.to(device=device, dtype=raw.dtype).reshape(1, joint_count, 1)
    jacobian = (1.0 - torch.tanh(raw).square()) * float(joint_limit_rad) * scales
    grad_bounded = grad / jacobian.clamp_min(1e-6)
    norms = grad_bounded.norm(dim=-1)
    if bone_mask is not None:
        mask = bone_mask.to(device=device, dtype=norms.dtype).reshape(1, joint_count)
        norms = norms * (mask > 0).to(norms.dtype)
    if effective_tabu > 0 and tabu_indices is not None:
        valid = tabu_indices[position] >= 0
        if bool(valid.any()):
            norms[position, tabu_indices[position][valid]] = 0.0
    if forced_bone_index is not None:
        chosen = int(forced_bone_index)
        if chosen < 0 or chosen >= joint_count:
            raise ValueError(f"forced_bone_index {chosen} is outside 0..{joint_count - 1}")
        bone_index_value = chosen
    else:
        bone_index_value = int(norms[position].argmax().item())
    selected_norm = float(norms[position, bone_index_value].item())
    moved = selected_norm > 0.0
    if moved:
        selected_grad = grad_bounded[position, bone_index_value]
        selected_jacobian = jacobian[position, bone_index_value]
        direction = selected_grad / selected_grad.norm().clamp_min(1e-12)
        delta_raw = (direction * float(step_rad)) / selected_jacobian.clamp_min(1e-6)
        raw.data[position, bone_index_value].sub_(delta_raw)
    new_tabu = None
    if effective_tabu > 0:
        if tabu_indices is None:
            new_tabu = torch.full((frame_count, effective_tabu), -1, dtype=torch.long, device=device)
        else:
            new_tabu = tabu_indices.clone()
            if int(new_tabu.shape[1]) != effective_tabu:
                resized = torch.full((frame_count, effective_tabu), -1, dtype=torch.long, device=device)
                keep = min(effective_tabu, int(new_tabu.shape[1]))
                resized[:, :keep] = new_tabu[:, :keep]
                new_tabu = resized
        if moved:
            previous = new_tabu[position].clone()
            if effective_tabu > 1:
                new_tabu[position, 1:] = previous[:-1]
            new_tabu[position, 0] = int(bone_index_value)
    return {
        "framePosition": position,
        "boneIndex": int(bone_index_value),
        "moved": bool(moved),
        "gradNorm": selected_norm,
        "stepRad": float(step_rad),
        "movedCount": int(moved),
        "tabuIndices": new_tabu,
    }


def root_hypothesis_unit_offsets(count: int, dimensions: int = 6):
    """Sobol offsets in [-1, 1]; row 0 is exactly zero (identity / previous heading)."""
    import torch

    if int(count) < 1:
        raise ValueError("root_hypotheses must be positive")
    if int(dimensions) < 1:
        raise ValueError("root hypothesis dimensions must be positive")
    engine = torch.quasirandom.SobolEngine(int(dimensions), scramble=False)
    samples = engine.draw(int(count))
    samples[0] = 0.5
    return samples * 2.0 - 1.0


def _pose_entry_to_xyz(entry: Any) -> np.ndarray:
    """Load a bone pose entry into XYZ Euler radians.

    JSON pose contracts use degrees for ``x``/``y``/``z`` (same as root
    ``camera_*``). Axis/angle entries use ``angle`` in degrees unless ``rad``
    is provided explicitly.
    """
    if not isinstance(entry, Mapping):
        return np.zeros(3, dtype=np.float32)
    if "axis" in entry:
        axis = str(entry.get("axis", "z")).lower()
        result = np.zeros(3, dtype=np.float32)
        if axis in {"x", "y", "z"}:
            if "rad" in entry and "angle" not in entry:
                result["xyz".index(axis)] = float(entry.get("rad", 0.0))
            else:
                result["xyz".index(axis)] = math.radians(float(entry.get("angle", 0.0)))
        return result
    if "quaternion" in entry:
        raise ValueError("GPU experiment initial poses must use xyz or axis/angle entries")
    return np.asarray(
        [math.radians(float(entry.get(axis, 0.0))) for axis in ("x", "y", "z")],
        dtype=np.float32,
    )


def _triangle_patterns(count: int) -> np.ndarray:
    patterns = np.asarray(
        [
            (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0),
            (0.5, 0.5, 0.0),
            (0.5, 0.0, 0.5),
            (0.0, 0.5, 0.5),
            (0.10, 0.45, 0.45),
            (0.45, 0.10, 0.45),
            (0.45, 0.45, 0.10),
        ],
        dtype=np.float32,
    )
    return patterns[: max(3, min(int(count), len(patterns)))]


def _read_camera_fit(path: str | Path, resolution: tuple[int, int]) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = np.asarray(data.get("basisScreenRows"), dtype=np.float32)
    if rows.shape != (2, 3):
        raise ValueError(f"camera fit must contain basisScreenRows with shape [2,3]: {path}")
    source_width, source_height = (int(value) for value in data.get("sourceResolution", (0, 0)))
    if source_width <= 0 or source_height <= 0:
        raise ValueError(f"camera fit has invalid sourceResolution: {path}")
    width, height = (int(value) for value in resolution)
    scale_x, scale_y = width / source_width, height / source_height
    # Keep the requested low-resolution raster size even when it is rounded by
    # a pixel or two from the source aspect ratio. The fitted basis is still
    # authoritative; use independent pixel scales rather than silently
    # changing the experiment's requested resolution.
    source_offset = np.asarray(data.get("screenOffsetPx"), dtype=np.float32).reshape(2)
    offset = source_offset * np.asarray((scale_x, scale_y), dtype=np.float32)
    px_per_world = float(data.get("pxPerWorld")) * np.asarray((scale_x, scale_y), dtype=np.float32)
    right = rows[0] / max(float(np.linalg.norm(rows[0])), 1e-8)
    down = rows[1] / max(float(np.linalg.norm(rows[1])), 1e-8)
    up = -down
    # Match the Blender worker's camera convention exactly: forward is the
    # camera-to-subject ray reconstructed from screen-up x screen-right. The
    # previous down x right form had the opposite sign and only affected 3D
    # root rotation/forward translation, which made GPU masks look plausible
    # while the Blender preview rotated differently.
    forward = np.cross(up, right)
    forward /= max(float(np.linalg.norm(forward)), 1e-8)
    return {
        "right": right,
        "down": down,
        "up": up,
        "forward": forward,
        "offset": offset,
        "pxPerWorld": px_per_world,
        "sourceResolution": (source_width, source_height),
        "rasterScale": (float(scale_x), float(scale_y)),
    }


def _load_target_masks(
    directory: str | Path,
    frame_indices: Sequence[int],
    resolution: tuple[int, int],
    threshold: int,
):
    import torch
    import torch.nn.functional as F

    width, height = (int(value) for value in resolution)
    masks = []
    paths = []
    for frame in frame_indices:
        path = Path(directory) / f"{int(frame):02d}.png"
        if not path.is_file():
            raise FileNotFoundError(f"GPU cascade target frame is missing: {path}")
        with Image.open(path) as image:
            rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        alpha = torch.from_numpy(np.ascontiguousarray(rgba[..., 3], dtype=np.float32))
        alpha = (alpha >= float(threshold)).to(torch.float32)[None, None]
        alpha = F.interpolate(alpha, size=(height, width), mode="nearest")[0, 0]
        masks.append(alpha)
        paths.append(path)
    return torch.stack(masks, dim=0), paths


def cascade_live_preview_frame_position(*, frame_count: int, idle_prefix_frames: int) -> int:
    """Pick the first motion plate. Frame 0 is often a locked idle hold."""
    return cascade_live_preview_frame_positions(
        frame_count=frame_count,
        idle_prefix_frames=idle_prefix_frames,
        max_frames=1,
    )[0]


def cascade_live_preview_frame_positions(
    *,
    frame_count: int,
    idle_prefix_frames: int,
    idle_suffix_frames: int = 0,
    max_frames: int = CASCADE_LIVE_PREVIEW_MAX_FRAMES,
) -> tuple[int, ...]:
    """Pick clip positions so a method step is visible across the animation.

    Cascade fits every frame together. One still cannot show whether base
    round 1 moved a walk plate while idle stayed put. Keep first motion,
    last motion, idle hold, and a mid plate, in that priority, unique and
    sorted for a left-to-right strip.
    """
    count = int(frame_count)
    if count < 1:
        raise ValueError("live preview has no clip frames")
    prefix = int(idle_prefix_frames)
    suffix = int(idle_suffix_frames)
    if prefix < 0 or suffix < 0:
        raise ValueError("idle prefix/suffix frames must be non-negative")
    keep = int(max_frames)
    if keep < 1:
        raise ValueError("live preview max_frames must be at least 1")
    first_motion = min(prefix, count - 1)
    last_motion = max(first_motion, count - 1 - suffix)
    priority = [first_motion, last_motion, 0, count - 1, (first_motion + last_motion) // 2]
    unique: list[int] = []
    seen: set[int] = set()
    for raw in priority:
        position = min(max(int(raw), 0), count - 1)
        if position in seen:
            continue
        seen.add(position)
        unique.append(position)
        if len(unique) >= keep:
            break
    return tuple(sorted(unique))


def cascade_live_preview_pane_size(
    height: int,
    width: int,
    *,
    max_width: int = CASCADE_LIVE_PREVIEW_PANE_WIDTH,
) -> tuple[int, int]:
    """Return a nearest-neighbor pane that stays watchable in the notebook."""
    if int(max_width) < 1:
        raise ValueError("live preview pane max_width must be at least 1")
    pane_h = int(height)
    pane_w = int(width)
    if pane_h < 1 or pane_w < 1:
        raise ValueError("live preview pane has an empty raster")
    if pane_w <= int(max_width):
        return pane_h, pane_w
    new_w = int(max_width)
    new_h = max(1, int(round(pane_h * new_w / pane_w)))
    return new_h, new_w


def cascade_live_preview_resize(array: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Nearest-neighbor resize a mask (H,W) or RGB (H,W,3) pane."""
    height, width = (int(size[0]), int(size[1]))
    if height < 1 or width < 1:
        raise ValueError("live preview resize size must be positive")
    arr = np.asarray(array)
    if arr.ndim not in (2, 3):
        raise ValueError("live preview resize expects HxW or HxWx3")
    if int(arr.shape[0]) == height and int(arr.shape[1]) == width:
        return arr
    if arr.ndim == 2:
        pixels = np.clip(np.rint(np.clip(arr.astype(np.float32), 0.0, 1.0) * 255.0), 0, 255).astype(np.uint8)
        scaled = np.asarray(
            Image.fromarray(pixels, "L").resize((width, height), Image.Resampling.NEAREST),
            dtype=np.float32,
        ) / 255.0
        return scaled
    if int(arr.shape[-1]) != 3:
        raise ValueError("live preview RGB resize expects HxWx3")
    pixels = np.clip(np.rint(np.clip(arr.astype(np.float32), 0.0, 1.0) * 255.0), 0, 255).astype(np.uint8)
    scaled = np.asarray(
        Image.fromarray(pixels, "RGB").resize((width, height), Image.Resampling.NEAREST),
        dtype=np.float32,
    ) / 255.0
    return scaled


def cascade_live_preview_depth_as_rgb(depth: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Turn a depth pane into RGB so geometry mode can use the watch strip."""
    gray = np.clip(np.asarray(depth, dtype=np.float32), 0.0, 1.0)
    occupied = np.asarray(mask, dtype=np.float32) > 0.5
    gray = np.where(occupied, np.maximum(gray, 16.0 / 255.0), gray)
    return np.repeat(gray[..., None], 3, axis=-1)


def _preview_occupancy_overlay(
    target_mask: np.ndarray,
    predicted_mask: np.ndarray,
    *,
    alpha_threshold: float,
) -> np.ndarray:
    target_foreground = np.asarray(target_mask, dtype=np.float32) > 0.5
    predicted_foreground = np.asarray(predicted_mask, dtype=np.float32) > float(alpha_threshold)
    overlay = np.zeros(target_foreground.shape + (3,), dtype=np.uint8)
    overlay[target_foreground & ~predicted_foreground] = (235, 45, 45)
    overlay[predicted_foreground & ~target_foreground] = (45, 105, 240)
    overlay[target_foreground & predicted_foreground] = (35, 210, 100)
    return overlay


def _rgb_pane_to_image(rgb: np.ndarray, size: tuple[int, int]) -> Image.Image:
    resized = cascade_live_preview_resize(rgb, size)
    pixels = np.clip(np.rint(np.clip(resized, 0.0, 1.0) * 255.0), 0, 255).astype(np.uint8)
    return Image.fromarray(pixels, "RGB")


def compose_cascade_solver_watch(
    *,
    frames: Sequence[int],
    current_label: str,
    current_rgb: Sequence[np.ndarray],
    current_mask: Sequence[np.ndarray],
    target_mask: Sequence[np.ndarray],
    previous_label: str | None = None,
    previous_rgb: Sequence[np.ndarray] | None = None,
    pane_size: tuple[int, int],
    change_gain: float = CASCADE_LIVE_PREVIEW_CHANGE_GAIN,
    alpha_threshold: float = 0.01,
) -> Image.Image:
    """Stack previous-step | current-step | change | occupancy for sampled frames.

    Top is the last committed method step (for example ``base 1/2 done``).
    Bottom is the live step. The change row is amplified |now − previous| so
    a later round that actually moved those frames cannot look identical.
    Black change means this step has not moved the sampled plates.
    """
    count = len(frames)
    if count < 1:
        raise ValueError("solver watch has no sampled frames")
    if (
        len(current_rgb) != count
        or len(current_mask) != count
        or len(target_mask) != count
    ):
        raise ValueError("solver watch current arrays must match sampled frames")
    has_previous = previous_rgb is not None
    if has_previous:
        if previous_label is None:
            raise ValueError("solver watch previous RGB requires previous_label")
        if len(previous_rgb) != count:
            raise ValueError("solver watch previous RGB must match sampled frames")
    pane_h, pane_w = (int(pane_size[0]), int(pane_size[1]))
    if pane_h < 1 or pane_w < 1:
        raise ValueError("solver watch pane_size must be positive")
    caption_h = 18
    row_h = caption_h + pane_h
    rows = 4 if has_previous else 2
    canvas = Image.new("RGB", (pane_w * count, row_h * rows), (24, 24, 24))
    draw = ImageDraw.Draw(canvas)

    def blit_row(row_index: int, label: str, images: Sequence[Image.Image]) -> None:
        top = int(row_index) * row_h
        draw.text((4, top + 3), str(label)[:88], fill=(240, 240, 240))
        for column, image in enumerate(images):
            canvas.paste(image, (column * pane_w, top + caption_h))

    current_images = [_rgb_pane_to_image(rgb, (pane_h, pane_w)) for rgb in current_rgb]
    overlay_images = []
    for predicted, target, frame in zip(current_mask, target_mask, frames):
        overlay = _preview_occupancy_overlay(
            cascade_live_preview_resize(target, (pane_h, pane_w)),
            cascade_live_preview_resize(predicted, (pane_h, pane_w)),
            alpha_threshold=float(alpha_threshold),
        )
        image = Image.fromarray(overlay, "RGB")
        ImageDraw.Draw(image).text((2, 2), f"{int(frame):02d}", fill=(255, 255, 255))
        overlay_images.append(image)
    if has_previous:
        previous_images = [_rgb_pane_to_image(rgb, (pane_h, pane_w)) for rgb in previous_rgb]
        change_images = []
        gain = float(change_gain)
        if not math.isfinite(gain) or gain <= 0.0:
            raise ValueError("solver watch change_gain must be finite and positive")
        for previous, current in zip(previous_rgb, current_rgb):
            prev_r = cascade_live_preview_resize(previous, (pane_h, pane_w))
            curr_r = cascade_live_preview_resize(current, (pane_h, pane_w))
            delta = np.clip(np.abs(curr_r - prev_r) * gain, 0.0, 1.0)
            change_images.append(_rgb_pane_to_image(delta, (pane_h, pane_w)))
        blit_row(0, str(previous_label), previous_images)
        blit_row(1, str(current_label), current_images)
        blit_row(2, "change x4 (black = sampled frames unchanged)", change_images)
        blit_row(3, "overlay R=target B=candidate G=shared", overlay_images)
    else:
        blit_row(0, str(current_label), current_images)
        blit_row(1, "overlay R=target B=candidate G=shared", overlay_images)
    return canvas


def cascade_live_preview_depth_panel(
    target_depth,
    target_mask: np.ndarray,
    *,
    uses_rgb: bool,
):
    """Return the depth array ``GpuDepthLivePreview.show`` still requires.

    The RGB occupancy panel does not read depth. Geometry silhouette+depth
    preview still needs the VDA target. Missing depth with RGB is zeros so
    dinov3_dense can preview without a depth cache.
    """
    mask = np.asarray(target_mask)
    if bool(uses_rgb):
        if target_depth is None:
            return np.zeros(mask.shape, dtype=np.float32)
        return np.asarray(target_depth, dtype=np.float32)
    if target_depth is None:
        raise RuntimeError("depth/silhouette live preview requires loaded target depth maps")
    return np.asarray(target_depth, dtype=np.float32)


def _load_target_depth(
    directory: str | Path,
    frame_indices: Sequence[int],
    resolution: tuple[int, int],
):
    import torch
    import torch.nn.functional as F
    from predict_sprite_depth import load_depth_u16
    from run_vda_movement_depth import assert_vda_pipeline_cache

    directory = Path(directory)
    assert_vda_pipeline_cache(directory)
    width, height = (int(value) for value in resolution)
    depth = []
    paths = []
    for frame in frame_indices:
        path = directory / f"{int(frame):02d}.png"
        if not path.is_file():
            raise FileNotFoundError(f"GPU cascade target depth frame is missing: {path}")
        gray = load_depth_u16(path)
        tensor = torch.from_numpy(np.ascontiguousarray(gray))[None, None]
        tensor = F.interpolate(tensor, size=(height, width), mode="bilinear", align_corners=False)[0, 0]
        depth.append(tensor)
        paths.append(path)
    return torch.stack(depth, dim=0), paths


@dataclass
class _PrimitiveGPU:
    node: int
    positions: Any
    homogeneous_positions: Any
    joints: Any | None
    weights: Any | None
    normalized_weights: Any | None
    skin_joints: Any | None
    inverse_bind: Any | None
    indices: Any
    sample_triangles: Any
    sample_barycentric: Any
    texcoords: Any | None = None
    material_index: int | None = None


def dinov3_dense_cascade_config(**overrides) -> GpuCascadeConfig:
    """Return a fail-closed DINOv3-only cascade config.

    Geometry, collision, unique occupancy, Adam root, IK, and the gradient
    ladder stay off. Discrete root hypotheses and joint walks still run.
    """
    values: dict[str, Any] = {
        "score_mode": "dinov3_dense",
        "depth_weight": 0.0,
        "silhouette_weight": 0.0,
        "chroma_weight": 0.0,
        "motion_weight": 0.0,
        "collision_enabled": False,
        "collision_weight": 0.0,
        "joint_unique_gain_weight": 0.0,
        "fine_unique_gain_weight": 0.0,
        "root_iterations": 0,
        "gradient_ladder_enabled": False,
        "ik_enabled": False,
        "bone_order_mode": "dependency",
        "dense_semantic_model_id": DEFAULT_CASCADE_DINO_V3_MODEL_ID,
        "dense_semantic_feature_layers": ("last",),
    }
    values.update(overrides)
    return GpuCascadeConfig(**values)


class GpuCascadeExperiment:
    """GPU-resident differentiable experiment for one mesh/clip."""

    def __init__(
        self,
        *,
        src_glb: str | Path,
        camera_fit: str | Path,
        target_frame_dir: str | Path,
        frame_indices: Sequence[int],
        config: GpuCascadeConfig | None = None,
    ) -> None:
        import torch

        self.config = config or GpuCascadeConfig()
        self.config.validate()
        self.device = torch.device(_select_device(self.config.device))
        self.target_frame_dir = Path(target_frame_dir).resolve()
        # RGB semantic interleave uses the Meshy's embedded base-color texture;
        # the geometric proxy loader keeps those large images lazy elsewhere.
        self.src_glb = Path(src_glb).resolve()
        self.asset: ProxyAsset = load_asset(self.src_glb, decode_images=True)
        self.bind_report = validate_bind_pose(self.asset)
        if not self.bind_report.get("ok"):
            raise ValueError(f"GPU cascade bind validation failed: {self.bind_report}")
        self.frame_indices = tuple(int(frame) for frame in frame_indices)
        if not self.frame_indices:
            raise ValueError("frame_indices cannot be empty")
        if float(self.config.motion_weight) > 0.0 and len(self.frame_indices) < 2:
            raise ValueError("motion_weight is set but the clip has fewer than two frames")
        if self.config.root_search_frame is not None and int(self.config.root_search_frame) not in self.frame_indices:
            raise ValueError(
                "root_search_frame must be one of frame_indices when it is not None"
            )
        self.camera = _read_camera_fit(camera_fit, self.config.resolution)
        self.target_masks, self.target_paths = _load_target_masks(
            target_frame_dir,
            self.frame_indices,
            self.config.resolution,
            self.config.alpha_threshold,
        )
        self.target_masks = self.target_masks.to(self.device)
        self.target_depth = None
        self.target_depth_paths: list[Path] = []
        if getattr(self.config, "depth_target_dir", None) is not None:
            self.target_depth, self.target_depth_paths = _load_target_depth(
                self.config.depth_target_dir,
                self.frame_indices,
                self.config.resolution,
            )
            self.target_depth = self.target_depth.to(self.device)
        self._exact_raster_context = None
        if bool(getattr(self.config, "exact_raster_enabled", False)):
            from nvdiffrast_local import ensure_local_nvdiffrast

            ensure_local_nvdiffrast(required=True)
            import nvdiffrast.torch as dr

            self._exact_raster_context = dr.RasterizeCudaContext(device=str(self.device))
        self.target_sdf = self._build_target_sdf(self.target_masks)
        self.node_names = tuple(node.name for node in self.asset.nodes)
        self.node_index = {name: index for index, name in enumerate(self.node_names)}
        active_nodes = sorted(
            {
                int(joint)
                for skin in self.asset.skins
                for joint in skin.joints
            }
        )
        self.active_node_indices = tuple(active_nodes)
        self.active_node_mask = None
        self.root_pivot = self._bind_pivot()
        self._build_gpu_asset()
        self._resolve_search_bones()
        self._resolve_anatomy_groups()
        self._build_grid()
        self.target_rgb = None
        self.target_lab_ab = None
        self.dense_semantic_scorer = None
        self.dense_semantic_target_grids: list[dict[str, Any]] = []
        self._sprite_change_maps = None
        self._committed_pred_rgb = None
        self._collision_table = None
        self._anatomy_veto_strain_table = None
        self._anatomy_veto_collision_table = None
        self._anatomy_veto_prop_targets = None
        if bool(self.config.collision_enabled):
            self._initialize_mesh_collision()
        if bool(self.config.anatomy_veto_enabled):
            self._initialize_anatomy_veto()
        if self.config.uses_rgb_raster():
            self._initialize_target_rgb()
        if float(self.config.chroma_weight) > 0.0:
            self._initialize_chroma_targets()
        if self.config.uses_dense_semantic_encoder():
            self._initialize_dense_semantic_targets()
        self.still_sprite_mask = None
        self.still_sprite_rgb_mad: tuple[float, ...] | None = None
        if bool(self.config.joint_keep_still_sprite_lock) or bool(
            self.config.joint_keep_sprite_change_gate
        ):
            reason = (
                "lock"
                if bool(self.config.joint_keep_still_sprite_lock)
                else "change-gate"
            )
            self._initialize_still_sprite_lock(reason=reason)
        self._live_preview = None
        self._live_preview_committed: dict[str, Any] | None = None

    def _initialize_still_sprite_lock(self, *, reason: str = "lock") -> None:
        """Build the still-sprite mask from the same PNGs the scorer sees."""
        import torch

        mads = consecutive_sprite_rgb_mad(self.target_paths)
        still = still_sprite_lock_mask(
            mads,
            threshold=float(self.config.joint_keep_still_sprite_rgb_mad),
        )
        if len(still) != len(self.frame_indices):
            raise ValueError(
                "still-sprite lock mask does not match the clip: "
                f"{len(still)} flags, {len(self.frame_indices)} frames"
            )
        self.still_sprite_rgb_mad = mads
        self.still_sprite_mask = torch.tensor(still, dtype=torch.bool, device=self.device)
        locked_frames = [
            f"{int(self.frame_indices[index]):02d}"
            for index, flag in enumerate(still)
            if flag
        ]
        print(
            f"gpu still-sprite {reason}: mad={float(self.config.joint_keep_still_sprite_rgb_mad):.4f} "
            f"still={sum(still)}/{len(still)} threshold="
            f"{float(self.config.joint_keep_still_sprite_rgb_mad):.3f} "
            f"frames={','.join(locked_frames)}",
            flush=True,
        )

    def _copy_still_leading_(self, tensor, *, force: bool = False) -> None:
        """Copy tensor[f-1] onto still frames, in order, so chains stay frozen."""
        import torch

        if not force and not bool(self.config.joint_keep_still_sprite_lock):
            return
        if self.still_sprite_mask is None:
            return
        still = self.still_sprite_mask
        if int(tensor.shape[0]) != int(still.shape[0]):
            raise ValueError(
                "still-sprite lock batch does not match the mask: "
                f"tensor={int(tensor.shape[0])} mask={int(still.shape[0])}"
            )
        with torch.no_grad():
            for index in range(1, int(still.shape[0])):
                if bool(still[index].item()):
                    tensor[index].copy_(tensor[index - 1])

    def _pose_row_is_bind(self, bone_vectors, frame_position: int) -> bool:
        import torch

        row = bone_vectors[int(frame_position)]
        return float(row.abs().sum().detach().item()) <= 1e-7

    def _seed_transit_pose_from_previous_(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
        *,
        frame_position: int | None = None,
        only_if_bind: bool = False,
        progress: bool = False,
        label: str = "seedPreviousFrame",
    ) -> int:
        """Copy the previous clip row onto transit frames (one_bone_depth parity).

        When ``only_if_bind`` is set, rows that already carry joint edits are
        left alone so a later round does not stomp per-frame IK/joint work.
        """
        import torch

        if not bool(self.config.seed_previous_frame):
            return 0
        prefix = int(getattr(self.config, "idle_prefix_frames", 0) or 0)
        frame_count = int(bone_vectors.shape[0])
        if frame_position is None:
            positions = range(max(1, prefix), frame_count)
        else:
            positions = [int(frame_position)]
        seeded = 0
        with torch.no_grad():
            for fp in positions:
                if int(fp) <= 0:
                    continue
                if only_if_bind and not self._pose_row_is_bind(bone_vectors, int(fp)):
                    continue
                bone_vectors[int(fp)].copy_(bone_vectors[int(fp) - 1])
                if self.config.optimize_root_translation:
                    root_translation[int(fp)].copy_(root_translation[int(fp) - 1])
                if self.config.optimize_root_rotation:
                    root_rotation[int(fp)].copy_(root_rotation[int(fp) - 1])
                seeded += 1
        if progress and seeded > 0:
            print(
                f"gpu {label}: seeded {seeded} transit row(s) from previous frame "
                f"(seed_previous_frame=1 onlyIfBind={int(only_if_bind)})",
                flush=True,
            )
        return seeded

    def _lock_still_sprite_pose_(self, bone_vectors, root_translation, root_rotation) -> None:
        """Still sprites cannot keep a different pose than the previous frame."""
        if not bool(self.config.joint_keep_still_sprite_lock):
            return
        self._copy_still_leading_(bone_vectors)
        self._copy_still_leading_(root_translation)
        self._copy_still_leading_(root_rotation)

    def _seed_still_frames_from_previous_(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
    ) -> None:
        """Once per joint stage, still plates start from the previous pose.

        A same-frame veto on every plate froze angel frames 01–27: the first
        step off bind changes more RGB than consecutive sprites do. Walk
        frames are not still, so they keep DINOv3. Still frames would stay
        bind without this seed.
        """
        if not bool(self.config.joint_keep_sprite_change_gate):
            return
        if bool(self.config.joint_keep_still_sprite_lock):
            return
        self._copy_still_leading_(bone_vectors, force=True)
        self._copy_still_leading_(root_translation, force=True)
        self._copy_still_leading_(root_rotation, force=True)
        self._refresh_committed_pred_rgb(bone_vectors, root_translation, root_rotation)
        print("gpu sprite-change gate: seeded still frames from previous pose", flush=True)

    def _commit_live_pose_(self, bone_vectors, root_translation, root_rotation) -> None:
        """Write-side keep: optional still-lock copy, then refresh gate plates."""
        self._lock_still_sprite_pose_(bone_vectors, root_translation, root_rotation)
        self._refresh_committed_pred_rgb(bone_vectors, root_translation, root_rotation)

    def _lock_still_sprite_winner(self, winner):
        """Remap per-frame winner indexes so idle does not grow extra probes."""
        import torch

        if self.still_sprite_mask is None or not bool(self.config.joint_keep_still_sprite_lock):
            return winner
        still = [bool(flag) for flag in self.still_sprite_mask.detach().cpu().tolist()]
        locked = lock_winner_indices_to_previous(
            [int(choice) for choice in winner.detach().cpu().tolist()],
            still,
        )
        return torch.as_tensor(locked, dtype=winner.dtype, device=winner.device)

    def _lock_idle_prefix_winner(self, winner, prefix_count: int):
        """Reject joint moves on idle-prefix frames so transit tuning stays isolated."""
        import torch

        prefix = int(prefix_count)
        if prefix <= 0:
            return winner
        locked = winner.detach().clone()
        stop = min(prefix, int(locked.numel()))
        if stop > 0:
            locked[:stop] = 0
        return locked

    def _lock_idle_bookend_winner(self, winner, prefix_count: int):
        from cascade_idle_loop_closure import lock_idle_suffix_winner

        locked = self._lock_idle_prefix_winner(winner, prefix_count)
        if not bool(self.config.idle_suffix_mirror_prefix_enabled):
            return locked
        return lock_idle_suffix_winner(
            locked,
            suffix_count=int(getattr(self.config, "idle_suffix_frames", 0) or 0),
            frame_count=int(locked.numel()),
        )

    def _mirror_idle_suffix_from_prefix_if_enabled(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
    ) -> int:
        if not bool(self.config.idle_suffix_mirror_prefix_enabled):
            return 0
        from cascade_idle_loop_closure import mirror_idle_suffix_from_prefix

        prefix = int(getattr(self.config, "idle_prefix_frames", 0) or 0)
        suffix = int(getattr(self.config, "idle_suffix_frames", 0) or 0)
        copied = mirror_idle_suffix_from_prefix(
            bone_vectors,
            root_translation,
            root_rotation,
            prefix_count=prefix,
            suffix_count=suffix,
        )
        if copied > 0:
            print(
                f"gpu idle loop: mirrored prefix->suffix frames={copied} "
                f"prefix={prefix} suffix={suffix}",
                flush=True,
            )
        return int(copied)

    def _initialize_sprite_change_gate(self) -> None:
        """Build the prev-sprite-to-current-sprite change maps used by keep."""
        import torch

        if self.target_rgb is None:
            raise RuntimeError(
                "joint_keep_sprite_change_gate is on but target RGB was not loaded"
            )
        change = sprite_frame_change_maps(self.target_rgb)
        occupied = self.target_masks > 0.5
        occupied_union = occupied.clone()
        if int(occupied_union.shape[0]) > 1:
            occupied_union[1:] = occupied[1:] | occupied[:-1]
        mass = occupied_union.to(dtype=change.dtype)
        denom = mass.reshape(int(mass.shape[0]), -1).sum(dim=1).clamp_min(1e-6)
        means = (change * mass).reshape(int(mass.shape[0]), -1).sum(dim=1) / denom
        self._sprite_change_maps = change
        moving = int((means[1:] > 1e-6).sum().item()) if int(means.numel()) > 1 else 0
        print(
            f"gpu sprite-change gate: veto excess>{SPRITE_CHANGE_VETO_EPS:g} "
            f"on still plates vs last committed plate (DINOv3 is not mixed) "
            f"slack={float(self.config.joint_keep_sprite_change_slack):.4f} "
            f"occupiedMean={float(means[1:].mean().item()) if int(means.numel()) > 1 else 0.0:.5f} "
            f"movingFrames={moving}/{max(int(means.numel()) - 1, 0)}",
            flush=True,
        )

    def _refresh_committed_pred_rgb(self, bone_vectors, root_translation, root_rotation) -> None:
        """Raster the live clip so later candidates compare to this plate."""
        import torch

        if not bool(self.config.joint_keep_sprite_change_gate):
            return
        with torch.no_grad():
            predicted_rgb, _alpha, _depth = self.exact_triangle_rgb(
                self._bounded_bone_vectors(bone_vectors),
                root_translation,
                root_rotation,
                bone_mask=self.active_node_mask,
            )
        if int(predicted_rgb.shape[0]) != len(self.frame_indices):
            raise RuntimeError(
                "committed RGB refresh must raster every clip frame: "
                f"got {int(predicted_rgb.shape[0])}, expected {len(self.frame_indices)}"
            )
        self._committed_pred_rgb = predicted_rgb.detach()

    def _remember_committed_pred_rgb_at(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
        frame_position: int,
    ) -> None:
        import torch

        if not bool(self.config.joint_keep_sprite_change_gate):
            return
        if self._committed_pred_rgb is None:
            raise RuntimeError("committed RGB was not seeded before per-frame remember")
        position = int(frame_position)
        if position < 0 or position >= int(self._committed_pred_rgb.shape[0]):
            raise ValueError(f"committed RGB frame {position} is outside the clip")
        index = torch.as_tensor([position], dtype=torch.long, device=bone_vectors.device)
        with torch.no_grad():
            predicted_rgb, _alpha, _depth = self.exact_triangle_rgb(
                self._bounded_bone_vectors(bone_vectors).index_select(0, index),
                root_translation.index_select(0, index),
                root_rotation.index_select(0, index),
                bone_mask=self.active_node_mask,
            )
        self._committed_pred_rgb[position].copy_(predicted_rgb[0].detach())

    def _apply_sprite_change_gate(self, components, predicted_rgb, frame_positions):
        import torch

        if predicted_rgb is None:
            raise RuntimeError("sprite-change gate requires predicted RGB")
        if self._sprite_change_maps is None:
            raise RuntimeError("sprite-change gate maps were not initialized")
        if self._committed_pred_rgb is None:
            raise RuntimeError(
                "sprite-change gate has no committed same-frame RGB; "
                "seed the live clip raster before scoring candidates"
            )
        positions = frame_positions.detach().to(
            device=predicted_rgb.device,
            dtype=torch.long,
        )
        previous_rgb = previous_predicted_for_sprite_change_gate(
            predicted_rgb,
            positions,
            self._committed_pred_rgb,
        )
        sprite_change = self._sprite_change_maps.index_select(0, positions)
        occupancy = torch.maximum(
            self.target_masks.index_select(0, positions),
            self.target_masks.index_select(0, (positions - 1).clamp(min=0)),
        )
        excess = excess_predicted_change(
            predicted_rgb,
            previous_rgb,
            sprite_change,
            occupancy,
            slack=float(self.config.joint_keep_sprite_change_slack),
        )
        if self.still_sprite_mask is None:
            raise RuntimeError(
                "sprite-change gate vetoes still plates and needs the still-sprite mask"
            )
        excess = mask_sprite_change_excess_to_still_frames(
            excess,
            self.still_sprite_mask,
            positions,
        )
        for key in (
            "score",
            "geometryScore",
            "denseSemanticQuality",
        ):
            if key in components and components[key] is not None:
                components[key] = veto_scores_on_sprite_change_excess(
                    components[key],
                    excess,
                )
        components["spriteChangeExcess"] = excess
        return components

    def attach_live_preview(self, host: Any | None) -> None:
        """Attach a ``GpuDepthLivePreview`` host for notebook updates."""
        self._live_preview = host
        self._live_preview_committed = None

    def _live_preview_rasters(
        self,
        frame_positions: Sequence[int],
        bone_vectors,
        root_translation,
        root_rotation,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
        """Raster sampled clip frames for display only (does not affect scoring)."""
        import torch

        positions = [int(position) for position in frame_positions]
        if not positions:
            raise ValueError("live preview has no frame positions")
        index = torch.as_tensor(positions, dtype=torch.long, device=bone_vectors.device)
        bounded = self._bounded_bone_vectors(bone_vectors.index_select(0, index))
        frame_root_t = root_translation.index_select(0, index)
        frame_root_r = root_rotation.index_select(0, index)
        with torch.no_grad():
            if self.config.uses_rgb_raster():
                predicted_rgb, predicted_alpha, predicted_depth = self.exact_triangle_rgb(
                    bounded,
                    frame_root_t,
                    frame_root_r,
                    bone_mask=self.active_node_mask,
                )
                return (
                    predicted_alpha.detach().cpu().numpy(),
                    predicted_depth.detach().cpu().numpy(),
                    predicted_rgb.detach().cpu().numpy(),
                )
            predicted_alpha, predicted_depth = self._exact_triangle_raster(
                bounded,
                frame_root_t,
                frame_root_r,
                bone_mask=self.active_node_mask,
            )
            return (
                predicted_alpha.detach().cpu().numpy(),
                predicted_depth.detach().cpu().numpy(),
                None,
            )

    def _refresh_live_preview(
        self,
        *,
        frame_index: int,
        frame_position: int,
        label: str,
        bone_vectors,
        root_translation,
        root_rotation,
        force: bool = False,
    ) -> None:
        if self._live_preview is None:
            return
        if not self._live_preview.will_emit(force=force):
            self._live_preview.skip_visit()
            return
        position = int(frame_position)
        predicted_mask, predicted_depth, predicted_rgb = self._live_preview_rasters(
            (position,),
            bone_vectors,
            root_translation,
            root_rotation,
        )
        predicted_mask = predicted_mask[0]
        predicted_depth = predicted_depth[0]
        if predicted_rgb is not None:
            predicted_rgb = predicted_rgb[0]
        target_mask = self.target_masks[position].detach().cpu().numpy()
        uses_rgb = predicted_rgb is not None
        target_rgb = None
        if uses_rgb:
            if self.target_rgb is None:
                raise RuntimeError("RGB live preview is set but target RGB was not loaded")
            target_rgb = self.target_rgb[position].detach().cpu().numpy()
        target_depth = cascade_live_preview_depth_panel(
            None if self.target_depth is None else self.target_depth[position].detach().cpu().numpy(),
            target_mask,
            uses_rgb=uses_rgb,
        )
        self._live_preview.show(
            frame=int(frame_index),
            label=label,
            target_depth=target_depth,
            predicted_depth=np.asarray(predicted_depth, dtype=np.float32),
            target_mask=target_mask,
            predicted_mask=np.asarray(predicted_mask, dtype=np.float32),
            target_rgb=None if target_rgb is None else np.asarray(target_rgb, dtype=np.float32),
            predicted_rgb=None if predicted_rgb is None else np.asarray(predicted_rgb, dtype=np.float32),
            force=force,
        )

    def _live_preview_frame_position(self) -> int:
        return cascade_live_preview_frame_position(
            frame_count=len(self.frame_indices),
            idle_prefix_frames=int(getattr(self.config, "idle_prefix_frames", 0) or 0),
        )

    def _live_preview_frame_positions(self) -> tuple[int, ...]:
        return cascade_live_preview_frame_positions(
            frame_count=len(self.frame_indices),
            idle_prefix_frames=int(getattr(self.config, "idle_prefix_frames", 0) or 0),
            idle_suffix_frames=int(getattr(self.config, "idle_suffix_frames", 0) or 0),
        )

    def _preview_clip_pose(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
        label: str,
        *,
        force: bool = False,
        commit: bool = False,
    ) -> None:
        """Push a clip strip so method steps can be compared.

        Top row is the last committed step (``base 1/2 done``). Bottom is
        this call. Change is amplified |now − previous| on the sampled
        plates. ``commit=True`` freezes this pose as the next comparison
        baseline. Round labels use ``force=True`` so base 1 and base 2
        always redraw even when the sampled plates did not move.
        """
        if self._live_preview is None:
            return
        if not self._live_preview.will_emit(force=force):
            self._live_preview.skip_visit()
            return
        positions = self._live_preview_frame_positions()
        predicted_mask, predicted_depth, predicted_rgb = self._live_preview_rasters(
            positions,
            bone_vectors,
            root_translation,
            root_rotation,
        )
        target_masks = [
            self.target_masks[int(position)].detach().cpu().numpy()
            for position in positions
        ]
        if predicted_rgb is None:
            current_rgb = [
                cascade_live_preview_depth_as_rgb(depth, mask)
                for depth, mask in zip(predicted_depth, predicted_mask)
            ]
        else:
            current_rgb = [np.asarray(rgb, dtype=np.float32) for rgb in predicted_rgb]
        current_mask = [np.asarray(mask, dtype=np.float32) for mask in predicted_mask]
        pane_size = cascade_live_preview_pane_size(
            int(current_mask[0].shape[0]),
            int(current_mask[0].shape[1]),
        )
        committed = self._live_preview_committed
        canvas = compose_cascade_solver_watch(
            frames=[int(self.frame_indices[int(position)]) for position in positions],
            current_label=str(label),
            current_rgb=current_rgb,
            current_mask=current_mask,
            target_mask=target_masks,
            previous_label=None if committed is None else str(committed["label"]),
            previous_rgb=None if committed is None else committed["rgb"],
            pane_size=pane_size,
            alpha_threshold=float(self._live_preview.alpha_threshold),
        )
        self._live_preview.emit_canvas(canvas)
        if bool(commit):
            self._live_preview_committed = {
                "label": str(label),
                "rgb": [np.asarray(rgb, dtype=np.float32).copy() for rgb in current_rgb],
            }

    def release_cuda(self) -> None:
        """Drop the nvdiffrast context so Windows can return system RAM.

        WDDM keeps that working set in host memory after a clip. A second
        overlapping batch process, or a leftover Jupyter kernel, is what
        emptied the machine and made later rasters page for tens of minutes.
        """
        self._exact_raster_context = None
        import gc

        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def _build_target_sdf(self, masks):
        """Build an outside-only target distance field once on the GPU."""
        import torch

        if float(self.config.sdf_weight) <= 0.0:
            return None
        try:
            from scipy.ndimage import distance_transform_edt
        except ImportError as exc:
            raise RuntimeError(
                "sdf_weight is enabled but scipy is unavailable; install scipy or set sdf_weight=0"
            ) from exc
        binary = masks.detach().cpu().numpy() > 0.5
        fields = []
        for mask in binary:
            # Interior pixels have zero penalty. Exterior pixels receive the
            # distance to the nearest target pixel, which supplies a useful
            # direction without punishing valid points inside the silhouette.
            distance = distance_transform_edt(~mask).astype(np.float32)
            fields.append(np.minimum(distance, float(self.config.sdf_max_distance_px)))
        return torch.as_tensor(np.stack(fields), dtype=torch.float32, device=self.device)

    def _bind_pivot(self):
        import torch
        from roc_geometric_proxy import evaluate_points

        points = evaluate_points(self.asset, level=1, max_points=20000)
        if len(points) == 0:
            return torch.zeros(3, dtype=torch.float32, device=self.device)
        return torch.as_tensor(np.mean(points, axis=0), dtype=torch.float32, device=self.device)

    def _build_gpu_asset(self) -> None:
        import torch

        self.parents = tuple(node.parent for node in self.asset.nodes)
        self.node_depths = tuple(self._node_depth(index) for index in range(len(self.parents)))
        from cascade_bone_limits import resolve_bone_limit_scales

        self.bone_limit_scales = torch.as_tensor(
            resolve_bone_limit_scales(
                node_names=self.node_names,
                node_depths=self.node_depths,
                proximal_depth=int(self.config.proximal_bone_limit_depth),
                proximal_scale=float(self.config.proximal_bone_limit_scale),
                overrides=self.config.bone_limit_scale_overrides,
            ),
            dtype=torch.float32,
            device=self.device,
        )
        self.base_rotations = torch.as_tensor(
            np.stack([_quat_to_matrix(node.rotation) for node in self.asset.nodes]),
            dtype=torch.float32,
            device=self.device,
        )
        self.translations = torch.as_tensor(
            np.stack([node.translation for node in self.asset.nodes]).astype(np.float32),
            dtype=torch.float32,
            device=self.device,
        )
        self.scales = torch.as_tensor(
            np.stack([node.scale for node in self.asset.nodes]).astype(np.float32),
            dtype=torch.float32,
            device=self.device,
        )
        self.scale_matrices = torch.diag_embed(self.scales)
        primitives: list[_PrimitiveGPU] = []
        patterns = _triangle_patterns(self.config.samples_per_triangle)
        for primitive in self.asset.primitives:
            if primitive.indices is None:
                count = (len(primitive.positions) // 3) * 3
                triangles = np.arange(count, dtype=np.int64).reshape(-1, 3)
            else:
                triangles = np.asarray(primitive.indices, dtype=np.int64).reshape(-1, 3)
            triangles = triangles[(triangles >= 0).all(axis=1)]
            cap = int(self.config.max_triangles_per_primitive)
            if len(triangles) > cap:
                chosen = np.linspace(0, len(triangles) - 1, cap, dtype=np.int64)
                triangles = triangles[chosen]
            triangles = np.repeat(triangles, len(patterns), axis=0)
            barycentric = np.tile(patterns, (len(triangles) // len(patterns), 1))
            skin = self.asset.skins[int(primitive.skin)] if primitive.skin is not None else None
            positions = torch.as_tensor(np.asarray(primitive.positions, dtype=np.float32), device=self.device)
            homogeneous_positions = torch.cat(
                (positions, torch.ones((int(positions.shape[0]), 1), dtype=torch.float32, device=self.device)),
                dim=1,
            )
            joints = (
                torch.as_tensor(np.asarray(primitive.joints, dtype=np.int64), device=self.device)
                if primitive.joints is not None
                else None
            )
            weights = (
                torch.as_tensor(np.asarray(primitive.weights, dtype=np.float32), device=self.device)
                if primitive.weights is not None
                else None
            )
            normalized_weights = None
            if weights is not None:
                normalized_weights = weights / torch.clamp(weights.sum(dim=1, keepdim=True), min=1e-8)
            primitives.append(
                _PrimitiveGPU(
                    node=int(primitive.node),
                    positions=positions,
                    homogeneous_positions=homogeneous_positions,
                    joints=joints,
                    weights=weights,
                    normalized_weights=normalized_weights,
                    skin_joints=(
                        torch.as_tensor(np.asarray(skin.joints, dtype=np.int64), device=self.device)
                        if skin is not None
                        else None
                    ),
                    inverse_bind=(
                        torch.as_tensor(np.asarray(skin.inverse_bind, dtype=np.float32), device=self.device)
                        if skin is not None
                        else None
                    ),
                    indices=torch.as_tensor(
                        np.asarray(
                            (
                                np.arange((len(primitive.positions) // 3) * 3, dtype=np.int64)
                                if primitive.indices is None
                                else primitive.indices
                            ),
                            dtype=np.int64,
                        ).reshape(-1, 3),
                        dtype=torch.long,
                        device=self.device,
                    ),
                    sample_triangles=torch.as_tensor(triangles, dtype=torch.long, device=self.device),
                    sample_barycentric=torch.as_tensor(barycentric, dtype=torch.float32, device=self.device),
                    texcoords=(
                        torch.as_tensor(np.asarray(primitive.texcoords, dtype=np.float32), device=self.device)
                        if primitive.texcoords is not None
                        else None
                    ),
                    material_index=None if primitive.material is None else int(primitive.material),
                )
            )
        self.primitives = tuple(primitives)
        self._build_fk_levels()
        # Materials and base-color images are immutable mesh data. Upload them
        # once so semantic RGB probes never reopen the GLB or leave CUDA for
        # texture lookup. The geometric silhouette/depth path does not read
        # these buffers.
        self._gpu_materials = tuple(
            {
                "factor": torch.as_tensor(
                    np.asarray(material.base_color_factor[:3], dtype=np.float32),
                    device=self.device,
                ),
                "alpha": float(material.base_color_factor[3]),
                "texture": (
                    torch.as_tensor(
                        np.asarray(self.asset.texture_images[int(material.base_color_texture)], dtype=np.float32)
                        / 255.0,
                        device=self.device,
                    ).unsqueeze(0).contiguous()
                    if material.base_color_texture is not None
                    and int(material.base_color_texture) < len(self.asset.texture_images)
                    and self.asset.texture_images[int(material.base_color_texture)] is not None
                    else None
                ),
                "alpha_mode": str(material.alpha_mode).upper(),
                "alpha_cutoff": float(material.alpha_cutoff),
            }
            for material in self.asset.materials
        )
        self.camera_right = torch.as_tensor(self.camera["right"], device=self.device)
        self.camera_down = torch.as_tensor(self.camera["down"], device=self.device)
        self.camera_up = torch.as_tensor(self.camera["up"], device=self.device)
        self.camera_forward = torch.as_tensor(self.camera["forward"], device=self.device)
        self.camera_offset = torch.as_tensor(self.camera["offset"], device=self.device)
        self.px_per_world = torch.as_tensor(self.camera["pxPerWorld"], device=self.device)
        self.root_basis = torch.stack((self.camera_forward, self.camera_right, self.camera_up), dim=0)
        self.root_rotation_mask = torch.as_tensor(
            [
                1.0 if axis in self.config.root_rotation_axes else 0.0
                for axis in ("camera_forward", "camera_right", "camera_up")
            ],
            dtype=torch.float32,
            device=self.device,
        )
        self.root_translation_mask = torch.as_tensor(
            [
                1.0 if axis in self.config.root_translation_axes else 0.0
                for axis in ("forward", "lateral", "vertical")
            ],
            dtype=torch.float32,
            device=self.device,
        )
        mask = torch.zeros(len(self.asset.nodes), dtype=torch.float32, device=self.device)
        if self.active_node_indices:
            mask[list(self.active_node_indices)] = 1.0
        self.active_node_mask = mask

    def _root_translation_axis_mask_tensor(self, axes: tuple[str, ...]) -> Any:
        import torch

        allowed = {str(axis) for axis in axes}
        return torch.as_tensor(
            [
                1.0 if axis in allowed else 0.0
                for axis in ("forward", "lateral", "vertical")
            ],
            dtype=torch.float32,
            device=self.device,
        )

    def _bind_joint_heads(self) -> dict[str, list[float]]:
        import torch

        zeros = torch.zeros(
            (1, len(self.asset.nodes), 3),
            dtype=torch.float32,
            device=self.device,
        )
        worlds = self._forward_kinematics(zeros, bone_mask=self.active_node_mask)
        heads: dict[str, list[float]] = {}
        for index, node in enumerate(self.asset.nodes):
            position = worlds[0, index, :3, 3].detach().cpu().tolist()
            heads[node.name] = [float(part) for part in position]
        return heads

    def _resolve_search_bones(self) -> None:
        from pose_fit_auto import filter_search_bones

        skinned = [self.node_names[index] for index in self.active_node_indices]
        if not skinned:
            raise RuntimeError("gpu cascade found no skinned joints")
        requested = [str(name) for name in self.config.search_bones]
        unknown = [name for name in requested if name not in self.node_index]
        if unknown:
            raise ValueError(f"search_bones contains unknown nodes: {unknown}")
        skinned_set = set(self.active_node_indices)
        not_skinned = [name for name in requested if self.node_index[name] not in skinned_set]
        if not_skinned:
            raise ValueError(f"search_bones contains non-skinned joints: {not_skinned}")
        from cascade_bone_order import validate_cascade_bone_order_mode

        mode = validate_cascade_bone_order_mode(str(self.config.bone_order_mode))
        if mode == "asset":
            ordered_names = list(skinned)
        else:
            ordered_names = sorted(
                skinned,
                key=lambda name: (self.node_depths[self.node_index[name]], self.node_index[name]),
            )
        if requested and not bool(self.config.include_unlisted_search_bones):
            ordered_names = [name for name in requested]
        elif requested:
            preferred = [name for name in requested if name in set(ordered_names)]
            rest = [name for name in ordered_names if name not in set(preferred)]
            ordered_names = preferred + rest
        parents = {
            node.name: None if node.parent is None else self.asset.nodes[int(node.parent)].name
            for node in self.asset.nodes
        }
        heads = self._bind_joint_heads()
        selected = set(ordered_names)
        children: dict[str, list[str]] = {name: [] for name in ordered_names}
        for name in ordered_names:
            parent = parents.get(name)
            if parent in selected:
                children[parent].append(name)
        descendant_count: dict[str, int] = {}

        def desc(name: str) -> int:
            if name not in descendant_count:
                descendant_count[name] = sum(1 + desc(child) for child in children.get(name, []))
            return descendant_count[name]

        for name in ordered_names:
            desc(name)
        bone_length = {}
        for name in ordered_names:
            parent = parents.get(name)
            if not parent or parent not in heads or name not in heads:
                bone_length[name] = 0.0
                continue
            a = heads[name]
            b = heads[parent]
            bone_length[name] = float(
                ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5
            )
        filtered = filter_search_bones(
            ordered_names,
            descendant_count=descendant_count,
            bone_length=bone_length,
            skip_tiny=bool(self.config.skip_tiny_bones),
            min_leaf_length_frac=float(self.config.min_leaf_length_frac),
        )
        if not filtered:
            raise RuntimeError(
                "gpu cascade skip_tiny_bones removed every skinned joint; "
                "set skip_tiny_bones=False or lower min_leaf_length_frac"
            )
        lengths = [float(bone_length.get(name, 0.0)) for name in filtered]
        positive = sorted(value for value in lengths if value > 1e-8)
        median = positive[len(positive) // 2] if positive else 0.0
        fine_cut = float(self.config.fine_only_leaf_length_frac) * median
        coarse: list[str] = []
        fine_only: list[str] = []
        for name in filtered:
            is_leaf = int(descendant_count.get(name, 0)) == 0
            short = median > 1e-8 and float(bone_length.get(name, 0.0)) < fine_cut
            if is_leaf and short and float(self.config.fine_only_leaf_length_frac) > 0.0:
                fine_only.append(name)
            else:
                coarse.append(name)
        if not coarse:
            coarse = list(filtered)
            fine_only = []
        fine_names = list(coarse) + [name for name in fine_only if name not in set(coarse)]
        self.search_node_indices = tuple(self.node_index[name] for name in coarse)
        self.fine_node_indices = tuple(self.node_index[name] for name in fine_names)
        self.search_bone_names = tuple(coarse)
        self.fine_bone_names = tuple(fine_names)
        self._bone_length_by_index = {
            int(self.node_index[name]): float(bone_length.get(name, 0.0))
            for name in filtered
        }
        self._skinned_children = {
            int(self.node_index[name]): [
                int(self.node_index[child]) for child in children.get(name, [])
            ]
            for name in ordered_names
        }
        filtered_set = set(filtered)
        self._search_parents = {
            self.node_index[name]: (
                self.node_index[parents[name]]
                if parents.get(name) in filtered_set
                else None
            )
            for name in filtered
        }
        print(
            "GPU cascade bones: "
            f"skinned={len(skinned)} search={len(coarse)} "
            f"fineOnly={len(fine_only)} skipTiny={bool(self.config.skip_tiny_bones)} "
            f"order={mode} "
            f"scorePack={joint_score_hyps_per_launch(pose_budget=int(self.config.joint_score_raster_batch), frame_count=max(1, len(self.frame_indices)))}hyps"
            f"x{max(1, len(self.frame_indices))}fr"
            f"/{int(self.config.joint_score_raster_batch)}slots",
            flush=True,
        )

    def _skinned_descendant_indices(self, bone_index: int) -> tuple[int, ...]:
        root = int(bone_index)
        found: list[int] = []
        stack = [root]
        seen: set[int] = {root}
        while stack:
            current = stack.pop()
            found.append(current)
            for child in self._skinned_children.get(int(current), ()):
                if int(child) in seen:
                    continue
                seen.add(int(child))
                stack.append(int(child))
        return tuple(found)

    def _screen_joint_xy(self, bone_vectors, root_translation, root_rotation):
        import torch

        bounded = self._bounded_bone_vectors(bone_vectors)
        worlds = self._forward_kinematics(bounded, bone_mask=self.active_node_mask)
        points = self._root_transform(
            worlds[:, :, :3, 3],
            root_translation,
            root_rotation,
        )
        screen_x = (
            torch.matmul(points, self.camera_right) * self.px_per_world[0]
            + self.camera_offset[0]
        )
        screen_y = (
            torch.matmul(points, self.camera_down) * self.px_per_world[1]
            + self.camera_offset[1]
        )
        return torch.stack((screen_x, screen_y), dim=-1).detach()

    def _bone_error_driven_scores(self, bones, bone_vectors, root_translation, root_rotation):
        import torch

        occupancy_only = bool(self.config.cheap_joint_probe_occupancy_only)
        bones_in = self._bounded_bone_vectors(bone_vectors)
        root_t = root_translation
        root_r = root_rotation
        eval_kwargs: dict[str, Any] = {
            "bone_mask": self.active_node_mask,
            "occupancy_only": occupancy_only,
        }
        if occupancy_only:
            from cascade_cheap_probe import free_frame_positions

            free = free_frame_positions(
                frame_count=int(bones_in.shape[0]),
                prefix=int(getattr(self.config, "idle_prefix_frames", 0) or 0),
                suffix=int(getattr(self.config, "idle_suffix_frames", 0) or 0),
            )
            index = torch.as_tensor(list(free), dtype=torch.long, device=bones_in.device)
            bones_in = bones_in.index_select(0, index)
            root_t = root_translation.index_select(0, index)
            root_r = root_rotation.index_select(0, index)
            eval_kwargs["frame_indices"] = tuple(
                int(self.frame_indices[int(position)]) for position in free
            )
        components = self.evaluate(
            bones_in,
            root_t,
            root_r,
            **eval_kwargs,
        )
        predicted = components["predictedMasks"].detach()
        target = components["targetMasks"].detach()
        error = (predicted - target).abs()
        mass = {int(index): 0.0 for index in bones}
        area = {int(index): 0.0 for index in bones}
        height = int(error.shape[-2])
        width = int(error.shape[-1])
        for frame_position in range(int(error.shape[0])):
            maps = compute_search_bone_influence_maps(
                self,
                bones_in,
                root_t,
                root_r,
                frame_position=int(frame_position),
                node_indices=bones,
                height=height,
                width=width,
            )
            frame_error = error[frame_position].detach().cpu().numpy()
            for index in bones:
                name = str(self.node_names[int(index)])
                influence = maps[name]
                mass[int(index)] += float((frame_error * influence).sum())
                area[int(index)] += float(influence.sum())
        from cascade_bone_order import area_normalized_scores

        return area_normalized_scores(mass, area)

    def _bone_gradient_magnitude_scores(
        self,
        bones,
        bone_vectors,
        root_translation,
        root_rotation,
        *,
        stage_mask,
    ):
        import torch
        from cascade_bone_order import length_normalized_scores

        with torch.enable_grad():
            bounded_leaf = (
                self._bounded_bone_vectors(bone_vectors.detach())
                .detach()
                .clone()
                .requires_grad_(True)
            )
            components = self.evaluate(
                bounded_leaf,
                root_translation.detach(),
                root_rotation.detach(),
                bone_mask=stage_mask,
            )
            geometry = components["geometryScore"]
            if not bool(torch.isfinite(geometry).all()):
                raise RuntimeError("gradient_magnitude bone order produced a non-finite score")
            geometry.sum().backward()
            grad = bounded_leaf.grad
            if grad is None or not bool(torch.isfinite(grad).all()):
                raise RuntimeError(
                    "gradient_magnitude bone order gradient is missing or not finite"
                )
        magnitude = {}
        length = {}
        for index in bones:
            if int(index) not in self._bone_length_by_index:
                raise RuntimeError(
                    f"gradient_magnitude bone order is missing length for "
                    f"{self.node_names[int(index)]}"
                )
            per_frame = grad[:, int(index), :].detach().norm(dim=-1)
            magnitude[int(index)] = float(per_frame.mean().item())
            length[int(index)] = float(self._bone_length_by_index[int(index)])
        return length_normalized_scores(magnitude, length)

    def _bone_expected_gain_scores(
        self,
        bones,
        bone_vectors,
        root_translation,
        root_rotation,
        *,
        stage_mask,
        evaluation_count: list[int] | None = None,
        abs_weight: float,
        unique_weight: float,
        current_abs,
        current_unique,
        current_col,
    ):
        import torch

        step_deg = float(self.config.joint_step_deg)
        if not math.isfinite(step_deg) or step_deg <= 0.0:
            raise ValueError("expected_gain bone order requires a positive joint_step_deg")
        direction = joint_search_directions(self.config.joint_search_axes, 0)[0]
        joint_limit_rad = math.radians(float(self.config.joint_limit_deg))
        current_raw = bone_vectors.detach()
        frame_count = int(current_raw.shape[0])
        hyps_per = joint_score_hyps_per_launch(
            pose_budget=int(self.config.joint_score_raster_batch),
            frame_count=int(frame_count),
        )
        scores: dict[int, float] = {}
        for start in range(0, len(tuple(bones)), hyps_per):
            chunk = [int(index) for index in bones][start : start + hyps_per]
            stacked = torch.cat(
                [
                    offset_raw_bone_direction(
                        current_raw,
                        bone_index=int(index),
                        direction=direction,
                        delta_rad=math.radians(step_deg),
                        joint_limit_rad=joint_limit_rad,
                        bone_limit_scales=self.bone_limit_scales,
                    )
                    for index in chunk
                ],
                dim=0,
            )
            if evaluation_count is not None:
                evaluation_count[0] += 1
            packed = self.evaluate(
                self._bounded_bone_vectors(stacked),
                root_translation.detach().repeat(len(chunk), 1),
                root_rotation.detach().repeat(len(chunk), 1),
                bone_mask=stage_mask,
            )
            for hyp_index, bone_index in enumerate(chunk):
                row_start = hyp_index * frame_count
                row_stop = row_start + frame_count
                keep = joint_keep_score(
                    absolute_geometry=packed["geometryScore"][row_start:row_stop],
                    unique_geometry=packed["uniqueGeometryQuality"][row_start:row_stop],
                    current_absolute=current_abs,
                    current_unique=current_unique,
                    collision=packed["collisionError"][row_start:row_stop],
                    current_collision=current_col,
                    absolute_gain_weight=float(abs_weight),
                    unique_gain_weight=float(unique_weight),
                    collision_weight=float(self.config.collision_weight),
                    collision_enabled=bool(self.config.collision_enabled),
                    collision_positive_abs_slack=float(self.config.joint_collision_positive_abs_slack),
                )
                if not bool(torch.isfinite(keep).all()):
                    raise RuntimeError(
                        f"expected_gain bone order produced a non-finite keep for "
                        f"{self.node_names[int(bone_index)]}"
                    )
                scores[int(bone_index)] = float(keep.mean().item())
        return scores

    def _bone_temporal_disagreement_scores(self, bones, bone_vectors):
        bounded = self._bounded_bone_vectors(bone_vectors).detach().cpu().numpy()
        scores: dict[int, float] = {}
        for index in bones:
            assignment, unique = cluster_bone_angles(bounded[:, int(index), :])
            del assignment
            scores[int(index)] = float(int(unique.shape[0]) - 1)
        return scores

    def _bone_screen_leverage_scores(self, bones, bone_vectors, root_translation, root_rotation):
        import torch

        xy = self._screen_joint_xy(bone_vectors, root_translation, root_rotation)
        if not bool(torch.isfinite(xy).all()):
            raise RuntimeError("screen_space_leverage joint projections are not finite")
        scores: dict[int, float] = {}
        rad_to_deg = math.pi / 180.0
        for index in bones:
            descendants = self._skinned_descendant_indices(int(index))
            radii = []
            origin = xy[:, int(index), :]
            for descendant in descendants:
                delta = xy[:, int(descendant), :] - origin
                radii.append(delta.norm(dim=-1))
            if not radii:
                raise RuntimeError(f"screen_space_leverage has no descendants for bone {index}")
            farthest = torch.stack(radii, dim=0).max(dim=0).values
            parent = self.parents[int(index)]
            if parent is not None:
                parent_len = (xy[:, int(index), :] - xy[:, int(parent), :]).norm(dim=-1)
                farthest = torch.maximum(farthest, parent_len)
            scores[int(index)] = float(farthest.mean().item()) * rad_to_deg
        if max(scores.values()) <= 0.0:
            raise RuntimeError(
                "screen_space_leverage is zero for every bone; "
                "the skeleton has no projected extent"
            )
        return scores

    def _rank_joint_bones(
        self,
        bones,
        bone_vectors,
        root_translation,
        root_rotation,
        *,
        original_order,
        stage_mask,
        evaluation_count: list[int] | None = None,
        abs_weight: float | None = None,
        unique_weight: float | None = None,
        current_abs=None,
        current_unique=None,
        current_col=None,
        mode_override: str | None = None,
    ) -> tuple[int, ...]:
        from cascade_bone_order import (
            error_leverage_scores,
            is_dynamic_bone_order_mode,
            rank_bones_by_score,
            validate_cascade_bone_order_mode,
        )

        mode = validate_cascade_bone_order_mode(
            str(mode_override if mode_override is not None else self.config.bone_order_mode)
        )
        ordered = tuple(int(index) for index in bones)
        if not ordered:
            raise ValueError("bone ranking requires at least one bone")
        if not is_dynamic_bone_order_mode(mode):
            return ordered
        if mode == "error_driven":
            if evaluation_count is not None:
                evaluation_count[0] += 1
            scores = self._bone_error_driven_scores(
                ordered, bone_vectors, root_translation, root_rotation
            )
            return rank_bones_by_score(ordered, scores, original_order=original_order)
        if mode == "gradient_magnitude":
            if evaluation_count is not None:
                evaluation_count[0] += 1
            scores = self._bone_gradient_magnitude_scores(
                ordered,
                bone_vectors,
                root_translation,
                root_rotation,
                stage_mask=stage_mask,
            )
            return rank_bones_by_score(ordered, scores, original_order=original_order)
        if mode == "expected_gain":
            if current_abs is None or current_unique is None or current_col is None:
                raise RuntimeError("expected_gain bone order requires a current keep baseline")
            scores = self._bone_expected_gain_scores(
                ordered,
                bone_vectors,
                root_translation,
                root_rotation,
                stage_mask=stage_mask,
                evaluation_count=evaluation_count,
                abs_weight=float(
                    self.config.joint_absolute_gain_weight if abs_weight is None else abs_weight
                ),
                unique_weight=float(
                    self.config.joint_unique_gain_weight if unique_weight is None else unique_weight
                ),
                current_abs=current_abs,
                current_unique=current_unique,
                current_col=current_col,
            )
            return rank_bones_by_score(ordered, scores, original_order=original_order)
        if mode == "temporal_disagreement":
            scores = self._bone_temporal_disagreement_scores(ordered, bone_vectors)
            return rank_bones_by_score(ordered, scores, original_order=original_order)
        if mode == "screen_space_leverage":
            scores = self._bone_screen_leverage_scores(
                ordered, bone_vectors, root_translation, root_rotation
            )
            return rank_bones_by_score(ordered, scores, original_order=original_order)
        if mode != "error_leverage":
            raise RuntimeError(f"unhandled dynamic bone_order_mode: {mode}")
        if evaluation_count is not None:
            evaluation_count[0] += 1
        error_scores = self._bone_error_driven_scores(
            ordered, bone_vectors, root_translation, root_rotation
        )
        leverage_scores = self._bone_screen_leverage_scores(
            ordered, bone_vectors, root_translation, root_rotation
        )
        return rank_bones_by_score(
            ordered,
            error_leverage_scores(error_scores, leverage_scores),
            original_order=original_order,
        )

    def _resolve_anatomy_groups(self) -> None:
        from cascade_anatomy_bone_order import anatomy_group_bone_names, load_json

        path = str(self.config.anatomy_groups_catalog_path or "").strip()
        visit = tuple(str(name) for name in self.config.anatomy_group_visit_order)
        if not path and not visit:
            self._anatomy_group_spans = ()
            self._resolve_early_symmetry_maps(None)
            return
        if not path or not visit:
            raise ValueError(
                "anatomy_groups_catalog_path and anatomy_group_visit_order must "
                "both be set to enable anatomy group scheduling"
            )
        catalog = load_json(Path(path))
        search_set = {int(index) for index in self.search_node_indices}
        spans: list[tuple[str, tuple[int, ...]]] = []
        for group_name, bone_names in anatomy_group_bone_names(
            groups_catalog=catalog,
            group_visit_order=visit,
        ):
            indices = tuple(
                self.node_index[name]
                for name in bone_names
                if name in self.node_index and self.node_index[name] in search_set
            )
            if indices:
                spans.append((group_name, indices))
        self._anatomy_group_spans = tuple(spans)
        self._resolve_early_symmetry_maps(catalog if path else None)

    def _resolve_early_symmetry_maps(self, catalog: Mapping[str, Any] | None) -> None:
        from cascade_early_symmetry import (
            build_bilateral_index_pairs,
            build_group_index_sets,
            central_bone_indices,
            secondary_group_names,
            symmetry_catalog_defaults,
        )

        self._early_symmetry_bilateral_pairs: dict[int, int] = {}
        self._early_symmetry_central_indices: frozenset[int] = frozenset()
        self._early_symmetry_secondary_groups: frozenset[str] = frozenset()
        self._early_symmetry_group_indices: dict[str, frozenset[int]] = {}
        self._early_symmetry_group_pairs: list[tuple[str, str]] = []
        if not bool(self.config.early_symmetry_enabled):
            return
        if not self._anatomy_group_spans:
            raise ValueError(
                "early_symmetry_enabled requires anatomy_groups_catalog_path "
                "and anatomy_group_visit_order"
            )
        catalog_defaults = symmetry_catalog_defaults(catalog)
        group_pairs = tuple(self.config.early_symmetry_bilateral_group_pairs)
        if not group_pairs:
            group_pairs = tuple(catalog_defaults["bilateral_group_pairs"])
        central_groups = tuple(self.config.early_symmetry_central_groups)
        if not central_groups:
            central_groups = tuple(catalog_defaults["central_groups"])
        central_axes = tuple(self.config.early_symmetry_central_joint_axes)
        if not central_axes:
            central_axes = tuple(catalog_defaults["central_joint_axes"])
        if not group_pairs:
            raise ValueError(
                "early_symmetry_enabled requires bilateral group pairs in config "
                "or anatomy catalog symmetry.bilateralGroupPairs"
            )
        self._early_symmetry_group_pairs = [
            (str(left), str(right)) for left, right in group_pairs
        ]
        self._early_symmetry_bilateral_pairs = build_bilateral_index_pairs(
            self._anatomy_group_spans,
            group_pairs,
        )
        self._early_symmetry_group_indices = build_group_index_sets(self._anatomy_group_spans)
        self._early_symmetry_secondary_groups = secondary_group_names(group_pairs)
        if central_groups:
            self._early_symmetry_central_indices = central_bone_indices(
                self._anatomy_group_spans,
                central_groups,
            )
        self._early_symmetry_central_axes = tuple(str(axis) for axis in central_axes)

    def _early_symmetry_active(self, visit_index: int) -> bool:
        if not bool(self.config.early_symmetry_enabled):
            return False
        return int(visit_index) < int(self.config.early_symmetry_visit_limit)

    def _early_symmetry_skip_bone(self, bone_index: int) -> bool:
        if not self._anatomy_group_spans:
            return False
        bone_index = int(bone_index)
        for group_name, indices in self._anatomy_group_spans:
            if bone_index in indices and group_name in self._early_symmetry_secondary_groups:
                return True
        return False

    def _early_symmetry_joint_directions(
        self,
        bone_index: int,
        directions: Sequence[tuple[float, float, float]],
    ) -> list[tuple[float, float, float]]:
        from cascade_early_symmetry import filter_joint_directions

        if int(bone_index) not in self._early_symmetry_central_indices:
            return list(directions)
        return filter_joint_directions(
            directions,
            allowed_axes=self._early_symmetry_central_axes,
        )

    def _early_symmetry_mirror_bones_(self, bone_vectors, bone_indices: Sequence[int]) -> None:
        from cascade_early_symmetry import mirror_bilateral_after_bones

        if not self._early_symmetry_bilateral_pairs:
            return
        mirror_bilateral_after_bones(
            bone_vectors,
            bone_indices,
            self._early_symmetry_bilateral_pairs,
        )

    def _early_symmetry_mirror_group_(self, bone_vectors, group_name: str) -> None:
        from cascade_early_symmetry import mirror_group_bones

        for left_name, right_name in self._early_symmetry_group_pairs:
            if str(group_name) != str(left_name):
                continue
            left_indices = sorted(
                self._early_symmetry_group_indices.get(str(left_name), frozenset())
            )
            right_indices = sorted(
                self._early_symmetry_group_indices.get(str(right_name), frozenset())
            )
            if left_indices and right_indices:
                mirror_group_bones(bone_vectors, left_indices, right_indices)
            return

    def _articulated_primary_groups(self) -> frozenset[str]:
        configured = tuple(str(name) for name in self.config.articulated_root_interleave_primary_groups)
        if configured:
            return frozenset(configured)
        if self._anatomy_group_spans:
            from cascade_anatomy_bone_order import CATALOG_TRANSIT_PRIMARY_GROUPS

            return frozenset(CATALOG_TRANSIT_PRIMARY_GROUPS)
        return frozenset()

    def _articulated_visit_groups(self, bone_indices: Sequence[int]) -> list[tuple[str, list[int]]]:
        active = {int(index) for index in bone_indices}
        rank_pos = {
            int(index): position for position, index in enumerate(self.search_node_indices)
        }
        if not self._anatomy_group_spans:
            ordered = sorted(active, key=lambda index: rank_pos.get(int(index), len(rank_pos)))
            return [("all", ordered)]
        groups: list[tuple[str, list[int]]] = []
        for group_name, indices in self._anatomy_group_spans:
            present = [int(index) for index in indices if int(index) in active]
            if present:
                present.sort(key=lambda index: rank_pos.get(int(index), len(rank_pos)))
                groups.append((group_name, present))
        if not groups:
            ordered = sorted(active, key=lambda index: rank_pos.get(int(index), len(rank_pos)))
            return [("all", ordered)]
        return groups

    def _joint_chains_for_bone_set(
        self,
        bone_set: set[int],
        *,
        block_size: int,
    ) -> list[tuple[int, ...]]:
        search_set = set(int(index) for index in bone_set)
        pairs: list[tuple[int, ...]] = []
        for child, parent in self._search_parents.items():
            if parent is None or int(child) not in search_set or int(parent) not in search_set:
                continue
            if block_size == 2:
                pairs.append((int(parent), int(child)))
            else:
                grand = self._search_parents.get(int(parent))
                if grand is None or int(grand) not in search_set:
                    pairs.append((int(parent), int(child)))
                else:
                    pairs.append((int(grand), int(parent), int(child)))
        unique_pairs: list[tuple[int, ...]] = []
        seen: set[tuple[int, ...]] = set()
        rank_pos = {
            int(index): position for position, index in enumerate(self.search_node_indices)
        }
        for chain in sorted(
            pairs,
            key=lambda chain: (
                min(rank_pos.get(int(index), len(rank_pos)) for index in chain),
                self.node_depths[chain[0]],
                chain,
            ),
        ):
            if chain in seen:
                continue
            seen.add(chain)
            unique_pairs.append(chain)
        return unique_pairs

    def _run_joint_chain_combo_pass(
        self,
        chains: Sequence[tuple[int, ...]],
        *,
        stage_label: str,
        tag_prefix: str,
        bone_vectors,
        root_translation,
        root_rotation,
        evaluation_count: list[int],
        started: float,
        progress: bool,
        joint_last_move: dict[int, tuple[tuple[float, float, float], float]],
        consensus_hops: dict[str, int],
        collision_veto_count: list[int],
        branch_groups: list[dict[str, Any]],
        abs_weight: float,
        unique_weight: float,
        min_improvement: float,
        joint_limit_rad: float,
        step_deg: float,
        _keep_score,
        baseline_abs,
        baseline_unique,
        current_collision,
        zeros_keep,
        stage_mask,
        apply_temporal_consensus,
        moved_sink: list[int] | None = None,
    ) -> tuple[Any, Any, Any, Any]:
        import itertools

        import torch

        if not chains:
            return baseline_abs, baseline_unique, current_collision, zeros_keep
        values_per = int(self.config.branch_rescue_values_per_bone)
        stage_mask = self._stage_bone_mask(stage_label)
        frame_count = int(bone_vectors.shape[0])

        def bone_values(bone_index: int) -> tuple[tuple[float, float, float], tuple[float, ...]]:
            recorded = joint_last_move.get(int(bone_index))
            if recorded is not None:
                direction, delta = recorded
                magnitudes = [0.0, float(delta), -float(delta)]
            else:
                if (
                    bool(self.config.early_symmetry_enabled)
                    and self._early_symmetry_active(self._early_symmetry_visit_counter)
                    and int(bone_index) in self._early_symmetry_central_indices
                ):
                    allowed = tuple(self._early_symmetry_central_axes)
                    if "x" in allowed:
                        direction = (1.0, 0.0, 0.0)
                    elif "y" in allowed:
                        direction = (0.0, 1.0, 0.0)
                    else:
                        direction = (0.0, 0.0, 1.0)
                else:
                    direction = (1.0, 0.0, 0.0)
                magnitudes = [0.0, step_deg, -step_deg]
            unique_mag: list[float] = []
            for value in magnitudes:
                if all(abs(value - existing) > 1e-9 for existing in unique_mag):
                    unique_mag.append(float(value))
            unique_mag = unique_mag[:values_per]
            if 0.0 not in unique_mag:
                unique_mag.insert(0, 0.0)
            return direction, tuple(unique_mag)

        with torch.no_grad():
            total_visits = len(chains)
            combo_mean_score = float("nan")
            hyps_per = joint_score_hyps_per_launch(
                pose_budget=int(self.config.joint_score_raster_batch),
                frame_count=int(frame_count),
            )
            for visit, chain in enumerate(chains, start=1):
                specs = [bone_values(index) for index in chain]
                grids = [spec[1] for spec in specs]
                combos = [
                    combo
                    for combo in itertools.product(*grids)
                    if any(abs(float(value)) > 1e-12 for value in combo)
                ]
                if not combos:
                    continue
                raw_choices = [bone_vectors.detach().clone()]
                keep_choices = [zeros_keep]
                current_raw = bone_vectors.detach().clone()
                for start in range(0, len(combos), hyps_per):
                    chunk = combos[start : start + hyps_per]
                    stacked_parts = []
                    for combo in chunk:
                        posed = current_raw
                        for bone_index, spec, delta_deg in zip(chain, specs, combo):
                            if abs(float(delta_deg)) <= 1e-12:
                                continue
                            posed = offset_raw_bone_direction(
                                posed,
                                bone_index=int(bone_index),
                                direction=spec[0],
                                delta_rad=math.radians(float(delta_deg)),
                                joint_limit_rad=joint_limit_rad,
                                bone_limit_scales=self.bone_limit_scales,
                            )
                        stacked_parts.append(posed)
                    stacked_raw = torch.cat(stacked_parts, dim=0)
                    evaluation_count[0] += 1
                    components = self.evaluate(
                        self._bounded_bone_vectors(stacked_raw),
                        root_translation.detach().repeat(len(chunk), 1),
                        root_rotation.detach().repeat(len(chunk), 1),
                        bone_mask=stage_mask,
                    )
                    packed_abs = components["geometryScore"]
                    packed_unique = components["uniqueGeometryQuality"]
                    packed_col = components["collisionError"]
                    for hyp_index in range(len(chunk)):
                        start_row = hyp_index * frame_count
                        abs_s = packed_abs[start_row : start_row + frame_count]
                        unique_s = packed_unique[start_row : start_row + frame_count]
                        col_s = packed_col[start_row : start_row + frame_count]
                        keep_choices.append(
                            _keep_score(
                                abs_s,
                                unique_s,
                                col_s,
                                abs_weight=abs_weight,
                                unique_weight=unique_weight,
                                current_abs=baseline_abs,
                                current_unique=baseline_unique,
                                current_col=current_collision,
                                collision_enabled=bool(self.config.collision_enabled),
                            )
                        )
                        raw_choices.append(
                            stacked_raw[start_row : start_row + frame_count].detach().clone()
                        )
                blended, winner, _chosen = gather_per_frame_winners(
                    raw_choices,
                    keep_choices,
                    min_improvement=min_improvement,
                )
                winner = self._lock_still_sprite_winner(winner)
                winner = self._lock_idle_bookend_winner(
                    winner, int(getattr(self.config, "idle_prefix_frames", 0) or 0)
                )
                self._copy_still_leading_(blended)
                moved = sum(int(choice) != 0 for choice in winner.detach().cpu().tolist())
                consensus_moved = 0
                if moved:
                    bone_vectors.copy_(blended)
                    if self._early_symmetry_active(self._early_symmetry_visit_counter):
                        self._early_symmetry_mirror_bones_(bone_vectors, [int(index) for index in chain])
                    self._commit_live_pose_(bone_vectors, root_translation, root_rotation)
                    post = self.evaluate(
                        self._bounded_bone_vectors(bone_vectors),
                        root_translation,
                        root_rotation,
                        bone_mask=stage_mask,
                    )
                    evaluation_count[0] += 1
                    baseline_abs = post["geometryScore"].detach().clone()
                    baseline_unique = post["uniqueGeometryQuality"].detach().clone()
                    current_collision = post["collisionError"].detach().clone()
                    zeros_keep = torch.zeros_like(baseline_abs)
                    combo_mean_score = float(post["score"].mean().item())
                    if moved_sink is not None:
                        moved_sink.extend(int(index) for index in chain)
                names = ",".join(self.node_names[index] for index in chain)
                branch_groups.append(
                    {
                        "bones": [self.node_names[index] for index in chain],
                        "kind": "articulated_multi",
                        "group": tag_prefix,
                    }
                )
                if progress:
                    extra = f" nConsensus={consensus_moved}" if consensus_moved else ""
                    score_text = (
                        f"{combo_mean_score:.5f}"
                        if math.isfinite(combo_mean_score)
                        else "hold"
                    )
                    print(
                        f"gpu {tag_prefix} {visit}/{total_visits}: "
                        f"score={score_text} "
                        f"bones={names} nMoved={moved} "
                        f"evals={evaluation_count[0]} "
                        f"elapsed={time.perf_counter() - started:.1f}s{extra}",
                        flush=True,
                    )
                if moved:
                    self._preview_clip_pose(
                        bone_vectors,
                        root_translation,
                        root_rotation,
                        f"{tag_prefix} {names}",
                        force=False,
                    )
        return baseline_abs, baseline_unique, current_collision, zeros_keep

    def _node_depth(self, index: int) -> int:
        depth = 0
        seen: set[int] = set()
        parent = self.asset.nodes[index].parent
        while parent is not None:
            if int(parent) in seen:
                raise ValueError("GLB node hierarchy contains a cycle")
            seen.add(int(parent))
            depth += 1
            parent = self.asset.nodes[int(parent)].parent
        return depth

    def _build_fk_levels(self) -> None:
        """Group nodes by hierarchy depth so world matrices can be batched.

        The previous walk issued one ``matmul`` per node from Python. Fifty
        sequential tiny kernels dominate a 96x86 depth raster of a 7k-triangle
        crusader. Depth layers keep the same parent-then-child product.
        """
        import torch

        max_depth = max(int(depth) for depth in self.node_depths) if self.node_depths else 0
        levels: list[tuple[Any, Any]] = []
        for depth in range(1, max_depth + 1):
            children = [index for index, node_depth in enumerate(self.node_depths) if int(node_depth) == depth]
            if not children:
                continue
            parents = [int(self.parents[index]) for index in children]
            if any(self.parents[index] is None for index in children):
                raise ValueError("FK depth grouping found a parentless child")
            child_set = set(children)
            if any(parent in child_set for parent in parents):
                raise ValueError("FK depth grouping overlapped parent and child at the same depth")
            levels.append(
                (
                    torch.as_tensor(children, dtype=torch.long, device=self.device),
                    torch.as_tensor(parents, dtype=torch.long, device=self.device),
                )
            )
        self._fk_levels = tuple(levels)

    def _stage_bone_mask(self, stage: str):
        import torch

        if not self.config.hierarchical_unlock_enabled or stage in {"root", "root_refit", "mid", "fine"}:
            return self.active_node_mask
        mask = self.active_node_mask.clone()
        max_depth = int(self.config.hierarchical_proximal_depth)
        for index, depth in enumerate(self.node_depths):
            if depth > max_depth:
                mask[index] = 0.0
        return mask

    def _build_grid(self) -> None:
        import torch

        width, height = (int(value) for value in self.config.resolution)
        yy, xx = torch.meshgrid(
            torch.arange(height, dtype=torch.float32, device=self.device),
            torch.arange(width, dtype=torch.float32, device=self.device),
            indexing="ij",
        )
        self.grid = torch.stack((xx.reshape(-1), yy.reshape(-1)), dim=-1)

    def _forward_kinematics(self, bone_vectors, bone_mask=None):
        import torch

        batch = int(bone_vectors.shape[0])
        mask = self.active_node_mask if bone_mask is None else bone_mask
        bone_vectors = bone_vectors * mask.view(1, -1, 1)
        delta = _axis_angle_matrix(bone_vectors)
        scale = self.scale_matrices.unsqueeze(0).expand(batch, -1, -1, -1)
        local_rotation = torch.matmul(self.base_rotations.unsqueeze(0), delta)
        local = torch.zeros((batch, len(self.asset.nodes), 4, 4), dtype=torch.float32, device=self.device)
        local[..., 3, 3] = 1.0
        local[..., :3, :3] = torch.matmul(local_rotation, scale)
        local[..., :3, 3] = self.translations.unsqueeze(0)
        world = local
        for children, parents in self._fk_levels:
            child_world = torch.matmul(world[:, parents], world[:, children])
            world = world.clone()
            world[:, children] = child_world
        return world

    def _bounded_bone_vectors(self, raw_vectors):
        import torch

        return (
            torch.tanh(raw_vectors)
            * math.radians(float(self.config.joint_limit_deg))
            * self.bone_limit_scales.view(1, -1, 1)
        )

    def _bind_bone_directions_np(self) -> np.ndarray:
        """World-space bind bone axes: parent→child, or local +Y on leaves."""
        import torch

        node_count = len(self.asset.nodes)
        zeros = torch.zeros((1, node_count, 3), dtype=torch.float32, device=self.device)
        worlds = self._forward_kinematics(zeros)[0].detach().cpu().numpy()
        origins = worlds[:, :3, 3]
        children: list[list[int]] = [[] for _ in range(node_count)]
        for child, parent in enumerate(self.parents):
            if parent is None:
                continue
            children[int(parent)].append(int(child))
        directions = np.zeros((node_count, 3), dtype=np.float64)
        for index in range(node_count):
            kids = children[index]
            if kids:
                axis = np.mean(origins[np.asarray(kids)] - origins[index], axis=0)
            else:
                axis = worlds[index, :3, :3] @ np.asarray((0.0, 1.0, 0.0), dtype=np.float64)
            norm = float(np.linalg.norm(axis))
            if norm <= 1e-8:
                continue
            directions[index] = axis / norm
        return directions

    def _apply_cascade_physics_smooth(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
        *,
        progress: bool,
    ) -> dict[str, Any]:
        """Rewrite pose Parameters after fine. No sprite or geometry scoring."""
        import torch
        from cascade_physics_smooth import smooth_cascade_clip

        config = self.config.physics_smooth_config()
        if not bool(config.enabled):
            return {"enabled": False, "outlierBoneFrames": 0, "outlierRootFrames": 0}

        with torch.no_grad():
            bones = (
                self._bounded_bone_vectors(bone_vectors)
                .detach()
                .cpu()
                .numpy()
                .astype(np.float64)
            )
            translation_limit = float(self.config.root_translation_limit_body_lengths)
            translation = (
                (torch.tanh(root_translation) * translation_limit)
                .detach()
                .cpu()
                .numpy()
                .astype(np.float64)
            )
            rotation = (
                self._bounded_root_rotation(root_rotation)
                .detach()
                .cpu()
                .numpy()
                .astype(np.float64)
            )
            smoothed_bones, smoothed_translation, smoothed_rotation, report = smooth_cascade_clip(
                bones,
                translation,
                rotation,
                config=config,
                bone_depths=np.asarray(self.node_depths, dtype=np.int32),
                bind_directions=self._bind_bone_directions_np(),
            )
            bone_limits = (
                math.radians(float(self.config.joint_limit_deg))
                * self.bone_limit_scales.detach().cpu().numpy()[None, :, None]
            )
            if np.any(bone_limits <= 0.0):
                raise ValueError("joint limits must be positive before physics inverse")
            if translation_limit <= 0.0:
                raise ValueError("root translation limit must be positive before physics inverse")
            smoothed_bones = np.clip(smoothed_bones, -bone_limits * 0.999, bone_limits * 0.999)
            smoothed_translation = np.clip(
                smoothed_translation,
                -translation_limit * 0.999,
                translation_limit * 0.999,
            )
            center, _half_range = self._root_rotation_center_half()
            axis_halves = self._root_rotation_axis_half_radians()
            smoothed_rotation = np.clip(
                smoothed_rotation,
                float(center) - axis_halves * 0.999,
                float(center) + axis_halves * 0.999,
            )
            raw_bones = np.arctanh(smoothed_bones / bone_limits).astype(np.float32)
            raw_translation = np.arctanh(smoothed_translation / translation_limit).astype(np.float32)
            raw_rotation = self._root_rotation_raw_inverse(smoothed_rotation)
            commit_pose_parameter_(
                bone_vectors,
                torch.as_tensor(raw_bones, dtype=bone_vectors.dtype, device=bone_vectors.device),
            )
            commit_pose_parameter_(
                root_translation,
                torch.as_tensor(
                    raw_translation,
                    dtype=root_translation.dtype,
                    device=root_translation.device,
                ),
            )
            commit_pose_parameter_(
                root_rotation,
                torch.as_tensor(
                    raw_rotation,
                    dtype=root_rotation.dtype,
                    device=root_rotation.device,
                ),
            )
            self._commit_live_pose_(bone_vectors, root_translation, root_rotation)
        if progress:
            print(
                f"gpu physics nOutliers={report['outlierBoneFrames']} "
                f"nRoot={report['outlierRootFrames']} "
                f"peakDeg {report['peakBoneDegBefore']:.1f}->{report['peakBoneDegAfter']:.1f} "
                f"rmsAccel {report['rmsBoneAccelBefore']:.4f}->{report['rmsBoneAccelAfter']:.4f}",
                flush=True,
            )
        return report

    def _run_anatomy_head_pin(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
        *,
        evaluation_count: list[int],
        progress: bool,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Pin neck/head per frame using anatomical box detection on target sprites."""
        import torch

        from anatomy_detect_keypoints import (
            anatomy_keypoints_by_frame_index,
            build_anatomy_keypoints_payload,
            write_anatomy_keypoints,
        )

        if not bool(self.config.anatomy_head_pin_enabled):
            return {"enabled": False}
        if not self.config.optimize_bones:
            return {"enabled": True, "skipped": True, "reason": "optimize_bones=False"}

        roles_path = str(self.config.anatomy_head_pin_bone_roles_path or "").strip()
        if roles_path:
            bone_roles = load_ik_bone_roles(Path(roles_path))
        else:
            bone_roles = load_ik_bone_roles(
                Path(__file__).resolve().parent / "bone_roles_h3_roc_smartrig.json"
            )
        depth_paths = getattr(self, "target_depth_paths", None)
        payload = build_anatomy_keypoints_payload(
            frame_indices=self.frame_indices,
            target_paths=self.target_paths,
            target_depth_paths=depth_paths,
            parts=tuple(str(part) for part in self.config.anatomy_head_pin_parts),
        )
        keypoints = anatomy_keypoints_by_frame_index(payload)
        if output_dir is not None:
            write_anatomy_keypoints(Path(output_dir) / "anatomy_head_keypoints.json", payload)
        if not keypoints:
            raise RuntimeError(
                "anatomy head pin found no detectable head boxes on any clip frame; "
                f"missing={payload.get('missingFrameIndices')}"
            )
        chains = ik_chains_from_bone_roles(bone_roles, self.node_index, self.parents)
        allowed_chain_indices = {
            int(self.node_index[name])
            for name in self.config.anatomy_head_pin_chain_bones
            if str(name) in self.node_index
        }
        if not allowed_chain_indices:
            raise ValueError(
                "anatomy_head_pin_chain_bones matched no skeleton nodes on the loaded GLB"
            )
        filtered_chains: list[tuple[list[int], str, int]] = []
        for chain_indices, target_joint, end_index in chains:
            narrowed = [
                int(index)
                for index in chain_indices
                if int(index) in allowed_chain_indices
            ]
            if not narrowed:
                continue
            filtered_chains.append((narrowed, str(target_joint), int(end_index)))
        if not filtered_chains:
            raise RuntimeError(
                "anatomy head pin found no IK chains after cervical bone filter; "
                f"roles={list(bone_roles.keys())} chain_bones={list(self.config.anatomy_head_pin_chain_bones)}"
            )

        prefix_count = int(getattr(self.config, "idle_prefix_frames", 0) or 0)
        skip_idle = bool(self.config.anatomy_head_pin_skip_idle_prefix)
        joint_limit_rad = math.radians(float(self.config.joint_limit_deg))
        max_step_rad = math.radians(float(self.config.anatomy_head_pin_max_step_deg))
        iterations = int(self.config.anatomy_head_pin_iterations)
        require_improvement = bool(self.config.anatomy_head_pin_require_improvement)
        accept_metric = str(self.config.anatomy_head_pin_accept_metric).strip().lower()
        scale_x, scale_y = (float(v) for v in self.camera["rasterScale"])

        def _frame_accept_score(packed, position: int) -> float:
            if accept_metric == "geometry":
                return float(packed["geometryScore"][int(position)].detach().item())
            if accept_metric == "silhouette":
                return float(packed["iou"][int(position)].detach().item())
            return float(packed["score"][int(position)].detach().item())

        bind_bone_vectors = torch.zeros_like(bone_vectors)
        bind_world = self._forward_kinematics(bind_bone_vectors)
        bind_positions = bind_world[0, :, :3, 3]
        reference_depths: dict[int, float] = {}
        for _label, bone_name in (
            (joint_name, mapped)
            for joint_name, mapped in bone_roles.items()
            if mapped in self.node_index
        ):
            bone_index = int(self.node_index[bone_name])
            pos_3d = bind_positions[bone_index]
            sx, sy = _project_world_positions_xy(
                pos_3d,
                self.camera_right,
                self.camera_down,
                self.camera_offset,
                self.px_per_world,
            )
            if self.target_depth is not None and len(self.target_depth) > 0:
                depth_map = self.target_depth[0]
                height, width = depth_map.shape
                px = int(round(sx))
                py = int(round(sy))
                if 0 <= px < width and 0 <= py < height:
                    reference_depths[bone_index] = float(depth_map[py, px])
                else:
                    reference_depths[bone_index] = 0.5
            else:
                reference_depths[bone_index] = 0.5

        def _fk_batch(raw_vectors):
            bounded = self._bounded_bone_vectors(raw_vectors)
            return self._forward_kinematics(bounded)

        frame_reports: list[dict[str, Any]] = []
        pinned = 0
        skipped_missing = 0
        skipped_idle = 0
        reverted = 0

        with torch.no_grad():
            opening = self.evaluate(
                self._bounded_bone_vectors(bone_vectors),
                root_translation,
                root_rotation,
                bone_mask=self.active_node_mask,
            )
        evaluation_count[0] += 1
        mean_before = float(opening["score"].mean().item())

        for frame_position, frame_index in enumerate(self.frame_indices):
            if skip_idle and int(frame_position) < prefix_count:
                skipped_idle += 1
                continue
            if int(frame_index) not in keypoints:
                skipped_missing += 1
                frame_reports.append(
                    {
                        "frameIndex": int(frame_index),
                        "skipped": True,
                        "reason": "no_head_detection",
                    }
                )
                continue
            joints_2d = keypoints[int(frame_index)]
            depth_map = None
            if self.target_depth is not None and frame_position < len(self.target_depth):
                depth_map = self.target_depth[frame_position]
            before_score = _frame_accept_score(opening, int(frame_position))
            current = bone_vectors[frame_position].clone()
            joints_3d: dict[str, torch.Tensor] = {}
            for joint_name, (x, y) in joints_2d.items():
                if joint_name not in bone_roles:
                    continue
                bone_name = bone_roles[joint_name]
                if bone_name not in self.node_index:
                    continue
                bone_index = int(self.node_index[bone_name])
                raster_x = float(x) * float(scale_x)
                raster_y = float(y) * float(scale_y)
                depth = reference_depths.get(bone_index, 0.5)
                if depth_map is not None:
                    height, width = depth_map.shape
                    px = int(round(raster_x))
                    py = int(round(raster_y))
                    if 0 <= px < width and 0 <= py < height:
                        depth = float(depth_map[py, px])
                joints_3d[joint_name] = ik_unproject_2d_to_3d(
                    raster_x,
                    raster_y,
                    depth,
                    self.camera_right,
                    self.camera_down,
                    self.camera_forward,
                    self.camera_offset,
                    self.px_per_world,
                )
            for chain_indices, target_joint, end_effector_index in filtered_chains:
                if target_joint not in joints_3d:
                    continue
                current = ik_ccd_chain(
                    current,
                    chain_indices,
                    joints_3d[target_joint],
                    end_effector_index,
                    _fk_batch,
                    joint_limit_rad=joint_limit_rad,
                    bone_limit_scales=self.bone_limit_scales,
                    max_iterations=iterations,
                    max_step_rad=max_step_rad,
                )
            trial = bone_vectors.detach().clone()
            trial[int(frame_position)] = current
            with torch.no_grad():
                post = self.evaluate(
                    self._bounded_bone_vectors(trial),
                    root_translation,
                    root_rotation,
                    bone_mask=self.active_node_mask,
                )
            evaluation_count[0] += 1
            after_score = _frame_accept_score(post, int(frame_position))
            accepted = not require_improvement or after_score >= before_score - 1e-9
            if accepted:
                commit_pose_parameter_(bone_vectors[int(frame_position)], current)
                pinned += 1
            else:
                reverted += 1
            frame_reports.append(
                {
                    "frameIndex": int(frame_index),
                    "skipped": False,
                    "accepted": bool(accepted),
                    "scoreBefore": before_score,
                    "scoreAfter": after_score,
                    "joints": list(joints_2d.keys()),
                }
            )

        with torch.no_grad():
            closing = self.evaluate(
                self._bounded_bone_vectors(bone_vectors),
                root_translation,
                root_rotation,
                bone_mask=self.active_node_mask,
            )
        evaluation_count[0] += 1
        mean_after = float(closing["score"].mean().item())
        report = {
            "enabled": True,
            "parts": [str(part) for part in self.config.anatomy_head_pin_parts],
            "acceptMetric": accept_metric,
            "chainBones": [str(bone) for bone in self.config.anatomy_head_pin_chain_bones],
            "meanBefore": mean_before,
            "meanAfter": mean_after,
            "pinnedFrames": pinned,
            "revertedFrames": reverted,
            "skippedMissingDetection": skipped_missing,
            "skippedIdlePrefix": skipped_idle,
            "missingFrameIndices": list(payload.get("missingFrameIndices") or []),
            "frames": frame_reports,
        }
        if progress:
            print(
                "gpu anatomy_head_pin: "
                f"mean={mean_before:.4f}->{mean_after:.4f} "
                f"pinned={pinned} reverted={reverted} "
                f"missing={skipped_missing}",
                flush=True,
            )
        return report

    def _apply_sprite_aligned_motion_keep(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
        *,
        evaluation_count: list[int],
        progress: bool,
    ) -> dict[str, Any]:
        """Keep travel that explains sprite occupancy change; zero the rest.

        Distal bones first, then root rotation, then root translation.
        Frames are decided in time order. Authority is the occupancy
        appear/disappear pairs that this frame actually changes, not
        clip-mean motion. Packed hold tests of later frames are reused
        only while the snapshot is unchanged; a zero rewrite clears that
        cache so a later frame is scored against the held pose.
        """
        import torch
        from cascade_sprite_aligned_motion import (
            SPRITE_ALIGNED_MIN_TRANSLATION,
            SPRITE_ALIGNED_MIN_TRAVEL_RAD,
            hold_raw_bone_at_frame,
            hold_raw_vector_at_frame,
            pair_qualities_for_frame,
            should_keep_local_pairs,
            traveling_frame_indices,
        )

        if not bool(self.config.sprite_aligned_motion_keep_enabled):
            return {
                "enabled": False,
                "keptBoneFrames": 0,
                "heldBoneFrames": 0,
                "keptRootRotationFrames": 0,
                "heldRootRotationFrames": 0,
                "keptRootTranslationFrames": 0,
                "heldRootTranslationFrames": 0,
                "evaluations": 0,
            }
        if evaluation_count is None:
            raise ValueError("sprite-aligned motion keep needs evaluation_count")
        min_improvement = float(self.config.sprite_aligned_motion_keep_min_improvement)
        joint_limit_rad = math.radians(float(self.config.joint_limit_deg))
        translation_limit = float(self.config.root_translation_limit_body_lengths)
        frame_count = int(bone_vectors.shape[0])
        if frame_count < 2:
            raise ValueError("sprite-aligned motion keep needs at least two frames")
        hyps_per = joint_score_hyps_per_launch(
            pose_budget=int(self.config.joint_score_raster_batch),
            frame_count=int(frame_count),
        )
        started_evals = int(evaluation_count[0])
        bone_snap = bone_vectors.detach().clone()
        translation_snap = root_translation.detach().clone()
        rotation_snap = root_rotation.detach().clone()
        baseline_row: list[object | None] = [None]
        report = {
            "enabled": True,
            "authority": "localOccupancyMotionPairs",
            "minImprovement": min_improvement,
            "noPairWorse": True,
            "keptBoneFrames": 0,
            "heldBoneFrames": 0,
            "skippedNoopBoneFrames": 0,
            "keptRootRotationFrames": 0,
            "heldRootRotationFrames": 0,
            "skippedNoopRootRotationFrames": 0,
            "keptRootTranslationFrames": 0,
            "heldRootTranslationFrames": 0,
            "skippedNoopRootTranslationFrames": 0,
            "evaluations": 0,
        }

        def _motion_row(packed, hyp_index: int):
            start = int(hyp_index) * frame_count
            row = packed["motionQuality"][start : start + frame_count]
            if int(row.numel()) != frame_count:
                raise RuntimeError(
                    "sprite-aligned packed motionQuality length "
                    f"{int(row.numel())} != clip {frame_count}"
                )
            if not bool(torch.isfinite(row).all()):
                raise RuntimeError("sprite-aligned occupancy motion is not finite")
            return row.detach().clone()

        def _evaluate_hyps(bone_hyps, translation_hyps, rotation_hyps):
            evaluation_count[0] += 1
            packed = self.evaluate(
                self._bounded_bone_vectors(torch.cat(bone_hyps, dim=0)),
                torch.cat(translation_hyps, dim=0),
                torch.cat(rotation_hyps, dim=0),
                bone_mask=self.active_node_mask,
            )
            if "motionQuality" not in packed:
                raise RuntimeError(
                    "sprite-aligned motion keep requires occupancy motionQuality"
                )
            return packed

        def _ensure_baseline_row():
            if baseline_row[0] is None:
                packed = _evaluate_hyps(
                    [bone_snap],
                    [translation_snap],
                    [rotation_snap],
                )
                baseline_row[0] = _motion_row(packed, 0)
            return baseline_row[0]

        def _decide_series(
            *,
            label: str,
            kept_key: str,
            held_key: str,
            skipped_key: str,
            list_traveling,
            hold_fn,
        ) -> None:
            remaining = [int(frame) for frame in list_traveling()]
            skipped = max(0, frame_count - 1 - len(remaining))
            pending: dict[int, tuple[float, ...]] = {}
            kept_here = 0
            held_here = 0
            while remaining:
                frame = int(remaining[0])
                if frame not in pending:
                    _ensure_baseline_row()
                    chunk = remaining[:hyps_per]
                    hyps = [
                        hold_fn(bone_snap, translation_snap, rotation_snap, int(item))
                        for item in chunk
                    ]
                    packed = _evaluate_hyps(
                        [hyp[0] for hyp in hyps],
                        [hyp[1] for hyp in hyps],
                        [hyp[2] for hyp in hyps],
                    )
                    for hyp_index, item in enumerate(chunk):
                        pending[int(item)] = pair_qualities_for_frame(
                            _motion_row(packed, hyp_index),
                            int(item),
                        )
                keep = should_keep_local_pairs(
                    pair_qualities_for_frame(_ensure_baseline_row(), frame),
                    pending[frame],
                    min_improvement=min_improvement,
                )
                remaining.pop(0)
                if keep:
                    kept_here += 1
                    report[kept_key] = int(report[kept_key]) + 1
                    continue
                held = hold_fn(bone_snap, translation_snap, rotation_snap, frame)
                bone_snap.copy_(held[0])
                translation_snap.copy_(held[1])
                rotation_snap.copy_(held[2])
                held_here += 1
                report[held_key] = int(report[held_key]) + 1
                pending.clear()
                baseline_row[0] = None
                remaining = [
                    int(item) for item in list_traveling() if int(item) > frame
                ]
            report[skipped_key] = int(report[skipped_key]) + skipped
            if progress and (kept_here or held_here):
                print(
                    f"gpu sprite-aligned {label} "
                    f"kept={kept_here} held={held_here} "
                    f"eval={evaluation_count[0]}",
                    flush=True,
                )

        def _hold_bone(bones, translation, rotation, frame: int, bone_index: int):
            return (
                hold_raw_bone_at_frame(
                    bones,
                    bone_index=int(bone_index),
                    frame=int(frame),
                    joint_limit_rad=joint_limit_rad,
                    bone_limit_scales=self.bone_limit_scales,
                ),
                translation,
                rotation,
            )

        def _hold_root_rotation(bones, translation, rotation, frame: int):
            return bones, translation, hold_raw_vector_at_frame(rotation, frame=int(frame))

        def _hold_root_translation(bones, translation, rotation, frame: int):
            return bones, hold_raw_vector_at_frame(translation, frame=int(frame)), rotation

        with torch.no_grad():
            distal_first = sorted(
                (int(index) for index in self.search_node_indices),
                key=lambda index: (-int(self.node_depths[index]), index),
            )
            for bone_index in distal_first:
                bone_name = self.node_names[int(bone_index)]

                def _list_bone_travel(current_bone=int(bone_index)):
                    bounded = self._bounded_bone_vectors(bone_snap)
                    return traveling_frame_indices(
                        bounded[:, current_bone, :],
                        min_travel=SPRITE_ALIGNED_MIN_TRAVEL_RAD,
                    )

                def _hold_this_bone(
                    bones,
                    translation,
                    rotation,
                    frame,
                    current_bone=int(bone_index),
                ):
                    return _hold_bone(bones, translation, rotation, frame, current_bone)

                _decide_series(
                    label=f"bone={bone_name}",
                    kept_key="keptBoneFrames",
                    held_key="heldBoneFrames",
                    skipped_key="skippedNoopBoneFrames",
                    list_traveling=_list_bone_travel,
                    hold_fn=_hold_this_bone,
                )

            def _list_root_rotation_travel():
                return traveling_frame_indices(
                    self._bounded_root_rotation(rotation_snap),
                    min_travel=SPRITE_ALIGNED_MIN_TRAVEL_RAD,
                )

            _decide_series(
                label="rootRotation",
                kept_key="keptRootRotationFrames",
                held_key="heldRootRotationFrames",
                skipped_key="skippedNoopRootRotationFrames",
                list_traveling=_list_root_rotation_travel,
                hold_fn=_hold_root_rotation,
            )

            def _list_root_translation_travel():
                bounded = torch.tanh(translation_snap) * translation_limit
                return traveling_frame_indices(
                    bounded,
                    min_travel=SPRITE_ALIGNED_MIN_TRANSLATION,
                )

            _decide_series(
                label="rootTranslation",
                kept_key="keptRootTranslationFrames",
                held_key="heldRootTranslationFrames",
                skipped_key="skippedNoopRootTranslationFrames",
                list_traveling=_list_root_translation_travel,
                hold_fn=_hold_root_translation,
            )
            commit_pose_parameter_(bone_vectors, bone_snap)
            commit_pose_parameter_(root_translation, translation_snap)
            commit_pose_parameter_(root_rotation, rotation_snap)
            self._commit_live_pose_(bone_vectors, root_translation, root_rotation)
        report["evaluations"] = int(evaluation_count[0]) - started_evals
        if progress:
            print(
                "gpu sprite-aligned "
                f"keptBones={report['keptBoneFrames']} heldBones={report['heldBoneFrames']} "
                f"keptRootRot={report['keptRootRotationFrames']} "
                f"heldRootRot={report['heldRootRotationFrames']} "
                f"keptRootT={report['keptRootTranslationFrames']} "
                f"heldRootT={report['heldRootTranslationFrames']} "
                f"evals={report['evaluations']}",
                flush=True,
            )
        return report

    def _skinned_vertices(self, worlds, primitive: _PrimitiveGPU):
        import torch
        from gpu_mesh_collision import linear_blend_skin_vertices

        positions = primitive.homogeneous_positions
        if primitive.skin_joints is None or primitive.joints is None or primitive.normalized_weights is None:
            return torch.einsum("bkl,nl->bnk", worlds[:, primitive.node], positions)[..., :3]
        return linear_blend_skin_vertices(
            worlds,
            primitive,
            positions,
            primitive.joints,
            primitive.normalized_weights,
        )

    def _root_transform(self, points, root_translation, root_rotation):
        import torch

        # Always apply the bounded root rotation tensor. optimize_root_rotation
        # only gates Adam/search updates; freezing root must still honor a
        # non-identity initial_poses prior (flyer PCA roll, authored attitude).
        root_rotation = self._bounded_root_rotation(root_rotation)
        root_translation = torch.tanh(root_translation) * float(
            self.config.root_translation_limit_body_lengths
        )
        root_rotation = root_rotation * self.root_rotation_mask.view(1, 3)
        root_translation = root_translation * self.root_translation_mask.view(1, 3)
        axis_vectors = self.root_basis.unsqueeze(0) * root_rotation.unsqueeze(-1)
        deltas = _axis_angle_matrix(axis_vectors)
        rotation = torch.matmul(deltas[:, 1], deltas[:, 0])
        rotation = torch.matmul(deltas[:, 2], rotation)
        displacement = torch.einsum("bi,ij->bj", root_translation, self.root_basis)
        centered = points - self.root_pivot.view(1, 1, 3)
        return torch.matmul(centered, rotation.transpose(1, 2)) + self.root_pivot.view(1, 1, 3) + displacement[:, None, :]

    def _root_rotation_center_half(self) -> tuple[float, float]:
        limit = math.radians(float(self.config.root_rotation_limit_optimization_deg))
        minimum = self.config.root_rotation_min_deg
        maximum = self.config.root_rotation_max_deg
        if minimum is None or maximum is None:
            return 0.0, limit
        minimum_radians = math.radians(float(minimum))
        maximum_radians = math.radians(float(maximum))
        return (minimum_radians + maximum_radians) * 0.5, (maximum_radians - minimum_radians) * 0.5

    def _root_rotation_axis_half_radians(self) -> np.ndarray:
        from gpu_depth_silhouette_solver import root_rotation_axis_envelopes_deg

        _center, general_half = self._root_rotation_center_half()
        envelopes = root_rotation_axis_envelopes_deg(
            envelope_deg=math.degrees(float(general_half)),
            camera_up_limit_deg=float(self.config.root_rotation_camera_up_limit_deg),
        )
        return np.asarray([math.radians(float(value)) for value in envelopes], dtype=np.float64)

    def _deferred_camera_up_window_deg(self) -> float:
        from gpu_depth_silhouette_solver import root_rotation_axis_envelope_deg

        envelope = root_rotation_axis_envelope_deg(
            "camera_up",
            envelope_deg=float(self.config.root_rotation_limit_deg),
            camera_up_limit_deg=float(self.config.root_rotation_camera_up_limit_deg),
        )
        return min(
            envelope,
            max(
                abs(float(self.config.root_rotation_first_frame_limit_deg)),
                abs(float(self.config.root_rotation_per_frame_limit_deg)),
            ),
        )

    def _root_rotation_search_mask(self, *, camera_up: bool):
        import torch

        mask = self.root_rotation_mask.clone()
        if not bool(camera_up):
            mask[2] = 0.0
        return mask

    def _bounded_root_rotation(self, raw_rotation):
        import torch

        center, _general_half = self._root_rotation_center_half()
        halves = torch.as_tensor(
            self._root_rotation_axis_half_radians(),
            dtype=raw_rotation.dtype,
            device=raw_rotation.device,
        ).view(1, 3)
        return float(center) + halves * torch.tanh(raw_rotation)

    def _root_rotation_raw_inverse(
        self,
        radians_values: np.ndarray,
        *,
        axis_index: int | None = None,
    ) -> np.ndarray:
        center, _general_half = self._root_rotation_center_half()
        return invert_bounded_root_rotation(
            radians_values,
            center=float(center),
            halves=self._root_rotation_axis_half_radians(),
            axis_index=axis_index,
        )

    def render_points(self, bone_vectors, root_translation, root_rotation, bone_mask=None):
        import torch

        worlds = self._forward_kinematics(bone_vectors, bone_mask=bone_mask)
        sample_chunks = []
        for primitive in self.primitives:
            vertices = self._skinned_vertices(worlds, primitive)
            triangle_vertices = vertices[:, primitive.sample_triangles]
            sample_chunks.append(torch.einsum("sc,bscd->bsd", primitive.sample_barycentric, triangle_vertices))
        points = torch.cat(sample_chunks, dim=1) if sample_chunks else torch.zeros((len(bone_vectors), 0, 3), device=self.device)
        points = self._root_transform(points, root_translation, root_rotation)
        projected = torch.stack(
            (
                torch.matmul(points, self.camera_right) * self.px_per_world[0] + self.camera_offset[0],
                torch.matmul(points, self.camera_down) * self.px_per_world[1] + self.camera_offset[1],
            ),
            dim=-1,
        )
        return projected

    def exact_triangle_masks(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
        *,
        bone_mask=None,
    ) -> np.ndarray:
        """Rasterize the complete deformed mesh for hard preview parity.

        This preview-only method uses the same weighted-LBS vertices and root
        transform as the optimizer, then fills every source triangle so the
        displayed mask can be compared directly with Blender's alpha render.
        Exact-mode optimization uses the CUDA raster directly; this helper is
        retained for a hard, CPU-serialized artifact and must not be called
        from the candidate loop.
        """
        import torch

        worlds = self._forward_kinematics(bone_vectors, bone_mask=bone_mask)
        width, height = (int(value) for value in self.config.resolution)
        masks: list[np.ndarray] = []
        with torch.no_grad():
            for batch_index in range(int(bone_vectors.shape[0])):
                projected_parts: list[np.ndarray] = []
                for primitive in self.primitives:
                    vertices = self._skinned_vertices(
                        worlds[batch_index : batch_index + 1], primitive
                    )[0]
                    transformed = self._root_transform(
                        vertices[None],
                        root_translation[batch_index : batch_index + 1],
                        root_rotation[batch_index : batch_index + 1],
                    )[0]
                    projected = torch.stack(
                        (
                            torch.matmul(transformed, self.camera_right) * self.px_per_world[0]
                            + self.camera_offset[0],
                            torch.matmul(transformed, self.camera_down) * self.px_per_world[1]
                            + self.camera_offset[1],
                        ),
                        dim=-1,
                    ).detach().cpu().numpy()
                    triangles = primitive.indices.detach().cpu().numpy()
                    if len(triangles):
                        projected_parts.append(projected[triangles])
                mask = Image.new("L", (width, height), 0)
                draw = ImageDraw.Draw(mask)
                for triangles in projected_parts:
                    for triangle in triangles:
                        points = [
                            (int(round(float(point[0]))), int(round(float(point[1]))))
                            for point in triangle
                        ]
                        if len(set(points)) >= 3:
                            draw.polygon(points, fill=255)
                masks.append(np.asarray(mask, dtype=np.float32) / 255.0)
        return np.stack(masks, axis=0) if masks else np.zeros((0, height, width), dtype=np.float32)

    def soft_raster(self, projected):
        import torch

        batch = int(projected.shape[0])
        width, height = (int(value) for value in self.config.resolution)
        min_distance = torch.full(
            (batch, self.grid.shape[0]),
            float("inf"),
            dtype=projected.dtype,
            device=self.device,
        )
        chunk = int(self.config.raster_point_chunk)
        for start in range(0, int(projected.shape[1]), chunk):
            points = projected[:, start : start + chunk]
            distance = ((points[:, :, None, :] - self.grid[None, None, :, :]) ** 2).sum(dim=-1)
            min_distance = torch.minimum(min_distance, distance.min(dim=1).values)
        mask = torch.exp(-min_distance / (2.0 * float(self.config.raster_sigma_px) ** 2))
        return mask.reshape(batch, height, width).clamp(0.0, 1.0)

    def _score_masks(self, predicted, target):
        import torch

        eps = 1e-6
        intersection = (predicted * target).sum(dim=(-2, -1))
        union = predicted.sum(dim=(-2, -1)) + target.sum(dim=(-2, -1)) - intersection
        iou = intersection / torch.clamp(union, min=eps)
        grid = self.grid.reshape(1, *self.config.resolution[::-1], 2)
        grid_norm = grid / torch.tensor(
            [max(int(self.config.resolution[0]) - 1, 1), max(int(self.config.resolution[1]) - 1, 1)],
            dtype=predicted.dtype,
            device=self.device,
        )
        pred_mass = predicted.sum(dim=(-2, -1)).clamp_min(eps)
        target_mass = target.sum(dim=(-2, -1)).clamp_min(eps)
        pred_center = (predicted[..., None] * grid_norm).sum(dim=(-3, -2)) / pred_mass[..., None]
        target_center = (target[..., None] * grid_norm).sum(dim=(-3, -2)) / target_mass[..., None]
        center_error = torch.linalg.vector_norm(pred_center - target_center, dim=-1).clamp(0.0, 1.0)
        pred_occupancy = (predicted > 0.25).to(predicted.dtype).mean(dim=(-2, -1))
        target_occupancy = (target > 0.5).to(target.dtype).mean(dim=(-2, -1))
        occupancy_error = (pred_occupancy - target_occupancy).abs().clamp(0.0, 1.0)
        score = (
            iou
            - float(self.config.score_centroid_weight) * center_error
            - float(self.config.score_occupancy_weight) * occupancy_error
        )
        return {
            "score": score,
            "iou": iou,
            "centerError": center_error,
            "occupancyError": occupancy_error,
        }

    def _initialize_mesh_collision(self) -> None:
        from gpu_mesh_collision import build_backend_collision_table

        mesh_key = str(getattr(self, "src_glb", "") or "")
        if not mesh_key:
            mesh_key = f"asset:{id(self.asset)}"
        cache_key = (
            mesh_key,
            int(self.config.collision_sample_count),
            int(self.config.collision_geodesic_min_hops),
            float(self.config.collision_margin_body_lengths),
            str(self.device),
        )
        cached = _MESH_COLLISION_TABLE_CACHE.get(cache_key)
        if cached is not None:
            self._collision_table = cached
            report = cached["report"]
            print(
                "GPU mesh collision: cache hit "
                f"samples={report['sampleCount']} pairs={report['pairCount']} "
                f"mesh={mesh_key}",
                flush=True,
            )
            return
        self._collision_table = build_backend_collision_table(
            self,
            sample_count=int(self.config.collision_sample_count),
            geodesic_min_hops=int(self.config.collision_geodesic_min_hops),
            margin_body_lengths=float(self.config.collision_margin_body_lengths),
        )
        _MESH_COLLISION_TABLE_CACHE[cache_key] = self._collision_table
        report = self._collision_table["report"]
        print(
            "GPU mesh collision: "
            f"samples={report['sampleCount']} pairs={report['pairCount']} "
            f"hops>={report['geodesicMinHops']} margin={float(report['margin']):.4f} "
            f"islands={report['rawIslandCount']}->{report['weldedIslandCount']} "
            f"crossComponentPairs={report['crossComponentPairs']} "
            f"weight={float(self.config.collision_weight):.2f}",
            flush=True,
        )

    def _initialize_anatomy_veto(self) -> None:
        from anatomy_probe_veto import load_prop_targets_for_veto, sprite_size_from_prop_coords
        from gpu_mesh_collision import build_backend_collision_table
        from gpu_mesh_strain import build_backend_strain_table

        cfg = self.config
        if bool(cfg.anatomy_veto_strain_enabled):
            self._anatomy_veto_strain_table = build_backend_strain_table(
                self,
                exclusive_weight=float(cfg.anatomy_veto_strain_exclusive_weight),
                min_rest_length_body_lengths=float(
                    cfg.anatomy_veto_strain_min_rest_length_body_lengths
                ),
            )
            report = self._anatomy_veto_strain_table["report"]
            print(
                "GPU anatomy veto strain: "
                f"edges={report['edgeCount']} tol={float(cfg.anatomy_veto_strain_tolerance):.3f} "
                f"slack={float(cfg.anatomy_veto_strain_slack):.3f}",
                flush=True,
            )
        if bool(cfg.anatomy_veto_collision_enabled):
            mesh_key = str(getattr(self, "src_glb", "") or "")
            if not mesh_key:
                mesh_key = f"asset:{id(self.asset)}"
            cache_key = (
                mesh_key,
                int(cfg.collision_sample_count),
                int(cfg.collision_geodesic_min_hops),
                float(cfg.collision_margin_body_lengths),
                str(self.device),
                "anatomy_veto",
            )
            cached = _MESH_COLLISION_TABLE_CACHE.get(cache_key)
            if cached is not None:
                self._anatomy_veto_collision_table = cached
            else:
                self._anatomy_veto_collision_table = build_backend_collision_table(
                    self,
                    sample_count=int(cfg.collision_sample_count),
                    geodesic_min_hops=int(cfg.collision_geodesic_min_hops),
                    margin_body_lengths=float(cfg.collision_margin_body_lengths),
                )
                _MESH_COLLISION_TABLE_CACHE[cache_key] = self._anatomy_veto_collision_table
            report = self._anatomy_veto_collision_table["report"]
            print(
                "GPU anatomy veto collision: "
                f"samples={report['sampleCount']} pairs={report['pairCount']} "
                f"slack={float(cfg.anatomy_veto_collision_slack):.3f}",
                flush=True,
            )
        if bool(cfg.anatomy_veto_prop_enabled):
            coords_path = Path(str(cfg.anatomy_veto_prop_coords_path))
            roles_path = Path(str(cfg.anatomy_veto_bone_roles_path))
            if not coords_path.is_file():
                raise FileNotFoundError(f"anatomy veto prop coords missing: {coords_path}")
            if not roles_path.is_file():
                raise FileNotFoundError(f"anatomy veto bone roles missing: {roles_path}")
            sprite_w, sprite_h = sprite_size_from_prop_coords(coords_path)
            if sprite_w < 1 or sprite_h < 1:
                raise ValueError(
                    "anatomy veto prop coords need spriteSize in author_bundle.json "
                    f"beside {coords_path}"
                )
            raster_w, raster_h = (int(value) for value in self.config.resolution)
            self._anatomy_veto_prop_targets = load_prop_targets_for_veto(
                coords_path,
                bone_roles_path=roles_path,
                node_names=self.node_names,
                clip_frame_indices=self.frame_indices,
                source_sprite_size=(sprite_w, sprite_h),
                raster_size=(raster_w, raster_h),
            )
            print(
                "GPU anatomy veto props: "
                f"frames={len(self._anatomy_veto_prop_targets.frame_indices)} "
                f"joints={len(self._anatomy_veto_prop_targets.joint_node_indices)} "
                f"slackPx={float(cfg.anatomy_veto_prop_slack_px):.1f}",
                flush=True,
            )

    def _anatomy_veto_metrics(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
    ) -> tuple[Any, Any, Any]:
        from anatomy_probe_veto import anatomy_metrics_batch, prop_px_error_batch

        bounded = self._bounded_bone_vectors(bone_vectors)
        strain, collision = anatomy_metrics_batch(
            self,
            bounded,
            strain_table=self._anatomy_veto_strain_table,
            collision_table=self._anatomy_veto_collision_table,
            strain_tolerance=float(self.config.anatomy_veto_strain_tolerance),
        )
        if self._anatomy_veto_prop_targets is None:
            import torch

            prop_px = torch.zeros((int(bounded.shape[0]),), dtype=torch.float32, device=self.device)
        else:
            prop_px = prop_px_error_batch(
                self,
                bounded,
                root_translation,
                root_rotation,
                prop_targets=self._anatomy_veto_prop_targets,
            )
        return strain, collision, prop_px

    def _apply_anatomy_veto_probe_family(
        self,
        raw_choices: Sequence[Any],
        keep_choices: Sequence[Any],
        *,
        baseline_raw,
        root_translation,
        root_rotation,
        anatomy_veto_count: list[int],
    ) -> list[Any]:
        from anatomy_probe_veto import apply_anatomy_veto_to_keep_family, combined_anatomy_delta

        if not bool(self.config.anatomy_veto_enabled):
            return list(keep_choices)
        baseline_strain, baseline_collision, baseline_prop = self._anatomy_veto_metrics(
            baseline_raw,
            root_translation,
            root_rotation,
        )
        cfg = self.config
        anatomy_deltas = []
        for raw in raw_choices:
            strain, collision, prop_px = self._anatomy_veto_metrics(
                raw,
                root_translation,
                root_rotation,
            )
            anatomy_deltas.append(
                combined_anatomy_delta(
                    strain=strain,
                    collision=collision,
                    prop_px=prop_px,
                    baseline_strain=baseline_strain,
                    baseline_collision=baseline_collision,
                    baseline_prop_px=baseline_prop,
                    strain_enabled=bool(cfg.anatomy_veto_strain_enabled),
                    collision_enabled=bool(cfg.anatomy_veto_collision_enabled),
                    prop_enabled=bool(cfg.anatomy_veto_prop_enabled),
                )
            )
        adjusted, stats = apply_anatomy_veto_to_keep_family(
            keep_choices,
            anatomy_deltas=anatomy_deltas,
            dino_tie_band=float(cfg.anatomy_veto_dino_tie_band),
            soft_weight=float(cfg.anatomy_veto_soft_weight),
            strain_slack=float(cfg.anatomy_veto_strain_slack),
            collision_slack=float(cfg.anatomy_veto_collision_slack),
            prop_slack_px=float(cfg.anatomy_veto_prop_slack_px),
            hard_strain_margin=float(cfg.anatomy_veto_hard_strain_margin),
            hard_collision_margin=float(cfg.anatomy_veto_hard_collision_margin),
            hard_prop_margin_px=float(cfg.anatomy_veto_hard_prop_margin_px),
            strain_enabled=bool(cfg.anatomy_veto_strain_enabled),
            collision_enabled=bool(cfg.anatomy_veto_collision_enabled),
            prop_enabled=bool(cfg.anatomy_veto_prop_enabled),
        )
        anatomy_veto_count[0] += int(stats["hardVetoes"])
        return adjusted


    def _initialize_target_rgb(self) -> None:
        import torch
        import torch.nn.functional as F

        textured = any(
            material.get("texture") is not None
            for material in self._gpu_materials
        )
        if not textured:
            raise ValueError(
                "RGB raster is set but this GLB has no base-color textures; "
                "unlit RGB candidates need the painted albedo"
            )
        width, height = (int(value) for value in self.config.resolution)
        frames = []
        missing = []
        for frame in self.frame_indices:
            path = self.target_frame_dir / f"{int(frame):02d}.png"
            if not path.is_file():
                missing.append(path)
                continue
            with Image.open(path) as image:
                rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
            rgb = torch.from_numpy(np.ascontiguousarray(rgba[..., :3], dtype=np.float32) / 255.0)
            rgb = rgb.permute(2, 0, 1).unsqueeze(0)
            rgb = F.interpolate(rgb, size=(height, width), mode="nearest")[0].permute(1, 2, 0)
            frames.append(rgb)
        if missing:
            raise FileNotFoundError(f"target RGB frame(s) are missing: {missing}")
        target_rgb = torch.stack(frames, dim=0).to(device=self.device, dtype=torch.float32)
        if not bool(torch.any(self.target_masks > 0.5).item()):
            raise ValueError("RGB targets have no foreground pixels")
        self.target_rgb = target_rgb
        self._sprite_change_maps = None
        self._committed_pred_rgb = None
        if bool(self.config.joint_keep_sprite_change_gate):
            self._initialize_sprite_change_gate()
        reason = (
            "dinov3_dense"
            if self.config.uses_dinov3_dense_score()
            else (
                "dinov3_geometry_consensus"
                if self.config.uses_dinov3_geometry_consensus()
                else "chroma"
            )
        )
        print(
            f"GPU RGB targets loaded ({reason}, raster={width}x{height})",
            flush=True,
        )

    def _initialize_chroma_targets(self) -> None:
        from gpu_geometry_score import srgb_rgb_to_lab_ab

        if self.target_rgb is None:
            self._initialize_target_rgb()
        self.target_lab_ab = srgb_rgb_to_lab_ab(self.target_rgb)
        width, height = (int(value) for value in self.config.resolution)
        print(
            "GPU chroma: Lab a,b targets loaded "
            f"(weight={float(self.config.chroma_weight):.2f}, "
            f"raster={width}x{height}, "
            f"scale={float(self.config.chroma_error_scale):.0f})",
            flush=True,
        )

    def _initialize_dense_semantic_targets(self) -> None:
        from dense_semantic_features import DenseFeatureScorer
        from roc_semantic_embedding_match import RocSemanticEmbedder

        textured = any(
            material.get("texture") is not None
            for material in self._gpu_materials
        )
        if not textured:
            raise ValueError(
                "dinov3_dense score_mode is set but this GLB has no base-color textures; "
                "unlit RGB candidates need the painted albedo"
            )
        token_present = bool(os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN"))
        if not token_present:
            raise RuntimeError(
                "dinov3_dense score_mode is set, but this process has no HF_TOKEN. "
                "Set the user-scoped HF_TOKEN and start a fresh Python process."
            )
        scorer = DenseFeatureScorer(
            self.config.dense_semantic_model_id,
            family="dino",
            feature_layers=self.config.dense_semantic_feature_layers,
            device=str(self.device),
            local_files_only=True,
        )
        images = []
        missing = []
        for frame in self.frame_indices:
            path = self.target_frame_dir / f"{int(frame):02d}.png"
            if not path.is_file():
                missing.append(path)
                continue
            image = RocSemanticEmbedder.load_image(path)
            if bool(self.config.dense_semantic_subject_crop):
                image = RocSemanticEmbedder.load_subject_image_from_image(
                    image,
                    float(self.config.dense_semantic_subject_padding_frac),
                )
            images.append(image)
        if missing:
            raise FileNotFoundError(f"dinov3_dense target RGB frame(s) are missing: {missing}")
        grids: list[dict[str, Any]] = []
        batch_size = int(self.config.dense_semantic_batch_size)
        for start in range(0, len(images), batch_size):
            extracted = scorer.extract_layers(images[start : start + batch_size])
            count = int(next(iter(extracted.values())).shape[0])
            for local in range(count):
                grids.append(
                    {
                        layer: values[local : local + 1].detach()
                        for layer, values in extracted.items()
                    }
                )
        if len(grids) != len(self.frame_indices):
            raise RuntimeError(
                "dinov3_dense target grid count does not match frames: "
                f"{len(grids)} vs {len(self.frame_indices)}"
            )
        self.dense_semantic_scorer = scorer
        self.dense_semantic_target_grids = grids
        width, height = (int(value) for value in self.config.resolution)
        print(
            "GPU cascade score: dinov3_dense "
            f"model={self.config.dense_semantic_model_id} "
            f"layers={list(self.config.dense_semantic_feature_layers)} "
            f"raster={width}x{height} "
            f"batch={batch_size} "
            f"autograd={int(bool(self.config.dense_semantic_autograd_enabled))} "
            "(profile init remains silhouette; Adam root is off)",
            flush=True,
        )

    def _score_dinov3_dense(
        self,
        predicted_alpha,
        predicted_depth,
        predicted_rgb,
        bone_vectors,
        *,
        frame_positions,
        autograd_enabled: bool = False,
    ):
        import torch
        from roc_semantic_embedding_match import RocSemanticEmbedder

        if self.dense_semantic_scorer is None or not self.dense_semantic_target_grids:
            raise RuntimeError("dinov3_dense score_mode is set but the encoder was not loaded")
        if predicted_rgb is None:
            raise RuntimeError("dinov3_dense score_mode is set but the raster did not return RGB")
        batch = int(predicted_alpha.shape[0])
        if int(frame_positions.numel()) == 1 and batch > 1:
            frame_positions = frame_positions.expand(batch)
        elif int(frame_positions.numel()) != batch:
            raise ValueError(
                "dinov3_dense batch does not match frame_positions: "
                f"poses={batch} frames={int(frame_positions.numel())}"
            )
        qualities = score_dense_semantic_rgb_batch(
            self.dense_semantic_scorer,
            target_grids_by_frame=self.dense_semantic_target_grids,
            predicted_rgb=predicted_rgb,
            frame_positions=frame_positions,
            batch_size=int(self.config.dense_semantic_batch_size),
            window_radius=int(self.config.dense_semantic_local_radius),
            position_weight=float(self.config.dense_semantic_position_weight),
            autograd_enabled=bool(autograd_enabled),
            subject_crop=bool(self.config.dense_semantic_subject_crop),
            subject_padding_frac=float(self.config.dense_semantic_subject_padding_frac),
        )
        zeros = torch.zeros((batch,), dtype=torch.float32, device=predicted_alpha.device)
        target_alpha = self.target_masks.index_select(0, frame_positions)
        return {
            "score": qualities,
            "uniqueScore": qualities,
            "uniqueGeometryQuality": qualities,
            "uniqueGeometryError": 1.0 - qualities,
            "uniqueOccupancyQuality": qualities,
            "uniqueOccupancyError": 1.0 - qualities,
            "geometryScore": qualities,
            "iou": zeros,
            "silhouetteIoU": zeros,
            "depthQuality": zeros,
            "depthError": zeros,
            "depthRobustError": zeros,
            "chromaQuality": zeros,
            "chromaError": zeros,
            "chromaRobustError": zeros,
            "motionQuality": zeros,
            "collisionError": zeros,
            "denseSemanticQuality": qualities,
            "predictedMasks": predicted_alpha,
            "predictedDepth": predicted_depth,
            "targetMasks": target_alpha,
            "targetDepth": (
                self.target_depth.index_select(0, frame_positions)
                if self.target_depth is not None
                else None
            ),
        }

    def _score_dinov3_geometry_consensus(
        self,
        predicted_alpha,
        predicted_depth,
        predicted_rgb,
        bone_vectors,
        *,
        frame_positions,
        collision_weight_override: float | None = None,
        autograd_enabled: bool = False,
    ):
        """Keep score = geometric mean of silhouette IoU and DINOv3 quality.

        Geometry still fills silhouette / depth / chroma / collision fields;
        DINOv3 fills denseSemanticQuality. Keep and Adam use the consensus.
        """
        import torch

        if bool(autograd_enabled):
            raise ValueError(
                "dinov3_geometry_consensus does not support dense_semantic_autograd"
            )
        if self.dense_semantic_scorer is None or not self.dense_semantic_target_grids:
            raise RuntimeError(
                "dinov3_geometry_consensus is set but the encoder was not loaded"
            )
        if predicted_rgb is None:
            raise RuntimeError(
                "dinov3_geometry_consensus is set but the raster did not return RGB"
            )
        geometry = self._score_geometry(
            predicted_alpha,
            predicted_depth,
            predicted_rgb,
            bone_vectors,
            frame_positions=frame_positions,
            collision_weight_override=collision_weight_override,
        )
        batch = int(predicted_alpha.shape[0])
        if int(frame_positions.numel()) == 1 and batch > 1:
            dino_frames = frame_positions.expand(batch)
        elif int(frame_positions.numel()) != batch:
            raise ValueError(
                "dinov3_geometry_consensus batch does not match frame_positions: "
                f"poses={batch} frames={int(frame_positions.numel())}"
            )
        else:
            dino_frames = frame_positions
        dense = score_dense_semantic_rgb_batch(
            self.dense_semantic_scorer,
            target_grids_by_frame=self.dense_semantic_target_grids,
            predicted_rgb=predicted_rgb,
            frame_positions=dino_frames,
            batch_size=int(self.config.dense_semantic_batch_size),
            window_radius=int(self.config.dense_semantic_local_radius),
            position_weight=float(self.config.dense_semantic_position_weight),
            autograd_enabled=False,
            subject_crop=bool(self.config.dense_semantic_subject_crop),
            subject_padding_frac=float(self.config.dense_semantic_subject_padding_frac),
        )
        consensus = dinov3_geometry_consensus_score(
            geometry["silhouetteIoU"],
            dense,
            frame_positions=dino_frames,
        )
        if bool(self.config.collision_enabled):
            collision_weight = (
                float(self.config.collision_weight)
                if collision_weight_override is None
                else float(collision_weight_override)
            )
            consensus = consensus - collision_weight * geometry["collisionError"]
        geometry["score"] = consensus
        geometry["geometryScore"] = consensus
        geometry["uniqueScore"] = consensus
        geometry["uniqueGeometryQuality"] = consensus
        geometry["uniqueGeometryError"] = 1.0 - consensus
        geometry["uniqueOccupancyQuality"] = geometry["silhouetteIoU"]
        geometry["uniqueOccupancyError"] = 1.0 - geometry["silhouetteIoU"]
        geometry["denseSemanticQuality"] = dense
        geometry["denseSemanticUnit"] = dense_semantic_unit_interval(dense)
        return geometry

    def _score_geometry(
        self,
        predicted_alpha,
        predicted_depth,
        predicted_rgb,
        bone_vectors,
        *,
        frame_positions,
        collision_weight_override: float | None = None,
        occupancy_only: bool = False,
        vertex_offsets=None,
    ):
        """Silhouette, Huber depth, Lab chroma, occupancy motion, and collision.

        Predicted occupancy is continuous alpha so cascade Adam can move the
        outline. Boolean 0/1 occupancy is numerically the same arithmetic.
        Occupancy motion is appear/disappear match between consecutive frames
        of the same packed hypothesis. A single-frame batch is a no-pair
        (quality 1). A mixed-frame pack with motion_weight set fails closed.
        ``occupancy_only`` is an explicit cheap-probe mix: silhouette + depth,
        no Lab chroma. Collision still scores when enabled. It is not a
        silent fallback.
        """
        import torch
        from gpu_geometry_score import (
            chroma_quality,
            compose_geometry_score,
            occupancy_motion_quality,
            silhouette_and_depth_quality,
            srgb_rgb_to_lab_ab,
            unique_geometry_quality,
        )
        from gpu_mesh_collision import collision_error_from_table

        # ``frame_positions`` is one index (many poses, one sprite) or one
        # index per pose (clip-wide Adam).

        batch = int(predicted_alpha.shape[0])
        if int(frame_positions.numel()) == 1 and batch > 1:
            target_index = frame_positions.expand(batch)
        elif int(frame_positions.numel()) == batch:
            target_index = frame_positions
        else:
            raise ValueError(
                "geometry score batch does not match frame_positions: "
                f"poses={batch} frames={int(frame_positions.numel())}"
            )
        target_alpha = self.target_masks.index_select(0, target_index)
        target_foreground = (target_alpha > 0.5).to(dtype=predicted_alpha.dtype)
        predicted_occupancy = predicted_alpha.clamp(0.0, 1.0)
        occupancy_only = bool(occupancy_only)
        chroma_weight = 0.0 if occupancy_only else float(self.config.chroma_weight)
        depth_weight = float(self.config.depth_weight)
        if predicted_depth is None:
            raise RuntimeError("cascade geometry scoring requires a filled-triangle depth buffer")
        if self.target_depth is not None:
            geometry = silhouette_and_depth_quality(
                target_foreground=target_foreground,
                predicted_foreground=predicted_occupancy,
                target_depth=self.target_depth.index_select(0, target_index),
                predicted_depth=predicted_depth,
                depth_tolerance=float(self.config.depth_tolerance),
                depth_robust_delta=float(self.config.depth_robust_delta),
            )
        else:
            if depth_weight > 0.0:
                raise RuntimeError("depth_weight is set but target depth was not loaded")
            intersection = (predicted_occupancy * target_foreground).sum(dim=(-2, -1))
            union = (
                predicted_occupancy.sum(dim=(-2, -1))
                + target_foreground.sum(dim=(-2, -1))
                - intersection
            ).clamp_min(1.0)
            zeros = torch.zeros((batch,), dtype=torch.float32, device=self.device)
            geometry = {
                "silhouetteIoU": intersection / union,
                "depthQuality": zeros,
                "depthError": zeros,
                "depthRobustError": zeros,
            }
        zeros = torch.zeros((batch,), dtype=torch.float32, device=predicted_alpha.device)
        if chroma_weight > 0.0:
            if predicted_rgb is None:
                raise RuntimeError("chroma_weight is set but the raster did not return RGB")
            if self.target_lab_ab is None:
                raise RuntimeError("chroma_weight is set but Lab a,b targets were not loaded")
            chroma = chroma_quality(
                target_foreground=target_foreground,
                predicted_foreground=predicted_occupancy,
                target_ab=self.target_lab_ab.index_select(0, target_index),
                predicted_ab=srgb_rgb_to_lab_ab(predicted_rgb),
                chroma_tolerance=float(self.config.chroma_tolerance),
                chroma_robust_delta=float(self.config.chroma_robust_delta),
                chroma_error_scale=float(self.config.chroma_error_scale),
            )
            chroma_quality_value = chroma["chromaQuality"]
            chroma_error = chroma["chromaError"]
            chroma_robust_error = chroma["chromaRobustError"]
        else:
            chroma_quality_value = zeros
            chroma_error = zeros
            chroma_robust_error = zeros
        clip_frames = int(torch.unique(target_index).numel())
        clip_unique = clip_frames >= 2 and batch % clip_frames == 0
        if clip_unique:
            n_hyp = batch // clip_frames
            expected = torch.arange(
                clip_frames,
                device=target_index.device,
                dtype=target_index.dtype,
            ).repeat(n_hyp)
            clip_unique = bool(torch.equal(target_index, expected))
        motion_weight = float(self.config.motion_weight)
        if motion_weight > 0.0:
            if clip_frames < 2:
                motion_quality = torch.ones(
                    (batch,),
                    dtype=torch.float32,
                    device=predicted_alpha.device,
                )
            elif not clip_unique:
                raise RuntimeError(
                    "motion_weight is set but the packed batch is not whole-clip "
                    "hypotheses; occupancy motion is a consecutive-frame term"
                )
            else:
                motion_quality = occupancy_motion_quality(
                    target_foreground=target_foreground,
                    predicted_foreground=predicted_occupancy,
                    clip_frames=clip_frames,
                )["motionQuality"]
                if bool(self.config.motion_exempt_idle_prefix):
                    prefix = max(
                        0,
                        int(getattr(self.config, "idle_prefix_frames", 0) or 0),
                    )
                    if prefix > 0:
                        n_hyp = batch // clip_frames
                        for hyp_index in range(n_hyp):
                            start = hyp_index * clip_frames
                            motion_quality[start : start + prefix] = 1.0
        else:
            motion_quality = zeros
        geometry_score = compose_geometry_score(
            silhouette_iou=geometry["silhouetteIoU"],
            depth_quality=geometry["depthQuality"],
            chroma_quality_value=chroma_quality_value,
            depth_weight=depth_weight,
            silhouette_weight=float(self.config.silhouette_weight),
            chroma_weight=chroma_weight,
            motion_quality=motion_quality,
            motion_weight=motion_weight,
        )
        collision_error = collision_error_from_table(
            self,
            self._collision_table,
            bone_vectors,
            vertex_offsets=vertex_offsets,
        )
        score = geometry_score
        if bool(self.config.collision_enabled):
            collision_weight = (
                float(self.config.collision_weight)
                if collision_weight_override is None
                else float(collision_weight_override)
            )
            score = score - collision_weight * collision_error
        pixel_chroma_error = chroma["pixelChromaError"] if chroma_weight > 0.0 else None
        target_ab_batch = None
        if chroma_weight > 0.0:
            target_ab_batch = self.target_lab_ab.index_select(0, target_index)
        if clip_unique:
            unique_parts = []
            occupancy_parts = []
            error_parts = []
            occupancy_error_parts = []
            n_hyp = batch // clip_frames
            for hyp_index in range(n_hyp):
                start = hyp_index * clip_frames
                stop = start + clip_frames
                chroma_slice = None if pixel_chroma_error is None else pixel_chroma_error[start:stop]
                ab_slice = None if target_ab_batch is None else target_ab_batch[start:stop]
                unique_terms = unique_geometry_quality(
                    target_foreground=target_foreground[start:stop],
                    predicted_foreground=predicted_occupancy[start:stop],
                    pixel_chroma_error=chroma_slice,
                    target_ab=ab_slice,
                    silhouette_weight=float(self.config.silhouette_weight),
                    chroma_weight=chroma_weight,
                )
                unique_parts.append(unique_terms["uniqueGeometryQuality"])
                occupancy_parts.append(unique_terms["uniqueOccupancyQuality"])
                error_parts.append(unique_terms["uniqueGeometryError"])
                occupancy_error_parts.append(unique_terms["uniqueOccupancyError"])
            unique_occupancy = torch.cat(occupancy_parts, dim=0)
            unique_geometry = torch.cat(unique_parts, dim=0)
            unique_error = torch.cat(error_parts, dim=0)
            unique_occupancy_error = torch.cat(occupancy_error_parts, dim=0)
        else:
            unique_occupancy = geometry["silhouetteIoU"]
            unique_geometry = geometry["silhouetteIoU"]
            unique_error = 1.0 - geometry["silhouetteIoU"]
            unique_occupancy_error = unique_error
        unique_score = unique_geometry
        return {
            "score": score,
            "uniqueScore": unique_score,
            "uniqueGeometryQuality": unique_geometry,
            "uniqueGeometryError": unique_error,
            "uniqueOccupancyQuality": unique_occupancy,
            "uniqueOccupancyError": unique_occupancy_error,
            "geometryScore": geometry_score,
            "iou": geometry["silhouetteIoU"],
            "silhouetteIoU": geometry["silhouetteIoU"],
            "depthQuality": geometry["depthQuality"],
            "depthError": geometry["depthError"],
            "depthRobustError": geometry["depthRobustError"],
            "chromaQuality": chroma_quality_value,
            "chromaError": chroma_error,
            "chromaRobustError": chroma_robust_error,
            "motionQuality": motion_quality,
            "collisionError": collision_error,
            "predictedMasks": predicted_alpha,
            "predictedDepth": predicted_depth,
            "targetMasks": target_alpha,
            "targetDepth": (
                self.target_depth.index_select(0, target_index)
                if self.target_depth is not None
                else None
            ),
        }

    def _sdf_error(self, projected, frame_positions):
        import torch
        import torch.nn.functional as F

        if self.target_sdf is None:
            return torch.zeros(projected.shape[0], dtype=projected.dtype, device=self.device)
        width, height = (int(value) for value in self.config.resolution)
        # grid_sample expects normalized x/y coordinates in [-1, 1].
        coords = projected.clone()
        coords[..., 0] = coords[..., 0] / max(width - 1, 1) * 2.0 - 1.0
        coords[..., 1] = coords[..., 1] / max(height - 1, 1) * 2.0 - 1.0
        sample_grid = coords.unsqueeze(2)
        fields = self.target_sdf.index_select(0, frame_positions).unsqueeze(1)
        target = self.target_masks.index_select(0, frame_positions).unsqueeze(1)
        distances = F.grid_sample(fields, sample_grid, mode="bilinear", padding_mode="border", align_corners=True).squeeze(1).squeeze(-1)
        occupancy = F.grid_sample(target, sample_grid, mode="bilinear", padding_mode="zeros", align_corners=True).squeeze(1).squeeze(-1)
        return ((1.0 - occupancy).clamp(0.0, 1.0) * distances / float(self.config.sdf_max_distance_px)).mean(dim=-1)

    def _exact_triangle_raster(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
        bone_mask=None,
        vertex_offsets=None,
    ):
        """Differentiably rasterize the complete posed mesh on CUDA."""
        import torch
        import nvdiffrast.torch as dr

        if self._exact_raster_context is None:
            raise RuntimeError("exact GPU raster evaluation was not initialized")
        worlds = self._forward_kinematics(bone_vectors, bone_mask=bone_mask)
        width, height = (int(value) for value in self.config.resolution)
        vertex_parts = []
        triangle_parts = []
        vertex_offset_cursor = 0
        triangle_offset = 0
        for primitive in self.primitives:
            vertices = self._skinned_vertices(worlds, primitive)
            if vertex_offsets is not None:
                vertex_count = int(vertices.shape[1])
                vertices = vertices + vertex_offsets[:, vertex_offset_cursor : vertex_offset_cursor + vertex_count, :]
                vertex_offset_cursor += vertex_count
            vertices = self._root_transform(vertices, root_translation, root_rotation)
            vertex_parts.append(vertices)
            triangle_parts.append(primitive.indices + triangle_offset)
            triangle_offset += int(vertices.shape[1])
        if not vertex_parts:
            raise ValueError("exact GPU rasterizer found no mesh primitives")
        vertices = torch.cat(vertex_parts, dim=1)
        triangles = torch.cat(triangle_parts, dim=0).to(torch.int32)
        projected = torch.stack(
            (
                torch.matmul(vertices, self.camera_right) * self.px_per_world[0] + self.camera_offset[0],
                torch.matmul(vertices, self.camera_down) * self.px_per_world[1] + self.camera_offset[1],
            ),
            dim=-1,
        )
        clip_x = projected[..., 0] / max(width - 1, 1) * 2.0 - 1.0
        clip_y = 1.0 - projected[..., 1] / max(height - 1, 1) * 2.0
        camera_depth = torch.matmul(vertices, self.camera_forward)
        depth_min = camera_depth.amin(dim=1, keepdim=True)
        depth_max = camera_depth.amax(dim=1, keepdim=True)
        depth_norm = (camera_depth - depth_min) / torch.clamp(depth_max - depth_min, min=1e-6)
        clip = torch.stack((clip_x, clip_y, depth_norm * 2.0 - 1.0, torch.ones_like(clip_x)), dim=-1)
        rast, _ = dr.rasterize(
            self._exact_raster_context,
            clip,
            triangles,
            resolution=[height, width],
            grad_db=False,
        )
        # ``rast[..., 3]`` is the triangle ID, not a coverage value.  Treating
        # it as continuous makes the first triangle look different from every
        # other triangle and, more importantly, gives the optimizer a hard
        # zero-gradient mask.  Antialias a binary coverage color instead.  The
        # resulting edge coverage is still the exact triangle raster, but now
        # supplies nvdiffrast's silhouette-edge derivatives for pose search.
        coverage = (rast[..., 3:4] > 0.0).to(rast.dtype)
        alpha = dr.antialias(coverage, rast, clip, triangles)[..., 0].clamp(0.0, 1.0)
        depth = (1.0 - ((rast[..., 2] + 1.0) * 0.5)).clamp(0.0, 1.0)
        depth = depth * (coverage[..., 0] > 0.0).to(depth.dtype)
        # nvdiffrast returns scanlines bottom-to-top. All target PNGs and the
        # Blender bridge use the conventional top-to-bottom image origin.
        # Normalize that boundary here so every exact GPU consumer sees the
        # same image coordinates rather than an implicit vertical mirror.
        alpha = torch.flip(alpha, dims=(-2,))
        depth = torch.flip(depth, dims=(-2,))
        return alpha, depth

    def exact_triangle_rgb(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
        bone_mask=None,
        vertex_offsets=None,
    ):
        """Rasterize unlit base-color RGB beside the exact alpha/depth buffers.

        This is deliberately a separate path from ``_exact_triangle_raster``:
        the optimizer's cheap geometry score can continue to evaluate every
        candidate without texture sampling, while the semantic interleave can
        request RGB for only a small, frequently refreshed subset of a wave.
        All deformation, projection, triangle coverage, UV interpolation, and
        texture sampling remain on CUDA until the caller explicitly transfers
        the resulting shortlist to PIL/model input.
        """
        import torch
        import torch.nn.functional as F
        import nvdiffrast.torch as dr

        if self._exact_raster_context is None:
            raise RuntimeError("exact GPU raster evaluation was not initialized")
        worlds = self._forward_kinematics(bone_vectors, bone_mask=bone_mask)
        width, height = (int(value) for value in self.config.resolution)
        vertex_parts: list[Any] = []
        triangle_parts: list[Any] = []
        uv_parts: list[Any] = []
        material_ranges: list[tuple[int, int, int | None]] = []
        vertex_offset = 0
        triangle_offset = 0
        deform_offset_cursor = 0
        for primitive in self.primitives:
            vertices = self._skinned_vertices(worlds, primitive)
            if vertex_offsets is not None:
                vertex_count = int(vertices.shape[1])
                vertices = vertices + vertex_offsets[:, deform_offset_cursor : deform_offset_cursor + vertex_count, :]
                deform_offset_cursor += vertex_count
            vertices = self._root_transform(vertices, root_translation, root_rotation)
            triangles = primitive.indices
            vertex_parts.append(vertices)
            triangle_parts.append(triangles + vertex_offset)
            if primitive.texcoords is None:
                uv_parts.append(torch.zeros((vertices.shape[1], 2), dtype=vertices.dtype, device=self.device))
            else:
                uv_parts.append(primitive.texcoords)
            triangle_count = int(triangles.shape[0])
            material_ranges.append((triangle_offset, triangle_offset + triangle_count, primitive.material_index))
            vertex_offset += int(vertices.shape[1])
            triangle_offset += triangle_count
        if not vertex_parts:
            raise ValueError("exact GPU RGB rasterizer found no mesh primitives")
        vertices = torch.cat(vertex_parts, dim=1)
        triangles = torch.cat(triangle_parts, dim=0).to(torch.int32)
        uv_attributes = torch.cat(
            [value.unsqueeze(0).expand(vertices.shape[0], -1, -1) for value in uv_parts], dim=1
        )
        projected = torch.stack(
            (
                torch.matmul(vertices, self.camera_right) * self.px_per_world[0] + self.camera_offset[0],
                torch.matmul(vertices, self.camera_down) * self.px_per_world[1] + self.camera_offset[1],
            ),
            dim=-1,
        )
        clip_x = projected[..., 0] / max(width - 1, 1) * 2.0 - 1.0
        clip_y = 1.0 - projected[..., 1] / max(height - 1, 1) * 2.0
        camera_depth = torch.matmul(vertices, self.camera_forward)
        depth_min = camera_depth.amin(dim=1, keepdim=True)
        depth_max = camera_depth.amax(dim=1, keepdim=True)
        depth_norm = (camera_depth - depth_min) / torch.clamp(depth_max - depth_min, min=1e-6)
        clip = torch.stack((clip_x, clip_y, depth_norm * 2.0 - 1.0, torch.ones_like(clip_x)), dim=-1)
        rast, _ = dr.rasterize(
            self._exact_raster_context,
            clip,
            triangles,
            resolution=[height, width],
            grad_db=False,
        )
        triangle_id = rast[..., 3].to(torch.long) - 1
        covered = triangle_id >= 0
        pixel_uv = dr.interpolate(
            uv_attributes.contiguous(), rast, triangles,
        )[0]
        background = torch.tensor((32.0, 32.0, 32.0), dtype=vertices.dtype, device=self.device) / 255.0
        rgb = background.view(1, 1, 1, 3).expand(vertices.shape[0], height, width, 3).clone()
        alpha = torch.zeros((vertices.shape[0], height, width), dtype=vertices.dtype, device=self.device)
        for start, end, material_index in material_ranges:
            covered_material = covered & (triangle_id >= int(start)) & (triangle_id < int(end))
            if material_index is None:
                color = background.view(1, 1, 1, 3).expand(vertices.shape[0], height, width, 3)
                opacity = torch.ones((vertices.shape[0], height, width), dtype=vertices.dtype, device=self.device)
                alpha_mode = "OPAQUE"
                alpha_cutoff = 0.5
            elif int(material_index) >= len(self._gpu_materials):
                raise ValueError(f"GPU RGB rasterizer has no material {material_index}")
            else:
                material = self._gpu_materials[int(material_index)]
                alpha_mode = str(material["alpha_mode"]).upper()
                alpha_cutoff = float(material["alpha_cutoff"])
                if material["texture"] is None:
                    color = material["factor"].view(1, 1, 1, 3).expand(vertices.shape[0], height, width, 3)
                    opacity = torch.full(
                        (vertices.shape[0], height, width), float(material["alpha"]),
                        dtype=vertices.dtype, device=self.device,
                    )
                else:
                    texture = material["texture"].permute(0, 3, 1, 2).expand(vertices.shape[0], -1, -1, -1)
                    grid = gltf_uv_to_grid_sample(pixel_uv)
                    sampled = F.grid_sample(
                        texture, grid, mode="bilinear", padding_mode="border", align_corners=True,
                    ).permute(0, 2, 3, 1)
                    color = (sampled[..., :3] * material["factor"].view(1, 1, 1, 3)).clamp(0.0, 1.0)
                    opacity = (sampled[..., 3] * float(material["alpha"])).clamp(0.0, 1.0)
            visible = covered_material
            if alpha_mode == "MASK":
                visible = visible & (opacity >= alpha_cutoff)
            rgb = torch.where(visible.unsqueeze(-1), color, rgb)
            alpha = torch.where(visible, opacity if alpha_mode != "OPAQUE" else torch.ones_like(opacity), alpha)
        # Match the exact alpha edge convention. RGB is composited onto the
        # same neutral matte so SigLIP never sees transparent black pixels.
        coverage = covered.unsqueeze(-1).to(vertices.dtype)
        coverage_alpha = dr.antialias(coverage, rast, clip, triangles)[..., 0].clamp(0.0, 1.0)
        alpha = torch.where(alpha > 0.0, alpha * coverage_alpha, coverage_alpha)
        rgb = rgb * alpha.unsqueeze(-1) + background.view(1, 1, 1, 3) * (1.0 - alpha.unsqueeze(-1))
        depth = (1.0 - ((rast[..., 2] + 1.0) * 0.5)).clamp(0.0, 1.0)
        depth = depth * covered.to(depth.dtype)
        return (
            torch.flip(rgb.clamp(0.0, 1.0), dims=(-3,)),
            torch.flip(alpha, dims=(-2,)),
            torch.flip(depth, dims=(-2,)),
        )

    def evaluate(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
        *,
        frame_indices: Sequence[int] | None = None,
        bone_mask=None,
        collision_weight_override: float | None = None,
        dense_semantic_autograd: bool = False,
        occupancy_only: bool = False,
        vertex_offsets=None,
    ) -> dict[str, Any]:
        import torch

        if bool(dense_semantic_autograd) and not (
            self.config.uses_dinov3_dense_score()
            and self.config.dense_semantic_autograd_enabled
        ):
            raise ValueError(
                "dense_semantic_autograd evaluation requires the explicit DINOv3 "
                "autograd config gate"
            )
        occupancy_only = bool(occupancy_only)
        if occupancy_only and (
            self.config.uses_dinov3_dense_score()
            or self.config.uses_dinov3_geometry_consensus()
        ):
            raise ValueError(
                "occupancy_only cheap probes cannot mix DINOv3 score modes"
            )
        frames = self.frame_indices if frame_indices is None else tuple(int(frame) for frame in frame_indices)
        frame_positions = torch.as_tensor(
            [self.frame_indices.index(frame) for frame in frames], dtype=torch.long, device=self.device
        )
        pose_count = int(bone_vectors.shape[0])
        requested = int(frame_positions.numel())
        if requested == 1 and pose_count > 1:
            frame_positions = frame_positions.expand(pose_count)
        elif requested > 1 and pose_count > requested:
            if pose_count % requested != 0:
                raise ValueError(
                    "packed pose batch must be a multiple of the clip length: "
                    f"poses={pose_count} frames={requested}"
                )
            frame_positions = frame_positions.repeat(pose_count // requested)
        if self.config.uses_rgb_raster() and not occupancy_only:
            predicted_rgb, predicted, predicted_depth = self.exact_triangle_rgb(
                bone_vectors,
                root_translation,
                root_rotation,
                bone_mask=bone_mask,
                vertex_offsets=vertex_offsets,
            )
        else:
            predicted, predicted_depth = self._exact_triangle_raster(
                bone_vectors,
                root_translation,
                root_rotation,
                bone_mask=bone_mask,
                vertex_offsets=vertex_offsets,
            )
            predicted_rgb = None
        if self.config.uses_dinov3_dense_score():
            components = self._score_dinov3_dense(
                predicted,
                predicted_depth,
                predicted_rgb,
                bone_vectors,
                frame_positions=frame_positions,
                autograd_enabled=bool(dense_semantic_autograd),
            )
        elif self.config.uses_dinov3_geometry_consensus():
            components = self._score_dinov3_geometry_consensus(
                predicted,
                predicted_depth,
                predicted_rgb,
                bone_vectors,
                frame_positions=frame_positions,
                collision_weight_override=collision_weight_override,
                autograd_enabled=bool(dense_semantic_autograd),
            )
        else:
            components = self._score_geometry(
                predicted,
                predicted_depth,
                predicted_rgb,
                bone_vectors,
                frame_positions=frame_positions,
                collision_weight_override=collision_weight_override,
                occupancy_only=occupancy_only,
                vertex_offsets=vertex_offsets,
            )
        if bool(self.config.joint_keep_sprite_change_gate):
            components = self._apply_sprite_change_gate(
                components,
                predicted_rgb,
                frame_positions,
            )
        components["sdfError"] = torch.zeros_like(components["score"])
        return components

    def _sa_search_node_indices(self) -> tuple[int, ...]:
        min_depth = int(self.config.sa_min_bone_depth)
        return tuple(
            int(index)
            for index in self.search_node_indices
            if int(self.node_depths[int(index)]) >= min_depth
        )

    def _initial_pose_tensors(self, initial_poses: Mapping[int, Mapping[str, Any]] | None):
        import torch

        frame_count = len(self.frame_indices)
        node_count = len(self.asset.nodes)
        vectors = np.zeros((frame_count, node_count, 3), dtype=np.float32)
        root_translation = np.zeros((frame_count, 3), dtype=np.float32)
        root_rotation = np.zeros((frame_count, 3), dtype=np.float32)
        normalized_initial_poses = {
            int(frame): pose for frame, pose in (initial_poses or {}).items()
        }
        for frame_position, frame in enumerate(self.frame_indices):
            pose = normalized_initial_poses.get(frame, {})
            for name, entry in pose.items():
                if name == MOTION_ROOT_KEY and isinstance(entry, Mapping):
                    # Load seed even when optimize_root_translation is False so a
                    # frozen root can hold a non-zero authored translation prior.
                    root_translation[frame_position] = [
                        float(entry.get("forward", 0.0)),
                        float(entry.get("lateral", 0.0)),
                        float(entry.get("vertical", 0.0)),
                    ]
                elif name == MOTION_ROOT_ROTATION_KEY and isinstance(entry, Mapping):
                    # Load seed even when optimize_root_rotation is False so a
                    # frozen root can hold a non-identity attitude prior.
                    root_rotation[frame_position] = [
                        math.radians(float(entry.get(axis, 0.0)))
                        for axis in ("camera_forward", "camera_right", "camera_up")
                    ]
                elif name in self.node_index and self.config.optimize_bones:
                    vectors[frame_position, self.node_index[name]] = _pose_entry_to_xyz(entry)
        def bounded_inverse(values, limit):
            ratio = np.clip(np.asarray(values) / np.asarray(limit), -0.999, 0.999)
            return np.arctanh(ratio).astype(np.float32)
        bone_limits = math.radians(float(self.config.joint_limit_deg)) * self.bone_limit_scales.detach().cpu().numpy()[None, :, None]
        root_rotation_raw = self._root_rotation_raw_inverse(
            np.stack(
                [
                    root_rotation[:, axis_index]
                    for axis_index in range(root_rotation.shape[1])
                ],
                axis=1,
            )
        )
        return (
            torch.nn.Parameter(torch.as_tensor(bounded_inverse(vectors, bone_limits), device=self.device)),
            torch.nn.Parameter(torch.as_tensor(bounded_inverse(root_translation, self.config.root_translation_limit_body_lengths), device=self.device)),
            torch.nn.Parameter(torch.as_tensor(root_rotation_raw, device=self.device)),
        )

    def _translation_search_objective_mean(
        self,
        bounded_bones: Any,
        root_translation: Any,
        root_rotation: Any,
        packed: Mapping[str, Any],
        *,
        image_only: bool = False,
    ) -> float:
        if image_only:
            mean = float(packed["geometryScore"].mean().item())
            if bool(self.config.collision_enabled):
                mean -= float(self.config.collision_weight) * float(
                    packed["collisionError"].mean().item()
                )
            return mean
        if self._velocity_acceleration_only_temporal():
            return self._clip_objective_mean(
                bounded_bones,
                root_translation,
                root_rotation,
                packed,
            )
        return float(packed["score"].mean().item())

    def _translation_hypothesis_objectives(
        self,
        bounded_full: Any,
        root_t_hyps: Any,
        root_r_hyps: Any,
        *,
        count: int,
        frame_count: int,
        image_only: bool = False,
    ) -> list[float]:
        import torch

        bones_flat = bounded_full.unsqueeze(0).expand(count, -1, -1, -1).reshape(
            count * frame_count,
            bounded_full.shape[-2],
            bounded_full.shape[-1],
        )
        root_t_flat = root_t_hyps.reshape(count * frame_count, root_t_hyps.shape[-1])
        root_r_flat = root_r_hyps.reshape(count * frame_count, root_r_hyps.shape[-1])
        packed_all = self.evaluate(
            bones_flat,
            root_t_flat,
            root_r_flat,
            bone_mask=self.active_node_mask,
        )
        objectives: list[float] = []
        for hyp_index in range(count):
            start = hyp_index * frame_count
            end = start + frame_count
            chunk = {
                key: (
                    value[start:end]
                    if isinstance(value, torch.Tensor)
                    and int(value.shape[0]) == count * frame_count
                    else value
                )
                for key, value in packed_all.items()
            }
            objectives.append(
                self._translation_search_objective_mean(
                    bounded_full,
                    root_t_hyps[hyp_index],
                    root_r_hyps[hyp_index],
                    chunk,
                    image_only=image_only,
                )
            )
        return objectives

    def _sprite_screen_plane_profiles_world(self, anchor_position: int) -> Any:
        import torch

        frame_count = int(self.target_masks.shape[0])
        profiles = torch.zeros((frame_count, 3), dtype=torch.float32, device=self.device)
        centroids_y: list[float] = []
        centroids_x: list[float] = []
        for position in range(frame_count):
            mask = self.target_masks[int(position)] > 0.5
            if not bool(mask.any().item()):
                centroids_y.append(0.0)
                centroids_x.append(0.0)
                continue
            coords = torch.nonzero(mask, as_tuple=False)
            ys = coords[:, 0].to(dtype=torch.float32)
            xs = coords[:, 1].to(dtype=torch.float32)
            centroids_y.append(float(ys.mean().item()))
            centroids_x.append(float(xs.mean().item()))
        anchor_cy = float(centroids_y[int(anchor_position)])
        anchor_cx = float(centroids_x[int(anchor_position)])
        px_per_world = float(self.px_per_world.detach().mean().item())
        if not math.isfinite(px_per_world) or px_per_world <= 0.0:
            raise ValueError("px_per_world must be finite and positive for sprite centroid profile")
        for position in range(frame_count):
            profiles[int(position), 1] = (
                float(centroids_x[position]) - anchor_cx
            ) / float(px_per_world)
            profiles[int(position), 2] = (
                anchor_cy - float(centroids_y[position])
            ) / float(px_per_world)
        return profiles

    def _root_translation_hypothesis_search(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
        frame_position: int,
        *,
        progress: bool = False,
        started: float | None = None,
        score_escape: bool = False,
    ) -> None:
        import torch

        if not bool(self.config.optimize_root_translation):
            return
        count = int(self.config.score_escape_translation_hypotheses)
        window_body = float(self.config.score_escape_translation_window_body_lengths)
        translation_limit = float(self.config.root_translation_limit_body_lengths)
        axis_mask = self._root_translation_axis_mask_tensor(
            tuple(str(axis) for axis in self.config.score_escape_translation_axes)
        )
        if float(axis_mask.sum().item()) <= 0.0:
            return
        if int(frame_position) > 0 and bool(self.config.seed_previous_frame):
            center_translation = (
                torch.tanh(root_translation[int(frame_position) - 1].detach())
                * translation_limit
            )
        else:
            center_translation = (
                torch.tanh(root_translation[int(frame_position)].detach())
                * translation_limit
            )
        offsets = root_hypothesis_unit_offsets(count, 3).to(self.device)
        candidate_translation = center_translation.unsqueeze(0) + offsets * float(window_body)
        candidate_translation = candidate_translation * axis_mask.view(1, 3)
        candidate_translation = candidate_translation.clamp(
            -translation_limit,
            translation_limit,
        )
        candidate_translation_raw = torch.atanh(
            torch.clamp(candidate_translation / translation_limit, -0.999, 0.999)
        )
        bounded_full = self._bounded_bone_vectors(bone_vectors.detach())
        frame_count = int(bone_vectors.shape[0])
        root_t_hyps = root_translation.detach().unsqueeze(0).expand(count, -1, -1).clone()
        root_r_hyps = root_rotation.detach().unsqueeze(0).expand(count, -1, -1).clone()
        root_t_hyps[:, int(frame_position)] = candidate_translation_raw
        with torch.no_grad():
            current_packed = self.evaluate(
                bounded_full,
                root_translation.detach(),
                root_rotation.detach(),
                bone_mask=self.active_node_mask,
            )
            current_mean = self._translation_search_objective_mean(
                bounded_full,
                root_translation.detach(),
                root_rotation.detach(),
                current_packed,
            )
        objectives = self._translation_hypothesis_objectives(
            bounded_full,
            root_t_hyps,
            root_r_hyps,
            count=count,
            frame_count=frame_count,
        )
        best = int(max(range(count), key=lambda index: objectives[index]))
        best_mean = float(objectives[best])
        if best_mean <= current_mean + 1e-6:
            if progress:
                elapsed = 0.0 if started is None else time.perf_counter() - started
                axes = ",".join(str(axis) for axis in self.config.score_escape_translation_axes)
                print(
                    f"gpu root-translation frame={self.frame_indices[frame_position]:02d} "
                    f"held (no improvement {best_mean:.5f}<={current_mean:.5f}) "
                    f"windowBody={window_body:.3f} axes={axes} "
                    f"elapsed={elapsed:.1f}s",
                    flush=True,
                )
            return
        root_translation.data[int(frame_position)] = root_t_hyps[best, int(frame_position)]
        if progress:
            elapsed = 0.0 if started is None else time.perf_counter() - started
            axes = ",".join(str(axis) for axis in self.config.score_escape_translation_axes)
            print(
                f"gpu root-translation frame={self.frame_indices[frame_position]:02d} "
                f"best={best_mean:.5f} delta={best_mean - current_mean:+.5f} "
                f"windowBody={window_body:.3f} axes={axes} "
                f"elapsed={elapsed:.1f}s",
                flush=True,
            )

    def _root_transit_correlated_translation_search(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
        transit_positions: Sequence[int],
        *,
        mode: str,
        progress: bool = False,
        started: float | None = None,
    ) -> None:
        import torch

        if not bool(self.config.optimize_root_translation):
            return
        if not transit_positions:
            return
        count = int(self.config.score_escape_translation_hypotheses)
        window_body = float(self.config.score_escape_translation_window_body_lengths)
        translation_limit = float(self.config.root_translation_limit_body_lengths)
        axis_mask = self._root_translation_axis_mask_tensor(
            tuple(str(axis) for axis in self.config.score_escape_translation_axes)
        )
        if float(axis_mask.sum().item()) <= 0.0:
            return
        bounded_full = self._bounded_bone_vectors(bone_vectors.detach())
        frame_count = int(bone_vectors.shape[0])
        prefix_count = int(getattr(self.config, "idle_prefix_frames", 0) or 0)
        transit_positions = [int(position) for position in transit_positions]
        transit_indices = torch.as_tensor(transit_positions, dtype=torch.long, device=self.device)
        transit_len = int(transit_indices.numel())
        image_only = str(mode).strip() == "transit_sprite_centroid"
        offsets = root_hypothesis_unit_offsets(count, 2).to(self.device)
        amplitudes = offsets[:, 0] * float(window_body)
        phase_span = float(self.config.score_escape_translation_wave_phase_span_rad)
        phase_shifts = offsets[:, 1] * float(phase_span)
        if str(mode).strip() == "transit_sprite_centroid":
            base_profiles = self._sprite_screen_plane_profiles_world(prefix_count)
            transit_profiles = base_profiles.index_select(0, transit_indices)
            scaled_profiles = transit_profiles.unsqueeze(0) * amplitudes.unsqueeze(1).unsqueeze(2)
            scaled = scaled_profiles.sum(dim=2)
        elif str(mode).strip() == "transit_uniform":
            waves = torch.ones((count, transit_len), dtype=torch.float32, device=self.device)
            scaled = waves * amplitudes.unsqueeze(1)
        else:
            denom = float(max(transit_len - 1, 1))
            phase_indices = transit_indices.to(dtype=torch.float32) - float(prefix_count)
            base_phase = (2.0 * math.pi * phase_indices / denom).unsqueeze(0)
            waves = torch.sin(base_phase + phase_shifts.unsqueeze(1))
            scaled = waves * amplitudes.unsqueeze(1)
        axis_index = {
            "forward": 0,
            "lateral": 1,
            "vertical": 2,
        }
        root_t_hyps = root_translation.detach().unsqueeze(0).expand(count, -1, -1).clone()
        root_r_hyps = root_rotation.detach().unsqueeze(0).expand(count, -1, -1).clone()
        t_world = torch.zeros(
            (count, frame_count, 3),
            dtype=torch.float32,
            device=self.device,
        )
        for axis_name in self.config.score_escape_translation_axes:
            axis_component = float(axis_mask[int(axis_index[str(axis_name)])].item())
            if axis_component <= 0.0:
                continue
            if str(mode).strip() == "transit_sprite_centroid":
                axis_offset = int(axis_index[str(axis_name)])
                t_world[:, transit_indices, axis_offset] = (
                    scaled_profiles[:, :, axis_offset] * axis_component
                )
            else:
                t_world[:, transit_indices, int(axis_index[str(axis_name)])] = scaled * axis_component
        t_world = t_world.clamp(-translation_limit, translation_limit)
        t_world_raw = torch.atanh(
            torch.clamp(t_world / translation_limit, -0.999, 0.999)
        )
        root_t_hyps[:, transit_indices, :] = t_world_raw[:, transit_indices, :]
        with torch.no_grad():
            current_packed = self.evaluate(
                bounded_full,
                root_translation.detach(),
                root_rotation.detach(),
                bone_mask=self.active_node_mask,
            )
            current_mean = self._translation_search_objective_mean(
                bounded_full,
                root_translation.detach(),
                root_rotation.detach(),
                current_packed,
                image_only=image_only,
            )
        objectives = self._translation_hypothesis_objectives(
            bounded_full,
            root_t_hyps,
            root_r_hyps,
            count=count,
            frame_count=frame_count,
            image_only=image_only,
        )
        best = int(max(range(count), key=lambda index: objectives[index]))
        best_mean = float(objectives[best])
        if best_mean <= current_mean + 1e-6:
            if progress:
                elapsed = 0.0 if started is None else time.perf_counter() - started
                axes = ",".join(str(axis) for axis in self.config.score_escape_translation_axes)
                print(
                    f"gpu root-translation {mode} held "
                    f"(no improvement {best_mean:.5f}<={current_mean:.5f}) "
                    f"windowBody={window_body:.3f} axes={axes} "
                    f"frames={len(transit_positions)} elapsed={elapsed:.1f}s",
                    flush=True,
                )
            return
        root_translation.data.copy_(root_t_hyps[best])
        if progress:
            elapsed = 0.0 if started is None else time.perf_counter() - started
            axes = ",".join(str(axis) for axis in self.config.score_escape_translation_axes)
            print(
                f"gpu root-translation {mode} best={best_mean:.5f} "
                f"delta={best_mean - current_mean:+.5f} "
                f"windowBody={window_body:.3f} axes={axes} "
                f"frames={len(transit_positions)} elapsed={elapsed:.1f}s",
                flush=True,
            )

    def _root_hypothesis_start(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
        frame_position: int,
        *,
        progress: bool = False,
        started: float | None = None,
        score_escape: bool = False,
        use_current_bones: bool = False,
    ) -> bool:
        import torch

        if not (
            self.config.optimize_root_translation or self.config.optimize_root_rotation
        ):
            return False
        if not score_escape and not self.config.root_search_enabled:
            return False
        if (
            bool(self.config.joint_keep_sprite_change_gate)
            and int(frame_position) > 0
            and self.still_sprite_mask is not None
            and bool(self.still_sprite_mask[int(frame_position)].item())
        ):
            # Keep current is previous root on still plates, not bind.
            root_translation.data[frame_position] = root_translation.data[frame_position - 1]
            root_rotation.data[frame_position] = root_rotation.data[frame_position - 1]
        count = int(self.config.root_hypotheses)
        from gpu_depth_silhouette_solver import root_rotation_search_window_deg

        if score_escape:
            window_deg = float(self.config.score_escape_root_window_deg)
        else:
            window_deg = root_rotation_search_window_deg(
                frame_position=int(frame_position),
                limit_deg=float(self.config.root_rotation_limit_deg),
                first_frame_limit_deg=float(self.config.root_rotation_first_frame_limit_deg),
                per_frame_limit_deg=float(self.config.root_rotation_per_frame_limit_deg),
            )
        window = math.radians(float(window_deg))
        if progress:
            elapsed = 0.0 if started is None else time.perf_counter() - started
            print(
                f"gpu root-search frame={self.frame_indices[frame_position]:02d} "
                f"hypotheses=0/{count} rootRotWindow={window_deg:.1f} "
                f"rootYawCap={float(self.config.root_rotation_camera_up_limit_deg):.1f} "
                f"rootYawDeferred={int(bool(self.config.root_rotation_defer_camera_up))} "
                f"elapsed={elapsed:.1f}s ...",
                end="\r",
                flush=True,
            )
        offsets = root_hypothesis_unit_offsets(count, 6).to(self.device)
        if bool(use_current_bones):
            # Always include the current root as candidate 0.
            offsets = offsets.clone()
            offsets[0].zero_()
        axis_limits = torch.as_tensor(
            self._root_rotation_axis_half_radians(),
            dtype=torch.float32,
            device=self.device,
        )
        # When refining against the current articulated bones, center on this
        # frame's root so the search scores the same pose family the clip mean
        # will evaluate. Bind-pose search still seeds from the prior frame.
        if bool(use_current_bones):
            center_rotation = self._bounded_root_rotation(root_rotation)[
                int(frame_position)
            ].detach()
            center_translation = (
                torch.tanh(root_translation[int(frame_position)].detach())
                * float(self.config.root_translation_limit_body_lengths)
            )
        elif frame_position == 0 or not bool(self.config.seed_previous_frame):
            center_rotation = torch.zeros(3, dtype=torch.float32, device=self.device)
            center_translation = torch.zeros(3, dtype=torch.float32, device=self.device)
        else:
            center_rotation = self._bounded_root_rotation(root_rotation)[frame_position - 1].detach()
            center_translation = (
                torch.tanh(root_translation[frame_position - 1].detach())
                * float(self.config.root_translation_limit_body_lengths)
            )
        translation_limit = float(self.config.root_translation_radius_body_lengths)
        if self.config.optimize_root_rotation:
            candidate_rotation = center_rotation.unsqueeze(0) + offsets[:, :3] * window
            candidate_rotation = candidate_rotation.clamp(-axis_limits, axis_limits)
        else:
            candidate_rotation = torch.zeros((count, 3), dtype=torch.float32, device=self.device)
        candidate_translation = (
            center_translation.unsqueeze(0) + offsets[:, 3:] * translation_limit
            if self.config.optimize_root_translation
            else torch.zeros((count, 3), dtype=torch.float32, device=self.device)
        )
        search_mask = self._root_rotation_search_mask(
            camera_up=not bool(self.config.root_rotation_defer_camera_up),
        )
        candidate_rotation = candidate_rotation * search_mask.view(1, 3)
        candidate_translation = candidate_translation * self.root_translation_mask.view(1, 3)
        rotation_center, _rotation_half_range = self._root_rotation_center_half()
        rotation_halves = torch.as_tensor(
            np.maximum(self._root_rotation_axis_half_radians(), 1e-9),
            dtype=torch.float32,
            device=self.device,
        )
        candidate_rotation_raw = torch.atanh(
            torch.clamp(
                (candidate_rotation - float(rotation_center)) / rotation_halves,
                -0.999,
                0.999,
            )
        )
        candidate_translation_raw = torch.atanh(
            torch.clamp(
                candidate_translation / float(self.config.root_translation_limit_body_lengths),
                -0.999,
                0.999,
            )
        )
        if self._velocity_acceleration_only_temporal():
            frame_count = int(bone_vectors.shape[0])
            bounded_full = self._bounded_bone_vectors(bone_vectors.detach())
            bones_hyps = bounded_full.unsqueeze(0).expand(count, -1, -1, -1).clone()
            root_t_hyps = root_translation.detach().unsqueeze(0).expand(count, -1, -1).clone()
            root_r_hyps = root_rotation.detach().unsqueeze(0).expand(count, -1, -1).clone()
            root_t_hyps[:, frame_position] = candidate_translation_raw
            root_r_hyps[:, frame_position] = candidate_rotation_raw
            bones_flat = bones_hyps.reshape(
                count * frame_count,
                bones_hyps.shape[-2],
                bones_hyps.shape[-1],
            )
            root_t_flat = root_t_hyps.reshape(count * frame_count, root_t_hyps.shape[-1])
            root_r_flat = root_r_hyps.reshape(count * frame_count, root_r_hyps.shape[-1])
            packed_all = self.evaluate(
                bones_flat,
                root_t_flat,
                root_r_flat,
                bone_mask=self.active_node_mask,
            )
            objectives: list[float] = []
            for hyp_index in range(count):
                start = hyp_index * frame_count
                end = start + frame_count
                chunk = {
                    key: (
                        value[start:end]
                        if isinstance(value, torch.Tensor)
                        and int(value.shape[0]) == count * frame_count
                        else value
                    )
                    for key, value in packed_all.items()
                }
                objectives.append(
                    self._clip_objective_mean(
                        bones_hyps[hyp_index],
                        root_t_hyps[hyp_index],
                        root_r_hyps[hyp_index],
                        chunk,
                    )
                )
            best = int(max(range(count), key=lambda index: objectives[index]))
            score = torch.as_tensor(
                objectives,
                dtype=torch.float32,
                device=self.device,
            )
            components = self.evaluate(
                bones_hyps[best],
                root_t_hyps[best],
                root_r_hyps[best],
                frame_indices=(self.frame_indices[frame_position],),
                bone_mask=self.active_node_mask,
            )
        else:
            if use_current_bones:
                # Must match clip-mean evaluation: FK always sees bounded bones.
                bounded = self._bounded_bone_vectors(bone_vectors.detach())
                frame_bones = bounded[int(frame_position) : int(frame_position) + 1]
                candidate_bones = frame_bones.repeat(count, 1, 1)
            else:
                candidate_bones = torch.zeros(
                    (count, bone_vectors.shape[1], 3),
                    dtype=torch.float32,
                    device=self.device,
                )
            components = self.evaluate(
                candidate_bones,
                candidate_translation_raw,
                candidate_rotation_raw,
                frame_indices=(self.frame_indices[frame_position],),
            )
            score = components["score"]
            best = int(torch.argmax(score).item())
        if bool(self.config.joint_keep_sprite_change_gate):
            excess = components["spriteChangeExcess"]
            if float(excess[best].item()) > SPRITE_CHANGE_VETO_EPS:
                if progress:
                    elapsed = 0.0 if started is None else time.perf_counter() - started
                    print(
                        f"gpu root-search frame={self.frame_indices[frame_position]:02d} "
                        f"hypotheses={count}/{count} best=held "
                        f"(sprite-change veto) "
                        f"rootRotWindow={window_deg:.1f} "
                        f"elapsed={elapsed:.1f}s",
                        flush=True,
                    )
                return False
        if bool(use_current_bones):
            if self._velocity_acceleration_only_temporal():
                bounded_full = self._bounded_bone_vectors(bone_vectors.detach())
                current_packed = self.evaluate(
                    bounded_full,
                    root_translation.detach(),
                    root_rotation.detach(),
                    bone_mask=self.active_node_mask,
                )
                current_score = self._clip_objective_mean(
                    bounded_full,
                    root_translation.detach(),
                    root_rotation.detach(),
                    current_packed,
                )
                best_score = float(score[best].item())
            else:
                frame_bones = self._bounded_bone_vectors(bone_vectors.detach())[
                    int(frame_position) : int(frame_position) + 1
                ]
                current_components = self.evaluate(
                    frame_bones,
                    root_translation[int(frame_position) : int(frame_position) + 1].detach(),
                    root_rotation[int(frame_position) : int(frame_position) + 1].detach(),
                    frame_indices=(self.frame_indices[frame_position],),
                )
                current_score = float(current_components["score"][0].item())
                best_score = float(score[best].item())
            if best_score <= current_score + 1e-6:
                if progress:
                    elapsed = 0.0 if started is None else time.perf_counter() - started
                    print(
                        f"gpu root-search frame={self.frame_indices[frame_position]:02d} "
                        f"hypotheses={count}/{count} best=held "
                        f"(no improvement {best_score:.5f}<={current_score:.5f}) "
                        f"rootRotWindow={window_deg:.1f} "
                        f"elapsed={elapsed:.1f}s",
                        flush=True,
                    )
                return False
        root_translation.data[frame_position] = candidate_translation_raw[best]
        root_rotation.data[frame_position] = candidate_rotation_raw[best]
        if progress:
            elapsed = 0.0 if started is None else time.perf_counter() - started
            print(
                f"gpu root-search frame={self.frame_indices[frame_position]:02d} "
                f"hypotheses={count}/{count} best={float(score[best].item()):.5f} "
                f"rootRotWindow={window_deg:.1f} "
                f"rootYawCap={float(self.config.root_rotation_camera_up_limit_deg):.1f} "
                f"rootYawDeferred={int(bool(self.config.root_rotation_defer_camera_up))} "
                f"elapsed={elapsed:.1f}s",
                flush=True,
            )
        return True


    def _clip_mean_for_selection(
        self,
        packed: Mapping[str, Any],
        *,
        ignore_motion: bool,
    ) -> float:
        if bool(ignore_motion):
            mean = float(packed["geometryScore"].mean().item())
            if bool(self.config.collision_enabled):
                mean -= float(self.config.collision_weight) * float(
                    packed["collisionError"].mean().item()
                )
            return mean
        return float(packed["score"].mean().item())

    def _velocity_acceleration_only_temporal(self) -> bool:
        return (
            str(self.config.temporal_scoring_mode).strip()
            == "velocity_acceleration_only"
        )

    def _clip_objective_mean(
        self,
        bounded_bones: Any,
        root_translation: Any,
        root_rotation: Any,
        packed: Mapping[str, Any],
        *,
        ignore_motion: bool | None = None,
    ) -> float:
        if ignore_motion is None:
            ignore_motion = self._velocity_acceleration_only_temporal()
        image_mean = self._clip_mean_for_selection(packed, ignore_motion=ignore_motion)
        temporal = self._temporal_penalty(bounded_bones, root_translation, root_rotation)
        return float(image_mean) - float(temporal.detach().item())

    def _clip_selection_mean(
        self,
        packed: Mapping[str, Any],
        bounded_bones: Any,
        root_translation: Any,
        root_rotation: Any,
        *,
        ignore_motion: bool,
    ) -> float:
        if bool(getattr(self, "_escape_selection_uses_hybrid_mean", False)):
            return float(packed["score"].mean().item())
        if self._velocity_acceleration_only_temporal():
            return self._clip_objective_mean(
                bounded_bones,
                root_translation,
                root_rotation,
                packed,
                ignore_motion=True,
            )
        return self._clip_mean_for_selection(packed, ignore_motion=ignore_motion)

    def _write_live_status(
        self,
        stage: str,
        *,
        started: float | None = None,
        hybrid_mean: float | None = None,
        geometry_mean: float | None = None,
        note: str = "",
    ) -> None:
        path = str(getattr(self.config, "live_status_path", "") or "").strip()
        if not path:
            return
        payload = {
            "stage": stage,
            "hybridMean": hybrid_mean,
            "geometryMean": geometry_mean,
            "elapsedSec": (
                round(time.perf_counter() - started, 1) if started is not None else None
            ),
            "note": note,
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        try:
            Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except OSError:
            return

    def _greedy_bone_adapt_for_clip_mean(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
        *,
        prefix_count: int,
        rounds: int,
        top_bones: int,
        step_deg: float,
        evaluation_count: list[int] | None = None,
        selection_ignore_motion: bool = False,
    ) -> None:
        """Short keep-if-better bone nudges under a frozen root, ranked by importance."""
        import torch

        from cascade_idle_fused_stack import importance_scores_for_mode

        stage_mask = self.active_node_mask
        joint_limit_rad = math.radians(float(self.config.joint_limit_deg))
        frame_count = int(bone_vectors.shape[0])
        prefix = max(0, int(prefix_count))
        step = float(step_deg)
        if step <= 0.0 or int(rounds) <= 0 or int(top_bones) <= 0:
            return
        prefix = max(0, int(prefix_count))
        idle_snap = (
            bone_vectors[:prefix].detach().clone() if prefix > 0 else None
        )
        for _ in range(int(rounds)):
            importance = importance_scores_for_mode(
                self,
                str(self.config.idle_fused_importance_mode),
                self.search_node_indices,
                bone_vectors,
                root_translation,
                root_rotation,
                stage_mask=stage_mask,
                evaluation_count=evaluation_count,
            )
            ranked = sorted(importance.items(), key=lambda item: (-float(item[1]), int(item[0])))
            ranked = ranked[: int(top_bones)]
            baseline_packed = self.evaluate(
                self._bounded_bone_vectors(bone_vectors),
                root_translation,
                root_rotation,
                bone_mask=stage_mask,
            )
            if evaluation_count is not None:
                evaluation_count[0] += 1
            baseline = self._clip_selection_mean(
                baseline_packed,
                self._bounded_bone_vectors(bone_vectors),
                root_translation,
                root_rotation,
                ignore_motion=selection_ignore_motion,
            )
            for bone_index, _score in ranked:
                direction = (1.0, 0.0, 0.0)
                for sign in (1.0, -1.0):
                    trial = offset_raw_bone_direction(
                        bone_vectors.detach().clone(),
                        bone_index=int(bone_index),
                        direction=direction,
                        delta_rad=math.radians(sign * step),
                        joint_limit_rad=joint_limit_rad,
                        bone_limit_scales=self.bone_limit_scales,
                    )
                    if idle_snap is not None:
                        trial[:prefix] = idle_snap
                    packed = self.evaluate(
                        self._bounded_bone_vectors(trial),
                        root_translation,
                        root_rotation,
                        bone_mask=stage_mask,
                    )
                    mean = self._clip_selection_mean(
                        packed,
                        self._bounded_bone_vectors(trial),
                        root_translation,
                        root_rotation,
                        ignore_motion=selection_ignore_motion,
                    )
                    if evaluation_count is not None:
                        evaluation_count[0] += 1
                    if mean > baseline + 1e-6:
                        baseline = mean
                        bone_vectors.data.copy_(trial)

    def _search_shared_transit_camera_up(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
        *,
        prefix_count: int,
        window_deg: float,
        step_deg: float,
        progress: bool = False,
        started: float | None = None,
        evaluation_count: list[int] | None = None,
        stage_label: str = "postArticulated",
    ) -> float:
        """One camera_up yaw for all transit frames, scored by full-clip mean.

        Per-frame root search can look strong in isolation while motion/temporal
        terms crush the clip mean. A shared yaw keeps transit orientation
        coherent, then bones adapt under that frozen heading.
        """
        import torch

        if not bool(self.config.optimize_root_rotation):
            return float("nan")
        frame_count = int(bone_vectors.shape[0])
        prefix = max(0, int(prefix_count))
        if prefix >= frame_count:
            return float("nan")
        axis_index = 2  # camera_up in (camera_forward, camera_right, camera_up)
        if float(self.root_rotation_mask[axis_index].item()) <= 0.0:
            return float("nan")
        window = float(window_deg)
        step = float(step_deg)
        if window <= 0.0 or step <= 0.0:
            raise ValueError("shared transit yaw window/step must be positive")
        angles = []
        cursor = -window
        while cursor <= window + 1e-9:
            angles.append(float(cursor))
            cursor += step
        if 0.0 not in angles:
            angles.append(0.0)
        angles = sorted(set(round(angle, 6) for angle in angles))
        center, _half = self._root_rotation_center_half()
        axis_half = float(self._root_rotation_axis_half_radians()[axis_index])
        lo = float(center) - axis_half
        hi = float(center) + axis_half
        bounded_bones = self._bounded_bone_vectors(bone_vectors.detach())
        adapt_rounds = int(self.config.idle_fused_shared_transit_yaw_bone_adapt_rounds)
        adapt_top = int(self.config.idle_fused_shared_transit_yaw_bone_adapt_top_bones)
        adapt_step = float(self.config.idle_fused_macro_step_deg)
        ignore_motion = bool(self.config.idle_fused_shared_transit_yaw_ignore_motion)
        with torch.no_grad():
            baseline = self.evaluate(
                bounded_bones,
                root_translation,
                root_rotation,
                bone_mask=self.active_node_mask,
            )
            if evaluation_count is not None:
                evaluation_count[0] += 1
            best_mean = self._clip_selection_mean(
                baseline,
                bounded_bones,
                root_translation,
                root_rotation,
                ignore_motion=ignore_motion,
            )
            best_raw = root_rotation.detach().clone()
            best_bones = bone_vectors.detach().clone()
            base_raw = root_rotation.detach().clone()
            for angle_deg in angles:
                angle_rad = math.radians(float(angle_deg))
                clamped = min(hi, max(lo, angle_rad))
                candidate = base_raw.clone()
                raw_value = math.atanh(
                    max(-0.999, min(0.999, (clamped - float(center)) / max(axis_half, 1e-9)))
                )
                candidate[prefix:, axis_index] = float(raw_value)
                trial_bones = bone_vectors.detach().clone()
                if adapt_rounds > 0:
                    self._greedy_bone_adapt_for_clip_mean(
                        trial_bones,
                        root_translation,
                        candidate,
                        prefix_count=prefix,
                        rounds=adapt_rounds,
                        top_bones=adapt_top,
                        step_deg=adapt_step,
                        evaluation_count=evaluation_count,
                        selection_ignore_motion=ignore_motion,
                    )
                packed = self.evaluate(
                    self._bounded_bone_vectors(trial_bones),
                    root_translation,
                    candidate,
                    bone_mask=self.active_node_mask,
                )
                if evaluation_count is not None:
                    evaluation_count[0] += 1
                mean = self._clip_selection_mean(
                    packed,
                    self._bounded_bone_vectors(trial_bones),
                    root_translation,
                    candidate,
                    ignore_motion=ignore_motion,
                )
                if mean > best_mean + 1e-6:
                    best_mean = mean
                    best_raw = candidate
                    best_bones = trial_bones
            bone_vectors.data.copy_(best_bones)
            root_rotation.data.copy_(best_raw)
        if progress:
            elapsed = 0.0 if started is None else time.perf_counter() - started
            yaw_deg = math.degrees(
                float(self._bounded_root_rotation(root_rotation)[prefix, axis_index].item())
            )
            hybrid_packed = self.evaluate(
                self._bounded_bone_vectors(bone_vectors),
                root_translation,
                root_rotation,
                bone_mask=self.active_node_mask,
            )
            if evaluation_count is not None:
                evaluation_count[0] += 1
            hybrid_mean = float(hybrid_packed["score"].mean().item())
            print(
                f"gpu idle_fused: sharedTransitYaw {stage_label} "
                f"selectMean={best_mean:.4f} "
                f"hybridMean={hybrid_mean:.4f} ignoreMotion={int(ignore_motion)} "
                f"yawDeg={yaw_deg:.1f} candidates={len(angles)} "
                f"elapsed={elapsed:.1f}s",
                flush=True,
            )
            self._write_live_status(
                f"sharedTransitYaw_{stage_label}",
                started=started,
                hybrid_mean=hybrid_mean,
                geometry_mean=best_mean if ignore_motion else None,
                note=f"yawDeg={yaw_deg:.1f}",
            )
        return best_mean

    def _uses_circular_temporal_wrap(self) -> bool:
        return bool(self.config.loop_enabled) or bool(self.config.temporal_loop_wrap_enabled)

    def _channel_velocity_acceleration(
        self,
        values,
        *,
        scale: float,
        mask=None,
        wrap: bool,
    ):
        import torch

        series = values if mask is None else values * mask
        frames = int(series.shape[0])
        zero = torch.zeros((), dtype=series.dtype, device=series.device)
        if frames < 2:
            return zero, zero
        if wrap:
            forward = series - torch.roll(series, 1, dims=0)
            backward = series - torch.roll(series, -1, dims=0)
            velocity = 0.5 * (
                torch.tanh(forward / scale).abs().mean()
                + torch.tanh(backward / scale).abs().mean()
            )
        else:
            velocity = torch.tanh((series[1:] - series[:-1]) / scale).abs().mean()
        if frames < 3:
            return velocity, zero
        if wrap:
            acceleration = torch.tanh(
                (torch.roll(series, -1, dims=0) - 2.0 * series + torch.roll(series, 1, dims=0))
                / scale
            ).abs().mean()
        else:
            acceleration = torch.tanh(
                (series[2:] - 2.0 * series[1:-1] + series[:-2]) / scale
            ).abs().mean()
        return velocity, acceleration

    def _velocity_acceleration_temporal_penalty(
        self,
        bone_vectors,
        root_translation,
        root_rotation,
    ) -> Any:
        import torch

        wrap = self._uses_circular_temporal_wrap()
        scale = math.radians(self.config.robust_scale_deg)
        rot_scale = max(scale, 1e-6)
        penalty = torch.zeros((), dtype=bone_vectors.dtype, device=self.device)
        bone_vel, bone_acc = self._channel_velocity_acceleration(
            bone_vectors, scale=scale, wrap=wrap
        )
        root_vel, root_acc = self._channel_velocity_acceleration(
            root_translation,
            scale=1.0,
            mask=self.root_translation_mask.view(1, 1, 3),
            wrap=wrap,
        )
        rot_vel, rot_acc = self._channel_velocity_acceleration(
            root_rotation,
            scale=rot_scale,
            mask=self.root_rotation_mask.view(1, 1, 3),
            wrap=wrap,
        )
        penalty = penalty + float(self.config.velocity_weight) * bone_vel
        penalty = penalty + float(self.config.root_velocity_weight) * root_vel
        penalty = penalty + float(self.config.root_rotation_velocity_weight) * rot_vel
        penalty = penalty + float(self.config.acceleration_weight) * bone_acc
        penalty = penalty + float(self.config.root_acceleration_weight) * root_acc
        penalty = penalty + float(self.config.root_rotation_acceleration_weight) * rot_acc
        return penalty

    def _temporal_penalty(self, bone_vectors, root_translation, root_rotation):
        import torch

        if self._velocity_acceleration_only_temporal():
            return self._velocity_acceleration_temporal_penalty(
                bone_vectors,
                root_translation,
                root_rotation,
            )

        penalty = torch.zeros((), dtype=bone_vectors.dtype, device=self.device)
        # Regularize the unconstrained optimizer variables rather than only
        # their tanh-bounded outputs. This keeps gradients alive when a
        # candidate is pressing against a configured motion limit.
        def smooth_abs(values):
            return (torch.sqrt(values * values + 1e-4) - 1e-2).mean()

        if self.config.optimize_bones:
            penalty = penalty + float(self.config.bone_pose_prior_weight) * smooth_abs(bone_vectors)
        if self.config.optimize_root_translation:
            penalty = penalty + float(self.config.root_translation_prior_weight) * smooth_abs(
                root_translation * self.root_translation_mask.view(1, 3)
            )
        if self.config.optimize_root_rotation:
            penalty = penalty + float(self.config.root_rotation_prior_weight) * smooth_abs(
                root_rotation * self.root_rotation_mask.view(1, 3)
            )
        wrap = self._uses_circular_temporal_wrap()
        scale = math.radians(self.config.robust_scale_deg)
        rot_scale = max(scale, 1e-6)
        bone_vel, bone_acc = self._channel_velocity_acceleration(
            bone_vectors, scale=scale, wrap=wrap
        )
        root_vel, root_acc = self._channel_velocity_acceleration(
            root_translation,
            scale=1.0,
            mask=self.root_translation_mask.view(1, 1, 3),
            wrap=wrap,
        )
        rot_vel, rot_acc = self._channel_velocity_acceleration(
            root_rotation,
            scale=rot_scale,
            mask=self.root_rotation_mask.view(1, 1, 3),
            wrap=wrap,
        )
        penalty = penalty + float(self.config.velocity_weight) * bone_vel
        penalty = penalty + float(self.config.root_velocity_weight) * root_vel
        penalty = penalty + float(self.config.root_rotation_velocity_weight) * rot_vel
        penalty = penalty + float(self.config.acceleration_weight) * bone_acc
        penalty = penalty + float(self.config.root_acceleration_weight) * root_acc
        penalty = penalty + float(self.config.root_rotation_acceleration_weight) * rot_acc
        if self.config.loop_enabled and bone_vectors.shape[0] > 1:
            loop_delta = torch.tanh(
                (bone_vectors[0] - bone_vectors[-1]) / math.radians(self.config.robust_scale_deg)
            ).abs().mean()
            root_loop_delta = torch.tanh(
                (root_translation[0] - root_translation[-1]) * self.root_translation_mask
            ).abs().mean()
            root_rotation_loop_delta = torch.tanh(
                (root_rotation[0] - root_rotation[-1]) * self.root_rotation_mask
            ).abs().mean()
            penalty = penalty + float(self.config.loop_weight) * loop_delta
            penalty = penalty + float(self.config.loop_velocity_weight) * (
                root_loop_delta + root_rotation_loop_delta
            )
        return penalty

    def _pose_dicts(self, bone_vectors, root_translation, root_rotation) -> dict[int, dict[str, Any]]:
        import torch

        bone_values = np.degrees(self._bounded_bone_vectors(bone_vectors).detach().cpu().numpy())
        translation_values = torch.tanh(root_translation).detach().cpu().numpy() * float(self.config.root_translation_limit_body_lengths)
        # Serialize the same bounded root used by _root_transform, including frozen
        # non-identity priors when optimize_root_rotation is False.
        rotation_values = np.degrees(self._bounded_root_rotation(root_rotation).detach().cpu().numpy())
        # Keep the serialized pose contract identical to the transform used by
        # the GPU evaluator. Disabled channels must not leak into the Blender
        # replay/export path as apparently valid motion.
        # Bone XYZ Euler values are degrees (same contract as camera_* root).
        translation_values *= self.root_translation_mask.detach().cpu().numpy()[None, :]
        rotation_values *= self.root_rotation_mask.detach().cpu().numpy()[None, :]
        result: dict[int, dict[str, Any]] = {}
        for frame_position, frame in enumerate(self.frame_indices):
            pose: dict[str, Any] = {}
            for node_index in self.active_node_indices:
                name = self.node_names[node_index]
                values = bone_values[frame_position, node_index]
                if np.max(np.abs(values)) > 1e-7:
                    pose[name] = {axis: float(values[axis_index]) for axis_index, axis in enumerate(("x", "y", "z"))}
            pose[MOTION_ROOT_KEY] = {
                "forward": float(translation_values[frame_position, 0]),
                "lateral": float(translation_values[frame_position, 1]),
                "vertical": float(translation_values[frame_position, 2]),
            }
            pose[MOTION_ROOT_ROTATION_KEY] = {
                axis: float(rotation_values[frame_position, axis_index])
                for axis_index, axis in enumerate(("camera_forward", "camera_right", "camera_up"))
            }
            result[int(frame)] = pose
        return result

    def optimize_clip(
        self,
        *,
        initial_poses: Mapping[int, Mapping[str, Any]] | None = None,
        progress: bool = True,
        live_preview: bool = False,
        preview_every: int = 1,
        live_preview_path: str | Path | None = None,
        live_preview_scale: int = 4,
        live_preview_host: Any | None = None,
    ) -> dict[str, Any]:
        """Optimize all selected frames and bones in one PyTorch solve."""
        import torch

        if live_preview_host is not None:
            self.attach_live_preview(live_preview_host)
        elif live_preview:
            if live_preview_path is None:
                raise ValueError("live_preview=True requires live_preview_path")
            from gpu_depth_silhouette_solver import GpuDepthLivePreview

            self.attach_live_preview(
                GpuDepthLivePreview(
                    live_preview_path,
                    every=int(preview_every),
                    scale=int(live_preview_scale),
                    alpha_threshold=float(self.config.ik_miss_predicted_alpha_threshold),
                )
            )
        else:
            self.attach_live_preview(None)
        if self._live_preview is not None:
            preview_positions = self._live_preview_frame_positions()
            preview_frames = ",".join(
                f"{int(self.frame_indices[int(position)]):02d}" for position in preview_positions
            )
            print(
                f"live preview: {self._live_preview.display_id} "
                f"every={int(preview_every)} "
                f"frames={preview_frames} "
                f"compare=last-committed-step "
                f"idlePrefix={int(getattr(self.config, 'idle_prefix_frames', 0) or 0)} "
                f"path={self._live_preview.path}",
                flush=True,
            )

        started = time.perf_counter()
        self._write_live_status("init", started=started)
        bone_vectors, root_translation, root_rotation = self._initial_pose_tensors(initial_poses)
        self._refresh_committed_pred_rgb(bone_vectors, root_translation, root_rotation)
        self._preview_clip_pose(
            bone_vectors,
            root_translation,
            root_rotation,
            "init",
            force=True,
            commit=True,
        )
        if self.config.root_search_enabled:
            if self.config.root_search_frame is None:
                search_positions = list(range(len(self.frame_indices)))
            else:
                search_positions = [self.frame_indices.index(int(self.config.root_search_frame))]
            for frame_position in search_positions:
                if (
                    bool(self.config.joint_keep_sprite_change_gate)
                    and int(frame_position) > 0
                    and self.still_sprite_mask is not None
                    and bool(self.still_sprite_mask[int(frame_position)].item())
                ):
                    if self._committed_pred_rgb is None:
                        raise RuntimeError(
                            "sprite-change gate has no committed RGB before root search"
                        )
                    self._committed_pred_rgb[int(frame_position)].copy_(
                        self._committed_pred_rgb[int(frame_position) - 1]
                    )
                self._root_hypothesis_start(
                    bone_vectors,
                    root_translation,
                    root_rotation,
                    frame_position,
                    progress=progress,
                    started=started,
                )
                self._remember_committed_pred_rgb_at(
                    bone_vectors,
                    root_translation,
                    root_rotation,
                    int(frame_position),
                )
            if len(search_positions) == 1 and len(self.frame_indices) > 1:
                anchor = search_positions[0]
                for frame_position in range(len(self.frame_indices)):
                    if frame_position != anchor:
                        root_translation.data[frame_position] = root_translation.data[anchor]
                        root_rotation.data[frame_position] = root_rotation.data[anchor]
                self._refresh_committed_pred_rgb(bone_vectors, root_translation, root_rotation)
            self._commit_live_pose_(bone_vectors, root_translation, root_rotation)
            self._preview_clip_pose(
                bone_vectors,
                root_translation,
                root_rotation,
                "root-search",
                force=True,
                commit=True,
            )
        elif progress:
            print(
                "gpu root-search skipped "
                f"(root_search_enabled={int(bool(self.config.root_search_enabled))})",
                flush=True,
            )
        history: list[dict[str, float]] = []
        collision_veto_count = [0]
        anatomy_veto_count = [0]
        joint_last_move: dict[int, tuple[tuple[float, float, float], float]] = {}
        branch_groups: list[dict[str, Any]] = []
        chain_space_history: list[dict[str, Any]] = []

        seeded_pose_skip = bool(initial_poses)
        root_iteration_count = (
            0
            if seeded_pose_skip and bool(self.config.root_skip_when_seeded)
            else int(self.config.root_iterations)
        )
        articulated_skip = (
            seeded_pose_skip and bool(self.config.articulated_skip_when_seeded)
        )
        evaluation_count = [0]
        iteration_display = "init"
        idle_fused_macro_done = bool(
            seeded_pose_skip and bool(self.config.idle_fused_skip_macro_when_seeded)
        )
        self._early_symmetry_visit_counter = 0
        idle_prefix_count = int(getattr(self.config, "idle_prefix_frames", 0) or 0)
        idle_suffix_count = int(getattr(self.config, "idle_suffix_frames", 0) or 0)
        idle_snap_bones_global = (
            bone_vectors[:idle_prefix_count].detach().clone()
            if idle_prefix_count > 0
            else None
        )

        def measure(phase: str, label: str, iterations: int):
            evaluation_count[0] += 1
            if progress:
                print(
                    f"gpu {label} {iteration_display}/{iterations} {phase} "
                    f"eval={evaluation_count[0]} elapsed={time.perf_counter() - started:.1f}s ...",
                    end="\r",
                    flush=True,
                )
            bounded_bones = self._bounded_bone_vectors(bone_vectors)
            bone_mask = self._stage_bone_mask(label)
            components = self.evaluate(
                bounded_bones,
                root_translation,
                root_rotation,
                bone_mask=bone_mask,
            )
            scores = components["score"]
            unique_scores = components["uniqueScore"]
            unique_errors = components["uniqueGeometryError"]
            image_score = scores.mean()
            temporal = self._temporal_penalty(
                bounded_bones,
                root_translation,
                root_rotation,
            )
            return (
                1.0 - image_score + temporal,
                image_score,
                temporal,
                scores,
                unique_scores,
                unique_errors,
                components["collisionError"],
            )

        def _joint_keep_weights(label: str) -> tuple[float, float, bool]:
            absolute_weight = float(self.config.joint_absolute_gain_weight)
            if label == "base":
                unique_weight = 0.0
                shared = True
            elif label in {"fine", "mid"}:
                unique_weight = (
                    float(self.config.fine_unique_gain_weight) if label == "fine" else 0.0
                )
                shared = False
            elif label == "articulated_broad":
                unique_weight = float(self.config.joint_unique_gain_weight)
                shared = True
            else:
                unique_weight = float(self.config.joint_unique_gain_weight)
                shared = False
            if len(self.frame_indices) < 2:
                unique_weight = 0.0
            return absolute_weight, unique_weight, shared

        def _joint_stage_bones(label: str, stage_mask) -> list[int]:
            use_fine_set = label == "fine" or (
                label in {"articulated", "articulated_broad"}
                and bool(self.config.joint_adaptive_step_enabled)
                and str(label) != "articulated_broad"
            )
            source = self.fine_node_indices if use_fine_set else self.search_node_indices
            bones = [
                int(index)
                for index in source
                if float(stage_mask[int(index)].detach().cpu().item()) > 0.0
            ]
            if not bones:
                raise RuntimeError(f"gpu {label} has no rotatable bones")
            return bones

        def _keep_score(abs_s, unique_s, col_s, *, abs_weight, unique_weight, current_abs, current_unique, current_col, collision_enabled):
            return joint_keep_score(
                absolute_geometry=abs_s,
                unique_geometry=unique_s,
                current_absolute=current_abs,
                current_unique=current_unique,
                collision=col_s,
                current_collision=current_col,
                absolute_gain_weight=abs_weight,
                unique_gain_weight=unique_weight,
                collision_weight=float(self.config.collision_weight),
                collision_enabled=bool(collision_enabled),
                collision_positive_abs_slack=float(self.config.joint_collision_positive_abs_slack),
            )

        consensus_hops = {"fwd": 0, "rev": 0, "idle": 0, "rev_pick": 0}

        def _independent_bone_walks(
            snapshot,
            snapshot_root,
            bone_index,
            stage_mask,
            joint_limit_rad,
            tie_bonus,
        ):
            scales = self.bone_limit_scales
            limit = float(joint_limit_rad) * float(scales[int(bone_index)].detach().item())
            if limit <= 1e-12:
                raise ValueError(f"bone {bone_index} has a zero joint limit")
            bounded = torch.tanh(snapshot) * float(joint_limit_rad) * scales.view(1, -1, 1)
            angles = bounded[:, int(bone_index), :].detach().cpu().numpy()
            assignment, unique_angles = cluster_bone_angles(angles)
            if int(unique_angles.shape[0]) < 2:
                return None
            unique_raw = np.arctanh(np.clip(unique_angles / limit, -0.999, 0.999))
            unique_raw_t = torch.as_tensor(unique_raw, dtype=snapshot.dtype, device=snapshot.device)
            candidates = []
            for cluster_index in range(int(unique_raw_t.shape[0])):
                cand = snapshot.detach().clone()
                cand[:, int(bone_index), :] = unique_raw_t[cluster_index]
                candidates.append(cand)
            frame_count = int(snapshot.shape[0])
            hyps_per = joint_score_hyps_per_launch(
            pose_budget=int(self.config.joint_score_raster_batch),
            frame_count=int(frame_count),
        )
            abs_rows = []
            for start in range(0, len(candidates), hyps_per):
                chunk = candidates[start : start + hyps_per]
                evaluation_count[0] += 1
                if progress:
                    print(
                        f"gpu consensus {iteration_display} "
                        f"eval={evaluation_count[0]} elapsed={time.perf_counter() - started:.1f}s ...",
                        end="\r",
                        flush=True,
                    )
                stacked_raw = torch.cat(chunk, dim=0)
                packed = self.evaluate(
                    self._bounded_bone_vectors(stacked_raw),
                    root_translation.detach().repeat(len(chunk), 1),
                    snapshot_root.detach().repeat(len(chunk), 1),
                    bone_mask=stage_mask,
                )
                packed_abs = packed["geometryScore"]
                for hyp_index in range(len(chunk)):
                    start_row = hyp_index * frame_count
                    abs_s = packed_abs[start_row : start_row + frame_count]
                    if not bool(torch.isfinite(abs_s).all()):
                        raise RuntimeError(
                            f"gpu consensus {self.node_names[int(bone_index)]} "
                            "produced a non-finite absolute score"
                        )
                    abs_rows.append(abs_s.detach().cpu().numpy())
            scores = np.stack(abs_rows, axis=0)
            end_cluster = None
            if (
                bool(self.config.joint_temporal_consensus_idle_end)
                and bool(self.config.idle_end_anchor)
                and int(assignment.shape[0]) >= 2
            ):
                end_cluster = int(assignment[0])
            forward, reverse, n_fwd, n_rev, n_end = independent_cluster_walks(
                assignment,
                scores,
                tie_bonus=tie_bonus,
                end_cluster=end_cluster,
                suffix_frames=int(self.config.idle_suffix_frames),
            )
            return forward, reverse, unique_raw, n_fwd, n_rev, n_end

        def _independent_root_walks(snapshot_raw, snapshot_root, stage_mask, tie_bonus):
            if not bool(self.config.optimize_root_rotation):
                cloned = snapshot_root.detach().clone()
                return cloned, cloned, 0, 0, 0
            bounded = self._bounded_root_rotation(snapshot_root)
            assignment, unique_angles = cluster_bone_angles(bounded.detach().cpu().numpy())
            if int(unique_angles.shape[0]) < 2:
                cloned = snapshot_root.detach().clone()
                return cloned, cloned, 0, 0, 0
            unique_raw = self._root_rotation_raw_inverse(unique_angles)
            unique_raw_t = torch.as_tensor(unique_raw, dtype=snapshot_root.dtype, device=snapshot_root.device)
            frame_count = int(snapshot_raw.shape[0])
            candidates_root = [
                unique_raw_t[cluster_index].unsqueeze(0).expand(frame_count, -1).contiguous()
                for cluster_index in range(int(unique_raw_t.shape[0]))
            ]
            hyps_per = joint_score_hyps_per_launch(
            pose_budget=int(self.config.joint_score_raster_batch),
            frame_count=int(frame_count),
        )
            abs_rows = []
            for start in range(0, len(candidates_root), hyps_per):
                chunk = candidates_root[start : start + hyps_per]
                evaluation_count[0] += 1
                stacked_raw = snapshot_raw.detach().repeat(len(chunk), 1, 1)
                stacked_root = torch.cat(chunk, dim=0)
                packed = self.evaluate(
                    self._bounded_bone_vectors(stacked_raw),
                    root_translation.detach().repeat(len(chunk), 1),
                    stacked_root,
                    bone_mask=stage_mask,
                )
                packed_abs = packed["geometryScore"]
                for hyp_index in range(len(chunk)):
                    start_row = hyp_index * frame_count
                    abs_s = packed_abs[start_row : start_row + frame_count]
                    if not bool(torch.isfinite(abs_s).all()):
                        raise RuntimeError("gpu consensus root produced a non-finite absolute score")
                    abs_rows.append(abs_s.detach().cpu().numpy())
            scores = np.stack(abs_rows, axis=0)
            end_cluster = None
            if (
                bool(self.config.joint_temporal_consensus_idle_end)
                and bool(self.config.idle_end_anchor)
                and int(assignment.shape[0]) >= 2
            ):
                end_cluster = int(assignment[0])
            forward, reverse, n_fwd, n_rev, n_end = independent_cluster_walks(
                assignment,
                scores,
                tie_bonus=tie_bonus,
                end_cluster=end_cluster,
                suffix_frames=int(self.config.idle_suffix_frames),
            )
            fwd_root = snapshot_root.detach().clone()
            rev_root = snapshot_root.detach().clone()
            unique_t = unique_raw_t
            fwd_root.copy_(unique_t[torch.as_tensor(forward, dtype=torch.int64, device=unique_t.device)])
            rev_root.copy_(unique_t[torch.as_tensor(reverse, dtype=torch.int64, device=unique_t.device)])
            return fwd_root, rev_root, n_fwd, n_rev, n_end

        def apply_temporal_consensus(current_raw, bone_indices, stage_mask):
            """Spread neighbor poses on independent forward/reverse copies, then pick a whole frame."""
            if not bool(self.config.joint_temporal_consensus_enabled):
                return current_raw, 0
            frame_count = int(current_raw.shape[0])
            if frame_count < 2 or not bone_indices:
                return current_raw, 0
            joint_limit_rad = math.radians(float(self.config.joint_limit_deg))
            tie_bonus = float(self.config.joint_temporal_consensus_tie_bonus)
            posed = current_raw.detach().clone()
            moved_frames = 0
            consensus_hops["fwd"] = 0
            consensus_hops["rev"] = 0
            consensus_hops["idle"] = 0
            consensus_hops["rev_pick"] = 0
            bidirectional = bool(self.config.joint_temporal_consensus_bidirectional)
            if bidirectional:
                snapshot = posed
                snapshot_root = root_rotation.detach().clone()
                fwd_raw = snapshot.clone()
                rev_raw = snapshot.clone()
                for bone_index in bone_indices:
                    walked = _independent_bone_walks(
                        snapshot,
                        snapshot_root,
                        int(bone_index),
                        stage_mask,
                        joint_limit_rad,
                        tie_bonus,
                    )
                    if walked is None:
                        continue
                    fwd_asg, rev_asg, unique_raw, n_fwd, n_rev, n_end = walked
                    consensus_hops["fwd"] += n_fwd
                    consensus_hops["rev"] += n_rev
                    consensus_hops["idle"] += n_end
                    fwd_raw = apply_cluster_raw_bone(
                        fwd_raw,
                        bone_index=int(bone_index),
                        unique_raw=unique_raw,
                        assignment=fwd_asg,
                    )
                    rev_raw = apply_cluster_raw_bone(
                        rev_raw,
                        bone_index=int(bone_index),
                        unique_raw=unique_raw,
                        assignment=rev_asg,
                    )
                fwd_root, rev_root, n_rf, n_rr, n_re = _independent_root_walks(
                    snapshot, snapshot_root, stage_mask, tie_bonus
                )
                consensus_hops["fwd"] += n_rf
                consensus_hops["rev"] += n_rr
                consensus_hops["idle"] += n_re
                if (
                    torch.allclose(fwd_raw, snapshot)
                    and torch.allclose(rev_raw, snapshot)
                    and torch.allclose(fwd_root, snapshot_root)
                    and torch.allclose(rev_root, snapshot_root)
                ):
                    return snapshot, 0
                evaluation_count[0] += 1
                stacked_raw = torch.cat([snapshot, fwd_raw, rev_raw], dim=0)
                stacked_root = torch.cat([snapshot_root, fwd_root, rev_root], dim=0)
                packed = self.evaluate(
                    self._bounded_bone_vectors(stacked_raw),
                    root_translation.detach().repeat(3, 1),
                    stacked_root,
                    bone_mask=stage_mask,
                )
                packed_abs = packed["geometryScore"]
                if int(packed_abs.numel()) != frame_count * 3:
                    raise RuntimeError(
                        f"gpu consensus whole-pose scores were {int(packed_abs.numel())}, "
                        f"not {frame_count * 3}"
                    )
                orig_abs = packed_abs[:frame_count].detach().cpu().numpy()
                fwd_abs = packed_abs[frame_count : frame_count * 2].detach().cpu().numpy()
                rev_abs = packed_abs[frame_count * 2 :].detach().cpu().numpy()
                if not bool(np.isfinite(orig_abs).all() and np.isfinite(fwd_abs).all() and np.isfinite(rev_abs).all()):
                    raise RuntimeError("gpu consensus whole-pose produced a non-finite absolute score")
                choice, n_rev_pick = pick_temporal_pose_pass(orig_abs, fwd_abs, rev_abs)
                consensus_hops["rev_pick"] = int(n_rev_pick)
                chosen_raw = snapshot.clone()
                chosen_root = snapshot_root.clone()
                for index, pass_id in enumerate(choice.tolist()):
                    if int(pass_id) == 1:
                        chosen_raw[index] = fwd_raw[index]
                        chosen_root[index] = fwd_root[index]
                        moved_frames += 1
                    elif int(pass_id) == 2:
                        chosen_raw[index] = rev_raw[index]
                        chosen_root[index] = rev_root[index]
                        moved_frames += 1
                commit_pose_parameter_(root_rotation, chosen_root)
                self._commit_live_pose_(chosen_raw, root_translation, root_rotation)
                return chosen_raw, moved_frames
            for bone_index in bone_indices:
                candidates = []
                for source_offset in (-1, 1):
                    copied = copy_raw_bone_from_neighbor(
                        posed,
                        bone_index=int(bone_index),
                        source_offset=source_offset,
                        joint_limit_rad=joint_limit_rad,
                        bone_limit_scales=self.bone_limit_scales,
                    )
                    if not torch.allclose(
                        copied[:, int(bone_index)],
                        posed[:, int(bone_index)],
                        atol=1e-6,
                    ):
                        candidates.append(copied)
                if frame_count >= 3:
                    lerped = lerp_raw_bone_from_neighbors(
                        posed,
                        bone_index=int(bone_index),
                        joint_limit_rad=joint_limit_rad,
                        bone_limit_scales=self.bone_limit_scales,
                    )
                    if not torch.allclose(
                        lerped[:, int(bone_index)],
                        posed[:, int(bone_index)],
                        atol=1e-6,
                    ):
                        candidates.append(lerped)
                if not candidates:
                    continue
                evaluation_count[0] += 1
                if progress:
                    print(
                        f"gpu consensus {iteration_display} "
                        f"eval={evaluation_count[0]} elapsed={time.perf_counter() - started:.1f}s ...",
                        end="\r",
                        flush=True,
                    )
                current_eval = self.evaluate(
                    self._bounded_bone_vectors(posed),
                    root_translation,
                    root_rotation,
                    bone_mask=stage_mask,
                )
                current_abs = current_eval["geometryScore"]
                stacked_raw = torch.cat(candidates, dim=0)
                packed = self.evaluate(
                    self._bounded_bone_vectors(stacked_raw),
                    root_translation.detach().repeat(len(candidates), 1),
                    root_rotation.detach().repeat(len(candidates), 1),
                    bone_mask=stage_mask,
                )
                evaluation_count[0] += 1
                raw_choices = [posed]
                keep_choices = [torch.zeros_like(current_abs)]
                packed_abs = packed["geometryScore"]
                for hyp_index in range(len(candidates)):
                    start_row = hyp_index * frame_count
                    abs_s = packed_abs[start_row : start_row + frame_count]
                    if not bool(torch.isfinite(abs_s).all()):
                        raise RuntimeError(
                            f"gpu consensus {self.node_names[int(bone_index)]} "
                            "produced a non-finite absolute score"
                        )
                    raw_choices.append(candidates[hyp_index])
                    keep_choices.append(
                        neighbor_copy_keep(abs_s, current_abs, tie_bonus=tie_bonus)
                    )
                blended, winner, _chosen = gather_per_frame_winners(
                    raw_choices,
                    keep_choices,
                    min_improvement=0.0,
                )
                winner = self._lock_still_sprite_winner(winner)
                winner = self._lock_idle_bookend_winner(winner, idle_prefix_count)
                self._copy_still_leading_(blended)
                winner_list = [int(choice) for choice in winner.detach().cpu().tolist()]
                if any(choice != 0 for choice in winner_list):
                    posed = blended
                    moved_frames += sum(choice != 0 for choice in winner_list)
            self._copy_still_leading_(posed)
            return posed, moved_frames

        def run_simultaneous_joint_stage(label: str, iterations: int, parameters: list[Any]) -> None:
            nonlocal iteration_display, idle_fused_macro_done
            import torch

            del parameters
            funnel_broad = str(label) == "articulated_broad"
            step_name = {
                "fine": "fine_joint_step_deg",
                "mid": "mid_joint_step_deg",
            }.get(label, "joint_step_deg")
            limit_name = {
                "fine": "fine_joint_pass_limit_deg",
                "mid": "mid_joint_pass_limit_deg",
            }.get(label, "joint_pass_limit_deg")
            if funnel_broad:
                step_deg = float(self.config.articulated_funnel_broad_step_deg)
                adaptive = False
                effective_probe_rungs = int(self.config.articulated_funnel_broad_probe_rungs)
                min_improvement = float(
                    self.config.articulated_funnel_broad_min_improvement
                )
                multi_bone_enabled = True
                multi_block_size = int(
                    self.config.articulated_funnel_broad_multi_bone_block_size
                )
                bone_order_override = (
                    "gradient_magnitude"
                    if bool(self.config.articulated_funnel_force_gradient_order)
                    else None
                )
            else:
                step_deg = float(getattr(self.config, step_name))
                configured_limit = float(getattr(self.config, limit_name))
                adaptive = bool(self.config.joint_adaptive_step_enabled)
                effective_probe_rungs = int(self.config.joint_probe_rungs)
                min_improvement = float(self.config.joint_keep_min_improvement)
                multi_bone_enabled = bool(self.config.articulated_multi_bone_enabled)
                multi_block_size = int(self.config.articulated_multi_bone_block_size)
                bone_order_override = None
                configured_limit = float(getattr(self.config, limit_name))
            if funnel_broad:
                configured_limit = 0.0
            directions = joint_search_directions(
                self.config.joint_search_axes,
                int(self.config.joint_diagonal_axes),
            )
            joint_limit_rad = math.radians(float(self.config.joint_limit_deg))
            stage_mask = self._stage_bone_mask(label)
            bone_indices = _joint_stage_bones(label, stage_mask)
            abs_weight, unique_weight, shared = _joint_keep_weights(label)
            accepted_count = 0
            moved_frame_total = 0
            rounds = max(1, int(iterations))
            active_bones = list(bone_indices)
            followup_neighbors = bool(self.config.joint_round_followup_neighbors)
            if str(label) == "shared_yaw_adapt":
                # Round-2 neighbor follow-up can drop macro trunk/leg bones from the
                # visit list before multi-bone anatomy groups run, starving coordinated
                # chain search that often carries the clip mean (leg_b multi ~+0.01).
                followup_neighbors = False
            anatomical_parents = {
                index: (int(parent) if parent is not None else None)
                for index, parent in enumerate(self.parents)
            }
            if funnel_broad and progress:
                print(
                    "gpu articulated_broad: "
                    f"step={step_deg:.1f}° rungs={effective_probe_rungs} "
                    f"multiBone={multi_block_size} "
                    f"minImprove={min_improvement:.4g}",
                    flush=True,
                )

            if (
                str(label) in ("articulated", "articulated_broad")
                and bool(self.config.idle_fused_macro_enabled)
                and not bool(idle_fused_macro_done)
            ):
                idle_fused_macro_done = True

                from cascade_idle_fused_stack import (
                    _restore_idle_prefix,
                    _top_gradient_chains,
                    format_importance_log,
                    importance_scores_for_mode,
                )

                prefix_count = int(getattr(self.config, "idle_prefix_frames", 0) or 0)
                idle_snap_bones = bone_vectors[:prefix_count].detach().clone()
                idle_snap_root_t = root_translation[:prefix_count].detach().clone()
                idle_snap_root_r = root_rotation[:prefix_count].detach().clone()
                macro_mask = self._stage_bone_mask("articulated")
                opening_macro = self.evaluate(
                    self._bounded_bone_vectors(bone_vectors),
                    root_translation,
                    root_rotation,
                    bone_mask=macro_mask,
                )
                evaluation_count[0] += 1
                frame_scores = opening_macro["score"].detach()
                idle_anchor = float(frame_scores[0].item()) if int(prefix_count) > 0 else 0.0
                importance = importance_scores_for_mode(
                    self,
                    str(self.config.idle_fused_importance_mode),
                    self.search_node_indices,
                    bone_vectors,
                    root_translation,
                    root_rotation,
                    stage_mask=macro_mask,
                    evaluation_count=evaluation_count,
                )
                ranked = sorted(
                    importance.keys(),
                    key=lambda index: (-float(importance[int(index)]), int(index)),
                )
                top_bones = ranked[: int(self.config.idle_fused_top_bone_count)]
                chains = _top_gradient_chains(
                    top_bones,
                    self.parents,
                    max_chains=int(self.config.idle_fused_macro_chain_count),
                )
                if progress:
                    print(
                        f"gpu idle_fused: anchor={idle_anchor:.4f} "
                        f"importance={format_importance_log(self, importance)} "
                        f"chains={len(chains)}",
                        flush=True,
                    )
                macro_root_axes = None
                explicit_macro_axes = self.config.idle_fused_macro_root_rotation_axes
                if explicit_macro_axes is not None:
                    macro_root_axes = tuple(str(axis) for axis in explicit_macro_axes)
                elif (
                    bool(self.config.idle_fused_shared_transit_yaw_enabled)
                    and bool(self.config.idle_fused_shared_transit_yaw_pre_articulated)
                ):
                    # Pre-articulated shared camera_up is the macro heading; refit
                    # forward/lateral only so idle_fused_root_full does not undo yaw.
                    macro_root_axes = ("camera_forward", "camera_right")
                elif bool(self.config.root_rotation_defer_camera_up):
                    from gpu_depth_silhouette_solver import root_rotation_axes_for_phase

                    macro_root_axes = root_rotation_axes_for_phase(
                        self.config.root_rotation_axes,
                        defer_camera_up=True,
                        phase="initial",
                    )
                run_root_refit(
                    label="idle_fused_root_full",
                    include_translation=False,
                    rotation_axes=macro_root_axes,
                    rotation_window_deg=float(self.config.idle_fused_root_window_deg),
                    rotation_step_deg=float(self.config.idle_fused_root_step_deg),
                )
                if bool(self.config.idle_fused_per_frame_root_enabled):
                    from cascade_idle_fused_stack import transit_worst_frame_positions

                    worst_positions = transit_worst_frame_positions(
                        frame_scores,
                        prefix_count=prefix_count,
                        keep_count=int(self.config.idle_fused_per_frame_root_count),
                    )
                    worst_indices = [
                        int(self.frame_indices[int(position)])
                        for position in worst_positions.detach().cpu().tolist()
                    ]
                    if progress:
                        print(
                            f"gpu idle_fused: perFrameRoot frames={worst_indices}",
                            flush=True,
                        )
                    for position in worst_positions.detach().cpu().tolist():
                        self._root_hypothesis_start(
                            bone_vectors,
                            root_translation,
                            root_rotation,
                            int(position),
                            progress=progress,
                            started=started,
                            score_escape=True,
                            use_current_bones=False,
                        )
                _restore_idle_prefix(
                    bone_vectors,
                    root_translation,
                    root_rotation,
                    idle_snap_bones=idle_snap_bones,
                    idle_snap_root_t=idle_snap_root_t,
                    idle_snap_root_r=idle_snap_root_r,
                    prefix_count=prefix_count,
                )
                if chains:
                    macro_abs_weight, macro_unique_weight, _macro_shared = _joint_keep_weights(
                        "articulated"
                    )
                    macro_min_improvement = float(self.config.joint_keep_min_improvement)
                    macro_joint_limit_rad = math.radians(float(self.config.joint_limit_deg))
                    macro_step_deg = float(self.config.idle_fused_macro_step_deg)
                    baseline_abs, baseline_unique, current_collision, zeros_keep = (
                        self._run_joint_chain_combo_pass(
                            chains,
                            stage_label="articulated",
                            tag_prefix="idle_fused macro",
                            bone_vectors=bone_vectors,
                            root_translation=root_translation,
                            root_rotation=root_rotation,
                            evaluation_count=evaluation_count,
                            started=started,
                            progress=progress,
                            joint_last_move=joint_last_move,
                            consensus_hops=consensus_hops,
                            collision_veto_count=collision_veto_count,
                            branch_groups=branch_groups,
                            abs_weight=macro_abs_weight,
                            unique_weight=macro_unique_weight,
                            min_improvement=macro_min_improvement,
                            joint_limit_rad=macro_joint_limit_rad,
                            step_deg=macro_step_deg,
                            _keep_score=_keep_score,
                            baseline_abs=opening_macro["geometryScore"].detach().clone(),
                            baseline_unique=opening_macro["uniqueGeometryQuality"].detach().clone(),
                            current_collision=opening_macro["collisionError"].detach().clone(),
                            zeros_keep=torch.zeros_like(opening_macro["geometryScore"]),
                            stage_mask=macro_mask,
                            apply_temporal_consensus=apply_temporal_consensus,
                        )
                    )
                _restore_idle_prefix(
                    bone_vectors,
                    root_translation,
                    root_rotation,
                    idle_snap_bones=idle_snap_bones,
                    idle_snap_root_t=idle_snap_root_t,
                    idle_snap_root_r=idle_snap_root_r,
                    prefix_count=prefix_count,
                )
                post_macro = self.evaluate(
                    self._bounded_bone_vectors(bone_vectors),
                    root_translation,
                    root_rotation,
                    bone_mask=macro_mask,
                )
                evaluation_count[0] += 1
                if progress:
                    print(
                        f"gpu idle_fused: postMacro mean={float(post_macro['score'].mean().item()):.4f} "
                        f"idleFrame={float(post_macro['score'][0].item()):.4f} "
                        f"evals={evaluation_count[0]}",
                        flush=True,
                    )
                self._preview_clip_pose(
                    bone_vectors,
                    root_translation,
                    root_rotation,
                    "idle_fused macro",
                    force=True,
                    commit=True,
                )

            def _articulated_root_interleave(tag: str) -> None:
                if str(label) != "articulated":
                    return
                if not bool(self.config.articulated_root_interleave_enabled):
                    return
                if not bool(self.config.optimize_root_rotation):
                    return
                # Whole-body turn as a joint peer: modest keep-gated root
                # steps woven with bone accepts, not a separate ±180° stage.
                run_root_refit(
                    label=tag,
                    include_translation=bool(
                        self.config.articulated_root_interleave_include_translation
                    ),
                    rotation_window_deg=float(
                        self.config.articulated_root_interleave_rotation_deg
                    ),
                    rotation_step_deg=float(
                        self.config.articulated_root_interleave_rotation_step_deg
                    ),
                )

            with torch.no_grad():
                iteration_display = "init"
                evaluation_count[0] += 1
                cheap_occupancy = bool(self.config.cheap_joint_probe_occupancy_only)
                sparse_probe_frames = int(self.config.cheap_joint_probe_frame_count) > 0
                opening = self.evaluate(
                    self._bounded_bone_vectors(bone_vectors),
                    root_translation,
                    root_rotation,
                    bone_mask=stage_mask,
                    occupancy_only=cheap_occupancy,
                )
                baseline_abs = opening["geometryScore"].detach().clone()
                baseline_unique = opening["uniqueGeometryQuality"].detach().clone()
                current_collision = opening["collisionError"].detach().clone()
                if not bool(torch.isfinite(baseline_abs).all()):
                    raise RuntimeError(f"gpu {label} opening absolute scores are not finite")
                if not bool(torch.isfinite(baseline_unique).all()):
                    raise RuntimeError(f"gpu {label} opening unique scores are not finite")
                opening_abs = float(baseline_abs.mean().item())
                opening_unique_error = float(opening["uniqueGeometryError"].mean().item())
                last_clip_score = float(opening["score"].mean().item())
                last_unique_err = opening_unique_error
                last_temporal = float(
                    self._temporal_penalty(
                        self._bounded_bone_vectors(bone_vectors),
                        root_translation,
                        root_rotation,
                    ).detach().item()
                )
                zeros_keep = torch.zeros_like(baseline_abs)
                if (cheap_occupancy or sparse_probe_frames) and progress:
                    from cascade_cheap_probe import cheap_probe_positions

                    cheap_frames = cheap_probe_positions(
                        [float(value) for value in baseline_abs.detach().cpu().tolist()],
                        prefix=int(getattr(self.config, "idle_prefix_frames", 0) or 0),
                        suffix=int(getattr(self.config, "idle_suffix_frames", 0) or 0),
                        keep_count=int(self.config.cheap_joint_probe_frame_count),
                    )
                    probe_kind = "occupancyOnly" if cheap_occupancy else "sparseScore"
                    print(
                        f"gpu {label} cheapProbe {probe_kind} "
                        f"frames={len(cheap_frames)} "
                        f"keepCount={int(self.config.cheap_joint_probe_frame_count)} "
                        f"ids={[int(self.frame_indices[i]) for i in cheap_frames]}",
                        flush=True,
                    )
                if adaptive and progress:
                    print(
                        f"gpu {label} adaptiveStep "
                        f"norm={self.config.joint_step_score_norm} "
                        f"fine={float(self.config.fine_joint_step_deg):.3g}°@"
                        f"{float(self.config.joint_step_score_fine):.3g} "
                        f"coarse={float(self.config.joint_step_deg):.3g}°@"
                        f"{float(self.config.joint_step_score_coarse):.3g} "
                        f"openingMin={float(baseline_abs.min().item()):.4f} "
                        f"openingMax={float(baseline_abs.max().item()):.4f}",
                        flush=True,
                    )

                def keep_from(abs_s, unique_s, col_s):
                    return _keep_score(
                        abs_s,
                        unique_s,
                        col_s,
                        abs_weight=abs_weight,
                        unique_weight=unique_weight,
                        current_abs=baseline_abs,
                        current_unique=baseline_unique,
                        current_col=current_collision,
                        collision_enabled=bool(self.config.collision_enabled),
                    )

                def probe_direction_offsets(current_raw, bone_index, pending):
                    from cascade_cheap_probe import cheap_probe_positions

                    frame_count = int(current_raw.shape[0])
                    probe_pos = None
                    raster_count = frame_count
                    raster_ids = None
                    pos_tensor = None
                    if cheap_occupancy or sparse_probe_frames:
                        probe_pos = cheap_probe_positions(
                            [float(value) for value in baseline_abs.detach().cpu().tolist()],
                            prefix=int(getattr(self.config, "idle_prefix_frames", 0) or 0),
                            suffix=int(getattr(self.config, "idle_suffix_frames", 0) or 0),
                            keep_count=int(self.config.cheap_joint_probe_frame_count),
                        )
                        raster_count = len(probe_pos)
                        raster_ids = tuple(
                            int(self.frame_indices[int(position)]) for position in probe_pos
                        )
                        pos_tensor = torch.as_tensor(
                            list(probe_pos), dtype=torch.long, device=current_raw.device
                        )
                    hyps_per = joint_score_hyps_per_launch(
                        pose_budget=int(self.config.joint_score_raster_batch),
                        frame_count=int(raster_count),
                    )
                    abs_out = []
                    unique_out = []
                    col_out = []
                    raw_out = []
                    for start in range(0, len(pending), hyps_per):
                        chunk = pending[start : start + hyps_per]
                        full_offsets = [
                            offset_raw_bone_direction(
                                current_raw,
                                bone_index=bone_index,
                                direction=direction,
                                delta_rad=(
                                    delta_deg * (math.pi / 180.0)
                                    if torch.is_tensor(delta_deg)
                                    else math.radians(float(delta_deg))
                                ),
                                joint_limit_rad=joint_limit_rad,
                                bone_limit_scales=self.bone_limit_scales,
                            )
                            for direction, delta_deg in chunk
                        ]
                        if cheap_occupancy:
                            stacked_raw = torch.cat(
                                [item.index_select(0, pos_tensor) for item in full_offsets],
                                dim=0,
                            )
                            stacked_root_t = root_translation.detach().index_select(
                                0, pos_tensor
                            ).repeat(len(chunk), 1)
                            stacked_root_r = root_rotation.detach().index_select(
                                0, pos_tensor
                            ).repeat(len(chunk), 1)
                            eval_kwargs = {
                                "bone_mask": stage_mask,
                                "frame_indices": raster_ids,
                                "occupancy_only": True,
                            }
                        elif sparse_probe_frames:
                            stacked_raw = torch.cat(
                                [item.index_select(0, pos_tensor) for item in full_offsets],
                                dim=0,
                            )
                            stacked_root_t = root_translation.detach().index_select(
                                0, pos_tensor
                            ).repeat(len(chunk), 1)
                            stacked_root_r = root_rotation.detach().index_select(
                                0, pos_tensor
                            ).repeat(len(chunk), 1)
                            eval_kwargs = {
                                "bone_mask": stage_mask,
                                "frame_indices": raster_ids,
                            }
                        else:
                            stacked_raw = torch.cat(full_offsets, dim=0)
                            stacked_root_t = root_translation.detach().repeat(len(chunk), 1)
                            stacked_root_r = root_rotation.detach().repeat(len(chunk), 1)
                            eval_kwargs = {"bone_mask": stage_mask}
                        evaluation_count[0] += 1
                        if progress:
                            print(
                                f"gpu {label} {iteration_display} probe "
                                f"eval={evaluation_count[0]} elapsed={time.perf_counter() - started:.1f}s ...",
                                end="\r",
                                flush=True,
                            )
                        components = self.evaluate(
                            self._bounded_bone_vectors(stacked_raw),
                            stacked_root_t,
                            stacked_root_r,
                            **eval_kwargs,
                        )
                        packed_abs = components["geometryScore"]
                        packed_unique = components["uniqueGeometryQuality"]
                        packed_collision = components["collisionError"]
                        expected = raster_count * len(chunk)
                        if int(packed_abs.numel()) != expected:
                            raise RuntimeError(
                                f"gpu {label} packed absolute scores were {int(packed_abs.numel())}, "
                                f"not {expected}"
                            )
                        for hyp_index, (direction, delta_deg) in enumerate(chunk):
                            start_row = hyp_index * raster_count
                            packed_abs_slice = packed_abs[start_row : start_row + raster_count]
                            packed_unique_slice = packed_unique[start_row : start_row + raster_count]
                            packed_col_slice = packed_collision[start_row : start_row + raster_count]
                            if cheap_occupancy or sparse_probe_frames:
                                abs_slice = baseline_abs.detach().clone()
                                unique_slice = baseline_unique.detach().clone()
                                col_slice = current_collision.detach().clone()
                                abs_slice.index_copy_(0, pos_tensor, packed_abs_slice)
                                unique_slice.index_copy_(0, pos_tensor, packed_unique_slice)
                                col_slice.index_copy_(0, pos_tensor, packed_col_slice)
                                raw_full = full_offsets[hyp_index].detach().clone()
                            else:
                                abs_slice = packed_abs_slice
                                unique_slice = packed_unique_slice
                                col_slice = packed_col_slice
                                raw_full = stacked_raw[
                                    hyp_index * frame_count : (hyp_index + 1) * frame_count
                                ]
                            if not bool(torch.isfinite(abs_slice).all()):
                                raise RuntimeError(
                                    f"gpu {label} {self.node_names[bone_index]} "
                                    f"{delta_deg:+.3g}° produced a non-finite absolute score"
                                )
                            abs_out.append(abs_slice.detach().clone())
                            unique_out.append(unique_slice.detach().clone())
                            col_out.append(col_slice.detach().clone())
                            raw_out.append(raw_full.detach().clone())
                    return abs_out, unique_out, col_out, raw_out

                visit = 0
                for round_index in range(rounds):
                    if not active_bones:
                        if progress:
                            print(
                                f"gpu {label} stalled after round {round_index}/"
                                f"{rounds}; later rounds would repeat the same keep surface",
                                flush=True,
                            )
                        break
                    self._seed_transit_pose_from_previous_(
                        bone_vectors,
                        root_translation,
                        root_rotation,
                        only_if_bind=True,
                        progress=progress,
                        label=f"{label} seedPreviousFrame",
                    )
                    round_probe_moved: list[int] = []
                    round_combo_moved: list[int] = []
                    round_accepted = 0
                    if round_index > 0 and followup_neighbors:
                        skipped_settled = len(bone_indices) - len(active_bones)
                        if progress:
                            print(
                                f"gpu {label} round {round_index + 1}/{rounds} "
                                f"followup={len(active_bones)} skippedSettled={skipped_settled}",
                                flush=True,
                            )
                    ranked_bones = self._rank_joint_bones(
                        active_bones,
                        bone_vectors,
                        root_translation,
                        root_rotation,
                        original_order=bone_indices,
                        stage_mask=stage_mask,
                        evaluation_count=evaluation_count,
                        abs_weight=abs_weight,
                        unique_weight=unique_weight,
                        current_abs=baseline_abs,
                        current_unique=baseline_unique,
                        current_col=current_collision,
                        mode_override=bone_order_override,
                    )
                    active_bones = list(ranked_bones)
                    round_label = f"{label} {round_index + 1}/{rounds}"
                    root_policy = str(self.config.articulated_root_interleave_policy)
                    primary_groups = self._articulated_primary_groups()
                    if progress:
                        names = [str(self.node_names[int(index)]) for index in active_bones]
                        order_label = (
                            bone_order_override
                            if bone_order_override is not None
                            else str(self.config.bone_order_mode)
                        )
                        print(
                            f"gpu {label} boneOrder={order_label} "
                            f"round={round_index + 1} "
                            f"first={','.join(names[:4])} "
                            f"last={','.join(names[-4:])}",
                            flush=True,
                        )
                    self._preview_clip_pose(
                        bone_vectors,
                        root_translation,
                        root_rotation,
                        round_label,
                        force=True,
                        commit=False,
                    )
                    for bone_index in active_bones:
                        symmetry_active = self._early_symmetry_active(
                            self._early_symmetry_visit_counter
                        )
                        if symmetry_active and self._early_symmetry_skip_bone(bone_index):
                            continue
                        visit += 1
                        iteration_display = str(visit)
                        bone_name = self.node_names[bone_index]
                        bone_directions = (
                            self._early_symmetry_joint_directions(bone_index, directions)
                            if symmetry_active
                            else directions
                        )
                        if symmetry_active and not bone_directions:
                            self._early_symmetry_visit_counter += 1
                            continue
                        bone_limit_deg = math.degrees(
                            joint_limit_rad * float(self.bone_limit_scales[bone_index].detach().item())
                        )
                        axis_limit_deg = (
                            bone_limit_deg
                            if configured_limit <= 0.0
                            else min(configured_limit, bone_limit_deg)
                        )
                        moved_frames: list[int] = []
                        moved_axes: list[str] = []
                        moved_deltas: list[str] = []
                        accepted = False
                        unit_step = None
                        if adaptive:
                            unit_step = joint_unit_step_deg(
                                normalize_keep_scores_for_joint_step(
                                    baseline_abs,
                                    mode=str(self.config.joint_step_score_norm),
                                ),
                                coarse_deg=float(self.config.joint_step_deg),
                                fine_deg=float(self.config.fine_joint_step_deg),
                                coarse_score=float(self.config.joint_step_score_coarse),
                                fine_score=float(self.config.joint_step_score_fine),
                            )
                            probe_step = float(unit_step.min().item())
                        else:
                            probe_step = step_deg
                        if axis_limit_deg + 1e-9 < probe_step:
                            continue
                        current_raw = bone_vectors.detach().clone()
                        raw_choices = [current_raw]
                        keep_choices = [zeros_keep]
                        keep_geom_choices = [zeros_keep]
                        meta_choices: list[tuple[tuple[float, float, float], float]] = [((0.0, 0.0, 0.0), 0.0)]
                        if adaptive:
                            pending = []
                            for direction in bone_directions:
                                for rung in range(1, effective_probe_rungs + 1):
                                    for sign in (1.0, -1.0):
                                        delta = (unit_step * (sign * float(rung))).clamp(
                                            -float(axis_limit_deg),
                                            float(axis_limit_deg),
                                        )
                                        if bool((delta.abs() <= 1e-12).any()):
                                            raise RuntimeError(
                                                f"gpu {label} {bone_name} adaptive step "
                                                "collapsed to 0 on a frame"
                                            )
                                        pending.append((direction, delta))
                        else:
                            window = first_axis_window_deg(
                                step_deg,
                                rungs=effective_probe_rungs,
                                limit_deg=axis_limit_deg,
                            )
                            pending = [(direction, float(delta_deg)) for direction in bone_directions for delta_deg in window]
                        scored_keys = {(0.0, 0.0, 0.0, 0.0)}
                        winner = None
                        winner_list: list[int] | None = None
                        while pending:
                            abs_list, unique_list, col_list, raw_list = probe_direction_offsets(
                                current_raw,
                                bone_index,
                                pending,
                            )
                            for (direction, delta_deg), abs_s, unique_s, col_s, raw_s in zip(
                                pending, abs_list, unique_list, col_list, raw_list
                            ):
                                raw_choices.append(raw_s)
                                keep_choices.append(keep_from(abs_s, unique_s, col_s))
                                keep_geom_choices.append(
                                    _keep_score(
                                        abs_s,
                                        unique_s,
                                        col_s,
                                        abs_weight=abs_weight,
                                        unique_weight=unique_weight,
                                        current_abs=baseline_abs,
                                        current_unique=baseline_unique,
                                        current_col=current_collision,
                                        collision_enabled=False,
                                    )
                                )
                                meta_delta = (
                                    float(delta_deg.detach().float().mean().item())
                                    if torch.is_tensor(delta_deg)
                                    else float(delta_deg)
                                )
                                meta_choices.append((tuple(float(part) for part in direction), meta_delta))
                                scored_keys.add((*tuple(float(part) for part in direction), meta_delta))
                            clip_frame_weights = None
                            if (
                                funnel_broad
                                and bool(
                                    self.config.articulated_funnel_worst_frame_keep_enabled
                                )
                            ):
                                import torch

                                frame_count = int(baseline_abs.shape[0])
                                clip_frame_weights = torch.ones(
                                    frame_count,
                                    dtype=torch.float32,
                                    device=baseline_abs.device,
                                )
                                worst_positions = worst_frame_indices(
                                    baseline_abs,
                                    keep_count=int(
                                        self.config.articulated_funnel_worst_frame_keep_count
                                    ),
                                )
                                clip_frame_weights[worst_positions] = float(
                                    self.config.articulated_funnel_worst_frame_keep_weight
                                )
                            if bool(self.config.anatomy_veto_enabled):
                                keep_choices = self._apply_anatomy_veto_probe_family(
                                    raw_choices,
                                    keep_choices,
                                    baseline_raw=current_raw,
                                    root_translation=root_translation,
                                    root_rotation=root_rotation,
                                    anatomy_veto_count=anatomy_veto_count,
                                )
                            if shared:
                                blended, winner_index, _chosen = gather_clip_winner(
                                    raw_choices,
                                    keep_choices,
                                    min_improvement=min_improvement,
                                    frame_weights=clip_frame_weights,
                                )
                                winner = torch.full(
                                    (int(current_raw.shape[0]),),
                                    int(winner_index),
                                    dtype=torch.long,
                                    device=current_raw.device,
                                )
                                winner_list = [int(winner_index)] * int(current_raw.shape[0])
                                geom_index = gather_clip_winner(
                                    raw_choices,
                                    keep_geom_choices,
                                    min_improvement=min_improvement,
                                )[1]
                                if int(geom_index) != int(winner_index):
                                    collision_veto_count[0] += 1
                            else:
                                blended, winner, _chosen = gather_per_frame_winners(
                                    raw_choices,
                                    keep_choices,
                                    min_improvement=min_improvement,
                                )
                                winner = self._lock_still_sprite_winner(winner)
                                winner = self._lock_idle_bookend_winner(winner, idle_prefix_count)
                                self._copy_still_leading_(blended)
                                winner_list = [int(choice) for choice in winner.detach().cpu().tolist()]
                                geom_winner = gather_per_frame_winners(
                                    raw_choices,
                                    keep_geom_choices,
                                    min_improvement=min_improvement,
                                )[1]
                                geom_winner = self._lock_still_sprite_winner(geom_winner)
                                geom_list = [int(choice) for choice in geom_winner.detach().cpu().tolist()]
                                if winner_list != geom_list:
                                    collision_veto_count[0] += 1
                            next_pending: list[tuple[tuple[float, float, float], float]] = []
                            queued: set[tuple[float, float, float, float]] = set()
                            max_abs: dict[tuple[float, float, float], float] = {}
                            if adaptive:
                                pending = []
                                continue
                            for direction, delta_deg in meta_choices:
                                if abs(delta_deg) <= 1e-12:
                                    continue
                                key = tuple(float(part) for part in direction)
                                max_abs[key] = max(max_abs.get(key, 0.0), abs(float(delta_deg)))
                            for choice in winner_list or []:
                                direction, delta_deg = meta_choices[int(choice)]
                                if abs(delta_deg) <= 1e-12:
                                    continue
                                key = tuple(float(part) for part in direction)
                                if abs(delta_deg) + 1e-9 < max_abs.get(key, 0.0):
                                    continue
                                grown = axis_rung_after(
                                    delta_deg,
                                    step_deg=step_deg,
                                    limit_deg=axis_limit_deg,
                                )
                                grown_key = (*key, float(grown) if grown is not None else 0.0)
                                if (
                                    grown is not None
                                    and grown_key not in scored_keys
                                    and grown_key not in queued
                                ):
                                    next_pending.append((key, float(grown)))
                                    queued.add(grown_key)
                            pending = next_pending
                        if winner is None or winner_list is None:
                            continue
                        bone_vectors.copy_(blended)
                        self._commit_live_pose_(bone_vectors, root_translation, root_rotation)
                        axis_frames = [
                            int(self.frame_indices[position])
                            for position, choice in enumerate(winner_list)
                            if int(choice) != 0
                        ]
                        probe_moved = bool(axis_frames)
                        if axis_frames:
                            accepted = True
                            vote: dict[tuple[float, float, float], list[float]] = {}
                            for choice in winner_list:
                                if int(choice) == 0:
                                    continue
                                direction, delta_deg = meta_choices[int(choice)]
                                vote.setdefault(direction, []).append(float(delta_deg))
                                axis_label = ",".join(f"{part:.2f}" for part in direction)
                                if axis_label not in moved_axes:
                                    moved_axes.append(axis_label)
                                label_deg = f"{delta_deg:+.3g}"
                                if label_deg not in moved_deltas:
                                    moved_deltas.append(label_deg)
                            best_dir = max(vote.items(), key=lambda item: len(item[1]))
                            median_delta = sorted(best_dir[1])[len(best_dir[1]) // 2]
                            joint_last_move[int(bone_index)] = (best_dir[0], float(median_delta))
                            for frame in axis_frames:
                                if frame not in moved_frames:
                                    moved_frames.append(frame)
                            round_probe_moved.append(int(bone_index))
                        if symmetry_active and probe_moved:
                            self._early_symmetry_mirror_bones_(bone_vectors, [int(bone_index)])
                            self._commit_live_pose_(bone_vectors, root_translation, root_rotation)
                        pose_changed = probe_moved
                        if pose_changed:
                            post_eval = self.evaluate(
                                self._bounded_bone_vectors(bone_vectors),
                                root_translation,
                                root_rotation,
                                bone_mask=stage_mask,
                                occupancy_only=cheap_occupancy,
                            )
                            evaluation_count[0] += 1
                            baseline_abs = post_eval["geometryScore"].detach().clone()
                            baseline_unique = post_eval["uniqueGeometryQuality"].detach().clone()
                            current_collision = post_eval["collisionError"].detach().clone()
                            zeros_keep = torch.zeros_like(baseline_abs)
                            last_clip_score = float(post_eval["score"].mean().item())
                            last_unique_err = float(post_eval["uniqueGeometryError"].mean().item())
                            last_temporal = float(
                                self._temporal_penalty(
                                    self._bounded_bone_vectors(bone_vectors),
                                    root_translation,
                                    root_rotation,
                                ).detach().item()
                            )
                        post_score = last_clip_score
                        post_unique_err = last_unique_err
                        post_loss_value = 1.0 - last_clip_score + last_temporal
                        if accepted:
                            accepted_count += 1
                            round_accepted += 1
                            moved_frame_total += len(moved_frames)
                        attempted = float(post_loss_value)
                        row = {
                            "stage": label,
                            "iteration": float(visit),
                            "loss": float(post_loss_value),
                            "score": float(post_score),
                            "temporal": float(last_temporal),
                            "accepted": bool(accepted),
                            "learningRate": math.radians(step_deg),
                            "rejectStreak": 0.0,
                            "attemptedLoss": attempted,
                            "boneGrad": float("nan"),
                            "stepDeg": (
                                float(unit_step.mean().item())
                                if unit_step is not None
                                else step_deg
                            ),
                            "movedCount": float(len(moved_frames)),
                            "activeFrames": ",".join(f"{frame:02d}" for frame in moved_frames),
                            "keepAbsWeight": abs_weight,
                            "keepUniqueWeight": unique_weight,
                            "sharedOffset": float(shared),
                            "consensusMoved": 0.0,
                        }
                        history.append(row)
                        if progress and (
                            visit == 1
                            or accepted
                            or visit % max(1, int(self.config.progress_every)) == 0
                        ):
                            extra = (
                                f" bones={bone_name}"
                                f" round={round_index + 1}/{rounds}"
                                f" uniqueErr={post_unique_err:.4f}"
                                f" abs={float(baseline_abs.mean().item()):.4f}"
                            )
                            if moved_axes:
                                extra += " axes=" + ",".join(moved_axes[:4])
                            if moved_deltas:
                                extra += " d=" + ",".join(moved_deltas[:6])
                            if unit_step is not None:
                                extra += (
                                    f" adaptiveStep={float(unit_step.min().item()):.2f}"
                                    f"..{float(unit_step.max().item()):.2f}"
                                )
                            print(
                                f"gpu {label} {visit}: "
                                f"score={row['score']:.5f} loss={row['loss']:.5f} "
                                f"attempted={attempted:.5f} "
                                f"temporal={row['temporal']:.5f} accepted={row['accepted']} "
                                f"stepDeg={row['stepDeg']:.3g} nMoved={len(moved_frames)} "
                                f"frames={row['activeFrames'] or '-'} "
                                f"evals={evaluation_count[0]} "
                                f"elapsed={time.perf_counter() - started:.1f}s"
                                f"{extra}",
                                flush=True,
                            )
                        self._preview_clip_pose(
                            bone_vectors,
                            root_translation,
                            root_rotation,
                            f"{round_label} {bone_name}",
                            force=bool(moved_frames or accepted),
                            commit=False,
                        )
                        if accepted and root_policy in ("per_accept", "accept_only"):
                            _articulated_root_interleave(
                                f"{round_label} {bone_name} root_interleave"
                            )
                    if not shared and self._early_symmetry_active(
                        self._early_symmetry_visit_counter
                    ):
                        self._early_symmetry_visit_counter += 1
                    self._preview_clip_pose(
                        bone_vectors,
                        root_translation,
                        root_rotation,
                        f"{round_label} done",
                        force=True,
                        commit=True,
                    )
                    if root_policy == "per_accept":
                        _articulated_root_interleave(f"{round_label} root_interleave")
                    multi_bone_bone_source = list(bone_indices)
                    for group_name, group_bones in self._articulated_visit_groups(
                        multi_bone_bone_source
                    ):
                        if (
                            self._early_symmetry_active(self._early_symmetry_visit_counter)
                            and str(group_name) in self._early_symmetry_secondary_groups
                        ):
                            continue
                        if multi_bone_enabled:
                            combo_chains = self._joint_chains_for_bone_set(
                                set(group_bones),
                                block_size=int(multi_block_size),
                            )
                            if combo_chains:
                                if progress and group_name != "all":
                                    print(
                                        f"gpu {label} multiBone group={group_name} "
                                        f"chains={len(combo_chains)}",
                                        flush=True,
                                    )
                                baseline_abs, baseline_unique, current_collision, zeros_keep = (
                                    self._run_joint_chain_combo_pass(
                                        combo_chains,
                                        stage_label="articulated",
                                        tag_prefix=f"{round_label} {group_name} multi",
                                        bone_vectors=bone_vectors,
                                        root_translation=root_translation,
                                        root_rotation=root_rotation,
                                        evaluation_count=evaluation_count,
                                        started=started,
                                        progress=progress,
                                        joint_last_move=joint_last_move,
                                        consensus_hops=consensus_hops,
                                        collision_veto_count=collision_veto_count,
                                        branch_groups=branch_groups,
                                        abs_weight=abs_weight,
                                        unique_weight=unique_weight,
                                        min_improvement=min_improvement,
                                        joint_limit_rad=joint_limit_rad,
                                        step_deg=step_deg,
                                        _keep_score=_keep_score,
                                        baseline_abs=baseline_abs,
                                        baseline_unique=baseline_unique,
                                        current_collision=current_collision,
                                        zeros_keep=zeros_keep,
                                        stage_mask=stage_mask,
                                        apply_temporal_consensus=apply_temporal_consensus,
                                        moved_sink=round_combo_moved,
                                    )
                                )
                                evaluation_count[0] += 1
                                if self._early_symmetry_active(
                                    self._early_symmetry_visit_counter
                                ):
                                    self._early_symmetry_mirror_group_(bone_vectors, group_name)
                        if (
                            root_policy == "primary_group_end"
                            and group_name in primary_groups
                        ):
                            _articulated_root_interleave(
                                f"{round_label} {group_name} root_group"
                            )
                    consensus_moved = 0
                    if joint_round_should_run_consensus(
                        probe_moved_count=len(round_probe_moved),
                        combo_moved_count=len(round_combo_moved),
                        shared_keep=shared,
                    ):
                        blended, consensus_moved = apply_temporal_consensus(
                            bone_vectors,
                            list(bone_indices),
                            stage_mask,
                        )
                        if consensus_moved:
                            bone_vectors.copy_(blended)
                        self._commit_live_pose_(bone_vectors, root_translation, root_rotation)
                        if consensus_moved:
                            accepted_count += 1
                            round_accepted += 1
                            evaluation_count[0] += 1
                            post_eval = self.evaluate(
                                self._bounded_bone_vectors(bone_vectors),
                                root_translation,
                                root_rotation,
                                bone_mask=stage_mask,
                            )
                            baseline_abs = post_eval["geometryScore"].detach().clone()
                            baseline_unique = post_eval["uniqueGeometryQuality"].detach().clone()
                            current_collision = post_eval["collisionError"].detach().clone()
                            zeros_keep = torch.zeros_like(baseline_abs)
                            last_clip_score = float(post_eval["score"].mean().item())
                            last_unique_err = float(
                                post_eval["uniqueGeometryError"].mean().item()
                            )
                            last_temporal = float(
                                self._temporal_penalty(
                                    self._bounded_bone_vectors(bone_vectors),
                                    root_translation,
                                    root_rotation,
                                ).detach().item()
                            )
                        if progress and (
                            consensus_moved
                            or consensus_hops["fwd"]
                            or consensus_hops["rev"]
                            or consensus_hops["idle"]
                            or consensus_hops["rev_pick"]
                        ):
                            print(
                                f"gpu {label} consensus round {round_index + 1}/{rounds}: "
                                f"score={last_clip_score:.5f} "
                                f"nConsensus={consensus_moved} "
                                f"nFwd={consensus_hops['fwd']} "
                                f"nRev={consensus_hops['rev']} "
                                f"nIdle={consensus_hops['idle']} "
                                f"nRevPick={consensus_hops['rev_pick']} "
                                f"evals={evaluation_count[0]} "
                                f"elapsed={time.perf_counter() - started:.1f}s",
                                flush=True,
                            )
                        if consensus_moved:
                            self._preview_clip_pose(
                                bone_vectors,
                                root_translation,
                                root_rotation,
                                f"{round_label} consensus",
                                force=True,
                                commit=False,
                            )
                    if followup_neighbors:
                        active_bones = list(
                            joint_round_followup_bones(
                                bone_indices,
                                list(round_probe_moved) + list(round_combo_moved),
                                anatomical_parents,
                            )
                        )
                        if not active_bones:
                            if progress:
                                print(
                                    f"gpu {label} stalled after round {round_index + 1}/"
                                    f"{rounds}; later rounds would repeat the same keep surface",
                                    flush=True,
                                )
                            break
                    elif round_accepted == 0:
                        if progress:
                            print(
                                f"gpu {label} stalled after round {round_index + 1}/"
                                f"{rounds}; later rounds would repeat the same keep surface",
                                flush=True,
                            )
                        break

            if progress:
                closing = self.evaluate(
                    self._bounded_bone_vectors(bone_vectors),
                    root_translation,
                    root_rotation,
                    bone_mask=stage_mask,
                )
                print(
                    f"gpu {label} done: accepted={accepted_count}/{visit} "
                    f"abs={opening_abs:.5f}->{float(closing['geometryScore'].mean().item()):.5f} "
                    f"uniqueErr={opening_unique_error:.5f}->{float(closing['uniqueGeometryError'].mean().item()):.5f} "
                    f"collisionVetoes={collision_veto_count[0]} "
                    f"anatomyVetoes={anatomy_veto_count[0]}",
                    flush=True,
                )
                self._write_live_status(
                    label,
                    started=started,
                    hybrid_mean=float(closing["score"].mean().item()),
                    geometry_mean=float(closing["geometryScore"].mean().item()),
                )
            self._preview_clip_pose(
                bone_vectors,
                root_translation,
                root_rotation,
                f"{label} done",
                force=True,
                commit=True,
            )

        def run_root_refit(
            *,
            label: str = "root_refit",
            include_translation: bool = True,
            rotation_axes: tuple[str, ...] | None = None,
            rotation_window_deg: float | None = None,
            rotation_step_deg: float | None = None,
        ) -> None:
            nonlocal iteration_display
            if include_translation:
                if not (
                    self.config.optimize_root_translation or self.config.optimize_root_rotation
                ):
                    return
            elif not self.config.optimize_root_rotation:
                return
            stage_mask = self._stage_bone_mask("root_refit")
            min_improvement = float(self.config.joint_keep_min_improvement)
            translation_limit = float(self.config.root_translation_limit_body_lengths)
            translation_step = float(self.config.root_refit_translation_step_body_lengths)
            translation_window = float(self.config.root_refit_translation_body_lengths)
            rotation_step = float(
                self.config.root_refit_rotation_step_deg
                if rotation_step_deg is None
                else rotation_step_deg
            )
            rotation_window = float(
                self.config.root_refit_rotation_deg
                if rotation_window_deg is None
                else rotation_window_deg
            )
            center, _half_range = self._root_rotation_center_half()
            axis_names = ("forward", "lateral", "vertical")
            rot_names = ("camera_forward", "camera_right", "camera_up")
            if rotation_axes is None:
                allowed_rotation = rot_names
            else:
                unknown = [axis for axis in rotation_axes if axis not in rot_names]
                if unknown:
                    raise ValueError(
                        "root refit rotation axis must be camera_forward, "
                        "camera_right, or camera_up"
                    )
                allowed_rotation = tuple(rotation_axes)
            with torch.no_grad():
                opening = self.evaluate(
                    self._bounded_bone_vectors(bone_vectors),
                    root_translation,
                    root_rotation,
                    bone_mask=stage_mask,
                )
                baseline_abs = opening["geometryScore"].detach().clone()
                current_collision = opening["collisionError"].detach().clone()
                zeros_keep = torch.zeros_like(baseline_abs)

                def keep_abs(abs_s, col_s):
                    return _keep_score(
                        abs_s,
                        abs_s,
                        col_s,
                        abs_weight=1.0,
                        unique_weight=0.0,
                        current_abs=baseline_abs,
                        current_unique=baseline_abs,
                        current_col=current_collision,
                        collision_enabled=bool(self.config.collision_enabled),
                    )

                def probe_root_raw(stacked_t, stacked_r, chunk_len):
                    evaluation_count[0] += 1
                    components = self.evaluate(
                        self._bounded_bone_vectors(bone_vectors.detach().repeat(chunk_len, 1, 1)),
                        stacked_t,
                        stacked_r,
                        bone_mask=stage_mask,
                    )
                    frame_count = int(bone_vectors.shape[0])
                    packed_abs = components["geometryScore"]
                    packed_col = components["collisionError"]
                    abs_out = []
                    col_out = []
                    for hyp_index in range(chunk_len):
                        start_row = hyp_index * frame_count
                        abs_out.append(packed_abs[start_row : start_row + frame_count].detach().clone())
                        col_out.append(packed_col[start_row : start_row + frame_count].detach().clone())
                    return abs_out, col_out

                def offset_translation(raw, axis_index, delta):
                    bounded = torch.tanh(raw) * translation_limit
                    current = bounded[:, axis_index]
                    new_axis = (current + float(delta)).clamp(
                        current - translation_window,
                        current + translation_window,
                    ).clamp(-translation_limit, translation_limit)
                    out = raw.detach().clone()
                    out[:, axis_index] = torch.atanh(
                        (new_axis / translation_limit).clamp(-0.999, 0.999)
                    )
                    return out

                def offset_rotation(raw, axis_index, delta_deg):
                    bounded = self._bounded_root_rotation(raw)
                    current = bounded[:, axis_index]
                    delta = math.radians(float(delta_deg))
                    window = math.radians(rotation_window)
                    axis_half = float(self._root_rotation_axis_half_radians()[int(axis_index)])
                    lo = float(center) - axis_half
                    hi = float(center) + axis_half
                    new_axis = (current + delta).clamp(current - window, current + window).clamp(lo, hi)
                    out = raw.detach().clone()
                    out[:, axis_index] = torch.atanh(
                        ((new_axis - float(center)) / max(axis_half, 1e-9)).clamp(-0.999, 0.999)
                    )
                    return out

                visits = []
                if include_translation and self.config.optimize_root_translation:
                    for axis_index, name in enumerate(axis_names):
                        if float(self.root_translation_mask[axis_index].item()) <= 0.0:
                            continue
                        if translation_step <= 1e-12 or translation_window + 1e-12 < translation_step:
                            continue
                        visits.append(("t", axis_index, name))
                if self.config.optimize_root_rotation:
                    for axis_index, name in enumerate(rot_names):
                        if name not in allowed_rotation:
                            continue
                        if float(self.root_rotation_mask[axis_index].item()) <= 0.0:
                            continue
                        if rotation_step <= 1e-12 or rotation_window + 1e-12 < rotation_step:
                            continue
                        visits.append(("r", axis_index, name))
                if not visits:
                    return
                total_visits = max(1, len(visits))
                for visit, (kind, axis_index, name) in enumerate(visits, start=1):
                    iteration_display = str(visit)
                    if kind == "t":
                        window = first_axis_window_deg(
                            translation_step,
                            rungs=max(1, int(round(translation_window / translation_step))),
                            limit_deg=translation_window,
                        )
                        current_raw = root_translation.detach().clone()
                    else:
                        window = first_axis_window_deg(
                            rotation_step,
                            rungs=max(1, int(round(rotation_window / rotation_step))),
                            limit_deg=rotation_window,
                        )
                        current_raw = root_rotation.detach().clone()
                    raw_choices = [current_raw]
                    keep_choices = [zeros_keep]
                    frame_count = int(bone_vectors.shape[0])
                    hyps_per = joint_score_hyps_per_launch(
            pose_budget=int(self.config.joint_score_raster_batch),
            frame_count=int(frame_count),
        )
                    for start in range(0, len(window), hyps_per):
                        chunk = window[start : start + hyps_per]
                        if kind == "t":
                            stacked = torch.cat(
                                [offset_translation(current_raw, axis_index, delta) for delta in chunk],
                                dim=0,
                            )
                            abs_list, col_list = probe_root_raw(
                                stacked,
                                root_rotation.detach().repeat(len(chunk), 1),
                                len(chunk),
                            )
                            raw_chunk = [
                                stacked[hyp * frame_count : (hyp + 1) * frame_count].detach().clone()
                                for hyp in range(len(chunk))
                            ]
                        else:
                            stacked = torch.cat(
                                [offset_rotation(current_raw, axis_index, delta) for delta in chunk],
                                dim=0,
                            )
                            abs_list, col_list = probe_root_raw(
                                root_translation.detach().repeat(len(chunk), 1),
                                stacked,
                                len(chunk),
                            )
                            raw_chunk = [
                                stacked[hyp * frame_count : (hyp + 1) * frame_count].detach().clone()
                                for hyp in range(len(chunk))
                            ]
                        for raw_s, abs_s, col_s in zip(raw_chunk, abs_list, col_list):
                            raw_choices.append(raw_s)
                            keep_choices.append(keep_abs(abs_s, col_s))
                    blended, winner, _chosen = gather_per_frame_winners(
                        raw_choices,
                        keep_choices,
                        min_improvement=min_improvement,
                    )
                    winner = self._lock_still_sprite_winner(winner)
                    winner = self._lock_idle_bookend_winner(winner, idle_prefix_count)
                    if kind == "t":
                        root_translation.copy_(blended)
                    else:
                        root_rotation.copy_(blended)
                    self._commit_live_pose_(bone_vectors, root_translation, root_rotation)
                    post = self.evaluate(
                        self._bounded_bone_vectors(bone_vectors),
                        root_translation,
                        root_rotation,
                        bone_mask=stage_mask,
                    )
                    evaluation_count[0] += 1
                    baseline_abs = post["geometryScore"].detach().clone()
                    current_collision = post["collisionError"].detach().clone()
                    zeros_keep = torch.zeros_like(baseline_abs)
                    moved = [int(choice) != 0 for choice in winner.detach().cpu().tolist()]
                    if progress:
                        print(
                            f"gpu {label} {visit}/{total_visits}: "
                            f"score={float(post['score'].mean().item()):.5f} "
                            f"axis={name} nMoved={sum(moved)} "
                            f"evals={evaluation_count[0]} "
                            f"elapsed={time.perf_counter() - started:.1f}s",
                            flush=True,
                        )
                    self._preview_clip_pose(
                        bone_vectors,
                        root_translation,
                        root_rotation,
                        f"{label} {name}",
                        force=False,
                    )
            self._preview_clip_pose(
                bone_vectors,
                root_translation,
                root_rotation,
                f"{label} done",
                force=True,
                commit=True,
            )

        def run_gradient_ladder() -> None:
            """Coupled all-bone step: gradient proposes, exact raster disposes.

            One backward pass on absolute sprite match gives a coupled
            direction over every search bone at once; the exact raster then
            scores each configured magnitude per frame and the normal keep
            decides. Runs early (after root refit, before articulated)
            because the gradient is strongest while the pose is far from
            the sprite; by the fine stage the same direction is plateau
            noise. A frame below the gradient floor keeps its current pose,
            and a ladder step that hurts the sprite match loses the keep,
            so the stage is fail-closed.
            """
            nonlocal iteration_display
            iterations = int(self.config.gradient_ladder_iterations)
            step_degs = tuple(float(value) for value in self.config.gradient_ladder_step_degs)
            min_norm = float(self.config.gradient_ladder_min_gradient_norm)
            joint_limit_rad = math.radians(float(self.config.joint_limit_deg))
            stage_mask = self._stage_bone_mask("ladder")
            abs_weight, unique_weight, _shared = _joint_keep_weights("articulated")
            min_improvement = float(self.config.joint_keep_min_improvement)
            bone_list = [int(index) for index in self.search_node_indices]
            frame_count = int(bone_vectors.shape[0])
            for ladder_iteration in range(iterations):
                iteration_display = f"ladder{ladder_iteration + 1}"
                with torch.enable_grad():
                    bounded_leaf = (
                        self._bounded_bone_vectors(bone_vectors.detach())
                        .detach()
                        .clone()
                        .requires_grad_(True)
                    )
                    grad_components = self.evaluate(
                        bounded_leaf,
                        root_translation.detach(),
                        root_rotation.detach(),
                        bone_mask=stage_mask,
                    )
                    geometry = grad_components["geometryScore"]
                    if not bool(torch.isfinite(geometry).all()):
                        raise RuntimeError("gpu ladder produced a non-finite absolute score")
                    geometry.sum().backward()
                    grad = bounded_leaf.grad
                    if grad is None or not bool(torch.isfinite(grad).all()):
                        raise RuntimeError("gpu ladder gradient is missing or not finite")
                    grad = grad.detach().clone()
                evaluation_count[0] += 1
                with torch.no_grad():
                    directions, norms = gradient_ladder_directions(
                        grad,
                        bone_list,
                        min_gradient_norm=min_norm,
                    )
                    active_frames = int((norms > min_norm).sum().detach().cpu().item())
                    if active_frames == 0:
                        if progress:
                            print(
                                f"gpu ladder {ladder_iteration + 1}/{iterations}: "
                                "gradient below floor on every frame; stage skipped",
                                flush=True,
                            )
                        return
                    baseline_abs = grad_components["geometryScore"].detach().clone()
                    baseline_unique = grad_components["uniqueGeometryQuality"].detach().clone()
                    current_collision = grad_components["collisionError"].detach().clone()
                    zeros_keep = torch.zeros_like(baseline_abs)
                    raw_choices = [bone_vectors.detach().clone()]
                    keep_choices = [zeros_keep]
                    meta_choices: list[float] = [0.0]
                    hyps_per = joint_score_hyps_per_launch(
            pose_budget=int(self.config.joint_score_raster_batch),
            frame_count=int(frame_count),
        )
                    for start in range(0, len(step_degs), hyps_per):
                        chunk = step_degs[start : start + hyps_per]
                        stacked_raw = torch.cat(
                            [
                                offset_raw_bounded_direction(
                                    bone_vectors.detach(),
                                    directions * math.radians(float(step_deg)),
                                    joint_limit_rad=joint_limit_rad,
                                    bone_limit_scales=self.bone_limit_scales,
                                )
                                for step_deg in chunk
                            ],
                            dim=0,
                        )
                        evaluation_count[0] += 1
                        if progress:
                            print(
                                f"gpu ladder {iteration_display} probe "
                                f"eval={evaluation_count[0]} elapsed={time.perf_counter() - started:.1f}s ...",
                                end="\r",
                                flush=True,
                            )
                        components = self.evaluate(
                            self._bounded_bone_vectors(stacked_raw),
                            root_translation.detach().repeat(len(chunk), 1),
                            root_rotation.detach().repeat(len(chunk), 1),
                            bone_mask=stage_mask,
                        )
                        packed_abs = components["geometryScore"]
                        packed_unique = components["uniqueGeometryQuality"]
                        packed_col = components["collisionError"]
                        expected = frame_count * len(chunk)
                        if int(packed_abs.numel()) != expected:
                            raise RuntimeError(
                                f"gpu ladder packed absolute scores were {int(packed_abs.numel())}, "
                                f"not {expected}"
                            )
                        for hyp_index, step_deg in enumerate(chunk):
                            start_row = hyp_index * frame_count
                            abs_s = packed_abs[start_row : start_row + frame_count]
                            unique_s = packed_unique[start_row : start_row + frame_count]
                            col_s = packed_col[start_row : start_row + frame_count]
                            if not bool(torch.isfinite(abs_s).all()):
                                raise RuntimeError(
                                    f"gpu ladder {step_deg:+.3g}° produced a non-finite absolute score"
                                )
                            raw_choices.append(
                                stacked_raw[start_row : start_row + frame_count].detach().clone()
                            )
                            keep_choices.append(
                                _keep_score(
                                    abs_s,
                                    unique_s,
                                    col_s,
                                    abs_weight=abs_weight,
                                    unique_weight=unique_weight,
                                    current_abs=baseline_abs,
                                    current_unique=baseline_unique,
                                    current_col=current_collision,
                                    collision_enabled=bool(self.config.collision_enabled),
                                )
                            )
                            meta_choices.append(float(step_deg))
                    blended, winner, _chosen = gather_per_frame_winners(
                        raw_choices,
                        keep_choices,
                        min_improvement=min_improvement,
                    )
                    winner = self._lock_still_sprite_winner(winner)
                    winner = self._lock_idle_bookend_winner(winner, idle_prefix_count)
                    self._copy_still_leading_(blended)
                    commit_pose_parameter_(bone_vectors, blended)
                    self._commit_live_pose_(bone_vectors, root_translation, root_rotation)
                    post = self.evaluate(
                        self._bounded_bone_vectors(bone_vectors),
                        root_translation,
                        root_rotation,
                        bone_mask=stage_mask,
                    )
                    evaluation_count[0] += 1
                    post_score = float(post["score"].mean().detach().item())
                    post_temporal = float(
                        self._temporal_penalty(
                            self._bounded_bone_vectors(bone_vectors),
                            root_translation,
                            root_rotation,
                        ).detach().item()
                    )
                    post_loss = 1.0 - post_score + post_temporal
                    winner_list = [int(choice) for choice in winner.detach().cpu().tolist()]
                    moved = sum(choice != 0 for choice in winner_list)
                    picked_steps = [meta_choices[choice] for choice in winner_list if choice != 0]
                    history.append(
                        {
                            "stage": "ladder",
                            "iteration": float(ladder_iteration + 1),
                            "loss": float(post_loss),
                            "score": float(post_score),
                            "temporal": float(post_temporal),
                            "accepted": bool(moved),
                            "learningRate": math.radians(max(picked_steps) if picked_steps else 0.0),
                            "rejectStreak": 0.0,
                            "attemptedLoss": float(post_loss),
                        }
                    )
                    if progress:
                        picked = ",".join(f"{value:g}" for value in picked_steps) or "-"
                        print(
                            f"gpu ladder {ladder_iteration + 1}/{iterations}: "
                            f"score={post_score:.5f} loss={post_loss:.5f} "
                            f"nMoved={moved} activeFrames={active_frames} steps={picked} "
                            f"gradNorm={float(norms.mean().detach().cpu().item()):.3g} "
                            f"evals={evaluation_count[0]} "
                            f"elapsed={time.perf_counter() - started:.1f}s",
                            flush=True,
                        )
                    self._preview_clip_pose(
                        bone_vectors,
                        root_translation,
                        root_rotation,
                        f"ladder {ladder_iteration + 1}/{iterations}",
                        force=True,
                        commit=True,
                    )

        def run_chain_space() -> None:
            """Navigate each branch in X-D joint space using the image surface.

            The active image objective proposes a coupled vector on that
            branch; the exact full-clip objective judges. Not tip IK.
            """
            from cascade_chain_space import (
                chains_for_mode,
                chain_block_directions,
                chain_block_rms_directions,
                equal_share_chain_directions,
                select_clipwide_trust_candidate,
                trust_region_backtracking_steps,
            )

            nonlocal iteration_display
            mode = str(self.config.chain_space_mode)
            dinov3_autograd = bool(
                self.config.uses_dinov3_dense_score()
                and self.config.dense_semantic_autograd_enabled
            )
            iterations = int(self.config.chain_space_iterations)
            eval_budget = self.config.chain_space_eval_budget
            if eval_budget is not None:
                eval_budget = int(eval_budget)
            step_degs = tuple(float(value) for value in self.config.chain_space_step_degs)
            min_norm = float(self.config.chain_space_min_gradient_norm)
            joint_limit_rad = math.radians(float(self.config.joint_limit_deg))
            stage_mask = self._stage_bone_mask("chainspace")
            abs_weight, unique_weight, _shared = _joint_keep_weights("articulated")
            min_improvement = (
                float(self.config.chain_space_min_clip_improvement)
                if dinov3_autograd
                else float(self.config.joint_keep_min_improvement)
            )
            search = [int(index) for index in self.search_node_indices]
            groups = chains_for_mode(
                mode,
                parents=self.parents,
                search_indices=search,
                node_depths=self.node_depths,
            )
            names = [
                [str(self.node_names[int(index)]) for index in chain]
                for chain in groups
            ]
            branch_groups.extend(
                {
                    "group": int(group_index),
                    "mode": mode,
                    "kind": (
                        "branch_vector"
                        if dinov3_autograd
                        else "chain_space"
                    ),
                    "indices": [int(index) for index in chain],
                    "bones": list(names[group_index]),
                }
                for group_index, chain in enumerate(groups)
            )
            if progress:
                print(
                    f"gpu chainspace mode={mode} groups={len(groups)} "
                    f"search={len(search)} first={','.join(names[0][:4])}"
                    + (
                        f" evalBudget={eval_budget}"
                        if eval_budget is not None
                        else ""
                    ),
                    flush=True,
                )
            trust_radii = [float(self.config.chain_space_trust_radius_deg) for _ in groups]
            radius_min = float(self.config.chain_space_trust_radius_min_deg)
            radius_max = float(self.config.chain_space_trust_radius_max_deg)
            frame_count = int(bone_vectors.shape[0])
            hyps_per = joint_score_hyps_per_launch(
            pose_budget=int(self.config.joint_score_raster_batch),
            frame_count=int(frame_count),
        )

            def _backward_grad():
                with torch.enable_grad():
                    bounded_leaf = (
                        self._bounded_bone_vectors(bone_vectors.detach())
                        .detach()
                        .clone()
                        .requires_grad_(True)
                    )
                    if dinov3_autograd:
                        quality_chunks = []
                        microbatch = int(self.config.dense_semantic_batch_size)
                        for start in range(0, frame_count, microbatch):
                            end = min(start + microbatch, frame_count)
                            evaluation_count[0] += 1
                            chunk_components = self.evaluate(
                                bounded_leaf[start:end],
                                root_translation.detach()[start:end],
                                root_rotation.detach()[start:end],
                                frame_indices=self.frame_indices[start:end],
                                bone_mask=stage_mask,
                                dense_semantic_autograd=True,
                            )
                            quality = chunk_components["score"]
                            if not bool(torch.isfinite(quality).all()):
                                raise RuntimeError(
                                    "DINOv3 chain-space produced a non-finite quality"
                                )
                            (quality.sum() / float(frame_count)).backward()
                            quality_chunks.append(quality.detach())
                        temporal = self._temporal_penalty(
                            bounded_leaf,
                            root_translation.detach(),
                            root_rotation.detach(),
                        )
                        if not bool(torch.isfinite(temporal)):
                            raise RuntimeError(
                                "DINOv3 chain-space produced a non-finite temporal penalty"
                            )
                        (-temporal).backward()
                        grad = bounded_leaf.grad
                        if grad is None or not bool(torch.isfinite(grad).all()):
                            raise RuntimeError(
                                "DINOv3 chain-space gradient is missing or not finite"
                            )
                        qualities = torch.cat(quality_chunks, dim=0)
                        return grad.detach().clone(), {
                            "score": qualities,
                            "geometryScore": qualities,
                            "uniqueGeometryQuality": qualities,
                            "collisionError": torch.zeros_like(qualities),
                            "clipObjective": qualities.mean() - temporal.detach(),
                            "temporalPenalty": temporal.detach(),
                        }
                    grad_components = self.evaluate(
                        bounded_leaf,
                        root_translation.detach(),
                        root_rotation.detach(),
                        bone_mask=stage_mask,
                    )
                    geometry = grad_components["geometryScore"]
                    if not bool(torch.isfinite(geometry).all()):
                        raise RuntimeError("gpu chainspace produced a non-finite absolute score")
                    geometry.sum().backward()
                    grad = bounded_leaf.grad
                    if grad is None or not bool(torch.isfinite(grad).all()):
                        raise RuntimeError("gpu chainspace gradient is missing or not finite")
                    return grad.detach().clone(), grad_components

            def _evaluate_dinov3_clip(raw_pose):
                bounded = self._bounded_bone_vectors(raw_pose)
                quality_chunks = []
                microbatch = int(self.config.dense_semantic_batch_size)
                with torch.no_grad():
                    for start in range(0, frame_count, microbatch):
                        end = min(start + microbatch, frame_count)
                        evaluation_count[0] += 1
                        components = self.evaluate(
                            bounded[start:end],
                            root_translation.detach()[start:end],
                            root_rotation.detach()[start:end],
                            frame_indices=self.frame_indices[start:end],
                            bone_mask=stage_mask,
                        )
                        quality_chunks.append(components["score"].detach())
                    qualities = torch.cat(quality_chunks, dim=0)
                    temporal = self._temporal_penalty(
                        bounded,
                        root_translation.detach(),
                        root_rotation.detach(),
                    ).detach()
                    objective = qualities.mean() - temporal
                if not bool(torch.isfinite(objective)):
                    raise RuntimeError(
                        "DINOv3 chain-space candidate produced a non-finite clip objective"
                    )
                return qualities, temporal, objective

            def _pack_keep(raw_hyps, *, baseline_abs, baseline_unique, current_collision):
                raw_choices = [bone_vectors.detach().clone()]
                keep_choices = [torch.zeros_like(baseline_abs)]
                meta_choices: list[float] = [0.0]
                for start in range(0, len(raw_hyps), hyps_per):
                    chunk = raw_hyps[start : start + hyps_per]
                    stacked_raw = torch.cat([item for item, _meta in chunk], dim=0)
                    evaluation_count[0] += 1
                    components = self.evaluate(
                        self._bounded_bone_vectors(stacked_raw),
                        root_translation.detach().repeat(len(chunk), 1),
                        root_rotation.detach().repeat(len(chunk), 1),
                        bone_mask=stage_mask,
                    )
                    packed_abs = components["geometryScore"]
                    packed_unique = components["uniqueGeometryQuality"]
                    packed_col = components["collisionError"]
                    expected = frame_count * len(chunk)
                    if int(packed_abs.numel()) != expected:
                        raise RuntimeError(
                            f"gpu chainspace packed scores were {int(packed_abs.numel())}, "
                            f"not {expected}"
                        )
                    for hyp_index, (_raw, meta) in enumerate(chunk):
                        start_row = hyp_index * frame_count
                        abs_s = packed_abs[start_row : start_row + frame_count]
                        unique_s = packed_unique[start_row : start_row + frame_count]
                        col_s = packed_col[start_row : start_row + frame_count]
                        if not bool(torch.isfinite(abs_s).all()):
                            raise RuntimeError("gpu chainspace produced a non-finite keep score")
                        raw_choices.append(
                            stacked_raw[start_row : start_row + frame_count].detach().clone()
                        )
                        keep_choices.append(
                            _keep_score(
                                abs_s,
                                unique_s,
                                col_s,
                                abs_weight=abs_weight,
                                unique_weight=unique_weight,
                                current_abs=baseline_abs,
                                current_unique=baseline_unique,
                                current_col=current_collision,
                                collision_enabled=bool(self.config.collision_enabled),
                            )
                        )
                        meta_choices.append(float(meta))
                return raw_choices, keep_choices, meta_choices

            for sweep in range(iterations):
                if eval_budget is not None and evaluation_count[0] >= eval_budget:
                    break
                iteration_display = f"chainspace{sweep + 1}"
                moved_any = False
                for group_index, chain in enumerate(groups):
                    if eval_budget is not None and evaluation_count[0] >= eval_budget:
                        break
                    bones = [int(index) for index in chain]
                    if not dinov3_autograd:
                        evaluation_count[0] += 1
                    grad, grad_components = _backward_grad()
                    baseline_abs = grad_components["geometryScore"].detach().clone()
                    baseline_unique = grad_components["uniqueGeometryQuality"].detach().clone()
                    current_collision = grad_components["collisionError"].detach().clone()
                    radius = float(trust_radii[group_index])
                    if mode == "chain_grad":
                        directions, norms = equal_share_chain_directions(
                            grad, bones, min_gradient_norm=min_norm
                        )
                        clip_norm = None
                        hyp_steps = list(step_degs)
                    elif mode == "branch_trust":
                        if dinov3_autograd:
                            directions, norms, clip_norm = chain_block_rms_directions(
                                grad, bones, min_gradient_norm=min_norm
                            )
                        else:
                            directions, norms = chain_block_directions(
                                grad, bones, min_gradient_norm=min_norm
                            )
                            clip_norm = None
                        hyp_steps = list(
                            trust_region_backtracking_steps(radius, radius_min)
                        )
                    else:
                        directions, norms = chain_block_directions(
                            grad, bones, min_gradient_norm=min_norm
                        )
                        clip_norm = None
                        hyp_steps = list(step_degs)
                    active_frames = int((norms > min_norm).sum().detach().cpu().item())
                    gradient_plateau = (
                        float(clip_norm.detach().cpu().item()) <= min_norm
                        if clip_norm is not None
                        else active_frames == 0
                    )
                    if gradient_plateau:
                        chain_space_history.append(
                            {
                                "stage": "chain_space",
                                "mode": mode,
                                "sweep": sweep + 1,
                                "group": group_index,
                                "bones": names[group_index],
                                "skipped": "gradient_floor",
                                "activeFrames": int(active_frames),
                                "gradNormRms": (
                                    float(clip_norm.detach().cpu().item())
                                    if clip_norm is not None
                                    else 0.0
                                ),
                            }
                        )
                        continue
                    hyps = [
                        (
                            offset_raw_bounded_direction(
                                bone_vectors.detach(),
                                directions * math.radians(float(step_deg)),
                                joint_limit_rad=joint_limit_rad,
                                bone_limit_scales=self.bone_limit_scales,
                            ),
                            float(step_deg),
                        )
                        for step_deg in hyp_steps
                    ]
                    if dinov3_autograd:
                        baseline_quality, baseline_temporal_tensor, baseline_objective_tensor = (
                            _evaluate_dinov3_clip(bone_vectors.detach())
                        )
                        baseline_objective = float(
                            baseline_objective_tensor.detach().cpu().item()
                        )
                        candidate_results = [
                            _evaluate_dinov3_clip(raw_pose) for raw_pose, _step_deg in hyps
                        ]
                        candidate_objectives = [
                            float(objective.detach().cpu().item())
                            for _qualities, _temporal, objective in candidate_results
                        ]
                        winner_index = select_clipwide_trust_candidate(
                            baseline_objective,
                            candidate_objectives,
                            min_improvement=min_improvement,
                        )
                        accepted = winner_index >= 0
                        selected_step = 0.0
                        selected_score = float(
                            baseline_quality.mean().detach().cpu().item()
                        )
                        selected_temporal = float(
                            baseline_temporal_tensor.detach().cpu().item()
                        )
                        selected_objective = baseline_objective
                        if accepted:
                            selected_raw, selected_step = hyps[winner_index]
                            selected_quality, selected_temporal_tensor, selected_objective_tensor = (
                                candidate_results[winner_index]
                            )
                            commit_pose_parameter_(bone_vectors, selected_raw)
                            self._commit_live_pose_(
                                bone_vectors, root_translation, root_rotation
                            )
                            selected_score = float(
                                selected_quality.mean().detach().cpu().item()
                            )
                            selected_temporal = float(
                                selected_temporal_tensor.detach().cpu().item()
                            )
                            selected_objective = float(
                                selected_objective_tensor.detach().cpu().item()
                            )
                            moved_any = True
                            trust_radii[group_index] = min(
                                max(selected_step * 1.5, radius_min),
                                radius_max,
                            )
                        else:
                            # This visit already tested every half step down to
                            # the floor. Revisit from the floor only after
                            # another branch changes the objective surface.
                            trust_radii[group_index] = radius_min
                        chain_space_history.append(
                            {
                                "stage": "chain_space",
                                "mode": mode,
                                "objective": "dinov3_mean_minus_temporal",
                                "acceptance": "whole_clip_atomic",
                                "normalization": "full_clip_branch_block_rms",
                                "sweep": sweep + 1,
                                "group": group_index,
                                "bones": names[group_index],
                                "accepted": bool(accepted),
                                "nMoved": frame_count if accepted else 0,
                                "activeFrames": int(active_frames),
                                "gradNormRms": (
                                    float(clip_norm.detach().cpu().item())
                                    if clip_norm is not None
                                    else float(norms.mean().detach().cpu().item())
                                ),
                                "baselineObjective": float(baseline_objective),
                                "candidateStepDegs": [
                                    float(step_deg) for step_deg in hyp_steps
                                ],
                                "candidateObjectives": candidate_objectives,
                                "selectedObjective": float(selected_objective),
                                "selectedScore": float(selected_score),
                                "selectedTemporal": float(selected_temporal),
                                "selectedStepDeg": float(selected_step),
                                "trustRadius": float(radius),
                                "proposalTrustRadius": float(radius),
                                "nextTrustRadius": float(trust_radii[group_index]),
                            }
                        )
                        if progress:
                            print(
                                f"gpu DINOv3 branch-vector g{group_index + 1}/{len(groups)} "
                                f"sweep {sweep + 1}/{iterations}: "
                                f"accepted={int(accepted)} step={selected_step:g} "
                                f"objective={selected_objective:.6f} "
                                f"score={selected_score:.6f} "
                                f"evals={evaluation_count[0]} "
                                f"elapsed={time.perf_counter() - started:.1f}s",
                                flush=True,
                            )
                        self._preview_clip_pose(
                            bone_vectors,
                            root_translation,
                            root_rotation,
                            f"DINOv3 branch-vector {group_index + 1}/{len(groups)}",
                            force=True,
                            commit=True,
                        )
                        continue
                    raw_choices, keep_choices, meta_choices = _pack_keep(
                        hyps,
                        baseline_abs=baseline_abs,
                        baseline_unique=baseline_unique,
                        current_collision=current_collision,
                    )
                    blended, winner, _chosen = gather_per_frame_winners(
                        raw_choices,
                        keep_choices,
                        min_improvement=min_improvement,
                    )
                    winner = self._lock_still_sprite_winner(winner)
                    winner = self._lock_idle_bookend_winner(winner, idle_prefix_count)
                    self._copy_still_leading_(blended)
                    commit_pose_parameter_(bone_vectors, blended)
                    self._commit_live_pose_(bone_vectors, root_translation, root_rotation)
                    winner_list = [int(choice) for choice in winner.detach().cpu().tolist()]
                    moved = sum(choice != 0 for choice in winner_list)
                    if moved:
                        moved_any = True
                    if mode == "branch_trust":
                        if moved * 2 >= frame_count:
                            trust_radii[group_index] = min(radius * 1.5, radius_max)
                        elif moved == 0:
                            trust_radii[group_index] = max(radius * 0.5, radius_min)
                    record = {
                        "stage": "chain_space",
                        "mode": mode,
                        "sweep": sweep + 1,
                        "group": group_index,
                        "bones": names[group_index],
                        "nMoved": int(moved),
                        "activeFrames": int(active_frames),
                        "gradNorm": float(norms.mean().detach().cpu().item()),
                    }
                    if mode == "branch_trust":
                        record["trustRadius"] = float(trust_radii[group_index])
                    chain_space_history.append(record)
                    if progress:
                        last = chain_space_history[-1]
                        print(
                            f"gpu chainspace {mode} g{group_index + 1}/{len(groups)} "
                            f"sweep {sweep + 1}/{iterations}: {last} "
                            f"evals={evaluation_count[0]} "
                            f"elapsed={time.perf_counter() - started:.1f}s",
                            flush=True,
                        )
                    self._preview_clip_pose(
                        bone_vectors,
                        root_translation,
                        root_rotation,
                        f"chainspace {mode} {group_index + 1}/{len(groups)}",
                        force=True,
                        commit=True,
                    )
                if eval_budget is None and not moved_any:
                    if progress:
                        print(
                            f"gpu chainspace {mode} sweep {sweep + 1} accepted no branch; stop",
                            flush=True,
                        )
                    break
            if eval_budget is not None and evaluation_count[0] < eval_budget:
                raise RuntimeError(
                    f"gpu chainspace ended at {evaluation_count[0]} evals, "
                    f"below chain_space_eval_budget={eval_budget}; "
                    "raise chain_space_iterations"
                )
            # Per-frame image keep can pick 0° on one frame and 40° on the
            # next. That is the jerk. Consensus copies a neighbor pose only
            # when the motion-led sprite score stays inside the tie budget.
            # One finish pass, not per-group: independent bone walks cost
            # clip evals, and chain-space already spent the raster budget
            # on the surface steps.
            iteration_display = "chainspace_consensus"
            with torch.no_grad():
                consensus_pose, consensus_moved = apply_temporal_consensus(
                    bone_vectors,
                    [int(index) for index in self.search_node_indices],
                    stage_mask,
                )
            if consensus_moved:
                commit_pose_parameter_(bone_vectors, consensus_pose)
                self._commit_live_pose_(
                    bone_vectors, root_translation, root_rotation
                )
            chain_space_history.append(
                {
                    "stage": "chain_space",
                    "mode": mode,
                    "finish": "temporal_consensus",
                    "consensusMoved": int(consensus_moved),
                }
            )
            if progress:
                print(
                    f"gpu chainspace {mode} consensusMoved={int(consensus_moved)} "
                    f"evals={evaluation_count[0]} "
                    f"elapsed={time.perf_counter() - started:.1f}s",
                    flush=True,
                )

        def run_simulated_annealing() -> None:
            """Broad-pose search: random restarts with Metropolis acceptance.

            Every other cascade stage starts from bind and makes local moves.
            When the correct pose is in a different basin (limb swapped,
            weapon turned), no local step escapes. SA explores globally: each
            restart samples a random pose within joint limits, then iterates
            with geometric cooling. Perturbation magnitude and bone count
            both scale with temperature, so early iterations move many bones
            by large angles (broad strokes) and late iterations move few
            bones by small angles (basin settling). Metropolis acceptance
            lets worsening moves through with probability exp(delta/T),
            which is how the search crosses between basins. Per-frame
            independent chains: each frame finds its own basin against its
            own sprite target. Temporal consistency is downstream's job.
            Root is not perturbed; root search + Adam already handle
            placement. Fail-closed: if SA is disabled or all restarts
            produce worse poses, the current pose is preserved.
            """
            nonlocal iteration_display
            restarts = int(self.config.sa_restarts)
            iterations = int(self.config.sa_iterations)
            t_start = float(self.config.sa_initial_temperature)
            t_end = float(self.config.sa_final_temperature)
            perturb_deg = float(self.config.sa_perturbation_scale_deg)
            bone_frac = float(self.config.sa_bone_fraction)
            seed = self.config.sa_seed
            joint_limit_rad = math.radians(float(self.config.joint_limit_deg))
            stage_mask = self._stage_bone_mask("annealing")
            frame_count = int(bone_vectors.shape[0])
            node_count = int(bone_vectors.shape[1])
            search_list = [int(index) for index in self._sa_search_node_indices()]
            if not search_list:
                if progress:
                    print("gpu annealing: no distal search bones; stage skipped", flush=True)
                return
            sa_collision_weight = self.config.sa_collision_weight

            generator = torch.Generator(device=self.device)
            if seed is not None:
                generator.manual_seed(int(seed))

            # Track the best pose per frame across all restarts.
            best_raw = bone_vectors.detach().clone()
            best_scores = self.evaluate(
                self._bounded_bone_vectors(bone_vectors),
                root_translation.detach(),
                root_rotation.detach(),
                bone_mask=stage_mask,
                collision_weight_override=sa_collision_weight,
            )["score"].detach().clone()
            evaluation_count[0] += 1
            baseline_scores = best_scores.clone()
            baseline_mean = float(best_scores.mean().item())
            baseline_min = float(best_scores.min().item())
            baseline_max = float(best_scores.max().item())
            if progress:
                print(
                    f"gpu annealing baseline: "
                    f"mean={baseline_mean:.5f} min={baseline_min:.5f} max={baseline_max:.5f}",
                    flush=True,
                )

            for restart in range(restarts):
                iteration_display = f"anneal-r{restart + 1}"
                if bool(self.config.sa_seed_from_current):
                    current_raw = best_raw.detach().clone()
                    current_raw = sa_perturb_pose(
                        current_raw,
                        1.0,
                        bone_frac,
                        perturb_deg,
                        search_list,
                        joint_limit_rad,
                        self.bone_limit_scales,
                        generator,
                    )
                else:
                    current_raw = sa_random_initial_pose(
                        frame_count,
                        node_count,
                        search_list,
                        joint_limit_rad,
                        self.bone_limit_scales,
                        self.device,
                        generator,
                    )
                current_scores = self.evaluate(
                    self._bounded_bone_vectors(current_raw),
                    root_translation.detach(),
                    root_rotation.detach(),
                    bone_mask=stage_mask,
                    collision_weight_override=sa_collision_weight,
                )["score"].detach().clone()
                evaluation_count[0] += 1
                init_mean = float(current_scores.mean().item())
                init_min = float(current_scores.min().item())
                init_max = float(current_scores.max().item())

                # Update best from this restart's initial pose.
                improved = current_scores > best_scores
                n_init_better = int(improved.sum().item())
                if bool(improved.any()):
                    best_raw = torch.where(
                        improved.view(-1, 1, 1),
                        current_raw,
                        best_raw,
                    )
                    best_scores = torch.where(improved, current_scores, best_scores)

                if progress:
                    print(
                        f"gpu annealing r{restart + 1}/{restarts} init: "
                        f"mean={init_mean:.5f} min={init_min:.5f} max={init_max:.5f} "
                        f"framesBetterThanBaseline={n_init_better}/{frame_count}",
                        flush=True,
                    )

                accepted_count = 0
                total_steps = 0
                for step in range(iterations):
                    temperature = sa_temperature(step, iterations, t_start, t_end)
                    norm_t = temperature / t_start
                    proposed_raw = sa_perturb_pose(
                        current_raw,
                        norm_t,
                        bone_frac,
                        perturb_deg,
                        search_list,
                        joint_limit_rad,
                        self.bone_limit_scales,
                        generator,
                    )
                    # Pack current + proposed into one evaluate call (2F poses).
                    packed_raw = torch.cat([current_raw, proposed_raw], dim=0)
                    packed_root_t = root_translation.detach().repeat(2, 1)
                    packed_root_r = root_rotation.detach().repeat(2, 1)
                    packed_scores = self.evaluate(
                        self._bounded_bone_vectors(packed_raw),
                        packed_root_t,
                        packed_root_r,
                        bone_mask=stage_mask,
                        collision_weight_override=sa_collision_weight,
                    )["score"].detach()
                    evaluation_count[0] += 1
                    current_scores_packed = packed_scores[:frame_count]
                    proposed_scores_packed = packed_scores[frame_count:]

                    accept = sa_metropolis_accept(
                        current_scores_packed,
                        proposed_scores_packed,
                        temperature,
                        generator,
                    )
                    accepted_count += int(accept.sum().item())
                    total_steps += frame_count

                    current_raw = torch.where(
                        accept.view(-1, 1, 1),
                        proposed_raw,
                        current_raw,
                    )
                    current_scores = torch.where(
                        accept,
                        proposed_scores_packed,
                        current_scores_packed,
                    )

                    # Update best.
                    improved = current_scores > best_scores
                    if bool(improved.any()):
                        best_raw = torch.where(
                            improved.view(-1, 1, 1),
                            current_raw,
                            best_raw,
                        )
                        best_scores = torch.where(improved, current_scores, best_scores)

                    if progress and (step + 1) % max(1, iterations // 4) == 0:
                        print(
                            f"gpu annealing r{restart + 1}/{restarts} "
                            f"step {step + 1}/{iterations} "
                            f"T={temperature:.4f} "
                            f"accept={accepted_count}/{total_steps} "
                            f"eval={evaluation_count[0]} "
                            f"elapsed={time.perf_counter() - started:.1f}s ...",
                            end="\r",
                            flush=True,
                        )

                # After this restart, commit the best found so far.
                commit_pose_parameter_(bone_vectors, best_raw)
                self._commit_live_pose_(bone_vectors, root_translation, root_rotation)
                post = self.evaluate(
                    self._bounded_bone_vectors(bone_vectors),
                    root_translation,
                    root_rotation,
                    bone_mask=stage_mask,
                    collision_weight_override=sa_collision_weight,
                )
                evaluation_count[0] += 1
                post_score = float(post["score"].mean().detach().item())
                post_temporal = float(
                    self._temporal_penalty(
                        self._bounded_bone_vectors(bone_vectors),
                        root_translation,
                        root_rotation,
                    ).detach().item()
                )
                post_loss = 1.0 - post_score + post_temporal
                accept_rate = accepted_count / max(total_steps, 1)
                best_mean = float(best_scores.mean().item())
                best_min = float(best_scores.min().item())
                best_max = float(best_scores.max().item())
                n_best_better = int((best_scores > baseline_scores).sum().item())
                history.append(
                    {
                        "stage": "annealing",
                        "iteration": float(restart + 1),
                        "loss": float(post_loss),
                        "score": float(post_score),
                        "temporal": float(post_temporal),
                        "accepted": bool(accepted_count > 0),
                        "learningRate": float(t_end),
                        "rejectStreak": 0.0,
                        "attemptedLoss": float(post_loss),
                        "acceptRate": float(accept_rate),
                    }
                )
                if progress:
                    print(
                        f"gpu annealing r{restart + 1}/{restarts}: "
                        f"score={post_score:.5f} loss={post_loss:.5f} "
                        f"acceptRate={accept_rate:.3f} "
                        f"bestMean={best_mean:.5f} bestMin={best_min:.5f} bestMax={best_max:.5f} "
                        f"framesAboveBaseline={n_best_better}/{frame_count} "
                        f"evals={evaluation_count[0]} "
                        f"elapsed={time.perf_counter() - started:.1f}s",
                        flush=True,
                    )
                self._preview_clip_pose(
                    bone_vectors,
                    root_translation,
                    root_rotation,
                    f"annealing r{restart + 1}/{restarts}",
                    force=True,
                    commit=True,
                )

        def run_ik_initialization() -> None:
            """IK-based broad-pose initialization from sticks or silhouette misses.

            ``authored`` loads keypoints.json and bone_roles.json, then runs bounded
            CCD on those stick chains.

            ``silhouette_miss`` pairs each red excess blob with a blue missing blob,
            attributes the red region by skinning influence, then searches local
            joint axes on the assigned bone. If regional IoU stays below the blob
            target, one parent is unlocked at a time. Spinal bones use a small
            rotation cap. The best interim chain length is kept.
            """
            nonlocal iteration_display
            iteration_display = "ik"
            keypoints_path = self.config.ik_keypoints_path
            bone_roles_path = self.config.ik_bone_roles_path
            iterations = int(self.config.ik_iterations)
            max_step_rad = math.radians(float(self.config.ik_max_step_deg))
            joint_limit_rad = math.radians(float(self.config.joint_limit_deg))

            pre = self.evaluate(
                self._bounded_bone_vectors(bone_vectors),
                root_translation,
                root_rotation,
                bone_mask=self._stage_bone_mask("annealing"),
            )
            evaluation_count[0] += 1
            pre_score = float(pre["score"].mean().detach().item())
            pre_temporal = float(
                self._temporal_penalty(
                    self._bounded_bone_vectors(bone_vectors),
                    root_translation,
                    root_rotation,
                ).detach().item()
            )
            pre_loss = 1.0 - pre_score + pre_temporal
            pre_pose = bone_vectors.detach().clone()
            blob_reports: list[dict[str, Any]] = []
            ik_pose = bone_vectors.detach().clone()
            keypoints_source = str(self.config.ik_keypoints_source)

            if keypoints_source == "silhouette_miss":
                from ik_incremental_blob import (
                    chain_prefixes,
                    distal_first_parent_chain,
                    grow_chain_keep_best,
                    region_iou,
                    search_chain_local_axes,
                    step_deg_for_bone_depth,
                )

                from ik_dynamic_policy import (
                    dynamic_stop_score,
                    filter_chain_prefixes,
                    scale_step_deg,
                )

                score_mode = str(self.config.ik_silhouette_score_mode)
                outer_passes = int(self.config.ik_iterations)
                directions = joint_search_directions(
                    self.config.joint_search_axes,
                    int(self.config.joint_diagonal_axes),
                )
                predicted_threshold = float(self.config.ik_miss_predicted_alpha_threshold)
                target_score = float(self.config.ik_blob_iou_target)
                stage_mask = self._stage_bone_mask("annealing")
                cheap_occupancy = bool(self.config.cheap_joint_probe_occupancy_only)
                idle_prefix_count = int(getattr(self.config, "idle_prefix_frames", 0) or 0)
                idle_suffix_count = int(getattr(self.config, "idle_suffix_frames", 0) or 0)
                cheap_keep_count = int(self.config.cheap_joint_probe_frame_count)
                def _preview_ik_pose(
                    frame_pose,
                    *,
                    _frame_index: int,
                    _frame_position: int,
                    _label: str,
                ) -> None:
                    preview_bones = ik_pose.detach().clone()
                    row = frame_pose[0] if int(frame_pose.ndim) == 2 else frame_pose
                    preview_bones[_frame_position] = row.detach().clone()
                    self._refresh_live_preview(
                        frame_index=int(_frame_index),
                        frame_position=int(_frame_position),
                        label=str(_label),
                        bone_vectors=preview_bones,
                        root_translation=root_translation,
                        root_rotation=root_rotation,
                        force=True,
                    )

                for pass_index in range(outer_passes):
                    jobs_by_position = derive_ik_blob_jobs(
                        self,
                        ik_pose,
                        root_translation,
                        root_rotation,
                    )
                    if not any(jobs_by_position.values()):
                        if int(pass_index) == 0:
                            raise RuntimeError(
                                "IK keypoints (silhouette_miss) have no frames in common with the clip "
                                f"(clip={list(self.frame_indices)}; silhouette_miss found no pairs)"
                            )
                        break
                    blob_count = sum(len(jobs) for jobs in jobs_by_position.values())
                    if progress:
                        print(
                            f"gpu ik: source=silhouette_miss keypoints=dynamic roles=skeleton "
                            f"pass={int(pass_index) + 1}/{outer_passes} "
                            f"scoreMode={score_mode} "
                            f"jobOrder={self.config.ik_job_order_mode} "
                            f"stepScale={self.config.ik_step_scale_mode} "
                            f"frameOrder={self.config.ik_frame_order_mode} "
                            f"frames={len(jobs_by_position)}/{len(self.frame_indices)} "
                            f"blobs={blob_count} solver=incremental_blob",
                            flush=True,
                        )
                    pass_opening = self.evaluate(
                        self._bounded_bone_vectors(ik_pose),
                        root_translation,
                        root_rotation,
                        bone_mask=stage_mask,
                    )
                    evaluation_count[0] += 1
                    pass_frame_scores = [
                        float(value)
                        for value in pass_opening["score"].detach().cpu().tolist()
                    ]
                    if str(self.config.ik_frame_order_mode) == "deficit":
                        frame_positions = sorted(
                            range(len(self.frame_indices)),
                            key=lambda position: pass_frame_scores[int(position)],
                        )
                    else:
                        frame_positions = list(range(len(self.frame_indices)))
                    cheap_frame_positions = None
                    if cheap_occupancy:
                        from cascade_cheap_probe import cheap_probe_positions

                        cheap_frame_positions = cheap_probe_positions(
                            pass_frame_scores,
                            prefix=idle_prefix_count,
                            suffix=idle_suffix_count,
                            keep_count=cheap_keep_count,
                        )
                        if progress:
                            print(
                                "gpu ik cheapProbe occupancyOnly "
                                f"pass={int(pass_index) + 1}/{outer_passes} "
                                f"frames={len(cheap_frame_positions)} "
                                f"keepCount={cheap_keep_count} "
                                f"ids={[int(self.frame_indices[i]) for i in cheap_frame_positions]}",
                                flush=True,
                            )
                    for frame_position in frame_positions:
                        if int(frame_position) > 0:
                            self._seed_transit_pose_from_previous_(
                                ik_pose,
                                root_translation,
                                root_rotation,
                                frame_position=int(frame_position),
                                only_if_bind=True,
                            )
                        if (
                            cheap_frame_positions is not None
                            and int(frame_position) not in cheap_frame_positions
                        ):
                            continue
                        frame_index = int(self.frame_indices[int(frame_position)])
                        jobs = jobs_by_position.get(int(frame_position), [])
                        if not jobs:
                            continue
                        frame_deficit = max(
                            0.0,
                            1.0 - float(pass_frame_scores[int(frame_position)]),
                        )
                        target_mask = self.target_masks[frame_position].detach().cpu().numpy()
                        frame_root_t = root_translation[frame_position : frame_position + 1]
                        frame_root_r = root_rotation[frame_position : frame_position + 1]
                        current = ik_pose[frame_position].detach().clone()
                        _preview_ik_pose(
                            current,
                            _frame_index=int(frame_index),
                            _frame_position=int(frame_position),
                            _label=(
                                f"ik f{int(frame_index):02d} pass={int(pass_index) + 1} "
                                f"start blobs={len(jobs)}"
                            ),
                        )
                        for job in jobs:
                            chain = distal_first_parent_chain(
                                int(job.bone_index),
                                self.parents,
                                max_joints=int(self.config.ik_max_chain_depth),
                            )
                            prefixes = filter_chain_prefixes(
                                chain_prefixes(chain),
                                mode=str(self.config.ik_chain_start_mode),
                                displacement_px=float(job.tip_displacement_px),
                                ref_px=float(self.config.ik_chain_displacement_ref_px),
                            )
                            region = np.asarray(job.repair_region, dtype=bool)

                            if score_mode == "frame_hybrid":
                                def score_batch(
                                    stacked,
                                    *,
                                    _frame_position=frame_position,
                                ):
                                    batch = int(stacked.shape[0])
                                    scores: list[float] = []
                                    for index in range(batch):
                                        trial_clip = ik_pose.detach().clone()
                                        trial_clip[_frame_position] = stacked[index]
                                        bounded = self._bounded_bone_vectors(trial_clip)
                                        post = self.evaluate(
                                            bounded,
                                            root_translation,
                                            root_rotation,
                                            bone_mask=stage_mask,
                                            occupancy_only=cheap_occupancy,
                                        )
                                        evaluation_count[0] += 1
                                        scores.append(
                                            float(
                                                post["score"][_frame_position].detach().item()
                                            )
                                        )
                                    return scores
                            else:
                                def score_batch(
                                    stacked,
                                    *,
                                    _region=region,
                                    _target=target_mask,
                                ):
                                    batch = int(stacked.shape[0])
                                    bounded = self._bounded_bone_vectors(stacked)
                                    alpha, _depth = self._exact_triangle_raster(
                                        bounded,
                                        frame_root_t.expand(batch, -1),
                                        frame_root_r.expand(batch, -1),
                                        bone_mask=self.active_node_mask,
                                    )
                                    evaluation_count[0] += 1
                                    predicted = alpha.detach().cpu().numpy()
                                    return [
                                        region_iou(
                                            predicted[index],
                                            _target,
                                            _region,
                                            predicted_threshold=predicted_threshold,
                                        )
                                        for index in range(batch)
                                    ]

                            opening_scores = score_batch(current.unsqueeze(0))
                            opening_score = float(opening_scores[0])
                            score_label = "score" if score_mode == "frame_hybrid" else "iou"
                            job_target_score = float(target_score)
                            if bool(self.config.ik_dynamic_stop_enabled):
                                job_target_score = dynamic_stop_score(
                                    opening_score,
                                    target_score,
                                    displacement_px=float(job.tip_displacement_px),
                                    ref_px=float(self.config.ik_step_displacement_ref_px),
                                )

                            def search_prefix(pose_frame, prefix, *, _job=job):
                                step_rad_by_index = {}
                                for index in prefix:
                                    base_deg = step_deg_for_bone_depth(
                                        int(self.node_depths[int(index)]),
                                        proximal_min_depth=int(
                                            self.config.ik_proximal_min_depth
                                        ),
                                        limb_step_deg=float(self.config.ik_max_step_deg),
                                        proximal_step_deg=float(
                                            self.config.ik_proximal_max_step_deg
                                        ),
                                    )
                                    scaled_deg = scale_step_deg(
                                        float(base_deg),
                                        mode=str(self.config.ik_step_scale_mode),
                                        displacement_px=float(_job.tip_displacement_px),
                                        frame_deficit=float(frame_deficit),
                                        ref_px=float(self.config.ik_step_displacement_ref_px),
                                        min_scale=float(self.config.ik_step_scale_min),
                                        max_scale=float(self.config.ik_step_scale_max),
                                    )
                                    step_rad_by_index[int(index)] = math.radians(scaled_deg)
                                chain_names = "+".join(
                                    str(self.node_names[int(index)]) for index in prefix
                                )

                                def on_improvement(trial_pose, trial_score, *, _prefix=prefix):
                                    _preview_ik_pose(
                                        trial_pose[0],
                                        _frame_index=int(frame_index),
                                        _frame_position=int(frame_position),
                                        _label=(
                                            f"ik f{int(frame_index):02d} {_job.bone_name} "
                                            f"chain={chain_names} {score_label}="
                                            f"{float(trial_score):.3f}"
                                        ),
                                    )

                                trial, trial_score, _round_scores = search_chain_local_axes(
                                    pose_frame.unsqueeze(0),
                                    prefix,
                                    directions=directions,
                                    step_rad_by_index=step_rad_by_index,
                                    joint_limit_rad=joint_limit_rad,
                                    bone_limit_scales=self.bone_limit_scales,
                                    offset_fn=offset_raw_bone_direction,
                                    score_batch_fn=score_batch,
                                    rounds=int(self.config.ik_blob_search_rounds),
                                    stop_score=job_target_score,
                                    on_improvement=on_improvement,
                                )
                                return trial[0], float(trial_score)

                            def on_chain_step(step, trial_pose, *, _job=job):
                                if int(step.chain_length) <= 0:
                                    return
                                chain_names = "+".join(
                                    str(self.node_names[int(index)])
                                    for index in step.chain_indices
                                )
                                _preview_ik_pose(
                                    trial_pose,
                                    _frame_index=int(frame_index),
                                    _frame_position=int(frame_position),
                                    _label=(
                                        f"ik f{int(frame_index):02d} {_job.bone_name} "
                                        f"kept chain={chain_names} {score_label}="
                                        f"{float(step.score):.3f}"
                                    ),
                                )

                            solved = grow_chain_keep_best(
                                current,
                                opening_score,
                                prefixes,
                                search_prefix=search_prefix,
                                target_score=job_target_score,
                                on_step=on_chain_step,
                            )
                            current = solved.pose
                            _preview_ik_pose(
                                current,
                                _frame_index=int(frame_index),
                                _frame_position=int(frame_position),
                                _label=(
                                    f"ik f{int(frame_index):02d} {job.bone_name} "
                                    f"blob done {score_label}={float(solved.score):.3f}"
                                ),
                            )
                            kept_step = next(
                                step
                                for step in solved.steps
                                if int(step.chain_length) == int(solved.kept_chain_length)
                            )
                            blob_reports.append(
                                {
                                    "passIndex": int(pass_index),
                                    "scoreMode": score_mode,
                                    "tipDisplacementPx": float(job.tip_displacement_px),
                                    "priorityScore": float(job.priority_score),
                                    "jobTargetScore": float(job_target_score),
                                    "frameDeficit": float(frame_deficit),
                                    "frameIndex": int(frame_index),
                                    "bone": str(job.bone_name),
                                    "excessArea": int(job.excess_area),
                                    "missingArea": int(job.missing_area),
                                    "openingScore": float(opening_score),
                                    "keptScore": float(solved.score),
                                    "keptChainLength": int(solved.kept_chain_length),
                                    "chain": [
                                        str(self.node_names[int(index)])
                                        for index in kept_step.chain_indices
                                    ],
                                    "steps": [
                                        {
                                            "chainLength": int(step.chain_length),
                                            "bones": [
                                                str(self.node_names[int(index)])
                                                for index in step.chain_indices
                                            ],
                                            "score": float(step.score),
                                            "stoppedAtTarget": bool(step.stopped_at_target),
                                        }
                                        for step in solved.steps
                                    ],
                                }
                            )
                            if progress:
                                print(
                                    f"gpu ik blob: pass={int(pass_index) + 1} "
                                    f"frame={int(frame_index)} bone={job.bone_name} "
                                    f"keptLen={solved.kept_chain_length} "
                                    f"{score_label}={solved.score:.3f} from={opening_score:.3f}",
                                    flush=True,
                                )
                        ik_pose[frame_position] = current
                        _preview_ik_pose(
                            current,
                            _frame_index=int(frame_index),
                            _frame_position=int(frame_position),
                            _label=f"ik f{int(frame_index):02d} pass={int(pass_index) + 1} done",
                        )
                    if cheap_frame_positions is not None and bool(
                        self.config.seed_previous_frame
                    ):
                        prefix = int(idle_prefix_count)
                        for fp in range(max(1, prefix), len(self.frame_indices)):
                            if int(fp) in cheap_frame_positions:
                                continue
                            self._seed_transit_pose_from_previous_(
                                ik_pose,
                                root_translation,
                                root_rotation,
                                frame_position=int(fp),
                                only_if_bind=True,
                            )
            elif keypoints_source == "authored":
                if not bone_roles_path:
                    raise ValueError("authored IK requires ik_bone_roles_path")
                bone_roles = load_ik_bone_roles(bone_roles_path)
                keypoints = load_ik_keypoints(keypoints_path)
                matched_frames = [index for index in self.frame_indices if int(index) in keypoints]
                if not matched_frames:
                    available = sorted(keypoints)
                    raise RuntimeError(
                        "IK keypoints (authored) have no frames in common with the clip "
                        f"(clip={list(self.frame_indices)}, keypoints={available})"
                    )
                chains = ik_chains_from_bone_roles(bone_roles, self.node_index, self.parents)
                if progress:
                    print(
                        f"gpu ik: source=authored keypoints={keypoints_path} "
                        f"roles={bone_roles_path} "
                        f"frames={len(matched_frames)}/{len(self.frame_indices)} "
                        f"chains={len(chains)}",
                        flush=True,
                    )
                bind_bone_vectors = torch.zeros_like(bone_vectors)
                bind_world = self._forward_kinematics(bind_bone_vectors)
                bind_positions = bind_world[0, :, :3, 3]
                reference_depths: dict[int, float] = {}
                for _label, bone_name in (
                    (joint_name, mapped)
                    for joint_name, mapped in bone_roles.items()
                    if mapped in self.node_index
                ):
                    bone_index = int(self.node_index[bone_name])
                    pos_3d = bind_positions[bone_index]
                    sx, sy = _project_world_positions_xy(
                        pos_3d,
                        self.camera_right,
                        self.camera_down,
                        self.camera_offset,
                        self.px_per_world,
                    )
                    if self.target_depth is not None and len(self.target_depth) > 0:
                        depth_map = self.target_depth[0]
                        height, width = depth_map.shape
                        px = int(round(sx))
                        py = int(round(sy))
                        if 0 <= px < width and 0 <= py < height:
                            reference_depths[bone_index] = float(depth_map[py, px])
                        else:
                            reference_depths[bone_index] = 0.5
                    else:
                        reference_depths[bone_index] = 0.5
                scale_x, scale_y = self.camera["rasterScale"]

                def _fk_batch(raw_vectors):
                    bounded = self._bounded_bone_vectors(raw_vectors)
                    return self._forward_kinematics(bounded)

                for frame_position, frame_index in enumerate(self.frame_indices):
                    if int(frame_index) not in keypoints:
                        continue
                    joints_2d = keypoints[int(frame_index)]
                    depth_map = None
                    if self.target_depth is not None and frame_position < len(self.target_depth):
                        depth_map = self.target_depth[frame_position]
                    current = ik_pose[frame_position].clone()
                    joints_3d: dict[str, torch.Tensor] = {}
                    for joint_name, (x, y) in joints_2d.items():
                        if joint_name not in bone_roles:
                            continue
                        bone_name = bone_roles[joint_name]
                        if bone_name not in self.node_index:
                            continue
                        bone_index = self.node_index[bone_name]
                        raster_x = float(x) * float(scale_x)
                        raster_y = float(y) * float(scale_y)
                        depth = reference_depths.get(bone_index, 0.5)
                        if depth_map is not None:
                            height, width = depth_map.shape
                            px = int(round(raster_x))
                            py = int(round(raster_y))
                            if 0 <= px < width and 0 <= py < height:
                                depth = float(depth_map[py, px])
                        joints_3d[joint_name] = ik_unproject_2d_to_3d(
                            raster_x,
                            raster_y,
                            depth,
                            self.camera_right,
                            self.camera_down,
                            self.camera_forward,
                            self.camera_offset,
                            self.px_per_world,
                        )
                    for chain_indices, target_joint, end_effector_index in chains:
                        if target_joint not in joints_3d:
                            continue
                        current = ik_ccd_chain(
                            current,
                            chain_indices,
                            joints_3d[target_joint],
                            end_effector_index,
                            _fk_batch,
                            joint_limit_rad=joint_limit_rad,
                            bone_limit_scales=self.bone_limit_scales,
                            max_iterations=iterations,
                            max_step_rad=max_step_rad,
                        )
                    ik_pose[frame_position] = current
            else:
                raise ValueError(f"unsupported ik_keypoints_source: {keypoints_source!r}")

            commit_pose_parameter_(bone_vectors, ik_pose)

            post = self.evaluate(
                self._bounded_bone_vectors(bone_vectors),
                root_translation,
                root_rotation,
                bone_mask=self._stage_bone_mask("annealing"),
            )
            evaluation_count[0] += 1
            post_score = float(post["score"].mean().detach().item())
            post_temporal = float(
                self._temporal_penalty(
                    self._bounded_bone_vectors(bone_vectors),
                    root_translation,
                    root_rotation,
                ).detach().item()
            )
            post_loss = 1.0 - post_score + post_temporal
            accepted = True
            if bool(self.config.ik_require_improvement) and post_loss > pre_loss + 1e-9:
                commit_pose_parameter_(bone_vectors, pre_pose)
                post_score = pre_score
                post_temporal = pre_temporal
                post_loss = pre_loss
                accepted = False
            history.append(
                {
                    "stage": "ik",
                    "iteration": 1.0,
                    "loss": float(post_loss),
                    "score": float(post_score),
                    "temporal": float(post_temporal),
                    "accepted": bool(accepted),
                    "learningRate": 0.0,
                    "rejectStreak": 0.0,
                    "attemptedLoss": float(post_loss if accepted else pre_loss),
                    "preScore": float(pre_score),
                    "preLoss": float(pre_loss),
                    "blobReports": blob_reports,
                    "solver": (
                        "incremental_blob"
                        if keypoints_source == "silhouette_miss"
                        else "authored_ccd"
                    ),
                }
            )
            if progress:
                print(
                    f"gpu ik: score={post_score:.5f} loss={post_loss:.5f} "
                    f"accepted={accepted} preScore={pre_score:.5f} "
                    f"blobs={len(blob_reports)} "
                    f"evals={evaluation_count[0]} "
                    f"elapsed={time.perf_counter() - started:.1f}s",
                    flush=True,
                )
            self._preview_clip_pose(
                bone_vectors,
                root_translation,
                root_rotation,
                "ik done",
                force=True,
                commit=True,
            )

        def run_branch_rescue() -> None:
            nonlocal iteration_display
            block_size = int(self.config.branch_rescue_block_size)
            values_per = int(self.config.branch_rescue_values_per_bone)
            step_deg = float(self.config.joint_step_deg)
            joint_limit_rad = math.radians(float(self.config.joint_limit_deg))
            stage_mask = self._stage_bone_mask("rescue")
            abs_weight, unique_weight, _shared = _joint_keep_weights("articulated")
            min_improvement = float(self.config.joint_keep_min_improvement)
            search_set = set(int(index) for index in self.fine_node_indices)
            pairs: list[tuple[int, ...]] = []
            for child, parent in self._search_parents.items():
                if parent is None or int(child) not in search_set or int(parent) not in search_set:
                    continue
                if block_size == 2:
                    pairs.append((int(parent), int(child)))
                else:
                    grand = self._search_parents.get(int(parent))
                    if grand is None or int(grand) not in search_set:
                        pairs.append((int(parent), int(child)))
                    else:
                        pairs.append((int(grand), int(parent), int(child)))
            # Keep unique chains in proximal-to-distal order.
            unique_pairs: list[tuple[int, ...]] = []
            seen: set[tuple[int, ...]] = set()
            for chain in sorted(pairs, key=lambda chain: (self.node_depths[chain[0]], chain)):
                if chain in seen:
                    continue
                seen.add(chain)
                unique_pairs.append(chain)
            branch_groups.extend(
                {
                    "bones": [self.node_names[index] for index in chain],
                    "kind": "rescue_pair" if len(chain) == 2 else "rescue_beam",
                }
                for chain in unique_pairs
            )
            if not unique_pairs:
                if progress:
                    print("gpu rescue skipped: no parent-child search chains", flush=True)
                return

            def bone_values(bone_index: int) -> tuple[tuple[float, float, float], tuple[float, ...]]:
                recorded = joint_last_move.get(int(bone_index))
                if recorded is not None:
                    direction, delta = recorded
                    magnitudes = [0.0, float(delta), -float(delta)]
                else:
                    direction = (1.0, 0.0, 0.0)
                    magnitudes = [0.0, step_deg, -step_deg]
                unique_mag: list[float] = []
                for value in magnitudes:
                    if all(abs(value - existing) > 1e-9 for existing in unique_mag):
                        unique_mag.append(float(value))
                unique_mag = unique_mag[:values_per]
                if 0.0 not in unique_mag:
                    unique_mag.insert(0, 0.0)
                return direction, tuple(unique_mag)

            with torch.no_grad():
                opening = self.evaluate(
                    self._bounded_bone_vectors(bone_vectors),
                    root_translation,
                    root_rotation,
                    bone_mask=stage_mask,
                )
                baseline_abs = opening["geometryScore"].detach().clone()
                baseline_unique = opening["uniqueGeometryQuality"].detach().clone()
                current_collision = opening["collisionError"].detach().clone()
                zeros_keep = torch.zeros_like(baseline_abs)
                frame_count = int(bone_vectors.shape[0])
                from cascade_bone_order import is_dynamic_bone_order_mode

                if is_dynamic_bone_order_mode(str(self.config.bone_order_mode)):
                    ranked = self._rank_joint_bones(
                        [int(index) for index in self.search_node_indices],
                        bone_vectors,
                        root_translation,
                        root_rotation,
                        original_order=self.search_node_indices,
                        stage_mask=stage_mask,
                        evaluation_count=evaluation_count,
                        abs_weight=abs_weight,
                        unique_weight=unique_weight,
                        current_abs=baseline_abs,
                        current_unique=baseline_unique,
                        current_col=current_collision,
                    )
                    rank_pos = {int(index): position for position, index in enumerate(ranked)}
                    for index in self.search_node_indices:
                        if int(index) not in rank_pos:
                            rank_pos[int(index)] = len(rank_pos)
                    for chain in unique_pairs:
                        for index in chain:
                            if int(index) not in rank_pos:
                                rank_pos[int(index)] = len(rank_pos)
                    unique_pairs.sort(
                        key=lambda chain: (
                            min(rank_pos[int(index)] for index in chain),
                            chain,
                        )
                    )
                    if progress:
                        names = [str(self.node_names[int(index)]) for index in ranked]
                        print(
                            f"gpu rescue boneOrder={self.config.bone_order_mode} "
                            f"first={','.join(names[:4])} last={','.join(names[-4:])}",
                            flush=True,
                        )
                hyps_per = joint_score_hyps_per_launch(
            pose_budget=int(self.config.joint_score_raster_batch),
            frame_count=int(frame_count),
        )
                total_visits = len(unique_pairs)
                for visit, chain in enumerate(unique_pairs, start=1):
                    iteration_display = str(visit)
                    specs = [bone_values(index) for index in chain]
                    grids = [spec[1] for spec in specs]
                    combos = [
                        combo
                        for combo in itertools.product(*grids)
                        if any(abs(float(value)) > 1e-12 for value in combo)
                    ]
                    if not combos:
                        continue
                    raw_choices = [bone_vectors.detach().clone()]
                    keep_choices = [zeros_keep]
                    current_raw = bone_vectors.detach().clone()
                    for start in range(0, len(combos), hyps_per):
                        chunk = combos[start : start + hyps_per]
                        stacked_parts = []
                        for combo in chunk:
                            posed = current_raw
                            for bone_index, spec, delta_deg in zip(chain, specs, combo):
                                if abs(float(delta_deg)) <= 1e-12:
                                    continue
                                posed = offset_raw_bone_direction(
                                    posed,
                                    bone_index=int(bone_index),
                                    direction=spec[0],
                                    delta_rad=math.radians(float(delta_deg)),
                                    joint_limit_rad=joint_limit_rad,
                                    bone_limit_scales=self.bone_limit_scales,
                                )
                            stacked_parts.append(posed)
                        stacked_raw = torch.cat(stacked_parts, dim=0)
                        evaluation_count[0] += 1
                        if progress:
                            print(
                                f"gpu rescue {visit}/{total_visits} probe "
                                f"eval={evaluation_count[0]} elapsed={time.perf_counter() - started:.1f}s ...",
                                end="\r",
                                flush=True,
                            )
                        components = self.evaluate(
                            self._bounded_bone_vectors(stacked_raw),
                            root_translation.detach().repeat(len(chunk), 1),
                            root_rotation.detach().repeat(len(chunk), 1),
                            bone_mask=stage_mask,
                        )
                        packed_abs = components["geometryScore"]
                        packed_unique = components["uniqueGeometryQuality"]
                        packed_col = components["collisionError"]
                        for hyp_index in range(len(chunk)):
                            start_row = hyp_index * frame_count
                            abs_s = packed_abs[start_row : start_row + frame_count]
                            unique_s = packed_unique[start_row : start_row + frame_count]
                            col_s = packed_col[start_row : start_row + frame_count]
                            keep_choices.append(
                                _keep_score(
                                    abs_s,
                                    unique_s,
                                    col_s,
                                    abs_weight=abs_weight,
                                    unique_weight=unique_weight,
                                    current_abs=baseline_abs,
                                    current_unique=baseline_unique,
                                    current_col=current_collision,
                                    collision_enabled=bool(self.config.collision_enabled),
                                )
                            )
                            raw_choices.append(
                                stacked_raw[start_row : start_row + frame_count].detach().clone()
                            )
                    blended, winner, _chosen = gather_per_frame_winners(
                        raw_choices,
                        keep_choices,
                        min_improvement=min_improvement,
                    )
                    winner = self._lock_still_sprite_winner(winner)
                    winner = self._lock_idle_bookend_winner(winner, idle_prefix_count)
                    self._copy_still_leading_(blended)
                    blended, consensus_moved = apply_temporal_consensus(
                        blended,
                        [int(index) for index in chain],
                        stage_mask,
                    )
                    bone_vectors.copy_(blended)
                    self._commit_live_pose_(bone_vectors, root_translation, root_rotation)
                    post = self.evaluate(
                        self._bounded_bone_vectors(bone_vectors),
                        root_translation,
                        root_rotation,
                        bone_mask=stage_mask,
                    )
                    evaluation_count[0] += 1
                    baseline_abs = post["geometryScore"].detach().clone()
                    baseline_unique = post["uniqueGeometryQuality"].detach().clone()
                    current_collision = post["collisionError"].detach().clone()
                    zeros_keep = torch.zeros_like(baseline_abs)
                    moved = sum(int(choice) != 0 for choice in winner.detach().cpu().tolist())
                    names = ",".join(self.node_names[index] for index in chain)
                    if progress:
                        extra = f" nConsensus={consensus_moved}" if consensus_moved else ""
                        if (
                            consensus_hops["fwd"]
                            or consensus_hops["rev"]
                            or consensus_hops["idle"]
                            or consensus_hops["rev_pick"]
                        ):
                            extra += (
                                f" nFwd={consensus_hops['fwd']}"
                                f" nRev={consensus_hops['rev']}"
                                f" nIdle={consensus_hops['idle']}"
                                f" nRevPick={consensus_hops['rev_pick']}"
                            )
                        print(
                            f"gpu rescue {visit}/{total_visits}: "
                            f"score={float(post['score'].mean().item()):.5f} "
                            f"bones={names} nMoved={moved} "
                            f"evals={evaluation_count[0]} "
                            f"elapsed={time.perf_counter() - started:.1f}s{extra}",
                            flush=True,
                        )
                    self._preview_clip_pose(
                        bone_vectors,
                        root_translation,
                        root_rotation,
                        f"rescue {names}",
                        force=False,
                    )
            self._preview_clip_pose(
                bone_vectors,
                root_translation,
                root_rotation,
                "rescue done",
                force=True,
                commit=True,
            )

        def run_stage(label: str, iterations: int, learning_rate: float, parameters: list[Any]) -> None:
            nonlocal iteration_display
            if int(iterations) <= 0 or not parameters:
                return
            uses_bones = any(parameter is bone_vectors for parameter in parameters)
            if uses_bones:
                run_simultaneous_joint_stage(label, iterations, parameters)
                return
            base_learning_rate = float(learning_rate)
            active_learning_rate = base_learning_rate
            reject_streak = 0
            optimizer = torch.optim.Adam(parameters, lr=base_learning_rate)

            def set_learning_rate(value: float) -> None:
                nonlocal active_learning_rate
                active_learning_rate = float(value)
                for parameter_group in optimizer.param_groups:
                    parameter_group["lr"] = active_learning_rate

            def root_measure(phase: str):
                return measure(phase, label, iterations)

            best_loss = float("inf")
            best_parameters: list[Any] | None = None

            def remember_best(loss_value: Any) -> bool:
                nonlocal best_loss, best_parameters
                value = float(loss_value.detach().item())
                if not math.isfinite(value) or value >= best_loss:
                    return False
                best_loss = value
                best_parameters = [parameter.detach().clone() for parameter in parameters]
                return True

            with torch.no_grad():
                iteration_display = "init"
                initial_loss, _, _, _, _, _, _ = root_measure("forward")
                remember_best(initial_loss)

            for iteration in range(int(iterations)):
                iteration_display = str(iteration + 1)
                optimizer.zero_grad(set_to_none=True)
                loss, image_score, temporal, _, _, _, _ = root_measure("forward")
                if progress:
                    print(
                        f"gpu {label} {iteration + 1}/{iterations} backward "
                        f"eval={evaluation_count[0]} elapsed={time.perf_counter() - started:.1f}s ...",
                        end="\r",
                        flush=True,
                    )
                loss.backward()
                for parameter in parameters:
                    if parameter.grad is None:
                        continue
                    if not bool(torch.isfinite(parameter.grad).all()):
                        raise RuntimeError(
                            f"gpu {label} parameter gradients are not finite; "
                            "Lab a,b or a zero-length rotation produced NaN and "
                            "every later step would write NaN into the pose"
                        )
                optimizer_state_before_step = copy.deepcopy(optimizer.state_dict())
                optimizer.step()
                with torch.no_grad():
                    post_loss, post_score, post_temporal, _, _, _, _ = root_measure("post-step")
                    attempted = float(post_loss.detach().item())
                    if not math.isfinite(attempted):
                        accepted = False
                    elif attempted < best_loss:
                        accepted = remember_best(post_loss)
                    elif attempted <= best_loss + 1e-8:
                        accepted = True
                    else:
                        accepted = False
                    if not accepted:
                        for parameter, best in zip(parameters, best_parameters or ()):
                            parameter.copy_(best)
                        optimizer.load_state_dict(optimizer_state_before_step)
                        post_loss, post_score, post_temporal, _, _, _, _ = root_measure("restore")
                        reject_streak += 1
                        if self.config.adaptive_learning_rate_enabled:
                            set_learning_rate(
                                backtracked_learning_rate(
                                    current=active_learning_rate,
                                    base=base_learning_rate,
                                    reject_streak=reject_streak,
                                    patience=int(self.config.adaptive_learning_rate_reject_patience),
                                    divisor=float(self.config.adaptive_learning_rate_multiplier),
                                    max_divisor=float(self.config.adaptive_learning_rate_max_multiplier),
                                )
                            )
                    else:
                        reject_streak = 0
                row = {
                    "stage": label,
                    "iteration": float(iteration + 1),
                    "loss": float(post_loss.detach().item()),
                    "score": float(post_score.detach().item()),
                    "temporal": float(post_temporal.detach().item()),
                    "accepted": bool(accepted),
                    "learningRate": float(active_learning_rate),
                    "rejectStreak": float(reject_streak),
                    "attemptedLoss": attempted,
                }
                history.append(row)
                if progress and (iteration == 0 or (iteration + 1) % max(1, int(self.config.progress_every)) == 0 or iteration + 1 == int(iterations)):
                    print(
                        f"gpu {label} {iteration + 1}/{iterations}: "
                        f"score={row['score']:.5f} loss={row['loss']:.5f} "
                        f"attempted={attempted:.5f} "
                        f"temporal={row['temporal']:.5f} accepted={row['accepted']} "
                        f"lr={row['learningRate']:.6g} rejects={int(row['rejectStreak'])} "
                        f"evals={evaluation_count[0]} elapsed={time.perf_counter() - started:.1f}s",
                        flush=True,
                    )
                if adam_stage_stalled(reject_streak, int(self.config.adam_stall_reject_streak)):
                    if progress:
                        print(
                            f"gpu {label} stalled after {reject_streak} rejected steps; "
                            f"later Adam steps would restore the same best",
                            flush=True,
                        )
                    break

            with torch.no_grad():
                iteration_display = "final"
                final_loss, _, _, _, _, _, _ = root_measure("final")
                remember_best(final_loss)
                if best_parameters is not None:
                    for parameter, best in zip(parameters, best_parameters):
                        parameter.copy_(best)
            self._preview_clip_pose(
                bone_vectors,
                root_translation,
                root_rotation,
                f"{label} done",
                force=True,
                commit=True,
            )

        root_parameters = []
        if self.config.optimize_root_translation:
            root_parameters.append(root_translation)
        # Discrete hypothesis already placed heading. Adam on rotation with
        # chroma_weight >> silhouette walks off a silhouette-correct idle.
        run_stage("root", root_iteration_count, self.config.learning_rate, root_parameters)
        if seeded_pose_skip and bool(self.config.root_skip_when_seeded) and progress:
            print("gpu root skipped (seeded poses preserved)", flush=True)
        if progress:
            print(
                f"gpu ik: enabled={bool(self.config.ik_enabled)} "
                f"optimizeBones={bool(self.config.optimize_bones)} "
                f"keypoints={self.config.ik_keypoints_path!r}",
                flush=True,
            )
        if self.config.optimize_bones and bool(self.config.ik_enabled):
            run_ik_initialization()
        elif progress:
            print("gpu ik: skipped", flush=True)
        if self.config.optimize_bones and bool(self.config.sa_enabled):
            run_simulated_annealing()
        if self.config.optimize_bones and bool(self.config.base_pose_enabled) and int(self.config.base_pose_iterations) > 0:
            if bool(self.config.joint_adaptive_step_enabled):
                if progress:
                    print(
                        "gpu base skipped: joint_adaptive_step uses one articulated walk",
                        flush=True,
                    )
            else:
                run_simultaneous_joint_stage("base", self.config.base_pose_iterations, [bone_vectors])
                self._seed_still_frames_from_previous_(
                    bone_vectors,
                    root_translation,
                    root_rotation,
                )
        if bool(self.config.root_refit_after_base_enabled):
            from gpu_depth_silhouette_solver import root_rotation_axes_for_phase

            after_base_axes = root_rotation_axes_for_phase(
                self.config.root_rotation_axes,
                defer_camera_up=bool(self.config.root_rotation_defer_camera_up),
                phase="initial",
            )
            run_root_refit(
                label="root_refit",
                include_translation=True,
                rotation_axes=after_base_axes,
            )
        if self.config.optimize_bones and bool(self.config.gradient_ladder_enabled):
            run_gradient_ladder()
        if self.config.optimize_bones and bool(self.config.chain_space_enabled):
            run_chain_space()
        def run_shared_transit_yaw(stage_label: str) -> None:
            if not (
                bool(self.config.idle_fused_macro_enabled)
                and bool(self.config.idle_fused_shared_transit_yaw_enabled)
            ):
                return
            if stage_label == "preArticulated" and not bool(
                self.config.idle_fused_shared_transit_yaw_pre_articulated
            ):
                return
            if stage_label == "postArticulated" and not bool(
                self.config.idle_fused_shared_transit_yaw_post_articulated
            ):
                return
            prefix_count = int(getattr(self.config, "idle_prefix_frames", 0) or 0)
            self._search_shared_transit_camera_up(
                bone_vectors,
                root_translation,
                root_rotation,
                prefix_count=prefix_count,
                window_deg=float(self.config.idle_fused_shared_transit_yaw_window_deg),
                step_deg=float(self.config.idle_fused_shared_transit_yaw_step_deg),
                progress=progress,
                started=started,
                evaluation_count=evaluation_count,
                stage_label=stage_label,
            )
            if progress and stage_label == "postArticulated":
                post_artic = self.evaluate(
                    self._bounded_bone_vectors(bone_vectors),
                    root_translation,
                    root_rotation,
                    bone_mask=self.active_node_mask,
                )
                evaluation_count[0] += 1
                print(
                    "gpu idle_fused: sharedTransitYaw postArticulated mean="
                    f"{float(post_artic['score'].mean().item()):.4f}",
                    flush=True,
                )

        run_shared_transit_yaw("preArticulated")
        articulated_parameters = [] if self.config.freeze_root_after_root_stage else list(root_parameters)
        if self.config.optimize_bones:
            articulated_parameters.insert(0, bone_vectors)
        if articulated_skip:
            if progress:
                print("gpu articulated skipped (seeded poses preserved)", flush=True)
        elif bool(self.config.articulated_funnel_enabled):
            broad_rounds = int(self.config.articulated_funnel_broad_rounds)
            refine_rounds = max(1, int(self.config.articulated_iterations))
            if progress and broad_rounds > 0:
                print(
                    "gpu articulated funnel: broad "
                    f"step={float(self.config.articulated_funnel_broad_step_deg):.1f}° "
                    f"rungs={int(self.config.articulated_funnel_broad_probe_rungs)} "
                    f"rounds={broad_rounds} "
                    f"then refine rounds={refine_rounds}",
                    flush=True,
                )
            run_stage(
                "articulated_broad",
                broad_rounds,
                self.config.learning_rate,
                [bone_vectors],
            )
            run_stage(
                "articulated",
                refine_rounds,
                self.config.learning_rate,
                articulated_parameters,
            )
        else:
            run_stage(
                "articulated",
                self.config.articulated_iterations,
                self.config.learning_rate,
                articulated_parameters,
            )
        self._seed_still_frames_from_previous_(
            bone_vectors,
            root_translation,
            root_rotation,
        )
        if idle_snap_bones_global is not None and idle_prefix_count > 0:
            bone_vectors.data[:idle_prefix_count] = idle_snap_bones_global
        run_shared_transit_yaw("postArticulated")
        post_iters = int(self.config.idle_fused_shared_transit_yaw_post_articulated_iterations)
        if post_iters > 0:
            run_stage(
                "shared_yaw_adapt",
                post_iters,
                self.config.learning_rate,
                [bone_vectors],
            )
        if (
            bool(self.config.idle_fused_macro_enabled)
            and bool(self.config.idle_fused_reroot_transit_after_articulated)
            and not (
                seeded_pose_skip and bool(self.config.idle_fused_skip_reroot_when_seeded)
            )
        ):
            prefix_count = int(getattr(self.config, "idle_prefix_frames", 0) or 0)
            frame_count = int(bone_vectors.shape[0])
            with torch.no_grad():
                frame_scores = self.evaluate(
                    self._bounded_bone_vectors(bone_vectors),
                    root_translation,
                    root_rotation,
                    bone_mask=self.active_node_mask,
                )["score"].detach()
            if bool(self.config.idle_fused_reroot_all_transit):
                positions = list(range(prefix_count, frame_count))
            else:
                from cascade_idle_fused_stack import transit_worst_frame_positions

                positions = [
                    int(position)
                    for position in transit_worst_frame_positions(
                        frame_scores,
                        prefix_count=prefix_count,
                        keep_count=int(self.config.idle_fused_per_frame_root_count),
                    )
                    .detach()
                    .cpu()
                    .tolist()
                ]
            if progress:
                print(
                    "gpu idle_fused: rerootTransit "
                    f"n={len(positions)} "
                    f"frames={[int(self.frame_indices[p]) for p in positions]}",
                    flush=True,
                )
            for position in positions:
                self._root_hypothesis_start(
                    bone_vectors,
                    root_translation,
                    root_rotation,
                    int(position),
                    progress=progress,
                    started=started,
                    score_escape=True,
                    use_current_bones=True,
                )
            post_reroot = self.evaluate(
                self._bounded_bone_vectors(bone_vectors),
                root_translation,
                root_rotation,
                bone_mask=self.active_node_mask,
            )
            evaluation_count[0] += 1
            if progress:
                print(
                    "gpu idle_fused: rerootTransit mean="
                    f"{float(post_reroot['score'].mean().item()):.4f}",
                    flush=True,
                )
        anatomy_pin_out = None
        if str(self.config.live_status_path or "").strip():
            anatomy_pin_out = Path(str(self.config.live_status_path)).parent
        anatomy_head_pin_report = self._run_anatomy_head_pin(
            bone_vectors,
            root_translation,
            root_rotation,
            evaluation_count=evaluation_count,
            progress=progress,
            output_dir=anatomy_pin_out,
        )
        if bool(anatomy_head_pin_report.get("enabled")) and progress:
            self._preview_clip_pose(
                bone_vectors,
                root_translation,
                root_rotation,
                "anatomy_head_pin",
                force=True,
                commit=True,
            )
        if self.config.optimize_bones and bool(self.config.branch_rescue_enabled):
            if bool(self.config.joint_adaptive_step_enabled):
                if progress:
                    print(
                        "gpu rescue skipped: joint_adaptive_step uses one articulated walk",
                        flush=True,
                    )
            else:
                run_branch_rescue()
        if (
            self.config.optimize_bones
            and bool(self.config.mid_pose_enabled)
            and int(self.config.mid_pose_iterations) > 0
        ):
            if bool(self.config.joint_adaptive_step_enabled):
                if progress:
                    print(
                        "gpu mid skipped: joint_adaptive_step uses one articulated walk",
                        flush=True,
                    )
            else:
                run_simultaneous_joint_stage("mid", self.config.mid_pose_iterations, [bone_vectors])
        fine_parameters = [bone_vectors] if self.config.optimize_bones else []
        if self.config.fine_root_enabled:
            fine_parameters = list(root_parameters) + fine_parameters
        if bool(self.config.joint_adaptive_step_enabled) and int(self.config.fine_iterations) > 0:
            if progress:
                print(
                    "gpu fine skipped: joint_adaptive_step uses one articulated walk",
                    flush=True,
                )
        else:
            run_stage("fine", self.config.fine_iterations, self.config.fine_learning_rate, fine_parameters)
        if bool(self.config.root_rotation_defer_camera_up):
            if bool(self.config.root_rotation_after_joints_yaw_enabled):
                from gpu_depth_silhouette_solver import root_rotation_axes_for_phase

                run_root_refit(
                    label="root_yaw",
                    include_translation=False,
                    rotation_axes=root_rotation_axes_for_phase(
                        self.config.root_rotation_axes,
                        defer_camera_up=True,
                        phase="after_joints",
                    ),
                    rotation_window_deg=self._deferred_camera_up_window_deg(),
                )

        def run_score_escape_passes() -> list[dict[str, Any]]:
            """Score-gated escape while keeping joint_adaptive_step enabled."""
            if not bool(self.config.score_escape_enabled):
                return []
            mode = str(self.config.score_escape_mode).strip()
            if not mode:
                return []
            threshold = float(self.config.score_escape_threshold)
            with torch.no_grad():
                opening = self.evaluate(
                    self._bounded_bone_vectors(bone_vectors),
                    root_translation,
                    root_rotation,
                    bone_mask=self.active_node_mask,
                )
            mean_before = float(opening["score"].mean().item())
            if (
                not bool(self.config.score_escape_threshold_uses_hybrid_mean)
                and self._velocity_acceleration_only_temporal()
            ):
                mean_before = self._clip_objective_mean(
                    self._bounded_bone_vectors(bone_vectors),
                    root_translation,
                    root_rotation,
                    opening,
                )
            if mean_before >= threshold:
                if progress:
                    print(
                        f"gpu score_escape skipped: mean={mean_before:.4f} "
                        f">= threshold={threshold:.4f}",
                        flush=True,
                    )
                return [
                    {
                        "enabled": True,
                        "skipped": True,
                        "mode": mode,
                        "threshold": threshold,
                        "meanBefore": mean_before,
                        "meanAfter": mean_before,
                    }
                ]
            self._escape_selection_uses_hybrid_mean = bool(
                self.config.score_escape_threshold_uses_hybrid_mean
            )
            try:
                return _run_score_escape_passes_body(
                    mode=mode,
                    threshold=threshold,
                    mean_before=mean_before,
                    progress=progress,
                    started=started,
                    seeded_pose_skip=seeded_pose_skip,
                )
            finally:
                self._escape_selection_uses_hybrid_mean = False

        def _run_score_escape_passes_body(
            *,
            mode: str,
            threshold: float,
            mean_before: float,
            progress: bool,
            started: float | None,
            seeded_pose_skip: bool,
        ) -> list[dict[str, Any]]:
            if progress:
                print(
                    f"gpu score_escape: mean={mean_before:.4f} < {threshold:.4f} "
                    f"mode={mode}",
                    flush=True,
                )
            reports: list[dict[str, Any]] = [
                {
                    "enabled": True,
                    "skipped": False,
                    "mode": mode,
                    "threshold": threshold,
                    "meanBefore": mean_before,
                }
            ]
            keep_best = bool(self.config.score_escape_keep_best)
            best_score = mean_before
            best_bone = bone_vectors.detach().clone()
            best_translation = root_translation.detach().clone()
            best_rotation = root_rotation.detach().clone()

            def snapshot_best() -> None:
                nonlocal best_score, best_bone, best_translation, best_rotation
                current = mean_score()
                if current > best_score:
                    best_score = current
                    best_bone = bone_vectors.detach().clone()
                    best_translation = root_translation.detach().clone()
                    best_rotation = root_rotation.detach().clone()

            def restore_best_if_needed() -> float:
                current = mean_score()
                if keep_best and current < best_score:
                    bone_vectors.data.copy_(best_bone)
                    root_translation.data.copy_(best_translation)
                    root_rotation.data.copy_(best_rotation)
                    if progress:
                        print(
                            f"gpu score_escape keep_best restore "
                            f"{current:.4f}->{best_score:.4f}",
                            flush=True,
                        )
                    return best_score
                return current

            def finalize_pass(tag: str, after: float) -> float:
                snapshot_best()
                if keep_best and after < best_score:
                    restored = restore_best_if_needed()
                    reports.append(
                        {
                            "pass": f"{tag}_reverted",
                            "meanAfter": restored,
                            "revertedFrom": after,
                        }
                    )
                    if progress:
                        print(
                            f"gpu score_escape {tag} revert "
                            f"{after:.4f}->{restored:.4f}",
                            flush=True,
                        )
                    return restored
                return after

            def mean_score() -> float:
                with torch.no_grad():
                    packed = self.evaluate(
                        self._bounded_bone_vectors(bone_vectors),
                        root_translation,
                        root_rotation,
                        bone_mask=self.active_node_mask,
                    )
                if bool(self.config.score_escape_threshold_uses_hybrid_mean):
                    return float(packed["score"].mean().item())
                if self._velocity_acceleration_only_temporal():
                    return self._clip_objective_mean(
                        self._bounded_bone_vectors(bone_vectors),
                        root_translation,
                        root_rotation,
                        packed,
                    )
                return float(packed["score"].mean().item())

            def escape_articulated_iterations() -> int:
                esc = int(self.config.score_escape_articulated_iterations)
                if esc > 0:
                    return esc
                return int(self.config.articulated_iterations)

            escape_articulated_parameters = (
                [] if self.config.freeze_root_after_root_stage else list(root_parameters)
            )
            if self.config.optimize_bones:
                escape_articulated_parameters.insert(0, bone_vectors)

            def config_override(**kwargs: Any) -> dict[str, Any]:
                saved = {key: getattr(self.config, key) for key in kwargs}
                for key, value in kwargs.items():
                    object.__setattr__(self.config, key, value)
                return saved

            def restore_config(saved: Mapping[str, Any]) -> None:
                for key, value in saved.items():
                    object.__setattr__(self.config, key, value)

            def pass_articulated_retry(*, tag: str = "articulated_retry") -> float:
                run_stage(
                    "articulated",
                    escape_articulated_iterations(),
                    self.config.learning_rate,
                    escape_articulated_parameters,
                )
                self._seed_still_frames_from_previous_(
                    bone_vectors,
                    root_translation,
                    root_rotation,
                )
                after = mean_score()
                reports.append({"pass": tag, "meanAfter": after})
                if progress:
                    print(f"gpu score_escape {tag} mean={after:.4f}", flush=True)
                return finalize_pass(tag, after)

            def pass_branch_rescue(*, tag: str = "branch_rescue") -> float:
                run_branch_rescue()
                after = mean_score()
                reports.append({"pass": tag, "meanAfter": after})
                if progress:
                    print(f"gpu score_escape {tag} mean={after:.4f}", flush=True)
                return finalize_pass(tag, after)

            def pass_coarse_push(*, tag: str = "coarse_push") -> float:
                saved = config_override(
                    joint_step_score_coarse=float(
                        self.config.score_escape_coarse_push_coarse
                    ),
                    joint_step_score_fine=float(
                        self.config.score_escape_coarse_push_fine
                    ),
                )
                run_stage(
                    "articulated",
                    escape_articulated_iterations(),
                    self.config.learning_rate,
                    escape_articulated_parameters,
                )
                restore_config(saved)
                after = mean_score()
                reports.append(
                    {
                        "pass": tag,
                        "meanAfter": after,
                        "coarseThreshold": float(
                            self.config.score_escape_coarse_push_coarse
                        ),
                    }
                )
                if progress:
                    print(f"gpu score_escape {tag} mean={after:.4f}", flush=True)
                return finalize_pass(tag, after)

            def pass_no_consensus_retry(*, tag: str = "no_consensus_retry") -> float:
                saved = config_override(joint_temporal_consensus_enabled=False)
                run_stage(
                    "articulated",
                    escape_articulated_iterations(),
                    self.config.learning_rate,
                    escape_articulated_parameters,
                )
                restore_config(saved)
                after = mean_score()
                reports.append({"pass": tag, "meanAfter": after})
                if progress:
                    print(f"gpu score_escape {tag} mean={after:.4f}", flush=True)
                return finalize_pass(tag, after)

            def pass_root_burst(*, tag: str = "root_burst") -> float:
                run_root_refit(
                    label=f"score_escape_{tag}",
                    include_translation=True,
                    rotation_window_deg=float(self.config.score_escape_root_window_deg),
                    rotation_step_deg=float(self.config.score_escape_root_step_deg),
                )
                after = mean_score()
                reports.append({"pass": tag, "meanAfter": after})
                if progress:
                    print(f"gpu score_escape {tag} mean={after:.4f}", flush=True)
                return finalize_pass(tag, after)

            def pass_shared_transit_yaw_escape(*, tag: str = "shared_transit_yaw") -> float:
                if not bool(self.config.score_escape_shared_transit_yaw_enabled):
                    return mean_score()
                prefix_count = int(getattr(self.config, "idle_prefix_frames", 0) or 0)
                self._search_shared_transit_camera_up(
                    bone_vectors,
                    root_translation,
                    root_rotation,
                    prefix_count=prefix_count,
                    window_deg=float(self.config.score_escape_root_window_deg),
                    step_deg=float(self.config.idle_fused_shared_transit_yaw_step_deg),
                    progress=progress,
                    started=started,
                    evaluation_count=evaluation_count,
                    stage_label="score_escape_shared_transit_yaw",
                )
                after = mean_score()
                reports.append({"pass": tag, "meanAfter": after})
                if progress:
                    print(f"gpu score_escape {tag} mean={after:.4f}", flush=True)
                return finalize_pass(tag, after)

            def pass_worst_root_burst(*, tag: str = "worst_root_burst") -> float:
                with torch.no_grad():
                    packed = self.evaluate(
                        self._bounded_bone_vectors(bone_vectors),
                        root_translation,
                        root_rotation,
                        bone_mask=self.active_node_mask,
                    )
                worst = escape_worst_frame_indices(
                    packed["score"],
                    packed["collisionError"],
                    keep_count=int(self.config.score_escape_worst_frame_count),
                    collision_weight=float(
                        self.config.score_escape_worst_frame_collision_weight
                    ),
                )
                worst_positions = [int(item) for item in worst.detach().cpu().tolist()]
                held_abort = int(getattr(self.config, "score_escape_root_held_abort", 0) or 0)
                held_streak = 0
                searched_positions: list[int] = []
                skipped_positions: list[int] = []
                for position in worst_positions:
                    improved = bool(
                        self._root_hypothesis_start(
                            bone_vectors,
                            root_translation,
                            root_rotation,
                            position,
                            progress=progress,
                            started=started,
                            score_escape=True,
                            use_current_bones=True,
                        )
                    )
                    searched_positions.append(int(position))
                    if improved:
                        held_streak = 0
                    else:
                        held_streak += 1
                        if held_abort > 0 and held_streak >= held_abort:
                            remain = [
                                int(p)
                                for p in worst_positions
                                if int(p) not in searched_positions
                            ]
                            skipped_positions.extend(remain)
                            if progress:
                                print(
                                    f"gpu score_escape {tag} root-search abort "
                                    f"after {held_streak} held frames; "
                                    f"skipped={len(remain)}",
                                    flush=True,
                                )
                            break
                after = mean_score()
                reports.append(
                    {
                        "pass": tag,
                        "meanAfter": after,
                        "worstFrameIndices": [
                            int(self.frame_indices[position])
                            for position in searched_positions
                        ],
                        "skippedFrameIndices": [
                            int(self.frame_indices[position])
                            for position in skipped_positions
                        ],
                    }
                )
                if progress:
                    print(
                        f"gpu score_escape {tag} frames="
                        f"{reports[-1]['worstFrameIndices']} mean={after:.4f}",
                        flush=True,
                    )
                return finalize_pass(tag, after)

            def pass_translation_burst(*, tag: str = "translation_burst") -> float:
                if not bool(self.config.score_escape_translation_burst_enabled):
                    return mean_score()
                prefix_count = int(getattr(self.config, "idle_prefix_frames", 0) or 0)
                frame_count = int(bone_vectors.shape[0])
                burst_mode = str(self.config.score_escape_translation_burst_mode).strip()
                if burst_mode == "worst":
                    with torch.no_grad():
                        frame_scores = self.evaluate(
                            self._bounded_bone_vectors(bone_vectors),
                            root_translation,
                            root_rotation,
                            bone_mask=self.active_node_mask,
                        )["score"]
                    worst_positions = [
                        int(item)
                        for item in worst_frame_indices(
                            frame_scores,
                            keep_count=int(self.config.score_escape_worst_frame_count),
                        )
                        .detach()
                        .cpu()
                        .tolist()
                    ]
                else:
                    worst_positions = list(range(prefix_count, frame_count))
                if burst_mode in {
                    "transit_wave",
                    "transit_uniform",
                    "transit_sprite_centroid",
                }:
                    self._root_transit_correlated_translation_search(
                        bone_vectors,
                        root_translation,
                        root_rotation,
                        worst_positions,
                        mode=burst_mode,
                        progress=progress,
                        started=started,
                    )
                else:
                    for position in worst_positions:
                        self._root_translation_hypothesis_search(
                            bone_vectors,
                            root_translation,
                            root_rotation,
                            int(position),
                            progress=progress,
                            started=started,
                            score_escape=True,
                        )
                after = mean_score()
                reports.append(
                    {
                        "pass": tag,
                        "meanAfter": after,
                        "burstMode": burst_mode,
                        "frameIndices": [
                            int(self.frame_indices[position])
                            for position in worst_positions
                        ],
                    }
                )
                if progress:
                    print(
                        f"gpu score_escape {tag} mode={burst_mode} "
                        f"frames={reports[-1]['frameIndices']} mean={after:.4f}",
                        flush=True,
                    )
                return finalize_pass(tag, after)

            def pass_collision_root_burst(*, tag: str = "collision_root_burst") -> float:
                if not bool(self.config.score_escape_collision_burst_enabled):
                    return mean_score()
                burst_threshold = float(self.config.score_escape_collision_burst_threshold)
                with torch.no_grad():
                    packed = self.evaluate(
                        self._bounded_bone_vectors(bone_vectors),
                        root_translation,
                        root_rotation,
                        bone_mask=self.active_node_mask,
                    )
                collision = packed["collisionError"].detach().cpu().tolist()
                worst_positions = [
                    int(position)
                    for position, value in enumerate(collision)
                    if float(value) > burst_threshold
                ]
                if not worst_positions:
                    reports.append(
                        {
                            "pass": tag,
                            "skipped": True,
                            "reason": "no_collision_frames",
                            "threshold": burst_threshold,
                            "meanAfter": mean_score(),
                        }
                    )
                    return mean_score()
                for position in worst_positions:
                    self._root_hypothesis_start(
                        bone_vectors,
                        root_translation,
                        root_rotation,
                        int(position),
                        progress=progress,
                        started=started,
                        score_escape=True,
                        use_current_bones=True,
                    )
                after = mean_score()
                reports.append(
                    {
                        "pass": tag,
                        "meanAfter": after,
                        "collisionFrameIndices": [
                            int(self.frame_indices[position])
                            for position in worst_positions
                        ],
                        "threshold": burst_threshold,
                    }
                )
                if progress:
                    print(
                        f"gpu score_escape {tag} frames="
                        f"{reports[-1]['collisionFrameIndices']} mean={after:.4f}",
                        flush=True,
                    )
                return finalize_pass(tag, after)

            def pass_chain_space(*, tag: str = "chain_space") -> float:
                run_chain_space()
                after = mean_score()
                reports.append({"pass": tag, "meanAfter": after})
                if progress:
                    print(f"gpu score_escape {tag} mean={after:.4f}", flush=True)
                return finalize_pass(tag, after)

            def pass_sa_nudge(*, tag: str = "sa_nudge") -> float:
                saved = config_override(
                    sa_enabled=True,
                    sa_seed_from_current=True,
                    sa_restarts=int(self.config.score_escape_sa_restarts),
                    sa_iterations=int(self.config.score_escape_sa_iterations),
                    sa_perturbation_scale_deg=float(
                        self.config.score_escape_sa_perturbation_deg
                    ),
                    sa_bone_fraction=float(self.config.score_escape_sa_bone_fraction),
                )
                run_simulated_annealing()
                restore_config(saved)
                after = mean_score()
                reports.append({"pass": tag, "meanAfter": after})
                if progress:
                    print(f"gpu score_escape {tag} mean={after:.4f}", flush=True)
                return finalize_pass(tag, after)

            def pass_articulated_broad_escape(*, tag: str = "articulated_broad_escape") -> float:
                run_stage(
                    "articulated_broad",
                    1,
                    self.config.learning_rate,
                    [bone_vectors],
                )
                self._seed_still_frames_from_previous_(
                    bone_vectors,
                    root_translation,
                    root_rotation,
                )
                after = mean_score()
                reports.append({"pass": tag, "meanAfter": after})
                if progress:
                    print(f"gpu score_escape {tag} mean={after:.4f}", flush=True)
                return finalize_pass(tag, after)

            def still_underfit() -> bool:
                return mean_score() < threshold

            def run_root_escape_passes(*, prefix: str) -> None:
                if still_underfit():
                    pass_worst_root_burst(tag=f"{prefix}stack_worst_root")
                if bool(self.config.score_escape_collision_burst_enabled):
                    pass_collision_root_burst(tag=f"{prefix}stack_collision")

            def run_retry_coarse_stack(*, round_index: int | None = None) -> float:
                before = mean_score()
                prefix = f"r{round_index}_" if round_index is not None else ""
                if still_underfit():
                    pass_articulated_retry(tag=f"{prefix}rc_retry")
                if still_underfit():
                    pass_coarse_push(tag=f"{prefix}rc_coarse")
                run_root_escape_passes(prefix=prefix)
                return mean_score() - before

            def run_full_stack(*, round_index: int | None = None) -> float:
                before = mean_score()
                prefix = f"r{round_index}_" if round_index is not None else ""
                fail_fast = bool(getattr(self.config, "score_escape_fail_fast", True))
                min_gain = float(self.config.score_escape_min_improvement)
                prior_gain = False
                cursor = before
                if still_underfit():
                    after = pass_articulated_retry(tag=f"{prefix}stack_retry")
                    prior_gain = after > cursor + min_gain
                    cursor = after
                if still_underfit():
                    after = pass_coarse_push(tag=f"{prefix}stack_coarse")
                    prior_gain = prior_gain or after > cursor + min_gain
                    cursor = after
                if still_underfit() and (prior_gain or not fail_fast):
                    after = pass_branch_rescue(tag=f"{prefix}stack_rescue")
                    prior_gain = prior_gain or after > cursor + min_gain
                    cursor = after
                elif still_underfit() and fail_fast:
                    reports.append(
                        {
                            "pass": f"{prefix}stack_rescue_skipped_no_prior_gain",
                            "meanAfter": cursor,
                        }
                    )
                    if progress:
                        print(
                            "gpu score_escape skip rescue: prior passes did not improve",
                            flush=True,
                        )
                if still_underfit() and (prior_gain or not fail_fast):
                    run_root_escape_passes(prefix=prefix)
                elif still_underfit() and fail_fast:
                    reports.append(
                        {
                            "pass": f"{prefix}stack_root_skipped_no_prior_gain",
                            "meanAfter": mean_score(),
                        }
                    )
                    if progress:
                        print(
                            "gpu score_escape skip root bursts: prior passes did not improve",
                            flush=True,
                        )
                return mean_score() - before

            if mode == "articulated_retry":
                pass_articulated_retry()
            elif mode == "branch_rescue":
                pass_branch_rescue()
            elif mode == "combo":
                pass_articulated_retry()
                if still_underfit():
                    pass_branch_rescue()
            elif mode == "coarse_push":
                pass_coarse_push()
            elif mode == "no_consensus_retry":
                pass_no_consensus_retry()
            elif mode == "chain_space":
                pass_chain_space()
            elif mode == "root_burst":
                pass_root_burst()
            elif mode == "sa_nudge":
                pass_sa_nudge()
            elif mode == "full_stack":
                run_full_stack()
            elif mode == "retry_coarse":
                run_retry_coarse_stack()
            elif mode == "deep_retry":
                if still_underfit():
                    pass_articulated_retry(tag="deep_retry_1")
                if still_underfit():
                    pass_articulated_retry(tag="deep_retry_2")
            elif mode == "deep_retry_4":
                for pass_index in range(1, 5):
                    if still_underfit():
                        pass_articulated_retry(tag=f"deep_retry_{pass_index}")
            elif mode == "retry_then_plateau":
                pass_articulated_retry(tag="pre_plateau_retry")
                max_rounds = int(self.config.score_escape_max_rounds)
                min_improvement = float(self.config.score_escape_min_improvement)
                for round_index in range(max_rounds):
                    if not still_underfit():
                        reports.append(
                            {
                                "pass": "threshold_reached",
                                "round": round_index + 1,
                                "meanAfter": mean_score(),
                            }
                        )
                        break
                    before_round = mean_score()
                    delta = run_retry_coarse_stack(round_index=round_index + 1)
                    after_round = mean_score()
                    reports.append(
                        {
                            "pass": f"retry_coarse_round_{round_index + 1}",
                            "delta": float(delta),
                            "meanAfter": after_round,
                        }
                    )
                    if after_round - before_round < min_improvement:
                        reports.append(
                            {
                                "pass": "plateau_stop",
                                "round": round_index + 1,
                                "delta": float(after_round - before_round),
                                "minImprovement": min_improvement,
                                "meanAfter": after_round,
                            }
                        )
                        if progress:
                            print(
                                f"gpu score_escape plateau at round={round_index + 1} "
                                f"delta={after_round - before_round:.4f}",
                                flush=True,
                            )
                        break
            elif mode == "worst_stack":
                max_rounds = int(self.config.score_escape_max_rounds)
                min_improvement = float(self.config.score_escape_min_improvement)
                for round_index in range(max_rounds):
                    if not still_underfit():
                        reports.append(
                            {
                                "pass": "threshold_reached",
                                "round": round_index + 1,
                                "meanAfter": mean_score(),
                            }
                        )
                        break
                    before_round = mean_score()
                    prefix = f"r{round_index + 1}_"
                    hopeless_floor = float(
                        getattr(
                            self.config,
                            "score_escape_skip_coarse_broad_below_mean",
                            0.0,
                        )
                        or 0.0
                    )
                    hopeless_skip = bool(
                        math.isfinite(hopeless_floor)
                        and hopeless_floor > 0.0
                        and before_round < hopeless_floor
                    )
                    skip_coarse_broad = (
                        (
                            seeded_pose_skip
                            and bool(
                                self.config.score_escape_skip_coarse_broad_when_seeded
                            )
                        )
                        or hopeless_skip
                    )
                    if hopeless_skip and progress:
                        print(
                            f"gpu score_escape skip coarse/broad: mean={before_round:.4f} "
                            f"< hopeless_floor={hopeless_floor:.4f}",
                            flush=True,
                        )
                    if still_underfit() and not skip_coarse_broad:
                        pass_coarse_push(tag=f"{prefix}worst_stack_coarse")
                    if still_underfit() and not skip_coarse_broad:
                        pass_articulated_broad_escape(tag=f"{prefix}worst_stack_broad")
                    if still_underfit() and skip_coarse_broad:
                        skip_retry = bool(
                            (
                                seeded_pose_skip
                                and bool(
                                    self.config.score_escape_skip_articulated_retry_when_seeded
                                )
                            )
                            or hopeless_skip
                        )
                        if not skip_retry:
                            pass_articulated_retry(tag=f"{prefix}worst_stack_retry")
                        elif hopeless_skip:
                            reports.append(
                                {
                                    "pass": f"{prefix}worst_stack_retry_skipped_hopeless",
                                    "meanAfter": mean_score(),
                                    "hopelessFloor": hopeless_floor,
                                }
                            )
                    if still_underfit() and bool(
                        self.config.score_escape_shared_transit_yaw_enabled
                    ):
                        pass_shared_transit_yaw_escape(
                            tag=f"{prefix}worst_stack_shared_yaw"
                        )
                    if still_underfit():
                        pass_worst_root_burst(tag=f"{prefix}worst_stack_root")
                    if bool(self.config.score_escape_collision_burst_enabled):
                        pass_collision_root_burst(tag=f"{prefix}worst_stack_collision")
                    if bool(self.config.score_escape_translation_burst_enabled):
                        pass_translation_burst(tag=f"{prefix}worst_stack_translation")
                    round_gain = mean_score() > before_round + float(
                        self.config.score_escape_min_improvement
                    )
                    if still_underfit() and (
                        round_gain
                        or not bool(getattr(self.config, "score_escape_fail_fast", True))
                    ):
                        pass_branch_rescue(tag=f"{prefix}worst_stack_rescue")
                    elif still_underfit():
                        reports.append(
                            {
                                "pass": f"{prefix}worst_stack_rescue_skipped_no_prior_gain",
                                "meanAfter": mean_score(),
                            }
                        )
                        if progress:
                            print(
                                "gpu score_escape skip worst_stack rescue: "
                                "round had no prior gain",
                                flush=True,
                            )
                    after_round = mean_score()
                    reports.append(
                        {
                            "pass": f"worst_stack_round_{round_index + 1}",
                            "delta": float(after_round - before_round),
                            "meanAfter": after_round,
                        }
                    )
                    if after_round - before_round < min_improvement:
                        reports.append(
                            {
                                "pass": "plateau_stop",
                                "round": round_index + 1,
                                "delta": float(after_round - before_round),
                                "minImprovement": min_improvement,
                                "meanAfter": after_round,
                            }
                        )
                        if progress:
                            print(
                                f"gpu score_escape worst_stack plateau at round="
                                f"{round_index + 1} "
                                f"delta={after_round - before_round:.4f}",
                                flush=True,
                            )
                        break
            elif mode == "until_threshold":
                max_rounds = int(self.config.score_escape_max_rounds)
                for round_index in range(max_rounds):
                    if not still_underfit():
                        reports.append(
                            {
                                "pass": "threshold_reached",
                                "round": round_index + 1,
                                "meanAfter": mean_score(),
                            }
                        )
                        break
                    delta = run_full_stack(round_index=round_index + 1)
                    reports.append(
                        {
                            "pass": f"full_stack_round_{round_index + 1}",
                            "delta": float(delta),
                            "meanAfter": mean_score(),
                        }
                    )
            elif mode == "until_plateau":
                max_rounds = int(self.config.score_escape_max_rounds)
                min_improvement = float(self.config.score_escape_min_improvement)
                for round_index in range(max_rounds):
                    if not still_underfit():
                        reports.append(
                            {
                                "pass": "threshold_reached",
                                "round": round_index + 1,
                                "meanAfter": mean_score(),
                            }
                        )
                        break
                    before_round = mean_score()
                    delta = run_full_stack(round_index=round_index + 1)
                    after_round = mean_score()
                    reports.append(
                        {
                            "pass": f"full_stack_round_{round_index + 1}",
                            "delta": float(delta),
                            "meanAfter": after_round,
                        }
                    )
                    if after_round - before_round < min_improvement:
                        reports.append(
                            {
                                "pass": "plateau_stop",
                                "round": round_index + 1,
                                "delta": float(after_round - before_round),
                                "minImprovement": min_improvement,
                                "meanAfter": after_round,
                            }
                        )
                        if progress:
                            print(
                                f"gpu score_escape plateau at round={round_index + 1} "
                                f"delta={after_round - before_round:.4f}",
                                flush=True,
                            )
                        break
            elif mode == "until_plateau_retry_coarse":
                max_rounds = int(self.config.score_escape_max_rounds)
                min_improvement = float(self.config.score_escape_min_improvement)
                for round_index in range(max_rounds):
                    if not still_underfit():
                        reports.append(
                            {
                                "pass": "threshold_reached",
                                "round": round_index + 1,
                                "meanAfter": mean_score(),
                            }
                        )
                        break
                    before_round = mean_score()
                    delta = run_retry_coarse_stack(round_index=round_index + 1)
                    after_round = mean_score()
                    reports.append(
                        {
                            "pass": f"retry_coarse_round_{round_index + 1}",
                            "delta": float(delta),
                            "meanAfter": after_round,
                        }
                    )
                    if after_round - before_round < min_improvement:
                        reports.append(
                            {
                                "pass": "plateau_stop",
                                "round": round_index + 1,
                                "delta": float(after_round - before_round),
                                "minImprovement": min_improvement,
                                "meanAfter": after_round,
                            }
                        )
                        if progress:
                            print(
                                f"gpu score_escape plateau at round={round_index + 1} "
                                f"delta={after_round - before_round:.4f}",
                                flush=True,
                            )
                        break
            else:
                raise RuntimeError(f"unsupported score_escape_mode: {mode!r}")

            mean_after = restore_best_if_needed()
            reports[0]["meanAfter"] = mean_after
            reports[0]["keepBest"] = keep_best
            reports[0]["bestScore"] = float(best_score)
            if progress:
                print(
                    f"gpu score_escape done: mean={mean_before:.4f}->{mean_after:.4f} "
                    f"best={best_score:.4f}",
                    flush=True,
                )
                self._write_live_status(
                    "score_escape",
                    started=started,
                    hybrid_mean=mean_after,
                    note=f"best={best_score:.4f}",
                )
            self._preview_clip_pose(
                bone_vectors,
                root_translation,
                root_rotation,
                "score_escape",
                force=True,
                commit=True,
            )
            return reports

        score_escape_reports = run_score_escape_passes()
        if (
            bool(self.config.idle_fused_macro_enabled)
            and bool(self.config.idle_fused_reroot_transit_after_articulated)
            and not (
                seeded_pose_skip and bool(self.config.idle_fused_skip_reroot_when_seeded)
            )
        ):
            prefix_count = int(getattr(self.config, "idle_prefix_frames", 0) or 0)
            frame_count = int(bone_vectors.shape[0])
            with torch.no_grad():
                frame_scores = self.evaluate(
                    self._bounded_bone_vectors(bone_vectors),
                    root_translation,
                    root_rotation,
                    bone_mask=self.active_node_mask,
                )["score"].detach()
            if bool(self.config.idle_fused_reroot_all_transit):
                final_positions = list(range(prefix_count, frame_count))
            else:
                from cascade_idle_fused_stack import transit_worst_frame_positions

                final_positions = [
                    int(position)
                    for position in transit_worst_frame_positions(
                        frame_scores,
                        prefix_count=prefix_count,
                        keep_count=int(self.config.idle_fused_per_frame_root_count),
                    )
                    .detach()
                    .cpu()
                    .tolist()
                ]
            if progress:
                print(
                    "gpu idle_fused: rerootFinal "
                    f"n={len(final_positions)}",
                    flush=True,
                )
            for position in final_positions:
                self._root_hypothesis_start(
                    bone_vectors,
                    root_translation,
                    root_rotation,
                    int(position),
                    progress=progress,
                    started=started,
                    score_escape=True,
                    use_current_bones=True,
                )

        sprite_aligned_report = self._apply_sprite_aligned_motion_keep(
            bone_vectors,
            root_translation,
            root_rotation,
            evaluation_count=evaluation_count,
            progress=progress,
        )
        if bool(self.config.sprite_aligned_motion_keep_enabled):
            self._preview_clip_pose(
                bone_vectors,
                root_translation,
                root_rotation,
                "sprite-aligned",
                force=True,
                commit=True,
            )
        physics_report = self._apply_cascade_physics_smooth(
            bone_vectors,
            root_translation,
            root_rotation,
            progress=progress,
        )
        self._preview_clip_pose(
            bone_vectors,
            root_translation,
            root_rotation,
            "physics",
            force=True,
            commit=True,
        )
        self._mirror_idle_suffix_from_prefix_if_enabled(
            bone_vectors,
            root_translation,
            root_rotation,
        )
        final_bones = self._bounded_bone_vectors(bone_vectors)
        final = self.evaluate(final_bones, root_translation, root_rotation, bone_mask=self.active_node_mask)
        final_hybrid = float(final["score"].mean().detach().item())
        self._write_live_status(
            "final",
            started=started,
            hybrid_mean=final_hybrid,
            geometry_mean=float(final["geometryScore"].mean().detach().item()),
            note="optimize_clip complete",
        )
        result = {
            "poses": self._pose_dicts(bone_vectors, root_translation, root_rotation),
            # Serialized pose x/y/z values are an axis-angle vector in DEGREES
            # (see _pose_dicts / _pose_entry_to_xyz). The GLB clip exporter and
            # any other consumer must require this marker before interpreting
            # the numbers; pre-marker radians-era results melted skinned meshes.
            "poseUnits": "degrees",
            "history": history,
            "score": final_hybrid,
            "frameScores": [float(value) for value in final["score"].detach().cpu().tolist()],
            "frameIoU": [float(value) for value in final["iou"].detach().cpu().tolist()],
            "elapsed": time.perf_counter() - started,
            "evaluationCount": int(evaluation_count[0]),
            "device": str(self.device),
            "backend": "nvdiffrast_exact_triangles" if bool(getattr(self.config, "exact_raster_enabled", False)) else "torch_soft_triangle_surface",
            "bindReport": self.bind_report,
            # Root rotation is evaluated around the sampled bind-surface
            # centroid, not the armature origin. Persist it so the Blender
            # proof renderer can reproduce the same rigid-body transform.
            "rootPivot": [
                float(value)
                for value in self.root_pivot.detach().cpu().tolist()
            ],
            "config": self.config.__dict__.copy(),
            "frameIndices": list(self.frame_indices),
            "bones": [self.node_names[index] for index in self.search_node_indices],
            "skinnedBones": [self.node_names[index] for index in self.active_node_indices],
            "searchBones": list(self.search_bone_names),
            "fineBones": list(self.fine_bone_names),
            "branchGroups": list(branch_groups),
            "chainSpaceHistory": list(chain_space_history),
            "collisionVetoCount": int(collision_veto_count[0]),
            "anatomyVetoCount": int(anatomy_veto_count[0]),
            "solver": "cascade",
            "physicsSmooth": physics_report,
            "spriteAlignedMotionKeep": sprite_aligned_report,
            "scoreEscape": score_escape_reports,
            "anatomyHeadPin": anatomy_head_pin_report,
            "targetPaths": [str(path) for path in self.target_paths],
            "frameDepthError": [float(value) for value in final["depthError"].detach().cpu().tolist()],
            "frameChromaQuality": [float(value) for value in final["chromaQuality"].detach().cpu().tolist()],
            "frameMotionQuality": [float(value) for value in final["motionQuality"].detach().cpu().tolist()],
            "frameCollisionError": [float(value) for value in final["collisionError"].detach().cpu().tolist()],
            "frameDenseSemanticQuality": (
                [float(value) for value in final["denseSemanticQuality"].detach().cpu().tolist()]
                if "denseSemanticQuality" in final
                else None
            ),
        }
        if self.config.return_masks:
            result["targetMasks"] = final["targetMasks"].detach().cpu().numpy()
            result["predictedMasks"] = final["predictedMasks"].detach().cpu().numpy()
        return result


def initialize_gpu_cascade(
    *,
    src_glb: str | Path,
    camera_fit: str | Path,
    target_frame_dir: str | Path,
    frame_indices: Sequence[int],
    config: GpuCascadeConfig | None = None,
) -> GpuCascadeExperiment:
    """Construct the isolated GPU experiment without starting Blender."""
    return GpuCascadeExperiment(
        src_glb=src_glb,
        camera_fit=camera_fit,
        target_frame_dir=target_frame_dir,
        frame_indices=frame_indices,
        config=config,
    )


def run_gpu_clip_pilot(
    experiment: GpuCascadeExperiment,
    *,
    initial_poses: Mapping[int, Mapping[str, Any]] | None = None,
    progress: bool = True,
) -> dict[str, Any]:
    return experiment.optimize_clip(initial_poses=initial_poses, progress=progress)


def exact_triangle_masks_for_result(
    experiment: GpuCascadeExperiment,
    result: Mapping[str, Any],
) -> np.ndarray:
    """Return exact full-triangle masks for a live GPU result.

    This is deliberately separate from ``run_gpu_clip_pilot`` and is intended
    for the notebook parity preview only. It reuses the result's poses and
    current experiment configuration without invoking Blender.
    """
    import torch

    raw_poses = result.get("poses")
    if not isinstance(raw_poses, Mapping):
        raise ValueError("GPU result has no pose mapping")
    poses = {int(frame): pose for frame, pose in raw_poses.items()}
    missing = [frame for frame in experiment.frame_indices if frame not in poses]
    if missing:
        raise ValueError(f"GPU result is missing poses for frames: {missing}")
    bone_vectors, root_translation, root_rotation = experiment._initial_pose_tensors(poses)
    with torch.no_grad():
        return experiment.exact_triangle_masks(
            experiment._bounded_bone_vectors(bone_vectors),
            root_translation,
            root_rotation,
            bone_mask=experiment.active_node_mask,
        )


def _interpolate_pose(left: Mapping[str, Any], right: Mapping[str, Any], fraction: float) -> dict[str, Any]:
    """Linearly interpolate sparse pipeline pose entries for a render frame."""
    keys = set(left) | set(right)
    result: dict[str, Any] = {}
    for key in keys:
        left_entry = left.get(key, {})
        right_entry = right.get(key, {})
        if not isinstance(left_entry, Mapping):
            left_entry = {}
        if not isinstance(right_entry, Mapping):
            right_entry = {}
        axes = set(left_entry) | set(right_entry)
        if key == MOTION_ROOT_ROTATION_KEY:
            # These values are degrees in the worker contract. Use the
            # shortest wrapped path so a +/-180 seam does not spin the model.
            values = {}
            for axis in axes:
                start = float(left_entry.get(axis, 0.0))
                end = float(right_entry.get(axis, 0.0))
                delta = (end - start + 180.0) % 360.0 - 180.0
                values[axis] = start + float(fraction) * delta
            result[key] = values
        else:
            result[key] = {
                axis: float(left_entry.get(axis, 0.0))
                + float(fraction) * (float(right_entry.get(axis, 0.0)) - float(left_entry.get(axis, 0.0)))
                for axis in axes
            }
    return result


def _interpolated_pose_frames(
    poses: Mapping[int, Mapping[str, Any]],
    frame_indices: Sequence[int],
    *,
    source_fps: float,
    output_fps: float,
) -> list[tuple[int, Mapping[str, Any]]]:
    if source_fps <= 0.0 or output_fps <= 0.0:
        raise ValueError("source_fps and output_fps must be positive")
    if output_fps < source_fps:
        raise ValueError("output_fps must not be lower than source_fps")
    frames = [int(frame) for frame in frame_indices]
    if not frames:
        raise ValueError("frame_indices cannot be empty")
    missing = [frame for frame in frames if frame not in poses]
    if missing:
        raise ValueError(f"GPU result is missing poses for frames: {missing}")
    steps = max(1, int(round(float(output_fps) / float(source_fps))))
    output: list[tuple[int, Mapping[str, Any]]] = []
    for index, frame in enumerate(frames[:-1]):
        left = poses[frame]
        right = poses[frames[index + 1]]
        for subframe in range(steps):
            output.append((frame * steps + subframe, _interpolate_pose(left, right, subframe / steps)))
    last = frames[-1]
    output.append((last * steps, poses[last]))
    return output


def _pose_for_blender_export(pose: Mapping[str, Any]) -> dict[str, Any]:
    """Convert GPU pose-dict entries to the Blender worker's pose contract.

    The serialized GPU pose dict stores each bone delta as an axis-angle
    vector in DEGREES (``_pose_dicts`` applies ``np.degrees``). The Blender
    worker builds ``Quaternion(axis, angle)`` from RADIANS, so the vector must
    be converted back to radians before splitting into axis/angle form;
    passing the degree numbers through over-rotates every joint ~57.3x.
    Motion-root entries retain their separate degree/normalized-unit contracts.
    """
    converted: dict[str, Any] = {}
    for name, value in pose.items():
        if name in {MOTION_ROOT_KEY, MOTION_ROOT_ROTATION_KEY}:
            converted[name] = dict(value) if isinstance(value, Mapping) else value
            continue
        if not isinstance(value, Mapping) or not all(axis in value for axis in ("x", "y", "z")):
            converted[name] = value
            continue
        vector = np.radians(
            np.asarray(
                [float(value.get(axis, 0.0)) for axis in ("x", "y", "z")],
                dtype=np.float64,
            )
        )
        angle = float(np.linalg.norm(vector))
        if angle <= 1e-12:
            converted[name] = {"axis": [1.0, 0.0, 0.0], "angle": 0.0}
        else:
            # The GPU vector is expressed in raw glTF Y-up coordinates. The
            # Blender-imported pose bone receives the equivalent Z-up axis.
            axis = GLTF_TO_BLENDER_BASIS @ (vector / angle)
            converted[name] = {"axis": axis.tolist(), "angle": angle}
    return converted


_GPU_CLIP_RESULT_ARRAY_KEYS = frozenset(
    {
        "targetMasks",
        "predictedMasks",
        "targetDepth",
        "predictedDepth",
        "targetRgb",
        "predictedRgb",
        "history",
    }
)


def _jsonable_clip_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _jsonable_clip_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable_clip_value(item) for item in value]
    return value


def persist_gpu_clip_result(result: Mapping[str, Any], output_dir: str | Path) -> Path:
    """Write pose/camera fields without the giant raster arrays.

    The last-cell Blender preview needs these poses after a kernel restart.
    Depth and mask buffers stay in their PNG folders; repeating them here
    would bury the pose contract in unreadable JSON.
    """
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    payload = {
        key: _jsonable_clip_value(value)
        for key, value in result.items()
        if key not in _GPU_CLIP_RESULT_ARRAY_KEYS
    }
    if not isinstance(payload.get("poses"), Mapping) or not payload["poses"]:
        raise RuntimeError("GPU clip result has no poses to persist")
    path = output / "gpu_clip_result.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def export_gpu_render_preview(
    result: Mapping[str, Any],
    *,
    src_glb: str | Path,
    unit_name: str,
    animation_name: str,
    pilot_dir: str | Path,
    camera_fit_path: str | Path,
    frame_indices: Sequence[int],
    meshy_rigidization_report: str | Path | None = None,
    output_dir: str | Path | None = None,
    source_fps: float = 12.0,
    output_fps: float = 60.0,
    frame_duration_ms: int | None = None,
    mesh_scale: float = 1.0,
    render_resolution: tuple[int, int] | None = None,
    preview_matte: tuple[int, int, int] | str | None = (42, 45, 52),
) -> dict[str, Any]:
    """Render an existing GPU pose result at interpolated output cadence.

    This is deliberately an export-only bridge. It does not optimize again;
    Blender is used here only as the final lit-render authority for poses that
    were already selected by the GPU experiment.
    """
    raw_poses = result.get("poses")
    if not isinstance(raw_poses, Mapping) or not raw_poses:
        raise RuntimeError("GPU result has no poses to render")
    # JSON persistence stringifies integer frame keys. Normalize both live
    # notebook results and persisted gpu_clip_result.json artifacts here.
    poses = {int(frame): pose for frame, pose in raw_poses.items()}
    pilot = Path(pilot_dir).resolve()
    out = Path(output_dir) if output_dir is not None else pilot / "gpu_cascade_experiment" / "rendered_60fps"
    out.mkdir(parents=True, exist_ok=True)
    mesh = Path(src_glb).resolve()
    fit = Path(camera_fit_path).resolve()
    if not mesh.is_file():
        raise FileNotFoundError(f"GPU preview mesh is missing: {mesh}")
    if not fit.is_file():
        raise FileNotFoundError(f"GPU preview camera fit is missing: {fit}")
    if meshy_rigidization_report is not None:
        report = Path(meshy_rigidization_report).resolve()
        if not report.is_file():
            raise FileNotFoundError(f"GPU preview Meshy rigidization report is missing: {report}")
    else:
        report = None

    roots = [pilot, *pilot.parents]
    root = next(
        (candidate for candidate in roots if (candidate / "tools" / "homm3_silhouette_pose_fit").is_dir()),
        pilot,
    )
    blender = resolve_pose_fit_blender()
    worker_script = root / "tools" / "homm3_silhouette_pose_fit" / "roc_chroma_match_worker.py"
    if not worker_script.is_file():
        raise FileNotFoundError(f"Blender preview worker is missing: {worker_script}")

    fit_data = json.loads(fit.read_text(encoding="utf-8"))
    source_resolution = fit_data.get("sourceResolution")
    if not isinstance(source_resolution, (list, tuple)) or len(source_resolution) != 2:
        raise ValueError(f"GPU preview camera fit has no sourceResolution: {fit}")
    source_width, source_height = (int(value) for value in source_resolution)
    if source_width <= 0 or source_height <= 0:
        raise ValueError(f"GPU preview camera fit has invalid sourceResolution: {fit}")
    # Keep the final Blender proof at the same aspect ratio as the target and
    # the CUDA raster.  The old fixed 768x683 canvas silently stretched every
    # 1098x876 HoMM3 frame before it reached the preview, so a correct GPU
    # silhouette and a correct Blender mesh could still look inconsistent.
    if render_resolution is None:
        render_width = 768
        render_height = max(1, int(round(render_width * source_height / source_width)))
    else:
        if len(render_resolution) != 2:
            raise ValueError("render_resolution must be (width, height)")
        render_width, render_height = (int(value) for value in render_resolution)
        if render_width < 16 or render_height < 16:
            raise ValueError("render_resolution must be at least 16x16")
    if not math.isfinite(float(mesh_scale)) or float(mesh_scale) <= 0.0:
        raise ValueError("mesh_scale must be finite and positive")
    normalized_preview_matte = _normalize_preview_matte(preview_matte)
    camera = _read_camera_fit(fit, (render_width, render_height))

    result_config = dict(result.get("config", {}) or {})
    configured_root_axes = tuple(
        str(axis)
        for axis in result_config.get(
            "root_translation_axes", ("forward", "lateral", "vertical")
        )
    )
    configured_root_rotation_axes = tuple(
        str(axis)
        for axis in result_config.get(
            "root_rotation_axes", ("camera_forward", "camera_right", "camera_up")
        )
    )
    root_translation_limit = max(
        1e-6,
        abs(float(result_config.get("root_translation_limit_body_lengths", 0.65))),
    )
    root_rotation_limit = max(
        1e-6,
        abs(float(result_config.get("root_rotation_limit_optimization_deg", 180.0))),
    )
    proxy_asset = load_asset(mesh)
    root_pivot = result.get("rootPivot")
    if not isinstance(root_pivot, (list, tuple)) or len(root_pivot) != 3:
        # Older persisted GPU results predate rootPivot. Recompute the exact
        # proxy pivot used by GpuCascadeExperiment rather than falling back to
        # the armature origin, which changes camera-relative root rotation.
        from roc_geometric_proxy import evaluate_points

        bind_points = evaluate_points(proxy_asset, level=1, max_points=20000)
        if len(bind_points) == 0:
            raise RuntimeError("GPU preview mesh has no bind surface points for root pivot")
        root_pivot = np.asarray(bind_points, dtype=np.float64).mean(axis=0).tolist()
    root_pivot_blender = GLTF_TO_BLENDER_BASIS @ np.asarray(root_pivot, dtype=np.float64)
    rest_worlds = _gpu_world_matrices(proxy_asset, None)

    # This payload intentionally contains only render/export controls. It
    # does not execute the semantic-hybrid setup, optimizer, depth pipeline,
    # or cached notebook worker state.
    init_command = {
        "cmd": "init",
        "src": str(mesh),
        "fit": str(fit),
        "autoFrame0Fit": False,
        "width": render_width,
        "height": render_height,
        "searchScale": 0.35,
        # The exact GPU vertex bridge below already applies mesh_scale to the
        # world-space vertices. Scaling the imported armature here would scale
        # those vertices a second time and would also move the armature root.
        "meshScale": 1.0,
        "semanticMultiview": False,
        "searchEngine": "BLENDER_WORKBENCH",
        "searchTaaSamples": 1,
        "proofEngine": "BLENDER_EEVEE",
        "proofTaaSamples": 8,
        "lightingMode": "flat_emission",
        "sunEnergy": 2.0,
        "sunAzimuthDeg": -35.0,
        "sunElevationDeg": 55.0,
        "sunAngleDeg": 5.0,
        "scoreMode": "depth",
        "renderDepth": False,
        "renderResultInMemory": False,
        "renderPngCompression": 0,
        "incrementalPoseApplication": True,
        # Motion-root values are baked into the GPU vertex buffer below. Keep
        # Blender's armature parent at bind so no root transform is applied a
        # second time during the final render.
        "motionRootEnabled": False,
        # GPU root translation is expressed in camera space and in raw GLB
        # world units. Do not reinterpret it as the legacy model-horizontal
        # basis or multiply it by a mesh span during final rendering.
        "motionRootBasis": "camera",
        "motionRootLengthWorld": 1.0,
        "motionRootPivotWorld": [float(value) for value in root_pivot_blender],
        "motionRootAxes": list(configured_root_axes),
        "motionRootForwardRadiusBodyLengths": root_translation_limit,
        "motionRootLateralRadiusBodyLengths": root_translation_limit,
        "motionRootVerticalRadiusBodyLengths": root_translation_limit,
        "motionRootRotationEnabled": False,
        "motionRootRotationAxes": list(configured_root_rotation_axes),
        "motionRootRotationLimitDeg": root_rotation_limit,
        "honorFitScreenOffset": True,
        "fitCoordinateBasis": "gltf_yup_to_blender_zup",
        "detectProfile": False,
        "meshOrientationMode": "none",
        "disableArmatureDeform": True,
        # GPU bone vectors are full local axis-angle deltas. Do not strip
        # twist during export or the Blender preview will not reproduce the
        # silhouette pose that was scored on the GPU.
        "stripBoneRoll": False,
    }
    worker = _GpuPreviewWorker(blender=blender, worker_script=worker_script)
    init_result = worker.request(init_command)
    if not init_result.get("ok"):
        worker.close()
        raise RuntimeError({"ok": False, "error": "GPU preview Blender init failed", "result": init_result})
    interpolated = _interpolated_pose_frames(
        poses,
        frame_indices,
        source_fps=source_fps,
        output_fps=output_fps,
    )
    frame_paths: list[Path] = []
    preview_frame_paths: list[Path] = []
    try:
        for output_index, pose in interpolated:
            worker.request(
                {
                    "cmd": "set_pose",
                    # The final render consumes the exact same weighted-LBS
                    # vertex buffer as the GPU silhouette path. Blender keeps
                    # the imported rig in bind pose and supplies materials,
                    # normals, camera, and lighting only.
                    "angles": {},
                    "meshVerticesWorld": _gpu_deformed_vertex_buffers(
                        proxy_asset,
                        pose,
                        camera=camera,
                        root_pivot=np.asarray(root_pivot, dtype=np.float64),
                        mesh_scale=float(mesh_scale),
                    ),
                }
            )
            frame_path = out / f"frame_{int(output_index):04d}.png"
            worker.request({"cmd": "save_render", "out": str(frame_path)})
            if not frame_path.is_file() or frame_path.stat().st_size <= 0:
                raise RuntimeError(f"GPU preview render was not written: {frame_path}")
            frame_paths.append(frame_path)
            preview_path = out / f"preview_{int(output_index):04d}.png"
            _write_preview_matte(frame_path, preview_path, normalized_preview_matte)
            preview_frame_paths.append(preview_path)
    finally:
        worker.close()

    # GIF and MP4 are inspection deliverables.  They use the neutral matte so
    # transparent pixels do not turn dark textured parts into black-on-black
    # silhouettes.  The original RGBA frame_paths remain the render authority.
    images = [Image.open(path).convert("RGB") for path in preview_frame_paths]
    duration = int(frame_duration_ms or round(1000.0 / float(output_fps)))
    gif_path = out / "gpu_cascade_rendered_60fps.gif"
    images[0].save(
        gif_path,
        save_all=True,
        append_images=images[1:],
        duration=max(1, duration),
        loop=0,
        optimize=False,
    )
    for image in images:
        image.close()

    mp4_path = out / "gpu_cascade_rendered_60fps.mp4"
    try:
        import cv2

        first = Image.open(frame_paths[0]).convert("RGB")
        width, height = first.size
        first.close()
        writer = cv2.VideoWriter(
            str(mp4_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            float(output_fps),
            (width, height),
        )
        if not writer.isOpened():
            raise RuntimeError("OpenCV could not open the GPU preview MP4 writer")
        try:
            for path in frame_paths:
                image = cv2.imread(str(path))
                if image is None:
                    raise RuntimeError(f"could not read GPU preview render: {path}")
                writer.write(image)
        finally:
            writer.release()
    except Exception as exc:
        mp4_path = None
        print(f"GPU preview MP4 unavailable: {exc}")

    return {
        "gif": str(gif_path),
        "mp4": str(mp4_path) if mp4_path is not None else None,
        "framePaths": [str(path) for path in frame_paths],
        "previewFramePaths": [str(path) for path in preview_frame_paths],
        "frameCount": len(frame_paths),
        "renderResolution": [render_width, render_height],
        "sourceFps": float(source_fps),
        "outputFps": float(output_fps),
        "source": "existing GPU pose result; exact GPU-LBS vertex buffers; Blender lit render only",
        "geometryPath": "gpu_lbs_vertex_override",
        "previewMatte": list(normalized_preview_matte) if normalized_preview_matte is not None else None,
    }


def score_rendered_clip_semantics(
    target_paths: Sequence[str | Path],
    candidate_paths: Sequence[str | Path],
    *,
    global_model_id: str = "google/siglip2-base-patch16-512",
    global_embedding_layers: Sequence[str] | str = ("projected",),
    dense_model_id: str | None = "google/siglip2-base-patch16-512",
    dense_feature_layers: Sequence[str | int] | str = ("last",),
    dense_window_radius: int = 1,
    dense_position_weight: float = 0.15,
    device: str = "cuda:0",
) -> dict[str, Any]:
    """Score final Blender frames with global and dense semantic features.

    This is intentionally a post-solve finalist gate. It does not backprop
    through SigLIP/DINO and does not claim that global embeddings can replace
    the differentiable geometry objective. DINOv3 remains an explicit opt-in
    through ``dense_model_id`` and uses the process environment for HF auth.
    """
    from roc_semantic_embedding_match import RocSemanticEmbedder

    targets = [Path(path).resolve() for path in target_paths]
    candidates = [Path(path).resolve() for path in candidate_paths]
    if len(targets) != len(candidates) or not targets:
        raise ValueError("target_paths and candidate_paths must have the same non-zero length")
    for path in (*targets, *candidates):
        if not path.is_file():
            raise FileNotFoundError(f"semantic finalist image is missing: {path}")

    result: dict[str, Any] = {"frameCount": len(targets), "global": None, "dense": None}
    global_embedder = RocSemanticEmbedder(
        model_id=global_model_id,
        embedding_layers=global_embedding_layers,
    )
    global_rows = global_embedder.compare_pairs(list(zip(targets, candidates)), batch_size=1)
    result["global"] = {
        "modelId": global_model_id,
        "embeddingLayers": list(global_embedder.embedding_layers),
        "frameCosines": [float(row["cosine"]) for row in global_rows],
        "meanCosine": float(np.mean([row["cosine"] for row in global_rows])),
    }

    if dense_model_id:
        from dense_semantic_features import DenseFeatureScorer

        dense = DenseFeatureScorer(
            model_id=dense_model_id,
            device=device,
            feature_layers=dense_feature_layers,
        )
        dense_rows = []
        for target, candidate in zip(targets, candidates):
            images = [dense_image for dense_image in (
                RocSemanticEmbedder.load_image(target),
                RocSemanticEmbedder.load_image(candidate),
            )]
            extracted = dense.extract_layers(images)
            target_grids = {layer: values[0:1] for layer, values in extracted.items()}
            candidate_grids = {layer: values[1:2] for layer, values in extracted.items()}
            mean_distance, layer_distances = dense.score_grid_layers_mean(
                target_grids,
                candidate_grids,
                window_radius=dense_window_radius,
                position_weight=dense_position_weight,
            )
            dense_rows.append({
                "distance": float(mean_distance),
                "score": float(1.0 - mean_distance),
                "layerDistances": {str(layer): float(value) for layer, value in layer_distances.items()},
            })
        result["dense"] = {
            "modelId": dense_model_id,
            "featureLayers": [str(layer) for layer in dense.feature_layers],
            "windowRadius": int(dense_window_radius),
            "positionWeight": float(dense_position_weight),
            "frames": dense_rows,
            "meanScore": float(np.mean([row["score"] for row in dense_rows])),
        }
    return result


__all__ = [
    "GpuCascadeConfig",
    "GpuCascadeExperiment",
    "CASCADE_SCORE_MODES",
    "JOINT_SOLVER_MODES",
    "DEFAULT_CASCADE_DINO_V3_MODEL_ID",
    "dinov3_dense_cascade_config",
    "cascade_live_preview_frame_position",
    "cascade_live_preview_frame_positions",
    "cascade_live_preview_pane_size",
    "cascade_live_preview_resize",
    "cascade_live_preview_depth_as_rgb",
    "cascade_live_preview_depth_panel",
    "compose_cascade_solver_watch",
    "crop_rgb_hwc_subject_square",
    "dense_semantic_quality_from_distance",
    "rgb_hwc_batch_to_pil_images",
    "score_dense_semantic_rgb_batch",
    "backtracked_learning_rate",
    "joint_line_search_radians",
    "signed_step_grid_deg",
    "axis_rung_after",
    "joint_score_hyps_per_launch",
    "adam_stage_stalled",
    "joint_probe_should_run_consensus",
    "joint_round_should_run_consensus",
    "joint_round_followup_bones",
    "first_axis_window_deg",
    "joint_unit_step_deg",
    "normalize_keep_scores_for_joint_step",
    "JOINT_STEP_SCORE_NORMS",
    "offset_raw_bone_axis",
    "offset_raw_bone_direction",
    "joint_search_directions",
    "joint_keep_score",
    "neighbor_copy_keep",
    "copy_raw_bone_from_neighbor",
    "lerp_raw_bone_from_neighbors",
    "cluster_bone_angles",
    "clip_uses_idle_end_anchor",
    "idle_prefix_frame_count",
    "idle_suffix_frame_count",
    "seed_end_cluster",
    "independent_cluster_walks",
    "pick_temporal_pose_pass",
    "sequential_cluster_adopt",
    "bidirectional_cluster_adopt",
    "apply_cluster_raw_bone",
    "gather_per_frame_winners",
    "consecutive_sprite_rgb_mad",
    "still_sprite_lock_mask",
    "lock_winner_indices_to_previous",
    "sprite_frame_change_maps",
    "excess_predicted_change",
    "SPRITE_CHANGE_VETO_EPS",
    "veto_scores_on_sprite_change_excess",
    "mask_sprite_change_excess_to_still_frames",
    "previous_predicted_for_sprite_change_gate",
    "gather_clip_winner",
    "sa_temperature",
    "sa_random_initial_pose",
    "sa_perturb_pose",
    "sa_metropolis_accept",
    "load_ik_keypoints",
    "load_ik_bone_roles",
    "resolve_ik_keypoints_path",
    "resolve_ik_bone_roles_path",
    "ik_unproject_2d_to_3d",
    "ik_chains_from_bone_roles",
    "ik_ccd_chain",
    "IncrementalBlobJob",
    "derive_ik_blob_jobs",
    "extra_collision_keep_score",
    "worst_frame_indices",
    "apply_per_frame_coordinate_joint_step",
    "invert_bounded_root_rotation",
    "root_hypothesis_unit_offsets",
    "capability_report",
    "initialize_gpu_cascade",
    "run_gpu_clip_pilot",
    "exact_triangle_masks_for_result",
    "export_gpu_render_preview",
    "persist_gpu_clip_result",
]
