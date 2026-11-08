#!/usr/bin/env python3
"""Fit physics-dampened cascade clips for every Meshy SmartRig catalog unit.

Uses CURRENT_CASCADE_KEEP (physics_smooth_enabled). One GPU lock. Does not
use the melted owned-bind path. Placeholder units are not fitted here; they
reuse a family peer idle at import time.
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
DEFAULT_OUT = ROOT / "artifacts/homm3_smartrig_skinned_rollout"
GPU_RUN_NAME = "gpu_cascade_delivery"

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
    apply_current_cascade_keep,
    contract_name_for_group,
    delivery_poses_by_group,
    extract_glb_hexlit_pbr_maps,
    require_pose_units_degrees,
    select_unit_delivery_choices,
    write_oriented_clip_glb,
    write_oriented_master_glb,
)
from deliberate_motion_contract import clip_lifecycle_row, default_edges_for_suffix
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
    _clip_result_path,
    _load_clip_result,
    _release_gpu_workspace,
    fit_choice,
    notebook_gpu_fit_kwargs,
)
from roc_semantic_hybrid_widgets import meshy_rigidization_status  # noqa: E402


def _json_dump(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _require_rigidization(mesh: Path) -> bool:
    return mesh.name.lower().endswith("_smartrigged_rigidized.glb")


def export_choice_clips(
    choice,
    payload: Mapping[str, Any],
    *,
    mesh: Path,
    clip_dir: Path,
    prefix: str,
    clip_result_path: Path | None = None,
    frame_duration_by_suffix: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    # Provenance must name the payload actually exported. Callers whose fit
    # results live outside this module's GPU_RUN_NAME lane (e.g. the fused-push
    # batch lane) pass their own resolved path; the fallback keeps the legacy
    # crusader-lane behavior consistent with its _load_clip_result source.
    # ``frame_duration_by_suffix`` overrides the authentic 12 fps per contract suffix
    # (clip_character_pass slows idles); the sidecar records whatever was used so the
    # clip-pose validator checks the GLB sampler against that value.
    source_path = Path(clip_result_path) if clip_result_path is not None else _clip_result_path(choice)
    require_pose_units_degrees(payload, source=str(source_path))
    groups = tuple(int(group) for group in choice.def_lab_groups)
    counts = tuple(int(count) for count in choice.def_expected_counts)
    delivered = delivery_poses_by_group(payload["poses"], groups, counts)
    reports = []
    for group, poses in delivered.items():
        if int(group) not in CHOSEN_DEF_GROUPS:
            continue
        contract = contract_name_for_group(int(group), prefix)
        dest = clip_dir / f"{contract}.glb"
        suffix = contract.split("_", 1)[-1]
        predecessor, successor = default_edges_for_suffix(suffix)
        lifecycle_kwargs: dict[str, Any] = {}
        if frame_duration_by_suffix is not None:
            if suffix not in frame_duration_by_suffix:
                raise KeyError(f"{contract}: no frame duration for suffix {suffix!r} in frame_duration_by_suffix")
            lifecycle_kwargs["frame_duration_seconds"] = float(frame_duration_by_suffix[suffix])
        lifecycle = clip_lifecycle_row(
            clip_name=contract,
            def_group=int(group),
            source_frame_count=len(poses),
            predecessor=predecessor,
            successor=successor,
            **lifecycle_kwargs,
        )
        # The lifecycle row is the single timing owner; fps is derived from it so the
        # writer's reciprocal check cannot trip on a slowed (character-pass) clip.
        report = write_oriented_clip_glb(
            mesh, dest, poses, clip_name=contract, lifecycle=lifecycle,
            fps=1.0 / float(lifecycle["frameDurationSeconds"]),
        )
        report.update(
            {
                "contractName": contract,
                "defGroup": int(group),
                "fitAnimation": choice.animation_name,
                "idlePrefixFrames": int(counts[0]) if groups and groups[0] == IDLE_GROUP else 0,
                "idleSuffixFrames": int(counts[-1])
                if len(groups) >= 3 and groups[0] == IDLE_GROUP and groups[-1] == IDLE_GROUP
                else 0,
                "clipResultPath": str(source_path),
                "fitScore": payload.get("score"),
            }
        )
        _json_dump(dest.with_suffix(".json"), report)
        reports.append(report)
    return reports


def rigidization_for_mesh(mesh: Path) -> tuple[bool, Path | None]:
    status, report = meshy_rigidization_status(mesh)
    if status == "pass":
        return True, report
    return False, None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK)
    parser.add_argument("--unit", default="all", help="lab SID, comma-separated SIDs, or all")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument("--export-idle-ready", action="store_true", help="export Idle GLBs for keep-matching results without taking the GPU lock")
    parser.add_argument("--fit-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit-units", type=int, default=0)
    return parser.parse_args(argv)


def _write_progress(out: Path, reports: list[dict[str, Any]], *, latest: dict[str, Any] | None = None) -> None:
    out = Path(out)
    errors = [row for row in reports if row.get("error")]
    ok = [row for row in reports if row.get("animation") and not row.get("error")]
    _json_dump(
        out / "progress.json",
        {
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "okClips": len(ok),
            "errorCount": len(errors),
            "last": reports[-20:],
            "errors": errors,
        },
    )
    if latest is not None:
        with (out / "clip_log.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(latest) + "\n")


def _is_idle_choice(choice) -> bool:
    groups = tuple(int(group) for group in choice.def_lab_groups)
    return groups == (IDLE_GROUP,)


def export_idle_unit(row: Mapping[str, Any], choice, *, mesh: Path, out_dir: Path) -> dict[str, Any]:
    sid = row["labSid"]
    prefix = "Crusader" if sid == "h3_crusader" else "Unit"
    payload = _load_clip_result(_clip_result_path(choice))
    out_root = Path(out_dir) / "units" / sid
    clip_dir = out_root / "clips"
    exported = export_choice_clips(choice, payload, mesh=mesh, clip_dir=clip_dir, prefix=prefix)
    idle_names = {item["contractName"] for item in exported}
    expected_idle = contract_name_for_group(IDLE_GROUP, prefix)
    if expected_idle not in idle_names:
        raise RuntimeError(f"{sid} idle export did not write {expected_idle}")
    master = write_oriented_master_glb(
        mesh,
        out_root / f"{sid}_smartrig_master.glb",
        allow_missing_pbr_maps=True,
    )
    unit_report = {
        "labSid": sid,
        "mesh": str(mesh),
        "master": master,
        "pbr": master.get("pbr"),
        "clips": exported,
        "scale": row.get("scale"),
        "idleOnly": True,
        "placeholderIdleOnly": True,
        "proofTier": "generated-artifact",
    }
    _json_dump(out_root / "delivery_manifest.json", unit_report)
    return {"labSid": sid, "clips": len(exported), "idleOnly": True, "out": str(out_root)}


def _build_config(choice, mesh: Path, notebook_kwargs: Mapping[str, Any], notebook):
    from roc_semantic_hybrid_experiment import RocHybridConfig

    require, report = rigidization_for_mesh(mesh)
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
    return replace(
        config,
        semantic_enabled=False,
        semantic_only=False,
        semantic_dense_weight=0.0,
        require_meshy_rigidization=require,
        meshy_rigidization_report=report,
    )


def selected_units(status: Mapping[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    requested = {part.strip() for part in str(args.unit).split(",") if part.strip() and part.strip().lower() not in {"all", "*"}}
    rows = []
    for row in status["units"]:
        if row["meshRole"] != "own_glb":
            continue
        if requested and row["labSid"] not in requested:
            continue
        rows.append(row)
    if requested:
        missing = sorted(requested - {row["labSid"] for row in rows})
        if missing:
            raise RuntimeError(f"requested units are not own-GLB SmartRig rows: {missing}")
    if args.limit_units:
        rows = rows[: int(args.limit_units)]
    if not rows:
        raise RuntimeError("no own-GLB SmartRig units selected")
    return rows


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.export_only and args.fit_only:
        raise SystemExit("use either --fit-only or --export-only, not both")
    if args.export_idle_ready and (args.export_only or args.fit_only):
        raise SystemExit("use --export-idle-ready alone")
    status = build_status()
    _json_dump(STATUS_PATH, status)
    units = selected_units(status, args)

    import roc_semantic_hybrid_widgets as widgets

    all_choices = widgets.discover_asset_choices(ROOT)
    gpu_kwargs = apply_current_cascade_keep(notebook_gpu_fit_kwargs(args.notebook))
    notebook_kwargs = _literal_config_kwargs(args.notebook, require_dino=False)

    plan = []
    idle_jobs: list[tuple[dict[str, Any], Any]] = []
    rest_jobs: list[tuple[dict[str, Any], Any]] = []
    for row in units:
        sid = row["labSid"]
        try:
            choices = select_unit_delivery_choices(all_choices, sid)
        except RuntimeError as exc:
            plan.append({"labSid": sid, "error": str(exc), "choices": []})
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
            if _is_idle_choice(choice):
                idle_jobs.append((row, choice))
            else:
                rest_jobs.append((row, choice))
    out_dir = Path(args.out).resolve()
    keep_record = {
        "score_mode": gpu_kwargs.get("score_mode"),
        "physics_smooth_enabled": gpu_kwargs.get("physics_smooth_enabled"),
        "articulated_iterations": gpu_kwargs.get("articulated_iterations"),
        "silhouette_weight": gpu_kwargs.get("silhouette_weight"),
        "depth_weight": gpu_kwargs.get("depth_weight"),
        "chroma_weight": gpu_kwargs.get("chroma_weight"),
        "collision_enabled": gpu_kwargs.get("collision_enabled"),
        "chain_space_enabled": gpu_kwargs.get("chain_space_enabled"),
        "motion_weight": gpu_kwargs.get("motion_weight"),
    }
    _json_dump(out_dir / "fit_plan.json", {"gpuKeep": keep_record, "plan": plan})
    print(
        json.dumps(
            {
                "units": len(units),
                "idleJobs": len(idle_jobs),
                "restJobs": len(rest_jobs),
                "gpuKeep": keep_record,
                "planErrors": [p for p in plan if p.get("error")],
                "out": str(out_dir),
            },
            indent=2,
        ),
        flush=True,
    )
    if args.dry_run:
        return 0
    if args.export_idle_ready:
        reports = []
        for row, choice in idle_jobs:
            sid = row["labSid"]
            try:
                mesh = Path(row["glb"]).resolve()
                if not mesh.is_file():
                    raise RuntimeError(f"missing GLB {mesh}")
                reports.append(export_idle_unit(row, choice, mesh=mesh, out_dir=out_dir))
                print(f"exported idle {sid}", flush=True)
            except Exception as exc:
                import traceback

                traceback.print_exc()
                print(f"ERROR {sid} idle-export: {exc}", flush=True)
                reports.append({"labSid": sid, "error": str(exc)})
        _json_dump(out_dir / "idle_export_report.json", {"reports": reports})
        errors = [row for row in reports if row.get("error")]
        print(json.dumps({"ok": not errors, "exported": len(reports) - len(errors), "errors": errors}, indent=2), flush=True)
        return 1 if errors else 0

    lock_path = global_cascade_batch_lock_path(ROOT)
    acquire_cascade_batch_lock(lock_path)
    reports: list[dict[str, Any]] = []
    for item in plan:
        if item.get("error"):
            reports.append({"labSid": item["labSid"], "error": item["error"]})
    try:
        jobs = idle_jobs + rest_jobs
        fitted_by_unit: dict[str, list[str]] = {}
        for row, choice in jobs:
            sid = row["labSid"]
            animation = str(choice.animation_name)
            groups = tuple(int(group) for group in choice.def_lab_groups)
            motion = [group for group in groups if group != IDLE_GROUP]
            if motion and all(
                group in SKIPPED_DEF_GROUPS or group not in CHOSEN_DEF_GROUPS
                for group in motion
            ):
                print(
                    f"skip {sid} {animation}: unshipped vertical DEF {motion}",
                    flush=True,
                )
                continue
            latest: dict[str, Any] | None = None
            try:
                mesh = Path(row["glb"]).resolve()
                if not mesh.is_file():
                    raise RuntimeError(f"missing GLB {mesh}")
                config = _build_config(choice, mesh, notebook_kwargs, args.notebook)
                if args.export_only:
                    payload = _load_clip_result(_clip_result_path(choice))
                else:
                    payload = fit_choice(
                        choice,
                        config=config,
                        gpu_kwargs=gpu_kwargs,
                        skip_existing=bool(args.skip_existing),
                    )
                fitted_by_unit.setdefault(sid, []).append(animation)
                latest = {
                    "labSid": sid,
                    "animation": animation,
                    "groups": list(choice.def_lab_groups),
                    "score": None if args.export_only else payload.get("score"),
                }
                reports.append(latest)
            except Exception as exc:
                import traceback

                traceback.print_exc()
                print(f"ERROR {sid} {animation}: {exc}", flush=True)
                latest = {"labSid": sid, "animation": animation, "error": str(exc)}
                reports.append(latest)
            finally:
                _write_progress(out_dir, reports, latest=latest)
                gc.collect()
                _release_gpu_workspace()
        if args.fit_only:
            for row in units:
                sid = row["labSid"]
                if sid in fitted_by_unit:
                    reports.append({"labSid": sid, "fitted": fitted_by_unit[sid]})
            _write_progress(out_dir, reports)
        else:
            for row in units:
                sid = row["labSid"]
                try:
                    mesh = Path(row["glb"]).resolve()
                    choices = select_unit_delivery_choices(all_choices, sid)
                    prefix = "Crusader" if sid == "h3_crusader" else "Unit"
                    out_root = out_dir / "units" / sid
                    clip_dir = out_root / "clips"
                    exported: list[dict[str, Any]] = []
                    for choice in choices:
                        payload = _load_clip_result(_clip_result_path(choice))
                        exported.extend(
                            export_choice_clips(choice, payload, mesh=mesh, clip_dir=clip_dir, prefix=prefix)
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
        release_cascade_batch_lock(lock_path)
    _json_dump(out_dir / "fit_report.json", {"reports": reports})
    errors = [row for row in reports if row.get("error")]
    print(json.dumps({"ok": not errors, "units": len(units), "clipRows": len(reports), "errors": errors}, indent=2), flush=True)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
