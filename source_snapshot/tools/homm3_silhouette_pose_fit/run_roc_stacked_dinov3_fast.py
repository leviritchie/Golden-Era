#!/usr/bin/env python3
"""Fast DINOv3 evaluation on Roc stacked geometry IK.

Phase 1 (~5 min): rescore existing ``stacked_small_ik_v1`` poses once per frame
with geometry (parity) and ``dinov3_geometry_consensus`` — no IK re-solve.

Phase 2 (~15–30 min): ``joint_dinov3_dense`` from rest (articulated probes only).

Does **not** run IK with DINO on every probe (that path is hours).

Writes under
``artifacts/pose_picker_runs/h3_roc/idle_start_move_end/stacked_dinov3_compare/``.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import fields
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
OUT = ROOT / "artifacts/pose_picker_runs" / "h3_roc" / "idle_start_move_end" / "stacked_dinov3_compare"
GEOMETRY_IK = (
    ROOT / "artifacts/pose_picker_runs/h3_roc/idle_start_move_end/stacked_small_ik_v1"
)
MESH = ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
FORBIDDEN_WRITE_PARTS = frozenset({"meshy_downloads", "fused_push_v24_pipeline"})

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from cascade_clip_pose_tweak import (  # noqa: E402
    clip_frame_indices,
    load_clip_result,
    target_frame_dir_from_clip,
)
from gpu_cascade_batch_lock import (  # noqa: E402
    SCRIPT_TOKENS,
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from gpu_cascade_delivery import require_pose_units_degrees, select_unit_delivery_choices  # noqa: E402
from roc_gpu_cascade_experiment import GpuCascadeConfig, GpuCascadeExperiment  # noqa: E402
from roc_stacked_solve_common import (  # noqa: E402
    ANATOMY_KWARGS,
    CLIP,
    JOINT_PROBE_BASE,
    NOTEBOOK,
    STACKED_UNLOCK_BASE,
    UNIT,
)
from run_crusader_full_animation_set import _literal_config_kwargs  # noqa: E402
from run_crusader_gpu_cascade_animation_set import (  # noqa: E402
    _release_gpu_workspace,
    notebook_gpu_fit_kwargs,
    prepare_gpu_targets,
)
from run_fused_push_batch_all_units import (  # noqa: E402
    _apply_choice_camera,
    _build_config,
    kwargs_for_choice,
)
from run_fused_push_regression_triplet import filter_kwargs  # noqa: E402
from run_roc_stacked_dinov3_pass import (  # noqa: E402
    DINOV3_SEMANTIC,
    assert_write_path,
    compose_compare_gif,
    validate_trial_kwargs,
)
from run_roc_stacked_small_pass import refuse_imported_pose_seed  # noqa: E402
from run_roc_stacked_solve_compare import sprite_dir_for_choice  # noqa: E402

DINOV3_CONSENSUS_OVERRIDES = {
    **DINOV3_SEMANTIC,
    "score_mode": "dinov3_geometry_consensus",
    "cheap_joint_probe_occupancy_only": False,
    "bone_order_mode": "dependency",
}

JOINT_DENSE_OVERRIDES = {
    **JOINT_PROBE_BASE,
    **DINOV3_SEMANTIC,
    "score_mode": "dinov3_dense",
    "depth_weight": 0.0,
    "silhouette_weight": 0.0,
    "chroma_weight": 0.0,
    "motion_weight": 0.0,
    "collision_enabled": False,
    "collision_weight": 0.0,
    "joint_unique_gain_weight": 0.0,
    "fine_unique_gain_weight": 0.0,
    "cheap_joint_probe_occupancy_only": False,
    "bone_order_mode": "dependency",
    "ik_enabled": False,
}


def config_from_saved(saved: Mapping[str, Any], *, overrides: Mapping[str, Any]) -> GpuCascadeConfig:
    def _tupleize(value: Any) -> Any:
        if isinstance(value, list):
            return tuple(_tupleize(item) for item in value)
        return value

    allowed = {item.name for item in fields(GpuCascadeConfig)}
    kwargs: dict[str, Any] = {}
    for name, value in saved.items():
        if name in allowed:
            kwargs[name] = _tupleize(value)
    for name, value in overrides.items():
        if name in allowed:
            kwargs[name] = value
    return GpuCascadeConfig(**kwargs)


def rescore_payload(
    payload: Mapping[str, Any],
    *,
    mesh: Path,
    overrides: Mapping[str, Any],
) -> dict[str, Any]:
    import torch

    config = config_from_saved(payload["config"], overrides=overrides)
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
    bounded = experiment._bounded_bone_vectors(bones)
    with torch.no_grad():
        packed = experiment.evaluate(
            bounded,
            root_t,
            root_r,
            bone_mask=experiment.active_node_mask,
        )
    clip_mean = experiment._clip_objective_mean(bounded, root_t, root_r, packed)
    per_frame = [float(value) for value in packed["score"].detach().cpu().tolist()]
    return {
        "scoreMode": str(config.score_mode),
        "clipObjective": float(clip_mean),
        "geometryMean": float(packed["score"].mean().detach().item()),
        "perFrameMean": sum(per_frame) / max(len(per_frame), 1),
        "perFrameScores": per_frame,
        "silhouetteMean": float(packed["silhouetteIoU"].mean().detach().item()),
        "denseSemanticMean": float(packed["denseSemanticQuality"].mean().detach().item())
        if "denseSemanticQuality" in packed
        else None,
    }


def main() -> int:
    if Path(__file__).name not in SCRIPT_TOKENS:
        raise RuntimeError("runner must be in gpu_cascade_batch_lock.SCRIPT_TOKENS")
    out_root = assert_write_path(OUT)
    out_root.mkdir(parents=True, exist_ok=True)
    source_clip = GEOMETRY_IK / "gpu_clip_result.json"
    if not source_clip.is_file():
        raise FileNotFoundError(source_clip)
    if not MESH.is_file():
        raise FileNotFoundError(MESH)

    payload = load_clip_result(source_clip)
    require_pose_units_degrees(payload, source=str(source_clip))
    source_score = float(payload.get("score") or 0)

    lock_path = global_cascade_batch_lock_path(ROOT)
    acquire_cascade_batch_lock(lock_path)
    started = time.perf_counter()
    report: dict[str, Any] = {
        "sourceClip": str(source_clip).replace("\\", "/"),
        "sourceGeometryScore": source_score,
        "proof": "generated-artifact",
    }
    try:
        print("phase 1: rescore geometry IK (no re-solve)", flush=True)
        geometry_rescore = rescore_payload(
            payload,
            mesh=MESH,
            overrides={"score_mode": "geometry"},
        )
        dino_rescore = rescore_payload(
            payload,
            mesh=MESH,
            overrides=DINOV3_CONSENSUS_OVERRIDES,
        )
        rescore_dir = assert_write_path(out_root / "geometry_ik_rescore")
        rescore_dir.mkdir(parents=True, exist_ok=True)
        rescore_report = {
            "geometry": geometry_rescore,
            "dinov3_geometry_consensus": dino_rescore,
            "sourceScore": source_score,
            "geometryDelta": float(geometry_rescore["clipObjective"]) - source_score,
        }
        (rescore_dir / "rescore_report.json").write_text(
            json.dumps(rescore_report, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(rescore_report, indent=2), flush=True)
        report["rescore"] = rescore_report

        print("phase 2: joint dinov3_dense from rest", flush=True)
        import roc_semantic_hybrid_widgets as widgets
        from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

        choices = select_unit_delivery_choices(widgets.discover_asset_choices(ROOT), UNIT)
        choice = next((item for item in choices if str(item.animation_name) == CLIP), None)
        if choice is None:
            raise RuntimeError(f"no delivery choice for {UNIT} {CLIP}")

        notebook_kwargs = _literal_config_kwargs(NOTEBOOK, require_dino=False)
        notebook_gpu_fit_kwargs(NOTEBOOK)
        config = _build_config(choice, MESH, notebook_kwargs, NOTEBOOK, use_cache=False)
        gpu_kwargs = kwargs_for_choice(choice, full_pipeline=False, batch=True, mesh=MESH)
        gpu_kwargs.update(ANATOMY_KWARGS)
        gpu_kwargs.update(STACKED_UNLOCK_BASE)
        gpu_kwargs.update(JOINT_DENSE_OVERRIDES)
        gpu_kwargs = refuse_imported_pose_seed(gpu_kwargs)
        joint_dest = assert_write_path(out_root / "joint_dinov3_dense")
        joint_dest.mkdir(parents=True, exist_ok=True)
        gpu_kwargs["live_status_path"] = str(joint_dest / "live_status.json")
        gpu_kwargs = filter_kwargs(gpu_kwargs)
        validate_trial_kwargs("joint_dinov3_dense", gpu_kwargs)
        config, gpu_kwargs = _apply_choice_camera(choice, config, gpu_kwargs, MESH)
        gpu_kwargs = refuse_imported_pose_seed(gpu_kwargs)
        gpu_kwargs = filter_kwargs(gpu_kwargs)
        config = prepare_gpu_targets(config)

        run_gpu_depth_fit_from_hybrid_config(
            config,
            output_dir=joint_dest,
            **dict(gpu_kwargs),
        )
        joint_path = joint_dest / "gpu_clip_result.json"
        joint_payload = json.loads(joint_path.read_text(encoding="utf-8"))
        require_pose_units_degrees(joint_payload, source=str(joint_path))
        joint_score = float(joint_payload.get("score") or 0)
        report["jointDinov3Dense"] = {
            "clipResult": str(joint_path).replace("\\", "/"),
            "score": joint_score,
        }

        geom_rgb = GEOMETRY_IK / "solved_rgb"
        joint_rgb = joint_dest / "solved_rgb"
        gif = None
        if geom_rgb.is_dir() and joint_rgb.is_dir():
            frames = [int(f) for f in joint_payload["frameIndices"]]
            gif = compose_compare_gif(
                sprite_dir=sprite_dir_for_choice(choice),
                geometry_rgb_dir=geom_rgb,
                solved_rgb_dir=joint_rgb,
                dest=out_root / "sprite_geometry_ik_vs_joint_dino.gif",
                frames=frames,
                geometry_label=f"geom ik {source_score:.3f}",
                solved_label=f"joint dino {joint_score:.3f}",
            )
        report["compareGif"] = str(gif).replace("\\", "/") if gif else None
        report["elapsedSec"] = time.perf_counter() - started
        report["ok"] = True
        (out_root / "fit_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
        return 0
    finally:
        _release_gpu_workspace()
        release_cascade_batch_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
