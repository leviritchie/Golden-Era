#!/usr/bin/env python3
"""Decide whether a solved clip is rig-limited or merely search-limited.

Why a dedicated test
--------------------
"The correction descent stopped improving" is **not** evidence that the skeleton
cannot express the sprite. Greedy one-bone-at-a-time descent stalls in local
minima all the time, and a stall plus a low score looks identical to a genuine
rig limit. Acting on that confusion is how the previous non-bone deformation
attempt went wrong: `gpu_post_pose_warp_repair` records that v1 treated ordinary
skinning strain as "warp" and then let free vertex offsets improve a different
metric than the fit objective, breaking 3D coherence while the number went up.

So this module does not ask about the search. It asks a structural question
about the rig:

    For each region the sprite fills but the posed mesh misses, can ANY single
    bone -- driven all the way to its joint limit, in either direction, on each
    axis -- bring mesh surface into that region?

If nothing reaches, no amount of extra search on this skeleton will cover those
pixels, because rotation within the joint limits cannot put surface there. That
is a statement about reachability, not about optimiser quality, and it is the
only honest basis for adding a non-bone deformation channel.

Deliberately generous to the rig, so a "rig-limited" verdict is hard to earn:
  - probes at the FULL joint limit, not the descent's fine steps
  - every searchable bone, every axis, both directions
  - reachability only needs surface within ``cover_tolerance_px`` of the region

Known limit of this version, stated rather than hidden: probes are single-bone.
A coordinated multi-bone pose could reach further than any bone alone, so a
"rigLimited" verdict here means "unreachable by any one bone at its limit", which
is strong evidence but not a proof over all poses. Pair probes would tighten it.

Proof tier: generated artifact. Not OE runtime.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from literature_polish_common import (  # noqa: E402
    assert_write_path,
    load_polish_experiment,
    unit_mesh,
)
from def_continuous_pose_tracker import (  # noqa: E402
    _active_axis_indices,
    _root_rotation_offset,
    _root_translation_offset,
)
from preview_timing import PREVIEW_GIF_FRAME_MS  # noqa: E402
from roc_gpu_cascade_experiment import offset_raw_bone_direction  # noqa: E402

REACH_AXES: tuple[tuple[float, float, float], ...] = (
    (1.0, 0.0, 0.0),
    (-1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, -1.0, 0.0),
    (0.0, 0.0, 1.0),
    (0.0, 0.0, -1.0),
)


@dataclass(frozen=True)
class RigSufficiencyConfig:
    mask_threshold: float = 0.5
    # Ignore specks; a handful of antialiased pixels is not a rig deficiency.
    min_blob_area_px: int = 12
    # Mesh surface this close to a region counts as able to cover it.
    cover_tolerance_px: float = 2.0
    # Blob pixels sampled when measuring distance from the mesh to the region.
    blob_probe_points: int = 48
    # Mesh samples forming the local patch that must do the covering.
    patch_samples: int = 64
    # Multiplier on the joint limit for reach probes; >1 saturates the clamp so
    # each probe really sits at the limit rather than near the current angle.
    reach_limit_multiple: float = 2.0


def _binary(mask: np.ndarray, threshold: float) -> np.ndarray:
    return (mask >= float(threshold)).astype(np.uint8)


def _blob_probe_points(blob_mask: np.ndarray, *, limit: int) -> np.ndarray:
    """Pixel coordinates sampled across one uncovered region, as [K, 2] xy.

    Deterministic even striding, not random choice. A random subset makes the
    verdict depend on draw order: the palindromic idle frames 2 and 5 are the
    same sprite at the same score, and random sampling reported 36px vs 111px
    rig-limited for them. Identical input must give an identical verdict.
    """
    ys, xs = np.nonzero(blob_mask)
    points = np.stack((xs, ys), axis=-1).astype(np.float32)
    if points.shape[0] <= int(limit):
        return points
    stride_index = np.linspace(0, points.shape[0] - 1, num=int(limit)).astype(np.int64)
    return points[stride_index]


def _pairwise_distance(cloud_xy: np.ndarray, probe_xy: np.ndarray) -> np.ndarray:
    deltas = probe_xy[:, None, :] - cloud_xy[None, :, :]
    return np.sqrt((deltas * deltas).sum(-1))


def _coverage_distance(cloud_xy: np.ndarray, probe_xy: np.ndarray) -> float:
    """Mean px distance from each region probe point to the nearest mesh sample."""
    if cloud_xy.size == 0 or probe_xy.size == 0:
        return float("inf")
    return float(_pairwise_distance(cloud_xy, probe_xy).min(axis=1).mean())


def _local_patch_indices(
    cloud_xy: np.ndarray, probe_xy: np.ndarray, *, patch_samples: int
) -> np.ndarray:
    """Indices of the mesh samples currently nearest an uncovered region.

    Reachability has to follow the *same* surface. Allowing any vertex to satisfy
    the region lets a full-limit root translation slide the torso into where a
    wing tip belongs and report the region as covered -- technically "surface got
    there", but a different body part, which is not what covering means.
    """
    per_sample = _pairwise_distance(cloud_xy, probe_xy).min(axis=0)
    count = int(min(int(patch_samples), per_sample.shape[0]))
    return np.argpartition(per_sample, count - 1)[:count]


def _reach_probe_poses(
    experiment: Any,
    bones: torch.Tensor,
    root_translation: torch.Tensor,
    root_rotation: torch.Tensor,
    *,
    bone_indices: Sequence[int],
    config: RigSufficiencyConfig,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, list[str]]:
    """Every single-DOF pose driven to its limit, batched. Generous by design.

    Covers bone rotations *and* root rotation/translation, because the root is a
    rig degree of freedom too. Leaving it out would let "the whole body needed to
    shift" masquerade as "the skeleton cannot deform there".
    """
    joint_limit_rad = math.radians(float(experiment.config.joint_limit_deg))
    bone_delta = float(config.reach_limit_multiple) * joint_limit_rad
    root_rotation_delta = float(config.reach_limit_multiple) * math.radians(
        float(experiment.config.root_rotation_limit_optimization_deg)
    )
    root_translation_delta = float(config.reach_limit_multiple) * float(
        experiment.config.root_translation_limit_body_lengths
    )

    bone_batch: list[torch.Tensor] = []
    translation_batch: list[torch.Tensor] = []
    rotation_batch: list[torch.Tensor] = []
    labels: list[str] = []

    base_bones = bones.unsqueeze(0)
    base_translation = root_translation.unsqueeze(0)
    base_rotation = root_rotation.unsqueeze(0)

    searchable = {int(index) for index in bone_indices}
    for bone_index in bone_indices:
        chain = _searchable_ancestor_chain(experiment, int(bone_index), searchable)
        for axis in REACH_AXES:
            single = offset_raw_bone_direction(
                base_bones,
                bone_index=int(bone_index),
                direction=axis,
                delta_rad=bone_delta,
                joint_limit_rad=joint_limit_rad,
                bone_limit_scales=experiment.bone_limit_scales,
            )
            bone_batch.append(single[0])
            translation_batch.append(root_translation)
            rotation_batch.append(root_rotation)
            labels.append(f"{experiment.node_names[int(bone_index)]}{_axis_tag(axis)}")

            # Compounded chain: this bone plus every searchable ancestor driven the
            # same way. A wing spread by shoulder+elbow+wrist together reaches far
            # past any single joint at its limit, so judging the rig on single-DOF
            # probes alone would overstate how much it cannot do.
            if len(chain) > 1:
                stacked = base_bones
                for member in chain:
                    stacked = offset_raw_bone_direction(
                        stacked,
                        bone_index=int(member),
                        direction=axis,
                        delta_rad=bone_delta,
                        joint_limit_rad=joint_limit_rad,
                        bone_limit_scales=experiment.bone_limit_scales,
                    )
                bone_batch.append(stacked[0])
                translation_batch.append(root_translation)
                rotation_batch.append(root_rotation)
                labels.append(
                    f"chain[{len(chain)}]:{experiment.node_names[int(bone_index)]}{_axis_tag(axis)}"
                )

    for axis_index in _active_axis_indices(experiment.root_rotation_mask):
        for sign in (1.0, -1.0):
            bone_batch.append(bones)
            translation_batch.append(root_translation)
            rotation_batch.append(
                _root_rotation_offset(
                    experiment,
                    base_rotation,
                    axis_index=axis_index,
                    delta_rad=sign * root_rotation_delta,
                )[0]
            )
            labels.append(f"rootRot{axis_index}{'+' if sign > 0 else '-'}")

    for axis_index in _active_axis_indices(experiment.root_translation_mask):
        for sign in (1.0, -1.0):
            bone_batch.append(bones)
            translation_batch.append(
                _root_translation_offset(
                    experiment,
                    base_translation,
                    axis_index=axis_index,
                    delta_body_lengths=sign * root_translation_delta,
                )[0]
            )
            rotation_batch.append(root_rotation)
            labels.append(f"rootTrans{axis_index}{'+' if sign > 0 else '-'}")

    return (
        torch.stack(bone_batch, dim=0),
        torch.stack(translation_batch, dim=0),
        torch.stack(rotation_batch, dim=0),
        labels,
    )


def _searchable_ancestor_chain(
    experiment: Any, bone_index: int, searchable: set[int]
) -> list[int]:
    """``bone_index`` plus its searchable ancestors, ordered root-first."""
    chain: list[int] = []
    current: int | None = int(bone_index)
    while current is not None:
        if int(current) in searchable:
            chain.append(int(current))
        parent = experiment.asset.nodes[int(current)].parent
        current = None if parent is None else int(parent)
    chain.reverse()
    return chain


def _axis_tag(axis: tuple[float, float, float]) -> str:
    names = ("X", "Y", "Z")
    for index, value in enumerate(axis):
        if value > 0.0:
            return f".{names[index]}+"
        if value < 0.0:
            return f".{names[index]}-"
    return ""


def analyse_frame(
    experiment: Any,
    bones: torch.Tensor,
    root_translation: torch.Tensor,
    root_rotation: torch.Tensor,
    *,
    frame_position: int,
    predicted: np.ndarray,
    target: np.ndarray,
    bone_indices: Sequence[int],
    config: RigSufficiencyConfig,
) -> dict[str, Any]:
    """Split this frame's uncovered area into bone-reachable and rig-limited parts."""
    predicted_bin = _binary(predicted, config.mask_threshold)
    target_bin = _binary(target, config.mask_threshold)
    uncovered = ((target_bin == 1) & (predicted_bin == 0)).astype(np.uint8)
    overcovered = ((predicted_bin == 1) & (target_bin == 0)).astype(np.uint8)

    frame_bones = bones[frame_position]
    frame_root_t = root_translation[frame_position].unsqueeze(0)
    frame_root_r = root_rotation[frame_position].unsqueeze(0)
    with torch.no_grad():
        current_cloud = (
            experiment.render_points(
                experiment._bounded_bone_vectors(frame_bones.unsqueeze(0)),
                frame_root_t,
                frame_root_r,
                bone_mask=experiment.active_node_mask,
            )[0]
            .detach()
            .cpu()
            .numpy()
            .astype(np.float32)
        )
        probe_poses, probe_translation, probe_rotation, labels = _reach_probe_poses(
            experiment,
            frame_bones,
            root_translation[frame_position],
            root_rotation[frame_position],
            bone_indices=bone_indices,
            config=config,
        )
        probe_clouds = (
            experiment.render_points(
                experiment._bounded_bone_vectors(probe_poses),
                probe_translation,
                probe_rotation,
                bone_mask=experiment.active_node_mask,
            )
            .detach()
            .cpu()
            .numpy()
            .astype(np.float32)
        )

    count, labelled, stats, centroids = cv2.connectedComponentsWithStats(uncovered, 8)
    blobs: list[dict[str, Any]] = []
    for index in range(1, int(count)):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < int(config.min_blob_area_px):
            continue
        blob_mask = (labelled == index).astype(np.uint8)
        probe_xy = _blob_probe_points(blob_mask, limit=int(config.blob_probe_points))
        patch = _local_patch_indices(
            current_cloud, probe_xy, patch_samples=int(config.patch_samples)
        )
        current_distance = _coverage_distance(current_cloud[patch], probe_xy)
        best_distance = current_distance
        best_label: str | None = None
        best_any_surface = current_distance
        for pose_index in range(probe_clouds.shape[0]):
            cloud = probe_clouds[pose_index]
            distance = _coverage_distance(cloud[patch], probe_xy)
            if distance < best_distance:
                best_distance = distance
                best_label = labels[pose_index]
            any_surface = _coverage_distance(cloud, probe_xy)
            if any_surface < best_any_surface:
                best_any_surface = any_surface
        reachable = best_distance <= float(config.cover_tolerance_px)
        blobs.append(
            {
                "areaPx": area,
                "centroid": [round(float(centroids[index][0]), 1), round(float(centroids[index][1]), 1)],
                "currentDistancePx": round(current_distance, 2),
                "bestSingleBoneDistancePx": round(best_distance, 2),
                "reachGainPx": round(current_distance - best_distance, 2),
                "bestDof": best_label,
                # Permissive comparison: any surface, no identity constraint. When
                # this is far below the patch distance, a global move is covering
                # the region with the wrong body part.
                "bestAnySurfaceDistancePx": round(best_any_surface, 2),
                "reachable": bool(reachable),
            }
        )

    rig_limited_area = sum(int(blob["areaPx"]) for blob in blobs if not blob["reachable"])
    reachable_area = sum(int(blob["areaPx"]) for blob in blobs if blob["reachable"])
    target_area = int(target_bin.sum())
    return {
        "framePosition": int(frame_position),
        "targetAreaPx": target_area,
        "uncoveredAreaPx": int(uncovered.sum()),
        "overcoveredAreaPx": int(overcovered.sum()),
        "blobsConsidered": len(blobs),
        "reachableAreaPx": reachable_area,
        "rigLimitedAreaPx": rig_limited_area,
        "rigLimitedFractionOfTarget": round(rig_limited_area / target_area, 4)
        if target_area
        else 0.0,
        "blobs": blobs,
        "_masks": {"uncovered": uncovered, "overcovered": overcovered},
    }


