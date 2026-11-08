#!/usr/bin/env python3
"""Report no-compromise strict-candidate law rows.

This report shows which current target laws are final/native-safe and which
would be stripped in a strict candidate Core until packet-backed behavior is
implemented. It is planning evidence only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"
LAW_OVERRIDE_DIR = ROOT / "custom_factions" / "law_overrides"

NONFINAL_STATUSES = {"needs-runtime", "temporary-compromise", "blocked"}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def load_targets() -> list[dict[str, Any]]:
    doc = load_json(TARGETS_PATH)
    targets = doc.get("targets") if isinstance(doc, dict) else None
    families = doc.get("families") if isinstance(doc, dict) else None
    if not isinstance(targets, list):
        raise ValueError(f"{TARGETS_PATH.relative_to(ROOT)} has no targets list")
    if not isinstance(families, dict):
        raise ValueError(f"{TARGETS_PATH.relative_to(ROOT)} has no families object")
    result: list[dict[str, Any]] = []
    for item in targets:
        if not isinstance(item, dict):
            raise ValueError(f"{TARGETS_PATH.relative_to(ROOT)} contains a non-object target")
        sid = item.get("lawSid")
        law_index = item.get("lawIndex")
        status = item.get("implementationStatus")
        if not isinstance(sid, str) or not sid:
            raise ValueError(f"{TARGETS_PATH.relative_to(ROOT)} contains a target without lawSid")
        if not isinstance(law_index, int):
            raise ValueError(f"{sid} has no integer lawIndex")
        if not isinstance(status, str) or not status:
            raise ValueError(f"{sid} has no implementationStatus")
        family = families.get(str(law_index))
        if not isinstance(family, dict):
            raise ValueError(f"{sid} references unknown law family {law_index}")
        packet = family.get("packet")
        if not isinstance(packet, str) or not packet:
            raise ValueError(f"{sid} law family {law_index} has no packet")
        target = dict(item)
        target["packet"] = packet
        result.append(target)
    return result


def load_override_rows() -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(LAW_OVERRIDE_DIR.glob("*.json")):
        doc = load_json(path)
        overrides = doc.get("lawOverrides") if isinstance(doc, dict) else None
        if not isinstance(overrides, dict):
            raise ValueError(f"{path.relative_to(ROOT)} has no lawOverrides object")
        for sid, row in overrides.items():
            if not isinstance(sid, str):
                raise ValueError(f"{path.relative_to(ROOT)} has a non-string law override key")
            if not isinstance(row, dict):
                raise ValueError(f"{path.relative_to(ROOT)} row for {sid} is not an object")
            if sid in rows:
                raise ValueError(f"duplicate law override row for {sid}")
            rows[sid] = row
    return rows


def bonus_count(row: dict[str, Any] | None) -> int:
    if row is None:
        return 0
    levels = row.get("parametersPerLevel")
    if not isinstance(levels, list):
        return 0
    total = 0
    for level in levels:
        if not isinstance(level, dict):
            continue
        bonuses = level.get("bonuses")
        if isinstance(bonuses, list):
            total += len(bonuses)
    return total


def strict_candidate_action(target: dict[str, Any], row: dict[str, Any] | None) -> str:
    status = target["implementationStatus"]
    count = bonus_count(row)
    if status == "native-exact":
        return "keep-native-row"
    if row is None:
        return "strict-source-missing-row"
    if status in NONFINAL_STATUSES and count > 0:
        return "strip-generated-bonuses-or-implement-packet"
    if status in NONFINAL_STATUSES:
        return "strict-placeholder-ready"
    return "unknown-status-review-required"


def render_report(targets: list[dict[str, Any]], rows: dict[str, dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("# Strict No-Compromise Law Candidate Rows")
    lines.append("")
    lines.append("This report is planning evidence only. It does not build, launch, mutate Core, or prove runtime behavior.")
    lines.append("")
    lines.append("| Faction | Law | Status | Packet | Source bonuses | Strict candidate action |")
    lines.append("|---|---|---|---|---:|---|")
    for target in sorted(targets, key=lambda item: (str(item.get("faction")), int(item.get("lawIndex", -1)))):
        sid = target["lawSid"]
        row = rows.get(sid)
        lines.append(
            "| {faction} | `{sid}` {name} | `{status}` | `{packet}` | {bonuses} | `{action}` |".format(
                faction=target.get("faction", ""),
                sid=sid,
                name=target.get("name", ""),
                status=target.get("implementationStatus", ""),
                packet=target.get("packet", ""),
                bonuses=bonus_count(row),
                action=strict_candidate_action(target, row),
            )
        )
    lines.append("")
    lines.append("Action meanings:")
    lines.append("")
    lines.append("- `keep-native-row`: target is `native-exact`; strict candidates may keep its concrete row.")
    lines.append("- `strip-generated-bonuses-or-implement-packet`: current source row has concrete bonuses but target is not final.")
    lines.append("- `strict-placeholder-ready`: current source row has no concrete bonuses for a non-final target.")
    lines.append("- `strict-source-missing-row`: source override is missing, so inherited donor/Core behavior could survive unless candidate Core validation catches it.")
    lines.append("- `unknown-status-review-required`: target status is not understood by this report.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Emit a strict no-compromise law-row planning report."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional Markdown output path. Writes to stdout when omitted.",
    )
    args = parser.parse_args()

    try:
        report = render_report(load_targets(), load_override_rows())
    except (OSError, json.JSONDecodeError, ValueError) as ex:
        print(f"strict candidate law report failed: {ex}", file=sys.stderr)
        return 1

    if args.out is None:
        print(report)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report + "\n", encoding="utf-8")
        print(f"wrote {args.out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
