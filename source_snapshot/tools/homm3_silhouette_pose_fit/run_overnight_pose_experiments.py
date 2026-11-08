"""Run isolated overnight ablations of the semantic clip pose solver.

This is intentionally a script rather than a notebook cell.  The parent
process schedules one variant at a time; each variant runs in a fresh Python
process so Hugging Face models and Blender workers are released before the
next ablation starts.  Every variant gets its own pilot directory and writes
its own renders, poses, timing data, and side-by-side previews.

The suite is a measurement harness, not an automatic winner selector.  The
objective is only directly comparable between variants with the same enabled
terms and weights.  Human inspection of the generated GIFs remains required.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from PIL import Image


ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL_DIR = ROOT / "tools/homm3_silhouette_pose_fit"
BASE_PILOT = ROOT / "artifacts/roc_pose_pipeline/smart_rig_move_pilot"
SRC_GLB = Path(r"C:/Users/<user>/Downloads/griffon_smart_rigged.glb")
FRAME_INDICES = (0, 1, 2, 3, 4, 5)
FRAME_DURATION_MS = 180
FPS = 60


def _jsonable(value: Any) -> Any:
    """Convert paths, numpy scalars, and nested records to JSON values."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _jsonable(item())
        except Exception:
            pass
    return str(value)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _base_config(variant_dir: Path) -> dict[str, Any]:
    """Return the clean control condition shared by all ablations."""
    return {
        "root": ROOT,
        "src_glb": SRC_GLB,
        "unit_name": "roc",
        "animation_name": "move_g0",
        "pilot_dir": variant_dir,
        "camera_fit_path": BASE_PILOT / "roc_sprite_camera_fit.json",
        # Absolute paths keep the source frames immutable while each variant
        # owns all generated match/export files under its own directory.
        "target_frame_dir": BASE_PILOT / "frames_ground_truth",
        "shadow_culled_frame_dir": BASE_PILOT / "frames_ground_truth_shadow_culled",
        "target_depth_dir": BASE_PILOT / "frames_ground_truth_depth_vda",
        "score_mode": "depth",
        "semantic_only": True,
        "semantic_enabled": True,
        "semantic_model_id": "google/siglip2-base-patch16-512",
        "semantic_embedding_layers": ("projected",),
        "semantic_batch_size": 1,
        "semantic_subject_crop": False,
        "semantic_dense_enabled": True,
        "semantic_dense_model_id": "google/siglip2-base-patch16-512",
        "semantic_dense_embedding_layers": ("last",),
        "semantic_dense_weight": 0.75,
        "semantic_dense_position_weight": 0.15,
        "hybrid_semantic_weight": 0.25,
        "hybrid_geometry_enabled": False,
        "hybrid_geometry_weight": 0.0,
        "render_depth_for_scoring": False,
        "render_lighting_mode": "flat_emission",
        "render_sun_energy": 2.0,
        "render_sun_azimuth_deg": -35.0,
        "render_sun_elevation_deg": 55.0,
        "render_sun_angle_deg": 5.0,
        "semantic_multiview": False,
        "triage_enabled": True,
        "triage_silhouette_enabled": True,
        "triage_silhouette_floor": 0.02,
        "triage_silhouette_keep_fraction": 0.25,
        "triage_silhouette_min_candidates": 2,
        "triage_silhouette_max_candidates": 2,
        "live_preview": False,
        "preview_every": 1,
        "run_frame0_pilot": False,
        "frame_indices": FRAME_INDICES,
        "seed_from_previous": True,
        # These are the current mesh/profile settings, not the old chroma
        # pipeline.  They are held fixed unless an ablation names them.
        "mesh_scale": 1.25,
        "search_scale": 1.0,
        "search_axes": ("x", "y", "z"),
        "exclude_bone_roll": True,
        "skip_tiny_bones": True,
        "bone_order_mode": "branch_walk",
        "branch_walk_camera_bias": "none",
        "multi_axis_mode": "compound",
        "near_bone_refinement_enabled": True,
        "near_bone_refinement_step_deg": 1.0,
        "ik_enabled": False,
        "ik_mode": "off",
        "semantic_text_enabled": False,
        "semantic_negative_text_enabled": False,
        "anatomical_boxes_enabled": False,
        "show_anatomical_boxes": False,
        "reverse_profile_enabled": False,
        "mesh_orientation_mode": "none",
        "clip_optimization_enabled": True,
        "clip_warm_start": "previous",
        "clip_rounds": 1,
        "clip_refine_rounds": 1,
        "clip_refine_accepted_only": True,
        "clip_velocity_weight": 0.08,
        "clip_acceleration_weight": 0.04,
        "clip_contact_weight": 0.0,
        "clip_loop_weight": 0.0,
        "clip_loop_velocity_weight": 0.0,
        "clip_loop_enabled": False,
        "clip_robust_scale_deg": 16.0,
        "clip_coarse_step_deg": 16.0,
        "clip_refine_step_deg": 4.0,
        "clip_max_evaluations_per_axis": 3,
        "clip_candidate_mode": "range_extremes",
        "clip_acceptance_margin": 0.001,
        "clip_acceptance_relative_margin": 0.0,
        "clip_preview_candidates": False,
        "clip_batch_candidates": True,
        "parallel_candidate_rendering": True,
        "render_worker_count": 4,
    }


