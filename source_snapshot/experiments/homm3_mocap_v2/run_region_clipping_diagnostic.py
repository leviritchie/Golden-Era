"""GPU weight-only comparison for prepared versus unclipped source weights."""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
import numpy as np
import torch
from audit_skin_region_clipping import audit
from asset_profiles import get_profile
from compare_aligned_capture_motion import read_skin
from corpus_motion import load_motion
from ownership_motion_comparison import _motion_retention
from pin import sha256_file
from run_skin_mesh_pilot import ROOT, comparison, deform, expand_camera_to_full_canvas, validate_capture_indices
from run_skin_weight_pilot import cascade_batch_lock, source_images
from skin_image_objective import SkinImageRenderer, image_metrics
from skin_surface_constraints import SurfaceConstraints

IMPLEMENTATION_NAMES = (
    "run_region_clipping_diagnostic.py",
    "audit_skin_region_clipping.py",
    "corpus_motion.py",
    "reconstruct_adapted.py",
)


def validate_corpus_structure(corpus: dict) -> None:
    """Reject ambiguous or composed corpus inputs before any expensive work."""
    if corpus.get("motionRepresentation", "capture_positions_v1") != "capture_positions_v1":
        raise ValueError("weight-only diagnostic requires capture_positions_v1")
    captures = corpus.get("captures")
    if not captures:
        raise ValueError("corpus has no captures")
    keys = [row.get("key") for row in captures]
    if any(not isinstance(key, str) or not key or Path(key).name != key or any(c in key for c in "/\\:") for key in keys):
        raise ValueError("unsafe clip key")
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate clip key")


def assert_weight_only(original: dict, candidate: dict) -> None:
    if set(original) != set(candidate):
        raise ValueError("candidate changed skin keys")
    for key in original:
        if key == "weights":
            continue
        if not np.array_equal(original[key], candidate[key]):
            raise ValueError(f"candidate changed non-weight field: {key}")


