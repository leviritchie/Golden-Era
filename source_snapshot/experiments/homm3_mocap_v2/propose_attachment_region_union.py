"""Create an explicit, review-unready union of a mask and one profile region."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from run_attachment_repair import load_repair
from run_skin_weight_pilot import get_profile


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def union_face_region(triangles: Any, labels: Any, existing_face_ids: Any,
                      region: str) -> dict[str, Any]:
    """Union existing face IDs with faces whose three corners have *region*."""
    tri = np.asarray(triangles)
    names = np.asarray(labels)
    existing = np.asarray(existing_face_ids)
    if tri.ndim != 2 or tri.shape[1] != 3 or tri.dtype.kind not in "iu":
        raise ValueError("triangles must be integer [F,3]")
    if len(tri) == 0 or np.any(tri < 0) or np.any(tri >= len(names)):
        raise ValueError("triangle indices are outside labels")
    if names.ndim != 1 or len(names) == 0 or names.dtype.kind not in "OU" or any(not isinstance(x, str) or not x for x in names.tolist()):
        raise ValueError("labels must be one-dimensional string labels")
    if not isinstance(region, str) or not region:
        raise ValueError("region must be a non-empty string")
    if existing.ndim != 1 or existing.dtype.kind not in "iu" or len(np.unique(existing)) != len(existing):
        raise ValueError("existing_face_ids must be unique integer IDs")
    if np.any(existing < 0) or np.any(existing >= len(tri)):
        raise ValueError("existing_face_ids are outside triangles")
    labels_str = names.astype(str, copy=False)
    region_faces = np.flatnonzero(np.all(labels_str[tri] == region, axis=1)).astype(np.int64)
    union = np.union1d(existing.astype(np.int64, copy=False), region_faces)
    return {"faceIds": union, "regionFaceIds": region_faces,
            "addedFaceIds": np.setdiff1d(region_faces, existing, assume_unique=True),
            "existingFaceCount": int(len(existing)), "regionFaceCount": int(len(region_faces)),
            "unionFaceCount": int(len(union))}


def _profile_region(asset: str, region: str, owner: str) -> dict[str, Any]:
    matches = [item for item in get_profile(asset).get("rigidAttachments", ())
               if isinstance(item, dict) and item.get("region") == region]
    if len(matches) != 1:
        raise ValueError("region must match exactly one profile rigidAttachments descriptor")
    descriptor = matches[0]
    donors = tuple(str(value) for value in descriptor.get("donorJoints", ()))
    if owner not in donors:
        raise ValueError("repair topology owner is not a donor for the selected rigid region")
    return {"region": region, "donorJoints": list(donors), "reason": descriptor.get("reason")}


def _snapshot_recipe(repair: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    """Read the hash-pinned recipe snapshot, never mutable history metadata."""
    recipe_path = Path(repair["recipePath"]).resolve()
    if not recipe_path.is_absolute() or sha256_file(recipe_path) != repair.get("recipeSha256"):
        raise ValueError("repair recipe snapshot identity drift")
    return recipe_path, json.loads(recipe_path.read_text(encoding="utf-8"))


def run(asset: str, fit_dir: Path, repair_report: Path, region: str, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    repair_report = repair_report.resolve()
    repair, original, _, _, selected = load_repair(repair_report, asset, fit_dir.resolve())
    source_recipe_path, source_recipe = _snapshot_recipe(repair)
    owner = source_recipe.get("owner")
    descriptor = _profile_region(asset, region, owner)
    source_mask_dir = Path(source_recipe["maskDirectory"]).resolve()
    source_mask = source_mask_dir / "face_proposal.npz"
    source_mask_report = source_mask_dir / "report.json"
    if not source_mask.is_file() or not source_mask_report.is_file():
        raise FileNotFoundError("source mask directory must contain face_proposal.npz and report.json")
    if sha256_file(source_mask) != source_recipe["maskSha256"] or sha256_file(source_mask_report) != source_recipe["maskReportSha256"]:
        raise ValueError("source mask identity drift")
    with np.load(source_mask, allow_pickle=False) as data:
        arrays = {key: data[key].copy() for key in data.files}
    if "propTriangles" not in arrays:
        raise ValueError("source proposal lacks propTriangles")
    if "faceIds" in arrays and not np.array_equal(arrays["faceIds"], arrays["propTriangles"]):
        raise ValueError("source proposal face aliases disagree")
    union = union_face_region(original["triangles"], original["regions"], selected, region)
    arrays["propTriangles"] = union["faceIds"]
    if "faceIds" in arrays:
        arrays["faceIds"] = union["faceIds"].copy()
    output.mkdir(parents=True)
    mask_path = output / "face_proposal.npz"
    np.savez_compressed(mask_path, **arrays)
    fit_provenance = repair.get("fitProvenance")
    prepared_hash = fit_provenance["preparedSkinSha256"]
    report = {
        "schema": "attachment-region-union-v1", "asset": asset,
        "researchSkinSha256": prepared_hash, "preparedSkinSha256": prepared_hash,
        "repairReport": str(repair_report), "repairReportSha256": sha256_file(repair_report),
        "sourceRecipePath": str(source_recipe_path), "sourceRecipeSha256": sha256_file(source_recipe_path),
        "sourceMaskDirectory": str(source_mask_dir), "sourceMaskSha256": sha256_file(source_mask),
        "sourceMaskReportSha256": sha256_file(source_mask_report),
        "fitProvenance": fit_provenance, "regionRule": descriptor,
        "existingSelectedFaceCount": union["existingFaceCount"],
        "regionFaceCount": union["regionFaceCount"], "addedFaceCount": int(len(union["addedFaceIds"])),
        "unionFaceCount": union["unionFaceCount"], "addedFaceIds": union["addedFaceIds"].tolist(),
        "maskSha256": sha256_file(mask_path),
        "uncertainty": "unreviewed", "accepted": False, "proof": "diagnostic-region-union-proposal",
        "implementationSha256": sha256_file(Path(__file__)),
    }
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    recipe = {"schema": "attachment-repair-recipe-v1", "asset": asset,
              "preparedSkinSha256": prepared_hash, "maskDirectory": str(output.resolve()),
              "maskReportSha256": sha256_file(report_path), "maskSha256": sha256_file(mask_path),
              "attachmentType": source_recipe["attachmentType"],
              "consolidateRedundantOwner": source_recipe["consolidateRedundantOwner"],
              "maskRefinement": "none", "owner": owner,
              "authorship": "Explicit existing-mask plus profile-region union; unreviewed diagnostic input."}
    (output / "recipe.json").write_text(json.dumps(recipe, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"output": str(output.resolve()), "report": report, "recipe": recipe}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", required=True)
    parser.add_argument("--fit-dir", type=Path, required=True)
    parser.add_argument("--repair-report", type=Path, required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.asset, args.fit_dir, args.repair_report, args.region, args.output), indent=2))
