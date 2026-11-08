#!/usr/bin/env python3
"""Compare chain-space surface navigators on three clips; write panel grids.

Four arms, one hypothesis each:

- ``control``: existing discrete one-bone walk (no chain-space stage).
- ``chain_grad``: overlapping root-to-leaf paths; per-frame coupled step
  where every active joint on the path takes the same angle along its
  own gradient (hips no longer eat the limb).
- ``branch_trust``: disjoint fork-split segments; per-frame RMS direction
  and a trust radius. Not a clip-wide pose.
- ``layer_surface``: proximal-to-distal one-joint layers (the next
  coordinate in X-D space).

Tip-IK is not an arm. DINOv3 autograd is not an arm. Occupancy motion
leads the keep mix. Per-frame chain-space keep then spreads neighbor
poses (temporal consensus). A later keep-or-zero pass leaves travel that
explains the occupancy pairs that frame actually changes, at full
strength, and copies the previous frame onto travel that does not or that
makes a neighboring pair worse. Physics damping stays off. Outputs are
generated experiment candidates; ``CURRENT_CASCADE_KEEP`` refuses them.
"""
from __future__ import annotations

import argparse
import gc
import inspect
import json
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
DEFAULT_OUT = ROOT / "artifacts/pose_picker_runs/chain_space_surface_compare_motion_aligned_tight"
MATCHED_OUT = ROOT / "artifacts/pose_picker_runs/chain_space_surface_compare_motion_aligned_tight_matched_budget"
MATCHED_CHAIN_SPACE_ITERATIONS = 64

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from cascade_chain_space import CHAIN_SPACE_MODES  # noqa: E402
from cascade_sprite_aligned_motion import (  # noqa: E402
    SPRITE_ALIGNED_KEEP_MIN_IMPROVEMENT,
)
from gpu_cascade_batch_lock import (  # noqa: E402
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from gpu_cascade_delivery import clip_result_matches_current_keep  # noqa: E402
from run_crusader_full_animation_set import (  # noqa: E402
    _literal_config_kwargs,
    _notebook_config,
)
from run_crusader_gpu_cascade_animation_set import (  # noqa: E402
    _choice_overrides,
    notebook_gpu_fit_kwargs,
    prepare_gpu_targets,
)

MESH_BY_UNIT = {
    "h3_angel": ROOT / "artifacts/meshy_downloads/h3_angel_smartrigged_rigidized.glb",
    "h3_hobgoblin": ROOT / "artifacts/meshy_downloads/h3_hobgoblin_smartrigged_rigidized.glb",
    "h3_crusader": ROOT / "artifacts/meshy_downloads/h3_crusader_smartrigged_rigidized.glb",
    "h3_roc": ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb",
}

CLIPS = (
    {
        "label": "angel_move",
        "unit_sid": "h3_angel",
        "animation": "idle_start_move_end",
        "title": "Angel movement (idle_start_move_end)",
    },
    {
        "label": "hobgoblin_attack",
        "unit_sid": "h3_hobgoblin",
        "animation": "idle_attack_front",
        "title": "Hobgoblin attack (idle_attack_front)",
    },
    {
        "label": "crusader_death",
        "unit_sid": "h3_crusader",
        "animation": "idle_death",
        "title": "Crusader death (idle_death)",
    },
    {
        "label": "roc_move",
        "unit_sid": "h3_roc",
        "animation": "move",
        "title": "Roc movement (DEF group 0)",
    },
)

ARMS = (
    {
        "id": "control",
        "title": "control (1-bone walk)",
        "chain_space_enabled": False,
        "chain_space_mode": "chain_grad",
        "articulated_iterations": 1,
    },
    {
        "id": "chain_grad",
        "title": "chain_grad (equal-share limb)",
        "chain_space_enabled": True,
        "chain_space_mode": "chain_grad",
        "articulated_iterations": 0,
    },
    {
        "id": "branch_trust",
        "title": "branch_trust (disjoint radius)",
        "chain_space_enabled": True,
        "chain_space_mode": "branch_trust",
        "articulated_iterations": 0,
    },
    {
        "id": "layer_surface",
        "title": "layer_surface (next joint)",
        "chain_space_enabled": True,
        "chain_space_mode": "layer_surface",
        "articulated_iterations": 0,
    },
)

# Keep uses this blend as absolute geometry. Occupancy motion (appear /
# disappear match) is the largest term so a limb that swings with the
# sprite can beat a pose that only covers the still blob. Pixel fill
# stays in the mix so the mesh cannot drift off the sprite. Delivery
# keep refuses motion_weight != 0.
GEOMETRY_AUTHORITY = {
    "score_mode": "geometry",
    "motion_weight": 1.00,
    "depth_weight": 0.25,
    "silhouette_weight": 0.20,
    "chroma_weight": 0.20,
    "collision_enabled": True,
    "collision_weight": 0.35,
}

SHARED_EXPERIMENT = {
    "sa_enabled": False,
    "gradient_ladder_enabled": False,
    "ik_enabled": False,
    # Neighbor-pose copy after per-frame keep (not magnitude damping).
    # Keep-or-zero occupancy-motion finish leaves intentional travel at
    # full strength and zeros travel that does not explain the occupancy
    # pairs this frame actually changes, or that makes a neighboring pair
    # worse. Clip-mean 1e-6 is not the gate.
    "physics_smooth_enabled": False,
    "joint_temporal_consensus_enabled": True,
    "sprite_aligned_motion_keep_enabled": True,
    "sprite_aligned_motion_keep_min_improvement": SPRITE_ALIGNED_KEEP_MIN_IMPROVEMENT,
    "live_preview": False,
    "chain_space_iterations": 2,
    "chain_space_step_degs": (5.0, 10.0, 20.0, 40.0),
    "fine_iterations": 0,
    "base_pose_enabled": False,
    "mid_pose_enabled": False,
    "branch_rescue_enabled": False,
}


def _geometry_authority_matches(config: Mapping[str, Any]) -> bool:
    if str(config.get("score_mode") or "") != str(GEOMETRY_AUTHORITY["score_mode"]):
        return False
    if bool(config.get("collision_enabled")) != bool(GEOMETRY_AUTHORITY["collision_enabled"]):
        return False
    for name in (
        "motion_weight",
        "depth_weight",
        "silhouette_weight",
        "chroma_weight",
        "collision_weight",
    ):
        got = config.get(name)
        if got is None:
            return False
        if abs(float(got) - float(GEOMETRY_AUTHORITY[name])) > 1e-12:
            return False
    return True


def _finish_knobs_match(config: Mapping[str, Any]) -> bool:
    extra = config.get("sprite_aligned_motion_keep_min_improvement")
    if extra is None:
        return False
    return (
        bool(config.get("joint_temporal_consensus_enabled")) is True
        and bool(config.get("physics_smooth_enabled")) is False
        and bool(config.get("sprite_aligned_motion_keep_enabled")) is True
        and abs(float(extra) - float(SPRITE_ALIGNED_KEEP_MIN_IMPROVEMENT)) <= 1e-12
    )


def _control_search_eval_budget(payload: Mapping[str, Any]) -> int:
    """Chain-space budget is control search evals, not the shared finish pass.

    Occupancy keep-or-zero runs after every arm. Counting those rasters in
    ``chain_space_eval_budget`` forces extra surface steps that control never
    spent on search.
    """
    total = int(payload["evaluationCount"])
    report = payload.get("spriteAlignedMotionKeep")
    if not isinstance(report, Mapping):
        raise RuntimeError("control payload is missing spriteAlignedMotionKeep")
    if not bool(report.get("enabled")):
        raise RuntimeError("control sprite-aligned keep was disabled")
    finish = int(report.get("evaluations") or 0)
    if finish < 0 or finish >= total:
        raise RuntimeError(
            f"control finish evals={finish} are not a strict subset of evals={total}"
        )
    return total - finish


def _mean(values: Sequence[float] | None) -> float | None:
    if not values:
        return None
    return float(sum(float(value) for value in values) / len(values))


def _filter_fit_kwargs(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    allowed = set(inspect.signature(run_gpu_depth_fit_from_hybrid_config).parameters)
    allowed.discard("config")
    allowed.discard("output_dir")
    unknown = sorted(set(kwargs) - allowed)
    if unknown:
        raise RuntimeError("GPU fit kwargs are not adapter parameters: " + ", ".join(unknown))
    return {name: kwargs[name] for name in kwargs if name in allowed}


def _build_isolated_move_choice(widgets, *, unit_sid: str):
    """Build a group-0-only Move choice. Idle stays a sibling profile plate."""
    from dataclasses import replace

    from materialize_rife_source_frames import (
        def_sequence_animation_name,
        def_sequence_choice_id,
        inventory_authentic_def_groups,
    )

    donors = [
        choice
        for choice in widgets.discover_asset_choices(ROOT)
        if choice.unit_sid == unit_sid
        and choice.source_kind == "authentic_def"
        and 0 in (choice.present_groups or ())
        and choice.def_lab_frame_dir is not None
    ]
    if not donors:
        raise RuntimeError(f"{unit_sid}: no authentic DEF inventory contains Move group 0")
    donor = donors[0]
    inventory = inventory_authentic_def_groups(Path(donor.def_lab_frame_dir))
    if 0 not in inventory or not inventory[0]:
        raise RuntimeError(f"{unit_sid}: DEF group 0 is missing from {donor.def_lab_frame_dir}")
    frames = tuple(inventory[0])
    animation = def_sequence_animation_name((0,))
    runtime_dir, camera_fit = widgets._runtime_paths(ROOT, unit_sid, animation)
    return replace(
        donor,
        animation_name=animation,
        choice_id=def_sequence_choice_id(unit_sid, (0,)),
        pilot_dir=runtime_dir,
        camera_fit=camera_fit,
        frame_indices=tuple(range(len(frames))),
        source_frames=frames,
        def_lab_groups=(0,),
        def_expected_counts=(len(frames),),
        sequence_kind="motion_only",
    )


def _select_choice(widgets, *, unit_sid: str, animation: str):
    matches = [
        choice
        for choice in widgets.discover_asset_choices(ROOT)
        if choice.unit_sid == unit_sid
        and choice.animation_name == animation
        and choice.source_kind == "authentic_def"
    ]
    if animation == "move" and not matches:
        return _build_isolated_move_choice(widgets, unit_sid=unit_sid)
    if len(matches) != 1:
        available = sorted(
            {
                f"{choice.unit_sid}:{choice.animation_name}"
                for choice in widgets.discover_asset_choices(ROOT)
                if choice.unit_sid == unit_sid and choice.source_kind == "authentic_def"
            }
        )
        raise RuntimeError(
            f"expected one authentic DEF {unit_sid}:{animation}, found {len(matches)}; "
            f"available={available}"
        )
    return matches[0]


def _release_gpu() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _arm_dir(clip_root: Path, arm_id: str) -> Path:
    return Path(clip_root) / str(arm_id)


def _result_complete(
    out_dir: Path,
    arm: Mapping[str, Any],
    *,
    eval_budget: int | None = None,
) -> bool:
    clip = out_dir / "gpu_clip_result.json"
    rgb = out_dir / "solved_rgb" / "00.png"
    if not clip.is_file() or not rgb.is_file():
        return False
    payload = json.loads(clip.read_text(encoding="utf-8"))
    config = payload.get("config")
    if not isinstance(config, Mapping):
        return False
    enabled = bool(config.get("chain_space_enabled"))
    mode = str(config.get("chain_space_mode") or "")
    want_enabled = bool(arm["chain_space_enabled"])
    if enabled != want_enabled:
        return False
    if want_enabled and mode != str(arm["chain_space_mode"]):
        return False
    if int(config.get("articulated_iterations", -1)) != int(arm["articulated_iterations"]):
        return False
    if not _geometry_authority_matches(config):
        return False
    if not _finish_knobs_match(config):
        return False
    if clip_result_matches_current_keep(payload):
        raise RuntimeError(f"{out_dir} unexpectedly matches CURRENT_CASCADE_KEEP")
    if want_enabled and eval_budget is not None:
        recorded_budget = config.get("chain_space_eval_budget")
        if recorded_budget is None or int(recorded_budget) != int(eval_budget):
            return False
        if int(payload.get("evaluationCount") or 0) < int(eval_budget):
            return False
    return True


def _sprite_dir(choice) -> Path:
    return Path(choice.pilot_dir) / f"frames_def12_nn_{choice.animation_name}_shadow_culled"


def _load_font(size: int):
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_cell(im: Image.Image, size: tuple[int, int], bg=(18, 18, 22)) -> Image.Image:
    cell = Image.new("RGB", size, bg)
    work = im.convert("RGBA")
    scale = min(size[0] / work.width, size[1] / work.height)
    width = max(1, int(work.width * scale))
    height = max(1, int(work.height * scale))
    resized = work.resize(
        (width, height),
        Image.Resampling.NEAREST if scale >= 2 else Image.Resampling.LANCZOS,
    )
    x = (size[0] - width) // 2
    y = (size[1] - height) // 2
    cell.paste(resized, (x, y), resized)
    return cell


def _find_frame(folder: Path, index: int) -> Path | None:
    stem = f"{index:02d}"
    for cand in (
        folder / f"{stem}.png",
        folder / f"mesh_{stem}.png",
        folder / "solved_rgb" / f"{stem}.png",
    ):
        if cand.is_file():
            return cand
    return None


def write_panel_grid(
    *,
    out_path: Path,
    title: str,
    sprite_dir: Path,
    arm_dirs: list[tuple[str, Path]],
    frame_count: int,
    scores: Mapping[str, Sequence[float] | None],
    motion_scores: Mapping[str, Sequence[float] | None] | None = None,
    iou_scores: Mapping[str, Sequence[float] | None] | None = None,
    cell_w: int = 236,
    cell_h: int = 250,
) -> Path:
    font = _load_font(16)
    font_sm = _load_font(13)
    font_title = _load_font(20)
    columns = [("sprite", sprite_dir), *arm_dirs]
    header_h = 36
    title_h = 44
    canvas_w = len(columns) * cell_w
    canvas_h = title_h + frame_count * (header_h + cell_h)
    canvas = Image.new("RGB", (canvas_w, canvas_h), (10, 10, 14))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, canvas_w, title_h - 1], fill=(24, 24, 32))
    draw.text((12, 10), title, fill=(235, 235, 240), font=font_title)
    for col, (label, folder) in enumerate(columns):
        x0 = col * cell_w
        frame_scores = scores.get(label)
        for frame in range(frame_count):
            y0 = title_h + frame * (header_h + cell_h)
            draw.rectangle(
                [x0, y0, x0 + cell_w - 1, y0 + header_h - 1],
                fill=(32, 32, 42),
            )
            caption = f"{label}  f{frame:02d}"
            motion_row = None if motion_scores is None else motion_scores.get(label)
            iou_row = None if iou_scores is None else iou_scores.get(label)
            extras: list[str] = []
            if motion_row is not None and frame < len(motion_row):
                extras.append(f"mot={float(motion_row[frame]):.3f}")
            if iou_row is not None and frame < len(iou_row):
                extras.append(f"iou={float(iou_row[frame]):.3f}")
            if not extras and frame_scores is not None and frame < len(frame_scores):
                extras.append(f"{float(frame_scores[frame]):.3f}")
            if extras:
                caption = f"{label}  f{frame:02d}  " + "  ".join(extras)
            draw.text((x0 + 8, y0 + 8), caption, fill=(230, 230, 235), font=font_sm)
            src = _find_frame(Path(folder), frame)
            if src is None:
                cell = Image.new("RGB", (cell_w, cell_h), (48, 20, 20))
                ImageDraw.Draw(cell).text(
                    (12, 12), f"missing f{frame:02d}", fill=(255, 120, 120), font=font
                )
            else:
                cell = _fit_cell(Image.open(src), (cell_w, cell_h))
            canvas.paste(cell, (x0, y0 + header_h))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return out_path


