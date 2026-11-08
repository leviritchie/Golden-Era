"""Controlled three-column anatomical capture diagnostic.

This runner is intentionally fail-closed until the anatomical motion module is
available. It shares one canonical coincident-bind candidate for the body-
relative control and anatomical candidate; only the reconstructed motion differs
between those two columns.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import torch

from asset_profiles import get_profile
from coincident_bind_candidate import build_candidate
from compare_aligned_capture_motion import read_skin
from pin import sha256_file
from corpus_motion import load_motion
from body_relative_capture_motion import reconstruct_body_relative
from run_skin_mesh_pilot import ROOT, comparison, deform, expand_camera_to_full_canvas, validate_capture_indices
from run_skin_weight_pilot import cascade_batch_lock, source_images
from skin_image_objective import SkinImageRenderer, image_metrics
from skin_surface_constraints import SurfaceConstraints
from mesh_preview import fk_world_matrices


IMPLEMENTATION_NAMES = (
    "run_anatomical_capture_comparison.py",
    "coincident_bind_candidate.py",
    "body_relative_capture_motion.py",
    "reconstruct_adapted.py",
    "anatomical_capture_motion.py",
    "anatomical_direction_transfer.py",
    "direction_retarget.py",
    "corpus_motion.py",
)


def validate_inputs(original: dict, corpus: dict, unit: str, original_path: Path,
                    corpus_path: Path, registration: Path) -> dict:
    if corpus.get("unit") != unit:
        raise ValueError("corpus unit mismatch")
    if corpus.get("motionRepresentation", "capture_positions_v1") != "capture_positions_v1":
        raise ValueError("anatomical trial requires capture_positions_v1")
    captures = corpus.get("captures") or []
    keys = [row.get("key") for row in captures]
    if not keys or len(set(keys)) != len(keys):
        raise ValueError("capture inventory must be nonempty and unique")
    for key in keys:
        if not isinstance(key, str) or Path(key).name != key or any(c in key for c in "/\\:"):
            raise ValueError("unsafe capture key")
    pilot_path = registration / "pilot_report.json"
    pilot = json.loads(pilot_path.read_text())
    if pilot.get("asset") != unit or pilot.get("kind") != "idle_registration_only":
        raise ValueError("registration identity mismatch")
    inputs = pilot["inputs"]
    if inputs.get("researchSkin") != sha256_file(original_path):
        raise ValueError("registration research skin mismatch")
    if inputs.get("corpusSha256") != sha256_file(corpus_path):
        raise ValueError("registration corpus mismatch")
    calibration = Path(inputs["calibrationPath"]).resolve()
    if sha256_file(calibration) != inputs.get("calibration"):
        raise ValueError("registration calibration mismatch")
    for row in captures:
        capture = Path(row["capture"]).resolve()
        if sha256_file(capture) != row["captureSha256"]:
            raise ValueError("capture hash mismatch")
        for frame in row["frames"]:
            path = Path(frame).resolve()
            if sha256_file(path) != corpus["sourceFrames"][frame]["sha256"]:
                raise ValueError("source frame hash mismatch")
    return {"pilot": pilot, "pilotPath": pilot_path, "calibration": calibration}


def prepare(unit: str, original_path: Path, corpus_path: Path, registration: Path) -> dict:
    original = read_skin(original_path)
    corpus = json.loads(corpus_path.read_text())
    provenance = validate_inputs(original, corpus, unit, original_path, corpus_path, registration)
    profile = get_profile(unit)
    canonical = build_candidate(original)
    if list(np.asarray(canonical["skin"]["names"]).astype(str)) != list(np.asarray(original["names"]).astype(str)) or not np.array_equal(canonical["skin"]["parents"], original["parents"]):
        raise ValueError("canonical candidate changed skeleton topology")
    return {"original": original, "corpus": corpus, "profile": profile,
            "canonical": canonical, "provenance": provenance,
            "inputHashes": {str(path.resolve()): sha256_file(path) for path in (original_path, corpus_path, provenance["pilotPath"], provenance["calibration"])}}


def rigid_weighted_controls(skin: dict, reference: np.ndarray, hubs: tuple) -> dict:
    from anatomical_capture_motion import reconstruct_anatomical_capture
    from direction_retarget import _rodrigues

    vertices = np.asarray(skin["vertices"], dtype=float)
    weights = np.asarray(skin["weights"], dtype=float)
    offsets = np.asarray(skin["offsets"], dtype=float)
    parents = np.asarray(skin["parents"], dtype=np.int64)
    inverse = np.asarray(skin["inverseBind"], dtype=float)
    hom = np.concatenate((vertices, np.ones((len(vertices), 1))), axis=1)
    rotations = [np.eye(3)] + [
        _rodrigues(axis, np.radians(degrees))
        for axis in np.eye(3) for degrees in (-90., -45., 45., 90.)
    ]
    travels = [np.zeros(3)] + [np.array([.13, -.07, .11])] * 12
    frames = np.stack([(reference - reference[0]) @ q.T + reference[0] + travel
                       for q, travel in zip(rotations, travels)])
    motion = reconstruct_anatomical_capture(
        capture_positions=frames, capture_reference_positions=reference,
        capture_offsets=skin["captureOffsets"], fitted_offsets=offsets,
        parents=parents, names=list(skin["names"]), hub_names=hubs,
        target_weights=weights,
    )
    gauge = motion["wholeBodyRotation"]
    root = motion["fittedRest"][0]
    errors = []
    for world, source_q, travel in zip(motion["jointWorld"], rotations, travels):
        target_q = gauge @ source_q @ gauge.T
        posed = np.einsum("vj,jki,vi->vk", weights, world @ inverse, hom)[:, :3]
        expected = (vertices - root) @ target_q.T + root + gauge @ travel
        errors.append(float(np.max(np.abs(posed - expected))))
    if not np.isfinite(errors).all() or max(errors) >= 1e-6:
        raise ValueError(f"anatomical rigid weighted control failed: {errors}")
    return {"neutralLbsMaxAbsError": errors[0],
            "rigidRotationMaxAbsError": max(errors[1:]), "perPoseMaxAbsError": errors,
            "motionReconstructorExercised": True, "capturePoseCount": len(frames),
            "rootTravelExercised": True, "passed": max(errors) < 1e-6}


def run(unit: str, original_path: Path, corpus_path: Path, registration: Path, output: Path) -> dict:
    started = time.perf_counter()
    if output.exists():
        raise FileExistsError(output)
    prepared = prepare(unit, original_path, corpus_path, registration)
    original = prepared["original"]
    canonical = prepared["canonical"]["skin"]
    corpus = prepared["corpus"]
    calibration = json.loads(prepared["provenance"]["calibration"].read_text())
    reference = np.asarray(calibration["referencePositions"], dtype=float)
    camera_path = registration / "camera.json"
    camera = expand_camera_to_full_canvas(json.loads(camera_path.read_text()), 224)
    pinned = dict(prepared["inputHashes"])
    pinned[str(camera_path.resolve())] = sha256_file(camera_path)
    for name in IMPLEMENTATION_NAMES:
        path = Path(__file__).parent / name
        if not path.exists():
            raise FileNotFoundError(path)
        pinned[str(path.resolve())] = sha256_file(path)
    for row in corpus["captures"]:
        pinned[str(Path(row["capture"]).resolve())] = sha256_file(Path(row["capture"]))
        for frame in row["frames"]:
            pinned[str(Path(frame).resolve())] = sha256_file(Path(frame))
    hubs = tuple(prepared["profile"]["wholeBodyHubs"])
    output.mkdir(parents=True)
    canonical_path = output / "canonical_skin.npz"
    np.savez_compressed(canonical_path, **canonical)
    report = {"asset": unit, "proof": "controlled_anatomical_capture_diagnostic", "accepted": False,
              "scope": "source original plus canonical body-relative and anatomical motion; no production selector",
              "inputHashes": pinned, "implementation": {name: sha256_file(Path(__file__).parent / name) for name in IMPLEMENTATION_NAMES},
              "canonicalPreparation": prepared["canonical"]["report"], "canonicalSkinSha256": sha256_file(canonical_path), "rigidWeightedControls": rigid_weighted_controls(canonical, reference, hubs), "cases": {}}
    try:
        from anatomical_capture_motion import reconstruct_anatomical_capture
    except ImportError as exc:
        raise RuntimeError("anatomical_capture_motion.reconstruct_anatomical_capture is not available") from exc
    with cascade_batch_lock(ROOT):
        renderer = SkinImageRenderer(original["triangles"], original["uvs"], original["albedo"], camera, 224)
        surface = SurfaceConstraints(original["vertices"], original["triangles"], device="cuda")
        vertices = torch.as_tensor(original["vertices"], device="cuda", dtype=torch.float32)
        source_weights = torch.as_tensor(original["weights"], device="cuda", dtype=torch.float32)
        canonical_weights = torch.as_tensor(canonical["weights"], device="cuda", dtype=torch.float32)
        for row in corpus["captures"]:
            with np.load(row["capture"], allow_pickle=False) as raw:
                validate_capture_indices(row, len(raw["pred_position"]))
                capture = raw["pred_position"][row["sourceIndices"]]
                source_motion = load_motion(raw, row, corpus, original, reference, hubs)
                kwargs = dict(capture_positions=capture, capture_reference_positions=reference,
                              capture_offsets=original["captureOffsets"], fitted_offsets=canonical["offsets"],
                              parents=original["parents"], names=original["names"], hub_names=hubs)
                body_motion = reconstruct_body_relative(**kwargs)
                anatomical_motion = reconstruct_anatomical_capture(**kwargs, target_weights=canonical["weights"])
            variants = [(source_motion, original["inverseBind"], source_weights),
                        (body_motion, canonical["inverseBind"], canonical_weights),
                        (anatomical_motion, canonical["inverseBind"], canonical_weights)]
            meshes = [deform(torch.as_tensor((motion["jointWorld"] @ inverse[None])[:, :, :3], device="cuda", dtype=torch.float32), weights, vertices) for motion, inverse, weights in variants]
            targets = source_images([Path(p) for p in row["frames"]], camera["sourceCrop"], 224)
            images = [renderer.render(mesh) for mesh in meshes]
            mean_steps = [float(torch.linalg.vector_norm(mesh[1:] - mesh[:-1], dim=-1).mean()) if len(mesh) > 1 else 0.0 for mesh in meshes]
            forward = torch.as_tensor(camera["forward"], device="cuda", dtype=torch.float32)
            depth_clipped = [int((((mesh @ forward) - camera["depth_center"]).abs() >= camera["depth_span"]).sum()) for mesh in meshes]
            report["cases"][row["key"]] = {"captureSha256": row["captureSha256"], "frameCount": len(row["frames"]), "scores": [image_metrics(*image, *targets[:2]) for image in images], "surface": [surface.metrics(mesh) for mesh in meshes], "meanVertexStep": mean_steps, "depthClippedVertexSamples": depth_clipped, "anatomicalHintCount": len(anatomical_motion["hints"]), "anatomicalHints": anatomical_motion["hints"], "inactiveTargetLeaves": anatomical_motion.get("inactiveTargetLeaves", []), "anatomicalFixedLengthErrorMax": anatomical_motion["fixedLengthErrorMax"]}
            comparison(output / (row["key"] + ".gif"), [targets[0]] + [image[0] for image in images], ["Source", "Current prepared", "Canonical body-relative", "Canonical anatomical"], row["key"] + "; canonical skin")
            np.savez_compressed(output / (row["key"] + ".npz"), sourceWorld=source_motion["jointWorld"], bodyRelativeWorld=body_motion["jointWorld"], anatomicalWorld=anatomical_motion["jointWorld"])
    for path, expected in pinned.items():
        if sha256_file(Path(path)) != expected:
            raise ValueError("trial input changed during run")
    report["elapsedSeconds"] = time.perf_counter() - started
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


__all__ = ["IMPLEMENTATION_NAMES", "prepare", "run", "validate_inputs"]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", required=True)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.unit, args.original.resolve(), args.corpus.resolve(), args.registration.resolve(), args.output.resolve())
    print(json.dumps({"report": str(args.output.resolve() / "report.json"),
                      "elapsedSeconds": report["elapsedSeconds"], "accepted": report["accepted"],
                      "caseCount": len(report["cases"])}))
