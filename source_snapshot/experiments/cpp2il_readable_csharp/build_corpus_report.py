#!/usr/bin/env python3
"""
Build a corpus-level triage report from Cpp2IL ISIL output.

This complements annotate_isil.py: use the corpus report to find suspicious or
high-value methods/addresses, then use annotate_isil.py for focused inspection.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from annotate_isil import (
    AddressEntry,
    DEFAULT_ISIL_ROOT,
    DISASM_CALL_RE,
    ISIL_THIS_OFFSET_RE,
    RAW_CALL_RE,
    REG_OFFSET_RE,
    assert_experiment_safe_output,
    build_readable_named_calls,
    build_readable_named_owner_calls,
    classify_disasm_field_access,
    classify_isil_this_field_access,
    collect_control_summary,
    count_call_sites,
    infer_this_registers,
    iter_named_call_targets,
    load_address_map,
    markdown_table_code,
    named_call_owner,
    normalize_address,
    parse_methods,
)


@dataclass
class MethodRow:
    type_name: str
    signature: str
    path: str
    disasm_lines: int
    isil_lines: int
    conditional_jumps: int
    unconditional_jumps: int
    returns: int
    disasm_native_sites: int
    isil_raw_sites: int
    named_sites: int
    unresolved_observations: int
    unique_unresolved: int
    resolved_observations: int
    score: int
    exact_field_reads: int = 0
    exact_field_writes: int = 0
    possible_field_reads: int = 0
    possible_field_writes: int = 0
    possible_field_refs: int = 0
    unique_field_offsets: int = 0


@dataclass
class AddressHotspot:
    address: str
    observations: int
    method_count: int
    type_count: int
    category: str
    examples: list[tuple[str, int]]


@dataclass
class TypeSummary:
    type_name: str
    method_count: int
    aggregate_score: int
    max_score: int
    conditional_jumps: int
    unresolved_observations: int
    resolved_observations: int
    named_sites: int
    examples: list[tuple[str, int]]


@dataclass(frozen=True)
class FieldOffsetTouch:
    offset: int
    exact_reads: int = 0
    exact_writes: int = 0
    possible_reads: int = 0
    possible_writes: int = 0
    possible_refs: int = 0

    @property
    def total(self) -> int:
        return (
            self.exact_reads
            + self.exact_writes
            + self.possible_reads
            + self.possible_writes
            + self.possible_refs
        )


def path_to_type_name(isil_root: Path, path: Path) -> str:
    rel = path.relative_to(isil_root).with_suffix("")
    parts = list(rel.parts)
    if len(parts) >= 2 and parts[0] == "Hex" and parts[1] == "Hex":
        parts = parts[1:]
    return ".".join(parts).replace("_NestedType_", "+")


class ScanTimeoutError(TimeoutError):
    pass


def check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise ScanTimeoutError("scan exceeded timeout")


def iter_text_files(root: Path, deadline: float | None = None):
    stack = [root]
    while stack:
        check_deadline(deadline)
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda path: path.name.lower())
        except OSError:
            continue
        for entry in reversed(entries):
            if entry.is_dir():
                stack.append(entry)
            elif entry.suffix.lower() == ".txt":
                yield entry


def candidate_roots_for_type_prefix(isil_root: Path, type_prefix: str | None) -> list[Path]:
    if not type_prefix:
        return [isil_root]

    parts = [part for part in type_prefix.replace("+", ".").split(".") if part]
    candidates: list[Path] = []
    if parts and parts[0] == "Hex":
        candidates.append(isil_root / "Hex" / Path(*parts))
    if parts:
        candidates.append(isil_root / Path(*parts))

    existing = []
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir() and candidate not in existing:
            existing.append(candidate)
    if not existing:
        raise FileNotFoundError(f"type prefix has no matching ISIL directory: {type_prefix}")
    return existing


def collect_addresses(method) -> tuple[Counter[str], Counter[str], Counter[str]]:
    disasm = Counter()
    raw = Counter()
    named = Counter()
    in_isil = False
    for line in method.body:
        if line.strip() == "ISIL:":
            in_isil = True
            continue
        if in_isil:
            for target in iter_named_call_targets(line):
                named[target] += 1
            for match in RAW_CALL_RE.finditer(line):
                raw[normalize_address(match.group("target"))] += 1
        else:
            for match in DISASM_CALL_RE.finditer(line):
                disasm[normalize_address(match.group("target"))] += 1
    return disasm, raw, named


def collect_field_offset_touches(method) -> dict[int, FieldOffsetTouch]:
    mutable: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    this_registers = infer_this_registers(method)
    in_isil = False

    for line in method.body:
        stripped = line.strip()
        if stripped == "ISIL:":
            in_isil = True
            continue
        if stripped == "Disassembly:":
            in_isil = False
            continue

        if in_isil:
            for match in ISIL_THIS_OFFSET_RE.finditer(stripped):
                offset = int(match.group("offset"), 16)
                if classify_isil_this_field_access(stripped) == "write":
                    mutable[offset]["exact_writes"] += 1
                else:
                    mutable[offset]["exact_reads"] += 1
        else:
            for match in REG_OFFSET_RE.finditer(stripped):
                reg = match.group("reg")
                if reg not in this_registers:
                    continue
                offset = int(match.group("offset"), 16)
                kind = classify_disasm_field_access(stripped, reg)
                if kind == "write":
                    mutable[offset]["possible_writes"] += 1
                elif kind == "ref":
                    mutable[offset]["possible_refs"] += 1
                else:
                    mutable[offset]["possible_reads"] += 1

    return {
        offset: FieldOffsetTouch(
            offset=offset,
            exact_reads=counts["exact_reads"],
            exact_writes=counts["exact_writes"],
            possible_reads=counts["possible_reads"],
            possible_writes=counts["possible_writes"],
            possible_refs=counts["possible_refs"],
        )
        for offset, counts in mutable.items()
    }


def is_constructor(signature: str) -> bool:
    return ".ctor(" in signature or signature.endswith(" .ctor()")


def classify_unresolved_address(observations: int, method_count: int, type_count: int) -> str:
    if type_count >= 10 or method_count >= 25:
        return "broad runtime helper candidate"
    if type_count >= 3 or method_count >= 8:
        return "shared native helper candidate"
    if observations >= 10 and method_count <= 2:
        return "method-local hot call"
    return "localized unresolved call"


def build_address_hotspots(unresolved_addresses: dict[str, Counter[str]]) -> list[AddressHotspot]:
    hotspots: list[AddressHotspot] = []
    for address, callers in unresolved_addresses.items():
        caller_types = {
            caller.split("::", 1)[0]
            for caller in callers
            if "::" in caller
        }
        observations = sum(callers.values())
        method_count = len(callers)
        type_count = len(caller_types)
        hotspots.append(
            AddressHotspot(
                address=address,
                observations=observations,
                method_count=method_count,
                type_count=type_count,
                category=classify_unresolved_address(observations, method_count, type_count),
                examples=callers.most_common(5),
            )
        )
    return sorted(
        hotspots,
        key=lambda item: (item.type_count, item.method_count, item.observations, item.address),
        reverse=True,
    )


def build_type_summaries(rows: list[MethodRow]) -> list[TypeSummary]:
    by_type: dict[str, list[MethodRow]] = defaultdict(list)
    for row in rows:
        by_type[row.type_name].append(row)

    summaries: list[TypeSummary] = []
    for type_name, type_rows in by_type.items():
        sorted_rows = sorted(type_rows, key=lambda row: row.score, reverse=True)
        summaries.append(
            TypeSummary(
                type_name=type_name,
                method_count=len(type_rows),
                aggregate_score=sum(row.score for row in type_rows),
                max_score=sorted_rows[0].score if sorted_rows else 0,
                conditional_jumps=sum(row.conditional_jumps for row in type_rows),
                unresolved_observations=sum(row.unresolved_observations for row in type_rows),
                resolved_observations=sum(row.resolved_observations for row in type_rows),
                named_sites=sum(row.named_sites for row in type_rows),
                examples=[(row.signature, row.score) for row in sorted_rows[:5]],
            )
        )
    return sorted(
        summaries,
        key=lambda item: (item.aggregate_score, item.max_score, item.unresolved_observations, item.type_name),
        reverse=True,
    )


def address_entry_to_dict(entry: AddressEntry) -> dict[str, Any]:
    return {
        "address": entry.address,
        "kind": entry.kind,
        "label": entry.label,
        "confidence": entry.confidence,
    }


def load_address_map_metadata(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    metadata: dict[str, Any] = {}
    for key in ("schema", "isil_root", "import_maps", "stats"):
        if key in document:
            metadata[key] = document[key]
    return metadata or None


def scan_corpus(
    isil_root: Path,
    address_map,
    type_prefix: str | None,
    max_files: int | None,
    include_constructors: bool,
    timeout_seconds: int | None = None,
):
    methods: list[MethodRow] = []
    ranked_methods: list[MethodRow] = []
    unresolved_addresses: dict[str, Counter[str]] = defaultdict(Counter)
    resolved_addresses = Counter()
    named_calls = Counter()
    named_callers: dict[str, Counter[str]] = defaultdict(Counter)
    named_call_owners = Counter()
    named_owner_calls: dict[str, Counter[str]] = defaultdict(Counter)
    field_touch_methods: dict[int, Counter[str]] = defaultdict(Counter)
    files_seen = 0
    deadline = time.monotonic() + timeout_seconds if timeout_seconds else None

    for root in candidate_roots_for_type_prefix(isil_root, type_prefix):
        for path in iter_text_files(root, deadline):
            check_deadline(deadline)
            if max_files is not None and files_seen >= max_files:
                break
            files_seen += 1
            type_name = path_to_type_name(isil_root, path)
            if type_prefix and not type_name.startswith(type_prefix):
                continue
            for method in parse_methods(path):
                check_deadline(deadline)
                control = collect_control_summary(method)
                calls = count_call_sites(method, address_map)
                eligible = include_constructors or not is_constructor(method.signature)
                disasm_calls, raw_calls, named = collect_addresses(method)
                field_touches = collect_field_offset_touches(method)
                if eligible:
                    named_calls.update(named)
                    caller_key = f"{type_name}::{method.signature}"
                    for name, count in named.items():
                        named_callers[name][caller_key] += count
                        owner = named_call_owner(name)
                        named_call_owners[owner] += count
                        named_owner_calls[owner][name] += count
                    for address, count in (disasm_calls + raw_calls).items():
                        if address in address_map:
                            resolved_addresses[address] += count
                        else:
                            unresolved_addresses[address][caller_key] += count
                    for offset, touch in field_touches.items():
                        field_touch_methods[offset][caller_key] += touch.total

                score = (
                    calls.unique_unresolved_native * 20
                    + control.conditional_jumps
                    + control.unconditional_jumps * 2
                    + max(0, control.disasm_lines // 25)
                )
                methods.append(
                    row := MethodRow(
                        type_name=type_name,
                        signature=method.signature,
                        path=str(path),
                        disasm_lines=control.disasm_lines,
                        isil_lines=control.isil_lines,
                        conditional_jumps=control.conditional_jumps,
                        unconditional_jumps=control.unconditional_jumps,
                        returns=control.returns,
                        disasm_native_sites=calls.disasm_native_sites,
                        isil_raw_sites=calls.isil_raw_sites,
                        named_sites=calls.named_sites,
                        unresolved_observations=calls.unresolved_native_observations,
                        unique_unresolved=calls.unique_unresolved_native,
                        resolved_observations=calls.resolved_native_observations,
                        score=score,
                        exact_field_reads=sum(touch.exact_reads for touch in field_touches.values()),
                        exact_field_writes=sum(touch.exact_writes for touch in field_touches.values()),
                        possible_field_reads=sum(touch.possible_reads for touch in field_touches.values()),
                        possible_field_writes=sum(touch.possible_writes for touch in field_touches.values()),
                        possible_field_refs=sum(touch.possible_refs for touch in field_touches.values()),
                        unique_field_offsets=len(field_touches),
                    )
                )
                if eligible:
                    ranked_methods.append(row)
        if max_files is not None and files_seen >= max_files:
            break

    return {
        "files_seen": files_seen,
        "methods": methods,
        "ranked_methods": ranked_methods,
        "unresolved_addresses": unresolved_addresses,
        "resolved_addresses": resolved_addresses,
        "named_calls": named_calls,
        "named_callers": named_callers,
        "named_call_owners": named_call_owners,
        "named_owner_calls": named_owner_calls,
        "field_touch_methods": field_touch_methods,
    }


def row_to_dict(row: MethodRow) -> dict[str, Any]:
    return {
        "type": row.type_name,
        "signature": row.signature,
        "path": row.path,
        "score": row.score,
        "disasm_lines": row.disasm_lines,
        "isil_lines": row.isil_lines,
        "conditional_jumps": row.conditional_jumps,
        "unconditional_jumps": row.unconditional_jumps,
        "returns": row.returns,
        "disasm_native_sites": row.disasm_native_sites,
        "isil_raw_sites": row.isil_raw_sites,
        "named_sites": row.named_sites,
        "unresolved_observations": row.unresolved_observations,
        "unique_unresolved": row.unique_unresolved,
        "resolved_observations": row.resolved_observations,
        "field_observations": {
            "exact_reads": row.exact_field_reads,
            "exact_writes": row.exact_field_writes,
            "possible_reads": row.possible_field_reads,
            "possible_writes": row.possible_field_writes,
            "possible_refs": row.possible_field_refs,
            "unique_offsets": row.unique_field_offsets,
        },
    }


def render_markdown(report: dict[str, Any], top: int) -> str:
    methods: list[MethodRow] = report["methods"]
    ranked_methods: list[MethodRow] = report["ranked_methods"]
    top_methods = sorted(ranked_methods, key=lambda row: row.score, reverse=True)[:top]
    top_unresolved = sorted(
        report["unresolved_addresses"].items(),
        key=lambda item: sum(item[1].values()),
        reverse=True,
    )[:top]
    address_hotspots = build_address_hotspots(report["unresolved_addresses"])[:top]
    top_named = report["named_calls"].most_common(top)
    top_named_owners = report["named_call_owners"].most_common(top)
    readable_named_calls = build_readable_named_calls(report["named_calls"])
    readable_named_owners, readable_named_owner_calls = build_readable_named_owner_calls(report["named_calls"])
    top_resolved = report["resolved_addresses"].most_common(top)
    top_types = build_type_summaries(ranked_methods)[:top]
    top_field_access_methods = sorted(
        ranked_methods,
        key=lambda row: (
            row.exact_field_writes + row.possible_field_writes,
            row.unique_field_offsets,
            row.exact_field_reads + row.possible_field_reads + row.possible_field_refs,
            row.score,
        ),
        reverse=True,
    )[:top]
    field_touch_methods = report.get("field_touch_methods", {})
    top_numeric_field_offsets = sorted(
        field_touch_methods.items(),
        key=lambda item: (sum(item[1].values()), len(item[1]), item[0]),
        reverse=True,
    )[:top]

    out: list[str] = []
    out.append("# Cpp2IL Corpus Triage Report")
    out.append("")
    out.append("## Summary")
    out.append("")
    out.append(f"- Files scanned: `{report['files_seen']}`")
    out.append(f"- Methods scanned: `{len(methods)}`")
    out.append(f"- Methods eligible for ranked triage: `{len(ranked_methods)}`")
    out.append(f"- Unique unresolved native addresses: `{len(report['unresolved_addresses'])}`")
    out.append(f"- Unique resolved native/helper addresses: `{len(report['resolved_addresses'])}`")
    out.append(f"- Unique named Cpp2IL calls: `{len(report['named_calls'])}`")
    out.append(f"- Unique human-readable named calls: `{len(readable_named_calls)}`")
    out.append("")
    out.append("Scores are triage heuristics, not correctness claims. Address and named-call tables use the same constructor filter as ranked methods.")
    out.append("")

    out.append("## Top Types By Aggregate Triage")
    out.append("")
    out.append("Type totals group ranked methods so review can prioritize whole classes; aggregate score is a triage heuristic, not a correctness claim.")
    out.append("")
    out.append("| Aggregate score | Type | Methods | Max method score | Branches | Calls | Top methods |")
    out.append("| ---: | --- | ---: | ---: | ---: | --- | --- |")
    for summary in top_types:
        calls = (
            f"{summary.unresolved_observations} unresolved obs; "
            f"{summary.resolved_observations} resolved; {summary.named_sites} named"
        )
        examples = "<br>".join(
            f"{markdown_table_code(signature)} ({score})"
            for signature, score in summary.examples[:3]
        )
        out.append(
            f"| {summary.aggregate_score} | {markdown_table_code(summary.type_name)} | "
            f"{summary.method_count} | {summary.max_score} | {summary.conditional_jumps} | "
            f"{markdown_table_code(calls)} | {examples} |"
        )
    out.append("")

    out.append("## Highest Triage Score Methods")
    out.append("")
    out.append("| Score | Type | Method | Shape | Calls | File |")
    out.append("| ---: | --- | --- | --- | --- | --- |")
    for row in top_methods:
        shape = (
            f"{row.disasm_lines} asm, {row.isil_lines} isil, "
            f"{row.conditional_jumps} cond, {row.unconditional_jumps} jmp"
        )
        calls = (
            f"{row.unresolved_observations} unresolved obs / "
            f"{row.unique_unresolved} unique; {row.resolved_observations} resolved"
        )
        out.append(
            f"| {row.score} | {markdown_table_code(row.type_name)} | {markdown_table_code(row.signature)} | "
            f"{markdown_table_code(shape)} | {markdown_table_code(calls)} | {markdown_table_code(row.path)} |"
        )
    out.append("")

    out.append("## Field Access Candidate Methods")
    out.append("")
    out.append(
        "Raw field-offset observations from exact ISIL `this` offsets and possible native `this` registers; possible observations require focused body audit."
    )
    out.append("")
    out.append("| Writes | Reads | Address/ref | Unique offsets | Method | File |")
    out.append("| ---: | ---: | ---: | ---: | --- | --- |")
    for row in top_field_access_methods:
        writes = row.exact_field_writes + row.possible_field_writes
        reads = row.exact_field_reads + row.possible_field_reads
        refs = row.possible_field_refs
        if not (writes or reads or refs):
            continue
        write_text = f"{writes} ({row.exact_field_writes} exact, {row.possible_field_writes} possible)"
        read_text = f"{reads} ({row.exact_field_reads} exact, {row.possible_field_reads} possible)"
        ref_text = f"{refs} possible"
        method = f"{row.type_name}::{row.signature}"
        out.append(
            f"| {markdown_table_code(write_text)} | {markdown_table_code(read_text)} | "
            f"{markdown_table_code(ref_text)} | {row.unique_field_offsets} | "
            f"{markdown_table_code(method)} | {markdown_table_code(row.path)} |"
        )
    out.append("")

    out.append("## Common Numeric Field Offset Hotspots")
    out.append("")
    out.append(
        "Offsets are raw static locations and are type-relative, not shared field identities; open focused notes for exact field labels when diffable C# is available."
    )
    out.append("")
    out.append("| Offset | Observations | Methods | Example callers |")
    out.append("| --- | ---: | ---: | --- |")
    for offset, callers in top_numeric_field_offsets:
        examples = "<br>".join(
            f"{markdown_table_code(name)} ({count})"
            for name, count in callers.most_common(3)
        )
        out.append(
            f"| {markdown_table_code(f'0x{offset:X}')} | {sum(callers.values())} | "
            f"{len(callers)} | {examples} |"
        )
    out.append("")

    out.append("## Top Unresolved Native Addresses")
    out.append("")
    out.append("| Address | Observations | Example callers |")
    out.append("| --- | ---: | --- |")
    for address, callers in top_unresolved:
        total = sum(callers.values())
        examples = "<br>".join(f"{markdown_table_code(name)} ({count})" for name, count in callers.most_common(3))
        out.append(f"| {markdown_table_code(address)} | {total} | {examples} |")
    out.append("")

    out.append("## Address Hotspots To Map Next")
    out.append("")
    out.append("Categories are heuristics for prioritizing static analysis, not identity claims.")
    out.append("")
    out.append("| Address | Category | Methods | Types | Observations | Example callers |")
    out.append("| --- | --- | ---: | ---: | ---: | --- |")
    for hotspot in address_hotspots:
        examples = "<br>".join(
            f"{markdown_table_code(name)} ({count})"
            for name, count in hotspot.examples[:3]
        )
        out.append(
            f"| {markdown_table_code(hotspot.address)} | {markdown_table_code(hotspot.category)} | "
            f"{hotspot.method_count} | {hotspot.type_count} | {hotspot.observations} | {examples} |"
        )
    out.append("")

    out.append("## Top Resolved Helper/Native Addresses")
    out.append("")
    out.append("| Address | Observations |")
    out.append("| --- | ---: |")
    for address, count in top_resolved:
        out.append(f"| {markdown_table_code(address)} | {count} |")
    out.append("")

    out.append("## Top Named Cpp2IL Calls")
    out.append("")
    out.append("| Name | Observations | Example callers |")
    out.append("| --- | ---: | --- |")
    for name, count in top_named:
        callers = report["named_callers"].get(name, Counter())
        examples = "<br>".join(
            f"{markdown_table_code(caller)} ({caller_count})"
            for caller, caller_count in callers.most_common(3)
        )
        out.append(f"| {markdown_table_code(name)} | {count} | {examples} |")
    out.append("")

    out.append("## Top Human-Readable Named Calls")
    out.append("")
    out.append("This filters out global IL2CPP helpers and short obfuscated owner/member names; it is a review convenience, not a semantic proof.")
    out.append("")
    out.append("| Name | Observations | Example callers |")
    out.append("| --- | ---: | --- |")
    for name, count in readable_named_calls.most_common(top):
        callers = report["named_callers"].get(name, Counter())
        examples = "<br>".join(
            f"{markdown_table_code(caller)} ({caller_count})"
            for caller, caller_count in callers.most_common(3)
        )
        out.append(f"| {markdown_table_code(name)} | {count} | {examples} |")
    out.append("")

    out.append("## Top Named Call Target Prefixes")
    out.append("")
    out.append("Owners are derived from Cpp2IL call target text before the final `.`; they are grouping hints, not semantic identity claims.")
    out.append("")
    out.append("| Owner | Observations | Example calls |")
    out.append("| --- | ---: | --- |")
    for owner, count in top_named_owners:
        calls = report["named_owner_calls"].get(owner, Counter())
        examples = "<br>".join(
            f"{markdown_table_code(call)} ({call_count})"
            for call, call_count in calls.most_common(3)
        )
        out.append(f"| {markdown_table_code(owner)} | {count} | {examples} |")
    out.append("")

    out.append("## Top Human-Readable Call Target Prefixes")
    out.append("")
    out.append("This is the owner-level view of the filtered human-readable call table above.")
    out.append("")
    out.append("| Owner | Observations | Example calls |")
    out.append("| --- | ---: | --- |")
    for owner, count in readable_named_owners.most_common(top):
        calls = readable_named_owner_calls.get(owner, Counter())
        examples = "<br>".join(
            f"{markdown_table_code(call)} ({call_count})"
            for call, call_count in calls.most_common(3)
        )
        out.append(f"| {markdown_table_code(owner)} | {count} | {examples} |")
    out.append("")
    return "\n".join(out)


def build_json_doc(
    report: dict[str, Any],
    address_map: dict[str, AddressEntry],
    isil_root: Path,
    address_map_path: Path | None,
    type_prefix: str | None,
    include_constructors: bool,
    top: int,
) -> dict[str, Any]:
    readable_named_calls = build_readable_named_calls(report["named_calls"])
    readable_owners, readable_owner_calls = build_readable_named_owner_calls(report["named_calls"])
    field_touch_methods = report.get("field_touch_methods", {})
    top_field_access_methods = sorted(
        report["ranked_methods"],
        key=lambda row: (
            row.exact_field_writes + row.possible_field_writes,
            row.unique_field_offsets,
            row.exact_field_reads + row.possible_field_reads + row.possible_field_refs,
            row.score,
        ),
        reverse=True,
    )[:top]
    return {
        "isil_root": str(isil_root),
        "address_map": str(address_map_path) if address_map_path else None,
        "type_prefix": type_prefix,
        "files_seen": report["files_seen"],
        "methods_scanned": len(report["methods"]),
        "ranked_methods": len(report["ranked_methods"]),
        "include_constructors": include_constructors,
        "readable_named_calls": len(readable_named_calls),
        "top_methods": [
            row_to_dict(row)
            for row in sorted(report["ranked_methods"], key=lambda r: r.score, reverse=True)[:top]
        ],
        "method_index": [
            row_to_dict(row)
            for row in sorted(report["methods"], key=lambda r: (r.type_name, r.signature))
        ],
        "method_index_scope": "all_scanned_methods",
        "top_types": [
            {
                "type": summary.type_name,
                "method_count": summary.method_count,
                "aggregate_score": summary.aggregate_score,
                "max_score": summary.max_score,
                "conditional_jumps": summary.conditional_jumps,
                "unresolved_observations": summary.unresolved_observations,
                "resolved_observations": summary.resolved_observations,
                "named_sites": summary.named_sites,
                "examples": summary.examples,
            }
            for summary in build_type_summaries(report["ranked_methods"])[:top]
        ],
        "top_field_access_methods": [
            row_to_dict(row)
            for row in top_field_access_methods
            if (
                row.exact_field_writes
                or row.possible_field_writes
                or row.exact_field_reads
                or row.possible_field_reads
                or row.possible_field_refs
            )
        ],
        "top_numeric_field_offset_hotspots": [
            {
                "offset": f"0x{offset:X}",
                "observations": sum(callers.values()),
                "method_count": len(callers),
                "examples": callers.most_common(10),
            }
            for offset, callers in sorted(
                field_touch_methods.items(),
                key=lambda item: (sum(item[1].values()), len(item[1]), item[0]),
                reverse=True,
            )[:top]
        ],
        "top_unresolved_addresses": [
            {
                "address": address,
                "observations": sum(callers.values()),
                "examples": callers.most_common(10),
            }
            for address, callers in sorted(
                report["unresolved_addresses"].items(),
                key=lambda item: sum(item[1].values()),
                reverse=True,
            )[:top]
        ],
        "address_hotspots": [
            {
                "address": hotspot.address,
                "category": hotspot.category,
                "observations": hotspot.observations,
                "method_count": hotspot.method_count,
                "type_count": hotspot.type_count,
                "examples": hotspot.examples,
            }
            for hotspot in build_address_hotspots(report["unresolved_addresses"])[:top]
        ],
        "top_named_calls": report["named_calls"].most_common(top),
        "top_named_callers": [
            {
                "name": name,
                "observations": count,
                "examples": report["named_callers"].get(name, Counter()).most_common(10),
            }
            for name, count in report["named_calls"].most_common(top)
        ],
        "top_named_owners": [
            {
                "owner": owner,
                "observations": count,
                "examples": report["named_owner_calls"].get(owner, Counter()).most_common(10),
            }
            for owner, count in report["named_call_owners"].most_common(top)
        ],
        "top_readable_named_calls": readable_named_calls.most_common(top),
        "top_readable_named_callers": [
            {
                "name": name,
                "observations": count,
                "examples": report["named_callers"].get(name, Counter()).most_common(10),
            }
            for name, count in readable_named_calls.most_common(top)
        ],
        "top_readable_named_owners": [
            {
                "owner": owner,
                "observations": count,
                "examples": readable_owner_calls.get(owner, Counter()).most_common(10),
            }
            for owner, count in readable_owners.most_common(top)
        ],
        "top_resolved_addresses": report["resolved_addresses"].most_common(top),
        "resolved_address_map_entries": [
            address_entry_to_dict(entry)
            for address, entry in sorted(address_map.items())
            if address in report["resolved_addresses"]
        ],
        "address_map_metadata": load_address_map_metadata(address_map_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a corpus-level Cpp2IL readability report.")
    parser.add_argument("--isil-root", type=Path, default=DEFAULT_ISIL_ROOT)
    parser.add_argument("--address-map", type=Path, help="Optional address-map JSON.")
    parser.add_argument("--type-prefix", help="Only scan types whose inferred name starts with this prefix.")
    parser.add_argument("--max-files", type=int, help="Debug/testing limit for scanned files.")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="Maximum direct scan runtime before failing closed.",
    )
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument(
        "--include-constructors",
        action="store_true",
        help="Include .ctor methods in ranked method tables.",
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

    address_map = load_address_map(args.address_map)
    try:
        report = scan_corpus(
            args.isil_root,
            address_map,
            args.type_prefix,
            args.max_files,
            args.include_constructors,
            args.timeout_seconds,
        )
    except (FileNotFoundError, ScanTimeoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    markdown = render_markdown(report, args.top)

    assert_experiment_safe_output(args.out_md, args.allow_outside_experiment)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(markdown, encoding="utf-8")

    if args.out_json:
        assert_experiment_safe_output(args.out_json, args.allow_outside_experiment)
        json_doc = build_json_doc(
            report,
            address_map,
            args.isil_root,
            args.address_map,
            args.type_prefix,
            args.include_constructors,
            args.top,
        )
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(json_doc, indent=2), encoding="utf-8")

    print(f"Scanned {report['files_seen']} files / {len(report['methods'])} methods.")
    print(f"Wrote {args.out_md}.")
    if args.out_json:
        print(f"Wrote {args.out_json}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
