"""Compare constrained skinning with one shared, bounded rest-mesh adaptation."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

from run_skin_weight_pilot import (
    ROOT, HERE,
    _load_frozen_prep, _write_json, sha256_file, digest,
    source_images, SkinImageRenderer,
    image_loss, image_metrics, cascade_batch_lock, SOURCE_FRAME_MS,
    write_skinned_glb, matrices_to_xyzw, verify_calibrated_export,
    validate_candidate_weights, get_profile,
)
from skin_weight_field import WeightField
from skin_mesh_field import MeshField, validate_rest_field
from skin_surface_constraints import SurfaceConstraints, triangle_principal_stretches
from run_shape_preserved import reconstruct_adapted
from corpus_motion import load_motion
from attachment_quality import attachment_quality
from motion_completion import apply_motion_completion
from pipeline_contract import contract_metadata, validate_corpus_contract, validate_fit_report_contract


def deform(transforms, weights, vertices):
    """Blend immutable transforms, then apply the shared rest geometry."""
    frames, joints = transforms.shape[:2]
    blended = (weights @ transforms.permute(1, 0, 2, 3).reshape(joints, -1))
    blended = blended.reshape(len(vertices), frames, 3, 4).permute(1, 0, 2, 3)
    homogeneous = torch.cat((vertices, torch.ones_like(vertices[:, :1])), dim=1)
    return torch.einsum("fvkl,vl->fvk", blended, homogeneous)


def validate_capture_indices(entry, frame_count):
    before, after = entry["contextBeforeCount"], entry["contextAfterCount"]
    if type(before) is not int or type(after) is not int or before < 1 or after < 0:
        raise ValueError("invalid explicit context counts")
    expected = list(range(before, before + len(entry["frames"])))
    if entry["referenceIndex"] != 0 or entry["sourceIndices"] != expected or frame_count != before + len(expected) + after:
        raise ValueError("capture must preserve every authored frame between explicit context ranges")


def project_mesh_step(mesh_field, surface, previous_control):
    """Backtrack the proposed control update until the rest surface is feasible."""
    with torch.no_grad():
        proposed = mesh_field.control.detach().clone()
        tri = surface.triangles
        original = mesh_field.rest_vertices[tri]
        normal = torch.cross(original[:, 1] - original[:, 0], original[:, 2] - original[:, 0], dim=-1)
        for attempt in range(12):
            fraction = .5 ** attempt
            mesh_field.control.copy_(previous_control + (proposed - previous_control) * fraction)
            vertices = mesh_field.vertices()
            ratios, valid, _ = triangle_principal_stretches(vertices, mesh_field.rest_vertices, tri)
            posed = vertices[tri]
            new_normal = torch.cross(posed[:, 1] - posed[:, 0], posed[:, 2] - posed[:, 0], dim=-1)
            feasible = ((ratios[:, valid] >= .80001) & (ratios[:, valid] <= 1.24999)).all()
            feasible = feasible & ((new_normal[valid] * normal[valid]).sum(-1) >= 0).all()
            if bool(feasible):
                return fraction
        # Rejected optimization steps are explicit, not replacement meshes.
        mesh_field.control.copy_(previous_control)
        return 0.0


def rest_barrier(rest, surface):
    """Steer away from active shape bounds before the line search rejects a step."""
    ratios, valid, _ = triangle_principal_stretches(rest, surface.vertices, surface.triangles)
    normalized = torch.log(ratios[:, valid].clamp_min(1e-6)) / np.log(1.25)
    barrier = -torch.log((1 - normalized.square()).clamp_min(1e-6))
    values = barrier.amax(-1).flatten()
    return barrier.mean() + .1 * values.topk(max(1, len(values) // 100)).values.mean()


def comparison(path, columns, labels, title):
    arrays = [value.detach().cpu().numpy() for value in columns]
    size = arrays[0].shape[1]
    frames = []
    for index in range(len(arrays[0])):
        panel = Image.new("RGB", (size * len(columns), size + 34), (12, 12, 16))
        draw = ImageDraw.Draw(panel)
        draw.text((4, 2), f"{title} frame {index:02d}", fill="white")
        for col, (values, label) in enumerate(zip(arrays, labels)):
            panel.paste(Image.fromarray(np.uint8(np.clip(values[index], 0, 1) * 255)), (col * size, 34))
            draw.text((col * size + 4, 18), label, fill="white")
        frames.append(panel)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=int(round(SOURCE_FRAME_MS)), loop=0)
    selected = np.linspace(0, len(frames) - 1, min(4, len(frames))).astype(int)
    sheet = Image.new("RGB", (frames[0].width, frames[0].height * len(selected)))
    for row, index in enumerate(selected):
        sheet.paste(frames[index], (0, row * frames[0].height))
    sheet.save(path.with_suffix(".png"))


def optimize(field, mesh_field, transforms, surface, renderer, train_indices, targets,
             original_idle, idle_target, *, iterations, deadline, allow_mesh, repair_only=False, motion_floor=None,
             joint_anchor=None, joint_anchor_weight=0):
    if not np.isfinite(joint_anchor_weight) or joint_anchor_weight < 0 or (joint_anchor_weight > 0 and joint_anchor is None):
        raise ValueError("positive joint anchor weight requires a fixed anchor objective")
    parameters = list(field.parameters()) + (list(mesh_field.parameters()) if allow_mesh else [])
    optimizer = torch.optim.Adam(parameters, lr=.025 if allow_mesh else .04)
    best, best_state, history = float("inf"), None, []
    projected_steps, rejected_steps = 0, 0
    for step in range(iterations):
        if time.perf_counter() >= deadline:
            break
        optimizer.zero_grad(set_to_none=True)
        weights = field.weights()
        rest = mesh_field.vertices() if allow_mesh else mesh_field.rest_vertices
        animated = deform(transforms, weights, rest)
        geometry = surface.loss(animated)
        regularity = field.penalty(weights)
        rendered = renderer.render(animated[train_indices])
        photo = image_loss(*rendered, *targets)["total"]
        rest_loss = rest_barrier(rest, surface) if allow_mesh else rest.sum() * 0
        idle_render = renderer.render(rest[None])
        idle_loss = image_loss(*idle_render, *idle_target)["total"]
        # Preserve the known-good idle appearance as well as bounded rest geometry.
        idle_preservation = (idle_render[0] - original_idle[0]).abs().mean() + (idle_render[1] - original_idle[1]).abs().mean()
        objective = (0 if repair_only else 10) * photo + 3 * geometry + 25 * regularity
        retention = animated.sum() * 0 if motion_floor is None else motion_floor.loss(animated)
        objective = objective + 100 * retention
        anchor_loss = animated.sum() * 0 if joint_anchor is None else joint_anchor.loss(animated)
        objective = objective + joint_anchor_weight * anchor_loss
        if allow_mesh:
            objective = objective + 10 * rest_loss + 40 * idle_preservation + .5 * idle_loss + 2 * mesh_field.penalty()
        if not torch.isfinite(objective):
            raise ValueError("nonfinite constrained optimization objective")
        score = float(objective.detach())
        if score < best:
            best = score
            best_state = (
                {key: value.detach().clone() for key, value in field.state_dict().items()},
                {key: value.detach().clone() for key, value in mesh_field.state_dict().items()},
            )
        objective.backward()
        torch.nn.utils.clip_grad_norm_(parameters, 2)
        previous_control = mesh_field.control.detach().clone()
        optimizer.step()
        if allow_mesh:
            fraction = project_mesh_step(mesh_field, surface, previous_control)
            projected_steps += int(fraction < 1)
            rejected_steps += int(fraction == 0)
        if step % 50 == 0 or step == iterations - 1:
            row = {"step": step, "objective": score, "surface": float(geometry.detach()),
                   "image": float(photo.detach()), "motionFloorPenalty": float(retention.detach()),
                   "jointAnchorLoss": float(anchor_loss.detach()),
                   "meshEnabled": allow_mesh, "repairOnly": repair_only,
                   "projectedMeshSteps": projected_steps, "rejectedMeshSteps": rejected_steps}
            history.append(row)
            print(json.dumps(row), flush=True)
    if best_state is None:
        raise TimeoutError("budget expired before stage optimization")
    field.load_state_dict(best_state[0])
    mesh_field.load_state_dict(best_state[1])
    return history


def _training_regions(asset, skin):
    """Train every deformable profile region; rigid attachments stay frozen."""
    profile = get_profile(asset)
    rigid = {str(item["region"]) for item in profile.get("rigidAttachments", ())}
    if asset == "h3_roc":
        # Preserve the established Roc pilot's intentionally bounded scope.
        return ("wing_left", "wing_right", "neck_head", "tail", "torso")
    return tuple(region for region in profile["regionJoints"] if region in skin["regions"] and region not in rigid)


def _frozen_ownership_vertices(skin):
    """Keep prepared ownership-seam weights exact, including incident interface faces."""
    pairs = skin.get("ownershipBoundaryPairs")
    if pairs is None:
        return None
    pairs = np.asarray(pairs)
    if pairs.size == 0:
        return None
    vertex_count = len(skin["vertices"])
    if pairs.ndim != 2 or pairs.shape[1] != 2 or not np.issubdtype(pairs.dtype, np.integer):
        raise ValueError("ownershipBoundaryPairs must be integer [N,2]")
    if np.any(pairs < 0) or np.any(pairs >= vertex_count):
        raise ValueError("ownershipBoundaryPairs escape the prepared vertex range")
    frozen = np.unique(pairs.reshape(-1)).astype(np.int64)
    triangles = np.asarray(skin["triangles"])
    if triangles.size == 0:
        return frozen
    if triangles.ndim != 2 or triangles.shape[1] != 3 or not np.issubdtype(triangles.dtype, np.integer):
        raise ValueError("triangles must be integer [F,3]")
    if np.any(triangles < 0) or np.any(triangles >= vertex_count):
        raise ValueError("triangles escape the prepared vertex range")
    pair_mask = np.zeros(vertex_count, dtype=bool)
    pair_mask[frozen] = True
    incident = pair_mask[triangles].any(axis=1)
    return np.unique(np.concatenate([frozen, triangles[incident].reshape(-1)])).astype(np.int64)


def make_asset_field(asset, skin, train_regions, *, region_joints=None):
    profile = get_profile(asset)
    return WeightField(
        skin["vertices"], skin["triangles"], skin["weights"], skin["regions"],
        skin["names"], profile["regionJoints"] if region_joints is None else region_joints, device="cuda",
        train_regions=train_regions,
        frozen_vertices=_frozen_ownership_vertices(skin),
    )


def expand_camera_to_full_canvas(camera, resolution=224):
    """Rebase a registered square crop onto the complete source canvas."""
    result = dict(camera)
    width, height = camera["sourceSize"]
    old_crop = camera["sourceCrop"]
    size = max(width, height)
    crop = {"left": -((size - width) // 2), "top": -((size - height) // 2), "size": size}
    factor = old_crop["size"] / crop["size"] * (resolution - 1) / (camera["resolution"] - 1)
    result["scale"] = camera["scale"] * factor
    result["offset"] = (np.asarray(camera["offset"]) * factor +
                         np.asarray([old_crop["left"] - crop["left"], old_crop["top"] - crop["top"]]) *
                         (resolution - 1) / crop["size"]).tolist()
    result["sourceCrop"], result["resolution"] = crop, resolution
    return result


def run(output, baseline_dir, corpus_path, seconds=600, iterations=200, *, asset="h3_roc", bind_mode="prepared", motion_completion_report=None, attachment_repair_recipe=None, attachment_skin_refit_seconds=0, anatomical_chain_regions=(), joint_anchor_weight=0, geometry_mode="weights_mesh"):
    started = time.perf_counter()
    if not np.isfinite(attachment_skin_refit_seconds) or not 0 <= attachment_skin_refit_seconds <= 600:
        raise ValueError("attachment skin refit requires a finite 0..600 second budget")
    if attachment_skin_refit_seconds > 0 and (attachment_repair_recipe is None or attachment_skin_refit_seconds < 1):
        raise ValueError("attachment skin refit requires an explicit repair recipe and at least one second")
    if anatomical_chain_regions and attachment_skin_refit_seconds <= 0:
        raise ValueError("anatomical chain initialization requires the skin refit stage")
    if not np.isfinite(joint_anchor_weight) or joint_anchor_weight < 0 or (joint_anchor_weight > 0 and not anatomical_chain_regions):
        raise ValueError("joint anchor objective requires explicit anatomical chains and nonnegative weight")
    if bind_mode not in ('prepared', 'source_reference'):
        raise ValueError('unknown explicit bind mode')
    if geometry_mode not in ('weights_only', 'weights_mesh'):
        raise ValueError("geometry_mode must be 'weights_only' or 'weights_mesh'")
    if attachment_repair_recipe is not None and bind_mode != "prepared":
        raise ValueError("attachment repair requires the frozen prepared skeleton")
    if motion_completion_report is not None and bind_mode != "prepared":
        raise ValueError("motion completion requires its unchanged prepared bind")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    profile = get_profile(asset)
    freeze, skin = _load_frozen_prep(asset)
    previous = json.loads((baseline_dir / "pilot_report.json").read_text())
    if sha256_file(Path(freeze["researchSkin"])) != previous["inputs"]["researchSkin"]:
        raise ValueError("frozen research skin changed since camera registration")
    corpus = json.loads(corpus_path.read_text())
    mocap_contract = validate_corpus_contract(corpus)
    from structured_profiles import require_profile_pin
    profile_pin = require_profile_pin(asset, profile, freeze, previous, corpus)
    if corpus.get("unit") != asset:
        raise ValueError(f"corpus unit {corpus.get('unit')!r} does not match selected asset {asset!r}")
    for path, source in corpus["sourceFrames"].items():
        if sha256_file(Path(path)) != source["sha256"]:
            raise ValueError("source images changed since capture")
    corpus_manifest = json.loads(Path(corpus["manifest"]).read_text())
    require_profile_pin(asset, corpus_manifest, profile_pin)
    if sha256_file(Path(corpus["manifest"])) != corpus["manifestSha256"]:
        raise ValueError("source manifest changed since capture")
    camera = json.loads((baseline_dir / "camera.json").read_text())
    camera = {key: camera[key] for key in ("right", "down", "forward", "scale", "offset", "depth_center", "depth_span", "sourceSize", "sourceCrop", "resolution")}
    if not previous['inputs'].get('calibrationPath'):
        raise ValueError('baseline lacks explicit calibration ownership; regenerate registration')
    calibration_path = Path(previous['inputs']['calibrationPath'])
    if sha256_file(calibration_path) != previous["inputs"]["calibration"]:
        raise ValueError("shared idle calibration differs from frozen baseline")
    calibration = json.loads(calibration_path.read_text())
    reference = np.asarray(calibration["referencePositions"], dtype=np.float64)
    original_skin = skin
    bind_candidate = None
    region_joints = profile['regionJoints']
    attachment_descriptors = profile.get("rigidAttachments", ())
    if bind_mode == 'source_reference':
        if corpus.get('motionRepresentation', 'capture_positions_v1') != 'capture_positions_v1':
            raise ValueError('source-reference trial requires ordinary position captures, not mounted composition')
        from source_reference_bind_candidate import build_source_reference_candidate as build_candidate
        from local_rotation_capture_motion import reconstruct_local_rotation
        bind_candidate = build_candidate(skin, reference, tuple(profile['wholeBodyHubs']))
        skin = bind_candidate['skin']
        canonical = {member: group['owner'] for group in bind_candidate['report']['coincidentPreparation']['groups']
                     for member in group['members']}
        region_joints = {region: tuple(dict.fromkeys(canonical.get(name, name) for name in joints))
                         for region, joints in region_joints.items()}
        attachment_descriptors = tuple({**item, "donorJoints": tuple(dict.fromkeys(
            canonical.get(name, name) for name in item["donorJoints"]))}
            for item in attachment_descriptors)
    # Expand the old source crop to a padded full canvas without refitting pose,
    # scale, or orientation. All DEF frames must remain inside the image.
    resolution = 224
    camera = expand_camera_to_full_canvas(camera, resolution)
    motions, frame_paths, control_motions = {}, {}, {}
    for entry in corpus["captures"]:
        key = entry["key"]
        if key in motions:
            raise ValueError("duplicate corpus clip")
        if sha256_file(Path(entry["capture"])) != entry["captureSha256"]:
            raise ValueError("capture changed after corpus freeze")
        with np.load(entry["capture"], allow_pickle=False) as raw:
            validate_capture_indices(entry, len(raw["pred_position"]))
            if list(raw["joint_names"].astype(str)) != list(skin["names"]) or not np.array_equal(raw["parents"], skin["parents"]):
                raise ValueError("capture skeleton inventory differs from frozen skin")
            positions = raw["pred_position"][entry["sourceIndices"]]
            if bind_candidate is None:
                motions[key] = load_motion(raw, entry, corpus, skin, reference, profile["wholeBodyHubs"])
            else:
                control_motions[key] = load_motion(raw, entry, corpus, original_skin, reference, profile['wholeBodyHubs'])
                motions[key] = reconstruct_local_rotation(capture_positions=positions,
                    capture_reference_positions=reference, capture_offsets=skin['captureOffsets'],
                    fitted_offsets=skin['offsets'], parents=skin['parents'], names=list(skin['names']),
                    hub_names=tuple(profile['wholeBodyHubs']))
                similarity = bind_candidate['report']['transform']
                expected_root = (similarity['scale'] * positions[:, 0] @ np.asarray(similarity['rotation']).T
                                 + np.asarray(similarity['translation']))
                root_delta = expected_root - motions[key]['jointWorld'][:, 0, :3, 3]
                motions[key]['jointWorld'][:, :, :3, 3] += root_delta[:, None, :]
                motions[key]['positions'] = motions[key]['jointWorld'][:, :, :3, 3].copy()
                motions[key]['captureRest'] = reference.copy()
            # The capture-leading idle is temporal context, not a per-clip bind.
            # Context-dependent predictions must never redefine the asset rest.
        if not np.array_equal(motions[key]["captureRest"], reference):
            raise ValueError("every clip must use the single asset-wide idle reference")
        frame_paths[key] = [Path(path) for path in entry["frames"]]
        if len(frame_paths[key]) != len(positions):
            raise ValueError("source/capture frame mapping changed")
    completion_provenance = None
    if motion_completion_report is not None:
        motions, completion_provenance = apply_motion_completion(
            motions, skin, motion_completion_report, asset,
            sha256_file(corpus_path), previous["inputs"]["researchSkin"])
    output.mkdir(parents=True)
    if bind_candidate is not None:
        np.savez_compressed(output/'source_reference_skin.npz', **skin)
    report = {"proof": "generated-candidate", "visualAcceptance": "unreviewed", "asset": asset,
              "motionOwner": previous["motionOwner"], "sharedMeshAndSkinAcrossClips": True,
              "geometryWitnesses": "all corpus poses; captures fixed before fitting",
              "validationScope": "one interior image per clip of at least five frames withheld initially, then all frames in final refit",
              "baselineDirectory": str(baseline_dir), "stages": {}, "cases": {},
              "motionReference": {"path": str(calibration_path), "sha256": sha256_file(calibration_path), "policy": "single_asset_calibrated_idle_not_per_clip_context"},
              "geometryMode": geometry_mode,
              "objectivePolicy": {"image": 10, "animatedSurface": 3, "weightPrior": 25, "restBarrier": 10, "idlePreservation": 40, "restProjection": "backtrack each control step into .8..1.25 principal stretch"},
              "inputs": {"researchSkin": previous["inputs"]["researchSkin"], "corpus": str(corpus_path), "corpusSha256": sha256_file(corpus_path)}, "secondsBudget": seconds,
              "pipelineContract": {**contract_metadata(geometry_mode=geometry_mode, bind_mode=bind_mode),
                                   "corpus": mocap_contract}}
    report.update(profile_pin)
    report['bindMode'] = bind_mode
    report['motionCompletion'] = completion_provenance
    if completion_provenance is not None:
        report['motionOwner'] = 'explicit_source_orientation_completion_fixed_positions'
    if bind_candidate is not None:
        report['sourceReferenceBind'] = bind_candidate['report']
        report['sourceReferenceSkinSha256'] = sha256_file(output/'source_reference_skin.npz')
        report['motionOwner'] = 'fixed_source_reference_local_rotation_diagnostic'
        report['productionSelectionChanged'] = False
        report['canonicalRegionJoints'] = region_joints
    if bind_mode == "prepared":
        # Catch accidental motion-lane drift before any candidate is written.
        validate_fit_report_contract(report)
    with cascade_batch_lock(ROOT):
        deadline = time.perf_counter() + seconds - 40
        renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], camera, resolution)
        surface = SurfaceConstraints(skin["vertices"], skin["triangles"], device="cuda")
        train_regions = _training_regions(asset, skin)
        field = make_asset_field(asset, skin, train_regions, region_joints=region_joints)
        frozen_regions = tuple(set(skin["regions"]) - set(train_regions))
        mesh_field = MeshField(skin["vertices"], skin["regions"], frozen_regions, device="cuda")
        original = torch.as_tensor(skin["weights"], device="cuda", dtype=torch.float32)
        rest = torch.as_tensor(skin["vertices"], device="cuda", dtype=torch.float32)
        transforms, slices, cursor = [], {}, 0
        for case, motion in motions.items():
            value = torch.as_tensor((motion["jointWorld"] @ skin["inverseBind"][None])[:, :, :3], device="cuda", dtype=torch.float32)
            transforms.append(value)
            slices[case] = slice(cursor, cursor + len(value))
            cursor += len(value)
        transforms = torch.cat(transforms).detach()
        targets = {case: source_images(frame_paths[case], camera["sourceCrop"], resolution) for case in motions}
        idle_target = source_images([Path(corpus_manifest["idle"])], camera["sourceCrop"], resolution)
        all_targets = tuple(torch.cat([targets[key][component] for key in motions]) for component in range(3))
        heldouts = {case: [len(frame_paths[case]) // 2] if len(frame_paths[case]) >= 5 else [] for case in motions}
        train_indices = [selected.start + index for case, selected in slices.items() for index in range(len(frame_paths[case])) if index not in heldouts[case]]
        train_target = tuple(value[train_indices] for value in all_targets)
        report["imageTrainingIndices"] = train_indices
        report["heldoutIndicesByClip"] = heldouts
        with torch.no_grad():
            original_idle = renderer.render(rest[None])
            baseline = deform(transforms, original, rest)
            control_meshes = None
            if bind_candidate is not None:
                control_transforms = torch.as_tensor(np.concatenate([
                    (control_motions[key]['jointWorld'] @ original_skin['inverseBind'][None])[:, :, :3]
                    for key in motions]), device='cuda', dtype=torch.float32)
                control_meshes = deform(control_transforms, torch.as_tensor(original_skin['weights'],
                    device='cuda', dtype=torch.float32), rest)
        shared = (field, mesh_field, transforms, surface, renderer, train_indices, train_target, original_idle, idle_target)
        report["stages"]["repair"] = optimize(*shared, iterations=150, deadline=deadline, allow_mesh=False, repair_only=True)
        report["stages"]["weights"] = optimize(*shared, iterations=iterations, deadline=deadline, allow_mesh=False)
        with torch.no_grad():
            weight_only = field.weights().clone()
            weight_meshes = deform(transforms, weight_only, rest)
        # Geometry changes are an explicit second stage, never a silent recovery path.
        # SmartRig modifier runs can opt out and keep the source rest surface
        # byte-for-byte represented by the frozen preparation.
        if geometry_mode == "weights_mesh":
            report["stages"]["mesh"] = optimize(*shared, iterations=iterations, deadline=deadline, allow_mesh=True)
        else:
            report["stages"]["mesh"] = {"skipped": True, "reason": "geometry_mode=weights_only"}
        with torch.no_grad():
            validation_rest = mesh_field.vertices() if geometry_mode == "weights_mesh" else rest
            validation_meshes = deform(transforms, field.weights(), validation_rest)
            report["validationBeforeAllFrameRefit"] = {}
            for case, selected in slices.items():
                rendered = renderer.render(validation_meshes[selected])
                scores = image_metrics(*rendered, *targets[case][:2])
                report["validationBeforeAllFrameRefit"][case] = {"heldoutIndices": heldouts[case], "scores": scores}
        all_shared = (field, mesh_field, transforms, surface, renderer, list(range(cursor)), all_targets, original_idle, idle_target)
        report["stages"]["allFrames"] = optimize(*all_shared, iterations=100, deadline=deadline, allow_mesh=(geometry_mode == "weights_mesh"))
        with torch.no_grad():
            learned_weights = field.weights().detach()
            learned_vertices = (mesh_field.vertices() if geometry_mode == "weights_mesh" else rest).detach()
            combined = deform(transforms, learned_weights, learned_vertices)
        report["weightContract"] = validate_candidate_weights(learned_weights.cpu().numpy(), skin["weights"], skin["regions"], skin["names"], region_joints, train_regions)
        report["trainRegions"] = list(train_regions)
        report["meshField"] = mesh_field.stats() if geometry_mode == "weights_mesh" else {
            "enabled": False, "reason": "geometry_mode=weights_only", "maxDisplacement": 0.0
        }
        if geometry_mode == "weights_mesh":
            validate_rest_field(mesh_field)
        report["restContract"] = surface.rest_gate(learned_vertices)
        report["surface"] = {"original": surface.metrics(baseline), "weights": surface.metrics(weight_meshes), "mesh": surface.metrics(combined)}
        report["attachmentGate"] = attachment_quality(
            combined, learned_vertices, skin["triangles"], learned_weights,
            skin["regions"], skin["names"], attachment_descriptors,
            ownership_profile=profile, prepared_skin=skin,
            expected_frame_count=sum(selected.stop - selected.start for selected in slices.values()))
        report["candidateValidForExport"] = bool(report["restContract"]["ok"] and report["attachmentGate"]["passed"])
        if "geometryOwnership" in profile:
            from geometry_ownership import animated_boundary_gate
            expected_frames = sum(selected.stop - selected.start for selected in slices.values())
            report["ownershipBoundaryGate"] = animated_boundary_gate(profile, skin, combined.detach().cpu().numpy(),
                                                                      expected_frame_count=expected_frames)
            report["candidateValidForExport"] &= report["ownershipBoundaryGate"]["passed"]
        np.savez_compressed(output / "diagnostic_candidate.npz", weights=learned_weights.cpu().numpy(), vertices=learned_vertices.cpu().numpy(),
                            weight_only=weight_only.cpu().numpy(), names=np.asarray(skin["names"]), parents=skin["parents"])
        for case, selected in slices.items():
            with torch.no_grad():
                images = [renderer.render(meshes[selected]) for meshes in (baseline, weight_meshes, combined)]
            comparison(output / f"{case}_comparison.gif", [targets[case][0]] + [image[0] for image in images],
                       ("Source", "Original", "Constrained skin", "Skin + mesh"), case)
            if control_meshes is not None:
                with torch.no_grad():
                    control_image = renderer.render(control_meshes[selected])
                comparison(output / f'{case}_bind_comparison.gif',
                    [targets[case][0], control_image[0], images[0][0], images[2][0]],
                    ('Source', 'Current prepared bind', 'Source-reference bind', 'Source bind + skin/mesh'), case)
            scores = [image_metrics(*image, *targets[case][:2]) for image in images]
            report["cases"][case] = {"scores": dict(zip(("original", "weights", "mesh"), scores)), "scoreScope": "all-frame training fit, not heldout",
                                     "fixedMotionSha256": digest(motions[case]["jointWorld"])}
            if control_meshes is not None:
                report['cases'][case]['scores']['preparedControl'] = image_metrics(*control_image, *targets[case][:2])
            times = np.arange(len(scores[0]), dtype=np.float32) * SOURCE_FRAME_MS / 1000
            glb = output / f"{case}_candidate.glb"
            if not report["candidateValidForExport"]:
                report["cases"][case]["exportParity"] = {"ok": False, "reason": "rest or attachment contract failed; no GLB exported"}
                print(json.dumps({"completedGif": str(output / f"{case}_comparison.gif"), "exportRejected": True}), flush=True)
                continue
            if attachment_repair_recipe is not None:
                report["cases"][case]["exportParity"] = {"ok": False, "reason": "post-fit attachment repair requested; no pre-repair GLB exported"}
                continue
            animation = {"name": "fixed_motion_adapted_mesh", "times": times,
                         "rotations": matrices_to_xyzw(motions[case]['localRotation'])}
            if bind_candidate is not None:
                translations = motions[case]['localTranslation'].copy()
                translations[:, 0] = motions[case]['jointWorld'][:, 0, :3, 3]
                animation['translations'] = translations
            write_skinned_glb(glb, names=skin["names"], parents=skin["parents"],
                rest_local_rotation=np.repeat(np.eye(3)[None], len(skin["names"]), axis=0), rest_local_translation=skin["offsets"],
                inverse_bind=skin["inverseBind"], vertices=learned_vertices.cpu().numpy(), triangles=skin["triangles"],
                uvs=skin["uvs"], albedo=skin["albedo"], weights=learned_weights.cpu().numpy(),
                animation=animation)
            report["cases"][case]["exportParity"] = verify_calibrated_export(glb, expected_meshes=combined[selected].cpu().numpy(), expected_times=times,
                idle_frame=0 if motions[case]["clipFrame0IsBind"] else None, allow_root_motion=bind_candidate is not None)
            print(json.dumps({"completedGif": str(output / f"{case}_comparison.gif")}), flush=True)
        with torch.no_grad():
            modified_idle = renderer.render(learned_vertices[None])
        report["idleRenderDifference"] = {"alphaMeanAbs": float((modified_idle[1] - original_idle[1]).abs().mean()),
                                         "rgbMeanAbs": float((modified_idle[0] - original_idle[0]).abs().mean())}
        comparison(output / "idle_comparison.gif", [idle_target[0], original_idle[0], modified_idle[0]], ("Source idle", "Original mesh", "Adapted mesh"), "Shared rest shape")
        _write_json(output / "camera.json", camera)
        # Inspect depth clipping explicitly; a clipped silhouette cannot count as a fit.
        depth = combined @ torch.as_tensor(camera["forward"], device="cuda", dtype=torch.float32)
        report["depthClippedVertices"] = int(((depth - camera["depth_center"]).abs() >= camera["depth_span"]).sum())
        final_surface = report["surface"]["mesh"]["perFrame"]
        report["qualityGate"] = {
            "attachments": report["attachmentGate"]["passed"],
            "restShape": bool(report["restContract"]["ok"]),
            "idleAppearance": report["idleRenderDifference"]["alphaMeanAbs"] <= .005,
            "depthUnclipped": report["depthClippedVertices"] == 0,
            "animatedSurface": all(row["p95"] <= 1.5 and row["compressionViolationFraction"] <= .05 for row in final_surface),
        }
        report["qualityGate"]["passed"] = all(report["qualityGate"].values())
        if "geometryOwnership" in profile:
            report["qualityGate"]["ownershipBoundary"] = report["ownershipBoundaryGate"]["passed"]
            report["qualityGate"]["passed"] = all(report["qualityGate"].values())
        report["elapsedSecondsCached"] = time.perf_counter() - started
        report["implementation"] = {name: sha256_file(HERE / name) for name in ("run_skin_mesh_pilot.py", "skin_mesh_field.py", "skin_surface_constraints.py", "attachment_quality.py", "motion_completion.py")}
        if bind_candidate is not None:
            for name in ('source_reference_bind_candidate.py', 'coincident_bind_candidate.py',
                         'local_rotation_capture_motion.py', 'reconstruct_adapted.py', 'direction_retarget.py'):
                report['implementation'][name] = sha256_file(HERE/name)
            report['implementation']['verify_calibrated_export.py'] = sha256_file(HERE/'verify_calibrated_export.py')
        report["disposition"] = "candidate_requires_visual_review" if report["qualityGate"]["passed"] else "rejected_quality_gate"
        if sha256_file(Path(freeze["researchSkin"])) != previous["inputs"]["researchSkin"]:
            raise ValueError("original asset changed during pilot")
        require_profile_pin(asset, report)
        _write_json(output / "report.json", report)
    if attachment_repair_recipe is not None:
        from run_attachment_repair import run as run_attachment_repair
        repair_dir = output / "attachment_repair"
        repair = run_attachment_repair(asset, output, attachment_repair_recipe, repair_dir)
        # Keep the fitted bundle immutable: the repair's provenance pins it.
        pipeline_result = {
            "fitReport": str((output / "report.json").resolve()),
            "fitReportSha256": sha256_file(output / "report.json"),
            "attachmentRepairReport": str((repair_dir / "report.json").resolve()),
            "attachmentRepairReportSha256": sha256_file(repair_dir / "report.json"),
            "candidateValidForExport": repair["candidateValidForExport"],
            "elapsedSecondsCached": time.perf_counter() - started}
        if attachment_skin_refit_seconds > 0:
            from run_attachment_skin_refit import run as run_attachment_skin_refit
            refit_dir = output / "attachment_skin_refit"
            refit = run_attachment_skin_refit(asset, output, repair_dir / "report.json", refit_dir,
                                             seconds=attachment_skin_refit_seconds,
                                             anatomical_chain_regions=anatomical_chain_regions,
                                             joint_anchor_weight=joint_anchor_weight)
            pipeline_result.update({
                "attachmentSkinRefitReport": str((refit_dir / "report.json").resolve()),
                "attachmentSkinRefitReportSha256": sha256_file(refit_dir / "report.json"),
                "candidateValidForExport": refit["candidateValidForExport"],
                "elapsedSecondsCached": time.perf_counter() - started})
        _write_json(output / "pipeline_result.json", pipeline_result)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path, default=ROOT / "artifacts/homm3_mocap_v2/skin_weight_pilot/roc_v5")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--asset", default="h3_roc", help="asset profile id; defaults to h3_roc for compatibility")
    parser.add_argument("--seconds", type=float, default=600)
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument('--bind-mode', choices=('prepared', 'source_reference'), default='prepared',
                        help='source_reference is an explicit diagnostic bind/skin trial; frozen preparation is unchanged')
    parser.add_argument('--geometry-mode', choices=('weights_only', 'weights_mesh'), default='weights_mesh',
                        help='weights_only preserves the frozen SmartRig rest surface; weights_mesh enables bounded rest adaptation')
    parser.add_argument('--motion-completion-report', type=Path,
                        help='explicit hash-pinned orientation completion; all mocap joint positions remain fixed')
    parser.add_argument('--attachment-repair-recipe', type=Path,
                        help='explicit shared post-fit topology/ownership repair; suppresses pre-repair GLB export')
    parser.add_argument('--attachment-skin-refit-seconds', type=float, default=0,
                        help='explicit post-separation skin fit budget; requires attachment repair, no geometry or motion edits')
    parser.add_argument('--anatomical-chain-regions', nargs='+', default=(),
                        help='explicit profile chains used to initialize the attachment skin refit')
    parser.add_argument('--joint-anchor-weight', type=float, default=0,
                        help='explicit normalized fixed-joint tracking objective weight; zero disables it')
    args = parser.parse_args()
    if not 120 <= args.seconds <= 600 or args.iterations <= 0:
        raise ValueError("require 120..600 seconds and positive iteration count")
    result = run(args.output.resolve(), args.baseline_dir.resolve(), args.corpus.resolve(), args.seconds, args.iterations, asset=args.asset, bind_mode=args.bind_mode, motion_completion_report=args.motion_completion_report, attachment_repair_recipe=args.attachment_repair_recipe, attachment_skin_refit_seconds=args.attachment_skin_refit_seconds, anatomical_chain_regions=args.anatomical_chain_regions, joint_anchor_weight=args.joint_anchor_weight, geometry_mode=args.geometry_mode)
    elapsed = result["elapsedSecondsCached"]
    if args.attachment_repair_recipe is not None:
        elapsed = json.loads((args.output / "pipeline_result.json").read_text())["elapsedSecondsCached"]
    print(json.dumps({"report": str(args.output / "report.json"), "elapsed": elapsed,
                      "fitElapsedSeconds": result["elapsedSecondsCached"]}))


if __name__ == "__main__":
    main()
