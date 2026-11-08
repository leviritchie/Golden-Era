#!/usr/bin/env python3
"""Fail-closed validator for camera-free SmartRig modifier candidates."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(report_path: Path) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    required = ("asset", "geometryMode", "skinningPolicy", "llmInLoop", "exportParity", "inputs", "clipKeys",
                "clips", "exportValidation", "motionRetention", "surface", "weightDelta")
    missing = [key for key in required if key not in report]
    if missing:
        raise ValueError(f"modifier report is missing required fields: {missing}")
    if report["geometryMode"] not in {"source_rest_immutable", "source_rest_autonomous_seam_split"}:
        raise ValueError("modifier candidate has an unknown geometry mode")
    topology = report.get("meshTopologyRepair") or {}
    if topology.get("schema") != "castle-smartrig-seam-split-v1":
        raise ValueError("modifier candidate is missing autonomous topology repair metadata")
    if topology.get("accepted") is not (topology.get("cutCount", 0) > 0):
        raise ValueError("topology repair acceptance does not match recorded cuts")
    if report["geometryMode"] == "source_rest_immutable" and topology.get("cutCount", 0) != 0:
        raise ValueError("immutable geometry mode cannot report seam cuts")
    if report["geometryMode"] == "source_rest_autonomous_seam_split" and topology.get("cutCount", 0) < 1:
        raise ValueError("seam-split geometry mode requires a recorded seam cut")
    if report["llmInLoop"] is not False:
        raise ValueError("modifier candidate must declare llmInLoop=false")
    if report["skinningPolicy"] != "dual_quaternion_sequence_solve":
        raise ValueError("unexpected SmartRig modifier skinning policy")
    parity = report.get("exportParity") or {}
    if parity.get("solver") != "dual_quaternion" or parity.get("serialized") != "gltf_linear_blend" or parity.get("status") != "not_equivalent":
        raise ValueError("modifier must explicitly classify DQ solve versus glTF export skinning")
    clip_keys = [str(value) for value in report["clipKeys"]]
    if len(set(clip_keys)) != len(clip_keys) or set(clip_keys) != set(report["clips"]):
        raise ValueError("clip inventory is duplicated or disagrees with clip records")
    exports = report["exportValidation"]
    if set(exports) != set(clip_keys) or not all(row.get("ok") is True for row in exports.values()):
        raise ValueError("serialized candidate readback did not pass for every clip")
    inputs = report["inputs"]
    for key in ("corpus", "calibration", "researchSkinSha256"):
        if key not in inputs:
            raise ValueError(f"modifier inputs missing {key}")
    for key in ("corpus", "calibration", "researchSkin"):
        path = Path(inputs[key])
        if not path.is_file():
            raise ValueError(f"modifier input is missing: {path}")
    for path_key, hash_key in (("corpus", "corpusSha256"), ("calibration", "calibrationSha256"), ("researchSkin", "researchSkinSha256")):
        if hash_key not in inputs or _sha256(Path(inputs[path_key])) != str(inputs[hash_key]).lower():
            raise ValueError(f"modifier input hash changed: {inputs[path_key]}")
    weights_path = report_path.parent / "candidate_weights.npz"
    if not weights_path.is_file():
        raise ValueError("candidate_weights.npz is missing")
    import numpy as np
    with np.load(weights_path, allow_pickle=False) as candidate:
        weights = np.asarray(candidate["weights"], dtype=np.float64)
        if weights.ndim != 2 or not np.isfinite(weights).all() or np.any(weights < -1e-7):
            raise ValueError("candidate weights are malformed")
        if not np.allclose(weights.sum(axis=1), 1.0, atol=2e-5, rtol=0.0):
            raise ValueError("candidate weights are not normalized")
        names = [str(value) for value in candidate["names"].tolist()]
        parents = np.asarray(candidate["parents"], dtype=np.int64)
        vertices = np.asarray(candidate["vertices"], dtype=np.float64)
        offsets = np.asarray(candidate["offsets"], dtype=np.float64)
        inverse_bind = np.asarray(candidate["inverseBind"], dtype=np.float64)
        triangles = np.asarray(candidate["triangles"], dtype=np.int64)
        uvs = np.asarray(candidate["uvs"], dtype=np.float64)
        if len(names) != weights.shape[1] or parents.shape != (len(names),) or vertices.ndim != 2 or vertices.shape[1] != 3:
            raise ValueError("candidate bind arrays are malformed")
        if triangles.ndim != 2 or triangles.shape[1] != 3 or np.any(triangles < 0) or np.any(triangles >= len(vertices)):
            raise ValueError("candidate topology is malformed")
        if uvs.shape != (len(vertices), 2) or not np.isfinite(uvs).all():
            raise ValueError("candidate UV topology is malformed")
    for key, row in report["clips"].items():
        for field in ("candidateGlb", "candidateGlbSha256", "frameCount"):
            if field not in row:
                raise ValueError(f"clip record {key} is missing {field}")
        path = Path(row["candidateGlb"])
        if not path.is_file():
            raise ValueError(f"candidate GLB is missing: {path}")
        if row.get("candidateGlbSha256") != _sha256(path):
            raise ValueError(f"candidate GLB hash changed: {path}")
        export = exports[key]
        if export.get("ok") is not True or export.get("bindOk") is not True or export.get("animationOk") is not True:
            raise ValueError(f"candidate GLB readback flags are not passing: {path}")
        from glb_skeleton import load_bind_skeleton
        loaded = load_bind_skeleton(path)
        if set(map(str, loaded.names)) != set(names):
            raise ValueError(f"candidate GLB joint inventory changed: {path}")
        expected_index = {name: index for index, name in enumerate(names)}
        loaded_index = {str(name): index for index, name in enumerate(loaded.names)}
        if len(loaded_index) != len(names):
            raise ValueError(f"candidate GLB contains duplicate joint names: {path}")
        loaded_parent_by_name = {
            name: (None if int(loaded.parents[index]) < 0 else str(loaded.names[int(loaded.parents[index])]))
            for name, index in loaded_index.items()
        }
        expected_parent_by_name = {
            name: (None if int(parents[index]) < 0 else names[int(parents[index])])
            for name, index in expected_index.items()
        }
        if loaded_parent_by_name != expected_parent_by_name:
            raise ValueError(f"candidate GLB hierarchy changed: {path}")
        loaded_weights = np.zeros_like(weights)
        joints = np.asarray(loaded.vertex_joints, dtype=np.int64)
        values = np.asarray(loaded.vertex_weights, dtype=np.float64)
        for slot in range(joints.shape[1]):
            for vertex_index, joint_index in enumerate(joints[:, slot]):
                loaded_weights[vertex_index, expected_index[str(loaded.names[int(joint_index)])]] += values[vertex_index, slot]
        if not np.allclose(np.asarray(loaded.vertices), vertices, atol=2e-5, rtol=0.0):
            raise ValueError(f"candidate GLB vertices changed: {path}")
        if loaded.triangles is None or not np.array_equal(np.asarray(loaded.triangles, dtype=np.int64), triangles):
            raise ValueError(f"candidate GLB topology changed: {path}")
        if loaded.uvs is None or not np.allclose(np.asarray(loaded.uvs), uvs, atol=2e-5, rtol=0.0):
            raise ValueError(f"candidate GLB UV topology changed: {path}")
        loaded_inverse = np.asarray(loaded.inverse_bind, dtype=np.float64)
        expected_inverse = np.zeros_like(inverse_bind)
        for name, index in loaded_index.items():
            expected_inverse[index] = inverse_bind[expected_index[name]]
        if not np.allclose(loaded_inverse, expected_inverse, atol=2e-5, rtol=0.0):
            raise ValueError(f"candidate GLB inverse bind changed: {path}")
        if not np.allclose(loaded_weights, weights, atol=2e-5, rtol=0.0):
            raise ValueError(f"candidate GLB weights changed: {path}")
    return {"ok": True, "asset": report["asset"], "clipCount": len(clip_keys),
            "candidateWeights": str(weights_path), "reportSha256": _sha256(report_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.report.resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
