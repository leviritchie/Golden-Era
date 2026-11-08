"""Explicit fixed-motion anatomical skin counterfactual; never a delivery stage."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from anatomical_chain_skin import initialize_profile_chains
from repair_skin_domain import condition_body_welds
from run_attachment_repair import load_repair
from run_attachment_skin_refit import validate_candidate
from run_skin_mesh_pilot import ROOT, SkinImageRenderer, comparison, deform, digest, sha256_file
from run_skin_weight_pilot import cascade_batch_lock, get_profile, source_images
from run_surface_loss_attribution import _load_inputs
from preview_skin_mesh_corpus import _offaxis_union_camera
from skin_image_objective import image_loss


def run(asset, fit_dir, repair_path, regions, output):
    started = time.perf_counter()
    if output.exists():
        raise FileExistsError(output)
    if not regions or len(set(regions)) != len(regions):
        raise ValueError("explicit unique chain regions required")
    repair, _, skin, motions, selected = load_repair(repair_path, asset, fit_dir)
    _, _, _, _, _, _, _, frames, _ = _load_inputs(fit_dir, asset)
    prop = np.zeros(len(skin["vertices"]), dtype=bool)
    prop[np.unique(skin["triangles"][selected])] = True
    initialization = initialize_profile_chains(skin, selected, get_profile(asset), regions)
    weights = initialization["weights"]
    evidence = initialization["report"]
    conditioned = condition_body_welds(skin["vertices"], skin["triangles"], weights, selected)
    candidate = {key: value.copy() for key, value in skin.items()}
    candidate["weights"] = conditioned["conditionedWeights"]
    domain = {"ownershipIds": prop.astype(np.int8), "trainMask": ~prop,
              "allowedSupport": candidate["weights"] > 0}
    invariants = validate_candidate(skin, candidate, domain)
    output.mkdir(parents=True)
    path = output / "candidate.npz"
    np.savez_compressed(path, **candidate)
    with np.load(path, allow_pickle=False) as data:
        saved = {key: data[key].copy() for key in data.files}
    validate_candidate(skin, saved, domain)
    if any(not np.array_equal(saved[key], candidate[key]) for key in candidate):
        raise ValueError("serialized candidate differs from constructed trial")
    pairs = {}
    for key, motion in motions.items():
        if len(frames[key]) != len(motion["jointWorld"]):
            raise ValueError("source and motion frame counts differ")
        transforms = torch.as_tensor((motion["jointWorld"] @ skin["inverseBind"][None])[:, :, :3], dtype=torch.float32)
        pairs[key] = [deform(transforms, torch.as_tensor(item["weights"], dtype=torch.float32),
                            torch.as_tensor(item["vertices"], dtype=torch.float32)) for item in (skin, saved)]
    camera = repair["camera"]
    offaxis = _offaxis_union_camera(camera, [v.numpy() for pair in pairs.values() for v in pair])
    report = {"schema": "anatomical-chain-trial-v1", "asset": asset,
              "repairReport": str(repair_path.resolve()), "repairReportSha256": sha256_file(repair_path),
              "candidateSha256": sha256_file(path), "regions": evidence,
              "fitProvenance": repair["fitProvenance"],
              "offaxisProof": "visual comparison only; no offaxis source target",
              "invariants": invariants, "camera": camera, "offaxisCamera": offaxis,
              "accepted": False, "candidateValidForExport": False, "cases": {}}
    with cascade_batch_lock(ROOT):
        front = SkinImageRenderer(saved["triangles"], saved["uvs"], saved["albedo"], camera, 320)
        side = SkinImageRenderer(saved["triangles"], saved["uvs"], saved["albedo"], offaxis, 320)
        for key, pair in pairs.items():
            targets = source_images(frames[key], camera["sourceCrop"], 320)
            rendered = [front.render(v.to("cuda")) for v in pair]
            comparison(output / f"{key}_comparison.gif", [targets[0]] + [r[0] for r in rendered],
                       ["DEF", "Separated skin", "Anatomical chain trial"], f"{asset} {key}")
            comparison(output / f"{key}_offaxis.gif", [side.render(v.to("cuda"))[0] for v in pair],
                       ["Separated skin", "Anatomical chain trial"], f"Off-angle {asset} {key}")
            report["cases"][key] = {"fixedMotionSha256": digest(motions[key]["jointWorld"]),
                "image": [{k: float(v.detach()) for k, v in image_loss(*r, *targets).items()} for r in rendered]}
            print(json.dumps({"completedGif": str(output / f"{key}_offaxis.gif")}), flush=True)
    report["elapsedSecondsCached"] = time.perf_counter() - started
    report["implementation"] = {name: sha256_file(Path(__file__).parent / name)
                                for name in ("run_anatomical_chain_trial.py", "anatomical_chain_skin.py")}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--fit-dir", type=Path, required=True)
    parser.add_argument("--repair-report", type=Path, required=True)
    parser.add_argument("--regions", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.asset, args.fit_dir, args.repair_report, args.regions, args.output)
    print(json.dumps({"elapsedSecondsCached": result["elapsedSecondsCached"]}))
