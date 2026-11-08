#!/usr/bin/env python3
"""Disassemble exact native method ranges from a Cpp2IL method-pointer CSV.

This is static evidence only. It proves current native bytes and control-flow shape
for an imported method address/range; it does not recover managed semantics by itself.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import capstone
import pefile


def parse_int(value: str | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text, 0)
    except ValueError:
        return int(text, 16)


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def row_label(row: dict[str, str]) -> str:
    typ = row.get("type") or row.get("Type") or "-"
    method = row.get("method") or row.get("Method") or "-"
    sig = row.get("signature") or row.get("Signature") or ""
    return f"{typ}::{method}{sig}"


def matches(row: dict[str, str], patterns: list[str]) -> bool:
    if not patterns:
        return True
    text = "\n".join(str(v or "") for v in row.values()).lower()
    return any(p.lower() in text for p in patterns)


def bytes_for_rva(pe: pefile.PE, rva: int, size: int) -> bytes:
    offset = pe.get_offset_from_rva(rva)
    data = pe.__data__[offset : offset + size]
    if len(data) < size:
        raise ValueError(f"RVA 0x{rva:X} requested {size} bytes but only {len(data)} are available")
    return bytes(data)


def load_address_maps(paths: list[Path]) -> dict[str, dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = {}
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for address, meta in (data.get("addresses") or {}).items():
            labels[address.upper().replace("0X", "0x")] = meta
    return labels


def call_target_label(op_str: str, address_labels: dict[str, dict[str, Any]]) -> str | None:
    token = op_str.strip().split(" ", 1)[0].strip()
    if not token.startswith("0x"):
        return None
    key = token.upper().replace("0X", "0x")
    meta = address_labels.get(key)
    if not meta:
        return None
    typ = meta.get("type") or "-"
    method = meta.get("method") or "-"
    confidence = meta.get("confidence") or "-"
    return f"{typ}::{method} [{confidence}]"


def disassemble(pe_path: Path, rows: list[dict[str, str]], max_instructions: int, address_labels: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    address_labels = address_labels or {}
    pe = pefile.PE(str(pe_path), fast_load=True)
    image_base = int(pe.OPTIONAL_HEADER.ImageBase)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = False
    out_rows: list[dict[str, Any]] = []
    for row in rows:
        rva = parse_int(row.get("rva") or row.get("RVA"))
        va = parse_int(row.get("address") or row.get("Address"))
        length = parse_int(row.get("length") or row.get("Length"))
        if rva is None and va is not None:
            rva = va - image_base
        if va is None and rva is not None:
            va = image_base + rva
        if rva is None or va is None:
            out_rows.append({"row": row, "error": "missing address/rva"})
            continue
        if length is None or length <= 0:
            length = 128
        try:
            data = bytes_for_rva(pe, rva, length)
            instructions = []
            for idx, ins in enumerate(md.disasm(data, va)):
                if idx >= max_instructions:
                    break
                instructions.append({
                    "address": f"0x{ins.address:X}",
                    "offset": f"0x{ins.address - image_base:X}",
                    "mnemonic": ins.mnemonic,
                    "op_str": ins.op_str,
                    "size": ins.size,
                    "targetLabel": call_target_label(ins.op_str, address_labels) if ins.mnemonic == "call" else None,
                })
            out_rows.append({
                "label": row_label(row),
                "assembly": row.get("assembly") or row.get("Assembly"),
                "type": row.get("type") or row.get("Type"),
                "method": row.get("method") or row.get("Method"),
                "signature": row.get("signature") or row.get("Signature"),
                "address": f"0x{va:X}",
                "rva": f"0x{rva:X}",
                "length": length,
                "instructionCount": len(instructions),
                "instructions": instructions,
            })
        except Exception as ex:
            out_rows.append({
                "label": row_label(row),
                "address": f"0x{va:X}",
                "rva": f"0x{rva:X}",
                "length": length,
                "error": str(ex),
            })
    return {
        "schema": "native-method-disassembly.v1",
        "evidenceBoundary": "Static native byte disassembly from imported Cpp2IL method-pointer ranges. This proves current addresses and instruction shape, not managed semantic intent or runtime invocation order.",
        "gameAssembly": str(pe_path),
        "imageBase": f"0x{image_base:X}",
        "methods": out_rows,
    }


def write_md(data: dict[str, Any], path: Path, max_methods: int) -> None:
    lines = [
        "# Native Method Disassembly from Method Pointers",
        "",
        "Status: static-only. Runtime-unvalidated.",
        "",
        data["evidenceBoundary"],
        "",
        f"GameAssembly: `{data['gameAssembly']}`",
        f"Image base: `{data['imageBase']}`",
        f"Methods included: {len(data['methods'])}",
        "",
    ]
    for method in data["methods"][:max_methods]:
        label = method.get("label") or "unknown"
        lines.extend([
            f"## `{label}`",
            "",
            f"Address: `{method.get('address', '-')}`  RVA: `{method.get('rva', '-')}`  Length: `{method.get('length', '-')}`",
            "",
        ])
        if method.get("error"):
            lines.extend([f"Error: `{method['error']}`", ""])
            continue
        lines.extend(["| Address | Instruction | Known target |", "|---|---|---|"])
        for ins in method.get("instructions", []):
            text = f"{ins.get('mnemonic', '')} {ins.get('op_str', '')}".strip().replace("|", "\\|")
            target = ins.get("targetLabel") or ""
            lines.append(f"| `{ins.get('address')}` | `{text}` | {target} |")
        lines.append("")
    if len(data["methods"]) > max_methods:
        lines.append(f"{len(data['methods']) - max_methods} more methods omitted from Markdown; see JSON artifact.")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-assembly", type=Path, required=True)
    ap.add_argument("--import-map", type=Path, required=True)
    ap.add_argument("--contains", action="append", default=[])
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--max-instructions", type=int, default=80)
    ap.add_argument("--address-map", type=Path, action="append", default=[])
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--out-md", type=Path)
    args = ap.parse_args()

    rows = [r for r in load_rows(args.import_map) if matches(r, args.contains)]
    rows = rows[: args.limit]
    data = disassemble(args.game_assembly, rows, args.max_instructions, load_address_maps(args.address_map))
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        write_md(data, args.out_md, args.limit)
    print(json.dumps({"outJson": str(args.out_json), "outMd": str(args.out_md) if args.out_md else None, "methods": len(data["methods"]), "errors": sum(1 for m in data["methods"] if m.get("error"))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
