"""Immutable capture-to-owned-bind reference calibration.

The calibration is asset-wide, rather than clip-local: a clip whose first
image happens to be idle may use it, but flight clips are never reset to it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _png_equal(left: Path, right: Path) -> bool:
    with Image.open(left) as a, Image.open(right) as b:
        return np.array_equal(np.asarray(a.convert("RGBA")), np.asarray(b.convert("RGBA")))


def _metadata(
    *, capture_path: Path, reference_png: Path, known_idle_png: Path,
    research_skin: Path, names: list[str], parents: np.ndarray,
    reference_index: int,
) -> dict[str, Any]:
    return {
        "captureSha256": _sha256(capture_path),
        "referencePngSha256": _sha256(reference_png),
        "knownIdlePngSha256": _sha256(known_idle_png),
        "researchSkinSha256": _sha256(research_skin),
        "jointNames": list(names),
        "parents": np.asarray(parents, dtype=np.int64).tolist(),
        "referenceIndex": int(reference_index),
    }


def load_or_create(
    *, calibration_path: Path, capture_path: Path, reference_png: Path,
    known_idle_png: Path, research_skin: Path, capture_positions: np.ndarray,
    names: list[str], parents: np.ndarray, reference_index: int = 0,
) -> dict[str, Any]:
    """Create once, then strictly validate and load the asset calibration."""
    for path, label in ((capture_path, "capture"), (reference_png, "reference PNG"),
                        (known_idle_png, "known idle PNG"), (research_skin, "research skin")):
        if not path.is_file():
            raise FileNotFoundError(f"idle calibration {label} is missing: {path}")
    if not _png_equal(reference_png, known_idle_png):
        raise ValueError("idle calibration refused: reference and known idle PNGs differ")
    positions = np.asarray(capture_positions, dtype=np.float64)
    if positions.ndim != 3 or positions.shape[2] != 3:
        raise ValueError(f"capture positions must have shape (frames,joints,3), got {positions.shape}")
    if not 0 <= reference_index < len(positions):
        raise IndexError(f"idle calibration reference index out of range: {reference_index}")
    if not np.all(np.isfinite(positions)):
        raise ValueError("idle calibration capture positions contain non-finite values")
    if len(names) != len(parents) or positions.shape[1] != len(names):
        raise ValueError("idle calibration joint topology does not match capture positions")
    with np.load(capture_path, allow_pickle=False) as raw:
        disk_positions = np.asarray(raw["pred_position"], dtype=np.float64)
        capture_names = [item.decode("utf-8") if isinstance(item, bytes) else str(item)
                         for item in np.asarray(raw["joint_names"]).tolist()]
        capture_parents = np.asarray(raw["parents"], dtype=np.int64)
    if disk_positions.shape != positions.shape or not np.array_equal(disk_positions, positions):
        raise ValueError("idle calibration caller positions do not match saved capture")
    if capture_names != list(names) or not np.array_equal(capture_parents, np.asarray(parents, dtype=np.int64)):
        raise ValueError("idle calibration joint topology does not match saved capture")
    reference = positions[reference_index].copy()
    metadata = _metadata(capture_path=capture_path, reference_png=reference_png,
                         known_idle_png=known_idle_png, research_skin=research_skin,
                         names=names, parents=parents, reference_index=reference_index)
    if calibration_path.is_file():
        payload = json.loads(calibration_path.read_text(encoding="utf-8"))
        if payload.get("schema") != "idle_reference_v1" or payload.get("metadata") != metadata:
            raise ValueError(f"idle calibration provenance drifted: {calibration_path}")
        saved = np.asarray(payload.get("referencePositions"), dtype=np.float64)
        if saved.shape != (len(names), 3) or not np.all(np.isfinite(saved)):
            raise ValueError(f"idle calibration reference positions are invalid: {calibration_path}")
        if not np.array_equal(saved, reference):
            raise ValueError(f"idle calibration reference positions drifted: {calibration_path}")
        return {"path": calibration_path, "hash": _sha256(calibration_path),
                "referencePositions": saved, "metadata": metadata}
    calibration_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "idle_reference_v1", "assetWide": True,
        "metadata": metadata,
        "referencePositions": positions[reference_index].tolist(),
        "provenance": f"capture frame {reference_index} paired with pixel-identical known idle sprite",
    }
    with calibration_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, indent=2) + "\n")
    return {"path": calibration_path, "hash": _sha256(calibration_path),
            "referencePositions": reference, "metadata": metadata}
