"""Score escape config validation."""
from __future__ import annotations

import pytest

from roc_gpu_cascade_experiment import GpuCascadeConfig


def test_score_escape_requires_mode_when_enabled():
    with pytest.raises(ValueError, match="score_escape_mode"):
        GpuCascadeConfig(score_escape_enabled=True, score_escape_mode="").validate()


def test_score_escape_rejects_unknown_mode():
    with pytest.raises(ValueError, match="articulated_retry"):
        GpuCascadeConfig(
            score_escape_enabled=True,
            score_escape_mode="not_a_mode",
        ).validate()


def test_score_escape_accepts_combo():
    GpuCascadeConfig(
        score_escape_enabled=True,
        score_escape_mode="combo",
    ).validate()


def test_score_escape_accepts_until_plateau_retry_coarse():
    GpuCascadeConfig(
        score_escape_enabled=True,
        score_escape_mode="until_plateau_retry_coarse",
        score_escape_max_rounds=5,
    ).validate()


def test_score_escape_accepts_retry_coarse():
    GpuCascadeConfig(
        score_escape_enabled=True,
        score_escape_mode="retry_coarse",
    ).validate()


def test_score_escape_accepts_deep_retry_4():
    GpuCascadeConfig(
        score_escape_enabled=True,
        score_escape_mode="deep_retry_4",
        score_escape_articulated_iterations=2,
    ).validate()
