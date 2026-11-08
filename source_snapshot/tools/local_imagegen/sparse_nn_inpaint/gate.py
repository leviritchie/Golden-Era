"""Fail-closed exact nearest-collapse gate."""

from __future__ import annotations

from PIL import Image

from nearest_collapse import nearest_collapse_metrics, sample_neighbor_discontinuity


def assert_exact_collapse(hr: Image.Image, lr: Image.Image) -> dict:
    metrics = nearest_collapse_metrics(hr, lr)
    if metrics["exact_frac"] < 1.0:
        raise SystemExit(f"exact nearest collapse failed: {metrics}")
    return metrics


def collapse_report(hr: Image.Image, lr: Image.Image) -> dict:
    return {
        "nearest": nearest_collapse_metrics(hr, lr),
        "lattice": sample_neighbor_discontinuity(hr, lr),
    }
