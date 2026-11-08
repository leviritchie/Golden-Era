#!/usr/bin/env python3
"""Build a pairwise static reachability matrix for native call graph anchors.

The matrix is bounded and static-only. A positive cell means the selected graph
contains a directed direct-call path between matching node labels within the
chosen depth. It does not prove runtime reachability, branch feasibility, or
managed semantic intent.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any


def load_graph(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def norm(text: str | None) -> str:
    return (text or "").lower()


def edge_target(edge: dict[str, Any]) -> str | None:
    return edge.get("targetLabel") or edge.get("targetOperand")


def split_patterns(text: str) -> list[str]:
    return [p.strip() for p in text.split(",") if p.strip()]


def parse_anchor(value: str) -> dict[str, Any]:
    if "=" in value:
        name, patterns = value.split("=", 1)
    else:
        name, patterns = value, value
    return {"name": name.strip(), "patterns": split_patterns(patterns)}


def node_matches(node: str, patterns: list[str]) -> bool:
    n = norm(node)
    return any(norm(p) in n for p in patterns)


def build_adjacency(edges: list[dict[str, Any]], labeled_only: bool) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        target = edge_target(edge)
        if not target:
            continue
        if labeled_only and not edge.get("targetLabel"):
            continue
        caller = edge.get("caller") or ""
        item = dict(edge)
        item["target"] = target
        out[caller].append(item)
    return out


def shortest_path(out: dict[str, list[dict[str, Any]]], sources: list[str], target_patterns: list[str], max_depth: int, max_sources: int) -> dict[str, Any]:
    if not sources:
        return {"found": False, "reason": "no source nodes matched"}
    q = deque()
    seen = set()
    for source in sources[:max_sources]:
        q.append((source, []))
        seen.add(source)
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
    return {"found": False, "reason": "no path within max_depth", "sourceMatchesConsidered": min(len(sources), max_sources)}


def build_matrix(graph: dict[str, Any], anchors: list[dict[str, Any]], max_depth: int, labeled_only: bool, max_sources: int) -> dict[str, Any]:
    edges = graph.get("edges") or []
    out = build_adjacency(edges, labeled_only)
    nodes = sorted(set(out) | {e["target"] for edges in out.values() for e in edges})
    matched: dict[str, list[str]] = {}
    for anchor in anchors:
        matched[anchor["name"]] = [n for n in nodes if node_matches(n, anchor["patterns"])]
    cells = []
    for source in anchors:
        for target in anchors:
            if source["name"] == target["name"]:
                continue
            result = shortest_path(out, matched[source["name"]], target["patterns"], max_depth, max_sources)
            cells.append({
                "source": source["name"],
                "target": target["name"],
                "sourcePatterns": source["patterns"],
                "targetPatterns": target["patterns"],
                "sourceMatchedNodes": len(matched[source["name"]]),
                "targetMatchedNodes": len(matched[target["name"]]),
                "result": result,
            })
    return {
        "schema": "native-anchor-matrix.v1",
        "evidenceBoundary": "Static bounded reachability over direct-call graph labels. Positive cells prove a direct-call path exists in this graph within the selected depth. Negative cells prove only no matching path under the selected labels, graph, depth, and source cap.",
        "graph": graph.get("_path"),
        "graphSummary": graph.get("summary"),
        "labeledOnly": labeled_only,
        "maxDepth": max_depth,
        "maxSourcesPerAnchor": max_sources,
        "anchors": [{"name": a["name"], "patterns": a["patterns"], "matchedNodes": len(matched[a["name"]]), "sampleNodes": matched[a["name"]][:20]} for a in anchors],
        "cells": cells,
    }


def write_md(data: dict[str, Any], path: Path) -> None:
    anchors = [a["name"] for a in data["anchors"]]
    cell_map = {(c["source"], c["target"]): c for c in data["cells"]}
    lines = [
        "# Native Call Graph Anchor Matrix",
        "",
        "Status: static-only. Runtime-unvalidated.",
        "",
        data["evidenceBoundary"],
        "",
        f"Graph: `{data.get('graph')}`",
        f"Max depth: {data['maxDepth']}",
        f"Labeled edges only: {data['labeledOnly']}",
        "",
        "## Anchor match counts",
        "",
        "| Anchor | Patterns | Matched nodes |",
        "|---|---|---:|",
    ]
    for anchor in data["anchors"]:
        patterns = ", ".join(f"`{p}`" for p in anchor["patterns"])
        lines.append(f"| {anchor['name']} | {patterns} | {anchor['matchedNodes']} |")
    lines.extend(["", "## Pairwise reachability", "", "Cell values are shortest static directed path depth; `-` means no path within the selected bound.", ""])
    header = "| From \\ To | " + " | ".join(anchors) + " |"
    sep = "|---|" + "---:|" * len(anchors)
    lines.extend([header, sep])
    for source in anchors:
        row = [source]
        for target in anchors:
            if source == target:
                row.append("self")
            else:
                cell = cell_map[(source, target)]
                result = cell["result"]
                row.append(str(result.get("depth")) if result.get("found") else "-")
        lines.append("| " + " | ".join(row) + " |")
    positives = [c for c in data["cells"] if c["result"].get("found")]
    lines.extend(["", "## Example positive paths", ""])
    for cell in sorted(positives, key=lambda c: (c["result"].get("depth", 99), c["source"], c["target"]))[:40]:
        lines.append(f"### {cell['source']} -> {cell['target']} depth {cell['result']['depth']}")
        lines.extend(["", "| Step | Caller | Call address | Target |", "|---:|---|---|---|"])
        for idx, edge in enumerate(cell["result"].get("path", []), 1):
            lines.append(f"| {idx} | `{edge.get('caller')}` | `{edge.get('callAddress')}` | `{edge.get('target')}` |")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", type=Path, required=True)
    ap.add_argument("--anchor", action="append", required=True, help="NAME=pattern[,pattern...] or pattern")
    ap.add_argument("--max-depth", type=int, default=4)
    ap.add_argument("--max-sources", type=int, default=500)
    ap.add_argument("--include-unlabeled", action="store_true")
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--out-md", type=Path, required=True)
    args = ap.parse_args()
    graph = load_graph(args.graph)
    graph["_path"] = str(args.graph)
    anchors = [parse_anchor(a) for a in args.anchor]
    data = build_matrix(graph, anchors, args.max_depth, not args.include_unlabeled, args.max_sources)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    write_md(data, args.out_md)
    found = sum(1 for c in data["cells"] if c["result"].get("found"))
    print(json.dumps({"outJson": str(args.out_json), "outMd": str(args.out_md), "anchors": len(anchors), "cells": len(data["cells"]), "found": found}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
