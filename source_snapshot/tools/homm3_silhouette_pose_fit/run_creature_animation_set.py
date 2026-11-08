#!/usr/bin/env python3
"""Fit a complete discovered creature animation set with one notebook config.

This is the generic batch entry point.  It uses the same picker inventory and
``RocHybridConfig`` execution path as the pilot, but processes every selected
unit/animation choice and reuses the Blender worker pool while the selected
mesh remains unchanged.  Fit-only is the default scalable first pass; review
rendering is explicitly opt-in.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL_DIR = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL_DIR / "roc_chromatic_single_bone_match.ipynb"
DEFAULT_OUT = ROOT / "artifacts/full_creature_animation_set"
DEFAULT_MESH_ROOT = ROOT / "artifacts/meshy_downloads"
CANONICAL_COVERAGE = ROOT / "artifacts/meshy_downloads/homm3_mesh_coverage.json"

if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from run_crusader_full_animation_set import (  # noqa: E402
    DEFAULT_FPS,
    SOURCE_FPS,
    SAMPLES_PER_INTERVAL,
    _config_call_source,
    _clip_input_fingerprint,
    _ensure_hf_token,
    _group_id,
    _json_safe,
    _load_sparse_pose_result,
    _literal_config_kwargs,
    _load_existing_comparison_frames,
    _load_runtime_modules,
    _materialize_choice_for_run,
    _notebook_config,
    _render_clip,
    _sha256,
)


def _dino_enabled(notebook: Path) -> bool:
    source = notebook.read_text(encoding="utf-8")
    return bool(
        re.search(r"^\s*USE_DINOV3_DENSE\s*=\s*True\b", source, flags=re.MULTILINE)
    )


def _choice_matches(choice, unit: str, animation: str | None) -> bool:
    unit_value = str(unit).strip().lower()
    if unit_value not in {"", "all", "*"}:
        if unit_value not in {
            str(choice.unit_name).strip().lower(),
            str(choice.unit_sid).strip().lower(),
        }:
            return False
    if animation:
        requested = {part.strip().lower() for part in animation.split(",") if part.strip()}
        if requested and str(choice.animation_name).strip().lower() not in requested:
            return False
    return True


_CANONICAL_SMARTRIG_PATHS: set[Path] | None = None


def _canonical_smartrig_paths() -> set[Path]:
    """Load authoritative canonical paths; filenames alone are not proof."""

    global _CANONICAL_SMARTRIG_PATHS
    if _CANONICAL_SMARTRIG_PATHS is not None:
        return _CANONICAL_SMARTRIG_PATHS
    paths: set[Path] = set()
    try:
        payload = json.loads(CANONICAL_COVERAGE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _CANONICAL_SMARTRIG_PATHS = paths
        return paths
    for record in payload.get("records", []):
        if not isinstance(record, dict) or record.get("status") != "smartrig_present":
            continue
        raw = record.get("smartrig") or record.get("mesh")
        if raw:
            paths.add(Path(str(raw)).expanduser().resolve())
    _CANONICAL_SMARTRIG_PATHS = paths
    return paths


def _selected_choices(widgets, *, unit: str, animation: str | None, limit: int):
    choices = [
        choice
        for choice in widgets.discover_asset_choices(ROOT)
        if _choice_matches(choice, unit, animation)
    ]
    choices.sort(key=lambda choice: (str(choice.unit_sid), str(choice.animation_name), str(choice.choice_id)))
    if limit:
        choices = choices[: int(limit)]
    if not choices:
        raise RuntimeError(
            f"asset picker returned no choices for unit={unit!r} animation={animation!r}"
        )
    return choices


def _mesh_audit(widgets, mesh: Path, *, allow_unverified: bool):
    status, report = widgets.meshy_rigidization_status(mesh)
    # Custom Astra/Blender candidates also use the ``*_smartrigged.glb``
    # suffix.  Only exact paths from the canonical coverage manifest receive
    # the downloaded-SmartRig exemption.
    is_meshy_smart_rig = mesh.expanduser().resolve() in _canonical_smartrig_paths()
    if status != "pass" and is_meshy_smart_rig:
        # The downloaded Meshy smart-rig is itself an authoritative armature
        # input. A passing rigidization report is required only when the
        # selected file is a post-rigidization derivative.
        status = "meshy_smart_rig"
        report = None
    if status not in {"pass", "meshy_smart_rig"} and not allow_unverified:
        raise RuntimeError(
            "selected mesh is not covered by a passing Meshy rigidization audit: "
            f"mesh={mesh} status={status} report={report}. "
            "Use --allow-unverified-mesh only for an explicit diagnostic run."
        )
    report_payload = None
    if report is not None and report.is_file():
        try:
            report_payload = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            report_payload = None
    return status, report, report_payload


def _resolve_mesh(choice, args: argparse.Namespace) -> Path | None:
    if args.mesh is not None:
        return Path(args.mesh).expanduser().resolve()
    if args.use_picker_mesh:
        return None if choice.default_mesh is None else Path(choice.default_mesh).expanduser().resolve()
    root = Path(args.mesh_root).expanduser().resolve()
    exact = root / f"{choice.unit_sid}_smartrigged.glb"
    if exact.is_file():
        return exact
    candidates = sorted(root.glob(f"{choice.unit_sid}_*_smartrigged.glb"))
    if len(candidates) == 1:
        return candidates[0].resolve()
    if len(candidates) > 1:
        raise RuntimeError(
            f"mesh-root has ambiguous Meshy files for {choice.unit_sid}: "
            + ", ".join(str(path.name) for path in candidates)
        )
    if choice.default_mesh is not None:
        # The deterministic Meshy naming convention is preferred, but legacy
        # and custom pipeline inventories may already carry the authoritative
        # mesh next to their source frames.
        return Path(choice.default_mesh).expanduser().resolve()
    return None


def _config_for_choice(
    base,
    choice,
    runtime_dir: Path,
    camera_fit: Path,
    mesh: Path,
    report: Path | None,
    audited: bool,
    *,
    def_nn_upscale_meta: Path | None = None,
):
    updates: dict[str, Any] = {
        "src_glb": mesh,
        "meshy_rigidization_report": report,
        "require_meshy_rigidization": bool(audited),
        "unit_name": str(choice.unit_name),
        "animation_name": str(choice.animation_name),
        "pilot_dir": runtime_dir,
        "camera_fit_path": camera_fit,
        "frame_indices": tuple(choice.frame_indices),
        "match_dir_name": f"full_{choice.unit_sid}_semantic",
    }
    if choice.source_kind == "authentic_def":
        if choice.def_lab_frame_dir is None or not choice.def_lab_groups:
            raise RuntimeError(f"authentic DEF choice is missing source groups: {choice.choice_id}")
        updates.update(
            {
                "def_lab_frame_dir": Path(choice.def_lab_frame_dir),
                "def_lab_group": tuple(int(group) for group in choice.def_lab_groups),
                "def_expected_count": tuple(int(count) for count in choice.def_expected_counts),
                "def_nn_upscale_meta": def_nn_upscale_meta,
                "rife_lab_frame_dir": None,
                "rife_lab_group": None,
                "rife_expected_count": None,
                "target_frame_dir": "frames_def12_nn",
                "shadow_culled_frame_dir": "frames_def12_nn_shadow_culled",
                "target_depth_dir": "frames_def12_nn_depth_vda",
            }
        )
    return replace(base, **updates)


def _clip_output_dir(out_root: Path, choice) -> Path:
    return out_root / "units" / str(choice.unit_sid) / "animations" / str(choice.animation_name)


def _cleanup_clip_tmp(clip_dir: Path) -> None:
    """Remove only the clip-local transient semantic scratch directory.

    ``clip_dir`` is the materialized picker/runtime directory, not the final
    pose-artifact directory; the GPU evaluator writes its candidate images
    beside the source plates under this path.
    """
    tmp_dir = clip_dir / "tmp"
    is_junction = getattr(os.path, "isjunction", None)
    if not tmp_dir.is_dir() or tmp_dir.is_symlink():
        return
    # A Windows directory junction is a reparse point but is not necessarily
    # reported as a symlink; never recurse through one as if it were scratch.
    if is_junction is not None and is_junction(tmp_dir):
        return
    if tmp_dir.is_dir():
        shutil.rmtree(tmp_dir)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--settings-override",
        choices=("custom", "smoke", "draft", "fast", "balanced", "high", "full"),
        default=None,
        help=(
            "override the notebook search budget explicitly; omit to honor its "
            "SETTINGS_OVERRIDE declaration"
        ),
    )
    parser.add_argument("--unit", default="all", help="unit SID/name, or all (default)")
    parser.add_argument(
        "--animation",
        default=None,
        help="exact animation name or comma-separated names; omit for every discovered animation",
    )
    mesh_group = parser.add_mutually_exclusive_group()
    mesh_group.add_argument("--mesh", type=Path, default=None, help="override the mesh for every selected choice")
    mesh_group.add_argument("--mesh-root", type=Path, default=DEFAULT_MESH_ROOT, help="directory containing <unit>_smartrigged.glb files")
    mesh_group.add_argument("--use-picker-mesh", action="store_true", help="use each picker choice's default mesh instead of artifacts/meshy_downloads")
    parser.add_argument("--limit", type=int, default=0, help="run only the first N choices; 0 means all")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--fit-only", action="store_true", help="fit sparse original frames without review rendering")
    mode_group.add_argument("--review", action="store_true", help="fit and render the interpolated 60 fps review")
    mode_group.add_argument("--review-only", action="store_true", help="render existing clip_poses_sparse.json artifacts without rerunning the optimizer")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--method", choices=("euler_linear", "quaternion_slerp", "quaternion_smoothstep"), default="quaternion_smoothstep")
    parser.add_argument("--no-persistent-blender-workers", action="store_true")
    parser.add_argument(
        "--allow-unverified-mesh",
        action="store_true",
        help="diagnostic opt-in that permits a selected mesh without a passing rigidization report",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.fit_only and not args.review and not args.review_only:
        args.fit_only = True
    if args.fps != DEFAULT_FPS:
        raise ValueError(f"this lane is defined at {DEFAULT_FPS} fps")
    notebook = args.notebook.resolve()
    out_root = args.out.resolve()
    if not notebook.is_file():
        raise FileNotFoundError(notebook)

    RocHybridConfig, initialize, run_clip_pilot, widgets, interpolate_clip, write_pose_artifact = _load_runtime_modules()
    base_kwargs = _literal_config_kwargs(notebook, require_dino=False)
    base = _notebook_config(RocHybridConfig, base_kwargs, notebook=notebook)
    if _dino_enabled(notebook):
        _ensure_hf_token()
    from roc_semantic_hybrid_settings_presets import (
        describe_settings_override,
        parse_settings_override_assignment,
    )

    notebook_settings_override = parse_settings_override_assignment(_config_call_source(notebook))
    settings_override = (
        notebook_settings_override if args.settings_override is None else str(args.settings_override)
    )
    from roc_semantic_hybrid_settings_presets import apply_settings_override

    base = apply_settings_override(base, settings_override)
    choices = _selected_choices(
        widgets,
        unit=args.unit,
        animation=args.animation,
        limit=args.limit,
    )
    resolved_meshes: dict[str, Path | None] = {}
    missing_meshes: list[str] = []
    for choice in choices:
        mesh = _resolve_mesh(choice, args)
        resolved_meshes[str(choice.choice_id)] = mesh
        if mesh is None or not mesh.is_file():
            missing_meshes.append(
                f"{choice.choice_id} -> {mesh or 'no mesh mapping'}"
            )

    print("Notebook config:", notebook)
    print("Notebook sha256:", _sha256(notebook))
    print(
        "Settings override:",
        settings_override,
        f"({describe_settings_override(settings_override)})",
    )
    print("Selected choices:", len(choices))
    print(
        "Run mode:",
        "fit-only" if args.fit_only else "review-only" if args.review_only else "review",
    )
    for choice in choices:
        mesh = resolved_meshes[str(choice.choice_id)]
        print(
            json.dumps(
                {
                    "choice": choice.choice_id,
                    "unit": choice.unit_sid,
                    "animation": choice.animation_name,
                    "sourceFrames": len(choice.frame_indices),
                    "mesh": None if mesh is None else str(mesh),
                    "source": choice.source_label,
                },
                default=str,
            )
        )
    if args.dry_run:
        return 0
    if missing_meshes:
        raise RuntimeError(
            "mesh preflight failed before any Blender worker was started:\n"
            + "\n".join(missing_meshes[:24])
            + (f"\n... and {len(missing_meshes) - 24} more" if len(missing_meshes) > 24 else "")
        )

    out_root.mkdir(parents=True, exist_ok=True)
    run_manifest_path = out_root / "run_manifest.json"
    notebook_sha = _sha256(notebook)
    run_manifest: dict[str, Any] = {
        "status": "running",
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "notebook": str(notebook),
        "notebookSha256": notebook_sha,
        "sourceInventory": "picker-discovered original VCMI/DEF frames; no RIFE interpolation",
        "sourceFps": SOURCE_FPS,
        "outputFps": SOURCE_FPS if args.fit_only else args.fps,
        "interpolationApplied": not args.fit_only,
        "interpolationMethod": None if args.fit_only else args.method,
        "samplesPerInterval": 1 if args.fit_only else SAMPLES_PER_INTERVAL,
        "runMode": "fit_only" if args.fit_only else "review_only" if args.review_only else "review",
        "reviewFramesRetained": not args.fit_only,
        "reviewOnly": bool(args.review_only),
        "persistentBlenderWorkers": not args.no_persistent_blender_workers,
        "config": _json_safe(asdict(base)),
        "selectedChoiceCount": len(choices),
        "selectedChoiceIds": [str(choice.choice_id) for choice in choices],
        "clips": [],
    }
    run_manifest_path.write_text(json.dumps(_json_safe(run_manifest), indent=2) + "\n", encoding="utf-8")

    global_frames = [] if not args.fit_only else None
    experiment = None
    persistent_worker_pool = None
    pool_mesh: Path | None = None
    current_runtime_dir: Path | None = None
    try:
        for index, choice in enumerate(choices, 1):
            clip_dir = _clip_output_dir(out_root, choice)
            clip_manifest_path = clip_dir / "clip_manifest.json"
            runtime_dir, camera_fit, source_manifest = _materialize_choice_for_run(widgets, choice)
            current_runtime_dir = runtime_dir
            def_nn_upscale_meta = source_manifest if choice.source_kind == "authentic_def" else None
            mesh = resolved_meshes[str(choice.choice_id)]
            if mesh is None:
                raise RuntimeError(
                    f"no deterministic mesh mapping for {choice.choice_id}; "
                    "supply --mesh or a matching --mesh-root"
                )
            mesh = Path(mesh).expanduser().resolve()
            if not mesh.is_file():
                raise FileNotFoundError(f"selected mesh does not exist: {mesh}")
            audit_status, report, report_payload = _mesh_audit(
                widgets,
                mesh,
                allow_unverified=args.allow_unverified_mesh,
            )
            config = _config_for_choice(
                base,
                choice,
                runtime_dir,
                camera_fit,
                mesh,
                report,
                audit_status == "pass",
                def_nn_upscale_meta=(
                    def_nn_upscale_meta if choice.source_kind == "authentic_def" else None
                ),
            )
            input_fingerprint = _clip_input_fingerprint(
                unit_name=str(choice.unit_sid),
                animation_name=str(choice.animation_name),
                mesh=mesh,
                pilot_dir=runtime_dir,
                camera_fit=camera_fit,
                config=config,
            )
            if not args.no_resume and clip_manifest_path.is_file():
                try:
                    existing = json.loads(clip_manifest_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    existing = None
                expected_mode = "fit_only" if args.fit_only else "interpolated"
                ready = (
                    isinstance(existing, dict)
                    and existing.get("status") == "complete"
                    and existing.get("reviewMode") == expected_mode
                    and existing.get("notebookSha256") == notebook_sha
                    and existing.get("inputFingerprint") == input_fingerprint
                    and Path(str(existing.get("poseArtifact", ""))).is_file()
                    and (args.fit_only or Path(str(existing.get("mp4", ""))).is_file())
                )
                if ready:
                    print(f"[{index}/{len(choices)}] {choice.choice_id}: reusing completed clip", flush=True)
                    run_manifest["clips"].append(existing)
                    # A prior interrupted run may have left evaluator scratch
                    # beside an otherwise reusable clip; remove only that
                    # transient directory before continuing.
                    try:
                        _cleanup_clip_tmp(runtime_dir)
                    except OSError as cleanup_error:
                        print(
                            f"warning: transient cleanup failed for {clip_dir}: {cleanup_error}",
                            flush=True,
                        )
                    if global_frames is not None:
                        global_frames.extend(_load_existing_comparison_frames(existing))
                    continue

            if pool_mesh is not None and pool_mesh != mesh:
                if persistent_worker_pool is not None:
                    persistent_worker_pool.close()
                persistent_worker_pool = None
                pool_mesh = None
            started = time.perf_counter()
            experiment = initialize(
                config,
                persistent_worker_pool=(
                    None if args.no_persistent_blender_workers else persistent_worker_pool
                ),
            )
            if not args.no_persistent_blender_workers and persistent_worker_pool is None:
                persistent_worker_pool = experiment.namespace.get("worker_pool")
                if persistent_worker_pool is None:
                    raise RuntimeError("initialized experiment did not expose a Blender worker pool")
                pool_mesh = mesh
                experiment.namespace["worker_pool_owned"] = False
            try:
                result = (
                    _load_sparse_pose_result(clip_dir / "clip_poses_sparse.json")
                    if args.review_only
                    else run_clip_pilot(experiment)
                )
                clip_summary = _render_clip(
                    experiment=experiment,
                    result=result,
                    choice=choice,
                    out_dir=clip_dir,
                    method=args.method,
                    fps=args.fps,
                    interpolate_clip=interpolate_clip,
                    write_pose_artifact=write_pose_artifact,
                    global_frames=global_frames,
                    fit_only=args.fit_only,
                    mesh_path=mesh,
                    unit_name=str(choice.unit_sid),
                )
            finally:
                experiment.close()
                experiment = None
            clip_summary.update(
                {
                    "status": "complete",
                    "elapsedSeconds": round(time.perf_counter() - started, 3),
                    "mesh": str(mesh),
                    "meshSha256": _sha256(mesh),
                    "meshAuditStatus": audit_status,
                    "meshAuditReport": None if report is None else str(report),
                    "meshAudit": _json_safe(report_payload),
                    "notebookSha256": notebook_sha,
                    "sourceManifest": str(source_manifest),
                    "cameraFit": str(camera_fit),
                    "inputFingerprint": input_fingerprint,
                    "reviewOnly": bool(args.review_only),
                }
            )
            clip_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            clip_manifest_path.write_text(json.dumps(_json_safe(clip_summary), indent=2) + "\n", encoding="utf-8")
            run_manifest["clips"].append(clip_summary)
            run_manifest_path.write_text(json.dumps(_json_safe(run_manifest), indent=2) + "\n", encoding="utf-8")
            try:
                _cleanup_clip_tmp(runtime_dir)
            except OSError as cleanup_error:
                print(
                    f"warning: transient cleanup failed for {clip_dir}: {cleanup_error}",
                    flush=True,
                )
            print(
                f"[{index}/{len(choices)}] {choice.choice_id}: complete in "
                f"{clip_summary['elapsedSeconds']:.1f}s -> "
                f"{clip_summary.get('mp4') or clip_summary['poseArtifact']}",
                flush=True,
            )

        run_manifest.update(
            {
                "status": "complete",
                "completedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "fittedClipCount": len(run_manifest["clips"]),
            }
        )
        if global_frames is not None:
            if not global_frames:
                raise RuntimeError("no clips were rendered; cannot assemble final review video")
            from run_crusader_full_animation_set import _write_gif, _write_mp4

            final_mp4 = out_root / "all_creatures_60fps_side_by_side.mp4"
            final_gif = out_root / "all_creatures_60fps_side_by_side.gif"
            _write_mp4(global_frames, final_mp4, args.fps)
            _write_gif(global_frames, final_gif, args.fps)
            run_manifest.update(
                {
                    "finalMp4": str(final_mp4),
                    "finalGif": str(final_gif),
                    "totalOutputFrames": len(global_frames),
                    "totalDurationSeconds": len(global_frames) / float(args.fps),
                }
            )
            for image in global_frames:
                image.close()
        run_manifest_path.write_text(json.dumps(_json_safe(run_manifest), indent=2) + "\n", encoding="utf-8")
        print("RUN MANIFEST:", run_manifest_path)
        return 0
    except Exception as exc:
        if experiment is not None:
            experiment.close()
        if current_runtime_dir is not None:
            try:
                _cleanup_clip_tmp(current_runtime_dir)
            except OSError as cleanup_error:
                run_manifest.setdefault("cleanupWarnings", []).append(
                    f"{current_runtime_dir}: {cleanup_error}"
                )
        run_manifest["status"] = "failed"
        run_manifest["error"] = repr(exc)
        run_manifest_path.write_text(json.dumps(_json_safe(run_manifest), indent=2) + "\n", encoding="utf-8")
        raise
    finally:
        if persistent_worker_pool is not None:
            persistent_worker_pool.close()


if __name__ == "__main__":
    raise SystemExit(main())