def write_residual_overlay_gif(
    *,
    frame_dir: Path,
    frame_indices: Sequence[int],
    reports: Sequence[dict[str, Any]],
    out: Path,
    upscale: int = 3,
) -> Path:
    """Sprite with uncovered red, overcovered blue, rig-limited regions ringed yellow."""
    panels: list[Image.Image] = []
    for report in reports:
        position = int(report["framePosition"])
        uncovered = report["_masks"]["uncovered"]
        overcovered = report["_masks"]["overcovered"]
        height, width = uncovered.shape
        sprite_path = frame_dir / f"{int(frame_indices[position]):02d}.png"
        sprite = (
            Image.open(sprite_path)
            .convert("RGB")
            .resize((width, height), Image.Resampling.LANCZOS)
        )
        canvas = np.asarray(sprite).astype(np.float32)
        canvas[uncovered == 1] = 0.35 * canvas[uncovered == 1] + 0.65 * np.array(
            [255.0, 40.0, 40.0]
        )
        canvas[overcovered == 1] = 0.55 * canvas[overcovered == 1] + 0.45 * np.array(
            [60.0, 110.0, 255.0]
        )
        image = Image.fromarray(canvas.clip(0, 255).astype(np.uint8)).resize(
            (width * upscale, height * upscale), Image.Resampling.NEAREST
        )
        draw = ImageDraw.Draw(image)
        for blob in report["blobs"]:
            if blob["reachable"]:
                continue
            cx, cy = (value * upscale for value in blob["centroid"])
            radius = max(6, int(math.sqrt(float(blob["areaPx"])) * upscale * 0.6))
            draw.ellipse(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                outline=(255, 230, 60),
                width=2,
            )
            draw.text((cx + radius + 2, cy - 6), f"{blob['bestSingleBoneDistancePx']}px", fill=(255, 230, 60))
        draw.text(
            (4, 4),
            f"f{int(frame_indices[position]):02d}  red=uncovered blue=over  "
            f"rigLimited={report['rigLimitedAreaPx']}px reachable={report['reachableAreaPx']}px",
            fill=(240, 240, 240),
        )
        panels.append(image)
    panels[0].save(
        out, save_all=True, append_images=panels[1:], duration=PREVIEW_GIF_FRAME_MS, loop=0
    )
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", default="h3_roc")
    parser.add_argument("--clip", default="idle_start_move_end")
    parser.add_argument(
        "--lane",
        required=True,
        help="Tracker lane directory name under artifacts/pose_picker_runs/<unit>/<clip>/.",
    )
    parser.add_argument("--cover-tolerance-px", type=float, default=None)
    parser.add_argument("--min-blob-area-px", type=int, default=None)
    parser.add_argument("--skip-gif", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    unit = str(args.unit)
    clip = str(args.clip)
    lane_root = ROOT / "artifacts" / "pose_picker_runs" / unit / clip / str(args.lane)
    clip_path = lane_root / "solve" / "gpu_clip_result.json"
    if not clip_path.is_file():
        raise FileNotFoundError(clip_path)

    config = RigSufficiencyConfig()
    if args.cover_tolerance_px is not None:
        config = RigSufficiencyConfig(
            **{**config.__dict__, "cover_tolerance_px": float(args.cover_tolerance_px)}
        )
    if args.min_blob_area_px is not None:
        config = RigSufficiencyConfig(
            **{**config.__dict__, "min_blob_area_px": int(args.min_blob_area_px)}
        )

    payload = json.loads(clip_path.read_text(encoding="utf-8"))
    experiment, bones, root_t, root_r = load_polish_experiment(
        payload=payload, mesh=unit_mesh(unit, clip)
    )
    frame_indices = list(experiment.frame_indices)
    bone_indices = [int(index) for index in experiment.search_node_indices]

    with torch.no_grad():
        packed = experiment.evaluate(
            experiment._bounded_bone_vectors(bones),
            root_t,
            root_r,
            bone_mask=experiment.active_node_mask,
        )
    predicted = packed["predictedMasks"].detach().cpu().numpy()
    target = packed["targetMasks"].detach().cpu().numpy()
    scores = [float(value) for value in packed["score"].detach().cpu().tolist()]

    reports: list[dict[str, Any]] = []
    for position in range(len(frame_indices)):
        report = analyse_frame(
            experiment,
            bones,
            root_t,
            root_r,
            frame_position=position,
            predicted=predicted[position],
            target=target[position],
            bone_indices=bone_indices,
            config=config,
        )
        report["frameIndex"] = int(frame_indices[position])
        report["silhouetteScore"] = round(scores[position], 4)
        reports.append(report)
        print(
            f"[rig ] frame {frame_indices[position]:>3} score={scores[position]:.4f} "
            f"uncovered={report['uncoveredAreaPx']:>5}px "
            f"reachable={report['reachableAreaPx']:>5}px "
            f"rigLimited={report['rigLimitedAreaPx']:>5}px "
            f"({report['rigLimitedFractionOfTarget'] * 100:5.2f}% of sprite)",
            flush=True,
        )

    gif = None
    if not bool(args.skip_gif):
        gif = write_residual_overlay_gif(
            frame_dir=Path(str(payload["targetPaths"][0])).parent,
            frame_indices=frame_indices,
            reports=reports,
            out=assert_write_path(lane_root) / "rig_sufficiency_residual.gif",
        )

    serialisable = [
        {key: value for key, value in report.items() if key != "_masks"} for report in reports
    ]
    total_target = sum(int(row["targetAreaPx"]) for row in serialisable)
    total_rig_limited = sum(int(row["rigLimitedAreaPx"]) for row in serialisable)
    total_reachable = sum(int(row["reachableAreaPx"]) for row in serialisable)
    summary = {
        "proof": "generated-artifact",
        "unit": unit,
        "clip": clip,
        "lane": str(args.lane),
        "clipResult": str(clip_path).replace("\\", "/"),
        "verdictBasis": "single_dof_full_limit_local_patch_reachability",
        "singleDofOnly": True,
        "rootDofsIncluded": True,
        "config": dict(config.__dict__),
        "clipRigLimitedFractionOfTarget": round(total_rig_limited / total_target, 4)
        if total_target
        else 0.0,
        "clipReachableFractionOfTarget": round(total_reachable / total_target, 4)
        if total_target
        else 0.0,
        "worstRigLimitedFrames": sorted(
            (
                {
                    "frameIndex": row["frameIndex"],
                    "rigLimitedAreaPx": row["rigLimitedAreaPx"],
                    "silhouetteScore": row["silhouetteScore"],
                }
                for row in serialisable
            ),
            key=lambda row: -int(row["rigLimitedAreaPx"]),
        )[:6],
        "frames": serialisable,
    }
    report_path = lane_root / f"{unit}_rig_sufficiency_report.json"
    report_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "lane": str(args.lane),
                "clipRigLimitedFractionOfTarget": summary["clipRigLimitedFractionOfTarget"],
                "clipReachableFractionOfTarget": summary["clipReachableFractionOfTarget"],
                "worstRigLimitedFrames": summary["worstRigLimitedFrames"],
                "report": str(report_path).replace("\\", "/"),
                "gif": str(gif).replace("\\", "/") if gif else None,
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
