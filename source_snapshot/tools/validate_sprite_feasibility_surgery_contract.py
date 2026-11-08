#!/usr/bin/env python3
"""Fail-closed write-path gate for sprite feasibility surgery.

The runner may only write under artifacts/sprite_feasibility/. It must not
target live fused-push payloads or artifacts/meshy_downloads/.
"""
from __future__ import annotations

import argparse
import ast
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIT = ROOT / "tools" / "homm3_silhouette_pose_fit"
REQUIRED_TOKENS = (
    "sprite_pose_feasibility.py",
    "sprite_body_surgery.py",
    "run_sprite_feasibility_surgery.py",
)
REQUIRED_RUNNER_NEEDLES = (
    "assert_write_path",
    "acquire_cascade_batch_lock",
    "artifacts/sprite_feasibility",
    "singleClipOnly",
    "neverMasterGlb",
    "poseUnits",
    "write_vision_check",
    "rootBasisUnchanged",
    "notOccupancyGate",
    "side_view_flight_better",
    "flyer_spine_chain_bones",
    "moveFramesOnly",
    "horizontalRatio",
    "spineAlign",
    "spineAlignAfter",
    "bellyRoll",
    "bellyAlignAfter",
    "flyer_per_frame_attitude_search",
    "spine_level_score",
    "perFrameAttitude",
    "perFrameSpineAfter",
    "spineLevelAfter",
    "mask_principal_axis_xy",
    "spine_sprite_axis_score",
    "mask_body_core_axis_xy",
    "spine_is_image_plane",
    "leftoverFillDeferred",
    "flight_phase_sprite_axis",
    "rotate_bone_deg_within_limit",
    "leftoverFillDeferredReason",
    "flight_rest_frame_candidates",
    "flightRestFrames",
    "copy_spine_pose",
    "flyer_frame_is_perch_trap",
    "flyer_frame_is_pitch_trap",
    "flyer_attitude_donor_frame",
    "seededFrom",
    "shared_skeleton_pose_first",
    "pose_bidirectional_velocity_rms",
    "flyer_shared_phase_attitude_search",
    "rotate_bone_deg_shared_within_limit",
    "temporalWrap",
    "clip_wraps_temporally",
    "flyer_measure_move_attitude",
    "independentPerFrameSearch",
    "copy_phase_skeleton",
    "flyer_frame_is_camera_trap",
    "cameraTrap",
    "preservePipelinePoses",
    "PIPELINE_REFINE_SPINE_STEPS_DEG",
    "clip_source",
    "flyer_shared_phase_belly_roll",
    "previous_rows_same_phase",
    "samePhaseOnly",
    "phase_baked_fly_rest",
    "identity_joint_keep_root_poses",
    "frame_rest_source",
    "bake_lbs_pose_to_rest",
    "architectureAccept",
    "phase_glide_rest_rotation",
    "phase_glide_wing_spread",
    "phase_glide_symmetric_wing_spread",
    "spread_labeled_wing_vertices",
    "symmetric_raised_wing_destinations",
    "earlySymmetry",
    "wingDivergence",
    "ANATOMY_FIT_STAGES",
    "anatomy_tpose_snip_rotation",
    "tpose_stretched_bridge_faces",
    "snip_tpose_bridges",
    "labeledWingSpread",
    "rotation_aligning_bases",
    "load_unit_anatomy_catalog",
    "_anatomyCatalog",
    "anatomy_catalog_ventral",
    "anatomy_visual_body_chain",
    "operate_shared_skeleton_temporal",
    "shared_skeleton_temporal",
    "copy_joints_keep_dest_root",
    "seed_frame_from_inertial",
    "substantial_occupancy_better",
    "temporal_coarse_combos",
    "combo_pruned_by_collision_bounds",
    "collisionBoundPrune",
    "inertialSeed",
    "leftover_trial_illegal",
    "seed_frame_pipeline_relative",
    "strainVeto",
    "copy_anatomical_delta",
    "ANATOMICAL_AXES",
    "modelFrameAxes",
    "unique_joint_pose_count",
    "operate_insert_missing_symmetric",
    "leftover_symmetric_insert_parents",
    "anatomy_joints_xy",
    "insert_missing_symmetric",
    "sameRoundReaim",
    "asymmetric_fine_tune",
    "ASYMMETRIC_REST_LENGTH_SCALES",
    "symmetric_bone_fit",
    "next_anatomy_fit_stage",
    "rotate_bilateral_pair_deg_shared",
    "SYMMETRIC_BONE_STEPS_DEG",
    "ARCHITECTURE_ACCEPT_NAMES",
    "symmetric_only",
    "_architectureSource",
    "skipMeshBoneRepair",
    "abbreviatedSymmetricOnly",
)


