"""Prepare a mounted unit skin from an authored mesh, labels, and composite rig."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

try:
    from .glb_skeleton import load_bind_skeleton
except ImportError:  # direct CLI execution from the experiment directory
    from glb_skeleton import load_bind_skeleton
try:
    from .donor_eagle import inverse_bind_matrices, skin_dense
except ImportError:
    from donor_eagle import inverse_bind_matrices, skin_dense


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _segment_distance(points: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    axis = b - a
    length2 = float(axis @ axis)
    if length2 <= 1e-12:
        return np.linalg.norm(points - a, axis=1)
    t = np.clip(((points - a) @ axis) / length2, 0.0, 1.0)
    return np.linalg.norm(points - (a + t[:, None] * axis), axis=1)


def _weights(vertices, regions, names, parents, rest, allowed, rigid):
    if not names or len(parents) != len(names) or len(rest) != len(names):
        raise ValueError("composite joint names, parents, and rest anchors have incompatible dimensions")
    index = {str(name): i for i, name in enumerate(names)}
    if len(index) != len(names):
        raise ValueError("composite joint names must be unique")
    if not np.isfinite(rest).all() or any(int(p) >= i for i, p in enumerate(parents) if int(p) >= 0):
        raise ValueError("composite parents must be finite, ordered, and acyclic")
    if int(parents[0]) != -1 or sum(int(p) == -1 for p in parents) != 1:
        raise ValueError("composite rig must have exactly one root at joint index 0")
    result = np.zeros((len(vertices), len(names)), dtype=np.float64)
    for region in np.unique(regions):
        region = str(region)
        rows = np.flatnonzero(np.asarray(regions) == region)
        joints = rigid.get(region) if region in rigid else allowed.get(region)
        if not joints:
            raise ValueError(f"vertex region {region!r} has no authored joint ownership")
        joints = [str(j) for j in joints]
        if len(joints) > 8:
            raise ValueError(f"region {region!r} allows more than 8 joints")
        if any(j not in index for j in joints):
            raise ValueError(f"region {region!r} references an absent joint")
        if region in rigid:
            if len(joints) != 1:
                raise ValueError("rigid ownership must name exactly one joint")
            result[rows, index[joints[0]]] = 1.0
            continue
        distances = []
        for joint in joints:
            i = index[joint]
            children = [j for j in np.flatnonzero(np.asarray(parents) == i) if str(names[j]) in joints]
            endpoints = rest[children] if len(children) else rest[i:i + 1]
            distances.append(np.maximum(np.min([_segment_distance(vertices[rows], rest[i], endpoint)
                                                for endpoint in endpoints], axis=0), 1e-4))
        inverse = 1.0 / np.asarray(distances).T ** 4
        result[np.ix_(rows, [index[j] for j in joints])] = inverse / inverse.sum(axis=1, keepdims=True)
    return result


def prepare(manifest_path: str, output_dir: str, *, publish: bool = True) -> dict:
    manifest_file = Path(manifest_path)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    from mounted_asset_identity import validate_profile_identity
    validate_profile_identity({'assetId': manifest['assetId'], 'mesh': manifest['originalMesh'],
                               'expectedMeshSha256': manifest['expectedMeshSha256']})
    if not manifest.get("authorProfile") or not manifest.get("authorProfileHash"):
        raise ValueError("manifest must pin a non-empty authorProfile and authorProfileHash")
    if _sha(Path(manifest["authorProfile"])) != manifest["authorProfileHash"]:
        raise ValueError("authored profile changed")
    mesh_file = Path(manifest["originalMesh"])
    if not mesh_file.is_file():
        raise ValueError("originalMesh must be an existing file")
    if _sha(mesh_file) != manifest["expectedMeshSha256"]:
        raise ValueError("original mesh changed")
    destination = Path(output_dir).resolve()
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite preparation directory: {destination}")
    from run_shape_preserved import prep_freeze_path
    central = prep_freeze_path(manifest["assetId"])
    # Check publication state before any expensive mesh work or candidate files.
    if publish and central.exists():
        raise FileExistsError(f"preparation is already frozen: {central}")
    skeleton = load_bind_skeleton(mesh_file)
    if skeleton.vertices is None or skeleton.triangles is None or skeleton.uvs is None or skeleton.albedo is None:
        raise ValueError("original mesh must contain vertices, triangles, UVs, and albedo")
    vertices = np.asarray(skeleton.vertices, dtype=np.float64)
    triangles = np.asarray(skeleton.triangles, dtype=np.int64)
    uvs = np.asarray(skeleton.uvs, dtype=np.float64)
    names = [str(x) for x in manifest["jointNames"]]
    parents = np.asarray(manifest["parents"], dtype=np.int64)
    rest = np.asarray(manifest["restAnchors"], dtype=np.float64)
    regions = np.asarray(manifest["vertexRegions"], dtype="U64")
    if len(regions) != len(vertices):
        raise ValueError("vertexRegions must label every original vertex")
    allowed = {str(k): list(v) for k, v in manifest["allowedRegionJoints"].items()}
    rigid = {str(k): [str(v)] for k, v in manifest.get("rigidAttachments", {}).items()}
    weights = _weights(vertices, regions, names, parents, rest, allowed, rigid)
    if not np.allclose(weights.sum(axis=1), 1.0, atol=1e-10):
        raise ValueError("generated weights are not normalized")
    destination.mkdir(parents=True)
    skin = destination / "research_skin.npz"
    offsets = rest.copy()
    for i, parent in enumerate(parents):
        if int(parent) >= 0:
            offsets[i] = rest[i] - rest[int(parent)]
    inverse_bind = np.repeat(np.eye(4, dtype=np.float64)[None], len(names), axis=0)
    bind = np.repeat(np.eye(4, dtype=np.float64)[None], len(names), axis=0)
    bind[:, :3, 3] = rest
    inverse_bind = inverse_bind_matrices(bind)
    identity = skin_dense(vertices, weights, bind, inverse_bind)
    rest_error = float(np.max(np.abs(identity - vertices))) if len(vertices) else 0.0
    if rest_error > 1e-8:
        raise ValueError(f"rest identity skin parity failed: max error {rest_error}")
    np.savez(skin, vertices=vertices, triangles=triangles, uvs=uvs, albedo=np.asarray(skeleton.albedo), weights=weights,
             names=np.asarray(names), parents=parents, restAnchors=rest, restWorld=rest,
             offsets=offsets, captureOffsets=offsets, inverseBind=inverse_bind, regions=regions)
    profile = {"policy": "mounted_capsule_owned", "authorProfile": manifest.get("authorProfile"),
               "source": str(mesh_file).replace("\\", "/"), "sourceSha256": _sha(mesh_file),
               "authorProfileHash": manifest.get("authorProfileHash")}
    frozen = {"schema": 1, "policy": "mounted_capsule_owned", "skinInitialization": "mounted_capsule_owned",
              "preparationDir": str(destination), "researchSkin": str(skin), "authoringManifest": str(manifest_file.resolve()),
              "inputHashes": {"originalMesh": profile["sourceSha256"], "manifest": _sha(manifest_file),
                              "researchSkin": _sha(skin)}, "jointCount": len(names),
              "visibleMeshUnchanged": bool(np.array_equal(vertices, np.asarray(skeleton.vertices))),
              "topologyPreserved": True, "uvsPreserved": True, "restIdentityParity": rest_error <= 1e-8,
              "restIdentityMaxError": rest_error,
              "profile": profile}
    (destination / "preparation_frozen.json").write_text(json.dumps(frozen, indent=2) + "\n", encoding="utf-8")
    if publish:
        central.parent.mkdir(parents=True, exist_ok=True)
        central.write_text(json.dumps(frozen, indent=2) + "\n", encoding="utf-8")
    return frozen


def _validate_frozen(candidate_path: Path, frozen: dict) -> None:
    from mounted_asset_identity import validate_profile_identity
    profile = frozen.get("profile")
    if not isinstance(profile, dict):
        raise ValueError("candidate is missing profile provenance")
    manifest_path = Path(str(frozen.get("authoringManifest", "")))
    if not manifest_path.is_file():
        raise ValueError("candidate authoring manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_profile_identity({"assetId": manifest.get("assetId"),
                              "mesh": profile.get("source"),
                              "expectedMeshSha256": profile.get("sourceSha256")})
    author = Path(str(profile.get("authorProfile", "")))
    if not author.is_file() or _sha(author) != profile.get("authorProfileHash"):
        raise ValueError("candidate author profile hash changed")
    hashes = frozen.get("inputHashes")
    if not isinstance(hashes, dict):
        raise ValueError("candidate is missing input hashes")
    mesh = Path(str(profile.get("source", "")))
    manifest = manifest_path
    skin = Path(str(frozen.get("researchSkin", "")))
    for label, path, expected in (("originalMesh", mesh, hashes.get("originalMesh")),
                                  ("manifest", manifest, hashes.get("manifest")),
                                  ("researchSkin", skin, hashes.get("researchSkin"))):
        if not path.is_file() or not expected or _sha(path) != expected:
            raise ValueError(f"candidate {label} hash changed or file is missing")
    if frozen.get("restIdentityParity") is not True or frozen.get("topologyPreserved") is not True:
        raise ValueError("candidate failed preparation identity gates")


def activate_candidate(candidate_freeze_path: str | Path, expected_previous_sha256: str | None = None) -> dict:
    candidate = Path(candidate_freeze_path).resolve()
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    frozen = json.loads(candidate.read_text(encoding="utf-8"))
    _validate_frozen(candidate, frozen)
    from run_shape_preserved import prep_freeze_path
    manifest = json.loads(Path(str(frozen["authoringManifest"])).read_text(encoding="utf-8"))
    central = prep_freeze_path(manifest["assetId"])
    current = _sha(central) if central.exists() else None
    if current != expected_previous_sha256:
        raise ValueError("central preparation changed; compare-and-swap refused")
    archive = candidate.parent / "previous_central_freeze.json"
    if archive.exists():
        raise FileExistsError(archive)
    if central.exists():
        archive.write_bytes(central.read_bytes())
    central.parent.mkdir(parents=True, exist_ok=True)
    temporary = central.with_name(central.name + f".tmp-{os.getpid()}")
    if temporary.exists():
        raise FileExistsError(temporary)
    temporary.write_bytes(candidate.read_bytes())
    os.replace(temporary, central)
    return {"central": str(central), "previous": str(archive) if archive.exists() else None,
            "candidateSha256": _sha(candidate), "previousSha256": current}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest")
    parser.add_argument("--output")
    parser.add_argument("--candidate-only", action="store_true")
    parser.add_argument("--activate-candidate", type=Path)
    parser.add_argument("--expected-previous-sha256")
    args = parser.parse_args()
    if args.activate_candidate:
        print(json.dumps(activate_candidate(args.activate_candidate, args.expected_previous_sha256), indent=2))
    else:
        if not args.manifest or not args.output:
            parser.error("--manifest and --output are required unless --activate-candidate is used")
        print(json.dumps(prepare(args.manifest, args.output, publish=not args.candidate_only), indent=2))
