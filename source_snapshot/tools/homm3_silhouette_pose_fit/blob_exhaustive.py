"""Exhaustive regional search over bones that own leftover silhouette blobs.

After ``one_bone_depth`` covers bulk occupancy, silhouette-miss pairing names
the distal bone that skins a red excess blob. This module turns that bone plus
a short parent chain into an exhaustive joint-limit search. The caller scores
candidates only inside the leftover neighborhood.

Chain order is distal-first: assigned bone, then parent, then grandparent.
Spinal bones (hierarchy depth below ``min_bone_depth``) are omitted so an
exhaustive swing cannot become a whole-mesh spin.
"""
from __future__ import annotations

from typing import Sequence

from ik_incremental_blob import distal_first_parent_chain


def blob_exhaustive_chain(
    assigned_index: int,
    parents: Sequence[int | None],
    node_depths: Sequence[int],
    *,
    max_joints: int,
    min_bone_depth: int,
) -> tuple[int, ...]:
    """Return a distal-first chain that stays on limb bones.

    ``assigned_index`` must itself be at or below ``min_bone_depth`` (deeper
    numbers are more distal). Proximal ancestors are dropped, not replaced.
    """
    if int(max_joints) < 1:
        raise ValueError("max_joints must be at least 1")
    if int(min_bone_depth) < 0:
        raise ValueError("min_bone_depth must be non-negative")
    assigned = int(assigned_index)
    if assigned < 0 or assigned >= len(parents):
        raise ValueError(f"assigned bone {assigned} is outside 0..{len(parents) - 1}")
    if assigned >= len(node_depths):
        raise ValueError(f"assigned bone {assigned} has no hierarchy depth")
    if int(node_depths[assigned]) < int(min_bone_depth):
        raise ValueError(
            f"assigned bone {assigned} is proximal "
            f"(depth={int(node_depths[assigned])} < min_bone_depth={int(min_bone_depth)})"
        )
    raw = distal_first_parent_chain(assigned, parents, max_joints=int(max_joints))
    kept = tuple(
        int(index)
        for index in raw
        if int(node_depths[int(index)]) >= int(min_bone_depth)
    )
    if not kept:
        raise ValueError(
            f"blob exhaustive chain for bone {assigned} dropped every joint "
            f"under min_bone_depth={int(min_bone_depth)}"
        )
    return kept


def split_blob_exhaustive_search(
    chain: Sequence[int],
    *,
    block_size: int,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Split a distal-first chain into a Cartesian block and leftover 1D bones.

    The Cartesian block is the most distal ``block_size`` joints, returned in
    parent-then-child order so the existing multi-bone grid can pose them
    together. Remaining (more proximal) joints are returned distal-first for
    later 1D exhaustive sweeps.
    """
    if int(block_size) < 1:
        raise ValueError("block_size must be at least 1")
    nodes = tuple(int(index) for index in chain)
    if not nodes:
        raise ValueError("chain must contain at least one bone")
    distal = nodes[: int(block_size)]
    remaining = nodes[int(block_size) :]
    cartesian = tuple(reversed(distal)) if len(distal) >= 2 else distal
    return cartesian, remaining


def blob_grid_candidate_count(bone_count: int, angle_count: int) -> int:
    """Return the Cartesian product size for one axis across ``bone_count`` bones."""
    if int(bone_count) < 1:
        raise ValueError("bone_count must be at least 1")
    if int(angle_count) < 1:
        raise ValueError("angle_count must be at least 1")
    return int(angle_count) ** int(bone_count)


def require_blob_grid_fits(
    *,
    bone_count: int,
    angle_count: int,
    max_candidates: int,
) -> int:
    """Fail closed when an exhaustive product would exceed the raster bound."""
    if int(max_candidates) < 1:
        raise ValueError("max_candidates must be at least 1")
    count = blob_grid_candidate_count(int(bone_count), int(angle_count))
    if count > int(max_candidates):
        raise RuntimeError(
            "blob exhaustive Cartesian grid exceeds max_candidates: "
            f"{int(angle_count)}^{int(bone_count)}={count} "
            f"max={int(max_candidates)}; increase the coarse step, "
            "raise max_candidates, or lower blob_exhaustive_block_size"
        )
    return count