def _fail(message: str) -> None:
    raise SystemExit(f"FAIL validate_sprite_feasibility_surgery_contract: {message}")


def _require(cond: bool, message: str) -> None:
    if not cond:
        _fail(message)


def _read(path: Path) -> str:
    if not path.is_file():
        _fail(f"missing {path}")
    return path.read_text(encoding="utf-8")


def validate_lock_tokens() -> None:
    text = _read(FIT / "gpu_cascade_batch_lock.py")
    for token in REQUIRED_TOKENS:
        _require(token in text, f"SCRIPT_TOKENS missing {token}")


def validate_runner_source() -> None:
    runner = _read(FIT / "run_sprite_feasibility_surgery.py")
    for needle in REQUIRED_RUNNER_NEEDLES:
        _require(needle in runner, f"runner missing {needle}")
    tree = ast.parse(runner)
    writes: list[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            name = ""
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in {"copy2", "write_text", "write_bytes", "dump", "save"}:
                for arg in list(node.args) + [kw.value for kw in node.keywords]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        writes.append(arg.value)
            self.generic_visit(node)

    Visitor().visit(tree)
    for value in writes:
        lowered = value.replace("\\", "/")
        if "meshy_downloads" in lowered or "fused_push_v24_pipeline" in lowered:
            _fail(f"runner contains a live write path literal: {value}")


def validate_write_path_gate() -> None:
    import sys

    if str(FIT) not in sys.path:
        sys.path.insert(0, str(FIT))
    from sprite_pose_feasibility import assert_write_path, work_tree_root

    work = work_tree_root(ROOT) / "_contract_probe" / "round_00"
    work.mkdir(parents=True, exist_ok=True)
    probe = work / "probe.txt"
    probe.write_text("ok\n", encoding="utf-8")
    _require(assert_write_path(probe, repo_root=ROOT) == probe.resolve(), "work-tree write path refused")
    try:
        assert_write_path(ROOT / "artifacts" / "meshy_downloads" / "probe.glb", repo_root=ROOT)
        _fail("meshy_downloads write was allowed")
    except RuntimeError:
        pass
    try:
        assert_write_path(
            ROOT
            / "artifacts"
            / "pose_picker_runs"
            / "h3_goblin"
            / "idle"
            / "fused_push_v24_pipeline"
            / "gpu_clip_result.json",
            repo_root=ROOT,
        )
        _fail("fused_push write was allowed")
    except RuntimeError:
        pass
    try:
        with tempfile.TemporaryDirectory() as tmp:
            assert_write_path(Path(tmp) / "outside.glb", repo_root=ROOT)
        _fail("path outside artifacts/sprite_feasibility was allowed")
    except RuntimeError:
        pass
    probe.unlink(missing_ok=True)


def validate() -> None:
    for name in REQUIRED_TOKENS:
        _require((FIT / name).is_file(), f"missing implementation file {name}")
    _require((ROOT / "tools" / "validate_sprite_feasibility_surgery_contract.py").is_file(), "validator missing")
    validate_lock_tokens()
    validate_runner_source()
    validate_write_path_gate()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    validate()
    print("PASS validate_sprite_feasibility_surgery_contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
