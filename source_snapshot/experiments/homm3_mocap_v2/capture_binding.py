"""Hash-pinned capture-to-SmartRig binding schema. No pose sequences.

A binding names the unmodified vendor reference and the semantic branch map.
It does not contain frame numbers, motion amplitudes, or species solver knobs.
Missing correspondence is an explicit limitation, not a silent bind-pose fallback.

The rotation retargeter itself stays gated until capture visibly improves the
source action. This module only validates mapping coverage.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

REQUIRED_FIELDS = (
    "captureReferenceId",
    "semanticBranches",
    "chainEndpoints",
    "bindFrameAlignment",
    "rigidAttachments",
    "captureSkeletonSha256",
    "targetMeshSha256",
)
FORBIDDEN_FIELDS = (
    "frameNumbers",
    "poseSequence",
    "motionAmplitude",
    "speciesSolverSettings",
)
_LEFT_MARK = re.compile(r"(left|(^|_|:)l(_|:|$))", re.IGNORECASE)
_RIGHT_MARK = re.compile(r"(right|(^|_|:)r(_|:|$))", re.IGNORECASE)


def _side(text: str) -> str | None:
    token = str(text)
    has_left = bool(_LEFT_MARK.search(token))
    has_right = bool(_RIGHT_MARK.search(token))
    if has_left and not has_right:
        return "left"
    if has_right and not has_left:
        return "right"
    return None


def validate_capture_binding(
    payload: Mapping[str, Any],
    *,
    capture_names: Sequence[str],
    target_names: Sequence[str],
    capture_skeleton_sha256: str,
    target_mesh_sha256: str,
    required_target_branches: Sequence[str],
) -> dict[str, Any]:
    missing_fields = [field for field in REQUIRED_FIELDS if field not in payload]
    if missing_fields:
        raise ValueError(f"capture_binding is missing {missing_fields}")
    present_forbidden = [field for field in FORBIDDEN_FIELDS if field in payload and payload[field] not in (None, [], {}, "")]
    if present_forbidden:
        raise ValueError(
            f"capture_binding must not contain pose or solver fields {present_forbidden}"
        )
    if str(payload["captureSkeletonSha256"]).lower() != str(capture_skeleton_sha256).lower():
        raise ValueError("capture_binding capture skeleton hash is stale")
    if str(payload["targetMeshSha256"]).lower() != str(target_mesh_sha256).lower():
        raise ValueError("capture_binding target mesh hash is stale")
    branches = payload["semanticBranches"]
    if not isinstance(branches, dict) or not branches:
        raise ValueError("semanticBranches must be a non-empty map of target bone -> capture joint")
    capture_set = set(capture_names)
    target_set = set(target_names)
    unknown_target = sorted(name for name in branches if name not in target_set)
    unknown_capture = sorted(str(value) for value in branches.values() if str(value) not in capture_set)
    if unknown_target:
        raise ValueError(f"semanticBranches has unknown target bones {unknown_target}")
    if unknown_capture:
        raise ValueError(f"semanticBranches has unknown capture joints {unknown_capture}")
    missing_branches = [name for name in required_target_branches if name not in branches]
    if missing_branches:
        raise ValueError(
            f"missing correspondence for deforming branches {missing_branches}; "
            "this is an explicit limitation, not a silent bind-pose fallback"
        )
    swapped: list[str] = []
    for target, capture in branches.items():
        target_side = _side(str(target))
        capture_side = _side(str(capture))
        if target_side and capture_side and target_side != capture_side:
            swapped.append(f"{target}->{capture}")
    if swapped:
        raise ValueError(f"left/right correspondence is swapped: {swapped}")
    endpoints = payload["chainEndpoints"]
    if not isinstance(endpoints, dict):
        raise ValueError("chainEndpoints must be a map")
    chains = payload.get("chains") or []
    if chains:
        _validate_chains(
            chains,
            capture_names=capture_names,
            target_names=target_names,
            required_target_branches=required_target_branches,
        )
    return {
        "ok": True,
        "captureReferenceId": payload["captureReferenceId"],
        "mappedTargetCount": len(branches),
        "requiredTargetCount": len(required_target_branches),
        "rigidAttachmentCount": len(payload["rigidAttachments"] or []),
        "missingCorrespondenceIsExplicit": True,
        "chainCount": len(chains) if isinstance(chains, list) else 0,
    }


def _validate_chains(
    chains: Sequence[Any],
    *,
    capture_names: Sequence[str],
    target_names: Sequence[str],
    required_target_branches: Sequence[str],
) -> None:
    if not isinstance(chains, list) or not chains:
        raise ValueError("chains must be a non-empty list")
    capture_set = set(capture_names)
    target_set = set(target_names)
    covered: set[str] = set()
    for chain in chains:
        if not isinstance(chain, dict):
            raise ValueError("each chain must be an object")
        target_chain = chain.get("target")
        capture_chain = chain.get("capture")
        if not isinstance(target_chain, list) or len(target_chain) < 2:
            raise ValueError(f"chain {chain.get('name')!r} target must have at least two joints")
        if not isinstance(capture_chain, list) or len(capture_chain) < 2:
            raise ValueError(f"chain {chain.get('name')!r} capture must have at least two joints")
        unknown_t = [name for name in target_chain if str(name) not in target_set]
        unknown_c = [name for name in capture_chain if str(name) not in capture_set]
        if unknown_t:
            raise ValueError(f"chain {chain.get('name')!r} has unknown target joints {unknown_t}")
        if unknown_c:
            raise ValueError(f"chain {chain.get('name')!r} has unknown capture joints {unknown_c}")
        covered.update(str(name) for name in target_chain)
    missing = [name for name in required_target_branches if name not in covered]
    if missing:
        raise ValueError(
            f"missing correspondence for deforming branches {missing}; "
            "this is an explicit limitation, not a silent bind-pose fallback"
        )


def validate_retarget_binding(
    payload: Mapping[str, Any],
    *,
    capture_names: Sequence[str],
    target_names: Sequence[str],
    capture_skeleton_sha256: str,
    target_mesh_sha256: str,
    required_target_branches: Sequence[str],
) -> dict[str, Any]:
    if not payload.get("chains"):
        raise ValueError("retarget binding requires chains; missing correspondence is not a bind-pose fallback")
    return validate_capture_binding(
        payload,
        capture_names=capture_names,
        target_names=target_names,
        capture_skeleton_sha256=capture_skeleton_sha256,
        target_mesh_sha256=target_mesh_sha256,
        required_target_branches=required_target_branches,
    )


def deforming_bones_from_aim_chains(joint_names_payload: Mapping[str, Any]) -> tuple[str, ...]:
    chains = joint_names_payload.get("aimChains") or []
    ordered: list[str] = []
    seen: set[str] = set()
    for chain in chains:
        for name in chain:
            token = str(name)
            if token not in seen:
                seen.add(token)
                ordered.append(token)
    return tuple(ordered)
