"""Diagnostic local-rotation capture transfer (not a production selector).

This experiment first reconstructs capture locals on the capture reference
skeleton, then transports every local rotation through one static bind-frame
rotation.  It deliberately does not solve each target frame independently.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from donor_eagle import compute_rest_joints
from mesh_preview import fk_world_matrices
from reconstruct_adapted import reconstruct_adapted, whole_body_rotation


def reconstruct_local_rotation(
    *,
    capture_positions: np.ndarray,
    capture_reference_positions: np.ndarray,
    capture_offsets: np.ndarray,
    fitted_offsets: np.ndarray,
    parents: np.ndarray,
    names: list[str],
    hub_names: tuple[str, ...],
) -> dict[str, Any]:
    """Transfer capture local rotations through a single static bind rotation.

    Source locals come from the existing same-reference reconstruction, including
    its existing regularization policy. Only target transfer changes.
    """
    capture = np.asarray(capture_positions, dtype=np.float64)
    reference = np.asarray(capture_reference_positions, dtype=np.float64)
    cap_off = np.asarray(capture_offsets, dtype=np.float64)
    fit_off = np.asarray(fitted_offsets, dtype=np.float64)
    parent = np.asarray(parents)
    if parent.ndim != 1 or parent.dtype.kind not in 'iu' or not len(parent):
        raise ValueError('parents must be nonempty integer indices')
    parent = parent.astype(np.int64)
    joint_count = len(parent)
    if parent[0] != -1 or any(p < 0 or p >= i for i, p in enumerate(parent[1:], 1)):
        raise ValueError('parents must be root-first and ordered')
    if reference.shape != (joint_count, 3) or len(names) != joint_count or len(set(names)) != joint_count:
        raise ValueError('reference and unique names must match hierarchy')
    if not hub_names or any(h not in names for h in hub_names):
        raise ValueError('hub names must exist in hierarchy')
    if fit_off.shape != (joint_count, 3) or not np.isfinite(fit_off).all():
        raise ValueError("fitted_offsets must be finite [J,3]")

    # Reuse the established structural validation, including coincident hubs.
    source_offsets = reference - reference[parent.clip(0)]
    source_offsets[0] = reference[0]
    source = reconstruct_adapted(
        capture_positions=capture,
        capture_reference_positions=reference,
        capture_offsets=cap_off,
        fitted_offsets=source_offsets,
        parents=parent,
        names=names,
        hub_names=hub_names,
    )

    capture_rest = reference.copy()
    fitted_rest = compute_rest_joints(fit_off, parent)
    static_q = whole_body_rotation(capture_rest, fitted_rest, names, hub_names)

    source_local = source['localRotation']
    local_rotation = np.einsum("ij,tfjk,lk->tfil", static_q, source_local, static_q)
    # The target root follows the raw capture root displacement, transported by Q.
    root_world = fitted_rest[0] + np.einsum("ij,fj->fi", static_q, capture[:, 0] - reference[0])
    local_translation = np.repeat(fit_off[None, :, :], len(capture), axis=0).copy()
    local_translation[:, 0] = 0.0
    joint_world = np.stack(
        [
            fk_world_matrices(
                local_rotation=local_rotation[frame],
                local_translation=local_translation[frame],
                parents=parent,
                root_world=root_world[frame],
            )
            for frame in range(len(capture))
        ]
    )
    positions = joint_world[:, :, :3, 3]
    lengths = np.linalg.norm(positions - positions[:, parent.clip(0)], axis=-1)
    rest_lengths = np.linalg.norm(fit_off, axis=1)
    nonroot = parent >= 0
    fixed_length_error = np.abs(lengths[:, nonroot] - rest_lengths[nonroot])
    local_bind = float(np.max(np.abs(local_rotation[0] - np.eye(3)[None])))
    pos_bind = float(np.max(np.linalg.norm(positions[0] - fitted_rest, axis=-1)))
    return {
        "localRotation": local_rotation,
        "localTranslation": local_translation,
        "jointWorld": joint_world,
        "positions": positions,
        "fixedLengthErrorMax": float(fixed_length_error.max()) if fixed_length_error.size else 0.0,
        "clipFrame0IsBind": bool(local_bind < 1e-5 and pos_bind < 1e-5),
        "staticBindRotation": static_q,
        "sourceLocalRotation": source_local,
        "fittedRest": fitted_rest,
        "diagnosticOnly": True,
        "notProductionSelector": True,
    }
