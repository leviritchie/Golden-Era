"""Diagnostic quality metrics for declared rigid mesh attachments."""
from __future__ import annotations

from typing import Any

import numpy as np
import torch

from skin_surface_constraints import triangle_principal_stretches


def _tensor(value: Any, *, name: str, dtype=torch.float64) -> torch.Tensor:
    result = torch.as_tensor(value, dtype=dtype).detach().clone()
    if not torch.isfinite(result).all():
        raise ValueError(f"{name} contains nonfinite values")
    return result


def _kabsch_residual(rest: torch.Tensor, posed: torch.Tensor) -> torch.Tensor:
    rc, pc = rest.mean(0), posed.mean(0)
    h = (rest - rc).T @ (posed - pc)
    u, _, vh = torch.linalg.svd(h)
    sign = torch.linalg.det(vh.T @ u.T)
    correction = torch.eye(3, dtype=rest.dtype, device=rest.device)
    correction[-1, -1] = torch.where(sign < 0, torch.tensor(-1., dtype=rest.dtype, device=rest.device), torch.tensor(1., dtype=rest.dtype, device=rest.device))
    rotation = vh.T @ correction @ u.T
    fitted = (rest - rc) @ rotation.T + pc
    return torch.linalg.vector_norm(fitted - posed, dim=1)


