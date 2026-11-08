#!/usr/bin/env python3
"""Roc pilot: sprite-driven wing-pose refinement on a saved linked-master capture.

Separate stage. Does not change the skin-only solver or overwrite original
capture / bind / weights. Reuses the linked-master v2 inputs and writes a new
artifact. Generated candidate, pending visual acceptance — not OE runtime.
"""
from __future__ import annotations

import argparse
import json
import math
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
from eagle_glb import matrices_to_xyzw, write_skinned_glb  # noqa: E402
from gpu_cascade_batch_lock import cascade_batch_lock  # noqa: E402
from linked_master_pose_refine import (  # noqa: E402
    ANCHOR_MATRIX_SLACK,
    MOTION_OWNER,
    SCHEMA,
    START_COUNT,
    acceptance,
    candidate_eligibility,
    continuity_hinge_losses,
    crop_panels_identically,
    evaluate_continuity,
    evaluate_geometry_gates,
    fold_toward_torso_deltas,
    identical_panel_close_box,
    per_clip_metrics,
    per_frame_iou_regression_hinge,
    playback_continuity_pairs,
    pilot_frame_plan,
    rotation_change_max,
    search_time_slices,
    source_matches_optimization_canvas,
    vertex_region_mask,
    wing_joint_indices,
)
from paths import REPO  # noqa: E402
from pin import sha256_file  # noqa: E402
from pose_rotation_fk import (  # noqa: E402
    TWIST_POLICY,
    apply_joint_deltas,
    bone_lengths_from_world,
    clamp_axis_angle_magnitude,
    edge_strain,
    fk_world,
    skin_lbs,
    so3_exp_np,
    so3_geodesic_np,
    so3_geodesic_sq,
)
from run_linked_master_pipeline import load_candidate_weights  # noqa: E402
from run_move_bind_t2_mocap_skin_fit import load_fixed_motion, load_skin_bundle  # noqa: E402
from run_skin_weight_pilot import geometry_edges, shared_canvas_source_images, strain  # noqa: E402
from skeleton_overlay import write_skeleton_overlay  # noqa: E402
from skin_image_objective import SkinImageRenderer, image_loss, image_metrics  # noqa: E402
from verify_calibrated_export import verify_calibrated_export  # noqa: E402

