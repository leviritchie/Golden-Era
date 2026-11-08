#!/usr/bin/env python3
"""Chain-space stacked solve with root hypothesis search enabled.

Re-runs the cheapest solve-compare trial (chain space, ~3s without root) with
``root_search_enabled=true``. Root Adam stays off; per-frame discrete root
hypotheses run once, then root freezes for chain-space joint search.

Writes under
``artifacts/pose_picker_runs/h3_roc/idle_start_move_end/stacked_solve_compare/chain_space_root/``.
Experiment lane only. Not OE battle.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
OUT = (
    ROOT
    / "artifacts/pose_picker_runs/h3_roc/idle_start_move_end/stacked_solve_compare/chain_space_root"
)
PRIOR_CHAIN_SPACE = (
    ROOT
    / "artifacts/pose_picker_runs/h3_roc/idle_start_move_end/stacked_solve_compare/chain_space"
)
SOLVER_ID = "chain_space_root"

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
from roc_stacked_solve_common import (  # noqa: E402
    ANATOMY_KWARGS,
    CLIP,
    FORBIDDEN_WRITE_PARTS,
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
from run_roc_stacked_solve_compare import assert_compare_write_path, sprite_dir_for_choice  # noqa: E402

CHAIN_SPACE_OVERRIDES = {
    **JOINT_PROBE_BASE,
    "articulated_iterations": 0,
    "ik_enabled": False,
    "chain_space_enabled": True,
    "chain_space_iterations": 4,
    "chain_space_step_degs": (4.0, 8.0, 12.0),
}

ROOT_ALLOWED_OVERRIDES = {
    "root_search_enabled": True,
    "root_iterations": 0,
    "freeze_root_after_root_stage": True,
    "root_refit_after_base_enabled": False,
    "root_rotation_after_joints_yaw_enabled": False,
    "root_rotation_defer_camera_up": False,
}


def compose_three_panel_gif(
    *,
    sprite_dir: Path,
    prior_rgb_dir: Path,
    solved_rgb_dir: Path,
    dest: Path,
    frames: list[int],
    prior_label: str,
    solved_label: str,
) -> Path:
    from PIL import Image, ImageDraw

    dest.parent.mkdir(parents=True, exist_ok=True)
    images = []
    for frame in frames:
        sprite_path = sprite_dir / f"{int(frame):02d}.png"
        prior = Image.open(prior_rgb_dir / f"{int(frame):02d}.png").convert("RGB")
        solved = Image.open(solved_rgb_dir / f"{int(frame):02d}.png").convert("RGB")
        panel_w, panel_h = prior.size
        sprite = Image.new("RGB", (panel_w, panel_h), (12, 12, 16))
        if sprite_path.is_file():
            with Image.open(sprite_path) as raw:
                sprite = raw.convert("RGB").resize((panel_w, panel_h))
        header = 22
        canvas = Image.new("RGB", (panel_w * 3, header + panel_h), (12, 12, 16))
        draw = ImageDraw.Draw(canvas)
        draw.text((8, 4), "sprite", fill=(230, 230, 235))
        draw.text((panel_w + 8, 4), prior_label, fill=(230, 230, 235))
        draw.text((panel_w * 2 + 8, 4), solved_label, fill=(230, 230, 235))
        canvas.paste(sprite, (0, header))
        canvas.paste(prior, (panel_w, header))
        canvas.paste(solved, (panel_w * 2, header))
        images.append(canvas)
        prior.close()
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


def main() -> int:
    if Path(__file__).name not in SCRIPT_TOKENS:
        raise RuntimeError("runner must be in gpu_cascade_batch_lock.SCRIPT_TOKENS")
    out = assert_compare_write_path(OUT)
    out.mkdir(parents=True, exist_ok=True)

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
    gpu_kwargs.update(CHAIN_SPACE_OVERRIDES)
    gpu_kwargs.update(ROOT_ALLOWED_OVERRIDES)
    gpu_kwargs = refuse_imported_pose_seed(gpu_kwargs)
    gpu_kwargs["live_status_path"] = str(out / "live_status.json")
    gpu_kwargs = filter_kwargs(gpu_kwargs)
    if gpu_kwargs.get("initial_poses"):
        raise RuntimeError(f"{SOLVER_ID} must start from rest")
    if not gpu_kwargs.get("root_search_enabled"):
        raise RuntimeError(f"{SOLVER_ID} requires root_search_enabled=True")
    if not gpu_kwargs.get("chain_space_enabled"):
        raise RuntimeError(f"{SOLVER_ID} requires chain_space_enabled=True")
    config, gpu_kwargs = _apply_choice_camera(choice, config, gpu_kwargs, MESH)
    gpu_kwargs = refuse_imported_pose_seed(gpu_kwargs)
    gpu_kwargs = filter_kwargs(gpu_kwargs)
    config = prepare_gpu_targets(config)

    lock_path = global_cascade_batch_lock_path(ROOT)
    acquire_cascade_batch_lock(lock_path)
    started = time.perf_counter()
    print(
        json.dumps(
            {
                "solver": SOLVER_ID,
                "baseTrial": "chain_space",
                "root_search_enabled": gpu_kwargs.get("root_search_enabled"),
                "freeze_root_after_root_stage": gpu_kwargs.get("freeze_root_after_root_stage"),
                "out": str(out).replace("\\", "/"),
                "proof": "generated-artifact",
            },
            indent=2,
        ),
        flush=True,
    )
    try:
        run_gpu_depth_fit_from_hybrid_config(
            config,
            output_dir=out,
            **dict(gpu_kwargs),
        )
        result_path = out / "gpu_clip_result.json"
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        require_pose_units_degrees(payload, source=str(result_path))
        if any(part in FORBIDDEN_WRITE_PARTS for part in result_path.parts):
            raise RuntimeError(f"{SOLVER_ID} wrote live fused-push: {result_path}")
        frames = [int(frame) for frame in payload["frameIndices"]]
        prior_score = None
        prior_clip = PRIOR_CHAIN_SPACE / "gpu_clip_result.json"
        if prior_clip.is_file():
            prior_score = float(json.loads(prior_clip.read_text()).get("score") or 0)
        gif = None
        prior_rgb = PRIOR_CHAIN_SPACE / "solved_rgb"
        solved_rgb = out / "solved_rgb"
        if prior_rgb.is_dir() and solved_rgb.is_dir():
            gif = compose_three_panel_gif(
                sprite_dir=sprite_dir_for_choice(choice),
                prior_rgb_dir=prior_rgb,
                solved_rgb_dir=solved_rgb,
                dest=out / "sprite_chain_space_root.gif",
                frames=frames,
                prior_label="chain no root",
                solved_label="chain + root",
            )
        report = {
            "ok": True,
            "solver": SOLVER_ID,
            "clipResult": str(result_path).replace("\\", "/"),
            "score": payload.get("score"),
            "priorChainSpaceScore": prior_score,
            "rootSearchEnabled": bool(gpu_kwargs.get("root_search_enabled")),
            "compareGif": str(gif).replace("\\", "/") if gif else None,
            "elapsedSec": time.perf_counter() - started,
            "proof": "generated-artifact",
        }
        (out / "fit_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
        return 0
    finally:
        _release_gpu_workspace()
        release_cascade_batch_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
