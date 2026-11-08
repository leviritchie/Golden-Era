#!/usr/bin/env python3
"""Create the surface motion a rotate-only skeleton cannot produce.

Why this exists
---------------
A rotation moves surface around; it does not create surface. On h3_roc
``idle_start_move_end`` the wing-spread frames need 17-21% more silhouette area
than the mesh can project in *any* pose, so those frames are outside the reach of
every rotate-only rig by arithmetic, not by optimiser weakness. Adding bones does
not help: more wing bones would redistribute the existing surface, not enlarge
it. The only channel that can close an area deficit is one that moves vertices
off the skinned result.

Which is dangerous, and has already failed once here. ``gpu_post_pose_warp_repair``
v1 was invalidated for exactly this: it flagged ordinary skinning strain as
"warp", then scored free per-group vertex slides against a *different* objective
than the fit. The number improved while 3D coherence broke.

Three structural choices keep this lane out of that hole:

1. **Trigger is a measured rig limit, not a low score.** Regions come from
   ``def_rig_sufficiency_probe``, which only flags area that no rig degree of
   freedom at its limit can reach with the local surface. A frame that merely
   scores badly gets nothing.
2. **Smooth by construction, not smooth by penalty.** Offsets are not free per
   vertex. Each flagged region contributes four numbers -- a displacement and a
   radial expansion -- spread over the surface by a Gaussian falloff in bind
   space, restricted to the bone chain that owns the region. Neighbouring
   vertices therefore move almost identically and cannot be pulled apart. This
   matters especially here because this lane's config has
   ``collision_enabled=False`` and ``anatomy_veto_enabled=False``, so the score
   itself contains no mesh-integrity term to lean on.
3. **Same objective as the fit, and fail-closed.** Candidates are scored with
   ``experiment.evaluate`` on the config loaded from the clip payload. Offsets
   are kept only when that score improves *and* the offsets' own edge strain and
   magnitude stay inside their bounds. Otherwise the frame keeps zero offsets.

Strain here is deliberately not ``gpu_mesh_strain``. That table holds only
mixed-influence edges -- edges spanning two bones -- because it was built to
catch LBS blend stretch. Offsets can rip an interior edge that a single bone
owns, which that table never sees. So this measures every edge, and measures the
offsets' *own* contribution: posed-with-offset length against posed-without,
which isolates the damage the offsets did rather than re-reporting the stretch
the pose already had.

Proof tier: generated artifact. Nothing here is exported or OE runtime proven.
Delivery note: offsets are applied post-skinning/pre-root, whereas a Unity blend
shape deforms in bind space before skinning. Shipping these needs that change of
basis per vertex; it is not done here.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, replace
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

from def_rig_sufficiency_probe import (  # noqa: E402
    RigSufficiencyConfig,
    _blob_probe_points,
    _local_patch_indices,
)
from literature_polish_common import (  # noqa: E402
    assert_write_path,
    load_polish_experiment,
    unit_mesh,
)
from preview_timing import PREVIEW_GIF_FRAME_MS  # noqa: E402


@dataclass(frozen=True)
class NonBoneDeformConfig:
    # Falloff width of a region's field, in body lengths. Wide enough that
    # neighbouring vertices move together; narrow enough to stay local.
    field_sigma_body_lengths: float = 0.055
    # Mesh samples defining the region's patch.
    patch_samples: int = 64
    # Only vertices owned by the region's bone chain may move, so growing a wing
    # cannot drag the torso along with it.
    chain_ancestor_levels: int = 2
    # Descent
    step_schedule: tuple[float, ...] = (1.0, 0.5, 0.25)
    translate_step_body_lengths: float = 0.008
    expand_step_body_lengths: float = 0.008
    max_accepted_steps: int = 60
    min_score_gain: float = 2e-4
    # Fail-closed bounds on what the offsets may do
    max_edge_strain: float = 0.12
    edge_strain_tolerance: float = 0.02
    max_offset_body_lengths: float = 0.12
    # Regions considered per frame, largest rig-limited first.
    max_regions_per_frame: int = 4
    min_region_area_px: int = 40


@dataclass(frozen=True)
class DeformRegion:
    frame_position: int
    area_px: int
    vertex_weights: torch.Tensor  # [V] smooth field, zero outside the chain
    radial: torch.Tensor  # [V, 3] unit outward direction from the patch centroid


def _body_length(bind_positions: torch.Tensor) -> float:
    from gpu_mesh_collision import bind_extent_length

    return float(bind_extent_length(bind_positions.detach().cpu().numpy()))


def _concat_bind_positions(experiment: Any) -> torch.Tensor:
    return torch.cat([primitive.positions for primitive in experiment.primitives], dim=0)


def _dominant_bone_per_vertex(experiment: Any) -> np.ndarray:
    """Node index of the bone holding the largest skin weight for each vertex."""
    dominant: list[np.ndarray] = []
    for primitive in experiment.primitives:
        if primitive.normalized_weights is None or primitive.joints is None:
            dominant.append(
                np.full((int(primitive.positions.shape[0]),), int(primitive.node), dtype=np.int64)
            )
            continue
        weights = primitive.normalized_weights.detach().cpu().numpy()
        slots = primitive.joints.detach().cpu().numpy()
        skin_to_node = primitive.skin_joints.detach().cpu().numpy().reshape(-1)
        best_slot = slots[np.arange(slots.shape[0]), weights.argmax(axis=1)]
        dominant.append(skin_to_node[best_slot].astype(np.int64))
    return np.concatenate(dominant, axis=0)


def _chain_node_set(experiment: Any, node: int, *, ancestor_levels: int) -> set[int]:
    """The region's bone, its descendants, and a few ancestors."""
    nodes = experiment.asset.nodes
    allowed: set[int] = set()
    stack = [int(node)]
    while stack:
        current = stack.pop()
        if current in allowed:
            continue
        allowed.add(current)
        for index, candidate in enumerate(nodes):
            parent = candidate.parent
            if parent is not None and int(parent) == current:
                stack.append(int(index))
    current_parent = nodes[int(node)].parent
    for _ in range(int(ancestor_levels)):
        if current_parent is None:
            break
        allowed.add(int(current_parent))
        current_parent = nodes[int(current_parent)].parent
    return allowed


