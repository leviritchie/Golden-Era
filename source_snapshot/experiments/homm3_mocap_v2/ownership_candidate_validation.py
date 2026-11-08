"""Fail-closed validation and CPU probe report for a mounted skin candidate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

try:
    from .mounted_ownership_diagnostic import probe
except ImportError:
    from mounted_ownership_diagnostic import probe


def validate_invariants(original: dict, candidate: dict, weapon_regions=()) -> dict:
    for key in ("vertices", "triangles", "uvs", "albedo", "names", "parents", "offsets", "captureOffsets", "inverseBind", "regions"):
        if key not in original or key not in candidate or not np.array_equal(original[key], candidate[key]):
            raise ValueError(f"candidate changed invariant field: {key}")
    has_rest = ("restAnchors" in original, "restAnchors" in candidate)
    if has_rest[0] != has_rest[1]:
        raise ValueError("restAnchors evidence must be present in both skins or neither")
    if has_rest[0] and not np.array_equal(original["restAnchors"], candidate["restAnchors"]):
        raise ValueError("candidate changed invariant field: restAnchors")
    weights = np.asarray(candidate["weights"], dtype=float)
    if weights.shape != (len(candidate["vertices"]), len(candidate["names"])):
        raise ValueError("candidate weights must be V x J")
    if weights.ndim != 2 or not np.isfinite(weights).all() or np.any(weights < -1e-10):
        raise ValueError("candidate weights must be finite and non-negative")
    if not np.allclose(weights.sum(axis=1), 1.0, atol=1e-8):
        raise ValueError("candidate weights must have normalized rows")
    if np.any(np.count_nonzero(weights > 1e-8, axis=1) > 8):
        raise ValueError("candidate contains a vertex with more than 8 influences")
    regions = np.asarray(candidate.get("regions", []), dtype=str)
    original_weights = np.asarray(original["weights"], dtype=float)
    for region in weapon_regions:
        rows = np.flatnonzero(regions == str(region))
        if len(rows) and (np.any(np.count_nonzero(weights[rows] > 1e-8, axis=1) != 1) or
                          np.any(np.argmax(weights[rows], axis=1) != np.argmax(original_weights[rows], axis=1))):
            raise ValueError(f"weapon region is not rigid: {region}")
    # Coincident source vertices must retain identical candidate ownership.
    vertices = np.asarray(candidate["vertices"])
    for _, rows in _coincident_groups(vertices):
        if len(rows) > 1 and not np.allclose(weights[rows], weights[rows[0]], atol=1e-10, rtol=0):
            raise ValueError("coincident vertices have divergent candidate weights")
    return {"invariants": True, "vertexCount": len(vertices), "jointCount": weights.shape[1],
            "maxInfluences": int(np.count_nonzero(weights > 1e-8, axis=1).max(initial=0))}


def _coincident_groups(vertices):
    groups = {}
    for i, vertex in enumerate(np.asarray(vertices)):
        groups.setdefault(tuple(vertex.tolist()), []).append(i)
    return [(key, np.asarray(rows, dtype=int)) for key, rows in groups.items()]


def probe_report(skin: dict) -> dict:
    reports = {}
    joints = [str(x) for x in skin["names"]]
    targets = [x for x in joints if x in {"rider:mixamorig:RightArm", "rider:mixamorig:LeftArm", "mount:Bip01_Neck"}]
    required = {"rider:mixamorig:RightArm", "rider:mixamorig:LeftArm", "mount:Bip01_Neck"}
    if set(targets) != required:
        raise ValueError(f"required probe joints missing: {sorted(required - set(targets))}")
    for joint in targets:
        for axis_name, axis in (("X", (1, 0, 0)), ("Y", (0, 1, 0)), ("Z", (0, 0, 1))):
            for degrees in (-30.0, 30.0, -60.0, 60.0):
                result = probe(skin["vertices"], skin["triangles"], skin["weights"], skin["names"],
                               skin["parents"], skin["restAnchors"], skin["inverseBind"], joint,
                               skin.get("regions"), degrees, axis)
                moved = result.pop("moved")
                edge = _edge_ratios(skin["vertices"], moved, skin["triangles"])
                result["worstMeanEdgeRatio"] = float(np.max(edge, initial=1.0))
                result["trianglesAbove2x"] = int(np.count_nonzero((edge > 2.0) | (edge < 0.5)))
                reports[f"{joint}:{axis_name}:{degrees:g}"] = result
    return reports


def _edge_ratios(original, posed, triangles):
    tri = np.asarray(triangles, dtype=int)
    before_edges = np.stack((np.linalg.norm(original[tri[:, 1]] - original[tri[:, 0]], axis=1),
                             np.linalg.norm(original[tri[:, 2]] - original[tri[:, 1]], axis=1),
                             np.linalg.norm(original[tri[:, 0]] - original[tri[:, 2]], axis=1)))
    after_edges = np.stack((np.linalg.norm(posed[tri[:, 1]] - posed[tri[:, 0]], axis=1),
                            np.linalg.norm(posed[tri[:, 2]] - posed[tri[:, 1]], axis=1),
                            np.linalg.norm(posed[tri[:, 0]] - posed[tri[:, 2]], axis=1)))
    return np.mean(after_edges / np.maximum(before_edges, 1e-8), axis=0)


def compare_probes(original: dict, candidate: dict, threshold=0.70) -> dict:
    regions = np.asarray(original["regions"], dtype=str)
    details = {}
    for joint in ("rider:mixamorig:RightArm", "rider:mixamorig:LeftArm", "mount:Bip01_Neck"):
        active_region = {"rider:mixamorig:RightArm": "rider_arm_right",
                         "rider:mixamorig:LeftArm": "rider_arm_left",
                         "mount:Bip01_Neck": "mount_head"}[joint]
        mask = regions == active_region
        if not np.any(mask):
            raise ValueError(f"no active region vertices for {joint}")
        for axis_name, axis in (("X", (1, 0, 0)), ("Y", (0, 1, 0)), ("Z", (0, 0, 1))):
            for degrees in (-30.0, 30.0, -60.0, 60.0):
                base = probe(original["vertices"], original["triangles"], original["weights"], original["names"], original["parents"], original["restAnchors"], original["inverseBind"], joint, regions, degrees, axis)["moved"]
                trial = probe(candidate["vertices"], candidate["triangles"], candidate["weights"], candidate["names"], candidate["parents"], candidate["restAnchors"], candidate["inverseBind"], joint, regions, degrees, axis)["moved"]
                baseline = float(np.median(np.linalg.norm(base[mask] - original["vertices"][mask], axis=1)))
                measured = float(np.median(np.linalg.norm(trial[mask] - candidate["vertices"][mask], axis=1)))
                ratio = measured / baseline if baseline > 1e-8 else 0.0
                details[f"{joint}:{axis_name}:{degrees:g}"] = {"baselineMedian": baseline, "candidateMedian": measured, "retention": None if baseline <= 1e-8 else ratio,
                                                                 "passes70Pct": baseline > 1e-8 and ratio >= threshold}
    failures = [key for key, item in details.items() if not item["passes70Pct"]]
    return {"motionRetentionPassed": not failures, "retentionFailureCount": len(failures), "failures": failures, "probes": details}


def validate(original_path: str, candidate_path: str, output: str, weapon_regions=()) -> dict:
    with np.load(original_path, allow_pickle=False) as z:
        original = {key: z[key] for key in z.files}
    with np.load(candidate_path, allow_pickle=False) as z:
        candidate = {key: z[key] for key in z.files}
    report = validate_invariants(original, candidate, weapon_regions)
    report["probes"] = probe_report(candidate)
    report['baselineProbes'] = probe_report(original)
    report["quality"] = compare_probes(original, candidate)
    surface_failures=[key for key,value in report['probes'].items() if value['trianglesAbove2x'] > 0]
    report['quality']['surfacePassed']=not surface_failures
    report['quality']['surfaceFailures']=surface_failures
    report['quality']['qualityPassed']=report['quality']['motionRetentionPassed'] and not surface_failures
    report['quality']['surfacePolicy']='every triangle mean edge ratio within .5..2 across all 36 probes; reference edge denominator floored at 1e-8'
    Path(output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", required=True); parser.add_argument("--candidate", required=True); parser.add_argument("--output", required=True)
    parser.add_argument("--weapon-region", action="append", default=[])
    args = parser.parse_args(); report = validate(args.original, args.candidate, args.output, args.weapon_region)
    print(json.dumps({"output": str(Path(args.output).resolve()), "qualityPassed": report["quality"]["qualityPassed"],
                      "retentionFailureCount": report["quality"]["retentionFailureCount"],
                      "surfaceFailureCount": len(report["quality"]["surfaceFailures"])}, indent=2))
