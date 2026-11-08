"""Strict source-frame visibility scope for diagnostic prop replay."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_visibility(value: Any, asset: str, corpus_sha: str,
                        frame_paths: dict[str, list[Path]]) -> dict[str, np.ndarray]:
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ValueError("visibility schema must be integer 1")
    if value.get("asset") != asset:
        raise ValueError("visibility asset does not match requested asset")
    if value.get("corpusSha256") != corpus_sha:
        raise ValueError("visibility corpus hash does not match requested corpus")
    clips = value.get("clips")
    if not isinstance(clips, dict) or not clips:
        raise ValueError("visibility clips must be a non-empty object")
    result: dict[str, np.ndarray] = {}
    for key, row in clips.items():
        if key not in frame_paths:
            raise ValueError(f"visibility declares unknown clip: {key}")
        if not isinstance(row, dict):
            raise ValueError(f"visibility clip {key} must be an object")
        paths = list(frame_paths[key])
        hashes = row.get("sourceFrameSha256")
        visible = row.get("visible")
        if not isinstance(hashes, list) or not isinstance(visible, list) or not paths:
            raise ValueError(f"visibility clip {key} requires non-empty hash/visible lists")
        if len(hashes) != len(paths) or len(visible) != len(paths):
            raise ValueError(f"visibility clip {key} length differs from source frames")
        if any(type(flag) is not bool for flag in visible):
            raise ValueError(f"visibility clip {key} contains a non-bool visible value")
        for index, (path_value, expected) in enumerate(zip(paths, hashes)):
            path = Path(path_value)
            if not isinstance(expected, str) or len(expected) != 64:
                raise ValueError(f"visibility clip {key} has invalid source hash at {index}")
            if not path.is_file() or _sha256(path) != expected:
                raise ValueError(f"visibility source hash mismatch: {key}[{index}]")
        result[key] = np.asarray(visible, dtype=bool)
    return result


__all__ = ["validate_visibility"]
