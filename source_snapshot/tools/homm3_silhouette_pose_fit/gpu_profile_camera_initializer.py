"""Blender-free static profile-camera initialization for the GPU pose lane.

The pose solver must not spend bone degrees of freedom compensating for a bad
camera.  This module searches camera azimuth around the selected mesh's seed
camera, uses the imported idle/bind silhouette to choose orientation, fits
scale and framing to a separate shadow-culled movement frame when requested,
and writes a new camera-fit contract for the pose solver to consume.

The default search uses an upright glTF-Y-up turntable basis.  The previous
implementation rotated the seed camera around its own screen-up vector.  That
is mathematically valid, but a pitched seed camera can then make an upright
Meshy rig appear to lie on its side.  Keeping the projected asset up axis
upright is a registration constraint, not a creature-specific assumption.

The search uses the same nvdiffrast filled-triangle rasterizer as the solver.
It is not a semantic camera detector and does not use Blender or a
creature-specific bone name.  HoMM3 battle sprites face screen-right, so
silhouette IoU is combined with painted albedo (Lab chroma) against the idle
sprite. Silhouette alone is ambiguous under a ~180° yaw flip. Selection is:

1. silhouette leader among upright cameras
2. among candidates within ``silhouette_near_tie`` of that leader, drop
   rear/front-on views (facing below ``PROFILE_MIN_PROFILE_FACING``), then
   highest chroma
3. if every near-tie is rear/front-on, pick the highest facing in the band
   (Meshy root +Z must not be a *primary* prior — that locked pikeman)

Bind-pose limb span is not the idle width; scale uses standing height.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image, ImageDraw

from roc_geometric_proxy import _world_matrices
from roc_gpu_cascade_experiment import GpuCascadeConfig, GpuCascadeExperiment

# Weak tertiary only. Root-+Z facing previously locked pikeman onto a back view
# (facing≈1 at yaw=-30) even when silhouette+chroma preferred the front ¾.
PROFILE_FACING_WEIGHT = 0.05
# Painted albedo vs idle sprite during yaw search. Used both in the composite
# score and as the near-tie breaker among near-equal silhouettes.
PROFILE_CHROMA_WEIGHT = 0.35
# v1 reports lack chroma near-tie selection (pikeman/gargoyle stayed back-facing).
# Batch camera reuse must refuse schema < this version and re-run profile_init.
# v3: near-tie chroma must not pick a rear view (min facing floor).
PROFILE_INIT_SCHEMA_VERSION = 3
# Gargoyle-class: sil gap between back (-75) and correct front (+15) was ~0.011.
# Band must cover that without swallowing clearly worse outlines.
PROFILE_SILHOUETTE_NEAR_TIE = 0.02
# HoMM3 battle sprites face screen-right. Chroma-among-silhouette-ties can still
# pick a rear yaw (goblin idle: facing 0.058 at yaw=-120). Floor facing inside
# the near-tie band; do not use facing as the primary silhouette ranker.
PROFILE_MIN_PROFILE_FACING = 0.35
# Bind-pose silhouette + painted albedo at the profile camera after a full yaw
# search. Historical calibration (goblin gremlin swap vs restored mesh at
# ~192x172). The hard fail gate is abandoned (2026-08-23): metrics are still
# recorded for diagnostics, but they must not block pose fit.
PROFILE_MESH_MIN_ORIENTATION_IOU = 0.45
PROFILE_MESH_MIN_ALIGNMENT_SUM = 1.15
PROFILE_MESH_SPRITE_GATE_ENABLED = False


class ProfileMeshSpriteMismatchError(RuntimeError):
    """Legacy mismatch signal. Gate abandoned — prefer metrics logging only."""


@dataclass(frozen=True)
class ProfileCameraInitConfig:
    """Controls for static profile-camera registration."""

    resolution: tuple[int, int] = (96, 86)
    alpha_threshold: int = 8
    predicted_alpha_threshold: float = 0.01
    yaw_min_deg: float = -180.0
    yaw_max_deg: float = 180.0
    yaw_step_deg: float = 15.0
    roll_range_deg: float = 8.0
    roll_step_deg: float = 8.0
    fit_margin: float = 0.96
    top_k: int = 8
    camera_basis_mode: str = "upright_turntable"
    world_up_axis: tuple[float, float, float] = (0.0, 1.0, 0.0)
    facing_weight: float = PROFILE_FACING_WEIGHT
    chroma_weight: float = PROFILE_CHROMA_WEIGHT
    silhouette_near_tie: float = PROFILE_SILHOUETTE_NEAR_TIE
    min_profile_facing: float = PROFILE_MIN_PROFILE_FACING
    rank_metric: str = "composite"
    mesh_sprite_validate: bool = False  # abandoned hard gate; metrics still optional
    mesh_sprite_min_orientation_iou: float = PROFILE_MESH_MIN_ORIENTATION_IOU
    mesh_sprite_min_alignment_sum: float = PROFILE_MESH_MIN_ALIGNMENT_SUM

    def validate(self) -> None:
        width, height = (int(value) for value in self.resolution)
        if width < 16 or height < 16:
            raise ValueError("profile initialization resolution must be at least 16x16")
        if not 0 <= int(self.alpha_threshold) <= 255:
            raise ValueError("profile initialization alpha_threshold must be between 0 and 255")
        if not 0.0 < float(self.predicted_alpha_threshold) <= 1.0:
            raise ValueError("profile initialization predicted_alpha_threshold must be in (0, 1]")
        if not math.isfinite(float(self.yaw_min_deg)) or not math.isfinite(float(self.yaw_max_deg)):
            raise ValueError("profile initialization yaw bounds must be finite")
        if float(self.yaw_max_deg) <= float(self.yaw_min_deg):
            raise ValueError("profile initialization yaw_max_deg must exceed yaw_min_deg")
        if not math.isfinite(float(self.yaw_step_deg)) or float(self.yaw_step_deg) <= 0.0:
            raise ValueError("profile initialization yaw_step_deg must be positive")
        if not math.isfinite(float(self.roll_range_deg)) or float(self.roll_range_deg) < 0.0:
            raise ValueError("profile initialization roll_range_deg must be non-negative")
        if not math.isfinite(float(self.roll_step_deg)) or float(self.roll_step_deg) <= 0.0:
            raise ValueError("profile initialization roll_step_deg must be positive")
        if not 0.0 < float(self.fit_margin) <= 1.0:
            raise ValueError("profile initialization fit_margin must be in (0, 1]")
        if int(self.top_k) < 1:
            raise ValueError("profile initialization top_k must be positive")
        if str(self.camera_basis_mode) not in {
            "upright_turntable",
            "seed_screen_up",
            "geometry_broad_thin",
        }:
            raise ValueError(
                "profile initialization camera_basis_mode must be "
                "'upright_turntable', 'seed_screen_up', or 'geometry_broad_thin'"
            )
        world_up = np.asarray(self.world_up_axis, dtype=np.float32).reshape(-1)
        if not math.isfinite(float(self.facing_weight)) or float(self.facing_weight) < 0.0:
            raise ValueError("profile initialization facing_weight must be finite and >= 0")
        if not math.isfinite(float(self.chroma_weight)) or float(self.chroma_weight) < 0.0:
            raise ValueError("profile initialization chroma_weight must be finite and >= 0")
        if not math.isfinite(float(self.silhouette_near_tie)) or float(self.silhouette_near_tie) < 0.0:
            raise ValueError("profile initialization silhouette_near_tie must be finite and >= 0")
        if not math.isfinite(float(self.min_profile_facing)) or not (
            0.0 <= float(self.min_profile_facing) <= 1.0
        ):
            raise ValueError("profile initialization min_profile_facing must be in [0, 1]")
        if str(self.rank_metric) not in {"composite", "iou"}:
            raise ValueError("profile initialization rank_metric must be 'composite' or 'iou'")
        if world_up.shape != (3,) or float(np.linalg.norm(world_up)) <= 1e-8:
            raise ValueError("profile initialization world_up_axis must be a non-zero 3-vector")
        if not math.isfinite(float(self.mesh_sprite_min_orientation_iou)) or not (
            0.0 <= float(self.mesh_sprite_min_orientation_iou) <= 1.0
        ):
            raise ValueError("mesh_sprite_min_orientation_iou must be in [0, 1]")
        if not math.isfinite(float(self.mesh_sprite_min_alignment_sum)) or float(
            self.mesh_sprite_min_alignment_sum
        ) <= 0.0:
            raise ValueError("mesh_sprite_min_alignment_sum must be positive")


@dataclass(frozen=True)
class ProfileCameraInitialization:
    """Artifacts and diagnostics from the static camera search."""

    camera_fit_path: Path
    report_path: Path
    preview_path: Path
    frame_index: int
    elapsed_seconds: float
    best: dict[str, Any]
    candidates: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cameraFitPath": str(self.camera_fit_path),
            "reportPath": str(self.report_path),
            "previewPath": str(self.preview_path),
            "frameIndex": int(self.frame_index),
            "elapsedSeconds": float(self.elapsed_seconds),
            "best": self.best,
            "candidates": list(self.candidates),
        }


def _unit(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32)
    length = float(np.linalg.norm(vector))
    if length <= 1e-8:
        raise ValueError("camera basis contains a zero-length vector")
    return vector / length


def screen_up_world_alignment(
    basis_screen_rows: Sequence[Sequence[float]],
    world_up_axis: Sequence[float] = (0.0, 1.0, 0.0),
) -> float:
    """Return screen-up · world-up for a camera-fit ``basisScreenRows`` pair."""
    rows = np.asarray(basis_screen_rows, dtype=np.float32)
    if rows.shape != (2, 3):
        raise ValueError("camera fit basisScreenRows must have shape [2,3]")
    down = _unit(rows[1])
    world_up = _unit(np.asarray(world_up_axis, dtype=np.float32))
    return float(np.dot(-down, world_up))


def minimum_upright_screen_alignment(
    *,
    camera_basis_mode: str,
    roll_range_deg: float,
) -> float | None:
    """Lowest |screen-up · world-up| allowed when searching an upright turntable.

    ``seed_screen_up`` is an explicit diagnostic and may keep a pitched seed.
    """
    mode = str(camera_basis_mode)
    if mode == "seed_screen_up":
        return None
    if mode not in {"upright_turntable", "geometry_broad_thin"}:
        raise ValueError(f"unknown profile camera basis mode: {mode!r}")
    return float(math.cos(math.radians(max(0.0, float(roll_range_deg)) + 1.0)))


def select_upright_profile_candidates(
    candidates: Sequence[dict[str, Any]],
    *,
    camera_basis_mode: str,
    roll_range_deg: float,
) -> list[dict[str, Any]]:
    """Rank cameras by score, then drop any that pitch the mesh onto its side."""
    if not candidates:
        raise RuntimeError("profile initialization generated no camera candidates")
    ranked = sorted(candidates, key=lambda item: float(item["score"]), reverse=True)
    min_alignment = minimum_upright_screen_alignment(
        camera_basis_mode=camera_basis_mode,
        roll_range_deg=roll_range_deg,
    )
    if min_alignment is None:
        return ranked
    eligible = [
        item
        for item in ranked
        if abs(float(item["screenUpWorldAlignment"])) >= float(min_alignment)
    ]
    if not eligible:
        best = ranked[0]
        raise RuntimeError(
            "profile initialization would keep a camera that pitches the mesh "
            "onto its side "
            f"(best screen-up·world-up={float(best['screenUpWorldAlignment']):.3f}, "
            f"need >={float(min_alignment):.3f}). Refusing the seed picker camera."
        )
    return eligible


def select_profile_orientation_candidate(
    eligible: Sequence[dict[str, Any]],
    *,
    rank_metric: str = "composite",
    silhouette_near_tie: float = PROFILE_SILHOUETTE_NEAR_TIE,
    chroma_enabled: bool = True,
    min_profile_facing: float = PROFILE_MIN_PROFILE_FACING,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pick orientation: silhouette leader, then chroma among profile-facing ties.

    Armature facing is not the primary ranker. Returning ``(best, diagnostics)``.
    """
    if not eligible:
        raise RuntimeError("profile orientation selection requires at least one candidate")
    metric = str(rank_metric)
    if metric not in {"composite", "iou"}:
        raise ValueError(f"unknown profile rank_metric: {metric!r}")
    primary_key = "iou" if metric == "iou" else "silhouetteScore"
    band = float(silhouette_near_tie)
    if not math.isfinite(band) or band < 0.0:
        raise ValueError("silhouette_near_tie must be finite and >= 0")
    facing_floor = float(min_profile_facing)
    if not math.isfinite(facing_floor) or not (0.0 <= facing_floor <= 1.0):
        raise ValueError("min_profile_facing must be in [0, 1]")

    by_primary = sorted(eligible, key=lambda item: float(item[primary_key]), reverse=True)
    leader = by_primary[0]
    leader_primary = float(leader[primary_key])
    near = [
        item
        for item in by_primary
        if leader_primary - float(item[primary_key]) <= band
    ]
    if bool(chroma_enabled):
        profile_near = [
            item
            for item in near
            if float(item.get("facingScore", 0.0)) >= facing_floor
        ]
        if profile_near:
            pool = profile_near
            facing_rule = "profile_facing_then_chroma"
        else:
            pool = near
            facing_rule = "max_facing_in_silhouette_band"
        if facing_rule == "max_facing_in_silhouette_band":
            near_sorted = sorted(
                pool,
                key=lambda item: (
                    float(item.get("facingScore", 0.0)),
                    float(item.get("chromaQuality", 0.0)),
                    float(item.get("score", 0.0)),
                    float(item[primary_key]),
                ),
                reverse=True,
            )
        else:
            near_sorted = sorted(
                pool,
                key=lambda item: (
                    float(item.get("chromaQuality", 0.0)),
                    float(item.get("facingScore", 0.0)),
                    float(item.get("score", 0.0)),
                    float(item[primary_key]),
                ),
                reverse=True,
            )
        best = near_sorted[0]
        selection_rule = (
            f"near_tie_{facing_rule}_on_{primary_key}"
            if len(near) > 1
            else f"primary_{primary_key}"
        )
    elif metric == "iou":
        best = leader
        selection_rule = f"primary_{primary_key}"
        facing_rule = "unused"
        profile_near = near
    else:
        best = sorted(eligible, key=lambda item: float(item["score"]), reverse=True)[0]
        selection_rule = "composite_score"
        facing_rule = "unused"
        profile_near = near

    diagnostics = {
        "selectionRule": selection_rule,
        "primaryMetric": primary_key,
        "primaryLeader": float(leader_primary),
        "silhouetteNearTie": float(band),
        "nearTieCount": int(len(near)),
        "profileFacingFloor": float(facing_floor),
        "profileFacingNearCount": int(len(profile_near)) if bool(chroma_enabled) else 0,
        "facingSelection": facing_rule if bool(chroma_enabled) else "unused",
        "chromaEnabled": bool(chroma_enabled),
        "selectedPrimary": float(best[primary_key]),
        "selectedChromaQuality": float(best.get("chromaQuality", 0.0)),
        "selectedFacingScore": float(best.get("facingScore", 0.0)),
        "selectedYawDeg": float(best["yawDeg"]),
        "selectedRollDeg": float(best["rollDeg"]),
    }
    return best, diagnostics


