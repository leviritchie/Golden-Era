#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"
DEFAULT_OVERRIDE_DIR = ROOT / "custom_factions" / "law_overrides"

LAW_SID_RE = re.compile(r"^fraction_law_homm3_([a-z0-9_]+)_([0-9]+)$")
RESOURCE_RICHES_RE = re.compile(r"resource\s+riches", re.IGNORECASE)
COMPROMISE_NOTE_RE = re.compile(
    r"(temporary[- ]compromise|runtime[- ]debt|runtime[- ]unproven|runtime disabled|hard case disabled|supported donor compromise|packet[- ]backed|pending no[- ]compromise|\b[a-z-]+ packet\b)",
    re.IGNORECASE,
)
NON_EXACT_STATUSES = {"needs-runtime", "temporary-compromise", "blocked"}


class Audit:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def parse_law_sid(law_sid: str) -> tuple[str, int] | None:
    match = LAW_SID_RE.match(law_sid)
    if not match:
        return None
    return match.group(1), int(match.group(2))


def target_index(doc: Any, audit: Audit) -> tuple[dict[str, dict[str, Any]], set[int]]:
    targets: dict[str, dict[str, Any]] = {}
    family_indices: set[int] = set()
    if not isinstance(doc, dict):
        audit.error("custom law targets root must be an object")
        return targets, family_indices

    families = doc.get("families")
    if isinstance(families, dict):
        for key in families:
            try:
                family_indices.add(int(key))
            except ValueError:
                audit.error(f"family key {key!r} is not an integer")

    raw_targets = doc.get("targets")
    if not isinstance(raw_targets, list):
        audit.error("custom law targets must contain a targets list")
        return targets, family_indices

    for target in raw_targets:
        if not isinstance(target, dict):
            audit.error("target entry must be an object")
            continue
        law_sid = target.get("lawSid")
        if not isinstance(law_sid, str) or not law_sid:
            audit.error(f"target entry has invalid lawSid: {target!r}")
            continue
        if law_sid in targets:
            audit.error(f"{law_sid}: duplicate target entry")
            continue
        targets[law_sid] = target
    return targets, family_indices


def iter_overrides(override_dir: Path) -> list[tuple[Path, str, Any]]:
    entries: list[tuple[Path, str, Any]] = []
    for path in sorted(override_dir.glob("homm3_*.json")):
        doc = load_json(path)
        if not isinstance(doc, dict):
            continue
        overrides = doc.get("lawOverrides")
        if not isinstance(overrides, dict):
            continue
        for law_sid, entry in sorted(overrides.items()):
            if isinstance(law_sid, str):
                entries.append((path, law_sid, entry))
    return entries


def has_parameters(entry: Any) -> bool:
    return isinstance(entry, dict) and isinstance(entry.get("parametersPerLevel"), list)


def note_text(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    notes = entry.get("notes")
    if isinstance(notes, str):
        return notes
    if isinstance(notes, list):
        return " ".join(str(item) for item in notes)
    return ""


def entry_name(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    name = entry.get("nameText")
    return name if isinstance(name, str) else ""


def audit_override_rows(
    targets: dict[str, dict[str, Any]],
    family_indices: set[int],
    override_entries: list[tuple[Path, str, Any]],
    audit: Audit,
) -> dict[str, int]:
    status_counts: dict[str, int] = defaultdict(int)
    seen_override_sids: set[str] = set()

    for path, law_sid, entry in override_entries:
        seen_override_sids.add(law_sid)
        parsed = parse_law_sid(law_sid)
        if parsed is None:
            audit.warn(f"{path.name}:{law_sid}: not a tracked HoMM3 custom law SID")
            continue
        _faction, law_index = parsed
        if law_index not in family_indices:
            continue

        target = targets.get(law_sid)
        if target is None:
            if RESOURCE_RICHES_RE.search(entry_name(entry)):
                audit.error(f"{path.name}:{law_sid}: Resource Riches-like override appears in a tracked family but is not allowed in no-compromise targets")
            else:
                audit.error(f"{path.name}:{law_sid}: tracked law-family override has no target entry")
            continue

        status = str(target.get("implementationStatus") or "unknown")
        status_counts[status] += 1
        if has_parameters(entry) and status in NON_EXACT_STATUSES:
            notes = note_text(entry)
            if not COMPROMISE_NOTE_RE.search(notes):
                audit.error(
                    f"{path.name}:{law_sid}: has parametersPerLevel while target status is {status!r}, but notes do not explicitly mark compromise/runtime debt"
                )
        if status == "native-exact" and "compromise" in note_text(entry).lower():
            audit.warn(f"{path.name}:{law_sid}: target is native-exact but override notes still mention compromise")

    for law_sid, target in sorted(targets.items()):
        if law_sid not in seen_override_sids:
            audit.error(f"{law_sid}: target entry has no current law override row; explicit source rows are required to avoid hidden donor/Core inheritance")
        status = str(target.get("implementationStatus") or "unknown")
        status_counts.setdefault(status, 0)

    return dict(sorted(status_counts.items()))


def emit_markdown(errors: list[str], warnings: list[str], status_counts: dict[str, int]) -> str:
    lines: list[str] = []
    lines.append("# Custom law override target audit")
    lines.append("")
    lines.append("Static audit only. This does not prove Core generation, build success, or runtime behavior.")
    lines.append("")
    lines.append("## Status counts for target-backed override rows")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|---|---:|")
    for status, count in sorted(status_counts.items()):
        lines.append(f"| `{status}` | {count} |")
    lines.append("")
    lines.append("## Errors")
    lines.append("")
    if errors:
        for error in errors:
            lines.append(f"- {error}")
    else:
        lines.append("None.")
    lines.append("")
    lines.append("## Warnings")
    lines.append("")
    if warnings:
        for warning in warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("None.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit current custom law overrides against the no-compromise target spec.")
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS_PATH)
    parser.add_argument("--override-dir", type=Path, default=DEFAULT_OVERRIDE_DIR)
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()

    audit = Audit()
    if not args.targets.exists():
        audit.error(f"missing targets file: {args.targets}")
        print(emit_markdown(audit.errors, audit.warnings, {}) if args.markdown else f"errors: {audit.errors}")
        return 1
    if not args.override_dir.exists():
        audit.error(f"missing law override dir: {args.override_dir}")
        print(emit_markdown(audit.errors, audit.warnings, {}) if args.markdown else f"errors: {audit.errors}")
        return 1

    targets, family_indices = target_index(load_json(args.targets), audit)
    override_entries = iter_overrides(args.override_dir)
    status_counts = audit_override_rows(targets, family_indices, override_entries, audit)

    if args.markdown:
        print(emit_markdown(audit.errors, audit.warnings, status_counts))
    else:
        print(f"target-backed override rows by status: {status_counts}")
        print(f"errors: {audit.errors}")
        if audit.warnings:
            print(f"warnings: {audit.warnings}")
    return 1 if audit.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

