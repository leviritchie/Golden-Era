"""Tests for dynamic silhouette_miss IK movement policy."""

from __future__ import annotations

import math
import unittest

from ik_dynamic_policy import (
    chain_start_length,
    dynamic_stop_score,
    filter_chain_prefixes,
    passes_influence_dominance,
    scale_step_deg,
    sort_blob_jobs,
)


def test_scale_step_deg_displacement_clamps() -> None:
    small = scale_step_deg(
        20.0,
        mode="displacement",
        displacement_px=10.0,
        frame_deficit=0.0,
        ref_px=56.0,
        min_scale=0.4,
        max_scale=1.6,
    )
    assert abs(small - (20.0 * max(0.4, 10.0 / 56.0))) < 1e-9
    large = scale_step_deg(
        20.0,
        mode="displacement",
        displacement_px=200.0,
        frame_deficit=0.0,
        ref_px=56.0,
        min_scale=0.4,
        max_scale=1.6,
    )
    assert abs(large - (20.0 * 1.6)) < 1e-9


def test_chain_start_length_grows_with_displacement() -> None:
    assert chain_start_length(10.0, 6, ref_px=40.0) == 1
    assert chain_start_length(45.0, 6, ref_px=40.0) == 2
    assert chain_start_length(120.0, 6, ref_px=40.0) == 4


def test_filter_chain_prefixes_skips_short_chains() -> None:
    prefixes = ((1,), (1, 2), (1, 2, 3))
    trimmed = filter_chain_prefixes(
        prefixes,
        mode="displacement",
        displacement_px=90.0,
        ref_px=40.0,
    )
    assert trimmed[0] == (1, 2, 3)


def test_influence_dominance_gate() -> None:
    influence = {"A": 0.7, "B": 0.3}
    assert passes_influence_dominance(influence, "A", min_ratio=0.6)
    assert not passes_influence_dominance(influence, "B", min_ratio=0.6)


def test_dynamic_stop_score_moves_toward_target() -> None:
    stop = dynamic_stop_score(0.2, 0.8, displacement_px=56.0, ref_px=56.0)
    assert 0.2 < stop < 0.8


class _Job:
    def __init__(self, displacement: float, priority: float) -> None:
        self.tip_displacement_px = displacement
        self.priority_score = priority


def test_sort_blob_jobs_priority() -> None:
    jobs = [_Job(10.0, 50.0), _Job(40.0, 20.0)]
    ordered = sort_blob_jobs(jobs, mode="priority")
    assert ordered[0].priority_score == 50.0
