"""Parse DiffableCs shells for method declarations (fail-closed; no invented bodies)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# DiffableCs method lines look like:
#   public void bbx(object a, BattleEventArgs b) { }
#   public static CastMagicEventArgs bctq(eir a, eew b, int[] c) { }
#   public Type: Hex.Session.Battle.CastMagicEventArgs(...) { }
#   private static Type: edb() { }
# Constructors:  public Type: Namespace.Type(args) { }
# Methods:       public static Ret name(args) { }
_METHOD_LINE = re.compile(
    r"^\s*"
    r"(?:\[.*?\]\s*)*"
    r"(?P<mods>(?:(?:public|private|internal|protected|static|virtual|override|abstract|sealed|new|extern)\s+)+)"
    r"(?:"
    r"Type:\s*(?P<ctor_type>[\w.<>,\[\]`]+)\s*"
    r"|"
    r"(?P<ret>[\w.<>,\[\]`]+)\s+(?P<name>\w+)\s*"
    r")"
    r"\((?P<params>[^)]*)\)\s*"
    r"\{\s*\}\s*$"
)

_NAMESPACE = re.compile(r"^namespace\s+([\w.]+)\s*;?\s*$")
_CLASS = re.compile(r"^\s*(?:public|internal|private|protected)?\s*(?:static\s+)?(?:partial\s+)?class\s+(\w+)")


@dataclass(frozen=True)
class DiffableMethod:
    type_name: str
    method_name: str
    signature: str
    method_id: str
    source_path: Path
    source_line: int
    raw_line: str


def _normalize_param_types(params: str) -> str:
    parts: list[str] = []
    for raw in params.split(","):
        token = raw.strip()
        if not token:
            continue
        # Drop parameter name; keep type tokens (last whitespace-separated is name).
        bits = token.split()
        if len(bits) >= 2:
            type_bits = bits[:-1]
        else:
            type_bits = bits
        parts.append(" ".join(type_bits))
    return ",".join(parts)


def _method_id(type_name: str, method_name: str, params: str) -> str:
    return f"{type_name}::{method_name}({_normalize_param_types(params)})"


def parse_diffable_cs_file(path: Path) -> list[DiffableMethod]:
    if not path.is_file():
        raise FileNotFoundError(f"DiffableCs file missing: {path}")

    text = path.read_text(encoding="utf-8-sig")
    namespace = ""
    class_name: str | None = None
    methods: list[DiffableMethod] = []

    for line_no, line in enumerate(text.splitlines(), start=1):
        ns = _NAMESPACE.match(line)
        if ns:
            namespace = ns.group(1)
            continue
        cls = _CLASS.match(line)
        if cls:
            class_name = cls.group(1)
            continue

        match = _METHOD_LINE.match(line)
        if not match:
            continue

        # Skip event/property add/remove accessor shells that somehow match.
        stripped = line.strip()
        if stripped.startswith("add ") or stripped.startswith("remove ") or stripped.startswith("get ") or stripped.startswith("set "):
            continue

        if class_name is None:
            raise ValueError(f"{path}:{line_no}: method found before class declaration: {stripped}")

        type_name = f"{namespace}.{class_name}" if namespace else class_name
        ctor_type = match.group("ctor_type")
        name = match.group("name")
        params = match.group("params") or ""

        if ctor_type is not None:
            mods = match.group("mods") or ""
            method_name = ".cctor" if "static" in mods.split() else ".ctor"
        else:
            if not name:
                raise ValueError(f"{path}:{line_no}: method line missing name: {stripped}")
            method_name = name

        signature = stripped
        method_id = _method_id(type_name, method_name, params)
        methods.append(
            DiffableMethod(
                type_name=type_name,
                method_name=method_name,
                signature=signature,
                method_id=method_id,
                source_path=path,
                source_line=line_no,
                raw_line=stripped,
            )
        )

    return methods


def scan_battle_eventargs(diffable_hex_root: Path) -> list[DiffableMethod]:
    battle_dir = diffable_hex_root / "Hex" / "Session" / "Battle"
    if not battle_dir.is_dir():
        raise FileNotFoundError(
            f"Battle EventArgs directory missing: {battle_dir}. "
            "Regenerate DiffableCs or re-run seed after dumps exist."
        )
    files = sorted(battle_dir.glob("*EventArgs.cs"))
    if not files:
        raise FileNotFoundError(
            f"No *EventArgs.cs under {battle_dir}. "
            "DiffableCs tree is present but empty of EventArgs — fail closed."
        )
    out: list[DiffableMethod] = []
    for path in files:
        out.extend(parse_diffable_cs_file(path))
    if not out:
        raise ValueError(f"Parsed zero methods from EventArgs under {battle_dir}")
    return out


def scan_edb(diffable_hex_root: Path) -> list[DiffableMethod]:
    path = diffable_hex_root / "edb.cs"
    if not path.is_file():
        raise FileNotFoundError(
            f"edb.cs missing: {path}. Regenerate DiffableCs or re-run seed after dumps exist."
        )
    methods = parse_diffable_cs_file(path)
    if not methods:
        raise ValueError(f"Parsed zero methods from {path}")
    return methods
