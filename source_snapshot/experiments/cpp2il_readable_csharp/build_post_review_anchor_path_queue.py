#!/usr/bin/env python3
"""Build a review-aware unresolved static queue for Mono/deobf anchor paths."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def key(path: str | None, current: str | None) -> tuple[str, str]:
    return (path or "", current or "")


def action_key(row: dict[str, Any], side: str = "caller") -> tuple[str, str]:
    if side == "target":
        current = f"{row.get('targetType') or ''}::{row.get('targetMethod') or ''}"
    else:
        current = f"{row.get('callerType') or ''}::{row.get('callerMethod') or ''}"
    return key(row.get("path"), current)


def index_reviews(confirm: dict[str, Any], action_review: dict[str, Any], missing_native: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    reviews: dict[tuple[str, str], dict[str, Any]] = {}
    for row in confirm.get("rows") or []:
        reviews[key(row.get("path"), row.get("current"))] = {
            "reviewSource": "confirm_ordinal_candidate_static_review",
            "status": row.get("outcome"),
            "evidence": row.get("evidence"),
        }
    for section_name in ("bodyXref", "targetEndpoint"):
        section = action_review.get(section_name) or {}
        for bucket in ("rows", "missing"):
            for row in section.get(bucket) or []:
                reviews[key(row.get("path"), row.get("current"))] = {
                    "reviewSource": f"high_priority_action_static_review.{section_name}.{bucket}",
                    "status": row.get("status"),
                    "evidence": row.get("evidence"),
                }
    for row in missing_native.get("rows") or []:
        # Attach by current method only when path-specific review already marked missing-isil.
        method = row.get("method")
        for existing_key, existing in list(reviews.items()):
            if existing_key[1] == method and existing.get("status") == "missing-isil":
                existing["nativeSupplement"] = {
                    "source": "missing_isil_native_callgraph_supplement",
                    "status": row.get("status"),
                    "outboundEdgeCount": row.get("outboundEdgeCount"),
                    "inboundEdgeCount": row.get("inboundEdgeCount"),
                    "sampleTargets": row.get("sampleTargets") or [],
                    "sampleCallers": row.get("sampleCallers") or [],
                }
    return reviews


def classify(original: dict[str, Any], review: dict[str, Any] | None) -> tuple[str, str, bool]:
    if not review:
        return original.get("action") or "review", "No post-review evidence matched this row; keep original action.", True
    status = review.get("status")
    native = review.get("nativeSupplement")
    if status == "supported-static":
        return "resolved-static", "Static review supports this current/Mono mapping; remaining gaps are runtime reachability/order or hook safety, not more static identity work.", False
    if status == "weak-static":
        return "deepen-weak-static", "Static review found adjacent evidence but not exact semantics; inspect native call graph, neighboring callers/callees, or generated interop metadata.", True
    if status == "likely-misnamed":
        return "reject-or-remap", "Static review contradicts the Mono method name; reject this alias or search neighbor methods for the intended semantic.", True
    if status == "missing-isil" and native:
        return "native-disasm-review", "ISIL body is absent, but exact native callgraph evidence exists; next static step is native instruction/callsite interpretation.", True
    if status == "missing-isil":
        return "recover-body-source", "ISIL body is absent and no native supplement is attached; use method pointers/native disassembly or refreshed ISIL if available.", True
    return "review", f"Unhandled review status {status!r}; inspect manually.", True


def build_report(actions: dict[str, Any], reviews: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    resolved_counter: Counter[str] = Counter()
    for row in actions.get("rows") or []:
        side = "target" if row.get("action") == "target-endpoint-or-runtime-order" else "caller"
        row_key = action_key(row, side=side)
        review = reviews.get(row_key)
        status, rationale, unresolved = classify(row, review)
        out = dict(row)
        out["postReviewAction"] = status
        out["postReviewRationale"] = rationale
        out["review"] = review
        out["reviewedSide"] = side
        if unresolved:
            rows.append(out)
            counters[status] += 1
        else:
            resolved.append(out)
            resolved_counter[status] += 1
    return {
        "schema": "post-review-anchor-path-static-queue.v1",
        "evidenceBoundary": "Static-only review-aware queue. Resolved-static means no further static identity/body evidence is currently required; it does not prove runtime behavior, call order, or hook safety.",
        "inputs": {
            "actions": "unresolved_anchor_path_actions_high_priority.json",
            "confirmReview": "confirm_ordinal_candidate_static_review.json",
            "actionReview": "high_priority_action_static_review.json",
            "missingIsilNativeSupplement": "missing_isil_native_callgraph_supplement.json",
        },
        "summary": {
            "unresolvedRows": len(rows),
            "resolvedRows": len(resolved),
            "unresolvedActions": dict(sorted(counters.items())),
            "resolvedActions": dict(sorted(resolved_counter.items())),
        },
        "rows": rows,
        "resolvedRows": resolved,
    }


def write_md(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Post-Review High-Priority Static Queue",
        "",
        "Status: static-only. Runtime-unvalidated.",
        "",
        report["evidenceBoundary"],
        "",
        "## Summary",
        "",
        f"- Unresolved rows: `{report['summary']['unresolvedRows']}`",
        f"- Resolved static rows: `{report['summary']['resolvedRows']}`",
        f"- Unresolved actions: `{report['summary']['unresolvedActions']}`",
        f"- Resolved actions: `{report['summary']['resolvedActions']}`",
        "",
        "## Unresolved rows",
        "",
        "| Post-review action | Path | Current | Prior action | Review status | Next static action |",
        "|---|---|---|---|---|---|",
    ]
    for row in report.get("rows") or []:
        side = row.get("reviewedSide")
        if side == "target":
            current = f"{row.get('targetType') or '-'}::{row.get('targetMethod') or '-'}"
        else:
            current = f"{row.get('callerType') or '-'}::{row.get('callerMethod') or '-'}"
        review = row.get("review") or {}
        native = review.get("nativeSupplement") or {}
        review_status = review.get("status") or "unreviewed"
        if native:
            review_status += f" + {native.get('status')}"
        rationale = (row.get("postReviewRationale") or "-").replace("|", "\\|")
        lines.append(f"| `{row.get('postReviewAction')}` | `{row.get('path')}` | `{current}` | `{row.get('action')}` | `{review_status}` | {rationale} |")
    lines += ["", "## Resolved static rows", "", "| Path | Current | Prior action | Evidence boundary |", "|---|---|---|---|"]
    for row in report.get("resolvedRows") or []:
        side = row.get("reviewedSide")
        current = f"{row.get('targetType') or '-'}::{row.get('targetMethod') or '-'}" if side == "target" else f"{row.get('callerType') or '-'}::{row.get('callerMethod') or '-'}"
        lines.append(f"| `{row.get('path')}` | `{current}` | `{row.get('action')}` | Static identity/body endpoint strengthened; runtime/order remains out of scope. |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--actions", type=Path, required=True)
    ap.add_argument("--confirm-review", type=Path, required=True)
    ap.add_argument("--action-review", type=Path, required=True)
    ap.add_argument("--missing-isil-native", type=Path, required=True)
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--out-md", type=Path, required=True)
    args = ap.parse_args()
    reviews = index_reviews(load_json(args.confirm_review), load_json(args.action_review), load_json(args.missing_isil_native))
    report = build_report(load_json(args.actions), reviews)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_md(report, args.out_md)
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
