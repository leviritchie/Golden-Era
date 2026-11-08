"""Phase-B anatomy veto for articulated probe keep.

DINO remains keep authority. Strain, collision, and optional prop screen error
act as hard reject and soft tie-break layers — they are never mixed into the
DINO/geometry keep score.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

# Prop stick names that are not in bone_roles["joints"].
_PROP_JOINT_BONE_OVERRIDES: dict[str, str] = {
    "ShieldCenter": "LeftHand",
}


@dataclass(frozen=True)
class AnatomyPropTargets:
    """Per clip-local frame, joint screen targets in raster pixel space."""

    joint_node_indices: tuple[tuple[str, int], ...]
    frame_indices: tuple[int, ...]
    target_xy: np.ndarray  # (F, J, 2)


def load_bone_roles(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"bone roles must be a JSON object: {path}")
    return payload


def resolve_prop_joint_node_indices(
    node_names: Sequence[str],
    *,
    bone_roles: Mapping[str, Any],
    joint_names: Sequence[str],
) -> dict[str, int]:
    joints = dict(bone_roles.get("joints") or {})
    name_to_index = {str(name): int(index) for index, name in enumerate(node_names)}
    resolved: dict[str, int] = {}
    for joint in joint_names:
        bone = str(joints.get(str(joint)) or _PROP_JOINT_BONE_OVERRIDES.get(str(joint), ""))
        if not bone:
            raise ValueError(
                f"prop joint {joint!r} has no bone mapping in bone roles "
                f"(tried joints and overrides)"
            )
        if bone not in name_to_index:
            raise ValueError(f"bone {bone!r} for prop joint {joint!r} is not on the skeleton")
        resolved[str(joint)] = int(name_to_index[bone])
    return resolved


def load_prop_targets_for_veto(
    coords_path: Path,
    *,
    bone_roles_path: Path,
    node_names: Sequence[str],
    clip_frame_indices: Sequence[int],
    source_sprite_size: tuple[int, int],
    raster_size: tuple[int, int],
) -> AnatomyPropTargets:
    payload = json.loads(Path(coords_path).read_text(encoding="utf-8"))
    joint_names = tuple(str(name) for name in (payload.get("joints") or ()))
    if not joint_names:
        raise ValueError(f"props_coords joints list is empty: {coords_path}")
    bone_roles = load_bone_roles(bone_roles_path)
    joint_nodes = resolve_prop_joint_node_indices(
        node_names,
        bone_roles=bone_roles,
        joint_names=joint_names,
    )
    sprite_w, sprite_h = (int(source_sprite_size[0]), int(source_sprite_size[1]))
    raster_w, raster_h = (int(raster_size[0]), int(raster_size[1]))
    if sprite_w < 1 or sprite_h < 1:
        raise ValueError(f"invalid source_sprite_size: {source_sprite_size}")
    if raster_w < 1 or raster_h < 1:
        raise ValueError(f"invalid raster_size: {raster_size}")
    scale_x = float(raster_w) / float(sprite_w)
    scale_y = float(raster_h) / float(sprite_h)

    clip_lookup = {int(frame): int(position) for position, frame in enumerate(clip_frame_indices)}
    authored = {
        int(entry["frameIndex"]): {
            str(joint): (
                float(xy[0]) * scale_x,
                float(xy[1]) * scale_y,
            )
            for joint, xy in (entry.get("xy") or {}).items()
        }
        for entry in (payload.get("frames") or ())
        if "frameIndex" in entry
    }
    if not authored:
        raise ValueError(f"props_coords has no frames: {coords_path}")

    frame_positions: list[int] = []
    target_rows: list[list[tuple[float, float]]] = []
    for frame_index, xy_map in sorted(authored.items()):
        position = clip_lookup.get(int(frame_index))
        if position is None:
            continue
        missing = [name for name in joint_names if name not in xy_map]
        if missing:
            raise ValueError(
                f"props_coords frame {frame_index} missing joints {missing} in {coords_path}"
            )
        frame_positions.append(int(position))
        target_rows.append([xy_map[name] for name in joint_names])

    if not frame_positions:
        raise ValueError(
            "props_coords frames do not overlap clip frame_indices: "
            f"authored={sorted(authored)} clip={list(clip_frame_indices)}"
        )

    target_xy = np.asarray(target_rows, dtype=np.float64)
    joint_pairs = tuple((name, int(joint_nodes[name])) for name in joint_names)
    return AnatomyPropTargets(
        joint_node_indices=joint_pairs,
        frame_indices=tuple(frame_positions),
        target_xy=target_xy,
    )


def prop_px_error_batch(
    backend: Any,
    bone_vectors,
    root_translation,
    root_rotation,
    *,
    prop_targets: AnatomyPropTargets,
    site_bindings: Sequence[Any] | None = None,
) -> Any:
    """Mean L2 prop screen error per clip-local frame. Unauthored frames are 0."""
    import torch

    frame_count = int(bone_vectors.shape[0])
    device = bone_vectors.device
    out = torch.zeros((frame_count,), dtype=torch.float32, device=device)
    if not prop_targets.joint_node_indices:
        return out

    if site_bindings is not None:
        from gpu_prop_joint_sites import screen_prop_sites_xy

        predicted = screen_prop_sites_xy(
            backend,
            bone_vectors,
            root_translation,
            root_rotation,
            bindings=site_bindings,
        )
    else:
        screen = backend._screen_joint_xy(bone_vectors, root_translation, root_rotation)
        node_indices = [int(index) for _, index in prop_targets.joint_node_indices]
        predicted = screen.index_select(1, torch.as_tensor(node_indices, device=device))
    target = torch.as_tensor(
        prop_targets.target_xy,
        dtype=torch.float32,
        device=device,
    )
    for row, frame_position in enumerate(prop_targets.frame_indices):
        delta = predicted[int(frame_position)] - target[int(row)]
        out[int(frame_position)] = torch.linalg.vector_norm(delta, dim=-1).mean()
    return out


def anatomy_metrics_batch(
    backend: Any,
    bone_vectors,
    *,
    strain_table: Mapping[str, Any] | None,
    collision_table: Mapping[str, Any] | None,
    strain_tolerance: float,
) -> tuple[Any, Any]:
    """Return per-frame strain RMS and collision error tensors."""
    from gpu_mesh_collision import collision_error_from_table
    from gpu_mesh_strain import strain_error_from_table

    strain = strain_error_from_table(
        backend,
        strain_table,
        bone_vectors,
        tolerance=float(strain_tolerance),
    )
    collision = collision_error_from_table(backend, collision_table, bone_vectors)
    return strain, collision


def combined_anatomy_delta(
    *,
    strain: Any,
    collision: Any,
    prop_px: Any,
    baseline_strain: Any,
    baseline_collision: Any,
    baseline_prop_px: Any,
    strain_enabled: bool,
    collision_enabled: bool,
    prop_enabled: bool,
) -> tuple[Any, Any, Any, Any]:
    """Per-frame deltas and a scalar combined penalty for soft tie-break."""
    import torch

    zeros = torch.zeros_like(strain)
    strain_delta = (strain - baseline_strain) if strain_enabled else zeros
    collision_delta = (collision - baseline_collision) if collision_enabled else zeros
    prop_delta = (prop_px - baseline_prop_px) if prop_enabled else zeros
    combined = strain_delta + collision_delta + (prop_delta / 64.0)
    return strain_delta, collision_delta, prop_delta, combined


def hard_veto_mask(
    strain_delta: Any,
    collision_delta: Any,
    prop_delta: Any,
    *,
    strain_slack: float,
    collision_slack: float,
    prop_slack_px: float,
    hard_strain_margin: float,
    hard_collision_margin: float,
    hard_prop_margin_px: float,
    strain_enabled: bool,
    collision_enabled: bool,
    prop_enabled: bool,
) -> Any:
    """True where the candidate is hard-vetoed on any enabled anatomy channel."""
    import torch

    legal = torch.ones_like(strain_delta, dtype=torch.bool)
    if strain_enabled:
        legal = legal & (
            strain_delta <= float(strain_slack) + float(hard_strain_margin) + 1e-9
        )
    if collision_enabled:
        legal = legal & (
            collision_delta <= float(collision_slack) + float(hard_collision_margin) + 1e-9
        )
    if prop_enabled:
        legal = legal & (
            prop_delta <= float(prop_slack_px) + float(hard_prop_margin_px) + 1e-9
        )
    return ~legal


def apply_anatomy_veto_to_keep_family(
    keep_choices: Sequence[Any],
    *,
    anatomy_deltas: Sequence[tuple[Any, Any, Any, Any]],
    dino_tie_band: float,
    soft_weight: float,
    strain_slack: float,
    collision_slack: float,
    prop_slack_px: float,
    hard_strain_margin: float,
    hard_collision_margin: float,
    hard_prop_margin_px: float,
    strain_enabled: bool,
    collision_enabled: bool,
    prop_enabled: bool,
) -> tuple[list[Any], dict[str, int]]:
    """Adjust probe keep tensors without changing DINO authority off the tie band."""
    import torch

    if len(keep_choices) < 1:
        raise ValueError("keep_choices must be non-empty")
    if len(anatomy_deltas) != len(keep_choices):
        raise ValueError("anatomy_deltas must align with keep_choices")

    hard_vetoes = 0
    soft_adjusted = 0
    adjusted: list[Any] = []
    stacked = torch.stack([tensor.detach().clone() for tensor in keep_choices], dim=0)
    dino_reference = stacked.clone()
    for index, keep in enumerate(keep_choices):
        out = keep.detach().clone()
        strain_delta, collision_delta, prop_delta, combined = anatomy_deltas[index]
        vetoed = hard_veto_mask(
            strain_delta,
            collision_delta,
            prop_delta,
            strain_slack=float(strain_slack),
            collision_slack=float(collision_slack),
            prop_slack_px=float(prop_slack_px),
            hard_strain_margin=float(hard_strain_margin),
            hard_collision_margin=float(hard_collision_margin),
            hard_prop_margin_px=float(hard_prop_margin_px),
            strain_enabled=bool(strain_enabled),
            collision_enabled=bool(collision_enabled),
            prop_enabled=bool(prop_enabled),
        )
        if bool(vetoed.any().item()):
            hard_vetoes += 1
            out = torch.where(vetoed, torch.full_like(out, -1.0e6), out)
        adjusted.append(out)

    max_dino = dino_reference.max(dim=0).values
    tie_band = float(dino_tie_band)
    soft_w = float(soft_weight)
    if tie_band > 0.0 and soft_w > 0.0:
        for index in range(len(adjusted)):
            if index == 0:
                continue
            near_tie = dino_reference[index] >= (max_dino - tie_band)
            if not bool(near_tie.any().item()):
                continue
            _, _, _, combined = anatomy_deltas[index]
            penalty = combined * soft_w
            adjusted[index] = torch.where(
                near_tie,
                adjusted[index] - penalty,
                adjusted[index],
            )
            soft_adjusted += 1

    return adjusted, {
        "hardVetoes": int(hard_vetoes),
        "softAdjusted": int(soft_adjusted),
    }


def sprite_size_from_prop_coords(coords_path: Path) -> tuple[int, int]:
    """Read spriteSize from props_coords.json or author_bundle.json beside it."""
    coords_path = Path(coords_path)
    if coords_path.is_file():
        payload = json.loads(coords_path.read_text(encoding="utf-8"))
        size = payload.get("spriteSize") or {}
        width = int(size.get("width") or 0)
        height = int(size.get("height") or 0)
        if width > 0 and height > 0:
            return width, height
    bundle = coords_path.parent / "author_bundle.json"
    if bundle.is_file():
        payload = json.loads(bundle.read_text(encoding="utf-8"))
        size = payload.get("spriteSize") or {}
        width = int(size.get("width") or 0)
        height = int(size.get("height") or 0)
        if width > 0 and height > 0:
            return width, height
    return 0, 0


def validate_anatomy_veto_config(config: Any) -> None:
    if not bool(getattr(config, "anatomy_veto_enabled", False)):
        return
    enabled = [
        bool(getattr(config, "anatomy_veto_strain_enabled", False)),
        bool(getattr(config, "anatomy_veto_collision_enabled", False)),
        bool(getattr(config, "anatomy_veto_prop_enabled", False)),
    ]
    if not any(enabled):
        raise ValueError(
            "anatomy_veto_enabled requires at least one of strain, collision, or prop"
        )
    if bool(getattr(config, "anatomy_veto_prop_enabled", False)):
        if not str(getattr(config, "anatomy_veto_prop_coords_path", "") or "").strip():
            raise ValueError("anatomy_veto_prop_enabled requires anatomy_veto_prop_coords_path")
        if not str(getattr(config, "anatomy_veto_bone_roles_path", "") or "").strip():
            raise ValueError("anatomy_veto_prop_enabled requires anatomy_veto_bone_roles_path")
    for name in (
        "anatomy_veto_strain_slack",
        "anatomy_veto_collision_slack",
        "anatomy_veto_prop_slack_px",
        "anatomy_veto_hard_strain_margin",
        "anatomy_veto_hard_collision_margin",
        "anatomy_veto_hard_prop_margin_px",
        "anatomy_veto_dino_tie_band",
        "anatomy_veto_soft_weight",
    ):
        value = float(getattr(config, name))
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(f"{name} must be finite and non-negative")
