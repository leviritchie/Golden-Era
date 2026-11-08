"""Prepare an unchanged visible mesh using an explicit source-to-mocap skin map."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

import run_shape_preserved as shared
from source_skin_initialization import initialize_source_weights
from structured_profiles import require_profile_pin


def _profile_hash(profile):
    fields = {"sourceJointMap": profile.get("sourceJointMap"),
                          "regionJoints": profile.get("regionJoints"),
                          "regionBones": profile.get("regionBones"),
                          "hubs": profile.get("hubs"), "chains": profile.get("chains"),
                          "rigidAttachments": profile.get("rigidAttachments", ())}
    if "geometryOwnership" in profile:
        fields["geometryOwnership"] = profile["geometryOwnership"]
    payload = json.dumps(fields,
                         sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _donor_hash(donor):
    digest = hashlib.sha256()
    for key in ("jointNames", "bindParents", "bindOffsets"):
        value = donor[key]
        digest.update(np.ascontiguousarray(value).tobytes() if hasattr(value, "tobytes")
                      else json.dumps(value, sort_keys=True, default=str).encode())
    return digest.hexdigest()


def prepare(asset, run_name):
    started = time.perf_counter()
    profile = shared.get_profile(asset)
    profile_pin = require_profile_pin(asset, profile)
    if profile.get("skinInitialization") != "source_joint_map":
        raise ValueError("this preparation requires explicit source_joint_map initialization")
    destination = shared.asset_dir(asset) / "preparation" / run_name
    shared._refuse_existing(destination)
    shared._refuse_existing(shared.prep_freeze_path(asset))
    target = shared.load_target_asset(profile)
    donor = shared.load_shape_donor(profile)
    profile_hash = _profile_hash(profile)
    donor_hash = _donor_hash(donor)
    names, parents = donor["jointNames"], donor["bindParents"]
    fit = shared.fit_deformation_bind(
        donor_names=names, donor_parents=parents, donor_rest=shared.donor_rest_joints(donor),
        target_names=target["names"], target_rest=target["restWorld"],
        target_vertices=target["vertices"], target_regions=target["vertexRegions"], profile=profile)
    rig = shared.rig_gate(names=names, parents=parents, fitted=fit["fittedPositions"],
                         offsets=fit["offsets"], profile=profile, helpers=fit["helpers"])
    initialization = initialize_source_weights(target["sourceDenseWeights"], target["names"], names,
                                              target["vertexRegions"], profile,
                                              source_vertex_ids=target.get("sourceVertexIds"))
    weights = initialization.pop("weights")
    shared.weight_gate(weights, len(target["vertices"]), len(names))
    bind = shared.bind_world_matrices(fit["offsets"], parents)
    inverse = shared.inverse_bind_matrices(bind)
    identity = shared.skin_dense(target["vertices"], weights, bind, inverse)
    preservation = shared.assert_visible_mesh_preserved(target, identity, target["triangles"], target["uvs"], target["albedo"])
    destination.mkdir(parents=True)
    skin_path = destination / "research_skin.npz"
    ownership_arrays = {key: target[key] for key in ("sourceVertexIds", "ownershipBoundaryPairs") if key in target}
    np.savez(skin_path, **ownership_arrays, vertices=target["vertices"], triangles=target["triangles"], uvs=target["uvs"],
             weights=weights, names=np.asarray(names), parents=parents, offsets=fit["offsets"],
             captureOffsets=donor["bindOffsets"], inverseBind=inverse,
             regions=np.asarray(target["vertexRegions"], dtype="U32"), albedo=target["albedo"])
    glb_path = destination / f"{asset}_mapped_skin.glb"
    rotations = np.repeat(np.eye(3)[None], len(names), axis=0)
    shared.write_skinned_glb(glb_path, names=names, parents=parents, rest_local_rotation=rotations,
        rest_local_translation=fit["offsets"], inverse_bind=inverse, vertices=target["vertices"],
        triangles=target["triangles"], uvs=target["uvs"], albedo=target["albedo"], weights=weights)
    working = shared.make_bind_skeleton(names=names, parents=parents, rest_world=fit["fittedPositions"],
        rest_local_rotation=rotations, rest_local_translation=fit["offsets"], inverse_bind=inverse,
        vertices=target["vertices"], triangles=target["triangles"], uvs=target["uvs"], weights=weights,
        albedo=target["albedo"], normals=shared.vertex_normals(target["vertices"], target["triangles"]))
    export = shared.export_reload_gate(glb_path, working=working, original_vertices=target["vertices"])
    camera = shared.freeze_shared_camera(np.concatenate([target["vertices"], fit["fittedPositions"]]),
                                         width=256, height=256, space="targetBindSpace")
    shared.write_bind_sheet(destination / "bind_sheet.png", cameras=camera,
        vertices=target["vertices"], triangles=target["triangles"], uvs=target["uvs"], albedo=target["albedo"],
        joints=fit["fittedPositions"], parents=parents, title=f"{asset} fixed mocap bind, original surface")
    report = {"assetId": asset, "proof": "generated-artifact", "visualAcceptance": "unreviewed_candidate",
              "initialization": initialization, "rig": rig, "preservation": preservation, "export": export,
              "profileHash": profile_hash, "donorHash": donor_hash,
              "prepareSeconds": time.perf_counter() - started, "visibleMeshUnchanged": True,
              "hiddenProxyUsed": False, "independentFingerMotion": False,
              "researchSkinSha256": shared.sha256_file(skin_path)}
    require_profile_pin(asset, profile_pin)
    if "geometryOwnership" in profile:
        from geometry_ownership import validate_prepared_ownership
        with np.load(skin_path, allow_pickle=False) as saved:
            validate_prepared_ownership(profile, saved)
        report["geometryOwnership"] = target["geometryOwnershipReport"]
    report.update(profile_pin)
    shared._write_json(destination / "prepare_report.json", report)
    shared._write_json(destination / "deformation_bind.json", fit)
    shared._write_json(shared.prep_freeze_path(asset), {
        **profile_pin, "assetId": asset, "runName": run_name, "preparationDir": str(destination), "researchSkin": str(skin_path),
        "glb": str(glb_path),
        "skinInitialization": "source_joint_map", "mappingHash": initialization["mappingHash"],
        "inputHashes": {"originalMesh": target["sourceSha256"], "profile": profile_hash, "donor": donor_hash,
                        "researchSkin": shared.sha256_file(skin_path)}})
    return report


def validate_and_pin_existing(asset: str):
    """Validate an existing mapped NPZ, then add current provenance pins only."""
    profile = shared.get_profile(asset)
    profile_pin = require_profile_pin(asset, profile)
    freeze_path = shared.prep_freeze_path(asset)
    freeze = json.loads(freeze_path.read_text())
    require_profile_pin(asset, freeze)
    report_path = Path(freeze["preparationDir"]) / "prepare_report.json"
    report = json.loads(report_path.read_text()) if report_path.is_file() else None
    if report is not None:
        require_profile_pin(asset, report)
    elif profile_pin:
        raise ValueError("registered preparation report is missing; regenerate preparation")
    if freeze.get("skinInitialization") != "source_joint_map":
        raise ValueError("existing preparation is not an explicit source-joint-map asset")
    target = shared.load_target_asset(profile)
    donor = shared.load_shape_donor(profile)
    fit = shared.fit_deformation_bind(
        donor_names=donor["jointNames"], donor_parents=donor["bindParents"], donor_rest=shared.donor_rest_joints(donor),
        target_names=target["names"], target_rest=target["restWorld"],
        target_vertices=target["vertices"], target_regions=target["vertexRegions"], profile=profile)
    skin_path = Path(freeze["researchSkin"])
    with np.load(skin_path, allow_pickle=False) as existing:
        if "geometryOwnership" in profile:
            from geometry_ownership import validate_prepared_ownership
            validate_prepared_ownership(profile, existing)
        if not np.array_equal(existing["vertices"], target["vertices"]) or not np.array_equal(existing["triangles"], target["triangles"]):
            raise ValueError("existing mapped skin surface differs from current target")
        if not np.array_equal(existing["uvs"], target["uvs"]):
            raise ValueError("existing mapped skin UVs differ from current target")
        if not np.array_equal(existing["albedo"], target["albedo"]) or not np.array_equal(existing["regions"], target["vertexRegions"]):
            raise ValueError("existing material or region ownership differs from profile")
        for key, value in (("offsets", fit["offsets"]), ("captureOffsets", donor["bindOffsets"]),
                           ("parents", donor["bindParents"]), ("names", np.asarray(donor["jointNames"]))):
            if not np.array_equal(existing[key], value):
                raise ValueError(f"existing mapped skeleton differs from current fit: {key}")
        inverse = shared.inverse_bind_matrices(shared.bind_world_matrices(fit["offsets"], donor["bindParents"]))
        if not np.array_equal(existing["inverseBind"], inverse):
            raise ValueError("existing mapped inverse bind differs from current fit")
        expected = initialize_source_weights(target["sourceDenseWeights"], target["names"], donor["jointNames"], target["vertexRegions"], profile,
                                             source_vertex_ids=target.get("sourceVertexIds"))["weights"]
        if not np.allclose(existing["weights"], expected, atol=1e-12, rtol=0):
            raise ValueError("existing mapped weights differ from current explicit initialization")
    profile_hash, donor_hash = _profile_hash(profile), _donor_hash(donor)
    require_profile_pin(asset, profile_pin)
    freeze.update(profile_pin)
    freeze.setdefault("inputHashes", {})
    freeze["inputHashes"].update({"profile": profile_hash, "donor": donor_hash, "researchSkin": shared.sha256_file(skin_path)})
    shared._write_json(freeze_path, freeze)
    if report is not None:
        report.update(profile_pin)
        report.update({"profileHash": profile_hash, "donorHash": donor_hash, "researchSkinSha256": shared.sha256_file(skin_path)})
        shared._write_json(report_path, report)
    return freeze


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--run-name", default="mapped_skin_v1")
    args = parser.parse_args()
    print(json.dumps(prepare(args.asset, args.run_name), default=shared._json_default))
