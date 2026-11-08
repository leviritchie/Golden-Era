#!/usr/bin/env python3
"""Regression guard: the penetration measure used for descent must not saturate.

This pins the bug that let the roc's head sit inside its own wing. The cascade's
``pair_collision_error_torch`` is ``tanh(sum(violation^2))``; once roughly a hundred
sample pairs overlap, the sum reaches tens and ``tanh`` is flat to float precision,
so a search comparing candidate poses sees no difference between "deeply
interpenetrating" and "slightly more deeply interpenetrating" and has no reason to
separate the parts. Scaling a flat term by a larger weight leaves it flat.

If someone later routes the tracker's guard back through the saturating form, or
"simplifies" the norm by averaging over the pair set, these assertions fail.

Run: py -3 test_penetration_norm.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import torch

TOOL = Path(__file__).resolve().parent
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from gpu_mesh_collision import (  # noqa: E402
    pair_collision_error_torch,
    pair_penetration_norm_torch,
)

MARGIN = 1.0


def _overlapping_batch(depths: list[float], *, pair_count: int) -> tuple[torch.Tensor, torch.Tensor]:
    """Two point clouds whose paired samples sit ``margin - depth`` apart."""
    pairs = torch.stack(
        (
            torch.arange(pair_count, dtype=torch.long),
            torch.arange(pair_count, 2 * pair_count, dtype=torch.long),
        ),
        dim=1,
    )
    batch = []
    for depth in depths:
        left = torch.zeros((pair_count, 3), dtype=torch.float32)
        right = torch.zeros((pair_count, 3), dtype=torch.float32)
        right[:, 0] = float(MARGIN) - float(depth)
        batch.append(torch.cat((left, right), dim=0))
    return torch.stack(batch, dim=0), pairs


def test_clean_pose_is_exactly_zero() -> None:
    positions, pairs = _overlapping_batch([0.0], pair_count=64)
    norm = pair_penetration_norm_torch(positions, pairs, MARGIN)
    assert float(norm[0]) < 1e-5, f"a non-overlapping pose must read zero, got {float(norm[0])}"


def test_tanh_form_saturates_where_the_norm_still_discriminates() -> None:
    # 100 pairs overlapping, as measured on the roc solve, at two different depths.
    positions, pairs = _overlapping_batch([0.55, 0.60], pair_count=100)
    saturated = pair_collision_error_torch(positions, pairs, MARGIN)
    norm = pair_penetration_norm_torch(positions, pairs, MARGIN)

    saturated_gap = abs(float(saturated[1]) - float(saturated[0]))
    norm_gap = abs(float(norm[1]) - float(norm[0]))
    assert saturated_gap < 1e-6, (
        "expected the tanh form to be flat here; if it now discriminates, this test's "
        f"premise changed (gap {saturated_gap})"
    )
    assert norm_gap > 0.1, (
        f"the descent measure must separate these poses, gap was only {norm_gap}"
    )


def test_norm_is_monotone_in_depth_and_in_pair_count() -> None:
    positions, pairs = _overlapping_batch([0.1, 0.3, 0.5, 0.9], pair_count=32)
    norm = pair_penetration_norm_torch(positions, pairs, MARGIN)
    values = [float(value) for value in norm]
    assert values == sorted(values), f"deeper penetration must score worse, got {values}"

    few, few_pairs = _overlapping_batch([0.5], pair_count=8)
    many, many_pairs = _overlapping_batch([0.5], pair_count=64)
    few_value = float(pair_penetration_norm_torch(few, few_pairs, MARGIN)[0])
    many_value = float(pair_penetration_norm_torch(many, many_pairs, MARGIN)[0])
    assert many_value > few_value, (
        "more overlapping pairs at the same depth must score worse, otherwise the "
        "solver has no incentive to reduce how much of the body overlaps "
        f"({many_value} vs {few_value})"
    )


def main() -> int:
    test_clean_pose_is_exactly_zero()
    test_tanh_form_saturates_where_the_norm_still_discriminates()
    test_norm_is_monotone_in_depth_and_in_pair_count()
    print({"ok": True, "tests": 3})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
