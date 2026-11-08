"""CPU audit of g00 wing articulation in each variant's own rest space."""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np

from compare_aligned_capture_motion import read_skin
from run_skin_mesh_pilot import validate_capture_indices
from corpus_motion import load_motion
from mesh_preview import fk_world_matrices
from pin import sha256_file
from asset_profiles import get_profile


def proper_alignment(rest: np.ndarray, current: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return row-vector rotation mapping rest centered points to current."""
    if rest.shape != current.shape or rest.ndim != 2 or rest.shape[1] != 3 or not np.isfinite(rest).all() or not np.isfinite(current).all():
        raise ValueError("invalid body hub coordinates")
    a = rest - rest.mean(0)
    b = current - current.mean(0)
    u, singular, vt = np.linalg.svd(a.T @ b)
    if singular.shape != (3,) or singular[1] <= 1e-9:
        raise ValueError("body hub alignment is rank deficient")
    q = u @ vt
    if np.linalg.det(q) < 0:
        u[:, -1] *= -1
        q = u @ vt
    return q, singular


def angle(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a); nb = np.linalg.norm(b)
    if not np.isfinite(na) or not np.isfinite(nb) or na <= 1e-12 or nb <= 1e-12:
        raise ValueError("zero or nonfinite articulation vector")
    return float(np.degrees(np.arccos(np.clip(np.dot(a, b) / (na * nb), -1.0, 1.0))))


def audit_unit(unit: str, root: Path, skin_path: Path, corpus_path: Path, registration: Path) -> dict:
    corpus_path = corpus_path.resolve(); registration = registration.resolve(); skin_path = skin_path.resolve()
    skin = read_skin(skin_path)
    corpus = json.loads(corpus_path.read_text())
    if corpus.get("unit") != unit:
        raise ValueError("corpus unit mismatch")
    row = next(item for item in corpus["captures"] if item["key"] == "g00_move")
    capture_path = Path(row["capture"]).resolve()
    if sha256_file(capture_path) != row["captureSha256"]:
        raise ValueError("capture hash mismatch")
    pilot_path = registration / "pilot_report.json"
    pilot = json.loads(pilot_path.read_text())
    if pilot.get("asset") != unit or pilot.get("kind") != "idle_registration_only":
        raise ValueError("registration identity mismatch")
    inputs = pilot["inputs"]
    if inputs.get("researchSkin") != sha256_file(skin_path) or inputs.get("corpusSha256") != sha256_file(corpus_path):
        raise ValueError("registration inputs do not match explicit audit inputs")
    calibration_path = Path(inputs["calibrationPath"]).resolve()
    if sha256_file(calibration_path) != inputs["calibration"]:
        raise ValueError("calibration hash mismatch")
    reference = np.asarray(json.loads(calibration_path.read_text())["referencePositions"], dtype=float)
    with np.load(capture_path, allow_pickle=False) as raw:
        validate_capture_indices(row, len(raw["pred_position"]))
        raw_positions = np.asarray(raw["pred_position"], dtype=float)[row["sourceIndices"]]
        hubs = tuple(get_profile(unit)["wholeBodyHubs"])
        reconstructed = load_motion(raw, row, corpus, skin, reference, hubs)["jointWorld"][:, :, :3, 3]
    offsets = np.asarray(skin["offsets"], dtype=float).copy()
    rest_world = fk_world_matrices(local_rotation=np.broadcast_to(np.eye(3), (len(offsets), 3, 3)), local_translation=offsets, parents=skin["parents"], root_world=offsets[0])[:, :3, 3]
    names = list(skin["names"]); ix = {name: i for i, name in enumerate(names)}
    hub_indices = [ix[name] for name in hubs]
    wings = {side: tuple(ix[f"BN_Wing_{side}_{part}"] for part in ("01", "03", "04")) for side in ("L", "R")}

    def variant(label: str, rest: np.ndarray, frames: np.ndarray) -> dict:
        result = {"restSites": {name: rest[ix[name]].tolist() for name in ("Hips", "BN_Wing_L_01", "BN_Wing_L_03", "BN_Wing_L_04", "BN_Wing_R_01", "BN_Wing_R_03", "BN_Wing_R_04")}, "frames": []}
        for frame in frames:
            q, singular = proper_alignment(rest[hub_indices], frame[hub_indices])
            aligned = (frame - frame[hub_indices].mean(0)) @ q.T + rest[hub_indices].mean(0)
            row_out = {}
            for side, (a, b, c) in wings.items():
                v1 = rest[b] - rest[a]; v2 = rest[c] - rest[b]
                x = aligned[b] - aligned[a]; y = aligned[c] - aligned[b]
                n0 = np.cross(v1, v2); n = np.cross(x, y)
                row_out[side] = {"d1": angle(x, v1), "d2": angle(y, v2), "plane": angle(n, n0), "v1Length": float(np.linalg.norm(x)), "v2Length": float(np.linalg.norm(y))}
            row_out["alignmentSingularValues"] = singular.tolist()
            row_out["alignmentCondition"] = (float(singular[0] / singular[-1]) if singular[-1] > 1e-9 else None)
            result["frames"].append(row_out)
        result["variant"] = label
        return result

    return {"unit": unit, "skinSha256": sha256_file(skin_path), "corpusSha256": sha256_file(corpus_path), "registrationPilotSha256": sha256_file(pilot_path), "calibrationPath": str(calibration_path), "calibrationSha256": sha256_file(calibration_path), "captureSha256": row["captureSha256"], "referenceSource": str(calibration_path), "source": variant("raw_source_vs_capture_reference", reference, raw_positions), "reconstructed": variant("load_motion_vs_own_rest_world", rest_world, reconstructed), "method": "per-frame proper Kabsch rotation over profile wholeBodyHubs; translation and body rigid rotation removed separately for each variant; rank checked and singular values/condition reported"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--unit", action="append", nargs=4, metavar=("NAME", "SKIN", "CORPUS", "REGISTRATION"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = {name: audit_unit(name, args.root.resolve(), Path(skin), Path(corpus), Path(registration)) for name, skin, corpus, registration in args.unit}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
