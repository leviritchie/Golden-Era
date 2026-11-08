"""Replay an explicit semantic attachment repair against a frozen all-clip fit."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from attachment_repair import split_attachment, boundary_gaps, consolidate_redundant_owner
from attachment_quality import attachment_quality
from attachment_mask_refinement import refine_mask
from motion_completion import apply_motion_completion
from run_surface_loss_attribution import _load_inputs
from run_skin_mesh_pilot import (ROOT, SkinImageRenderer, comparison, deform, digest,
                                 expand_camera_to_full_canvas, sha256_file)
from run_skin_weight_pilot import cascade_batch_lock, source_images


def load_recipe(path, asset, fit_report, skin):
    recipe = json.loads(path.read_text(encoding="utf-8"))
    if recipe.get("schema") != "attachment-repair-recipe-v1" or recipe.get("asset") != asset:
        raise ValueError("repair recipe schema/asset mismatch")
    if recipe.get("preparedSkinSha256") != fit_report["inputs"]["researchSkin"]:
        raise ValueError("repair recipe prepared skin mismatch")
    mask_dir = Path(recipe["maskDirectory"])
    producer = mask_dir / "report.json"
    mask = mask_dir / "face_proposal.npz"
    if not mask_dir.is_absolute() or sha256_file(producer) != recipe["maskReportSha256"]:
        raise ValueError("repair mask producer identity mismatch")
    report = json.loads(producer.read_text(encoding="utf-8"))
    if report.get("asset") != asset or report.get("researchSkinSha256") != recipe["preparedSkinSha256"]:
        raise ValueError("repair mask source mismatch")
    if sha256_file(mask) != recipe["maskSha256"] or report.get("maskSha256") != recipe["maskSha256"]:
        raise ValueError("repair mask hash mismatch")
    if recipe.get("attachmentType") != "rigid_held_part":
        raise ValueError("this capability requires an explicit rigid held part")
    if type(recipe.get("consolidateRedundantOwner")) is not bool:
        raise ValueError("explicit redundant-owner consolidation policy required")
    if recipe.get("maskRefinement") not in ("none", "source_samples_potts_v1"):
        raise ValueError("explicit supported mask refinement policy required")
    with np.load(mask, allow_pickle=False) as data:
        selected = data["propTriangles"].copy()
        if recipe["maskRefinement"] == "source_samples_potts_v1":
            selected = refine_mask(skin["vertices"], skin["triangles"], data["samplePassed"])["selectedFaceIds"]
    return recipe, selected


def baseline_worlds(motions, completion):
    """Recover only the original reference for equivalence tests, not playback."""
    worlds = {key: value["jointWorld"] for key, value in motions.items()}
    if completion is not None:
        report_path = Path(completion["reportPath"])
        if sha256_file(report_path) != completion["reportSha256"]:
            raise ValueError("baseline completion report drift")
        artifact = report_path.parent / "source_wrist_motion.npz"
        if sha256_file(artifact) != completion["motionArtifactSha256"]:
            raise ValueError("baseline completion artifact drift")
        with np.load(artifact, allow_pickle=False) as data:
            keys, offsets = data["clipKeys"].astype(str), data["clipOffsets"]
            if list(keys) != completion["mappedClips"]:
                raise ValueError("baseline completion clip inventory drift")
            for index, key in enumerate(keys):
                selected = slice(int(offsets[index]), int(offsets[index + 1]))
                if not np.array_equal(worlds[key], data["jointWorld"][selected]):
                    raise ValueError("baseline reference does not match completed playback")
                worlds[key] = data["baselineJointWorld"][selected].copy()
    return np.concatenate(list(worlds.values()))


def run(asset, fit_dir, recipe_path, output, motion_completion_report=None):
    started = time.perf_counter()
    if output.exists():
        raise FileExistsError(output)
    fit_report, corpus, _, prepared, skin, _, motions, frames, provenance = _load_inputs(fit_dir, asset)
    recipe, selected = load_recipe(recipe_path, asset, fit_report, skin)
    completion = fit_report.get("motionCompletion")
    original_worlds = baseline_worlds(motions, completion)
    if motion_completion_report is not None:
        if completion is not None:
            raise ValueError("fit already contains motion completion")
        motions, completion = apply_motion_completion(
            motions, prepared, motion_completion_report, asset,
            fit_report["inputs"]["corpusSha256"], fit_report["inputs"]["researchSkin"])
    owner = recipe["owner"]
    body = skin
    consolidation = None
    if recipe["consolidateRedundantOwner"]:
        body, consolidation = consolidate_redundant_owner(skin, original_worlds, owner)
    repaired, topology = split_attachment(body, selected, owner)
    owner_id = list(skin["names"]).index(owner)
    baseline_weights = np.array(skin["weights"], copy=True)
    baseline_weights[np.unique(skin["triangles"][selected])] = 0
    baseline_weights[np.unique(skin["triangles"][selected]), owner_id] = 1
    labels = np.full(len(repaired["vertices"]), "body", dtype="<U20")
    labels[np.unique(repaired["triangles"][selected])] = "declared_part"
    camera_path = Path(fit_report["baselineDirectory"]) / "camera.json"
    camera = expand_camera_to_full_canvas(json.loads(camera_path.read_text()), 320)
    output.mkdir(parents=True)
    recipe_copy = output / "recipe.json"
    recipe_copy.write_bytes(recipe_path.read_bytes())
    np.savez_compressed(output / "repaired_skin.npz", **repaired)
    result = {"schema": "attachment-repair-result-v1", "asset": asset,
              "accepted": False, "delivery": False, "fitProvenance": provenance,
              "recipePath": str(recipe_copy.resolve()), "recipeSha256": sha256_file(recipe_copy),
              "sourceRecipePath": str(recipe_path.resolve()),
              "motionCompletion": completion, "topology": topology,
              "bodyOwnershipConsolidation": consolidation,
              "candidateSha256": sha256_file(output / "repaired_skin.npz"),
              "cameraSha256": sha256_file(camera_path), "cases": {},
              "camera": camera,
              "proof": "generated-repair-candidate-no-delivery"}
    with cascade_batch_lock(ROOT):
        rest = torch.as_tensor(skin["vertices"], device="cuda", dtype=torch.float32)
        new_rest = torch.as_tensor(repaired["vertices"], device="cuda", dtype=torch.float32)
        weights = torch.as_tensor(baseline_weights, device="cuda", dtype=torch.float32)
        original_weights = torch.as_tensor(skin["weights"], device="cuda", dtype=torch.float32)
        new_weights = torch.as_tensor(repaired["weights"], device="cuda", dtype=torch.float32)
        renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], camera, 320)
        repaired_renderer = SkinImageRenderer(repaired["triangles"], repaired["uvs"], repaired["albedo"], camera, 320)
        all_new = []
        frame_start = 0
        body_faces = np.ones(len(skin["triangles"]), dtype=bool)
        body_faces[selected] = False
        for key, motion in motions.items():
            transforms = torch.as_tensor(motion["jointWorld"] @ skin["inverseBind"][None], device="cuda", dtype=torch.float32)[:, :, :3]
            baseline = deform(transforms, weights, rest).detach()
            posed = deform(transforms, new_weights, new_rest).detach()
            raw_world = original_worlds[frame_start:frame_start + len(posed)]
            raw_transforms = torch.as_tensor(raw_world @ skin["inverseBind"][None], device="cuda", dtype=torch.float32)[:, :, :3]
            raw_body = deform(raw_transforms, original_weights, rest).detach()
            body_error = float((posed[:, repaired["triangles"][body_faces]] - raw_body[:, skin["triangles"][body_faces]]).abs().max()) if body_faces.any() else 0.0
            if body_error > 1e-5:
                raise ValueError("repaired body corners changed original corpus motion")
            frame_start += len(posed)
            all_new.append(posed)
            before_rgb, _ = renderer.render(baseline)
            after_rgb, _ = repaired_renderer.render(posed)
            source = source_images(frames[key], camera["sourceCrop"], 320)
            comparison(output / f"{key}_comparison.gif", [source[0], before_rgb, after_rgb],
                       ["DEF", "Shared-vertex ownership", "Semantic attachment repair"], f"{asset} {key}")
            result["cases"][key] = {"frames": len(posed), "fixedMotionSha256": digest(motion["jointWorld"]),
                                     "bodyCornerOriginalMotionMaxError": body_error,
                                     "boundaryGaps": boundary_gaps(posed.cpu().numpy(), topology["boundaryPairs"])}
            print(json.dumps({"completedGif": str(output / f"{key}_comparison.gif")}), flush=True)
        result["attachmentGate"] = attachment_quality(torch.cat(all_new), new_rest, repaired["triangles"],
            new_weights, labels, repaired["names"], [{"region": "declared_part", "donorJoints": [owner]}])
    # A detached part can pass rigidity while exposing holes. Never promote that
    # local result to attachment-surface or delivery approval.
    result["surfaceClosure"] = {"status": "unvalidated", "exportAllowed": False,
        "maxSeamDistance": max(row["boundaryGaps"]["maxDistance"] for row in result["cases"].values())}
    result["candidateValidForExport"] = False
    result["elapsedSeconds"] = time.perf_counter() - started
    result["implementation"] = {name: sha256_file(Path(__file__).parent / name)
                                for name in ("run_attachment_repair.py", "attachment_repair.py", "attachment_quality.py", "attachment_mask_refinement.py")}
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def load_repair(report_path, asset, fit_dir):
    """Read back the actual candidate and verify its deterministic provenance."""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("schema") != "attachment-repair-result-v1" or report.get("asset") != asset:
        raise ValueError("repair report schema/asset mismatch")
    fit, _, _, prepared, original, _, motions, _, provenance = _load_inputs(fit_dir, asset)
    if report.get("fitProvenance") != provenance:
        raise ValueError("repair fit provenance drift")
    recipe_path = Path(report["recipePath"])
    if not recipe_path.is_absolute() or sha256_file(recipe_path) != report["recipeSha256"]:
        raise ValueError("repair recipe identity drift")
    recipe, selected = load_recipe(recipe_path, asset, fit, original)
    body = original
    if recipe["consolidateRedundantOwner"]:
        body, consolidation = consolidate_redundant_owner(original,
            baseline_worlds(motions, fit.get("motionCompletion")), recipe["owner"])
        if consolidation != report.get("bodyOwnershipConsolidation"):
            raise ValueError("body consolidation provenance drift")
    expected, topology = split_attachment(body, selected, recipe["owner"])
    if topology != report["topology"]:
        raise ValueError("repair topology provenance drift")
    completion = report.get("motionCompletion")
    if completion != fit.get("motionCompletion"):
        if fit.get("motionCompletion") is not None or completion is None:
            raise ValueError("repair completion identity mismatch")
        path = Path(completion["reportPath"])
        if sha256_file(path) != completion["reportSha256"]:
            raise ValueError("repair completion report drift")
        motions, restored = apply_motion_completion(motions, prepared, path, asset,
            fit["inputs"]["corpusSha256"], fit["inputs"]["researchSkin"])
        if restored != completion:
            raise ValueError("repair completion provenance drift")
    if set(report["cases"]) != set(motions) or any(
            report["cases"][key]["fixedMotionSha256"] != digest(value["jointWorld"])
            for key, value in motions.items()):
        raise ValueError("repair fixed motion inventory drift")
    candidate_path = report_path.parent / "repaired_skin.npz"
    if sha256_file(candidate_path) != report["candidateSha256"]:
        raise ValueError("repaired skin hash drift")
    with np.load(candidate_path, allow_pickle=False) as data:
        repaired = {key: data[key].copy() for key in data.files}
    if set(repaired) != set(expected) or any(not np.array_equal(repaired[k], expected[k]) for k in expected):
        raise ValueError("serialized repair differs from declared shared operation")
    camera_path = Path(fit["baselineDirectory"]) / "camera.json"
    if sha256_file(camera_path) != report["cameraSha256"]:
        raise ValueError("repair camera source drift")
    return report, original, repaired, motions, selected


def preview_repair(fit_dir, report_path, output, asset):
    """Standard preview consumer for the saved repaired topology and weights."""
    from preview_skin_mesh_corpus import _offaxis_union_camera, FOCUS
    if output.exists():
        raise FileExistsError(output)
    report, original, repaired, motions, selected = load_repair(report_path, asset, fit_dir)
    owner = list(original["names"]).index(report["topology"]["owner"])
    baseline_weights = original["weights"].copy()
    ids = np.unique(original["triangles"][selected])
    baseline_weights[ids] = 0
    baseline_weights[ids, owner] = 1
    all_meshes = []
    pairs = {}
    for key, motion in motions.items():
        transforms = torch.as_tensor((motion["jointWorld"] @ original["inverseBind"][None])[:, :, :3], dtype=torch.float32)
        values = [deform(transforms, torch.as_tensor(w, dtype=torch.float32), torch.as_tensor(v, dtype=torch.float32))
                  for w, v in ((baseline_weights, original["vertices"]), (repaired["weights"], repaired["vertices"]))]
        all_meshes.extend([value.numpy() for value in values])
        pairs[key] = values
    camera = _offaxis_union_camera(report["camera"], all_meshes, 320)
    output.mkdir(parents=True)
    with cascade_batch_lock(ROOT):
        renderers = [SkinImageRenderer(s["triangles"], s["uvs"], s["albedo"], camera, 320)
                     for s in (original, repaired)]
        for key, values in pairs.items():
            if key not in FOCUS:
                continue
            images = [renderer.render(value.to("cuda"))[0] for renderer, value in zip(renderers, values)]
            comparison(output / f"{key}_comparison.gif", images, ["Before repair", "Saved repaired mesh"], f"Off-angle {asset} {key}")
    (output / "preview_manifest.json").write_text(json.dumps({"repairReport": str(report_path.resolve()),
        "repairReportSha256": sha256_file(report_path), "candidateSha256": report["candidateSha256"],
        "allCorpusClips": list(motions), "focusClips": [k for k in motions if k in FOCUS],
        "camera": camera, "proof": "generated-candidate-readback-render", "noOptimization": True}, indent=2) + "\n")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--fit-dir", type=Path, required=True)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--motion-completion-report", type=Path)
    args = parser.parse_args()
    report = run(args.asset, args.fit_dir, args.recipe, args.output, args.motion_completion_report)
    print(json.dumps({"output": str(args.output), "elapsedSeconds": report["elapsedSeconds"]}))
