#!/usr/bin/env python3
"""Fit every shipped Crusader combat clip with the notebook GPU cascade.

Idle (DEF group 2) is concatenated in front of the other groups so the
cascade can pose later frames from a stable rest. Those idle frames are
then sliced out before GLB export. They are not part of Walk, Attack, or
the other Olden Era contracts.

The mesh is the audited Meshy smart-rig, replacing the broken owned-bind
master. Delivery is skinned-mesh GLBs through CrusaderOwnedSkinnedLabBuild.
"""
from __future__ import annotations

import argparse
import ast
import gc
import json
import shutil
import sys
import time
from dataclasses import fields, replace
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
MESHY_RIGIDIZED = ROOT / "artifacts/meshy_downloads/h3_crusader_smartrigged_rigidized.glb"
DEFAULT_OUT = ROOT / "artifacts/crusader_pose_pipeline/gpu_cascade_skinned"
GPU_RUN_NAME = "gpu_cascade_delivery"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_cascade_batch_lock import (  # noqa: E402
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    release_cascade_batch_lock,
)
from gpu_cascade_delivery import (  # noqa: E402
    CONTRACT_BY_GROUP,
    IDLE_GROUP,
    SKIPPED_DEF_GROUPS,
    clip_result_matches_current_keep,
    delivery_poses_by_group,
    require_pose_units_degrees,
    write_oriented_clip_glb,
    write_oriented_master_glb,
)
from run_crusader_full_animation_set import (  # noqa: E402
    _literal_config_kwargs,
    _notebook_config,
    _prepare_smartrig,
)

