#!/usr/bin/env python3
"""Build evidence dossiers for positive anchor-matrix paths.

Inputs are a native anchor matrix and one or more native disassembly packs.
The output enriches each static path step with method metadata and instruction
context around the call address.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["_path"] = str(path)
    return data


def index_disassembly(packs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for pack in packs:
        for method in pack.get("methods") or []:
            label = method.get("label")
            if label and label not in index:
                entry = dict(method)
                entry["sourcePack"] = pack.get("_path")
                index[label] = entry
    return index


def instruction_context(method: dict[str, Any] | None, call_address: str | None, radius: int) -> dict[str, Any]:
    if not method:
        return {"found": False, "reason": "caller method not found in disassembly packs"}
    instructions = method.get("instructions") or []
    idx = None
    for i, ins in enumerate(instructions):
        if ins.get("address") == call_address:
            idx = i
            break
    if idx is None:
        return {"found": False, "reason": "call address not found in caller method disassembly", "methodAddress": method.get("address"), "sourcePack": method.get("sourcePack")}
    start = max(0, idx - radius)
    end = min(len(instructions), idx + radius + 1)
    return {
        "found": True,
        "methodAddress": method.get("address"),
        "methodRva": method.get("rva"),
        "methodLength": method.get("length"),
        "sourcePack": method.get("sourcePack"),
        "instructionIndex": idx,
        "context": instructions[start:end],
    }


def build_dossiers(matrix: dict[str, Any], disasm_index: dict[str, dict[str, Any]], radius: int, limit: int | None) -> dict[str, Any]:
    cells = [c for c in (matrix.get("cells") or []) if c.get("result", {}).get("found")]
    cells.sort(key=lambda c: (c["result"].get("depth", 999), c.get("source", ""), c.get("target", "")))
    if limit is not None:
        cells = cells[:limit]
    dossiers = []
    for cell in cells:
        steps = []
        for step in cell.get("result", {}).get("path", []):
            caller = step.get("caller")
            method = disasm_index.get(caller or "")
            enriched = dict(step)
            enriched["callerMethod"] = {
                "found": method is not None,
                "address": method.get("address") if method else None,
                "rva": method.get("rva") if method else None,
                "length": method.get("length") if method else None,
                "sourcePack": method.get("sourcePack") if method else None,
                "signature": method.get("signature") if method else None,
            }
            enriched["callInstructionContext"] = instruction_context(method, step.get("callAddress"), radius)
            steps.append(enriched)
        dossiers.append({
            "source": cell.get("source"),
            "target": cell.get("target"),
            "depth": cell.get("result", {}).get("depth"),
            "sourcePatterns": cell.get("sourcePatterns"),
            "targetPatterns": cell.get("targetPatterns"),
            "steps": steps,
        })
    return {
        "schema": "native-anchor-path-dossiers.v1",
        "evidenceBoundary": "Static native path dossiers. These prove direct-call path steps and local native instruction context in the selected disassembly packs; they do not prove branch feasibility, runtime reachability, managed semantic intent, or hook safety.",
        "matrix": matrix.get("_path"),
        "matrixMaxDepth": matrix.get("maxDepth"),
        "dossierCount": len(dossiers),
        "contextRadius": radius,
        "dossiers": dossiers,
    }


def fmt_ins(ins: dict[str, Any]) -> str:
    text = f"{ins.get('mnemonic', '')} {ins.get('op_str', '')}".strip().replace("|", "\\|")
    target = ins.get("targetLabel")
    if target:
        text += f" ; {target}"
    return text


def write_md(data: dict[str, Any], path: Path) -> None:
    lines = [
        "# Native Anchor Path Dossiers",
        "",
        "Status: static-only. Runtime-unvalidated.",
        "",
        data["evidenceBoundary"],
        "",
        f"Matrix: `{data.get('matrix')}`",
        f"Dossiers: {data.get('dossierCount')}",
        "",
    ]
    for dossier in data.get("dossiers", []):
        lines.extend([
            f"## {dossier['source']} -> {dossier['target']} depth {dossier['depth']}",
            "",
        ])
        for idx, step in enumerate(dossier.get("steps", []), 1):
            caller_method = step.get("callerMethod") or {}
            ctx = step.get("callInstructionContext") or {}
            lines.extend([
                f"### Step {idx}",
                "",
                f"Caller: `{step.get('caller')}`",
                f"Call address: `{step.get('callAddress')}`",
                f"Target: `{step.get('target')}`",
                f"Caller source pack: `{caller_method.get('sourcePack')}`",
                "",
            ])
            if not ctx.get("found"):
                lines.extend([f"Instruction context unavailable: {ctx.get('reason')}", ""])
                continue
            lines.extend(["| Address | Instruction |", "|---|---|"])
            for ins in ctx.get("context", []):
                marker = " **CALL**" if ins.get("address") == step.get("callAddress") else ""
                lines.append(f"| `{ins.get('address')}`{marker} | `{fmt_ins(ins)}` |")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", type=Path, required=True)
    ap.add_argument("--disasm", type=Path, action="append", required=True)
    ap.add_argument("--context-radius", type=int, default=4)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--out-md", type=Path, required=True)
    args = ap.parse_args()
    matrix = load_json(args.matrix)
    packs = [load_json(p) for p in args.disasm]
    data = build_dossiers(matrix, index_disassembly(packs), args.context_radius, args.limit)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    write_md(data, args.out_md)
    missing_context = 0
    for dossier in data["dossiers"]:
        for step in dossier["steps"]:
            if not step.get("callInstructionContext", {}).get("found"):
                missing_context += 1
    print(json.dumps({"outJson": str(args.out_json), "outMd": str(args.out_md), "dossiers": data["dossierCount"], "missingInstructionContexts": missing_context}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
