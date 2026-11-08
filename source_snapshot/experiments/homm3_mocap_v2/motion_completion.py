"""Apply a previously generated, explicitly scoped motion-completion artifact."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _so3(values: np.ndarray, label: str) -> None:
    values = np.asarray(values, dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError(f"{label} contains nonfinite values")
    if values.shape[-2:] != (3, 3):
        raise ValueError(f"{label} is not a stack of 3x3 matrices")
    if not np.allclose(values @ np.swapaxes(values, -1, -2), np.eye(3), atol=1e-6, rtol=0):
        raise ValueError(f"{label} contains non-orthogonal matrices")
    if not np.allclose(np.linalg.det(values), 1.0, atol=1e-6, rtol=0):
        raise ValueError(f"{label} contains improper rotations")


def _resolve(value: str, base: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def _idle_hashes(annotation: dict[str, Any], corpus_path: Path, corpus_sha: str) -> set[str]:
    source_corpus = _resolve(str(annotation.get("sourceCorpus", "")), corpus_path.parent)
    if source_corpus.resolve() != corpus_path.resolve() or annotation.get("corpusSha256") != corpus_sha:
        raise ValueError("annotation source corpus does not match completion report")
    if _sha256(corpus_path) != corpus_sha:
        raise ValueError("completion corpus file does not match pinned digest")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    idle = [row for row in corpus["captures"] if row.get("key") == "g02_idle" or str(row.get("key", "")).endswith("_idle")]
    if len(idle) != 1:
        raise ValueError("source corpus must contain exactly one idle clip")
    hashes: set[str] = set()
    for value in idle[0]["frames"]:
        path = _resolve(str(value), corpus_path.parent)
        if not path.is_file():
            raise FileNotFoundError(path)
        hashes.add(_sha256(path))
    return hashes


def apply_motion_completion(
    motions: dict[str, dict[str, Any]],
    skin: dict[str, Any],
    report_path: str | Path,
    asset: str,
    corpus_sha: str,
    prepared_skin_sha: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Load and validate an explicit source-wrist artifact without fitting or writing files."""
    report_path = Path(report_path).resolve()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("proof") != "source-guided-wrist-orientation-diagnostic-no-delivery":
        raise ValueError("motion completion requires a source-guided wrist diagnostic report")
    if report.get("asset") != asset or report.get("corpusSha256") != corpus_sha:
        raise ValueError("motion completion provenance does not match requested asset/corpus")
    provenance = report.get("fitProvenance")
    if not isinstance(provenance, dict) or provenance.get("preparedSkinSha256") != prepared_skin_sha:
        raise ValueError("motion completion prepared skin provenance differs")
    annotation_value = report.get("annotationPath")
    annotation_sha = report.get("annotationSha256")
    if not annotation_value or not annotation_sha:
        raise ValueError("completion report must pin annotationPath and annotationSha256")
    annotation_path = _resolve(str(annotation_value), report_path.parent)
    if not annotation_path.is_file() or _sha256(annotation_path) != annotation_sha:
        raise ValueError("completion annotation is missing or changed")
    annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
    if annotation.get("asset") != asset or annotation.get("researchSkinSha256") != prepared_skin_sha:
        raise ValueError("completion annotation asset or prepared skin differs")
    motion_path = report_path.parent / "source_wrist_motion.npz"
    if not motion_path.is_file() or report.get("motionArtifactSha256") != _sha256(motion_path):
        raise ValueError("completion motion artifact is missing or changed")
    corpus_path = _resolve(str(annotation.get("sourceCorpus", "")), report_path.parent)
    idle_hashes = _idle_hashes(annotation, corpus_path, corpus_sha)
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    corpus_rows = {str(row["key"]): row for row in corpus.get("captures", [])}
    with np.load(motion_path, allow_pickle=False) as data:
        required = {"clipKeys", "clipOffsets", "jointWorld", "localRotation", "corrections", "baselineJointWorld", "baselineLocalRotation"}
        if set(data.files) != required | {"anchorVertexIds", "anchorRestWorld", "ownerRestWorld"}:
            raise ValueError("completion motion artifact has unexpected keys")
        clip_keys = [str(value) for value in data["clipKeys"].tolist()]
        offsets = np.asarray(data["clipOffsets"])
        corrected_world = np.asarray(data["jointWorld"], dtype=np.float64)
        corrected_local = np.asarray(data["localRotation"], dtype=np.float64)
        corrections = np.asarray(data["corrections"], dtype=np.float64)
        baseline_world = np.asarray(data["baselineJointWorld"], dtype=np.float64)
        baseline_local = np.asarray(data["baselineLocalRotation"], dtype=np.float64)
    report_keys = [str(value) for value in report.get("clipKeys", [])]
    report_offsets = report.get("clipOffsets")
    if report_keys != clip_keys or report_offsets != offsets.tolist():
        raise ValueError("completion report clip inventory differs from motion artifact")
    names = [str(value) for value in np.asarray(skin["names"]).tolist()]
    parents = np.asarray(skin["parents"], dtype=np.int64)
    if len(set(names)) != len(names) or len(parents) != len(names) or parents[0] != -1 or any(p < 0 or p >= i for i, p in enumerate(parents[1:], 1)):
        raise ValueError("skin hierarchy is invalid")
    owner = str(report.get("owner", ""))
    if names.count(owner) != 1:
        raise ValueError("completion owner is absent or duplicated")
    owner_index = names.index(owner)
    if np.any(parents == owner_index):
        raise ValueError("completion owner must be a leaf")
    if parents[owner_index] < 0:
        raise ValueError("completion owner must have a parent")
    if not clip_keys or len(set(clip_keys)) != len(clip_keys) or offsets.ndim != 1 or offsets.dtype.kind not in "iu" or len(offsets) != len(clip_keys) + 1 or offsets[0] != 0 or np.any(np.diff(offsets) <= 0) or offsets[-1] != len(corrected_world):
        raise ValueError("completion clip offsets are invalid")
    if len(corpus_rows) != len(corpus.get("captures", [])):
        raise ValueError("source corpus contains duplicate clip keys")
    expected = (len(corrected_world), len(names))
    for value, label in ((corrected_world, "corrected world"), (baseline_world, "baseline world")):
        if value.shape != expected + (4, 4) or not np.isfinite(value).all():
            raise ValueError(f"{label} dimensions or finiteness are invalid")
    _so3(corrected_world[..., :3, :3], "corrected world rotations")
    _so3(baseline_world[..., :3, :3], "baseline world rotations")
    if corrected_local.shape != expected + (3, 3) or baseline_local.shape != corrected_local.shape or corrections.shape != (len(corrected_world), 3, 3):
        raise ValueError("completion rotation dimensions are invalid")
    _so3(corrected_local, "corrected local")
    _so3(baseline_local, "baseline local")
    _so3(corrections, "completion corrections")
    if not np.isfinite(corrected_local).all() or not np.isfinite(baseline_local).all() or not np.isfinite(corrections).all():
        raise ValueError("completion rotations are nonfinite")
    result = copy.deepcopy(motions)
    for key, start, end in zip(clip_keys, offsets[:-1], offsets[1:]):
        if key not in motions:
            raise ValueError(f"completion clip is absent from current motion: {key}")
        row = corpus_rows.get(key)
        capture = annotation.get("captures", {}).get(key)
        if row is None or not isinstance(capture, dict):
            raise ValueError(f"completion clip lacks exact corpus/annotation ownership: {key}")
        if capture.get("captureSha256") != row.get("captureSha256") or capture.get("frameCount") != len(row.get("frames", [])):
            raise ValueError(f"completion capture provenance differs for {key}")
        frames = capture.get("frames")
        if not isinstance(frames, list) or len(frames) != end - start or len(frames) != len(row.get("frames", [])):
            raise ValueError(f"completion annotation frame count differs for {key}")
        for index, frame in enumerate(frames):
            if frame.get("localIndex") != index:
                raise ValueError(f"completion annotation localIndex differs for {key}[{index}]")
            expected_path = _resolve(str(row["frames"][index]), corpus_path.parent)
            actual_path = _resolve(str(frame.get("sourcePath", "")), corpus_path.parent)
            if actual_path != expected_path:
                raise ValueError(f"completion annotation source path differs for {key}[{index}]")
        motion = motions[key]
        world0 = np.asarray(motion["jointWorld"])
        local0 = np.asarray(motion["localRotation"])
        if world0.shape != (end - start, len(names), 4, 4) or local0.shape != (end - start, len(names), 3, 3):
            raise ValueError(f"current motion dimensions differ for {key}")
        if not np.array_equal(baseline_world[start:end], world0) or not np.array_equal(baseline_local[start:end], local0):
            raise ValueError(f"completion baseline differs for {key}")
        if "positions" in motion:
            positions = np.asarray(motion["positions"])
            if positions.shape != (end - start, len(names), 3) or not np.array_equal(positions, world0[:, :, :3, 3]):
                raise ValueError(f"current motion positions differ from joint worlds for {key}")
        if not np.array_equal(corrected_world[start:end, :, :3, 3], world0[:, :, :3, 3]):
            raise ValueError(f"completion changed joint positions for {key}")
        if not np.array_equal(corrected_world[start:end, :, 3, :], world0[:, :, 3, :]):
            raise ValueError(f"completion changed world homogeneous rows for {key}")
        if len(names) > 1:
            nonowner = [index for index in range(len(names)) if index != owner_index]
            if not np.array_equal(corrected_world[start:end, nonowner], world0[:, nonowner]):
                raise ValueError(f"completion changed non-owner world matrices for {key}")
            if not np.array_equal(corrected_local[start:end, nonowner], local0[:, nonowner]):
                raise ValueError(f"completion changed non-owner local rotations for {key}")
        base_r = world0[:, owner_index, :3, :3]
        got_r = corrected_world[start:end, owner_index, :3, :3]
        if not np.allclose(got_r, np.einsum("tij,tjk->tik", corrections[start:end], base_r), atol=1e-6, rtol=0):
            raise ValueError(f"completion correction does not match owner world rotation for {key}")
        parent = int(parents[owner_index])
        expected_local = np.einsum("tij,tjk->tik", corrected_world[start:end, parent, :3, :3].swapaxes(-1, -2), got_r)
        if not np.allclose(corrected_local[start:end, owner_index], expected_local, atol=1e-6, rtol=0):
            raise ValueError(f"completion owner local rotation is inconsistent for {key}")
        idle = annotation.get("captures", {}).get(key, {}).get("frames", [])
        for index, frame in enumerate(idle):
            source = _resolve(str(frame.get("sourcePath", "")), corpus_path.parent)
            source_sha = _sha256(source)
            if frame.get("sourceSha256") != source_sha:
                raise ValueError(f"annotation source hash differs for {key}[{index}]")
            if source_sha in idle_hashes and (not np.array_equal(corrected_world[start + index], world0[index]) or not np.array_equal(corrected_local[start + index], local0[index])):
                raise ValueError(f"completion changed protected idle world for {key}[{index}]")
        result[key]["jointWorld"] = corrected_world[start:end].copy()
        result[key]["localRotation"] = corrected_local[start:end].copy()
        result[key]["clipFrame0IsBind"] = bool(np.allclose(corrected_local[start], np.eye(3), atol=1e-7, rtol=0))
    return result, {"reportPath": str(report_path), "reportSha256": _sha256(report_path), "motionArtifactSha256": report["motionArtifactSha256"], "annotationSha256": annotation_sha, "asset": asset, "owner": owner, "mappedClips": clip_keys, "preservedClips": sorted(set(motions) - set(clip_keys))}


def restore_motion_completion(motions, skin, fit_report):
    """Replay the recorded completion before a fit consumer checks motion hashes."""
    recorded = fit_report.get("motionCompletion")
    if recorded is None:
        return motions
    path = Path(recorded["reportPath"])
    if not path.is_absolute() or _sha256(path) != recorded["reportSha256"]:
        raise ValueError("fitted motion completion report changed")
    completed, verified = apply_motion_completion(
        motions, skin, path, fit_report["asset"], fit_report["inputs"]["corpusSha256"],
        fit_report["inputs"]["researchSkin"])
    if verified != recorded:
        raise ValueError("fitted motion completion provenance changed")
    return completed


__all__ = ["apply_motion_completion", "restore_motion_completion"]