DEFAULT_LINKED = REPO / "artifacts/homm3_mocap_v2/roc_linked_master_v2"
DEFAULT_OUT = REPO / "artifacts/homm3_mocap_v2/roc_wing_pose_refine_v2"
FROZEN_V1 = REPO / "artifacts/homm3_mocap_v2/roc_wing_pose_refine_v1"
PILOT_UNIT = "h3_roc"
GPU_BUDGET_SECONDS = 120.0
START_LR = 0.03
MAX_JOINT_DELTA_RAD = 2.0
IMAGE_WEIGHT = 1.0
STRAIN_WEIGHT = 0.5
ROTATION_WEIGHT = 0.15
TEMPORAL_WEIGHT = 0.25
CONTINUITY_GATE_WEIGHT = 1.0
FRAME_IOU_GATE_WEIGHT = 10.0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_inputs(linked_dir: Path, unit: str) -> dict[str, Any]:
    if unit != PILOT_UNIT:
        raise ValueError(f"this iteration is the {PILOT_UNIT} pilot only, got {unit!r}")
    report_path = linked_dir / "report.json"
    master_path = linked_dir / "master_sequence" / "master_sequence.json"
    camera_path = linked_dir / "skin_fit" / "camera.json"
    weights_path = linked_dir / "skin_fit" / "candidate_weights.npz"
    for path in (report_path, master_path, camera_path, weights_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    master = json.loads(master_path.read_text(encoding="utf-8"))
    if report.get("unit") != unit or master.get("unit") != unit:
        raise ValueError("linked-master report/sequence unit does not match --unit")
    capture_path = Path(report["capture"])
    bind_glb = Path(report["bindGlb"])
    if sha256_file(capture_path) != report["captureSha256"]:
        raise ValueError("linked-master capture hash drifted")
    if sha256_file(bind_glb) != report["bindSha256"]:
        raise ValueError("linked-master bind hash drifted")
    profile = get_profile(unit)
    if profile.get("assetId") != unit:
        raise ValueError(f"profile assetId {profile.get('assetId')!r} != {unit!r}")
    skin = load_skin_bundle(bind_glb)
    weights = load_candidate_weights(weights_path, skin)
    motion = load_fixed_motion(skin, capture_path, reference_frame=int(master["bindGlobalIndex"]))
    camera = json.loads(camera_path.read_text(encoding="utf-8"))
    required = ("right", "down", "forward", "scale", "offset", "depth_center", "depth_span", "sourceCrop")
    missing = [key for key in required if key not in camera]
    if missing:
        raise ValueError(f"saved camera missing {missing}")
    plan = pilot_frame_plan(master)
    wings = wing_joint_indices(skin["names"], profile["regionJoints"])
    sprites = [Path(row["numberedPng"]) for row in master["frames"]]
    if len(sprites) != len(motion["localRotation"]):
        raise ValueError("sprite count does not match reconstructed capture length")
    hashes = {
        "linkedReport": sha256_file(report_path),
        "masterSequence": sha256_file(master_path),
        "capture": report["captureSha256"],
        "bindGlb": report["bindSha256"],
        "camera": sha256_file(camera_path),
        "candidateWeights": sha256_file(weights_path),
        "sourceMesh": report.get("sourceMeshSha256"),
    }
    return {
        "unit": unit,
        "profile": profile,
        "report": report,
        "master": master,
        "skin": skin,
        "weights": weights,
        "motion": motion,
        "camera": camera,
        "plan": plan,
        "wings": wings,
        "sprites": sprites,
        "capturePath": capture_path,
        "bindGlb": bind_glb,
        "hashes": hashes,
        "paths": {
            "linkedDir": str(linked_dir.resolve()).replace("\\", "/"),
            "capture": str(capture_path).replace("\\", "/"),
            "bindGlb": str(bind_glb).replace("\\", "/"),
            "camera": str(camera_path.resolve()).replace("\\", "/"),
            "weights": str(weights_path.resolve()).replace("\\", "/"),
        },
    }


def yawed_camera(camera: dict[str, Any], degrees: float, keep_world: np.ndarray) -> dict[str, Any]:
    """One extra fixed camera. Offset is solved so `keep_world` stays at the same pixel."""
    axis = np.asarray(camera["up"], dtype=np.float64)
    axis = axis / float(np.linalg.norm(axis))
    rotation = so3_exp_np(axis * math.radians(float(degrees)))
    right = rotation @ np.asarray(camera["right"], dtype=np.float64)
    down = rotation @ np.asarray(camera["down"], dtype=np.float64)
    forward = rotation @ np.asarray(camera["forward"], dtype=np.float64)
    scale = float(camera["scale"])
    old_offset = np.asarray(camera["offset"], dtype=np.float64)
    old_right = np.asarray(camera["right"], dtype=np.float64)
    old_down = np.asarray(camera["down"], dtype=np.float64)
    point = np.asarray(keep_world, dtype=np.float64).reshape(3)
    target = np.array([point @ old_right * scale + old_offset[0], point @ old_down * scale + old_offset[1]])
    offset = target - np.array([point @ right * scale, point @ down * scale])
    out = dict(camera)
    out.update(
        {
            "right": right.tolist(),
            "down": down.tolist(),
            "forward": forward.tolist(),
            "up": (rotation @ axis).tolist(),
            "offset": offset.tolist(),
            "yawDeg": float(camera.get("yawDeg", 0.0)) + float(degrees),
            "framingPolicy": "fixed_alternate_view_same_scale_anchor_original_centroid",
        }
    )
    return out


def _save_row_gif(path: Path, rows: list[Image.Image], frame_ms: float) -> None:
    durations = [10 * (round((i + 1) * frame_ms / 10) - round(i * frame_ms / 10)) for i in range(len(rows))]
    rows[0].save(path, save_all=True, append_images=rows[1:], duration=durations, loop=0)


def comparison_rows(
    *,
    source_rgb: np.ndarray,
    frames: list[int],
    before_rgb: np.ndarray,
    after_rgb: np.ndarray,
    labels: list[str],
    candidate_label: str = "candidate - unaccepted",
) -> list[Image.Image]:
    source_matches_optimization_canvas(source_rgb, before_rgb)
    source_matches_optimization_canvas(source_rgb, after_rgb)
    resolution = int(source_rgb.shape[1])
    images = []
    for frame, label in zip(frames, labels):
        row = Image.new("RGB", (resolution * 3, resolution + 28), (12, 12, 16))
        draw = ImageDraw.Draw(row)
        draw.text((4, 6), label, fill="white")
        draw.text((4, 16), "sprite (optimization canvas)", fill=(180, 180, 200))
        draw.text((resolution + 4, 16), "original capture", fill=(180, 180, 200))
        draw.text((resolution * 2 + 4, 16), candidate_label, fill=(180, 180, 200))
        row.paste(Image.fromarray(np.uint8(np.clip(source_rgb[frame], 0, 1) * 255)), (0, 28))
        row.paste(Image.fromarray(np.uint8(np.clip(before_rgb[frame], 0, 1) * 255)), (resolution, 28))
        row.paste(Image.fromarray(np.uint8(np.clip(after_rgb[frame], 0, 1) * 255)), (resolution * 2, 28))
        images.append(row)
    return images


def close_rows(
    *,
    source_rgb: np.ndarray,
    frames: list[int],
    before_rgb: np.ndarray,
    after_rgb: np.ndarray,
    labels: list[str],
) -> list[Image.Image]:
    box = identical_panel_close_box(*(source_rgb[frame] for frame in frames), *(before_rgb[frame] for frame in frames), *(after_rgb[frame] for frame in frames))
    images = []
    for frame, label in zip(frames, labels):
        cropped = crop_panels_identically([source_rgb[frame], before_rgb[frame], after_rgb[frame]], box)
        height, width = cropped[0].shape[:2]
        row = Image.new("RGB", (width * 3, height + 28), (12, 12, 16))
        draw = ImageDraw.Draw(row)
        draw.text((4, 6), f"{label} identical close crop {box}", fill="white")
        for index, panel in enumerate(cropped):
            row.paste(Image.fromarray(np.uint8(np.clip(panel, 0, 1) * 255)), (width * index, 28))
        images.append(row)
    return images


def render_mesh(renderer: SkinImageRenderer, verts: torch.Tensor) -> np.ndarray:
    rgb, _alpha = renderer.render(verts)
    return rgb.detach().cpu().numpy()


def _terms(losses: dict[str, torch.Tensor]) -> dict[str, float]:
    return {
        "total": float(losses["total"].detach()),
        "image": float(losses["image"].detach()),
        "iou": float(losses["iou"].detach()),
        "color": float(losses["color"].detach()),
        "strain": float(losses["strain"].detach()),
        "rotation": float(losses["rotation"].detach()),
        "temporal": float(losses["temporal"].detach()),
        "length": float(losses["length"].detach()),
        "continuityAngular": float(losses["continuityAngular"].detach()),
        "continuitySurface": float(losses["continuitySurface"].detach()),
        "frameIouRegression": float(losses["frameIouRegression"].detach()),
    }


def score_pose(
    *,
    bundle: dict[str, Any],
    local_np: np.ndarray,
    before_np: np.ndarray,
    after_np: np.ndarray,
    before_iou: list[float],
    after_iou: list[float],
    before_color: list[float],
    after_color: list[float],
    before_p95: list[float],
    after_p95: list[float],
    edges_np: np.ndarray,
    rest_lengths_np: np.ndarray,
) -> dict[str, Any]:
    plan = bundle["plan"]
    clips = per_clip_metrics(
        plan=plan, before_iou=before_iou, after_iou=after_iou,
        before_color=before_color, after_color=after_color,
        before_strain_p95=before_p95, after_strain_p95=after_p95,
    )
    geometry = evaluate_geometry_gates(
        before_verts=before_np,
        after_verts=after_np,
        regions=bundle["skin"]["regions"],
        rest_verts=bundle["skin"]["vertices"],
        triangles=bundle["skin"]["triangles"],
        edges=edges_np,
        rest_lengths=rest_lengths_np,
        before_strain_p95=float(np.max(before_p95)),
        after_strain_p95=float(np.max(after_p95)),
    )
    continuity = evaluate_continuity(
        plan=plan,
        before_local=bundle["motion"]["localRotation"],
        after_local=local_np,
        before_verts=before_np,
        after_verts=after_np,
        wing_joints=bundle["wings"]["indices"],
        wing_mask=vertex_region_mask(bundle["skin"]["regions"], "wing_"),
    )
    move_rot = rotation_change_max(bundle["motion"]["localRotation"], local_np, plan["moveFrames"])
    pinned_rot = rotation_change_max(bundle["motion"]["localRotation"], local_np, plan["pinnedFrames"])
    eligibility = candidate_eligibility(
        geometry=geometry, continuity=continuity, clips=clips,
        move_rotation_max=move_rot, pinned_rotation_max=pinned_rot,
        optimize_frames=plan["optimizeFrames"], before_iou=before_iou, after_iou=after_iou,
    )
    gate = acceptance(eligibility=eligibility, clips=clips, geometry=geometry)
    return {
        "clips": clips,
        "geometry": geometry,
        "continuity": continuity,
        "eligibility": eligibility,
        "acceptance": gate,
        "playbackContinuityPairs": playback_continuity_pairs(plan),
        "moveRotationMax": move_rot,
        "pinnedRotationMax": pinned_rot,
    }


def optimize(
    *,
    bundle: dict[str, Any],
    targets: tuple[torch.Tensor, torch.Tensor, torch.Tensor],
    renderer: SkinImageRenderer,
    edges: torch.Tensor,
    rest_lengths: torch.Tensor,
    gpu_budget: float,
    capture_only: bool = False,
) -> dict[str, Any]:
    skin = bundle["skin"]
    motion = bundle["motion"]
    plan = bundle["plan"]
    wings = bundle["wings"]
    device = torch.device("cuda")
    base_local = torch.as_tensor(motion["localRotation"], dtype=torch.float32, device=device)
    offsets = torch.as_tensor(skin["offsets"], dtype=torch.float32, device=device).clone()
    offsets[0] = 0.0
    inverse_bind = torch.as_tensor(skin["inverseBind"], dtype=torch.float32, device=device)
    vertices = torch.as_tensor(skin["vertices"], dtype=torch.float32, device=device)
    weights = torch.as_tensor(bundle["weights"], dtype=torch.float32, device=device)
    root = torch.as_tensor(motion["jointWorld"][:, 0, :3, 3], dtype=torch.float32, device=device)
    parents = skin["parents"]
    rest_bone = bone_lengths_from_world(
        fk_world(base_local[:1], offsets, parents, root[:1]), parents
    )[0].detach()
    free_frames = torch.as_tensor(plan["freeFrames"], dtype=torch.long, device=device)
    free_joints = torch.as_tensor(wings["indices"], dtype=torch.long, device=device)
    optimize_frames = torch.as_tensor(plan["optimizeFrames"], dtype=torch.long, device=device)
    pair_a = torch.as_tensor([a for a, _ in plan["regularizePairs"]], dtype=torch.long, device=device)
    pair_b = torch.as_tensor([b for _, b in plan["regularizePairs"]], dtype=torch.long, device=device)
    rng = np.random.default_rng(0)
    wing_mask = vertex_region_mask(skin["regions"], "wing_")
    starts = [
        ("capture_control", np.zeros((len(plan["freeFrames"]), len(wings["indices"]), 3), dtype=np.float64)),
    ] + ([] if capture_only else [
        (
            "fold_0.4",
            fold_toward_torso_deltas(
                local=motion["localRotation"], offsets=skin["offsets"], parents=parents,
                root_world=motion["jointWorld"][:, 0, :3, 3], names=skin["names"],
                region_joints=bundle["profile"]["regionJoints"], free_frames=plan["freeFrames"], amount=0.4,
            ),
        ),
        (
            "fold_0.8",
            fold_toward_torso_deltas(
                local=motion["localRotation"], offsets=skin["offsets"], parents=parents,
                root_world=motion["jointWorld"][:, 0, :3, 3], names=skin["names"],
                region_joints=bundle["profile"]["regionJoints"], free_frames=plan["freeFrames"], amount=0.8,
            ),
        ),
        (
            "fold_0.4_mid_0.2",
            fold_toward_torso_deltas(
                local=motion["localRotation"], offsets=skin["offsets"], parents=parents,
                root_world=motion["jointWorld"][:, 0, :3, 3], names=skin["names"],
                region_joints=bundle["profile"]["regionJoints"], free_frames=plan["freeFrames"],
                amount=0.4, mid_amount=0.2,
            ),
        ),
        ("noise_0.15", rng.standard_normal((len(plan["freeFrames"]), len(wings["indices"]), 3)) * 0.15),
    ])

    def posed_from(omega_free: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        clamped = clamp_axis_angle_magnitude(omega_free, MAX_JOINT_DELTA_RAD)
        local = apply_joint_deltas(base_local, clamped, free_frames=free_frames, free_joints=free_joints)
        world = fk_world(local, offsets, parents, root)
        lengths = bone_lengths_from_world(world, parents)
        verts = skin_lbs(world, inverse_bind, vertices, weights)
        if not torch.isfinite(verts).all():
            raise ValueError(
                "pose FK produced non-finite vertices "
                f"(omega_finite={bool(torch.isfinite(omega_free).all())} "
                f"omega_max={float(omega_free.detach().abs().max()) if torch.isfinite(omega_free).all() else 'nan'} "
                f"local_finite={bool(torch.isfinite(local).all())} "
                f"world_finite={bool(torch.isfinite(world).all())} "
                f"grad={omega_free.requires_grad})"
            )
        return local, world, verts, lengths

    def objective(omega_free: torch.Tensor) -> dict[str, Any]:
        local, world, verts, lengths = posed_from(omega_free)
        rgb, alpha = renderer.render(verts[optimize_frames])
        photo = image_loss(rgb, alpha, targets[0][optimize_frames], targets[1][optimize_frames], targets[2][optimize_frames])
        deformation, _ = edge_strain(verts[optimize_frames], edges, rest_lengths)
        change = so3_geodesic_sq(base_local[optimize_frames][:, wings["indices"]], local[optimize_frames][:, wings["indices"]])
        temporal = so3_geodesic_sq(local[pair_a][:, wings["indices"]], local[pair_b][:, wings["indices"]])
        # Optimize the same boundary and per-frame checks used by final eligibility.
        continuity = continuity_hinge_losses(
            plan=plan, before_local=base_local, after_local=local,
            before_verts=before_verts, after_verts=verts,
            wing_joints=wings["indices"], wing_mask=wing_mask,
        )
        target_alpha = targets[1][optimize_frames]
        intersection = (alpha * target_alpha).mean((1, 2, 3))
        union = (alpha + target_alpha - alpha * target_alpha).mean((1, 2, 3)).clamp_min(1e-6)
        frame_iou = before_iou_tensor.clone()
        frame_iou[optimize_frames] = intersection / union
        frame_regression = per_frame_iou_regression_hinge(before_iou_tensor, frame_iou, plan["optimizeFrames"])
        length_err = (lengths - rest_bone).square().mean()
        total = (
            IMAGE_WEIGHT * photo["total"]
            + STRAIN_WEIGHT * deformation
            + ROTATION_WEIGHT * change.mean()
            + TEMPORAL_WEIGHT * temporal.mean()
            + CONTINUITY_GATE_WEIGHT * (continuity["angular"] + continuity["surface"])
            + FRAME_IOU_GATE_WEIGHT * frame_regression
            + 50.0 * length_err
        )
        return {
            "total": total,
            "image": photo["total"],
            "iou": photo["iou"],
            "color": photo["color"],
            "strain": deformation,
            "rotation": change.mean(),
            "temporal": temporal.mean(),
            "length": length_err,
            "continuityAngular": continuity["angular"],
            "continuitySurface": continuity["surface"],
            "frameIouRegression": frame_regression,
            "local": local,
            "world": world,
            "verts": verts,
            "rgb": rgb,
            "alpha": alpha,
        }

    slices = [gpu_budget] if capture_only else search_time_slices(gpu_budget, START_COUNT)
    if len(slices) != len(starts):
        raise ValueError("search allocation must give every deterministic start the same slice")
    with torch.no_grad():
        before_verts = skin_lbs(fk_world(base_local, offsets, parents, root), inverse_bind, vertices, weights)
        before_rgb, before_alpha = renderer.render(before_verts)
        before_metrics = image_metrics(before_rgb, before_alpha, targets[0], targets[1])
        before_iou = [row["iou"] for row in before_metrics]
        before_iou_tensor = torch.as_tensor(before_iou, dtype=torch.float32, device=device)
        edges_np = edges.detach().cpu().numpy()
        rest_np = rest_lengths.detach().cpu().numpy()

    def evaluate_state(payload: dict[str, Any], omega: torch.Tensor) -> dict[str, Any]:
        local = payload["local"]
        world = payload["world"]
        verts = payload["verts"]
        metrics = image_metrics(payload["rgb"], payload["alpha"], targets[0][optimize_frames], targets[1][optimize_frames])
        after_iou = list(before_iou)
        after_color = [row["color"] for row in before_metrics]
        for frame, row in zip(plan["optimizeFrames"], metrics):
            after_iou[frame] = row["iou"]
            after_color[frame] = row["color"]
        _, before_ratio = strain(before_verts, edges, rest_lengths)
        _, after_ratio = strain(verts, edges, rest_lengths)
        before_p95 = torch.quantile(before_ratio, 0.95, dim=1).detach().cpu().numpy().tolist()
        after_p95 = torch.quantile(after_ratio, 0.95, dim=1).detach().cpu().numpy().tolist()
        scored = score_pose(
            bundle=bundle,
            local_np=local.detach().cpu().numpy(),
            before_np=before_verts.detach().cpu().numpy(),
            after_np=verts.detach().cpu().numpy(),
            before_iou=before_iou,
            after_iou=after_iou,
            before_color=[row["color"] for row in before_metrics],
            after_color=after_color,
            before_p95=before_p95,
            after_p95=after_p95,
            edges_np=edges_np,
            rest_lengths_np=rest_np,
        )
        protected = (base_local[:, wings["protectedIndices"]] - local[:, wings["protectedIndices"]]).abs().max().detach()
        if float(protected) > ANCHOR_MATRIX_SLACK:
            raise RuntimeError(f"protected joint rotation changed by {float(protected)}")
        return {
            "omega": omega.detach().cpu().clone(),
            "local": local.detach(),
            "world": world.detach(),
            "verts": verts.detach(),
            "afterIou": after_iou,
            "terms": _terms(payload),
            **scored,
        }

    def run_branch(omega: torch.Tensor, deadline: float) -> dict[str, Any]:
        if not torch.isfinite(omega).all():
            raise ValueError("optimizer received a non-finite parameter")
        param = torch.nn.Parameter(clamp_axis_angle_magnitude(omega.detach().clone(), MAX_JOINT_DELTA_RAD))
        optimizer = torch.optim.Adam([param], lr=START_LR)
        history: list[dict[str, float]] = []
        best_loss_state, best_loss = param.detach().clone(), float("inf")
        best_eligible_state, best_eligible_image = None, float("inf")
        completed = 0
        saturated_steps = 0
        while time.perf_counter() < deadline:
            optimizer.zero_grad(set_to_none=True)
            losses = objective(param)
            if not torch.isfinite(losses["total"]):
                raise ValueError("nonfinite pose-refine objective")
            terms = _terms(losses)
            if terms["total"] < best_loss:
                best_loss = terms["total"]
                best_loss_state = param.detach().clone()
            scored = evaluate_state(losses, param.detach())
            if scored["eligibility"]["passed"] and terms["image"] < best_eligible_image:
                best_eligible_image = terms["image"]
                best_eligible_state = param.detach().clone()
            losses["total"].backward()
            if param.grad is None or not torch.isfinite(param.grad).all():
                raise ValueError("non-finite pose-refine gradient")
            torch.nn.utils.clip_grad_norm_([param], 2.0)
            optimizer.step()
            if not torch.isfinite(param).all():
                raise ValueError("optimizer step produced a non-finite pose delta")
            magnitude = torch.linalg.vector_norm(param.detach(), dim=-1)
            if int((magnitude > MAX_JOINT_DELTA_RAD - 1e-5).sum()) > 0:
                saturated_steps += 1
            param.data.copy_(clamp_axis_angle_magnitude(param.data, MAX_JOINT_DELTA_RAD))
            completed += 1
            if completed == 1 or completed % 10 == 0:
                history.append({"step": completed, **terms, "eligible": scored["eligibility"]["passed"]})
        with torch.no_grad():
            loss_ckpt = evaluate_state(objective(best_loss_state), best_loss_state)
            eligible_ckpt = None if best_eligible_state is None else evaluate_state(objective(best_eligible_state), best_eligible_state)
        return {
            "steps": completed,
            "history": history,
            "saturatedSteps": saturated_steps,
            "bestLoss": loss_ckpt,
            "bestEligible": eligible_ckpt,
            "allocatedSeconds": None,
        }

    start_rows = []
    used = 0.0
    for (name, seed), slice_s in zip(starts, slices, strict=True):
        seed_omega = clamp_axis_angle_magnitude(
            torch.as_tensor(seed, dtype=torch.float32, device=device), MAX_JOINT_DELTA_RAD
        )
        with torch.no_grad():
            opening = objective(seed_omega)
        branch_started = time.perf_counter()
        branch = run_branch(seed_omega, branch_started + float(slice_s))
        branch["allocatedSeconds"] = float(slice_s)
        branch["usedSeconds"] = time.perf_counter() - branch_started
        used += branch["usedSeconds"]
        chosen = branch["bestEligible"] or branch["bestLoss"]
        row = {
            "name": name,
            "opening": _terms(opening),
            "steps": branch["steps"],
            "allocatedSeconds": branch["allocatedSeconds"],
            "usedSeconds": branch["usedSeconds"],
            "saturatedSteps": branch["saturatedSteps"],
            "eligible": bool(branch["bestEligible"] is not None),
            "bestLossTerms": branch["bestLoss"]["terms"],
            "bestEligibleTerms": None if branch["bestEligible"] is None else branch["bestEligible"]["terms"],
            "bestLossAcceptance": branch["bestLoss"]["acceptance"],
            "bestEligibleAcceptance": None if branch["bestEligible"] is None else branch["bestEligible"]["acceptance"],
            "history": branch["history"],
            "state": chosen,
            "diagnosticState": branch["bestLoss"],
        }
        start_rows.append(row)
        print(
            json.dumps(
                {
                    "name": name,
                    "steps": row["steps"],
                    "allocatedSeconds": row["allocatedSeconds"],
                    "eligible": row["eligible"],
                    "openingImage": row["opening"]["image"],
                    "bestLossImage": row["bestLossTerms"]["image"] if row["bestLossTerms"] else None,
                }
            ),
            flush=True,
        )

    eligible_rows = [row for row in start_rows if row["eligible"]]
    selected = None
    if eligible_rows:
        selected = min(eligible_rows, key=lambda row: row["bestEligibleTerms"]["image"])
    winner = selected["state"] if selected is not None else start_rows[0]["state"]
    return {
        "omega": winner["omega"],
        "local": winner["local"],
        "world": winner["world"],
        "verts": winner["verts"],
        "beforeVerts": before_verts.detach(),
        "starts": start_rows,
        "selectedStart": None if selected is None else selected["name"],
        "selectedEligible": selected is not None,
        "gpuSecondsUsed": used,
        "searchSlices": slices,
        "scored": {key: winner[key] for key in ("clips", "geometry", "continuity", "eligibility", "acceptance")},
    }


def _json_starts(starts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for start in starts:
        row = {key: value for key, value in start.items() if key not in ("state", "diagnosticState")}
        rows.append(row)
    return rows


def run(
    *,
    linked_dir: Path,
    output: Path,
    unit: str,
    gpu_seconds: float,
    overwrite: bool,
    assess_npz: Path | None = None,
    capture_only: bool = False,
) -> dict[str, Any]:
    wall_started = time.perf_counter()
    if output.resolve() == FROZEN_V1.resolve():
        raise ValueError("refusing to write into frozen v1; use a new assessment or v2 directory")
    if output.exists():
        if not overwrite:
            raise FileExistsError(f"refusing to overwrite {output} (pass --overwrite)")
        import shutil

        shutil.rmtree(output)
    bundle = load_inputs(linked_dir, unit)
    output.mkdir(parents=True)
    plan = bundle["plan"]
    camera = bundle["camera"]
    resolution = int(camera["resolution"])
    frame_ms = float(bundle["master"]["sourceFrameMs"])
    load_seconds = time.perf_counter() - wall_started

    with cascade_batch_lock(REPO):
        targets, crop, source_size = shared_canvas_source_images(bundle["sprites"], resolution)
        if {k: int(crop[k]) for k in ("left", "top", "size")} != {k: int(camera["sourceCrop"][k]) for k in ("left", "top", "size")}:
            raise ValueError("shared canvas crop does not match the saved camera crop")
        if tuple(source_size) != tuple(camera["sourceSize"]):
            raise ValueError("sprite canvas size does not match the saved camera")
        renderer = SkinImageRenderer(
            bundle["skin"]["triangles"], bundle["skin"]["uvs"], bundle["skin"]["albedo"], camera, resolution
        )
        edges, rest_lengths = geometry_edges(bundle["skin"])
        gpu_started = time.perf_counter()
        if assess_npz is not None:
            loaded = np.load(assess_npz, allow_pickle=False)
            before_np = np.asarray(loaded["originalVertices"])
            after_np = np.asarray(loaded["correctedVertices"])
            local_np = np.asarray(loaded["correctedLocalRotation"])
            before_t = torch.as_tensor(before_np, dtype=torch.float32, device="cuda")
            after_t = torch.as_tensor(after_np, dtype=torch.float32, device="cuda")
            result = {
                "beforeVerts": before_t,
                "verts": after_t,
                "local": torch.as_tensor(local_np, dtype=torch.float32, device="cuda"),
                "world": None,
                "starts": [],
                "selectedStart": "v1_saved",
                "selectedEligible": False,
                "gpuSecondsUsed": 0.0,
                "searchSlices": [],
            }
        else:
            result = optimize(
                bundle=bundle, targets=targets, renderer=renderer, edges=edges,
                rest_lengths=rest_lengths, gpu_budget=gpu_seconds,
                capture_only=capture_only,
            )
            before_np = result["beforeVerts"].detach().cpu().numpy()
            after_np = result["verts"].detach().cpu().numpy()
            local_np = result["local"].detach().cpu().numpy()
        gpu_seconds_used = time.perf_counter() - gpu_started
        source_rgb = targets[0].detach().cpu().numpy()
        before_rgb = render_mesh(renderer, result["beforeVerts"])
        after_rgb = render_mesh(renderer, result["verts"])
        before_metrics = image_metrics(*renderer.render(result["beforeVerts"]), targets[0], targets[1])
        after_metrics = image_metrics(*renderer.render(result["verts"]), targets[0], targets[1])
        _, before_ratio = strain(result["beforeVerts"], edges, rest_lengths)
        _, after_ratio = strain(result["verts"], edges, rest_lengths)
        before_p95 = torch.quantile(before_ratio, 0.95, dim=1).detach().cpu().numpy()
        after_p95 = torch.quantile(after_ratio, 0.95, dim=1).detach().cpu().numpy()
        scored = score_pose(
            bundle=bundle,
            local_np=local_np,
            before_np=before_np,
            after_np=after_np,
            before_iou=[row["iou"] for row in before_metrics],
            after_iou=[row["iou"] for row in after_metrics],
            before_color=[row["color"] for row in before_metrics],
            after_color=[row["color"] for row in after_metrics],
            before_p95=before_p95.tolist(),
            after_p95=after_p95.tolist(),
            edges_np=edges.detach().cpu().numpy(),
            rest_lengths_np=rest_lengths.detach().cpu().numpy(),
        )
        keep = result["beforeVerts"][plan["clips"]["idle"]["frames"][0]].mean(dim=0).detach().cpu().numpy()
        side = yawed_camera(camera, 90.0, keep)
        rear = yawed_camera(camera, 180.0, keep)
        side_renderer = SkinImageRenderer(
            bundle["skin"]["triangles"], bundle["skin"]["uvs"], bundle["skin"]["albedo"], side, resolution
        )
        rear_renderer = SkinImageRenderer(
            bundle["skin"]["triangles"], bundle["skin"]["uvs"], bundle["skin"]["albedo"], rear, resolution
        )
        side_before = render_mesh(side_renderer, result["beforeVerts"])
        side_after = render_mesh(side_renderer, result["verts"])
        rear_before = render_mesh(rear_renderer, result["beforeVerts"])
        rear_after = render_mesh(rear_renderer, result["verts"])
        start_previews = []
        for start in result["starts"]:
            start_rgb = render_mesh(renderer, start["state"]["verts"])
            start_previews.append((start["name"], start_rgb, start["state"]))
            diagnostic = start["diagnosticState"]
            start_previews.append((start["name"] + "_best_loss_unaccepted", render_mesh(renderer, diagnostic["verts"]), diagnostic))

    render_started = time.perf_counter()
    clips = scored["clips"]
    geometry = scored["geometry"]
    gate = scored["acceptance"]
    base_np = bundle["motion"]["localRotation"]
    labels = {
        frame: f"{row['clipKey']} f{int(row['localIndex']):02d} g{int(row['globalIndex']):03d}"
        for frame, row in enumerate(bundle["master"]["frames"])
    }
    pilot_frames = plan["optimizeFrames"]
    compare = comparison_rows(
        source_rgb=source_rgb, frames=pilot_frames, before_rgb=before_rgb, after_rgb=after_rgb,
        labels=[labels[i] for i in pilot_frames],
    )
    compare_path = output / "pilot_comparison.gif"
    _save_row_gif(compare_path, compare, frame_ms)
    idle_frames = plan["clips"]["idle"]["frames"]
    idle_rows = comparison_rows(
        source_rgb=source_rgb, frames=idle_frames, before_rgb=before_rgb, after_rgb=after_rgb,
        labels=[labels[i] for i in idle_frames],
    )
    close_path = output / "idle_close.gif"
    _save_row_gif(
        close_path,
        close_rows(
            source_rgb=source_rgb, frames=idle_frames, before_rgb=before_rgb, after_rgb=after_rgb,
            labels=[labels[i] for i in idle_frames],
        ),
        frame_ms,
    )
    _save_row_gif(output / "idle_comparison.gif", idle_rows, frame_ms)
    transition = plan["clips"]["move_start"]["frames"] + plan["moveFrames"] + plan["clips"]["move_end"]["frames"]
    _save_row_gif(
        output / "transition_comparison.gif",
        comparison_rows(
            source_rgb=source_rgb, frames=transition, before_rgb=before_rgb, after_rgb=after_rgb,
            labels=[labels[i] for i in transition],
        ),
        frame_ms,
    )
    start_evidence = []
    for name, start_rgb, state in start_previews:
        start_dir = output / "starts" / name
        start_dir.mkdir(parents=True)
        start_gif = start_dir / "pilot_comparison.gif"
        _save_row_gif(
            start_gif,
            comparison_rows(
                source_rgb=source_rgb, frames=pilot_frames, before_rgb=before_rgb, after_rgb=start_rgb,
                labels=[labels[i] for i in pilot_frames],
                candidate_label="unaccepted diagnostic" if name.endswith("_best_loss_unaccepted") else "candidate - unaccepted",
            ),
            frame_ms,
        )
        np.savez_compressed(
            start_dir / "corrected_local_rotation.npz",
            originalLocalRotation=base_np,
            correctedLocalRotation=state["local"].detach().cpu().numpy(),
            originalVertices=before_np,
            correctedVertices=state["verts"].detach().cpu().numpy(),
        )
        start_report = {
            "name": name,
            "proof": "generated candidate diagnostic; not delivery",
            "visualAcceptance": "unaccepted",
            "diagnosticOnly": name.endswith("_best_loss_unaccepted"),
            "eligible": state["eligibility"]["passed"],
            "acceptance": state["acceptance"],
            "clips": state["clips"],
            "geometry": state["geometry"],
            "continuity": state["continuity"],
            "terms": state["terms"],
        }
        _write_json(start_dir / "report.json", start_report)
        start_evidence.append({"name": name, "gif": str(start_gif).replace("\\", "/"), "eligible": start_report["eligible"]})

    def view_gif(name: str, before_v: np.ndarray, after_v: np.ndarray) -> str:
        rows = []
        for frame in idle_frames:
            row = Image.new("RGB", (resolution * 2, resolution + 20), (12, 12, 16))
            draw = ImageDraw.Draw(row)
            draw.text((4, 4), f"{name} {labels[frame]}", fill="white")
            row.paste(Image.fromarray(np.uint8(np.clip(before_v[frame], 0, 1) * 255)), (0, 20))
            row.paste(Image.fromarray(np.uint8(np.clip(after_v[frame], 0, 1) * 255)), (resolution, 20))
            rows.append(row)
        path = output / f"{name}.gif"
        _save_row_gif(path, rows, frame_ms)
        return str(path).replace("\\", "/")

    side_gif = view_gif("idle_side90", side_before, side_after)
    rear_gif = view_gif("idle_rear180", rear_before, rear_after)
    write_skeleton_overlay(
        output / "idle_skeleton_original.png",
        vertices=before_np[idle_frames[0]],
        regions=bundle["skin"]["regions"],
        joints=bundle["motion"]["jointWorld"][idle_frames[0], :, :3, 3],
        parents=bundle["skin"]["parents"],
        names=bundle["skin"]["names"],
        title="original capture idle frame 0",
    )
    write_skeleton_overlay(
        output / "idle_skeleton_corrected.png",
        vertices=after_np[idle_frames[0]],
        regions=bundle["skin"]["regions"],
        joints=(
            result["world"][idle_frames[0], :, :3, 3].cpu().numpy()
            if result["world"] is not None
            else bundle["motion"]["jointWorld"][idle_frames[0], :, :3, 3]
        ),
        parents=bundle["skin"]["parents"],
        names=bundle["skin"]["names"],
        title="candidate pose idle frame 0" if result["world"] is not None else "assess verts; joints are original capture",
    )
    times = np.arange(len(local_np), dtype=np.float32) * frame_ms / 1000.0
    glb = output / "refined_master.glb"
    write_skinned_glb(
        glb,
        names=bundle["skin"]["names"],
        parents=bundle["skin"]["parents"],
        rest_local_rotation=bundle["skin"]["restLocalRotation"],
        rest_local_translation=bundle["skin"]["offsets"],
        inverse_bind=bundle["skin"]["inverseBind"],
        vertices=bundle["skin"]["vertices"],
        triangles=bundle["skin"]["triangles"],
        uvs=bundle["skin"]["uvs"],
        albedo=bundle["skin"]["albedo"],
        weights=bundle["weights"],
        animation={"name": f"{unit}_pose_refine_pilot", "times": times, "rotations": matrices_to_xyzw(local_np)},
    )
    parity = verify_calibrated_export(
        glb, expected_meshes=after_np, expected_times=times, idle_frame=None, allow_root_motion=True
    )
    changed = []
    for frame in plan["freeFrames"]:
        for joint, name in zip(bundle["wings"]["indices"], bundle["wings"]["names"]):
            angle = float(so3_geodesic_np(base_np[frame, joint], local_np[frame, joint]))
            if angle > 1e-5:
                changed.append({"globalIndex": frame, "joint": name, "geodesicRad": angle})
    np.savez_compressed(
        output / "corrected_local_rotation.npz",
        originalLocalRotation=base_np,
        correctedLocalRotation=local_np,
        originalVertices=before_np,
        correctedVertices=after_np,
        freeFrames=np.asarray(plan["freeFrames"], dtype=np.int64),
        pinnedFrames=np.asarray(plan["pinnedFrames"], dtype=np.int64),
        moveFrames=np.asarray(plan["moveFrames"], dtype=np.int64),
        wingJoints=np.asarray(bundle["wings"]["indices"], dtype=np.int64),
        wingJointNames=np.asarray(bundle["wings"]["names"]),
        protectedJoints=np.asarray(bundle["wings"]["protectedIndices"], dtype=np.int64),
    )
    report = {
        "schema": SCHEMA,
        "ok": True,
        "proof": "generated-candidate",
        "visualAcceptance": "unreviewed",
        "unit": unit,
        "motionOwner": MOTION_OWNER,
        "doesNotReplaceSkinSolver": True,
        "doesNotOverwriteOriginalCapture": True,
        "twistPolicy": TWIST_POLICY,
        "inputs": bundle["paths"],
        "inputHashes": bundle["hashes"],
        "plan": {
            "optimizeFrames": plan["optimizeFrames"],
            "freeFrames": plan["freeFrames"],
            "pinnedFrames": plan["pinnedFrames"],
            "moveFrames": plan["moveFrames"],
            "adjacentToMove": plan["adjacentToMove"],
            "regularizePairs": plan["regularizePairs"],
            "clips": {name: {"clipKey": clip["clipKey"], "frames": clip["frames"]} for name, clip in plan["clips"].items()},
        },
        "changedJoints": bundle["wings"]["names"],
        "changedJointRegions": bundle["wings"]["byRegion"],
        "protectedJoints": bundle["wings"]["protectedNames"],
        "changedFrameJoints": changed,
        "assessedFrozenV1": assess_npz is not None,
        "optimization": {
            "gpuBudgetSeconds": gpu_seconds,
            "gpuSecondsUsed": result.get("gpuSecondsUsed", gpu_seconds_used),
            "searchSlices": result.get("searchSlices", []),
            "equalStartAllocation": True,
            "startPolicy": "capture_only" if capture_only else "five_deterministic_starts",
            "starts": _json_starts(result["starts"]),
            "selectedStart": result["selectedStart"],
            "selectedEligible": result.get("selectedEligible"),
            "magnitudeBoundRad": MAX_JOINT_DELTA_RAD,
            "magnitudeBoundIsVectorNorm": True,
            "weights": {
                "image": IMAGE_WEIGHT,
                "strain": STRAIN_WEIGHT,
                "rotationChange": ROTATION_WEIGHT,
                "temporal": TEMPORAL_WEIGHT,
                "continuityGate": CONTINUITY_GATE_WEIGHT,
                "perFrameIouGate": FRAME_IOU_GATE_WEIGHT,
            },
            "rotationPenalty": "so3_geodesic_sq_chordal_half_frobenius",
            "cameraPolicy": "saved_linked_master_camera_shared_canvas_no_reframe",
            "previewSource": "optimization_target_pixels",
        },
        "clips": clips,
        "geometry": geometry,
        "continuity": scored["continuity"],
        "eligibility": scored["eligibility"],
        "acceptance": gate,
        "disposition": gate["disposition"],
        "exportParity": parity,
        "evidence": {
            "pilotComparisonGif": str(compare_path).replace("\\", "/"),
            "idleComparisonGif": str((output / "idle_comparison.gif").resolve()).replace("\\", "/"),
            "idleCloseGif": str(close_path.resolve()).replace("\\", "/"),
            "transitionComparisonGif": str((output / "transition_comparison.gif").resolve()).replace("\\", "/"),
            "idleSide90Gif": side_gif,
            "idleRear180Gif": rear_gif,
            "idleSkeletonOriginal": str((output / "idle_skeleton_original.png").resolve()).replace("\\", "/"),
            "idleSkeletonCorrected": str((output / "idle_skeleton_corrected.png").resolve()).replace("\\", "/"),
            "refinedGlb": str(glb).replace("\\", "/"),
            "starts": start_evidence,
        },
        "timings": {
            "loadSeconds": load_seconds,
            "gpuOptimizeSeconds": gpu_seconds_used,
            "renderEvidenceSeconds": time.perf_counter() - render_started,
            "elapsedWallSeconds": time.perf_counter() - wall_started,
            "stageSeparated": True,
        },
    }
    _write_json(output / "report.json", report)
    print(
        json.dumps(
            {
                "ok": True,
                "disposition": gate["disposition"],
                "reasons": gate["reasons"],
                "idleMeanIouImprovement": clips["idle"]["meanIouImprovement"],
                "worstIdleFrame": clips["idle"]["worstFrame"],
                "selectedStart": result["selectedStart"],
                "eligible": scored["eligibility"]["passed"],
                "gpuSeconds": gpu_seconds_used,
                "wallSeconds": report["timings"]["elapsedWallSeconds"],
                "gif": report["evidence"]["pilotComparisonGif"],
            },
            indent=2,
        )
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", default=PILOT_UNIT)
    parser.add_argument("--linked-master", type=Path, default=DEFAULT_LINKED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--gpu-seconds", type=float, default=GPU_BUDGET_SECONDS)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--assess-npz", type=Path, default=None, help="Re-score a frozen candidate; do not optimize")
    parser.add_argument("--capture-only", action="store_true", help="Spend the search budget on the unchanged-capture initializer; no fold or noise starts")
    args = parser.parse_args()
    if args.assess_npz is None and not 1.0 <= args.gpu_seconds <= GPU_BUDGET_SECONDS + 1e-6:
        raise ValueError(f"gpu-seconds must be in (0, {GPU_BUDGET_SECONDS}]")

    def absolute(path: Path) -> Path:
        return (path if path.is_absolute() else REPO / path).resolve()

    run(
        linked_dir=absolute(args.linked_master),
        output=absolute(args.output),
        unit=args.unit,
        gpu_seconds=float(args.gpu_seconds),
        overwrite=bool(args.overwrite),
        assess_npz=None if args.assess_npz is None else absolute(args.assess_npz),
        capture_only=bool(args.capture_only),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
