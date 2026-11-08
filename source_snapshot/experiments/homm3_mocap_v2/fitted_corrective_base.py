"""Load a fitted all-frame corrective base without changing prepared metadata."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_report(report: dict, asset: str, prepared_skin_sha256: str,
                    motion_hashes: dict[str, str], corpus_sha256: str) -> Path:
    if not isinstance(report, dict) or not isinstance(asset, str) or not asset:
        raise ValueError("invalid fit report or asset")
    if report.get('asset') != asset:
        raise ValueError('fit report asset differs from requested asset')
    inputs = report.get("inputs")
    if not isinstance(inputs, dict) or inputs.get("researchSkin") != prepared_skin_sha256:
        raise ValueError("fit report prepared research skin hash differs")
    if inputs.get("corpusSha256") != corpus_sha256:
        raise ValueError("fit report corpus hash differs")
    corpus_path = Path(inputs.get("corpus", ""))
    if not corpus_path.is_file() or _sha(corpus_path) != corpus_sha256:
        raise ValueError("fit corpus is missing or hash-drifted")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    if corpus.get("unit") != asset:
        raise ValueError("fit corpus unit differs from requested asset")
    cases = report.get("cases")
    if not isinstance(cases, dict) or set(cases) != set(motion_hashes):
        raise ValueError("fit report motion cases do not exactly match requested hashes")
    for key, expected in motion_hashes.items():
        if cases[key].get("fixedMotionSha256") != expected:
            raise ValueError(f"fixed motion hash drift for {key}")
    if not report.get("validationBeforeAllFrameRefit"):
        raise ValueError("fit report lacks pre-refit holdout validation")
    if not isinstance(report.get("stages", {}).get("allFrames"), list):
        raise ValueError("fit report lacks all-frame refit stage")
    return corpus_path


def _validate_arrays(candidate: dict[str, np.ndarray], prepared: dict[str, np.ndarray]):
    required = ("vertices", "weights", "names", "parents")
    if any(key not in candidate for key in required):
        raise ValueError("diagnostic candidate is missing required arrays")
    vertices = np.array(candidate["vertices"], dtype=np.float64, copy=True)
    weights = np.array(candidate["weights"], dtype=np.float64, copy=True)
    names = np.asarray(candidate["names"]).astype(str)
    parents = np.asarray(candidate["parents"])
    if vertices.shape != np.asarray(prepared["vertices"]).shape or vertices.ndim != 2 or vertices.shape[1] != 3:
        raise ValueError("candidate vertices shape differs from prepared skin")
    if weights.shape != np.asarray(prepared["weights"]).shape or weights.ndim != 2:
        raise ValueError("candidate weights shape differs from prepared skin")
    if names.shape != np.asarray(prepared["names"]).shape or not np.array_equal(names, np.asarray(prepared["names"]).astype(str)):
        raise ValueError("candidate joint names differ from prepared skin")
    if parents.dtype.kind not in 'iu' or parents.shape != np.asarray(prepared["parents"]).shape or not np.array_equal(parents, prepared["parents"]):
        raise ValueError("candidate parents differ from prepared skin")
    prepared_vertices = np.asarray(prepared["vertices"])
    prepared_weights = np.asarray(prepared["weights"])
    if (not np.isfinite(prepared_vertices).all() or not np.isfinite(prepared_weights).all()
            or np.any(prepared_weights < 0.0)
            or not np.allclose(prepared_weights.sum(axis=1), 1.0, rtol=0.0, atol=1e-6)):
        raise ValueError("prepared vertices/weights must be finite and normalized")
    if not np.isfinite(vertices).all() or not np.isfinite(weights).all() or np.any(weights < 0.0):
        raise ValueError("candidate vertices/weights must be finite and nonnegative")
    if not np.allclose(weights.sum(axis=1), 1.0, rtol=0.0, atol=1e-6):
        raise ValueError("candidate weights must be normalized")
    return vertices, weights


def load_fitted_base(fit_dir, asset, prepared_skin, motion_hashes, corpus_sha256,
                     prepared_skin_sha256):
    """Return a prepared-skin copy with only fitted vertices and weights replaced."""
    fit_path = Path(fit_dir)
    report_path = fit_path / "report.json"
    candidate_path = fit_path / "diagnostic_candidate.npz"
    if not report_path.is_file() or not candidate_path.is_file():
        raise FileNotFoundError("fit directory requires report.json and diagnostic_candidate.npz")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    corpus_path = _require_report(report, asset, prepared_skin_sha256, motion_hashes, corpus_sha256)
    with np.load(candidate_path, allow_pickle=False) as data:
        candidate = {key: data[key].copy() for key in data.files}
    vertices, weights = _validate_arrays(candidate, prepared_skin)
    updated = {key: np.array(value, copy=True) for key, value in prepared_skin.items()}
    updated["vertices"] = vertices
    updated["weights"] = weights
    provenance = {
        "fitDirectory": str(fit_path.resolve()),
        "reportSha256": _sha(report_path),
        "candidateSha256": _sha(candidate_path),
        "corpusPath": str(corpus_path.resolve()),
        "corpusSha256": corpus_sha256,
        "preparedSkinSha256": prepared_skin_sha256,
        "allFrameBaseFit": True,
        "laterHeldoutRequiresIncrementalValidation": True,
        "replacedFields": ["vertices", "weights"],
    }
    return updated, provenance


__all__ = ["load_fitted_base"]
