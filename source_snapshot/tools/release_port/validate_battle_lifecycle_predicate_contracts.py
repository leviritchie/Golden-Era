#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "battle_lifecycle_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"


def load_lifecycle_profiles(inventory_path: Path) -> dict[str, dict[str, Any]]:
    inventory = load_json(inventory_path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    profiles: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return profiles
    for row in rows:
        if not isinstance(row, dict):
            continue
        predicates = row.get("requiredPredicates")
        if not isinstance(predicates, list) or "RequiresBattleStartOrRoundEvent" not in predicates:
            continue
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            profiles[effect_key] = row
    return profiles


def validate_contracts(doc: Any, profiles: dict[str, dict[str, Any]], validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("battle lifecycle predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"battle lifecycle predicate contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresBattleStartOrRoundEventProfiles",
            "genericBattleEventSubstitutionForbidden",
            "adventureDayMustBeSeparatedFromBattleRound",
            "battleStartMustBeSeparatedFromUnitTurnStart",
            "runtimeProofStillRequiredForGameplay",
        )
        for key in required_true:
            if policy.get(key) is not True:
                validation.error(f"policy.{key} must be true")

    required_runtime = doc.get("requiredRuntimeProof")
    required_items = {
        "battle start hook ordering proof",
        "round start hook ordering proof",
        "unit turn start hook ordering proof when used",
        "adventure day/calendar idempotence proof",
        "active law owner/rank proof in lifecycle context",
        "battle/session cleanup proof",
    }
    if not isinstance(required_runtime, list) or not required_runtime:
        validation.error("requiredRuntimeProof must be a non-empty list")
    else:
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
        validation.error(f"{missing}: missing battle lifecycle predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: battle lifecycle predicate contract has no exact RequiresBattleStartOrRoundEvent profile")

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        lifecycle_kinds = contract.get("lifecycleKinds")
        if not isinstance(lifecycle_kinds, list) or not lifecycle_kinds:
            validation.error(f"{effect_key}: lifecycleKinds must be a non-empty list")
            lifecycle_kinds = []
        for item in lifecycle_kinds:
            if not isinstance(item, str) or not item:
                validation.error(f"{effect_key}: lifecycleKinds entries must be non-empty strings")
        lifecycle_text = "\n".join(str(item).lower() for item in lifecycle_kinds if isinstance(item, str))
        if not any(token in lifecycle_text for token in ("battle-start", "round-start", "unit-turn", "adventure-day")):
            validation.error(f"{effect_key}: lifecycleKinds must name concrete lifecycle phase tokens")
        companion = contract.get("companionPredicates")
        if not isinstance(companion, list):
            validation.error(f"{effect_key}: companionPredicates must be a list")
            companion = []
        profile = profiles.get(effect_key)
        profile_preds = set(profile.get("requiredPredicates", [])) if isinstance(profile, dict) else set()
        for predicate in companion:
            if not isinstance(predicate, str) or not predicate:
                validation.error(f"{effect_key}: companionPredicates entries must be non-empty strings")
            elif predicate not in profile_preds:
                validation.error(f"{effect_key}: companion predicate {predicate!r} is not present on the profile row")
        forbidden = contract.get("forbiddenSubstitutes")
        if not isinstance(forbidden, list) or not forbidden:
            validation.error(f"{effect_key}: forbiddenSubstitutes must be a non-empty list")
            forbidden = []
        forbidden_text = "\n".join(str(item).lower() for item in forbidden if isinstance(item, str))
        if "any battle event" not in forbidden_text:
            validation.error(f"{effect_key}: forbiddenSubstitutes must reject generic battle event substitution")
        if effect_key.startswith(("castle.", "stronghold.")) and "generic day refresh" not in forbidden_text:
            validation.error(f"{effect_key}: astrology lifecycle contract must reject generic day refresh")
        if effect_key.startswith("conflux.") and "battle round treated as adventure day" not in forbidden_text:
            validation.error(f"{effect_key}: Conflux lifecycle contract must distinguish battle round from adventure day")
        if effect_key.startswith("cove.") and "passive all-ranged bonus" not in forbidden_text:
            validation.error(f"{effect_key}: Cove lifecycle contract must forbid passive all-ranged substitute")
        if effect_key.startswith("stronghold.") and "traditional spell cooldown" not in forbidden_text:
            validation.error(f"{effect_key}: Stronghold lifecycle contract must forbid traditional spell cooldown substitute")
        notes = contract.get("notes")
        if not isinstance(notes, str) or not notes:
            validation.error(f"{effect_key}: notes must be a non-empty string")
        elif "requires" not in notes.lower() or "remain" not in notes.lower():
            validation.error(f"{effect_key}: notes must state lifecycle requirement and remaining runtime boundary")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_lifecycle_profiles(args.inventory)
    validate_contracts(doc, profiles, validation)
    print(f"battle lifecycle predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"RequiresBattleStartOrRoundEvent effect keys: {len(profiles)} unique key(s)")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