def _variant_specs() -> list[dict[str, Any]]:
    """Return the ordered ablations for one unattended suite."""
    return [
        {
            "name": "01_control_global_dense",
            "purpose": "Current semantic+dense control with batched four-worker rendering.",
            "overrides": {},
        },
        {
            "name": "02_global_only",
            "purpose": "Global SigLIP2 only; measures whether dense tokens earn their cost.",
            "overrides": {
                "semantic_dense_enabled": False,
                "semantic_dense_weight": 0.0,
                "hybrid_semantic_weight": 1.0,
            },
        },
        {
            "name": "03_dense_only",
            "purpose": "Dense SigLIP2 only; tests whether spatial features can carry the fit.",
            "overrides": {
                "hybrid_semantic_weight": 0.0,
                "semantic_dense_weight": 1.0,
            },
        },
        {
            "name": "04_global_dense_multiview",
            "purpose": "Three semantic candidate views; tests view robustness against extra encoder work.",
            "overrides": {
                "semantic_multiview": True,
            },
        },
        {
            "name": "05_global_dense_sun_above",
            "purpose": "Above-sun Eevee lighting; tests whether sprite-like lighting improves semantic signal.",
            "overrides": {
                "render_lighting_mode": "sun_above",
            },
        },
        {
            "name": "05b_dinov3_dense_only",
            "purpose": "Gated DINOv3 dense features only; compares spatial correspondence quality against SigLIP2.",
            "overrides": {
                "hybrid_semantic_weight": 0.0,
                "semantic_dense_weight": 1.0,
                "semantic_dense_model_id": "facebook/dinov3-vits16-pretrain-lvd1689m",
                "semantic_dense_embedding_layers": ("last",),
            },
        },
        {
            "name": "06_semantic_depth_hybrid",
            "purpose": "Global+dense semantic plus predicted-depth geometry.",
            "overrides": {
                "hybrid_semantic_weight": 0.25,
                "semantic_dense_weight": 0.50,
                "hybrid_geometry_enabled": True,
                "hybrid_geometry_weight": 0.25,
                "render_depth_for_scoring": True,
            },
        },
        {
            "name": "07_no_silhouette_triage",
            "purpose": "Control without cheap silhouette pruning; measures triage speed and quality impact.",
            "overrides": {
                "triage_enabled": False,
                "triage_silhouette_enabled": False,
            },
        },
        {
            "name": "08_local_clip_proposals",
            "purpose": "Local clip proposals; tests whether smaller moves reduce wasted Blender renders.",
            "overrides": {
                "clip_candidate_mode": "local",
                "clip_coarse_step_deg": 12.0,
                "clip_refine_step_deg": 4.0,
            },
        },
        {
            "name": "09_strong_temporal_regularization",
            "purpose": "Stronger velocity/acceleration plus loop seam penalties for motion coherence.",
            "overrides": {
                "clip_velocity_weight": 0.16,
                "clip_acceleration_weight": 0.08,
                "clip_loop_enabled": True,
                "clip_loop_weight": 0.03,
                "clip_loop_velocity_weight": 0.01,
            },
        },
        {
            "name": "10_bind_warm_start",
            "purpose": "Skip per-frame warm-start solves; measures startup cost versus global recovery.",
            "overrides": {
                "clip_warm_start": "bind",
            },
        },
        {
            "name": "11_single_blender_worker",
            "purpose": "Control with one persistent Blender worker; measures parallel render scaling.",
            "overrides": {
                "render_worker_count": 1,
                "parallel_candidate_rendering": False,
            },
        },
    ]


