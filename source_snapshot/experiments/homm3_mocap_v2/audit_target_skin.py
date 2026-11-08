"""Profile-independent, named joint/skin evidence for onboarding a target mesh.

Influence slots are scattered through vertex_joints before any per-bone statistic.
This report supplies evidence, not an automatic anatomical role assignment.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from glb_skeleton import load_bind_skeleton
from pin import sha256_file
from target_asset import dense_weights


def summarize(skeleton):
    names = list(skeleton.names)
    parents = np.asarray(skeleton.parents)
    if not np.issubdtype(parents.dtype, np.integer):
        raise ValueError("joint parents must be integer indices")
    vertices = np.asarray(skeleton.vertices, dtype=np.float64)
    rest = np.asarray(skeleton.rest_world, dtype=np.float64)
    if not names or len(set(names)) != len(names) or parents.shape != (len(names),):
        raise ValueError("joint names/parents are ambiguous")
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not len(vertices) or not np.isfinite(vertices).all():
        raise ValueError("vertices must be finite nonempty Vx3")
    if rest.shape != (len(names), 3) or not np.isfinite(rest).all():
        raise ValueError("joint rest positions must be finite Jx3")
    triangles = np.asarray(skeleton.triangles)
    if (triangles.ndim != 2 or triangles.shape[1] != 3 or
            not np.issubdtype(triangles.dtype, np.integer) or
            np.any(triangles < 0) or np.any(triangles >= len(vertices))):
        raise ValueError("triangles must be integer Tx3 vertex indices")
    slots = np.asarray(skeleton.vertex_joints)
    raw_weights = np.asarray(skeleton.vertex_weights)
    if slots.ndim != 2 or slots.shape != raw_weights.shape or len(slots) != len(vertices):
        raise ValueError("influence rows must match vertex rows")
    if not np.issubdtype(slots.dtype, np.integer) or np.any(slots < 0) or np.any(slots >= len(names)):
        raise ValueError("influence joint index outside skeleton")
    if not np.isfinite(raw_weights).all() or np.any(raw_weights < 0):
        raise ValueError("invalid raw influence weights")
    weights = dense_weights(skeleton)
    if weights.shape != (len(vertices), len(names)):
        raise ValueError("dense skin must have one column per named joint")
    if not np.isfinite(weights).all() or np.any(weights < 0) or not np.allclose(weights.sum(1), 1):
        raise ValueError("invalid or unsupported vertex skin rows")
    rows = []
    dominant = weights.argmax(1)
    for index, name in enumerate(names):
        parent = int(parents[index])
        if parent < -1 or parent >= len(names) or parent == index:
            raise ValueError("invalid joint parent index")
        weight = weights[:, index]
        mass = float(weight.sum())
        selected = vertices[weight > .1]
        rows.append({"index": index, "name": name, "parentIndex": parent,
                     "parent": names[parent] if parent >= 0 else None,
                     "children": [names[i] for i in np.flatnonzero(parents == index)],
                     "restWorld": rest[index].tolist(), "weightMass": mass,
                     "nonzeroVertexCount": int((weight > 1e-8).sum()),
                     "dominantVertexCount": int((dominant == index).sum()),
                     "overPointOneVertexCount": len(selected),
                     "weightedCentroidMeshLocal": ((vertices * weight[:, None]).sum(0) / mass).tolist() if mass > 0 else None,
                     "overPointOneBoundsMeshLocal": [selected.min(0).tolist(), selected.max(0).tolist()] if len(selected) else None})
    return {"proof": "decoded_mesh_evidence_not_anatomical_acceptance",
            "coordinateSpaces": {"restWorld": "glTF node world",
                                 "weightedCentroidMeshLocal": "mesh POSITION accessor; no node transform applied",
                                 "overPointOneBoundsMeshLocal": "mesh POSITION accessor; no node transform applied"},
            "jointCount": len(names), "vertexCount": len(vertices),
            "triangleCount": len(skeleton.triangles),
            "influenceSlotsPerVertex": int(np.asarray(skeleton.vertex_weights).shape[1]),
            "weightedJointCount": sum(row["weightMass"] > 1e-8 for row in rows),
            "joints": rows}


def audit(mesh: Path, output: Path):
    if output.exists():
        raise FileExistsError(output)
    mesh = mesh.resolve()
    digest = sha256_file(mesh)
    report = summarize(load_bind_skeleton(mesh))
    if sha256_file(mesh) != digest:
        raise ValueError("mesh changed during audit")
    report.update({"mesh": str(mesh), "meshSha256": digest,
                   "implementationSha256": sha256_file(Path(__file__)),
                   "decoderSha256": sha256_file(Path(__file__).with_name("glb_skeleton.py")),
                   "denseWeightsImplementationSha256": sha256_file(Path(__file__).with_name("target_asset.py"))})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.mesh, args.output)
    print(json.dumps({key: report[key] for key in
                     ("meshSha256", "jointCount", "vertexCount", "triangleCount", "weightedJointCount", "influenceSlotsPerVertex")}))
