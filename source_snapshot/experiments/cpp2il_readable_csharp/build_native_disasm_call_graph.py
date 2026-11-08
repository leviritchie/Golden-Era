#!/usr/bin/env python3
"""Build a static direct-call graph from native method disassembly packs."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_pack(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["_path"] = str(path)
    return data


def caller_label(method: dict[str, Any]) -> str:
    return method.get("label") or f"{method.get('type','-')}::{method.get('method','-')}"


def build_graph(packs: list[dict[str, Any]]) -> dict[str, Any]:
    edges: list[dict[str, Any]] = []
    caller_counts = Counter()
    target_counts = Counter()
    unresolved_counts = Counter()
    for pack in packs:
        source = pack.get("_path")
        for method in pack.get("methods") or []:
            caller = caller_label(method)
            caller_address = method.get("address")
            for ins in method.get("instructions") or []:
                if ins.get("mnemonic") != "call":
                    continue
                op = ins.get("op_str") or ""
                target_label = ins.get("targetLabel")
                edge = {
                    "sourcePack": source,
                    "caller": caller,
                    "callerAddress": caller_address,
                    "callAddress": ins.get("address"),
                    "targetOperand": op,
                    "targetLabel": target_label,
                }
                edges.append(edge)
                caller_counts[caller] += 1
                if target_label:
                    target_counts[target_label] += 1
                else:
                    unresolved_counts[op] += 1
    return {
        "schema": "native-disasm-call-graph.v1",
        "evidenceBoundary": "Static direct-call observations from native disassembly packs. Edges prove instruction-level call operands and address-map labels where present; they do not prove managed semantics, call reachability, or runtime order.",
        "inputs": [p.get("_path") for p in packs],
        "summary": {
            "methodsWithPacks": sum(len(p.get("methods") or []) for p in packs),
            "edges": len(edges),
            "labeledEdges": sum(1 for e in edges if e.get("targetLabel")),
            "unlabeledEdges": sum(1 for e in edges if not e.get("targetLabel")),
            "uniqueCallers": len(caller_counts),
            "uniqueLabeledTargets": len(target_counts),
            "uniqueUnlabeledOperands": len(unresolved_counts),
        },
        "topCallers": [{"caller": k, "calls": v} for k, v in caller_counts.most_common(80)],
        "topLabeledTargets": [{"target": k, "calls": v} for k, v in target_counts.most_common(80)],
        "topUnlabeledOperands": [{"targetOperand": k, "calls": v} for k, v in unresolved_counts.most_common(80)],
        "edges": edges,
    }


def write_md(data: dict[str, Any], path: Path, edge_limit: int) -> None:
    s = data["summary"]
    lines = [
        "# Native Disassembly Direct Call Graph",
        "",
        "Status: static-only. Runtime-unvalidated.",
        "",
        data["evidenceBoundary"],
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|---|---:|",
    ]
    for key in ["methodsWithPacks", "edges", "labeledEdges", "unlabeledEdges", "uniqueCallers", "uniqueLabeledTargets", "uniqueUnlabeledOperands"]:
        lines.append(f"| {key} | {s.get(key, 0)} |")
    lines.extend(["", "## Top labeled targets", "", "| Target | Calls |", "|---|---:|"])
    for row in data.get("topLabeledTargets", [])[:40]:
        lines.append(f"| `{row['target']}` | {row['calls']} |")
    lines.extend(["", "## Top callers", "", "| Caller | Calls |", "|---|---:|"])
    for row in data.get("topCallers", [])[:40]:
        lines.append(f"| `{row['caller']}` | {row['calls']} |")
    lines.extend(["", "## Sample edges", "", "| Caller | Call address | Target operand | Known target |", "|---|---|---|---|"])
    for edge in data.get("edges", [])[:edge_limit]:
        lines.append(f"| `{edge.get('caller','-')}` | `{edge.get('callAddress','-')}` | `{edge.get('targetOperand','-')}` | {edge.get('targetLabel') or ''} |")
    if len(data.get("edges", [])) > edge_limit:
        lines.append(f"\n{len(data['edges']) - edge_limit} more edges omitted from Markdown; see JSON artifact.")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--disasm", type=Path, action="append", required=True)
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--out-md", type=Path, required=True)
    ap.add_argument("--edge-limit", type=int, default=200)
    args = ap.parse_args()
    data = build_graph([load_pack(p) for p in args.disasm])
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    write_md(data, args.out_md, args.edge_limit)
    print(json.dumps({"outJson": str(args.out_json), "outMd": str(args.out_md), **data["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
