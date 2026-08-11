#!/usr/bin/env python3
"""Unit-agnostic bone order and angle-range helpers for silhouette pose fit.

Order is hierarchy inside→outside (descendant count). Angle ranges and optional
hub locks come from bind parents / subtree mass. Camera vectors are optional
call-site leftovers and do not affect order.
"""
from __future__ import annotations

from typing import Any


def _descendants(bone: str, children: dict[str, list[str]], memo: dict[str, int]) -> int:
    if bone in memo:
        return memo[bone]
    total = 0
    for child in children.get(bone, []):
        total += 1 + _descendants(child, children, memo)
    memo[bone] = total
    return total


def _bone_length(name: str, heads: dict[str, list[float]], parents: dict[str, str | None]) -> float:
    parent = parents.get(name)
    if not parent or parent not in heads or name not in heads:
        return 0.0
    a = heads[name]
    b = heads[parent]
    return float(
        ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5
    )


def _child_map(bones: list[str], parents: dict[str, str | None]) -> dict[str, list[str]]:
    bone_set = set(bones)
    children: dict[str, list[str]] = {b: [] for b in bones}
    for child, parent in parents.items():
        if child not in bone_set:
            continue
        # Parent may be an armature/object outside the deform set; skip those links.
        if parent and parent in children:
            children[parent].append(child)
    return children


def _hierarchy_roots(bones: list[str], parents: dict[str, str | None]) -> list[str]:
    """Bones whose parent is missing or outside the deform bone set."""
    bone_set = set(bones)
    roots = []
    for b in bones:
        p = parents.get(b)
        if not p or p not in bone_set:
            roots.append(b)
    return roots


def build_dependency_order(
    bones: list[str],
    *,
    parents: dict[str, str | None],
    heads: dict[str, list[float]],
    view: list[float] | None = None,
    right: list[float] | None = None,
    center_lateral_frac: float = 0.28,
    # Lock any non-root bone that carries at least this fraction of the skeleton.
    # ~25% catches thorax / shoulder girdle hubs; limb roots (~20%) stay free.
    global_hub_frac: float = 0.25,
) -> tuple[list[str], dict[str, Any]]:
    """Inside→outside by hierarchy mass only (no camera near/far).

    Unlocked bones are sorted by descendant count descending (proximal / high-mass
    first, leaves last). Hierarchy roots and global/branching hubs stay locked.
    `view` / `heads` / `right` are accepted for call-site compatibility but do not
    affect order.
    """
    bones = list(bones)
    children = _child_map(bones, parents)
    memo: dict[str, int] = {}

    def desc(b: str) -> int:
        return _descendants(b, children, memo)

    roots = _hierarchy_roots(bones, parents)
    locked = set(roots) if roots else set()
    if len(roots) > 1:
        # Prefer the root that owns the largest subtree (true hierarchy apex).
        locked = {max(roots, key=lambda b: (desc(b), b))}

    n_other = max(1, len(bones) - 1)
    hub_cut = max(1, int(round(global_hub_frac * n_other)))
    branch_child_cut = max(3, hub_cut // 5)

    for b in bones:
        if b in locked:
            continue
        d = desc(b)
        if d >= hub_cut:
            locked.add(b)
            continue
        # Multi-limb / girdle hubs: two+ heavy children ⇒ full-body attitude if rotated.
        heavy_kids = sum(1 for c in children.get(b, []) if desc(c) >= branch_child_cut)
        if heavy_kids >= 2 and d >= max(4, hub_cut // 3):
            locked.add(b)

    unlocked = [b for b in bones if b not in locked]
    # Inside→outside: more descendants first, stable name tie-break.
    order = sorted(unlocked, key=lambda b: (-desc(b), b))
    return order, {
        "locked": sorted(locked),
        "near": [],
        "center": list(order),
        "far": [],
        "orderMode": "inside_out_hierarchy",
        "globalHubFrac": global_hub_frac,
        "hubDescendantCut": hub_cut,
        "branchChildCut": branch_child_cut,
        "descendantCount": {b: desc(b) for b in bones},
        "boneLength": {b: _bone_length(b, heads, parents) for b in bones},
    }


def filter_search_bones(
    order: list[str],
    *,
    descendant_count: dict[str, int],
    bone_length: dict[str, float],
    skip_tiny: bool = True,
    min_leaf_length_frac: float = 0.45,
) -> list[str]:
    """Drop short leaf tips that barely move silhouette mass."""
    if not skip_tiny:
        return list(order)
    lengths = [float(bone_length.get(b, 0.0)) for b in order]
    positive = sorted(L for L in lengths if L > 1e-8)
    med = positive[len(positive) // 2] if positive else 0.0
    out: list[str] = []
    for b in order:
        d = int(descendant_count.get(b, 0))
        L = float(bone_length.get(b, 0.0))
        if d == 0 and med > 1e-8 and L < min_leaf_length_frac * med:
            continue
        out.append(b)
    return out


def build_range_table(
    bones: list[str],
    *,
    parents: dict[str, str | None],
    heads: dict[str, list[float]],
    locked: set[str] | list[str],
    # Unrestricted search box for unlocked bones (degrees, symmetric).
    free_deg: float = 90.0,
    # Legacy knobs kept for call-site compat; ignored when unrestricted=True.
    leaf_deg: float = 90.0,
    mid_deg: float = 90.0,
    limb_root_deg: float = 90.0,
    leaf_frac: float = 0.04,
    mid_frac: float = 0.10,
    unrestricted: bool = True,
) -> dict[str, tuple[float, float]]:
    """Symmetric angle bounds. Default: no joint limits on unlocked bones (±free_deg)."""
    locked_set = set(locked)
    children = _child_map(bones, parents)
    memo: dict[str, int] = {}
    n_other = max(1, len(bones) - 1)
    counts = {b: _descendants(b, children, memo) for b in bones}

    ranges: dict[str, tuple[float, float]] = {}
    for b in bones:
        if b in locked_set:
            ranges[b] = (0.0, 0.0)
            continue
        if unrestricted:
            half = float(free_deg)
        else:
            d = counts.get(b, 0)
            frac = d / float(n_other)
            if frac >= mid_frac:
                half = limb_root_deg
            elif frac >= leaf_frac:
                half = mid_deg
            else:
                half = leaf_deg
            length = _bone_length(b, heads, parents)
            lengths = [_bone_length(x, heads, parents) for x in bones if x not in locked_set]
            med = sorted(lengths)[len(lengths) // 2] if lengths else 0.0
            if med > 1e-8 and length > 1.25 * med:
                half *= 0.85
            if d >= 10:
                half = min(half, 30.0)
            elif d >= 6:
                half = min(half, 40.0)
            elif d >= 3:
                half = min(half, 55.0)
        ranges[b] = (-float(half), float(half))
    return ranges
