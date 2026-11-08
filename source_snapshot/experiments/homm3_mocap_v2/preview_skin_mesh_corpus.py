"""Render a cached mesh-field candidate across the complete capture corpus.

This is a read-only diagnostic: it never optimizes, refits motion, or scores a
source image.  The run directory is treated as an immutable candidate bundle.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from run_skin_mesh_pilot import (
    ROOT, _load_frozen_prep, comparison, deform, digest,
    reconstruct_adapted, sha256_file, SkinImageRenderer, validate_capture_indices,
)
from run_skin_weight_pilot import cascade_batch_lock, get_profile
from corpus_motion import load_motion
from motion_completion import restore_motion_completion

FOCUS = ("g00_move", "g12_attack_front", "g20_move_start", "g21_move_end", "g05_death")


def _path(value, base):
    path = Path(value)
    return path if path.is_absolute() else base / path


def _check_bundle(run_dir: Path, asset: str):
    report = json.loads((run_dir / "report.json").read_text())
    camera_path = run_dir / "camera.json"
    candidate_path = run_dir / "diagnostic_candidate.npz"
    if not camera_path.exists() or not candidate_path.exists():
        raise FileNotFoundError("run directory must contain report.json, camera.json, and diagnostic_candidate.npz")
    corpus_path = _path(report["inputs"]["corpus"], run_dir)
    if sha256_file(corpus_path) != report["inputs"]["corpusSha256"]:
        raise ValueError("corpus hash changed since fitting")
    corpus = json.loads(corpus_path.read_text())
    if corpus.get("unit") != asset:
        raise ValueError(f"corpus unit {corpus.get('unit')!r} does not match selected asset {asset!r}")
    for entry in corpus["captures"]:
        capture = _path(entry["capture"], corpus_path.parent)
        if sha256_file(capture) != entry["captureSha256"]:
            raise ValueError(f"capture hash changed: {capture}")
    for value, expected in corpus["sourceFrames"].items():
        if sha256_file(_path(value, corpus_path.parent)) != expected["sha256"]:
            raise ValueError(f"source frame hash changed: {value}")
    manifest = _path(corpus["manifest"], corpus_path.parent)
    if sha256_file(manifest) != corpus["manifestSha256"]:
        raise ValueError("corpus manifest hash changed")
    baseline = _path(report["baselineDirectory"], run_dir)
    baseline_report = json.loads((baseline / "pilot_report.json").read_text())
    freeze, skin = _load_frozen_prep(asset)
    research = Path(freeze["researchSkin"])
    if sha256_file(research) != report["inputs"]["researchSkin"] or sha256_file(research) != baseline_report["inputs"]["researchSkin"]:
        raise ValueError("research skin hash changed since fitting")
    reference = report.get("motionReference")
    if not reference or "path" not in reference or "sha256" not in reference:
        raise ValueError("candidate report lacks shared motionReference; refusing per-capture fallback")
    reference_path = _path(reference["path"], run_dir)
    if sha256_file(reference_path) != reference["sha256"]:
        raise ValueError("shared motion reference changed since fitting")
    payload = json.loads(reference_path.read_text())
    reference_positions = np.asarray(payload["referencePositions"], dtype=np.float64)
    if reference_positions.ndim != 2 or reference_positions.shape[1:] != (3,):
        raise ValueError("shared motion reference must be [J,3]")
    return report, corpus, skin, camera_path, candidate_path, reference_positions


def _offaxis_union_camera(camera, meshes, resolution=320):
    """Rotate the source basis 90 degrees in yaw and frame every mesh."""
    right = np.asarray(camera["right"], dtype=np.float64)
    down = np.asarray(camera["down"], dtype=np.float64)
    forward = np.asarray(camera["forward"], dtype=np.float64)
    # A true quarter-turn, not a cosmetic offset: old right becomes negative
    # view direction and old forward becomes screen-right.
    rotated_right, rotated_forward = forward / np.linalg.norm(forward), -right / np.linalg.norm(right)
    projected = np.concatenate([np.asarray(mesh).reshape(-1, 3) for mesh in meshes], axis=0)
    x = projected @ rotated_right
    y = projected @ down / max(np.linalg.norm(down), 1e-12)
    z = projected @ rotated_forward
    span_xy = max(float(np.ptp(x)), float(np.ptp(y)), 1e-6) * 1.12
    result = dict(camera)
    result.update({"right": rotated_right.tolist(), "down": (down / np.linalg.norm(down)).tolist(),
                   "forward": rotated_forward.tolist(), "resolution": int(resolution),
                   "scale": (resolution - 1) / span_xy,
                   "offset": [float((resolution - 1) / 2 - (x.min() + x.max()) / 2 * (resolution - 1) / span_xy),
                              float((resolution - 1) / 2 - (y.min() + y.max()) / 2 * (resolution - 1) / span_xy)],
                   "depth_center": float((z.min() + z.max()) / 2),
                   "depth_span": max(float(np.ptp(z)) * .56, 1e-5)})
    return result


def run(run_dir: Path, output: Path, *, asset: str = "h3_roc", repair_report: Path | None = None,
        skin_refit_report: Path | None = None):
    if repair_report is not None and skin_refit_report is not None:
        raise ValueError("select one saved repair or skin-refit report")
    if skin_refit_report is not None:
        from run_attachment_skin_refit import preview as preview_skin_refit
        return preview_skin_refit(run_dir, skin_refit_report, output, asset)
    if repair_report is not None:
        from run_attachment_repair import preview_repair
        return preview_repair(run_dir, repair_report, output, asset)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    report, corpus, skin, camera_path, candidate_path, reference_positions = _check_bundle(run_dir, asset)
    if report.get("asset", asset) != asset:
        raise ValueError("candidate report asset does not match selected asset")
    output.mkdir(parents=True)
    with np.load(candidate_path, allow_pickle=False) as candidate:
        weights = candidate["weights"]
        weight_only = candidate["weight_only"]
        adapted_vertices = candidate["vertices"]
        if list(candidate["names"].astype(str)) != list(skin["names"]):
            raise ValueError("candidate skeleton names differ from research skin")
    if weights.shape != weight_only.shape or weights.shape != skin["weights"].shape or adapted_vertices.shape != skin["vertices"].shape:
        raise ValueError("candidate dimensions differ from research skin")
    camera = json.loads(camera_path.read_text())
    renderer = None
    motions, frame_paths = {}, {}
    for entry in corpus["captures"]:
        key = entry["key"]
        capture_path = _path(entry["capture"], _path(report["inputs"]["corpus"], run_dir).parent)
        with np.load(capture_path, allow_pickle=False) as raw:
            validate_capture_indices(entry, len(raw["pred_position"]))
            positions = raw["pred_position"][entry["sourceIndices"]]
            motions[key] = load_motion(raw, entry, corpus, skin, reference_positions, get_profile(asset)["wholeBodyHubs"])
        frame_paths[key] = [_path(path, _path(report["inputs"]["corpus"], run_dir).parent) for path in entry["frames"]]
    motions = restore_motion_completion(motions, skin, report)
    for key, motion in motions.items():
        if digest(motion["jointWorld"]) != report["cases"][key]["fixedMotionSha256"]:
            raise ValueError("reconstructed motion differs from fitted motion")
    # Build all 15 candidate mesh sequences before allocating the renderer so
    # the one rotated camera is framed against the full corpus union.
    all_meshes = []
    for key, motion in motions.items():
        transforms = torch.as_tensor((motion["jointWorld"] @ skin["inverseBind"][None])[:, :, :3], dtype=torch.float32)
        all_meshes.extend([deform(transforms, torch.as_tensor(value, dtype=torch.float32), torch.as_tensor(rest, dtype=torch.float32)).numpy()
                           for value, rest in ((skin["weights"], skin["vertices"]), (weight_only, skin["vertices"]), (weights, adapted_vertices))])
    camera = _offaxis_union_camera(camera, all_meshes, resolution=320)
    with cascade_batch_lock(ROOT):
        renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], camera, 320, device="cuda")
        device = torch.device("cuda")
        original_weights = torch.as_tensor(skin["weights"], device=device, dtype=torch.float32)
        cached_weights = torch.as_tensor(weight_only, device=device, dtype=torch.float32)
        cached_final = torch.as_tensor(weights, device=device, dtype=torch.float32)
        original_rest = torch.as_tensor(skin["vertices"], device=device, dtype=torch.float32)
        adapted_rest = torch.as_tensor(adapted_vertices, device=device, dtype=torch.float32)
        for key, motion in motions.items():
            if key not in FOCUS:
                continue
            transforms = torch.as_tensor((motion["jointWorld"] @ skin["inverseBind"][None])[:, :, :3], device=device, dtype=torch.float32)
            meshes = [deform(transforms, value, rest) for value, rest in (
                (original_weights, original_rest), (cached_weights, original_rest), (cached_final, adapted_rest))]
            renderings = [renderer.render(mesh)[0] for mesh in meshes]
            comparison(output / f"{key}_comparison.gif", renderings,
                        ("Original", "Weight only", "Adapted rest + weights"), f"Off-angle {key}")
            print(json.dumps({"clip": key, "focus": key in FOCUS,
                              "comparison": str(output / f"{key}_comparison.png")}), flush=True)
    (output / "preview_manifest.json").write_text(json.dumps({"proof": "generated-candidate", "camera": camera,
        "sourceRun": str(run_dir), "focusClips": list(FOCUS), "allCorpusClips": list(motions),
        "noOptimization": True, "noSourceScore": True, "fixedMotion": True}, indent=2) + "\n")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--asset", default="h3_roc", help="asset profile id; defaults to h3_roc for compatibility")
    parser.add_argument("--repair-report", type=Path, help="explicit saved attachment-repair candidate")
    parser.add_argument("--skin-refit-report", type=Path, help="explicit saved post-separation skin candidate")
    args = parser.parse_args()
    print(json.dumps({"output": str(run(args.run_dir.resolve(), args.output.resolve(), asset=args.asset,
                                       repair_report=args.repair_report, skin_refit_report=args.skin_refit_report))}))


if __name__ == "__main__":
    main()
