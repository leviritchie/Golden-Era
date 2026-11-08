#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"
DEFAULT_PROOFS_PATH = ROOT / "custom_factions" / "custom_law_packet_proofs.json"
PROOF_STATUSES_REQUIRING_ARTIFACT = {
    "static-evidence",
    "runtime-proven",
    "live-bridge-metadata-proven-runtime-ordering-unproven",
    "partial-live-bridge-metadata-proven-correlation-unproven",
    "partial-live-bridge-metadata-proven-commit-unproven",
    "live-bridge-metadata-proven-cast-gate-unproven",
    "live-bridge-metadata-proven-reveal-mutation-unproven",
}
ALLOWED_PROOF_STATUS = {
    "runtime-unproven",
    "static-evidence",
    "runtime-proven",
    "blocked",
    "live-bridge-metadata-proven-runtime-ordering-unproven",
    "partial-live-bridge-metadata-proven-correlation-unproven",
    "partial-live-bridge-metadata-proven-commit-unproven",
    "live-bridge-metadata-proven-cast-gate-unproven",
    "live-bridge-metadata-proven-reveal-mutation-unproven",
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
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def target_packets(targets_doc: Any, v: Validation) -> set[str]:
    packets: set[str] = set()
    if not isinstance(targets_doc, dict):
        v.error("custom law targets root must be an object")
        return packets
    families = targets_doc.get("families")
    if not isinstance(families, dict):
        v.error("custom law targets families must be an object")
        return packets
    for key, entry in sorted(families.items()):
        if not isinstance(entry, dict):
            v.error(f"targets families.{key}: must be an object")
            continue
        packet = entry.get("packet")
        if not isinstance(packet, str) or not packet:
            v.error(f"targets families.{key}: packet must be a non-empty string")
            continue
        packets.add(packet)
    return packets


def validate_packet_entry(packet: str, entry: Any, v: Validation) -> None:
    if not isinstance(entry, dict):
        v.error(f"{packet}: proof entry must be an object")
        return
    proof_status = entry.get("proofStatus")
    if proof_status not in ALLOWED_PROOF_STATUS:
        v.error(f"{packet}: proofStatus must be one of {sorted(ALLOWED_PROOF_STATUS)}, got {proof_status!r}")
    gameplay_allowed = entry.get("gameplayAllowed")
    if not isinstance(gameplay_allowed, bool):
        v.error(f"{packet}: gameplayAllowed must be a boolean")
    evidence_summary = entry.get("evidenceSummary")
    if not isinstance(evidence_summary, str) or not evidence_summary.strip():
        v.error(f"{packet}: evidenceSummary must be a non-empty string")
    artifact = entry.get("lastEvidenceArtifact")
    if artifact is not None and (not isinstance(artifact, str) or not artifact.strip()):
        v.error(f"{packet}: lastEvidenceArtifact must be null or a non-empty string")

    if proof_status in PROOF_STATUSES_REQUIRING_ARTIFACT:
        if not isinstance(artifact, str) or not artifact.strip():
            v.error(f"{packet}: proofStatus={proof_status!r} requires lastEvidenceArtifact")
        else:
            artifact_path = ROOT / artifact
            if not artifact_path.exists():
                v.error(f"{packet}: lastEvidenceArtifact does not exist: {artifact}")
    if proof_status == "runtime-unproven" and artifact is not None:
        v.error(f"{packet}: runtime-unproven packets must not carry lastEvidenceArtifact")
    if proof_status == "runtime-unproven" and isinstance(evidence_summary, str):
        lowered = evidence_summary.lower()
        if "live bridge metadata proves" in lowered or "metadata proves" in lowered or "runtime-proven" in lowered:
            v.error(f"{packet}: runtime-unproven evidenceSummary must not claim proof")

    if gameplay_allowed is True and proof_status != "runtime-proven":
        v.error(f"{packet}: gameplayAllowed=true requires proofStatus='runtime-proven'")
    if proof_status == "runtime-proven" and gameplay_allowed is not True:
        v.error(f"{packet}: proofStatus='runtime-proven' requires gameplayAllowed=true")
    if gameplay_allowed is True and artifact is None:
        v.error(f"{packet}: gameplayAllowed=true requires lastEvidenceArtifact")


def validate_proofs(proofs_doc: Any, required_packets: set[str], v: Validation) -> None:
    if not isinstance(proofs_doc, dict):
        v.error("packet proofs root must be an object")
        return
    if proofs_doc.get("schemaVersion") != 1:
        v.error(f"schemaVersion must be 1, got {proofs_doc.get('schemaVersion')!r}")
    packets = proofs_doc.get("packets")
    if not isinstance(packets, dict):
        v.error("packets must be an object keyed by packet name")
        return

    for packet in sorted(required_packets):
        if packet not in packets:
            v.error(f"missing proof entry for target packet {packet!r}")

    for packet, entry in sorted(packets.items()):
        if packet not in required_packets:
            v.warn(f"{packet}: proof entry is not referenced by current target packet families")
        validate_packet_entry(str(packet), entry, v)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate custom law packet proof-state ledger.")
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS_PATH)
    parser.add_argument("--proofs", type=Path, default=DEFAULT_PROOFS_PATH)
    args = parser.parse_args()

    v = Validation()
    if not args.targets.exists():
        v.error(f"missing targets file: {args.targets}")
    if not args.proofs.exists():
        v.error(f"missing packet proofs file: {args.proofs}")
    if v.errors:
        print(f"errors: {v.errors}")
        return 1

    packets = target_packets(load_json(args.targets), v)
    validate_proofs(load_json(args.proofs), packets, v)
    print(f"target packets: {sorted(packets)}")
    print(f"errors: {v.errors}")
    if v.warnings:
        print(f"warnings: {v.warnings}")
    return 1 if v.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
