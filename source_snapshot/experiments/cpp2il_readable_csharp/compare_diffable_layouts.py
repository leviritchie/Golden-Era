#!/usr/bin/env python3
"""
Compare Cpp2IL DiffableCs type layouts.

This static patch-review tool focuses on deobf-sensitive surface changes:
types, field offsets/types/names, and method signatures. It does not inspect
runtime state or mod code.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from annotate_isil import (
    DEFAULT_DIFFABLE_ROOT,
    FIELD_RE,
    assert_experiment_safe_output,
    markdown_code,
    markdown_table_code,
)


METHOD_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|internal|static|virtual|override|sealed|"
    r"abstract|extern|unsafe|new|readonly|async)\s+)*"
    r"(?P<signature>[A-Za-z_][\w.`<>\[\], ?:]+\s+@?[A-Za-z_][\w]*\s*\([^;{}]*\))\s*(?:\{|;)"
)


@dataclass(frozen=True)
class FieldLayout:
    name: str
    type_name: str
    offset: int


@dataclass(frozen=True)
class TypeLayout:
    type_name: str
    path: str
    fields: tuple[FieldLayout, ...]
    methods: tuple[str, ...]


class ScanTimeoutError(TimeoutError):
    pass


def normalize_type_from_path(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if len(parts) >= 2 and parts[0] == "Hex" and parts[1] == "Hex":
        parts = parts[1:]
    return ".".join(parts).replace("_NestedType_", "+")


def parse_diffable_type(root: Path, path: Path) -> TypeLayout:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    fields: list[FieldLayout] = []
    methods: list[str] = []
    for line in lines:
        field = FIELD_RE.match(line)
        if field:
            fields.append(
                FieldLayout(
                    name=field.group("name"),
                    type_name=field.group("type").strip(),
                    offset=int(field.group("offset"), 16),
                )
            )
            continue
        method = METHOD_RE.match(line)
        if method and " Type: " not in line:
            methods.append(" ".join(method.group("signature").split()))
    return TypeLayout(
        type_name=normalize_type_from_path(root, path),
        path=str(path),
        fields=tuple(fields),
        methods=tuple(sorted(set(methods))),
    )


def candidate_roots_for_prefix(root: Path, type_prefix: str | None) -> list[Path]:
    if not type_prefix:
        return [root]
    parts = type_prefix.split(".")
    candidates = [root / Path(*parts)]
    if parts and parts[0] == "Hex":
        candidates.insert(0, root / "Hex" / Path(*parts))
    existing = []
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir() and candidate not in existing:
            existing.append(candidate)
    if not existing:
        raise FileNotFoundError(
            f"No DiffableCs directory matched type prefix {type_prefix!r} under {root}"
        )
    return existing


def iter_cs_files(root: Path):
    stack = [root]
    while stack:
        current = stack.pop()
        dirs: list[Path] = []
        files: list[Path] = []
        for child in current.iterdir():
            if child.is_dir():
                dirs.append(child)
            elif child.suffix == ".cs":
                files.append(child)
        stack.extend(sorted(dirs, reverse=True))
        yield from sorted(files)


def check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise ScanTimeoutError("DiffableCs layout comparison exceeded timeout")


def scan_diffable_root(
    root: Path,
    type_prefix: str | None,
    max_files: int | None = None,
    deadline: float | None = None,
) -> dict[str, TypeLayout]:
    layouts: dict[str, TypeLayout] = {}
    files_seen = 0
    for scan_root in candidate_roots_for_prefix(root, type_prefix):
        for path in iter_cs_files(scan_root):
            check_deadline(deadline)
            if max_files is not None and files_seen >= max_files:
                return layouts
            files_seen += 1
            layout = parse_diffable_type(root, path)
            if type_prefix and not layout.type_name.startswith(type_prefix):
                continue
            layouts[layout.type_name] = layout
    return layouts


def field_key(field: FieldLayout) -> str:
    return field.name


def fields_by_name(layout: TypeLayout) -> dict[str, FieldLayout]:
    return {field.name: field for field in layout.fields}


def fields_by_offset(layout: TypeLayout) -> dict[int, FieldLayout]:
    return {field.offset: field for field in layout.fields}


def compare_type_layout(old: TypeLayout, new: TypeLayout) -> dict[str, Any]:
    old_by_name = fields_by_name(old)
    new_by_name = fields_by_name(new)
    old_by_offset = fields_by_offset(old)
    new_by_offset = fields_by_offset(new)

    moved_fields = []
    changed_type_fields = []
    for name in sorted(set(old_by_name) & set(new_by_name)):
        old_field = old_by_name[name]
        new_field = new_by_name[name]
        if old_field.offset != new_field.offset:
            moved_fields.append(
                {
                    "field": name,
                    "type": new_field.type_name,
                    "old_offset": f"0x{old_field.offset:X}",
                    "new_offset": f"0x{new_field.offset:X}",
                }
            )
        if old_field.type_name != new_field.type_name:
            changed_type_fields.append(
                {
                    "field": name,
                    "old_type": old_field.type_name,
                    "new_type": new_field.type_name,
                    "offset": f"0x{new_field.offset:X}",
                }
            )

    renamed_at_offsets = []
    for offset in sorted(set(old_by_offset) & set(new_by_offset)):
        old_field = old_by_offset[offset]
        new_field = new_by_offset[offset]
        if old_field.name != new_field.name:
            renamed_at_offsets.append(
                {
                    "offset": f"0x{offset:X}",
                    "old_field": old_field.name,
                    "new_field": new_field.name,
                    "old_type": old_field.type_name,
                    "new_type": new_field.type_name,
                }
            )

    old_methods = set(old.methods)
    new_methods = set(new.methods)
    return {
        "type": new.type_name,
        "old_path": old.path,
        "new_path": new.path,
        "field_count_delta": len(new.fields) - len(old.fields),
        "method_count_delta": len(new.methods) - len(old.methods),
        "added_fields": [
            {
                "field": field.name,
                "type": field.type_name,
                "offset": f"0x{field.offset:X}",
            }
            for name, field in sorted(new_by_name.items())
            if name not in old_by_name
        ],
        "removed_fields": [
            {
                "field": field.name,
                "type": field.type_name,
                "offset": f"0x{field.offset:X}",
            }
            for name, field in sorted(old_by_name.items())
            if name not in new_by_name
        ],
        "moved_fields": moved_fields,
        "changed_field_types": changed_type_fields,
        "renamed_fields_at_same_offset": renamed_at_offsets,
        "added_methods": sorted(new_methods - old_methods),
        "removed_methods": sorted(old_methods - new_methods),
    }


def has_type_changes(change: dict[str, Any]) -> bool:
    return any(
        change[key]
        for key in (
            "added_fields",
            "removed_fields",
            "moved_fields",
            "changed_field_types",
            "renamed_fields_at_same_offset",
            "added_methods",
            "removed_methods",
        )
    )


def change_score(change: dict[str, Any]) -> int:
    return (
        len(change["moved_fields"]) * 8
        + len(change["changed_field_types"]) * 6
        + len(change["added_fields"]) * 4
        + len(change["removed_fields"]) * 4
        + len(change["renamed_fields_at_same_offset"]) * 3
        + len(change["added_methods"])
        + len(change["removed_methods"])
    )


def build_comparison(
    old_root: Path,
    new_root: Path,
    type_prefix: str | None,
    top: int,
    max_files: int | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    old = scan_diffable_root(old_root, type_prefix, max_files, deadline)
    new = scan_diffable_root(new_root, type_prefix, max_files, deadline)
    check_deadline(deadline)
    added_types = sorted(set(new) - set(old))
    removed_types = sorted(set(old) - set(new))
    changed_types = []
    for key in sorted(set(old) & set(new)):
        check_deadline(deadline)
        change = compare_type_layout(old[key], new[key])
        if has_type_changes(change):
            changed_types.append(change)
    check_deadline(deadline)
    changed_types = sorted(changed_types, key=lambda change: (change_score(change), change["type"]), reverse=True)
    return {
        "schema": 1,
        "old_root": str(old_root),
        "new_root": str(new_root),
        "type_prefix": type_prefix,
        "max_files": max_files,
        "timeout_seconds": timeout_seconds,
        "summary": {
            "old_types": len(old),
            "new_types": len(new),
            "added_types": len(added_types),
            "removed_types": len(removed_types),
            "changed_types": len(changed_types),
        },
        "added_types": added_types[:top],
        "removed_types": removed_types[:top],
        "changed_types": changed_types[:top],
    }


def render_field_rows(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    if not rows:
        return ["No entries."]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(markdown_table_code(row.get(column, "")) for column in columns) + " |")
    return lines


def render_methods(methods: list[str]) -> str:
    if not methods:
        return "none"
    return "<br>".join(markdown_table_code(method) for method in methods[:10])


def render_markdown(comparison: dict[str, Any]) -> str:
    summary = comparison["summary"]
    out: list[str] = []
    out.append("# Cpp2IL Diffable Layout Comparison")
    out.append("")
    out.append("This compares Cpp2IL DiffableCs field layouts and method signatures only; it does not use runtime probes.")
    out.append("")
    out.append("## Inputs")
    out.append("")
    out.append(f"- Old DiffableCs root: {markdown_code(comparison['old_root'])}")
    out.append(f"- New DiffableCs root: {markdown_code(comparison['new_root'])}")
    out.append(f"- Type prefix: {markdown_code(comparison.get('type_prefix'))}")
    out.append("")
    out.append("## Summary")
    out.append("")
    out.append(f"- Old types: {markdown_code(summary['old_types'])}")
    out.append(f"- New types: {markdown_code(summary['new_types'])}")
    out.append(f"- Added types: {markdown_code(summary['added_types'])}")
    out.append(f"- Removed types: {markdown_code(summary['removed_types'])}")
    out.append(f"- Changed common types: {markdown_code(summary['changed_types'])}")
    out.append("")
    out.append("Type and member identity comes from Cpp2IL DiffableCs names; obfuscated renames can look like add/remove changes.")
    out.append("")
    out.append("## Changed Types")
    out.append("")
    if not comparison["changed_types"]:
        out.append("No entries.")
    else:
        out.append("| Score | Type | Field delta | Method delta | Added methods | Removed methods |")
        out.append("| ---: | --- | ---: | ---: | --- | --- |")
        for change in comparison["changed_types"]:
            out.append(
                f"| {change_score(change)} | {markdown_table_code(change['type'])} | "
                f"{change['field_count_delta']} | {change['method_count_delta']} | "
                f"{render_methods(change['added_methods'])} | {render_methods(change['removed_methods'])} |"
            )
    out.append("")
    for change in comparison["changed_types"][:5]:
        out.append(f"### {change['type']}")
        out.append("")
        out.append("Moved fields:")
        out.extend(render_field_rows(change["moved_fields"], ["field", "type", "old_offset", "new_offset"]))
        out.append("")
        out.append("Added fields:")
        out.extend(render_field_rows(change["added_fields"], ["field", "type", "offset"]))
        out.append("")
        out.append("Removed fields:")
        out.extend(render_field_rows(change["removed_fields"], ["field", "type", "offset"]))
        out.append("")
        out.append("Renamed fields at same offset:")
        out.extend(render_field_rows(change["renamed_fields_at_same_offset"], ["offset", "old_field", "new_field", "old_type", "new_type"]))
        out.append("")
    out.append("## Added Types")
    out.append("")
    if comparison["added_types"]:
        for type_name in comparison["added_types"]:
            out.append(f"- {markdown_code(type_name)}")
    else:
        out.append("No entries.")
    out.append("")
    out.append("## Removed Types")
    out.append("")
    if comparison["removed_types"]:
        for type_name in comparison["removed_types"]:
            out.append(f"- {markdown_code(type_name)}")
    else:
        out.append("No entries.")
    out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two Cpp2IL DiffableCs layout roots.")
    parser.add_argument("--old-root", type=Path, required=True)
    parser.add_argument("--new-root", type=Path, default=DEFAULT_DIFFABLE_ROOT)
    parser.add_argument("--type-prefix")
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--max-files", type=int, help="Debug/testing cap for visited candidate DiffableCs files per root.")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="Maximum elapsed runtime for scanning and comparing layouts.",
    )
    parser.add_argument("--out-md", type=Path, required=True)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument(
        "--allow-outside-experiment",
        action="store_true",
        help="Allow writing outside the experiment/tmp Cpp2IL areas.",
    )
    args = parser.parse_args()

    if args.top < 1:
        raise ValueError("--top must be positive")
    if args.max_files is not None and args.max_files < 1:
        raise ValueError("--max-files must be positive")
    if args.timeout_seconds < 1:
        raise ValueError("--timeout-seconds must be positive")
    if not args.old_root.is_dir():
        raise FileNotFoundError(f"Old DiffableCs root not found: {args.old_root}")
    if not args.new_root.is_dir():
        raise FileNotFoundError(f"New DiffableCs root not found: {args.new_root}")

    try:
        comparison = build_comparison(
            args.old_root,
            args.new_root,
            args.type_prefix,
            args.top,
            args.max_files,
            args.timeout_seconds,
        )
    except (FileNotFoundError, ScanTimeoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    assert_experiment_safe_output(args.out_md, args.allow_outside_experiment)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(render_markdown(comparison), encoding="utf-8")
    if args.out_json:
        assert_experiment_safe_output(args.out_json, args.allow_outside_experiment)
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    print(f"Wrote layout comparison to {args.out_md}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
