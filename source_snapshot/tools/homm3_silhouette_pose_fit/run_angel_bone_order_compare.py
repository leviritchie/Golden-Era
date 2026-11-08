#!/usr/bin/env python3
"""Fit angel move with every cascade bone-order mode and compose one grid GIF.

Notebook GPU knobs are reused except:
- ``bone_order_mode`` (the compared variable)
- ``base_pose_enabled=True`` so visit order actually runs
- ``sa_seed=0`` so SA does not become a second hidden variable
"""
from __future__ import annotations

import argparse
import ast
import gc
import inspect
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
ANGEL_MESH = ROOT / "artifacts/meshy_downloads/h3_angel_smartrigged_rigidized.glb"
DEFAULT_OUT = (
    ROOT / "artifacts/pose_picker_runs/h3_angel/idle_start_move_end/bone_order_compare"
)

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (  # noqa: E402
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from cascade_bone_order import CASCADE_BONE_ORDER_MODES  # noqa: E402
from run_crusader_full_animation_set import (  # noqa: E402
    _literal_config_kwargs,
    _notebook_config,
)
from run_crusader_gpu_cascade_animation_set import (  # noqa: E402
    NOTEBOOK_FIT_ASSIGNMENTS,
    _choice_overrides,
    prepare_gpu_targets,
)


LABELS = {
    "asset": "asset",
    "dependency": "dependency",
    "error_driven": "error_driven",
    "gradient_magnitude": "grad_mag",
    "expected_gain": "expected_gain",
    "temporal_disagreement": "temporal",
    "screen_space_leverage": "leverage",
    "error_leverage": "error_lev",
}


def _notebook_gpu_kwargs(notebook: Path) -> dict[str, Any]:
    payload = json.loads(Path(notebook).read_text(encoding="utf-8"))
    wanted = set(NOTEBOOK_FIT_ASSIGNMENTS)
    found: dict[str, Any] = {}
    for cell in payload.get("cells", []):
        source = "".join(cell.get("source", []))
        if "CASCADE_BONE_ORDER_MODE" not in source and "SIMPLE_DEPTH_DEPTH_WEIGHT" not in source:
            continue
        tree = ast.parse(source, filename=str(notebook))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name) or target.id not in wanted:
                    continue
                try:
                    found[target.id] = ast.literal_eval(node.value)
                except (ValueError, TypeError) as exc:
                    raise RuntimeError(
                        f"notebook assignment {target.id} is not a literal"
                    ) from exc
    missing_core = [
        name
        for name in (
            "CASCADE_BONE_ORDER_MODE",
            "CASCADE_SA_ENABLED",
            "CASCADE_BASE_POSE_ENABLED",
            "SIMPLE_DEPTH_CHROMA_WEIGHT",
        )
        if name not in found
    ]
    if missing_core:
        raise RuntimeError("notebook is missing GPU cascade literals: " + ", ".join(missing_core))
    return {
        NOTEBOOK_FIT_ASSIGNMENTS[name]: value
        for name, value in found.items()
    }


