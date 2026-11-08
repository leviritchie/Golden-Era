"""CPU rigid-turn counterfactual; no source animation or pipeline defaults changed."""
import argparse
import json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from asset_profiles import get_profile
from body_relative_capture_motion import reconstruct_body_relative
from aligned_capture_motion import reconstruct_aligned
from local_rotation_capture_motion import reconstruct_local_rotation
from reconstruct_adapted import reconstruct_adapted
from coincident_bind_candidate import build_candidate
from donor_eagle import skin_dense
from pin import sha256_file


def distance_drift(positions):
    values = np.asarray(positions, dtype=float)
    if values.ndim != 3 or values.shape[-1] != 3 or not len(values) or not np.isfinite(values).all():
        raise ValueError("positions must be nonempty finite [T,J,3]")
    distance = np.linalg.norm(values[:, :, None] - values[:, None, :], axis=-1)
    return float(np.abs(distance - distance[0]).max())


def audit(skin_path, registration, output):
    if output.exists():
        raise FileExistsError(output)
    report_path = registration / "pilot_report.json"
    registered = json.loads(report_path.read_text())
    if registered.get("kind") != "idle_registration_only":
        raise ValueError("expected an idle-only registration")
    if sha256_file(skin_path) != registered["inputs"]["researchSkin"]:
        raise ValueError("skin differs from registration")
    calibration_path = Path(registered["inputs"]["calibrationPath"])
    if sha256_file(calibration_path) != registered["inputs"]["calibration"]:
        raise ValueError("calibration differs from registration")
    reference = np.asarray(json.loads(calibration_path.read_text())["referencePositions"])
    with np.load(skin_path, allow_pickle=False) as data:
        skin = {key: data[key].copy() for key in data.files}
    names = list(skin["names"].astype(str))
    hubs = tuple(get_profile(registered["asset"])["wholeBodyHubs"])
    rotations = [np.eye(3)]
    labels = ["neutral"]
    for axis in range(3):
        for degrees in (-90, -45, 45, 90):
            vector = np.zeros(3)
            vector[axis] = np.deg2rad(degrees)
            rotations.append(Rotation.from_rotvec(vector).as_matrix())
            labels.append(f"{'XYZ'[axis]}{degrees:+d}")
    capture = np.einsum("tij,kj->tki", rotations, reference-reference[0]) + reference[0]
    args = dict(capture_positions=capture, capture_reference_positions=reference,
        capture_offsets=skin["captureOffsets"], fitted_offsets=skin["offsets"],
        parents=skin["parents"], names=names, hub_names=hubs)
    results = {}
    for name, reconstruct in (("current", reconstruct_adapted),
                               ("old_source_alignment", reconstruct_aligned),
                               ("body_relative", reconstruct_body_relative),
                               ("local_rotation", reconstruct_local_rotation)):
        motion = reconstruct(**args)
        drift = distance_drift(motion["positions"])
        span = float(np.linalg.norm(np.ptp(motion["fittedRest"], axis=0)))
        results[name] = {"pairDistanceChangeMax": drift, "pairDistanceChangeOverSpan": drift/span,
            "fixedBoneLengthErrorMax": motion["fixedLengthErrorMax"],
            "neutralMaxError": float(np.linalg.norm(motion["positions"][0]-motion["fittedRest"], axis=1).max())}
    offsets = reference.copy()
    offsets[1:] -= reference[skin["parents"][1:]]
    matched = reconstruct_adapted(**dict(args, fitted_offsets=offsets))
    coincident = build_candidate(skin)
    corrected = coincident['skin']
    motion = reconstruct_local_rotation(**dict(args, fitted_offsets=corrected['offsets']))
    q = motion['staticBindRotation']
    rest_root = motion['fittedRest'][0]
    expected = np.einsum('tij,vj->tvi', q @ np.asarray(rotations) @ q.T,
                         skin['vertices'] - rest_root) + rest_root
    mesh_errors = {}
    for name, weights in (('canonical_ownership', corrected['weights']), ('position_only', skin['weights'])):
        posed = np.stack([skin_dense(skin['vertices'], weights, world, corrected['inverseBind'])
                          for world in motion['jointWorld']])
        mesh_errors[name] = {'maxVertexError': float(np.linalg.norm(posed-expected, axis=-1).max()),
                             'neutralMaxVertexError': float(np.linalg.norm(posed[0]-skin['vertices'], axis=-1).max())}
    results['coincident_local_rotation'] = {
        'pairDistanceChangeMax': distance_drift(motion['positions']),
        'fixedBoneLengthErrorMax': motion['fixedLengthErrorMax'],
        'weightedMeshRigidError': mesh_errors,
        'preparation': coincident['report'],
    }
    result = {"asset": registered["asset"], "proof": "synthetic_rigid_turn_only",
        "accepted": False, "source": "rotated reference; reference remains unchanged; not authored clips",
        "rotations": labels, "bodyHubs": list(hubs), "sourcePairDistanceChangeMax": distance_drift(capture),
        "matchedRestCurrentControlDrift": distance_drift(matched["positions"]), "results": results,
        "inputs": {str(p.resolve()): sha256_file(p) for p in (skin_path, report_path, calibration_path)},
        "implementation": {name: sha256_file(Path(__file__).parent/name) for name in
            ("audit_rigid_capture_transfer.py", "body_relative_capture_motion.py", "local_rotation_capture_motion.py", "reconstruct_adapted.py", "direction_retarget.py", "aligned_capture_motion.py", "coincident_bind_candidate.py", "donor_eagle.py")}}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("skin", "registration", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.skin.resolve(), args.registration.resolve(), args.output.resolve())))
