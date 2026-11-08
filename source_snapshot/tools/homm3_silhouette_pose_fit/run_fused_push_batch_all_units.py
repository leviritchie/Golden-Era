#!/usr/bin/env python3
"""Fit every own-GLB SmartRig unit with the memory-safe fused_push hybrid stack.

This remains a diagnostic silhouette experiment. Its outputs are explicitly
**not** inputs to the current captured-mocap delivery lane; use
``experiments/homm3_mocap_v2/run_skin_mesh_pilot.py`` for captured motion.

One clip at a time inside the GPU lock (release + empty_cache after each fit).
Exports oriented clip GLBs via gpu_cascade_delivery when not --fit-only.

Output: artifacts/fused_push_skinned_rollout/ (parallel to homm3_smartrig_skinned_rollout).
Golden Era install: prepare_smartrig_skinned_import.py --rollout-dir <out> then Unity lab build.

Performance defaults:
- Default batch lane: packed raster sized from the mesh (vertices, capped triangles, primitives, skinned joints, clip frames). Dense Stronghold meshes get a smaller pack than Cavalier-class meshes. ``--memory-safe`` / ``--gpu-fed`` stay explicit constant overrides.
- ``--skip-existing`` on (reuse gpu_clip_result.json without rebuilding config)
- Batch perf knobs trim macro/escape vs regression triplet (transit clips re-enable macro)
- Reuses profile_camera_fit.json from fused_push or gpu_cascade_delivery when present
  and current (schemaVersion >= 2 with chroma near-tie selection). Older profile
  cameras are discarded and re-inited — v1 silhouette+facing rankings flipped
  near-symmetric units (gargoyle/pikeman) 180°.
"""
from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from dataclasses import fields, replace
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
DEFAULT_OUT = ROOT / "artifacts/fused_push_skinned_rollout"
GPU_RUN_NAME = "fused_push_v24_pipeline"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (  # noqa: E402
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from gpu_cascade_delivery import (  # noqa: E402
    CHOSEN_DEF_GROUPS,
    IDLE_GROUP,
    SKIPPED_DEF_GROUPS,
    contract_name_for_group,
    delivery_poses_by_group,
    extract_glb_hexlit_pbr_maps,
    select_unit_delivery_choices,
    write_oriented_clip_glb,
    write_oriented_master_glb,
)
from inventory_smartrig_skinned_rollout import (  # noqa: E402
    STATUS_PATH,
    build_status,
)
from run_crusader_full_animation_set import (  # noqa: E402
    _literal_config_kwargs,
    _notebook_config,
)
from run_crusader_gpu_cascade_animation_set import (  # noqa: E402
    _choice_overrides,
    _release_gpu_workspace,
    notebook_gpu_fit_kwargs,
    prepare_gpu_targets,
)
from run_chain_space_surface_compare import compose_clip_gif, _sprite_dir  # noqa: E402
from run_fused_push_regression_triplet import regression_kwargs  # noqa: E402
from run_gpu_cascade_animation_set import (  # noqa: E402
    export_choice_clips,
    rigidization_for_mesh,
    selected_units,
)
from faction_rollout import (  # noqa: E402
    FACTION_ROLLOUT_ORDER,
    active_faction_key,
    faction_clip_progress,
    filter_units_for_faction,
    normalize_faction_key,
    sort_jobs_by_faction,
)

_RIGID_CACHE: dict[str, tuple[bool, Any]] = {}
_CONFIG_CACHE: dict[tuple[str, str, tuple[int, ...]], Any] = {}
CHOICES_CACHE_NAME = "asset_choices_cache.json"


def _choice_to_dict(choice) -> dict[str, Any]:
    from dataclasses import asdict

    payload = asdict(choice)
    for key, value in list(payload.items()):
        if isinstance(value, Path):
            payload[key] = str(value)
        elif isinstance(value, tuple) and value and isinstance(value[0], Path):
            payload[key] = [str(item) for item in value]
    return payload


def _choice_from_dict(payload: dict[str, Any]):
    from roc_semantic_hybrid_widgets import RocAssetChoice

    data = dict(payload)
    for key in ("pilot_dir", "camera_fit", "default_mesh", "def_lab_frame_dir"):
        if data.get(key):
            data[key] = Path(data[key])
    if data.get("source_frames"):
        data["source_frames"] = tuple(Path(item) for item in data["source_frames"])
    for key in ("frame_indices", "def_lab_groups", "def_expected_counts", "present_groups"):
        data[key] = tuple(int(item) for item in data.get(key) or ())
    return RocAssetChoice(**data)


def _discover_all_choices(
    root: Path,
    *,
    resume: bool,
    status_path: Path,
    cache_path: Path,
) -> tuple[tuple[Any, ...], str]:
    status_mtime = status_path.stat().st_mtime if status_path.is_file() else None
    if resume and status_mtime is not None and cache_path.is_file():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("statusMtime") == status_mtime:
            choices = tuple(_choice_from_dict(row) for row in cached.get("choices") or [])
            return choices, f"cache {cache_path} ({len(choices)} choices)"
    import roc_semantic_hybrid_widgets as widgets

    started = time.perf_counter()
    choices = widgets.discover_asset_choices(root)
    elapsed = time.perf_counter() - started
    if status_mtime is not None:
        _json_dump(
            cache_path,
            {
                "statusMtime": status_mtime,
                "choices": [_choice_to_dict(choice) for choice in choices],
            },
        )
    return choices, f"discover elapsed={elapsed:.1f}s choices={len(choices)}"


def _json_dump(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_rollout_index(out_dir: Path) -> dict[str, Any]:
    """Scan pose_picker_runs for completed fused_push clips (authoritative on-disk proof)."""
    picker = ROOT / "artifacts/pose_picker_runs"
    clips: list[dict[str, Any]] = []
    for path in picker.glob(f"**/{GPU_RUN_NAME}/gpu_clip_result.json"):
        if "fused_push_regression" in path.parts:
            continue
        rel = path.relative_to(ROOT)
        parts = rel.parts
        if len(parts) < 5:
            continue
        sid, anim = parts[2], parts[3]
        payload = json.loads(path.read_text(encoding="utf-8"))
        preview = path.parent / "preview_compare.gif"
        clips.append(
            {
                "labSid": sid,
                "animation": anim,
                "score": payload.get("score"),
                "elapsedSec": payload.get("elapsed"),
                "clipResult": str(path),
                "previewGif": str(preview) if preview.is_file() else None,
                "frameCount": len(payload.get("frameIndices") or []),
            }
        )
    clips.sort(key=lambda row: (row["labSid"], row["animation"]))
    summary = {
        "pipeline": GPU_RUN_NAME,
        "proofTier": "generated-artifact validated",
        "completedClips": len(clips),
        "clips": clips,
    }
    _json_dump(out_dir / "rollout_index.json", summary)
    return summary


def _clip_result_path(choice) -> Path:
    return Path(choice.pilot_dir) / GPU_RUN_NAME / "gpu_clip_result.json"


def _gpu_output_dir(choice) -> Path:
    return Path(choice.pilot_dir) / GPU_RUN_NAME


def _preview_path(choice) -> Path:
    return _gpu_output_dir(choice) / "preview_compare.gif"


def _seed_profile_camera(choice) -> Path | None:
    pilot = Path(choice.pilot_dir)
    for subdir in (GPU_RUN_NAME, "gpu_cascade_delivery"):
        cam = pilot / subdir / "initialization" / "profile_camera_fit.json"
        if cam.is_file():
            return cam
    # Non-idle clips: reuse the unit idle profile camera when present.
    if str(choice.animation_name) != "idle":
        idle_pilot = pilot.parent / "idle"
        for subdir in (GPU_RUN_NAME, "gpu_cascade_delivery"):
            cam = idle_pilot / subdir / "initialization" / "profile_camera_fit.json"
            if cam.is_file():
                return cam
    return None


def _idle_profile_sprite_dir(choice) -> Path:
    pilot = Path(choice.pilot_dir)
    idle_pilot = pilot if str(choice.animation_name) == "idle" else pilot.parent / "idle"
    return idle_pilot / "frames_def12_nn_idle_shadow_culled"


def _profile_validation_config(gpu_kwargs: Mapping[str, Any]):
    from gpu_profile_camera_initializer import ProfileCameraInitConfig

    res = gpu_kwargs.get("profile_init_resolution")
    if res is None:
        resolution = (192, 172)
    else:
        resolution = tuple(int(value) for value in res)
    return ProfileCameraInitConfig(resolution=resolution)


def _mesh_fit_blocked(row: Mapping[str, Any]) -> str | None:
    from inventory_smartrig_skinned_rollout import mesh_catalog_note

    sid = str(row.get("labSid") or "")
    live = mesh_catalog_note(sid) if sid else None
    note = live if isinstance(live, dict) else row.get("meshNote")
    if not isinstance(note, dict):
        return None
    if bool(note.get("fitBlocked") or note.get("blockFit")):
        return str(note.get("reason") or note.get("issue") or "mesh note blocks pose fit")
    return None


def _validate_reused_profile_camera(
    choice,
    mesh: Path,
    camera_fit: Path,
    *,
    config=None,
) -> None:
    from gpu_profile_camera_initializer import (
        ProfileMeshSpriteMismatchError,
        validate_profile_mesh_sprite_alignment,
    )

    sprite_dir = _idle_profile_sprite_dir(choice)
    if not sprite_dir.is_dir():
        raise RuntimeError(
            f"profile mesh-sprite validation requires idle sprites at {sprite_dir} "
            f"for {choice.unit_sid} {choice.animation_name}"
        )
    validation_config = config or _profile_validation_config({})
    try:
        validate_profile_mesh_sprite_alignment(
            src_glb=mesh,
            camera_fit=camera_fit,
            target_frame_dir=sprite_dir,
            frame_index=0,
            config=validation_config,
        )
    except ProfileMeshSpriteMismatchError:
        raise
    except Exception as exc:
        raise RuntimeError(
            f"profile mesh-sprite validation failed for {choice.unit_sid} "
            f"{choice.animation_name}: {exc}"
        ) from exc


def _apply_choice_camera(choice, config, gpu_kwargs: dict[str, Any], mesh: Path):
    """Pin a real camera file on config + kwargs before GPU fit."""
    from gpu_profile_camera_initializer import (
        ProfileMeshSpriteMismatchError,
        profile_camera_init_is_current,
        profile_camera_source_mesh,
    )

    mesh = Path(mesh).resolve()
    if not mesh.is_file():
        raise RuntimeError(
            f"missing mesh for {choice.unit_sid} {choice.animation_name}: {mesh}"
        )
    validation_config = _profile_validation_config(gpu_kwargs)
    seed = _seed_profile_camera(choice)
    if seed is not None:
        recorded_mesh = profile_camera_source_mesh(seed)
        if recorded_mesh is not None and recorded_mesh != mesh.resolve():
            print(
                f"profile camera stale for {choice.unit_sid} {choice.animation_name}: "
                f"recorded mesh {recorded_mesh} != current {mesh.resolve()} "
                "— re-running profile_init",
                flush=True,
            )
            seed = None
        if seed is not None:
            current, reason = profile_camera_init_is_current(seed)
            if not current:
                print(
                    f"profile camera outdated for {choice.unit_sid} {choice.animation_name}: "
                    f"{reason} — re-running profile_init "
                    "(chroma near-tie selection; see PROFILE_INIT_SCHEMA_VERSION)",
                    flush=True,
                )
                seed = None
        if seed is not None:
            try:
                _validate_reused_profile_camera(
                    choice,
                    mesh,
                    seed,
                    config=validation_config,
                )
                gpu_kwargs = dict(gpu_kwargs)
                gpu_kwargs["profile_init_enabled"] = False
                return replace(config, camera_fit_path=str(seed)), gpu_kwargs
            except ProfileMeshSpriteMismatchError as exc:
                print(
                    f"reused profile camera failed mesh-sprite gate for "
                    f"{choice.unit_sid} {choice.animation_name}: {exc} "
                    "— re-running profile_init",
                    flush=True,
                )
                seed = None
    sprite = Path(choice.pilot_dir) / "roc_sprite_camera_fit.json"
    if not sprite.is_file():
        raise RuntimeError(
            f"missing profile camera and roc_sprite_camera_fit.json for "
            f"{choice.unit_sid} {choice.animation_name}"
        )
    gpu_kwargs = dict(gpu_kwargs)
    gpu_kwargs["profile_init_enabled"] = True
    return replace(config, camera_fit_path=str(sprite)), gpu_kwargs


def _frame_count_for_choice(choice) -> int:
    return sum(int(count) for count in choice.def_expected_counts)


def _rigid_for_mesh(mesh: Path) -> tuple[bool, Any]:
    key = str(mesh.resolve())
    cached = _RIGID_CACHE.get(key)
    if cached is not None:
        return cached
    cached = rigidization_for_mesh(mesh)
    _RIGID_CACHE[key] = cached
    return cached



def _idle_seed_poses(choice) -> dict[int, dict[str, Any]] | None:
    """Seed non-idle clips from the unit idle solve (frame 0), without skipping articulated."""
    if str(choice.animation_name) == "idle":
        return None
    idle_pilot = Path(choice.pilot_dir).parent / "idle"
    for subdir in (GPU_RUN_NAME, "gpu_cascade_delivery"):
        clip = idle_pilot / subdir / "gpu_clip_result.json"
        if not clip.is_file():
            continue
        payload = json.loads(clip.read_text(encoding="utf-8"))
        poses = payload.get("poses") or {}
        frame0 = poses.get("0", poses.get(0))
        if isinstance(frame0, dict) and frame0:
            return {0: dict(frame0)}
    return None


def _upgrade_line_seed_poses(choice, mesh: Path | None) -> dict[int, dict[str, Any]] | None:
    if mesh is None or not Path(mesh).is_file():
        return None
    from upgrade_line_keypoints import upgrade_line_pose_seed

    return upgrade_line_pose_seed(
        root=ROOT,
        lab_sid=str(choice.unit_sid),
        animation_name=str(choice.animation_name),
        target_mesh=Path(mesh),
        run_names=(GPU_RUN_NAME, "gpu_cascade_delivery"),
    )


def kwargs_for_choice(
    choice,
    *,
    full_pipeline: bool,
    batch: bool = True,
    memory_safe_batch: bool = False,
    gpu_fed_batch: bool = False,
    mesh: Path | None = None,
) -> dict[str, Any]:
    from run_fused_push_regression_triplet import filter_kwargs

    if full_pipeline:
        kw = dict(regression_kwargs(full_pipeline=True))
    elif batch:
        kw = dict(
            regression_kwargs(
                batch=True,
                memory_safe_batch=memory_safe_batch,
                gpu_fed_batch=gpu_fed_batch,
            )
        )
    else:
        kw = dict(regression_kwargs(full_pipeline=False))
    groups = tuple(int(g) for g in choice.def_lab_groups)
    counts = tuple(int(c) for c in choice.def_expected_counts)
    if groups and int(groups[0]) == IDLE_GROUP and len(groups) > 1:
        kw["idle_prefix_frames"] = int(counts[0])
        kw["joint_temporal_consensus_idle_end"] = False
        if len(groups) >= 3 and int(groups[-1]) == IDLE_GROUP:
            kw["idle_suffix_frames"] = int(counts[-1])
        if batch and not full_pipeline:
            kw["idle_fused_macro_enabled"] = True
            # Do not re-root after articulated: on Cavalier attack this burned ~38s
            # after mean was already above the escape threshold.
    seed_poses = _upgrade_line_seed_poses(choice, mesh) or _idle_seed_poses(choice)
    if seed_poses is not None:
        kw["initial_poses"] = seed_poses
        # Seed from idle, but still run articulated refine on motion.
        kw["articulated_skip_when_seeded"] = False
        kw["root_skip_when_seeded"] = False
    if batch and not full_pipeline and not memory_safe_batch and not gpu_fed_batch:
        if mesh is None:
            raise RuntimeError("batch fused-push requires a mesh path to size the raster pack")
        frames = _frame_count_for_choice(choice)
        if frames < 1:
            raise RuntimeError(f"batch fused-push clip has no frames: {choice.animation_name}")
        from fused_push_mesh_raster_budget import apply_mesh_raster_budget

        kw, budget = apply_mesh_raster_budget(kw, mesh, frame_count=frames)
        print(
            "batch mesh-raster "
            f"slots={budget['joint_score_raster_batch']} "
            f"chroma={budget['chroma_scale']} "
            f"hyps={budget['jointScoreHypsPerLaunch']} "
            f"frames={budget['clipFrameCount']} "
            f"verts={budget['meshVertexCount']} "
            f"tris={budget['meshRasterTriangles']} "
            f"prims={budget['meshPrimitiveCount']} "
            f"joints={budget['meshSkinnedJoints']} "
            f"load={budget['meshRasterLoad']}",
            flush=True,
        )
    return filter_kwargs(kw)


def _build_config(
    choice,
    mesh: Path,
    notebook_kwargs: Mapping[str, Any],
    notebook,
    *,
    use_cache: bool = True,
):
    from roc_semantic_hybrid_experiment import RocHybridConfig

    groups = tuple(int(g) for g in choice.def_lab_groups)
    cache_key = (str(mesh.resolve()), str(choice.animation_name), groups)
    if use_cache and cache_key in _CONFIG_CACHE:
        return _CONFIG_CACHE[cache_key]

    require, report = _rigid_for_mesh(mesh)
    overrides = _choice_overrides(choice, mesh)
    overrides["require_meshy_rigidization"] = require
    overrides["meshy_rigidization_report"] = report
    config_kwargs = dict(notebook_kwargs)
    config_kwargs.update(overrides)
    valid = {field.name for field in fields(RocHybridConfig)}
    unknown = sorted(set(config_kwargs) - valid)
    if unknown:
        raise TypeError("unsupported RocHybridConfig fields: " + ", ".join(unknown))
    config = _notebook_config(RocHybridConfig, config_kwargs, notebook=notebook)
    config = replace(
        config,
        semantic_enabled=False,
        semantic_only=False,
        semantic_dense_weight=0.0,
        require_meshy_rigidization=require,
        meshy_rigidization_report=report,
    )
    if use_cache:
        _CONFIG_CACHE[cache_key] = config
    return config


def _clip_success_report(choice, payload: Mapping[str, Any], *, fitted_new: bool) -> dict[str, Any]:
    preview = _preview_path(choice)
    return {
        "labSid": choice.unit_sid,
        "animation": choice.animation_name,
        "groups": list(choice.def_lab_groups),
        "score": payload.get("score"),
        "clipResult": str(_clip_result_path(choice)),
        "previewGif": str(preview).replace("\\", "/") if preview.is_file() else None,
        "fittedNew": bool(fitted_new),
        "reused": not fitted_new,
    }


def _clip_fully_done(choice, *, skip_existing: bool, want_preview: bool) -> bool:
    if not skip_existing:
        return False
    if not _clip_result_path(choice).is_file():
        return False
    if want_preview and not _preview_path(choice).is_file():
        return False
    return True


def fit_choice_fused(
    choice,
    *,
    config,
    gpu_kwargs: Mapping[str, Any],
    skip_existing: bool,
) -> tuple[dict[str, Any], bool]:
    """Return (payload, fitted_new)."""
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    result_path = _clip_result_path(choice)
    if skip_existing and result_path.is_file():
        existing = json.loads(result_path.read_text(encoding="utf-8"))
        print(f"reuse {choice.animation_name}: {result_path}", flush=True)
        return existing, False
    config = prepare_gpu_targets(config)
    started = time.perf_counter()
    print(
        f"fit {choice.unit_sid} {choice.animation_name} groups={list(choice.def_lab_groups)} "
        f"frames={len(config.frame_indices)} raster_batch={gpu_kwargs.get('joint_score_raster_batch')} "
        f"profile_init={gpu_kwargs.get('profile_init_enabled', True)}",
        flush=True,
    )
    solved = run_gpu_depth_fit_from_hybrid_config(
        config,
        output_dir=_gpu_output_dir(choice),
        **dict(gpu_kwargs),
    )
    result_path = Path(solved.pose_result["clipResultPath"])
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    print(
        f"fitted {choice.animation_name} score={payload.get('score')} "
        f"elapsed={time.perf_counter() - started:.1f}s",
        flush=True,
    )
    return payload, True


def write_preview_gif(choice, *, frame_count: int) -> Path:
    pilot = Path(choice.pilot_dir).resolve()
    gif = compose_clip_gif(
        clip_root=pilot,
        sprite_dir=_sprite_dir(choice),
        frame_count=int(frame_count),
        arms=({"id": GPU_RUN_NAME},),
    )
    preview = _preview_path(choice)
    preview.parent.mkdir(parents=True, exist_ok=True)
    if preview.resolve() != gif.resolve():
        preview.write_bytes(gif.read_bytes())
    return preview


def _load_status(*, resume: bool, refresh: bool) -> dict[str, Any]:
    if resume and not refresh and STATUS_PATH.is_file():
        print(f"resume: status from {STATUS_PATH}", flush=True)
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    started = time.perf_counter()
    status = build_status()
    _json_dump(STATUS_PATH, status)
    print(f"build_status elapsed={time.perf_counter() - started:.1f}s", flush=True)
    return status


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK)
    parser.add_argument("--unit", default="all", help="lab SID, comma-separated, or all")
    parser.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="reuse gpu_clip_result.json (default: on)",
    )
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument("--fit-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit-units", type=int, default=0)
    parser.add_argument(
        "--animation",
        default="",
        help="optional animation name filter (e.g. idle_start_move_end)",
    )
    parser.add_argument(
        "--limit-clips",
        type=int,
        default=0,
        help="max *new* clip fits this invocation (0 = all pending)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="v24-class full pipeline (high VRAM; GPU lane must be empty)",
    )
    parser.add_argument(
        "--export-units",
        action="store_true",
        help="export delivery GLBs after fit (requires every clip for each unit)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse cached inventory status.json (skip build_status scan)",
    )
    parser.add_argument(
        "--refresh-status",
        action="store_true",
        help="force build_status even with --resume",
    )
    parser.add_argument(
        "--preview-gif",
        action="store_true",
        help="write preview_compare.gif per clip (off by default for throughput)",
    )
    parser.add_argument(
        "--memory-safe",
        action="store_true",
        help="tighter raster batch (16) + chroma=2 to avoid shared-memory spill",
    )
    parser.add_argument(
        "--gpu-fed",
        action="store_true",
        help="wider raster batch (48) + chroma=4; may spill if VRAM is tight",
    )
    parser.add_argument(
        "--faction",
        default="",
        help="homm3 faction key or short name (e.g. castle, homm3_castle); limits jobs to one faction",
    )
    parser.add_argument(
        "--active-faction",
        action="store_true",
        help="auto-pick the first faction in rollout order that still has pending clips",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.export_only and args.fit_only:
        raise SystemExit("use either --fit-only or --export-only, not both")
    if args.faction and args.active_faction:
        raise SystemExit("use either --faction or --active-faction, not both")

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "fit_runs").mkdir(parents=True, exist_ok=True)

    status = _load_status(resume=bool(args.resume), refresh=bool(args.refresh_status))
    units = selected_units(status, args)
    all_choices, choices_note = _discover_all_choices(
        ROOT,
        resume=bool(args.resume),
        status_path=STATUS_PATH,
        cache_path=out_dir / CHOICES_CACHE_NAME,
    )
    print(f"asset choices: {choices_note}", flush=True)

    faction_key: str | None = None
    if str(args.faction or "").strip():
        faction_key = normalize_faction_key(str(args.faction))

    plan: list[dict[str, Any]] = []
    jobs: list[tuple[dict[str, Any], Any]] = []
    for row in units:
        sid = row["labSid"]
        mesh_block = _mesh_fit_blocked(row)
        if mesh_block is not None:
            # Fail-closed at plan time so quarantined GLBs do not burn GPU rounds.
            plan.append(
                {
                    "labSid": sid,
                    "blocked": True,
                    "reason": mesh_block,
                    "choices": [],
                }
            )
            continue
        try:
            choices = select_unit_delivery_choices(all_choices, sid)
        except RuntimeError as exc:
            # Missing lab DEF / delivery plan: skip unit, do not fail the whole faction batch.
            plan.append(
                {
                    "labSid": sid,
                    "blocked": True,
                    "reason": str(exc),
                    "choices": [],
                }
            )
            continue
        plan.append(
            {
                "labSid": sid,
                "mesh": row["glb"],
                "choices": [
                    {
                        "animation": choice.animation_name,
                        "groups": list(choice.def_lab_groups),
                        "counts": list(choice.def_expected_counts),
                    }
                    for choice in choices
                ],
            }
        )
        for choice in choices:
            jobs.append((row, choice))

    animation_filter = str(args.animation or "").strip()
    if animation_filter:
        jobs = [
            (row, choice)
            for row, choice in jobs
            if str(choice.animation_name) == animation_filter
        ]
        print(
            f"animation filter={animation_filter!r} jobs={len(jobs)}",
            flush=True,
        )
    want_preview = bool(args.preview_gif)

    def _clip_done(sid: str, animation: str) -> bool:
        for _row, choice in jobs:
            if str(choice.unit_sid) != sid:
                continue
            if str(choice.animation_name) != animation:
                continue
            return _clip_fully_done(
                choice, skip_existing=bool(args.skip_existing), want_preview=want_preview
            )
        return False

    if args.active_faction and faction_key is None:
        faction_key = active_faction_key(
            clip_done=_clip_done,
            status_units=status["units"],
            all_choices=all_choices,
            mesh_blocked=_mesh_fit_blocked,
        )
        if faction_key is None:
            print("active-faction: all factions complete (no pending own-GLB clips)", flush=True)

    if faction_key is not None:
        units = filter_units_for_faction(units, faction_key)
        allowed = {row["labSid"] for row in units}
        jobs = [(row, choice) for row, choice in jobs if str(row.get("labSid")) in allowed]
        jobs = sort_jobs_by_faction(jobs, faction_key)
        plan = [item for item in plan if str(item.get("labSid")) in allowed]
        faction_progress = faction_clip_progress(
            faction_key,
            status_units=status["units"],
            all_choices=all_choices,
            clip_done=_clip_done,
            mesh_blocked=_mesh_fit_blocked,
        )
        _json_dump(out_dir / "faction_progress.json", faction_progress)
    else:
        faction_progress = None

    knob_mode = (
        "full"
        if args.full
        else (
            "batch_gpu_fed"
            if args.gpu_fed
            else ("batch_memory_safe" if args.memory_safe else "batch_default")
        )
    )
    sample_kw = (
        kwargs_for_choice(
            jobs[0][1],
            full_pipeline=bool(args.full),
            memory_safe_batch=bool(args.memory_safe),
            gpu_fed_batch=bool(args.gpu_fed),
            mesh=Path(jobs[0][0]["glb"]),
        )
        if jobs
        else {}
    )
    _json_dump(
        out_dir / "fit_plan.json",
        {
            "pipeline": "fused_push_batch",
            "knobMode": knob_mode,
            "gpuRunName": GPU_RUN_NAME,
            "knobs": sample_kw,
            "factionKey": faction_key,
            "factionRolloutOrder": list(FACTION_ROLLOUT_ORDER),
            "factionProgress": faction_progress,
            "plan": plan,
        },
    )

    pending = [
        (row, choice)
        for row, choice in jobs
        if not _clip_fully_done(choice, skip_existing=bool(args.skip_existing), want_preview=want_preview)
    ]
    if faction_key is not None:
        pending = sort_jobs_by_faction(pending, faction_key)
    print(
        json.dumps(
            {
                "units": len(units),
                "clipJobs": len(jobs),
                "pendingJobs": len(pending),
                "factionKey": faction_key,
                "factionPendingClips": (
                    faction_progress.get("pendingClips") if faction_progress else None
                ),
                "knobMode": knob_mode,
                "rasterBatch": sample_kw.get("joint_score_raster_batch"),
                "chromaScale": sample_kw.get("chroma_scale"),
                "previewGif": want_preview,
                "out": str(out_dir),
                "planBlocked": [p for p in plan if p.get("blocked")],
                "planErrors": [p for p in plan if p.get("error")],
            },
            indent=2,
        ),
        flush=True,
    )
    if args.dry_run:
        return 0

    notebook_kwargs: dict[str, Any] | None = None
    lock_path = global_cascade_batch_lock_path(ROOT)
    # Export does not touch CUDA; do not contend with a live fit cascade.
    needs_gpu_lock = not bool(args.export_only)
    if needs_gpu_lock:
        acquire_cascade_batch_lock(lock_path)
    reports: list[dict[str, Any]] = []
    fitted_clips = 0
    skipped_clips = 0
    try:
        for item in plan:
            if item.get("blocked"):
                print(
                    f"skip {item['labSid']}: blocked — {item.get('reason')}",
                    flush=True,
                )
                reports.append(
                    {
                        "labSid": item["labSid"],
                        "blocked": True,
                        "reason": item.get("reason"),
                    }
                )

        if args.export_only:
            pending = []

        for row, choice in pending:
            if args.limit_clips and fitted_clips >= int(args.limit_clips):
                print(f"limit-clips={args.limit_clips} reached; stopping", flush=True)
                break

            sid = row["labSid"]
            animation = str(choice.animation_name)
            groups = tuple(int(group) for group in choice.def_lab_groups)
            motion = [group for group in groups if group != IDLE_GROUP]
            if motion and all(
                group in SKIPPED_DEF_GROUPS or group not in CHOSEN_DEF_GROUPS
                for group in motion
            ):
                print(f"skip {sid} {animation}: unshipped vertical DEF {motion}", flush=True)
                continue

            if _clip_fully_done(
                choice, skip_existing=bool(args.skip_existing), want_preview=want_preview
            ):
                skipped_clips += 1
                if str(args.unit) != "all":
                    payload = json.loads(_clip_result_path(choice).read_text(encoding="utf-8"))
                    reports.append(_clip_success_report(choice, payload, fitted_new=False))
                continue

            mesh_block = _mesh_fit_blocked(row)
            if mesh_block is not None:
                # Should already be plan-blocked; keep a soft skip if status drifts mid-run.
                msg = f"{sid}: fit blocked by mesh note — {mesh_block}"
                print(f"skip {sid} {animation}: {msg}", flush=True)
                reports.append(
                    {
                        "labSid": sid,
                        "animation": animation,
                        "blocked": True,
                        "reason": msg,
                    }
                )
                continue

            latest: dict[str, Any] | None = None
            try:
                mesh = Path(row["glb"]).resolve()
                if not mesh.is_file():
                    raise RuntimeError(f"missing GLB {mesh}")

                result_exists = _clip_result_path(choice).is_file()
                gpu_kwargs = kwargs_for_choice(
                    choice,
                    full_pipeline=bool(args.full),
                    memory_safe_batch=bool(args.memory_safe),
                    gpu_fed_batch=bool(args.gpu_fed),
                    mesh=mesh,
                )
                latest_preview = str(_preview_path(choice)).replace("\\", "/") if result_exists and _preview_path(choice).is_file() else None

                if args.export_only:
                    payload = json.loads(_clip_result_path(choice).read_text(encoding="utf-8"))
                    fitted_new = False
                elif result_exists and bool(args.skip_existing):
                    payload = json.loads(_clip_result_path(choice).read_text(encoding="utf-8"))
                    fitted_new = False
                    print(f"reuse {animation}: {_clip_result_path(choice)}", flush=True)
                else:
                    if notebook_kwargs is None:
                        nb_started = time.perf_counter()
                        notebook_kwargs = _literal_config_kwargs(args.notebook, require_dino=False)
                        notebook_gpu_fit_kwargs(args.notebook)
                        print(
                            f"notebook warmup elapsed={time.perf_counter() - nb_started:.1f}s",
                            flush=True,
                        )
                    config = _build_config(choice, mesh, notebook_kwargs, args.notebook)
                    config, gpu_kwargs = _apply_choice_camera(choice, config, gpu_kwargs, mesh)
                    payload, fitted_new = fit_choice_fused(
                        choice,
                        config=config,
                        gpu_kwargs=gpu_kwargs,
                        skip_existing=False,
                    )
                    if fitted_new:
                        fitted_clips += 1

                if want_preview and (fitted_new or not _preview_path(choice).is_file()):
                    if fitted_new and payload:
                        frame_indices = payload.get("frameIndices") or []
                        frame_count = len(frame_indices)
                    else:
                        frame_count = _frame_count_for_choice(choice)
                    if int(frame_count) <= 0:
                        raise RuntimeError(
                            f"preview GIF requires frame_count>0 for {sid} {animation}"
                        )
                    preview = write_preview_gif(choice, frame_count=frame_count)
                    latest_preview = str(preview).replace("\\", "/")

                latest = _clip_success_report(choice, payload, fitted_new=fitted_new)
                reports.append(latest)
            except Exception as exc:
                import traceback

                traceback.print_exc()
                print(f"ERROR {sid} {animation}: {exc}", flush=True)
                latest = {"labSid": sid, "animation": animation, "error": str(exc)}
                reports.append(latest)
            finally:
                _json_dump(
                    out_dir / "progress.json",
                    {
                        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "reports": reports[-40:],
                        "fittedClips": fitted_clips,
                        "skippedClips": skipped_clips,
                    },
                )
                if latest is not None:
                    clip_log = out_dir / "clip_log.jsonl"
                    with clip_log.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(latest) + "\n")
                gc.collect()
                _release_gpu_workspace()

        export_units = (bool(args.export_units) or bool(args.export_only)) and not args.fit_only
        if export_units and args.limit_clips and not args.export_only and not args.export_units:
            print(
                "skip unit export: --limit-clips set; pass --export-units to export complete units",
                flush=True,
            )
            export_units = False
        if export_units:
            for row in units:
                sid = row["labSid"]
                if _mesh_fit_blocked(row) is not None:
                    print(f"skip {sid} export: mesh blocked", flush=True)
                    continue
                try:
                    mesh = Path(row["glb"]).resolve()
                    choices = select_unit_delivery_choices(all_choices, sid)
                    missing_clips = [
                        str(choice.animation_name)
                        for choice in choices
                        if not _clip_result_path(choice).is_file()
                    ]
                    if missing_clips:
                        print(
                            f"skip {sid} export: missing {len(missing_clips)} clip result(s) "
                            f"({', '.join(missing_clips[:4])}{'…' if len(missing_clips) > 4 else ''})",
                            flush=True,
                        )
                        continue
                    prefix = "Crusader" if sid == "h3_crusader" else "Unit"
                    out_root = out_dir / "units" / sid
                    clip_dir = out_root / "clips"
                    exported: list[dict[str, Any]] = []
                    for choice in choices:
                        clip_path = _clip_result_path(choice)
                        payload = json.loads(clip_path.read_text(encoding="utf-8"))
                        exported.extend(
                            export_choice_clips(
                                choice,
                                payload,
                                mesh=mesh,
                                clip_dir=clip_dir,
                                prefix=prefix,
                                clip_result_path=clip_path,
                            )
                        )
                    master = write_oriented_master_glb(
                        mesh,
                        out_root / f"{sid}_smartrig_master.glb",
                        allow_missing_pbr_maps=True,
                    )
                    pbr = extract_glb_hexlit_pbr_maps(mesh, out_root)
                    shipped = {item["contractName"] for item in exported}
                    needed = {
                        contract_name_for_group(int(group), prefix)
                        for choice in choices
                        for group in choice.def_lab_groups
                        if int(group) in CHOSEN_DEF_GROUPS
                        and not (int(group) == IDLE_GROUP and len(choice.def_lab_groups) > 1)
                    }
                    missing = sorted(needed - shipped)
                    if missing:
                        raise RuntimeError(f"{sid} delivery is missing contracts: {missing}")
                    unit_report = {
                        "labSid": sid,
                        "mesh": str(mesh),
                        "master": master,
                        "pbr": pbr,
                        "clips": exported,
                        "scale": row.get("scale"),
                        "pipeline": "fused_push_batch",
                        "proofTier": "generated-artifact",
                    }
                    _json_dump(out_root / "delivery_manifest.json", unit_report)
                    reports.append({"labSid": sid, "clips": len(exported), "out": str(out_root)})
                except Exception as exc:
                    import traceback

                    traceback.print_exc()
                    print(f"ERROR {sid} export: {exc}", flush=True)
                    reports.append({"labSid": sid, "error": str(exc)})
    finally:
        if needs_gpu_lock:
            release_cascade_batch_lock(lock_path)

    fit_report_path = out_dir / "fit_report.json"
    prior: list[dict[str, Any]] = []
    if fit_report_path.is_file():
        prior = list(json.loads(fit_report_path.read_text(encoding="utf-8")).get("reports") or [])
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in prior:
        key = (str(row.get("labSid")), str(row.get("animation")))
        if key[0] and key[1]:
            merged[key] = row
    for row in reports:
        key = (str(row.get("labSid")), str(row.get("animation")))
        if key[0] and key[1]:
            merged[key] = row
    _json_dump(fit_report_path, {"reports": list(merged.values())})
    rollout_index = _write_rollout_index(out_dir)
    errors = [row for row in reports if row.get("error")]
    print(
        json.dumps(
            {
                "ok": not errors,
                "fittedClips": fitted_clips,
                "skippedClips": skipped_clips,
                "rolloutCompletedClips": rollout_index.get("completedClips"),
                "rolloutIndex": str(out_dir / "rollout_index.json"),
                "errors": errors,
            },
            indent=2,
        ),
        flush=True,
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
