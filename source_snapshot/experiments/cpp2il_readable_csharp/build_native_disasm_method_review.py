#!/usr/bin/env python3
"""Build focused native-disassembly reviews for selected current methods."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def current_method(row: dict[str, Any]) -> str | None:
    side = row.get("reviewedSide")
    if side == "target":
        t, m = row.get("targetType"), row.get("targetMethod")
    else:
        t, m = row.get("callerType"), row.get("callerMethod")
    if not t or not m:
        return None
    return f"{t}::{m}"


def compact_instruction(ins: dict[str, Any]) -> str:
    label = ins.get("targetLabel")
    target = f" -> {label}" if label else ""
    return f"{ins.get('address')} {ins.get('mnemonic')} {ins.get('op_str')}{target}"


def method_matches(label: str, target: str) -> bool:
    return label.startswith(target)


def load_disasm_methods(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    out: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(root.glob("native_disasm_*.json")):
        if "call_graph" in path.name:
            continue
        data = load_json(path)
        for method in data.get("methods") or []:
            out.append((path, method))
    return out


def load_graph_edges(path: Path) -> list[dict[str, Any]]:
    return (load_json(path).get("edges") or [])


def review_method(target: str, methods: list[tuple[Path, dict[str, Any]]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [(path, m) for path, m in methods if method_matches(m.get("label") or "", target)]
    inbound = [e for e in edges if (e.get("targetLabel") or "").startswith(target)]
    outbound = [e for e in edges if (e.get("caller") or "").startswith(target)]
    body_reviews = []
    for path, method in matches:
        instructions = method.get("instructions") or []
        calls = [ins for ins in instructions if ins.get("mnemonic") == "call"]
        branches = [ins for ins in instructions if (ins.get("mnemonic") or "").startswith("j")]
        returns = [ins for ins in instructions if ins.get("mnemonic") == "ret"]
        writes = [ins for ins in instructions if (ins.get("mnemonic") or "") in {"mov", "movups", "movss", "movsd"} and (ins.get("op_str") or "").lstrip().startswith(("byte ptr [", "word ptr [", "dword ptr [", "qword ptr [", "ptr [", "["))]
        call_windows = []
        for idx, ins in enumerate(instructions):
            if ins.get("mnemonic") != "call":
                continue
            start = max(0, idx - 3)
            end = min(len(instructions), idx + 4)
            call_windows.append({
                "call": compact_instruction(ins),
                "window": [compact_instruction(x) for x in instructions[start:end]],
            })
        body_reviews.append({
            "sourceDisasm": str(path),
            "label": method.get("label"),
            "assembly": method.get("assembly"),
            "type": method.get("type"),
            "method": method.get("method"),
            "signature": method.get("signature"),
            "address": method.get("address"),
            "rva": method.get("rva"),
            "length": method.get("length"),
            "instructionCount": method.get("instructionCount"),
            "callCount": len(calls),
            "branchCount": len(branches),
            "returnCount": len(returns),
            "memoryWriteLikeCount": len(writes),
            "directCallTargets": sorted(set((ins.get("targetLabel") or ins.get("op_str") or "") for ins in calls)),
            "callWindows": call_windows[:12],
            "firstInstructions": [compact_instruction(x) for x in instructions[:12]],
            "lastInstructions": [compact_instruction(x) for x in instructions[-8:]],
        })
    if body_reviews and outbound and inbound:
        status = "native-body-inbound-outbound"
    elif body_reviews and outbound:
        status = "native-body-outbound"
    elif body_reviews and inbound:
        status = "native-body-inbound"
    elif body_reviews:
        status = "native-body-only"
    elif outbound or inbound:
        status = "callgraph-only"
    else:
        status = "not-found"
    return {
        "method": target,
        "status": status,
        "bodyMatchCount": len(body_reviews),
        "inboundEdgeCount": len(inbound),
        "outboundEdgeCount": len(outbound),
        "sampleInboundCallers": sorted(set(e.get("caller") or "" for e in inbound))[:12],
        "sampleOutboundTargets": sorted(set((e.get("targetLabel") or e.get("targetOperand") or "") for e in outbound))[:12],
        "bodies": body_reviews,
    }


def write_md(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Native Disassembly Method Review",
        "",
        "Status: static native-disassembly evidence only. Runtime-unvalidated.",
        "",
        report["evidenceBoundary"],
        "",
        "## Summary",
        "",
    ]
    for k, v in report["summary"].items():
        lines.append(f"- `{k}`: {v}")
    lines.append("")
    for row in report.get("rows") or []:
        lines += [f"## {row['method']}", "", f"- Status: `{row['status']}`", f"- Body matches: {row['bodyMatchCount']}", f"- Inbound edges: {row['inboundEdgeCount']}", f"- Outbound edges: {row['outboundEdgeCount']}"]
        if row.get("sampleInboundCallers"):
            lines.append("- Sample inbound callers:")
            for c in row["sampleInboundCallers"][:8]:
                lines.append(f"  - `{c}`")
        if row.get("sampleOutboundTargets"):
            lines.append("- Sample outbound targets:")
            for t in row["sampleOutboundTargets"][:8]:
                lines.append(f"  - `{t}`")
        for body in row.get("bodies") or []:
            lines += ["", f"### Body `{body.get('signature')}`", "", f"- Source: `{body.get('sourceDisasm')}`", f"- Address: `{body.get('address')}` RVA `{body.get('rva')}`", f"- Instructions: {body.get('instructionCount')}; calls: {body.get('callCount')}; branches: {body.get('branchCount')}; returns: {body.get('returnCount')}; write-like moves: {body.get('memoryWriteLikeCount')}"]
            if body.get("directCallTargets"):
                lines.append("- Direct call targets:")
                for t in body["directCallTargets"][:12]:
                    lines.append(f"  - `{t}`")
            if body.get("callWindows"):
                lines.append("- Call windows:")
                for w in body["callWindows"][:6]:
                    lines.append(f"  - `{w['call']}`")
                    for inst in w["window"]:
                        lines.append(f"    - `{inst}`")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", type=Path, required=True)
    ap.add_argument("--disasm-root", type=Path, required=True)
    ap.add_argument("--graph", type=Path, required=True)
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--out-md", type=Path, required=True)
    ap.add_argument("--post-review-action", action="append", default=None, help="Post-review action to include; repeatable. Defaults to native-disasm-review.")
    args = ap.parse_args()
    queue = load_json(args.queue)
    targets = []
    wanted = set(args.post_review_action or ["native-disasm-review"])
    for row in queue.get("rows") or []:
        if row.get("postReviewAction") in wanted:
            target = current_method(row)
            if target and target not in targets:
                targets.append(target)
    methods = load_disasm_methods(args.disasm_root)
    edges = load_graph_edges(args.graph)
    rows = [review_method(target, methods, edges) for target in targets]
    summary: dict[str, int] = {}
    for row in rows:
        summary[row["status"]] = summary.get(row["status"], 0) + 1
    report = {
        "schema": "native-disasm-method-review.v1",
        "evidenceBoundary": "Exact current native disassembly plus direct-call graph evidence. This improves static body/callsite confidence but does not prove managed high-level intent, runtime invocation order, or hook safety.",
        "queue": str(args.queue),
        "graph": str(args.graph),
        "summary": summary,
        "rows": rows,
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_md(report, args.out_md)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

