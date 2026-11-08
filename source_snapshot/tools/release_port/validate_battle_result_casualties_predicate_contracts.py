#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "battle_result_casualties_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"


def load_profiles(inventory_path: Path) -> list[dict[str, Any]]:
    inventory = load_json(inventory_path)
    rows = inventory.get("rows") if isinstance(inventory, dict) else None
    profiles: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return profiles
    for row in rows:
        if not isinstance(row, dict):
            continue
        predicates = row.get("requiredPredicates")
        if isinstance(predicates, list) and "RequiresBattleResultCasualties" in predicates:
            profiles.append(row)
    return profiles


def profile_effect_keys(profiles: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for row in profiles:
        effect_key = row.get("effectKey")
        if isinstance(effect_key, str):
            result.add(effect_key)
    return result


def validate_contracts(doc: Any, profiles: list[dict[str, Any]], validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("battle result casualties predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"battle result casualties predicate contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresBattleResultCasualtiesProfiles",
            "rewardEconomyFamilyOnly",
            "battleResultMustBeCommittedPostBattleOutcome",
            "victoryAnimationOrRewardRowSubstituteForbidden",
            "runtimeProofStillRequiredForGameplay",
        )
        for key in required_true:
            if policy.get(key) is not True:
                validation.error(f"policy.{key} must be true")

    prefixes = doc.get("allowedEffectKeyPrefixes")
    expected_prefixes = ["fortress.", "rampart."]
    if not isinstance(prefixes, list) or sorted(prefixes) != sorted(expected_prefixes):
        validation.error(f"allowedEffectKeyPrefixes must be exactly {expected_prefixes!r}")
        prefixes = []

    required_runtime = doc.get("requiredRuntimeProof")
    required_items = {
        "committed battle result event proof",
        "winner and loser side proof",
        "friendly and enemy casualty count proof",
        "permanent casualty versus temporary loss proof",
        "low-loss threshold calculation proof",
        "reward commit ordering proof",
        "idempotent per-battle reward application proof",
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
    expected_keys = profile_effect_keys(profiles)
    actual_keys = set(contracts)
    for missing in sorted(expected_keys - actual_keys):
        validation.error(f"{missing}: missing battle result casualties predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: battle result casualties contract has no exact RequiresBattleResultCasualties profile")

    for row in profiles:
        effect_key = row.get("effectKey")
        if not isinstance(effect_key, str):
            validation.error(f"RequiresBattleResultCasualties profile has invalid effectKey {effect_key!r}")
        elif not any(effect_key.startswith(prefix) for prefix in prefixes):
            validation.error(f"{effect_key}: RequiresBattleResultCasualties is outside expected faction scope")
        if row.get("family") != "RewardEconomy":
            validation.error(f"{effect_key}: RequiresBattleResultCasualties must remain in RewardEconomy family")

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        casualty_kinds = contract.get("casualtyKinds")
        if not isinstance(casualty_kinds, list) or not casualty_kinds:
            validation.error(f"{effect_key}: casualtyKinds must be a non-empty list")
            casualty_kinds = []
        kind_text = "\n".join(str(item).lower() for item in casualty_kinds if isinstance(item, str))
        if "committed-post-battle-result-casualties" not in kind_text:
            validation.error(f"{effect_key}: casualtyKinds must require committed post-battle result casualties")
        companion = contract.get("companionPredicates")
        if not isinstance(companion, list):
            validation.error(f"{effect_key}: companionPredicates must be a list")
            companion = []
        matching_profiles = [row for row in profiles if row.get("effectKey") == effect_key]
        profile_preds = set()
        for row in matching_profiles:
            predicates = row.get("requiredPredicates")
            if isinstance(predicates, list):
                profile_preds.update(predicates)
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
        required_forbidden = (
            "battle victory animation counted as casualty result",
            "battle start or end notification counted as committed result",
            "reward row counted without battle result proof",
            "temporary summoned loss counted as permanent casualty",
        )
        for phrase in required_forbidden:
            if phrase not in forbidden_text:
                validation.error(f"{effect_key}: forbiddenSubstitutes must reject {phrase!r}")
        if effect_key.startswith("rampart.") and "low-loss assumed without casualty count proof" not in forbidden_text:
            validation.error(f"{effect_key}: Rampart low-loss laws must reject low-loss without casualty count proof")
        if effect_key.startswith("rampart.") and "Avenger mark counted without casualty result proof".lower() not in forbidden_text:
            validation.error(f"{effect_key}: Rampart Avenger laws must reject Avenger-only substitutes")
        notes = contract.get("notes")
        if not isinstance(notes, str) or not notes:
            validation.error(f"{effect_key}: notes must be a non-empty string")
        elif "requires" not in notes.lower() or "committed post-battle result casualties" not in notes.lower():
            validation.error(f"{effect_key}: notes must state committed post-battle result casualty boundary")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_profiles(args.inventory)
    validate_contracts(doc, profiles, validation)
    print(f"battle result casualties predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"RequiresBattleResultCasualties effect keys: {len(profile_effect_keys(profiles))} unique key(s)")
    print(f"RequiresBattleResultCasualties profile rows: {len(profiles)}")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())