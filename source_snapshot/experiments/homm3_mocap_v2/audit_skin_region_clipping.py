"""Audit source-weight loss caused by profile region clipping.

This is a CPU-only diagnostic.  It remaps the complete source dense weights to
the prepared joint order, but deliberately does not restrict weights to the
profile's allowed region joints.  The returned candidate changes weights only;
geometry, bind data and ownership labels remain untouched.
"""
from __future__ import annotations

import copy
from typing import Any

import numpy as np


_EPS = 1.0e-8


def _array(target: dict[str, Any], key: str) -> np.ndarray:
    if key not in target:
        raise ValueError(f"target asset is missing {key}")
    return np.asarray(target[key])


def _source_map(profile: dict[str, Any]) -> dict[str, str]:
    mapping = profile.get("sourceJointMap")
    if not isinstance(mapping, dict):
        raise ValueError("profile requires sourceJointMap")
    return {str(source): str(destination) for source, destination in mapping.items()}


def audit(original: dict[str, Any], target: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Return an unclipped remapped-weight candidate and clipping diagnostics."""
    required_original = ("vertices", "triangles", "uvs", "albedo", "weights", "names", "regions")
    missing = [key for key in required_original if key not in original]
    if missing:
        raise ValueError(f"prepared skin is missing {missing}")
    if profile.get("rigidAttachments"):
        raise ValueError("rigidAttachments are not supported by ordinary unclipped source audit")
    for key in ("vertices", "triangles", "uvs", "albedo"):
        if key not in target or not np.array_equal(np.asarray(original[key]), np.asarray(target[key])):
            raise ValueError(f"target geometry/material differs from prepared skin: {key}")

    source_weights = _array(target, "sourceDenseWeights").astype(np.float64, copy=False)
    source_names = [str(value) for value in _array(target, "sourceNames" if "sourceNames" in target else "names").tolist()]
    prepared_names = [str(value) for value in np.asarray(original["names"]).tolist()]
    regions = [str(value) for value in np.asarray(original["regions"]).tolist()]
    vertices = np.asarray(original["vertices"])
    if source_weights.ndim != 2 or source_weights.shape != (len(vertices), len(source_names)):
        raise ValueError("source dense weights do not match target vertices and source names")
    if len(set(source_names)) != len(source_names) or len(set(prepared_names)) != len(prepared_names):
        raise ValueError("source and prepared joint names must be unique")
    if len(regions) != len(vertices):
        raise ValueError("prepared regions do not match target vertices")
    prepared_weights = np.asarray(original["weights"], dtype=np.float64)
    if prepared_weights.shape != (len(vertices), len(prepared_names)):
        raise ValueError("prepared weights do not match vertices and prepared names")
    if (not np.isfinite(prepared_weights).all() or np.any(prepared_weights < 0.0) or
            not np.allclose(prepared_weights.sum(axis=1), 1.0, atol=1e-8, rtol=0.0)):
        raise ValueError("prepared weights must be finite, nonnegative, and normalized")
    if not np.isfinite(source_weights).all() or np.any(source_weights < 0.0):
        raise ValueError("source dense weights must be finite and nonnegative")
    if not np.allclose(source_weights.sum(axis=1), 1.0, atol=1e-8, rtol=0.0):
        raise ValueError("source dense weights must be normalized")

    mapping = _source_map(profile)
    if set(mapping) != set(source_names):
        raise ValueError("sourceJointMap must map every source joint exactly once")
    prepared_index = {name: index for index, name in enumerate(prepared_names)}
    unknown = sorted(set(mapping.values()) - set(prepared_index))
    if unknown:
        raise ValueError(f"sourceJointMap references unknown prepared joints: {unknown}")
    remapped = np.zeros((len(vertices), len(prepared_names)), dtype=np.float64)
    for source_index, source_name in enumerate(source_names):
        remapped[:, prepared_index[mapping[source_name]]] += source_weights[:, source_index]
    if not np.allclose(remapped.sum(axis=1), 1.0, atol=1e-8, rtol=0.0):
        raise ValueError("remapped source weights are not normalized")

    region_joints = profile.get("regionJoints")
    if not isinstance(region_joints, dict):
        raise ValueError("profile requires regionJoints")
    allowed = {str(region): {str(joint) for joint in joints} for region, joints in region_joints.items()}
    missing_regions = sorted(set(regions) - set(allowed))
    if missing_regions:
        raise ValueError(f"profile regionJoints missing vertex regions: {missing_regions}")
    discarded = np.zeros(len(vertices), dtype=np.float64)
    clipped = np.zeros_like(remapped)
    no_allowed_support = 0
    per_region: dict[str, dict[str, float | int]] = {}
    joint_removed = np.zeros(len(prepared_names), dtype=np.float64)
    cross_region = 0
    for vertex, region in enumerate(regions):
        allowed_indices = {prepared_index[name] for name in allowed[region] if name in prepared_index}
        if len(allowed_indices) != len(allowed[region]):
            raise ValueError(f"region {region} references an unknown prepared joint")
        outside = np.ones(len(prepared_names), dtype=bool)
        outside[list(allowed_indices)] = False
        mass = float(remapped[vertex, outside].sum())
        discarded[vertex] = mass
        if not allowed_indices:
            raise ValueError(f"region {region} has no prepared allowed joints")
        clipped[vertex, list(allowed_indices)] = remapped[vertex, list(allowed_indices)]
        kept = float(clipped[vertex].sum())
        if kept <= _EPS:
            no_allowed_support += 1
        else:
            clipped[vertex] /= kept
        joint_removed[outside] += remapped[vertex, outside]
        if mass > _EPS:
            cross_region += 1
        item = per_region.setdefault(region, {"vertexCount": 0, "verticesWithDiscardedMass": 0, "discardedMass": 0.0})
        item["vertexCount"] += 1
        item["verticesWithDiscardedMass"] += int(mass > _EPS)
        item["discardedMass"] += mass

    candidate = copy.deepcopy(original)
    candidate["weights"] = remapped.copy()
    report = {
        "proof": "source-region-clipping-diagnostic",
        "accepted": False,
        "inputContract": {"geometryIdentical": True, "sourceWeightRowsNormalized": True,
                           "sourceMaxInfluences": int(np.count_nonzero(source_weights > _EPS, axis=1).max(initial=0)),
                           "remappedMaxInfluences": int(np.count_nonzero(remapped > _EPS, axis=1).max(initial=0)),
                           "export8Compatible": bool(np.count_nonzero(remapped > _EPS, axis=1).max(initial=0) <= 8),
                           "sourceJointCount": len(source_names), "preparedJointCount": len(prepared_names)},
        "sourceJointMap": mapping,
        "perRegion": per_region,
        "jointRemovedMass": {name: float(mass) for name, mass in zip(prepared_names, joint_removed) if mass > _EPS},
        "discardedMassTotal": float(discarded.sum()),
        "discardedMassMaxPerVertex": float(discarded.max(initial=0.0)),
        "verticesWithCrossRegionMass": int(cross_region),
        "noAllowedSupportVertices": int(no_allowed_support),
        "clippedReconstruction": None if no_allowed_support else {
            "maxAbsDifferenceFromPrepared": float(np.abs(clipped - prepared_weights).max(initial=0.0)),
            "meanAbsDifferenceFromPrepared": float(np.abs(clipped - prepared_weights).mean()),
            "matchesPreparedWeights": bool(np.allclose(clipped, prepared_weights, atol=1e-8, rtol=0.0)),
            "meaning": "diagnostic reconstruction of region-restricted remap; not assumed to equal prepared weights",
        },
        "candidateChanges": ["weights"],
        "rigidAttachmentsRejected": True,
    }
    return {"skin": candidate, "report": report}


__all__ = ["audit"]
