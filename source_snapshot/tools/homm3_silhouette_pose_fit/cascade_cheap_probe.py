"""Sparse joint probes on free frames only.

Locked idle prefix/suffix are never rastered. ``keep_count`` 0 means every
free frame. ``keep_count`` > 0 takes the worst-scoring free frames from the
current opening baseline. Unsampled frames keep that baseline during the
probe so accept/reject deltas are zero there.

With ``cheap_joint_probe_occupancy_only``, Lab chroma is skipped and mesh
collision still scores. With DINO score modes, the same frame subset is
rastered with the full semantic scorer (not occupancy-only).
"""
from __future__ import annotations

from typing import Sequence


def free_frame_positions(*, frame_count: int, prefix: int, suffix: int) -> tuple[int, ...]:
    total = int(frame_count)
    pre = max(0, int(prefix))
    suf = max(0, int(suffix))
    if pre + suf >= total:
        raise ValueError("idle prefix/suffix leave no free frames for cheap probes")
    return tuple(range(pre, total - suf))


def cheap_probe_positions(
    scores: Sequence[float],
    *,
    prefix: int,
    suffix: int,
    keep_count: int,
) -> tuple[int, ...]:
    """Return clip-local frame indices to raster for one cheap joint visit."""
    values = [float(item) for item in scores]
    free = free_frame_positions(frame_count=len(values), prefix=prefix, suffix=suffix)
    if int(keep_count) < 0:
        raise ValueError("keep_count must be >= 0 (0 = every free frame)")
    if int(keep_count) == 0 or int(keep_count) >= len(free):
        return free
    ranked = sorted(free, key=lambda index: (float(values[int(index)]), int(index)))
    picked = ranked[: int(keep_count)]
    return tuple(sorted(int(index) for index in picked))


def scatter_sparse_scores(
    baseline: Sequence[float],
    sparse: Sequence[float],
    positions: Sequence[int],
) -> list[float]:
    """Write sparse probe scores into a full-clip baseline copy.

    Unsampled frames keep the baseline so keep delta is 0 there. Positions
    must be clip-local indices, never locked idle prefix/suffix.
    """
    out = [float(value) for value in baseline]
    if len(sparse) != len(positions):
        raise ValueError("sparse scores and positions length mismatch")
    for index, value in zip(positions, sparse):
        slot = int(index)
        if slot < 0 or slot >= len(out):
            raise ValueError(f"sparse position {slot} is outside the clip")
        out[slot] = float(value)
    return out
