#!/usr/bin/env python3
"""Audit whether the Mono/deobf static map has remaining broad static-improvement queues."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED = {
    "semanticMap": "mono_deobf_semantic_map.json",
    "focusedPack": "focused_anchor_path_review_pack_high_priority.json",
    "postReviewQueue": "post_review_anchor_path_static_queue.json",
    "postNativeCoverage": "post_native_static_coverage.json",
    "semanticInterpretation": "static_semantic_interpretation_review.json",
    "broadCandidateAudit": "broad_candidate_static_audit.json",
    "focusAdjacentBroadReview": "focus_adjacent_broad_candidate_review.json",
    "focusProbableAudit": "focus_probable_static_audit.json",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build(root: Path) -> dict[str, Any]:
    loaded: dict[str, dict[str, Any]] = {}
    missing = []
    for key, name in REQUIRED.items():
        path = root / name
        if not path.exists():
            missing.append(str(path))
            continue
        loaded[key] = load_json(path)
    findings = []
    blockers = []
    if missing:
        blockers.append({"requirement": "required artifacts exist", "status": "missing", "details": missing})
    semantic = loaded.get("semanticMap", {})
    sem_summary = semantic.get("summary") or {}
    if sem_summary.get("weakCandidate") != 0:
        blockers.append({"requirement": "no weak broad type candidates", "status": "failed", "details": sem_summary.get("weakCandidate")})
    findings.append({
        "requirement": "broad type-map generated and counted",
        "status": "proven-static",
        "evidence": sem_summary,
        "boundary": "Type-level map only. Method behavior requires separate evidence.",
    })
    focus_rows = semantic.get("focusRows") or []
    focus_conf = {}
    for row in focus_rows:
        cand = (row.get("candidates") or [{}])[0]
        focus_conf[cand.get("confidence")] = focus_conf.get(cand.get("confidence"), 0) + 1
    if focus_conf.get("candidate", 0) or focus_conf.get("weak-candidate", 0):
        blockers.append({"requirement": "focus rows have no candidate/weak-candidate aliases", "status": "failed", "details": focus_conf})
    findings.append({
        "requirement": "focus type aliases bounded",
        "status": "proven-static",
        "evidence": focus_conf,
        "boundary": "Probable-static focus aliases are type-level unless separately reviewed.",
    })
    interp = loaded.get("semanticInterpretation", {})
    interp_summary = interp.get("summary") or {}
    if interp_summary.get("missingInterpretations") != 0 or interp_summary.get("rows") != 23:
        blockers.append({"requirement": "high-priority cautious rows semantically interpreted", "status": "failed", "details": interp_summary})
    findings.append({
        "requirement": "high-priority post-native semantic interpretations complete",
        "status": "proven-static",
        "evidence": interp_summary,
        "boundary": "Runtime reachability/order/hook safety remain outside static map proof.",
    })
    coverage = loaded.get("postNativeCoverage", {})
    cov_summary = coverage.get("summary") or {}
    if cov_summary.get("unresolvedRowsMissingNativeBodyReview") != 0:
        blockers.append({"requirement": "all post-review rows have native body review", "status": "failed", "details": cov_summary})
    findings.append({
        "requirement": "post-review high-priority rows have native body coverage",
        "status": "proven-static",
        "evidence": cov_summary,
        "boundary": "Native disassembly body evidence is static and does not reconstruct full managed semantics.",
    })
    broad = loaded.get("broadCandidateAudit", {})
    broad_summary = broad.get("summary") or {}
    if broad_summary.get("focusAdjacentCandidates") != 3 or broad_summary.get("candidateRows") != 22:
        blockers.append({"requirement": "broad candidate audit covers expected rows", "status": "failed", "details": broad_summary})
    findings.append({
        "requirement": "broad candidate aliases classified",
        "status": "proven-static",
        "evidence": broad_summary,
        "boundary": "Most remaining broad candidates are non-focus/generic and left as candidate-boundary unless a domain need appears.",
    })
    focus_adj = loaded.get("focusAdjacentBroadReview", {})
    focus_adj_summary = focus_adj.get("summary") or {}
    if focus_adj_summary.get("rows") != 3:
        blockers.append({"requirement": "focus-adjacent broad candidates reviewed", "status": "failed", "details": focus_adj_summary})
    findings.append({
        "requirement": "focus-adjacent broad candidates reviewed",
        "status": "proven-static",
        "evidence": focus_adj_summary,
        "boundary": "MapBonus remains shell-only with current artifacts; not a hidden queue.",
    })
    probable = loaded.get("focusProbableAudit", {})
    probable_summary = probable.get("summary") or {}
    if probable_summary.get("rows") != 36:
        blockers.append({"requirement": "focus probable rows classified", "status": "failed", "details": probable_summary})
    findings.append({
        "requirement": "focus probable-static rows classified",
        "status": "proven-static",
        "evidence": probable_summary,
        "boundary": "Probable rows are type-alias evidence; method-level use remains target-dependent.",
    })
    boundary_items = [
        "runtime reachability/order/hook safety cannot be proven statically",
        "targeted method-level reviews are still possible when a future hook/domain names a method",
        "refreshed/fuller ISIL export could improve shell-only rows such as Hex.Map.MapBonus",
        "new external semantic anchors could improve non-focus/generic candidate rows",
    ]
    decision = "static-boundary-reached" if not blockers else "incomplete"
    return {
        "schema": "static-map-completion-boundary-audit.v1",
        "evidenceBoundary": "Completion audit for the current broad Mono-demo to Golden-Era static map. This proves the broad static queues are classified/exhausted with current artifacts; it does not prove runtime behavior or forbid future target-specific static reviews.",
        "decision": decision,
        "summary": {
            "blockers": len(blockers),
            "findings": len(findings),
            "semanticMap": sem_summary,
            "focusConfidence": focus_conf,
            "highPriorityInterpretation": interp_summary,
            "postNativeCoverage": cov_summary,
            "broadCandidateAudit": broad_summary,
            "focusProbableAudit": probable_summary,
        },
        "findings": findings,
        "blockers": blockers,
        "staticBoundaryNotCompletionOf": boundary_items,
    }


def write_md(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Static Map Completion Boundary Audit",
        "",
        "Status: static-only. Runtime-unvalidated.",
        "",
        report["evidenceBoundary"],
        "",
        f"Decision: `{report['decision']}`",
        "",
        "## Summary",
        "",
        f"- Blockers: `{report['summary']['blockers']}`",
        f"- Findings: `{report['summary']['findings']}`",
        f"- Semantic map: `{report['summary']['semanticMap']}`",
        f"- Focus confidence: `{report['summary']['focusConfidence']}`",
        f"- High-priority interpretation: `{report['summary']['highPriorityInterpretation']}`",
        f"- Post-native coverage: `{report['summary']['postNativeCoverage']}`",
        f"- Broad candidate audit: `{report['summary']['broadCandidateAudit']}`",
        f"- Focus probable audit: `{report['summary']['focusProbableAudit']}`",
        "",
        "## Findings",
        "",
        "| Requirement | Status | Evidence | Boundary |",
        "|---|---|---|---|",
    ]
    for finding in report["findings"]:
        evidence = str(finding.get("evidence")).replace("|", "\\|")
        boundary = str(finding.get("boundary")).replace("|", "\\|")
        lines.append(f"| {finding['requirement']} | `{finding['status']}` | `{evidence}` | {boundary} |")
    lines.extend(["", "## Remaining non-static or target-dependent boundaries", ""])
    for item in report["staticBoundaryNotCompletionOf"]:
        lines.append(f"- {item}")
    if report["blockers"]:
        lines.extend(["", "## Blockers", ""])
        for blocker in report["blockers"]:
            lines.append(f"- `{blocker['requirement']}`: {blocker.get('details')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--out-md", type=Path, required=True)
    args = ap.parse_args()
    report = build(args.root)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_md(report, args.out_md)
    print(json.dumps({"decision": report["decision"], "summary": report["summary"]}, indent=2))
    return 0 if report["decision"] == "static-boundary-reached" else 1


if __name__ == "__main__":
    raise SystemExit(main())