def assert_solver_camera_is_registered_profile(
    camera_fit: str | Path,
    *,
    profile_init_enabled: bool,
    world_up_axis: Sequence[float] = (0.0, 1.0, 0.0),
    min_alignment: float = 0.5,
) -> None:
    """Refuse a pitched pose-picker camera when profile initialization is off.

    ``provisional_job_camera`` looks down and across the imported Y-up rig, so
    an upright Meshy mesh projects as if it were lying on its side. Profile
    initialization replaces that camera; skipping it is not a shortcut.
    """
    if bool(profile_init_enabled):
        return
    path = Path(camera_fit)
    data = json.loads(path.read_text(encoding="utf-8"))
    policy = str(data.get("cameraPolicy") or "").strip()
    alignment = screen_up_world_alignment(
        data.get("basisScreenRows"),
        world_up_axis,
    )
    if policy == "provisional_job_camera":
        raise RuntimeError(
            "simple depth solver refused provisional_job_camera without "
            "profile_init. That picker camera pitches an upright Meshy rig onto "
            "its side. Set profile_init_enabled=True, or point camera_fit_path at "
            "a gpu_profile_initialization camera."
        )
    if abs(alignment) < float(min_alignment):
        raise RuntimeError(
            "simple depth solver camera screen-up is not aligned with world-up "
            f"(dot={alignment:.3f} < {float(min_alignment):.3f}). The mesh will "
            "appear to lie on its side. Enable profile_init or replace the camera fit."
        )


