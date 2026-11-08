#!/usr/bin/env python3
"""
Build a compact static review pack from Cpp2IL readable-C# outputs.

The pack contains a corpus triage report plus focused method notes for the
highest-ranked methods. It is intentionally static-only and uses the same
experiment output guard as the underlying tools.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from annotate_isil import (
    DEFAULT_DIFFABLE_ROOT,
    DEFAULT_ISIL_ROOT,
    assert_experiment_safe_output,
    find_type_file,
    load_address_map,
    markdown_code,
    parse_fields,
    parse_methods,
    render_markdown as render_type_markdown,
)
from build_corpus_report import (
    ScanTimeoutError,
    build_json_doc,
    render_markdown as render_corpus_markdown,
    row_to_dict,
    scan_corpus,
)


@dataclass
class FocusedNote:
    rank: int
    type_name: str
    signature: str
    score: int
    path: Path | None = None
    error: str | None = None


def safe_stem(value: str, max_length: int = 90) -> str:
    text = re.sub(r"[^A-Za-z0-9_.+-]+", "_", value).strip("_")
    if not text:
        return "item"
    return text[:max_length].rstrip("_") or "item"


def find_method_by_signature(methods, signature: str):
    for method in methods:
        if method.signature == signature:
            return method
    return None


def clean_focused_output_dir(out_dir: Path, allow_outside_experiment: bool) -> None:
    focused_dir = out_dir / "focused"
    if not focused_dir.exists():
        return
    for path in focused_dir.glob("*.md"):
        assert_experiment_safe_output(path, allow_outside_experiment)
        path.unlink()


def build_focused_note(
    row,
    rank: int,
    out_dir: Path,
    diffable_root: Path,
    isil_root: Path,
    address_map_path: Path | None,
    address_map,
    max_body_lines: int,
    summary_only: bool,
    allow_outside_experiment: bool,
) -> FocusedNote:
    note = FocusedNote(rank=rank, type_name=row.type_name, signature=row.signature, score=row.score)
    try:
        csharp_path = find_type_file(diffable_root, row.type_name, ".cs")
        isil_path = Path(row.path)
        if not isil_path.exists():
            isil_path = find_type_file(isil_root, row.type_name, ".txt")
        all_methods = parse_methods(isil_path)
        method = find_method_by_signature(all_methods, row.signature)
        if method is None:
            raise ValueError(f"Method signature not found in ISIL: {row.signature}")
        fields = parse_fields(csharp_path)
        markdown = render_type_markdown(
            row.type_name,
            csharp_path,
            isil_path,
            fields,
            [method],
            all_methods,
            max_body_lines,
            address_map_path,
            address_map,
            summary_only,
        )
        file_name = f"{rank:02d}_{safe_stem(row.type_name)}_{safe_stem(method.short_name, 32)}.md"
        note.path = out_dir / "focused" / file_name
        assert_experiment_safe_output(note.path, allow_outside_experiment)
        note.path.parent.mkdir(parents=True, exist_ok=True)
        note.path.write_text(markdown, encoding="utf-8")
    except Exception as exc:  # Report and continue so the pack index explains gaps.
        note.error = f"{type(exc).__name__}: {exc}"
    return note


def render_index(report: dict, focused_notes: list[FocusedNote], corpus_md: Path, corpus_json: Path) -> str:
    lines: list[str] = []
    lines.append("# Cpp2IL Static Review Pack")
    lines.append("")
    lines.append("This pack is generated from Cpp2IL static output only; it does not use runtime probes.")
    lines.append("")
    lines.append("## Corpus")
    lines.append("")
    lines.append(f"- Corpus report: {markdown_code(corpus_md)}")
    lines.append(f"- Corpus JSON: {markdown_code(corpus_json)}")
    lines.append(f"- Files scanned: {markdown_code(report['files_seen'])}")
    lines.append(f"- Methods scanned: {markdown_code(len(report['methods']))}")
    lines.append(f"- Ranked methods: {markdown_code(len(report['ranked_methods']))}")
    lines.append(f"- Unresolved native addresses: {markdown_code(len(report['unresolved_addresses']))}")
    lines.append("")
    lines.append("## Focused Notes")
    lines.append("")
    lines.append("| Rank | Score | Method | Note |")
    lines.append("| ---: | ---: | --- | --- |")
    for note in focused_notes:
        method = f"{note.type_name}::{note.signature}"
        if note.path is not None:
            note_cell = markdown_code(note.path)
        else:
            note_cell = f"skipped: {markdown_code(note.error or 'unknown error')}"
        lines.append(f"| {note.rank} | {note.score} | {markdown_code(method)} | {note_cell} |")
    lines.append("")
    lines.append("## Next Static Steps")
    lines.append("")
    lines.append("- Map broad unresolved helper candidates first, then regenerate this pack.")
    lines.append("- Open focused notes for high-score methods before reading full body dumps.")
    lines.append("- Import exact managed method-pointer maps when available to improve call labels.")
    lines.append("")
    return "\n".join(lines)


def focused_note_to_dict(note: FocusedNote) -> dict[str, object]:
    return {
        "rank": note.rank,
        "type": note.type_name,
        "signature": note.signature,
        "score": note.score,
        "path": str(note.path) if note.path else None,
        "error": note.error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a static Cpp2IL review pack.")
    parser.add_argument("--diffable-root", type=Path, default=DEFAULT_DIFFABLE_ROOT)
    parser.add_argument("--isil-root", type=Path, default=DEFAULT_ISIL_ROOT)
    parser.add_argument("--address-map", type=Path, help="Optional address-map JSON.")
    parser.add_argument("--type-prefix", help="Only scan types whose inferred name starts with this prefix.")
    parser.add_argument("--max-files", type=int, help="Debug/testing limit for scanned ISIL files.")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="Maximum direct corpus scan runtime before failing closed.",
    )
    parser.add_argument("--top", type=int, default=8, help="Number of focused notes to generate.")
    parser.add_argument("--corpus-top", type=int, default=25, help="Rows to include in corpus report tables.")
    parser.add_argument("--max-body-lines", type=int, default=300)
    parser.add_argument("--summary-only", action="store_true", help="Generate focused notes without body dumps.")
    parser.add_argument("--include-constructors", action="store_true")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--allow-outside-experiment",
        action="store_true",
        help="Allow writing outside the experiment/tmp Cpp2IL areas.",
    )
    args = parser.parse_args()

    if args.top < 1:
        raise ValueError("--top must be positive")
    if args.corpus_top < 1:
        raise ValueError("--corpus-top must be positive")
    if args.max_body_lines < 1:
        raise ValueError("--max-body-lines must be positive")
    if args.max_files is not None and args.max_files < 1:
        raise ValueError("--max-files must be positive")
    if args.timeout_seconds < 1:
        raise ValueError("--timeout-seconds must be positive")

    assert_experiment_safe_output(args.out_dir / "index.md", args.allow_outside_experiment)
    args.out_dir.mkdir(parents=True, exist_ok=True)

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
    corpus_md = args.out_dir / "corpus_report.md"
    corpus_json = args.out_dir / "corpus_report.json"
    assert_experiment_safe_output(corpus_md, args.allow_outside_experiment)
    assert_experiment_safe_output(corpus_json, args.allow_outside_experiment)
    corpus_md.write_text(render_corpus_markdown(report, args.corpus_top), encoding="utf-8")
    corpus_json.write_text(
        json.dumps(
            build_json_doc(
                report,
                address_map,
                args.isil_root,
                args.address_map,
                args.type_prefix,
                args.include_constructors,
                args.corpus_top,
            ),
            indent=2,
        ),
        encoding="utf-8",
    )

    focused_rows = sorted(report["ranked_methods"], key=lambda row: row.score, reverse=True)[: args.top]
    clean_focused_output_dir(args.out_dir, args.allow_outside_experiment)
    focused_notes = [
        build_focused_note(
            row,
            rank,
            args.out_dir,
            args.diffable_root,
            args.isil_root,
            args.address_map,
            address_map,
            args.max_body_lines,
            args.summary_only,
            args.allow_outside_experiment,
        )
        for rank, row in enumerate(focused_rows, start=1)
    ]

    index_md = args.out_dir / "index.md"
    manifest_json = args.out_dir / "manifest.json"
    assert_experiment_safe_output(index_md, args.allow_outside_experiment)
    assert_experiment_safe_output(manifest_json, args.allow_outside_experiment)
    index_md.write_text(render_index(report, focused_notes, corpus_md, corpus_json), encoding="utf-8")
    manifest_json.write_text(
        json.dumps(
            {
                "type_prefix": args.type_prefix,
                "max_files": args.max_files,
                "timeout_seconds": args.timeout_seconds,
                "address_map": str(args.address_map) if args.address_map else None,
                "corpus_report": str(corpus_md),
                "corpus_json": str(corpus_json),
                "focused_notes": [focused_note_to_dict(note) for note in focused_notes],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    skipped = sum(1 for note in focused_notes if note.error)
    print(f"Wrote review pack to {args.out_dir}.")
    print(f"Focused notes: {len(focused_notes) - skipped} written, {skipped} skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
