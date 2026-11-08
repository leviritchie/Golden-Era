#!/usr/bin/env python3
"""Roc start→move→end with LLM anatomy bone order + DINOv3/geometry consensus.

DEF groups g20→g00→g21. Bone visit order is LLM-authored by anatomical group
priority for this flyer transit; within each group, bones stay dependency
order. Per-group rotation scales become bone_limit_scale_overrides.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
MESH = ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
SIDE_CAM = (
    ROOT
    / "artifacts/pose_picker_runs/h3_roc/move/initialization"
    / "flyer_side_profile_camera_fit.json"
)
OUT = ROOT / "artifacts/pose_picker_runs/hybrid_method_quad/roc_move_dinov3_geometry_consensus"
METHOD = "dinov3_geometry_consensus"
DEF_GROUPS = (20, 0, 21)
BUDGET_SEC = 300.0
ANATOMY_GROUPS = TOOL / "roc_smartrig_anatomy_groups.json"
ANATOMY_ORDER = TOOL / "llm_authored/roc_start_move_end_anatomy_order.json"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))


def _write_labeled_gif(*, sprite_dir: Path, solved_dir: Path, out_gif: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default()
    for candidate in (
        Path(r"C:/Windows/Fonts/arial.ttf"),
        Path(r"C:/Windows/Fonts/segoeui.ttf"),
    ):
        if candidate.is_file():
            font = ImageFont.truetype(str(candidate), 16)
            break
    segments = (
        (0, 4, "MOVE START g20"),
        (4, 10, "MOVE g00"),
        (10, 14, "MOVE END g21"),
    )
    width = height = 220
    frames = []
    for index in range(14):
        sprite = Image.open(sprite_dir / f"{index:02d}.png").convert("RGBA")
        mesh = Image.open(solved_dir / f"{index:02d}.png").convert("RGBA")

        def fit(image: Image.Image) -> Image.Image:
            image = image.copy()
            image.thumbnail((width, height - 28), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (width, height), (18, 18, 22, 255))
            canvas.paste(
                image,
                ((width - image.width) // 2, 28 + (height - 28 - image.height) // 2),
                image,
            )
            return canvas

        band = Image.new("RGBA", (width * 2 + 8, height), (12, 12, 16, 255))
        band.paste(fit(sprite), (0, 0))
        band.paste(fit(mesh), (width + 8, 0))
        draw = ImageDraw.Draw(band)
        label = next(name for start, stop, name in segments if start <= index < stop)
        draw.rectangle((0, 0, width * 2 + 8, 26), fill=(30, 30, 40, 255))
        draw.text(
            (8, 5),
            f"{index:02d}  {label}   sprite | mesh  (anatomy bone order)",
            fill=(230, 230, 240, 255),
            font=font,
        )
        frames.append(band.convert("RGB"))
    out_gif.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        out_gif,
        save_all=True,
        append_images=frames[1:],
        duration=160,
        loop=0,
        optimize=False,
    )
    return out_gif


def main() -> int:
    from cascade_anatomy_bone_order import (
        cascade_kwargs_from_anatomy_order,
        expand_anatomy_order_paths,
    )
    from gpu_cascade_batch_lock import (
        acquire_cascade_batch_lock,
        global_cascade_batch_lock_path,
        release_cascade_batch_lock,
    )
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
    from run_chain_space_surface_compare import (
        _prepare_choice_config,
        _sprite_dir,
        compose_clip_gif,
    )
    from run_crusader_gpu_cascade_animation_set import (
        _release_gpu_workspace,
        notebook_gpu_fit_kwargs,
    )
    import roc_semantic_hybrid_widgets as widgets

    if not MESH.is_file():
        raise FileNotFoundError(MESH)
    if not SIDE_CAM.is_file():
        raise FileNotFoundError(SIDE_CAM)
    if not ANATOMY_GROUPS.is_file():
        raise FileNotFoundError(ANATOMY_GROUPS)
    if not ANATOMY_ORDER.is_file():
        raise FileNotFoundError(ANATOMY_ORDER)

    anatomy = expand_anatomy_order_paths(
        groups_path=ANATOMY_GROUPS,
        authored_path=ANATOMY_ORDER,
    )
    anatomy_kwargs = cascade_kwargs_from_anatomy_order(anatomy)

    lock = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
    started = time.perf_counter()
    try:
        from run_hybrid_method_quad import _build_isolated_def_choice

        choice = _build_isolated_def_choice(
            widgets, unit_sid="h3_roc", def_groups=DEF_GROUPS
        )
        config = _prepare_choice_config(choice, MESH, NOTEBOOK)
        config.camera_fit_path = str(SIDE_CAM)
        if hasattr(config, "joint_free_deg"):
            config.joint_free_deg = 150.0

        arm = OUT / METHOD
        arm.mkdir(parents=True, exist_ok=True)

        def _jsonable(value):
            if isinstance(value, tuple):
                return [_jsonable(item) for item in value]
            if isinstance(value, list):
                return [_jsonable(item) for item in value]
            if isinstance(value, dict):
                return {key: _jsonable(item) for key, item in value.items()}
            return value

        (arm / "llm_anatomy_order_expanded.json").write_text(
            json.dumps(_jsonable(anatomy), indent=2) + "\n", encoding="utf-8"
        )

        kwargs = notebook_gpu_fit_kwargs(NOTEBOOK)
        kwargs.update(
            {
                "score_mode": "dinov3_geometry_consensus",
                "dense_semantic_model_id": "facebook/dinov3-vits16-pretrain-lvd1689m",
                "dense_semantic_feature_layers": ("last",),
                "dense_semantic_local_radius": 1,
                "dense_semantic_position_weight": 1.0,
                "dense_semantic_raster_scale": 4,
                "dense_semantic_batch_size": 8,
                "depth_weight": 0.0,
                "silhouette_weight": 1.0,
                "chroma_weight": 0.0,
                "motion_weight": 0.0,
                "collision_enabled": False,
                "collision_weight": 0.0,
                "gradient_ladder_enabled": False,
                "chain_space_enabled": False,
                "ik_enabled": False,
                "physics_smooth_enabled": False,
                "profile_init_enabled": True,
                "profile_init_camera_basis_mode": "upright_turntable",
                "root_search_enabled": True,
                "root_rotation_axes": ("camera_forward", "camera_right", "camera_up"),
                "root_rotation_camera_up_limit_deg": 180.0,
                "root_rotation_first_frame_limit_deg": 180.0,
                "root_rotation_per_frame_limit_deg": 180.0,
                "root_rotation_defer_camera_up": False,
                "freeze_root_after_root_stage": False,
                "joint_search_axes": ("x", "y", "z"),
                "joint_diagonal_axes": 6,
                "joint_step_deg": 15.0,
                "mid_joint_step_deg": 5.0,
                "fine_joint_step_deg": 2.5,
                "articulated_iterations": 1,
                "fine_iterations": 0,
                "base_pose_enabled": False,
                "mid_pose_enabled": False,
                "branch_rescue_enabled": False,
                "root_refit_after_base_enabled": False,
                "fine_root_enabled": False,
                "skip_tiny_bones": False,
                **anatomy_kwargs,
            }
        )
        import inspect

        allowed = set(inspect.signature(run_gpu_depth_fit_from_hybrid_config).parameters)
        kwargs = {key: value for key, value in kwargs.items() if key in allowed}

        frame_count = len(tuple(getattr(config, "frame_indices", ()) or ()))
        print(
            f"roc start_move_end anatomy-order consensus -> {arm} "
            f"groups={DEF_GROUPS} frames={frame_count} "
            f"visit={list(anatomy['groupVisitOrder'])} "
            f"search_bones={len(kwargs.get('search_bones') or ())}",
            flush=True,
        )
        solved = run_gpu_depth_fit_from_hybrid_config(config, output_dir=arm, **kwargs)
        _release_gpu_workspace()

        pose_result = (
            getattr(solved, "pose_result", None)
            or getattr(solved, "clip_result", None)
            or {}
        )
        if not isinstance(pose_result, dict):
            pose_result = {}
        result_path = Path(
            pose_result.get("clipResultPath")
            or pose_result.get("clip_result_path")
            or (arm / "gpu_clip_result.json")
        )
        if not result_path.is_file():
            for cand in sorted(arm.glob("*clip*.json")) + sorted(arm.glob("*result*.json")):
                if cand.is_file():
                    result_path = cand
                    break
        payload = (
            json.loads(result_path.read_text(encoding="utf-8"))
            if result_path.is_file()
            else {}
        )
        sprite_dir = Path(_sprite_dir(choice))
        if frame_count < 1:
            frame_count = len(tuple(getattr(config, "frame_indices", ()) or ())) or 14
        gif = compose_clip_gif(
            clip_root=OUT,
            sprite_dir=sprite_dir,
            frame_count=frame_count,
            arms=({"id": METHOD},),
        )
        labeled = _write_labeled_gif(
            sprite_dir=sprite_dir,
            solved_dir=arm / "solved_rgb",
            out_gif=OUT / "start_move_end_anatomy_order_labeled.gif",
        )
        elapsed = time.perf_counter() - started
        report = {
            "method": METHOD,
            "proof": (
                "generated-artifact; LLM anatomy group order + dependency within "
                "group; DINOv3+silhouette consensus; not OE runtime"
            ),
            "defGroups": list(DEF_GROUPS),
            "frameCount": frame_count,
            "elapsedSec": round(elapsed, 1),
            "budgetSec": BUDGET_SEC,
            "withinBudget": elapsed <= BUDGET_SEC,
            "gif": str(gif).replace("\\", "/"),
            "labeledGif": str(labeled).replace("\\", "/"),
            "clipResult": str(result_path).replace("\\", "/"),
            "anatomyOrder": {
                "groupsPath": anatomy["groupsPath"],
                "authoredPath": anatomy["authoredPath"],
                "groupVisitOrder": anatomy["groupVisitOrder"],
                "rationale": anatomy.get("rationale"),
                "searchBones": list(anatomy["search_bones"]),
                "rotationScaleByGroup": {
                    name: entry["rotationScale"]
                    for name, entry in anatomy["expandedGroups"].items()
                },
            },
            "score_mode": (payload.get("config") or {}).get("score_mode"),
            "frameIoU": payload.get("frameIoU"),
            "frameScores": payload.get("frameScores"),
            "score": payload.get("score"),
        }
        (OUT / "run_report_anatomy_order.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, indent=2), flush=True)
        if elapsed > BUDGET_SEC:
            print(
                f"WARNING: exceeded {BUDGET_SEC:.0f}s budget ({elapsed:.1f}s)",
                flush=True,
            )
        return 0
    finally:
        release_cascade_batch_lock(lock)


if __name__ == "__main__":
    raise SystemExit(main())