NOTEBOOK_FIT_ASSIGNMENTS = {
    "SIMPLE_DEPTH_DEPTH_WEIGHT": "depth_weight",
    "SIMPLE_DEPTH_SILHOUETTE_WEIGHT": "silhouette_weight",
    "SIMPLE_DEPTH_DEPTH_TOLERANCE": "depth_tolerance",
    "SIMPLE_DEPTH_DEPTH_ROBUST_DELTA": "depth_robust_delta",
    "SIMPLE_DEPTH_CHROMA_WEIGHT": "chroma_weight",
    "SIMPLE_DEPTH_CHROMA_TOLERANCE": "chroma_tolerance",
    "SIMPLE_DEPTH_CHROMA_ROBUST_DELTA": "chroma_robust_delta",
    "SIMPLE_DEPTH_CHROMA_ERROR_SCALE": "chroma_error_scale",
    "SIMPLE_DEPTH_CHROMA_SCALE": "chroma_scale",
    "SIMPLE_DEPTH_CHROMA_RESOLUTION": "chroma_resolution",
    "SIMPLE_DEPTH_COLLISION_ENABLED": "collision_enabled",
    "SIMPLE_DEPTH_COLLISION_SAMPLE_COUNT": "collision_sample_count",
    "SIMPLE_DEPTH_COLLISION_GEODESIC_MIN_HOPS": "collision_geodesic_min_hops",
    "SIMPLE_DEPTH_COLLISION_MARGIN_BODY_LENGTHS": "collision_margin_body_lengths",
    "SIMPLE_DEPTH_COLLISION_WEIGHT": "collision_weight",
    "SIMPLE_DEPTH_PROFILE_INIT_ENABLED": "profile_init_enabled",
    "SIMPLE_DEPTH_PROFILE_INIT_FRAME": "profile_init_frame",
    "SIMPLE_DEPTH_PROFILE_INIT_TARGET_DIR": "profile_init_target_dir",
    "SIMPLE_DEPTH_PROFILE_INIT_YAW_MIN_DEG": "profile_init_yaw_min_deg",
    "SIMPLE_DEPTH_PROFILE_INIT_YAW_MAX_DEG": "profile_init_yaw_max_deg",
    "SIMPLE_DEPTH_PROFILE_INIT_YAW_STEP_DEG": "profile_init_yaw_step_deg",
    "SIMPLE_DEPTH_PROFILE_INIT_ROLL_RANGE_DEG": "profile_init_roll_range_deg",
    "SIMPLE_DEPTH_PROFILE_INIT_ROLL_STEP_DEG": "profile_init_roll_step_deg",
    "SIMPLE_DEPTH_PROFILE_INIT_FIT_MARGIN": "profile_init_fit_margin",
    "SIMPLE_DEPTH_PROFILE_INIT_TOP_K": "profile_init_top_k",
    "SIMPLE_DEPTH_PROFILE_INIT_CAMERA_BASIS_MODE": "profile_init_camera_basis_mode",
    "SIMPLE_DEPTH_PROFILE_INIT_WORLD_UP_AXIS": "profile_init_world_up_axis",
    "SIMPLE_DEPTH_PROFILE_INIT_RESOLUTION": "profile_init_resolution",
    "SIMPLE_DEPTH_PROFILE_INIT_MAX_DIMENSION": "profile_init_max_dimension",
    "SIMPLE_DEPTH_ROOT_ROTATION_FIRST_FRAME_LIMIT_DEG": "root_rotation_first_frame_limit_deg",
    "SIMPLE_DEPTH_ROOT_ROTATION_PER_FRAME_LIMIT_DEG": "root_rotation_per_frame_limit_deg",
    "SIMPLE_DEPTH_ROOT_ROTATION_CAMERA_UP_LIMIT_DEG": "root_rotation_camera_up_limit_deg",
    "SIMPLE_DEPTH_ROOT_ROTATION_DEFER_CAMERA_UP": "root_rotation_defer_camera_up",
    "CASCADE_ROOT_SEARCH_ENABLED": "root_search_enabled",
    "CASCADE_ROOT_TRANSLATION_AXES": "root_translation_axes",
    "CASCADE_ROOT_TRANSLATION_LIMIT_BODY_LENGTHS": "root_translation_limit_body_lengths",
    "CASCADE_ROOT_TRANSLATION_RADIUS_BODY_LENGTHS": "root_translation_radius_body_lengths",
    "CASCADE_SEED_PREVIOUS_FRAME": "seed_previous_frame",
    "CASCADE_JOINT_SEARCH_AXES": "joint_search_axes",
    "CASCADE_JOINT_DIAGONAL_AXES": "joint_diagonal_axes",
    "CASCADE_JOINT_STEP_DEG": "joint_step_deg",
    "CASCADE_FINE_JOINT_STEP_DEG": "fine_joint_step_deg",
    "CASCADE_JOINT_ADAPTIVE_STEP_ENABLED": "joint_adaptive_step_enabled",
    "CASCADE_JOINT_STEP_SCORE_COARSE": "joint_step_score_coarse",
    "CASCADE_JOINT_STEP_SCORE_FINE": "joint_step_score_fine",
    "CASCADE_JOINT_STEP_SCORE_NORM": "joint_step_score_norm",
    "CASCADE_JOINT_SCORE_RASTER_BATCH": "joint_score_raster_batch",
    "CASCADE_JOINT_ABSOLUTE_GAIN_WEIGHT": "joint_absolute_gain_weight",
    "CASCADE_JOINT_UNIQUE_GAIN_WEIGHT": "joint_unique_gain_weight",
    "CASCADE_FINE_UNIQUE_GAIN_WEIGHT": "fine_unique_gain_weight",
    "CASCADE_JOINT_COLLISION_POSITIVE_ABS_SLACK": "joint_collision_positive_abs_slack",
    "CASCADE_JOINT_TEMPORAL_CONSENSUS_ENABLED": "joint_temporal_consensus_enabled",
    "CASCADE_JOINT_TEMPORAL_CONSENSUS_TIE_BONUS": "joint_temporal_consensus_tie_bonus",
    "CASCADE_JOINT_TEMPORAL_CONSENSUS_BIDIRECTIONAL": "joint_temporal_consensus_bidirectional",
    "CASCADE_JOINT_TEMPORAL_CONSENSUS_IDLE_END": "joint_temporal_consensus_idle_end",
    "CASCADE_JOINT_TEMPORAL_CONSENSUS_INDEPENDENT_PASSES": "joint_temporal_consensus_independent_passes",
    "CASCADE_JOINT_TEMPORAL_CONSENSUS_WHOLE_POSE": "joint_temporal_consensus_whole_pose",
    "CASCADE_SCORE_MODE": "score_mode",
    "CASCADE_DENSE_SEMANTIC_MODEL_ID": "dense_semantic_model_id",
    "CASCADE_DENSE_SEMANTIC_FEATURE_LAYERS": "dense_semantic_feature_layers",
    "CASCADE_DENSE_SEMANTIC_LOCAL_RADIUS": "dense_semantic_local_radius",
    "CASCADE_DENSE_SEMANTIC_POSITION_WEIGHT": "dense_semantic_position_weight",
    "CASCADE_DENSE_SEMANTIC_BATCH_SIZE": "dense_semantic_batch_size",
    "CASCADE_DENSE_SEMANTIC_RASTER_SCALE": "dense_semantic_raster_scale",
    "CASCADE_DENSE_SEMANTIC_SUBJECT_CROP": "dense_semantic_subject_crop",
    "CASCADE_DENSE_SEMANTIC_SUBJECT_PADDING_FRAC": "dense_semantic_subject_padding_frac",
    "CASCADE_GRADIENT_LADDER_ENABLED": "gradient_ladder_enabled",
    "CASCADE_GRADIENT_LADDER_ITERATIONS": "gradient_ladder_iterations",
    "CASCADE_GRADIENT_LADDER_STEP_DEGS": "gradient_ladder_step_degs",
    "CASCADE_GRADIENT_LADDER_MIN_GRADIENT_NORM": "gradient_ladder_min_gradient_norm",
    "CASCADE_CHAIN_SPACE_ENABLED": "chain_space_enabled",
    "CASCADE_CHAIN_SPACE_MODE": "chain_space_mode",
    "CASCADE_CHAIN_SPACE_ITERATIONS": "chain_space_iterations",
    "CASCADE_CHAIN_SPACE_STEP_DEGS": "chain_space_step_degs",
    "CASCADE_CHAIN_SPACE_MIN_GRADIENT_NORM": "chain_space_min_gradient_norm",
    "CASCADE_CHAIN_SPACE_TRUST_RADIUS_DEG": "chain_space_trust_radius_deg",
    "CASCADE_CHAIN_SPACE_TRUST_RADIUS_MIN_DEG": "chain_space_trust_radius_min_deg",
    "CASCADE_CHAIN_SPACE_TRUST_RADIUS_MAX_DEG": "chain_space_trust_radius_max_deg",
    "CASCADE_CHAIN_SPACE_MIN_CLIP_IMPROVEMENT": "chain_space_min_clip_improvement",
    "CASCADE_SA_ENABLED": "sa_enabled",
    "CASCADE_SA_RESTARTS": "sa_restarts",
    "CASCADE_SA_ITERATIONS": "sa_iterations",
    "CASCADE_SA_INITIAL_TEMPERATURE": "sa_initial_temperature",
    "CASCADE_SA_FINAL_TEMPERATURE": "sa_final_temperature",
    "CASCADE_SA_PERTURBATION_SCALE_DEG": "sa_perturbation_scale_deg",
    "CASCADE_SA_BONE_FRACTION": "sa_bone_fraction",
    "CASCADE_SA_SEED": "sa_seed",
    "CASCADE_SA_SEED_FROM_CURRENT": "sa_seed_from_current",
    "CASCADE_SA_MIN_BONE_DEPTH": "sa_min_bone_depth",
    "CASCADE_SA_COLLISION_WEIGHT": "sa_collision_weight",
    "CASCADE_PHYSICS_SMOOTH_ENABLED": "physics_smooth_enabled",
    "CASCADE_PHYSICS_SMOOTH_OUTLIER_WINDOW": "physics_smooth_outlier_window",
    "CASCADE_PHYSICS_SMOOTH_OUTLIER_SIGMA": "physics_smooth_outlier_sigma",
    "CASCADE_PHYSICS_SMOOTH_OUTLIER_MIN_DEG": "physics_smooth_outlier_min_deg",
    "CASCADE_PHYSICS_SMOOTH_OUTLIER_MIN_TRANSLATION": "physics_smooth_outlier_min_translation",
    "CASCADE_PHYSICS_SMOOTH_STIFFNESS": "physics_smooth_stiffness",
    "CASCADE_PHYSICS_SMOOTH_DT": "physics_smooth_dt",
    "CASCADE_PHYSICS_SMOOTH_SUBSTEPS": "physics_smooth_substeps",
    "CASCADE_PHYSICS_SMOOTH_GRAVITY": "physics_smooth_gravity",
    "CASCADE_PHYSICS_SMOOTH_GRAVITY_WEIGHT": "physics_smooth_gravity_weight",
    "CASCADE_PHYSICS_SMOOTH_GRAVITY_MIN_BONE_DEPTH": "physics_smooth_gravity_min_bone_depth",
    "CASCADE_PHYSICS_SMOOTH_ROOT_VERTICAL_AXIS": "physics_smooth_root_vertical_axis",
    "CASCADE_IK_ENABLED": "ik_enabled",
    "CASCADE_IK_KEYPOINTS_PATH": "ik_keypoints_path",
    "CASCADE_IK_BONE_ROLES_PATH": "ik_bone_roles_path",
    "CASCADE_IK_KEYPOINTS_SOURCE": "ik_keypoints_source",
    "CASCADE_IK_MISS_DEPTH_TOLERANCE": "ik_miss_depth_tolerance",
    "CASCADE_IK_MISS_MIN_COMPONENT_AREA": "ik_miss_min_component_area",
    "CASCADE_IK_MISS_MAX_PAIRS": "ik_miss_max_pairs",
    "CASCADE_IK_ITERATIONS": "ik_iterations",
    "CASCADE_IK_MAX_STEP_DEG": "ik_max_step_deg",
    "CASCADE_IK_REQUIRE_IMPROVEMENT": "ik_require_improvement",
    "CASCADE_IK_BLOB_IOU_TARGET": "ik_blob_iou_target",
    "CASCADE_IK_PROXIMAL_MIN_DEPTH": "ik_proximal_min_depth",
    "CASCADE_IK_PROXIMAL_MAX_STEP_DEG": "ik_proximal_max_step_deg",
    "CASCADE_IK_MAX_CHAIN_DEPTH": "ik_max_chain_depth",
    "CASCADE_IK_REPAIR_DILATE_PX": "ik_repair_dilate_px",
    "CASCADE_IK_BLOB_SEARCH_ROUNDS": "ik_blob_search_rounds",
    "CASCADE_BASE_POSE_ENABLED": "base_pose_enabled",
    "CASCADE_BASE_POSE_ITERATIONS": "base_pose_iterations",
    "CASCADE_MID_POSE_ENABLED": "mid_pose_enabled",
    "CASCADE_MID_POSE_ITERATIONS": "mid_pose_iterations",
    "CASCADE_MID_JOINT_STEP_DEG": "mid_joint_step_deg",
    "CASCADE_ROOT_REFIT_AFTER_BASE_ENABLED": "root_refit_after_base_enabled",
    "CASCADE_ROOT_REFIT_TRANSLATION_BODY_LENGTHS": "root_refit_translation_body_lengths",
    "CASCADE_ROOT_REFIT_TRANSLATION_STEP_BODY_LENGTHS": "root_refit_translation_step_body_lengths",
    "CASCADE_ROOT_REFIT_ROTATION_DEG": "root_refit_rotation_deg",
    "CASCADE_ROOT_REFIT_ROTATION_STEP_DEG": "root_refit_rotation_step_deg",
    "CASCADE_BRANCH_RESCUE_ENABLED": "branch_rescue_enabled",
    "CASCADE_BRANCH_RESCUE_BLOCK_SIZE": "branch_rescue_block_size",
    "CASCADE_SKIP_TINY_BONES": "skip_tiny_bones",
    "CASCADE_MIN_LEAF_LENGTH_FRAC": "min_leaf_length_frac",
    "CASCADE_FINE_ONLY_LEAF_LENGTH_FRAC": "fine_only_leaf_length_frac",
    "CASCADE_BONE_ORDER_MODE": "bone_order_mode",
    "CASCADE_SEARCH_BONES": "search_bones",
    "CASCADE_INCLUDE_UNLISTED_SEARCH_BONES": "include_unlisted_search_bones",
    "CASCADE_FREEZE_ROOT_AFTER_ROOT_STAGE": "freeze_root_after_root_stage",
    "CASCADE_FINE_ROOT_ENABLED": "fine_root_enabled",
    "CASCADE_ARTICULATED_ITERATIONS": "articulated_iterations",
    "CASCADE_FINE_ITERATIONS": "fine_iterations",
}


