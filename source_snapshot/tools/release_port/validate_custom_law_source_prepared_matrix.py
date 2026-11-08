#!/usr/bin/env python3
"""Validate the source-prepared no-compromise custom law matrix.

This is a static hygiene check only. It proves that the implementation matrix
is internally consistent with the target family spec, packet proof ledger,
handler registry, and named source seams. It does not build the mod, register
Harmony patches, or prove runtime gameplay behavior.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CUSTOM_FACTIONS = ROOT / "custom_factions"
MOD_SOURCE = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"

MATRIX_PATH = CUSTOM_FACTIONS / "custom_law_source_prepared_matrix.json"
TARGETS_PATH = CUSTOM_FACTIONS / "custom_law_targets.json"
PACKET_PROOFS_PATH = CUSTOM_FACTIONS / "custom_law_packet_proofs.json"
RUNTIME_PATH = MOD_SOURCE / "Homm3CustomFactionLawRuntime.cs"
REGISTRY_PATH = MOD_SOURCE / "Homm3CustomLawHandlerRegistry.cs"

RUNTIME_INDEX_RE = re.compile(
    r"internal\s+const\s+int\s+(?P<name>[A-Za-z0-9_]+Index)\s*=\s*(?P<value>\d+)\s*;"
)
SLOT_RE = re.compile(
    r"LawIndex\s*=\s*Homm3CustomFactionLawRuntime\.(?P<index>[A-Za-z0-9_]+Index)\s*,"
    r"\s*Packet\s*=\s*Homm3CustomLawPacketGate\.(?P<packet>[A-Za-z0-9_]+)\s*,"
    r"\s*HandlerKey\s*=\s*\"(?P<handler>[^\"]+)\"",
    re.DOTALL,
)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def as_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not an object")
    return value


def parse_runtime_indices() -> dict[str, int]:
    text = RUNTIME_PATH.read_text(encoding="utf-8-sig")
    indices = {match.group("name"): int(match.group("value")) for match in RUNTIME_INDEX_RE.finditer(text)}
    if not indices:
        raise ValueError(f"no runtime law index constants found in {RUNTIME_PATH.relative_to(ROOT)}")
    return indices


def parse_handler_slots() -> dict[int, tuple[str, str]]:
    runtime_indices = parse_runtime_indices()
    text = REGISTRY_PATH.read_text(encoding="utf-8-sig")
    slots: dict[int, tuple[str, str]] = {}
    for match in SLOT_RE.finditer(text):
        index_name = match.group("index")
        if index_name not in runtime_indices:
            raise ValueError(f"handler slot references unknown runtime index constant {index_name}")
        law_index = runtime_indices[index_name]
        if law_index in slots:
            raise ValueError(f"multiple handler slots found for law index {law_index}")
        slots[law_index] = (match.group("handler"), match.group("packet"))
    if not slots:
        raise ValueError(f"no handler slots found in {REGISTRY_PATH.relative_to(ROOT)}")
    return slots


def split_source_names(value: Any, field: str, family_index: str) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"family {family_index}: {field} must be a non-empty string")
    names = [part.strip() for part in value.split("/") if part.strip()]
    if not names:
        raise ValueError(f"family {family_index}: {field} has no source names")
    return names


def validate_named_source_file(name: str, field: str, family_index: str, errors: list[str]) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        errors.append(f"family {family_index}: {field} source name {name!r} is not a simple C# type name")
        return
    path = MOD_SOURCE / f"{name}.cs"
    if not path.exists():
        errors.append(f"family {family_index}: {field} source file is missing: {path.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate custom_law_source_prepared_matrix.json against target families, packet proofs, "
            "handler slots, and named source files. This does not build or prove runtime behavior."
        )
    )
    parser.parse_args()

    try:
        matrix = as_object(load_json(MATRIX_PATH), str(MATRIX_PATH.relative_to(ROOT)))
        targets = as_object(load_json(TARGETS_PATH), str(TARGETS_PATH.relative_to(ROOT)))
        packet_proofs = as_object(load_json(PACKET_PROOFS_PATH), str(PACKET_PROOFS_PATH.relative_to(ROOT)))
        handler_slots = parse_handler_slots()
    except (OSError, json.JSONDecodeError, ValueError) as ex:
        print(f"source-prepared matrix validation failed: {ex}", file=sys.stderr)
        return 1

    errors: list[str] = []
    if matrix.get("schemaVersion") != 1:
        errors.append("matrix schemaVersion must be 1")
    if matrix.get("policy", {}).get("noFallbacks") is not True:
        errors.append("matrix policy.noFallbacks must be true")
    if matrix.get("policy", {}).get("gameplayRequiresPacketGate") is not True:
        errors.append("matrix policy.gameplayRequiresPacketGate must be true")

    matrix_families = as_object(matrix.get("families"), "matrix families")
    target_families = as_object(targets.get("families"), "target families")
    proof_packets = as_object(packet_proofs.get("packets"), "packet proof packets")

    if set(matrix_families.keys()) != set(target_families.keys()):
        missing = sorted(set(target_families.keys()) - set(matrix_families.keys()), key=int)
        extra = sorted(set(matrix_families.keys()) - set(target_families.keys()), key=int)
        if missing:
            errors.append("matrix missing target family indices: " + ", ".join(missing))
        if extra:
            errors.append("matrix has extra family indices: " + ", ".join(extra))

    seen_handlers: set[tuple[int, str]] = set()
    for raw_index in sorted(matrix_families.keys(), key=int):
        family = as_object(matrix_families[raw_index], f"matrix family {raw_index}")
        target_family = as_object(target_families.get(raw_index), f"target family {raw_index}")
        law_index = int(raw_index)

        if family.get("key") != target_family.get("key"):
            errors.append(
                f"family {raw_index}: key {family.get('key')!r} does not match target {target_family.get('key')!r}"
            )
        packet = family.get("packet")
        if packet != target_family.get("packet"):
            errors.append(
                f"family {raw_index}: packet {packet!r} does not match target {target_family.get('packet')!r}"
            )
        if packet not in proof_packets:
            errors.append(f"family {raw_index}: packet {packet!r} has no proof ledger entry")
            proof = None
        else:
            proof = as_object(proof_packets[packet], f"packet proof {packet}")

        handler = family.get("handler")
        if not isinstance(handler, str) or not handler:
            errors.append(f"family {raw_index}: handler must be a non-empty string")
        elif law_index not in handler_slots:
            errors.append(f"family {raw_index}: no handler registry slot exists for this law index")
        else:
            expected_handler, _packet_constant = handler_slots[law_index]
            if handler != expected_handler:
                errors.append(
                    f"family {raw_index}: handler {handler!r} does not match registry {expected_handler!r}"
                )
            handler_key = (law_index, handler)
            if handler_key in seen_handlers:
                errors.append(f"family {raw_index}: duplicate handler binding {handler!r}")
            seen_handlers.add(handler_key)

        source_prepared = family.get("sourcePrepared")
        if source_prepared not in (True, "partial"):
            errors.append(f"family {raw_index}: sourcePrepared must be true or 'partial'")

        current_capability = family.get("currentCapability")
        if not isinstance(current_capability, str) or not current_capability.strip():
            errors.append(f"family {raw_index}: currentCapability must be non-empty")

        blocked_by = family.get("blockedBy")
        if not isinstance(blocked_by, list) or not blocked_by:
            errors.append(f"family {raw_index}: blockedBy must be a non-empty list")
        else:
            for blocker in blocked_by:
                if not isinstance(blocker, str) or not blocker.strip():
                    errors.append(f"family {raw_index}: blockedBy entries must be non-empty strings")
            if proof is not None and proof.get("gameplayAllowed") is False:
                if "packet gameplayAllowed=false" not in blocked_by:
                    errors.append(
                        f"family {raw_index}: blockedBy must include 'packet gameplayAllowed=false' "
                        f"while packet {packet!r} is not promoted"
                    )

        try:
            adapters = split_source_names(family.get("adapter"), "adapter", raw_index)
            runtimes = split_source_names(family.get("runtime"), "runtime", raw_index)
        except ValueError as ex:
            errors.append(str(ex))
            continue

        for adapter in adapters:
            if not adapter.endswith("NativeAdapter"):
                errors.append(f"family {raw_index}: adapter {adapter!r} must end with NativeAdapter")
            validate_named_source_file(adapter, "adapter", raw_index, errors)
        for runtime in runtimes:
            if not runtime.endswith("Runtime"):
                errors.append(f"family {raw_index}: runtime {runtime!r} must end with Runtime")
            validate_named_source_file(runtime, "runtime", raw_index, errors)

    if errors:
        print("source-prepared matrix validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"source-prepared matrix validation passed ({len(matrix_families)} family seam(s))")
    print("Note: static pass does not prove build success or runtime law behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
