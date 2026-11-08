"""Build minimal write-body IR from Capstone asm when ISIL/CompGen synthesis is unavailable.

Fail-closed: never invent control flow. Emit one unresolved block whose instructions are
the annotated asm lines and whose calls are parsed from `; -> name` comments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from olden_cs_recovery.queue_store import to_iso, utc_now

_CALL_RE = re.compile(
    r"call\s+0x[0-9a-fA-F]+\s*;\s*->\s*(?P<target>[^\s(]+)",
)
_ADDR_RE = re.compile(r"^(?P<addr>0x[0-9a-fA-F]+):")


@dataclass(frozen=True)
class AsmCall:
    target: str
    raw: str
    index: int


def parse_capstone_asm(path: Path) -> tuple[list[dict[str, Any]], list[AsmCall]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    instructions: list[dict[str, Any]] = []
    calls: list[AsmCall] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        addr_m = _ADDR_RE.match(stripped)
        if not addr_m:
            continue
        idx = len(instructions)
        opcode = "asm"
        operands = stripped.split(":", 1)[-1].strip()
        if "\t" in operands:
            parts = operands.split("\t", 1)
            opcode = parts[0].strip() or "asm"
            operands = parts[1].strip() if len(parts) > 1 else ""
        instructions.append(
            {
                "index": idx,
                "opcode": opcode,
                "raw": stripped,
                "operands": operands,
            }
        )
        call_m = _CALL_RE.search(stripped)
        if call_m:
            calls.append(AsmCall(target=call_m.group("target"), raw=stripped, index=idx))
    if not instructions:
        raise ValueError(f"no Capstone instruction lines in {path}")
    return instructions, calls


def build_write_body_ir_from_asm(
    *,
    method_id: str,
    type_name: str,
    method_name: str,
    signature: str,
    asm_path: Path,
    sources: dict[str, Any],
    native_address: str | None = None,
) -> dict[str, Any]:
    instructions, asm_calls = parse_capstone_asm(asm_path)
    calls = [
        {
            "instruction_index": c.index,
            "kind": "named",
            "target_raw": c.target,
            "resolved_label": c.target,
            "resolved_signature": None,
        }
        for c in asm_calls
    ]
    unresolved = [
        {
            "code": "write_body_capstone_stub",
            "message": (
                "ISIL absent / CompGen synthesis unsupported. IR is Capstone-annotated call "
                "skeleton only; control flow, stores, and Il2Cpp helpers remain Unresolved."
            ),
            "detail": str(asm_path).replace("\\", "/"),
            "instruction_index": None,
        },
        {
            "code": "mandatory_unresolved_write_body",
            "message": (
                "Write-body lift must not invent CF; EquivTester must use field-delta "
                "live_execution oracle for bar C."
            ),
            "instruction_index": None,
        },
    ]
    asm_rel = sources.get("capstone_asm") or str(asm_path)
    return {
        "schema_version": 1,
        "method_id": method_id,
        "type_name": type_name,
        "method_name": method_name,
        "isil_signature": signature or method_id,
        "native_address": native_address,
        "isil_instruction_count": len(instructions),
        "disasm_line_count": len(instructions),
        "basic_blocks": [
            {
                "id": "bb0",
                "instructions": instructions,
                "successors": [
                    {
                        "kind": "unresolved",
                        "target": "unresolved_exit",
                        "reason": "Capstone stub — opaque branches not lifted",
                    }
                ],
                "terminator": "unresolved",
            }
        ],
        "calls": calls,
        "field_touches": [],
        "unresolved": unresolved,
        "sources": {
            "diffable_cs": sources["diffable_cs"],
            "isil": f"capstone_asm_stub:{asm_rel}",
            "address_map": sources.get("address_map"),
            "native_disasm": sources.get("native_disasm"),
        },
        "lifted_at": to_iso(utc_now()),
        "notes": (
            "Direct State write-body Capstone stub IR. Not equivalence-proven. "
            "Unresolved markers mandatory."
        ),
    }
