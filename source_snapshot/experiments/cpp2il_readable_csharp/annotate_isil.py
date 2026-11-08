#!/usr/bin/env python3
"""
Annotate Cpp2IL ISIL output with field offsets from diffable-cs shells.

This is deliberately standalone experiment tooling. It does not import or
modify OfflineUnlockMod code, and its default input/output locations stay under
tmp/cpp2il_experiment.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


DEFAULT_DIFFABLE_ROOT = Path("tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs")
DEFAULT_ISIL_ROOT = Path("tmp/cpp2il_experiment/out_dev_isil/IsilDump")

FIELD_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|internal|static|readonly|const|"
    r"volatile|sealed|new|unsafe|event)\s+)*"
    r"(?P<type>[A-Za-z_][\w.`<>\[\], ?:]*)\s+"
    r"(?P<name>@?[A-Za-z_][\w]*)\s*;"
    r"\s*//Field offset:\s*0x(?P<offset>[0-9A-Fa-f]+)"
)
METHOD_HEADER_RE = re.compile(r"^Method:\s+(?P<signature>.+)$")
REG_OFFSET_RE = re.compile(r"\[(?P<reg>[a-z][a-z0-9]*)\+(?P<offset>[0-9A-Fa-f]+)h?\]")
ISIL_THIS_OFFSET_RE = re.compile(r"\[this\s*@\s*rcx\+(?P<offset>[0-9A-Fa-f]+)\]")
ISIL_OWNER_OFFSET_RE = re.compile(
    r"^\[(?P<owner>[A-Za-z_][\w`<>]*)"
    r"(?:\s*@\s*[A-Za-z_][\w+\-]*(?:_v\d+)?)?"
    r"(?:\s+\([^][]*\))?"
    r"\+(?P<offset>[0-9A-Fa-f]+)h?\]$"
)
STATIC_METADATA_FLAG_CHECK_RE = re.compile(
    r"\bCheck(?:Equal|NotEqual)\s+[^,]+,\s+\[1856[0-9A-Fa-f]{5,}\],\s*0\b"
)
RAW_CALL_RE = re.compile(r"\bCall(?:Void)?\s+(?P<target>[0-9A-Fa-f]{8,16})\b")
CALL_OPCODE_RE = re.compile(r"\bCall(?:Void)?\s+")
ISIL_CALL_LINE_RE = re.compile(r"^\s*\d+\s+(?P<opcode>CallVoid|Call)\s+(?P<rest>.+)$")
ISIL_MOVE_LINE_RE = re.compile(r"^\s*\d+\s+Move\s+(?P<rest>.+)$")
DISASM_CALL_RE = re.compile(r"\bcall\s+(?P<target>[0-9A-Fa-f]{8,16})h\b")
SYMBOL_ALIAS_RE = re.compile(
    r"(?<![\w.])(?P<name>this|[A-Za-z_][\w]*)\s+@\s+"
    r"(?P<storage>[A-Za-z_][\w+\-]*(?:_v\d+)?)"
    r"(?:\s+\((?P<type>[^)\r\n]+)\))?"
)


@dataclass(frozen=True)
class FieldInfo:
    offset: int
    name: str
    type_name: str


@dataclass
class MethodBlock:
    signature: str
    body: list[str]

    @property
    def short_name(self) -> str:
        text = self.signature.split("(", 1)[0].strip()
        return text.split()[-1].split(".")[-1]


@dataclass(frozen=True)
class AddressEntry:
    address: str
    kind: str
    label: str
    confidence: str
    raw: dict[str, object]


@dataclass
class FieldAccessSummary:
    field: FieldInfo
    exact_reads: int = 0
    exact_writes: int = 0
    possible_reads: int = 0
    possible_writes: int = 0
    possible_refs: int = 0


@dataclass(frozen=True)
class FieldDataFlowSummary:
    field: FieldInfo
    observed_use: str
    exact_observations: int
    possible_observations: int
    read_observations: int
    write_observations: int
    address_observations: int
    confidence: str


@dataclass
class CallSummary:
    disasm_native_sites: int
    isil_raw_sites: int
    resolved_native_observations: int
    unresolved_native_observations: int
    named_sites: int
    unique_resolved_native: int
    unique_unresolved_native: int
    unique_named: int


@dataclass
class ControlSummary:
    disasm_lines: int
    isil_lines: int
    conditional_jumps: int
    unconditional_jumps: int
    returns: int
    int3_traps: int


@dataclass
class MethodSummary:
    method: MethodBlock
    control: ControlSummary
    calls: CallSummary
    field_accesses: list[FieldAccessSummary]
    score: int


@dataclass(frozen=True)
class CallContext:
    address: str
    view: str
    line_number: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedCallContext:
    address: str
    label: str
    view: str
    line_number: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class NamedCallContext:
    target: str
    line_number: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class CallSequenceItem:
    step: int
    line_number: int
    kind: str
    target: str
    line: str


@dataclass(frozen=True)
class MemberAssignmentItem:
    step: int
    line_number: int
    target: str
    value: str
    line: str


@dataclass(frozen=True)
class BranchContext:
    target: str
    line_number: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class BranchTargetSummary:
    target: str
    observations: int
    first_line_number: int
    first_lines: tuple[str, ...]


@dataclass(frozen=True)
class ReturnContext:
    line_number: int
    expression: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class MethodSkeletonItem:
    step: int
    line_number: int
    kind: str
    detail: str
    evidence: str


@dataclass(frozen=True)
class SymbolAliasSummary:
    symbol: str
    observations: int
    storages: tuple[tuple[str, int], ...]
    type_hints: tuple[tuple[str, int], ...]
    first_line_number: int
    first_line: str


@dataclass(frozen=True)
class FieldAccessContext:
    field: FieldInfo
    confidence: str
    access_kind: str
    view: str
    line_number: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class ReviewCue:
    kind: str
    detail: str
    why: str
    evidence: str


@dataclass(frozen=True)
class ParameterUseSummary:
    parameter: str
    observations: int
    uses: tuple[tuple[str, int], ...]
    first_line_number: int
    first_line: str


def markdown_code(value: object) -> str:
    return f"<code>{html.escape(str(value))}</code>"


def markdown_table_code(value: object) -> str:
    return markdown_code(value).replace("|", "&#124;")


def compact_text(value: object, limit: int = 220) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def is_context_noise(line: str) -> bool:
    return bool(re.fullmatch(r"\d+\s+Nop\s*", line.strip()))


def remember_context_line(recent_lines: list[str], line: str, limit: int = 2) -> list[str]:
    stripped = line.strip()
    if not stripped or is_context_noise(stripped):
        return recent_lines
    recent_lines.append(stripped)
    if len(recent_lines) > limit:
        return recent_lines[-limit:]
    return recent_lines


def split_signature_parameter_names(signature: str) -> list[str]:
    start = signature.rfind("(")
    end = signature.rfind(")")
    if start < 0 or end < start:
        return []
    params = signature[start + 1 : end].strip()
    if not params:
        return []

    result: list[str] = []
    seen: set[str] = set()
    depth = 0
    current: list[str] = []
    parts: list[str] = []
    for char in params:
        if char in "<([":
            depth += 1
        elif char in ">)]" and depth > 0:
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current).strip())

    for part in parts:
        part = part.split("=", 1)[0].strip()
        tokens = part.replace("&", " ").split()
        if tokens:
            candidate = tokens[-1].strip()
            if re.fullmatch(r"@?[A-Za-z_][\w]*", candidate):
                name = candidate.lstrip("@")
                if name not in seen:
                    result.append(name)
                    seen.add(name)
    return result


def split_signature_parameters(signature: str) -> set[str]:
    return set(split_signature_parameter_names(signature))


def type_to_relative_path(type_name: str, suffix: str) -> Path:
    parts = type_name.split(".")
    if len(parts) >= 2 and parts[0] == "Hex":
        parts = ["Hex"] + parts
    return Path(*parts).with_suffix(suffix)


def find_type_file(root: Path, type_name: str, suffix: str) -> Path:
    preferred = root / type_to_relative_path(type_name, suffix)
    if preferred.exists():
        return preferred

    simple = type_name.split(".")[-1]
    matches = list(root.rglob(f"{simple}{suffix}"))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(f"No {suffix} file found for {type_name} under {root}")
    joined = "\n  ".join(str(m) for m in matches[:20])
    raise FileExistsError(f"Ambiguous {suffix} file for {type_name}:\n  {joined}")


def normalize_address(value: str) -> str:
    text = value.strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    if text.lower().endswith("h"):
        text = text[:-1]
    text = text.upper().lstrip("0") or "0"
    return "0x" + text


def load_address_map(path: Path | None) -> dict[str, AddressEntry]:
    if path is None:
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    addresses = document.get("addresses", document)
    if not isinstance(addresses, dict):
        raise ValueError(f"Address map {path} does not contain an addresses object")

    result: dict[str, AddressEntry] = {}
    for raw_address, value in addresses.items():
        if not isinstance(value, dict):
            continue
        address = normalize_address(raw_address)
        kind = str(value.get("kind") or "unknown")
        confidence = str(value.get("confidence") or "unknown")
        label = address
        if kind == "managed_method":
            signature = str(value.get("signature") or "").strip()
            type_name = str(value.get("type") or "").strip()
            method = str(value.get("method") or "").strip()
            label = signature or ".".join(part for part in [type_name, method] if part) or address
        elif value.get("name"):
            label = str(value["name"])
        result[address] = AddressEntry(
            address=address,
            kind=kind,
            label=label,
            confidence=confidence,
            raw=value,
        )
    return result


def parse_fields(csharp_path: Path) -> dict[int, FieldInfo]:
    fields: dict[int, FieldInfo] = {}
    class_seen = False
    class_depth = 0
    for line in csharp_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not class_seen and re.search(r"\b(class|struct)\b", stripped):
            class_seen = True

        if class_seen:
            class_depth += line.count("{")
            class_depth -= line.count("}")

        if class_depth != 1:
            continue

        match = FIELD_RE.match(line)
        if not match:
            continue
        offset = int(match.group("offset"), 16)
        fields[offset] = FieldInfo(
            offset=offset,
            name=match.group("name"),
            type_name=" ".join(match.group("type").split()),
        )
    return fields


def parse_methods(isil_path: Path) -> list[MethodBlock]:
    methods: list[MethodBlock] = []
    current: MethodBlock | None = None

    for line in isil_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = METHOD_HEADER_RE.match(line)
        if match:
            if current is not None:
                methods.append(current)
            current = MethodBlock(signature=match.group("signature"), body=[])
            continue
        if current is not None:
            current.body.append(line)

    if current is not None:
        methods.append(current)
    return methods


def filter_methods(methods: Iterable[MethodBlock], method_filter: str | None) -> list[MethodBlock]:
    result = list(methods)
    if method_filter is None:
        return result
    wanted = method_filter.lower()
    return [
        method
        for method in result
        if wanted in method.short_name.lower() or wanted in method.signature.lower()
    ]


def infer_this_registers(method: MethodBlock) -> set[str]:
    """Infer native registers that currently alias the managed this pointer."""
    registers = {"rcx"}
    for line in method.body:
        if line.strip() == "ISIL:":
            break
        match = re.search(r"\bmov\s+(?P<dst>r[a-z0-9]+),rcx\b", line)
        if match:
            registers.add(match.group("dst"))
    return registers


def split_method_body(method: MethodBlock) -> tuple[list[str], list[str]]:
    disasm: list[str] = []
    isil: list[str] = []
    in_isil = False
    for line in method.body:
        if line.strip() == "ISIL:":
            in_isil = True
            continue
        if in_isil:
            isil.append(line)
        else:
            disasm.append(line)
    return disasm, isil


def format_address_entry(entry: AddressEntry) -> str:
    if entry.kind == "managed_method":
        return f"{entry.label} [{entry.confidence}]"
    if entry.kind == "inferred_helper":
        return f"helper {entry.label} [{entry.confidence}, n={entry.raw.get('observations', '?')}]"
    return f"{entry.label} [{entry.kind}, {entry.confidence}]"


def annotate_line(
    line: str,
    fields: dict[int, FieldInfo],
    this_registers: set[str],
    address_map: dict[str, AddressEntry],
) -> str:
    line = line.rstrip()
    comments: list[str] = []

    for match in ISIL_THIS_OFFSET_RE.finditer(line):
        offset = int(match.group("offset"), 16)
        field = fields.get(offset)
        if field:
            comments.append(f"this+0x{offset:X} = {field.name}: {field.type_name}")

    for match in REG_OFFSET_RE.finditer(line):
        if match.group("reg") not in this_registers:
            continue
        offset = int(match.group("offset"), 16)
        field = fields.get(offset)
        if field:
            comments.append(
                f"possible this alias {match.group('reg')}+0x{offset:X} = "
                f"{field.name}: {field.type_name}"
            )

    for pattern in (RAW_CALL_RE, DISASM_CALL_RE):
        for match in pattern.finditer(line):
            address = normalize_address(match.group("target"))
            entry = address_map.get(address)
            if entry:
                comments.append(f"{address} = {format_address_entry(entry)}")

    if not comments:
        return line
    unique = list(dict.fromkeys(comments))
    return f"{line}    // {'; '.join(unique)}"


def iter_named_call_targets(line: str) -> Iterable[str]:
    for match in CALL_OPCODE_RE.finditer(line):
        rest = line[match.end() :].lstrip()
        if not rest:
            continue
        if rest.startswith('"'):
            end = rest.find('"', 1)
            if end > 1:
                yield rest[1:end]
            continue

        depth = 0
        end = 0
        for index, char in enumerate(rest):
            if char == "<":
                depth += 1
            elif char == ">" and depth:
                depth -= 1
            elif depth == 0 and (char == "," or char.isspace()):
                break
            end = index + 1
        target = rest[:end].strip()
        if not target or re.fullmatch(r"[0-9A-Fa-f]{8,16}", target):
            continue
        yield target


def parse_isil_call_target(stripped_line: str) -> str | None:
    match = ISIL_CALL_LINE_RE.match(stripped_line)
    if not match:
        return None
    rest = match.group("rest").lstrip()
    if not rest:
        return None
    if rest.startswith('"'):
        end = rest.find('"', 1)
        if end > 1:
            return rest[1:end]
        return None

    depth = 0
    end = 0
    for index, char in enumerate(rest):
        if char == "<":
            depth += 1
        elif char == ">" and depth:
            depth -= 1
        elif depth == 0 and (char == "," or char.isspace()):
            break
        end = index + 1
    return rest[:end].strip() or None


def split_isil_operands(rest: str) -> tuple[str, str] | None:
    angle_depth = 0
    paren_depth = 0
    bracket_depth = 0
    for index, char in enumerate(rest):
        if char == "<":
            angle_depth += 1
        elif char == ">" and angle_depth:
            angle_depth -= 1
        elif char == "(":
            paren_depth += 1
        elif char == ")" and paren_depth:
            paren_depth -= 1
        elif char == "[":
            bracket_depth += 1
        elif char == "]" and bracket_depth:
            bracket_depth -= 1
        elif char == "," and angle_depth == 0 and paren_depth == 0 and bracket_depth == 0:
            return rest[:index].strip(), rest[index + 1 :].strip()
    return None


def split_isil_csv_operands(rest: str) -> list[str]:
    angle_depth = 0
    paren_depth = 0
    bracket_depth = 0
    in_quote = False
    escaped = False
    current: list[str] = []
    parts: list[str] = []
    for char in rest:
        if in_quote:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_quote = False
            continue
        if char == '"':
            in_quote = True
            current.append(char)
            continue
        if char == "<":
            angle_depth += 1
        elif char == ">" and angle_depth:
            angle_depth -= 1
        elif char == "(":
            paren_depth += 1
        elif char == ")" and paren_depth:
            paren_depth -= 1
        elif char == "[":
            bracket_depth += 1
        elif char == "]" and bracket_depth:
            bracket_depth -= 1
        if char == "," and angle_depth == 0 and paren_depth == 0 and bracket_depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        current.append(char)
    final = "".join(current).strip()
    if final:
        parts.append(final)
    return parts


def is_member_assignment_target(target: str) -> bool:
    if "." not in target:
        return False
    if target.startswith("["):
        return False
    if re.fullmatch(r"v\d+\s+@\s+[A-Za-z_][\w+\-]*(?:_v\d+)?(?:\s+\([^)]+\))?", target):
        return False
    member = target.rsplit(".", 1)[-1]
    if not member or " " in member:
        return False
    return bool(re.search(r"[A-Za-z_<>]", member))


def compact_isil_operand(value: str, limit: int = 160) -> str:
    return compact_text(value.strip(), limit)


def strip_isil_type_hints(value: str) -> str:
    text = re.sub(r"\s+@\s+[A-Za-z_][\w+\-]*(?:_v\d+)?", "", value)
    text = re.sub(r"\s+\([^()]*\)", "", text)
    return " ".join(text.split())


def normalize_outline_aliases(value: str, this_aliases: set[str] | None = None) -> str:
    text = value
    for alias in sorted(this_aliases or set(), key=len, reverse=True):
        if alias == "this":
            continue
        text = re.sub(rf"\b{re.escape(alias)}(?=\.)", "this", text)
        text = re.sub(rf"\[{re.escape(alias)}(?=[+\]])", "[this", text)
        text = re.sub(rf"\b{re.escape(alias)}\b", "this", text)
    return text


def render_static_operand(
    value: str,
    fields: dict[int, FieldInfo] | None = None,
    this_aliases: set[str] | None = None,
    limit: int = 120,
) -> str:
    aliases = this_aliases or {"this"}
    stripped = value.strip()
    offset_match = ISIL_OWNER_OFFSET_RE.fullmatch(stripped)
    if offset_match and offset_match.group("owner") in aliases:
        offset = int(offset_match.group("offset"), 16)
        field = (fields or {}).get(offset)
        if field:
            return f"this.{field.name}"
    return compact_text(normalize_outline_aliases(strip_isil_type_hints(stripped), this_aliases), limit)


def extract_call_arguments(
    line: str,
    this_aliases: set[str] | None = None,
    fields: dict[int, FieldInfo] | None = None,
) -> list[str]:
    call_match = ISIL_CALL_LINE_RE.match(line.strip())
    if not call_match:
        return []
    rest = call_match.group("rest").lstrip()
    target = parse_isil_call_target(line.strip())
    if not target:
        return []
    if rest.startswith('"'):
        target_end = rest.find('"', 1)
        remaining = rest[target_end + 1 :].lstrip()
    else:
        remaining = rest[len(target) :].lstrip()
    if remaining.startswith(","):
        remaining = remaining[1:].lstrip()

    args = [
        render_static_operand(arg, fields, this_aliases, 80)
        for arg in split_isil_csv_operands(remaining)
        if arg.strip()
    ]
    if call_match.group("opcode") == "Call" and args:
        args = args[1:]
    return args


def extract_call_result(
    line: str,
    this_aliases: set[str] | None = None,
    fields: dict[int, FieldInfo] | None = None,
) -> str | None:
    call_match = ISIL_CALL_LINE_RE.match(line.strip())
    if not call_match or call_match.group("opcode") != "Call":
        return None
    rest = call_match.group("rest").lstrip()
    target = parse_isil_call_target(line.strip())
    if not target:
        return None
    if rest.startswith('"'):
        target_end = rest.find('"', 1)
        remaining = rest[target_end + 1 :].lstrip()
    else:
        remaining = rest[len(target) :].lstrip()
    if remaining.startswith(","):
        remaining = remaining[1:].lstrip()
    operands = split_isil_operands(remaining)
    if operands:
        return render_static_operand(operands[0], fields, this_aliases, 80)
    if remaining:
        return render_static_operand(remaining, fields, this_aliases, 80)
    return None


def isil_operand_owner(value: str) -> str:
    return value.strip().split(".", 1)[0].split(None, 1)[0]


def infer_isil_this_aliases(method: MethodBlock, type_name: str | None = None) -> set[str]:
    aliases = {"this"}
    in_isil = False
    for line in method.body:
        stripped = line.strip()
        if stripped == "ISIL:":
            in_isil = True
            continue
        if stripped == "Disassembly:":
            in_isil = False
            continue
        if not in_isil:
            continue
        match = ISIL_MOVE_LINE_RE.match(stripped)
        if not match:
            continue
        operands = split_isil_operands(match.group("rest"))
        if not operands:
            continue
        dest, src = operands
        if src.strip().startswith("this @"):
            aliases.add(isil_operand_owner(dest))
    return aliases


def named_call_owner(target: str) -> str:
    if "." not in target:
        return "(global/helper)"
    owner = target.rsplit(".", 1)[0].rstrip(".")
    return owner or "(global/helper)"


def named_call_member(target: str) -> str:
    owner = named_call_owner(target)
    if owner == "(global/helper)":
        return target
    prefix = f"{owner}."
    if target.startswith(prefix):
        return target[len(prefix):]
    return target.rsplit(".", 1)[-1]


def is_short_obfuscated_identifier(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z]{1,4}\d*", value))


def is_readable_named_call(target: str) -> bool:
    owner = named_call_owner(target)
    if owner == "(global/helper)" or is_short_obfuscated_identifier(owner):
        return False
    member = named_call_member(target)
    if member in {".ctor", "ctor"}:
        return True
    if is_short_obfuscated_identifier(member):
        return False
    return (
        any(char.isupper() for char in owner)
        and (
            any(char.isupper() for char in member)
            or member.startswith(("get_", "set_", "add_", "remove_"))
            or len(member) > 4
        )
    )


def build_readable_named_calls(named_calls: Counter[str]) -> Counter[str]:
    return Counter(
        {
            name: count
            for name, count in named_calls.items()
            if is_readable_named_call(name)
        }
    )


def build_readable_named_owner_calls(named_calls: Counter[str]) -> tuple[Counter[str], dict[str, Counter[str]]]:
    owners = Counter()
    owner_calls: dict[str, Counter[str]] = defaultdict(Counter)
    for name, count in build_readable_named_calls(named_calls).items():
        owner = named_call_owner(name)
        owners[owner] += count
        owner_calls[owner][name] += count
    return owners, owner_calls


def is_routine_helper_named_target(target: str) -> bool:
    return target.startswith("il2cpp_") or target in {
        "SzArrayNew",
        "ThrowIfNull",
    }


def is_routine_helper_address_entry(entry: AddressEntry) -> bool:
    return entry.kind in {"il2cpp_helper", "inferred_helper"} or entry.label.startswith("il2cpp_")


def collect_named_call_owners(method: MethodBlock) -> Counter[str]:
    owners: Counter[str] = Counter()
    _disasm, isil = split_method_body(method)
    for line in isil:
        for target in iter_named_call_targets(line):
            owners[named_call_owner(target)] += 1
    return owners


def collect_named_call_counts(method: MethodBlock) -> Counter[str]:
    counts: Counter[str] = Counter()
    _disasm, isil = split_method_body(method)
    for line in isil:
        for target in iter_named_call_targets(line):
            counts[target] += 1
    return counts


def collect_calls(
    method: MethodBlock,
    address_map: dict[str, AddressEntry],
) -> tuple[list[str], list[str], list[str]]:
    named: list[str] = []
    resolved: list[str] = []
    raw: list[str] = []
    seen_addresses: set[str] = set()
    for line in method.body:
        for target in iter_named_call_targets(line):
            named.append(target)
        for pattern in (RAW_CALL_RE, DISASM_CALL_RE):
            for match in pattern.finditer(line):
                address = normalize_address(match.group("target"))
                if address in seen_addresses:
                    continue
                seen_addresses.add(address)
                entry = address_map.get(address)
                if entry:
                    resolved.append(f"{address} = {format_address_entry(entry)}")
                else:
                    raw.append(address)
    return list(dict.fromkeys(named)), list(dict.fromkeys(resolved)), list(dict.fromkeys(raw))


def collect_unresolved_call_contexts(
    method: MethodBlock,
    address_map: dict[str, AddressEntry],
    limit: int,
) -> tuple[list[CallContext], int]:
    contexts: list[CallContext] = []
    total = 0
    seen_addresses: set[str] = set()
    in_isil = False
    recent_lines: list[str] = []
    for line_number, line in enumerate(method.body, start=1):
        stripped = line.strip()
        if stripped == "ISIL:":
            in_isil = True
            recent_lines = []
            continue
        if stripped == "Disassembly:":
            in_isil = False
            recent_lines = []
            continue
        pattern = RAW_CALL_RE if in_isil else DISASM_CALL_RE
        for match in pattern.finditer(line):
            address = normalize_address(match.group("target"))
            if address in address_map:
                continue
            total += 1
            if address in seen_addresses or len(contexts) >= limit:
                continue
            seen_addresses.add(address)
            contexts.append(
                CallContext(
                    address=address,
                    view="ISIL" if in_isil else "disasm",
                    line_number=line_number,
                    lines=tuple(recent_lines[-2:] + [stripped]),
                )
            )
        if in_isil:
            recent_lines = remember_context_line(recent_lines, stripped)
        elif stripped:
            recent_lines.append(stripped)
            if len(recent_lines) > 2:
                recent_lines = recent_lines[-2:]
    return contexts, total


def collect_resolved_call_contexts(
    method: MethodBlock,
    address_map: dict[str, AddressEntry],
    limit: int,
) -> tuple[list[ResolvedCallContext], int]:
    contexts: list[ResolvedCallContext] = []
    total = 0
    seen_addresses: set[str] = set()
    in_isil = False
    recent_lines: list[str] = []
    for line_number, line in enumerate(method.body, start=1):
        stripped = line.strip()
        if stripped == "ISIL:":
            in_isil = True
            recent_lines = []
            continue
        if stripped == "Disassembly:":
            in_isil = False
            recent_lines = []
            continue
        pattern = RAW_CALL_RE if in_isil else DISASM_CALL_RE
        for match in pattern.finditer(line):
            address = normalize_address(match.group("target"))
            entry = address_map.get(address)
            if not entry:
                continue
            total += 1
            if address in seen_addresses or len(contexts) >= limit:
                continue
            seen_addresses.add(address)
            contexts.append(
                ResolvedCallContext(
                    address=address,
                    label=format_address_entry(entry),
                    view="ISIL" if in_isil else "disasm",
                    line_number=line_number,
                    lines=tuple(recent_lines[-2:] + [stripped]),
                )
            )
        recent_lines = remember_context_line(recent_lines, stripped)
    return contexts, total


def collect_named_call_contexts(
    method: MethodBlock,
    limit: int,
    target_filter: Callable[[str], bool] | None = None,
) -> tuple[list[NamedCallContext], int]:
    contexts: list[NamedCallContext] = []
    total = 0
    seen_targets: set[str] = set()
    in_isil = False
    recent_lines: list[str] = []
    for line_number, line in enumerate(method.body, start=1):
        stripped = line.strip()
        if stripped == "ISIL:":
            in_isil = True
            recent_lines = []
            continue
        if stripped == "Disassembly:":
            in_isil = False
            recent_lines = []
            continue
        if in_isil:
            for target in iter_named_call_targets(line):
                if target_filter is not None and not target_filter(target):
                    continue
                total += 1
                if target in seen_targets or len(contexts) >= limit:
                    continue
                seen_targets.add(target)
                contexts.append(
                    NamedCallContext(
                        target=target,
                        line_number=line_number,
                        lines=tuple(recent_lines[-2:] + [stripped]),
                    )
                )
        recent_lines = remember_context_line(recent_lines, stripped)
    return contexts, total


def collect_isil_call_sequence(
    method: MethodBlock,
    address_map: dict[str, AddressEntry],
    limit: int,
) -> tuple[list[CallSequenceItem], int]:
    sequence: list[CallSequenceItem] = []
    total = 0
    in_isil = False
    for line_number, line in enumerate(method.body, start=1):
        stripped = line.strip()
        if stripped == "ISIL:":
            in_isil = True
            continue
        if stripped == "Disassembly:":
            in_isil = False
            continue
        if not in_isil:
            continue
        call_match = ISIL_CALL_LINE_RE.match(stripped)
        if not call_match:
            continue
        target = parse_isil_call_target(stripped)
        if not target:
            continue
        if re.fullmatch(r"[0-9A-Fa-f]{8,16}", target):
            address = normalize_address(target)
            entry = address_map.get(address)
            if entry:
                if is_routine_helper_address_entry(entry):
                    continue
                kind = "resolved"
                label = f"{address} = {format_address_entry(entry)}"
            else:
                kind = "unresolved"
                label = address
        else:
            if is_routine_helper_named_target(target):
                continue
            kind = "named"
            label = target
        total += 1
        if len(sequence) >= limit:
            continue
        sequence.append(
            CallSequenceItem(
                step=total,
                line_number=line_number,
                kind=kind,
                target=label,
                line=compact_text(stripped),
            )
        )
    return sequence, total


def collect_isil_member_assignments(
    method: MethodBlock,
    limit: int,
    type_name: str | None = None,
) -> tuple[list[MemberAssignmentItem], int]:
    assignments: list[MemberAssignmentItem] = []
    total = 0
    in_isil = False
    this_aliases = infer_isil_this_aliases(method, type_name)
    for line_number, line in enumerate(method.body, start=1):
        stripped = line.strip()
        if stripped == "ISIL:":
            in_isil = True
            continue
        if stripped == "Disassembly:":
            in_isil = False
            continue
        if not in_isil:
            continue
        match = ISIL_MOVE_LINE_RE.match(stripped)
        if not match:
            continue
        operands = split_isil_operands(match.group("rest"))
        if not operands:
            continue
        target = compact_isil_operand(operands[0])
        if not is_member_assignment_target(target):
            continue
        if isil_operand_owner(target) not in this_aliases:
            continue
        value = compact_isil_operand(operands[1])
        total += 1
        if len(assignments) >= limit:
            continue
        assignments.append(
            MemberAssignmentItem(
                step=total,
                line_number=line_number,
                target=target,
                value=value,
                line=compact_text(stripped),
            )
        )
    return assignments, total


def collect_branch_contexts(method: MethodBlock, limit: int) -> tuple[list[BranchContext], int]:
    contexts: list[BranchContext] = []
    total = 0
    in_isil = False
    recent_lines: list[str] = []
    for line_number, line in enumerate(method.body, start=1):
        stripped = line.strip()
        if stripped == "ISIL:":
            in_isil = True
            recent_lines = []
            continue
        if stripped == "Disassembly:":
            in_isil = False
            recent_lines = []
            continue
        if in_isil and " ConditionalJump " in f" {stripped} ":
            total += 1
            if len(contexts) < limit:
                target_match = re.search(r"\bConditionalJump\s+(?P<target>@[A-Za-z0-9_]+)", stripped)
                contexts.append(
                    BranchContext(
                        target=target_match.group("target") if target_match else "?",
                        line_number=line_number,
                        lines=tuple(recent_lines[-2:] + [stripped]),
                    )
                )
        recent_lines = remember_context_line(recent_lines, stripped)
    return contexts, total


def collect_branch_target_summaries(method: MethodBlock, limit: int) -> tuple[list[BranchTargetSummary], int]:
    counts: Counter[str] = Counter()
    first_seen: dict[str, tuple[int, tuple[str, ...]]] = {}
    in_isil = False
    recent_lines: list[str] = []
    for line_number, line in enumerate(method.body, start=1):
        stripped = line.strip()
        if stripped == "ISIL:":
            in_isil = True
            recent_lines = []
            continue
        if stripped == "Disassembly:":
            in_isil = False
            recent_lines = []
            continue
        if in_isil and " ConditionalJump " in f" {stripped} ":
            target_match = re.search(r"\bConditionalJump\s+(?P<target>@[A-Za-z0-9_]+)", stripped)
            target = target_match.group("target") if target_match else "?"
            counts[target] += 1
            if target not in first_seen:
                first_seen[target] = (line_number, tuple(recent_lines[-2:] + [stripped]))
        recent_lines = remember_context_line(recent_lines, stripped)

    summaries = [
        BranchTargetSummary(
            target=target,
            observations=count,
            first_line_number=first_seen[target][0],
            first_lines=first_seen[target][1],
        )
        for target, count in counts.most_common(limit)
    ]
    return summaries, len(counts)


def collect_return_contexts(method: MethodBlock, limit: int) -> tuple[list[ReturnContext], int]:
    contexts: list[ReturnContext] = []
    total = 0
    in_isil = False
    recent_lines: list[str] = []
    for line_number, line in enumerate(method.body, start=1):
        stripped = line.strip()
        if stripped == "ISIL:":
            in_isil = True
            recent_lines = []
            continue
        if stripped == "Disassembly:":
            in_isil = False
            recent_lines = []
            continue
        return_match = re.match(r"^\d+\s+Return\b\s*(?P<expression>.*)$", stripped)
        if in_isil and return_match:
            total += 1
            if len(contexts) < limit:
                expression = return_match.group("expression").strip()
                contexts.append(
                    ReturnContext(
                        line_number=line_number,
                        expression=expression or "(void)",
                        lines=tuple(recent_lines[-2:] + [stripped]),
                    )
                )
        recent_lines = remember_context_line(recent_lines, stripped)
    return contexts, total


def is_routine_metadata_guard_branch(context: str) -> bool:
    return bool(STATIC_METADATA_FLAG_CHECK_RE.search(context))


def collect_method_skeleton(
    method: MethodBlock,
    address_map: dict[str, AddressEntry],
    limit: int,
    type_name: str | None = None,
) -> tuple[list[MethodSkeletonItem], int]:
    items: list[MethodSkeletonItem] = []
    total = 0
    in_isil = False
    this_aliases = infer_isil_this_aliases(method, type_name)
    recent_lines: list[str] = []
    branch_target_counts: Counter[str] = Counter()
    branch_events = 0

    def append_item(line_number: int, kind: str, detail: str, evidence: str) -> None:
        nonlocal total
        total += 1
        if len(items) >= limit:
            return
        items.append(
            MethodSkeletonItem(
                step=total,
                line_number=line_number,
                kind=kind,
                detail=compact_text(detail, 180),
                evidence=evidence,
            )
        )

    for line_number, line in enumerate(method.body, start=1):
        stripped = line.strip()
        if stripped == "ISIL:":
            in_isil = True
            recent_lines = []
            continue
        if stripped == "Disassembly:":
            in_isil = False
            recent_lines = []
            continue
        if not in_isil:
            continue

        move_match = ISIL_MOVE_LINE_RE.match(stripped)
        if move_match:
            operands = split_isil_operands(move_match.group("rest"))
            if operands:
                target = compact_isil_operand(operands[0])
                if is_member_assignment_target(target) and isil_operand_owner(target) in this_aliases:
                    value = compact_isil_operand(operands[1])
                    append_item(line_number, "field/member write", f"{target} = {value}", stripped)

        call_match = ISIL_CALL_LINE_RE.match(stripped)
        if call_match:
            target = parse_isil_call_target(stripped)
            if target:
                if re.fullmatch(r"[0-9A-Fa-f]{8,16}", target):
                    address = normalize_address(target)
                    entry = address_map.get(address)
                    if entry and is_routine_helper_address_entry(entry):
                        target = ""
                    elif entry:
                        target = f"{address} = {format_address_entry(entry)}"
                    else:
                        target = address
                elif is_routine_helper_named_target(target):
                    target = ""
                if target:
                    append_item(line_number, "call", target, stripped)

        branch_match = re.search(r"\bConditionalJump\s+(?P<target>@[A-Za-z0-9_]+)", stripped)
        if branch_match:
            context = " | ".join(recent_lines[-2:] + [stripped])
            target = branch_match.group("target")
            branch_target_counts[target] += 1
            if (
                branch_events < 16
                and branch_target_counts[target] <= 3
                and "Il2CppClass" not in context
                and "il2cpp_runtime_class_init_export" not in context
                and not is_routine_metadata_guard_branch(context)
            ):
                branch_events += 1
                append_item(line_number, "conditional branch", target, context)

        return_match = re.match(r"^\d+\s+Return\b\s*(?P<expression>.*)$", stripped)
        if return_match:
            expression = return_match.group("expression").strip() or "(void)"
            append_item(line_number, "return", expression, stripped)

        recent_lines = remember_context_line(recent_lines, stripped)
    return items, total


CHECK_OPERATOR_LABELS = {
    "CheckEqual": "==",
    "CheckNotEqual": "!=",
    "CheckLess": "<",
    "CheckLessOrEqual": "<=",
    "CheckGreater": ">",
    "CheckGreaterOrEqual": ">=",
}


def format_check_condition(
    check_text: str,
    this_aliases: set[str] | None = None,
    fields: dict[int, FieldInfo] | None = None,
) -> str:
    match = re.match(r"^(?P<opcode>Check[A-Za-z]+)\s+(?P<rest>.+)$", check_text.strip())
    if not match:
        return render_static_operand(check_text, fields, this_aliases, 140)
    opcode = match.group("opcode")
    operator_label = CHECK_OPERATOR_LABELS.get(opcode)
    if not operator_label:
        return render_static_operand(check_text, fields, this_aliases, 140)
    operands = [
        render_static_operand(operand, fields, this_aliases, 140)
        for operand in split_isil_csv_operands(match.group("rest"))
    ]
    if len(operands) != 3:
        return render_static_operand(check_text, fields, this_aliases, 140)
    compared = operands[1:]
    return compact_text(f"{compared[0]} {operator_label} {compared[1]}", 140)


def branch_condition_from_evidence(
    evidence: str,
    this_aliases: set[str] | None = None,
    fields: dict[int, FieldInfo] | None = None,
) -> str:
    parts = [part.strip() for part in evidence.split(" | ") if part.strip()]
    for part in reversed(parts):
        if " ConditionalJump " in f" {part} ":
            continue
        if re.match(r"^\d+\s+Check", part):
            text = re.sub(r"^\d+\s+", "", part)
            return format_check_condition(text, this_aliases, fields)
    return "condition"


def outline_call_target(detail: str) -> str:
    match = re.match(r"0x[0-9A-Fa-f]+\s+=\s+(?P<label>.+)$", detail)
    if not match:
        return detail
    label = match.group("label")
    label = re.sub(r"\s+\[[^\]]+\]$", "", label)
    return label


def render_skeleton_outline_lines(
    items: list[MethodSkeletonItem],
    limit: int = 32,
    this_aliases: set[str] | None = None,
    fields: dict[int, FieldInfo] | None = None,
) -> list[str]:
    lines: list[str] = []
    for item in items[:limit]:
        if item.kind == "field/member write":
            lines.append(
                f"{render_static_operand(item.detail, fields, this_aliases, 140)};"
            )
        elif item.kind == "call":
            args = extract_call_arguments(item.evidence, this_aliases, fields)
            arg_text = ", ".join(args[:4])
            if len(args) > 4:
                arg_text += ", ..."
            result = extract_call_result(item.evidence, this_aliases, fields)
            call_text = f"{outline_call_target(item.detail)}({arg_text});"
            if result:
                call_text = f"{result} = {call_text}"
            lines.append(call_text)
        elif item.kind == "conditional branch":
            lines.append(f"if ({branch_condition_from_evidence(item.evidence, this_aliases, fields)}) goto {item.detail};")
        elif item.kind == "return":
            expression = render_static_operand(item.detail, fields, this_aliases)
            if expression == "(void)":
                lines.append("return;")
            else:
                lines.append(f"return {compact_text(expression, 120)};")
    if len(items) > limit:
        lines.append(f"// ... {len(items) - limit} additional skeleton events omitted")
    return lines


def collect_symbol_aliases(method: MethodBlock, limit: int) -> list[SymbolAliasSummary]:
    wanted = {"this"} | split_signature_parameters(method.signature)
    if not wanted:
        return []

    observations: dict[str, int] = {}
    storages: dict[str, Counter[str]] = {}
    type_hints: dict[str, Counter[str]] = {}
    first_seen: dict[str, tuple[int, str]] = {}
    in_isil = False
    for line_number, line in enumerate(method.body, start=1):
        stripped = line.strip()
        if stripped == "ISIL:":
            in_isil = True
            continue
        if stripped == "Disassembly:":
            in_isil = False
            continue
        if not in_isil:
            continue
        for match in SYMBOL_ALIAS_RE.finditer(stripped):
            if match.start() > 0 and stripped[match.start() - 1] == "[":
                continue
            symbol = match.group("name").lstrip("@")
            if symbol not in wanted:
                continue
            storage = match.group("storage")
            type_hint = match.group("type")
            observations[symbol] = observations.get(symbol, 0) + 1
            storages.setdefault(symbol, Counter())[storage] += 1
            if type_hint:
                type_hints.setdefault(symbol, Counter())[type_hint] += 1
            first_seen.setdefault(symbol, (line_number, stripped))

    summaries: list[SymbolAliasSummary] = []
    for symbol, count in observations.items():
        first_line_number, first_line = first_seen[symbol]
        summaries.append(
            SymbolAliasSummary(
                symbol=symbol,
                observations=count,
                storages=tuple(storages.get(symbol, Counter()).most_common(4)),
                type_hints=tuple(type_hints.get(symbol, Counter()).most_common(4)),
                first_line_number=first_line_number,
                first_line=first_line,
            )
        )
    return sorted(
        summaries,
        key=lambda item: (0 if item.symbol == "this" else 1, -item.observations, item.symbol),
    )[:limit]


def operand_mentions_symbol(text: str, symbol: str) -> bool:
    return bool(re.search(rf"(?<![\w]){re.escape(symbol)}(?![\w])", text))


def classify_parameter_use(line: str, parameter: str) -> str:
    stripped = line.strip()
    if ISIL_CALL_LINE_RE.match(stripped):
        return "call operand"
    if re.match(r"^\d+\s+Check[A-Za-z]+\b", stripped):
        return "comparison"
    if re.match(r"^\d+\s+ConditionalJump\b", stripped):
        return "branch operand"
    move_match = ISIL_MOVE_LINE_RE.match(stripped)
    if move_match:
        operands = split_isil_operands(move_match.group("rest"))
        if operands and operand_mentions_symbol(operands[0], parameter):
            return "move target"
        return "move value"
    if re.match(r"^\d+\s+Return\b", stripped):
        return "return"
    return "other"


def collect_parameter_uses(
    method: MethodBlock,
    limit: int,
    address_map: dict[str, AddressEntry] | None = None,
) -> tuple[list[ParameterUseSummary], int]:
    parameters = split_signature_parameter_names(method.signature)
    if not parameters:
        return [], 0

    by_param: dict[str, dict[str, object]] = {
        parameter: {
            "observations": 0,
            "uses": Counter(),
            "first_line_number": 0,
            "first_line": "",
        }
        for parameter in parameters
    }
    in_isil = False

    for line_number, line in enumerate(method.body, start=1):
        stripped = line.strip()
        if stripped == "ISIL:":
            in_isil = True
            continue
        if stripped == "Disassembly:":
            in_isil = False
            continue
        if not in_isil:
            continue
        if address_map is not None and is_helper_or_setup_isil_line(stripped, address_map):
            continue
        for parameter in parameters:
            if not operand_mentions_symbol(stripped, parameter):
                continue
            use_kind = classify_parameter_use(stripped, parameter)
            bucket = by_param[parameter]
            bucket["observations"] = int(bucket["observations"]) + 1
            uses = bucket["uses"]
            assert isinstance(uses, Counter)
            uses[use_kind] += 1
            if not bucket["first_line"]:
                bucket["first_line_number"] = line_number
                bucket["first_line"] = stripped

    summaries: list[ParameterUseSummary] = []
    for parameter in parameters:
        bucket = by_param[parameter]
        observations = int(bucket["observations"])
        if not observations:
            continue
        uses = bucket["uses"]
        assert isinstance(uses, Counter)
        summaries.append(
            ParameterUseSummary(
                parameter=parameter,
                observations=observations,
                uses=tuple(uses.most_common()),
                first_line_number=int(bucket["first_line_number"]),
                first_line=str(bucket["first_line"]),
            )
        )
    return summaries[:limit], len(summaries)


def count_call_sites(method: MethodBlock, address_map: dict[str, AddressEntry]) -> CallSummary:
    disasm_native = 0
    isil_raw = 0
    resolved_native = 0
    unresolved_native = 0
    named = 0
    unique_named: set[str] = set()
    unique_resolved_native: set[str] = set()
    unique_unresolved_native: set[str] = set()
    disasm, isil = split_method_body(method)

    for line in isil:
        for target in iter_named_call_targets(line):
            named += 1
            unique_named.add(target)
        for match in RAW_CALL_RE.finditer(line):
            isil_raw += 1
            address = normalize_address(match.group("target"))
            if address in address_map:
                resolved_native += 1
                unique_resolved_native.add(address)
            else:
                unresolved_native += 1
                unique_unresolved_native.add(address)

    for line in disasm:
        for match in DISASM_CALL_RE.finditer(line):
            disasm_native += 1
            address = normalize_address(match.group("target"))
            if address in address_map:
                resolved_native += 1
                unique_resolved_native.add(address)
            else:
                unresolved_native += 1
                unique_unresolved_native.add(address)

    return CallSummary(
        disasm_native_sites=disasm_native,
        isil_raw_sites=isil_raw,
        resolved_native_observations=resolved_native,
        unresolved_native_observations=unresolved_native,
        named_sites=named,
        unique_resolved_native=len(unique_resolved_native),
        unique_unresolved_native=len(unique_unresolved_native),
        unique_named=len(unique_named),
    )


def classify_disasm_field_access(line: str, reg: str) -> str:
    stripped = line.strip()
    if re.match(rf"lea\s+\w+,\s*\[{re.escape(reg)}\+", stripped):
        return "ref"
    operand_match = re.match(r"(?P<opcode>[a-z][a-z0-9]*)\s+(?P<operands>.+)", stripped)
    if operand_match:
        opcode = operand_match.group("opcode")
        first_operand = operand_match.group("operands").split(",", 1)[0].strip()
        if re.search(rf"(?:^|\s)\[{re.escape(reg)}\+", first_operand):
            if opcode in {"cmp", "test"}:
                return "read"
            return "write"
    return "read"


def classify_isil_this_field_access(line: str) -> str:
    if re.search(r"\bMove\s+\[this\s*@\s*rcx\+", line):
        return "write"
    return "read"


def collect_field_accesses(
    method: MethodBlock,
    fields: dict[int, FieldInfo],
    this_registers: set[str],
) -> list[FieldAccessSummary]:
    summaries = {offset: FieldAccessSummary(field=field) for offset, field in fields.items()}
    disasm, isil = split_method_body(method)

    for line in isil:
        for match in ISIL_THIS_OFFSET_RE.finditer(line):
            offset = int(match.group("offset"), 16)
            summary = summaries.get(offset)
            if not summary:
                continue
            if classify_isil_this_field_access(line) == "write":
                summary.exact_writes += 1
            else:
                summary.exact_reads += 1

    for line in disasm:
        for match in REG_OFFSET_RE.finditer(line):
            reg = match.group("reg")
            if reg not in this_registers:
                continue
            offset = int(match.group("offset"), 16)
            summary = summaries.get(offset)
            if not summary:
                continue
            kind = classify_disasm_field_access(line, reg)
            if kind == "write":
                summary.possible_writes += 1
            elif kind == "ref":
                summary.possible_refs += 1
            else:
                summary.possible_reads += 1

    return [
        summary
        for summary in summaries.values()
        if (
            summary.exact_reads
            or summary.exact_writes
            or summary.possible_reads
            or summary.possible_writes
            or summary.possible_refs
        )
    ]


def collect_field_access_contexts(
    method: MethodBlock,
    fields: dict[int, FieldInfo],
    this_registers: set[str],
    limit: int,
) -> tuple[list[FieldAccessContext], int]:
    contexts: list[FieldAccessContext] = []
    total = 0
    seen: set[tuple[int, str, str, str]] = set()
    in_isil = False
    recent_lines: list[str] = []
    for line_number, line in enumerate(method.body, start=1):
        stripped = line.strip()
        if stripped == "ISIL:":
            in_isil = True
            recent_lines = []
            continue
        if stripped == "Disassembly:":
            in_isil = False
            recent_lines = []
            continue

        if in_isil:
            for match in ISIL_THIS_OFFSET_RE.finditer(stripped):
                offset = int(match.group("offset"), 16)
                field = fields.get(offset)
                if not field:
                    continue
                kind = classify_isil_this_field_access(stripped)
                key = (offset, "exact", kind, "ISIL")
                total += 1
                if key not in seen and len(contexts) < limit:
                    seen.add(key)
                    contexts.append(
                        FieldAccessContext(
                            field=field,
                            confidence="exact",
                            access_kind=kind,
                            view="ISIL",
                            line_number=line_number,
                            lines=tuple(recent_lines[-2:] + [stripped]),
                        )
                    )
        else:
            for match in REG_OFFSET_RE.finditer(stripped):
                reg = match.group("reg")
                if reg not in this_registers:
                    continue
                offset = int(match.group("offset"), 16)
                field = fields.get(offset)
                if not field:
                    continue
                kind = classify_disasm_field_access(stripped, reg)
                key = (offset, "possible", kind, "disasm")
                total += 1
                if key not in seen and len(contexts) < limit:
                    seen.add(key)
                    contexts.append(
                        FieldAccessContext(
                            field=field,
                            confidence="possible",
                            access_kind=kind,
                            view="disasm",
                            line_number=line_number,
                            lines=tuple(recent_lines[-2:] + [stripped]),
                        )
                    )
        recent_lines = remember_context_line(recent_lines, stripped)
    return contexts, total


def collect_field_data_flow(
    method: MethodBlock,
    fields: dict[int, FieldInfo],
    this_registers: set[str],
    limit: int,
) -> tuple[list[FieldDataFlowSummary], int]:
    summaries: list[FieldDataFlowSummary] = []
    for access in collect_field_accesses(method, fields, this_registers):
        read_observations = access.exact_reads + access.possible_reads
        write_observations = access.exact_writes + access.possible_writes
        address_observations = access.possible_refs
        exact_observations = access.exact_reads + access.exact_writes
        possible_observations = access.possible_reads + access.possible_writes + access.possible_refs

        use_parts: list[str] = []
        if read_observations:
            use_parts.append("read")
        if write_observations:
            use_parts.append("write")
        if address_observations:
            use_parts.append("address/ref")
        observed_use = ", ".join(use_parts)

        if exact_observations and possible_observations:
            confidence = "exact + possible"
        elif exact_observations:
            confidence = "exact"
        else:
            confidence = "possible"

        summaries.append(
            FieldDataFlowSummary(
                field=access.field,
                observed_use=observed_use,
                exact_observations=exact_observations,
                possible_observations=possible_observations,
                read_observations=read_observations,
                write_observations=write_observations,
                address_observations=address_observations,
                confidence=confidence,
            )
        )

    summaries.sort(
        key=lambda item: (
            0 if item.write_observations else 1,
            0 if item.exact_observations else 1,
            -(item.read_observations + item.write_observations + item.address_observations),
            item.field.offset,
        )
    )
    return summaries[:limit], len(summaries)


def collect_control_summary(method: MethodBlock) -> ControlSummary:
    disasm, isil = split_method_body(method)
    conditional_jumps = 0
    unconditional_jumps = 0
    returns = 0
    int3_traps = 0
    for line in disasm:
        stripped = line.strip()
        if re.match(r"j[a-z]+\s+", stripped) and not stripped.startswith("jmp "):
            conditional_jumps += 1
        elif stripped.startswith("jmp "):
            unconditional_jumps += 1
        elif stripped == "ret":
            returns += 1
        elif stripped == "int 3":
            int3_traps += 1

    return ControlSummary(
        disasm_lines=sum(1 for line in disasm if line.strip()),
        isil_lines=sum(1 for line in isil if line.strip()),
        conditional_jumps=conditional_jumps,
        unconditional_jumps=unconditional_jumps,
        returns=returns,
        int3_traps=int3_traps,
    )


def render_readable_summary(
    method: MethodBlock,
    fields: dict[int, FieldInfo],
    this_registers: set[str],
    address_map: dict[str, AddressEntry],
) -> list[str]:
    call_summary = count_call_sites(method, address_map)
    control_summary = collect_control_summary(method)
    field_accesses = collect_field_accesses(method, fields, this_registers)
    named_call_owners = collect_named_call_owners(method)

    lines = ["", "Readable summary:", ""]
    lines.append(
        f"- Disassembly shape: {control_summary.disasm_lines} lines, "
        f"{control_summary.conditional_jumps} conditional jumps, "
        f"{control_summary.unconditional_jumps} unconditional jumps, "
        f"{control_summary.returns} returns, {control_summary.int3_traps} traps."
    )
    lines.append(f"- ISIL view: {control_summary.isil_lines} non-empty lines.")
    lines.append(
        f"- Calls: {call_summary.disasm_native_sites} disassembly native call sites, "
        f"{call_summary.isil_raw_sites} ISIL raw call observations, "
        f"{call_summary.named_sites} Cpp2IL-named call observations "
        f"({call_summary.unique_named} unique names)."
    )
    if named_call_owners:
        examples = ", ".join(
            f"`{owner}` x{count}"
            for owner, count in named_call_owners.most_common(5)
        )
        lines.append(
            "- Named-call target-prefix groups: "
            f"{len(named_call_owners)} groups; top groups: {examples}. "
            "Prefixes are grouping hints from Cpp2IL target text, not semantic identity claims."
        )
    lines.append(
        f"- Native call resolution: {call_summary.resolved_native_observations} "
        f"resolved observations by address map "
        f"({call_summary.unique_resolved_native} unique native addresses), "
        f"{call_summary.unresolved_native_observations} unresolved observations "
        f"({call_summary.unique_unresolved_native} unique native addresses)."
    )
    if field_accesses:
        lines.append(
            "- Field access candidates: exact ISIL `this` matches plus unverified "
            "native-register matches; `possible` entries require body audit."
        )
        for summary in sorted(field_accesses, key=lambda item: item.field.offset):
            parts = []
            if summary.exact_reads:
                parts.append(f"{summary.exact_reads} exact read")
            if summary.exact_writes:
                parts.append(f"{summary.exact_writes} exact write")
            if summary.possible_reads:
                parts.append(f"{summary.possible_reads} possible read")
            if summary.possible_writes:
                parts.append(f"{summary.possible_writes} possible write")
            if summary.possible_refs:
                parts.append(f"{summary.possible_refs} possible by-ref/address use")
            lines.append(
                f"  - `0x{summary.field.offset:X}` `{summary.field.name}` "
                f"({summary.field.type_name}): {', '.join(parts)}"
            )
    else:
        lines.append("- Field access candidates: none matched known field offsets.")
    return lines


def collect_static_review_cues(
    method: MethodBlock,
    fields: dict[int, FieldInfo],
    this_registers: set[str],
    address_map: dict[str, AddressEntry],
    limit: int,
) -> tuple[list[ReviewCue], int]:
    cues: list[ReviewCue] = []

    readable_calls = build_readable_named_calls(collect_named_call_counts(method))
    for target, count in readable_calls.most_common(3):
        cues.append(
            ReviewCue(
                kind="readable call",
                detail=f"{target} x{count}",
                why="recognizable symbolic Cpp2IL call target",
                evidence=target,
            )
        )

    unresolved_contexts, _unresolved_total = collect_unresolved_call_contexts(method, address_map, 3)
    for context in unresolved_contexts:
        cues.append(
            ReviewCue(
                kind="unresolved native",
                detail=context.address,
                why=f"unmapped {context.view} call; inspect call-site context",
                evidence=" | ".join(context.lines),
            )
        )

    for summary in sorted(
        collect_field_accesses(method, fields, this_registers),
        key=lambda item: (
            -(item.exact_reads + item.exact_writes),
            -(item.possible_reads + item.possible_writes + item.possible_refs),
            item.field.offset,
        ),
    )[:3]:
        exact = summary.exact_reads + summary.exact_writes
        possible = summary.possible_reads + summary.possible_writes + summary.possible_refs
        detail = f"0x{summary.field.offset:X} {summary.field.name}"
        cues.append(
            ReviewCue(
                kind="field touch",
                detail=detail,
                why=f"known field offset touched; {exact} exact, {possible} possible observations",
                evidence=summary.field.type_name,
            )
        )

    return cues[:limit], len(cues)


def score_method(control: ControlSummary, calls: CallSummary, field_accesses: list[FieldAccessSummary]) -> int:
    exact_fields = sum(1 for item in field_accesses if item.exact_reads or item.exact_writes)
    possible_fields = sum(
        1
        for item in field_accesses
        if item.possible_reads or item.possible_writes or item.possible_refs
    )
    return (
        calls.unique_unresolved_native * 20
        + control.conditional_jumps
        + control.unconditional_jumps * 2
        + exact_fields * 4
        + possible_fields
        + max(0, control.disasm_lines // 25)
    )


def summarize_methods(
    methods: list[MethodBlock],
    fields: dict[int, FieldInfo],
    address_map: dict[str, AddressEntry],
) -> list[MethodSummary]:
    summaries: list[MethodSummary] = []
    for method in methods:
        this_registers = infer_this_registers(method)
        control = collect_control_summary(method)
        calls = count_call_sites(method, address_map)
        field_accesses = collect_field_accesses(method, fields, this_registers)
        summaries.append(
            MethodSummary(
                method=method,
                control=control,
                calls=calls,
                field_accesses=field_accesses,
                score=score_method(control, calls, field_accesses),
            )
        )
    return summaries


def render_type_indexes(
    summaries: list[MethodSummary],
    fields: dict[int, FieldInfo],
    address_map: dict[str, AddressEntry],
) -> list[str]:
    lines: list[str] = ["## Type-Level Index", ""]
    if not summaries:
        lines.append("No methods available for indexing.")
        lines.append("")
        return lines

    lines.append("### Method Triage")
    lines.append("")
    lines.append("| Score | Method | Shape | Calls | Fields |")
    lines.append("| ---: | --- | --- | --- | --- |")
    for summary in sorted(summaries, key=lambda item: item.score, reverse=True)[:25]:
        control = summary.control
        calls = summary.calls
        exact_fields = sum(1 for item in summary.field_accesses if item.exact_reads or item.exact_writes)
        possible_fields = sum(
            1
            for item in summary.field_accesses
            if item.possible_reads or item.possible_writes or item.possible_refs
        )
        shape = (
            f"{control.disasm_lines} asm, {control.isil_lines} isil, "
            f"{control.conditional_jumps} cond, {control.unconditional_jumps} jmp"
        )
        call_text = (
            f"{calls.unique_unresolved_native} unresolved native, "
            f"{calls.unique_resolved_native} resolved native, {calls.unique_named} named"
        )
        field_text = f"{exact_fields} exact, {possible_fields} possible"
        lines.append(
            f"| {summary.score} | {markdown_code(summary.method.signature)} | "
            f"{markdown_code(shape)} | {markdown_code(call_text)} | {markdown_code(field_text)} |"
        )
    lines.append("")

    if fields:
        field_rows: list[tuple[int, FieldInfo, int, int, list[str]]] = []
        for offset, field in sorted(fields.items()):
            exact_total = 0
            possible_total = 0
            methods_seen: list[str] = []
            for summary in summaries:
                for access in summary.field_accesses:
                    if access.field.offset != offset:
                        continue
                    exact = access.exact_reads + access.exact_writes
                    possible = access.possible_reads + access.possible_writes + access.possible_refs
                    exact_total += exact
                    possible_total += possible
                    if exact or possible:
                        methods_seen.append(summary.method.signature)
                    break
            if exact_total or possible_total:
                field_rows.append((exact_total + possible_total, field, exact_total, possible_total, methods_seen))

        lines.append("### Field Usage")
        lines.append("")
        if field_rows:
            lines.append("| Field | Type | Accesses | Example methods |")
            lines.append("| --- | --- | --- | --- |")
            for _total, field, exact_total, possible_total, methods_seen in sorted(
                field_rows,
                key=lambda item: (-item[0], item[1].offset),
            ):
                access_text = f"{exact_total} exact, {possible_total} possible"
                examples = "<br>".join(markdown_code(method) for method in methods_seen[:3])
                if len(methods_seen) > 3:
                    examples += f"<br>... {len(methods_seen) - 3} more"
                field_label = f"0x{field.offset:X} {field.name}"
                lines.append(
                    f"| {markdown_code(field_label)} | {markdown_code(field.type_name)} | "
                    f"{markdown_code(access_text)} | {examples} |"
                )
        else:
            lines.append("No indexed methods matched known field offsets.")
        lines.append("")

    unresolved_by_address: dict[str, set[str]] = {}
    for summary in summaries:
        _named_calls, _resolved_calls, raw_calls = collect_calls(summary.method, address_map)
        for address in raw_calls:
            unresolved_by_address.setdefault(address, set()).add(summary.method.signature)

    lines.append("### Unresolved Native Calls")
    lines.append("")
    if unresolved_by_address:
        lines.append("| Address | Method count | Example methods |")
        lines.append("| --- | ---: | --- |")
        for address, callers in sorted(
            unresolved_by_address.items(),
            key=lambda item: (-len(item[1]), item[0]),
        )[:25]:
            ordered = sorted(callers)
            examples = "<br>".join(markdown_code(method) for method in ordered[:3])
            if len(ordered) > 3:
                examples += f"<br>... {len(ordered) - 3} more"
            lines.append(f"| {markdown_code(address)} | {len(callers)} | {examples} |")
    else:
        lines.append("No unresolved native calls found in selected methods.")
    lines.append("")
    return lines


def is_helper_or_setup_isil_line(line: str, address_map: dict[str, AddressEntry]) -> bool:
    stripped = line.strip()
    if re.match(r"^\d+\s+Nop\b", stripped):
        return True
    call_match = ISIL_CALL_LINE_RE.match(stripped)
    if not call_match:
        return False
    target = parse_isil_call_target(stripped)
    if not target:
        return False
    address = normalize_address(target) if re.fullmatch(r"[0-9A-Fa-f]{8,16}", target) else None
    if address and address in address_map and address_map[address].kind in {"il2cpp_helper", "inferred_helper"}:
        return True
    return is_routine_helper_named_target(target)


def is_pointer_add_setup_for_helper(line: str, helper_inputs: set[str]) -> bool:
    match = re.match(
        r"^\d+\s+Add\s+(?P<dest>v\d+)\s+@\s+[^,]+,\s+this\s+@[^,]+,\s*(?:-?\d+|[0-9A-Fa-f]+h?)\s*$",
        line.strip(),
    )
    return bool(match and match.group("dest") in helper_inputs)


def summarize_trivial_method(
    method: MethodBlock,
    fields: dict[int, FieldInfo],
    address_map: dict[str, AddressEntry],
    type_name: str | None = None,
) -> str | None:
    isil_lines = [line.strip() for line in method.body if re.match(r"^\d+\s+", line.strip())]
    helper_inputs: set[str] = set()
    for line in isil_lines:
        if is_helper_or_setup_isil_line(line, address_map):
            helper_inputs.update(re.findall(r"\b(v\d+)\s+@", line))
    meaningful = [
        line
        for line in isil_lines
        if not is_helper_or_setup_isil_line(line, address_map)
        and not is_pointer_add_setup_for_helper(line, helper_inputs)
    ]
    returns = [line for line in meaningful if re.search(r"\bReturn\b", line)]
    moves = [line for line in meaningful if ISIL_MOVE_LINE_RE.match(line)]
    if not returns:
        return None
    if any(line not in returns and line not in moves for line in meaningful):
        return None

    this_aliases = infer_isil_this_aliases(method, type_name)
    if len(meaningful) == 1 and len(returns) == 1:
        ret = returns[0]
        expression = ret.split("Return", 1)[1].strip()
        if not expression:
            return "return;"
        literal_match = re.fullmatch(r"-?\d+", expression)
        if literal_match:
            return f"return {literal_match.group(0)};"
        return f"return {render_static_operand(expression, fields, this_aliases)};"

    if len(moves) == 1 and len(returns) == 1:
        operands = split_isil_operands(ISIL_MOVE_LINE_RE.match(moves[0]).group("rest"))  # type: ignore[union-attr]
        if not operands:
            return None
        target, value = operands
        rendered_target = render_static_operand(target, fields, this_aliases)
        rendered_value = render_static_operand(value, fields, this_aliases)
        return_expression = returns[0].split("Return", 1)[1].strip()
        if not return_expression:
            return f"{rendered_target} = {rendered_value};\nreturn;"
        rendered_return = render_static_operand(return_expression, fields, this_aliases)
        if rendered_return == rendered_target and not is_member_assignment_target(rendered_target):
            return f"return {rendered_value};"
        return f"{rendered_target} = {rendered_value};\nreturn {rendered_return};"

    if len(meaningful) != 1:
        return None

    ret = returns[0]
    literal_match = re.search(r"Return\s+(-?\d+)\b", ret)
    if literal_match:
        return f"return {literal_match.group(1)};"
    return None


def render_markdown(
    type_name: str,
    csharp_path: Path,
    isil_path: Path,
    fields: dict[int, FieldInfo],
    methods: list[MethodBlock],
    index_methods: list[MethodBlock],
    max_body_lines: int | None,
    address_map_path: Path | None,
    address_map: dict[str, AddressEntry],
    summary_only: bool,
) -> str:
    out: list[str] = []
    out.append(f"# {type_name}")
    out.append("")
    out.append("## Sources")
    out.append("")
    out.append(f"- Diffable C#: `{csharp_path}`")
    out.append(f"- ISIL: `{isil_path}`")
    if address_map_path is not None:
        out.append(f"- Address map: `{address_map_path}`")
    out.append("")
    out.append("## Field Offsets")
    out.append("")
    if fields:
        out.append("| Offset | Field | Type |")
        out.append("| --- | --- | --- |")
        for offset, field in sorted(fields.items()):
            out.append(
                f"| {markdown_code(f'0x{offset:X}')} | {markdown_code(field.name)} | "
                f"{markdown_code(field.type_name)} |"
            )
    else:
        out.append("No field offsets parsed from diffable C#.")
    out.append("")

    summaries = summarize_methods(index_methods, fields, address_map)
    out.extend(render_type_indexes(summaries, fields, address_map))

    out.append("## Methods")
    out.append("")
    if not methods:
        out.append("No matching methods found.")
        return "\n".join(out) + "\n"

    for method in methods:
        out.append(f"### {markdown_code(method.signature)}")
        this_registers = infer_this_registers(method)
        out.extend(render_readable_summary(method, fields, this_registers, address_map))
        review_cues, review_cue_total = collect_static_review_cues(method, fields, this_registers, address_map, 8)
        if review_cues:
            out.append("")
            out.append("Static review cues:")
            out.append("")
            out.append(
                "Shortlist of existing static evidence to inspect first; cues are triage hints, not semantic conclusions."
            )
            out.append("")
            out.append("| Kind | Detail | Why inspect | Evidence |")
            out.append("| --- | --- | --- | --- |")
            for cue in review_cues:
                out.append(
                    f"| {markdown_table_code(cue.kind)} | {markdown_table_code(cue.detail)} | "
                    f"{markdown_table_code(cue.why)} | {markdown_table_code(compact_text(cue.evidence, 160))} |"
                )
            if review_cue_total > len(review_cues):
                out.append("")
                out.append(
                    f"Shown: {len(review_cues)} static review cues; "
                    f"{review_cue_total - len(review_cues)} additional cues omitted."
                )
        field_flows, field_flow_total = collect_field_data_flow(method, fields, this_registers, 12)
        if field_flows:
            out.append("")
            out.append("Field data-flow summary:")
            out.append("")
            out.append(
                "Observed field reads/writes from exact ISIL `this` offsets and possible native `this` registers; possible rows still require body audit."
            )
            out.append("")
            out.append("| Field | Observed use | Observed reads | Observed writes | Address/ref | Evidence confidence |")
            out.append("| --- | --- | ---: | ---: | ---: | --- |")
            for flow in field_flows:
                field_label = f"0x{flow.field.offset:X} {flow.field.name}"
                out.append(
                    f"| {markdown_table_code(field_label)} | {markdown_table_code(flow.observed_use)} | "
                    f"{flow.read_observations} | {flow.write_observations} | {flow.address_observations} | "
                    f"{markdown_table_code(flow.confidence)} "
                    f"({flow.exact_observations} exact, {flow.possible_observations} possible) |"
                )
            if field_flow_total > len(field_flows):
                out.append("")
                out.append(
                    f"Shown: {len(field_flows)} field data-flow summaries; "
                    f"{field_flow_total - len(field_flows)} additional fields omitted."
                )
        field_contexts, field_context_total = collect_field_access_contexts(method, fields, this_registers, 12)
        if field_contexts:
            out.append("")
            out.append("Field access contexts:")
            out.append("")
            out.append("| Field | Confidence | Access | View | Body line | First context |")
            out.append("| --- | --- | --- | --- | ---: | --- |")
            for context in field_contexts:
                field_label = f"0x{context.field.offset:X} {context.field.name}"
                context_lines = "<br>".join(markdown_table_code(line) for line in context.lines)
                out.append(
                    f"| {markdown_table_code(field_label)} | {markdown_table_code(context.confidence)} | "
                    f"{markdown_table_code(context.access_kind)} | {markdown_table_code(context.view)} | "
                    f"{context.line_number} | {context_lines} |"
                )
            if field_context_total > len(field_contexts):
                out.append("")
                out.append(
                    f"Shown: {len(field_contexts)} first field access contexts; "
                    f"{field_context_total - len(field_contexts)} additional field access observations omitted."
                )
        symbol_aliases = collect_symbol_aliases(method, 12)
        if symbol_aliases:
            out.append("")
            out.append("ISIL source-symbol aliases:")
            out.append("")
            out.append("| Symbol | Observations | Storage hints | Type hints | First seen |")
            out.append("| --- | ---: | --- | --- | --- |")
            for alias in symbol_aliases:
                storage_hints = "<br>".join(
                    f"{markdown_table_code(storage)} x{count}" for storage, count in alias.storages
                )
                type_hints = "<br>".join(
                    f"{markdown_table_code(type_hint)} x{count}" for type_hint, count in alias.type_hints
                )
                if not type_hints:
                    type_hints = "-"
                first_seen = f"{alias.first_line_number}: {markdown_table_code(alias.first_line)}"
                out.append(
                    f"| {markdown_table_code(alias.symbol)} | {alias.observations} | "
                    f"{storage_hints} | {type_hints} | {first_seen} |"
                )
        parameter_uses, parameter_use_total = collect_parameter_uses(method, 12, address_map)
        if parameter_uses:
            out.append("")
            out.append("ISIL parameter-use summary:")
            out.append("")
            out.append(
                "Static observations of declared parameters in ISIL lines; this is a use-site index, not proof of parameter semantics."
            )
            out.append("")
            out.append("| Parameter | Observations | Use kinds | First seen |")
            out.append("| --- | ---: | --- | --- |")
            for item in parameter_uses:
                use_text = "<br>".join(
                    f"{markdown_table_code(kind)} x{count}" for kind, count in item.uses
                )
                first_seen = f"{item.first_line_number}: {markdown_table_code(item.first_line)}"
                out.append(
                    f"| {markdown_table_code(item.parameter)} | {item.observations} | "
                    f"{use_text} | {first_seen} |"
                )
            if parameter_use_total > len(parameter_uses):
                out.append("")
                out.append(
                    f"Shown: {len(parameter_uses)} parameter-use summaries; "
                    f"{parameter_use_total - len(parameter_uses)} additional parameters omitted."
                )
        pseudo = summarize_trivial_method(method, fields, address_map, type_name)
        if pseudo:
            out.append("")
            out.append("Simple static sketch:")
            out.append("")
            out.append(
                "Emitted only for tiny accessor-shaped ISIL after routine helper/setup lines are ignored."
            )
            out.append("")
            out.append("```csharp")
            out.append(pseudo)
            out.append("```")

        skeleton, skeleton_total = collect_method_skeleton(method, address_map, 48, type_name)
        if skeleton:
            out.append("")
            out.append("C#-oriented method skeleton:")
            out.append("")
            out.append(
                "This is an ordered static outline from ISIL facts only; it is not reconstructed control flow and does not prove original C# semantics."
            )
            out.append("")
            out.append("Static outline:")
            out.append("")
            out.append("```csharp")
            out.extend(render_skeleton_outline_lines(skeleton, 32, infer_isil_this_aliases(method, type_name), fields))
            out.append("```")
            out.append("")
            out.append("| Step | Body line | Kind | Detail | Evidence |")
            out.append("| ---: | ---: | --- | --- | --- |")
            for item in skeleton:
                out.append(
                    f"| {item.step} | {item.line_number} | {markdown_table_code(item.kind)} | "
                    f"{markdown_table_code(item.detail)} | {markdown_table_code(compact_text(item.evidence, 220))} |"
                )
            if skeleton_total > len(skeleton):
                out.append("")
                out.append(
                    f"Shown: first {len(skeleton)} skeleton events in order; "
                    f"{skeleton_total - len(skeleton)} additional events omitted."
                )

        member_assignments, member_assignment_total = collect_isil_member_assignments(method, 32, type_name)
        if member_assignments:
            out.append("")
            out.append("ISIL inferred instance-member assignment sketch:")
            out.append("")
            out.append(
                "These are chronological `Move` writes into member-looking destinations owned by explicit `this` or aliases copied from `this`; they are static hints, not proven C# field identity."
            )
            out.append("")
            out.append("| Step | Body line | Target | Value | ISIL line |")
            out.append("| ---: | ---: | --- | --- | --- |")
            for item in member_assignments:
                out.append(
                    f"| {item.step} | {item.line_number} | {markdown_table_code(item.target)} | "
                    f"{markdown_table_code(item.value)} | {markdown_table_code(item.line)} |"
                )
            if member_assignment_total > len(member_assignments):
                out.append("")
                out.append(
                    f"Shown: first {len(member_assignments)} ISIL inferred instance-member-looking assignments in order; "
                    f"{member_assignment_total - len(member_assignments)} additional assignments omitted."
                )

        branch_target_summaries, branch_target_total = collect_branch_target_summaries(method, 12)
        if branch_target_summaries:
            out.append("")
            out.append("ISIL branch target summary:")
            out.append("")
            out.append(
                "Targets are grouped by `ConditionalJump` destination; repeated targets often indicate common bailout or shared continuation paths, not reconstructed basic blocks."
            )
            out.append("")
            out.append("| Target | Observations | First body line | First condition context |")
            out.append("| --- | ---: | ---: | --- |")
            for summary in branch_target_summaries:
                context_lines = "<br>".join(markdown_table_code(line) for line in summary.first_lines)
                out.append(
                    f"| {markdown_table_code(summary.target)} | {summary.observations} | "
                    f"{summary.first_line_number} | {context_lines} |"
                )
            if branch_target_total > len(branch_target_summaries):
                out.append("")
                out.append(
                    f"Shown: {len(branch_target_summaries)} branch targets; "
                    f"{branch_target_total - len(branch_target_summaries)} additional targets omitted."
                )

        branch_contexts, branch_context_total = collect_branch_contexts(method, 12)
        if branch_contexts:
            out.append("")
            out.append("ISIL branch-condition contexts:")
            out.append("")
            out.append("| Target | Body line | First condition context |")
            out.append("| --- | ---: | --- |")
            for context in branch_contexts:
                context_lines = "<br>".join(markdown_code(line) for line in context.lines)
                out.append(
                    f"| {markdown_code(context.target)} | {context.line_number} | {context_lines} |"
                )
            if branch_context_total > len(branch_contexts):
                out.append("")
                out.append(
                    f"Shown: {len(branch_contexts)} conditional jumps; "
                    f"{branch_context_total - len(branch_contexts)} additional conditional jumps omitted."
                )

        return_contexts, return_context_total = collect_return_contexts(method, 8)
        if return_contexts:
            out.append("")
            out.append("ISIL return contexts:")
            out.append("")
            out.append("| Body line | Return expression | Nearby ISIL lines |")
            out.append("| ---: | --- | --- |")
            for context in return_contexts:
                context_lines = "<br>".join(markdown_table_code(line) for line in context.lines)
                out.append(
                    f"| {context.line_number} | {markdown_table_code(context.expression)} | {context_lines} |"
                )
            if return_context_total > len(return_contexts):
                out.append("")
                out.append(
                    f"Shown: {len(return_contexts)} return contexts; "
                    f"{return_context_total - len(return_contexts)} additional return observations omitted."
                )

        named_calls, resolved_calls, raw_calls = collect_calls(method, address_map)
        named_call_counts = collect_named_call_counts(method)
        readable_named_call_counts = build_readable_named_calls(named_call_counts)
        if named_call_counts:
            out.append("")
            out.append("Named call frequency:")
            out.append("")
            out.append("| Target | Target prefix | Observations |")
            out.append("| --- | --- | ---: |")
            for target, count in named_call_counts.most_common(12):
                out.append(
                    f"| {markdown_table_code(target)} | {markdown_table_code(named_call_owner(target))} | {count} |"
                )
            if len(named_call_counts) > 12:
                out.append("")
                out.append(
                    f"Shown: 12 named call targets; {len(named_call_counts) - 12} additional unique targets omitted."
                )
        if readable_named_call_counts:
            out.append("")
            out.append("Human-readable named call frequency:")
            out.append("")
            out.append(
                "Filters out global IL2CPP helpers and short obfuscated owner/member names; raw named calls remain in the full frequency table."
            )
            out.append("")
            out.append("| Target | Target prefix | Observations |")
            out.append("| --- | --- | ---: |")
            for target, count in readable_named_call_counts.most_common(12):
                out.append(
                    f"| {markdown_table_code(target)} | {markdown_table_code(named_call_owner(target))} | {count} |"
                )
            if len(readable_named_call_counts) > 12:
                out.append("")
                out.append(
                    f"Shown: 12 human-readable named call targets; "
                    f"{len(readable_named_call_counts) - 12} additional unique targets omitted."
                )

        call_sequence, call_sequence_total = collect_isil_call_sequence(method, address_map, 40)
        if call_sequence:
            out.append("")
            out.append("ISIL call sequence sketch:")
            out.append("")
            out.append(
                "Routine IL2CPP/helper setup calls are omitted here; use the frequency and resolved-context tables for those."
            )
            out.append("")
            out.append("| Step | Body line | Kind | Target | Call line |")
            out.append("| ---: | ---: | --- | --- | --- |")
            for item in call_sequence:
                out.append(
                    f"| {item.step} | {item.line_number} | {markdown_table_code(item.kind)} | "
                    f"{markdown_table_code(item.target)} | {markdown_table_code(item.line)} |"
                )
            if call_sequence_total > len(call_sequence):
                out.append("")
                out.append(
                    f"Shown: first {len(call_sequence)} ISIL call observations in order; "
                    f"{call_sequence_total - len(call_sequence)} additional call observations omitted."
                )

        if named_calls or resolved_calls or raw_calls:
            out.append("")
            out.append("Calls:")
            for call in named_calls[:25]:
                out.append(f"- {markdown_code(call)}")
            for call in resolved_calls[:25]:
                out.append(f"- resolved {markdown_code(call)}")
            for call in raw_calls[:25]:
                out.append(f"- unresolved {markdown_code(call)}")
            if len(named_calls) + len(resolved_calls) + len(raw_calls) > 75:
                out.append("- ...")

        named_contexts, named_context_total = collect_named_call_contexts(method, 12)
        if named_contexts:
            out.append("")
            out.append("Named call-site contexts:")
            out.append("")
            out.append("| Target | Body line | First call-site context |")
            out.append("| --- | ---: | --- |")
            for context in named_contexts:
                context_lines = "<br>".join(markdown_code(line) for line in context.lines)
                out.append(
                    f"| {markdown_code(context.target)} | {context.line_number} | {context_lines} |"
                )
            if named_context_total > len(named_contexts):
                out.append("")
                out.append(
                    f"Shown: {len(named_contexts)} unique named call targets; "
                    f"{named_context_total - len(named_contexts)} additional named call observations omitted."
                )

        readable_named_contexts, readable_named_context_total = collect_named_call_contexts(
            method,
            12,
            is_readable_named_call,
        )
        if readable_named_contexts:
            out.append("")
            out.append("Human-readable named call-site contexts:")
            out.append("")
            out.append("| Target | Body line | First call-site context |")
            out.append("| --- | ---: | --- |")
            for context in readable_named_contexts:
                context_lines = "<br>".join(markdown_code(line) for line in context.lines)
                out.append(
                    f"| {markdown_code(context.target)} | {context.line_number} | {context_lines} |"
                )
            if readable_named_context_total > len(readable_named_contexts):
                out.append("")
                out.append(
                    f"Shown: {len(readable_named_contexts)} unique human-readable named call targets; "
                    f"{readable_named_context_total - len(readable_named_contexts)} additional human-readable named call observations omitted."
                )

        resolved_contexts, resolved_context_total = collect_resolved_call_contexts(
            method,
            address_map,
            12,
        )
        if resolved_contexts:
            out.append("")
            out.append("Resolved address call-site contexts:")
            out.append("")
            out.append("| Address | Label | View | Body line | First call-site context |")
            out.append("| --- | --- | --- | ---: | --- |")
            for context in resolved_contexts:
                context_lines = "<br>".join(markdown_table_code(line) for line in context.lines)
                out.append(
                    f"| {markdown_table_code(context.address)} | {markdown_table_code(context.label)} | "
                    f"{markdown_table_code(context.view)} | {context.line_number} | {context_lines} |"
                )
            if resolved_context_total > len(resolved_contexts):
                out.append("")
                out.append(
                    f"Shown: {len(resolved_contexts)} unique resolved addresses; "
                    f"{resolved_context_total - len(resolved_contexts)} additional resolved call observations omitted."
                )

        unresolved_contexts, unresolved_context_total = collect_unresolved_call_contexts(
            method,
            address_map,
            12,
        )
        if unresolved_contexts:
            out.append("")
            out.append("Unresolved call-site contexts:")
            out.append("")
            out.append("| Address | View | Body line | First call-site context |")
            out.append("| --- | --- | ---: | --- |")
            for context in unresolved_contexts:
                context_lines = "<br>".join(markdown_code(line) for line in context.lines)
                out.append(
                    f"| {markdown_code(context.address)} | {markdown_code(context.view)} | "
                    f"{context.line_number} | {context_lines} |"
                )
            if unresolved_context_total > len(unresolved_contexts):
                out.append("")
                out.append(
                    f"Shown: {len(unresolved_contexts)} unique unresolved addresses; "
                    f"{unresolved_context_total - len(unresolved_contexts)} additional unresolved call observations omitted."
                )

        if not summary_only:
            out.append("")
            out.append("Annotated ISIL/disassembly:")
            out.append("")
            out.append("```text")
            body_lines = method.body
            if max_body_lines is not None and len(body_lines) > max_body_lines:
                body_lines = body_lines[:max_body_lines]
            for line in body_lines:
                out.append(annotate_line(line, fields, this_registers, address_map))
            if len(body_lines) < len(method.body):
                omitted = len(method.body) - len(body_lines)
                out.append(f"... truncated {omitted} lines; rerun with a larger --max-body-lines to inspect more.")
            out.append("```")
            out.append("")
        else:
            out.append("")

    return "\n".join(out).rstrip() + "\n"


def assert_experiment_safe_output(path: Path, allow_outside_experiment: bool) -> None:
    if allow_outside_experiment:
        return
    resolved = path.resolve()
    cwd = Path.cwd().resolve()
    allowed_roots = [
        (cwd / "experiments" / "cpp2il_readable_csharp").resolve(),
        (cwd / "tmp" / "cpp2il_experiment").resolve(),
    ]
    if any(resolved == root or root in resolved.parents for root in allowed_roots):
        return
    allowed_text = ", ".join(str(root) for root in allowed_roots)
    raise ValueError(
        "Refusing to write outside the Cpp2IL readable-C# experiment areas. "
        f"Allowed roots: {allowed_text}. Pass --allow-outside-experiment "
        "only for an intentional manual export."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Annotate Cpp2IL ISIL with diffable-cs field names."
    )
    parser.add_argument("--type", required=True, help="Fully-qualified type name")
    parser.add_argument("--method", help="Optional method name/signature filter")
    parser.add_argument("--diffable-root", type=Path, default=DEFAULT_DIFFABLE_ROOT)
    parser.add_argument("--isil-root", type=Path, default=DEFAULT_ISIL_ROOT)
    parser.add_argument("--address-map", type=Path, help="Optional address-map JSON from build_address_map.py")
    parser.add_argument("--out", type=Path, help="Markdown output path")
    parser.add_argument(
        "--max-body-lines",
        type=int,
        default=None,
        help="Maximum annotated body lines per method before truncating output.",
    )
    parser.add_argument(
        "--allow-outside-experiment",
        action="store_true",
        help="Allow writing outside the experiment/tmp Cpp2IL areas.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Write readable summaries and call lists without annotated body dumps.",
    )
    args = parser.parse_args()

    csharp_path = find_type_file(args.diffable_root, args.type, ".cs")
    isil_path = find_type_file(args.isil_root, args.type, ".txt")
    address_map = load_address_map(args.address_map)
    fields = parse_fields(csharp_path)
    all_methods = parse_methods(isil_path)
    methods = filter_methods(all_methods, args.method)
    if args.method and not methods:
        raise ValueError(f"No methods matched --method {args.method!r} on {args.type}")
    if args.max_body_lines is not None and args.max_body_lines < 1:
        raise ValueError("--max-body-lines must be positive when provided")
    markdown = render_markdown(
        args.type,
        csharp_path,
        isil_path,
        fields,
        methods,
        all_methods,
        args.max_body_lines,
        args.address_map,
        address_map,
        args.summary_only,
    )

    if args.out:
        assert_experiment_safe_output(args.out, args.allow_outside_experiment)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(markdown, encoding="utf-8")
    else:
        sys.stdout.write(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
