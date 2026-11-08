#!/usr/bin/env python3
"""Mocap-only pretrained baseline. No recipes, weave, or idle-bookended output."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

import numpy as np
from diagnostic_preview import write_diagnostic_gifs
from evaluation import EVALUATION_CASES, EvaluationCase
from glb_skeleton import load_bind_skeleton
from idle_camera import camera_from_yaw, fit_idle_yaw_camera
from mesh_preview import (
    joint_world_from_pred_rot6d,
    prepare_albedo,
    proposal_source_pred_world,
    raster_mesh,
)
from mocap_preflight import (
    refuse_case_recipes,
    refuse_forbidden_inputs,
    refuse_holdout_without_freeze,
    run_structural_tests,
)
from model_runner import run_proposal
from motion_metrics import report_proposal_motion
from paths import MOCAP_BASELINE, MOCAP_KEEP_AUTHORITY, REPO, require_dir, require_file
from pin import BASELINE_SEED, build_pin, write_pin
from position_transfer import solve_fixed_length_clip, transfer_residuals
from preview import idle_alpha_bbox
from rig_adapter import build_reference


def _gpu_lock_waiting(repo: Path, *, timeout_sec: float = 1800.0, poll_sec: float = 5.0):
    """Wait for the exclusive GPU lock. Do not fall back to CPU."""
    sys.path.insert(0, str(REPO / "tools/homm3_silhouette_pose_fit"))
    from gpu_cascade_batch_lock import wait_for_cascade_batch_lock

    return wait_for_cascade_batch_lock(
        repo,
        timeout_sec=timeout_sec,
        poll_sec=poll_sec,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=sorted(EVALUATION_CASES))
    parser.add_argument("--run-name", required=True, help="New immutable run directory name")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=MOCAP_BASELINE,
        help="Run directory root. Diagnosis writes under mocap_diagnosis/; never overwrite mocap_baseline_v1",
    )
    parser.add_argument(
        "--preprocess",
        choices=("clip_locked_union_alpha_aabb", "vendor_per_frame_prepare_image"),
        default="clip_locked_union_alpha_aabb",
    )
    parser.add_argument(
        "--temporal-context",
        choices=("native", "repeat_to_24"),
        default="native",
    )
    parser.add_argument(
        "--require-vendor-parity",
        action="store_true",
        help="Refuse to run sprite recovery until vendor_parity/parity_report.json records a pass",
    )
    parser.add_argument(
        "--allow-holdout",
        action="store_true",
        help="Required to run a holdout case after the development configuration is frozen",
    )
    parser.add_argument("--skip-gif", action="store_true")
    return parser.parse_args()


def _prepare_asset(case: EvaluationCase, ref_dir: Path) -> dict[str, Path]:
    require_file(case.mesh, label="mesh")
    require_file(case.idle, label="idle frame")
    require_file(case.joint_names, label="joint names")
    written = build_reference(
        case.unit,
        case.mesh,
        None,
        ref_dir,
        joint_names_path=case.joint_names,
        source_facing=case.source_facing,
        memory_recipe_path=None,
    )
    skeleton = load_bind_skeleton(case.mesh)
    if skeleton.triangles is None or skeleton.vertices is None:
        raise ValueError(f"{case.mesh} has no skinned triangles")
    rig_path = written["rig"]
    rig = json.loads(rig_path.read_text(encoding="utf-8"))
    if rig.get("memoryPolicy") != "singleton_bind_reference":
        raise ValueError(f"mocap baseline requires singleton bind memory, got {rig.get('memoryPolicy')}")
    if int(rig.get("memoryCount", 0)) != 1:
        raise ValueError("mocap baseline refuses multi-pose memory")
    from PIL import Image

    clip_pngs = sorted(path for path in case.frames.glob("*.png") if path.stem.isdigit())
    if not clip_pngs:
        raise FileNotFoundError(f"no numbered PNG frames in {case.frames}")
    with Image.open(clip_pngs[0]) as clip0:
        width, height = clip0.size
    idle_cam = fit_idle_yaw_camera(
        vertices=skeleton.vertices,
        triangles=skeleton.triangles,
        idle_png=case.idle,
    )
    if case.idle_canvas_matches_clip:
        camera = idle_cam
        camera["cameraPlate"] = "idle"
    else:
        clip_bbox = idle_alpha_bbox(clip_pngs[0])
        camera = camera_from_yaw(
            yaw_deg=float(idle_cam["yawDeg"]),
            vertices=skeleton.vertices,
            idle_bbox=clip_bbox,
        )
        camera["cameraPlate"] = "clip_frame0_bbox"
        camera["yawSource"] = "idle_occupancy"
        camera["yawDegIdle"] = float(idle_cam["yawDeg"])
        camera["idleIou"] = idle_cam.get("iou")
    rig["camera"] = camera
    rig_path.write_text(json.dumps(rig, indent=2) + "\n", encoding="utf-8")
    bind_render = ref_dir / "bind_reference.png"
    raster_mesh(
        vertices=skeleton.vertices,
        triangles=skeleton.triangles,
        camera=rig["camera"],
        width=width,
        height=height,
        uvs=skeleton.uvs,
        albedo=prepare_albedo(skeleton.albedo),
        normals=skeleton.normals,
    ).save(bind_render)
    written["bind_render"] = bind_render
    written["rig"] = rig_path
    return written


def run_evaluation_case(
    case: EvaluationCase,
    *,
    run_name: str,
    allow_holdout: bool,
    skip_gif: bool,
    artifact_root: Path = MOCAP_BASELINE,
    preprocess_policy: str = "clip_locked_union_alpha_aabb",
    temporal_context: str = "native",
    require_vendor_parity: bool = False,
) -> dict[str, object]:
    wall_started = time.perf_counter()
    refuse_forbidden_inputs()
    refuse_case_recipes(case)
    refuse_holdout_without_freeze(case, allow_holdout=allow_holdout)
    if require_vendor_parity:
        from paths import MOCAP_DIAGNOSIS

        parity_path = MOCAP_DIAGNOSIS / "vendor_parity" / "parity_report.json"
        if not parity_path.is_file():
            raise FileNotFoundError(
                "vendor parity report is missing; stop sprite tuning until the control suite passes"
            )
        parity = json.loads(parity_path.read_text(encoding="utf-8"))
        if not parity.get("ok"):
            raise RuntimeError(
                f"vendor parity did not pass ({parity.get('failureClass')}); "
                "this is a control/setup failure, not proof that the model cannot handle HoMM3"
            )
    if not case.available:
        report = {
            "ok": False,
            "proof": "generated-artifact",
            "keepAuthority": MOCAP_KEEP_AUTHORITY,
            "case": case.key,
            "unit": case.unit,
            "clip": case.clip,
            "role": case.role,
            "available": False,
            "unavailableReason": case.unavailable_reason,
            "visualAcceptance": "unavailable_input",
            "runName": run_name,
        }
        upsert_acceptance_matrix(report, artifact_root=artifact_root)
        return report
    if Path(run_name).name != run_name or run_name in (".", ".."):
        raise ValueError("run-name must be a single directory name")
    timings: dict[str, float] = {}
    started = time.perf_counter()
    run_structural_tests()
    timings["preflightSec"] = time.perf_counter() - started
    out_dir = Path(artifact_root) / case.unit / case.clip / run_name
    if out_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing run: {out_dir}")
    out_dir.mkdir(parents=True)
    require_dir(case.frames, label="clip frames")
    started = time.perf_counter()
    written = _prepare_asset(case, out_dir / "reference")
    timings["assetPrepSec"] = time.perf_counter() - started
    pin = build_pin(
        case_key=case.key,
        mesh=case.mesh,
        frames=case.frames,
        idle=case.idle,
        joint_names=case.joint_names,
        bind_render=written["bind_render"],
    )
    write_pin(out_dir / "pin.json", pin)
    with _gpu_lock_waiting(REPO) as (_lock_path, lock_wait):
        timings["gpuLockWaitSec"] = float(lock_wait)
        infer_started = time.perf_counter()
        report = run_proposal(
            unit=case.unit,
            clip=case.clip,
            frame_dir=case.frames,
            idle_png=case.idle,
            reference_npz=written["reference"],
            out_dir=out_dir,
            reference_image_png=written["bind_render"],
            sequence_policy="clip_only",
            window_include_idle=False,
            seed=BASELINE_SEED,
            proposal_name="raw_proposal.npz",
            preprocess_policy=preprocess_policy,
            do_center_crop=preprocess_policy == "vendor_per_frame_prepare_image",
            dino_dtype="float16" if preprocess_policy == "vendor_per_frame_prepare_image" else "float32",
            temporal_context=temporal_context,
            cyclic=case.cyclic,
        )
        timings["inferenceSec"] = time.perf_counter() - infer_started
    raw_path = out_dir / "raw_proposal.npz"
    if not raw_path.is_file():
        raise FileNotFoundError("raw unmodified proposal was not written")
    transfer_started = time.perf_counter()
    skeleton = load_bind_skeleton(case.mesh)
    payload = np.load(raw_path)
    reference = np.load(written["reference"])
    pred_world = proposal_source_pred_world(
        pred_position=payload["pred_position"],
        reference=reference,
        skeleton=skeleton,
    )
    native_world = joint_world_from_pred_rot6d(
        pred_rot6d=payload["pred_rot6d"],
        skeleton=skeleton,
        source_to_model=reference["source_to_model"],
    )
    np.savez(
        out_dir / "native_transfer.npz",
        posed_joint_world=native_world.astype(np.float64),
        pred_world=pred_world.astype(np.float64),
    )
    motion = report.get("motion") or report_proposal_motion(
        pred_position=payload["pred_position"],
        pred_rot6d=payload["pred_rot6d"],
        parents=reference["parents"],
        bind_model=reference["ref_position"],
        joint_count=int(reference["J_valid"][0]),
    )
    position_worlds = solve_fixed_length_clip(
        pred_world=pred_world,
        skeleton=skeleton,
        temporal_blend=0.0,
        temporal_passes=0,
    )
    residuals = transfer_residuals(pred_world=pred_world, posed_world=position_worlds)
    np.savez(
        out_dir / "position_transfer_unsmoothed.npz",
        posed_joint_world=position_worlds.astype(np.float64),
        pred_world=pred_world.astype(np.float64),
        smoothing="disabled_for_diagnosis",
        historicalSmoothedComparison="artifacts/homm3_mocap_v2/mocap_baseline/*/mocap_baseline_v1/position_transfer.npz",
    )
    position_report: dict[str, object] = {
        "ran": True,
        "smoothing": "disabled_for_diagnosis",
        "historicalSmoothed": "mocap_baseline_v1/review_position_transfer.gif",
        "gatedOnBindOffset": False,
        **residuals,
        "motion": motion,
    }
    timings["transferSec"] = time.perf_counter() - transfer_started
    gif_paths = {}
    if not skip_gif:
        render_started = time.perf_counter()
        gif_paths = write_diagnostic_gifs(
            sprite_dir=case.frames,
            idle_png=case.idle,
            raw_npz=raw_path,
            rig_json=written["rig"],
            mesh_glb=case.mesh,
            dest_dir=out_dir,
            position_worlds=position_worlds,
            position_gif_name="review_position_transfer_unsmoothed.gif",
            plate_png=None if case.idle_canvas_matches_clip else next(
                path for path in sorted(case.frames.glob("*.png")) if path.stem.isdigit()
            ),
        )
        timings["renderSec"] = time.perf_counter() - render_started
    native_err = np.linalg.norm(native_world[:, :, :3, 3] - pred_world, axis=-1)
    report.update(
        {
            "keepAuthority": MOCAP_KEEP_AUTHORITY,
            "case": case.key,
            "runName": run_name,
            "role": case.role,
            "available": True,
            "drive": "native_rot_bind_basis_conversion",
            "seedDrive": None,
            "previewDrive": "native_rot",
            "visualAcceptance": "unreviewed_candidate",
            "outputBookends": False,
            "idleCanvasMatchesClip": case.idle_canvas_matches_clip,
            "preprocessPolicy": preprocess_policy,
            "temporalContext": temporal_context,
            "globalMotion": {
                "rootPolicy": "static_pos_joint_mask_index0_equals_reference",
                "rootTravelInterpretation": "zero_does_not_prove_absent_source_movement",
                "poseDisplacementIsNotMotion": True,
                "label": motion.get("label"),
                "countsAsMotion": motion.get("countsAsMotion"),
                "countsAsLimbAction": motion.get("countsAsLimbAction"),
                "rootRelativeMaxJointRange": motion.get("rootRelativeTemporal", {}).get("maxJointRange"),
                "articulationMaxJointRange": motion.get("rigidAlignedArticulation", {}).get("maxJointRange"),
                "rotationSo3FrameToFrameMaxRad": motion.get("rotationSo3", {}).get("frameToFrameMaxRad"),
                "rotationSo3FromFirstMaxRad": motion.get("rotationSo3", {}).get("fromFirstMaxRad"),
                "historicalRot6dAbsMean": motion.get("historicalRot6dVsIdentity", {}).get("predRot6dAbsMean"),
            },
            "positionTransfer": position_report,
            "predVsNativeMean": float(native_err.mean()),
            "predVsNativeMax": float(native_err.max()),
            "gifs": gif_paths,
            "timing": timings,
            "warmClipSec": sum(
                timings[key]
                for key in ("assetPrepSec", "inferenceSec", "transferSec", "renderSec")
                if key in timings
            ),
            "recurringAssetPrepSec": timings.get("assetPrepSec"),
            "oneTimeAssetPrepSec": None,
            "oneTimeNotes": "model download, venv, and first checkpoint load are outside this runner",
            "gpuLockWaitSec": timings.get("gpuLockWaitSec"),
            "preflightSec": timings.get("preflightSec"),
            "pin": str((out_dir / "pin.json")).replace("\\", "/"),
            "rawProposal": str(raw_path).replace("\\", "/"),
            "solveSec": time.perf_counter() - wall_started,
        }
    )
    (out_dir / "fit_report.json").write_text(
        json.dumps(report, indent=2, default=_json_default) + "\n", encoding="utf-8"
    )
    upsert_acceptance_matrix(report, artifact_root=artifact_root)
    return report


def _json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value).replace("\\", "/")
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def upsert_acceptance_matrix(
    report: dict[str, object], *, artifact_root: Path = MOCAP_BASELINE
) -> Path:
    artifact_root.mkdir(parents=True, exist_ok=True)
    path = artifact_root / "acceptance_matrix.json"
    payload: dict[str, object] = {
        "proof": "generated-artifact",
        "visualAcceptanceRule": "user visual review only; numerical scores do not approve a clip",
        "rows": [],
    }
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
    rows = list(payload.get("rows") or [])
    key = (report.get("case"), report.get("runName"))
    rows = [row for row in rows if (row.get("case"), row.get("runName")) != key]
    position = report.get("positionTransfer")
    rows.append(
        {
            "case": report.get("case"),
            "runName": report.get("runName"),
            "role": report.get("role"),
            "available": report.get("available"),
            "unavailableReason": report.get("unavailableReason"),
            "visualAcceptance": report.get("visualAcceptance"),
            "warmClipSec": report.get("warmClipSec"),
            "recurringAssetPrepSec": report.get("recurringAssetPrepSec"),
            "gpuLockWaitSec": report.get("gpuLockWaitSec"),
            "gifs": report.get("gifs"),
            "positionTransferRan": position.get("ran") if isinstance(position, dict) else None,
            "motionLabel": (report.get("globalMotion") or {}).get("label")
            if isinstance(report.get("globalMotion"), dict)
            else None,
            "countsAsLimbAction": (report.get("globalMotion") or {}).get("countsAsLimbAction")
            if isinstance(report.get("globalMotion"), dict)
            else None,
            "predVsNativeMean": report.get("predVsNativeMean"),
            "globalMotion": report.get("globalMotion"),
            "pin": report.get("pin"),
        }
    )
    payload["rows"] = rows
    path.write_text(json.dumps(payload, indent=2, default=_json_default) + "\n", encoding="utf-8")
    return path


def main() -> int:
    args = parse_args()
    case = EVALUATION_CASES[str(args.case)]
    report = run_evaluation_case(
        case,
        run_name=args.run_name,
        allow_holdout=bool(args.allow_holdout),
        skip_gif=bool(args.skip_gif),
        artifact_root=Path(args.artifact_root),
        preprocess_policy=str(args.preprocess),
        temporal_context=str(args.temporal_context),
        require_vendor_parity=bool(args.require_vendor_parity),
    )
    print(json.dumps(report, indent=2, default=_json_default), flush=True)
    if not report.get("available", False):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