def _rotate(vector: np.ndarray, axis: np.ndarray, degrees: float) -> np.ndarray:
    """Rodrigues rotation used only for the low-cardinality camera search."""
    axis = _unit(axis)
    angle = math.radians(float(degrees))
    cosine = math.cos(angle)
    sine = math.sin(angle)
    vector = np.asarray(vector, dtype=np.float32)
    return (
        vector * cosine
        + np.cross(axis, vector) * sine
        + axis * float(np.dot(axis, vector)) * (1.0 - cosine)
    ).astype(np.float32)


def _inclusive_grid(minimum: float, maximum: float, step: float) -> np.ndarray:
    values = np.arange(float(minimum), float(maximum) + float(step) * 0.5, float(step))
    values = np.clip(values, float(minimum), float(maximum))
    values = np.concatenate((values, np.asarray((minimum, maximum, 0.0), dtype=np.float64)))
    return np.unique(np.round(values, decimals=6))


def _mask_bounds(mask: np.ndarray) -> dict[str, float]:
    ys, xs = np.where(np.asarray(mask, dtype=bool))
    if len(xs) == 0:
        raise ValueError("profile initialization target contains no foreground pixels")
    return {
        "xmin": float(xs.min()),
        "xmax": float(xs.max()),
        "ymin": float(ys.min()),
        "ymax": float(ys.max()),
        "width": float(xs.max() - xs.min() + 1),
        "height": float(ys.max() - ys.min() + 1),
        "centerX": float(xs.mean()),
        "centerY": float(ys.mean()),
    }


def _bbox_from_mask(mask: np.ndarray) -> dict[str, float] | None:
    ys, xs = np.where(np.asarray(mask, dtype=bool))
    if len(xs) == 0:
        return None
    return {
        "xmin": float(xs.min()),
        "xmax": float(xs.max()),
        "ymin": float(ys.min()),
        "ymax": float(ys.max()),
        "width": float(xs.max() - xs.min() + 1),
        "height": float(ys.max() - ys.min() + 1),
        "centerX": float(xs.mean()),
        "centerY": float(ys.mean()),
    }


def _load_alpha_mask(path: Path, resolution: tuple[int, int], threshold: int) -> np.ndarray:
    """Load one alpha mask at the initializer's working resolution.

    RIFE plates keep gray RGB on zero-alpha pixels. ``Image.convert("L")`` is
    luma of that RGB, so it would treat the whole canvas as the subject and
    the camera scale would fill the plate instead of the character.
    """
    width, height = (int(value) for value in resolution)
    if width < 1 or height < 1:
        raise ValueError(f"profile initialization mask resolution must be positive, got {(width, height)}")
    with Image.open(path) as image:
        if "A" not in image.getbands():
            raise ValueError(f"profile initialization frame has no alpha channel: {path}")
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    alpha = rgba[:, :, 3]
    binary = Image.fromarray(((alpha >= int(threshold)).astype(np.uint8) * 255), "L")
    resized = binary.resize((width, height), Image.Resampling.NEAREST)
    return np.asarray(resized, dtype=np.uint8) >= 128


