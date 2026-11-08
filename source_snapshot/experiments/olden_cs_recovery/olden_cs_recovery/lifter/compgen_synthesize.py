"""Synthesize CompGen accessor ISIL from native disasm (fail-closed shapes only)."""

from __future__ import annotations

import re
from typing import Any

from olden_cs_recovery.lifter.isil_parse import FieldInfo, IsilInstruction, IsilMethodBlock

_WRITE_BARRIER = "180489F70"

_GETTER_QWORD = re.compile(
    r"^mov\s+(?:rax|eax),\s*(?:qword|dword)\s+ptr\s+\[rcx\s*\+\s*0x(?P<off>[0-9a-fA-F]+)\]\s*$",
    re.IGNORECASE,
)
_GETTER_BYTE = re.compile(
    r"^movzx\s+eax,\s*byte\s+ptr\s+\[rcx\s*\+\s*0x(?P<off>[0-9a-fA-F]+)\]\s*$",
    re.IGNORECASE,
)
_SETTER_QWORD = re.compile(
    r"^mov\s+qword\s+ptr\s+\[rcx\s*\+\s*0x(?P<off>[0-9a-fA-F]+)\],\s*rdx\s*$",
    re.IGNORECASE,
)
_SETTER_BYTE = re.compile(
    r"^mov\s+byte\s+ptr\s+\[rcx\s*\+\s*0x(?P<off>[0-9a-fA-F]+)\],\s*dl\s*$",
    re.IGNORECASE,
)
_ADD_RCX = re.compile(
    r"^add\s+rcx,\s*0x(?P<off>[0-9a-fA-F]+)\s*$",
    re.IGNORECASE,
)
_JMP_BARRIER = re.compile(
    r"^jmp\s+(?:0x)?(?P<addr>180489[fF]70)\s*$",
    re.IGNORECASE,
)


class CompGenSynthesizeError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _ins_text(ins: dict[str, Any]) -> str:
    return f"{ins.get('mnemonic', '')} {ins.get('op_str', '')}".strip()


def _field_token(offset: int, fields: dict[int, FieldInfo]) -> str:
    info = fields.get(offset)
    if info and info.name:
        # ISIL uses angle-bracket backing names when DiffableCs had <prop>k__BackingField.
        if info.name.startswith("_") and info.name.endswith("_k__BackingField"):
            prop = info.name[1 : -len("_k__BackingField")]
            return f"<{prop}>k__BackingField"
        return info.name
    return f"field_0x{offset:X}"


