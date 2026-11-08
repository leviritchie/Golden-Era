#!/usr/bin/env python3
"""Unit-generic linked-master pipeline: one reel, one capture, bind-frame skin fit, per-clip export.

Steps:
  1. Derive the native in-game reel from the unit's corpus manifest and the
     shared DEF-group contract; materialize it as one numbered sprite sequence.
  2. Run a single vendor mocap capture over every frame (continuous bone motion,
     never chunked or stitched).
  3. Register and bind. The accepted-artifact path still requires a human-confirmed
     static registration before bind. The full-set automatic lane uses
     `--registration-policy idle_frame0_meshy_source_identity`: Meshy meshes were
     made from idle DEF group 2 frame 0, so camera and frozen bind are that plate
     with the documented yaw-0 / pitch-0 view. Unshipped DEF groups are skipped.
  4. Refine skin weights only, against every reel frame simultaneously, with
     the mocap bones fixed.
  5. Export one GLB per native clip (Unit_Idle, Unit_Move, ...) sliced from the
     master motion, plus a sprite|mesh comparison GIF of the whole reel.

Everything unit-specific comes from data: `--unit` selects the profile
(asset_profiles.get_profile, or a caller-injected idle-0 lane profile) and frozen
donor package (capture_candidates, or the Mixamo 25-joint lane default).
`--manifest` is the unit's sprite corpus; `--source-mesh` is the Meshy/SmartRig
surface generated from idle frame 0. If a unit's profile lacks `captureBind`,
the run stops with that message.

Generated-artifact only - not OE runtime.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image, ImageDraw

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))
_TOOL = EXPERIMENT.parents[1] / "tools/homm3_silhouette_pose_fit"
if str(_TOOL) not in sys.path:
    sys.path.insert(0, str(_TOOL))

from asset_profiles import get_profile  # noqa: E402
from capture_candidates import require_frozen_package  # noqa: E402
from eagle_glb import matrices_to_xyzw, write_skinned_glb  # noqa: E402
from gpu_cascade_batch_lock import cascade_batch_lock  # noqa: E402
from gpu_cascade_delivery import contract_name_for_group, contract_prefix_for_unit  # noqa: E402
from idle0_meshy_registration import write_idle0_meshy_registration  # noqa: E402
from authored_zoo_donors import pad_package_to_capacity  # noqa: E402
from linked_master_sequence import (  # noqa: E402
    IDLE_GROUP,
    MOVE_GROUP,
    all_sequence_indices,
    build_master_sequence,
    capture_master_sequence,
    effective_capture_capacity,
    export_segments,
    load_manifest,
    native_reel,
    reel_frame_count,
)
from paths import REPO  # noqa: E402
from pin import sha256_file  # noqa: E402
from prepare_move_bind_capture_bind import (  # noqa: E402
    load_capture,
    prepare_move_bind_capture_bind,
    require_capture_bind_spec,
)
from roc_copy import _load_unskinned_triangle_surface  # noqa: E402
from static_bind_registration import StaticRegistrationError, load_static_registration  # noqa: E402
from preview_move_bind_linked_reel import frame_camera, letterbox_sprite  # noqa: E402
from run_move_bind_t2_mocap_skin_fit import load_fixed_motion, load_skin_bundle, run as run_skin_fit  # noqa: E402
from run_skin_weight_pilot import skin_with  # noqa: E402
from skin_image_objective import SkinImageRenderer  # noqa: E402
from verify_calibrated_export import verify_calibrated_export  # noqa: E402

CLIPS_MANIFEST_SCHEMA = "homm3.linked-master-clips.v1"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_candidate_weights(weights_path: Path, skin: dict[str, Any]) -> np.ndarray:
    raw = np.load(weights_path, allow_pickle=False)
    stored_names = [
        item.decode("utf-8") if isinstance(item, bytes) else str(item) for item in np.asarray(raw["names"]).tolist()
    ]
    if stored_names != list(skin["names"]):
        raise ValueError("candidate weights joint order does not match the bind GLB")
    return np.asarray(raw["weights"], dtype=np.float64)


def pose_master(skin: dict[str, Any], fixed: dict[str, Any], weights: np.ndarray) -> np.ndarray:
    """Skin every reel frame with the refined weights (GPU, under the cascade lock)."""
    with cascade_batch_lock(REPO):
        transforms = torch.as_tensor(fixed["jointWorld"] @ skin["inverseBind"][None], dtype=torch.float32, device="cuda")
        rest = torch.as_tensor(
            np.column_stack((skin["vertices"], np.ones(len(skin["vertices"])))), dtype=torch.float32, device="cuda"
        )
        candidates = torch.einsum("fjkl,vl->fvjk", transforms[:, :, :3], rest).detach()
        posed = skin_with(candidates, torch.as_tensor(weights, dtype=torch.float32, device="cuda"))
        return posed.detach().cpu().numpy()


def export_native_clips(
    *,
    master: dict[str, Any],
    skin: dict[str, Any],
    fixed: dict[str, Any],
    weights: np.ndarray,
    posed: np.ndarray,
    output_dir: Path,
) -> dict[str, Any]:
    """One GLB per native clip, sliced from the continuous master motion."""
    unit = str(master["unit"])
    prefix = contract_prefix_for_unit(unit)
    frame_ms = float(master["sourceFrameMs"])
    clips_dir = output_dir / "clips"
    clips_dir.mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    for segment in export_segments(master):
        start, end = int(segment["globalStart"]), int(segment["globalEnd"])
        if end <= start:
            raise ValueError(f"segment {segment['clipKey']} is empty")
        name = contract_name_for_group(int(segment["defGroup"]), prefix)
        glb = clips_dir / f"{name}.glb"
        times = np.arange(end - start, dtype=np.float32) * frame_ms / 1000.0
        write_skinned_glb(
            glb,
            names=skin["names"], parents=skin["parents"],
            rest_local_rotation=skin["restLocalRotation"], rest_local_translation=skin["offsets"],
            inverse_bind=skin["inverseBind"], vertices=skin["vertices"], triangles=skin["triangles"],
            uvs=skin["uvs"], albedo=skin["albedo"], weights=weights,
            animation={"name": name, "times": times, "rotations": matrices_to_xyzw(fixed["localRotation"][start:end])},
        )
        parity = verify_calibrated_export(
            glb, expected_meshes=posed[start:end], expected_times=times, idle_frame=None, allow_root_motion=True
        )
        rows.append(
            {
                "contractName": name,
                "clipKey": segment["clipKey"],
                "defGroup": int(segment["defGroup"]),
                "globalStart": start,
                "globalEnd": end,
                "frameCount": end - start,
                "glb": str(glb).replace("\\", "/"),
                "glbSha256": sha256_file(glb),
                "exportParity": parity,
            }
        )
    manifest = {
        "schema": CLIPS_MANIFEST_SCHEMA,
        "unit": unit,
        "contractPrefix": prefix,
        "sourceFrameMs": frame_ms,
        "motionOwner": "linked_master_single_capture_fixed_length_rotations",
        "sharedSkinWeightsAcrossClips": True,
        "clips": rows,
        "proof": "generated-artifact - per-clip GLBs sliced from one master capture; not imported, built, or game-visible",
    }
    _write_json(clips_dir / "clips_manifest.json", manifest)
    return manifest


def render_master_gif(
    *,
    master: dict[str, Any],
    skin: dict[str, Any],
    posed: np.ndarray,
    camera_path: Path,
    output_dir: Path,
    resolution: int,
) -> dict[str, Any]:
    unit = str(master["unit"])
    base_camera = json.loads(camera_path.read_text(encoding="utf-8"))
    sprite_paths = [Path(row["numberedPng"]) for row in master["frames"]]
    if len(posed) != len(sprite_paths):
        raise ValueError(f"posed frames {len(posed)} != master sprites {len(sprite_paths)}")
    with cascade_batch_lock(REPO):
        camera = frame_camera(base_camera, posed, resolution)
        renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], camera, resolution)
        rgb, alpha = renderer.render(torch.as_tensor(posed, dtype=torch.float32, device="cuda"))
        mesh_rgb = rgb.detach().cpu().numpy() * alpha.detach().cpu().numpy()

    gif_frames = []
    for index, row in enumerate(master["frames"]):
        label = f"{row['clipKey']} f{int(row['localIndex']):02d} g{int(row['globalIndex']):03d} [{row['role']}]"
        sprite = letterbox_sprite(sprite_paths[index], resolution)
        mesh = np.clip(mesh_rgb[index], 0, 1)
        row_image = Image.new("RGB", (resolution * 2, resolution + 28), (12, 12, 16))
        draw = ImageDraw.Draw(row_image)
        draw.text((4, 6), label, fill="white")
        draw.text((4, 16), "sprite", fill=(180, 180, 200))
        draw.text((resolution + 4, 16), "mesh+skin (linked master mocap)", fill=(180, 180, 200))
        row_image.paste(Image.fromarray(np.uint8(sprite * 255)), (0, 28))
        row_image.paste(Image.fromarray(np.uint8(mesh * 255)), (resolution, 28))
        gif_frames.append(row_image)

    gif_path = output_dir / f"{unit}_linked_master.gif"
    gif_frames[0].save(
        gif_path, save_all=True, append_images=gif_frames[1:], duration=int(round(float(master["sourceFrameMs"]))), loop=0
    )
    contact_path = output_dir / f"{unit}_linked_master_contact.png"
    contact = Image.new("RGB", (gif_frames[0].size[0], gif_frames[0].size[1] * min(8, len(gif_frames))))
    step = max(1, len(gif_frames) // 8)
    for i, frame in enumerate(gif_frames[::step][:8]):
        contact.paste(frame, (0, i * gif_frames[0].size[1]))
    contact.save(contact_path)
    return {
        "gif": str(gif_path).replace("\\", "/"),
        "contact": str(contact_path.resolve()).replace("\\", "/"),
        "frameCount": len(gif_frames),
        "camera": {k: camera[k] for k in ("yawDeg", "pitchDeg", "scale", "offset", "framingPolicy", "resolution")},
    }


def run(
    *,
    unit: str,
    manifest_path: Path,
    output_dir: Path,
    source_mesh: Path,
    seconds: float,
    resolution: int,
    iterations: int,
    idle_bookend_frames: int,
    bind_group: int,
    bind_local_frame: int,
    min_camera_iou: float,
    strain_weight: float,
    overwrite: bool,
    static_registration: Path | None = None,
    registration_policy: str = "accepted_artifact",
    profile: dict[str, Any] | None = None,
    package: dict[str, Any] | None = None,
    registration_fit: str | None = None,
    allow_missing_move: bool = False,
    allow_short_donor: bool = False,
    skip_gif: bool = False,
) -> dict[str, Any]:
    if not source_mesh.is_file():
        raise FileNotFoundError(source_mesh)
    if registration_policy not in {"accepted_artifact", "idle_frame0_meshy_source_identity"}:
        raise ValueError(f"unknown registration_policy {registration_policy!r}")
    if registration_policy == "idle_frame0_meshy_source_identity":
        if int(bind_group) != IDLE_GROUP or int(bind_local_frame) != 0:
            raise ValueError("idle_frame0_meshy_source_identity requires --bind-group 2 --bind-local-frame 0")
        static_registration = None
    elif static_registration is None:
        raise StaticRegistrationError(
            "downstream bind/skin fitting requires an accepted static registration artifact"
        )
    else:
        payload = load_static_registration(Path(static_registration))
        acceptance = payload.get("acceptance") or {}
        if (
            acceptance.get("status") != "accepted"
            or acceptance.get("visualConfirmation") is not True
            or acceptance.get("accepted") is not True
            or acceptance.get("consumable") is not True
        ):
            raise StaticRegistrationError(
                f"static registration is not accepted (status={acceptance.get('status')!r}); "
                "fitting cannot consume an unverified registration"
            )
        if (payload.get("inputHashes") or {}).get("mesh") != sha256_file(source_mesh):
            raise StaticRegistrationError("static registration mesh hash does not match this mesh")
    if profile is None:
        profile = get_profile(unit)
    if profile.get("assetId") != unit:
        raise ValueError(f"profile for {unit!r} reports assetId {profile.get('assetId')!r}")
    require_capture_bind_spec(profile)  # fail before any GPU work if the profile cannot bind
    if package is None:
        package = require_frozen_package(unit, role="primary")
    if allow_missing_move or allow_short_donor:
        preview_manifest = load_manifest(manifest_path)
        preview_reel, _skipped = native_reel(
            preview_manifest,
            idle_bookend_frames=idle_bookend_frames,
            allow_missing_move=allow_missing_move,
        )
        needed = reel_frame_count(preview_reel, preview_manifest)
        if allow_short_donor:
            package = pad_package_to_capacity(package, needed)
    capacity = effective_capture_capacity(package)

    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"refusing to overwrite {output_dir} (pass --overwrite)")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    timings: dict[str, float] = {}
    started_total = time.perf_counter()

    step_started = time.perf_counter()
    master_dir = output_dir / "master_sequence"
    master = build_master_sequence(
        manifest_path,
        master_dir,
        pose_capacity=capacity,
        idle_bookend_frames=idle_bookend_frames,
        bind_group=bind_group,
        bind_local_frame=bind_local_frame,
        overwrite=True,
        allow_missing_move=allow_missing_move,
    )
    if master["unit"] != unit:
        raise ValueError(f"manifest is for {master['unit']!r}, but --unit is {unit!r}")
    timings["buildSequenceSeconds"] = time.perf_counter() - step_started

    step_started = time.perf_counter()
    capture_report = capture_master_sequence(
        master_dir, output_dir / "capture", overwrite=True, package=package
    )
    capture_path = Path(capture_report["capture"])
    timings["captureSeconds"] = capture_report["timings"]["captureSeconds"]
    timings["captureEncodeSeconds"] = capture_report["timings"]["encodeSeconds"]
    timings["captureModelLoadSeconds"] = capture_report["timings"]["modelLoadSeconds"]
    timings["captureTotalSeconds"] = time.perf_counter() - step_started

    bind_frame = int(master["bindGlobalIndex"])
    if registration_policy == "idle_frame0_meshy_source_identity":
        if bind_frame != 0:
            raise ValueError(f"idle-0 bind must be global index 0, got {bind_frame}")
        idle0 = Path(master["frames"][0]["sourcePng"])
        if int(master["frames"][0]["defGroup"]) != IDLE_GROUP or int(master["frames"][0]["localIndex"]) != 0:
            raise ValueError("linked master frame 0 is not idle group 2 local frame 0")
        surface = _load_unskinned_triangle_surface(source_mesh)
        capture = load_capture(capture_path)
        static_registration = output_dir / "idle0_registration.json"
        write_idle0_meshy_registration(
            output_path=static_registration,
            unit=unit,
            mesh_path=source_mesh,
            mesh_vertices=surface["vertices"],
            capture_path=capture_path,
            capture_joints=capture["positions"][0],
            capture_parents=capture["parents"],
            idle_frame0=idle0,
            bind_frame=0,
            mesh_triangles=surface["triangles"],
            fit=registration_fit,
        )
    bind_glb = output_dir / "capture_bind" / f"{unit}_linked_master_bind.glb"
    step_started = time.perf_counter()
    bind_report = prepare_move_bind_capture_bind(
        mesh_glb=source_mesh,
        capture_path=capture_path,
        out_glb=bind_glb,
        bind_frame=bind_frame,
        unit=unit,
        static_registration=static_registration,
        profile=profile,
    )
    timings["prepareBindSeconds"] = time.perf_counter() - step_started

    train_frames = all_sequence_indices(master)
    sprite_paths = [Path(row["numberedPng"]) for row in master["frames"]]
    skin_out = output_dir / "skin_fit"
    step_started = time.perf_counter()
    skin_report = run_skin_fit(
        skin_out,
        seconds=seconds,
        resolution=resolution,
        iterations=iterations,
        bind_glb=bind_glb,
        source_mesh=source_mesh,
        capture_path=capture_path,
        min_camera_iou=min_camera_iou,
        strain_weight=strain_weight,
        overwrite=True,
        reference_frame=bind_frame,
        sprite_paths=sprite_paths,
        train_frames=train_frames,
        holdout_frames=[],
        case_key=f"{unit}_linked_master",
        skip_synthetic=True,
        comparison_title=f"{unit} linked master",
        enable_checkpoints=False,
        crop_policy="shared_canvas",
        unit=unit,
        static_registration=static_registration,
    )
    timings["skinFitSeconds"] = time.perf_counter() - step_started

    step_started = time.perf_counter()
    skin = load_skin_bundle(bind_glb)
    fixed = load_fixed_motion(skin, capture_path, reference_frame=bind_frame)
    weights = load_candidate_weights(skin_out / "candidate_weights.npz", skin)
    posed = pose_master(skin, fixed, weights)
    clips = export_native_clips(master=master, skin=skin, fixed=fixed, weights=weights, posed=posed, output_dir=output_dir)
    timings["exportClipsSeconds"] = time.perf_counter() - step_started

    step_started = time.perf_counter()
    if skip_gif:
        preview = {"gif": None, "contact": None}
        timings["renderGifSeconds"] = 0.0
    else:
        preview = render_master_gif(
            master=master, skin=skin, posed=posed, camera_path=skin_out / "camera.json", output_dir=output_dir, resolution=resolution
        )
        timings["renderGifSeconds"] = time.perf_counter() - step_started
    timings["elapsedTotalSeconds"] = time.perf_counter() - started_total

    frame_count = int(master["frameCount"])
    report = {
        "ok": True,
        "proof": "generated-artifact",
        "visualAcceptance": "unreviewed",
        "paradigm": "owned_bones_capture_skeleton_bind_frame_skin_only",
        "unit": unit,
        "manifest": str(manifest_path).replace("\\", "/"),
        "manifestSha256": sha256_file(manifest_path),
        "sourceMesh": str(source_mesh).replace("\\", "/"),
        "sourceMeshSha256": sha256_file(source_mesh),
        "sourceMeshProvenance": (
            "meshy_idle_def_group_2_frame_0"
            if registration_policy == "idle_frame0_meshy_source_identity"
            else "declared by caller; this pipeline does not verify which sprite generated the mesh"
        ),
        "registrationPolicy": registration_policy,
        "staticRegistration": str(static_registration).replace("\\", "/") if static_registration else None,
        "outputDir": str(output_dir).replace("\\", "/"),
        "frameCount": frame_count,
        "poseCapacity": capacity,
        "idleBookendFrames": int(idle_bookend_frames),
        "bindGlobalIndex": bind_frame,
        "bindGroup": master["bindGroup"],
        "bindLocalFrame": master["bindLocalFrame"],
        "segments": master["segments"],
        "skippedClips": master["skippedClips"],
        "trainingFrameCount": len(train_frames),
        "skinObjectivePolicy": "all_frames_after_bind",
        "capture": str(capture_path).replace("\\", "/"),
        "captureSha256": sha256_file(capture_path),
        "bindGlb": str(bind_glb).replace("\\", "/"),
        "bindSha256": sha256_file(bind_glb),
        "bindSkeletonPlacement": bind_report["skeletonPlacement"],
        "skinFitDisposition": skin_report.get("disposition"),
        "skinFitReport": str(skin_out / "pilot_report.json").replace("\\", "/"),
        "clipsManifest": str(output_dir / "clips" / "clips_manifest.json").replace("\\", "/"),
        "clipContractNames": [row["contractName"] for row in clips["clips"]],
        "gif": preview["gif"],
        "contactSheet": preview["contact"],
        "timings": timings,
        "budgetNotes": {
            "skinFitBudgetSeconds": seconds,
            "perFrameCaptureSeconds": timings["captureSeconds"] / frame_count,
            "perFrameSkinFitSeconds": timings["skinFitSeconds"] / frame_count,
            "perFrameRenderSeconds": timings["renderGifSeconds"] / frame_count,
        },
    }
    _write_json(output_dir / "report.json", report)
    print(
        json.dumps(
            {
                "ok": True,
                "unit": unit,
                "frameCount": frame_count,
                "gif": report["gif"],
                "clips": report["clipContractNames"],
                "timings": timings,
                "disposition": skin_report.get("disposition"),
            },
            indent=2,
        )
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--unit", required=True, help="unit sid, e.g. h3_roc (profile + frozen donor package)")
    parser.add_argument("--manifest", type=Path, required=True, help="sprite corpus manifest.json for the unit")
    parser.add_argument("--source-mesh", type=Path, required=True, help="Meshy/SmartRig GLB generated from idle frame 0")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=900.0)
    parser.add_argument("--resolution", type=int, default=192)
    parser.add_argument("--iterations", type=int, default=240)
    parser.add_argument("--idle-bookend-frames", type=int, default=1)
    parser.add_argument(
        "--bind-group",
        type=int,
        default=MOVE_GROUP,
        help="DEF group of the bind cycle (default 0 = move). Use 2 for idle.",
    )
    parser.add_argument("--bind-local-frame", type=int, default=0, help="local frame inside that cycle")
    parser.add_argument("--min-camera-iou", type=float, default=0.48)
    parser.add_argument("--strain-weight", type=float, default=0.5)
    parser.add_argument(
        "--registration-policy",
        choices=("accepted_artifact", "idle_frame0_meshy_source_identity"),
        default="accepted_artifact",
    )
    parser.add_argument(
        "--static-registration",
        type=Path,
        help="accepted homm3.static-bind-registration.v1 artifact; required unless --registration-policy idle_frame0_meshy_source_identity",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if not 120 <= args.seconds <= 900:
        raise ValueError("skin fit budget must be between 120 and 900 seconds")
    if args.registration_policy == "accepted_artifact" and args.static_registration is None:
        raise ValueError("--static-registration is required unless --registration-policy idle_frame0_meshy_source_identity")

    def absolute(path: Path) -> Path:
        return (path if path.is_absolute() else REPO / path).resolve()

    run(
        unit=args.unit,
        manifest_path=absolute(args.manifest),
        output_dir=absolute(args.output),
        source_mesh=absolute(args.source_mesh),
        seconds=float(args.seconds),
        resolution=int(args.resolution),
        iterations=int(args.iterations),
        idle_bookend_frames=int(args.idle_bookend_frames),
        bind_group=int(args.bind_group),
        bind_local_frame=int(args.bind_local_frame),
        min_camera_iou=float(args.min_camera_iou),
        strain_weight=float(args.strain_weight),
        overwrite=bool(args.overwrite),
        static_registration=None if args.static_registration is None else absolute(args.static_registration),
        registration_policy=str(args.registration_policy),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
