"""Opt-in paired-site bind candidate; no source profiles or assets are changed."""
import copy

import numpy as np

import run_shape_preserved as shared
from prepare_mapped_skin_asset import _donor_hash, _profile_hash


def build_paired_bind(profile):
    candidate = copy.deepcopy(profile)
    for chain in candidate["chains"]:
        if chain["kind"] == "polyline":
            chain["kind"] = "paired_landmarks"
    target = shared.load_target_asset(candidate)
    donor = shared.load_shape_donor(candidate)
    fit = shared.fit_deformation_bind(
        donor_names=donor["jointNames"], donor_parents=donor["bindParents"],
        donor_rest=shared.donor_rest_joints(donor), target_names=target["names"],
        target_rest=target["restWorld"], target_vertices=target["vertices"],
        target_regions=target["vertexRegions"], profile=candidate)
    shared.rig_gate(names=donor["jointNames"], parents=donor["bindParents"],
        fitted=fit["fittedPositions"], offsets=fit["offsets"],
        profile=candidate, helpers=fit["helpers"])
    world = shared.bind_world_matrices(fit["offsets"], donor["bindParents"])
    return {"offsets": fit["offsets"], "inverseBind": shared.inverse_bind_matrices(world),
            "names": list(donor["jointNames"]), "parents": donor["bindParents"],
            "inputProfileHash": _profile_hash(profile), "candidateProfileHash": _profile_hash(candidate),
            "donorHash": _donor_hash(donor), "meshSha256": target["sourceSha256"],
            "referenceBindIdentityError": float(np.abs(world @ shared.inverse_bind_matrices(world) - np.eye(4)).max())}
