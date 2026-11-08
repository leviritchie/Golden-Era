"""Shared helpers for post-solve literature polish passes."""
from __future__ import annotations

import copy
import json
from dataclasses import fields
from pathlib import Path
from typing import Any, Mapping

import torch

from cascade_clip_pose_tweak import (
    clip_frame_indices,
    load_clip_result,
    raster_tweak_preview,
    target_frame_dir_from_clip,
)
from gpu_cascade_delivery import require_pose_units_degrees
from roc_gpu_cascade_experiment import GpuCascadeConfig, GpuCascadeExperiment, persist_gpu_clip_result
from roc_stacked_solve_common import CLIP, ROOT, stacked_unit_resolve


LANE_NAME = "literature_walk_v1"
FORBIDDEN_WRITE_PARTS = frozenset({"meshy_downloads", "fused_push_v24_pipeline"})


def assert_write_path(path: Path) -> Path:
    resolved = path.resolve()
    allowed = (ROOT / "artifacts" / "pose_picker_runs").resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise RuntimeError(f"writes must stay under {allowed}; got {resolved}") from exc
    if any(part in FORBIDDEN_WRITE_PARTS for part in resolved.parts):
        raise RuntimeError(f"must not write live payload paths: {resolved}")
    return resolved


def config_from_saved(saved: Mapping[str, Any], *, overrides: Mapping[str, Any] | None = None) -> GpuCascadeConfig:
    def _tupleize(value: Any) -> Any:
        if isinstance(value, list):
            return tuple(_tupleize(item) for item in value)
        return value

    allowed = {item.name for item in fields(GpuCascadeConfig)}
    kwargs: dict[str, Any] = {}
    for name, value in saved.items():
        if name in allowed:
            kwargs[name] = _tupleize(value)
    for name, value in (overrides or {}).items():
        if name in allowed:
            kwargs[name] = value
    return GpuCascadeConfig(**kwargs)


def load_polish_experiment(
    *,
    payload: Mapping[str, Any],
    mesh: Path,
) -> tuple[GpuCascadeExperiment, torch.Tensor, torch.Tensor, torch.Tensor]:
    config = config_from_saved(payload["config"])
    frames = clip_frame_indices(payload)
    experiment = GpuCascadeExperiment(
        src_glb=mesh.resolve(),
        camera_fit=Path(str(payload["cameraFitPath"])).resolve(),
        target_frame_dir=target_frame_dir_from_clip(payload),
        frame_indices=frames,
        config=config,
    )
    poses = {int(key): value for key, value in payload["poses"].items()}
    bones, root_t, root_r = experiment._initial_pose_tensors(poses)
    return experiment, bones, root_t, root_r


def rescore_tensors(
    experiment: GpuCascadeExperiment,
    bone_vectors: torch.Tensor,
    root_translation: torch.Tensor,
    root_rotation: torch.Tensor,
) -> dict[str, Any]:
    bounded = experiment._bounded_bone_vectors(bone_vectors)
    with torch.no_grad():
        packed = experiment.evaluate(
            bounded,
            root_translation,
            root_rotation,
            bone_mask=experiment.active_node_mask,
        )
    clip_mean = experiment._clip_objective_mean(bounded, root_translation, root_rotation, packed)
    per_frame = [float(value) for value in packed["score"].detach().cpu().tolist()]
    return {
        "clipObjective": float(clip_mean),
        "meanScore": float(packed["score"].mean().detach().item()),
        "perFrameScores": per_frame,
    }


def poses_from_tensors(
    experiment: GpuCascadeExperiment,
    bone_vectors: torch.Tensor,
    root_translation: torch.Tensor,
    root_rotation: torch.Tensor,
) -> dict[int, dict[str, Any]]:
    return experiment._pose_dicts(bone_vectors, root_translation, root_rotation)


