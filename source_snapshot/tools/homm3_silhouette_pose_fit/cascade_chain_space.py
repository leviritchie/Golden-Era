"""Chain-space surface navigation: topology and movement vectors.

A base-to-tip branch is one point in an X-joint configuration space.
The target is another point in that same space, identified by matching
the limb's occupancy and chroma surface — not a 2D/3D tip keypoint.

Modes (required when enabled; no silent default):

- ``chain_grad``: overlapping root-to-leaf paths. Per-frame coupled step
  with **equal angle share per active joint** on that path. Full-image
  score gradient on a long overlapping path lives on the hips; a single
  3X RMS unit vector therefore leaves limbs at bind.
- ``branch_trust``: disjoint non-forking segments. DINOv3 autograd uses one
  full-clip F x 3X direction on each segment, normalized by one RMS magnitude
  so relative gradient strength across frames is preserved. The trust-region
  candidate owns and accepts or rejects the complete trajectory atomically.
- ``layer_surface``: one-joint layers in ``search_indices`` order. Default
  cascade resolve depth-sorts search when no explicit bone list is given;
  an explicit anatomy schedule is therefore preserved instead of being
  re-sorted by bind depth.

Tip-Jacobian / blob-centroid IK is intentionally absent.
"""
from __future__ import annotations

import math
from typing import Sequence

CHAIN_SPACE_MODES = ("chain_grad", "branch_trust", "layer_surface")


def select_clipwide_trust_candidate(
    baseline_objective: float,
    candidate_objectives: Sequence[float],
    *,
    min_improvement: float,
) -> int:
    """Return a whole-clip candidate index, or ``-1`` to preserve the baseline.

    The decision is deliberately scalar. A branch proposal owns the complete
    frame-by-joint trajectory and cannot splice per-frame winners.
    """

    baseline = float(baseline_objective)
    threshold = float(min_improvement)
    candidates = tuple(float(value) for value in candidate_objectives)
    if not math.isfinite(baseline):
        raise ValueError("baseline_objective must be finite")
    if not math.isfinite(threshold) or threshold <= 0.0:
        raise ValueError("min_improvement must be finite and positive")
    if not candidates:
        raise ValueError("candidate_objectives cannot be empty")
    if not all(math.isfinite(value) for value in candidates):
        raise ValueError("candidate_objectives must be finite")
    winner = max(range(len(candidates)), key=candidates.__getitem__)
    if candidates[winner] <= baseline + threshold:
        return -1
    return int(winner)


def trust_region_backtracking_steps(
    trust_radius_deg: float,
    trust_radius_min_deg: float,
) -> tuple[float, ...]:
    """Return a complete descending half-step line search inside the radius.

    A nonzero gradient only guarantees improvement in a sufficiently small
    neighborhood. Testing half and full radius once made a rejected 20-degree
    proposal indistinguishable from a branch with no useful direction. Walk
    all the way to the declared floor so a coarse overshoot does not freeze the
    branch for the rest of a short clip fit.
    """

    radius = float(trust_radius_deg)
    floor = float(trust_radius_min_deg)
    if not math.isfinite(radius) or radius <= 0.0:
        raise ValueError("trust_radius_deg must be finite and positive")
    if not math.isfinite(floor) or floor <= 0.0:
        raise ValueError("trust_radius_min_deg must be finite and positive")
    if floor > radius:
        raise ValueError("trust_radius_min_deg cannot exceed trust_radius_deg")
    steps: list[float] = []
    current = radius
    while current > floor:
        steps.append(float(current))
        current *= 0.5
    if not steps or not math.isclose(steps[-1], floor, rel_tol=0.0, abs_tol=1e-12):
        steps.append(floor)
    return tuple(steps)