def _flatten_rgb(path: Path) -> Image.Image:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    background.alpha_composite(rgba)
    return background.convert("RGB")


def _write_timed_mp4(
    frame_paths: list[Path],
    out_path: Path,
    *,
    fps: int,
    frame_duration_ms: int,
) -> str | None:
    """Write a real-time 60 fps movie by holding each source frame."""
    try:
        import cv2

        if not frame_paths:
            return None
        first = cv2.imread(str(frame_paths[0]))
        if first is None:
            raise RuntimeError(f"could not read {frame_paths[0]}")
        height, width = first.shape[:2]
        writer = cv2.VideoWriter(
            str(out_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            int(fps),
            (int(width), int(height)),
        )
        if not writer.isOpened():
            raise RuntimeError("OpenCV could not open the MP4 writer")
        repeats = max(1, round(int(fps) * int(frame_duration_ms) / 1000.0))
        try:
            for frame_path in frame_paths:
                frame = cv2.imread(str(frame_path))
                if frame is None:
                    raise RuntimeError(f"could not read {frame_path}")
                for _ in range(repeats):
                    writer.write(frame)
        finally:
            writer.release()
        return str(out_path)
    except Exception as exc:
        print(f"timed MP4 unavailable: {exc}", flush=True)
        return None


def _compose_side_by_side(
    *,
    target_dir: Path,
    mesh_frame_paths: list[Path],
    frames: list[int],
    out_dir: Path,
) -> dict[str, Any]:
    """Create a target/render GIF and a correctly timed side-by-side MP4."""
    side_dir = out_dir / "side_by_side_frames"
    side_dir.mkdir(parents=True, exist_ok=True)
    side_paths: list[Path] = []
    for frame, mesh_path in zip(frames, mesh_frame_paths):
        target_path = target_dir / f"{int(frame):02d}.png"
        if not target_path.is_file():
            raise FileNotFoundError(f"target frame missing for side-by-side export: {target_path}")
        target = _flatten_rgb(target_path)
        mesh = _flatten_rgb(mesh_path)
        height = max(target.height, mesh.height)
        canvas = Image.new("RGB", (target.width + mesh.width, height), "black")
        canvas.paste(target, (0, 0))
        canvas.paste(mesh, (target.width, 0))
        path = side_dir / f"frame_{int(frame):02d}.png"
        canvas.save(path, format="PNG")
        canvas.close()
        target.close()
        mesh.close()
        side_paths.append(path)

    gif_path = out_dir / "target_mesh_side_by_side.gif"
    images = [Image.open(path).convert("RGB") for path in side_paths]
    try:
        images[0].save(
            gif_path,
            save_all=True,
            append_images=images[1:],
            duration=FRAME_DURATION_MS,
            loop=0,
            optimize=False,
        )
    finally:
        for image in images:
            image.close()
    mp4_path = _write_timed_mp4(
        side_paths,
        out_dir / "target_mesh_side_by_side_60fps.mp4",
        fps=FPS,
        frame_duration_ms=FRAME_DURATION_MS,
    )
    return {
        "gif": str(gif_path),
        "mp4": mp4_path,
        "frames": [str(path) for path in side_paths],
    }


def _run_variant(
    *,
    spec: Mapping[str, Any],
    run_dir: Path,
    smoke: bool = False,
) -> int:
    """Run one variant in the current child process."""
    name = str(spec["name"])
    variant_dir = run_dir / name
    variant_dir.mkdir(parents=True, exist_ok=True)
    config_values = _base_config(variant_dir)
    config_values.update(dict(spec.get("overrides") or {}))
    if smoke:
        config_values.update(
            {
                "frame_indices": (0,),
                "clip_rounds": 1,
                "clip_refine_rounds": 1,
                "clip_max_evaluations_per_axis": 1,
                "clip_candidate_mode": "local",
                "clip_warm_start": "bind",
                "render_worker_count": 1,
                "parallel_candidate_rendering": False,
            }
        )

    config_path = variant_dir / "config.json"
    _write_json(
        config_path,
        {
            "name": name,
            "purpose": spec.get("purpose"),
            "smoke": smoke,
            "config": config_values,
        },
    )
    result_path = variant_dir / "result_summary.json"
    started = time.perf_counter()
    experiment = None
    try:
        sys.path.insert(0, str(TOOL_DIR))
        from roc_semantic_hybrid_experiment import (
            RocHybridConfig,
            export_clip_result,
            initialize,
            run_clip_pilot,
        )

        config = RocHybridConfig(**config_values)
        experiment = initialize(config)
        result = run_clip_pilot(experiment)
        export_dir = variant_dir / "export"
        export = export_clip_result(
            experiment,
            output_dir=export_dir,
            frame_duration_ms=FRAME_DURATION_MS,
            fps=FPS,
        )
        frames = [int(frame) for frame in result["config"]["frameIndices"]]
        side_by_side = _compose_side_by_side(
            target_dir=Path(config_values["shadow_culled_frame_dir"]),
            mesh_frame_paths=[Path(path) for path in export["framePaths"]],
            frames=frames,
            out_dir=variant_dir / "export",
        )
        frame_scores = [float(value) for value in result.get("frameScores", {}).values()]
        details = result.get("objectiveDetails") or {}
        summary = {
            "ok": True,
            "name": name,
            "purpose": spec.get("purpose"),
            "elapsedSeconds": float(time.perf_counter() - started),
            "optimizerElapsedSeconds": float(result.get("elapsed", 0.0)),
            "evaluations": int(result.get("evaluations", 0)),
            "accepted": int(result.get("accepted", 0)),
            "meanFrameScore": sum(frame_scores) / len(frame_scores) if frame_scores else 0.0,
            "frameScores": result.get("frameScores", {}),
            "objective": result.get("objective"),
            "objectiveDetails": details,
            "optimizerConfig": result.get("config", {}),
            "export": export,
            "sideBySide": side_by_side,
            "configPath": str(config_path),
        }
        _write_json(result_path, summary)
        print(
            f"DONE {name}: objective={float(result['objective']):.6f} "
            f"meanFrame={summary['meanFrameScore']:.6f} "
            f"evals={summary['evaluations']} accepted={summary['accepted']} "
            f"elapsed={summary['optimizerElapsedSeconds']:.2f}s",
            flush=True,
        )
        return 0
    except Exception as exc:
        failure = {
            "ok": False,
            "name": name,
            "purpose": spec.get("purpose"),
            "elapsedSeconds": float(time.perf_counter() - started),
            "error": repr(exc),
            "traceback": traceback.format_exc(),
            "configPath": str(config_path),
        }
        _write_json(result_path, failure)
        print(f"FAILED {name}: {exc!r}", flush=True)
        traceback.print_exc()
        return 1
    finally:
        if experiment is not None:
            try:
                experiment.close()
            except Exception:
                traceback.print_exc()


def _run_suite(
    *,
    run_dir: Path,
    only: set[str] | None,
    timeout_minutes: float,
) -> int:
    specs = [spec for spec in _variant_specs() if not only or spec["name"] in only]
    if not specs:
        raise ValueError("no experiment variants selected")
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        run_dir / "suite_manifest.json",
        {
            "created": datetime.now().isoformat(timespec="seconds"),
            "root": ROOT,
            "sourceMesh": SRC_GLB,
            "sourceFrames": BASE_PILOT / "frames_ground_truth_shadow_culled",
            "frameIndices": FRAME_INDICES,
            "frameDurationMs": FRAME_DURATION_MS,
            "fps": FPS,
            "linkNote": "The user-provided shared ChatGPT link was not retrievable in this environment.",
            "variants": specs,
        },
    )
    statuses: list[dict[str, Any]] = []
    for index, spec in enumerate(specs, start=1):
        name = str(spec["name"])
        log_path = run_dir / f"{name}.log"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--variant",
            name,
            "--run-dir",
            str(run_dir),
        ]
        print(f"START {index}/{len(specs)} {name}", flush=True)
        started = time.perf_counter()
        with log_path.open("w", encoding="utf-8") as log:
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(ROOT),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=None if timeout_minutes <= 0 else timeout_minutes * 60.0,
                    check=False,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                )
                return_code = int(completed.returncode)
                timed_out = False
            except subprocess.TimeoutExpired:
                return_code = 124
                timed_out = True
                log.write("\nSUITE TIMEOUT: child exceeded configured timeout.\n")
        result_path = run_dir / name / "result_summary.json"
        result = {}
        if result_path.is_file():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except Exception as exc:
                result = {"ok": False, "error": f"could not read result: {exc!r}"}
        status = {
            "name": name,
            "returnCode": return_code,
            "timedOut": timed_out,
            "elapsedSeconds": time.perf_counter() - started,
            "log": str(log_path),
            "result": result,
        }
        statuses.append(status)
        _write_json(run_dir / "suite_status.json", statuses)
        print(
            f"END {name}: rc={return_code} timeout={timed_out} "
            f"elapsed={status['elapsedSeconds']:.2f}s",
            flush=True,
        )

    rows = []
    for status in statuses:
        result = status.get("result") or {}
        if result.get("ok"):
            rows.append(
                {
                    "name": status["name"],
                    "ok": True,
                    "objective": result.get("objective"),
                    "meanFrameScore": result.get("meanFrameScore"),
                    "optimizerElapsedSeconds": result.get("optimizerElapsedSeconds"),
                    "evaluations": result.get("evaluations"),
                    "accepted": result.get("accepted"),
                    "sideBySideGif": (result.get("sideBySide") or {}).get("gif"),
                    "sideBySideMp4": (result.get("sideBySide") or {}).get("mp4"),
                }
            )
        else:
            rows.append(
                {
                    "name": status["name"],
                    "ok": False,
                    "error": (result or {}).get("error", "no result summary"),
                }
            )
    successful = [row for row in rows if row.get("ok")]
    leaderboard = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "note": "Scores are not comparable across variants that change objective weights; use matching ablations and inspect GIFs.",
        "rowsByObjective": sorted(
            successful,
            key=lambda row: float(row.get("objective") or float("-inf")),
            reverse=True,
        ),
        "rowsByElapsed": sorted(
            successful,
            key=lambda row: float(row.get("optimizerElapsedSeconds") or float("inf")),
        ),
        "all": rows,
    }
    _write_json(run_dir / "leaderboard.json", leaderboard)
    return 0 if all(row.get("ok") for row in rows) else 1


