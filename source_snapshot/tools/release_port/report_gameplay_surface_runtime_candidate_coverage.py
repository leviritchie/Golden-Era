#!/usr/bin/env python3
"""Report generated/runtime candidate coverage for implementation-relevant surfaces.

Implementation-relevant means the surface is tied to at least one custom-law
packet and is not rejected. The report distinguishes runtime-symbol candidates
from weaker static dossier coverage, so implementation agents can see where a
surface is ready for runtime metadata reconciliation versus only static planning.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATRIX = ROOT / "custom_factions" / "gameplay_surface_evidence_matrix.json"
DEFAULT_DOSSIER_INDEX = ROOT / "custom_factions" / "gameplay_surface_weak_dossier_index.json"
DEFAULT_OUT_JSON = ROOT / "custom_factions" / "gameplay_surface_runtime_candidate_coverage.json"
DEFAULT_OUT_MD = ROOT / "docs" / "gameplay_surface_runtime_candidate_coverage.md"
IMPLEMENTATION_STATUSES = {"candidate", "partial", "missing", "runtime-unproven", "proven-live-metadata"}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def dossier_statuses(index_doc: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for row in index_doc.get("surfaces", []):
        if not isinstance(row, dict):
            continue
        surface_id = row.get("surfaceId")
        if not isinstance(surface_id, str):
            continue
        result[surface_id] = [
            dossier.get("status")
            for dossier in row.get("dossiers", [])
            if isinstance(dossier, dict) and isinstance(dossier.get("status"), str)
        ]
    return result


def coverage_level(surface: dict[str, Any], statuses: list[str]) -> str:
    if surface.get("runtimeSymbolCandidates"):
        return "runtime-candidate"
    if surface.get("status") == "proven-live-metadata":
        return "live-metadata-proven"
    if "built" in statuses:
        return "method-dossier-only"
    if "declaration-only" in statuses:
        return "declaration-only"
    return "no-generated-or-dossier-candidate"


def build_report(matrix_doc: dict[str, Any], index_doc: dict[str, Any]) -> dict[str, Any]:
    statuses_by_surface = dossier_statuses(index_doc)
    rows: list[dict[str, Any]] = []
    for surface_id, surface in sorted(matrix_doc.get("surfaces", {}).items()):
        if not isinstance(surface, dict):
            continue
        packets = surface.get("packets", [])
        if not packets or surface.get("status") == "rejected":
            continue
        if surface.get("status") not in IMPLEMENTATION_STATUSES and not surface.get("runtimeSymbolCandidates"):
            continue
        statuses = statuses_by_surface.get(surface_id, [])
        candidates = surface.get("runtimeSymbolCandidates", [])
        rows.append(
            {
                "surfaceId": surface_id,
                "domain": surface.get("domain"),
                "status": surface.get("status"),
                "packets": packets,
                "coverageLevel": coverage_level(surface, statuses),
                "runtimeCandidateCount": len(candidates) if isinstance(candidates, list) else 0,
                "dossierStatuses": statuses,
                "nextProofAction": surface.get("nextProofAction"),
                "boundary": (
                    "Runtime candidates are static/generated candidates only; they still require bridge/native/runtime reconciliation."
                    if candidates
                    else "No runtime candidate is attached; use dossier coverage to resolve exact generated/runtime identity before implementation."
                ),
            }
        )

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["coverageLevel"]] = counts.get(row["coverageLevel"], 0) + 1
    return {
        "schemaVersion": 1,
        "purpose": "Generated/runtime candidate coverage report for packet-linked gameplay surfaces.",
        "generationBoundary": "Static planning only. Candidate presence is not runtime proof or hook safety proof.",
        "implementationRelevantSurfaceCount": len(rows),
        "coverageCounts": counts,
        "surfaces": rows,
    }


def write_md(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Gameplay Surface Runtime Candidate Coverage",
        "",
        "Boundary: static planning only. Runtime candidates here are not runtime proof, hook safety proof, or gameplay authorization.",
        "",
        f"Implementation-relevant surface count: `{report['implementationRelevantSurfaceCount']}`",
        "",
        "## Coverage Counts",
        "",
        "| Coverage level | Count |",
        "| --- | ---: |",
    ]
    for level, count in sorted(report["coverageCounts"].items()):
        lines.append(f"| `{level}` | {count} |")
    lines.extend(
        [
            "",
            "## Surfaces",
            "",
            "| Surface | Domain | Status | Runtime candidates | Dossier statuses | Coverage |",
            "| --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for row in report["surfaces"]:
        statuses = ", ".join(f"`{status}`" for status in row.get("dossierStatuses", [])) or ""
        lines.append(
            f"| `{row['surfaceId']}` | {row.get('domain')} | {row.get('status')} | "
            f"{row.get('runtimeCandidateCount', 0)} | {statuses} | `{row.get('coverageLevel')}` |"
        )
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--dossier-index", type=Path, default=DEFAULT_DOSSIER_INDEX)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    args = parser.parse_args()

    matrix = load_json(args.matrix)
    index = load_json(args.dossier_index)
    report = build_report(matrix, index)
    dump_json(args.out_json, report)
    write_md(args.out_md, report)
    print(
        "gameplay surface runtime candidate coverage report written "
        f"({report['implementationRelevantSurfaceCount']} implementation-relevant surface(s))"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
