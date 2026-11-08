"""Audit per-frame skinned deformation without changing the mocap fit.

This is a read-only diagnostic for generated candidates.  It replays the
serialized animation, groups vertices by their dominant joint, and reports
regions whose motion is unusually small while their surface strain is high.
The result is evidence for a later reviewed weight edit; it never edits a GLB,
changes captured joints, or searches for a better camera pose.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import torch

from eagle_glb import gltf_world_matrices
from glb_skeleton import load_bind_skeleton
from mesh_preview import skin_vertices
from skin_surface_constraints import triangle_principal_stretches
from verify_calibrated_export import _serialized_local_rotations


SCHEMA = "homm3.mocap-frame-deformation-audit.v1"
_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def _semantic_region(name: str) -> str:
    """Map a joint label to a conservative, species-independent region."""
    token = _TOKEN_RE.sub("", str(name).lower())
    if any(value in token for value in ("wing", "feather")):
        return "wing"
    if any(value in token for value in ("tail",)):
        return "tail"
    if any(value in token for value in ("head", "neck", "jaw", "face")):
        return "head_neck"
    if any(value in token for value in ("arm", "forearm", "hand", "shoulder", "clavicle")):
        return "upper_limb"
    if any(value in token for value in ("leg", "upleg", "thigh", "calf", "shin", "foot", "toe")):
        return "lower_limb"
    if any(value in token for value in ("spine", "chest", "hip", "pelvis", "root")):
        return "torso"
    return "other"


def _percentile(values: np.ndarray, quantile: float) -> float:
    values = np.asarray(values, dtype=np.float64)
    return float(np.quantile(values, quantile)) if values.size else 0.0


def audit_deformation_arrays(
    *,
    names: list[str] | tuple[str, ...],
    vertex_joints: np.ndarray,
    vertex_weights: np.ndarray,
    triangles: np.ndarray,
    rest_vertices: np.ndarray,
    posed_vertices: np.ndarray,
) -> dict[str, Any]:
    """Compute region diagnostics from a replayed animation stack."""
    rest = np.asarray(rest_vertices, dtype=np.float64)
    posed = np.asarray(posed_vertices, dtype=np.float64)
    joints = np.asarray(vertex_joints, dtype=np.int64)
    weights = np.asarray(vertex_weights, dtype=np.float64)
    tri = np.asarray(triangles, dtype=np.int64)
    if rest.ndim != 2 or rest.shape[1] != 3:
        raise ValueError("rest_vertices must have shape [V,3]")
    if posed.ndim != 3 or posed.shape[1:] != rest.shape:
        raise ValueError("posed_vertices must have shape [F,V,3]")
    if joints.ndim != 2 or joints.shape[0] != len(rest) or weights.shape != joints.shape:
        raise ValueError("vertex joints/weights do not match rest vertices")
    if tri.ndim != 2 or tri.shape[1] != 3 or np.any(tri < 0) or np.any(tri >= len(rest)):
        raise ValueError("triangles must have shape [T,3] and valid indices")
    if len(names) == 0 or np.any(joints >= len(names)):
        raise ValueError("joint labels do not match vertex joints")
    if not np.isfinite(rest).all() or not np.isfinite(posed).all():
        raise ValueError("deformation arrays contain non-finite values")

    dominant = joints[np.arange(len(joints)), np.argmax(weights, axis=1)]
    joint_regions = [_semantic_region(name) for name in names]
    vertex_regions = np.asarray([joint_regions[int(index)] for index in dominant], dtype=object)
    region_names = sorted(set(vertex_regions.tolist()))

    from_rest = np.linalg.norm(posed - posed[0:1], axis=2)
    from_previous = np.zeros_like(from_rest)
    if len(posed) > 1:
        from_previous[1:] = np.linalg.norm(posed[1:] - posed[:-1], axis=2)
    global_motion = float(np.mean(from_previous[1:])) if len(posed) > 1 else 0.0
    global_motion_floor = max(global_motion * 0.25, 1e-8)

    # Triangle labels use the dominant joint of their vertices.  This keeps
    # strain attribution conservative at seams instead of inventing masks.
    tri_regions = np.asarray([
        max((vertex_regions[int(index)] for index in face), key=lambda value: sum(vertex_regions[int(i)] == value for i in face))
        for face in tri
    ], dtype=object)
    rest_t = torch.as_tensor(rest, dtype=torch.float32)
    posed_t = torch.as_tensor(posed, dtype=torch.float32)
    stretches, valid, _ = triangle_principal_stretches(posed_t, rest_t, torch.as_tensor(tri, dtype=torch.long))
    stretch = stretches.detach().cpu().numpy()
    valid_np = valid.detach().cpu().numpy().astype(bool)
    region_rows: dict[str, dict[str, Any]] = {}
    for region in region_names:
        vertex_mask = vertex_regions == region
        tri_mask = (tri_regions == region) & valid_np
        region_strain = stretch[:, tri_mask] if np.any(tri_mask) else np.empty((len(posed), 0, 2), dtype=np.float64)
        strain_max = region_strain.max(axis=2) if region_strain.size else np.empty((len(posed), 0))
        compression = region_strain.min(axis=2) if region_strain.size else np.empty((len(posed), 0))
        motion = from_previous[:, vertex_mask]
        displacement = from_rest[:, vertex_mask]
        frame_strain_p95 = [_percentile(frame, .95) for frame in strain_max] if strain_max.size else [1.0] * len(posed)
        frame_violation = [float(np.mean((frame > 1.5) | (comp < .67))) for frame, comp in zip(strain_max, compression)] if strain_max.size else [0.0] * len(posed)
        frame_motion = [float(np.mean(frame)) if len(frame) else 0.0 for frame in motion]
        strain_p95 = float(max(frame_strain_p95))
        violation_fraction = float(np.mean(frame_violation))
        motion_energy = float(np.mean(motion[1:])) if len(posed) > 1 and motion.size else 0.0
        worst_frame = int(np.argmax(frame_strain_p95))
        per_frame = [
            {"frame": index, "motionEnergy": frame_motion[index],
             "surfaceStrainP95": float(frame_strain_p95[index]),
             "surfaceViolationFraction": float(frame_violation[index])}
            for index in range(len(posed))
        ]
        row = {
            "vertexCount": int(vertex_mask.sum()),
            "triangleCount": int(tri_mask.sum()),
            "motionEnergy": motion_energy,
            "displacementP95": _percentile(displacement, .95),
            "displacementMax": float(displacement.max()) if displacement.size else 0.0,
            "surfaceStrainP95": strain_p95,
            "surfaceViolationFraction": violation_fraction,
            "worstFrame": worst_frame,
            "worstFrameSurfaceStrainP95": float(frame_strain_p95[worst_frame]),
            "highStrain": bool(strain_p95 > 1.5 or violation_fraction > .05),
            "perFrame": per_frame,
            "lowMotionHighStrain": bool(motion_energy <= global_motion_floor and strain_p95 > 1.5),
        }
        region_rows[region] = row

    flagged = [name for name, row in region_rows.items() if row["lowMotionHighStrain"]]
    return {
        "schema": SCHEMA,
        "proof": "generated-candidate diagnostic",
        "frameCount": int(len(posed)),
        "vertexCount": int(len(rest)),
        "triangleCount": int(len(tri)),
        "globalMotionEnergy": global_motion,
        "lowMotionThreshold": global_motion_floor,
        "regions": region_rows,
        "flaggedRegions": flagged,
        "policy": "diagnostic-only; no mesh, joint, camera, or captured-motion edits",
    }


def audit_candidate(glb: Path) -> dict[str, Any]:
    """Replay one serialized candidate and return a read-only audit."""
    skeleton = load_bind_skeleton(glb)
    if skeleton.vertices is None or skeleton.vertex_joints is None or skeleton.vertex_weights is None or skeleton.triangles is None:
        raise ValueError(f"{glb}: candidate lacks a complete skinned primitive")
    times, rotations, translations, channel_info = _serialized_local_rotations(glb)
    parents = np.asarray(skeleton.parents, dtype=np.int64)
    posed = []
    for frame in range(len(times)):
        # Rotation-only exports carry a broadcast translation stack for the
        # verifier; glTF FK consumes one [J,3] local-translation frame.
        worlds = gltf_world_matrices(
            local_rotation=rotations[frame],
            local_translation=skeleton.rest_local_translation,
            parents=parents,
        )
        posed.append(skin_vertices(skeleton, worlds))
    result = audit_deformation_arrays(
        names=skeleton.names,
        vertex_joints=skeleton.vertex_joints,
        vertex_weights=skeleton.vertex_weights,
        triangles=skeleton.triangles,
        rest_vertices=skeleton.vertices,
        posed_vertices=np.stack(posed),
    )
    result["glb"] = glb.as_posix()
    result["channelInfo"] = channel_info
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--glb", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = audit_candidate(args.glb.resolve())
    payload = json.dumps(result, indent=2) + "\n"
    if args.out:
        args.out.resolve().parent.mkdir(parents=True, exist_ok=True)
        args.out.resolve().write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
