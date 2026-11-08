"""Parse ISIL dump files into method blocks (no control-flow invention)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

METHOD_HEADER_RE = re.compile(r"^Method:\s+(?P<signature>.+)$")
TYPE_HEADER_RE = re.compile(r"^Type:\s+(?P<type>.+)$")
ISIL_LINE_RE = re.compile(r"^\s*(?P<index>\d+)\s+(?P<opcode>\S+)(?:\s+(?P<operands>.*))?$")
# Ordinary fields plus CompilerGenerated backing fields:
#   private Unit <cfqf>k__BackingField; //Field offset: 0x30
# Recovered / oracle snapshots use _cfqf_k__BackingField.
FIELD_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|internal|static|readonly|const|"
    r"volatile|sealed|new|unsafe|event)\s+)*"
    r"(?P<type>[A-Za-z_][\w.`<>\[\], ?:]*)\s+"
    r"(?:"
    r"<(?P<backing_prop>[A-Za-z_][\w]*)>k__BackingField"
    r"|"
    r"(?P<name>@?[A-Za-z_][\w]*)"
    r")\s*;"
    r"\s*//Field offset:\s*0x(?P<offset>[0-9A-Fa-f]+)"
)

CONTROL_OPCODES = frozenset({"ConditionalJump", "Jump", "Return"})


@dataclass(frozen=True)
class FieldInfo:
    offset: int
    name: str
    type_name: str


@dataclass
class IsilInstruction:
    index: int
    opcode: str
    operands: str
    raw: str


@dataclass
class IsilMethodBlock:
    type_name: str
    signature: str
    disasm_lines: list[str] = field(default_factory=list)
    instructions: list[IsilInstruction] = field(default_factory=list)
    source_path: Path | None = None


_BASE_CLASS_RE = re.compile(r"class\s+\w+\s*:\s*(?P<base>[A-Za-z_][\w.]*)")
_TERMINAL_BASES = frozenset(
    {"EventArgs", "System.EventArgs", "object", "Object", "System.Object"}
)


def parse_diffable_fields(diffable_path: Path) -> dict[int, FieldInfo]:
    if not diffable_path.is_file():
        raise FileNotFoundError(f"DiffableCs missing: {diffable_path}")
    fields: dict[int, FieldInfo] = {}
    for line in diffable_path.read_text(encoding="utf-8-sig").splitlines():
        match = FIELD_RE.match(line)
        if not match:
            continue
        offset = int(match.group("offset"), 16)
        backing = match.group("backing_prop")
        if backing:
            name = f"_{backing}_k__BackingField"
        else:
            name = match.group("name")
        fields[offset] = FieldInfo(
            offset=offset,
            name=name,
            type_name=match.group("type"),
        )
    return fields


def detect_diffable_base_simple_name(diffable_path: Path) -> str | None:
    """Return unqualified DiffableCs base class name, or None at EventArgs/object."""
    if not diffable_path.is_file():
        return None
    for line in diffable_path.read_text(encoding="utf-8-sig").splitlines():
        match = _BASE_CLASS_RE.search(line)
        if not match:
            continue
        base = match.group("base")
        if base in _TERMINAL_BASES:
            return None
        return base.rsplit(".", 1)[-1]
    return None


def parse_diffable_fields_with_bases(diffable_path: Path) -> dict[int, FieldInfo]:
    """
    Merge own DiffableCs fields with evidenced base-class fields from sibling files.

    Walks `: Base` declarations in the same DiffableCs directory (e.g. StepEventArgs →
    BattleEventArgs). Base fields apply first; own fields win on offset collision.
    Does not invent fields — only offsets declared in DiffableCs.
    """
    chain: list[Path] = []
    current: Path | None = diffable_path
    seen: set[Path] = set()
    while current is not None:
        resolved = current.resolve()
        if resolved in seen:
            break
        if not current.is_file():
            break
        seen.add(resolved)
        chain.append(current)
        base_simple = detect_diffable_base_simple_name(current)
        if not base_simple:
            break
        sibling = current.parent / f"{base_simple}.cs"
        current = sibling if sibling.is_file() else None
    merged: dict[int, FieldInfo] = {}
    for path in reversed(chain):
        merged.update(parse_diffable_fields(path))
    return merged


def parse_isil_file(path: Path) -> list[IsilMethodBlock]:
    if not path.is_file():
        raise FileNotFoundError(f"ISIL dump missing: {path}")

    methods: list[IsilMethodBlock] = []
    current_type = ""
    current: IsilMethodBlock | None = None
    section: str | None = None  # "disasm" | "isil"

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        type_match = TYPE_HEADER_RE.match(line)
        if type_match:
            current_type = type_match.group("type").strip()
            continue

        method_match = METHOD_HEADER_RE.match(line)
        if method_match:
            if current is not None:
                methods.append(current)
            current = IsilMethodBlock(
                type_name=current_type,
                signature=method_match.group("signature").strip(),
                source_path=path,
            )
            section = None
            continue

        if current is None:
            continue

        stripped = line.strip()
        if stripped == "Disassembly:":
            section = "disasm"
            continue
        if stripped == "ISIL:":
            section = "isil"
            continue

        if section == "disasm":
            if stripped:
                current.disasm_lines.append(line.rstrip())
            continue

        if section == "isil":
            instr_match = ISIL_LINE_RE.match(line)
            if not instr_match:
                continue
            current.instructions.append(
                IsilInstruction(
                    index=int(instr_match.group("index")),
                    opcode=instr_match.group("opcode"),
                    operands=(instr_match.group("operands") or "").strip(),
                    raw=line.rstrip(),
                )
            )

    if current is not None:
        methods.append(current)
    return methods


def _normalize_type_token(token: str) -> str:
    text = token.strip()
    text = re.sub(r"\s+", "", text)
    # Strip generic arity markers and namespace prefixes for loose matching.
    text = text.replace("`1", "").replace("`2", "").replace("`3", "")
    if "<" in text:
        text = text.split("<", 1)[0]
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    text = text.lower()
    aliases = {
        "int32": "int",
        "int64": "long",
        "uint32": "uint",
        "uint64": "ulong",
        "boolean": "bool",
        "single": "float",
        "string": "string",
        "object": "object",
        "byte": "byte",
        "sbyte": "sbyte",
        "int16": "short",
        "uint16": "ushort",
        "char": "char",
        "void": "void",
    }
    # Handle arrays: int32[] -> int[]
    array_suffix = ""
    while text.endswith("[]"):
        array_suffix += "[]"
        text = text[:-2]
    text = aliases.get(text, text)
    return text + array_suffix


def _param_tokens_from_isil_signature(signature: str) -> list[str]:
    if "(" not in signature or not signature.endswith(")"):
        return []
    inside = signature[signature.find("(") + 1 : -1].strip()
    if not inside:
        return []
    parts: list[str] = []
    depth = 0
    current = []
    for ch in inside:
        if ch == "<":
            depth += 1
            current.append(ch)
        elif ch == ">":
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())

    out: list[str] = []
    for part in parts:
        bits = part.split()
        if not bits:
            continue
        # Drop trailing parameter name when present.
        if len(bits) >= 2 and re.match(r"^[@A-Za-z_]\w*$", bits[-1]):
            type_bits = bits[:-1]
        else:
            type_bits = bits
        out.append(_normalize_type_token(" ".join(type_bits)))
    return out


def _method_name_from_isil_signature(signature: str) -> str:
    head = signature.split("(", 1)[0].strip()
    # Preserve .ctor / .cctor — do not split those on '.'.
    if head.endswith(".ctor"):
        return ".ctor"
    if head.endswith(".cctor"):
        return ".cctor"
    return head.split()[-1].split(".")[-1]


def match_isil_method(
    methods: list[IsilMethodBlock],
    *,
    type_name: str,
    method_name: str,
    method_id: str,
) -> IsilMethodBlock:
    """Fail-closed exact-or-unique match of queue method_id to an ISIL block."""
    wanted_params = method_id[method_id.find("(") + 1 : method_id.rfind(")")] if "(" in method_id else ""
    wanted_tokens = [_normalize_type_token(p) for p in wanted_params.split(",") if p.strip()]

    typed = [m for m in methods if m.type_name == type_name]
    if not typed:
        raise LookupError(f"No ISIL methods for type {type_name!r}")

    named = [m for m in typed if _method_name_from_isil_signature(m.signature) == method_name]
    if not named:
        raise LookupError(
            f"No ISIL method named {method_name!r} on {type_name!r} "
            f"(have {[ _method_name_from_isil_signature(m.signature) for m in typed ]})"
        )

    if len(named) == 1:
        return named[0]

    scored: list[tuple[int, IsilMethodBlock]] = []
    for method in named:
        tokens = _param_tokens_from_isil_signature(method.signature)
        if len(tokens) != len(wanted_tokens):
            continue
        overlap = sum(1 for a, b in zip(tokens, wanted_tokens) if a == b or a in b or b in a)
        if overlap == len(wanted_tokens):
            scored.append((overlap, method))
    if len(scored) == 1:
        return scored[0][1]
    if not scored:
        raise LookupError(
            f"Ambiguous/unmatched ISIL overload for {method_id}. "
            f"Candidates: {[m.signature for m in named]}"
        )
    raise LookupError(
        f"Multiple ISIL overloads matched {method_id}: {[m.signature for _, m in scored]}"
    )