def _wait_for_processes(pids: list[int], *, poll_seconds: int = 30) -> None:
    """Wait for a captured set of existing processes without touching them."""
    def is_alive(pid: int) -> bool:
        if os.name == "nt":
            import ctypes

            process_query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information,
                False,
                int(pid),
            )
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            try:
                ok = ctypes.windll.kernel32.GetExitCodeProcess(
                    handle,
                    ctypes.byref(exit_code),
                )
                # STILL_ACTIVE is 259 on Windows.
                return bool(ok) and int(exit_code.value) == 259
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError, OSError):
            return False
        return True

    remaining = {int(pid) for pid in pids if int(pid) > 0}
    if not remaining:
        return
    print(f"waiting for existing processes before GPU work: {sorted(remaining)}", flush=True)
    while remaining:
        alive: set[int] = set()
        for pid in remaining:
            if is_alive(pid):
                alive.add(pid)
        remaining = alive
        if remaining:
            print(f"still active: {sorted(remaining)}", flush=True)
            time.sleep(int(poll_seconds))
    print("existing processes released", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, help="suite artifact directory")
    parser.add_argument("--variant", help="run one named variant in child mode")
    parser.add_argument("--only", nargs="*", help="limit suite to named variants")
    parser.add_argument(
        "--timeout-minutes",
        type=float,
        default=180.0,
        help="per-variant timeout; <=0 disables it",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="run the selected child with one frame and one local proposal per axis",
    )
    parser.add_argument(
        "--wait-for-pids",
        nargs="*",
        type=int,
        default=(),
        help="wait for these already-running process IDs before starting the suite",
    )
    args = parser.parse_args()

    if args.run_dir is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = BASE_PILOT / f"overnight_pose_experiments_{stamp}"
    else:
        run_dir = args.run_dir.resolve()

    if args.variant:
        specs = {str(spec["name"]): spec for spec in _variant_specs()}
        if args.variant not in specs:
            raise SystemExit(f"unknown variant: {args.variant}")
        return _run_variant(spec=specs[args.variant], run_dir=run_dir, smoke=args.smoke)

    _wait_for_processes(list(args.wait_for_pids))
    only = set(args.only or ())
    return _run_suite(
        run_dir=run_dir,
        only=only or None,
        timeout_minutes=float(args.timeout_minutes),
    )


if __name__ == "__main__":
    raise SystemExit(main())
