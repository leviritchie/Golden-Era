#!/usr/bin/env python3
"""
Build law-surface dossier indexes from the mod's centralized GameSymbols file.

This joins mod-side law symbol declarations to optional Cpp2IL symbol-map and
semantic-index evidence. It is a maintenance layer: missing runtime/static proof
is recorded as an explicit gap instead of being guessed.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from annotate_isil import (
    AddressEntry,
    assert_experiment_safe_output,
    collect_calls,
    find_type_file,
    load_address_map,
    markdown_table_code,
    parse_methods,
)
from build_symbol_map import (
	RuntimeMethod,
	candidate_runtime_methods,
	collect_runtime_map_methods,
	normalize_parameter_type,
	parse_method_shape,
	split_parameters,
)


CLASS_RE = re.compile(r"\binternal\s+static\s+class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*Laws)\b")
TYPE_ID_RE = re.compile(
    r"\binternal\s+const\s+string\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*TypeId)\s*=\s*"
    r'"(?P<value>[^"]+)"',
    re.DOTALL,
)
TYPE_HINTS_RE = re.compile(
    r"\binternal\s+static\s+readonly\s+string\[\]\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*TypeHints)\s*=\s*(?:new\s*\[\]\s*)?"
    r"\{(?P<body>.*?)\};",
    re.DOTALL,
)
TYPE_HINT_RE = re.compile(
    r"\binternal\s+const\s+string\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*TypeHint)\s*=\s*"
    r'"(?P<value>[^"]+)"',
    re.DOTALL,
)
METHOD_SYMBOL_RE = re.compile(
    r"\binternal\s+static\s+readonly\s+MethodSymbol\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*new\s*\((?P<body>.*?)\);",
    re.DOTALL,
)
STRING_RE = re.compile(r'"(?P<value>(?:\\.|[^"\\])*)"')
C_SHARP_MODIFIERS = {
	"public",
	"private",
	"protected",
	"internal",
	"static",
	"virtual",
	"override",
	"sealed",
	"new",
	"extern",
	"unsafe",
	"async",
	"readonly",
	"abstract",
}
C_SHARP_TYPE_ALIASES = {
	"bool": "System.Boolean",
	"byte": "System.Byte",
	"sbyte": "System.SByte",
	"char": "System.Char",
	"decimal": "System.Decimal",
	"double": "System.Double",
	"float": "System.Single",
	"int": "System.Int32",
	"uint": "System.UInt32",
	"long": "System.Int64",
	"ulong": "System.UInt64",
	"object": "System.Object",
	"short": "System.Int16",
	"ushort": "System.UInt16",
	"string": "System.String",
	"void": "System.Void",
}


@dataclass(frozen=True)
class TypeSurface:
    name: str
    symbol_id: str | None
    hints: tuple[str, ...]
    position: int


@dataclass(frozen=True)
class MethodSurface:
    law_class: str
    symbol_name: str
    symbol_id: str
    name_hints: tuple[str, ...]
    type_surface: TypeSurface | None
    position: int


@dataclass(frozen=True)
class StaticEvidence:
    type_name: str
    method_name: str
    method_ordinal: int | None
    signature: str
    diffable_source: str | None
    isil_source: str
    named_calls: tuple[str, ...]
    resolved_calls: tuple[str, ...]
    unresolved_native_calls: tuple[str, ...]
    status: str


def matching_brace(text: str, open_index: int) -> int:
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("unbalanced braces while parsing GameSymbols")


def extract_strings(text: str) -> tuple[str, ...]:
    return tuple(match.group("value") for match in STRING_RE.finditer(text))


def declaration_stem(name: str) -> str:
    for suffix in ("TypeHints", "TypeHint", "TypeId"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def iter_law_class_blocks(text: str) -> list[tuple[str, int, str]]:
    blocks: list[tuple[str, int, str]] = []
    for match in CLASS_RE.finditer(text):
        open_index = text.find("{", match.end())
        if open_index < 0:
            continue
        close_index = matching_brace(text, open_index)
        blocks.append((match.group("name"), match.start(), text[open_index + 1 : close_index]))
    return blocks


def parse_type_surfaces(block: str) -> list[TypeSurface]:
    by_stem: dict[str, dict[str, object]] = {}
    for match in TYPE_ID_RE.finditer(block):
        stem = declaration_stem(match.group("name"))
        row = by_stem.setdefault(stem, {"hints": [], "position": match.start(), "symbol_id": None})
        row["symbol_id"] = match.group("value")
        row["position"] = min(int(row["position"]), match.start())
    for match in TYPE_HINTS_RE.finditer(block):
        stem = declaration_stem(match.group("name"))
        row = by_stem.setdefault(stem, {"hints": [], "position": match.start(), "symbol_id": None})
        row["hints"] = list(extract_strings(match.group("body")))
        row["position"] = min(int(row["position"]), match.start())
    for match in TYPE_HINT_RE.finditer(block):
        stem = declaration_stem(match.group("name"))
        row = by_stem.setdefault(stem, {"hints": [], "position": match.start(), "symbol_id": None})
        row["hints"] = [match.group("value")]
        row["position"] = min(int(row["position"]), match.start())
    result: list[TypeSurface] = []
    for stem, row in by_stem.items():
        result.append(
            TypeSurface(
                name=stem,
                symbol_id=row["symbol_id"] if isinstance(row["symbol_id"], str) else None,
                hints=tuple(row["hints"]) if isinstance(row["hints"], list) else (),
                position=int(row["position"]),
            )
        )
    return sorted(result, key=lambda item: item.position)


def choose_type_context(types: list[TypeSurface], position: int) -> TypeSurface | None:
    prior = [item for item in types if item.position <= position]
    return prior[-1] if prior else None


def parse_law_surfaces(text: str) -> list[MethodSurface]:
    surfaces: list[MethodSurface] = []
    for class_name, class_position, block in iter_law_class_blocks(text):
        types = parse_type_surfaces(block)
        for match in METHOD_SYMBOL_RE.finditer(block):
            strings = extract_strings(match.group("body"))
            if not strings:
                continue
            symbol_id, *hints = strings
            if not symbol_id.startswith("law."):
                continue
            surfaces.append(
                MethodSurface(
                    law_class=class_name,
                    symbol_name=match.group("name"),
                    symbol_id=symbol_id,
                    name_hints=tuple(hints),
                    type_surface=choose_type_context(types, match.start()),
                    position=class_position + match.start(),
                )
            )
    return surfaces


def type_candidates(surface: MethodSurface) -> list[str]:
    if surface.type_surface is None:
        return []
    values: list[str] = []
    for hint in surface.type_surface.hints:
        if hint not in values:
            values.append(hint)
        if "." not in hint:
            prefixed = f"Hex.{hint}"
            if prefixed not in values:
                values.append(prefixed)
    return values


def method_candidates(surface: MethodSurface) -> list[str]:
    return [
        hint
        for hint in surface.name_hints
        if hint and not hint.startswith("Method_")
    ] or list(surface.name_hints)


def simple_name(value: str) -> str:
    text = value.strip()
    if text.endswith("[]"):
        text = text[:-2]
    text = text.split("`", 1)[0]
    return re.split(r"[.+]", text)[-1]


def semantic_target_queries(surface: MethodSurface) -> list[str]:
    queries: list[str] = []
    types = type_candidates(surface)
    methods = method_candidates(surface)
    unsafe_bare_methods = {
        "add",
        "base",
        "city",
        "copy",
        "count",
        "hero",
        "init",
        "item",
        "lookup",
        "show",
    }
    for type_name in types:
        if "." in type_name and len(type_name) >= 6 and type_name not in queries:
            queries.append(type_name)
    for method_name in methods:
        if (
            len(method_name) >= 4
            and method_name.islower()
            and method_name not in unsafe_bare_methods
            and method_name not in queries
        ):
            queries.append(method_name)
    for type_name in types:
        type_values = [type_name, simple_name(type_name)]
        for method_name in methods:
            for type_value in type_values:
                if not type_value or not method_name:
                    continue
                query = f"{type_value}.{method_name}"
                if query not in queries:
                    queries.append(query)
    return queries


def same_type(left: str, right: str) -> bool:
    return (
        left == right
        or left.lower() == right.lower()
        or simple_name(left).lower() == simple_name(right).lower()
    )


def load_json_file(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def find_symbol_map_row(
    surface: MethodSurface,
    symbol_map: dict[str, object] | None,
) -> dict[str, object] | None:
    if not symbol_map:
        return None
    methods = symbol_map.get("methods", [])
    if not isinstance(methods, list):
        return None
    surface_types = type_candidates(surface)
    surface_methods = method_candidates(surface)
    for row in methods:
        if not isinstance(row, dict):
            continue
        row_type = str(row.get("type") or "")
        row_method = str(row.get("method") or "")
        if any(same_type(candidate, row_type) for candidate in surface_types) and row_method in surface_methods:
            return row
    return None


def find_exact_type_file(root: Path, type_name: str, suffix: str) -> Path | None:
	try:
		return find_type_file(root, type_name, suffix)
	except (FileNotFoundError, FileExistsError):
		return None


def strip_csharp_modifiers(tokens: list[str]) -> list[str]:
	while tokens and tokens[0] in C_SHARP_MODIFIERS:
		tokens = tokens[1:]
	return tokens


def canonical_csharp_type(type_text: str, declaring_type: str) -> str:
	text = type_text.strip()
	array_suffix = ""
	while text.endswith("[]"):
		array_suffix += "[]"
		text = text[:-2].strip()
	if text in C_SHARP_TYPE_ALIASES:
		text = C_SHARP_TYPE_ALIASES[text]
	elif text == simple_name(declaring_type):
		text = declaring_type
	return text + array_suffix


def canonical_csharp_parameter(parameter: str, declaring_type: str) -> str:
	text = normalize_parameter_type(parameter)
	if not text:
		return ""
	tokens = text.split()
	if len(tokens) <= 1:
		return canonical_csharp_type(text, declaring_type)
	name = tokens[-1]
	parameter_type = canonical_csharp_type(" ".join(tokens[:-1]), declaring_type)
	return parameter_type + " " + name


def canonical_diffable_signature(line: str, declaring_type: str) -> tuple[str, str] | None:
	text = line.strip().rstrip("{").strip()
	if "(" not in text or ")" not in text or text.startswith("public Type:"):
		return None
	before_params, _, after_open = text.partition("(")
	params = after_open.rsplit(")", 1)[0]
	tokens = strip_csharp_modifiers(before_params.split())
	if len(tokens) < 2:
		return None
	method_name = tokens[-1].split(".")[-1]
	return_type = canonical_csharp_type(" ".join(tokens[:-1]), declaring_type)
	parameters = [
		canonical
		for canonical in (canonical_csharp_parameter(part, declaring_type) for part in split_parameters(params))
		if canonical
	]
	return method_name, return_type + " " + method_name + "(" + ", ".join(parameters) + ")"


def diffable_method_signatures(path: Path, declaring_type: str) -> list[tuple[str, str]]:
	methods: list[tuple[str, str]] = []
	for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
		signature = canonical_diffable_signature(line, declaring_type)
		if signature is not None:
			methods.append(signature)
	return methods


def method_name_matches(signature: str, candidates: list[str]) -> str | None:
    try:
        before_params = signature.split("(", 1)[0].strip()
        name = before_params.split()[-1].split(".")[-1]
    except IndexError:
        return None
    for candidate in candidates:
        if name == candidate or candidate in signature:
            return candidate
    return None


def is_callable_decomp_method(signature: str) -> bool:
    try:
        name = signature.split("(", 1)[0].strip().split()[-1].split(".")[-1]
    except IndexError:
        return False
    return name not in {".ctor", ".cctor"}


def collect_direct_static_evidence(
	surface: MethodSurface,
	diffable_root: Path | None,
	isil_root: Path | None,
	address_map: dict[str, AddressEntry],
) -> StaticEvidence | None:
	methods = method_candidates(surface)
	if not methods:
		return None
	found_type_without_method: StaticEvidence | None = None
	for type_name in type_candidates(surface):
		diffable_path = find_exact_type_file(diffable_root, type_name.split("+", 1)[0], ".cs") if diffable_root else None
		if isil_root is not None and isil_root.is_dir():
			isil_path = find_exact_type_file(isil_root, type_name, ".txt")
			if isil_path is not None:
				candidates = parse_methods(isil_path)
				callable_methods = [method for method in candidates if is_callable_decomp_method(method.signature)]
				ordinal_by_signature = {
					method.signature: index
					for index, method in enumerate(callable_methods)
				}
				matches = [
					method
					for method in candidates
					if method_name_matches(method.signature, methods) is not None
				]
				if not matches:
					found_type_without_method = StaticEvidence(
						type_name=type_name,
						method_name=methods[0],
						method_ordinal=None,
						signature="",
						diffable_source=str(diffable_path) if diffable_path else None,
						isil_source=str(isil_path),
						named_calls=(),
						resolved_calls=(),
						unresolved_native_calls=(),
						status="type_found_method_not_found",
					)
					continue
				method = matches[0]
				named_calls, resolved_calls, raw_calls = collect_calls(method, address_map)
				return StaticEvidence(
					type_name=type_name,
					method_name=method_name_matches(method.signature, methods) or methods[0],
					method_ordinal=ordinal_by_signature.get(method.signature),
					signature=method.signature,
					diffable_source=str(diffable_path) if diffable_path else None,
					isil_source=str(isil_path),
					named_calls=tuple(named_calls[:24]),
					resolved_calls=tuple(resolved_calls[:24]),
					unresolved_native_calls=tuple(raw_calls[:24]),
					status="static_method_found",
				)
		if diffable_path is not None:
			diffable_methods = diffable_method_signatures(diffable_path, type_name)
			diffable_matches = [
				(method_name, signature)
				for method_name, signature in diffable_methods
				if method_name in methods
			]
			if diffable_matches:
				method_name, signature = diffable_matches[0]
				return StaticEvidence(
					type_name=type_name,
					method_name=method_name,
					method_ordinal=None,
					signature=signature,
					diffable_source=str(diffable_path),
					isil_source="",
					named_calls=(),
					resolved_calls=(),
					unresolved_native_calls=(),
					status="diffable_method_found_no_isil",
				)
			found_type_without_method = StaticEvidence(
				type_name=type_name,
				method_name=methods[0],
				method_ordinal=None,
				signature="",
				diffable_source=str(diffable_path),
				isil_source="",
				named_calls=(),
				resolved_calls=(),
				unresolved_native_calls=(),
				status="diffable_type_found_method_not_found",
			)
	if found_type_without_method is not None:
		return found_type_without_method
	return StaticEvidence(
		type_name=type_candidates(surface)[0] if type_candidates(surface) else "",
		method_name=methods[0],
        method_ordinal=None,
        signature="",
        diffable_source=None,
        isil_source="",
        named_calls=(),
        resolved_calls=(),
        unresolved_native_calls=(),
        status="type_not_found",
    )


def collect_semantic_callers(
    surface: MethodSurface,
    semantic_index: dict[str, object] | None,
) -> list[dict[str, object]]:
    if not semantic_index:
        return []
    focus_rows = semantic_index.get("focus_targets", [])
    if not isinstance(focus_rows, list):
        return []
    queries = set(semantic_target_queries(surface))
    matches: list[dict[str, object]] = []
    for focus in focus_rows:
        if not isinstance(focus, dict) or str(focus.get("query") or "") not in queries:
            continue
        for match in focus.get("matches", []):
            if isinstance(match, dict):
                matches.append(match)
    return matches[:12]


def collect_anchor_hits(
    surface: MethodSurface,
    semantic_index: dict[str, object] | None,
) -> list[dict[str, object]]:
    if not semantic_index:
        return []
    anchors = semantic_index.get("anchors", [])
    if not isinstance(anchors, list):
        return []
    tokens = [token for token in re.split(r"[._]", surface.symbol_id.lower()) if len(token) > 3]
    rows: list[dict[str, object]] = []
    for row in anchors:
        if not isinstance(row, dict):
            continue
        text = str(row.get("anchor") or "").lower()
        if any(token in text for token in tokens):
            rows.append(row)
    return rows[:8]


def bridge_resolver_payload(
    surface: MethodSurface,
    direct_evidence: StaticEvidence | None,
    diffable_signature: str | None,
    method_ordinal: int | None,
) -> tuple[dict[str, object] | None, str]:
    if not diffable_signature:
        return None, "missing_diffable_signature"
    type_name = direct_evidence.type_name if direct_evidence else None
    if not type_name:
        candidates = type_candidates(surface)
        type_name = candidates[0] if candidates else None
    if not type_name:
        return None, "missing_type_name"
    payload: dict[str, object] = {
        "typeName": type_name,
        "signature": diffable_signature,
        "limit": 12,
    }
    if method_ordinal is not None:
        payload["methodOrdinal"] = method_ordinal
    return payload, "ready"


def source_references(
    surface: MethodSurface,
    source_root: Path | None,
    game_symbols: Path,
) -> list[str]:
    if source_root is None or not source_root.is_dir():
        return []
    needles = {surface.symbol_name, surface.symbol_id}
    result: list[str] = []
    for path in source_root.glob("*.cs"):
        if path.resolve() == game_symbols.resolve():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(needle in text for needle in needles):
            result.append(str(path))
    return sorted(result)


def chosen_dossier_target(surface: MethodSurface) -> str | None:
    types = type_candidates(surface)
    methods = method_candidates(surface)
    if not types or not methods:
        return None
    return f"{types[0]}::{methods[0]}"


def build_document(
    game_symbols: Path,
    source_root: Path | None,
    symbol_map: dict[str, object] | None,
    semantic_index: dict[str, object] | None,
    diffable_root: Path | None = None,
    isil_root: Path | None = None,
    address_map: dict[str, AddressEntry] | None = None,
    runtime_methods: dict[str, list[RuntimeMethod]] | None = None,
) -> dict[str, object]:
    surfaces = parse_law_surfaces(game_symbols.read_text(encoding="utf-8", errors="replace"))
    return build_document_from_surfaces(
        surfaces,
        game_symbols,
        source_root,
        symbol_map,
        semantic_index,
        diffable_root,
        isil_root,
        address_map or {},
        runtime_methods or {},
    )


def build_document_from_surfaces(
    surfaces: list[MethodSurface],
    game_symbols: Path,
    source_root: Path | None,
    symbol_map: dict[str, object] | None,
    semantic_index: dict[str, object] | None,
    diffable_root: Path | None = None,
    isil_root: Path | None = None,
    address_map: dict[str, AddressEntry] | None = None,
    runtime_methods: dict[str, list[RuntimeMethod]] | None = None,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for surface in surfaces:
        symbol_row = find_symbol_map_row(surface, symbol_map)
        direct_evidence = collect_direct_static_evidence(
            surface,
            diffable_root,
            isil_root,
            address_map or {},
        )
        source_refs = source_references(surface, source_root, game_symbols)
        runtime_candidates = symbol_row.get("runtime_candidates", []) if symbol_row else []
        runtime_mapping_status = (
            symbol_row.get("runtime_mapping_status") if symbol_row else "symbol_map_not_found"
        )
        if not runtime_candidates and direct_evidence and direct_evidence.signature and runtime_methods:
            try:
                runtime_candidates = candidate_runtime_methods(
                    parse_method_shape(direct_evidence.signature),
                    direct_evidence.type_name,
                    runtime_methods,
                    direct_evidence.method_ordinal,
                )[:16]
            except ValueError:
                runtime_candidates = []
            if runtime_candidates:
                runtime_mapping_status = "candidate_found_from_runtime_interop_map"
            else:
                runtime_mapping_status = "no_static_candidate_from_runtime_interop_map"
        diffable_signature = (
            symbol_row.get("signature")
            if symbol_row
            else direct_evidence.signature
            if direct_evidence and direct_evidence.signature
            else None
        )
        decomp_method_ordinal = (
            symbol_row.get("method_ordinal")
            if symbol_row
            else direct_evidence.method_ordinal
            if direct_evidence
            else None
        )
        bridge_payload, bridge_status = bridge_resolver_payload(
            surface,
            direct_evidence,
            diffable_signature if isinstance(diffable_signature, str) else None,
            decomp_method_ordinal if isinstance(decomp_method_ordinal, int) else None,
        )
        isil_call_evidence = {
            "named_calls": symbol_row.get("named_calls", []) if symbol_row else list(direct_evidence.named_calls) if direct_evidence else [],
            "resolved_calls": symbol_row.get("resolved_calls", []) if symbol_row else list(direct_evidence.resolved_calls) if direct_evidence else [],
            "unresolved_native_calls": (
                symbol_row.get("unresolved_native_calls", [])
                if symbol_row
                else list(direct_evidence.unresolved_native_calls)
                if direct_evidence
                else []
            ),
        }
        rows.append(
            {
                "law_class": surface.law_class,
                "symbol_name": surface.symbol_name,
                "symbol_id": surface.symbol_id,
                "type_id": surface.type_surface.symbol_id if surface.type_surface else None,
                "type_hints": list(surface.type_surface.hints) if surface.type_surface else [],
                "method_hints": list(surface.name_hints),
                "dossier_target": chosen_dossier_target(surface),
                "diffable_signature": diffable_signature,
                "decomp_method_ordinal": decomp_method_ordinal,
                "diffable_source": symbol_row.get("diffable_source") if symbol_row else direct_evidence.diffable_source if direct_evidence else None,
                "isil_source": symbol_row.get("isil_source") if symbol_row else direct_evidence.isil_source if direct_evidence else None,
                "static_evidence_status": (
                    "symbol_map_row_found"
                    if symbol_row
                    else direct_evidence.status
                    if direct_evidence
                    else "not_checked"
                ),
                "isil_call_evidence": isil_call_evidence,
                "runtime_generated_candidates": runtime_candidates,
                "runtime_mapping_status": runtime_mapping_status,
                "registration_status": (
                    "referenced_in_mod_source"
                    if source_refs
                    else "not_found_in_mod_source"
                    if source_root
                    else "not_checked"
                ),
                "registration_sources": source_refs[:12],
                "direct_callers": collect_semantic_callers(surface, semantic_index),
                "string_loc_anchors": collect_anchor_hits(surface, semantic_index),
                "bridge_resolver_payload": bridge_payload,
                "bridge_resolver_status": bridge_status,
                "proof_status": "not_runtime_proven_by_static_pipeline",
                "evidence_boundary": [
                    "Generated from GameSymbols law MethodSymbol declarations.",
                    "DiffableCs/ISIL evidence comes from symbol_map when available, otherwise direct exact Cpp2IL lookup.",
                    "Runtime generated candidates are metadata candidates, not invocation proof.",
                    "Bridge resolver payloads are read-only live metadata request templates, not proof.",
                    "Registration status is static source-reference evidence, not Harmony startup proof.",
                ],
            }
        )
    return {
        "schema": 1,
        "inputs": {
            "game_symbols": str(game_symbols),
            "source_root": str(source_root) if source_root else None,
            "symbol_map_available": symbol_map is not None,
            "semantic_index_available": semantic_index is not None,
            "diffable_root": str(diffable_root) if diffable_root else None,
            "isil_root": str(isil_root) if isil_root else None,
            "address_map_available": bool(address_map),
            "runtime_interop_map_available": bool(runtime_methods),
        },
        "surface_count": len(rows),
        "surfaces": rows,
    }


def render_markdown(document: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append("# Law Surface Dossier Index")
    lines.append("")
    inputs = document["inputs"]
    lines.append(f"- GameSymbols: {markdown_table_code(inputs['game_symbols'])}")
    lines.append(f"- Source root: {markdown_table_code(inputs.get('source_root') or '(not checked)')}")
    lines.append(f"- Symbol map available: {inputs['symbol_map_available']}")
    lines.append(f"- Runtime interop map available: {inputs.get('runtime_interop_map_available', False)}")
    lines.append(f"- Semantic index available: {inputs['semantic_index_available']}")
    lines.append(f"- Direct Cpp2IL roots: {markdown_table_code(inputs.get('isil_root') or '(not checked)')}")
    lines.append(f"- Surfaces: {document['surface_count']}")
    bridge_ready_count = sum(
        1
        for row in document["surfaces"]
        if isinstance(row, dict) and row.get("bridge_resolver_status") == "ready"
    )
    lines.append(f"- Bridge resolver payloads ready: {bridge_ready_count}")
    lines.append("")
    lines.append("## Evidence Boundary")
    lines.append("")
    lines.append("- This index is generated from centralized law symbols and optional static pipeline artifacts.")
    lines.append("- Runtime proof remains explicit per surface and is not inferred from static metadata.")
    lines.append("")
    lines.append("## Surfaces")
    lines.append("")
    lines.append("| Law class | Symbol | Dossier target | Static status | Signature | Calls | Runtime candidate | Runtime status | Bridge | Registration | Proof |")
    lines.append("| --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- |")
    for row in document["surfaces"]:
        calls = row["isil_call_evidence"]
        call_count = len(calls["named_calls"]) + len(calls["resolved_calls"]) + len(calls["unresolved_native_calls"])
        runtime_candidates = row.get("runtime_generated_candidates") or []
        runtime_candidate = "-"
        if runtime_candidates:
            first_candidate = runtime_candidates[0]
            if isinstance(first_candidate, dict):
                extra_count = max(0, len(runtime_candidates) - 1)
                suffix = f"; +{extra_count} more" if extra_count else ""
                runtime_candidate = (
                    f"{first_candidate.get('runtime_method', '-')}"
                    f" ({first_candidate.get('confidence', 'candidate')}{suffix})"
                )
        lines.append(
            f"| {markdown_table_code(row['law_class'])} | {markdown_table_code(row['symbol_id'])} | "
            f"{markdown_table_code(row.get('dossier_target') or '-')} | "
            f"{markdown_table_code(row.get('static_evidence_status') or 'not_checked')} | "
            f"{markdown_table_code(row.get('diffable_signature') or 'not found')} | "
            f"{call_count} | "
            f"{markdown_table_code(runtime_candidate)} | "
            f"{markdown_table_code(row['runtime_mapping_status'])} | "
            f"{markdown_table_code(row.get('bridge_resolver_status') or 'not_checked')} | "
            f"{markdown_table_code(row['registration_status'])} | "
            f"{markdown_table_code(row['proof_status'])} |"
        )
    lines.append("")
    lines.append("## Surface Details")
    lines.append("")
    for row in document["surfaces"]:
        lines.extend(render_surface_detail(row))
    return "\n".join(lines)


def first_runtime_candidate(row: dict[str, object]) -> str:
    candidates = row.get("runtime_generated_candidates") or []
    if not candidates:
        return "not found"
    first = candidates[0]
    if not isinstance(first, dict):
        return str(first)
    method = first.get("runtime_method") or "-"
    confidence = first.get("confidence") or "candidate"
    ordinal = first.get("runtime_callable_ordinal")
    ordinal_text = f", runtime ordinal {ordinal}" if ordinal is not None else ""
    extra_count = max(0, len(candidates) - 1)
    extra_text = f", +{extra_count} more" if extra_count else ""
    return f"{method} ({confidence}{ordinal_text}{extra_text})"


def compact_values(values: object, limit: int = 3) -> str:
    if not isinstance(values, list) or not values:
        return "none"
    text_values = [str(value) for value in values[:limit]]
    if len(values) > limit:
        text_values.append(f"+{len(values) - limit} more")
    return "; ".join(text_values)


def compact_dict_rows(rows: object, keys: tuple[str, ...], limit: int = 3) -> str:
    if not isinstance(rows, list) or not rows:
        return "none"
    values: list[str] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            values.append(str(row))
            continue
        parts = [str(row.get(key) or "") for key in keys if row.get(key) is not None]
        values.append(" | ".join(parts))
    if len(rows) > limit:
        values.append(f"+{len(rows) - limit} more")
    return "; ".join(values)


def render_surface_detail(row: dict[str, object]) -> list[str]:
    calls = row.get("isil_call_evidence") if isinstance(row.get("isil_call_evidence"), dict) else {}
    bridge_payload = row.get("bridge_resolver_payload")
    bridge_text = (
        json.dumps(bridge_payload, sort_keys=True)
        if isinstance(bridge_payload, dict)
        else str(row.get("bridge_resolver_status") or "not available")
    )
    lines = [
        f"### {row.get('symbol_id', row.get('symbol_name', 'unknown'))}",
        "",
        f"- Law class: {markdown_table_code(str(row.get('law_class') or ''))}",
        f"- Dossier target: {markdown_table_code(str(row.get('dossier_target') or 'not found'))}",
        f"- Decomp signature: {markdown_table_code(str(row.get('diffable_signature') or 'not found'))}",
        f"- Decomp method ordinal: {markdown_table_code(str(row.get('decomp_method_ordinal') if row.get('decomp_method_ordinal') is not None else 'not found'))}",
        f"- DiffableCs file: {markdown_table_code(str(row.get('diffable_source') or 'not found'))}",
        f"- ISIL file: {markdown_table_code(str(row.get('isil_source') or 'not found'))}",
        f"- Runtime/generated candidate: {markdown_table_code(first_runtime_candidate(row))}",
        f"- Runtime mapping status: {markdown_table_code(str(row.get('runtime_mapping_status') or 'not checked'))}",
        f"- Bridge resolver payload: {markdown_table_code(bridge_text)}",
        f"- Named calls: {markdown_table_code(compact_values(calls.get('named_calls') if isinstance(calls, dict) else []))}",
        f"- Resolved calls: {markdown_table_code(compact_values(calls.get('resolved_calls') if isinstance(calls, dict) else []))}",
        f"- Unresolved native calls: {markdown_table_code(compact_values(calls.get('unresolved_native_calls') if isinstance(calls, dict) else []))}",
        f"- Direct callers: {markdown_table_code(compact_dict_rows(row.get('direct_callers'), ('caller', 'target', 'kind')))}",
        f"- String/LOC anchors: {markdown_table_code(compact_dict_rows(row.get('string_loc_anchors'), ('anchor', 'caller', 'kind')))}",
        f"- Registration status: {markdown_table_code(str(row.get('registration_status') or 'not checked'))}",
        f"- Registration sources: {markdown_table_code(compact_values(row.get('registration_sources')))}",
        f"- Runtime proof status: {markdown_table_code(str(row.get('proof_status') or 'not checked'))}",
        f"- Evidence boundary: {markdown_table_code(compact_values(row.get('evidence_boundary'), 5))}",
        "",
    ]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Build generated dossiers for GameSymbols law surfaces.")
    parser.add_argument("--game-symbols", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--diffable-root", type=Path)
    parser.add_argument("--isil-root", type=Path)
    parser.add_argument("--address-map", type=Path)
    parser.add_argument("--symbol-map", type=Path)
    parser.add_argument("--runtime-map-json", type=Path)
    parser.add_argument("--semantic-index", type=Path)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    parser.add_argument("--allow-outside-experiment", action="store_true")
    args = parser.parse_args()

    if not args.game_symbols.is_file():
        raise FileNotFoundError(f"GameSymbols file does not exist: {args.game_symbols}")
    if args.source_root and not args.source_root.is_dir():
        raise FileNotFoundError(f"source root does not exist: {args.source_root}")
    if args.diffable_root and not args.diffable_root.is_dir():
        raise FileNotFoundError(f"DiffableCs root does not exist: {args.diffable_root}")
    if args.isil_root and not args.isil_root.is_dir():
        raise FileNotFoundError(f"ISIL root does not exist: {args.isil_root}")
    if args.address_map and not args.address_map.is_file():
        raise FileNotFoundError(f"address map does not exist: {args.address_map}")
    if args.runtime_map_json and not args.runtime_map_json.is_file():
        raise FileNotFoundError(f"runtime map JSON does not exist: {args.runtime_map_json}")

    document = build_document(
        args.game_symbols,
        args.source_root,
        load_json_file(args.symbol_map),
        load_json_file(args.semantic_index),
        args.diffable_root,
        args.isil_root,
        load_address_map(args.address_map) if args.address_map else {},
        collect_runtime_map_methods(args.runtime_map_json),
    )
    assert_experiment_safe_output(args.out_json, args.allow_outside_experiment)
    assert_experiment_safe_output(args.out_md, args.allow_outside_experiment)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(document, indent=2), encoding="utf-8")
    args.out_md.write_text(render_markdown(document), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
