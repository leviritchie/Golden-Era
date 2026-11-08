"""Generate an asset-level semantic description from geometry and existing rig evidence."""
from __future__ import annotations

from typing import Any

import numpy as np

from shape_donor import donor_rest_joints, load_shape_donor, region_for_joint
from target_asset import load_target_asset


def _pca(points: np.ndarray) -> dict[str, Any]:
    values = np.asarray(points, dtype=np.float64)
    if len(values) < 3:
        return {"count": int(len(values)), "axis": None, "span": None}
    centered = values - values.mean(0)
    _u, singular, vh = np.linalg.svd(centered, full_matrices=False)
    return {
        "count": int(len(values)),
        "centroid": values.mean(0).tolist(),
        "axis": vh[0].tolist(),
        "span": singular.tolist(),
        "bboxMin": values.min(0).tolist(),
        "bboxMax": values.max(0).tolist(),
    }


def describe_asset(profile: dict[str, Any]) -> dict[str, Any]:
    target = load_target_asset(profile)
    donor = load_shape_donor(profile)
    names = list(donor["jointNames"])
    donor_rest = donor_rest_joints(donor)
    target_rest = np.asarray(target["restWorld"], dtype=np.float64)
    regions = np.asarray(target["vertexRegions"])
    region_stats = {}
    for region in sorted(set(regions.tolist())):
        mask = regions == region
        region_stats[str(region)] = _pca(target["vertices"][mask])
        region_stats[str(region)]["vertexCount"] = int(mask.sum())
    evidence = []
    t_index = target["nameIndex"]
    for hub_donor, hub_target in profile["hubs"].items():
        evidence.append(
            {
                "role": "hub",
                "donorJoint": hub_donor,
                "targetBone": hub_target,
                "targetPosition": target_rest[t_index[hub_target]].tolist(),
                "source": "existing_smartrig_label_as_evidence_not_truth",
            }
        )
    for chain in profile["chains"]:
        if chain["kind"] != "polyline":
            continue
        evidence.append(
            {
                "role": "chain",
                "name": chain["name"],
                "donorJoints": list(chain["donor"]),
                "targetBones": list(chain["evidence"]),
                "targetPositions": [target_rest[t_index[name]].tolist() for name in chain["evidence"]],
                "source": "smartrig_chain_plus_mesh_region",
            }
        )
    donor_index = {name: index for index, name in enumerate(names)}
    left_right = []
    for pair in profile["leftRightPairs"]:
        left_d, right_d = pair["donor"]
        left_t, right_t = pair["evidence"]
        left_right.append(
            {
                "donorLeft": left_d,
                "donorRight": right_d,
                "targetLeft": left_t,
                "targetRight": right_t,
                "donorLeftRest": donor_rest[donor_index[left_d]].tolist(),
                "donorRightRest": donor_rest[donor_index[right_d]].tolist(),
                "targetLeftRest": target_rest[t_index[left_t]].tolist(),
                "targetRightRest": target_rest[t_index[right_t]].tolist(),
            }
        )
    helpers = [chain["name"] for chain in profile["chains"] if chain.get("helper")]
    return {
        "assetId": profile["assetId"],
        "proof": "generated-artifact",
        "reviewStatus": "pending_agent_verification",
        "visibleMesh": {
            "path": target["sourceMesh"],
            "sha256": target["sourceSha256"],
            "vertexCount": int(len(target["vertices"])),
            "triangleCount": int(len(target["triangles"])),
            "uvCount": int(len(target["uvs"])),
            "componentCount": int(target["componentCount"]),
            "coincidenceGroupCount": int(len(target["coincidenceGroups"])),
        },
        "existingRigEvidence": {
            "boneNames": target["names"],
            "boneCount": int(len(target["names"])),
            "note": "labels and weights are evidence; they do not define the deformation graph",
        },
        "donor": {
            "kind": profile["donorKind"],
            "refSeq": profile["donorRefSeq"],
            "jointNames": names,
            "jointCount": int(len(names)),
            "parents": np.asarray(donor["bindParents"], dtype=np.int64).tolist(),
            "bindSource": profile["donorBindSource"],
        },
        "regionOwnership": region_stats,
        "proposedCorrespondence": evidence,
        "leftRight": left_right,
        "rigidAttachments": [dict(item) for item in profile.get("rigidAttachments", ())],
        "helperChains": helpers,
        "unsupportedRequiredArticulations": list(profile.get("unsupportedRequiredArticulations", ())),
        "extraTargetBonesNotInDonorGraph": list(profile.get("extraTargetBones", ())),
        "requiredBranches": list(profile["requiredBranches"]),
        "spaces": donor["spaces"],
        "verificationChecklist": [
            "Left/right pairs match mesh laterality, not the old compressed SmartRig retarget map.",
            "Wing/arm chains keep every donor joint; they are not collapsed onto three SmartRig bones.",
            "Hubs are one consistent torso, not independent Procrustes per limb.",
            "Rigid props (beak, shield, weapon) are attached regions, not fake articulations.",
            "Helper joints are explicit. Unweighted helpers are allowed; silent nearest-bone is not.",
        ],
        "jointRegionTable": {
            name: region_for_joint(name, profile["regionJoints"]) for name in names
        },
    }
