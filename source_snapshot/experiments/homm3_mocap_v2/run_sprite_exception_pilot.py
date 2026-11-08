"""Explicit source-frame surface correction after a measured pose-fit conflict.

Diagnostic only: fixed topology, texture, camera, skeleton and skin. The output
is a vertex sequence, not a deliverable skeletal animation or accepted mesh.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

from run_linked_master_pipeline import load_candidate_weights, pose_master
from gpu_cascade_batch_lock import cascade_batch_lock
from paths import REPO
from pin import sha256_file
from pose_rotation_fk import fk_world, skin_lbs
from pose_representation_exception import detect_conflicts
from run_move_bind_t2_mocap_skin_fit import load_fixed_motion, load_skin_bundle
from run_skin_weight_pilot import shared_canvas_source_images
from run_roc_wing_pose_refine import yawed_camera
from skin_image_objective import SkinImageRenderer, image_loss, image_metrics
from skin_surface_constraints import triangle_principal_stretches, surface_constraint_metrics
from sprite_surface_residual import SpriteSurfaceResidual


def face_error(buffers, target_rgb, target_alpha, face_count):
    """Visible residual ownership only; missing source pixels have no mesh owner."""
    error = torch.relu(buffers["alpha"] - target_alpha)[..., 0]
    error = error + .1 * torch.abs(buffers["rgb"] - target_rgb).sum(-1) * buffers["alpha"][..., 0]
    ids = buffers["triangleId"].cpu().numpy()
    values = error.cpu().numpy()
    result = np.zeros((len(ids), face_count), dtype=np.float32)
    coverage = np.zeros_like(result)
    for frame in range(len(ids)):
        visible = ids[frame] >= 0
        coverage[frame] = np.bincount(ids[frame][visible], minlength=face_count)
        error_sum = np.bincount(ids[frame][visible], weights=values[frame][visible], minlength=face_count)
        result[frame] = np.divide(error_sum, coverage[frame], out=np.zeros(face_count), where=coverage[frame] > 0)
    return result, coverage


def topology_support(triangles, seed_faces, rings):
    """Expand sparse diagnostic witnesses by a fixed source-topology neighborhood."""
    support = np.zeros(int(np.max(triangles)) + 1, dtype=bool)
    support[np.unique(triangles[seed_faces])] = True
    for _ in range(rings):
        support[np.unique(triangles[np.any(support[triangles], axis=1)])] = True
    return np.flatnonzero(support).tolist()


def require_pose_parity(reproduced, expected):
    if reproduced.shape != expected.shape:
        raise ValueError("reconstructed pose shape differs")
    error = float(torch.max(torch.abs(reproduced - expected)))
    if not np.isfinite(error) or error > 1e-5:
        raise ValueError(f"candidate is not reproduced by its rotations and frozen skin: {error}")
    return error


def save_comparison(path, panels, labels, frame_ms):
    """One fixed crop and scale across every frame and comparison panel."""
    occupied = np.any(np.stack(panels).max(axis=(0, 1)) > .01, axis=-1)
    y, x = np.where(occupied)
    if not len(x):
        raise ValueError("blank comparison")
    left, right = max(0, int(x.min()) - 6), min(occupied.shape[1], int(x.max()) + 7)
    top, bottom = max(0, int(y.min()) - 6), min(occupied.shape[0], int(y.max()) + 7)
    width, height = max(160, right - left), bottom - top
    rows = []
    for frame in range(len(panels[0])):
        row = Image.new("RGB", (width * len(panels), height + 32), (12, 12, 16))
        draw = ImageDraw.Draw(row)
        for column, (pixels, label) in enumerate(zip(panels, labels)):
            draw.text((column * width + 4, 3), label, fill="white")
            draw.text((column * width + 4, 17), f"source frame {frame}", fill=(190, 190, 195))
            crop = np.uint8(np.clip(pixels[frame, top:bottom, left:right], 0, 1) * 255)
            row.paste(Image.fromarray(crop), (column * width + (width - (right - left)) // 2, 32))
        rows.append(row.resize((row.width * 2, row.height * 2), Image.Resampling.NEAREST))
    durations = [10 * (round((i + 1) * frame_ms / 10) - round(i * frame_ms / 10)) for i in range(len(rows))]
    rows[0].save(path, save_all=True, append_images=rows[1:], duration=durations, loop=0)
    rows[0].save(path.with_suffix(".png"))


def run(args):
    started = time.perf_counter()
    if args.output.exists():
        raise FileExistsError("choose a new output directory; this pilot never overwrites")
    if len(args.candidate) < 2 or len({sha256_file(p) for p in args.candidate}) != len(args.candidate):
        raise ValueError("provide at least two distinct prior pose candidates")
    saved = json.loads((args.linked / "report.json").read_text(encoding="utf-8"))
    master_path = args.linked / "master_sequence/master_sequence.json"
    master = json.loads(master_path.read_text(encoding="utf-8"))
    if master["unit"] != saved["unit"]:
        raise ValueError("source unit mismatch")
    for path, key in ((saved["capture"], "captureSha256"), (saved["bindGlb"], "bindSha256")):
        if sha256_file(Path(path)) != saved[key]:
            raise ValueError(f"source hash drift: {key}")
    sprites = [Path(frame["numberedPng"]) for frame in master["frames"]]
    for path, frame in zip(sprites, master["frames"]):
        if sha256_file(path) != frame["sourceSha256"]:
            raise ValueError(f"sprite hash drift: {path}")
    segments = [s for s in master["segments"] if s["clipKey"] == args.clip_key and s["exportsClip"]]
    if len(segments) != 1:
        raise ValueError("clip selection must identify exactly one exported source clip")
    indices = list(range(segments[0]["globalStart"], segments[0]["globalEnd"]))
    if len(indices) < 2:
        raise ValueError("pilot requires an animated source clip")
    frame_ms = float(master["sourceFrameMs"])
    if not np.isfinite(frame_ms) or frame_ms < 10:
        raise ValueError("source timing must be finite and at least one GIF centisecond")
    camera_path = args.linked / "skin_fit/camera.json"
    weights_path = args.linked / "skin_fit/candidate_weights.npz"
    camera = json.loads(camera_path.read_text(encoding="utf-8"))
    skin = load_skin_bundle(Path(saved["bindGlb"]))
    weights = load_candidate_weights(weights_path, skin)
    motion = load_fixed_motion(skin, Path(saved["capture"]), reference_frame=int(master["bindGlobalIndex"]))
    original = pose_master(skin, motion, weights)
    candidates, candidate_locals = [], []
    for path in args.candidate:
        with np.load(path, allow_pickle=False) as payload:
            if not np.allclose(payload["originalVertices"], original, rtol=0, atol=1e-6):
                raise ValueError(f"candidate baseline vertices differ: {path}")
            if not np.allclose(payload["originalLocalRotation"], motion["localRotation"], rtol=0, atol=1e-6):
                raise ValueError(f"candidate motion lineage differs: {path}")
            value = payload["correctedVertices"].copy()
            local = payload["correctedLocalRotation"].copy()
        if value.shape != original.shape or not np.isfinite(value).all():
            raise ValueError("candidate must contain finite comparable vertex frames")
        if local.shape != motion["localRotation"].shape or not np.isfinite(local).all():
            raise ValueError("candidate local rotations have wrong shape or nonfinite values")
        if any(np.allclose(local, prior, rtol=0, atol=1e-5) for prior in candidate_locals):
            raise ValueError("duplicate corrected pose content cannot count as another trial")
        candidates.append(value)
        candidate_locals.append(local)
    args.output.mkdir(parents=True)
    with cascade_batch_lock(REPO):
        targets, crop, size = shared_canvas_source_images(sprites, int(camera["resolution"]))
        if any(crop[k] != camera["sourceCrop"][k] for k in ("left", "top", "size")) or list(size) != camera["sourceSize"]:
            raise ValueError("source camera/canvas mismatch")
        renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], camera, int(camera["resolution"]))
        base = torch.as_tensor(original, device="cuda", dtype=torch.float32)
        rest = torch.as_tensor(skin["vertices"], device="cuda", dtype=torch.float32)
        with torch.no_grad():
            buffers = renderer.render_buffers(base)
            base_metrics = image_metrics(buffers["rgb"], buffers["alpha"], targets[0], targets[1])
            base_error, base_coverage = face_error(buffers, targets[0], targets[1], len(skin["triangles"]))
            base_rgb = buffers["rgb"].cpu().numpy()
            base_stretches, valid, areas = triangle_principal_stretches(base, rest, skin["triangles"])
            trial_iou, trial_stretches, trial_errors, trial_coverage, parity_errors = [], [], [], [], []
            offsets = torch.as_tensor(skin["offsets"], device="cuda", dtype=torch.float32).clone()
            offsets[0] = 0.
            root = torch.as_tensor(motion["jointWorld"][:, 0, :3, 3], device="cuda", dtype=torch.float32)
            inverse_bind = torch.as_tensor(skin["inverseBind"], device="cuda", dtype=torch.float32)
            weight_tensor = torch.as_tensor(weights, device="cuda", dtype=torch.float32)
            for candidate, local in zip(candidates, candidate_locals):
                verts = torch.as_tensor(candidate, device="cuda", dtype=torch.float32)
                world = fk_world(torch.as_tensor(local, device="cuda", dtype=torch.float32), offsets, skin["parents"], root)
                reproduced = skin_lbs(world, inverse_bind, rest, weight_tensor)
                parity_error = require_pose_parity(reproduced, verts)
                parity_errors.append(parity_error)
                rendered = renderer.render_buffers(verts)
                trial_iou.append([m["iou"] for m in image_metrics(rendered["rgb"], rendered["alpha"], targets[0], targets[1])])
                residual, coverage = face_error(rendered, targets[0], targets[1], len(skin["triangles"]))
                trial_errors.append(residual)
                trial_coverage.append(coverage)
                trial_stretches.append(triangle_principal_stretches(verts, rest, skin["triangles"])[0].cpu().numpy())
            detection = detect_conflicts(
                baseline_iou=[m["iou"] for m in base_metrics], candidate_iou=np.array(trial_iou),
                baseline_stretches=base_stretches.cpu().numpy(), candidate_stretches=np.array(trial_stretches),
                valid_faces=valid.cpu().numpy(), visible_face_error=base_error,
                candidate_visible_face_error=np.array(trial_errors), triangles=skin["triangles"],
                visible_face_coverage=base_coverage, candidate_visible_face_coverage=np.array(trial_coverage),
            )
        (args.output / "detection.json").write_text(json.dumps(detection, indent=2) + "\n", encoding="utf-8")
        if args.diagnose_only:
            print(json.dumps({"detection": str(args.output / "detection.json"), "selectedClip": args.clip_key}))
            return
        selected_rows = [detection["perFrame"][i] for i in indices]
        conflict_faces = sorted({face for row in selected_rows for face in row["conflictFaceIds"]})
        support = topology_support(skin["triangles"], conflict_faces, args.support_rings)
        if not support:
            raise ValueError("selected source clip has no repeated localized conflict; no correction authorized")
        field = SpriteSurfaceResidual(skin["vertices"], weights, support, len(indices), device="cuda")
        baseline = base[indices].detach()
        original_s = base_stretches[indices].detach()
        face_weights = areas[valid] / areas[valid].sum()
        triangles = torch.as_tensor(skin["triangles"], device="cuda", dtype=torch.long)
        edges_np = np.unique(np.sort(np.concatenate([skin["triangles"][:, [0, 1]], skin["triangles"][:, [1, 2]], skin["triangles"][:, [2, 0]]]), axis=1), axis=0)
        edges = torch.as_tensor(edges_np, device="cuda", dtype=torch.long)
        scale = float(np.linalg.norm(np.ptp(skin["vertices"], axis=0)))
        optimizer = torch.optim.Adam(field.parameters(), lr=.001)
        best, best_loss, history = None, float("inf"), []
        fit_started = time.perf_counter()
        step = 0
        while time.perf_counter() - fit_started < args.seconds:
            progress = min(1., (time.perf_counter() - fit_started) / args.seconds)
            optimizer.param_groups[0]["lr"] = .001 * (1. - .9 * progress)
            optimizer.zero_grad(set_to_none=True)
            delta = field.displacement()
            verts = baseline + delta
            rgb, alpha = renderer.render(verts)
            photo = image_loss(rgb, alpha, targets[0][indices], targets[1][indices], targets[2][indices])
            s, _, _ = triangle_principal_stretches(verts, rest, triangles)
            over = torch.relu(s[..., 0] - original_s[..., 0].clamp_min(1.5))
            under = torch.relu(original_s[..., 1].clamp_max(.67) - s[..., 1])
            damage = (over.square() + under.square())[:, valid]
            geometry = (damage * face_weights).sum(-1).mean() + damage.topk(max(1, damage.shape[1] // 100), dim=1).values.mean()
            smooth = ((delta[:, edges[:, 0]] - delta[:, edges[:, 1]]) / scale).square().mean()
            temporal = ((delta[1:] - delta[:-1]) / scale).square().mean()
            if args.loop:
                temporal = temporal + ((delta[-1] - delta[0]) / scale).square().mean()
            depth = (delta @ torch.as_tensor(camera["forward"], device="cuda", dtype=torch.float32) / scale).square().mean()
            loss = photo["total"] + 2 * geometry + 5 * smooth + 5 * temporal + .2 * depth + .02 * (delta / scale).square().mean()
            if not torch.isfinite(loss):
                raise ValueError("nonfinite correction objective")
            if float(loss.detach()) < best_loss:
                best_loss = float(loss.detach())
                best = delta.detach().clone()
            loss.backward()
            if any(p.grad is None or not torch.isfinite(p.grad).all() for p in field.parameters()):
                raise ValueError("nonfinite or disconnected correction gradient")
            torch.nn.utils.clip_grad_norm_(field.parameters(), 2.)
            optimizer.step()
            step += 1
            if step == 1 or step % 500 == 0:
                history.append({"step": step, "loss": float(loss.detach()), "image": float(photo["total"].detach()), "geometry": float(geometry.detach())})
                print(json.dumps(history[-1]), flush=True)
        fit_seconds = time.perf_counter() - fit_started
        if best is None:
            raise ValueError("no correction step completed")
        with torch.no_grad():
            corrected = baseline + best
            corrected_rgb, corrected_alpha = renderer.render(corrected)
            metrics = image_metrics(corrected_rgb, corrected_alpha, targets[0][indices], targets[1][indices])
            new_s, _, _ = triangle_principal_stretches(corrected, rest, triangles)
            changed_rgb = corrected_rgb.cpu().numpy()
            side_camera = yawed_camera(camera, 90., original[indices[0]].mean(axis=0))
            side_renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], side_camera, int(camera["resolution"]))
            side_before = side_renderer.render(baseline)[0].cpu().numpy()
            side_after = side_renderer.render(corrected)[0].cpu().numpy()
            support_mask = field.support_mask.cpu().numpy()
            before_quality = surface_constraint_metrics(original_s, valid, areas)
            after_quality = surface_constraint_metrics(new_s, valid, areas)
        full = original.copy()
        full[indices] = corrected.cpu().numpy()
        untouched = np.ones(len(full), dtype=bool)
        untouched[indices] = False
        if not np.array_equal(full[untouched], original[untouched]) or not np.array_equal(full[indices][:, ~support_mask], original[indices][:, ~support_mask]):
            raise ValueError("correction escaped its selected frames/surface support")
        source_rgb = targets[0][indices].cpu().numpy()
    save_comparison(args.output / "comparison.gif", [source_rgb, base_rgb[indices], changed_rgb], ["Source", "Original", "Surface trial - unaccepted"], frame_ms)
    save_comparison(args.output / "side90.gif", [side_before, side_after], ["Original side view", "Trial side - unaccepted"], frame_ms)
    np.savez_compressed(args.output / "surface_candidate.npz", originalVertices=original, correctedVertices=full, selectedFrames=np.array(indices), supportMask=support_mask)
    result = {
        "proof": "explicit sprite-frame surface adjustment diagnostic", "accepted": False,
        "visualAcceptance": "unaccepted", "runtimeExportAvailable": False,
        "motionAuthority": "source-frame residual geometry; not captured motion or skin-only fitting",
        "unit": saved["unit"], "clipKey": args.clip_key, "selectedFrames": indices,
        "loopResidualRegularized": args.loop, "transitionsValidated": False,
        "outsideSelectedFramesExact": True, "outsideSelectedSurfaceExact": True,
        "supportVertexCount": int(support_mask.sum()), "vertexCount": len(support_mask),
        "supportPolicy": "repeated_conflict_faces_plus_explicit_topology_rings_and_proven_duplicates",
        "supportRings": args.support_rings, "selectedConflictFaceCount": len(conflict_faces),
        "poseTrialReconstructionMaxErrors": parity_errors,
        "sourceFrameMs": frame_ms, "maxDisplacement": float(torch.linalg.vector_norm(best, dim=-1).max()),
        "maxAllowedDisplacement": field.max_displacement,
        "beforeIou": [base_metrics[i]["iou"] for i in indices], "afterIou": [m["iou"] for m in metrics],
        "beforeSurface": before_quality, "afterSurface": after_quality,
        "fitSeconds": fit_seconds, "steps": step, "history": history,
        "inputs": {"linkedReport": sha256_file(args.linked / "report.json"), "master": sha256_file(master_path),
                   "camera": sha256_file(camera_path), "weights": sha256_file(weights_path),
                   "candidateTrials": [{"path": str(p.resolve()), "sha256": sha256_file(p)} for p in args.candidate]},
        "elapsedSeconds": time.perf_counter() - started,
    }
    (args.output / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gif": str(args.output / "comparison.gif"), "supportVertices": result["supportVertexCount"], "steps": step, "accepted": False}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linked", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, action="append", required=True)
    parser.add_argument("--clip-key", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=120.)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--diagnose-only", action="store_true")
    parser.add_argument("--support-rings", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 120:
        raise ValueError("diagnostic fit budget must be 1..120 seconds")
    if not 0 <= args.support_rings <= 4:
        raise ValueError("support rings must be 0..4; no automatic support expansion")
    run(args)
