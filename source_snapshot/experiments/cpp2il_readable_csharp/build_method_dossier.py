#!/usr/bin/env python3
"""
Build a focused static evidence dossier for one Cpp2IL type/method.

This is an assumption-audit layer over annotate_isil.py. It deliberately
separates what DiffableCs/ISIL prove from what still requires native
disassembly or runtime proof.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from annotate_isil import (
    DEFAULT_DIFFABLE_ROOT,
    DEFAULT_ISIL_ROOT,
    AddressEntry,
    MethodBlock,
    assert_experiment_safe_output,
    collect_calls,
    filter_methods,
    find_type_file,
    load_address_map,
    markdown_code,
    markdown_table_code,
    parse_fields,
    parse_methods,
    render_markdown as render_type_markdown,
)


DECLARATION_RE = re.compile(
    r"\b(const|readonly|static)\b|//Field offset:",
)
ARRAY_ALLOCATION_RE = re.compile(
    r'\b(?:SzArrayNew|Newarr)\b.*?\((?P<type>[^)]*\[\])\).*?,\s*(?P<count>\d+)\b'
)
NUMERIC_LITERAL_RE = re.compile(r"(?<![\w])(?:0x[0-9A-Fa-f]+|\d+)(?![\w])")


@dataclass(frozen=True)
class DossierTarget:
    type_name: str
    method_filter: str | None
    role: str


class DossierTimeoutError(TimeoutError):
    pass


def check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise DossierTimeoutError("method dossier build exceeded timeout")


def safe_stem(value: str, max_length: int = 120) -> str:
    text = re.sub(r"[^A-Za-z0-9_.+-]+", "_", value).strip("_")
    return (text[:max_length].rstrip("_") or "item")


def find_isil_file(isil_root: Path, type_name: str) -> Path:
    try:
        return find_type_file(isil_root, type_name, ".txt")
    except FileNotFoundError:
        if "+" not in type_name:
            raise
        parent, nested = type_name.split("+", 1)
        parent_path = find_type_file(isil_root, parent, ".txt")
        candidate = parent_path.with_name(f"{parent_path.stem}_NestedType_{nested}.txt")
        if candidate.exists():
            return candidate
        raise


def find_csharp_file(diffable_root: Path, type_name: str) -> Path:
    if "+" in type_name:
        type_name = type_name.split("+", 1)[0]
    return find_type_file(diffable_root, type_name, ".cs")


def parse_fields_for_dossier(csharp_path: Path, type_name: str) -> dict[int, object]:
    if "+" in type_name:
        return {}
    return parse_fields(csharp_path)


def parse_target(value: str) -> DossierTarget:
    if "::" in value:
        type_name, method = value.split("::", 1)
        method = method.strip() or None
    else:
        type_name, method = value, None
    type_name = type_name.strip()
    if not type_name:
        raise ValueError("dossier target must include a type name")
    return DossierTarget(type_name=type_name, method_filter=method, role="target")


def collect_csharp_declarations(csharp_path: Path, limit: int) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    for line_number, line in enumerate(
        csharp_path.read_text(encoding="utf-8", errors="replace").splitlines(),
        start=1,
    ):
        if not DECLARATION_RE.search(line):
            continue
        rows.append((line_number, line.strip()))
        if len(rows) >= limit:
            break
    return rows


def collect_array_allocations(method: MethodBlock, limit: int) -> list[tuple[int, str, str, str]]:
    rows: list[tuple[int, str, str, str]] = []
    for line_number, line in enumerate(method.body, start=1):
        match = ARRAY_ALLOCATION_RE.search(line)
        if not match:
            continue
        rows.append((line_number, match.group("type"), match.group("count"), line.strip()))
        if len(rows) >= limit:
            break
    return rows


def collect_numeric_literal_lines(method: MethodBlock, limit: int) -> list[tuple[int, str, str]]:
    rows: list[tuple[int, str, str]] = []
    for line_number, line in enumerate(method.body, start=1):
        literals = sorted(set(NUMERIC_LITERAL_RE.findall(line)))
        if not literals:
            continue
        rows.append((line_number, ", ".join(literals[:8]), line.strip()))
        if len(rows) >= limit:
            break
    return rows


def collect_pattern_lines(method: MethodBlock, patterns: list[str], limit: int) -> list[tuple[int, str, str]]:
    if not patterns:
        return []
    lowered = [(pattern, pattern.lower()) for pattern in patterns]
    rows: list[tuple[int, str, str]] = []
    for line_number, line in enumerate(method.body, start=1):
        line_lower = line.lower()
        for original, pattern in lowered:
            if pattern in line_lower:
                rows.append((line_number, original, line.strip()))
                break
        if len(rows) >= limit:
            break
    return rows


def collect_method_records(
    diffable_root: Path,
    isil_root: Path,
    target: DossierTarget,
    include_static_initializers: bool,
) -> tuple[Path, Path, list[MethodBlock], list[MethodBlock]]:
    csharp_path = find_csharp_file(diffable_root, target.type_name)
    isil_path = find_isil_file(isil_root, target.type_name)
    all_methods = parse_methods(isil_path)
    methods = filter_methods(all_methods, target.method_filter)
    if target.method_filter and not methods:
        raise ValueError(f"No methods matched {target.type_name}::{target.method_filter}")
    if include_static_initializers:
        existing = {method.signature for method in methods}
        for method in all_methods:
            if ".cctor(" in method.signature and method.signature not in existing:
                methods.append(method)
                existing.add(method.signature)
    return csharp_path, isil_path, all_methods, methods


def render_declaration_table(lines: list[str], declarations: list[tuple[int, str]]) -> None:
    if not declarations:
        return
    lines.append("## DiffableCs Declarations")
    lines.append("")
    lines.append("| Source line | Declaration |")
    lines.append("| ---: | --- |")
    for line_number, declaration in declarations:
        lines.append(f"| {line_number} | {markdown_table_code(declaration)} |")
    lines.append("")


def render_method_highlights(
    lines: list[str],
    target: DossierTarget,
    methods: list[MethodBlock],
    address_map: dict[str, AddressEntry],
    patterns: list[str],
) -> None:
    lines.append("## Evidence Highlights")
    lines.append("")
    lines.append("| Method | Evidence | Body line | Detail | Raw line |")
    lines.append("| --- | --- | ---: | --- | --- |")
    row_count = 0
    for method in methods:
        named_calls, resolved_calls, raw_calls = collect_calls(method, address_map)
        for line_number, type_name, count, raw_line in collect_array_allocations(method, 16):
            lines.append(
                f"| {markdown_table_code(method.signature)} | array allocation | {line_number} | "
                f"{markdown_table_code(f'{type_name} length {count}')} | {markdown_table_code(raw_line)} |"
            )
            row_count += 1
        for line_number, pattern, raw_line in collect_pattern_lines(method, patterns, 16):
            lines.append(
                f"| {markdown_table_code(method.signature)} | pattern match | {line_number} | "
                f"{markdown_table_code(pattern)} | {markdown_table_code(raw_line)} |"
            )
            row_count += 1
        for line_number, literals, raw_line in collect_numeric_literal_lines(method, 8):
            lines.append(
                f"| {markdown_table_code(method.signature)} | numeric literal | {line_number} | "
                f"{markdown_table_code(literals)} | {markdown_table_code(raw_line)} |"
            )
            row_count += 1
        for call in named_calls[:8]:
            lines.append(
                f"| {markdown_table_code(method.signature)} | named call |  | "
                f"{markdown_table_code(call)} |  |"
            )
            row_count += 1
        for call in resolved_calls[:8]:
            lines.append(
                f"| {markdown_table_code(method.signature)} | resolved native call |  | "
                f"{markdown_table_code(call)} |  |"
            )
            row_count += 1
        for call in raw_calls[:8]:
            lines.append(
                f"| {markdown_table_code(method.signature)} | unresolved native call |  | "
                f"{markdown_table_code(call)} |  |"
            )
            row_count += 1
    if row_count == 0:
        lines.append(
            f"| {markdown_table_code(target.type_name)} | no compact highlights |  | "
            "Open the annotated evidence section below. |  |"
        )
    lines.append("")


def render_evidence_boundary(
    lines: list[str],
    target: DossierTarget,
    csharp_path: Path,
    isil_path: Path,
    methods: list[MethodBlock],
    declarations: list[tuple[int, str]],
) -> None:
    lines.append("## Evidence Boundary")
    lines.append("")
    lines.append("### Proven By Static Cpp2IL Output")
    lines.append("")
    lines.append(f"- DiffableCs shell found at {markdown_code(csharp_path)}.")
    lines.append(f"- ISIL dump found at {markdown_code(isil_path)}.")
    lines.append(f"- Matched {markdown_code(len(methods))} method body/bodies for this dossier.")
    if declarations:
        lines.append(f"- Found {markdown_code(len(declarations))} constant/field/static declarations in the C# shell excerpt.")
    if "+" in target.type_name:
        lines.append("- Nested-target field-offset annotation is disabled because nested DiffableCs field scope is not parsed safely yet.")
    if target.method_filter:
        lines.append(f"- Target method filter {markdown_code(target.method_filter)} matched at least one Cpp2IL method signature.")
    lines.append("")
    lines.append("### Static Inferences To Treat Carefully")
    lines.append("")
    lines.append("- Array lengths, numeric literals, field offsets, and call order are useful static evidence, but they do not by themselves prove original source intent.")
    lines.append("- Repeated constants or property IDs should be treated as architectural clues until checked against native disassembly or runtime behavior.")
    lines.append("- Unresolved native addresses are stable evidence only for this exact build unless an imported method-pointer map identifies them.")
    if "+" in target.type_name:
        lines.append("- Parent C# declarations may appear as context for nested targets, but they are not nested field-offset proof.")
    lines.append("")
    lines.append("### Not Traceable From This Dossier Alone")
    lines.append("")
    lines.append("- Original C# source body and exact high-level control flow.")
    lines.append("- Unity runtime ordering such as the first call that initializes a global shader array length.")
    lines.append("- Whether a constructor or static initializer can be reached early enough to preseed runtime state.")
    lines.append("- Semantics of unresolved native callees without native disassembly, imported method-pointer maps, or runtime probes.")
    lines.append("")


def build_dossier_markdown(
    target: DossierTarget,
    related_targets: list[DossierTarget],
    diffable_root: Path,
    isil_root: Path,
    address_map_path: Path | None,
    address_map: dict[str, AddressEntry],
    max_body_lines: int,
    summary_only: bool,
    include_static_initializers: bool,
    declaration_limit: int,
    patterns: list[str],
    deadline: float | None = None,
) -> tuple[str, dict[str, object]]:
    sections: list[str] = []
    manifest_targets: list[dict[str, object]] = []

    check_deadline(deadline)
    csharp_path, isil_path, all_methods, methods = collect_method_records(
        diffable_root,
        isil_root,
        target,
        include_static_initializers,
    )
    check_deadline(deadline)
    declarations = collect_csharp_declarations(csharp_path, declaration_limit)

    sections.append(f"# Cpp2IL Method Evidence Dossier: {target.type_name}")
    sections.append("")
    if target.method_filter:
        sections.append(f"- Target method filter: {markdown_code(target.method_filter)}")
    sections.append(f"- Address map: {markdown_code(address_map_path) if address_map_path else markdown_code('none')}")
    sections.append("- Scope: static Cpp2IL/DiffableCs evidence only; no runtime probes.")
    sections.append("")
    render_evidence_boundary(sections, target, csharp_path, isil_path, methods, declarations)
    render_declaration_table(sections, declarations)
    check_deadline(deadline)
    render_method_highlights(sections, target, methods, address_map, patterns)
    sections.append("## Annotated Target Evidence")
    sections.append("")
    check_deadline(deadline)
    sections.append(
        render_type_markdown(
            target.type_name,
            csharp_path,
            isil_path,
            parse_fields_for_dossier(csharp_path, target.type_name),
            methods,
            all_methods,
            max_body_lines,
            address_map_path,
            address_map,
            summary_only,
        ).rstrip()
    )
    manifest_targets.append(
        {
            "role": target.role,
            "type": target.type_name,
            "method_filter": target.method_filter,
            "csharp_path": str(csharp_path),
            "isil_path": str(isil_path),
            "matched_methods": [method.signature for method in methods],
        }
    )

    for related in related_targets:
        check_deadline(deadline)
        related_csharp, related_isil, related_all, related_methods = collect_method_records(
            diffable_root,
            isil_root,
            related,
            include_static_initializers=True,
        )
        sections.append("")
        sections.append(f"## Related Evidence: {related.type_name}")
        sections.append("")
        check_deadline(deadline)
        sections.append(
            render_type_markdown(
                related.type_name,
                related_csharp,
                related_isil,
                parse_fields_for_dossier(related_csharp, related.type_name),
                related_methods,
                related_all,
                max_body_lines,
                address_map_path,
                address_map,
                summary_only,
            ).rstrip()
        )
        manifest_targets.append(
            {
                "role": related.role,
                "type": related.type_name,
                "method_filter": related.method_filter,
                "csharp_path": str(related_csharp),
                "isil_path": str(related_isil),
                "matched_methods": [method.signature for method in related_methods],
            }
        )

    manifest = {
        "schema": 1,
        "target": target.type_name,
        "method_filter": target.method_filter,
        "address_map": str(address_map_path) if address_map_path else None,
        "include_static_initializers": include_static_initializers,
        "summary_only": summary_only,
        "max_body_lines": max_body_lines,
        "evidence_patterns": patterns,
        "targets": manifest_targets,
    }
    return "\n".join(sections).rstrip() + "\n", manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a focused Cpp2IL method evidence dossier.")
    parser.add_argument("--type", required=True, help="Primary type name.")
    parser.add_argument("--method", help="Primary method name/signature filter.")
    parser.add_argument("--diffable-root", type=Path, default=DEFAULT_DIFFABLE_ROOT)
    parser.add_argument("--isil-root", type=Path, default=DEFAULT_ISIL_ROOT)
    parser.add_argument("--address-map", type=Path, help="Optional address-map JSON.")
    parser.add_argument(
        "--include-static-initializers",
        action="store_true",
        help="Include .cctor methods from primary and related types.",
    )
    parser.add_argument(
        "--include-related",
        action="append",
        default=[],
        metavar="TYPE[::METHOD]",
        help="Additional type/method evidence to include, for example beh+beg::.cctor.",
    )
    parser.add_argument(
        "--evidence-pattern",
        action="append",
        default=[],
        help="Case-insensitive body substring to highlight, such as SetGlobalVectorArray.",
    )
    parser.add_argument("--max-body-lines", type=int, default=500)
    parser.add_argument("--declaration-limit", type=int, default=80)
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="Maximum direct dossier build runtime before failing closed.",
    )
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument(
        "--allow-outside-experiment",
        action="store_true",
        help="Allow writing outside the experiment/tmp Cpp2IL areas.",
    )
    args = parser.parse_args()

    if args.max_body_lines < 1:
        raise ValueError("--max-body-lines must be positive")
    if args.declaration_limit < 1:
        raise ValueError("--declaration-limit must be positive")
    if args.timeout_seconds < 1:
        raise ValueError("--timeout-seconds must be positive")

    target = DossierTarget(args.type, args.method, "target")
    related = [
        DossierTarget(parsed.type_name, parsed.method_filter, "related")
        for parsed in (parse_target(value) for value in args.include_related)
    ]
    address_map = load_address_map(args.address_map)
    try:
        markdown, manifest = build_dossier_markdown(
            target,
            related,
            args.diffable_root,
            args.isil_root,
            args.address_map,
            address_map,
            args.max_body_lines,
            args.summary_only,
            args.include_static_initializers,
            args.declaration_limit,
            args.evidence_pattern,
            time.monotonic() + args.timeout_seconds,
        )
    except DossierTimeoutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    assert_experiment_safe_output(args.out, args.allow_outside_experiment)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(markdown, encoding="utf-8")
    if args.out_json:
        assert_experiment_safe_output(args.out_json, args.allow_outside_experiment)
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote method dossier to {args.out}.")
    if args.out_json:
        print(f"Wrote method dossier manifest to {args.out_json}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
