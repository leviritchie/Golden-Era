"""Time-bounded image-supervised skin fitting with immutable motion and mesh."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt
import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools/homm3_silhouette_pose_fit"))

from gpu_cascade_batch_lock import cascade_batch_lock
from run_shape_preserved import (
    CAPTURE_BY_CASE, EVALUATION_CASES, _load_frozen_prep, _write_json,
    get_profile, numbered_pngs, reconstruct_adapted, sha256_file,
)
from idle_calibration import load_or_create
from paths import SOURCE_FRAME_MS
from skin_image_objective import SkinImageRenderer, image_loss, image_metrics
from skin_weight_field import WeightField
from skin_weight_contract import holdout_gate, validate_candidate_weights
from donor_eagle import bind_world_matrices, skin_dense
from eagle_glb import matrices_to_xyzw, write_skinned_glb
from shape_gates import preservation_limit
from verify_calibrated_export import verify_calibrated_export


TRAIN = (2, 5, 8, 12, 17, 21)
TRAIN_REGIONS = ("wing_left", "wing_right", "neck_head", "tail", "torso")


def digest(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def load_sprite_rgba(path: Path) -> Image.Image:
    """Load a plate. Empty alpha is a recorded defect, not a stop, when accepted."""
    rgba = Image.open(path).convert("RGBA")
    if rgba.getbbox() is not None:
        return rgba
    if not os.environ.get("HOMM3_ACCEPT_EMPTY_ALPHA"):
        raise ValueError(f"empty sprite {path}")
    punched = rgba.copy()
    punched.putpixel((0, 0), (0, 0, 0, 255))
    return punched


def union_square_crop(paths: list[Path]) -> tuple[dict[str, int], tuple[int, int]]:
    """Square crop that contains every sprite foreground bbox on the shared canvas."""
    boxes: list[tuple[int, int, int, int]] = []
    source_size: tuple[int, int] | None = None
    for path in paths:
        image = load_sprite_rgba(path)
        if source_size is None:
            source_size = image.size
        elif image.size != source_size:
            raise ValueError(f"all sprites must share one canvas size; {path} is {image.size}, expected {source_size}")
        box = image.getbbox()
        if box is None:
            raise ValueError(f"empty sprite {path}")
        boxes.append(box)
    if source_size is None:
        raise ValueError("no sprite paths provided")
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[2] for box in boxes)
    bottom = max(box[3] for box in boxes)
    span = max(right - left, bottom - top, 1)
    span = min(int(span), min(source_size))
    center_x = (left + right) / 2.0
    center_y = (top + bottom) / 2.0
    crop_left = int(round(center_x - span / 2.0))
    crop_top = int(round(center_y - span / 2.0))
    crop_left = max(0, min(crop_left, source_size[0] - span))
    crop_top = max(0, min(crop_top, source_size[1] - span))
    crop = {"left": crop_left, "top": crop_top, "size": span}
    box = (crop_left, crop_top, crop_left + span, crop_top + span)
    for path, sprite_box in zip(paths, boxes):
        if sprite_box[0] < box[0] or sprite_box[1] < box[1] or sprite_box[2] > box[2] or sprite_box[3] > box[3]:
            raise ValueError(f"union sprite crop would clip foreground: {path}")
    return crop, source_size


def canonical_square_crop(source_size: tuple[int, int]) -> dict[str, int]:
    """Pad the shared DEF canvas to a square. Same rule as camera registration."""
    width, height = int(source_size[0]), int(source_size[1])
    if min(width, height) <= 0:
        raise ValueError(f"source_size must be positive, got {source_size}")
    size = max(width, height)
    return {
        "left": -((size - width) // 2),
        "top": -((size - height) // 2),
        "size": size,
    }


def shared_canvas_source_images(paths: list[Path], resolution: int):
    """Letterbox every frame on the same padded canvas. Foreground is never recentered."""
    source_size: tuple[int, int] | None = None
    for path in paths:
        with Image.open(path) as image:
            size = image.size
        if source_size is None:
            source_size = size
        elif size != source_size:
            raise ValueError(f"all sprites must share one canvas size; {path} is {size}, expected {source_size}")
    if source_size is None:
        raise ValueError("no sprite paths provided")
    crop = canonical_square_crop(source_size)
    rgb, alpha = [], []
    for path in paths:
        rgba = load_sprite_rgba(path)
        canvas = Image.new("RGBA", (crop["size"], crop["size"]), (0, 0, 0, 0))
        canvas.paste(rgba, (-crop["left"], -crop["top"]), rgba)
        raw = canvas.resize((resolution, resolution), Image.Resampling.LANCZOS)
        values = np.asarray(raw, dtype=np.float32) / 255.0
        alpha.append(values[..., 3:4])
        rgb.append(values[..., :3] * values[..., 3:4])
    alpha = np.stack(alpha)
    distances = np.stack([distance_transform_edt(a[..., 0] < 0.5) for a in alpha]).astype(np.float32)
    return (
        tuple(torch.as_tensor(value, device="cuda") for value in (np.stack(rgb), alpha, distances)),
        crop,
        source_size,
    )


def letterbox_source_images(paths: list[Path], resolution: int):
    """Per-frame letterbox from each sprite's own bbox (no shared crop gate)."""
    rgb, alpha = [], []
    for path in paths:
        rgba = load_sprite_rgba(path)
        box = rgba.getbbox()
        if box is None:
            raise ValueError(f"empty sprite {path}")
        cropped = rgba.crop(box)
        scale = min(resolution / cropped.size[0], resolution / cropped.size[1])
        size = (max(1, int(round(cropped.size[0] * scale))), max(1, int(round(cropped.size[1] * scale))))
        resized = cropped.resize(size, Image.Resampling.NEAREST)
        canvas = Image.new("RGBA", (resolution, resolution), (0, 0, 0, 255))
        canvas.paste(resized, ((resolution - size[0]) // 2, (resolution - size[1]) // 2), resized)
        values = np.asarray(canvas, dtype=np.float32) / 255.0
        alpha.append(values[..., 3:4])
        rgb.append(values[..., :3] * values[..., 3:4])
    alpha = np.stack(alpha)
    distances = np.stack([distance_transform_edt(a[..., 0] < 0.5) for a in alpha]).astype(np.float32)
    return tuple(torch.as_tensor(value, device="cuda") for value in (np.stack(rgb), alpha, distances))


def source_images(paths: list[Path], crop: dict, resolution: int):
    rgb, alpha = [], []
    box = (crop["left"], crop["top"], crop["left"] + crop["size"], crop["top"] + crop["size"])
    for path in paths:
        with Image.open(path) as image:
            bounds = image.getbbox()
            if bounds is None or bounds[0] < box[0] or bounds[1] < box[1] or bounds[2] > box[2] or bounds[3] > box[3]:
                raise ValueError(f"fixed source crop would clip foreground: {path}")
            raw = image.convert("RGBA").crop(box).resize((resolution, resolution), Image.Resampling.LANCZOS)
            values = np.asarray(raw, dtype=np.float32) / 255.0
        alpha.append(values[..., 3:4])
        rgb.append(values[..., :3] * values[..., 3:4])
    alpha = np.stack(alpha)
    distances = np.stack([distance_transform_edt(a[..., 0] < 0.5) for a in alpha]).astype(np.float32)
    return tuple(torch.as_tensor(value, device="cuda") for value in (np.stack(rgb), alpha, distances))


def prepare_motion(skin: dict, reference: np.ndarray, case: str) -> dict:
    with np.load(CAPTURE_BY_CASE[case], allow_pickle=False) as capture:
        positions = capture["pred_position"].copy()
    return reconstruct_adapted(
        capture_positions=positions, capture_reference_positions=reference,
        capture_offsets=skin["captureOffsets"], fitted_offsets=skin["offsets"],
        parents=skin["parents"], names=skin["names"],
        hub_names=tuple(get_profile("h3_roc")["wholeBodyHubs"]),
    )


def deformed_candidates(skin: dict, motion: dict) -> torch.Tensor:
    transforms = torch.as_tensor(motion["jointWorld"] @ skin["inverseBind"][None], dtype=torch.float32, device="cuda")
    vertices = torch.as_tensor(np.column_stack((skin["vertices"], np.ones(len(skin["vertices"])))), dtype=torch.float32, device="cuda")
    return torch.einsum("fjkl,vl->fvjk", transforms[:, :, :3], vertices).detach()


def skin_with(candidates: torch.Tensor, weights: torch.Tensor) -> torch.Tensor:
    return torch.einsum("fvjc,vj->fvc", candidates, weights)


def geometry_edges(skin: dict):
    tri = skin["triangles"]
    edges = np.unique(np.sort(np.concatenate((tri[:, :2], tri[:, 1:], tri[:, [0, 2]])), axis=1), axis=0)
    lengths = np.linalg.norm(skin["vertices"][edges[:, 0]] - skin["vertices"][edges[:, 1]], axis=1)
    keep = lengths > 1e-4 * np.linalg.norm(np.ptp(skin["vertices"], axis=0))
    return torch.as_tensor(edges[keep], device="cuda"), torch.as_tensor(lengths[keep], dtype=torch.float32, device="cuda")


def strain(vertices, edges, lengths):
    actual = torch.linalg.vector_norm(vertices[:, edges[:, 0]] - vertices[:, edges[:, 1]], dim=-1)
    ratio = (actual / lengths).clamp_min(1e-4)
    return torch.log(ratio).square().mean(), ratio


def make_field(skin: dict) -> WeightField:
    return WeightField(
        skin["vertices"], skin["triangles"], skin["weights"], skin["regions"],
        skin["names"], get_profile("h3_roc")["regionJoints"],
        device="cuda", train_regions=TRAIN_REGIONS,
    )


def fit(field, renderer, candidates, targets, edges, lengths, *, iterations, deadline, synthetic=False, callback=None):
    optimizer = torch.optim.Adam(field.parameters(), lr=0.06)
    history = []
    best_loss, best_state = float("inf"), None
    for step in range(iterations):
        if time.perf_counter() >= deadline:
            break
        field.group_logits.requires_grad_(step >= min(60, iterations // 3))
        optimizer.zero_grad(set_to_none=True)
        weights = field.weights()
        vertices = skin_with(candidates, weights)
        rgb, alpha = renderer.render(vertices)
        losses = image_loss(rgb, alpha, *targets)
        deformation, _ = strain(vertices, edges, lengths)
        penalty = field.penalty(weights)
        objective = losses["total"] + (0.0 if synthetic else 0.15) * deformation + (1.0 if synthetic else 25.0) * penalty
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


def save_gif(path: Path, targets, before, after, *, title: str, labels=("Target", "Frozen skin", "Optimized skin")):
    target_rgb, target_alpha, _ = targets
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
    frames[0].save(path.with_suffix(".png"))


def run(output: Path, *, seconds: float, resolution: int, iterations: int):
    pipeline_started = time.perf_counter()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite pilot: {output}")
    freeze, skin = _load_frozen_prep("h3_roc")
    calibration_path = Path(freeze["preparationDir"]).parents[1] / "calibration/idle_reference_v1.json"
    with np.load(CAPTURE_BY_CASE["roc_attack"], allow_pickle=False) as raw:
        calibration = load_or_create(
            calibration_path=calibration_path, capture_path=CAPTURE_BY_CASE["roc_attack"],
            reference_png=numbered_pngs(EVALUATION_CASES["roc_attack"].frames)[0],
            known_idle_png=EVALUATION_CASES["roc_attack"].idle,
            research_skin=Path(freeze["researchSkin"]), capture_positions=raw["pred_position"],
            names=skin["names"], parents=skin["parents"],
        )
    motions = {case: prepare_motion(skin, calibration["referencePositions"], case) for case in CAPTURE_BY_CASE}
    idle_path = EVALUATION_CASES["roc_attack"].idle
    with Image.open(idle_path) as idle:
        box, source_size = idle.getbbox(), idle.size
    if box is None:
        raise ValueError("empty idle alpha")
    size = min(source_size)
    crop = {"left": (source_size[0] - size) // 2, "top": (source_size[1] - size) // 2, "size": size}
    output.mkdir(parents=True)
    with cascade_batch_lock(ROOT):
        started = time.perf_counter()
        deadline = started + seconds
        targets = {case: source_images(numbered_pngs(EVALUATION_CASES[case].frames), crop, resolution) for case in CAPTURE_BY_CASE}
        idle_target = source_images([idle_path], crop, resolution)
        placeholder = {"right": [1, 0, 0], "down": [0, -1, 0], "forward": [0, 0, 1], "scale": 50, "offset": [96, 96], "depth_center": 0, "depth_span": 10}
        renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], placeholder, resolution)
        from skin_camera_registration import register_camera
        try:
            camera, camera_report = register_camera(
                renderer, skin["vertices"], *idle_target, resolution=resolution,
                source_crop=crop, source_size=source_size,
            )
        except ValueError as error:
            _write_json(output / "registration_failure.json", {"error": str(error), "report": getattr(error, "report", {})})
            preview = renderer.render(torch.as_tensor(skin["vertices"], dtype=torch.float32, device="cuda")[None])
            save_gif(output / "registration_failure.gif", idle_target, preview, preview, title="Rejected idle registration")
            raise
        renderer.set_camera(camera)
        _write_json(output / "camera_registration.json", camera_report)
        _write_json(output / "camera.json", camera)
        candidates = {case: deformed_candidates(skin, motion) for case, motion in motions.items()}
        original = torch.as_tensor(skin["weights"], dtype=torch.float32, device="cuda")
        edges, lengths = geometry_edges(skin)
        with torch.no_grad():
            baseline = {case: renderer.render(skin_with(value, original)) for case, value in candidates.items()}
            idle_render = renderer.render(torch.as_tensor(skin["vertices"], dtype=torch.float32, device="cuda")[None])
        save_gif(output / "idle_registration.gif", idle_target, idle_render, idle_render, title="Idle registration")
        synthetic = make_field(skin)
        generator = torch.Generator(device="cuda").manual_seed(19)
        with torch.no_grad():
            synthetic.region_logits.copy_(torch.randn(synthetic.region_logits.shape, generator=generator, device="cuda") * 1.0)
        synth_indices, synth_holdout = [3, 9, 15], [6, 12, 22]
        synth_targets = (*[value[synth_indices].detach() for value in baseline["roc_attack"]],)
        synth_distance = torch.as_tensor(np.stack([distance_transform_edt(a[..., 0] < .5) for a in synth_targets[1].cpu().numpy()]), device="cuda", dtype=torch.float32)
        synth_targets = (*synth_targets, synth_distance)
        with torch.no_grad():
            synth_before = renderer.render(skin_with(candidates["roc_attack"], synthetic.weights()))
        synthetic_history = fit(synthetic, renderer, candidates["roc_attack"][synth_indices], synth_targets, edges, lengths, iterations=140, deadline=min(deadline - 60, time.perf_counter() + 90), synthetic=True)
        with torch.no_grad():
            synth_after = renderer.render(skin_with(candidates["roc_attack"], synthetic.weights()))
        known = baseline["roc_attack"]
        synth_before_metrics = image_metrics(*synth_before, *known)
        synth_after_metrics = image_metrics(*synth_after, *known)
        before_error = np.mean([1 - synth_before_metrics[i]["iou"] for i in synth_holdout])
        after_error = np.mean([1 - synth_after_metrics[i]["iou"] for i in synth_holdout])
        perfect_metrics = image_metrics(*known, *known)
        floor = np.mean([1 - perfect_metrics[i]["iou"] for i in synth_holdout])
        synthetic_report = {"beforeHoldoutError": before_error, "afterHoldoutError": after_error, "antialiasErrorFloor": floor, "passed": bool(before_error - floor > 1e-5 and after_error - floor < (before_error - floor) * .8), "history": synthetic_history}
        _write_json(output / "synthetic_control.json", synthetic_report)
        save_gif(output / "synthetic_control.gif", (*known, targets["roc_attack"][2]), synth_before, synth_after, title="Synthetic known-skin recovery", labels=("Known skin target", "Perturbed skin", "Recovered skin"))
        print(json.dumps({"syntheticControl": synthetic_report["passed"], "gif": str(output / "synthetic_control.gif")}), flush=True)
        if not synthetic_report["passed"]:
            raise ValueError("synthetic held-out deformation recovery failed; real sprite fit not run")
        field = make_field(skin)
        train_indices = list(TRAIN)
        train_targets = tuple(value[train_indices] for value in targets["roc_attack"])
        def checkpoint(step, weights):
            with torch.no_grad():
                preview = renderer.render(skin_with(candidates["roc_attack"], weights))
            path = output / f"attack_checkpoint_{step:03d}.gif"
            save_gif(path, targets["roc_attack"], baseline["roc_attack"], preview, title=f"Attack training checkpoint {step}")
            print(json.dumps({"checkpointGif": str(path)}), flush=True)
        history = fit(field, renderer, candidates["roc_attack"][train_indices], train_targets, edges, lengths, iterations=iterations, deadline=deadline - 35, callback=checkpoint)
        learned = field.weights().detach()
        weight_gate = validate_candidate_weights(
            learned.cpu().numpy(), skin["weights"], skin["regions"], skin["names"],
            get_profile("h3_roc")["regionJoints"], TRAIN_REGIONS,
        )
        idle_vertices = skin_dense(
            skin["vertices"], learned.cpu().numpy(),
            bind_world_matrices(skin["offsets"], skin["parents"]), skin["inverseBind"],
        )
        idle_error = float(np.linalg.norm(idle_vertices - skin["vertices"], axis=1).max())
        if idle_error > preservation_limit(skin["vertices"]):
            raise ValueError("learned skin violates original idle identity")
        weight_gate["idleVertexMaxError"] = idle_error
        np.savez_compressed(output / "candidate_weights.npz", weights=learned.cpu().numpy(), names=np.asarray(skin["names"]), parents=skin["parents"])
        report = {"proof": "generated-candidate", "visualAcceptance": "unreviewed", "motionOwner": "frozen_idle_calibrated_adapted_transforms", "trainingFrames": train_indices, "trainRegions": list(TRAIN_REGIONS), "sharedWeightsAcrossClips": True, "camera": camera_report, "synthetic": synthetic_report, "field": field.support_stats(), "history": history, "inputs": {"researchSkin": sha256_file(Path(freeze["researchSkin"])), "calibration": calibration["hash"]}, "cases": {}}
        for case, transformed in candidates.items():
            with torch.no_grad():
                before_mesh = skin_with(transformed, original)
                after_mesh = skin_with(transformed, learned)
                rendered = renderer.render(after_mesh)
                _, before_ratio = strain(before_mesh, edges, lengths)
                _, after_ratio = strain(after_mesh, edges, lengths)
            before_metrics = image_metrics(*baseline[case], *targets[case][:2])
            after_metrics = image_metrics(*rendered, *targets[case][:2])
            # Frame zero registered the camera, so it is not a fully unseen image.
            held = [i for i in range(len(after_metrics)) if case != "roc_attack" or (i not in TRAIN and i != 0)]
            improvement = float(np.mean([after_metrics[i]["iou"] - before_metrics[i]["iou"] for i in held]))
            row = {"before": before_metrics, "after": after_metrics, "holdoutIndices": held, "holdoutMeanIouImprovement": improvement, "beforeEdgeRatioP95": float(torch.quantile(before_ratio.flatten(), .95)), "afterEdgeRatioP95": float(torch.quantile(after_ratio.flatten(), .95)), "fixedMotionSha256": digest(motions[case]["jointWorld"])}
            report["cases"][case] = row
            row["registrationFrame"] = 0 if case == "roc_attack" else None
            row["holdoutMinimumIouDelta"] = min(after_metrics[i]["iou"] - before_metrics[i]["iou"] for i in held)
            row["holdoutMeanRgbErrorDelta"] = float(np.mean([after_metrics[i]["color"] - before_metrics[i]["color"] for i in held]))
            row["colorMetric"] = "raw RGB absolute error, lower is better; not training chroma loss"
            row["beforePerFrameEdgeRatioP95"] = torch.quantile(before_ratio, .95, dim=1).cpu().tolist()
            row["afterPerFrameEdgeRatioP95"] = torch.quantile(after_ratio, .95, dim=1).cpu().tolist()
            save_gif(output / f"{case}_comparison.gif", targets[case], baseline[case], rendered, title=case)
            times = np.arange(len(after_metrics), dtype=np.float32) * float(SOURCE_FRAME_MS) / 1000.0
            glb = output / f"{case}_candidate.glb"
            write_skinned_glb(
                glb, names=skin["names"], parents=skin["parents"],
                rest_local_rotation=np.repeat(np.eye(3)[None], len(skin["names"]), axis=0),
                rest_local_translation=skin["offsets"], inverse_bind=skin["inverseBind"],
                vertices=skin["vertices"], triangles=skin["triangles"], uvs=skin["uvs"],
                albedo=skin["albedo"], weights=learned.cpu().numpy(),
                animation={"name": "fixed_motion_learned_skin", "times": times,
                           "rotations": matrices_to_xyzw(motions[case]["localRotation"])},
            )
            row["exportParity"] = verify_calibrated_export(
                glb, expected_meshes=after_mesh.cpu().numpy(), expected_times=times,
                idle_frame=0 if motions[case]["clipFrame0IsBind"] else None,
            )
            print(json.dumps({"case": case, "holdoutIouImprovement": improvement, "gif": str(output / f"{case}_comparison.gif")}), flush=True)
        report["elapsedSeconds"] = time.perf_counter() - started
        report["cachedPipelineSecondsIncludingLockWait"] = time.perf_counter() - pipeline_started
        report["timingScope"] = "cached captures; elapsedSeconds excludes CPU preparation and lock wait; no fresh mocap inference"
        report["inputs"]["sources"] = {
            case: [{"path": str(path), "sha256": sha256_file(path)} for path in numbered_pngs(EVALUATION_CASES[case].frames)]
            for case in CAPTURE_BY_CASE
        }
        report["inputs"]["idleSource"] = {"path": str(idle_path), "sha256": sha256_file(idle_path)}
        report["inputs"]["implementation"] = {
            name: sha256_file(HERE / name) for name in (
                "run_skin_weight_pilot.py", "skin_image_objective.py", "skin_weight_field.py",
                "skin_camera_registration.py", "skin_weight_contract.py",
            )
        }
        if sha256_file(Path(freeze["researchSkin"])) != report["inputs"]["researchSkin"]:
            raise ValueError("frozen preparation changed during skin fitting")
        report["weightContract"] = weight_gate
        report["passedHoldouts"] = holdout_gate(report["cases"])
        report["disposition"] = "candidate_for_visual_review" if report["passedHoldouts"] else "rejected_generalization_or_deformation_gate"
        _write_json(output / "pilot_report.json", report)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=600)
    parser.add_argument("--resolution", type=int, default=192)
    parser.add_argument("--iterations", type=int, default=400)
    args = parser.parse_args()
    if not 120 <= args.seconds <= 600:
        raise ValueError("pilot budget must be between 120 and 600 seconds")
    print(json.dumps(run(args.output.resolve(), seconds=args.seconds, resolution=args.resolution, iterations=args.iterations), indent=2))


if __name__ == "__main__":
    main()
