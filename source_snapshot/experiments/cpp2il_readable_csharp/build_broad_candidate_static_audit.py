#!/usr/bin/env python3
"""Audit non-focus candidate rows in the Mono/deobf semantic map."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

FOCUS_PREFIXES = (
    "Hex.Session.Battle",
    "Hex.Session.City",
    "Hex.Session.Data",
    "Hex.Session.Hud",
    "Hex.Session.UI",
    "Hex.UI",
    "Hex.Configs",
    "Hex.Map",
    "Hex.ResManager",
    "Hex.Sound",
    "Hex.Arena",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def is_focus_type(name: str) -> bool:
    return any(name == p or name.startswith(p + ".") for p in FOCUS_PREFIXES)


def reason_value(reasons: list[str], prefix: str) -> str | None:
    for reason in reasons:
        if reason.startswith(prefix):
            return reason
    return None


def classify(row: dict[str, Any], cand: dict[str, Any], focus_type_set: set[str]) -> tuple[str, str, str]:
    mono = row["mono"]["full"]
    deobf = cand["deobf"]["full"]
    reasons = cand.get("reasons") or []
    shared_methods = cand.get("sharedMethodNames") or []
    shared_fields = cand.get("sharedFieldNames") or []
    score = cand.get("score") or 0
    if mono in focus_type_set or deobf in focus_type_set or is_focus_type(mono) or is_focus_type(deobf):
        return (
            "focus-adjacent-candidate",
            "Candidate touches focus prefixes but was not in focusRows; targeted manual review may be worthwhile if gameplay work references it.",
            "targeted-review-if-used",
        )
    if reason_value(reasons, "Hex namespace migration candidate"):
        if score >= 65 and (shared_methods or shared_fields):
            return (
                "non-focus-namespace-migration-plausible",
                "Exact simple name plus Hex namespace migration and some member overlap. Useful as a broad semantic hint only.",
                "leave-candidate-unless-domain-needed",
            )
        return (
            "non-focus-namespace-migration-weak",
            "Exact simple name plus Hex namespace migration, but weak member overlap or low score. No focused gameplay payoff.",
            "leave-candidate-boundary",
        )
    if "." not in mono or mono in {"Data", "Node", "Element", "Condition", "Item", "Battle", "Slots", "LevelUp"}:
        return (
            "global-or-generic-simple-name",
            "Generic simple-name match with limited namespace/member evidence; likely too ambiguous for automatic promotion.",
            "leave-candidate-boundary",
        )
    return (
        "non-focus-simple-name-only",
        "Simple-name candidate outside focus scope without enough independent static evidence for promotion.",
        "leave-candidate-boundary",
    )


def build(map_data: dict[str, Any]) -> dict[str, Any]:
    focus_type_set = {row["mono"]["full"] for row in map_data.get("focusRows") or []}
    focus_type_set.update((row.get("candidates") or [{}])[0].get("deobf", {}).get("full") for row in map_data.get("focusRows") or [])
    rows = []
    for row in map_data.get("rows") or []:
        cand = (row.get("candidates") or [None])[0]
        if not cand or cand.get("confidence") != "candidate":
            continue
        category, rationale, next_action = classify(row, cand, focus_type_set)
        rows.append({
            "mono": row["mono"]["full"],
            "deobf": cand["deobf"]["full"],
            "score": cand.get("score"),
            "category": category,
            "rationale": rationale,
            "nextAction": next_action,
            "reasons": cand.get("reasons") or [],
            "sharedMethodNames": cand.get("sharedMethodNames") or [],
            "sharedFieldNames": cand.get("sharedFieldNames") or [],
            "monoMethodCount": row["mono"].get("methodCount"),
            "deobfMethodCount": cand["deobf"].get("methodCount"),
            "monoFieldCount": row["mono"].get("fieldCount"),
            "deobfFieldCount": cand["deobf"].get("fieldCount"),
        })
    counter = Counter(row["category"] for row in rows)
    action_counter = Counter(row["nextAction"] for row in rows)
    focus_candidates = [row for row in rows if row["category"] == "focus-adjacent-candidate"]
    return {
        "schema": "broad-candidate-static-audit.v1",
        "evidenceBoundary": "Static audit of broad semantic-map candidate rows outside the high-priority focus queue. This classifies remaining candidate-only type aliases; it does not promote them to runtime-safe mappings.",
        "summary": {
            "candidateRows": len(rows),
            "focusAdjacentCandidates": len(focus_candidates),
            "categories": dict(sorted(counter.items())),
            "nextActions": dict(sorted(action_counter.items())),
        },
        "rows": rows,
    }


def write_md(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Broad Candidate Static Audit",
        "",
        "Status: static-only. Runtime-unvalidated.",
        "",
        report["evidenceBoundary"],
        "",
        "## Summary",
        "",
        f"- Candidate rows: `{report['summary']['candidateRows']}`",
        f"- Focus-adjacent candidates: `{report['summary']['focusAdjacentCandidates']}`",
        f"- Categories: `{report['summary']['categories']}`",
        f"- Next actions: `{report['summary']['nextActions']}`",
        "",
        "## Rows",
        "",
        "| Category | Mono | Current deobf | Score | Next action | Rationale |",
        "|---|---|---|---:|---|---|",
    ]
    for row in report["rows"]:
        rationale = row["rationale"].replace("|", "\\|")
        lines.append(f"| `{row['category']}` | `{row['mono']}` | `{row['deobf']}` | {row['score']} | `{row['nextAction']}` | {rationale} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", type=Path, required=True)
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--out-md", type=Path, required=True)
    args = ap.parse_args()
    report = build(load_json(args.map))
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_md(report, args.out_md)
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
