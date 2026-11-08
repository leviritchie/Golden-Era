#!/usr/bin/env python3
"""Audit focusRows that remain probable-static in the Mono/deobf semantic map."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def metric(reasons: list[str], name: str) -> float:
    pat = re.compile(re.escape(name) + r" ([0-9.]+)")
    for reason in reasons:
        m = pat.search(reason)
        if m:
            return float(m.group(1))
    return 0.0


def classify(mono: str, deobf: str, cand: dict[str, Any]) -> tuple[str, str, str]:
    reasons = cand.get("reasons") or []
    score = float(cand.get("score") or 0)
    method_overlap = metric(reasons, "method-name overlap")
    field_close = metric(reasons, "field-count closeness")
    param_sim = metric(reasons, "param-count histogram similarity")
    shared_methods = cand.get("sharedMethodNames") or []
    shared_fields = cand.get("sharedFieldNames") or []
    if mono.startswith("Hex.Session.City.Building") and deobf.startswith("Hex.Session.Data.Building"):
        if score >= 75 or field_close >= 0.5 or method_overlap >= 0.25:
            return (
                "building-data-migration-supported",
                "City building type migrated to Session.Data with exact simple name and enough member/shape overlap for type identity.",
                "method-level-review-if-hooked",
            )
        return (
            "building-data-migration-weak",
            "City building type migrated to Session.Data by exact simple name, but member overlap is thin.",
            "type-alias-only",
        )
    if mono.startswith("Hex.Session.Logic.") and deobf.startswith("Hex.Session.Data."):
        if shared_fields or score >= 70 or param_sim >= 0.45:
            return (
                "logic-to-data-migration-supported",
                "Session.Logic data-holder appears migrated into Session.Data with exact simple name and acceptable shape evidence.",
                "method-level-review-if-hooked",
            )
        return (
            "logic-to-data-migration-weak",
            "Session.Logic to Session.Data exact simple-name migration is plausible, but method/field overlap is low.",
            "type-alias-only",
        )
    if mono.startswith("Hex.BhMagic") or "BhMagic" in mono or "BhMagic" in deobf:
        return (
            "magic-ui-migration-supported",
            "Magic UI type has high method/member overlap and exact simple name across namespace migration.",
            "safe-static-type-alias",
        )
    if score >= 100 and (method_overlap >= 0.8 or field_close >= 0.8):
        return (
            "strong-probable-shell-match",
            "Probable-static only because namespace differs, but member shape is effectively exact.",
            "safe-static-type-alias",
        )
    if score >= 70 and (field_close >= 0.5 or method_overlap >= 0.25 or shared_fields):
        return (
            "probable-type-alias-supported",
            "Exact simple-name migration with enough member shape evidence for type-level use.",
            "method-level-review-if-hooked",
        )
    return (
        "probable-type-alias-weak",
        "Exact simple-name migration is plausible, but current static evidence is not enough for method-level assumptions.",
        "type-alias-only",
    )


def build(data: dict[str, Any]) -> dict[str, Any]:
    rows=[]
    for row in data.get("focusRows") or []:
        cand=(row.get("candidates") or [None])[0]
        if not cand or cand.get("confidence") != "probable-static":
            continue
        mono=row["mono"]["full"]
        deobf=cand["deobf"]["full"]
        category,rationale,next_action=classify(mono,deobf,cand)
        reasons=cand.get("reasons") or []
        rows.append({
            "mono": mono,
            "deobf": deobf,
            "score": cand.get("score"),
            "category": category,
            "rationale": rationale,
            "nextAction": next_action,
            "methodNameOverlap": metric(reasons, "method-name overlap"),
            "fieldCountCloseness": metric(reasons, "field-count closeness"),
            "paramCountSimilarity": metric(reasons, "param-count histogram similarity"),
            "sharedMethodNames": cand.get("sharedMethodNames") or [],
            "sharedFieldNames": cand.get("sharedFieldNames") or [],
            "reasons": reasons,
        })
    categories=Counter(r["category"] for r in rows)
    actions=Counter(r["nextAction"] for r in rows)
    return {
        "schema":"focus-probable-static-audit.v1",
        "evidenceBoundary":"Static audit of focusRows whose top candidate is probable-static. These are type-alias confidence classifications only; method-level behavior still requires dossiers/native review if used for hooks.",
        "summary":{"rows":len(rows),"categories":dict(sorted(categories.items())),"nextActions":dict(sorted(actions.items()))},
        "rows":rows,
    }


def write_md(report: dict[str, Any], path: Path) -> None:
    lines=["# Focus Probable-Static Audit","","Status: static-only. Runtime-unvalidated.","",report["evidenceBoundary"],"","## Summary","",f"- Rows: `{report['summary']['rows']}`",f"- Categories: `{report['summary']['categories']}`",f"- Next actions: `{report['summary']['nextActions']}`","","## Rows","","| Category | Mono | Current deobf | Score | Next action | Rationale |","|---|---|---|---:|---|---|"]
    for r in report["rows"]:
        lines.append(f"| `{r['category']}` | `{r['mono']}` | `{r['deobf']}` | {r['score']} | `{r['nextAction']}` | {r['rationale']} |")
    path.write_text("\n".join(lines)+"\n",encoding="utf-8")


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--map",type=Path,required=True)
    ap.add_argument("--out-json",type=Path,required=True)
    ap.add_argument("--out-md",type=Path,required=True)
    args=ap.parse_args()
    report=build(load_json(args.map))
    args.out_json.parent.mkdir(parents=True,exist_ok=True)
    args.out_json.write_text(json.dumps(report,indent=2),encoding="utf-8")
    write_md(report,args.out_md)
    print(json.dumps(report["summary"],indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
