"""Address map + optional native disasm lookups (fail-closed when required)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AddressEntry:
    address: str
    kind: str
    label: str
    signature: str | None
    confidence: str
    raw: dict[str, Any]


def normalize_address(value: str) -> str:
    text = value.strip().lower().replace("h", "")
    if text.startswith("0x"):
        text = text[2:]
    text = text.lstrip("0") or "0"
    return "0x" + text.upper()


def load_address_map(path: Path) -> dict[str, AddressEntry]:
    if not path.is_file():
        raise FileNotFoundError(f"Address map missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or "addresses" not in data:
        raise ValueError(f"Address map root must contain 'addresses': {path}")
    addresses = data["addresses"]
    if not isinstance(addresses, dict):
        raise ValueError(f"Address map 'addresses' must be object: {path}")

    out: dict[str, AddressEntry] = {}
    for raw_addr, raw_entry in addresses.items():
        if not isinstance(raw_entry, dict):
            continue
        addr = normalize_address(str(raw_addr))
        kind = str(raw_entry.get("kind") or "unknown")
        label = str(
            raw_entry.get("label")
            or raw_entry.get("signature")
            or f"{raw_entry.get('type', '?')}::{raw_entry.get('method', '?')}"
        )
        out[addr] = AddressEntry(
            address=addr,
            kind=kind,
            label=label,
            signature=raw_entry.get("signature") if isinstance(raw_entry.get("signature"), str) else None,
            confidence=str(raw_entry.get("confidence") or "unknown"),
            raw=raw_entry,
        )
    return out


def find_method_address(
    address_map: dict[str, AddressEntry],
    *,
    type_name: str,
    method_name: str,
    method_id: str,
) -> AddressEntry | None:
    """Best-effort reverse lookup; returns None when absent (caller decides fail-closed)."""
    hits: list[AddressEntry] = []
    for entry in address_map.values():
        raw = entry.raw
        if str(raw.get("type") or "") != type_name:
            continue
        if str(raw.get("method") or "") != method_name:
            continue
        hits.append(entry)
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0]
    # Prefer signature containment of method_id bare name.
    for entry in hits:
        sig = entry.signature or ""
        if method_name in sig and type_name in sig:
            # Prefer exact param-count match via parentheses contents length heuristic.
            if sig.count(",") == method_id.count(","):
                return entry
    return hits[0]


def load_native_disasm_methods(path: Path) -> list[dict[str, Any]]:
    """Load native disasm methods[] without address-key collapse."""
    if not path.is_file():
        raise FileNotFoundError(f"Native disasm pack missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    methods = data.get("methods")
    if not isinstance(methods, list):
        raise ValueError(f"Native disasm pack missing methods[]: {path}")
    return [m for m in methods if isinstance(m, dict)]


def load_native_disasm_index(path: Path) -> dict[str, dict[str, Any]]:
    """
    Index native disasm methods by normalized address. Optional enrichment only.

    Warning: CompGen getters/setters can share identical bytes/VAs across types.
    Prefer load_native_disasm_methods + type/method indexing for CompGen identity.
    """
    out: dict[str, dict[str, Any]] = {}
    for method in load_native_disasm_methods(path):
        addr = method.get("address")
        if not isinstance(addr, str):
            continue
        out[normalize_address(addr)] = method
    return out
