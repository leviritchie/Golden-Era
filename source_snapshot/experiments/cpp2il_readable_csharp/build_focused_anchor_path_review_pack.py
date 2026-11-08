#!/usr/bin/env python3
"""Build focused review dossiers for high-priority native anchor paths.

This joins three existing static artifacts:
- native anchor path dossiers with instruction context,
- heuristic anchor path triage,
- native call graph edges annotated with Mono semantic aliases.

It does not perform new decompilation, runtime probing, or semantic inference.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def path_key(source: str, target: str) -> str:
    return f"{source}->{target}"


def edge_key(caller: str | None, call_address: str | None, target_label: str | None) -> tuple[str | None, str | None, str | None]:
    return (caller, call_address, target_label)


def compact_alias(alias: dict[str, Any] | None) -> dict[str, Any] | None:
    if not alias:
        return None
    out = {
        "monoType": alias.get("monoType"),
        "confidence": alias.get("confidence"),
        "source": alias.get("source"),
    }
    if alias.get("score") is not None:
        out["score"] = alias.get("score")
    if alias.get("reasons"):
        out["reasons"] = alias.get("reasons")[:4]
    return out


def compact_method_alias(alias: dict[str, Any] | None) -> dict[str, Any] | None:
    if not alias:
        return None
    keys = ["deobfMethod", "monoMethod", "confidence", "source", "score", "ordinal", "evidenceBoundary"]
    out = {key: alias.get(key) for key in keys if alias.get(key) is not None}
    if alias.get("reasons"):
        out["reasons"] = alias.get("reasons")[:4]
    return out


def instruction_window(step: dict[str, Any]) -> list[dict[str, Any]]:
    ctx = ((step.get("callInstructionContext") or {}).get("context") or [])
    out = []
    for ins in ctx:
        out.append({
            "address": ins.get("address"),
            "mnemonic": ins.get("mnemonic"),
            "op_str": ins.get("op_str"),
            "targetLabel": ins.get("targetLabel"),
        })
    return out


def classify_gap(step: dict[str, Any], annotated: dict[str, Any] | None) -> str:
    if not annotated:
        return "missing annotated graph edge; check graph/dossier key drift"
    caller_method_alias = annotated.get("callerMethodMonoAlias") or {}
    target_method_alias = annotated.get("targetMethodMonoAlias") or {}
    caller_method = annotated.get("callerMethod")
    if caller_method_alias.get("confidence") == "strong-static" and target_method_alias.get("confidence") == "strong-static":
        return "both endpoint methods have exact-name static aliases; runtime reachability/order still unproven"
    if caller_method_alias.get("confidence") == "strong-static":
        return "caller method has exact-name static alias; target method alias is absent or candidate-only"
    if caller_method_alias:
        mono_method = caller_method_alias.get("monoMethod")
        reasons = caller_method_alias.get("reasons") or []
        if mono_method == ".ctor" and caller_method != ".ctor":
            return "ordinal candidate is likely noisy: non-constructor current method maps to Mono .ctor"
        if any("parameter count differs" in str(reason) for reason in reasons):
            return "ordinal candidate has parameter-count mismatch; needs body/xref confirmation before use"
        return "caller method alias is ordinal candidate only; needs method-body/xref confirmation before implementation use"
    if annotated.get("callerMonoAlias"):
        return "caller type alias exists, but caller method alias is not resolved"
    return "caller type is unmapped; focused Mono/current type dossier would improve this path"


def build_pack(triage: dict[str, Any], dossiers: dict[str, Any], annotated_graph: dict[str, Any], limit: int) -> dict[str, Any]:
    triage_rows = [row for row in triage.get("rows") or [] if row.get("priority") == "high"]
    if limit > 0:
        triage_rows = triage_rows[:limit]
    triage_by_key = {path_key(row.get("source"), row.get("target")): row for row in triage_rows}
    dossier_by_key = {path_key(row.get("source"), row.get("target")): row for row in dossiers.get("dossiers") or []}
    edge_by_key = {
        edge_key(edge.get("caller"), edge.get("callAddress"), edge.get("targetLabel")): edge
        for edge in annotated_graph.get("edges") or []
    }
    rows = []
    gap_counter: Counter[str] = Counter()
    confidence_counter: Counter[str] = Counter()
    missing_dossiers = []
    missing_edges = 0
    unmapped_callers: dict[str, list[str]] = {}
    for key, triage_row in triage_by_key.items():
        dossier = dossier_by_key.get(key)
        if not dossier:
            missing_dossiers.append(key)
            continue
        steps = []
        for step in dossier.get("steps") or []:
            annotated = edge_by_key.get(edge_key(step.get("caller"), step.get("callAddress"), step.get("targetLabel")))
            if not annotated:
                missing_edges += 1
            gap = classify_gap(step, annotated)
            gap_counter[gap] += 1
            if annotated and (annotated.get("callerMethodMonoAlias") or {}).get("confidence"):
                confidence_counter[(annotated.get("callerMethodMonoAlias") or {}).get("confidence")] += 1
            if annotated and not annotated.get("callerMonoAlias") and annotated.get("callerType"):
                unmapped_callers.setdefault(annotated.get("callerType"), []).append(key)
            steps.append({
                "caller": step.get("caller"),
                "callAddress": step.get("callAddress"),
                "targetLabel": step.get("targetLabel"),
                "targetOperand": step.get("targetOperand"),
                "callerMethodAddress": (step.get("callerMethod") or {}).get("address"),
                "callerMethodSignature": (step.get("callerMethod") or {}).get("signature"),
                "callerType": (annotated or {}).get("callerType"),
                "callerMethod": (annotated or {}).get("callerMethod"),
                "targetType": (annotated or {}).get("targetType"),
                "targetMethod": (annotated or {}).get("targetMethod"),
                "callerMonoAlias": compact_alias((annotated or {}).get("callerMonoAlias")),
                "targetMonoAlias": compact_alias((annotated or {}).get("targetMonoAlias")),
                "callerMethodMonoAlias": compact_method_alias((annotated or {}).get("callerMethodMonoAlias")),
                "targetMethodMonoAlias": compact_method_alias((annotated or {}).get("targetMethodMonoAlias")),
                "instructionWindow": instruction_window(step),
                "staticGap": gap,
            })
        rows.append({
            "path": key,
            "source": triage_row.get("source"),
            "target": triage_row.get("target"),
            "category": triage_row.get("category"),
            "priority": triage_row.get("priority"),
            "score": triage_row.get("score"),
            "triageReasons": triage_row.get("reasons") or [],
            "domainHits": triage_row.get("domainHits") or {},
            "depth": dossier.get("depth"),
            "steps": steps,
        })
    return {
        "schema": "focused-anchor-path-review-pack.v1",
        "evidenceBoundary": "Static-only focused review pack over high-priority native anchor paths. Native call context and Mono aliases are evidence for candidate mapping only; this does not prove runtime reachability, invocation order, managed semantics, or hook safety.",
        "inputs": {
            "triage": triage.get("inputDossiers"),
            "dossiers": dossiers.get("matrix"),
            "annotatedGraphSchema": annotated_graph.get("schema"),
        },
        "summary": {
            "paths": len(rows),
            "steps": sum(len(row.get("steps") or []) for row in rows),
            "missingDossiers": len(missing_dossiers),
            "missingAnnotatedEdges": missing_edges,
            "callerMethodAliasConfidence": dict(sorted(confidence_counter.items())),
            "staticGaps": dict(sorted(gap_counter.items())),
        },
        "missingDossiers": missing_dossiers,
        "unmappedCallerTypes": [{"currentType": current_type, "paths": sorted(set(paths))} for current_type, paths in sorted(unmapped_callers.items())],
        "rows": rows,
    }


def write_md(data: dict[str, Any], path: Path) -> None:
    lines = [
        "# Focused High-Priority Anchor Path Review Pack",
        "",
        "Status: static-only. Runtime-unvalidated.",
        "",
        data["evidenceBoundary"],
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key, value in data.get("summary", {}).items():
        if isinstance(value, dict):
            continue
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "### Caller method alias confidence", "", "| Confidence | Steps |", "|---|---:|"])
    for key, value in (data.get("summary", {}).get("callerMethodAliasConfidence") or {}).items():
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "### Static gaps", "", "| Gap | Steps |", "|---|---:|"])
    for key, value in (data.get("summary", {}).get("staticGaps") or {}).items():
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "## Unmapped high-priority caller types", "", "| Current type | Paths |", "|---|---|"])
    for row in data.get("unmappedCallerTypes") or []:
        paths = ", ".join(f"`{p}`" for p in row.get("paths", []))
        lines.append(f"| `{row['currentType']}` | {paths} |")
    lines.extend(["", "## Paths", ""])
    for row in data.get("rows") or []:
        lines.append(f"### `{row['path']}`")
        reasons = "; ".join((row.get("triageReasons") or [])[:4])
        lines.append("")
        lines.append(f"Priority/category: `{row.get('priority')}` / `{row.get('category')}`; score `{row.get('score')}`; depth `{row.get('depth')}`.")
        lines.append(f"Triage reasons: {reasons}")
        lines.append("")
        lines.append("| Step | Caller | Caller Mono | Caller method Mono | Target | Target Mono | Gap |")
        lines.append("|---:|---|---|---|---|---|---|")
        for i, step in enumerate(row.get("steps") or [], 1):
            caller = step.get("caller") or "-"
            target = step.get("targetLabel") or "-"
            caller_alias = step.get("callerMonoAlias") or {}
            target_alias = step.get("targetMonoAlias") or {}
            caller_method = step.get("callerMethodMonoAlias") or {}
            caller_mono = caller_alias.get("monoType") or "-"
            target_mono = target_alias.get("monoType") or "-"
            method_mono = caller_method.get("monoMethod") or "-"
            method_conf = caller_method.get("confidence") or "-"
            gap = (step.get("staticGap") or "-").replace("|", "\\|")
            lines.append(f"| {i} | `{caller}` | `{caller_mono}` | `{method_mono}` ({method_conf}) | `{target}` | `{target_mono}` | {gap} |")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--triage", type=Path, required=True)
    ap.add_argument("--dossiers", type=Path, required=True)
    ap.add_argument("--annotated-graph", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=0, help="Limit high-priority paths; 0 means all.")
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--out-md", type=Path, required=True)
    args = ap.parse_args()
    data = build_pack(load_json(args.triage), load_json(args.dossiers), load_json(args.annotated_graph), args.limit)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    write_md(data, args.out_md)
    print(json.dumps({"outJson": str(args.out_json), "outMd": str(args.out_md), "summary": data["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