def run(original: Path, corpus_path: Path, registration: Path, output: Path) -> dict:
    started = time.perf_counter()
    if output.exists(): raise FileExistsError(output)
    original_skin = read_skin(original); corpus = json.loads(corpus_path.read_text())
    validate_corpus_structure(corpus)
    profile = get_profile(corpus["unit"])
    from target_asset import load_target_asset
    clipped = audit(original_skin, load_target_asset(profile), profile)
    output.parent.mkdir(parents=True, exist_ok=True)
    candidate_path = output.parent / (output.name + "_unclipped_skin.npz")
    if candidate_path.exists(): raise FileExistsError(candidate_path)
    np.savez_compressed(candidate_path, **clipped["skin"]); candidate_skin = read_skin(candidate_path)
    assert_weight_only(original_skin, candidate_skin)
    previous_path = registration / "pilot_report.json"; previous = json.loads(previous_path.read_text())
    if previous.get("asset") != corpus["unit"] or previous.get("kind") != "idle_registration_only": raise ValueError("registration identity differs from corpus")
    inputs = previous["inputs"]
    if inputs["researchSkin"] != sha256_file(original): raise ValueError("registration differs from original preparation")
    if inputs["corpusSha256"] != sha256_file(corpus_path): raise ValueError("registration differs from captured corpus")
    calibration_path = Path(inputs["calibrationPath"])
    if sha256_file(calibration_path) != inputs["calibration"]: raise ValueError("calibration changed")
    reference = np.asarray(json.loads(calibration_path.read_text())["referencePositions"])
    camera_path = registration / "camera.json"; camera = expand_camera_to_full_canvas(json.loads(camera_path.read_text()), 224)
    manifest_path = Path(corpus["manifest"])
    if sha256_file(manifest_path) != corpus["manifestSha256"]: raise ValueError("source manifest changed")
    clips = corpus["captures"]
    for row in clips:
        if sha256_file(Path(row["capture"])) != row["captureSha256"]: raise ValueError("capture changed")
        for frame in row["frames"]:
            if sha256_file(Path(frame)) != corpus["sourceFrames"][frame]["sha256"]: raise ValueError("source frame changed")
    hubs = tuple(profile["wholeBodyHubs"])
    implementation_paths = [Path(__file__).parent / name for name in IMPLEMENTATION_NAMES]
    pinned = {str(p.resolve()): sha256_file(p) for p in (original, candidate_path, corpus_path, camera_path, calibration_path, previous_path, manifest_path, *implementation_paths)}
    for row in clips:
        pinned[str(Path(row["capture"]).resolve())] = sha256_file(Path(row["capture"]))
        for frame in row["frames"]:
            pinned[str(Path(frame).resolve())] = sha256_file(Path(frame))
    report = {"asset": corpus["unit"], "proof": "controlled_weight_only_diagnostic", "scope": "identical reconstructed motion, bind, geometry, camera and source; weights only", "candidate": "unclipped_source_region_weights", "accepted": False, "inputHashes": pinned, "implementation": {name: sha256_file(Path(__file__).parent / name) for name in IMPLEMENTATION_NAMES}, "cases": {}, "weightAudit": clipped["report"], "bindUnchanged": bool(np.array_equal(original_skin["offsets"], candidate_skin["offsets"]) and np.array_equal(original_skin["inverseBind"], candidate_skin["inverseBind"]) and np.array_equal(original_skin["captureOffsets"], candidate_skin["captureOffsets"])), "candidateSkinSha256": sha256_file(candidate_path), "outputPolicy": "diagnostic-only; no export or production payload"}
    output.mkdir(parents=True)
    with cascade_batch_lock(ROOT):
        renderer = SkinImageRenderer(original_skin["triangles"], original_skin["uvs"], original_skin["albedo"], camera, 224)
        surface = SurfaceConstraints(original_skin["vertices"], original_skin["triangles"], device="cuda")
        vertices = torch.as_tensor(original_skin["vertices"], device="cuda", dtype=torch.float32)
        weights = torch.as_tensor(original_skin["weights"], device="cuda", dtype=torch.float32)
        candidate_weights = torch.as_tensor(candidate_skin["weights"], device="cuda", dtype=torch.float32)
        for row in clips:
            with np.load(row["capture"], allow_pickle=False) as raw:
                validate_capture_indices(row, len(raw["pred_position"])); baseline = load_motion(raw, row, corpus, original_skin, reference, hubs)
            palettes = torch.as_tensor((baseline["jointWorld"] @ original_skin["inverseBind"][None])[:, :, :3], device="cuda", dtype=torch.float32)
            meshes = [deform(palettes, w, vertices) for w in (weights, candidate_weights)]
            targets = source_images([Path(p) for p in row["frames"]], camera["sourceCrop"], 224); images = [renderer.render(mesh) for mesh in meshes]
            forward = torch.as_tensor(camera["forward"], device="cuda", dtype=torch.float32)
            depths = [int((((mesh @ forward) - camera["depth_center"]).abs() >= camera["depth_span"]).sum()) for mesh in meshes]
            report["cases"][row["key"]] = {"captureSha256": row["captureSha256"], "frameCount": len(row["frames"]), "scores": [image_metrics(*image, *targets[:2]) for image in images], "surface": [surface.metrics(mesh) for mesh in meshes], "depthClippedVertexSamples": depths, "motionRetention": _motion_retention(*meshes, original_skin["regions"]), "firstPoseVertexDifferenceMax": float(torch.linalg.vector_norm(meshes[1][0] - meshes[0][0], dim=-1).max()), "motionSource": "single baseline load_motion palette shared by both weight variants"}
            np.savez_compressed(output / (row["key"] + ".npz"), baselineWorld=baseline["jointWorld"])
            comparison(output / (row["key"] + ".gif"), [targets[0]] + [image[0] for image in images], ["Source", "Prepared weights", "Unclipped source weights"], row["key"] + "; identical motion/bind")
    for path, expected in pinned.items():
        if sha256_file(Path(path)) != expected: raise ValueError("trial input changed during run")
    report["elapsedSeconds"] = time.perf_counter() - started
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, required=True); parser.add_argument("--corpus", type=Path, required=True); parser.add_argument("--registration", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); print(json.dumps(run(args.original.resolve(), args.corpus.resolve(), args.registration.resolve(), args.output.resolve()), indent=2))
