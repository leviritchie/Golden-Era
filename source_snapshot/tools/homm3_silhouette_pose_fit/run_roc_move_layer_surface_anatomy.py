#!/usr/bin/env python3
"""Roc move with layer_surface + LLM anatomy schedule (no articulated walk).

Same chain-space geometry authority as the surface compare, but joint layers
follow authored anatomy group priority (wings first) with dependency order
inside each group, and per-group rotation limit scales.
"""

from __future__ import annotations

import inspect
import json
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
MESH = ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
OUT = (
    ROOT
    / "artifacts/pose_picker_runs/chain_space_surface_compare_roc_move_layer_surface_anatomy"
)
ANATOMY_GROUPS = TOOL / "roc_smartrig_anatomy_groups.json"
ANATOMY_ORDER = TOOL / "llm_authored/roc_move_layer_surface_anatomy_order.json"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

# Motion-led geometry mix from the chain-space surface compare.
GEOMETRY_AUTHORITY = {
    "score_mode": "geometry",
    "motion_weight": 1.00,
    "depth_weight": 0.25,
    "silhouette_weight": 0.20,
    "chroma_weight": 0.20,
    "collision_enabled": True,
    "collision_weight": 0.35,
}


def _write_labeled_gif(*, sprite_dir: Path, solved_dir: Path, out_gif: Path) -> Path:
    font = ImageFont.load_default()
    for candidate in (
        Path(r"C:/Windows/Fonts/arial.ttf"),
        Path(r"C:/Windows/Fonts/segoeui.ttf"),
    ):
        if candidate.is_file():
            font = ImageFont.truetype(str(candidate), 16)
            break
    width = height = 220
    frames = []
    count = len(list(solved_dir.glob("*.png")))
    for index in range(count):
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
        draw.rectangle((0, 0, width * 2 + 8, 26), fill=(30, 30, 40, 255))
        draw.text(
            (8, 5),
            f"{index:02d}  roc move  sprite | layer_surface+anatomy",
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
        _select_choice,
        _sprite_dir,
        compose_clip_gif,
    )
    from run_crusader_gpu_cascade_animation_set import notebook_gpu_fit_kwargs
    import roc_semantic_hybrid_widgets as widgets

    if not MESH.is_file():
        raise FileNotFoundError(MESH)
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
        choice = _select_choice(widgets, unit_sid="h3_roc", animation="move")
        config = _prepare_choice_config(choice, MESH, NOTEBOOK)
        arm = OUT / "roc_move" / "layer_surface_anatomy"
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
                **GEOMETRY_AUTHORITY,
                "sa_enabled": False,
                "gradient_ladder_enabled": False,
                "ik_enabled": False,
                "physics_smooth_enabled": False,
                "joint_temporal_consensus_enabled": True,
                "sprite_aligned_motion_keep_enabled": True,
                "sprite_aligned_motion_keep_min_improvement": 0.01,
                "live_preview": False,
                "chain_space_enabled": True,
                "chain_space_mode": "layer_surface",
                "chain_space_iterations": 2,
                "chain_space_step_degs": (5.0, 10.0, 20.0, 40.0),
                "articulated_iterations": 0,
                "fine_iterations": 0,
                "base_pose_enabled": False,
                "mid_pose_enabled": False,
                "branch_rescue_enabled": False,
                "skip_tiny_bones": False,
                # Adapter maps optimize_root_rotation from root_search_enabled.
                # Defer-up with root search off fails closed; keep root search
                # off like the surface-compare layer_surface arm.
                "root_search_enabled": False,
                "root_rotation_defer_camera_up": False,
                **anatomy_kwargs,
            }
        )
        allowed = set(inspect.signature(run_gpu_depth_fit_from_hybrid_config).parameters)
        kwargs = {key: value for key, value in kwargs.items() if key in allowed}

        print(
            f"roc move layer_surface+anatomy -> {arm} "
            f"visit={list(anatomy['groupVisitOrder'])} "
            f"search_bones={len(kwargs.get('search_bones') or ())}",
            flush=True,
        )
        solved = run_gpu_depth_fit_from_hybrid_config(config, output_dir=arm, **kwargs)

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
        frame_count = len(tuple(getattr(config, "frame_indices", ()) or ())) or 6
        gif = compose_clip_gif(
            clip_root=OUT / "roc_move",
            sprite_dir=sprite_dir,
            frame_count=frame_count,
            arms=({"id": "layer_surface_anatomy"},),
        )
        solved_rgb = arm / "solved_rgb"
        if not solved_rgb.is_dir():
            for name in ("solved_rgb", "preview"):
                if (arm / name).is_dir():
                    solved_rgb = arm / name
                    break
        labeled = _write_labeled_gif(
            sprite_dir=sprite_dir,
            solved_dir=solved_rgb,
            out_gif=OUT / "roc_move" / "roc_move_layer_surface_anatomy_labeled.gif",
        )
        elapsed = time.perf_counter() - started

        # Prove layer visit order was anatomy, not bind-depth.
        history = []
        for key, value in payload.items():
            if (
                isinstance(value, list)
                and value
                and isinstance(value[0], dict)
                and "bones" in value[0]
            ):
                history = [row for row in value if row.get("bones")]
                break
        first_pass = []
        seen = set()
        for row in history:
            bone = (row.get("bones") or ["?"])[0]
            if bone not in seen:
                first_pass.append(bone)
                seen.add(bone)

        report = {
            "method": "layer_surface_anatomy",
            "proof": (
                "generated-artifact; layer_surface with LLM anatomy group "
                "schedule + dependency within group + rotation scales; "
                "not OE runtime"
            ),
            "elapsedSec": round(elapsed, 1),
            "gif": str(gif).replace("\\", "/"),
            "labeledGif": str(labeled).replace("\\", "/"),
            "clipResult": str(result_path).replace("\\", "/"),
            "score": payload.get("score"),
            "frameIoU": payload.get("frameIoU"),
            "frameScores": payload.get("frameScores"),
            "anatomyOrder": {
                "groupVisitOrder": anatomy["groupVisitOrder"],
                "searchBones": list(anatomy["search_bones"]),
                "rotationScaleByGroup": {
                    name: entry["rotationScale"]
                    for name, entry in anatomy["expandedGroups"].items()
                },
            },
            "observedFirstPassBones": first_pass,
            "recorded": {
                "chain_space_mode": (payload.get("config") or {}).get("chain_space_mode"),
                "chain_space_enabled": (payload.get("config") or {}).get(
                    "chain_space_enabled"
                ),
                "search_bones": (payload.get("config") or {}).get("search_bones"),
                "include_unlisted_search_bones": (payload.get("config") or {}).get(
                    "include_unlisted_search_bones"
                ),
                "articulated_iterations": (payload.get("config") or {}).get(
                    "articulated_iterations"
                ),
            },
        }
        (OUT / "roc_move" / "run_report_layer_surface_anatomy.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, indent=2), flush=True)
        expected = list(anatomy["search_bones"])
        if first_pass and first_pass != expected[: len(first_pass)]:
            print(
                "WARNING: first-pass bone order diverged from anatomy search_bones",
                flush=True,
            )
            print("expected", expected[: len(first_pass)], flush=True)
            print("observed", first_pass, flush=True)
        return 0
    finally:
        release_cascade_batch_lock(lock)


if __name__ == "__main__":
    raise SystemExit(main())