def compose_clip_gif(
    *,
    clip_root: Path,
    sprite_dir: Path,
    frame_count: int,
    arms: Sequence[Mapping[str, Any]] | None = None,
) -> Path:
    from compose_method_compare_gif import main as compose_main

    selected = list(ARMS if arms is None else arms)
    gif = Path(clip_root) / "chain_space_compare.gif"
    argv = [
        "--out",
        str(gif),
        "--cols",
        str(1 + len(selected)),
        "--cell-w",
        "240",
        "--cell-h",
        "280",
        "--hold",
        "2",
        "--frame-count",
        str(int(frame_count)),
        "--panel",
        "sprite",
        str(sprite_dir),
    ]
    for arm in selected:
        argv.extend(["--panel", arm["id"], str(_arm_dir(clip_root, arm["id"]) / "solved_rgb")])
    old = sys.argv
    try:
        sys.argv = ["compose_method_compare_gif.py", *argv]
        code = compose_main()
    finally:
        sys.argv = old
    if int(code) != 0:
        raise RuntimeError("compare GIF compose failed")
    return gif


def _prepare_choice_config(choice, mesh: Path, notebook: Path):
    from roc_semantic_hybrid_experiment import RocHybridConfig

    notebook_kwargs = _literal_config_kwargs(notebook, require_dino=False)
    config = _notebook_config(RocHybridConfig, notebook_kwargs, notebook=notebook)
    overrides = _choice_overrides(choice, mesh)
    report_path = overrides.get("meshy_rigidization_report")
    if report_path is None:
        # Owned bind masters have no Meshy rigidization report. Do not require one.
        overrides["require_meshy_rigidization"] = False
    else:
        report_payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
        report_output = Path(str(report_payload.get("output") or "")).resolve()
        if report_output != mesh.resolve():
            overrides["meshy_rigidization_report"] = None
            overrides["require_meshy_rigidization"] = False
    config = replace(config, **overrides)
    return prepare_gpu_targets(config)


