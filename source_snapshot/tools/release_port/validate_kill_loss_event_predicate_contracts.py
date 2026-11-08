#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "kill_loss_event_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"


def load_kill_loss_profiles(inventory_path: Path) -> dict[str, dict[str, Any]]:
    inventory = load_json(inventory_path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    profiles: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return profiles
    for row in rows:
        if not isinstance(row, dict):
            continue
        predicates = row.get("requiredPredicates")
        if not isinstance(predicates, list) or "RequiresKillOrLossEvent" not in predicates:
            continue
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            profiles[effect_key] = row
    return profiles


def validate_contracts(doc: Any, profiles: dict[str, dict[str, Any]], validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("kill/loss event predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"kill/loss event predicate contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresKillOrLossEventProfiles",
            "genericKillCounterForbidden",
            "friendlyLossMustBeSeparatedFromEnemyKill",
            "temporaryGatedLossMustBeSeparatedFromPermanentCasualty",
            "runtimeProofStillRequiredForGameplay",
        )
        for key in required_true:
            if policy.get(key) is not True:
                validation.error(f"policy.{key} must be true")

    required_runtime = doc.get("requiredRuntimeProof")
    if not isinstance(required_runtime, list) or not required_runtime:
        validation.error("requiredRuntimeProof must be a non-empty list")
    else:
        required_items = {
            "kill event semantic proof",
            "friendly loss event semantic proof",
            "temporary gated loss versus permanent casualty discriminator proof",
            "killer/victim owner correlation proof",
            "event-to-law-owner idempotence proof",
            "post-death action ordering proof",
        }
        actual_items = {item for item in required_runtime if isinstance(item, str)}
        for missing in sorted(required_items - actual_items):
            validation.error(f"requiredRuntimeProof missing {missing!r}")
        for item in required_runtime:
            if not isinstance(item, str) or not item:
                validation.error(f"requiredRuntimeProof entries must be non-empty strings, got {item!r}")

    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or not contracts:
        validation.error("contracts must be a non-empty object")
        return

    expected_keys = set(profiles)
    actual_keys = set(contracts)
    for missing in sorted(expected_keys - actual_keys):
        validation.error(f"{missing}: missing kill/loss event predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: kill/loss event predicate contract has no exact RequiresKillOrLossEvent profile")

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        for field in ("eventKinds", "correlationRequired", "forbiddenSubstitutes"):
            value = contract.get(field)
            if not isinstance(value, list) or not value:
                validation.error(f"{effect_key}: {field} must be a non-empty list")
                continue
            for item in value:
                if not isinstance(item, str) or not item:
                    validation.error(f"{effect_key}: {field} entries must be non-empty strings")
        notes = contract.get("notes")
        if not isinstance(notes, str) or not notes:
            validation.error(f"{effect_key}: notes must be a non-empty string")
        elif "proven" not in notes.lower() and "requires" not in notes.lower():
            validation.error(f"{effect_key}: notes must state the proof boundary")
        forbidden_text = "\n".join(
            str(item).lower() for item in contract.get("forbiddenSubstitutes", []) if isinstance(item, str)
        )
        if "any battle kill" not in forbidden_text and "any enemy kill" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject generic kill substitution")
        event_kinds = set(contract.get("eventKinds", [])) if isinstance(contract.get("eventKinds"), list) else set()
        if effect_key.startswith("inferno.") and "temporary-gated-loss" not in event_kinds:
            validation.error(f"{effect_key}: Inferno kill/loss contract must include temporary-gated-loss")
        if effect_key.startswith("stronghold.") and "damage-taken" not in event_kinds:
            validation.error(f"{effect_key}: Stronghold kill/loss contract must include damage-taken")
        if effect_key.startswith("rampart.") and "low-loss-battle" not in event_kinds:
            validation.error(f"{effect_key}: Rampart kill/loss contract must include low-loss-battle")
        if effect_key.startswith("cove.") and "plunder-or-reward" not in event_kinds:
            validation.error(f"{effect_key}: Cove kill/loss contract must include plunder-or-reward")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_kill_loss_profiles(args.inventory)
    validate_contracts(doc, profiles, validation)
    print(f"kill/loss event predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"RequiresKillOrLossEvent profiles: {len(profiles)} profile(s)")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
