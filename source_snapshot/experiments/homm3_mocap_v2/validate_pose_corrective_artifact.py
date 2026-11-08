"""Fail-closed CPU validator for a saved pose-corrective diagnostic artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from pose_corrective_field import PoseCorrectiveField
from run_shape_preserved import _load_frozen_prep
from run_skin_mesh_pilot import _training_regions
from fitted_corrective_base import load_fitted_base

HERE = Path(__file__).resolve().parent


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_hashes(report: dict) -> dict[str, str]:
    checked: dict[str, str] = {}
    if not report.get('inputs') or not report.get('implementationHashes'):
        raise ValueError('required provenance hashes missing')
    for path_text, expected in report.get("inputs", {}).items():
        path = Path(path_text)
        actual = _sha(path)
        if actual != expected:
            raise ValueError(f"input hash drift: {path}")
        checked[str(path.resolve())] = actual
    for name, expected in report.get("implementationHashes", {}).items():
        path = HERE / name
        if not path.is_file():
            raise ValueError(f"implementation file missing: {name}")
        actual = _sha(path)
        if actual != expected:
            raise ValueError(f"implementation hash drift: {name}")
        checked[str(path.resolve())] = actual
    return checked


def _state_equal(actual: torch.Tensor, expected: torch.Tensor, key: str) -> None:
    if actual.shape != expected.shape or actual.dtype != expected.dtype or not torch.equal(actual, expected):
        raise ValueError(f"reconstructed field state differs before loading: {key}")


def _validate_surface_report(report: dict) -> dict:
    surface = report.get("surface", {})
    candidate_surface = surface.get("candidate", {})
    frames = candidate_surface.get("perFrame", [])
    if not isinstance(frames, list) or not frames:
        raise ValueError("report lacks candidate surface perFrame metrics")
    p95 = [float(row["p95"]) for row in frames]
    compression = [float(row["compressionViolationFraction"]) for row in frames]
    idle_alpha = float(report.get("idleDifference", {}).get("alphaMeanAbs", float("inf")))
    held = report.get("heldoutMean", {})
    if not all(np.isfinite(p95 + compression + [idle_alpha])):
        raise ValueError("report surface or idle metrics are non-finite")
    if not isinstance(held.get("baseline"), dict) or not isinstance(held.get("candidate"), dict):
        raise ValueError("report lacks baseline/candidate heldout metrics")
    for side in ("baseline", "candidate"):
        for metric in ("iou", "color"):
            if not np.isfinite(float(held[side][metric])):
                raise ValueError(f"non-finite heldout {side} {metric}")
    return {
        "surfaceP95Max": max(p95),
        "compressionViolationFractionMax": max(compression),
        "idleAlphaMeanAbs": idle_alpha,
        "heldout": held,
        "gates": {
            "surfaceP95": max(p95) <= 1.5,
            "compressionFraction": max(compression) <= .05,
            "idleAlpha": idle_alpha <= .005,
            "heldoutIoUNotWorse": float(held["candidate"]["iou"]) >= float(held["baseline"]["iou"]),
            "heldoutColorNotWorse": float(held["candidate"]["color"]) <= float(held["baseline"]["color"]),
        },
    }


def _array_sha(value: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(value).tobytes())
    return digest.hexdigest()


def _validate_warm_checkpoint(report: dict, *, require: bool = False) -> dict | None:
    warm = report.get("warmStart")
    if warm is None:
        if require:
            raise ValueError("residual corrective artifact requires warmStart provenance")
        return None
    required = ("reportPath", "reportSha256", "statePath", "stateSha256",
                "meshesPath", "meshesSha256", "candidateSha256")
    if any(key not in warm for key in required):
        raise ValueError("warmStart checkpoint provenance is incomplete")
    policy = report.get("checkpointPolicy")
    if policy != "image_best_without_surface_or_idle_regression":
        raise ValueError("unsupported warmStart checkpoint policy")
    paths = {key: Path(warm[key]) for key in ("reportPath", "statePath", "meshesPath")}
    expected = {"reportPath": "reportSha256", "statePath": "stateSha256", "meshesPath": "meshesSha256"}
    for path_key, hash_key in expected.items():
        if not paths[path_key].is_file() or _sha(paths[path_key]) != warm[hash_key]:
            raise ValueError(f"warmStart {path_key} hash drift")
    with np.load(paths["meshesPath"], allow_pickle=False) as arrays:
        if "candidate" not in arrays or _array_sha(arrays["candidate"]) != warm["candidateSha256"]:
            raise ValueError("warmStart candidate hash drift")
    initial = report.get("warmStartMetrics")
    selected = report.get("selectedMetrics")
    if not isinstance(initial, dict) or not isinstance(selected, dict):
        raise ValueError("warmStart metrics are missing")
    for key in ("image", "surface", "idle"):
        if key not in initial or key not in selected or not np.isfinite(float(initial[key])) or not np.isfinite(float(selected[key])):
            raise ValueError(f"warmStart metric missing or non-finite: {key}")
        if float(selected[key]) > float(initial[key]) + 1e-6:
            raise ValueError(f"selected metric regressed warmStart: {key}")
    feasible = float(selected["image"]) < float(initial["image"]) - 1e-6
    if type(report.get("feasibleImprovement")) is not bool or report["feasibleImprovement"] != feasible:
        raise ValueError("warmStart feasibleImprovement flag is inconsistent")
    warm_report = json.loads(paths["reportPath"].read_text(encoding="utf-8"))
    if warm_report.get("asset") != report.get("asset"):
        raise ValueError("warmStart report asset differs")
    if warm_report.get("baseFit") != report.get("baseFit"):
        raise ValueError("warmStart report baseFit differs")
    if warm_report.get("fixedMotionHashes") != report.get("fixedMotionHashes"):
        raise ValueError("warmStart report fixed motion hashes differ")
    return {"checkpointPolicy": policy, "warmStartMetrics": initial,
            "selectedMetrics": selected, "feasibleImprovement": feasible}


def validate(artifact: Path, output: Path) -> dict:
    if not artifact.is_dir():
        raise FileNotFoundError(f"artifact folder does not exist: {artifact}")
    if output.exists():
        raise FileExistsError(f"output must be absent: {output}")
    report_path = artifact / "report.json"
    state_path = artifact / "corrective_field.pt"
    meshes_path = artifact / "candidate_meshes.npz"
    for path in (report_path, state_path, meshes_path):
        if not path.is_file():
            raise FileNotFoundError(f"required artifact file missing: {path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    checked_hashes = _check_hashes(report)
    asset = report.get("asset")
    if not isinstance(asset, str) or not asset:
        raise ValueError("report lacks asset")
    freeze, skin = _load_frozen_prep(asset)
    if report.get('baseFit') is not None:
        base = report['baseFit']
        old_report=json.loads((Path(base['fitDirectory'])/'report.json').read_text())
        skin, verified_base = load_fitted_base(Path(base['fitDirectory']),asset,skin,
            report['fixedMotionHashes'],old_report['inputs']['corpusSha256'],_sha(Path(freeze['researchSkin'])))
        if verified_base != base:
            raise ValueError('fitted base provenance differs')
    with np.load(meshes_path, allow_pickle=False) as arrays:
        candidate = np.asarray(arrays["candidate"], dtype=np.float64).copy()
        baseline = np.asarray(arrays["baseline"], dtype=np.float64).copy()
        local = np.asarray(arrays["localRotation"], dtype=np.float64).copy()
    if candidate.shape != baseline.shape or candidate.ndim != 3 or candidate.shape[-1] != 3:
        raise ValueError("candidate and baseline meshes must have matching [F,V,3] shape")
    if not np.isfinite(candidate).all() or not np.isfinite(baseline).all():
        raise ValueError("candidate and baseline meshes must be finite")
    if candidate.shape != (len(local), len(skin['vertices']), 3) or len(local) == 0:
        raise ValueError('mesh inventory differs from local poses or prepared mesh')
    train_indices = np.asarray(report.get("trainIndices", []))
    if train_indices.dtype.kind not in 'iu' or train_indices.ndim != 1 or len(train_indices) == 0 or np.any(train_indices < 0) or np.any(train_indices >= len(local)) or len(np.unique(train_indices)) != len(train_indices):
        raise ValueError("invalid saved training indices")
    neutral = np.repeat(np.eye(3, dtype=np.float64)[None], len(skin["names"]), axis=0)
    frozen = tuple(str(value) for value in report.get("frozenRegions", []))
    expected_frozen = tuple(sorted(set(skin['regions'])-set(_training_regions(asset,skin))))
    if frozen != expected_frozen:
        raise ValueError('frozen regions differ from prepared profile policy')
    residual_energy = report.get("residualFeatureEnergy")
    field_kwargs = {}
    if residual_energy is None:
        field_class = PoseCorrectiveField
    else:
        try:
            from residual_pose_corrective_field import ResidualPoseCorrectiveField
        except ImportError as error:
            raise ValueError("residual corrective field implementation is unavailable") from error
        if not np.isfinite(float(residual_energy)) or not 0.0 < float(residual_energy) <= 1.0:
            raise ValueError("residualFeatureEnergy must be finite and nonnegative")
        field_class = ResidualPoseCorrectiveField
        field_kwargs["target_energy"] = float(residual_energy)
    field = field_class(skin["vertices"], skin["regions"], local[train_indices], neutral,
                        frozen_regions=frozen, max_displacement_fraction=.10,
                        grid_resolution=4, device="cpu", **field_kwargs)
    if int(report.get("modeCount", -1)) != len(field.modes):
        raise ValueError("report modeCount differs from reconstructed field")
    state = torch.load(state_path, weights_only=True, map_location="cpu")
    if not isinstance(state, dict):
        raise ValueError("corrective field state must be a tensor mapping")
    current = field.state_dict()
    for key, expected in current.items():
        if key not in state:
            raise ValueError(f"saved field state missing: {key}")
        # Controls are the learned artifact. Every neutral/feature/spatial
        # buffer must match the reconstruction before those controls load.
        if not key.endswith(".control"):
            _state_equal(expected, state[key], key)
    field.load_state_dict(state, strict=True)
    local_t = torch.as_tensor(local, dtype=torch.float32)
    with torch.no_grad():
        delta = field.displacement(local_t)
        coefficients = field.coefficients(local_t)
        neutral_delta = field.displacement(torch.as_tensor(neutral[None], dtype=torch.float32))
    if not bool(torch.isfinite(delta).all()) or not bool(torch.isfinite(coefficients).all()):
        raise ValueError("field produced non-finite displacement or coefficients")
    max_allowed = .10 * float(field.bbox_diag)
    displacement_norm = torch.linalg.vector_norm(delta, dim=-1)
    frozen_mask = field.modes[0].frozen_mask
    if float(displacement_norm.max()) > max_allowed + 1e-6:
        raise ValueError("corrective displacement exceeds configured bound")
    if float(neutral_delta.abs().max()) != 0.0:
        raise ValueError("neutral corrective displacement is not exactly zero")
    if bool(frozen_mask.any()) and float(delta[:, frozen_mask].abs().max()) != 0.0:
        raise ValueError("frozen vertices received corrective displacement")
    groups = field.modes[0].group_ids.detach().cpu().numpy()
    duplicate_max = 0.0
    for group in np.unique(groups):
        members = np.flatnonzero(groups == group)
        if len(members) > 1:
            duplicate_max = max(duplicate_max, float((delta[:, members] - delta[:, members[:1]]).abs().max()))
    if duplicate_max > 1e-7:
        raise ValueError("duplicate vertices received different corrective displacements")
    coefficient_sum_abs = coefficients.abs().sum(dim=-1)
    if float(coefficient_sum_abs.max()) > 1.0 + 1e-6:
        raise ValueError("corrective coefficient sum exceeds one")
    gates = _validate_surface_report(report)
    warm_checkpoint = _validate_warm_checkpoint(report, require=residual_energy is not None)
    result = {
        "schema": "homm3.pose-corrective-artifact-validation.v1",
        "artifact": str(artifact.resolve()),
        "asset": asset,
        "accepted": False,
        "proof": "CPU artifact contract and reported quality gates only; no promotion",
        "inputHashes": checked_hashes,
        "artifactHashes": {name: _sha(artifact / name) for name in ("report.json", "corrective_field.pt", "candidate_meshes.npz")},
        "fieldChecks": {
            "frameCount": int(len(local)),
            "vertexCount": int(candidate.shape[1]),
            "maxDisplacement": float(displacement_norm.max()),
            "maxAllowedDisplacement": max_allowed,
            "neutralMaxDisplacement": float(neutral_delta.abs().max()),
            "duplicateMaxDifference": duplicate_max,
            "maxCoefficientSumAbs": float(coefficient_sum_abs.max()),
            "frozenVertexCount": int(frozen_mask.sum()),
        },
        "quality": gates,
        "reportQualityGate": report.get("qualityGate"),
        "warmStart": warm_checkpoint,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.artifact, args.output), indent=2))
