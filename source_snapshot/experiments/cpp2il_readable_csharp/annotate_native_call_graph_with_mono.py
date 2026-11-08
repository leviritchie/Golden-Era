#!/usr/bin/env python3
"""Annotate a native deobf call graph with Mono-demo semantic aliases.

This is a static consolidation tool. It does not infer runtime behavior. It
joins the current-build native call graph to the Mono-to-deobf semantic map so
future reviews can traverse current native calls while seeing older readable
Mono type names where the type mapping is strong enough. Method aliases are
emitted only as exact-name static survivals or explicitly labeled ordinal
candidates.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

MIN_CONFIDENCE = {"strong-static", "probable-static"}
TYPE_LABEL_RE = re.compile(r"^(?P<type>[^:]+)::")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    last_error: Exception | None = None
    for attempt in range(12):
        try:
            tmp.replace(path)
            return
        except (PermissionError, OSError) as exc:
            last_error = exc
            time.sleep(0.25 * (attempt + 1))
    if last_error:
        raise last_error


def extract_type(label: str | None) -> str | None:
    if not label or label == "unlabeled":
        return None
    match = TYPE_LABEL_RE.match(label)
    if not match:
        return None
    type_name = match.group("type").strip()
    if not type_name or type_name == "-":
        return None
    return type_name


def build_method_aliases(candidate: dict[str, Any]) -> dict[str, Any]:
    alignment = candidate.get("memberAlignment") or {}
    exact_by_deobf: dict[str, dict[str, Any]] = {}
    ordinal_by_deobf: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in alignment.get("exactMethodNameAlignment") or []:
        deobf = row.get("deobf") or {}
        name = deobf.get("name") or row.get("name")
        if not name:
            continue
        exact_by_deobf[name] = {
            "monoMethod": (row.get("mono") or {}).get("name"),
            "confidence": "strong-static",
            "reasons": row.get("reasons") or ["same owner type", "same method name"],
            "source": "exact-method-name-alignment",
        }
    for row in alignment.get("methodOrdinalAlignment") or []:
        deobf = row.get("deobf") or {}
        mono = row.get("mono") or {}
        name = deobf.get("name")
        if not name:
            continue
        ordinal_by_deobf[name].append({
            "monoMethod": mono.get("name"),
            "confidence": row.get("confidence") or "candidate",
            "score": row.get("score"),
            "ordinal": row.get("ordinal"),
            "reasons": row.get("reasons") or [],
            "source": "method-ordinal-alignment",
        })
    return {"exactByDeobf": exact_by_deobf, "ordinalByDeobf": dict(ordinal_by_deobf)}


def build_aliases(semantic_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    aliases: dict[str, dict[str, Any]] = {}
    for row in semantic_map.get("rows") or []:
        mono = row.get("mono") or {}
        candidates = row.get("candidates") or []
        if not candidates:
            continue
        candidate = candidates[0]
        confidence = candidate.get("confidence")
        if confidence not in MIN_CONFIDENCE:
            continue
        deobf = candidate.get("deobf") or {}
        current = deobf.get("full")
        if not current:
            continue
        aliases[current] = {
            "monoType": mono.get("full"),
            "confidence": confidence,
            "score": candidate.get("score"),
            "reasons": candidate.get("reasons") or [],
            "source": "semantic-map",
            "methodAliases": build_method_aliases(candidate),
        }

    for manual in semantic_map.get("manualTypeAliases") or []:
        confidence = manual.get("confidence")
        if confidence not in MIN_CONFIDENCE:
            continue
        current = manual.get("current")
        if not current:
            continue
        aliases[current] = {
            "monoType": manual.get("mono"),
            "confidence": confidence,
            "score": None,
            "reasons": manual.get("evidence") or [],
            "source": "manual-alias",
            "domain": manual.get("domain"),
            "doc": manual.get("doc"),
            "methodAliases": {"exactByDeobf": {}, "ordinalByDeobf": {}},
        }
    return aliases




def compact_type_alias(alias: dict[str, Any] | None) -> dict[str, Any] | None:
    if not alias:
        return None
    out = {
        "monoType": alias.get("monoType"),
        "confidence": alias.get("confidence"),
        "score": alias.get("score"),
        "reasons": alias.get("reasons") or [],
        "source": alias.get("source"),
    }
    for key in ("domain", "doc"):
        if alias.get(key):
            out[key] = alias.get(key)
    return out



def raw_method_from_label_rest(rest: str) -> str | None:
    for marker in ("System.", "Hex.", "UnityEngine.", "Unity.", "Il2Cpp", "TMPro."):
        idx = rest.find(marker)
        if idx > 0:
            return rest[:idx]
    match = re.match(r"([A-Za-z_][A-Za-z0-9_`<>.]*)", rest)
    return match.group(1) if match else None


def extract_method_name(label: str | None, type_name: str | None, alias: dict[str, Any] | None) -> str | None:
    if not label or not type_name:
        return None
    prefix = f"{type_name}::"
    if not label.startswith(prefix):
        return None
    rest = label[len(prefix):]
    method_aliases = (alias or {}).get("methodAliases") or {}
    names: set[str] = set((method_aliases.get("exactByDeobf") or {}).keys())
    names.update((method_aliases.get("ordinalByDeobf") or {}).keys())
    for name in sorted(names, key=len, reverse=True):
        if rest.startswith(name):
            return name
    return raw_method_from_label_rest(rest)

def method_alias_for(deobf_method: str | None, alias: dict[str, Any] | None) -> dict[str, Any] | None:
    if not deobf_method or not alias:
        return None
    method_aliases = (alias or {}).get("methodAliases") or {}
    exact = (method_aliases.get("exactByDeobf") or {}).get(deobf_method)
    ordinal = (method_aliases.get("ordinalByDeobf") or {}).get(deobf_method) or []
    if exact:
        out = dict(exact)
        out["deobfMethod"] = deobf_method
        if ordinal:
            out["ordinalCandidates"] = ordinal[:3]
        return out
    if ordinal:
        best = sorted(ordinal, key=lambda r: (r.get("score") or 0), reverse=True)[0]
        return {
            "deobfMethod": deobf_method,
            "monoMethod": best.get("monoMethod"),
            "confidence": "candidate",
            "score": best.get("score"),
            "ordinal": best.get("ordinal"),
            "reasons": best.get("reasons") or [],
            "source": "method-ordinal-alignment",
            "evidenceBoundary": "Ordinal method alignment is a review candidate only unless backed by exact name/body evidence.",
        }
    return None


def annotate_edge(edge: dict[str, Any], aliases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    caller_type = extract_type(edge.get("caller"))
    target_type = extract_type(edge.get("targetLabel"))
    out = dict(edge)
    out["callerType"] = caller_type
    out["targetType"] = target_type
    caller_alias = aliases.get(caller_type) if caller_type else None
    target_alias = aliases.get(target_type) if target_type else None
    out["callerMonoAlias"] = compact_type_alias(caller_alias)
    out["targetMonoAlias"] = compact_type_alias(target_alias)
    out["callerMethod"] = extract_method_name(edge.get("caller"), caller_type, caller_alias)
    out["targetMethod"] = extract_method_name(edge.get("targetLabel"), target_type, target_alias)
    out["callerMethodMonoAlias"] = method_alias_for(out["callerMethod"], caller_alias)
    out["targetMethodMonoAlias"] = method_alias_for(out["targetMethod"], target_alias)
    return out


def write_md(data: dict[str, Any], path: Path) -> None:
    lines = [
        "# Native Call Graph with Mono Semantic Aliases",
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
    for key, value in data.get("summary", {}).items():
        lines.append(f"| {key} | {value} |")

    lines.extend([
        "",
        "## Top mapped current types by outgoing calls",
        "",
        "| Current type | Mono alias | Calls | Confidence |",
        "|---|---|---:|---|",
    ])
    for row in data.get("topMappedCallerTypes", [])[:80]:
        lines.append(f"| `{row['currentType']}` | `{row['monoType']}` | {row['edgeCount']} | {row['confidence']} |")

    lines.extend([
        "",
        "## Top unmapped current caller types",
        "",
        "| Current type | Calls |",
        "|---|---:|",
    ])
    for row in data.get("topUnmappedCallerTypes", [])[:80]:
        lines.append(f"| `{row['currentType']}` | {row['edgeCount']} |")

    lines.extend([
        "",
        "## Method alias coverage",
        "",
        "| Current caller method | Mono method | Edges | Confidence | Source |",
        "|---|---|---:|---|---|",
    ])
    for row in data.get("topCallerMethodAliases", [])[:80]:
        lines.append(
            f"| `{row['currentType']}::{row['deobfMethod']}` | `{row['monoType']}::{row['monoMethod']}` | {row['edgeCount']} | {row['confidence']} | {row['source']} |"
        )

    lines.extend([
        "",
        "## Review notes",
        "",
        "- `callerMonoAlias` and `targetMonoAlias` in the JSON are type-level aliases only.",
        "- Method aliases are emitted only when the deobf method label matches exact method-name survival or a separately labeled ordinal candidate from the semantic map.",
        "- Unmapped caller/target types are not failures; they identify where focused Mono/current dossiers would improve the map next.",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", type=Path, required=True)
    ap.add_argument("--semantic-map", type=Path, required=True)
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--out-md", type=Path, required=True)
    args = ap.parse_args()

    graph = load_json(args.graph)
    semantic_map = load_json(args.semantic_map)
    aliases = build_aliases(semantic_map)
    annotated_edges = [annotate_edge(edge, aliases) for edge in graph.get("edges") or []]

    caller_counts: Counter[str] = Counter()
    mapped_caller_counts: Counter[str] = Counter()
    target_counts: Counter[str] = Counter()
    mapped_target_counts: Counter[str] = Counter()
    caller_method_alias_counts: Counter[tuple[str, str, str, str, str, str]] = Counter()
    alias_sources: Counter[str] = Counter()
    alias_confidences: Counter[str] = Counter()
    current_type_domains: dict[str, dict[str, Any]] = {}

    for edge in annotated_edges:
        caller_type = edge.get("callerType")
        target_type = edge.get("targetType")
        if caller_type:
            caller_counts[caller_type] += 1
        if target_type:
            target_counts[target_type] += 1
        caller_alias = edge.get("callerMonoAlias")
        target_alias = edge.get("targetMonoAlias")
        if caller_type and caller_alias:
            mapped_caller_counts[caller_type] += 1
            current_type_domains[caller_type] = caller_alias
            alias_sources[caller_alias.get("source") or "-"] += 1
            alias_confidences[caller_alias.get("confidence") or "-"] += 1
        if target_type and target_alias:
            mapped_target_counts[target_type] += 1
            current_type_domains[target_type] = target_alias
            alias_sources[target_alias.get("source") or "-"] += 1
            alias_confidences[target_alias.get("confidence") or "-"] += 1
        method_alias = edge.get("callerMethodMonoAlias")
        if caller_type and caller_alias and method_alias:
            caller_method_alias_counts[(
                caller_type,
                caller_alias.get("monoType") or "-",
                method_alias.get("deobfMethod") or "-",
                method_alias.get("monoMethod") or "-",
                method_alias.get("confidence") or "-",
                method_alias.get("source") or "-",
            )] += 1

    top_mapped = []
    for current_type, count in mapped_caller_counts.most_common(120):
        alias = current_type_domains[current_type]
        top_mapped.append({
            "currentType": current_type,
            "monoType": alias.get("monoType"),
            "edgeCount": count,
            "confidence": alias.get("confidence"),
            "source": alias.get("source"),
        })

    top_unmapped = [
        {"currentType": current_type, "edgeCount": count}
        for current_type, count in caller_counts.most_common(120)
        if current_type not in aliases
    ][:120]

    top_method_aliases = []
    for (current_type, mono_type, deobf_method, mono_method, confidence, source), count in caller_method_alias_counts.most_common(120):
        top_method_aliases.append({
            "currentType": current_type,
            "monoType": mono_type,
            "deobfMethod": deobf_method,
            "monoMethod": mono_method,
            "confidence": confidence,
            "source": source,
            "edgeCount": count,
        })

    data = {
        "schema": "native-call-graph-mono-annotations.v2",
        "evidenceBoundary": "Static join of current native direct-call graph labels to Mono-demo semantic aliases. Type aliases are strong/probable static joins. Method aliases are exact-name static survivals or separately labeled ordinal candidates only. This does not prove runtime reachability, invocation order, method semantics, or hook safety.",
        "inputs": {
            "graph": str(args.graph),
            "semanticMap": str(args.semantic_map),
        },
        "summary": {
            "edges": len(annotated_edges),
            "typeAliasesAvailable": len(aliases),
            "callerTypes": len(caller_counts),
            "callerTypesMapped": len(mapped_caller_counts),
            "targetTypes": len(target_counts),
            "targetTypesMapped": len(mapped_target_counts),
            "edgesWithCallerAlias": sum(1 for edge in annotated_edges if edge.get("callerMonoAlias")),
            "edgesWithTargetAlias": sum(1 for edge in annotated_edges if edge.get("targetMonoAlias")),
            "edgesWithCallerMethodAlias": sum(1 for edge in annotated_edges if edge.get("callerMethodMonoAlias")),
            "edgesWithTargetMethodAlias": sum(1 for edge in annotated_edges if edge.get("targetMethodMonoAlias")),
            "edgesWithStrongCallerMethodAlias": sum(1 for edge in annotated_edges if (edge.get("callerMethodMonoAlias") or {}).get("confidence") == "strong-static"),
            "edgesWithStrongTargetMethodAlias": sum(1 for edge in annotated_edges if (edge.get("targetMethodMonoAlias") or {}).get("confidence") == "strong-static"),
        },
        "aliasSources": dict(sorted(alias_sources.items())),
        "aliasConfidences": dict(sorted(alias_confidences.items())),
        "topMappedCallerTypes": top_mapped,
        "topUnmappedCallerTypes": top_unmapped,
        "topCallerMethodAliases": top_method_aliases,
        "edges": annotated_edges,
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(args.out_json, json.dumps(data, indent=2))
    write_md(data, args.out_md)
    print(json.dumps({"outJson": str(args.out_json), "outMd": str(args.out_md), "summary": data["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


