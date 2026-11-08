"""Keep-or-zero finish pass: sprite occupancy motion decides travel.

Search can pick a large angle on one frame and a different large angle on
the next. A spring that follows every frame damps the real swing with the
mistake. This pass does not scale motion.

For one bone (or root) at one frame:

- Keep the current angles unchanged when the occupancy appear/disappear
  pairs that frame actually changes beat holding still by
  ``SPRITE_ALIGNED_KEEP_MIN_IMPROVEMENT``, and no affected pair gets worse.
- Otherwise copy the previous frame's bounded angles onto this frame
  (zero travel). Not a lerp. Not a 0.5x scale.

Clip-mean occupancy motion is not the gate. Holding frame t only changes
pairs (t-1, t) and (t, t+1). Averaging those pairs over the whole clip
lets a one-pixel accident keep a 40 degree pop.

Authority is occupancy motion, not pixel fill. Fill rewards covering the
still blob; that is the jitter we are trying to drop.

Tiny travel (below ``SPRITE_ALIGNED_MIN_TRAVEL_RAD`` / translation epsilon)
is already ~zero: skip the test and leave it.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

SPRITE_ALIGNED_MIN_TRAVEL_DEG = 0.5
SPRITE_ALIGNED_MIN_TRAVEL_RAD = math.radians(SPRITE_ALIGNED_MIN_TRAVEL_DEG)
SPRITE_ALIGNED_MIN_TRANSLATION = 1e-4
# Occupancy-motion pair quality is 0..1. One extra XOR pixel is far below
# this. A limb that actually appears or disappears is far above it.
SPRITE_ALIGNED_KEEP_MIN_IMPROVEMENT = 0.01


def should_keep_travel(
    current_motion_mean: float,
    hold_motion_mean: float,
    *,
    min_improvement: float,
) -> bool:
    """True when current travel beats holding still on occupancy motion.

    Equal or worse motion match is a mistaken move: caller must zero it.
    ``min_improvement`` 0 keeps travel only on a strict gain.
    """
    current = float(current_motion_mean)
    hold = float(hold_motion_mean)
    extra = float(min_improvement)
    if not math.isfinite(current) or not math.isfinite(hold):
        raise ValueError("occupancy motion means must be finite")
    if not math.isfinite(extra) or extra < 0.0:
        raise ValueError("min_improvement must be finite and non-negative")
    return current > hold + extra


def affected_pair_quality_indices(frame: int, frame_count: int) -> tuple[int, ...]:
    """``motionQuality`` indices of occupancy pairs that holding ``frame`` changes.

    ``motionQuality[i]`` for i >= 1 is the pair from frame i-1 to i.
    Frame 0 duplicates pair 0, so it is never an extra independent pair.
    """
    dest = int(frame)
    frames = int(frame_count)
    if dest < 1:
        raise ValueError("hold frame must be at least 1")
    if frames < 2:
        raise ValueError("affected pairs need at least two frames")
    if dest >= frames:
        raise ValueError(f"hold frame {dest} is outside 0..{frames - 1}")
    indices = [dest]
    if dest + 1 < frames:
        indices.append(dest + 1)
    return tuple(indices)


def pair_qualities_for_frame(motion_quality_row, frame: int) -> tuple[float, ...]:
    """Occupancy-motion pair qualities affected by holding this frame."""
    if hasattr(motion_quality_row, "detach"):
        values = motion_quality_row.detach().reshape(-1)
        row = tuple(float(item) for item in values.cpu().tolist())
    else:
        row = tuple(float(item) for item in motion_quality_row)
    if any(not math.isfinite(item) for item in row):
        raise ValueError("occupancy motion pair qualities must be finite")
    indices = affected_pair_quality_indices(frame, len(row))
    return tuple(row[index] for index in indices)


def should_keep_local_pairs(
    current_pairs: Sequence[float],
    hold_pairs: Sequence[float],
    *,
    min_improvement: float,
) -> bool:
    """Keep travel only when local occupancy pairs improve and none get worse.

    A pop that helps one pair and hurts the next is a false motion even if
    the two-pair mean ticks up. Intentional travel is not scaled.
    """
    currents = [float(item) for item in current_pairs]
    holds = [float(item) for item in hold_pairs]
    if len(currents) != len(holds) or not currents:
        raise ValueError("current and hold pair lists must be the same non-empty length")
    if any(not math.isfinite(item) for item in currents + holds):
        raise ValueError("occupancy motion pair qualities must be finite")
    extra = float(min_improvement)
    if not math.isfinite(extra) or extra < 0.0:
        raise ValueError("min_improvement must be finite and non-negative")
    if any(current < hold for current, hold in zip(currents, holds)):
        return False
    return should_keep_travel(
        sum(currents) / len(currents),
        sum(holds) / len(holds),
        min_improvement=extra,
    )


def traveling_frame_indices(values, *, min_travel: float) -> tuple[int, ...]:
    """Return frame indices >= 1 whose step from the previous frame exceeds min_travel."""
    import torch

    extra = float(min_travel)
    if not math.isfinite(extra) or extra < 0.0:
        raise ValueError("min_travel must be finite and non-negative")
    if int(values.ndim) not in {1, 2}:
        raise ValueError("travel values must have shape (frames,) or (frames, components)")
    frame_count = int(values.shape[0])
    if frame_count < 2:
        return ()
    delta = values[1:] - values[:-1]
    if int(delta.ndim) == 1:
        travel = delta.abs()
    else:
        travel = torch.linalg.vector_norm(delta, dim=-1)
    moved = (travel > extra).detach().cpu().tolist()
    return tuple(index + 1 for index, flag in enumerate(moved) if bool(flag))


def hold_raw_vector_at_frame(raw, *, frame: int):
    """Copy raw[frame-1] onto raw[frame]. Frame 0 is illegal."""
    dest = int(frame)
    if dest < 1:
        raise ValueError("hold frame must be at least 1")
    if dest >= int(raw.shape[0]):
        raise ValueError(f"hold frame {dest} is outside 0..{int(raw.shape[0]) - 1}")
    out = raw.detach().clone()
    out[dest] = out[dest - 1]
    return out


def hold_raw_bone_at_frame(
    raw,
    *,
    bone_index: int,
    frame: int,
    joint_limit_rad: float,
    bone_limit_scales,
):
    """Copy this bone's bounded angles from frame-1 onto frame.

    Other bones and other frames stay unchanged. Copy is in angle space,
    then written back through atanh so the raw parameter matches a hold,
    not a half-step.
    """
    import torch

    dest = int(frame)
    if dest < 1:
        raise ValueError("hold frame must be at least 1")
    if dest >= int(raw.shape[0]):
        raise ValueError(f"hold frame {dest} is outside 0..{int(raw.shape[0]) - 1}")
    if not math.isfinite(float(joint_limit_rad)) or float(joint_limit_rad) <= 0.0:
        raise ValueError("joint_limit_rad must be finite and positive")
    scales = bone_limit_scales.to(device=raw.device, dtype=raw.dtype).reshape(-1)
    joint = int(bone_index)
    if joint < 0 or joint >= int(scales.numel()):
        raise ValueError(f"bone_index {joint} is outside 0..{int(scales.numel()) - 1}")
    if joint >= int(raw.shape[1]):
        raise ValueError(f"bone_index {joint} is outside raw bone count {int(raw.shape[1])}")
    limit = float(joint_limit_rad) * float(scales[joint].detach().item())
    if limit <= 1e-12:
        raise ValueError(f"bone {joint} has a zero joint limit")
    bounded = torch.tanh(raw) * float(joint_limit_rad) * scales.view(1, -1, 1)
    held_angles = bounded[dest - 1, joint, :].clamp(-limit, limit)
    out = raw.detach().clone()
    out[dest, joint, :] = torch.atanh((held_angles / limit).clamp(-0.999, 0.999))
    return out
