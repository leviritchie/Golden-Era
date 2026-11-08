#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import DEFAULT_MANIFEST_DIR, Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "construction_building_category_contracts.json"
SOURCE_MECHANICS_DIR = ROOT / "custom_factions" / "source_mechanics"


def load_building_mechanics(_manifest_dir: Path) -> dict[str, dict[str, Any]]:
    mechanics: dict[str, dict[str, Any]] = {}
    for path in sorted(SOURCE_MECHANICS_DIR.glob("homm3_*.json")):
        doc = load_json(path)
        faction_sid = doc.get("factionSid") if isinstance(doc, dict) else None
        for entry in doc.get("mechanics", []) if isinstance(doc, dict) else []:
            if not isinstance(entry, dict) or entry.get("surface") != "building":
                continue
            mechanic_id = entry.get("id")
            if not isinstance(mechanic_id, str):
                continue
            mechanics[mechanic_id] = {
                "factionSid": faction_sid,
                "currentRows": entry.get("currentRows") if isinstance(entry.get("currentRows"), list) else [],
                "sourceFile": str(path.relative_to(ROOT)),
            }
    return mechanics


def eligible_tokens(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def validate_contracts(doc: Any, mechanics: dict[str, dict[str, Any]], validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("construction building category contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"schemaVersion must be 1, got {doc.get('schemaVersion')!r}")

    contracts = doc.get("contracts")
    if not isinstance(contracts, dict):
        validation.error("contracts must be an object keyed by faction SID")
        return

    concrete_mappings = 0
    for faction_sid, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{faction_sid}: contract must be an object")
            continue
        groups = contract.get("groups")
        missing_groups = contract.get("missingGroups", {})
        if not isinstance(groups, dict):
            validation.error(f"{faction_sid}.groups must be an object")
            continue
        if not isinstance(missing_groups, dict):
            validation.error(f"{faction_sid}.missingGroups must be an object")
            missing_groups = {}

        for token in eligible_tokens(contract.get("profileEligibleGroup")):
            concrete_entries = groups.get(token)
            has_concrete = isinstance(concrete_entries, list) and len(concrete_entries) > 0
            has_missing = isinstance(missing_groups.get(token), str) and bool(missing_groups[token].strip())
            if not has_concrete and not has_missing:
                validation.error(f"{faction_sid}: eligible group {token!r} has no concrete mapping or missingGroups explanation")

        for group, entries in sorted(groups.items()):
            if not isinstance(entries, list):
                validation.error(f"{faction_sid}.{group}: group entries must be a list")
                continue
            if len(entries) == 0:
                if group not in missing_groups:
                    validation.error(f"{faction_sid}.{group}: empty group must have missingGroups explanation")
                continue
            for index, entry in enumerate(entries):
                context = f"{faction_sid}.{group}[{index}]"
                if not isinstance(entry, dict):
                    validation.error(f"{context}: entry must be an object")
                    continue
                mechanic_id = entry.get("sourceMechanicId")
                current_row = entry.get("currentRow")
                if not isinstance(mechanic_id, str) or not mechanic_id:
                    validation.error(f"{context}: sourceMechanicId must be a non-empty string")
                    continue
                mechanic = mechanics.get(mechanic_id)
                if mechanic is None:
                    validation.error(f"{context}: no exact source_mechanics building id {mechanic_id!r}")
                    continue
                if mechanic.get("factionSid") != faction_sid:
                    validation.error(
                        f"{context}: mechanic faction mismatch, contract {faction_sid!r} source has {mechanic.get('factionSid')!r}"
                    )
                if current_row not in mechanic.get("currentRows", []):
                    validation.error(f"{context}: currentRow {current_row!r} not found in source mechanic currentRows")
                else:
                    concrete_mappings += 1

    if concrete_mappings == 0:
        validation.error("construction building category contracts contain no concrete mappings")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate source-authored construction building category contracts against exact source_mechanics currentRows."
        )
    )
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    mechanics = load_building_mechanics(args.manifest_dir)
    validate_contracts(doc, mechanics, validation)
    contract_count = len(doc.get("contracts", {})) if isinstance(doc, dict) else 0
    print(f"construction building category contracts: {contract_count} faction contract(s)")
    print(f"source building mechanics: {len(mechanics)} exact building mechanic(s)")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
