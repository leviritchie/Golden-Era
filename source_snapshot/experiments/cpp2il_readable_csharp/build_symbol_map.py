#!/usr/bin/env python3
"""
Build a bounded static symbol map from Cpp2IL DiffableCs/ISIL output.

This is a reuse layer for future agents: it records decomp type/method
signatures, call anchors, optional exact address-map labels, and optional
runtime generated-source candidates without claiming runtime proof.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from annotate_isil import (
    DEFAULT_DIFFABLE_ROOT,
    DEFAULT_ISIL_ROOT,
    AddressEntry,
    MethodBlock,
    assert_experiment_safe_output,
    collect_calls,
    find_type_file,
    load_address_map,
    markdown_table_code,
    parse_fields,
    parse_methods,
)
from build_corpus_report import candidate_roots_for_type_prefix, path_to_type_name


RUNTIME_METHOD_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|internal|static|virtual|override|sealed|"
    r"new|extern|unsafe|async|readonly)\s+)*"
    r"(?P<return>[A-Za-z_][\w.`<>\[\], ?:&]*)\s+"
    r"(?P<name>@?[A-Za-z_][\w]*)\s*"
    r"\((?P<params>[^()]*)\)"
)
NAMESPACE_RE = re.compile(r"^\s*namespace\s+(?P<name>[A-Za-z_][\w.]*)")
TYPE_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|internal|sealed|abstract|static|partial)\s+)*"
    r"(?:class|struct|interface|enum)\s+(?P<name>[A-Za-z_][\w`]*)"
)
STRING_LITERAL_RE = re.compile(r'"(?P<value>(?:\\.|[^"\\])*)"')
GAME_SYMBOL_TYPE_HINTS_RE = re.compile(
    r"\b[A-Za-z_][A-Za-z0-9_]*TypeHints\b\s*=\s*(?:new\s*\[\]\s*)?\{(?P<body>.*?)\};",
    re.DOTALL,
)
GAME_SYMBOL_TYPE_HINT_RE = re.compile(
    r"\b[A-Za-z_][A-Za-z0-9_]*TypeHint\b\s*=\s*\"(?P<value>[^\"]+)\"",
    re.DOTALL,
)


@dataclass(frozen=True)
class MethodShape:
    signature: str
    return_type: str
    name: str
    parameter_count: int
    parameter_types: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeMethod:
    type_name: str
    type_obfuscated_name: str | None
    name: str
    obfuscated_name: str | None
    callable_ordinal: int | None
    return_type: str
    parameter_count: int
    parameter_types: tuple[str, ...]
    signature: str
    source: str


class SymbolMapTimeoutError(TimeoutError):
    pass


def check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise SymbolMapTimeoutError("symbol-map scan exceeded timeout")


def split_parameters(text: str) -> tuple[str, ...]:
    text = text.strip()
    if not text:
        return ()
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        if char == "<":
            depth += 1
        elif char == ">" and depth:
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append("".join(current).strip())
    return tuple(part for part in parts if part)


def normalize_parameter_type(parameter: str) -> str:
    text = parameter.strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*=\s*.+$", "", text)
    tokens = [token for token in text.replace("&", " &").split(" ") if token]
    if len(tokens) > 1 and re.fullmatch(r"@?[A-Za-z_][\w]*", tokens[-1]):
        tokens = tokens[:-1]
    return " ".join(tokens).strip()


def parse_method_shape(signature: str) -> MethodShape:
    before_params, _, params = signature.partition("(")
    params = params.rsplit(")", 1)[0] if ")" in params else params
    tokens = before_params.strip().split()
    if len(tokens) < 2:
        raise ValueError(f"Cannot parse method signature: {signature}")
    name = tokens[-1].split(".")[-1]
    return_type = " ".join(tokens[:-1])
    parameter_types = tuple(normalize_parameter_type(part) for part in split_parameters(params))
    return MethodShape(
        signature=signature,
        return_type=return_type,
        name=name,
        parameter_count=len(parameter_types),
        parameter_types=parameter_types,
    )


def iter_isil_files(isil_root: Path, type_prefix: str | None, max_files: int, deadline: float | None):
    count = 0
    for root in candidate_roots_for_type_prefix(isil_root, type_prefix):
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
                    count += 1
                    if count > max_files:
                        return
                    yield entry


def infer_namespace_and_type(lines: list[str]) -> str | None:
    namespace = None
    type_name = None
    for line in lines:
        if namespace is None:
            namespace_match = NAMESPACE_RE.match(line)
            if namespace_match:
                namespace = namespace_match.group("name")
        if type_name is None:
            type_match = TYPE_RE.match(line)
            if type_match:
                type_name = type_match.group("name").split("`", 1)[0]
        if namespace and type_name:
            return f"{namespace}.{type_name}"
    return None


def collect_runtime_source_methods(
    root: Path | None,
    max_files: int,
    deadline: float | None,
) -> dict[str, list[RuntimeMethod]]:
    if root is None:
        return {}
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"runtime source root does not exist: {root}")

    methods_by_type: dict[str, list[RuntimeMethod]] = defaultdict(list)
    count = 0
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
                continue
            if entry.suffix.lower() != ".cs":
                continue
            count += 1
            if count > max_files:
                return methods_by_type
            lines = entry.read_text(encoding="utf-8", errors="replace").splitlines()
            type_name = infer_namespace_and_type(lines)
            if type_name is None:
                continue
            for line in lines:
                match = RUNTIME_METHOD_RE.match(line)
                if not match:
                    continue
                params = tuple(normalize_parameter_type(part) for part in split_parameters(match.group("params")))
                name = match.group("name").lstrip("@")
                methods_by_type[type_name].append(
                    RuntimeMethod(
                        type_name=type_name,
                        type_obfuscated_name=None,
                        name=name,
                        obfuscated_name=None,
                        callable_ordinal=None,
                        return_type=" ".join(match.group("return").split()),
                        parameter_count=len(params),
                        parameter_types=params,
                        signature=line.strip().rstrip("{").strip(),
                        source=str(entry),
                    )
                )
    return methods_by_type


def runtime_type_keys(runtime_type: str, obfuscated_type: str | None) -> tuple[str, ...]:
    keys: list[str] = []
    for value in (runtime_type, obfuscated_type):
        if not value:
            continue
        if value not in keys:
            keys.append(value)
        if "." not in value:
            prefixed = f"Hex.{value}"
            if prefixed not in keys:
                keys.append(prefixed)
    simple = runtime_type.rsplit(".", 1)[-1].rsplit("+", 1)[-1]
    if simple and simple not in keys:
        keys.append(simple)
    return tuple(keys)


def runtime_methods_from_map_document(
    document: dict[str, object],
    source: str,
) -> dict[str, list[RuntimeMethod]]:
    methods_by_type: dict[str, list[RuntimeMethod]] = defaultdict(list)
    for type_row in document.get("types", []):
        if not isinstance(type_row, dict):
            continue
        runtime_type = str(type_row.get("runtime_type") or "")
        obfuscated_type = type_row.get("obfuscated_type")
        obfuscated_type = str(obfuscated_type) if obfuscated_type else None
        for method_row in type_row.get("methods", []):
            if not isinstance(method_row, dict):
                continue
            runtime = RuntimeMethod(
                type_name=runtime_type,
                type_obfuscated_name=obfuscated_type,
                name=str(method_row.get("runtime_method") or ""),
                obfuscated_name=(
                    str(method_row.get("obfuscated_method"))
                    if method_row.get("obfuscated_method")
                    else None
                ),
                callable_ordinal=(
                    int(method_row["callable_ordinal"])
                    if method_row.get("callable_ordinal") is not None
                    else None
                ),
                return_type=str(method_row.get("return_type") or ""),
                parameter_count=int(method_row.get("parameter_count") or 0),
                parameter_types=tuple(str(value) for value in method_row.get("parameter_types", [])),
                signature=str(method_row.get("signature") or ""),
                source=source,
            )
            for key in runtime_type_keys(runtime_type, obfuscated_type):
                methods_by_type[key].append(runtime)
    return methods_by_type


def collect_runtime_map_methods(path: Path | None) -> dict[str, list[RuntimeMethod]]:
    if path is None:
        return {}
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    return runtime_methods_from_map_document(document, str(path))


def add_type_name(values: list[str], raw_value: str) -> None:
    value = raw_value.strip()
    if not value or value.startswith("law."):
        return
    candidates = [value] if "." in value else [f"Hex.{value}", value]
    for candidate in candidates:
        if candidate not in values:
            values.append(candidate)


def type_names_from_game_symbols(path: Path | None) -> tuple[str, ...]:
    if path is None:
        return ()
    text = path.read_text(encoding="utf-8", errors="replace")
    values: list[str] = []
    for match in GAME_SYMBOL_TYPE_HINTS_RE.finditer(text):
        for item in STRING_LITERAL_RE.finditer(match.group("body")):
            add_type_name(values, item.group("value"))
    for match in GAME_SYMBOL_TYPE_HINT_RE.finditer(text):
        add_type_name(values, match.group("value"))
    return tuple(values)


def merge_runtime_methods(*maps: dict[str, list[RuntimeMethod]]) -> dict[str, list[RuntimeMethod]]:
    result: dict[str, list[RuntimeMethod]] = defaultdict(list)
    seen: set[tuple[str, str, str, str]] = set()
    for mapping in maps:
        for key, methods in mapping.items():
            for method in methods:
                identity = (key, method.type_name, method.name, method.signature)
                if identity in seen:
                    continue
                seen.add(identity)
                result[key].append(method)
    return result


def candidate_runtime_methods(
    shape: MethodShape,
    type_name: str,
    runtime_methods: dict[str, list[RuntimeMethod]],
    method_ordinal: int | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    confidence_rank = {
        "assembly_obfuscated_type_method_and_arity": 0,
        "assembly_obfuscated_method_and_arity": 1,
        "exact_type_method_name_and_arity": 2,
        "type_callable_ordinal_and_signature_shape": 3,
        "exact_type_signature_shape_only": 4,
    }
    for runtime in runtime_methods.get(type_name, []):
        if (
            runtime.obfuscated_name == shape.name
            and runtime.type_obfuscated_name
            and type_name.endswith(runtime.type_obfuscated_name)
            and runtime.parameter_count == shape.parameter_count
        ):
            confidence = "assembly_obfuscated_type_method_and_arity"
        elif runtime.obfuscated_name == shape.name and runtime.parameter_count == shape.parameter_count:
            confidence = "assembly_obfuscated_method_and_arity"
        elif runtime.name == shape.name and runtime.parameter_count == shape.parameter_count:
            confidence = "exact_type_method_name_and_arity"
        elif (
            method_ordinal is not None
            and runtime.callable_ordinal == method_ordinal
            and runtime.parameter_count == shape.parameter_count
            and runtime.return_type == shape.return_type
        ):
            confidence = "type_callable_ordinal_and_signature_shape"
        elif (
            runtime.parameter_count == shape.parameter_count
            and runtime.return_type == shape.return_type
        ):
            confidence = "exact_type_signature_shape_only"
        else:
            continue
        rows.append(
            {
                "runtime_type": runtime.type_name,
                "runtime_type_obfuscated": runtime.type_obfuscated_name,
                "runtime_method": runtime.name,
                "runtime_method_obfuscated": runtime.obfuscated_name,
                "runtime_callable_ordinal": runtime.callable_ordinal,
                "runtime_signature": runtime.signature,
                "runtime_source": runtime.source,
                "confidence": confidence,
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            confidence_rank.get(str(row["confidence"]), 99),
            row["runtime_callable_ordinal"] is None,
            row["runtime_callable_ordinal"] if row["runtime_callable_ordinal"] is not None else 999999,
            str(row["runtime_method"]),
        ),
    )


def resolve_exact_isil_files(
    isil_root: Path,
    exact_types: tuple[str, ...],
    deadline: float | None,
) -> tuple[list[Path], list[str]]:
    paths: list[Path] = []
    missing: list[str] = []
    seen_paths: set[Path] = set()
    seen_types: set[str] = set()
    for type_name in exact_types:
        check_deadline(deadline)
        if type_name in seen_types:
            continue
        seen_types.add(type_name)
        try:
            path = find_type_file(isil_root, type_name, ".txt")
        except (FileNotFoundError, FileExistsError) as exc:
            missing.append(f"{type_name}: {exc}")
            continue
        resolved = path.resolve()
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        paths.append(path)
    return paths, missing


def build_symbol_map(
    diffable_root: Path,
    isil_root: Path,
    address_map: dict[str, AddressEntry],
    type_prefix: str | None,
    max_files: int,
    runtime_methods: dict[str, list[RuntimeMethod]],
    exact_types: tuple[str, ...],
    candidate_limit: int,
    call_limit: int,
    deadline: float | None,
) -> dict[str, object]:
    type_rows: list[dict[str, object]] = []
    method_rows: list[dict[str, object]] = []
    missing_requested_types: list[str] = []

    if exact_types:
        isil_paths, missing_requested_types = resolve_exact_isil_files(isil_root, exact_types, deadline)
    else:
        isil_paths = list(iter_isil_files(isil_root, type_prefix, max_files, deadline))

    for isil_path in isil_paths:
        check_deadline(deadline)
        type_name = path_to_type_name(isil_root, isil_path)
        try:
            csharp_path = find_type_file(diffable_root, type_name.split("+", 1)[0], ".cs")
            fields = parse_fields(csharp_path) if "+" not in type_name else {}
            diffable_source: str | None = str(csharp_path)
        except (FileNotFoundError, FileExistsError):
            fields = {}
            diffable_source = None

        methods = parse_methods(isil_path)
        ordinal_by_signature = {
            method.signature: index
            for index, method in enumerate(
                item
                for item in methods
                if parse_method_shape(item.signature).name not in {".ctor", ".cctor"}
            )
        }
        type_rows.append(
            {
                "type": type_name,
                "isil_source": str(isil_path),
                "diffable_source": diffable_source,
                "method_count": len(methods),
                "field_count": len(fields),
                "runtime_source_available": type_name in runtime_methods,
            }
        )

        for method in methods:
            shape = parse_method_shape(method.signature)
            named_calls, resolved_calls, raw_calls = collect_calls(method, address_map)
            method_ordinal = ordinal_by_signature.get(method.signature)
            candidates = candidate_runtime_methods(shape, type_name, runtime_methods, method_ordinal)
            method_rows.append(
                {
                    "type": type_name,
                    "method": shape.name,
                    "method_ordinal": method_ordinal,
                    "signature": shape.signature,
                    "return_type": shape.return_type,
                    "parameter_count": shape.parameter_count,
                    "parameter_types": list(shape.parameter_types),
                    "named_calls": named_calls[:call_limit],
                    "resolved_calls": resolved_calls[:call_limit],
                    "unresolved_native_calls": raw_calls[:call_limit],
                    "runtime_candidates": candidates[:candidate_limit],
                    "runtime_mapping_status": (
                        "candidate_found"
                        if candidates
                        else "runtime_source_unavailable"
                        if not runtime_methods
                        else "no_static_candidate"
                    ),
                }
            )

    return {
        "schema": 1,
        "inputs": {
            "diffable_root": str(diffable_root),
            "isil_root": str(isil_root),
            "type_prefix": type_prefix,
            "max_files": max_files,
            "exact_type_count": len(exact_types),
            "missing_requested_types": missing_requested_types,
            "candidate_limit": candidate_limit,
            "call_limit": call_limit,
        },
        "type_count": len(type_rows),
        "method_count": len(method_rows),
        "types": type_rows,
        "methods": method_rows,
        "evidence_boundary": [
            "DiffableCs/ISIL signatures and call anchors are static Cpp2IL evidence.",
            "runtime_candidates require generated C# source or generated interop assembly metadata and remain candidates until runtime proof.",
            "runtime_source_unavailable is an explicit gap, not a fallback mapping.",
        ],
    }


def render_markdown(document: dict[str, object], limit: int) -> str:
    lines: list[str] = []
    inputs = document["inputs"]
    lines.append("# Cpp2IL Symbol Map")
    lines.append("")
    lines.append(f"- DiffableCs: {markdown_table_code(inputs['diffable_root'])}")
    lines.append(f"- ISIL: {markdown_table_code(inputs['isil_root'])}")
    lines.append(f"- Type prefix: {markdown_table_code(inputs.get('type_prefix') or '(all)')}")
    lines.append(f"- Exact requested types: {inputs.get('exact_type_count', 0)}")
    lines.append(f"- Candidate limit per method: {inputs.get('candidate_limit', 0)}")
    lines.append(f"- Call-anchor limit per bucket: {inputs.get('call_limit', 0)}")
    missing_requested_types = inputs.get("missing_requested_types") or []
    if missing_requested_types:
        lines.append(f"- Missing requested types: {len(missing_requested_types)}")
    lines.append(f"- Scanned types: {document['type_count']}")
    lines.append(f"- Indexed methods: {document['method_count']}")
    lines.append("")
    lines.append("## Evidence Boundary")
    lines.append("")
    for item in document["evidence_boundary"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Method Map")
    lines.append("")
    lines.append("| Type | Method | Arity | Runtime status | Candidates | Named-call anchors |")
    lines.append("| --- | --- | ---: | --- | --- | --- |")
    for row in document["methods"][:limit]:
        candidates = row["runtime_candidates"]
        candidate_text = ", ".join(
            f"{candidate['runtime_method']} ({candidate['confidence']})"
            for candidate in candidates[:3]
        )
        named_calls = ", ".join(row["named_calls"][:4])
        lines.append(
            f"| {markdown_table_code(row['type'])} | {markdown_table_code(row['method'])} | "
            f"{row['parameter_count']} | {markdown_table_code(row['runtime_mapping_status'])} | "
            f"{markdown_table_code(candidate_text or '-')} | {markdown_table_code(named_calls or '-')} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a bounded Cpp2IL static symbol map.")
    parser.add_argument("--diffable-root", type=Path, default=DEFAULT_DIFFABLE_ROOT)
    parser.add_argument("--isil-root", type=Path, default=DEFAULT_ISIL_ROOT)
    parser.add_argument("--address-map", type=Path)
    parser.add_argument("--runtime-source-root", type=Path)
    parser.add_argument("--runtime-map-json", type=Path)
    parser.add_argument("--type", action="append", default=[], help="Exact Cpp2IL type to include; repeatable.")
    parser.add_argument("--game-symbols-types", type=Path, help="GameSymbols.cs path; include exact law TypeHint/TypeHints types.")
    parser.add_argument("--type-prefix")
    parser.add_argument("--max-files", type=int, default=200)
    parser.add_argument("--max-runtime-files", type=int, default=500)
    parser.add_argument("--candidate-limit", type=int, default=8)
    parser.add_argument("--call-limit", type=int, default=8)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-md", type=Path)
    parser.add_argument("--markdown-limit", type=int, default=200)
    parser.add_argument("--allow-outside-experiment", action="store_true")
    args = parser.parse_args()

    if args.max_files < 1:
        raise ValueError("--max-files must be positive")
    if args.max_runtime_files < 1:
        raise ValueError("--max-runtime-files must be positive")
    if args.candidate_limit < 1:
        raise ValueError("--candidate-limit must be positive")
    if args.call_limit < 1:
        raise ValueError("--call-limit must be positive")
    if args.timeout_seconds < 1:
        raise ValueError("--timeout-seconds must be positive")
    if not args.diffable_root.is_dir():
        raise FileNotFoundError(f"DiffableCs root does not exist: {args.diffable_root}")
    if not args.isil_root.is_dir():
        raise FileNotFoundError(f"ISIL root does not exist: {args.isil_root}")
    if args.runtime_map_json and not args.runtime_map_json.is_file():
        raise FileNotFoundError(f"runtime map JSON does not exist: {args.runtime_map_json}")
    if args.game_symbols_types and not args.game_symbols_types.is_file():
        raise FileNotFoundError(f"GameSymbols file does not exist: {args.game_symbols_types}")
    if args.out_json is None and args.out_md is None:
        raise ValueError("provide --out-json, --out-md, or both")

    deadline = time.monotonic() + args.timeout_seconds
    address_map = load_address_map(args.address_map) if args.address_map else {}
    runtime_methods = merge_runtime_methods(
        collect_runtime_source_methods(
            args.runtime_source_root,
            args.max_runtime_files,
            deadline,
        ),
        collect_runtime_map_methods(args.runtime_map_json),
    )
    exact_types = tuple(dict.fromkeys([*args.type, *type_names_from_game_symbols(args.game_symbols_types)]))
    document = build_symbol_map(
        args.diffable_root,
        args.isil_root,
        address_map,
        args.type_prefix,
        args.max_files,
        runtime_methods,
        exact_types,
        args.candidate_limit,
        args.call_limit,
        deadline,
    )

    if args.out_json:
        assert_experiment_safe_output(args.out_json, args.allow_outside_experiment)
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(document, indent=2), encoding="utf-8")
    if args.out_md:
        assert_experiment_safe_output(args.out_md, args.allow_outside_experiment)
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(render_markdown(document, args.markdown_limit), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