def _filter_fit_kwargs(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    allowed = set(inspect.signature(run_gpu_depth_fit_from_hybrid_config).parameters)
    allowed.discard("config")
    allowed.discard("output_dir")
    unknown = sorted(set(kwargs) - allowed)
    if unknown:
        raise RuntimeError("GPU fit kwargs are not adapter parameters: " + ", ".join(unknown))
    return {name: kwargs[name] for name in kwargs if name in allowed}


def _select_angel_move(widgets):
    matches = [
        choice
        for choice in widgets.discover_asset_choices(ROOT)
        if choice.unit_sid == "h3_angel"
        and choice.animation_name == "idle_start_move_end"
        and choice.source_kind == "authentic_def"
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one angel idle_start_move_end authentic DEF choice, found {len(matches)}"
        )
    return matches[0]


def _mode_dir(out_root: Path, mode: str) -> Path:
    return Path(out_root) / str(mode)


def _result_complete(out_dir: Path, mode: str) -> bool:
    clip = out_dir / "gpu_clip_result.json"
    rgb = out_dir / "solved_rgb" / "00.png"
    if not clip.is_file() or not rgb.is_file():
        return False
    payload = json.loads(clip.read_text(encoding="utf-8"))
    config = payload.get("config")
    if not isinstance(config, Mapping):
        return False
    recorded = str(config.get("bone_order_mode") or config.get("boneOrderMode") or "")
    return recorded == str(mode)


def _release_gpu() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def compose_compare_gif(*, out_root: Path, sprite_dir: Path, frame_count: int) -> Path:
    from compose_method_compare_gif import main as compose_main

    gif = Path(out_root) / "angel_move_bone_order_compare.gif"
    argv = [
        "--out",
        str(gif),
        "--cols",
        "3",
        "--cell-w",
        "260",
        "--cell-h",
        "300",
        "--hold",
        "2",
        "--frame-count",
        str(int(frame_count)),
        "--panel",
        "sprite",
        str(sprite_dir),
    ]
    for mode in CASCADE_BONE_ORDER_MODES:
        argv.extend(["--panel", LABELS[mode], str(_mode_dir(out_root, mode) / "solved_rgb")])
    old = sys.argv
    try:
        sys.argv = ["compose_method_compare_gif.py", *argv]
        code = compose_main()
    finally:
        sys.argv = old
    if int(code) != 0:
        raise RuntimeError("compare GIF compose failed")
    return gif


def _main_locked() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK)
    parser.add_argument("--mesh", type=Path, default=ANGEL_MESH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--compose-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    mesh = Path(args.mesh).resolve()
    if mesh != ANGEL_MESH.resolve():
        raise RuntimeError(f"angel compare is locked to {ANGEL_MESH}")
    if not mesh.is_file():
        raise FileNotFoundError(mesh)

    import roc_semantic_hybrid_widgets as widgets
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config
    from roc_semantic_hybrid_experiment import RocHybridConfig

    choice = _select_angel_move(widgets)
    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    notebook_kwargs = _literal_config_kwargs(args.notebook, require_dino=False)
    gpu_kwargs = _filter_fit_kwargs(_notebook_gpu_kwargs(args.notebook))
    gpu_kwargs["base_pose_enabled"] = True
    gpu_kwargs["sa_seed"] = 0
    gpu_kwargs["live_preview"] = False

    plan = {
        "unit": choice.unit_sid,
        "animation": choice.animation_name,
        "groups": list(choice.def_lab_groups),
        "counts": list(choice.def_expected_counts),
        "frames": len(choice.frame_indices),
        "modes": list(CASCADE_BONE_ORDER_MODES),
        "overrides": {
            "base_pose_enabled": True,
            "sa_seed": 0,
            "reason": "bone order only affects the discrete base/mid/rescue walk; SA seed pins the shared random stage",
        },
        "notebookSaEnabled": gpu_kwargs.get("sa_enabled"),
        "notebookBaseEnabled": False,
        "mesh": str(mesh).replace("\\", "/"),
        "out": str(out_root).replace("\\", "/"),
    }
    (out_root / "compare_plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(plan, indent=2), flush=True)
    if args.dry_run:
        return 0

    sprite_dir = Path(choice.pilot_dir) / f"frames_def12_nn_{choice.animation_name}_shadow_culled"
    if args.compose_only:
        gif = compose_compare_gif(
            out_root=out_root,
            sprite_dir=sprite_dir,
            frame_count=sum(int(count) for count in choice.def_expected_counts),
        )
        print(f"composed {gif}", flush=True)
        return 0

    config = _notebook_config(RocHybridConfig, notebook_kwargs, notebook=args.notebook)
    overrides = _choice_overrides(choice, mesh)
    report_path = overrides.get("meshy_rigidization_report")
    if report_path is not None:
        report_payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
        report_output = Path(str(report_payload.get("output") or "")).resolve()
        if report_output != mesh:
            # The Meshy folder keeps one shared report for the last audited unit.
            # Do not attach a griffin/other report to the angel GLB.
            overrides["meshy_rigidization_report"] = None
            overrides["require_meshy_rigidization"] = False
    config = replace(config, **overrides)
    config = prepare_gpu_targets(config)
    if len(config.frame_indices) != sum(int(count) for count in choice.def_expected_counts):
        raise RuntimeError(
            f"angel move materialized {len(config.frame_indices)} frames, "
            f"expected {sum(int(count) for count in choice.def_expected_counts)}"
        )

    for mode in CASCADE_BONE_ORDER_MODES:
        dest = _mode_dir(out_root, mode)
        if args.skip_existing and _result_complete(dest, mode):
            print(f"reuse {mode}: {dest}", flush=True)
            continue
        started = time.perf_counter()
        print(f"fit {mode} frames={len(config.frame_indices)} out={dest}", flush=True)
        try:
            solved = run_gpu_depth_fit_from_hybrid_config(
                config,
                output_dir=dest,
                **{**gpu_kwargs, "bone_order_mode": mode},
            )
            payload = json.loads(Path(solved.pose_result["clipResultPath"]).read_text(encoding="utf-8"))
            recorded = str((payload.get("config") or {}).get("bone_order_mode") or "")
            if recorded != mode:
                raise RuntimeError(f"{dest} recorded bone_order_mode={recorded!r}, not {mode!r}")
            print(
                f"fitted {mode} score={payload.get('score')} "
                f"elapsed={time.perf_counter() - started:.1f}s",
                flush=True,
            )
        finally:
            _release_gpu()

    gif = compose_compare_gif(
        out_root=out_root,
        sprite_dir=sprite_dir,
        frame_count=len(config.frame_indices),
    )
    print(f"composed {gif}", flush=True)
    return 0


def main() -> int:
    lock_path = global_cascade_batch_lock_path(ROOT)
    acquire_cascade_batch_lock(lock_path)
    try:
        return _main_locked()
    finally:
        release_cascade_batch_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
