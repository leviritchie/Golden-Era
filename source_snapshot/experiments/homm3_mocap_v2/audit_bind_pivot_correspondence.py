"""Measure fitted bind sites against explicitly paired target chain evidence.

Read-only diagnostic: equal chain cardinality permits a correspondence check,
not a claim that source bone labels or anatomy are automatically correct.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import run_shape_preserved as shared
from prepare_mapped_skin_asset import _profile_hash


def audit(asset):
    profile = shared.get_profile(asset)
    freeze_path = shared.prep_freeze_path(asset)
    freeze = json.loads(freeze_path.read_text())
    if freeze["inputHashes"]["profile"] != _profile_hash(profile):
        raise ValueError(f"frozen preparation profile changed: {asset}")
    skin_path = Path(freeze["researchSkin"])
    if shared.sha256_file(skin_path) != freeze["inputHashes"]["researchSkin"]:
        raise ValueError(f"frozen preparation skin changed: {asset}")
    target = shared.load_target_asset(profile)
    with np.load(skin_path, allow_pickle=False) as skin:
        names = list(skin["names"].astype(str))
        fitted = shared.compute_rest_joints(skin["offsets"], skin["parents"])
    target_index = {name: i for i, name in enumerate(target["names"])}
    bbox = float(np.linalg.norm(np.ptp(target["vertices"], axis=0)))
    rows, unpaired = [], []
    for chain in profile["chains"]:
        if chain["kind"] != "polyline":
            continue
        donor, evidence = chain["donor"], chain["evidence"]
        if len(donor) != len(evidence):
            unpaired.append({"chain": chain["name"], "donorCount": len(donor),
                             "evidenceCount": len(evidence)})
            continue
        expected = np.asarray([target["restWorld"][target_index[n]] for n in evidence])
        for i, (joint, source_bone) in enumerate(zip(donor, evidence)):
            actual = fitted[names.index(joint)]
            delta = float(np.linalg.norm(actual - expected[i]))
            segment = float(np.linalg.norm(expected[i] - expected[i - 1])) if i else None
            rows.append({"chain": chain["name"], "joint": joint, "sourceBone": source_bone,
                         "expected": expected[i].tolist(), "fitted": actual.tolist(),
                         "distance": delta, "bboxFraction": delta / bbox,
                         "precedingSegmentFraction": delta / segment if segment else None})
    return {"asset": asset, "proof": "bind_site_diagnostic", "accepted": False,
            "skinSha256": shared.sha256_file(skin_path), "profileHash": _profile_hash(profile),
            "meshSha256": target["sourceSha256"], "bboxDiagonal": bbox,
            "pairedSites": rows, "unpairedChains": unpaired,
            "maxDistance": max((row["distance"] for row in rows), default=0.0),
            "maxBboxFraction": max((row["bboxFraction"] for row in rows), default=0.0)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    report = {"scope": "paired polyline sites only; no motion or skin changes",
              "assets": [audit(asset) for asset in args.assets]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    for row in report["assets"]:
        print(json.dumps({key: row[key] for key in
                          ("asset", "maxDistance", "maxBboxFraction", "unpairedChains")}))
