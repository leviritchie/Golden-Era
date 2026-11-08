"""Two-actor capture for a mounted unit, without fabricating a vendor graph.

The source clip is captured once per actor package.  Actor corpora remain
separate; composition and rider constraints belong to a later stage.
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np

from capture_skin_corpus import _sha, validate_manifest
from intermediate_capture import encode_sprite_vendor, run_capture
from model_runner import load_model
from pin import sha256_files
from paths import REPO
from run_mocap_baseline import _gpu_lock_waiting
from authored_zoo_donors import pad_package_to_capacity
from vendor_reference import load_complete_package, package_paths

DEFAULT_MOUNT_REF = "Coyote#Coyote-Attack1/y0"
DEFAULT_RIDER_REF = "00160523-f3b6-5765-931a-351e339862d7#00160523-f3b6-5765-931a-351e339862d7/y0"


def _provenance(kind: str, ref_seq: str, package: dict[str, Any]) -> dict[str, Any]:
    paths = package_paths(kind, ref_seq)
    files = [paths[key] for key in ("bvh", "pose", "train", "speciesInfo", "scaleCache")]
    return {
        "kind": kind,
        "refSeq": ref_seq,
        "packageSha256": sha256_files(files),
        "jointCount": int(package["jointCount"]),
        "jointNames": list(package["jointNames"]),
    }


def _actor_manifest(source: dict[str, Any], unit: str, out: Path) -> Path:
    payload = dict(source)
    payload["unit"] = unit
    path = out / "manifest.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def validate_actor_alignment(source: dict[str, Any]) -> None:
    """Ensure both actor corpora receive identical source clip timelines."""
    for clip in source["clips"]:
        if not (clip["contextBefore"] and clip["frames"]):
            raise ValueError(f"clip {clip['key']} must have contextBefore and authored frames")
        if any(not isinstance(path, str) for path in clip["contextBefore"] + clip["frames"] + clip["contextAfter"]):
            raise ValueError(f"clip {clip['key']} contains a non-string source path")


def capture_mounted(
    manifest_path: Path,
    output: Path,
    *,
    mount_ref: str = DEFAULT_MOUNT_REF,
    rider_ref: str = DEFAULT_RIDER_REF,
    device: str = "cuda",
) -> dict[str, Any]:
    started = time.perf_counter()
    source = validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    validate_actor_alignment(source)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite output: {output}")
    mount = load_complete_package("zoo", mount_ref)
    rider = load_complete_package("obj", rider_ref)
    longest = max(
        len(clip["contextBefore"]) + len(clip["frames"]) + len(clip["contextAfter"])
        for clip in source["clips"]
    )
    mount = pad_package_to_capacity(mount, longest)
    rider = pad_package_to_capacity(rider, longest)
    actors = ((source["unit"] + "_mount", "zoo", mount_ref, mount), (source["unit"] + "_rider", "obj", rider_ref, rider))
    # Reject over-capacity clips before creating output or touching CUDA.
    for actor, _kind, _ref, package in actors:
        capacity = int(np.asarray(package["posePosition"]).shape[0])
        for clip in source["clips"]:
            count = len(clip["contextBefore"]) + len(clip["frames"]) + len(clip["contextAfter"])
            if count > capacity:
                raise ValueError(f"{actor} clip {clip['key']} has {count} capture frames but capacity is {capacity}")
    output.mkdir(parents=True)
    shared_inputs = output / "source_inputs"
    shared_inputs.mkdir()
    all_paths = [Path(source["idle"])] + [Path(frame) for clip in source["clips"] for frame in clip["contextBefore"] + clip["frames"] + clip["contextAfter"]]
    unique = list(dict.fromkeys(all_paths))
    numbered = []
    for index, path in enumerate(unique):
        dest = shared_inputs / f"{index:06d}.png"
        shutil.copy2(path, dest)
        numbered.append(dest)
    results = []
    import torch
    with _gpu_lock_waiting(REPO):
        encode_started = time.perf_counter()
        embeds, preprocess = encode_sprite_vendor(numbered, device=device, encoder_input_dir=output / "encoder_cache")
        encode_seconds = time.perf_counter() - encode_started
        model_started = time.perf_counter()
        model = load_model(torch.device(device))[0]
        model_load_seconds = time.perf_counter() - model_started
        for actor, kind, ref_seq, package in actors:
            actor_started = time.perf_counter()
            actor_dir = output / ("mount" if actor.endswith("mount") else "rider")
            actor_dir.mkdir()
            actor_manifest = _actor_manifest(source, actor, actor_dir)
            rows = []
            for clip in source["clips"]:
                clip_dir = actor_dir / clip["key"]
                frame_dir = clip_dir / "frames"
                frame_dir.mkdir(parents=True)
                paths = [Path(frame) for frame in clip["contextBefore"] + clip["frames"] + clip["contextAfter"]]
                indices = [unique.index(path) for path in paths]
                for number, source_index in enumerate(indices):
                    shutil.copy2(numbered[source_index], frame_dir / f"{number:06d}.png")
                clip_started = time.perf_counter()
                report = run_capture(package=package, frames_dir=frame_dir, out_dir=clip_dir / "capture", image_embed=embeds[indices], preprocess_meta=preprocess, model=model, source_kind="full_plate_actor_conditioned", title=clip["key"], compare_gt=False)
                capture_path = (clip_dir / "capture" / "raw_capture.npz").resolve()
                start = len(clip["contextBefore"])
                rows.append({"key": clip["key"], "frames": [str(x) for x in paths[start:start + len(clip["frames"])]], "capture": str(capture_path), "captureSha256": _sha(capture_path), "sourceIndices": list(range(start, start + len(clip["frames"]))), "referenceIndex": 0, "contextBeforeCount": start, "contextAfterCount": len(clip["contextAfter"]), "captureSeconds": time.perf_counter() - clip_started, "report": report})
                print(f"captured {actor}/{clip['key']}", flush=True)
            actor_seconds = time.perf_counter() - actor_started
            corpus = {"schema": "homm3.skin-corpus.v1", "unit": actor, "manifest": str(actor_manifest.resolve()), "manifestSha256": _sha(actor_manifest), "package": _provenance(kind, ref_seq, package), "preprocess": preprocess, "sourceFrames": {str(path): {"sha256": _sha(path), "anchor": path == Path(source["idle"])} for path in unique}, "captures": rows, "captureCondition": "full_plate_actor_conditioned", "timings": {"actorSeconds": actor_seconds}, "createdAt": time.time()}
            (actor_dir / "corpus.json").write_text(json.dumps(corpus, indent=2), encoding="utf-8")
            results.append(corpus)
    summary = {"schema": "homm3.mounted-capture.v1", "sourceManifest": str(manifest_path.resolve()), "sourceManifestSha256": _sha(manifest_path), "corpora": [{"unit": x["unit"], "path": str((output / ("mount" if x["unit"].endswith("_mount") else "rider") / "corpus.json").resolve()), "sha256": _sha(Path(x["manifest"]).parent / "corpus.json")} for x in results], "timings": {"encodeSeconds": encode_seconds, "modelLoadSeconds": model_load_seconds, "elapsedSeconds": time.perf_counter() - started}}
    (output / "mounted_capture.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mount-ref", default=DEFAULT_MOUNT_REF)
    parser.add_argument("--rider-ref", default=DEFAULT_RIDER_REF)
    args = parser.parse_args()
    result = capture_mounted(args.manifest, args.output, mount_ref=args.mount_ref, rider_ref=args.rider_ref)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
