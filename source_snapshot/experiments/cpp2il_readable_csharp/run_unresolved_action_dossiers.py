#!/usr/bin/env python3
"""Run static method dossiers for selected unresolved anchor-path actions."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value).strip("_")[:160] or "dossier"


def rewrite_outputs(command: str, output_dir: Path, caller_type: str, caller_method: str, path_name: str) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe = safe_slug("_".join(part for part in (path_name, caller_type, caller_method) if part))
    md = output_dir / f"{safe}_dossier.md"
    js = output_dir / f"{safe}_dossier.json"
    parts = command.split()
    out: list[str] = []
    i = 0
    while i < len(parts):
        if parts[i] == "--out" and i + 1 < len(parts):
            out.extend(["--out", str(md)])
            i += 2
            continue
        if parts[i] == "--out-json" and i + 1 < len(parts):
            out.extend(["--out-json", str(js)])
            i += 2
            continue
        out.append(parts[i])
        i += 1
    return " ".join(out)


def build_target_command(row: dict[str, Any]) -> str | None:
    target_type = row.get("targetType")
    target_method = row.get("targetMethod")
    if not target_type or not target_method:
        return None
    slug = safe_slug((row.get("path") or "path") + "_target_" + target_type + "_" + target_method)
    return (
        "python experiments\\cpp2il_readable_csharp\\build_method_dossier.py "
        f"--type {target_type} "
        f"--method {target_method} "
        "--address-map experiments\\cpp2il_readable_csharp\\samples\\latest_refresh\\address_map_all_dummydll_methods.json "
        "--include-static-initializers "
        "--max-body-lines 500 "
        "--timeout-seconds 300 "
        f"--out tmp\\cpp2il_experiment\\readable_notes\\{slug}_dossier.md "
        f"--out-json tmp\\cpp2il_experiment\\readable_notes\\{slug}_dossier.json"
    )


def run_command(command: str, cwd: Path) -> dict[str, Any]:
    proc = subprocess.run(command, cwd=str(cwd), shell=True, text=True, capture_output=True)
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--actions", type=Path, required=True)
    ap.add_argument("--action", default="confirm-ordinal-candidate")
    ap.add_argument("--cwd", type=Path, default=Path("."))
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--dossier-output-dir", type=Path, default=Path("experiments/cpp2il_readable_csharp/samples/latest_refresh/action_dossiers"))
    ap.add_argument("--side", choices=["caller", "target"], default="caller")
    args = ap.parse_args()
    data = load_json(args.actions)
    rows = [row for row in data.get("rows") or [] if row.get("action") == args.action]
    results = []
    for row in rows:
        command = build_target_command(row) if args.side == "target" else row.get("dossierCommand")
        if not command:
            results.append({"path": row.get("path"), "error": "missing dossierCommand", "row": row})
            continue
        if args.side == "target":
            dossier_type = row.get("targetType") or "unknown"
            dossier_method = row.get("targetMethod") or "unknown"
        else:
            dossier_type = row.get("callerType") or "unknown"
            dossier_method = row.get("callerMethod") or "unknown"
        command = rewrite_outputs(command, args.dossier_output_dir, dossier_type, dossier_method, row.get("path") or "path")
        result = run_command(command, args.cwd)
        results.append({
            "path": row.get("path"),
            "callerType": row.get("callerType"),
            "callerMethod": row.get("callerMethod"),
            "targetType": row.get("targetType"),
            "targetMethod": row.get("targetMethod"),
            "monoCandidate": row.get("callerMonoMethodCandidate"),
            "targetMonoCandidate": row.get("targetMonoMethodCandidate"),
            "side": args.side,
            "command": command,
            "result": result,
        })
    report = {
        "schema": "unresolved-action-dossier-run.v1",
        "action": args.action,
        "side": args.side,
        "input": str(args.actions),
        "summary": {
            "rows": len(rows),
            "succeeded": sum(1 for r in results if (r.get("result") or {}).get("returncode") == 0),
            "failed": sum(1 for r in results if (r.get("result") or {}).get("returncode") not in (0, None) or r.get("error")),
        },
        "results": results,
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


