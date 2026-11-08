"""Diagnostic source-fit/deformation conflicts, not correction authorization."""
from __future__ import annotations

import numpy as np


TOLERANCE = 1e-6
MIN_STRETCH = 0.67
MAX_STRETCH = 1.5
MIN_COVERAGE_RATIO = 0.5


def detect_conflicts(*, baseline_iou, candidate_iou, baseline_stretches,
                    candidate_stretches, valid_faces, visible_face_error,
                    candidate_visible_face_error,
                    visible_face_coverage, candidate_visible_face_coverage,
                    triangles):
    """Find repeated image gains coupled to worse visible-face deformation.

    Tolerances are diagnostic defaults, not calibrated quality acceptance.
    Source residuals without a visible face owner must not populate
    ``visible_face_error``. Candidate trials are supplied explicitly by caller.
    Errors are means per covered pixel. Coverage loss is not matching evidence;
    a trial retains at least half of that face's baseline visible coverage.
    """
    baseline = np.asarray(baseline_iou, dtype=np.float64)
    candidates = np.asarray(candidate_iou, dtype=np.float64)
    rest = np.asarray(baseline_stretches, dtype=np.float64)
    proposals = np.asarray(candidate_stretches, dtype=np.float64)
    valid = np.asarray(valid_faces)
    error = np.asarray(visible_face_error, dtype=np.float64)
    candidate_error = np.asarray(candidate_visible_face_error, dtype=np.float64)
    coverage = np.asarray(visible_face_coverage, dtype=np.float64)
    candidate_coverage = np.asarray(candidate_visible_face_coverage, dtype=np.float64)
    faces = np.asarray(triangles)
    if baseline.ndim != 1 or not len(baseline):
        raise ValueError("baseline_iou must be nonempty [F]")
    frames = len(baseline)
    if candidates.ndim != 2 or candidates.shape[1] != frames:
        raise ValueError("candidate_iou must be [C,F]")
    if faces.ndim != 2 or faces.shape[1] != 3 or not len(faces):
        raise ValueError("triangles must be nonempty [T,3]")
    if not np.issubdtype(faces.dtype, np.integer) or np.any(faces < 0):
        raise ValueError("triangles must contain nonnegative integer vertex IDs")
    count = len(faces)
    if valid.shape != (count,) or valid.dtype != np.bool_:
        raise ValueError("valid_faces must be boolean [T]")
    if rest.shape != (frames, count, 2):
        raise ValueError("baseline_stretches must be [F,T,2]")
    if proposals.shape != (len(candidates), frames, count, 2):
        raise ValueError("candidate_stretches must be [C,F,T,2]")
    if error.shape != (frames, count) or not np.isfinite(error).all() or np.any(error < 0):
        raise ValueError("visible_face_error must be finite nonnegative [F,T]")
    if (candidate_error.shape != (len(candidates), frames, count)
            or not np.isfinite(candidate_error).all() or np.any(candidate_error < 0)):
        raise ValueError("candidate_visible_face_error must be finite nonnegative [C,F,T]")
    if coverage.shape != (frames, count) or not np.isfinite(coverage).all() or np.any(coverage < 0):
        raise ValueError("visible_face_coverage must be finite nonnegative [F,T]")
    if (candidate_coverage.shape != (len(candidates), frames, count)
            or not np.isfinite(candidate_coverage).all() or np.any(candidate_coverage < 0)):
        raise ValueError("candidate_visible_face_coverage must be finite nonnegative [C,F,T]")
    if (not np.isfinite(baseline).all() or not np.isfinite(candidates).all()
            or np.any((baseline < 0) | (baseline > 1))
            or np.any((candidates < 0) | (candidates > 1))):
        raise ValueError("IoU values must be finite in [0,1]")
    for values in (rest[:, valid], proposals[:, :, valid]):
        if not np.isfinite(values).all() or np.any(values < 0):
            raise ValueError("valid-face stretches must be finite and nonnegative")

    # Compare compression and stretch separately so one cannot hide the other.
    def violations(values):
        return np.stack((np.maximum(MIN_STRETCH - values, 0).max(axis=-1),
                         np.maximum(values - MAX_STRETCH, 0).max(axis=-1)), axis=-1)

    increase = (violations(proposals) - violations(rest)[None] > TOLERANCE).any(axis=-1)
    gain = candidates - baseline[None] > TOLERANCE
    face_gain = error[None] - candidate_error > TOLERANCE
    coverage_lost = ((coverage[None] > 0)
                     & (candidate_coverage < MIN_COVERAGE_RATIO * coverage[None]))
    coverage_ok = (coverage[None] > 0) & ~coverage_lost
    votes = (increase & gain[:, :, None] & valid[None, None]
             & (error[None] > 0) & face_gain & coverage_ok)
    vote_count = votes.sum(axis=0)
    repeated = vote_count >= 2
    selected = np.flatnonzero(repeated.any(axis=0)).tolist()

    # Connectivity is topological: sharing a source vertex, never spatial proximity.
    by_vertex = {}
    for face in selected:
        for vertex in faces[face]:
            by_vertex.setdefault(int(vertex), []).append(face)
    remaining = set(selected)
    components = []
    while remaining:
        seed = min(remaining)
        remaining.remove(seed)
        queue, component = [seed], []
        while queue:
            face = queue.pop()
            component.append(face)
            for vertex in faces[face]:
                for neighbor in by_vertex[int(vertex)]:
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        queue.append(neighbor)
        components.append(sorted(component))
    per_frame = []
    for frame in range(frames):
        ids = np.flatnonzero(repeated[frame]).tolist()
        classification = ("unresolved_insufficient_trials" if len(candidates) < 2 else
                          "suspected_pose_deformation_conflict" if ids else
                          "no_repeated_conflict_observed")
        per_frame.append({"frame": frame, "classification": classification,
                          "conflictFaceIds": ids,
                          "coverageLossExcludedFaceIdsByCandidate": {
                              str(candidate): np.flatnonzero(coverage_lost[candidate, frame] & valid).tolist()
                              for candidate in range(len(candidates))},
                          "supportingCandidateIdsByFace": {
                              str(face): np.flatnonzero(votes[:, frame, face]).tolist()
                              for face in ids}})
    return {"schema": "pose-representation-exception-v3", "perFrame": per_frame,
            "candidateCount": len(candidates), "repeatedConflictFaceIds": selected,
            "faceComponents": components,
            "correctionVertexIds": sorted(set(int(v) for face in selected for v in faces[face])),
            "automaticCorrectionAuthorized": False, "provesRepresentationImpossible": False,
            "visibleFaceErrorMetric": "mean_error_per_covered_pixel",
            "lostCoverageExcludedFaceIds": np.flatnonzero(
                coverage_lost.any(axis=(0, 1)) & valid).tolist(),
            "thresholds": {"imageGain": TOLERANCE, "visibleFaceErrorDecrease": TOLERANCE,
                           "violationIncrease": TOLERANCE,
                           "minStretch": MIN_STRETCH, "maxStretch": MAX_STRETCH,
                           "minimumCoverageRatio": MIN_COVERAGE_RATIO,
                           "minimumTrials": 2, "calibratedQualityAcceptance": False}}
