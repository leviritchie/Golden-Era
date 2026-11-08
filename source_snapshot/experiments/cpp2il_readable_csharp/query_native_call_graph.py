#!/usr/bin/env python3
"""Query static direct-call graph artifacts.

This tool works on build_native_disasm_call_graph.py JSON output. It reports
exact static direct-call observations and shortest directed paths between text
patterns. It does not prove runtime reachability or managed semantic intent.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any


def load_graph(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def norm(text: str | None) -> str:
    return (text or "").lower()


def edge_target(edge: dict[str, Any]) -> str | None:
    return edge.get("targetLabel") or edge.get("targetOperand")


def node_matches(node: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    n = norm(node)
    return any(norm(p) in n for p in patterns)


def build_adjacency(edges: list[dict[str, Any]], labeled_only: bool) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        target = edge_target(edge)
        if not target:
            continue
        if labeled_only and not edge.get("targetLabel"):
            continue
        caller = edge.get("caller") or ""
        edge = dict(edge)
        edge["target"] = target
        out[caller].append(edge)
        incoming[target].append(edge)
    return out, incoming


def shortest_path(edges: list[dict[str, Any]], source_patterns: list[str], target_patterns: list[str], max_depth: int, labeled_only: bool) -> dict[str, Any]:
    out, _incoming = build_adjacency(edges, labeled_only)
    sources = sorted(n for n in out if node_matches(n, source_patterns))
    if not sources:
        return {"found": False, "reason": "no source nodes matched", "sourcePatterns": source_patterns, "targetPatterns": target_patterns}
    q = deque()
    seen = set()
    for s in sources[:500]:
        q.append((s, []))
        seen.add(s)
    while q:
        node, path = q.popleft()
        if path and node_matches(node, target_patterns):
            return {"found": True, "depth": len(path), "path": path}
        if len(path) >= max_depth:
            continue
        for edge in out.get(node, []):
            target = edge["target"]
            if target in seen:
                continue
            seen.add(target)
            q.append((target, path + [{
                "caller": edge.get("caller"),
                "callAddress": edge.get("callAddress"),
                "target": target,
                "targetOperand": edge.get("targetOperand"),
                "targetLabel": edge.get("targetLabel"),
            }]))
    return {"found": False, "reason": "no path within max_depth", "sourceMatchesConsidered": len(sources), "maxDepth": max_depth, "sourcePatterns": source_patterns, "targetPatterns": target_patterns}


def summarize_patterns(edges: list[dict[str, Any]], patterns: list[str], labeled_only: bool) -> dict[str, Any]:
    out, incoming = build_adjacency(edges, labeled_only)
    nodes = set(out) | set(incoming)
    matched = sorted(n for n in nodes if node_matches(n, patterns))
    outbound_edges = [e for n in matched for e in out.get(n, [])]
    inbound_edges = [e for n in matched for e in incoming.get(n, [])]
    target_counts = Counter(e.get("target") for e in outbound_edges if e.get("target"))
    caller_counts = Counter(e.get("caller") for e in inbound_edges if e.get("caller"))
    return {
        "patterns": patterns,
        "matchedNodes": len(matched),
        "sampleNodes": matched[:40],
        "outboundEdges": len(outbound_edges),
        "inboundEdges": len(inbound_edges),
        "topOutboundTargets": [{"target": k, "calls": v} for k, v in target_counts.most_common(30)],
        "topInboundCallers": [{"caller": k, "calls": v} for k, v in caller_counts.most_common(30)],
    }


def write_md(data: dict[str, Any], out_path: Path) -> None:
    lines = [
        "# Native Call Graph Query Report",
        "",
        "Status: static-only. Runtime-unvalidated.",
        "",
        data["evidenceBoundary"],
        "",
        f"Graph: `{data['graph']}`",
        "",
    ]
    if data.get("summaries"):
        lines.extend(["## Pattern summaries", ""])
        for summary in data["summaries"]:
            lines.extend([
                f"### `{', '.join(summary['patterns'])}`",
                "",
                f"Matched nodes: {summary['matchedNodes']}",
                f"Outbound edges: {summary['outboundEdges']}",
                f"Inbound edges: {summary['inboundEdges']}",
                "",
                "Top outbound targets:",
                "",
                "| Target | Calls |",
                "|---|---:|",
            ])
            for row in summary.get("topOutboundTargets", [])[:12]:
                lines.append(f"| `{row['target']}` | {row['calls']} |")
            lines.extend(["", "Top inbound callers:", "", "| Caller | Calls |", "|---|---:|"])
            for row in summary.get("topInboundCallers", [])[:12]:
                lines.append(f"| `{row['caller']}` | {row['calls']} |")
            lines.append("")
    if data.get("paths"):
        lines.extend(["## Shortest path queries", ""])
        for path_row in data["paths"]:
            lines.append(f"### `{path_row['source']}` -> `{path_row['target']}`")
            lines.append("")
            result = path_row["result"]
            if not result.get("found"):
                lines.append(f"No path: {result.get('reason')}.")
                lines.append("")
                continue
            lines.append(f"Depth: {result['depth']}")
            lines.extend(["", "| Step | Caller | Call address | Target |", "|---:|---|---|---|"])
            for idx, edge in enumerate(result.get("path", []), 1):
                lines.append(f"| {idx} | `{edge.get('caller')}` | `{edge.get('callAddress')}` | `{edge.get('target')}` |")
            lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", type=Path, required=True)
    ap.add_argument("--summary", action="append", default=[], help="Pattern to summarize. Repeatable; comma separates alternatives in one group.")
    ap.add_argument("--path", action="append", default=[], help="Shortest path query SOURCE=>TARGET. Comma separates alternatives per side.")
    ap.add_argument("--max-depth", type=int, default=4)
    ap.add_argument("--include-unlabeled", action="store_true")
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--out-md", type=Path, required=True)
    args = ap.parse_args()

    graph = load_graph(args.graph)
    edges = graph.get("edges") or []
    labeled_only = not args.include_unlabeled
    summaries = []
    for item in args.summary:
        patterns = [p.strip() for p in item.split(",") if p.strip()]
        summaries.append(summarize_patterns(edges, patterns, labeled_only))
    paths = []
    for item in args.path:
        if "=>" not in item:
            raise SystemExit(f"invalid --path {item!r}; expected SOURCE=>TARGET")
        left, right = item.split("=>", 1)
        source_patterns = [p.strip() for p in left.split(",") if p.strip()]
        target_patterns = [p.strip() for p in right.split(",") if p.strip()]
        paths.append({
            "source": left,
            "target": right,
            "result": shortest_path(edges, source_patterns, target_patterns, args.max_depth, labeled_only),
        })
    data = {
        "schema": "native-call-graph-query.v1",
        "evidenceBoundary": "Static graph query over direct-call observations. Paths prove only that native instructions contain direct call chains in the selected graph; they do not prove runtime reachability, branch feasibility, managed semantics, or hook safety.",
        "graph": str(args.graph),
        "labeledOnly": labeled_only,
        "summaries": summaries,
        "paths": paths,
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    write_md(data, args.out_md)
    print(json.dumps({"outJson": str(args.out_json), "outMd": str(args.out_md), "summaries": len(summaries), "paths": len(paths)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
