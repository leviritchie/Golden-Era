"""Idle bookend loop closure for idle-leading DEF clips.

When a clip ends on the same idle group it started with (for example Roc
``idle_start_move_end``), the trailing idle suffix must match the leading idle
prefix frame-for-frame so the clip can loop without a pose pop.
"""
from __future__ import annotations


def lock_idle_suffix_winner(winner, *, suffix_count: int, frame_count: int):
    """Reject joint probe winners on trailing idle suffix frames."""
    import torch

    suffix = int(suffix_count)
    count = int(frame_count)
    if suffix <= 0:
        return winner
    locked = winner.detach().clone()
    start = max(0, count - suffix)
    if start < count:
        locked[start:count] = 0
    return locked


def mirror_idle_suffix_from_prefix(
    bone_vectors,
    root_translation,
    root_rotation,
    *,
    prefix_count: int,
    suffix_count: int,
) -> int:
    """Copy leading idle poses onto the trailing idle suffix.

    Returns the number of clip-local frames copied.
    """
    prefix = int(prefix_count)
    suffix = int(suffix_count)
    if suffix <= 0 or prefix <= 0:
        return 0
    frame_count = int(bone_vectors.shape[0])
    suffix_start = frame_count - suffix
    if suffix_start < 0:
        raise ValueError(
            f"suffix_start={suffix_start} is negative for frame_count={frame_count} suffix={suffix}"
        )
    copy_count = min(prefix, suffix)
    if copy_count <= 0:
        return 0
    import torch

    with torch.no_grad():
        for offset in range(copy_count):
            src = int(offset)
            dst = int(suffix_start + offset)
            bone_vectors.data[dst] = bone_vectors.data[src].clone()
            root_translation.data[dst] = root_translation.data[src].clone()
            root_rotation.data[dst] = root_rotation.data[src].clone()
    return int(copy_count)