def _full_edge_table(experiment: Any) -> torch.Tensor:
    """Unique undirected edges over the whole mesh, offset into concatenated order."""
    edges: list[np.ndarray] = []
    cursor = 0
    for primitive in experiment.primitives:
        indices = primitive.indices.detach().cpu().numpy().reshape(-1, 3)
        triples = np.concatenate(
            (indices[:, [0, 1]], indices[:, [1, 2]], indices[:, [2, 0]]), axis=0
        )
        triples = np.sort(triples, axis=1) + cursor
        edges.append(np.unique(triples, axis=0))
        cursor += int(primitive.positions.shape[0])
    stacked = np.unique(np.concatenate(edges, axis=0), axis=0)
    return torch.as_tensor(stacked, dtype=torch.long, device=experiment.device)


def offset_edge_strain(
    posed: torch.Tensor,
    offsets: torch.Tensor,
    edges: torch.Tensor,
    *,
    tolerance: float,
) -> torch.Tensor:
    """RMS edge stretch caused by the offsets alone, per batch entry.

    Compares posed-with-offset edge length against posed-without. Measuring
    against the *bind* rest length instead would re-report stretch the pose
    already had and blame the offsets for it.
    """
    rest = torch.linalg.vector_norm(
        posed[:, edges[:, 0], :] - posed[:, edges[:, 1], :], dim=-1
    ).clamp_min(1e-9)
    deformed = posed + offsets
    length = torch.linalg.vector_norm(
        deformed[:, edges[:, 0], :] - deformed[:, edges[:, 1], :], dim=-1
    )
    excess = torch.clamp((length / rest - 1.0).abs() - float(tolerance), min=0.0)
    return torch.sqrt((excess * excess).mean(dim=-1))


def posed_vertices(
    experiment: Any,
    bones: torch.Tensor,
    *,
    frame_position: int,
) -> torch.Tensor:
    """Skinned vertex positions in the space where offsets are added (pre-root)."""
    with torch.no_grad():
        worlds = experiment._forward_kinematics(
            experiment._bounded_bone_vectors(bones[frame_position].unsqueeze(0)),
            bone_mask=experiment.active_node_mask,
        )
        parts = [
            experiment._skinned_vertices(worlds, primitive)
            for primitive in experiment.primitives
        ]
    return torch.cat(parts, dim=1)


