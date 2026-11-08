"""Controlled motion, bind, or coincident-ownership trials with fixed rest mesh.

Produces diagnostic motion arrays, scores and GIFs only. No captures, fitting,
production motion selection, or delivery exports are changed.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from aligned_capture_motion import reconstruct_aligned
from body_relative_capture_motion import reconstruct_body_relative
from local_rotation_capture_motion import reconstruct_local_rotation
from coincident_bind_candidate import build_candidate as build_coincident_bind
from reconstruct_adapted import reconstruct_adapted
from paired_bind_candidate import build_paired_bind
from asset_profiles import get_profile
from corpus_motion import load_motion
from ownership_candidate_validation import validate_invariants
from ownership_motion_comparison import _motion_retention
from pin import sha256_file
from run_skin_mesh_pilot import comparison, deform, expand_camera_to_full_canvas, validate_capture_indices
from run_skin_weight_pilot import ROOT, cascade_batch_lock, source_images
from skin_image_objective import SkinImageRenderer, image_metrics
from skin_surface_constraints import SurfaceConstraints


def read_skin(path):
    with np.load(path, allow_pickle=False) as raw:
        skin = {key: raw[key].copy() for key in raw.files}
    skin["names"] = list(skin["names"].astype(str))
    return skin


def run(original_path, skin_path, corpus_path, registration, output, *, candidate="source_alignment"):
    started = time.perf_counter()
    if candidate not in ("source_alignment", "paired_bind", "body_relative", "local_rotation", "coincident_bind", "coincident_local_rotation"):
        raise ValueError("unknown controlled motion candidate")
    if output.exists():
        raise FileExistsError(output)
    original, skin = read_skin(original_path), read_skin(skin_path)
    validate_invariants(original, skin, weapon_regions=("weapon",))
    corpus = json.loads(corpus_path.read_text())
    if corpus.get("motionRepresentation", "capture_positions_v1") != "capture_positions_v1":
        raise ValueError("alignment trial requires ordinary position captures, not composed FK")
    previous_path = registration / "pilot_report.json"
    previous = json.loads(previous_path.read_text())
    if previous.get("asset") != corpus["unit"] or previous.get("kind") != "idle_registration_only":
        raise ValueError("registration identity differs from corpus")
    inputs = previous["inputs"]
    if inputs["researchSkin"] != sha256_file(original_path):
        raise ValueError("registration differs from original preparation")
    if inputs["corpusSha256"] != sha256_file(corpus_path):
        raise ValueError("registration differs from captured corpus")
    calibration_path = Path(inputs["calibrationPath"])
    if sha256_file(calibration_path) != inputs["calibration"]:
        raise ValueError("calibration changed")
    manifest_path = Path(corpus["manifest"])
    if sha256_file(manifest_path) != corpus["manifestSha256"]:
        raise ValueError("source manifest changed")
    reference = np.asarray(json.loads(calibration_path.read_text())["referencePositions"])
    profile = get_profile(corpus["unit"])
    hubs = tuple(profile["wholeBodyHubs"])
    camera_path = registration / "camera.json"
    camera = expand_camera_to_full_canvas(json.loads(camera_path.read_text()), 224)
    pinned = {str(path.resolve()): sha256_file(path) for path in
              (original_path, skin_path, corpus_path, camera_path, calibration_path, previous_path)}
    report = {"asset": corpus["unit"], "proof": "controlled_motion_candidate",
              "scope": ("source-frame alignment only; identical skin, geometry, camera and source" if candidate == "source_alignment"
                        else "paired bind sites and inverse bind only; identical weights, geometry, camera and source"),
              "candidate": candidate,
              "accepted": False, "inputHashes": pinned, "cases": {},
              "implementation": {name: sha256_file(Path(__file__).parent / name) for name in
                                 ("reconstruct_adapted.py", "aligned_capture_motion.py",
                                  "compare_aligned_capture_motion.py", "paired_bind_candidate.py",
                                  "fit_deformation_bind.py")}}
    if candidate == "body_relative":
        report["scope"] = "body rotation separated from articulation; identical skin, geometry, camera and source"
        report["implementation"]["body_relative_capture_motion.py"] = sha256_file(Path(__file__).parent / "body_relative_capture_motion.py")
    if candidate in ("local_rotation", "coincident_local_rotation"):
        report["scope"] = "same-reference capture local rotations transported in one static frame; identical skin, geometry, camera and source"
        report["implementation"]["local_rotation_capture_motion.py"] = sha256_file(Path(__file__).parent / "local_rotation_capture_motion.py")
        report["implementation"]["direction_retarget.py"] = sha256_file(Path(__file__).parent / "direction_retarget.py")
    coincident = build_coincident_bind(skin) if candidate in ('coincident_bind', 'coincident_local_rotation') else None
    if coincident is not None:
        report['scope'] = 'serial coincident bind and canonical skin owner; unchanged rest mesh and capture'
        report['coincidentPreparation'] = coincident['report']
        report['implementation']['coincident_bind_candidate.py'] = sha256_file(Path(__file__).parent/'coincident_bind_candidate.py')
    clips = corpus["captures"]
    if not clips or len({row["key"] for row in clips}) != len(clips):
        raise ValueError("empty or duplicate clip inventory")
    # Check all provenance before starting the expensive render phase.
    for row in clips:
        if Path(row["key"]).name != row["key"] or any(c in row["key"] for c in "/\\:"):
            raise ValueError("unsafe clip key")
        if sha256_file(Path(row["capture"])) != row["captureSha256"]:
            raise ValueError("capture changed")
        for frame in row["frames"]:
            if sha256_file(Path(frame)) != corpus["sourceFrames"][frame]["sha256"]:
                raise ValueError("source frame changed")
    paired = build_paired_bind(profile) if candidate == "paired_bind" else None
    if paired is not None:
        if paired["names"] != original["names"] or not np.array_equal(paired["parents"], original["parents"]):
            raise ValueError("paired bind candidate differs from frozen skeleton topology")
        report["candidateReferenceBindIdentityError"] = paired["referenceBindIdentityError"]
        report["pairedBindInputs"] = {key: paired[key] for key in
            ("inputProfileHash", "candidateProfileHash", "donorHash", "meshSha256")}
    output.mkdir(parents=True)
    if coincident is not None:
        np.savez_compressed(output/'candidate_skin.npz', **coincident['skin'])
        report['candidateSkinSha256'] = sha256_file(output/'candidate_skin.npz')
    if paired is not None:
        np.savez_compressed(output / "paired_bind.npz", offsets=paired["offsets"], inverseBind=paired["inverseBind"])
        report["pairedBindSha256"] = sha256_file(output / "paired_bind.npz")
    with cascade_batch_lock(ROOT):
        renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], camera, 224)
        surface = SurfaceConstraints(skin["vertices"], skin["triangles"], device="cuda")
        vertices = torch.as_tensor(skin["vertices"], device="cuda", dtype=torch.float32)
        weights = torch.as_tensor(skin["weights"], device="cuda", dtype=torch.float32)
        bind_trial = coincident['skin'] if coincident is not None else paired
        candidate_weights = torch.as_tensor(coincident['skin']['weights'], device='cuda', dtype=torch.float32) if coincident is not None else weights
        for row in clips:
            with np.load(row["capture"], allow_pickle=False) as raw:
                validate_capture_indices(row, len(raw["pred_position"]))
                indices = row["sourceIndices"]
                baseline = load_motion(raw, row, corpus, original, reference, hubs)
                reconstruct = {"source_alignment": reconstruct_aligned,
                               "paired_bind": reconstruct_adapted,
                               "body_relative": reconstruct_body_relative,
                               "local_rotation": reconstruct_local_rotation,
                               "coincident_bind": reconstruct_adapted,
                               "coincident_local_rotation": reconstruct_local_rotation}[candidate]
                aligned = reconstruct(
                    capture_positions=raw["pred_position"][indices], capture_reference_positions=reference,
                    capture_offsets=original["captureOffsets"], fitted_offsets=original["offsets"] if bind_trial is None else bind_trial["offsets"],
                    parents=original["parents"], names=original["names"], hub_names=hubs,
                )
            variants = (baseline, aligned)
            inverse_binds = (skin["inverseBind"], skin["inverseBind"] if bind_trial is None else bind_trial["inverseBind"])
            meshes = [deform(torch.as_tensor((m["jointWorld"] @ inverse[None])[:, :, :3],
                                             device="cuda", dtype=torch.float32), w, vertices) for m, inverse, w in zip(variants, inverse_binds, (weights, candidate_weights))]
            targets = source_images([Path(p) for p in row["frames"]], camera["sourceCrop"], 224)
            images = [renderer.render(mesh) for mesh in meshes]
            depth_counts = []
            for mesh in meshes:
                depth = mesh @ torch.as_tensor(camera["forward"], device="cuda", dtype=torch.float32)
                depth_counts.append(int(((depth-camera["depth_center"]).abs() >= camera["depth_span"]).sum()))
            case = {"captureSha256": row["captureSha256"], "frameCount": len(row["frames"]),
                    "scores": [image_metrics(*image, *targets[:2]) for image in images],
                    "surface": [surface.metrics(mesh) for mesh in meshes], "depthClippedVertexSamples": depth_counts,
                    "motionRetention": _motion_retention(*meshes, skin["regions"]),
                    "firstPoseVertexDifferenceMax": float(torch.linalg.vector_norm(meshes[1][0]-meshes[0][0], dim=-1).max()),
                    "candidateFixedLengthErrorMax": aligned["fixedLengthErrorMax"],
                    "baselineFrame0IsBind": baseline["clipFrame0IsBind"],
                    "candidateFrame0IsBind": aligned["clipFrame0IsBind"]}
            if candidate == "body_relative":
                case["bodyDiagnostics"] = aligned["bodyDiagnostics"]
            report["cases"][row["key"]] = case
            np.savez_compressed(output / (row["key"] + ".npz"), baselineWorld=baseline["jointWorld"],
                                alignedWorld=aligned["jointWorld"], baselineLocal=baseline["localRotation"],
                                alignedLocal=aligned["localRotation"])
            comparison(output / (row["key"] + ".gif"), [targets[0]] + [image[0] for image in images],
                       ["Source", "Current motion", {"source_alignment": "Source-frame aligned",
                            "paired_bind": "Paired bind sites", "body_relative": "Body-relative motion",
                            "local_rotation": "Local rotation transfer", "coincident_bind": "Coincident bind + ownership",
                            "coincident_local_rotation": "Coincident bind + local motion"}[candidate]],
                       row["key"] + ("; fixed rest mesh" if coincident is not None else "; fixed weights and mesh"))
            print(str(output / (row["key"] + ".gif")), flush=True)
    for path, expected in pinned.items():
        if sha256_file(Path(path)) != expected:
            raise ValueError("trial input changed during run")
    report["elapsedSeconds"] = time.perf_counter() - started
    (output / "report.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original", "skin", "corpus", "registration", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--candidate", choices=("source_alignment", "paired_bind", "body_relative", "local_rotation", "coincident_bind", "coincident_local_rotation"), default="source_alignment")
    args = parser.parse_args()
    run(args.original.resolve(), args.skin.resolve(), args.corpus.resolve(),
        args.registration.resolve(), args.output.resolve(), candidate=args.candidate)
