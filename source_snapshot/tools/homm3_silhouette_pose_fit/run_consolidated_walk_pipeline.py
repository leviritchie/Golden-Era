#!/usr/bin/env python3
"""Run the consolidated walk-solve profile on one unit/clip.

Scoring authority and every search knob come from
``consolidated_walk_profile.CONSOLIDATED_WALK_PROFILE``, which carries the
verdict provenance for each value. This runner owns only orchestration:
GPU lock, target prep, solve, persist, preview.

Performance rules are the ones the user's own diagnosis produced after a clip
took ~40 minutes and the machine ran out of RAM:

  * exactly one solver process holds a CUDA raster context (exclusive lock);
  * the GPU workspace is released when the solve finishes;
  * poses are persisted to disk before any preview is composed, because a
    preview crash once destroyed 40 minutes of solved poses.

    py -3 run_consolidated_walk_pipeline.py --unit h3_roc
    py -3 run_consolidated_walk_pipeline.py --unit h3_crusader

Writes under
``artifacts/pose_picker_runs/<unit>/<clip>/consolidated_walk_v1/``.
Proof tier: generated artifact. Not OE battle runtime.
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
LANE_NAME = "consolidated_walk_v1"
ANATOMY_VETO_LANE_NAME = "consolidated_walk_anatomy_veto_v1"
FORBIDDEN_WRITE_PARTS = frozenset({"meshy_downloads", "fused_push_v24_pipeline"})

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from consolidated_walk_profile import (  # noqa: E402
    RUNTIME_GOAL_SEC,
    assert_dense_keep_authority,
    consolidated_walk_anatomy_veto_overrides,
    consolidated_walk_overrides,
)
from gpu_cascade_batch_lock import (  # noqa: E402
    SCRIPT_TOKENS,
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from gpu_cascade_delivery import (  # noqa: E402
    require_pose_units_degrees,
    select_unit_delivery_choices,
)
from preview_timing import PREVIEW_GIF_FRAME_MS  # noqa: E402
from roc_stacked_solve_common import CLIP, UNIT, stacked_unit_resolve  # noqa: E402
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


def assert_write_path(path: Path) -> Path:
    """Confine writes to this lane under artifacts/pose_picker_runs."""
    resolved = path.resolve()
    allowed = (ROOT / "artifacts" / "pose_picker_runs").resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise RuntimeError(f"writes must stay under {allowed}; got {resolved}") from exc
    if any(part in FORBIDDEN_WRITE_PARTS for part in resolved.parts):
        raise RuntimeError(f"must not write live payload paths: {resolved}")
    if not any(
        str(part).startswith(LANE_NAME) or str(part).startswith(ANATOMY_VETO_LANE_NAME)
        for part in resolved.parts
    ):
        raise RuntimeError(
            f"path must be under a {LANE_NAME}* or {ANATOMY_VETO_LANE_NAME}* lane; got {resolved}"
        )
    return resolved


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
    if not images:
        raise RuntimeError("no solved frames to preview")
    images[0].save(
        dest,
        save_all=True,
        append_images=images[1:],
        duration=int(PREVIEW_GIF_FRAME_MS),
        loop=0,
        optimize=False,
    )
    return dest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", default=UNIT, help=f"unit sid (default: {UNIT})")
    parser.add_argument("--clip", default=CLIP, help=f"animation clip (default: {CLIP})")
    parser.add_argument(
        "--anatomy-veto",
        action="store_true",
        help="enable Phase-B anatomy veto during probe keep (strain/collision/prop)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if Path(__file__).name not in SCRIPT_TOKENS:
        raise RuntimeError("runner must be in gpu_cascade_batch_lock.SCRIPT_TOKENS")

    unit_cfg = stacked_unit_resolve(str(args.unit), str(args.clip))
    unit = str(unit_cfg["unit"])
    clip = str(unit_cfg["clip"])
    mesh = Path(unit_cfg["mesh"])
    notebook = Path(unit_cfg["notebook"])
    anatomy_kwargs = dict(unit_cfg.get("anatomy_kwargs") or {})
    anatomy_veto_kwargs = dict(unit_cfg.get("anatomy_veto_kwargs") or {})
    if not mesh.is_file():
        raise FileNotFoundError(mesh)

    lane_name = ANATOMY_VETO_LANE_NAME if bool(args.anatomy_veto) else LANE_NAME
    out_root = assert_write_path(
        ROOT / "artifacts" / "pose_picker_runs" / unit / clip / lane_name
    )
    out_root.mkdir(parents=True, exist_ok=True)
    solve_dest = assert_write_path(out_root / "solve")
    solve_dest.mkdir(parents=True, exist_ok=True)

    lock_path = global_cascade_batch_lock_path(ROOT)
    acquire_cascade_batch_lock(lock_path)
    started = time.perf_counter()
    report: dict[str, Any] = {
        "proof": "generated-artifact",
        "lane": lane_name,
        "unit": unit,
        "clip": clip,
        "mesh": str(mesh).replace("\\", "/"),
        "seed": "rest",
        "runtimeGoalSec": RUNTIME_GOAL_SEC,
    }
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
        if bool(args.anatomy_veto):
            gpu_kwargs.update(consolidated_walk_anatomy_veto_overrides())
            gpu_kwargs.update(anatomy_veto_kwargs)
        else:
            gpu_kwargs.update(consolidated_walk_overrides())
        gpu_kwargs = refuse_imported_pose_seed(gpu_kwargs)
        gpu_kwargs["live_status_path"] = str(solve_dest / "live_status.json")
        gpu_kwargs = filter_kwargs(gpu_kwargs)
        assert_dense_keep_authority(gpu_kwargs)
        config, gpu_kwargs = _apply_choice_camera(choice, config, gpu_kwargs, mesh)
        gpu_kwargs = refuse_imported_pose_seed(gpu_kwargs)
        if gpu_kwargs.get("initial_poses"):
            raise RuntimeError("consolidated lane must start from rest")
        gpu_kwargs = filter_kwargs(gpu_kwargs)
        assert_dense_keep_authority(gpu_kwargs)
        config = prepare_gpu_targets(config)

        print(
            f"consolidated walk: unit={unit} clip={clip} seed=rest "
            f"lane={lane_name} anatomyVeto={int(bool(args.anatomy_veto))} "
            f"score={gpu_kwargs.get('score_mode')} consensus=on loopMirror=on "
            f"step={gpu_kwargs.get('joint_step_deg')} "
            f"passLimit={gpu_kwargs.get('joint_pass_limit_deg')} "
            f"rungs={gpu_kwargs.get('joint_probe_rungs')} "
            f"sparseProbe={gpu_kwargs.get('cheap_joint_probe_frame_count')}",
            flush=True,
        )
        run_gpu_depth_fit_from_hybrid_config(
            config,
            output_dir=solve_dest,
            **dict(gpu_kwargs),
        )

        # Poses are on disk from here on; preview work cannot lose the solve.
        clip_path = solve_dest / "gpu_clip_result.json"
        payload = json.loads(clip_path.read_text(encoding="utf-8"))
        require_pose_units_degrees(payload, source=str(clip_path))
        score = float(payload.get("score") or 0)
        elapsed = time.perf_counter() - started
        report["result"] = {
            "clipResult": str(clip_path).replace("\\", "/"),
            "score": score,
            "scoreMode": gpu_kwargs.get("score_mode"),
            "solveSec": elapsed,
            "withinRuntimeGoal": elapsed <= RUNTIME_GOAL_SEC,
            "profile": {
                key: gpu_kwargs.get(key)
                for key in (
                    "score_mode",
                    "articulated_iterations",
                    "joint_step_deg",
                    "fine_joint_step_deg",
                    "joint_pass_limit_deg",
                    "joint_probe_rungs",
                    "cheap_joint_probe_frame_count",
                    "dense_semantic_raster_scale",
                    "joint_step_score_norm",
                    "joint_temporal_consensus_enabled",
                    "joint_temporal_consensus_tie_bonus",
                    "joint_temporal_consensus_bidirectional",
                    "joint_temporal_consensus_independent_passes",
                    "joint_temporal_consensus_whole_pose",
                    "joint_temporal_consensus_idle_end",
                    "idle_suffix_mirror_prefix_enabled",
                )
            },
        }
        (out_root / "fit_report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

        solved_rgb = solve_dest / "solved_rgb"
        if not solved_rgb.is_dir():
            raise RuntimeError(f"solver did not write preview rasters: {solved_rgb}")
        gif = compose_sprite_vs_solved_gif(
            sprite_dir=sprite_dir_for_choice(choice),
            solved_rgb_dir=solved_rgb,
            dest=out_root / f"sprite_vs_consolidated_{unit}.gif",
            frames=[int(frame) for frame in payload["frameIndices"]],
            solved_label=f"consolidated {score:.3f}",
        )
        report["compareGif"] = str(gif).replace("\\", "/")
        report["elapsedSec"] = time.perf_counter() - started
        report["ok"] = True
        (out_root / "fit_report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, indent=2), flush=True)
        return 0
    finally:
        _release_gpu_workspace()
        release_cascade_batch_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
