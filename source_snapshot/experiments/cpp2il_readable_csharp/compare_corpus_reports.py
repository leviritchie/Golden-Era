#!/usr/bin/env python3
"""
Compare two Cpp2IL corpus JSON reports.

This is a static patch-review aid: it highlights method, triage-score, shape,
and address-table changes between two generated corpus reports without using
runtime probes.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from annotate_isil import assert_experiment_safe_output, markdown_code, markdown_table_code


@dataclass(frozen=True)
class MethodDelta:
    key: str
    type_name: str
    signature: str
    old_score: int
    new_score: int
    score_delta: int
    old_unresolved: int
    new_unresolved: int
    unresolved_delta: int
    old_named: int
    new_named: int
    named_delta: int
    old_shape: str
    new_shape: str


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def method_key(row: dict[str, Any]) -> str:
    return f"{row.get('type', '')}::{row.get('signature', '')}"


def report_methods(report: dict[str, Any], allow_partial_index: bool) -> dict[str, dict[str, Any]]:
    if not has_method_index(report) and not allow_partial_index:
        raise ValueError(
            "Corpus report lacks method_index; rerun build_corpus_report.py or pass "
            "--allow-partial-index to compare exported top-method rows only."
        )
    rows = report.get("method_index") or report.get("top_methods") or []
    return {method_key(row): row for row in rows}


def has_method_index(report: dict[str, Any]) -> bool:
    return isinstance(report.get("method_index"), list)


def address_map_policy(report: dict[str, Any]) -> dict[str, Any]:
    metadata = report.get("address_map_metadata") or {}
    stats = metadata.get("stats") if isinstance(metadata, dict) else {}
    return {
        "known_helper_seed_addresses": stats.get("known_helper_seed_addresses") if isinstance(stats, dict) else None,
        "imported_addresses": stats.get("imported_addresses") if isinstance(stats, dict) else None,
        "total_addresses": stats.get("total_addresses") if isinstance(stats, dict) else None,
        "import_maps": metadata.get("import_maps") if isinstance(metadata, dict) else None,
    }


def build_caveats(old_report: dict[str, Any], new_report: dict[str, Any], allow_partial_index: bool) -> list[str]:
    caveats: list[str] = []
    if not has_method_index(old_report) or not has_method_index(new_report):
        if allow_partial_index:
            caveats.append(
                "At least one input lacks method_index; method added/removed counts compare exported top-method rows only."
            )
        else:
            caveats.append("Both inputs have method_index.")
    old_policy = address_map_policy(old_report)
    new_policy = address_map_policy(new_report)
    if old_policy != new_policy:
        caveats.append(
            "Address-map metadata differs or is unavailable; address deltas may reflect labeling policy changes rather than code changes."
        )
    return caveats


def int_value(row: dict[str, Any], key: str) -> int:
    value = row.get(key, 0)
    return value if isinstance(value, int) else 0


def shape_summary(row: dict[str, Any]) -> str:
    return (
        f"{int_value(row, 'disasm_lines')} asm, "
        f"{int_value(row, 'isil_lines')} isil, "
        f"{int_value(row, 'conditional_jumps')} cond, "
        f"{int_value(row, 'unconditional_jumps')} jmp"
    )


def build_method_deltas(
    old_methods: dict[str, dict[str, Any]],
    new_methods: dict[str, dict[str, Any]],
) -> list[MethodDelta]:
    deltas: list[MethodDelta] = []
    for key in sorted(set(old_methods) & set(new_methods)):
        old = old_methods[key]
        new = new_methods[key]
        old_score = int_value(old, "score")
        new_score = int_value(new, "score")
        old_unresolved = int_value(old, "unresolved_observations")
        new_unresolved = int_value(new, "unresolved_observations")
        old_named = int_value(old, "named_sites")
        new_named = int_value(new, "named_sites")
        old_shape = shape_summary(old)
        new_shape = shape_summary(new)
        if (
            old_score == new_score
            and old_unresolved == new_unresolved
            and old_named == new_named
            and old_shape == new_shape
        ):
            continue
        deltas.append(
            MethodDelta(
                key=key,
                type_name=str(new.get("type") or old.get("type") or ""),
                signature=str(new.get("signature") or old.get("signature") or ""),
                old_score=old_score,
                new_score=new_score,
                score_delta=new_score - old_score,
                old_unresolved=old_unresolved,
                new_unresolved=new_unresolved,
                unresolved_delta=new_unresolved - old_unresolved,
                old_named=old_named,
                new_named=new_named,
                named_delta=new_named - old_named,
                old_shape=old_shape,
                new_shape=new_shape,
            )
        )
    return sorted(
        deltas,
        key=lambda item: (
            abs(item.score_delta),
            abs(item.unresolved_delta),
            abs(item.named_delta),
            item.key,
        ),
        reverse=True,
    )


def row_brief(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": row.get("type", ""),
        "signature": row.get("signature", ""),
        "score": row.get("score", 0),
        "shape": shape_summary(row),
        "unresolved_observations": row.get("unresolved_observations", 0),
        "named_sites": row.get("named_sites", 0),
    }


def address_table(report: dict[str, Any], name: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in report.get(name, []):
        if isinstance(row, dict):
            address = row.get("address")
            observations = row.get("observations")
            if isinstance(address, str) and isinstance(observations, int):
                result[address] = observations
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            address, observations = row[0], row[1]
            if isinstance(address, str) and isinstance(observations, int):
                result[address] = observations
    return result


def build_count_deltas(old: dict[str, int], new: dict[str, int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in sorted(set(old) | set(new)):
        old_count = old.get(key, 0)
        new_count = new.get(key, 0)
        if old_count == new_count:
            continue
        rows.append(
            {
                "key": key,
                "old": old_count,
                "new": new_count,
                "delta": new_count - old_count,
                "status": "added" if key not in old else "removed" if key not in new else "changed",
            }
        )
    return sorted(rows, key=lambda row: (abs(row["delta"]), row["key"]), reverse=True)


def build_comparison(
    old_report: dict[str, Any],
    new_report: dict[str, Any],
    top: int,
    allow_partial_index: bool = False,
) -> dict[str, Any]:
    old_methods = report_methods(old_report, allow_partial_index)
    new_methods = report_methods(new_report, allow_partial_index)
    added_keys = sorted(set(new_methods) - set(old_methods))
    removed_keys = sorted(set(old_methods) - set(new_methods))
    method_deltas = build_method_deltas(old_methods, new_methods)

    unresolved_deltas = build_count_deltas(
        address_table(old_report, "top_unresolved_addresses"),
        address_table(new_report, "top_unresolved_addresses"),
    )
    resolved_deltas = build_count_deltas(
        dict(old_report.get("top_resolved_addresses", [])),
        dict(new_report.get("top_resolved_addresses", [])),
    )

    return {
        "schema": 1,
        "old": {
            "isil_root": old_report.get("isil_root"),
            "address_map": old_report.get("address_map"),
            "type_prefix": old_report.get("type_prefix"),
            "methods": len(old_methods),
            "has_method_index": has_method_index(old_report),
            "method_index_scope": old_report.get("method_index_scope"),
            "address_map_policy": address_map_policy(old_report),
        },
        "new": {
            "isil_root": new_report.get("isil_root"),
            "address_map": new_report.get("address_map"),
            "type_prefix": new_report.get("type_prefix"),
            "methods": len(new_methods),
            "has_method_index": has_method_index(new_report),
            "method_index_scope": new_report.get("method_index_scope"),
            "address_map_policy": address_map_policy(new_report),
        },
        "comparison_scope": "partial_top_methods" if allow_partial_index and (
            not has_method_index(old_report) or not has_method_index(new_report)
        ) else "method_index",
        "caveats": build_caveats(old_report, new_report, allow_partial_index),
        "summary": {
            "added_methods": len(added_keys),
            "removed_methods": len(removed_keys),
            "changed_methods": len(method_deltas),
            "old_methods": len(old_methods),
            "new_methods": len(new_methods),
        },
        "added_methods": [row_brief(new_methods[key]) for key in added_keys[:top]],
        "removed_methods": [row_brief(old_methods[key]) for key in removed_keys[:top]],
        "changed_methods": [
            {
                "type": delta.type_name,
                "signature": delta.signature,
                "old_score": delta.old_score,
                "new_score": delta.new_score,
                "score_delta": delta.score_delta,
                "old_unresolved_observations": delta.old_unresolved,
                "new_unresolved_observations": delta.new_unresolved,
                "unresolved_delta": delta.unresolved_delta,
                "old_named_sites": delta.old_named,
                "new_named_sites": delta.new_named,
                "named_delta": delta.named_delta,
                "old_shape": delta.old_shape,
                "new_shape": delta.new_shape,
            }
            for delta in method_deltas[:top]
        ],
        "top_unresolved_address_deltas": unresolved_deltas[:top],
        "top_resolved_address_deltas": resolved_deltas[:top],
    }


def render_methods_table(rows: list[dict[str, Any]], include_delta: bool) -> list[str]:
    if not rows:
        return ["No entries."]
    if include_delta:
        lines = [
            "| Score delta | Unresolved delta | Named delta | Type | Method | Shape |",
            "| ---: | ---: | ---: | --- | --- | --- |",
        ]
        for row in rows:
            shape = f"{row['old_shape']} -> {row['new_shape']}"
            lines.append(
                f"| {row['score_delta']} | {row['unresolved_delta']} | {row['named_delta']} | "
                f"{markdown_table_code(row['type'])} | {markdown_table_code(row['signature'])} | "
                f"{markdown_table_code(shape)} |"
            )
        return lines

    lines = [
        "| Score | Unresolved obs | Named sites | Type | Method | Shape |",
        "| ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['score']} | {row['unresolved_observations']} | {row['named_sites']} | "
            f"{markdown_table_code(row['type'])} | {markdown_table_code(row['signature'])} | "
            f"{markdown_table_code(row['shape'])} |"
        )
    return lines


def render_address_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["No entries."]
    lines = ["| Delta | Old | New | Status | Key |", "| ---: | ---: | ---: | --- | --- |"]
    for row in rows:
        lines.append(
            f"| {row['delta']} | {row['old']} | {row['new']} | "
            f"{markdown_table_code(row['status'])} | {markdown_table_code(row['key'])} |"
        )
    return lines


def render_markdown(comparison: dict[str, Any]) -> str:
    summary = comparison["summary"]
    out: list[str] = []
    out.append("# Cpp2IL Corpus Comparison")
    out.append("")
    out.append("This compares generated static corpus JSON reports only; it does not use runtime probes.")
    out.append("")
    out.append("## Inputs")
    out.append("")
    out.append(f"- Old ISIL root: {markdown_code(comparison['old'].get('isil_root'))}")
    out.append(f"- New ISIL root: {markdown_code(comparison['new'].get('isil_root'))}")
    out.append(f"- Old address map: {markdown_code(comparison['old'].get('address_map'))}")
    out.append(f"- New address map: {markdown_code(comparison['new'].get('address_map'))}")
    out.append(f"- Type prefix: {markdown_code(comparison['new'].get('type_prefix'))}")
    out.append(f"- Old has method index: {markdown_code(comparison['old'].get('has_method_index'))}")
    out.append(f"- New has method index: {markdown_code(comparison['new'].get('has_method_index'))}")
    out.append(f"- Comparison scope: {markdown_code(comparison.get('comparison_scope'))}")
    out.append("")
    if comparison.get("caveats"):
        out.append("## Caveats")
        out.append("")
        for caveat in comparison["caveats"]:
            out.append(f"- {caveat}")
        out.append("")
    out.append("## Summary")
    out.append("")
    out.append(f"- Old methods indexed: {markdown_code(summary['old_methods'])}")
    out.append(f"- New methods indexed: {markdown_code(summary['new_methods'])}")
    out.append(f"- Added methods: {markdown_code(summary['added_methods'])}")
    out.append(f"- Removed methods: {markdown_code(summary['removed_methods'])}")
    out.append(f"- Changed common methods: {markdown_code(summary['changed_methods'])}")
    out.append("")
    out.append("Method identity is `type + signature`; score and shape deltas are triage hints, not correctness claims.")
    out.append("")
    out.append("## Changed Methods")
    out.append("")
    out.extend(render_methods_table(comparison["changed_methods"], include_delta=True))
    out.append("")
    out.append("## Added Methods")
    out.append("")
    out.extend(render_methods_table(comparison["added_methods"], include_delta=False))
    out.append("")
    out.append("## Removed Methods")
    out.append("")
    out.extend(render_methods_table(comparison["removed_methods"], include_delta=False))
    out.append("")
    out.append("## Top Unresolved Address Table Deltas")
    out.append("")
    out.extend(render_address_table(comparison["top_unresolved_address_deltas"]))
    out.append("")
    out.append("## Top Resolved Address Table Deltas")
    out.append("")
    out.extend(render_address_table(comparison["top_resolved_address_deltas"]))
    out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two Cpp2IL corpus JSON reports.")
    parser.add_argument("--old", type=Path, required=True, help="Old corpus_report.json")
    parser.add_argument("--new", type=Path, required=True, help="New corpus_report.json")
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument(
        "--allow-partial-index",
        action="store_true",
        help="Allow comparison when an input lacks method_index; method counts then use exported top-method rows only.",
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

    try:
        comparison = build_comparison(
            load_report(args.old),
            load_report(args.new),
            args.top,
            args.allow_partial_index,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    assert_experiment_safe_output(args.out_md, args.allow_outside_experiment)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(render_markdown(comparison), encoding="utf-8")
    if args.out_json:
        assert_experiment_safe_output(args.out_json, args.allow_outside_experiment)
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    print(f"Wrote corpus comparison to {args.out_md}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
