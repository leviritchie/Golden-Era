#!/usr/bin/env python3
"""Build a next-action report for unresolved focused anchor paths.

The input is the focused high-priority anchor path pack. This report does not
search decompilation artifacts; it turns current static evidence into a stable
work queue for the next static proof pass.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def command_for(type_name: str | None, method_name: str | None, out_slug: str) -> str | None:
    if not type_name or not method_name:
        return None
    return (
        "python experiments\\cpp2il_readable_csharp\\build_method_dossier.py "
        f"--type {type_name} --method {method_name} "
        "--address-map experiments\\cpp2il_readable_csharp\\samples\\latest_refresh\\address_map_all_dummydll_methods.json "
        "--include-static-initializers --max-body-lines 500 --timeout-seconds 300 "
        f"--out tmp\\cpp2il_experiment\\readable_notes\\{out_slug}_dossier.md "
        f"--out-json tmp\\cpp2il_experiment\\readable_notes\\{out_slug}_dossier.json"
    )


def slug(value: str) -> str:
    out = []
    for ch in value:
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("_")
    return "".join(out).strip("_")[:120] or "target"


def next_action(step: dict[str, Any]) -> tuple[str, str]:
    gap = step.get("staticGap") or ""
    caller_type = step.get("callerType")
    caller_method = step.get("callerMethod")
    method_alias = step.get("callerMethodMonoAlias") or {}
    mono_method = method_alias.get("monoMethod")
    if "unmapped" in gap:
        return (
            "map-current-type",
            "Search current DiffableCs/interop shape for this type, then compare against Mono demo by neighboring type names and native callers. If no Mono type exists, mark as current-only type in the map boundary.",
        )
    if "constructor-drift" in gap or "likely noisy" in gap:
        return (
            "reject-or-remap-ordinal",
            "Treat the ordinal alias as likely wrong. Build a current method dossier and search same owner/neighbor call targets; do not use the Mono .ctor candidate as semantic evidence.",
        )
    if "parameter-count mismatch" in gap:
        return (
            "body-xref-required",
            "Build a current method dossier and compare direct callees/native instruction context against the claimed Mono method intent. Keep candidate below implementation proof until body/xref evidence agrees.",
        )
    if "ordinal candidate only" in gap:
        return (
            "confirm-ordinal-candidate",
            "Build a current method dossier and compare method-body shape, caller/callee neighborhood, and literals against the Mono method candidate.",
        )
    if "exact-name" in gap:
        return (
            "target-endpoint-or-runtime-order",
            "Caller method identity is strong static. Improve target endpoint alias or leave runtime reachability/order as the remaining non-static gap.",
        )
    return ("review", "Review focused pack row manually.")


def build_report(focused: dict[str, Any]) -> dict[str, Any]:
    rows = []
    action_counter: Counter[str] = Counter()
    gap_counter: Counter[str] = Counter()
    for row in focused.get("rows") or []:
        for idx, step in enumerate(row.get("steps") or [], 1):
            gap = step.get("staticGap") or ""
            if "both endpoint methods" in gap:
                continue
            action, rationale = next_action(step)
            action_counter[action] += 1
            gap_counter[gap] += 1
            caller_type = step.get("callerType")
            caller_method = step.get("callerMethod")
            out_slug = slug(f"{row.get('path')}_{caller_type or 'unmapped'}_{caller_method or 'unknown'}")
            rows.append({
                "path": row.get("path"),
                "step": idx,
                "action": action,
                "rationale": rationale,
                "gap": gap,
                "caller": step.get("caller"),
                "callerType": caller_type,
                "callerMethod": caller_method,
                "targetLabel": step.get("targetLabel"),
                "targetType": step.get("targetType"),
                "targetMethod": step.get("targetMethod"),
                "callerMonoType": (step.get("callerMonoAlias") or {}).get("monoType"),
                "callerMonoMethodCandidate": (step.get("callerMethodMonoAlias") or {}).get("monoMethod"),
                "callerMethodAliasConfidence": (step.get("callerMethodMonoAlias") or {}).get("confidence"),
                "callerMethodAliasScore": (step.get("callerMethodMonoAlias") or {}).get("score"),
                "callerMethodAliasReasons": (step.get("callerMethodMonoAlias") or {}).get("reasons") or [],
                "dossierCommand": command_for(caller_type, caller_method, out_slug),
            })
    return {
        "schema": "unresolved-anchor-path-actions.v1",
        "evidenceBoundary": "Static planning artifact derived from the focused high-priority anchor path pack. It recommends static proof actions; it does not prove method semantics or runtime behavior.",
        "inputSchema": focused.get("schema"),
        "summary": {
            "unresolvedSteps": len(rows),
            "actions": dict(sorted(action_counter.items())),
            "gaps": dict(sorted(gap_counter.items())),
        },
        "rows": rows,
    }


def write_md(data: dict[str, Any], path: Path) -> None:
    lines = [
        "# Unresolved High-Priority Anchor Path Actions",
        "",
        "Status: static-only. Runtime-unvalidated.",
        "",
        data["evidenceBoundary"],
        "",
        "## Summary",
        "",
        "| Action | Count |",
        "|---|---:|",
    ]
    for action, count in (data.get("summary", {}).get("actions") or {}).items():
        lines.append(f"| `{action}` | {count} |")
    lines.extend(["", "## Rows", "", "| Action | Path | Current caller | Mono candidate | Gap | Next static proof |", "|---|---|---|---|---|---|"])
    for row in data.get("rows") or []:
        caller = f"{row.get('callerType') or '-'}::{row.get('callerMethod') or '-'}"
        mono = f"{row.get('callerMonoType') or '-'}::{row.get('callerMonoMethodCandidate') or '-'}"
        gap = (row.get("gap") or "-").replace("|", "\\|")
        rationale = (row.get("rationale") or "-").replace("|", "\\|")
        lines.append(f"| `{row.get('action')}` | `{row.get('path')}` | `{caller}` | `{mono}` | {gap} | {rationale} |")
    lines.extend(["", "## Dossier commands", ""])
    for row in data.get("rows") or []:
        cmd = row.get("dossierCommand")
        if not cmd:
            continue
        lines.append(f"### `{row.get('path')}` `{row.get('callerType')}::{row.get('callerMethod')}`")
        lines.append("")
        lines.append("```powershell")
        lines.append(cmd)
        lines.append("```")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--focused-pack", type=Path, required=True)
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--out-md", type=Path, required=True)
    args = ap.parse_args()
    data = build_report(load_json(args.focused_pack))
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    write_md(data, args.out_md)
    print(json.dumps({"outJson": str(args.out_json), "outMd": str(args.out_md), "summary": data["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

