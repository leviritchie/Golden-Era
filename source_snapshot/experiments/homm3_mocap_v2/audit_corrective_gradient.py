"""CPU/GPU diagnostic attribution of pose-corrective objective gradients."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from fitted_corrective_base import _sha
from pose_corrective_field import PoseCorrectiveField
from run_pose_corrective_pilot import split_frames
from run_skin_weight_pilot import cascade_batch_lock, image_loss, source_images, SkinImageRenderer, ROOT
from run_surface_loss_attribution import _load_inputs
from skin_surface_constraints import SurfaceConstraints
from run_skin_mesh_pilot import expand_camera_to_full_canvas
from validate_pose_corrective_artifact import _check_hashes

HERE = Path(__file__).resolve().parent


def _flat(grads, controls):
    return torch.cat([g.reshape(-1) for g in grads])


def _stats(terms, controls):
    grads = {}
    for name, value in terms.items():
        grads[name] = _flat(torch.autograd.grad(value, controls, retain_graph=True, allow_unused=False), controls)
    total = sum(grads.values(), torch.zeros_like(next(iter(grads.values()))))
    norms = {name: float(vector.norm()) for name, vector in grads.items()}
    total_norm = float(total.norm())
    pairwise = {}
    names = list(grads)
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            denom = grads[left].norm() * grads[right].norm()
            pairwise[f"{left}:{right}"] = float(torch.dot(grads[left], grads[right]) / denom) if float(denom) else None
    image_gradient = grads["image"]
    dot = float(torch.dot(image_gradient, total))
    descent_alignment = float(torch.dot(image_gradient, -total) /
                              (image_gradient.norm() * total.norm())) if image_gradient.norm() and total.norm() else None
    values = {name: float(value.detach()) for name, value in terms.items()}
    if not all(np.isfinite(list(values.values()) + list(norms.values()) + [total_norm, dot])):
        raise ValueError("non-finite objective or gradient attribution")
    return {"values": values, "norms": norms, "totalNorm": total_norm, "pairwiseCosine": pairwise,
            "imageTotalDot": dot, "imageDescentAlignment": descent_alignment}


def _feature_energy(local, neutral, basis, names, subsets):
    features = (local - neutral[None]).reshape(len(local), -1)
    projected = features @ basis
    residual = features - projected @ basis.T
    result = {}
    for label, selection in subsets.items():
        x, p, e = features[selection], projected[selection], residual[selection]
        full = float(np.square(x).sum())
        retained = float(np.square(p).sum())
        joint_error = np.square(e.reshape(len(e), len(names), 9)).sum(axis=(0, 2))
        largest = np.argsort(-joint_error, kind='stable')[:5]
        result[label] = dict(fullEnergy=full, retainedEnergy=retained,
            retainedFraction=retained / full if full > 0 else None,
            largestResidualJoints=[dict(name=str(names[j]), energy=float(joint_error[j])) for j in largest])
    return result


def audit(asset: str, fit_dir: Path, corrective_dir: Path, output: Path):
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    fit_report, corpus, freeze, prepared, fitted, calibration_path, motions, frame_paths, fit_provenance = _load_inputs(fit_dir, asset)
    report_path = corrective_dir / "report.json"
    state_path = corrective_dir / "corrective_field.pt"
    mesh_path = corrective_dir / "candidate_meshes.npz"
    if not report_path.is_file() or not state_path.is_file() or not mesh_path.is_file():
        raise FileNotFoundError("corrective directory requires report.json, corrective_field.pt, candidate_meshes.npz")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("asset") != asset:
        raise ValueError("corrective report asset differs")
    checked_hashes = _check_hashes(report)
    with np.load(mesh_path, allow_pickle=False) as arrays:
        candidate_saved = np.asarray(arrays["candidate"], dtype=np.float64).copy()
        baseline_saved = np.asarray(arrays["baseline"], dtype=np.float64).copy()
        local_np = np.asarray(arrays["localRotation"], dtype=np.float64).copy()
    ordered = list(motions)
    reconstructed_local = np.concatenate([motions[key]["localRotation"] for key in ordered])
    if local_np.shape != reconstructed_local.shape or not np.allclose(local_np, reconstructed_local, rtol=0, atol=1e-6):
        raise ValueError("saved localRotation differs from reconstructed fixed motion")
    train = np.asarray(report.get("trainIndices", []), dtype=np.int64)
    neutral = np.repeat(np.eye(3)[None], len(fitted["names"]), axis=0)
    frozen = tuple(report.get("frozenRegions", ()))
    expected_train, expected_held, slices = split_frames({key: len(frame_paths[key]) for key in ordered})
    if train.tolist() != expected_train or report.get("heldoutIndices") != expected_held:
        raise ValueError("corrective report train/heldout indices differ from fixed split")
    device = torch.device("cuda")
    camera = expand_camera_to_full_canvas(json.loads((Path(fit_report["baselineDirectory"]) / "camera.json").read_text()), 224)
    report_hashes = {**checked_hashes, str(report_path.resolve()): _sha(report_path), str(mesh_path.resolve()): _sha(mesh_path),
                     str(state_path.resolve()): _sha(state_path), str((fit_dir / "report.json").resolve()): _sha(fit_dir / "report.json")}
    with cascade_batch_lock(ROOT):
        field = PoseCorrectiveField(fitted["vertices"], fitted["regions"], local_np[train], neutral,
                                    frozen_regions=frozen, max_displacement_fraction=.10,
                                    grid_resolution=4, device=device)
        state = torch.load(state_path, weights_only=True, map_location=device)
        for key, expected in field.state_dict().items():
            if key not in state:
                raise ValueError(f"corrective state missing {key}")
            if not key.endswith(".control") and not torch.equal(expected, state[key].to(device=expected.device)):
                raise ValueError(f"corrective static state drift: {key}")
        field.load_state_dict(state, strict=True)
        feature_energy = _feature_energy(local_np, neutral,
            field.feature_basis.detach().cpu().numpy(), fitted['names'],
            {'all': slice(None), 'train': expected_train, 'held': expected_held, **slices})
        local = torch.as_tensor(local_np, device=device, dtype=torch.float32)
        rest = torch.as_tensor(fitted["vertices"], device=device, dtype=torch.float32)
        weights = torch.as_tensor(fitted["weights"], device=device, dtype=torch.float32)
        transforms = torch.as_tensor(np.concatenate([(motions[key]["jointWorld"] @ fitted["inverseBind"][None])[:, :, :3] for key in ordered]), device=device, dtype=torch.float32)
        blended = (weights @ transforms.permute(1, 0, 2, 3).reshape(transforms.shape[1], -1)).reshape(
            len(weights), len(local), 3, 4).permute(1, 0, 2, 3)
        baseline = torch.einsum("fvkl,vl->fvk", blended, torch.cat((rest, torch.ones_like(rest[:, :1])), 1)).detach()
        if baseline.shape != baseline_saved.shape or not np.allclose(baseline.cpu().numpy(), baseline_saved, rtol=0, atol=1e-6):
            raise ValueError("saved baseline differs from reconstructed LBS baseline")
        renderer = SkinImageRenderer(fitted["triangles"], fitted["uvs"], fitted["albedo"], camera, 224)
        surface = SurfaceConstraints(fitted["vertices"], fitted["triangles"], device=device)
        targets = {key: source_images(frame_paths[key], camera["sourceCrop"], 224) for key in ordered}
        all_targets = tuple(torch.cat([targets[key][c] for key in ordered]) for c in range(3))
        train_list, _, slices = split_frames({key: len(frame_paths[key]) for key in ordered})
        train_t = torch.as_tensor(train_list, device=device, dtype=torch.long)
        idle_slice = slices["g02_idle"]
        controls = tuple(mode.control for mode in field.modes)
        saved_controls = [control.detach().clone() for control in controls]
        zero_controls = [torch.zeros_like(control) for control in controls]
        def evaluate(control_state):
            with torch.no_grad():
                for control, value in zip(controls, control_state):
                    control.copy_(value)
            displacement = field.displacement(local)
            animated = baseline + torch.einsum("fvkl,fvl->fvk", blended[:, :, :, :3], displacement)
            image = 10 * image_loss(*renderer.render(animated[train_t]), *[target[train_t] for target in all_targets])["total"]
            geometry = 3 * surface.loss(animated)
            idle_rgb, idle_alpha = renderer.render(animated[idle_slice])
            base_rgb, base_alpha = renderer.render(baseline[idle_slice])
            idle = 40 * ((idle_rgb - base_rgb).abs().mean() + (idle_alpha - base_alpha).abs().mean())
            field_term = 2 * field.penalty()
            terms = {"image": image, "geometry": geometry, "idle": idle, "field": field_term}
            return _stats(terms, controls)
        zero_stats = evaluate(zero_controls)
        saved_stats = evaluate(saved_controls)
        saved_candidate = (baseline + torch.einsum("fvkl,fvl->fvk", blended[:, :, :, :3], field.displacement(local))).detach()
        if saved_candidate.shape != candidate_saved.shape or not np.allclose(saved_candidate.cpu().numpy(), candidate_saved, rtol=0, atol=1e-6):
            raise ValueError("saved candidate differs from reconstructed corrective field")
    result = {"schema": "homm3.corrective-gradient-audit.v1", "asset": asset,
              "accepted": False, "proof": "gradient attribution only; no optimization or promotion",
              "fitDirectory": str(fit_dir.resolve()), "correctiveDirectory": str(corrective_dir.resolve()),
              "fitProvenance": fit_provenance, "inputHashes": report_hashes,
              "implementationHashes": {name: _sha(HERE / name) for name in
                  ("audit_corrective_gradient.py", "pose_corrective_field.py", "run_pose_corrective_pilot.py",
                   "run_surface_loss_attribution.py", "skin_surface_constraints.py", "skin_image_objective.py",
                   "fitted_corrective_base.py")},
              "zeroControls": zero_stats, "savedControls": saved_stats,
              "featureEnergy": feature_energy,
              "frameCount": int(len(local_np)), "trainCount": int(len(train_list))}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", required=True)
    parser.add_argument("--fit-dir", type=Path, required=True)
    parser.add_argument("--corrective-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.asset, args.fit_dir, args.corrective_dir, args.output), indent=2))
