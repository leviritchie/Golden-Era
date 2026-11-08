#!/usr/bin/env python3
"""Stacked IK with DINOv3 geometry consensus scoring on Roc walk.

Mirrors stacked_small_ik_v1 solve (silhouette_miss blob IK, unlocked joints,
root frozen) but keep score is ``dinov3_geometry_consensus``:
``sqrt(silhouette_iou * softened_dino_n)`` minus collision.

``cheap_joint_probe_occupancy_only`` must be false — DINOv3 cannot score
occupancy-only probes. Also runs a joint-only ``dinov3_dense`` baseline.

Writes under
``artifacts/pose_picker_runs/h3_roc/idle_start_move_end/stacked_dinov3_compare/``.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
OUT = ROOT / "artifacts/pose_picker_runs" / "h3_roc" / "idle_start_move_end" / "stacked_dinov3_compare"
GEOMETRY_IK = (
    ROOT / "artifacts/pose_picker_runs/h3_roc/idle_start_move_end/stacked_small_ik_v1"
)
FORBIDDEN_WRITE_PARTS = frozenset({"meshy_downloads", "fused_push_v24_pipeline"})

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (  # noqa: E402
    SCRIPT_TOKENS,
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from gpu_cascade_delivery import require_pose_units_degrees, select_unit_delivery_choices  # noqa: E402
from preview_timing import PREVIEW_GIF_FRAME_MS  # noqa: E402
from roc_gpu_cascade_experiment import DEFAULT_CASCADE_DINO_V3_MODEL_ID  # noqa: E402
from roc_stacked_solve_common import (  # noqa: E402
    ANATOMY_KWARGS,
    CLIP,
    IK_MISS_BASE,
    JOINT_PROBE_BASE,
    MESH,
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
from run_roc_stacked_small_pass import refuse_imported_pose_seed  # noqa: E402
from run_roc_stacked_solve_compare import sprite_dir_for_choice  # noqa: E402

DINOV3_SEMANTIC = {
    "dense_semantic_model_id": DEFAULT_CASCADE_DINO_V3_MODEL_ID,
    "dense_semantic_feature_layers": ("last",),
    "dense_semantic_local_radius": 1,
    "dense_semantic_position_weight": 1.0,
    "dense_semantic_raster_scale": 4,
    "dense_semantic_batch_size": 8,
    "dense_semantic_autograd_enabled": False,
}

TRIALS: tuple[dict[str, Any], ...] = (
    {
        "id": "ik_dinov3_consensus",
        "label": "ik dino consensus",
        "overrides": {
            **IK_MISS_BASE,
            **DINOV3_SEMANTIC,
            "score_mode": "dinov3_geometry_consensus",
            "cheap_joint_probe_occupancy_only": False,
            "bone_order_mode": "dependency",
        },
    },
    {
        "id": "joint_dinov3_dense",
        "label": "joint dino dense",
        "overrides": {
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
        },
    },
)


def assert_write_path(path: Path) -> Path:
    resolved = path.resolve()
    allowed = (ROOT / "artifacts" / "pose_picker_runs").resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise RuntimeError(f"writes must stay under {allowed}; got {resolved}") from exc
    if any(part in FORBIDDEN_WRITE_PARTS for part in resolved.parts):
        raise RuntimeError(f"must not write live payload paths: {resolved}")
    if not any(str(part).startswith("stacked_dinov3_") for part in resolved.parts):
        raise RuntimeError(
            f"path must be under a stacked_dinov3_* lane; got {resolved}"
        )
    return resolved


def compose_compare_gif(
    *,
    sprite_dir: Path,
    geometry_rgb_dir: Path,
    solved_rgb_dir: Path,
    dest: Path,
    frames: list[int],
    geometry_label: str,
    solved_label: str,
) -> Path:
    from PIL import Image, ImageDraw

    dest = assert_write_path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    images = []
    for frame in frames:
        sprite_path = sprite_dir / f"{int(frame):02d}.png"
        geom = Image.open(geometry_rgb_dir / f"{int(frame):02d}.png").convert("RGB")
        solved = Image.open(solved_rgb_dir / f"{int(frame):02d}.png").convert("RGB")
        panel_w, panel_h = geom.size
        sprite = Image.new("RGB", (panel_w, panel_h), (12, 12, 16))
        if sprite_path.is_file():
            with Image.open(sprite_path) as raw:
                sprite = raw.convert("RGB").resize((panel_w, panel_h))
        header = 22
        canvas = Image.new("RGB", (panel_w * 3, header + panel_h), (12, 12, 16))
        draw = ImageDraw.Draw(canvas)
        draw.text((8, 4), "sprite", fill=(230, 230, 235))
        draw.text((panel_w + 8, 4), geometry_label, fill=(230, 230, 235))
        draw.text((panel_w * 2 + 8, 4), solved_label, fill=(230, 230, 235))
        canvas.paste(sprite, (0, header))
        canvas.paste(geom, (panel_w, header))
        canvas.paste(solved, (panel_w * 2, header))
        images.append(canvas)
        geom.close()
        solved.close()
    images[0].save(
        dest,
        save_all=True,
        append_images=images[1:],
        duration=int(PREVIEW_GIF_FRAME_MS),
        loop=0,
        optimize=False,
    )
    return dest


def validate_trial_kwargs(trial_id: str, kwargs: dict[str, Any]) -> None:
    mode = str(kwargs.get("score_mode") or "geometry")
    if mode in {"dinov3_dense", "dinov3_geometry_consensus"}:
        if bool(kwargs.get("cheap_joint_probe_occupancy_only")):
            raise RuntimeError(
                f"{trial_id}: DINOv3 score modes cannot use cheap occupancy-only probes"
            )
    if mode == "dinov3_dense" and bool(kwargs.get("ik_enabled")):
        raise RuntimeError(f"{trial_id}: dinov3_dense cannot run with ik_enabled=True")


def main() -> int:
    if Path(__file__).name not in SCRIPT_TOKENS:
        raise RuntimeError("runner must be in gpu_cascade_batch_lock.SCRIPT_TOKENS")
    out_root = assert_write_path(OUT)
    out_root.mkdir(parents=True, exist_ok=True)

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
    gpu_kwargs = refuse_imported_pose_seed(gpu_kwargs)
    gpu_kwargs = filter_kwargs(gpu_kwargs)
    config, gpu_kwargs = _apply_choice_camera(choice, config, gpu_kwargs, MESH)
    gpu_kwargs = refuse_imported_pose_seed(gpu_kwargs)
    gpu_kwargs = filter_kwargs(gpu_kwargs)
    config = prepare_gpu_targets(config)

    lock_path = global_cascade_batch_lock_path(ROOT)
    acquire_cascade_batch_lock(lock_path)
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    try:
        for trial in TRIALS:
            dest = assert_write_path(out_root / str(trial["id"]))
            dest.mkdir(parents=True, exist_ok=True)
            kwargs = dict(gpu_kwargs)
            kwargs.update(dict(trial.get("overrides") or {}))
            kwargs["live_status_path"] = str(dest / "live_status.json")
            kwargs = refuse_imported_pose_seed(kwargs)
            kwargs = filter_kwargs(kwargs)
            validate_trial_kwargs(str(trial["id"]), kwargs)
            if kwargs.get("initial_poses"):
                raise RuntimeError(f"{trial['id']} must start from rest")
            print(
                json.dumps(
                    {
                        "trial": trial["id"],
                        "score_mode": kwargs.get("score_mode"),
                        "ik_enabled": kwargs.get("ik_enabled"),
                        "cheap_joint_probe_occupancy_only": kwargs.get(
                            "cheap_joint_probe_occupancy_only"
                        ),
                    },
                    indent=2,
                ),
                flush=True,
            )
            run_gpu_depth_fit_from_hybrid_config(
                config,
                output_dir=dest,
                **dict(kwargs),
            )
            result_path = dest / "gpu_clip_result.json"
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            require_pose_units_degrees(payload, source=str(result_path))
            results.append(
                {
                    "id": trial["id"],
                    "label": trial["label"],
                    "score": payload.get("score"),
                    "scoreMode": payload.get("config", {}).get("score_mode"),
                }
            )
            print(f"done {trial['id']} score={float(payload.get('score') or 0):.4f}", flush=True)

        ik_dest = out_root / "ik_dinov3_consensus"
        geom_rgb = GEOMETRY_IK / "solved_rgb"
        dino_rgb = ik_dest / "solved_rgb"
        gif = None
        if geom_rgb.is_dir() and dino_rgb.is_dir():
            geom_score = None
            geom_clip = GEOMETRY_IK / "gpu_clip_result.json"
            if geom_clip.is_file():
                geom_score = float(json.loads(geom_clip.read_text()).get("score") or 0)
            dino_score = float(
                json.loads((ik_dest / "gpu_clip_result.json").read_text()).get("score") or 0
            )
            frames = [
                int(frame)
                for frame in json.loads((ik_dest / "gpu_clip_result.json").read_text())[
                    "frameIndices"
                ]
            ]
            gif = compose_compare_gif(
                sprite_dir=sprite_dir_for_choice(choice),
                geometry_rgb_dir=geom_rgb,
                solved_rgb_dir=dino_rgb,
                dest=ik_dest / "sprite_geometry_vs_dinov3_ik.gif",
                frames=frames,
                geometry_label=f"geom ik {geom_score:.3f}" if geom_score else "geom ik",
                solved_label=f"dino ik {dino_score:.3f}",
            )
        report = {
            "ok": True,
            "elapsedSec": time.perf_counter() - started,
            "trials": results,
            "compareGif": str(gif).replace("\\", "/") if gif else None,
            "proof": "generated-artifact",
        }
        (out_root / "fit_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
        return 0
    finally:
        _release_gpu_workspace()
        release_cascade_batch_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