def _json_dump(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _notebook_assignment_literals(notebook: Path) -> dict[str, Any]:
    payload = json.loads(Path(notebook).read_text(encoding="utf-8"))
    wanted = set(NOTEBOOK_FIT_ASSIGNMENTS)
    found: dict[str, Any] = {}
    for cell in payload.get("cells", []):
        source = "".join(cell.get("source", []))
        if "CASCADE_FINE_ITERATIONS" not in source and "SIMPLE_DEPTH_DEPTH_WEIGHT" not in source:
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
                except (ValueError, TypeError):
                    raise RuntimeError(
                        f"notebook assignment {target.id} is not a literal; "
                        "refusing to guess GPU cascade knobs"
                    ) from None
    missing = sorted(wanted - set(found))
    if missing:
        raise RuntimeError(
            "notebook is missing GPU cascade literals: " + ", ".join(missing)
        )
    return found


def notebook_gpu_fit_kwargs(notebook: Path) -> dict[str, Any]:
    literals = _notebook_assignment_literals(notebook)
    return {
        NOTEBOOK_FIT_ASSIGNMENTS[name]: value
        for name, value in literals.items()
    }


def _load_cull_alpha_shadows():
    path = TOOL / "roc_semantic_hybrid_setup.py"
    source = path.read_text(encoding="utf-8")
    marker = "\nraw_sources, culled_targets = cull_alpha_shadows"
    if marker not in source:
        raise RuntimeError(
            "roc_semantic_hybrid_setup.py no longer has the alpha-shadow cull call site"
        )
    preamble = source.split(marker, 1)[0]
    namespace: dict[str, Any] = {"__name__": "roc_semantic_hybrid_setup_cull"}
    exec(compile(preamble, str(path), "exec"), namespace, namespace)
    fn = namespace.get("cull_alpha_shadows")
    if not callable(fn):
        raise RuntimeError("failed to load cull_alpha_shadows from the setup preamble")
    return fn


def select_crusader_delivery_choices(choices) -> list:
    selected = []
    covered: set[int] = set()
    for choice in choices:
        if choice.unit_sid != "h3_crusader" or choice.source_kind != "authentic_def":
            continue
        groups = tuple(int(group) for group in choice.def_lab_groups)
        if not groups or groups[0] != IDLE_GROUP:
            continue
        ship = [
            group
            for group in groups
            if group in CONTRACT_BY_GROUP
            and group not in SKIPPED_DEF_GROUPS
            and not (group == IDLE_GROUP and len(groups) > 1)
        ]
        if not ship:
            continue
        overlap = set(ship) & covered
        if overlap:
            raise RuntimeError(
                f"DEF group(s) {sorted(overlap)} are covered by more than one picker sequence"
            )
        covered.update(ship)
        selected.append(choice)
    missing = sorted(set(CONTRACT_BY_GROUP) - covered)
    if missing:
        raise RuntimeError(f"missing crusader delivery DEF groups: {missing}")
    return selected


def _choice_overrides(choice, mesh: Path) -> dict[str, Any]:
    from roc_semantic_hybrid_widgets import _materialize_def_choice, meshy_rigidization_report_for

    pilot_dir, camera_fit, meta = _materialize_def_choice(ROOT, choice)
    frame_dir = f"frames_def12_nn_{choice.animation_name}"
    return {
        "src_glb": Path(mesh).resolve(),
        "meshy_rigidization_report": meshy_rigidization_report_for(Path(mesh).resolve()),
        "require_meshy_rigidization": True,
        "unit_name": choice.unit_name,
        "animation_name": choice.animation_name,
        "pilot_dir": pilot_dir,
        "camera_fit_path": camera_fit,
        "frame_indices": (),
        "target_frame_dir": frame_dir,
        "shadow_culled_frame_dir": f"{frame_dir}_shadow_culled",
        "target_depth_dir": f"{frame_dir}_depth_vda",
        "def_lab_frame_dir": choice.def_lab_frame_dir,
        "def_lab_group": choice.def_lab_groups,
        "def_expected_count": choice.def_expected_counts,
        "def_nn_upscale_meta": meta,
        "semantic_enabled": False,
        "semantic_only": False,
        "semantic_dense_weight": 0.0,
    }


def _gpu_output_dir(choice) -> Path:
    return Path(choice.pilot_dir) / GPU_RUN_NAME


def _clip_result_path(choice) -> Path:
    return _gpu_output_dir(choice) / "gpu_clip_result.json"


def _expected_def_frame_count(def_expected_count) -> int:
    """Authentic DEF materialize stores a single-group count as an int."""
    if def_expected_count is None:
        raise ValueError("authentic DEF source requires def_expected_count")
    if isinstance(def_expected_count, (str, bytes)):
        raise TypeError("def_expected_count must be an int or a sequence of ints")
    if isinstance(def_expected_count, int):
        return int(def_expected_count)
    return sum(int(count) for count in def_expected_count)


def _resolve_pilot_paths(config) -> tuple[Path, Path, Path, Path]:
    pilot = Path(config.pilot_dir)
    raw = Path(config.target_frame_dir)
    if not raw.is_absolute():
        raw = pilot / raw
    culled = Path(config.shadow_culled_frame_dir)
    if not culled.is_absolute():
        culled = pilot / culled
    depth = Path(config.target_depth_dir)
    if not depth.is_absolute():
        depth = pilot / depth
    return pilot, raw, culled, depth


def _materialize_def_source_or_refresh_stale_cache(config) -> Any:
    from roc_semantic_hybrid_experiment import _materialize_def_source

    try:
        return _materialize_def_source(config)
    except RuntimeError as exc:
        message = str(exc).lower()
        stale = (
            "refusing to mix a new authentic def copy into" in message
            or "refusing to mix authentic def frames into" in message
            or (
                "refusing to mix" in message
                and "authentic def" in message
                and "delete that folder" in message
            )
        )
        if not stale:
            raise
        _pilot, raw, culled, depth = _resolve_pilot_paths(config)
        removed: list[str] = []
        for path in (raw, culled, depth):
            if path.is_dir():
                shutil.rmtree(path)
                removed.append(str(path))
        if not removed:
            raise
        print(
            f"stale DEF nn cache removed ({len(removed)} dirs); "
            f"rematerializing from live lab source: {raw}",
            flush=True,
        )
        return _materialize_def_source(config)


def prepare_gpu_targets(config) -> Any:
    from roc_semantic_hybrid_experiment import (
        _source_frame_indices,
        _validate_meshy_rigidization,
    )
    from run_vda_movement_depth import assert_vda_pipeline_cache, ensure_vda_pipeline_cache

    _validate_meshy_rigidization(config)
    config = _materialize_def_source_or_refresh_stale_cache(config)
    indices = _source_frame_indices(config)
    config = replace(config, frame_indices=indices)
    _pilot, raw, culled, depth = _resolve_pilot_paths(config)
    cull_alpha_shadows = _load_cull_alpha_shadows()
    cull_alpha_shadows(raw, culled)
    ensure_vda_pipeline_cache(culled, depth, fps=float(config.depth_video_fps))
    assert_vda_pipeline_cache(depth)
    expected = _expected_def_frame_count(config.def_expected_count)
    if len(indices) != expected:
        raise RuntimeError(
            f"{config.animation_name} materialized {len(indices)} frames, "
            f"expected concatenated {expected} from {config.def_lab_group}"
        )
    return config


def _load_clip_result(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not clip_result_matches_current_keep(payload):
        raise RuntimeError(
            f"{path} is not a current sprite-authority cascade result; re-run the fit"
        )
    return payload


def export_choice_clips(
    choice,
    payload: Mapping[str, Any],
    *,
    mesh: Path,
    clip_dir: Path,
) -> list[dict[str, Any]]:
    require_pose_units_degrees(payload, source=str(_clip_result_path(choice)))
    groups = tuple(int(group) for group in choice.def_lab_groups)
    counts = tuple(int(count) for count in choice.def_expected_counts)
    delivered = delivery_poses_by_group(payload["poses"], groups, counts)
    reports = []
    for group, poses in delivered.items():
        contract = CONTRACT_BY_GROUP[int(group)]
        dest = clip_dir / f"{contract}.glb"
        report = write_oriented_clip_glb(mesh, dest, poses, clip_name=contract)
        report.update(
            {
                "contractName": contract,
                "defGroup": int(group),
                "fitAnimation": choice.animation_name,
                "idlePrefixFrames": int(counts[0]) if groups and groups[0] == 2 else 0,
                "idleSuffixFrames": int(counts[-1]) if len(groups) >= 3 and groups[0] == 2 and groups[-1] == 2 else 0,
                "clipResultPath": str(_clip_result_path(choice)),
                "fitScore": payload.get("score"),
            }
        )
        _json_dump(dest.with_suffix(".json"), report)
        reports.append(report)
    return reports


def _release_gpu_workspace() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def fit_choice(choice, *, config, gpu_kwargs: Mapping[str, Any], skip_existing: bool) -> dict[str, Any]:
    from gpu_raster_depth_animation import run_gpu_depth_fit_from_hybrid_config

    result_path = _clip_result_path(choice)
    if skip_existing and result_path.is_file():
        existing = json.loads(result_path.read_text(encoding="utf-8"))
        if clip_result_matches_current_keep(existing):
            print(f"reuse {choice.animation_name}: {result_path}", flush=True)
            return existing
        print(f"stale cascade result, refitting {choice.animation_name}", flush=True)
    config = prepare_gpu_targets(config)
    started = time.perf_counter()
    print(
        f"fit {choice.animation_name} groups={list(choice.def_lab_groups)} "
        f"frames={len(config.frame_indices)}",
        flush=True,
    )
    try:
        solved = run_gpu_depth_fit_from_hybrid_config(
            config,
            output_dir=_gpu_output_dir(choice),
            **gpu_kwargs,
        )
        result_path = Path(solved.pose_result["clipResultPath"])
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        if not clip_result_matches_current_keep(payload):
            raise RuntimeError(f"new cascade result failed keep fingerprint: {result_path}")
        print(
            f"fitted {choice.animation_name} score={payload.get('score')} "
            f"elapsed={time.perf_counter() - started:.1f}s vetoes={payload.get('collisionVetoCount')}",
            flush=True,
        )
        return payload
    finally:
        _release_gpu_workspace()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK)
    parser.add_argument("--mesh", type=Path, default=MESHY_RIGIDIZED)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument("--fit-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", default="", help="comma-separated animation names")
    args = parser.parse_args()
    if args.export_only and args.fit_only:
        raise SystemExit("use either --fit-only or --export-only, not both")

    _prepare_smartrig()
    mesh = Path(args.mesh).resolve()
    if mesh != MESHY_RIGIDIZED.resolve():
        raise RuntimeError(f"this delivery path is locked to the audited smartrig mesh: {MESHY_RIGIDIZED}")

    import roc_semantic_hybrid_widgets as widgets

    choices = select_crusader_delivery_choices(widgets.discover_asset_choices(ROOT))
    requested = {part.strip() for part in str(args.only).split(",") if part.strip()}
    if requested:
        choices = [choice for choice in choices if choice.animation_name in requested]
        if not choices:
            raise RuntimeError(f"no crusader delivery choices matched --only {sorted(requested)}")

    gpu_kwargs = notebook_gpu_fit_kwargs(args.notebook)
    notebook_kwargs = _literal_config_kwargs(args.notebook, require_dino=False)
    out_root = Path(args.out).resolve()
    clip_dir = out_root / "clips"
    plan = [
        {
            "animation": choice.animation_name,
            "groups": list(choice.def_lab_groups),
            "counts": list(choice.def_expected_counts),
            "contracts": [
                CONTRACT_BY_GROUP[int(group)]
                for group in choice.def_lab_groups
                if int(group) in CONTRACT_BY_GROUP
            ],
        }
        for choice in choices
    ]
    print(json.dumps({"plan": plan, "out": str(out_root)}, indent=2), flush=True)
    if args.dry_run:
        return 0

    lock_path = global_cascade_batch_lock_path(ROOT)
    acquire_cascade_batch_lock(lock_path)
    try:
        return _run_locked_delivery(
            args=args,
            choices=choices,
            mesh=mesh,
            gpu_kwargs=gpu_kwargs,
            notebook_kwargs=notebook_kwargs,
            out_root=out_root,
            clip_dir=clip_dir,
            plan=plan,
            requested=requested,
        )
    finally:
        release_cascade_batch_lock(lock_path)


def _run_locked_delivery(
    *,
    args,
    choices,
    mesh: Path,
    gpu_kwargs: Mapping[str, Any],
    notebook_kwargs: Mapping[str, Any],
    out_root: Path,
    clip_dir: Path,
    plan: list[dict[str, Any]],
    requested: set[str],
) -> int:
    from roc_semantic_hybrid_experiment import RocHybridConfig

    exported: list[dict[str, Any]] = []
    for choice in choices:
        overrides = _choice_overrides(choice, mesh)
        config_kwargs = dict(notebook_kwargs)
        config_kwargs.update(overrides)
        valid = {field.name for field in fields(RocHybridConfig)}
        unknown = sorted(set(config_kwargs) - valid)
        if unknown:
            raise TypeError("unsupported RocHybridConfig fields: " + ", ".join(unknown))
        config = _notebook_config(RocHybridConfig, config_kwargs, notebook=args.notebook)
        config = replace(
            config,
            semantic_enabled=False,
            semantic_only=False,
            semantic_dense_weight=0.0,
            require_meshy_rigidization=True,
        )
        if args.export_only:
            payload = _load_clip_result(_clip_result_path(choice))
        else:
            payload = fit_choice(
                choice,
                config=config,
                gpu_kwargs=gpu_kwargs,
                skip_existing=bool(args.skip_existing),
            )
        if args.fit_only:
            continue
        exported.extend(export_choice_clips(choice, payload, mesh=mesh, clip_dir=clip_dir))

    if not args.fit_only:
        master = write_oriented_master_glb(mesh, out_root / "crusader_smartrig_master.glb")
        shipped = {item["contractName"] for item in exported}
        missing = sorted(set(CONTRACT_BY_GROUP.values()) - shipped)
        if requested:
            missing = [name for name in missing if any(name in item.get("contracts", []) for item in plan)]
        elif missing:
            raise RuntimeError(f"delivery is missing contracts: {missing}")
        manifest = {
            "mesh": str(mesh),
            "master": master,
            "clips": exported,
            "idlePolicy": (
                "idle DEF group 2 ships as Crusader_Idle; when concatenated in front of "
                "other groups during fitting it is stripped from those delivery clips"
            ),
            "motionRoot": "camera-space motion root is omitted from Unity clips",
        }
        _json_dump(out_root / "delivery_manifest.json", manifest)
        print(json.dumps({"ok": True, "clips": len(exported), "master": master["master"]}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