def synthesize_compgen_isil_from_native(
    *,
    type_name: str,
    method_name: str,
    method_id: str,
    native_method: dict[str, Any],
    fields: dict[int, FieldInfo],
) -> IsilMethodBlock:
    """
    Build an IsilMethodBlock for proven CompGen accessor shapes only:

    - getter: mov rax/eax,[rcx+off] ; ret   OR  movzx eax, byte [rcx+off] ; ret
    - ref setter: mov [rcx+off],rdx ; add rcx,off ; jmp write_barrier
    - bool setter: mov byte [rcx+off], dl ; ret

    Any other native shape fails closed.
    """
    instructions_raw = native_method.get("instructions")
    if not isinstance(instructions_raw, list) or not instructions_raw:
        raise CompGenSynthesizeError("native_disasm_empty", f"no instructions for {method_id}")

    texts = [_ins_text(i) for i in instructions_raw if isinstance(i, dict)]
    disasm_lines = [f"\t{t}" for t in texts]
    sig = str(native_method.get("signature") or method_id)

    # Getter shapes (exactly 2 instructions).
    if len(texts) == 2 and texts[1].lower() == "ret":
        m = _GETTER_QWORD.match(texts[0]) or _GETTER_BYTE.match(texts[0])
        if m:
            offset = int(m.group("off"), 16)
            token = _field_token(offset, fields)
            isil = [
                IsilInstruction(0, "Nop", "", "\t0 Nop"),
                IsilInstruction(
                    1,
                    "Return",
                    f"[this @ rcx+{offset:X}]",
                    f"\t1 Return [this @ rcx+{offset:X}] /* {token} */",
                ),
            ]
            return IsilMethodBlock(
                type_name=type_name,
                signature=sig,
                disasm_lines=disasm_lines,
                instructions=isil,
                source_path=None,
            )

    # Bool / byte setter without write barrier (exactly 2 instructions).
    if len(texts) == 2 and texts[1].lower() == "ret":
        m = _SETTER_BYTE.match(texts[0])
        if m:
            offset = int(m.group("off"), 16)
            token = _field_token(offset, fields)
            isil = [
                IsilInstruction(
                    0,
                    "Move",
                    f"this.{token}, a @ rdx",
                    f"\t0 Move this.{token}, a @ rdx /* +0x{offset:X} */",
                ),
                IsilInstruction(1, "Return", "", "\t1 Return"),
            ]
            return IsilMethodBlock(
                type_name=type_name,
                signature=sig,
                disasm_lines=disasm_lines,
                instructions=isil,
                source_path=None,
            )

    # Reference setter with Il2Cpp write barrier (exactly 3 instructions).
    if len(texts) == 3:
        m0 = _SETTER_QWORD.match(texts[0])
        m1 = _ADD_RCX.match(texts[1])
        m2 = _JMP_BARRIER.match(texts[2])
        if m0 and m1 and m2:
            offset = int(m0.group("off"), 16)
            add_off = int(m1.group("off"), 16)
            if offset != add_off:
                raise CompGenSynthesizeError(
                    "compgen_setter_offset_mismatch",
                    f"store offset 0x{offset:X} != add offset 0x{add_off:X} for {method_id}",
                )
            token = _field_token(offset, fields)
            isil = [
                IsilInstruction(
                    0,
                    "Move",
                    f"this.{token}, a @ rdx",
                    f"\t0 Move this.{token} (ref), a @ rdx /* +0x{offset:X} */",
                ),
                IsilInstruction(
                    1,
                    "Add",
                    f"v2 @ rcx_v1, this @ rcx, {offset}",
                    f"\t1 Add v2 @ rcx_v1, this @ rcx, {offset}",
                ),
                IsilInstruction(
                    2,
                    "Call",
                    f"{_WRITE_BARRIER}, v3 @ rax_v1, v2 @ rcx_v1, a @ rdx",
                    f"\t2 Call {_WRITE_BARRIER}, v3 @ rax_v1, v2 @ rcx_v1, a @ rdx",
                ),
                IsilInstruction(3, "Return", "", "\t3 Return"),
            ]
            return IsilMethodBlock(
                type_name=type_name,
                signature=sig,
                disasm_lines=disasm_lines,
                instructions=isil,
                source_path=None,
            )

    raise CompGenSynthesizeError(
        "compgen_shape_unsupported",
        (
            f"native disasm for {method_id} is not a proven CompGen getter/setter shape "
            f"({len(texts)} ins). Refuse synthesis rather than invent control flow."
        ),
    )


def find_native_method(
    native_index_by_type_method: dict[tuple[str, str], list[dict[str, Any]]],
    *,
    type_name: str,
    method_name: str,
    method_id: str,
) -> dict[str, Any] | None:
    hits = native_index_by_type_method.get((type_name, method_name)) or []
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0]
    # Prefer signature comma-count match against method_id.
    want_commas = method_id.count(",")
    for hit in hits:
        sig = str(hit.get("signature") or "")
        if sig.count(",") == want_commas:
            return hit
    return hits[0]


def index_native_disasm_by_type_method(
    native_disasm: dict[str, dict[str, Any]] | list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """
    Index by (type, method). Prefer a raw methods[] list over an address-keyed
    dict: CompGen thunks often share identical machine code / VA aliases, and
    address-only maps silently drop earlier type+method rows.
    """
    if isinstance(native_disasm, dict):
        methods_iter: list[dict[str, Any]] = [
            m for m in native_disasm.values() if isinstance(m, dict)
        ]
    else:
        methods_iter = [m for m in native_disasm if isinstance(m, dict)]
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for method in methods_iter:
        typ = str(method.get("type") or "")
        name = str(method.get("method") or "")
        if not typ or not name:
            continue
        out.setdefault((typ, name), []).append(method)
    return out
