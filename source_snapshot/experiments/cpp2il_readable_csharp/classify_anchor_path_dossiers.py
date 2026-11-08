#!/usr/bin/env python3
"""Heuristically classify native anchor path dossiers for review priority.

This does not infer runtime semantics. It scores static path dossiers by domain
labels, depth, and instruction-context noise so humans can decide which paths
are worth focused interpretation.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

HIGH_VALUE_ANCHORS = {"Battle", "City", "SessionData", "Map", "Configs", "ResManager", "Sound"}
UI_ANCHORS = {"UI", "SessionUI", "SessionHud", "CheatUI"}
ASSET_ANCHORS = {"Configs", "ResManager", "RenderStorage"}

GENERIC_TERMS = (
    "System.", "UnityEngine.", "Unity.", "<>c", "Enumerator", ".ctor", "MonoScriptData",
    "Object::", "List`1", "Dictionary`2", "Action", "Func`",
)

DOMAIN_TERMS = (
    "Hex.Session.Battle", "Hex.Session.City", "Hex.Session.Data", "Hex.Map", "Hex.Configs",
    "Hex.ResManager", "Hex.Sound", "Hex.UI", "Hex.Session.UI", "Hex.Session.Hud",
    "Hex.Cheat.UI", "Hex.Render", "Hex.Storage",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def text_blob(dossier: dict[str, Any]) -> str:
    parts: list[str] = [dossier.get("source", ""), dossier.get("target", "")]
    for step in dossier.get("steps") or []:
        parts.extend([step.get("caller") or "", step.get("target") or "", step.get("targetLabel") or "", step.get("targetOperand") or ""])
        ctx = step.get("callInstructionContext") or {}
        for ins in ctx.get("context") or []:
            parts.extend([ins.get("mnemonic") or "", ins.get("op_str") or "", ins.get("targetLabel") or ""])
    return "\n".join(parts)


def classify(dossier: dict[str, Any]) -> dict[str, Any]:
    source = dossier.get("source") or ""
    target = dossier.get("target") or ""
    depth = int(dossier.get("depth") or 0)
    blob = text_blob(dossier)
    generic_hits = sum(blob.count(term) for term in GENERIC_TERMS)
    domain_hits = {term: blob.count(term) for term in DOMAIN_TERMS if blob.count(term)}
    step_count = len(dossier.get("steps") or [])
    reasons: list[str] = []
    score = 0

    if depth == 1:
        score += 4
        reasons.append("direct static call path")
    elif depth == 2:
        score += 2
        reasons.append("short static call path")
    else:
        score -= 1
        reasons.append("longer static path")

    if source in HIGH_VALUE_ANCHORS and target in HIGH_VALUE_ANCHORS:
        score += 5
        category = "domain-direct"
        reasons.append("source and target are gameplay/data anchors")
    elif source in UI_ANCHORS and target in HIGH_VALUE_ANCHORS:
        score += 3
        category = "ui-to-gameplay"
        reasons.append("UI/HUD path reaches gameplay/data anchor")
    elif source in HIGH_VALUE_ANCHORS and target in UI_ANCHORS:
        score += 1
        category = "gameplay-to-ui"
        reasons.append("gameplay/data path reaches UI anchor")
    elif source in ASSET_ANCHORS or target in ASSET_ANCHORS:
        score += 2
        category = "asset-config-resource"
        reasons.append("path involves config/resource/render/storage anchor")
    else:
        category = "structural"
        reasons.append("path is mostly structural between broad anchors")

    if generic_hits > 30:
        score -= 3
        reasons.append(f"generic/helper-heavy context ({generic_hits} generic hits)")
    elif generic_hits > 10:
        score -= 1
        reasons.append(f"some generic/helper context ({generic_hits} generic hits)")

    if len(domain_hits) >= 3:
        score += 2
        reasons.append("multiple domain labels appear in path context")
    elif len(domain_hits) >= 1:
        score += 1
        reasons.append("domain labels appear in path context")

    priority = "high" if score >= 8 else "medium" if score >= 4 else "low"
    if category == "structural" and priority == "high":
        priority = "medium"
    return {
        "source": source,
        "target": target,
        "depth": depth,
        "steps": step_count,
        "category": category,
        "priority": priority,
        "score": score,
        "reasons": reasons,
        "genericHits": generic_hits,
        "domainHits": domain_hits,
        "firstStepCaller": (dossier.get("steps") or [{}])[0].get("caller"),
        "firstStepTarget": (dossier.get("steps") or [{}])[0].get("target"),
    }


def write_md(data: dict[str, Any], path: Path) -> None:
    lines = [
        "# Native Anchor Path Triage",
        "",
        "Status: static-only. Runtime-unvalidated.",
        "",
        data["evidenceBoundary"],
        "",
        "## Summary",
        "",
        "| Bucket | Count |",
        "|---|---:|",
    ]
    for bucket, count in data.get("summary", {}).items():
        lines.append(f"| {bucket} | {count} |")
    lines.extend(["", "## Classified paths", "", "| Priority | Category | Score | Path | Reasons |", "|---|---|---:|---|---|"])
    for row in data.get("rows", []):
        path_label = f"{row['source']} -> {row['target']} (d{row['depth']})"
        reasons = "; ".join(row.get("reasons", [])[:4]).replace("|", "\\|")
        lines.append(f"| {row['priority']} | {row['category']} | {row['score']} | `{path_label}` | {reasons} |")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dossiers", type=Path, required=True)
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--out-md", type=Path, required=True)
    args = ap.parse_args()
    source = load_json(args.dossiers)
    rows = [classify(d) for d in source.get("dossiers") or []]
    rows.sort(key=lambda r: ({"high": 0, "medium": 1, "low": 2}[r["priority"]], -r["score"], r["source"], r["target"]))
    summary_counter = Counter()
    for row in rows:
        summary_counter[f"priority:{row['priority']}"] += 1
        summary_counter[f"category:{row['category']}"] += 1
    data = {
        "schema": "native-anchor-path-triage.v1",
        "evidenceBoundary": "Heuristic static triage over native path dossiers. Priority/category values are review aids only; they do not prove runtime semantics, branch feasibility, or hook safety.",
        "inputDossiers": str(args.dossiers),
        "summary": dict(sorted(summary_counter.items())),
        "rows": rows,
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    write_md(data, args.out_md)
    print(json.dumps({"outJson": str(args.out_json), "outMd": str(args.out_md), "rows": len(rows), "summary": data["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