def fit_arm(
    *,
    config,
    gpu_kwargs: dict[str, Any],
    arm: Mapping[str, Any],
    dest: Path,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    dest.mkdir(parents=True, exist_ok=True)
    kwargs = {
        **gpu_kwargs,
        **GEOMETRY_AUTHORITY,
        **SHARED_EXPERIMENT,
        "chain_space_enabled": bool(arm["chain_space_enabled"]),
        "chain_space_mode": str(arm["chain_space_mode"]),
        "articulated_iterations": int(arm["articulated_iterations"]),
        **(extra or {}),
    }
    if bool(arm["chain_space_enabled"]) and int(arm["articulated_iterations"]) != 0:
        raise RuntimeError("chain-space arms must set articulated_iterations=0")
    solved = run_gpu_depth_fit_from_hybrid_config(config, output_dir=dest, **kwargs)
    payload = json.loads(Path(solved.pose_result["clipResultPath"]).read_text(encoding="utf-8"))
    recorded = payload.get("config") or {}
    if bool(recorded.get("chain_space_enabled")) != bool(arm["chain_space_enabled"]):
        raise RuntimeError(
            f"{dest} recorded chain_space_enabled={recorded.get('chain_space_enabled')!r}"
        )
    if bool(arm["chain_space_enabled"]):
        if str(recorded.get("chain_space_mode")) != str(arm["chain_space_mode"]):
            raise RuntimeError(
                f"{dest} recorded chain_space_mode={recorded.get('chain_space_mode')!r}"
            )
    if clip_result_matches_current_keep(payload):
        raise RuntimeError(f"{dest} matched CURRENT_CASCADE_KEEP")
    if str(recorded.get("score_mode") or "") != "geometry":
        raise RuntimeError(f"{dest} recorded score_mode={recorded.get('score_mode')!r}")
    if not _geometry_authority_matches(recorded):
        raise RuntimeError(f"{dest} recorded geometry weights do not match the motion-led mix")
    if not _finish_knobs_match(recorded):
        raise RuntimeError(
            f"{dest} recorded finish knobs are not consensus+local-pair keep"
        )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--compose-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--matched-budget",
        action="store_true",
        help=(
            "Spend about as many clip evaluations as control on each chain arm. "
            "Writes to chain_space_surface_compare_motion_aligned_tight_matched_budget unless --out is set."
        ),
    )
    parser.add_argument(
        "--clip",
        action="append",
        dest="clips",
        help="Restrict to clip labels (angel_move, hobgoblin_attack, crusader_death, roc_move)",
    )
    parser.add_argument(
        "--arm",
        action="append",
        dest="arms",
        help="Restrict to arm ids (control, chain_grad, branch_trust, layer_surface)",
    )
    parser.add_argument(
        "--mesh",
        type=Path,
        help="Override the unit mesh (use for an owned bind master; do not reuse smartrig control).",
    )
    args = parser.parse_args()
    wanted = set(args.clips) if args.clips else {row["label"] for row in CLIPS}
    unknown = sorted(wanted - {row["label"] for row in CLIPS})
    if unknown:
        raise RuntimeError(f"unknown --clip labels: {unknown}")
    selected_arms = list(ARMS)
    if args.arms:
        wanted_arms = set(args.arms)
        unknown_arms = sorted(wanted_arms - {arm["id"] for arm in ARMS})
        if unknown_arms:
            raise RuntimeError(f"unknown --arm ids: {unknown_arms}")
        selected_arms = [arm for arm in ARMS if arm["id"] in wanted_arms]
        if not selected_arms:
            raise RuntimeError("no chain-space arms selected")
        if args.matched_budget and not any(not arm["chain_space_enabled"] for arm in selected_arms):
            raise RuntimeError("--matched-budget requires the control arm")
    if args.matched_budget and Path(args.out).resolve() == DEFAULT_OUT.resolve():
        args.out = MATCHED_OUT

    import roc_semantic_hybrid_widgets as widgets
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    _ = run_gpu_depth_fit_from_hybrid_config
    gpu_kwargs = _filter_fit_kwargs(notebook_gpu_fit_kwargs(args.notebook))
    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    plan = {
        "proof": "generated experiment candidate; not delivery validated",
        "geometryAuthority": GEOMETRY_AUTHORITY,
        "shared": SHARED_EXPERIMENT,
        "arms": list(selected_arms),
        "clips": [row for row in CLIPS if row["label"] in wanted],
        "out": str(out_root).replace("\\", "/"),
        "modes": list(CHAIN_SPACE_MODES),
        "matchedBudget": bool(args.matched_budget),
        "motionLed": True,
        "meshOverride": None if args.mesh is None else str(Path(args.mesh).resolve()).replace("\\", "/"),
        "matchedChainSpaceIterations": (
            MATCHED_CHAIN_SPACE_ITERATIONS if args.matched_budget else None
        ),
    }
    (out_root / "compare_plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(plan, indent=2), flush=True)
    if args.dry_run:
        return 0

    lock_path = (
        None
        if args.compose_only
        else acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
    )
    try:
        for spec in CLIPS:
            if spec["label"] not in wanted:
                continue
            mesh = Path(args.mesh).resolve() if args.mesh is not None else MESH_BY_UNIT[spec["unit_sid"]]
            if not mesh.is_file():
                raise FileNotFoundError(mesh)
            if args.mesh is not None and len(wanted) != 1:
                raise RuntimeError("--mesh requires exactly one --clip so the override cannot hit the wrong unit")
            choice = _select_choice(
                widgets, unit_sid=spec["unit_sid"], animation=spec["animation"]
            )
            clip_root = out_root / spec["label"]
            clip_root.mkdir(parents=True, exist_ok=True)
            sprite_dir = _sprite_dir(choice)
            if not args.compose_only:
                config = _prepare_choice_config(choice, mesh, args.notebook)
                expected = sum(int(count) for count in choice.def_expected_counts)
                if len(config.frame_indices) != expected:
                    raise RuntimeError(
                        f"{spec['label']} materialized {len(config.frame_indices)} frames, "
                        f"expected {expected}"
                    )
                if args.matched_budget and args.mesh is None:
                    cheap_control = DEFAULT_OUT / spec["label"] / "control"
                    dest_control = clip_root / "control"
                    cheap_result = cheap_control / "gpu_clip_result.json"
                    if (
                        cheap_control.is_dir()
                        and cheap_result.is_file()
                        and not (dest_control / "gpu_clip_result.json").is_file()
                    ):
                        cheap_payload = json.loads(cheap_result.read_text(encoding="utf-8"))
                        cheap_config = cheap_payload.get("config") or {}
                        if (
                            isinstance(cheap_config, Mapping)
                            and _geometry_authority_matches(cheap_config)
                            and _finish_knobs_match(cheap_config)
                        ):
                            shutil.copytree(cheap_control, dest_control)
                            print(
                                f"copy control {cheap_control} -> {dest_control}",
                                flush=True,
                            )
                        else:
                            print(
                                f"skip copy {cheap_control}: finish knobs are not "
                                "consensus+local-pair keep",
                                flush=True,
                            )
                control_evals: int | None = None
                search_budget: int | None = None
                for arm in selected_arms:
                    dest = _arm_dir(clip_root, arm["id"])
                    extra: dict[str, Any] = {}
                    is_control = not bool(arm["chain_space_enabled"])
                    if args.matched_budget and is_control and _result_complete(dest, arm):
                        payload = json.loads(
                            (dest / "gpu_clip_result.json").read_text(encoding="utf-8")
                        )
                        control_evals = int(payload["evaluationCount"])
                        search_budget = _control_search_eval_budget(payload)
                        print(
                            f"reuse {spec['label']}/{arm['id']} evals={control_evals} "
                            f"searchBudget={search_budget}: {dest}",
                            flush=True,
                        )
                        continue
                    if args.matched_budget and not is_control:
                        if control_evals is None or search_budget is None:
                            raise RuntimeError(
                                f"{spec['label']}: control must finish first so the "
                                "raster budget exists"
                            )
                        extra = {
                            "chain_space_eval_budget": int(search_budget),
                            "chain_space_iterations": MATCHED_CHAIN_SPACE_ITERATIONS,
                        }
                        if _result_complete(
                            dest, arm, eval_budget=int(search_budget)
                        ):
                            print(
                                f"reuse {spec['label']}/{arm['id']} "
                                f"searchBudget={search_budget}: {dest}",
                                flush=True,
                            )
                            continue
                    if args.skip_existing and _result_complete(
                        dest, arm, eval_budget=extra.get("chain_space_eval_budget")
                    ):
                        print(f"reuse {spec['label']}/{arm['id']}: {dest}", flush=True)
                        if is_control:
                            payload = json.loads(
                                (dest / "gpu_clip_result.json").read_text(encoding="utf-8")
                            )
                            control_evals = int(payload["evaluationCount"])
                            search_budget = _control_search_eval_budget(payload)
                        continue
                    started = time.perf_counter()
                    print(
                        f"fit {spec['label']}/{arm['id']} frames={len(config.frame_indices)} "
                        f"out={dest}"
                        + (
                            f" budget={search_budget}"
                            if extra.get("chain_space_eval_budget") is not None
                            else ""
                        ),
                        flush=True,
                    )
                    try:
                        payload = fit_arm(
                            config=config,
                            gpu_kwargs=gpu_kwargs,
                            arm=arm,
                            dest=dest,
                            extra=extra,
                        )
                        print(
                            f"fitted {spec['label']}/{arm['id']} "
                            f"score={payload.get('score')} "
                            f"evals={payload.get('evaluationCount')} "
                            f"elapsed={time.perf_counter() - started:.1f}s",
                            flush=True,
                        )
                    finally:
                        _release_gpu()
                    if is_control:
                        control_evals = int(payload["evaluationCount"])
                        search_budget = _control_search_eval_budget(payload)
                    elif args.matched_budget:
                        got = int(payload["evaluationCount"])
                        recorded = (payload.get("config") or {}).get(
                            "chain_space_eval_budget"
                        )
                        if recorded is None or int(recorded) != int(search_budget):
                            raise RuntimeError(
                                f"{spec['label']}/{arm['id']} recorded "
                                f"chain_space_eval_budget={recorded!r}, "
                                f"expected search budget {search_budget}"
                            )
                        if got < int(search_budget):
                            raise RuntimeError(
                                f"{spec['label']}/{arm['id']} evals={got} "
                                f"below search budget {search_budget}"
                            )

            scores: dict[str, list[float] | None] = {"sprite": None}
            motion_scores: dict[str, list[float] | None] = {"sprite": None}
            iou_scores: dict[str, list[float] | None] = {"sprite": None}
            frame_count = None
            arm_dirs: list[tuple[str, Path]] = []
            summary_rows = []
            for arm in selected_arms:
                dest = _arm_dir(clip_root, arm["id"])
                payload = json.loads((dest / "gpu_clip_result.json").read_text(encoding="utf-8"))
                if not _geometry_authority_matches(payload.get("config") or {}) or not _finish_knobs_match(
                    payload.get("config") or {}
                ):
                    raise RuntimeError(
                        f"{dest} is not a motion-led sprite-aligned result; "
                        "refusing to compose a mixed compare"
                    )
                frame_scores = [float(value) for value in payload.get("frameScores") or []]
                frame_motion = [float(value) for value in payload.get("frameMotionQuality") or []]
                frame_iou = [float(value) for value in payload.get("frameIoU") or []]
                if frame_motion and len(frame_motion) != len(frame_scores):
                    raise RuntimeError(
                        f"{spec['label']}/{arm['id']} motion frames={len(frame_motion)} "
                        f"score frames={len(frame_scores)}"
                    )
                if frame_iou and len(frame_iou) != len(frame_scores):
                    raise RuntimeError(
                        f"{spec['label']}/{arm['id']} iou frames={len(frame_iou)} "
                        f"score frames={len(frame_scores)}"
                    )
                scores[arm["id"]] = frame_scores
                motion_scores[arm["id"]] = frame_motion or None
                iou_scores[arm["id"]] = frame_iou or None
                arm_dirs.append((arm["id"], dest / "solved_rgb"))
                if frame_count is None:
                    frame_count = len(frame_scores)
                elif len(frame_scores) != frame_count:
                    raise RuntimeError(
                        f"{spec['label']}/{arm['id']} has {len(frame_scores)} frames, "
                        f"expected {frame_count}"
                    )
                summary_rows.append(
                    {
                        "arm": arm["id"],
                        "score": payload.get("score"),
                        "meanMotionQuality": _mean(frame_motion),
                        "meanIoU": _mean(frame_iou),
                        "evaluationCount": payload.get("evaluationCount"),
                        "elapsed": payload.get("elapsed"),
                        "chain_space_enabled": (payload.get("config") or {}).get(
                            "chain_space_enabled"
                        ),
                        "chain_space_mode": (payload.get("config") or {}).get("chain_space_mode"),
                    }
                )
            if frame_count is None:
                raise RuntimeError(f"{spec['label']} has no fitted arms")
            png = write_panel_grid(
                out_path=clip_root / "chain_space_panel_grid.png",
                title=f"{spec['title']} · motion-led · sprite-aligned keep",
                sprite_dir=sprite_dir,
                arm_dirs=arm_dirs,
                frame_count=int(frame_count),
                scores=scores,
                motion_scores=motion_scores,
                iou_scores=iou_scores,
            )
            gif = compose_clip_gif(
                clip_root=clip_root,
                sprite_dir=sprite_dir,
                frame_count=int(frame_count),
                arms=selected_arms,
            )
            report = {
                "clip": spec,
                "frames": int(frame_count),
                "arms": summary_rows,
                "panelGrid": str(png).replace("\\", "/"),
                "compareGif": str(gif).replace("\\", "/"),
                "proof": "generated experiment candidate; not delivery validated",
                "objective": "occupancy motion leads pixel fill; consensus then sprite-aligned keep/zero; CURRENT_CASCADE_KEEP closed",
            }
            (clip_root / "compare_report.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
            print(json.dumps(report, indent=2), flush=True)
    finally:
        if lock_path is not None:
            release_cascade_batch_lock(lock_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
