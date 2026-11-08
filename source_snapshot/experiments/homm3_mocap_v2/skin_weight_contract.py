"""Cheap fail-closed contracts shared by skin fitting and candidate export."""
from __future__ import annotations

import numpy as np


def validate_candidate_weights(weights, original, regions, names, region_joints, train_regions):
    values = np.asarray(weights)
    base = np.asarray(original, dtype=values.dtype)
    labels = np.asarray(regions).astype(str)
    if values.shape != base.shape or values.shape != (len(labels), len(names)):
        raise ValueError("candidate weights changed the vertex or joint inventory")
    if not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError("candidate weights must be finite and nonnegative")
    sum_error = float(np.abs(values.sum(axis=1) - 1).max())
    influences = int((values > 0).sum(axis=1).max())
    if sum_error > 1e-5 or influences > 8:
        raise ValueError("candidate weights violate normalization or export influence limit")
    frozen = ~np.isin(labels, list(train_regions))
    if not np.array_equal(values[frozen], base[frozen]):
        raise ValueError("candidate changed a frozen anatomical region")
    for region in train_regions:
        allowed = np.isin(names, list(region_joints[region]))
        if np.any(values[labels == region][:, ~allowed] != 0):
            raise ValueError(f"candidate leaks outside allowed bones in {region}")
    return {"ok": True, "normalizationMaxError": sum_error, "maxInfluences": influences,
            "frozenVertexCount": int(frozen.sum()), "anatomicalSupportPreserved": True}


def validate_support_candidate_weights(weights, original, allowed_support, train_mask):
    """Per-vertex-support variant: frozen rows unchanged, no mass outside declared support."""
    values = np.asarray(weights)
    base = np.asarray(original, dtype=values.dtype)
    support = np.asarray(allowed_support, dtype=bool)
    trainable = np.asarray(train_mask, dtype=bool)
    if values.shape != base.shape or support.shape != values.shape or trainable.shape != (len(values),):
        raise ValueError("candidate weights, support, or train mask changed the vertex or joint inventory")
    if not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError("candidate weights must be finite and nonnegative")
    sum_error = float(np.abs(values.sum(axis=1) - 1).max())
    influences = int((values > 0).sum(axis=1).max())
    if sum_error > 1e-5 or influences > 8:
        raise ValueError("candidate weights violate normalization or export influence limit")
    if not np.array_equal(values[~trainable], base[~trainable]):
        raise ValueError("candidate changed a frozen vertex")
    if np.any(values[~support] != 0):
        raise ValueError("candidate leaks outside declared per-vertex support")
    moved = np.abs(values - base).sum(axis=1) > 1e-6
    return {"ok": True, "normalizationMaxError": sum_error, "maxInfluences": influences,
            "frozenVertexCount": int((~trainable).sum()), "trainableVertexCount": int(trainable.sum()),
            "vertexCountWithChangedWeights": int(moved.sum()), "declaredSupportPreserved": True}


def holdout_gate(cases):
    return all(
        row["holdoutMeanIouImprovement"] >= 0.01
        and row["afterEdgeRatioP95"] <= row["beforeEdgeRatioP95"] * 1.1
        for row in cases.values()
    ) and bool(cases)


def all_frame_objective_gate(cases):
    """Used when every sequence frame is in the image objective (no holdout)."""
    return all(
        row["allFrameMeanIouImprovement"] >= 0.01
        and row["afterEdgeRatioP95"] <= row["beforeEdgeRatioP95"] * 1.1
        for row in cases.values()
    ) and bool(cases)