def _normalize_mask_to_reference(
    mask: np.ndarray,
    reference: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Move an orientation target into the reference target's pixel scale.

    DEF exports from different preparation runs can have different canvas and
    subject scales.  Matching their raw pixels would make static registration
    solve scale and orientation at once.  Preserve the source mask's internal
    silhouette, but map its foreground bounds to the selected animation's
    frame-00 bounds before the camera search.
    """
    source_bounds = _mask_bounds(mask)
    reference_bounds = _mask_bounds(reference)
    source_box = (
        int(source_bounds["xmin"]),
        int(source_bounds["ymin"]),
        int(source_bounds["xmax"] + 1),
        int(source_bounds["ymax"] + 1),
    )
    reference_box = (
        int(reference_bounds["xmin"]),
        int(reference_bounds["ymin"]),
        int(reference_bounds["xmax"] + 1),
        int(reference_bounds["ymax"] + 1),
    )
    crop = Image.fromarray(np.asarray(mask[source_box[1]:source_box[3], source_box[0]:source_box[2]], dtype=np.uint8) * 255, "L")
    target_width = max(1, reference_box[2] - reference_box[0])
    target_height = max(1, reference_box[3] - reference_box[1])
    resized = np.asarray(
        crop.resize((target_width, target_height), Image.Resampling.NEAREST),
        dtype=np.uint8,
    ) >= 128
    normalized = np.zeros_like(reference, dtype=bool)
    normalized[reference_box[1]:reference_box[3], reference_box[0]:reference_box[2]] = resized
    return normalized, {
        "sourceBounds": source_bounds,
        "referenceBounds": reference_bounds,
        "sourceBox": list(source_box),
        "referenceBox": list(reference_box),
    }


def _bind_vertices(backend: GpuCascadeExperiment):
    import torch

    zero_bones = torch.zeros(
        (1, len(backend.asset.nodes), 3), dtype=torch.float32, device=backend.device
    )
    worlds = backend._forward_kinematics(zero_bones, bone_mask=backend.active_node_mask)
    parts = []
    with torch.no_grad():
        for primitive in backend.primitives:
            parts.append(backend._skinned_vertices(worlds, primitive)[0])
    if not parts:
        raise ValueError("profile initialization found no mesh geometry")
    return torch.cat(parts, dim=0)


def _set_backend_camera(
    backend: GpuCascadeExperiment,
    *,
    right: np.ndarray,
    down: np.ndarray,
    forward: np.ndarray,
    offset: np.ndarray,
    px_per_world: np.ndarray,
) -> None:
    import torch

    backend.camera_right = torch.as_tensor(right, dtype=torch.float32, device=backend.device)
    backend.camera_down = torch.as_tensor(down, dtype=torch.float32, device=backend.device)
    backend.camera_up = -backend.camera_down
    backend.camera_forward = torch.as_tensor(forward, dtype=torch.float32, device=backend.device)
    backend.camera_offset = torch.as_tensor(offset, dtype=torch.float32, device=backend.device)
    backend.px_per_world = torch.as_tensor(px_per_world, dtype=torch.float32, device=backend.device)
    backend.root_basis = torch.stack((backend.camera_forward, backend.camera_right, backend.camera_up), dim=0)


def _camera_candidate_basis(
    seed_right: np.ndarray,
    seed_down: np.ndarray,
    seed_forward: np.ndarray,
    *,
    yaw_deg: float,
    roll_deg: float,
    mode: str = "upright_turntable",
    world_up_axis: Sequence[float] = (0.0, 1.0, 0.0),
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return an orthonormal camera basis for one registration candidate.

    ``upright_turntable`` rotates the seed view direction around the asset's
    world-up axis, then projects that axis onto the camera plane for screen
    up.  This prevents camera pitch from becoming an accidental 90-degree
    roll of the subject.  ``seed_screen_up`` is retained as an explicit
    diagnostic/compatibility mode for comparing against the old initializer.
    """
    if str(mode) in {"upright_turntable", "geometry_broad_thin"}:
        world_up = _unit(np.asarray(world_up_axis, dtype=np.float32))
        # The picker camera is often pitched down toward the source sprite.
        # Rotating that pitched ray around world-up preserves the pitch and
        # makes every candidate look diagonally down at the rig.  That is not
        # a profile search: an upright mesh can appear to lie on its back.
        # Remove the seed's world-up component before the turntable search so
        # each candidate is a level, horizontal view of the imported Y-up rig.
        seed_horizontal = _unit(
            _unit(seed_forward)
            - world_up * float(np.dot(_unit(seed_forward), world_up))
        )
        forward = _unit(_rotate(seed_horizontal, world_up, yaw_deg))
        up = world_up.copy()
        right = _unit(np.cross(forward, up))
        right = _unit(_rotate(right, forward, roll_deg))
        up = _unit(_rotate(up, forward, roll_deg))
        down = -up
        forward = _unit(np.cross(up, right))
        return right, down, forward
    if str(mode) not in {"seed_screen_up", "geometry_broad_thin"}:
        raise ValueError(f"unknown profile camera basis mode: {mode!r}")
    seed_up = _unit(-seed_down)
    yaw_right = _rotate(seed_right, seed_up, yaw_deg)
    yaw_down = _rotate(seed_down, seed_up, yaw_deg)
    yaw_forward = _rotate(seed_forward, seed_up, yaw_deg)
    right = _rotate(yaw_right, yaw_forward, roll_deg)
    down = _rotate(yaw_down, yaw_forward, roll_deg)
    right = _unit(right)
    down = _unit(down - right * float(np.dot(down, right)))
    up = _unit(-down)
    forward = _unit(np.cross(up, right))
    return right, down, forward


def _character_ground_forward(asset: Any, world_up: np.ndarray) -> np.ndarray:
    """Return the character's ground-plane facing from the armature root +Z.

    Meshy UniRig stores that axis on the armature root, not on bone index 0,
    which is often a head or finger in export order.
    """
    worlds = _world_matrices(asset, None)
    chosen_index = None
    for index, node in enumerate(asset.nodes):
        if node.parent is not None:
            continue
        if chosen_index is None:
            chosen_index = index
        name = str(node.name or "").lower()
        if "armature" in name or name.startswith("unirig"):
            chosen_index = index
            break
    if chosen_index is None:
        raise ValueError("profile initialization mesh has no root node")
    axis = np.asarray(worlds[int(chosen_index)][:3, 2], dtype=np.float32)
    world_up = _unit(world_up)
    flattened = axis - world_up * float(np.dot(axis, world_up))
    if float(np.linalg.norm(flattened)) <= 1e-6:
        fallback = np.asarray((0.0, 0.0, 1.0), dtype=np.float32)
        flattened = fallback - world_up * float(np.dot(fallback, world_up))
    if float(np.linalg.norm(flattened)) <= 1e-6:
        raise ValueError("profile initialization could not derive a ground-plane facing axis")
    return _unit(flattened)


def _profile_facing_score(character_forward: np.ndarray, right: np.ndarray) -> float:
    """1 when the character faces screen-right; 0 for front, back, or face-left."""
    return max(0.0, float(np.dot(_unit(character_forward), _unit(right))))


def _silhouette_selection_score(
    *,
    silhouette_score: float,
    geometry_score: float,
    character_forward: np.ndarray,
    right: np.ndarray,
    camera_basis_mode: str,
    facing_weight: float = PROFILE_FACING_WEIGHT,
    chroma_quality: float = 0.0,
    chroma_weight: float = PROFILE_CHROMA_WEIGHT,
) -> tuple[float, float]:
    facing = _profile_facing_score(character_forward, right)
    if str(camera_basis_mode) == "geometry_broad_thin":
        return float(geometry_score), facing
    return (
        float(silhouette_score)
        + float(facing_weight) * facing
        + float(chroma_weight) * float(chroma_quality),
        facing,
    )


def _geometry_profile_score(
    vertices: np.ndarray,
    *,
    right: np.ndarray,
    down: np.ndarray,
    forward: np.ndarray,
    seed_forward: np.ndarray,
) -> float:
    """Prefer a broad, thin view of the bind mesh without using a target pose.

    The registration mesh is in its idle/bind pose while an animation frame can
    have a much wider stance, a raised weapon, or a crouch.  Using that action
    silhouette to choose camera yaw makes the initializer rotate the mesh to
    compensate for articulation.  This geometry-only criterion is the same
    broad/thin test used by the earlier reliable Blender profile detector, but
    runs on the already decoded GPU rig vertices and keeps the authored side as
    a deterministic tie-breaker.
    """
    relative = np.asarray(vertices, dtype=np.float32)
    center = relative.mean(axis=0, keepdims=True)
    relative = relative - center
    width = float(np.ptp(relative @ np.asarray(right, dtype=np.float32)))
    height = float(np.ptp(relative @ np.asarray(down, dtype=np.float32)))
    thickness = float(np.ptp(relative @ np.asarray(forward, dtype=np.float32)))
    broad_thin = width / max(thickness + 0.12 * height, 1e-8)
    facing_tiebreak = 0.015 * float(
        np.dot(
            _unit(np.asarray(forward, dtype=np.float32)),
            _unit(np.asarray(seed_forward, dtype=np.float32)),
        )
    )
    return broad_thin + facing_tiebreak


def _fit_scale_and_offset(
    vertices: np.ndarray,
    target_bounds: dict[str, float],
    right: np.ndarray,
    down: np.ndarray,
    seed_px_per_world: np.ndarray,
    fit_margin: float,
) -> tuple[np.ndarray, np.ndarray]:
    raw_x = vertices @ right
    raw_y = vertices @ down
    raw_width = float(raw_x.max() - raw_x.min())
    raw_height = float(raw_y.max() - raw_y.min())
    if raw_width <= 1e-8 or raw_height <= 1e-8:
        raise ValueError("profile initialization projected mesh has zero width or height")
    base_px = np.asarray(seed_px_per_world, dtype=np.float32).reshape(2)
    # Bind pose is often a T-pose or A-pose. Idle sprites are not. Fitting
    # isotropic scale with min(width, height) shrinks the body until the
    # outstretched arms or weapon fit inside the idle bbox, so the standing
    # figure is too short. Idle and bind share standing height, not width.
    multiplier = target_bounds["height"] * float(fit_margin) / (
        raw_height * max(float(base_px[1]), 1e-8)
    )
    multiplier = max(float(multiplier), 1e-8)
    px_per_world = base_px * multiplier
    raw_center = np.asarray(
        (
            float((raw_x.min() + raw_x.max()) * 0.5),
            float((raw_y.min() + raw_y.max()) * 0.5),
        ),
        dtype=np.float32,
    )
    target_center = np.asarray((target_bounds["centerX"], target_bounds["centerY"]), dtype=np.float32)
    offset = target_center - raw_center * px_per_world
    return px_per_world.astype(np.float32), offset.astype(np.float32)


def _score_mask(
    target: np.ndarray,
    candidate: np.ndarray,
    *,
    target_bounds: dict[str, float],
) -> tuple[float, dict[str, float]]:
    candidate_bounds = _bbox_from_mask(candidate)
    if candidate_bounds is None:
        return 0.0, {
            "iou": 0.0,
            "centroidErrorPx": float("inf"),
            "bboxError": float("inf"),
        }
    target = np.asarray(target, dtype=bool)
    candidate = np.asarray(candidate, dtype=bool)
    intersection = float(np.logical_and(target, candidate).sum())
    union = float(np.logical_or(target, candidate).sum())
    iou = intersection / max(union, 1.0)
    centroid_error = math.hypot(
        candidate_bounds["centerX"] - target_bounds["centerX"],
        candidate_bounds["centerY"] - target_bounds["centerY"],
    )
    diagonal = math.hypot(target.shape[1], target.shape[0])
    centroid_term = math.exp(-4.0 * centroid_error / max(diagonal, 1.0))
    bbox_error = abs(math.log(candidate_bounds["width"] / max(target_bounds["width"], 1.0)))
    bbox_error += abs(math.log(candidate_bounds["height"] / max(target_bounds["height"], 1.0)))
    bbox_term = math.exp(-2.0 * bbox_error)
    # IoU dominates. The other terms keep a badly framed candidate from
    # winning simply because it overlaps one broad part of the subject.
    score = 0.72 * iou + 0.16 * centroid_term + 0.12 * bbox_term
    return float(score), {
        "iou": float(iou),
        "centroidErrorPx": float(centroid_error),
        "bboxError": float(bbox_error),
    }


def _write_camera_fit(
    seed_path: Path,
    output_path: Path,
    *,
    right: np.ndarray,
    down: np.ndarray,
    px_per_world: np.ndarray,
    offset: np.ndarray,
    resolution: tuple[int, int],
    best: dict[str, Any],
    frame_index: int,
    camera_basis_mode: str,
    world_up_axis: Sequence[float],
) -> None:
    data = json.loads(seed_path.read_text(encoding="utf-8"))
    source_width, source_height = (int(value) for value in data["sourceResolution"])
    width, height = (int(value) for value in resolution)
    scale_x = width / max(source_width, 1)
    scale_y = height / max(source_height, 1)
    source_px = float(px_per_world[0]) / max(scale_x, 1e-8)
    source_offset = np.asarray(
        (float(offset[0]) / max(scale_x, 1e-8), float(offset[1]) / max(scale_y, 1e-8)),
        dtype=np.float32,
    )
    data["basisScreenRows"] = [right.astype(float).tolist(), down.astype(float).tolist()]
    data["pxPerWorld"] = source_px
    data["screenOffsetPx"] = source_offset.astype(float).tolist()
    data["cameraPolicy"] = "gpu_profile_initialization"
    data["sourceFrame"] = int(frame_index)
    data["profileMetrics"] = {
        "source": str(seed_path),
        "initializer": "nvdiffrast_exact_alpha_profile_search",
        "cameraBasisMode": str(camera_basis_mode),
        "worldUpAxis": [float(value) for value in world_up_axis],
        "characterForward": [float(value) for value in best.get("characterForward", (0.0, 0.0, 1.0))],
        "bestYawDeg": float(best["yawDeg"]),
        "bestRollDeg": float(best["rollDeg"]),
        "bestScore": float(best["score"]),
        "bestIoU": float(best["iou"]),
        "centroidErrorPx": float(best["centroidErrorPx"]),
        "bboxError": float(best["bboxError"]),
        "screenUpWorldAlignment": float(best["screenUpWorldAlignment"]),
        "facingScore": float(best.get("facingScore", 0.0)),
        "chromaQuality": float(best.get("chromaQuality", 0.0)),
        "chromaWeight": float(best.get("chromaWeight", 0.0)),
    }
    mesh_alignment = best.get("meshSpriteAlignment")
    if isinstance(mesh_alignment, dict):
        data["profileMetrics"]["meshSpriteAlignment"] = mesh_alignment
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _mask_image(mask: np.ndarray) -> Image.Image:
    return Image.fromarray((np.asarray(mask, dtype=np.uint8) * 255), "L").convert("RGB")


def _overlay_image(target: np.ndarray, candidate: np.ndarray) -> Image.Image:
    target = np.asarray(target, dtype=bool)
    candidate = np.asarray(candidate, dtype=bool)
    overlay = np.zeros((*target.shape, 3), dtype=np.uint8)
    overlay[target & ~candidate] = (235, 45, 45)
    overlay[candidate & ~target] = (45, 105, 240)
    overlay[target & candidate] = (35, 210, 100)
    return Image.fromarray(overlay, "RGB")


def _write_initialization_preview(
    output_path: Path,
    *,
    target: np.ndarray,
    candidates: Sequence[dict[str, Any]],
    scale: int = 3,
) -> None:
    width = int(target.shape[1])
    height = int(target.shape[0])
    panels: list[Image.Image] = [_mask_image(target)]
    titles = ["target alpha"]
    for index, candidate in enumerate(candidates):
        panels.append(_overlay_image(target, candidate["mask"]))
        chroma = candidate.get("chromaQuality")
        chroma_note = (
            f" ch={float(chroma):.2f}" if chroma is not None else ""
        )
        titles.append(
            f"#{index + 1} yaw={candidate['yawDeg']:.0f} roll={candidate['rollDeg']:.0f} "
            f"IoU={candidate['iou']:.3f}{chroma_note}"
        )
    columns = min(3, len(panels))
    rows = int(math.ceil(len(panels) / columns))
    panel_height = height + 18
    canvas = Image.new("RGB", (columns * width, rows * panel_height), (24, 24, 24))
    draw = ImageDraw.Draw(canvas)
    for index, panel in enumerate(panels):
        x = (index % columns) * width
        y = (index // columns) * panel_height
        canvas.paste(panel, (x, y + 18))
        draw.text((x + 3, y + 3), titles[index], fill=(240, 240, 240))
    if int(scale) != 1:
        canvas = canvas.resize((canvas.width * int(scale), canvas.height * int(scale)), Image.Resampling.NEAREST)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)


def _load_target_rgb_tensor(
    frame_path: Path,
    resolution: tuple[int, int],
    *,
    device: Any,
):
    import torch
    import torch.nn.functional as F

    width, height = (int(value) for value in resolution)
    with Image.open(frame_path) as image:
        if "A" not in image.getbands():
            raise ValueError(f"profile mesh-sprite validation frame has no alpha: {frame_path}")
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    rgb = torch.from_numpy(np.ascontiguousarray(rgba[..., :3], dtype=np.float32) / 255.0)
    rgb = rgb.permute(2, 0, 1).unsqueeze(0)
    rgb = F.interpolate(rgb, size=(height, width), mode="nearest")[0].permute(1, 2, 0)
    alpha = torch.from_numpy((rgba[:, :, 3] >= 128).astype(np.float32))
    alpha = F.interpolate(alpha.unsqueeze(0).unsqueeze(0), size=(height, width), mode="nearest")[0, 0]
    return rgb.to(device=device, dtype=torch.float32), alpha.to(device=device, dtype=torch.float32)


def _profile_bind_pose_chroma_quality(
    backend: GpuCascadeExperiment,
    *,
    target_rgb,
    target_alpha,
    predicted_alpha_threshold: float,
) -> dict[str, float]:
    import torch

    from gpu_geometry_score import chroma_quality, srgb_rgb_to_lab_ab

    zero_bones = torch.zeros(
        (1, len(backend.asset.nodes), 3), dtype=torch.float32, device=backend.device
    )
    zero_root = torch.zeros((1, 3), dtype=torch.float32, device=backend.device)
    with torch.no_grad():
        alpha, _ = backend._exact_triangle_raster(
            zero_bones,
            zero_root,
            zero_root,
            bone_mask=backend.active_node_mask,
        )
        pred_rgb, _, _ = backend.exact_triangle_rgb(
            zero_bones,
            zero_root,
            zero_root,
            bone_mask=backend.active_node_mask,
        )
    pred_fg = alpha[0] > float(predicted_alpha_threshold)
    target_fg = target_alpha > 0.5
    target_ab = srgb_rgb_to_lab_ab(target_rgb.unsqueeze(0))
    pred_ab = srgb_rgb_to_lab_ab(pred_rgb)
    scored = chroma_quality(
        target_foreground=target_fg.unsqueeze(0),
        predicted_foreground=pred_fg.unsqueeze(0),
        target_ab=target_ab,
        predicted_ab=pred_ab,
        chroma_tolerance=0.10,
        chroma_robust_delta=0.12,
        chroma_error_scale=80.0,
    )
    return {
        "chromaQuality": float(scored["chromaQuality"].item()),
        "chromaError": float(scored["chromaError"].item()),
        "predictedForegroundPixels": int(pred_fg.sum().item()),
        "targetForegroundPixels": int(target_fg.sum().item()),
    }


def evaluate_profile_mesh_sprite_alignment(
    backend: GpuCascadeExperiment,
    *,
    orientation_target: np.ndarray,
    target_frame_path: Path,
    orientation_iou: float,
    config: ProfileCameraInitConfig,
) -> dict[str, Any]:
    """Measure bind-pose silhouette + chroma agreement at the selected profile camera."""
    textured = any(material.get("texture") is not None for material in backend._gpu_materials)
    if not textured:
        raise ValueError(
            "profile mesh-sprite validation requires a painted Meshy GLB; "
            f"no base-color textures on {backend.src_glb}"
        )
    target_rgb, target_alpha = _load_target_rgb_tensor(
        target_frame_path,
        tuple(int(value) for value in config.resolution),
        device=backend.device,
    )
    chroma = _profile_bind_pose_chroma_quality(
        backend,
        target_rgb=target_rgb,
        target_alpha=target_alpha,
        predicted_alpha_threshold=float(config.predicted_alpha_threshold),
    )
    orientation_iou = float(orientation_iou)
    chroma_quality = float(chroma["chromaQuality"])
    alignment_sum = orientation_iou + chroma_quality
    return {
        "orientationIoU": orientation_iou,
        "chromaQuality": chroma_quality,
        "chromaError": float(chroma["chromaError"]),
        "alignmentSum": float(alignment_sum),
        "targetFrame": str(Path(target_frame_path).resolve()),
        "minOrientationIoU": float(config.mesh_sprite_min_orientation_iou),
        "minAlignmentSum": float(config.mesh_sprite_min_alignment_sum),
        "passed": bool(
            orientation_iou >= float(config.mesh_sprite_min_orientation_iou)
            and alignment_sum >= float(config.mesh_sprite_min_alignment_sum)
        ),
    }


def assert_profile_mesh_sprite_alignment(
    metrics: Mapping[str, Any],
    *,
    src_glb: str | Path,
    target_frame_dir: str | Path,
) -> None:
    """Record mesh-sprite mismatch diagnostics without blocking pose fit.

    The hard profile gate is abandoned (2026-08-23): orientation/chroma metrics
    remain useful for audits, but they must not quarantine GLBs or abort fits.
    """
    if bool(metrics.get("passed")):
        return
    message = (
        "profile mesh-sprite alignment soft-miss (gate abandoned; fit continues): "
        f"mesh={Path(src_glb).resolve()} "
        f"sprites={Path(target_frame_dir).resolve()} "
        f"orientationIoU={float(metrics.get('orientationIoU', 0.0)):.3f} "
        f"chromaQuality={float(metrics.get('chromaQuality', 0.0)):.3f} "
        f"alignmentSum={float(metrics.get('alignmentSum', 0.0)):.3f} "
        f"(legacy thresholds orientationIoU>={float(metrics.get('minOrientationIoU', PROFILE_MESH_MIN_ORIENTATION_IOU)):.2f} "
        f"and sum>={float(metrics.get('minAlignmentSum', PROFILE_MESH_MIN_ALIGNMENT_SUM)):.2f})"
    )
    if PROFILE_MESH_SPRITE_GATE_ENABLED:
        raise ProfileMeshSpriteMismatchError(
            message.replace(
                "soft-miss (gate abandoned; fit continues)",
                "failed",
                1,
            )
            + ". Replace or quarantine the GLB before running pose fit."
        )
    print(message, flush=True)


def profile_camera_source_mesh(camera_fit: str | Path) -> Path | None:
    """Return sourceMesh recorded beside a profile camera fit, if present."""
    init_path = Path(camera_fit).resolve().parent / "profile_camera_initialization.json"
    if not init_path.is_file():
        return None
    data = json.loads(init_path.read_text(encoding="utf-8"))
    raw = data.get("sourceMesh")
    if not raw:
        return None
    return Path(str(raw)).resolve()


def profile_camera_init_is_current(camera_fit: str | Path) -> tuple[bool, str]:
    """True when the sibling init report uses facing-floored chroma near-tie (schema >= 3).

    Pre-v2 cameras can lock gargoyle/pikeman onto a 180° silhouette flip.
    Pre-v3 cameras can pick a rear yaw when chroma wins a silhouette near-tie
    (goblin idle facing≈0.06 at yaw=-120).
    """
    init_path = Path(camera_fit).resolve().parent / "profile_camera_initialization.json"
    if not init_path.is_file():
        return False, f"missing init report beside {camera_fit}"
    data = json.loads(init_path.read_text(encoding="utf-8"))
    version = int(data.get("schemaVersion") or 0)
    if version < int(PROFILE_INIT_SCHEMA_VERSION):
        return (
            False,
            f"schemaVersion={version} < required {PROFILE_INIT_SCHEMA_VERSION}",
        )
    selection = data.get("selection")
    if not isinstance(selection, dict):
        return False, "missing selection diagnostics"
    if "selectionRule" not in selection:
        return False, "selection missing selectionRule"
    best = data.get("best")
    if isinstance(best, dict) and best.get("chromaQuality") is None:
        return False, "best.chromaQuality missing (pre-chroma init)"
    return True, f"schemaVersion={version} rule={selection.get('selectionRule')}"


def validate_profile_mesh_sprite_alignment(
    *,
    src_glb: str | Path,
    camera_fit: str | Path,
    target_frame_dir: str | Path,
    frame_index: int,
    config: ProfileCameraInitConfig | None = None,
) -> dict[str, Any]:
    """Re-check an existing profile camera against the current mesh + sprite lane."""
    import torch

    config = config or ProfileCameraInitConfig()
    config.validate()
    frame_path = Path(target_frame_dir).resolve() / f"{int(frame_index):02d}.png"
    if not frame_path.is_file():
        raise FileNotFoundError(f"profile mesh-sprite validation frame is missing: {frame_path}")
    backend_config = GpuCascadeConfig(
        device="cuda",
        resolution=tuple(int(value) for value in config.resolution),
        alpha_threshold=int(config.alpha_threshold),
        max_triangles_per_primitive=2048,
        samples_per_triangle=3,
        root_search_enabled=False,
        root_hypotheses=1,
        root_iterations=0,
        articulated_iterations=0,
        fine_iterations=0,
        optimize_root_translation=False,
        optimize_root_rotation=False,
        root_rotation_defer_camera_up=False,
        optimize_bones=False,
        exact_raster_enabled=True,
        collision_enabled=False,
        collision_weight=0.0,
        return_masks=True,
    )
    backend = GpuCascadeExperiment(
        src_glb=src_glb,
        camera_fit=camera_fit,
        target_frame_dir=target_frame_dir,
        frame_indices=(int(frame_index),),
        config=backend_config,
    )
    try:
        orientation_target = backend.target_masks[0].detach().cpu().numpy() > 0.5
        orientation_bounds = _mask_bounds(orientation_target)
        zero_bones = torch.zeros(
            (1, len(backend.asset.nodes), 3), dtype=torch.float32, device=backend.device
        )
        zero_root = torch.zeros((1, 3), dtype=torch.float32, device=backend.device)
        with torch.no_grad():
            alpha, _ = backend._exact_triangle_raster(
                zero_bones,
                zero_root,
                zero_root,
                bone_mask=backend.active_node_mask,
            )
        candidate_mask = alpha[0].detach().cpu().numpy() > float(config.predicted_alpha_threshold)
        orientation_iou, _ = _score_mask(
            orientation_target,
            candidate_mask,
            target_bounds=orientation_bounds,
        )
        metrics = evaluate_profile_mesh_sprite_alignment(
            backend,
            orientation_target=orientation_target,
            target_frame_path=frame_path,
            orientation_iou=float(orientation_iou),
            config=config,
        )
        assert_profile_mesh_sprite_alignment(
            metrics,
            src_glb=src_glb,
            target_frame_dir=target_frame_dir,
        )
        return metrics
    finally:
        backend.release_cuda()


def initialize_profile_camera(
    *,
    src_glb: str | Path,
    seed_camera_fit: str | Path,
    target_frame_dir: str | Path,
    fit_target_frame_dir: str | Path | None = None,
    normalization_frame_dir: str | Path | None = None,
    frame_index: int,
    output_dir: str | Path,
    config: ProfileCameraInitConfig | None = None,
    progress: bool = True,
) -> ProfileCameraInitialization:
    """Find and serialize a profile-oriented camera before bone optimization."""
    import torch

    config = config or ProfileCameraInitConfig()
    config.validate()
    started = time.perf_counter()
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    seed_path = Path(seed_camera_fit).resolve()
    if not seed_path.is_file():
        raise FileNotFoundError(f"profile initialization seed camera is missing: {seed_path}")

    backend_config = GpuCascadeConfig(
        device="cuda",
        resolution=tuple(int(value) for value in config.resolution),
        alpha_threshold=int(config.alpha_threshold),
        max_triangles_per_primitive=2048,
        samples_per_triangle=3,
        root_search_enabled=False,
        root_hypotheses=1,
        root_iterations=0,
        articulated_iterations=0,
        fine_iterations=0,
        optimize_root_translation=False,
        optimize_root_rotation=False,
        root_rotation_defer_camera_up=False,
        optimize_bones=False,
        exact_raster_enabled=True,
        score_centroid_weight=0.0,
        score_occupancy_weight=0.0,
        sdf_weight=0.0,
        depth_weight=0.0,
        silhouette_weight=1.0,
        chroma_weight=0.0,
        collision_enabled=False,
        collision_weight=0.0,
        return_masks=True,
    )
    backend = GpuCascadeExperiment(
        src_glb=src_glb,
        camera_fit=seed_path,
        target_frame_dir=target_frame_dir,
        frame_indices=(int(frame_index),),
        config=backend_config,
    )
    try:
        # ``target_frame_dir`` is the orientation authority.  In the normal path
        # this is an authentic idle frame matching the imported bind pose.  The
        # optional fit target is deliberately separate: movement frames may have a
        # larger stride or weapon extension and must not be allowed to choose the
        # static camera yaw.
        orientation_target = backend.target_masks[0].detach().cpu().numpy() > 0.5
        if fit_target_frame_dir is not None and normalization_frame_dir is not None:
            raise ValueError(
                "profile initialization accepts either fit_target_frame_dir or "
                "normalization_frame_dir, not both"
            )
        target = orientation_target
        target_normalization = None
        if normalization_frame_dir is not None:
            reference_path = Path(normalization_frame_dir).resolve() / f"{int(frame_index):02d}.png"
            if not reference_path.is_file():
                raise FileNotFoundError(
                    f"profile normalization frame is missing: {reference_path}"
                )
            reference = _load_alpha_mask(
                reference_path,
                tuple(int(value) for value in config.resolution),
                int(config.alpha_threshold),
            )
            orientation_target, target_normalization = _normalize_mask_to_reference(
                orientation_target,
                reference,
            )
            target = orientation_target
        elif fit_target_frame_dir is not None:
            fit_path = Path(fit_target_frame_dir).resolve() / f"{int(frame_index):02d}.png"
            if not fit_path.is_file():
                raise FileNotFoundError(f"profile fit target frame is missing: {fit_path}")
            target = _load_alpha_mask(
                fit_path,
                tuple(int(value) for value in config.resolution),
                int(config.alpha_threshold),
            )
        # Search against the idle/bind silhouette.  If a separate fit target was
        # supplied, it is used only after yaw/roll are selected to set the output
        # scale and framing for the movement canvas.
        orientation_bounds = _mask_bounds(orientation_target)
        target_bounds = _mask_bounds(target)
        vertices = _bind_vertices(backend).detach().cpu().numpy()
        seed_right = backend.camera_right.detach().cpu().numpy()
        seed_down = backend.camera_down.detach().cpu().numpy()
        seed_forward = backend.camera_forward.detach().cpu().numpy()
        seed_px = backend.px_per_world.detach().cpu().numpy()
        world_up_axis = _unit(np.asarray(config.world_up_axis, dtype=np.float32))
        character_forward = _character_ground_forward(backend.asset, world_up_axis)
        zero_bones = torch.zeros(
            (1, len(backend.asset.nodes), 3), dtype=torch.float32, device=backend.device
        )
        zero_root = torch.zeros((1, 3), dtype=torch.float32, device=backend.device)
        chroma_weight = float(config.chroma_weight)
        score_chroma = (
            chroma_weight > 0.0 and str(config.camera_basis_mode) != "geometry_broad_thin"
        )
        target_rgb = None
        target_alpha_rgb = None
        if score_chroma:
            textured = any(
                material.get("texture") is not None for material in backend._gpu_materials
            )
            if not textured:
                raise ValueError(
                    "profile initialization chroma_weight requires a painted Meshy GLB; "
                    f"no base-color textures on {Path(src_glb).resolve()}"
                )
            orientation_frame_path = (
                Path(target_frame_dir).resolve() / f"{int(frame_index):02d}.png"
            )
            if not orientation_frame_path.is_file():
                raise FileNotFoundError(
                    f"profile initialization chroma frame is missing: {orientation_frame_path}"
                )
            target_rgb, target_alpha_rgb = _load_target_rgb_tensor(
                orientation_frame_path,
                tuple(int(value) for value in config.resolution),
                device=backend.device,
            )
        candidates: list[dict[str, Any]] = []
        yaw_values = _inclusive_grid(config.yaw_min_deg, config.yaw_max_deg, config.yaw_step_deg)
        roll_values = _inclusive_grid(-config.roll_range_deg, config.roll_range_deg, config.roll_step_deg)

        def _candidate_chroma_quality() -> dict[str, float]:
            if not score_chroma:
                return {"chromaQuality": 0.0, "chromaError": 0.0}
            assert target_rgb is not None and target_alpha_rgb is not None
            return _profile_bind_pose_chroma_quality(
                backend,
                target_rgb=target_rgb,
                target_alpha=target_alpha_rgb,
                predicted_alpha_threshold=float(config.predicted_alpha_threshold),
            )

        def _render_candidate_mask(
            right: np.ndarray,
            down: np.ndarray,
            forward: np.ndarray,
            px_per_world: np.ndarray,
            offset: np.ndarray,
            *,
            recenter_bounds: dict[str, float] | None = None,
        ) -> tuple[np.ndarray, np.ndarray]:
            """Render and recenter one exact bind-pose candidate."""
            bounds = recenter_bounds or orientation_bounds
            _set_backend_camera(
                backend,
                right=right,
                down=down,
                forward=forward,
                offset=offset,
                px_per_world=px_per_world,
            )
            with torch.no_grad():
                alpha, _ = backend._exact_triangle_raster(
                    zero_bones,
                    zero_root,
                    zero_root,
                    bone_mask=backend.active_node_mask,
                )
            candidate_mask = alpha[0].detach().cpu().numpy() > float(config.predicted_alpha_threshold)
            # Vertex bounds are a useful first estimate, but skinning and occlusion
            # make their centroid differ from the filled silhouette. Recenter once
            # from the actual raster mask before scoring.
            candidate_bounds = _bbox_from_mask(candidate_mask)
            if candidate_bounds is not None:
                offset = offset + np.asarray(
                    (
                        bounds["centerX"] - candidate_bounds["centerX"],
                        # The nvdiffrast output row origin is opposite the
                        # camera-down projection coordinate used by the GPU
                        # contract, so a positive camera offset moves the image
                        # upward in the saved array.
                        -(bounds["centerY"] - candidate_bounds["centerY"]),
                    ),
                    dtype=np.float32,
                )
                _set_backend_camera(
                    backend,
                    right=right,
                    down=down,
                    forward=forward,
                    offset=offset,
                    px_per_world=px_per_world,
                )
                with torch.no_grad():
                    alpha, _ = backend._exact_triangle_raster(
                        zero_bones,
                        zero_root,
                        zero_root,
                        bone_mask=backend.active_node_mask,
                    )
                candidate_mask = alpha[0].detach().cpu().numpy() > float(config.predicted_alpha_threshold)
            return candidate_mask, offset

        # The seed camera is a fair baseline only after it is fitted to the
        # initialization target. Its original framing usually came from a
        # different animation and otherwise makes the comparison meaningless.
        seed_px_fitted, seed_offset = _fit_scale_and_offset(
            vertices,
            orientation_bounds,
            seed_right,
            seed_down,
            seed_px,
            float(config.fit_margin),
        )
        seed_mask, seed_offset = _render_candidate_mask(
            seed_right,
            seed_down,
            seed_forward,
            seed_px_fitted,
            seed_offset,
        )
        seed_score, seed_diagnostics = _score_mask(
            orientation_target,
            seed_mask,
            target_bounds=orientation_bounds,
        )
        seed_geometry_score = _geometry_profile_score(
            vertices,
            right=seed_right,
            down=seed_down,
            forward=seed_forward,
            seed_forward=seed_forward,
        )
        seed_chroma = _candidate_chroma_quality()
        seed_selection_score, seed_facing = _silhouette_selection_score(
            silhouette_score=seed_score,
            geometry_score=seed_geometry_score,
            character_forward=character_forward,
            right=seed_right,
            camera_basis_mode=str(config.camera_basis_mode),
            facing_weight=float(config.facing_weight),
            chroma_quality=float(seed_chroma["chromaQuality"]),
            chroma_weight=chroma_weight if score_chroma else 0.0,
        )
        candidates.append(
            {
                "yawDeg": 0.0,
                "rollDeg": 0.0,
                "source": "seed_camera",
                "score": float(seed_selection_score),
                "silhouetteScore": float(seed_score),
                "geometryScore": float(seed_geometry_score),
                **seed_diagnostics,
                "pxPerWorld": [float(value) for value in seed_px_fitted],
                "screenOffsetPx": [float(value) for value in seed_offset],
                "right": [float(value) for value in seed_right],
                "down": [float(value) for value in seed_down],
                "forward": [float(value) for value in seed_forward],
                "screenUpWorldAlignment": float(np.dot(-seed_down, world_up_axis)),
                "facingScore": float(seed_facing),
                "chromaQuality": float(seed_chroma["chromaQuality"]),
                "chromaError": float(seed_chroma.get("chromaError", 0.0)),
                "chromaWeight": float(chroma_weight if score_chroma else 0.0),
                "mask": seed_mask,
            }
        )
        for yaw_deg in yaw_values:
            for roll_deg in roll_values:
                right, down, forward = _camera_candidate_basis(
                    seed_right,
                    seed_down,
                    seed_forward,
                    yaw_deg=float(yaw_deg),
                    roll_deg=float(roll_deg),
                    mode=str(config.camera_basis_mode),
                    world_up_axis=world_up_axis,
                )
                px_per_world, offset = _fit_scale_and_offset(
                    vertices,
                    orientation_bounds,
                    right,
                    down,
                    seed_px,
                    float(config.fit_margin),
                )
                candidate_mask, offset = _render_candidate_mask(
                    right,
                    down,
                    forward,
                    px_per_world,
                    offset,
                )
                silhouette_score, diagnostics = _score_mask(
                    orientation_target,
                    candidate_mask,
                    target_bounds=orientation_bounds,
                )
                geometry_score = _geometry_profile_score(
                    vertices,
                    right=right,
                    down=down,
                    forward=forward,
                    seed_forward=seed_forward,
                )
                chroma = _candidate_chroma_quality()
                score, facing = _silhouette_selection_score(
                    silhouette_score=silhouette_score,
                    geometry_score=geometry_score,
                    character_forward=character_forward,
                    right=right,
                    camera_basis_mode=str(config.camera_basis_mode),
                    facing_weight=float(config.facing_weight),
                    chroma_quality=float(chroma["chromaQuality"]),
                    chroma_weight=chroma_weight if score_chroma else 0.0,
                )
                candidates.append(
                    {
                        "yawDeg": float(yaw_deg),
                        "rollDeg": float(roll_deg),
                        "source": "profile_search",
                        "score": float(score),
                        "silhouetteScore": float(silhouette_score),
                        "geometryScore": float(geometry_score),
                        **diagnostics,
                        "pxPerWorld": [float(value) for value in px_per_world],
                        "screenOffsetPx": [float(value) for value in offset],
                        "right": [float(value) for value in right],
                        "down": [float(value) for value in down],
                        "forward": [float(value) for value in forward],
                        "screenUpWorldAlignment": float(np.dot(-down, world_up_axis)),
                        "facingScore": float(facing),
                        "chromaQuality": float(chroma["chromaQuality"]),
                        "chromaError": float(chroma.get("chromaError", 0.0)),
                        "chromaWeight": float(chroma_weight if score_chroma else 0.0),
                        "mask": candidate_mask,
                    }
                )
        eligible = select_upright_profile_candidates(
            candidates,
            camera_basis_mode=str(config.camera_basis_mode),
            roll_range_deg=float(config.roll_range_deg),
        )
        best, selection_diagnostics = select_profile_orientation_candidate(
            eligible,
            rank_metric=str(config.rank_metric),
            silhouette_near_tie=float(config.silhouette_near_tie),
            chroma_enabled=bool(score_chroma),
            min_profile_facing=float(config.min_profile_facing),
        )
        # Keep the chosen orientation at the front of ranked lists / previews.
        eligible = [best] + [item for item in eligible if item is not best]
        best["characterForward"] = [float(value) for value in character_forward]
        best["selection"] = dict(selection_diagnostics)
        # Keep the orientation evidence intact for the diagnostic sheet before
        # replacing the selected candidate's scale/framing with the movement fit.
        preview_candidates = [dict(candidate) for candidate in eligible[: int(config.top_k)]]
        best["orientationScore"] = float(best["score"])
        best["orientationIoU"] = float(best["iou"])
        best["orientationCentroidErrorPx"] = float(best["centroidErrorPx"])
        best["orientationBboxError"] = float(best["bboxError"])
        best_px, best_offset = _fit_scale_and_offset(
            vertices,
            target_bounds,
            np.asarray(best["right"], dtype=np.float32),
            np.asarray(best["down"], dtype=np.float32),
            seed_px,
            float(config.fit_margin),
        )
        best_mask, best_offset = _render_candidate_mask(
            np.asarray(best["right"], dtype=np.float32),
            np.asarray(best["down"], dtype=np.float32),
            np.asarray(best["forward"], dtype=np.float32),
            best_px,
            best_offset,
            recenter_bounds=target_bounds,
        )
        final_score, final_diagnostics = _score_mask(
            target,
            best_mask,
            target_bounds=target_bounds,
        )
        best.update(
            {
                "score": float(best["geometryScore"] if str(config.camera_basis_mode) == "geometry_broad_thin" else final_score),
                "silhouetteScore": float(final_score),
                "iou": float(final_diagnostics["iou"]),
                "centroidErrorPx": float(final_diagnostics["centroidErrorPx"]),
                "bboxError": float(final_diagnostics["bboxError"]),
                "pxPerWorld": [float(value) for value in best_px],
                "screenOffsetPx": [float(value) for value in best_offset],
                "mask": best_mask,
            }
        )
        top = eligible[: int(config.top_k)]
        camera_fit_path = output / "profile_camera_fit.json"
        _write_camera_fit(
            seed_path,
            camera_fit_path,
            right=np.asarray(best["right"], dtype=np.float32),
            down=np.asarray(best["down"], dtype=np.float32),
            px_per_world=np.asarray(best["pxPerWorld"], dtype=np.float32),
            offset=np.asarray(best["screenOffsetPx"], dtype=np.float32),
            resolution=tuple(int(value) for value in config.resolution),
            best=best,
            frame_index=int(frame_index),
            camera_basis_mode=str(config.camera_basis_mode),
            world_up_axis=world_up_axis,
        )
        preview_path = output / "profile_camera_initialization.png"
        _write_initialization_preview(
            preview_path,
            target=orientation_target,
            candidates=preview_candidates,
        )
        mesh_sprite_alignment = None
        if bool(config.mesh_sprite_validate) and str(config.camera_basis_mode) != "geometry_broad_thin":
            orientation_frame_path = Path(target_frame_dir).resolve() / f"{int(frame_index):02d}.png"
            _set_backend_camera(
                backend,
                right=np.asarray(best["right"], dtype=np.float32),
                down=np.asarray(best["down"], dtype=np.float32),
                forward=np.asarray(best["forward"], dtype=np.float32),
                offset=np.asarray(best["screenOffsetPx"], dtype=np.float32),
                px_per_world=np.asarray(best["pxPerWorld"], dtype=np.float32),
            )
            mesh_sprite_alignment = evaluate_profile_mesh_sprite_alignment(
                backend,
                orientation_target=orientation_target,
                target_frame_path=orientation_frame_path,
                orientation_iou=float(best.get("orientationIoU", best["iou"])),
                config=config,
            )
            assert_profile_mesh_sprite_alignment(
                mesh_sprite_alignment,
                src_glb=src_glb,
                target_frame_dir=target_frame_dir,
            )
            best["meshSpriteAlignment"] = dict(mesh_sprite_alignment)
        elapsed = time.perf_counter() - started
        report = {
            "schemaVersion": int(PROFILE_INIT_SCHEMA_VERSION),
            "renderer": "nvdiffrast RasterizeCudaContext",
            "sourceMesh": str(Path(src_glb).resolve()),
            "seedCameraFit": str(seed_path),
            "targetFrameDir": str(Path(target_frame_dir).resolve()),
            "fitTargetFrameDir": (
                str(Path(fit_target_frame_dir).resolve())
                if fit_target_frame_dir is not None
                else None
            ),
            "frameIndex": int(frame_index),
            "config": asdict(config),
            "selection": dict(selection_diagnostics),
            "targetBounds": target_bounds,
            "orientationTargetBounds": _mask_bounds(orientation_target),
            "targetNormalization": target_normalization,
            "best": {key: value for key, value in best.items() if key != "mask"},
            "candidates": [
                {key: value for key, value in candidate.items() if key != "mask"}
                for candidate in top
            ],
            "cameraFitPath": str(camera_fit_path),
            "previewPath": str(preview_path),
            "elapsedSeconds": float(elapsed),
            "meshSpriteAlignment": mesh_sprite_alignment,
        }
        report_path = output / "profile_camera_initialization.json"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if progress:
            alignment_note = ""
            if mesh_sprite_alignment is not None:
                alignment_note = (
                    f" chroma={float(mesh_sprite_alignment['chromaQuality']):.3f} "
                    f"alignSum={float(mesh_sprite_alignment['alignmentSum']):.3f}"
                )
            print(
                f"GPU profile initialization f{int(frame_index):02d}: "
                f"yaw={best['yawDeg']:.1f} roll={best['rollDeg']:.1f} "
                f"IoU={best['iou']:.4f} score={best['score']:.4f} "
                f"facing={float(best.get('facingScore', 0.0)):.3f} "
                f"chroma={float(best.get('chromaQuality', 0.0)):.3f} "
                f"rule={selection_diagnostics.get('selectionRule', '?')} "
                f"near={int(selection_diagnostics.get('nearTieCount', 0))} "
                f"basis={config.camera_basis_mode} upDotY={best['screenUpWorldAlignment']:.3f} "
                f"candidates={len(candidates)} elapsed={elapsed:.1f}s{alignment_note}",
                flush=True,
            )
        serializable_top = tuple(
            {key: value for key, value in candidate.items() if key != "mask"}
            for candidate in top
        )
        return ProfileCameraInitialization(
            camera_fit_path=camera_fit_path,
            report_path=report_path,
            preview_path=preview_path,
            frame_index=int(frame_index),
            elapsed_seconds=float(elapsed),
            best={key: value for key, value in best.items() if key != "mask"},
            candidates=serializable_top,
        )
    finally:
        backend.release_cuda()
