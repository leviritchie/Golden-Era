#!/usr/bin/env python3
"""Move-bind Meshy T2 Roc on the Eagle capture skeleton: fixed mocap bones, skin refinement only.

Owned-bones paradigm. The rig is the mocap capture skeleton bound at move frame
0 (see prepare_move_bind_capture_bind.py); the mesh was generated from move
sprite frame 00, so frame 0 is the bind by construction. Motion is the saved
roc_flight capture replayed as fixed-length rotations (`reconstruct_ab` path A),
root travel removed. The GPU image objective adjusts skin weights only; bone
animation is never re-optimized.

Weights live in a per-vertex candidate support (RepairWeightField): each vertex
may redistribute weight among its initializer bones and the nearest bone of each
trainable region that is geometrically close. Region labels only decide which
coincident vertices weld and which edges the smoothness penalty spans; they do
not cap where a vertex's weight may go.

Generated-artifact only - not OE runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))
sys.path.insert(0, str(EXPERIMENT.parents[1] / "tools/homm3_silhouette_pose_fit"))

from donor_eagle import bind_world_matrices, skin_dense  # noqa: E402
from eagle_glb import matrices_to_xyzw, write_skinned_glb  # noqa: E402
from evaluation import EVALUATION_CASES  # noqa: E402
from glb_skeleton import load_bind_skeleton  # noqa: E402
from gpu_cascade_batch_lock import cascade_batch_lock  # noqa: E402
from paths import REPO, SOURCE_FRAME_MS  # noqa: E402
from pin import numbered_pngs, sha256_file  # noqa: E402
from prepare_move_bind_capture_bind import (  # noqa: E402
    DEFAULT_OUT as CAPTURE_BIND_GLB,
    MOVE_BIND_MESH,
    MOVE_CAPTURE,
    DEFAULT_UNIT,
    load_capture,
    prepare_move_bind_capture_bind,
    regions_sidecar_path,
)
from static_bind_registration import require_accepted_static_registration, require_bind_registration  # noqa: E402
from reconstruct_ab import reconstruct_ab  # noqa: E402
from run_skin_weight_pilot import (  # noqa: E402
    geometry_edges,
    letterbox_source_images,
    shared_canvas_source_images,
    skin_with,
    source_images,
    strain,
    union_square_crop,
)
from shape_gates import preservation_limit  # noqa: E402
from skin_camera_registration import register_camera  # noqa: E402
from skin_image_objective import SkinImageRenderer, image_loss, image_metrics  # noqa: E402
from skin_weight_contract import all_frame_objective_gate, holdout_gate, validate_support_candidate_weights  # noqa: E402
from topology_weight_field import RepairWeightField  # noqa: E402
from verify_calibrated_export import verify_calibrated_export  # noqa: E402

DEFAULT_OUT = REPO / "artifacts/homm3_mocap_v2/roc_move_bind_t2_v1/capture_skin_fit"
CASE_KEY = "roc_flight"
TRAIN_FRAMES = (1, 2, 3)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def digest(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def _save_gif(
    path: Path,
    targets: tuple,
    before: tuple,
    after: tuple,
    *,
    title: str,
    labels: tuple[str, str, str] = ("Target", "Initial skin", "Refined skin"),
) -> None:
    target_rgb, _, _ = targets
    arrays = [x.detach().cpu().numpy() for x in (target_rgb, before[0], after[0])]
    resolution = arrays[0].shape[1]
    frames = []
    for index in range(len(arrays[0])):
        row = Image.new("RGB", (resolution * 3, resolution + 32), (12, 12, 16))
        draw = ImageDraw.Draw(row)
        draw.text((4, 2), f"{title} frame {index:02d}", fill="white")
        for column, (label, values) in enumerate(zip(labels, arrays)):
            image = Image.fromarray(np.uint8(np.clip(values[index], 0, 1) * 255))
            row.paste(image, (column * resolution, 32))
            draw.text((column * resolution + 4, 18), label, fill="white")
        frames.append(row)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=int(round(SOURCE_FRAME_MS)), loop=0)


def load_skin_bundle(bind_glb: Path) -> dict[str, Any]:
    """Capture-skeleton bind GLB plus its region sidecar (pinned to the GLB hash)."""
    skeleton = load_bind_skeleton(bind_glb)
    if skeleton.inverse_bind is None:
        raise RuntimeError(f"{bind_glb} is missing inverse bind matrices")
    if skeleton.vertex_weights is None or skeleton.vertex_joints is None:
        raise RuntimeError(f"{bind_glb} is missing skin weights")
    joints = np.asarray(skeleton.vertex_joints, dtype=np.int64)
    sparse = np.asarray(skeleton.vertex_weights, dtype=np.float64)
    dense = np.zeros((len(skeleton.vertices), len(skeleton.names)), dtype=np.float64)
    for slot in range(joints.shape[1]):
        valid = sparse[:, slot] > 1e-8
        dense[np.arange(len(dense))[valid], joints[valid, slot]] += sparse[valid, slot]
    row = dense.sum(axis=1)
    if np.any(row < 1e-8):
        raise RuntimeError(f"{bind_glb} has vertices with zero skin weight")
    dense /= row[:, None]
    sidecar = json.loads(regions_sidecar_path(bind_glb).read_text(encoding="utf-8"))
    if sidecar["schema"] != "vertex_regions_v2":
        raise RuntimeError(f"unexpected regions sidecar schema {sidecar['schema']}")
    if sidecar["bindSha256"] != sha256_file(bind_glb):
        raise RuntimeError("regions sidecar was written for a different bind GLB")
    regions = np.asarray(sidecar["regions"], dtype=object)
    if len(regions) != len(skeleton.vertices):
        raise RuntimeError("regions sidecar vertex count does not match bind GLB")
    rest_local_rotation = np.asarray(skeleton.rest_local_rotation, dtype=np.float64)
    if float(np.abs(rest_local_rotation - np.eye(3)[None]).max()) > 1e-9:
        raise RuntimeError("capture-skeleton bind must have identity rest local rotations")
    # Sidecar support indices are in the prep's (capture) joint order; the GLB
    # writer reorders joints, so remap through names.
    names = list(skeleton.names)
    glb_index = {name: index for index, name in enumerate(names)}
    sidecar_names = list(sidecar["jointNames"])
    if sorted(sidecar_names) != sorted(names):
        raise RuntimeError("regions sidecar joint names do not match bind GLB")
    remap = np.asarray([glb_index[name] for name in sidecar_names], dtype=np.int64)
    support = np.zeros((len(regions), len(names)), dtype=bool)
    for vertex, joint_ids in enumerate(sidecar["candidateSupport"]):
        support[vertex, remap[np.asarray(joint_ids, dtype=np.int64)]] = True
    trainable = np.asarray(sidecar["trainable"], dtype=bool)
    if trainable.shape != (len(regions),):
        raise RuntimeError("regions sidecar train mask does not match vertex count")
    if np.any((dense > 1e-8) & ~support):
        raise RuntimeError("bind initial weights fall outside the sidecar candidate support")
    trainable_regions = sidecar["supportRule"].get("trainableRegions")
    if not isinstance(trainable_regions, list) or not trainable_regions:
        raise RuntimeError("regions sidecar supportRule.trainableRegions is missing or empty")
    unknown = sorted(set(trainable_regions) - set(sidecar["regionJoints"]))
    if unknown:
        raise RuntimeError(f"regions sidecar trainable regions are not profile regions: {unknown}")
    return {
        "unit": sidecar.get("unit"),
        "trainableRegions": [str(region) for region in trainable_regions],
        "candidateSupport": support,
        "trainable": trainable,
        "supportRule": sidecar["supportRule"],
        "vertices": np.asarray(skeleton.vertices, dtype=np.float64),
        "triangles": np.asarray(skeleton.triangles, dtype=np.int64),
        "uvs": np.asarray(skeleton.uvs, dtype=np.float64),
        "albedo": np.asarray(skeleton.albedo),
        "weights": dense,
        "regions": regions,
        "regionJoints": {str(k): tuple(str(b) for b in v) for k, v in sidecar["regionJoints"].items()},
        "names": list(skeleton.names),
        "parents": np.asarray(skeleton.parents, dtype=np.int64),
        "offsets": np.asarray(skeleton.rest_local_translation, dtype=np.float64),
        "inverseBind": np.asarray(skeleton.inverse_bind, dtype=np.float64),
        "restLocalRotation": rest_local_rotation,
        "restWorld": np.asarray(skeleton.rest_world, dtype=np.float64),
    }


def load_fixed_motion(
    skin: dict[str, Any], capture_path: Path, *, reference_frame: int = 0
) -> dict[str, Any]:
    """Saved capture as relative rotations on the bind-first rest (reconstruct_ab path A)."""
    reference_frame = int(reference_frame)
    capture = load_capture(capture_path)
    if sorted(capture["names"]) != sorted(skin["names"]):
        raise ValueError("bind joint names do not match the capture skeleton")
    # The GLB writer stores joints in loader (topological) order; permute the
    # capture into the bind's order by name and confirm the hierarchy is the same.
    capture_index = {name: index for index, name in enumerate(capture["names"])}
    order = np.asarray([capture_index[name] for name in skin["names"]], dtype=np.int64)
    capture_parent_names = [
        None if int(capture["parents"][index]) < 0 else capture["names"][int(capture["parents"][index])]
        for index in order
    ]
    bind_parent_names = [
        None if int(parent) < 0 else skin["names"][int(parent)] for parent in skin["parents"]
    ]
    if capture_parent_names != bind_parent_names:
        raise ValueError("bind hierarchy does not match the capture skeleton")
    positions = capture["positions"][:, order]
    reference = positions[reference_frame]
    aim_offsets = reference - reference[np.asarray(skin["parents"], dtype=np.int64).clip(0)]
    aim_offsets[0] = reference[0]
    ab = reconstruct_ab(
        capture_positions=positions,
        offsets=skin["offsets"],
        parents=skin["parents"],
        reference_frame=reference_frame,
        aim_offsets=aim_offsets,
    )
    local_rotation = np.asarray(ab["localRotation"], dtype=np.float64)
    frame0_from_rest = float(np.abs(local_rotation[reference_frame] - skin["restLocalRotation"]).max())
    if frame0_from_rest > 1e-6:
        raise ValueError(
            f"capture bind frame {reference_frame} must be identity on the bind skeleton, "
            f"got deviation {frame0_from_rest}"
        )
    length_error = float(ab["fixedLengthErrorMax"])
    if length_error > 1e-6:
        raise ValueError(f"fixed-length replay changed a bone length by {length_error}")
    return {
        "jointWorld": np.asarray(ab["jointWorldA"], dtype=np.float64),
        "localRotation": local_rotation,
        "captureSha256": capture["sha256"],
        "placement": {
            "policy": "reconstruct_ab_path_A_capture_relative_rotations_on_bind_first_rest",
            "captureReferenceFrame": reference_frame,
            "boneLengthErrorMax": length_error,
            "bindFrameLocalRotationFromRestMax": frame0_from_rest,
            "residualAMax": float(ab["residualAMax"]),
            "residualAMean": float(ab["residualAMean"]),
            "rootMotion": ab["captureToBind"]["root"],
            "twistPolicy": ab["twistPolicy"],
        },
        "bindFrameIsRest": True,
    }


def assert_frame0_is_rest(skin: dict[str, Any], motion: dict[str, Any], reference_frame: int = 0) -> float:
    reference_frame = int(reference_frame)
    posed = skin_dense(
        skin["vertices"], skin["weights"], motion["jointWorld"][reference_frame], skin["inverseBind"]
    )
    error = float(np.linalg.norm(posed - skin["vertices"], axis=1).max())
    limit = preservation_limit(skin["vertices"])
    if error > limit:
        raise ValueError(f"fixed motion frame 0 displaces bind vertices by {error} (limit {limit})")
    return error


def deformed_candidates(skin: dict[str, Any], motion: dict[str, Any]) -> torch.Tensor:
    transforms = torch.as_tensor(motion["jointWorld"] @ skin["inverseBind"][None], dtype=torch.float32, device="cuda")
    vertices = torch.as_tensor(
        np.column_stack((skin["vertices"], np.ones(len(skin["vertices"])))), dtype=torch.float32, device="cuda"
    )
    return torch.einsum("fjkl,vl->fvjk", transforms[:, :, :3], vertices).detach()


def make_field(skin: dict[str, Any]) -> RepairWeightField:
    """Per-vertex candidate-support field with one ownership id for the whole mesh.

    Region labels are soft here (a vertex's support may span regions), so the
    smoothness penalty must span every mesh edge and coincident vertices must
    weld regardless of label. Splitting ownership by region left the label
    boundaries unsmoothed and produced tearing sheets there.
    """
    return RepairWeightField(
        skin["vertices"], skin["triangles"], skin["weights"],
        ownership_ids=np.zeros(len(skin["vertices"]), dtype=np.int64),
        train_mask=skin["trainable"], allowed_support=skin["candidateSupport"],
        device="cuda",
    )


def fit(field, renderer, candidates, targets, edges, lengths, *, iterations, deadline, strain_weight, synthetic=False, callback=None):
    """Adam over the field's simplex deltas; image loss + strain + prior/smoothness penalty."""
    optimizer = torch.optim.Adam(field.parameters(), lr=0.06)
    history = []
    best_loss, best_state = float("inf"), None
    for step in range(iterations):
        if time.perf_counter() >= deadline:
            break
        optimizer.zero_grad(set_to_none=True)
        weights = field.weights()
        vertices = skin_with(candidates, weights)
        rgb, alpha = renderer.render(vertices)
        losses = image_loss(rgb, alpha, *targets)
        deformation, _ = strain(vertices, edges, lengths)
        penalty = field.penalty(weights)
        objective = losses["total"] + (0.0 if synthetic else strain_weight) * deformation + (1.0 if synthetic else 25.0) * penalty
        if not torch.isfinite(objective):
            raise ValueError("nonfinite skin fitting objective")
        score = float(objective.detach())
        if score < best_loss:
            best_loss = score
            best_state = {key: value.detach().clone() for key, value in field.state_dict().items()}
        objective.backward()
        torch.nn.utils.clip_grad_norm_(field.parameters(), 2.0)
        optimizer.step()
        if step % 25 == 0 or step == iterations - 1:
            row = {"step": step, "objective": score, "iou": float(losses["iou"].detach()), "strain": float(deformation.detach())}
            history.append(row)
            print(json.dumps(row), flush=True)
            if callback is not None and step % 100 == 0:
                callback(step, weights.detach())
    if best_state is None:
        raise TimeoutError("skin pilot budget expired before optimization")
    field.load_state_dict(best_state)
    return history


def run(
    output: Path,
    *,
    seconds: float,
    resolution: int,
    iterations: int,
    bind_glb: Path,
    source_mesh: Path,
    capture_path: Path,
    min_camera_iou: float,
    strain_weight: float,
    overwrite: bool,
    reference_frame: int = 0,
    sprite_paths: list[Path] | tuple[Path, ...] | None = None,
    train_frames: list[int] | None = None,
    holdout_frames: list[int] | None = None,
    case_key: str = CASE_KEY,
    skip_synthetic: bool = False,
    comparison_title: str | None = None,
    enable_checkpoints: bool = True,
    crop_policy: str = "bind_frame",
    unit: str = DEFAULT_UNIT,
    static_registration: Path | None = None,
) -> dict[str, Any]:
    if not source_mesh.is_file():
        raise FileNotFoundError(source_mesh)
    if not capture_path.is_file():
        raise FileNotFoundError(capture_path)
    registration = require_accepted_static_registration(
        static_registration,
        mesh_sha256=sha256_file(source_mesh),
        capture_sha256=sha256_file(capture_path),
        bind_frame=int(reference_frame),
    )
    if not bind_glb.is_file():
        prepare_move_bind_capture_bind(
            mesh_glb=source_mesh,
            capture_path=capture_path,
            out_glb=bind_glb,
            bind_frame=reference_frame,
            unit=unit,
            static_registration=static_registration,
        )
    require_bind_registration(
        json.loads(regions_sidecar_path(bind_glb).read_text(encoding="utf-8")),
        registration, sha256_file(Path(static_registration)),
    )
    skin = load_skin_bundle(bind_glb)
    if output.exists():
        if not overwrite:
            raise FileExistsError(f"refusing to overwrite pilot: {output} (pass --overwrite)")
        shutil.rmtree(output) if output.is_dir() else output.unlink()
    if skin["unit"] is not None and skin["unit"] != unit:
        raise RuntimeError(f"bind GLB sidecar was prepared for unit {skin['unit']!r}, not {unit!r}")
    motion = load_fixed_motion(skin, capture_path, reference_frame=reference_frame)
    frame0_rest_error = assert_frame0_is_rest(skin, motion, reference_frame=reference_frame)
    if sprite_paths is None:
        sprite_paths = numbered_pngs(EVALUATION_CASES[case_key].frames)
    else:
        sprite_paths = [Path(path) for path in sprite_paths]
    if len(sprite_paths) != len(motion["jointWorld"]):
        raise ValueError(
            f"sprite frame count {len(sprite_paths)} does not match capture length {len(motion['jointWorld'])}"
        )
    crop_frame = int(reference_frame)
    if crop_policy in {"letterbox", "shared_canvas"}:
        crop = None
        source_size = None
    elif crop_policy == "union":
        crop, source_size = union_square_crop(sprite_paths)
    elif crop_policy == "bind_frame":
        with Image.open(sprite_paths[crop_frame]) as first_sprite:
            box, source_size = first_sprite.getbbox(), first_sprite.size
        if box is None:
            raise ValueError(f"empty sprite alpha at bind frame {crop_frame}")
        size = min(source_size)
        crop = {"left": (source_size[0] - size) // 2, "top": (source_size[1] - size) // 2, "size": size}
    else:
        raise ValueError(f"unknown crop_policy {crop_policy!r}")
    output.mkdir(parents=True)
    pipeline_started = time.perf_counter()
    with cascade_batch_lock(REPO):
        started = time.perf_counter()
        deadline = started + seconds
        if crop_policy == "shared_canvas":
            move_targets, source_crop, source_size = shared_canvas_source_images(sprite_paths, resolution)
            bind_targets = tuple(tensor[reference_frame : reference_frame + 1] for tensor in move_targets)
            source_crop = {**source_crop, "policy": "shared_padded_canvas"}
        elif crop_policy == "letterbox":
            move_targets = letterbox_source_images(sprite_paths, resolution)
            bind_targets = tuple(tensor[reference_frame : reference_frame + 1] for tensor in move_targets)
            source_crop = {"left": 0, "top": 0, "size": resolution, "policy": "per_frame_letterbox"}
            source_size = (resolution, resolution)
        else:
            move_targets = source_images(sprite_paths, crop, resolution)
            bind_targets = tuple(tensor[reference_frame : reference_frame + 1] for tensor in move_targets)
            source_crop = crop
        placeholder = {
            "right": [1, 0, 0], "down": [0, -1, 0], "forward": [0, 0, 1],
            "scale": 50, "offset": [96, 96], "depth_center": 0, "depth_span": 10,
        }
        renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], placeholder, resolution)
        candidates = deformed_candidates(skin, motion)
        original = torch.as_tensor(skin["weights"], dtype=torch.float32, device="cuda")
        # Frame 0 of the fixed motion is the bind (gated above), so registering on
        # the bind rest and on the mocap frame-0 pose are the same thing.
        camera, camera_report = register_camera(
            renderer, skin["vertices"], *bind_targets,
            resolution=resolution, source_crop=source_crop, source_size=source_size, min_iou=min_camera_iou,
        )
        camera_report["registrationPolicy"] = (
            f"bind_rest_equals_mocap_frame_{reference_frame}_vs_sprite_frame_{reference_frame}"
        )
        renderer.set_camera(camera)
        _write_json(output / "camera_registration.json", camera_report)
        _write_json(output / "camera.json", camera_report.get("camera", camera))
        edges, lengths = geometry_edges(skin)
        with torch.no_grad():
            baseline = renderer.render(skin_with(candidates, original))
            registration_render = renderer.render(
                torch.as_tensor(skin["vertices"][None], dtype=torch.float32, device="cuda")
            )
        _save_gif(
            output / "bind_registration.gif",
            bind_targets,
            registration_render,
            registration_render,
            title=f"Camera registration (bind = mocap frame {reference_frame})",
            labels=(f"Sprite f{reference_frame:02d}", "Bind rest", "Bind rest"),
        )
        if skip_synthetic:
            synthetic_report = {"skipped": True, "reason": "linked_master_budget"}
        else:
            synthetic = make_field(skin)
            generator = torch.Generator(device="cuda").manual_seed(29)
            with torch.no_grad():
                synthetic.delta.copy_(torch.randn(synthetic.delta.shape, generator=generator, device="cuda") * 0.3)
            synth_indices, synth_holdout = [1, 2, 3], [4, 5]
            synth_targets = tuple(value[synth_indices].detach() for value in baseline)
            synth_distance = torch.as_tensor(
                np.stack([distance_transform_edt(a[..., 0] < 0.5) for a in synth_targets[1].cpu().numpy()]),
                device="cuda", dtype=torch.float32,
            )
            synth_targets = (*synth_targets, synth_distance)
            with torch.no_grad():
                synth_before = renderer.render(skin_with(candidates, synthetic.weights()))
            synthetic_history = fit(
                synthetic, renderer, candidates[synth_indices], synth_targets, edges, lengths,
                iterations=120, deadline=min(deadline - 60, time.perf_counter() + 90), strain_weight=strain_weight, synthetic=True,
            )
            with torch.no_grad():
                synth_after = renderer.render(skin_with(candidates, synthetic.weights()))
            synth_before_metrics = image_metrics(*synth_before, *move_targets[:2])
            synth_after_metrics = image_metrics(*synth_after, *move_targets[:2])
            before_error = float(np.mean([1 - synth_before_metrics[i]["iou"] for i in synth_holdout]))
            after_error = float(np.mean([1 - synth_after_metrics[i]["iou"] for i in synth_holdout]))
            perfect_metrics = image_metrics(*baseline, *move_targets[:2])
            floor = float(np.mean([1 - perfect_metrics[i]["iou"] for i in synth_holdout]))
            synthetic_report = {
                "beforeHoldoutError": before_error,
                "afterHoldoutError": after_error,
                "antialiasErrorFloor": floor,
                "passed": bool(before_error - floor > 1e-5 and after_error - floor < (before_error - floor) * 0.8),
                "history": synthetic_history,
                "gateEnforced": False,
                "note": "roc_flight move is 6 frames; synthetic holdout is logged, not enforced, for this clip length.",
            }
            _write_json(output / "synthetic_control.json", synthetic_report)
        field = make_field(skin)
        frame_count = len(sprite_paths)
        if train_frames is None:
            train_indices = list(TRAIN_FRAMES)
            holdout_indices = list(
                holdout_frames
                if holdout_frames is not None
                else [index for index in range(frame_count) if index not in train_indices and index != reference_frame]
            )
        else:
            train_indices = list(train_frames)
            holdout_indices = list(holdout_frames) if holdout_frames is not None else []
        if sorted(train_indices) != train_indices or len(set(train_indices)) != len(train_indices):
            raise ValueError("train_frames must be unique and sorted")
        if any(index < 0 or index >= frame_count for index in train_indices + holdout_indices):
            raise ValueError("train or holdout frame is outside the capture length")
        if set(train_indices) & set(holdout_indices):
            raise ValueError("train_frames and holdout_frames overlap")
        if not train_indices:
            raise ValueError("skin fit requires at least one training frame")
        train_targets = tuple(value[train_indices] for value in move_targets)

        checkpoint = None
        if enable_checkpoints:
            def checkpoint(step: int, weights: torch.Tensor) -> None:
                with torch.no_grad():
                    preview = renderer.render(skin_with(candidates, weights))
                path = output / f"move_checkpoint_{step:03d}.gif"
                _save_gif(path, move_targets, baseline, preview, title=f"Move skin checkpoint {step}")
                print(json.dumps({"checkpointGif": str(path)}), flush=True)

        history = fit(
            field, renderer, candidates[train_indices], train_targets, edges, lengths,
            iterations=iterations, deadline=deadline - 20, strain_weight=strain_weight, callback=checkpoint,
        )
        field.validate()
        learned = field.weights().detach()
        learned_np = learned.cpu().numpy()
        weight_gate = validate_support_candidate_weights(
            learned_np, skin["weights"], skin["candidateSupport"], skin["trainable"]
        )
        weight_gate["supportRule"] = skin["supportRule"]
        # Identity rest locals are enforced in load_skin_bundle, so FK of offsets is the bind.
        bind_rest = bind_world_matrices(skin["offsets"], skin["parents"])
        rest_vertices = skin_dense(skin["vertices"], learned_np, bind_rest, skin["inverseBind"])
        bind_limit = preservation_limit(skin["vertices"])
        bind_identity_error = float(np.linalg.norm(rest_vertices - skin["vertices"], axis=1).max())
        weight_gate["bindSkinIdentityMax"] = bind_identity_error
        weight_gate["bindSkinIdentityLimit"] = bind_limit
        weight_gate["bindSkinIdentityOk"] = bind_identity_error <= bind_limit
        np.savez_compressed(
            output / "candidate_weights.npz", weights=learned_np, names=np.asarray(skin["names"]), parents=skin["parents"]
        )
        report: dict[str, Any] = {
            "ok": True,
            "proof": "generated-candidate",
            "visualAcceptance": "unreviewed",
            "paradigm": "owned_bones_capture_skeleton_bind_frame_rest",
            "unit": unit,
            "motionOwner": "mocap_capture_fixed_length_rotations",
            "bind": str(bind_glb).replace("\\", "/"),
            "bindSha256": sha256_file(bind_glb),
            "sourceMesh": str(source_mesh).replace("\\", "/"),
            "capture": str(capture_path).replace("\\", "/"),
            "captureSha256": motion["captureSha256"],
            "trainingFrames": train_indices,
            "holdoutFrames": holdout_indices,
            "referenceFrame": int(reference_frame),
            "trainableRegions": list(skin["trainableRegions"]),
            "trainableVertexCount": int(skin["trainable"].sum()),
            "camera": camera_report,
            "synthetic": synthetic_report,
            "placement": motion["placement"],
            "frame0BindVertexErrorMax": frame0_rest_error,
            "field": field.support_stats(),
            "history": history,
            "solver": "fixed_mocap_bones_incremental_skin_weights",
            "objectiveWeights": {"image": 1.0, "edgeStrain": strain_weight, "priorAndSmoothness": 25.0},
        }
        with torch.no_grad():
            before_mesh = skin_with(candidates, original)
            after_mesh = skin_with(candidates, learned)
            rendered = renderer.render(after_mesh)
            _, before_ratio = strain(before_mesh, edges, lengths)
            _, after_ratio = strain(after_mesh, edges, lengths)
        before_metrics = image_metrics(*baseline, *move_targets[:2])
        after_metrics = image_metrics(*rendered, *move_targets[:2])
        held = [index for index in holdout_indices if index < len(after_metrics)]
        all_indices = list(range(len(after_metrics)))
        all_improvement = float(np.mean([after_metrics[i]["iou"] - before_metrics[i]["iou"] for i in all_indices]))
        improvement = (
            float(np.mean([after_metrics[i]["iou"] - before_metrics[i]["iou"] for i in held]))
            if held
            else all_improvement
        )
        row = {
            "before": before_metrics,
            "after": after_metrics,
            "holdoutIndices": held,
            "holdoutMeanIouImprovement": improvement if held else None,
            "allFrameMeanIouImprovement": all_improvement,
            "beforeEdgeRatioP95": float(torch.quantile(before_ratio.flatten(), 0.95)),
            "afterEdgeRatioP95": float(torch.quantile(after_ratio.flatten(), 0.95)),
            "fixedMotionSha256": digest(motion["jointWorld"]),
        }
        report["cases"] = {case_key: row}
        compare_title = comparison_title or case_key
        compare_gif = output / "skin_comparison.gif"
        _save_gif(compare_gif, move_targets, baseline, rendered, title=compare_title)
        times = np.arange(len(after_metrics), dtype=np.float32) * float(SOURCE_FRAME_MS) / 1000.0
        glb = output / "skin_candidate.glb"
        write_skinned_glb(
            glb,
            names=skin["names"], parents=skin["parents"],
            rest_local_rotation=skin["restLocalRotation"], rest_local_translation=skin["offsets"],
            inverse_bind=skin["inverseBind"], vertices=skin["vertices"], triangles=skin["triangles"],
            uvs=skin["uvs"], albedo=skin["albedo"], weights=learned_np,
            animation={
                "name": f"{case_key}_capture_refined_skin",
                "times": times,
                "rotations": matrices_to_xyzw(motion["localRotation"]),
            },
        )
        row["exportParity"] = verify_calibrated_export(
            glb, expected_meshes=after_mesh.cpu().numpy(), expected_times=times, idle_frame=None, allow_root_motion=True
        )
        row["compareGif"] = str(compare_gif).replace("\\", "/")
        row["candidateGlb"] = str(glb).replace("\\", "/")
        report["elapsedSeconds"] = time.perf_counter() - started
        report["cachedPipelineSecondsIncludingLockWait"] = time.perf_counter() - pipeline_started
        report["weightContract"] = weight_gate
        if held:
            report["objectivePolicy"] = "train_holdout"
            report["passedHoldouts"] = holdout_gate(report["cases"])
            report["passedAllFrameObjective"] = False
            passed_objective = bool(report["passedHoldouts"])
        else:
            report["objectivePolicy"] = "all_frames_after_bind"
            report["passedHoldouts"] = False
            report["passedAllFrameObjective"] = all_frame_objective_gate(report["cases"])
            passed_objective = bool(report["passedAllFrameObjective"])
        if not weight_gate["bindSkinIdentityOk"]:
            report["disposition"] = "rejected_bind_rest_identity_gate"
        elif passed_objective:
            report["disposition"] = "candidate_for_visual_review"
        else:
            report["disposition"] = "rejected_generalization_or_deformation_gate"
        _write_json(output / "pilot_report.json", report)
        print(
            json.dumps(
                {
                    "ok": report["ok"],
                    "disposition": report["disposition"],
                    "compareGif": row["compareGif"],
                    "holdoutIouImprovement": improvement,
                    "cameraIoU": camera_report["best"]["iou"],
                    "beforeIoU": [round(m["iou"], 3) for m in before_metrics],
                    "afterIoU": [round(m["iou"], 3) for m in after_metrics],
                },
                indent=2,
            ),
            flush=True,
        )
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--unit", default=DEFAULT_UNIT, help="profile id (asset_profiles.get_profile)")
    parser.add_argument("--bind", type=Path, default=CAPTURE_BIND_GLB)
    parser.add_argument("--source-mesh", type=Path, default=MOVE_BIND_MESH, help="Unrigged T2 surface used when --bind is missing")
    parser.add_argument("--capture", type=Path, default=MOVE_CAPTURE)
    parser.add_argument("--seconds", type=float, default=420)
    parser.add_argument("--resolution", type=int, default=192)
    parser.add_argument("--iterations", type=int, default=320)
    parser.add_argument("--min-camera-iou", type=float, default=0.48)
    parser.add_argument("--strain-weight", type=float, default=0.5, help="Weight of the log edge-strain term in the objective")
    parser.add_argument(
        "--static-registration",
        type=Path,
        required=True,
        help="accepted homm3.static-bind-registration.v1 artifact; required before skin fitting",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if not 120 <= args.seconds <= 900:
        raise ValueError("pilot budget must be between 120 and 900 seconds")

    def absolute(path: Path) -> Path:
        return (path if path.is_absolute() else REPO / path).resolve()

    run(
        absolute(args.output),
        seconds=args.seconds,
        resolution=args.resolution,
        iterations=args.iterations,
        bind_glb=absolute(args.bind),
        source_mesh=absolute(args.source_mesh),
        capture_path=absolute(args.capture),
        min_camera_iou=float(args.min_camera_iou),
        strain_weight=float(args.strain_weight),
        overwrite=bool(args.overwrite),
        unit=args.unit,
        static_registration=absolute(args.static_registration),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
