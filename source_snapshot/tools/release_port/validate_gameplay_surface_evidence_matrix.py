#!/usr/bin/env python3
"""Validate the gameplay surface evidence matrix.

This is a static falsifiability check. It verifies that authored gameplay
surface claims do not overstate available evidence and that no surface can
authorize gameplay mutation without packet-level runtime proof.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATRIX_PATH = ROOT / "custom_factions" / "gameplay_surface_evidence_matrix.json"
DEFAULT_PACKET_PROOFS_PATH = ROOT / "custom_factions" / "custom_law_packet_proofs.json"

ALLOWED_DOMAINS = {
    "ability-config",
    "adventure-service",
    "adventure-object",
    "adventure-movement",
    "artifact-service",
    "battle-action",
    "battle-actor",
    "battle-lifecycle",
    "battle-outcome",
    "biome",
    "bonus-system",
    "buff-status",
    "calendar-weather",
    "committed-damage",
    "config-taxonomy",
    "construction",
    "counterattack",
    "corpse-death",
    "damage-forecast",
    "diplomacy",
    "economy",
    "energy",
    "event-payload",
    "event-bank",
    "hero-ability",
    "hero-identity",
    "hero-ownership",
    "hero-skill",
    "item-artifact",
    "law-state",
    "luck-morale",
    "magic-rules",
    "market",
    "map-area",
    "map-trigger",
    "morale",
    "necromancy",
    "object-property",
    "party-squad",
    "reward-config",
    "reward-result",
    "scenario-state",
    "session-state",
    "spell-cooldown",
    "spellbook",
    "town-building",
    "town-hire",
    "town-service",
    "teleportation",
    "turn-mode",
    "ui",
    "unit-identity",
    "vision",
}
ALLOWED_CLAIM_TYPES = {
    "classifier",
    "correlation",
    "event",
    "identity",
    "lifecycle",
    "mutation",
    "read",
    "ui",
}
ALLOWED_STATUSES = {
    "candidate",
    "missing",
    "partial",
    "proven-live-metadata",
    "proven-static",
    "rejected",
    "runtime-proven",
    "runtime-unproven",
}
ALLOWED_USES = {"diagnostic", "gameplayMutation", "readOnly", "sourcePrepared"}
PROVEN_STATUSES = {"proven-live-metadata", "proven-static", "runtime-proven"}
STATIC_EVIDENCE_KINDS = {
    "decomp-static",
    "diffable",
    "game-symbols",
    "generated-interop",
    "isil",
    "law-surface-dossier",
    "method-dossier",
    "semantic-index",
    "source-prepared-matrix",
    "symbol-map",
}
LIVE_EVIDENCE_KINDS = {"live-bridge-proof", "runtime-log"}
ALLOWED_PACKET_STATIC_LEVELS = {"strong", "strong-partial", "partial", "weak", "missing"}
ALLOWED_PATCH_DRIFT_STABILITIES = {
    "candidate-or-partial-sensitive",
    "generated-symbol-sensitive",
    "layout-sensitive-static",
    "runtime-metadata-sensitive",
    "static-declaration-sensitive",
}


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def as_object(value: Any, label: str, v: Validation) -> dict[str, Any]:
    if not isinstance(value, dict):
        v.error(f"{label} must be an object")
        return {}
    return value


def as_string_list(value: Any, label: str, v: Validation, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        v.error(f"{label} must be a list")
        return []
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            v.error(f"{label}[{index}] must be a non-empty string")
            continue
        result.append(item)
    if not allow_empty and not result:
        v.error(f"{label} must not be empty")
    return result


def packet_entries(packet_doc: Any, v: Validation) -> dict[str, Any]:
    root = as_object(packet_doc, "packet proof root", v)
    packets = as_object(root.get("packets"), "packet proof packets", v)
    return packets


def has_evidence_kind(evidence_refs: list[dict[str, Any]], allowed: set[str]) -> bool:
    return any(ref.get("kind") in allowed for ref in evidence_refs)


def blocking_contradictions(entry: dict[str, Any]) -> list[str]:
    result: list[str] = []
    contradictions = entry.get("contradictingEvidence", [])
    if not isinstance(contradictions, list):
        return ["contradictingEvidence must be a list"]
    for index, contradiction in enumerate(contradictions):
        if not isinstance(contradiction, dict):
            result.append(f"contradictingEvidence[{index}] must be an object")
            continue
        if contradiction.get("severity") == "blocking":
            summary = contradiction.get("summary")
            result.append(summary if isinstance(summary, str) and summary else f"blocking contradiction {index}")
    return result


def validate_evidence_refs(surface_id: str, value: Any, v: Validation) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        v.error(f"{surface_id}: evidenceRefs must be a non-empty list")
        return []
    refs: list[dict[str, Any]] = []
    for index, raw_ref in enumerate(value):
        if not isinstance(raw_ref, dict):
            v.error(f"{surface_id}: evidenceRefs[{index}] must be an object")
            continue
        kind = raw_ref.get("kind")
        path_value = raw_ref.get("path")
        ref_id = raw_ref.get("id")
        if not isinstance(kind, str) or not kind.strip():
            v.error(f"{surface_id}: evidenceRefs[{index}].kind must be a non-empty string")
        if not isinstance(path_value, str) or not path_value.strip():
            v.error(f"{surface_id}: evidenceRefs[{index}].path must be a non-empty string")
        else:
            path = ROOT / path_value
            if not path.exists():
                v.error(f"{surface_id}: evidenceRefs[{index}].path does not exist: {path_value}")
        if ref_id is not None and (not isinstance(ref_id, str) or not ref_id.strip()):
            v.error(f"{surface_id}: evidenceRefs[{index}].id must be omitted or a non-empty string")
        refs.append(raw_ref)
    return refs



def validate_proof_boundary_chains(
    matrix: dict[str, Any],
    surfaces: dict[str, Any],
    proofs: dict[str, Any],
    v: Validation,
) -> None:
    chains_raw = matrix.get("proofBoundaryChains", {})
    if chains_raw is None:
        chains_raw = {}
    chains = as_object(chains_raw, "proofBoundaryChains", v)
    for chain_id, chain in sorted(chains.items()):
        if not isinstance(chain_id, str) or not chain_id.strip():
            v.error("proofBoundaryChains ids must be non-empty strings")
            continue
        entry = as_object(chain, f"proofBoundaryChains.{chain_id}", v)
        if not entry:
            continue
        purpose = entry.get("purpose")
        if not isinstance(purpose, str) or not purpose.strip():
            v.error(f"proofBoundaryChains.{chain_id}.purpose must be a non-empty string")
        packets = as_string_list(entry.get("appliesToPackets"), f"proofBoundaryChains.{chain_id}.appliesToPackets", v)
        stages_raw = entry.get("stages")
        if not isinstance(stages_raw, list) or not stages_raw:
            v.error(f"proofBoundaryChains.{chain_id}.stages must be a non-empty list")
            continue
        stage_labels: list[str] = []
        for index, raw_stage in enumerate(stages_raw):
            stage = as_object(raw_stage, f"proofBoundaryChains.{chain_id}.stages[{index}]", v)
            if not stage:
                continue
            for field in ("id", "surfaceId", "requiredBefore"):
                value = stage.get(field)
                if not isinstance(value, str) or not value.strip():
                    v.error(f"proofBoundaryChains.{chain_id}.stages[{index}].{field} must be a non-empty string")
            surface_id = stage.get("surfaceId")
            if isinstance(surface_id, str) and surface_id not in surfaces:
                v.error(f"proofBoundaryChains.{chain_id}.stages[{index}] references unknown surface {surface_id!r}")
            elif isinstance(surface_id, str):
                surface = surfaces.get(surface_id)
                if isinstance(surface, dict):
                    details = surface.get("surface")
                    if not isinstance(details, dict) or details.get("proofStage") != stage.get("id"):
                        v.error(f"proofBoundaryChains.{chain_id}.stages[{index}] surface {surface_id!r} must declare matching surface.proofStage")
            label = stage.get("requiredBefore")
            if isinstance(label, str) and label.strip():
                stage_labels.append(label)
            distinguish = stage.get("mustDistinguishFailureFrom", [])
            if not isinstance(distinguish, list):
                v.error(f"proofBoundaryChains.{chain_id}.stages[{index}].mustDistinguishFailureFrom must be a list")
            else:
                for d_index, item in enumerate(distinguish):
                    if not isinstance(item, str) or not item.strip():
                        v.error(f"proofBoundaryChains.{chain_id}.stages[{index}].mustDistinguishFailureFrom[{d_index}] must be a non-empty string")
        for packet in packets:
            if packet not in proofs:
                v.error(f"proofBoundaryChains.{chain_id}: packet {packet!r} has no packet proof entry")
                continue
            packet_evidence = matrix.get("packetEvidence", {}).get(packet)
            if not isinstance(packet_evidence, dict):
                v.error(f"proofBoundaryChains.{chain_id}: packetEvidence missing packet {packet!r}")
                continue
            blocked = packet_evidence.get("stillRuntimeBlockedBy", [])
            if not isinstance(blocked, list):
                v.error(f"proofBoundaryChains.{chain_id}: packetEvidence.{packet}.stillRuntimeBlockedBy must be a list")
                continue
            for label in stage_labels:
                if label not in blocked:
                    v.error(f"proofBoundaryChains.{chain_id}: packetEvidence.{packet}.stillRuntimeBlockedBy missing staged blocker {label!r}")

def validate_packet_evidence(
    matrix: dict[str, Any],
    surfaces: dict[str, Any],
    proofs: dict[str, Any],
    v: Validation,
) -> None:
    packet_evidence = as_object(matrix.get("packetEvidence"), "packetEvidence", v)
    if not packet_evidence:
        return

    proof_packets = set(proofs.keys())
    evidence_packets = set(str(packet) for packet in packet_evidence.keys())
    missing = sorted(proof_packets - evidence_packets)
    extra = sorted(evidence_packets - proof_packets)
    if missing:
        v.error("packetEvidence missing packet(s): " + ", ".join(missing))
    if extra:
        v.error("packetEvidence has unknown packet(s): " + ", ".join(extra))

    for packet in sorted(evidence_packets):
        entry = as_object(packet_evidence.get(packet), f"packetEvidence.{packet}", v)
        if not entry:
            continue
        level = entry.get("staticEvidenceLevel")
        if level not in ALLOWED_PACKET_STATIC_LEVELS:
            v.error(
                f"packetEvidence.{packet}: staticEvidenceLevel must be one of "
                f"{sorted(ALLOWED_PACKET_STATIC_LEVELS)}, got {level!r}"
            )
        summary = entry.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            v.error(f"packetEvidence.{packet}: summary must be a non-empty string")

        surface_ids = as_string_list(entry.get("surfaceIds"), f"packetEvidence.{packet}.surfaceIds", v)
        for surface_id in surface_ids:
            if surface_id not in surfaces:
                v.error(f"packetEvidence.{packet}: surfaceIds references unknown surface {surface_id!r}")
                continue
            surface = surfaces.get(surface_id)
            if isinstance(surface, dict) and packet not in surface.get("packets", []):
                v.error(f"packetEvidence.{packet}: surface {surface_id!r} does not reference packet {packet!r}")

        exact_anchors = as_string_list(entry.get("exactStaticAnchors"), f"packetEvidence.{packet}.exactStaticAnchors", v)
        generated_anchors = as_string_list(
            entry.get("generatedOrLiveAnchors"),
            f"packetEvidence.{packet}.generatedOrLiveAnchors",
            v,
            allow_empty=True,
        )
        still_blocked = as_string_list(entry.get("stillRuntimeBlockedBy"), f"packetEvidence.{packet}.stillRuntimeBlockedBy", v)
        if "packet gameplayAllowed=false" not in still_blocked:
            proof = proofs.get(packet)
            if isinstance(proof, dict) and proof.get("gameplayAllowed") is False:
                v.error(f"packetEvidence.{packet}: stillRuntimeBlockedBy must include 'packet gameplayAllowed=false'")

        evidence_refs = validate_evidence_refs(f"packetEvidence.{packet}", entry.get("evidenceRefs"), v)
        if level in {"strong", "strong-partial"}:
            if len(exact_anchors) < 2:
                v.error(f"packetEvidence.{packet}: strong static evidence requires at least two exactStaticAnchors")
            if not generated_anchors:
                v.error(f"packetEvidence.{packet}: strong static evidence requires generatedOrLiveAnchors")
            if not has_evidence_kind(evidence_refs, STATIC_EVIDENCE_KINDS):
                v.error(f"packetEvidence.{packet}: strong static evidence requires a static evidence reference")

        contradictions = entry.get("contradictions")
        if not isinstance(contradictions, list):
            v.error(f"packetEvidence.{packet}: contradictions must be a list")
        else:
            for index, contradiction in enumerate(contradictions):
                if not isinstance(contradiction, str) or not contradiction.strip():
                    v.error(f"packetEvidence.{packet}: contradictions[{index}] must be a non-empty string")


def validate_surface(
    surface_id: str,
    entry: Any,
    surfaces: dict[str, Any],
    proofs: dict[str, Any],
    v: Validation,
) -> None:
    surface = as_object(entry, f"{surface_id}", v)
    if not surface:
        return

    domain = surface.get("domain")
    if domain not in ALLOWED_DOMAINS:
        v.error(f"{surface_id}: domain must be one of {sorted(ALLOWED_DOMAINS)}, got {domain!r}")

    claim_type = surface.get("claimType")
    if claim_type not in ALLOWED_CLAIM_TYPES:
        v.error(f"{surface_id}: claimType must be one of {sorted(ALLOWED_CLAIM_TYPES)}, got {claim_type!r}")

    semantic_claim = surface.get("semanticClaim")
    if not isinstance(semantic_claim, str) or not semantic_claim.strip():
        v.error(f"{surface_id}: semanticClaim must be a non-empty string")

    status = surface.get("status")
    if status not in ALLOWED_STATUSES:
        v.error(f"{surface_id}: status must be one of {sorted(ALLOWED_STATUSES)}, got {status!r}")

    allowed_uses = as_string_list(surface.get("allowedUses"), f"{surface_id}.allowedUses", v, allow_empty=True)
    for use in allowed_uses:
        if use not in ALLOWED_USES:
            v.error(f"{surface_id}: allowedUses contains unsupported use {use!r}")
    if status == "rejected" and allowed_uses:
        v.error(f"{surface_id}: rejected surfaces must not have allowedUses")
    if status == "missing" and allowed_uses:
        v.error(f"{surface_id}: missing surfaces must not have allowedUses")

    packets = as_string_list(surface.get("packets"), f"{surface_id}.packets", v, allow_empty=True)
    for packet in packets:
        if packet not in proofs:
            v.error(f"{surface_id}: packet {packet!r} has no packet proof entry")

    evidence_refs = validate_evidence_refs(surface_id, surface.get("evidenceRefs"), v)
    dependencies = as_string_list(surface.get("dependsOn"), f"{surface_id}.dependsOn", v, allow_empty=True)
    for dependency in dependencies:
        if dependency not in surfaces:
            v.error(f"{surface_id}: dependsOn references unknown surface {dependency!r}")

    blocked_by = as_string_list(surface.get("blockedBy"), f"{surface_id}.blockedBy", v, allow_empty=True)
    if "gameplayMutation" not in allowed_uses:
        unpromoted_packets = [
            packet
            for packet in packets
            if isinstance(proofs.get(packet), dict) and proofs[packet].get("gameplayAllowed") is False
        ]
        if unpromoted_packets and "packet gameplayAllowed=false" not in blocked_by and status != "rejected":
            v.error(
                f"{surface_id}: blockedBy must include 'packet gameplayAllowed=false' "
                f"while packet(s) {unpromoted_packets} are not promoted"
            )

    if not isinstance(surface.get("falsifiers"), list) or not surface.get("falsifiers"):
        v.error(f"{surface_id}: falsifiers must be a non-empty list")
    else:
        for index, falsifier in enumerate(surface["falsifiers"]):
            if not isinstance(falsifier, str) or not falsifier.strip():
                v.error(f"{surface_id}: falsifiers[{index}] must be a non-empty string")

    next_proof_action = surface.get("nextProofAction")
    if not isinstance(next_proof_action, str) or not next_proof_action.strip():
        v.error(f"{surface_id}: nextProofAction must be a non-empty string")

    details = as_object(surface.get("surface"), f"{surface_id}.surface", v)
    candidate_ambiguity = details.get("candidateAmbiguity") if details else None
    if not isinstance(candidate_ambiguity, int) or candidate_ambiguity < 0:
        v.error(f"{surface_id}: surface.candidateAmbiguity must be a non-negative integer")
    discriminator = details.get("discriminator") if details else None
    flags = details.get("flags", []) if details else []
    if flags is None:
        flags = []
    if not isinstance(flags, list):
        v.error(f"{surface_id}: surface.flags must be a list when present")
        flags = []

    blockers = blocking_contradictions(surface)
    if status in PROVEN_STATUSES and blockers:
        v.error(f"{surface_id}: proven status cannot have blocking contradictingEvidence: {blockers}")

    if status == "proven-live-metadata" and not has_evidence_kind(evidence_refs, LIVE_EVIDENCE_KINDS):
        v.error(f"{surface_id}: proven-live-metadata requires live bridge or runtime log evidence")
    if status == "proven-static" and not has_evidence_kind(evidence_refs, STATIC_EVIDENCE_KINDS):
        v.error(f"{surface_id}: proven-static requires static decomp/generated evidence")
    if status == "runtime-proven" and not has_evidence_kind(evidence_refs, LIVE_EVIDENCE_KINDS):
        v.error(f"{surface_id}: runtime-proven requires runtime evidence")

    if "ordinal-mismatch" in flags and status in PROVEN_STATUSES:
        v.error(f"{surface_id}: ordinal-mismatch evidence cannot be marked proven")
    if candidate_ambiguity and candidate_ambiguity > 0 and status in PROVEN_STATUSES and not discriminator:
        v.error(f"{surface_id}: ambiguous candidates cannot be marked proven without a discriminator")
    if any(flag in {"broad-fallback", "broad-event-dispatch"} for flag in flags) and status != "rejected":
        v.error(f"{surface_id}: broad fallback/event dispatch surfaces must be rejected")
    if "eew.bdmh(Int32)" in json.dumps(details, sort_keys=True) and status != "rejected":
        v.error(f"{surface_id}: eew.bdmh(Int32) cooldown setter hypothesis must remain rejected")

    if domain == "reward-result":
        reward_stage = surface.get("rewardCommitStage")
        if not isinstance(reward_stage, str) or not reward_stage.strip():
            v.error(f"{surface_id}: reward-result surfaces must include rewardCommitStage")

    if claim_type == "classifier" and surface.get("unitRoleFactStatus") == "unknown":
        if status not in {"candidate", "missing", "rejected"} or allowed_uses:
            v.error(f"{surface_id}: unknown unit role facts cannot support active uses")

    patch_drift = as_object(surface.get("patchDrift"), f"{surface_id}.patchDrift", v)
    if patch_drift:
        stability = patch_drift.get("stability")
        if stability not in ALLOWED_PATCH_DRIFT_STABILITIES:
            v.error(
                f"{surface_id}: patchDrift.stability must be one of "
                f"{sorted(ALLOWED_PATCH_DRIFT_STABILITIES)}, got {stability!r}"
            )
        as_string_list(patch_drift.get("refreshActions"), f"{surface_id}.patchDrift.refreshActions", v)
        drift_risks = as_string_list(
            patch_drift.get("driftRisks"),
            f"{surface_id}.patchDrift.driftRisks",
            v,
            allow_empty=True,
        )
        if status in {"candidate", "partial", "missing", "runtime-unproven"}:
            if "not gameplay-authoritative" not in drift_risks:
                v.error(f"{surface_id}: weak surfaces must include patchDrift drift risk 'not gameplay-authoritative'")
        for field in ("lastStaticRefresh", "lastRuntimeRefresh"):
            value = patch_drift.get(field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                v.error(f"{surface_id}: patchDrift.{field} must be null or a non-empty string")

    if "gameplayMutation" in allowed_uses:
        if not packets:
            v.error(f"{surface_id}: gameplayMutation requires at least one packet gate")
        if status != "runtime-proven":
            v.error(f"{surface_id}: gameplayMutation requires status='runtime-proven'")
        for packet in packets:
            proof = proofs.get(packet)
            if not isinstance(proof, dict):
                continue
            if proof.get("proofStatus") != "runtime-proven" or proof.get("gameplayAllowed") is not True:
                v.error(f"{surface_id}: gameplayMutation requires packet {packet!r} to be runtime-proven and gameplayAllowed=true")

    for dependency in dependencies:
        dep = surfaces.get(dependency)
        if not isinstance(dep, dict):
            continue
        dep_status = dep.get("status")
        if status in PROVEN_STATUSES and dep_status not in PROVEN_STATUSES:
            v.error(f"{surface_id}: proven surface depends on weaker surface {dependency} ({dep_status})")
        if "gameplayMutation" in allowed_uses and dep_status in {"missing", "rejected"}:
            v.error(f"{surface_id}: gameplay surface depends on blocked surface {dependency} ({dep_status})")


def validate_matrix(matrix_doc: Any, packet_doc: Any) -> Validation:
    v = Validation()
    matrix = as_object(matrix_doc, "matrix root", v)
    proofs = packet_entries(packet_doc, v)
    if v.errors:
        return v

    if matrix.get("schemaVersion") != 1:
        v.error(f"schemaVersion must be 1, got {matrix.get('schemaVersion')!r}")

    dependency_semantics = as_object(matrix.get("dependencySemantics"), "dependencySemantics", v)
    for required_key in ("dependsOn", "blockedBy", "relatedSurfaces"):
        value = dependency_semantics.get(required_key)
        if not isinstance(value, str) or not value.strip():
            v.error(f"dependencySemantics.{required_key} must be a non-empty string")

    policy = as_object(matrix.get("policy"), "policy", v)
    for required_true in (
        "noFallbacks",
        "failClosed",
        "staticEvidenceCannotPromoteGameplay",
        "runtimeProofRequiredForGameplayMutation",
        "ambiguousCandidatesCannotBeExact",
    ):
        if policy.get(required_true) is not True:
            v.error(f"policy.{required_true} must be true")

    surfaces = as_object(matrix.get("surfaces"), "surfaces", v)
    if not surfaces:
        v.error("surfaces must not be empty")
        return v

    validate_packet_evidence(matrix, surfaces, proofs, v)
    validate_proof_boundary_chains(matrix, surfaces, proofs, v)

    for surface_id in sorted(surfaces.keys()):
        if not isinstance(surface_id, str) or not surface_id.strip():
            v.error("surface ids must be non-empty strings")
            continue
        validate_surface(surface_id, surfaces[surface_id], surfaces, proofs, v)

    return v


def make_minimal_valid_doc() -> tuple[dict[str, Any], dict[str, Any]]:
    packet_doc = {
        "packets": {
            "vision": {
                "proofStatus": "runtime-unproven",
                "gameplayAllowed": False,
                "evidenceSummary": "test",
                "lastEvidenceArtifact": None,
            }
        }
    }
    matrix_doc = {
        "schemaVersion": 1,
        "policy": {
            "noFallbacks": True,
            "failClosed": True,
            "staticEvidenceCannotPromoteGameplay": True,
            "runtimeProofRequiredForGameplayMutation": True,
            "ambiguousCandidatesCannotBeExact": True,
        },
        "dependencySemantics": {
            "dependsOn": "hard dependencies only",
            "blockedBy": "proof blockers",
            "relatedSurfaces": "non-gating context",
        },
        "surfaces": {
            "vision.test": {
                "domain": "vision",
                "claimType": "read",
                "semanticClaim": "Test surface.",
                "status": "partial",
                "allowedUses": ["diagnostic"],
                "packets": ["vision"],
                "surface": {
                    "candidateAmbiguity": 0,
                    "discriminator": None,
                },
                "patchDrift": {
                    "stability": "candidate-or-partial-sensitive",
                    "refreshActions": ["validate evidence path exists"],
                    "driftRisks": ["not gameplay-authoritative"],
                    "lastStaticRefresh": None,
                    "lastRuntimeRefresh": None,
                },
                "evidenceRefs": [
                    {
                        "kind": "packet-proof",
                        "path": "custom_factions/custom_law_packet_proofs.json",
                        "id": "vision",
                    }
                ],
                "contradictingEvidence": [],
                "falsifiers": ["test falsifier"],
                "dependsOn": [],
                "blockedBy": ["packet gameplayAllowed=false"],
                "nextProofAction": "test action",
            }
        },
        "packetEvidence": {
            "vision": {
                "staticEvidenceLevel": "strong",
                "summary": "Test packet evidence.",
                "surfaceIds": ["vision.test"],
                "exactStaticAnchors": ["anchor one", "anchor two"],
                "generatedOrLiveAnchors": ["generated anchor"],
                "contradictions": [],
                "stillRuntimeBlockedBy": ["packet gameplayAllowed=false"],
                "evidenceRefs": [
                    {
                        "kind": "packet-proof",
                        "path": "custom_factions/custom_law_packet_proofs.json",
                        "id": "vision",
                    },
                    {
                        "kind": "diffable",
                        "path": "tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/Data/DataObject.cs",
                        "id": "test",
                    },
                ],
            }
        },
    }
    return matrix_doc, packet_doc


def run_self_tests() -> int:
    cases: list[tuple[str, Any]] = []
    base_matrix, base_packets = make_minimal_valid_doc()

    overclaimed_runtime = copy.deepcopy(base_matrix)
    overclaimed_runtime["surfaces"]["vision.test"]["allowedUses"] = ["gameplayMutation"]
    cases.append(("gameplay mutation without runtime packet proof", overclaimed_runtime))

    ordinal_mismatch = copy.deepcopy(base_matrix)
    ordinal_mismatch["surfaces"]["vision.test"]["status"] = "proven-live-metadata"
    ordinal_mismatch["surfaces"]["vision.test"]["surface"]["flags"] = ["ordinal-mismatch"]
    ordinal_mismatch["surfaces"]["vision.test"]["evidenceRefs"].append(
        {
            "kind": "live-bridge-proof",
            "path": "experiments/cpp2il_readable_csharp/samples/latest_refresh/live_bridge_proofs",
            "id": "test",
        }
    )
    cases.append(("ordinal mismatch marked proven", ordinal_mismatch))

    missing_evidence = copy.deepcopy(base_matrix)
    missing_evidence["surfaces"]["vision.test"]["evidenceRefs"][0]["path"] = "missing/path.json"
    cases.append(("missing evidence reference", missing_evidence))

    ambiguous_proven = copy.deepcopy(base_matrix)
    ambiguous_proven["surfaces"]["vision.test"]["status"] = "proven-live-metadata"
    ambiguous_proven["surfaces"]["vision.test"]["surface"]["candidateAmbiguity"] = 2
    ambiguous_proven["surfaces"]["vision.test"]["surface"]["discriminator"] = None
    ambiguous_proven["surfaces"]["vision.test"]["evidenceRefs"].append(
        {
            "kind": "live-bridge-proof",
            "path": "experiments/cpp2il_readable_csharp/samples/latest_refresh/live_bridge_proofs",
            "id": "test",
        }
    )
    cases.append(("ambiguous candidate marked proven", ambiguous_proven))

    rejected_active = copy.deepcopy(base_matrix)
    rejected_active["surfaces"]["vision.test"]["status"] = "rejected"
    rejected_active["surfaces"]["vision.test"]["allowedUses"] = ["diagnostic"]
    cases.append(("rejected surface with active use", rejected_active))

    unknown_role = copy.deepcopy(base_matrix)
    role = unknown_role["surfaces"]["vision.test"]
    role["domain"] = "battle-action"
    role["claimType"] = "classifier"
    role["status"] = "partial"
    role["allowedUses"] = ["diagnostic"]
    role["packets"] = ["battle-action"]
    role["unitRoleFactStatus"] = "unknown"
    unknown_packets = copy.deepcopy(base_packets)
    unknown_packets["packets"]["battle-action"] = copy.deepcopy(base_packets["packets"]["vision"])
    cases.append(("unknown unit role with active use", (unknown_role, unknown_packets)))

    valid = validate_matrix(base_matrix, base_packets)
    if valid.errors:
        print("self-test baseline failed unexpectedly:", valid.errors, file=sys.stderr)
        return 1

    failures: list[str] = []
    for name, payload in cases:
        if isinstance(payload, tuple):
            matrix, packets = payload
        else:
            matrix, packets = payload, base_packets
        result = validate_matrix(matrix, packets)
        if not result.errors:
            failures.append(name)

    if failures:
        print("self-tests failed to reject invalid case(s): " + ", ".join(failures), file=sys.stderr)
        return 1

    print(f"gameplay surface evidence matrix self-tests passed ({len(cases)} negative case(s))")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate gameplay_surface_evidence_matrix.json. This is a static traceability check only; "
            "it does not build, launch, patch, or prove runtime gameplay behavior."
        )
    )
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX_PATH)
    parser.add_argument("--packet-proofs", type=Path, default=DEFAULT_PACKET_PROOFS_PATH)
    parser.add_argument("--self-test", action="store_true", help="Run built-in negative validation cases.")
    args = parser.parse_args()

    if args.self_test:
        return run_self_tests()

    try:
        matrix = load_json(args.matrix)
        packet_proofs = load_json(args.packet_proofs)
    except (OSError, json.JSONDecodeError) as ex:
        print(f"gameplay surface evidence matrix validation failed: {ex}", file=sys.stderr)
        return 1

    result = validate_matrix(matrix, packet_proofs)
    if result.errors:
        print("gameplay surface evidence matrix validation failed:", file=sys.stderr)
        for error in result.errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    if result.warnings:
        print("warnings:")
        for warning in result.warnings:
            print(f"  - {warning}")

    surfaces = as_object(matrix.get("surfaces"), "surfaces", Validation())
    print(f"gameplay surface evidence matrix validation passed ({len(surfaces)} surface(s))")
    print("Note: static pass does not prove build success or runtime law behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
