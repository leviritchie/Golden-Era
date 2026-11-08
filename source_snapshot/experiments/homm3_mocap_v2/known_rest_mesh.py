"""Load a rest-pose triangle surface and place it on capture rest joints.

The source GLB may carry a foreign skeleton. Those joints and weights are
discarded. Capture mocap owns articulation. Alignment is one uniform scale
plus translation from bounding boxes; rotation stays identity.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from glb_skeleton import load_bind_skeleton
from pin import sha256_file


class KnownMeshError(ValueError):
    """Raised when a rest-pose surface cannot be used as an initializer."""


def load_rest_surface(path: Path) -> dict[str, Any]:
    glb = Path(path)
    if not glb.is_file():
        raise KnownMeshError(f"rest-pose mesh is missing: {glb}")
    skeleton = load_bind_skeleton(glb)
    if skeleton.vertices is None or skeleton.triangles is None:
        raise KnownMeshError(f"{glb} has no triangle surface")
    vertices = np.asarray(skeleton.vertices, dtype=np.float64)
    triangles = np.asarray(skeleton.triangles, dtype=np.int32)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) < 32:
        raise KnownMeshError(f"{glb} surface is too small: {vertices.shape}")
    if triangles.ndim != 2 or triangles.shape[1] != 3 or len(triangles) < 32:
        raise KnownMeshError(f"{glb} has too few triangles: {triangles.shape}")
    if int(triangles.min()) < 0 or int(triangles.max()) >= len(vertices):
        raise KnownMeshError(f"{glb} triangle indices leave the vertex array")
    return {
        "path": glb,
        "sha256": sha256_file(glb),
        "vertices": vertices,
        "triangles": triangles,
        "sourceJointCount": int(len(skeleton.names)),
        "discardedSourceSkin": True,
        "discardedSourceJointNames": True,
    }


def align_surface_to_rest(vertices: np.ndarray, rest_joints: np.ndarray) -> dict[str, Any]:
    mesh = np.asarray(vertices, dtype=np.float64)
    rest = np.asarray(rest_joints, dtype=np.float64)
    if mesh.ndim != 2 or mesh.shape[1] != 3 or rest.ndim != 2 or rest.shape[1] != 3:
        raise KnownMeshError("mesh and rest joints must be [N,3]")
    if len(rest) < 2:
        raise KnownMeshError("need at least two rest joints to place a mesh")
    mesh_lo = mesh.min(axis=0)
    mesh_hi = mesh.max(axis=0)
    rest_lo = rest.min(axis=0)
    rest_hi = rest.max(axis=0)
    mesh_span = float(np.max(mesh_hi - mesh_lo))
    rest_span = float(np.max(rest_hi - rest_lo))
    if mesh_span < 1e-8 or rest_span < 1e-8:
        raise KnownMeshError("mesh or rest-joint span is degenerate")
    scale = rest_span / mesh_span
    mesh_c = 0.5 * (mesh_lo + mesh_hi)
    rest_c = 0.5 * (rest_lo + rest_hi)
    rotation = np.eye(3, dtype=np.float64)
    translation = rest_c - scale * (rotation @ mesh_c)
    aligned = scale * (mesh @ rotation.T) + translation
    return {
        "vertices": aligned,
        "scale": float(scale),
        "rotation": rotation,
        "translation": translation,
        "det": float(np.linalg.det(rotation)),
        "policy": "aabb_uniform_scale_translate",
    }
