#!/usr/bin/env python3
"""~5-minute DINO joint iteration lane (Roc or crusader).

Seeds from ``stacked_small_ik_v1`` geometry IK when present, then runs coarse
joint rounds with sparse worst-8 walk probes. Default keep score is
``dinov3_geometry_consensus`` (per-probe-pack logit-minmax DINO + silhouette
IoU), not raw ``dinov3_dense``.

Contrast with ``run_roc_stacked_dinov3_fast.py`` (full-clip DINO probes,
~25 min, bind/rest seed).

Writes under
``artifacts/pose_picker_runs/<unit>/<clip>/stacked_dinov3_quick*``.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
FORBIDDEN_WRITE_PARTS = frozenset({"meshy_downloads", "fused_push_v24_pipeline"})

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from cascade_clip_pose_tweak import load_clip_result  # noqa: E402
from gpu_cascade_batch_lock import (  # noqa: E402
    SCRIPT_TOKENS,
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from gpu_cascade_delivery import require_pose_units_degrees, select_unit_delivery_choices  # noqa: E402
from roc_stacked_solve_common import (  # noqa: E402
    CLIP,
    JOINT_DINO_QUICK_LOOSE_PATCH,
    JOINT_DINO_QUICK_OVERRIDES,
    STACKED_UNLOCK_BASE,
    UNIT,
    stacked_unit_resolve,
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
from preview_timing import PREVIEW_GIF_FRAME_MS  # noqa: E402


def compose_sprite_vs_solved_gif(
    *,
    sprite_dir: Path,
    solved_rgb_dir: Path,
    dest: Path,
    frames: list[int],
    solved_label: str,
) -> Path:
    from PIL import Image, ImageDraw

    dest = assert_write_path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    images = []
    for frame in frames:
        sprite_path = sprite_dir / f"{int(frame):02d}.png"
        solved = Image.open(solved_rgb_dir / f"{int(frame):02d}.png").convert("RGB")
        panel_w, panel_h = solved.size
        sprite = Image.new("RGB", (panel_w, panel_h), (12, 12, 16))
        if sprite_path.is_file():
            with Image.open(sprite_path) as raw:
                sprite = raw.convert("RGB").resize((panel_w, panel_h))
        header = 22
        canvas = Image.new("RGB", (panel_w * 2, header + panel_h), (12, 12, 16))
        draw = ImageDraw.Draw(canvas)
        draw.text((8, 4), "sprite", fill=(230, 230, 235))
        draw.text((panel_w + 8, 4), solved_label, fill=(230, 230, 235))
        canvas.paste(sprite, (0, header))
        canvas.paste(solved, (panel_w, header))
        images.append(canvas)
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

def joint_quick_overrides(*, dense_only: bool, loose: bool = False) -> dict[str, Any]:
    overrides = {
        **JOINT_DINO_QUICK_OVERRIDES,
        **DINOV3_SEMANTIC,
        "dense_semantic_raster_scale": 2,
        "collision_enabled": False,
        "collision_weight": 0.0,
        "joint_unique_gain_weight": 0.0,
        "fine_unique_gain_weight": 0.0,
        "cheap_joint_probe_occupancy_only": False,
        "ik_enabled": False,
    }
    if loose:
        overrides.update(JOINT_DINO_QUICK_LOOSE_PATCH)
    if dense_only:
        overrides["score_mode"] = "dinov3_dense"
        overrides["depth_weight"] = 0.0
        overrides["silhouette_weight"] = 0.0
        overrides["chroma_weight"] = 0.0
        overrides["motion_weight"] = 0.0
    return overrides


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dense-only",
        action="store_true",
        help="score_mode=dinov3_dense with silhouette/depth/chroma/motion zeroed",
    )
    parser.add_argument(
        "--from-rest",
        action="store_true",
        help="start from bind/rest; do not seed from stacked_small_ik_v1 geometry IK",
    )
    parser.add_argument(
        "--loose",
        action="store_true",
        help="12° steps, 45° pass limit, 3 probe rungs, 3 articulated rounds",
    )
    parser.add_argument("--unit", default=UNIT, help=f"unit sid (default: {UNIT})")
    parser.add_argument("--clip", default=CLIP, help=f"animation clip (default: {CLIP})")
    return parser.parse_args()


def output_root(
    *,
    unit: str,
    clip: str,
    dense_only: bool,
    from_rest: bool,
    loose: bool,
) -> Path:
    base = ROOT / "artifacts" / "pose_picker_runs" / str(unit) / str(clip)
    if from_rest:
        if dense_only:
            suffix = "_loose" if loose else ""
            return base / f"stacked_dinov3_quick_dense_only_from_rest{suffix}"
        return base / "stacked_dinov3_quick_from_rest"
    if dense_only:
        return base / "stacked_dinov3_quick_dense_only"
    return base / "stacked_dinov3_quick"


def profile_name(*, dense_only: bool, from_rest: bool, loose: bool) -> str:
    if from_rest:
        if dense_only:
            return (
                "joint_dinov3_quick_dense_only_from_rest_loose"
                if loose
                else "joint_dinov3_quick_dense_only_from_rest"
            )
        return "joint_dinov3_quick_from_rest"
    return "joint_dinov3_quick_dense_only" if dense_only else "joint_dinov3_quick"


def geometry_ik_pose_seed(source_clip: Path) -> dict[int, dict[str, Any]]:
    payload = load_clip_result(source_clip)
    require_pose_units_degrees(payload, source=str(source_clip))
    poses = payload.get("poses") or {}
    return {int(frame): dict(pose) for frame, pose in poses.items()}


def main() -> int:
    args = parse_args()
    dense_only = bool(args.dense_only)
    from_rest = bool(args.from_rest)
    loose = bool(args.loose)
    unit_cfg = stacked_unit_resolve(str(args.unit), str(args.clip))
    unit = str(unit_cfg["unit"])
    clip = str(unit_cfg["clip"])
    mesh = Path(unit_cfg["mesh"])
    notebook = Path(unit_cfg["notebook"])
    anatomy_kwargs = dict(unit_cfg.get("anatomy_kwargs") or {})
    geometry_ik_root = Path(unit_cfg["geometry_ik_root"])
    out_root = assert_write_path(
        output_root(
            unit=unit,
            clip=clip,
            dense_only=dense_only,
            from_rest=from_rest,
            loose=loose,
        )
    )
    profile = profile_name(dense_only=dense_only, from_rest=from_rest, loose=loose)
    trial_id = profile
    score_mode = "dinov3_dense" if dense_only else str(
        JOINT_DINO_QUICK_OVERRIDES.get("score_mode") or "dinov3_geometry_consensus"
    )
    seed_label = "rest" if from_rest else "geometry_ik"

    if Path(__file__).name not in SCRIPT_TOKENS:
        raise RuntimeError("runner must be in gpu_cascade_batch_lock.SCRIPT_TOKENS")
    out_root.mkdir(parents=True, exist_ok=True)
    source_clip = geometry_ik_root / "gpu_clip_result.json"
    if not from_rest and not source_clip.is_file():
        raise FileNotFoundError(source_clip)
    if not mesh.is_file():
        raise FileNotFoundError(mesh)

    seed_poses: dict[int, dict[str, Any]] | None = None
    source_score: float | None = None
    if not from_rest:
        seed_poses = geometry_ik_pose_seed(source_clip)
        source_payload = load_clip_result(source_clip)
        source_score = float(source_payload.get("score") or 0)

    lock_path = global_cascade_batch_lock_path(ROOT)
    acquire_cascade_batch_lock(lock_path)
    started = time.perf_counter()
    report: dict[str, Any] = {
        "proof": "generated-artifact",
        "unit": unit,
        "clip": clip,
        "mesh": str(mesh).replace("\\", "/"),
        "profile": profile,
        "scoreMode": score_mode,
        "seed": seed_label,
        "loose": loose,
    }
    if not from_rest:
        report["sourceClip"] = str(source_clip).replace("\\", "/")
        report["sourceGeometryScore"] = source_score
        report["seedFrameCount"] = len(seed_poses or {})
    try:
        import roc_semantic_hybrid_widgets as widgets
        from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

        choices = select_unit_delivery_choices(widgets.discover_asset_choices(ROOT), unit)
        choice = next((item for item in choices if str(item.animation_name) == clip), None)
        if choice is None:
            raise RuntimeError(f"no delivery choice for {unit} {clip}")

        notebook_kwargs = _literal_config_kwargs(notebook, require_dino=False)
        notebook_gpu_fit_kwargs(notebook)
        config = _build_config(choice, mesh, notebook_kwargs, notebook, use_cache=False)
        gpu_kwargs = kwargs_for_choice(choice, full_pipeline=False, batch=True, mesh=mesh)
        gpu_kwargs.update(anatomy_kwargs)
        gpu_kwargs.update(STACKED_UNLOCK_BASE)
        gpu_kwargs.update(joint_quick_overrides(dense_only=dense_only, loose=loose))
        gpu_kwargs = refuse_imported_pose_seed(gpu_kwargs)
        if not from_rest and seed_poses is not None:
            gpu_kwargs["initial_poses"] = seed_poses
            gpu_kwargs["articulated_skip_when_seeded"] = False

        joint_dest = assert_write_path(out_root / profile)
        joint_dest.mkdir(parents=True, exist_ok=True)
        gpu_kwargs["live_status_path"] = str(joint_dest / "live_status.json")
        gpu_kwargs = filter_kwargs(gpu_kwargs)
        validate_trial_kwargs(trial_id, gpu_kwargs)
        config, gpu_kwargs = _apply_choice_camera(choice, config, gpu_kwargs, mesh)
        gpu_kwargs = refuse_imported_pose_seed(gpu_kwargs)
        if from_rest and gpu_kwargs.get("initial_poses"):
            raise RuntimeError("--from-rest must not keep initial_poses after camera apply")
        gpu_kwargs = filter_kwargs(gpu_kwargs)
        config = prepare_gpu_targets(config)

        step_note = "12 passLimit=45 rungs=3 rounds=3" if loose else "7.5 passLimit=25 rungs=2 rounds=2"
        print(
            f"joint_dinov3_quick: unit={unit} clip={clip} seed={seed_label} score={score_mode} "
            f"sparseProbe=8 step={step_note} dinoRaster=2x",
            flush=True,
        )
        run_gpu_depth_fit_from_hybrid_config(
            config,
            output_dir=joint_dest,
            **dict(gpu_kwargs),
        )
        joint_path = joint_dest / "gpu_clip_result.json"
        joint_payload = json.loads(joint_path.read_text(encoding="utf-8"))
        require_pose_units_degrees(joint_payload, source=str(joint_path))
        joint_score = float(joint_payload.get("score") or 0)
        report["result"] = {
            "clipResult": str(joint_path).replace("\\", "/"),
            "score": joint_score,
            "overrides": {
                key: gpu_kwargs.get(key)
                for key in (
                    "score_mode",
                    "articulated_iterations",
                    "joint_step_deg",
                    "joint_pass_limit_deg",
                    "joint_probe_rungs",
                    "cheap_joint_probe_frame_count",
                    "dense_semantic_raster_scale",
                )
            },
        }

        joint_rgb = joint_dest / "solved_rgb"
        gif = None
        if joint_rgb.is_dir():
            frames = [int(f) for f in joint_payload["frameIndices"]]
            sprite = sprite_dir_for_choice(choice)
            if from_rest:
                gif = compose_sprite_vs_solved_gif(
                    sprite_dir=sprite,
                    solved_rgb_dir=joint_rgb,
                    dest=out_root
                    / (
                        "sprite_vs_joint_dino_quick_dense_from_rest_loose.gif"
                        if loose
                        else "sprite_vs_joint_dino_quick_dense_from_rest.gif"
                    ),
                    frames=frames,
                    solved_label=f"dino {score_mode} {joint_score:.3f}",
                )
            else:
                geom_rgb = geometry_ik_root / "solved_rgb"
                if geom_rgb.is_dir():
                    gif = compose_compare_gif(
                        sprite_dir=sprite,
                        geometry_rgb_dir=geom_rgb,
                        solved_rgb_dir=joint_rgb,
                        dest=out_root
                        / (
                            "sprite_geometry_ik_vs_joint_dino_quick_dense.gif"
                            if dense_only
                            else "sprite_geometry_ik_vs_joint_dino_quick.gif"
                        ),
                        frames=frames,
                        geometry_label=f"geom ik {source_score:.3f}",
                        solved_label=f"joint dino {score_mode} {joint_score:.3f}",
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