def _search_parent_map(
    parents: Sequence[int | None],
    search_indices: Sequence[int],
) -> tuple[tuple[int, ...], dict[int, int | None], dict[int, tuple[int, ...]]]:
    search = tuple(int(index) for index in search_indices)
    if not search:
        raise ValueError("search_indices cannot be empty")
    parent_count = len(parents)
    search_set = set(search)
    if len(search_set) != len(search):
        raise ValueError("search_indices must be unique")
    for index in search:
        if index < 0 or index >= parent_count:
            raise ValueError(f"search bone {index} is outside the parent table")
    search_parent: dict[int, int | None] = {}
    children: dict[int, list[int]] = {index: [] for index in search}
    for index in search:
        raw = parents[index]
        parent = None if raw is None else int(raw)
        if parent is not None and parent not in search_set:
            parent = None
        search_parent[index] = parent
        if parent is not None:
            children[parent].append(index)
    child_map = {index: tuple(children[index]) for index in search}
    return search, search_parent, child_map


def derive_root_to_leaf_chains(
    parents: Sequence[int | None],
    search_indices: Sequence[int],
) -> tuple[tuple[int, ...], ...]:
    """Overlapping proximal-to-leaf paths. Shared joints above a fork appear in every descendant path."""
    search, search_parent, child_map = _search_parent_map(parents, search_indices)
    leaves = [index for index in search if not child_map[index]]
    if not leaves:
        raise ValueError("search skeleton has no leaves; refusing a cyclic parent table")
    chains: list[tuple[int, ...]] = []
    seen_leaves: set[int] = set()
    for leaf in leaves:
        if leaf in seen_leaves:
            raise ValueError(f"duplicate leaf {leaf}")
        seen_leaves.add(leaf)
        path = [leaf]
        cursor = leaf
        walked = {leaf}
        while search_parent[cursor] is not None:
            cursor = int(search_parent[cursor])
            if cursor in walked:
                raise ValueError(f"parent cycle while walking leaf {leaf}")
            walked.add(cursor)
            path.append(cursor)
        chains.append(tuple(reversed(path)))
    covered = {index for chain in chains for index in chain}
    missing = [index for index in search if index not in covered]
    if missing:
        raise ValueError(f"root-to-leaf chains miss search bones: {missing[:8]}")
    return tuple(chains)


def derive_disjoint_branch_segments(
    parents: Sequence[int | None],
    search_indices: Sequence[int],
) -> tuple[tuple[int, ...], ...]:
    """Maximal non-forking segments. Pairwise disjoint; every search bone once."""
    search, search_parent, child_map = _search_parent_map(parents, search_indices)
    starts: list[int] = []
    for index in search:
        parent = search_parent[index]
        if parent is None or len(child_map[parent]) != 1:
            starts.append(index)
    if not starts:
        raise ValueError("disjoint branch walk found no segment starts")
    segments: list[tuple[int, ...]] = []
    owned: set[int] = set()
    for start in starts:
        if start in owned:
            raise ValueError(f"segment start {start} is already owned")
        path = [start]
        owned.add(start)
        cursor = start
        while len(child_map[cursor]) == 1:
            child = int(child_map[cursor][0])
            if child in owned:
                raise ValueError(f"disjoint segment overlap at bone {child}")
            path.append(child)
            owned.add(child)
            cursor = child
        segments.append(tuple(path))
    missing = [index for index in search if index not in owned]
    if missing:
        raise ValueError(f"disjoint segments miss search bones: {missing[:8]}")
    extra = owned - set(search)
    if extra:
        raise ValueError(f"disjoint segments contain non-search bones: {sorted(extra)[:8]}")
    return tuple(segments)


def derive_layer_joints(
    parents: Sequence[int | None],
    search_indices: Sequence[int],
    node_depths: Sequence[int],
) -> tuple[tuple[int, ...], ...]:
    """One joint per layer, in ``search_indices`` order.

    Depth sorting belongs upstream (default dependency resolve). When the
    caller passes an explicit search list — e.g. anatomy group priority with
    dependency order inside each group — re-sorting by bind depth would
    put legs before wings on a flyer and undo that schedule. ``node_depths``
    is still required so a short table fails closed.
    """
    search, _, _ = _search_parent_map(parents, search_indices)
    if len(node_depths) < max(search) + 1:
        raise ValueError("node_depths is shorter than the parent table requires")
    # Preserve caller order; ``search`` is the validated unique tuple in
    # the same sequence as ``search_indices``.
    return tuple((index,) for index in search)


