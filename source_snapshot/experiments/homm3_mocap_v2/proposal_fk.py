"""Vendor identity-rest FK mapped back into source GLB world positions."""
from __future__ import annotations

from typing import Mapping

import numpy as np

from glb_skeleton import BindSkeleton
from preview import proposal_fk_world


def rotation_fk_source_world(
    *,
    pred_rot6d: np.ndarray,
    reference: Mapping[str, np.ndarray],
    skeleton: BindSkeleton,
) -> np.ndarray:
    rot6d = np.asarray(pred_rot6d, dtype=np.float32)
    joint_count = len(skeleton.names)
    if rot6d.ndim != 3 or rot6d.shape[-1] != 6:
        raise ValueError(f"pred_rot6d must be [T,J,6], got {rot6d.shape}")
    if rot6d.shape[1] < joint_count:
        raise ValueError("pred_rot6d has fewer joints than the skeleton")
    offsets = np.asarray(reference["offset"][:joint_count], dtype=np.float32)
    parents = np.asarray(reference["parents"][:joint_count], dtype=np.int64)
    scale = float(np.asarray(reference["global_scale"]).reshape(-1)[0])
    rest_root = np.asarray(skeleton.rest_world[0], dtype=np.float64)
    source_to_model = np.asarray(reference["source_to_model"], dtype=np.float64)
    model_root = rest_root @ source_to_model.T
    model_world = proposal_fk_world(
        pred_rot6d=rot6d[:, :joint_count],
        offsets=offsets,
        parents=parents,
        global_scale=scale,
        rest_root=np.zeros(3),
    )
    return (model_world + model_root.reshape(1, 1, 3)) @ source_to_model