def attachment_quality(animated: Any, rest: Any, triangles: Any, weights: Any,
                       regions: Any, names: Any, attachments: Any, *,
                       ownership_profile=None, prepared_skin=None,
                       expected_frame_count=None) -> dict[str, Any]:
    device = animated.device if isinstance(animated, torch.Tensor) else torch.device("cpu")
    posed = _tensor(animated, name="animated").to(device)
    reference = _tensor(rest, name="rest").to(device)
    tri = torch.as_tensor(triangles, dtype=torch.long, device=device).clone()
    weight = _tensor(weights, name="weights").to(device)
    region = np.asarray(regions).astype(str)
    joint_names = [str(x) for x in np.asarray(names).tolist()]
    if posed.ndim != 3 or posed.shape[-1] != 3 or reference.shape != posed.shape[1:]:
        raise ValueError("animated/rest must have shapes [F,V,3]/[V,3]")
    if tri.ndim != 2 or tri.shape[1] != 3 or weight.shape != (reference.shape[0], len(joint_names)) or len(region) != reference.shape[0]:
        raise ValueError("topology, weights, regions, and names shapes disagree")
    if (tri < 0).any() or (tri >= reference.shape[0]).any() or (weight < 0).any():
        raise ValueError("invalid triangles or nonnegative weights")
    if not len(posed) or not len(reference) or not len(tri):
        raise ValueError("attachment inputs require frames, vertices, and triangles")
    if len(set(joint_names)) != len(joint_names):
        raise ValueError("joint names must be unique")
    if not torch.allclose(weight.sum(1), torch.ones(len(weight), dtype=weight.dtype, device=device), atol=1e-5, rtol=0):
        raise ValueError("weights must be normalized")
    if attachments is None:
        raise ValueError("attachments must be an explicit sequence")
    if not isinstance(attachments, (list, tuple)):
        raise ValueError("attachments must be a sequence")
    if not attachments:
        return {"schema": "attachment-quality-v1", "applicable": False, "passed": True, "attachments": []}
    edge = reference.max(0).values - reference.min(0).values
    diag = float(torch.linalg.vector_norm(edge))
    tol = 1e-5 * max(1., diag)
    stretches, valid, _ = triangle_principal_stretches(posed, reference, tri)
    has_ownership = isinstance(ownership_profile, dict) and "geometryOwnership" in ownership_profile
    physical = has_ownership or any(
        isinstance(row, dict) and row.get("interfacePolicy") == "physical_boundary" for row in attachments)
    ownership = None
    if physical:
        from geometry_ownership import validate_prepared_ownership, animated_boundary_gate
        from target_asset import load_target_asset
        if not isinstance(ownership_profile, dict) or "geometryOwnership" not in ownership_profile or not isinstance(prepared_skin, dict):
            raise ValueError("physical_boundary requires source-pinned ownership profile and prepared skin")
        if list(attachments) != list(ownership_profile.get("rigidAttachments", ())):
            raise ValueError("physical_boundary descriptors differ from authored profile")
        validate_prepared_ownership(ownership_profile, prepared_skin)
        for actual, key in ((tri.cpu().numpy(), "triangles"), (region, "regions"), (joint_names, "names")):
            if not np.array_equal(actual, prepared_skin[key]):
                raise ValueError(f"physical_boundary candidate differs from prepared {key}")
        ownership = load_target_asset(ownership_profile)
        closure = animated_boundary_gate(ownership_profile, prepared_skin, posed.cpu().numpy(),
                                         expected_frame_count=expected_frame_count)
    results = []
    all_pass = True
    for descriptor in attachments:
        if not isinstance(descriptor, dict):
            raise ValueError("attachment descriptor must be an object")
        name = descriptor.get("region")
        donors = descriptor.get("donorJoints")
        if not isinstance(name, str) or not name or name not in set(region):
            raise ValueError(f"attachment region is missing: {name!r}")
        if not isinstance(donors, (list, tuple)) or not donors or any(str(x) not in joint_names for x in donors):
            raise ValueError(f"attachment {name} has unknown or empty donorJoints")
        if len(set(donors)) != len(donors):
            raise ValueError("attachment donors must be unique")
        vertex_mask = torch.as_tensor(region == name, device=device)
        face_region = vertex_mask[tri]
        part_faces = face_region.all(1)
        boundary_faces = face_region.any(1) & ~part_faces
        donor_ids = [joint_names.index(str(x)) for x in donors]
        donor_mass = weight[:, donor_ids].sum(1)
        donor_touched = donor_mass > 1e-8
        partial_owner = donor_mass < (1.0 - 1e-8)
        mixed_faces = donor_touched[tri].any(1) & (partial_owner[tri].any(1) | ~donor_touched[tri].all(1))
        boundary = boundary_faces | mixed_faces
        declared = descriptor.get("interfacePolicy", "mixed_influence")
        if declared not in ("mixed_influence", "physical_boundary"):
            raise ValueError(f"unknown attachment interfacePolicy: {declared!r}")
        if has_ownership:
            if "interfacePolicy" in descriptor and declared != "physical_boundary":
                raise ValueError("geometry ownership requires physical_boundary interfaces")
            policy = "physical_boundary"
        else:
            policy = declared
        broad_boundary = boundary.clone()
        interface = None
        gap_max = None
        gap_pass = True
        if policy == "physical_boundary":
            interfaces = [row for row in ownership["geometryOwnershipReport"]["interfaces"] if row["region"] == name]
            if len(interfaces) != 1:
                raise ValueError(f"physical_boundary requires exactly one source interface for {name}")
            interface = interfaces[0]
            pairs = ownership["ownershipBoundaryPairs"][interface["boundaryPairIndices"]]
            # Only source-replayed split endpoints define the physical interface.
            # Hand influence elsewhere in the body is a separate strain diagnostic.
            endpoints = sorted({int(v) for pair in pairs for v in pair if region[v] != name})
            endpoint_mask = torch.zeros(len(region), dtype=torch.bool, device=device)
            endpoint_mask[endpoints] = True
            boundary = endpoint_mask[tri].any(1) & ~part_faces
            if interface["interfaceMode"] == "split_shared" and (not len(pairs) or not bool(boundary.any())):
                raise ValueError(f"physical_boundary {name} has no complete split interface faces")
            gap_max = float(np.linalg.norm(posed.cpu().numpy()[:, pairs[:, 0]] - posed.cpu().numpy()[:, pairs[:, 1]], axis=-1).max()) if len(pairs) else None
            gap_pass = gap_max is None or gap_max <= closure["maxBoundaryGap"]
        part_ids = torch.nonzero(vertex_mask, as_tuple=False).reshape(-1)
        if len(part_ids) == 0:
            raise ValueError(f"attachment {name} has no vertices")
        residuals = torch.stack([_kabsch_residual(reference[part_ids], posed[f, part_ids]) for f in range(len(posed))])
        rigid_max = float(residuals.max())
        boundary_values = stretches[:, boundary].amax(-1) if bool(boundary.any()) else torch.empty((len(posed), 0), dtype=stretches.dtype, device=device)
        boundary_valid = valid[boundary]
        valid_values = boundary_values[:, boundary_valid].reshape(-1)
        compression = stretches[:, boundary & valid].amin(-1) < 0.67
        compression_fraction = float(compression.float().mean()) if compression.numel() else 0.0
        exposure = int((~vertex_mask & donor_touched).sum())
        per_frame_p95 = [float(torch.quantile(boundary_values[f, boundary_valid], .95)) if bool(boundary_valid.any()) else None for f in range(len(posed))]
        per_frame_compression = [float(compression[f].float().mean()) if compression.shape[1] else 0.0 for f in range(len(posed))]
        interface_pass = not bool(boundary.any()) or (
            bool(boundary_valid.any()) and all(value is not None and value <= 1.5 for value in per_frame_p95)
            and all(value <= .05 for value in per_frame_compression))
        passed = rigid_max <= tol and interface_pass and gap_pass
        all_pass &= passed
        results.append({"region": name, "donorJoints": [str(x) for x in donors], "vertexCount": int(len(part_ids)), "partFaceCount": int(part_faces.sum()), "boundaryFaceCount": int(boundary.sum()), "rigidFitMaxResidual": rigid_max, "rigidTolerance": tol, "interfaceStretchP95": float(torch.quantile(valid_values, .95)) if len(valid_values) else None, "interfaceStretchP95PerFrame": per_frame_p95, "compressionViolationFraction": compression_fraction, "compressionViolationFractionPerFrame": per_frame_compression, "donorInfluenceOutsidePartVertexCount": exposure, "passed": bool(passed)})
        results[-1].update(interfacePolicy=policy, mixedInfluenceDiagnosticFaceCount=int(broad_boundary.sum()))
        broad_values = stretches[:, broad_boundary & valid]
        results[-1]["mixedInfluenceDiagnostic"] = {
            "stretchP95PerFrame": [float(torch.quantile(row.amax(-1), .95)) if len(row) else None for row in broad_values],
            "compressionFractionPerFrame": [float((row.amin(-1) < .67).double().mean()) if len(row) else 0.0 for row in broad_values],
            "gatesExport": policy == "mixed_influence"}
        if interface is not None:
            results[-1].update(interfaceMode=interface["interfaceMode"], boundaryPairCount=len(pairs),
                boundaryMaxDistance=gap_max, maxBoundaryGap=closure["maxBoundaryGap"], boundaryPassed=gap_pass,
                interfaceApplicable=bool(len(pairs)), contactProven=False,
                ownershipSidecarSha256=ownership_profile["geometryOwnership"]["sha256"], frameCount=len(posed))
    return {"schema": "attachment-quality-v1", "applicable": True, "passed": bool(all_pass), "attachments": results}


__all__ = ["attachment_quality"]