def write_polished_clip(
    *,
    source_payload: Mapping[str, Any],
    experiment: GpuCascadeExperiment,
    bone_vectors: torch.Tensor,
    root_translation: torch.Tensor,
    root_rotation: torch.Tensor,
    output_dir: Path,
    polish_report: Mapping[str, Any],
    require_pose_units: bool = True,
) -> Path:
    output_dir = assert_write_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rescored = rescore_tensors(experiment, bone_vectors, root_translation, root_rotation)
    payload = copy.deepcopy(dict(source_payload))
    payload["poses"] = poses_from_tensors(experiment, bone_vectors, root_translation, root_rotation)
    payload["score"] = float(rescored["meanScore"])
    payload["frameScores"] = rescored["perFrameScores"]
    payload["literaturePolish"] = dict(polish_report)
    clip_path = persist_gpu_clip_result(payload, output_dir)
    if bool(require_pose_units):
        require_pose_units_degrees(json.loads(clip_path.read_text(encoding="utf-8")), source=str(clip_path))
    return clip_path


def default_prop_coords_path(unit: str) -> Path | None:
    if str(unit) == "h3_crusader":
        preferred = (
            ROOT
            / "artifacts/pose_picker_runs/h3_crusader/idle_start_move_end/sprite_skeleton_walk_props_authored/props_coords.json"
        )
        if preferred.is_file():
            return preferred
        path = (
            ROOT
            / "artifacts/pose_picker_runs/h3_crusader/move_g0_props_authored/props_coords.json"
        )
        return path if path.is_file() else None
    return None


def default_bone_roles_path(unit: str) -> Path:
    tool = Path(__file__).resolve().parent
    sid = str(unit)
    hand_authored = {
        "h3_crusader": tool / "bone_roles_crusader_smartrigged_rigidized.json",
        "h3_beholder": tool / "bone_roles_beholder_smartrigged_rigidized.json",
        "h3_roc": tool / "bone_roles_roc_smartrig_props.json",
        "h3_hobgoblin": tool / "bone_roles_hobgoblin_smartrigged_rigidized.json",
        "h3_behemoth": tool / "bone_roles_behemoth_smartrig_props.json",
        "h3_ogre": tool / "bone_roles_h3_ogre_smartrig_props.json",
        "h3_thunderbird": tool / "bone_roles_h3_thunderbird_smartrig_props.json",
        "h3_ancient_behemoth": tool / "bone_roles_h3_ancient_behemoth_smartrig_props.json",
    }
    if sid in hand_authored and hand_authored[sid].is_file():
        return hand_authored[sid]
    bootstrap = tool / f"bone_roles_{sid}_smartrig_props.json"
    if bootstrap.is_file():
        return bootstrap
    raise ValueError(f"no default bone roles for unit={sid!r}")


def literature_lane_root(unit: str, clip: str = CLIP) -> Path:
    return assert_write_path(
        ROOT / "artifacts" / "pose_picker_runs" / str(unit) / str(clip) / LANE_NAME
    )


def load_source_clip(path: Path) -> dict[str, Any]:
    payload = load_clip_result(path)
    require_pose_units_degrees(payload, source=str(path))
    return payload


def resolve_lane_clip_path(lane_root: Path) -> Path:
    candidates = (
        lane_root / "solve" / "gpu_clip_result.json",
        lane_root / "gpu_clip_result.json",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(candidates[0])


def raster_literature_preview(
    *,
    payload: Mapping[str, Any],
    mesh: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Raster polished poses for GIF compare (geometry preview lane only)."""
    preview_payload = copy.deepcopy(dict(payload))
    config = dict(preview_payload.get("config") or {})
    config["score_mode"] = "geometry"
    config["depth_weight"] = 0.0
    config["silhouette_weight"] = 1.0
    config["chroma_weight"] = 0.0
    config["motion_weight"] = 0.0
    config["collision_enabled"] = False
    config["collision_weight"] = 0.0
    preview_payload["config"] = config
    return raster_tweak_preview(payload=preview_payload, mesh_glb=mesh, output_dir=output_dir)


def unit_mesh(unit: str, clip: str = CLIP) -> Path:
    sid = str(unit)
    meshy = ROOT / "artifacts/meshy_downloads"
    for suffix in ("_smartrigged_rigidized.glb", "_smartrigged.glb"):
        candidate = meshy / f"{sid}{suffix}"
        if candidate.is_file():
            return candidate
    return Path(stacked_unit_resolve(sid, clip)["mesh"])
