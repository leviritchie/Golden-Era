#!/usr/bin/env python3
"""Detect post-pose 2D residual on frozen GPU cascade clips.

v1 ``vertex_array`` group offsets were **invalidated**: they used preview scoring
(collision/depth stripped, chroma boosted) and treated normal attack LBS strain
as warp. Independent camera-space group slides improved the wrong metric while
breaking 3D coherence.

Current contract:
  1. Rescore frozen poses with ``gpu_config_for_rescore`` (same weights as fit).
  2. Abort unless rescore matches source ``frameScores`` within tolerance.
  3. Flag regions from **chroma residual only** (not LBS strain during motion).
  4. Do **not** apply vertex offsets unless ``apply_corrections=True`` **and**
     per-frame rescore improves vs source under the same objective.

Proof: generated artifact validated — not OE runtime proven.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GROUPS = Path(__file__).resolve().parent / "cavalier_owned_anatomy_groups.json"


@dataclass(frozen=True)
class WarpDetectConfig:
    group_chroma_threshold: float = 0.18
    min_group_vertices: int = 24
    min_groups_flagged: int = 1


@dataclass(frozen=True)
class RescoreParityConfig:
    max_mean_abs_delta: float = 0.025
    max_frame_abs_delta: float = 0.06


def _require_cuda():
    from nvdiffrast_local import ensure_local_nvdiffrast

    ensure_local_nvdiffrast(required=True)


def _load_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("poses"), Mapping):
        raise ValueError(f"{path} has no poses")
    if not payload.get("cameraFitPath"):
        raise ValueError(f"{path} has no cameraFitPath")
    if not isinstance(payload.get("config"), Mapping):
        raise ValueError(f"{path} has no config")
    return payload


def _experiment_from_clip(
    *,
    clip_path: Path,
    mesh_glb: Path,
    frame_indices: Sequence[int] | None = None,
    rescore: bool = True,
):
    from cascade_clip_pose_tweak import clone_poses, gpu_config_for_preview, gpu_config_for_rescore, target_frame_dir_from_clip
    from roc_gpu_cascade_experiment import GpuCascadeExperiment

    payload = _load_payload(clip_path)
    config = gpu_config_for_rescore(payload["config"]) if rescore else gpu_config_for_preview(payload["config"])
    frames = (
        tuple(int(f) for f in payload.get("frameIndices") or sorted(int(k) for k in payload["poses"]))
        if frame_indices is None
        else tuple(int(f) for f in frame_indices)
    )
    experiment = GpuCascadeExperiment(
        src_glb=Path(mesh_glb).resolve(),
        camera_fit=Path(str(payload["cameraFitPath"])).resolve(),
        target_frame_dir=target_frame_dir_from_clip(payload),
        frame_indices=frames,
        config=config,
    )
    poses = clone_poses(payload)
    return experiment, payload, poses


def frozen_pose_tensors(experiment, poses: Mapping[int, Mapping[str, Any]]):
    normalized = {int(frame): dict(pose) for frame, pose in poses.items()}
    bone_vectors, root_translation, root_rotation = experiment._initial_pose_tensors(normalized)
    bone_vectors = experiment._bounded_bone_vectors(bone_vectors)
    return bone_vectors, root_translation, root_rotation


def all_frame_poses(experiment, poses: Mapping[int, Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    missing = [frame for frame in experiment.frame_indices if int(frame) not in poses]
    if missing:
        raise ValueError(f"poses are missing frames: {missing}")
    return {int(frame): dict(poses[int(frame)]) for frame in experiment.frame_indices}


def rescore_frozen_clip(
    experiment,
    poses: Mapping[int, Mapping[str, Any]],
    *,
    vertex_offsets=None,
) -> dict[str, Any]:
    clip_poses = all_frame_poses(experiment, poses)
    bone_vectors, root_translation, root_rotation = frozen_pose_tensors(experiment, clip_poses)
    components = experiment.evaluate(
        bone_vectors,
        root_translation,
        root_rotation,
        vertex_offsets=vertex_offsets,
    )
    scores = components["score"].detach().cpu().numpy().tolist()
    collision = components.get("collisionError")
    collision_values = (
        collision.detach().cpu().numpy().tolist() if collision is not None else [0.0] * len(scores)
    )
    iou = components["iou"].detach().cpu().numpy().tolist()
    chroma_q = components.get("chromaQuality")
    chroma_values = chroma_q.detach().cpu().numpy().tolist() if chroma_q is not None else [0.0] * len(scores)
    return {
        "frameIndices": [int(f) for f in experiment.frame_indices],
        "frameScores": [float(v) for v in scores],
        "frameIoU": [float(v) for v in iou],
        "frameChromaQuality": [float(v) for v in chroma_values],
        "frameCollisionError": [float(v) for v in collision_values],
        "meanScore": float(np.mean(scores)),
    }


def validate_rescore_parity(
    payload: Mapping[str, Any],
    rescore: Mapping[str, Any],
    *,
    cfg: RescoreParityConfig | None = None,
) -> dict[str, Any]:
    parity = cfg or RescoreParityConfig()
    source_scores = payload.get("frameScores")
    if not isinstance(source_scores, Sequence) or not source_scores:
        raise ValueError("clip payload has no frameScores for parity check")
    if len(source_scores) != len(rescore["frameScores"]):
        raise ValueError(
            f"frameScores length mismatch: source={len(source_scores)} rescore={len(rescore['frameScores'])}"
        )
    deltas = [
        float(rescore["frameScores"][i]) - float(source_scores[i])
        for i in range(len(source_scores))
    ]
    abs_deltas = [abs(delta) for delta in deltas]
    mean_abs = float(np.mean(abs_deltas))
    max_abs = float(np.max(abs_deltas))
    ok = mean_abs <= parity.max_mean_abs_delta and max_abs <= parity.max_frame_abs_delta
    worst = int(np.argmax(abs_deltas))
    return {
        "ok": ok,
        "meanAbsDelta": mean_abs,
        "maxAbsDelta": max_abs,
        "worstFrameIndex": int(rescore["frameIndices"][worst]),
        "worstDelta": float(deltas[worst]),
        "sourceMeanScore": float(np.mean(source_scores)),
        "rescoreMeanScore": float(rescore["meanScore"]),
        "perFrameDelta": deltas,
        "limits": parity.__dict__,
    }


def _project_vertices_to_pixels(experiment, vertices) -> tuple[np.ndarray, np.ndarray]:
    import torch

    right = experiment.camera_right
    down = experiment.camera_down
    offset = experiment.camera_offset
    px = experiment.px_per_world
    if vertices.ndim == 2:
        vertices = vertices.unsqueeze(0)
    pts = vertices[0]
    sx = torch.sum(pts * right, dim=-1) * px[0] + offset[0]
    sy = torch.sum(pts * down, dim=-1) * px[1] + offset[1]
    return sx.detach().cpu().numpy(), sy.detach().cpu().numpy()


def _frame_chroma_error_map(
    experiment,
    bone_vectors,
    root_translation,
    root_rotation,
    *,
    frame_index: int,
    vertex_offsets=None,
):
    import torch
    from gpu_geometry_score import chroma_quality, srgb_rgb_to_lab_ab

    frame_pos = experiment.frame_indices.index(int(frame_index))
    with torch.no_grad():
        predicted_rgb, predicted_alpha, _depth = experiment.exact_triangle_rgb(
            bone_vectors[frame_pos : frame_pos + 1],
            root_translation[frame_pos : frame_pos + 1],
            root_rotation[frame_pos : frame_pos + 1],
            bone_mask=experiment.active_node_mask,
            vertex_offsets=None if vertex_offsets is None else vertex_offsets[frame_pos : frame_pos + 1],
        )
    target_alpha = experiment.target_masks[frame_pos : frame_pos + 1]
    target_foreground = (target_alpha > 0.5).to(dtype=predicted_alpha.dtype)
    predicted_occupancy = predicted_alpha.clamp(0.0, 1.0)
    chroma = chroma_quality(
        target_foreground=target_foreground,
        predicted_foreground=predicted_occupancy,
        target_ab=experiment.target_lab_ab[frame_pos : frame_pos + 1],
        predicted_ab=srgb_rgb_to_lab_ab(predicted_rgb),
        chroma_tolerance=float(experiment.config.chroma_tolerance),
        chroma_robust_delta=float(experiment.config.chroma_robust_delta),
        chroma_error_scale=float(experiment.config.chroma_error_scale),
    )
    return chroma["pixelChromaError"]


def _group_chroma_means(
    experiment,
    bone_vectors,
    root_translation,
    root_rotation,
    *,
    frame_index: int,
    group_masks,
    pixel_chroma_error,
) -> list[float]:
    import torch

    frame_pos = experiment.frame_indices.index(int(frame_index))
    worlds = experiment._forward_kinematics(
        bone_vectors[frame_pos : frame_pos + 1],
        bone_mask=experiment.active_node_mask,
    )
    parts = [
        experiment._skinned_vertices(worlds, primitive)[0]
        for primitive in experiment.primitives
    ]
    verts = experiment._root_transform(
        torch.cat(parts, dim=0).unsqueeze(0),
        root_translation[frame_pos : frame_pos + 1],
        root_rotation[frame_pos : frame_pos + 1],
    )[0]
    sx, sy = _project_vertices_to_pixels(experiment, verts)
    err = pixel_chroma_error[0].detach().cpu().numpy()
    means: list[float] = []
    for mask in group_masks:
        idx = torch.nonzero(mask, as_tuple=False).reshape(-1).detach().cpu().numpy()
        if idx.size < 1:
            means.append(1.0)
            continue
        xs = np.clip(np.rint(sx[idx]).astype(np.int64), 0, err.shape[1] - 1)
        ys = np.clip(np.rint(sy[idx]).astype(np.int64), 0, err.shape[0] - 1)
        means.append(float(np.mean(err[ys, xs])))
    return means


def detect_frame_warp(
    experiment,
    poses: Mapping[int, Mapping[str, Any]],
    *,
    frame_index: int,
    group_masks,
    detect_cfg: WarpDetectConfig,
    source_frame_score: float,
) -> dict[str, Any]:
    clip_poses = all_frame_poses(experiment, poses)
    bone_vectors, root_translation, root_rotation = frozen_pose_tensors(experiment, clip_poses)
    frame_pos = experiment.frame_indices.index(int(frame_index))
    components = experiment.evaluate(
        bone_vectors[frame_pos : frame_pos + 1],
        root_translation[frame_pos : frame_pos + 1],
        root_rotation[frame_pos : frame_pos + 1],
        frame_indices=(int(frame_index),),
    )
    rescore_score = float(components["score"][0].item())
    pixel_chroma = _frame_chroma_error_map(
        experiment,
        bone_vectors,
        root_translation,
        root_rotation,
        frame_index=int(frame_index),
    )
    group_names = getattr(experiment, "_warp_group_names", ())
    group_chroma = _group_chroma_means(
        experiment,
        bone_vectors,
        root_translation,
        root_rotation,
        frame_index=int(frame_index),
        group_masks=group_masks,
        pixel_chroma_error=pixel_chroma,
    )
    flagged = [
        str(name)
        for name, chroma_mean in zip(group_names, group_chroma, strict=True)
        if chroma_mean >= detect_cfg.group_chroma_threshold
    ]
    return {
        "frameIndex": int(frame_index),
        "sourceFrameScore": float(source_frame_score),
        "rescoreScore": rescore_score,
        "rescoreDelta": rescore_score - float(source_frame_score),
        "groupChromaMean": group_chroma,
        "flaggedGroups": flagged,
        "flaggedForRepair": len(flagged) >= int(detect_cfg.min_groups_flagged),
    }


def evaluate_frozen_with_offsets(
    experiment,
    poses: Mapping[int, Mapping[str, Any]],
    offsets,
    *,
    frame_index: int | None = None,
) -> dict[str, Any]:
    import torch

    clip_poses = all_frame_poses(experiment, poses)
    bone_vectors, root_translation, root_rotation = frozen_pose_tensors(experiment, clip_poses)
    if offsets.ndim == 2:
        offsets = offsets.unsqueeze(0)
    frame_indices = None if frame_index is None else (int(frame_index),)
    return experiment.evaluate(
        bone_vectors,
        root_translation,
        root_rotation,
        frame_indices=frame_indices,
        vertex_offsets=offsets,
    )


def score_frozen_offsets(
    experiment,
    poses: Mapping[int, Mapping[str, Any]],
    offsets,
    *,
    frame_index: int,
) -> float:
    components = evaluate_frozen_with_offsets(
        experiment,
        poses,
        offsets,
        frame_index=frame_index,
    )
    return float(components["score"][0].item())


def optimize_flagged_offsets(
    experiment,
    state,
    poses: Mapping[int, Mapping[str, Any]],
    *,
    frame_index: int,
    flagged_groups: Sequence[str],
    source_frame_score: float,
    max_rounds: int = 5,
    seed_params: np.ndarray | None = None,
) -> tuple[np.ndarray, float, bool]:
    from gpu_alternate_deform import _step_sizes, offsets_from_params, params_dim

    method = "vertex_array"
    dim = params_dim(state, method)
    group_index = {name: i for i, name in enumerate(state.group_names)}
    active_dims: list[int] = []
    for name in flagged_groups:
        gi = group_index.get(name)
        if gi is None:
            continue
        base = gi * 3
        active_dims.extend((base, base + 1, base + 2))
    params = np.zeros((dim,), dtype=np.float64)
    if seed_params is not None:
        params = np.asarray(seed_params, dtype=np.float64).reshape(-1).copy()
    device = experiment.device
    baseline = score_frozen_offsets(
        experiment,
        poses,
        offsets_from_params(state, method, params, device).unsqueeze(0),
        frame_index=frame_index,
    )
    if baseline + 1e-6 < float(source_frame_score):
        return params, baseline, False
    if not active_dims:
        return params, baseline, False
    steps = _step_sizes(state, method)
    best_score = baseline
    for _round in range(int(max_rounds)):
        improved = False
        for dim_index in active_dims:
            for direction in (-1.0, 1.0):
                trial = params.copy()
                trial[dim_index] += direction * steps[dim_index]
                offsets = offsets_from_params(state, method, trial, device).unsqueeze(0)
                trial_score = score_frozen_offsets(
                    experiment,
                    poses,
                    offsets,
                    frame_index=frame_index,
                )
                if trial_score > best_score + 1e-6:
                    params = trial
                    best_score = trial_score
                    improved = True
        if not improved:
            break
    accepted = best_score > float(source_frame_score) + 1e-5
    if not accepted:
        params = np.zeros((dim,), dtype=np.float64)
        best_score = baseline
    return params, best_score, accepted


def export_frozen_pose_rgb(
    experiment,
    poses: Mapping[int, Mapping[str, Any]],
    offsets,
    output_dir: Path,
) -> Path:
    import torch
    from PIL import Image

    from preview_timing import PREVIEW_GIF_FRAME_MS

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    clip_poses = all_frame_poses(experiment, poses)
    bone_vectors, root_translation, root_rotation = frozen_pose_tensors(experiment, clip_poses)
    frame_count = len(experiment.frame_indices)
    vcount = state_vertex_count(experiment)
    if offsets is None:
        offsets_batch = torch.zeros((frame_count, vcount, 3), dtype=torch.float32, device=experiment.device)
    elif offsets.ndim == 2:
        offsets_batch = offsets.unsqueeze(0)
    else:
        offsets_batch = offsets
    with torch.no_grad():
        rgb, _alpha, _depth = experiment.exact_triangle_rgb(
            bone_vectors,
            root_translation,
            root_rotation,
            bone_mask=experiment.active_node_mask,
            vertex_offsets=offsets_batch,
        )
    images = []
    for frame_position, frame in enumerate(experiment.frame_indices):
        array = rgb[frame_position].detach().clamp(0.0, 1.0).mul(255.0).byte().cpu().numpy()
        image = Image.fromarray(array, "RGB")
        image.save(output_dir / f"{int(frame):02d}.png", format="PNG", compress_level=0)
        images.append(image)
    gif_path = output_dir / "gpu_solved_rgb.gif"
    images[0].save(
        gif_path,
        save_all=True,
        append_images=images[1:],
        duration=int(PREVIEW_GIF_FRAME_MS),
        loop=0,
        optimize=False,
    )
    return gif_path


def state_vertex_count(experiment) -> int:
    return sum(int(primitive.positions.shape[0]) for primitive in experiment.primitives)


def repair_clip_warp(
    *,
    clip_path: Path,
    mesh_glb: Path,
    output_dir: Path,
    groups_catalog_path: Path = DEFAULT_GROUPS,
    detect_cfg: WarpDetectConfig | None = None,
    parity_cfg: RescoreParityConfig | None = None,
    max_rounds: int = 5,
    frame_indices: Sequence[int] | None = None,
    apply_corrections: bool = False,
) -> dict[str, Any]:
    import torch
    from gpu_alternate_deform import build_alternate_deform_state, offsets_from_params, params_dim
    from cascade_clip_pose_tweak import clone_poses

    _require_cuda()
    started = time.perf_counter()
    cfg = detect_cfg or WarpDetectConfig()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    experiment, payload, poses = _experiment_from_clip(
        clip_path=clip_path,
        mesh_glb=mesh_glb,
        frame_indices=frame_indices,
        rescore=True,
    )
    baseline_rescore = rescore_frozen_clip(experiment, poses)
    parity = validate_rescore_parity(payload, baseline_rescore, cfg=parity_cfg)
    if not parity["ok"]:
        report = {
            "ok": False,
            "aborted": True,
            "reason": "rescore_parity_failed",
            "parity": parity,
            "baselineRescore": baseline_rescore,
            "invalidatedMethods": ["post_pose_warp_repair_vertex_array_v1"],
            "proof": "rescore parity gate failed — metrics not trustworthy for repair",
        }
        (output_dir / "warp_repair_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report

    visit = tuple(json.loads(Path(groups_catalog_path).read_text(encoding="utf-8"))["groups"].keys())
    state = build_alternate_deform_state(
        experiment,
        groups_catalog_path=groups_catalog_path,
        group_visit_order=visit,
    )
    experiment._warp_group_names = state.group_names  # noqa: SLF001

    source_scores = [float(v) for v in payload["frameScores"]]
    detections: list[dict[str, Any]] = []
    per_frame_params: list[np.ndarray] = []
    per_frame_accepted: list[bool] = []
    method = "vertex_array"

    seed: np.ndarray | None = None
    for frame_pos, frame in enumerate(experiment.frame_indices):
        det = detect_frame_warp(
            experiment,
            poses,
            frame_index=int(frame),
            group_masks=state.group_masks,
            detect_cfg=cfg,
            source_frame_score=source_scores[frame_pos],
        )
        detections.append(det)
        if not apply_corrections or not det["flaggedForRepair"]:
            params = np.zeros((params_dim(state, method),), dtype=np.float64)
            accepted = False
            score_after = det["rescoreScore"]
        else:
            params, score_after, accepted = optimize_flagged_offsets(
                experiment,
                state,
                all_frame_poses(experiment, poses),
                frame_index=int(frame),
                flagged_groups=det["flaggedGroups"],
                source_frame_score=source_scores[frame_pos],
                max_rounds=max_rounds,
                seed_params=seed,
            )
        per_frame_params.append(params)
        per_frame_accepted.append(accepted)
        det["scoreAfter"] = float(score_after)
        det["acceptedCorrection"] = accepted
        seed = params if accepted else seed

    offsets = torch.stack(
        [offsets_from_params(state, method, params, experiment.device) for params in per_frame_params],
        dim=0,
    )
    repaired_rescore = rescore_frozen_clip(experiment, poses, vertex_offsets=offsets)
    export_frozen_pose_rgb(experiment, poses, None, output_dir / "baseline_rgb")
    if apply_corrections and any(per_frame_accepted):
        export_frozen_pose_rgb(experiment, poses, offsets, output_dir / "solved_rgb")
    else:
        export_frozen_pose_rgb(experiment, poses, None, output_dir / "solved_rgb")

    report = {
        "ok": True,
        "aborted": False,
        "method": "post_pose_warp_repair_chroma_detect_rescore_gated",
        "applyCorrections": bool(apply_corrections),
        "acceptedFrameCount": int(sum(1 for item in per_frame_accepted if item)),
        "sourceClip": str(Path(clip_path).resolve()),
        "meshGlb": str(Path(mesh_glb).resolve()),
        "groupsCatalog": str(Path(groups_catalog_path).resolve()),
        "frameIndices": [int(f) for f in experiment.frame_indices],
        "parity": parity,
        "baselineRescore": baseline_rescore,
        "repairedRescore": repaired_rescore,
        "sourceMeanScore": float(np.mean(source_scores)),
        "detectConfig": cfg.__dict__,
        "frames": detections,
        "perFrameParams": [params.tolist() for params in per_frame_params],
        "perFrameAccepted": per_frame_accepted,
        "elapsedSec": round(time.perf_counter() - started, 1),
        "invalidatedMethods": [
            "post_pose_warp_repair_vertex_array_v1: preview scoring + LBS strain flags + uncoupled group slides",
        ],
        "proof": "generated artifact validated — rescore-parity gated detect; corrections off unless --apply and per-frame gain",
    }
    (output_dir / "warp_repair_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if apply_corrections and report["acceptedFrameCount"] > 0:
        repaired_payload = dict(payload)
        repaired_payload["poses"] = clone_poses(payload)
        repaired_payload["warpRepair"] = {
            "method": report["method"],
            "perFrameGroupParams": report["perFrameParams"],
            "perFrameAccepted": report["perFrameAccepted"],
            "groupNames": list(state.group_names),
            "sourceClip": report["sourceClip"],
        }
        (output_dir / "gpu_clip_result_warp_repaired.json").write_text(
            json.dumps(repaired_payload, indent=2) + "\n",
            encoding="utf-8",
        )
    return report
