"""Align source capture into the fitted bind frame before retargeting.

This is an explicit opt-in wrapper around :func:`reconstruct_adapted`.  The
source reference and every source frame are rotated and translated together;
the fitted target is never changed.  Keeping this operation outside the
existing retargeter makes the coordinate-gauge choice visible in reports.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from donor_eagle import compute_rest_joints
from reconstruct_adapted import reconstruct_adapted, whole_body_rotation


def reconstruct_aligned(**kwargs: Any) -> dict[str, Any]:
    """Normalize a source capture gauge once, then call ``reconstruct_adapted``.

    The keyword contract is intentionally the same as ``reconstruct_adapted``:
    ``capture_positions``, ``capture_reference_positions``,
    ``capture_offsets``, ``fitted_offsets``, ``parents``, ``names``, and
    ``hub_names``.  Inputs are copied and are never modified in place.
    """
    required = {
        "capture_positions", "capture_reference_positions", "capture_offsets",
        "fitted_offsets", "parents", "names", "hub_names",
    }
    if set(kwargs) != required:
        missing = sorted(required - set(kwargs))
        extra = sorted(set(kwargs) - required)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("unknown " + ", ".join(extra))
        raise TypeError("reconstruct_aligned requires the reconstruct_adapted keyword contract (" + "; ".join(detail) + ")")

    capture = np.asarray(kwargs["capture_positions"], dtype=np.float64)
    source_reference = np.asarray(kwargs["capture_reference_positions"], dtype=np.float64)
    source_offsets = np.asarray(kwargs["capture_offsets"], dtype=np.float64)
    fitted_offsets = np.asarray(kwargs["fitted_offsets"], dtype=np.float64)
    raw_parents = kwargs["parents"]
    parents = np.asarray(raw_parents, dtype=np.int64)
    names = kwargs["names"]
    hub_names = kwargs["hub_names"]

    # Let the underlying implementation enforce the complete shape/finite/
    # hierarchy contract, while rejecting malformed arrays before alignment.
    if source_reference.ndim != 2 or source_reference.shape[1:] != (3,):
        raise ValueError("capture reference must have shape [J,3]")
    if capture.ndim != 3 or capture.shape[1:] != source_reference.shape or len(capture) == 0:
        raise ValueError("capture must have nonempty shape [T,J,3]")
    if source_offsets.shape != source_reference.shape:
        raise ValueError("source offsets must have shape [J,3]")
    if fitted_offsets.shape != source_reference.shape:
        raise ValueError("fitted and source offsets must have the same [J,3] shape")
    if np.asarray(raw_parents).ndim != 1 or not np.array_equal(parents, raw_parents):
        raise ValueError("parents must be an integer vector")
    if len(parents) == 0 or int(parents[0]) != -1 or any(int(p) < 0 or int(p) >= i for i, p in enumerate(parents[1:], 1)):
        raise ValueError("parents must be root-first and ordered")
    if len(parents) != len(source_reference):
        raise ValueError("parents and capture reference must have the same joint count")
    if len(names) != len(parents) or len(set(names)) != len(names):
        raise ValueError("names must be unique and match the joint count")
    if len(set(hub_names)) != len(hub_names) or len(hub_names) < 3 or any(name not in names for name in hub_names):
        raise ValueError("hub_names must contain at least three unique known joints")
    if not np.isfinite(source_reference).all() or not np.isfinite(source_offsets).all() or not np.isfinite(fitted_offsets).all():
        raise ValueError("alignment inputs must be finite")

    source_hubs = source_reference[[names.index(name) for name in hub_names]]
    fitted_rest = compute_rest_joints(fitted_offsets, parents)
    target_hubs = fitted_rest[[names.index(name) for name in hub_names]]
    if np.linalg.matrix_rank(source_hubs - source_hubs.mean(axis=0)) < 2 or np.linalg.matrix_rank(target_hubs - target_hubs.mean(axis=0)) < 2:
        raise ValueError("alignment hubs must span rank-2 geometry")
    source_rotation = whole_body_rotation(source_reference, fitted_rest, names, hub_names)
    source_root = source_reference[0]
    target_root = fitted_rest[0]

    # Translate about the source reference root, then apply the single gauge
    # rotation.  Offsets are vectors and therefore receive no translation.
    aligned_capture = np.einsum("ij,tfj->tfi", source_rotation, capture - source_root) + target_root
    aligned_reference = np.einsum("ij,kj->ki", source_rotation, source_reference - source_root) + target_root
    aligned_offsets = np.einsum("ij,kj->ki", source_rotation, source_offsets)

    result = reconstruct_adapted(
        capture_positions=aligned_capture,
        capture_reference_positions=aligned_reference,
        capture_offsets=aligned_offsets,
        fitted_offsets=fitted_offsets,
        parents=parents,
        names=names,
        hub_names=hub_names,
    )
    result.update({
        "sourceWholeBodyRotation": source_rotation,
        "sourceReferenceRoot": source_root.copy(),
        "fittedReferenceRoot": target_root.copy(),
        "alignedCapture": aligned_capture,
        "alignedCaptureReference": aligned_reference,
        "alignedCaptureOffsets": aligned_offsets,
        "originalCapturePositions": capture.copy(),
        "originalCaptureReferencePositions": source_reference.copy(),
        "originalCaptureOffsets": source_offsets.copy(),
        "alignmentPolicy": "source_reference_to_fitted_rest_once",
    })
    return result
