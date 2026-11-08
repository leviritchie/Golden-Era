#!/usr/bin/env python3
"""Measure self-intersection in a solved clip, and name the bones responsible.

Why this is needed
------------------
The continuous tracker's correction stage maximises silhouette agreement, and
this lane's config ships ``collision_enabled=False`` / ``anatomy_veto_enabled=False``.
Outline agreement is indifferent to a head pushed inside the chest: those pixels
are already covered by the torso, so burying the head costs the objective nothing
and can even help by removing an outline bump the sprite does not have. Nothing in
the score objects.

That makes self-intersection invisible to every number the lane currently reports,
including the silhouette scores in the deformation report. This audit rebuilds the
same clip with collision scoring switched on -- purely as a measurement, it does
not re-solve -- so the damage can be quantified and attributed.

Reported per frame:
  - penetration for the bind pose, the solved pose, and the solved pose plus
    non-bone offsets when they exist, so pose faults and offset faults are
    separated rather than blamed on each other
  - the bone pairs contributing most penetration, by dominant skin weight, which
    is what turns "the mesh self-intersects" into "the head is inside the torso"

The headline number is the **unsaturated** penetration norm. The cascade's own
``collision_error_from_table`` is reported alongside it but must not be used to
compare two solves: it is ``tanh``-compressed and reads 0.999+ for anything worse
than mild contact, so a lane that removed the head from the torso and a lane that
did not both score ~1.0 and look identical. Measured example: frames 17 and 18 of
the unguarded roc solve differ by 0.10 in the norm and by 0.00009 in the tanh term.

Proof tier: generated artifact measurement.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import torch

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from cascade_clip_pose_tweak import (  # noqa: E402
    _gpu_config_from_saved,
    clip_frame_indices,
    target_frame_dir_from_clip,
)
from def_nonbone_deform import _dominant_bone_per_vertex  # noqa: E402
from literature_polish_common import unit_mesh  # noqa: E402


def collision_audit_config(saved: dict[str, Any], *, sample_count: int, margin: float):
    """The clip's own config with collision measurement forced on.

    ``collision_weight`` is set only because ``validate()`` refuses an enabled
    penalty with zero weight. It has no effect on this audit: nothing here reads
    ``score``, only ``collision_error_from_table`` directly.
    """
    return _gpu_config_from_saved(
        saved,
        overrides={
            "collision_enabled": True,
            "collision_weight": 1.0,
            "collision_sample_count": int(sample_count),
            "collision_margin_body_lengths": float(margin),
            "anatomy_veto_enabled": False,
            "physics_smooth_enabled": False,
            "return_masks": False,
        },
    )


def sample_global_vertices(experiment: Any, table: dict[str, Any]) -> np.ndarray:
    """Global vertex index for each collision sample, in sample order."""
    offsets: list[int] = []
    cursor = 0
    for primitive in experiment.primitives:
        offsets.append(cursor)
        cursor += int(primitive.positions.shape[0])
    chunk_globals: list[int] = []
    for primitive_index, local in table["perPrimitive"]:
        start = offsets[int(primitive_index)]
        chunk_globals.extend(
            (local.detach().cpu().numpy() + start).astype(np.int64).tolist()
        )
    chunk_array = np.asarray(chunk_globals, dtype=np.int64)
    gather = table["gather"].detach().cpu().numpy()
    return chunk_array[gather]


def pair_penetration(
    experiment: Any,
    table: dict[str, Any],
    bones: torch.Tensor,
    *,
    frame_position: int,
    vertex_offsets: torch.Tensor | None,
) -> np.ndarray:
    """Per-pair penetration depth (margin minus distance, clamped at zero)."""
    from gpu_mesh_collision import skinned_indexed_vertices

    with torch.no_grad():
        worlds = experiment._forward_kinematics(
            experiment._bounded_bone_vectors(bones[frame_position].unsqueeze(0)),
            bone_mask=experiment.active_node_mask,
        )
        offset_chunks = None
        if vertex_offsets is not None:
            offset_chunks = []
            cursor = 0
            for primitive in experiment.primitives:
                count = int(primitive.positions.shape[0])
                offset_chunks.append(vertex_offsets[:, cursor : cursor + count, :])
                cursor += count
        chunks = []
        for primitive_index, local in table["perPrimitive"]:
            primitive = experiment.primitives[int(primitive_index)]
            skinned = skinned_indexed_vertices(experiment, worlds, primitive, local)
            if offset_chunks is not None:
                skinned = skinned + offset_chunks[int(primitive_index)].index_select(1, local)
            chunks.append(skinned)
        samples = torch.cat(chunks, dim=1)[:, table["gather"], :][0]
        pairs = table["pairs"]
        delta = samples[pairs[:, 0]] - samples[pairs[:, 1]]
        distance = torch.linalg.vector_norm(delta, dim=-1)
        depth = torch.clamp(float(table["margin"]) - distance, min=0.0)
    return depth.detach().cpu().numpy()


def top_bone_pairs(
    depth: np.ndarray,
    pairs: np.ndarray,
    sample_bone: np.ndarray,
    node_names: Sequence[str],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    totals: dict[tuple[int, int], float] = defaultdict(float)
    counts: dict[tuple[int, int], int] = defaultdict(int)
    hit = np.nonzero(depth > 0.0)[0]
    for index in hit.tolist():
        left = int(sample_bone[int(pairs[index, 0])])
        right = int(sample_bone[int(pairs[index, 1])])
        key = (min(left, right), max(left, right))
        totals[key] += float(depth[index])
        counts[key] += 1
    ranked = sorted(totals.items(), key=lambda item: -item[1])[: int(limit)]
    return [
        {
            "bones": [str(node_names[key[0]]), str(node_names[key[1]])],
            "pairs": int(counts[key]),
            "penetrationSum": round(float(value), 5),
        }
        for key, value in ranked
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", default="h3_roc")
    parser.add_argument("--clip", default="idle_start_move_end")
    parser.add_argument("--lane", required=True)
    parser.add_argument("--tag", default="")
    parser.add_argument("--sample-count", type=int, default=1024)
    parser.add_argument("--margin-body-lengths", type=float, default=0.04)
    parser.add_argument("--top-pairs", type=int, default=5)
    parser.add_argument(
        "--head-bones",
        default=None,
        help=(
            "Comma-separated bones treated as the head/neck chain for attribution. "
            "Defaults to the clip config's anatomy_head_pin_chain_bones."
        ),
    )
    parser.add_argument(
        "--no-head-attribution",
        action="store_true",
        help=(
            "Measure total penetration only and report every head field as null. For "
            "units whose anatomy groups define no head-specific chain (several "
            "Stronghold smartrigs list each group as a full root-to-tip chain, so the "
            "head group also contains the hips). Attributing to such a chain would "
            "measure the whole body while printing a plausible head number."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    unit = str(args.unit)
    clip = str(args.clip)
    tag = f"_{args.tag}" if str(args.tag) else ""
    lane_root = ROOT / "artifacts" / "pose_picker_runs" / unit / clip / str(args.lane)
    clip_path = lane_root / "solve" / "gpu_clip_result.json"
    if not clip_path.is_file():
        raise FileNotFoundError(clip_path)

    from gpu_mesh_collision import collision_error_from_table, penetration_norm_from_table
    from nvdiffrast_local import ensure_local_nvdiffrast
    from roc_gpu_cascade_experiment import GpuCascadeExperiment

    ensure_local_nvdiffrast(required=True)
    payload = json.loads(clip_path.read_text(encoding="utf-8"))
    frames = clip_frame_indices(payload)
    experiment = GpuCascadeExperiment(
        src_glb=unit_mesh(unit, clip).resolve(),
        camera_fit=Path(str(payload["cameraFitPath"])).resolve(),
        target_frame_dir=target_frame_dir_from_clip(payload),
        frame_indices=frames,
        config=collision_audit_config(
            payload["config"],
            sample_count=int(args.sample_count),
            margin=float(args.margin_body_lengths),
        ),
    )
    table = experiment._collision_table
    if table is None:
        raise RuntimeError("collision table did not build; audit cannot measure anything")

    poses = {int(key): value for key, value in payload["poses"].items()}
    bones, root_t, root_r = experiment._initial_pose_tensors(poses)
    bind = torch.zeros_like(bones)

    vertex_count = sum(
        int(primitive.positions.shape[0]) for primitive in experiment.primitives
    )
    offsets_path = lane_root / f"nonbone_deform_offsets{tag}.npz"
    offsets = None
    if offsets_path.is_file():
        offsets = torch.zeros(
            (len(frames), vertex_count, 3), dtype=torch.float32, device=experiment.device
        )
        stored = np.load(offsets_path)
        for key in stored.files:
            position = int(str(key).split("_")[-1])
            offsets[position] = torch.as_tensor(
                np.asarray(stored[key], dtype=np.float32), device=experiment.device
            )

    with torch.no_grad():
        bind_error = penetration_norm_from_table(
            experiment, table, experiment._bounded_bone_vectors(bind)
        )
        solved_error = penetration_norm_from_table(
            experiment, table, experiment._bounded_bone_vectors(bones)
        )
        offset_error = (
            None
            if offsets is None
            else penetration_norm_from_table(
                experiment,
                table,
                experiment._bounded_bone_vectors(bones),
                vertex_offsets=offsets,
            )
        )
        saturated_error = collision_error_from_table(
            experiment, table, experiment._bounded_bone_vectors(bones)
        )

    attribute_head = not bool(args.no_head_attribution)
    if args.head_bones is not None:
        head_bones = {part.strip() for part in str(args.head_bones).split(",") if part.strip()}
    else:
        head_bones = {
            str(name)
            for name in (payload["config"].get("anatomyHeadPinChainBones") or [])
        }
    if attribute_head and not head_bones:
        raise ValueError(
            "no head chain to attribute against: the clip config has no "
            "anatomyHeadPinChainBones, so pass --head-bones explicitly, or pass "
            "--no-head-attribution to report head fields as null, rather than "
            "silently reporting zero head penetration"
        )
    if not attribute_head and head_bones:
        raise ValueError(
            "--no-head-attribution and --head-bones contradict each other; pass one"
        )

    dominant = _dominant_bone_per_vertex(experiment)
    sample_vertices = sample_global_vertices(experiment, table)
    sample_bone = dominant[sample_vertices]
    pairs = table["pairs"].detach().cpu().numpy()

    rows: list[dict[str, Any]] = []
    for position, frame_index in enumerate(frames):
        depth = pair_penetration(
            experiment,
            table,
            bones,
            frame_position=position,
            vertex_offsets=None,
        )
        ranked = top_bone_pairs(
            depth, pairs, sample_bone, experiment.node_names, limit=int(args.top_pairs)
        )
        head_penetration = (
            sum(
                float(entry["penetrationSum"])
                for entry in ranked
                if head_bones & set(entry["bones"])
            )
            if attribute_head
            else None
        )
        row = {
            "frameIndex": int(frame_index),
            "framePosition": int(position),
            "bindPenetration": round(float(bind_error[position].item()), 5),
            "solvedPenetration": round(float(solved_error[position].item()), 5),
            "offsetPenetration": None
            if offset_error is None
            else round(float(offset_error[position].item()), 5),
            "solvedSaturatedTanh": round(float(saturated_error[position].item()), 5),
            "collidingPairs": int((depth > 0.0).sum()),
            "headChainPenetrationSum": None
            if head_penetration is None
            else round(head_penetration, 5),
            "topBonePairs": ranked,
        }
        rows.append(row)
        offset_text = (
            "" if row["offsetPenetration"] is None else f" offset={row['offsetPenetration']:.4f}"
        )
        worst = ranked[0] if ranked else None
        worst_text = "" if worst is None else f" worst={worst['bones'][0]}~{worst['bones'][1]}"
        print(
            f"[pen ] frame {frame_index:>3} bind={row['bindPenetration']:.4f} "
            f"solved={row['solvedPenetration']:.4f}{offset_text} "
            f"pairs={row['collidingPairs']:>4} "
            f"head={'  n/a ' if head_penetration is None else f'{head_penetration:6.3f}'}"
            f"{worst_text}",
            flush=True,
        )

    summary = {
        "proof": "generated-artifact",
        "unit": unit,
        "clip": clip,
        "lane": str(args.lane),
        "note": (
            "measurement only; the lane solved with collision_enabled=False so "
            "these penetrations were never penalised during the fit"
        ),
        "metric": "unsaturated_penetration_norm_in_margin_units",
        "headChainBones": sorted(head_bones) if attribute_head else None,
        "headAttribution": "measured"
        if attribute_head
        else "disabled: no head-specific chain for this unit, so head fields are null",
        "collisionSampleCount": int(args.sample_count),
        "collisionMarginBodyLengths": float(args.margin_body_lengths),
        "meanBindPenetration": round(float(bind_error.mean().item()), 5),
        "meanSolvedPenetration": round(float(solved_error.mean().item()), 5),
        "maxSolvedPenetration": round(float(solved_error.max().item()), 5),
        "meanOffsetPenetration": None
        if offset_error is None
        else round(float(offset_error.mean().item()), 5),
        "meanHeadChainPenetrationSum": round(
            float(np.mean([row["headChainPenetrationSum"] for row in rows])), 5
        )
        if attribute_head
        else None,
        "framesWithHeadChainPenetration": int(
            sum(1 for row in rows if float(row["headChainPenetrationSum"]) > 0.0)
        )
        if attribute_head
        else None,
        "worstFrames": sorted(
            ({"frameIndex": row["frameIndex"], "solvedPenetration": row["solvedPenetration"]}
             for row in rows),
            key=lambda row: -float(row["solvedPenetration"]),
        )[:6],
        "frames": rows,
    }
    report_path = lane_root / f"{unit}_self_intersection_audit{tag}.json"
    report_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "meanBindPenetration": summary["meanBindPenetration"],
                "meanSolvedPenetration": summary["meanSolvedPenetration"],
                "maxSolvedPenetration": summary["maxSolvedPenetration"],
                "meanOffsetPenetration": summary["meanOffsetPenetration"],
                "meanHeadChainPenetrationSum": summary["meanHeadChainPenetrationSum"],
                "framesWithHeadChainPenetration": summary["framesWithHeadChainPenetration"],
                "worstFrames": summary["worstFrames"],
                "report": str(report_path).replace("\\", "/"),
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
