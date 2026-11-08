"""Idle-anchored macro init led by motion-importance ranking.

Default fused-push ranking is ``error_leverage`` (occupancy leftover × screen
joint reach). ``gradient_magnitude`` remains for compare scripts. Idle prefix
frames are snapshotted and restored so the idle pose stays fixed while transit
frames explore.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


def _restore_idle_prefix(
    bone_vectors,
    root_translation,
    root_rotation,
    *,
    idle_snap_bones,
    idle_snap_root_t,
    idle_snap_root_r,
    prefix_count: int,
) -> None:
    if int(prefix_count) <= 0:
        return
    bone_vectors.data[:prefix_count] = idle_snap_bones
    root_translation.data[:prefix_count] = idle_snap_root_t
    root_rotation.data[:prefix_count] = idle_snap_root_r


def _top_gradient_chains(
    ranked_bones: Sequence[int],
    parents: Sequence[int | None],
    *,
    max_chains: int = 2,
) -> list[tuple[int, ...]]:
    ordered = [int(index) for index in ranked_bones]
    if len(ordered) < 2:
        return []
    chains: list[tuple[int, ...]] = []
    used: set[int] = set()
    for distal in ordered:
        if distal in used:
            continue
        parent = parents[distal]
        parent_index = None if parent is None else int(parent)
        if parent_index is not None and parent_index in ordered and parent_index not in used:
            chains.append((parent_index, distal))
            used.add(parent_index)
            used.add(distal)
        else:
            chains.append((distal,))
            used.add(distal)
        if len(chains) >= int(max_chains):
            break
    return chains


IDLE_FUSED_IMPORTANCE_MODES = ("error_leverage", "gradient_magnitude")


def importance_scores_for_mode(
    experiment,
    mode: str,
    bone_indices: Sequence[int],
    bone_vectors,
    root_translation,
    root_rotation,
    *,
    stage_mask,
    evaluation_count: list[int] | None,
) -> dict[int, float]:
    mode = str(mode)
    bones = tuple(int(index) for index in bone_indices)
    if mode == "gradient_magnitude":
        scores = experiment._bone_gradient_magnitude_scores(
            bones,
            bone_vectors,
            root_translation,
            root_rotation,
            stage_mask=stage_mask,
        )
        if evaluation_count is not None:
            evaluation_count[0] += 1
        return dict(scores)
    if mode == "error_leverage":
        from cascade_bone_order import error_leverage_scores

        if evaluation_count is not None:
            evaluation_count[0] += 1
        error_scores = experiment._bone_error_driven_scores(
            bones, bone_vectors, root_translation, root_rotation
        )
        leverage_scores = experiment._bone_screen_leverage_scores(
            bones, bone_vectors, root_translation, root_rotation
        )
        return error_leverage_scores(error_scores, leverage_scores)
    raise ValueError(
        "idle_fused_importance_mode must be one of: "
        + ", ".join(IDLE_FUSED_IMPORTANCE_MODES)
    )


def transit_worst_frame_positions(
    scores,
    *,
    prefix_count: int,
    keep_count: int,
):
    """Lowest-scoring transit frames; idle prefix is never selected."""
    import torch

    flat = scores.detach().reshape(-1)
    prefix = max(0, int(prefix_count))
    if prefix >= int(flat.numel()):
        keep = min(int(flat.numel()), int(keep_count))
        return torch.topk(flat, keep, largest=False).indices
    transit = flat[prefix:]
    keep = min(int(transit.numel()), int(keep_count))
    if keep < 1:
        raise ValueError("transit_worst_frame_positions needs at least one transit frame")
    local = torch.topk(transit, keep, largest=False).indices
    return local + prefix


def format_importance_log(
    experiment,
    scores: Mapping[int, float],
    *,
    top_n: int = 6,
) -> str:
    ranked = sorted(scores.items(), key=lambda item: (-float(item[1]), int(item[0])))
    parts = [
        f"{experiment.node_names[int(index)]}:{float(value):.4f}"
        for index, value in ranked[: int(top_n)]
    ]
    return ",".join(parts)
