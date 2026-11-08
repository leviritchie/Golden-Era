#!/usr/bin/env python3
"""Report likely raw obfuscated game symbols outside the central registry."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


OBF_STRING = re.compile(r'"([a-z]{2,5})"')
NATIVE_FIELD = re.compile(r"NativeFieldInfoPtr_[A-Za-z0-9_]+")
GLOBAL_TYPE = re.compile(r"\bglobal::([a-z]{2,4})\b")
WORD = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")

SUSPICIOUS_CONTEXT = (
    "AccessTools.",
    "Assembly.GetType(",
    "FindFirstMethod",
    "FindMethods",
    "GetField(",
    "GetMethod(",
    "HarmonyPatch",
    "NativeFieldInfoPtr_",
    "PatchByName",
    "PatchByRuntimeType",
    "ResolveByNames(",
    "Type.GetType(",
    "PatchCityTownMethod",
    "TryPatch",
    "global::",
)

MEMBER_HELPER_CONTEXT = (
    "GetFirstGameObjectMember(",
    "GetMemberValue(",
    "InvokeNoArg(",
    "TryGetFirstMemberValue(",
    "TryGetIntMember(",
    "TryGetMemberValue(",
    "TryGetStringMember(",
    "TryInvokeNoArg(",
    "TryReadFirstMember(",
    "TryReadMember(",
    "TrySetStringMember(",
)

INDIRECT_HELPER_CONTEXT = SUSPICIOUS_CONTEXT + MEMBER_HELPER_CONTEXT

ALLOW_WORDS = {
    "a",
    "all",
    "as",
    "bar",
    "btn",
    "by",
    "can",
    "cs",
    "city",
    "data",
    "dll",
    "err",
    "ex",
    "get",
    "h",
    "has",
    "hero",
    "hire",
    "id",
    "img",
    "icon",
    "in",
    "io",
    "is",
    "key",
    "low",
    "log",
    "map",
    "max",
    "min",
    "mod",
    "name",
    "new",
    "nil",
    "no",
    "node",
    "net",
    "off",
    "obj",
    "old",
    "on",
    "one",
    "out",
    "owner",
    "pic",
    "pics",
    "png",
    "raw",
    "set",
    "side",
    "sides",
    "sid",
    "src",
    "tex",
    "text",
    "tip",
    "tmp",
    "town",
    "txt",
    "type",
    "ui",
    "unit",
    "url",
    "var",
    "yes",
}

DECLARATION_START = re.compile(
    r"\b(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:new(?:\s+string\s*\[\]|\s*\[\])?\s*)?\{"
)
TYPED_DECLARATION_START = re.compile(
    r"\b(?:private|internal|public|protected|static|readonly|const|\s)+"
    r"(?:string\s*\[\]|var|IEnumerable\s*<\s*string\s*>|HashSet\s*<\s*string\s*>|List\s*<\s*string\s*>)"
    r"\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*="
)
CONST_STRING_DECLARATION = re.compile(
    r"\b(?:private|internal|public|protected|static|readonly|const|\s)+string\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*\"(?P<value>[a-z]{2,5})\""
)
FOREACH_DECLARED = re.compile(
    r"\bforeach\s*\(\s*var\s+(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\s+in\s+(?P<source>[A-Za-z_][A-Za-z0-9_]*)\s*\)"
)
FOREACH_INLINE = re.compile(
    r"\bforeach\s*\(\s*var\s+(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\s+in\s+new\s*\[\]\s*\{(?P<body>[^}]*)\}\s*\)"
)

EXCLUDED_PARTS = {
    ".git",
    "bin",
    "obj",
    "tools",
    "_decompiled_shipped",
    "_decompiled_filtered",
    "_decompiled_release_hex",
}

ALLOWLIST_FILES = {
    "GameSymbols.cs",
}

PROBE_NAME_MARKERS = (
    "Probe",
    "Diagnostic",
    "Telemetry",
)


@dataclass
class SymbolLiteralGroup:
    name: str
    line: int
    values: tuple[str, ...]
    kind: str
    text: str


def is_excluded(path: Path) -> bool:
    return bool(EXCLUDED_PARTS.intersection(path.parts))


def classify_file(path: Path) -> str:
    if any(marker in path.name for marker in PROBE_NAME_MARKERS):
        return "probe"
    return "runtime"


def short_literals(line: str) -> list[str]:
    return [match.group(1) for match in OBF_STRING.finditer(line) if match.group(1) not in ALLOW_WORDS]


def format_values(values: tuple[str, ...]) -> str:
    unique = list(dict.fromkeys(values))
    if len(unique) <= 10:
        return ", ".join(f'"{value}"' for value in unique)
    shown = ", ".join(f'"{value}"' for value in unique[:10])
    return f"{shown}, ... (+{len(unique) - 10})"


def line_has_context(line: str, include_member_helpers: bool) -> bool:
    contexts = INDIRECT_HELPER_CONTEXT if include_member_helpers else SUSPICIOUS_CONTEXT
    return any(token in line for token in contexts)


def line_has_indirect_context(line: str) -> bool:
    return any(token in line for token in INDIRECT_HELPER_CONTEXT)


def find_symbol_literal_groups(lines: list[str]) -> list[SymbolLiteralGroup]:
    groups: list[SymbolLiteralGroup] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        const_match = CONST_STRING_DECLARATION.search(line)
        if const_match:
            value = const_match.group("value")
            if value not in ALLOW_WORDS:
                groups.append(
                    SymbolLiteralGroup(
                        name=const_match.group("name"),
                        line=index + 1,
                        values=(value,),
                        kind="const",
                        text=stripped,
                    )
                )

        start_match = None
        if TYPED_DECLARATION_START.search(line):
            start_match = DECLARATION_START.search(line)
        if start_match and "GameSymbols." not in line:
            body_lines = [line]
            cursor = index
            # Handles the common multiline initializer pattern without trying to
            # become a C# parser.
            while ";" not in lines[cursor] and cursor + 1 < len(lines):
                cursor += 1
                body_lines.append(lines[cursor])
            body = "\n".join(body_lines)
            values = tuple(short_literals(body))
            if values:
                groups.append(
                    SymbolLiteralGroup(
                        name=start_match.group("name"),
                        line=index + 1,
                        values=values,
                        kind="array",
                        text=stripped,
                    )
                )
            index = max(index, cursor)
        index += 1
    return groups


def word_in_line(name: str, line: str) -> bool:
    return any(match.group(0) == name for match in WORD.finditer(line))


def report_indirect_groups(
    path: Path,
    root: Path,
    lines: list[str],
    category: str,
    groups: list[SymbolLiteralGroup],
) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    reported: set[tuple[str, int, int, str]] = set()
    by_name = {group.name: group for group in groups}
    rel = path.relative_to(root)

    def add(group: SymbolLiteralGroup, use_line: int, reason: str) -> None:
        key = (group.name, group.line, use_line, reason)
        if key in reported:
            return
        reported.add(key)
        findings.append(
            (
                category,
                f"{rel}:{group.line}: indirect short strings {format_values(group.values)} in {group.kind} '{group.name}' "
                f"used by {reason} at line {use_line}",
            )
        )

    for line_index, line in enumerate(lines, 1):
        if "GameSymbols." in line:
            continue
        if line_has_indirect_context(line):
            for group in groups:
                if word_in_line(group.name, line):
                    add(group, line_index, "reflection/helper call")

        foreach_inline = FOREACH_INLINE.search(line)
        inline_values = tuple(short_literals(foreach_inline.group("body"))) if foreach_inline else ()
        if foreach_inline and inline_values:
            pseudo = SymbolLiteralGroup(
                name=foreach_inline.group("alias"),
                line=line_index,
                values=inline_values,
                kind="inline-foreach",
                text=line.strip(),
            )
            for use_line in find_alias_helper_uses(lines, line_index, foreach_inline.group("alias")):
                add(pseudo, use_line, "foreach alias helper call")

        foreach_declared = FOREACH_DECLARED.search(line)
        if foreach_declared:
            group = by_name.get(foreach_declared.group("source"))
            if not group:
                continue
            for use_line in find_alias_helper_uses(lines, line_index, foreach_declared.group("alias")):
                add(group, use_line, "foreach alias helper call")

    return findings


def find_alias_helper_uses(
    lines: list[str],
    foreach_line: int,
    alias: str,
) -> list[int]:
    uses: list[int] = []
    depth = 0
    started = False
    for index in range(foreach_line - 1, min(len(lines), foreach_line + 120)):
        line = lines[index]
        if index == foreach_line - 1:
            started = True
        depth += line.count("{")
        depth -= line.count("}")
        if index > foreach_line - 1 and line_has_indirect_context(line) and word_in_line(alias, line):
            uses.append(index + 1)
            if len(uses) >= 3:
                break
        if started and index > foreach_line - 1 and depth <= 0:
            break
    return uses


def report_file(path: Path, root: Path, include_indirect: bool, include_member_helpers: bool) -> list[tuple[str, str]]:
    if path.name in ALLOWLIST_FILES or is_excluded(path.relative_to(root)):
        return []

    findings: list[tuple[str, str]] = []
    category = classify_file(path)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return findings

    groups = find_symbol_literal_groups(lines) if include_indirect else []

    for lineno, line in enumerate(lines, 1):
        if "GameSymbols." in line:
            continue
        for match in NATIVE_FIELD.finditer(line):
            findings.append((category, f"{path.relative_to(root)}:{lineno}: native field pointer {match.group(0)}"))
        if not line_has_context(line, include_member_helpers):
            continue
        for value in short_literals(line):
            findings.append((category, f"{path.relative_to(root)}:{lineno}: short string \"{value}\""))
        for match in GLOBAL_TYPE.finditer(line):
            findings.append((category, f"{path.relative_to(root)}:{lineno}: global type {match.group(0)}"))

    if include_indirect:
        findings.extend(report_indirect_groups(path, root, lines, category, groups))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repository root to scan")
    parser.add_argument("--source", default="Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod")
    parser.add_argument(
        "--fail-on-findings",
        action="store_true",
        help="exit non-zero when likely raw obfuscated references remain",
    )
    parser.add_argument(
        "--runtime-only",
        action="store_true",
        help="suppress probe/diagnostic findings and report only runtime hook/source debt",
    )
    parser.add_argument(
        "--no-indirect",
        action="store_true",
        help="skip one-hop scans for arrays/constants later used by reflection helpers",
    )
    parser.add_argument(
        "--include-member-helpers",
        action="store_true",
        help="also flag direct short-string arguments to broad member helpers such as TryGetMemberValue/GetMemberValue",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    source = (root / args.source).resolve()
    findings: list[tuple[str, str]] = []
    for path in source.rglob("*.cs"):
        findings.extend(
            report_file(
                path.resolve(),
                root,
                include_indirect=not args.no_indirect,
                include_member_helpers=args.include_member_helpers,
            )
        )

    if args.runtime_only:
        findings = [finding for finding in findings if finding[0] == "runtime"]

    counts = Counter(category for category, _ in findings)
    for category, finding in findings:
        print(f"[{category}] {finding}")
    if counts:
        print("Finding categories: " + ", ".join(f"{category}={counts[category]}" for category in sorted(counts)))
    else:
        print("Finding categories: none")
    print(f"Likely raw obfuscated symbol findings: {len(findings)}")
    return 1 if args.fail_on_findings and findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
