#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROOFS_PATH = ROOT / "custom_factions" / "custom_law_packet_proofs.json"
CONFIRM_TEXT = "I_REVIEWED_RUNTIME_EVIDENCE"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path: Path, doc: Any) -> None:
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def require_text(value: str, label: str) -> str:
    value = (value or "").strip()
    if not value:
        raise RuntimeError(f"{label} is required")
    return value


def artifact_text(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Promote one no-compromise custom law packet proof after reviewed runtime evidence. "
            "This edits custom_law_packet_proofs.json only; it does not regenerate C#, build, launch, or validate."
        )
    )
    parser.add_argument("--proofs", type=Path, default=DEFAULT_PROOFS_PATH)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--evidence-artifact", type=Path, required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--flags", required=True, help="Comma-separated diagnostic flags used for the capture.")
    parser.add_argument("--native-symbols", required=True, help="Exact native symbols proven by the reviewed capture.")
    parser.add_argument("--consumed-state", required=True, help="Exact native/custom state read by the intended implementation.")
    parser.add_argument("--mutated-state", required=True, help="Exact native/custom state allowed to be mutated by the intended implementation.")
    parser.add_argument("--docs-updated", required=True, help="Docs/AGENTS files updated with the proof finding.")
    parser.add_argument("--summary", required=True, help="Concise reviewed evidence summary.")
    parser.add_argument(
        "--confirm",
        required=True,
        help=f"Must be exactly {CONFIRM_TEXT!r}; prevents accidental proof promotion.",
    )
    args = parser.parse_args()

    if args.confirm != CONFIRM_TEXT:
        raise RuntimeError(f"--confirm must be exactly {CONFIRM_TEXT!r}")
    if not args.proofs.exists():
        raise RuntimeError(f"missing packet proofs file: {args.proofs}")
    if not args.evidence_artifact.exists():
        raise RuntimeError(f"evidence artifact does not exist: {args.evidence_artifact}")

    doc = load_json(args.proofs)
    if not isinstance(doc, dict):
        raise RuntimeError("packet proofs root must be an object")
    packets = doc.get("packets")
    if not isinstance(packets, dict):
        raise RuntimeError("packet proofs must contain packets object")
    packet = require_text(args.packet, "packet")
    entry = packets.get(packet)
    if not isinstance(entry, dict):
        raise RuntimeError(f"unknown packet proof entry: {packet}")

    flags = [item.strip() for item in args.flags.split(",") if item.strip()]
    if not flags:
        raise RuntimeError("--flags must contain at least one diagnostic flag")

    summary_parts = [
        "Runtime reviewed evidence: " + require_text(args.summary, "summary"),
        "Scenario: " + require_text(args.scenario, "scenario"),
        "Flags: " + ", ".join(flags),
        "Native symbols: " + require_text(args.native_symbols, "native-symbols"),
        "Consumed state: " + require_text(args.consumed_state, "consumed-state"),
        "Mutated state: " + require_text(args.mutated_state, "mutated-state"),
        "Docs updated: " + require_text(args.docs_updated, "docs-updated"),
    ]

    entry["proofStatus"] = "runtime-proven"
    entry["gameplayAllowed"] = True
    entry["evidenceSummary"] = " | ".join(summary_parts)
    entry["lastEvidenceArtifact"] = artifact_text(args.evidence_artifact)
    write_json(args.proofs, doc)
    print(f"promoted packet {packet!r} using evidence artifact {entry['lastEvidenceArtifact']}")
    print("Next required steps: regenerate/check Homm3CustomLawPacketGate.cs, build, and update docs with validation evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
