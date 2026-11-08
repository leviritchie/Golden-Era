"""Deterministic source-weight initialization for profile-driven target assets."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

import numpy as np


def _mapping_hash(mapping: dict[str, str]) -> str:
    payload = json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def initialize_source_weights(
    source_dense_weights: np.ndarray,
    source_bone_names: Iterable[str],
    donor_joint_names: Iterable[str],
    vertex_regions: Iterable[str],
    profile: dict[str, Any],
    *, source_vertex_ids=None,
) -> dict[str, Any]:
    """Remap source weights, restrict them by anatomy, and fail closed.

    ``sourceJointMap`` is deliberately mandatory for opted-in profiles. No
    nearest-bone or torso fallback is permitted when support is absent.
    """
    source = np.asarray(source_dense_weights, dtype=np.float64)
    source_names = [str(name) for name in source_bone_names]
    donor_names = [str(name) for name in donor_joint_names]
    regions = [str(region) for region in vertex_regions]
    if source.ndim != 2 or source.shape[1] != len(source_names) or len(source) != len(regions):
        raise ValueError("source dense weights, source bones, and vertex regions have incompatible dimensions")
    if not np.isfinite(source).all() or np.any(source < -1e-8):
        raise ValueError("source dense weights must be finite and non-negative")
    row_sums = source.sum(axis=1)
    if np.any(row_sums <= 1e-8) or not np.allclose(row_sums, 1.0, atol=1e-5):
        raise ValueError("source dense weights must have normalized nonzero rows")
    if len(set(source_names)) != len(source_names):
        raise ValueError("source bone names must be unique")
    mapping = profile.get("sourceJointMap")
    if not isinstance(mapping, dict) or set(mapping) != set(source_names):
        raise ValueError("sourceJointMap must explicitly map every source bone")
    mapping = {str(source_name): str(donor) for source_name, donor in mapping.items()}
    donor_index = {name: index for index, name in enumerate(donor_names)}
    if len(donor_index) != len(donor_names):
        raise ValueError("donor joint names must be unique")
    missing = sorted(set(mapping.values()) - set(donor_index))
    if missing:
        raise ValueError(f"sourceJointMap names donors absent from skeleton: {missing}")
    remapped = np.zeros((len(source), len(donor_names)), dtype=np.float64)
    for column, source_name in enumerate(source_names):
        remapped[:, donor_index[mapping[source_name]]] += source[:, column]

    region_joints = profile.get("regionJoints")
    if not isinstance(region_joints, dict):
        raise ValueError("profile requires regionJoints")
    rigid_by_region = {}
    for entry in profile.get("rigidAttachments", ()):
        if not isinstance(entry, dict) or not entry.get("region"):
            raise ValueError("rigidAttachments entries require a region")
        rigid_by_region[str(entry["region"])] = tuple(str(item) for item in entry.get("donorJoints", ()))
    weights = np.zeros_like(remapped)
    restricted_mass = []
    rigid_count = 0
    physical_regions = set()
    overrides = {}
    applied_overrides = set()
    if "geometryOwnership" in profile:
        from geometry_ownership import load_ownership, body_weight_overrides
        ownership = load_ownership(profile)
        physical_regions = {part["region"] for part in ownership["rigidParts"]}
        overrides = body_weight_overrides(ownership, profile)
        if overrides:
            source_vertex_ids = np.asarray(source_vertex_ids)
            if (source_vertex_ids.shape != (len(source),) or not np.issubdtype(source_vertex_ids.dtype, np.integer) or
                    np.any(source_vertex_ids < 0) or np.any(source_vertex_ids >= ownership["sourceVertexCount"])):
                raise ValueError("body weight overrides require complete valid source_vertex_ids")
    for vertex, region in enumerate(regions):
        if region in rigid_by_region:
            allowed = rigid_by_region[region]
            if len(allowed) != 1:
                raise ValueError(f"rigid region {region} requires exactly one donor joint")
            rigid_count += 1
        elif region in region_joints:
            allowed = tuple(str(item) for item in region_joints[region])
        else:
            raise ValueError(f"vertex region {region} is absent from regionJoints")
        indices = [donor_index[name] for name in allowed if name in donor_index]
        if len(indices) != len(allowed):
            raise ValueError(f"region {region} references donor joint absent from skeleton")
        mass = float(remapped[vertex, indices].sum())
        restricted_mass.append(mass)
        if region in physical_regions:
            if region not in rigid_by_region or len(indices) != 1:
                raise ValueError("physical prop requires one explicit rigid owner")
            weights[vertex, indices[0]] = 1.0
            continue
        if overrides and int(source_vertex_ids[vertex]) in overrides:
            source_id = int(source_vertex_ids[vertex])
            override = overrides[source_id]
            if override["region"] != region or source_id in applied_overrides:
                raise ValueError("body override source ID must resolve exactly once to its authored body region")
            for name, value in override["weights"].items():
                weights[vertex, donor_index[name]] = value
            applied_overrides.add(source_id)
            continue
        if mass <= 1e-8:
            raise ValueError(f"vertex {vertex} has zero support in region {region}")
        weights[vertex, indices] = remapped[vertex, indices] / mass
    if applied_overrides != set(overrides):
        raise ValueError("body weight override source IDs were not all applied to their body copies")
    return {
        "weights": weights,
        "mappingHash": _mapping_hash(mapping),
        "restrictedMassReport": {
            "min": float(min(restricted_mass, default=0.0)),
            "max": float(max(restricted_mass, default=0.0)),
            "mean": float(np.mean(restricted_mass)) if restricted_mass else 0.0,
        },
        "rigidCount": rigid_count,
        "bodyWeightOverrideCount": len(applied_overrides),
        "sourceJointMap": mapping,
    }
