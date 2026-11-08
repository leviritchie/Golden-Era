#!/usr/bin/env python3
"""Validate no-compromise custom law handler registry coverage.

This is a static source-hygiene check. It compares the target family list to
the runtime handler slots so new target families cannot be added without an
explicit named runtime entry seam.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"
RUNTIME_PATH = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3CustomFactionLawRuntime.cs"
REGISTRY_PATH = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3CustomLawHandlerRegistry.cs"

RUNTIME_INDEX_RE = re.compile(r"internal\s+const\s+int\s+(?P<name>[A-Za-z0-9_]+Index)\s*=\s*(?P<value>\d+)\s*;")
SLOT_RE = re.compile(
    r"LawIndex\s*=\s*Homm3CustomFactionLawRuntime\.(?P<index>[A-Za-z0-9_]+Index)\s*,"
    r"\s*Packet\s*=\s*Homm3CustomLawPacketGate\.(?P<packet>[A-Za-z0-9_]+)\s*,"
    r"\s*HandlerKey\s*=\s*\"(?P<handler>[^\"]+)\"",
    re.DOTALL,
)

PACKET_CONSTANT_BY_VALUE = {
    "vision": "Vision",
    "committed-damage": "CommittedDamage",
    "counterattack": "Counterattack",
    "battle-action": "BattleAction",
    "reward-result": "RewardResult",
    "morale": "Morale",
    "spell-cooldown": "SpellCooldown",
    "construction": "Construction",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def load_target_families() -> dict[int, str]:
    doc = load_json(TARGETS_PATH)
    families = doc.get("families") if isinstance(doc, dict) else None
    if not isinstance(families, dict):
        raise ValueError(f"{TARGETS_PATH.relative_to(ROOT)} has no families object")
    result: dict[int, str] = {}
    for raw_index, family in families.items():
        try:
            index = int(raw_index)
        except ValueError as ex:
            raise ValueError(f"target family key is not an integer: {raw_index}") from ex
        if not isinstance(family, dict):
            raise ValueError(f"target family {raw_index} is not an object")
        packet = family.get("packet")
        if not isinstance(packet, str) or not packet:
            raise ValueError(f"target family {raw_index} has no packet")
        if packet not in PACKET_CONSTANT_BY_VALUE:
            raise ValueError(f"target family {raw_index} uses unknown packet {packet!r}")
        result[index] = packet
    return result


def parse_runtime_indices() -> dict[str, int]:
    text = RUNTIME_PATH.read_text(encoding="utf-8-sig")
    result: dict[str, int] = {}
    for match in RUNTIME_INDEX_RE.finditer(text):
        result[match.group("name")] = int(match.group("value"))
    if not result:
        raise ValueError(f"no runtime law index constants found in {RUNTIME_PATH.relative_to(ROOT)}")
    return result


def parse_handler_slots() -> list[dict[str, str]]:
    text = REGISTRY_PATH.read_text(encoding="utf-8-sig")
    slots: list[dict[str, str]] = []
    for match in SLOT_RE.finditer(text):
        slots.append(match.groupdict())
    if not slots:
        raise ValueError(f"no handler slots found in {REGISTRY_PATH.relative_to(ROOT)}")
    return slots


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate Homm3CustomLawHandlerRegistry slot coverage against custom_law_targets.json. "
            "This is static source hygiene only; it does not build or prove runtime behavior."
        )
    )
    parser.parse_args()

    try:
        families = load_target_families()
        runtime_indices = parse_runtime_indices()
        slots = parse_handler_slots()
    except (OSError, json.JSONDecodeError, ValueError) as ex:
        print(f"handler registry validation failed: {ex}", file=sys.stderr)
        return 1

    errors: list[str] = []
    seen_indices: dict[int, list[str]] = {}
    for slot in slots:
        index_name = slot["index"]
        if index_name not in runtime_indices:
            errors.append(f"handler {slot['handler']}: unknown runtime index constant {index_name}")
            continue
        law_index = runtime_indices[index_name]
        seen_indices.setdefault(law_index, []).append(slot["handler"])
        expected_packet = families.get(law_index)
        if expected_packet is None:
            errors.append(f"handler {slot['handler']}: law index {law_index} is not in target families")
            continue
        expected_packet_constant = PACKET_CONSTANT_BY_VALUE[expected_packet]
        if slot["packet"] != expected_packet_constant:
            errors.append(
                f"handler {slot['handler']}: packet constant {slot['packet']} does not match "
                f"target family packet {expected_packet!r} ({expected_packet_constant})"
            )

    for law_index, packet in sorted(families.items()):
        handlers = seen_indices.get(law_index, [])
        if not handlers:
            errors.append(f"target family law index {law_index} packet {packet!r} has no handler slot")
        elif len(handlers) > 1:
            errors.append(f"target family law index {law_index} has multiple handler slots: {', '.join(handlers)}")

    if errors:
        print("handler registry validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"handler registry validation passed ({len(families)} family slot(s))")
    print("Note: static pass does not prove build success or runtime law behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