def chains_for_mode(
    mode: str,
    *,
    parents: Sequence[int | None],
    search_indices: Sequence[int],
    node_depths: Sequence[int],
) -> tuple[tuple[int, ...], ...]:
    name = str(mode)
    if name not in CHAIN_SPACE_MODES:
        raise ValueError(
            "chain_space_mode must be one of "
            f"{CHAIN_SPACE_MODES}; got {name!r}"
        )
    if name == "chain_grad":
        return derive_root_to_leaf_chains(parents, search_indices)
    if name == "branch_trust":
        return derive_disjoint_branch_segments(parents, search_indices)
    return derive_layer_joints(parents, search_indices, node_depths)


def chain_block_directions(grad, bone_indices, *, min_gradient_norm):
    """Per-frame unit directions on one chain's 3X block. Same contract as the gradient ladder."""
    from roc_gpu_cascade_experiment import gradient_ladder_directions

    return gradient_ladder_directions(
        grad,
        bone_indices,
        min_gradient_norm=min_gradient_norm,
    )


def chain_block_rms_directions(grad, bone_indices, *, min_gradient_norm):
    """One full-clip F x 3X branch direction with RMS magnitude one."""

    import torch

    floor = float(min_gradient_norm)
    if not math.isfinite(floor) or floor <= 0.0:
        raise ValueError("min_gradient_norm must be finite and positive")
    if int(grad.dim()) != 3 or int(grad.shape[2]) != 3:
        raise ValueError("grad must have shape (frames, bones, 3)")
    indices = [int(index) for index in bone_indices]
    if not indices:
        raise ValueError("chain_block_rms_directions requires at least one bone")
    block = grad[:, indices, :]
    flat = block.reshape(int(grad.shape[0]), -1)
    frame_rms = torch.sqrt(torch.mean(flat * flat, dim=1))
    clip_rms = torch.sqrt(torch.mean(flat * flat))
    if not bool(torch.isfinite(frame_rms).all()) or not bool(torch.isfinite(clip_rms)):
        raise RuntimeError("chain-block RMS gradient norm is not finite")
    out = torch.zeros_like(grad)
    if float(clip_rms.detach().cpu().item()) > floor:
        out[:, indices, :] = block / clip_rms
    return out, frame_rms, clip_rms


def equal_share_chain_directions(grad, bone_indices, *, min_gradient_norm):
    """Per-frame coupled direction with the same angle on every active bone.

    ``chain_block_directions`` RMS-normalizes the concatenated 3X gradient.
    On an overlapping hips→leaf path the full-image score slope sits on the
    proximal joints, so a 40° step becomes a hip step and the limb stays at
    bind. This unit-normalizes each bone's 3-vector instead. Bones below
    ``min_gradient_norm`` stay zero. The raster still judges one coupled
    hypothesis: every active joint on the path rotates ``step_deg`` along
    its own gradient. A second 3X RMS normalize would split that angle by
    ``sqrt(X)`` and freeze the limb again.
    """
    import torch

    if not math.isfinite(float(min_gradient_norm)) or float(min_gradient_norm) <= 0.0:
        raise ValueError("min_gradient_norm must be finite and positive")
    if int(grad.dim()) != 3 or int(grad.shape[2]) != 3:
        raise ValueError("grad must have shape (frames, bones, 3)")
    indices = [int(index) for index in bone_indices]
    if not indices:
        raise ValueError("equal_share_chain_directions requires at least one bone")
    floor = float(min_gradient_norm)
    masked = torch.zeros_like(grad)
    bone_norms = []
    for index in indices:
        bone_grad = grad[:, index, :]
        norms = bone_grad.norm(dim=1)
        bone_norms.append(norms)
        active = norms > floor
        safe = torch.where(active, norms, torch.ones_like(norms))
        unit = bone_grad / safe.unsqueeze(-1)
        masked[:, index, :] = torch.where(active.unsqueeze(-1), unit, torch.zeros_like(unit))
    stacked = torch.stack(bone_norms, dim=1).max(dim=1).values
    chain = masked[:, indices, :].reshape(int(grad.shape[0]), -1)
    active_chain = chain.norm(dim=1) > floor
    return torch.where(active_chain.view(-1, 1, 1), masked, torch.zeros_like(masked)), stacked


