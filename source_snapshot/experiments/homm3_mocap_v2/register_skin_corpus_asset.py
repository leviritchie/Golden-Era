"""Freeze one asset-wide idle reference and camera before corpus skin fitting."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

from run_skin_weight_pilot import (
    ROOT, _load_frozen_prep, _write_json, sha256_file, source_images,
    SkinImageRenderer, cascade_batch_lock,
)
from idle_calibration import load_or_create
from skin_camera_registration import register_camera, CameraRegistrationError
from run_skin_mesh_pilot import comparison
from structured_profiles import require_profile_pin


def register(asset: str, corpus_path: Path, output: Path):
    if output.exists():
        raise FileExistsError(output)
    started = time.perf_counter()
    corpus = json.loads(corpus_path.read_text())
    if corpus.get("unit") != asset:
        raise ValueError("corpus belongs to a different asset")
    manifest_path = Path(corpus["manifest"])
    if sha256_file(manifest_path) != corpus["manifestSha256"]:
        raise ValueError("source manifest changed after capture")
    manifest = json.loads(manifest_path.read_text())
    profile_pin = require_profile_pin(asset, corpus, manifest)
    idle_clips = [clip for clip in manifest["clips"] if clip["group"] == 2]
    if len(idle_clips) != 1:
        raise ValueError("one authored idle group is required")
    idle_clip = idle_clips[0]
    entry = next(item for item in corpus["captures"] if item["key"] == idle_clip["key"])
    capture_path = Path(entry["capture"])
    if sha256_file(capture_path) != entry["captureSha256"]:
        raise ValueError("idle capture changed after freeze")
    idle_path = Path(manifest["idle"])
    if sha256_file(idle_path) != corpus["sourceFrames"][str(idle_path)]["sha256"]:
        raise ValueError("idle source changed after capture")
    captured_idle = capture_path.parents[1] / "frames/000000.png"
    freeze, skin = _load_frozen_prep(asset)
    require_profile_pin(asset, freeze, profile_pin)
    # Registration owns this reference. Deriving an asset cache from directory
    # depth aliases unrelated units and preparation revisions.
    output.mkdir(parents=True)
    calibration_path = output / "idle_reference.json"
    with np.load(capture_path, allow_pickle=False) as raw:
        calibration = load_or_create(
            calibration_path=calibration_path, capture_path=capture_path,
            reference_png=captured_idle, known_idle_png=idle_path,
            research_skin=Path(freeze["researchSkin"]), capture_positions=raw["pred_position"],
            names=skin["names"], parents=skin["parents"],
        )
    with Image.open(idle_path) as image:
        source_size = image.size
    # Keep the complete tall/wide source canvas.  source_images pads the
    # centered square when left/top are negative, preserving foreground that
    # a min-dimension crop would cut off.
    size = max(source_size)
    crop = {"left": -((size - source_size[0]) // 2),
            "top": -((size - source_size[1]) // 2), "size": size}
    resolution = 224
    with cascade_batch_lock(ROOT):
        target = source_images([idle_path], crop, resolution)
        placeholder = {"right": [1, 0, 0], "down": [0, -1, 0], "forward": [0, 0, 1],
                       "scale": 50, "offset": [112, 112], "depth_center": 0, "depth_span": 10}
        renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], placeholder, resolution)
        try:
            camera, report = register_camera(renderer, skin["vertices"], *target,
                resolution=resolution, source_crop=crop, source_size=source_size)
        except CameraRegistrationError as error:
            _write_json(output / "registration_failure.json", error.report)
            raise
        comparison(output / "idle_registration.gif", [target[0], renderer.render(skin["vertices"][None])[0]],
                   ["Source idle", "Original mesh"], asset)
    _write_json(output / "camera.json", camera)
    _write_json(output / "camera_registration.json", report)
    # This is the existing runner's baseline contract, not a trained pilot.
    payload = {"asset": asset, "kind": "idle_registration_only", "proof": "generated-candidate",
               "motionOwner": "frozen_idle_calibrated_adapted_transforms",
               "inputs": {"researchSkin": sha256_file(Path(freeze["researchSkin"])),
                          "calibrationPath": str(calibration_path.resolve()),
                          "calibration": calibration["hash"], "corpusSha256": sha256_file(corpus_path)},
               "elapsedSeconds": time.perf_counter() - started}
    require_profile_pin(asset, profile_pin)
    payload.update(profile_pin)
    _write_json(output / "pilot_report.json", payload)
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(register(args.asset, args.corpus.resolve(), args.output.resolve())))