def project_vertices_xy(
    experiment: Any,
    posed: torch.Tensor,
    root_translation: torch.Tensor,
    root_rotation: torch.Tensor,
) -> torch.Tensor:
    """Per-vertex pixel coordinates, [B, V, 2].

    ``render_points`` cannot be used for this. It returns *surface sample* points
    built from fixed triangle barycentrics, so its indices do not address
    vertices -- indexing per-vertex skin weights with a sample index silently
    reads the wrong vertex, or runs off the end of the array.
    """
    with torch.no_grad():
        points = experiment._root_transform(posed, root_translation, root_rotation)
        return torch.stack(
            (
                torch.matmul(points, experiment.camera_right) * experiment.px_per_world[0]
                + experiment.camera_offset[0],
                torch.matmul(points, experiment.camera_down) * experiment.px_per_world[1]
                + experiment.camera_offset[1],
            ),
            dim=-1,
        )


def build_regions(
    experiment: Any,
    bones: torch.Tensor,
    root_translation: torch.Tensor,
    root_rotation: torch.Tensor,
    *,
    frame_position: int,
    frame_report: dict[str, Any],
    predicted: np.ndarray,
    target: np.ndarray,
    posed: torch.Tensor,
    bind_positions: torch.Tensor,
    dominant: np.ndarray,
    body_length: float,
    config: NonBoneDeformConfig,
    probe_config: RigSufficiencyConfig,
) -> list[DeformRegion]:
    """One smooth field per rig-limited region on this frame."""
    if int(frame_report["rigLimitedAreaPx"]) <= 0:
        return []

    predicted_bin = (predicted >= probe_config.mask_threshold).astype(np.uint8)
    target_bin = (target >= probe_config.mask_threshold).astype(np.uint8)
    uncovered = ((target_bin == 1) & (predicted_bin == 0)).astype(np.uint8)
    count, labelled, stats, _ = cv2.connectedComponentsWithStats(uncovered, 8)

    vertex_xy = (
        project_vertices_xy(
            experiment,
            posed,
            root_translation[frame_position].unsqueeze(0),
            root_rotation[frame_position].unsqueeze(0),
        )[0]
        .detach()
        .cpu()
        .numpy()
        .astype(np.float32)
    )

    # Rank candidate blobs by area, keeping only ones the probe called unreachable.
    unreachable_centroids = {
        (round(float(blob["centroid"][0]), 1), round(float(blob["centroid"][1]), 1))
        for blob in frame_report["blobs"]
        if not bool(blob["reachable"])
    }
    candidates: list[tuple[int, int]] = []
    for index in range(1, int(count)):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < int(config.min_region_area_px):
            continue
        moments = cv2.moments((labelled == index).astype(np.uint8))
        if moments["m00"] <= 0:
            continue
        centroid = (
            round(moments["m10"] / moments["m00"], 1),
            round(moments["m01"] / moments["m00"], 1),
        )
        if centroid not in unreachable_centroids:
            continue
        candidates.append((area, index))
    candidates.sort(reverse=True)

    sigma = float(config.field_sigma_body_lengths) * body_length
    regions: list[DeformRegion] = []
    for area, index in candidates[: int(config.max_regions_per_frame)]:
        blob_mask = (labelled == index).astype(np.uint8)
        probe_xy = _blob_probe_points(blob_mask, limit=int(probe_config.blob_probe_points))
        patch = _local_patch_indices(
            vertex_xy, probe_xy, patch_samples=int(config.patch_samples)
        )
        patch_nodes = np.unique(dominant[patch])
        owner = int(np.bincount(dominant[patch]).argmax())
        allowed = _chain_node_set(
            experiment, owner, ancestor_levels=int(config.chain_ancestor_levels)
        )
        allowed.update(int(node) for node in patch_nodes)
        chain_mask = torch.as_tensor(
            np.isin(dominant, np.asarray(sorted(allowed), dtype=np.int64)),
            dtype=torch.float32,
            device=experiment.device,
        )

        patch_centre = bind_positions[torch.as_tensor(patch, device=experiment.device)].mean(dim=0)
        distance = torch.linalg.vector_norm(bind_positions - patch_centre.reshape(1, 3), dim=-1)
        weights = torch.exp(-0.5 * (distance / sigma) ** 2) * chain_mask
        peak = float(weights.max().item())
        if peak <= 1e-6:
            continue
        weights = weights / peak

        frame_posed = posed[0]
        posed_centre = (frame_posed * weights.reshape(-1, 1)).sum(
            dim=0
        ) / weights.sum().clamp_min(1e-9)
        radial = frame_posed - posed_centre.reshape(1, 3)
        radial = radial / torch.linalg.vector_norm(radial, dim=-1, keepdim=True).clamp_min(1e-9)
        regions.append(
            DeformRegion(
                frame_position=int(frame_position),
                area_px=int(area),
                vertex_weights=weights,
                radial=radial,
            )
        )
    return regions