def clip_block_direction(grad, bone_indices, *, min_gradient_norm):
    """One unit 3X direction, broadcast to every frame.

    RMS is taken on the chain block only. Averaging zeros from bones that
    are not on the chain used to inflate the direction onto the joint limit
    or reject every step.
    """
    import torch

    if not math.isfinite(float(min_gradient_norm)) or float(min_gradient_norm) <= 0.0:
        raise ValueError("min_gradient_norm must be finite and positive")
    if int(grad.dim()) != 3 or int(grad.shape[2]) != 3:
        raise ValueError("grad must have shape (frames, bones, 3)")
    indices = [int(index) for index in bone_indices]
    if not indices:
        raise ValueError("clip_block_direction requires at least one bone")
    block = grad[:, indices, :]
    pooled = block.mean(dim=0)
    flat = pooled.reshape(-1)
    norm = flat.norm()
    if not bool(torch.isfinite(norm)):
        raise RuntimeError("clip-block gradient norm is not finite")
    out = torch.zeros_like(grad)
    if float(norm.detach().cpu().item()) <= float(min_gradient_norm):
        return out, norm
    unit = pooled / norm
    out[:, indices, :] = unit
    return out, norm


def validate_chain_space_config(
    *,
    enabled: bool,
    mode: str,
    iterations: int,
    step_degs: Sequence[float],
    min_gradient_norm: float,
    trust_radius_deg: float,
    trust_radius_min_deg: float,
    trust_radius_max_deg: float,
    min_clip_improvement: float,
    eval_budget: int | None = None,
) -> None:
    if not bool(enabled):
        return
    if str(mode) not in CHAIN_SPACE_MODES:
        raise ValueError(
            "chain_space_mode must be one of "
            f"{CHAIN_SPACE_MODES} when chain_space_enabled; got {mode!r}"
        )
    if int(iterations) < 1:
        raise ValueError("chain_space_iterations must be at least 1 when enabled")
    if eval_budget is not None and int(eval_budget) < 1:
        raise ValueError("chain_space_eval_budget must be a positive int when set")
    if not tuple(step_degs):
        raise ValueError("chain_space_step_degs must be non-empty when enabled")
    previous = 0.0
    for step_deg in step_degs:
        if not math.isfinite(float(step_deg)) or float(step_deg) <= 0.0:
            raise ValueError("chain_space_step_degs must be finite and positive")
        if float(step_deg) <= previous:
            raise ValueError("chain_space_step_degs must be strictly increasing")
        previous = float(step_deg)
    if not math.isfinite(float(min_gradient_norm)) or float(min_gradient_norm) <= 0.0:
        raise ValueError("chain_space_min_gradient_norm must be finite and positive")
    for name, value in (
        ("chain_space_trust_radius_deg", trust_radius_deg),
        ("chain_space_trust_radius_min_deg", trust_radius_min_deg),
        ("chain_space_trust_radius_max_deg", trust_radius_max_deg),
        ("chain_space_min_clip_improvement", min_clip_improvement),
    ):
        if not math.isfinite(float(value)) or float(value) <= 0.0:
            raise ValueError(f"{name} must be finite and positive")
    if float(trust_radius_min_deg) > float(trust_radius_deg):
        raise ValueError("chain_space_trust_radius_min_deg cannot exceed the start radius")
    if float(trust_radius_deg) > float(trust_radius_max_deg):
        raise ValueError("chain_space_trust_radius_deg cannot exceed the max radius")
    if float(trust_radius_min_deg) >= float(trust_radius_max_deg):
        raise ValueError("chain_space_trust_radius_min_deg must be < max")
