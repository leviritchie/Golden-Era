"""Attribute fitted-base surface violations without changing the fit."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from corpus_motion import load_motion
from motion_completion import restore_motion_completion
from fitted_corrective_base import load_fitted_base
from run_skin_mesh_pilot import (
    ROOT,
    SkinImageRenderer,
    _load_frozen_prep,
    comparison,
    deform,
    digest,
    expand_camera_to_full_canvas,
    sha256_file,
    validate_capture_indices,
)
from run_skin_weight_pilot import cascade_batch_lock, get_profile, source_images
from run_eagle_reference_capture_comparison import verify_source_identity
from skin_surface_constraints import triangle_principal_stretches
from surface_loss_attribution import attribute_surface


def _path(value: str | Path, base: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def _load_inputs(fit_dir: Path, asset: str):
    fit_report_path = fit_dir / "report.json"
    if not fit_report_path.is_file():
        raise FileNotFoundError(fit_report_path)
    fit_report = json.loads(fit_report_path.read_text(encoding="utf-8"))
    if fit_report.get("asset") != asset:
        raise ValueError("fit report asset does not match --asset")
    inputs = fit_report.get("inputs", {})
    corpus_path = Path(inputs.get("corpus", ""))
    if not corpus_path.is_file() or sha256_file(corpus_path) != inputs.get("corpusSha256"):
        raise ValueError("fit corpus missing or hash drifted")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    if corpus.get("unit") != asset:
        raise ValueError("corpus unit does not match asset")
    freeze, prepared = _load_frozen_prep(asset)
    prepared_path = Path(freeze["researchSkin"])
    prepared_sha = sha256_file(prepared_path)
    if prepared_sha != inputs.get("researchSkin"):
        raise ValueError("prepared skin hash drifted from fit report")
    baseline_dir = Path(fit_report.get("baselineDirectory", ""))
    baseline_report_path = baseline_dir / "pilot_report.json"
    baseline_report = json.loads(baseline_report_path.read_text(encoding="utf-8"))
    if baseline_report.get("inputs", {}).get("researchSkin") != prepared_sha:
        raise ValueError("baseline research skin hash differs from fit report")
    calibration_path = Path(fit_report["motionReference"]["path"])
    calibration_sha = sha256_file(calibration_path)
    if calibration_sha != fit_report["motionReference"]["sha256"]:
        raise ValueError("fit motion reference hash drifted")
    if calibration_sha != baseline_report["inputs"]["calibration"]:
        raise ValueError("baseline calibration hash drifted")
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    reference = np.asarray(calibration["referencePositions"], dtype=np.float64)
    hubs = tuple(get_profile(asset)["wholeBodyHubs"])
    motions = {}
    frame_paths = {}
    motion_hashes = {}
    seen_keys = set()
    for entry in corpus["captures"]:
        if entry["key"] in seen_keys:
            raise ValueError(f"duplicate corpus clip key: {entry['key']}")
        seen_keys.add(entry["key"])
        capture = _path(entry["capture"], corpus_path.parent)
        if sha256_file(capture) != entry["captureSha256"]:
            raise ValueError(f"capture hash drifted: {capture}")
        verify_source_identity(corpus, entry)
        with np.load(capture, allow_pickle=False) as raw:
            validate_capture_indices(entry, len(raw["pred_position"]))
            if list(raw["joint_names"].astype(str)) != list(prepared["names"]):
                raise ValueError(f"capture names differ from prepared skin: {entry['key']}")
            if not np.array_equal(raw["parents"], prepared["parents"]):
                raise ValueError(f"capture parents differ from prepared skin: {entry['key']}")
            motion = load_motion(raw, entry, corpus, prepared, reference, hubs)
            if not np.array_equal(np.asarray(motion["captureRest"]), reference):
                raise ValueError(f"motion captureRest differs from shared calibration: {entry['key']}")
            motions[entry["key"]] = motion
            frame_paths[entry["key"]] = [_path(value, corpus_path.parent) for value in entry["frames"]]
        motion_hashes[entry["key"]] = digest(motion["jointWorld"])
    motions = restore_motion_completion(motions, prepared, fit_report)
    motion_hashes = {key: digest(motion["jointWorld"]) for key, motion in motions.items()}
    if fit_report.get("cases") is None:
        raise ValueError("fit report lacks cases")
    for key, value in motion_hashes.items():
        if fit_report["cases"].get(key, {}).get("fixedMotionSha256") != value:
            raise ValueError(f"fixed motion hash drift: {key}")
    fitted, fit_provenance = load_fitted_base(
        fit_dir,
        asset,
        prepared,
        motion_hashes,
        inputs["corpusSha256"],
        prepared_sha,
    )
    return fit_report, corpus, freeze, prepared, fitted, calibration_path, motions, frame_paths, fit_provenance


def _face_debug_geometry(
    triangles: np.ndarray,
    selected: list[int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    expanded_triangles = np.arange(len(triangles) * 3, dtype=np.int64).reshape(-1, 3)
    expanded_uvs = np.empty((len(triangles) * 3, 2), dtype=np.float32)
    selected_set = set(int(value) for value in selected)
    texture = np.asarray([[[150, 150, 150], [220, 25, 25]]], dtype=np.uint8)
    for index in range(len(triangles)):
        u = 0.75 if index in selected_set else 0.25
        expanded_uvs[index * 3:(index + 1) * 3] = (u, 0.5)
    return expanded_triangles, expanded_uvs, texture


def _face_debug_renderer(
    triangles: np.ndarray,
    selected: list[int],
    camera: dict,
    resolution: int,
) -> tuple[SkinImageRenderer, np.ndarray]:
    expanded_triangles, expanded_uvs, texture = _face_debug_geometry(triangles, selected)
    return SkinImageRenderer(expanded_triangles, expanded_uvs, texture, camera, resolution), expanded_triangles


def run(asset: str, fit_dir: Path, output: Path) -> dict:
    started = time.perf_counter()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    fit_report, corpus, freeze, prepared, fitted, calibration_path, motions, frame_paths, fit_provenance = _load_inputs(fit_dir, asset)
    baseline_dir = Path(fit_report["baselineDirectory"])
    baseline_report_path = baseline_dir / "pilot_report.json"
    camera_path = baseline_dir / "camera.json"
    camera = json.loads(camera_path.read_text(encoding="utf-8"))
    camera = expand_camera_to_full_canvas(camera, 224)
    resolution = 224
    output.mkdir(parents=True)
    result = {
        "schema": "homm3.surface-loss-attribution.v1",
        "asset": asset,
        "fitDirectory": str(fit_dir.resolve()),
        "fitProvenance": fit_provenance,
        "calibrationPath": str(calibration_path.resolve()),
        "calibrationSha256": sha256_file(calibration_path),
        "inputs": {
            "corpus": str(Path(fit_report["inputs"]["corpus"]).resolve()),
            "corpusSha256": fit_report["inputs"]["corpusSha256"],
            "researchSkinSha256": fit_report["inputs"]["researchSkin"],
            "fitReportSha256": sha256_file(fit_dir / "report.json"),
            "baselineReportSha256": sha256_file(baseline_report_path),
            "cameraSha256": sha256_file(camera_path),
        },
        "camera": camera,
        "cases": {},
    }
    with cascade_batch_lock(ROOT):
        device = torch.device("cuda")
        rest = torch.as_tensor(fitted["vertices"], device=device, dtype=torch.float32)
        weights = torch.as_tensor(fitted["weights"], device=device, dtype=torch.float32)
        prepared_triangles = np.asarray(fitted["triangles"], dtype=np.int64)
        renderer = SkinImageRenderer(fitted["triangles"], fitted["uvs"], fitted["albedo"], camera, resolution)
        for key, motion in motions.items():
            transforms = torch.as_tensor((motion["jointWorld"] @ fitted["inverseBind"][None])[:, :, :3], device=device, dtype=torch.float32)
            meshes = deform(transforms, weights, rest).detach()
            stretches, valid, areas = triangle_principal_stretches(meshes, rest, torch.as_tensor(prepared_triangles, device=device))
            attribution = attribute_surface(stretches, valid, areas)
            values = stretches.detach()
            valid_values = values[:, valid]
            boundary_penalty_mean = float(
                (torch.relu(valid_values - 1.5).square() + torch.relu(0.67 - valid_values).square()).mean()
            )
            attribution["boundaryPenaltyMean"] = boundary_penalty_mean
            attribution["rankingScope"] = "per_clip_all_frames"
            selected = attribution["topTriangleIndices"]
            diagnostic_renderer, expanded_triangles = _face_debug_renderer(
                prepared_triangles, selected, camera, resolution
            )
            baseline_rgb, baseline_alpha = renderer.render(meshes)
            expanded_meshes = meshes[:, prepared_triangles].reshape(len(meshes), -1, 3)
            diagnostic_rgb, diagnostic_alpha = diagnostic_renderer.render(expanded_meshes)
            red = (diagnostic_rgb[..., 0] > 0.65) & (diagnostic_rgb[..., 1] < 0.25) & (diagnostic_rgb[..., 2] < 0.25) & (diagnostic_alpha[..., 0] > 0.1)
            visible_fraction = red.float().mean(dim=(1, 2)).detach().cpu().tolist()
            target_paths = frame_paths[key]
            source = source_images(target_paths, camera["sourceCrop"], resolution)
            comparison(output / f"{key}_surface_attribution.gif", [source[0], baseline_rgb, diagnostic_rgb], ("DEF", "Fitted base", "Top 1% surface faces"), f"{asset} {key}")
            arrays = {"selectedTriangleIndices": np.asarray(selected, dtype=np.int64), "stretches": stretches.detach().cpu().numpy(), "valid": valid.detach().cpu().numpy(), "areas": areas.detach().cpu().numpy()}
            np.savez_compressed(output / f"{key}_attribution.npz", **arrays)
            result["cases"][key] = {
                "frames": len(meshes),
                "fixedMotionSha256": digest(motion["jointWorld"]),
                "attribution": attribution,
                "visibleRedPixelFractionApprox": visible_fraction,
                "expandedFaceCorners": True,
                "captureSha256": sha256_file(
                    _path(
                        corpus["captures"][[row["key"] for row in corpus["captures"]].index(key)]["capture"],
                        Path(fit_report["inputs"]["corpus"]).parent,
                    )
                ),
            }
    result["elapsedSeconds"] = time.perf_counter() - started
    result["codeHashes"] = {
        name: sha256_file(Path(__file__).parent / name)
        for name in (
            "run_surface_loss_attribution.py",
            "surface_loss_attribution.py",
            "skin_surface_constraints.py",
            "fitted_corrective_base.py",
            "corpus_motion.py",
        )
    }
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", required=True)
    parser.add_argument("--fit-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.asset, args.fit_dir, args.output), indent=2))