def offsets_from_params(
    regions: Sequence[DeformRegion],
    params: torch.Tensor,
    *,
    body_length: float,
) -> torch.Tensor:
    """[B, V, 3] offsets from [B, R, 4] parameters (translate xyz, radial expand)."""
    batch = int(params.shape[0])
    vertex_count = int(regions[0].vertex_weights.shape[0])
    offsets = torch.zeros(
        (batch, vertex_count, 3), dtype=torch.float32, device=params.device
    )
    for region_index, region in enumerate(regions):
        weight = region.vertex_weights.reshape(1, -1, 1)
        translate = params[:, region_index, 0:3].reshape(batch, 1, 3) * body_length
        expand = params[:, region_index, 3].reshape(batch, 1, 1) * body_length
        offsets = offsets + weight * (translate + expand * region.radial.unsqueeze(0))
    return offsets


def score_params(
    experiment: Any,
    bones: torch.Tensor,
    root_translation: torch.Tensor,
    root_rotation: torch.Tensor,
    regions: Sequence[DeformRegion],
    params: torch.Tensor,
    *,
    frame_position: int,
    posed: torch.Tensor,
    edges: torch.Tensor,
    body_length: float,
    config: NonBoneDeformConfig,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Fit-objective score plus the two fail-closed measurements, per candidate."""
    batch = int(params.shape[0])
    offsets = offsets_from_params(regions, params, body_length=body_length)
    frame_index = torch.full(
        (batch,), int(frame_position), dtype=torch.long, device=experiment.device
    )
    with torch.no_grad():
        packed = experiment.evaluate(
            experiment._bounded_bone_vectors(
                bones[frame_position].unsqueeze(0).expand(batch, -1, -1)
            ),
            root_translation[frame_position].unsqueeze(0).expand(batch, -1),
            root_rotation[frame_position].unsqueeze(0).expand(batch, -1),
            bone_mask=experiment.active_node_mask,
            frame_indices=frame_index,
            vertex_offsets=offsets,
        )
        strain = offset_edge_strain(
            posed.expand(batch, -1, -1),
            offsets,
            edges,
            tolerance=float(config.edge_strain_tolerance),
        )
        magnitude = torch.linalg.vector_norm(offsets, dim=-1).amax(dim=-1) / body_length
    return packed["score"].detach(), strain, magnitude


def _param_trials(params: torch.Tensor, step: float) -> torch.Tensor:
    """Current parameters plus a one-at-a-time +/- step on every parameter."""
    region_count, param_count = params.shape
    trials = [params.reshape(1, region_count, param_count)]
    for region_index in range(region_count):
        for param_index in range(param_count):
            for sign in (1.0, -1.0):
                trial = params.clone()
                trial[region_index, param_index] += sign * float(step)
                trials.append(trial.reshape(1, region_count, param_count))
    return torch.cat(trials, dim=0)


def solve_frame_offsets(
    experiment: Any,
    bones: torch.Tensor,
    root_translation: torch.Tensor,
    root_rotation: torch.Tensor,
    regions: Sequence[DeformRegion],
    *,
    frame_position: int,
    posed: torch.Tensor,
    edges: torch.Tensor,
    body_length: float,
    config: NonBoneDeformConfig,
) -> dict[str, Any]:
    """Steepest descent on the region parameters under the fit objective."""
    params = torch.zeros(
        (len(regions), 4), dtype=torch.float32, device=experiment.device
    )
    baseline, _, _ = score_params(
        experiment,
        bones,
        root_translation,
        root_rotation,
        regions,
        params.unsqueeze(0),
        frame_position=frame_position,
        posed=posed,
        edges=edges,
        body_length=body_length,
        config=config,
    )
    baseline_score = float(baseline[0].item())
    best_score = baseline_score
    accepted = 0
    rejected_strain = 0
    rejected_magnitude = 0

    for level in config.step_schedule:
        translate_step = float(level) * float(config.translate_step_body_lengths)
        while accepted < int(config.max_accepted_steps):
            trials = _param_trials(params, translate_step)
            scores, strain, magnitude = score_params(
                experiment,
                bones,
                root_translation,
                root_rotation,
                regions,
                trials,
                frame_position=frame_position,
                posed=posed,
                edges=edges,
                body_length=body_length,
                config=config,
            )
            legal = (strain <= float(config.max_edge_strain)) & (
                magnitude <= float(config.max_offset_body_lengths)
            )
            rejected_strain += int((strain > float(config.max_edge_strain)).sum().item())
            rejected_magnitude += int(
                (magnitude > float(config.max_offset_body_lengths)).sum().item()
            )
            masked = scores.clone()
            masked[~legal] = -float("inf")
            candidate = int(masked.argmax().item())
            if candidate == 0 or not bool(legal[candidate].item()):
                break
            gain = float(masked[candidate].item()) - best_score
            if gain < float(config.min_score_gain):
                break
            params = trials[candidate].clone()
            best_score = float(masked[candidate].item())
            accepted += 1

    final, final_strain, final_magnitude = score_params(
        experiment,
        bones,
        root_translation,
        root_rotation,
        regions,
        params.unsqueeze(0),
        frame_position=frame_position,
        posed=posed,
        edges=edges,
        body_length=body_length,
        config=config,
    )
    improved = float(final[0].item()) - baseline_score
    keep = improved >= float(config.min_score_gain)
    if not keep:
        params = torch.zeros_like(params)
    return {
        "framePosition": int(frame_position),
        "regions": len(regions),
        "regionAreaPx": [int(region.area_px) for region in regions],
        "baselineScore": round(baseline_score, 4),
        "offsetScore": round(float(final[0].item()), 4),
        "scoreGain": round(improved, 4),
        "kept": bool(keep),
        "acceptedSteps": int(accepted),
        "edgeStrain": round(float(final_strain[0].item()), 4),
        "maxOffsetBodyLengths": round(float(final_magnitude[0].item()), 4),
        "trialsRejectedStrain": int(rejected_strain),
        "trialsRejectedMagnitude": int(rejected_magnitude),
        "params": [[round(float(value), 5) for value in row] for row in params.tolist()],
        "_params": params,
    }


def compose_compare_gif(
    experiment: Any,
    bones: torch.Tensor,
    root_translation: torch.Tensor,
    root_rotation: torch.Tensor,
    *,
    frame_indices: Sequence[int],
    offsets_by_frame: dict[int, torch.Tensor],
    frame_dir: Path,
    out: Path,
    upscale: int = 3,
) -> Path:
    """sprite | bones only | bones + non-bone offsets."""
    panels: list[Image.Image] = []
    for position, frame_index in enumerate(frame_indices):
        frame_batch = torch.full(
            (1,), int(position), dtype=torch.long, device=experiment.device
        )
        bounded = experiment._bounded_bone_vectors(bones[position].unsqueeze(0))
        with torch.no_grad():
            plain = experiment.evaluate(
                bounded,
                root_translation[position].unsqueeze(0),
                root_rotation[position].unsqueeze(0),
                bone_mask=experiment.active_node_mask,
                frame_indices=frame_batch,
            )
            offsets = offsets_by_frame.get(int(position))
            deformed = (
                plain
                if offsets is None
                else experiment.evaluate(
                    bounded,
                    root_translation[position].unsqueeze(0),
                    root_rotation[position].unsqueeze(0),
                    bone_mask=experiment.active_node_mask,
                    frame_indices=frame_batch,
                    vertex_offsets=offsets,
                )
            )
        target = plain["targetMasks"][0].detach().cpu().numpy()
        height, width = target.shape
        sprite = (
            Image.open(frame_dir / f"{int(frame_index):02d}.png")
            .convert("RGB")
            .resize((width, height), Image.Resampling.LANCZOS)
        )

        def _panel(mask_source: dict[str, Any], caption: str) -> Image.Image:
            mask = mask_source["predictedMasks"][0].detach().cpu().numpy()
            canvas = np.zeros((height, width, 3), dtype=np.float32)
            canvas[..., 0] = target * 90.0
            canvas[..., 1] = target * 30.0
            canvas[..., 2] = target * 30.0
            lit = mask > 0.5
            canvas[lit] = np.array([225.0, 225.0, 235.0])
            both = lit & (target > 0.5)
            canvas[both] = np.array([120.0, 210.0, 130.0])
            image = Image.fromarray(canvas.astype(np.uint8)).resize(
                (width * upscale, height * upscale), Image.Resampling.NEAREST
            )
            ImageDraw.Draw(image).text((4, 4), caption, fill=(240, 240, 240))
            return image

        sprite_panel = sprite.resize(
            (width * upscale, height * upscale), Image.Resampling.NEAREST
        )
        ImageDraw.Draw(sprite_panel).text((4, 4), f"f{int(frame_index):02d} sprite", fill=(240, 240, 240))
        bone_panel = _panel(plain, f"bones {float(plain['score'][0].item()):.3f}")
        deform_panel = _panel(
            deformed,
            ("bones+offsets " if offsets is not None else "no offsets ")
            + f"{float(deformed['score'][0].item()):.3f}",
        )
        row = Image.new(
            "RGB",
            (sprite_panel.width * 3, sprite_panel.height),
            (10, 10, 14),
        )
        row.paste(sprite_panel, (0, 0))
        row.paste(bone_panel, (sprite_panel.width, 0))
        row.paste(deform_panel, (sprite_panel.width * 2, 0))
        panels.append(row)
    panels[0].save(
        out, save_all=True, append_images=panels[1:], duration=PREVIEW_GIF_FRAME_MS, loop=0
    )
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", default="h3_roc")
    parser.add_argument("--clip", default="idle_start_move_end")
    parser.add_argument("--lane", required=True)
    parser.add_argument("--max-regions", type=int, default=None)
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--max-edge-strain", type=float, default=None)
    parser.add_argument("--max-offset-body-lengths", type=float, default=None)
    parser.add_argument(
        "--tag",
        default="",
        help="Suffix for output artifacts, so a cap-sensitivity run does not overwrite the baseline.",
    )
    parser.add_argument("--skip-gif", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    unit = str(args.unit)
    clip = str(args.clip)
    lane_root = ROOT / "artifacts" / "pose_picker_runs" / unit / clip / str(args.lane)
    clip_path = lane_root / "solve" / "gpu_clip_result.json"
    probe_path = lane_root / f"{unit}_rig_sufficiency_report.json"
    for path in (clip_path, probe_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    config = NonBoneDeformConfig()
    if args.max_regions is not None:
        config = replace(config, max_regions_per_frame=int(args.max_regions))
    if args.max_steps is not None:
        config = replace(config, max_accepted_steps=int(args.max_steps))
    if args.max_edge_strain is not None:
        config = replace(config, max_edge_strain=float(args.max_edge_strain))
    if args.max_offset_body_lengths is not None:
        config = replace(
            config, max_offset_body_lengths=float(args.max_offset_body_lengths)
        )
    tag = f"_{args.tag}" if str(args.tag) else ""

    payload = json.loads(clip_path.read_text(encoding="utf-8"))
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    probe_config = RigSufficiencyConfig(**probe["config"])
    experiment, bones, root_t, root_r = load_polish_experiment(
        payload=payload, mesh=unit_mesh(unit, clip)
    )
    frame_indices = list(experiment.frame_indices)
    bind_positions = _concat_bind_positions(experiment)
    body_length = _body_length(bind_positions)
    dominant = _dominant_bone_per_vertex(experiment)
    edges = _full_edge_table(experiment)
    print(
        f"non-bone deform: verts={int(bind_positions.shape[0])} edges={int(edges.shape[0])} "
        f"bodyLength={body_length:.4f} sigma={config.field_sigma_body_lengths:.3f}bl "
        f"strainCap={config.max_edge_strain:.3f} offsetCap={config.max_offset_body_lengths:.3f}bl",
        flush=True,
    )

    with torch.no_grad():
        packed = experiment.evaluate(
            experiment._bounded_bone_vectors(bones),
            root_t,
            root_r,
            bone_mask=experiment.active_node_mask,
        )
    predicted = packed["predictedMasks"].detach().cpu().numpy()
    target = packed["targetMasks"].detach().cpu().numpy()

    started = time.time()
    frame_reports: list[dict[str, Any]] = []
    offsets_by_frame: dict[int, torch.Tensor] = {}
    for position, frame_index in enumerate(frame_indices):
        frame_report = next(
            row for row in probe["frames"] if int(row["framePosition"]) == int(position)
        )
        posed = posed_vertices(experiment, bones, frame_position=position)
        regions = build_regions(
            experiment,
            bones,
            root_t,
            root_r,
            frame_position=position,
            frame_report=frame_report,
            predicted=predicted[position],
            target=target[position],
            posed=posed,
            bind_positions=bind_positions,
            dominant=dominant,
            body_length=body_length,
            config=config,
            probe_config=probe_config,
        )
        if not regions:
            print(
                f"[dfrm] frame {frame_index:>3} no rig-limited region above "
                f"{config.min_region_area_px}px -- skipped",
                flush=True,
            )
            continue
        result = solve_frame_offsets(
            experiment,
            bones,
            root_t,
            root_r,
            regions,
            frame_position=position,
            posed=posed,
            edges=edges,
            body_length=body_length,
            config=config,
        )
        result["frameIndex"] = int(frame_index)
        if bool(result["kept"]):
            offsets_by_frame[int(position)] = offsets_from_params(
                regions, result["_params"].unsqueeze(0), body_length=body_length
            )
        params = result.pop("_params")
        frame_reports.append(result)
        print(
            f"[dfrm] frame {frame_index:>3} regions={result['regions']} "
            f"score {result['baselineScore']:.4f} -> {result['offsetScore']:.4f} "
            f"gain {result['scoreGain']:+.4f} kept={result['kept']} "
            f"steps={result['acceptedSteps']} strain={result['edgeStrain']:.4f} "
            f"maxOffset={result['maxOffsetBodyLengths']:.4f}bl "
            f"vetoStrain={result['trialsRejectedStrain']} "
            f"vetoMag={result['trialsRejectedMagnitude']}",
            flush=True,
        )
        del params

    gif = None
    if not bool(args.skip_gif) and offsets_by_frame:
        gif = compose_compare_gif(
            experiment,
            bones,
            root_t,
            root_r,
            frame_indices=frame_indices,
            offsets_by_frame=offsets_by_frame,
            frame_dir=Path(str(payload["targetPaths"][0])).parent,
            out=assert_write_path(lane_root) / f"nonbone_deform_compare{tag}.gif",
        )

    kept = [row for row in frame_reports if bool(row["kept"])]
    summary = {
        "proof": "generated-artifact",
        "unit": unit,
        "clip": clip,
        "lane": str(args.lane),
        "trigger": "def_rig_sufficiency_probe rig-limited regions only",
        "objective": "same experiment.evaluate score as the clip fit",
        "offsetSpace": "post_skinning_pre_root",
        "deliveryConversionDone": False,
        "config": {
            key: (list(value) if isinstance(value, tuple) else value)
            for key, value in config.__dict__.items()
        },
        "framesConsidered": len(frame_reports),
        "framesKept": len(kept),
        "meanScoreGainOnKept": round(
            float(np.mean([row["scoreGain"] for row in kept])), 4
        )
        if kept
        else 0.0,
        "maxEdgeStrainOnKept": round(
            float(max(row["edgeStrain"] for row in kept)), 4
        )
        if kept
        else 0.0,
        "solveSec": round(time.time() - started, 2),
        "frames": frame_reports,
    }
    report_path = lane_root / f"{unit}_nonbone_deform_report{tag}.json"
    report_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if offsets_by_frame:
        np.savez_compressed(
            lane_root / f"nonbone_deform_offsets{tag}.npz",
            **{
                f"frame_{int(position):02d}": tensor[0].detach().cpu().numpy()
                for position, tensor in offsets_by_frame.items()
            },
        )

    print(
        json.dumps(
            {
                "ok": True,
                "framesConsidered": summary["framesConsidered"],
                "framesKept": summary["framesKept"],
                "meanScoreGainOnKept": summary["meanScoreGainOnKept"],
                "maxEdgeStrainOnKept": summary["maxEdgeStrainOnKept"],
                "solveSec": summary["solveSec"],
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
