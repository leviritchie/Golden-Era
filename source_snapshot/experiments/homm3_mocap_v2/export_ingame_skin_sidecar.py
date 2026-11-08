"""Emit lossless Unity skin-weight sidecars for raw current-mocap GLBs.

The local glTFast delivery lane currently consumes JOINTS_0/WEIGHTS_0 only.
This sidecar preserves every serialized influence tuple (the raw exports use
eight slots) so the Unity adapter can apply all weights after import without
re-fitting or silently truncating the skin.
"""
from __future__ import annotations

import argparse
import json
import hashlib
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glb_skeleton import load_bind_skeleton
from delivery_ownership import ownership_context


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


SCHEMA = "stronghold-current-mocap-skin-sidecar-v1"


def _sidecar_from_glb(glb: Path, source: dict[str, Any]) -> dict[str, Any]:
    skeleton = load_bind_skeleton(glb)
    joints = np.asarray(skeleton.vertex_joints)
    weights = np.asarray(skeleton.vertex_weights, dtype=np.float64)
    if joints.ndim != 2 or weights.shape != joints.shape or joints.shape[1] != 8:
        raise ValueError(f"raw GLB must preserve exactly eight skin slots: {glb}")
    if not np.isfinite(weights).all() or np.any(weights < 0):
        raise ValueError(f"raw GLB contains invalid skin weights: {glb}")
    if not np.allclose(weights.sum(axis=1), 1.0, atol=1e-5, rtol=0):
        raise ValueError(f"raw GLB weights are not normalized: {glb}")
    if skeleton.vertices is None or skeleton.uvs is None or skeleton.triangles is None:
        raise ValueError(f"raw GLB lacks required mesh identity arrays: {glb}")
    if len(skeleton.vertices) != len(skeleton.uvs):
        raise ValueError(f"raw GLB vertex/UV order differs: {glb}")
    return {
        "schema": SCHEMA,
        "sourceGlb": str(glb.resolve()),
        "sourceGlbSha256": sha256_file(glb),
        "sourceReportSha256": source["sourceReportSha256"],
        "assetId": source["assetId"],
        "gameSid": source["gameSid"],
        "jointNames": list(skeleton.names),
        # Keep these flat: Unity JsonUtility does not deserialize jagged arrays.
        "vertices": np.asarray(skeleton.vertices, dtype=np.float32).reshape(-1).tolist(),
        "uvs": np.asarray(skeleton.uvs, dtype=np.float32).reshape(-1).tolist(),
        "triangles": np.asarray(skeleton.triangles, dtype=np.int32).reshape(-1).tolist(),
        "jointIndices": joints.astype(np.int32).reshape(-1).tolist(),
        "weights": weights.astype(np.float32).reshape(-1).tolist(),
        "vertexCount": int(len(joints)),
        "influenceSlots": 8,
        "disposition": "user_requested_ingame_test",
    }


def _ownership_reference(source: dict[str, Any]) -> dict[str, Any] | None:
    context = ownership_context(source)
    return None if context is None else context['reference']


def export_sidecars(raw_manifest: Path, output: Path) -> dict[str, Any]:
    """Write one idle-frame sidecar per exported unit into a fresh directory."""
    raw_manifest = Path(raw_manifest).resolve()
    report = json.loads(raw_manifest.read_text(encoding="utf-8"))
    if report.get("schema") != "stronghold-current-mocap-raw-export-v1":
        raise ValueError("unsupported raw export manifest schema")
    if report.get("accepted") is not False or report.get("disposition") != "user_requested_ingame_test":
        raise ValueError("skin sidecars require an unaccepted test-only export")
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    entries = []
    for unit in report.get("units", []):
        groups = unit.get("groups") or []
        if not groups:
            raise ValueError(f"unit has no raw groups: {unit.get('gameSid')}")
        chosen = next((g for g in groups if g.get("groupId") == "g02_idle"), groups[0])
        glb = raw_manifest.parent / chosen["glb"]
        sidecar = _sidecar_from_glb(glb, unit)
        ownership = _ownership_reference(unit)
        if ownership is not None:
            sidecar["preparedOwnership"] = ownership
        sidecar["rawManifestSha256"] = report.get("rawManifestSha256") or sha256_file(raw_manifest)
        sidecar["rawManifest"] = str(raw_manifest)
        path = output / unit["gameSid"] / "skin_weights.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(sidecar, separators=(",", ":")) + "\n", encoding="utf-8")
        entries.append({"gameSid": unit["gameSid"], "assetId": unit["assetId"],
                        "groupId": chosen["groupId"], "path": path.relative_to(output).as_posix(),
                        "sourceGlbSha256": sidecar["sourceGlbSha256"],
                        "sourceReportSha256": unit["sourceReportSha256"],
                        "vertexCount": sidecar["vertexCount"], "influenceSlots": 8})
    result = {"schema": "stronghold-current-mocap-skin-sidecar-manifest-v1",
              "rawManifest": str(raw_manifest), "rawManifestSha256": sha256_file(raw_manifest),
              "disposition": "user_requested_ingame_test", "accepted": False,
              "sidecars": entries}
    (output / "manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_sidecars(args.raw_manifest, args.output), indent=2))
