"""Diagnostic-only separation of body rotation from articulated capture motion."""
import numpy as np

from direction_retarget import kabsch_rotation
from reconstruct_adapted import reconstruct_adapted

MIN_HUB_SPREAD_RATIO = 1e-6


def reconstruct_body_relative(**kwargs):
    names = list(kwargs["names"])
    hubs = list(kwargs["hub_names"])
    if (len(hubs) < 3 or not all(isinstance(name, str) for name in hubs)
            or len(set(hubs)) != len(hubs) or any(name not in names for name in hubs)):
        raise ValueError("body rotation requires at least three distinct known hub names")
    # The existing consumer validates the complete input contract first.
    baseline = reconstruct_adapted(**kwargs)
    capture = np.asarray(kwargs["capture_positions"], dtype=np.float64)
    reference = np.asarray(kwargs["capture_reference_positions"], dtype=np.float64)
    indices = [names.index(name) for name in hubs]
    reference_hubs = reference[indices] - reference[indices].mean(axis=0)
    def spread(points):
        singular = np.linalg.svd(points, compute_uv=False)
        ratio = float(singular[1] / max(singular[0], 1e-15))
        if ratio < MIN_HUB_SPREAD_RATIO:
            raise ValueError("body hubs are collinear or numerically ill-conditioned")
        return ratio
    reference_spread = spread(reference_hubs)
    reference_radius = float(np.sqrt(np.mean(np.sum(reference_hubs**2, axis=1))))
    rotations, spread_ratios, fit_residuals = [], [], []
    for frame in capture:
        posed_hubs = frame[indices] - frame[indices].mean(axis=0)
        spread_ratios.append(spread(posed_hubs))
        rotation = kabsch_rotation(reference_hubs, posed_hubs)
        rotations.append(rotation)
        error = reference_hubs @ rotation.T - posed_hubs
        fit_residuals.append(float(np.sqrt(np.mean(np.sum(error**2, axis=1))) / reference_radius))
    body = np.stack(rotations)
    residual_capture = np.einsum("tji,tkj->tki", body, capture - capture[:, :1]) + reference[0]
    residual_args = dict(kwargs, capture_positions=residual_capture)
    residual = reconstruct_adapted(**residual_args)
    gauge = baseline["wholeBodyRotation"]
    target_body = gauge[None] @ body @ gauge.T[None]
    root = baseline["fittedRest"][0]
    travel = (capture[:, 0] - reference[0]) @ gauge.T
    world = residual["jointWorld"].copy()
    world[:, :, :3, :3] = target_body[:, None] @ world[:, :, :3, :3]
    world[:, :, :3, 3] = np.einsum("tij,tkj->tki", target_body,
        residual["positions"] - root) + root + travel[:, None]
    local = residual["localRotation"].copy()
    local[:, 0] = target_body @ local[:, 0]
    positions = world[:, :, :3, 3]
    parents = np.asarray(kwargs["parents"])
    lengths = np.linalg.norm(positions[:, 1:] - positions[:, parents[1:]], axis=-1)
    rest_lengths = np.linalg.norm(np.asarray(kwargs["fitted_offsets"])[1:], axis=-1)
    steps = body[1:] @ body[:-1].swapaxes(-1, -2)
    step_degrees = np.rad2deg(np.arccos(np.clip((np.trace(steps, axis1=1, axis2=2)-1)/2, -1, 1)))
    return {
        "jointWorld": world, "positions": positions, "localRotation": local,
        "localTranslation": residual["localTranslation"].copy(),
        "captureRest": reference.copy(), "fittedRest": baseline["fittedRest"].copy(),
        "wholeBodyRotation": gauge.copy(), "captureBodyRotation": body,
        "targetBodyRotation": target_body,
        "fixedLengthErrorMax": float(np.abs(lengths - rest_lengths).max()),
        "clipFrame0IsBind": bool(np.max(np.abs(local[0] - np.eye(3))) < 1e-5
            and np.max(np.abs(positions[0] - baseline["fittedRest"])) < 1e-5),
        "motionOwner": "diagnostic_body_relative_capture",
        "bodyHubNames": hubs, "accepted": False,
        # Articulated hub motion is measured, not claimed to be rigid or smoothed away.
        "bodyDiagnostics": {"referenceSpreadRatio": reference_spread,
            "minimumAllowedSpreadRatio": MIN_HUB_SPREAD_RATIO,
            "frameSpreadRatios": spread_ratios, "relativeRigidFitRms": fit_residuals,
            "rotationStepDegrees": step_degrees.tolist(), "rigidHubAssumptionValidated": False},
    }
