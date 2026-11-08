"""Early-step profile symmetry for cascade joint search.

During the first N bone visits, bilateral anatomy groups (wing_a/wing_b,
leg_a/leg_b, etc.) are driven from the primary side only; accepted local
rotations are copied to the paired bones so both sides move identically.
Central groups (trunk, neck, tail) only probe axes that stay in the
profile plane (default local x/y), preserving left-right symmetry.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

AXIS_LABELS = ("x", "y", "z")


def symmetry_catalog_defaults(catalog: Mapping[str, Any] | None) -> dict[str, Any]:
    symmetry = (catalog or {}).get("symmetry") or {}
    pairs = symmetry.get("bilateralGroupPairs") or symmetry.get("bilateral_group_pairs") or ()
    central = symmetry.get("centralGroups") or symmetry.get("central_groups") or ()
    axes = symmetry.get("centralJointAxes") or symmetry.get("central_joint_axes") or ("x", "y")
    return {
        "bilateral_group_pairs": tuple(
            tuple(str(part) for part in pair) for pair in pairs
        ),
        "central_groups": tuple(str(name) for name in central),
        "central_joint_axes": tuple(str(axis) for axis in axes),
    }


def build_bilateral_index_pairs(
    group_spans: Sequence[tuple[str, Sequence[int]]],
    group_pairs: Sequence[tuple[str, str]],
) -> dict[int, int]:
    by_group = {str(name): tuple(int(i) for i in indices) for name, indices in group_spans}
    pairs: dict[int, int] = {}
    for left_name, right_name in group_pairs:
        left = by_group.get(str(left_name))
        right = by_group.get(str(right_name))
        if left is None or right is None:
            raise ValueError(
                f"bilateral pair {left_name!r}/{right_name!r} missing from anatomy spans"
            )
        if len(left) != len(right):
            raise ValueError(
                f"bilateral pair {left_name!r}/{right_name!r} chain length mismatch "
                f"({len(left)} vs {len(right)})"
            )
        for left_index, right_index in zip(left, right):
            pairs[int(left_index)] = int(right_index)
            pairs[int(right_index)] = int(left_index)
    return pairs


def build_group_index_sets(
    group_spans: Sequence[tuple[str, Sequence[int]]],
) -> dict[str, frozenset[int]]:
    return {
        str(name): frozenset(int(index) for index in indices) for name, indices in group_spans
    }


def secondary_group_names(group_pairs: Sequence[tuple[str, str]]) -> frozenset[str]:
    return frozenset(str(right) for _, right in group_pairs)


def central_bone_indices(
    group_spans: Sequence[tuple[str, Sequence[int]]],
    central_groups: Sequence[str],
) -> frozenset[int]:
    by_group = {str(name): tuple(int(i) for i in indices) for name, indices in group_spans}
    indices: set[int] = set()
    for name in central_groups:
        if str(name) not in by_group:
            raise ValueError(f"central symmetry group missing from anatomy spans: {name!r}")
        indices.update(by_group[str(name)])
    return frozenset(indices)


def filter_joint_directions(
    directions: Sequence[tuple[float, float, float]],
    *,
    allowed_axes: Sequence[str],
) -> list[tuple[float, float, float]]:
    allowed = {str(axis) for axis in allowed_axes}
    if not allowed:
        raise ValueError("central_joint_axes must not be empty when symmetry filters directions")
    filtered: list[tuple[float, float, float]] = []
    for direction in directions:
        parts = tuple(float(part) for part in direction)
        if len(parts) != 3:
            raise ValueError("joint direction must be a 3-vector")
        active = [
            label
            for label, value in zip(AXIS_LABELS, parts)
            if abs(float(value)) > 1e-12
        ]
        if not active:
            filtered.append(parts)
            continue
        if any(label not in allowed for label in active):
            continue
        filtered.append(parts)
    return filtered


def mirror_bone_raw(bone_vectors, bone_index: int, partner_index: int) -> None:
    bone_vectors[:, int(partner_index), :].copy_(bone_vectors[:, int(bone_index), :])


def mirror_group_bones(
    bone_vectors,
    source_indices: Sequence[int],
    target_indices: Sequence[int],
) -> None:
    if len(source_indices) != len(target_indices):
        raise ValueError("mirror_group_bones requires equal chain lengths")
    for source, target in zip(source_indices, target_indices):
        mirror_bone_raw(bone_vectors, int(source), int(target))


def mirror_bilateral_after_bones(
    bone_vectors,
    bone_indices: Sequence[int],
    bilateral_pairs: Mapping[int, int],
) -> None:
    for bone_index in bone_indices:
        partner = bilateral_pairs.get(int(bone_index))
        if partner is None:
            continue
        mirror_bone_raw(bone_vectors, int(bone_index), int(partner))
