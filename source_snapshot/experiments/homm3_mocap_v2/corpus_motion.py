"""Load explicitly typed immutable motion without reconstructing composed FK."""
from __future__ import annotations

import numpy as np

from mesh_preview import fk_world_matrices
from reconstruct_adapted import reconstruct_adapted


def load_motion(raw, entry, corpus, skin, reference, hubs):
    indices = entry["sourceIndices"]
    positions = np.asarray(raw["pred_position"], dtype=np.float64)
    if positions.ndim != 3 or positions.shape[1:] != (len(skin["names"]), 3):
        raise ValueError("motion positions must match frozen joint count")
    if list(raw["joint_names"].astype(str)) != list(skin["names"]) or not np.array_equal(raw["parents"], skin["parents"]):
        raise ValueError("motion skeleton differs from frozen skin")
    representation = corpus.get("motionRepresentation", "capture_positions_v1")
    if representation == "capture_positions_v1":
        return reconstruct_adapted(capture_positions=positions[indices],
            capture_reference_positions=reference, capture_offsets=skin["captureOffsets"],
            fitted_offsets=skin["offsets"], parents=skin["parents"], names=skin["names"], hub_names=tuple(hubs))
    if representation != "fixed_composed_fk_v1":
        raise ValueError(f"unsupported motion representation: {representation}")
    if not np.array_equal(raw["offsets"], skin["offsets"]):
        raise ValueError("composed motion bind differs from frozen skin")
    local = np.asarray(raw["local_rotation"], dtype=np.float64)
    world = np.asarray(raw["joint_world"], dtype=np.float64)
    count, joints = positions.shape[:2]
    if positions.shape != (count, joints, 3) or local.shape != (count, joints, 3, 3) or world.shape != (count, joints, 4, 4):
        raise ValueError("composed motion dimensions disagree")
    if not all(np.isfinite(value).all() for value in (positions, local, world)):
        raise ValueError("nonfinite composed motion")
    if not np.allclose(local @ local.swapaxes(-1, -2), np.eye(3), atol=1e-6) or not np.allclose(np.linalg.det(local), 1, atol=1e-6):
        raise ValueError("composed motion contains nonrigid rotations")
    offsets = np.asarray(skin["offsets"], dtype=np.float64).copy()
    root = offsets[0].copy()
    offsets[0] = 0
    rebuilt = np.asarray([fk_world_matrices(local_rotation=frame, local_translation=offsets,
        parents=skin["parents"], root_world=root) for frame in local])
    if not np.allclose(rebuilt, world, atol=1e-7) or not np.allclose(world[:, :, :3, 3], positions, atol=1e-7):
        raise ValueError("composed transforms violate frozen bind FK")
    return {"jointWorld": world[indices], "localRotation": local[indices],
            "captureRest": np.asarray(reference).copy(),
            "clipFrame0IsBind": bool(np.allclose(local[indices[0]], np.eye(3), atol=1e-7))}
