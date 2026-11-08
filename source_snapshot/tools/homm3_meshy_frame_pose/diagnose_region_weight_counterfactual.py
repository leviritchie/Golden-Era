"""Build diagnostic region-constrained weight counterfactuals for a biped bind.

This tool never edits the source bind or candidate weights. It emits fresh GLBs
whose only change is the diagnostic weight matrix, so the existing high-resolution
replay renderer can compare the current, region-restricted, and region-rigid lanes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = ROOT / "experiments/homm3_mocap_v2"
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from eagle_glb import write_skinned_glb  # noqa: E402
from run_move_bind_t2_mocap_skin_fit import load_skin_bundle  # noqa: E402


def region_variants(skin: dict[str, object], current: np.ndarray) -> dict[str, np.ndarray]:
    names = [str(name) for name in skin["names"]]
    name_to_index = {name: index for index, name in enumerate(names)}
    restricted = np.zeros_like(current)
    rigid = np.zeros_like(current)
    regions = [str(region) for region in skin["regions"]]
    region_joints = skin["regionJoints"]
    for vertex, region in enumerate(regions):
        joints = [str(joint) for joint in region_joints[region]]
        indices = [name_to_index[joint] for joint in joints]
        restricted[vertex, indices] = current[vertex, indices]
        total = float(restricted[vertex].sum())
        if total > 1e-8:
            restricted[vertex] /= total
        else:
            restricted[vertex] = current[vertex]
        chosen = indices[int(np.argmax(current[vertex, indices]))]
        rigid[vertex, chosen] = 1.0
    return {"current": current, "region_restricted": restricted, "region_rigid": rigid}


def write_variant(path: Path, skin: dict[str, object], weights: np.ndarray) -> None:
    write_skinned_glb(
        path,
        names=list(skin["names"]),
        parents=skin["parents"],
        rest_local_rotation=skin["restLocalRotation"],
        rest_local_translation=skin["offsets"],
        inverse_bind=skin["inverseBind"],
        vertices=skin["vertices"],
        triangles=skin["triangles"],
        uvs=skin["uvs"],
        albedo=skin["albedo"],
        weights=weights,
    )


def write_regions_sidecar(source_bind: Path, variant_bind: Path, label: str) -> None:
    """Retain the region contract while rebinding the sidecar to the new GLB hash."""
    source_sidecar = source_bind.with_name(source_bind.stem + "_regions.json")
    if not source_sidecar.is_file():
        raise FileNotFoundError(f"source bind region sidecar is missing: {source_sidecar}")
    sidecar = json.loads(source_sidecar.read_text(encoding="utf-8"))
    source_digest = hashlib.sha256(source_bind.read_bytes()).hexdigest()
    if sidecar.get("bindSha256") != source_digest:
        raise ValueError("source bind region sidecar hash does not match the source GLB")
    sidecar["bindGlb"] = str(variant_bind).replace("\\", "/")
    sidecar["bindSha256"] = hashlib.sha256(variant_bind.read_bytes()).hexdigest()
    sidecar["counterfactualVariant"] = label
    variant_sidecar = variant_bind.with_name(variant_bind.stem + "_regions.json")
    variant_sidecar.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    output = args.out.resolve()
    if output.exists():
        raise FileExistsError(f"choose a fresh diagnostic output directory: {output}")
    bind = run_dir / "capture_bind" / f"{args.unit}_linked_master_bind.glb"
    weights_path = run_dir / "skin_fit" / "candidate_weights.npz"
    skin = load_skin_bundle(bind)
    payload = np.load(weights_path, allow_pickle=True)
    names = [str(name) for name in payload["names"].tolist()]
    if names != [str(name) for name in skin["names"]]:
        raise ValueError("candidate weight names do not match the bind skeleton")
    current = np.asarray(payload["weights"], dtype=np.float64)
    variants = region_variants(skin, current)
    output.mkdir(parents=True)
    report: dict[str, object] = {
        "schema": "homm3.region-weight-counterfactual.v1",
        "proof": "generated-artifact diagnostic only; no candidate promotion or runtime proof",
        "unit": args.unit,
        "bind": str(bind).replace("\\", "/"),
        "weights": str(weights_path).replace("\\", "/"),
        "regionRestrictedMeaning": "current weights masked to each vertex region's profile joints and renormalized",
        "regionRigidMeaning": "one dominant current-weight joint selected inside each vertex region's profile joints",
        "variants": {},
    }
    for label, weights in variants.items():
        variant_glb = output / f"{label}.glb"
        write_variant(variant_glb, skin, weights)
        write_regions_sidecar(bind, variant_glb, label)
        np.savez_compressed(output / f"{label}.npz", names=np.asarray(names), weights=weights)
        allowed_mass = []
        for vertex, region in enumerate(str(value) for value in skin["regions"]):
            indices = [names.index(str(joint)) for joint in skin["regionJoints"][region]]
            allowed_mass.append(float(weights[vertex, indices].sum()))
        report["variants"][label] = {
            "glb": str(variant_glb).replace("\\", "/"),
            "weightSha256": hashlib.sha256(np.ascontiguousarray(weights).tobytes()).hexdigest(),
            "minRegionMass": float(min(allowed_mass)),
            "meanRegionMass": float(np.mean(allowed_mass)),
        }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
