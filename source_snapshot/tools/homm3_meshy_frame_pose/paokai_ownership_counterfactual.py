#!/usr/bin/env python3
"""Measure Paokai ownership counterfactuals against the saved dragon replay.

This is a diagnostic-only experiment. It does not replace the candidate weights,
rewrite the pinned bind sidecar, or register a new delivery candidate. The
region-restricted variants answer one narrow question: does the current
wing/body collapse improve when each labeled surface is allowed to use only its
profile joints, or is the candidate geometry/registration already the limiter?
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = ROOT / "experiments/homm3_mocap_v2"
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

from run_linked_master_pipeline import (  # noqa: E402
    load_candidate_weights,
    load_fixed_motion,
    load_skin_bundle,
    pose_master,
    render_master_gif,
)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def region_allowed_mask(skin: dict[str, Any]) -> np.ndarray:
    name_to_index = {name: index for index, name in enumerate(skin["names"])}
    allowed = np.zeros((len(skin["vertices"]), len(skin["names"])), dtype=bool)
    for vertex, region_value in enumerate(skin["regions"]):
        region = str(region_value)
        joints = skin["regionJoints"].get(region)
        if not joints:
            raise ValueError(f"region {region!r} has no regionJoints entry")
        for joint in joints:
            try:
                allowed[vertex, name_to_index[joint]] = True
            except KeyError as exc:
                raise ValueError(f"region {region!r} references unknown joint {joint!r}") from exc
    return allowed


def make_variants(skin: dict[str, Any], current: np.ndarray) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    allowed = region_allowed_mask(skin)
    restricted_mass = np.sum(current * allowed, axis=1)
    restricted = current * allowed
    usable = restricted_mass > 1e-8
    restricted[usable] /= restricted_mass[usable, None]
    restricted[~usable] = current[~usable]

    rigid = np.zeros_like(current)
    allowed_indices = np.flatnonzero(allowed.any(axis=0))
    for vertex in range(len(current)):
        candidates = np.flatnonzero(allowed[vertex])
        if len(candidates) == 0:
            candidates = allowed_indices
        chosen = candidates[int(np.argmax(current[vertex, candidates]))]
        rigid[vertex, chosen] = 1.0

    metadata = {
        "restrictedVerticesWithRegionMass": int(np.count_nonzero(usable)),
        "restrictedFallbackVertices": int(np.count_nonzero(~usable)),
        "restrictedFallbackFraction": float(np.mean(~usable)),
        "regionCounts": {
            str(region): int(np.count_nonzero(np.asarray(skin["regions"], dtype=object) == region))
            for region in sorted(set(map(str, skin["regions"])))
        },
        "variantSemantics": {
            "current": "saved fitted candidate_weights.npz",
            "regionRestricted": "current weights masked to the labeled regionJoints, renormalized; diagnostic only",
            "regionRigid": "one dominant current-weight joint selected inside each labeled regionJoints set; diagnostic only",
        },
    }
    return {"current": current, "regionRestricted": restricted, "regionRigid": rigid}, metadata


def edge_metrics(vertices: np.ndarray, rest_vertices: np.ndarray, triangles: np.ndarray) -> dict[str, float]:
    edges = np.unique(
        np.sort(np.concatenate((triangles[:, :2], triangles[:, 1:], triangles[:, [0, 2]])), axis=1), axis=0
    )
    rest_lengths = np.linalg.norm(rest_vertices[edges[:, 0]] - rest_vertices[edges[:, 1]], axis=1)
    keep = rest_lengths > 1e-4 * np.linalg.norm(np.ptp(rest_vertices, axis=0))
    ratios = np.linalg.norm(vertices[:, edges[keep, 0]] - vertices[:, edges[keep, 1]], axis=-1) / rest_lengths[keep]
    values = ratios.reshape(-1)
    return {
        "p50": float(np.quantile(values, 0.50)),
        "p95": float(np.quantile(values, 0.95)),
        "p99": float(np.quantile(values, 0.99)),
        "worst": float(np.max(values)),
        "over2xFraction": float(np.mean(values > 2.0)),
        "over5xFraction": float(np.mean(values > 5.0)),
    }


def clip_rows(master: dict[str, Any], posed: np.ndarray, skin: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for segment in master["segments"]:
        if not bool(segment.get("exportsClip")):
            continue
        start, end = int(segment["globalStart"]), int(segment["globalEnd"])
        rows.append(
            {
                "clipKey": str(segment["clipKey"]),
                "contractSuffix": str(segment["contractSuffix"]),
                "globalStart": start,
                "globalEnd": end,
                "frameCount": end - start,
                "edge": edge_metrics(posed[start:end], skin["vertices"], skin["triangles"]),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--resolution", type=int, default=768)
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    output = args.out.resolve()
    if output.exists():
        raise FileExistsError(f"choose a fresh diagnostic output directory: {output}")
    master_path = run_dir / "linked_master/master_sequence/master_sequence.json"
    bind = run_dir / "linked_master/capture_bind/h3_paokai_linked_master_bind.glb"
    weights_path = run_dir / "linked_master/skin_fit/candidate_weights.npz"
    camera = run_dir / "linked_master/skin_fit/camera.json"
    capture = run_dir / "linked_master/capture/capture/raw_capture.npz"
    skin = load_skin_bundle(bind)
    current = load_candidate_weights(weights_path, skin)
    fixed = load_fixed_motion(skin, capture, reference_frame=0)
    master = json.loads(master_path.read_text(encoding="utf-8"))
    variants, variant_meta = make_variants(skin, current)

    output.mkdir(parents=True)
    reports: dict[str, Any] = {}
    for name, weights in variants.items():
        np.savez_compressed(output / f"{name}.npz", names=np.asarray(skin["names"]), weights=weights)
        posed = pose_master(skin, fixed, weights)
        reports[name] = {
            "weightSha256": hashlib.sha256(np.ascontiguousarray(weights).tobytes()).hexdigest(),
            "clips": clip_rows(master, posed, skin),
            "allFrames": edge_metrics(posed, skin["vertices"], skin["triangles"]),
        }
        (output / name).mkdir(parents=True, exist_ok=True)
        render_master_gif(
            master=master,
            skin=skin,
            posed=posed,
            camera_path=camera,
            output_dir=output / name,
            resolution=int(args.resolution),
        )

    report = {
        "schema": "homm3.paokai-ownership-counterfactual.v1",
        "proof": "generated-artifact diagnostic only; no candidate promotion, deployment, or runtime proof",
        "unit": "h3_paokai",
        "runDir": str(run_dir).replace("\\", "/"),
        "bind": str(bind).replace("\\", "/"),
        "capture": str(capture).replace("\\", "/"),
        "masterSequence": str(master_path).replace("\\", "/"),
        "resolution": int(args.resolution),
        "variantMetadata": variant_meta,
        "variants": reports,
        "interpretation": {
            "acceptance": "none; this is a counterfactual ownership diagnostic",
            "nextDecision": "compare regionRestricted and regionRigid high-resolution attack/death panels against current before attempting a production bind change",
        },
    }
    write_json(output / "counterfactual_report.json", report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
