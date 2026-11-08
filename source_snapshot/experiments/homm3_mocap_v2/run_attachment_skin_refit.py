"""Refit body skin on separated topology; captured motion and rest data are fixed.

Explicit research stage. It never promotes an open attachment to delivery.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from motion_retention_floor import RegionMotionFloor
from anatomical_chain_skin import initialize_profile_chains
from skin_joint_anchors import build_anchors
from joint_anchor_objective import FixedJointAnchorObjective
from repair_skin_domain import condition_body_welds, make_repair_domain, restore_source_owner_support
from run_attachment_repair import load_repair
from run_skin_mesh_pilot import (
    ROOT, SkinImageRenderer, comparison, deform, digest,
    expand_camera_to_full_canvas, optimize, sha256_file,
)
from run_skin_weight_pilot import cascade_batch_lock, source_images, get_profile
from run_surface_loss_attribution import _load_inputs
from skin_image_objective import image_loss
from skin_mesh_field import MeshField
from skin_surface_constraints import SurfaceConstraints
from topology_weight_field import RepairWeightField


def validate_candidate(original, candidate, domain):
    """Only declared train weights may change, including in serialized output."""
    if set(candidate) != set(original):
        raise ValueError("skin field inventory changed")
    for key in original:
        if key != "weights" and not np.array_equal(original[key], candidate[key]):
            raise ValueError(f"skin-only refit changed {key}")
    weights = np.asarray(candidate["weights"])
    if (weights.shape != original["weights"].shape or not np.isfinite(weights).all()
            or np.any(weights < 0) or not np.allclose(weights.sum(1), 1, atol=1e-6, rtol=0)):
        raise ValueError("candidate weights must be finite normalized nonnegative VxJ")
    if np.any(weights[~domain["allowedSupport"]] != 0) or np.any((weights > 0).sum(1) > 8):
        raise ValueError("candidate weights exceed declared support")
    frozen = ~domain["trainMask"]
    if not np.array_equal(weights[frozen], original["weights"][frozen]):
        raise ValueError("candidate changed frozen ownership weights")
    groups = {}
    for vertex in np.flatnonzero(domain["trainMask"]):
        key = (int(domain["ownershipIds"][vertex]), tuple(original["vertices"][vertex]))
        if key in groups and not np.array_equal(weights[vertex], weights[groups[key]]):
            raise ValueError("candidate split a body weight weld")
        groups[key] = vertex
    return {"restAndTopologyExact": True, "frozenWeightsExact": True,
            "maxInfluences": int((weights > 0).sum(1).max()),
            "changedVertexCount": int(np.any(weights != original["weights"], axis=1).sum())}


def _anchor_spec(skin, domain, profile, regions, initialization, motions, weight):
    if not np.isfinite(weight) or weight < 0:
        raise ValueError("joint anchor weight must be finite and nonnegative")
    if weight == 0:
        return None
    if not regions:
        raise ValueError("joint anchor objective requires explicit anatomical chains")
    worlds = np.concatenate([motion["jointWorld"] for motion in motions.values()])
    model = build_anchors(skin, ~domain["trainMask"], profile, list(regions),
                          initialization.get("bodyRegionRouting", {}))
    coverage = FixedJointAnchorObjective(model, worlds, len(skin["vertices"]), "cpu").report()
    return {"schema": "fixed-joint-anchor-objective-v1", "weight": float(weight),
            "model": model, "jointWorldSha256": digest(worlds), "coverage": coverage}


def load_refit(report_path, asset, fit_dir):
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("schema") not in ("attachment-skin-refit-v1", "attachment-skin-refit-v2", "attachment-skin-refit-v3") or report.get("asset") != asset:
        raise ValueError("skin refit schema/asset mismatch")
    source = Path(report["repairReport"])
    if not source.is_absolute() or sha256_file(source) != report["repairReportSha256"]:
        raise ValueError("repair source identity drift")
    repair, fitted, original, motions, selected = load_repair(source, asset, fit_dir)
    initialization = {"weights": original["weights"], "report": None}
    if report["schema"] == "attachment-skin-refit-v3":
        regions = report.get("anatomicalChainRegions")
        if not isinstance(regions, list) or any(not isinstance(region, str) for region in regions):
            raise ValueError("anatomical chain region inventory is malformed")
        initialization = initialize_profile_chains(original, selected, get_profile(asset), tuple(regions),
            schema=report["anatomicalInitialization"]["schema"])
        if initialization["report"] != report.get("anatomicalInitialization"):
            raise ValueError("anatomical initialization evidence drift")
    conditioning = condition_body_welds(original["vertices"], original["triangles"], initialization["weights"], selected)
    if digest(conditioning["conditionedWeights"]) != report["conditionedWeightsSha256"]:
        raise ValueError("conditioned weld weights drift")
    support_options = {}
    if report["schema"] in ("attachment-skin-refit-v2", "attachment-skin-refit-v3"):
        support_options = {"source_weights_mapped": fitted["weights"][original["sourceVertexIds"]],
                           "owner_id": repair["topology"]["ownerIndex"]}
    domain = make_repair_domain(original["vertices"], original["triangles"],
                               conditioning["conditionedWeights"], selected,
                               neighbor_rings=report["neighborRings"], **support_options)
    if report["schema"] in ("attachment-skin-refit-v2", "attachment-skin-refit-v3"):
        if domain["report"] != report["domain"]:
            raise ValueError("source owner support evidence drift")
    domain_path = report_path.parent / "domain.npz"
    if sha256_file(domain_path) != report["domainSha256"]:
        raise ValueError("skin domain identity drift")
    with np.load(domain_path, allow_pickle=False) as data:
        keys = {"ownershipIds", "trainMask", "allowedSupport"}
        if set(data.files) != keys or any(not np.array_equal(data[key], domain[key]) for key in keys):
            raise ValueError("skin domain differs from declared topology support")
    path = report_path.parent / "refitted_skin.npz"
    if sha256_file(path) != report["candidateSha256"]:
        raise ValueError("skin candidate identity drift")
    with np.load(path, allow_pickle=False) as data:
        candidate = {key: data[key].copy() for key in data.files}
    contract = validate_candidate(original, candidate, domain)
    if contract != report["invariants"]:
        raise ValueError("skin invariant report drift")
    if set(report["cases"]) != set(motions) or any(
            report["cases"][key]["fixedMotionSha256"] != digest(value["jointWorld"])
            for key, value in motions.items()):
        raise ValueError("skin refit motion inventory drift")
    anchor_spec = report.get("jointAnchorObjective")
    if anchor_spec is not None:
        if report["schema"] != "attachment-skin-refit-v3":
            raise ValueError("joint anchor objective requires anatomical refit provenance")
        reconstructed = _anchor_spec(original, domain, get_profile(asset), regions,
                                     initialization["report"], motions, anchor_spec["weight"])
        if reconstructed != anchor_spec:
            raise ValueError("joint anchor objective evidence drift")
    return report, repair, original, candidate, motions


def _scores(rendered, targets):
    return {key: float(value.detach()) for key, value in image_loss(*rendered, *targets).items()}


def run(asset, fit_dir, repair_report, output, *, seconds=240, iterations=200,
        neighbor_rings=1, anatomical_chain_regions=(), joint_anchor_weight=0):
    started = time.perf_counter()
    if not np.isfinite(seconds) or not 1 <= seconds <= 600 or type(iterations) is not int or iterations < 1:
        raise ValueError("require 1..600 optimization seconds and positive integer iterations")
    if output.exists():
        raise FileExistsError(output)
    repair, fitted, skin, motions, selected = load_repair(repair_report, asset, fit_dir)
    _, _, _, _, _, _, _, frame_paths, _ = _load_inputs(fit_dir, asset)
    if anatomical_chain_regions is None:
        anatomical_chain_regions = ()
    if isinstance(anatomical_chain_regions, str):
        raise ValueError("anatomical_chain_regions must be a sequence of region names")
    anatomical_chain_regions = tuple(anatomical_chain_regions)
    initialization = initialize_profile_chains(skin, selected, get_profile(asset), anatomical_chain_regions,
        schema="profile-chain-initialization-v2")
    conditioning = condition_body_welds(skin["vertices"], skin["triangles"], initialization["weights"], selected)
    conditioned_weights = conditioning["conditionedWeights"]
    domain = make_repair_domain(skin["vertices"], skin["triangles"], conditioned_weights,
                               selected, neighbor_rings=neighbor_rings,
                               source_weights_mapped=fitted["weights"][skin["sourceVertexIds"]],
                               owner_id=repair["topology"]["ownerIndex"])
    anchor_spec = _anchor_spec(skin, domain, get_profile(asset), anatomical_chain_regions,
                              initialization["report"], motions, joint_anchor_weight)
    camera = expand_camera_to_full_canvas(repair["camera"], 224)
    slices, packed, cursor = {}, [], 0
    for key, motion in motions.items():
        count = len(motion["jointWorld"])
        if len(frame_paths[key]) != count:
            raise ValueError("source and motion frame counts differ")
        slices[key] = (cursor, cursor + count)
        cursor += count
        packed.append((motion["jointWorld"] @ skin["inverseBind"][None])[:, :, :3])
    output.mkdir(parents=True)
    report = {"schema": "attachment-skin-refit-v3", "asset": asset,
              "repairReport": str(repair_report.resolve()), "repairReportSha256": sha256_file(repair_report),
              "neighborRings": neighbor_rings, "anatomicalChainRegions": list(anatomical_chain_regions),
              "anatomicalInitialization": initialization["report"], "domain": domain["report"], "camera": camera,
              "conditioning": {key: value for key, value in conditioning.items() if key != "conditionedWeights"},
              "conditionedWeightsSha256": digest(conditioned_weights),
              "trainingScope": "all source frames; all nonprop body vertices; no heldout claim",
              "frameCount": cursor, "iterationsRequested": iterations, "optimizationSecondsBudget": seconds,
              "accepted": False, "candidateValidForExport": False,
              "surfaceClosure": "unvalidated", "cases": {}}
    np.savez_compressed(output / "domain.npz", **{key: domain[key] for key in ("ownershipIds", "trainMask", "allowedSupport")})
    report["jointAnchorObjective"] = anchor_spec
    report["domainSha256"] = sha256_file(output / "domain.npz")
    with cascade_batch_lock(ROOT):
        field = RepairWeightField(skin["vertices"], skin["triangles"], conditioned_weights,
                                  ownership_ids=domain["ownershipIds"], train_mask=domain["trainMask"],
                                  allowed_support=domain["allowedSupport"], device="cuda")
        # This adapter remains entirely frozen. No lattice correction is enabled.
        mesh_field = MeshField(skin["vertices"], skin["regions"], set(skin["regions"]), device="cuda")
        transforms = torch.as_tensor(np.concatenate(packed), dtype=torch.float32, device="cuda")
        rest = mesh_field.rest_vertices
        original_weights = torch.as_tensor(skin["weights"], dtype=torch.float32, device="cuda")
        before = deform(transforms, original_weights, rest).detach()
        conditioned = deform(transforms, torch.as_tensor(conditioned_weights, dtype=torch.float32, device="cuda"), rest).detach()
        surface = SurfaceConstraints(skin["vertices"], skin["triangles"], device="cuda")
        renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], camera, 224)
        batches = [source_images(frame_paths[key], camera["sourceCrop"], 224) for key in motions]
        targets = tuple(torch.cat([batch[i] for batch in batches]) for i in range(3))
        regions = np.asarray(skin["regions"]).astype("U128")
        regions[~domain["trainMask"]] = "declared_rigid_part"
        floor = RegionMotionFloor(before, regions, slices, fraction=.9,
                                  min_range=float(np.linalg.norm(np.ptp(skin["vertices"], axis=0))) * .005)
        anchor_objective = None if anchor_spec is None else FixedJointAnchorObjective(
            anchor_spec["model"], np.concatenate([motion["jointWorld"] for motion in motions.values()]),
            len(skin["vertices"]), "cuda")
        fit_start = time.perf_counter()
        report["history"] = optimize(field, mesh_field, transforms, surface, renderer,
                                     torch.arange(cursor, device="cuda"), targets,
                                     renderer.render(rest[None]), tuple(value[:1] for value in targets),
                                     iterations=iterations, deadline=fit_start + seconds,
                                     allow_mesh=False, motion_floor=floor,
                                     joint_anchor=anchor_objective, joint_anchor_weight=joint_anchor_weight)
        report["optimizationElapsedSeconds"] = time.perf_counter() - fit_start
        field.validate()
        candidate = {key: value.copy() for key, value in skin.items()}
        # Preserve frozen input values byte-for-byte, not through a float32 roundtrip.
        learned = field.weights().detach().cpu().numpy()
        candidate["weights"][domain["trainMask"]] = learned[domain["trainMask"]]
        report["invariants"] = validate_candidate(skin, candidate, domain)
        np.savez_compressed(output / "refitted_skin.npz", **candidate)
        report["candidateSha256"] = sha256_file(output / "refitted_skin.npz")
        # Render the serialized candidate, not optimizer memory.
        with np.load(output / "refitted_skin.npz", allow_pickle=False) as data:
            saved = {key: data[key].copy() for key in data.files}
        validate_candidate(skin, saved, domain)
        after = deform(transforms, torch.as_tensor(saved["weights"], dtype=torch.float32, device="cuda"), rest).detach()
        report["motionFloor"] = floor.report(after)
        if anchor_objective is not None:
            report["jointAnchorLoss"] = {key: float(anchor_objective.loss(value).detach()) for key, value in
                                         (("before", before), ("initialized", conditioned), ("after", after))}
        for key, (start, end) in slices.items():
            current_targets = tuple(value[start:end] for value in targets)
            rendered = [renderer.render(value[start:end]) for value in (before, conditioned, after)]
            frozen_error = float((after[start:end, ~domain["trainMask"]] - before[start:end, ~domain["trainMask"]]).abs().max())
            if frozen_error != 0:
                raise ValueError("frozen part playback changed")
            report["cases"][key] = {"fixedMotionSha256": digest(motions[key]["jointWorld"]),
                                   "frozenPlaybackMaxError": frozen_error,
                                   "image": {"before": _scores(rendered[0], current_targets), "conditioned": _scores(rendered[1], current_targets), "after": _scores(rendered[2], current_targets)},
                                   "surface": {"before": surface.metrics(before[start:end]), "conditioned": surface.metrics(conditioned[start:end]), "after": surface.metrics(after[start:end])}}
            comparison(output / f"{key}_comparison.gif", [current_targets[0]] + [value[0] for value in rendered],
                       ["DEF", "Separated ownership", "Skin initialization", "Post-separation skin fit"], f"{asset} {key}")
            print(json.dumps({"completedGif": str(output / f"{key}_comparison.gif")}), flush=True)
    report["elapsedSecondsCached"] = time.perf_counter() - started
    report["implementation"] = {name: sha256_file(Path(__file__).parent / name) for name in
                                ("run_attachment_skin_refit.py", "repair_skin_domain.py", "anatomical_chain_skin.py", "topology_weight_field.py", "run_skin_mesh_pilot.py", "skin_joint_anchors.py", "joint_anchor_objective.py")}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    load_refit(output / "report.json", asset, fit_dir)
    return report


def preview(fit_dir, report_path, output, asset):
    from preview_skin_mesh_corpus import FOCUS, _offaxis_union_camera
    if output.exists():
        raise FileExistsError(output)
    report, repair, original, candidate, motions = load_refit(report_path, asset, fit_dir)
    pairs = {}
    all_meshes = []
    for key, motion in motions.items():
        transforms = torch.as_tensor((motion["jointWorld"] @ original["inverseBind"][None])[:, :, :3], dtype=torch.float32)
        pairs[key] = [deform(transforms, torch.as_tensor(skin["weights"], dtype=torch.float32),
                             torch.as_tensor(skin["vertices"], dtype=torch.float32)) for skin in (original, candidate)]
        all_meshes.extend(value.numpy() for value in pairs[key])
    camera = _offaxis_union_camera(repair["camera"], all_meshes, 320)
    output.mkdir(parents=True)
    with cascade_batch_lock(ROOT):
        renderer = SkinImageRenderer(candidate["triangles"], candidate["uvs"], candidate["albedo"], camera, 320)
        for key, values in pairs.items():
            if key in FOCUS:
                images = [renderer.render(value.to("cuda"))[0] for value in values]
                comparison(output / f"{key}_comparison.gif", images,
                           ["Separated ownership", "Saved refitted skin"], f"Off-angle {asset} {key}")
    (output / "preview_manifest.json").write_text(json.dumps({"sourceReport": str(report_path.resolve()),
        "sourceReportSha256": sha256_file(report_path), "camera": camera,
        "candidateSha256": report["candidateSha256"], "proof": "generated-candidate-readback-render",
        "allCorpusClips": list(motions), "focusClips": [key for key in motions if key in FOCUS]}, indent=2) + "\n")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--fit-dir", type=Path, required=True)
    parser.add_argument("--repair-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=240)
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--neighbor-rings", type=int, default=1)
    parser.add_argument("--anatomical-chain-regions", nargs="+", default=None)
    parser.add_argument("--joint-anchor-weight", type=float, default=0)
    parser.add_argument("--preview-only", action="store_true", help="repair-report then names a saved skin-refit report")
    args = parser.parse_args()
    if args.preview_only:
        print(preview(args.fit_dir, args.repair_report, args.output, args.asset))
    else:
        result = run(args.asset, args.fit_dir, args.repair_report, args.output,
                     seconds=args.seconds, iterations=args.iterations, neighbor_rings=args.neighbor_rings,
                     anatomical_chain_regions=args.anatomical_chain_regions,
                     joint_anchor_weight=args.joint_anchor_weight)
        print(json.dumps({"output": str(args.output), "elapsedSecondsCached": result["elapsedSecondsCached"]}))
