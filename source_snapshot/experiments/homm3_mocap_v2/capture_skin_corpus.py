"""Capture a manifest of authored sprite clips with one frozen vendor model.

This is deliberately a capture-only lane: it never invents idle/death frames,
silently truncates a clip, or falls back to another model/package.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
import re
from pathlib import Path
from typing import Any

import numpy as np

from capture_candidates import asset_entry, require_frozen_package
from intermediate_capture import encode_sprite_vendor, run_capture
from model_runner import load_model
from paths import REPO
from run_mocap_baseline import _gpu_lock_waiting
from structured_profiles import require_profile_pin

def validate_manifest(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("manifest must be an object")
    unit = value.get("unit")
    if not isinstance(unit, str) or not re.fullmatch(r"h3_[A-Za-z0-9][A-Za-z0-9_.-]*", unit):
        raise ValueError("manifest unit must match h3_<name>")
    idle = Path(value.get("idle", ""))
    if not idle.is_absolute() or not idle.is_file() or idle.suffix.lower() != ".png":
        raise ValueError("idle must be an existing absolute PNG path")
    clips = value.get("clips")
    if not isinstance(clips, list) or not clips:
        raise ValueError("clips must be a non-empty list")
    keys: set[str] = set()
    canvas_size = None
    def check_canvas(path: Path) -> None:
        nonlocal canvas_size
        from PIL import Image
        with Image.open(path) as image:
            size = tuple(image.size)
        if canvas_size is None:
            canvas_size = size
        elif size != canvas_size:
            raise ValueError(f"all corpus PNGs must share one canvas size: {path} has {size}, expected {canvas_size}")
    check_canvas(idle)
    clean = {"unit": unit, "idle": str(idle), "clips": []}
    for clip in clips:
        if not isinstance(clip, dict) or not isinstance(clip.get("key"), str) or not clip["key"]:
            raise ValueError("each clip requires a non-empty key")
        key = clip["key"]
        if key in keys:
            raise ValueError(f"duplicate clip key: {key}")
        keys.add(key)
        frames = clip.get("frames")
        before = clip.get("contextBefore")
        after = clip.get("contextAfter")
        if not isinstance(before, list) or not before:
            raise ValueError(f"clip {key} requires non-empty contextBefore")
        if not isinstance(after, list):
            raise ValueError(f"clip {key} requires contextAfter list (it may be empty for terminal clips)")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", key):
            raise ValueError(f"clip key is not a safe output directory name: {key!r}")
        if not isinstance(frames, list) or not frames:
            raise ValueError(f"clip {key} must have at least one frame")
        paths = []
        for raw in frames:
            path = Path(raw)
            if not path.is_absolute() or not path.is_file() or path.suffix.lower() != ".png":
                raise ValueError(f"clip {key} contains missing/non-PNG absolute frame: {raw}")
            paths.append(str(path))
            check_canvas(path)
        def context_paths(values, label):
            result = []
            for raw in values:
                path = Path(raw)
                if not path.is_absolute() or not path.is_file() or path.suffix.lower() != ".png":
                    raise ValueError(f"clip {key} context {label} contains missing/non-PNG absolute frame: {raw}")
                result.append(str(path))
                check_canvas(path)
            return result
        before_paths = context_paths(before, "before")
        after_paths = context_paths(after, "after")
        if Path(before_paths[0]) != idle:
            raise ValueError(f"clip {key} contextBefore must start with the manifest idle anchor")
        clean["clips"].append({"key": key, "frames": paths, "contextBefore": before_paths, "contextAfter": after_paths})
    return clean


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_source_identity(raw_manifest: dict[str, Any]) -> None:
    """Enforce an optional candidate pin against the original idle source row."""
    entry = asset_entry(str(raw_manifest.get("unit", "")))
    identity = entry.get("sourceIdentity")
    if identity is None:
        return
    if not isinstance(identity, dict):
        raise ValueError("sourceIdentity must be an object when present")
    pinned = identity.get("nativeIdleSha256")
    def_name = identity.get("defName")
    if not isinstance(pinned, str) or len(pinned) != 64 or any(c not in "0123456789abcdefABCDEF" for c in pinned):
        raise ValueError("sourceIdentity.nativeIdleSha256 must be a SHA-256 hex string")
    if not isinstance(def_name, str) or not def_name.strip():
        raise ValueError("sourceIdentity.defName must be a non-empty string")
    rows = raw_manifest.get("frames")
    if not isinstance(rows, list):
        raise ValueError("sourceIdentity requires raw manifest.frames provenance")
    matches = [row for row in rows if isinstance(row, dict) and row.get("group") == 2 and row.get("frame") == 0]
    if len(matches) != 1:
        raise ValueError("sourceIdentity requires exactly one original group 2 frame 0 row")
    row = matches[0]
    source = row.get("source")
    row_hash = row.get("sourceSha256")
    prepared = row.get("prepared")
    prepared_hash = row.get("preparedSha256")
    idle = raw_manifest.get("idle")
    if not all(isinstance(value, str) for value in (source, row_hash, prepared, prepared_hash, idle)):
        raise ValueError("sourceIdentity group 2 frame 0 row must pin source/prepared paths and hashes")
    source_path = Path(source)
    if Path(prepared).resolve() != Path(idle).resolve():
        raise ValueError("sourceIdentity group 2 frame 0 row is not the manifest prepared idle")
    if not source_path.is_file() or _sha(source_path).lower() != row_hash.lower():
        raise ValueError("sourceIdentity original source hash does not match row.sourceSha256")
    prepared_path = Path(prepared)
    if not prepared_path.is_file() or _sha(prepared_path).lower() != prepared_hash.lower():
        raise ValueError("sourceIdentity prepared idle hash does not match row.preparedSha256")
    if _sha(source_path).lower() != pinned.lower():
        raise ValueError("sourceIdentity nativeIdleSha256 does not match original source")


def capture_corpus(manifest_path: Path, output: Path, *, device: str = "cuda") -> dict[str, Any]:
    started_total = time.perf_counter()
    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    profile_pin = require_profile_pin(raw_manifest.get("unit"), raw_manifest)
    validate_source_identity(raw_manifest)
    manifest = validate_manifest(raw_manifest)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite output: {output}")
    package = require_frozen_package(manifest["unit"], role="primary")
    pose_capacity = int(np.asarray(package["posePosition"]).shape[0])
    all_paths = [Path(manifest["idle"])] + [Path(frame) for clip in manifest["clips"] for frame in clip["contextBefore"] + clip["frames"] + clip["contextAfter"]]
    unique = list(dict.fromkeys(all_paths))
    output.mkdir(parents=True)
    inputs = output / "inputs"
    inputs.mkdir()
    numbered = []
    for index, path in enumerate(unique):
        dest = inputs / f"{index:06d}.png"
        shutil.copy2(path, dest)
        numbered.append(dest)
    # Hold the process-wide GPU lock across model load, encoding, and every
    # fresh inference; concurrent cascade workers otherwise thrash WDDM.
    import torch
    with _gpu_lock_waiting(REPO):
        # One encoder invocation prevents repeated weight initialization.
        encode_started = time.perf_counter()
        embeds, preprocess = encode_sprite_vendor(numbered, device=device, encoder_input_dir=output / "encoder_cache")
        encode_seconds = time.perf_counter() - encode_started
        model_started = time.perf_counter()
        model = load_model(torch.device(device))[0]
        model_load_seconds = time.perf_counter() - model_started
        rows = []
        for clip in manifest["clips"]:
            source = [Path(frame) for frame in clip["contextBefore"] + clip["frames"] + clip["contextAfter"]]
            if len(source) > pose_capacity:
                raise ValueError(f"clip {clip['key']} has {len(source)} capture frames but capacity is {pose_capacity}")
            clip_dir = output / clip["key"]
            frame_dir = clip_dir / "frames"
            frame_dir.mkdir(parents=True)
            indices = [unique.index(path) for path in source]
            for number, source_index in enumerate(indices):
                shutil.copy2(numbered[source_index], frame_dir / f"{number:06d}.png")
            clip_started = time.perf_counter()
            report = run_capture(package=package, frames_dir=frame_dir, out_dir=clip_dir / "capture", image_embed=embeds[indices], preprocess_meta=preprocess, model=model, source_kind="authored_source_frame", title=clip["key"], compare_gt=False)
            capture_path = (clip_dir / "capture" / "raw_capture.npz").resolve()
            clip_seconds = time.perf_counter() - clip_started
            authored_start = len(clip["contextBefore"])
            authored_end = authored_start + len(clip["frames"])
            rows.append({"key": clip["key"], "frames": [str(path) for path in source[authored_start:authored_end]], "capture": str(capture_path), "captureSha256": _sha(capture_path), "sourceIndices": list(range(authored_start, authored_end)), "referenceIndex": 0, "contextBeforeCount": authored_start, "contextAfterCount": len(clip["contextAfter"]), "captureSeconds": clip_seconds, "over600Seconds": clip_seconds > 600, "report": report})
            print(f"captured {clip['key']} ({clip_seconds:.1f}s)", flush=True)
    result = {"schema": "homm3.skin-corpus.v1", "unit": manifest["unit"], "manifest": str(manifest_path.resolve()), "manifestSha256": _sha(manifest_path), "package": {"kind": package["kind"], "refSeq": package["refSeq"], "candidateRole": package.get("candidateRole")}, "preprocess": preprocess, "sourceFrames": {str(path): {"sha256": _sha(path), "anchor": path == Path(manifest["idle"])} for path in unique}, "captures": rows, "timings": {"modelLoadSeconds": model_load_seconds, "encodeSeconds": encode_seconds, "elapsedTotalSeconds": time.perf_counter() - started_total}, "createdAt": time.time()}
    require_profile_pin(manifest["unit"], profile_pin)
    result.update(profile_pin)
    (output / "corpus.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    capture_corpus(args.manifest, args.output)


if __name__ == "__main__":
    main()
