"""Audit saved repair skins against immutable joint origins; CPU only."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from anatomical_chain_skin import initialize_profile_chains
from repair_skin_domain import condition_body_welds
from run_attachment_repair import load_repair
from run_attachment_skin_refit import load_refit
from run_skin_weight_pilot import get_profile
from run_skin_mesh_pilot import digest, sha256_file
from skin_joint_anchors import build_anchors, evaluate_anchors


def posed(skin, weights, worlds):
    rest = np.column_stack((skin["vertices"], np.ones(len(weights))))
    frames = []
    for world in worlds:
        transforms = (world @ skin["inverseBind"])[:, :3]
        blended = np.einsum("vj,jkl->vkl", weights, transforms)
        frames.append(np.einsum("vkl,vl->vk", blended, rest))
    return np.asarray(frames)


def audit_motion(skin, worlds):
    transforms = worlds @ skin["inverseBind"][None]
    rotations = transforms[:, :, :3, :3]
    bind_points = np.linalg.inv(skin["inverseBind"])[:, :, 3]
    rows = []
    for joint, parent in enumerate(skin["parents"]):
        if parent < 0:
            continue
        predicted = np.einsum("fij,j->fi", transforms[:, parent], bind_points[joint])[:, :3]
        error = np.linalg.norm(predicted - worlds[:, joint, :3, 3], axis=1)
        length = float(np.linalg.norm(bind_points[joint, :3] - bind_points[parent, :3]))
        rows.append({"joint": str(skin["names"][joint]), "maxSharedJointError": float(error.max()),
                     "bindLength": length, "relativeError": None if length == 0 else float(error.max() / length)})
    return {"singularValueDeviationMax": float(np.abs(np.linalg.svd(rotations, compute_uv=False) - 1).max()),
            "determinantDeviationMax": float(np.abs(np.linalg.det(rotations) - 1).max()), "joints": rows}


def run(asset, fit_dir, refit_path, output, chains):
    started = time.perf_counter()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    report, repair, skin, candidate, motions = load_refit(refit_path, asset, fit_dir)
    repair_path = Path(report["repairReport"])
    _, _, _, _, selected = load_repair(repair_path, asset, fit_dir)
    prop = np.zeros(len(skin["vertices"]), dtype=bool)
    prop[np.unique(skin["triangles"][selected])] = True
    profile = get_profile(asset)
    initialization = report.get("anatomicalInitialization")
    weights = skin["weights"]
    routing = {}
    if initialization is not None:
        replay = initialize_profile_chains(skin, selected, profile,
            report["anatomicalChainRegions"], schema=initialization["schema"])
        if replay["report"] != initialization:
            raise ValueError("initializer evidence drift")
        weights = replay["weights"]
        routing = initialization.get("bodyRegionRouting", {})
    conditioned = condition_body_welds(skin["vertices"], skin["triangles"], weights, selected)["conditionedWeights"]
    model = build_anchors(skin, prop, profile, list(chains), routing)
    cases = {}
    for key, motion in motions.items():
        worlds = motion["jointWorld"]
        meshes = {stage: posed(skin, value, worlds) for stage, value in
                  (("separated", skin["weights"]), ("initialized", conditioned), ("refitted", candidate["weights"]))}
        cases[key] = {"fixedMotionSha256": digest(worlds), "motion": audit_motion(skin, worlds),
                      "tracking": evaluate_anchors(model, meshes, worlds, {key: (0, len(worlds))})}
    result = {"schema": "saved-skin-joint-anchor-audit-v1", "asset": asset,
              "refitReport": str(refit_path.resolve()), "refitReportSha256": sha256_file(refit_path),
              "repairReportSha256": sha256_file(repair_path), "candidateSha256": report["candidateSha256"],
              "chains": list(chains), "model": model, "cases": cases,
              "proof": "saved-candidate CPU diagnostic; no acceptance or export", "accepted": False,
              "elapsedSecondsCached": time.perf_counter() - started,
              "implementation": {name: sha256_file(Path(__file__).with_name(name)) for name in
                                 ("run_skin_joint_anchor_audit.py", "skin_joint_anchors.py")}}
    output.mkdir(parents=True)
    path = output / "report.json"
    path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(path), "elapsedSecondsCached": result["elapsedSecondsCached"]}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--fit-dir", type=Path, required=True)
    parser.add_argument("--refit-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chains", nargs="+", required=True)
    args = parser.parse_args()
    run(args.asset, args.fit_dir.resolve(), args.refit_report.resolve(), args.output.resolve(), args.chains)


if __name__ == "__main__":
    main()
