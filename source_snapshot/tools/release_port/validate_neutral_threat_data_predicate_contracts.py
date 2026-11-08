#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "neutral_threat_data_predicate_contracts.json"
DEFAULT_INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
PREDICATE = "RequiresNeutralThreatData"


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
        if isinstance(predicates, list) and PREDICATE in predicates:
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
        validation.error("neutral threat data predicate contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"neutral threat data predicate contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")
    policy = doc.get("policy")
    if not isinstance(policy, dict):
        validation.error("policy must be an object")
    else:
        required_true = (
            "effectKeysMustMatchRequiresNeutralThreatDataProfiles",
            "visionFamilyOnly",
            "neutralThreatMustComeFromNativeData",
            "localizedTextParsingForbidden",
            "runtimeProofStillRequiredForGameplay",
        )
        for key in required_true:
            if policy.get(key) is not True:
                validation.error(f"policy.{key} must be true")

    allowed_factions = doc.get("allowedFactions")
    expected_factions = ["homm3_cove", "homm3_dungeon", "homm3_stronghold"]
    if not isinstance(allowed_factions, list) or sorted(allowed_factions) != sorted(expected_factions):
        validation.error(f"allowedFactions must be exactly {expected_factions!r}")
        allowed_factions = []
    if doc.get("allowedFamily") != "Vision":
        validation.error("allowedFamily must be Vision")

    required_runtime = doc.get("requiredRuntimeProof")
    required_items = {
        "neutral stack object identity proof",
        "native threat or strength value proof",
        "native intention or join/fight disposition proof when intention is used",
        "hero proximity or area-scan context proof",
        "law-owner and observing-side correlation proof",
        "read-only preview versus fog reveal mutation boundary proof",
        "localized threat text exclusion proof",
        "idempotent per-scan or per-preview application proof",
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
        validation.error(f"{missing}: missing neutral threat data predicate contract")
    for extra in sorted(actual_keys - expected_keys):
        validation.error(f"{extra}: neutral threat data contract has no exact {PREDICATE} profile")

    for row in profiles:
        effect_key = row.get("effectKey")
        if row.get("family") != "Vision":
            validation.error(f"{effect_key}: {PREDICATE} must remain in Vision family")
        if row.get("factionSid") not in allowed_factions:
            validation.error(f"{effect_key}: {PREDICATE} faction {row.get('factionSid')!r} is outside expected scope")
        values = row.get("values")
        if not isinstance(values, dict):
            validation.error(f"{effect_key}: profile values must be an object")
            continue
        if not isinstance(values.get("TriggerContext"), str) or not values.get("TriggerContext"):
            validation.error(f"{effect_key}: neutral threat profiles must keep explicit TriggerContext")
        if not isinstance(values.get("RevealGroup"), str) or not values.get("RevealGroup"):
            validation.error(f"{effect_key}: neutral threat profiles must keep explicit RevealGroup")

    for effect_key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            validation.error(f"{effect_key}: contract must be an object")
            continue
        kinds = contract.get("neutralDataKinds")
        if not isinstance(kinds, list) or not kinds:
            validation.error(f"{effect_key}: neutralDataKinds must be a non-empty list")
            kinds = []
        kind_text = "\n".join(str(item).lower() for item in kinds if isinstance(item, str))
        if "native-neutral" not in kind_text:
            validation.error(f"{effect_key}: neutralDataKinds must require native neutral data")
        companion = contract.get("companionPredicates")
        if not isinstance(companion, list):
            validation.error(f"{effect_key}: companionPredicates must be a list")
            companion = []
        profile_preds: set[str] = set()
        for row in profiles:
            if row.get("effectKey") == effect_key and isinstance(row.get("requiredPredicates"), list):
                profile_preds.update(row["requiredPredicates"])
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
            "localized threat text parsed as neutral threat data",
            "object category allowlist counted as threat data",
            "fog reveal target counted as threat data",
            "weak or high-value label inferred without native strength value",
        )
        for phrase in required_forbidden:
            if phrase not in forbidden_text:
                validation.error(f"{effect_key}: forbiddenSubstitutes must reject {phrase!r}")
        if effect_key == "dungeon.neutral-intention-preview" and "read-only tooltip preview counted without native neutral data" not in forbidden_text:
            validation.error(f"{effect_key}: must reject tooltip-only neutral data substitutes")
        notes = contract.get("notes")
        if not isinstance(notes, str) or not notes:
            validation.error(f"{effect_key}: notes must be a non-empty string")
        elif "requires" not in notes.lower() or "native neutral" not in notes.lower():
            validation.error(f"{effect_key}: notes must state native neutral data boundary")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    profiles = load_profiles(args.inventory)
    validate_contracts(doc, profiles, validation)
    print(f"neutral threat data predicate contracts: {len(doc.get('contracts', {})) if isinstance(doc, dict) else 0} contract(s)")
    print(f"{PREDICATE} effect keys: {len(profile_effect_keys(profiles))} unique key(s)")
    print(f"{PREDICATE} profile rows: {len(profiles)}")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
